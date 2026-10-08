"""Chuỗi cho biểu đồ (P9.5): payload trang Danh mục (dashboard), giải thích tín hiệu một chiến lược trên một mã (signal_explain),
chuỗi theo giai đoạn train/test (series_stages).

Hợp nhất NGUYÊN VĂN từ core/analytics/{dashboard,signal_explain}.py + core/metrics/series_stages.py (xem docs/bmad/p9_review_log.md, mục P9.5).
Đường dẫn cũ là shim. Đổi tên duy nhất: `signal_explain._num` -> `_sx_num` (trùng tên `dashboard._num`, hai hàm khác nghĩa).
"""
import math
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.metrics import metrics as rt
from backend.metrics.metrics import ANN, daily_nav_series


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/analytics/dashboard.py
#
# Payload trang Danh mục (docs/ui_contract.md §3) dựng từ kết quả một job `book_backtest` + giá đóng cửa ngày của benchmark.
#
# Hàm thuần (không I/O trừ `benchmark_daily_closes`) để test được bằng dữ liệu giả:
#   build_dashboard(result, bench_closes, period)  -> dict payload (available: True)
# Quy ước:
#   - Ngày = ngày UTC. NAV ngày = vốn MTM cuối ngày (`daily_nav` của run_book_backtest nếu có, không thì mẫu cuối ngày của equity_curve).
#   - Lợi suất ngày r_t = NAV_t / NAV_{t-1} - 1; ngày đầu tính so với vốn ban đầu. Sharpe/Sortino/vol quy năm bằng sqrt(365).
#   - Cắt kỳ (period): cutoff = cuối dữ liệu - 1M/3M/1Y (YTD: 31/12 năm trước, ALL: không cắt). Chuỗi gồm các ngày > cutoff;
#     NAV gốc của kỳ = NAV cuối ngày cutoff (hoặc vốn ban đầu nếu cutoff trước ngày đầu). KPI kỳ + MDD + drawdown tính trên phần đã cắt
#     (đỉnh khởi đầu = NAV gốc). Rolling Sharpe 63 ngày và bảng tháng tính trên TOÀN BỘ lịch sử rồi mới cắt/giữ nguyên.
#   - VaR/CVaR: lịch sử 95% trên lợi suất ngày của kỳ; USDT = % × NAV cuối (dương = mức lỗ 1 ngày).
#   - Exposure/vị thế mở: tại điểm cuối dữ liệu, từ trade_list (danh nghĩa / NAV cuối); vị thế "mở" = đóng bởi "End of Backtest"
#     hoặc close_time > mẫu vốn cuối. Danh nghĩa = `notional` (qty × giá vào TB) nếu có, không thì qty × enter_price.
#   - Số liệu theo chiến lược dùng PnL ĐÃ CHỐT (theo ngày đóng lệnh): không có MTM riêng từng chiến lược.
#   - `result["positions"]` (tuỳ chọn) = vị thế còn mở cuối dữ liệu, KHÔNG nằm trong trade_list: tính vào exposure/ký quỹ
#     (danh nghĩa theo giá mark) và trả lại ở payload["positions"]; backtest đã đóng hết nên rỗng.
# ══════════════════════════════════════════════════════════════════════════

PERIODS = ("1M", "3M", "YTD", "1Y", "ALL")
ROLL = 63                     # cửa sổ rolling Sharpe
SPARK = 30                    # số điểm sparkline / pnl_30d
DIST_BINS = 20
DAY_MS = 86_400_000
END_REASON = "End of Backtest"
BUDGET_STEPS = ((0.5, "warn"), (0.8, "crit"))   # cảnh báo khi MDD chạm 50% / 80% hạn mức kill switch


