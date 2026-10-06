"""Trade-by-trade comparison Nora vs Nautilus for the extended stages (S4-S8) + mismatch classification.
Usage: ~/.venvs/nora/bin/python test/scripts/nautilus_diff/ext_compare.py [path=ohlc|adaptive] [stage-prefix|all]
Classes (S1-S3 classes kept): a same-bar/tick ordering | b gap at open | c rounding | d timing (funding settlement at the entry/exit tick)
  x cascade (downstream of an earlier classified divergence) | e UNEXPLAINED
New classes: l liquidation model (Nora isolated intrabar level vs Nautilus account-level bar-close check) |
  p portfolio sequencing (Nora admits symbol B at open t AFTER processing symbol A's whole bar t) | t trailing tick order (peak/trigger update order)
"""
import json
import os
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ext_common import skip, CAPITAL, DATASETS, H, OUT, SIGNALS, STAGES, tag  # noqa: E402

TICK = 1e-8
REASON = {"Stop-loss": "SL", "Take-profit": "TP", "Tín hiệu": "SIG", "Hết thời gian": "TIMEOUT", "Trailing": "TRAIL", "Thanh lý": "LIQ",
          "End of": "END", "Kill": "KILL"}


def reason_n(s):
    for k, v in REASON.items():
        if s.startswith(k):
            return v
    return s


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def load(p):
    return json.load(open(p))


def bar_levels(avg, st, s):
    sl, tp = st.get("sl", 0.0), st.get("tp", 0.0)
    return (avg * (1 - s * sl / 100) if sl else None), (avg * (1 + s * tp / 100) if tp else None)


