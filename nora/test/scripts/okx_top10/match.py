"""Chỉ số so khớp actual vs simulated.

LEVEL A (điều kiện hoá theo fill đầu thật; chỉ đo luật thực thi: add, thoát, PnL):
  adds   : với mỗi add THẬT thứ k (k>=1) -> khớp nếu sim có add thứ k trong +-5 phút VÀ giá lệch <= 10 bps.
           add_time_match = % add thật có sim add k trong +-5 phút; add_match = % khớp cả thời gian lẫn giá;
           add_match_any = như add_match nhưng cho phép ghép với BẤT KỲ sim add (không cần cùng chỉ số k);
           add_px_err_bps median/p90 = |px_sim_k/px_thật_k-1| (bps) trên các add có sim add k trong +-5 phút (không điều kiện giá).
           layer_eq = % basket có số fill sim == số fill thật.
  exits  : thời điểm đóng basket = lần đóng CUỐI. sim_close_t = lần đóng cuối của sim (nếu sim chưa đóng hết trong horizon
           = t1 thật + 60 phút thì tính là KHÔNG khớp). close_match_{5,15,60} = % basket có |dt| <= 5/15/60 phút.
           close_px_err_bps = |px đóng sim / px đóng cuối thật - 1| (median/p90) trên basket sim đã đóng.
           layer_close_match5 = với basket THẬT đóng từng tầng lệch giờ (>1 mốc đóng): % tầng có sim đóng tầng đó +-5 phút.
  pnl    : ret = PnL ròng / tổng notional (%). Thật = sum(pnl)/sum(mg*lev); sim = pnl sim (trừ phí 3.5 bps/chiều)/notional sim.
           sign_agree = % basket cùng dấu; corr = Pearson(ret thật, ret sim); med_abs_err_pp = median |ret_sim-ret_thật| (điểm %);
           corr_usdt = Pearson PnL USDT; cum curve = cộng dồn theo thời điểm đóng thật (cả 2 chuỗi).
  tranche: các fill liên tiếp cách <=15 phút gộp thành 1 tranche (load.collapse); chỉ số tiền tố tr_ (tr_add_match, tr_layer_eq...) tính trên
           tranche = tầng DCA thật sự (bỏ các fill chia nhỏ của cùng 1 lệnh vào). Chỉ số không tiền tố tính trên fill thô đúng như đặc tả.
  score  = trung bình(close_match_15, tr_layer_eq, tr_add_match) -> chọn tham số trên TRAIN (xem `score()`).
"""
import numpy as np

MIN = 60_000


def _pct(x):
    return None if x is None else round(float(x) * 100, 2)


def _q(a, q):
    a = np.asarray(a, float)
    return None if len(a) == 0 else round(float(np.percentile(a, q)), 2)


def _tr(fills):
    from load import collapse
    return [dict(t=g["t"], px=g["px"]) for g in collapse(fills)]


