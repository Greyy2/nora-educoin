"""Regime thị trường (P9.5): nhận diện trạng thái theo phút, causal (classifier) + học bảng regime ↔ chiến lược từ dữ liệu TRAIN (learn).

Hợp nhất NGUYÊN VĂN từ core/regime/{classifier,learn}.py (xem docs/bmad/p9_review_log.md, mục P9.5). Đường dẫn cũ là shim.
`core/regime/report.py` là job (run_job) -> ở lại cho P9.6.
"""
import math
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/regime/classifier.py
#
# Regime thị trường theo phút — causal, cùng bộ máy căn khung với tín hiệu (chỉ nến 1h/4h ĐÃ ĐÓNG), dùng chung cho backtest / WFA / phễu /
# tín hiệu thị trường / live.
#
# Đặc trưng (cột kernel, core/signals/kernels.py):
#   4h er_20 (độ hiệu quả xu hướng), 4h adx_14 (độ mạnh), 4h ema_50 / ema_200 (chiều), 1h roc_24 (lợi suất 24h, %), 1h roc_1 (nến 1h cuối, %),
#   1h bbwp_20_2_720 (phân vị độ rộng Bollinger trong 30 ngày 1h, 0..100).
# Trạng thái thô (ưu tiên từ trên xuống):
#   CRASH  roc_24 <= -crash_24h_pct  hoặc  roc_1 <= -shock_1h_pct      SURGE  roc_24 >= surge_24h_pct  hoặc  roc_1 >= shock_1h_pct
#   VOL_EXPANSION  bbwp >= vol_pct
#   TREND_UP / TREND_DOWN  er >= er_min và adx >= adx_min, chiều theo ema_50 so với ema_200
#   RANGE  còn lại;  UNKNOWN  thiếu đặc trưng (đang khởi động)
# Chống nhảy: trạng thái thường phải giữ liên tục >= confirm_min phút mới được nhận; CRASH/SURGE nhận ngay và giữ ít nhất shock_hold_min phút
# kể từ lần cuối còn tín hiệu sốc.
# ══════════════════════════════════════════════════════════════════════════

UNKNOWN, RANGE, TREND_UP, TREND_DOWN, VOL_EXPANSION, SURGE, CRASH = range(7)
NAMES = ("UNKNOWN", "RANGE", "TREND_UP", "TREND_DOWN", "VOL_EXPANSION", "SURGE", "CRASH")
LABEL_VI = {"UNKNOWN": "Chưa đủ dữ liệu", "RANGE": "Đi ngang", "TREND_UP": "Xu hướng tăng", "TREND_DOWN": "Xu hướng giảm",
            "VOL_EXPANSION": "Biến động bùng nổ", "SURGE": "Tăng thẳng đứng", "CRASH": "Sập mạnh"}
CODE = {n: i for i, n in enumerate(NAMES)}

DEFAULTS: Dict[str, Any] = {"er_min": 0.30, "adx_min": 20.0, "vol_pct": 90.0, "crash_24h_pct": 12.0, "surge_24h_pct": 12.0,
                            "shock_1h_pct": 5.0, "confirm_min": 180, "shock_hold_min": 360, "trend_frame": "4h"}
# Hồ sơ ngưỡng (P2 khắc phục): "slow" = mặc định (xu hướng 4h, xác nhận 180 phút); "fast" = xu hướng đo trên 1h, xác nhận 60 phút — nhãn đến sớm
# hơn, gần điểm phá vỡ mà chiến lược 15m/1h vào lệnh. Chọn hồ sơ bằng khoá "classifier" trong cấu hình regime của chiến lược.
PROFILES: Dict[str, Dict[str, Any]] = {"slow": dict(DEFAULTS), "fast": {**DEFAULTS, "trend_frame": "1h", "confirm_min": 60}}

# (khung, cột kernel, độ trễ) — thêm vào refs của engine khi có chiến lược bật regime / khi cần hiển thị regime
REFS: Dict[str, Set[Tuple[str, int]]] = {
    "4h": {("er_20", 0), ("adx_14", 0), ("ema_50", 0), ("ema_200", 0)},
    "1h": {("roc_24", 0), ("roc_1", 0), ("bbwp_20_2_720", 0), ("er_20", 0), ("adx_14", 0), ("ema_50", 0), ("ema_200", 0)},
}
MINUTE = 60_000


def profile_cfg(spec: Any) -> Optional[Dict[str, Any]]:
    """Khoá "classifier" của cấu hình regime -> cfg: None (mặc định) | tên hồ sơ trong PROFILES | dict ngưỡng."""
    if spec is None or isinstance(spec, dict):
        return spec
    if spec not in PROFILES:
        raise ValueError(f"hồ sơ regime không có: {spec!r} (có {sorted(PROFILES)})")
    return PROFILES[spec]


def raw_states(get: Callable[[str, str], np.ndarray], n: int, cfg: Optional[Dict[str, float]] = None) -> np.ndarray:
    """Trạng thái thô từng phút từ các cột đặc trưng đã căn (get(frame, column) -> mảng float độ dài n, NaN = chưa có)."""
    c = {**DEFAULTS, **(cfg or {})}
    tf = c["trend_frame"]
    er, adx = get(tf, "er_20"), get(tf, "adx_14")
    e50, e200 = get(tf, "ema_50"), get(tf, "ema_200")
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
    from backend.core.backtest import PortfolioEngine
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


