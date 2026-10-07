"""Job custom_backtest (POST /api/studio/custom/backtest -> api/jobs/runner.py -> run_job): chiến lược Python (DSL SimpleAlgorithm) chạy trên PortfolioEngine.

Một engine duy nhất: code được biên dịch (core/strategy/pydsl, KHÔNG exec), đăng ký thành cột kernel `py_<hash12>_*`, rồi cấu hình thực thi mặc định của Nora
(core/strategy/pydsl/profiles: perp OKX, định cỡ theo rủi ro, SL 3×ATR) dựng chiến lược dict cho PortfolioEngine y như chiến lược lõi.
Kết quả ghi $NORA_JOB_DIR/result.json (docs/bmad/p7_python_strategies.md §6). Dữ liệu = kho OKX (crawl/store).

Tham số (run_job params; mặc định ở DEFAULTS):
  code            mã Python `class X(SimpleAlgorithm)` (bắt buộc)
  symbols         danh sách tài sản (BTC hoặc BTC@perp); trống = cả rổ perp OKX có trong kho dữ liệu (default_universe)
  start, end      YYYY-MM-DD UTC (ngày kết thúc tính cả ngày)
  train_ratio     tỉ lệ giai đoạn train (mặc định 0,7): mốc chia = đầu năm dương lịch gần nhất không sau start + ratio × (end - start)
  initial_capital vốn ban đầu (mặc định 10000)
  position        ghi đè tham số vị thế: khoá theo params.builder.POSITION_KEYS
  run_frame       khung chạy (nến mô phỏng); trống = 1m
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import io
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.backtest.run_defaults import DAY, DEFAULT_CAPITAL, DEFAULT_TRAIN_RATIO, default_universe, iso_day as _iso
from backend.utils.jobs import as_list, options, write_job_result

ANN_DAYS = 365                       # năm = 365 ngày (core/metrics/returns.ANN): MỘT quy ước quy năm cho mọi chỉ số
MIN_YEAR_DAYS = 2                    # bảng yearly chỉ giữ năm có >= 2 ngày lợi suất (Sharpe/độ lệch cần >= 2)
WARMUP = 20 * DAY
MAX_DAYS = 4000                      # trần ngày của BacktestEngine.MAX_BACKTEST_DAYS (1100) được nâng trong tiến trình job: cho phép chạy nhiều năm
DEFAULTS = {"code": "", "symbols": None, "start": "", "end": "", "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": None, "position": None, "run_frame": ""}


def _ts(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").value // 1_000_000)


# ─── Chọn tài sản + kiểm dữ liệu ────────────────────────────────────────────

def resolve_symbols(symbols: Optional[List[str]]) -> List[str]:
    """Tên cơ sở (BTC, ETH, ...) của rổ: `symbols` nếu có, không thì default_universe()."""
    from backend.core.strategy.pydsl.profiles import base_name
    if symbols:
        return list(dict.fromkeys(base_name(s) for s in symbols))
    names = default_universe()
    if not names:
        raise ValueError("Kho dữ liệu chưa có tài sản perp nào")
    return names


def check_data(data_symbols: List[str]) -> None:
    from backend.crawl.store import exchange, list_assets, resolve_asset_dir
    missing = [s for s in data_symbols if not resolve_asset_dir(s)]
    if missing:
        have = sorted({a["symbol"] for a in list_assets()})
        raise ValueError(f"Không có dữ liệu sàn {exchange()} cho {missing}; tài sản có: {have}")


def data_info(data_symbols: List[str], start: int, end: int, source: str) -> Tuple[Dict[str, Any], List[str]]:
    from backend.crawl.store import read_manifest
    warns, sha = [], {}
    for s in data_symbols:
        m = read_manifest(s) or {}
        sha[s] = m.get("sha256_1m")
        if m.get("start_ts") and start < int(m["start_ts"]):
            warns.append(f"{s}: dữ liệu bắt đầu {_iso(int(m['start_ts']))}, sau start {_iso(start)} — giữ tiền mặt tới nến đầu có dữ liệu")
        if m.get("end_ts") and end - DAY > int(m["end_ts"]):
            warns.append(f"{s}: dữ liệu kết thúc {_iso(int(m['end_ts']))}, trước end {_iso(end - DAY)}")
    return {"source": source, "sha256_1m": sha}, warns


# ─── Chạy engine ────────────────────────────────────────────────────────────

def execute(plan, start: int, end: int, initial_capital: float, close_at_end: bool = False):
    """PortfolioEngine cho một Plan (core/strategy/pydsl/profiles) -> (get_results(), engine). Chương trình phải đã được compile_code (đăng ký)."""
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    BacktestEngine.MAX_BACKTEST_DAYS = max(BacktestEngine.MAX_BACKTEST_DAYS, MAX_DAYS)
    eng = PortfolioEngine(plan.symbols, plan.strategies, start - WARMUP, end, trade_start_ts=start, initial_capital=initial_capital,
                          risk=RiskConfig.from_dict(plan.risk), venue=plan.venue, close_at_end=close_at_end, base_frame=plan.base_frame,
                          shared_dir=None)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    return eng.get_results(), eng


# ─── Benchmark "luôn long" + đầu vào chẩn đoán ──────────────────────────────

BENCH_CODE = ('class AlwaysLong(SimpleAlgorithm):\n    timeframe = "{tf}"\n    def __algorithm__(self):\n'
              '        self.set_positions(self.data.pv_close > 0, position=1)\n')
NO_EXIT_POSITION = {"stop_loss_rate": 0.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0}
_BENCH_CACHE: Dict[str, Dict[str, Any]] = {}      # mỗi cấu hình (rổ, khung, ngày, vốn, dữ liệu) chỉ chạy benchmark MỘT lần trong tiến trình


def run_benchmark(program, a, plan, names: List[str], start: int, end: int, capital: float, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Benchmark "luôn long" `self.set_positions(self.data.pv_close > 0, position=1)` chạy qua CÙNG đường engine: cùng rổ, khung, run_frame, start/end, vốn, nguồn dữ liệu.
    Chia vốn đều giữa các tài sản, đòn bẩy 1, bỏ SL/TP/trailing/timeout và giới hạn rủi ro danh mục (định cỡ theo rủi ro cần SL; benchmark phải nắm giữ).
    Trả {times, equity, label, ...}; lỗi -> None (người gọi ghi cảnh báo)."""
    import json
    from backend.core.backtest.engine import FRAME_MS
    from backend.core.params.builder import resolve_costs
    from backend.core.strategy.pydsl import compile_code
    from backend.core.strategy.pydsl.profiles import build_plan
    position = {**(program.position_overrides or {}), **(a.position or {})}
    taker = resolve_costs(plan.venue, "perp", position.get("fee_rate"), position.get("slippage_rate"), position.get("maker_fee_rate"))[0]
    position.update(NO_EXIT_POSITION)
    position.update(sizing="margin_pct", leverage=1, order_size_pct=100.0 / len(names) / (1.0 + taker) * (1.0 - 1e-9))
    key = json.dumps([plan.symbols, program.timeframe, plan.base_frame, start, end, capital, data.get("source"), data.get("sha256_1m"), sorted(position.items())],
                     sort_keys=True, default=str)
    hit = _BENCH_CACHE.get(key)
    if hit is not None:
        return hit
    bench_prog = compile_code(BENCH_CODE.format(tf=program.timeframe))
    bplan = build_plan(bench_prog, names, position=position, run_frame=plan.base_frame)
    bplan.risk = {"max_positions": max(1, len(names)), "max_per_symbol": 1, "max_gross_exposure": 1e6, "kill_switch_dd_pct": 0.0, "max_open_risk_pct": 0.0, "dd_throttle_pct": 0.0}
    res, _ = execute(bplan, start, end, capital)
    ser = daily_series(res["equity_curve"], start, end, FRAME_MS[bplan.base_frame], capital)
    out = {"times": ser["times"], "equity": ser["equity"], "program_hash": bench_prog.code_hash, "strategies": [s["id"] for s in bplan.strategies],
           "label": "Luôn long (position=1) cùng rổ/ngày/vốn, chia đều, đòn bẩy 1, không SL/TP/trailing/timeout/kill-switch", "symbols": bplan.symbols}
    _BENCH_CACHE[key] = out
    return out


