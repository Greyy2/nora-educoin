"""P19 — Alpha Runners: Universe Scan (100 coins), Parameter Sweep (100 variants), & Alpha Research (LLM).

Consolidated into backend/jobs/runner/alpha.py.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.data import data as D
from backend.data.crawl import load_scan_universe, scan_universe_bases
from backend.analys.param import DAY_MS as DAY, FRAME_MS
from backend.models.storage import data_home, write_json_atomic, write_job_result
from backend.core.engine import PortfolioEngine
from backend.analys.metrics.metrics import portfolio_metrics

logger = logging.getLogger("nora.jobs.runner.alpha")

# 8 coin của sổ đã dùng để tối ưu tham số (tập tối ưu)
OPTIMIZED_8_COINS = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"}

# Cửa sổ mặc định theo P19 plan
DEFAULT_IS_START = 1744502400000   # 2025-04-13 00:00:00 UTC
DEFAULT_IS_END = 1775952000000     # 2026-04-12 00:00:00 UTC
DEFAULT_OOS_START = 1776038400000  # 2026-04-13 00:00:00 UTC
DEFAULT_OOS_END = 1791763200000    # 2026-10-12 00:00:00 UTC
WARMUP_MS = 180 * DAY              # 6 tháng warmup


def _to_ms(val: Any, default: int) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        try:
            return int(dt.datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            try:
                return int(val)
            except Exception:
                return default
    return default


def _calc_spearman(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 3 or len(x) != len(y):
        return None
    try:
        rx = pd.Series(x).rank()
        ry = pd.Series(y).rank()
        corr = rx.corr(ry)
        return float(corr) if np.isfinite(corr) else None
    except Exception:
        return None


def load_universe_sectors() -> Dict[str, str]:
    path = os.path.join(data_home(), "market", "okx", "universe_sectors.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def run_single_coin(
    base: str,
    strategy: Dict[str, Any],
    signal_tf: str,
    is_start: int,
    is_end: int,
    oos_start: int,
    oos_end: int,
    capital: float,
    grade: str,
    sector: str = "Other",
) -> Dict[str, Any]:
    """Chạy backtest độc lập cho 1 coin trên 2 cửa sổ: IS và OOS."""
    sym = f"{base}@perp"
    strat_copy = dict(strategy)
    strat_copy["symbols"] = [sym]

    res_coin: Dict[str, Any] = {
        "base": base,
        "symbol": sym,
        "grade": grade,
        "sector": sector,
        "is_optimized_8": base in OPTIMIZED_8_COINS,
        "is": None,
        "oos": None,
        "status": "OK",
        "error": None,
    }

    # 1. Chạy In-Sample
    try:
        eng_is = PortfolioEngine(
            [sym],
            [strat_copy],
            is_start - WARMUP_MS,
            is_end,
            trade_start_ts=is_start,
            risk=None,
            base_frame=signal_tf,
            initial_capital=capital,
        )
        eng_is.run()
        raw_is = eng_is.get_results()
        m_is = portfolio_metrics(raw_is, is_start)
        res_coin["is"] = {
            "ret_pct": m_is.get("ret_pct", 0.0),
            "mdd_pct": m_is.get("mdd_pct", 0.0),
            "sharpe": m_is.get("sharpe"),
            "win_rate": m_is.get("win_pct"),
            "trades": m_is.get("trades", 0),
            "fees_usd": m_is.get("fees_usd", 0.0),
            "low_trades": (m_is.get("trades") or 0) < 30,
        }
    except Exception as exc:
        res_coin["is"] = {"error": str(exc), "trades": 0, "ret_pct": 0.0, "low_trades": True}
        res_coin["status"] = "ERROR_IS"
        res_coin["error"] = str(exc)

    # 2. Chạy Out-of-Sample
    try:
        eng_oos = PortfolioEngine(
            [sym],
            [strat_copy],
            oos_start - WARMUP_MS,
            oos_end,
            trade_start_ts=oos_start,
            risk=None,
            base_frame=signal_tf,
            initial_capital=capital,
        )
        eng_oos.run()
        raw_oos = eng_oos.get_results()
        m_oos = portfolio_metrics(raw_oos, oos_start)
        res_coin["oos"] = {
            "ret_pct": m_oos.get("ret_pct", 0.0),
            "mdd_pct": m_oos.get("mdd_pct", 0.0),
            "sharpe": m_oos.get("sharpe"),
            "win_rate": m_oos.get("win_pct"),
            "trades": m_oos.get("trades", 0),
            "fees_usd": m_oos.get("fees_usd", 0.0),
            "low_trades": (m_oos.get("trades") or 0) < 30,
        }
    except Exception as exc:
        res_coin["oos"] = {"error": str(exc), "trades": 0, "ret_pct": 0.0, "low_trades": True}
        if res_coin["status"] == "OK":
            res_coin["status"] = "ERROR_OOS"
        res_coin["error"] = str(exc)

    return res_coin


def run_universe_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """Job `universe_scan`: Quét thị trường 100 coin OKX USDT-SWAP."""
    from backend.jobs.tasks import resolve_strategy

    t_start = time.time()
    alpha_id = params.get("alpha_id") or "dca_long"
    signal_tf = params.get("signal_tf") or "15m"
    book_source = params.get("book_source") or "explore"
    capital = float(params.get("capital") or 1000.0)

    is_start = _to_ms(params.get("is_start"), DEFAULT_IS_START)
    is_end = _to_ms(params.get("is_end"), DEFAULT_IS_END)
    oos_start = _to_ms(params.get("oos_start"), DEFAULT_OOS_START)
    oos_end = _to_ms(params.get("oos_end"), DEFAULT_OOS_END)

    rs = resolve_strategy(alpha_id, None, signal_tf, None, None, book_source)
    strategy = rs["strategy"]

    scan_meta = load_scan_universe()
    grade_map = {c["base"]: c.get("grade", "C") for c in scan_meta}
    sector_map = load_universe_sectors()
    target_coins = params.get("coins") or [c["base"] for c in scan_meta] or scan_universe_bases()

    print(f"[Universe Scan] Bắt đầu quét {len(target_coins)} coin (Alpha: {alpha_id}, TF: {signal_tf})", flush=True)

    coin_results: List[Dict[str, Any]] = []
    workers = 3

    def _worker(coin: str) -> Dict[str, Any]:
        grade = grade_map.get(coin, "C")
        sector = sector_map.get(coin, "Other")
        return run_single_coin(coin, strategy, signal_tf, is_start, is_end, oos_start, oos_end, capital, grade, sector)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, res in enumerate(pool.map(_worker, target_coins), 1):
            coin_results.append(res)
            c = res["base"]
            is_ret = res.get("is", {}).get("ret_pct", 0.0)
            oos_ret = res.get("oos", {}).get("ret_pct", 0.0)
            print(f"[{idx}/{len(target_coins)}] {c}: IS {is_ret:+.1f}%, OOS {oos_ret:+.1f}% ({res['status']})", flush=True)

    def _group_stats(subset: List[Dict[str, Any]], key: str = "oos") -> Dict[str, Any]:
        if not subset:
            return {"total": 0, "profitable_pct": 0.0, "median_ret": 0.0, "median_sharpe": None}
        rets = [r[key]["ret_pct"] for r in subset if r.get(key) and "ret_pct" in r[key]]
        sharpes = [r[key]["sharpe"] for r in subset if r.get(key) and r[key].get("sharpe") is not None and not r[key].get("low_trades")]
        n_pos = sum(1 for ret in rets if ret > 0)
        return {
            "total": len(subset),
            "profitable": n_pos,
            "profitable_pct": round(n_pos / len(subset) * 100.0, 1) if subset else 0.0,
            "median_ret": round(float(np.median(rets)), 2) if rets else 0.0,
            "median_sharpe": round(float(np.median(sharpes)), 2) if sharpes else None,
            "sharpe_p25": round(float(np.percentile(sharpes, 25)), 2) if sharpes else None,
            "sharpe_p75": round(float(np.percentile(sharpes, 75)), 2) if sharpes else None,
        }

    group_opt_8 = [r for r in coin_results if r["is_optimized_8"]]
    group_unseen_92 = [r for r in coin_results if not r["is_optimized_8"]]

    grade_a_unseen = [r for r in group_unseen_92 if r["grade"] == "A"]
    grade_b_unseen = [r for r in group_unseen_92 if r["grade"] == "B"]
    grade_ab_unseen = [r for r in group_unseen_92 if r["grade"] in ("A", "B")]
    grade_c_unseen = [r for r in group_unseen_92 if r["grade"] == "C"]

    common_is_ret, common_oos_ret = [], []
    for r in coin_results:
        if r.get("is") and r.get("oos") and "ret_pct" in r["is"] and "ret_pct" in r["oos"]:
            common_is_ret.append(float(r["is"]["ret_pct"]))
            common_oos_ret.append(float(r["oos"]["ret_pct"]))
    spearman_corr = _calc_spearman(common_is_ret, common_oos_ret)

    ab_stats_oos = _group_stats(grade_ab_unseen, "oos")
    ab_profitable_pct = ab_stats_oos["profitable_pct"]
    ab_median_sharpe = ab_stats_oos["median_sharpe"] or 0.0
    has_edge = bool(ab_profitable_pct >= 60.0 and ab_median_sharpe > 0.0)

    verdict_note = (
        f"Chiến lược {'CÓ EDGE' if has_edge else 'CHƯA ĐẠT EDGE'}: "
        f"{ab_profitable_pct}% coin hạng A+B chưa từng thấy có lãi ở OOS (yêu cầu ≥ 60%), "
        f"Median Sharpe OOS: {ab_median_sharpe:.2f} (yêu cầu > 0)."
    )

    summary_report = {
        "alpha_id": alpha_id,
        "signal_tf": signal_tf,
        "book_source": book_source,
        "capital_per_coin": capital,
        "windows": {
            "in_sample": {"start": is_start, "end": is_end, "days": round((is_end - is_start) / DAY)},
            "out_of_sample": {"start": oos_start, "end": oos_end, "days": round((oos_end - oos_start) / DAY)},
        },
        "evaluation": {
            "has_edge": has_edge,
            "criteria": "≥ 60% coin hạng A+B chưa từng thấy lãi ở OOS VÀ median Sharpe OOS > 0",
            "verdict": verdict_note,
            "spearman_rank_correlation_is_oos": round(spearman_corr, 3) if spearman_corr is not None else None,
        },
        "groups": {
            "unseen_92": {
                "grade_ab": {
                    "is": _group_stats(grade_ab_unseen, "is"),
                    "oos": ab_stats_oos,
                },
                "grade_a": {
                    "is": _group_stats(grade_a_unseen, "is"),
                    "oos": _group_stats(grade_a_unseen, "oos"),
                },
                "grade_b": {
                    "is": _group_stats(grade_b_unseen, "is"),
                    "oos": _group_stats(grade_b_unseen, "oos"),
                },
                "grade_c_reference": {
                    "is": _group_stats(grade_c_unseen, "is"),
                    "oos": _group_stats(grade_c_unseen, "oos"),
                },
                "all_unseen": {
                    "is": _group_stats(group_unseen_92, "is"),
                    "oos": _group_stats(group_unseen_92, "oos"),
                },
            },
            "optimized_8": {
                "is": _group_stats(group_opt_8, "is"),
                "oos": _group_stats(group_opt_8, "oos"),
            },
            "all_100_coins": {
                "is": _group_stats(coin_results, "is"),
                "oos": _group_stats(coin_results, "oos"),
            },
            "sectors": {
                sec: {
                    "total": len([r for r in coin_results if r.get("sector") == sec]),
                    "is": _group_stats([r for r in coin_results if r.get("sector") == sec], "is"),
                    "oos": _group_stats([r for r in coin_results if r.get("sector") == sec], "oos"),
                }
                for sec in sorted(set(sector_map.values()) | {"Other"})
                if [r for r in coin_results if r.get("sector") == sec]
            },
        },
        "elapsed_s": round(time.time() - t_start, 1),
        "coins": coin_results,
    }

    run_id = f"scan_{int(time.time())}_{alpha_id}"
    out_dir = os.path.join(data_home(), "backtest", "scan", run_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "result.json")
    write_json_atomic(out_path, summary_report)

    latest_path = os.path.join(data_home(), "backtest", "scan", "latest_result.json")
    write_json_atomic(latest_path, summary_report)

    print(f"\n[Universe Scan] Hoàn tất quét 100 coin trong {summary_report['elapsed_s']}s -> {out_path}")
    print(f"  Kết luận: {verdict_note}")
    return summary_report


run_scan_job = run_universe_scan
scan_universe = run_universe_scan
scan_single_coin = run_single_coin


# ── Parameter Sweep 100 Strategies ──────────────────────────────────────────
def generate_100_strategies(base_strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tạo 100 biến thể tham số xoay quanh DCA Long."""
    step_pct_grid = [1.2, 1.6, 2.0, 2.25, 2.6, 3.0, 3.5]
    max_layers_grid = [2, 3, 4]
    tp_grid = [1.0, 1.4, 1.8, 2.2, 2.6]
    sl_grid = [6.0, 8.0, 9.7, 12.0, 15.0]
    mult_grid = [1.5, 1.8, 2.0, 2.3]
    rsi_grid = [35.0, 38.0, 40.0, 43.0, 46.0]

    strategies = []
    s0 = copy.deepcopy(base_strategy)
    s0["id"] = "dca_btc_cfg_000_baseline"
    strategies.append(s0)

    np.random.seed(42)
    seen = set()
    seen.add((
        base_strategy["position"]["dca_step_pct"],
        base_strategy["position"]["dca_max_layers"],
        base_strategy["position"]["take_profit_rate"],
        base_strategy["position"]["stop_loss_rate"],
        base_strategy["position"]["dca_size_multiplier"],
        base_strategy["signal_params"]["rsi_lo"],
    ))

    while len(strategies) < 100:
        step = float(np.random.choice(step_pct_grid))
        layers = int(np.random.choice(max_layers_grid))
        tp = float(np.random.choice(tp_grid))
        sl = float(np.random.choice(sl_grid))
        mult = float(np.random.choice(mult_grid))
        rsi = float(np.random.choice(rsi_grid))

        key = (step, layers, tp, sl, mult, rsi)
        if key in seen:
            continue
        seen.add(key)

        idx = len(strategies)
        s = copy.deepcopy(base_strategy)
        s["id"] = f"dca_btc_cfg_{idx:03d}"
        s["position"]["dca_step_pct"] = step
        s["position"]["dca_max_layers"] = layers
        s["position"]["take_profit_rate"] = tp
        s["position"]["stop_loss_rate"] = sl
        s["position"]["dca_size_multiplier"] = mult
        s["signal_params"]["rsi_lo"] = rsi

        if "tree" in s and s["tree"]:
            try:
                s["tree"][0][0][2] = rsi
            except Exception:
                pass

        strategies.append(s)

    return strategies