# ══════════════════════════════════════════════════════════════════════════
# P9.5 — nguyên văn từ core/regime/learn.py
#
# Học bảng regime ↔ chiến lược từ dữ liệu TRAIN (WFA regime="learn") thay cho bảng tĩnh book.REGIME_MAP.
#
# Lý do (P2.4, báo cáo regime trên 8 tài sản): bảng tĩnh không khớp dữ liệu — vd. momentum_long lãi ở RANGE nhưng chỉ được phép TREND_UP/SURGE;
# sau CRASH giá thường hồi (lợi suất 24h tới +2,5%) nên cầu chì cắt LONG khi CRASH làm lỗ thêm. Bật bảng tĩnh làm sổ từ +29,6% thành −26%.
#
# Luật học (chỉ dùng lệnh của cửa sổ học, không nhìn test):
#   chặn regime R của chiến lược S  khi  số lệnh S vào trong R >= min_trades (30)  VÀ  t-stat của lãi/lỗ trung bình mỗi lệnh <= t_max (−2).
#   Ít lệnh hơn / lỗ không có ý nghĩa thống kê: không đủ bằng chứng để chặn -> vẫn cho phép.  Cầu chì: tắt (fuse=False) trừ khi truyền fuse=True.
#   Vì sao chặt: luật cũ (>= 5 lệnh, tổng lỗ) chỉ giữ cùng dấu 48% cặp (chiến lược, regime) từ dev1 sang dev2 — học nhiễu
#   (test/scripts/research_regime_diagnosis.py phần D).
# OBSERVE: cấu hình regime "chỉ quan sát" (cho phép mọi regime, không cầu chì) -> engine tính nhãn mà lệnh trùng bit với khi tắt regime.
# ══════════════════════════════════════════════════════════════════════════

OBSERVE: Dict[str, Any] = {"allowed": list(NAMES), "fuse": False}
MIN_TRADES = 30
T_MAX = -2.0


def trade_regime(t: np.ndarray, labels: np.ndarray, enter_time: int) -> str:
    """Regime ở nến đã đóng ngay trước khi vào lệnh."""
    i = int(np.searchsorted(t, int(enter_time), side="left")) - 1
    return NAMES[int(labels[max(i, 0)])]


def by_regime(trades: List[Dict[str, Any]], labels: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{chiến lược: {regime: {trades, wins, pnl_usd, win_rate, avg_pnl_pct}}}. trades: [{symbol, strategy, enter_time, pnl, pnl_pct?}];
    labels: {symbol: {"t", "labels"}}."""
    agg: Dict[str, Dict[str, Dict[str, float]]] = {}
    for tr in trades:
        s = labels.get(tr["symbol"])
        if s is None:
            continue
        name = trade_regime(s["t"], s["labels"], tr["enter_time"])
        a = agg.setdefault(tr["strategy"], {}).setdefault(name, {"trades": 0, "wins": 0, "pnl_usd": 0.0, "pnl_pct_sum": 0.0, "_sq": 0.0})
        a["trades"] += 1
        a["wins"] += tr["pnl"] > 0
        a["pnl_usd"] += tr["pnl"]
        a["_sq"] += tr["pnl"] ** 2
        a["pnl_pct_sum"] += tr.get("pnl_pct") or 0.0
    for st in agg.values():
        for a in st.values():
            n, sq = a["trades"], a.pop("_sq")
            mean = a["pnl_usd"] / n
            var = max(0.0, (sq - n * mean * mean) / (n - 1)) if n > 1 else 0.0
            a["t_stat"] = (round(mean / math.sqrt(var / n), 3) if var > 0 else (0.0 if mean == 0 else math.copysign(99.0, mean))) if n > 1 else 0.0
            a["win_rate"] = round(100 * a["wins"] / n, 1)
            a["avg_pnl_pct"] = round(a.pop("pnl_pct_sum") / n, 3)
            a["pnl_usd"] = round(a["pnl_usd"], 2)
    return agg


def engine_by_regime(eng, positions) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """by_regime từ một PortfolioEngine đã chạy với cấu hình regime (nhãn nằm ở eng.books[*].entries[*].regime)."""
    labels = {}
    for b in eng.books:
        lab = next((e["regime"] for e in b["entries"] if e.get("regime") is not None), None)
        if lab is not None:
            labels[b["symbol"]] = {"t": b["data"]["t"], "labels": lab}
    trades = [{"symbol": p.symbol, "strategy": p.strategy_id, "enter_time": p.enter_time, "pnl": p.real_pnl, "pnl_pct": p.profit_pct}
              for p in positions]
    return by_regime(trades, labels)


def learn_map(stats: Dict[str, Dict[str, Dict[str, Any]]], strategies: List[str], min_trades: int = MIN_TRADES,
              fuse: bool = False, t_max: float = T_MAX) -> Dict[str, Optional[Dict[str, Any]]]:
    """{chiến lược: cấu hình regime | None (không lọc)} theo luật ở đầu file."""
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for sid in strategies:
        st = stats.get(sid) or {}
        blocked = sorted(r for r, a in st.items() if a["trades"] >= min_trades and a["pnl_usd"] < 0 and a.get("t_stat", 0.0) <= t_max)
        if not blocked and not fuse:
            out[sid] = None
            continue
        out[sid] = {"allowed": [r for r in NAMES if r not in blocked], "fuse": bool(fuse), "blocked": blocked}
    return out
