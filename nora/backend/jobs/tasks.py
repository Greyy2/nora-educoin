"""Các job (P9.6, P11): điểm vào khởi chạy của từng loại job (mỗi loại job một hàm run_<kind> mỏng).

Nội dung tính toán thuần -> backend/metrics/trades.py
Nội dung nạp dữ liệu -> backend/data/data.py
Nội dung chạy engine / WFA -> backend/jobs/evaluate.py
Nội dung xuất bản / quản lý sổ -> backend/strategies.py
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
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

from backend import strategies
from backend.models.params import DAY_MS as DAY, DEFAULT_CAPITAL, DEFAULT_TRAIN_RATIO, date_ms
from backend.models.storage import as_list, json_default, load_report, load_samples, options, write_job_result
from backend.data.data import check_data, data_info, load_prices, resolve_symbols, strategy_frames
from backend.nautilus.engine import provenance as engine_provenance
from backend.metrics.trades import build_result, stage_split
from backend.jobs.evaluate import (WARMUP, _pool_shared, candidates_from_ids, candidates_from_list, candidates_from_report, execute, load_items,
                                              plan_is_jobs, print_summary, run, run_benchmark, run_portfolio_wfa)

CUSTOM_BACKTEST_DEFAULTS = {"code": "", "symbols": None, "start": "", "end": "", "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": None, "position": None, "run_frame": ""}
BOOK_BACKTEST_DEFAULTS = {"book": "", "strategies": None, "symbols": "", "start": "", "end": "", "risk_per_trade": None, "stop_fill": "level", "regime": False, "timeframe": "1m", "out": "",
                          "data": "candle", "latency_ms": None, "gas_usd": None, "capital": None}
BOOK_WFA_DEFAULTS = {"report": "", "include_rejected": False, "candidates": "", "strategies": None, "symbols": "", "n": 3, "seed": 7,
                     "start": "", "end": "", "train_days": 120, "test_days": 30, "step_days": None, "min_is_trades": 10, "sims": 10_000,
                     "mc_seed": 1, "timeframe": "1m", "regime": "off", "risk_per_trade": None, "workers": "auto", "per_worker_mb": None, "resume": "", "max_configs": 200_000,
                     "force_large": False}


def stamp_provenance(prov: Dict[str, Any]) -> Dict[str, Any]:
    """Thêm LÊN provenance do engine dựng (nautilus/engine.py::provenance) nguồn job: job_id (thư mục job: env NORA_JOB_DIR; ngoài job -> None) và computed_at (UTC).
    Không định nghĩa lại trường nào của engine."""
    job_dir = os.environ.get("NORA_JOB_DIR")
    return {**prov, "job_id": os.path.basename(os.path.normpath(job_dir)) if job_dir else None,
            "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


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


def education_warm(params=None):
    """Job education_warm: chạy THẬT (cùng đường run_custom của Studio) các mẫu giáo dục chưa có cache, ghi kết quả vào strategies.
    params: keys (tuỳ chọn) = chỉ các mẫu này. -> [{key, status: cached|skipped|error, cache_key, error?}]; lỗi từng mẫu không dừng job."""
    a = options({"keys": None}, params)
    wanted = set(as_list(a.keys)) if a.keys else None
    out = []
    for s in load_samples():
        k = s.get("key")
        if wanted is not None and k not in wanted:
            continue
        try:
            spec = strategies.sample_run_spec(s)
            ck = strategies.sample_cache_key(s.get("code", ""), spec)
            if strategies.sample_get(ck) is not None:
                out.append({"key": k, "status": "skipped", "cache_key": ck})
                continue
            res = run_custom({"code": s.get("code", ""), **{f: spec.get(f) for f in strategies.SAMPLE_SPEC_FIELDS if spec.get(f) not in (None, "")}})
            strategies.sample_put(ck, res)
            out.append({"key": k, "status": "cached", "cache_key": ck})
        except Exception as e:   # noqa: BLE001 — ghi lỗi từng mẫu, chạy tiếp
            out.append({"key": k, "status": "error", "error": f"{type(e).__name__}: {e}"})
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
    source = "okx"
    os.environ.pop("NORA_SHARED_DATA_DIR", None)   # cột py_ tính trong tiến trình, không đi qua kho dùng chung
    from backend.jobs.workers import require_memory_limit
    require_memory_limit("custom_run")
    from datetime import datetime, timezone
    from backend.jobs.runner import Progress
    from backend.signal.nodes import DslError
    from backend.alpha.compile import compile_code
    from backend.signal.compute import SignalEngine
    from backend.alpha.plan import build_plan
    SignalEngine.MAX_BACKTEST_DAYS = 4000

    t0 = time.time()
    job_dir = os.environ.get("NORA_JOB_DIR")
    progress = Progress(job_dir, min_interval=0.05) if job_dir else None

    def _mark(step: int, total: int, stage_name: str, detail: str = ""):
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        txt = f"[{now_str}] [{step}/{total}] {stage_name}"
        if detail:
            txt += f" · {detail}"
        print(txt, flush=True)
        if progress:
            progress.start_stage(stage_name, total=total, done=step)

    _mark(1, 5, "Biên dịch chiến lược", "phân tích cú pháp AST & hợp đồng")
    try:
        program = compile_code(a.code)
    except DslError as e:
        raise ValueError(f"Lỗi biên dịch chiến lược: {e}") from None

    native = bool(getattr(program, "is_native", False))
    if native:      # Strategy Nautilus bản địa: không có plan DSL -> Plan thật (cùng kiểu build_plan trả về) để benchmark / chẩn đoán / build_result dùng chung
        from backend.alpha.plan import Plan
        names = resolve_symbols(as_list(a.symbols) or program.symbols or None)
        plan = Plan(strategies=[{"id": program.name}], symbols=[f"{n}@perp" for n in names], risk={}, base_frame=a.run_frame or program.timeframe)
    else:
        names = resolve_symbols(as_list(a.symbols))
        plan = build_plan(program, names, position=a.position or None, run_frame=a.run_frame)

    _mark(2, 5, "Nạp & xác thực dữ liệu", f"{len(plan.symbols)} tài sản · khung {plan.base_frame}")
    check_data(plan.symbols)
    start, end = date_ms(a.start), date_ms(a.end) + DAY
    if end <= start:
        raise ValueError("end phải sau start")
    capital = float(a.initial_capital) if a.initial_capital else DEFAULT_CAPITAL
    data, warns = data_info(plan.symbols, start, end, source)

    if native:
        _mark(3, 5, "Khởi tạo Nautilus Engine", f"Chiến lược {program.name} · venue OKX")

        def run_one(s: int, e: int, ev):
            from backend.nautilus.backtest import run_native
            ev.set()        # chạy thẳng từ catalog Nautilus: không có bước nạp tín hiệu tuần tự
            r = run_native(program.strategy_cls, plan.symbols, s, e, capital, plan.base_frame, strategy_id=program.name)
            r["provenance"] = engine_provenance(plan.base_frame)
            return r, _OpenPositions(r["open_positions"])
    else:
        _mark(3, 5, "Tính toán ma trận tín hiệu", f"khung {program.timeframe} với warmup lịch sử")

        def run_one(s: int, e: int, ev):
            return execute(plan, s, e, capital, loaded=ev)
    split = stage_split(start, end, float(a.train_ratio))
    # 4 lần chạy engine độc lập (chính, test, benchmark toàn kỳ, benchmark test): nạp dữ liệu TUẦN TỰ theo thứ tự này (lần rộng nhất dựng cửa sổ, các lần sau cắt từ bộ nhớ đệm),
    # kernel numba (nogil) chạy SONG SONG bằng thread. Kết quả từng lần không phụ thuộc lần khác (cùng chương trình/cấu hình/dữ liệu, warmup như lần chạy chính).
    steps = [("main", lambda ev: run_one(start, end, ev))]
    if split < end:     # giai đoạn test = lần chạy riêng bắt đầu từ vốn đầu tại đầu test
        steps.append(("test", lambda ev: run_one(split, end, ev)))
    # benchmark luôn long qua cùng engine (cache theo cấu hình: chỉ chạy một lần mỗi job/tiến trình)
    steps.append(("bench", lambda ev: run_benchmark(program, a, plan, names, start, end, capital, data, loaded=ev)))
    if split < end:     # benchmark của giai đoạn Test: cùng cửa sổ [mốc chia, end], vốn đầu
        steps.append(("test_bench", lambda ev: run_benchmark(program, a, plan, names, split, end, capital, data, loaded=ev)))

    _mark(4, 5, "Khớp lệnh", f"mô phỏng vị thế · {plan.base_frame}")
    got = run_parallel(steps)
    return _finish(program, plan, a, start, end, capital, data, warns, split, got, t0, progress, _mark)


class _OpenPositions:
    """Vị thế mở của một lần chạy bản địa, theo giao diện `open_positions()` mà build_result đọc từ engine."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows

    def open_positions(self) -> List[Dict[str, Any]]:
        return list(self.rows)