def basket_row(B, S):
    """Một dòng so sánh cho basket B (actual) với kết quả sim S (hoặc None)."""
    act_adds = [dict(t=f["t"], px=f["px"]) for f in B["fills"][1:]]
    last_t = B["t1"]
    cl_last = [c for c in B["closes"] if abs(c["t"] - last_t) <= 2000]
    act_close_px = sum(c["px"] * c["qty"] for c in cl_last) / sum(c["qty"] for c in cl_last)
    row = dict(id=B["id"], sym=B["sym"], side=B["side"], lev=B["lev"], t0=B["t0"], t1=B["t1"], n_act=len(B["fills"]),
               act_ret=round(B["ret"], 4), act_pnl=round(B["pnl"], 2), act_notional=round(B["notional"], 1),
               act_adds=[dict(t=a["t"], px=round(a["px"], 6)) for a in act_adds],
               act_tr_adds=[dict(t=a["t"], px=round(a["px"], 6)) for a in _tr(B["fills"])[1:]], n_act_tr=len(B["tranches"]),
               act_close=dict(t=last_t, px=round(act_close_px, 6)),
               act_closes=[dict(t=c["t"], px=round(c["px"], 6), layer=c["fill"]) for c in B["closes"]],
               staged=len({round(c["t"] / 2000) for c in B["closes"]}) > 1)
    if S is None:
        row["sim"] = None
        return row
    sim_adds = [dict(t=f["t"], px=f["px"]) for f in S["fills"][1:]]
    sim_close_t = max(c["t"] for c in S["closes"])
    last_c = [c for c in S["closes"] if c["t"] == sim_close_t]
    sim_close_px = sum(c["px"] * c["qty"] for c in last_c) / sum(c["qty"] for c in last_c)
    row.update(n_sim=len(S["fills"]), sim_ret=round(S["ret"], 4), sim_pnl=round(S["pnl"], 2), sim_closed=S["closed"],
               sim_adds=[dict(t=a["t"], px=round(a["px"], 6)) for a in sim_adds],
               sim_tr_adds=[dict(t=a["t"], px=round(a["px"], 6)) for a in _tr(S["fills"])[1:]], n_sim_tr=len(_tr(S["fills"])),
               sim_close=dict(t=int(sim_close_t), px=round(sim_close_px, 6)),
               sim_closes=[dict(t=c["t"], px=round(c["px"], 6), layer=c["layer"]) for c in S["closes"]])
    return row


def _add_stats(rows, akey="act_adds", skey="sim_adds", pre=""):
    tm = pm = pa = n = 0
    errs = []
    for r in rows:
        if r.get("sim") is False:
            continue
        sa = r.get(skey, [])
        for k, a in enumerate(r[akey]):
            n += 1
            if k < len(sa) and abs(sa[k]["t"] - a["t"]) <= 5 * MIN:
                tm += 1
                e = abs(sa[k]["px"] / a["px"] - 1) * 1e4
                errs.append(e)
                if e <= 10:
                    pm += 1
            if any(abs(x["t"] - a["t"]) <= 5 * MIN and abs(x["px"] / a["px"] - 1) * 1e4 <= 10 for x in sa):
                pa += 1
    return {pre + "n_actual_adds": n, pre + "add_time_match": _pct(tm / n) if n else None, pre + "add_match": _pct(pm / n) if n else None,
            pre + "add_match_any": _pct(pa / n) if n else None, pre + "add_px_err_bps_med": _q(errs, 50), pre + "add_px_err_bps_p90": _q(errs, 90)}


def level_a(rows):
    """rows: danh sách basket_row (đã gồm sim). Trả dict chỉ số."""
    ok = [r for r in rows if "sim_ret" in r]
    out = dict(n_baskets=len(rows), n_simulated=len(ok))
    if not ok:
        return out
    out.update(_add_stats(ok))
    out.update(_add_stats(ok, "act_tr_adds", "sim_tr_adds", "tr_"))
    out["layer_eq"] = _pct(np.mean([r["n_act"] == r["n_sim"] for r in ok]))
    out["tr_layer_eq"] = _pct(np.mean([r["n_act_tr"] == r["n_sim_tr"] for r in ok]))
    out["n_sim_layers_mean"] = round(float(np.mean([r["n_sim"] for r in ok])), 2)
    out["n_act_layers_mean"] = round(float(np.mean([r["n_act"] for r in ok])), 2)
    dt = np.array([abs(r["sim_close"]["t"] - r["act_close"]["t"]) / MIN if r["sim_closed"] else np.inf for r in ok])
    for m in (5, 15, 60):
        out[f"close_match_{m}"] = _pct(np.mean(dt <= m))
    out["sim_closed_pct"] = _pct(np.mean([r["sim_closed"] for r in ok]))
    pe = [abs(r["sim_close"]["px"] / r["act_close"]["px"] - 1) * 1e4 for r in ok if r["sim_closed"]]
    out["close_px_err_bps_med"] = _q(pe, 50); out["close_px_err_bps_p90"] = _q(pe, 90)
    # đóng từng tầng
    lm = ln = 0
    lerr = []
    for r in ok:
        if not r["staged"]:
            continue
        sc = {c["layer"]: c for c in r["sim_closes"]}
        for c in r["act_closes"]:
            ln += 1
            s = sc.get(c["layer"])
            if s is not None and r["sim_closed"] and abs(s["t"] - c["t"]) <= 5 * MIN:
                lm += 1
                lerr.append(abs(s["px"] / c["px"] - 1) * 1e4)
    out["layer_close_n"] = ln; out["layer_close_match5"] = _pct(lm / ln) if ln else None
    out["layer_close_px_err_bps_med"] = _q(lerr, 50)
    ar = np.array([r["act_ret"] for r in ok]); sr = np.array([r["sim_ret"] for r in ok])
    out["pnl_sign_agree"] = _pct(np.mean(np.sign(ar) == np.sign(sr)))
    out["pnl_corr"] = round(float(np.corrcoef(ar, sr)[0, 1]), 3) if len(ok) > 2 and sr.std() > 0 else None
    out["pnl_med_abs_err_pp"] = round(float(np.median(np.abs(ar - sr))), 3)
    ap = np.array([r["act_pnl"] for r in ok]); sp = np.array([r["sim_pnl"] for r in ok])
    out["pnl_corr_usdt"] = round(float(np.corrcoef(ap, sp)[0, 1]), 3) if len(ok) > 2 and sp.std() > 0 else None
    out["act_pnl_sum"] = round(float(ap.sum()), 0); out["sim_pnl_sum"] = round(float(sp.sum()), 0)
    out["act_win_pct"] = _pct(np.mean(ar > 0)); out["sim_win_pct"] = _pct(np.mean(sr > 0))
    out["score"] = round(score(out), 4)
    return out