def compare(ds, sname, stname, path, variant=""):
    """variant "_sync": Nora run with the time-synchronous (look-ahead free) admission view instead of its production view (S8 counterfactual)."""
    st = STAGES[stname]
    s = 1 if st["side"] == "L" else -1
    nn = load(os.path.join(OUT, f"nora_{tag(ds, sname, stname, path)}{variant}.json"))
    na = load(os.path.join(OUT, f"nautilus_{tag(ds, sname, stname, path)}.json"))
    bars = {sym: pd.read_csv(os.path.join(OUT, f"bars_{sym}_{ds}.csv")) for sym in st["syms"]}
    bar0 = int(bars[st["syms"][0]].open_time.iloc[0])
    idx = {sym: {int(t): i for i, t in enumerate(b.open_time)} for sym, b in bars.items()}
    for t in na["trades"]:                       # stop/limit/liquidation fills are stamped with the bar close -> use the bar open time (Nora numbering)
        if t["reason"] in ("SL", "TP", "TRAIL", "LIQ"):
            t["close_time"] = bar0 + t["bar_exit"] * H
    sym_of_n = lambda t: t.get("sym", st["syms"][0])  # noqa: E731
    N = {(sym_of_n(t), t["enter_time"]): dict(t, r=reason_n(t["reason"])) for t in nn["trades"]}
    A = {(t["sym"], t["enter_time"]): dict(t, r=t["reason"]) for t in na["trades"]}
    order = {sym: k for k, sym in enumerate(st["syms"])}
    dec = {(d["t"], d["sym"]): d for d in nn.get("decisions", [])}
    adm_a = {(r[0], r[1]): r for r in na.get("admit_log", [])}
    ruin = next((t["close_time"] for t in sorted(na["trades"], key=lambda t: t["close_time"]) if t["equity_after"] <= 0), None)
    rows, cls = [], Counter()
    div_end = {}                                 # per symbol (or "*" for portfolio): latest close time of a classified divergence
    exact = 0
    portfolio = len(st["syms"]) > 1
    for key in sorted(set(N) | set(A), key=lambda k: (k[1], k[0])):
        sym, et = key
        n, a = N.get(key), A.get(key)
        dk = "*" if portfolio else sym
        row = {"sym": sym, "enter_time": et, "cls": None, "note": ""}
        if n is None or a is None:
            who = "nautilus-only" if n is None else "nora-only"
            tr_ = a if a is not None else n
            dust = tr_["qty"] * tr_["avg_price"] < 0.01
            if portfolio and a is not None and dust:
                i_ = idx[sym][et] - 1
                r_ = adm_a.get((i_, sym))
                row.update(cls="c", note=f"dust entry from a knife-edge: the cap leaves room {r_[6] if r_ else float('nan'):.3g} USDT (earlier entries sized to "
                                         f"exactly fill max_gross_exposure); Nora's float arithmetic gives room <= 0 (rejected), Nautilus' 8-decimal qty "
                                         f"rounding leaves a positive notional {tr_['qty'] * tr_['avg_price']:.3g} USDT")
            elif a is not None and a.get("stray"):
                row.update(cls="x", note="stray DCA fill: a resting DCA limit filled in the same tick right AFTER a stop closed the position "
                                         "(Nautilus matches bid-side orders before ask-side orders: for shorts exits first, then DCA); "
                                         "consequence of the class-a trade before it")
            elif ruin is not None and et > ruin and a is None:
                row.update(cls="x", note="Nautilus account ruined (balance <= 0 after an uncapped liquidation, strategy stops entering); Nora's isolated "
                                         "liquidation caps the loss at margin+fees so it keeps trading")
            elif dk in div_end and et <= div_end[dk] + 3 * H:
                row.update(cls="x", note=f"{who} trade inside cascade window of an earlier classified divergence")
            elif portfolio:
                d_ = dec.get((et, sym))
                if n is not None and d_ and d_["nora"]["can"] and not d_["sync"]["can"]:
                    row.update(cls="p", note=(f"Nora admitted at open {et}: its view had n_open={d_['nora']['n_open']}, gross={d_['nora']['gross']:.2f}, "
                                              f"eq={d_['nora']['eq']:.2f} (earlier symbol(s) already closed intrabar in this bar); the time-synchronous view "
                                              f"has n_open={d_['sync']['n_open']}, gross={d_['sync']['gross']:.2f}, eq={d_['sync']['eq']:.2f} -> blocked "
                                              f"(Nautilus does not take the trade)"))
                elif a is not None and d_ and (not d_["nora"]["can"]) and d_["sync"]["can"]:
                    row.update(cls="p", note=(f"Nora rejected: its view had n_open={d_['nora']['n_open']}, gross={d_['nora']['gross']:.2f}; the "
                                              f"time-synchronous view admits (n_open={d_['sync']['n_open']}, gross={d_['sync']['gross']:.2f})"))
                else:
                    row.update(cls="e", note=f"{who} trade in portfolio run, no look-ahead evidence in the decision log {d_}")
            else:
                row.update(cls="e", note=f"{who} trade, no preceding divergence")
            if row["cls"] in ("a", "b", "d", "l", "p", "c"):
                other = n if n is not None else a
                div_end[dk] = max(div_end.get(dk, 0), other["close_time"])
            rows.append(row)
            cls[row["cls"]] += 1
            continue
        b_idx = idx[sym]
        fields = []
        if rel(a["enter_price"], n["enter_price"]) > 1e-9:
            fields.append("enter_price")
        if a["close_time"] != n["close_time"]:
            fields.append("close_time")
        if a["r"] != n["r"]:
            fields.append("reason")
        if "close_time" not in fields and rel(a["close_price"], n["close_price"]) > 1e-9:
            fields.append("close_price")
        ee_n, ee_a = n["entry_equity"], a["entry_equity"]
        nq_n, nq_a = n["qty"] * n["avg_price"] / ee_n, a["qty"] * a["avg_price"] / ee_a
        qty_rel = rel(nq_a, nq_n)
        qty_tol = 0.5e-8 * max(1, a.get("layers", 1)) / a["qty"] + 1e-9      # size precision 8 (lot rounding)
        if portfolio:                                             # cap-clamped sizes inherit the 8-decimal qty rounding of the other legs' gross
            qty_tol = max(qty_tol, 2e-7, 1e-4 / max(a["qty"] * a["enter_price"], 1e-12))      # abs 1e-4 USDT of gross rounding
        if qty_rel > qty_tol:
            fields.append("qty")
        rn, ra = n["pnl"] / ee_n, a["pnl"] / ee_a
        pred = rn * nq_a / nq_n
        pnl_resid = abs(ra - pred)
        fund_diff = abs(a["funding"] - n.get("funding", 0.0))
        fund_tol = 2e-6 * max(abs(n.get("funding", 0.0)), 1.0) + 1e-6
        price_slack = (1e-8 / n["enter_price"] + 1e-8 / n["close_price"]) * nq_a + 1e-9 + (qty_tol if portfolio else 0.0) * abs(rn) * 0.01
        if not fields and pnl_resid > price_slack:
            fields.append("pnl")
        if "pnl" not in fields and "close_time" not in fields and st.get("fund") and fund_diff > fund_tol:
            fields.append("funding")
        row["eq_rel"] = rel(ee_a, ee_n)
        if portfolio:
            row["lookahead_pnl"] = sum(u["pnl"] for u in nn["trades"] if order[u["sym"]] < order[sym] and u["close_time"] == et
                                       and not reason_n(u["reason"]) in ("SIG", "TIMEOUT"))
            row["qty_rel_signed"] = (n["qty"] - a["qty"]) / a["qty"] if a["qty"] * a["enter_price"] > 1.0 else 0.0
        row.update(qty_rel_diff=qty_rel, pnl_ret_nora=rn, pnl_ret_naut=ra, pnl_resid=pnl_resid, fund_nora=n.get("funding", 0.0),
                   fund_naut=a["funding"], nora=[n["enter_price"], n["close_time"], n["close_price"], n["r"]],
                   naut=[a["enter_price"], a["close_time"], a["close_price"], a["r"]], fields=list(fields))
        if not fields:
            exact += 1
            row["cls"] = "match"
            if qty_rel > 1e-12:
                row["note"] = "match (qty rounded to lot)"
            rows.append(row)
            cls["match"] += 1
            continue
        c, note = None, ""
        if portfolio and set(fields) <= {"qty", "pnl"}:
            d_, r_ = dec.get((et, sym)), adm_a.get((b_idx[et] - 1, sym))
            vw = "sync" if variant else "nora"                       # the view that was actually applied in this Nora run
            n_not, a_not = n["qty"] * n["enter_price"], a["qty"] * a["enter_price"]
            if d_ and d_["nora"]["can"] and not d_["sync"]["can"] and variant == "":
                c, note = "p", (f"Nora admits (n_open={d_['nora']['n_open']}, gross={d_['nora']['gross']:.2f}: earlier symbols already closed intrabar in this bar), "
                                f"the time-synchronous view blocks (n_open={d_['sync']['n_open']}, gross={d_['sync']['gross']:.2f}, cap binding); Nautilus "
                                f"enters only a knife-edge dust size {a_not:.3g} USDT vs Nora {n_not:.2f} USDT")
            if c is None and d_ and r_ and rel(d_[vw]["mnn"], r_[6]) > 1e-6 and d_[vw]["mnn"] < 1e18:
                if rel(n_not, d_[vw]["mnn"]) < 1e-6 or rel(a_not, r_[6]) < 1e-5:
                    c, note = "p", (f"gross-exposure room differs: Nora notional {n_not:.2f} (room {d_[vw]['mnn']:.2f}, gross {d_[vw]['gross']:.2f}, "
                                    f"eq {d_[vw]['eq']:.2f}) vs Nautilus {a_not:.2f} (room {r_[6]:.2f}, gross {r_[4]:.2f}, eq {r_[5]:.2f}); Nora marks "
                                    f"earlier-order symbols at close[t] and counts their intrabar closes, Nautilus has only the state at the open")
            if c is None and d_ and r_ and d_[vw]["mnn"] < 1e18 and rel(ee_a, ee_n) > 1e-9 and (
                    rel(n_not, d_[vw]["mnn"]) < 1e-6 or rel(a_not, r_[6]) < 1e-5):
                c, note = "p", (f"cap-clamped size follows the entry equity, which differs (Nora {ee_n:.4f}, Nautilus {ee_a:.4f}): Nora sizes with a ledger "
                                f"that already holds the intrabar PnL of earlier-order symbols' bar t")
        if c is None:
            c, note = classify(st, s, ds, sym, n, a, fields, bars[sym], b_idx, nn, na, row)
        if c in ("a", "b", "d", "l", "t", "p", "c") or "close_time" in fields:
            div_end[dk] = max(div_end.get(dk, 0), n["close_time"], a["close_time"])
        row.update(cls=c, note=note)
        rows.append(row)
        cls[c] += 1
    fe_n = nn["final_equity"]
    fe_a = na["final_equity_nora_def"]
    return {"dataset": ds, "signal": sname, "stage": stname, "path": path, "trades_nora": len(N), "trades_naut": len(A),
            "matched_pairs": sum(1 for e in N if e in A), "exact_matches": exact, "classes": dict(cls),
            "final_equity_nora": fe_n, "final_equity_naut": fe_a, "final_equity_diff_pct": (fe_a / fe_n - 1) * 100,
            "bit_identical": nn.get("tracker_eq_manager_bit_identical"), "rows": rows,
            "funding_nora": sum(t.get("funding", 0.0) for t in nn["trades"]), "funding_naut": sum(t["funding"] for t in na["trades"]),
            "rejected_for_risk": nn.get("rejected_for_risk"), "variant": variant,
            "entry_equity_differs": sum(1 for x in rows if x.get("eq_rel", 0) > 1e-9),
            "entry_equity_max_rel": max([x.get("eq_rel", 0) for x in rows] or [0]),
            "sizing_lookahead_trades": sum(1 for x in rows if x.get("lookahead_pnl", 0) != 0),
            "sizing_lookahead_max_qty_rel": max([abs(x.get("qty_rel_signed", 0)) for x in rows if x.get("lookahead_pnl", 0) != 0] or [0])}


