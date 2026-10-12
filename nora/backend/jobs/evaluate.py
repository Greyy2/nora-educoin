"""Chạy hàng loạt (P9.6): thư viện backtest danh mục (BacktestJob, make_engine, run, result_payload), phía WORKER của phễu (w_*) và kho dữ liệu dùng chung (SharedExporter).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6). Gồm backtest tick DEX (tick_run; ở đây để engine_version băm được — engine_inputs có evaluate.py).
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import hashlib
import heapq
import io
import itertools
import json
import math
import shutil
import sqlite3
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.models.params import DAY_MS as DAY
from backend.alpha.plan import display_name
from backend.data.data import catalog_digest, default_catalog_path, read_manifest

if TYPE_CHECKING:
    from backend.nautilus.engine import BacktestEngine, PortfolioEngine
from backend.metrics.metrics import portfolio_metrics
from backend.models.models import NORA_DIR
from backend.jobs.workers import pool_imap_bounded
from backend.models.storage import json_default


# ══════════════════════════════════════════════════════════════════════════
# Job backtest (POST /api/studio/book/backtest -> jobs/runner.py -> run_job): một lần PortfolioEngine cho sổ chiến lược.
#
# Tham số (run_job params; mặc định ở DEFAULTS):
#   book        đường dẫn book.json (mặc định data/alpha/book.json) — chiến lược + tham số + rủi ro/lệnh + giới hạn danh mục của sổ đã chốt
#   strategies  [{"id": "trend_long", "params": {...}}] thay cho book; tham số thiếu lấy mức GIỮA của không gian tham số ứng viên
#   start, end  YYYY-MM-DD UTC (ngày kết thúc tính CẢ ngày); mặc định = toàn bộ dữ liệu sau warmup
#   risk_per_trade  % vốn rủi ro mỗi lệnh (mặc định: của sổ, hoặc mức chuẩn 0,5%); stop_fill level|extreme (mặc định level)
#   symbols     perp ("BTC", "BTC@perp") HOẶC DEX ("AERO", "dex:AERO"; spot, chỉ chân LONG) — không trộn hai loại; DEX không bị ép "@perp"
#   data        candle (mặc định: engine nến như mọi tài sản) | tick (chỉ DEX: mỗi swap on-chain là một bước khớp lệnh, chi phí AMM đúng trên dự trữ pool —
#               jobs/evaluate.py.run_tick); latency_ms / gas_usd chỉ cho data=tick (mặc định theo mạng của pool: NETWORKS[mạng]); capital vốn ban đầu
#   out         (tuỳ chọn) ghi kết quả JSON ra đường dẫn này
# Kết quả: số đo danh mục (portfolio_metrics) + by_symbol/by_strategy + lệnh + đường vốn (<= 2000 điểm) -> $NORA_JOB_DIR/result.json.
# ══════════════════════════════════════════════════════════════════════════


WARMUP = 20 * DAY            # nạp thêm 20 ngày trước start để chỉ báo ấm (chỉ số đo từ start trở đi)
# Đo 01/10/2026 (dữ liệu dùng chung qua mmap, 8 tài sản perp, dev1 ≈ 14 tháng): VmHWM 560–590 MB mỗi worker (đã gồm trang mmap
# dùng chung ~440 MB/giai đoạn; phần riêng ~150 MB) × 1,3 dự phòng. Đo lại bằng dòng `đỉnh RAM/worker`, ghi đè bằng per_worker_mb
# khi kích thước dữ liệu hoặc ngân sách cache đổi; trần cgroup (run_limited.sh) mới là rào cứng.
PER_WORKER_MB = 800


def windows(symbols):
    """Cửa sổ dev1/dev2 (ms) theo dữ liệu thật của các tài sản: bắt đầu sau WARMUP, dev1 = 40%, dev2 đến 80%."""
    ms = [read_manifest(s) for s in symbols]
    start = max(int(m["start_ts"]) for m in ms) + WARMUP
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    return {"start": start, "dev1_end": start + int(span * 0.4), "dev2_end": start + int(span * 0.8), "end": end}
MAX_DAYS = 4000


def execute(plan, start: int, end: int, initial_capital: float, close_at_end: bool = False, loaded=None):
    """PortfolioEngine cho một Plan (signal/compute.py.build_plan) -> (get_results(), engine). Chương trình phải đã được compile_code (đăng ký).
    loaded: threading.Event (chế độ chạy song song, xem tasks.run_parallel) — nạp dữ liệu dưới khoá toàn cục rồi báo `loaded` để lần chạy kế tiếp bắt đầu nạp
    (thứ tự nạp cố định -> bộ nhớ đệm cửa sổ của lần chạy rộng nhất phục vụ các lần sau); phần kernel chạy song song (numba nogil). Người gọi tự chuyển hướng stdout."""
    from backend.nautilus.engine import BacktestEngine, PortfolioEngine
    from backend.alpha.plan import RiskConfig
    BacktestEngine.MAX_BACKTEST_DAYS = max(BacktestEngine.MAX_BACKTEST_DAYS, MAX_DAYS)
    eng = PortfolioEngine(plan.symbols, plan.strategies, start - WARMUP, end, trade_start_ts=start, initial_capital=initial_capital,
                          risk=RiskConfig.from_dict(plan.risk), venue=plan.venue, close_at_end=close_at_end, base_frame=plan.base_frame,
                          shared_dir=None)
    if loaded is not None:
        try:
            eng.load_data()
        finally:
            loaded.set()
        eng.run()
        return eng.get_results(), eng
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    return eng.get_results(), eng


BENCH_CODE = ('class AlwaysLong(SimpleAlgorithm):\n    timeframe = "{tf}"\n    def __algorithm__(self):\n'
              '        self.set_positions(self.data.pv_close > 0, position=1)\n')
NO_EXIT_POSITION = {"stop_loss_rate": 0.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0}
_BENCH_CACHE: Dict[str, Dict[str, Any]] = {}


def run_benchmark(program, a, plan, names: List[str], start: int, end: int, capital: float, data: Dict[str, Any], loaded=None) -> Optional[Dict[str, Any]]:
    """Benchmark "luôn long" self.set_positions(self.data.pv_close > 0, position=1) chạy qua CÙNG đường engine."""
    from backend.models.params import FRAME_MS
    from backend.models.params import resolve_costs
    from backend.alpha.compile import compile_code
    from backend.alpha.plan import build_plan
    from backend.metrics.trades import daily_series
    position = {**(program.position_overrides or {}), **(a.position or {})}
    taker = resolve_costs(plan.venue, "perp", position.get("fee_rate"), position.get("slippage_rate"), position.get("maker_fee_rate"))[0]
    position.update(NO_EXIT_POSITION)
    position.update(sizing="margin_pct", leverage=1, order_size_pct=100.0 / len(names) / (1.0 + taker) * (1.0 - 1e-9))
    key = json.dumps([plan.symbols, program.timeframe, plan.base_frame, start, end, capital, data.get("source"), data.get("sha256_1m"), sorted(position.items())],
                     sort_keys=True, default=str)
    hit = _BENCH_CACHE.get(key)
    if hit is not None:
        if loaded is not None:
            loaded.set()
        return hit
    bench_prog = compile_code(BENCH_CODE.format(tf=program.timeframe))
    bplan = build_plan(bench_prog, names, position=position, run_frame=plan.base_frame)
    bplan.risk = {"max_positions": max(1, len(names)), "max_per_symbol": 1, "max_gross_exposure": 1e6, "kill_switch_dd_pct": 0.0, "max_open_risk_pct": 0.0, "dd_throttle_pct": 0.0}
    res, _ = execute(bplan, start, end, capital, loaded=loaded) if loaded is not None else execute(bplan, start, end, capital)
    ser = daily_series(res["equity_curve"], start, end, FRAME_MS[bplan.base_frame], capital)
    out = {"times": ser["times"], "equity": ser["equity"], "program_hash": bench_prog.code_hash, "strategies": [s["id"] for s in bplan.strategies],
           "label": "Luôn long (position=1) cùng rổ/ngày/vốn, chia đều, đòn bẩy 1, không SL/TP/trailing/timeout/kill-switch", "symbols": bplan.symbols}
    _BENCH_CACHE[key] = out
    return out


def _mid_params(candidate, params):
    """Điền tham số thiếu bằng mức giữa của không gian tham số (để {"id": "trend_long"} chạy được)."""
    out = dict(params or {})
    for key, values in candidate["space"].items():
        out.setdefault(key, values[len(values) // 2])
    return out


def load_items(a):
    """-> (items [(id, params)], rủi ro/lệnh mặc định, dict RiskConfig)."""
    from backend.models.params import BASE_RISK_PER_TRADE_PCT, RISK
    from backend.strategies import BY_ID
    by_id = BY_ID
    if a.strategies:
        raw = a.strategies
        if not isinstance(raw, list) or not raw:
            raise SystemExit("strategies phải là danh sách không rỗng")
        items = []
        for s in raw:
            if s.get("id") not in by_id:
                raise SystemExit(f"Không có chiến lược: {s.get('id')}; có: {sorted(by_id)}")
            items.append((s["id"], _mid_params(by_id[s["id"]], s.get("params"))))
    from backend.models.storage import alpha_file
    path = a.book or alpha_file("book")
    if not os.path.isfile(path):
        alt = os.path.join(NORA_DIR, "data", "alpha", "book.json")
        if os.path.isfile(alt):
            path = alt
    with open(path, encoding="utf-8") as fh:
        book = json.load(fh)
    items = [(s["id"], s["params"]) for s in book["strategies"]]
    bad = [i for i, _ in items if i not in by_id]
    if bad:
        raise SystemExit(f"book {path} có chiến lược không còn trong thư viện: {bad}")
    return items, book.get("risk_per_trade_pct") or BASE_RISK_PER_TRADE_PCT, book.get("risk") or RISK


from backend.metrics.metrics import result_payload


class BacktestJob(NamedTuple):
    """Đặc tả MỘT lần backtest danh mục — dùng chung cho dựng sổ (strategies.py), WFA (wfa/wfa) và phễu ((phễu đã gỡ)).
    items: [(id chiến lược lõi, tham số)]; window: (start, end) ms — chỉ số đo từ start, nạp thêm WARMUP trước đó; symbols None = vũ trụ
    perp của sổ; shared_dir None = env NORA_SHARED_DATA_DIR (backend/jobs/evaluate.py); base_frame = khung chạy (nến mô phỏng)."""
    items: List[Tuple[str, Dict[str, Any]]]
    window: Tuple[int, int]
    stop_fill: str
    risk: Dict[str, Any]
    rpt: float
    symbols: Optional[List[str]] = None
    shared_dir: Optional[str] = None
    base_frame: str = "1m"
    regime: Optional[Dict[str, Any]] = None   # {id chiến lược: cấu hình regime} (metrics/regime.learn_map); thiếu id -> không lọc


def make_engine(job: BacktestJob):
    """PortfolioEngine của job (chưa nạp dữ liệu) + mốc bắt đầu đo. Khung tín hiệu nhỏ hơn khung chạy được nâng lên (params.modes.lift_frames)."""
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.plan import RiskConfig
    from backend.strategies import lift_frames
    from backend.models.params import materialize
    from backend.strategies import perp_symbols, BY_ID
    by_id = BY_ID
    regime = job.regime or {}
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, job.base_frame), regime=regime.get(cid) or False,
                              stop_fill=job.stop_fill, risk_per_trade_pct=job.rpt) for cid, prm in job.items]
    start, end = job.window
    return PortfolioEngine(list(job.symbols or perp_symbols()), strategies, start - WARMUP, end, trade_start_ts=start,
                           risk=RiskConfig.from_dict(job.risk), shared_dir=job.shared_dir, base_frame=job.base_frame), start


def run(items, symbols, start, end, rpt, stop_fill, risk, extra_strategies=None, initial_capital=None, close_at_end=True,
        warmup=WARMUP, regime=False, base_frame="1m", venue="cex"):
    """extra_strategies: chiến lược dựng sẵn (dict của PortfolioEngine, có thể có khoá "symbols") chạy cùng sổ — dùng cho feed
    giả lập. close_at_end=False: giữ vị thế còn mở cuối dữ liệu (kết quả thêm `open_positions`); mặc định như backtest thường.
    venue="dex": symbols là tài sản DEX ("dex:AERO") — spot, đòn bẩy 1, chỉ chân LONG, phí pool từ manifest (builder.build_params); mặc định "cex" = perp."""
    from backend.models.params import materialize
    from backend.strategies import BY_ID
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.plan import RiskConfig
    from backend.jobs.workers import peak_rss_mb
    by_id = BY_ID
    from backend.strategies import lift_frames
    spot = {}
    if venue == "dex":
        from backend.alpha import plan as dex
        dex.require_long_legs([cid for cid, _ in items], BY_ID)
        spot = dex.SPOT_POSITION
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, base_frame), regime=regime, stop_fill=stop_fill,
                              risk_per_trade_pct=rpt, **spot) for cid, prm in items]
    strategies += list(extra_strategies or [])
    t0 = time.time()
    kw = {} if initial_capital is None else {"initial_capital": float(initial_capital)}
    eng = PortfolioEngine(symbols, strategies, start - warmup, end, trade_start_ts=start, risk=RiskConfig.from_dict(risk),
                          close_at_end=close_at_end, base_frame=base_frame, venue=venue, **kw)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    out = result_payload(res, start, end)
    out["config"] = {"strategies": [{"id": i, "params": p} for i, p in items]
                     + [{"id": x["id"], "params": x["position"]} for x in extra_strategies or []], "symbols": symbols, "risk_per_trade_pct": rpt,
                     "stop_fill": stop_fill, "risk": res["risk"], "start": start, "end": end,
                     "initial_capital": res["initial_capital"]}
    if venue == "dex":
        out["config"].update(venue="dex", data="candle", symbols=[display_name(x) for x in symbols])
    if regime:
        out["config"]["regime"] = True
    if base_frame != "1m":
        out["config"]["timeframe"] = base_frame
    out["final_equity"] = round(res["final_equity"], 2)
    if not close_at_end:
        out["open_positions"] = eng.open_positions()
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}  # không tất định -> tách riêng
    return out


# ══════════════════════════════════════════════════════════════════════════
# Backtest THEO TICK cho tài sản DEX (AMM): Nautilus không có AMM -> NotReady. Thân cũ: test/backend-no (tick_run của engine cũ).
# ══════════════════════════════════════════════════════════════════════════

def run_tick(items, symbols: List[str], start: Optional[int], end: Optional[int], rpt: float, risk: Dict[str, Any], stop_fill: str, base_frame: str,
             capital: float, latency_ms: Optional[int] = None, gas_usd: Optional[float] = None) -> Dict[str, Any]:
    """items [(id chiến lược, tham số)], symbols = ký hiệu DEX engine ("dex:AERO"), start/end ms (None = hết độ phủ tick; cắt theo độ phủ, xem dex.tick_window)
    -> kết quả cùng lược đồ run.run. latency_ms / gas_usd None = theo mạng của pool (tạo từ NETWORKS).
    Nautilus không có AMM -> NotReady (501) ngay từ đầu (thân hàm cũ: test/backend-no)."""
    from backend.jobs.runner import DEX_UNSUPPORTED, NotReady
    raise NotReady(DEX_UNSUPPORTED)


# ══════════════════════════════════════════════════════════════════════════
# Phía WORKER của phễu: backtest danh mục một alpha, WFA cố định tham số, Monte Carlo, tìm/xác nhận hệ số s, holdout.
#
# Mọi hàm `w_*` là hàm cấp module (pickle được qua ProcessPoolExecutor), nhận một dict `job` thuần dữ liệu và trả dict thuần dữ liệu.
# Máy chạy là PortfolioEngine DÙNG LẠI (cùng đường với build_strategy_book giai đoạn A / validate_book): không có logic mô phỏng riêng ở đây.
# Dữ liệu giá + kernel đọc qua mmap dùng chung (backend/jobs/evaluate.py) khi `shared_dir` có đặt; không thì tự dựng (cùng kết quả từng bit).
# ══════════════════════════════════════════════════════════════════════════


# ── Engine ──────────────────────────────────────────────────────────────────
def risk_dict(kill: bool) -> Dict[str, Any]:
    """Giới hạn danh mục của sổ (RISK); kill=False = đánh giá tham số (kill switch tắt, như build_strategy_book giai đoạn A/IS)."""
    from backend.models.params import RISK
    return {**RISK, "kill_switch_dd_pct": RISK["kill_switch_dd_pct"] if kill else 0}


def to_job(job: Dict[str, Any]) -> BacktestJob:
    """Job phễu (dict: strategy, params, window, stop_fill, kill, rpt, symbols, shared_dir, base_frame, regime_map?) -> đặc tả chung BacktestJob."""
    rmap = job.get("regime_map")
    return BacktestJob([(job["strategy"], job["params"])], (int(job["window"][0]), int(job["window"][1])), job["stop_fill"],
                       risk_dict(job["kill"]), job["rpt"], list(job["symbols"]), job.get("shared_dir"), job.get("base_frame", "1m"),
                       {job["strategy"]: rmap} if rmap else None)


# ══════════════════════════════════════════════════════════════════════════
# WFA danh mục (Portfolio WFA + Monte Carlo trên lợi suất ngày MTM)
# ══════════════════════════════════════════════════════════════════════════

def candidates_from_report(stage_a, report, n, include_rejected, only=None):
    """Top-n cấu hình (điểm dev1 cao nhất, bỏ điểm -inf) mỗi chiến lược; mặc định chỉ chiến lược ĐẠT."""
    out = []
    for cid, rows in stage_a.items():
        if only and cid not in only:
            continue
        accepted = (report.get("candidates", {}).get(cid) or {}).get("accepted")
        if not include_rejected and not (accepted is True or accepted == "True"):  # báo cáo cũ lưu chuỗi 'False' (default=str)
            continue
        ranked = sorted((r for r in rows if r["score"] is not None and r["score"] > float("-inf")), key=lambda r: -r["score"])
        if ranked:
            out.append({"id": cid, "configs": [r["params"] for r in ranked[:n]]})
    return out


def candidates_from_ids(ids, n, seed):
    from backend.strategies import BY_ID, configs
    by_id = BY_ID
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": configs(by_id[i], n, seed)} for i in ids]


def candidates_from_list(raw):
    """Cấu hình do người dùng chọn: [{"id", "configs": [{tham số}]}] -> đúng như vậy (kiểm id/khoá tham số theo `space` + `params_schema`)."""
    from backend.strategies import BY_ID
    by_id = BY_ID
    if not isinstance(raw, list) or not raw:
        raise SystemExit("strategies phải là danh sách không rỗng")
    out, seen = [], set()
    for s in raw:
        cid, cfgs = s.get("id"), s.get("configs")
        if cid not in by_id or cid in seen:
            raise SystemExit(f"Chiến lược lạ hoặc bị lặp: {cid!r}; có: {sorted(by_id)}")
        if not isinstance(cfgs, list) or not cfgs or not all(isinstance(c, dict) for c in cfgs):
            raise SystemExit(f"{cid}: configs phải là danh sách không rỗng các dict tham số")
        bad = sorted({k for c in cfgs for k in c} - set(by_id[cid]["space"]) - set(by_id[cid].get("params_schema") or {}))
        if bad:
            raise SystemExit(f"{cid}: khoá tham số không thuộc không gian tham số / lược đồ tham số: {bad}")
        seen.add(cid)
        out.append({"id": cid, "configs": cfgs})
    return out


from backend.jobs.workers import pool_map_safe
_pool_map = pool_map_safe


def run_wfa_job(job):
    from backend.jobs.workers import peak_rss_mb, rss_anon_mb
    from backend.carlo.carlo import measure_turnover, vertical_exposure
    from backend.models.params import iso_date
    eng, start = make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    result = portfolio_metrics(res, start)
    from backend.metrics.trades import trade_rows
    rows = trade_rows(res["positions"])
    result["shock"] = vertical_exposure(rows, job.rpt)   # MC: kịch bản trend thẳng đứng
    result["turnover"] = measure_turnover(rows, len(result["daily"]))   # MC: kịch bản cost_x2 dùng vòng quay ĐO TỪ LỆNH
    if job.regime:   # lãi/lỗ theo (chiến lược, regime lúc vào lệnh) -> học bảng regime (regime="learn")
        from backend.metrics.regime import engine_by_regime
        result["by_regime"] = engine_by_regime(eng, res["positions"])
    # Ngày UTC đầu của chuỗi lợi suất ngày (mẫu vốn đầu tiên >= start) -> dựng nhãn ngày cho đường vốn OOS
    first = next((c["time"] for c in res["equity_curve"] if c["time"] >= start), None)
    result["_daily_start"] = iso_date(first) if first is not None else None
    result["_peak_rss_mb"] = round(peak_rss_mb(), 1)
    result["_rss_anon_mb"] = round(rss_anon_mb(), 1)
    return result


def _pool_shared(jobs, workers, label, shared_dir, store=None, stage=None, progress=None):
    """Làm nóng kho dùng chung -> pool -> dọn kho (lỗi thì ngoại lệ bay lên, kho giữ nguyên để gỡ lỗi). jobs: [BacktestJob].
    store (ResultsStore, tuỳ chọn): mỗi kết quả ghi ngay khi xong; job đã có trong kho (cùng job_key) bỏ qua -> `--resume`.
    stage "wfa_is": bỏ chuỗi `daily` (chọn cấu hình IS không cần) để RAM/kho gọn. Kết quả luôn đúng thứ tự jobs."""
    if store is None and progress is None:
        exporter = SharedExporter(shared_dir, label)
        exporter.ensure(jobs)
        res = _pool_map(run_wfa_job, jobs, workers, label)
        exporter.cleanup()
        return res
    stage = stage or "wfa"
    results: List[Any] = [None] * len(jobs)
    keys_of: List[Optional[str]] = [None] * len(jobs)
    missing = []
    fp = data_fingerprint(jobs[0].symbols) if (store is not None and jobs) else None
    for i, job in enumerate(jobs):
        if store is not None:
            extra = {"rpt": job.rpt, "symbols": list(job.symbols)}
            if job.base_frame != "1m":   # khung chạy khác -> khoá khác (resume không trộn kết quả hai khung)
                extra["base_frame"] = job.base_frame
            if job.regime:
                extra["regime"] = job.regime
            keys_of[i] = make_job_key(stage, "-", [[c, p] for c, p in job.items], list(job.window), job.stop_fill, job.risk, fp,
                                      extra=extra)
            row = store.get(keys_of[i])
            if row is not None:
                results[i] = row["metrics"]
                if progress is not None:
                    progress.tick(resumed=True)
                continue
        missing.append(i)
    if missing:
        sub = [jobs[i] for i in missing]
        exporter = SharedExporter(shared_dir, label)
        exporter.ensure(sub)

        def _done(j, res):
            i = missing[j]
            m = normalize(res)
            if stage == "wfa_is":
                m.pop("daily", None)
                m.pop("stats", None)
            results[i] = m
            if store is not None:
                store.put(keys_of[i], stage, "-", [[c, p] for c, p in jobs[i].items], m, ord=i)
            if progress is not None:
                progress.tick(worker_peak_mb=m.get("_peak_rss_mb"))
        _pool_map(run_wfa_job, sub, workers, label, on_done=_done)
        exporter.cleanup()
    return results


def _strip(m):
    from backend.strategies import strip_metrics
    return strip_metrics(m, ("_daily_start", "by_regime", "shock", "turnover"))


def plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_dir, base_frame="1m"):
    """Danh sách (khoá, job) IS: khoá = (fold, candidate_id, chỉ số cấu hình). Cửa sổ IS = [train_start, train_end]."""
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        for cand in candidates:
            for ci, cfg_params in enumerate(cand["configs"]):
                keys.append((fi, cand["id"], ci))
                jobs.append(BacktestJob([(cand["id"], cfg_params)], (fold["train_start_ts"], fold["train_end_ts"]), "level", is_risk,
                                        rpt, symbols, shared_dir, base_frame))
    return keys, jobs


def plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_dir, base_frame="1m", regime_maps=None):
    """chosen[fold] = [(candidate_id, params)] (rỗng -> fold NO_TRADE, không chạy). Khoá = (fold, stop_fill).
    regime_maps[fold] (tuỳ chọn): bảng regime học trên train của fold đó."""
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if not chosen[fi]:
            continue
        rmap = regime_maps[fi] if regime_maps else None
        for sf in ("level", "extreme"):
            keys.append((fi, sf))
            jobs.append(BacktestJob(chosen[fi], (fold["test_start_ts"], fold["test_end_ts"]), sf, risk, rpt, symbols, shared_dir, base_frame,
                                    rmap))
    return keys, jobs


def plan_regime_jobs(chosen, folds, symbols, risk, rpt, shared_dir, base_frame="1m", learn_from=None):
    """regime="learn": mỗi fold chạy lại các cấu hình đã chọn trên cửa sổ HỌC (kill switch tắt như IS) ở chế độ quan sát regime
    -> lãi/lỗ theo (chiến lược, regime). Cửa sổ học = [learn_from, train_end] (mở rộng: thêm mẫu, vẫn kết thúc trước test);
    learn_from=None -> đúng cửa sổ train của fold. Khoá = fold."""
    from backend.metrics.regime import OBSERVE
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if chosen[fi]:
            keys.append(fi)
            lo = fold["train_start_ts"] if learn_from is None else min(int(learn_from), fold["train_start_ts"])
            jobs.append(BacktestJob(chosen[fi], (lo, fold["train_end_ts"]), "level", is_risk, rpt, symbols, shared_dir,
                                    base_frame, {cid: OBSERVE for cid, _ in chosen[fi]}))
    return keys, jobs


def run_portfolio_wfa(candidates, symbols, start_ts, end_ts, cfg, risk, risk_per_trade_pct, workers, shared_root,
                      store=None, progress=None, base_frame="1m", regime="off", regime_learn_from=None) -> Dict[str, Any]:
    """candidates = [{"id": candidate_id, "configs": [params...]}]; cfg: PortfolioWfaConfig hoặc dict.
    regime: "off" (mặc định, như trước) | "learn": mỗi fold học bảng regime ↔ chiến lược trên TRAIN (metrics/regime.learn_map) rồi áp lên test;
    regime_learn_from (ms, tuỳ chọn): học trên cửa sổ mở rộng [regime_learn_from, train_end] thay vì chỉ train của fold.
    risk: dict RiskConfig dùng cho OOS (kill switch BẬT); IS tự tắt kill switch. Trả dict kết quả (xem aggregate_folds).
    store/progress (tuỳ chọn, backend/optimize): ghi từng kết quả job vào kho + bỏ qua job đã có (--resume) + tiến độ."""
    from dataclasses import asdict
    from backend.models.params import iso_date
    from backend.wfa.wfa import PortfolioWfaConfig, aggregate_folds, evaluate_gate, generate_folds, is_score, select_best
    from backend.carlo.carlo import measure_turnover
    cfg = cfg if isinstance(cfg, PortfolioWfaConfig) else PortfolioWfaConfig.from_dict(cfg)
    symbols, rpt = list(symbols), float(risk_per_trade_pct)
    folds = generate_folds(int(start_ts), int(end_ts), cfg.train_days, cfg.test_days, cfg.step_days)
    if not folds:
        raise ValueError("Khoảng thời gian không đủ để tạo ít nhất 1 fold")
    os.makedirs(shared_root, exist_ok=True)
    t0 = time.time()

    # IS: MỌI fold × chiến lược × cấu hình trong MỘT pool
    is_keys, is_jobs = plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_root, base_frame)
    if progress is not None:
        progress.start_stage("WFA-IS", len(is_jobs))
    is_res = _pool_shared(is_jobs, workers, f"[WFA-IS] {len(folds)} fold × {len(is_jobs) // len(folds)} job", shared_root,
                          store, "wfa_is", progress)
    is_by = {k: m for k, m in zip(is_keys, is_res)}
    print(f"[WFA-IS] {len(is_jobs)} job IS xong ({time.time() - t0:.0f}s)", flush=True)

    # Chọn cấu hình theo IS (chỉ dùng kết quả IS)
    chosen: List[List[Tuple[str, Dict[str, Any]]]] = []
    picks: List[Dict[str, Optional[int]]] = []
    for fi in range(len(folds)):
        pick, items = {}, []
        for cand in candidates:
            rows = [is_by[(fi, cand["id"], ci)] for ci in range(len(cand["configs"]))]
            best = select_best(rows, cfg.min_is_trades)
            pick[cand["id"]] = best
            if best is not None:
                items.append((cand["id"], cand["configs"][best]))
        chosen.append(items)
        picks.append(pick)

    # regime="learn": bảng regime của mỗi fold chỉ học từ train
    regime_maps, train_regime = None, {}
    if regime == "learn":
        from backend.metrics.regime import learn_map
        rg_keys, rg_jobs = plan_regime_jobs(chosen, folds, symbols, risk, rpt, shared_root, base_frame, regime_learn_from)
        if progress is not None:
            progress.start_stage("WFA-REGIME", len(rg_jobs))
        rg_res = _pool_shared(rg_jobs, workers, f"[WFA-REGIME] {len(rg_jobs)} job", shared_root, store, "wfa_regime", progress) if rg_jobs else []
        train_regime = {fi: m.get("by_regime") or {} for fi, m in zip(rg_keys, rg_res)}
        regime_maps = [{cid: rc for cid, rc in learn_map(train_regime.get(fi, {}), [c for c, _ in chosen[fi]]).items() if rc}
                       for fi in range(len(folds))]
        print(f"[WFA-REGIME] {len(rg_jobs)} job học regime xong ({time.time() - t0:.0f}s)", flush=True)
    elif regime != "off":
        raise ValueError(f"regime phải là off|learn (nhận {regime!r})")

    # OOS: MỌI fold × {level, extreme} trong MỘT pool
    oos_keys, oos_jobs = plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_root, base_frame, regime_maps)
    if progress is not None:
        progress.start_stage("WFA-OOS", len(oos_jobs))
    oos_res = _pool_shared(oos_jobs, workers, f"[WFA-OOS] {len(oos_jobs)} job", shared_root, store, "wfa_oos", progress) if oos_jobs else []
    oos_by = {k: m for k, m in zip(oos_keys, oos_res)}
    print(f"[WFA-OOS] {len(oos_jobs)} job OOS xong ({time.time() - t0:.0f}s)", flush=True)

    fold_records = []
    for fi, fold in enumerate(folds):
        cids = [c["id"] for c in candidates]
        is_sel = {cid: _strip(is_by[(fi, cid, picks[fi][cid])]) | {"score": round(is_score(is_by[(fi, cid, picks[fi][cid])],
                                                                                          cfg.min_is_trades), 4)}
                  for cid in cids if picks[fi][cid] is not None}
        rec = {
            "fold": fi + 1,
            "train": [iso_date(fold["train_start_ts"]), iso_date(fold["train_end_ts"])],
            "test": [iso_date(fold["test_start_ts"]), iso_date(fold["test_end_ts"])],
            "train_ts": [fold["train_start_ts"], fold["train_end_ts"]], "test_ts": [fold["test_start_ts"], fold["test_end_ts"]],
            "status": "TRADED" if chosen[fi] else "NO_TRADE",
            "chosen_idx": picks[fi],
            "chosen": {cid: (candidates[i]["configs"][picks[fi][cid]] if picks[fi][cid] is not None else None)
                       for i, cid in enumerate(cids)},
            "is": is_sel,
            "is_ret_pct": round(sum(m["ret_pct"] for m in is_sel.values()) / len(is_sel), 2) if is_sel else 0.0,
            "is_candidates": {cid: [{"ret_pct": m["ret_pct"], "mdd_pct": m["mdd_pct"], "trades": m["trades"],
                                     "score": is_score(m, cfg.min_is_trades)}
                                    for m in (is_by[(fi, cid, ci)] for ci in range(len(candidates[i]["configs"])))]
                              for i, cid in enumerate(cids)},
        }
        for sf in ("level", "extreme"):
            m = oos_by.get((fi, sf))
            rec[f"oos_{sf}"] = _strip(m) if m else None
            rec[f"oos_daily_{sf}"] = list(m["daily"]) if m else [0.0] * cfg.test_days   # NO_TRADE: vốn đứng yên
            first = (m or {}).get("_daily_start") or iso_date(fold["test_start_ts"])
            rec[f"oos_daily_dates_{sf}"] = [f"{d:%Y-%m-%d}" for d in pd.date_range(first, periods=len(rec[f"oos_daily_{sf}"]), freq="D")]
        rec["shock"] = (oos_by.get((fi, "extreme")) or {}).get("shock")
        m_ext = oos_by.get((fi, "extreme"))
        if m_ext is None:                                           # fold NO_TRADE: không có lệnh nào -> vòng quay 0 (đo được)
            rec["turnover"] = measure_turnover([], len(rec["oos_daily_extreme"]))
        else:                                                       # kết quả job cũ trong kho (resume) không lưu vòng quay -> không đo được
            rec["turnover"] = m_ext.get("turnover") or {"turnover_daily": None, "note": "kết quả fold cũ không lưu vòng quay", "sum": 0.0,
                                                        "days": len(rec["oos_daily_extreme"]), "trades": 0, "measurable": 0}
        if regime_maps is not None:
            rec["regime_map"] = regime_maps[fi]
            rec["train_by_regime"] = train_regime.get(fi, {})
        rec["trades"] = {sf: (rec[f"oos_{sf}"]["trades"] if rec[f"oos_{sf}"] else 0) for sf in ("level", "extreme")}
        rec["halted_at"] = {sf: (rec[f"oos_{sf}"]["halted_at"] if rec[f"oos_{sf}"] else None) for sf in ("level", "extreme")}
        fold_records.append(rec)

    summary = aggregate_folds(fold_records, cfg)
    gate = evaluate_gate(summary)
    all_res = [m for m in list(is_res) + list(oos_res) if m]
    return {
        "config": asdict(cfg), "risk": risk, "risk_per_trade_pct": rpt, "symbols": symbols,
        **({"regime": regime} if regime != "off" else {}),
        **({"regime_learn_from": iso_date(regime_learn_from)} if regime != "off" and regime_learn_from else {}),
        "window": [iso_date(start_ts), iso_date(end_ts)], "candidates": [{"id": c["id"], "configs": c["configs"]} for c in candidates],
        "folds": fold_records, "summary": summary, "gate": gate,
        "aggregate": summary, "mc": summary["mc"],   # tên theo docs/ui_contract.md §4 (cùng đối tượng với summary / summary.mc)
        "mem": {"peak_rss_mb": max([m["_peak_rss_mb"] for m in all_res], default=0.0),
                "rss_anon_mb": max([m["_rss_anon_mb"] for m in all_res], default=0.0)},
    }


def print_summary(res):
    s, g = res["summary"], res["gate"]
    print(f"\ncửa sổ {res['window'][0]} → {res['window'][1]} | train {res['config']['train_days']}d test {res['config']['test_days']}d "
          f"| rủi ro/lệnh {res['risk_per_trade_pct']}% | {s['n_folds']} fold")
    print(f"{'#':>2} {'train':23s} {'test':23s} {'IS%':>7} {'OOSlv%':>7} {'OOSex%':>7} {'MDDex':>6} {'lệnh':>5} {'kill':>4}  chọn")
    for f in res["folds"]:
        ex, lv = f["oos_extreme"], f["oos_level"]
        pick = ",".join(f"{cid}#{i}" for cid, i in f["chosen_idx"].items() if i is not None) or "-"
        print(f"{f['fold']:>2} {f['train'][0]}→{f['train'][1]:10s} {f['test'][0]}→{f['test'][1]:10s} {f['is_ret_pct']:7.2f} "
              f"{(lv['ret_pct'] if lv else 0.0):7.2f} {(ex['ret_pct'] if ex else 0.0):7.2f} {(ex['mdd_pct'] if ex else 0.0):6.2f} "
              f"{f['trades']['extreme']:5d} {'có' if f['halted_at']['extreme'] else '-':>4}  {pick}")
    print("ổn định tham số: " + "; ".join(f"{cid} {v['share'] * 100:.0f}% ({v['distinct']} cấu hình/{v['folds_chosen']} fold)"
                                          for cid, v in s["param_stability"].items()))
    c, w = s["compounded_oos_ret_pct"], s["worst_fold_mdd_pct"]
    print(f"OOS lãi kép: level {c['level']}% | extreme {c['extreme']}% | MDD fold tệ nhất: level {w['level']}% | extreme {w['extreme']}% "
          f"| {s['oos_days']} ngày, lệnh {s['oos_trades']['extreme']}")
    mc = s["mc"]
    if mc:
        print(f"MC {mc['simulations']}×{mc['horizon_days']}d (block {mc['block_days']}, ngày MTM extreme): lãi trung vị {mc['median_ret_pct']}%, "
              f"p05 {mc['p05_ret_pct']}%, MDD p50 {mc['mdd_p50_pct']}% / p95 {mc['mdd_p95_pct']}%, P(MDD>=30%) {mc['p_mdd_ge_ruin_pct']}%")
    else:
        print("MC: không đủ ngày OOS")
    print("GATE: " + ("ĐẠT" if g["passed"] else "KHÔNG ĐẠT"))
    for c in g["checks"].values():
        print(f"  [{'ok' if c['passed'] else 'XX'}] {c['label']}: {c['actual']} (cần {c['required']})")
    m = res["mem"]
    print(f"đỉnh RAM/worker {m['peak_rss_mb']:.0f} MB (riêng {m['rss_anon_mb']:.0f} MB + mmap dùng chung)", flush=True)


# ══════════════════════════════════════════════════════════════════════════
# Làm nóng / dọn kho dữ liệu dùng chung (backend/jobs/evaluate.py) cho MỌI lối chạy nhiều alpha: dựng sổ (strategies.py), WFA
# (wfa/wfa) và phễu ((phễu đã gỡ)). Một chỗ duy nhất — trước đây mỗi lối có bản riêng.
#
# Kho không bắt buộc đầy đủ: worker thiếu nền / cột / chỉ số nào thì tự tính đúng phần đó và ghi vào kho cho worker khác (song song, không
# nghẽn ở tiến trình cha). Làm nóng ở tiến trình cha chỉ để các worker đầu tiên không cùng tính một thứ.
# ══════════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────────────
# Kho mmap dùng chung — bộ đệm TỐC ĐỘ của engine (đọc/ghi
# mảng đã tính), không phải I/O dữ liệu gốc -> ở đây cạnh SharedExporter. Engine dùng qua nguồn dữ liệu (EngineData.shared_*, cuối file này).
#
# Dữ liệu giá + chỉ báo dùng CHUNG giữa các tiến trình qua mmap (chỉ đọc) — kho tính sẵn kiểu "ma trận chỉ báo" (học từ sova/prepare.py).
#
# Chỉ báo tính từ gốc cố định (đầu lịch sử, BacktestEngine.frame_values) nên giá trị của một cột trên nến khung chỉ phụ thuộc
# (tài sản, khung, cột, file dữ liệu, mốc cuối) — KHÔNG phụ thuộc cửa sổ hay các cột khác. Vì vậy mỗi cột của mỗi khung tính đúng MỘT lần
# cho cả lần chạy (mọi nhóm alpha dùng lại), ở dạng nến khung (nhỏ: 15m ~100k nến), rồi mỗi worker căn về phút bằng chỉ số dùng chung.
#
# Bố cục <out_dir>/:
#   base/<khoá nền>/{t,o,h,l,c,f_t,f_r}.npy + meta.json   nến khung chạy (thật) + funding của cửa sổ (theo engine.load_data)
#   ft/<khoá khung>.npy                                     open_time các nến của khung (khung 1m: các phút có giao dịch)
#   fv/<khoá cột>.npy                                       giá trị cột trên các nến đó
#   ix/<khoá căn>.npy                                       chỉ số nến khung dùng ở từng phút của nền (-1 = chưa có)
# Khoá:
#   nền  = sha1(tài sản, nguồn, cửa sổ, khung chạy, điểm bắt đầu nạp, perp, vân tay catalog)
#   khung = sha1(tài sản, nguồn, khung, vân tay file khung, mốc cuối)       cột = sha1(khung, cột)       căn = sha1(nền, khung)
# Ghi nguyên tử (file / thư mục tạm + rename): người đọc không bao giờ thấy dữ liệu dở; hai tiến trình ghi cùng khoá thì một bản thắng.
#
# Dùng:
#   export()  — tiến trình cha làm nóng trước khi chạy pool (sổ, WFA, phễu).
#   PortfolioEngine._load_shared — worker: đủ thì đọc; thiếu thì fill() đúng phần thiếu (nền / cột / chỉ số căn) rồi đọc lại.
# Kết quả bằng từng bit với PortfolioEngine._build_symbol_data (test/test_shared_data.py).
# ────────────────────────────────────────────────────────────────────────────

FORMAT_VERSION = 6   # 6: nền có thể kèm đường giá 1m trong nến chạy (MINUTE_ARRAYS) cho khớp "extreme" ở khung chạy > 1m
BASE_ARRAYS = ("t", "o", "h", "l", "c", "f_t", "f_r")
MINUTE_ARRAYS = ("m_a", "m_b", "m_l", "m_h")
STATS = {"fills": 0, "bases_written": 0, "cols_written": 0, "frames_written": 0, "index_written": 0}   # theo tiến trình (giám sát / test)


def _sha1(payload: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _catalog_fp(symbol: str) -> Optional[List[str]]:
    """Dấu vân tay nến của tài sản = digest catalog (mọi khung đều suy ra từ nến 1m của catalog). None nếu catalog chưa có tài sản."""
    return None if read_manifest(symbol) is None else [catalog_digest([symbol])]


def plan(eng: "BacktestEngine") -> Optional[Dict[str, Any]]:
    """Khoá nền + khoá từng khung / cột / chỉ số căn cho đúng bộ dữ liệu `eng` sẽ dựng. None nếu catalog không có nến của tài sản."""
    from backend.models.params import FRAME_MS
    from backend.signal.compute import needs_minute_path, slot_fresh_frames
    from backend.signal.nodes import lag_key
    root = default_catalog_path()
    base_fr = eng.base_frame
    fp1 = _catalog_fp(eng.symbol)
    if fp1 is None:
        return None
    refs = eng._refs_by_frame()
    if any(col.startswith("py_") for rs in refs.values() for col, _ in rs):
        return None   # cột chương trình Python (P7) tính trong tiến trình, KHÔNG ghi vào kho dùng chung
    perp = any(tr.market == "perp" for tr in eng.slots)
    base = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "start": int(eng.start_ts), "end": int(eng.end_ts),
                  "base_frame": base_fr, "load_base": int(eng.start_ts - eng._warmup_ms(base_fr, refs.get(base_fr, set()))),
                  "perp": perp, "fp_base": list(fp1), "minute": needs_minute_path(eng),
                  "fp_1m": list(_catalog_fp(eng.symbol) or []) if needs_minute_path(eng) else None})
    frames: Dict[str, Dict[str, str]] = {}
    cols: Dict[str, Dict[str, str]] = {}
    for frame in ([base_fr] if base_fr in refs else []) + [f for f in refs if f != base_fr]:   # cùng thứ tự với _build_matrix
        if frame not in FRAME_MS:
            continue
        fp = _catalog_fp(eng.symbol)
        tkey = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "frame": frame, "fp": list(fp) if fp else None,
                      "end": int(eng.end_ts)})
        frames[frame] = {"t": tkey, "ix": _sha1({"base": base, "frame": tkey, "base_frame": base_fr})}
        for col, lag in sorted(refs[frame]):
            cid = f"{frame}|{lag_key(col, lag)}"
            cols[cid] = {"frame": frame, "v": _sha1({"frame": tkey, "cid": cid})}
    return {"base": base, "frames": frames, "cols": cols, "minute": needs_minute_path(eng),
            "fresh": sorted(slot_fresh_frames(eng.slots, base_fr))}      # khung cần cột sự kiện "khung|__fresh" (suy ra từ chỉ số căn khi nạp)


def _base_dir(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "base", key)


def _file(out_dir: str, kind: str, key: str) -> str:
    return os.path.join(out_dir, kind, f"{key}.npy")


def paths(p: Dict[str, Any]) -> Set[str]:
    """Đường dẫn tương đối (trong out_dir) của mọi phần thuộc kế hoạch `p` — để dọn theo giai đoạn (remove)."""
    out = {os.path.join("base", p["base"])}
    for f in p["frames"].values():
        out |= {os.path.join("ft", f"{f['t']}.npy"), os.path.join("ix", f"{f['ix']}.npy")}
    return out | {os.path.join("fv", f"{c['v']}.npy") for c in p["cols"].values()}


def _load_array(path: str) -> np.ndarray:
    try:
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
    except ValueError:  # mảng rỗng không mmap được
        return np.load(path, allow_pickle=False)
    return np.asarray(arr)  # ndarray thường (index từng phần tử nhanh hơn np.memmap), vẫn chia sẻ mmap, chỉ đọc


def load_base(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, np.ndarray]]:
    """Mảng nền {t,o,h,l,c,f_t,f_r} (mmap chỉ đọc); None nếu chưa có / hỏng."""
    bdir = _base_dir(out_dir, p["base"])
    try:
        with open(os.path.join(bdir, "meta.json"), encoding="utf-8") as fh:
            if json.load(fh).get("version") != FORMAT_VERSION:
                return None
        names = BASE_ARRAYS + (MINUTE_ARRAYS if p.get("minute") else ())
        return {name: _load_array(os.path.join(bdir, f"{name}.npy")) for name in names}
    except (OSError, ValueError):
        return None


def load(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dict giống PortfolioEngine._build_symbol_data: nền là view mmap chỉ đọc, cột = giá trị khung (mmap) căn theo chỉ số dùng chung.
    None nếu thiếu / hỏng bất kỳ phần nào."""
    from backend.signal.compute import FRESH, SignalEngine, frame_fresh
    base = load_base(out_dir, p)
    if base is None:
        return None
    try:
        idx = {fr: _load_array(_file(out_dir, "ix", f["ix"])) for fr, f in p["frames"].items()}
        cols = {}
        for fr in p["frames"]:            # cùng thứ tự với _build_matrix: cột của khung rồi cột sự kiện của khung đó
            for cid, c in p["cols"].items():
                if c["frame"] == fr:
                    cols[cid] = SignalEngine.gather(_load_array(_file(out_dir, "fv", c["v"])), idx[fr])
            if fr in p.get("fresh", ()):     # nền chỉ gồm nến thực -> chuỗi chỉ số căn không có nến điền
                cols[f"{fr}|{FRESH}"] = frame_fresh(idx[fr])
    except (OSError, ValueError):
        return None
    data: Dict[str, Any] = {k: base[k] for k in ("t", "o", "h", "l", "c")}
    data["cols"] = cols
    data["f_t"], data["f_r"] = base["f_t"], base["f_r"]
    if p.get("minute"):
        data["minute"] = {k: base[k] for k in MINUTE_ARRAYS}
    return data


