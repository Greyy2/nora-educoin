"""Phase 2 — mô hình học luật quyết định từ panel: GBM, cây nông (độ sâu 2/3/4), luật ngưỡng 1-2 đặc trưng.

Chia train/test theo THỜI GIAN (60/40 theo basket). Điểm cho train là OUT-OF-FOLD (nhóm theo basket / khối thời gian) để chọn ngưỡng
sim trên train không bị lạc quan; điểm cho test từ mô hình fit trên toàn train. Bot nhỏ (<40 basket): leave-one-basket-out (LOO) —
mọi điểm đều là LOO, và nói rõ trong JSON.
"""
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.inspection import permutation_importance

warnings.filterwarnings("ignore")

POS_BASE = [n for n in ["upnl", "upnl_a1h", "upnl_a15m", "upnl_a1m", "mfe_last", "mfe_last_a", "mfe_first", "mfe_first_a", "gb", "gb_a", "gb_ratio",
                        "gb_first", "gb_first_a", "mae_last", "mae_last_a", "mae_first", "mae_first_a", "mins_first", "mins_last", "n_fill", "n_tr",
                        "last_step", "notional_vs_first"]]


def col_group(nm):
    """Nhóm của cột: pos / pos_ext / price / price_ext / cal / book / meta."""
    if nm in POS_BASE:
        return "pos"
    if nm in ("x_mins_since_peak", "x_px_vs_last", "x_px_vs_first", "x_avg_vs_first", "x_mins_since_peak_first", "x_upnl_per_step"):
        return "pos_ext"
    if nm.startswith("bk_"):
        return "book"
    if nm.startswith(("cal_", "is_stock", "cls", "side")):
        return "cal"
    if nm.startswith(("s_x_", "x_", "w_", "vz")):
        return "price_ext"
    return "price"


def select_cols(columns, groups):
    return [c for c in columns if col_group(c) in groups]


# ----------------------------------------------------------------------------- bộ học
def _bal(y, w):
    """Trọng số cân bằng lớp (tổng trọng số dương = tổng trọng số âm)."""
    wp = w[y == 1].sum(); wn = w[y == 0].sum()
    return np.where(y == 1, w * (wn / max(wp, 1e-9)), w)


class GBM:
    name = "gbm"

    def fit(self, X, y, w, cols):
        n = len(y)
        self.m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=max(40, int(n * 0.0008)),
                                                l2_regularization=1.0, early_stopping=True, validation_fraction=0.15, n_iter_no_change=20, random_state=0)
        self.m.fit(X, y, sample_weight=_bal(y, w))
        return self

    def score(self, X):
        return self.m.predict_proba(X)[:, 1]


class Tree:
    def __init__(self, depth):
        self.depth = depth; self.name = f"tree{depth}"

    def fit(self, X, y, w, cols):
        n = len(y)
        self.cols = cols
        self.m = DecisionTreeClassifier(max_depth=self.depth, min_samples_leaf=max(30, int(n * 0.002)), random_state=0)
        self.m.fit(X, y, sample_weight=_bal(y, w))
        return self

    def score(self, X):
        return self.m.predict_proba(X)[:, 1]

    def text(self):
        return export_text(self.m, feature_names=list(self.cols), decimals=3)


def _wauc(y, s, w):
    ok = ~np.isnan(s)
    if ok.sum() < 3 or len(np.unique(y[ok])) < 2:
        return 0.5
    return float(roc_auc_score(y[ok], s[ok], sample_weight=w[ok]))


class Single:
    """Đặc trưng đơn điệu tốt nhất (hướng + AUC chọn trên train)."""
    name = "single"

    def fit(self, X, y, w, cols):
        self.cols = cols
        best = (0, 0, 0)
        for k in range(X.shape[1]):
            a = _wauc(y, X[:, k], w)
            if abs(a - 0.5) > best[0]:
                best = (abs(a - 0.5), k, 1 if a >= 0.5 else -1)
        self.k, self.dir = best[1], best[2]
        self.feature = cols[self.k]
        return self

    def score(self, X):
        x = X[:, self.k] * self.dir
        return np.where(np.isnan(x), -1e9, x)