def classify(st, s, ds, sym, n, a, fields, bars, idx, nn, na, row):
    """Return (class, note). Rules are evidence based: each one checks the bar data / fills that explain the difference."""
    t0 = min(n["close_time"], a["close_time"])
    b = bars.iloc[idx[t0]] if t0 in idx else None
    avg = n["avg_price"]
    sl_lv, tp_lv = bar_levels(avg, st, s)
    fav = (lambda bb: bb.high) if s > 0 else (lambda bb: bb.low)
    adv = (lambda bb: bb.low) if s > 0 else (lambda bb: bb.high)
    reach_sl = b is not None and sl_lv is not None and (adv(b) <= sl_lv if s > 0 else adv(b) >= sl_lv)
    reach_tp = b is not None and tp_lv is not None and (fav(b) >= tp_lv if s > 0 else fav(b) <= tp_lv)
    kinds = {n["r"], a["r"]}
    # ---- liquidation model (S5) ----
    if "LIQ" in kinds:
        return liq_rule(st, s, n, a, bars, idx, row)
    # ---- timeout exit on gapped data: Nora closes at the open of bar t, the Nautilus strategy at the close of bar t-1 (open != previous close) ----
    if n["r"] == "TIMEOUT" and a["r"] == "TIMEOUT" and set(fields) <= {"close_price", "pnl"} and n["close_time"] in idx:
        k = idx[n["close_time"]]
        o_, pc = float(bars.open.iloc[k]), float(bars.close.iloc[k - 1])
        if rel(n["close_price"], o_) < 1e-9 and rel(a["close_price"], pc) < 1e-9 and rel(o_, pc) > 1e-9:
            return "d", f"timeout exit timing: Nora fills at open[t]={o_} (gap), Nautilus market order at close[t-1]={pc}"
    # ---- funding ----
    if st.get("fund") and set(fields) <= {"pnl", "funding"}:
        return funding_rule(st, s, n, a, bars, idx, sym, row)
    # ---- S3-style rules (stale SL, DCA & TP same bar), generalised to the short side ----
    if st.get("dca_steps"):
        r = dca_rules(st, s, n, a, bars, idx, b, tp_lv, sl_lv, reach_tp)
        if r:
            return r
    if ("reason" in fields or "close_time" in fields) and reach_sl and reach_tp:
        return "a", (f"both SL and TP reachable in bar {pd.to_datetime(t0, unit='ms')}: Nora={n['r']}@{n['close_time']}, "
                     f"Nautilus={a['r']}@{a['close_time']}")
    if st.get("trail") and ("TRAIL" in kinds):
        r = trail_rule(st, s, n, a, bars, idx, b, sl_lv, tp_lv, reach_sl, reach_tp)
        if r:
            return r
    if set(fields) == {"close_price"} and b is not None and sl_lv is not None and (b.open <= sl_lv if s > 0 else b.open >= sl_lv):
        return "b", "gap at open through the stop level"
    return "e", f"fields={fields}"