def _save(path: str, arr: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "wb") as fh:
        np.save(fh, np.ascontiguousarray(arr), allow_pickle=False)
    os.replace(tmp, path)


def _write_base(out_dir: str, key: str, symbol: str, data: Dict[str, Any]) -> None:
    final = _base_dir(out_dir, key)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    tmp = f"{final}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for name in BASE_ARRAYS:
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, data[name], allow_pickle=False)
    for name, arr in (data.get("minute") or {}).items():
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, arr, allow_pickle=False)
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": FORMAT_VERSION, "symbol": symbol}, fh)
    try:
        os.rename(tmp, final)
    except OSError:                 # tiến trình khác đã ghi xong cùng khoá
        shutil.rmtree(tmp, ignore_errors=True)
        if not os.path.isdir(final):
            raise


def fill(out_dir: str, pe: "PortfolioEngine", eng: "BacktestEngine", p: Dict[str, Any]) -> Dict[str, int]:
    """Tính và ghi phần còn thiếu của kế hoạch `p`: nền, giá trị cột theo khung, chỉ số căn — qua đúng hàm của engine."""
    from backend.signal.nodes import lag_key
    wrote = {"base": 0, "cols": 0, "frames": 0, "index": 0}
    if load_base(out_dir, p) is None:
        _write_base(out_dir, p["base"], eng.symbol, pe._build_symbol_data(eng, only=set()))
        wrote["base"] = 1
    base_t = load_base(out_dir, p)["t"]
    refs = eng._refs_by_frame()
    loaded = False
    for frame, f in p["frames"].items():
        miss_cols = {cid for cid, c in p["cols"].items() if c["frame"] == frame and not os.path.isfile(_file(out_dir, "fv", c["v"]))}
        t_path, ix_path = _file(out_dir, "ft", f["t"]), _file(out_dir, "ix", f["ix"])
        if not miss_cols and os.path.isfile(t_path) and os.path.isfile(ix_path):
            continue
        if frame != eng.base_frame and not loaded:
            eng.load_frames(refs)               # khung lớn từ đầu lịch sử (gốc cố định)
            loaded = True
        sub = {(col, lag) for col, lag in refs[frame] if f"{frame}|{lag_key(col, lag)}" in miss_cols}
        if sub or not os.path.isfile(t_path):
            t_frame, vals = eng.frame_values(frame, sub or {sorted(refs[frame])[0]})
            for cid in miss_cols:
                _save(_file(out_dir, "fv", p["cols"][cid]["v"]), vals[cid])
            wrote["cols"] += len(miss_cols)
            if not os.path.isfile(t_path):
                _save(t_path, t_frame)
                wrote["frames"] += 1
        if not os.path.isfile(ix_path):
            _save(ix_path, eng.align_index(frame, _load_array(t_path), base_t, eng.base_frame))
            wrote["index"] += 1
    STATS["fills"] += 1
    for k, n in wrote.items():
        STATS[{"base": "bases_written", "cols": "cols_written", "frames": "frames_written", "index": "index_written"}[k]] += n
    return wrote


