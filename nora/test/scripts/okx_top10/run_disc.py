"""Phase 2 — chạy khám phá cơ chế cho 1 bot: panel -> mô hình -> sim có điều kiện (Level A/B) -> vòng lặp -> Level S (free-running).
Dùng:  run_limited.sh -- run_disc.py "Auroraxwt" [--quick] [--stages exit,add,entry,levelS]
Kết quả: out/disc_<slug>.json. Mọi lựa chọn (ngưỡng, cấu hình, k) chọn trên TRAIN (điểm out-of-fold); test chỉ để báo cáo.
"""
import json, os, sys, time, copy, argparse
os.environ.setdefault("OMP_NUM_THREADS", "6")      # máy dùng chung tải cao: quá nhiều luồng OpenMP làm GBM chậm 50 lần
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load, match
import disc_panels as DP
import disc_models as DM
import disc_sim as DS
import disc_stats as ST

MIN = 60_000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
LMAP = {"gbm": DM.GBM, "tree2": lambda: DM.Tree(2), "tree3": lambda: DM.Tree(3), "tree4": lambda: DM.Tree(4), "single": DM.Single, "pair": DM.Pair}
ALL_L = ["gbm", "tree2", "tree3", "tree4", "single", "pair"]
MAIN_L = ["gbm", "tree3", "pair"]
CLS_GROUP = {0: "stock", 1: "other", 2: "major", 3: "other"}
BASE_GROUPS = {"pos", "price", "cal"}
SMALL = 40


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def compact(m):
    keys = ["n_baskets", "n_simulated", "close_match_5", "close_match_15", "close_match_60", "sim_closed_pct", "pnl_corr", "pnl_corr_usdt", "pnl_sign_agree",
            "add_match", "add_time_match", "tr_add_match", "tr_add_time_match", "layer_eq", "tr_layer_eq", "close_px_err_bps_med", "act_pnl_sum", "sim_pnl_sum",
            "act_win_pct", "sim_win_pct", "n_sim_layers_mean", "n_act_layers_mean"]
    return {k: m.get(k) for k in keys if k in m}


# ======================================================================= thiết lập
class Ctx:
    def __init__(self, name, lag=1, quick=False):
        self.name = name; self.lag = lag; self.quick = quick
        self.P = DP.build_panels(name, lag=lag)
        self.baskets = self.P["baskets"]; self.bot = self.P["bot"]; self.split_t = self.P["split_t"]
        n_tr = int(len(self.baskets) * 0.6)
        self.train = self.baskets[:n_tr]; self.test = self.baskets[n_tr:]
        self.loo = len(self.baskets) < SMALL
        if self.loo:
            self.train = list(self.baskets); self.test = list(self.baskets); self.split_t = 1 << 62
        self.t0 = {b["id"]: b["t0"] for b in self.P["ctx"].baskets}
        # basket mở-đóng trong cùng 1 phút (scalp < 1m) không có hàng quyết định ở độ phân giải 1m -> bỏ khỏi đánh giá thoát/add (mọi phương pháp, kể cả baseline)
        have = set(self.P["exit"][0].loc[self.P["exit"][0].after_last == 1, "bid"].unique())
        self.train_all, self.test_all = self.train, self.test
        self.n_scalp = sum(1 for B in self.baskets if B["id"] not in have)
        self.train = [B for B in self.train if B["id"] in have]; self.test = [B for B in self.test if B["id"] in have]
        self.train_ids = {B["id"] for B in self.train}; self.test_ids = {B["id"] for B in self.test}


# ======================================================================= EXIT
def _cls_groups(meta):
    return np.array([CLS_GROUP[DP.sym_class(s)] for s in meta.sym.values]) if False else meta.sym.map(lambda s: CLS_GROUP[DP.sym_class(s)]).values


