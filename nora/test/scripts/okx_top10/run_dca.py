"""Chạy harness DCA cho 1 bot với họ THOÁT/VÀO mới:
  run_limited.sh --no-lock -- test/scripts/okx_top10/run_dca.py "Auroraxwt" [--quick]
Ghi out/<slug>.json (cùng schema out/01pp.json + khoá alias idea/rules/params/metrics + exit_only/replay + representative).

Quy trình (fit CHỈ trên train = 60% basket đầu theo t0; headline = test 40% cuối; không chỉnh theo từng basket):
  0. infer: thống kê của pilot (run_bot.infer) + infer_dca (độ tròn giá, qty tier, đóng chung, giờ, first-touch add/exit, lift sự kiện).
  1. LEVEL A cơ khí (giá): họ bước %/ATR + TP/SL của pilot -> chọn theo điểm train.
  2. EXIT-ONLY (replay): giữ NGUYÊN các fill thật, chỉ thay luật thoát -> tách riêng "luật thoát" khỏi "luật add". Gồm TP %/ATR, sự kiện chỉ báo, giờ, sau-add.
     Baseline: TP rút ngẫu nhiên từ phân phối TP của train (cùng mã) -> mean/p95 của close_match.
  3. Mô hình đầy đủ: add (giá hoặc tín hiệu chỉ báo) + thoát chỉ báo (+ fallback TP/time-stop). Chọn theo train.
  4. LEVEL B: họ vào lệnh mới (đỉnh/đáy N giờ, mức tròn, lệch VWAP/EMA, sau biến động N-sigma, cổng giờ/phiên) fit F1 trên train, báo test + baseline.
"""
import itertools
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import families_dca as F
import load
import match
import run_bot as RB
import sim

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
G = {}
H = 3_600_000

HYP = {
    "Sugary-PoH-GasCap": ("Trader ETH (76% short, 50x) rải tầng DCA dày (bước trung vị ~0,23%) bằng lệnh LIMIT ở mức giá tròn với size theo bậc qty cố định (10/20/50/100/200), "
                          "chốt bằng limit ở mức giá tròn khi giá hồi (53% đóng nhiều tầng cùng lúc). Giả thuyết: lưới giá cố định theo % (hoặc mức tròn) + TP % từ avg, "
                          "hoặc thoát theo sự kiện chỉ báo (RSI/EMA/VWAP cắt lại) / mốc phiên."),
    "Scary-Merge-Llama": ("DCA long ETH/BTC 50x, chỉ ≤6 tầng, bước 0,5%, giữ trung vị 14h, thắng 81%. Giả thuyết: bước % cố định + TP % từ avg; hoặc thoát khi chỉ báo "
                          "(RSI/EMA/VWAP/MACD) đảo chiều; vào ở đáy N giờ / sau biến động mạnh."),
    "Auroraxwt": ("Lướt ~20 lệnh/ngày, 2 chiều, 20x, tập trung phiên Mỹ (13-15h UTC) trên cổ phiếu/perp vàng/BTC, giữ trung vị ~0,6h, 44% đóng cả rổ. "
                  "Giả thuyết: vào tại mức tạm quá mua/bán quanh mở cửa Mỹ, add theo bước % (hoặc ATR), thoát khi TP % hoặc chỉ báo đảo chiều; cắt lỗ muộn/thủ công."),
    "01pp": ("DCA hai chiều bắt hồi (pilot không tái tạo được: bước/TP không cố định theo % hay ATR; thoát muộn ~5h sau lần chạm đầu của mức giá thoát). "
             "Chạy lại với họ thoát mới: sự kiện chỉ báo trên nến đóng, giờ phiên/funding, thời gian kể từ add cuối."),
}


# ---------------------------------------------------------------- tiện ích
def _grid(spec):
    keys = list(spec)
    return [dict(zip(keys, v)) for v in itertools.product(*[spec[k] for k in keys])]


def _rows(baskets, params, horizon=60):
    return [match.basket_row(B, F.simulate2(B, params, horizon)) for B in baskets]


def _eval_train(params):
    return match.level_a(_rows(G["train"], params))


def sc_exit(m):
    """Điểm cho EXIT-ONLY (add = thật nên tr_layer_eq/add_match tầm thường): trung bình close_match 5/15/60."""
    return (m.get("close_match_5", 0) + m.get("close_match_15", 0) + m.get("close_match_60", 0)) / 300.0