def export(pe: "PortfolioEngine", out_dir: str) -> Dict[str, Any]:
    """Làm nóng: điền nền + cột + chỉ số cho mọi tài sản của `pe`. Trả {"paths": tập đường dẫn tương đối, "written": [tài sản có ghi mới]}."""
    os.makedirs(out_dir, exist_ok=True)
    out: Dict[str, Any] = {"paths": set(), "written": []}
    for sym in pe.symbols:
        eng, _ = pe._make_slots(sym, pe.ledger)
        p = plan(eng)
        if p is None:
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (catalog chưa có nến)")
        if any(fill(out_dir, pe, eng, p).values()):
            out["written"].append(sym)
        out["paths"] |= paths(p)
    return out


def size_mb(out_dir: str, rel_paths: Optional[Iterable[str]] = None) -> float:
    """Dung lượng (MB) của các phần chỉ định, hoặc cả out_dir."""
    targets = [os.path.join(out_dir, r) for r in rel_paths] if rel_paths is not None else [out_dir]
    total = 0
    for t in targets:
        if os.path.isfile(t):
            total += os.path.getsize(t)
            continue
        for base, _, files in os.walk(t):
            total += sum(os.path.getsize(os.path.join(base, f)) for f in files)
    return total / 1048576


STORE_DIRS = ("base", "ft", "fv", "ix")


