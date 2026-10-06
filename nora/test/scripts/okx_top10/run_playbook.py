"""Phase 3 - chay PLAYBOOK cho 1 bot: ho so TRAIN -> tham so -> hieu chinh tan suat vao lenh (TRAIN) -> backtest free-running ca cua so ->
Level S (test + full) + overlap episode vs baseline ngau nhien (20 seed) -> out/playbook_<slug>.json.

Dung:  run_limited.sh --mem 4G --no-lock -- run_playbook.py --bot Auroraxwt [--variants v0,v1] [--seeds 20]
"""
import argparse, json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load
import disc_stats as ST
import playbook as PB

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
MIN = 60_000; DAY = 86_400_000
SMALL = 40
LAYER_GAP_MS = 30_000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- bien the luat (lap luat) theo bot: ten -> cfg
# Moi bien the la MOT thay doi LUAT co ly do (neu trong 'why'), chon theo so khop tren cua so TRAIN, KHONG theo test.
VARIANTS = {"default": {"v0": {}}}


class Ctx:
    def __init__(self, name):
        self.name = name; self.slug = load.slug(name)
        self.bot = load.get_bot(name)
        allb = load.build_baskets(self.bot)
        self.baskets = []
        for B in allb:
            a = load.candle_arrays(B["sym"])
            if a is not None and B["t0"] >= a["t"][0]:
                B["tranches"] = load.collapse(B["fills"], LAYER_GAP_MS)     # tang = cum fill cach nhau <= 30 giay (lenh vao chia nho); them tang that nam o tang sau
                self.baskets.append(B)
        n = len(self.baskets); self.n = n
        self.n_tr = int(n * 0.6)
        self.split_t = self.baskets[self.n_tr]["t0"]
        self.small = n < SMALL
        self.first = min(B["t0"] for B in self.baskets); self.last = max(B["t1"] for B in self.baskets)
        self.syms = sorted({B["sym"] for B in self.baskets})
        self.grid = PB.Grid(self.syms, self.first, self.last)
        self.tstart = self.grid.bar(self.first) - 1; self.tend = self.grid.bar(self.last) + 2

    def trades_of(self, baskets):
        ids = set()
        for B in baskets:
            ids.update(B["bk_ids"])
        return [dict(t) for t in self.bot["trades"] if t["bk"] in ids]


def opp_pct(bks):
    """% basket co basket nguoc chieu cung ma dang mo luc no mo (bks: list (sym, side, t0, t1))."""
    by = {}
    for b in bks:
        by.setdefault((b[0], b[1]), []).append(b)
    ov = 0
    for b in bks:
        other = by.get((b[0], "short" if b[1] == "long" else "long"), [])
        t1 = b[3] if b[3] is not None else 1 << 60
        if any(o[2] <= b[2] < (o[3] if o[3] is not None else 1 << 60) for o in other):
            ov += 1
    return 100 * ov / max(1, len(bks))


def window_slice(grid, trades, bks, lo, hi):
    """Trade sim co basket mo trong [lo,hi] (ms) va basket tuong ung (da dong)."""
    T = [t for t in trades if lo <= t["bt0"] <= hi]
    B = [(s, d, t0) for (s, d, t0, t1) in bks if lo <= t0 <= hi and t1 is not None]
    return T, B


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    return o


