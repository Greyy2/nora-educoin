"""Chẩn đoán chi tiết từ kết quả chạy backtest (B3 — lớp thực tế, không dùng LLM).

QUY TẮC: mọi con số đều tính từ dữ liệu của CHÍNH lần chạy (đường vốn, lệnh, giá nến, chương trình đã biên dịch). Không có hằng số giả/ước lượng;
thiếu đầu vào (không có benchmark, không có giá thị trường, không có nến) thì mục tương ứng ghi `available: False` / None, KHÔNG bịa số.

Các nhóm:
1. signal_activity: số lệnh, thời gian nắm giữ, lý do thoát THẬT (close_reason của engine), ngày có vị thế, exposure trung bình, thời gian theo từng coin.
2. binding_condition: với mỗi quy tắc vào lệnh dạng A & B & C: % nến đúng của từng điều kiện và % nến mà nó là điều kiện DUY NHẤT sai (điều kiện chặn); quy tắc một vế chỉ có % nến đúng (binding = None).
3. market_comparison: so với benchmark "luôn long" chạy qua CÙNG đường engine (beta, tương quan, CAGR, MDD, excess CAGR) — benchmark do custom_run chạy.
4. train_vs_test: Sharpe, CAGR, MDD và mức suy giảm ngoài mẫu (OOS decay).
5. pnl_structure: win rate, payoff, top 5 lệnh, chuỗi thua, fee drag, phân bổ coin & năm.
6. regime_analysis: chế độ thị trường theo giá BTC (hoặc chỉ số rổ nếu không có BTC) trên/dưới SMA200 nhân quả: số ngày, lãi theo ngày, lệnh vào, thời gian có vị thế.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.strategy.pydsl.program import Program

DAY = 86_400_000
SMA_DAYS = 200
EXIT_CATEGORIES = ("signal", "stop_loss", "take_profit", "trailing", "timeout", "kill_switch", "open_at_end")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        val = float(v)
        return default if np.isnan(val) or np.isinf(val) else val
    except (TypeError, ValueError):
        return default


def _num(v: Any, nd: int = 2) -> Optional[float]:
    """float làm tròn hoặc None nếu không hữu hạn (JSON an toàn)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


def _base(sym: str) -> str:
    return str(sym).split(":")[-1].split("@")[0]


# ─── Chuẩn hoá lệnh (đã đóng + đang mở) ─────────────────────────────────────

def exit_category(reason: Any) -> str:
    """close_reason của engine (core/backtest/kernel.py REASONS) -> signal | stop_loss | take_profit | trailing | timeout | kill_switch | open_at_end |
    liquidation | other | unknown. KHÔNG suy từ status (status chỉ là dấu lãi/lỗ cho thoát theo tín hiệu)."""
    r = str(reason or "").strip().lower()
    if not r:
        return "unknown"
    if r.startswith("tín hiệu thoát") or "ast stop" in r:
        return "signal"
    if r.startswith("stop-loss") or r == "sl":
        return "stop_loss"
    if r.startswith("take-profit") or r == "tp":
        return "take_profit"
    if r.startswith("trailing"):
        return "trailing"
    if "hết thời gian giữ" in r or r == "timeout":
        return "timeout"
    if r.startswith("kill switch"):
        return "kill_switch"
    if r.startswith("end of backtest"):
        return "open_at_end"
    if r.startswith("thanh lý"):
        return "liquidation"
    return "other"


