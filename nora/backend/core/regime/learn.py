"""Học bảng regime ↔ chiến lược từ dữ liệu TRAIN (WFA regime="learn") thay cho bảng tĩnh book.REGIME_MAP.

Lý do (P2.4, báo cáo regime trên 8 tài sản): bảng tĩnh không khớp dữ liệu — vd. momentum_long lãi ở RANGE nhưng chỉ được phép TREND_UP/SURGE;
sau CRASH giá thường hồi (lợi suất 24h tới +2,5%) nên cầu chì cắt LONG khi CRASH làm lỗ thêm. Bật bảng tĩnh làm sổ từ +29,6% thành −26%.

Luật học (chỉ dùng lệnh của cửa sổ train, không nhìn test):
  chặn regime R của chiến lược S  khi  số lệnh S vào trong R >= min_trades  VÀ  tổng lãi/lỗ của chúng <= 0.
  regime ít lệnh hơn min_trades: không đủ bằng chứng để chặn -> vẫn cho phép.  Cầu chì: tắt (fuse=False) trừ khi truyền fuse=True.
OBSERVE: cấu hình regime "chỉ quan sát" (cho phép mọi regime, không cầu chì) -> engine tính nhãn mà lệnh trùng bit với khi tắt regime.
"""
from typing import Any, Dict, List, Optional

import numpy as np

from backend.core.regime.classifier import NAMES

OBSERVE: Dict[str, Any] = {"allowed": list(NAMES), "fuse": False}
MIN_TRADES = 5


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
        a = agg.setdefault(tr["strategy"], {}).setdefault(name, {"trades": 0, "wins": 0, "pnl_usd": 0.0, "pnl_pct_sum": 0.0})
        a["trades"] += 1
        a["wins"] += tr["pnl"] > 0
        a["pnl_usd"] += tr["pnl"]
        a["pnl_pct_sum"] += tr.get("pnl_pct") or 0.0
    for st in agg.values():
        for a in st.values():
            a["win_rate"] = round(100 * a["wins"] / a["trades"], 1)
            a["avg_pnl_pct"] = round(a.pop("pnl_pct_sum") / a["trades"], 3)
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
              fuse: bool = False) -> Dict[str, Optional[Dict[str, Any]]]:
    """{chiến lược: cấu hình regime | None (không lọc)} theo luật ở đầu file."""
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for sid in strategies:
        st = stats.get(sid) or {}
        blocked = sorted(r for r, a in st.items() if a["trades"] >= min_trades and a["pnl_usd"] <= 0)
        if not blocked and not fuse:
            out[sid] = None
            continue
        out[sid] = {"allowed": [r for r in NAMES if r not in blocked], "fuse": bool(fuse), "blocked": blocked}
    return out