def release_memory() -> None:
    """Xoá bộ đệm nến / dữ liệu trong tiến trình và trả heap về OS (trước khi fork pool / sau khi xuất)."""
    import ctypes
    import gc
    from backend.signal.compute import data_cache_clear
    from backend.data.data import clear_caches
    clear_caches()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def export_job(job: BacktestJob) -> List[str]:
    """Điền kho cho mọi tài sản của job (job.shared_dir). Chạy được trong worker của pool."""
    eng, _ = make_engine(job)
    info = export(eng, job.shared_dir)
    release_memory()
    return sorted(info["paths"])


class SharedExporter:
    """Làm nóng kho trước khi chạy pool của một giai đoạn và dọn sau giai đoạn.
    ensure(jobs) / exporter(job): xuất một lần cho mỗi (chiến lược, cửa sổ, khung chạy); song song tối đa `workers` tiến trình.
    to_job: đổi job riêng của lối gọi (vd. dict của phễu) sang BacktestJob."""

    def __init__(self, shared_dir: Optional[str], label: str = "", workers: int = 1,
                 to_job: Optional[Callable[[Any], BacktestJob]] = None):
        self.shared_dir, self.label, self.workers, self.to_job = shared_dir, label, max(1, int(workers)), to_job
        self.seen: Set[Tuple] = set()
        self.t0 = time.time()

    def ensure(self, jobs: Iterable[Any]) -> None:
        if not self.shared_dir:
            return
        todo = []
        for j in jobs:
            job = self.to_job(j) if self.to_job else j
            memo = (tuple(cid for cid, _ in job.items), tuple(job.window), job.base_frame)
            if memo in self.seen:
                continue
            self.seen.add(memo)
            todo.append(job._replace(shared_dir=self.shared_dir))
        if not todo:
            return
        os.makedirs(self.shared_dir, exist_ok=True)
        if self.workers <= 1 or len(todo) == 1:
            for job in todo:
                export_job(job)
        else:
            from backend.jobs.workers import pool_map_safe
            pool_map_safe(export_job, todo, min(self.workers, len(todo)), f"[shared] {self.label}")

    def __call__(self, job: Any) -> None:
        self.ensure([job])

    def cleanup(self) -> None:
        """Xoá toàn bộ kho của giai đoạn (gồm phần worker tự điền) — các giai đoạn chạy tuần tự nên an toàn."""
        if not self.shared_dir:
            return
        mb = size_mb(self.shared_dir) if os.path.isdir(self.shared_dir) else 0.0
        for sub in STORE_DIRS:
            shutil.rmtree(os.path.join(self.shared_dir, sub), ignore_errors=True)
        if self.label:
            print(f"[shared] {self.label}: dọn {mb:.0f} MB ({time.time() - self.t0:.0f}s)", flush=True)
        self.seen.clear()