def fit(ctx, train, split_t, cfg, log=log, mode_candidates=None):
    """Tu TRAIN: ho so -> tham so -> (chon che do chieu neu 'none') -> hieu chinh tan suat. Tra dict fit (co sigfn(seed, window))."""
    g = ctx.grid
    trt = ctx.trades_of(train)
    prof, M = PB.profile(g, train, trt)
    P, R = PB.derive(g, train, M, prof, cfg)
    t_lo = min(B["t0"] for B in train)
    lo, hi = g.bar(t_lo), g.bar(split_t)
    cand = [P["mode"]] if P["mode"] != "none" else (cfg.get("modes") or mode_candidates or ["both", "rand", "opp1"])
    kind = cfg.get("entry", "threshold")
    H = PB.fit_hazard(g, train, P, split_t) if kind == "hazard" else None
    best = None; table = []
    for m in cand:
        if kind == "hazard":
            f, cal = PB.calibrate_hazard(g, P, train, split_t, H, mode=m)
            sigfn = (lambda seed, window, m=m, f=f: PB.build_signals_hz(g, P, H, f, mode=m, seed=seed, window=window))
        else:
            q, cal = PB.calibrate_rate(g, P, train, split_t, mode=m, by_symbol=cfg.get("rate_by_symbol", False))
            sigfn = (lambda seed, window, m=m, q=q: PB.build_signals(g, P, q, mode=m, seed=seed, window=window))
        res = PB.run_engine(g, sigfn(0, (lo, hi)), P, lo - 1, hi)
        trades, info = PB.decode(g, res, P, P["fee_bps_side"])
        bks = PB.sim_baskets(g, res)
        lp = 100 * np.mean([b[1] == "long" for b in bks]) if bks else 0
        op = opp_pct(bks)
        err = abs(lp - prof["long_pct"]) + abs(op - prof["opp_side_open_pct"])
        table.append(dict(mode=m, long_pct=round(float(lp), 1), opp_side_open_pct=round(float(op), 1), err=round(float(err), 1), n_baskets=len(bks)))
        log("  mode", m, table[-1])
        if best is None or err < best[0]:
            best = (err, m, sigfn, cal, H)
    _, mode, sigfn, cal, H = best
    P["mode"] = mode
    R["direction"]["chosen_mode"] = mode; R["direction"]["mode_table_train"] = table
    R["entry_kind"] = kind
    if H is not None:
        R["hazard"] = dict(edges=[round(float(x), 3) for x in H["edges"]], rate_per_bar=[float("%.3g" % x) for x in H["rate"]], entries=H["ent"], ref_bars=H["nref"], quantiles=list(PB.HZ_Q))
    return dict(prof=prof, M=M, P=P, R=R, cal=cal, split_t=split_t, train=train, sigfn=sigfn, cfg=cfg, H=H)


def p_sym_baseline(ctx, F, train):
    """Xac suat thinning moi nen theo ma de so basket/ngay ~ TRAIN (cong phien), hieu chinh 1 lan theo lop."""
    g = ctx.grid; P = F["P"]
    t_lo = min(B["t0"] for B in train); lo = g.bar(t_lo); hi = g.bar(F["split_t"])
    G = PB.gate_matrix(g, P)
    ok = G[:, lo:hi] & np.isfinite(g.o[:, lo:hi])
    nbars = ok.sum(axis=1)
    cnt = np.zeros(g.S)
    for B in train:
        cnt[g.sidx[B["sym"]]] += 1
    p = np.zeros(g.S)
    cls = P["cls_of"]
    for c_ in range(4):
        idx = np.flatnonzero(cls == c_)
        if len(idx) == 0: continue
        pc = cnt[idx].sum() / max(1, nbars[idx].sum())
        for k in idx:
            p[k] = (cnt[k] / nbars[k]) if (cnt[k] >= 8 and nbars[k] > 0) else pc
    for _ in range(2):
        got = np.zeros(g.S)
        for sd in range(3):
            sig = PB.random_signals(g, P, p, sd, (lo, hi))
            res = PB.run_engine(g, sig, P, lo - 1, hi)
            nb_, nf, ovf, nopen, bk_s, bk_d, bk_t0 = res[:7]
            got += np.bincount(bk_s[:nb_][(bk_t0[:nb_] >= lo) & (bk_t0[:nb_] < hi)], minlength=g.S) / 3
        for c_ in range(4):
            idx = np.flatnonzero(cls == c_)
            tg = cnt[idx].sum()
            if got[idx].sum() > 0 and tg > 0:
                p[idx] *= tg / got[idx].sum()
    return p


KEYS_OV = ("recall_same_15", "recall_same_60", "recall_same_240", "recall_any_15", "recall_any_60", "recall_any_240",
           "precision_same_15", "precision_same_60", "precision_same_240", "precision_any_15", "precision_any_60", "precision_any_240")


def _agg(L, f):
    v = np.array([f(e) for e in L if f(e) is not None], float)
    return dict(mean=round(float(v.mean()), 3), sd=round(float(v.std()), 3), p5=round(float(np.percentile(v, 5)), 3), p95=round(float(np.percentile(v, 95)), 3),
                min=round(float(v.min()), 3), max=round(float(v.max()), 3)) if len(v) else None