class Pair:
    """Luật AND của 2 điều kiện ngưỡng (đặc trưng, hướng, ngưỡng) tối đa hoá TPR-FPR có trọng số trên train. score nhị phân (0/1)."""
    name = "pair"

    def __init__(self, ntop=25, nthr=15, nsub=60000, seed=0):
        self.ntop, self.nthr, self.nsub, self.seed = ntop, nthr, nsub, seed

    def fit(self, X, y, w, cols):
        rng = np.random.default_rng(self.seed)
        pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]
        if len(neg) > self.nsub:
            neg = rng.choice(neg, self.nsub, replace=False)
        sub = np.r_[pos, neg]
        Xs = X[sub]; ys = y[sub]; ws = w[sub].astype(np.float64)
        # trọng số lấy mẫu lại: âm bị giảm mẫu -> nhân bù
        if len(neg) < (y == 0).sum():
            ws = np.where(ys == 0, ws * ((y == 0).sum() / len(neg)), ws)
        # top đặc trưng theo |AUC-0.5| đơn lẻ
        aucs = np.array([abs(_wauc(ys, Xs[:, k], ws) - 0.5) for k in range(Xs.shape[1])])
        top = np.argsort(-aucs)[: self.ntop]
        conds = []; meta = []
        for k in top:
            x = Xs[:, k]
            qs = np.unique(np.nanquantile(x, np.linspace(0.03, 0.97, self.nthr))) if np.isfinite(x).any() else []
            for t in qs:
                conds.append(x > t); meta.append((k, 1, float(t)))
                conds.append(x < t); meta.append((k, -1, float(t)))
        C = np.column_stack(conds).astype(np.float32)
        wp = ws * (ys == 1); wn = ws * (ys == 0)
        Wp, Wn = wp.sum(), wn.sum()
        TPR = (C.T * wp.astype(np.float32)) @ C / max(Wp, 1e-9)
        FPR = (C.T * wn.astype(np.float32)) @ C / max(Wn, 1e-9)
        J = TPR - FPR
        kf = np.array([m[0] for m in meta])
        J[kf[:, None] == kf[None, :]] = -9               # hai điều kiện phải khác đặc trưng
        i, j = np.unravel_index(np.argmax(J), J.shape)
        self.rule = [(cols[meta[i][0]], meta[i][0], meta[i][1], meta[i][2]), (cols[meta[j][0]], meta[j][0], meta[j][1], meta[j][2])]
        self.J = float(J[i, j])
        return self

    def score(self, X):
        out = np.ones(len(X), bool)
        for _, k, d, t in self.rule:
            out &= (X[:, k] > t) if d == 1 else (X[:, k] < t)
        return out.astype(np.float32)

    def text(self):
        return " AND ".join(f"{n} {'>' if d == 1 else '<'} {t:.4g}" for n, k, d, t in self.rule)


# ----------------------------------------------------------------------------- khung fold + đánh giá
def folds_for(groups, is_train, loo, k=4, seed=0):
    """Gán fold cho từng hàng. loo: mỗi nhóm một fold. Chỉ gán cho nhóm train (hoặc tất cả khi loo); phần còn lại = -1."""
    g = np.asarray(groups)
    fold = np.full(len(g), -1)
    ug = np.unique(g[is_train] if not loo else g)
    if loo:
        mp = {x: i for i, x in enumerate(ug)}
        fold = np.array([mp.get(x, -1) for x in g])
        return fold, len(ug)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ug))
    mp = {x: perm[i] % k for i, x in enumerate(ug)}
    fold = np.array([mp.get(x, -1) if t else -1 for x, t in zip(g, is_train)])
    return fold, k


NEG_CAP = 70_000


def _sub(idx, y, w, seed=0):
    """Giảm mẫu hàng âm (các hàng liên tiếp rất tương quan) xuống NEG_CAP, nhân bù trọng số; giữ toàn bộ dương."""
    pos = idx[y[idx] == 1]; neg = idx[y[idx] != 1]
    if len(neg) <= NEG_CAP:
        return idx, w[idx]
    rng = np.random.default_rng(seed)
    keep = rng.choice(neg, NEG_CAP, replace=False)
    ii = np.r_[pos, keep]
    ww = np.r_[w[pos], w[keep] * (len(neg) / NEG_CAP)]
    return ii, ww