# ════ Kho kết quả append-only (ResultsStore) + khoá job: dùng cho WFA danh mục (tiếp tục lần chạy bị ngắt) ════

# ══════════════════════════════════════════════════════════════════════════
# Kho kết quả append-only (SQLite, WAL) cho mỗi lần chạy tối ưu quy mô lớn: <run_dir>/results.sqlite.
#
# Vì sao: tối ưu tới ~1.000.000 cấu hình không thể giữ mọi kết quả trong RAM của tiến trình cha (và không thể chạy lại từ đầu khi
# bị kill). Mỗi kết quả của một job được ghi NGAY vào kho (idempotent theo job_key); tiến trình cha chỉ giữ top-K trong RAM; chạy lại
# với --resume bỏ qua các job_key đã có -> kết quả cuối y hệt lần chạy không gián đoạn.
#
# Bảng:
#   results(job_key TEXT PRIMARY KEY, stage, candidate, ord INTEGER, params_json, metrics_json, score REAL, created REAL)
#       ord = chỉ số cấu hình theo thứ tự sinh (để xếp hạng hoà điểm giống `sorted` ổn định); score = điểm xếp hạng (NULL = không đạt / -inf)
#   meta(key TEXT PRIMARY KEY, value TEXT)
# job_key = sha1(stage, candidate, params chuẩn hoá, cửa sổ, stop_fill, risk, sha256 dữ liệu, phiên bản mã) — đổi một trong các thành phần
# này thì kết quả cũ KHÔNG bao giờ được dùng lại.
#
# Ghi theo lô (commit mỗi COMMIT_EVERY lần put hoặc COMMIT_SECONDS giây); flush()/close() ghi nốt — CLI gọi trong finally + khi nhận SIGTERM.
# Móc kiểm thử: env NORA_TEST_FAIL_AFTER_PUTS=N -> sau lần put thứ N (đã commit) ném RuntimeError để mô phỏng sập giữa chừng (chỉ dùng trong test).
#
# Chạy một giai đoạn kiểu streaming (stream_stage):
# Chạy một giai đoạn tối ưu theo kiểu STREAMING: job sinh lười -> pool (bounded) -> ghi ngay vào ResultsStore -> chỉ giữ top-K trong RAM.
#
# stream_stage() là khung dùng chung cho build_strategy_book (giai đoạn A) và sàng lọc của (phễu đã gỡ)/stages:
#   - bỏ qua job đã có trong kho (job_key) -> `--resume` tiếp tục đúng chỗ dừng, kết quả cuối y hệt lần chạy không gián đoạn;
#   - kết quả mỗi job được chuẩn hoá qua JSON (cùng cấu trúc dù lấy từ worker hay từ kho) trước khi đưa cho `handle`;
#   - `handle(ord, params, metrics, from_store) -> (metrics_để_lưu, điểm)` quyết định lưu gì (vd. bỏ chuỗi `daily` của hàng không thuộc top-K).
# ══════════════════════════════════════════════════════════════════════════