def _fit(grid, pool, key=None):
    """Chọn tham số tốt nhất trên TRAIN. key(m)->điểm (mặc định match.score), hoà thì pnl_med_abs_err nhỏ hơn."""
    key = key or (lambda m: m.get("score", 0))
    res = pool.map(_eval_train, grid, chunksize=max(1, len(grid) // 80))
    best = max(range(len(grid)), key=lambda i: (key(res[i]), -res[i].get("pnl_med_abs_err_pp", 9e9)))
    return grid[best], res[best], res, len(grid)


def wilson(p_pct, n, z=1.96):
    """Khoảng tin cậy Wilson 95% (đơn vị %) cho tỉ lệ p_pct trên n mẫu."""
    if not n or p_pct is None: return None
    p = p_pct / 100.0; d = 1 + z * z / n; c = p + z * z / (2 * n); w = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(float(100 * (c - w) / d), 1), round(float(100 * (c + w) / d), 1)]


def _trim(m):
    t = RB._trim(m)
    t["score_exit"] = round(sc_exit(m), 4)
    n = m.get("n_simulated") or m.get("n_baskets")
    t["close_match_15_ci95"] = wilson(m.get("close_match_15"), n)
    t["tr_add_match_ci95"] = wilson(m.get("tr_add_match"), m.get("tr_n_actual_adds"))
    return t


def _uq(a, lo=1e-3):
    return sorted({round(float(x), 3) for x in a if x is not None and x > lo})


def _qs(a, ps):
    a = np.asarray(a, float)
    return [] if len(a) == 0 else list(np.percentile(a, ps))


# ---------------------------------------------------------------- lưới tham số có cơ sở (an toàn với mẫu nhỏ)
def derive(ev, train):
    q = lambda k: ev.get(k) or []
    sl = q("step_adverse_pct_q_last")
    steps = _uq(sl[:4] + ([sl[2] * 1.5, sl[2] * 2.5] if len(sl) > 2 else [])) or [0.3, 0.6, 1.0, 2.0]
    nt = q("n_tranches_per_basket_q")
    layers = sorted({2, 3, 4, 6} | ({int(max(2, nt[2])), int(max(2, nt[3]))} if len(nt) >= 4 else set()))
    layers = [x for x in layers if x <= 24]
    cp = q("close_pos_q") or [0.2, 0.4, 0.8, 1.5, 3.0]
    tps = _uq(cp + [cp[2] * 0.6])
    cn = q("close_neg_q")
    sls = _uq([abs(x) for x in cn[1:]]) or [1.0, 2.0, 4.0]
    r1 = q("add_over_first_notional_q") or [0.2, 0.3, 0.5, 0.8, 1.0]
    size = _uq([r1[1], r1[2], r1[3]]) or [0.3, 0.5, 1.0]
    sa = q("step_over_atr_q")
    atr_k = sorted(set(_uq(sa[1:4]) + ([round(sa[2] * 0.5, 3)] if len(sa) > 2 else []))) or [0.5, 1.0, 2.0]
    tp_atr = _uq(q("close_pos_over_atr_q")[1:]) or [0.3, 0.6, 1.2]
    sl_atr = _uq(q("close_neg_over_atr_q")[1:]) or [1.0, 2.0, 4.0]
    holdm = float(np.median([(B["t1"] - B["t0"]) / 6e4 for B in train]))
    return dict(steps=steps, layers=layers, tps=tps, sls=sls, size=size, atr_k=atr_k, tp_atr=tp_atr, sl_atr=sl_atr, hold_med_min=holdm,
                deep=bool(len(nt) >= 4 and nt[2] >= 4))


def exit_specs():
    """Danh sách (tên, spec) họ thoát chỉ báo/giờ. edge=1 = cạnh (cắt), edge=0 = trạng thái (đã ở phía kia thì thoát ngay khi đủ cổng lãi)."""
    S = []
    for tf in (1, 5, 15, 60):
        for L in (40, 50, 60, 70): S.append((f"rsi{L}_{tf}m", dict(kind="rsi", tf=tf, L=L)))
        for n in (9, 20, 50): S.append((f"ema{n}_{tf}m", dict(kind="ema", tf=tf, n=n)))
        S.append((f"vwap_{tf}m", dict(kind="vwap", tf=tf)))
        for n in (5, 10, 20): S.append((f"nbar{n}_{tf}m", dict(kind="nbar", tf=tf, n=n)))
    for tf in (5, 15, 60):
        S.append((f"bbmid_sma20_{tf}m", dict(kind="sma", tf=tf, n=20)))
        S.append((f"bbext_{tf}m", dict(kind="bbext", tf=tf)))
        S.append((f"macd_{tf}m", dict(kind="macd", tf=tf)))
    S += [("time_funding", dict(kind="time", times=(0, 480, 960))), ("time_us_open", dict(kind="time", times=(810,))),
          ("time_us_close", dict(kind="time", times=(1200,))), ("time_us_open_close", dict(kind="time", times=(810, 1200))),
          ("time_all_marks", dict(kind="time", times=(0, 480, 810, 960, 1200)))]
    return S


# ---------------------------------------------------------------- baseline: TP ngẫu nhiên từ phân phối train
def tp_pool(train):
    by = {}
    allv = []
    for B in train:
        s = 1 if B["side"] == "long" else -1
        for c in B["closes"]:
            f = B["fills"][c["fill"]]; r = (c["px"] / f["px"] - 1) * s * 100
            if r > 0.02:
                by.setdefault(B["sym"], []).append(r); allv.append(r)
    return by, allv


def shuffled_tp_baseline(train, test, reps=20, seed=0):
    by, allv = tp_pool(train)
    rng = np.random.default_rng(seed); out = []
    for _ in range(reps):
        rows = []
        for B in test:
            pool = by.get(B["sym"]) if len(by.get(B["sym"], [])) >= 8 else allv
            p = dict(replay=1, max_layers=40, tp_pct=float(rng.choice(pool)), tp_mode=1)
            rows.append(match.basket_row(B, F.simulate2(B, p)))
        out.append(match.level_a(rows))
    f = lambda k: [m.get(k) or 0 for m in out]
    return {k: dict(mean=round(float(np.mean(f(k))), 2), p95=round(float(np.percentile(f(k), 95)), 2)) for k in ("close_match_5", "close_match_15", "close_match_60", "pnl_corr", "pnl_sign_agree")} | dict(reps=reps)


# ---------------------------------------------------------------- Level B
def level_b(baskets_all, split_t, bot_name, fast=False):
    act_tr, act_te = {}, {}
    for B in baskets_all:
        (act_tr if B["t0"] < split_t else act_te).setdefault((B["sym"], B["side"]), []).append(B["t0"])
    act_tr = {k: np.array(sorted(v), np.int64) for k, v in act_tr.items()}
    act_te = {k: np.array(sorted(v), np.int64) for k, v in act_te.items()}
    syms = sorted({B["sym"] for B in baskets_all})
    t_lo = min(B["t0"] for B in baskets_all); t_hi = max(B["t0"] for B in baskets_all) + 15 * 60_000
    t_tr = np.array([B["t0"] for B in baskets_all if B["t0"] < split_t])
    hh = np.bincount(((t_tr // H + 7) % 24).astype(int), minlength=24).astype(float) + 0.5; hh /= hh.sum()
    hu = np.bincount(((t_tr // H) % 24).astype(int), minlength=24).astype(float)
    top = int(np.argmax(np.convolve(np.r_[hu, hu[:5]], np.ones(6), "valid")[:24]))
    gate = [(top + i) % 24 for i in range(6)]   # 6 giờ UTC dày nhất trên TRAIN
    sigcache = {}

    def sigs(rule, lo, hi):
        out = {}
        for s in syms:
            r = F.entry_signals(s, rule)
            if r is None: continue
            for side, t in zip(("long", "short"), r):
                t = t[(t >= lo) & (t <= hi)]
                if len(t): out[(s, side)] = t
        return out

    rules = []
    for N in (1, 4, 12, 24):
        for mode in ("fade", "break"):
            for h in (None, gate):
                for c in (1, 6): rules.append(dict(kind="hl", N=N, mode=mode, hours=h, cool_h=c))
    for rel in (0.5, 1.0, 2.0):
        for mode in ("fade", "break"):
            for h in (None, gate):
                for c in (1, 6): rules.append(dict(kind="round", rel=rel, mode=mode, hours=h, cool_h=c))
    for feat in ("vwap_z", "ema_z", "ret1h", "ret4h"):
        for thr in (0.5, 1.0, 1.5, 2.0, 2.5):
            for mode in ("contra", "mom"):
                for h in (None, gate):
                    for c in (1, 6): rules.append(dict(kind="z", feat=feat, thr=thr, mode=mode, hours=h, cool_h=c))
    for tm, nm in (((810,), "us_open"), ((825,), "us_open+15"), ((840,), "us_open+30"), ((0, 480, 960), "funding"), ((1200,), "us_close")):
        for mode in ("both", "contra", "mom"):
            rules.append(dict(kind="session", tmins=tm, mode=mode, name=nm, hours=None, cool_h=1))
    if fast: rules = rules[::6]
    fit = []
    for rule in rules:
        m = match.level_b(act_tr, sigs(rule, t_lo, split_t), t_lo, split_t, reps=12, seed=1, hour_hist=hh)
        fit.append((match.f1_excess(m), rule, m))
    best_by = {}
    for sc, rule, m in fit:
        k = (rule["kind"], rule.get("feat") or rule.get("name") or rule.get("mode"), rule["mode"])
        if k not in best_by or sc > best_by[k][0]: best_by[k] = (sc, rule, m)
    allbest = max(fit, key=lambda x: x[0])
    res = dict(gate_hours_utc=gate, n_rules=len(rules), train_window=[t_lo, split_t], test_window=[split_t, t_hi], per_family=[])
    reps = 60 if fast else 200
    for k, (sc, rule, m) in sorted(best_by.items(), key=lambda kv: -kv[1][0])[:14]:
        tr = match.level_b(act_tr, sigs(rule, t_lo, split_t), t_lo, split_t, reps=reps, seed=2, hour_hist=hh)
        te = match.level_b(act_te, sigs(rule, split_t, t_hi), split_t, t_hi, reps=reps, seed=3, hour_hist=hh)
        res["per_family"].append(dict(family=f"{k[0]}:{k[1]}:{k[2]}", rule=rule, train_f1_excess=round(sc, 4), train=tr, test=te))
    res["best_rule_by_train"] = [d for d in res["per_family"] if d["rule"] == allbest[1]][0]
    res["note"] = ("Luật chọn theo F1(+-15p) vượt baseline trên TRAIN; chỉ 'khớp' khi TEST recall VÀ precision (+-15p) > p95 của cả 2 baseline (đều theo thời gian / theo giờ VN) "
                   "và lift>=3 và recall15>=30%. Cổng giờ = 6 giờ UTC dày nhất của train; hours=None = không cổng.")
    return res


# ---------------------------------------------------------------- mô tả luật bằng lời
def rules_words2(p):
    s = []
    if p.get("replay"):
        s.append("Add = các fill thật (replay).")
    elif p.get("ak"):
        sp = p.get("aspec") or {}
        s.append(f"Add khi tín hiệu {sp.get('kind')} (tf {sp.get('tf')}m, {sp}) xuất hiện lúc giá đã đi ngược >= {p.get('amin')}% so với fill gần nhất (nghỉ >= {p.get('acool')} phút); "
                 f"tối đa {int(p['max_layers'])} fill, size add = {p.get('size_mult')} x notional {'fill đầu' if p.get('size_ref', 1) == 1 else 'fill trước'}.")
    else:
        s.append(RB.rules_words(p).split(" Chốt")[0].split(" Cắt")[0].split(" Trailing")[0].split(" Time-stop")[0])
    if p.get("tp_pct"):
        s.append(f"TP {p['tp_pct']}%{' x ATR%(1h)' if p.get('tp_use_scale') else ''} từ {'giá TB' if p.get('tp_ref', 0) == 0 else 'fill đầu'}, "
                 + ("từng tầng riêng." if p.get("tp_mode") == 1 else "đóng cả rổ."))
    if p.get("sl_pct"): s.append(f"SL {p['sl_pct']}%{' x ATR' if p.get('sl_use_scale') else ''} từ {'giá TB' if p.get('sl_ref', 0) == 0 else 'fill đầu'}.")
    if p.get("xk") and p.get("xspec"):
        s.append(f"Thoát khi sự kiện {p['xspec']} trên nến đóng (khớp open nến sau), chỉ khi lãi >= {p.get('xprof', 0)}%{' x ATR%(1h)' if p.get('xprof_scale') else ''} "
                 f"{'từ avg cả rổ' if p.get('xscope', 0) == 0 else 'của TỪNG tầng (đóng riêng tầng đủ lãi)'}; nghỉ >= {p.get('xsince', 0)} phút sau add cuối.")
    if p.get("xaa"): s.append(f"Đóng {p['xaa']} phút sau add cuối nếu lãi >= {p.get('xprof', 0)}%.")
    if p.get("max_hold_bars"): s.append(f"Time-stop {int(p['max_hold_bars'])} phút.")
    if p.get("trail_act"): s.append(f"Trailing kích hoạt {p['trail_act']}% lùi {p['trail_dist']}%.")
    return " ".join(s)


def cut(p):
    """Tham số gọn cho JSON (bỏ giá trị mặc định)."""
    d = dict(sim.PARAM_DEFAULT); d.update(F.XDEFAULT)
    return {k: v for k, v in p.items() if k not in d or d[k] != v}


# ---------------------------------------------------------------- verdict
def verdict2(test_m, lvb, exit_best, shuf, null_te):
    cm = test_m.get("close_match_15") or 0; am = test_m.get("add_match") or 0; corr = test_m.get("pnl_corr") or 0
    sign = test_m.get("pnl_sign_agree") or 0; leq = test_m.get("layer_eq") or 0
    ci = test_m.get("close_match_15_ci95") or [0, 100]
    ci5 = F_wilson(test_m.get("close_match_5"), test_m.get("n_simulated")) or [0, 100]
    # CI95 dưới của thoát +-5p và +-15p phải vượt cả p95 của TP ngẫu nhiên lẫn mốc rỗng (time-stop) trên test
    beats_null = (ci5[0] > max(shuf["close_match_5"]["p95"], null_te.get("close_match_5") or 0)
                  and ci[0] > max(shuf["close_match_15"]["p95"], null_te.get("close_match_15") or 0))
    weak = cm >= 25 or am >= 25 or (corr >= 0.5 and sign >= 70)
    if cm >= 60 and am >= 50 and corr >= 0.7 and beats_null: lab = "khớp tốt"
    elif weak and beats_null: lab = "khớp một phần"
    elif weak: lab = "yếu / chưa phân biệt được khỏi ngẫu nhiên (CI95 chạm baseline)"
    else: lab = "không tái tạo được"
    why = (f"[n_test={test_m.get('n_simulated')} basket, CI95 thoát15 {test_m.get('close_match_15_ci95')}] TEST (40% basket cuối, điều kiện hoá theo fill đầu thật; mô hình cơ khí đầy đủ chọn theo train): thoát +-15p {cm:.1f}% (+-60p {test_m.get('close_match_60')}%), "
           f"add khớp giờ+giá {am:.1f}% (chỉ giờ {test_m.get('add_time_match')}%), số tầng bằng {leq:.1f}%, dấu PnL cùng {sign:.1f}%, corr lợi suất {corr}. ")
    why += f"Mốc rỗng (1 fill + time-stop) trên test: thoát +-5p {null_te.get('close_match_5')}% / +-15p {null_te.get('close_match_15')}%; TP ngẫu nhiên +-5p mean {shuf['close_match_5']['mean']}% (p95 {shuf['close_match_5']['p95']}%). "
    if exit_best:
        why += (f"Thoát RIÊNG (replay fill thật): tốt nhất {exit_best['model']} thoát +-15p {exit_best['test'].get('close_match_15')}% (+-5p {exit_best['test'].get('close_match_5')}%) "
                f"vs TP ngẫu nhiên theo phân phối train mean {shuf['close_match_15']['mean']}% / p95 {shuf['close_match_15']['p95']}%. ")
    b = lvb["best_rule_by_train"]["test"]
    why += (f"Level B (luật vào tốt nhất trên train, test): recall15 {b['recall_15']}% / precision15 {b['precision_15']}% vs baseline giờ-khớp {b.get('rand_hour_recall_15_mean')}% / "
            f"{b.get('rand_hour_precision_15_mean')}% (p95 {b.get('rand_hour_recall_15_p95')}% / {b.get('rand_hour_precision_15_p95')}%) -> {b['strength']}.")
    return dict(label=lab, why=why)


def F_wilson(p, n):
    return wilson(p, n)


def pick_rep(rows):
    """3-5 basket đại diện trong test: tốt nhất / trung vị / tệ nhất theo |lệch giờ đóng|, lỗ thật lớn nhất, lãi thật lớn nhất (ưu tiên >=2 fill)."""
    te = [r for r in rows if r.get("split") == "test" and "sim_ret" in r]
    if not te: return []
    multi = [r for r in te if r["n_act"] >= 2] or te
    dt = lambda r: abs(r["sim_close"]["t"] - r["act_close"]["t"]) if r["sim_closed"] else 1e18
    s = sorted(multi, key=dt)
    sel = [("khớp thoát tốt nhất", s[0]), ("trung vị", s[len(s) // 2]), ("lệch nhất", s[-1])]
    sel.append(("lỗ thật lớn nhất", min(te, key=lambda r: r["act_pnl"]))); sel.append(("lãi thật lớn nhất", max(te, key=lambda r: r["act_pnl"])))
    seen, out = set(), []
    for tag, r in sel:
        if r["id"] in seen: continue
        seen.add(r["id"]); out.append(dict(tag=tag, id=r["id"]))
    return out


# ---------------------------------------------------------------- chính
def run(name, quick=False):
    t_start = time.time()
    bot = load.get_bot(name); summ = load.load_summary()["bots"][name]
    allb = load.build_baskets(bot); chk = load.check_bk(bot, allb); cov = load.coverage(bot)
    baskets = [B for B in allb if load.candle_arrays(B["sym"]) is not None and B["t0"] >= load.candle_arrays(B["sym"])["t"][0]]
    n_tr = int(len(baskets) * 0.6); train, test = baskets[:n_tr], baskets[n_tr:]; split_t = test[0]["t0"]
    G["train"] = train
    ev = RB.infer(train, bot); ev2 = F.infer_dca(train)
    gr = derive(ev, train)
    print("grids:", gr, flush=True)
    F.simulate2(train[0], dict(replay=1, xk=1, xspec=dict(kind="rsi", tf=15, L=50)))  # biên dịch numba trước khi fork
    ncpu = min(10, len(os.sched_getaffinity(0)))
    pool = mp.get_context("fork").Pool(ncpu)
    iters = []; allres = []   # allres: (name, params, train_metrics) của mọi lưới cơ khí

    def record(nm, note, p, tr, n, mode="mechanical", t0=None, key=None):
        te = match.level_a(_rows(test, p))
        it = dict(model=nm, note=note, mode=mode, params=cut(p), n_grid=n, train=_trim(tr), test=_trim(te), secs=round(time.time() - (t0 or time.time()), 1))
        iters.append(it)
        print(f"{nm}[{mode}]: n={n} train score {tr.get('score')} / exit {sc_exit(tr):.3f} | TEST close5 {te.get('close_match_5')} c15 {te.get('close_match_15')} c60 {te.get('close_match_60')} "
              f"add {te.get('add_match')} leq {te.get('layer_eq')} corr {te.get('pnl_corr')} | {cut(p)}", flush=True)
        return it

    def stage(nm, note, grid, mode="mechanical", key=None):
        if quick: grid = grid[::max(1, len(grid) // 40)]
        t0 = time.time()
        p, tr, res, n = _fit(grid, pool, key)
        if mode == "mechanical":
            allres.extend(zip(grid, res))
        it = record(nm, note, p, tr, n, mode, t0)
        return p, tr, res, grid

    sz = gr["size"][len(gr["size"]) // 2]
    base = dict(add_ref=[0], step_pct=gr["steps"], step_growth=[1.0], max_layers=gr["layers"], size_mult=[sz], size_ref=[1], tp_pct=gr["tps"], tp_ref=[0], tp_mode=[0], sl_pct=[0.0])
    # ---- 1. mốc rỗng + họ giá của pilot
    stage("M0_null", "Mốc rỗng: 1 fill, không add/TP, time-stop = bội trung vị thời gian giữ của train.",
          _grid(dict(add_ref=[0], step_pct=[1.0], max_layers=[1], max_hold_bars=[max(2, int(gr["hold_med_min"] * k)) for k in (0.25, 0.5, 1, 2, 4)])))
    fams = [("P1_step_last_TP_avg", "bước % cố định từ fill gần nhất + TP % từ giá TB (đóng cả rổ).", base),
            ("P2_ladder_first", "thang lưới từ fill ĐẦU (mức k = giá đầu -/+ k x bước), TP từ avg.", {**base, "add_ref": [1]}),
            ("P3_step_avg", "bước từ giá TB, TP từ avg.", {**base, "add_ref": [2]}),
            ("P4_per_layer_TP", "mỗi tầng TP riêng từ giá fill của nó (lưới đóng từng tầng).", {**base, "tp_mode": [1]}),
            ("P5_ATR_step_TP_ATR", "bước = k x ATR%(1h) và TP = m x ATR%(1h) (co giãn theo biến động).", {**base, "step_pct": gr["atr_k"], "use_scale": [1], "tp_pct": gr["tp_atr"], "tp_use_scale": [1]}),
            ("P6_ATR_step_per_layer_TP", "bước ATR + TP % riêng từng tầng.", {**base, "step_pct": gr["atr_k"], "use_scale": [1], "tp_mode": [1]})]
    if gr["deep"]:
        forced = {**base, "max_layers": [6, 12]}
        fams += [("F1_forced_last", "ÉP >=6 tầng: bước từ fill gần nhất.", {**forced, "add_ref": [0]}), ("F2_forced_first", "ÉP >=6 tầng: thang lưới từ fill đầu.", {**forced, "add_ref": [1]}),
                 ("F5_forced_per_layer_TP", "ÉP >=6 tầng: mỗi tầng TP riêng.", {**forced, "tp_mode": [1]})]
    for nm, note, sp in fams:
        stage(nm, note, _grid(sp))
    cand = [it for it in iters if it["model"] != "M0_null"]
    bi = max(cand, key=lambda it: it["train"]["score"]); bp0 = {**{k: v for k, v in sim.PARAM_DEFAULT.items()}, **bi["params"]}
    one = lambda d: {k: [v] for k, v in d.items()}
    stage("R1_best+SL", "mô hình giá tốt nhất theo train + stop-loss % / ATR.", _grid({**one(bp0), "sl_pct": [0.0] + gr["sls"]}) + _grid({**one(bp0), "sl_pct": gr["sl_atr"], "sl_use_scale": [1]}))
    stage("R2_best+growth_size", "thêm bước tăng dần và size add khác.", _grid({**one(bp0), "step_growth": [1.0, 1.25, 1.5], "size_mult": gr["size"], "size_ref": [0, 1]}))
    stage("R3_best+timestop_trail", "thêm time-stop và trailing.", _grid({**one(bp0), "max_hold_bars": [0] + [max(2, int(gr["hold_med_min"] * k)) for k in (1, 2, 4)],
                                                                        "trail_act": [0.0] + gr["tps"][:3], "trail_dist": [0.3, 0.6]}))
    # ---- 2. EXIT-ONLY (replay fill thật)
    rb = dict(replay=1, max_layers=40, size_mult=1.0)
    ex_best = []
    p, tr, res, grid = stage("X0_replay_TP_pct", "REPLAY: chỉ thay luật thoát. TP % từ avg cả rổ (đóng cả rổ).", _grid({**{k: [v] for k, v in rb.items()}, "tp_pct": gr["tps"] + [0.1, 0.2, 0.3, 0.5, 0.8]}), "replay", sc_exit)
    ex_best.append(("TP_pct_avg", p, tr))
    p, tr, res, grid = stage("X0b_replay_TP_layer", "REPLAY: TP % riêng từng tầng.", _grid({**{k: [v] for k, v in rb.items()}, "tp_pct": gr["tps"] + [0.1, 0.2, 0.3, 0.5, 0.8], "tp_mode": [1]}), "replay", sc_exit)
    ex_best.append(("TP_pct_layer", p, tr))
    p, tr, res, grid = stage("X0c_replay_TP_ATR", "REPLAY: TP = m x ATR%(1h) từ avg.", _grid({**{k: [v] for k, v in rb.items()}, "tp_pct": gr["tp_atr"] + [0.15, 0.25, 0.4, 0.6], "tp_use_scale": [1]}), "replay", sc_exit)
    ex_best.append(("TP_ATR", p, tr))
    # sự kiện chỉ báo: lưới cổng lãi
    gates = [(0.0, 0), (0.1, 0), (0.25, 0), (0.5, 0), (0.2, 1), (0.5, 1)]   # (ngưỡng, xprof_scale)
    allx = []
    kinds = {}
    for nm, sp in exit_specs():
        kinds.setdefault(sp["kind"], []).append((nm, sp))
    for kind, lst in kinds.items():
        grid = []
        for nm, sp in lst:
            for edge in ((1,) if kind in ("time", "bbext", "macd", "nbar") else (0, 1)):
                for g, sc in gates:
                    for scope in (0, 1):
                        grid.append(dict(rb, xk=1, xspec=dict(sp, edge=edge, nm=nm), xprof=g, xprof_scale=sc, xscope=scope))
        p, tr, res, grid = stage(f"X1_replay_{kind}", f"REPLAY: thoát theo sự kiện {kind} trên nến đóng (tf/tham số/cạnh/cổng lãi/phạm vi lưới chọn theo train).", grid, "replay", sc_exit)
        ex_best.append((kind, p, tr)); allx.extend(zip(grid, res))
    p, tr, res, grid = stage("X2_replay_after_last_add", "REPLAY: đóng cả rổ N phút sau add cuối nếu lãi >= cổng.", _grid({**{k: [v] for k, v in rb.items()}, "xaa": [5, 15, 30, 60, 120, 240, 480],
                                                                                                                       "xprof": [0.0, 0.1, 0.25, 0.5]}), "replay", sc_exit)
    ex_best.append(("after_last_add", p, tr))
    topx = sorted(allx, key=lambda gr_: -sc_exit(gr_[1]))
    # lấy top-3 cấu hình sự kiện khác nhau (khác kind) theo train
    seen, top3 = set(), []
    for g_, m_ in topx:
        k_ = g_["xspec"]["kind"]
        if k_ in seen: continue
        seen.add(k_); top3.append(g_)
        if len(top3) == 3: break
    # ---- 3. mô hình đầy đủ: add cơ khí + thoát sự kiện
    adds = sorted(allres, key=lambda gm: -gm[1].get("score", 0))
    tops, seen = [], set()
    for g_, m_ in adds:
        k_ = (g_.get("add_ref"), g_.get("step_pct"), g_.get("max_layers"), g_.get("use_scale"), g_.get("tp_mode"))
        if k_ in seen: continue
        seen.add(k_); tops.append(g_)
        if len(tops) == 4: break
    comb = []
    for a_ in tops:
        a2 = {k: v for k, v in a_.items() if k not in ("tp_pct", "tp_ref", "tp_mode", "tp_use_scale")}
        for x_ in top3:
            xx = {k: x_[k] for k in ("xk", "xspec", "xprof", "xprof_scale", "xscope")}
            comb.append({**a2, **xx})
            for tpv in gr["tps"][:3]: comb.append({**a2, **xx, "tp_pct": tpv, "tp_mode": 0})
            for hm in (2, 6): comb.append({**a2, **xx, "max_hold_bars": max(2, int(gr["hold_med_min"] * hm))})
    stage("C1_price_add+indicator_exit", "add cơ khí theo giá (tốt nhất train) + thoát chỉ báo (top-3 họ theo replay) +/- TP fallback / time-stop.", comb)
    cb = iters[-1]; cbp = {**sim.PARAM_DEFAULT, **F.XDEFAULT, **cb["params"]}
    # tinh chỉnh thoát: xsince, xaa trên mô hình C1
    stage("C2_refine_since_add", "C1 + cấm thoát sớm (xsince phút từ add cuối) / đóng sau add cuối (xaa).",
          _grid({**one(cbp), "xsince": [0, 5, 15, 30, 60]}) + _grid({**one(cbp), "xaa": [30, 60, 120, 240]}))
    c2 = iters[-1]; cbp = {**sim.PARAM_DEFAULT, **F.XDEFAULT, **c2["params"]}
    # add theo tín hiệu chỉ báo
    ak = []
    for nm, sp in [(n_, s_) for n_, s_ in exit_specs() if s_["kind"] in ("rsi", "bbext", "nbar", "ema") and s_["tf"] in (5, 15, 60)]:
        if sp["kind"] == "rsi" and sp["L"] not in (60, 70): continue
        if sp["kind"] in ("ema", "nbar") and sp.get("n") not in (20, 50, 10, 5): continue
        for amin in (0.1, 0.4):
            for ml in (3, 8):
                ak.append({**one({**cbp, "add_ref": 0, "max_layers": ml, "size_mult": sz}), "ak": [1], "aspec": [dict(sp, edge=1)], "amin": [amin], "acool": [15]})
    akg = [d for g_ in ak for d in _grid(g_)]
    stage("A1_signal_add+indicator_exit", "add theo tín hiệu chỉ báo (quá bán/mua, phá cực trị) khi giá đã đi ngược >= amin% + thoát chỉ báo của C2.", akg)
    pool.close()
    # ---- chọn mô hình cuối theo TRAIN (loại replay)
    mech = [it for it in iters if it["mode"] == "mechanical" and it["model"] != "M0_null"]
    best = max(mech, key=lambda it: it["train"]["score"])
    bp = {**sim.PARAM_DEFAULT, **F.XDEFAULT, **best["params"]}
    for k in ("xspec", "aspec"):
        if k in best["params"]: bp[k] = best["params"][k]
    rows_tr = _rows(train, bp); rows_te = _rows(test, bp)
    for r in rows_tr: r["split"] = "train"
    for r in rows_te: r["split"] = "test"
    rows = rows_tr + rows_te
    best_x = max([it for it in iters if it["mode"] == "replay"], key=lambda it: it["train"]["score_exit"])
    xp = {**sim.PARAM_DEFAULT, **F.XDEFAULT, **best_x["params"]}
    for k in ("xspec",):
        if k in best_x["params"]: xp[k] = best_x["params"][k]
    shuf = shuffled_tp_baseline(train, test, reps=8 if quick else 20)
    print("shuffled TP baseline:", shuf, flush=True)
    # replay tốt nhất: hàng gọn cho đồ thị (giờ đóng thật vs sim)
    rx = _rows(test, xp)
    exit_rows = [dict(id=r["id"], sym=r["sym"], act_close=r["act_close"], sim_close=r.get("sim_close"), act_ret=r["act_ret"], sim_ret=r.get("sim_ret"), sim_closed=r.get("sim_closed")) for r in rx]
    best["test_single_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] == 1]))
    best["test_multi_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] > 1]))
    lvb = level_b(baskets, split_t, name, fast=quick)
    null = next(it for it in iters if it["model"] == "M0_null")
    v = verdict2(best["test"], lvb, best_x, shuf, null["test"])
    seq = [[it["model"], it["mode"], it["train"]["score"], it["test"]["score"], it["test"].get("close_match_15")] for it in iters]
    mech_seq = [it["test"]["score"] for it in mech]
    iter_sum = dict(null=dict(train=null["train"]["score"], test=null["test"]["score"]),
                    best_by_train=dict(model=best["model"], train=best["train"]["score"], test=best["test"]["score"]),
                    best_replay_by_train=dict(model=best_x["model"], train_exit=best_x["train"]["score_exit"], test_exit=best_x["test"]["score_exit"]),
                    sequence=seq,
                    stop_rule=("dừng khi điểm TEST cơ khí không tăng > 1 điểm% qua >=3 họ liên tiếp (P6 -> R3 -> C1 -> C2 -> A1); điểm cơ khí tốt nhất test-sequence = "
                               + str([round(x, 3) for x in mech_seq])))
    res = dict(
        bot=name, rank=bot["rank"], style=summ["style"], styleKey=summ["styleKey"], idea_from_summary=dict(how=summ["how"], edge=summ["edge"], risk=summ["risk"]),
        hypothesis=HYP.get(name, summ["how"] + " " + summ["edge"]), idea=HYP.get(name, summ["how"] + " " + summ["edge"]),
        data=dict(n_subpositions=len(bot["trades"]), n_baskets=len(allb), n_baskets_simulated=len(baskets), basket_check=chk, symbols_missing_candles=[r["sym"] for r in cov if not r["file"]],
                  coverage=cov, n_train=len(train), n_test=len(test), split_t=split_t, train_period=[train[0]["t0"], train[-1]["t0"]], test_period=[test[0]["t0"], test[-1]["t0"]],
                  note_sim="Điều kiện hoá theo fill đầu thật; horizon = t1 thật + 60 phút; chưa đóng -> tính không khớp (mark-to-market cho PnL); phí 3.5 bps/chiều; không funding. "
                          "Sự kiện chỉ báo trên nến đóng, khớp open nến 1m kế tiếp."),
        inference=ev, inference_dca=ev2, grids=gr, iterations=iters,
        best_model=dict(name=best["model"], params=cut(bp), rules_words=rules_words2(bp), train=best["train"], test=best["test"], test_single_fill=best["test_single_fill"],
                        test_multi_fill=best["test_multi_fill"]),
        rules=rules_words2(bp), params=cut(bp), metrics=dict(train=dict(levelA=best["train"]), test=dict(levelA=best["test"], levelB=lvb["best_rule_by_train"]["test"])),
        exit_only=dict(best=dict(model=best_x["model"], params=cut(xp), rules_words=rules_words2(xp), train=best_x["train"], test=best_x["test"]),
                       per_family=[dict(model=it["model"], params=it["params"], train=it["train"], test=it["test"]) for it in iters if it["mode"] == "replay"],
                       shuffled_tp_baseline_test=shuf, rows_test=exit_rows,
                       note="REPLAY giữ nguyên các fill thật; chỉ luật thoát được mô phỏng. Baseline = TP % rút ngẫu nhiên từ phân phối TP của train (cùng mã), áp lên cùng basket test."),
        levelB=lvb, verdict=v,
        diagnostics=dict(oracle_exit_first_touch_train=RB.oracle_exit(train), oracle_exit_first_touch_test=RB.oracle_exit(test),
                         note="oracle_exit: dùng giá thoát THẬT làm mức; trễ lớn sau lần chạm đầu = không phải limit TP mức giá cố định. Xem thêm inference_dca.exit_first_touch/add_first_touch."),
        iteration_summary=iter_sum, pnl_check=dict(note="pnl OKX ~ gross - ~7bps*notional (phí); sim trừ 3.5bps/chiều"),
        cum_curve_train=match.cum_curve(rows_tr), cum_curve_test=match.cum_curve(rows_te), representative=pick_rep(rows), rows=rows, runtime_s=round(time.time() - t_start, 1))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, load.slug(name) + ".json")
    json.dump(res, open(p, "w"), ensure_ascii=False, default=RB._default)
    print("VERDICT:", v, "\nwritten", p, "runtime", res["runtime_s"], flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0], quick="--quick" in sys.argv)
