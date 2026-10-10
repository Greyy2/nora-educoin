# Nguồn: docs/bmad/p9_review_log.md (mục P9.5, P9.7, P9.10a). Cuối file có khối đối soát sàn <-> sim.
"""Số đo theo LỆNH (đã đóng) và theo phơi nhiễm vốn: bảng lệnh phẳng, thắng/thua, profit factor, payoff, expectancy, chuỗi thua,
độ tập trung lãi, thời gian giữ, tách long/short, phí/funding, DCA (tầng, lỗ treo, độ gần thanh lý), ký quỹ/exposure theo thời gian.

Quy ước:
  - thắng = PnL > 0, thua = PnL < 0, hoà (= 0) đếm riêng; win_rate = thắng / tổng lệnh (hoà làm giảm win_rate, không tính là thua);
  - profit_factor = Σ lãi / Σ lỗ. KHÔNG có lệnh lỗ (Σ lỗ = 0) thì PF không xác định -> None + `profit_factor_note` nêu lý do (không còn số chặn 99);
    0 lệnh -> win_rate = None, profit_factor = None (+ ghi chú), không phải 0 giả. Giao diện hiện "—" + lý do;
  - cổng phễu (optimize/funnel/stages.py) KHÔNG đọc win_rate / profit_factor nên đổi này không đổi quyết định cổng nào; nếu sau này cổng đọc PF,
    "không có lệnh thua" (profit_factor_note == NOTE_NO_LOSSES) phải được coi là ĐẠT tiêu chí PF (hành vi cũ: PF = 99 ≥ mọi ngưỡng), đừng so None với số;
  - payoff = TB lệnh thắng / |TB lệnh thua|; expectancy = PnL trung bình mỗi lệnh (USD và % vốn lúc mở lệnh);
  - fee_drag_pct = phí / lãi trước phí (phần lãi gộp bị phí ăn mất); None khi lãi trước phí <= 0;
  - liq_proximity_pct = |lỗ treo tối đa của lệnh| / ký quỹ của lệnh × 100 (100 = mất hết ký quỹ = thanh lý, isolated);
  - ký quỹ / exposure theo thời gian dựng lại từ [enter, close] của lệnh với ký quỹ CUỐI của lệnh (sau mọi tầng DCA) -> hơi cao hơn
    thực tế trước khi nhồi; tính theo % vốn ban đầu.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.params import DAY_MS as DAY, FRAME_MS as FRAME_MS_ALL, HOUR_MS as HOUR, MINUTE_MS as MINUTE, date_ms, iso_date
from backend.regime import regime as rg

LIQ_STATUS = "LIQ"
NOTE_NO_TRADES = "không có lệnh nào"
NOTE_NO_LOSSES = "không có lệnh thua"
NOTE_NO_PNL = "không có lệnh lãi hay lỗ (chỉ lệnh hoà)"


def profit_factor_of(gross_profit: float, gross_loss: float, n_trades: int):
    """(profit_factor | None, lý do | None). Σ lỗ = 0 -> PF không xác định (None), KHÔNG chặn ở một hằng số."""
    if n_trades == 0:
        return None, NOTE_NO_TRADES
    if gross_loss > 0:
        return gross_profit / gross_loss, None
    return None, (NOTE_NO_LOSSES if gross_profit > 0 else NOTE_NO_PNL)


def trade_rows(positions) -> List[Dict[str, Any]]:
    return [{
        "symbol": p.symbol, "strategy": getattr(p, "strategy_id", "") or "", "side": p.pos_type.name,
        "enter_time": int(p.enter_time), "close_time": int(p.close_time),
        "enter_price": float(p.enter_price), "close_price": float(p.close_price), "qty": float(p.qty),
        "pnl_usd": float(p.real_pnl), "pnl_pct": float(p.profit_pct), "fees_usd": float(p.fees_usd or 0.0),
        "funding_usd": float(p.funding_usd or 0.0), "status": p.status.name, "layers": int(p.layers or 0),
        "mae_pct": float(p.mae_pct or 0.0), "margin_usd": float(getattr(p, "total_margin_usd", 0.0) or 0.0),
        "leverage": float(getattr(p, "leverage_used", 1.0) or 1.0), "entry_equity": float(getattr(p, "entry_equity", 0.0) or 0.0),
    } for p in positions]


def strategy_family(sid: str) -> str:
    """Họ chiến lược của một id: id của sổ ("trend_long") giữ nguyên; alpha kho dạng "<chiến lược>__<TÀI SẢN>" -> phần trước "__".
    Đổi tham số KHÔNG đổi họ: mọi alpha của cùng chiến lược gộp chung một nhóm."""
    return str(sid or "").split("__")[0] or "?"


def rows_from_trade_list(trade_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """trade_list của job backtest / feed (khoá `pnl`, ...) -> dạng trade_rows để tính trade_metrics. Lệnh chưa đóng bị bỏ qua."""
    out = []
    for t in trade_list or []:
        if t.get("close_time") is None:
            continue
        eq = float(t.get("entry_equity") or 0.0)
        pnl = float(t.get("pnl") or 0.0)
        out.append({"symbol": t.get("symbol"), "strategy": t.get("strategy") or "", "side": t.get("side") or "LONG",
                    "enter_time": int(t.get("enter_time") or 0), "close_time": int(t["close_time"]),
                    "pnl_usd": pnl, "pnl_pct": float(t["pnl_pct"]) if t.get("pnl_pct") is not None else (pnl / eq * 100.0 if eq > 0 else 0.0),
                    "fees_usd": float(t.get("fees_usd") or 0.0), "funding_usd": float(t.get("funding_usd") or 0.0),
                    "status": t.get("status"), "layers": int(t.get("layers") or 1), "mae_pct": float(t.get("mae_pct") or 0.0),
                    "margin_usd": float(t.get("margin_usd") or 0.0), "leverage": float(t.get("leverage") or 1.0), "entry_equity": eq})
    return out


def trade_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """win_rate (1 chữ số) + profit_factor (3 chữ số) cho bảng của phễu. Không xác định -> None + `*_note` (lý do), không dùng 0/99 giả."""
    pnl = np.asarray([r["pnl_usd"] for r in rows], dtype=float)
    gp, gl = float(pnl[pnl > 0].sum()), float(-pnl[pnl < 0].sum())
    pf, note = profit_factor_of(gp, gl, int(pnl.size))
    return {"win_rate": round(float((pnl > 0).mean() * 100), 1) if pnl.size else None,
            "win_rate_note": None if pnl.size else NOTE_NO_TRADES,
            "profit_factor": round(pf, 3) if pf is not None else None, "profit_factor_note": note}


def _side_block(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pnl = np.asarray([r["pnl_usd"] for r in rows], dtype=float)
    return {"trades": int(pnl.size), "pnl_usd": float(pnl.sum()) if pnl.size else 0.0,
            "win_rate": float((pnl > 0).mean() * 100.0) if pnl.size else None}


def max_consecutive(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def trade_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mọi số đo theo lệnh từ trade_rows (lệnh xếp theo thời điểm đóng)."""
    rows = sorted(rows, key=lambda r: (r["close_time"], r["enter_time"]))
    n = len(rows)
    pnl = np.asarray([r["pnl_usd"] for r in rows], dtype=float)
    pct = np.asarray([r["pnl_pct"] for r in rows], dtype=float)
    fees = float(sum(r.get("fees_usd", 0.0) for r in rows))
    funding = float(sum(r.get("funding_usd", 0.0) for r in rows))
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gp, gl = float(wins.sum()), float(-losses.sum())
    avg_win = float(wins.mean()) if wins.size else None
    avg_loss = float(losses.mean()) if losses.size else None
    pre_fee = float(pnl.sum()) + fees
    top = np.sort(wins)[::-1][:5]
    hold_h = np.asarray([(r["close_time"] - r["enter_time"]) / 3_600_000 for r in rows], dtype=float)
    mae = np.asarray([r.get("mae_pct", 0.0) for r in rows], dtype=float)
    layers = np.asarray([r.get("layers", 1) for r in rows], dtype=float)
    pf, pf_note = profit_factor_of(gp, gl, n)
    prox = [abs(r["mae_pct"]) / 100.0 * r["entry_equity"] / r["margin_usd"] * 100.0
            for r in rows if r.get("margin_usd") and r.get("entry_equity")]
    return {
        "trades": n, "wins": int(wins.size), "losses": int(losses.size), "breakeven": int(n - wins.size - losses.size),
        "win_rate": float(wins.size / n * 100.0) if n else None, "loss_rate": float(losses.size / n * 100.0) if n else None,
        "win_rate_note": None if n else NOTE_NO_TRADES,
        "profit_factor": pf, "profit_factor_note": pf_note,
        "gross_profit_usd": gp, "gross_loss_usd": gl, "pnl_usd": float(pnl.sum()),
        "avg_win_usd": avg_win, "avg_loss_usd": avg_loss,
        "payoff": (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss else None,
        "expectancy_usd": float(pnl.mean()) if n else None, "expectancy_pct": float(pct.mean()) if n else None,
        "best_trade_usd": float(pnl.max()) if n else None, "worst_trade_usd": float(pnl.min()) if n else None,
        "best_trade_pct": float(pct.max()) if n else None, "worst_trade_pct": float(pct.min()) if n else None,
        "max_consec_wins": max_consecutive(pnl > 0), "max_consec_losses": max_consecutive(pnl < 0),
        "top5_share_pct": float(top.sum() / gp * 100.0) if gp > 0 else None,
        "avg_hold_h": float(hold_h.mean()) if n else None, "max_hold_h": float(hold_h.max()) if n else None,
        "fees_usd": fees, "funding_usd": funding, "fee_drag_pct": float(fees / pre_fee * 100.0) if pre_fee > 0 else None,
        "long": _side_block([r for r in rows if r["side"] == "LONG"]),
        "short": _side_block([r for r in rows if r["side"] == "SHORT"]),
        "layers_avg": float(layers.mean()) if n else None, "layers_max": int(layers.max()) if n else 0,
        "mae_avg_pct": float(mae.mean()) if n else None, "mae_worst_pct": float(mae.min()) if n else None,
        "liq_proximity_max_pct": float(max(prox)) if prox else None,
        "liquidations": int(sum(1 for r in rows if r.get("status") == LIQ_STATUS)),
    }


def exposure_metrics(rows: List[Dict[str, Any]], start_ts: int, end_ts: int, capital: float) -> Dict[str, Any]:
    """Theo thời gian, từ khoảng [enter, close] của lệnh: % thời gian có vị thế, ký quỹ đỉnh, exposure gộp/ròng TB (theo thời gian) và
    lớn nhất — % vốn ban đầu. Ký quỹ mỗi lệnh = ký quỹ cuối (sau DCA); danh nghĩa = ký quỹ × đòn bẩy."""
    span = max(1, int(end_ts) - int(start_ts))
    if not rows or capital <= 0:
        return {"time_in_market_pct": 0.0, "peak_margin_pct": 0.0, "exposure_gross_avg_pct": 0.0, "exposure_gross_max_pct": 0.0,
                "exposure_net_avg_pct": 0.0, "exposure_net_max_pct": 0.0, "max_concurrent": 0}
    ev = []
    for r in rows:
        a, b = max(int(r["enter_time"]), int(start_ts)), min(int(r["close_time"]), int(end_ts))
        if b <= a:
            continue
        m = float(r.get("margin_usd") or 0.0)
        g = m * float(r.get("leverage") or 1.0)
        s = g if r["side"] == "LONG" else -g
        ev.append((a, 1, m, g, s))
        ev.append((b, -1, -m, -g, -s))
    ev.sort(key=lambda e: (e[0], e[1]))          # đóng trước mở cùng thời điểm
    open_n = 0
    margin = gross = net = 0.0
    peak_m = peak_g = peak_abs_net = 0.0
    max_open = 0
    t_prev = None
    covered = area_g = area_n = 0.0
    for t, d, m, g, s in ev:
        if t_prev is not None and t > t_prev:
            dt = t - t_prev
            if open_n > 0:
                covered += dt
            area_g += gross * dt
            area_n += net * dt
        open_n += d
        margin += m
        gross += g
        net += s
        peak_m, peak_g, peak_abs_net = max(peak_m, margin), max(peak_g, gross), max(peak_abs_net, abs(net))
        max_open = max(max_open, open_n)
        t_prev = t
    return {"time_in_market_pct": covered / span * 100.0, "peak_margin_pct": peak_m / capital * 100.0,
            "exposure_gross_avg_pct": area_g / span / capital * 100.0, "exposure_gross_max_pct": peak_g / capital * 100.0,
            "exposure_net_avg_pct": area_n / span / capital * 100.0, "exposure_net_max_pct": peak_abs_net / capital * 100.0,
            "max_concurrent": int(max_open)}


def strategy_correlation(rows: List[Dict[str, Any]], start_ts: int, end_ts: int) -> Optional[Dict[str, Any]]:
    """Tương quan PnL NGÀY (theo ngày đóng lệnh) giữa các chiến lược: {"pairs": {"a|b": r}, "avg": r TB, "max": r lớn nhất}.
    < 2 chiến lược có lệnh -> None."""
    import pandas as pd
    ids = sorted({r["strategy"] for r in rows if r.get("strategy")})
    if len(ids) < 2:
        return None
    days = pd.date_range(pd.Timestamp(int(start_ts), unit="ms").normalize(), pd.Timestamp(int(end_ts), unit="ms").normalize(), freq="D")
    m = pd.DataFrame(0.0, index=days, columns=ids)
    for r in rows:
        d = pd.Timestamp(int(r["close_time"]), unit="ms").normalize()
        if r.get("strategy") in m.columns and d in m.index:
            m.loc[d, r["strategy"]] += float(r["pnl_usd"])
    c = m.corr()
    pairs = {f"{a}|{b}": (float(c.loc[a, b]) if np.isfinite(c.loc[a, b]) else None) for i, a in enumerate(ids) for b in ids[i + 1:]}
    vals = [v for v in pairs.values() if v is not None]
    return {"pairs": pairs, "avg": float(np.mean(vals)) if vals else None, "max": float(np.max(vals)) if vals else None}


# ══════════════════════════════════════════════════════════════════════════
# So lệnh bot sàn (demo/live, khớp THẬT) với bóng paper cùng nến (khớp mô phỏng bằng engine) — đo khoảng cách giả lập ↔ thực tế.
#
# Ghép cặp: cùng mã + cùng chiến lược, giờ vào lệnh lệch không quá 1 nến khung chạy (bot đặt lệnh vài giây sau khi nến mở; paper ghi
# open_time nến). Mỗi cặp: chênh giá vào / giá đóng (bps, dấu + = sàn KÉM hơn paper), lãi lỗ theo % danh nghĩa (hai bên khác vốn), số tầng DCA, lý do đóng.
# Lệnh chỉ có ở một bên (paper khớp mà sàn không, hoặc ngược lại) là dấu hiệu giả lập lạc quan / bi quan về khớp lệnh.
# ══════════════════════════════════════════════════════════════════════════

FRAME_MS = {f: FRAME_MS_ALL[f] for f in ("15m", "1h", "4h")}      # khung bot chạy (bản đầy đủ: core.params.FRAME_MS)
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


# ═════════════════════════════════════════════════════════════════════════════════════════════
# P6.8a — đối soát CẤP SỰ KIỆN (Fill của sàn / OkxVenue  ↔  Fill của bóng sim / SimVenue qua PositionManager).
# compare_trades ở trên giữ nguyên (router /api/studio/live/compare dùng nó); đây là lớp mịn hơn: từng lệnh khớp theo loại.
# ═════════════════════════════════════════════════════════════════════════════════════════════
ENTER_KINDS = ("entry", "dca")                                              # lệnh mở / nhồi tầng
CLOSE_KINDS = ("sl", "tp", "trail", "exit", "timeout", "kill", "liq", "end")    # lệnh đóng hết vị thế
REPORT_KINDS = ("entry", "dca", "sl", "tp", "trail", "exit", "timeout", "kill")
TAKER_KINDS = ("entry", "exit", "sl", "trail")                              # loại khớp taker -> có thể hiệu chỉnh slippage_rate (D4)
# Ngân sách dung sai ĐỀ XUẤT: *_bps theo loại = chênh giá TB (+ = sàn kém hơn sim); only_sim_share 0..1; fee_gap_pct = điểm % danh nghĩa.
# Muốn kiểm thêm: "<kind>" cho timeout/kill, hoặc "equity_drift_pct" (chỉ kiểm khi người gọi đặt).
EVENT_BUDGETS = {"entry": 5.0, "dca": 5.0, "sl": 10.0, "tp": 3.0, "trail": 10.0, "exit": 5.0, "only_sim_share": 0.2, "fee_gap_pct": 0.02}


def _g(o: Any, name: str, default: Any = None) -> Any:
    """Đọc trường của Fill dạng dataclass hoặc dict (events.jsonl qua dataclasses.asdict)."""
    return o.get(name, default) if isinstance(o, dict) else getattr(o, name, default)


def _is_fill(o: Any) -> bool:
    if isinstance(o, dict):
        return "price" in o and "kind" in o
    return type(o).__name__ == "Fill" or (hasattr(o, "price") and hasattr(o, "kind") and hasattr(o, "liquidity"))


def _is_reject(o: Any) -> bool:
    if isinstance(o, dict):
        return "price" not in o and "kind" in o and "reason" in o and "order_id" in o
    return type(o).__name__ == "OrderRejected"


def _frame_ms(timeframe: str) -> int:
    if timeframe in FRAME_MS:
        return FRAME_MS[timeframe]
    try:
        return int(timeframe[:-1]) * {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[timeframe[-1]]
    except (KeyError, ValueError, IndexError, TypeError):
        return 3_600_000


def _pct(v: List[float], q: float) -> Optional[float]:
    """Phân vị q (0..1) nội suy tuyến tính; rỗng -> None."""
    if not v:
        return None
    s = sorted(v)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _stats(v: List[float], nd: int = 2) -> Dict[str, Any]:
    if not v:
        return {"n": 0, "mean": None, "p50": None, "p90": None}
    return {"n": len(v), "mean": round(sum(v) / len(v), nd), "p50": round(_pct(v, 0.5), nd), "p90": round(_pct(v, 0.9), nd)}


def _split_positions(fills: List[Any]) -> Dict[Any, List[List[Any]]]:
    """Gom fill theo khoá (symbol hoặc slot) rồi cắt thành các VỊ THẾ theo thứ tự thời gian: lệnh đóng kết thúc vị thế;
    "entry" gặp khi vị thế đang mở và đã có entry (mất lệnh đóng) mở vị thế mới."""
    by_key: Dict[Any, List[Any]] = {}
    for f in fills:
        k = _g(f, "symbol")
        by_key.setdefault(_g(f, "slot") if k is None else k, []).append(f)
    out: Dict[Any, List[List[Any]]] = {}
    for k, fs in by_key.items():
        fs.sort(key=lambda f: (int(_g(f, "t") or 0), int(_g(f, "order_id") or 0)))
        poss: List[List[Any]] = []
        cur: List[Any] = []
        for f in fs:
            kind = _g(f, "kind")
            if kind == "entry" and any(_g(x, "kind") == "entry" for x in cur):
                poss.append(cur)
                cur = []
            cur.append(f)
            if kind in CLOSE_KINDS:
                poss.append(cur)
                cur = []
        if cur:
            poss.append(cur)
        out[k] = poss
    return out


def _by_kind(pos: List[Any]) -> Dict[str, List[Any]]:
    d: Dict[str, List[Any]] = {}
    for f in pos:
        d.setdefault(_g(f, "kind"), []).append(f)
    return d


def _closed(pos: List[Any]) -> bool:
    return any(_g(f, "kind") in CLOSE_KINDS for f in pos)


def _position_side(key: Any, ex: List[Any], sm: List[Any], sides: Optional[Dict[Any, str]]) -> Optional[str]:
    """Hướng vị thế: trường `side` của fill > sides[key] > suy luận. Suy luận: SL thấp hơn giá vào = LONG, TP cao hơn = LONG;
    hoặc fill vào của sim có trượt (giá > raw = LONG)."""
    for f in sm + ex:
        s = _g(f, "side")
        if s:
            return str(s).upper()
    if sides and sides.get(key):
        return str(sides[key]).upper()
    for pos in (sm, ex):
        ent = next((f for f in pos if _g(f, "kind") == "entry"), None)
        if ent is None:
            continue
        for f in pos:
            if _g(f, "kind") == "sl":
                return "LONG" if float(_g(f, "price")) < float(_g(ent, "price")) else "SHORT"
            if _g(f, "kind") == "tp":
                return "LONG" if float(_g(f, "price")) > float(_g(ent, "price")) else "SHORT"
    for f in sm:
        if _g(f, "kind") == "entry" and _g(f, "raw_price") and float(_g(f, "price")) != float(_g(f, "raw_price")):
            return "LONG" if float(_g(f, "price")) > float(_g(f, "raw_price")) else "SHORT"
    return None


def _fee_pct(pos: List[Any]) -> Optional[float]:
    """Tổng phí của vị thế / tổng danh nghĩa vào lệnh (entry + dca), %. Chưa đóng hoặc không có danh nghĩa -> None."""
    notional = sum(float(_g(f, "notional") or 0.0) for f in pos if _g(f, "kind") in ENTER_KINDS)
    if not _closed(pos) or notional <= 0:
        return None
    return sum(abs(float(_g(f, "fee") or 0.0)) for f in pos) / notional * 100.0


def _series(s: Any) -> Dict[Any, float]:
    """Chuỗi vốn: list số (khoá = chỉ số), list [t, v], hoặc list dict {t, equity|value}."""
    out: Dict[Any, float] = {}
    for i, x in enumerate(s or []):
        if isinstance(x, dict):
            v = x.get("equity", x.get("value"))
            out[x.get("t", i)] = float(v)
        elif isinstance(x, (list, tuple)):
            out[x[0]] = float(x[1])
        else:
            out[i] = float(x)
    return out


def compare_events(exec_events: List[Any], sim_events: List[Any], timeframe: str, budgets: Optional[Dict[str, float]] = None, *,
                   sides: Optional[Dict[Any, str]] = None, exec_equity: Any = None, sim_equity: Any = None) -> Dict[str, Any]:
    """Đối soát từng lệnh khớp của sàn (exec) với bóng sim. Hàm THUẦN, tất định, không I/O.

    exec_events / sim_events: list Fill (có thể kèm OrderRejected) dạng dataclass hoặc dict (dataclasses.asdict); sự kiện khác bị bỏ qua.
    Ghép: theo khoá (symbol nếu có, không thì slot) -> cặp VỊ THẾ có giờ bắt đầu lệch <= 1 nến `timeframe` (D5: sàn vào vài giây sau đóng nến,
    sim vào ở open) -> trong vị thế ghép theo (kind, thứ tự thứ n của kind đó), giờ lệch <= 1 nến. Vị thế/fill không ghép được tính vào only_exec / only_sim.
    Dấu bps: dương = sàn khớp KÉM hơn sim (mua đắt hơn / bán rẻ hơn); độ trễ = t_sàn − t_sim (ms). Hướng lấy từ `side` của fill,
    `sides[key]` hoặc suy luận (_position_side); không biết hướng -> bỏ qua bps của vị thế đó (đếm ở `side_unknown`).
    Fill SL của sim có thể mang thêm `level` / `extreme` (dict) để phân lớp dải SL; thiếu `level` dùng raw_price của sim, thiếu `extreme` thì chỉ biết better/not.
    Trả: kinds{kind:{matched, only_exec, only_sim, bps{n,mean,p50,p90}, latency_ms{...}}}, positions, summary, fees, equity, rejected,
    budgets, breaches, ok, enough (matched >= MIN_PAIRS), calibrated (slippage_rate đề xuất theo loại taker, None nếu < MIN_PAIRS mẫu), sl_band, pairs.
    """
    B = {**EVENT_BUDGETS, **(budgets or {})}
    tol = _frame_ms(timeframe)
    ex_fills = [e for e in exec_events or [] if _is_fill(e)]
    sm_fills = [e for e in sim_events or [] if _is_fill(e)]
    rej = {"exec": {}, "sim": {}}
    for tag, evs in (("exec", exec_events or []), ("sim", sim_events or [])):
        for e in evs:
            if _is_reject(e):
                r = str(_g(e, "reason"))
                rej[tag][r] = rej[tag].get(r, 0) + 1
    ex_pos, sm_pos = _split_positions(ex_fills), _split_positions(sm_fills)

    kinds: Dict[str, Dict[str, Any]] = {k: {"matched": 0, "only_exec": 0, "only_sim": 0, "_bps": [], "_lat": []} for k in REPORT_KINDS}

    def kd(kind: str) -> Dict[str, Any]:
        return kinds.setdefault(kind, {"matched": 0, "only_exec": 0, "only_sim": 0, "_bps": [], "_lat": []})

    pairs: List[Dict[str, Any]] = []
    pos_m = pos_ex = pos_sm = side_unknown = 0
    fee_rows: List[List[float]] = []
    adverse = {k: [] for k in TAKER_KINDS}
    sl_class = {"better": 0, "between": 0, "worse": 0, "no_extreme": 0}

    def lone(pos: List[Any], tag: str) -> None:
        for f in pos:
            kd(_g(f, "kind"))["only_" + tag] += 1

    for key in sorted(set(ex_pos) | set(sm_pos), key=lambda k: (isinstance(k, str), str(k))):
        eps, sps = ex_pos.get(key, []), sm_pos.get(key, [])
        used = set()
        for ep in eps:
            t0, best, gap = int(_g(ep[0], "t") or 0), None, None
            for j, sp in enumerate(sps):
                g = abs(int(_g(sp[0], "t") or 0) - t0)
                if j not in used and g <= tol and (gap is None or g < gap):
                    best, gap = j, g
            if best is None:
                pos_ex += 1
                lone(ep, "exec")
                continue
            used.add(best)
            sp = sps[best]
            pos_m += 1
            side = _position_side(key, ep, sp, sides)
            if side is None:
                side_unknown += 1
            ek, sk = _by_kind(ep), _by_kind(sp)
            for kind in set(ek) | set(sk):
                el, sl_ = ek.get(kind, []), sk.get(kind, [])
                for n in range(max(len(el), len(sl_))):
                    x = el[n] if n < len(el) else None
                    s = sl_[n] if n < len(sl_) else None
                    if x is None or s is None or abs(int(_g(x, "t") or 0) - int(_g(s, "t") or 0)) > tol:
                        if x is not None:
                            kd(kind)["only_exec"] += 1
                        if s is not None:
                            kd(kind)["only_sim"] += 1
                        continue
                    entering = kind in ENTER_KINDS
                    bps = _bps(float(_g(x, "price")), float(_g(s, "price")), side, entering) if side else None
                    lat = int(_g(x, "t") or 0) - int(_g(s, "t") or 0)
                    d = kd(kind)
                    d["matched"] += 1
                    d["_lat"].append(float(lat))
                    if bps is not None:
                        d["_bps"].append(bps)
                        if kind in adverse:
                            adverse[kind].append(bps)
                    row = {"key": key, "kind": kind, "seq": n, "t_exec": _g(x, "t"), "t_sim": _g(s, "t"), "bps": bps, "latency_ms": lat}
                    if kind == "sl" and side:
                        level = _g(s, "level") if _g(s, "level") is not None else _g(s, "raw_price")
                        extreme = _g(s, "extreme")
                        lb = _bps(float(_g(x, "price")), float(level), side, False) if level else None
                        eb = _bps(float(_g(x, "price")), float(extreme), side, False) if extreme else None
                        cls = _sl_class(lb, eb)          # None khi thiếu extreme
                        if lb is not None:
                            sl_class[cls or "no_extreme"] += 1
                        row["sl"], row["sl_extreme_bps"] = cls, eb
                    pairs.append(row)
            fe, fs = _fee_pct(ep), _fee_pct(sp)
            if fe is not None and fs is not None:
                fee_rows.append([fe, fs])
        pos_sm += sum(1 for j in range(len(sps)) if j not in used)
        for j, sp in enumerate(sps):
            if j not in used:
                lone(sp, "sim")

    matched = sum(d["matched"] for d in kinds.values())
    o_ex, o_sm = sum(d["only_exec"] for d in kinds.values()), sum(d["only_sim"] for d in kinds.values())
    only_sim_share = o_sm / max(1, matched + o_sm)
    out_kinds = {}
    for k, d in kinds.items():
        out_kinds[k] = {"matched": d["matched"], "only_exec": d["only_exec"], "only_sim": d["only_sim"],
                        "bps": _stats(d["_bps"]), "latency_ms": _stats(d["_lat"], 1)}

    fee_exec = sum(r[0] for r in fee_rows) / len(fee_rows) if fee_rows else None
    fee_sim = sum(r[1] for r in fee_rows) / len(fee_rows) if fee_rows else None
    fees = {"n": len(fee_rows), "exec_pct_mean": None if fee_exec is None else round(fee_exec, 5),
            "sim_pct_mean": None if fee_sim is None else round(fee_sim, 5),
            "gap_pct_mean": None if fee_exec is None else round(fee_exec - fee_sim, 5)}

    equity = None
    if exec_equity is not None and sim_equity is not None:
        a, b = _series(exec_equity), _series(sim_equity)
        keys = [k for k in a if k in b and b[k]]
        drifts = [abs(a[k] - b[k]) / abs(b[k]) * 100.0 for k in keys]
        equity = {"n": len(drifts), "max_abs_drift_pct": round(max(drifts), 4) if drifts else None}

    breaches: List[Dict[str, Any]] = []

    def breach(key: str, value: Optional[float], limit: Optional[float], msg: str) -> None:
        if value is not None and limit is not None and value > limit:
            breaches.append({"key": key, "value": round(value, 5), "limit": limit, "msg": msg})
    for k, d in out_kinds.items():
        breach(f"{k}_bps", d["bps"]["mean"], B.get(k), f"Giá khớp '{k}' của sàn kém sim quá ngưỡng (bps TB): xem lại trượt giá / mô hình khớp.")
    breach("only_sim_share", only_sim_share, B.get("only_sim_share"), "Sim khớp nhiều lệnh mà sàn không khớp: mô phỏng đang lạc quan.")
    breach("fee_gap_pct", fees["gap_pct_mean"], B.get("fee_gap_pct"), "Phí thực trên sàn cao hơn sim: xem lại giả định phí.")
    breach("equity_drift_pct", equity["max_abs_drift_pct"] if equity else None, B.get("equity_drift_pct"), "Vốn sàn lệch khỏi sim quá ngưỡng.")

    # Hiệu chỉnh (D4): slippage_rate đề xuất = trung vị bps bất lợi / 10000 (kẹp >= 0), chỉ khi đủ MIN_PAIRS mẫu cho loại đó.
    calibrated = {k: (round(max(0.0, _pct(v, 0.5)) / 10_000, 8) if len(v) >= MIN_PAIRS else None) for k, v in adverse.items()}
    n_sl = sum(sl_class.values())
    n_ext = sl_class["better"] + sl_class["between"] + sl_class["worse"]
    sl_band = {"n": n_sl, "n_with_extreme": n_ext, **sl_class,
               "between_share": round(sl_class["between"] / n_ext, 4) if n_ext >= MIN_PAIRS else None,
               "enough": n_sl >= MIN_PAIRS}
    return {
        "kinds": out_kinds, "pairs": pairs,
        "positions": {"matched": pos_m, "only_exec": pos_ex, "only_sim": pos_sm, "side_unknown": side_unknown},
        "summary": {"matched": matched, "only_exec": o_ex, "only_sim": o_sm, "only_sim_share": round(only_sim_share, 4),
                    "min_pairs": MIN_PAIRS, "enough": matched >= MIN_PAIRS},
        "fees": fees, "equity": equity, "rejected": rej, "budgets": B, "breaches": breaches, "ok": not breaches,
        "enough": matched >= MIN_PAIRS, "calibrated": calibrated, "sl_band": sl_band,
    }


# ══════════════════════════════════════════════════════════════════════════
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
from backend.core.signal import Program


SMA_DAYS = 200



def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        val = float(v)
        return default if np.isnan(val) or np.isinf(val) else val
    except (TypeError, ValueError):
        return default


def num_or_none(v: Any, nd: Optional[int] = 2) -> Optional[float]:
    """float làm tròn `nd` chữ số (nd=None: không làm tròn) hoặc None nếu không phải số / không hữu hạn (JSON an toàn)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return x if nd is None else round(x, nd)


def _base(sym: str) -> str:
    return str(sym).split(":")[-1].split("@")[0]


# ─── Chuẩn hoá lệnh (đã đóng + đang mở) ─────────────────────────────────────

def exit_category(reason: Any) -> str:
    """close_reason của engine (core/backtest.py REASONS) -> signal | stop_loss | take_profit | trailing | timeout | kill_switch | open_at_end |
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
    return {"days": int(n_days), "days_in_market_pct": num_or_none((count > 0).mean() * 100.0), "avg_exposure_pct": num_or_none(expo.mean()), "max_exposure_pct": num_or_none(expo.max()),
            "time_in_market_by_coin": {c: num_or_none(m.mean() * 100.0) for c, m in sorted(by_coin.items())},
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
        "fees_usd": num_or_none(fees_total), "net_pnl_usd": num_or_none(net), "gross_pnl_before_fees_usd": num_or_none(gross_before_fees), "fee_drag_pct": fee_drag,
        "fees_pct_of_capital": num_or_none(fees_total / initial_capital * 100.0) if initial_capital else None, "by_coin": {}, "by_year": {}, "short_pnl_usd": 0.0,
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
        "avg_win": num_or_none(avg_win) if len(wins) else None, "avg_loss": num_or_none(avg_loss) if len(losses) else None,      # độ lớn (USDT, dương); None khi không có lệnh loại đó
        "max_win": num_or_none(float(wins.max())) if len(wins) else None, "max_loss": num_or_none(float(-losses.min())) if len(losses) else None,
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
    return num_or_none(cagr_pct(eq[1:] / eq[:-1] - 1.0)), num_or_none(abs(float((eq / peak - 1.0).min())) * 100.0)


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
    out.update({"available": True, "beta": num_or_none(beta, 3), "correlation": num_or_none(corr, 4), "market_cagr": m_cagr, "market_mdd": m_mdd,
                "strategy_cagr": s_cagr, "strategy_mdd": s_mdd,
                "excess_cagr": num_or_none(s_cagr - m_cagr) if s_cagr is not None and m_cagr is not None else None,
                "strategy_total_return_pct": num_or_none((se[-1] / se[0] - 1.0) * 100.0), "market_total_return_pct": num_or_none((bq[-1] / bq[0] - 1.0) * 100.0),
                "days": int(common.shape[0] - 1)})
    return out


# ─── 4. Train vs test ───────────────────────────────────────────────────────

def _stage_numbers(block: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """(sharpe, CAGR %, MDD %) của một giai đoạn từ bộ chỉ số phẳng {sharpe, cagr_pct, mdd_pct} (năm = 365 ngày)."""
    sharpe, cagr, mdd = block.get("sharpe"), block.get("cagr_pct"), block.get("mdd_pct")
    return {"sharpe": num_or_none(sharpe) if sharpe is not None else None, "cagr": num_or_none(_safe_float(cagr)) if cagr is not None else None,
            "mdd": num_or_none(abs(_safe_float(mdd))) if mdd is not None else None}


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
    out: Dict[str, Any] = {"available": True, "market": market.get("source"), "sma_days": SMA_DAYS, "total_days": int(n_days), "total_pnl_usd": num_or_none(total_pnl)}
    for name, code in (("bull", 1), ("bear", -1), ("unknown", 0)):
        m = state == code
        d = int(m.sum())
        out[name] = {"days": d, "pct_days": num_or_none(d / n_days * 100.0), "pnl_usd": num_or_none(daily_pnl[m].sum()),
                     "pnl_share_pct": num_or_none(daily_pnl[m].sum() / total_pnl * 100.0) if abs(total_pnl) > 1e-9 else None,
                     "trades_entered": int(sum(1 for k in enter_day if m[k])), "days_in_market_pct": num_or_none((count[m] > 0).mean() * 100.0) if d else None,
                     "market_return_pct": num_or_none((np.prod(1.0 + mret[m]) - 1.0) * 100.0) if d else None,
                     "benchmark_pnl_usd": num_or_none(bench_pnl[m].sum()) if bench_pnl is not None else None}
    out["initial_capital"] = num_or_none(initial_capital) if initial_capital is not None else None
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
    from backend.alpha.compile import expr_to_vi
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
                per_symbol1[_base(sym)] = {"pct_true": num_or_none(ev.mean() * 100.0), "bars": nbars}
            rule.update({"bars": int(tot_bars), "all_true_bars": int(true_bars)})
            rule["conjuncts"] = [{"index": 1, "text_vi": nodes[0][1], "pct_true": num_or_none(true_bars / tot_bars * 100.0) if tot_bars else None, "per_symbol": per_symbol1}]
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
                    per_symbol[j][_base(sym)] = {"pct_true": num_or_none(ev[j].mean() * 100.0), "only_false_bars": only, "bars": nbars}
            rule.update({"bars": int(tot_bars), "all_true_bars": int(all_true), "near_miss_bars": int(near)})
            for j, (nd, txt) in enumerate(nodes):
                rule["conjuncts"].append({"index": j + 1, "text_vi": txt, "pct_true": num_or_none(true_c[j] / tot_bars * 100.0) if tot_bars else None,
                                          "only_false_bars": int(only_c[j]), "pct_only_false_of_bars": num_or_none(only_c[j] / tot_bars * 100.0) if tot_bars else None,
                                          "share_of_near_miss_pct": num_or_none(only_c[j] / near * 100.0) if near else None, "per_symbol": per_symbol[j]})
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


def market_series(prices: Dict[str, Tuple[np.ndarray, np.ndarray]], weights: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """Chuỗi giá thị trường để phân chế độ: BTC nếu có trong rổ; không thì chỉ số rổ rebalance ngày theo trọng số `weights` (mặc định đều) trên các coin có giá ngày hôm đó."""
    by_base: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for k, v in prices.items():
        by_base.setdefault(k.split("@")[0], v)
    if not by_base:
        return None
    if "BTC" in by_base:
        lab, cl = by_base["BTC"]
        return {"label_times": lab, "close": cl, "source": "BTC"}
    frame = pd.DataFrame({b: pd.Series(c, index=l) for b, (l, c) in by_base.items()}).sort_index()
    rets = frame.pct_change(fill_method=None)
    w = pd.Series({b: float((weights or {}).get(b, 1.0)) for b in frame.columns})
    valid = rets.notna()
    wsum = (valid * w).sum(axis=1)
    daily = (rets.fillna(0.0) * w).sum(axis=1) / wsum.where(wsum > 0)
    index = (1.0 + daily.fillna(0.0)).cumprod()
    return {"label_times": index.index.to_numpy(dtype="int64"), "close": index.to_numpy(dtype="float64"),
            "source": f"chỉ số rổ {len(by_base)} coin ({'theo trọng số' if weights else 'đều'})"}


# ══════════════════════════════════════════════════════════════════════════
# Chỉ số và kết quả cho Custom Backtest (P11 D2.2; gộp từ metrics/custom.py). Thuần tính toán: không I/O đĩa, không phụ thuộc FastAPI/routes.
# ══════════════════════════════════════════════════════════════════════════

MIN_YEAR_DAYS = 2                    # bảng yearly chỉ giữ năm có >= 2 ngày lợi suất (Sharpe/độ lệch cần >= 2)
MAX_PLOT_POINTS = 1200               # trần số điểm mỗi chuỗi giai đoạn gửi cho biểu đồ (series.stages); chuỗi ngày đầy đủ vẫn ở series.times/equity/...
MAX_POINTS = 400                     # trần số điểm mỗi chuỗi ngày trong kết quả edu_precompute (downsample_series)


def stage_split(start: int, end: int, ratio: float) -> int:
    """Mốc chia train/test (ms): đầu năm dương lịch gần nhất không sau start + ratio·(end - start) (ví dụ 2020-01-02 → 2025-01-01, 0,7 -> 2023-01-01);
    nếu mốc đó không nằm sau start ít nhất 30 ngày thì lấy chính điểm ratio (làm tròn nửa đêm UTC)."""
    point = start + ratio * (end - start)
    year = pd.Timestamp(point, unit="ms").year
    jan1 = date_ms(f"{year}-01-01")
    if jan1 - start >= 30 * DAY:
        return jan1
    return int(point // DAY * DAY)


def daily_series(curve: List[Dict[str, float]], start: int, end: int, base_ms: int, capital: float) -> Dict[str, np.ndarray]:
    """Vốn MTM tại từng mốc nửa đêm UTC b_0 = start .. b_N = end (nhãn = giờ ĐÓNG nến): mẫu engine có nhãn = open + độ dài nến chạy (vốn là giá đóng cửa)."""
    bounds = np.arange(start, end + 1, DAY, dtype="int64")
    pts = [(int(c["time"]) + base_ms, float(c["equity"])) for c in curve if c["time"] >= start]
    if not pts:
        eq = np.full(bounds.shape[0], float(capital))
    else:
        t = np.asarray([p[0] for p in pts], dtype="int64")
        v = np.asarray([p[1] for p in pts], dtype="float64")
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
        idx = np.searchsorted(t, bounds, side="right") - 1
        eq = np.where(idx >= 0, v[np.maximum(idx, 0)], float(capital))
    ret = np.zeros(eq.shape[0])
    ret[1:] = eq[1:] / eq[:-1] - 1.0
    return {"times": bounds, "equity": eq, "returns": ret}


def _segments(times: np.ndarray, split: int) -> Dict[str, np.ndarray]:
    n = times.shape[0]
    return {"simulate": np.ones(n, dtype=bool), "train": times <= split, "test": times > split}


def _metric_block(ret: np.ndarray, rows: List[Dict[str, Any]], fees: float) -> Dict[str, Any]:
    """Bộ chỉ số phẳng của Nora (metrics/metrics: năm = 365 ngày, Sharpe/Sortino/CAGR trên lợi suất ngày MTM; lệnh: win rate, profit factor theo lệnh đóng)."""
    from backend.metrics.metrics import series_metrics
    m = series_metrics(ret[1:] if ret.size else ret, rows)    # bỏ phần tử 0 đứng đầu (không phải ngày giao dịch)
    return {"ret_pct": m["ret_pct"], "mdd_pct": m["mdd_pct"], "sharpe": m["sharpe"], "sortino": m["sortino"], "cagr_pct": m.get("cagr_pct"),
            "calmar": m.get("calmar"), "trades": m["trades"], "win_rate_trades": m["win_rate"], "profit_factor_trades": m["profit_factor"],
            "fees_usd": round(fees, 2)}


def build_metrics(series: Dict[str, np.ndarray], split: int, trade_rows: List[Dict[str, Any]], orders: List[Any],
                  test_run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """metrics.{simulate,train,test}: MỘT bộ chỉ số phẳng mỗi giai đoạn. simulate/train cắt lát đường vốn của lần chạy đầy đủ; test lấy từ `test_run` =
    {series, rows, orders} (lần chạy riêng bắt đầu lại từ vốn đầu tại mốc chia) nếu có, không thì cắt lát."""
    from backend.metrics.metrics import ANN   # nhập muộn: metrics.metrics nhập metrics.trades (tránh vòng nhập)
    times, ret = series["times"], series["returns"]
    out: Dict[str, Any] = {}
    for name, m in _segments(times, split).items():
        if name == "test" and test_run is not None:
            fees = sum(float(o.fee_usd or 0.0) for o in test_run["orders"])
            out[name] = _metric_block(test_run["series"]["returns"], test_run["rows"], fees)
            continue
        lo = int(times[m][0]) if m.any() else 0
        hi = int(times[m][-1]) if m.any() else 0
        rows = [r for r in trade_rows if lo < r["close_time"] <= hi] if name != "simulate" else trade_rows
        fees = sum(float(o.fee_usd or 0.0) for o in orders if lo < o.order_time <= hi + DAY) if name != "simulate" else sum(float(o.fee_usd or 0.0) for o in orders)
        out[name] = _metric_block(ret[m], rows, fees)
    basis = ("simulate/train cắt lát đường vốn của lần chạy đầy đủ (train bắt đầu tại start nên trùng); test và các năm giai đoạn test tính từ lần chạy lại "
             "[mốc chia, end] bắt đầu từ vốn đầu" if test_run is not None else
             "train/test/yearly cắt lát đường vốn liên tục")
    out["notes"] = {"stage_basis": basis, "annualization_days": ANN, "test_fresh_capital": test_run is not None}
    return out


def _year_rows(series: Dict[str, np.ndarray], rows: List[Dict[str, Any]], stage: str, upto: Optional[int] = None) -> List[Dict[str, Any]]:
    times, ret = series["times"], series["returns"]
    years = np.asarray([pd.Timestamp(int(t) - 1, unit="ms").year for t in times])   # nến thuộc năm của giờ mở (nhãn - 1ms)
    keep = np.arange(times.shape[0]) > 0
    if upto is not None:
        keep &= times <= upto
    out = []
    for y in sorted(set(years.tolist())):
        m = (years == y) & keep
        if int(m.sum()) >= MIN_YEAR_DAYS:      # năm chỉ có 1 ngày lợi suất (vd. năm trước start 1 ngày) không có chỉ số -> bỏ
            lo, hi = int(times[m][0]) - DAY, int(times[m][-1])
            blk = _metric_block(np.r_[0.0, ret[m]], [r for r in rows if lo < r["close_time"] <= hi], 0.0)
            out.append({"year": int(y), "stage": stage, "days": int(m.sum()), **{k: blk[k] for k in ("cagr_pct", "sharpe", "mdd_pct", "profit_factor_trades", "calmar")}})
    return out


def yearly_table(series: Dict[str, np.ndarray], split: int, rows: List[Dict[str, Any]], test_series: Optional[Dict[str, np.ndarray]] = None,
                 test_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Bảng theo năm cùng bộ chỉ số phẳng: năm train từ đường vốn đầy đủ; năm test từ lần chạy lại từ vốn đầu (`test_series`) nếu có, không thì cắt lát."""
    if test_series is None:
        times = series["times"]
        years = np.asarray([pd.Timestamp(int(t) - 1, unit="ms").year for t in times])
        out = _year_rows(series, rows, "train")
        for r in out:
            m = (years == r["year"]) & (np.arange(times.shape[0]) > 0)
            r["stage"] = "train" if times[m][-1] <= split else "test"
        return out
    return _year_rows(series, rows, "train", upto=split) + _year_rows(test_series, test_rows or [], "test")


def _bench_on(bench: Optional[Dict[str, Any]], times: np.ndarray) -> Optional[np.ndarray]:
    """Đường vốn benchmark nếu cùng lưới ngày với `times`, không thì None (không nội suy / co dãn)."""
    if bench is None:
        return None
    bt = np.asarray(bench["times"], dtype="int64")
    return np.asarray(bench["equity"], dtype="float64") if bt.shape == times.shape and np.array_equal(bt, times) else None


def build_stages(series: Dict[str, np.ndarray], split: int, test_series: Optional[Dict[str, np.ndarray]], bench: Optional[Dict[str, Any]],
                 test_bench: Optional[Dict[str, Any]], max_points: int = MAX_PLOT_POINTS) -> Dict[str, Any]:
    """series.stages = {all, train, test}: mỗi giai đoạn tính trên dữ liệu ngày đầy đủ (equity, pnl, drawdown_pct, ret_pct, benchmark) rồi hạ mẫu CHỈ để vẽ
    (metrics/charts.stage_block). Test = lần chạy lại từ vốn đầu tại mốc chia + benchmark chạy lại cùng cửa sổ (không co dãn); thiếu thì None."""
    from backend.metrics.charts import downsample_stage, stage_block
    times, eq = series["times"], series["equity"]
    label = (bench or {}).get("label")
    beq = _bench_on(bench, times)
    m = times <= split
    out: Dict[str, Any] = {
        "all": stage_block(times, eq, beq, label),
        "train": stage_block(times[m], eq[m], None if beq is None else beq[m], label) if m.any() else None,
        "test": None,
    }
    if test_series is not None:
        tb = _bench_on(test_bench, test_series["times"])
        out["test"] = stage_block(test_series["times"], test_series["equity"], tb, (test_bench or {}).get("label"))
    return {k: downsample_stage(v, max_points) for k, v in out.items()}


def build_result(program, plan, res, eng, a, start: int, end: int, capital: float, data: Dict[str, Any], extra_warnings: List[str],
                 test_res: Optional[Dict[str, Any]] = None, test_start: Optional[int] = None, bench: Optional[Dict[str, Any]] = None,
                 inputs: Optional[Dict[str, Any]] = None, test_bench: Optional[Dict[str, Any]] = None,
                 alpha_id: Optional[str] = None, checklist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.core.strategy import FRAME_MS
    from backend.metrics.metrics import result_payload
    from backend.metrics.trades import rows_from_trade_list
    payload = result_payload(res, start, end)
    trades = payload["trade_list"]
    rows = rows_from_trade_list(trades)
    series = daily_series(res["equity_curve"], start, end, FRAME_MS[plan.base_frame], capital)
    split = stage_split(start, end, float(a.train_ratio))
    test_run = test_series = None
    if test_res is not None:
        test_series = daily_series(test_res["equity_curve"], test_start, end, FRAME_MS[plan.base_frame], capital)
        test_run = {"series": test_series, "rows": rows_from_trade_list(result_payload(test_res, test_start, end)["trade_list"]), "orders": test_res["orders"]}
    metrics = build_metrics(series, split, rows, res["orders"], test_run)
    eq = series["equity"]
    peak = np.maximum.accumulate(eq)
    series_out = {"times": [int(t // 1000) for t in series["times"]], "equity": [round(float(x), 2) for x in eq],
                  "pnl": [round(float(x - capital), 2) for x in eq], "drawdown": [round(float(x), 6) for x in eq / peak - 1.0],
                  "stage_split": int(split // 1000)}
    if test_series is not None:
        teq = test_series["equity"]
        series_out["test"] = {"times": [int(t // 1000) for t in test_series["times"]], "equity": [round(float(x), 2) for x in teq],
                              "drawdown": [round(float(x), 6) for x in teq / np.maximum.accumulate(teq) - 1.0]}
        if test_bench is not None:
            tbe = test_bench["equity"]
            series_out["test"]["benchmark"] = {"times": [int(t // 1000) for t in test_bench["times"]], "equity": [round(float(x), 2) for x in tbe],
                                               "label": test_bench["label"], "final_equity": round(float(tbe[-1]), 2)}
    opens = eng.open_positions()
    by_symbol = []
    for sym in plan.symbols:
        agg = res["by_symbol"].get(sym, {})
        by_symbol.append({"symbol": sym.split(":")[-1], "pnl_usd": round(agg.get("pnl_usd", 0.0), 2), "trades": int(agg.get("trades", 0)),
                          "wins": int(agg.get("wins", 0)), "fees_usd": round(agg.get("fees_usd", 0.0), 2),
                          "open_pnl_usd": round(sum(o["unrealized_pnl"] for o in opens if o["symbol"] == sym), 2)})
    warns = list(dict.fromkeys(program.warnings + plan.warnings + extra_warnings))
    from backend.metrics.trades import diagnose_run
    from backend.metrics.charts import generate_insights
    fees_total = sum(float(o.fee_usd or 0.0) for o in res["orders"])
    inputs = inputs or {}
    diagnostics = diagnose_run(program, series, trades, metrics, capital, start, end, fees_total=fees_total, open_positions=opens, benchmark=bench,
                               market=inputs.get("market"), prices=inputs.get("prices"), frames=inputs.get("frames"))
    insights = generate_insights(diagnostics, metrics)
    if bench is not None:
        beq = bench["equity"]
        series_out["benchmark"] = {"times": [int(t // 1000) for t in bench["times"]], "equity": [round(float(x), 2) for x in beq], "label": bench["label"],
                                   "final_equity": round(float(beq[-1]), 2)}
    warns += [f"chẩn đoán thiếu dữ liệu: {e}" for e in inputs.get("errors", [])]
    series_out["stages"] = build_stages(series, split, test_series, bench, test_bench)
    if test_series is not None and test_bench is None:
        warns.append("không có benchmark cho giai đoạn Test (chạy lại benchmark cửa sổ test không thành công)")
    from backend.alpha.compile import explain_program
    from backend.metrics.charts import build_notes
    out = {
        "config": {"symbols": [s.split("@")[0] for s in plan.symbols], "data_symbols": plan.symbols, "start": iso_date(start),
                   "end": iso_date(end - DAY), "train_ratio": float(a.train_ratio), "initial_capital": capital, "timeframe": program.timeframe,
                   "run_frame": plan.base_frame, "exchange": data["source"], "program": {"name": program.name, "legs": program.legs,
                   "levels": program.levels, "features": program.features, "warmup_bars": program.warmup_bars},
                   "risk": plan.risk, "strategies": [s["id"] for s in plan.strategies], **plan.echo},
        "program_hash": program.code_hash, "data": data, "metrics": metrics, "yearly": yearly_table(series, split, rows, test_series, test_run["rows"] if test_run else None),
        "series": series_out,
        "trades": trades, "positions_open": opens, "by_symbol": by_symbol, "warnings": warns,
        "diagnostics": diagnostics, "insights": insights,
        "final_equity": round(float(eq[-1]), 2) if eq.size else capital,
    }
    logic = explain_program(program, position=a.position)
    out["explain"] = {**logic, "notes": build_notes(logic, out)}
    if alpha_id is not None:
        out["alpha_id"] = alpha_id
    if checklist is not None:
        out["checklist"] = checklist
    return out


def downsample_series(series: Dict[str, Any], max_points: int = MAX_POINTS) -> Dict[str, Any]:
    """Hạ mẫu các chuỗi ngày (cùng chỉ số cho times/equity/pnl/drawdown/benchmark) còn <= max_points điểm, luôn giữ điểm đầu và cuối."""
    def pick(n: int) -> List[int]:
        return list(range(n)) if n <= max_points else sorted(set(np.linspace(0, n - 1, max_points).round().astype(int).tolist()))

    def cut(block: Dict[str, Any]) -> Dict[str, Any]:
        n = len(block.get("times", []))
        idx = pick(n)
        out = dict(block)
        for k, v in block.items():
            if isinstance(v, list) and len(v) == n:
                out[k] = [v[i] for i in idx]
        return out

    from backend.metrics.charts import downsample_stage
    out = cut({k: v for k, v in series.items() if k not in ("test", "benchmark", "stages")})
    for k in ("test", "benchmark"):
        if k in series:
            blk = dict(series[k])
            nested = blk.pop("benchmark", None)       # series.test.benchmark (benchmark chạy lại trên cửa sổ test) cắt cùng lưới riêng
            out[k] = cut(blk)
            if nested is not None:
                out[k]["benchmark"] = cut(nested)
    if "stages" in series:      # chuỗi giai đoạn ĐÃ tính ở backend: chỉ gom nhóm để vẽ (series_stages.downsample_stage), không tính lại
        out["stages"] = {k: downsample_stage(v, max_points) for k, v in series["stages"].items()}
    out["downsampled_from"] = len(series.get("times", []))
    return out


def _episodes(mask: np.ndarray):
    """[(đầu, cuối+1)] các đoạn True liên tiếp."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def label_stats(s: Dict[str, np.ndarray], start: int) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    n = len(t)
    days = (t[-1] - t[0]) / DAY if n > 1 else 0.0
    # mẫu mỗi giờ: lợi suất 24h tới (phút cuối cùng <= t + 24h)
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    ok = (t[fwd_idx] >= t[hourly] + DAY - HOUR)
    h, fi = hourly[ok], fwd_idx[ok]
    fwd = (close[fi] / close[h] - 1.0) * 100.0
    out: Dict[str, Any] = {"minutes": int(n), "days": round(days, 1), "states": {}}
    switches = int((np.diff(lab.astype(np.int16)) != 0).sum())
    out["switches_per_30d"] = round(switches / days * 30, 2) if days else None
    for code, name in enumerate(rg.NAMES):
        m = lab == code
        if not m.any():
            continue
        eps = _episodes(m)
        dur = [(t[e - 1] - t[b]) / HOUR + 1 / 60 for b, e in eps]
        r = fwd[lab[h] == code]
        out["states"][name] = {
            "share_pct": round(100 * m.mean(), 2), "episodes": len(eps), "avg_hours": round(float(np.mean(dur)), 1),
            "fwd24_n": int(r.size),
            "fwd24_mean_pct": round(float(r.mean()), 3) if r.size else None,
            "fwd24_median_pct": round(float(np.median(r)), 3) if r.size else None,
            "fwd24_up_pct": round(float((r > 0).mean() * 100), 1) if r.size else None,
            "fwd24_abs_pct": round(float(np.abs(r).mean()), 3) if r.size else None,
        }
    return out


def shock_stats(s: Dict[str, np.ndarray], start: int, event_pct: float) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    fwd = (close[fwd_idx] / close[hourly] - 1.0) * 100.0
    out = {}
    for name, code, sign in (("CRASH", rg.CRASH, -1), ("SURGE", rg.SURGE, 1)):
        ev = sign * fwd >= event_pct
        rows = []
        for b, e in _episodes(ev):
            i0 = hourly[b]
            i1 = int(np.searchsorted(t, t[i0] + DAY, side="right"))
            hit = np.flatnonzero(lab[i0:i1] == code)
            already = None
            # cực trị của đợt trong 24h sau đầu đợt (đáy với sập, đỉnh với tăng)
            seg = close[i0:i1]
            ext = int(np.argmin(seg) if sign < 0 else np.argmax(seg))
            total = seg[ext] / close[i0] - 1.0
            lag = None
            if hit.size:
                k = int(hit[0])
                lag = int((t[i0 + k] - t[i0]) // MINUTE)
                already = round(100 * (close[i0 + k] / close[i0] - 1.0) / total, 1) if total else None
            rows.append({"start": int(t[i0]), "move_pct": round(100 * total, 2), "detected": bool(hit.size), "lag_min": lag,
                         "move_done_pct": already})
        det = [r for r in rows if r["detected"]]
        alarms = []
        for b, e in _episodes(lab == code):
            j = int(np.searchsorted(t, t[b] + DAY, side="right")) - 1
            if t[j] >= t[b] + DAY - HOUR:
                alarms.append((close[j] / close[b] - 1.0) * 100.0)
        alarms = np.asarray(alarms)
        out[name] = {
            "events": len(rows), "detected": len(det),
            "recall_pct": round(100 * len(det) / len(rows), 1) if rows else None,
            "median_lag_min": int(np.median([r["lag_min"] for r in det])) if det else None,
            "median_move_done_pct": float(np.median([r["move_done_pct"] for r in det if r["move_done_pct"] is not None]))
            if det else None,
            "alarms": int(alarms.size),
            # cầu chì đúng khi sau khi bật giá TIẾP TỤC cùng chiều sốc (vị thế ngược chiều bị cắt là tránh lỗ thêm)
            "alarm_continuation_pct": round(float((sign * alarms > 0).mean() * 100), 1) if alarms.size else None,
            "alarm_fwd24_mean_pct": round(float(alarms.mean()), 3) if alarms.size else None,
            "worst_events": sorted(rows, key=lambda r: sign * -r["move_pct"])[:5],
        }
    return out