DB_NAME = "results.sqlite"
COMMIT_EVERY = 200
COMMIT_SECONDS = 3.0
SCHEMA_VERSION = 1

_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS results(
    job_key TEXT PRIMARY KEY, stage TEXT NOT NULL, candidate TEXT NOT NULL, ord INTEGER,
    params_json TEXT NOT NULL, metrics_json TEXT NOT NULL, score REAL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS results_rank ON results(stage, candidate, score DESC, ord);
CREATE INDEX IF NOT EXISTS results_ord ON results(stage, candidate, ord);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

_CODE_FILES = (   # mọi file ảnh hưởng kết quả backtest: đổi một file -> khoá job đổi -> --resume không dùng lại kết quả cũ
    "backend/signal/compute.py", "backend/alpha/plan.py", "backend/models/models.py", "backend/models/params.py", "backend/models/position_size.py",   # tín hiệu + kế hoạch vị thế
    "backend/nautilus/engine.py", "backend/jobs/evaluate.py",   # P15: engine khớp lệnh = Nautilus (adapter) + vòng chạy
    "backend/metrics/metrics.py", "backend/metrics/trades.py",   # P9.5: returns+portfolio gộp, trades chuyển
    "backend/data/data.py", "backend/signal/nodes.py", "backend/alpha/contract.py", "backend/alpha/compile.py", "backend/signal/indicator.py",   # P9.4 part 2: evaluator/kernels đã gộp
    "backend/strategies.py", "backend/wfa/wfa.py",   # P9.5 (+ P9.9: sổ chiến lược book.py/library.py gộp vào build.py/signal.py)
)
_CODE_VERSION: Optional[str] = None


def canonical(obj: Any) -> str:
    """JSON chuẩn hoá (khoá sắp xếp, không khoảng trắng) — dùng cho job_key."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=json_default, allow_nan=True)


def code_version() -> str:
    """Chuỗi phiên bản mã ảnh hưởng kết quả: sha1 nội dung các file engine/chiến lược (hoặc env NORA_CODE_VERSION). Tính một lần."""
    global _CODE_VERSION
    env = os.environ.get("NORA_CODE_VERSION")
    if env:
        return env
    if _CODE_VERSION is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        from backend.nautilus.version import NAUTILUS_VERSION
        h = hashlib.sha1(f"v{SCHEMA_VERSION}|nautilus {NAUTILUS_VERSION}".encode())   # nâng Nautilus -> khoá job đổi
        for rel in _CODE_FILES:
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    h.update(rel.encode() + b"\0" + fh.read())
            except OSError:
                h.update(rel.encode() + b"\0missing")
        _CODE_VERSION = h.hexdigest()[:16]
    return _CODE_VERSION


def data_fingerprint(symbols: Iterable[str]) -> List[Any]:
    """Dấu vân tay catalog nến 1m của từng tài sản (data.catalog_digest) — thành phần của job_key."""
    from backend.data.data import catalog_digest
    return [[s, catalog_digest([s])] for s in symbols]


def make_job_key(stage: str, candidate: str, params: Any, window: Any = None, stop_fill: Any = None, risk: Any = None,
                 data: Any = None, code: Optional[str] = None, extra: Any = None) -> str:
    payload = canonical([stage, candidate, params, window, stop_fill, risk, data, code or code_version(), extra])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _results_dumps(obj: Any) -> str:
    return json.dumps(obj, default=json_default, allow_nan=True)


class ResultsStore:
    """Kho kết quả của MỘT lần chạy (một file SQLite trong run_dir). An toàn đa luồng; nhiều tiến trình cùng ghi được (WAL + busy_timeout)."""

    def __init__(self, run_dir: str, name: str = DB_NAME, read_only: bool = False):
        self.path = run_dir if run_dir.endswith(".sqlite") else os.path.join(run_dir, name)
        if not read_only:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.read_only = read_only
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, timeout=60.0, check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA busy_timeout=60000")
        if read_only:
            self._con.execute("PRAGMA query_only=1")
        else:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_RESULTS_SCHEMA)
        self._pending = 0
        self._in_tx = False
        self._last_commit = time.time()
        self._puts = 0
        self._fail_after = int(os.environ.get("NORA_TEST_FAIL_AFTER_PUTS") or 0)

    # ── ghi ────────────────────────────────────────────────────────────────
    def put(self, job_key: str, stage: str, candidate: str, params: Any, metrics: Any, ord: Optional[int] = None,
            score: Optional[float] = None) -> bool:
        """Ghi một kết quả; idempotent theo job_key (đã có -> không đổi, trả False)."""
        sc = None if score is None or (isinstance(score, float) and not math.isfinite(score)) else float(score)
        with self._lock:
            if not self._in_tx:
                self._con.execute("BEGIN")
                self._in_tx = True
            cur = self._con.execute(
                "INSERT OR IGNORE INTO results(job_key, stage, candidate, ord, params_json, metrics_json, score, created) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (job_key, stage, candidate, ord, _results_dumps(params), _results_dumps(metrics), sc, time.time()))
            inserted = cur.rowcount == 1
            self._pending += 1
            if self._pending >= COMMIT_EVERY or time.time() - self._last_commit >= COMMIT_SECONDS:
                self._commit()
            if inserted:
                self._puts += 1
                if self._fail_after and self._puts >= self._fail_after:
                    self._commit()
                    raise RuntimeError(f"[test] mô phỏng sập sau {self._puts} job (NORA_TEST_FAIL_AFTER_PUTS)")
            return inserted

    def _commit(self) -> None:
        if self._in_tx:
            self._con.execute("COMMIT")
            self._in_tx = False
        self._pending = 0
        self._last_commit = time.time()

    def flush(self) -> None:
        with self._lock:
            if not self.read_only:
                self._commit()

    def close(self) -> None:
        with self._lock:
            try:
                self.flush()
            finally:
                self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:   # autocommit; nếu đang trong giao dịch put thì commit cùng lô
            self._con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, _results_dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # ── đọc ────────────────────────────────────────────────────────────────
    @staticmethod
    def _row(r) -> Dict[str, Any]:
        return {"job_key": r[0], "stage": r[1], "candidate": r[2], "ord": r[3], "params": json.loads(r[4]),
                "metrics": json.loads(r[5]), "score": r[6]}

    _COLS = "job_key, stage, candidate, ord, params_json, metrics_json, score"

    def has(self, job_key: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM results WHERE job_key=?", (job_key,)).fetchone() is not None

    def get(self, job_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._con.execute(f"SELECT {self._COLS} FROM results WHERE job_key=?", (job_key,)).fetchone()
        return self._row(r) if r else None

    def count(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> int:
        q, args = "SELECT COUNT(*) FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        with self._lock:
            return int(self._con.execute(q, args).fetchone()[0])

    def done_keys(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> Iterator[str]:
        """Duyệt job_key đã xong (iterator — không nạp cả tập vào RAM)."""
        q, args = "SELECT job_key FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        con = self._con
        with self._lock:
            keys = con.execute(q, args)
            for (k,) in keys:
                yield k

    def iter_rows(self, stage: str, candidate: str) -> Iterator[Dict[str, Any]]:
        """Duyệt hàng theo ord (streaming, từng lô 500)."""
        with self._lock:
            cur = self._con.cursor()
            cur.execute(f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? ORDER BY ord", (stage, candidate))
        while True:
            with self._lock:
                batch = cur.fetchmany(500)
            if not batch:
                break
            for r in batch:
                yield self._row(r)

    def top_k(self, stage: str, candidate: str, k: int, score_fn: Optional[Callable[[Dict[str, Any]], float]] = None) -> List[Dict[str, Any]]:
        """k hàng điểm cao nhất, xếp (-điểm, ord) — hoà điểm thì cấu hình sinh trước đứng trước (= `sorted` ổn định theo -điểm).
        score_fn(row) -> float (-inf = không đạt); mặc định dùng cột score (NULL = -inf). Duyệt streaming, RAM O(k)."""
        k = max(0, int(k))
        if score_fn is None:
            with self._lock:
                rs = self._con.execute(
                    f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? "
                    f"ORDER BY score IS NULL, score DESC, ord LIMIT ?", (stage, candidate, k)).fetchall()
            return [self._row(r) for r in rs]

        def keyed():
            for row in self.iter_rows(stage, candidate):
                sc = score_fn(row)
                yield (-sc, row["ord"] if row["ord"] is not None else 0), row["job_key"], row
        best = heapq.nsmallest(k, keyed(), key=lambda t: t[0])
        return [t[2] for t in best]

    def page(self, stage: str, candidate: Optional[str] = None, offset: int = 0, limit: int = 100,
             sort: str = "order") -> List[Dict[str, Any]]:
        """Phân trang: sort="order" (thứ tự sinh) hoặc "score" (cao -> thấp, hoà theo ord)."""
        order = "ORDER BY score IS NULL, score DESC, ord" if sort == "score" else "ORDER BY ord"
        q, args = f"SELECT {self._COLS} FROM results WHERE stage=?", [stage]
        if candidate is not None:
            q += " AND candidate=?"
            args.append(candidate)
        q += f" {order} LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 1000)), max(0, int(offset))]
        with self._lock:
            rs = self._con.execute(q, args).fetchall()
        return [self._row(r) for r in rs]

    def candidates(self, stage: str) -> List[str]:
        with self._lock:
            return [r[0] for r in self._con.execute("SELECT DISTINCT candidate FROM results WHERE stage=? ORDER BY candidate", (stage,))]


# ─── Chạy một giai đoạn kiểu streaming (stream_stage) ──────────────────────
def normalize(obj: Any) -> Any:
    """Qua một vòng JSON (np.float64 -> float, tuple -> list...) — đúng thứ sẽ đọc lại từ kho."""
    return json.loads(json.dumps(obj, default=json_default, allow_nan=True))


def stream_stage(items: Iterable[Tuple[int, Any, Any]], fn: Callable, *, workers: int, label: str,
                 store: Optional[ResultsStore], stage: str, candidate: str,
                 key_of: Callable[[int, Any, Any], str],
                 handle: Callable[[int, Any, Dict[str, Any], bool], Tuple[Dict[str, Any], Optional[float]]],
                 progress=None, max_inflight: Optional[int] = None,
                 prepare: Optional[Callable[[Any], None]] = None) -> Dict[str, int]:
    """items: iterable lười của (ord, params, job). Trả {"new": số job vừa chạy, "resumed": số job lấy từ kho}."""
    pending: Dict[int, Tuple[int, Any, str]] = {}
    counts = {"new": 0, "resumed": 0}

    def feeder():
        seq = itertools.count()
        for ord_, params, job in items:
            key = key_of(ord_, params, job)
            row = store.get(key) if store is not None else None
            if row is not None:
                handle(ord_, params, row["metrics"], True)
                counts["resumed"] += 1
                if progress is not None:
                    progress.tick(resumed=True)
                continue
            if prepare is not None:
                prepare(job)
            pending[next(seq)] = (ord_, params, key)
            yield job

    for i, res in pool_imap_bounded(fn, feeder(), workers, label, max_inflight):
        ord_, params, key = pending.pop(i)
        metrics = normalize(res)
        to_store, score = handle(ord_, params, metrics, False)
        if store is not None:
            store.put(key, stage, candidate, params, to_store, ord=ord_, score=score)
        counts["new"] += 1
        if progress is not None:
            progress.tick(worker_peak_mb=metrics.get("_peak_rss_mb") if isinstance(metrics, dict) else None)
    return counts