def dca_rules(st, s, n, a, bars, idx, b, tp_lv, sl_lv, reach_tp):
    # stale SL (same tick DCA fill + SL): Nautilus fills deeper layers in the same tick before the SL
    if a["r"] == "SL" and sl_lv is not None and a.get("fills"):
        ex = a["fills"][-1]
        buys = [f for f in a["fills"][:-1] if f["is_entry"]]
        same = [k for k, f in enumerate(buys) if f["kind"] == "DCA" and f["bar"] == ex["bar"]]
        if same:
            pre = buys[:same[0]]
            avg_pre = sum(f["px"] * f["qty"] for f in pre) / sum(f["qty"] for f in pre)
            lvl = avg_pre * (1 - s * st["sl"] / 100)
            if rel(a["close_price"], lvl) < 1e-9:
                return "a", (f"same-tick DCA fill(s) + stale SL at the pre-DCA level {a['close_price']:.4f}: Nautilus fills the deeper layer(s) "
                             f"before the SL ({a['layers']} layers vs Nora {n['layers']})")
    # same-tick DCA and exit, short side: Nora fills the DCA group first (all sides), Nautilus processes bid-side orders (BUY: SL/TP of a short)
    # before ask-side orders (SELL: the DCA ladder of a short), so the exit comes first and the DCA opens a stray new position
    if n["layers"] > a["layers"] and n["r"] == a["r"] and rel(a["close_price"], n["close_price"]) < 1e-9 and s < 0:
        if any(f[0] == n["close_time"] and f[4] == "maker" for f in n["fills"][:-1]):
            return "a", (f"short: DCA layer and {n['r']} crossed by the same tick: Nora fills the layer first ({n['layers']} layers), "
                         f"Nautilus exits first (bid side before ask side, {a['layers']} layers) and the layer opens a stray position")
    # DCA and TP reachable in the same bar
    if b is not None and tp_lv is not None and reach_tp:
        px, lv = n["enter_price"], []
        for x in st["dca_steps"]:
            px *= 1 - s * x / 100
            lv.append(px)
        if any((b.low <= x if s > 0 else b.high >= x) for x in lv):
            return "a", f"DCA & TP reachable in same bar: Nora={n['r']}, Nautilus={a['r']}"
    return None


