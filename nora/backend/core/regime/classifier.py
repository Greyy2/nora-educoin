"""Regime thị trường theo phút — causal, cùng bộ máy căn khung với tín hiệu (chỉ nến 1h/4h ĐÃ ĐÓNG), dùng chung cho backtest / WFA / phễu /
tín hiệu thị trường / live.

Đặc trưng (cột kernel, core/signals/kernels.py):
  4h er_20 (độ hiệu quả xu hướng), 4h adx_14 (độ mạnh), 4h ema_50 / ema_200 (chiều), 1h roc_24 (lợi suất 24h, %), 1h roc_1 (nến 1h cuối, %),
  1h bbwp_20_2_720 (phân vị độ rộng Bollinger trong 30 ngày 1h, 0..100).
Trạng thái thô (ưu tiên từ trên xuống):
  CRASH  roc_24 <= -crash_24h_pct  hoặc  roc_1 <= -shock_1h_pct      SURGE  roc_24 >= surge_24h_pct  hoặc  roc_1 >= shock_1h_pct
  VOL_EXPANSION  bbwp >= vol_pct
  TREND_UP / TREND_DOWN  er >= er_min và adx >= adx_min, chiều theo ema_50 so với ema_200
  RANGE  còn lại;  UNKNOWN  thiếu đặc trưng (đang khởi động)
Chống nhảy: trạng thái thường phải giữ liên tục >= confirm_min phút mới được nhận; CRASH/SURGE nhận ngay và giữ ít nhất shock_hold_min phút
kể từ lần cuối còn tín hiệu sốc.
"""
from typing import Any, Callable, Dict, Optional, Set, Tuple

import numpy as np

UNKNOWN, RANGE, TREND_UP, TREND_DOWN, VOL_EXPANSION, SURGE, CRASH = range(7)
NAMES = ("UNKNOWN", "RANGE", "TREND_UP", "TREND_DOWN", "VOL_EXPANSION", "SURGE", "CRASH")
LABEL_VI = {"UNKNOWN": "Chưa đủ dữ liệu", "RANGE": "Đi ngang", "TREND_UP": "Xu hướng tăng", "TREND_DOWN": "Xu hướng giảm",
            "VOL_EXPANSION": "Biến động bùng nổ", "SURGE": "Tăng thẳng đứng", "CRASH": "Sập mạnh"}
CODE = {n: i for i, n in enumerate(NAMES)}

DEFAULTS: Dict[str, float] = {"er_min": 0.30, "adx_min": 20.0, "vol_pct": 90.0, "crash_24h_pct": 12.0, "surge_24h_pct": 12.0,
                              "shock_1h_pct": 5.0, "confirm_min": 180, "shock_hold_min": 360}

# (khung, cột kernel, độ trễ) — thêm vào refs của engine khi có chiến lược bật regime / khi cần hiển thị regime
REFS: Dict[str, Set[Tuple[str, int]]] = {
    "4h": {("er_20", 0), ("adx_14", 0), ("ema_50", 0), ("ema_200", 0)},
    "1h": {("roc_24", 0), ("roc_1", 0), ("bbwp_20_2_720", 0)},
}
MINUTE = 60_000


