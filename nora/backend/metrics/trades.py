# P9.5 — chuyển NGUYÊN VĂN từ core/metrics/trades.py (đường dẫn cũ là shim). Còn chờ: live/compare.py (đối soát sàn <-> sim) sẽ về đây sau P9.4b.
"""Số đo theo LỆNH (đã đóng) và theo phơi nhiễm vốn: bảng lệnh phẳng, thắng/thua, profit factor, payoff, expectancy, chuỗi thua,
độ tập trung lãi, thời gian giữ, tách long/short, phí/funding, DCA (tầng, lỗ treo, độ gần thanh lý), ký quỹ/exposure theo thời gian.

Quy ước:
  - thắng = PnL > 0, thua = PnL < 0, hoà (= 0) đếm riêng; win_rate = thắng / tổng lệnh (hoà làm giảm win_rate, không tính là thua);
  - profit_factor = Σ lãi / Σ lỗ. KHÔNG có lệnh lỗ (Σ lỗ = 0) thì PF không xác định -> None + `profit_factor_note` nêu lý do (không còn số chặn 99);
    0 lệnh -> win_rate = None, profit_factor = None (+ ghi chú), không phải 0 giả. Giao diện hiện "—" + lý do;
  - cổng phễu (optimize/funnel/gates.py) KHÔNG đọc win_rate / profit_factor nên đổi này không đổi quyết định cổng nào; nếu sau này cổng đọc PF,
    "không có lệnh thua" (profit_factor_note == NOTE_NO_LOSSES) phải được coi là ĐẠT tiêu chí PF (hành vi cũ: PF = 99 ≥ mọi ngưỡng), đừng so None với số;
  - payoff = TB lệnh thắng / |TB lệnh thua|; expectancy = PnL trung bình mỗi lệnh (USD và % vốn lúc mở lệnh);
  - fee_drag_pct = phí / lãi trước phí (phần lãi gộp bị phí ăn mất); None khi lãi trước phí <= 0;
  - liq_proximity_pct = |lỗ treo tối đa của lệnh| / ký quỹ của lệnh × 100 (100 = mất hết ký quỹ = thanh lý, isolated);
  - ký quỹ / exposure theo thời gian dựng lại từ [enter, close] của lệnh với ký quỹ CUỐI của lệnh (sau mọi tầng DCA) -> hơi cao hơn
    thực tế trước khi nhồi; tính theo % vốn ban đầu.
"""
from typing import Any, Dict, List, Optional

import numpy as np

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