def multi_seed(ctx, F, make_sig, seeds, windows, params=None, keep_first=False):
    """Chay `seeds` lan (tin hieu ngau nhien khac nhau) -> tong hop phan phoi cua stats-match, daily corr, overlap, metric sim."""
    g = ctx.grid; P = params or F["P"]
    acc = {w: [] for w in windows}; first = None
    for sd in range(seeds):
        sig = make_sig(sd)
        res = PB.run_engine(g, sig, P, ctx.tstart, ctx.tend)
        trades, info = PB.decode(g, res, P, P["fee_bps_side"], seed=sd)
        bks = PB.sim_baskets(g, res)
        for wname, (lo, hi) in windows.items():
            real_T = ctx.trades_of([B for B in ctx.baskets if lo <= B["t0"] <= hi])
            real_b = [(B["sym"], B["side"], B["t0"]) for B in ctx.baskets if lo <= B["t0"] <= hi]
            sT, sB = window_slice(g, trades, bks, lo, hi)
            ev = PB.level_s_eval(real_T, sT, real_b, sB, lo, hi); ev["window_ms"] = [int(lo), int(hi)]
            if sd == 0 and keep_first:
                ev["sim_trades"] = [{k: v for k, v in t.items() if k not in ("why", "bt0")} for t in sT]; ev["info"] = info
            acc[wname].append(ev)
    out = {}
    for w, L in acc.items():
        L2 = [e for e in L if e.get("compare")]
        if not L2:
            out[w] = dict(first=L[0] if keep_first else None, summary=None); continue
        r = dict(n_seeds=len(L2), stats_match=_agg(L2, lambda e: e["compare"]["stats_match_score"]), daily_corr=_agg(L2, lambda e: (e["daily"] or {}).get("daily_corr")),
                 day_sign_agree=_agg(L2, lambda e: (e["daily"] or {}).get("day_sign_agree")), mix_overlap=_agg(L2, lambda e: e["mix_overlap"]), n_sim=_agg(L2, lambda e: e["sim"]["n"]))
        for key in KEYS_OV:
            r[key] = _agg(L2, lambda e, k=key: e["overlap"][k])
        r["metric_mean"] = {}; r["metric_ok_rate"] = {}
        for k in PB.ST.CORE + ["levMed", "realized", "maxWin", "maxLoss", "holdWin", "holdLoss"]:
            v = [e["compare"]["rows"][k]["sim"] for e in L2 if e["compare"]["rows"][k]["sim"] is not None]
            r["metric_mean"][k] = round(float(np.mean(v)), 3) if v else None
            r["metric_ok_rate"][k] = round(float(np.mean([e["compare"]["rows"][k]["ok"] for e in L2])), 2)
        out[w] = dict(summary=r, first=L[0] if keep_first else None)
    return out


def evaluate(ctx, F, seeds, windows, log=log, with_baseline=True, keep_trades=True, pb_seeds=None):
    """Playbook: seed 0 = backtest tham chieu (bang day du) + phan phoi tren `pb_seeds` seed; baseline ngau nhien `seeds` seed."""
    g = ctx.grid
    pb = multi_seed(ctx, F, lambda sd: F["sigfn"](sd, (ctx.tstart, ctx.tend)), pb_seeds or (seeds if F["P"]["mode"] in ("rand",) or F["cfg"].get("entry") == "hazard" else 1), windows, keep_first=True)
    out = dict(windows={}, summary={})
    for w, d in pb.items():
        ev = d["first"]
        if not keep_trades and ev: ev.pop("sim_trades", None)
        out["windows"][w] = ev; out["summary"][w] = d["summary"]
        if ev and ev.get("compare"):
            log("  [%s] stats match %.2f | daily corr %s | same60 recall %s precision %s | n sim %d real %d" % (
                w, ev["compare"]["stats_match_score"], (ev["daily"] or {}).get("daily_corr"), ev["overlap"]["recall_same_60"], ev["overlap"]["precision_same_60"], ev["sim"].get("n", 0), ev["real"].get("n", 0)))
    out["info"] = (out["windows"].get("full") or next(iter(out["windows"].values())) or {}).get("info", {})
    if with_baseline:
        p = p_sym_baseline(ctx, F, F["train"])
        out["baseline"] = {w: d["summary"] for w, d in multi_seed(ctx, F, lambda sd: PB.random_signals(g, F["P"], p, sd, (ctx.tstart, ctx.tend)), seeds, windows).items()}
    return out


# ======================================================================= luat tieng Viet (so cu the tu TRAIN)
WD = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


