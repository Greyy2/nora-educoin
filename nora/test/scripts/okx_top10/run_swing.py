"""Runner SWING/SCALP: Professor-Wang, M Power7, Dark-Wood-Dahlia.
  run_limited.sh --no-lock -- test/scripts/okx_top10/run_swing.py "Professor-Wang" [--quick] [--workers N]
Ghi out/<slug>.json (cùng schema out/01pp.json + thêm: representative, loo, diagnostics.*, subpos, levelC).

Quy trình (xem docstring families_swing.py cho họ luật):
  1. dựng basket (load.py), chia 60% đầu (train) / 40% cuối (test) theo t0; INFER chẩn đoán trên TRAIN (+ mô tả toàn mẫu cho bằng chứng không-fit).
  2. LEVEL A: mỗi họ thoát -> lưới -> chọn trên TRAIN bằng xobj (công thức dưới) -> báo TRAIN & TEST (headline = TEST) + baseline thời gian giữ ngẫu nhiên.
     Sau đó forward-selection: thêm từng thành phần (SL/TP/trailing/time/chỉ báo/phiên/add) lên mô hình tốt nhất, chỉ giữ nếu xobj train tăng >= 0.01.
  3. LEVEL B: luật vào lệnh (ORB Mỹ, N-sigma theo ATR, pullback EMA/VWAP, mức hôm trước) x cổng giờ x cooldown, fit F1(+-15p) vượt baseline trên TRAIN, báo TEST.
  4. LEVEL C: chạy tự do (vào theo tín hiệu tốt nhất + thoát tốt nhất) so với bot thật & với vào ngẫu nhiên cùng số lượng.
  5. Professor-Wang: leave-one-out (chọn tham số trên 32 basket, đo trên basket bị loại) cho mọi họ.
  xobj v2 (chỉ dùng TRAIN, không dùng TEST) = (mean close_15 + mean close_60)/2 + 0.5*max(corr(ret thật, ret sim),0) + 0.25*mean(số tranche bằng nhau)
  - 0.1*trung vị|ln(hold sim/hold thật)|  (v1 không có số hạng cuối: chọn mô hình thoát tức thì chỉ để khớp nhóm lệnh ngắn).
"""
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import families_swing as fs
import load
import match
import run_bot
import sim

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
G = {}
MINMS = 60_000
H = 3_600_000

BOTS = {
    "Professor-Wang": dict(
        hyp=("Swing cắt lỗ nhanh trên ETH/BTC/ZEC: vào theo cụm nhiều mã cùng lúc (cụm 12:15-13:00 UTC quanh dữ liệu vĩ mô 12:30 UTC và cụm đêm), "
             "lệnh thua bị cắt nhanh (trung vị 0,4 giờ) và nhiều lệnh đóng ĐỒNG LOẠT (7 lệnh cùng 12:37 UTC 11/09), lệnh thắng giữ ~19 giờ với giveback nhỏ so với đỉnh. "
             "Giả thuyết: (H1) SL cố định % hoặc bội số ATR + trailing/TP; (H2) thoát theo chỉ báo nến ĐÓNG 15m/1h (cắt qua EMA/VWAP) trên chính mã hoặc BTC (thị trường chung); "
             "(H3) cắt nếu chưa có lãi sau T giờ; (H4) thoát theo phiên. Add hiếm (15%) -> không mô hình hoá add."),
        adds=False, maxL_grid=[1], sym_ref=["BTC"], loo=True),
    "M Power7": dict(
        hyp=("Lướt ngắn cổ phiếu/hàng hoá perp (SNDK, ZEC, SKHYNIX, CL, TSLA, SOXL), long 82%, đòn bẩy 20x, ngủ 04-12h VN (người thật): "
             "lệnh thua cắt sau ~1,9 giờ, lệnh thắng giữ ~4,5 giờ. Giả thuyết: (H1) cắt nếu chưa có lãi sau T≈2 giờ; (H2) SL % / ATR + TP/trailing; "
             "(H3) thoát theo chỉ báo nến đóng 5m/15m/1h; (H4) thoát theo phiên Mỹ (mở 13:30 UTC / đóng 20:00 UTC); vào: ORB phiên Mỹ, N-sigma, pullback về VWAP/EMA, mức hôm trước."),
        adds=True, maxL_grid=[1, 2, 3], sym_ref=["BTC"], loo=False),
    "Dark-Wood-Dahlia": dict(
        hyp=("Swing nhiều mã (60 mã, chủ yếu cổ phiếu perp SNDK/MU/AAOI/LITE + BTC/ZEC/XAU), đòn bẩy 10x, 57% là tầng add bước ~1,06%, chuỗi tới 114 tầng; "
             "thắng 47% payoff 1,78, lệnh thắng giữ 25 giờ, lệnh thua 8 giờ. Giả thuyết: (H1) DCA theo bước % + TP % từ avg; (H2) SL/trailing; "
             "(H3) cắt nếu chưa lãi sau T giờ; (H4) thoát theo chỉ báo/phiên; (H5) giao dịch theo CHỦ ĐỀ (cổ phiếu bộ nhớ SNDK/MU/SKHYNIX cùng lúc). "
             "Do chuỗi chồng lấn rất dài (SNDK 116 lệnh con = 3 chuỗi), chạy thêm mức LỆNH CON (mỗi tầng là 1 lệnh độc lập)."),
        adds=True, maxL_grid=[1, 2, 4, 8, 16, 40], sym_ref=["BTC"], loo=False),
}


# ------------------------------------------------------------------ tiện ích
def _default(o):
    return run_bot._default(o)


def subpos_baskets(bot):
    """Mỗi lệnh con = 1 'basket' 1 fill (mức lệnh con; thoát độc lập của từng tầng)."""
    out = []
    for t in sorted(bot["trades"], key=lambda x: x["o"]):
        n = t["mg"] * t["lev"]
        s = 1 if t["side"] == "long" else -1
        fill = dict(t=t["o"], px=t["po"], notional=n, qty=n / t["po"], mg=t["mg"], lev=t["lev"])
        cl = dict(t=t["c"], px=t["pc"], qty=n / t["po"], fill=0, pnl=t["pnl"])
        B = dict(sym=t["sym"], side=t["side"], lev=float(t["lev"]), fills=[fill], closes=[cl], t0=t["o"], t1=t["c"], bk_ids=[t["bk"]],
                 notional=n, avg_px=t["po"], pnl=t["pnl"])
        B["ret"] = B["pnl"] / n * 100
        B["tranches"] = load.collapse(B["fills"])
        out.append(B)
    for i, B in enumerate(out): B["id"] = i
    return out


def _q(a, qs):
    a = np.asarray(a, float)
    return [] if len(a) == 0 else [round(float(x), 3) for x in np.percentile(a, qs)]


def _ret_from_avg(B):
    last = B["t1"]; cl = [c for c in B["closes"] if abs(c["t"] - last) <= 2000]
    fl = [B["fills"][c["fill"]] for c in cl]
    avg = sum(x["px"] * x["qty"] for x in fl) / sum(x["qty"] for x in fl)
    pxc = sum(c["px"] * c["qty"] for c in cl) / sum(c["qty"] for c in cl)
    s = 1 if B["side"] == "long" else -1
    return (pxc / avg - 1) * s * 100, avg


