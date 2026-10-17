# Đã chuyển khỏi test/scripts (P17 T1-B5c): phụ thuộc phễu / job regime_report đã gỡ; bản gốc ở tag pre-p17-research.
"""Chẩn đoán vì sao regime (P2.4/P2.5) chưa đạt: tách từng nguyên nhân bằng thí nghiệm có đối chứng trên dữ liệu thật (khung 15m, preset).

  A. Danh mục: tắt / bảng tĩnh / bảng tĩnh không cầu chì / chỉ cầu chì            -> phần lỗ do lọc vào lệnh vs do cầu chì
  B. Từng chiến lược chạy RIÊNG: tắt vs bảng tĩnh                                  -> bỏ hiệu ứng tranh chỗ (max_positions) giữa chiến lược
  C. Độ trễ nhãn: lệnh lãi của chiến lược xu hướng vào ở regime nào, 12 h sau là regime nào
  D. Luật học có giữ được ngoài mẫu không: học trên dev1, đo trên dev2 (cùng chiến lược, regime): tỉ lệ quyết định chặn đúng dấu
  E. Danh mục dev2: tắt vs bảng học trên dev1 (ngoài mẫu thật)
  F. Lãi/lỗ từng chiến lược dev1 -> dev2 (không regime): chiến lược có edge ngoài mẫu không
  G. So hồ sơ nhãn "slow" (xu hướng 4h, xác nhận 180 phút) và "fast" (1h, 60 phút) cho C, D và bảng chặn ngược chiều
  H. Tiêu chí P2.4 (viết lại): trên dev2 (ngoài mẫu), lãi trung bình/lệnh trong regime ĐƯỢC PHÉP > trong regime BỊ CHẶN, ở >= 2/3 chiến lược

Dùng (từ nora/): ops/run_limited.sh -- test/scripts/research_regime_diagnosis.py [--out FILE]
"""
import argparse
import json
import os
import sys
import time
import warnings

import numpy as np

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

TF = "15m"
HOUR = 3_600_000


def _strategies(items, rpt, regime_of):
    from backend.strategies import lift_frames
    from backend.analys.param import materialize
    from backend.strategies import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
    return [materialize(by_id[cid], lift_frames(by_id[cid], prm, TF), regime=regime_of(cid) or False, stop_fill="level",
                        risk_per_trade_pct=rpt) for cid, prm in items]


def bt(items, symbols, start, end, rpt, regime_of=lambda cid: None):
    from backend.jobs.evaluate import run
    from backend.analys.param import RISK
    out = run([], symbols, start, end, rpt, "level", RISK, extra_strategies=_strategies(items, rpt, regime_of), base_frame=TF)
    by = {}
    for t in out["trade_list"]:
        by[t["strategy"]] = round(by.get(t["strategy"], 0.0) + t["pnl"], 2)
    return {"ret_pct": out["ret_pct"], "mdd_pct": out["mdd_pct"], "trades": out["trades"], "pnl_by_strategy": by,
            "trade_list": out["trade_list"]}


def short(r):
    return {k: r[k] for k in ("ret_pct", "mdd_pct", "trades", "pnl_by_strategy")}