def _finish(program, plan, a, start: int, end: int, capital: float, data: Dict[str, Any], warns: List[str], split: int, got: Dict[str, Any], t0: float,
            progress, mark) -> Dict[str, Any]:
    """MỘT đuôi cho mọi nhánh của run_custom: kết quả các lần chạy (`got` của run_parallel) -> build_result + alpha_id / checklist / meta / provenance."""
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

    mark(5, 5, "Tính toán chỉ số & chẩn đoán", "Sharpe, Drawdown, PnL & báo cáo")
    out = build_result(program, plan, res, eng, a, start, end, capital, data, warns, test_res, split, bench=bench, inputs=diagnostic_inputs(plan, program, end),
                       test_bench=test_bench)
    from backend.strategies import evaluate_checklist, generate_alpha_id
    out["alpha_id"] = generate_alpha_id(program.code_hash, out["config"])
    out["checklist"] = evaluate_checklist(out)
    from backend.jobs.workers import peak_rss_mb
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}   # không tất định -> tách riêng
    out["provenance"] = stamp_provenance(out.get("provenance") or engine_provenance(plan.base_frame))

    if progress:
        progress.status = "done"
        progress.write(force=True)

    sim = out["metrics"]["simulate"]
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now_str}] Hoàn tất! Vốn cuối {out['final_equity']} | Lãi {sim['ret_pct']}% | MDD {sim['mdd_pct']}% | Lệnh {len(out['trades'])} | {out['meta']['wall_s']}s", flush=True)
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
    from backend.jobs.workers import require_memory_limit
    require_memory_limit("run_book_backtest")
    from backend.signal.compute import SignalEngine
    SignalEngine.MAX_BACKTEST_DAYS = 4000
    from backend.strategies import perp_symbols

    from backend.data.data import classify_symbols
    if a.data not in ("candle", "tick"):
        raise ValueError("data phải là candle|tick")
    symbols, venue = classify_symbols(as_list(a.symbols)) if as_list(a.symbols) else (perp_symbols(), "cex")
    if a.data == "tick" and venue != "dex":
        raise ValueError("data=tick chỉ dành cho tài sản DEX (chỉ DEX có tick swap on-chain)")
    from backend.data.data import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (synthetic / sai sha256 / thiếu dữ liệu -> từ chối)
    items, rpt, risk = load_items(a)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if a.data == "tick":   # cửa sổ do độ phủ tick quyết định (tick_run.run_tick cắt theo tick); thiếu đầu nào lấy hết độ phủ
        start, end = (date_ms(a.start) if a.start else None), (date_ms(a.end) + DAY if a.end else None)
        from backend.jobs.evaluate import run_tick
        out = run_tick(items, symbols, start, end, rpt, risk, a.stop_fill, a.timeframe or "1m", float(a.capital or DEFAULT_CAPITAL),
                       latency_ms=a.latency_ms, gas_usd=a.gas_usd)
    else:
        if not (a.start and a.end):  # thiếu một đầu -> lấy theo dữ liệu có sẵn
            from backend.data.data import read_manifest
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
    out["provenance"] = stamp_provenance(out["provenance"])
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
    from backend.data.data import require_perp
    require_perp(as_list(a.symbols), "WFA")
    if sum(map(bool, (a.report, a.candidates, a.strategies))) != 1:
        raise ValueError("chọn đúng một: report, candidates hoặc strategies")

    from backend.jobs.workers import check_memory_gate, require_memory_limit
    require_memory_limit("validate_book")
    from backend.models.params import BASE_RISK_PER_TRADE_PCT, RISK
    from backend.strategies import perp_symbols
    from backend.models.storage import run_dir as run_dir_of
    from backend.jobs.workers import resolve_workers
    from backend.jobs import evaluate as bsb
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
    from backend.data.data import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (trước khi fork pool để worker thừa kế cache gate)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if not cands:
        raise SystemExit("Không có chiến lược nào để kiểm (report không có chiến lược đạt? thử include_rejected)")
    start = date_ms(a.start) if a.start else w["dev1_end"]
    end = date_ms(a.end) if a.end else w["dev2_end"]

    from backend.jobs.runner import Progress, graceful_sigterm
    from backend.jobs.evaluate import ResultsStore

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
            res["provenance"] = stamp_provenance(engine_provenance(a.timeframe or "1m"))
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


# ══════════════════════════════════════════════════════════════════════════
# Job funnel_book: xuất bản sổ chung vốn từ phễu
# ══════════════════════════════════════════════════════════════════════════

