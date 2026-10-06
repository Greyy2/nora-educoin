"""Chạy harness "săn cú lớn / swing" cho 1 bot:
   run_limited.sh --no-lock -- test/scripts/okx_top10/run_bigshot.py "Faithful-Punk-Fuse" [--quick]
Ghi test/scripts/okx_top10/out/<slug>.json (cùng schema khoá chính với out/01pp.json: idea/hypothesis, inference, iterations, best_model, levelB, verdict,
diagnostics, cum_curve_*, rows, runtime_s; thêm: rules_inferred, loo, walk_forward, add_model, full_sim, representative).

Đơn vị so khớp = UNIT (tranche vào lệnh + các lệnh đóng của chính nó), không phải rổ chuỗi chồng lấn như 01pp (xem families_bigshot.py).
Chia 60/40 theo thời điểm mở unit; MẪU RẤT NHỎ (23-73 sub-position) nên TEST chủ yếu để BÁC BỎ, không thể 'xác nhận'; báo thêm LOO (bỏ từng unit) và
walk-forward (mở rộng dần) cho cả thoát, vào lệnh, nhồi lệnh. Mọi tham số chọn trên TRAIN (hoặc trên mẫu trừ phần giữ lại), không chỉnh theo từng basket.
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import families_bigshot as F
import load
import match
import run_bot

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
MIN = 60_000
H = 3_600_000

HYP = {
    "Faithful-Punk-Fuse": dict(
        hypothesis=("Swing-long ETH/BTC đòn bẩy cao (50-100x, cross-margin), vào SAU nhịp giảm/hồi về EMA trong xu hướng tăng (28% theo đà), "
                    "nhồi thêm (63% là tầng thêm) khi giá hồi về dưới giá fill gần nhất HOẶC nhịp hồi trong lúc đang lãi (nhồi kim tự tháp), "
                    "giữ lệnh thắng ~184h, cắt lệnh thua sau ~30h. Thoát thủ công theo cụm (ETH+BTC cùng phút)."),
        candidate=["vào: sau nhịp giảm N-sigma (contra) / hồi về EMA20 trong xu hướng tăng (pull) / phá đỉnh N giờ (brk) / nhịp quét đáy (sweep), cổng giờ + biến động",
                   "nhồi: avg-down >=x% dưới fill gần nhất, kim tự tháp khi lãi >=x%, hồi về EMA20 khi đang lãi",
                   "thoát: trailing ATR, thoát đóng nến dưới EMA, TP/SL R-multiple, ROI cố định, time-stop"]),
    "Firsthand-ATL-Pansy": dict(
        hypothesis=("Chỉ BTC đòn bẩy 100x (cross), 57% long, vào ngược đà (21% theo đà) sau nhịp quét; tầng thêm cùng giá (0,02%) = chia nhỏ 1 lệnh vào "
                    "(tranche), không DCA. Lãi trung bình gấp ~3,8 lần lỗ: cắt lỗ nhanh/giữ lệnh thắng nhiều ngày; PF 10,8 nhờ 5 lệnh lớn nhất."),
        candidate=["vào: sau nhịp quét đáy/đỉnh 24h, contra N-sigma, cổng giờ (phiên Á/Mỹ)", "chia lệnh: 2-3 fill trong <=15 phút (không thêm theo giá)",
                   "thoát: SL hẹp trong khoảng cách thanh lý ~0.6% ở 100x? (kiểm tra), trailing/EMA, giữ nhiều ngày"]),
    "Physical-Epoch-Fuel": dict(
        hypothesis=("Swing cắt lỗ nhanh trên cổ phiếu token hoá (SKHYNIX/SNDK/MU) + BTC/ETH: đặt LIMIT tại mức giá tròn (entry 56% là số tròn so với ~4% ngẫu nhiên), "
                    "mua nhịp giảm (33% theo đà), trung bình giá xuống từng bước ~1,09% (47% là tầng thêm), thoát theo cụm (42% đóng cùng giây, nhiều mã cùng lúc), "
                    "thắng giữ ~72h, thua ~25h; phiên Mỹ/Hàn có thể là cổng giờ."),
        candidate=["vào: limit tại mức tròn (level), contra N-sigma, pullback EMA, cổng phiên (US 13:30 UTC, KRX 0-6 UTC)",
                   "nhồi: avg-down ~1% từ fill gần nhất, limit ladder tại mức tròn", "thoát: TP tại mức tròn, trailing, time-stop, thoát theo phiên"]),
}


def _jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, np.ndarray): return o.tolist()
    if isinstance(o, np.uint64): return int(o)
    raise TypeError(type(o))


def _clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_") and k not in ("masks", "sig_t", "sig_mask", "hit", "S")}


def _rows(units, params):
    return [match.basket_row(u, F.simulate_unit(u, params)) for u in units]


def _level_a_rows(units, params, a_cache=None):
    rows = _rows(units, params)
    return rows, match.level_a(rows)


# ---------------------------------------------------------------- Level A: thoát
def run_exits(units, tr_idx, te_idx, grids, info, quick):
    tr = [units[i] for i in tr_idx]; te = [units[i] for i in te_idx]
    iters = []
    best = None

    def record(nm, note, grid, kind="family"):
        nonlocal best
        t = time.time()
        T, C, R, P = F.exit_family_matrix(units, grid)
        gb, J, loo, jt, je = F.exit_selection(units, T, C, R, tr_idx, te_idx)
        prm = grid[gb]
        rows_tr, m_tr = _level_a_rows(tr, prm); rows_te, m_te = _level_a_rows(te, prm)
        allr = rows_tr + rows_te
        bo = {}
        for lab, sel in (("winners", lambda r: r["act_ret"] > 0), ("losers", lambda r: r["act_ret"] <= 0)):
            rr = [r for r in allr if sel(r)]
            dm = [abs(r["sim_close"]["t"] - r["act_close"]["t"]) / MIN if r["sim_closed"] else 1e9 for r in rr]
            bo[lab] = dict(n=len(rr), match_15=int(sum(d <= 15 for d in dm)), match_60=int(sum(d <= 60 for d in dm)))
        it = dict(model=nm, family="exit", note=note, params=prm, n_grid=len(grid), J_train=round(jt, 4), J_test=round(je, 4),
                  train=F.trim_a(m_tr), test=F.trim_a(m_te), loo=loo, by_outcome_train_plus_test=bo, secs=round(time.time() - t, 1))
        iters.append(it)
        if best is None or jt > best["J_train"]:
            best = dict(it)
        print(f"  {nm:22s} n={len(grid):3d} J tr {jt:.3f} te {je:.3f} | test c15 {m_te.get('close_match_15')} c60 {m_te.get('close_match_60')} sign {m_te.get('pnl_sign_agree')} | LOO c15 {loo['close_match_15']} c60 {loo['close_match_60']} J {loo['J_rel_mean']}", flush=True)
        return prm

    for nm, note, grid in grids:
        if quick: grid = grid[::max(1, len(grid) // 12)]
        record(nm, note, grid)
    # vòng tinh chỉnh: thêm time-stop / SL / trailing vào tham số tốt nhất theo TRAIN (không chọn theo TEST); lưới luôn chứa nguyên mô hình gốc
    hq = info["hold_min_q"]; la = info["loss_atr_q"] or [2.0]
    for nm, note, ovs in [
            ("R1_best+time_stop", "thêm time-stop (x2, x4, x8 phân vị 50 thời gian giữ) vào mô hình tốt nhất theo train.", [dict(hold_min=k * hq[1]) for k in (2, 4, 8)]),
            ("R2_best+SL_ATR", "thêm stop-loss theo ATR (chỉ khi mô hình gốc chưa có SL).", [dict(sl=x, sl_mode=2, roi=0) for x in la] if not best["params"].get("sl") else []),
            ("R3_best+trail", "thêm trailing % (kích hoạt/lùi).", [dict(tr_act=a_, tr_dist=d_, tr_mode=1) for a_ in (1.0, 2.0, 4.0) for d_ in (0.5, 1.0, 2.0)])]:
        if not ovs: continue
        grid = [dict(best["params"])] + [{**best["params"], **o} for o in ovs]
        record(nm, note, grid)
    return iters, best


# ---------------------------------------------------------------- Level B: bảng luật
def entry_block(label, keys, units, lo, hi, hh, split_t, entries, rules, reps, quick):
    t = time.time()
    tab, ev, act_tr, act_te = F.rule_table(keys, rules, units, lo, hi, hh, split_t, entries=entries, reps=reps)
    print(f"  [{label}] {len(rules)} luật, {len(ev)} sự kiện, {time.time()-t:.0f}s", flush=True)
    res = dict(n_rules=len(rules), n_events=len(ev), n_events_train=int(sum(len(v) for v in act_tr.values())), n_events_test=int(sum(len(v) for v in act_te.values())))
    n_tr = res["n_events_train"]

    def full(row, part):
        r = row["rule"]
        if part == "train":
            sg = {k: v[v < split_t] for k, v in F.sig_dict(keys, r, lo, hi).items() if (v < split_t).any()}
            return match.level_b(act_tr, sg, lo, split_t, reps=200 if not quick else 30, seed=2, tols=(15, 60, 240), hour_hist=hh) if act_tr else None
        return match.level_b(act_te, row["_sg_te"], split_t, hi, reps=200 if not quick else 30, seed=3, tols=(15, 60, 240), hour_hist=hh) if act_te else None

    per_kind = {}
    for row in tab:
        k = row["rule"]["kind"]; sc = F.f1_excess_b(row["train"], 15)
        if k not in per_kind or sc > per_kind[k][0]: per_kind[k] = (sc, row)
    res["per_kind"] = []
    for k, (sc, row) in sorted(per_kind.items(), key=lambda kv: -kv[1][0]):
        res["per_kind"].append(dict(kind=k, rule=row["rule"], name=F.rule_name(row["rule"]), train_f1_excess_15=round(sc, 4), train=full(row, "train"), test=full(row, "test")))
    for tol, nm in ((15, "best_tight_15min"), (240, "best_coarse_240min")):
        row = max(tab, key=lambda r: F.f1_excess_b(r["train"], tol))
        res[nm] = dict(rule=row["rule"], name=F.rule_name(row["rule"]), selection_tol_min=tol, train_f1_excess=round(F.f1_excess_b(row["train"], tol), 4),
                       train=full(row, "train"), test=full(row, "test"), loo_all_events=F.loo_rules(tab, ev, tol), walk_forward=F.walk_forward_rules(tab, ev, tol))
        print(f"    {nm}: {res[nm]['name']} | test rec15 {(res[nm]['test'] or {}).get('recall_15')} rec240 {(res[nm]['test'] or {}).get('recall_240')} | LOO {res[nm]['loo_all_events']['recall_loo']}% vs chance {res[nm]['loo_all_events']['expected_by_chance']}% p={res[nm]['loo_all_events']['p_value']}", flush=True)
    sub = [r for r in tab if r["rule"].get("gate") in (None, "sess")]
    res["no_event_gate"] = {nm: dict(n_rules=len(sub), loo=F.loo_rules(sub, ev, tol), walk_forward=F.walk_forward_rules(sub, ev, tol)) for tol, nm in ((15, "tight_15min"), (240, "coarse_240min"))}
    res["no_event_gate_note"] = ("cổng giờ của luật được suy ra từ giờ vào của TRAIN (kể cả event bị giữ lại trong LOO) nên LOO có rò rỉ nhẹ; 'no_event_gate' lặp lại LOO/WF chỉ với luật "
                                 "KHÔNG cổng giờ suy từ dữ liệu (không cổng hoặc cổng phiên cổ phiếu cố định).")
    res["note"] = ("%d luật được thử trên mẫu nhỏ -> p-value LOO/WF chỉ có nghĩa khi luật chọn KHÔNG nhìn event bị giữ lại (đúng với LOO/WF ở đây); "
                   "headline = TEST + LOO, không phải điểm train." % len(rules))
    return res, tab, ev


def add_block(units, split_t, reps, quick):
    rules = F.add_rules()
    if quick: rules = rules[::4]
    t = time.time()
    tab, adds = F.add_table(units, rules, split_t, reps=reps)
    print(f"  [add] {len(rules)} luật, {len(adds)} add thật, {time.time()-t:.0f}s", flush=True)
    res = dict(n_rules=len(rules), n_actual_adds=len(adds))
    per_kind = {}
    for row in tab:
        k = row["rule"]["kind"]; sc = F.f1_excess_b(row["train"], 15) if row["train"]["n_actual"] else -9
        if k not in per_kind or sc > per_kind[k][0]: per_kind[k] = (sc, row)
    res["per_kind"] = [dict(kind=k, rule=row["rule"], name=F.add_rule_name(row["rule"]), train_f1_excess_15=round(sc, 4), train=row["train"], test=row["test"], all=row["all"])
                       for k, (sc, row) in sorted(per_kind.items(), key=lambda kv: -kv[1][0])]
    for tol, nm in ((15, "best_tight_15min"), (240, "best_coarse_240min")):
        row = max(tab, key=lambda r: F.f1_excess_b(r["train"], tol) if r["train"]["n_actual"] else -9)
        res[nm] = dict(rule=row["rule"], name=F.add_rule_name(row["rule"]), selection_tol_min=tol, train=row["train"], test=row["test"], all=row["all"],
                       loo_all_adds=F.loo_rules(tab, adds, tol), walk_forward=F.walk_forward_rules(tab, adds, tol, min_train=5))
        a = row["test"]
        print(f"    add {nm}: {res[nm]['name']} | test rec15 {a['recall_15']} (rand {a['rand_recall_15_mean']}) rec240 {a['recall_240']} (rand {a['rand_recall_240_mean']}) | LOO {res[nm]['loo_all_adds']['recall_loo']}% vs {res[nm]['loo_all_adds']['expected_by_chance']}% p={res[nm]['loo_all_adds']['p_value']}", flush=True)
    return res, tab


def pf_block(units, split_t, quick):
    out = {}
    for group in ("all", "sym"):
        for basis in ("notional", "margin"):
            for mu in (1, 2):
                tab, ev = F.pf_table(units, group, split_t, mu, basis, reps=200 if not quick else 20)
                if len(ev) < 6: continue
                res = dict(group=group, basis=basis, min_units_in_cluster=mu, n_events=len(ev), n_events_train=int(sum(t < split_t for _, t in ev)), n_events_test=int(sum(t >= split_t for _, t in ev)))
                for tol, nm in ((15, "best_tight_15min"), (240, "best_coarse_240min")):
                    row = max(tab, key=lambda r: F.f1_excess_b(r["train"], tol) if r["train"]["n_actual"] else -9)
                    res[nm] = dict(rule=row["rule"], name=F.pf_rule_name(row["rule"]), train=row["train"], test=row["test"], all=row["all"],
                                   loo=F.loo_rules(tab, ev, tol), walk_forward=F.walk_forward_rules(tab, ev, tol, min_train=5))
                a = res["best_tight_15min"]
                print(f"  [pf {group}/{basis}/min{mu}] {len(ev)} cụm đóng | tight {a['name']}: all rec15 {a['all']['recall_15']} prec15 {a['all']['precision_15']} (rand {a['all']['rand_recall_15_mean']}/{a['all']['rand_precision_15_mean']}) test rec15 {a['test']['recall_15']} | LOO {a['loo']['recall_loo']}% vs {a['loo']['expected_by_chance']}% p={a['loo']['p_value']}", flush=True)
                out[f"{group}_{basis}_min{mu}"] = res
    return out


def add_examples(units, best_add, chains, n=3):
    out = []
    for ch in sorted(chains, key=lambda c: -len(c["tranches"]))[:n]:
        if len(ch["tranches"]) < 2: continue
        sym, side = ch["sym"], ch["side"]
        pan = F.panel(sym)
        ex = dict(sym=sym, side=side, t0=ch["t0"], t1=ch["t1"], actual_tranches=[dict(t=int(x["t"]), px=round(x["px"], 6)) for x in ch["tranches"]])
        for nm in ("best_tight_15min", "best_coarse_240min"):
            t, _ = F.add_signals(units, sym, side, best_add[nm]["rule"])
            t = t[(t >= ch["t0"]) & (t <= ch["t1"])]
            ex["sim_" + nm] = [dict(t=int(x), px=round(float(pan.loc[x, "c"]), 6)) for x in t[:20]]
        out.append(ex)
    return out


# ---------------------------------------------------------------- tổng hợp
def run(name, quick=False):
    t_start = time.time()
    bot = load.get_bot(name); summ = load.load_summary()["bots"][name]
    units = [u for u in F.build_units(bot) if load.candle_arrays(u["sym"]) is not None]
    units = F.mark_adds(units)
    for i, u in enumerate(units): u["id"] = i
    chains = load.build_baskets(bot)
    n = len(units); n_tr = int(n * 0.6)
    tr, te = units[:n_tr], units[n_tr:]
    split_t = te[0]["t0"]
    tr_idx = np.arange(n_tr); te_idx = np.arange(n_tr, n)
    print(f"{name}: {len(bot['trades'])} sub-position -> {n} unit ({sum(u['is_add'] for u in units)} nhồi), chain={len(chains)}; train {len(tr)} test {len(te)}", flush=True)
    # ---- suy luận mô tả
    ev = dict(units_all=F.infer_units(units), units_train=F.infer_units(tr), feature_ranks=F.feature_ranks(units), roundness=F.roundness(units),
              add_structure=F.add_structure(units), tranche_stats=F.tranche_stats(units), timing_quality=F.timing_quality(units), oracle_exit_first_touch_all=run_bot.oracle_exit(units),
              shuffle_hold_baseline=F.shuffled_hold_baseline(units), n_chains_harness=len(chains))
    for k in ("units_all",):
        print("  infer:", json.dumps({kk: v for kk, v in ev[k].items() if kk in ("n_units", "win_pct", "n_mae_beyond_isolated_liq", "n_loss_ge_100pct_margin", "pct_units_closed_within60s_of_other_unit")}), flush=True)
    # ---- Level A thoát
    grids, info = F.exit_grids(tr)
    F.pf_register(units)
    for grp, bas, nm in (("all", "notional", "P1_pf_all_notional"), ("all", "margin", "P2_pf_all_margin"), ("sym", "notional", "P3_pf_sym_notional"), ("sym", "margin", "P4_pf_sym_margin")):
        grids.append((nm, "THOÁT CẤP DANH MỤC (đóng cả cụm): đóng mọi unit đang mở của nhóm '%s' khi lãi/lỗ chưa chốt gộp (theo %% %s, trạng thái = vị thế THẬT) chạm TP / SL / trailing-từ-đỉnh; "
                                    "mỗi unit đóng ở tín hiệu đầu tiên sau lúc vào." % (grp, bas), F.pf_exit_grid(grp, bas)))
    print("LEVEL A (thoát)", info, flush=True)
    iters, best_exit = run_exits(units, tr_idx, te_idx, grids, info, quick)
    bp = best_exit["params"]
    rows_tr = _rows(tr, bp); rows_te = _rows(te, bp)
    for r in rows_tr: r["split"] = "train"
    for r in rows_te: r["split"] = "test"
    best_by_test = max(iters, key=lambda it: it["J_test"])
    # ---- Level B vào lệnh
    keys = sorted({(u["sym"], u["side"]) for u in units})
    lo = min(int(F.panel(k[0]).t_close.iloc[0]) for k in keys); hi = max(u["t0"] for u in units) + 15 * MIN
    first_tr = [u for u in tr if not u["is_add"]] or tr
    gate = F.train_gate(first_tr); hh = F.hour_hist_vn(first_tr)
    extra = ("sess",) if name.startswith("Physical") else ()
    rules = F.entry_rules(gate, extra_gates=extra)
    if quick: rules = rules[::6]
    reps = 30 if not quick else 5
    print("LEVEL B (vào lệnh) gate UTC", gate, flush=True)
    lb_first, tab_first, ev_first = entry_block("first", keys, units, lo, hi, hh, split_t, lambda u: not u["is_add"], rules, reps, quick)
    lb_all, tab_all, ev_all = entry_block("all", keys, units, lo, hi, hh, split_t, None, rules, reps, quick)
    # ---- nhồi lệnh
    print("ADD (nhồi)", flush=True)
    lb_add, tab_add = add_block(units, split_t, 200 if not quick else 20, quick)
    print("THOÁT CỤM (cấp danh mục, mức sự kiện)", flush=True)
    pf_ev = pf_block(units, split_t, quick)
    # ---- mô phỏng đầy đủ: luật vào tốt nhất (train, +-15p, sự kiện vào mới) + luật thoát tốt nhất
    notional = float(np.median([u["notional"] for u in first_tr]))
    fr = lb_first["best_tight_15min"]["rule"]
    unit_iters = [it for it in iters if "pf_kind" not in it["params"] and it.get("family") == "exit"]
    best_unit_exit = max(unit_iters, key=lambda it: it["J_train"])
    trades = F.full_sim(keys, fr, best_unit_exit["params"], notional, lo, hi, lev=float(np.median([u["lev"] for u in units])))
    fs_te = [t for t in trades if t["t0"] >= split_t]
    act_first_te = [u for u in te if not u["is_add"]]
    full = dict(entry_rule=fr, exit_model=best_unit_exit["model"], exit_params=best_unit_exit["params"], notional_per_trade=round(notional, 0), n_sim_trades=len(trades), n_sim_trades_test=len(fs_te), n_actual_first_entries_test=len(act_first_te),
                sim_win_pct_test=round(100 * float(np.mean([t["ret"] > 0 for t in fs_te])), 1) if fs_te else None,
                sim_ret_sum_pct_test=round(float(sum(t["ret"] for t in fs_te)), 2) if fs_te else None,
                actual_ret_pct_mean_first_test=round(float(np.mean([u["ret"] for u in act_first_te])), 3) if act_first_te else None,
                sim_ret_pct_mean_test=round(float(np.mean([t["ret"] for t in fs_te])), 3) if fs_te else None,
                cum_sim_usdt=F.cum_series([(t["t1"], t["pnl"]) for t in trades]), cum_sim_usdt_test_only=F.cum_series([(t["t1"], t["pnl"]) for t in fs_te]),
                cum_actual_usdt=F.cum_series([(u["t1"], u["pnl"]) for u in units]),
                note=("Mô phỏng ĐẦY ĐỦ không điều kiện hoá: vào tại tín hiệu của luật vào tốt nhất trên TRAIN (+-15p, sự kiện vào mới), notional cố định = trung vị unit vào mới của train, "
                      "thoát bằng luật thoát tốt nhất; không nhồi lệnh; 1 vị thế/(mã,chiều). So sánh: số lệnh, tỉ lệ thắng, lợi suất - PnL USDT sim dùng notional khác actual nên chỉ dùng để xem hình dạng."))
    print(f"  full_sim: {len(trades)} lệnh sim (test {len(fs_te)}), actual vào mới test {len(act_first_te)}", flush=True)
    # ---- đại diện
    rr = [r for r in rows_te + rows_tr if "sim_ret" in r]
    def dtm(r): return abs(r["sim_close"]["t"] - r["act_close"]["t"]) / MIN if r["sim_closed"] else 1e9
    cands = []
    srt = sorted(rr, key=dtm)
    cands += [("khớp giờ đóng nhất", srt[0]), ("giờ đóng lệch trung vị", srt[len(srt) // 2]), ("lệch nhất", srt[-1]),
              ("lãi lớn nhất (thật)", max(rr, key=lambda r: r["act_pnl"])), ("lỗ lớn nhất (thật)", min(rr, key=lambda r: r["act_pnl"]))]
    seen = set(); rep = []
    for lab, r in cands:
        if r["id"] in seen: continue
        seen.add(r["id"]); rep.append(dict(label=lab, split=r.get("split"), row=r, dt_close_min=None if dtm(r) > 1e8 else round(dtm(r), 1)))
    ex_add = add_examples(units, lb_add, chains)
    # ---- verdict
    tm = best_exit["test"]; lo_ = best_exit["loo"]; sh = ev["shuffle_hold_baseline"]
    exit_lab = ("khớp một phần" if max(tm.get("close_match_60") or 0, lo_["close_match_60"]) >= 25 else "không tái tạo được")
    bt = lb_first["best_tight_15min"]; bc = lb_first["best_coarse_240min"]
    ba = lb_add["best_coarse_240min"]; bat = lb_add["best_tight_15min"]
    verdict = dict(
        exit=exit_lab, entry_first_tight=bt["test"]["strength"] if bt["test"] else "n/a",
        why=(f"THOÁT (Level A, unit, điều kiện hoá theo fill thật; mô hình tốt nhất theo train = {best_exit['model']}): test close +-15p {tm.get('close_match_15')}% / +-60p {tm.get('close_match_60')}%, "
             f"LOO +-15p {lo_['close_match_15']}% / +-60p {lo_['close_match_60']}% (baseline hoán vị thời gian giữ: +-15p {sh['shuffle_hold_match_15_mean']}% (p95 {sh['shuffle_hold_match_15_p95']}%), "
             f"+-60p {sh['shuffle_hold_match_60_mean']}% (p95 {sh['shuffle_hold_match_60_p95']}%)); dấu PnL cùng {tm.get('pnl_sign_agree')}% (LOO {lo_['sign_agree']}%), corr lợi suất test {tm.get('pnl_corr')}. "
             f"VÀO MỚI (Level B, luật tốt nhất train +-15p = {bt['name']}): test recall15 {(bt['test'] or {}).get('recall_15')}% / precision15 {(bt['test'] or {}).get('precision_15')}% vs baseline giờ-khớp "
             f"{(bt['test'] or {}).get('rand_hour_recall_15_mean')}%/{(bt['test'] or {}).get('rand_hour_precision_15_mean')}%; LOO recall15 {bt['loo_all_events']['recall_loo']}% vs ngẫu nhiên {bt['loo_all_events']['expected_by_chance']}% (p={bt['loo_all_events']['p_value']}); "
             f"thô +-4h (chọn theo +-240p): test recall240 {(bc['test'] or {}).get('recall_240')}% vs {(bc['test'] or {}).get('rand_hour_recall_240_mean')}%, LOO {bc['loo_all_events']['recall_loo']}% vs {bc['loo_all_events']['expected_by_chance']}% (p={bc['loo_all_events']['p_value']}). "
             f"NHỒI: luật tốt nhất +-15p = {bat['name']}: LOO recall15 {bat['loo_all_adds']['recall_loo']}% vs {bat['loo_all_adds']['expected_by_chance']}% (p={bat['loo_all_adds']['p_value']}); +-4h = {ba['name']}: LOO {ba['loo_all_adds']['recall_loo']}% vs {ba['loo_all_adds']['expected_by_chance']}% (p={ba['loo_all_adds']['p_value']})."),
        sample_caveat=(f"Chỉ {n} unit ({sum(not u['is_add'] for u in units)} vào mới, {sum(u['is_add'] for u in units)} nhồi) / {len(bot['trades'])} sub-position, test = {len(te)} unit: "
                       "với mẫu này 60/40 chỉ đủ để BÁC BỎ (một luật không khớp ở test là bằng chứng), không đủ để XÁC NHẬN; vì vậy báo thêm LOO và walk-forward. "
                       "Vị thế còn mở (8-12, OKX ẩn mã) không có trong dữ liệu."))
    n_exit_iters = len(iters)
    for blk, fam in ((lb_first, "entry_first"), (lb_all, "entry_all")):
        for pk in blk["per_kind"]:
            tt = pk["test"] or {}; tn = pk["train"] or {}
            iters.append(dict(model="E_" + pk["kind"], family=fam, note="luật vào tốt nhất theo train (F1-excess +-15p) trong họ " + pk["kind"], params=pk["rule"], name=pk["name"],
                              train={k: tn.get(k) for k in ("recall_15", "precision_15", "recall_60", "recall_240", "rand_hour_recall_15_mean", "rand_hour_precision_15_mean", "above_baseline_15", "strength", "n_actual_starts", "n_sim_starts")},
                              test={k: tt.get(k) for k in ("recall_15", "precision_15", "recall_60", "recall_240", "rand_hour_recall_15_mean", "rand_hour_precision_15_mean", "rand_hour_recall_15_p95", "rand_hour_recall_240_mean", "above_baseline_15", "strength", "n_actual_starts", "n_sim_starts")}))
    for pk in lb_add["per_kind"]:
        iters.append(dict(model="A_" + pk["kind"], family="add", note="luật nhồi tốt nhất theo train trong họ " + pk["kind"], params=pk["rule"], name=pk["name"], train=pk["train"], test=pk["test"]))
    seq = [[it["model"], it["J_train"], it["J_test"]] for it in iters[:n_exit_iters]]
    iter_summary = dict(best_by_train=dict(model=best_exit["model"], J_train=best_exit["J_train"], J_test=best_exit["J_test"]),
                        best_by_test_info_only=dict(model=best_by_test["model"], J_test=best_by_test["J_test"]), J_sequence=seq,
                        stop_rule="dừng khi 3 vòng tinh chỉnh liên tiếp (time-stop, SL, trailing) không nâng J_train > 0.005 và LOO không cải thiện; J = trung bình exp(-|dt|/(0.25 x giữ thật)), "
                                  "chỉ để chọn tham số; chỉ số cứng = close_match_15/60.")
    res = dict(
        bot=name, rank=bot["rank"], style=summ["style"], styleKey=summ["styleKey"], idea_from_summary=dict(how=summ["how"], edge=summ["edge"], risk=summ["risk"]),
        hypothesis=HYP[name]["hypothesis"], candidate_rules=HYP[name]["candidate"],
        data=dict(n_subpositions=len(bot["trades"]), n_units=n, n_units_first=sum(not u["is_add"] for u in units), n_units_add=sum(u["is_add"] for u in units), n_chains_harness_baskets=len(chains),
                  n_train=len(tr), n_test=len(te), split_t=split_t, train_period=[tr[0]["t0"], tr[-1]["t0"]], test_period=[te[0]["t0"], te[-1]["t0"]],
                  note_sim="Điều kiện hoá theo fill thật của unit (thời điểm, giá, notional); horizon = t1 thật + 60 phút; chưa đóng -> mark-to-market; phí 3.5 bps/chiều; không funding. "
                          "Unit = tranche (fill cách <=15 phút) + lệnh đóng của chính nó; nhồi = unit mở khi vị thế cùng chiều còn mở.",
                  open_positions_hidden=bot.get("nOpen")),
        inference=ev, iterations=iters,
        best_model=dict(name=best_exit["model"], params=bp, rules_words=rules_words(bp), train=best_exit["train"], test=best_exit["test"], loo=best_exit["loo"],
                        J_train=best_exit["J_train"], J_test=best_exit["J_test"]),
        levelB=dict(first_entries=lb_first, all_entries=lb_all, gate_hours_utc=gate, train_window=[lo, split_t], test_window=[split_t, hi]),
        add_model=lb_add, add_examples=ex_add, portfolio_exit_events=pf_ev, full_sim=full, verdict=verdict, iteration_summary=iter_summary,
        diagnostics=dict(oracle_exit_first_touch=ev["oracle_exit_first_touch_all"], shuffle_hold_baseline=sh,
                         note="oracle_exit: dùng giá thoát THẬT làm mức; nếu bot đặt limit TP cố định thì thoát phải trùng lần chạm ĐẦU của mức đó."),
        cum_curve_train=match.cum_curve(rows_tr), cum_curve_test=match.cum_curve(rows_te), representative=rep, rows=rows_tr + rows_te,
        pnl_check=dict(note="cum_curve_*: [t_đóng_thật, cum PnL thật, cum PnL sim] với sim = vào THẬT + thoát theo luật tốt nhất (điều kiện hoá); full_sim.cum_* là mô phỏng không điều kiện."),
        runtime_s=round(time.time() - t_start, 1))
    add_common_schema(res)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, load.slug(name) + ".json")
    json.dump(res, open(p, "w"), ensure_ascii=False, default=_jsonable)
    print("VERDICT:", json.dumps({k: verdict[k] for k in ("exit", "entry_first_tight")}, ensure_ascii=False), "\nwritten", p, "runtime", res["runtime_s"], flush=True)


def add_common_schema(res):
    """Thêm các khoá cùng schema out/01pp.json (idea, rules, params, metrics train/test Level A & B, levelB.per_family/best_rule_by_train, iteration_summary.null/sequence,
    representative [{tag,id}], verdict.label) + 'highlights' (thành phần nào VỮNG: LOO >=3 hit và p<0.05, walk-forward p<0.1). Idempotent."""
    bm = res["best_model"]; lb = res["levelB"]["first_entries"]; add = res["add_model"]; pf = res.get("portfolio_exit_events", {})
    res["idea"] = res["hypothesis"]
    res["params"] = dict(exit=bm["params"], entry_first_tight_15min=lb["best_tight_15min"]["rule"], entry_first_coarse_240min=lb["best_coarse_240min"]["rule"],
                         add_tight_15min=add["best_tight_15min"]["rule"], add_coarse_240min=add["best_coarse_240min"]["rule"])
    res["rules"] = (f"THOÁT (điều kiện hoá theo fill thật): {bm['rules_words']} | VÀO MỚI (luật tốt nhất train +-15p): {lb['best_tight_15min']['name']}; (+-4h): {lb['best_coarse_240min']['name']} | "
                    f"NHỒI (+-15p): {add['best_tight_15min']['name']}; (+-4h): {add['best_coarse_240min']['name']}")
    bt = lb["best_tight_15min"]
    res["metrics"] = dict(train=dict(levelA=bm["train"], levelB=bt["train"]), test=dict(levelA=bm["test"], levelB=bt["test"]),
                          loo=dict(levelA=bm["loo"], levelB_first_tight=bt["loo_all_events"], levelB_first_coarse=lb["best_coarse_240min"]["loo_all_events"],
                                   add_tight=add["best_tight_15min"]["loo_all_adds"], add_coarse=add["best_coarse_240min"]["loo_all_adds"]),
                          walk_forward=dict(levelA=bm["loo"].get("walk_forward"), levelB_first_tight=bt["walk_forward"], levelB_first_coarse=lb["best_coarse_240min"]["walk_forward"],
                                            add_tight=add["best_tight_15min"]["walk_forward"], add_coarse=add["best_coarse_240min"]["walk_forward"]))
    res["levelB"]["n_rules"] = lb["n_rules"]
    res["levelB"]["per_family"] = [dict(family=pk["kind"], rule=pk["rule"], train_f1_excess=pk["train_f1_excess_15"], train=pk["train"], test=pk["test"]) for pk in lb["per_kind"]]
    res["levelB"]["best_rule_by_train"] = dict(family=bt["rule"]["kind"], rule=bt["rule"], train_f1_excess=bt["train_f1_excess"], train=bt["train"], test=bt["test"])
    res["levelB"]["note"] = lb["note"]
    it = res["iterations"]; ex = [i for i in it if i.get("family") == "exit"]
    for i in it:
        i.setdefault("mode", {"exit": "exit_conditioned_on_real_entry", "entry_first": "entry_signal", "entry_all": "entry_signal", "add": "add_conditioned_on_real_position"}.get(i.get("family"), "?"))
    null = next((i for i in ex if i["model"] == "X0_time_stop"), None)
    sm = res["iteration_summary"]
    if null: sm["null"] = dict(train=null["J_train"], test=null["J_test"])
    sm["sequence"] = [[i["model"], i["mode"], i["J_train"], i["J_test"], i["test"].get("close_match_15")] for i in ex]
    # đại diện: [{tag,id}] (id = id unit trong rows)
    if res.get("representative") and "row" in res["representative"][0]:
        res["representative"] = [dict(tag=r["label"], id=r["row"]["id"], split=r.get("split"), dt_close_min=r.get("dt_close_min")) for r in res["representative"]]
    # điểm vững
    hl = []
    def chk(name, loo, wf):
        if loo and loo.get("hits", 0) >= 3 and loo.get("p_value") is not None and loo["p_value"] < 0.05 and wf and wf.get("p_value") is not None and wf["p_value"] < 0.1:
            hl.append(f"{name}: LOO {loo['recall_loo']}% vs ngẫu nhiên {loo['expected_by_chance']}% (p={loo['p_value']}), walk-forward {wf['recall_wf']}% vs {wf['expected_by_chance']}% (p={wf['p_value']})")
    m = res["metrics"]
    ng = lb.get("no_event_gate")
    if ng:   # vào mới: chỉ tính khi vững cả với luật KHÔNG cổng giờ suy từ event (tránh rò rỉ nhẹ của cổng giờ fit trên train)
        chk("vào mới +-15p (không cổng giờ suy từ dữ liệu)", ng["tight_15min"]["loo"], ng["tight_15min"]["walk_forward"])
        chk("vào mới +-4h (không cổng giờ suy từ dữ liệu)", ng["coarse_240min"]["loo"], ng["coarse_240min"]["walk_forward"])
    else:
        chk("vào mới +-15p", m["loo"]["levelB_first_tight"], m["walk_forward"]["levelB_first_tight"]); chk("vào mới +-4h", m["loo"]["levelB_first_coarse"], m["walk_forward"]["levelB_first_coarse"])
    chk("nhồi +-15p", m["loo"]["add_tight"], m["walk_forward"]["add_tight"]); chk("nhồi +-4h", m["loo"]["add_coarse"], m["walk_forward"]["add_coarse"])
    for k, v in pf.items():
        for sub in ("best_tight_15min", "best_coarse_240min"):
            chk(f"thoát cụm {k} {v[sub]['name']} ({'+-15p' if sub.startswith('best_t') else '+-4h'})", v[sub]["loo"], v[sub]["walk_forward"])
    v = res["verdict"]; v["highlights"] = hl
    lm = bm["loo"]; sh = res["inference"]["shuffle_hold_baseline"]
    exit_sig = lm["close_match_15"] >= 20 and lm["close_match_15"] > sh["shuffle_hold_match_15_p95"]
    bo = next((i.get("by_outcome_train_plus_test") for i in res["iterations"] if i.get("family") == "exit" and i["model"] == bm["name"]), None)
    bo_txt = (" [thắng %d/%d, thua %d/%d khớp +-15p]" % (bo["winners"]["match_15"], bo["winners"]["n"], bo["losers"]["match_15"], bo["losers"]["n"])) if bo else ""
    v["label"] = ("không tái tạo được ở mức giờ-phút; thoát từng lệnh: " + ("khớp một phần" if exit_sig else "không vượt baseline đáng kể") + f" (LOO +-15p {lm['close_match_15']}% vs hoán vị p95 {sh['shuffle_hold_match_15_p95']}%){bo_txt}"
                  + ("; vùng +-4h / cụm: %d thành phần vững (xem highlights)" % len(hl) if hl else "; không thành phần nào vững qua LOO + walk-forward"))
    return res


def compat_only(name):
    p = os.path.join(OUT, load.slug(name) + ".json")
    res = json.load(open(p))
    add_common_schema(res)
    json.dump(res, open(p, "w"), ensure_ascii=False, default=_jsonable)
    print("compat ok", p)


def rules_words(p):
    s = ["Vào lệnh = fill thật của unit (điều kiện hoá)."]
    if p.get("tp"):
        unit = {1: "% giá" + (" (ROI/đòn bẩy)" if p.get("roi") else ""), 2: "x ATR1h"}.get(int(p.get("tp_mode", 0)), "")
        s.append(f"TP {p['tp']} {unit} từ giá TB.")
    if p.get("round_k"): s.append(f"TP tại mức tròn đầu tiên cách >= {p['round_k']} x ATR.")
    if p.get("sl"): s.append(f"SL {p['sl']} {({1: '% giá', 2: 'x ATR1h'}).get(int(p.get('sl_mode', 0)), '')} từ giá TB.")
    if p.get("tr_act"): s.append(f"Trailing: kích hoạt {p['tr_act']}, lùi {p['tr_dist']} ({'ATR' if int(p.get('tr_mode', 0)) == 2 else '%'}).")
    if p.get("hold_min"): s.append(f"Time-stop {int(p['hold_min'])} phút.")
    if p.get("ema_mode"): s.append(f"Thoát khi nến 1h đóng qua EMA{20 if int(p['ema_mode']) == 1 else 50} (buffer {p.get('ema_buf', 0)} ATR), giữ tối thiểu {int(p.get('min_hold_min', 0))} phút.")
    if p.get("rsi_lvl"): s.append(f"Thoát khi RSI1h >= {p['rsi_lvl']} (long) / <= {100 - p['rsi_lvl']} (short).")
    if p.get("sess_hr", -1) is not None and int(p.get("sess_hr", -1)) >= 0: s.append(f"Thoát tại phút 00 giờ {int(p['sess_hr'])} UTC sau khi giữ >= {int(p.get('sess_min_hold_h', 0))}h.")
    return " ".join(s)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--compat" in sys.argv:
        compat_only(args[0])
    else:
        run(args[0], quick="--quick" in sys.argv)
