"""Giải thích tín hiệu của MỘT chiến lược trên MỘT mã: nến + đường chỉ báo + điểm tín hiệu + từng điều kiện đúng/sai tại mỗi điểm.

Tính bằng đúng đường của engine/bot (live/signals.evaluate -> PortfolioEngine._build_matrix + VectorEvaluator), nên thứ vẽ ra là thứ engine
"thấy": giá trị khung lớn ở nến t là nến khung ĐÃ ĐÓNG gần nhất; tín hiệu ở nến t xét trên giá đóng của t và vào lệnh ở open nến t+1.

explain(...) -> {
  "candles": [{t, o, h, l, c}],               # nến khung chạy trong cửa sổ (t = giây, cho thư viện biểu đồ)
  "overlays": [{name, frame, values}],        # đường cùng thang giá (EMA, dải Keltner/Bollinger, Donchian ...)
  "oscillators": [{name, frame, values, levels}],   # chỉ báo khác thang (RSI, ADX, ROC, ER ...) + ngưỡng hằng trong điều kiện
  "signals": [{t, kind: entry|exit, conditions: [{text, left, op, right, ok}], blocks_ok}],
  "conditions": {"entry": [[text...]], "exit": [[text...]]},   # cây điều kiện dạng chữ (OR các khối AND)
}
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

FRAME_NAME = {"1m": "1 phút", "5m": "5 phút", "15m": "15 phút", "1h": "1 giờ", "4h": "4 giờ", "24h": "1 ngày"}
OP_TEXT = {">": ">", "<": "<", ">=": "≥", "<=": "≤", "==": "=", "!=": "≠"}


def _num(v: float) -> str:
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
        return _num(float(node))
    if not isinstance(node, dict):
        return "?"
    t = node.get("type")
    if t == "calculate":
        mul = node.get("multiply", 1.0)
        s = f"({label(node.get('number_1'))} {node.get('logic')} {label(node.get('number_2'))})"
        return s if mul in (1, 1.0) else f"{s} × {_num(float(mul))}"
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
