"""Phase 2 — mô phỏng từ luật đã học.

(1) EXIT có điều kiện (Level A): đi từng phút từ fill thật cuối, thoát ở nến đầu tiên điểm số > ngưỡng (ngưỡng chọn trên train theo khớp +-15p).
(2) ADD có điều kiện / mô phỏng đầy đủ: fill đầu thật + add học được + thoát học được (vòng lặp vector hoá, vị thế tính lại sau mỗi add).
(3) ENTRY (Level B): tín hiệu vào từ mô hình entry trên lưới 5m (ngưỡng + cooldown chọn trên train, điểm train = out-of-fold).
(4) LEVEL S: backtest tự chạy (free-running) cả cửa sổ của bot: entry + add + exit học được, không bơm fill thật.
Quy ước nến quyết định i: LAG=1 -> đặc trưng đến nến i-1, khớp tại open nến i; LAG=0 -> khớp tại close nến i (xem disc_panels).
"""
import numpy as np
import pandas as pd

import load
import match
import sim as sim_mod
import families_dca as FD
import disc_panels as DP

MIN = 60_000
FEE_A = 3.5       # bps/chiều, đúng như mô phỏng phase 1 (so sánh công bằng với baseline)
FEE_S = 5.0       # bps/chiều taker cho Level S (theo spec)


# ======================================================================= tiện ích
def first_run(mask, k=1):
    """Chỉ số cuối của đoạn True liên tiếp dài >= k đầu tiên; -1 nếu không có."""
    if k <= 1:
        w = np.flatnonzero(mask)
        return int(w[0]) if len(w) else -1
    c = np.convolve(mask.astype(np.int8), np.ones(k, np.int8), "full")[: len(mask)]
    w = np.flatnonzero(c >= k)
    return int(w[0]) if len(w) else -1


def replay_fills(B):
    """Fill replay theo đúng quy ước families_dca.simulate2: fill đầu = tranche đầu gộp, rồi các fill thô sau tranche đầu."""
    fl = B["fills"]; t_end = B["tranches"][0]["t_last"]
    out = [dict(t=fl[0]["t"], px=fl[0]["px"], notional=B["tranches"][0]["notional"])]
    out += [dict(t=f["t"], px=f["px"], notional=f["notional"]) for f in fl[1:] if f["t"] > t_end]
    return out


def make_S(B_side, fills, t_exit, px_exit, closed, fee_bps):
    """Kết quả sim cho match.basket_row: tất cả fill (t < t_exit) đóng cùng lúc."""
    s = 1 if B_side == "long" else -1
    fee = fee_bps / 1e4
    fl = [f for k, f in enumerate(fills) if k == 0 or f["t"] < t_exit]
    out_f = [dict(t=int(f["t"]), px=float(f["px"]), notional=float(f["notional"]), layer=k) for k, f in enumerate(fl)]
    closes = []; pnl = 0.0
    for k, f in enumerate(fl):
        q = f["notional"] / f["px"]
        closes.append(dict(t=int(t_exit), px=float(px_exit), qty=q, layer=k))
        pnl += q * (px_exit - f["px"]) * s - fee * q * (px_exit + f["px"])
    notional = float(sum(f["notional"] for f in fl))
    return dict(fills=out_f, closes=closes, closed=bool(closed), pnl=pnl, notional=notional, ret=pnl / notional * 100)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float) and (o != o):
        return None
    return o


# ======================================================================= (1) EXIT có điều kiện từ điểm số panel
class ExitWalk:
    """Chỉ mục hàng 'sau fill cuối' theo basket để đi nhanh. meta đã sắp theo (bid, i)."""

    def __init__(self, meta, ctx, lag):
        self.meta = meta; self.lag = lag; self.ctx = ctx
        m = meta[meta.after_last == 1]
        self.rows = m.index.values
        bids = m.bid.values
        cut = np.flatnonzero(np.r_[True, bids[1:] != bids[:-1], True])
        self.slices = {int(bids[a]): (int(self.rows[a]), int(self.rows[b - 1]) + 1) for a, b in zip(cut[:-1], cut[1:])}
        self.i = meta.i.values; self.tau = meta.tau.values

    def first_exit(self, bid, score, thr, k=1):
        """Chỉ số hàng panel (tuyệt đối) của nến thoát hoặc -1."""
        a, b = self.slices[bid]
        sl = score[a:b]
        m = np.nan_to_num(sl, nan=-1e18) > thr
        r = first_run(m, k)
        return -1 if r < 0 else a + r


