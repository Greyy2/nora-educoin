"""Ảnh chụp TÍN HIỆU thị trường tại nến 1m ĐÃ ĐÓNG mới nhất — cùng một đường tính với backtest (không có bản tính thứ hai).

signal_snapshot(symbol, strategies, end_ts) dựng engine của tài sản y như PortfolioEngine (_make_trackers -> load_data -> _build_matrix ->
VectorEvaluator), nên giá trị chỉ báo / điều kiện / tín hiệu vào-thoát ở phút t TRÙNG với thứ engine dùng ở phút t (test_signal_snapshot).
Khung lớn chỉ dùng nến đã đóng (avail_time = open + độ dài khung); phút cuối là phút có giao dịch thật (bỏ nến điền).

Dùng cho: trang Tổng quan (dữ liệu backtest), và sau này Live/Testnet — chỉ cần nạp nến mới nhất của sàn vào cùng bố cục dữ liệu rồi gọi lại hàm này.
Kết quả mỗi chiến lược: entry/exit (tín hiệu ở nến đã đóng cuối), `entry_since` (từ phút nào tín hiệu vào giữ trạng thái hiện tại),
và từng điều kiện (giá trị trái/phải, toán tử, đạt/không) để biết vì sao có / không có tín hiệu.
"""
from typing import Any, Dict, List, Optional

import numpy as np

from backend.core.signals.evaluator import VectorEvaluator, lag_key

MINUTE = 60_000
DEFAULT_LOOKBACK_MIN = 3 * 24 * 60     # 3 ngày 1m (chỉ báo khung lớn có warmup riêng do engine tự nạp thêm)


def _label(item: Any) -> str:
    if isinstance(item, bool) or item is None:
        return "?"
    if isinstance(item, (int, float)):
        return f"{item:g}"
    if isinstance(item, dict):
        if "frame" in item and "column" in item:
            lag = int(item.get("index", 0) or 0)
            base = f"{item['frame']} {item['column']}" + (f"[-{lag}]" if lag else "")
            for key, sign in (("subtract", " − "), ("add", " + "), ("divide", " ÷ ")):
                if key in item:
                    base = f"({base}{sign}{_label(item[key])})"
            return base
        if item.get("type") == "calculate":
            s = f"({_label(item.get('number_1'))} {item.get('logic')} {_label(item.get('number_2'))})"
            mult = item.get("multiply", 1.0)
            return s if mult in (1, 1.0) else f"{s} × {mult:g}"
        if item.get("type") in ("min", "max"):
            return f"{item['type']}(" + ", ".join(_label(x) for x in item.get("numbers", [])) + ")"
    return "?"


def _num(x) -> Optional[float]:
    x = float(x)
    return x if np.isfinite(x) else None


def _explain(vec: VectorEvaluator, tree: Any, i: int) -> List[Dict[str, Any]]:
    """Mỗi khối AND của cây (OR giữa các khối): điều kiện + giá trị tại vị trí i."""
    blocks = []
    if not isinstance(tree, list):
        return blocks
    for block in tree:
        if not isinstance(block, list) or not block:
            continue
        conds = []
        for trip in block:
            ok = bool(vec._triplet(trip)[i])
            if isinstance(trip, list) and len(trip) == 3:
                conds.append({"left": _label(trip[0]), "left_value": _num(vec.value(trip[0])[i]), "op": trip[1],
                              "right": _label(trip[2]), "right_value": _num(vec.value(trip[2])[i]), "pass": ok})
            else:
                conds.append({"left": "?", "left_value": None, "op": "?", "right": "?", "right_value": None, "pass": False})
        blocks.append({"pass": all(c["pass"] for c in conds), "conditions": conds})
    return blocks


def _since(arr: np.ndarray, t: np.ndarray, i: int) -> Optional[int]:
    """open_time của phút đầu tiên trong chuỗi liên tiếp hiện tại có cùng giá trị với arr[i] (None nếu chuỗi kéo dài hết cửa sổ)."""
    v = arr[i]
    j = i
    while j > 0 and arr[j - 1] == v:
        j -= 1
    return int(t[j]) if j > 0 else None


