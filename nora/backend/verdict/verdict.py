"""Kết luận chống ăn may (P9.5): DSR / PBO / lân cận / N hiệu dụng (antiluck), chẩn đoán chi tiết từ kết quả chạy (diagnose), bộ quy tắc nhận xét (insights).

Hợp nhất NGUYÊN VĂN từ optimize/funnel/antiluck.py + core/metrics/diagnose.py + core/analytics/insights.py (xem docs/bmad/p9_review_log.md, mục P9.5).
Đường dẫn cũ là shim. Không import crawl; `core/metrics/diagnose_inputs.py` (có I/O) ở lại chỗ cũ — phiên logic sẽ tách, phần tính thuần về đây.
"""
import itertools
import math
from statistics import NormalDist
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backend.core.signal import Program


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ optimize/funnel/antiluck.py
#
# Chống ăn may (S2): Deflated Sharpe Ratio, PBO (CSCV), lân cận tham số + thống kê chuỗi lợi suất ngày.
#
# - DSR: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio". Mọi Sharpe ở đây là Sharpe THEO NGÀY (không quy năm).
#     SR0 = sqrt(V[SR_trials]) * ((1 - γ) * Φ^-1(1 - 1/N) + γ * Φ^-1(1 - 1/(N e)))       (kỳ vọng SR lớn nhất của N lần thử, γ = Euler–Mascheroni)
#     DSR = Φ( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1)/4 * SR²) )      (kurt = kurtosis THÔ, chuẩn = 3)
# - PBO: Bailey, Borwein, López de Prado, Zhu (2017) — CSCV: chia T ngày thành S khối liền kề, mọi C(S, S/2) cách chọn nửa IS;
#   alpha tốt nhất IS có hạng OOS tương đối ω; logit = ln(ω / (1 - ω)); PBO = P(logit <= 0).
# - Lân cận: ±1 bước trên lưới của TỪNG khoá của không gian tham số (khoá chỉ có 1 giá trị thì không có lân cận).
# - N hiệu dụng (effective_trials): các lần thử gần trùng nhau (lân cận lưới, biến thể regime) không phải phép thử độc lập. Theo López de Prado
#   (gom cụm các chiến lược tương quan), N dùng cho SR0 = số cụm (tương quan lợi suất ngày > rho) trong mẫu top-K, phóng theo tỉ lệ ra cả N.
# ══════════════════════════════════════════════════════════════════════════

EULER_GAMMA = 0.5772156649015329
_N01 = NormalDist()


def norm_cdf(z: float) -> float:
    return _N01.cdf(z)


def norm_ppf(p: float) -> float:
    return _N01.inv_cdf(p)


