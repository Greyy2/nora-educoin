"""Bộ chỉ số Nora (P9.5): số đo trên chuỗi lợi suất NGÀY (returns) + bộ số đo chuẩn của MỘT lần chạy (portfolio), một công thức chuẩn, năm = 365 ngày.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.5).
Thứ tự trong file: returns, portfolio, METRIC_DEFS (từ điển chỉ số cho giao diện). Chỉ import `metrics/trades.py` (cùng tầng) — không import ngoài core.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backend.carlo.carlo import MC_RUIN_THRESHOLD_PCT
from backend.metrics.trades import exposure_metrics, strategy_correlation, trade_metrics, trade_rows, trade_stats


# ══════════════════════════════════════════════════════════════════════════
# Số đo trên chuỗi lợi suất NGÀY (vốn MTM cuối ngày UTC): lợi nhuận, quy năm, biến động, Sharpe/Sortino/Calmar, sụt giảm + thời gian
# hồi phục, VaR/CVaR, thống kê chuỗi (cho DSR).
#
# Quy ước (một nguồn duy nhất cho mọi tầng: backtest, sổ, phễu, WFA, trang Danh mục):
#   - năm = 365 ngày (crypto giao dịch cả tuần); lãi suất phi rủi ro = 0;
#   - Sharpe = mean(r) / std(r, ddof=1) × √365; Sortino = mean(r) / √mean(min(r, 0)²) × √365 (độ lệch xuống so với 0);
#     chuỗi < 2 ngày hoặc độ lệch ≈ 0 -> None (không xác định), KHÔNG phải 0;
#   - CAGR = (Π(1 + r))^(365 / số ngày) − 1; Calmar = CAGR / MDD theo ngày;
#   - MDD theo ngày dùng giá đóng ngày (nhẹ hơn MDD trong nến của engine — xem metrics/portfolio.py);
#   - VaR/CVaR 95% = phân vị 5% lịch sử của r ngày (số dương = mức lỗ 1 ngày) và trung bình phần đuôi tệ hơn nó.
# ══════════════════════════════════════════════════════════════════════════

ANN = 365   # số ngày quy năm (crypto giao dịch cả tuần)


def _arr(r) -> np.ndarray:
    return np.asarray(r, dtype=float)


def curve_frame(curve_rows) -> pd.DataFrame:
    """DataFrame của đường vốn (list dict time/equity/equity_worst) dựng theo CỘT — cùng giá trị/dtype với pd.DataFrame(curve_rows)
    nhưng nhanh hơn nhiều (đường vốn theo giờ có hàng chục nghìn điểm, tính lại cho mọi alpha)."""
    if not curve_rows:
        return pd.DataFrame()
    try:
        return pd.DataFrame({k: [r[k] for r in curve_rows] for k in curve_rows[0]})
    except KeyError:                                  # dòng thiếu khoá -> để pandas tự điền NaN
        return pd.DataFrame(curve_rows)


def daily_returns_from_curve(curve_rows, start_ts, initial_capital, end_ts=None):
    """Lợi suất ngày MTM (vốn đóng cửa mỗi ngày UTC) từ đường vốn `curve_rows` (list dict time/equity/...),
    chỉ lấy điểm có time >= start_ts, nối từ vốn ban đầu. Dùng chung cho danh mục, WFA và Monte Carlo ngày.
    `end_ts` (mốc end LOẠI TRỪ của cửa sổ, nếu biết): mẫu đúng mốc đó thuộc ngày cuối thật (end - 1ms) như daily_nav / daily_nav_series,
    không tạo thêm một "ngày" 00:00 chỉ có đúng một mẫu."""
    curve = curve_frame(curve_rows)
    if curve.empty:
        return []
    curve = curve[curve["time"] >= start_ts]
    if curve.empty:
        return []
    t = curve["time"] if end_ts is None else np.minimum(curve["time"].to_numpy(), end_ts - 1)
    s = pd.Series(curve["equity"].to_numpy(), index=pd.to_datetime(t, unit="ms"))
    daily = s.resample("1D").last().ffill()
    daily = pd.concat([pd.Series([initial_capital], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()
    return [float(x) for x in daily.to_numpy()]


# ─── Rủi ro điều chỉnh lợi nhuận ────────────────────────────────────────────
def sharpe(r) -> Optional[float]:
    r = _arr(r)
    if len(r) < 2:
        return None
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd * math.sqrt(ANN)) if sd > 1e-12 else None


def sortino(r) -> Optional[float]:
    r = _arr(r)
    if len(r) < 2:
        return None
    dd = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))   # độ lệch xuống so với 0
    return float(np.mean(r) / dd * math.sqrt(ANN)) if dd > 1e-12 else None


def total_return_pct(r) -> float:
    r = _arr(r)
    return float((np.prod(1.0 + r) - 1.0) * 100.0) if r.size else 0.0


def calmar(cagr: Optional[float], mdd_pct: float) -> Optional[float]:
    """Calmar = CAGR% / |MDD%| (cùng đơn vị %); None khi chưa có CAGR hoặc không có sụt giảm (MDD ~ 0). Định nghĩa duy nhất."""
    return cagr / abs(mdd_pct) if cagr is not None and abs(mdd_pct) > 1e-9 else None


def cagr_pct(r) -> Optional[float]:
    """Lợi nhuận quy năm. Vốn về 0 hoặc âm -> -100; chuỗi rỗng -> None."""
    r = _arr(r)
    if r.size == 0:
        return None
    growth = float(np.prod(1.0 + r))
    if growth <= 0:
        return -100.0
    return float((growth ** (ANN / r.size) - 1.0) * 100.0)


def vol_ann_pct(r) -> Optional[float]:
    r = _arr(r)
    return float(np.std(r, ddof=1) * math.sqrt(ANN) * 100.0) if r.size >= 2 else None


def var_cvar_pct(r, q: float = 5.0) -> Tuple[Optional[float], Optional[float]]:
    """(VaR, CVaR) lịch sử ở mức (100 − q)%: phần trăm lỗ 1 ngày (số dương; 0 nếu phân vị không âm)."""
    r = _arr(r)
    if r.size < 2:
        return None, None
    cut = float(np.percentile(r, q))
    tail = r[r <= cut]
    return max(0.0, -cut * 100.0), (max(0.0, -float(tail.mean()) * 100.0) if tail.size else None)


# ─── Sụt giảm ───────────────────────────────────────────────────────────────
def equity_mdd_pct(daily) -> float:
    """MDD (%) của vốn nối từ chuỗi r ngày (giá đóng ngày); vốn không xuống dưới 0."""
    d = _arr(daily)
    if d.size == 0:
        return 0.0
    eq = np.cumprod(np.maximum(0.0, 1.0 + d))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(((peak - eq) / peak).max() * 100.0)


def equity_series_summary(values: Sequence[float]) -> Dict[str, Any]:
    """Số đo của một đường vốn theo NẾN (bot live): {bars, start, last, mdd_pct, mdd_note}. MDD = sụt giảm lớn nhất từ đỉnh vốn (đóng nến);
    < 2 điểm hoặc đỉnh <= 0 -> mdd_pct None + lý do (không phải 0 giả)."""
    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    out: Dict[str, Any] = {"bars": int(v.size), "start": float(v[0]) if v.size else None, "last": float(v[-1]) if v.size else None,
                           "mdd_pct": None, "mdd_note": None}
    if v.size < 2:
        out["mdd_note"] = "cần ít nhất hai nến để đo MDD"
        return out
    peak = np.maximum.accumulate(v)
    if not peak.max() > 0:
        out["mdd_note"] = "vốn không dương, không tính được MDD"
        return out
    ok = peak > 0
    out["mdd_pct"] = float(((peak[ok] - v[ok]) / peak[ok]).max() * 100.0)
    return out


def pnl_since_start(start: Optional[float], last: Optional[float]) -> Dict[str, Any]:
    """Lãi/lỗ từ đầu: USD và % so với vốn đầu đường vốn. Thiếu đầu/cuối hoặc vốn đầu <= 0 -> None + lý do."""
    if start is None or last is None:
        return {"pnl_usd": None, "pnl_pct": None, "pnl_note": "chưa có điểm vốn nào từ bot"}
    if not start > 0:
        return {"pnl_usd": float(last - start), "pnl_pct": None, "pnl_note": "vốn đầu kỳ <= 0, không tính được %"}
    return {"pnl_usd": float(last - start), "pnl_pct": float((last / start - 1.0) * 100.0), "pnl_note": None}


def drawdown_stats(daily) -> Dict[str, Any]:
    """MDD theo ngày + thời gian: `max_dd_days` = đợt nằm dưới đỉnh dài nhất (ngày), `recovery_days` = số ngày từ đáy của đợt MDD
    tới khi lấy lại đỉnh (None nếu chưa hồi phục), `ulcer_index` = √mean(dd%²) (độ sâu × độ dài sụt giảm)."""
    d = _arr(daily)
    if d.size == 0:
        return {"mdd_daily_pct": 0.0, "max_dd_days": 0, "recovery_days": 0, "ulcer_index": 0.0}
    eq = np.cumprod(np.maximum(0.0, 1.0 + d))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = (peak - eq) / peak                                  # >= 0
    trough = int(np.argmax(dd))
    longest = cur = 0
    for under in dd > 1e-12:
        cur = cur + 1 if under else 0
        longest = max(longest, cur)
    rec = None
    if dd[trough] <= 1e-12:
        rec = 0
    else:
        after = np.nonzero(eq[trough:] >= peak[trough] - 1e-12)[0]
        rec = int(after[0]) if after.size else None
    return {"mdd_daily_pct": float(dd[trough] * 100.0), "max_dd_days": int(longest), "recovery_days": rec,
            "ulcer_index": float(np.sqrt(np.mean((dd * 100.0) ** 2)))}


# ─── Bộ số đo chuỗi ngày ────────────────────────────────────────────────────
def daily_stats(daily: Sequence[float]) -> Dict[str, Any]:
    """Sharpe/độ lệch/kurtosis thô theo NGÀY của chuỗi lợi suất ngày (dùng cho DSR). Chuỗi < 3 ngày hoặc std = 0 -> sr = 0."""
    d = _arr(daily)
    n = int(d.size)
    if n < 3:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    sd = float(d.std(ddof=1))
    if not sd > 0:
        return {"sr_daily": 0.0, "skew": 0.0, "kurt": 3.0, "n_days": n}
    mu = float(d.mean())
    z = (d - mu) / float(d.std(ddof=0))
    return {"sr_daily": mu / sd, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean()), "n_days": n}


def return_metrics(daily) -> Dict[str, Any]:
    """Mọi số đo của chuỗi r ngày (chưa làm tròn trừ khi ghi chú): lợi nhuận, CAGR, biến động, Sharpe, Sortino, Calmar, VaR/CVaR,
    sụt giảm + thời gian, độ lệch/độ nhọn, tỉ lệ ngày lãi, ngày tốt/xấu nhất."""
    d = _arr(daily)
    ddm = drawdown_stats(d)
    cg = cagr_pct(d)
    var, cvar = var_cvar_pct(d)
    st = daily_stats(d)
    active = d[np.abs(d) > 1e-12]
    return {
        "ret_pct": total_return_pct(d), "cagr_pct": cg, "vol_ann_pct": vol_ann_pct(d),
        "sharpe": sharpe(d), "sortino": sortino(d),
        "calmar": calmar(cg, ddm["mdd_daily_pct"]),
        **ddm, "var95_pct": var, "cvar95_pct": cvar, "skew": st["skew"], "kurt": st["kurt"],
        "days": int(d.size), "win_days_pct": float((active > 0).mean() * 100.0) if active.size else None,
        "best_day_pct": float(d.max() * 100.0) if d.size else None, "worst_day_pct": float(d.min() * 100.0) if d.size else None,
    }


# ─── NAV ────────────────────────────────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════════
# Bộ số đo chuẩn của MỘT lần chạy — mọi tầng (backtest, dựng sổ, WFA, phễu, trang Danh mục) dùng chung.
#
# portfolio_metrics(res, start_ts)  từ PortfolioEngine.get_results() (bỏ phần warmup trước start_ts):
#     khoá phẳng (định dạng cũ, gate/bảng đọc): ret_pct, mdd_pct (= MDD TRONG NẾN, khắt nhất), sharpe, trades, win_pct, symbols_positive,
#     by_symbol, by_strategy, fees_usd, funding_usd, rejected_*, halted_at, daily
#     + mdd_intrabar_pct, mdd_daily_pct, mdd_basis="intrabar", cagr_pct, calmar
#     + stats = {returns: metrics/returns.return_metrics, trades: metrics/trades.trade_metrics, exposure, correlation}
# series_metrics(daily, trades)     từ chuỗi ngày nối + lệnh (OOS của WFA/phễu): mdd_pct = MDD THEO NGÀY (mdd_basis="daily").
#
# Hai kiểu MDD: trong nến = đỉnh vốn MTM so với vốn ở giá XẤU NHẤT của nến (engine ghi equity_worst mỗi mẫu) — chỉ có khi có đường vốn engine;
# theo ngày = trên vốn đóng ngày. Trong nến >= theo ngày. Gate dùng `mdd_pct` của nguồn tương ứng; UI hiện cả hai.
# ══════════════════════════════════════════════════════════════════════════

def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _round_tree(obj, nd=4):
    if isinstance(obj, float):
        return round(obj, nd) if np.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _round_tree(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_tree(v, nd) for v in obj]
    return obj


def curve_mdd_pct(curve_rows, start_ts, initial_capital) -> float:
    """MDD TRONG NẾN (%) từ đường vốn engine: đỉnh vốn MTM so với min(vốn MTM, vốn ở giá xấu nhất của nến), từ start_ts."""
    curve = curve_frame(curve_rows)
    if curve.empty:
        return 0.0
    curve = curve[curve["time"] >= start_ts]
    eq = curve["equity"].to_numpy()
    worst = curve["equity_worst"].to_numpy() if "equity_worst" in curve else eq
    peak = np.maximum.accumulate(np.r_[initial_capital, eq])[1:]
    return float(np.max((peak - np.minimum(eq, worst)) / peak) * 100) if len(eq) else 0.0


def portfolio_metrics(res, start_ts, end_ts=None):
    """Số đo của `res` (PortfolioEngine.get_results()) từ `start_ts` trở đi (bỏ phần warmup).
    `end_ts`: mốc end loại trừ của cửa sổ (xem daily_returns_from_curve). `daily` = lợi suất ngày theo vốn MTM (đóng cửa), nối từ vốn ban đầu; ngày lấy theo UTC."""
    init = res["initial_capital"]
    mdd = curve_mdd_pct(res["equity_curve"], start_ts, init)
    daily = pd.Series(daily_returns_from_curve(res["equity_curve"], start_ts, init, end_ts), dtype=float)
    sharpe_ = sharpe(daily.to_numpy()) or 0.0       # công thức duy nhất (sharpe()); chuỗi <2 ngày / không biến động -> 0.0
    by_sym = {k.split("@")[0].split(":")[-1]: round(v["pnl_usd"], 2) for k, v in res["by_symbol"].items()}
    rows = trade_rows(res["positions"])
    times = [c["time"] for c in res["equity_curve"] if c["time"] >= start_ts]
    end_ts = int(times[-1]) if times else int(start_ts)
    rm = return_metrics(daily.to_numpy())
    stats = {"returns": rm, "trades": trade_metrics(rows), "exposure": exposure_metrics(rows, start_ts, end_ts, init),
             "correlation": strategy_correlation(rows, start_ts, end_ts)}
    return {
        "ret_pct": round((res["final_equity"] / init - 1) * 100, 2), "mdd_pct": round(mdd, 2), "sharpe": round(sharpe_, 2),
        "trades": len(res["positions"]), "win_pct": round(float(np.mean([p.real_pnl > 0 for p in res["positions"]]) * 100), 1)
        if res["positions"] else None,   # 0 lệnh -> None (không phải 0% giả)
        "symbols_positive": sum(v > 0 for v in by_sym.values()), "by_symbol": by_sym,
        "by_strategy": {k: {"pnl_usd": round(v["pnl_usd"], 2), "trades": v["trades"]} for k, v in res["by_strategy"].items()},
        "fees_usd": round(sum(p.fees_usd or 0 for p in res["positions"]), 2),
        "funding_usd": round(sum(p.funding_usd or 0 for p in res["positions"]), 2),
        "rejected_for_risk": res["rejected_for_risk"], "rejected_for_capital": res["rejected_for_capital"],
        "halted_at": res["halted_at"], "daily": [round(float(x), 6) for x in daily.to_numpy()],
        "mdd_intrabar_pct": round(mdd, 2), "mdd_daily_pct": _r(rm["mdd_daily_pct"]), "mdd_basis": "intrabar",
        "cagr_pct": _r(rm["cagr_pct"]),
        "calmar": _r(calmar(rm["cagr_pct"], mdd)),
        "stats": _round_tree(stats),
    }


def flat_extras(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Các số đo phẳng (để lọc / sắp xếp alpha) rút từ `stats` của portfolio_metrics / series_metrics."""
    r, t = stats.get("returns") or {}, stats.get("trades") or {}
    return {"cagr_pct": _r(r.get("cagr_pct")), "calmar": _r(r.get("calmar")), "cvar95_pct": _r(r.get("cvar95_pct"), 3),
            "max_dd_days": r.get("max_dd_days"), "payoff": _r(t.get("payoff"), 3), "expectancy_pct": _r(t.get("expectancy_pct"), 4),
            "max_consec_losses": t.get("max_consec_losses"), "top5_share_pct": _r(t.get("top5_share_pct"), 1),
            "mae_worst_pct": _r(t.get("mae_worst_pct")), "liq_proximity_max_pct": _r(t.get("liq_proximity_max_pct"), 1),
            "liquidations": t.get("liquidations"), "fee_drag_pct": _r(t.get("fee_drag_pct"), 1)}