def exit_times(walk, score, thr, bids, k=1):
    """Thời điểm thoát sim (ms, đầu nến quyết định; lag0 +60s) hoặc nan nếu không thoát; vector theo bids."""
    out = np.full(len(bids), np.nan)
    for n, b in enumerate(bids):
        r = walk.first_exit(b, score, thr, k)
        if r >= 0:
            out[n] = walk.tau[r] + (MIN if walk.lag == 0 else 0)
    return out


def choose_exit_thr(walk, score, bids, t1_real, k=1, qs=None):
    """Ngưỡng tối đa hoá khớp +-15p trên TRAIN (điểm out-of-fold). Trả (thr, match15, bảng)."""
    a = np.concatenate([score[walk.slices[b][0]: walk.slices[b][1]] for b in bids])
    a = a[~np.isnan(a) & (a > -1e8)]
    if len(a) == 0:
        return None, 0.0, []
    uq = np.unique(a)
    if len(uq) <= 40:                                            # điểm rời rạc (cây nông / luật cặp): thử giữa các giá trị
        cands = (uq[:-1] + uq[1:]) / 2 if len(uq) > 1 else uq - 1e-9
    else:
        qs = qs if qs is not None else np.r_[np.linspace(0.5, 0.99, 25), 0.995, 0.998, 0.999, 0.9995, 0.9999]
        cands = np.unique(np.quantile(a, qs))
    best = (None, -1.0); tab = []
    for th in cands:
        t = exit_times(walk, score, th, bids, k)
        m15 = float(np.mean(np.abs(t - t1_real) <= 15 * MIN))      # nan -> False
        tab.append((float(th), round(m15, 4)))
        if m15 > best[1]:
            best = (float(th), m15)
    return best[0], best[1], tab


def exit_rows(walk, score, thr, baskets, P_lag, k=1, fee=FEE_A):
    """Dựng danh sách basket_row (kèm sim) cho các basket với luật thoát học được; fill thật replay."""
    rows = []
    for B in baskets:
        b = B["id"]
        if b not in walk.slices:
            continue
        a = DP.sym_matrix(B["sym"])[2]
        fills = replay_fills(B)
        th = thr[DP.sym_class(B["sym"])] if isinstance(thr, dict) else thr
        r = walk.first_exit(b, score, th, k)
        i_last = DP.bar_of(a, B["t1"] + 60 * MIN)
        if r >= 0:
            i = int(walk.i[r])
            if walk.lag == 1:
                t_ex, px = int(a["t"][i]), float(a["o"][i])
            else:
                t_ex, px = int(a["t"][i]) + MIN, float(a["c"][i])
            S = make_S(B["side"], fills, t_ex, px, True, fee)
        else:
            S = make_S(B["side"], fills, int(a["t"][min(i_last, len(a["t"]) - 1)]), float(a["c"][min(i_last, len(a["t"]) - 1)]), False, fee)
        rows.append(match.basket_row(B, S))
    return rows


# ======================================================================= baselines phase 1 (null time-stop, shuffled TP) với CÙNG code
def baseline_null(train, test):
    """Thời gian giữ cố định (replay fill thật): bội của trung vị thời gian giữ train, chọn bội theo khớp +-15p trên train."""
    hold = np.median([(B["t1"] - B["t0"]) / MIN for B in train])
    best = None
    for kmul in (0.25, 0.5, 1, 2, 4):
        p = dict(replay=1, max_layers=40, max_hold_bars=max(1, int(hold * kmul)))
        rows = [match.basket_row(B, FD.simulate2(B, p)) for B in train]
        m = match.level_a(rows)
        if best is None or (m.get("close_match_15") or 0) > best[0]:
            best = (m.get("close_match_15") or 0, p)
    rows = [match.basket_row(B, FD.simulate2(B, best[1])) for B in test]
    return match.level_a(rows), best[1]


