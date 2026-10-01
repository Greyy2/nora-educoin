"""Payload trang Danh mục (docs/ui_contract.md §3) dựng từ kết quả một job `book_backtest` + giá đóng cửa ngày của benchmark.

Hàm thuần (không I/O trừ `benchmark_daily_closes`) để test được bằng dữ liệu giả:
  build_dashboard(result, bench_closes, period)  -> dict payload (available: True)
Quy ước:
  - Ngày = ngày UTC. NAV ngày = vốn MTM cuối ngày (`daily_nav` của run_book_backtest nếu có, không thì mẫu cuối ngày của equity_curve).
  - Lợi suất ngày r_t = NAV_t / NAV_{t-1} - 1; ngày đầu tính so với vốn ban đầu. Sharpe/Sortino/vol quy năm bằng sqrt(365).
  - Cắt kỳ (period): cutoff = cuối dữ liệu - 1M/3M/1Y (YTD: 31/12 năm trước, ALL: không cắt). Chuỗi gồm các ngày > cutoff;
    NAV gốc của kỳ = NAV cuối ngày cutoff (hoặc vốn ban đầu nếu cutoff trước ngày đầu). KPI kỳ + MDD + drawdown tính trên phần đã cắt
    (đỉnh khởi đầu = NAV gốc). Rolling Sharpe 63 ngày và bảng tháng tính trên TOÀN BỘ lịch sử rồi mới cắt/giữ nguyên.
  - VaR/CVaR: lịch sử 95% trên lợi suất ngày của kỳ; USDT = % × NAV cuối (dương = mức lỗ 1 ngày).
  - Exposure/vị thế mở: tại điểm cuối dữ liệu, từ trade_list (danh nghĩa / NAV cuối); vị thế "mở" = đóng bởi "End of Backtest"
    hoặc close_time > mẫu vốn cuối. Danh nghĩa = `notional` (qty × giá vào TB) nếu có, không thì qty × enter_price.
  - Số liệu theo chiến lược dùng PnL ĐÃ CHỐT (theo ngày đóng lệnh): không có MTM riêng từng chiến lược.
  - `result["positions"]` (feed live/testnet/giả lập; xem feeds.py) = vị thế còn mở cuối dữ liệu, KHÔNG nằm trong trade_list: tính vào exposure/ký quỹ
    (danh nghĩa theo giá mark) và trả lại ở payload["positions"]; backtest đã đóng hết nên rỗng.
"""
import math
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PERIODS = ("1M", "3M", "YTD", "1Y", "ALL")
ANN = 365                     # số ngày quy năm (crypto giao dịch cả tuần)
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


def _sharpe(r: np.ndarray) -> Optional[float]:
    if len(r) < 2:
        return None
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd * math.sqrt(ANN)) if sd > 1e-12 else None


def _sortino(r: np.ndarray) -> Optional[float]:
    if len(r) < 2:
        return None
    dd = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))   # độ lệch xuống so với 0
    return float(np.mean(r) / dd * math.sqrt(ANN)) if dd > 1e-12 else None


# ─── NAV ngày ───────────────────────────────────────────────────────────────
def daily_nav_series(result: Dict[str, Any]) -> pd.Series:
    """NAV cuối mỗi ngày UTC (liên tục theo ngày, ngày thiếu lấy giá trị trước đó). Index = ngày (00:00, không múi giờ)."""
    rows = result.get("daily_nav")
    if rows:
        s = pd.Series([float(r["equity"]) for r in rows], index=pd.to_datetime([r["date"] for r in rows]))
    else:
        curve = result.get("equity_curve") or []
        if not curve:
            return pd.Series(dtype=float)
        end = (result.get("config") or {}).get("end")     # mẫu đúng mốc end (loại trừ) thuộc ngày cuối thật
        t = pd.to_datetime([min(c["time"], end - 1) if end else c["time"] for c in curve], unit="ms")
        s = pd.Series([float(c["equity"]) for c in curve], index=t)
        s = s.groupby(s.index.normalize()).last()
    s = s.sort_index()
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D")).ffill()


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
        from backend.core.strategy.strategy_book import CANDIDATES
        for c in CANDIDATES:
            if c["id"] == sid:
                return c["side"]
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
            "sharpe": _num(_sharpe(r)), "mdd_pct": _num(float(np.min(eq / peak - 1.0)) * 100.0 if len(eq) else 0.0),
            "pnl_30d": _lst(pnl_day.to_numpy()[-SPARK:]),
        })
    return rows


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
    rej = result.get("rejected_for_risk")
    if rej:
        ev.append({"time": int(curve[-1]["time"]) if curve else 0, "level": "info",
                   "text": f"{int(rej)} tín hiệu bị từ chối vì giới hạn rủi ro danh mục"})
    return sorted((e for e in ev if e["time"] >= t_min), key=lambda e: e["time"])


# ─── Dựng payload ───────────────────────────────────────────────────────────
def unavailable(source: str) -> Dict[str, Any]:
    return {"available": False, "reason": f"Chưa kết nối tài khoản {source}: nguồn này sẽ dùng cùng payload khi được nối."}


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
    cagr = ((nav_p[-1] / base_nav) ** (ANN / n) - 1.0) * 100.0 if base_nav > 0 and nav_p[-1] > 0 else None
    sharpe, sortino = _sharpe(ret_p), _sortino(ret_p)
    if n >= 2:
        q = float(np.percentile(ret_p, 5))
        tail = ret_p[ret_p <= q]
        var_pct = max(0.0, -q * 100.0)
        cvar_pct = max(0.0, -float(tail.mean()) * 100.0) if len(tail) else None
    else:
        var_pct = cvar_pct = None
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
        "profit_factor": _num(wins / losses) if losses > 0 else None,
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
        "strategies": _strategy_rows(ids, p_trades, dates, init, base_nav, halted,
                                     {x["strategy"]: x["side"] for x in list(trades) + pos_rows if x.get("side")}),
        "events": _events(result, p_start), "positions": pos_rows,
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
    """Payload dashboard từ FeedSnapshot (feeds.py). Feed giả lập gắn `mock`/`mock_note` ở cấp ngoài và trong `source`."""
    src = snap.source or {}
    p = build_dashboard(snap.result, bench_closes, period, job_id=src.get("job_id"), label=src.get("label"), benchmark=benchmark,
                        source_kind=snap.kind)
    if snap.mock and p.get("available"):
        p["source"]["mock"] = True
        p["mock"], p["mock_note"] = True, snap.mock_note
    return p


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
