"""Các job (P9.6, P11): điểm vào khởi chạy của từng loại job (mỗi loại job một hàm run_<kind> mỏng).

Nội dung tính toán thuần -> backend/metrics/trades.py
Nội dung nạp dữ liệu -> backend/crawl/store.py
Nội dung chạy engine / WFA -> backend/optimize/search/evaluate.py
Nội dung xuất bản / quản lý sổ -> backend/optimize/book/registry.py
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import itertools
import json
import shutil
import subprocess
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.core.models import NORA_DIR
from backend.core.params import DAY_MS as DAY, DEFAULT_CAPITAL, DEFAULT_TRAIN_RATIO, date_ms, iso_date
from backend.crawl.store import (as_list, check_data, data_info, default_window, json_default, load_prices, load_report, load_samples, options,
                                 resolve_symbols, strategy_frames, write_job_result)
from backend.metrics.trades import build_result, downsample_series, label_stats, shock_stats, stage_split
from backend.optimize.funnel.storage import atomic_write_json
from backend.optimize.search.evaluate import (WARMUP, _pool_shared, candidates_from_ids, candidates_from_list, candidates_from_report, execute, load_items,
                                              plan_is_jobs, print_summary, run, run_benchmark, run_portfolio_wfa)
from backend.regime import regime as rg
from backend.regime.regime import by_regime

CUSTOM_BACKTEST_DEFAULTS = {"code": "", "symbols": None, "start": "", "end": "", "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": None, "position": None, "run_frame": ""}
BOOK_BACKTEST_DEFAULTS = {"book": "", "strategies": None, "symbols": "", "start": "", "end": "", "risk_per_trade": None, "stop_fill": "level", "regime": False, "timeframe": "1m", "out": "",
                          "data": "candle", "latency_ms": None, "gas_usd": None, "capital": None}
BOOK_WFA_DEFAULTS = {"report": "", "include_rejected": False, "candidates": "", "strategies": None, "symbols": "", "n": 3, "seed": 7,
                     "start": "", "end": "", "train_days": 120, "test_days": 30, "step_days": None, "min_is_trades": 10, "sims": 10_000,
                     "mc_seed": 1, "timeframe": "1m", "regime": "off", "risk_per_trade": None, "workers": "auto", "per_worker_mb": None, "resume": "", "max_configs": 200_000,
                     "force_large": False}
REGIME_REPORT_DEFAULTS = {"symbols": "", "start": "", "end": "", "event_pct": 12.0, "backtest": True, "timeframe": "15m"}
FUNNEL_BOOK_DEFAULTS = {"run_id": "", "alpha_ids": "", "risk_per_trade_pct": None, "wfa_job_id": "", "dry_run": False, "explore": False}


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=NORA_DIR, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:      # noqa: BLE001
        return None


def _clear_data_caches() -> None:
    from backend.core.backtest import data_cache_clear
    from backend.crawl.store import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()


def diagnostic_inputs(plan, program, end: int) -> Dict[str, Any]:
    """Dữ liệu thật cho chẩn đoán: giá ngày từng tài sản, chuỗi thị trường (BTC hoặc chỉ số rổ đều), nến khung chiến lược (binding_condition)."""
    from backend.metrics.trades import market_series
    out: Dict[str, Any] = {"prices": None, "market": None, "frames": None, "errors": []}
    try:
        out["prices"] = load_prices(plan.symbols, end)
        out["market"] = market_series(out["prices"])
    except Exception as e:      # noqa: BLE001 — chẩn đoán không được làm hỏng kết quả backtest
        out["errors"].append(f"giá thị trường: {e}")
    try:
        out["frames"] = strategy_frames(plan.symbols, program.timeframe, end, drop_filled=(program.timeframe == plan.base_frame))
    except Exception as e:      # noqa: BLE001
        out["errors"].append(f"nến khung chiến lược: {e}")
    return out


# ══════════════════════════════════════════════════════════════════════════
# Job custom_backtest: chiến lược Python chạy trên PortfolioEngine
# ══════════════════════════════════════════════════════════════════════════


def run_custom_backtest(params=None):
    """Chạy job custom_backtest với `params` -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
    out = run_custom(params)
    write_job_result(out)
    return out


