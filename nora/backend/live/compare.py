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