# ── DSR ─────────────────────────────────────────────────────────────────────
def expected_max_sr(n_trials: int, sr_var: float) -> float:
    """SR0: kỳ vọng Sharpe lớn nhất của n_trials lần thử độc lập có phương sai Sharpe sr_var (theo ngày). n <= 1 -> 0."""
    if n_trials <= 1 or not sr_var > 0:
        return 0.0
    g = EULER_GAMMA
    return math.sqrt(sr_var) * ((1.0 - g) * norm_ppf(1.0 - 1.0 / n_trials) + g * norm_ppf(1.0 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(sr: float, n_days: int, skew: float, kurt: float, n_trials: int, sr_var: float) -> Dict[str, float]:
    """DSR = xác suất Sharpe thật > SR0 sau khi hiệu chỉnh số lần thử, độ lệch, kurtosis, độ dài mẫu. -> {dsr, sr0}."""
    sr0 = expected_max_sr(n_trials, sr_var)
    if n_days < 3:
        return {"dsr": 0.0, "sr0": sr0}
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr0) * math.sqrt(n_days - 1) / denom
    return {"dsr": norm_cdf(z), "sr0": sr0}


def trial_sr_variance(srs: Sequence[float]) -> float:
    """Phương sai (ddof=1) của Sharpe theo ngày qua các alpha đã thử của một chiến lược; < 2 alpha -> 0."""
    a = np.asarray([x for x in srs if x is not None and math.isfinite(x)], dtype=float)
    return float(a.var(ddof=1)) if a.size >= 2 else 0.0


# ── PBO (CSCV) ──────────────────────────────────────────────────────────────
def pbo_cscv(matrix: np.ndarray, n_blocks: int = 16, chunk: int = 1024) -> Dict[str, Any]:
    """matrix (T ngày × N alpha) lợi suất ngày -> {"pbo", "n_splits", "n_alphas", "n_days", "logit_median"}.
    T bị cắt phần đầu cho chia hết n_blocks. Hiệu năng = Sharpe (mean/std) trên tập ngày; alpha phẳng (std = 0) có Sharpe 0.
    Hạng OOS của alpha tốt nhất IS: hạng trung bình khi hoà; ω = hạng / (N + 1). Không đủ dữ liệu (N < 2 hoặc T < 2*n_blocks) -> pbo None."""
    M = np.asarray(matrix, dtype=float)
    T, N = M.shape
    if N < 2 or T < 2 * n_blocks or n_blocks % 2:
        return {"pbo": None, "n_splits": 0, "n_alphas": int(N), "n_days": int(T), "logit_median": None}
    bs = T // n_blocks
    M = M[T - bs * n_blocks:]
    blocks = M.reshape(n_blocks, bs, N)
    s1 = blocks.sum(axis=1)                 # (S, N)
    s2 = (blocks ** 2).sum(axis=1)
    tot1, tot2 = s1.sum(axis=0), s2.sum(axis=0)
    combos = np.array(list(itertools.combinations(range(n_blocks), n_blocks // 2)), dtype=np.int64)   # (C, S/2)
    C = combos.shape[0]
    ind = np.zeros((C, n_blocks), dtype=float)
    ind[np.arange(C)[:, None], combos] = 1.0
    n_is = bs * (n_blocks // 2)
    n_oos = bs * n_blocks - n_is

    def sharpe(sum1, sum2, n):
        mean = sum1 / n
        var = np.maximum(sum2 / n - mean ** 2, 0.0) * n / (n - 1)
        sd = np.sqrt(var)
        return np.where(sd > 1e-12, mean / np.where(sd > 1e-12, sd, 1.0), 0.0)

    logits: List[np.ndarray] = []
    for lo in range(0, C, chunk):
        w = ind[lo:lo + chunk]
        sr_is = sharpe(w @ s1, w @ s2, n_is)
        sr_oos = sharpe(tot1 - w @ s1, tot2 - w @ s2, n_oos)
        best = np.argmax(sr_is, axis=1)
        ob = sr_oos[np.arange(len(w)), best][:, None]
        less = (sr_oos < ob).sum(axis=1)
        eq = (sr_oos == ob).sum(axis=1)
        rank = less + (eq + 1) / 2.0         # hạng trung bình (1..N)
        omega = rank / (N + 1.0)
        logits.append(np.log(omega / (1.0 - omega)))
    lg = np.concatenate(logits)
    return {"pbo": float((lg <= 0).mean()), "n_splits": int(C), "n_alphas": int(N), "n_days": int(bs * n_blocks),
            "logit_median": float(np.median(lg))}


def align_daily(series: List[Dict[str, Any]], n_max: Optional[int] = None) -> np.ndarray:
    """series = [{"start": "YYYY-MM-DD", "rets": [...]}, ...] (mỗi alpha một chuỗi) -> ma trận (ngày × alpha) căn theo NGÀY lịch,
    ngày thiếu = 0 (vốn đứng yên). Dùng cho PBO khi các alpha có độ dài/ngày bắt đầu hơi khác nhau."""
    import pandas as pd
    if not series:
        return np.zeros((0, 0))
    starts = [pd.Timestamp(s["start"]) for s in series]
    ends = [st + pd.Timedelta(days=len(s["rets"])) for st, s in zip(starts, series)]
    lo, hi = min(starts), max(ends)
    T = int((hi - lo).days)
    M = np.zeros((T, len(series)))
    for j, (st, s) in enumerate(zip(starts, series)):
        off = int((st - lo).days)
        M[off:off + len(s["rets"]), j] = s["rets"]
    return M


EFF_RHO = 0.7   # hai lần thử tương quan lợi suất ngày > 0,7 -> cùng một cụm (không độc lập)


def effective_trials(M: np.ndarray, n_total: int, rho: float = EFF_RHO) -> int:
    """N hiệu dụng: gom cụm tham lam các cột của M (ngày × alpha, thứ tự = xếp hạng giảm dần) — alpha vào cụm có đại diện tương quan > rho,
    không thì mở cụm mới; N_eff = round(số cụm / số cột × n_total), trong [1, n_total]. Mẫu rỗng -> n_total (bảo thủ)."""
    if M.size == 0 or M.shape[1] < 2:
        return max(1, int(n_total))
    M = M[:, M.std(axis=0) > 0]
    k = M.shape[1]
    if k < 2:
        return max(1, int(n_total))
    C = np.corrcoef(M.T)
    reps: List[int] = []
    for j in range(k):
        if not any(C[j, r] > rho for r in reps):
            reps.append(j)
    return int(min(n_total, max(1, round(len(reps) / k * n_total))))


# ── Lân cận tham số ─────────────────────────────────────────────────────────
def neighbours(space: Dict[str, Sequence[Any]], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Các điểm cách `params` đúng 1 bước lưới trên đúng 1 khoá (tối đa 2 mỗi khoá). Khoá có giá trị lệch lưới -> không có lân cận khoá đó."""
    out = []
    for key in sorted(space):
        vals = list(space[key])
        if key not in params or params[key] not in vals:
            continue
        i = vals.index(params[key])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                out.append({**params, key: vals[j]})
    return out


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/metrics/diagnose.py
#
# Chẩn đoán chi tiết từ kết quả chạy backtest (B3 — lớp thực tế, không dùng LLM).
#
# QUY TẮC: mọi con số đều tính từ dữ liệu của CHÍNH lần chạy (đường vốn, lệnh, giá nến, chương trình đã biên dịch). Không có hằng số giả/ước lượng;
# thiếu đầu vào (không có benchmark, không có giá thị trường, không có nến) thì mục tương ứng ghi `available: False` / None, KHÔNG bịa số.
#
# Các nhóm:
# 1. signal_activity: số lệnh, thời gian nắm giữ, lý do thoát THẬT (close_reason của engine), ngày có vị thế, exposure trung bình, thời gian theo từng coin.
# 2. binding_condition: với mỗi quy tắc vào lệnh dạng A & B & C: % nến đúng của từng điều kiện và % nến mà nó là điều kiện DUY NHẤT sai (điều kiện chặn); quy tắc một vế chỉ có % nến đúng (binding = None).
# 3. market_comparison: so với benchmark "luôn long" chạy qua CÙNG đường engine (beta, tương quan, CAGR, MDD, excess CAGR) — benchmark do custom_run chạy.
# 4. train_vs_test: Sharpe, CAGR, MDD và mức suy giảm ngoài mẫu (OOS decay).
# 5. pnl_structure: win rate, payoff, top 5 lệnh, chuỗi thua, fee drag, phân bổ coin & năm.
# 6. regime_analysis: chế độ thị trường theo giá BTC (hoặc chỉ số rổ nếu không có BTC) trên/dưới SMA200 nhân quả: số ngày, lãi theo ngày, lệnh vào, thời gian có vị thế.
# ══════════════════════════════════════════════════════════════════════════

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
    from backend.metrics.metrics import cagr_pct
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
    from backend.core.signal import Call, Logic
    if isinstance(node, Logic) and node.op == "&":
        return _conjuncts(node.a) + _conjuncts(node.b)
    if isinstance(node, Call) and not node.is_feature and node.spec.name == "and_":
        return _conjuncts(node.bound["a"]) + _conjuncts(node.bound["b"])
    return [node]


def compute_binding_condition(program: Optional[Program], frames: Optional[Dict[str, pd.DataFrame]], start: int, end: int) -> Dict[str, Any]:
    """Với mỗi quy tắc VÀO lệnh (set_positions mức != 0) có >= 1 vế (A & B & C; một vế chỉ tính pct_true, không có binding): tính từng vế trên nến khung chiến lược của từng tài sản (chỉ báo tính từ đầu lịch sử như engine;
    đếm nến có open_time trong [start, end)). Mỗi vế: pct_true, only_false_bars (nến mà nó là vế DUY NHẤT sai = vế chặn), share_of_near_miss_pct = only_false / (tổng nến chỉ sai
    đúng một vế). `binding` = vế có phần chặn lớn nhất. Bỏ qua điều kiện giờ vào lệnh (position_open_times/ranges)."""
    from backend.core.signal import expr_to_vi
    from backend.core.signal import Ctx
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


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/analytics/insights.py
#
# Bộ quy tắc sinh nhận xét và chẩn đoán chiến lược (B4 — lớp thực tế, không dùng LLM).
#
# QUY TẮC: mỗi câu nhận xét phải truy được về MỘT con số đo thật trong `diagnostics` (core/metrics/diagnose.py) của chính lần chạy; `evidence` ghi đúng các giá trị đã dùng
# để kích hoạt và để viết câu (không số giả, không ngưỡng ngầm trên trường không tồn tại). Đầu vào thiếu (None / available False) -> quy tắc không kích hoạt.
#
# Mỗi quy tắc: id, severity ("warning" | "good" | "info"), hàm (diag, metrics) -> (message_vi, evidence) hoặc None.
# ══════════════════════════════════════════════════════════════════════════

BETA_DRIVEN_ID = "beta_driven"   # nguồn duy nhất: checklist của user_alphas.evaluate_checklist và PushToAlphaModal.jsx (cùng chuỗi) dựa vào id này
SEVERITY_ORDER = {"warning": 0, "good": 1, "info": 2}
Result = Optional[Tuple[str, Dict[str, Any]]]


class InsightRule:
    def __init__(self, rule_id: str, severity: str, builder: Callable[[Dict[str, Any], Dict[str, Any]], Result]):
        self.id = rule_id
        self.severity = severity
        self.builder = builder


RULES: List[InsightRule] = []


def register_rule(rule_id: str, severity: str):
    def decorator(fn):
        RULES.append(InsightRule(rule_id, severity, fn))
        return fn
    return decorator


def _g(d: Dict[str, Any], *path, default=None):
    """d[path0][path1]... an toàn; thiếu / None -> default."""
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or cur.get(p) is None:
            return default
        cur = cur[p]
    return cur


def _nums(*vals) -> bool:
    return all(isinstance(v, (int, float)) for v in vals)


def _exit_share_closed(d: Dict[str, Any], cat: str) -> Optional[Tuple[float, int, int]]:
    """(% lệnh ĐÃ ĐÓNG thoát vì `cat`, số lệnh, số lệnh đã đóng). Lệnh đang mở cuối kỳ không tính vào mẫu số."""
    sig = d.get("signal_activity", {})
    closed = sig.get("closed_trades") or 0
    if closed <= 0:
        return None
    n = (sig.get("exit_reason_counts") or {}).get(cat, 0)
    return n / closed * 100.0, n, closed


# ─── Quy tắc ────────────────────────────────────────────────────────────────

@register_rule(BETA_DRIVEN_ID, "warning")
def rule_beta_driven(d, m):
    mkt = d.get("market_comparison", {})
    if not mkt.get("available"):
        return None
    beta, corr, s_cagr, m_cagr, excess = (mkt.get(k) for k in ("beta", "correlation", "strategy_cagr", "market_cagr", "excess_cagr"))
    if _nums(beta, corr, s_cagr, m_cagr, excess) and corr >= 0.9 and beta >= 0.8:
        return (f"Kết quả bám sát nhịp thị trường: beta {beta:.2f} và tương quan {corr:.2f} với benchmark luôn long; CAGR chiến lược {s_cagr:.1f}%/năm so với "
                f"{m_cagr:.1f}%/năm của benchmark (chênh {excess:+.1f} điểm %/năm).",
                {"beta": beta, "correlation": corr, "strategy_cagr": s_cagr, "market_cagr": m_cagr, "excess_cagr": excess})
    return None


@register_rule("overfit_gap", "warning")
def rule_overfit_gap(d, m):
    tr_s, te_s = _g(d, "train_vs_test", "train_sharpe"), _g(d, "train_vs_test", "test_sharpe")
    if _nums(tr_s, te_s) and tr_s >= 0.8 and te_s < 0.5 * tr_s:
        decay = (1.0 - te_s / tr_s) * 100.0
        return (f"Hiệu quả giảm mạnh ngoài mẫu (Sharpe train {tr_s:.2f} → test {te_s:.2f}, suy giảm {decay:.0f}%); có dấu hiệu quá khớp dữ liệu (overfitting).",
                {"train_sharpe": tr_s, "test_sharpe": te_s, "decay_pct": round(decay, 1)})
    return None


@register_rule("fee_drag", "warning")
def rule_fee_drag(d, m):
    pnl = d.get("pnl_structure", {})
    drag = pnl.get("fee_drag_pct")
    if _nums(drag) and drag >= 20.0:
        return (f"Phí giao dịch ăn {drag:.1f}% lãi gộp trước phí ({pnl.get('fees_usd'):,.0f} USD phí trên {pnl.get('gross_pnl_before_fees_usd'):,.0f} USD lãi gộp); "
                "tần suất ra vào lệnh đang làm mòn đáng kể lợi nhuận ròng.",
                {"fee_drag_pct": drag, "fees_usd": pnl.get("fees_usd"), "gross_pnl_before_fees_usd": pnl.get("gross_pnl_before_fees_usd")})
    return None


@register_rule("tail_dependent", "warning")
def rule_tail_dependent(d, m):
    pnl = d.get("pnl_structure", {})
    top5, closed = pnl.get("top5_profit_pct"), pnl.get("closed_trades", 0)
    if _nums(top5) and closed >= 12 and top5 >= 50.0:
        return (f"Lợi nhuận phụ thuộc lớn vào vài cơ hội cá biệt (5 lệnh thắng lớn nhất đóng góp {top5:.1f}% tổng lãi gộp của {closed} lệnh đã đóng).",
                {"top5_profit_pct": top5, "closed_trades": closed})
    return None


@register_rule("rarely_in_market", "info")
def rule_rarely_in_market(d, m):
    sig = d.get("signal_activity", {})
    days = sig.get("days_in_market_pct")
    if _nums(days) and days < 10.0 and sig.get("total_trades", 0) > 0:
        return (f"Chiến lược hiếm khi có vị thế: chỉ {days:.1f}% số ngày có ít nhất một vị thế mở (exposure trung bình {sig.get('avg_exposure_pct')}% vốn, "
                f"{sig.get('total_trades')} lệnh).",
                {"days_in_market_pct": days, "avg_exposure_pct": sig.get("avg_exposure_pct"), "total_trades": sig.get("total_trades")})
    return None


@register_rule("always_in", "info")
def rule_always_in(d, m):
    sig = d.get("signal_activity", {})
    days, expo = sig.get("days_in_market_pct"), sig.get("avg_exposure_pct")
    if _nums(days) and days >= 95.0:
        tail = f", exposure trung bình {expo:.1f}% vốn" if _nums(expo) else ""
        return (f"Chiến lược gần như luôn có vị thế ({days:.1f}% số ngày có ít nhất một vị thế mở{tail}).",
                {"days_in_market_pct": days, "avg_exposure_pct": expo})
    return None


@register_rule("bear_loss", "warning")
def rule_bear_loss(d, m):
    reg = d.get("regime_analysis", {})
    if not reg.get("available"):
        return None
    bear, bull, cap = reg.get("bear", {}), reg.get("bull", {}), reg.get("initial_capital")
    bp, bu, bd = bear.get("pnl_usd"), bull.get("pnl_usd"), bear.get("days", 0)
    if _nums(bp, bu, cap) and bd >= 30 and bp < 0 and bu > 0 and abs(bp) >= 0.05 * cap:
        return (f"Thua lỗ tập trung khi thị trường dưới SMA200: {bp:,.0f} USD trong {bd} ngày giá {reg.get('market')} dưới SMA{reg.get('sma_days')} "
                f"(trong khi {bull.get('days')} ngày trên SMA200 lãi {bu:,.0f} USD).",
                {"bear_pnl_usd": bp, "bear_days": bd, "bull_pnl_usd": bu, "bull_days": bull.get("days"), "initial_capital": cap,
                 "benchmark_bear_pnl_usd": bear.get("benchmark_pnl_usd"), "market": reg.get("market")})
    return None


@register_rule("positive_bear_performance", "good")
def rule_positive_bear(d, m):
    reg = d.get("regime_analysis", {})
    if not reg.get("available"):
        return None
    bear = reg.get("bear", {})
    bp, bd, mkt_ret, inm = bear.get("pnl_usd"), bear.get("days", 0), bear.get("market_return_pct"), bear.get("days_in_market_pct")
    if _nums(bp, mkt_ret, inm) and bd >= 30 and bp > 0 and mkt_ret < 0 and inm >= 10.0:
        return (f"Có lãi khi thị trường yếu: +{bp:,.0f} USD trong {bd} ngày giá {reg.get('market')} dưới SMA{reg.get('sma_days')}, lúc thị trường giảm "
                f"{mkt_ret:.1f}% (chiến lược có vị thế {inm:.0f}% số ngày đó).",
                {"bear_pnl_usd": bp, "bear_days": bd, "bear_market_return_pct": mkt_ret, "bear_days_in_market_pct": inm, "market": reg.get("market")})
    return None


@register_rule("high_win_rate", "good")
def rule_high_win_rate(d, m):
    pnl = d.get("pnl_structure", {})
    wr, payoff, closed = pnl.get("win_rate"), pnl.get("payoff"), pnl.get("closed_trades", 0)
    if _nums(wr) and wr >= 65.0 and closed >= 10:
        tail = f", tỷ lệ lãi/lỗ trung bình (payoff) {payoff:.2f}" if _nums(payoff) else ""
        return (f"Tỷ lệ lệnh thắng cao ({wr:.1f}% trên {closed} lệnh đã đóng{tail}).", {"win_rate": wr, "payoff": payoff, "closed_trades": closed})
    return None


@register_rule("low_win_rate_trend", "info")
def rule_trend_payoff(d, m):
    pnl = d.get("pnl_structure", {})
    wr, payoff, closed = pnl.get("win_rate"), pnl.get("payoff"), pnl.get("closed_trades", 0)
    if _nums(wr, payoff) and wr < 40.0 and payoff >= 2.0 and closed >= 10:
        return (f"Đặc trưng bắt sóng xu hướng lớn: tỷ lệ thắng thấp ({wr:.1f}%) nhưng payoff cao ({payoff:.2f}) trên {closed} lệnh đã đóng.",
                {"win_rate": wr, "payoff": payoff, "closed_trades": closed})
    return None


@register_rule("drawdown_heavy", "warning")
def rule_drawdown_heavy(d, m):
    mkt = d.get("market_comparison", {})
    mdd, m_mdd = mkt.get("strategy_mdd"), mkt.get("market_mdd")
    if _nums(mdd) and mdd >= 35.0:
        tail = f" (benchmark luôn long: {m_mdd:.1f}%)" if _nums(m_mdd) else ""
        return (f"Mức sụt giảm tối đa theo ngày khá sâu ({mdd:.1f}%){tail}; cần cơ chế cắt lỗ hoặc kiểm soát tỷ trọng vốn.",
                {"max_drawdown_pct": mdd, "market_mdd_pct": m_mdd})
    return None


@register_rule("high_consecutive_losses", "warning")
def rule_consec_losses(d, m):
    losses = _g(d, "pnl_structure", "max_consecutive_losses", default=0)
    if losses >= 6:
        return (f"Chuỗi thua liên tiếp dài nhất lên tới {losses} lệnh đã đóng; cần chuẩn bị chịu đựng chuỗi thua này.", {"max_consecutive_losses": losses})
    return None


@register_rule("low_trade_count", "warning")
def rule_low_trade_count(d, m):
    sig = d.get("signal_activity", {})
    total = sig.get("total_trades", 0)
    if 0 < total < 20:
        return (f"Số lệnh chưa nhiều ({total} lệnh: {sig.get('closed_trades')} đã đóng, {sig.get('open_trades')} đang mở); mẫu thống kê có thể chưa đủ lớn để loại trừ may rủi.",
                {"total_trades": total, "closed_trades": sig.get("closed_trades"), "open_trades": sig.get("open_trades")})
    return None


@register_rule("strong_alpha", "good")
def rule_strong_alpha(d, m):
    mkt = d.get("market_comparison", {})
    if not mkt.get("available"):
        return None
    corr, excess, te_s = mkt.get("correlation"), mkt.get("excess_cagr"), _g(d, "train_vs_test", "test_sharpe")
    if _nums(corr, excess, te_s) and corr <= 0.65 and excess > 0 and te_s >= 0.9:
        return (f"Tín hiệu có tính độc lập với thị trường: tương quan với benchmark thấp ({corr:.2f}), CAGR vượt benchmark {excess:+.1f} điểm %/năm, Sharpe ngoài mẫu {te_s:.2f}.",
                {"correlation": corr, "excess_cagr": excess, "test_sharpe": te_s})
    return None


@register_rule("robust_oos", "good")
def rule_robust_oos(d, m):
    tst = d.get("train_vs_test", {})
    decay, te_s, tr_s = tst.get("sharpe_decay"), tst.get("test_sharpe"), tst.get("train_sharpe")
    if _nums(decay, te_s, tr_s) and decay >= 0.8 and te_s >= 1.0 and tr_s >= 1.0:
        return (f"Hiệu quả ngoài mẫu vững: Sharpe test {te_s:.2f} (giữ {decay * 100:.0f}% so với train {tr_s:.2f}).",
                {"train_sharpe": tr_s, "test_sharpe": te_s, "sharpe_decay": decay})
    return None


@register_rule("sl_dominant_exit", "warning")
def rule_sl_dominant(d, m):
    r = _exit_share_closed(d, "stop_loss")
    if r and r[2] >= 10 and r[0] >= 40.0:
        return (f"{r[0]:.1f}% lệnh đã đóng ({r[1]}/{r[2]}) thoát bằng Stop-Loss thật của engine; cần xem lại điều kiện vào lệnh hoặc khoảng dừng lỗ.",
                {"stop_loss_pct_of_closed": round(r[0], 1), "stop_loss_trades": r[1], "closed_trades": r[2]})
    return None


@register_rule("tp_dominant_exit", "good")
def rule_tp_dominant(d, m):
    r = _exit_share_closed(d, "take_profit")
    if r and r[2] >= 10 and r[0] >= 45.0:
        return (f"{r[0]:.1f}% lệnh đã đóng ({r[1]}/{r[2]}) chạm Take-Profit.",
                {"take_profit_pct_of_closed": round(r[0], 1), "take_profit_trades": r[1], "closed_trades": r[2]})
    return None


@register_rule("kill_switch_hit", "warning")
def rule_kill_switch(d, m):
    n = _g(d, "signal_activity", "exit_reason_counts", "kill_switch", default=0)
    if n > 0:
        return (f"Kill-switch danh mục đã đóng {n} vị thế (vốn sụt tới ngưỡng dừng giao dịch).", {"kill_switch_trades": n})
    return None


@register_rule("negative_excess", "warning")
def rule_negative_excess(d, m):
    mkt = d.get("market_comparison", {})
    excess, s_cagr, m_cagr = mkt.get("excess_cagr"), mkt.get("strategy_cagr"), mkt.get("market_cagr")
    if mkt.get("available") and _nums(excess, s_cagr, m_cagr) and excess < -5.0:
        return (f"Kém hơn việc nắm giữ thụ động: CAGR {s_cagr:.1f}%/năm so với {m_cagr:.1f}%/năm của benchmark luôn long (chênh {excess:.1f} điểm %/năm).",
                {"excess_cagr": excess, "strategy_cagr": s_cagr, "market_cagr": m_cagr})
    return None


@register_rule("concentrated_coin", "warning")
def rule_concentrated_coin(d, m):
    by_coin = _g(d, "pnl_structure", "by_coin", default={})
    if len(by_coin) > 1:
        total = sum(v for v in by_coin.values() if v > 0)
        if total > 0:
            top_sym, top_val = max(by_coin.items(), key=lambda x: x[1])
            share = top_val / total * 100.0
            if share >= 65.0:
                return (f"Lãi tập trung vào {top_sym} ({share:.1f}% tổng lãi các coin có lãi, {top_val:,.0f} USD, gồm lệnh đang mở theo giá cuối).",
                        {"top_coin": top_sym, "share_pct": round(share, 1), "top_coin_pnl_usd": top_val})
    return None


@register_rule("short_profitable", "good")
def rule_short_profitable(d, m):
    pnl = d.get("pnl_structure", {})
    n, p = pnl.get("short_closed_trades", 0), pnl.get("short_pnl_usd")
    if n >= 5 and _nums(p) and p > 0:
        return (f"Chiều Short có lãi: {p:,.0f} USD từ {n} lệnh short đã đóng.", {"short_closed_trades": n, "short_pnl_usd": p})
    return None


@register_rule("short_losing", "warning")
def rule_short_losing(d, m):
    pnl = d.get("pnl_structure", {})
    n, p = pnl.get("short_closed_trades", 0), pnl.get("short_pnl_usd")
    if n >= 5 and _nums(p) and p < 0:
        return (f"Chiều Short đang lỗ: {p:,.0f} USD từ {n} lệnh short đã đóng.", {"short_closed_trades": n, "short_pnl_usd": p})
    return None


@register_rule("only_long_bias", "info")
def rule_only_long(d, m):
    sig = d.get("signal_activity", {})
    shorts, longs = sig.get("short_trades", 0), sig.get("long_trades", 0)
    if shorts == 0 and longs > 0:
        return (f"Chiến lược chỉ tham gia chiều Long ({longs} lệnh, 0 lệnh short).", {"long_trades": longs, "short_trades": shorts})
    return None


@register_rule("binding_condition", "info")
def rule_binding_condition(d, m):
    """Vế duy nhất chặn >= 50% số nến 'suýt đủ điều kiện' (đúng mọi vế trừ một) của quy tắc vào lệnh có >= 3 vế A & B & C."""
    bc = d.get("binding_condition", {})
    if not bc.get("available"):
        return None
    best = None
    for r in bc.get("rules", []):
        b = r.get("binding")
        if r.get("n_conjuncts", 0) >= 3 and b and r.get("near_miss_bars", 0) >= 20 and _nums(b.get("share_of_near_miss_pct")) and b["share_of_near_miss_pct"] >= 50.0:
            if best is None or b["share_of_near_miss_pct"] > best[1]["share_of_near_miss_pct"]:
                best = (r, b)
    if best is None:
        return None
    r, b = best
    return (f"Điều kiện vào lệnh \"{b['text_vi']}\" (quy tắc dòng {r['line']}, {r['n_conjuncts']} vế) là vế DUY NHẤT sai trong {b['share_of_near_miss_pct']:.0f}% số nến suýt đủ điều kiện "
            f"({b['only_false_bars']}/{r['near_miss_bars']} nến); vế này chỉ đúng {b['pct_true']:.1f}% số nến.",
            {"rule_index": r["index"], "line": r["line"], "side": r["side"], "n_conjuncts": r["n_conjuncts"], "conjunct": b["text_vi"], "conjunct_index": b["index"],
             "pct_true": b["pct_true"], "only_false_bars": b["only_false_bars"], "near_miss_bars": r["near_miss_bars"], "all_true_bars": r.get("all_true_bars"),
             "share_of_near_miss_pct": b["share_of_near_miss_pct"]})


def generate_insights(diagnostics: Dict[str, Any], metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chạy toàn bộ bộ quy tắc, sắp theo mức độ: warning -> good -> info (giữ thứ tự khai báo trong cùng mức)."""
    results: List[Dict[str, Any]] = []
    for rule in RULES:
        try:
            out = rule.builder(diagnostics, metrics)
        except Exception:      # noqa: BLE001 — một quy tắc lỗi không làm mất các nhận xét khác
            continue
        if out is not None:
            message, evidence = out
            results.append({"id": rule.id, "severity": rule.severity, "message_vi": message, "evidence": evidence})
    results.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 99))
    return results
