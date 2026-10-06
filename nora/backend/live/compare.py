"""So lệnh bot sàn (demo/live, khớp THẬT) với bóng paper cùng nến (khớp mô phỏng bằng engine) — đo khoảng cách giả lập ↔ thực tế.

Ghép cặp: cùng mã + cùng chiến lược, giờ vào lệnh lệch không quá 1 nến khung chạy (bot đặt lệnh vài giây sau khi nến mở; paper ghi
open_time nến). Mỗi cặp: chênh giá vào / giá đóng (bps, dấu + = sàn KÉM hơn paper), lãi lỗ theo % danh nghĩa (hai bên khác vốn), số tầng DCA, lý do đóng.
Lệnh chỉ có ở một bên (paper khớp mà sàn không, hoặc ngược lại) là dấu hiệu giả lập lạc quan / bi quan về khớp lệnh.
"""
from typing import Any, Dict, List, Optional

FRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
MIN_PAIRS = 30            # dưới ngưỡng này các số trung bình chưa đáng tin (UI hiện "chưa đủ mẫu")
# Ngưỡng cảnh báo ĐỀ XUẤT (mặc định chờ chủ hệ thống duyệt): bps = chênh giá TB (+ = sàn kém), fee_gap_pct = điểm % danh nghĩa, còn lại là tỷ lệ 0..1.
THRESHOLDS = {"entry_bps_mean": 5.0, "close_bps_mean": 5.0, "avg_bps_mean": 5.0, "fee_gap_pct": 0.02, "only_paper_share": 0.2, "sl_worse_share": 0.1}


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


def _cost_pct(cost, qty, px) -> Optional[float]:
    """Chi phí (dương = trả) / danh nghĩa, %. Thiếu dữ liệu -> None."""
    if cost is None or not qty or not px:
        return None
    return round(float(cost) / (abs(float(qty)) * float(px)) * 100.0, 5)


def _neg(v) -> Optional[float]:
    return None if v is None else -float(v)          # OKX: fee/funding âm = đã trả -> chi phí dương


def _sl_class(close_bps: Optional[float], extreme_bps: Optional[float]) -> Optional[str]:
    """Giá đóng của sàn so với hai kịch bản SL của paper: khớp đúng mức SL (level) và khớp tại cực trị nến (bi quan)."""
    if close_bps is None or extreme_bps is None:
        return None
    return "better" if close_bps <= 0 else ("between" if extreme_bps <= 0 else "worse")


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
        close_bps = _bps(x.get("close_price"), p.get("close_price"), x["side"], False)
        sl, ext_bps = None, None
        if str(p.get("reason") or "").startswith("Stop-loss"):          # lý do của PAPER (nhãn reason bên sàn do bot tự gán, không đáng tin)
            ext = p.get("bar_low") if x["side"] == "LONG" else p.get("bar_high")
            ext_bps = _bps(x.get("close_price"), ext, x["side"], False)
            sl = _sl_class(close_bps, ext_bps)
        real_in = x.get("entry_price") or x.get("open_price")   # giá khớp lệnh ĐẦU (openAvgPx của sàn là giá TB gồm các tầng DCA)
        pairs.append({
            "symbol": x["symbol"], "strategy": x["strategy"], "side": x["side"], "entry_time": x["entry_time"],
            "entry_bps": _bps(real_in, p.get("enter_price"), x["side"], True),
            "avg_bps": _bps(x.get("open_price") or x.get("avg"), p.get("avg_price"), x["side"], True),
            "close_bps": close_bps, "sl": sl, "sl_extreme_bps": ext_bps,
            "fee_pct": [_cost_pct(_neg(x.get("fee")), x.get("qty"), x.get("avg") or x.get("open_price")),
                        _cost_pct(p.get("fees"), p.get("qty"), p.get("avg_price") or p.get("enter_price"))],
            "funding_pct": [_cost_pct(_neg(x.get("funding")), x.get("qty"), x.get("avg") or x.get("open_price")),
                            _cost_pct(p.get("funding"), p.get("qty"), p.get("avg_price") or p.get("enter_price"))],
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

    both = lambda key: [q[key] for q in pairs if q[key][0] is not None and q[key][1] is not None]   # noqa: E731  (chỉ cặp có đủ hai phía)
    fee, fund = both("fee_pct"), both("funding_pct")
    fee_mean = [round(sum(v[i] for v in fee) / len(fee), 5) for i in (0, 1)] if fee else [None, None]
    fund_sum = [round(sum(v[i] for v in fund), 5) for i in (0, 1)] if fund else [None, None]
    sl_n = [q["sl"] for q in pairs if q["sl"]]
    sl_sum = {"n": len(sl_n), **{k: sl_n.count(k) for k in ("better", "between", "worse")}}
    m, T = len(pairs), THRESHOLDS
    only_paper_share = len(only_paper) / max(1, m + len(only_paper))
    flags = []

    def flag(key, value, limit, msg):
        if value is not None and value > limit:
            flags.append({"key": key, "value": round(value, 5), "limit": limit, "msg": msg})
    flag("entry_bps_mean", mean("entry_bps"), T["entry_bps_mean"], "Giá vào của sàn kém paper quá ngưỡng: xem lại giả định trượt giá (slippage).")
    flag("close_bps_mean", mean("close_bps"), T["close_bps_mean"], "Giá đóng của sàn kém paper quá ngưỡng: xem lại trượt giá / cách khớp stop-loss (stop_fill).")
    flag("avg_bps_mean", mean("avg_bps"), T["avg_bps_mean"], "Giá TB sau DCA của sàn kém paper: xem lại mô hình khớp lệnh limit DCA (limit_through_pct).")
    flag("fee_gap_pct", fee_mean[0] - fee_mean[1] if fee else None, T["fee_gap_pct"], "Phí thực trên sàn cao hơn paper: xem lại giả định phí.")
    flag("only_paper_share", only_paper_share, T["only_paper_share"], "Giả lập khớp nhiều lệnh mà sàn không khớp: mô phỏng đang lạc quan.")
    flag("sl_worse_share", sl_sum["worse"] / len(sl_n) if sl_n else None, T["sl_worse_share"], "Nhiều lệnh SL khớp xấu hơn cả đáy/đỉnh nến của kịch bản bi quan: xem lại stop_fill.")
    return {
        "pairs": pairs, "only_exec": only_exec, "only_paper": only_paper,
        "summary": {"matched": len(pairs), "only_exec": len(only_exec), "only_paper": len(only_paper),
                    "entry_bps_mean": mean("entry_bps"), "avg_bps_mean": mean("avg_bps"), "close_bps_mean": mean("close_bps"),
                    "layers_diff": sum(1 for q in pairs if q["layers"][0] != q["layers"][1]),
                    "ret_pct_exec": round(sum(q["ret_pct"][0] or 0 for q in pairs), 4),
                    "ret_pct_paper": round(sum(q["ret_pct"][1] or 0 for q in pairs), 4),
                    "fee_pct_mean": fee_mean, "funding_pct_sum": fund_sum, "sl": sl_sum,
                    "min_pairs": MIN_PAIRS, "enough": m >= MIN_PAIRS, "flags": flags},
    }
