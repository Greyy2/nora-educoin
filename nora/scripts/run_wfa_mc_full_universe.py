"""Pipeline WFA Rolling OOS & Monte Carlo toàn diện cho TOÀN BỘ Vũ Trụ Alpha (COIN + EDU).

BẢN CHẤT & TIÊU CHUẨN KỸ THUẬT:
1. Rerun Engine Nautilus COIN độc lập cho từng Fold OOS (Fold 1, Fold 2, Fold 3).
   - Fold 1: 2024-12-01 -> 2025-06-30
   - Fold 2: 2025-07-01 -> 2026-01-31
   - Fold 3: 2026-02-01 -> 2026-09-01
   - Tự động nạp warmup 20 ngày nến cho chỉ báo.
   - Bắt buộc close_at_end = True tại mốc kết thúc fold.
2. Trích xuất đường vốn NAV hàng ngày (Daily NAV Curve MTM 365 ngày, rf = 0).
3. Chạy Monte Carlo Stationary Bootstrap 10,000 kịch bản theo lãi kép thực tế (Politis & Romano 1994).
   - Đo xác suất P(MDD >= 15%) và P(MDD >= 20%).
4. Ghi nhận kết quả ở trạng thái technical dry-run; không xếp hạng hay quyết định alpha.
"""

import os
import sys
import glob
import json
import time
import hashlib
from importlib.metadata import version
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path("/home/vmc03/norabt").resolve()
COIN_ROOT = REPO_ROOT / "nora" / "coin"
EDU_ROOT = REPO_ROOT / "nora" / "edu"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))
os.environ["NORA_DIR"] = str(COIN_ROOT)
os.environ["NORA_LOCAL_DATA_ROOT"] = str(COIN_ROOT / "data")

from backend.jobs.tasks import run_book_backtest, run_custom
from backend.analys.metrics.metrics import daily_returns_from_curve
from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.compile import is_nautilus_native

FOLDS = [
    ("fold_1", "2024-12-01", "2025-06-30"),
    ("fold_2", "2025-07-01", "2026-01-31"),
    ("fold_3", "2026-02-01", "2026-09-01"),
]

def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def validate_universe(records: List[Dict[str, Any]], code_map: Dict[str, str]) -> None:
    """Reject malformed or non-compilable inputs before any fold is executed."""
    keys = [record.get("universe_key", record["id"]) for record in records]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Universe contains duplicate product-scoped record keys")
    missing = [
        record.get("universe_key", record["id"])
        for record in records
        if record.get("code_key") and not code_map.get(record["code_key"], "").strip()
    ]
    if missing:
        raise RuntimeError(f"Universe has missing source code: {', '.join(missing)}")
    compile_errors = []
    for record in records:
        code = code_map.get(record.get("code_key", ""))
        if not code:
            continue
        try:
            compile_code(code)
        except Exception as exc:
            compile_errors.append(f"{record.get('universe_key', record['id'])}: {exc}")
    if compile_errors:
        raise RuntimeError("Universe preflight compile failed:\n" + "\n".join(compile_errors))


def _underlying_symbol(symbol: str) -> str:
    normalized = str(symbol).split("@", 1)[0].upper()
    for suffix in ("-USDT-SWAP", "-USDT", "-PERP"):
        if normalized.endswith(suffix):
            return normalized[:-len(suffix)]
    return normalized