# ─── Tiện ích ───────────────────────────────────────────────────────────────
def _num(x, nd=2):
    """float làm tròn; NaN/inf/None -> None (JSON hợp lệ)."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return round(x, nd) + 0.0     # +0.0: đổi -0.0 thành 0.0


def _lst(arr, nd=2) -> List[Optional[float]]:
    return [_num(x, nd) for x in arr]


def _date(ts_ms) -> str:
    return f"{pd.Timestamp(int(ts_ms), unit='ms'):%Y-%m-%d}"


def _cutoff(last: pd.Timestamp, period: str) -> Optional[pd.Timestamp]:
    if period == "ALL":
        return None
    if period == "YTD":
        return pd.Timestamp(year=last.year - 1, month=12, day=31)
    return last - pd.DateOffset(months={"1M": 1, "3M": 3, "1Y": 12}[period])


def _prev_nav(nav: pd.Series, init: float) -> np.ndarray:
    return np.r_[init, nav.to_numpy()[:-1]]


def _nav_at_or_before(nav: pd.Series, day: pd.Timestamp, init: float) -> float:
    s = nav.loc[:day]
    return float(s.iloc[-1]) if len(s) else init


# ─── Benchmark ──────────────────────────────────────────────────────────────
def benchmark_daily_closes(symbol: str, start_ms: int, end_ms: int) -> pd.Series:
    """Giá đóng cửa ngày UTC (khung 24h của dữ liệu cục bộ) trong [start - 10 ngày, end]; Series rỗng nếu thiếu dữ liệu."""
    from backend.db.local_pkl import fetch_candles_df
    df = fetch_candles_df(symbol, "24h", start_ts=int(start_ms) - 10 * DAY_MS, end_ts=int(end_ms), columns=["open_time", "close"],
                          compat=False)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(df["open_time"].to_numpy(), unit="ms").normalize()
    return pd.Series(df["close"].to_numpy(dtype=float), index=idx).groupby(level=0).last()


# ─── Phân bố ────────────────────────────────────────────────────────────────
def _nice_step(span: float, bins: int) -> float:
    raw = span / bins
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def distribution(ret_pct: np.ndarray, var95_pct: Optional[float]) -> Dict[str, Any]:
    """Histogram lợi suất ngày (%) ~DIST_BINS cột, cạnh là bội của bước "đẹp" (0,1/0,2/0,25/0,5...). Có đường VaR95 (âm)."""
    if len(ret_pct) == 0:
        return {"bins": [], "var95_pct": None}
    lo, hi = float(np.min(ret_pct)), float(np.max(ret_pct))
    if var95_pct is not None:
        lo, hi = min(lo, var95_pct), max(hi, var95_pct)
    step = _nice_step(max(hi - lo, 1e-6), DIST_BINS)
    a, b = math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step
    if b - a < step:
        b = a + step
    edges = np.arange(a, b + step / 2, step)
    counts, edges = np.histogram(ret_pct, bins=edges)
    return {"bins": [{"lo": _num(edges[i], 4), "hi": _num(edges[i + 1], 4), "count": int(counts[i])} for i in range(len(counts))],
            "var95_pct": _num(var95_pct, 2)}


# ─── Bảng tháng (toàn lịch sử) ──────────────────────────────────────────────
def monthly_table(nav: pd.Series, init: float) -> Dict[str, Any]:
    ym = nav.groupby([nav.index.year, nav.index.month]).last()
    prev_nav, month_ret = init, {}
    for (y, m), v in ym.items():
        month_ret[(int(y), int(m))] = (float(v) / prev_nav - 1.0) * 100.0 if prev_nav > 0 else None
        prev_nav = float(v)
    years, prev_year_nav = [], init
    for y in sorted({k[0] for k in month_ret}):
        end_nav = float(nav[nav.index.year == y].iloc[-1])
        years.append({"year": y, "months": [_num(month_ret.get((y, m))) for m in range(1, 13)],
                      "total": _num((end_nav / prev_year_nav - 1.0) * 100.0) if prev_year_nav > 0 else None})
        prev_year_nav = end_nav
    return {"years": years}


# ─── Vị thế / exposure / chiến lược ─────────────────────────────────────────
def _notional(t: Dict[str, Any]) -> Optional[float]:
    if t.get("notional") is not None:
        return float(t["notional"])
    if t.get("qty") is not None and t.get("enter_price") is not None:
        return float(t["qty"]) * float(t["enter_price"])
    return None


def _open_trades(trades: List[Dict[str, Any]], t_ref: int) -> List[Dict[str, Any]]:
    return [t for t in trades if (t.get("enter_time") or 0) <= t_ref
            and (t.get("close_reason") == END_REASON or t.get("close_time") is None or t["close_time"] > t_ref)]


def _side_of(sid: str, fallback: Optional[Dict[str, str]] = None) -> Optional[str]:
    try:
        from backend.core.strategy.book import BY_ID
        if sid in BY_ID:
            return BY_ID[sid]["side"]
    except Exception:   # noqa: BLE001  (thiếu thư viện chiến lược: suy từ tên)
        pass
    by_name = "LONG" if sid.endswith("_long") else "SHORT" if sid.endswith("_short") else None
    return by_name or (fallback or {}).get(sid)      # alpha trong kho (id dạng trend_long_perp__SOL): lấy chiều từ lệnh


def _strategy_rows(ids: List[str], trades: List[Dict[str, Any]], dates: pd.DatetimeIndex, init: float, base_nav: float,
                   halted: bool, side_hint: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Mỗi chiến lược: PnL đã chốt trong kỳ, đóng góp (% NAV gốc), Sharpe/MDD trên PnL ngày/vốn ban đầu, 30 ngày gần nhất, trọng số."""
    rows, gross = [], {i: 0.0 for i in ids}
    for t in trades:
        gross[t["strategy"]] = gross.get(t["strategy"], 0.0) + (_notional(t) or 0.0)
    total_gross = sum(gross.values())
    for sid in ids:
        mine = [t for t in trades if t["strategy"] == sid and t.get("close_time") is not None]
        pnl_day = pd.Series(0.0, index=dates)
        for t in mine:
            d = pd.Timestamp(int(t["close_time"]), unit="ms").normalize()
            if d in pnl_day.index:
                pnl_day[d] += float(t["pnl"])
        r = pnl_day.to_numpy() / init
        eq = init + np.cumsum(pnl_day.to_numpy())
        peak = np.maximum.accumulate(np.r_[init, eq])[1:]
        pnl = float(pnl_day.sum())
        rows.append({
            "id": sid, "side": _side_of(sid, side_hint), "status": "halted" if halted else "active",
            "weight_pct": _num(gross[sid] / total_gross * 100.0, 1) if total_gross > 0 else None,
            "pnl": _num(pnl), "contribution_pct": _num(pnl / base_nav * 100.0) if base_nav > 0 else None,
            "sharpe": _num(rt.sharpe(r)), "mdd_pct": _num(float(np.min(eq / peak - 1.0)) * 100.0 if len(eq) else 0.0),
            "pnl_30d": _lst(pnl_day.to_numpy()[-SPARK:]),
        })
    return rows