def main():
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "data", "_cache", "research", "regime_diagnosis.json"))
    a = ap.parse_args()
    from backend.jobs.evaluate import WARMUP
    from backend.metrics import regime as rg
    from backend.metrics.regime import OBSERVE, by_regime, learn_map, trade_regime
    from backend.analys.param import REGIME_MAP
    from backend.strategies import perp_symbols
    from backend.XXstages import compute_windows
    from backend.jobs.tasks import _book_items
    t0 = time.time()
    symbols = perp_symbols()
    w = compute_windows(symbols)
    items, rpt = _book_items()
    ids = [cid for cid, _ in items]
    static = lambda cid: REGIME_MAP.get(cid)  # noqa: E731
    nofuse = lambda cid: {**REGIME_MAP[cid], "fuse": False} if cid in REGIME_MAP else None  # noqa: E731
    fuse_only = lambda cid: {"allowed": list(rg.NAMES), "fuse": True}  # noqa: E731
    S, E = w["start"], w["end"]
    rep = {"windows": w, "rpt": rpt}

    print("[A] danh mục toàn kỳ", flush=True)
    A = {name: bt(items, symbols, S, E, rpt, f) for name, f in
         (("off", lambda c: None), ("static", static), ("static_no_fuse", nofuse), ("fuse_only", fuse_only))}
    rep["A_portfolio"] = {k: short(v) for k, v in A.items()}
    for k, v in rep["A_portfolio"].items():
        print(f"  {k:15s} lãi {v['ret_pct']:7.2f}% MDD {v['mdd_pct']:6.2f}% lệnh {v['trades']}", flush=True)

    print("[B] từng chiến lược riêng", flush=True)
    B = {}
    for cid, prm in items:
        off, on = bt([(cid, prm)], symbols, S, E, rpt), bt([(cid, prm)], symbols, S, E, rpt, static)
        B[cid] = {"off": short(off), "static": short(on)}
        print(f"  {cid:20s} tắt {off['ret_pct']:7.2f}% ({off['trades']}) | bảng tĩnh {on['ret_pct']:7.2f}% ({on['trades']})", flush=True)
    rep["B_isolated"] = B
    rep["B_sum_isolated_delta_pct"] = round(sum(v["static"]["ret_pct"] - v["off"]["ret_pct"] for v in B.values()), 2)

    print("[C] độ trễ nhãn", flush=True)
    labels = {}
    for sym in symbols:
        s = rg.series(sym, S - WARMUP, E, base_frame=TF)
        labels[sym] = {"t": s["t"], "labels": s["labels"]}
    C = {}
    for cid in ("trend_long", "keltner_trend_long", "momentum_long", "breakout_4h_long", "trend_short", "keltner_trend_short"):
        wins = [t for t in A["off"]["trade_list"] if t["strategy"] == cid and t["pnl"] > 0]
        at, later = {}, {}
        for t in wins:
            L = labels[t["symbol"]]
            r0 = trade_regime(L["t"], L["labels"], t["enter_time"])
            r1 = trade_regime(L["t"], L["labels"], t["enter_time"] + 12 * HOUR)
            at[r0] = at.get(r0, 0) + 1
            later[r1] = later.get(r1, 0) + 1
        n = max(1, len(wins))
        C[cid] = {"winning_trades": len(wins), "regime_at_entry_pct": {k: round(100 * v / n, 1) for k, v in sorted(at.items())},
                  "regime_12h_later_pct": {k: round(100 * v / n, 1) for k, v in sorted(later.items())},
                  "allowed_static": REGIME_MAP[cid]["allowed"]}
        ok0 = sum(v for k, v in at.items() if k in REGIME_MAP[cid]["allowed"])
        C[cid]["winners_allowed_at_entry_pct"] = round(100 * ok0 / n, 1)
        print(f"  {cid:20s} lệnh lãi {len(wins):4d}: được bảng tĩnh cho vào {C[cid]['winners_allowed_at_entry_pct']}% | "
              f"lúc vào {C[cid]['regime_at_entry_pct']}", flush=True)
    rep["C_label_lag"] = C

    print("[D] luật học: dev1 -> dev2", flush=True)
    obs = lambda cid: OBSERVE  # noqa: E731
    d1 = bt(items, symbols, w["start"], w["dev1_end"], rpt, obs)
    d2 = bt(items, symbols, w["dev1_end"], w["dev2_end"], rpt, obs)
    st1, st2 = by_regime(d1["trade_list"], labels), by_regime(d2["trade_list"], labels)
    rows, agree, total = [], 0, 0
    for cid in ids:
        for r in rg.NAMES:
            a1, a2 = (st1.get(cid) or {}).get(r), (st2.get(cid) or {}).get(r)
            if not a1 or a1["trades"] < 5 or not a2 or a2["trades"] < 5:
                continue
            total += 1
            same = (a1["pnl_usd"] > 0) == (a2["pnl_usd"] > 0)
            agree += same
            rows.append({"strategy": cid, "regime": r, "dev1": [a1["trades"], a1["pnl_usd"]], "dev2": [a2["trades"], a2["pnl_usd"]], "same_sign": same})
    learned = learn_map(st1, ids)
    blocked_rows = [x for x in rows if learned.get(x["strategy"]) and x["regime"] in learned[x["strategy"]]["blocked"]]
    hit = sum(1 for x in blocked_rows if x["dev2"][1] <= 0)
    rep["D_learn_oos"] = {"pairs": total, "same_sign_pct": round(100 * agree / total, 1) if total else None,
                          "blocked_pairs": len(blocked_rows), "blocked_still_losing_dev2_pct": round(100 * hit / len(blocked_rows), 1) if blocked_rows else None,
                          "rows": rows, "learned_map_dev1": learned}
    print(f"  cặp (chiến lược, regime) đủ lệnh ở cả 2 kỳ: {total}; cùng dấu lãi/lỗ: {rep['D_learn_oos']['same_sign_pct']}% | "
          f"chặn trên dev1 mà dev2 vẫn lỗ: {rep['D_learn_oos']['blocked_still_losing_dev2_pct']}% ({len(blocked_rows)} cặp)", flush=True)

    print("[E] dev2: tắt vs bảng học trên dev1", flush=True)
    off2 = bt(items, symbols, w["dev1_end"], w["dev2_end"], rpt)
    lrn2 = bt(items, symbols, w["dev1_end"], w["dev2_end"], rpt, lambda cid: learned.get(cid))
    rep["E_dev2"] = {"off": short(off2), "learned_on_dev1": short(lrn2)}
    print(f"  tắt {off2['ret_pct']}% MDD {off2['mdd_pct']}% | học dev1 {lrn2['ret_pct']}% MDD {lrn2['mdd_pct']}%", flush=True)

    # F. bản thân chiến lược có edge ngoài mẫu không (không regime): dev1 vs dev2 theo chiến lược
    rep["F_edge_dev1_vs_dev2"] = {cid: {"dev1_pnl": d1["pnl_by_strategy"].get(cid, 0.0), "dev2_pnl": d2["pnl_by_strategy"].get(cid, 0.0)}
                                  for cid in ids}
    print("[F] lãi/lỗ từng chiến lược dev1 -> dev2 (không regime):", flush=True)
    for cid, v in rep["F_edge_dev1_vs_dev2"].items():
        print(f"  {cid:20s} {v['dev1_pnl']:9.2f} -> {v['dev2_pnl']:9.2f}", flush=True)

    print("[G/H] hồ sơ nhãn slow vs fast", flush=True)
    rep["G_profiles"] = {}
    for prof in ("slow", "fast"):
        cfg = rg.PROFILES[prof]
        lab = {}
        for sym in symbols:
            s_ = rg.series(sym, S - WARMUP, E, base_frame=TF, cfg=cfg)
            lab[sym] = {"t": s_["t"], "labels": s_["labels"]}
        deny = lambda cid, prof=prof: {**REGIME_MAP[cid], "classifier": prof}  # noqa: E731
        full = bt(items, symbols, S, E, rpt, deny)
        dv2 = bt(items, symbols, w["dev1_end"], w["dev2_end"], rpt, deny)
        hol = bt(items, symbols, w["dev2_end"], E, rpt, deny)
        # C: tỉ lệ lệnh lãi (toàn kỳ, tắt regime) rơi vào regime được phép
        win_ok = {}
        for cid in ids:
            wins = [t for t in A["off"]["trade_list"] if t["strategy"] == cid and t["pnl"] > 0]
            ok = sum(1 for t in wins if trade_regime(lab[t["symbol"]]["t"], lab[t["symbol"]]["labels"], t["enter_time"]) in REGIME_MAP[cid]["allowed"])
            win_ok[cid] = round(100 * ok / max(1, len(wins)), 1)
        # D: độ bền dấu (dev1 -> dev2) với luật chặt + luật cũ
        s1, s2 = by_regime(d1["trade_list"], lab), by_regime(d2["trade_list"], lab)
        pairs = [(cid, r) for cid in ids for r in rg.NAMES
                 if (s1.get(cid) or {}).get(r, {}).get("trades", 0) >= 30 and (s2.get(cid) or {}).get(r, {}).get("trades", 0) >= 30]
        same = sum(1 for cid, r in pairs if (s1[cid][r]["pnl_usd"] > 0) == (s2[cid][r]["pnl_usd"] > 0))
        strict = learn_map(s1, ids)
        lrn2 = bt(items, symbols, w["dev1_end"], w["dev2_end"], rpt, lambda cid: ({**strict[cid], "classifier": prof} if strict.get(cid) else None))
        # H: dev2, lãi TB/lệnh trong regime được phép vs bị chặn (bảng chặn ngược chiều), từ lệnh dev2 khi TẮT regime
        H, better = {}, 0
        for cid in ids:
            al = [t["pnl"] for t in d2["trade_list"] if t["strategy"] == cid
                  and trade_regime(lab[t["symbol"]]["t"], lab[t["symbol"]]["labels"], t["enter_time"]) in REGIME_MAP[cid]["allowed"]]
            bl = [t["pnl"] for t in d2["trade_list"] if t["strategy"] == cid
                  and trade_regime(lab[t["symbol"]]["t"], lab[t["symbol"]]["labels"], t["enter_time"]) not in REGIME_MAP[cid]["allowed"]]
            ma, mb = (float(np.mean(al)) if al else None), (float(np.mean(bl)) if bl else None)
            ok = ma is not None and mb is not None and ma > mb
            better += ok
            H[cid] = {"allowed_n": len(al), "allowed_avg": None if ma is None else round(ma, 3), "blocked_n": len(bl),
                      "blocked_avg": None if mb is None else round(mb, 3), "allowed_better": ok}
        g = {"deny_full": short(full), "deny_dev2": short(dv2), "deny_holdout": short(hol), "winners_allowed_pct": win_ok,
             "D_pairs_30": len(pairs), "D_same_sign_pct": round(100 * same / len(pairs), 1) if pairs else None,
             "strict_learned_dev1": {k: v["blocked"] for k, v in strict.items() if v}, "dev2_strict_learned": short(lrn2),
             "H_dev2": H, "H_allowed_better_count": better, "H_pass": better >= (2 * len(ids) + 2) // 3}
        rep["G_profiles"][prof] = g
        print(f"  [{prof}] chặn ngược chiều: toàn kỳ {full['ret_pct']}% | dev2 {dv2['ret_pct']}% | holdout {hol['ret_pct']}% ; "
              f"lệnh lãi được phép TB {round(float(np.mean(list(win_ok.values()))), 1)}% ; D(>=30 lệnh) {g['D_pairs_30']} cặp, cùng dấu "
              f"{g['D_same_sign_pct']}% ; học chặt dev1->dev2 {lrn2['ret_pct']}% (chặn {g['strict_learned_dev1']}) ; "
              f"H: {better}/{len(ids)} chiến lược regime được phép tốt hơn -> {'ĐẠT' if g['H_pass'] else 'TRƯỢT'}", flush=True)
    rep["wall_s"] = round(time.time() - t0, 1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    from backend.models.storage import json_default
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=json_default)
    print(f"ghi {a.out} ({rep['wall_s']}s)", flush=True)


if __name__ == "__main__":
    main()