def series_metrics(daily, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Số đo phẳng từ chuỗi ngày nối + danh sách lệnh (cho S3/S4/S5): lãi kép, MDD ngày, Sharpe/Sortino quy năm, lệnh, win rate, PF
    + số đo mở rộng (CAGR, Calmar, CVaR, payoff, expectancy, chuỗi thua, MAE...)."""
    d = np.asarray(daily, dtype=float)
    rm = return_metrics(d)
    stats = {"returns": rm, "trades": trade_metrics(trades)}
    return {"ret_pct": round(rm["ret_pct"], 2) if d.size else 0.0, "mdd_pct": round(rm["mdd_daily_pct"], 2),
            "sharpe": round(rm["sharpe"], 2) if rm["sharpe"] is not None else 0.0,
            "sortino": round(rm["sortino"], 2) if rm["sortino"] is not None else 0.0,
            "trades": len(trades), **trade_stats(trades), "oos_days": int(d.size),
            "mdd_daily_pct": round(rm["mdd_daily_pct"], 2), "mdd_basis": "daily", **flat_extras(stats)}


MAX_CURVE_POINTS = 2000


def downsample(curve, limit=MAX_CURVE_POINTS):
    """<= limit điểm, cách đều theo chỉ số, luôn giữ điểm cuối (tất định)."""
    n = len(curve)
    if n <= limit:
        return list(curve)
    idx = sorted({round(i * (n - 1) / (limit - 1)) for i in range(limit)})
    return [curve[i] for i in idx]


def daily_nav(curve, end):
    """Vốn MTM cuối mỗi ngày UTC (từ đường vốn ĐẦY ĐỦ, chưa downsample) -> [{date, equity}]; dashboard dùng khi dữ liệu dài.
    Mẫu cuối đúng mốc `end` (loại trừ) tính vào ngày cuối thật (end - 1ms), không tạo thêm ngày 00:00."""
    last = {}
    for c in curve:
        last[pd.Timestamp(min(c["time"], end - 1), unit="ms").strftime("%Y-%m-%d")] = float(c["equity"])
    return [{"date": d, "equity": e} for d, e in last.items()]


def result_payload(res, start, end):
    """Kết quả chuẩn của một lần chạy từ PortfolioEngine.get_results() (hoặc dict cùng dạng của backtest tick): số đo danh mục + danh sách lệnh +
    đường vốn (<= 2000 điểm) + vốn cuối mỗi ngày. Chưa có config / final_equity / meta (người gọi thêm)."""
    out = portfolio_metrics(res, start, end)
    out["provenance"] = dict(res["provenance"])   # do engine dựng (nautilus/engine.py::provenance); job runner thêm job_id / computed_at
    out["warnings"] = list(res.get("warnings", []))   # tính năng Nautilus không mô phỏng (trượt giá, funding, thanh lý...) — nói thẳng cho người dùng
    out["risk_blocked_attempts"] = res["risk_blocked_attempts"]   # số lần vào lệnh bị chặn (rejected_for_risk đếm phút)
    out["trade_list"] = [{
        "symbol": p.symbol.split(":")[-1], "strategy": p.strategy_id, "side": p.pos_type.name,
        "enter_time": p.enter_time, "enter_price": p.enter_price, "close_time": p.close_time, "close_price": p.close_price,
        "pnl": round(p.real_pnl, 4), "status": p.status.name, "close_reason": p.close_reason,
        # khối lượng + danh nghĩa (qty × giá vào trung bình sau DCA) + ký quỹ: để tính exposure/trọng số ở dashboard
        "qty": round(p.qty, 8), "notional": round(p.qty * (p.avg_price or p.enter_price), 2),
        "margin_usd": round(p.total_margin_usd or 0.0, 2),
        # thêm cho bảng lệnh + số đo theo chiến lược (metrics/trades.rows_from_trade_list)
        "avg_price": round(p.avg_price or p.enter_price, 8), "pnl_pct": None if p.profit_pct is None else round(p.profit_pct, 4), "fees_usd": round(p.fees_usd or 0.0, 4),
        "funding_usd": round(p.funding_usd or 0.0, 4), "layers": int(p.layers or 0), "mae_pct": None if p.mae_pct is None else round(p.mae_pct, 4),
        "leverage": None if p.leverage_used is None else float(p.leverage_used or 1.0), "entry_equity": round(p.entry_equity or 0.0, 2),
    } for p in res["positions"]]
    curve = [{"time": c["time"], "equity": round(c["equity"], 2), "equity_worst": round(c["equity_worst"], 2)}
             for c in res["equity_curve"] if c["time"] >= start]
    out["equity_curve"] = downsample(curve)
    out["daily_nav"] = daily_nav(curve, end)
    return out



# ══════════════════════════════════════════════════════════════════════════
# METRIC_DEFS — từ điển MỘT NƠI cho mọi khoá chỉ số API trả cho giao diện (kết quả backtest, dashboard sổ/danh mục, phễu, WFA, Monte Carlo, live).
# Giao diện nhận qua GET /api/studio/meta (`metrics`), không tự đặt nhãn / đơn vị / định dạng.
#   label_vi: nhãn ngắn | unit: "%", "x", "USD", "lệnh", "ngày", "" | format: pct1|pct2|num2|num3|int|usd2|text (số chữ số khi hiển thị)
#   better: "higher" | "lower" | None (không có chiều tốt/xấu tự thân) | group: nhóm hiển thị | help_vi: cách tính TRONG mã này (không ngưỡng tốt/xấu)
# Khoá trùng tên ở nhiều khối (vd. `mdd_pct`, `trades`) dùng một mục: ghi rõ cơ sở khác nhau trong help_vi.
# ══════════════════════════════════════════════════════════════════════════
METRIC_GROUPS = {"return": "Lợi nhuận", "risk": "Rủi ro và sụt giảm", "trade": "Theo lệnh", "cost": "Phí và funding", "exposure": "Phơi nhiễm",
                 "benchmark": "So với thị trường", "split": "Train và test", "wfa": "Walk-forward", "montecarlo": "Monte Carlo", "regime": "Chế độ thị trường",
                 "funnel": "Phễu", "live": "Bot live"}


def _d(label_vi: str, unit: str, fmt: str, better: Optional[str], group: str, help_vi: str) -> Dict[str, Any]:
    return {"label_vi": label_vi, "unit": unit, "format": fmt, "better": better, "group": group, "help_vi": help_vi}


METRIC_DEFS: Dict[str, Dict[str, Any]] = {
    # ─── Lợi nhuận ──
    "ret_pct": _d("Lãi", "%", "pct2", "higher", "return", "Lãi kép toàn kỳ: vốn cuối / vốn đầu − 1 (đã trừ phí và funding)."),
    "cagr_pct": _d("CAGR", "%", "pct2", "higher", "return", "Lợi suất quy năm: (Π(1 + r ngày))^(365 / số ngày) − 1; vốn về 0 hoặc âm thì −100%."),
    "total_return_pct": _d("Lãi kép", "%", "pct2", "higher", "return", "Π(1 + r ngày) − 1 trên chuỗi lợi suất ngày."),
    "calmar": _d("Calmar", "", "num2", "higher", "return", "CAGR / MDD. Dùng MDD của cùng khối số liệu; MDD ≈ 0 thì không xác định."),
    "sharpe": _d("Sharpe", "", "num2", "higher", "return", "mean(r ngày) / std(r ngày, ddof=1) × √365, lãi suất phi rủi ro 0; dưới 2 ngày hoặc độ lệch ≈ 0 thì không xác định."),
    "sortino": _d("Sortino", "", "num2", "higher", "return", "mean(r ngày) / √mean(min(r, 0)²) × √365: chỉ tính độ lệch phía lỗ so với 0."),
    "vol_ann_pct": _d("Biến động năm", "%", "pct2", None, "risk", "std(r ngày, ddof=1) × √365 × 100."),
    "win_days_pct": _d("Tỉ lệ ngày lãi", "%", "pct1", "higher", "return", "Phần trăm ngày có r > 0 trong các ngày có phát sinh lãi/lỗ (|r| > 1e-12)."),
    "best_day_pct": _d("Ngày tốt nhất", "%", "pct2", "higher", "return", "Lợi suất ngày lớn nhất."),
    "worst_day_pct": _d("Ngày xấu nhất", "%", "pct2", "higher", "risk", "Lợi suất ngày nhỏ nhất."),
    "days": _d("Số ngày", "ngày", "int", None, "return", "Số ngày của chuỗi / khoảng được đo."),
    "n_days": _d("Số ngày", "ngày", "int", None, "return", "Số ngày của chuỗi lợi suất được dùng."),
    "oos_days": _d("Ngày ngoài mẫu", "ngày", "int", None, "wfa", "Số ngày của chuỗi lợi suất ghép từ các đoạn test (OOS)."),
    "total_days": _d("Tổng số ngày", "ngày", "int", None, "regime", "Số ngày giao dịch của đường vốn ngày trong phân tích chế độ thị trường."),
    "initial_capital": _d("Vốn đầu", "USD", "usd2", None, "return", "Vốn ban đầu của lần chạy."),
    "final_equity": _d("Vốn cuối", "USD", "usd2", "higher", "return", "Vốn mark-to-market cuối kỳ."),
    "net_pnl_usd": _d("Lãi ròng", "USD", "usd2", "higher", "return", "Vốn cuối − vốn đầu theo đường vốn, tính cả lệnh đang mở."),
    "gross_pnl_before_fees_usd": _d("Lãi gộp trước phí", "USD", "usd2", "higher", "return", "(Vốn cuối − vốn đầu) + phí đã trả."),
    "total_pnl_usd": _d("Tổng lãi/lỗ", "USD", "usd2", "higher", "return", "Tổng chênh lệch vốn theo ngày trong cả kỳ."),
    "pnl_usd": _d("Lãi/lỗ", "USD", "usd2", "higher", "return", "Lãi/lỗ đã chốt (đã trừ phí) của nhóm được nêu; bảng theo tài sản chỉ gồm lệnh đã đóng."),
    "open_pnl_usd": _d("Lãi/lỗ đang mở", "USD", "usd2", "higher", "return", "Lãi/lỗ chưa chốt của vị thế đang mở theo giá cuối kỳ."),
    "pnl_pct": _d("Lãi/lỗ so với vốn đầu", "%", "pct2", "higher", "live", "(vốn hiện tại / vốn đầu đường vốn − 1) × 100; vốn đầu ≤ 0 thì không tính."),
    "start": _d("Vốn đầu đường vốn", "USD", "usd2", None, "live", "Điểm vốn đầu tiên của đường vốn theo nến."),
    "last": _d("Vốn hiện tại", "USD", "usd2", None, "live", "Điểm vốn mới nhất của đường vốn theo nến."),
    "bars": _d("Số nến", "nến", "int", None, "live", "Số điểm trên đường vốn theo nến."),
    # ─── Rủi ro ──
    "mdd_pct": _d("MDD", "%", "pct2", "lower", "risk", "Sụt giảm lớn nhất từ đỉnh vốn xuống đáy kế tiếp. Cơ sở theo từng khối: backtest/sổ = trong nến (giá xấu nhất của nến), phễu/WFA/train/test = vốn đóng cửa ngày."),
    "mdd_intrabar_pct": _d("MDD trong nến", "%", "pct2", "lower", "risk", "Đỉnh vốn MTM so với min(vốn MTM, vốn ở giá xấu nhất của nến); khắt hơn MDD theo ngày."),
    "mdd_daily_pct": _d("MDD theo ngày", "%", "pct2", "lower", "risk", "Sụt giảm lớn nhất trên vốn đóng cửa mỗi ngày UTC."),
    "max_dd_days": _d("Ngày sụt giảm dài nhất", "ngày", "int", "lower", "risk", "Đợt nằm dưới đỉnh vốn dài nhất, tính bằng ngày."),
    "recovery_days": _d("Ngày hồi phục", "ngày", "int", "lower", "risk", "Số ngày từ đáy của đợt MDD tới khi lấy lại đỉnh; chưa hồi phục thì không có số."),
    "ulcer_index": _d("Ulcer index", "", "num2", "lower", "risk", "√mean(sụt giảm ngày %²): phạt cả độ sâu lẫn thời gian nằm dưới đỉnh."),
    "var95_pct": _d("VaR 95%", "%", "pct2", "lower", "risk", "Phân vị 5% lịch sử của lợi suất ngày, đổi dấu (số dương = mức lỗ 1 ngày)."),
    "cvar95_pct": _d("CVaR 95%", "%", "pct2", "lower", "risk", "Lỗ trung bình của các ngày tệ hơn hoặc bằng phân vị 5%, đổi dấu."),
    "skew": _d("Độ lệch", "", "num2", None, "risk", "Moment bậc 3 chuẩn hoá của lợi suất ngày."),
    "kurt": _d("Độ nhọn", "", "num2", None, "risk", "Moment bậc 4 chuẩn hoá của lợi suất ngày (phân phối chuẩn = 3)."),
    "sr_daily": _d("Sharpe theo ngày", "", "num3", "higher", "risk", "mean(r) / std(r, ddof=1) trên lợi suất ngày, chưa quy năm (đầu vào DSR)."),
    "mae_avg_pct": _d("Lỗ treo TB", "%", "pct2", "higher", "risk", "Trung bình MAE mỗi lệnh (lỗ chưa chốt sâu nhất, % vốn lúc mở lệnh; số âm)."),
    "mae_worst_pct": _d("Lỗ treo tệ nhất", "%", "pct2", "higher", "risk", "MAE nhỏ nhất (sâu nhất) trong các lệnh."),
    "liq_proximity_max_pct": _d("Gần thanh lý nhất", "%", "pct1", "lower", "risk", "max(|MAE| × vốn lúc vào / ký quỹ lệnh); 100% = ký quỹ bị ăn hết."),
    "liquidations": _d("Số lần thanh lý", "lệnh", "int", "lower", "risk", "Số lệnh đóng với trạng thái thanh lý."),
    "halted": _d("Bị dừng khẩn", "", "text", None, "risk", "Lần chạy bị dừng khẩn giữa chừng (có/không)."),
    # ─── Theo lệnh ──
    "trades": _d("Số lệnh", "lệnh", "int", None, "trade", "Số lệnh trong khối số liệu được nêu."),
    "total_trades": _d("Tổng số lệnh", "lệnh", "int", None, "trade", "Lệnh đã đóng cộng lệnh đang mở."),
    "closed_trades": _d("Lệnh đã đóng", "lệnh", "int", None, "trade", "Số lệnh đã đóng."),
    "open_trades": _d("Lệnh đang mở", "lệnh", "int", None, "trade", "Số vị thế còn mở cuối kỳ."),
    "long_trades": _d("Lệnh long", "lệnh", "int", None, "trade", "Số lệnh chiều long."),
    "short_trades": _d("Lệnh short", "lệnh", "int", None, "trade", "Số lệnh chiều short."),
    "short_closed_trades": _d("Lệnh short đã đóng", "lệnh", "int", None, "trade", "Số lệnh short đã đóng."),
    "short_pnl_usd": _d("Lãi/lỗ lệnh short", "USD", "usd2", "higher", "trade", "Tổng lãi/lỗ của các lệnh short đã đóng."),
    "wins": _d("Lệnh thắng", "lệnh", "int", "higher", "trade", "Số lệnh có lãi/lỗ > 0."),
    "losses": _d("Lệnh thua", "lệnh", "int", "lower", "trade", "Số lệnh có lãi/lỗ < 0."),
    "breakeven": _d("Lệnh hoà", "lệnh", "int", None, "trade", "Số lệnh có lãi/lỗ = 0."),
    "winning_trades": _d("Lệnh thắng", "lệnh", "int", "higher", "trade", "Số lệnh đã đóng có lãi > 0."),
    "losing_trades": _d("Lệnh thua", "lệnh", "int", "lower", "trade", "Số lệnh đã đóng có lỗ < 0."),
    "win_rate": _d("Tỉ lệ thắng", "%", "pct1", "higher", "trade", "Lệnh thắng / lệnh đã đóng × 100."),
    "win_rate_trades": _d("Tỉ lệ thắng", "%", "pct1", "higher", "trade", "Lệnh thắng / lệnh đã đóng × 100 (thang 0–100)."),
    "win_pct": _d("Tỉ lệ thắng", "%", "pct1", "higher", "trade", "Tỉ lệ lệnh có lãi trên mọi lệnh của lần chạy; không có lệnh thì không xác định."),
    "loss_rate": _d("Tỉ lệ thua", "%", "pct1", "lower", "trade", "Lệnh thua / tổng lệnh × 100."),
    "profit_factor": _d("Profit factor", "x", "num2", "higher", "trade", "Tổng lãi các lệnh thắng / tổng lỗ các lệnh thua (đã tính phí); không có lệnh thua thì không xác định."),
    "profit_factor_trades": _d("Profit factor", "x", "num3", "higher", "trade", "Tổng lãi các lệnh thắng / tổng lỗ các lệnh thua (đã tính phí)."),
    "gross_profit_usd": _d("Tổng lãi gộp", "USD", "usd2", "higher", "trade", "Tổng lãi các lệnh thắng."),
    "gross_loss_usd": _d("Tổng lỗ gộp", "USD", "usd2", "lower", "trade", "Tổng độ lớn lỗ các lệnh thua."),
    "avg_win": _d("Lãi TB lệnh thắng", "USD", "usd2", "higher", "trade", "Trung bình lãi của lệnh thắng."),
    "avg_loss": _d("Lỗ TB lệnh thua", "USD", "usd2", "lower", "trade", "Trung bình độ lớn lỗ của lệnh thua (số dương)."),
    "avg_win_usd": _d("Lãi TB lệnh thắng", "USD", "usd2", "higher", "trade", "Trung bình lãi của lệnh thắng."),
    "avg_loss_usd": _d("Lỗ TB lệnh thua", "USD", "usd2", None, "trade", "Trung bình lãi/lỗ của lệnh thua (số âm)."),
    "max_win": _d("Lệnh thắng nhất", "USD", "usd2", "higher", "trade", "Lãi lớn nhất của một lệnh đã đóng."),
    "max_loss": _d("Lệnh thua nhất", "USD", "usd2", "lower", "trade", "Độ lớn lỗ lớn nhất của một lệnh đã đóng (số dương)."),
    "best_trade_usd": _d("Lệnh tốt nhất", "USD", "usd2", "higher", "trade", "Lãi/lỗ lớn nhất của một lệnh."),
    "worst_trade_usd": _d("Lệnh tệ nhất", "USD", "usd2", "higher", "trade", "Lãi/lỗ nhỏ nhất của một lệnh."),
    "best_trade_pct": _d("Lệnh tốt nhất (%)", "%", "pct2", "higher", "trade", "Lãi/lỗ % lớn nhất của một lệnh."),
    "worst_trade_pct": _d("Lệnh tệ nhất (%)", "%", "pct2", "higher", "trade", "Lãi/lỗ % nhỏ nhất của một lệnh."),
    "payoff": _d("Payoff", "x", "num2", "higher", "trade", "Lãi TB lệnh thắng / độ lớn lỗ TB lệnh thua."),
    "expectancy_usd": _d("Kỳ vọng mỗi lệnh", "USD", "usd2", "higher", "trade", "Lãi/lỗ trung bình của một lệnh (đã trừ phí)."),
    "expectancy_pct": _d("Kỳ vọng mỗi lệnh (%)", "%", "pct2", "higher", "trade", "Lãi/lỗ % trung bình của một lệnh."),
    "max_consec_wins": _d("Chuỗi thắng dài nhất", "lệnh", "int", "higher", "trade", "Số lệnh thắng liên tiếp nhiều nhất (xếp theo thời điểm đóng)."),
    "max_consec_losses": _d("Chuỗi thua dài nhất", "lệnh", "int", "lower", "trade", "Số lệnh thua liên tiếp nhiều nhất (xếp theo thời điểm đóng)."),
    "max_consecutive_losses": _d("Chuỗi thua dài nhất", "lệnh", "int", "lower", "trade", "Số lệnh thua liên tiếp nhiều nhất (xếp theo thời điểm đóng)."),
    "top5_share_pct": _d("5 lệnh lãi nhất", "%", "pct1", "lower", "trade", "Tổng 5 lệnh lãi nhất / tổng lãi gộp các lệnh thắng × 100."),
    "top5_profit_pct": _d("5 lệnh lãi nhất", "%", "pct1", "lower", "trade", "Tổng 5 lệnh lãi nhất / tổng lãi gộp các lệnh thắng × 100."),
    "avg_hold_h": _d("Giữ lệnh TB", "giờ", "num2", None, "trade", "Trung bình (thời điểm đóng − thời điểm vào) của các lệnh, tính bằng giờ."),
    "max_hold_h": _d("Giữ lệnh lâu nhất", "giờ", "num2", None, "trade", "Thời gian giữ lâu nhất của một lệnh, tính bằng giờ."),
    "avg_holding_days": _d("Giữ lệnh TB", "ngày", "num2", None, "trade", "Trung bình số ngày giữ lệnh; lệnh đang mở tính tới cuối kỳ."),
    "median_holding_days": _d("Giữ lệnh trung vị", "ngày", "num2", None, "trade", "Trung vị số ngày giữ lệnh; lệnh đang mở tính tới cuối kỳ."),
    "layers_avg": _d("Số tầng DCA TB", "tầng", "num2", None, "trade", "Trung bình số tầng (lần khớp) mỗi lệnh."),
    "layers_max": _d("Số tầng DCA lớn nhất", "tầng", "int", None, "trade", "Số tầng lớn nhất của một lệnh."),
    "symbols_positive": _d("Tài sản có lãi", "", "int", "higher", "trade", "Số tài sản có lãi/lỗ đã chốt > 0."),
    "by_symbol_trades": _d("Lệnh theo tài sản", "lệnh", "int", None, "trade", "Số lệnh của một tài sản."),
    # ─── Phí ──
    "fees_usd": _d("Phí", "USD", "usd2", "lower", "cost", "Tổng phí giao dịch đã trả của các lệnh trong khối số liệu."),
    "funding_usd": _d("Funding", "USD", "usd2", None, "cost", "Tổng funding của các lệnh trong khối số liệu."),
    "fee_drag_pct": _d("Phí ăn lãi", "%", "pct2", "lower", "cost", "Phí / lãi gộp trước phí × 100; lãi gộp ≤ 0 thì không xác định."),
    "fees_pct_of_capital": _d("Phí so với vốn", "%", "pct2", "lower", "cost", "Tổng phí / vốn đầu × 100."),
    "rejected_for_risk": _d("Bị chặn vì rủi ro", "phút", "int", "lower", "cost", "Số phút có lệnh vào bị từ chối do vượt hạn mức rủi ro."),
    "rejected_for_capital": _d("Bị chặn vì vốn", "lệnh", "int", "lower", "cost", "Số lệnh vào bị từ chối do thiếu vốn."),
    "risk_blocked_attempts": _d("Lần vào lệnh bị chặn", "lần", "int", "lower", "cost", "Số lần vào lệnh bị chặn bởi quản trị rủi ro."),
    # ─── Phơi nhiễm ──
    "days_in_market_pct": _d("Ngày có vị thế", "%", "pct1", None, "exposure", "% số ngày có ít nhất một vị thế mở."),
    "time_in_market_pct": _d("Thời gian có vị thế", "%", "pct1", None, "exposure", "% thời gian của kỳ có ít nhất một lệnh mở (từ khoảng [vào, đóng] của lệnh)."),
    "avg_exposure_pct": _d("Phơi nhiễm TB", "%", "pct1", None, "exposure", "Trung bình ngày của tổng |khối lượng| × giá đóng cửa ngày / vốn cuối ngày × 100."),
    "max_exposure_pct": _d("Phơi nhiễm lớn nhất", "%", "pct1", None, "exposure", "Giá trị lớn nhất theo ngày của phơi nhiễm trên vốn."),
    "peak_margin_pct": _d("Ký quỹ đỉnh", "%", "pct1", "lower", "exposure", "Tổng ký quỹ lớn nhất cùng lúc / vốn đầu × 100."),
    "exposure_gross_avg_pct": _d("Exposure gộp TB", "%", "pct1", None, "exposure", "Trung bình theo thời gian của tổng danh nghĩa mọi vị thế (long + short, trị tuyệt đối) / vốn đầu × 100."),
    "exposure_gross_max_pct": _d("Exposure gộp lớn nhất", "%", "pct1", None, "exposure", "Tổng danh nghĩa mọi vị thế lớn nhất cùng lúc / vốn đầu × 100."),
    "exposure_net_avg_pct": _d("Exposure ròng TB", "%", "pct1", None, "exposure", "Trung bình theo thời gian của (danh nghĩa long − short) / vốn đầu × 100."),
    "exposure_net_max_pct": _d("Exposure ròng lớn nhất", "%", "pct1", None, "exposure", "Giá trị tuyệt đối lớn nhất của (long − short) / vốn đầu × 100."),
    "max_concurrent": _d("Vị thế đồng thời tối đa", "lệnh", "int", None, "exposure", "Số lệnh mở cùng lúc nhiều nhất."),
    # ─── So với thị trường ──
    "beta": _d("Beta", "", "num3", None, "benchmark", "cov(r chiến lược, r benchmark) / var(r benchmark) trên lợi suất ngày chung; benchmark = luôn long qua cùng engine."),
    "correlation": _d("Tương quan", "", "num3", None, "benchmark", "Hệ số tương quan Pearson giữa lợi suất ngày chiến lược và benchmark luôn long."),
    "excess_cagr": _d("Chênh CAGR", "%", "pct2", "higher", "benchmark", "CAGR chiến lược − CAGR benchmark (điểm %/năm)."),
    "market_cagr": _d("CAGR benchmark", "%", "pct2", None, "benchmark", "CAGR của benchmark luôn long cùng cửa sổ."),
    "market_mdd": _d("MDD benchmark", "%", "pct2", "lower", "benchmark", "MDD theo ngày của benchmark luôn long."),
    "strategy_cagr": _d("CAGR chiến lược", "%", "pct2", "higher", "benchmark", "CAGR của chiến lược trên các ngày chung với benchmark."),
    "strategy_mdd": _d("MDD chiến lược", "%", "pct2", "lower", "benchmark", "MDD theo ngày của chiến lược trên các ngày chung với benchmark."),
    "strategy_total_return_pct": _d("Lãi chiến lược", "%", "pct2", "higher", "benchmark", "Vốn cuối / vốn đầu − 1 của chiến lược trên các ngày chung với benchmark."),
    "market_total_return_pct": _d("Lãi benchmark", "%", "pct2", None, "benchmark", "Vốn cuối / vốn đầu − 1 của benchmark luôn long."),
    # ─── Train / test ──
    "train_sharpe": _d("Sharpe train", "", "num2", "higher", "split", "Sharpe trên đoạn train (cùng công thức, năm 365 ngày)."),
    "test_sharpe": _d("Sharpe test", "", "num2", "higher", "split", "Sharpe trên đoạn test, chạy lại từ vốn đầu tại mốc chia."),
    "sharpe_decay": _d("Tỉ lệ Sharpe test/train", "x", "num2", "higher", "split", "Sharpe test / Sharpe train; Sharpe train ≤ 0,1 thì không xác định."),
    "train_cagr": _d("CAGR train", "%", "pct2", "higher", "split", "CAGR trên đoạn train."),
    "test_cagr": _d("CAGR test", "%", "pct2", "higher", "split", "CAGR trên đoạn test."),
    "train_mdd": _d("MDD train", "%", "pct2", "lower", "split", "MDD trên đoạn train."),
    "test_mdd": _d("MDD test", "%", "pct2", "lower", "split", "MDD trên đoạn test."),
    # ─── Chế độ thị trường ──
    "sma_days": _d("Chu kỳ SMA", "ngày", "int", None, "regime", "Số nến ngày của SMA dùng để chia bull/bear (giá trên SMA = bull)."),
    "pct_days": _d("Tỉ lệ ngày của chế độ", "%", "pct1", None, "regime", "Số ngày thuộc chế độ / tổng số ngày × 100."),
    "pnl_share_pct": _d("Phần lãi/lỗ của chế độ", "%", "pct1", None, "regime", "Lãi/lỗ trong chế độ / tổng lãi/lỗ × 100; tổng ≈ 0 thì không xác định."),
    "trades_entered": _d("Lệnh vào trong chế độ", "lệnh", "int", None, "regime", "Số lệnh có ngày vào thuộc chế độ này."),
    "market_return_pct": _d("Lãi thị trường trong chế độ", "%", "pct2", None, "regime", "Lãi kép của giá thị trường qua các ngày thuộc chế độ."),
    "benchmark_pnl_usd": _d("Lãi/lỗ benchmark trong chế độ", "USD", "usd2", None, "regime", "Lãi/lỗ của benchmark luôn long cùng vốn qua các ngày thuộc chế độ."),
    # ─── WFA ──
    "n_folds": _d("Số fold", "", "int", "higher", "wfa", "Số cặp train → test nối tiếp."),
    "folds": _d("Số fold", "", "int", "higher", "wfa", "Số cặp train → test nối tiếp."),
    "n_traded_folds": _d("Fold có lệnh", "", "int", "higher", "wfa", "Số fold test có ít nhất một lệnh."),
    "traded_folds": _d("Fold có lệnh", "", "int", "higher", "wfa", "Số fold test có ít nhất một lệnh."),
    "n_active_folds": _d("Fold có lệnh", "", "int", "higher", "wfa", "Số fold test có ít nhất một lệnh."),
    "positive_folds": _d("Fold lãi", "", "int", "higher", "wfa", "Số fold test có lãi > 0."),
    "folds_profitable": _d("Fold lãi", "", "int", "higher", "wfa", "Số fold test có lãi > 0."),
    "positive_ratio_pct": _d("Tỉ lệ fold lãi", "%", "pct1", "higher", "wfa", "Fold lãi / tổng số fold × 100."),
    "positive_ratio": _d("Tỉ lệ fold lãi", "%", "pct1", "higher", "wfa", "Tỉ lệ fold có lãi trên các fold có lệnh, thang 0–1 (nhân 100 khi hiển thị)."),
    "fold_t": _d("t-stat lãi theo fold", "", "num2", "higher", "wfa", "t-stat của lãi trung bình mỗi fold trên các fold có lệnh; dưới 2 fold hoặc độ lệch 0 thì bằng 0."),
    "oos_ex_best_pct": _d("Lãi OOS bỏ fold tốt nhất", "%", "pct2", "higher", "wfa", "Lãi kép OOS sau khi bỏ fold lãi cao nhất."),
    "compounded_oos_ret_pct": _d("Lãi kép OOS", "%", "pct2", "higher", "wfa", "Lãi kép của lợi suất các fold test nối tiếp."),
    "avg_is_ret_pct": _d("Lãi IS trung bình", "%", "pct2", "higher", "wfa", "Trung bình lãi trên đoạn train (in-sample) của các fold."),
    "is_ret_avg": _d("Lãi IS trung bình", "%", "pct2", "higher", "wfa", "Trung bình lãi trên đoạn train (in-sample) của các fold."),
    "worst_fold_mdd_pct": _d("MDD fold xấu nhất", "%", "pct2", "lower", "wfa", "MDD lớn nhất trong các fold test."),
    "worst_fold_mdd": _d("MDD fold xấu nhất", "%", "pct2", "lower", "wfa", "MDD lớn nhất trong các fold test."),
    "turnover_daily": _d("Vòng quay ngày", "", "num3", None, "wfa", "Σ (danh nghĩa lúc mở / vốn lúc vào lệnh) / số ngày, đo từ lệnh của lượt chạy; thiếu dữ liệu lệnh thì không xác định."),
    # ─── Phễu ──
    "dsr": _d("DSR", "", "num3", "higher", "funnel", "Deflated Sharpe: xác suất Sharpe thật > 0 sau khi hiệu chỉnh số lần thử."),
    "neighbor_ratio": _d("Lân cận có lãi", "%", "pct1", "higher", "funnel", "Tỉ lệ điểm lân cận (±1 bước mỗi khoá tham số) có lãi trên dev1, thang 0–1 (nhân 100 khi hiển thị)."),
    "pbo": _d("PBO", "", "num2", "lower", "funnel", "Xác suất overfit theo CSCV: tỉ lệ lần alpha tốt nhất trong mẫu có logit hạng ngoài mẫu ≤ 0."),
    "pbo_strategy": _d("PBO (chiến lược)", "", "num2", "lower", "funnel", "PBO (CSCV) tính trên ma trận lợi suất ngày của các alpha cùng chiến lược."),
    "pbo_flag": _d("Cờ PBO", "", "text", None, "funnel", "Có: PBO của chiến lược vượt ngưỡng cảnh báo (chỉ cảnh báo, không loại alpha)."),
    "final_scale": _d("Hệ số s", "x", "num2", "higher", "funnel", "Hệ số vốn lớn nhất trong (0, 1] mà alpha còn qua cổng Monte Carlo và kịch bản cực xấu."),
    "search_steps": _d("Bước tìm s", "", "int", None, "funnel", "Số bước thử khi tìm hệ số s."),
    # ─── Monte Carlo ──
    "simulations": _d("Số mô phỏng", "", "int", "higher", "montecarlo", "Số kịch bản bootstrap theo khối."),
    "median_ret_pct": _d("Lãi trung vị", "%", "pct1", "higher", "montecarlo", "Trung vị lãi cuối chân trời của các kịch bản mô phỏng."),
    "p05_ret_pct": _d("Lãi P5", "%", "pct1", "higher", "montecarlo", "Phân vị 5% lãi cuối chân trời."),
    "mdd_p50_pct": _d("MDD trung vị", "%", "pct1", "lower", "montecarlo", "Trung vị MDD của các kịch bản."),
    "mdd_p95_pct": _d("MDD P95", "%", "pct1", "lower", "montecarlo", "Phân vị 95% của MDD các kịch bản."),
    "p_mdd_ge_ruin_pct": _d("P(MDD ≥ ngưỡng phá sản)", "%", "pct2", "lower", "montecarlo", "% kịch bản có MDD chạm hoặc vượt ngưỡng phá sản của lần chạy."),
    # khoá giữ tên cũ "p_mdd_ge_30"; con số trong nhãn đọc từ MC_RUIN_THRESHOLD_PCT (carlo.py), không chép tay
    "p_mdd_ge_30": _d(f"P(MDD ≥ {MC_RUIN_THRESHOLD_PCT:g}%)", "%", "pct2", "lower", "montecarlo",
                      f"% kịch bản có MDD ≥ ngưỡng phá sản ({MC_RUIN_THRESHOLD_PCT:g}% theo cổng chuẩn)."),
    "mdd_p95": _d("MDD P95", "%", "pct1", "lower", "montecarlo", "Phân vị 95% của MDD các kịch bản (bí danh của mdd_p95_pct trong bảng phễu)."),
    "mdd_basis": _d("Cơ sở MDD", "", "text", None, "risk", "Cách đo MDD của số liệu: intrabar = trong nến (giá xấu nhất của nến), daily = theo vốn đóng cửa ngày."),
    "stress_max_mdd": _d("MDD kịch bản cực xấu", "%", "pct1", "lower", "montecarlo", "MDD lớn nhất trong các kịch bản cực xấu."),
    "block_days": _d("Độ dài khối", "ngày", "int", None, "montecarlo", "Số ngày liên tiếp mỗi lần lấy mẫu bootstrap."),
    "horizon_days": _d("Chân trời", "ngày", "int", None, "montecarlo", "Số ngày của mỗi kịch bản mô phỏng."),
}