def baseline_shuffled_tp(train, test, reps=20, seed=0):
    """TP % mỗi tầng rút ngẫu nhiên từ phân phối train (theo mã), replay fill thật."""
    by, allv = {}, []
    for B in train:
        s = 1 if B["side"] == "long" else -1
        for c in B["closes"]:
            f = B["fills"][c["fill"]]; r = (c["px"] / f["px"] - 1) * s * 100
            if r > 0.02:
                by.setdefault(B["sym"], []).append(r); allv.append(r)
    if not allv:
        return None
    rng = np.random.default_rng(seed); out = []
    for _ in range(reps):
        rows = []
        for B in test:
            pool = by.get(B["sym"]) if len(by.get(B["sym"], [])) >= 8 else allv
            p = dict(replay=1, max_layers=40, tp_pct=float(rng.choice(pool)), tp_mode=1)
            rows.append(match.basket_row(B, FD.simulate2(B, p)))
        out.append(match.level_a(rows))
    f = lambda k: [m.get(k) or 0 for m in out]
    return {k: dict(mean=round(float(np.mean(f(k))), 2), p95=round(float(np.percentile(f(k), 95)), 2)) for k in ("close_match_5", "close_match_15", "close_match_60", "pnl_corr", "pnl_sign_agree")} | dict(reps=reps)


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n; d = 1 + z * z / n
    c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100 * (c - h) / d, 2), round(100 * (c + h) / d, 2)


# ======================================================================= (2) đường đi động: add + exit học được
class Engine:
    """Sinh đường đi 1 basket: fill đầu cho trước -> add học được -> thoát học được. Vị thế tính lại sau mỗi add."""

    def __init__(self, ctx, exit_cols, exit_fn, thr_exit, add_cols=None, add_fn=None, thr_add=None, lag=1, k_exit=1, k_add=1, add_gap_min=15,
                 max_layers=24, add_ratio=1.0, fee=FEE_A):
        self.ctx = ctx
        self.cols = list(dict.fromkeys(list(exit_cols) + list(add_cols or [])))      # hợp 2 tập cột
        self.ex_idx = [self.cols.index(c) for c in exit_cols]
        self.ad_idx = [self.cols.index(c) for c in (add_cols or [])]
        self.exit_fn = exit_fn; self.thr_exit = thr_exit
        self.add_fn = add_fn; self.thr_add = thr_add; self.lag = lag; self.k_exit = k_exit; self.k_add = k_add
        self.gap = add_gap_min; self.maxL = max_layers; self.ratio = add_ratio; self.fee = fee
        self.pos_cols = set(DP.POS_NAMES)

    def path(self, sym, side_s, t0, px0, N0, i_end, bid=-1):
        """Trả dict(fills[{t,px,notional}], t_exit, px_exit, closed, forced). t0: thời điểm fill đầu (ms); i_end: nến cuối cho phép."""
        names, X, a = DP.sym_matrix(sym)
        s = side_s; lag = self.lag
        cl = DP.sym_class(sym)
        th_ex = self.thr_exit[cl] if isinstance(self.thr_exit, dict) else self.thr_exit
        th_ad = self.thr_add[cl] if isinstance(self.thr_add, dict) else self.thr_add
        i_f0 = DP.bar_of(a, t0)
        ii = np.arange(i_f0 + 1, i_end + 1)
        if len(ii) == 0 or ii[0] - lag < 0:
            return None
        jr = ii - lag
        Bv = dict(sym=sym, id=-1)
        st = DP.static_block(self.ctx, Bv, a, names, X, s, jr, with_book=False)
        stc = {c: st[c].to_numpy(np.float32) for c in self.cols if c in st.columns}
        ft = [t0]; fp = [px0]; fn = [N0]
        r0 = 0
        while r0 < len(ii):
            pos = DP.pos_block(a, names, X, s, jr[r0:], np.array(ft, np.int64), np.array(fp), np.array(fn))
            cols_arr = []
            for c in self.cols:
                v = pos[c] if c in pos else stc[c][r0:]
                cols_arr.append(v)
            Xm = np.column_stack(cols_arr).astype(np.float32)
            Xm[~np.isfinite(Xm)] = np.nan
            es = self.exit_fn(Xm[:, self.ex_idx], sym)
            k_ex = first_run(np.nan_to_num(es, nan=-1e18) > th_ex, self.k_exit)
            k_ad = -1
            if self.add_fn is not None and len(ft) < self.maxL:
                ad = self.add_fn(Xm[:, self.ad_idx], sym)
                m = (np.nan_to_num(ad, nan=-1e18) > th_ad) & (pos["mins_last"] > self.gap)
                k_ad = first_run(m, self.k_add)
            if k_ad >= 0 and (k_ex < 0 or k_ad < k_ex):
                i = int(ii[r0 + k_ad])
                if lag == 1:
                    ft.append(int(a["t"][i])); fp.append(float(a["o"][i]))
                else:
                    ft.append(int(a["t"][i]) + MIN); fp.append(float(a["c"][i]))
                fn.append(N0 * self.ratio)
                r0 += k_ad + 1
                continue
            if k_ex >= 0:
                i = int(ii[r0 + k_ex])
                t_ex, px = (int(a["t"][i]), float(a["o"][i])) if lag == 1 else (int(a["t"][i]) + MIN, float(a["c"][i]))
                return dict(fills=[dict(t=t, px=p, notional=n) for t, p, n in zip(ft, fp, fn)], t_exit=t_ex, px_exit=px, closed=True)
            break
        i = int(ii[-1])
        return dict(fills=[dict(t=t, px=p, notional=n) for t, p, n in zip(ft, fp, fn)], t_exit=int(a["t"][i]) + MIN, px_exit=float(a["c"][i]), closed=False)