def rules_vi(ctx, F):
    P = F["P"]; R = F["R"]; prof = F["prof"]; cfg = F["cfg"]
    D = R["direction"]; mode = D["chosen_mode"]; H = R["activity"]["H"]
    ent = []
    sess = "; ".join("%s: %s (%s)" % (k, ", ".join(v["buckets_utc"]), "/".join(v["weekdays"])) for k, v in R["session"].items())
    ent.append("Chỉ canh lệnh trong các khung 15 phút (UTC) chứa ≥ 80%% số lần mở lệnh đầu của bot ở TRAIN, theo từng lớp mã: %s." % sess)
    if R.get("entry_kind") == "hazard":
        hz = R["hazard"]
        ent.append("Mỗi nến 1 phút ĐÃ ĐÓNG trong khung đó, bot mở basket mới với xác suất phụ thuộc độ hoạt động z = |biến động %d phút| / trung vị cuộn 3 ngày của chính mã đó. "
                   "Xác suất mỗi nến theo 6 mức z (cắt tại phân vị %s, tức z = %s) = %s; nhân thêm hệ số riêng từng mã để số basket/ngày khớp TRAIN. Lệnh khớp tại giá mở cửa nến kế tiếp." % (
                       H, "/".join(str(q) for q in hz["quantiles"]), "/".join(str(x) for x in hz["edges"]), "/".join("%.2g" % x for x in hz["rate_per_bar"])))
    else:
        ent.append("Mỗi nến 1 phút ĐÃ ĐÓNG: nếu z = |biến động %d phút| / trung vị cuộn 3 ngày của chính mã đó ≥ ngưỡng q (theo lớp mã, hiệu chỉnh để số basket/ngày khớp TRAIN) thì vào lệnh tại giá mở cửa nến kế tiếp."
                   % H)
    if mode in ("contrarian", "momentum"):
        ent.append("Chiều: %s theo biến động %d phút trước đó (TRAIN: %.0f%% lệnh cùng hướng với biến động đó)." % (
            "ngược xu hướng (mua khi giảm, bán khi tăng)" if mode == "contrarian" else "thuận xu hướng", D["H"], D["share_pct"]))
    elif mode == "rand":
        ent.append("Chiều: không có thiên hướng rõ (lệch ≤ %.0f điểm %% so với 50/50 ở mọi chân trời 1-1440 phút) nên chọn ngẫu nhiên theo tỷ lệ long của từng mã ở TRAIN (chung %.0f%% long)." % (D["bias_pp"], prof["long_pct"]))
    elif mode == "both":
        ent.append("Chiều: mở cả long và short cùng lúc khi có tín hiệu.")
    elif mode == "opp1":
        ent.append("Chiều: ngược với biến động 1 phút gần nhất.")
    if R.get("side_lock", {}).get("on"):
        sl = R["side_lock"]
        ent.append("Khóa chiều: chỉ long với %s; chỉ short với %s (≥ 75%% basket TRAIN cùng một chiều)." % (", ".join(sl["long_only"]) or "—", ", ".join(sl["short_only"]) or "—"))
    ent.append("Chờ sau khi đóng cùng (mã, chiều): %d phút; tối đa %d basket cùng lúc; %s." % (P["cool"], P["maxconc"],
               "cho phép giữ đồng thời long và short cùng một mã (TRAIN: %.0f%% basket có basket ngược chiều đang mở)" % prof["opp_side_open_pct"] if P["hedge"] else "mỗi mã chỉ một chiều tại một thời điểm"))
    add = []
    A = R["add"]
    if A["on"]:
        add.append("Thêm tầng (DCA): khi giá đi ngược ≥ %s so với giá lần khớp trước thì thêm 1 tầng bằng lệnh limit tại mức đó; tối đa %d tầng." % (
            ("%.2f%%" % A["step_pct"]) if A["step_mode"] == "pct" else ("%.2f × ATR1h" % A["step_atr"]), A["max_layers"]))
        if P.get("rsamp") is not None and len(P["rsamp"]):
            add.append("Khối lượng tầng thêm: bốc ngẫu nhiên từ phân phối TRAIN của (notional tầng thêm / notional tầng đầu): trung vị %.2f, q90 %.2f, q99 %.2f (đuôi nặng)." % (
                R["add_ratio_sampling"]["q50"], R["add_ratio_sampling"]["q90"], R["add_ratio_sampling"]["q99"]))
        else:
            add.append("Khối lượng tầng thêm = %s × notional tầng đầu (trung vị TRAIN theo tầng)." % "/".join("%.2f" % x for x in P["ratio"][1:]))
    else:
        add.append("Không thêm tầng: TRAIN chỉ %.1f%% basket có hơn 1 lệnh vào (ngoài việc chia nhỏ lệnh)." % prof["add_basket_pct"])
    if R["split"]["on"]:
        add.append("Mỗi lệnh vào được chia thành m lệnh con (m lấy mẫu từ TRAIN, trung bình %.2f, %.0f%% lệnh bị chia) cách nhau vài giây, lệch giá bám theo phân phối TRAIN; các lệnh con đóng cùng basket tại cùng giá đóng." % (R["split"]["mean_fills_per_order"], R["split"]["share_multi_pct"]))
    ex = []
    T = R["tp"]
    if R.get("trail", {}).get("on"):
        ex.append("Thoát bằng trailing: khi lợi nhuận đỉnh ≥ mức chốt lời (bên dưới) thì thoát khi giá lùi %.2f%% từ đỉnh, nhưng không bao giờ thoát dưới hòa vốn + phí." % R["trail"]["giveback_pct"])
    if T["mode"] == "fixed":
        ex.append("Chốt lời: đặt limit tại giá TB × (1 ± TP) với TP = trung vị lợi nhuận gộp của basket thắng ở TRAIN theo lớp: %s." % ", ".join("%s %.2f%%" % (k, v) for k, v in T["per_class_pct"].items()))
    else:
        ex.append("Chốt lời: TP = c × ATR1h (14 nến 1h đã đóng) của mã tại lúc vào, c = trung vị TRAIN theo lớp: %s (CV theo ATR %.2f < CV theo %% cố định %.2f)." % (
            ", ".join("%s %.2f" % (k, v) for k, v in T["per_class_atr"].items()), T["cv_atr"], T["cv_fixed"]))
    L = R["loser"]
    if L["mode"] in ("stop", "both"):
        ex.append("Cắt lỗ: đóng thị trường khi giá chạm −SL so với giá TB (chỉ hiệu lực từ tầng thứ %d), SL = trung vị |lợi nhuận| basket thua ở TRAIN theo lớp: %s (TRAIN: lỗ đóng gần điểm xấu nhất, ret/MAE = %.2f ≥ 0.8)." % (
            R.get("stop_layers", 1), ", ".join("%s %.2f%%" % (k, v) for k, v in L["stop_pct_per_class"].items()), L["ret_over_mae"] or 0))
    if L["mode"] in ("hold_be", "both"):
        ex.append("Không cắt lỗ cứng: basket thua được giữ đến khi giá về hòa vốn (TRAIN: ret/MAE = %.2f ≤ 0.6). Sau khi tụt sâu hơn %s thì đổi mức chốt sang hòa vốn (+ phí khứ hồi %.1f bps)." % (
            L["ret_over_mae"] if L["ret_over_mae"] is not None else float("nan"), ", ".join("%s %.2f%%" % (k, v) for k, v in L["be_after_dd_pct_per_class"].items()), L["fee_rt_bps"]))
    ex.append("Giới hạn thời gian giữ: %s." % (("%d phút (%.1f giờ) rồi thoát thị trường ở giá mở cửa nến kế tiếp" % (P["maxhold"], P["maxhold"] / 60)) if P["maxhold"] > 0 else "không có (basket thua vẫn mở như bot thật; chỉ tính lệnh đã đóng giống dữ liệu thật)"))
    sz = ["Notional lệnh vào đầu = trung vị TRAIN theo mã (đủ ≥ 2 basket) → theo lớp → toàn bot: %s; đòn bẩy trung vị theo mã (%s)." % (
        ", ".join("%s %.0f" % (k, v) for k, v in R["sizing"]["n0_class_med"].items()), "/".join("%g" % x for x in sorted(set(np.round(P["lev"], 0))))),
        "Phí khứ hồi %.1f bps trên notional (ước từ chênh lệch giữa PnL báo cáo và giá khớp thật ở TRAIN); độ nhạy với 5 bps/chiều (theo spec) được chạy riêng." % (2 * P["fee_bps_side"])]
    return dict(entry=ent, add=add, exit=ex, sizing=sz)


