"""Các job (P9.6): backtest sổ (run_book_backtest), WFA (run_book_wfa), báo cáo regime (run_regime_report), backtest tạm của người dùng (run_custom_backtest), dựng mẫu Education (run_edu_precompute) + mặc định dùng chung (run_defaults).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8). Backtest tick DEX (tick_run) nằm ở optimize/search/evaluate.py (là mã engine: ENGINE_FILES băm file đó).
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import io
import itertools
import json
import shutil
import subprocess
import time
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.carlo.carlo import measure_turnover, vertical_exposure
from backend.core.params import DAY_MS as DAY, DEFAULT_CAPITAL, MINUTE_MS as MINUTE
from backend.metrics.charts import iso_date
from backend.metrics.metrics import ANN, portfolio_metrics
from backend.optimize.book import build as bsb
from backend.optimize.funnel.storage import atomic_write_json
from backend.optimize.process.process import NORA_DIR
from backend.optimize.process.workers import pool_map_safe
from backend.optimize.search.evaluate import _ts, BacktestJob, load_items, make_engine, run, SharedExporter, WARMUP
from backend.wfa.wfa import PortfolioWfaConfig, aggregate_folds, evaluate_gate, generate_folds, is_score, select_best
from backend.regime import regime as rg
from backend.regime.regime import by_regime
from backend.crawl.store import as_list, json_default, options, write_job_result


# ══════════════════════════════════════════════════════════════════════════
# Mặc định MỘT chỗ của backtest chiến lược Python (custom_run, edu_precompute, GET /api/studio/custom/defaults): rổ + cửa sổ ngày + vốn đều lấy từ kho dữ liệu OKX.
#
# Module nhẹ (không đặt biến môi trường của job như custom_run) để API và job cùng import được.
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_TRAIN_RATIO = 0.7


def default_universe() -> List[str]:
    """Rổ mặc định = mọi tài sản perp CEX có trong kho dữ liệu của sàn đang dùng (OKX), tên cơ sở đã sắp xếp."""
    from backend.crawl.store import list_assets
    return sorted({a["symbol"].split("@")[0] for a in list_assets() if a["venue"] == "cex" and a.get("instrument") == "perp"})


def default_window() -> Tuple[str, str]:
    """(start, end) 'YYYY-MM-DD' = phần dữ liệu chung của cả rổ: sau nến đầu muộn nhất 1 ngày, trước nến cuối sớm nhất 1 ngày."""
    from backend.crawl.store import read_manifest
    firsts, lasts = [], []
    for n in default_universe():
        m = read_manifest(f"{n}@perp") or {}
        if m.get("start_ts") and m.get("end_ts"):
            firsts.append(int(m["start_ts"]))
            lasts.append(int(m["end_ts"]))
    if not firsts:
        raise ValueError("Kho dữ liệu chưa có manifest (start_ts/end_ts) cho rổ mặc định")
    return iso_date(max(firsts) + DAY), iso_date(min(lasts) - DAY)


def run_defaults() -> Dict[str, object]:
    start, end = default_window()
    return {"symbols": [f"{n}@perp" for n in default_universe()], "start": start, "end": end,
            "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": DEFAULT_CAPITAL}


# ══════════════════════════════════════════════════════════════════════════
# Job custom_backtest (POST /api/studio/custom/backtest -> optimize/process/process.py -> run_job): chiến lược Python (DSL SimpleAlgorithm) chạy trên PortfolioEngine.
#
# Một engine duy nhất: code được biên dịch (core/signal.compile_code, KHÔNG exec), đăng ký thành cột kernel `py_<hash12>_*`, rồi cấu hình thực thi mặc định của Nora
# (core/backtest.build_plan: perp OKX, định cỡ theo rủi ro, SL 3×ATR) dựng chiến lược dict cho PortfolioEngine y như chiến lược lõi.
# Kết quả ghi $NORA_JOB_DIR/result.json (docs/bmad/p7_python_strategies.md §6). Dữ liệu = kho OKX (crawl/store).
#
# Tham số (run_job params; mặc định ở DEFAULTS):
#   code            mã Python `class X(SimpleAlgorithm)` (bắt buộc)
#   symbols         danh sách tài sản (BTC hoặc BTC@perp); trống = cả rổ perp OKX có trong kho dữ liệu (default_universe)
#   start, end      YYYY-MM-DD UTC (ngày kết thúc tính cả ngày)
#   train_ratio     tỉ lệ giai đoạn train (mặc định 0,7): mốc chia = đầu năm dương lịch gần nhất không sau start + ratio × (end - start)
#   initial_capital vốn ban đầu (mặc định 10000)
#   position        ghi đè tham số vị thế: khoá theo params.builder.POSITION_KEYS
#   run_frame       khung chạy (nến mô phỏng); trống = 1m
# ══════════════════════════════════════════════════════════════════════════

MIN_YEAR_DAYS = 2                    # bảng yearly chỉ giữ năm có >= 2 ngày lợi suất (Sharpe/độ lệch cần >= 2)
MAX_DAYS = 4000                      # trần ngày của BacktestEngine.MAX_BACKTEST_DAYS (1100) được nâng trong tiến trình job: cho phép chạy nhiều năm
CUSTOM_BACKTEST_DEFAULTS = {"code": "", "symbols": None, "start": "", "end": "", "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": None, "position": None, "run_frame": ""}


# ─── Chọn tài sản + kiểm dữ liệu ────────────────────────────────────────────

def resolve_symbols(symbols: Optional[List[str]]) -> List[str]:
    """Tên cơ sở (BTC, ETH, ...) của rổ: `symbols` nếu có, không thì default_universe()."""
    from backend.crawl.store import base_name
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
            warns.append(f"{s}: dữ liệu bắt đầu {iso_date(int(m['start_ts']))}, sau start {iso_date(start)} — giữ tiền mặt tới nến đầu có dữ liệu")
        if m.get("end_ts") and end - DAY > int(m["end_ts"]):
            warns.append(f"{s}: dữ liệu kết thúc {iso_date(int(m['end_ts']))}, trước end {iso_date(end - DAY)}")
    return {"source": source, "sha256_1m": sha}, warns


# ─── Chạy engine ────────────────────────────────────────────────────────────

def execute(plan, start: int, end: int, initial_capital: float, close_at_end: bool = False):
    """PortfolioEngine cho một Plan (core/backtest.build_plan) -> (get_results(), engine). Chương trình phải đã được compile_code (đăng ký)."""
    from backend.core.backtest import BacktestEngine, PortfolioEngine, RiskConfig
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
    from backend.core.backtest import FRAME_MS
    from backend.core.params import resolve_costs
    from backend.alpha.compile import compile_code
    from backend.core.backtest import build_plan
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
    """Bộ chỉ số phẳng của Nora (metrics/metrics: năm = 365 ngày, Sharpe/Sortino/CAGR trên lợi suất ngày MTM; lệnh: win rate, profit factor theo lệnh đóng)."""
    from backend.metrics.metrics import series_metrics
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
    out["notes"] = {"stage_basis": basis, "annualization_days": ANN, "test_fresh_capital": test_run is not None}
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
    (metrics/charts.stage_block). Test = lần chạy lại từ vốn đầu tại mốc chia + benchmark chạy lại cùng cửa sổ (không co dãn); thiếu thì None."""
    from backend.metrics.charts import downsample_stage, stage_block
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
    from backend.core.backtest import FRAME_MS
    from backend.optimize.search.evaluate import result_payload
    from backend.metrics.trades import rows_from_trade_list
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
    from backend.metrics.trades import diagnose_run
    from backend.metrics.charts import generate_insights
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
    from backend.optimize.book.registry import evaluate_checklist, generate_alpha_id
    out = {
        "config": {"symbols": [s.split("@")[0] for s in plan.symbols], "data_symbols": plan.symbols, "start": iso_date(start),
                   "end": iso_date(end - DAY), "train_ratio": float(a.train_ratio), "initial_capital": capital, "timeframe": program.timeframe,
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


def run_custom_backtest(params=None):
    """Chạy job custom_backtest với `params` (xem docstring module) -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
    out = run_custom(params)
    write_job_result(out)
    return out


def run_custom(params=None):
    """Như run_job nhưng KHÔNG ghi result.json (job edu_precompute chạy nhiều lần trong một tiến trình rồi tự ghi kết quả)."""
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
    start, end = _ts(a.start), _ts(a.end) + DAY
    if end <= start:
        raise ValueError("end phải sau start")
    capital = float(a.initial_capital) if a.initial_capital else DEFAULT_CAPITAL
    data, warns = data_info(plan.symbols, start, end, source)
    t0 = time.time()
    print(f"chiến lược {program.name} [{program.code_hash}] | {len(plan.symbols)} tài sản | {iso_date(start)} → {iso_date(end - DAY)} "
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
    from backend.optimize.process.workers import peak_rss_mb
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}   # không tất định -> tách riêng
    sim = out["metrics"]["simulate"]
    print(f"vốn cuối {out['final_equity']} | lãi {sim['ret_pct']}% | MDD {sim['mdd_pct']}% | lệnh đóng {len(out['trades'])} "
          f"mở {len(out['positions_open'])} | {out['meta']['wall_s']}s", flush=True)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Job edu_precompute (B7): chạy backtest THẬT cho 50 mẫu chiến lược giáo dục và lưu kết quả để trang Education hiển thị ngay.
#
# Mỗi mẫu của samples.json (crawl/store.alpha_education_samples(); xuất từ frontend/src/components/education/educationSamples.js bằng test/scripts/export_edu_samples.py)
# chạy qua ĐÚNG đường custom_run.run_custom (cùng engine, benchmark luôn long, chẩn đoán, nhận xét như POST /api/studio/custom/backtest) với cấu hình mặc định của Nora
# và `position` CỦA MẪU (nếu có).
# Kết quả: crawl/store.education_results_dir()/<key>.json = {key, name, ..., program_hash, config, data (nguồn + sha256), git_commit, generated_at, metrics, diagnostics,
# insights, series (hạ mẫu), explain, warnings} và index.json cùng thư mục.
#
# Mặc định: cửa sổ = phần dữ liệu chung của cả rổ trong kho (run_defaults.default_window: ngày đầy đủ đầu tiên sau nến đầu muộn nhất → ngày đầy đủ cuối cùng trước nến cuối sớm nhất),
# vốn 10000, train_ratio 0,7, rổ = mọi tài sản perp OKX có trong kho (run_defaults.default_universe).
#
# Tham số (run_job params): only (list key; trống = tất cả), start, end, train_ratio, initial_capital.
# ══════════════════════════════════════════════════════════════════════════

EDU_PRECOMPUTE_DEFAULTS = {"only": None, "start": None, "end": None, "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": DEFAULT_CAPITAL}
MAX_POINTS = 400


def results_dir() -> str:
    from backend.crawl.store import education_results_dir
    return education_results_dir()


def load_samples(path: Optional[str] = None) -> List[Dict[str, Any]]:
    from backend.crawl.store import alpha_education_samples
    with open(path or alpha_education_samples(), encoding="utf-8") as fh:
        return json.load(fh)


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=NORA_DIR, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:      # noqa: BLE001
        return None


def downsample_series(series: Dict[str, Any], max_points: int = MAX_POINTS) -> Dict[str, Any]:
    """Hạ mẫu các chuỗi ngày (cùng chỉ số cho times/equity/pnl/drawdown/benchmark) còn <= max_points điểm, luôn giữ điểm đầu và cuối."""
    def pick(n: int) -> List[int]:
        return list(range(n)) if n <= max_points else sorted(set(np.linspace(0, n - 1, max_points).round().astype(int).tolist()))

    def cut(block: Dict[str, Any]) -> Dict[str, Any]:
        n = len(block.get("times", []))
        idx = pick(n)
        out = dict(block)
        for k, v in block.items():
            if isinstance(v, list) and len(v) == n:
                out[k] = [v[i] for i in idx]
        return out

    from backend.metrics.charts import downsample_stage
    out = cut({k: v for k, v in series.items() if k not in ("test", "benchmark", "stages")})
    for k in ("test", "benchmark"):
        if k in series:
            blk = dict(series[k])
            nested = blk.pop("benchmark", None)       # series.test.benchmark (benchmark chạy lại trên cửa sổ test) cắt cùng lưới riêng
            out[k] = cut(blk)
            if nested is not None:
                out[k]["benchmark"] = cut(nested)
    if "stages" in series:      # chuỗi giai đoạn ĐÃ tính ở backend: chỉ gom nhóm để vẽ (series_stages.downsample_stage), không tính lại
        out["stages"] = {k: downsample_stage(v, max_points) for k, v in series["stages"].items()}
    out["downsampled_from"] = len(series.get("times", []))
    return out


def _clear_data_caches() -> None:
    from backend.core.backtest import data_cache_clear
    from backend.crawl.store import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()


def _run_one(sample: Dict[str, Any], a, custom_run) -> Dict[str, Any]:
    """Chạy một mẫu qua custom_run.run_custom; trả dict kết quả."""
    params = {"code": sample["code"], "start": a.start, "end": a.end, "train_ratio": float(a.train_ratio), "initial_capital": float(a.initial_capital)}
    if sample.get("position"):
        params["position"] = sample["position"]
    _clear_data_caches()
    try:
        return custom_run.run_custom(params)
    finally:
        _clear_data_caches()


def run_edu_precompute(params=None):
    import warnings
    warnings.filterwarnings("ignore")
    a = options(EDU_PRECOMPUTE_DEFAULTS, params)
    if not (a.start and a.end):
        a.start, a.end = default_window()
    from backend.optimize.process import tasks as custom_run
    from backend.alpha.compile import compile_code, explain_program
    samples = load_samples()
    only = set(a.only or [])
    unknown = sorted(only - {s["key"] for s in samples})
    if unknown:
        raise ValueError(f"mẫu không tồn tại: {unknown}")
    if only:
        samples = [s for s in samples if s["key"] in only]
    out_dir = results_dir()
    os.makedirs(out_dir, exist_ok=True)
    commit, t0 = git_commit(), time.time()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index: List[Dict[str, Any]] = []
    print(f"edu_precompute: {len(samples)} mẫu | {a.start} → {a.end} | commit {commit}", flush=True)
    for n, s in enumerate(samples, 1):
        key, ts = s["key"], time.time()
        item: Dict[str, Any] = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"),
                                "file": f"{key}.json"}
        try:
            out = _run_one(s, a, custom_run)
            prog = compile_code(s["code"], register=False)
            sim = out["metrics"]["simulate"]
            rec = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"), "summary": s.get("summary"),
                   "program_hash": out["program_hash"], "config": out["config"], "data": out["data"], "git_commit": commit,
                   "generated_at": generated_at, "metrics": out["metrics"], "yearly": out["yearly"], "diagnostics": out["diagnostics"], "insights": out["insights"],
                   "series": downsample_series(out["series"]), "by_symbol": out["by_symbol"], "final_equity": out["final_equity"], "warnings": out["warnings"],
                   "trades_closed": len(out["trades"]), "positions_open": len(out["positions_open"]), "explain": explain_program(prog, position=s.get("position"))}
            atomic_write_json(os.path.join(out_dir, f"{key}.json"), rec, indent=1, clean=False)
            item.update({"status": "ok", "program_hash": out["program_hash"], "final_equity": out["final_equity"], "cagr_pct": sim.get("cagr_pct"),
                         "mdd_pct": sim.get("mdd_pct"), "sharpe": sim.get("sharpe"), "trades": len(out["trades"]) + len(out["positions_open"]),
                         "insights": [i["id"] for i in out["insights"]], "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: OK vốn cuối {out['final_equity']} | {item['wall_s']}s", flush=True)
        except Exception as e:      # noqa: BLE001 — một mẫu lỗi không dừng cả job; ghi rõ lỗi vào index
            item.update({"status": "failed", "error": f"{type(e).__name__}: {e}", "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: LỖI {item['error']}", flush=True)
        index.append(item)
    ok = sum(1 for i in index if i["status"] == "ok")
    full = not only
    if not full:      # chạy một phần: giữ các dòng cũ của mẫu khác trong index
        try:
            with open(os.path.join(out_dir, "index.json"), encoding="utf-8") as fh:
                old = {i["key"]: i for i in json.load(fh).get("items", [])}
        except (OSError, ValueError):
            old = {}
        old.update({i["key"]: i for i in index})
        index_items = list(old.values())
    else:
        index_items = index
    wall = round(time.time() - t0, 1)
    idx = {"generated_at": generated_at, "git_commit": commit, "start": a.start, "end": a.end, "train_ratio": float(a.train_ratio), "initial_capital": float(a.initial_capital),
           "count": len(index_items), "ok": sum(1 for i in index_items if i.get("status") == "ok"), "failed": sum(1 for i in index_items if i.get("status") == "failed"),
           "last_run": {"samples": len(index), "ok": ok, "failed": len(index) - ok, "wall_s": wall}, "items": index_items}
    atomic_write_json(os.path.join(out_dir, "index.json"), idx, indent=1, clean=False)
    result = {"samples": len(index), "ok": ok, "failed": len(index) - ok, "wall_s": wall, "git_commit": commit, "items": index}
    print(f"edu_precompute xong: {ok}/{len(index)} mẫu OK, {wall}s", flush=True)
    write_job_result(result)
    return result


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

BOOK_BACKTEST_DEFAULTS = {"book": "", "strategies": None, "symbols": "", "start": "", "end": "", "risk_per_trade": None, "stop_fill": "level", "regime": False, "timeframe": "1m", "out": "",
            "data": "candle", "latency_ms": None, "gas_usd": None, "capital": None}


def run_book_backtest(params=None):
    """Chạy job backtest với `params` (xem docstring module) -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
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
        start, end = (_ts(a.start) if a.start else None), (_ts(a.end) + DAY if a.end else None)
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
        start = _ts(a.start) if a.start else data_start
        end = _ts(a.end) + DAY if a.end else data_end
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
# Job WFA danh mục (POST /api/studio/book/wfa -> optimize/process/process.py -> run_job): Walk-Forward cả sổ + Monte Carlo lợi suất ngày MTM.
#
# Mỗi fold: IS chọn lại cấu hình của TỪNG chiến lược (top-K ứng viên), OOS chạy CẢ sổ chung vốn (kill switch bật, SL "level" và
# "extreme"). Sau đó nối lợi suất ngày OOS (extreme) -> Monte Carlo 1 năm. Gate: xem hằng số đầu wfa/wfa.py.
#
# Nguồn ứng viên (chọn một tham số):
#   report       thư mục lần dựng sổ (optimize/book/build.py): top-N cấu hình mỗi chiến lược theo điểm dev1; mặc định chỉ chiến lược ĐẠT
#                (include_rejected=True: cả loại)
#   candidates   "id1,id2" hoặc [id...]: lấy mẫu n cấu hình mỗi chiến lược như optimize.book.configs(seed)
#   strategies   [{"id": ..., "configs": [{...}, ...]}] do người dùng chọn; DÙNG ĐÚNG các cấu hình này
# Cửa sổ mặc định: dev1_end -> dev2_end; start/end (YYYY-MM-DD) ghi đè. Rủi ro/lệnh: report["book"] hoặc 0,5% (risk_per_trade ghi đè).
# regime "learn": mỗi fold học bảng regime ↔ chiến lược trên dữ liệu trước test (mở rộng từ đầu dev1 tới hết train của fold;
# regime/regime.learn_map) rồi áp lên OOS; "off" (mặc định): không lọc.
# Kết quả: <data>/wfa/<thời điểm>/report.json + $NORA_JOB_DIR/result.json.
# ══════════════════════════════════════════════════════════════════════════

# ── Đặt TRƯỚC mọi import numpy/backend: tiến trình con kế thừa qua fork ──────
# ─────────────────────────────────────────────────────────────────────────────


BOOK_WFA_DEFAULTS = {"report": "", "include_rejected": False, "candidates": "", "strategies": None, "symbols": "", "n": 3, "seed": 7,
            "start": "", "end": "", "train_days": 120, "test_days": 30, "step_days": None, "min_is_trades": 10, "sims": 10_000,
            "mc_seed": 1, "timeframe": "1m", "regime": "off", "risk_per_trade": None, "workers": "auto", "per_worker_mb": None, "resume": "", "max_configs": 200_000,
            "force_large": False}


def load_report(report_dir):
    """(stage_a, report) từ thư mục lần chạy build_strategy_book."""
    with open(os.path.join(report_dir, "stage_a.json"), encoding="utf-8") as fh:
        stage_a = json.load(fh)
    with open(os.path.join(report_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    return stage_a, report


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
    from backend.optimize.book.build import BY_ID
    by_id = BY_ID
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": bsb.configs(by_id[i], n, seed)} for i in ids]


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


# ══════════════════════════════════════════════════════════════════════════
# Phần CHẠY engine của WFA danh mục (job + pool + kho kết quả + run_portfolio_wfa).
# Chuyển lên tầng optimize vì dùng optimize/search/evaluate (BacktestJob, make_engine, SharedExporter), optimize/process/workers và
# optimize/funnel/storage; wfa/wfa.py giữ phần thuần (fold, điểm IS, gate, tổng hợp).
# ══════════════════════════════════════════════════════════════════════════

# Seam cho test: thay bằng bản chạy tuần tự trong tiến trình để ghi lại job.
_pool_map = pool_map_safe


# ── Job & worker ────────────────────────────────────────────────────────────
def run_wfa_job(job):
    import contextlib
    import io
    from backend.optimize.process.workers import peak_rss_mb, rss_anon_mb
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
        from backend.regime.regime import engine_by_regime
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
    return bsb.strip_metrics(m, ("_daily_start", "by_regime", "shock", "turnover"))


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
    from backend.regime.regime import OBSERVE
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if chosen[fi]:
            keys.append(fi)
            lo = fold["train_start_ts"] if learn_from is None else min(int(learn_from), fold["train_start_ts"])
            jobs.append(BacktestJob(chosen[fi], (lo, fold["train_end_ts"]), "level", is_risk, rpt, symbols, shared_dir,
                                    base_frame, {cid: OBSERVE for cid, _ in chosen[fi]}))
    return keys, jobs


# ── Chạy ────────────────────────────────────────────────────────────────────
def run_portfolio_wfa(candidates, symbols, start_ts, end_ts, cfg, risk, risk_per_trade_pct, workers, shared_root,
                      store=None, progress=None, base_frame="1m", regime="off", regime_learn_from=None) -> Dict[str, Any]:
    """candidates = [{"id": candidate_id, "configs": [params...]}]; cfg: PortfolioWfaConfig hoặc dict.
    regime: "off" (mặc định, như trước) | "learn": mỗi fold học bảng regime ↔ chiến lược trên TRAIN (regime/regime.learn_map) rồi áp lên test;
    regime_learn_from (ms, tuỳ chọn): học trên cửa sổ mở rộng [regime_learn_from, train_end] thay vì chỉ train của fold.
    risk: dict RiskConfig dùng cho OOS (kill switch BẬT); IS tự tắt kill switch. Trả dict kết quả (xem aggregate_folds).
    store/progress (tuỳ chọn, backend/optimize): ghi từng kết quả job vào kho + bỏ qua job đã có (--resume) + tiến độ."""
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
        from backend.regime.regime import learn_map
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


def run_book_wfa(params=None):
    """Chạy job WFA với `params` (xem docstring module) -> báo cáo (cũng ghi report.json + $NORA_JOB_DIR/result.json)."""
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

    per_worker_mb = a.per_worker_mb or bsb.PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "validate_book")
    check_memory_gate(workers * per_worker_mb, f"validate_book --workers {workers}")

    risk, rpt, report = RISK, BASE_RISK_PER_TRADE_PCT, None
    if a.report:
        stage_a, report = load_report(a.report)
        cands = candidates_from_report(stage_a, report, a.n, a.include_rejected)
        risk = report.get("risk") or RISK
        rpt = ((report.get("book") or {}).get("risk_per_trade_pct")) or rpt
        w = {k: _ts(v) for k, v in report["windows"].items()}
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
    start = _ts(a.start) if a.start else w["dev1_end"]
    end = _ts(a.end) if a.end else w["dev2_end"]

    from backend.optimize.process.process import Progress, graceful_sigterm
    from backend.optimize.funnel.storage import ResultsStore

    # Ước lượng + trần số job TRƯỚC khi chạy: IS = fold × tổng số cấu hình; OOS = 2 × fold
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
            # Hiệu chỉnh: chạy 1 job IS đầu (1 worker, ghi vào kho như job thường) -> ước lượng thời gian
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
            if os.path.isdir(shared_dir):  # chạy xong thành công: dọn (lỗi thì không tới đây -> còn nguyên để gỡ lỗi)
                shutil.rmtree(shared_dir, ignore_errors=True)
            path = os.path.join(run_dir, "report.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=json_default)
            print_summary(res)
            print(f"thời gian {res['source']['wall_s']:.0f}s | báo cáo: {path}")
            store.flush()
            progress.finish("done")
            write_job_result({**res, "report_path": path})  # chỉ khi chạy như job API (env NORA_JOB_DIR)
    finally:
        store.close()   # flush lô ghi cuối (cả khi SIGTERM/ngoại lệ) -> --resume dùng được
    return res


# ══════════════════════════════════════════════════════════════════════════
# Báo cáo độ chính xác regime + so sánh backtest bật/tắt regime (job API `regime_report`, POST /api/studio/regime/report).
#
# Khung chạy (timeframe, mặc định 15m): nhãn + backtest trên nến khung chạy (như mọi job); "minutes" = số nến, độ trễ tính theo phút.
# Phần A — nhãn regime (regime/regime.series, đúng đường dữ liệu của engine) trên dữ liệu thật từng tài sản:
#   tỷ trọng thời gian, số đợt, thời lượng trung bình, số lần đổi / 30 ngày; lợi suất 24h TIẾP THEO theo nhãn (lấy mẫu mỗi giờ):
#   trung bình, trung vị, % dương, |lợi suất| trung bình -> nhãn xu hướng phải có lợi suất tiếp theo cùng chiều, RANGE có biên độ nhỏ.
# Phần B — sự kiện thẳng đứng (định nghĩa SAU sự việc, chỉ để chấm điểm): giờ h có lợi suất 24h tới <= -event_pct (sập) / >= +event_pct
#   (tăng dựng). Gộp giờ liên tiếp thành đợt. Phát hiện = nhãn CRASH/SURGE xuất hiện trong [đầu đợt, đầu đợt + 24h):
#   tỷ lệ phát hiện, độ trễ (phút), % quãng giá đã đi trước khi phát hiện. Cảnh báo: mỗi đợt CRASH/SURGE (nhãn) -> lợi suất 24h sau khi bật
#   (cầu chì đúng khi giá tiếp tục đi ngược vị thế bị cắt).
# Phần C — sổ mọi chiến lược lõi (presets) chạy 2 lần trên cùng dữ liệu: tắt / bật regime. Kết quả tổng + theo chiến lược, và lãi/lỗ theo
#   (chiến lược, regime lúc vào lệnh) của lần tắt -> kiểm chứng bảng REGIME_MAP (chiến lược nào lỗ ở regime nào).
# ══════════════════════════════════════════════════════════════════════════

REGIME_REPORT_DEFAULTS = {"symbols": "", "start": "", "end": "", "event_pct": 12.0, "backtest": True, "timeframe": "15m"}
HOUR = 3_600_000


def _episodes(mask: np.ndarray):
    """[(đầu, cuối+1)] các đoạn True liên tiếp."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def label_stats(s: Dict[str, np.ndarray], start: int) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    n = len(t)
    days = (t[-1] - t[0]) / DAY if n > 1 else 0.0
    # mẫu mỗi giờ: lợi suất 24h tới (phút cuối cùng <= t + 24h)
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    ok = (t[fwd_idx] >= t[hourly] + DAY - HOUR)
    h, fi = hourly[ok], fwd_idx[ok]
    fwd = (close[fi] / close[h] - 1.0) * 100.0
    out: Dict[str, Any] = {"minutes": int(n), "days": round(days, 1), "states": {}}
    switches = int((np.diff(lab.astype(np.int16)) != 0).sum())
    out["switches_per_30d"] = round(switches / days * 30, 2) if days else None
    for code, name in enumerate(rg.NAMES):
        m = lab == code
        if not m.any():
            continue
        eps = _episodes(m)
        dur = [(t[e - 1] - t[b]) / HOUR + 1 / 60 for b, e in eps]
        r = fwd[lab[h] == code]
        out["states"][name] = {
            "share_pct": round(100 * m.mean(), 2), "episodes": len(eps), "avg_hours": round(float(np.mean(dur)), 1),
            "fwd24_n": int(r.size),
            "fwd24_mean_pct": round(float(r.mean()), 3) if r.size else None,
            "fwd24_median_pct": round(float(np.median(r)), 3) if r.size else None,
            "fwd24_up_pct": round(float((r > 0).mean() * 100), 1) if r.size else None,
            "fwd24_abs_pct": round(float(np.abs(r).mean()), 3) if r.size else None,
        }
    return out


def shock_stats(s: Dict[str, np.ndarray], start: int, event_pct: float) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    fwd = (close[fwd_idx] / close[hourly] - 1.0) * 100.0
    out = {}
    for name, code, sign in (("CRASH", rg.CRASH, -1), ("SURGE", rg.SURGE, 1)):
        ev = sign * fwd >= event_pct
        rows = []
        for b, e in _episodes(ev):
            i0 = hourly[b]
            i1 = int(np.searchsorted(t, t[i0] + DAY, side="right"))
            hit = np.flatnonzero(lab[i0:i1] == code)
            already = None
            # cực trị của đợt trong 24h sau đầu đợt (đáy với sập, đỉnh với tăng)
            seg = close[i0:i1]
            ext = int(np.argmin(seg) if sign < 0 else np.argmax(seg))
            total = seg[ext] / close[i0] - 1.0
            lag = None
            if hit.size:
                k = int(hit[0])
                lag = int((t[i0 + k] - t[i0]) // MINUTE)
                already = round(100 * (close[i0 + k] / close[i0] - 1.0) / total, 1) if total else None
            rows.append({"start": int(t[i0]), "move_pct": round(100 * total, 2), "detected": bool(hit.size), "lag_min": lag,
                         "move_done_pct": already})
        det = [r for r in rows if r["detected"]]
        alarms = []
        for b, e in _episodes(lab == code):
            j = int(np.searchsorted(t, t[b] + DAY, side="right")) - 1
            if t[j] >= t[b] + DAY - HOUR:
                alarms.append((close[j] / close[b] - 1.0) * 100.0)
        alarms = np.asarray(alarms)
        out[name] = {
            "events": len(rows), "detected": len(det),
            "recall_pct": round(100 * len(det) / len(rows), 1) if rows else None,
            "median_lag_min": int(np.median([r["lag_min"] for r in det])) if det else None,
            "median_move_done_pct": float(np.median([r["move_done_pct"] for r in det if r["move_done_pct"] is not None]))
            if det else None,
            "alarms": int(alarms.size),
            # cầu chì đúng khi sau khi bật giá TIẾP TỤC cùng chiều sốc (vị thế ngược chiều bị cắt là tránh lỗ thêm)
            "alarm_continuation_pct": round(float((sign * alarms > 0).mean() * 100), 1) if alarms.size else None,
            "alarm_fwd24_mean_pct": round(float(alarms.mean()), 3) if alarms.size else None,
            "worst_events": sorted(rows, key=lambda r: sign * -r["move_pct"])[:5],
        }
    return out


def _book_items():
    from backend.optimize.book.build import load_presets
    from backend.core.params import BASE_RISK_PER_TRADE_PCT
    from backend.optimize.book.build import CANDIDATES
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


def run_regime_report(params=None):
    warnings.filterwarnings("ignore")
    a = options(REGIME_REPORT_DEFAULTS, params)
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("regime_report")
    from backend.core.params import REGIME_MAP
    from backend.optimize.book.build import perp_symbols
    from backend.optimize.search.evaluate import WARMUP, run
    from backend.crawl.store import read_manifest
    symbols = [s if "@" in s else f"{s}@perp" for s in as_list(a.symbols)] or perp_symbols()
    from backend.crawl.store import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    start = _ts(a.start) if a.start else max(int(m["start_ts"]) for m in ms) + WARMUP
    end = _ts(a.end) + DAY if a.end else min(int(m["end_ts"]) for m in ms)
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


def _pool_states(per_symbol: Dict[str, Any]) -> Dict[str, Any]:
    """Gộp các tài sản: tỷ trọng theo phút, lợi suất 24h tới theo trọng số số mẫu."""
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


# ══════════════════════════════════════════════════════════════════════════
# Chẩn đoán: phần NẠP dữ liệu (market_series thuần nằm ở metrics/trades.py)
#
# Đầu vào dữ liệu thật cho chẩn đoán (metrics/trades.diagnose_run): giá ngày của từng tài sản, chuỗi thị trường (BTC hoặc chỉ số rổ), nến khung chiến lược.
#
# Mọi thứ đọc từ CHÍNH nguồn dữ liệu của lần chạy (env NORA_EXCHANGE / NORA_LOCAL_DATA_ROOT đã đặt trước khi chạy) qua CandleLoader — cùng kho với engine.
# Nhãn thời gian = giờ ĐÓNG nến (open_time + độ dài khung) như đường vốn ngày của custom_run.
# ══════════════════════════════════════════════════════════════════════════

_FRAME_ORDER = ("24h", "4h", "1h", "15m", "5m", "1m")


def _clean(df: pd.DataFrame, drop_filled: bool = True) -> pd.DataFrame:
    from backend.core.backtest import BacktestEngine
    out = BacktestEngine._prepare_candles(df)
    if drop_filled and "is_filled" in out.columns:
        out = out[pd.to_numeric(out["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
    return out


def daily_close(symbol: str, end: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(nhãn đóng ngày ms, giá đóng cửa ngày) của tài sản từ đầu lịch sử tới `end`; khung 24h nếu có, không thì gộp từ khung nhỏ hơn. None nếu không có dữ liệu."""
    from backend.crawl.store import CandleLoader
    for frame in _FRAME_ORDER:
        try:
            df = _clean(CandleLoader(symbol, frame=frame, use_cache=True).load_data(0, end))
        except FileNotFoundError:
            continue
        if df.empty:
            continue
        t, c = df["open_time"].to_numpy(dtype="int64"), df["close"].to_numpy(dtype="float64")
        if frame != "24h":
            day = t // DAY * DAY
            keep = np.r_[day[1:] != day[:-1], True]            # nến cuối của mỗi ngày
            t, c = day[keep], c[keep]
        return t + DAY, c
    return None


def load_prices(symbols: List[str], end: int) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """{ký hiệu dữ liệu (BTC, BTC@perp, ...): (nhãn ngày, giá đóng)} cho các tài sản đọc được."""
    out = {}
    for s in symbols:
        r = daily_close(s, end)
        if r is not None:
            out[str(s).split(":")[-1]] = r
    return out


def strategy_frames(symbols: List[str], timeframe: str, end: int, drop_filled: bool = False) -> Dict[str, pd.DataFrame]:
    """Nến khung chiến lược của từng tài sản từ đầu lịch sử tới `end` (chỉ báo như engine: gốc cố định); tài sản không đọc được bị bỏ qua.
    drop_filled=True khi khung chiến lược = khung chạy (engine bỏ nến điền ở khung chạy)."""
    from backend.crawl.store import CandleLoader
    out = {}
    for s in symbols:
        try:
            df = _clean(CandleLoader(s, frame=timeframe, use_cache=True).load_data(0, end), drop_filled)
        except FileNotFoundError:
            continue
        if not df.empty:
            out[str(s).split(":")[-1]] = df
    return out