def _family_stats(trades: List[Dict[str, Any]], dates: pd.DatetimeIndex, init: float, base_nav: float) -> List[Dict[str, Any]]:
    """Thống kê theo HỌ chiến lược (gộp mọi bộ tham số / alpha của cùng chiến lược) trên lệnh đã đóng trong kỳ: bộ số đo theo lệnh chuẩn
    (core/metrics/trades.trade_metrics) + PnL, đóng góp, Sharpe/MDD trên PnL ngày / vốn ban đầu, số tài sản và id con."""
    from backend.metrics.trades import rows_from_trade_list, strategy_family, trade_metrics
    rows = rows_from_trade_list(trades)
    fams: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        fams.setdefault(strategy_family(r["strategy"]), []).append(r)
    out = []
    for fam in sorted(fams):
        mine = fams[fam]
        pnl_day = pd.Series(0.0, index=dates)
        for r in mine:
            d = pd.Timestamp(int(r["close_time"]), unit="ms").normalize()
            if d in pnl_day.index:
                pnl_day[d] += r["pnl_usd"]
        eq = init + np.cumsum(pnl_day.to_numpy())
        peak = np.maximum.accumulate(np.r_[init, eq])[1:]
        tm = trade_metrics(mine)
        out.append({"family": fam, "ids": sorted({r["strategy"] for r in mine}), "symbols": sorted({r["symbol"] for r in mine}),
                    "pnl": _num(tm["pnl_usd"]), "contribution_pct": _num(tm["pnl_usd"] / base_nav * 100.0) if base_nav > 0 else None,
                    "sharpe": _num(rt.sharpe(pnl_day.to_numpy() / init)),
                    "mdd_pct": _num(float(np.min(eq / peak - 1.0)) * 100.0 if len(eq) else 0.0),
                    "trades": {k: (_num(v, 4) if isinstance(v, float) else v) for k, v in tm.items()}})
    return out