def gaps(cmp_):
    out = []
    for k, r in (cmp_ or {}).get("rows", {}).items():
        if not r["ok"] and r["real"] is not None:
            out.append(dict(metric=k, real=r["real"], sim=r["sim"], rel_err=r["rel_err"]))
    return out


def composite(ev_sum):
    """Diem chon bien the tren cua so TRAIN: stats-match + 0.5*corr ngay (>=0) + 0.25*recall60 cung chieu."""
    s = ev_sum
    if not s: return -1
    sm = s["stats_match"]["mean"]; dc = max(0.0, (s["daily_corr"] or {"mean": 0})["mean"] or 0); rc = s["recall_same_60"]["mean"] / 100
    return sm + 0.5 * dc + 0.25 * rc


# ======================================================================= ung vien thay doi LUAT (chon tham lam theo diem TRAIN)
CANDIDATES = [
    ("fidelity", {"split": True, "ratio_sample": True}, "Lệnh vào chia nhỏ thành m lệnh con (TRAIN: số fill/lệnh và lệch giá giữa các fill), khối lượng tầng thêm bốc từ phân phối TRAIN (đuôi nặng) để khớp addPct, top5Share, maxLayers."),
    ("hazard", {"entry": "hazard"}, "Thay ngưỡng cứng bằng XÁC SUẤT theo độ hoạt động (hazard theo 6 mức z + hệ số từng mã): ngưỡng cứng chỉ chọn các nến cực đoan, còn bot thật vào ở mức hoạt động vừa phải (AUC TRAIN < 1)."),
    ("cap99", {"maxhold_q": 99}, "Nới lỏng cap thời gian giữ p95 → p99: bot thật không cắt lỗ theo giờ, chỉ vài basket thua bị đóng sau nhiều ngày."),
    ("nocap", {"maxhold": 0}, "Bỏ cap thời gian giữ (basket thua vẫn mở như bot thật; cuối kỳ bot còn vị thế mở lỗ chưa thực hiện)."),
    ("side_lock", {"side_lock": True}, "Khóa chiều: mã (hoặc cả bot) có ≥ 75% basket TRAIN cùng một chiều thì chỉ vào chiều đó (bot thiên về một phía)."),
    ("stop_layers", {"stop_layers": "median_loser"}, "Cắt lỗ chỉ hiệu lực từ tầng thứ K (K = trung vị số tầng của basket thua TRAIN): không cắt lỗ trước khi thêm tầng vì giá TB đổi theo tầng."),
    ("trail", {"trail": True}, "Thoát bằng trailing: kích hoạt khi lợi nhuận đỉnh ≥ TP, thoát khi giá lùi gb từ đỉnh (gb = trung vị MFE − lợi nhuận chốt của basket thắng TRAIN), không bao giờ dưới hòa vốn + phí; thay cho TP cố định."),
    ("cool25", {"cool_q": 25}, "Thời gian chờ = phân vị 25% khoảng tái-vào TRAIN (bot thật tái vào rất nhanh sau khi đóng) thay vì trung vị."),
    ("rate_sym", {"rate_by_symbol": True}, "Hiệu chỉnh ngưỡng z theo từng mã (mã ≥ 8 basket TRAIN) để cơ cấu mã khớp TRAIN (chỉ áp dụng cho vào bằng ngưỡng)."),
]
EXCL = {"cap99": {"nocap"}, "nocap": {"cap99"}}