def normalize_trades(trades: List[Dict[str, Any]], open_positions: Optional[List[Dict[str, Any]]], end: int = 0) -> List[Dict[str, Any]]:
    """Danh sách lệnh thống nhất: {sym, side, enter, close (None = đang mở), qty, pnl, realized, category, notional}. Lệnh mở tính pnl = unrealized (mark giá cuối)."""
    out: List[Dict[str, Any]] = []
    for t in trades or []:
        reason = t.get("close_reason") or t.get("exit_reason")
        out.append({"sym": str(t.get("symbol", "UNKNOWN")).split(":")[-1], "side": str(t.get("side", "")).upper(), "enter": int(t.get("enter_time") or 0),
                    "close": int(t.get("close_time") or 0) or None, "qty": abs(_safe_float(t.get("qty"))), "pnl": _safe_float(t.get("pnl", t.get("realized_pnl"))),
                    "realized": True, "category": exit_category(reason), "notional": _safe_float(t.get("notional"))})
    for p in open_positions or []:
        out.append({"sym": str(p.get("symbol", "UNKNOWN")).split(":")[-1], "side": str(p.get("side", "")).upper(), "enter": int(p.get("opened") or 0),
                    "close": None, "qty": abs(_safe_float(p.get("qty"))), "pnl": _safe_float(p.get("unrealized_pnl")), "realized": False,
                    "category": "open_at_end", "notional": _safe_float(p.get("notional"))})
    return out


# ─── Ngày có vị thế / exposure ──────────────────────────────────────────────

def _day_span(times: np.ndarray, enter: int, close: Optional[int]) -> Optional[Tuple[int, int]]:
    """Chỉ số ngày k (ngày k = [times[k], times[k+1])) đầu/cuối mà lệnh còn mở; None nếu lệnh không chạm ngày nào."""
    n_days = times.shape[0] - 1
    if n_days <= 0:
        return None
    k0 = max(int(np.searchsorted(times, enter, side="right")) - 1, 0)
    k1 = n_days - 1 if close is None else min(int(np.searchsorted(times, close, side="left")) - 1, n_days - 1)
    return (k0, k1) if k0 <= k1 and k1 >= 0 else None


def _price_at(prices: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]], sym: str, t: np.ndarray) -> Optional[np.ndarray]:
    """Giá đóng cửa ngày gần nhất có nhãn <= t (nhãn = giờ ĐÓNG nến); None nếu không có giá của tài sản."""
    if not prices:
        return None
    ent = prices.get(sym) or prices.get(_base(sym))
    if ent is None or len(ent[0]) == 0:
        return None
    lab, cl = ent
    idx = np.searchsorted(lab, t, side="right") - 1
    out = np.where(idx >= 0, cl[np.maximum(idx, 0)], np.nan)
    return out


def daily_positions(times: np.ndarray, norm: List[Dict[str, Any]]) -> Tuple[np.ndarray, Dict[str, np.ndarray], List[Tuple[Dict[str, Any], int, int]]]:
    """(số vị thế đang mở theo ngày, {coin: bool theo ngày}, [(lệnh, k0, k1)])."""
    n_days = max(times.shape[0] - 1, 0)
    count = np.zeros(n_days, dtype="int64")
    by_coin: Dict[str, np.ndarray] = {}
    spans = []
    for tr in norm:
        sp = _day_span(times, tr["enter"], tr["close"])
        if sp is None:
            continue
        k0, k1 = sp
        count[k0:k1 + 1] += 1
        by_coin.setdefault(_base(tr["sym"]), np.zeros(n_days, dtype=bool))[k0:k1 + 1] = True
        spans.append((tr, k0, k1))
    return count, by_coin, spans


def compute_exposure(series: Dict[str, np.ndarray], norm: List[Dict[str, Any]],
                     prices: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None) -> Dict[str, Any]:
    """days_in_market_pct = % số ngày có >= 1 vị thế mở; avg_exposure_pct = trung bình ngày của (tổng |qty| × giá đóng cửa ngày) / vốn cuối ngày;
    time_in_market_by_coin = % số ngày có vị thế theo từng coin. Chỉ dùng dữ liệu của lần chạy."""
    times, eq = np.asarray(series.get("times", [])), np.asarray(series.get("equity", []), dtype=float)
    n_days = times.shape[0] - 1
    if n_days <= 0 or eq.shape[0] != times.shape[0]:
        return {"days": 0, "days_in_market_pct": None, "avg_exposure_pct": None, "max_exposure_pct": None, "time_in_market_by_coin": {}, "exposure_basis": None}
    count, by_coin, spans = daily_positions(times, norm)
    gross = np.zeros(n_days)
    fallback = 0
    for tr, k0, k1 in spans:
        ks = np.arange(k0, k1 + 1)
        px = _price_at(prices, tr["sym"], times[ks + 1])
        if px is None or not np.isfinite(px).any():
            fallback += 1
            gross[ks] += tr["notional"]
            continue
        # ngày chưa có giá (trước nến đầu có dữ liệu) -> giá vào lệnh (notional/qty) thay vì NaN
        entry_px = tr["notional"] / tr["qty"] if tr["qty"] > 0 else 0.0
        gross[ks] += tr["qty"] * np.where(np.isfinite(px), px, entry_px)
    expo = np.where(eq[1:] > 0, gross / np.where(eq[1:] > 0, eq[1:], 1.0) * 100.0, 0.0)
    return {"days": int(n_days), "days_in_market_pct": _num((count > 0).mean() * 100.0), "avg_exposure_pct": _num(expo.mean()), "max_exposure_pct": _num(expo.max()),
            "time_in_market_by_coin": {c: _num(m.mean() * 100.0) for c, m in sorted(by_coin.items())},
            "exposure_basis": "mtm_daily_close" if not fallback else f"mtm_daily_close (+{fallback} lệnh dùng danh nghĩa tại thời điểm vào)"}