def run_parallel(steps) -> Dict[str, Any]:
    """steps: [(tên, fn(loaded_event))]. Mỗi fn phải set `loaded` khi nạp xong dữ liệu (execute/run_benchmark làm việc đó); bước kế chỉ bắt đầu sau đó
    (nạp tuần tự, kernel song song). -> {tên: kết quả | ngoại lệ}. stdout chuyển hướng MỘT lần cho cả nhóm (redirect_stdout không an toàn khi lồng giữa thread)."""
    import contextlib
    import io
    import threading
    out: Dict[str, Any] = {}

    def work(name, fn, ev):
        try:
            out[name] = fn(ev)
        except BaseException as e:      # noqa: BLE001 — trả về cho người gọi quyết định (benchmark lỗi chỉ là cảnh báo)
            out[name] = e
        finally:
            ev.set()

    threads = []
    with contextlib.redirect_stdout(io.StringIO()):
        for name, fn in steps:
            ev = threading.Event()
            t = threading.Thread(target=work, args=(name, fn, ev), daemon=True)
            t.start()
            threads.append(t)
            ev.wait()
        for t in threads:
            t.join()
    return out


def run_custom(params=None):
    """Chạy backtest custom và trả kết quả dict (không tự ghi result.json)."""
    warnings.filterwarnings("ignore")
    a = options(CUSTOM_BACKTEST_DEFAULTS, params)
    if not isinstance(a.code, str) or not a.code.strip():
        raise ValueError("thiếu code")
    if not (a.start and a.end):
        raise ValueError("cần start và end (YYYY-MM-DD)")
    if not 0.1 <= float(a.train_ratio) <= 0.95:
        raise ValueError("train_ratio phải trong [0,1; 0,95]")
    from backend.crawl.store import exchange
    source = exchange()
    os.environ.pop("NORA_SHARED_DATA_DIR", None)   # cột py_ tính trong tiến trình, không đi qua kho dùng chung
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("custom_run")
    from backend.core.signal import DslError
    from backend.alpha.compile import compile_code
    from backend.core.backtest import build_plan
    try:
        program = compile_code(a.code)
    except DslError as e:
        raise ValueError(f"Lỗi biên dịch chiến lược: {e}") from None
    names = resolve_symbols(as_list(a.symbols))
    plan = build_plan(program, names, position=a.position or None, run_frame=a.run_frame or None)
    check_data(plan.symbols)
    start, end = date_ms(a.start), date_ms(a.end) + DAY
    if end <= start:
        raise ValueError("end phải sau start")
    capital = float(a.initial_capital) if a.initial_capital else DEFAULT_CAPITAL
    data, warns = data_info(plan.symbols, start, end, source)
    t0 = time.time()
    print(f"chiến lược {program.name} [{program.code_hash}] | {len(plan.symbols)} tài sản | {iso_date(start)} → {iso_date(end - DAY)} "
          f"| khung {program.timeframe} chạy {plan.base_frame} | vốn {capital:g}", flush=True)
    split = stage_split(start, end, float(a.train_ratio))
    # 4 lần chạy engine độc lập (chính, test, benchmark toàn kỳ, benchmark test): nạp dữ liệu TUẦN TỰ theo thứ tự này (lần rộng nhất dựng cửa sổ, các lần sau cắt từ bộ nhớ đệm),
    # kernel numba (nogil) chạy SONG SONG bằng thread. Kết quả từng lần không phụ thuộc lần khác (cùng chương trình/cấu hình/dữ liệu, warmup như lần chạy chính).
    steps = [("main", lambda ev: execute(plan, start, end, capital, loaded=ev))]
    if split < end:     # giai đoạn test = lần chạy riêng bắt đầu từ vốn đầu tại đầu test
        steps.append(("test", lambda ev: execute(plan, split, end, capital, loaded=ev)))
    # benchmark luôn long qua cùng engine (cache theo cấu hình: chỉ chạy một lần mỗi job/tiến trình)
    steps.append(("bench", lambda ev: run_benchmark(program, a, plan, names, start, end, capital, data, loaded=ev)))
    if split < end:     # benchmark của giai đoạn Test: cùng cửa sổ [mốc chia, end], vốn đầu
        steps.append(("test_bench", lambda ev: run_benchmark(program, a, plan, names, split, end, capital, data, loaded=ev)))
    got = run_parallel(steps)
    if isinstance(got["main"], BaseException):
        raise got["main"]
    res, eng = got["main"]
    test_res = got["test"][0] if "test" in got and not isinstance(got["test"], BaseException) else None
    if isinstance(got.get("test"), BaseException):
        raise got["test"]
    bench = test_bench = None
    if isinstance(got["bench"], BaseException):     # thiếu benchmark thì chẩn đoán market_comparison ghi available=False, không bịa số
        warns = warns + [f"không chạy được benchmark luôn long: {got['bench']}"]
    else:
        bench = got["bench"]
    if "test_bench" in got:
        if isinstance(got["test_bench"], BaseException):    # thiếu thì series.stages.test.benchmark = None, không co dãn benchmark toàn kỳ
            warns = warns + [f"không chạy được benchmark giai đoạn test: {got['test_bench']}"]
        else:
            test_bench = got["test_bench"]
    out = build_result(program, plan, res, eng, a, start, end, capital, data, warns, test_res, split, bench=bench, inputs=diagnostic_inputs(plan, program, end),
                       test_bench=test_bench)
    from backend.optimize.book.registry import evaluate_checklist, generate_alpha_id
    out["alpha_id"] = generate_alpha_id(program.code_hash, out["config"])
    out["checklist"] = evaluate_checklist(out)
    from backend.optimize.process.workers import peak_rss_mb
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}   # không tất định -> tách riêng

    sim = out["metrics"]["simulate"]
    print(f"vốn cuối {out['final_equity']} | lãi {sim['ret_pct']}% | MDD {sim['mdd_pct']}% | lệnh đóng {len(out['trades'])} "
          f"mở {len(out['positions_open'])} | {out['meta']['wall_s']}s", flush=True)
    return out