def run(name, seeds=20, pb_sel_seeds=5, cands=None, out_dir=OUT, max_rounds=3):
    t_all = time.time()
    ctx = Ctx(name); g = ctx.grid
    log(name, "baskets", ctx.n, "train", ctx.n_tr, "split", ctx.split_t, "syms", len(ctx.syms), "small" if ctx.small else "")
    cands = cands or CANDIDATES
    train = ctx.baskets[:ctx.n_tr]
    W_train = {"train": (ctx.first, ctx.split_t)}
    W = {"test": (ctx.split_t, ctx.last), "full": (ctx.first, ctx.last)}
    iters = []

    def trial(cfg, label, why):
        t = time.time()
        F = fit(ctx, train, ctx.split_t, cfg, log=lambda *a: None)
        stoch = F["P"]["mode"] == "rand" or cfg.get("entry") == "hazard"
        E = evaluate(ctx, F, pb_sel_seeds, {**W_train, **W}, log=lambda *a: None, with_baseline=False, keep_trades=False, pb_seeds=pb_sel_seeds if stoch else 1)
        sc = composite(E["summary"]["train"])
        row = dict(i=len(iters), name=label, cfg=cfg, change=why, train_score=round(sc, 3), secs=round(time.time() - t, 1), mode=F["P"]["mode"])
        for w in ("train", "test"):
            s_ = E["summary"].get(w)
            if s_:
                row[w] = dict(stats_match=s_["stats_match"]["mean"], daily_corr=(s_["daily_corr"] or {}).get("mean"), recall_same_60=s_["recall_same_60"]["mean"], precision_same_60=s_["precision_same_60"]["mean"],
                              mix=s_["mix_overlap"]["mean"], n_sim=s_["n_sim"]["mean"], realized=s_["metric_mean"]["realized"], hold_med=s_["metric_mean"]["holdMed"])
        row["train_gaps"] = gaps((E["windows"].get("train") or {}).get("compare"))
        iters.append(row)
        log("  %-34s train score %.3f | train %s | test %s" % (label, sc, {k: v for k, v in (row.get("train") or {}).items() if k in ("stats_match", "daily_corr", "recall_same_60")},
                                                              {k: v for k, v in (row.get("test") or {}).items() if k in ("stats_match", "daily_corr", "recall_same_60")}))
        return sc, F, row

    cfg = {}
    sc, F, row = trial(cfg, "v0_spec", "Luật đúng spec: ngưỡng z hiệu chỉnh theo lớp, TP/SL theo lớp, cap thời gian p95, 1 fill/tầng.")
    row["accepted"] = True
    best_sc, best_F = sc, F
    # quy tac CAU TRUC (suy ra truc tiep tu ho so TRAIN, khong theo diem): khoa chieu neu bot lech 1 phia >= 80%, cat lo chi tu tang K neu co them tang va co cat lo
    struct = {}; applied = []
    prof0 = F["prof"]
    if len(train) >= 10 and (prof0["long_pct"] >= 75 or prof0["long_pct"] <= 25):
        struct["side_lock"] = True; applied.append("side_lock")
    if F["R"]["add"]["on"] and F["R"]["loser"]["mode"] in ("stop", "both"):
        struct["stop_layers"] = "median_loser"; applied.append("stop_layers")
    if struct:
        cfg = dict(struct)
        sc, F, row = trial(cfg, "+".join(applied) + " (cấu trúc, theo hồ sơ TRAIN)", "Quy tắc nhất quán suy từ hồ sơ TRAIN: " + ", ".join(applied))
        row["accepted"] = True; row["structural"] = True
        best_sc, best_F = sc, F
    remaining = [c for c in cands if c[0] not in applied]
    for rd in range(max_rounds):
        pick = None
        for (cn, delta, why) in remaining:
            if any(a in EXCL.get(cn, set()) for a in applied):
                continue
            c2 = {**cfg, **delta}
            if delta.get("rate_by_symbol") and cfg.get("entry") == "hazard":
                continue
            sc2, F2, row2 = trial(c2, "+".join(applied + [cn]) if applied else cn, why)
            row2["candidate"] = cn
            if pick is None or sc2 > pick[0]:
                pick = (sc2, cn, delta, F2, row2)
        if pick is None or pick[0] < best_sc + 0.005:
            break
        best_sc, cn, delta, best_F, prow = pick
        prow["accepted"] = True
        cfg = {**cfg, **delta}; applied.append(cn)
        remaining = [c for c in remaining if c[0] != cn]
        log(" -> ACCEPT", cn, "score %.3f" % best_sc)
    F = best_F
    vn = "+".join(applied) if applied else "v0_spec"
    log("CHOSEN", vn, "train score %.3f" % best_sc)
    stoch = F["P"]["mode"] == "rand" or cfg.get("entry") == "hazard"
    E = evaluate(ctx, F, seeds, {**W_train, **W}, log=log, with_baseline=True, keep_trades=True, pb_seeds=seeds if stoch else 1)
    P2 = dict(F["P"]); P2["fee_bps_side"] = 5.0; P2["be_tp"] = 10 / 1e4 + 1e-4
    sens = multi_seed(ctx, F, lambda sd: F["sigfn"](sd, (ctx.tstart, ctx.tend)), 5 if stoch else 1, W, params=P2)
    out = dict(bot=name, slug=ctx.slug, n_baskets=ctx.n, split=dict(split_t=int(ctx.split_t), n_train=ctx.n_tr, n_test=ctx.n - ctx.n_tr, small_bot=ctx.small,
                                                                  note="tham số ước lượng trên 60% basket đầu (TRAIN); cửa sổ TEST = 40% cuối; 'full' bao gồm cả TRAIN (trong mẫu)"),
               profile_train=F["prof"], chosen_variant=vn, params=dict(cfg=cfg, rules=F["R"], fee_bps_side=F["P"]["fee_bps_side"], max_concurrent=int(F["P"]["maxconc"]), cooldown_min=int(F["P"]["cool"]),
                                                                      lev={s: float(F["P"]["lev"][k]) for k, s in enumerate(g.syms)}, n0={s: round(float(F["P"]["N0"][k]), 0) for k, s in enumerate(g.syms)}),
               rules_vi=rules_vi(ctx, F), calibration={k: v for k, v in F["cal"].items() if k != "hist"}, iterations=iters, level_s={}, baselines=E.get("baseline"), seed_summary=E["summary"],
               sensitivity_fee_5bps_side={w: (d["summary"] and dict(stats_match=d["summary"]["stats_match"], metric_mean=d["summary"]["metric_mean"])) for w, d in sens.items()},
               info=E["info"], runtime_s=0)
    for w in ("train", "test", "full"):
        ev = E["windows"].get(w)
        if not ev or not ev.get("compare"):
            out["level_s"][w] = None; continue
        d = ev["daily"]
        out["level_s"][w] = dict(window_ms=ev["window_ms"], real=ev["real"], sim=ev["sim"], compare=ev["compare"], mix_overlap=ev["mix_overlap"], overlap=ev["overlap"],
                                 daily=dict(daily_corr=d["daily_corr"], day_sign_agree=d["day_sign_agree"], n_days=d["n_days"], days=d["days"], real_cum=d["real_cum"], sim_cum=d["sim_cum"]),
                                 gaps=gaps(ev["compare"]), sim_trades=ev.get("sim_trades") if w == "full" else None)
    # phuong an UOC LUONG TREN TOAN BO CUA SO (trong mau): cung bien the luat, tham so tu moi basket -> kha nang MO TA, khong phai du bao
    log("in-sample (full-window) estimation, rules", vn)
    F2 = fit(ctx, ctx.baskets, ctx.last + 1, cfg, log=lambda *a: None)
    E2 = evaluate(ctx, F2, seeds, {"full": (ctx.first, ctx.last)}, log=log, with_baseline=True, keep_trades=True, pb_seeds=seeds if stoch else 1)
    ev = E2["windows"]["full"]
    out["insample_full"] = dict(note="tham số (cả tần suất vào lệnh) ước lượng trên TOÀN BỘ basket của bot -> trong mẫu, chỉ đo khả năng MÔ TẢ, không phải dự báo",
                               profile=F2["prof"], rules=F2["R"], rules_vi=rules_vi(ctx, F2), seed_summary=E2["summary"].get("full"), baseline=(E2.get("baseline") or {}).get("full"),
                               level_s=dict(real=ev["real"], sim=ev["sim"], compare=ev["compare"], mix_overlap=ev["mix_overlap"], overlap=ev["overlap"],
                                            daily=dict(daily_corr=ev["daily"]["daily_corr"], day_sign_agree=ev["daily"]["day_sign_agree"], n_days=ev["daily"]["n_days"], days=ev["daily"]["days"], real_cum=ev["daily"]["real_cum"], sim_cum=ev["daily"]["sim_cum"]),
                                            gaps=gaps(ev["compare"]), sim_trades=ev.get("sim_trades")))
    out["verdict"] = verdict(out)
    out["runtime_s"] = round(time.time() - t_all, 1)
    path = os.path.join(out_dir, "playbook_%s.json" % ctx.slug)
    open(path, "w").write(json.dumps(jsonable(out), ensure_ascii=False))
    log("wrote", path, "%.0fs" % (time.time() - t_all))
    return out