def sim_basket_full(eng, B, fee=FEE_A, horizon_min=60):
    """Mô phỏng đầy đủ có điều kiện theo fill đầu thật: add học được + thoát học được."""
    a = DP.sym_matrix(B["sym"])[2]
    s = 1 if B["side"] == "long" else -1
    i_end = min(len(a["t"]) - 1, DP.bar_of(a, B["t1"] + horizon_min * MIN))
    f0 = B["fills"][0]
    r = eng.path(B["sym"], s, f0["t"], f0["px"], B["tranches"][0]["notional"], i_end, B["id"])
    if r is None:
        return None
    return make_S(B["side"], r["fills"], r["t_exit"], r["px_exit"], r["closed"], fee)


# ======================================================================= (3) ENTRY: điểm trên lưới 5m + tín hiệu
def grid_scores(P, cols, models, oof_fold_models=None, fold_of_block=None, split_t=None, lo=None, hi=None, syms=None, block_ms=2 * 86400_000, names_to_run=("gbm",)):
    """Điểm entry trên TOÀN lưới 5m theo (mã, chiều). Train (tau<split_t) dùng mô hình out-of-fold theo khối thời gian; test dùng mô hình cuối.
    Trả {(sym, s): (tau, {tên: điểm float32})}."""
    ctx = P["ctx"]; out = {}
    G = 5 * MIN
    syms = syms or sorted({B["sym"] for B in ctx.baskets})
    for sym in syms:
        sm = DP.sym_matrix(sym)
        if sm is None:
            continue
        names, X, a = sm
        first = max(lo, a["t"][0] + 1500 * MIN); last = min(hi, a["t"][-1])
        grid = np.arange(int(np.ceil(first / G)) * G, int(last // G) * G + 1, G, dtype=np.int64)
        jr = np.searchsorted(a["t"], grid - MIN)
        ok = (jr >= 0) & (jr < len(a["t"])) & (a["t"][np.minimum(jr, len(a["t"]) - 1)] == grid - MIN)
        grid = grid[ok]; jr = jr[ok]
        if len(grid) == 0:
            continue
        for sd in (1, -1):
            st = DP.static_block(ctx, dict(sym=sym, id=-1), a, names, X, sd, jr, with_book=False)
            Xm = st[cols].to_numpy(np.float32)
            res = {}
            for nm in names_to_run:
                sc = np.empty(len(grid), np.float32)
                tr = grid < split_t if split_t is not None else np.zeros(len(grid), bool)
                if (~tr).any():
                    sc[~tr] = models[nm].score(Xm[~tr])
                if tr.any():
                    blk = (grid[tr] // block_ms)
                    fo = np.array([fold_of_block.get(int(b), 0) for b in blk])
                    tmp = np.empty(tr.sum(), np.float32)
                    for k in np.unique(fo):
                        mm = oof_fold_models[nm].get(int(k)) or models[nm]
                        idx = fo == k
                        tmp[idx] = mm.score(Xm[tr][idx])
                    sc[tr] = tmp
                res[nm] = sc
            out[(sym, sd)] = (grid, res)
    return out


def signals_from(tau, sc, thr, cooldown_ms):
    """Tín hiệu: điểm > ngưỡng, bỏ qua trong cooldown sau mỗi tín hiệu."""
    idx = np.flatnonzero(sc > thr)
    out = []; last = -1 << 62
    for i in idx:
        if tau[i] - last >= cooldown_ms:
            out.append(tau[i]); last = tau[i]
    return np.array(out, np.int64)


def rate_match_thresholds(gs, nm, lo, hi, counts, cool_min, factor=1.0):
    """Ngưỡng entry THEO (mã, chiều) sao cho số tín hiệu trên cửa sổ train [lo,hi) ~ số basket thật của (mã, chiều) đó (x factor):
    chọn top-N điểm cao nhất, các điểm cách nhau >= cooldown (NMS tham lam). (mã,chiều) không có basket thật trong train -> ngưỡng = +inf."""
    out = {}
    for (sym, sd), (tau, res) in gs.items():
        n = int(round(counts.get((sym, "long" if sd == 1 else "short"), 0) * factor))
        if n <= 0:
            out[(sym, sd)] = np.inf; continue
        m = (tau >= lo) & (tau < hi)
        t = tau[m]; sc = res[nm][m]
        order = np.argsort(-sc)
        picked = []
        for i in order:
            if len(picked) >= n:
                break
            if all(abs(t[i] - t[j]) >= cool_min * MIN for j in picked):
                picked.append(i)
        out[(sym, sd)] = float(sc[picked[-1]]) - 1e-9 if picked else np.inf
    return out


def entry_levelb(P, gs, nm, thr, cool_min, lo, hi, hour_hist, reps=100, seed=0, act_lo=None):
    """Level B trên [lo, hi): recall/precision +-15/60 so với baseline ngẫu nhiên + khớp giờ."""
    split_ok = lambda t: (t >= lo) & (t < hi)
    act = {}
    for B in P["baskets"]:
        if lo <= B["t0"] < hi:
            act.setdefault((B["sym"], B["side"]), []).append(B["t0"])
    act = {k: np.array(sorted(v), np.int64) for k, v in act.items()}
    sig = {}
    for (sym, sd), (tau, res) in gs.items():
        m = split_ok(tau)
        if not m.any():
            continue
        th = thr.get((sym, sd), np.inf) if isinstance(thr, dict) else thr
        s_ = signals_from(tau[m], res[nm][m], th, cool_min * MIN)
        if len(s_):
            sig[(sym, "long" if sd == 1 else "short")] = s_
    return match.level_b(act, sig, lo, hi, reps=reps, seed=seed, hour_hist=hour_hist), sig


# ======================================================================= (4) LEVEL S: free-running
def real_max_concurrent(baskets):
    ev = sorted([(b["t0"], 1) for b in baskets] + [(b["t1"], -1) for b in baskets], key=lambda x: (x[0], x[1]))
    cur = mx = 0
    for _, d in ev:
        cur += d; mx = max(mx, cur)
    return mx


def sizing_from_train(train, trades_train):
    """Notional fill đầu theo lớp mã (trung vị), tỉ lệ notional add (trung vị tranche k / tranche 0), đòn bẩy theo mã (trung vị)."""
    n0 = {}; n0s = {}
    for B in train:
        n0.setdefault(DP.sym_class(B["sym"]), []).append(B["tranches"][0]["notional"])
        n0s.setdefault(B["sym"], []).append(B["tranches"][0]["notional"])
    allm = float(np.median([v for l in n0.values() for v in l]))
    n0 = {k: float(np.median(v)) for k, v in n0.items()}
    n0s = {k: float(np.median(v)) for k, v in n0s.items()}
    ratios = [g["notional"] / B["tranches"][0]["notional"] for B in train for g in B["tranches"][1:]]
    lev = {}
    for t in trades_train:
        lev.setdefault(t["sym"], []).append(t["lev"])
    levall = float(np.median([x for v in lev.values() for x in v]))
    return dict(n0=n0, n0_sym=n0s, n0_all=allm, add_ratio=float(np.median(ratios)) if ratios else 1.0,
                lev={k: float(np.median(v)) for k, v in lev.items()}, lev_all=levall)


def free_run(P, eng, gs, nm, thr_entry, cool_min, lo, hi, sizing, max_conc, max_hold_min, fee=FEE_S):
    """Backtest tự chạy: tín hiệu entry (điểm lưới) -> Engine.path (add + exit học được) cho tới khi hết cửa sổ. Trả list trade (schema bots.json) + info."""
    ctx = P["ctx"]
    sig = []
    for (sym, sd), (tau, res) in gs.items():
        m = (tau >= lo) & (tau < hi)
        if m.any():
            th = thr_entry.get((sym, sd), np.inf) if isinstance(thr_entry, dict) else thr_entry
            for t in signals_from(tau[m], res[nm][m], th, cool_min * MIN):
                sig.append((int(t), sym, sd))
    sig.sort()
    open_until = {}; ends = []
    trades = []; n_forced = 0; n_long_hold = 0; n_skip_conc = 0; n_skip_own = 0; n_baskets = 0
    for t, sym, sd in sig:
        if open_until.get((sym, sd), -1) > t:
            n_skip_own += 1; continue
        ends = [e for e in ends if e > t]
        if len(ends) >= max_conc:
            n_skip_conc += 1; continue
        sm = DP.sym_matrix(sym)
        a = sm[2]
        i0 = int(np.searchsorted(a["t"], t))
        if i0 >= len(a["t"]) - 2 or a["t"][i0] != t:
            continue
        cls = DP.sym_class(sym)
        N0 = sizing["n0_sym"].get(sym, sizing["n0"].get(cls, sizing["n0_all"]))
        i_end = min(len(a["t"]) - 1, DP.bar_of(a, min(hi, t + max_hold_min * MIN)))
        px0 = float(a["o"][i0]) if eng.lag == 1 else float(a["c"][i0])
        r = eng.path(sym, sd, t, px0, N0, i_end)
        if r is None:
            continue
        n_baskets += 1
        side = "long" if sd == 1 else "short"
        lev = sizing["lev"].get(sym, sizing["lev_all"])
        if not r["closed"]:
            n_forced += 1
        t_ex = r["t_exit"]; px_ex = r["px_exit"]
        open_until[(sym, sd)] = t_ex; ends.append(t_ex)
        if (t_ex - t) > 8 * 3600_000:
            n_long_hold += 1
        for k, f in enumerate(r["fills"]):
            q = f["notional"] / f["px"]
            gross = q * (px_ex - f["px"]) * sd
            pnl = gross - fee / 1e4 * q * (px_ex + f["px"])
            mg = f["notional"] / lev
            trades.append(dict(sym=sym, side=side, lev=lev, o=int(f["t"]), c=int(t_ex), po=f["px"], pc=px_ex, pnl=round(pnl, 2), pr=round(pnl / mg * 100, 1), mg=round(mg, 2),
                               forced=not r["closed"]))
    info = dict(n_signals=len(sig), n_baskets=n_baskets, n_forced_close=n_forced, n_hold_gt8h=n_long_hold, skipped_own_open=n_skip_own, skipped_concurrency=n_skip_conc,
                funding="không áp dụng (không có dữ liệu funding); số basket giữ >8h ghi ở n_hold_gt8h")
    return trades, info


def free_run_replay_entries(P, eng, baskets, lo, hi, sizing, max_hold_min, fee=FEE_S):
    """Biến thể Level S: fill ĐẦU THẬT được bơm vào (thời điểm, giá, notional tranche đầu), add + thoát học được chạy tự do.
    Tách lỗi entry khỏi lỗi add/exit trong bảng thống kê."""
    trades = []; n_forced = 0
    for B in baskets:
        if not (lo <= B["t0"] <= hi):
            continue
        sm = DP.sym_matrix(B["sym"]); a = sm[2]
        sd = 1 if B["side"] == "long" else -1
        i_end = min(len(a["t"]) - 1, DP.bar_of(a, min(hi, B["t0"] + max_hold_min * MIN)))
        f0 = B["fills"][0]
        r = eng.path(B["sym"], sd, f0["t"], f0["px"], B["tranches"][0]["notional"], i_end)
        if r is None:
            continue
        n_forced += (not r["closed"])
        lev = sizing["lev"].get(B["sym"], sizing["lev_all"])
        t_ex, px_ex = r["t_exit"], r["px_exit"]
        for f in r["fills"]:
            q = f["notional"] / f["px"]
            pnl = q * (px_ex - f["px"]) * sd - fee / 1e4 * q * (px_ex + f["px"])
            mg = f["notional"] / lev
            trades.append(dict(sym=B["sym"], side=B["side"], lev=lev, o=int(f["t"]), c=int(t_ex), po=f["px"], pc=px_ex, pnl=round(pnl, 2), pr=round(pnl / mg * 100, 1), mg=round(mg, 2)))
    return trades, dict(n_baskets=len({(t["sym"], t["side"], t["o"]) for t in trades if True}), n_forced_close=n_forced)
