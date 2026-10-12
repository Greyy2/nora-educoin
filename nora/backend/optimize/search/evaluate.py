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
import io
import json
import shutil
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.nautilus import catalog as nautilus_catalog
from backend.models.params import DAY_MS as DAY
from backend.alpha.dsl.strategy import display_name
from backend.crawl.store import ByteLRU, CandleLoader, env_mb, read_manifest, require_data_ok, base_name as _base_name
from backend.crawl.store import _file_fingerprint, default_data_root, resolve_symbol_dir   # kho mmap dùng chung (plan)

if TYPE_CHECKING:
    from backend.nautilus.engine import BacktestEngine, PortfolioEngine
from backend.metrics.metrics import daily_stats, flat_extras, portfolio_metrics, series_metrics, sortino
from backend.metrics.trades import trade_rows, trade_stats
from backend.models.models import NORA_DIR


# ══════════════════════════════════════════════════════════════════════════
# Job backtest (POST /api/studio/book/backtest -> optimize/process/process.py -> run_job): một lần PortfolioEngine cho sổ chiến lược.
#
# Tham số (run_job params; mặc định ở DEFAULTS):
#   book        đường dẫn book.json (mặc định data/alpha/book.json) — chiến lược + tham số + rủi ro/lệnh + giới hạn danh mục của sổ đã chốt
#   strategies  [{"id": "trend_long", "params": {...}}] thay cho book; tham số thiếu lấy mức GIỮA của không gian tham số ứng viên
#   start, end  YYYY-MM-DD UTC (ngày kết thúc tính CẢ ngày); mặc định = toàn bộ dữ liệu sau warmup
#   risk_per_trade  % vốn rủi ro mỗi lệnh (mặc định: của sổ, hoặc mức chuẩn 0,5%); stop_fill level|extreme (mặc định level)
#   symbols     perp ("BTC", "BTC@perp") HOẶC DEX ("AERO", "dex:AERO"; spot, chỉ chân LONG) — không trộn hai loại; DEX không bị ép "@perp"
#   data        candle (mặc định: engine nến như mọi tài sản) | tick (chỉ DEX: mỗi swap on-chain là một bước khớp lệnh, chi phí AMM đúng trên dự trữ pool —
#               optimize/search/evaluate.run_tick); latency_ms / gas_usd chỉ cho data=tick (mặc định theo mạng của pool: NETWORKS[mạng]); capital vốn ban đầu
#   out         (tuỳ chọn) ghi kết quả JSON ra đường dẫn này
# Kết quả: số đo danh mục (portfolio_metrics) + by_symbol/by_strategy + lệnh + đường vốn (<= 2000 điểm) -> $NORA_JOB_DIR/result.json.
# ══════════════════════════════════════════════════════════════════════════


WARMUP = 20 * DAY            # bằng build_strategy_book.WARMUP (chỉ số đo từ start trở đi)
MAX_DAYS = 4000


def execute(plan, start: int, end: int, initial_capital: float, close_at_end: bool = False, loaded=None):
    """PortfolioEngine cho một Plan (alpha/dsl/strategy.build_plan) -> (get_results(), engine). Chương trình phải đã được compile_code (đăng ký).
    loaded: threading.Event (chế độ chạy song song, xem tasks.run_parallel) — nạp dữ liệu dưới khoá toàn cục rồi báo `loaded` để lần chạy kế tiếp bắt đầu nạp
    (thứ tự nạp cố định -> bộ nhớ đệm cửa sổ của lần chạy rộng nhất phục vụ các lần sau); phần kernel chạy song song (numba nogil). Người gọi tự chuyển hướng stdout."""
    from backend.nautilus.engine import BacktestEngine, PortfolioEngine
    from backend.alpha.dsl.strategy import RiskConfig
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
    from backend.alpha.dsl.strategy import FRAME_MS
    from backend.models.params import resolve_costs
    from backend.alpha.compile import compile_code
    from backend.alpha.dsl.strategy import build_plan
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
    from backend.optimize.book.build import BY_ID
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
    from backend.crawl.store import alpha_file
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
    """Đặc tả MỘT lần backtest danh mục — dùng chung cho dựng sổ (optimize/book), WFA (wfa/wfa) và phễu (optimize/funnel).
    items: [(id chiến lược lõi, tham số)]; window: (start, end) ms — chỉ số đo từ start, nạp thêm WARMUP trước đó; symbols None = vũ trụ
    perp của sổ; shared_dir None = env NORA_SHARED_DATA_DIR (crawl/store.py); base_frame = khung chạy (nến mô phỏng)."""
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
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.optimize.book.build import lift_frames
    from backend.models.params import materialize
    from backend.optimize.book.build import perp_symbols, BY_ID
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
    from backend.optimize.book.build import BY_ID
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.optimize.process.workers import peak_rss_mb
    by_id = BY_ID
    from backend.optimize.book.build import lift_frames
    spot = {}
    if venue == "dex":
        from backend.alpha.dsl import strategy as dex
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
    from backend.optimize.process.process import DEX_UNSUPPORTED, NotReady
    raise NotReady(DEX_UNSUPPORTED)


