"""Chạy harness cho 1 bot:  run_limited.sh --no-lock -- test/scripts/okx_top10/run_bot.py "01pp" [--quick]
Ghi test/scripts/okx_top10/out/<slug>.json.

Quy trình:
  1. dựng basket (load.py), lọc basket có nến, chia 60% đầu (train) / 40% cuối (test) theo thời gian t0.
  2. INFER: thống kê mô tả trên TRAIN (bước add theo 3 mốc tham chiếu, tỉ lệ size, thoát so với avg, ...) -> lưới tham số có cơ sở.
  3. LEVEL A: với mỗi họ mô hình, grid search trên TRAIN (điểm = match.score), báo TRAIN và TEST (headline = TEST).
  4. LEVEL B: luật vào lệnh (đặc trưng x ngưỡng x cổng giờ x cooldown) fit trên TRAIN, báo TEST + baseline ngẫu nhiên.
  5. verdict + hàng so sánh từng basket cho vẽ biểu đồ.
"""
import itertools
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features
import load
import match
import sim

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
G = {}  # dữ liệu dùng chung cho worker (fork)

HYPOTHESES = {
    "01pp": ("DCA hai chiều (long/short) bắt hồi: mở vị thế lớn tại mức giá đã chọn, nếu giá đi ngược thì vào thêm các tầng NHỎ HƠN "
             "(add/first ~ 1/3) cách nhau ~0,76% (trung vị), cả rổ chốt cùng lúc khi giá quay về gần giá vốn trung bình (lãi nhỏ, tỉ lệ thắng 64%), "
             "không rõ stop-loss. Giả thuyết kiểm định: bước add cố định % tính từ fill gần nhất/đầu/avg + TP % từ avg đóng cả rổ "
             "(hoặc TP từng tầng, hoặc bước theo ATR)."),
}


# ---------------------------------------------------------------- tiện ích
def _default(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, np.ndarray): return o.tolist()
    raise TypeError(type(o))


def _q(a, qs):
    a = np.asarray(a, float)
    return [] if len(a) == 0 else [round(float(x), 3) for x in np.percentile(a, qs)]


def _rows(baskets, params, horizon=60):
    return [match.basket_row(B, sim.simulate(B, params, horizon)) for B in baskets]


def _eval_train(params):
    return match.level_a(_rows(G["train"], params))


def _grid(spec):
    keys = list(spec)
    return [dict(zip(keys, v)) for v in itertools.product(*[spec[k] for k in keys])]