def diagnostic_inputs(plan, program, end: int) -> Dict[str, Any]:
    """Dữ liệu thật cho chẩn đoán: giá ngày từng tài sản, chuỗi thị trường (BTC hoặc chỉ số rổ đều), nến khung chiến lược (binding_condition). Lỗi từng phần -> thiếu phần đó."""
    from backend.core.metrics import diagnose_inputs as di
    out: Dict[str, Any] = {"prices": None, "market": None, "frames": None, "errors": []}
    try:
        out["prices"] = di.load_prices(plan.symbols, end)
        out["market"] = di.market_series(out["prices"])
    except Exception as e:      # noqa: BLE001 — chẩn đoán không được làm hỏng kết quả backtest
        out["errors"].append(f"giá thị trường: {e}")
    try:
        out["frames"] = di.strategy_frames(plan.symbols, program.timeframe, end, drop_filled=(program.timeframe == plan.base_frame))
    except Exception as e:      # noqa: BLE001
        out["errors"].append(f"nến khung chiến lược: {e}")
    return out


# ─── Chuỗi ngày + chỉ số ────────────────────────────────────────────────────

def stage_split(start: int, end: int, ratio: float) -> int:
    """Mốc chia train/test (ms): đầu năm dương lịch gần nhất không sau start + ratio·(end - start) (ví dụ 2020-01-02 → 2025-01-01, 0,7 -> 2023-01-01);
    nếu mốc đó không nằm sau start ít nhất 30 ngày thì lấy chính điểm ratio (làm tròn nửa đêm UTC)."""
    point = start + ratio * (end - start)
    year = pd.Timestamp(point, unit="ms").year
    jan1 = _ts(f"{year}-01-01")
    if jan1 - start >= 30 * DAY:
        return jan1
    return int(point // DAY * DAY)


def daily_series(curve: List[Dict[str, float]], start: int, end: int, base_ms: int, capital: float) -> Dict[str, np.ndarray]:
    """Vốn MTM tại từng mốc nửa đêm UTC b_0 = start .. b_N = end (nhãn = giờ ĐÓNG nến): mẫu engine có nhãn = open + độ dài nến chạy (vốn là giá đóng cửa)."""
    bounds = np.arange(start, end + 1, DAY, dtype="int64")
    pts = [(int(c["time"]) + base_ms, float(c["equity"])) for c in curve if c["time"] >= start]
    if not pts:
        eq = np.full(bounds.shape[0], float(capital))
    else:
        t = np.asarray([p[0] for p in pts], dtype="int64")
        v = np.asarray([p[1] for p in pts], dtype="float64")
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
        idx = np.searchsorted(t, bounds, side="right") - 1
        eq = np.where(idx >= 0, v[np.maximum(idx, 0)], float(capital))
    ret = np.zeros(eq.shape[0])
    ret[1:] = eq[1:] / eq[:-1] - 1.0
    return {"times": bounds, "equity": eq, "returns": ret}


def _segments(times: np.ndarray, split: int) -> Dict[str, np.ndarray]:
    n = times.shape[0]
    return {"simulate": np.ones(n, dtype=bool), "train": times <= split, "test": times > split}


def _metric_block(ret: np.ndarray, rows: List[Dict[str, Any]], fees: float) -> Dict[str, Any]:
    """Bộ chỉ số phẳng của Nora (core/metrics/returns: năm = 365 ngày, Sharpe/Sortino/CAGR trên lợi suất ngày MTM; lệnh: win rate, profit factor theo lệnh đóng)."""
    from backend.core.metrics.portfolio import series_metrics
    m = series_metrics(ret[1:] if ret.size else ret, rows)    # bỏ phần tử 0 đứng đầu (không phải ngày giao dịch)
    return {"ret_pct": m["ret_pct"], "mdd_pct": m["mdd_pct"], "sharpe": m["sharpe"], "sortino": m["sortino"], "cagr_pct": m.get("cagr_pct"),
            "calmar": m.get("calmar"), "trades": m["trades"], "win_rate_trades": m["win_rate"], "profit_factor_trades": m["profit_factor"],
            "fees_usd": round(fees, 2)}


def build_metrics(series: Dict[str, np.ndarray], split: int, trade_rows: List[Dict[str, Any]], orders: List[Any],
                  test_run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """metrics.{simulate,train,test}: MỘT bộ chỉ số phẳng mỗi giai đoạn. simulate/train cắt lát đường vốn của lần chạy đầy đủ; test lấy từ `test_run` =
    {series, rows, orders} (lần chạy riêng bắt đầu lại từ vốn đầu tại mốc chia) nếu có, không thì cắt lát."""
    times, ret = series["times"], series["returns"]
    out: Dict[str, Any] = {}
    for name, m in _segments(times, split).items():
        if name == "test" and test_run is not None:
            fees = sum(float(o.fee_usd or 0.0) for o in test_run["orders"])
            out[name] = _metric_block(test_run["series"]["returns"], test_run["rows"], fees)
            continue
        lo = int(times[m][0]) if m.any() else 0
        hi = int(times[m][-1]) if m.any() else 0
        rows = [r for r in trade_rows if lo < r["close_time"] <= hi] if name != "simulate" else trade_rows
        fees = sum(float(o.fee_usd or 0.0) for o in orders if lo < o.order_time <= hi + DAY) if name != "simulate" else sum(float(o.fee_usd or 0.0) for o in orders)
        out[name] = _metric_block(ret[m], rows, fees)
    basis = ("simulate/train cắt lát đường vốn của lần chạy đầy đủ (train bắt đầu tại start nên trùng); test và các năm giai đoạn test tính từ lần chạy lại "
             "[mốc chia, end] bắt đầu từ vốn đầu" if test_run is not None else
             "train/test/yearly cắt lát đường vốn liên tục")
    out["notes"] = {"stage_basis": basis, "annualization_days": ANN_DAYS, "test_fresh_capital": test_run is not None}
    return out


def _year_rows(series: Dict[str, np.ndarray], rows: List[Dict[str, Any]], stage: str, upto: Optional[int] = None) -> List[Dict[str, Any]]:
    times, ret = series["times"], series["returns"]
    years = np.asarray([pd.Timestamp(int(t) - 1, unit="ms").year for t in times])   # nến thuộc năm của giờ mở (nhãn - 1ms)
    keep = np.arange(times.shape[0]) > 0
    if upto is not None:
        keep &= times <= upto
    out = []
    for y in sorted(set(years.tolist())):
        m = (years == y) & keep
        if int(m.sum()) >= MIN_YEAR_DAYS:      # năm chỉ có 1 ngày lợi suất (vd. năm trước start 1 ngày) không có chỉ số -> bỏ
            lo, hi = int(times[m][0]) - DAY, int(times[m][-1])
            blk = _metric_block(np.r_[0.0, ret[m]], [r for r in rows if lo < r["close_time"] <= hi], 0.0)
            out.append({"year": int(y), "stage": stage, "days": int(m.sum()), **{k: blk[k] for k in ("cagr_pct", "sharpe", "mdd_pct", "profit_factor_trades", "calmar")}})
    return out


def yearly_table(series: Dict[str, np.ndarray], split: int, rows: List[Dict[str, Any]], test_series: Optional[Dict[str, np.ndarray]] = None,
                 test_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Bảng theo năm cùng bộ chỉ số phẳng: năm train từ đường vốn đầy đủ; năm test từ lần chạy lại từ vốn đầu (`test_series`) nếu có, không thì cắt lát."""
    if test_series is None:
        times = series["times"]
        years = np.asarray([pd.Timestamp(int(t) - 1, unit="ms").year for t in times])
        out = _year_rows(series, rows, "train")
        for r in out:
            m = (years == r["year"]) & (np.arange(times.shape[0]) > 0)
            r["stage"] = "train" if times[m][-1] <= split else "test"
        return out
    return _year_rows(series, rows, "train", upto=split) + _year_rows(test_series, test_rows or [], "test")


MAX_PLOT_POINTS = 1200     # trần số điểm mỗi chuỗi giai đoạn gửi cho biểu đồ (series.stages); chuỗi ngày đầy đủ vẫn ở series.times/equity/...


def _bench_on(bench: Optional[Dict[str, Any]], times: np.ndarray) -> Optional[np.ndarray]:
    """Đường vốn benchmark nếu cùng lưới ngày với `times`, không thì None (không nội suy / co dãn)."""
    if bench is None:
        return None
    bt = np.asarray(bench["times"], dtype="int64")
    return np.asarray(bench["equity"], dtype="float64") if bt.shape == times.shape and np.array_equal(bt, times) else None


def build_stages(series: Dict[str, np.ndarray], split: int, test_series: Optional[Dict[str, np.ndarray]], bench: Optional[Dict[str, Any]],
                 test_bench: Optional[Dict[str, Any]], max_points: int = MAX_PLOT_POINTS) -> Dict[str, Any]:
    """series.stages = {all, train, test}: mỗi giai đoạn tính trên dữ liệu ngày đầy đủ (equity, pnl, drawdown_pct, ret_pct, benchmark) rồi hạ mẫu CHỈ để vẽ
    (core/metrics/series_stages). Test = lần chạy lại từ vốn đầu tại mốc chia + benchmark chạy lại cùng cửa sổ (không co dãn); thiếu thì None."""
    from backend.core.metrics.series_stages import downsample_stage, stage_block
    times, eq = series["times"], series["equity"]
    label = (bench or {}).get("label")
    beq = _bench_on(bench, times)
    m = times <= split
    out: Dict[str, Any] = {
        "all": stage_block(times, eq, beq, label),
        "train": stage_block(times[m], eq[m], None if beq is None else beq[m], label) if m.any() else None,
        "test": None,
    }
    if test_series is not None:
        tb = _bench_on(test_bench, test_series["times"])
        out["test"] = stage_block(test_series["times"], test_series["equity"], tb, (test_bench or {}).get("label"))
    return {k: downsample_stage(v, max_points) for k, v in out.items()}


def build_result(program, plan, res, eng, a, start: int, end: int, capital: float, data: Dict[str, Any], extra_warnings: List[str],
                 test_res: Optional[Dict[str, Any]] = None, test_start: Optional[int] = None, bench: Optional[Dict[str, Any]] = None,
                 inputs: Optional[Dict[str, Any]] = None, test_bench: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.core.backtest.engine import FRAME_MS
    from backend.core.backtest.run import result_payload
    from backend.core.metrics.trades import rows_from_trade_list
    payload = result_payload(res, start, end)
    trades = payload["trade_list"]
    rows = rows_from_trade_list(trades)
    series = daily_series(res["equity_curve"], start, end, FRAME_MS[plan.base_frame], capital)
    split = stage_split(start, end, float(a.train_ratio))
    test_run = test_series = None
    if test_res is not None:
        test_series = daily_series(test_res["equity_curve"], test_start, end, FRAME_MS[plan.base_frame], capital)
        test_run = {"series": test_series, "rows": rows_from_trade_list(result_payload(test_res, test_start, end)["trade_list"]), "orders": test_res["orders"]}
    metrics = build_metrics(series, split, rows, res["orders"], test_run)
    eq = series["equity"]
    peak = np.maximum.accumulate(eq)
    series_out = {"times": [int(t // 1000) for t in series["times"]], "equity": [round(float(x), 2) for x in eq],
                  "pnl": [round(float(x - capital), 2) for x in eq], "drawdown": [round(float(x), 6) for x in eq / peak - 1.0],
                  "stage_split": int(split // 1000)}
    if test_series is not None:   # lần chạy lại giai đoạn test từ vốn đầu (nhãn đầu = mốc chia)
        teq = test_series["equity"]
        series_out["test"] = {"times": [int(t // 1000) for t in test_series["times"]], "equity": [round(float(x), 2) for x in teq],
                              "drawdown": [round(float(x), 6) for x in teq / np.maximum.accumulate(teq) - 1.0]}
        if test_bench is not None:    # benchmark luôn long chạy lại trên CÙNG cửa sổ test (vốn đầu = vốn đầu giai đoạn), không co dãn đường toàn kỳ
            tbe = test_bench["equity"]
            series_out["test"]["benchmark"] = {"times": [int(t // 1000) for t in test_bench["times"]], "equity": [round(float(x), 2) for x in tbe],
                                               "label": test_bench["label"], "final_equity": round(float(tbe[-1]), 2)}
    opens = eng.open_positions()
    by_symbol = []
    for sym in plan.symbols:
        agg = res["by_symbol"].get(sym, {})
        by_symbol.append({"symbol": sym.split(":")[-1], "pnl_usd": round(agg.get("pnl_usd", 0.0), 2), "trades": int(agg.get("trades", 0)),
                          "wins": int(agg.get("wins", 0)), "fees_usd": round(agg.get("fees_usd", 0.0), 2),
                          "open_pnl_usd": round(sum(o["unrealized_pnl"] for o in opens if o["symbol"] == sym), 2)})
    warns = list(dict.fromkeys(program.warnings + plan.warnings + extra_warnings))
    from backend.core.metrics.diagnose import diagnose_run
    from backend.core.analytics.insights import generate_insights
    fees_total = sum(float(o.fee_usd or 0.0) for o in res["orders"])
    inputs = inputs or {}
    diagnostics = diagnose_run(program, series, trades, metrics, capital, start, end, fees_total=fees_total, open_positions=opens, benchmark=bench,
                               market=inputs.get("market"), prices=inputs.get("prices"), frames=inputs.get("frames"))
    insights = generate_insights(diagnostics, metrics)
    if bench is not None:
        beq = bench["equity"]
        series_out["benchmark"] = {"times": [int(t // 1000) for t in bench["times"]], "equity": [round(float(x), 2) for x in beq], "label": bench["label"],
                                   "final_equity": round(float(beq[-1]), 2)}
    warns += [f"chẩn đoán thiếu dữ liệu: {e}" for e in inputs.get("errors", [])]
    series_out["stages"] = build_stages(series, split, test_series, bench, test_bench)
    if test_series is not None and test_bench is None:
        warns.append("không có benchmark cho giai đoạn Test (chạy lại benchmark cửa sổ test không thành công)")
    from backend.core.analytics.user_alphas import evaluate_checklist, generate_alpha_id
    out = {
        "config": {"symbols": [s.split("@")[0] for s in plan.symbols], "data_symbols": plan.symbols, "start": _iso(start),
                   "end": _iso(end - DAY), "train_ratio": float(a.train_ratio), "initial_capital": capital, "timeframe": program.timeframe,
                   "run_frame": plan.base_frame, "exchange": data["source"], "program": {"name": program.name, "legs": program.legs,
                   "levels": program.levels, "features": program.features, "warmup_bars": program.warmup_bars},
                   "risk": plan.risk, "strategies": [s["id"] for s in plan.strategies], **plan.echo},
        "program_hash": program.code_hash, "data": data, "metrics": metrics, "yearly": yearly_table(series, split, rows, test_series, test_run["rows"] if test_run else None),
        "series": series_out,
        "trades": trades, "positions_open": opens, "by_symbol": by_symbol, "warnings": warns,
        "diagnostics": diagnostics, "insights": insights,
        "final_equity": round(float(eq[-1]), 2) if eq.size else capital,
    }
    out["alpha_id"] = generate_alpha_id(program.code_hash, out["config"])   # cùng mã + cùng cấu hình chạy -> cùng alpha_id (lưu lại = cập nhật)
    out["checklist"] = evaluate_checklist(out)                              # nguồn DUY NHẤT của checklist; giao diện chỉ hiển thị
    return out


def run_job(params=None):
    """Chạy job custom_backtest với `params` (xem docstring module) -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
    out = run_custom(params)
    write_job_result(out)
    return out


def run_custom(params=None):
    """Như run_job nhưng KHÔNG ghi result.json (job edu_precompute chạy nhiều lần trong một tiến trình rồi tự ghi kết quả)."""
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    if not isinstance(a.code, str) or not a.code.strip():
        raise ValueError("thiếu code")
    if not (a.start and a.end):
        raise ValueError("cần start và end (YYYY-MM-DD)")
    if not 0.1 <= float(a.train_ratio) <= 0.95:
        raise ValueError("train_ratio phải trong [0,1; 0,95]")
    from backend.crawl.store import exchange
    source = exchange()
    os.environ.pop("NORA_SHARED_DATA_DIR", None)   # cột py_ tính trong tiến trình, không đi qua kho dùng chung
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("custom_run")
    from backend.core.strategy.pydsl import DslError, compile_code
    from backend.core.strategy.pydsl.profiles import build_plan
    try:
        program = compile_code(a.code)
    except DslError as e:
        raise ValueError(f"Lỗi biên dịch chiến lược: {e}") from None
    names = resolve_symbols(as_list(a.symbols))
    plan = build_plan(program, names, position=a.position or None, run_frame=a.run_frame or None)
    check_data(plan.symbols)
    start, end = _ts(a.start), _ts(a.end) + DAY
    if end <= start:
        raise ValueError("end phải sau start")
    capital = float(a.initial_capital) if a.initial_capital else DEFAULT_CAPITAL
    data, warns = data_info(plan.symbols, start, end, source)
    t0 = time.time()
    print(f"chiến lược {program.name} [{program.code_hash}] | {len(plan.symbols)} tài sản | {_iso(start)} → {_iso(end - DAY)} "
          f"| khung {program.timeframe} chạy {plan.base_frame} | vốn {capital:g}", flush=True)
    res, eng = execute(plan, start, end, capital)
    split = stage_split(start, end, float(a.train_ratio))
    test_res = None    # giai đoạn test = lần chạy riêng bắt đầu từ vốn đầu tại đầu test: cùng chương trình/cấu hình/dữ liệu, warmup như lần chạy chính
    if split < end:
        test_res, _ = execute(plan, split, end, capital)
    bench = None
    try:      # benchmark luôn long qua cùng engine (cache theo cấu hình: chỉ chạy một lần mỗi job/tiến trình)
        bench = run_benchmark(program, a, plan, names, start, end, capital, data)
    except Exception as e:      # noqa: BLE001 — thiếu benchmark thì chẩn đoán market_comparison ghi available=False, không bịa số
        warns = warns + [f"không chạy được benchmark luôn long: {e}"]
    test_bench = None
    if test_res is not None:
        try:      # benchmark của giai đoạn Test: cùng cửa sổ [mốc chia, end], vốn đầu (cache theo cấu hình)
            test_bench = run_benchmark(program, a, plan, names, split, end, capital, data)
        except Exception as e:      # noqa: BLE001 — thiếu thì series.stages.test.benchmark = None, không co dãn benchmark toàn kỳ
            warns = warns + [f"không chạy được benchmark giai đoạn test: {e}"]
    out = build_result(program, plan, res, eng, a, start, end, capital, data, warns, test_res, split, bench=bench, inputs=diagnostic_inputs(plan, program, end),
                       test_bench=test_bench)
    from backend.utils.memwatch import peak_rss_mb
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}   # không tất định -> tách riêng
    sim = out["metrics"]["simulate"]
    print(f"vốn cuối {out['final_equity']} | lãi {sim['ret_pct']}% | MDD {sim['mdd_pct']}% | lệnh đóng {len(out['trades'])} "
          f"mở {len(out['positions_open'])} | {out['meta']['wall_s']}s", flush=True)
    return out