def run_learners(F, cols, y, w, fit_ok, groups, is_train, loo, learners, with_test_model=True):
    """F: DataFrame đặc trưng cho MỌI hàng; y,w nhãn/trọng số (nan ở hàng không dùng để fit); fit_ok: hàng đủ điều kiện fit/đánh giá.
    Trả {tên: điểm cho mọi hàng} (train: OOF, test: mô hình fit trên toàn train; loo: LOO) + mô hình cuối."""
    X = F[cols].to_numpy(np.float32)
    fold, K = folds_for(groups, is_train, loo)
    out = {}; final = {}; fm = {}
    for mk in learners:
        sc = np.full(len(F), np.nan, np.float32)
        for k in range(K):
            tr = fit_ok & is_train & (fold != k) if not loo else fit_ok & (fold != k)
            te = fold == k
            if not te.any() or tr.sum() < 20 or y[tr].sum() < 3:
                continue
            ii, ww = _sub(np.where(tr)[0], y, w)
            m = mk().fit(X[ii], y[ii].astype(int), ww, cols)
            sc[te] = m.score(X[te])
            fm.setdefault(m.name, {})[k] = m
        if not loo:
            trm = fit_ok & is_train
            ii, ww = _sub(np.where(trm)[0], y, w)
            m = mk().fit(X[ii], y[ii].astype(int), ww, cols)
            rest = ~is_train
            if rest.any():
                sc[rest] = m.score(X[rest])
            final[m.name] = m
        else:
            ii, ww = _sub(np.where(fit_ok)[0], y, w)
            m = mk().fit(X[ii], y[ii].astype(int), ww, cols)
            final[m.name] = m
        out[m.name] = sc
    return out, final, dict(fold_models=fm, fold=fold)


def panel_report(F, cols, y, w, fit_ok, is_train, scores, final, loo, imp_rows=15000):
    """JSON báo cáo: AUC/PR-AUC test, importance, cây, luật cặp, tỉ lệ lift giữ lại."""
    te = fit_ok & (~is_train if not loo else np.ones(len(y), bool))
    rep = dict(n_rows=int(fit_ok.sum()), n_pos=int((y[fit_ok] == 1).sum()), n_test_rows=int(te.sum()), n_test_pos=int((y[te] == 1).sum()), loo=bool(loo))
    yt, wt = y[te].astype(int), w[te]
    res = {}
    for nm, sc in scores.items():
        s = sc[te]
        auc = _wauc(yt, s, wt)
        pr = float(average_precision_score(yt, np.nan_to_num(s, nan=-1e9), sample_weight=wt)) if len(np.unique(yt)) > 1 else None
        res[nm] = dict(auc_test=round(auc, 4), pr_auc=None if pr is None else round(pr, 4))
    g = res["gbm"]["auc_test"]
    for nm in res:
        res[nm]["lift_kept_vs_gbm"] = round((res[nm]["auc_test"] - 0.5) / (g - 0.5), 3) if g > 0.505 else None
    # importance hoán vị trên test (mẫu: toàn bộ dương + âm lấy mẫu)
    try:
        rng = np.random.default_rng(0)
        ti = np.where(te)[0]; pos = ti[y[ti] == 1]; neg = ti[y[ti] == 0]
        take = np.r_[rng.choice(pos, min(len(pos), 3000), replace=False), rng.choice(neg, min(len(neg), imp_rows), replace=False)]
        Xt = F[cols].to_numpy(np.float32)[take]
        gb = final["gbm"]
        pi = permutation_importance(gb.m, Xt, y[take].astype(int), scoring="roc_auc", n_repeats=3, random_state=0, sample_weight=w[take])
        o = np.argsort(-pi.importances_mean)[:15]
        res["gbm"]["importance"] = [dict(feature=cols[k], drop_auc=round(float(pi.importances_mean[k]), 4)) for k in o]
    except Exception as e:
        res["gbm"]["importance"] = [dict(error=str(e)[:100])]
    for d in (2, 3, 4):
        nm = f"tree{d}"
        if nm in final:
            res[nm]["rules_text"] = final[nm].text()
    if "pair" in final:
        p = final["pair"]
        res["pair"]["features"] = [r[0] for r in p.rule]; res["pair"]["thresholds"] = [[r[0], ">" if r[2] == 1 else "<", r[3]] for r in p.rule]
        res["pair"]["rule_text"] = p.text()
    if "single" in final:
        res["single"]["feature"] = final["single"].feature; res["single"]["direction"] = int(final["single"].dir)
    rep.update(res)
    return rep


LEARNERS = [GBM, lambda: Tree(2), lambda: Tree(3), lambda: Tree(4), Single, Pair]