# ══════════════════════════════════════════════════════════════════════════
# Phía WORKER của phễu: backtest danh mục một alpha, WFA cố định tham số, Monte Carlo, tìm/xác nhận hệ số s, holdout.
#
# Mọi hàm `w_*` là hàm cấp module (pickle được qua ProcessPoolExecutor), nhận một dict `job` thuần dữ liệu và trả dict thuần dữ liệu.
# Máy chạy là PortfolioEngine DÙNG LẠI (cùng đường với build_strategy_book giai đoạn A / validate_book): không có logic mô phỏng riêng ở đây.
# Dữ liệu giá + kernel đọc qua mmap dùng chung (backend/crawl/store.py) khi `shared_dir` có đặt; không thì tự dựng (cùng kết quả từng bit).
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


def learned_regime(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Alpha regime="learn": chạy chế độ quan sát (SL level, kill tắt) trên cửa sổ HỌC (job["learn_window"], mặc định chính cửa sổ của job —
    S1 dev1 là trong mẫu, đã tính là một lần thử riêng trong DSR/PBO) -> bảng regime của chiến lược (None = không chặn regime nào)."""
    from backend.metrics.regime import OBSERVE, engine_by_regime, learn_map
    obs = to_job({**job, "window": job.get("learn_window") or job["window"], "stop_fill": "level", "kill": False, "regime_map": OBSERVE})
    eng, _ = make_engine(obs)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    return learn_map(engine_by_regime(eng, eng.get_results()["positions"]), [job["strategy"]])[job["strategy"]]


def make_engine_from_dict(job: Dict[str, Any]):
    return make_engine(to_job(job))


def _outputs(res: Dict[str, Any], start: int, want_trades: bool) -> Dict[str, Any]:
    """get_results() của một lần chạy -> {"metrics", "daily", "daily_start", "trades"} (số đo phẳng của phễu, không gồm chuỗi ngày)."""
    pm = portfolio_metrics(res, start)
    daily = pm["daily"]

    first = next((c["time"] for c in res["equity_curve"] if c["time"] >= start), None)
    rows = trade_rows(res["positions"])
    ds = daily_stats(daily)
    m = {
        "ret_pct": pm["ret_pct"], "mdd_pct": pm["mdd_pct"], "sharpe": pm["sharpe"], "sortino": round(sortino(daily) or 0.0, 2),
        "trades": pm["trades"], "symbols_positive": pm["symbols_positive"], **trade_stats(rows),
        "sr_daily": round(ds["sr_daily"], 6), "skew": round(ds["skew"], 4), "kurt": round(ds["kurt"], 4), "n_days": ds["n_days"],
        "fees_usd": pm["fees_usd"], "funding_usd": pm["funding_usd"], "halted": bool(pm["halted_at"]),
        "by_symbol": pm["by_symbol"],
        "mdd_intrabar_pct": pm["mdd_intrabar_pct"], "mdd_daily_pct": pm["mdd_daily_pct"], "mdd_basis": "intrabar", **flat_extras(pm["stats"]),
    }
    return {"metrics": m, "daily": daily, "daily_start": f"{pd.Timestamp(int(first), unit='ms'):%Y-%m-%d}" if first is not None else None,
            "trades": rows if want_trades else None}


def run_backtest(job: Dict[str, Any], want_trades: bool = False) -> Dict[str, Any]:
    """Một lần PortfolioEngine -> {"metrics", "daily", "daily_start", "trades"}. Alpha regime="learn": học bảng regime trước (learned_regime)."""
    if job.get("regime_mode") == "learn":
        job = {**job, "regime_map": learned_regime(job)}
    eng, start = make_engine_from_dict(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    out = _outputs(eng.get_results(), start, want_trades)
    if job.get("regime_mode") == "learn":
        out["metrics"]["regime_blocked"] = (job["regime_map"] or {}).get("blocked", [])
    return out


def signal_key(job: Dict[str, Any]) -> str:
    """Khoá nhóm cho run_many: cùng chiến lược + cùng cây tín hiệu sau khi thay tham số + cùng đơn vị thoát / khung ATR + cùng cửa sổ/tài sản/
    kill/stop_fill -> dữ liệu và tín hiệu dùng chung; chỉ tham số vị thế/thoát lệnh khác nhau."""
    import json
    from backend.models.params import materialize
    from backend.optimize.book.build import BY_ID
    by_id = BY_ID
    st = materialize(by_id[job["strategy"]], job["params"], stop_fill=job["stop_fill"], risk_per_trade_pct=job["rpt"])
    pos = st["position"]
    return json.dumps([job["strategy"], st["tree"], st.get("stop"), pos.get("exit_unit"), pos.get("atr_frame"), pos.get("atr_period"),
                       job["window"], job["kill"], list(job["symbols"]), job.get("base_frame", "1m"), job.get("regime_mode")],
                      sort_keys=True, default=str)


def run_backtest_many(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nhiều alpha CÙNG signal_key: nạp dữ liệu + tính tín hiệu một lần (engine của job đầu), chạy các bộ tham số vị thế bằng
    PortfolioEngine.run_many (trùng từng bit với chạy riêng — test_kernel_parity / test_funnel)."""
    from backend.models.params import materialize
    from backend.optimize.book.build import BY_ID
    if jobs[0].get("regime_mode"):   # bảng regime học riêng từng alpha -> tín hiệu vào khác nhau, chạy riêng
        return [run_backtest(j, bool(j.get("trades"))) for j in jobs]
    by_id = BY_ID
    eng, start = make_engine_from_dict(jobs[0])
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
        results = eng.run_many([materialize(by_id[j["strategy"]], j["params"], stop_fill=j["stop_fill"], risk_per_trade_pct=j["rpt"])["position"]
                                for j in jobs])
    return [_outputs(r, start, bool(j.get("trades"))) for r, j in zip(results, jobs)]


def base_job(strategy: str, params: Dict[str, Any], window, stop_fill: str, kill: bool, rpt: float, symbols, shared_dir,
             base_frame: str = "1m", learn_window=None) -> Dict[str, Any]:
    """params có thể kèm khoá regime ("learn") -> tách ra regime_mode; learn_window: cửa sổ học bảng regime (mặc định = window)."""
    from backend.optimize.search.generate import split_regime
    params, rmode = split_regime(params)
    job = {"strategy": strategy, "params": params, "window": [int(window[0]), int(window[1])], "stop_fill": stop_fill, "kill": kill,
           "rpt": rpt, "symbols": list(symbols), "shared_dir": shared_dir, "base_frame": base_frame}
    if rmode:
        job["regime_mode"] = rmode
        if learn_window is not None:
            job["learn_window"] = [int(learn_window[0]), int(learn_window[1])]
    return job


# ── Monte Carlo (DÙNG LẠI backend/carlo/carlo.py) ─────────────────────
def _mc_kwargs(scale: float) -> Dict[str, Any]:
    from backend.optimize.funnel import stages as gates
    return dict(simulations=gates.S4_MIN_SIMULATIONS, block_days=gates.S4_BLOCK_DAYS, horizon_days=gates.S4_HORIZON_DAYS,
                ruin_threshold_pct=gates.S4_RUIN_THRESHOLD_PCT, seed=gates.S4_SEED, scale=scale,
                max_ruin_pct=gates.S4_MAX_RUIN_PCT, stress_max_mdd_pct=gates.S4_STRESS_MAX_MDD_PCT)


def _gate_of(simulations: int, ruin: float, stress) -> Dict[str, Any]:
    from backend.optimize.funnel import stages as gates
    from backend.carlo.carlo import evaluate_mc_gate
    return evaluate_mc_gate(simulations, ruin, stress, min_simulations=gates.S4_MIN_SIMULATIONS, max_ruin_pct=gates.S4_MAX_RUIN_PCT,
                            ruin_threshold_pct=gates.S4_RUIN_THRESHOLD_PCT, stress_max_mdd_pct=gates.S4_STRESS_MAX_MDD_PCT)


def mc_check(series, scale: float, shock: Optional[Dict[str, float]] = None, turnover: Optional[float] = None) -> Dict[str, Any]:
    """MC dạng gate (không điểm vẽ) trên chuỗi ngày × scale -> {"passed", "p_mdd_ge_30", "stress_max_mdd", "gate", "summary"}.
    shock (metrics["shock"] của S3): thêm kịch bản trend thẳng đứng (lỗ nhân scale).
    turnover (metrics["turnover_daily"] của S3, lần vốn/ngày ĐO TỪ LỆNH): cho kịch bản cost_x2; None -> cost_x2 "không đo được", cổng không đạt."""
    from backend.carlo.carlo import extra_cost_from_turnover, run_monte_carlo_daily_gate
    r = run_monte_carlo_daily_gate(series, **_mc_kwargs(scale), shock=shock, extra_cost_daily=extra_cost_from_turnover(turnover))
    gate = _gate_of(r["simulations"], r["p_mdd_ge_ruin_pct"], r["stress"])
    return {"passed": bool(gate["passed"]), "p_mdd_ge_30": r["p_mdd_ge_ruin_pct"],
            "stress_max_mdd": max((x["mdd_pct"] for x in r["stress"] if x["mdd_pct"] is not None), default=None), "gate": gate,
            "summary": {k: r[k] for k in ("median_ret_pct", "p05_ret_pct", "mdd_p50_pct", "mdd_p95_pct", "p_mdd_ge_ruin_pct", "simulations")}}


def mc_detail(series, scale: float, basis: str = "extreme", shock: Optional[Dict[str, float]] = None,
              turnover: Optional[float] = None) -> Dict[str, Any]:
    """MC chi tiết (quạt, histogram, kịch bản cực xấu có đường vẽ) + gate theo ngưỡng của phễu. Ghi vào mc/<alpha_id>.json."""
    from backend.carlo.carlo import extra_cost_from_turnover, run_monte_carlo_daily_detail
    out = run_monte_carlo_daily_detail(series, **_mc_kwargs(scale), shock=shock, extra_cost_daily=extra_cost_from_turnover(turnover))
    out["gate"] = _gate_of(out["summary"]["simulations"], out["summary"]["p_mdd_ge_ruin_pct"], out["stress"])
    out["params"] = {**out["params"], "basis": basis}
    return out


# ── WFA tham số cố định ─────────────────────────────────────────────────────
def fold_job_plan(folds: List[Dict[str, int]]) -> List[Dict[str, Any]]:
    from backend.models.params import iso_date
    return [{"fold": i + 1, "train": [f["train_start_ts"], f["train_end_ts"]], "test": [f["test_start_ts"], f["test_end_ts"]],
             "train_iso": [iso_date(f["train_start_ts"]), iso_date(f["train_end_ts"])],
             "test_iso": [iso_date(f["test_start_ts"]), iso_date(f["test_end_ts"])]} for i, f in enumerate(folds)]


def run_wfa(strategy: str, params: Dict[str, Any], folds: List[Dict[str, Any]], symbols, rpt: float, shared_dir: Optional[str],
            base_frame: str = "1m") -> Dict[str, Any]:
    """Mỗi fold: IS = backtest cửa sổ train (SL level, kill tắt); OOS = backtest cửa sổ test (SL extreme = khớp bi quan, kill BẬT).
    Cùng quy ước validate_book với một cấu hình duy nhất (không chọn lại tham số). Cơ sở kết luận là OOS extreme."""
    out = []
    for f in folds:
        is_r = run_backtest(base_job(strategy, params, f["train"], "level", False, rpt, symbols, shared_dir, base_frame))
        oos = run_backtest(base_job(strategy, params, f["test"], "extreme", True, rpt, symbols, shared_dir, base_frame, learn_window=f["train"]),
                           want_trades=True)   # regime="learn": bảng regime học trên train của fold
        out.append({"fold": f["fold"], "train": f["train_iso"], "test": f["test_iso"], "is_ret_pct": is_r["metrics"]["ret_pct"],
                    "is_trades": is_r["metrics"]["trades"], "oos": oos["metrics"], "daily": oos["daily"],
                    "daily_start": oos["daily_start"] or f["test_iso"][0], "trades": oos["trades"]})
    return {"folds": out}


def aggregate_wfa(folds: List[Dict[str, Any]], rpt: Optional[float] = None) -> Dict[str, Any]:
    """-> {"summary" (cho evaluate_s3), "metrics" (stage_metrics S3), "series" (chuỗi ngày OOS nối), "trades" (có cột fold), "daily" (theo fold)}.
    rpt (rủi ro/lệnh lúc chạy OOS): metrics["shock"] = vị thế ngược chiều lớn nhất (carlo.vertical_exposure) cho kịch bản trend thẳng đứng."""
    n = len(folds)
    series = [x for f in folds for x in f["daily"]]
    trades = [{**t, "fold": f["fold"]} for f in folds for t in (f["trades"] or [])]
    positive = sum(1 for f in folds if f["oos"]["ret_pct"] > 0)
    compounded = round(float((np.prod(1.0 + np.asarray(series, dtype=float)) - 1.0) * 100), 2) if series else 0.0
    is_avg = round(sum(f["is_ret_pct"] for f in folds) / n, 2) if n else None
    from backend.wfa.wfa import fold_stats
    fs = fold_stats([f["oos"]["ret_pct"] for f in folds], [f["oos"]["trades"] > 0 for f in folds])
    summary = {"folds": n, "positive_ratio": fs["positive_ratio"], "compounded_oos_ret_pct": compounded,
               "worst_fold_mdd": max((f["oos"]["mdd_pct"] for f in folds), default=0.0), "is_ret_avg": is_avg,
               "traded_folds": fs["traded_folds"], "fold_t": fs["fold_t"], "oos_ex_best_pct": fs["oos_ex_best_pct"]}
    metrics = {**series_metrics(series, trades), "folds": n, "folds_profitable": positive, "positive_ratio": round(summary["positive_ratio"], 4),
               "traded_folds": fs["traded_folds"], "fold_t": fs["fold_t"], "oos_ex_best_pct": fs["oos_ex_best_pct"],
               "worst_fold_mdd": summary["worst_fold_mdd"], "is_ret_avg": is_avg,
               "fold_detail": [{"fold": f["fold"], "train": f["train"], "test": f["test"], "is_ret_pct": f["is_ret_pct"],
                                "oos_ret_pct": f["oos"]["ret_pct"], "oos_mdd_pct": f["oos"]["mdd_pct"], "trades": f["oos"]["trades"],
                                "halted": f["oos"]["halted"]} for f in folds]}
    from backend.carlo.carlo import measure_turnover
    tv = measure_turnover(None if any(f["trades"] is None for f in folds) else trades, len(series))   # vòng quay vốn đo từ lệnh OOS -> cost_x2 của MC
    metrics["turnover_daily"], metrics["turnover_note"] = tv["turnover_daily"], tv["note"]
    if rpt is not None:
        from backend.carlo.carlo import vertical_exposure
        metrics["shock"] = vertical_exposure(trades, rpt)
    daily = [{"fold": f["fold"], "start": f["daily_start"], "rets": f["daily"]} for f in folds]
    return {"summary": summary, "metrics": metrics, "series": series, "trades": trades, "daily": daily}


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
    from backend.optimize.book.build import BY_ID, configs
    by_id = BY_ID
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": configs(by_id[i], n, seed)} for i in ids]


def candidates_from_list(raw):
    """Cấu hình do người dùng chọn: [{"id", "configs": [{tham số}]}] -> đúng như vậy (kiểm id/khoá tham số theo `space` + `params_schema`)."""
    from backend.optimize.book.build import BY_ID
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


from backend.optimize.process.workers import pool_map_safe
_pool_map = pool_map_safe


def run_wfa_job(job):
    from backend.optimize.process.workers import peak_rss_mb, rss_anon_mb
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
    from backend.optimize.funnel.storage import data_fingerprint, make_job_key
    from backend.optimize.funnel.storage import normalize
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
    from backend.optimize.book.build import strip_metrics
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


# ── Hàm worker (một job = một alpha) ────────────────────────────────────────
def w_backtest(job: Dict[str, Any]) -> Dict[str, Any]:
    """S1 / điểm lân cận (S3) / tính lại lệnh: job gồm các khoá của base_job + "trades": False | True | "pass" (chỉ trả lệnh khi qua S1)."""
    from backend.optimize.funnel import stages as gates
    try:
        out = run_backtest(job, want_trades=bool(job.get("trades")))
        if job.get("trades") == "pass" and not gates.evaluate_s1(out["metrics"])[0]:
            out["trades"] = None   # alpha bị loại ở S1: chỉ lưu thống kê (lệnh tính lại khi cần)
        return out
    except ValueError as exc:   # tham số không hợp lệ ngoài dự kiến (S0 đã lọc phần lớn) -> loại alpha này, không sập cả lượt
        return {"error": f"{type(exc).__name__}: {exc}"}


def w_backtest_group(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """S1 theo nhóm: group = {"jobs": [job w_backtest, ...]} cùng signal_key -> danh sách kết quả cùng thứ tự (như w_backtest từng job).
    Lỗi tham số ở một job -> chạy riêng từng job của nhóm để chỉ alpha lỗi bị loại."""
    from backend.optimize.funnel import stages as gates
    jobs = group["jobs"]
    try:
        outs = run_backtest_many(jobs)
    except ValueError:
        return [w_backtest(j) for j in jobs]
    for j, out in zip(jobs, outs):
        if j.get("trades") == "pass" and not gates.evaluate_s1(out["metrics"])[0]:
            out["trades"] = None
    return outs


def w_backtest_group_rss(group: Dict[str, Any]) -> Dict[str, Any]:
    """w_backtest_group + RAM RIÊNG của worker sau nhóm (heap, không gồm trang mmap dùng chung) -> progress.worker_peak_rss_mb."""
    from backend.optimize.process.workers import rss_anon_mb
    outs = w_backtest_group(group)
    return {"outs": outs, "rss_anon_mb": round(rss_anon_mb(), 1)}


def w_wfa(job: Dict[str, Any]) -> Dict[str, Any]:
    """S3: job = {strategy, params, folds (fold_job_plan), symbols, rpt, shared_dir}."""
    try:
        return run_wfa(job["strategy"], job["params"], job["folds"], job["symbols"], job["rpt"], job["shared_dir"], job.get("base_frame", "1m"))
    except ValueError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def w_mc(job: Dict[str, Any]) -> Dict[str, Any]:
    """S4: job = {series, shock?}. Chi tiết ở s = 1 (ghi mc/<alpha>.json) + gate ở hệ số tối thiểu S5_S_MIN (alpha còn cứu được bằng giảm khối lượng không?)."""
    from backend.optimize.funnel import stages as gates
    series = job["series"]
    if len(series) < gates.S4_MIN_DAYS:
        return {"days": len(series), "detail": None, "min_size": None}
    detail = mc_detail(series, 1.0, shock=job.get("shock"), turnover=job.get("turnover"))
    mn = mc_check(series, gates.S5_S_MIN, job.get("shock"), job.get("turnover"))
    return {"days": len(series), "detail": detail, "min_size": {"s": gates.S5_S_MIN, **{k: mn[k] for k in ("passed", "p_mdd_ge_30", "stress_max_mdd", "gate")}}}


def w_sizing(job: Dict[str, Any]) -> Dict[str, Any]:
    """S5: tìm nhị phân s trên chuỗi ngày nhân s; xác nhận bằng S1 + WFA + MC thật ở s (hạ s từng bước nếu trượt).
    job = {strategy, params, series, shock?, windows {start, dev1_end}, folds, symbols, shared_dir}."""
    from backend.optimize.funnel import stages as gates
    from backend.optimize.funnel import stages as sizing
    series = np.asarray(job["series"], dtype=float)
    s_star, steps = sizing.search_scale(lambda s: mc_check(series, s, job.get("shock"), job.get("turnover")))
    if s_star is None:
        return {"s": None, "search": steps, "attempts": [], "reason": "scale_low"}
    keep: Dict[str, Any] = {}

    def confirm(s: float) -> Dict[str, Any]:
        rpt = sizing.risk_for_scale(s)
        r1 = run_backtest(base_job(job["strategy"], job["params"], (job["windows"]["start"], job["windows"]["dev1_end"]), "level", False, rpt,
                                   job["symbols"], job["shared_dir"], job.get("base_frame", "1m")))
        ok1 = gates.evaluate_s1(r1["metrics"])
        att: Dict[str, Any] = {"backtest": ok1[0], "backtest_ret_pct": r1["metrics"]["ret_pct"], "backtest_mdd_pct": r1["metrics"]["mdd_pct"],
                               "wfa": None, "mc": None, "passed": False}
        if not ok1[0]:
            att["reason"] = ok1[2]
            return att
        wfa = aggregate_wfa(run_wfa(job["strategy"], job["params"], job["folds"], job["symbols"], rpt, job["shared_dir"],
                                    job.get("base_frame", "1m"))["folds"], rpt)
        ok3 = gates.evaluate_s3(wfa["summary"])
        att["wfa"] = ok3[0]
        if not ok3[0]:
            att["reason"] = ok3[2]
            return att
        if len(wfa["series"]) < gates.S4_MIN_DAYS:
            att["mc"], att["reason"] = False, "quá ít ngày OOS"
            return att
        mcr = mc_check(wfa["series"], 1.0, wfa["metrics"].get("shock"), wfa["metrics"].get("turnover_daily"))
        att["mc"], att["p_mdd_ge_30"], att["stress_max_mdd"] = mcr["passed"], mcr["p_mdd_ge_30"], mcr["stress_max_mdd"]
        att["passed"] = bool(mcr["passed"])
        if not att["passed"]:
            att["reason"] = gates.evaluate_mc_checks(mcr["gate"], "S5")[2]
        else:
            keep.update(s=s, wfa=wfa, backtest=r1)
        return att

    s_ok, attempts = sizing.confirm_with_stepdown(s_star, confirm)
    out: Dict[str, Any] = {"s": s_ok, "s_search": s_star, "search": steps, "attempts": attempts}
    if s_ok is None:
        out["reason"] = "scale_low" if (attempts and attempts[-1]["s"] - gates.S5_CONFIRM_STEP < gates.S5_S_MIN - 1e-9) else "confirm"
        return out
    wfa = keep["wfa"]
    out.update({"wfa": wfa, "backtest": {"metrics": keep["backtest"]["metrics"]}, "mc_detail": mc_detail(wfa["series"], 1.0, basis="confirmed_wfa_at_s",
                                                                                                      shock=wfa["metrics"].get("shock"),
                                                                                                      turnover=wfa["metrics"].get("turnover_daily"))})
    return out


def w_holdout(job: Dict[str, Any]) -> Dict[str, Any]:
    """S6: chạy MỘT lần ở hệ số s trên holdout: SL khớp đúng mức ("level") và giá xấu nhất ("extreme"), kill switch BẬT."""
    win = (job["windows"]["dev2_end"], job["windows"]["end"])
    learn = (job["windows"]["start"], job["windows"]["dev2_end"])   # regime="learn": học trên toàn bộ dữ liệu trước holdout
    out = {}
    for fill in ("level", "extreme"):
        out[fill] = run_backtest(base_job(job["strategy"], job["params"], win, fill, True, job["rpt"], job["symbols"], job["shared_dir"],
                                          job.get("base_frame", "1m"), learn_window=learn), want_trades=True)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Làm nóng / dọn kho dữ liệu dùng chung (crawl/store.py) cho MỌI lối chạy nhiều alpha: dựng sổ (optimize/book), WFA
# (wfa/wfa) và phễu (optimize/funnel). Một chỗ duy nhất — trước đây mỗi lối có bản riêng.
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
#   nền  = sha1(tài sản, nguồn, cửa sổ, khung chạy, điểm bắt đầu nạp, perp, vân tay file khung chạy + funding.pkl)
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


def _stat(path: Optional[str]):
    try:
        st = os.stat(path) if path else None
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size] if st else None


def plan(eng: "BacktestEngine") -> Optional[Dict[str, Any]]:
    """Khoá nền + khoá từng khung / cột / chỉ số căn cho đúng bộ dữ liệu `eng` sẽ dựng. None nếu không có 1m.pkl."""
    from backend.alpha.dsl.strategy import FRAME_MS, needs_minute_path, slot_fresh_frames
    from backend.alpha.dsl.signal import lag_key
    root = default_data_root()
    base_fr = eng.base_frame
    fp1 = _file_fingerprint(eng.symbol, base_fr, root)
    if fp1 is None:
        return None
    refs = eng._refs_by_frame()
    if any(col.startswith("py_") for rs in refs.values() for col, _ in rs):
        return None   # cột chương trình Python (P7) tính trong tiến trình, KHÔNG ghi vào kho dùng chung
    perp = any(tr.market == "perp" for tr in eng.slots)
    sym_dir = resolve_symbol_dir(eng.symbol)
    base = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "start": int(eng.start_ts), "end": int(eng.end_ts),
                  "base_frame": base_fr, "load_base": int(eng.start_ts - eng._warmup_ms(base_fr, refs.get(base_fr, set()))),
                  "perp": perp, "fp_base": list(fp1), "minute": needs_minute_path(eng),
                  "fp_1m": list(_file_fingerprint(eng.symbol, "1m", root) or []) if needs_minute_path(eng) else None,
                  "fp_funding": _stat(os.path.join(sym_dir, "funding.pkl")) if (perp and sym_dir) else None})
    frames: Dict[str, Dict[str, str]] = {}
    cols: Dict[str, Dict[str, str]] = {}
    for frame in ([base_fr] if base_fr in refs else []) + [f for f in refs if f != base_fr]:   # cùng thứ tự với _build_matrix
        if frame not in FRAME_MS:
            continue
        fp = _file_fingerprint(eng.symbol, frame, root)
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
    from backend.alpha.dsl.strategy import FRESH, SignalEngine, frame_fresh
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
    from backend.alpha.dsl.signal import lag_key
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
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (thiếu 1m.pkl)")
        if any(fill(out_dir, pe, eng, p).values()):
            out["written"].append(sym)
        out["paths"] |= paths(p)
    return out