def run_single_strategy_sweep(
    strat: Dict[str, Any],
    symbol: str,
    signal_tf: str,
    is_start: int,
    is_end: int,
    oos_start: int,
    oos_end: int,
    capital: float,
) -> Dict[str, Any]:
    """Chạy 1 cấu hình chiến lược trên BTC cả IS và OOS."""
    cfg_id = strat["id"]
    strat_run = copy.deepcopy(strat)
    strat_run["symbols"] = [symbol]

    out: Dict[str, Any] = {
        "cfg_id": cfg_id,
        "symbol": symbol,
        "params": {
            "dca_step_pct": strat["position"]["dca_step_pct"],
            "dca_max_layers": strat["position"]["dca_max_layers"],
            "take_profit_rate": strat["position"]["take_profit_rate"],
            "stop_loss_rate": strat["position"]["stop_loss_rate"],
            "dca_size_multiplier": strat["position"]["dca_size_multiplier"],
            "rsi_lo": strat["signal_params"]["rsi_lo"],
        },
        "is": None,
        "oos": None,
        "status": "OK",
    }

    try:
        eng_is = PortfolioEngine(
            [symbol],
            [strat_run],
            is_start - WARMUP_MS,
            is_end,
            trade_start_ts=is_start,
            risk=None,
            base_frame=signal_tf,
            initial_capital=capital,
        )
        eng_is.run()
        raw_is = eng_is.get_results()
        m_is = portfolio_metrics(raw_is, is_start)
        out["is"] = {
            "ret_pct": m_is.get("ret_pct", 0.0),
            "mdd_pct": m_is.get("mdd_pct", 0.0),
            "sharpe": m_is.get("sharpe"),
            "win_rate": m_is.get("win_pct"),
            "trades": m_is.get("trades", 0),
        }
    except Exception as e:
        out["is"] = {"error": str(e), "ret_pct": 0.0, "trades": 0}
        out["status"] = "ERROR_IS"

    try:
        eng_oos = PortfolioEngine(
            [symbol],
            [strat_run],
            oos_start - WARMUP_MS,
            oos_end,
            trade_start_ts=oos_start,
            risk=None,
            base_frame=signal_tf,
            initial_capital=capital,
        )
        eng_oos.run()
        raw_oos = eng_oos.get_results()
        m_oos = portfolio_metrics(raw_oos, oos_start)
        out["oos"] = {
            "ret_pct": m_oos.get("ret_pct", 0.0),
            "mdd_pct": m_oos.get("mdd_pct", 0.0),
            "sharpe": m_oos.get("sharpe"),
            "win_rate": m_oos.get("win_pct"),
            "trades": m_oos.get("trades", 0),
        }
    except Exception as e:
        out["oos"] = {"error": str(e), "ret_pct": 0.0, "trades": 0}
        out["status"] = "ERROR_OOS"

    return out