def exit_stage(C, cfg, full_report=True):
    """Một cấu hình exit: huấn luyện, chọn ngưỡng trên train (OOF), đo Level A train/test. Trả dict + điểm cho sim."""
    meta, f = C.P["exit"]
    cols = DM.select_cols(f.columns, cfg["groups"])
    tgt = cfg.get("target", "first")
    y = (meta.exit_y if tgt == "first" else meta.exit_last_y).to_numpy(float)
    valid = ((meta.after_last == 1) & ((meta.post == 0) if tgt == "first" else (meta.pre_last == 1))).to_numpy()
    w = np.ones(len(meta))
    is_train = meta.bid.map(lambda b: b in C.train_ids).to_numpy() if not C.loo else np.ones(len(meta), bool)
    names = ALL_L if full_report else MAIN_L
    learners = [LMAP[n] for n in names]
    t = time.time()
    sc, fin, ex = DM.run_learners(f, cols, y, w, valid, meta.bid.values, is_train, C.loo, learners)
    rep = DM.panel_report(f, cols, y, w, valid, is_train, sc, fin, C.loo)
    cls_scores = None; out_cls = None
    if cfg.get("cls_models"):
        cg = _cls_groups(meta)
        cls_scores = {n: sc[n].copy() for n in MAIN_L}; cls_fin = {}
        for g in ("stock", "major", "other"):
            msk = cg == g
            ntr = int((valid & is_train & msk & (y == 1)).sum()) if not C.loo else int((valid & msk & (y == 1)).sum())
            if ntr < 40:
                continue
            fm = valid & msk
            s2, f2, _ = DM.run_learners(f, cols, y, w, fm, meta.bid.values, is_train & msk if not C.loo else msk, C.loo, [LMAP[n] for n in MAIN_L])
            for n in MAIN_L:
                cls_scores[n][msk] = s2[n][msk]
            cls_fin[g] = f2
        rep["cls_models"] = dict(groups_fit=sorted(cls_fin))
        out_cls = {g: {n: m for n, m in d.items()} for g, d in cls_fin.items()}
    walk = ExitWalkCache.get(C, meta)
    t1r = {B["id"]: B["t1"] for B in C.baskets}
    out = dict(report=rep, scores=sc, final=fin, cols=cols, walk=walk, cls_scores=cls_scores, cls_final=out_cls, secs=round(time.time() - t, 1))
    res = {}
    use = cls_scores if cls_scores is not None else sc
    tr_b = [B["id"] for B in C.train]; te_b = [B["id"] for B in C.test]
    two = None
    if cfg.get("two_stage"):
        # thoát 2 giai đoạn: (a) hazard chốt lời trên hàng uPnL>0, (b) hazard cắt lỗ trên hàng uPnL<=0 (có thể = "không bao giờ", bot giữ lệnh lỗ)
        up = f["upnl"].to_numpy()
        vp = valid & (up > 0); vl = valid & (up <= 0)
        scp, finp, _ = DM.run_learners(f, cols, y, w, vp, meta.bid.values, is_train, C.loo, [LMAP[n] for n in MAIN_L])
        npl = int((y[vl & (is_train if not C.loo else True)] == 1).sum())
        scl, finl = (None, None)
        if npl >= 20:
            scl, finl, _ = DM.run_learners(f, cols, y, w, vl, meta.bid.values, is_train, C.loo, [LMAP[n] for n in MAIN_L])
        two = dict(models={n: (finp[n], finl[n] if finl else None) for n in MAIN_L}, comp={}, n_pos_loss_rows=npl, n_pos_profit_rows=int((y[vp] == 1).sum()), params={})
        out["two"] = two; use = {}
        t1a = np.array([t1r[b] for b in tr_b])
        for n in MAIN_L:
            bestk = None
            for k in (1, 3):
                A = np.where(up > 0, scp[n], -1e9)
                thr_p, m15p, _ = DS.choose_exit_thr(walk, A, tr_b, t1a, k)
                if thr_p is None:
                    continue
                thl, m15 = np.inf, m15p
                if scl is not None:
                    lr = scl[n][vl & (is_train if not C.loo else True)]; lr = lr[~np.isnan(lr)]
                    cl = np.unique(lr) if len(np.unique(lr)) <= 40 else np.unique(np.quantile(lr, [0.9, 0.95, 0.98, 0.99, 0.995, 0.999]))
                    for th_l in (cl[:-1] + cl[1:]) / 2 if len(cl) <= 40 and len(cl) > 1 else cl:
                        comp = np.where(up > 0, scp[n] - thr_p, scl[n] - th_l)
                        tt = DS.exit_times(walk, comp, 0.0, tr_b, k)
                        mm = float(np.mean(np.abs(tt - t1a) <= 15 * MIN))
                        if mm > m15 + 0.005:
                            thl, m15 = float(th_l), mm
                if bestk is None or m15 > bestk[0]:
                    bestk = (m15, thr_p, thl, k)
            if bestk is None:
                continue
            m15, thr_p, thl, k = bestk
            comp = np.where(up > 0, scp[n] - thr_p, (scl[n] - thl) if scl is not None else -1e9)
            use[n] = comp; two["comp"][n] = comp; two["params"][n] = dict(thr_profit=float(thr_p), thr_loss=None if not np.isfinite(thl) else float(thl), k=k)
        out["comp"] = use
    for n in MAIN_L:
        if two is not None:
            if n not in use:
                continue
            k = two["params"][n]["k"]; th = 0.0
            rows_tr = DS.exit_rows(walk, use[n], th, C.train, C.lag, k)
            rows_te = DS.exit_rows(walk, use[n], th, C.test, C.lag, k)
            res[n] = dict(thr=th, k=k, two_stage=two["params"][n], train=compact(match.level_a(rows_tr)), test=compact(match.level_a(rows_te)), rows_test=rows_te, rows_train=rows_tr)
            continue
        best = None
        for k in (1, 3):
            if cls_scores is None:
                thr, m15, tab = DS.choose_exit_thr(walk, use[n], tr_b, np.array([t1r[b] for b in tr_b]), k)
                if thr is None:
                    continue
                th = thr
            else:
                th = {}; num = 0
                cgb = {b: CLS_GROUP[DP.sym_class(C.P["ctx"].baskets[b]["sym"])] for b in tr_b}
                m_all = 0
                for g in ("stock", "major", "other"):
                    bb = [b for b in tr_b if cgb[b] == g]
                    if len(bb) < 8:
                        continue
                    thr, m15, tab = DS.choose_exit_thr(walk, use[n], bb, np.array([t1r[b] for b in bb]), k)
                    if thr is None:
                        continue
                    for c, gg in CLS_GROUP.items():
                        if gg == g:
                            th[c] = thr
                    m_all += m15 * len(bb)
                if not th:
                    continue
                dflt = float(np.median(list(th.values())))
                for c in range(4):
                    th.setdefault(c, dflt)
                m15 = m_all / len(tr_b)
            if best is None or m15 > best[0]:
                best = (m15, th, k)
        if best is None:
            continue
        m15, th, k = best
        rows_tr = DS.exit_rows(walk, use[n], th, C.train, C.lag, k)
        rows_te = DS.exit_rows(walk, use[n], th, C.test, C.lag, k)
        res[n] = dict(thr=th, k=k, train=compact(match.level_a(rows_tr)), test=compact(match.level_a(rows_te)), rows_test=rows_te, rows_train=rows_tr)
    out["sim"] = res
    return out


class ExitWalkCache:
    _c = {}

    @classmethod
    def get(cls, C, meta):
        key = (C.name, C.lag, id(meta))
        if key not in cls._c:
            cls._c[key] = DS.ExitWalk(meta, C.P["ctx"], C.lag)
        return cls._c[key]


def miss_analysis(C, ex, model="gbm", topn=12):
    """Trên TRAIN: basket sim thoát lệch > 60p. So đặc trưng tại thời điểm thoát THẬT với tại thời điểm thoát SIM (chuẩn hoá bằng độ lệch chuẩn toàn panel)."""
    meta, f = C.P["exit"]
    walk = ex["walk"]; sc = (ex.get("comp") or ex["cls_scores"] or ex["scores"])[model]; sm = ex["sim"][model]
    cols = ex["cols"]; sd = f[cols].std().replace(0, np.nan)
    diffs = []; n = 0
    for r in sm["rows_train"]:
        if not r.get("sim_close") or r["sim_closed"] and abs(r["sim_close"]["t"] - r["act_close"]["t"]) <= 60 * MIN:
            continue
        b = r["id"]
        a, e = walk.slices[b]
        m = meta.iloc[a:e]
        real = np.flatnonzero((m.exit_y == 1).values)
        if len(real) == 0:
            continue
        rr = a + int(real[0])
        th = sm["thr"][DP.sym_class(r["sym"])] if isinstance(sm["thr"], dict) else sm["thr"]
        ex_r = walk.first_exit(b, sc, th, sm["k"])
        if ex_r < 0:
            ex_r = e - 1
        diffs.append(((f.iloc[rr][cols] - f.iloc[ex_r][cols]) / sd).to_numpy(float)); n += 1
    if not diffs:
        return dict(n_miss=0)
    D = np.array(diffs)
    z = np.nanmean(D, 0) / (np.nanstd(D, 0) / np.sqrt(np.maximum(1, np.sum(~np.isnan(D), 0))) + 1e-9)
    o = np.argsort(-np.abs(np.nan_to_num(z)))[:topn]
    return dict(n_miss=n, top=[dict(feature=cols[k], mean_std_diff_real_minus_sim=round(float(np.nanmean(D[:, k])), 3), t=round(float(z[k]), 2)) for k in o])