def trail_rule(st, s, n, a, bars, idx, b, sl_lv, tp_lv, reach_sl, reach_tp):
    return None


_FUND_CACHE = {}


def funding_rule(st, s, n, a, bars, idx, sym, row):
    """Predict BOTH engines' per-trade funding from their documented semantics and check each prediction against the engine output.
    Nora: charged iff enter_time < t_apply <= close_time, t_apply = first bar open >= funding_time, price = open[t_apply] (kernel / Runner).
    Nautilus: settlement at funding_time; charged iff entry fill ts <= funding_time < exit fill ts (entry fills at the same ts come first, exit
    fills at the same ts too), price = last book mid = close of the last bar whose close ts <= funding_time. Difference = timing class d."""
    if sym not in _FUND_CACHE:
        _FUND_CACHE[sym] = pd.read_csv(os.path.join(OUT, f"funding_{sym}.csv"))
    fu = _FUND_CACHE[sym]
    ot = bars.open_time.values
    side = 1.0 if s > 0 else -1.0
    pred_n = pred_a = 0.0
    boundary, offsets = 0, 0
    t_e, t_x = n["enter_time"], a["fills"][-1]["t"]
    for ft, rate in zip(fu.funding_time.values, fu.rate.values):
        ft = int(ft)
        k = int(ot.searchsorted(ft))                      # first bar with open >= ft
        if k < len(ot):
            t_apply = int(ot[k])
            if n["enter_time"] < t_apply <= n["close_time"]:
                pred_n += n["qty"] * float(bars.open.iloc[k]) * rate * side
        if st["fund"] == "bar":                              # boundary = Nora's application bar open, strategy orders delayed 1 ns (Nora ordering)
            if k < len(ot) and n["enter_time"] < int(ot[k]) <= n["close_time"] and k >= 1:
                pred_a += a["qty"] * float(bars.close.iloc[k - 1]) * rate * side
        elif t_e <= ft < t_x:
            j = int((ot + H <= ft).sum()) - 1               # last bar closed at or before ft
            if j >= 0:
                pred_a += a["qty"] * float(bars.close.iloc[j]) * rate * side
        if ft % H == 0 and (ft == t_e or ft == t_x or ft == n["close_time"]):
            boundary += 1
        elif ft % H != 0:
            offsets += 1 if (min(t_e, n["enter_time"]) <= ft <= max(t_x, n["close_time"] + H)) else 0
    tol = 2e-6 * max(abs(pred_n), 1.0) + 1e-6
    okn, oka = abs(pred_n - n.get("funding", 0.0)) < tol, abs(pred_a - a["funding"]) < tol
    if okn and oka:
        if st["fund"] == "bar":
            return "d", (f"funding price only: both engines charge the same settlements; Nora prices at open[t], Nautilus at the last book price close[t-1] "
                         f"and the synthetic gaps make them differ (Nora {n.get('funding', 0):.6f} == predicted {pred_n:.6f}, "
                         f"Nautilus {a['funding']:.6f} == predicted {pred_a:.6f})")
        return "d", (f"funding timing only: both engines match their own documented rule (Nora {n.get('funding', 0):.6f} == predicted {pred_n:.6f}, "
                     f"Nautilus {a['funding']:.6f} == predicted {pred_a:.6f}); {boundary} settlement(s) exactly on this trade's entry/exit tick "
                     f"(Nora charges the exit tick, not the entry tick; Nautilus the reverse), {offsets} with a seconds offset (price open[t+1] vs open[t])")
    return "e", (f"funding differs and is not explained: Nora {n.get('funding', 0):.6f} vs predicted {pred_n:.6f}, "
                 f"Nautilus {a['funding']:.6f} vs predicted {pred_a:.6f}")


