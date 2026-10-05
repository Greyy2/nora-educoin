"""So lệnh bot sàn (demo/live, khớp THẬT) với bóng paper cùng nến (khớp mô phỏng bằng engine) — đo khoảng cách giả lập ↔ thực tế.

Ghép cặp: cùng mã + cùng chiến lược, giờ vào lệnh lệch không quá 1 nến khung chạy (bot đặt lệnh vài giây sau khi nến mở; paper ghi
open_time nến). Mỗi cặp: chênh giá vào / giá đóng (bps, dấu + = sàn KÉM hơn paper), lãi lỗ theo % danh nghĩa (hai bên khác vốn), số tầng DCA, lý do đóng.
Lệnh chỉ có ở một bên (paper khớp mà sàn không, hoặc ngược lại) là dấu hiệu giả lập lạc quan / bi quan về khớp lệnh.
"""
from typing import Any, Dict, List, Optional

FRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def _bps(real: Optional[float], sim: Optional[float], side: str, entering: bool) -> Optional[float]:
    """Chênh giá theo bps, dương = sàn khớp kém hơn paper (mua đắt hơn / bán rẻ hơn)."""
    if not real or not sim:
        return None
    buy = (side == "LONG") == entering
    return round(((real - sim) / sim if buy else (sim - real) / sim) * 10_000, 2)


def _ret(pnl, qty, px) -> Optional[float]:
    if pnl is None or not qty or not px:
        return None
    return round(float(pnl) / (abs(float(qty)) * float(px)) * 100.0, 4)


def compare_trades(exec_trades: List[Dict[str, Any]], paper_trades: List[Dict[str, Any]], timeframe: str) -> Dict[str, Any]:
    tol = FRAME_MS.get(timeframe, 3_600_000)          # bot vào lệnh ở open nến (như paper); lệch tối đa 1 nến
    used, pairs, only_exec = set(), [], []
    for x in sorted(exec_trades, key=lambda t: t.get("entry_time") or 0):
        best, gap = None, None
        for j, p in enumerate(paper_trades):
            if j in used or p["symbol"].split("@")[0] != x["symbol"] or p["strategy"] != x["strategy"]:
                continue
            g = abs(int(p["enter_time"]) - int(x["entry_time"]))
            if g <= tol and (gap is None or g < gap):
                best, gap = j, g
        if best is None:
            only_exec.append(x)
            continue
        used.add(best)
        p = paper_trades[best]
        real_in = x.get("entry_price") or x.get("open_price")   # giá khớp lệnh ĐẦU (openAvgPx của sàn là giá TB gồm các tầng DCA)
        pairs.append({
            "symbol": x["symbol"], "strategy": x["strategy"], "side": x["side"], "entry_time": x["entry_time"],
            "entry_bps": _bps(real_in, p.get("enter_price"), x["side"], True),
            "avg_bps": _bps(x.get("open_price") or x.get("avg"), p.get("avg_price"), x["side"], True),
            "close_bps": _bps(x.get("close_price"), p.get("close_price"), x["side"], False),
            "layers": [x.get("layers"), p.get("layers")],
            "reason": [x.get("reason"), p.get("reason")],
            "ret_pct": [_ret(x.get("pnl"), x.get("qty"), x.get("open_price") or x.get("avg")),
                        _ret(p.get("pnl"), p.get("qty"), p.get("avg_price") or p.get("enter_price"))],   # lãi lỗ / danh nghĩa (hai bên khác vốn)
        })
    only_paper = [p for j, p in enumerate(paper_trades) if j not in used and int(p["enter_time"]) >= min(
        [int(t.get("entry_time") or 0) for t in exec_trades] or [int(p["enter_time"])])]

    def mean(key):
        v = [q[key] for q in pairs if q[key] is not None]
        return round(sum(v) / len(v), 2) if v else None
    return {
        "pairs": pairs, "only_exec": only_exec, "only_paper": only_paper,
        "summary": {"matched": len(pairs), "only_exec": len(only_exec), "only_paper": len(only_paper),
                    "entry_bps_mean": mean("entry_bps"), "avg_bps_mean": mean("avg_bps"), "close_bps_mean": mean("close_bps"),
                    "layers_diff": sum(1 for q in pairs if q["layers"][0] != q["layers"][1]),
                    "ret_pct_exec": round(sum(q["ret_pct"][0] or 0 for q in pairs), 4),
                    "ret_pct_paper": round(sum(q["ret_pct"][1] or 0 for q in pairs), 4)},
    }