# ─── 1. Hoạt động tín hiệu ──────────────────────────────────────────────────

def compute_signal_activity(trades: List[Dict[str, Any]], start: int, end: int, series: Optional[Dict[str, np.ndarray]] = None,
                            open_positions: Optional[List[Dict[str, Any]]] = None,
                            prices: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None) -> Dict[str, Any]:
    """Số lệnh (đóng + đang mở), thời gian nắm giữ trung bình, lý do thoát thật, ngày có vị thế, exposure."""
    norm = normalize_trades(trades, open_positions, end)
    n_closed = sum(1 for t in norm if t["realized"])
    n_open = len(norm) - n_closed
    expo = compute_exposure(series, norm, prices) if series is not None else {}
    base = {"total_trades": len(norm), "closed_trades": n_closed, "open_trades": n_open, "avg_holding_days": 0.0, "median_holding_days": 0.0,
            "exit_reasons": {}, "exit_reason_counts": {}, "long_trades": 0, "short_trades": 0,
            "days_in_market_pct": expo.get("days_in_market_pct"), "avg_exposure_pct": expo.get("avg_exposure_pct"),
            "max_exposure_pct": expo.get("max_exposure_pct"), "time_in_market_by_coin": expo.get("time_in_market_by_coin", {}),
            "exposure_basis": expo.get("exposure_basis")}
    if not norm:
        return base
    hold_days = np.asarray([max((t["close"] if t["close"] is not None else end) - t["enter"], 0) for t in norm], dtype=float) / DAY
    counts: Dict[str, int] = {}
    for t in norm:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    base.update({
        "avg_holding_days": round(float(hold_days.mean()), 2), "median_holding_days": round(float(np.median(hold_days)), 2),
        "holding_basis": "lệnh đang mở tính tới cuối kỳ",
        "exit_reason_counts": counts, "exit_reasons": {k: round(v / len(norm) * 100.0, 1) for k, v in counts.items()},
        "long_trades": sum(1 for t in norm if t["side"] == "LONG"), "short_trades": sum(1 for t in norm if t["side"] == "SHORT"),
    })
    return base


# ─── 5. Cấu trúc lãi/lỗ ─────────────────────────────────────────────────────