def liq_rule(st, s, n, a, bars, idx, row):
    """Evidence: (1) Nora's liquidation level avg*(1 -+ (1/L - mmr)) was crossed intrabar by the bar's adverse extreme;
    (2) Nautilus' account-level trigger (balance + upnl <= maintenance) as a price level for THIS position, evaluated at bar CLOSES."""
    L, mmr = float(st["lev"]), st["mmr"]
    avg = n["avg_price"]
    lv_n = avg * (1 - s * (1 / L - mmr))
    bal = a["entry_equity"] - a["fills"][0]["fee"]
    notional = a["qty"] * a["avg_price"]
    d_a = bal / notional - mmr
    lv_a = a["avg_price"] * (1 - s * d_a)
    hit_a = lambda px: (px <= lv_a) if s > 0 else (px >= lv_a)       # noqa: E731
    hit_n = lambda px: (px <= lv_n) if s > 0 else (px >= lv_n)       # noqa: E731
    ev = f"Nora level {lv_n:.2f} (liq distance {100 * (1 / L - mmr):.2f}%), Nautilus account-level trigger {lv_a:.2f} ({100 * d_a:.2f}% from avg)"
    if n["r"] == "LIQ" and a["r"] == "LIQ":
        return "l", f"both liquidate in the same bar; Nora at its level {n['close_price']:.2f} (loss capped at margin+fees), Nautilus at the bar close {a['close_price']:.2f}. {ev}"
    if n["r"] == "LIQ":
        b = bars.iloc[idx[n["close_time"]]]
        ext = b.low if s > 0 else b.high
        if not hit_n(ext):
            return "e", f"Nora LIQ but bar extreme {ext} did not cross {lv_n:.2f}"
        # Nautilus must not have a bar close beyond its own trigger level from entry up to its exit
        i0, i1 = idx[n["enter_time"]], idx[min(a["close_time"], bars.open_time.iloc[-1])]
        closes = bars.close.iloc[i0:i1 + 1]
        cross = [k for k, x in enumerate(closes) if hit_a(x)]
        if cross:
            t_cross = int(bars.open_time.iloc[i0 + cross[0]]) + H
            if a["r"] in ("SIG", "TIMEOUT") and a["close_time"] == t_cross:
                return "l", (f"Nautilus' trigger {lv_a:.2f} was crossed at the close of the bar before {t_cross}, but the strategy's {a['r']} exit "
                             f"is executed at that same timestamp BEFORE the liquidation check (run after on_bar), so no liquidation; Nora liquidated "
                             f"intrabar at {lv_n:.2f}. {ev}")
            return "e", f"Nautilus trigger {lv_a:.2f} crossed by a bar close but no liquidation. {ev}"
        why = "Nautilus checks account equity vs maintenance margin once per bar timestamp at the bar close"
        if d_a > (1 / L - mmr) * 1.001:
            why += f"; cross-margin: the whole account balance backs the position (margin share {100 * notional / L / bal:.0f}% of balance), so its trigger is further away"
        return "l", f"Nora liquidated intrabar (low/high {ext} crossed {lv_n:.2f}); Nautilus had no bar close beyond its trigger and exited by {a['r']}. {why}. {ev}"
    if a["r"] == "LIQ":
        return "e", f"Nautilus-only liquidation. {ev}"
    return "e", "liquidation rule not applicable"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "ohlc"
    pref = sys.argv[2] if len(sys.argv) > 2 else "all"
    res = []
    for ds in DATASETS:
        for sname in SIGNALS:
            for stname in STAGES:
                if (pref != "all" and not stname.startswith(pref)) or skip(stname, sname):
                    continue
                if not (os.path.exists(os.path.join(OUT, f"nora_{tag(ds, sname, stname, path)}.json"))
                        and os.path.exists(os.path.join(OUT, f"nautilus_{tag(ds, sname, stname, path)}.json"))):
                    continue
                res.append(compare(ds, sname, stname, path))
                if len(STAGES[stname]["syms"]) > 1 and os.path.exists(os.path.join(OUT, f"nora_{tag(ds, sname, stname, path)}_sync.json")):
                    r2 = compare(ds, sname, stname, path, "_sync")
                    r2["stage"] = stname + " [sync adm]"
                    res.append(r2)
    json.dump(res, open(os.path.join(OUT, f"ext_results_{path}.json"), "w"), indent=1, default=str)
    def keep(rows):                       # every non-exact row, but at most 4 per class and run (the full rows are in out/ext/ext_results_<path>.json)
        seen, out = Counter(), []
        for x in rows:
            if x["cls"] != "match" and seen[x["cls"]] < 4:
                seen[x["cls"]] += 1
                out.append({k: x.get(k) for k in ("sym", "enter_time", "cls", "note", "nora", "naut", "fund_nora", "fund_naut")})
        return out
    slim = [{k: v for k, v in r.items() if k != "rows"} | {"non_exact_examples": keep(r["rows"])} for r in res]
    json.dump(slim, open(os.path.join(HERE, f"ext_results_{path}.json"), "w"), indent=1, default=str)
    print("| dataset | signal | stage | trades N/A | exact | a | b | c | d | l | p | t | x | e | final eq Nora | final eq Naut | diff % | bit-id |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        c = r["classes"]
        print(f"| {r['dataset']} | {r['signal']} | {r['stage']} | {r['trades_nora']}/{r['trades_naut']} | {r['exact_matches']} | "
              + " | ".join(str(c.get(k, 0)) for k in "abcdlptxe")
              + f" | {r['final_equity_nora']:.2f} | {r['final_equity_naut']:.2f} | {r['final_equity_diff_pct']:+.4f} | {r['bit_identical']} |")
    print()
    print(f"Per-stage totals over datasets x signals (path={path}): exact / total paired trades, classes")
    print("| stage | runs | trades Nora/Naut | exact | a | b | c | d | l | p | t | x | e | max |final eq diff %| |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    agg = {}
    for r in res:
        g = agg.setdefault(r["stage"], {"runs": 0, "tn": 0, "ta": 0, "exact": 0, "mx": 0.0, "cls": Counter()})
        g["runs"] += 1
        g["tn"] += r["trades_nora"]
        g["ta"] += r["trades_naut"]
        g["exact"] += r["exact_matches"]
        g["mx"] = max(g["mx"], abs(r["final_equity_diff_pct"]))
        g["cls"].update({k: v for k, v in r["classes"].items() if k != "match"})
    for k, g in agg.items():
        print(f"| {k} | {g['runs']} | {g['tn']}/{g['ta']} | {g['exact']} | " + " | ".join(str(g["cls"].get(x, 0)) for x in "abcdlptxe") + f" | {g['mx']:.4f} |")
    print()
    print("S8 admission look-ahead (decisions logged on Nora's own history; Nora view = symbols earlier in book order already processed their whole bar t)")
    print("| dataset | signal | stage | decisions | can_open differs | gross-room differs | sizing equity differs | trades prod/sync/Nautilus | final eq prod | sync adm | Nautilus |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for ds in DATASETS:
        for sname in SIGNALS:
            for stname in STAGES:
                f1 = os.path.join(OUT, f"nora_{tag(ds, sname, stname, path)}.json")
                f2 = os.path.join(OUT, f"nora_{tag(ds, sname, stname, path)}_sync.json")
                f3 = os.path.join(OUT, f"nautilus_{tag(ds, sname, stname, path)}.json")
                if not (os.path.exists(f2) and os.path.exists(f3)):
                    continue
                n_, y_, a_ = load(f1), load(f2), load(f3)
                d_ = n_["decisions"]
                big = 1e18
                dc = sum(1 for d in d_ if d["nora"]["can"] != d["sync"]["can"])
                dm = sum(1 for d in d_ if d["nora"]["can"] and d["sync"]["can"] and d["sync"]["mnn"] < big and rel(d["nora"]["mnn"], d["sync"]["mnn"]) > 1e-6)
                de = sum(1 for d in d_ if rel(d["nora"]["eq"], d["sync"]["eq"]) > 1e-9)
                print(f"| {ds} | {sname} | {stname} | {len(d_)} | {dc} | {dm} | {de} | {len(n_['trades'])}/{len(y_['trades'])}/{len(a_['trades'])} | "
                      f"{n_['final_equity']:.2f} | {y_['final_equity']:.2f} | {a_['final_equity_nora_def']:.2f} |")
    print()
    print("S8 sizing look-ahead (matched trades whose entry equity includes the intrabar PnL of an earlier-order symbol closing in the same bar)")
    print("| dataset | signal | stage | trades with look-ahead sizing | max qty rel diff | trades with different entry equity (incl. carried-over) |")
    print("|---|---|---|---|---|---|")
    for r in res:
        if r.get("variant") == "" and len(STAGES[r["stage"]]["syms"]) > 1:
            print(f"| {r['dataset']} | {r['signal']} | {r['stage']} | {r['sizing_lookahead_trades']} | {r['sizing_lookahead_max_qty_rel']:.4f} | {r['entry_equity_differs']} |")
    nshow = 0
    for r in res:
        for x in r["rows"]:
            if x["cls"] == "e" and nshow < int(os.environ.get("SHOW_E", "40")):
                nshow += 1
                print("UNEXPLAINED", r["dataset"], r["signal"], r["stage"], x["sym"], x["enter_time"], x["note"], x.get("nora"), x.get("naut"))


if __name__ == "__main__":
    main()