def _risk_block_events(result: Dict[str, Any], cfg: Dict[str, Any], curve: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Số LẦN vào lệnh bị chặn bởi giới hạn rủi ro danh mục (các phút liên tiếp của cùng một tracker = một lần).
    Kết quả cũ chỉ có `rejected_for_risk` (đếm phút) nên không đổi được thành số lần: nêu sự việc, không nêu con số."""
    t = int(curve[-1]["time"]) if curve else 0
    risk = cfg.get("risk") or {}
    n = result.get("risk_blocked_attempts")
    bits = []
    if risk.get("max_positions") is not None:
        bits.append(f"tối đa {int(risk['max_positions'])} vị thế")
    if risk.get("max_per_symbol") is not None:
        bits.append(f"{int(risk['max_per_symbol'])} mỗi tài sản")
    if risk.get("max_gross_exposure") is not None:
        bits.append(f"trần exposure {float(risk['max_gross_exposure']):g}× vốn")
    limits = f" ({' / '.join(bits)})" if bits else ""
    if n is not None:
        if int(n) <= 0:
            return []
        return [{"time": t, "level": "info", "text": f"{int(n)} lần vào lệnh bị chặn do giới hạn rủi ro danh mục{limits}"}]
    if result.get("rejected_for_risk"):
        return [{"time": t, "level": "info", "text": f"Có lần vào lệnh bị chặn do giới hạn rủi ro danh mục{limits} (kết quả cũ chưa đếm theo lần)"}]
    return []


def _events(result: Dict[str, Any], t_min: int) -> List[Dict[str, Any]]:
    """Kill switch, MDD chạm 50%/80% hạn mức, lệnh bị từ chối vì rủi ro. Dùng điểm xấu nhất của nến trong equity_curve."""
    cfg = result.get("config") or {}
    init = float(cfg.get("initial_capital") or 0.0)
    budget = float(((cfg.get("risk") or {}).get("kill_switch_dd_pct")) or 0.0)
    ev: List[Dict[str, Any]] = []
    curve = result.get("equity_curve") or []
    if budget > 0 and curve and init > 0:
        peak, pending = init, list(BUDGET_STEPS)
        for c in curve:
            peak = max(peak, float(c["equity"]))
            dd = 1.0 - float(c.get("equity_worst", c["equity"])) / peak
            while pending and dd >= pending[0][0] * budget / 100.0:
                frac, level = pending.pop(0)
                ev.append({"time": int(c["time"]), "level": level,
                           "text": f"Sụt giảm từ đỉnh chạm {frac * 100:.0f}% hạn mức {budget:g}% (hiện {dd * 100:.1f}%)"})
    if result.get("halted_at"):
        ev.append({"time": int(result["halted_at"]), "level": "crit",
                   "text": f"Kill switch kích hoạt (sụt {budget:g}% từ đỉnh): đã đóng mọi vị thế và dừng mở lệnh mới"})
    ev.extend(_risk_block_events(result, cfg, curve))
    return sorted((e for e in ev if e["time"] >= t_min), key=lambda e: e["time"])


# ─── Dựng payload ───────────────────────────────────────────────────────────
def position_rows(raw: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Vị thế đang mở -> hàng payload (làm tròn, lớn nhất trước). Giữ thêm `margin_usd` (ký quỹ) cho tính ký quỹ đã dùng."""
    rows = [{"symbol": r["symbol"], "strategy": r["strategy"], "side": r["side"], "qty": _num(r["qty"], 6),
             "entry_price": _num(r["entry_price"], 4), "mark_price": _num(r["mark_price"], 4), "notional": _num(r["notional"]),
             "unrealized_pnl": _num(r["unrealized_pnl"]), "opened": int(r["opened"]), "margin_usd": _num(r.get("margin_usd"))}
            for r in raw or []]
    return sorted(rows, key=lambda r: -(r["notional"] or 0.0))


def build_dashboard(result: Dict[str, Any], bench_closes: Optional[pd.Series] = None, period: str = "ALL",
                    job_id: Optional[str] = None, label: Optional[str] = None, benchmark: str = "BTC@perp",
                    source_kind: str = "backtest") -> Dict[str, Any]:
    """Payload dashboard từ result của job book_backtest (xem docstring module). `bench_closes`: Series giá đóng cửa ngày (index ngày)."""
    if period not in PERIODS:
        raise ValueError(f"period phải thuộc {PERIODS}")
    nav = daily_nav_series(result)
    cfg = result.get("config") or {}
    init = float(cfg.get("initial_capital") or (nav.iloc[0] if len(nav) else 0.0))
    if len(nav) == 0 or init <= 0:
        return {"available": False, "reason": "Kết quả backtest không có đường vốn."}

    ret_full = nav.to_numpy() / _prev_nav(nav, init) - 1.0
    roll = pd.Series(ret_full, index=nav.index).rolling(ROLL)
    roll_sharpe = (roll.mean() / roll.std() * math.sqrt(ANN)).replace([np.inf, -np.inf], np.nan)

    last = nav.index[-1]
    cut = _cutoff(last, period)
    sel = nav.index > cut if cut is not None else np.ones(len(nav), dtype=bool)
    if not sel.any():
        sel = np.zeros(len(nav), dtype=bool)
        sel[-1] = True
    dates = nav.index[sel]
    base_nav = _nav_at_or_before(nav, dates[0] - pd.Timedelta(days=1), init)
    nav_p = nav.to_numpy()[sel]
    ret_p = ret_full[sel]
    pnl_p = nav_p - np.r_[base_nav, nav_p[:-1]]
    peak = np.maximum.accumulate(np.r_[base_nav, nav_p])[1:]
    dd_p = (nav_p / peak - 1.0) * 100.0
    mdd = float(dd_p.min())
    n = len(dates)

    # benchmark: mua giữ, quy về cùng NAV gốc của kỳ
    bench_p: List[Optional[float]] = [None] * n
    bench_ret = None
    if bench_closes is not None and len(bench_closes):
        ref_day = dates[0] - pd.Timedelta(days=1)
        ref = bench_closes.loc[:ref_day]
        ref_px = float(ref.iloc[-1]) if len(ref) else float(bench_closes.iloc[0])
        px = bench_closes.reindex(dates).ffill()
        px = px.fillna(ref_px)
        bench_arr = base_nav * px.to_numpy() / ref_px
        bench_p = _lst(bench_arr)
        bench_ret = (float(bench_arr[-1]) / base_nav - 1.0) * 100.0

    # KPI
    nav_last = float(nav.iloc[-1])
    prev_day = float(nav.iloc[-2]) if len(nav) > 1 else init
    month_ref = _nav_at_or_before(nav, last.replace(day=1) - pd.Timedelta(days=1), init)
    year_ref = _nav_at_or_before(nav, pd.Timestamp(year=last.year - 1, month=12, day=31), init)
    ret_period = (nav_p[-1] / base_nav - 1.0) * 100.0
    cagr = rt.cagr_pct(ret_p) if base_nav > 0 and nav_p[-1] > 0 else None
    sharpe, sortino = rt.sharpe(ret_p), rt.sortino(ret_p)
    var_pct, cvar_pct = rt.var_cvar_pct(ret_p)
    kpis = {
        "nav": _num(nav_last), "nav_change_day": _num(nav_last - prev_day),
        "nav_change_day_pct": _num((nav_last / prev_day - 1.0) * 100.0) if prev_day > 0 else None,
        "pnl_today": _num(nav_last - prev_day), "pnl_month": _num(nav_last - month_ref), "pnl_year": _num(nav_last - year_ref),
        "ret_period_pct": _num(ret_period), "bench_ret_period_pct": _num(bench_ret),
        "excess_pct": _num(ret_period - bench_ret) if bench_ret is not None else None,
        "sharpe": _num(sharpe), "sortino": _num(sortino),
        "calmar": _num(cagr / abs(mdd)) if cagr is not None and mdd < -1e-9 else None,
        "mdd_pct": _num(mdd), "dd_now_pct": _num(dd_p[-1]),
        "var95_1d": _num(var_pct / 100.0 * nav_last) if var_pct is not None else None,
        "var95_pct": _num(var_pct), "cvar95_1d": _num(cvar_pct / 100.0 * nav_last) if cvar_pct is not None else None,
        "spark_nav": _lst(nav_p[-SPARK:]), "spark_ret": _lst(ret_p[-SPARK:] * 100.0, 3), "spark_dd": _lst(dd_p[-SPARK:]),
    }
    series = {"dates": [f"{d:%Y-%m-%d}" for d in dates], "nav": _lst(nav_p), "bench": bench_p, "drawdown_pct": _lst(dd_p),
              "daily_pnl": _lst(pnl_p), "rolling_sharpe_63": _lst(roll_sharpe.to_numpy()[sel])}

    # Lệnh
    trades = result.get("trade_list") or []
    p_start = int(dates[0].value // 1_000_000)           # đầu ngày đầu tiên của kỳ (ms)
    p_trades = [t for t in trades if t.get("close_time") is not None and t["close_time"] >= p_start]
    wins = sum(t["pnl"] for t in p_trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in p_trades if t["pnl"] < 0)
    t_ref = int(result["equity_curve"][-1]["time"]) if result.get("equity_curve") else int(last.value // 1_000_000) + DAY_MS
    pos_rows = position_rows(result.get("positions"))
    live_open = [{"strategy": r["strategy"], "side": r["side"], "enter_time": r["opened"], "close_time": None, "notional": r["notional"],
                  "margin_usd": r["margin_usd"]} for r in pos_rows]       # vị thế chưa đóng: tính vào exposure/ký quỹ
    open_t = _open_trades(trades, t_ref) + live_open
    notionals = [_notional(t) for t in open_t]
    have_notional = all(x is not None for x in notionals)
    long_n = sum(x for t, x in zip(open_t, notionals) if x and t.get("side") == "LONG")
    short_n = sum(x for t, x in zip(open_t, notionals) if x and t.get("side") == "SHORT")
    margins = [t.get("margin_usd") for t in open_t]
    pct = lambda x: _num(x / nav_last * 100.0, 1) if nav_last > 0 else None
    ids = [s["id"] for s in cfg.get("strategies") or []] or sorted({t["strategy"] for t in trades})
    halted = bool(result.get("halted_at"))
    from backend.metrics.trades import profit_factor_of
    pf_period, pf_note = profit_factor_of(wins, losses, len(p_trades))
    active = np.abs(pnl_p) > 1e-9   # ngày có P&L khác 0 (ngày đứng ngoài thị trường không tính là ngày lỗ)
    risk = {
        "margin_used_pct": pct(sum(margins)) if open_t and all(m is not None for m in margins) else None,
        "exposure_gross_pct": (pct(long_n + short_n) if open_t else 0.0) if have_notional else None,
        "exposure_net_pct": (pct(long_n - short_n) if open_t else 0.0) if have_notional else None,
        "by_market": [{"name": "Crypto perp", "long_pct": pct(long_n) if have_notional else None,
                       "short_pct": pct(short_n) if have_notional else None}],
        "cagr_pct": _num(cagr), "vol_annual_pct": _num(float(np.std(ret_p, ddof=1)) * math.sqrt(ANN) * 100.0) if n >= 2 else None,
        "win_days_pct": _num(float(np.mean(pnl_p[active] > 0)) * 100.0, 1) if active.any() else None,
        "active_days": int(active.sum()),
        "profit_factor": _num(pf_period),
        "open_positions": len(open_t), "strategies_running": 0 if halted else len(ids),
    }

    start_ms, end_ms = cfg.get("start"), cfg.get("end")
    first_d, last_d = nav.index[0], last
    source = {"kind": source_kind, "job_id": job_id,
              "label": label or f"Backtest · {', '.join(ids)} · {len(cfg.get('symbols') or [])} tài sản",
              "start": _date(start_ms) if start_ms else f"{first_d:%Y-%m-%d}",
              "end": _date(int(end_ms) - 1) if end_ms else f"{last_d:%Y-%m-%d}",
              "strategies": ids, "symbols": cfg.get("symbols") or [], "benchmark": benchmark}
    return {
        "available": True, "source": source, "period": period, "kpis": kpis, "series": series,
        "distribution": distribution(ret_p * 100.0, -var_pct if var_pct is not None else None),
        "monthly": monthly_table(nav, init), "risk": risk,
        # lý do một số đo của `risk` là None (giao diện hiện "—" + lý do): khoá riêng để payload `risk` cũ giữ nguyên từng bit
        "risk_notes": {"profit_factor": pf_note,
                       "win_days_pct": None if risk["win_days_pct"] is not None else "không có ngày nào có giao dịch trong kỳ"},
        "strategies": _strategy_rows(ids, p_trades, dates, init, base_nav, halted,
                                     {x["strategy"]: x["side"] for x in list(trades) + pos_rows if x.get("side")}),
        "events": _events(result, p_start), "positions": pos_rows,
        "strategy_stats": _family_stats(p_trades, dates, init, base_nav),
        # bộ số đo chuẩn toàn kỳ chạy (core/metrics/portfolio.portfolio_metrics) — không cắt theo `period`; None với kết quả cũ
        "stats": result.get("stats"),
        "mdd": {"intrabar_pct": result.get("mdd_intrabar_pct", result.get("mdd_pct")), "daily_pct": result.get("mdd_daily_pct")},
    }


def snapshot_benchmark(result: Dict[str, Any], benchmark: str = "BTC@perp") -> Optional[pd.Series]:
    """Giá đóng cửa ngày của benchmark trong cửa sổ của `result`; None nếu thiếu cấu hình/dữ liệu (bench = null)."""
    cfg = result.get("config") or {}
    if not (cfg.get("start") and cfg.get("end")):
        return None
    try:
        return benchmark_daily_closes(benchmark, cfg["start"], cfg["end"])
    except Exception:   # noqa: BLE001  (thiếu dữ liệu benchmark thì vẫn trả dashboard)
        return None


def build_from_snapshot(snap, period: str = "ALL", bench_closes: Optional[pd.Series] = None, benchmark: str = "BTC@perp") -> Dict[str, Any]:
    """Payload dashboard từ FeedSnapshot (feeds.py)."""
    src = snap.source or {}
    return build_dashboard(snap.result, bench_closes, period, job_id=src.get("job_id"), label=src.get("label"), benchmark=benchmark,
                           source_kind=snap.kind)


# ─── Bộ nhớ đệm LRU trong tiến trình ────────────────────────────────────────
class LruCache:
    def __init__(self, size: int = 32):
        self.size, self._d = size, OrderedDict()

    def get(self, key):
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key, value):
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.size:
            self._d.popitem(last=False)

    def clear(self):
        self._d.clear()


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/analytics/signal_explain.py
#
# Giải thích tín hiệu của MỘT chiến lược trên MỘT mã: nến + đường chỉ báo + điểm tín hiệu + từng điều kiện đúng/sai tại mỗi điểm.
#
# Tính bằng đúng đường của engine/bot (live/signals.evaluate -> PortfolioEngine._build_matrix + VectorEvaluator), nên thứ vẽ ra là thứ engine
# "thấy": giá trị khung lớn ở nến t là nến khung ĐÃ ĐÓNG gần nhất; tín hiệu ở nến t xét trên giá đóng của t và vào lệnh ở open nến t+1.
#
# explain(...) -> {
#   "candles": [{t, o, h, l, c}],               # nến khung chạy trong cửa sổ (t = giây, cho thư viện biểu đồ)
#   "overlays": [{name, frame, values}],        # đường cùng thang giá (EMA, dải Keltner/Bollinger, Donchian ...)
#   "oscillators": [{name, frame, values, levels}],   # chỉ báo khác thang (RSI, ADX, ROC, ER ...) + ngưỡng hằng trong điều kiện
#   "signals": [{t, kind: entry|exit, conditions: [{text, left, op, right, ok}], blocks_ok}],
#   "conditions": {"entry": [[text...]], "exit": [[text...]]},   # cây điều kiện dạng chữ (OR các khối AND)
# }
# ══════════════════════════════════════════════════════════════════════════

FRAME_NAME = {"1m": "1 phút", "5m": "5 phút", "15m": "15 phút", "1h": "1 giờ", "4h": "4 giờ", "24h": "1 ngày"}
OP_TEXT = {">": ">", "<": "<", ">=": "≥", "<=": "≤", "==": "=", "!=": "≠"}


def _sx_num(v: float) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    a = abs(v)
    return f"{v:.6g}" if a < 1000 else f"{v:,.2f}"


COLUMN_NAME = [("ema_", "EMA {}"), ("sma_", "SMA {}"), ("rsi_", "RSI {}"), ("adx_", "ADX {}"), ("roc_", "ROC {} (%)"),
               ("er_", "ER {} (độ thẳng xu hướng)"), ("dch_", "Đỉnh Donchian {}"), ("dcl_", "Đáy Donchian {}"), ("bbu_", "Bollinger trên {}"),
               ("bbl_", "Bollinger dưới {}"), ("natr_", "ATR% {}"), ("atr_", "ATR {}")]
PRICE = {"close": "Giá đóng", "open": "Giá mở", "high": "Giá cao", "low": "Giá thấp"}


def column_name(col: str) -> str:
    if col in PRICE:
        return PRICE[col]
    for pre, fmt in COLUMN_NAME:
        if col.startswith(pre):
            return fmt.format(col[len(pre):].replace("_", " / "))
    return col


def label(node: Any) -> str:
    """Tên dễ đọc của một toán hạng trong cây điều kiện."""
    if isinstance(node, bool) or node is None:
        return "?"
    if isinstance(node, (int, float)):
        return _sx_num(float(node))
    if not isinstance(node, dict):
        return "?"
    t = node.get("type")
    if t == "calculate":
        mul = node.get("multiply", 1.0)
        s = f"({label(node.get('number_1'))} {node.get('logic')} {label(node.get('number_2'))})"
        return s if mul in (1, 1.0) else f"{s} × {_sx_num(float(mul))}"
    if t in ("min", "max"):
        return f"{t}({', '.join(label(x) for x in node.get('numbers', []))})"
    if "frame" in node and "column" in node:
        s = f"{column_name(node['column'])} [{node['frame']}]"
        lag = int(node.get("index", 0) or 0)
        if lag:
            s += f" (trước {lag} nến)"
        for key, sign in (("add", "+"), ("subtract", "−")):
            if key in node:
                s += f" {sign} {label(node[key])}"
        if "divide" in node:
            s += f" ÷ {label(node['divide'])}"
        return s
    return "?"


def _leaves(tree: Any) -> List[Tuple[int, List]]:
    """[(chỉ số khối AND, bộ ba)] của cây OR-of-AND."""
    out = []
    if isinstance(tree, list):
        for b, block in enumerate(tree):
            if isinstance(block, list):
                out += [(b, t) for t in block if isinstance(t, list) and len(t) == 3]
    return out


def _operands(tree: Any) -> List[Dict[str, Any]]:
    """Các toán hạng KHÔNG phải hằng số (để vẽ), không trùng."""
    seen, out = set(), []
    for _, (a, _, b) in _leaves(tree):
        for x in (a, b):
            if isinstance(x, dict):
                k = label(x)
                if k not in seen:
                    seen.add(k)
                    out.append(x)
    return out


def _frame_of(node: Dict[str, Any]) -> Optional[str]:
    if "frame" in node:
        return node["frame"]
    for k in ("number_1", "number_2"):
        if isinstance(node.get(k), dict):
            f = _frame_of(node[k])
            if f:
                return f
    return None


def _rising(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=bool)
    return np.flatnonzero(x & ~np.r_[False, x[:-1]])


def explain(symbol: str, strategy: Dict[str, Any], base_frame: str, frames: Dict[str, Any], start_ms: int, end_ms: int,
            max_signals: int = 400) -> Dict[str, Any]:
    from backend.live import signals as ls
    v = ls.evaluate(symbol, [strategy], frames, base_frame, with_vec=True)
    vec, t = v["vec"], v["t"]
    e = v["entries"][0]
    tr = e["tracker"]
    win = np.flatnonzero((t >= int(start_ms)) & (t <= int(end_ms)))
    if not len(win):
        raise ValueError("không có nến nào trong cửa sổ đã chọn (dữ liệu chưa phủ khoảng này?)")
    lo, hi = int(win[0]), int(win[-1]) + 1
    close = v["close"][lo:hi]
    sec = (t[lo:hi] // 1000).tolist()

    def series(node) -> np.ndarray:
        return vec.value(node)[lo:hi]

    def clean(a: np.ndarray) -> List[Optional[float]]:
        return [float(x) if np.isfinite(x) else None for x in a]

    overlays, oscillators = [], []
    trees = {"entry": tr.match_tree, "exit": tr.stop_tree}
    levels: Dict[str, List[float]] = {}
    for _, (a, _, b) in _leaves(tr.match_tree) + _leaves(tr.stop_tree):   # ngưỡng hằng đi kèm chỉ báo -> vạch ngang trên khung dao động
        for x, y in ((a, b), (b, a)):
            if isinstance(x, dict) and isinstance(y, (int, float)) and not isinstance(y, bool):
                levels.setdefault(label(x), []).append(float(y))
    seen = set()
    for node in _operands(tr.match_tree) + _operands(tr.stop_tree):
        name = label(node)
        plain = "frame" in node and not any(k in node for k in ("add", "subtract", "divide"))
        if name in seen or "(trước " in name or (plain and node["column"] in PRICE and node["frame"] == base_frame):
            continue                                        # bản trễ 1 nến (điểm cắt) / giá của chính nến đã vẽ: chỉ hiện ở điều kiện
        seen.add(name)
        vals = series(node)
        ok = np.isfinite(vals) & np.isfinite(close) & (close != 0)
        ratio = np.nanmedian(vals[ok] / close[ok]) if ok.any() else np.nan
        item = {"name": name, "frame": _frame_of(node), "values": clean(vals)}
        if np.isfinite(ratio) and 0.5 <= ratio <= 2.0:
            overlays.append(item)
        else:
            oscillators.append({**item, "levels": sorted(set(levels.get(name, [])))})

    sigs = []
    for kind, arr in (("entry", e["match"]), ("exit", e["stop"])):
        tree = trees[kind]
        if not tree:
            continue
        leaves = _leaves(tree)
        vals = [(b, trip, vec.value(trip[0]), vec.value(trip[2]), vec._triplet(trip)) for b, trip in leaves]
        for i in _rising(np.asarray(arr)[lo:hi])[:max_signals]:
            k = lo + int(i)
            conds = [{"block": b, "text": f"{label(trip[0])} {OP_TEXT.get(trip[1], trip[1])} {label(trip[2])}",
                      "left": float(L[k]) if np.isfinite(L[k]) else None, "op": trip[1],
                      "right": float(R[k]) if np.isfinite(R[k]) else None, "ok": bool(M[k])} for b, trip, L, R, M in vals]
            blocks = sorted({c["block"] for c in conds})
            sigs.append({"t": int(t[k] // 1000), "kind": kind, "price": float(v["close"][k]), "conditions": conds,
                         "blocks_ok": [b for b in blocks if all(c["ok"] for c in conds if c["block"] == b)]})
    sigs.sort(key=lambda s: s["t"])
    text = {kind: [[f"{label(a)} {OP_TEXT.get(op, op)} {label(b)}" for a, op, b in block] for block in (tree or []) if isinstance(block, list)]
            for kind, tree in trees.items()}
    return {
        "symbol": symbol, "timeframe": base_frame, "frame_names": FRAME_NAME,
        "candles": [{"t": s, "o": float(o), "h": float(h), "l": float(l_), "c": float(c)}
                    for s, o, h, l_, c in zip(sec, v["open"][lo:hi], v["high"][lo:hi], v["low"][lo:hi], close)],
        "overlays": overlays, "oscillators": oscillators, "signals": sigs, "conditions": text,
        "position": {k: strategy.get("position", {}).get(k) for k in ("exit_unit", "atr_frame", "atr_period", "stop_loss_rate", "take_profit_rate",
                                                                       "trailing_stop", "trailing_activation_pct", "timeout", "cooldown",
                                                                       "leverage", "dca_steps", "dca_multipliers")},
        "note": "Tín hiệu ở nến t xét trên giá ĐÓNG của nến t; lệnh vào ở giá mở nến t+1. Chỉ báo khung lớn = nến khung đã đóng gần nhất.",
    }


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/metrics/series_stages.py
#
# Chuỗi theo giai đoạn (train / test / toàn kỳ) cho biểu đồ, TÍNH HẾT ở backend trên dữ liệu ngày đầy đủ (docs/bmad/p8_education_user_alpha.md §3.7).
#
# `stage_block` dựng một giai đoạn từ đường vốn ngày (+ benchmark cùng lưới): equity, pnl (so với điểm đầu giai đoạn), drawdown_pct (<= 0, đỉnh chạy từ đầu
# giai đoạn), ret_pct (lợi suất ngày, phần tử 0 = 0 vì không phải ngày giao dịch), benchmark {equity, pnl}.
# `downsample_stage` CHỈ để vẽ: gom nhóm `step` điểm liên tiếp (điểm 0 đứng riêng) rồi lấy từ các số ĐÃ TÍNH: nhãn thời gian/equity/pnl = điểm cuối nhóm,
# drawdown = đáy nhóm, ret_pct = lãi kép các ngày trong nhóm (đúng bằng vốn cuối nhóm / vốn cuối nhóm trước − 1). Có thể gọi lại nhiều lần (khối ghi
# `downsample` = {step, source_points, points, rule}); giao diện không tính lại số nào, chỉ vẽ.
# ══════════════════════════════════════════════════════════════════════════

RULE = "nhãn/equity/pnl = điểm cuối nhóm; drawdown_pct = đáy nhóm; ret_pct = lãi kép trong nhóm; điểm đầu đứng riêng"


def _r(a, d: int) -> List[float]:
    return [round(float(x), d) for x in a]


def stage_block(times_ms, equity, bench_equity=None, bench_label: Optional[str] = None) -> Dict[str, Any]:
    """times_ms: nhãn ms (nửa đêm UTC), trả về nhãn giây. bench_equity: cùng lưới thời gian hoặc None."""
    t = np.asarray(times_ms, dtype="int64")
    eq = np.asarray(equity, dtype="float64")
    peak = np.maximum.accumulate(eq)
    ret = np.zeros(eq.shape[0])
    ret[1:] = (eq[1:] / eq[:-1] - 1.0) * 100.0
    out: Dict[str, Any] = {
        "times": [int(x // 1000) for x in t], "equity": _r(eq, 2), "pnl": _r(eq - eq[0], 2),
        "drawdown_pct": _r((eq / peak - 1.0) * 100.0, 6), "ret_pct": _r(ret, 6), "benchmark": None,
        "downsample": {"step": 1, "source_points": int(t.shape[0]), "points": int(t.shape[0]), "rule": RULE},
    }
    if bench_equity is not None:
        be = np.asarray(bench_equity, dtype="float64")
        out["benchmark"] = {"equity": _r(be, 2), "pnl": _r(be - be[0], 2), "label": bench_label}
    return out


def _groups(n: int, step: int) -> List[slice]:
    return [slice(0, 1)] + [slice(i, min(n, i + step)) for i in range(1, n, step)]


def downsample_stage(block: Optional[Dict[str, Any]], max_points: int) -> Optional[Dict[str, Any]]:
    if not block:
        return block
    n = len(block["times"])
    prev = block.get("downsample") or {"step": 1, "source_points": n}
    if n <= max_points or n < 3:
        return block
    step = int(np.ceil((n - 1) / (max_points - 1)))
    gs = _groups(n, step)
    last = [g.stop - 1 for g in gs]

    def at_last(v: List[float]) -> List[float]:
        return [v[i] for i in last]

    ret = block["ret_pct"]
    out = dict(block)
    out["times"] = at_last(block["times"])
    out["equity"] = at_last(block["equity"])
    out["pnl"] = at_last(block["pnl"])
    out["drawdown_pct"] = [min(block["drawdown_pct"][g]) for g in gs]
    out["ret_pct"] = [round((float(np.prod(1.0 + np.asarray(ret[g]) / 100.0)) - 1.0) * 100.0, 6) if g.start else 0.0 for g in gs]
    b = block.get("benchmark")
    if b:
        out["benchmark"] = {**b, "equity": at_last(b["equity"]), "pnl": at_last(b["pnl"])}
    out["downsample"] = {"step": int(prev["step"]) * step, "source_points": int(prev["source_points"]), "points": len(gs), "rule": RULE}
    return out
