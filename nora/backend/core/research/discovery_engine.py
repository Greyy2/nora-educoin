"""Discovery Engine Module
Aggregates per-asset market fingerprints into cross-asset statistical findings
("Discoveries") — the primary navigation surface for the Research Desk.

Design principle: never recompute from raw ticks here. Reuse the existing
per-asset pipeline (analyze_market) and aggregate its already-computed output
with numpy/pandas. Every number must trace back to a real per-asset field —
no fabricated statistics, no invented fields. Where data is insufficient,
report null + an explicit status rather than a fallback number.
"""
import json
import os
import re
import time
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

try:
    from backend.core.research.market_analyzer import analyze_market, list_known_symbols, get_cache_dir
except ImportError:
    from nora.backend.core.research.market_analyzer import analyze_market, list_known_symbols, get_cache_dir


def _targets_file_path(data_root: Optional[str] = None) -> str:
    if data_root:
        base = data_root
    else:
        # data_root defaults to <repo>/nora/data via default_data_root(); the
        # targets file lives alongside it, not inside it.
        base = None
    candidates = []
    if base:
        candidates.append(os.path.join(os.path.dirname(base.rstrip("/")), "geckoterminal_targets.json"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.abspath(os.path.join(here, "..", "..", "..", "..", "data", "geckoterminal_targets.json")))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[-1]


_DEX_NAME_RE = re.compile(r"\(([^)]+)\)\s*$")


def _load_asset_dex_map(data_root: Optional[str] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """Maps SYMBOL -> {network, dex_name} using the crawler target registry."""
    path = _targets_file_path(data_root)
    mapping: Dict[str, Dict[str, Optional[str]]] = {}
    if not os.path.isfile(path):
        return mapping
    try:
        with open(path, "r", encoding="utf-8") as f:
            targets = json.load(f)
    except Exception:
        return mapping
    for t in targets:
        asset = str(t.get("asset", "")).strip().upper()
        if not asset:
            continue
        network = t.get("network")
        name = t.get("name", "") or ""
        m = _DEX_NAME_RE.search(name)
        dex_name = m.group(1).strip() if m else None
        mapping[asset] = {"network": network, "dex_name": dex_name}
    return mapping


def get_discovery_cache_dir(data_root: Optional[str] = None) -> str:
    c_dir = os.path.join(get_cache_dir(data_root), "discoveries")
    os.makedirs(c_dir, exist_ok=True)
    return c_dir


def collect_universe_fingerprints(
    timeframe: str = "1h",
    data_root: Optional[str] = None,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Loops over the full research universe, reusing analyze_market() per asset,
    and keeps the subset of fields needed for cross-asset aggregation.
    """
    cache_dir = get_discovery_cache_dir(data_root)
    cache_file = os.path.join(cache_dir, f"universe_fingerprints_{timeframe}.json")

    if not force_refresh and os.path.isfile(cache_file):
        try:
            # Short TTL: this is a cheap aggregation step once per-asset
            # analyze_market() caches are warm, so we don't need mtime
            # invalidation against every tick file — 5 minutes is enough
            # to avoid recomputation on rapid repeated overview loads.
            if time.time() - os.path.getmtime(cache_file) < 300:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    dex_map = _load_asset_dex_map(data_root)
    symbols = list_known_symbols(data_root)
    rows: List[Dict[str, Any]] = []

    for sym in symbols:
        try:
            res = analyze_market(sym, timeframe=timeframe, data_root=data_root, force_refresh=force_refresh)
            dex_info = dex_map.get(sym, {"network": None, "dex_name": None})
            rows.append({
                "symbol": sym,
                "network": dex_info.get("network"),
                "dex_name": dex_info.get("dex_name"),
                "classification": res.get("classification"),
                "market_health_score": res.get("market_health_score", 0.0),
                "tradeability_score": res.get("tradeability_score", 0.0),
                "current_regime": res.get("regime", {}).get("current_regime"),
                "market_fingerprint": res.get("market_fingerprint", {}),
                "scaling_law": res.get("scaling_law", {}),
                "data_quality_metrics": res.get("data_quality", {}).get("metrics", {}),
                "dc_best_metrics": res.get("best_metrics", {}),
            })
        except Exception:
            continue

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
    except Exception:
        pass

    return rows


def _numeric_series(rows: List[Dict[str, Any]], accessor) -> np.ndarray:
    vals = []
    for r in rows:
        try:
            v = accessor(r)
            if v is None:
                continue
            v = float(v)
            if np.isnan(v) or np.isinf(v):
                continue
            vals.append(v)
        except Exception:
            continue
    return np.array(vals, dtype=float)


def _global_stats(values: np.ndarray, n_dexes: int) -> Dict[str, Any]:
    if values.size == 0:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "n_assets": 0,
            "n_dexes": n_dexes,
        }
    return {
        "mean": round(float(np.mean(values)), 4),
        "median": round(float(np.median(values)), 4),
        "std": round(float(np.std(values)), 4),
        "min": round(float(np.min(values)), 4),
        "max": round(float(np.max(values)), 4),
        "n_assets": int(values.size),
        "n_dexes": n_dexes,
    }


def _distribution(values: np.ndarray, bins: int = 10) -> Dict[str, Any]:
    if values.size < 2:
        return {"bins": [], "counts": []}
    counts, edges = np.histogram(values, bins=bins)
    return {
        "bins": [round(float(e), 4) for e in edges],
        "counts": [int(c) for c in counts],
    }


def _cross_asset(rows: List[Dict[str, Any]], accessor, mean_val: Optional[float]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        try:
            v = accessor(r)
            if v is None:
                continue
            v = float(v)
            if np.isnan(v) or np.isinf(v):
                continue
        except Exception:
            continue
        out.append({
            "symbol": r["symbol"],
            "value": round(v, 4),
            "delta_from_mean": round(v - mean_val, 4) if mean_val is not None else None,
        })
    out.sort(key=lambda x: x["value"], reverse=True)
    return out


def _cross_dex(rows: List[Dict[str, Any]], accessor) -> List[Dict[str, Any]]:
    groups: Dict[str, List[float]] = {}
    dex_names: Dict[str, set] = {}
    for r in rows:
        try:
            v = accessor(r)
            if v is None:
                continue
            v = float(v)
            if np.isnan(v) or np.isinf(v):
                continue
        except Exception:
            continue
        network = r.get("network") or "unknown"
        groups.setdefault(network, []).append(v)
        dex_names.setdefault(network, set())
        if r.get("dex_name"):
            dex_names[network].add(r["dex_name"])

    out = []
    for network, vals in groups.items():
        arr = np.array(vals, dtype=float)
        n = int(arr.size)
        names = sorted(dex_names.get(network, []))
        out.append({
            "network": network,
            "dex_name": ", ".join(names) if names else None,
            "n_assets": n,
            "mean": round(float(np.mean(arr)), 4) if n > 0 else None,
            "std": round(float(np.std(arr)), 4) if n > 0 else None,
            "insufficient_sample": n < 3,
        })
    out.sort(key=lambda x: x["n_assets"], reverse=True)
    return out


def _robustness(rows: List[Dict[str, Any]], values: np.ndarray) -> Dict[str, Any]:
    theta_stability_vals = _numeric_series(rows, lambda r: r.get("scaling_law", {}).get("cross_theta_stability"))
    threshold_sensitivity = {
        "score": round(float(np.mean(theta_stability_vals)), 1) if theta_stability_vals.size > 0 else None,
        "basis": "cross_theta_stability avg",
        "status": "ok" if theta_stability_vals.size > 0 else "insufficient_data",
    }

    time_period_stability = {
        "score": None,
        "basis": "rolling multi-period backtest not yet implemented",
        "status": "insufficient_data",
    }

    if values.size >= 2 and float(np.mean(values)) != 0:
        cv = float(np.std(values)) / abs(float(np.mean(values)))
        cross_market_score = round(max(0.0, min(100.0, 100.0 / (1.0 + cv))), 1)
        cross_market_stability = {
            "score": cross_market_score,
            "basis": "1/CV of field across assets",
            "status": "ok",
        }
    else:
        cross_market_stability = {"score": None, "basis": "1/CV of field across assets", "status": "insufficient_data"}

    return {
        "threshold_sensitivity": threshold_sensitivity,
        "time_period_stability": time_period_stability,
        "cross_market_stability": cross_market_stability,
    }


def _severity(n_assets: int, n_total: int, values: np.ndarray) -> str:
    if n_total <= 0 or n_assets <= 0:
        return "LOW"
    coverage = n_assets / n_total
    cv = None
    if values.size >= 2 and float(np.mean(values)) != 0:
        cv = abs(float(np.std(values)) / float(np.mean(values)))
    if coverage >= 0.7 and cv is not None and cv < 0.5:
        return "HIGH"
    if coverage >= 0.4:
        return "MEDIUM"
    return "LOW"


DISCOVERY_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "dc_os_ratio_invariance",
        "title": "DC / OS Ratio Invariance",
        "field": "market_fingerprint.mu_os_dc",
        "hypothesis": "Sau khi xác nhận Directional Change tại theta*, tỷ lệ overshoot trung bình (mu_OS/DC) hội tụ quanh một giá trị ổn định trên toàn bộ tài sản, cho thấy đây là một quy luật cấu trúc chứ không phải nhiễu riêng lẻ của từng tài sản.",
        "accessor": lambda r: r.get("market_fingerprint", {}).get("mu_os_dc"),
        "unit": "ratio",
    },
    {
        "id": "deficit_frequency_pattern",
        "title": "Overshoot Deficit Frequency Pattern",
        "field": "market_fingerprint.deficit_frequency",
        "hypothesis": "Tần suất xảy ra Overshoot Deficit (OSD < 0, tức sóng yếu hơn kỳ vọng) có phân bố nhất quán giữa các tài sản, phản ánh một cơ chế hụt động lượng mang tính hệ thống trên thị trường DEX.",
        "accessor": lambda r: r.get("market_fingerprint", {}).get("deficit_frequency"),
        "unit": "fraction",
    },
    {
        "id": "clustering_structure",
        "title": "Event Clustering Structure",
        "field": "market_fingerprint.clustering_index",
        "hypothesis": "Các sự kiện Directional Change không xuất hiện theo phân phối Poisson đều đặn mà có xu hướng tụ cụm (bursty), thể hiện qua chỉ số phân tán (clustering CV) lệch khỏi 1.0 một cách hệ thống.",
        "accessor": lambda r: r.get("market_fingerprint", {}).get("clustering_index"),
        "unit": "cv",
    },
    {
        "id": "directional_persistence",
        "title": "Directional Persistence",
        "field": "market_fingerprint.directional_persistence",
        "hypothesis": "Xác suất một sự kiện DC tiếp theo cùng chiều với sự kiện trước đó khác đáng kể so với 50%, cho thấy có tính bền hướng (trend persistence) nội tại trong intrinsic time.",
        "accessor": lambda r: r.get("market_fingerprint", {}).get("directional_persistence"),
        "unit": "probability",
    },
    {
        "id": "lambda_dc_stability",
        "title": "DC Event Intensity Stability",
        "field": "market_fingerprint.lambda_dc_daily",
        "hypothesis": "Tần suất sự kiện Directional Change mỗi ngày (lambda_DC) hội tụ về một dải giá trị ổn định trên các tài sản có đủ dữ liệu, cho thấy đây là một tham số cấu trúc thị trường chứ không phải hiện tượng ngẫu nhiên.",
        "accessor": lambda r: r.get("market_fingerprint", {}).get("lambda_dc_daily"),
        "unit": "events/day",
    },
]


def _build_discovery(template: Dict[str, Any], rows: List[Dict[str, Any]], n_total: int) -> Dict[str, Any]:
    accessor = template["accessor"]
    values = _numeric_series(rows, accessor)
    n_dexes = len({r.get("network") for r in rows if r.get("network")})
    stats = _global_stats(values, n_dexes)
    mean_val = stats["mean"]

    cross_asset = _cross_asset(rows, accessor, mean_val)
    cross_dex = _cross_dex(rows, accessor)
    robustness = _robustness(rows, values)
    severity = _severity(stats["n_assets"], n_total, values)

    if stats["n_assets"] == 0:
        status = "insufficient_data"
        headline_stat = "Không đủ dữ liệu"
    elif stats["n_assets"] >= n_total and n_total >= 3:
        status = "ready"
        stable_dex = [g for g in cross_dex if not g["insufficient_sample"]]
        dex_stability_txt = f" — {len(stable_dex)}/{len(cross_dex)} nhóm DEX đủ mẫu" if cross_dex else ""
        headline_stat = f"Có mặt ở {stats['n_assets']}/{n_total} tài sản{dex_stability_txt}"
    else:
        status = "partial"
        stable_dex = [g for g in cross_dex if not g["insufficient_sample"]]
        dex_stability_txt = f" — {len(stable_dex)}/{len(cross_dex)} nhóm DEX đủ mẫu" if cross_dex else ""
        headline_stat = f"Có mặt ở {stats['n_assets']}/{n_total} tài sản{dex_stability_txt}"

    available_symbols = {item["symbol"] for item in cross_asset}
    missing_symbols = [r["symbol"] for r in rows if r.get("symbol") not in available_symbols]

    coverage = {
        "available_assets": stats["n_assets"],
        "total_assets": n_total,
        "missing_assets": missing_symbols,
        "missing_reason": "Thiếu giá trị trường nguồn trong phân tích" if missing_symbols else None,
    }

    return {
        "id": template["id"],
        "title": template["title"],
        "severity": severity,
        "status": status,
        "hypothesis": template["hypothesis"],
        "headline_stat": headline_stat,
        "field": template.get("field", ""),
        "unit": template["unit"],
        "global_stats": stats,
        "distribution": _distribution(values),
        "cross_asset": cross_asset,
        "cross_dex": cross_dex,
        "robustness": robustness,
        "coverage": coverage,
    }


def compute_discoveries(
    timeframe: str = "1h",
    data_root: Optional[str] = None,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    rows = collect_universe_fingerprints(timeframe, data_root, force_refresh)
    n_total = len(rows)
    discoveries = [_build_discovery(t, rows, n_total) for t in DISCOVERY_TEMPLATES]

    severity_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    discoveries.sort(key=lambda d: (severity_rank.get(d["severity"], 3), -d["global_stats"]["n_assets"]))
    return discoveries


def get_discovery_by_id(
    discovery_id: str,
    timeframe: str = "1h",
    data_root: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    template = next((t for t in DISCOVERY_TEMPLATES if t["id"] == discovery_id), None)
    if template is None:
        return None
    rows = collect_universe_fingerprints(timeframe, data_root, force_refresh)
    return _build_discovery(template, rows, len(rows))


def get_dataset_summary(
    timeframe: str = "1h",
    data_root: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    rows = collect_universe_fingerprints(timeframe, data_root, force_refresh)
    n_dexes = len({r.get("network") for r in rows if r.get("network")})
    total_ticks = sum(int(r.get("data_quality_metrics", {}).get("total_ticks", 0) or 0) for r in rows)
    return {
        "n_assets": len(rows),
        "n_dexes": n_dexes,
        "total_ticks": total_ticks,
    }


def compute_method_comparison(
    timeframe: str = "1h",
    data_root: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Compares analytical sampling methods. Only Directional Change (and DC+OS,
    the DC engine enriched with overshoot statistics) are implemented in this
    codebase today. Time Sampling and Volume Sampling have no engine — report
    them as not_implemented rather than fabricating comparison numbers.
    """
    rows = collect_universe_fingerprints(timeframe, data_root, force_refresh)

    dc_scores = _numeric_series(rows, lambda r: r.get("dc_best_metrics", {}).get("dc_structure_score"))
    dc_event_rates = _numeric_series(rows, lambda r: r.get("dc_best_metrics", {}).get("event_rate_per_day"))
    os_ratios = _numeric_series(rows, lambda r: r.get("market_fingerprint", {}).get("mu_os_dc"))
    theta_stability = _numeric_series(rows, lambda r: r.get("scaling_law", {}).get("cross_theta_stability"))

    methods = [
        {
            "id": "time_sampling",
            "title": "Time Sampling",
            "status": "not_implemented",
            "relative_strength": None,
            "metrics": {},
            "note": "Chưa có engine lấy mẫu theo thời gian cố định trong codebase hiện tại.",
        },
        {
            "id": "volume_sampling",
            "title": "Volume Sampling",
            "status": "not_implemented",
            "relative_strength": None,
            "metrics": {},
            "note": "Chưa có engine lấy mẫu theo khối lượng trong codebase hiện tại.",
        },
        {
            "id": "directional_change",
            "title": "Directional Change",
            "status": "available" if dc_scores.size > 0 else "insufficient_data",
            "relative_strength": round(float(np.mean(dc_scores)), 1) if dc_scores.size > 0 else None,
            "metrics": {
                "avg_dc_structure_score": round(float(np.mean(dc_scores)), 1) if dc_scores.size > 0 else None,
                "avg_event_rate_per_day": round(float(np.mean(dc_event_rates)), 2) if dc_event_rates.size > 0 else None,
                "n_assets": int(dc_scores.size),
            },
            "note": None,
        },
        {
            "id": "dc_plus_os",
            "title": "DC + OS",
            "status": "available" if theta_stability.size > 0 else "insufficient_data",
            "relative_strength": round(float(np.mean(theta_stability)), 1) if theta_stability.size > 0 else None,
            "metrics": {
                "avg_mu_os_dc": round(float(np.mean(os_ratios)), 2) if os_ratios.size > 0 else None,
                "avg_cross_theta_stability": round(float(np.mean(theta_stability)), 1) if theta_stability.size > 0 else None,
                "n_assets": int(theta_stability.size),
            },
            "note": None,
        },
    ]

    return {
        "timeframe": timeframe,
        "generated_at": int(time.time()),
        "methods": methods,
    }
