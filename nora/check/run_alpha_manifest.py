"""Run the finite COIN alpha manifest as an exploratory default-parameter screen.

This runner never starts a bot, never sends venue orders, and does not certify
OOS performance or Backtest-Live parity.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import gzip
import hashlib
import json
import os
import resource
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COIN_ROOT = ROOT / "nora" / "coin"
sys.path.insert(0, str(COIN_ROOT))

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NORA_CANDLE_CACHE_MB"] = "256"
os.environ["NORA_DATA_CACHE_MB"] = "512"
os.environ["NORA_BARS_CACHE_MB"] = "512"

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.alpha.strategies import engine_version
from backend.analys.metrics.metrics import portfolio_metrics
from backend.analys.param import BASE_RISK_PER_TRADE_PCT, DAY_MS, FRAME_MS, RISK, materialize, schema_defaults
from backend.core import catalog as instrument_catalog
from backend.data.data import catalog_digest, default_catalog_path, read_manifest
from backend.jobs.runner.backtest import BacktestJob, make_engine
from backend.models.storage import json_default

MANIFEST_PATH = ROOT / "nora" / "check" / "alpha_universe_manifest.json"
PROXY_PATH = ROOT / "nora" / "coin" / "backend" / "adapter" / "contracts.py"
INITIAL_CAPITAL = 10_000.0
STOP_FILL = "level"
WARMUP_FALLBACK_MS = 20 * DAY_MS
ENGINE_MAX_BACKTEST_DAYS = 1100


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _hash_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode())


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default, allow_nan=False) + "\n")
    os.replace(tmp, path)


def _aligned_windows(
    symbols: list[str], timeframe: str, warmup_ms: int
) -> tuple[int, int, bool]:
    manifests = [read_manifest(symbol) for symbol in symbols]
    if any(not item for item in manifests):
        raise RuntimeError(f"Missing market-data manifest for {symbols}")
    first = max(int(item["start_ts"]) for item in manifests if item)
    latest_open = min(int(item["end_ts"]) for item in manifests if item)
    base_ms = FRAME_MS[timeframe]
    requested_start = ((first + warmup_ms + base_ms - 1) // base_ms) * base_ms
    start = requested_start
    last_closed_boundary = ((latest_open + 60_000) // base_ms) * base_ms
    end_exclusive = last_closed_boundary
    earliest_allowed_start = end_exclusive - (
        ENGINE_MAX_BACKTEST_DAYS * DAY_MS - WARMUP_FALLBACK_MS
    )
    earliest_allowed_start = (
        (earliest_allowed_start + base_ms - 1) // base_ms
    ) * base_ms
    start = max(start, earliest_allowed_start)
    if start >= end_exclusive:
        raise RuntimeError(f"No full bars after warm-up for {timeframe}")
    return start, end_exclusive, start > requested_start


def _variant_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for strategy in manifest["system_strategies"]:
        for candidate in strategy["candidates"]:
            for symbol in manifest["approved_symbols"]:
                for track, frames in manifest["timeframe_tracks"].items():
                    for timeframe in frames:
                        rows.append({
                            "variant_id": f"{candidate['candidate_id']}|{symbol}|{timeframe}",
                            "candidate_id": candidate["candidate_id"],
                            "strategy_id": strategy["strategy_id"],
                            "side": candidate["side"],
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "track": "scalp" if track == "scalp_track" else "swing",
                            "warmup_bars": int(strategy["warmup_bars"]),
                        })
    keys = [row["variant_id"] for row in rows]
    expected = int(manifest["matrix_summary"]["total_finite_variants"])
    if len(rows) != expected or len(set(keys)) != expected:
        raise ValueError(f"Expected {expected} unique manifest variants; got {len(rows)} rows / {len(set(keys))} IDs")
    return rows


def _position_dict(value: Any) -> dict[str, Any]:
    return asdict(value) if is_dataclass(value) else dict(value)


def _write_raw_artifact(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, default=json_default, allow_nan=False)
        stream.write("\n")
    os.replace(tmp, path)
    return _hash_bytes(path.read_bytes())


def _run_variant(
    row: dict[str, Any],
    candidate: dict[str, Any],
    source: dict[str, str],
    source_file: str,
    repo_root: Path,
    manifest_hash: str,
    engine_hash: str,
    proxy_hash: str,
    started_at: str,
    output_dir: Path,
) -> dict[str, Any]:
    from backend.analys.alpha.strategies import lift_frames

    params = schema_defaults(candidate)
    effective_params = lift_frames(candidate, params, row["timeframe"])
    strategy = materialize(
        candidate,
        effective_params,
        regime=False,
        stop_fill=STOP_FILL,
        risk_per_trade_pct=BASE_RISK_PER_TRADE_PCT,
    )
    frame_windows = [
        FRAME_MS[value]
        for value in effective_params.values()
        if isinstance(value, str) and value in FRAME_MS
    ]
    warmup_ms = max(frame_windows, default=FRAME_MS[row["timeframe"]]) * row["warmup_bars"]
    start, end_exclusive, window_capped = _aligned_windows(
        [row["symbol"]], row["timeframe"], warmup_ms
    )
    end_inclusive = end_exclusive - 1
    instrument_spec = instrument_catalog.instrument_spec(row["symbol"])
    data_hash = catalog_digest([row["symbol"]])
    source_path = repo_root / source_file
    source_hash = _hash_bytes(source_path.read_bytes())
    config_hash = _canonical_hash({
        "effective_params": effective_params,
        "position": strategy["position"],
        "risk": RISK,
        "risk_per_trade_pct": BASE_RISK_PER_TRADE_PCT,
        "initial_capital": INITIAL_CAPITAL,
        "stop_fill": STOP_FILL,
        "regime": False,
        "timeframe": row["timeframe"],
    })
    job = BacktestJob(
        items=[(row["candidate_id"], effective_params)],
        window=(start, end_inclusive),
        stop_fill=STOP_FILL,
        risk=dict(RISK),
        rpt=BASE_RISK_PER_TRADE_PCT,
        symbols=[f"{row['symbol'].split('-')[0]}@perp"],
        shared_dir=None,
        base_frame=row["timeframe"],
        regime=None,
    )
    engine, _ = make_engine(job)
    t0 = time.monotonic()
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        engine.run()
    result = engine.get_results()
    duration = time.monotonic() - t0
    metrics = portfolio_metrics(result, start, end_exclusive)
    positions = [_position_dict(position) for position in result["positions"]]
    orders = [_position_dict(order) for order in result["orders"]]
    closed_pnls = [float(position.real_pnl) for position in result["positions"]]
    fees = sum(float(position.fees_usd or 0.0) for position in result["positions"])
    funding = sum(float(position.funding_usd or 0.0) for position in result["positions"])
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    final_equity = float(result["final_equity"])
    warnings = list(result.get("warnings", []))
    funding_modeled = bool(result.get("funding_modeled", False))
    raw_rel = f"raw/{row['variant_id'].replace('|', '__')}.json.gz"
    raw_path = output_dir / raw_rel
    raw_hash = _write_raw_artifact(raw_path, {
        "variant": row,
        "input_hashes": {
            "source_sha256": source_hash,
            "code_sha256": source["code_hash"],
            "config_sha256": config_hash,
            "data_sha256": data_hash,
            "instrument_spec_sha256": _canonical_hash(instrument_spec),
            "cost_model_sha256": proxy_hash,
            "engine_sha256": engine_hash,
            "manifest_sha256": manifest_hash,
        },
        "run": {
            "started_at_utc": started_at,
            "window_start_utc": datetime.fromtimestamp(start / 1000, timezone.utc).isoformat(),
            "window_end_exclusive_utc": datetime.fromtimestamp(end_exclusive / 1000, timezone.utc).isoformat(),
            "window_capped_to_engine_limit": window_capped,
            "warmup_bars": row["warmup_bars"],
            "effective_params": effective_params,
            "risk": RISK,
            "risk_per_trade_pct": BASE_RISK_PER_TRADE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "cost_model": "APPROVED_RESEARCH_PROXY; fee remains unverified",
            "holdout_opened": False,
        },
        "summary": metrics,
        "positions": positions,
        "orders": orders,
        "equity_curve": result["equity_curve"],
        "open_positions": engine.open_positions(),
        "warnings": result["warnings"],
    })
    engine.dispose() if hasattr(engine, "dispose") else None
    del engine, result
    gc.collect()

    return {
        **row,
        "run_status": "COMPLETED_EXPLORATORY",
        "window_start_utc": datetime.fromtimestamp(start / 1000, timezone.utc).isoformat(),
        "window_end_exclusive_utc": datetime.fromtimestamp(end_exclusive / 1000, timezone.utc).isoformat(),
        "window_capped_to_engine_limit": window_capped,
        "initial_capital_usdt": INITIAL_CAPITAL,
        "final_equity_usdt": final_equity,
        "net_pnl_by_equity_usdt": final_equity - INITIAL_CAPITAL,
        "net_return_pct": metrics["ret_pct"],
        "closed_trades": metrics["trades"],
        "win_rate_pct": metrics["win_pct"],
        "avg_closed_trade_pnl_usdt": (sum(closed_pnls) / len(closed_pnls)) if closed_pnls else None,
        "closed_position_realized_pnl_usdt": sum(closed_pnls),
        "fees_usdt": fees,
        "funding_usdt": funding,
        "funding_modeled": funding_modeled,
        "mdd_intrabar_pct": metrics["mdd_intrabar_pct"],
        "mdd_daily_pct": metrics["mdd_daily_pct"],
        "daily_sharpe": metrics["sharpe"],
        "daily_sample_count": len(metrics["daily"]),
        "rejected_for_risk": metrics["rejected_for_risk"],
        "rejected_for_capital": metrics["rejected_for_capital"],
        "warnings": warnings,
        "wall_seconds": duration,
        "process_peak_rss_mb": peak_rss_mb,
        "input_hashes": {
            "source_sha256": source_hash,
            "code_sha256": source["code_hash"],
            "config_sha256": config_hash,
            "data_sha256": data_hash,
            "instrument_spec_sha256": _canonical_hash(instrument_spec),
            "cost_model_sha256": proxy_hash,
            "engine_sha256": engine_hash,
            "manifest_sha256": manifest_hash,
        },
        "raw_artifact": raw_rel,
        "raw_artifact_sha256": raw_hash,
    }


def _write_report(path: Path, package: dict[str, Any]) -> None:
    rows = package["results"]
    lines = [
        "# COIN Alpha Manifest Exploratory Backtest",
        "",
        f"- **Status:** {package['status']}",
        f"- **Run ID:** `{package['run_id']}`",
        f"- **Manifest:** {package['variant_count']} variants; SHA-256 `{package['manifest_sha256']}`",
        f"- **Active catalog:** `{package['catalog_path']}`",
        f"- **Catalog digests:** {json.dumps(package['catalog_digests'], sort_keys=True)}",
        f"- **Initial capital per independent run:** {INITIAL_CAPITAL:,.2f} USDT",
        f"- **Run config:** default alpha parameters, 0.5% base risk/trade, legacy shared risk config, stop_fill=`{STOP_FILL}`, regime off; no parameter optimization.",
        "- **Important:** this is an exploratory screen over the latest available period within the engine's 1,100-day limit (including its 20-day warm-up), not WFA/OOS, DSR, cost stress, parity certification, or bot eligibility. Per-variant timestamps and whether the window was capped are in raw artifacts. Fee tier is unverified; funding is not modeled; liquidation is not modeled; quotes are synthetic OHLC-open proxies.",
        f"- **Raw artifacts:** `{package['output_dir']}/raw/` (gzip JSON per variant).",
        "",
        "## Per-variant results",
        "",
        "| Candidate | Symbol | Frame | Status | Net return % | Net PnL USDT | Closed trades | Win % | Avg closed PnL USDT | MDD intrabar % | MDD daily % | Fees USDT | Sharpe |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        values = [
            row["candidate_id"], row["symbol"], row["timeframe"], row["run_status"],
            row.get("net_return_pct"), row.get("net_pnl_by_equity_usdt"), row.get("closed_trades"),
            row.get("win_rate_pct"), row.get("avg_closed_trade_pnl_usdt"), row.get("mdd_intrabar_pct"),
            row.get("mdd_daily_pct"), row.get("fees_usdt"), row.get("daily_sharpe"),
        ]
        cells = [str(value) if value is not None else "—" for value in values]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Candidate aggregate (descriptive only)", "",
                  "| Candidate | Variants complete | Positive equity return | Total closed trades | Mean variant return % | Mean MDD intrabar % |",
                  "|---|---:|---:|---:|---:|---:|"])
    candidate_ids = sorted({row["candidate_id"] for row in rows})
    for candidate_id in candidate_ids:
        group = [row for row in rows if row["candidate_id"] == candidate_id]
        completed = [row for row in group if row["run_status"] == "COMPLETED_EXPLORATORY"]
        mean_return = (sum(row["net_return_pct"] for row in completed) / len(completed)) if completed else None
        mean_mdd = (sum(row["mdd_intrabar_pct"] for row in completed) / len(completed)) if completed else None
        positives = sum(row["net_return_pct"] > 0 for row in completed)
        trade_count = sum(row["closed_trades"] for row in completed)
        lines.append(f"| {candidate_id} | {len(completed)}/{len(group)} | {positives} | {trade_count} | "
                     f"{mean_return if mean_return is not None else '—'} | {mean_mdd if mean_mdd is not None else '—'} |")
    lines.extend(["", "Metrics are per independent single-symbol run; candidate aggregates are not a combined portfolio and are not risk-normalized.",
                  "A positive full-window return is not an alpha pass. No run in this report may be promoted.",
                  ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path.home() / ".local/share/norabt-alpha-runs")
    parser.add_argument("--report", type=Path, default=ROOT / "nora/check/alpha_exploratory_backtest_report.md")
    parser.add_argument("--limit", type=int, help="run only the first N variants (for smoke validation)")
    parser.add_argument("--resume", action="store_true", help="resume only missing/errored variants in the matching run directory")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_hash = _hash_bytes(MANIFEST_PATH.read_bytes())
    loaded = load_system_strategies()
    candidates = {candidate["id"]: candidate for candidate in loaded["candidates"]}
    source_files = {
        candidate["candidate_id"]: strategy["source_file"]
        for strategy in manifest["system_strategies"]
        for candidate in strategy["candidates"]
    }
    engine_meta = engine_version()
    engine_hash = str(engine_meta["hash"])
    proxy_hash = _hash_bytes(PROXY_PATH.read_bytes())
    rows = _variant_rows(manifest)
    if args.limit:
        rows = rows[:args.limit]
    symbols = manifest["approved_symbols"]
    manifests = [read_manifest(symbol) for symbol in symbols]
    if any(item is None for item in manifests):
        raise RuntimeError("Missing active catalog manifest for one or more approved symbols")
    catalog_digests = {
        symbol.split("-", 1)[0]: catalog_digest([symbol])
        for symbol in symbols
    }
    if catalog_digests != manifest["active_catalog_digest"]:
        raise RuntimeError(
            f"Active catalog digest mismatch: manifest={manifest['active_catalog_digest']}, actual={catalog_digests}; "
            "refusing to run under a different dataset"
        )
    key = _canonical_hash({
        "manifest_sha256": manifest_hash,
        "engine_sha256": engine_hash,
        "proxy_sha256": proxy_hash,
        "catalog_digests": catalog_digests,
        "initial_capital": INITIAL_CAPITAL,
        "risk": RISK,
        "risk_per_trade_pct": BASE_RISK_PER_TRADE_PCT,
        "stop_fill": STOP_FILL,
        "variants": [row["variant_id"] for row in rows],
    })[:16]
    output_dir = args.output_root / f"exploratory-{key}"
    package_path = output_dir / "results.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.resume and package_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        existing = {row["variant_id"]: row for row in package.get("results", [])}
    else:
        existing = {}
        package = {
            "schema_version": "exploratory-1.0.0",
            "status": "RUNNING",
            "run_id": key,
            "manifest_sha256": manifest_hash,
            "engine_sha256": engine_hash,
            "cost_model_source_sha256": proxy_hash,
            "catalog_path": default_catalog_path(),
            "catalog_digests": catalog_digests,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "scope": "FINITE_MANIFEST_DEFAULT_PARAMS_SINGLE_FULL_WINDOW_PER_VARIANT; NOT_WFA_OR_OOS",
            "variant_count": len(rows),
            "results": [],
        }
    started_at = package.get("started_at_utc") or datetime.now(timezone.utc).isoformat()
    sources = loaded["sources"]
    for index, row in enumerate(rows, start=1):
        prior = existing.get(row["variant_id"])
        if prior and prior.get("run_status") == "COMPLETED_EXPLORATORY":
            print(f"[{index}/{len(rows)}] SKIP {row['variant_id']} already complete", flush=True)
            continue
        print(f"[{index}/{len(rows)}] START {row['variant_id']}", flush=True)
        try:
            result = _run_variant(
                row, candidates[row["candidate_id"]], sources[row["candidate_id"]],
                source_files[row["candidate_id"]],
                ROOT, manifest_hash, engine_hash, proxy_hash, started_at, output_dir,
            )
            existing[row["variant_id"]] = result
            print(
                f"[{index}/{len(rows)}] DONE {row['variant_id']} return={result['net_return_pct']:.4f}% "
                f"trades={result['closed_trades']} mdd={result['mdd_intrabar_pct']:.4f}% "
                f"wall={result['wall_seconds']:.1f}s peak_rss={result['process_peak_rss_mb']:.0f}MB",
                flush=True,
            )
        except Exception as exc:
            existing[row["variant_id"]] = {
                **row,
                "run_status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            print(f"[{index}/{len(rows)}] ERROR {row['variant_id']}: {type(exc).__name__}: {exc}", flush=True)
        package["results"] = [existing[key] for key in sorted(existing)]
        package["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        package["completed_count"] = sum(value["run_status"] == "COMPLETED_EXPLORATORY" for value in existing.values())
        package["error_count"] = sum(value["run_status"] == "ERROR" for value in existing.values())
        package["status"] = "RUNNING"
        _atomic_json(package_path, package)
        _write_report(args.report, package)

    expected_ids = {row["variant_id"] for row in rows}
    package["results"] = [existing[key] for key in sorted(existing)]
    package["completed_count"] = sum(value["run_status"] == "COMPLETED_EXPLORATORY" for value in existing.values())
    package["error_count"] = sum(value["run_status"] == "ERROR" for value in existing.values())
    package["status"] = (
        "COMPLETED_EXPLORATORY"
        if expected_ids <= set(existing) and package["completed_count"] == len(rows)
        else "INCOMPLETE_WITH_ERRORS"
    )
    package["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(package_path, package)
    _write_report(args.report, package)
    print(f"FINAL {package['status']}: {package['completed_count']}/{len(rows)} complete, "
          f"{package['error_count']} errors; results={package_path}; report={args.report}", flush=True)
    return 0 if package["status"] == "COMPLETED_EXPLORATORY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