# ══════════════════════════════════════════════════════════════════════════
# Job backtest: PortfolioEngine cho sổ chiến lược
# ══════════════════════════════════════════════════════════════════════════

def run_book_backtest(params=None):
    """Chạy job backtest với `params` -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(BOOK_BACKTEST_DEFAULTS, params)
    if a.stop_fill not in ("level", "extreme"):
        raise ValueError("stop_fill phải là level|extreme")
    if a.book and a.strategies:
        raise ValueError("chọn một: book hoặc strategies")
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("run_book_backtest")
    from backend.optimize.book.build import perp_symbols

    from backend.crawl.store import classify_symbols
    if a.data not in ("candle", "tick"):
        raise ValueError("data phải là candle|tick")
    symbols, venue = classify_symbols(as_list(a.symbols)) if as_list(a.symbols) else (perp_symbols(), "cex")
    if a.data == "tick" and venue != "dex":
        raise ValueError("data=tick chỉ dành cho tài sản DEX (chỉ DEX có tick swap on-chain)")
    from backend.crawl.store import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (synthetic / sai sha256 / thiếu dữ liệu -> từ chối)
    items, rpt, risk = load_items(a)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if a.data == "tick":   # cửa sổ do độ phủ tick quyết định (tick_run.run_tick cắt theo tick); thiếu đầu nào lấy hết độ phủ
        start, end = (date_ms(a.start) if a.start else None), (date_ms(a.end) + DAY if a.end else None)
        from backend.optimize.search.evaluate import run_tick
        out = run_tick(items, symbols, start, end, rpt, risk, a.stop_fill, a.timeframe or "1m", float(a.capital or DEFAULT_CAPITAL),
                       latency_ms=a.latency_ms, gas_usd=a.gas_usd)
    else:
        if not (a.start and a.end):  # thiếu một đầu -> lấy theo dữ liệu có sẵn
            from backend.crawl.store import read_manifest
            ms = [read_manifest(s) for s in symbols]
            if not all(ms):
                raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
            data_start = max(int(m["start_ts"]) for m in ms) + WARMUP
            data_end = min(int(m["end_ts"]) for m in ms)
        start = date_ms(a.start) if a.start else data_start
        end = date_ms(a.end) + DAY if a.end else data_end
        if end <= start:
            raise SystemExit("end phải sau start")
        print(f"sổ {[i for i, _ in items]} | {len(symbols)} tài sản | {pd.Timestamp(start, unit='ms'):%Y-%m-%d} → "
              f"{pd.Timestamp(end, unit='ms'):%Y-%m-%d} | rủi ro/lệnh {rpt}% | SL {a.stop_fill}", flush=True)
        out = run(items, symbols, start, end, rpt, a.stop_fill, risk, regime=bool(a.regime), base_frame=a.timeframe or "1m",
                  venue=venue, initial_capital=a.capital)
    print(f"lãi {out['ret_pct']}%  MDD {out['mdd_pct']}%  sharpe {out['sharpe']}  lệnh {out['trades']}  "
          f"+{out['symbols_positive']}/{len(symbols)}  kill={'có' if out['halted_at'] else 'không'}  "
          f"{json.dumps(out['by_strategy'], ensure_ascii=False, default=json_default)}", flush=True)
    print(f"thời gian {out['meta']['wall_s']}s | đỉnh RAM {out['meta']['peak_rss_mb']} MB", flush=True)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, default=json_default)
        print("ghi:", a.out)
    write_job_result(out)  # chỉ khi chạy như job API (env NORA_JOB_DIR)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Job WFA danh mục: Walk-Forward cả sổ + Monte Carlo lợi suất ngày MTM
# ══════════════════════════════════════════════════════════════════════════

def run_book_wfa(params=None):
    """Chạy job WFA với `params` -> báo cáo (cũng ghi report.json + $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(BOOK_WFA_DEFAULTS, params)
    from backend.crawl.store import require_perp
    require_perp(as_list(a.symbols), "WFA")
    if sum(map(bool, (a.report, a.candidates, a.strategies))) != 1:
        raise ValueError("chọn đúng một: report, candidates hoặc strategies")

    from backend.optimize.process.workers import check_memory_gate, require_memory_limit
    require_memory_limit("validate_book")
    from backend.core.params import BASE_RISK_PER_TRADE_PCT, RISK
    from backend.optimize.book.build import perp_symbols
    from backend.crawl.store import run_dir as run_dir_of
    from backend.optimize.process.workers import resolve_workers
    from backend.optimize.book import build as bsb
    from backend.wfa.wfa import generate_folds, PortfolioWfaConfig

    per_worker_mb = a.per_worker_mb or bsb.PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "validate_book")
    check_memory_gate(workers * per_worker_mb, f"validate_book --workers {workers}")

    risk, rpt, report = RISK, BASE_RISK_PER_TRADE_PCT, None
    if a.report:
        stage_a, report = load_report(a.report)
        cands = candidates_from_report(stage_a, report, a.n, a.include_rejected)
        risk = report.get("risk") or RISK
        rpt = ((report.get("book") or {}).get("risk_per_trade_pct")) or rpt
        w = {k: date_ms(v) for k, v in report["windows"].items()}
    else:
        cands = (candidates_from_list(a.strategies) if a.strategies
                 else candidates_from_ids(as_list(a.candidates), a.n, a.seed))
        w = bsb.windows(perp_symbols())
    symbols = [x if "@" in x else f"{x}@perp" for x in as_list(a.symbols)] or perp_symbols()
    from backend.crawl.store import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (trước khi fork pool để worker thừa kế cache gate)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if not cands:
        raise SystemExit("Không có chiến lược nào để kiểm (report không có chiến lược đạt? thử include_rejected)")
    start = date_ms(a.start) if a.start else w["dev1_end"]
    end = date_ms(a.end) if a.end else w["dev2_end"]

    from backend.optimize.process.process import Progress, graceful_sigterm
    from backend.optimize.funnel.storage import ResultsStore

    folds = generate_folds(int(start), int(end), a.train_days, a.test_days, a.step_days)
    n_cfg = sum(len(c["configs"]) for c in cands)
    is_total = len(folds) * n_cfg
    if is_total > a.max_configs and not a.force_large:
        raise SystemExit(f"Từ chối: {is_total:,} job IS ({len(folds)} fold × {n_cfg} cấu hình) vượt max_configs {a.max_configs:,}. "
                         f"Giảm n / số chiến lược hoặc đặt force_large.")
    if a.resume:
        run_dir = os.path.abspath(a.resume if os.path.isabs(a.resume) or os.path.isdir(a.resume)
                                  else os.path.join(run_dir_of("wfa"), a.resume))
        if not os.path.isfile(os.path.join(run_dir, "results.sqlite")):
            raise SystemExit(f"resume: {run_dir} không có results.sqlite")
    else:
        base = time.strftime("%Y%m%d_%H%M%S")
        for k in itertools.count(1):
            run_dir = run_dir_of("wfa", base if k == 1 else f"{base}_{k}")
            if not os.path.exists(os.path.join(run_dir, "results.sqlite")):
                break
        os.makedirs(run_dir, exist_ok=True)
    shared_dir = os.path.join(run_dir, "_shared")
    cfg = PortfolioWfaConfig(train_days=a.train_days, test_days=a.test_days, step_days=a.step_days,
                             min_is_trades=a.min_is_trades, mc_simulations=a.sims, mc_seed=a.mc_seed)
    print(f"chiến lược {[(c['id'], len(c['configs'])) for c in cands]} | workers={workers} | trần mỗi worker {per_worker_mb:.0f} MB", flush=True)
    store = ResultsStore(run_dir)
    progress = Progress(run_dir)
    t0 = time.time()
    try:
        with graceful_sigterm(progress):
            if a.resume:
                print(f"[resume] {run_dir}: kho đã có {store.count():,} kết quả", flush=True)
            os.makedirs(shared_dir, exist_ok=True)
            _, is_jobs0 = plan_is_jobs(cands, folds, symbols, risk, rpt, shared_dir, a.timeframe or "1m")
            t_cal = time.time()
            _pool_shared(is_jobs0[:1], 1, "[WFA] hiệu chỉnh", shared_dir, store, "wfa_is", None)
            sec = time.time() - t_cal
            n_jobs = is_total + 2 * len(folds)
            est = {"is_jobs": is_total, "oos_jobs": 2 * len(folds), "sec_per_job": round(sec, 3), "workers": workers,
                   "eta_s": round(n_jobs * sec / workers, 1)}
            print(f"[estimate] {n_jobs:,} job ({is_total:,} IS + {2 * len(folds)} OOS) × {sec:.1f} s/job / {workers} worker ≈ "
                  f"{est['eta_s'] / 60:.1f} phút", flush=True)
            with open(os.path.join(run_dir, "estimate.json"), "w", encoding="utf-8") as fh:
                json.dump(est, fh, ensure_ascii=False, indent=1)
            progress.set_estimate(est)
            res = run_portfolio_wfa(cands, symbols, start, end, cfg, risk, rpt, workers, shared_dir, store=store, progress=progress,
                                    base_frame=a.timeframe or "1m", regime=a.regime or "off",
                                    regime_learn_from=w["start"] if (a.regime or "off") != "off" else None)
            res["source"] = {"report": os.path.abspath(a.report) if a.report else None, "include_rejected": a.include_rejected,
                             "strategies": bool(a.strategies),
                             "wall_s": round(time.time() - t0, 1)}
            if os.path.isdir(shared_dir):
                shutil.rmtree(shared_dir, ignore_errors=True)
            path = os.path.join(run_dir, "report.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=json_default)
            print_summary(res)
            print(f"thời gian {res['source']['wall_s']:.0f}s | báo cáo: {path}")
            store.flush()
            progress.finish("done")
            write_job_result({**res, "report_path": path})
    finally:
        store.close()
    return res


# ══════════════════════════════════════════════════════════════════════════
# Job regime_report: báo cáo độ chính xác regime + so sánh backtest
# ══════════════════════════════════════════════════════════════════════════

def _book_items():
    from backend.optimize.book.build import load_presets, CANDIDATES
    from backend.core.params import BASE_RISK_PER_TRADE_PCT
    presets = load_presets()
    items, rpts = [], []
    for c in CANDIDATES:
        prm = dict(presets[c["id"]]["params"])
        if prm.get("risk_per_trade_pct") is not None:
            rpts.append(float(prm["risk_per_trade_pct"]))
        prm.pop("risk_per_trade_pct", None)
        items.append((c["id"], prm))
    return items, (min(rpts) if rpts else BASE_RISK_PER_TRADE_PCT)


def _summary(out: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("ret_pct", "mdd_pct", "sharpe", "sortino", "calmar", "trades", "win_rate", "profit_factor", "final_equity", "halted_at")
    return {**{k: out.get(k) for k in keys}, "by_strategy": out.get("by_strategy")}


def _pool_states(per_symbol: Dict[str, Any]) -> Dict[str, Any]:
    tot = sum(v["minutes"] for v in per_symbol.values()) or 1
    out = {}
    for name in rg.NAMES:
        rows = [(v["minutes"], v["states"][name]) for v in per_symbol.values() if name in v["states"]]
        if not rows:
            continue
        n = sum(r["fwd24_n"] for _, r in rows) or 1
        avg = lambda k: round(sum((r[k] or 0) * r["fwd24_n"] for _, r in rows) / n, 3)  # noqa: E731
        out[name] = {"share_pct": round(sum(m * r["share_pct"] for m, r in rows) / tot, 2),
                     "fwd24_mean_pct": avg("fwd24_mean_pct"), "fwd24_up_pct": avg("fwd24_up_pct"), "fwd24_abs_pct": avg("fwd24_abs_pct")}
    return out


def run_regime_report(params=None):
    warnings.filterwarnings("ignore")
    a = options(REGIME_REPORT_DEFAULTS, params)
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("regime_report")
    from backend.core.params import REGIME_MAP
    from backend.optimize.book.build import perp_symbols
    from backend.crawl.store import read_manifest, require_data_ok_or_exit
    symbols = [s if "@" in s else f"{s}@perp" for s in as_list(a.symbols)] or perp_symbols()
    require_data_ok_or_exit(symbols)
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    start = date_ms(a.start) if a.start else max(int(m["start_ts"]) for m in ms) + WARMUP
    end = date_ms(a.end) + DAY if a.end else min(int(m["end_ts"]) for m in ms)
    t0 = time.time()
    tf = a.timeframe
    report: Dict[str, Any] = {"config": {"symbols": symbols, "start": start, "end": end, "event_pct": float(a.event_pct), "timeframe": tf,
                                         "classifier": rg.DEFAULTS, "regime_map": REGIME_MAP},
                              "labels": {}, "shocks": {}}
    series = {}
    for sym in symbols:
        s = rg.series(sym, start - WARMUP, end, base_frame=tf)
        series[sym] = {"t": s["t"], "labels": s["labels"]}
        report["labels"][sym] = label_stats(s, start)
        report["shocks"][sym] = shock_stats(s, start, float(a.event_pct))
        sh = report["shocks"][sym]
        print(f"{sym}: đổi {report['labels'][sym]['switches_per_30d']}/30 ngày | sập {sh['CRASH']['detected']}/{sh['CRASH']['events']} "
              f"trễ {sh['CRASH']['median_lag_min']}p | tăng dựng {sh['SURGE']['detected']}/{sh['SURGE']['events']}", flush=True)
        del s
    report["labels_all"] = _pool_states(report["labels"])
    if a.backtest:
        items, rpt = _book_items()
        off = run(items, symbols, start, end, rpt, "level", None, base_frame=tf)
        print(f"tắt regime: lãi {off['ret_pct']}% MDD {off['mdd_pct']}% sharpe {off['sharpe']} lệnh {off['trades']}", flush=True)
        on = run(items, symbols, start, end, rpt, "level", None, regime=True, base_frame=tf)
        print(f"bật regime: lãi {on['ret_pct']}% MDD {on['mdd_pct']}% sharpe {on['sharpe']} lệnh {on['trades']}", flush=True)
        report["backtest"] = {"risk_per_trade_pct": rpt, "off": _summary(off), "on": _summary(on),
                              "off_by_regime": by_regime(off["trade_list"], series),
                              "on_by_regime": by_regime(on["trade_list"], series),
                              "equity_off": off.get("daily_nav"), "equity_on": on.get("daily_nav")}
    report["meta"] = {"wall_s": round(time.time() - t0, 1)}
    print(f"thời gian {report['meta']['wall_s']}s", flush=True)
    write_job_result(report)
    return report


# ══════════════════════════════════════════════════════════════════════════
# Job funnel_book: xuất bản sổ chung vốn từ phễu
# ══════════════════════════════════════════════════════════════════════════

def run_funnel_book(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(FUNNEL_BOOK_DEFAULTS, params)
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("funnel_book")
    from backend.optimize.process import process as batch_jobs
    from backend.crawl.store import alpha_dir as alphas_dir
    from backend.optimize.funnel.stages import funnel_root
    from backend.optimize.book.registry import write_book, write_explore_book, build_report, book_source
    run_dir = os.path.join(funnel_root(), a.run_id)
    wfa = {}
    if a.wfa_job_id or not a.explore:
        job = batch_jobs.status(a.wfa_job_id)
        if not job or job.get("kind") != "book_wfa" or job.get("status") != "done":
            raise SystemExit(f"wfa_job_id {a.wfa_job_id} không phải job book_wfa đã xong")
        wfa = job["result"]
    rep = build_report(run_dir, as_list(a.alpha_ids), float(a.risk_per_trade_pct), wfa, explore=bool(a.explore))
    h = rep["book"]["final"]["holdout"]
    print(f"holdout level {h['level']['ret_pct']}% / extreme {h['extreme']['ret_pct']}% (MDD {h['extreme']['mdd_pct']}%) -> "
          f"{'ĐẠT' if rep['book']['holdout_pass'] else 'TRƯỢT'}", flush=True)
    out = {"report": rep, "written": []}
    if not a.dry_run:
        source = book_source(a.run_id, a.wfa_job_id, time.strftime('%Y-%m-%d'))
        repo = os.path.abspath(os.path.join(alphas_dir(), "..", ".."))
        out["written"] = (write_explore_book(rep, os.path.join(alphas_dir(), "explore"), source=source, repo_dir=repo) if a.explore
                          else write_book(rep, alphas_dir(), source=source, repo_dir=repo))
        print("ghi:", out["written"], flush=True)
    write_job_result(out)
    return out