def score(m):
    """Điểm chọn tham số trên TRAIN = trung bình của: close_match_15, tr_layer_eq (số tranche bằng nhau), tr_add_match (nếu có add tranche)."""
    parts = [m.get("close_match_15") or 0, m.get("tr_layer_eq") or 0]
    if m.get("tr_add_match") is not None:
        parts.append(m["tr_add_match"])
    return float(np.mean(parts)) / 100.0


def cum_curve(rows):
    """Đường PnL cộng dồn theo thời điểm đóng thật: [[t1, cum_act, cum_sim], ...]."""
    ok = sorted([r for r in rows if "sim_ret" in r], key=lambda r: r["t1"])
    ca = cs = 0.0
    out = []
    for r in ok:
        ca += r["act_pnl"]; cs += r["sim_pnl"]
        out.append([r["t1"], round(ca, 1), round(cs, 1)])
    return out


# ---------------------------------------------------------------- LEVEL B (vào lệnh, không điều kiện hoá)
H = 3_600_000
DAY = 24 * H


def _hits(a, b, tol):
    """bool theo từng phần tử của a: có phần tử b trong +-tol."""
    if len(a) == 0:
        return np.zeros(0, bool)
    if len(b) == 0:
        return np.zeros(len(a), bool)
    i = np.searchsorted(b, a)
    d = np.full(len(a), np.inf)
    ok = i < len(b); d[ok] = np.abs(b[i[ok]] - a[ok])
    ok = i > 0; d[ok] = np.minimum(d[ok], np.abs(b[i[ok] - 1] - a[ok]))
    return d <= tol


def _pr(act, sig, tol):
    """act/sig: dict key->mảng thời gian. Trả (recall, precision, n_act, n_sig)."""
    na = ns = ha = hs = 0
    for k in set(act) | set(sig):
        a = act.get(k, np.zeros(0, np.int64)); s = sig.get(k, np.zeros(0, np.int64))
        na += len(a); ns += len(s)
        ha += _hits(a, s, tol).sum(); hs += _hits(s, a, tol).sum()
    _pr.hits = (int(ha), int(hs))
    return (ha / na if na else 0.0), (hs / ns if ns else 0.0), na, ns