def signal_snapshot(symbol: str, strategies: List[Dict[str, Any]], end_ts: int, lookback_minutes: int = DEFAULT_LOOKBACK_MIN,
                    venue: str = "cex") -> Dict[str, Any]:
    """Tín hiệu của `strategies` (dạng chiến lược của PortfolioEngine) trên `symbol` tại nến 1m đã đóng cuối cùng <= end_ts."""
    from backend.core.backtest.portfolio import PortfolioEngine
    start = int(end_ts) - int(lookback_minutes) * MINUTE
    pe = PortfolioEngine([symbol], strategies, start, int(end_ts), trade_start_ts=start, venue=venue, use_cache=True)
    eng, pairs = pe._make_trackers(symbol, pe.ledger)
    out: Dict[str, Any] = {"symbol": symbol, "bar_open_time": None, "as_of": None, "close": None, "regime": None, "strategies": []}
    if not pairs:
        return out
    from backend.core.regime import classifier as rg
    eng.extra_refs = rg.REFS                         # regime luôn hiển thị, cùng cột đặc trưng với backtest bật regime
    eng.load_data()
    if eng.df_1m is None or eng.df_1m.empty:
        return out
    df1, cols = eng._build_matrix()
    n = len(df1)
    real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)
    t_all = df1["open_time"].to_numpy(dtype="int64")
    real = real[t_all[real] < int(end_ts)]          # chỉ nến đã ĐÓNG trước end_ts
    if real.size == 0:
        return out
    i = int(real[-1])

    def get(frame, column, lag):
        return cols.get(f"{frame}|{lag_key(column, lag)}", np.full(n, np.nan))

    vec = VectorEvaluator(n, get)
    t_real = t_all[real]
    out.update(bar_open_time=int(t_all[i]), as_of=int(t_all[i]) + MINUTE, close=_num(df1["close"].to_numpy()[i]))
    labels = rg.classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t_all)
    raw = rg.raw_states(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), n)
    name = rg.NAMES[int(labels[i])]
    out["regime"] = {"state": name, "label": rg.LABEL_VI[name], "raw": rg.NAMES[int(raw[i])],
                     "since": _since(labels[real], t_real, len(real) - 1),
                     "features": {f"{fr} {c}": _num(cols.get(f"{fr}|{c}", np.full(n, np.nan))[i])
                                  for fr, refs in sorted(rg.REFS.items()) for c, _ in sorted(refs)}}
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
        entry_raw = bool(match[i])
        if st.get("regime"):                          # cùng mặt nạ với PortfolioEngine.load_data
            allowed, fuse = rg.masks_for(st, st["side"], labels)
            match = match & allowed
            if fuse is not None:
                stop = stop | fuse
        m_real = match[real]
        out["strategies"].append({
            "id": st["id"], "side": st["side"], "entry": bool(match[i]), "exit": bool(stop[i]), "entry_raw": entry_raw,
            "entry_since": _since(m_real, t_real, len(real) - 1),
            "entry_minutes_in_window": int(m_real.sum()),
            "entry_blocks": _explain(vec, tr.match_tree, i), "exit_blocks": _explain(vec, tr.stop_tree, i),
            "regime_allowed": (st.get("regime") or {}).get("allowed"),
            "regime_ok": bool(not st.get("regime") or labels[i] in [rg.CODE[x] for x in st["regime"].get("allowed") or rg.NAMES]),
        })
    return out


def book_strategies(ids: Optional[List[str]] = None, regime: bool = True) -> List[Dict[str, Any]]:
    """7 chiến lược lõi của sổ với bộ tham số tốt nhất (presets.json) — tham số khác vẫn là cùng chiến lược.
    regime=True: kèm bảng regime cho phép (entry = tín hiệu thô VÀ regime cho phép; entry_raw = tín hiệu thô)."""
    from backend.core.params.presets import load_presets
    from backend.core.strategy.book import CANDIDATES, materialize
    presets = load_presets()
    return [materialize(c, presets[c["id"]]["params"], regime=regime) for c in CANDIDATES if not ids or c["id"] in ids]