# ======================================================================= ADD
def add_tf_eval(meta, walk_idx, score, thr, k):
    """Thoát-đúng-nghĩa 'teacher-forced' cho add: recall add thật (+-5 phút) và specificity (đoạn không có add thật không bị add giả)."""
    hit = tot = ok_neg = tot_neg = 0
    for b, (a, e) in walk_idx.items():
        m = meta.iloc[a:e]
        pre = ((m.pre_close == 1) & (m.tr_ok == 1)).to_numpy()
        ra = np.flatnonzero(m.add_tr_y.to_numpy() == 1)
        s_ = np.where(pre, score[a:e], np.nan)
        bounds = [-1] + list(ra) + [len(m) - 1]
        for q in range(len(bounds) - 1):
            lo, hi = bounds[q] + 1, bounds[q + 1] + 1
            seg = np.nan_to_num(s_[lo:hi], nan=-1e18) > thr
            r = DS.first_run(seg, k)
            if q < len(ra):
                tot += 1
                if r >= 0 and abs(lo + r - ra[q]) <= 5:
                    hit += 1
            else:
                tot_neg += 1
                if r < 0:
                    ok_neg += 1
    rec = hit / tot if tot else 0.0; spec = ok_neg / tot_neg if tot_neg else 1.0
    return rec, spec


def add_stage(C, cfg):
    meta, f = C.P["exit"]
    cols = DM.select_cols(f.columns, cfg["groups"])
    y = meta.add_tr_y.to_numpy(float)
    valid = ((meta.pre_close == 1) & (meta.tr_ok == 1)).to_numpy()
    w = np.ones(len(meta))
    is_train = meta.bid.map(lambda b: b in C.train_ids).to_numpy() if not C.loo else np.ones(len(meta), bool)
    if (y[valid] == 1).sum() < 10:
        return dict(report=dict(n_rows=int(valid.sum()), n_pos=int((y[valid] == 1).sum()), note="quá ít add để học"), skipped=True)
    sc, fin, ex = DM.run_learners(f, cols, y, w, valid, meta.bid.values, is_train, C.loo, [LMAP[n] for n in ALL_L])
    rep = DM.panel_report(f, cols, y, w, valid, is_train, sc, fin, C.loo)
    walk = ExitWalkCache.get(C, meta)
    # chỉ mục theo basket toàn bộ hàng (pre-close) — dùng slices của meta theo bid
    allidx = {}
    bids = meta.bid.values
    cut = np.flatnonzero(np.r_[True, bids[1:] != bids[:-1], True])
    for a, b in zip(cut[:-1], cut[1:]):
        allidx[int(bids[a])] = (int(a), int(b))
    tr_idx = {b: allidx[b] for b in (B["id"] for B in C.train) if b in allidx}
    te_idx = {b: allidx[b] for b in (B["id"] for B in C.test) if b in allidx}
    res = {}
    for n in MAIN_L:
        s_ = sc[n]
        a_ = s_[valid & is_train] if not C.loo else s_[valid]
        a_ = a_[~np.isnan(a_)]
        if len(a_) == 0:
            continue
        uq = np.unique(a_)
        cands = (uq[:-1] + uq[1:]) / 2 if len(uq) <= 40 else np.unique(np.quantile(a_, np.r_[np.linspace(0.8, 0.99, 20), 0.995, 0.998, 0.999, 0.9995]))
        best = None
        for k in (1, 3):
            for th in cands:
                rec, spec = add_tf_eval(meta, tr_idx, s_, th, k)
                J = rec + spec - 1
                if best is None or J > best[0]:
                    best = (J, float(th), k, rec, spec)
        J, th, k, rec, spec = best
        rte, ste = add_tf_eval(meta, te_idx, s_, th, k)
        res[n] = dict(thr=th, k=k, train_recall=round(rec, 3), train_spec=round(spec, 3), test_recall=round(rte, 3), test_spec=round(ste, 3))
    return dict(report=rep, final=fin, cols=cols, sim=res, scores=sc, skipped=False)