def verdict(o):
    v = {}
    for w in ("test", "full"):
        L = o["level_s"].get(w); S = (o["seed_summary"] or {}).get(w); B = (o["baselines"] or {}).get(w)
        if not L or not S:
            continue
        ok = [k for k, r in L["compare"]["rows"].items() if r["ok"] and k in PB.ST.CORE]
        bad = [k for k, r in L["compare"]["rows"].items() if not r["ok"] and k in PB.ST.CORE]
        rec = S["recall_same_60"]["mean"]; brec = B["recall_same_60"] if B else None
        z = (rec - brec["mean"]) / brec["sd"] if brec and brec["sd"] > 0 else None
        v[w] = dict(stats_match_seed0=L["compare"]["stats_match_score"], stats_match_mean=S["stats_match"]["mean"], stats_match_baseline=B["stats_match"]["mean"] if B else None,
                    metrics_ok=ok, metrics_off=bad, daily_corr_mean=(S["daily_corr"] or {}).get("mean"), daily_corr_baseline=(B["daily_corr"] or {}).get("mean") if B else None,
                    recall_same_60=rec, recall_same_60_baseline=brec["mean"] if brec else None, recall_z_vs_baseline=None if z is None else round(float(z), 2),
                    precision_same_60=S["precision_same_60"]["mean"], precision_same_60_baseline=B["precision_same_60"]["mean"] if B else None)
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    run(a.bot, seeds=a.seeds)
