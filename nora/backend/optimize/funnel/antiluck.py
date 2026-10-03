"""Chống ăn may (S2): Deflated Sharpe Ratio, PBO (CSCV), lân cận tham số + thống kê chuỗi lợi suất ngày.

- DSR: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio". Mọi Sharpe ở đây là Sharpe THEO NGÀY (không quy năm).
    SR0 = sqrt(V[SR_trials]) * ((1 - γ) * Φ^-1(1 - 1/N) + γ * Φ^-1(1 - 1/(N e)))       (kỳ vọng SR lớn nhất của N lần thử, γ = Euler–Mascheroni)
    DSR = Φ( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1)/4 * SR²) )      (kurt = kurtosis THÔ, chuẩn = 3)
- PBO: Bailey, Borwein, López de Prado, Zhu (2017) — CSCV: chia T ngày thành S khối liền kề, mọi C(S, S/2) cách chọn nửa IS;
  alpha tốt nhất IS có hạng OOS tương đối ω; logit = ln(ω / (1 - ω)); PBO = P(logit <= 0).
- Lân cận: ±1 bước trên lưới của TỪNG khoá của không gian tham số (khoá chỉ có 1 giá trị thì không có lân cận).
- N hiệu dụng (effective_trials): các lần thử gần trùng nhau (lân cận lưới, biến thể regime) không phải phép thử độc lập. Theo López de Prado
  (gom cụm các chiến lược tương quan), N dùng cho SR0 = số cụm (tương quan lợi suất ngày > rho) trong mẫu top-K, phóng theo tỉ lệ ra cả N.
"""
import itertools
import math
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

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