def remove(out_dir: str, rel_paths: Iterable[str]) -> None:
    """Xoá các phần (thư mục nền / file) theo đường dẫn tương đối — dọn sau một giai đoạn."""
    for rel in rel_paths:
        path = os.path.join(out_dir, rel)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


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
    from backend.alpha.dsl.strategy import data_cache_clear
    from backend.crawl.store import CandleLoader
    CandleLoader.clear_cache()
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
            from backend.optimize.process.workers import pool_map_safe
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


# ══════════════════════════════════════════════════════════════════════════
# Nguồn dữ liệu mặc định của engine (từ module data cũ): cài đặt models/models.DataSource trên crawl/store + kho mmap ở trên.
# ══════════════════════════════════════════════════════════════════════════

class EngineData:
    """DataSource (models/models.DataSource) trên dữ liệu local: nến (CandleLoader, có cache theo tiến trình), funding.pkl, manifest, cổng chất lượng, kho mmap dùng chung,
    bộ nhớ đệm mảng đã dựng (memo: ByteLRU theo NORA_DATA_CACHE_MB, mặc định 1500 MB — tạo ở lần dùng đầu)."""

    def __init__(self) -> None:
        self._memo = None

    def candles(self, symbol: str, frame: str, start: int, end: int, columns: Optional[List[str]] = None, use_cache: bool = True):
        return CandleLoader(symbol, frame=frame, use_cache=use_cache).load_data(start, end, columns=columns)

    def exec_arrays(self, symbol: str, frame: str, start: int, end: int):
        """Nến thực thi từ ParquetDataCatalog Nautilus (kho nến chuẩn của engine; cache theo tiến trình ở nautilus/catalog)."""
        return nautilus_catalog.exec_arrays(symbol, frame, start, end)

    def instrument_spec(self, symbol: str):
        """Spec OKX thật (data/market/okx/instruments.json)."""
        return nautilus_catalog.instrument_spec(symbol)

    def funding(self, symbol: str):
        path = resolve_symbol_dir(symbol)
        file = os.path.join(path, "funding.pkl") if path else None
        if not file or not os.path.isfile(file):
            return None
        return pd.read_pickle(file)

    def require_ok(self, symbols: List[str]):
        return require_data_ok(symbols)

    def manifest(self, symbol: str) -> Optional[Dict[str, Any]]:
        return read_manifest(symbol)

    def base_name(self, symbol: str) -> str:
        return _base_name(symbol)

    def shared_plan(self, eng):
        return plan(eng)

    def shared_load(self, out_dir: str, plan: Dict[str, Any]):
        return load(out_dir, plan)

    def shared_fill(self, out_dir: str, pe, eng, plan: Dict[str, Any]):
        return fill(out_dir, pe, eng, plan)

    def release(self) -> None:
        CandleLoader.clear_cache()

    @property
    def memo(self):
        if self._memo is None:
            self._memo = ByteLRU(env_mb("NORA_DATA_CACHE_MB", 1500))
        return self._memo


ENGINE_DATA = EngineData()


def make_engine_data() -> EngineData:
    """Nhà máy nguồn dữ liệu mặc định (backend/optimize/__init__.py đăng ký LƯỜI qua core.models.set_default_data_factory)."""
    return ENGINE_DATA