def _rand_like(sig, lo, hi, rng, hour_hist=None):
    """Cùng số tín hiệu theo (mã, chiều), thời điểm ngẫu nhiên đều trong [lo,hi]; nếu hour_hist: giờ VN lấy theo phân bố actual."""
    out = {}
    for k, s in sig.items():
        n = len(s)
        if n == 0:
            out[k] = np.zeros(0, np.int64); continue
        u = rng.uniform(lo, hi, n)
        if hour_hist is not None:
            day = np.floor((u + 7 * H) / DAY) * DAY - 7 * H
            hr = rng.choice(24, size=n, p=hour_hist)
            u = day + hr * H + rng.uniform(0, H, n)
            u = np.clip(u, lo, hi)
        out[k] = np.sort(u.astype(np.int64))
    return out


def level_b(act, sig, lo, hi, reps=200, seed=0, tols=(15, 60), hour_hist=None):
    """act/sig: {(sym,side): mảng ms}. Chỉ số: recall/precision tại +-15, +-60 phút; baseline ngẫu nhiên (đều theo thời gian) và
    ngẫu nhiên khớp phân bố giờ VN của actual; mỗi baseline báo mean và p95 qua `reps` lần rút."""
    out = {}
    for m in tols:
        r, p, na, ns = _pr(act, sig, m * MIN)
        out[f"recall_{m}"] = round(r * 100, 2); out[f"precision_{m}"] = round(p * 100, 2)
        out[f"hits_recall_{m}"], out[f"hits_precision_{m}"] = _pr.hits
    out["n_actual_starts"] = na; out["n_sim_starts"] = ns
    rng = np.random.default_rng(seed)
    for name, hh in (("rand", None), ("rand_hour", hour_hist)):
        if name == "rand_hour" and hh is None:
            continue
        res = {m: ([], []) for m in tols}
        for _ in range(reps):
            rs = _rand_like(sig, lo, hi, rng, hh)
            for m in tols:
                r, p, _, _ = _pr(act, rs, m * MIN)
                res[m][0].append(r); res[m][1].append(p)
        for m in tols:
            for j, nm in enumerate(("recall", "precision")):
                v = np.array(res[m][j]) * 100
                out[f"{name}_{nm}_{m}_mean"] = round(float(v.mean()), 2); out[f"{name}_{nm}_{m}_p95"] = round(float(np.percentile(v, 95)), 2)
    # kết luận: chỉ "vượt baseline" khi cả recall và precision (+-15) > p95 của cả 2 baseline
    ks = [n for n in ("rand", "rand_hour") if f"{n}_recall_15_p95" in out]
    out["above_baseline_15"] = bool(all(out["recall_15"] > out[f"{n}_recall_15_p95"] and out["precision_15"] > out[f"{n}_precision_15_p95"] for n in ks))
    out["lift_recall_15"] = round(out["recall_15"] / max(1e-9, out[f"{ks[-1]}_recall_15_mean"]), 2)
    out["lift_precision_15"] = round(out["precision_15"] / max(1e-9, out[f"{ks[-1]}_precision_15_mean"]), 2)
    # 'khớp' thật sự chỉ khi VƯỢT p95 baseline VÀ lift >= 3 VÀ recall15 >= 30%; còn lại là yếu/không
    if not out["above_baseline_15"]:
        out["strength"] = "không vượt baseline"
    elif out["lift_recall_15"] >= 3 and out["lift_precision_15"] >= 3 and out["recall_15"] >= 30:
        out["strength"] = "khớp"
    else:
        out["strength"] = "vượt baseline nhưng yếu (recall15 %.1f%% = %d/%d)" % (out["recall_15"], out["hits_recall_15"], out["n_actual_starts"])
    return out


def f1_excess(m):
    """Tiêu chí chọn luật trên TRAIN: F1(+-15) trừ F1 kỳ vọng của baseline giờ-khớp/đều (xấp xỉ qua mean recall/precision)."""
    def f1(r, p):
        return 0 if r + p == 0 else 2 * r * p / (r + p)
    k = "rand_hour" if "rand_hour_recall_15_mean" in m else "rand"
    return f1(m["recall_15"], m["precision_15"]) - f1(m[f"{k}_recall_15_mean"], m[f"{k}_precision_15_mean"])