# ------------------------------------------------------------------ INFER (chẩn đoán)
def infer_swing(allb, train, bot):
    """Bằng chứng về luật thoát/vào từ dữ liệu: MFE/MAE/giveback, chuỗi 'còn lỗ tại T', đóng/mở đồng loạt, canh phiên, canh nến đóng, giờ vào."""
    ev = {}
    rows = []
    for B in train:
        a = load.candle_arrays(B["sym"]); s = 1 if B["side"] == "long" else -1
        i0 = int(np.searchsorted(a["t"], B["t0"], side="right")) - 1; i1 = int(np.searchsorted(a["t"], B["t1"], side="right")) - 1
        r, avg = _ret_from_avg(B)
        hh = a["h"][i0:i1 + 1]; ll = a["l"][i0:i1 + 1]
        mfe = ((hh.max() / avg - 1) if s == 1 else -(ll.min() / avg - 1)) * 100
        mae = (-(ll.min() / avg - 1) if s == 1 else (hh.max() / avg - 1)) * 100
        atr = float(sim.atr_scale(B["sym"])[i0])
        rows.append(dict(r=r, mfe=mfe, mae=mae, atr=atr, hold=(B["t1"] - B["t0"]) / H, lev=B["lev"]))
    d = pd.DataFrame(rows); d["win"] = d.r > 0; d["give"] = d.mfe - d.r
    for nm, g in (("win", d[d.win]), ("loss", d[~d.win])):
        if len(g) == 0: continue
        ev[f"{nm}_n"] = int(len(g)); ev[f"{nm}_ret_pct_q"] = _q(g.r, [10, 25, 50, 75, 90]); ev[f"{nm}_ret_atr_q"] = _q(g.r / g.atr, [10, 25, 50, 75, 90])
        ev[f"{nm}_hold_h_q"] = _q(g.hold, [10, 25, 50, 75, 90]); ev[f"{nm}_mfe_pct_q"] = _q(g.mfe, [25, 50, 75]); ev[f"{nm}_mae_pct_q"] = _q(g.mae, [25, 50, 75])
        ev[f"{nm}_giveback_pct_q"] = _q(g.give, [25, 50, 75]); ev[f"{nm}_giveback_over_atr_q"] = _q(g.give / g.atr, [25, 50, 75])
        ev[f"{nm}_ret_cv_robust"] = round(float(np.median(np.abs(g.r - g.r.median())) / abs(g.r.median())), 3) if abs(g.r.median()) > 1e-9 else None
    ev["note_giveback"] = ("giveback = MFE(1m, từ giá TB tới lúc đóng) - lợi suất đóng; nếu bot dùng trailing/limit TP cố định thì giveback thắng ổn định (CV nhỏ); "
                           "giveback = 0 nghĩa là đóng ngay tại đỉnh (limit TP / thoát tay đúng đỉnh).")
    # --- còn lỗ tại T (toàn mẫu): bác bỏ/ủng hộ luật 'cắt nếu chưa lãi sau T'
    Ts = [0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 12, 24, 48]
    uw = []
    for T in Ts:
        n_open = n_uw = n_uw_close30 = 0
        for B in allb:
            tt = B["t0"] + T * H
            if B["t1"] <= tt: continue
            a = load.candle_arrays(B["sym"]); j = int(np.searchsorted(a["t"], tt, side="right")) - 1
            fl = [f for f in B["fills"] if f["t"] <= tt]; q = sum(f["qty"] for f in fl); avg = sum(f["px"] * f["qty"] for f in fl) / q
            u = (a["c"][j] / avg - 1) * (1 if B["side"] == "long" else -1)
            n_open += 1
            if u < 0:
                n_uw += 1
                if B["t1"] <= tt + 30 * MINMS: n_uw_close30 += 1
        uw.append(dict(T_h=T, n_open=n_open, underwater_pct=round(100 * n_uw / max(1, n_open), 1), underwater_closed_within_30min=n_uw_close30))
    ev["underwater_at_T"] = uw
    ev["underwater_note"] = ("Nếu bot có luật 'đóng nếu chưa có lãi sau T giờ' thì với mọi T' >= T tỉ lệ vị thế CÒN MỞ mà đang lỗ phải ~0%. Thực tế vẫn ~30-55% ở T lớn -> không có luật đó "
                             "(giá đi ngẫu nhiên: ~40-50% nằm dưới giá vào là mức chờ đợi khi không có cắt theo thời gian).")
    # --- đóng / mở đồng loạt giữa các mã (gần hơn 2 phút)
    def batch(key, w=120):
        t = np.array([B[key] for B in allb]); sy = np.array([B["sym"] for B in allb])
        def cnt(tv):
            n = 0
            for i in range(len(tv)):
                m = np.abs(tv - tv[i]) <= w * 1000; m[i] = False
                if (m & (sy != sy[i])).any(): n += 1
            return n
        real = cnt(t)
        rng = np.random.default_rng(0); lo, hi = t.min(), t.max()
        base = [cnt(rng.uniform(lo, hi, len(t))) for _ in range(30)]
        return dict(real_n=int(real), n=len(t), real_pct=round(100 * real / len(t), 1), random_uniform_pct_mean=round(100 * float(np.mean(base)) / len(t), 1),
                    random_uniform_pct_p95=round(100 * float(np.percentile(base, 95)) / len(t), 1))
    ev["batch_close_other_symbol_within_2min"] = batch("t1"); ev["batch_open_other_symbol_within_2min"] = batch("t0")
    # --- canh phiên / mốc nến
    tc = np.array([B["t1"] for B in allb]); to = np.array([B["t0"] for B in allb])
    mod_c = (tc // MINMS) % 1440; mod_o = (to // MINMS) % 1440
    near = lambda mod, m, w=10: float(np.mean(np.minimum(np.abs(mod - m), 1440 - np.abs(mod - m)) <= w))
    ev["session_alignment_pct"] = {nm: dict(close=round(100 * near(mod_c, m), 1), open=round(100 * near(mod_o, m), 1), uniform_expected=round(100 * 21 / 1440, 1))
                                   for nm, m in (("us_open_13:30UTC", 810), ("us_close_20:00UTC", 1200), ("eu_open_07:00UTC", 420), ("macro_12:30UTC", 750))}
    sec_in_hour = ((tc // 1000) % 3600); ev["close_bar_alignment_pct"] = {
        "within_90s_after_5m": round(100 * float(np.mean(sec_in_hour % 300 <= 90)), 1), "expected_5m": 30.0,
        "within_90s_after_15m": round(100 * float(np.mean(sec_in_hour % 900 <= 90)), 1), "expected_15m": 10.0,
        "within_90s_after_1h": round(100 * float(np.mean(sec_in_hour <= 90)), 1), "expected_1h": 2.5}
    ev["entry_hour_vn_hist"] = np.bincount(((to // H + 7) % 24).astype(int), minlength=24).tolist()
    ev["entry_weekday_hist_mon0"] = np.bincount(((to // (24 * H) + 3) % 7).astype(int), minlength=7).tolist()
    ev["close_hour_vn_hist"] = np.bincount(((tc // H + 7) % 24).astype(int), minlength=24).tolist()
    ev["long_pct"] = round(100 * float(np.mean([B["side"] == "long" for B in allb])), 1)
    ev["sym_counts"] = Counter(B["sym"] for B in allb).most_common(12)
    ev["loser_time_concentration"] = loser_time_concentration(bot)
    ev["close_clusters"] = close_clusters(bot)
    ev["session_hazard"] = session_hazard(bot)
    ev["entry_context"] = entry_context(allb)
    ev["n_fills_per_basket_q"] = _q([len(B["fills"]) for B in allb], [50, 75, 90, 100]); ev["n_tranches_per_basket_q"] = _q([len(B["tranches"]) for B in allb], [50, 75, 90, 100])
    return ev


STOCK = {"SNDK", "MU", "LITE", "AAOI", "SKHYNIX", "SKHY", "DRAM", "SOXL", "QCOM", "MRVL", "NVDA", "AMD", "TSLA", "AAPL", "GOOGL", "META", "MSFT", "AMZN", "INTC", "SPCX", "CBRS", "CRCL", "NBIS", "SAMSUNG"}


def session_hazard(bot, win=5):
    """Xác suất lệnh con đang mở (ngày thường) bị đóng trong +-win phút quanh mốc phiên (UTC) - mốc kiểm soát là các giờ khác; tách cổ phiếu perp / crypto.
    Luật 'đóng tại mở/đóng cửa Mỹ' thật sự sẽ cho xác suất >> 5-10%; hazard chỉ cao hơn kiểm soát vài lần ở mức vài % -> xu hướng, không phải luật."""
    out = {}
    for minute, lab in ((810, "13:30 mở cửa Mỹ"), (840, "14:00"), (900, "15:00"), (1020, "17:00"), (1200, "20:00 đóng cửa Mỹ"), (1260, "21:00"), (420, "07:00"), (660, "11:00")):
        cnt = {True: [0, 0], False: [0, 0]}
        for t in bot["trades"]:
            if t["sym"] is None: continue
            a = load.candle_arrays(t["sym"])
            for d in range(t["o"] // 86400000, t["c"] // 86400000 + 1):
                if (d + 3) % 7 >= 5: continue
                ev = d * 86400000 + minute * 60000
                if t["o"] < ev - win * MINMS and t["c"] > ev - win * MINMS:
                    k = t["sym"] in STOCK; cnt[k][0] += 1; cnt[k][1] += t["c"] <= ev + win * MINMS
        out[lab] = {("stock_perp" if k else "crypto"): dict(n_open=v[0], closed_pct=round(100 * v[1] / v[0], 1) if v[0] else None) for k, v in cnt.items() if v[0] >= 5}
    return out


def loser_time_concentration(bot):
    """Mức tập trung thời gian giữ của lệnh con thua/thắng: tỉ lệ rơi vào cửa sổ [T,1.25T] lớn nhất qua các T (lưới nhân 1.1 từ 0.1h đến 100h). Time-stop thật cho cửa sổ rất dày (>50%)."""
    out = {}
    for lab, fn in (("loser", lambda t: t["pnl"] <= 0), ("winner", lambda t: t["pnl"] > 0)):
        h = np.array([(t["c"] - t["o"]) / H for t in bot["trades"] if fn(t)])
        best = (0, None)
        for T in np.geomspace(0.1, 100, 80):
            fr = float(np.mean((h >= T) & (h < 1.25 * T)))
            if fr > best[0]: best = (fr, T)
        out[lab] = dict(n=int(len(h)), hold_h_q10_25_50_75_90=_q(h, [10, 25, 50, 75, 90]), max_share_in_window_T_to_1_25T=round(100 * best[0], 1), at_T_h=round(float(best[1]), 2),
                        share_in_1_5_to_2_5h=round(100 * float(np.mean((h > 1.5) & (h < 2.5))), 1))
    out["note"] = "Median hold trong summary (vd 1,9h vs 4,5h) là trung vị phân phối rộng, không phải ngưỡng thời gian: cửa sổ dày nhất chỉ chứa phần nhỏ lệnh."
    return out


def close_clusters(bot, gap_s=180):
    """Các đợt đóng đồng loạt (lệnh con đóng cách nhau <= gap_s) gồm >= 2 mã khác nhau: thời điểm, số lệnh, PnL nhóm, ký quỹ nhóm, ROI nhóm trên ký quỹ."""
    tr = sorted(bot["trades"], key=lambda t: t["c"])
    cl = []; cur = [tr[0]]
    for t in tr[1:]:
        if t["c"] - cur[-1]["c"] <= gap_s * 1000: cur.append(t)
        else: cl.append(cur); cur = [t]
    cl.append(cur)
    rows = []
    for c in cl:
        syms = sorted({t["sym"] for t in c})
        if len(syms) < 2: continue
        mg = sum(t["mg"] for t in c); pnl = sum(t["pnl"] for t in c)
        rows.append(dict(t=int(c[0]["c"]), n=len(c), syms=syms, pnl=round(pnl, 1), margin=round(mg, 1), roi_on_margin_pct=round(100 * pnl / mg, 1)))
    roi = [x["roi_on_margin_pct"] for x in rows]
    return dict(n_clusters=len(rows), n_baskets_in_clusters=int(sum(x["n"] for x in rows)), roi_q=_q(roi, [10, 25, 50, 75, 90]), clusters=rows[:40],
                note="Nếu thoát theo ngưỡng PnL cả sổ (book TP/SL) thì ROI nhóm tại thời điểm đóng phải tập trung quanh một mức; phân tán rộng -> không có ngưỡng cố định.")


def entry_context(allb, reps=200):
    """Bối cảnh giá tại thời điểm vào so với thời điểm ngẫu nhiên cùng (mã, chiều) trong cùng cửa sổ: giá trị mang DẤU THEO CHIỀU LỆNH
    (+ = vào thuận đà / thuận phía trên VWAP,...). z = (trung vị thật - mean baseline) / sd baseline; ||z||>2 mới coi là khác ngẫu nhiên."""
    rng = np.random.default_rng(7)
    lo = min(B["t0"] for B in allb); hi = max(B["t1"] for B in allb)
    act = {}; rnd = {}
    bys = {}
    for B in allb: bys.setdefault((B["sym"], B["side"]), []).append(B["t0"])
    names = None
    for (sym, side), ts in bys.items():
        sg = 1 if side == "long" else -1
        f = fs.entry_features(sym, ts)
        if names is None: names = list(f)
        for k, v in f.items():
            act.setdefault(k, []).append(v * (sg if k != "pos_in_24h_range" else 1) if k != "pos_in_24h_range" else (v if sg == 1 else 1 - v))
        for rep in range(reps):
            u = rng.uniform(lo, hi, len(ts))
            f2 = fs.entry_features(sym, u)
            for k, v in f2.items():
                rnd.setdefault(k, {}).setdefault(rep, []).append(v * (sg if k != "pos_in_24h_range" else 1) if k != "pos_in_24h_range" else (v if sg == 1 else 1 - v))
    out = {}
    for k in names:
        a = np.concatenate(act[k]); meds = np.array([np.median(np.concatenate(rnd[k][r])) for r in range(reps)])
        out[k] = dict(actual_median=round(float(np.median(a)), 3), random_mean=round(float(meds.mean()), 3), random_p5=round(float(np.percentile(meds, 5)), 3),
                      random_p95=round(float(np.percentile(meds, 95)), 3), z=round(float((np.median(a) - meds.mean()) / max(meds.std(), 1e-9)), 2))
    out["note"] = ("ret*: lợi suất k phút trước / (ATR%(1h) x sqrt(k/60)) nhân dấu chiều lệnh (dương = vào THUẬN đà, âm = vào NGƯỢC đà/bắt hồi); dist_*: khoảng cách giá tới VWAP ngày/EMA20 15m (đơn vị ATR) "
                   "nhân dấu (dương = giá đã ở phía thuận chiều lệnh); pos_in_24h_range: vị trí trong biên 24h theo chiều lệnh (1 = sát đỉnh khi long). Baseline: thời điểm ngẫu nhiên đều cùng (mã,chiều).")
    return out


def derive_grid_inputs(train):
    """Phân vị TRAIN dùng để bổ sung lưới (ngoài lưới số tròn)."""
    r = np.array([_ret_from_avg(B)[0] for B in train]); atr = np.array([float(sim.atr_scale(B["sym"])[int(np.searchsorted(load.candle_arrays(B["sym"])["t"], B["t0"], side="right")) - 1]) for B in train])
    holds = np.array([(B["t1"] - B["t0"]) / H for B in train])
    out = dict(sl_q=[round(float(x), 2) for x in np.percentile(-r[r < 0], [25, 50, 75])] if (r < 0).sum() > 3 else [],
               tp_q=[round(float(x), 2) for x in np.percentile(r[r > 0], [25, 50, 75])] if (r > 0).sum() > 3 else [],
               sl_atr_q=[round(float(x), 2) for x in np.percentile(-r[r < 0] / atr[r < 0], [25, 50, 75])] if (r < 0).sum() > 3 else [],
               tp_atr_q=[round(float(x), 2) for x in np.percentile(r[r > 0] / atr[r > 0], [25, 50, 75])] if (r > 0).sum() > 3 else [],
               hold_med_h=float(np.median(holds)), loss_hold_med_h=float(np.median(holds[r < 0])) if (r < 0).sum() else None)
    return out


# ------------------------------------------------------------------ đánh giá lưới (vector hoá theo basket)
def _grid(spec):
    keys = list(spec)
    return [dict(zip(keys, v)) for v in itertools.product(*[spec[k] for k in keys])]


def _eval_spec(spec):
    """spec=(params, xspec, smin). Trả mảng (nB,6): close<=15, close<=60, tranche bằng nhau, ret sim (%), pnl sim, closed."""
    p, x, sm = spec
    out = np.zeros((len(G["all"]), 7))
    for k, B in enumerate(G["all"]):
        S = fs.simulate2(B, p, x, sm)
        if S is None:
            out[k] = [0, 0, 0, 0, 0, 0, 1.0]; continue
        ct = max(c["t"] for c in S["closes"]); dt = abs(ct - B["t1"]) / MINMS if S["closed"] else np.inf
        out[k] = [dt <= 15, dt <= 60, len(load.collapse(S["fills"])) == len(B["tranches"]), S["ret"], S["pnl"], S["closed"], max(1.0, (ct - B["t0"]) / MINMS)]
    return out


def xobj(R, ar, mask, ah=None):
    """R: (nP,nB,7); ar: act ret (nB,); ah: hold thật (phút, nB,); mask: bool (nB,). Trả (nP,) xobj.
    v2: trừ 0.1 x trung vị |ln(hold sim / hold thật)| (phạt mô hình thoát nhanh/chậm sai bậc độ lớn; tránh chọn mô hình chỉ khớp được nhóm lệnh thoát tức thì)."""
    m = mask
    c15 = R[:, m, 0].mean(1); c60 = R[:, m, 1].mean(1); le = R[:, m, 2].mean(1)
    a = ar[m]; s = R[:, m, 3]
    sc = s - s.mean(1, keepdims=True); ac = a - a.mean()
    den = np.sqrt((sc ** 2).sum(1) * (ac ** 2).sum())
    corr = np.where(den > 0, (sc * ac).sum(1) / np.where(den > 0, den, 1), 0.0)
    base = (c15 + c60) / 2 + 0.5 * np.maximum(corr, 0) + 0.25 * le
    if ah is not None:
        base = base - 0.1 * np.median(np.abs(np.log(R[:, m, 6] / np.maximum(ah[m], 1.0))), axis=1)
    return base


def _rows(baskets, spec):
    p, x, sm = spec
    return [match.basket_row(B, fs.simulate2(B, p, x, sm)) for B in baskets]


def _trim(m):
    r = run_bot._trim(m)
    return r


def hold_buckets(rows):
    """Khớp thoát theo nhóm thời gian giữ THẬT: cho biết mô hình khớp ở lệnh thoát nhanh hay lệnh giữ lâu."""
    out = []
    for nm, lo, hi in (("<1h", 0, 60), ("1-6h", 60, 360), ("6-24h", 360, 1440), (">24h", 1440, 1e12)):
        rr = [r for r in rows if "sim_ret" in r and lo <= (r["act_close"]["t"] - r["t0"]) / MINMS < hi]
        if not rr:
            out.append(dict(bucket=nm, n=0)); continue
        dt = np.array([abs(r["sim_close"]["t"] - r["act_close"]["t"]) / MINMS if r["sim_closed"] else np.inf for r in rr])
        hs = np.array([(r["sim_close"]["t"] - r["t0"]) / MINMS for r in rr])
        out.append(dict(bucket=nm, n=len(rr), close15_pct=round(100 * float(np.mean(dt <= 15)), 1), close60_pct=round(100 * float(np.mean(dt <= 60)), 1), sim_hold_med_h=round(float(np.median(hs)) / 60, 2),
                        sign_agree_pct=round(100 * float(np.mean([np.sign(r["act_ret"]) == np.sign(r["sim_ret"]) for r in rr])), 1)))
    return out


def _report(baskets, spec, hold_train):
    rows = _rows(baskets, spec)
    m = match.level_a(rows)
    return rows, _trim(m), fs.extra_metrics(rows, hold_train)


# ------------------------------------------------------------------ họ Level A
def A_families(bc, gi, ref_syms):
    """Danh sách (tên, ghi chú, [spec...]) với spec=(params, xspec, smin). Lưới = số tròn + phân vị TRAIN."""
    uq = lambda a: sorted({round(float(x), 3) for x in a if x and x > 0})
    SLp = uq([0.5, 0.75, 1, 1.5, 2, 3, 5] + gi["sl_q"]); TPp = uq([0.5, 1, 1.5, 2, 3, 5, 8] + gi["tp_q"])
    SLa = uq([0.5, 0.75, 1, 1.5, 2, 3] + gi["sl_atr_q"]); TPa = uq([0.5, 1, 1.5, 2, 3, 5] + gi["tp_atr_q"])
    Ts = [0.5, 1, 2, 3, 4, 6, 8, 12, 24, 48]
    mx = lambda h: int(h * 60)
    F = []
    F.append(("N0_null_timestop", "Mốc rỗng: 1 fill, không add/SL/TP; time-stop tại bội của trung vị thời gian giữ train (ngẫu nhiên có cấu trúc).",
              [(dict(maxhold=int(gi["hold_med_h"] * 60 * k)), None, None) for k in (0.25, 0.5, 1, 2, 4)]))
    F.append(("A1_TP_SL_pct", "SL % và TP % cố định từ giá TB (đóng cả rổ).",
              [(dict(tp=tp, sl=sl), None, None) for tp in [0] + TPp for sl in [0] + SLp if tp or sl]))
    F.append(("A2_TP_SL_ATR", "SL và TP là bội số ATR%(1h,14) tại fill đầu.",
              [(dict(tp=tp, tp_scale=1, sl=sl, sl_scale=1), None, None) for tp in [0] + TPa for sl in [0] + SLa if tp or sl]))
    F.append(("A3_SL_trailing", "SL (%/ATR) + trailing từ đỉnh (kích hoạt khi lãi >= act, lùi dist), không TP.",
              [(dict(sl=sl, tr_act=a, tr_dist=d), None, None) for sl in [0] + SLp for a in (0.5, 1, 2, 3) for d in (0.25, 0.5, 1, 2)]
              + [(dict(sl=sl, sl_scale=1, tr_act=a, tr_dist=d, tr_scale=1), None, None) for sl in [0] + SLa for a in (0.5, 1, 2) for d in (0.25, 0.5, 1, 1.5)]))
    F.append(("A4_cut_if_not_profit_after_T", "Cắt nếu CHƯA CÓ LÃI sau T giờ (kiểm tra mỗi nến hoặc chỉ đúng tại T) + SL/TP tuỳ chọn. Giả thuyết 'cắt lệnh thua sau ~2h'.",
              [(dict(tx_bars=mx(T), tx_gate=2, tx_once=o, sl=sl, tp=tp), None, None) for T in Ts for o in (0, 1) for sl in [0] + SLp[1:5] for tp in [0] + TPp[1:5]]))
    F.append(("A5_take_profit_after_T", "Chốt nếu ĐANG LÃI sau T giờ (time-exit có cổng lãi) + SL.",
              [(dict(tx_bars=mx(T), tx_gate=1, tx_thr=thr, sl=sl), None, None) for T in Ts for thr in (0.0, 0.5, 1.0) for sl in [0] + SLp[1:5]]))
    inds = [("ema", 20), ("ema", 50), ("bb", 20), ("vwap", 0), ("rsi", 14), ("ema_x", 9)]
    tfs = (5, 15, 60, 240)
    xs = [(i, n, tf, dr, ref) for (i, n) in inds for tf in tfs for dr in ("against", "with") for ref in ["self"] + list(ref_syms)]
    xs += [("donch", n_, tf, "against", ref) for n_ in (5, 10, 20) for tf in (15, 60, 240) for ref in ["self"]]
    xs += [("shock", thr, tf, "against", ref) for thr in (1.5, 2.5, 4.0) for tf in (5, 15) for ref in ["self"] + list(ref_syms)]
    F.append(("A6_indicator_exit", "Thoát khi nến ĐÓNG (5m/15m/1h) cắt EMA/BB-mid/VWAP ngày/RSI50/EMA chéo: 'against' = cắt ngược chiều (trend-follow exit), 'with' = cắt thuận chiều (mean-rev chốt); "
                                   "ref=BTC dùng chỉ báo của BTC (thị trường chung); cổng 0=mọi lúc,1=chỉ khi lãi,2=chỉ khi lỗ; + SL rộng tuỳ chọn.",
              [(dict(xgate=g, xmin=xm, sl=sl), x, None) for x in xs for g in (0, 1, 2) for xm in (0, 15) for sl in (0, 2.0)]))
    F.append(("A8_breakeven_stop", "SL % / ATR + dời SL về hoà vốn sau khi lãi đạt be_act (giải thích giveback nhỏ của lệnh thắng) + TP/trailing tuỳ chọn.",
              [(dict(sl=sl, sl_scale=sc_, be_act=ba, be_scale=sc_, be_off=off, tp=tp, tp_scale=sc_), None, None) for sc_, SLs, BAs, TPs in ((0, SLp, (0.5, 1, 1.5, 2, 3), [0] + TPp[1:5]), (1, SLa, (0.5, 1, 1.5, 2), [0] + TPa[1:4]))
               for sl in SLs for ba in BAs for off in (0.0, 0.2) for tp in TPs]))
    if bc["adds"]:
        stp = uq([0.5, 0.75, 1, 1.25, 1.5, 2, 3] + [round(x, 2) for x in [gi.get("add_step_med")] if x])
        MLs = [m for m in bc["maxL_grid"] if m > 1]
        dca = [dict(add_ref=ar_, step=st, maxL=ml, size_mult=sz, size_ref=1, tp=tp) for ar_ in (0, 1, 2) for st in stp for ml in MLs for sz in (0.33, 0.7, 1.0) for tp in TPp[:6]]
        F.append(("D1_DCA_TP", "DCA: add khi giá đi ngược %step so với fill gần nhất/đầu/TB (tối đa maxL fill, size add = size x notional fill đầu) + TP % từ giá TB đóng cả rổ.",
                  [(p, None, None) for p in dca]))
        dca2 = [dict(add_ref=ar_, step=st, maxL=ml, size_mult=sz, size_ref=1, tp=tp, sl=sl) for ar_ in (0, 2) for st in stp[2:6] for ml in MLs[:4] for sz in (0.5, 1.0) for tp in TPp[:5] for sl in (3, 5, 8)]
        F.append(("D2_DCA_TP_SL", "DCA + TP % + SL % từ giá TB (SL rộng, bảo hiểm chuỗi dài).", [(p, None, None) for p in dca2]))
        dca3 = [dict(add_ref=ar_, step=st, maxL=ml, size_mult=sz, size_ref=1, tx_bars=int(T * 60), tx_gate=g) for ar_ in (0, 2) for st in stp[2:6] for ml in MLs[:4] for sz in (0.5, 1.0) for T in (6, 24, 48) for g in (1,)]
        F.append(("D3_DCA_profit_after_T", "DCA + chốt toàn rổ khi đang lãi sau T giờ (time-exit có cổng lãi).", [(p, None, None) for p in dca3]))
    SLr = [10, 15, 20, 25, 27, 30, 35, 40, 50, 60, 80, 100]; TPr = [0, 10, 20, 30, 50, 75, 100, 150]
    F.append(("A9_ROI_SL_TP", "SL/TP tính theo ROI trên ký quỹ (% giá = ROI / đòn bẩy): phát hiện từ dữ liệu: lỗ đóng của lệnh thua tập trung ở ROI giá -27% (PW) và -25..-36%/-50% (M Power7).",
              [(dict(sl_roi=sl, tp_roi=tp), None, None) for sl in [0] + SLr for tp in TPr if sl or tp]))
    F.append(("A7_session_exit", "Thoát theo phiên Mỹ: 13:30 UTC (mở), 14:00, 20:00 (đóng), 21:00 UTC, có cổng lãi/lỗ, tối thiểu smin phút sau vào + SL.",
              [(dict(sgate=g, smin=sm, sl=sl), None, mod) for mod in (810, 840, 1200, 1260) for g in (0, 1, 2) for sm in (30, 120, 360) for sl in (0, 1.5, 3.0)]))
    return F


def _best(R, specs, ar, mask):
    sc = xobj(R, ar, mask, G["ah"])
    k = int(np.argmax(sc))
    return k, float(sc[k]), sc


def _par_eval(specs, pool):
    res = pool.map(_eval_spec, specs, chunksize=max(1, len(specs) // 64))
    return np.stack(res)


def _spec_words(spec):
    p, x, sm = spec
    s = []
    if p.get("maxL", 1) > 1: s.append(f"add: bước {p.get('step')}{'xATR' if p.get('step_scale') else '%'} từ {['fill gần nhất', 'fill đầu', 'giá TB'][int(p.get('add_ref', 0))]}, tối đa {int(p['maxL'])} fill, size add {p.get('size_mult', 0.33)}x notional {'fill đầu' if p.get('size_ref', 1) == 1 else 'fill trước'}")
    if p.get("sl_roi"): s.append(f"SL theo ROI {p['sl_roi']}% ký quỹ (= giá {p['sl_roi']}/đòn bẩy %)")
    if p.get("tp_roi"): s.append(f"TP theo ROI {p['tp_roi']}% ký quỹ (= giá {p['tp_roi']}/đòn bẩy %)")
    if p.get("tp"): s.append(f"TP {p['tp']}{'xATR%' if p.get('tp_scale') else '%'} từ {'giá TB' if p.get('tp_ref', 0) == 0 else 'fill đầu'}")
    if p.get("sl"): s.append(f"SL {p['sl']}{'xATR%' if p.get('sl_scale') else '%'} từ {'giá TB' if p.get('sl_ref', 0) == 0 else 'fill đầu'}")
    if p.get("be_act"): s.append(f"dời SL về hoà vốn{' +' + str(p['be_off']) + '%' if p.get('be_off') else ''} sau khi lãi {p['be_act']}{'xATR%' if p.get('be_scale') else '%'}")
    if p.get("tr_act"): s.append(f"trailing: kích hoạt khi lãi {p['tr_act']}{'xATR%' if p.get('tr_scale') else '%'}, lùi {p['tr_dist']}{'xATR%' if p.get('tr_scale') else '%'} từ đỉnh")
    if p.get("maxhold"): s.append(f"time-stop {p['maxhold']/60:.1f} giờ")
    gname = {0: "mọi lúc", 1: "chỉ khi đang lãi", 2: "chỉ khi chưa có lãi"}
    if p.get("tx_bars"): s.append(f"time-exit sau {p['tx_bars']/60:.1f} giờ ({gname[int(p['tx_gate'])]}, ngưỡng {p.get('tx_thr', 0)}%{', chỉ kiểm tra đúng tại T' if p.get('tx_once') else ''})")
    if x: s.append(f"thoát khi nến {x[2]}m đóng cắt {x[0]}{x[1] if x[1] else ''} ({'ngược' if x[3] == 'against' else 'thuận'} chiều vị thế, chỉ báo của {x[4]}; {gname[int(p.get('xgate', 0))]})")
    if sm is not None: s.append(f"thoát tại {sm // 60:02d}:{sm % 60:02d} UTC ({gname[int(p.get('sgate', 0))]}, sau >= {int(p.get('smin', 0))} phút)")
    return "Vào = fill đầu thật; " + "; ".join(s) + "." if s else "Vào = fill đầu thật; không thoát (mark-to-market)."


def run_level_a(name, allb, train, test, tr_idx, te_idx, bc, pool, quick, tag=""):
    """Chạy toàn bộ họ + forward-selection trên 1 danh sách basket. Trả (iterations, best (spec,k), cache)."""
    gi = derive_grid_inputs(train); gi.update(bc.get("gi_extra", {}))
    ar = np.array([B["ret"] for B in allb])
    mask_tr = np.zeros(len(allb), bool); mask_tr[tr_idx] = True
    hold_train = fs.hold_minutes(train)
    fams = A_families(bc, gi, bc["sym_ref"])
    reps_b = 60 if quick else (100 if len(allb) > 100 else 200)
    base_te = fs.rand_exit_baseline(test, hold_train, reps=reps_b, seed=1); base_tr = fs.rand_exit_baseline(train, hold_train, reps=reps_b, seed=2)
    print(f"{tag}random-exit baseline TEST: {json.dumps(base_te)}", flush=True)
    iters = []; best_by_fam = {}
    t_all = time.time()
    for nm, note, specs in fams:
        if quick: specs = specs[::max(1, len(specs) // 60)]
        t = time.time()
        R = _par_eval(specs, pool)
        k, sc, scs = _best(R, specs, ar, mask_tr)
        spec = specs[k]
        rows_tr, m_tr, ex_tr = _report(train, spec, hold_train); rows_te, m_te, ex_te = _report(test, spec, hold_train)
        it = dict(model=nm, note=note, params=dict(spec[0], xspec=spec[1], session_minute_utc=spec[2]), n_grid=len(specs), xobj_train=round(sc, 4),
                  train=m_tr, test=m_te, extra_train=ex_tr, extra_test=ex_te, words=_spec_words(spec), secs=round(time.time() - t, 1))
        iters.append(it); best_by_fam[nm] = (spec, sc, R, specs)
        print(f"{tag}{nm}: grid {len(specs)} xobj_train {sc:.3f} | TEST close15 {m_te.get('close_match_15')} close60 {m_te.get('close_match_60')} corr {m_te.get('pnl_corr')} "
              f"sign {m_te.get('pnl_sign_agree')} holdErr {ex_te.get('hold_med_abs_log_ratio')} | {it['words'][:150]} ({it['secs']}s)", flush=True)
    # --- forward selection trên mô hình tốt nhất theo TRAIN
    cand = {k: v for k, v in best_by_fam.items() if k != "N0_null_timestop"}
    top = max(cand, key=lambda k: cand[k][1])
    cur, cur_sc = cand[top][0], cand[top][1]
    SLp = [0.75, 1, 1.5, 2, 3, 5]; TPp = [0.75, 1, 1.5, 2, 3, 5]
    thr_gain = 2.0 / len(train)      # thành phần mới phải tăng xobj >= 2 basket train (chống overfit mẫu nhỏ)
    for rnd in range(3):
        p0, x0, s0 = cur
        comps = {}
        comps["+SL"] = [(dict(p0, sl=v, sl_scale=sc_), x0, s0) for sc_, vs in ((0, SLp), (1, [0.5, 1, 1.5, 2, 3])) for v in vs]
        comps["+SL_roi"] = [(dict(p0, sl_roi=v), x0, s0) for v in (15, 20, 25, 27, 30, 35, 50)]
        comps["+TP_roi"] = [(dict(p0, tp_roi=v), x0, s0) for v in (20, 30, 50, 75, 100, 150)]
        comps["+TP"] = [(dict(p0, tp=v, tp_scale=sc_), x0, s0) for sc_, vs in ((0, TPp), (1, [0.5, 1, 2, 3, 5])) for v in vs]
        comps["+trail"] = [(dict(p0, tr_act=a, tr_dist=d, tr_scale=sc_), x0, s0) for sc_ in (0, 1) for a in ((0.5, 1, 2) if sc_ else (0.5, 1, 2, 3)) for d in (0.25, 0.5, 1, 1.5)]
        comps["+cut_if_not_profit"] = [(dict(p0, tx_bars=int(T * 60), tx_gate=2, tx_once=o), x0, s0) for T in (1, 2, 4, 8, 24) for o in (0, 1)]
        comps["+indicator"] = [(dict(p0, xgate=g, xmin=xm), (i, n, tf, dr, ref), s0) for (i, n) in (("ema", 20), ("ema", 50), ("vwap", 0), ("rsi", 14)) for tf in (15, 60)
                               for dr in ("against", "with") for ref in ["self"] + list(bc["sym_ref"]) for g in (0, 1, 2) for xm in (0, 15)]
        comps["+breakeven"] = [(dict(p0, be_act=ba, be_scale=sc_, be_off=off), x0, s0) for sc_, bas in ((0, (0.5, 1, 2, 3)), (1, (0.5, 1, 2))) for ba in bas for off in (0.0, 0.2)]
        comps["+session"] = [(dict(p0, sgate=g, smin=sm), x0, mod) for mod in (810, 1200) for g in (0, 1, 2) for sm in (30, 120, 360)]
        if bc["adds"]:
            comps["+adds"] = [(dict(p0, add_ref=ar_, step=st, step_scale=ss, maxL=ml, size_mult=sz, size_ref=1), x0, s0)
                              for ar_ in (0, 1, 2) for (st, ss) in ((0.5, 0), (1.0, 0), (1.5, 0), (2.5, 0), (0.5, 1), (1.0, 1)) for ml in bc["maxL_grid"] if ml > 1 for sz in (0.33, 0.7, 1.0)]
        added = None
        for cn, specs in comps.items():
            if not specs: continue
            if quick: specs = specs[::max(1, len(specs) // 40)]
            R = _par_eval(specs, pool); k, sc, _ = _best(R, specs, ar, mask_tr)
            if sc > cur_sc + thr_gain and (added is None or sc > added[1]):
                added = (cn, sc, specs[k])
        if added is None:
            iters.append(dict(model=f"R{rnd + 1}_stop", note="không thành phần nào tăng xobj train >= 2/n_train -> dừng forward-selection.", params=dict(cur[0], xspec=cur[1], session_minute_utc=cur[2]), xobj_train=round(cur_sc, 4)))
            break
        cn, sc, spec = added
        rows_tr, m_tr, ex_tr = _report(train, spec, hold_train); rows_te, m_te, ex_te = _report(test, spec, hold_train)
        it = dict(model=f"R{rnd + 1}_best{cn}", note=f"forward-selection vòng {rnd + 1}: thêm thành phần {cn} vào mô hình tốt nhất (chỉ giữ vì xobj train tăng {sc - cur_sc:+.3f} >= 2/n_train = {thr_gain:.3f}).",
                  params=dict(spec[0], xspec=spec[1], session_minute_utc=spec[2]), n_grid=len(comps[cn]), xobj_train=round(sc, 4), train=m_tr, test=m_te, extra_train=ex_tr, extra_test=ex_te,
                  words=_spec_words(spec), secs=0)
        iters.append(it); cur, cur_sc = spec, sc
        print(f"{tag}R{rnd + 1} {cn}: xobj {sc:.3f} | TEST close15 {m_te.get('close_match_15')} close60 {m_te.get('close_match_60')} corr {m_te.get('pnl_corr')} sign {m_te.get('pnl_sign_agree')} | {it['words'][:200]}", flush=True)
    for it in iters:
        if "test" in it:
            t_ = it["test"]
            it["beats_random_p95_test"] = dict(close_match_15=bool((t_.get("close_match_15") or 0) > base_te["close_match_15"]["p95"]), close_match_60=bool((t_.get("close_match_60") or 0) > base_te["close_match_60"]["p95"]),
                                               pnl_corr=bool((t_.get("pnl_corr") or 0) > base_te["pnl_corr"]["p95"]))
    print(f"{tag}Level A done in {time.time() - t_all:.0f}s", flush=True)
    return iters, cur, cur_sc, best_by_fam, gi, hold_train, dict(test=base_te, train=base_tr)


# ------------------------------------------------------------------ LOO (Professor-Wang)
def loo_eval(allb, best_by_fam, ar):
    """Với mỗi họ: chọn tham số (xobj) trên n-1 basket, lấy kết quả sim của tham số đó trên basket bị loại; gộp -> Level A trên toàn bộ n basket 'ngoài mẫu'."""
    res = []
    n = len(allb)
    for nm, (spec, sc, R, specs) in best_by_fam.items():
        held = []; picks = []
        for i in range(n):
            m = np.ones(n, bool); m[i] = False
            k = int(np.argmax(xobj(R, ar, m, G["ah"])))
            picks.append(k); held.append(specs[k])
        rows = [match.basket_row(allb[i], fs.simulate2(allb[i], held[i][0], held[i][1], held[i][2])) for i in range(n)]
        m_ = _trim(match.level_a(rows))
        ex = fs.extra_metrics(rows, fs.hold_minutes(allb))
        stab = Counter(picks).most_common(1)[0][1] / n
        pb = [dict(id=allb[i]["id"], sym=allb[i]["sym"], side=allb[i]["side"], t0=allb[i]["t0"], act_hold_min=round((rows[i]["act_close"]["t"] - rows[i]["t0"]) / MINMS, 1),
                   sim_hold_min=round((rows[i]["sim_close"]["t"] - rows[i]["t0"]) / MINMS, 1), act_ret=rows[i]["act_ret"], sim_ret=rows[i]["sim_ret"],
                   match15=bool(rows[i]["sim_closed"] and abs(rows[i]["sim_close"]["t"] - rows[i]["act_close"]["t"]) <= 15 * MINMS), picked=_spec_words(held[i])) for i in range(n)]
        res.append(dict(model=nm, loo=m_, extra=ex, pick_stability=round(stab, 2), n_distinct_picks=len(set(picks)), per_basket=pb))
        print(f"LOO {nm}: close15 {m_.get('close_match_15')} close60 {m_.get('close_match_60')} corr {m_.get('pnl_corr')} sign {m_.get('pnl_sign_agree')} stability {stab:.2f}", flush=True)
    return res


# ------------------------------------------------------------------ LEVEL B / C
def entry_rules(bot_gate):
    prms = [("orb", (810, rm, wm)) for rm in (30, 60) for wm in (120, 240)]
    prms += [("nsig", (k, thr, md)) for k in (1, 4, 16) for thr in (0.5, 1.0, 1.5, 2.0, 3.0) for md in ("mom", "contra")]
    prms += [("dist", (ind, thr, md)) for ind in ("vwap", "ema20") for thr in (0.3, 0.6, 1.0, 1.5) for md in ("mom", "contra")]
    prms += [("pull", ("ema", n, tr)) for n in (20, 50) for tr in (False, True)] + [("pull", ("vwap", 0, tr)) for tr in (False, True)]
    prms += [("pday", ("mom",)), ("pday", ("rev",))]
    rules = []
    for fam, prm in prms:
        for ref in ([None, "BTC"] if fam in ("nsig", "pull", "pday", "dist") else [None]):
            for hrs, us in ((None, False), (bot_gate, False), (None, True)):
                for cool in (1, 6, 24):
                    rules.append(dict(fam=fam, prm=prm, hours=hrs, us=us, cool_h=cool, ref=ref))
    return rules


def _sigs(rule, syms, lo, hi):
    out = {}
    if rule.get("ref"):     # tín hiệu của mã tham chiếu (BTC = thị trường chung) áp cho mọi mã của bot
        l, sh = fs.entry_signals(rule["ref"], rule, lo, hi)
        for s in syms:
            if len(l): out[(s, "long")] = l
            if len(sh): out[(s, "short")] = sh
        return out
    for s in syms:
        if load.candle_arrays(s) is None: continue
        l, sh = fs.entry_signals(s, rule, lo, hi)
        if len(l): out[(s, "long")] = l
        if len(sh): out[(s, "short")] = sh
    return out


def _any_side(d):
    o = {}
    for (s, _), v in d.items(): o.setdefault((s, "any"), []).append(v)
    return {k: np.sort(np.concatenate(v)) for k, v in o.items()}


def level_b_entries(allb, split_t, quick):
    act_tr, act_te = {}, {}
    for B in allb:
        (act_tr if B["t0"] < split_t else act_te).setdefault((B["sym"], B["side"]), []).append(B["t0"])
    act_tr = {k: np.array(sorted(v), np.int64) for k, v in act_tr.items()}; act_te = {k: np.array(sorted(v), np.int64) for k, v in act_te.items()}
    syms = sorted({B["sym"] for B in allb})
    t_lo = min(B["t0"] for B in allb); t_hi = max(B["t0"] for B in allb) + 15 * MINMS
    hh = np.bincount(((np.array([B["t0"] for B in allb if B["t0"] < split_t]) // H + 7) % 24).astype(int), minlength=24).astype(float) + 0.5; hh /= hh.sum()
    top = int(np.argsort(-np.convolve(np.r_[hh, hh[:3]], np.ones(4), "valid")[:24])[0]); gate = [(top + i) % 24 for i in range(4)]
    rules = entry_rules(gate)
    if quick: rules = rules[::6]
    fit = []
    for rule in rules:
        m = match.level_b(act_tr, _sigs(rule, syms, t_lo, split_t), t_lo, split_t, reps=12, seed=1, hour_hist=hh)
        fit.append((match.f1_excess(m), rule, m))
    best_by = {}
    for sc, rule, m in fit:
        k = (rule["fam"], (rule["prm"][-1] if rule["fam"] in ("nsig", "pday", "dist") else rule["fam"]), rule.get("ref") or "self")
        if k not in best_by or sc > best_by[k][0]: best_by[k] = (sc, rule, m)
    allbest = max(fit, key=lambda x: x[0])
    res = dict(gate_hours_vn=gate, n_rules=len(rules), train_window=[t_lo, split_t], test_window=[split_t, t_hi], per_family=[],
               note=("Luật chọn theo F1(+-15p) vượt baseline trên TRAIN; chỉ coi là 'khớp' khi TEST recall VÀ precision (+-15p) đều > p95 của cả baseline ngẫu nhiên đều và baseline giờ-khớp "
                     "VÀ lift >= 3 và recall15 >= 30%. Tín hiệu chỉ tính trên các mã bot từng giao dịch (như harness)."))
    for k, (sc, rule, m) in sorted(best_by.items(), key=lambda kv: -kv[1][0]):
        tr = match.level_b(act_tr, _sigs(rule, syms, t_lo, split_t), t_lo, split_t, reps=200, seed=2, hour_hist=hh)
        te = match.level_b(act_te, _sigs(rule, syms, split_t, t_hi), split_t, t_hi, reps=200, seed=3, hour_hist=hh)
        res["per_family"].append(dict(feat=f"{rule['fam']}{rule['prm']}", mode=f"{k[1]}/{k[2]}", rule=rule, train_f1_excess=round(sc, 4), train=tr, test=te))
    best = [d for d in res["per_family"] if d["rule"] == allbest[1]][0]
    res["best_rule_by_train"] = best
    # chiều bất kỳ (chỉ đo thời điểm + mã, bỏ qua chiều long/short)
    r = best["rule"]
    te_any = match.level_b(_any_side(act_te), _any_side(_sigs(r, syms, split_t, t_hi)), split_t, t_hi, reps=100, seed=4, hour_hist=hh)
    res["best_rule_any_side_test"] = te_any
    res["hour_hist_vn_train"] = [round(float(x), 4) for x in hh]
    return res, hh, act_te, syms, t_hi


def level_c(allb, best_spec, rule, split_t, t_hi, syms, hh, n_rand=20, hold_med_min=None):
    """Chạy tự do: tín hiệu vào tốt nhất (train) + thoát tốt nhất; so lợi suất/lệnh & số lệnh với bot thật trong cửa sổ TEST; baseline: cùng số lệnh vào ngẫu nhiên (cùng mã/chiều)."""
    p, x, sm = best_spec
    te_act = [B for B in allb if B["t0"] >= split_t]
    notional = float(np.median([B["tranches"][0]["notional"] for B in allb])); lev0 = float(np.median([B["lev"] for B in allb]))
    sig = _sigs(rule, syms, split_t, t_hi)
    rets = []
    for (s, side), ts in sig.items():
        for t in ts:
            S = fs.free_run(s, side, int(t), notional, p, x, sm, lev=lev0)
            if S is not None: rets.append(S["ret"])
    rng = np.random.default_rng(5); rr = []
    for _ in range(n_rand):
        rs = []
        for (s, side), ts in sig.items():
            u = rng.uniform(split_t, t_hi - 14 * 24 * H if t_hi - split_t > 14 * 24 * H else t_hi, len(ts))
            for t in u:
                S = fs.free_run(s, side, int(t), notional, p, x, sm, lev=lev0)
                if S is not None: rs.append(S["ret"])
        if rs: rr.append((np.mean(rs), np.mean(np.array(rs) > 0), len(rs)))
    ar = np.array([B["ret"] for B in te_act]); days = (t_hi - split_t) / (24 * H)
    return dict(n_sim_trades=len(rets), n_actual_trades=len(te_act), sim_trades_per_day=round(len(rets) / days, 2), act_trades_per_day=round(len(te_act) / days, 2),
                sim_mean_ret_pct=round(float(np.mean(rets)), 3) if rets else None, sim_win_pct=round(100 * float(np.mean(np.array(rets) > 0)), 1) if rets else None,
                sim_sum_ret_pct=round(float(np.sum(rets)), 1) if rets else None, act_mean_ret_pct=round(float(ar.mean()), 3), act_win_pct=round(100 * float((ar > 0).mean()), 1),
                act_sum_ret_pct=round(float(ar.sum()), 1),
                random_entry_mean_ret_pct_mean=round(float(np.mean([r[0] for r in rr])), 3) if rr else None,
                random_entry_mean_ret_pct_p95=round(float(np.percentile([r[0] for r in rr], 95)), 3) if rr else None,
                random_entry_win_pct_mean=round(100 * float(np.mean([r[1] for r in rr])), 1) if rr else None,
                note=("Vào ở open nến 1m kế tiếp sau tín hiệu, notional = trung vị notional tranche đầu của bot, thoát = mô hình Level A tốt nhất, horizon 14 ngày, phí 3.5bps/chiều. "
                      "Không điều kiện hoá theo fill thật -> đo xem chiến lược tái tạo có lợi nhuận cùng cỡ & cùng dấu với bot không (không phải khớp từng lệnh)."))


# ------------------------------------------------------------------ chủ đề (Dark-Wood-Dahlia)
THEMES = dict(memory_semis=["SNDK", "MU", "SKHYNIX", "SKHY", "DRAM", "SOXL", "QCOM", "MRVL", "NVDA", "AMD", "LITE", "AAOI"],
              meme=["PEPE", "TRUMP", "WIF", "PUMP", "USELESS"], majors=["BTC", "ETH", "SOL"], commod=["XAU", "XAG", "CL"])


def theme_analysis(allb):
    """Với mỗi basket thuộc chủ đề: có basket khác (mã khác trong cùng chủ đề, cùng chiều) mở trong +-60 phút? So với baseline: dịch ngẫu nhiên thời điểm mở (uniform theo giờ-VN-khớp)."""
    out = {}
    rng = np.random.default_rng(1)
    lo = min(B["t0"] for B in allb); hi = max(B["t0"] for B in allb)
    for th, syms in THEMES.items():
        mem = [B for B in allb if B["sym"] in syms]
        if len(mem) < 4: continue
        def frac(times):
            n = 0
            for i, B in enumerate(mem):
                for j, C in enumerate(mem):
                    if i != j and C["sym"] != B["sym"] and C["side"] == B["side"] and abs(times[j] - times[i]) <= 60 * MINMS:
                        n += 1; break
            return n / len(mem)
        real = frac([B["t0"] for B in mem])
        # baseline: giữ giờ trong ngày thật, hoán vị ngày giữa các basket
        base = []
        t0 = np.array([B["t0"] for B in mem]); day = (t0 // (24 * H)); tod = t0 % (24 * H)
        for _ in range(200):
            d2 = rng.permutation(day); base.append(frac(list(d2 * 24 * H + tod)))
        out[th] = dict(n_baskets=len(mem), syms=sorted({B["sym"] for B in mem}), real_pct=round(100 * real, 1), shuffled_day_mean_pct=round(100 * float(np.mean(base)), 1),
                       shuffled_day_p95_pct=round(100 * float(np.percentile(base, 95)), 1), above_p95=bool(real > np.percentile(base, 95)))
    # chủ đề chéo: SNDK/MU/SKHYNIX cùng chiều trong +-24h (bot nhìn là 1 chủ đề đa ngày)
    return out


# ------------------------------------------------------------------ đại diện, verdict
def representative(rows, k=4):
    ok = [r for r in rows if "sim_ret" in r and r.get("split") == "test"]
    if not ok: return []
    dt = lambda r: abs(r["sim_close"]["t"] - r["act_close"]["t"]) / MINMS if r["sim_closed"] else 1e9
    picks = []
    for nm, key in (("khớp gần nhất (thoát)", lambda r: dt(r)), ("lãi/lỗ thật lớn nhất", lambda r: -abs(r["act_pnl"])), ("trung vị lệch thoát", None), ("lệch xa nhất", lambda r: -dt(r))):
        if key is None:
            srt = sorted(ok, key=dt); r = srt[len(srt) // 2]
        else:
            r = min(ok, key=key)
        if all(r["id"] != p["id"] for p in picks):
            picks.append(dict(why=nm, id=r["id"], sym=r["sym"], side=r["side"], t0=r["t0"], act_fills=r["act_adds"], act_close=r["act_close"], sim_close=r.get("sim_close"),
                              sim_closed=r["sim_closed"], dt_close_min=round(dt(r), 1) if dt(r) < 1e8 else None, act_ret=r["act_ret"], sim_ret=r["sim_ret"],
                              sim_fills=r.get("sim_adds"), act_closes=r["act_closes"], sim_closes=r.get("sim_closes")))
    return picks[:k]


def build_evidence(ev, loo, ev_base=None):
    """Bằng chứng suy luận tự động từ chẩn đoán (có số)."""
    out = []
    lt = ev.get("loser_time_concentration")
    if lt:
        out.append(f"Thời gian giữ lệnh con thua: phân vị 10/25/50/75/90 = {lt['loser']['hold_h_q10_25_50_75_90']} giờ; cửa sổ [T,1.25T] dày nhất chỉ chứa {lt['loser']['max_share_in_window_T_to_1_25T']}% lệnh thua (T={lt['loser']['at_T_h']}h), "
                   f"{lt['loser']['share_in_1_5_to_2_5h']}% rơi vào 1,5-2,5h -> trung vị 'cắt lệnh thua ~2h' trong summary là trung vị của phân phối rộng, KHÔNG phải time-stop cố định.")
    if ev_base and ev_base.get("n_tranche_adds", 0) >= 20:
        q = ev_base["step_adverse_pct_q_last"]; a = ev_base["add_over_first_notional_q"]
        out.append(f"Add (tranche, n={ev_base['n_tranche_adds']}): bước ngược so với tranche trước phân vị 10/25/50/75/90 = {q} % (CV vững {ev_base['step_robust_cv_last']}) -> bước KHÔNG cố định; "
                   f"khoảng cách giữa các tầng phân vị {ev_base['gap_min_to_prev_tranche_q']} phút; add/notional đầu {a}; {ev_base['pct_multifill_baskets_closed_all_at_once']}% rổ nhiều tầng đóng cùng lúc.")
    uw = {u["T_h"]: u for u in ev["underwater_at_T"]}
    far = [u for u in ev["underwater_at_T"] if u["T_h"] >= 3 and u["n_open"] >= 8]
    if far:
        out.append(f"Cắt-nếu-chưa-lãi-sau-T: tại T>=3h vẫn còn {min(u['underwater_pct'] for u in far):.0f}-{max(u['underwater_pct'] for u in far):.0f}% vị thế còn mở đang lỗ so với giá vào "
                   f"(n_mở tại 3h={uw.get(3, {}).get('n_open')}); nếu có luật time-stop-lỗ thì phải ~0% -> KHÔNG có luật cắt theo thời gian.")
    b = ev["batch_close_other_symbol_within_2min"]; o = ev["batch_open_other_symbol_within_2min"]
    sh = ev.get("session_hazard", {})
    h = sh.get("13:30 mở cửa Mỹ", {})
    if h:
        parts = []
        for cat in ("stock_perp", "crypto"):
            if cat in h:
                ctrl = [v[cat]["closed_pct"] for k, v in sh.items() if k in ("07:00", "11:00", "17:00", "21:00") and cat in v]
                parts.append(f"{cat}: {h[cat]['closed_pct']}% (n={h[cat]['n_open']}) vs mốc kiểm soát 07/11/17/21h {ctrl}%")
        out.append("Hazard đóng quanh 13:30 UTC (+-5 phút) của lệnh con đang mở: " + "; ".join(parts) + " -> chỉ là xu hướng nhẹ nếu cao hơn kiểm soát vài lần ở mức vài %, không phải luật 'đóng tại 13:30'.")
    out.append(f"Đóng đồng loạt giữa các mã (+-2 phút): {b['real_pct']}% basket (ngẫu nhiên {b['random_uniform_pct_mean']}%, p95 {b['random_uniform_pct_p95']}%); mở đồng loạt {o['real_pct']}% (ngẫu nhiên {o['random_uniform_pct_mean']}%).")
    ec = ev["entry_context"]
    sig = [f"{k} z={v['z']} (thật {v['actual_median']} vs ngẫu nhiên p5-p95 {v['random_p5']}..{v['random_p95']})" for k, v in ec.items() if k != "note" and abs(v["z"]) >= 2.5]
    out.append("Bối cảnh vào lệnh khác ngẫu nhiên: " + ("; ".join(sig) if sig else "không có đặc trưng nào |z|>=2.5") + " (dương = thuận đà/thuận phía VWAP, âm = ngược đà/bắt hồi).")
    ca = ev["close_bar_alignment_pct"]
    out.append(f"Thoát canh nến đóng: <=90s sau mốc 5m {ca['within_90s_after_5m']}% (kỳ vọng {ca['expected_5m']}%), 15m {ca['within_90s_after_15m']}% ({ca['expected_15m']}%), 1h {ca['within_90s_after_1h']}% ({ca['expected_1h']}%).")
    sa = ev["session_alignment_pct"]
    hot = [f"{k}: đóng {v['close']}%/mở {v['open']}% (kỳ vọng {v['uniform_expected']}%)" for k, v in sa.items() if v["close"] >= 3 * v["uniform_expected"] or v["open"] >= 3 * v["uniform_expected"]]
    out.append("Canh phiên (+-10 phút): " + ("; ".join(hot) if hot else "không mốc nào cao gấp 3 lần kỳ vọng"))
    w = ev.get("win_giveback_pct_q"); wl = ev.get("win_ret_cv_robust")
    if w: out.append(f"Giveback lệnh thắng (MFE - lợi suất đóng) phân vị 25/50/75: {w} %; lãi đóng/ATR: {ev.get('win_ret_atr_q')} (CV vững {wl}); lỗ đóng/ATR: {ev.get('loss_ret_atr_q')} -> mức thoát KHÔNG cố định (không phải SL/TP % hay ATR cố định).")
    return out


DESIGN_ITERS = [
    "v0: họ A1-A7 (TP/SL %, ATR, trailing, cắt-nếu-chưa-lãi-sau-T, chốt-nếu-lãi-sau-T, thoát theo chỉ báo nến đóng 5m/15m/1h, thoát theo phiên) + forward-selection (ngưỡng tăng xobj 0.01). Kết quả: overfit mạnh trên PW "
    "(train thoát+-15p 58% -> test 7%).",
    "v1: thêm baseline thoát ngẫu nhiên (time-stop ngẫu nhiên theo phân bố giữ của train, 200 lần) và nhãn so với p95 baseline thay vì ngưỡng tuyệt đối (run_bot.verdict khen nhầm M Power7 vì nhiều lệnh thoát tức thì); "
    "ngưỡng forward-selection = 2 basket train.",
    "v2: xobj thêm phạt sai số log thời gian giữ; thêm A8 (hoà vốn), chỉ báo shock/Donchian/khung 4h, họ DCA D1-D3 cho bot có add, luật vào 'dist' (khoảng cách VWAP/EMA20 theo ATR), tín hiệu vào từ BTC áp cho mọi mã, Level C, LOO (PW), mức lệnh con (bot có add).",
    "v3: sau khi quan sát ROI giá của lệnh thua (PW: 3/11 lệnh thua cùng ROI giá -27.0/-27.2/-27.4% ở đòn bẩy 10 và 20; M Power7: dải -25..-36% và cụm ~-48..-51%), thêm A9 = SL/TP theo ROI ký quỹ (% giá = ROI/đòn bẩy).",
]


def finalize_schema(res):
    """Đưa về schema out/01pp.json: inference phẳng (+ khoá 'swing'), iteration_summary cùng khoá (null_train_score, null_test_score, best_by_train{model,train,test}, ...). Idempotent."""
    inf = res["inference"]
    if "harness" in inf:
        flat = dict(inf["harness"]); flat["swing"] = inf["swing"]; res["inference"] = flat
    its = [it for it in res["iterations"] if "test" in it]
    ms = [it for it in its if it["model"] != "N0_null_timestop"]
    null = next(it for it in its if it["model"] == "N0_null_timestop")
    b_te = max(ms, key=lambda it: it["test"].get("score", 0))
    bm = res["best_model"]["name"]; bi = next(it for it in its if it["model"] == bm)
    res["iteration_summary"] = dict(
        null_train_score=null["train"].get("score"), null_test_score=null["test"].get("score"),
        best_by_train=dict(model=bm, train=bi["train"].get("score"), test=bi["test"].get("score"), xobj_train=bi.get("xobj_train")),
        best_by_test_info_only=dict(model=b_te["model"], test=b_te["test"].get("score")),
        test_score_sequence=[[it["model"], it["test"].get("score")] for it in its],
        stop_rule=("Họ chạy lần lượt A1..A9 (+D1-D3 nếu bot có add); forward-selection tối đa 3 vòng, dừng khi thành phần mới không tăng xobj TRAIN >= 2/n_train (2 basket). "
                   "Mô hình cuối chọn theo xobj TRAIN (công thức ở docstring run_swing.py), KHÔNG theo TEST; 'score' = điểm harness match.score để so sánh với 01pp. Điểm TEST tốt nhất chỉ để tham khảo."))
    return res


def my_verdict(best, null, rb, lvb, lvc, loo):
    """Nhãn dựa trên TEST + so với baseline thoát ngẫu nhiên (p95) và mô hình rỗng; harness run_bot.verdict chỉ nhìn ngưỡng tuyệt đối nên dễ khen nhầm khi nhiều lệnh thoát rất nhanh."""
    t = best["test"]; ex = best["extra_test"]
    c15 = t.get("close_match_15") or 0; c60 = t.get("close_match_60") or 0; corr = t.get("pnl_corr") or 0; sign = t.get("pnl_sign_agree") or 0
    b15 = c15 > rb["close_match_15"]["p95"]; b60 = c60 > rb["close_match_60"]["p95"]; bc_ = corr > rb["pnl_corr"]["p95"]
    n15 = null["test"].get("close_match_15") or 0; n60 = null["test"].get("close_match_60") or 0
    if c15 >= 60 and b15 and corr >= 0.7: lab = "khớp tốt"
    elif b15 and b60 and c15 >= 25: lab = "khớp một phần"
    else: lab = "không tái tạo được"
    bb = lvb["best_rule_by_train"]["test"]
    why = (f"Level A TEST (điều kiện hoá theo fill đầu thật, n={t.get('n_baskets')}): mô hình tốt nhất theo TRAIN thoát +-15p {c15}% / +-60p {c60}% "
           f"(baseline thoát ngẫu nhiên cùng phân bố giữ: mean {rb['close_match_15']['mean']}% / {rb['close_match_60']['mean']}%, p95 {rb['close_match_15']['p95']}% / {rb['close_match_60']['p95']}%; "
           f"mô hình rỗng time-stop: {n15}% / {n60}%) -> {'VƯỢT' if (b15 and b60) else 'KHÔNG vượt'} p95 ngẫu nhiên. "
           f"Dấu PnL cùng {sign}% (ngẫu nhiên mean {rb['pnl_sign_agree']['mean']}%), corr lợi suất {corr} (ngẫu nhiên p95 {rb['pnl_corr']['p95']}), Spearman {ex.get('ret_spearman')}; "
           f"thời gian giữ trung vị thật {ex.get('hold_act_med_h')}h vs sim {ex.get('hold_sim_med_h')}h (sai số log {ex.get('hold_med_abs_log_ratio')}). "
           f"Level B (luật vào tốt nhất theo TRAIN, TEST): recall15 {bb['recall_15']}% / precision15 {bb['precision_15']}% vs baseline giờ-khớp "
           f"{bb.get('rand_hour_recall_15_mean')}% / {bb.get('rand_hour_precision_15_mean')}% (p95 {bb.get('rand_hour_recall_15_p95')}% / {bb.get('rand_hour_precision_15_p95')}%) -> {bb['strength']}. "
           f"Level C (chạy tự do): {lvc['n_sim_trades']} lệnh sim vs {lvc['n_actual_trades']} lệnh thật, lợi suất TB/lệnh sim {lvc['sim_mean_ret_pct']}% vs thật {lvc['act_mean_ret_pct']}% (vào ngẫu nhiên: {lvc['random_entry_mean_ret_pct_mean']}%).")
    if loo:
        bl = max(loo["per_family"], key=lambda d: (d["loo"].get("close_match_15") or 0) + (d["loo"].get("close_match_60") or 0))
        why += (f" Leave-one-out (33 basket): họ tốt nhất {bl['model']} thoát +-15p {bl['loo'].get('close_match_15')}% / +-60p {bl['loo'].get('close_match_60')}% "
                f"(ngẫu nhiên mean {loo['random_exit_baseline_all']['close_match_15']['mean']}% / {loo['random_exit_baseline_all']['close_match_60']['mean']}%), corr {bl['loo'].get('pnl_corr')} (ngẫu nhiên p95 {loo['random_exit_baseline_all']['pnl_corr']['p95']}).")
    if lab == "không tái tạo được" and b15 and b60:
        why += " [Vượt baseline ngẫu nhiên nhưng yếu: thoát15 dưới 25%.]"
    return dict(label=lab, why=why, criteria="'khớp tốt' = thoát15>=60 & vượt p95 ngẫu nhiên & corr>=0.7; 'một phần' = vượt p95 ngẫu nhiên cả thoát15 và thoát60 & thoát15>=25; còn lại 'không tái tạo được' (kể cả trường hợp vượt ngẫu nhiên nhưng dưới 25%: ghi rõ 'vượt ngẫu nhiên yếu' trong why). corr/dấu PnL không dùng làm tiêu chí vì baseline thoát ngẫu nhiên đã đạt corr/dấu cao khi chung điểm vào.")


def run(name, quick=False, workers=6):
    t_start = time.time()
    bc = BOTS[name]
    bc = dict(bc)
    bot = load.get_bot(name); summ = load.load_summary()["bots"][name]
    allb0 = load.build_baskets(bot)
    chk = load.check_bk(bot, allb0); cov = load.coverage(bot)
    allb = [B for B in allb0 if load.candle_arrays(B["sym"]) is not None and B["t0"] >= load.candle_arrays(B["sym"])["t"][0]]
    n_tr = int(len(allb) * 0.6); train, test = allb[:n_tr], allb[n_tr:]; split_t = test[0]["t0"]
    tr_idx = np.arange(n_tr); te_idx = np.arange(n_tr, len(allb))
    ev_base = run_bot.infer(train, bot)  # thống kê add/step/exit của harness (train)
    ev = infer_swing(allb, train, bot)
    print("INFER:", json.dumps({k: ev[k] for k in ev if k in ("win_n", "loss_n", "win_hold_h_q", "loss_hold_h_q", "win_giveback_pct_q", "loss_ret_pct_q", "batch_close_other_symbol_within_2min", "session_alignment_pct")}, ensure_ascii=False), flush=True)
    G["all"] = allb; G["ah"] = np.array([max(1.0, (B["t1"] - B["t0"]) / MINMS) for B in allb])
    q = ev_base.get("step_adverse_pct_q_last") or []
    bc["gi_extra"] = dict(add_step_med=q[2] if len(q) > 2 else None)
    ref = [s for s in bc["sym_ref"] if load.candle_arrays(s) is not None]
    bc["sym_ref"] = ref
    pool = mp.get_context("fork").Pool(workers)
    iters, cur, cur_sc, best_by_fam, gi, hold_train, rbase = run_level_a(name, allb, train, test, tr_idx, te_idx, bc, pool, quick)
    # --- thống kê tổng hợp mô hình tốt nhất theo TRAIN
    cand = [it for it in iters if it["model"] != "N0_null_timestop" and "words" in it]
    best = max(cand, key=lambda it: it["xobj_train"])
    spec = (dict((k, v) for k, v in best["params"].items() if k not in ("xspec", "session_minute_utc")), best["params"].get("xspec"), best["params"].get("session_minute_utc"))
    if spec[1] is not None: spec = (spec[0], tuple(spec[1]), spec[2])
    rows_tr, _, _ = _report(train, spec, hold_train); rows_te, _, _ = _report(test, spec, hold_train)
    for r in rows_tr: r["split"] = "train"
    for r in rows_te: r["split"] = "test"
    best["match_by_actual_hold_bucket_test"] = hold_buckets(rows_te)
    best["test_single_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] == 1])); best["test_multi_fill"] = _trim(match.level_a([r for r in rows_te if r["n_act"] > 1]))
    # --- LOO
    loo = None
    if bc["loo"]:
        ar = np.array([B["ret"] for B in allb])
        loo = dict(per_family=loo_eval(allb, best_by_fam, ar), random_exit_baseline_all=fs.rand_exit_baseline(allb, fs.hold_minutes(allb), reps=200, seed=3))
        print("LOO baseline:", json.dumps(loo["random_exit_baseline_all"]), flush=True)
    # --- Level A mức lệnh con (DWD bắt buộc; cả 3 bot để bổ sung)
    subpos = None
    sub = subpos_baskets(bot)
    sub = [B for B in sub if load.candle_arrays(B["sym"]) is not None and B["t0"] >= load.candle_arrays(B["sym"])["t"][0]]
    pool.close(); pool.join()
    if bc["adds"]:
        n2s = int(len(sub) * 0.6)
        lvb_sub, _, _, _, _ = level_b_entries(sub, sub[n2s]["t0"], quick)
        print(f"Level B (subpos) best {lvb_sub['best_rule_by_train']['rule']} test recall15 {lvb_sub['best_rule_by_train']['test']['recall_15']} precision15 {lvb_sub['best_rule_by_train']['test']['precision_15']} {lvb_sub['best_rule_by_train']['test']['strength']}", flush=True)
        G["all"] = sub; G["ah"] = np.array([max(1.0, (B["t1"] - B["t0"]) / MINMS) for B in sub])
        pool = mp.get_context("fork").Pool(workers)
        n2 = int(len(sub) * 0.6); tr2, te2 = sub[:n2], sub[n2:]
        sub_bc = dict(bc); sub_bc["adds"] = False
        it2, cur2, sc2, bbf2, gi2, ht2, rbase2 = run_level_a(name, sub, tr2, te2, np.arange(n2), np.arange(n2, len(sub)), sub_bc, pool, quick, tag="[subpos] ")
        cand2 = [it for it in it2 if it["model"] != "N0_null_timestop" and "words" in it]
        b2 = max(cand2, key=lambda it: it["xobj_train"])
        subpos = dict(note="Mức LỆNH CON: mỗi lệnh con (một tầng DCA) là 1 basket 1 fill; thoát độc lập. Tránh chuỗi chồng lấn dài (SNDK 116 lệnh con = 3 chuỗi).", n=len(sub), n_train=n2, n_test=len(sub) - n2,
                      random_exit_baseline=rbase2, levelB=lvb_sub, iterations=it2, best_model=dict(name=b2["model"], params=b2["params"], words=b2["words"], train=b2["train"], test=b2["test"], extra_test=b2["extra_test"]))
        G["all"] = allb; G["ah"] = np.array([max(1.0, (B["t1"] - B["t0"]) / MINMS) for B in allb])
        pool.close(); pool.join()
    # --- Level B / C
    t = time.time()
    lvb, hh, act_te, syms, t_hi = level_b_entries(allb, split_t, quick)
    print(f"Level B done {time.time() - t:.0f}s: best {lvb['best_rule_by_train']['rule']} test recall15 {lvb['best_rule_by_train']['test']['recall_15']} precision15 {lvb['best_rule_by_train']['test']['precision_15']}", flush=True)
    lvc = level_c(allb, spec, lvb["best_rule_by_train"]["rule"], split_t, t_hi, syms, hh)
    neutral = (dict(maxhold=int(np.median(hold_train))), None, None)
    lvc["with_neutral_exit_median_hold"] = level_c(allb, neutral, lvb["best_rule_by_train"]["rule"], split_t, t_hi, syms, hh)
    print("Level C:", lvc, flush=True)
    theme = theme_analysis(allb) if name == "Dark-Wood-Dahlia" else None
    null = next(it for it in iters if it["model"] == "N0_null_timestop")
    evidence = build_evidence(ev, loo, ev_base)
    v = my_verdict(best, null, rbase["test"], lvb, lvc, loo)
    res = dict(
        bot=name, rank=bot["rank"], style=summ["style"], styleKey=summ["styleKey"], idea_from_summary=dict(how=summ["how"], edge=summ["edge"], risk=summ["risk"]),
        hypothesis=bc["hyp"],
        data=dict(n_subpositions=len(bot["trades"]), n_baskets=len(allb0), n_baskets_simulated=len(allb), basket_check=chk, symbols_missing_candles=[r["sym"] for r in cov if not r["file"]], coverage=cov,
                  n_train=len(train), n_test=len(test), split_t=split_t, train_period=[train[0]["t0"], train[-1]["t0"]], test_period=[test[0]["t0"], test[-1]["t0"]],
                  note_sim="Mô phỏng điều kiện hoá theo fill đầu thật; horizon = t1 thật + 60 phút; chưa đóng -> mark-to-market; phí 3.5 bps/chiều; không funding. Nến 1m: đường giá O->bất lợi->có lợi->C."),
        inference=dict(harness=ev_base, swing=ev), grids=gi,
        iterations=iters, best_model=dict(name=best["model"], params=best["params"], rules_words=best["words"], train=best["train"], test=best["test"], extra_test=best["extra_test"],
                                          test_single_fill=best["test_single_fill"], test_multi_fill=best["test_multi_fill"], xobj_train=best["xobj_train"],
                                          match_by_actual_hold_bucket_test=best["match_by_actual_hold_bucket_test"]),
        design_iterations=DESIGN_ITERS, evidence=evidence, random_exit_baseline=rbase, levelB=lvb, levelC=lvc, verdict=v,
        diagnostics=dict(oracle_exit_first_touch_train=run_bot.oracle_exit(train), oracle_exit_first_touch_test=run_bot.oracle_exit(test), underwater_at_T=ev["underwater_at_T"],
                         batch_close=ev["batch_close_other_symbol_within_2min"], batch_open=ev["batch_open_other_symbol_within_2min"], session_alignment_pct=ev["session_alignment_pct"],
                         close_bar_alignment_pct=ev["close_bar_alignment_pct"], theme=theme,
                         note=("oracle_exit: dùng giá thoát THẬT làm mức; thoát thật trùng lần chạm ĐẦU của mức đó (<=5p) -> hợp với limit TP/SL mức giá; chậm hơn nhiều -> không phải mức giá cố định.")),
        iteration_summary=dict(null_train_xobj=null.get("xobj_train"), null_test=null["test"], best_by_train=dict(model=best["model"], xobj_train=best["xobj_train"], test_score=best["test"].get("score")),
                               test_score_sequence=[[it["model"], it["test"].get("score")] for it in iters if "test" in it],
                               stop_rule=("Họ chạy lần lượt A1..A7; forward-selection tối đa 3 vòng, dừng khi thành phần mới không tăng xobj TRAIN >= 2/n_train (2 basket). Chọn mô hình cuối theo xobj TRAIN, KHÔNG theo TEST.")),
        pnl_check=dict(note="pnl OKX ~ gross - ~7bps*notional (phí); sim trừ 3.5bps/chiều"),
        cum_curve_train=match.cum_curve(rows_tr), cum_curve_test=match.cum_curve(rows_te), representative=representative(rows_tr + rows_te),
        loo=loo, subpos=subpos, rows=rows_tr + rows_te, runtime_s=round(time.time() - t_start, 1))
    finalize_schema(res)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, load.slug(name) + ".json")
    json.dump(res, open(p, "w"), ensure_ascii=False, default=_default)
    print("VERDICT:", v, "\nwritten", p, "runtime", res["runtime_s"], flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    w = 6
    if "--workers" in sys.argv: w = int(sys.argv[sys.argv.index("--workers") + 1]); args = [a for a in args if a != str(w)]
    run(args[0], quick="--quick" in sys.argv, workers=w)
