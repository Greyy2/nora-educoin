"""Market Regime Classification & Analysis (Tích hợp trong metrics).

Nhận diện trạng thái thị trường theo phút, causal (classifier) + học bảng regime ↔ chiến lược từ dữ liệu TRAIN (learn).
"""
import math
from typing import Any, Dict, List, Optional

import numpy as np

# Phân loại trạng thái, ngưỡng, REFS, raw_states/smooth/classify, masks_for
from backend.analys.signal.signal import (
    CODE, CRASH, DEFAULTS, LABEL_VI, MINUTE, NAMES, PROFILES, RANGE, REFS, SURGE, TREND_DOWN, TREND_UP, UNKNOWN, VOL_EXPANSION,
    classify, masks_for, profile_cfg, raw_states, smooth,
)

__all__ = [
    "CODE", "CRASH", "DEFAULTS", "LABEL_VI", "MINUTE", "NAMES", "PROFILES", "RANGE", "REFS", "SURGE", "TREND_DOWN", "TREND_UP", "UNKNOWN",
    "VOL_EXPANSION", "classify", "masks_for", "profile_cfg", "raw_states", "smooth", "summarize_window_labels", "summarize_window_context",
    "series", "OBSERVE", "MIN_TRADES", "T_MAX", "trade_regime", "by_regime", "engine_by_regime", "learn_map",
]


def series(symbol: str, start: int, end: int, venue: str = "cex", cfg: Optional[Dict[str, float]] = None,
           base_frame: str = "1m") -> Dict[str, np.ndarray]:
    """Nhãn regime từng nến khung chạy của một tài sản qua đường dữ liệu của engine."""
    from backend.analys.signal.compute import SignalPortfolio
    probe = {"id": "_regime_probe", "side": "LONG", "position": {"market": "perp"},
             "tree": [[[{"frame": "1h", "column": "roc_1", "index": 0}, ">", 1e18]]]}
    pe = SignalPortfolio([symbol], [probe], start, end, trade_start_ts=start, venue=venue, use_cache=False, base_frame=base_frame)
    eng, _ = pe._make_slots(symbol, pe.ledger)
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


def summarize_window_labels(
    symbol: str,
    times: np.ndarray,
    labels: np.ndarray,
    real: np.ndarray,
    start_ms: int,
    end_ms: int,
) -> Dict[str, Any]:
    """DEC-01: Return descriptive dominant context for real bars in a half-open run window."""
    if end_ms <= start_ms:
        raise ValueError("Market-context window must have end_ms > start_ms")
    if not (len(times) == len(labels) == len(real)):
        raise ValueError("Market-context arrays must have matching lengths")

    in_window = (times >= start_ms) & (times < end_ms) & real
    window_bars = int(np.count_nonzero(in_window))
    usable = in_window & (labels > UNKNOWN) & (labels < len(NAMES))
    counts = np.bincount(labels[usable].astype(np.int64), minlength=len(NAMES))
    classified_bars = int(counts.sum())
    context: Dict[str, Any] = {
        "status": "unavailable",
        "symbol": symbol,
        "timeframe": "15m",
        "method": "dominant_causal_label_over_closed_bars_in_backtest_window",
        "window_start_ms": int(start_ms),
        "window_end_ms": int(end_ms),
        "window_bars": window_bars,
        "classified_bars": classified_bars,
        "coverage_pct": round(100 * classified_bars / window_bars, 1) if window_bars else 0.0,
        "reference_only": True,
    }
    if not classified_bars:
        context["reason"] = "No classified real 15m bars in the backtest window"
        return context

    dominant_code = max(range(1, len(NAMES)), key=lambda code: (int(counts[code]), -code))
    context.update(
        status="available",
        dominant=NAMES[dominant_code],
        distribution_pct={
            NAMES[code]: round(100 * int(counts[code]) / classified_bars, 1)
            for code in range(1, len(NAMES))
            if counts[code]
        },
    )
    return context


def summarize_window_context(symbol: str, start_ms: int, end_ms: int) -> Dict[str, Any]:
    """DEC-01: Classify actual EDU 15m bars in-window; this never affects execution."""
    from backend.data.data import base_name

    market_symbol = f"{base_name(symbol)}-USDT"
    bars = series(symbol, start_ms, end_ms, base_frame="15m")
    return summarize_window_labels(
        market_symbol,
        bars["t"],
        bars["labels"],
        bars["real"],
        start_ms,
        end_ms,
    )


OBSERVE: Dict[str, Any] = {"allowed": list(NAMES), "fuse": False}
MIN_TRADES = 30
T_MAX = -2.0


def trade_regime(t: np.ndarray, labels: np.ndarray, enter_time: int) -> str:
    """Regime ở nến đã đóng ngay trước khi vào lệnh."""
    i = int(np.searchsorted(t, int(enter_time), side="left")) - 1
    return NAMES[int(labels[max(i, 0)])]


def by_regime(trades: List[Dict[str, Any]], labels: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{chiến lược: {regime: {trades, wins, pnl_usd, win_rate, avg_pnl_pct}}}."""
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
    """by_regime từ một PortfolioEngine đã chạy với cấu hình regime."""
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
    """{chiến lược: cấu hình regime | None (không lọc)} theo luật kiểm định thống kê."""
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for sid in strategies:
        st = stats.get(sid) or {}
        blocked = sorted(r for r, a in st.items() if a["trades"] >= min_trades and a["pnl_usd"] < 0 and a.get("t_stat", 0.0) <= t_max)
        if not blocked and not fuse:
            out[sid] = None
            continue
        out[sid] = {"allowed": [r for r in NAMES if r not in blocked], "fuse": bool(fuse), "blocked": blocked}
    return out