def _fit(grid, pool):
    """Chọn tham số tốt nhất trên TRAIN (score, rồi pnl_med_abs_err nhỏ hơn)."""
    res = pool.map(_eval_train, grid, chunksize=max(1, len(grid) // (4 * 8)))
    best = max(range(len(grid)), key=lambda i: (res[i].get("score", 0), -res[i].get("pnl_med_abs_err_pp", 9e9)))
    return grid[best], res[best], len(grid)


def _trim(m):
    keep = ["n_baskets", "n_simulated", "score", "add_time_match", "add_match", "add_match_any", "add_px_err_bps_med", "add_px_err_bps_p90",
            "layer_eq", "n_sim_layers_mean", "n_act_layers_mean", "close_match_5", "close_match_15", "close_match_60", "sim_closed_pct",
            "close_px_err_bps_med", "close_px_err_bps_p90", "layer_close_n", "layer_close_match5", "layer_close_px_err_bps_med",
            "pnl_sign_agree", "pnl_corr", "pnl_med_abs_err_pp", "pnl_corr_usdt", "act_pnl_sum", "sim_pnl_sum", "act_win_pct", "sim_win_pct",
            "n_actual_adds", "tr_n_actual_adds", "tr_add_time_match", "tr_add_match", "tr_add_match_any", "tr_add_px_err_bps_med", "tr_add_px_err_bps_p90",
            "tr_layer_eq"]
    return {k: m.get(k) for k in keep if k in m}


# ---------------------------------------------------------------- INFER
def infer(train, bot):
    """Bằng chứng từ TRAIN về luật add / size / thoát (không dùng nến test)."""
    sg = lambda B: 1 if B["side"] == "long" else -1
    st = dict(last=[], first=[], avg=[]); gaps = []; ratio_first = []; ratio_prev = []; fav = 0; nadd = 0
    step_over_atr = []
    raw_gaps = [(B["fills"][i]["t"] - B["fills"][i - 1]["t"]) / 60000 for B in train for i in range(1, len(B["fills"]))]
    for B in train:
        f = B["tranches"]; q = f[0]["qty"]; sp = f[0]["px"] * f[0]["qty"]   # tầng DCA = tranche (fill cách <=15 phút gộp lại)
        sc = sim.atr_scale(B["sym"]); a = load.candle_arrays(B["sym"])
        for i in range(1, len(f)):
            x = f[i]; nadd += 1
            adv_l = -(x["px"] / f[i - 1]["px"] - 1) * sg(B) * 100
            adv_f = -(x["px"] / f[0]["px"] - 1) * sg(B) * 100
            adv_a = -(x["px"] / (sp / q) - 1) * sg(B) * 100
            if adv_l <= 0: fav += 1
            else:
                st["last"].append(adv_l)
                if adv_f > 0: st["first"].append(adv_f)
                if adv_a > 0: st["avg"].append(adv_a)
                j = int(np.searchsorted(a["t"], f[i - 1]["t"], side="right")) - 1
                step_over_atr.append((adv_l, float(sc[j]), adv_l / float(sc[j])))
            gaps.append((x["t"] - f[i - 1]["t_last"]) / 60000)
            ratio_first.append(x["notional"] / f[0]["notional"]); ratio_prev.append(x["notional"] / f[i - 1]["notional"])
            q += x["qty"]; sp += x["px"] * x["qty"]
    robust_cv = lambda a: round(float(np.median(np.abs(np.array(a) - np.median(a))) / np.median(a)), 3) if len(a) > 3 else None
    # thoát: lợi suất từ avg tại lần đóng cuối
    ret_close = []; atr0 = []; staged = 0; multi = 0; whole = 0; hold = []
    for B in train:
        last = B["t1"]; cl = [c for c in B["closes"] if abs(c["t"] - last) <= 2000]
        fl = [B["fills"][c["fill"]] for c in cl]
        avg = sum(x["px"] * x["qty"] for x in fl) / sum(x["qty"] for x in fl)
        pxc = sum(c["px"] * c["qty"] for c in cl) / sum(c["qty"] for c in cl)
        ret_close.append((pxc / avg - 1) * sg(B) * 100)
        a_ = load.candle_arrays(B["sym"]); j_ = int(np.searchsorted(a_["t"], B["t0"], side="right")) - 1
        atr0.append(float(sim.atr_scale(B["sym"])[j_]))
        hold.append((B["t1"] - B["t0"]) / 3.6e6)
        if len(B["fills"]) > 1:
            multi += 1
            if len(cl) == len(B["closes"]): whole += 1
    rc = np.array(ret_close); ra = rc / np.array(atr0)
    # độ "tròn" của giá fill so với nến: <=3 chữ số có nghĩa (vd 1760, 80000) so với mức nền trên giá đóng nến 1m cùng mã
    def sig4(p, n=3):
        e = 10 ** (np.floor(np.log10(abs(p))) - (n - 1))
        return abs(p / e - round(p / e)) < 1e-6
    fills_round = [sig4(x["px"]) for B in train for x in B["fills"]]
    base = []
    rng = np.random.default_rng(0)
    for B in train:
        a = load.candle_arrays(B["sym"])
        base += [sig4(float(p)) for p in a["c"][rng.integers(0, len(a["c"]), 40)]]
    ev = dict(
        n_train_baskets=len(train), n_fills=sum(len(B["fills"]) for B in train), n_tranches=sum(len(B["tranches"]) for B in train), n_tranche_adds=nadd,
        tranche_note="add = tranche (fill cách nhau <=15 phút gộp thành 1 lệnh vào) - các số step/size/gap dưới đây tính trên tranche",
        pct_baskets_single_fill=round(100 * np.mean([len(B["fills"]) == 1 for B in train]), 1),
        fills_per_basket_q=_q([len(B["fills"]) for B in train], [50, 75, 90, 100]),
        adds_adverse_vs_last_pct=round(100 * (1 - fav / max(1, nadd)), 1),
        step_adverse_pct_q_last=_q(st["last"], [10, 25, 50, 75, 90]), step_adverse_pct_q_first=_q(st["first"], [10, 25, 50, 75, 90]),
        step_adverse_pct_q_avg=_q(st["avg"], [10, 25, 50, 75, 90]),
        step_robust_cv_last=robust_cv(st["last"]), step_robust_cv_first=robust_cv(st["first"]), step_robust_cv_avg=robust_cv(st["avg"]),
        step_over_atr_q=_q([x[2] for x in step_over_atr], [10, 25, 50, 75, 90]),
        step_vs_atr_spearman=(round(float(pd.Series([x[0] for x in step_over_atr]).rank().corr(pd.Series([x[1] for x in step_over_atr]).rank())), 3)
                              if len(step_over_atr) > 5 else None),
        gap_min_to_prev_tranche_q=_q(gaps, [10, 25, 50, 75, 90]),
        raw_fill_gap_min_q=_q(raw_gaps, [10, 25, 50, 75, 90]), pct_raw_adds_within_15min_of_prev_fill=round(100 * float(np.mean(np.array(raw_gaps) <= 15)), 1) if raw_gaps else None,
        n_tranches_per_basket_q=_q([len(B["tranches"]) for B in train], [50, 75, 90, 100]),
        add_over_first_notional_q=_q(ratio_first, [10, 25, 50, 75, 90]), add_over_prev_notional_q=_q(ratio_prev, [10, 25, 50, 75, 90]),
        close_ret_from_avg_pct_q=_q(rc, [5, 10, 25, 50, 75, 90, 95]), close_positive_pct=round(100 * float((rc > 0).mean()), 1),
        close_pos_q=_q(rc[rc > 0], [10, 25, 50, 75, 90]), close_neg_q=_q(rc[rc < 0], [10, 25, 50, 75, 90]),
        close_pos_robust_cv=robust_cv(rc[rc > 0]) if (rc > 0).sum() > 3 else None,
        close_pos_over_atr_q=_q(ra[rc > 0], [10, 25, 50, 75, 90]), close_pos_over_atr_robust_cv=robust_cv(ra[rc > 0]) if (rc > 0).sum() > 3 else None,
        close_neg_over_atr_q=_q(-ra[rc < 0], [10, 25, 50, 75, 90]), close_neg_over_atr_robust_cv=robust_cv(-ra[rc < 0]) if (rc < 0).sum() > 3 else None,
        pct_multifill_baskets_closed_all_at_once=round(100 * whole / max(1, multi), 1),
        hold_h_q=_q(hold, [10, 25, 50, 75, 90]),
        pct_fill_px_round_3sig=round(100 * float(np.mean(fills_round)), 1), pct_candle_close_round_3sig_baseline=round(100 * float(np.mean(base)), 1),
        lev_q=_q([B["lev"] for B in train], [10, 50, 90]), long_pct=round(100 * float(np.mean([B["side"] == "long" for B in train])), 1),
    )
    return ev


def derive_grids(ev, train):
    """Lưới tham số có cơ sở từ thống kê TRAIN (phân vị quan sát, không tinh chỉnh từng basket)."""
    uq = lambda a: sorted({round(float(x), 3) for x in a if x and x > 0})
    qs = lambda a, ps: np.percentile(a, ps) if len(a) else []
    steps = uq(ev["step_adverse_pct_q_last"][:4] + [ev["step_adverse_pct_q_last"][2] * 1.5, ev["step_adverse_pct_q_last"][2] * 2.5])
    layers = sorted({2, 3, 4, 6, int(max(2, ev["n_tranches_per_basket_q"][2])), int(max(2, ev["n_tranches_per_basket_q"][3]))})
    tps = uq(ev["close_pos_q"] + [ev["close_pos_q"][2] * 0.6])
    sls = uq([abs(x) for x in ev["close_neg_q"][1:]])
    r1 = ev["add_over_first_notional_q"]
    size = uq([r1[1], r1[2], r1[3]])
    atr_k = uq(ev["step_over_atr_q"][1:4]) + [round(ev["step_over_atr_q"][2] * 0.5, 3)]
    tp_atr = uq(ev["close_pos_over_atr_q"][1:]); sl_atr = uq(ev["close_neg_over_atr_q"][1:])
    holdm = float(np.median([(B["t1"] - B["t0"]) / 6e4 for B in train]))
    delays = sorted({max(16, int(round(x))) for x in ev["gap_min_to_prev_tranche_q"][1:4]})
    return dict(delays=delays, tp_atr=tp_atr, sl_atr=sl_atr, steps=steps, layers=layers, tps=tps, sls=sls, size=size, atr_k=sorted(set(atr_k)), hold_med_min=holdm)


# ---------------------------------------------------------------- chẩn đoán "oracle" (không dùng để fit)
def oracle_exit(baskets):
    """Giới hạn trên của mọi luật thoát THEO MỨC GIÁ: lấy giá thoát THẬT làm mức TP/SL; hỏi lần ĐẦU giá chạm mức đó (sau fill cuối bị đóng
    ở lần đóng cuối) có trùng giờ thoát thật không. Nếu thoát thật thường muộn hơn lần chạm đầu -> bot không đặt lệnh mức giá cố định."""
    out = dict(tp=dict(n=0, hit5=0, hit15=0, hit60=0, delays_h=[]), sl=dict(n=0, hit5=0, hit15=0, hit60=0, delays_h=[]))
    for B in baskets:
        a = load.candle_arrays(B["sym"]); s_ = 1 if B["side"] == "long" else -1
        last = B["t1"]; cl = [c for c in B["closes"] if abs(c["t"] - last) <= 2000]
        fl = [B["fills"][c["fill"]] for c in cl]
        avg = sum(x["px"] * x["qty"] for x in fl) / sum(x["qty"] for x in fl)
        pxc = sum(c["px"] * c["qty"] for c in cl) / sum(c["qty"] for c in cl)
        tstart = max(x["t"] for x in fl)
        i0 = int(np.searchsorted(a["t"], tstart, side="right")); i1 = int(np.searchsorted(a["t"], last, side="right"))
        if i1 <= i0: continue
        win = slice(i0, i1 + 1)
        kind = "tp" if s_ * (pxc - avg) > 0 else "sl"
        reach = (a["h"][win] >= pxc) if (s_ == 1 and kind == "tp") or (s_ == -1 and kind == "sl") else (a["l"][win] <= pxc)
        if not reach.any(): continue
        t_touch = int(a["t"][win][np.argmax(reach)])
        d = (last - t_touch) / 60000
        o = out[kind]; o["n"] += 1; o["delays_h"].append(d / 60)
        for m in (5, 15, 60):
            if d <= m: o[f"hit{m}"] += 1
    res = {}
    for k, o in out.items():
        n = max(1, o["n"])
        res[k] = dict(n=o["n"], first_touch_within_5min_pct=round(100 * o["hit5"] / n, 1), within_15min_pct=round(100 * o["hit15"] / n, 1),
                      within_60min_pct=round(100 * o["hit60"] / n, 1), delay_after_first_touch_h_q=_q(o["delays_h"], [25, 50, 75, 90]))
    return res


# ---------------------------------------------------------------- LEVEL B
def level_b(baskets_all, split_t, hours_train):
    act_tr, act_te = {}, {}
    for B in baskets_all:
        (act_tr if B["t0"] < split_t else act_te).setdefault((B["sym"], B["side"]), []).append(B["t0"])
    act_tr = {k: np.array(sorted(v), np.int64) for k, v in act_tr.items()}
    act_te = {k: np.array(sorted(v), np.int64) for k, v in act_te.items()}
    syms = sorted({B["sym"] for B in baskets_all})
    t_lo = min(B["t0"] for B in baskets_all); t_hi = max(B["t0"] for B in baskets_all) + 15 * 60_000
    hh = np.bincount(((np.array([B["t0"] for B in baskets_all if B["t0"] < split_t]) // 3_600_000 + 7) % 24).astype(int), minlength=24).astype(float)
    hh = (hh + 0.5); hh /= hh.sum()
    top = np.argsort(-np.convolve(np.r_[hh, hh[:3]], np.ones(4), "valid")[:24])[0]
    gate = [(int(top) + i) % 24 for i in range(4)]  # khung 4 giờ VN dày nhất trên TRAIN

    def sigs(rule, lo, hi):
        out = {}
        for s in syms:
            r = features.signals(s, rule)
            if r is None: continue
            for side, t in zip(("long", "short"), r):
                t = t[(t >= lo) & (t <= hi)]
                if len(t): out[(s, side)] = t
        return out

    grid = [dict(feat=f, thr=t, mode=m, hours=h, cool_h=c) for f in features.FEATURES
            for t in ((10, 15, 20, 25) if f == "rsi" else (0.5, 1.0, 1.5, 2.0, 2.5))
            for m in ("contra", "mom") for h in (None, gate) for c in (1, 6, 24)]
    fit = []
    for rule in grid:
        m = match.level_b(act_tr, sigs(rule, t_lo, split_t), t_lo, split_t, reps=15, seed=1, hour_hist=hh)
        fit.append((match.f1_excess(m), rule, m))
    res = dict(gate_hours_vn=gate, n_rules=len(grid), train_window=[t_lo, split_t], test_window=[split_t, t_hi], per_family=[])
    best_by = {}
    for sc, rule, m in fit:
        k = (rule["feat"], rule["mode"])
        if k not in best_by or sc > best_by[k][0]: best_by[k] = (sc, rule, m)
    allbest = max(fit, key=lambda x: x[0])
    for k, (sc, rule, m) in sorted(best_by.items(), key=lambda kv: -kv[1][0]):
        tr = match.level_b(act_tr, sigs(rule, t_lo, split_t), t_lo, split_t, reps=200, seed=2, hour_hist=hh)
        te = match.level_b(act_te, sigs(rule, split_t, t_hi), split_t, t_hi, reps=200, seed=3, hour_hist=hh)
        res["per_family"].append(dict(feat=k[0], mode=k[1], rule=rule, train_f1_excess=round(sc, 4), train=tr, test=te))
    res["best_rule_by_train"] = [d for d in res["per_family"] if d["rule"] == allbest[1]][0]
    res["note"] = ("Luật chọn theo F1(+-15p) vượt baseline trên TRAIN; chỉ coi là 'khớp' khi TEST recall VÀ precision (+-15p) đều > p95 của "
                   "cả baseline ngẫu nhiên đều và baseline ngẫu nhiên khớp phân bố giờ VN.")
    return res


# ---------------------------------------------------------------- verdict
def verdict(test_m, lvb):
    cm = test_m.get("close_match_15") or 0; am = test_m.get("add_match") or 0; corr = test_m.get("pnl_corr") or 0
    sign = test_m.get("pnl_sign_agree") or 0; leq = test_m.get("layer_eq") or 0
    if cm >= 60 and am >= 50 and corr >= 0.7: lab = "khớp tốt"
    elif cm >= 25 or am >= 25 or (corr >= 0.5 and sign >= 70): lab = "khớp một phần"
    else: lab = "không tái tạo được"
    why = (f"TEST (40% basket cuối, điều kiện hoá theo fill đầu thật): thoát +-15p {cm:.1f}% (+-60p {test_m.get('close_match_60')}%), "
           f"add khớp giờ+giá {am:.1f}% (chỉ giờ {test_m.get('add_time_match')}%), số tầng bằng {leq:.1f}%, dấu PnL cùng {sign:.1f}%, "
           f"corr lợi suất {corr}. Tiêu chí: 'khớp tốt' = thoát15>=60 & add>=50 & corr>=0.7; 'một phần' = thoát15>=25 hoặc add>=25 hoặc (corr>=0.5 & dấu>=70).")
    b = lvb["best_rule_by_train"]["test"]
    why += (f" Level B (luật vào lệnh tốt nhất trên train, test): recall15 {b['recall_15']}% / precision15 {b['precision_15']}% vs baseline giờ-khớp "
            f"{b.get('rand_hour_recall_15_mean')}% / {b.get('rand_hour_precision_15_mean')}% (p95 {b.get('rand_hour_recall_15_p95')}% / {b.get('rand_hour_precision_15_p95')}%) -> "
            f"{'VƯỢT' if b['above_baseline_15'] else 'KHÔNG vượt'} baseline.")
    return dict(label=lab, why=why)


# ---------------------------------------------------------------- mô hình
def families(gr, ev, best=None):
    """Danh sách (tên, ghi chú, lưới). Tất cả điều kiện hoá theo fill đầu thật; size add = size_mult x notional fill đầu."""
    sz = gr["size"][len(gr["size"]) // 2]
    base = dict(add_ref=[0], step_pct=gr["steps"], step_growth=[1.0], max_layers=gr["layers"], size_mult=[sz], size_ref=[1],
                tp_pct=gr["tps"], tp_ref=[0], tp_mode=[0], sl_pct=[0.0])
    F = []
    F.append(("M0_null", "Mốc rỗng: 1 fill, không add/TP, time-stop = trung vị thời gian giữ của train. Cho biết điểm 'đoán mò có cấu trúc'.",
              _grid(dict(add_ref=[0], step_pct=[1.0], max_layers=[1], max_hold_bars=[int(gr["hold_med_min"] * k) for k in (0.25, 0.5, 1, 2, 4)]))))
    F.append(("M1_step_last_TP_avg", "(a) bước % cố định tính từ fill GẦN NHẤT, TP % từ giá TB, đóng cả rổ.", _grid(base)))
    F.append(("M1b_step_last_TP_first", "như (a) nhưng TP tính từ giá fill ĐẦU thay vì giá TB.", _grid({**base, "tp_ref": [1]})))
    F.append(("M2_step_first_ladder", "(b) thang lưới từ fill ĐẦU: mức add k = giá đầu -/+ k x bước; TP từ avg, đóng cả rổ.", _grid({**base, "add_ref": [1]})))
    F.append(("M2b_step_avg", "bước % tính từ giá TRUNG BÌNH hiện tại (avg), TP từ avg.", _grid({**base, "add_ref": [2]})))
    F.append(("M3_per_layer_TP", "(c) mỗi tầng có TP riêng từ giá fill của nó (đóng từng tầng), bước từ fill gần nhất.",
              _grid({**base, "tp_mode": [1]})))
    F.append(("M4_ATR_step", "(d) bước = k x ATR%(1h,14) tại fill tham chiếu (k lấy từ tỉ lệ step/ATR quan sát), TP % từ avg, đóng cả rổ.",
              _grid({**base, "step_pct": gr["atr_k"], "use_scale": [1]})))
    F.append(("M5_time_scale_in", "add THEO THỜI GIAN (scale-in mỗi D phút, bất kể giá; D lấy từ phân vị khoảng cách tranche của train) + TP % từ avg, đóng cả rổ - kiểm tra giả thuyết 47% add xảy ra <15 phút sau fill trước.",
              _grid({**base, "add_ref": [3], "step_pct": [1.0], "add_delay_min": gr["delays"]})))
    F.append(("M6_TP_ATR", "bước % cố định từ fill gần nhất NHƯNG TP = bội số ATR%(1h) tại fill đầu (TP co giãn theo biến động), đóng cả rổ.",
              _grid({**base, "tp_pct": gr["tp_atr"], "tp_use_scale": [1]})))
    # nhóm "ép cấu trúc DCA" (max_layers>=6): so sánh công bằng điểm tham chiếu của bước add, vì lưới tự do luôn thoái hoá về ~không add
    forced = {**base, "max_layers": [6, 12]}
    F.append(("F1_forced_last", "ÉP DCA (>=6 tầng): bước từ fill gần nhất, TP từ avg, đóng cả rổ.", _grid({**forced, "add_ref": [0]})))
    F.append(("F2_forced_first", "ÉP DCA (>=6 tầng): thang lưới từ fill đầu.", _grid({**forced, "add_ref": [1]})))
    F.append(("F3_forced_avg", "ÉP DCA (>=6 tầng): bước từ giá trung bình.", _grid({**forced, "add_ref": [2]})))
    F.append(("F4_forced_ATR", "ÉP DCA (>=6 tầng): bước = k x ATR%.", _grid({**forced, "step_pct": gr["atr_k"], "use_scale": [1]})))
    F.append(("F5_forced_per_layer_TP", "ÉP DCA (>=6 tầng): mỗi tầng TP riêng.", _grid({**forced, "tp_mode": [1]})))
    return F


def run(name, quick=False):
    t_start = time.time()
    bot = load.get_bot(name); summ = load.load_summary()["bots"][name]
    allb = load.build_baskets(bot)
    chk = load.check_bk(bot, allb)
    cov = load.coverage(bot)
    missing = [r["sym"] for r in cov if not r["file"]]
    baskets = [B for B in allb if load.candle_arrays(B["sym"]) is not None]
    baskets = [B for B in baskets if B["t0"] >= load.candle_arrays(B["sym"])["t"][0]]
    n_tr = int(len(baskets) * 0.6)
    train, test = baskets[:n_tr], baskets[n_tr:]
    split_t = test[0]["t0"]
    G["train"] = train
    ev = infer(train, bot)
    gr = derive_grids(ev, train)
    print("infer:", json.dumps(ev, ensure_ascii=False)[:1500], flush=True)
    print("grids:", gr, flush=True)
    ncpu = min(10, len(os.sched_getaffinity(0)))
    pool = mp.get_context("fork").Pool(ncpu)
    iters = []; fitted = {}
    for nm, note, grid in families(gr, ev):
        if quick: grid = grid[::max(1, len(grid) // 40)]
        t = time.time()
        p, tr, n = _fit(grid, pool)
        te = match.level_a(_rows(test, p))
        iters.append(dict(model=nm, note=note, params=p, n_grid=n, train=_trim(tr), test=_trim(te), secs=round(time.time() - t, 1)))
        fitted[nm] = p
        print(f"{nm}: grid {n} train score {tr['score']} test score {te['score']} | test close15 {te.get('close_match_15')} add {te.get('add_match')} layer_eq {te.get('layer_eq')} "
              f"corr {te.get('pnl_corr')} | params {p} ({time.time()-t:.0f}s)", flush=True)
    # ---- vòng 2: thêm SL / time stop / trailing / tăng bước trên mô hình tốt nhất theo TRAIN (không chọn theo TEST)
    cand = [it for it in iters if it["model"] != "M0_null"]
    bestit = max(cand, key=lambda it: it["train"]["score"])
    bp = dict(bestit["params"])
    ext = [("R1_best+SL", "mô hình tốt nhất theo train + stop-loss % (từ avg).", _grid({**{k: [v] for k, v in bp.items()}, "sl_pct": [0.0] + gr["sls"]})),
           ("R2b_best+SL_ATR", "SL = bội số ATR%(1h) tại fill đầu.", _grid({**{k: [v] for k, v in bp.items()}, "sl_pct": gr["sl_atr"], "sl_use_scale": [1]})),
           ("R2_best+SL_first", "như R1 nhưng SL tính từ fill đầu.", _grid({**{k: [v] for k, v in bp.items()}, "sl_pct": gr["sls"], "sl_ref": [1]})),
           ("R3_best+growth_size", "thêm bước tăng dần (growth) và size add khác nhau.",
            _grid({**{k: [v] for k, v in bp.items()}, "step_growth": [1.0, 1.25, 1.5], "size_mult": gr["size"], "size_ref": [0, 1]})),
           ("R4_best+timestop_trail", "thêm time-stop (bội trung vị giữ lệnh) và trailing (kích hoạt/lùi).",
            _grid({**{k: [v] for k, v in bp.items()}, "max_hold_bars": [0] + [int(gr["hold_med_min"] * k) for k in (1, 2, 4)],
                   "trail_act": [0.0] + gr["tps"][:3], "trail_dist": [0.3, 0.6]}))]
    for nm, note, grid in ext:
        if quick: grid = grid[::max(1, len(grid) // 20)]
        t = time.time()
        p, tr, n = _fit(grid, pool)
        te = match.level_a(_rows(test, p))
        iters.append(dict(model=nm, note=note, params=p, n_grid=n, train=_trim(tr), test=_trim(te), secs=round(time.time() - t, 1)))
        print(f"{nm}: grid {n} train {tr['score']} test {te['score']} | test close15 {te.get('close_match_15')} add {te.get('add_match')} corr {te.get('pnl_corr')} | {p}", flush=True)
    pool.close()
    cand = [it for it in iters if it["model"] != "M0_null"]
    best = max(cand, key=lambda it: it["train"]["score"])
    bp = best["params"]
    rows_tr = _rows(train, bp); rows_te = _rows(test, bp)
    for r in rows_tr: r["split"] = "train"
    for r in rows_te: r["split"] = "test"
    best["test_single_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] == 1]))
    best["test_multi_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] > 1]))
    lvb = level_b(baskets, split_t, None)
    v = verdict(best["test"], lvb)
    res = dict(
        bot=name, rank=bot["rank"], style=summ["style"], styleKey=summ["styleKey"], idea_from_summary=dict(how=summ["how"], edge=summ["edge"], risk=summ["risk"]),
        hypothesis=HYPOTHESES.get(name, summ["how"] + " " + summ["edge"]),
        data=dict(n_subpositions=len(bot["trades"]), n_baskets=len(allb), n_baskets_simulated=len(baskets), basket_check=chk,
                  symbols_missing_candles=missing, coverage=cov, n_train=len(train), n_test=len(test), split_t=split_t,
                  train_period=[train[0]["t0"], train[-1]["t0"]], test_period=[test[0]["t0"], test[-1]["t0"]],
                  note_sim="Mô phỏng điều kiện hoá theo fill đầu thật; horizon = t1 thật + 60 phút; chưa đóng -> mark-to-market; phí 3.5 bps/chiều; không funding."),
        inference=ev, grids=gr,
        iterations=iters, best_model=dict(name=best["model"], params=bp, rules_words=rules_words(bp), train=best["train"], test=best["test"],
                        test_single_fill=best["test_single_fill"], test_multi_fill=best["test_multi_fill"]),
        levelB=lvb, verdict=v, diagnostics=dict(oracle_exit_first_touch_train=oracle_exit(train), oracle_exit_first_touch_test=oracle_exit(test),
            note=("oracle_exit: dùng giá thoát THẬT làm mức; nếu bot đặt limit TP cố định thì thoát phải trùng lần chạm ĐẦU của mức đó -> tp thấp = KHÔNG phải limit TP mức giá "
                  "(giá đã chạm mức đó từ trước mà bot chưa thoát). Với sl thì chỉ gợi ý (thoát ở đáy mới luôn là lần chạm đầu, kể cả thoát tay).")),
        iteration_summary=iteration_summary(iters),
        pnl_check=dict(note="pnl OKX ~ gross - ~7bps*notional (phí); sim trừ 3.5bps/chiều"),
        cum_curve_train=match.cum_curve(rows_tr), cum_curve_test=match.cum_curve(rows_te),
        rows=rows_tr + rows_te, runtime_s=round(time.time() - t_start, 1))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, load.slug(name) + ".json")
    json.dump(res, open(p, "w"), ensure_ascii=False, default=_default)
    print("VERDICT:", v, "\nwritten", p, "runtime", res["runtime_s"], flush=True)


def iteration_summary(iters):
    ms = [it for it in iters if it["model"] != "M0_null"]
    null = next(it for it in iters if it["model"] == "M0_null")
    b_tr = max(ms, key=lambda it: it["train"]["score"]); b_te = max(ms, key=lambda it: it["test"]["score"])
    seq = [it["test"]["score"] for it in iters]
    return dict(null_train_score=null["train"]["score"], null_test_score=null["test"]["score"],
                best_by_train=dict(model=b_tr["model"], train=b_tr["train"]["score"], test=b_tr["test"]["score"]),
                best_by_test_info_only=dict(model=b_te["model"], test=b_te["test"]["score"]),
                test_score_sequence=[[it["model"], it["test"]["score"]] for it in iters],
                stop_rule=("dừng sau các vòng R1-R4 vì điểm TEST tốt nhất không cải thiện > 1 điểm %% so với M1 qua >=3 họ liên tiếp "
                           "(và chỉ hơn mô hình rỗng M0 ~%.1f điểm %%)." % (100 * (b_te["test"]["score"] - null["test"]["score"]))))


def rules_words(p):
    ref = {0: "fill gần nhất", 1: "fill đầu (thang lưới)", 2: "giá trung bình", 3: "THỜI GIAN (scale-in mỗi %d phút, bất kể giá)" % int(p.get("add_delay_min", 0))}[int(p["add_ref"])]
    s = [f"Vào lệnh đầu = fill đầu thật (điều kiện hoá).",
         f"Add khi giá đi ngược {p['step_pct']}%{' x ATR%(1h,14)' if p.get('use_scale') else ''} so với {ref}"
         f"{', bước nhân ' + str(p['step_growth']) + '/tầng' if p.get('step_growth', 1) != 1 else ''}; tối đa {int(p['max_layers'])} fill; "
         f"size add = {p['size_mult']} x notional {'fill đầu' if p.get('size_ref', 1) == 1 else 'fill trước'}."]
    if p.get("tp_pct"):
        s.append(f"Chốt lời {p['tp_pct']}% từ {'giá TB' if p.get('tp_ref', 0) == 0 else 'fill đầu'}, " + ("mỗi tầng có TP riêng từ giá fill của tầng." if p.get("tp_mode") == 1 else "đóng cả rổ."))
    if p.get("sl_pct"): s.append(f"Cắt lỗ {p['sl_pct']}% từ {'giá TB' if p.get('sl_ref', 0) == 0 else 'fill đầu'}, đóng cả rổ.")
    if p.get("trail_act"): s.append(f"Trailing: kích hoạt khi lãi {p['trail_act']}% từ avg, lùi {p['trail_dist']}% từ đỉnh.")
    if p.get("max_hold_bars"): s.append(f"Time-stop sau {int(p['max_hold_bars'])} phút.")
    return " ".join(s)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0], quick="--quick" in sys.argv)