def compute_pnl_structure(trades: List[Dict[str, Any]], fees_total: float, initial_capital: float,
                          open_positions: Optional[List[Dict[str, Any]]] = None, series: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, Any]:
    """win_rate/payoff/top5/chuỗi thua/avg_win/avg_loss/max_win/max_loss (USDT, độ lớn dương)/số lệnh thắng-thua tính trên lệnh ĐÃ ĐÓNG; by_coin = đã chốt + lãi/lỗ lệnh đang mở (mark giá cuối);
    fee_drag_pct = phí / lãi gộp trước phí, lãi gộp = (vốn cuối - vốn đầu) + phí (theo đường vốn, tính cả lệnh đang mở)."""
    eq = np.asarray((series or {}).get("equity", []), dtype=float)
    net = float(eq[-1] - initial_capital) if eq.size else None
    gross_before_fees = (net + fees_total) if net is not None else None
    fee_drag = round(fees_total / gross_before_fees * 100.0, 2) if gross_before_fees and gross_before_fees > 0 else None
    base: Dict[str, Any] = {
        "closed_trades": len(trades or []), "win_rate": None, "payoff": None, "top5_profit_pct": None, "max_consecutive_losses": 0,
        "winning_trades": None, "losing_trades": None, "avg_win": None, "avg_loss": None, "max_win": None, "max_loss": None,
        "fees_usd": _num(fees_total), "net_pnl_usd": _num(net), "gross_pnl_before_fees_usd": _num(gross_before_fees), "fee_drag_pct": fee_drag,
        "fees_pct_of_capital": _num(fees_total / initial_capital * 100.0) if initial_capital else None, "by_coin": {}, "by_year": {}, "short_pnl_usd": 0.0,
        "short_closed_trades": 0,
    }
    by_coin: Dict[str, float] = {}
    for t in trades or []:
        by_coin[_base(t.get("symbol", "UNKNOWN"))] = by_coin.get(_base(t.get("symbol", "UNKNOWN")), 0.0) + _safe_float(t.get("pnl", t.get("realized_pnl")))
    for p in open_positions or []:
        by_coin[_base(p.get("symbol", "UNKNOWN"))] = by_coin.get(_base(p.get("symbol", "UNKNOWN")), 0.0) + _safe_float(p.get("unrealized_pnl"))
    base["by_coin"] = {k: round(v, 2) for k, v in sorted(by_coin.items())}
    base["by_coin_basis"] = "đã chốt + lệnh đang mở theo giá cuối"
    if not trades:
        return base

    pnls = np.asarray([_safe_float(t.get("pnl", t.get("realized_pnl"))) for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(np.abs(losses.mean())) if len(losses) else 0.0
    gross_profit = float(wins.sum())
    streak = best = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        best = max(best, streak)
    by_year: Dict[int, float] = {}
    for t in trades:
        ts = int(t.get("close_time") or t.get("enter_time") or 0)
        if ts > 0:
            yr = pd.Timestamp(ts, unit="ms", tz="UTC").year
            by_year[yr] = round(by_year.get(yr, 0.0) + _safe_float(t.get("pnl", t.get("realized_pnl"))), 2)
    shorts = [t for t in trades if str(t.get("side", "")).upper() == "SHORT"]
    base.update({
        "winning_trades": int(len(wins)), "losing_trades": int(len(losses)),
        "avg_win": _num(avg_win) if len(wins) else None, "avg_loss": _num(avg_loss) if len(losses) else None,      # độ lớn (USDT, dương); None khi không có lệnh loại đó
        "max_win": _num(float(wins.max())) if len(wins) else None, "max_loss": _num(float(-losses.min())) if len(losses) else None,
        "win_rate": round(float(len(wins) / len(pnls) * 100.0), 2), "payoff": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "top5_profit_pct": round(float(np.sort(wins)[::-1][:5].sum()) / gross_profit * 100.0, 2) if gross_profit > 0 else None,
        "max_consecutive_losses": best, "by_year": by_year,
        "short_pnl_usd": round(sum(_safe_float(t.get("pnl", t.get("realized_pnl"))) for t in shorts), 2), "short_closed_trades": len(shorts),
    })
    return base


# ─── 3. So sánh thị trường (benchmark luôn long qua cùng engine) ────────────

def _cagr_mdd(times: np.ndarray, eq: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """(CAGR %, MDD %) từ đường vốn ngày — CÙNG định nghĩa với metrics.simulate (metrics/returns.cagr_pct): CAGR = (vốn cuối/vốn đầu)^(365/số ngày lợi suất) − 1 với
    số ngày lợi suất = số mẫu − 1 (mẫu đầu = vốn đầu, không phải một ngày giao dịch); MDD dương theo vốn đóng ngày."""
    from backend.core.metrics.returns import cagr_pct
    if eq.shape[0] < 2 or eq[0] <= 0:
        return None, None
    peak = np.maximum.accumulate(eq)
    return _num(cagr_pct(eq[1:] / eq[:-1] - 1.0)), _num(abs(float((eq / peak - 1.0).min())) * 100.0)


def compute_market_comparison(strat_equity: np.ndarray, strat_times: np.ndarray, initial_capital: float,
                              benchmark: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """benchmark = {"times","equity", "label"?}: đường vốn ngày của lần chạy "luôn long" qua CÙNG engine/hồ sơ/rổ/ngày/vốn (custom_run).
    Không có benchmark -> available False và không có beta/tương quan (không bịa)."""
    eq, tm = np.asarray(strat_equity, dtype=float), np.asarray(strat_times, dtype="int64")
    s_cagr, s_mdd = _cagr_mdd(tm, eq)
    out: Dict[str, Any] = {"available": False, "beta": None, "correlation": None, "excess_cagr": None, "market_cagr": None, "market_mdd": None,
                           "strategy_cagr": s_cagr, "strategy_mdd": s_mdd, "benchmark": (benchmark or {}).get("label")}
    if not benchmark or eq.shape[0] < 3:
        return out
    bt, be = np.asarray(benchmark["times"], dtype="int64"), np.asarray(benchmark["equity"], dtype=float)
    common, ia, ib = np.intersect1d(tm, bt, return_indices=True)
    if common.shape[0] < 3:
        return out
    se, bq = eq[ia], be[ib]
    sr, br = se[1:] / se[:-1] - 1.0, bq[1:] / bq[:-1] - 1.0
    ok = np.isfinite(sr) & np.isfinite(br)
    sr, br = sr[ok], br[ok]
    beta = corr = None
    if sr.shape[0] >= 2 and br.std() > 1e-12:
        beta = float(np.cov(sr, br, ddof=0)[0, 1] / br.var())
        if sr.std() > 1e-12:
            corr = float(np.corrcoef(sr, br)[0, 1])
    m_cagr, m_mdd = _cagr_mdd(common, bq)
    s_cagr, s_mdd = _cagr_mdd(common, se)
    out.update({"available": True, "beta": _num(beta, 3), "correlation": _num(corr, 4), "market_cagr": m_cagr, "market_mdd": m_mdd,
                "strategy_cagr": s_cagr, "strategy_mdd": s_mdd,
                "excess_cagr": _num(s_cagr - m_cagr) if s_cagr is not None and m_cagr is not None else None,
                "strategy_total_return_pct": _num((se[-1] / se[0] - 1.0) * 100.0), "market_total_return_pct": _num((bq[-1] / bq[0] - 1.0) * 100.0),
                "days": int(common.shape[0] - 1)})
    return out


# ─── 4. Train vs test ───────────────────────────────────────────────────────

def _stage_numbers(block: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """(sharpe, CAGR %, MDD %) của một giai đoạn từ bộ chỉ số phẳng {sharpe, cagr_pct, mdd_pct} (năm = 365 ngày)."""
    sharpe, cagr, mdd = block.get("sharpe"), block.get("cagr_pct"), block.get("mdd_pct")
    return {"sharpe": _num(sharpe) if sharpe is not None else None, "cagr": _num(_safe_float(cagr)) if cagr is not None else None,
            "mdd": _num(abs(_safe_float(mdd))) if mdd is not None else None}


def compute_train_vs_test(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Sharpe/CAGR/MDD của train và test (test = lần chạy lại từ vốn đầu tại mốc chia nếu có) + sharpe_decay = test/train (None nếu Sharpe train <= 0,1)."""
    tr, te = _stage_numbers(metrics.get("train", {}) or {}), _stage_numbers(metrics.get("test", {}) or {})
    decay = round(te["sharpe"] / tr["sharpe"], 2) if tr["sharpe"] is not None and te["sharpe"] is not None and tr["sharpe"] > 0.1 else None
    return {"train_sharpe": tr["sharpe"], "test_sharpe": te["sharpe"], "sharpe_decay": decay, "train_cagr": tr["cagr"], "test_cagr": te["cagr"],
            "train_mdd": tr["mdd"], "test_mdd": te["mdd"]}


# ─── 6. Chế độ thị trường (SMA200 nhân quả của BTC / rổ) ────────────────────

def _market_state(market: Dict[str, Any], t: np.ndarray) -> np.ndarray:
    """+1 giá trên SMA200, -1 dưới, 0 chưa đủ 200 nến. Trạng thái tại mốc t chỉ dùng nến ĐÃ ĐÓNG (nhãn <= t); SMA gồm nến hiện tại, trượt trên toàn lịch sử nạp được
    (kể cả trước start)."""
    lab, cl = np.asarray(market["label_times"], dtype="int64"), np.asarray(market["close"], dtype=float)
    sma = pd.Series(cl).rolling(SMA_DAYS, min_periods=SMA_DAYS).mean().to_numpy()
    state = np.where(np.isfinite(sma) & np.isfinite(cl), np.where(cl > sma, 1, -1), 0)
    idx = np.searchsorted(lab, t, side="right") - 1
    return np.where(idx >= 0, state[np.maximum(idx, 0)], 0)


def compute_regime_analysis(series: Dict[str, np.ndarray], trades: List[Dict[str, Any]], open_positions: Optional[List[Dict[str, Any]]] = None,
                            market: Optional[Dict[str, Any]] = None, benchmark: Optional[Dict[str, Any]] = None,
                            initial_capital: Optional[float] = None) -> Dict[str, Any]:
    """Mỗi NGÀY giao dịch k (= [times[k], times[k+1])) thuộc chế độ theo giá thị trường lúc MỞ ngày (times[k]) so với SMA200: bull (trên) | bear (dưới) | unknown (chưa đủ
    200 nến). Mỗi chế độ: days, pnl_usd (tổng lãi/lỗ theo ngày của chiến lược), pnl_share_pct, trades_entered, days_in_market_pct, market_return_pct (chỉ số thị trường) và
    benchmark_pnl_usd (benchmark luôn long cùng vốn). Σ days của ba chế độ = tổng số ngày."""
    times, eq = np.asarray(series.get("times", [])), np.asarray(series.get("equity", []), dtype=float)
    n_days = times.shape[0] - 1
    if not market or n_days <= 0 or eq.shape[0] != times.shape[0]:
        return {"available": False, "reason": "thiếu giá thị trường" if not market else "chuỗi ngày quá ngắn"}
    state = _market_state(market, times[:-1])
    daily_pnl = np.diff(eq)
    norm = normalize_trades(trades, open_positions, int(times[-1]))
    count, _, _ = daily_positions(times, norm)
    # ngày của lệnh = ngày chứa thời điểm vào; vào đúng mốc cuối (times[-1]) hoặc trước mốc đầu thì tính vào ngày cuối / ngày đầu để không mất lệnh và không vượt chỉ số
    enter_day = np.asarray([min(max(int(np.searchsorted(times, t["enter"], side="right")) - 1, 0), n_days - 1) for t in norm], dtype="int64")
    bench_pnl = None
    if benchmark:
        _, ia, ib = np.intersect1d(times, np.asarray(benchmark["times"], dtype="int64"), return_indices=True)
        if ia.shape[0] == times.shape[0]:
            bench_pnl = np.diff(np.asarray(benchmark["equity"], dtype=float)[ib])
    lab, cl = np.asarray(market["label_times"], dtype="int64"), np.asarray(market["close"], dtype=float)
    mclose_a = cl[np.maximum(np.searchsorted(lab, times[:-1], side="right") - 1, 0)]
    mclose_b = cl[np.maximum(np.searchsorted(lab, times[1:], side="right") - 1, 0)]
    mret = np.where(mclose_a > 0, mclose_b / mclose_a - 1.0, 0.0)
    total_pnl = float(daily_pnl.sum())
    out: Dict[str, Any] = {"available": True, "market": market.get("source"), "sma_days": SMA_DAYS, "total_days": int(n_days), "total_pnl_usd": _num(total_pnl)}
    for name, code in (("bull", 1), ("bear", -1), ("unknown", 0)):
        m = state == code
        d = int(m.sum())
        out[name] = {"days": d, "pct_days": _num(d / n_days * 100.0), "pnl_usd": _num(daily_pnl[m].sum()),
                     "pnl_share_pct": _num(daily_pnl[m].sum() / total_pnl * 100.0) if abs(total_pnl) > 1e-9 else None,
                     "trades_entered": int(sum(1 for k in enter_day if m[k])), "days_in_market_pct": _num((count[m] > 0).mean() * 100.0) if d else None,
                     "market_return_pct": _num((np.prod(1.0 + mret[m]) - 1.0) * 100.0) if d else None,
                     "benchmark_pnl_usd": _num(bench_pnl[m].sum()) if bench_pnl is not None else None}
    out["initial_capital"] = _num(initial_capital) if initial_capital is not None else None
    return out


# ─── 2. Điều kiện chặn (binding condition) ──────────────────────────────────

def _conjuncts(node) -> List[Any]:
    """Các vế cấp cao nhất của một chuỗi A & B & C (cả toán tử & lẫn op and_)."""
    from backend.core.strategy.pydsl.program import Call, Logic
    if isinstance(node, Logic) and node.op == "&":
        return _conjuncts(node.a) + _conjuncts(node.b)
    if isinstance(node, Call) and not node.is_feature and node.spec.name == "and_":
        return _conjuncts(node.bound["a"]) + _conjuncts(node.bound["b"])
    return [node]


def compute_binding_condition(program: Optional[Program], frames: Optional[Dict[str, pd.DataFrame]], start: int, end: int) -> Dict[str, Any]:
    """Với mỗi quy tắc VÀO lệnh (set_positions mức != 0) có >= 1 vế (A & B & C; một vế chỉ tính pct_true, không có binding): tính từng vế trên nến khung chiến lược của từng tài sản (chỉ báo tính từ đầu lịch sử như engine;
    đếm nến có open_time trong [start, end)). Mỗi vế: pct_true, only_false_bars (nến mà nó là vế DUY NHẤT sai = vế chặn), share_of_near_miss_pct = only_false / (tổng nến chỉ sai
    đúng một vế). `binding` = vế có phần chặn lớn nhất. Bỏ qua điều kiện giờ vào lệnh (position_open_times/ranges)."""
    from backend.core.strategy.pydsl.explain import expr_to_vi
    from backend.core.strategy.pydsl.program import Ctx
    if program is None or not frames:
        return {"available": False, "rules": [], "reason": "thiếu chương trình hoặc nến"}
    rules: List[Dict[str, Any]] = []
    for idx, (mask, level, line) in enumerate(program.calls, start=1):
        if level == 0:
            continue
        nodes, seen = [], set()
        for nd in _conjuncts(mask):
            txt = expr_to_vi(nd)
            if txt not in seen:
                seen.add(txt)
                nodes.append((nd, txt))
        rule: Dict[str, Any] = {"index": idx, "line": line, "level": float(level), "side": "LONG" if level > 0 else "SHORT", "n_conjuncts": len(nodes), "conjuncts": [], "binding": None}
        if len(nodes) == 1:      # một vế: chỉ có % nến đúng (không có vế chặn / phần suýt đạt)
            tot_bars = true_bars = 0
            per_symbol1: Dict[str, Any] = {}
            for sym, df in frames.items():
                n, data = Program._data(df)
                ot = np.asarray(df["open_time"], dtype="int64")
                win = (ot >= start) & (ot < end)
                nbars = int(win.sum())
                if nbars == 0:
                    continue
                ev = np.broadcast_to(np.asarray(nodes[0][0].ev(Ctx(n, data)), dtype=bool), (n,))[win]
                tot_bars += nbars
                true_bars += int(ev.sum())
                per_symbol1[_base(sym)] = {"pct_true": _num(ev.mean() * 100.0), "bars": nbars}
            rule.update({"bars": int(tot_bars), "all_true_bars": int(true_bars)})
            rule["conjuncts"] = [{"index": 1, "text_vi": nodes[0][1], "pct_true": _num(true_bars / tot_bars * 100.0) if tot_bars else None, "per_symbol": per_symbol1}]
        elif len(nodes) >= 2:
            tot_bars = all_true = near = 0
            true_c, only_c = np.zeros(len(nodes), dtype="int64"), np.zeros(len(nodes), dtype="int64")
            per_symbol: List[Dict[str, Any]] = [{} for _ in nodes]
            for sym, df in frames.items():
                n, data = Program._data(df)
                win = (np.asarray(df["open_time"], dtype="int64") >= start) & (np.asarray(df["open_time"], dtype="int64") < end)
                ctx = Ctx(n, data)
                ev = np.stack([np.broadcast_to(np.asarray(nd.ev(ctx), dtype=bool), (n,)) for nd, _ in nodes])[:, win]
                nbars = int(win.sum())
                if nbars == 0:
                    continue
                n_false = (~ev).sum(axis=0)
                tot_bars += nbars
                all_true += int((n_false == 0).sum())
                near += int((n_false == 1).sum())
                for j in range(len(nodes)):
                    only = int(((n_false == 1) & ~ev[j]).sum())
                    true_c[j] += int(ev[j].sum())
                    only_c[j] += only
                    per_symbol[j][_base(sym)] = {"pct_true": _num(ev[j].mean() * 100.0), "only_false_bars": only, "bars": nbars}
            rule.update({"bars": int(tot_bars), "all_true_bars": int(all_true), "near_miss_bars": int(near)})
            for j, (nd, txt) in enumerate(nodes):
                rule["conjuncts"].append({"index": j + 1, "text_vi": txt, "pct_true": _num(true_c[j] / tot_bars * 100.0) if tot_bars else None,
                                          "only_false_bars": int(only_c[j]), "pct_only_false_of_bars": _num(only_c[j] / tot_bars * 100.0) if tot_bars else None,
                                          "share_of_near_miss_pct": _num(only_c[j] / near * 100.0) if near else None, "per_symbol": per_symbol[j]})
            if near > 0:
                best = max(range(len(nodes)), key=lambda j: only_c[j])
                rule["binding"] = {"index": best + 1, **{k: rule["conjuncts"][best][k] for k in ("text_vi", "pct_true", "only_false_bars", "share_of_near_miss_pct")}}
        rules.append(rule)
    return {"available": True, "timeframe": program.timeframe, "symbols": sorted({_base(s) for s in frames}), "rules": rules}


# ─── Tổng hợp ───────────────────────────────────────────────────────────────

def diagnose_run(program: Optional[Program], series: Dict[str, np.ndarray], trades: List[Dict[str, Any]],
                 metrics: Dict[str, Any], initial_capital: float, start: int, end: int, fees_total: float = 0.0, *,
                 open_positions: Optional[List[Dict[str, Any]]] = None, benchmark: Optional[Dict[str, Any]] = None,
                 market: Optional[Dict[str, Any]] = None, prices: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None,
                 frames: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    """Tổng hợp chẩn đoán B3. Đầu vào tuỳ chọn (không có -> mục tương ứng available False, không bịa):
    open_positions  eng.open_positions() (lệnh đang mở cuối kỳ)
    benchmark       {"times","equity","label"} đường vốn ngày của benchmark luôn long qua cùng engine
    market          {"label_times","close","source"} chuỗi giá ngày của BTC (hoặc chỉ số rổ) gồm cả lịch sử trước start
    prices          {symbol: (label_times, close)} giá đóng cửa ngày để tính exposure theo giá thị trường
    frames          {symbol: DataFrame nến khung chiến lược toàn lịch sử} cho binding_condition"""
    eq = series.get("equity", np.array([]))
    times = series.get("times", np.array([]))
    return {
        "signal_activity": compute_signal_activity(trades, start, end, series, open_positions, prices),
        "binding_condition": compute_binding_condition(program, frames, start, end),
        "pnl_structure": compute_pnl_structure(trades, fees_total, initial_capital, open_positions, series),
        "market_comparison": compute_market_comparison(eq, times, initial_capital, benchmark),
        "train_vs_test": compute_train_vs_test(metrics),
        "regime_analysis": compute_regime_analysis(series, trades, open_positions, market, benchmark, initial_capital),
    }