def run_parameter_sweep(
    alpha_id: str = "dca_long",
    symbol: str = "BTC@perp",
    signal_tf: str = "15m",
    book_source: str = "explore",
    capital: float = 10000.0,
    max_workers: int = 3,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Quét 100 biến thể tham số trên 1 coin."""
    from backend.jobs.tasks import resolve_strategy

    t0 = time.time()
    rs = resolve_strategy(alpha_id, None, signal_tf, None, None, book_source)
    base_strategy = rs["strategy"]

    strat_list = generate_100_strategies(base_strategy)
    logger.info("Generated %d strategies for sweep on %s", len(strat_list), symbol)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [
            pool.submit(
                run_single_strategy_sweep,
                strat,
                symbol,
                signal_tf,
                DEFAULT_IS_START,
                DEFAULT_IS_END,
                DEFAULT_OOS_START,
                DEFAULT_OOS_END,
                capital,
            )
            for strat in strat_list
        ]
        for fut in futs:
            results.append(fut.result())

    valid = [r for r in results if r["oos"] and r["oos"].get("trades", 0) >= 5]
    valid_sorted = sorted(
        valid,
        key=lambda x: (
            x["oos"].get("sharpe") if x["oos"].get("sharpe") is not None else -999.0,
            x["oos"].get("ret_pct", -999.0),
        ),
        reverse=True,
    )

    top_1 = valid_sorted[0] if valid_sorted else results[0]
    best_strat = next(s for s in strat_list if s["id"] == top_1["cfg_id"])
    elapsed = round(time.time() - t0, 1)

    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "symbol": symbol,
        "base_alpha_id": alpha_id,
        "total_strategies": len(results),
        "valid_strategies": len(valid),
        "top_1_strategy_id": top_1["cfg_id"],
        "top_1_params": top_1["params"],
        "top_1_is": top_1["is"],
        "top_1_oos": top_1["oos"],
        "all_results": results,
    }

    out_dir = os.path.join(data_home(), "backtest", "scan")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "parameter_sweep_btc_100.json")
    write_json_atomic(out_file, summary, indent=2)

    logger.info("Sweep complete in %.1fs. Top 1: %s (OOS Sharpe: %s, Return: %s%%)",
                elapsed, top_1["cfg_id"], top_1["oos"].get("sharpe"), top_1["oos"].get("ret_pct"))

    return summary, best_strat


run_sweep_job = run_parameter_sweep
run_param_sweep = run_parameter_sweep



# ── Alpha Research (LLM) ────────────────────────────────────────────────────
def run_alpha_research(params=None):
    """Chạy job alpha_research với params {prompt, opts} -> dict kết quả."""
    from backend.analys.alpha.prompt import research
    p = params or {}
    prompt = str(p.get("prompt", ""))
    opts = dict(p.get("opts", {}) or {})
    s1 = research.validate_prompt(prompt, opts)
    if not s1.get("valid"):
        out = {"valid": False, "error": s1.get("reason"), "step1": s1}
    else:
        ideas = research.generate_ideas(s1.get("normalized_prompt") or prompt, opts)
        out = {"valid": True, "step1": s1, "step2": ideas}
    write_job_result(out)
    return out


__all__ = [
    "run_alpha_research",
    "run_scan_job",
    "scan_single_coin",
    "scan_universe",
    "run_universe_scan",
    "run_sweep_job",
    "generate_100_strategies",
    "run_parameter_sweep",
    "run_single_strategy_sweep",
    "OPTIMIZED_8_COINS",
    "DEFAULT_IS_START",
    "DEFAULT_IS_END",
    "DEFAULT_OOS_START",
    "DEFAULT_OOS_END",
    "WARMUP_MS",
]