# ======================================================================= ENTRY
def entry_stage(C, cfg, ex_cache={}):
    P = C.P
    meta, f = P["entry"]
    cols = DM.select_cols(f.columns, set(cfg["groups"]) - {"pos", "pos_ext", "book"})
    y = meta.entry_y.to_numpy(float); w = meta.w.to_numpy(float)
    blocks = (meta.tau.values // (2 * 86400_000)).astype(int)
    is_train = (meta.tau.values < C.split_t) if not C.loo else np.ones(len(meta), bool)
    valid = np.ones(len(meta), bool)
    t = time.time()
    sc, fin, ex = DM.run_learners(f, cols, y, w, valid, blocks, is_train, False, [LMAP[n] for n in ALL_L])
    rep = DM.panel_report(f, cols, y, w, valid, is_train, sc, fin, C.loo)
    rep["note"] = "entry: lưới 5m, âm giảm mẫu (trọng số 1/p_keep=%.1f); " % (1 / P["p_keep"]) + ("LOO không áp dụng -> OOF theo khối 2 ngày (4 fold)" if C.loo else "test = tau >= split")
    fold = ex["fold"]
    fob = {int(b): int(k) for b, k in zip(blocks[is_train], fold[is_train])}
    fms = {n: {k: m for k, m in d.items()} for n, d in ex["fold_models"].items()}
    out = dict(report=rep, final=fin, cols=cols, fold_of_block=fob, fold_models=fms, secs=round(time.time() - t, 1))
    return out


def entry_levelb_stage(C, en, quick=False):
    """Điểm lưới 5m toàn cửa sổ; chọn (ngưỡng, cooldown) trên train theo F1 vượt baseline; báo cáo test."""
    P = C.P; ctx = P["ctx"]
    lo = min(B["t0"] for B in C.baskets) - 6 * 3600_000; hi = max(B["t0"] for B in C.baskets) + 15 * MIN
    names = ["gbm", "tree3", "pair"]
    log("entry grid scoring ...")
    gs = DS.grid_scores(P, en["cols"], en["final"], en["fold_models"], en["fold_of_block"], C.split_t if not C.loo else 1 << 62, lo, hi, names_to_run=names)
    t_tr = np.array([B["t0"] for B in C.baskets if B["t0"] < C.split_t]) if not C.loo else np.array([B["t0"] for B in C.baskets])
    hh = np.bincount(((t_tr // 3_600_000 + 7) % 24).astype(int), minlength=24).astype(float) + 0.5; hh /= hh.sum()
    hold_med = float(np.median([(B["t1"] - B["t0"]) / MIN for B in C.train]))
    res = {}
    split = C.split_t if not C.loo else hi
    lo_tr = min(B["t0"] for B in C.baskets)
    for n in names:
        allsc = np.concatenate([r[n][(t < split) & (t >= lo_tr)] for (t, r) in gs.values()])
        if len(allsc) == 0:
            continue
        uq = np.unique(allsc)
        cands = (uq[:-1] + uq[1:]) / 2 if len(uq) <= 40 else np.unique(np.quantile(allsc, [0.9, 0.95, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995]))
        best = None
        for th in cands:
            for cool in (15, 60, max(15, min(1440, hold_med))):
                m, _ = DS.entry_levelb(P, gs, n, th, cool, lo_tr, split, hh, reps=8 if quick else 15)
                if m["n_sim_starts"] < 5:
                    continue
                sc_ = match.f1_excess(m)
                if best is None or sc_ > best[0]:
                    best = (sc_, float(th), float(cool), m)
        if best is None:
            continue
        _, th, cool, mtr = best
        mte, sig = DS.entry_levelb(P, gs, n, th, cool, split if not C.loo else lo_tr, hi if not C.loo else split, hh, reps=60 if quick else 200)
        res[n] = dict(thr=th, cooldown_min=cool, train=mtr, test=mte, cands=[float(c) for c in cands])
        # ngưỡng THEO (mã, chiều): số tín hiệu trên train ~ số basket thật của (mã, chiều) đó (khớp tần suất theo mã/lớp mã + bộ mã của bot + phiên giao dịch do mô hình tự học)
        counts = {}
        for B in C.baskets:
            if B["t0"] < split:
                counts[(B["sym"], B["side"])] = counts.get((B["sym"], B["side"]), 0) + 1
        rm_thr = DS.rate_match_thresholds(gs, n, lo_tr, split, counts, cool)
        mtr2, _ = DS.entry_levelb(P, gs, n, rm_thr, cool, lo_tr, split, hh, reps=8 if quick else 15)
        mte2, _ = DS.entry_levelb(P, gs, n, rm_thr, cool, split if not C.loo else lo_tr, hi if not C.loo else split, hh, reps=60 if quick else 200)
        res[n]["rate_matched"] = dict(thr=rm_thr, counts=counts, cooldown_min=cool, train=mtr2, test=mte2, n_ss_active=sum(1 for v in rm_thr.values() if np.isfinite(v)),
                                      train_f1_excess=match.f1_excess(mtr2), global_train_f1_excess=match.f1_excess(mtr))
    return dict(gs=gs, sim=res, hh=hh, hold_med=hold_med, split=split, lo_tr=lo_tr, hi=hi)


# ======================================================================= toàn bộ + Level S
def build_engine(C, ex, ad, model_exit, model_add, add_mode=True, k_exit=1, k_add=1, thr_exit=None, thr_add=None, fee=DS.FEE_A, sizing=None):
    """Engine từ mô hình đã học. exit: dùng mô hình cuối của exit_stage (theo lớp nếu cfg cls)."""
    fe = ex["final"][model_exit]; cf = ex.get("cls_final") or {}
    iu = ex["cols"].index("upnl") if "upnl" in ex["cols"] else None
    def ex_fn(X, sym):
        if ex.get("two"):
            mp, ml = ex["two"]["models"][model_exit]; pr = ex["two"]["params"][model_exit]
            sp = mp.score(X) - pr["thr_profit"]
            sl = (ml.score(X) - pr["thr_loss"]) if (ml is not None and pr["thr_loss"] is not None) else np.full(len(X), -1e9)
            return np.where(X[:, iu] > 0, sp, sl)
        g = CLS_GROUP[DP.sym_class(sym)]
        return (cf[g][model_exit] if g in cf and model_exit in cf[g] else fe).score(X)
    ad_fn = (lambda X, sym: ad["final"][model_add].score(X)) if (add_mode and ad and not ad.get("skipped")) else None
    return DS.Engine(C.P["ctx"], ex["cols"], ex_fn, thr_exit, ad["cols"] if ad_fn else None, ad_fn, thr_add, lag=C.lag, k_exit=k_exit, k_add=k_add,
                     max_layers=int(min(40, max(2, max(len(B["tranches"]) for B in C.train) + 2))), add_ratio=(sizing or {}).get("add_ratio", 1.0), fee=fee)


def full_sim_rows(C, eng, baskets):
    rows = []
    for B in baskets:
        S = DS.sim_basket_full(eng, B)
        rows.append(match.basket_row(B, S))
    return rows


def baskets_trades(C, lo, hi):
    """Trade thật (schema bots.json) của các basket có t0 trong [lo, hi]."""
    bk = set()
    for B in C.P["ctx"].baskets:
        if lo <= B["t0"] <= hi:
            bk.update(B["bk_ids"])
    return [dict(t) for t in C.bot["trades"] if t["bk"] in bk]


def slim_trades(T):
    """Trade sim theo schema bots.json (sym, side, lev, o, c, po, pc, pnl, pr, mg, mae, add, bk), số thực làm tròn 6 chữ số có nghĩa."""
    r6 = lambda x: None if x is None else float("%.6g" % x)
    return [dict(sym=t["sym"], side=t["side"], lev=r6(t["lev"]), o=int(t["o"]), c=int(t["c"]), po=r6(t["po"]), pc=r6(t["pc"]), pnl=r6(t["pnl"]), pr=r6(t["pr"]), mg=r6(t["mg"]),
                 mae=r6(t.get("mae")), add=bool(t.get("add")), bk=int(t.get("bk", -1))) for t in sorted(T, key=lambda x: x["o"])]


def level_s(C, eng_fn, en_ls, window, lo, hi, sizing, tag, replay=False):
    """Backtest tự chạy trên [lo,hi] và so sánh với bot thật."""
    real_T = baskets_trades(C, lo, hi)
    real_st = ST.stats([dict(t) for t in real_T])
    real_T2 = [dict(t) for t in real_T]; ST.stats(real_T2)         # gán add/bk
    max_conc = DS.real_max_concurrent([B for B in C.P["ctx"].baskets])
    hold = np.array([(B["t1"] - B["t0"]) / MIN for B in C.train])
    max_hold = float(max(1440.0, 2 * np.percentile(hold, 95)))
    en = en_ls
    eng = eng_fn
    t = time.time()
    if replay:
        trades, info = DS.free_run_replay_entries(C.P, eng, C.P["ctx"].baskets, lo, hi, sizing, max_hold)
    else:
        trades, info = DS.free_run(C.P, eng, en["gs"], en["model"], en["thr"], en["cool"], lo, hi, sizing, max_conc, max_hold)
    sim_T = [{k: v for k, v in t_.items() if k != "forced"} for t_ in trades]
    sim_st = ST.stats(sim_T) if sim_T else dict(n=0)
    cmp = ST.compare(real_st, sim_st) if sim_T else None
    out = dict(window=[int(lo), int(hi)], tag=tag, info=info, max_concurrent=max_conc, max_hold_min=max_hold, secs=round(time.time() - t, 1),
               real=real_st, sim=sim_st, compare=cmp)
    if sim_T:
        out["mix_overlap"] = ST.mix_overlap(real_st, sim_st)
        out["daily"] = ST.daily_corr(real_T2, sim_T, lo, hi)
        out["basket_overlap"] = ST.basket_overlap(real_T2, sim_T)
        out["trades"] = slim_trades(sim_T)
    return out, sim_T


def verdict(lA, base, add_base_p95, ci):
    """Nhãn theo spec: khớp tốt / khớp một phần / không tái tạo được."""
    ex15 = lA.get("close_match_15") or 0; addm = lA.get("tr_add_match") or lA.get("add_match") or 0; corr = lA.get("pnl_corr") or 0
    b15 = max(base["null"].get("close_match_15") or 0, (base["shuffled_tp"] or {}).get("close_match_15", {}).get("p95", 0))
    bcorr = (base["shuffled_tp"] or {}).get("pnl_corr", {}).get("p95", 0)
    p_ex = ex15 >= 60 and ex15 > b15
    p_add = addm >= 50 and addm > add_base_p95
    p_pnl = corr >= 0.7 and corr > bcorr
    n_pass = p_ex + p_add + p_pnl
    if n_pass == 3:
        lab = "khớp tốt"
    elif n_pass >= 1 and ((ci[0] or 0) > b15 if p_ex else True):
        lab = "khớp một phần"
    else:
        lab = "không tái tạo được"
    # "một phần" yêu cầu CI95 dưới của thoát +-15 vượt p95 baseline NẾU điều kiện thoát là điều kiện đạt; các điều kiện khác dùng số liệu trực tiếp
    return dict(label=lab, passes=dict(exit15_ge60_and_beats_baseline=bool(p_ex), add_ge50_and_beats_baseline=bool(p_add), pnl_corr_ge07_and_beats_baseline=bool(p_pnl)),
                numbers=dict(exit15=ex15, exit15_ci95=ci, baseline_exit15_p95=b15, add_match=addm, add_baseline=add_base_p95, pnl_corr=corr, baseline_pnl_corr_p95=bcorr))


def phase1_add_baseline(slug):
    """Add match tốt nhất của mô hình cơ khí phase 1 trên TEST (để so)."""
    p = os.path.join(OUT, f"{slug}.json")
    try:
        d = json.load(open(p))
        m = d["metrics"]["test"]["levelA"] if "test" in d["metrics"] else d["metrics"]["levelA"]
        return float(m.get("tr_add_match") or m.get("add_match") or 0)
    except Exception:
        return 0.0


def sel_score(m):
    """Điểm chọn cấu hình/mô hình trên TRAIN: nửa khớp thời điểm thoát +-15p, nửa khớp dấu PnL (giữ lệnh lỗ / chốt lời nhỏ)."""
    return 0.5 * (m.get("close_match_15") or 0) + 0.5 * (m.get("pnl_sign_agree") or 0)


def pick(sim_d, key="train", metric="close_match_15"):
    return max(sim_d, key=lambda n: sel_score(sim_d[n][key]))


def rep_slim(rep):
    """Báo cáo panel gọn cho JSON (bỏ khoá nặng)."""
    out = {k: v for k, v in rep.items() if k not in ("gbm", "tree2", "tree3", "tree4", "single", "pair")}
    gbm = rep["gbm"]
    out["gbm"] = dict(auc_test=gbm["auc_test"], pr_auc=gbm["pr_auc"], importance=gbm.get("importance"))
    for k in ("tree2", "tree3", "tree4"):
        if k in rep:
            out[k] = {kk: vv for kk, vv in rep[k].items()}
    for k in ("single", "pair"):
        if k in rep:
            out[k] = rep[k]
    return out


CASE_COLS = ["upnl", "upnl_a1h", "mfe_last", "gb", "mae_first", "mins_first", "mins_last", "n_fill", "s_rsi1h", "s_zret60", "s_ema21_15m_a", "atr1h", "cal_mod", "d_fav240_a", "d_adv240_a"]


def run_tiny(C, name, slug):
    """Bot < 20 basket: bỏ ML; bảng từng ca (trạng thái tại lúc vào và lúc thoát) + chỉ số thật; ghi rõ mẫu quá nhỏ."""
    meta, f = C.P["exit"]
    cases = []
    for B in C.baskets:
        names, X, a = DP.sym_matrix(B["sym"])
        s = 1 if B["side"] == "long" else -1
        j = DP.bar_of(a, B["t0"]) - 1
        nm, Xs = DP.signed_view(names, np.asarray(X[[j]]), s)
        ent = {k: round(float(v), 4) for k, v in zip(nm, Xs[0]) if k in CASE_COLS or k in ("s_rsi1h", "s_zret60", "s_ret240", "atr1h", "cal_mod", "cal_wday")}
        m = meta[(meta.bid == B["id"]) & (meta.exit_y == 1)]
        ex = {}
        if len(m):
            row = f.loc[m.index[0]]
            ex = {k: round(float(row[k]), 4) for k in CASE_COLS if k in row.index and np.isfinite(row[k])}
        cases.append(dict(id=B["id"], sym=B["sym"], side=B["side"], lev=B["lev"], t0=int(B["t0"]), t1=int(B["t1"]), hold_h=round((B["t1"] - B["t0"]) / 3.6e6, 2), n_fills=len(B["fills"]),
                          ret_pct=round(B["ret"], 3), pnl=round(B["pnl"], 1), state_at_entry=ent, state_at_exit=ex))
    real = ST.stats([dict(t) for t in C.bot["trades"]])
    js = dict(bot=name, n_baskets=len(C.baskets), tiny=True, case_table=cases, real_stats=real, panels={}, iterations=[], level_s={},
              mechanism=dict(exit="Mẫu quá nhỏ (%d basket) để học luật; xem bảng ca." % len(C.baskets), add="Mẫu quá nhỏ.", entry="Mẫu quá nhỏ."),
              verdict=dict(label="không tái tạo được", why="Chỉ %d basket: không đủ mẫu để học/kiểm định (bỏ ML theo spec); chỉ có bảng ca thủ công." % len(C.baskets)))
    path = os.path.join(OUT, f"disc_{slug}.json")
    open(path, "w").write(json.dumps(DS._jsonable(js), ensure_ascii=False))
    log("wrote tiny", path)
    return js


def run(name, quick=False, stages=("exit", "add", "entry", "levelS")):
    t_start = time.time()
    slug = load.slug(name)
    C = Ctx(name, lag=1, quick=quick)
    if len(C.baskets) < 20:
        return run_tiny(C, name, slug)
    meta_ex = C.P["exit"][0]
    log(name, "baskets", len(C.baskets), "train", len(C.train), "test", len(C.test), "scalp<1m", C.n_scalp, "LOO" if C.loo else "time-split", "exit rows", len(meta_ex))
    js = dict(bot=name, n_baskets=len(C.baskets), n_scalp_sub_minute=C.n_scalp,
              split=dict(split_t=int(C.split_t) if not C.loo else None, n_train=len(C.train), n_test=len(C.test), loo=C.loo,
                         note="LOO theo basket (mô hình/ngưỡng/đánh giá trên cùng dữ liệu, lạc quan; entry dùng OOF theo khối 2 ngày)" if C.loo else "60%% basket đầu theo thời điểm fill đầu = train; 40%% cuối = test; basket mở-đóng <1 phút bị loại khỏi đánh giá exit/add (%d basket)" % C.n_scalp),
              lag=C.lag, panels={}, iterations=[])
    sc = DP.selfcheck(name)
    js["selfcheck_no_lookahead"] = dict(n_checked=sc["n_checked"], n_bad=sc["n_bad"], max_pos_dev=max(r["pos_dev"] for r in sc["rows"]), max_price_err=max(r["price_maxerr"] for r in sc["rows"]))
    log("selfcheck", js["selfcheck_no_lookahead"])
    nullm, nullp = DS.baseline_null(C.train, C.test)
    shuf = DS.baseline_shuffled_tp(C.train, C.test, reps=6 if quick else 20)
    base = dict(null=compact(nullm), null_params=nullp, shuffled_tp=shuf)
    log("baselines null15", base["null"].get("close_match_15"), "shuffledTP15", (shuf or {}).get("close_match_15"))
    # ------------------------------------------------------------------ EXIT: vòng lặp (spec §4)
    G1 = set(BASE_GROUPS)
    cfgs = [("base", dict(groups=G1), "mốc đầu: vị thế + giá + lịch (spec §1), nhãn = lần đóng đầu, đặc trưng chỉ đến nến i-1 (LAG=1)"),
            ("ext_pos", dict(groups=G1 | {"pos_ext"}), "thêm đặc trưng vị thế mở rộng (phút từ đỉnh, giá vs fill gần/đầu, avg vs đầu, upnl/bước)"),
            ("ext_price", dict(groups=G1 | {"pos_ext", "price_ext"}), "thêm đặc trưng giá mở rộng (từ open giờ/ngày/phiên Mỹ, ngày trước, hình nến, rank, streak, volume khung lớn)"),
            ("two_stage", dict(groups=G1 | {"pos_ext", "price_ext"}, two_stage=True), "thoát 2 giai đoạn: hazard chốt lời (uPnL>0) và hazard cắt lỗ (uPnL<=0, có thể không bao giờ) — bot chốt lời nhỏ, giữ lệnh lỗ"),
            ("target_last", dict(groups=G1 | {"pos_ext", "price_ext"}, target="last"), "nhãn = lần đóng CUỐI (basket đóng từng tầng lệch giờ), vì level_a so với lần đóng cuối"),
            ("per_class", dict(groups=G1 | {"pos_ext", "price_ext"}, cls_models=True), "mô hình riêng theo lớp mã (cổ phiếu / crypto lớn / khác)")]
    best_name = None; best_tr = -1.0; no_gain = 0
    exits = {}
    pc = cfgs[-1]; cfgs = cfgs[:-1]
    queue = list(cfgs)
    i = 0; stopped = False
    while queue or not stopped:
        if not queue:                                   # luôn thử mô hình theo lớp mã (spec §4) trên cấu hình tốt nhất theo train
            bcfg = dict(exits[best_name][0]); bcfg["cls_models"] = True; bcfg.pop("two_stage", None)
            nm, cfg, why = pc[0], bcfg, pc[2] + " (trên cấu hình tốt nhất theo train: %s)" % best_name
            stopped = True
        else:
            nm, cfg, why = queue.pop(0)
        log("EXIT iter", i, nm)
        ex = exit_stage(C, cfg, full_report=(i == 0))
        exits[nm] = (cfg, ex)
        sm = ex["sim"]
        bn = pick(sm)
        tr15 = sm[bn]["train"].get("close_match_15") or 0
        sel = sel_score(sm[bn]["train"])
        mi = miss_analysis(C, ex, bn)
        js["iterations"].append(dict(i=i, name=nm, change=why, why="chọn theo khớp +-15p trên TRAIN (điểm out-of-fold); test chỉ để báo cáo", best_model_by_train=bn,
                                     train_close15=tr15, train_sel_score=round(sel, 2), test_close15=sm[bn]["test"].get("close_match_15"), test_pnl_sign_agree=sm[bn]["test"].get("pnl_sign_agree"), gbm_auc_test=ex["report"]["gbm"]["auc_test"], secs=ex["secs"],
                                     metrics={n: dict(train=sm[n]["train"], test=sm[n]["test"], k=sm[n]["k"]) for n in sm}, miss_top_features=mi))
        log("   best", bn, "train15", tr15, "sel", round(sel, 1), "test15", sm[bn]["test"].get("close_match_15"), "auc", ex["report"]["gbm"]["auc_test"])
        if sel > best_tr:
            gain = sel - best_tr
            no_gain = 0 if (gain >= 1.0 or best_name is None) else no_gain + 1
            best_tr = sel; best_name = nm
        else:
            no_gain += 1
        i += 1
        if no_gain >= 3 and queue:
            js["iterations"][-1]["stop"] = "3 vòng liên tiếp cải thiện train < 1 điểm"
            queue = []
    cfg, ex = exits[best_name]
    js["selected_exit_config"] = dict(name=best_name, groups=sorted(cfg["groups"]), target=cfg.get("target", "first"), per_class=bool(cfg.get("cls_models")))
    bn = pick(ex["sim"]); primary = bn
    js["panels"]["exit"] = rep_slim(ex["report"])
    js["panels"]["exit"]["note"] = "AUC gộp theo hàng: bị chi phối bởi trạng thái lãi/lỗ (thoát khi đang lãi) — xem so sánh thời điểm +-15p"
    # ------------------------------------------------------------------ ADD
    ad = add_stage(C, cfg)
    js["panels"]["add"] = rep_slim(ad["report"]) if not ad.get("skipped") else ad["report"]
    js["panels"]["add"]["sim_teacher_forced"] = ad.get("sim")
    log("ADD", ad.get("sim"))
    # ------------------------------------------------------------------ ENTRY
    en = entry_stage(C, cfg)
    js["panels"]["entry"] = rep_slim(en["report"])
    lb = entry_levelb_stage(C, en, quick)
    slim = lambda m: {k: m[k] for k in m if not k.startswith("hits")}
    js["sim_entry_levelB"] = {n: dict(thr=v["thr"], cooldown_min=v["cooldown_min"], train=slim(v["train"]), test=slim(v["test"]),
                                       rate_matched=dict(n_symbol_side_active=v["rate_matched"]["n_ss_active"], cooldown_min=v["rate_matched"]["cooldown_min"],
                                                         train=slim(v["rate_matched"]["train"]), test=slim(v["rate_matched"]["test"]),
                                                         note="ngưỡng theo (mã,chiều): số tín hiệu train ~ số basket thật; (mã,chiều) không có basket thật = tắt")) for n, v in lb["sim"].items()}
    for n, v in lb["sim"].items():
        log("ENTRY", n, "global:", v["test"]["strength"], "recall15", v["test"]["recall_15"], "prec15", v["test"]["precision_15"], "| rate-matched:", v["rate_matched"]["test"]["strength"], "recall15", v["rate_matched"]["test"]["recall_15"], "prec15", v["rate_matched"]["test"]["precision_15"], "n_sim", v["rate_matched"]["test"]["n_sim_starts"], "n_act", v["rate_matched"]["test"]["n_actual_starts"])
    # ------------------------------------------------------------------ sim đầy đủ có điều kiện (add + exit học được)
    trades_train = [t for t in C.bot["trades"] if t["bk"] in {b for B in C.train_all for b in B["bk_ids"]}]
    sizing = DS.sizing_from_train(C.train_all, trades_train)
    js["sizing_from_train"] = sizing
    full = {}
    for n in MAIN_L:
        if n not in ex["sim"]:
            continue
        thr_e = ex["sim"][n]["thr"]; k_e = ex["sim"][n]["k"]
        use_add = (not ad.get("skipped")) and n in ad["sim"]
        eng = build_engine(C, ex, ad if use_add else None, n, n, add_mode=use_add, k_exit=k_e, k_add=(ad["sim"][n]["k"] if use_add else 1),
                           thr_exit=thr_e, thr_add=(ad["sim"][n]["thr"] if use_add else None), sizing=sizing)
        rows = full_sim_rows(C, eng, C.test)
        full[n] = dict(rows=rows, levelA=compact(match.level_a(rows)), used_add=use_add)
        log("FULL SIM", n, full[n]["levelA"].get("close_match_15"), full[n]["levelA"].get("tr_add_match"), full[n]["levelA"].get("pnl_corr"))
    # ------------------------------------------------------------------ gói kết quả Level A
    rows_exit = ex["sim"][primary]["rows_test"]
    nT = len(rows_exit)
    m15 = ex["sim"][primary]["test"].get("close_match_15") or 0
    ci = DS.wilson(int(round(m15 / 100 * nT)), nT)
    add_base = phase1_add_baseline(slug)
    lA_full = full[primary]["levelA"] if primary in full else {}
    verd_inputs = dict(lA_full)
    verd_inputs["close_match_15"] = m15
    verd_inputs["pnl_corr"] = ex["sim"][primary]["test"].get("pnl_corr")
    js["sim"] = dict(primary_model=primary, level_a_test_exit_only_replay_fills={n: ex["sim"][n]["test"] for n in ex["sim"]},
                     level_a_train_oof_exit_only={n: ex["sim"][n]["train"] for n in ex["sim"]},
                     thresholds={n: dict(exit_thr=ex["sim"][n]["thr"], k_exit=ex["sim"][n]["k"], **({"add_thr": ad["sim"][n]["thr"], "k_add": ad["sim"][n]["k"]} if (not ad.get("skipped") and n in ad["sim"]) else {})) for n in ex["sim"]},
                     level_a_test_full_sim_add_plus_exit={n: full[n]["levelA"] for n in full},
                     baselines=base, exit15_ci95_primary=ci, phase1_best_mechanical_add_match_test=add_base)
    js["verdict"] = verdict(verd_inputs, base, add_base, ci)
    # đại diện + đường cộng dồn
    rows_f = full[primary]["rows"] if primary in full else rows_exit
    okr = [r for r in rows_f if "sim_ret" in r]
    if okr:
        dts = [abs(r["sim_close"]["t"] - r["act_close"]["t"]) if r["sim_closed"] else 1e18 for r in okr]
        o = np.argsort(dts)
        picks = {"khớp thoát tốt nhất": okr[o[0]], "trung vị": okr[o[len(o) // 2]], "lệch nhất": okr[o[-1]],
                 "lỗ thật lớn nhất": min(okr, key=lambda r: r["act_pnl"]), "lãi thật lớn nhất": max(okr, key=lambda r: r["act_pnl"])}
        js["representative"] = [dict(tag=k, **v) for k, v in picks.items()]
    js["cum_curve_test"] = match.cum_curve(rows_f)
    # ------------------------------------------------------------------ mechanism (mô tả bằng số từ mô hình)
    js["mechanism"] = mechanism_text(C, ex, ad, lb, primary, en)
    # ------------------------------------------------------------------ Level S
    js["level_s"] = {}
    if "levelS" in stages:
        s_models = [primary] + (["tree3"] if primary != "tree3" else [])
        t_first = min(B["t0"] for B in C.baskets); t_last = max(B["t1"] for B in C.baskets)
        for n in s_models:
            if n not in ex["sim"] or n not in lb["sim"]:
                continue
            thr_e = ex["sim"][n]["thr"]; use_add = (not ad.get("skipped")) and n in ad["sim"]
            if use_add:
                a_ = ad["sim"][n]; J_ = a_["train_recall"] + a_["train_spec"] - 1
                if J_ < 0.10:       # luật add không hơn ngẫu nhiên trên train -> không sinh add trong backtest tự chạy (add giả tạo martingale vô nghĩa)
                    use_add = False
                js["level_s"].setdefault("_add_rule", {})[n] = dict(train_youden=round(J_, 3), enabled=bool(use_add), note="add chỉ bật khi Youden(recall+specificity-1) trên train >= 0.10")
            eng = build_engine(C, ex, ad if use_add else None, n, n, add_mode=use_add, k_exit=ex["sim"][n]["k"], k_add=(ad["sim"][n]["k"] if use_add else 1),
                               thr_exit=thr_e, thr_add=(ad["sim"][n]["thr"] if use_add else None), fee=DS.FEE_S, sizing=sizing)
            rm = lb["sim"][n]["rate_matched"]
            en_ls = dict(gs=lb["gs"], model=n, thr=rm["thr"], cool=rm["cooldown_min"])
            res = {}
            if n == primary and not quick and os.environ.get("DISC_CALIB"):
                # lặp theo Level S (spec §6): hệ số tần suất entry (x số basket thật theo mã/chiều) và cooldown, chọn trên cửa sổ TRAIN theo stats-match + tương quan PnL ngày
                lo_c, hi_c = t_first, (C.split_t if not C.loo else t_last)
                combos = [(0.6, rm["cooldown_min"]), (1.0, rm["cooldown_min"]), (1.5, rm["cooldown_min"]), (1.0, 60.0)]
                cal = []; bestc = None
                for fac, cl in combos:
                    thr_f = DS.rate_match_thresholds(lb["gs"], n, lb["lo_tr"], lb["split"], rm["counts"], cl, fac)
                    e2 = dict(en_ls, thr=thr_f, cool=cl)
                    r, _ = level_s(C, eng, e2, "calib", lo_c, hi_c, sizing, "train-calib")
                    sc_ = ((r["compare"] or {}).get("stats_match_score") or 0) + 0.5 * max(0, (r.get("daily") or {}).get("daily_corr") or 0)
                    cal.append(dict(factor=fac, cooldown_min=cl, stats_match=(r["compare"] or {}).get("stats_match_score"), daily_corr=(r.get("daily") or {}).get("daily_corr"),
                                    n_sim_baskets=r["info"]["n_baskets"], hold_med_h=(r["sim"] or {}).get("holdMed"), win=(r["sim"] or {}).get("win"), score=round(sc_, 3)))
                    log("   S-calib", cal[-1])
                    if bestc is None or sc_ > bestc[0]:
                        bestc = (sc_, thr_f, cl, fac)
                en_ls = dict(en_ls, thr=bestc[1], cool=bestc[2])
                js["level_s"].setdefault("_calibration", {})[n] = dict(window="train" if not C.loo else "toàn bộ (LOO)", table=cal, chosen=dict(factor=bestc[3], cooldown_min=bestc[2]))
            wins = [("test", C.split_t if not C.loo else t_first, t_last)] + ([("full", t_first, t_last)] if not C.loo else [])
            for tag, lo, hi in wins:
                log("LEVEL S", n, tag)
                r, sim_T = level_s(C, eng, en_ls, tag, lo, hi, sizing, tag)
                r2, _ = level_s(C, eng, en_ls, tag, lo, hi, sizing, tag + "-replay-entries", replay=True)
                r["replay_entries"] = r2
                res[tag] = r
                for nm_, rr in (("free", r), ("replay-entries", r2)):
                    if rr.get("compare"):
                        log("   %s: stats match" % nm_, rr["compare"]["stats_match_score"], "daily corr", (rr.get("daily") or {}).get("daily_corr"), "overlap15", (rr.get("basket_overlap") or {}).get("recall_15"),
                            "n sim trades", rr["sim"].get("n"), "holdMed", rr["sim"].get("holdMed"), "win", rr["sim"].get("win"))
            js["level_s"][n] = res
    js["runtime_s"] = round(time.time() - t_start, 1)
    path = os.path.join(OUT, f"disc_{slug}.json")
    txt = json.dumps(DS._jsonable(js), ensure_ascii=False)
    if len(txt) > 3e6:                                   # giữ < 3 MB: bỏ trade cửa sổ test và biến thể replay, chỉ giữ cửa sổ full
        for n_, v_ in js.get("level_s", {}).items():
            if isinstance(v_, dict) and "test" in v_ and "full" in v_:
                v_["test"].pop("trades", None)
        txt = json.dumps(DS._jsonable(js), ensure_ascii=False)
    if len(txt) > 3e6:
        for n_, v_ in js.get("level_s", {}).items():
            if isinstance(v_, dict):
                for w_ in ("test", "full"):
                    if w_ in v_:
                        v_[w_].get("replay_entries", {}).pop("trades", None)
        txt = json.dumps(DS._jsonable(js), ensure_ascii=False)
    open(path, "w").write(txt)
    log("wrote", path, "verdict", js["verdict"]["label"])
    return js


def mechanism_text(C, ex, ad, lb, primary, en):
    """Mô tả cơ chế (số cụ thể) từ cây/luật cặp + nhận xét độ dự đoán (AUC GBM < 0.65 => không dự đoán được)."""
    def one(rep, nm):
        g = rep["gbm"]["auc_test"]
        imp = ", ".join(x["feature"] for x in (rep["gbm"].get("importance") or [])[:5] if "feature" in x)
        pr = rep.get("pair", {}).get("rule_text")
        t3 = rep.get("tree3", {}).get("auc_test")
        return "%s: GBM test AUC %.3f (%s); cây sâu 3 AUC %s (giữ %s lift); luật cặp: %s (AUC %s); đặc trưng quan trọng: %s." % (
            nm, g, "có tín hiệu" if g >= 0.65 else "KHÔNG dự đoán được từ trạng thái giá/giờ", t3, rep.get("tree3", {}).get("lift_kept_vs_gbm"), pr, rep.get("pair", {}).get("auc_test"), imp)
    return dict(exit=one(ex["report"], "Thoát"), add=("Add: bỏ qua (quá ít mẫu)" if ad.get("skipped") else one(ad["report"], "Add")), entry=one(en["report"], "Vào lệnh"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bot"); ap.add_argument("--quick", action="store_true"); ap.add_argument("--stages", default="exit,add,entry,levelS")
    a = ap.parse_args()
    run(a.bot, a.quick, tuple(a.stages.split(",")))