def raw_states(get: Callable[[str, str], np.ndarray], n: int, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Trạng thái thô từng phút từ các cột đặc trưng đã căn (get(frame, column) -> mảng float độ dài n, NaN = chưa có)."""
    c = {**DEFAULTS, **(cfg or {})}
    er, adx = get("4h", "er_20"), get("4h", "adx_14")
    e50, e200 = get("4h", "ema_50"), get("4h", "ema_200")
    r24, r1, bw = get("1h", "roc_24"), get("1h", "roc_1"), get("1h", "bbwp_20_2_720")
    out = np.full(n, UNKNOWN, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        trend_ok = np.isfinite(er) & np.isfinite(adx) & np.isfinite(e50) & np.isfinite(e200)
        out[trend_ok] = RANGE
        strong = trend_ok & (er >= c["er_min"]) & (adx >= c["adx_min"])
        out[strong & (e50 > e200)] = TREND_UP
        out[strong & (e50 < e200)] = TREND_DOWN
        out[np.isfinite(bw) & (bw >= c["vol_pct"])] = VOL_EXPANSION
        surge = (np.isfinite(r24) & (r24 >= c["surge_24h_pct"])) | (np.isfinite(r1) & (r1 >= c["shock_1h_pct"]))
        crash = (np.isfinite(r24) & (r24 <= -c["crash_24h_pct"])) | (np.isfinite(r1) & (r1 <= -c["shock_1h_pct"]))
    out[surge] = SURGE
    out[crash] = CRASH
    return out


def smooth(raw: np.ndarray, t: np.ndarray, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Áp luật chống nhảy lên chuỗi thô (t = open_time từng phút, tăng dần). Chỉ duyệt các điểm đổi trạng thái thô (vài nghìn) nên nhanh."""
    c = {**DEFAULTS, **(cfg or {})}
    n = len(raw)
    out = np.empty(n, dtype=np.int8)
    if n == 0:
        return out
    confirm = int(c["confirm_min"]) * MINUTE
    hold = int(c["shock_hold_min"]) * MINUTE
    cur = int(raw[0])
    shock_until = -1
    pending, pending_since = None, None
    cuts = np.flatnonzero(np.diff(raw.astype(np.int16))) + 1
    bounds = np.concatenate(([0], cuts, [n]))
    for s, e in zip(bounds[:-1], bounds[1:]):
        r = int(raw[s])
        if r in (SURGE, CRASH):
            cur, pending = r, None
            out[s:e] = r
            shock_until = int(t[e - 1]) + hold
            continue
        # đoạn [s, e) có trạng thái thô thường r
        i = s
        if cur in (SURGE, CRASH) and shock_until >= int(t[s]):      # còn trong thời gian giữ sốc
            j = int(np.searchsorted(t, shock_until, side="right", sorter=None))
            j = min(max(j, s), e)
            out[s:j] = cur
            i = j
            if i >= e:
                continue
            cur, pending = r, None          # hết thời gian giữ sốc: nhận ngay trạng thái nền (đã ổn định trong suốt thời gian giữ)
            out[i:e] = cur
            continue
        if cur in (SURGE, CRASH):           # khoảng trống dữ liệu vượt quá thời gian giữ
            cur, pending = r, None
            out[i:e] = cur
            continue
        if r == cur:
            out[i:e] = cur
            pending = None
            continue
        if pending != r:
            pending, pending_since = r, int(t[i])
        k = int(np.searchsorted(t, pending_since + confirm, side="left"))
        k = min(max(k, i), e)
        out[i:k] = cur
        if k < e:
            cur, pending = r, None
            out[k:e] = cur
    return out


def classify(get: Callable[[str, str], np.ndarray], t: np.ndarray, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Mã regime (int8, xem NAMES) từng phút."""
    return smooth(raw_states(get, len(t), cfg), np.asarray(t, dtype=np.int64), cfg)


def masks_for(strategy: Dict[str, Any], side: str, labels: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """(cho phép vào lệnh, cầu chì thoát) theo cấu hình strategy["regime"] = {"allowed": [tên...], "fuse": bool}.
    Cầu chì: LONG gặp CRASH / SHORT gặp SURGE -> tín hiệu thoát (đóng ở nến sau), cắt cả thang DCA trước khi bị thanh lý."""
    rg = strategy.get("regime") or {}
    if not rg:
        return None, None
    allowed = np.isin(labels, [CODE[x] for x in rg.get("allowed") or NAMES])
    fuse = None
    if rg.get("fuse", True):
        fuse = labels == (CRASH if side == "LONG" else SURGE)
    return allowed, fuse


def series(symbol: str, start: int, end: int, venue: str = "cex", cfg: Optional[Dict[str, float]] = None,
           base_frame: str = "1m") -> Dict[str, np.ndarray]:
    """Nhãn regime từng nến khung chạy của một tài sản qua đúng đường dữ liệu của engine (nạp + căn khung + warmup theo khung).
    -> {t, close, real (nến thật, không điền), raw, labels}."""
    from backend.core.backtest.portfolio import PortfolioEngine
    probe = {"id": "_regime_probe", "side": "LONG", "position": {"market": "perp"},
             "tree": [[[{"frame": "1h", "column": "roc_1", "index": 0}, ">", 1e18]]]}
    pe = PortfolioEngine([symbol], [probe], start, end, trade_start_ts=start, venue=venue, use_cache=False, base_frame=base_frame)
    eng, _ = pe._make_trackers(symbol, pe.ledger)
    eng.extra_refs = REFS
    eng.load_data()
    df1, cols = eng._build_matrix()
    n = len(df1)
    t = df1["open_time"].to_numpy(dtype="int64")

    def get(fr, c):
        return cols.get(f"{fr}|{c}", np.full(n, np.nan))
    raw = raw_states(get, n, cfg)
    return {"t": t, "close": df1["close"].to_numpy(dtype="float64"), "real": df1["is_filled"].to_numpy() == 0,
            "raw": raw, "labels": smooth(raw, t, cfg)}