def data_manifest_provenance(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fingerprint every market manifest referenced by the discovered universe."""
    def as_symbols(value: Any) -> List[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    symbols = sorted({
        _underlying_symbol(symbol)
        for record in records
        for symbol in as_symbols(record.get("symbols"))
    })
    manifest_dir = COIN_ROOT / "data" / "market" / "okx" / "catalog" / "_manifest"
    entries: Dict[str, Dict[str, str]] = {}
    missing: List[str] = []
    for symbol in symbols:
        path = manifest_dir / f"{symbol}.json"
        if not path.is_file():
            missing.append(symbol)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries[symbol] = {
            "manifest_sha256": file_sha256(path),
            "catalog_digest": str(payload.get("quality", {}).get("catalog_digest") or ""),
        }
    fingerprint = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "symbols": symbols,
        "manifest_fingerprints": entries,
        "missing_symbols": missing,
        "fingerprint_sha256": fingerprint,
        "status": "COMPLETE" if not missing else "INCOMPLETE_MISSING_MANIFESTS",
    }


def source_provenance(code_map: Dict[str, str]) -> Dict[str, Any]:
    """Separate alpha-source hashes from implementation-source hashes."""
    implementation_paths = [
        Path(__file__),
        COIN_ROOT / "backend" / "jobs" / "tasks.py",
        COIN_ROOT / "backend" / "jobs" / "runner" / "backtest.py",
        COIN_ROOT / "backend" / "core" / "backtest.py",
        COIN_ROOT / "backend" / "core" / "engine.py",
        COIN_ROOT / "backend" / "core" / "strategy.py",
        COIN_ROOT / "backend" / "core" / "portfolio.py",
        COIN_ROOT / "backend" / "analys" / "alpha" / "code" / "plan.py",
        COIN_ROOT / "backend" / "analys" / "alpha" / "code" / "compile.py",
        COIN_ROOT / "backend" / "analys" / "alpha" / "code" / "route.py",
        COIN_ROOT / "backend" / "analys" / "param" / "params.py",
        COIN_ROOT / "backend" / "analys" / "metrics" / "metrics.py",
        COIN_ROOT / "backend" / "analys" / "metrics" / "trades.py",
        COIN_ROOT / "backend" / "data" / "data.py",
        COIN_ROOT / "backend" / "adapter" / "contracts.py",
        REPO_ROOT / "scripts" / "top_agents_proxy_catalog.py",
        EDU_ROOT / "data" / "alpha" / "education" / "canonical_templates.py",
        *[
            COIN_ROOT / "data" / "alpha" / "strategies" / f"{name}.py"
            for name in ("dca", "kema", "sideway")
        ],
    ]
    missing_implementation_paths = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in implementation_paths
        if not path.is_file()
    ]
    if missing_implementation_paths:
        raise RuntimeError(
            "Cannot fingerprint missing implementation sources: "
            + ", ".join(missing_implementation_paths)
        )
    implementation_hashes = {
        path.relative_to(REPO_ROOT).as_posix(): file_sha256(path)
        for path in implementation_paths
    }
    alpha_sources_sha256 = hashlib.sha256(
        "\n".join(
            f"{key}:{hashlib.sha256(value.encode()).hexdigest()}"
            for key, value in sorted(code_map.items())
        ).encode()
    ).hexdigest()
    implementation_sha256 = hashlib.sha256(
        json.dumps(implementation_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "alpha_sources_sha256": alpha_sources_sha256,
        "implementation_source_hashes": implementation_hashes,
        "implementation_sha256": implementation_sha256,
    }


def cohort_provenance(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    members = sorted(
        (
            {
                "universe_key": record["universe_key"],
                "code_key": record.get("code_key"),
                "category": record["category"],
                "venue": record["venue"],
                "timeframe": record.get("timeframe"),
                "symbols": record.get("symbols", []),
                "source_classification": record["source_classification"],
            }
            for record in records
        ),
        key=lambda member: member["universe_key"],
    )
    digest = hashlib.sha256(
        json.dumps(members, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"sha256": digest, "record_count": len(members), "members": members}


def resource_provenance() -> Dict[str, Any]:
    """Report the actual cgroup limit/peak when readable; never infer a cap from a wrapper label."""
    cgroup_path = None
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
            if line.startswith("0::"):
                cgroup_path = Path("/sys/fs/cgroup") / line.partition("::")[2].lstrip("/")
                break
    except OSError:
        pass

    details: Dict[str, Any] = {
        "wrapper_memory_limit_label": os.environ.get("NORA_MEM_LIMIT_LABEL"),
        "cgroup_status": "UNAVAILABLE",
        "memory_limit_bytes": None,
        "memory_peak_bytes": None,
    }
    if cgroup_path is None:
        return details

    try:
        limit_text = (cgroup_path / "memory.max").read_text(encoding="ascii").strip()
        peak_text = (cgroup_path / "memory.peak").read_text(encoding="ascii").strip()
        details["memory_limit_bytes"] = None if limit_text == "max" else int(limit_text)
        details["memory_peak_bytes"] = int(peak_text)
        details["cgroup_status"] = "LIMITED" if details["memory_limit_bytes"] is not None else "UNLIMITED"
    except (OSError, ValueError):
        details["cgroup_status"] = "UNAVAILABLE"
    return details


def git_provenance() -> Dict[str, Any]:
    import subprocess

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(REPO_ROOT),
        text=True,
    )
    return {
        "commit": commit,
        "worktree_dirty": bool(status.strip()),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def protocol_provenance() -> Dict[str, Any]:
    protocol = {
        "folds": FOLDS,
        "warmup_days": 20,
        "close_at_end": True,
        "execution_mode": "INDEPENDENT_ENGINE_RUN_PER_FOLD",
        "metric_calculation": "DAILY_EQUITY_RETURNS_MTM_365D_SHARPE",
        "monte_carlo_model": "COMPOUNDED_STATIONARY_BOOTSTRAP_DAILY_RETURNS",
        "monte_carlo_simulations": 10000,
        "monte_carlo_horizon_days": 365,
        "monte_carlo_block_days": [3, 5, 10],
        "monte_carlo_seed": 42,
        "status": "TECHNICAL_DRY_RUN_NOT_OWNER_APPROVED",
    }
    digest = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"sha256": digest, "definition": protocol}


def run_stationary_bootstrap_compounded(
    daily_returns: List[float],
    n_sims: int = 10000,
    block_days: int = 5,
    horizon_days: int = 365,
    seed: int = 42,
) -> Dict[str, Any]:
    """Stationary bootstrap (Politis & Romano 1994) trên chuỗi lợi suất ngày ghép lãi kép."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "simulations": n_sims,
            "block_days": block_days,
            "prob_mdd_ge_15_pct": None,
            "prob_mdd_ge_20_pct": None,
            "median_terminal_ret_pct": None,
            "mdd_p50_pct": None,
            "mdd_p95_pct": None,
        }

    rng = np.random.default_rng(seed)
    mdds = np.empty(n_sims)
    rets_mc = np.empty(n_sims)

    if block_days < 1:
        raise ValueError("block_days must be >= 1")
    continuation_probability = 1.0 - (1.0 / block_days)

    for k in range(n_sims):
        idx = np.empty(horizon_days, dtype=np.int64)
        idx[0] = rng.integers(0, len(d))
        for day in range(1, horizon_days):
            if rng.random() < continuation_probability:
                idx[day] = (idx[day - 1] + 1) % len(d)
            else:
                idx[day] = rng.integers(0, len(d))
        eq = np.cumprod(1.0 + d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets_mc[k] = eq[-1] - 1.0

    p_mdd_15 = float(np.mean(mdds >= 0.15) * 100.0)
    p_mdd_20 = float(np.mean(mdds >= 0.20) * 100.0)
    median_ret = float(np.median(rets_mc) * 100.0)
    p50_mdd = float(np.percentile(mdds, 50) * 100.0)
    p95_mdd = float(np.percentile(mdds, 95) * 100.0)

    return {
        "status": "COMPLETED",
        "simulations": n_sims,
        "block_days": block_days,
        "prob_mdd_ge_15_pct": round(p_mdd_15, 2),
        "prob_mdd_ge_20_pct": round(p_mdd_20, 2),
        "median_terminal_ret_pct": round(median_ret, 2),
        "mdd_p50_pct": round(p50_mdd, 2),
        "mdd_p95_pct": round(p95_mdd, 2),
    }

def run_single_alpha_fold(
    rec: Dict[str, Any],
    start_str: str,
    end_str: str,
    alpha_code_map: Dict[str, str],
) -> Dict[str, Any]:
    aid = rec["id"]
    cat = rec.get("category", "")
    source_class = rec.get("source_classification", "")
    symbols = rec.get("symbols", ["BTC-USDT"])
    if not symbols:
        symbols = ["BTC-USDT"]
    norm_symbols = []
    for s in symbols:
        clean_s = s.split("@")[0]
        if clean_s.endswith("PERP"):
            clean_s = clean_s[:-4]
        if not clean_s.endswith("-USDT"):
            clean_s = f"{clean_s}-USDT"
        norm_symbols.append(clean_s)
    symbols = norm_symbols
    timeframe = rec.get("timeframe") or "1h"

    # Nhánh 1: COIN System Leg hoặc Portfolio Combo
    if cat in ("COIN System Leg", "COIN Portfolio"):
        if aid == "combo_top3":
            leg_ids = ["kema_long", "dca_long", "dca_short"]
        elif aid == "combo_6_system_legs" or source_class == "PORTFOLIO_COMBO":
            leg_ids = ["kema_long", "kema_short", "sideway_long", "sideway_short", "dca_long", "dca_short"]
        else:
            leg_ids = [aid]

        params = {
            "strategies": [{"id": sid} for sid in leg_ids],
            "symbols": symbols[0] if isinstance(symbols, list) else symbols,
            "start": start_str,
            "end": end_str,
            "timeframe": timeframe,
        }
        res = run_book_backtest(params)
        curve = res.get("equity_curve", [])
        trades_count = res.get("trades", 0)
        ret_pct = res.get("ret_pct", 0.0)
        mdd_pct = res.get("mdd_pct", 0.0)
        trades_list = res.get("trade_list", [])
        fees_usd = res.get("fees_usd", 0.0)
        start_ms = res["config"]["start"]
        end_ms = res["config"]["end"]
        cap = res["config"]["initial_capital"]
        daily_rets = daily_returns_from_curve(curve, start_ms, cap, end_ms)

    # Nhánh 2: Custom DSL (User V2, Top Agent, EDU Canonical, EDU User)
    else:
        code_key = rec.get("code_key", aid)
        code_text = alpha_code_map.get(code_key, "")
        if not code_text:
            raise RuntimeError(f"Missing source code for {rec.get('universe_key', aid)} ({code_key})")
        params = {
            "code": code_text,
            "symbols": symbols,
            "start": start_str,
            "end": end_str,
            "train_ratio": 0.8,
            "initial_capital": 10000.0,
            "run_frame": timeframe,
            "close_at_end": True,
        }
        res = run_custom(params)
        sim = res.get("metrics", {}).get("simulate", {})
        trades_list = res.get("trades", []) or res.get("trade_list", [])
        trades_count = len(trades_list)
        ret_pct = sim.get("ret_pct", 0.0)
        mdd_pct = sim.get("mdd_pct", 0.0)
        fees_usd = sim.get("fees_usd", 0.0)
        series_data = res.get("series", {})
        times = series_data.get("times", [])
        equities = series_data.get("equity", [])
        curve = [{"time": t * 1000, "equity": eq, "equity_worst": eq} for t, eq in zip(times, equities)]

        from backend.analys.param import date_ms, DAY_MS
        start_ms = date_ms(start_str)
        end_ms = date_ms(end_str) + DAY_MS
        daily_rets = daily_returns_from_curve(curve, start_ms, 10000.0, end_ms)

    mean_d = float(np.mean(daily_rets)) if len(daily_rets) else 0.0
    std_d = float(np.std(daily_rets)) if len(daily_rets) else 0.0
    daily_sr = (mean_d / std_d * np.sqrt(365)) if std_d > 0 else 0.0

    return {
        "period": f"{start_str} -> {end_str}",
        "trades": trades_count,
        "ret_pct": round(ret_pct, 2),
        "mdd_pct": round(mdd_pct, 2),
        "fees_usd": round(fees_usd, 2),
        "daily_sharpe": round(daily_sr, 2),
        "days_count": len(daily_rets),
        "daily_returns": daily_rets,
        "trades_list": trades_list,
    }

def discover_full_universe() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Tự động khám phá toàn bộ vũ trụ alpha trong repo."""
    records = []
    code_map = {}

    # 1. COIN System Legs & Combos
    system_legs = [
        ("kema_long", "System Leg kema_long", "COIN System Leg", "FIXED_PARAM_ROLLING_OOS", "1h"),
        ("kema_short", "System Leg kema_short", "COIN System Leg", "FIXED_PARAM_ROLLING_OOS", "1h"),
        ("sideway_long", "System Leg sideway_long", "COIN System Leg", "LOW_SAMPLE_CRITICAL", "1h"),
        ("sideway_short", "System Leg sideway_short", "COIN System Leg", "LOW_SAMPLE_CRITICAL", "1h"),
        ("dca_long", "System Leg dca_long", "COIN System Leg", "FIXED_PARAM_ROLLING_OOS", "1h"),
        ("dca_short", "System Leg dca_short", "COIN System Leg", "FIXED_PARAM_ROLLING_OOS", "1h"),
        ("combo_6_system_legs", "Portfolio Combo 6 Legs", "COIN Portfolio", "PORTFOLIO_COMBO", "1h"),
        ("combo_top3", "Portfolio Combo Top 3", "COIN Portfolio", "PORTFOLIO_COMBO", "1h"),
    ]
    for aid, name, cat, sclass, tf in system_legs:
        records.append({
            "id": aid,
            "universe_key": f"coin-system:{aid}",
            "name": name,
            "venue": "coin",
            "category": cat,
            "source_classification": sclass,
            "wfa_method_assigned": "PORTFOLIO_ROLLING_OOS" if sclass == "PORTFOLIO_COMBO" else "FIXED_PARAM_ROLLING_OOS",
            "timeframe": tf,
            "symbols": ["BTC"],
        })

    # 2. COIN User Alphas
    coin_user_files = sorted(glob.glob(str(COIN_ROOT / "data" / "alpha" / "user" / "*.json")))
    for uf in coin_user_files:
        try:
            d = json.loads(Path(uf).read_text(encoding="utf-8"))
            uid = d.get("id") or Path(uf).stem
            code = d.get("code", "")
            code_key = f"coin-user:{uid}"
            code_map[code_key] = code
            is_native = bool(d.get("config", {}).get("is_native")) or is_nautilus_native(code)
            records.append({
                "id": uid,
                "universe_key": code_key,
                "code_key": code_key,
                "name": d.get("name") or uid,
                "venue": "coin",
                "category": "COIN Native Research" if is_native else ("COIN User V2" if "_v2" in uid else "COIN User"),
                "source_classification": "RESEARCH_NATIVE_NO_DECISION" if is_native else "FIXED_PARAM_ROLLING_OOS",
                "wfa_method_assigned": "RESEARCH_ONLY_NO_DECISION" if is_native else "FIXED_PARAM_ROLLING_OOS",
                "timeframe": d.get("config", {}).get("timeframe") or "1h",
                "symbols": d.get("config", {}).get("symbols", ["BTC-USDT"]),
            })
        except Exception as exc:
            raise RuntimeError(f"Cannot discover COIN alpha source {uf}: {exc}") from exc

    # 3. Top Agent OKX Proxies (từ scripts/top_agents_proxy_catalog.py ngoài core)
    from scripts.top_agents_proxy_catalog import TOP_AGENT_PROXY_CODES
    for tid, code in TOP_AGENT_PROXY_CODES.items():
        code_key = f"coin-proxy:{tid}"
        code_map[code_key] = code
        records.append({
            "id": tid,
            "universe_key": code_key,
            "code_key": code_key,
            "name": f"OKX Top Agent {tid} (Proxy)",
            "venue": "coin",
            "category": "COIN Top Agent",
            "source_classification": "PROXY_ENTRY_RESEARCH_ONLY",
            "wfa_method_assigned": "RESEARCH_ONLY_NO_DECISION",
            "timeframe": "15m" if "dahlia" in tid else "1h",
            "symbols": ["BTC"],
        })

    # 4. EDU Canonical Templates
    sys.path.insert(0, str(EDU_ROOT))
    from nora.edu.data.alpha.education.canonical_templates import CANONICAL_TEMPLATES
    for t in CANONICAL_TEMPLATES:
        code_key = f"edu-canonical:{t['id']}"
        code_map[code_key] = t["code"]
        records.append({
            "id": t["id"],
            "universe_key": code_key,
            "code_key": code_key,
            "name": t.get("name") or t["id"],
            "venue": "edu",
            "category": "EDU Canonical",
            "source_classification": "FIXED_PARAM_ROLLING_OOS",
            "wfa_method_assigned": "FIXED_PARAM_ROLLING_OOS",
            "timeframe": "1h",
            "symbols": ["BTC"],
        })

    # 5. EDU User Alphas (Full 75)
    edu_user_files = sorted(glob.glob(str(EDU_ROOT / "data" / "alpha" / "user" / "*.json")))
    for uf in edu_user_files:
        try:
            d = json.loads(Path(uf).read_text(encoding="utf-8"))
            uid = d.get("id") or Path(uf).stem
            code = d.get("code", "")
            code_key = f"edu-user:{uid}"
            code_map[code_key] = code
            records.append({
                "id": uid,
                "universe_key": code_key,
                "code_key": code_key,
                "name": d.get("name") or uid,
                "venue": "edu",
                "category": "EDU User",
                "source_classification": "FIXED_PARAM_ROLLING_OOS",
                "wfa_method_assigned": "FIXED_PARAM_ROLLING_OOS",
                "timeframe": d.get("config", {}).get("timeframe") or "1h",
                "symbols": d.get("config", {}).get("symbols", ["BTC-USDT"]),
            })
        except Exception as exc:
            raise RuntimeError(f"Cannot discover EDU alpha source {uf}: {exc}") from exc

    return records, code_map

def main():
    print("=" * 80)
    print("BẮT ĐẦU TECHNICAL DRY-RUN: FULL VŨ TRỤ ALPHA (COIN + EDU)")
    print("Engine COIN Nautilus | close_at_end=True | Stationary Bootstrap 10k")
    print("=" * 80, flush=True)

    records, alpha_code_map = discover_full_universe()
    total_alphas = len(records)
    print(f"-> Tổng số alpha được khám phá trong vũ trụ: {total_alphas} alphas.")
    validate_universe(records, alpha_code_map)
    data_prov = data_manifest_provenance(records)
    if data_prov["missing_symbols"]:
        raise RuntimeError(
            "Missing market manifests for universe symbols: "
            + ", ".join(data_prov["missing_symbols"])
        )
    source_prov = source_provenance(alpha_code_map)
    cohort_prov = cohort_provenance(records)
    git_prov = git_provenance()

    results = []
    t_pipeline_start = time.time()

    for idx, rec in enumerate(records, 1):
        aid = rec["id"]
        source_class = rec["source_classification"]
        wfa_method = rec["wfa_method_assigned"]
        print(f"\n[{idx:02d}/{total_alphas}] Đang xử lý `{rec['universe_key']}` ({rec['category']})...", flush=True)

        if source_class == "RESEARCH_NATIVE_NO_DECISION":
            empty_fold = {
                "period": "NOT_RUN_RESEARCH_NATIVE",
                "trades": None,
                "ret_pct": None,
                "mdd_pct": None,
                "fees_usd": None,
                "daily_sharpe": None,
                "days_count": None,
                "status": "NOT_RUN",
                "reason": "Native research source requires a deterministic backtest adapter and replay-only data; current Proxima lifecycle performs live REST warmup.",
            }
            results.append({
                "id": aid,
                "universe_key": rec["universe_key"],
                "code_key": rec.get("code_key"),
                "name": rec["name"],
                "venue": rec["venue"],
                "category": rec.get("category", ""),
                "source_classification": source_class,
                "wfa_method_assigned": wfa_method,
                "total_agg_oos_trades": None,
                "total_fees_usd": None,
                "folds_metrics": {"fold_1": empty_fold, "fold_2": empty_fold, "fold_3": empty_fold},
                "aggregated_oos_metrics": {
                    "trades": None,
                    "folds_positive_count": None,
                    "consistency": "NOT_RUN",
                    "cum_return_pct": None,
                    "mdd_pct": None,
                    "daily_sharpe": None,
                    "days_count": None,
                },
                "monte_carlo_block_bootstrap": {
                    "base_block_5": {"status": "NOT_RUN", "reason": "No deterministic replay adapter"},
                    "sensitivity_block_3": {"status": "NOT_RUN"},
                    "sensitivity_block_10": {"status": "NOT_RUN"},
                },
                "technical_dry_run_disposition": "RESEARCH_NATIVE_NO_DECISION",
                "disposition_reason": "Native research alpha is excluded until its live REST warmup is replaced by a deterministic catalog/replay data adapter.",
                "execution_status": "NOT_RUN",
                "execution_time_seconds": 0.0,
            })
            continue

        fold_results = {}
        agg_daily_returns = []
        total_oos_trades = 0
        total_fees = 0.0
        all_oos_trades = []

        t_alpha_start = time.time()
        for fname, s_str, e_str in FOLDS:
            print(f"  -> Running {fname} ({s_str} -> {e_str})...", end="", flush=True)
            t_f0 = time.time()
            try:
                f_out = run_single_alpha_fold(rec, s_str, e_str, alpha_code_map)
                fold_results[fname] = {
                    "period": f_out["period"],
                    "status": "COMPLETED",
                    "trades": f_out["trades"],
                    "ret_pct": f_out["ret_pct"],
                    "mdd_pct": f_out["mdd_pct"],
                    "fees_usd": f_out["fees_usd"],
                    "daily_sharpe": f_out["daily_sharpe"],
                    "days_count": f_out["days_count"],
                }
                agg_daily_returns.extend(f_out["daily_returns"])
                total_oos_trades += f_out["trades"]
                total_fees += f_out["fees_usd"]
                all_oos_trades.extend(f_out["trades_list"])
                print(f" Done ({time.time()-t_f0:.1f}s, Trades={f_out['trades']}, Ret={f_out['ret_pct']:+.2f}%, Sharpe={f_out['daily_sharpe']:.2f})", flush=True)
            except Exception as e:
                raise RuntimeError(f"{aid} {fname} failed; aborting instead of recording zero-result: {e}") from e

        folds_positive_count = sum(1 for f in fold_results.values() if f.get("ret_pct", 0) > 0)

        if len(agg_daily_returns):
            cum_ret = float(np.prod(1.0 + np.asarray(agg_daily_returns)) - 1.0) * 100.0
            cum_eq = np.cumprod(1.0 + np.asarray(agg_daily_returns))
            cum_peak = np.maximum.accumulate(np.r_[1.0, cum_eq])[1:]
            agg_mdd = float(np.max((cum_peak - cum_eq) / cum_peak) * 100.0) if len(cum_eq) else 0.0
            mean_d = float(np.mean(agg_daily_returns))
            std_d = float(np.std(agg_daily_returns))
            agg_daily_sr = float(mean_d / std_d * np.sqrt(365)) if std_d > 0 else 0.0
        else:
            cum_ret = 0.0
            agg_mdd = 0.0
            agg_daily_sr = 0.0

        mc_res = run_stationary_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=5)
        mc_sens_3 = run_stationary_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=3)
        mc_sens_10 = run_stationary_bootstrap_compounded(agg_daily_returns, n_sims=10000, block_days=10)

        # This is descriptive run status only; no owner-approved acceptance thresholds exist.
        if source_class == "PORTFOLIO_COMBO":
            dry_run_disposition = "PORTFOLIO_COMBO_TECHNICAL_ONLY"
            disposition_reason = "Portfolio output is recorded separately and is not an alpha decision."
        elif wfa_method == "RESEARCH_ONLY_NO_DECISION":
            dry_run_disposition = "RESEARCH_PROXY_NO_DECISION"
            disposition_reason = "Proxy entry logic is research-only; metrics are technical observations, not alpha evidence."
        else:
            dry_run_disposition = "TECHNICAL_DRY_RUN_COMPLETED"
            disposition_reason = "Metrics are descriptive only; owner-approved evaluation protocol is not set."

        res_record = {
            "id": aid,
            "universe_key": rec["universe_key"],
            "code_key": rec.get("code_key"),
            "name": rec["name"],
            "venue": rec["venue"],
            "category": rec.get("category", ""),
            "source_classification": source_class,
            "wfa_method_assigned": wfa_method,
            "total_agg_oos_trades": total_oos_trades,
            "total_fees_usd": round(total_fees, 2),
            "folds_metrics": fold_results,
            "aggregated_oos_metrics": {
                "trades": total_oos_trades,
                "folds_positive_count": folds_positive_count,
                "consistency": f"{folds_positive_count}/3 Folds Positive",
                "cum_return_pct": round(cum_ret, 2),
                "mdd_pct": round(agg_mdd, 2),
                "daily_sharpe": round(agg_daily_sr, 2),
                "days_count": len(agg_daily_returns),
            },
            "monte_carlo_block_bootstrap": {
                "base_block_5": mc_res,
                "sensitivity_block_3": mc_sens_3,
                "sensitivity_block_10": mc_sens_10,
            },
            "technical_dry_run_disposition": dry_run_disposition,
            "disposition_reason": disposition_reason,
            "execution_status": "COMPLETED",
            "execution_time_seconds": round(time.time() - t_alpha_start, 2),
        }
        results.append(res_record)
        print(f"  ==> `{rec['universe_key']}` technical run recorded (Ret={cum_ret:+.2f}%, MDD={agg_mdd:.2f}%, Sharpe={agg_daily_sr:.2f}, MDD15%={mc_res['prob_mdd_ge_15_pct']}%)")

    execution_coverage = {
        "records_in_universe": len(results),
        "records_backtested": sum(result["execution_status"] == "COMPLETED" for result in results),
        "records_not_run": sum(result["execution_status"] == "NOT_RUN" for result in results),
        "folds_completed": sum(
            fold.get("status") == "COMPLETED"
            for result in results
            for fold in result["folds_metrics"].values()
        ),
        "folds_not_run": sum(
            fold.get("status") == "NOT_RUN"
            for result in results
            for fold in result["folds_metrics"].values()
        ),
    }
    protocol_prov = protocol_provenance()
    engine_version = version("nautilus-trader")
    cost_model_prov = {
        "declared_defaults_bps": {"maker": 2.0, "taker": 5.0},
        "scope": "Defaults only; alpha configuration may override and account-specific fees are unverified.",
    }
    cost_model_prov["sha256"] = hashlib.sha256(
        json.dumps(cost_model_prov, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    # Lưu JSON Artifacts
    output_payload = {
        "artifact_status": "TECHNICAL_DRY_RUN",
        "execution_coverage": execution_coverage,
        "metadata": {
            "pipeline_version": "1.3.0-FULL-UNIVERSE",
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit": git_prov["commit"],
            "git_worktree_dirty": git_prov["worktree_dirty"],
            "git_status_sha256": git_prov["status_sha256"],
            "engine_version": engine_version,
            "total_records": len(results),
            "total_wall_time_seconds": round(time.time() - t_pipeline_start, 2),
            "source_file_count": len(alpha_code_map),
            "source_code_sha256": source_prov["alpha_sources_sha256"],
            "implementation_source_sha256": source_prov["implementation_sha256"],
            "implementation_source_hashes": source_prov["implementation_source_hashes"],
            "cohort_sha256": cohort_prov["sha256"],
            "cohort_record_count": cohort_prov["record_count"],
            "cohort_members": cohort_prov["members"],
            "data_catalog_fingerprint": data_prov["fingerprint_sha256"],
            "data_provenance_scope": "Catalog manifests only; raw candle files are not content-hashed by this runner.",
            "data_catalog_provenance": data_prov,
            "protocol_sha256": protocol_prov["sha256"],
            "protocol": protocol_prov["definition"],
            "cost_model": cost_model_prov,
            "resource_provenance": resource_provenance(),
            "environment": {
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
            },
        },
        "methodology": {
            "execution_mode": "INDEPENDENT_ENGINE_RUN_PER_FOLD",
            "boundary_handling": "WARMUP_20D_PRELOAD_WITH_CLOSE_AT_END",
            "metric_calculation": "DAILY_EQUITY_RETURNS_MTM_365D_SHARPE",
            "monte_carlo_model": "COMPOUNDED_STATIONARY_BOOTSTRAP_DAILY_RETURNS_10K_SIMS",
            "execution_status": "TECHNICAL_DRY_RUN_UNTIL_READINESS_GATES_PASS",
            "native_research_policy": "NOT_RUN_WITHOUT_DETERMINISTIC_CATALOG_REPLAY",
        },
        "technical_dry_run_disposition_summary": {
            key: sum(1 for result in results if result["technical_dry_run_disposition"] == key)
            for key in sorted({result["technical_dry_run_disposition"] for result in results})
        },
        "records": results,
    }

    full_results_json = ARTIFACT_DIR / "wfa_mc_full_universe_results.json"
    full_results_json.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Đã lưu kết quả chi tiết full vũ trụ: {full_results_json}")

    md_lines = [
        f"# WFA/Monte Carlo Technical Dry-Run ({len(results)} records)",
        f"\n*UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} | Git: `{git_prov['commit']}`*",
        "",
        "> **Technical run only. No ranking, promotion, rejection, or removal decision.**",
        f"> Records: {execution_coverage['records_in_universe']}; backtested: {execution_coverage['records_backtested']}; not run: {execution_coverage['records_not_run']}; folds completed: {execution_coverage['folds_completed']}.",
        "> Fee defaults are unverified; this protocol is not owner-approved. See JSON provenance for source/data/protocol hashes and measured cgroup data.",
        "",
        "| # | Product-scoped source | Category | Execution | Trades | OOS return | OOS MDD | Daily Sharpe | P(MDD >= 15%) | P(MDD >= 20%) | Technical status |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    def metric(value: Any, suffix: str = "") -> str:
        return f"{value}{suffix}" if value is not None else "N/A"

    for idx, result in enumerate(results, 1):
        metrics = result["aggregated_oos_metrics"]
        mc = result["monte_carlo_block_bootstrap"]["base_block_5"]
        p15 = metric(mc.get("prob_mdd_ge_15_pct"), "%") if mc.get("status") == "COMPLETED" else "N/A"
        p20 = metric(mc.get("prob_mdd_ge_20_pct"), "%") if mc.get("status") == "COMPLETED" else "N/A"
        md_lines.append(
            f"| {idx} | `{result['universe_key']}` | {result['category']} | {result['execution_status']} | "
            f"{metric(result['total_agg_oos_trades'])} | {metric(metrics['cum_return_pct'], '%')} | "
            f"{metric(metrics['mdd_pct'], '%')} | {metric(metrics['daily_sharpe'])} | {p15} | {p20} | "
            f"{result['technical_dry_run_disposition']} |"
        )

    md_lines.append("\n## Technical status counts")
    for status, count in sorted(output_payload["technical_dry_run_disposition_summary"].items()):
        md_lines.append(f"- `{status}`: {count}")

    full_summary_md = ARTIFACT_DIR / "wfa_mc_full_universe_summary.md"
    full_summary_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"✅ Đã lưu báo cáo tổng hợp Markdown: {full_summary_md}")

    full_dossier_md = ARTIFACT_DIR / "alpha_full_underperformer_dossier.md"
    full_dossier_md.write_text(
        "# No alpha disposition dossier\n\n"
        "This file intentionally contains no KEEP/REJECT classifications or inferred causes. "
        "The current run is a technical dry-run; owner-approved evaluation gates and authoritative "
        "cost/data inputs are not established.\n",
        encoding="utf-8",
    )
    print(f"✅ Đã vô hiệu nội dung dossier quyết định alpha: {full_dossier_md}")

    print("\n" + "=" * 80)
    print("HOÀN THÀNH TOÀN BỘ PIPELINE WFA & MONTE CARLO CHO FULL VŨ TRỤ ALPHA!")
    print("=" * 80, flush=True)

if __name__ == "__main__":
    main()
