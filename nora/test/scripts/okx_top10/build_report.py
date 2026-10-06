#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Dựng báo cáo HTML tiếng Việt "Mô phỏng lại 10 bot top OKX" (một file, dữ liệu nhúng inline).

Chạy:   ~/.venvs/nora/bin/python build_report.py            (hoặc ~/.venvs/okxr/bin/python)
Tuỳ chọn: --disc-dir DIR  (thư mục chứa disc_<slug>.json của giai đoạn 2; mặc định out/)
          --out FILE      (mặc định /home/vmc03/norabt/none/okx-replication.html)

Đầu vào chỉ đọc:
  none/okx-top10/bots.json, summary.json
  out/<slug>.json            (giai đoạn 1: luật viết tay + grid search, Level A/B)
  out/disc_<slug>.json       (giai đoạn 2: học cơ chế + Level S; tuỳ chọn, chạy lại script là tự nhận)
  nến 1m qua load.candle_arrays(sym)
Không ghi đè okx-report.html.
"""
import argparse
import datetime
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import load  # noqa: E402

NONE_DIR = "/home/vmc03/norabt/none"
DEFAULT_OUT = os.path.join(NONE_DIR, "okx-replication.html")
P1_DIR = os.path.join(HERE, "out")
MIN = 60_000
HOUR = 3_600_000
MAX_CANDLES = 2000


# ------------------------------------------------------------------ helpers
def g(o, *path, default=None):
    """Truy cập lồng nhau chịu lỗi (dict key / list index)."""
    cur = o
    for p in path:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
        if cur is None:
            return default
    return cur


def num(x, nd=None):
    """Số JSON an toàn (None nếu NaN/inf/không phải số)."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if nd is not None:
        v = round(v, nd)
    return int(v) if v == int(v) and abs(v) < 1e15 and nd is None and isinstance(x, int) else v


def vn(x, nd=1):
    """Định dạng số kiểu Việt cho văn bản sinh ở Python (chấm nghìn, phẩy thập phân)."""
    v = num(x)
    if v is None:
        return "—"
    s = f"{abs(v):,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if v < 0 and any(c in "123456789" for c in s) else "") + s


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def dec_vn(s):
    """Chuyển số thập phân dạng 1.23 trong văn bản thô sang 1,23."""
    return re.sub(r"(?<=\d)\.(?=\d)", ",", s) if isinstance(s, str) else s


def clean_text(s):
    if not isinstance(s, str):
        return s
    # bỏ ghi chú quá trình ("pilot ...") lẫn trong giả thuyết
    s = re.sub(r"\s*\((?:[^()]*pilot[^()]*)\)", "", s)
    s = re.sub(r"\s*Chạy lại với họ thoát mới[^.]*\.", "", s)
    # sự kiện chỉ báo dạng dict -> tên ngắn
    s = re.sub(r"\{[^{}]*'nm': '([^']+)'[^{}]*\}", r"\1", s)
    return s.strip()


def vclass(label):
    l = (label or "").lower().strip()
    if l.startswith("khớp tốt") or l.startswith("tiệm cận tốt"):
        return "good"
    if l.startswith("khớp một phần") or l.startswith("tiệm cận một phần"):
        return "part"
    if l.startswith("yếu") or "chưa phân biệt" in l:
        return "weak"
    return "none"


def fmt_hours(hs):
    if not hs:
        return None
    hs = sorted(set(int(h) for h in hs))
    runs, st, pv = [], hs[0], hs[0]
    for h in hs[1:]:
        if h == pv + 1:
            pv = h
            continue
        runs.append((st, pv)); st = pv = h
    runs.append((st, pv))
    return ", ".join(f"{a}h" if a == b else f"{a}-{b}h" for a, b in runs)


def rule_words(bl, tz):
    """Mô tả ngắn luật vào lệnh tốt nhất (nhận cả dạng best_rule_by_train và dạng params)."""
    if not bl:
        return None
    r = bl.get("rule") if isinstance(bl.get("rule"), dict) else bl
    name = bl.get("family") or bl.get("feat") or r.get("kind") or r.get("fam")
    parts = [str(name)] if name else []
    if r.get("thr") is not None:
        parts.append(f"ngưỡng {vn(r['thr'], 2).rstrip('0').rstrip(',')}")
    if r.get("n") is not None:
        parts.append(f"n={r['n']}")
    if r.get("prm") is not None and not name:
        parts.append("tham số " + ", ".join(str(x) for x in r["prm"]))
    h = fmt_hours(r.get("hours") or r.get("gate"))
    if h:
        parts.append(f"cổng giờ {h} {tz}")
    if r.get("cool_h") is not None:
        parts.append(f"nghỉ {r['cool_h']} giờ sau mỗi lệnh")
    if r.get("vol") is not None:
        parts.append(f"biến động ≥ phân vị {r['vol']}")
    return " · ".join(parts)


# ------------------------------------------------------------------ nến
_CANDLE_CACHE = {}


def candles_window(sym, t_lo, t_hi, tf_min=None):
    """(tf_phút, [[t_giây,o,h,l,c],...]) trong [t_lo,t_hi] ms; 1m nếu cửa sổ <= 2 ngày, ngược lại 5m, tự thô hơn để <= MAX_CANDLES."""
    if sym not in _CANDLE_CACHE:
        _CANDLE_CACHE[sym] = load.candle_arrays(sym)
    a = _CANDLE_CACHE[sym]
    if a is None:
        return None, None
    span = t_hi - t_lo
    tf = tf_min or (1 if span <= 2 * 24 * HOUR else 5)
    for cand in (tf, 5, 15, 60, 240):
        if cand < tf:
            continue
        if span / (cand * MIN) <= MAX_CANDLES:
            tf = cand
            break
    else:
        tf = 240
    i0 = int(np.searchsorted(a["t"], t_lo, side="left"))
    i1 = int(np.searchsorted(a["t"], t_hi, side="right"))
    if i1 - i0 < 2:
        return tf, None
    t = a["t"][i0:i1]
    o, h, l, c = a["o"][i0:i1], a["h"][i0:i1], a["l"][i0:i1], a["c"][i0:i1]
    key = t // (tf * MIN)
    cut = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    end = np.r_[cut[1:], len(t)]
    out = []
    for s, e in zip(cut, end):
        out.append([int(key[s] * tf * 60), float("%.7g" % o[s]), float("%.7g" % h[s:e].max()),
                    float("%.7g" % l[s:e].min()), float("%.7g" % c[e - 1])])
    return tf, out


# ------------------------------------------------------------------ sự kiện thật / mô phỏng của một basket
def real_events(bot, row):
    t0, t1 = row["t0"], row["t1"]
    cts = [c["t"] for c in (row.get("act_closes") or [])]
    cands = [t for t in bot["trades"] if t["sym"] == row["sym"] and t["side"] == row["side"]
             and t0 - 1500 <= t["o"] <= t1 + 1500]
    if cts:
        f = [t for t in cands if any(abs(t["c"] - x) <= 5000 for x in cts)]
        cands = f or cands
    cands.sort(key=lambda t: t["o"])
    ev, seen = [], set()
    for i, t in enumerate(cands):
        k = ("in", int(t["o"] // 1000), round(t["po"], 8))
        if k in seen:
            continue
        seen.add(k)
        ev.append(dict(k="in" if not ev else "add", t=int(t["o"]), px=num(t["po"])))
    seen = set()
    for t in sorted(cands, key=lambda t: t["c"]):
        k = (int(t["c"] // 1000), round(t["pc"], 8), t["pnl"] > 0)
        if k in seen:
            continue
        seen.add(k)
        ev.append(dict(k="out", t=int(t["c"]), px=num(t["pc"]), w=bool(t["pnl"] > 0)))
    if not cands:  # dự phòng: chỉ có số liệu trong row
        for a in (row.get("act_adds") or []):
            ev.append(dict(k="add", t=int(a["t"]), px=num(a["px"])))
        for c in (row.get("act_closes") or []):
            ev.append(dict(k="out", t=int(c["t"]), px=num(c["px"]), w=bool((row.get("act_pnl") or 0) > 0)))
    return ev, len(cands)


def sim_events(row):
    ev, seen = [], set()
    for a in (row.get("sim_adds") or row.get("sim_fills") or []):
        ev.append(dict(k="add", t=int(a["t"]), px=num(a["px"])))
    sw = bool((row.get("sim_ret") or 0) > 0)
    closed = bool(row.get("sim_closed", True))
    cl = row.get("sim_closes") or ([row["sim_close"]] if row.get("sim_close") else [])
    for c in cl:
        k = (int(c["t"] // 1000), round(c["px"], 8))
        if k in seen:
            continue
        seen.add(k)
        ev.append(dict(k="out", t=int(c["t"]), px=num(c["px"]), w=sw, open=not closed))
    return ev


def basket_payload(bot, row, tag, src, split_t):
    rev, nsub = real_events(bot, row)
    sev = sim_events(row)
    ts = [e["t"] for e in rev + sev]
    if not ts:
        return None
    t_lo = min(min(ts), row["t0"]) - 2 * HOUR
    t_hi = max(max(ts), row["t1"]) + 2 * HOUR
    tf, cd = candles_window(row["sym"], t_lo, t_hi)
    sc = row.get("split") or ("test" if split_t and row["t0"] >= split_t else "train")
    return dict(
        src=src, tag=tag, id=row.get("id"), sym=row["sym"], side=row["side"], lev=num(row.get("lev")),
        split=sc, t0=int(row["t0"]), t1=int(row["t1"]), n_sub=nsub,
        ret_real=num(row.get("act_ret"), 3), ret_sim=num(row.get("sim_ret"), 3),
        pnl_real=num(row.get("act_pnl"), 1), pnl_sim=num(row.get("sim_pnl"), 1),
        sim_closed=bool(row.get("sim_closed", True)), n_act=row.get("n_act"), n_sim=row.get("n_sim"),
        real=rev, sim=sev, tf=tf, t_lo=int(t_lo), t_hi=int(t_hi), candles=cd)


def thin(curve, n=450):
    """Giảm số điểm đường cộng dồn (giữ điểm đầu/cuối), thời gian tăng chặt."""
    if not curve:
        return []
    c = [[int(p[0]), num(p[1], 1), num(p[2], 1) if len(p) > 2 else None] for p in curve]
    if len(c) > n:
        idx = sorted(set(int(round(i * (len(c) - 1) / (n - 1))) for i in range(n)))
        c = [c[i] for i in idx]
    return c


# ------------------------------------------------------------------ giai đoạn 1
def find_iter(d, prefixes):
    for it in d.get("iterations") or []:
        if str(it.get("model", "")).startswith(prefixes):
            return it
    return None


def build_levelA_blocks(d):
    """Các khối bảng Level A (train / test / LOO / walk-forward, mốc ngẫu nhiên p95, mốc rỗng)."""
    m = d.get("metrics") or {}
    bm_tr, bm_te = g(m, "train", "levelA", default={}), g(m, "test", "levelA", default={})
    loo = g(m, "loo", "levelA")
    wf = g(m, "walk_forward", "levelA") or (loo or {}).get("walk_forward")
    nul = find_iter(d, ("M0_null", "N0_null", "X0_time"))
    nul_te = (nul or {}).get("test") if isinstance((nul or {}).get("test"), dict) else {}
    rb = g(d, "random_exit_baseline", "test")
    sh = g(d, "inference", "shuffle_hold_baseline")
    esh = g(d, "exit_only", "shuffled_tp_baseline_test")

    def p95_of(key):
        if rb and isinstance(rb.get(key), dict):
            return num(rb[key].get("p95")), "thoát ngẫu nhiên cùng phân bố giữ lệnh"
        if sh:
            if key == "close_match_15":
                return num(sh.get("shuffle_hold_match_15_p95")), "hoán vị thời gian giữ lệnh"
            if key == "close_match_60":
                return num(sh.get("shuffle_hold_match_60_p95")), "hoán vị thời gian giữ lệnh"
        return None, None

    def rows_for(tr, te, p95fn, with_null, loo_d=None, wf_d=None, add=True):
        rows = []

        def R(label, unit, key, loo_key=None, p95key=None, null_key=None, hint=None):
            tv, ev = num((tr or {}).get(key)), num((te or {}).get(key))
            lv = num((loo_d or {}).get(loo_key)) if loo_d and loo_key else None
            wv = num((wf_d or {}).get(loo_key)) if wf_d and loo_key else None
            if tv is None and ev is None and lv is None:
                return
            p = p95fn(p95key or key) if p95fn else None
            rows.append(dict(label=label, unit=unit, train=tv, test=ev, loo=lv, wf=wv,
                             p95=p[0] if p else None, null=num(nul_te.get(null_key or key)) if with_null else None, hint=hint))
        R("Thoát khớp trong ±5 phút", "%", "close_match_5", None, None)
        R("Thoát khớp trong ±15 phút", "%", "close_match_15", "close_match_15")
        R("Thoát khớp trong ±60 phút", "%", "close_match_60", "close_match_60")
        if add:
            R("Add khớp giờ và giá (tầng gộp theo tranche)", "%", "tr_add_match", None, "tr_add_match")
            R("Add khớp riêng về giờ", "%", "tr_add_time_match", None, "tr_add_time_match")
            if (te or {}).get("tr_layer_eq") is not None:
                R("Số tầng bằng số tầng thật", "%", "tr_layer_eq", None, "tr_layer_eq")
            else:
                R("Số tầng bằng số tầng thật", "%", "layer_eq", None, "layer_eq")
        R("Dấu PnL cùng dấu thật", "%", "pnl_sign_agree", "sign_agree")
        R("Tương quan lợi suất mỗi rổ", "r", "pnl_corr", None)
        R("Tỷ lệ thắng thật", "%", "act_win_pct")
        R("Tỷ lệ thắng mô phỏng", "%", "sim_win_pct")
        R("PnL cộng dồn thật", "usdt", "act_pnl_sum")
        R("PnL cộng dồn mô phỏng", "usdt", "sim_pnl_sum")
        return rows

    def p95_main(key):
        if rb and isinstance(rb.get(key), dict):
            return num(rb[key].get("p95")), "thoát ngẫu nhiên cùng phân bố giữ lệnh"
        if key in ("close_match_15", "close_match_60"):
            return p95_of(key)
        return None, None

    blocks = []
    kind = "thoát ngẫu nhiên cùng phân bố giữ lệnh" if rb else ("hoán vị thời gian giữ lệnh" if sh else None)
    has_loo = bool(loo)
    # khối 1: mô hình tốt nhất (đầy đủ)
    title1 = "Mô hình tốt nhất theo train"
    if g(d, "exit_only", "best"):
        title1 = "Mô hình đầy đủ: vào thật, add và thoát đều do luật mô phỏng"
    blocks.append(dict(title=title1, name=g(d, "best_model", "name"), cols=dict(loo=has_loo, wf=bool(wf), p95=bool(rb or sh), null=bool(nul_te)),
                       base_kind=kind,
                       rows=rows_for(bm_tr, bm_te, p95_main, True, loo, wf)))
    # khối 2 (DCA): chỉ mô phỏng luật thoát, giữ nguyên các fill thật
    eo = g(d, "exit_only", "best")
    if eo and esh:
        def p95_eo(key):
            if isinstance(esh.get(key), dict):
                return num(esh[key].get("p95")), "TP ngẫu nhiên rút từ phân phối train"
            return None, None
        blocks.append(dict(title="Chỉ mô phỏng luật thoát, giữ nguyên các fill thật (replay)", name=eo.get("model"),
                           cols=dict(loo=False, wf=False, p95=True, null=False), base_kind="TP ngẫu nhiên rút từ phân phối train",
                           rows=rows_for(eo.get("train"), eo.get("test"), p95_eo, False, None, None, add=False)))
    return blocks, nul_te


def build_levelB(d):
    m = d.get("metrics") or {}
    lb_te = g(m, "test", "levelB") or {}
    brt = g(d, "levelB", "best_rule_by_train") or {}
    lb_tr = g(m, "train", "levelB") or brt.get("train") or {}
    if not lb_te and brt.get("test"):
        lb_te = brt["test"]
    tz = "VN" if g(d, "levelB", "gate_hours_vn") else "UTC"
    rule = rule_words(brt, tz) if brt else rule_words(g(d, "params", "entry_first_tight_15min"), tz)
    if not lb_te:
        return None
    tols = [15, 60] + ([240] if lb_te.get("recall_240") is not None else [])
    rows = []
    for tol in tols:
        for nm, key in (("Recall", "recall"), ("Precision", "precision")):
            k = f"{key}_{tol}"
            rows.append(dict(label=f"{nm} vào lệnh ±{tol} phút" if tol < 240 else f"{nm} vào lệnh ±4 giờ", tol=tol, kind=key,
                             train=num(lb_tr.get(k)), test=num(lb_te.get(k)),
                             hits=g(lb_te, f"hits_{k}"), hour_mean=num(lb_te.get(f"rand_hour_{k}_mean")),
                             hour_p95=num(lb_te.get(f"rand_hour_{k}_p95")), rand_p95=num(lb_te.get(f"rand_{k}_p95"))))
    return dict(rule=rule, n_actual=lb_te.get("n_actual_starts"), n_sim=lb_te.get("n_sim_starts"),
                above=lb_te.get("above_baseline_15"), strength=lb_te.get("strength"), rows=rows,
                n_rules=g(d, "levelB", "n_rules") or g(d, "levelB", "first_entries", "n_rules"))


def build_extra_checks(d):
    """LOO / walk-forward cho nhóm mẫu nhỏ (Faithful, Firsthand, Physical)."""
    m = d.get("metrics") or {}
    out = []
    labels = [("levelB_first_tight", "Vào lệnh mới ±15 phút"), ("levelB_first_coarse", "Vào lệnh mới ±4 giờ"),
              ("add_tight", "Nhồi thêm ±15 phút"), ("add_coarse", "Nhồi thêm ±4 giờ")]
    for key, lab in labels:
        a, b = g(m, "loo", key), g(m, "walk_forward", key)
        if not a and not b:
            continue
        out.append(dict(label=lab, loo=dict(hits=a.get("hits"), n=a.get("n"), recall=num(a.get("recall_loo")),
                                            exp=num(a.get("expected_by_chance")), p=num(a.get("p_value"))) if a else None,
                        wf=dict(hits=b.get("hits"), n=b.get("n"), recall=num(b.get("recall_wf", b.get("recall_loo", b.get("recall")))),
                                exp=num(b.get("expected_by_chance")), p=num(b.get("p_value"))) if b else None))
    return out


def build_evidence(d):
    ev = d.get("evidence")
    if isinstance(ev, list) and ev:
        return [dec_vn(clean_text(x)) for x in ev]
    out = []
    inf, dca = d.get("inference") or {}, d.get("inference_dca") or {}

    def q(arr, i):
        try:
            return arr[i]
        except Exception:
            return None
    try:
        if inf.get("n_train_baskets") is not None:
            out.append(f"{vn(inf.get('pct_baskets_single_fill'), 1)}% rổ chỉ có đúng một fill; {vn(inf.get('n_fills'), 0)} fill trên {vn(inf.get('n_train_baskets'), 0)} rổ ở tập train. "
                       f"Các fill cách nhau không quá 15 phút được gộp thành một tranche ({vn(inf.get('n_tranches'), 0)} tranche), vì {vn(inf.get('pct_raw_adds_within_15min_of_prev_fill'), 0)}% lần add thô nằm sát fill trước.")
        if q(inf.get("step_adverse_pct_q_last") or [], 2) is not None:
            out.append(f"{vn(inf.get('adds_adverse_vs_last_pct'), 1)}% lần thêm tầng xảy ra khi giá đi ngược so với tầng trước; bước trung vị {vn(q(inf['step_adverse_pct_q_last'], 2), 2)}% "
                       f"(hệ số biến thiên vững {vn(inf.get('step_robust_cv_last'), 2)}), tức bước không cố định" +
                       (f"; tính theo ATR 1 giờ, trung vị {vn(q(inf['step_over_atr_q'], 2), 2)} ATR (Spearman với ATR {vn(inf.get('step_vs_atr_spearman'), 2)})." if inf.get("step_over_atr_q") else "."))
        if q(inf.get("close_pos_q") or [], 2) is not None:
            out.append(f"{vn(inf.get('close_positive_pct'), 1)}% sub-position đóng có lãi; lãi trung vị {vn(q(inf['close_pos_q'], 2), 2)}% từ giá trung bình, hệ số biến thiên vững {vn(inf.get('close_pos_robust_cv'), 2)}: mức chốt không cố định theo % giá. "
                       f"{vn(inf.get('pct_multifill_baskets_closed_all_at_once'), 1)}% rổ nhiều tầng đóng cả rổ cùng lúc.")
        if q(inf.get("hold_h_q") or [], 2) is not None:
            out.append(f"Thời gian giữ trung vị {vn(q(inf['hold_h_q'], 2), 1)} giờ (phân vị 10 đến 90: {vn(q(inf['hold_h_q'], 0), 2)} đến {vn(q(inf['hold_h_q'], 4), 1)} giờ).")
        if dca.get("roundness"):
            r = dca["roundness"]
            out.append(f"Giá fill có 8 chữ số thập phân ở {vn(r.get('fill_8digit'), 0)}% lệnh vào và {vn(r.get('close_8digit'), 0)}% lệnh đóng, dấu hiệu lệnh thị trường hoặc thuật toán chia lệnh; "
                       f"{vn(dca.get('pct_closes_sharing_time_with_sibling'), 0)}% lệnh đóng trùng giây với tầng anh em.")
        hp = dca.get("hour_utc_first_fill_pct")
        if hp:
            h = int(np.argmax(hp))
            out.append(f"Fill đầu dồn vào {h}h UTC ({vn(hp[h], 1)}% số rổ); mức đồng đều là {vn(100 / 24, 1)}%.")
        ot = g(d, "diagnostics", "oracle_exit_first_touch_train", "tp")
        if ot and ot.get("first_touch_within_5min_pct") is not None:
            out.append(f"Dùng chính giá thoát thật làm mức chốt: {vn(ot['first_touch_within_5min_pct'], 1)}% lệnh chốt trong 5 phút kể từ lần giá chạm mức đó lần đầu, "
                       f"{vn(ot.get('within_60min_pct'), 1)}% trong 60 phút; phần còn lại chốt trễ hơn, nên mức chốt không phải lệnh limit cố định.")
        ua = inf.get("units_all")
        if ua:
            out.append(f"{vn(ua.get('n_units'), 0)} unit (tranche), thắng {vn(ua.get('win_pct'), 1)}%; thời gian giữ trung vị {vn(q(ua.get('hold_h_all_q') or [], 2), 1)} giờ; "
                       f"{vn(ua.get('pct_units_closed_within60s_of_other_unit'), 0)}% unit đóng trong vòng 60 giây sau một unit khác (đóng theo cụm).")
            if ua.get("n_mae_beyond_isolated_liq"):
                out.append(f"{ua['n_mae_beyond_isolated_liq']} unit từng đi ngược vượt mức thanh lý nếu chạy isolated; bot dùng cross margin nên thua lỗ tối đa {vn(ua.get('max_loss_over_margin_pct'), 0)}% ký quỹ của unit.")
        rd, ad, tq = inf.get("roundness") or {}, inf.get("add_structure") or {}, inf.get("timing_quality") or {}
        if "entry_ge_5bps" in rd and "units_all" in inf:
            out.append(f"Giá vào lệnh tròn (khoảng cách tới số tròn ≤ 5 bps) ở {vn(rd.get('entry_ge_5bps'), 1)}% unit, mốc nến ngẫu nhiên {vn(rd.get('baseline_candle_close_ge_5bps'), 1)}%.")
        if ad.get("n_adds") is not None:
            out.append(f"{vn(ad.get('n_adds'), 0)} unit là nhồi thêm; {vn(ad.get('pct_against_vs_last'), 0)}% nhồi khi giá đi ngược so với fill trước, {vn(ad.get('pct_into_profit_vs_avg'), 0)}% nhồi khi đang lãi so với giá trung bình.")
        if tq.get("entry_price_rank_mean") is not None:
            out.append(f"Chất lượng giá vào trong ±12 giờ: hạng trung bình {vn(tq['entry_price_rank_mean'], 2)} (0,5 là ngẫu nhiên, 1 là giá tốt nhất); giá thoát {vn(tq.get('exit_price_rank_mean'), 2)}.")
    except Exception as e:  # không để một khoá lạ làm hỏng cả trang
        out.append(f"(Một số bằng chứng không đọc được: {type(e).__name__})")
    return out


def flatten_params(p, prefix=""):
    out = []
    for k, v in (p or {}).items():
        if isinstance(v, dict):
            if v.get("nm"):
                out.append([prefix + k, str(v["nm"])])
            else:
                out += flatten_params(v, prefix + k + ".")
        elif isinstance(v, list):
            out.append([prefix + k, ", ".join(str(x) for x in v)])
        elif v is not None:
            out.append([prefix + k, v if isinstance(v, (int, float, str)) else str(v)])
    return out


def phase1(d, bot):
    """Gói toàn bộ dữ liệu giai đoạn 1 cho một bot."""
    data = d.get("data") or {}
    m = d.get("metrics") or {}
    big = bool(g(m, "loo"))
    blocks, nul_te = build_levelA_blocks(d)
    lb = build_levelB(d)
    te = g(m, "test", "levelA", default={})
    eo = g(d, "exit_only", "best")
    esh = g(d, "exit_only", "shuffled_tp_baseline_test")
    rb = g(d, "random_exit_baseline", "test")
    sh = g(d, "inference", "shuffle_hold_baseline")
    # --- số liệu tổng quan (một dòng trong bảng 10 bot)
    ov = {}
    if eo and esh:           # DCA: thoát riêng với giữ fill thật so với TP ngẫu nhiên
        ex = eo["test"]
        ov.update(exit15=num(ex.get("close_match_15")), exit_p95=num(g(esh, "close_match_15", "p95")), exit_basis="Thoát riêng, giữ fill thật",
                  pnl_corr=num(ex.get("pnl_corr")), pnl_corr_p95=num(g(esh, "pnl_corr", "p95")), exit_model=eo.get("model"))
    else:
        ov.update(exit15=num(te.get("close_match_15")),
                  exit_p95=num(g(rb, "close_match_15", "p95")) if rb else (num(sh.get("shuffle_hold_match_15_p95")) if sh else None),
                  exit_basis="Mô hình tốt nhất theo train", pnl_corr=num(te.get("pnl_corr")),
                  pnl_corr_p95=num(g(rb, "pnl_corr", "p95")) if rb else None, exit_model=g(d, "best_model", "name"))
    ov["exit_null"] = num(nul_te.get("close_match_15"))
    ov["full15"] = num(te.get("close_match_15"))
    ov["full_null"] = num(nul_te.get("close_match_15"))
    ov["exit60"] = num((eo["test"] if (eo and esh) else te).get("close_match_60"))
    if big:
        ov["exit_alt"] = dict(label="LOO", val=num(g(m, "loo", "levelA", "close_match_15")))
    # add
    if big:
        a = g(m, "loo", "add_tight") or {}
        ov["add"] = num(a.get("recall_loo"))
        ov["add_note"] = f"LOO ±15 phút: {a.get('hits')}/{a.get('n')} nhồi khớp, ngẫu nhiên kỳ vọng {vn(a.get('expected_by_chance'), 1)}" if a else None
    else:
        v = te.get("tr_add_match")
        ov["add"] = num(v if v is not None else te.get("add_match"))
        ov["add_note"] = "mô hình đầy đủ, tập test"
    # entry
    lbt = g(m, "test", "levelB") or g(d, "levelB", "best_rule_by_train", "test") or {}
    ov.update(entry=num(lbt.get("recall_15")), entry_p95=num(lbt.get("rand_hour_recall_15_p95")), entry_prec=num(lbt.get("precision_15")),
              entry_prec_p95=num(lbt.get("rand_hour_precision_15_p95")), entry_n=lbt.get("n_actual_starts"))
    ver = d.get("verdict") or {}
    label = ver.get("label") or ""
    ov["v_label"], ov["v_cls"] = label, vclass(label)
    n_total = data.get("n_baskets") if not big else data.get("n_units")
    ov.update(n=n_total, n_test=data.get("n_test"), n_train=data.get("n_train"), unit="unit" if big else "rổ",
              n_baskets_big=data.get("n_chains_harness_baskets") if big else None)
    verdict = dict(label=dec_vn(label), cls=vclass(label), why=dec_vn(ver.get("why")), exit=dec_vn(ver.get("exit")), entry_first_tight=dec_vn(ver.get("entry_first_tight")),
                   caveat=dec_vn(ver.get("sample_caveat")), highlights=[dec_vn(x) for x in (ver.get("highlights") or [])], criteria=dec_vn(ver.get("criteria")))
    its = []
    for it in d.get("iterations") or []:
        tr_, te_ = it.get("train") if isinstance(it.get("train"), dict) else {}, it.get("test") if isinstance(it.get("test"), dict) else {}
        its.append([it.get("model"), num(tr_.get("close_match_15")), num(te_.get("close_match_15")), it.get("mode") or it.get("family")])
    bm_params = flatten_params(g(d, "best_model", "params") or d.get("params"))
    return dict(
        hypothesis=clean_text(d.get("hypothesis") or d.get("idea")),
        evidence=build_evidence(d),
        rules=dec_vn(clean_text(d.get("rules") or g(d, "best_model", "rules_words"))),
        model=g(d, "best_model", "name"),
        params=bm_params,
        exit_only=dict(model=eo.get("model"), rules=dec_vn(clean_text(eo.get("rules_words")))) if eo else None,
        blocks=blocks, levelB=lb, extra=build_extra_checks(d) if big else [],
        iterations=its, ov=ov, verdict=verdict,
        periods=dict(train=data.get("train_period"), test=data.get("test_period"), split_t=data.get("split_t")),
        sim_note=dec_vn(data.get("note_sim")), big=big,
        cum=dict(test=thin(d.get("cum_curve_test")), train=thin(d.get("cum_curve_train"), 250)),
        cum_note=(g(d, "pnl_check", "note") if str(g(d, "pnl_check", "note") or "").startswith("pnl") else None))


# ------------------------------------------------------------------ giai đoạn 2 (tuỳ chọn)
def phase2(path, bot, rows_by_id):
    d = load_json(path)
    if not d:
        return None
    sim = d.get("sim") or {}
    primary = sim.get("primary_model")
    ver = d.get("verdict") or {}
    label = ver.get("label") or ""
    panels = {}
    for k in ("exit", "add", "entry"):
        p = (d.get("panels") or {}).get(k)
        if isinstance(p, dict):
            panels[k] = dict(n_rows=p.get("n_rows"), n_pos=p.get("n_pos"), auc=num(g(p, "gbm", "auc_test"), 3), pr_auc=num(g(p, "gbm", "pr_auc"), 3),
                             imp=[x.get("feature") for x in (g(p, "gbm", "importance") or [])[:6] if isinstance(x, dict)],
                             tree=g(p, "tree3", "rules_text") or g(p, "tree3", "rule_text"), tree_auc=num(g(p, "tree3", "auc_test"), 3),
                             pair=g(p, "pair", "rule_text"), pair_auc=num(g(p, "pair", "auc_test"), 3), note=p.get("note"), skipped=p.get("skipped"))
    # Level A của giai đoạn 2
    la = {}
    if primary:
        la["exit_only"] = g(sim, "level_a_test_exit_only_replay_fills", primary)
        la["full"] = g(sim, "level_a_test_full_sim_add_plus_exit", primary)
    base = sim.get("baselines") or {}
    # Level S
    ls_all = d.get("level_s") or {}
    model = primary if primary in ls_all else (next(iter(ls_all), None))
    ls = None
    if model:
        ls = dict(model=model, windows={})
        for w, r in (ls_all[model] or {}).items():
            if not isinstance(r, dict):
                continue
            cmp_ = r.get("compare") or {}
            ls["windows"][w] = dict(
                window=r.get("window"), score=num(cmp_.get("stats_match_score"), 3), n_ok=cmp_.get("n_ok"), n_core=cmp_.get("n_core"),
                rows=cmp_.get("rows") or {}, mix=num(r.get("mix_overlap"), 3), daily=r.get("daily"), overlap=r.get("basket_overlap"),
                max_conc=r.get("max_concurrent"), n_sim=g(r, "sim", "n"), n_real=g(r, "real", "n"),
                trades=r.get("trades") or r.get("sim_trades") or r.get("trades_sample") or [])
    baskets = []
    for rep in d.get("representative") or []:
        row = dict(rows_by_id.get(rep.get("id")) or {})
        row.update({k: v for k, v in rep.items() if k not in ("tag",)})
        baskets.append((rep.get("tag") or rep.get("why") or "đại diện", row))
    its = [dict(i=it.get("i"), name=it.get("name"), change=dec_vn(it.get("change")), best=it.get("best_model_by_train"), tr=num(it.get("train_close15")),
                te=num(it.get("test_close15")), auc=num(it.get("gbm_auc_test"), 3)) for it in d.get("iterations") or []]
    # --- số liệu tổng quan theo giai đoạn 2 (ghi đè từng trường nếu có)
    ov2 = {}
    ex_t, fu_t = la.get("exit_only") or {}, la.get("full") or {}
    sh = base.get("shuffled_tp") or {}
    if ex_t.get("close_match_15") is not None:
        ov2.update(exit15=num(ex_t.get("close_match_15")), exit_p95=num(g(sh, "close_match_15", "p95")), exit60=num(ex_t.get("close_match_60")),
                   pnl_corr=num(ex_t.get("pnl_corr")), pnl_corr_p95=num(g(sh, "pnl_corr", "p95")), exit_model=primary, exit_basis="Thoát riêng, giữ fill thật (giai đoạn 2)")
    if fu_t:
        v = fu_t.get("tr_add_match") if fu_t.get("tr_add_match") is not None else fu_t.get("add_match")
        if v is not None:
            ov2.update(add=num(v), add_note="mô hình học từ dữ liệu, chạy đầy đủ, tập test")
        ov2.update(full15=num(fu_t.get("close_match_15")), full_null=num(g(base, "null", "close_match_15")))
    se = g(d, "sim_entry_levelB", primary, "test") if primary else None
    if isinstance(se, dict) and se.get("recall_15") is not None:
        ov2.update(entry=num(se.get("recall_15")), entry_p95=num(se.get("rand_hour_recall_15_p95")), entry_prec=num(se.get("precision_15")),
                   entry_prec_p95=num(se.get("rand_hour_precision_15_p95")), entry_n=se.get("n_actual_starts"))
    ov2 = {k: v for k, v in ov2.items() if v is not None}
    return dict(
        ov2=ov2, label=label, cls=vclass(label), why=dec_vn(ver.get("why")), passes=ver.get("passes"), numbers=ver.get("numbers"),
        mechanism={k: dec_vn(v) for k, v in (d.get("mechanism") or {}).items()}, panels=panels, level_a=la, primary=primary,
        base=dict(null=base.get("null"), shuffled=base.get("shuffled_tp")), ci=sim.get("exit15_ci95_primary"),
        level_s=ls, iterations=its, split=d.get("split"), n_baskets=d.get("n_baskets"),
        cum=thin(d.get("cum_curve_test")), selected=d.get("selected_exit_config"),
        selfcheck=d.get("selfcheck_no_lookahead")), baskets



# ------------------------------------------------------------------ giai đoạn 3: playbook (tuỳ chọn)
P3_KEEP_BASE = ("stats_match", "daily_corr", "day_sign_agree", "mix_overlap", "recall_same_15", "recall_same_60", "recall_same_240",
                "recall_any_15", "recall_any_60", "recall_any_240", "precision_same_15", "precision_same_60", "precision_same_240",
                "precision_any_15", "precision_any_60", "precision_any_240")
VN_OFF = 7 * HOUR


def _stat(v):
    return dict(mean=num(v.get("mean"), 4), p95=num(v.get("p95"), 4), p5=num(v.get("p5"), 4)) if isinstance(v, dict) else None


def p3_days(bot, sim_trades, n_pick=5):
    """Chọn vài (mã, ngày giờ VN) có cả lệnh thật lẫn lệnh mô phỏng để vẽ nến."""
    if not sim_trades:
        return []
    from collections import defaultdict
    def day_of(t):
        return int((t + VN_OFF) // (24 * HOUR))
    R, Sm = defaultdict(list), defaultdict(list)
    for t in bot["trades"]:
        R[(t["sym"], day_of(t["o"]))].append(t)
    for t in sim_trades:
        Sm[(t["sym"], day_of(t["o"]))].append(t)
    cands = []
    for k in set(R) & set(Sm):
        nr, ns = len(R[k]), len(Sm[k])
        if nr + ns > 160:
            continue
        cands.append((min(nr, ns), nr + ns, k))
    if not cands:
        for k in set(R) | set(Sm):
            nr, ns = len(R.get(k, [])), len(Sm.get(k, []))
            if 0 < nr + ns <= 160:
                cands.append((0, nr + ns, k))
    cands.sort(reverse=True)
    picks, used_sym = [], set()
    for sc, tot, k in cands:               # ưu tiên mã khác nhau
        if k[0] not in used_sym:
            picks.append(k); used_sym.add(k[0])
        if len(picks) >= n_pick:
            break
    for sc, tot, k in cands:
        if len(picks) >= n_pick:
            break
        if k not in picks:
            picks.append(k)
    out = []
    for sym, dy in picks:
        start = dy * 24 * HOUR - VN_OFF
        t_lo, t_hi = start - HOUR, start + 24 * HOUR + 2 * HOUR
        tf, cd = candles_window(sym, t_lo, t_hi, tf_min=5)
        def evs(T):
            ev, seen = [], set()
            for t in sorted(T, key=lambda x: x["o"]):
                k = ("in", int(t["o"] // 1000), round(t["po"], 6), t["side"])
                if k not in seen:
                    seen.add(k); ev.append(dict(k="in", t=int(t["o"]), px=num(t["po"]), s=t["side"]))
            for t in sorted(T, key=lambda x: x["c"]):
                if t_lo <= t["c"] <= t_hi:
                    k = ("out", int(t["c"] // 1000), round(t["pc"], 6), t["side"])
                    if k not in seen:
                        seen.add(k); ev.append(dict(k="out", t=int(t["c"]), px=num(t["pc"]), w=bool(t["pnl"] > 0), s=t["side"]))
            return ev
        rr, ss = R[(sym, dy)], Sm[(sym, dy)]
        d0 = datetime.datetime.utcfromtimestamp((start + VN_OFF) / 1000).strftime("%d/%m")
        out.append(dict(src="p3", tag=f"{sym} ngày {d0}", sym=sym, side="mixed", day=int(start), t_lo=int(t_lo), t_hi=int(t_hi),
                        n_real=len(rr), n_sim=len(ss), pnl_real=num(sum(t["pnl"] for t in rr), 0), pnl_sim=num(sum(t["pnl"] for t in ss), 0),
                        real=evs(rr), sim=evs(ss), tf=tf, candles=cd,
                        n_long_real=sum(t["side"] == "long" for t in rr), n_long_sim=sum(t["side"] == "long" for t in ss)))
    return out


def phase3(path, bot):
    d = load_json(path)
    if not d or not isinstance(d, dict):
        return None
    ls = d.get("level_s") or {}
    wins = {}
    for w in ("test", "full"):
        r = ls.get(w)
        if not isinstance(r, dict):
            continue
        cmp_ = r.get("compare") or {}
        wins[w] = dict(window=r.get("window_ms"), score=num(cmp_.get("stats_match_score"), 3), n_ok=cmp_.get("n_ok"), n_core=cmp_.get("n_core"),
                       rows=cmp_.get("rows") or {}, mix=num(r.get("mix_overlap"), 3), overlap=r.get("overlap") or {}, daily=r.get("daily") or {},
                       n_real=g(r, "real", "n"), n_sim=g(r, "sim", "n"), baskets_real=g(r, "real", "baskets"), baskets_sim=g(r, "sim", "baskets"))
    base = {}
    for w in ("test", "full"):
        b = (d.get("baselines") or {}).get(w)
        if isinstance(b, dict):
            base[w] = {k: _stat(b.get(k)) for k in P3_KEEP_BASE}
            base[w]["metric_ok_rate"] = b.get("metric_ok_rate") or {}
            base[w]["n_seeds"] = b.get("n_seeds")
    sim_tr = g(ls, "full", "sim_trades") or []
    prof = d.get("profile_train") or {}
    rules = d.get("rules_vi") or {}
    for k in list(rules):
        if isinstance(rules[k], str):
            rules[k] = [rules[k]]
        if isinstance(rules[k], list):
            rules[k] = [dec_vn(x) for x in rules[k]]
    par = d.get("params") or {}
    cal = d.get("calibration") or {}
    kv = []
    def add(lab, v):
        if v is not None and v != "":
            kv.append([lab, v])
    add("Biến thể được chọn", d.get("chosen_variant"))
    add("Chế độ chọn chiều (TRAIN)", g(par, "rules", "direction", "chosen_mode") or g(par, "rules", "direction", "mode"))
    add("Chờ sau khi đóng (phút)", par.get("cooldown_min"))
    add("Số basket tối đa cùng lúc", par.get("max_concurrent"))
    add("Phí mỗi chiều (bps)", par.get("fee_bps_side"))
    add("Kiểu chốt lời", g(par, "rules", "tp", "mode"))
    add("Kiểu xử lý lệnh thua", g(par, "rules", "loser", "mode"))
    add("Bước thêm tầng (%)", g(par, "rules", "add", "step_pct"))
    add("Tối đa tầng", g(par, "rules", "add", "max_layers"))
    its = []
    for it in d.get("iterations") or []:
        its.append(dict(i=it.get("i"), name=it.get("name"), change=it.get("change"), acc=it.get("accepted"), train=num(it.get("train_score"), 3),
                        s_test=num(g(it, "test", "stats_match"), 3), c_test=num(g(it, "test", "daily_corr"), 3), r60=num(g(it, "test", "recall_same_60"), 2)))
    sens = d.get("sensitivity_fee_5bps_side") or {}
    p3 = dict(variant=d.get("chosen_variant"), rules=rules, profile=prof, kv=kv, windows=wins, base=base, iterations=its,
              split=d.get("split"), info=d.get("info"), insample_note=g(d, "insample_full", "note"), runtime=d.get("runtime_s"),
              seeds={w: dict(n=g(d, "seed_summary", w, "n_seeds"), sd=num(g(d, "seed_summary", w, "stats_match", "sd"), 3)) for w in ("test", "full")},
              sens={w: num(g(sens, w, "stats_match", "mean"), 3) for w in ("test", "full")},
              verdict=d.get("verdict"), calibration=dict(target=cal.get("target_per_day"), q=cal.get("q_final")),
              n_sim_trades=len(sim_tr), days=p3_days(bot, sim_tr))
    bt, bf = base.get("test", {}), base.get("full", {})
    wt, wf = wins.get("test") or {}, wins.get("full") or {}
    ov3 = dict(s_test=wt.get("score"), s_test_p95=g(bt, "stats_match", "p95"), s_test_mean=g(bt, "stats_match", "mean"),
               s_full=wf.get("score"), s_full_p95=g(bf, "stats_match", "p95"),
               corr_test=num(g(wt, "daily", "daily_corr"), 3), corr_test_p95=g(bt, "daily_corr", "p95"),
               corr_full=num(g(wf, "daily", "daily_corr"), 3), corr_full_p95=g(bf, "daily_corr", "p95"),
               rec60_test=num(g(wt, "overlap", "recall_same_60")), rec60_test_p95=g(bt, "recall_same_60", "p95"),
               prec60_test=num(g(wt, "overlap", "precision_same_60")), prec60_test_p95=g(bt, "precision_same_60", "p95"),
               rec60_full=num(g(wf, "overlap", "recall_same_60")), rec60_full_p95=g(bf, "recall_same_60", "p95"),
               ok_test=sorted(k for k, r in (wt.get("rows") or {}).items() if isinstance(r, dict) and r.get("ok") and k in ("perDay", "win", "pf", "payoff", "longPct", "holdMed", "top5Share", "addPct", "addDownPct", "stepMed", "maxLayers", "baskets")),
               off_test=sorted(k for k, r in (wt.get("rows") or {}).items() if isinstance(r, dict) and not r.get("ok") and k in ("perDay", "win", "pf", "payoff", "longPct", "holdMed", "top5Share", "addPct", "addDownPct", "stepMed", "maxLayers", "baskets")))
    p3["ov3"] = ov3
    return p3



# ------------------------------------------------------------------ giai đoạn 4: tiệm cận TP/SL với điểm vào thật (tuỳ chọn, rất linh hoạt về schema)
def _scalar(v):
    """Số từ một giá trị có thể là số, hoặc dict {value|test|in_sample|mean: số}."""
    if isinstance(v, dict):
        for k in ("value", "in_sample", "test", "mean", "val"):
            if k in v and num(v[k]) is not None:
                return num(v[k])
        return None
    return num(v)


def _find(d, names, depth=3):
    """Tìm khoá đầu tiên trong names (BFS theo độ sâu) trong dict lồng nhau."""
    if not isinstance(d, dict):
        return None
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    if depth > 0:
        for v in d.values():
            if isinstance(v, dict):
                r = _find(v, names, depth - 1)
                if r is not None:
                    return r
    return None


def _brief(v, n=160):
    if isinstance(v, (dict, list)):
        s = json.dumps(sanitize_p4(v), ensure_ascii=False, separators=(",", ":"))
        return s if len(s) <= n else s[:n] + "…"
    return v


def sanitize_p4(o):
    if isinstance(o, dict):
        return {str(k): sanitize_p4(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize_p4(v) for v in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else round(o, 5)
    return o


def _table(items, maxrows=40):
    """list[dict] hoặc dict[name->dict|scalar] -> (cột, hàng) toàn giá trị vô hướng/chuỗi ngắn."""
    rows = []
    if isinstance(items, dict):
        for k, v in items.items():
            rows.append(dict(name=k, **(v if isinstance(v, dict) else {"value": v})))
    elif isinstance(items, list):
        for i, v in enumerate(items):
            rows.append(v if isinstance(v, dict) else {"value": v})
    rows = rows[:maxrows]
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    cols = cols[:10]
    return dict(cols=cols, rows=[[_brief(r.get(c)) if not isinstance(r.get(c), float) else round(r.get(c), 4) for c in cols] for r in rows])


P4_METRICS = [("exit_match_5", ["exit_match_5", "close_match_5"], "%", "Thoát khớp trong ±5 phút"),
              ("exit_match_15", ["exit_match_15", "close_match_15"], "%", "Thoát khớp trong ±15 phút"),
              ("exit_match_60", ["exit_match_60", "close_match_60"], "%", "Thoát khớp trong ±60 phút"),
              ("exit_px_err_bps_med", ["exit_px_err_bps_med", "close_px_err_bps_med"], "bps", "Sai số giá thoát, trung vị (bps)"),
              ("exit_px_err_bps_p90", ["exit_px_err_bps_p90", "close_px_err_bps_p90"], "bps", "Sai số giá thoát, p90 (bps)"),
              ("pnl_sign_agree", ["pnl_sign_agree", "sign_agree"], "%", "Dấu PnL cùng dấu thật"),
              ("pnl_corr", ["pnl_corr"], "r", "Tương quan lợi suất mỗi rổ"),
              ("pnl_corr_usdt", ["pnl_corr_usdt"], "r", "Tương quan PnL USDT mỗi rổ")]


def _norm_report(rs):
    rows = []
    if not isinstance(rs, dict):
        return rows
    if isinstance(rs.get("rows"), dict):
        src = rs["rows"]
    elif isinstance(rs.get("compare"), dict) and isinstance(rs["compare"].get("rows"), dict):
        src = rs["compare"]["rows"]
    elif isinstance(rs.get("real"), dict) and isinstance(rs.get("sim"), dict):
        src = {k: dict(real=rs["real"].get(k), sim=rs["sim"].get(k)) for k in rs["real"] if k in rs["sim"]}
    else:
        src = {k: v for k, v in rs.items() if isinstance(v, dict) and ("real" in v or "sim" in v)}
    for k, v in src.items():
        r, s = num(v.get("real")), num(v.get("sim"))
        if r is None and s is None:
            continue
        rel = num(v.get("rel_err"))
        if rel is None and r not in (None, 0) and s is not None:
            rel = (s - r) / abs(r)
        rows.append(dict(k=k, real=r, sim=s, rel=num(rel, 4), ok=v.get("ok")))
    return rows


# run_implied.py ghi mốc so sánh bằng khoá ngắn (m5/m15/m60 là tỷ lệ 0..1, sign 0..1, px_med bps) -> đổi về tên/đơn vị của metrics
_P4_ALIAS = {"m5": ("exit_match_5", 100), "m15": ("exit_match_15", 100), "m60": ("exit_match_60", 100),
             "px_med": ("exit_px_err_bps_med", 1), "sign": ("pnl_sign_agree", 100),
             "corr_ret": ("pnl_corr", 1), "corr_usdt": ("pnl_corr_usdt", 1)}


def _p4_base_alias(b):
    if not isinstance(b, dict):
        return b
    out = dict(b)
    for k, (name, mul) in _P4_ALIAS.items():
        if k not in b or name in b:
            continue
        v = b[k]
        if isinstance(v, dict):
            out[name] = {q: (num(x) * mul if num(x) is not None else None) for q, x in v.items()}
        elif num(v) is not None:
            out[name] = num(v) * mul
    return out


def phase4(path, bot, rows_by_id, split_t):
    d = load_json(path)
    if not isinstance(d, dict):
        return None
    m = d.get("metrics") if isinstance(d.get("metrics"), dict) else d
    base = d.get("baselines") if isinstance(d.get("baselines"), dict) else {}
    nul = base.get("null") or base.get("null_timestop") or base.get("null_time_stop") or base.get("null_time_stop_median_hold") or {}
    shf = base.get("shuffled_tp") or base.get("shuffled") or base.get("shuffled_tp_baseline") or base.get("shuffled_levels_20seeds") or {}
    nul, shf = _p4_base_alias(nul), _p4_base_alias(shf)
    rows = []
    for key, names, unit, label in P4_METRICS:
        v = _scalar(_find(m, names))
        nv = _scalar(_find(nul, names)) if isinstance(nul, dict) else None
        sh = _find(shf, names) if isinstance(shf, dict) else None
        sm = num(sh.get("mean")) if isinstance(sh, dict) else _scalar(sh)
        s95 = num(sh.get("p95")) if isinstance(sh, dict) else None
        if v is None and nv is None:
            continue
        rows.append(dict(k=key, label=label, unit=unit, sim=v, null=nv, shuf_mean=sm, shuf_p95=s95))
    # PnL thực hiện thật vs mô phỏng
    pr = _scalar(_find(m, ["real_pnl", "pnl_real", "realized_real", "act_pnl_sum", "real_pnl_sum"]))
    ps = _scalar(_find(m, ["sim_pnl", "pnl_sim", "realized_sim", "sim_pnl_sum"]))
    if pr is None and isinstance(_find(m, ["realized", "realised", "pnl_realized"]), dict):
        rr = _find(m, ["realized", "realised", "pnl_realized"])
        pr, ps = num(rr.get("real")), num(rr.get("sim"))
    cum = _find(m, ["cum_curve", "cum", "cum_curve_full"]) or d.get("cum_curve")
    if isinstance(cum, dict) and "t" in cum:
        cum = [[a, b_, c_] for a, b_, c_ in zip(cum["t"], cum.get("real", []), cum.get("sim", []))]
    cum = thin(cum, 450) if isinstance(cum, list) and cum and isinstance(cum[0], (list, tuple)) else []
    rep = _norm_report(_find(m, ["report_stats", "report", "stats", "okx_report"]) or d.get("report_stats"))
    cm = d.get("class_mix")
    class_mix = []
    if isinstance(cm, dict):
        for k, v in cm.items():
            class_mix.append([k, _scalar(v) if not isinstance(v, dict) else num(v.get("pct", v.get("n")))])
    elif isinstance(cm, list):
        for v in cm:
            if isinstance(v, dict):
                class_mix.append([v.get("name") or v.get("class") or v.get("k"), num(v.get("pct", v.get("share", v.get("n"))))])
    br = d.get("best_rule") if isinstance(d.get("best_rule"), dict) else {}
    text = br.get("text_vi") or d.get("text_vi") or (d.get("best_rule") if isinstance(d.get("best_rule"), str) else None)
    params = flatten_params(br.get("params") or {})
    formulas = d.get("formulas")
    ver = d.get("verdict")
    if isinstance(ver, str):
        ver = dict(label=ver)
    ver = ver if isinstance(ver, dict) else {}
    label = ver.get("label") or ver.get("verdict") or ""
    baskets = []
    for rep_ in d.get("representative") or d.get("representative_baskets") or []:
        if not isinstance(rep_, dict):
            continue
        row = dict(rows_by_id.get(rep_.get("id")) or {})
        row.update({k: v for k, v in rep_.items() if k not in ("tag", "why")})
        if "sim_exits" in rep_ and "sim_closes" not in rep_:
            row["sim_closes"] = rep_["sim_exits"]
        if "real_exits" in rep_ and "act_closes" not in rep_:
            row["act_closes"] = rep_["real_exits"]
        row.setdefault("sim_adds", [])
        if "t0" in row and "sym" in row and "side" in row:
            bp = basket_payload(bot, row, rep_.get("tag") or rep_.get("why") or "đại diện", "p4", split_t)
            if bp:
                baskets.append(bp)
    sim_tr = d.get("sim_trades")
    out = dict(
        text=dec_vn(text) if isinstance(text, str) else None, params=params,
        formulas=_table(formulas) if formulas else None, class_mix=class_mix, metrics=rows,
        pnl=dict(real=pr, sim=ps), cum=cum, report=rep,
        ablation=_table(d.get("ablation")) if d.get("ablation") else None,
        regimes=sanitize_p4(d.get("regimes")) if d.get("regimes") else None,
        top5=_table(d.get("top5") or d.get("alternatives")) if (d.get("top5") or d.get("alternatives")) else None,
        label=label, cls=vclass(label), why=dec_vn(ver.get("why")), in_sample=d.get("in_sample", True),
        n_sim=len(sim_tr) if isinstance(sim_tr, list) else None, baskets=baskets,
        base_note=sanitize_p4({k: v for k, v in base.items() if k in ("n_seeds", "seeds", "note")}))
    ov4 = dict(exit15=next((r["sim"] for r in rows if r["k"] == "exit_match_15"), None),
               exit15_null=next((r["null"] for r in rows if r["k"] == "exit_match_15"), None),
               exit15_p95=next((r["shuf_p95"] for r in rows if r["k"] == "exit_match_15"), None),
               corr=next((r["sim"] for r in rows if r["k"] == "pnl_corr"), None),
               corr_p95=next((r["shuf_p95"] for r in rows if r["k"] == "pnl_corr"), None),
               label=label, cls=vclass(label) if label else None)
    out["ov4"] = ov4
    return out


# ------------------------------------------------------------------ lắp dữ liệu
def build_data(disc_dir):
    bots = load.load_bots()
    summ = load.load_summary()
    out = []
    for b in sorted(bots, key=lambda x: x["rank"]):
        slug = load.slug(b["name"])
        d = load_json(os.path.join(P1_DIR, slug + ".json"))
        if not d:
            print("thiếu", slug, file=sys.stderr)
            continue
        sb = (summ.get("bots") or {}).get(b["name"], {})
        p1 = phase1(d, b)
        rows_by_id = {r["id"]: r for r in d.get("rows") or []}
        split_t = p1["periods"]["split_t"]
        baskets = []
        for rep in d.get("representative") or []:
            row = rows_by_id.get(rep.get("id"))
            if row is None:
                continue
            bp = basket_payload(b, row, rep.get("tag") or rep.get("why") or "đại diện", "p1", split_t)
            if bp:
                baskets.append(bp)
        p2 = None
        p2res = phase2(os.path.join(disc_dir, f"disc_{slug}.json"), b, rows_by_id)
        if p2res:
            p2, reps2 = p2res
            for tag, row in reps2:
                if "t0" in row and "sym" in row:
                    bp = basket_payload(b, row, tag, "p2", split_t)
                    if bp:
                        baskets.append(bp)
        ls = (p2 or {}).get("level_s")
        ov = dict(p1["ov"])
        ov["src"] = "p1"
        if p2:
            ov.update(p2.pop("ov2", {}))
            ov["src"] = "p2"
            w = (ls or {}).get("windows", {}).get("test") or next(iter((ls or {}).get("windows", {}).values()), None)
            ov["s_score"] = w.get("score") if w else None
            ov["s_window"] = "test" if (ls and "test" in ls["windows"]) else "full"
        p3 = phase3(os.path.join(disc_dir, f"playbook_{slug}.json"), b)
        p4 = phase4(os.path.join(disc_dir, f"implied_{slug}.json"), b, rows_by_id, split_t)
        out.append(dict(
            slug=slug, name=b["name"], rank=b["rank"], url=b.get("url"), styleKey=d.get("styleKey") or sb.get("styleKey"),
            style=d.get("style") or sb.get("style"),
            okx=dict(how=sb.get("how"), edge=sb.get("edge"), risk=sb.get("risk"), verdict=sb.get("verdict")),
            facts=dict(pnl90=num(b.get("pnl90"), 0), roi90=num(b.get("roi90"), 1), winOkx=num(b.get("winOkx"), 1), n=b.get("n"),
                       leadDays=b.get("leadDays"), copiers=b.get("copiers"), levMed=num(b.get("levMed"), 1), holdMed=num(b.get("holdMed"), 1),
                       longPct=num(b.get("longPct"), 1), first=b.get("first"), last=b.get("last"), nOpen=b.get("nOpen"), pnl30=num(b.get("pnl30"), 0), pnl7=num(b.get("pnl7"), 0)),
            p1=p1, p2=p2, p3=p3, p4=p4, ov=ov, ov3=(p3 or {}).get("ov3"), ov4=(p4 or {}).get("ov4"), baskets=baskets))
    meta = dict(asOf=summ.get("asOf"), generated=datetime.date.today().strftime("%d/%m/%Y"), styles=summ.get("styles"),
                n_p2=sum(1 for x in out if x["p2"]), n_p3=sum(1 for x in out if x["p3"]), n_p4=sum(1 for x in out if x["p4"]))
    return dict(bots=out, meta=meta)


# ------------------------------------------------------------------ mẫu HTML / CSS / JS
CSS = r'''/*
  BỐ CỤC (anh em với okx-report.html): thanh bên trái (tên trang, lọc lối chơi, tiến độ, mục lục), cột chính
  (tổng quan, bảng 10 bot, phương pháp, giới hạn), ngăn chi tiết bên phải mở khi bấm một bot.
  Chỉ ngăn chi tiết và dải KPI nổi; trang chính chỉ dùng đường kẻ mảnh. Màu chỉ qua token (sáng, tối).
  Phần đầu là token và quy tắc nền sao chép nguyên văn từ okx-report.html; phần "bổ sung" ở cuối là riêng của trang này.
*/
:root{
  --bg:#f2f5f8;
  --surface:#ffffff;
  --surface-2:#e9eef3;
  --line:#d6dde4;
  --line-strong:#b9c4ce;
  --text:#16202b;
  --text-2:#4c5967;
  --text-3:#667381;
  --accent:#0a6c97;
  --accent-ink:#ffffff;
  --accent-soft:#dcedf5;
  --accent-fill-top:rgba(10,108,151,.30);
  --accent-fill-bottom:rgba(10,108,151,0);
  --focus:#0a6c97;
  --profit:#0b7d47;
  --loss:#c3283a;
  --long:#2160c4;
  --short:#a66200;
  --candle-up:#5a9c88;
  --candle-down:#c2828b;
  --grid:#e6ebf0;
  --cross-label:#46525e;
  --bar:#aebcc9;
  --st-dca:#0e7490;
  --st-swing:#4f46c8;
  --st-big:#b0215f;
  --st-scalp:#587a12;
  --scrim:rgba(14,22,30,.42);
  --shadow:0 0 0 1px rgba(22,32,43,.06),-18px 0 48px rgba(22,32,43,.16);
  color-scheme:light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0e1317;
    --surface:#151c22;
    --surface-2:#1d262e;
    --line:#26323c;
    --line-strong:#3a4856;
    --text:#e6ebf0;
    --text-2:#a0adb9;
    --text-3:#8190a0;
    --accent:#4cc2e8;
    --accent-ink:#06222c;
    --accent-soft:#12303d;
    --accent-fill-top:rgba(76,194,232,.32);
    --accent-fill-bottom:rgba(76,194,232,0);
    --focus:#4cc2e8;
    --profit:#3ddc97;
    --loss:#ff7280;
    --long:#74abff;
    --short:#f0b04a;
    --candle-up:#4f8f7c;
    --candle-down:#a1636d;
    --grid:#1f2a33;
    --cross-label:#3a4753;
    --bar:#3b4a58;
    --st-dca:#4fd1e5;
    --st-swing:#a3adff;
    --st-big:#f48fb1;
    --st-scalp:#b6d86a;
    --scrim:rgba(0,0,0,.58);
    --shadow:0 0 0 1px rgba(255,255,255,.06),-18px 0 48px rgba(0,0,0,.5);
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0e1317;
  --surface:#151c22;
  --surface-2:#1d262e;
  --line:#26323c;
  --line-strong:#3a4856;
  --text:#e6ebf0;
  --text-2:#a0adb9;
  --text-3:#8190a0;
  --accent:#4cc2e8;
  --accent-ink:#06222c;
  --accent-soft:#12303d;
  --accent-fill-top:rgba(76,194,232,.32);
  --accent-fill-bottom:rgba(76,194,232,0);
  --focus:#4cc2e8;
  --profit:#3ddc97;
  --loss:#ff7280;
  --long:#74abff;
  --short:#f0b04a;
  --candle-up:#4f8f7c;
  --candle-down:#a1636d;
  --grid:#1f2a33;
  --cross-label:#3a4753;
  --bar:#3b4a58;
  --st-dca:#4fd1e5;
  --st-swing:#a3adff;
  --st-big:#f48fb1;
  --st-scalp:#b6d86a;
  --scrim:rgba(0,0,0,.58);
  --shadow:0 0 0 1px rgba(255,255,255,.06),-18px 0 48px rgba(0,0,0,.5);
  color-scheme:dark;
}


*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none !important}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{
  margin:0;background:var(--bg);color:var(--text);
  font-family:"Be Vietnam Pro","Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:14px;line-height:1.55;
  font-variant-numeric:tabular-nums;
}
body.locked{overflow:hidden}
h1,h2,h3,h4{text-wrap:balance;margin:0;font-weight:600;line-height:1.3}
p{margin:0}
a{color:var(--accent);text-underline-offset:2px}
button{font:inherit;color:inherit}
.mono,td.num,.kv dd,.kpi dd,.tlines .mono{font-family:"JetBrains Mono","Noto Sans SC",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.93em;font-variant-numeric:tabular-nums}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:3px}
tr:focus-visible{outline-offset:-2px;border-radius:0}
.pos{color:var(--profit)}
.neg{color:var(--loss)}
.muted{color:var(--text-3)}
.sub{color:var(--text-2);font-size:13px}

/* ---------- app shell ---------- */
.app{display:block}
.side{padding:16px 16px 14px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:14px 28px;align-items:flex-start}
.side>*{min-width:0}
.brand h1{font-size:16px;letter-spacing:-.005em}
.brand .asof{margin-top:2px;font-size:12px;color:var(--text-3)}
.sblock h2{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-bottom:6px}
.mkt .lab{font-size:13px;font-weight:600;display:block;margin-bottom:4px}
.mkt table{border-collapse:collapse;width:100%;font-size:12.5px}
.mkt th{font-weight:500;color:var(--text-3);text-align:right;padding:2px 0 2px 10px;font-size:11.5px}
.mkt td{padding:3px 0 3px 10px;text-align:right}
.mkt th:first-child,.mkt td:first-child{text-align:left;padding-left:0;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.fchip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line-strong);background:transparent;border-radius:999px;padding:3px 10px 3px 8px;font-size:12.5px;cursor:pointer;color:var(--text-2);text-align:left}
.fchip:hover{background:var(--surface-2)}
.fchip .dot{width:8px;height:8px;border-radius:50%;background:var(--st-c,var(--text-3));flex:none}
.fchip .n{margin-left:auto;color:var(--text-3);font-size:11.5px;font-family:"JetBrains Mono",ui-monospace,monospace}
.fchip[aria-pressed="true"]{background:color-mix(in srgb,var(--st-c,var(--accent)) 14%,transparent);border-color:var(--st-c,var(--accent));color:var(--text);font-weight:600}
.fchip.all[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent)}
.snav{display:flex;flex-wrap:wrap;gap:4px}
.snav a{display:flex;flex-direction:column;gap:1px;text-decoration:none;color:var(--text-2);padding:6px 10px;border-radius:8px;border:1px solid transparent}
.snav a b{font-size:14px;font-weight:600;color:var(--text)}
.snav a span{display:none;font-size:12px;color:var(--text-3)}
.snav a:hover{background:var(--surface-2)}
.snav a[aria-current="true"]{background:var(--accent-soft);border-color:color-mix(in srgb,var(--accent) 35%,transparent)}
.snav a[aria-current="true"] b{color:var(--accent)}
.st-dca{--st-c:var(--st-dca)}
.st-swing{--st-c:var(--st-swing)}
.st-big{--st-c:var(--st-big)}
.st-scalp{--st-c:var(--st-scalp)}
.chip{display:inline-block;padding:0 8px;border-radius:999px;font-size:12px;font-weight:500;white-space:nowrap;line-height:1.7;color:var(--st-c);background:color-mix(in srgb,var(--st-c) 12%,transparent);border:1px solid color-mix(in srgb,var(--st-c) 36%,transparent)}

@media (min-width:1024px){
  .app{display:grid;grid-template-columns:260px minmax(0,1fr);align-items:start}
  .side{position:sticky;top:0;height:100vh;overflow-y:auto;flex-direction:column;flex-wrap:nowrap;gap:22px;padding:24px 20px;border-bottom:0;border-right:1px solid var(--line)}
  .side>*{width:100%}
  .snav{flex-direction:column;gap:4px;margin:-4px -10px 0}
  .snav a{padding:8px 10px}
  .snav a span{display:block}
  .sblock.mkt{margin-top:auto;padding-top:14px;border-top:1px solid var(--line)}
  .chips{flex-direction:column;align-items:stretch}
  .fchip{border-radius:8px;padding:5px 10px 5px 9px}
}
@media (max-width:1023px){
  .side{gap:12px 20px;padding:14px 16px 12px}
  .side .mkt{min-width:170px;flex:0 0 auto}
  .side .brand{flex:1 1 100%}
  .side .snav{flex:1 1 100%}
}

/* ---------- main ---------- */
.main{padding:28px 16px 64px;max-width:1180px;min-width:0}
@media (min-width:720px){.main{padding-inline:28px}}
@media (min-width:1024px){.main{padding:36px 36px 80px}}
.msec{margin-top:52px;scroll-margin-top:16px}
.msec:first-child{margin-top:0}
.msec>h2{font-size:15px;margin-bottom:14px}
.headline{font-size:19px;line-height:1.45;font-weight:600;letter-spacing:-.005em;max-width:62ch;text-wrap:pretty}
@media (max-width:600px){.headline{font-size:17px}}
.points{margin:18px 0 0;padding:0;list-style:none;display:grid;gap:8px;max-width:72ch}
.points li{padding-left:14px;position:relative;color:var(--text-2);text-wrap:pretty}
.points li::before{content:"";position:absolute;left:0;top:.62em;width:5px;height:5px;border-radius:50%;background:var(--accent)}
.tag-lead{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-bottom:8px}

/* bot list */
.hint{color:var(--text-3);font-size:12.5px;margin:-8px 0 12px}
.fdesc{margin:0 0 10px;font-size:12.5px;color:var(--text-2)}
.tablewrap{overflow-x:auto;max-width:100%}
table.grid{border-collapse:collapse;width:100%}
table.grid th,table.grid td{padding:7px 9px;white-space:nowrap;text-align:left;border-bottom:1px solid var(--line)}
table.grid th{color:var(--text-3);font-weight:500;font-size:12px;border-bottom-color:var(--line-strong)}
table.grid th.r,table.grid td.r{text-align:right}
table.grid tbody tr:last-child td{border-bottom:0}
table.ranks{min-width:840px}
table.ranks tbody tr{cursor:pointer}
table.ranks tbody tr td{padding-block:9px}
table.ranks tbody tr:hover{background:var(--surface-2)}
table.ranks tbody tr.sel{background:var(--accent-soft)}
table.ranks td.go{width:22px;padding-left:0;color:var(--text-3);font-size:17px;line-height:1;text-align:right}
table.ranks tbody tr:hover td.go,table.ranks tr.sel td.go{color:var(--accent)}
.rank{color:var(--text-3)}
.nm{font-weight:600}
td.sp{padding-block:4px}
svg.sp{display:block;width:100px;height:28px;overflow:visible}
svg.sp .ar{fill:currentColor;opacity:.14;stroke:none}
svg.sp .ln{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
svg.sp .z{stroke:var(--line-strong);stroke-width:1;stroke-dasharray:2 3}
svg.sp circle{fill:currentColor}
.tnote{margin-top:10px;font-size:12px;color:var(--text-3);max-width:90ch}

/* data block */
.dv{display:grid;gap:26px;margin-bottom:6px}
.dv h3{font-size:12.5px;font-weight:600;margin:0 0 8px;color:var(--text)}
.dv .cap{margin-top:8px;font-size:12.5px;color:var(--text-3);text-wrap:pretty;max-width:60ch}
/* flow strip: a real sequence, hairline connectors */
.flow{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));counter-reset:st}
.flow li{position:relative;padding:0 18px 0 0;min-width:0}
.flow .n{display:grid;place-items:center;width:20px;height:20px;border:1px solid var(--line-strong);border-radius:50%;font-size:11px;color:var(--text-2);background:var(--bg);position:relative;z-index:1}
.flow .t{display:block;margin-top:8px;font-weight:600;font-size:13px;line-height:1.35;color:var(--text);text-wrap:balance}
.flow .s{display:block;margin-top:2px;font-size:12px;line-height:1.4;color:var(--text-3);text-wrap:pretty}
.flow li:not(:last-child)::after{content:"";position:absolute;left:26px;right:6px;top:10px;border-top:1px solid var(--line-strong)}
.flow li:not(:last-child)::before{content:"";position:absolute;right:6px;top:7px;width:6px;height:6px;border-top:1px solid var(--line-strong);border-right:1px solid var(--line-strong);transform:rotate(45deg)}
@media (max-width:640px){
  .flow{grid-template-columns:minmax(0,1fr);gap:14px}
  .flow li{padding:0 0 0 32px;min-height:20px}
  .flow .n{position:absolute;left:0;top:0}
  .flow .t{margin-top:0}
  .flow li:not(:last-child)::after{left:10px;right:auto;top:24px;bottom:-12px;border-top:0;border-left:1px solid var(--line-strong)}
  .flow li:not(:last-child)::before{right:auto;left:7px;top:auto;bottom:-12px;transform:rotate(135deg)}
}
/* have / missing */
.hm2{display:grid;grid-template-columns:minmax(0,1fr);gap:18px 40px}
@media (min-width:640px){.hm2{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.hm2 ul{list-style:none;margin:0;padding:0;display:grid;gap:5px}
.hm2 li{display:grid;grid-template-columns:16px minmax(0,1fr);gap:4px;color:var(--text-2);font-size:13px}
.hm2 li b{font-weight:700;font-size:13px}
.hm2 .have h3{color:var(--profit)}
.hm2 .miss h3{color:var(--loss)}
.hm2 .have li b{color:var(--profit)}
.hm2 .miss li b{color:var(--loss)}
/* charts */
.charts{display:grid;grid-template-columns:minmax(0,1fr);gap:26px 36px}
@media (min-width:760px){.charts{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.charts>div{min-width:0}
.cscroll{overflow-x:auto;overscroll-behavior-x:contain}
.bc{--ref:31%;--lw:14ch;min-width:300px;font-size:12px}
.bc-r{display:grid;grid-template-columns:var(--lw) minmax(0,1fr) 5.2ch;gap:8px;align-items:center;height:21px}
.bc-r .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-2)}
.bc-r .v{text-align:right;color:var(--text);font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11.5px;font-variant-numeric:tabular-nums}
.bc-t{position:relative;height:100%}
.bc-t i{position:absolute;left:0;top:5px;bottom:5px;background:var(--accent);border-radius:0 2px 2px 0;min-width:1px}
.bc-t::after{content:"";position:absolute;left:var(--ref);top:0;bottom:0;border-left:1px dashed var(--text-2)}
.bc-h{height:18px}
.bc-h .bc-t::after{display:none}
.bc-h .bc-t span{position:absolute;left:var(--ref);bottom:2px;transform:translateX(-50%);white-space:nowrap;color:var(--text-2);font-size:11.5px}
.bc-ax .bc-t::after{display:none}
.bc-ax{height:16px;color:var(--text-3);font-size:11px}
.bc-ax .bc-t span{position:absolute;top:2px;font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.hm{--lw:14ch;--cw:1fr;min-width:340px;font-size:12px}
.hm-b{position:relative}
.hm-r{display:grid;grid-template-columns:var(--lw) minmax(0,1fr);gap:6px;align-items:center;height:19px}
.hm-r .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-2)}
.hm-c{display:grid;grid-template-columns:repeat(24,minmax(0,1fr));gap:1px;height:15px}
.hm-c i{display:block;background:color-mix(in srgb,var(--text-3) 9%,transparent);border-radius:1px}
.hm-c i.z{background:color-mix(in srgb,var(--text-3) 9%,transparent)}
.hm-band{position:absolute;top:-2px;bottom:-2px;left:calc(var(--lwpx,0px) + (100% - var(--lwpx,0px)) * 19 / 24);width:calc((100% - var(--lwpx,0px)) * 4 / 24);border:1px solid color-mix(in srgb,var(--accent) 55%,transparent);border-radius:3px;background:color-mix(in srgb,var(--accent) 6%,transparent);pointer-events:none}
.hm-ax .hm-c{height:14px;margin-top:3px}
.hm-ax .hm-c span{display:block;text-align:center;overflow:visible;white-space:nowrap;font-size:10.5px;color:var(--text-3);font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;line-height:14px}
.hm-ax .hm-r{height:auto}
/* glossary */
.gl{margin:0;display:grid;grid-template-columns:minmax(0,1fr);gap:8px 40px}
@media (min-width:760px){.gl{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.gl div{display:grid;gap:0}
.gl dt{font-weight:600;font-size:12.5px;color:var(--text)}
.gl dd{margin:0;font-size:12.5px;color:var(--text-2);text-wrap:pretty}
details.more-d{margin-top:16px}
details.more-d>summary{cursor:pointer;color:var(--accent);font-size:13px;width:fit-content;padding:3px 0}
details.more-d[open]>summary{margin-bottom:12px}
.scope{display:grid;gap:18px;max-width:92ch}
.scope .cols{display:grid;grid-template-columns:minmax(0,1fr);gap:16px 32px}
@media (min-width:760px){.scope .cols{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.scope h4,.scope h5{font-size:12.5px;margin:0 0 3px;font-weight:600}
.scope ul{margin:4px 0 0;padding-left:18px;display:grid;gap:5px;font-size:13px;color:var(--text-2)}
.scope .have h4{color:var(--profit)}
.scope .miss h4{color:var(--loss)}
.scope p{font-size:13px;color:var(--text-2);text-wrap:pretty}
.scope .finds{display:grid;gap:12px}
.method{margin-top:6px}
.method ul{margin:6px 0 0;padding-left:18px;display:grid;gap:5px;font-size:13px;color:var(--text-2)}
.srcnote{margin-top:20px;font-size:12px;color:var(--text-3)}

/* ---------- drawer ---------- */
.scrim{position:fixed;inset:0;background:var(--scrim);z-index:50;opacity:0;visibility:hidden;transition:opacity .25s ease,visibility 0s linear .25s}
.scrim.open{opacity:1;visibility:visible;transition:opacity .25s ease,visibility 0s}
.drawer{position:fixed;top:50%;left:50%;width:min(1320px,calc(100vw - 48px));height:calc(100vh - 48px);z-index:60;background:var(--surface);box-shadow:var(--shadow);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;opacity:0;transform:translate(-50%,-48%) scale(.98);visibility:hidden;transition:opacity .2s ease,transform .22s cubic-bezier(.2,.7,.2,1),visibility 0s linear .22s}
.drawer.open{opacity:1;transform:translate(-50%,-50%);visibility:visible;transition:opacity .2s ease,transform .22s cubic-bezier(.2,.7,.2,1),visibility 0s}
@media (max-width:700px){.drawer{width:100vw;height:100vh;height:100dvh;border-radius:0;border:0}}
.drawer:focus{outline:0}
.dhead{flex:none;padding:14px 16px 12px 20px;border-bottom:1px solid var(--line)}
.dtop{display:flex;align-items:center;gap:10px}
.dtitle{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;min-width:0;flex:1}
.dtitle .rk{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px;color:var(--text-3)}
.dtitle h2{font-size:18px;overflow-wrap:anywhere}
.dnav{display:flex;align-items:center;gap:4px;flex:none}
.dnav .pos-i{font-size:12px;color:var(--text-3);font-family:"JetBrains Mono",ui-monospace,monospace;padding:0 4px}
.ib{width:34px;height:34px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--text-2);cursor:pointer;display:grid;place-items:center;font-size:20px;line-height:1;padding:0}
.ib:hover{background:var(--surface-2);color:var(--text)}
.ib svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.dmeta{margin-top:4px;display:flex;flex-wrap:wrap;gap:2px 16px;font-size:12.5px;color:var(--text-2)}
.dscroll{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:18px 28px 40px}
.verdict{font-size:15px;font-weight:500;line-height:1.5;text-wrap:pretty;max-width:68ch}
.kpi{margin:16px 0 0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.kpi>div{background:var(--bg);padding:9px 12px}
.kpi dt{font-size:11.5px;color:var(--text-3);white-space:nowrap}
.kpi dd{margin:1px 0 0;font-size:15.5px;font-weight:600;white-space:nowrap}
@media (max-width:600px){
  .kpi{grid-template-columns:repeat(6,minmax(0,1fr))}
  .kpi>div:nth-child(-n+3){grid-column:span 2}
  .kpi>div:nth-child(n+4){grid-column:span 3}
}
.cblock{margin-top:20px;scroll-margin-top:8px}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-bottom:8px}
.toolbar label{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-2)}
select,.btn{font:inherit;font-size:13px;color:var(--text);background:var(--surface);border:1px solid var(--line-strong);border-radius:6px;padding:4px 10px;min-height:32px}
select{max-width:100%}
.btn{cursor:pointer}
.btn:hover{background:var(--surface-2)}
.seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:6px;overflow:hidden}
.seg button{font-size:12.5px;border:0;background:var(--surface);color:var(--text-2);padding:4px 11px;min-height:30px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line-strong)}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink);font-weight:600}
.seg button:focus-visible{outline-offset:-3px}
.tfnote{font-size:12.5px;color:var(--loss)}
.chartbox{position:relative;border:1px solid var(--line);border-radius:8px;background:var(--surface);overflow:hidden;min-width:0}
.chart{width:100%;min-width:0}
.chart.eq{height:180px}
.chart.px{height:clamp(340px,52vh,560px)}
@media (max-width:600px){.chart.px{height:280px}}
.clegend{position:absolute;left:8px;top:5px;z-index:5;font-size:11.5px;color:var(--text-2);pointer-events:none;max-width:calc(100% - 16px);background:var(--surface);padding:1px 6px;border-radius:4px;overflow-wrap:anywhere}
.cempty{position:absolute;inset:0;z-index:6;display:grid;place-items:center;background:var(--surface);color:var(--text-2);padding:16px;text-align:center}
.legend{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:3px 16px;font-size:12px;color:var(--text-2)}
.legend li{display:flex;align-items:center;gap:5px}
.legend svg{width:12px;height:12px;flex:none}
.i-long{fill:var(--long)}
.i-short{fill:var(--short)}
.i-win{fill:var(--profit)}
.i-loss{fill:var(--loss)}
.chartnote{margin-top:6px;font-size:11.5px;color:var(--text-3);max-width:100ch;text-wrap:pretty}

/* tabs */
.tabs{margin-top:24px;display:flex;gap:2px;border-bottom:1px solid var(--line);overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{border:0;background:none;padding:9px 14px;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--text-2);cursor:pointer;font-size:13.5px;white-space:nowrap}
.tabs button:hover{color:var(--text)}
.tabs button[aria-selected="true"]{color:var(--text);font-weight:600;border-bottom-color:var(--accent)}
.tabs button:focus-visible{outline-offset:-3px}
.tpanel{padding-top:18px}
.prose{display:grid;gap:14px}
.prose>div{padding-left:12px;border-left:2px solid var(--line-strong)}
.prose .how{border-left-color:var(--accent)}
.prose .edge{border-left-color:var(--profit)}
.prose .risk{border-left-color:var(--loss)}
.prose h4{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--text-3);margin-bottom:2px}
.prose p{text-wrap:pretty;max-width:74ch}
.psec{margin-top:26px}
.psec>h3{font-size:12.5px;color:var(--text-2);margin-bottom:8px}
.kv{margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,180px),1fr));gap:0 22px}
.kv>div{padding:6px 0;border-bottom:1px solid var(--line)}
.kv dt{font-size:11.5px;color:var(--text-3)}
.kv dd{margin:0;font-weight:500;overflow-wrap:anywhere}
.rhythm{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}
.hours{display:grid;grid-template-columns:repeat(24,minmax(0,1fr));grid-template-rows:100%;gap:2px;align-items:end;height:84px;border-bottom:1px solid var(--line-strong)}
.hours i{display:block;background:var(--bar);border-radius:2px 2px 0 0;min-height:1px}
.hours i.pk{background:var(--accent)}
.hlabels{display:grid;grid-template-columns:repeat(24,minmax(0,1fr));gap:2px;font-size:11px;color:var(--text-3);margin-top:3px;text-align:center}
.hcap{margin-top:6px;font-size:12px;color:var(--text-3)}
.hcap .sw{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:-1px;margin-right:4px}
.sw.pk{background:var(--accent)}
.sw.of{background:var(--bar)}
.tlines{margin:0;padding:0;list-style:none;display:grid;gap:0;font-size:13px}
.tlines li{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding:7px 0}
.tlines li span:first-child{color:var(--text-2)}
.tlines li span:last-child{text-align:right}
.side-l{font-weight:500}
.side-l.long{color:var(--long)}
.side-l.short{color:var(--short)}
.tag{font-size:11px;padding:0 6px;border:1px solid var(--line-strong);border-radius:4px;color:var(--text-2)}
table.trades{min-width:1080px}
table.trades tbody tr[data-i]{cursor:pointer}
table.trades tbody tr[data-i]:hover{background:var(--surface-2)}
table.trades tbody tr.sel{background:var(--accent-soft)}
table.trades th,table.trades td,.optbl th,.optbl td{padding:6px 10px}
.optbl{min-width:700px}
.scroll-y{max-height:460px;overflow:auto}
.more{margin-top:10px;display:flex;flex-wrap:wrap;align-items:center;gap:10px}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none !important;transition-duration:0s !important;transition-delay:0s !important;scroll-behavior:auto !important}}
img{max-width:100%}

/* ================= bổ sung cho báo cáo mô phỏng ================= */
:root{--v-good:var(--profit);--v-part:var(--accent);--v-weak:var(--short);--v-none:var(--loss)}
.v-good{--st-c:var(--v-good)}
.v-part{--st-c:var(--v-part)}
.v-weak{--st-c:var(--v-weak)}
.v-none{--st-c:var(--v-none)}
.lead{font-size:13.5px;color:var(--text-2);max-width:78ch;text-wrap:pretty}
.sblock .prog{margin:0;display:grid;gap:3px;font-size:12.5px;color:var(--text-2)}
.sblock .prog div{display:flex;justify-content:space-between;gap:12px}
.sblock .prog b{font-family:"JetBrains Mono",ui-monospace,monospace;font-weight:500;color:var(--text)}
table.ranks{min-width:1080px}
table.ranks th small{display:block;font-weight:400;color:var(--text-3);font-size:11px;white-space:nowrap}
.sm{font-size:11.5px;color:var(--text-3);font-weight:400}
.tagok{display:inline-block;margin-left:5px;padding:0 5px;border:1px solid color-mix(in srgb,var(--profit) 45%,transparent);border-radius:4px;font-size:10.5px;color:var(--profit);line-height:1.5;vertical-align:1px}
.srcmark{display:inline-block;margin-left:4px;font-size:10.5px;color:var(--text-3)}
.none-cell{color:var(--text-3)}

/* phương pháp */
.flow2{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr))}
.flow2 li{position:relative;padding:0 18px 0 0;min-width:0}
.flow2 .nd{display:block;width:9px;height:9px;border-radius:50%;border:1.5px solid var(--accent);background:var(--bg);position:relative;z-index:1;margin-top:5px}
.flow2 li:not(:last-child)::after{content:"";position:absolute;left:14px;right:6px;top:10px;border-top:1px solid var(--line-strong)}
.flow2 .t{display:block;margin-top:9px;font-weight:600;font-size:13px;line-height:1.35;color:var(--text);text-wrap:balance}
.flow2 .s{display:block;margin-top:2px;font-size:12px;line-height:1.4;color:var(--text-3);text-wrap:pretty}
@media (max-width:640px){
  .flow2{grid-template-columns:minmax(0,1fr);gap:14px}
  .flow2 li{padding:0 0 0 22px}
  .flow2 .nd{position:absolute;left:0;top:5px;margin:0}
  .flow2 .t{margin-top:0}
  .flow2 li:not(:last-child)::after{left:4px;right:auto;top:18px;bottom:-14px;border-top:0;border-left:1px solid var(--line-strong)}
}
.mgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:18px 40px;margin-top:26px;max-width:1000px}
@media (min-width:760px){.mgrid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.mgrid h3,.limits h3{font-size:12.5px;margin:0 0 6px}
.mgrid p,.mgrid li,.limits li,.limits p{font-size:13px;color:var(--text-2);text-wrap:pretty}
.mgrid ul,.limits ul{margin:4px 0 0;padding-left:18px;display:grid;gap:5px}
.limits{margin-top:6px;max-width:92ch}
.limits ul{margin-top:8px}
code,.code{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.92em;background:var(--surface-2);padding:0 4px;border-radius:3px}

/* drawer bên phải */
.drawer{top:0;left:auto;right:0;bottom:0;width:min(1120px,calc(100vw - 32px));height:100vh;height:100dvh;border-radius:0;border:0;border-left:1px solid var(--line);transform:translateX(100%);opacity:1;transition:transform .24s cubic-bezier(.2,.7,.2,1),visibility 0s linear .24s}
.drawer.open{transform:none;transition:transform .24s cubic-bezier(.2,.7,.2,1),visibility 0s}
@media (max-width:700px){.drawer{width:100vw;border-left:0}}
.dscroll{padding:18px 28px 56px}
@media (max-width:600px){.dscroll{padding:16px 16px 48px}.dhead{padding:12px 12px 10px 16px}}
.dsec{margin-top:34px;scroll-margin-top:8px}
.dsec:first-child{margin-top:0}
.dsec>h3{font-size:14px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.dsec h4{font-size:12.5px;font-weight:600;margin:20px 0 6px;color:var(--text)}
.dsec p{text-wrap:pretty;max-width:80ch;color:var(--text)}
.dsec p+p{margin-top:8px}
.dsec .sub{max-width:80ch}
.bl{margin:0;padding-left:18px;display:grid;gap:7px;max-width:84ch;color:var(--text-2)}
.bl li{text-wrap:pretty}
.verdict-line{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.mono{font-family:"JetBrains Mono",ui-monospace,monospace}
table.mt{border-collapse:collapse;width:100%;min-width:560px}
table.mt th,table.mt td{padding:6px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
table.mt th:first-child,table.mt td:first-child{text-align:left;white-space:normal;min-width:15ch}
table.mt th{color:var(--text-3);font-weight:500;font-size:12px;border-bottom-color:var(--line-strong)}
table.mt tbody tr:last-child td{border-bottom:0}
table.mt td.num{font-size:12.5px}
table.mt tr.hl td{background:var(--accent-soft)}
.tcap{margin:6px 0 0;font-size:12px;color:var(--text-3);max-width:90ch}
.pill{display:inline-block;padding:0 7px;border-radius:999px;font-size:11.5px;line-height:1.65;border:1px solid var(--line-strong);color:var(--text-2);white-space:nowrap}
.pill.yes{color:var(--profit);border-color:color-mix(in srgb,var(--profit) 45%,transparent)}
.pill.no{color:var(--loss);border-color:color-mix(in srgb,var(--loss) 45%,transparent)}
details.dd{margin-top:14px}
details.dd>summary{cursor:pointer;color:var(--accent);font-size:13px;width:fit-content;padding:3px 0}
details.dd[open]>summary{margin-bottom:10px}
.splitnote{margin-top:6px;font-size:12px;color:var(--text-3);max-width:90ch}
.tabsx{display:inline-flex;border:1px solid var(--line-strong);border-radius:6px;overflow:hidden;margin-bottom:10px}
.tabsx button{font-size:12.5px;border:0;background:var(--surface);color:var(--text-2);padding:4px 12px;min-height:30px;cursor:pointer}
.tabsx button+button{border-left:1px solid var(--line-strong)}
.tabsx button[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink);font-weight:600}
.chartbox .ovl{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:4}
.chart.px{height:clamp(340px,50vh,520px)}
.chart.eq{height:220px}
.legend svg{width:14px;height:14px}
.lg-real{fill:currentColor}
.lg-sim{fill:none;stroke:currentColor;stroke-width:1.6}
.cmpnote{margin-top:8px;font-size:13px;color:var(--text-2);max-width:84ch}
.sw2{display:inline-block;width:18px;height:0;border-top:2px solid;vertical-align:middle;margin-right:5px}
.sw2.dash{border-top-style:dashed}
.kvg{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,200px),1fr));gap:0 22px;margin:0}
.kvg>div{padding:6px 0;border-bottom:1px solid var(--line)}
.kvg dt{font-size:11.5px;color:var(--text-3)}
.kvg dd{margin:0;font-weight:500;overflow-wrap:anywhere;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px}
.empty2{padding:12px 14px;border:1px dashed var(--line-strong);border-radius:8px;color:var(--text-3);font-size:13px;max-width:80ch}
pre.rt{margin:6px 0 0;padding:8px 10px;background:var(--surface-2);border-radius:6px;overflow:auto;font-size:12px;line-height:1.45;max-height:220px;font-family:"JetBrains Mono",ui-monospace,monospace}
.kpi dd small{font-size:11px;font-weight:400;color:var(--text-3)}
.kpi{grid-template-columns:repeat(5,minmax(0,1fr))}
@media (max-width:600px){.kpi{grid-template-columns:repeat(6,minmax(0,1fr))}}

.main{max-width:1400px}
table.ranks th,table.ranks td{padding-inline:8px}
table.ranks{min-width:1040px}
.toolbar label{min-width:0;max-width:100%}
.toolbar select{min-width:0;text-overflow:ellipsis}
@media (max-width:600px){.toolbar label{flex:1 1 100%;flex-wrap:wrap}#bk-select{width:100%}}

table.ranks{min-width:1700px}
table.ranks th.gh{text-align:left;color:var(--text-2);font-size:11.5px;border-bottom:1px solid var(--accent);padding-bottom:3px}
table.ranks tr.grp th{border-bottom:0}
details.dd2{border-top:1px solid var(--line)}
details.dd2:last-of-type{border-bottom:1px solid var(--line)}
details.dd2>summary{cursor:pointer;padding:10px 0;list-style:none;display:flex;flex-wrap:wrap;gap:2px 14px;align-items:baseline}
details.dd2>summary::-webkit-details-marker{display:none}
details.dd2>summary::before{content:"\25B8";color:var(--accent);margin-right:2px}
details.dd2[open]>summary::before{content:"\25BE"}
details.dd2>summary .sm{font-size:12.5px}
details.dd2>.dbody{padding:4px 0 18px 14px;border-left:2px solid var(--line-strong);margin-left:3px}

.kpi{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
@media (max-width:600px){.kpi{grid-template-columns:repeat(6,minmax(0,1fr))}}
'''

JS = r'''(function(){
'use strict';
var DATA=JSON.parse(document.getElementById('data').textContent);
var BOTS=DATA.bots, META=DATA.meta;
function $(id){return document.getElementById(id);}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}

/* ---------- định dạng số kiểu Việt (vi-VN) ---------- */
var MINUS='−', DASH='—';
var nfc={};
function nfo(d){return nfc[d]||(nfc[d]=new Intl.NumberFormat('vi-VN',{minimumFractionDigits:d,maximumFractionDigits:d}));}
var nfPrice=new Intl.NumberFormat('vi-VN',{maximumSignificantDigits:7});
function ok(v){return typeof v==='number'&&isFinite(v);}
function num(v,d){d=d||0;if(!ok(v))return DASH;var s=nfo(d).format(Math.abs(v));return (v<0&&/[1-9]/.test(s)?MINUS:'')+s;}
function sgn(v,d){d=d||0;if(!ok(v))return DASH;var s=nfo(d).format(Math.abs(v));if(!/[1-9]/.test(s))return s;return (v<0?MINUS:'+')+s;}
function pct(v,d){return ok(v)?num(v,d==null?1:d)+'%':DASH;}
function price(v){if(!ok(v))return DASH;var s=nfPrice.format(Math.abs(v));return (v<0?MINUS:'')+s;}
function cls(v){return !ok(v)?'':(v>0?'pos':(v<0?'neg':''));}
function p2(n){return (n<10?'0':'')+n;}
function fmtVN(ms,sec){if(!ok(ms))return DASH;var d=new Date(ms+25200000);return p2(d.getUTCDate())+'/'+p2(d.getUTCMonth()+1)+' '+p2(d.getUTCHours())+':'+p2(d.getUTCMinutes())+(sec?':'+p2(d.getUTCSeconds()):'');}
function fmtDate(ms){if(!ok(ms))return DASH;var d=new Date(ms+25200000);return p2(d.getUTCDate())+'/'+p2(d.getUTCMonth()+1)+'/'+d.getUTCFullYear();}
function usdt(v,d){return ok(v)?num(v,d||0)+' USDT':DASH;}
function pm(s){return String(s==null?'':s).replace(/\+-/g,'±');}
function cap1(s){s=String(s==null?'':s);return s.charAt(0).toUpperCase()+s.slice(1);}
function fv(unit,v,d){
  if(!ok(v))return DASH;
  if(unit==='%')return pct(v,d==null?1:d);
  if(unit==='r')return num(v,2);
  if(unit==='usdt')return num(v,0);
  if(unit==='h')return num(v,d==null?1:d);
  return num(v,d||0);
}
function plural(n,w){return num(n,0)+' '+w;}
function names(a){return a.join(', ');}

/* ---------- trạng thái ---------- */
var VLAB={good:'Khớp tốt',part:'Khớp một phần',weak:'Yếu, chưa tách khỏi ngẫu nhiên',none:'Không tái tạo được'};
var STYLE_LABEL={},STYLE_DESC={};
(META.styles||[]).forEach(function(s){STYLE_LABEL[s.key]=s.label;STYLE_DESC[s.key]=s.desc;});
var state={i:0,open:false,style:'',opener:null,sel:{dy:0,bx:0,ib:0},lsw:'test',p3w:'test',openIds:{},charts:{},raf:0};
var HAS_LW=typeof LightweightCharts!=='undefined';
function chip(label,key){return label?'<span class="chip st-'+esc(key)+'">'+esc(label)+'</span>':'';}
var VSHORT={good:'Khớp tốt',part:'Khớp một phần',weak:'Yếu',none:'Không tái tạo được'};
function vchip(c,text,short){return '<span class="chip v-'+esc(c)+'" title="'+esc(VLAB[c])+'">'+esc(text||(short?VSHORT[c]:VLAB[c]))+'</span>';}
function vOf(b){return b.p2?{cls:b.p2.cls,label:b.p2.label,src:'Giai đoạn 2'}:{cls:b.p1.verdict.cls,label:b.p1.verdict.label,src:'Giai đoạn 1'};}
function beats(v,base){return ok(v)&&ok(base)&&v>base;}

/* ---------- số liệu tổng hợp để sinh văn bản ---------- */
function median(a){a=a.filter(ok).slice().sort(function(x,y){return x-y;});if(!a.length)return null;var m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2;}
function p3checks(b){
  var o=b.ov3;if(!o||!ok(o.s_test))return null;
  var L=[
    {k:'stats',label:'Điểm khớp thống kê (Level S)',v:o.s_test,base:o.s_test_p95,f:function(x){return pct(x*100,0);}},
    {k:'corr',label:'Tương quan PnL theo ngày',v:o.corr_test,base:o.corr_test_p95,f:function(x){return num(x,2);}},
    {k:'rec',label:'Trùng thời điểm vào rổ ±60 phút (cùng chiều)',v:o.rec60_test,base:o.rec60_test_p95,f:function(x){return pct(x,1);}}];
  var n=0;L.forEach(function(c){c.pass=beats(c.v,c.base);if(c.pass)n++;});
  return {n:n,list:L};
}
function agg(){
  var N=BOTS.length,A={N:N};
  var vs=BOTS.map(function(b){return vOf(b).cls;});
  A.cnt={good:0,part:0,weak:0,none:0};vs.forEach(function(c){A.cnt[c]++;});
  A.byCls=function(c){return BOTS.filter(function(b,i){return vs[i]===c;}).map(function(b){return b.name;});};
  A.exit=BOTS.filter(function(b){return ok(b.ov.exit15)&&ok(b.ov.exit_p95);});
  A.exitPass=A.exit.filter(function(b){return b.ov.exit15>b.ov.exit_p95;});
  A.addMax=BOTS.reduce(function(m,b){var v=b.ov.add;return ok(v)&&(!m||v>m.v)?{v:v,n:b.name}:m;},null);
  A.entry=BOTS.filter(function(b){return ok(b.ov.entry)&&ok(b.ov.entry_p95);});
  A.entryPass=A.entry.filter(function(b){return b.ov.entry>b.ov.entry_p95;});
  A.entryMax=BOTS.reduce(function(m,b){var v=b.ov.entry;return ok(v)&&(!m||v>m.v)?{v:v,n:b.name}:m;},null);
  A.small=BOTS.filter(function(b){return ok(b.ov.n_test)&&b.ov.n_test<20;});
  A.rules=BOTS.reduce(function(s,b){return s+(b.p1.levelB&&ok(b.p1.levelB.n_rules)?b.p1.levelB.n_rules:0);},0);
  A.s2=BOTS.filter(function(b){return ok(b.ov.s_score);});
  A.hidden=BOTS.reduce(function(s,b){return s+(b.facts.nOpen||0);},0);
  /* giai đoạn 3 */
  A.p3=BOTS.filter(function(b){return p3checks(b);});
  A.p3s=A.p3.filter(function(b){return beats(b.ov3.s_test,b.ov3.s_test_p95);});
  A.p3sf=A.p3.filter(function(b){return beats(b.ov3.s_full,b.ov3.s_full_p95);});
  A.p3c=A.p3.filter(function(b){return beats(b.ov3.corr_test,b.ov3.corr_test_p95);});
  A.p3r=A.p3.filter(function(b){return beats(b.ov3.rec60_test,b.ov3.rec60_test_p95);});
  A.p3rf=A.p3.filter(function(b){return beats(b.ov3.rec60_full,b.ov3.rec60_full_p95);});
  A.p3all=A.p3.filter(function(b){return p3checks(b).n===3;});
  A.p4=BOTS.filter(function(b){return b.ov4&&ok(b.ov4.exit15);});
  A.p4c={good:0,part:0,none:0,weak:0};A.p4.forEach(function(b){A.p4c[b.ov4.cls||'none']++;});
  A.p4pass=A.p4.filter(function(b){return beats(b.ov4.exit15,b.ov4.exit15_p95);});
  A.okCnt={};A.offCnt={};
  A.p3.forEach(function(b){(b.ov3.ok_test||[]).forEach(function(k){A.okCnt[k]=(A.okCnt[k]||0)+1;});(b.ov3.off_test||[]).forEach(function(k){A.offCnt[k]=(A.offCnt[k]||0)+1;});});
  return A;
}
var A=agg();

/* ---------- thanh bên ---------- */
function renderSide(){
  $('asof').textContent='Dữ liệu OKX đến '+(META.asOf||DASH)+', tạo ngày '+META.generated;
  var total=BOTS.length;
  var cnt={};BOTS.forEach(function(b){cnt[b.styleKey]=(cnt[b.styleKey]||0)+1;});
  var keys=Object.keys(STYLE_LABEL).filter(function(k){return cnt[k];});
  $('chips').innerHTML='<button type="button" class="fchip all" data-style="" aria-pressed="true"><span>Tất cả</span><span class="n">'+total+'/'+total+'</span></button>'
    +keys.map(function(k){return '<button type="button" class="fchip st-'+esc(k)+'" data-style="'+esc(k)+'" aria-pressed="false" title="'+esc(STYLE_DESC[k]||'')+'"><i class="dot"></i><span>'+esc(STYLE_LABEL[k])+'</span><span class="n">'+cnt[k]+'/'+total+'</span></button>';}).join('');
  $('prog').innerHTML='<div><span>Giai đoạn 1: luật viết tay</span><b>'+BOTS.length+'/'+total+'</b></div>'
    +'<div><span>Giai đoạn 2: học cơ chế, Level S</span><b>'+META.n_p2+'/'+total+'</b></div>';
}

/* ---------- tổng quan: văn bản sinh từ dữ liệu ---------- */
function topKeys(o,n){return Object.keys(o).sort(function(a,b){return o[b]-o[a];}).slice(0,n);}
function lsName(k){return (LS_META[k]||[k])[0].replace(/\s*\(.*\)$/,'');}
function maxBy(arr,f){return arr.reduce(function(m,b){var v=f(b);return ok(v)&&(!m||v>m.v)?{v:v,b:b}:m;},null);}
function renderOverview(){
  var c=A.cnt,N=A.N,P=A.p3.length,h='',pts=[];
  var p4h=null;
  if(A.p4.length){
    var Q=A.p4.length,e4=A.p4.map(function(b){return b.ov4.exit15;}),cr4=A.p4.map(function(b){return b.ov4.corr;});
    p4h='Giữ nguyên điểm vào và thêm tầng thật, luật thoát TP/SL được chỉnh trong mẫu: '+num(A.p4c.good,0)+'/'+Q+' bot tiệm cận tốt, '+num(A.p4c.part,0)+' tiệm cận một phần, '+num(A.p4c.none+A.p4c.weak,0)+' không tiệm cận được (đây là phép khớp trong mẫu, không phải dự báo).';
    var b4=maxBy(A.p4,function(b){return b.ov4.exit15;});
    pts.push('Thoát ±15 phút với luật TP/SL tiệm cận (trong mẫu): trung vị '+pct(median(e4),1)+', cao nhất '+b4.b.name+' '+pct(b4.v,1)+'; vượt p95 của TP ngẫu nhiên ở '+num(A.p4pass.length,0)+'/'+Q+' bot. Tương quan PnL mỗi rổ: trung vị '+num(median(cr4),2)+'.');
  }
  if(P){
    h='Playbook dựng từ thống kê của chính từng bot rồi chạy tự do trên đúng cửa sổ của bot: ở tập test, điểm khớp thống kê vượt mốc ngẫu nhiên p95 ở '+num(A.p3s.length,0)+'/'+P+' bot, tương quan PnL theo ngày ở '+num(A.p3c.length,0)+'/'+P+' bot, trùng thời điểm vào rổ ±60 phút ở '+num(A.p3r.length,0)+'/'+P+' bot.';
    var ss=A.p3.map(function(b){return b.ov3.s_test;}),bs=maxBy(A.p3,function(b){return b.ov3.s_test;});
    pts.push('Điểm khớp thống kê (tỷ lệ 12 chỉ số lõi nằm trong ±20% so với bot thật), tập test: trung vị '+pct(median(ss)*100,0)+', cao nhất '+bs.b.name+' '+pct(bs.v*100,0)+'; mốc ngẫu nhiên p95 của chính bot đó là '+pct(bs.b.ov3.s_test_p95*100,0)+'. Trên toàn bộ cửa sổ (tham số ước lượng một phần trong mẫu) '+num(A.p3sf.length,0)+'/'+P+' bot vượt p95.');
    var okK=topKeys(A.okCnt,3).filter(function(k){return A.okCnt[k]>0;}),offK=topKeys(A.offCnt,3);
    pts.push('Chỉ số khớp thường xuyên nhất ở tập test: '+(okK.length?okK.map(function(k){return lsName(k)+' ('+A.okCnt[k]+'/'+P+')';}).join(', '):'không có')+'. Lệch thường xuyên nhất: '+offK.map(function(k){return lsName(k)+' ('+A.offCnt[k]+'/'+P+')';}).join(', ')+'.');
    var cc=maxBy(A.p3,function(b){return b.ov3.corr_test;});
    pts.push('Tương quan PnL theo ngày (test): trung vị '+num(median(A.p3.map(function(b){return b.ov3.corr_test;})),2)+', cao nhất '+cc.b.name+' '+num(cc.v,2)+'; vượt p95 ngẫu nhiên ở '+num(A.p3c.length,0)+'/'+P+' bot. Playbook chỉ tái tạo hình dạng PnL theo ngày khi cũng tái tạo được cỡ lệnh và chiều thắng thua.');
    var rr=maxBy(A.p3,function(b){return b.ov3.rec60_test;});
    pts.push('Trùng thời điểm vào rổ ±60 phút, cùng mã cùng chiều (test): trung vị '+pct(median(A.p3.map(function(b){return b.ov3.rec60_test;})),1)+' so với p95 ngẫu nhiên trung vị '+pct(median(A.p3.map(function(b){return b.ov3.rec60_test_p95;})),1)+'; vượt ở '+num(A.p3r.length,0)+'/'+P+' bot (toàn cửa sổ: '+num(A.p3rf.length,0)+'/'+P+'), cao nhất '+rr.b.name+' '+pct(rr.v,1)+'. Dù vượt mốc, phần lớn rổ thật vẫn không có rổ mô phỏng tương ứng.');
    pts.push(num(A.p3all.length,0)+'/'+P+' bot vượt mốc ngẫu nhiên ở cả ba phép đo trên tập test'+(A.p3all.length?' ('+names(A.p3all.map(function(b){return b.name;}))+')':'')+'. Số seed ngẫu nhiên và tham số được ghi trong từng ngăn chi tiết.');
  }else{
    h='Chưa có kết quả playbook (giai đoạn 3). Các cách đã thử trước (giai đoạn 1 và 2): '+num(c.none,0)+' bot không tái tạo được'+(c.weak?', '+num(c.weak,0)+' bot ở mức yếu':'')+(c.part+c.good?', '+num(c.part+c.good,0)+' bot khớp một phần hoặc tốt':'')+'.';
  }
  var mx=maxBy(A.exit,function(b){return b.ov.exit15;});
  pts.push('Các cách đã thử trước (giai đoạn 1 và 2, khớp từng lệnh): '+num(c.good+c.part,0)+'/'+N+' bot khớp tốt hoặc một phần, '+num(c.none,0)+' không tái tạo được'+(c.weak?', '+num(c.weak,0)+' yếu':'')+'. Giờ thoát ±15 phút vượt p95 ngẫu nhiên ở '+num(A.exitPass.length,0)+'/'+A.exit.length+' bot'+(mx?' (cao nhất '+mx.b.name+' '+pct(mx.v,1)+')':'')+'; add khớp cả giờ và giá cao nhất chỉ '+(A.addMax?pct(A.addMax.v,1):DASH)+'; recall vào lệnh ±15 phút vượt p95 ở '+num(A.entryPass.length,0)+'/'+A.entry.length+' bot, cao nhất '+(A.entryMax?pct(A.entryMax.v,1):DASH)+'.');
  if(A.s2.length){var sc=A.s2.map(function(b){return b.ov.s_score;}).sort(function(a,b){return a-b;});pts.push('Level S của giai đoạn 2 (mô hình học từ dữ liệu): '+pct(sc[0]*100,0)+(sc.length>1?' đến '+pct(sc[sc.length-1]*100,0):'')+' chỉ số lõi khớp ở '+num(A.s2.length,0)+' bot; khớp thống kê chưa đồng nghĩa khớp thời điểm.');}
  pts.push(num(A.small.length,0)+'/'+N+' bot có tập test dưới 20 rổ hoặc unit ('+names(A.small.map(function(b){return b.name;}))+'): mẫu này chỉ đủ để bác bỏ một luật, không đủ để xác nhận. Đã thử '+num(A.rules,0)+' luật vào lệnh ở giai đoạn 1; ở mức p95 mỗi phép so có khoảng 5% cơ hội vượt do may mắn.');
  if(p4h){pts.unshift('Playbook tự chạy (giai đoạn 3): '+h.replace(/^Playbook dựng từ thống kê của chính từng bot rồi chạy tự do trên đúng cửa sổ của bot: /,'ở tập test, ')); h=p4h;}
  $('headline').textContent=h;
  $('points').innerHTML=pts.map(function(t){return '<li>'+esc(t)+'</li>';}).join('');
}

/* ---------- bảng 10 bot ---------- */
function cmpCell(v,base,unit,d,alt,scale){
  scale=scale||1;
  if(!ok(v))return '<td class="r num none-cell">'+DASH+'</td>';
  var win=beats(v,base);
  return '<td class="r num'+(win?' pos':'')+'">'+fv(unit||'%',v*scale,d)+(win?'<span class="tagok">vượt</span>':'')
    +'<div class="sm">'+(ok(base)?'p95 '+fv(unit||'%',base*scale,d):'không có mốc')+(alt?' · '+esc(alt):'')+'</div></td>';
}
function renderHead(){
  var has4=META.n_p4>0,th=function(t,s,r){return '<th'+(r===false?'':' class="r"')+'>'+t+(s?'<small>'+s+'</small>':'')+'</th>';};
  var g='<tr class="grp"><th colspan="4"></th>'+(has4?'<th colspan="3" class="gh">Giai đoạn 4: TP/SL tiệm cận, trong mẫu</th>':'')+'<th colspan="5" class="gh">Giai đoạn 3: playbook tự chạy</th><th colspan="6" class="gh">Đã thử trước: giai đoạn 1 và 2</th><th></th></tr>';
  var r='<tr>'+th('Hạng')+th('Bot','',false)+th('Lối chơi','',false)+th('Số rổ','tập test');
  if(has4)r+=th('Thoát ±15 phút','so với p95 ngẫu nhiên')+th('Tương quan PnL','mỗi rổ')+th('Kết luận','',false);
  r+=th('Điểm khớp thống kê','test, so với p95')+th('Điểm khớp thống kê','toàn cửa sổ')+th('Tương quan PnL','theo ngày, test')+th('Trùng rổ ±60 phút','test, cùng chiều')+th('Vượt mốc','trên 3 phép đo')
    +th('Thoát ±15 phút','test, so với p95')+th('Add khớp','giờ và giá')+th('Vào lệnh, recall ±15 phút','so với p95 khớp giờ')+th('Tương quan PnL','mỗi rổ')+th('Level S','giai đoạn 2')+th('Kết luận','',false)+'<th aria-label="Mở"></th></tr>';
  $('ranks-head').innerHTML=g+r;
}
function renderRanks(){
  var h='';
  BOTS.forEach(function(b,i){
    if(state.style&&b.styleKey!==state.style)return;
    var o=b.ov,o3=b.ov3,v=vOf(b),ck=p3checks(b);
    var n=ok(o.n)?'<span class="mono">'+num(o.n,0)+'</span> '+esc(o.unit)+' <span class="sm">(test <span class="mono">'+num(o.n_test,0)+'</span>)</span>':DASH;
    var alt=o.exit_alt&&ok(o.exit_alt.val)?o.exit_alt.label+' '+pct(o.exit_alt.val,1):'';
    var exit=cmpCell(o.exit15,o.exit_p95,'%',1,alt);
    var addc=ok(o.add)?'<td class="r num'+(o.add>=50?' pos':'')+'" title="'+esc(o.add_note||'')+'">'+pct(o.add,1)+'</td>':'<td class="r num none-cell">'+DASH+'</td>';
    var ent=cmpCell(o.entry,o.entry_p95,'%',1);
    var corr=ok(o.pnl_corr)?'<td class="r num'+(beats(o.pnl_corr,o.pnl_corr_p95)?' pos':'')+'">'+num(o.pnl_corr,2)+'<div class="sm">'+(ok(o.pnl_corr_p95)?'p95 '+num(o.pnl_corr_p95,2):'không có mốc')+'</div></td>':'<td class="r num none-cell">'+DASH+'</td>';
    var ls=ok(o.s_score)?'<td class="r num">'+pct(o.s_score*100,0)+'</td>':'<td class="r num none-cell" title="Giai đoạn 2 chưa có kết quả">'+DASH+'</td>';
    var p4c='';
    if(META.n_p4>0){
      var o4=b.ov4;
      if(o4&&ok(o4.exit15)){var bs4=ok(o4.exit15_p95)?o4.exit15_p95:o4.exit15_null;p4c=cmpCell(o4.exit15,bs4,'%',1)+cmpCell(o4.corr,o4.corr_p95,'r',2)+'<td>'+(o4.label?vchip(o4.cls||'none',{good:'Tiệm cận tốt',part:'Tiệm cận một phần',weak:'Yếu',none:'Không tiệm cận được'}[o4.cls||'none']):DASH)+'</td>';}
      else p4c='<td class="r num none-cell" colspan="3">chưa có</td>';
    }
    var p3='';
    if(o3&&ck){
      p3=cmpCell(o3.s_test,o3.s_test_p95,'%',0,'',100)+cmpCell(o3.s_full,o3.s_full_p95,'%',0,'',100)+cmpCell(o3.corr_test,o3.corr_test_p95,'r',2)+cmpCell(o3.rec60_test,o3.rec60_test_p95,'%',1)
        +'<td class="r num'+(ck.n>=2?' pos':'')+'">'+ck.n+'/3</td>';
    }else{p3='<td class="r num none-cell" colspan="5" title="Chưa có out/playbook_'+esc(b.slug)+'.json">chưa có playbook</td>';}
    h+='<tr tabindex="0" data-i="'+i+'" role="button" aria-label="Mở chi tiết '+esc(b.name)+'">'
      +'<td class="rank r">'+b.rank+'</td>'
      +'<td class="nm">'+esc(b.name)+'</td>'
      +'<td>'+chip(b.style,b.styleKey)+'</td>'
      +'<td class="r">'+n+'</td>'
      +p4c+p3+exit+addc+ent+corr+ls
      +'<td>'+vchip(v.cls,null,true)+'<span class="srcmark">'+esc(v.src==='Giai đoạn 2'?'GĐ2':'GĐ1')+'</span></td>'
      +'<td class="go" aria-hidden="true">›</td></tr>';
  });
  $('ranks-body').innerHTML=h||'<tr><td colspan="19" class="muted">Không có bot nào thuộc lối chơi này.</td></tr>';
  var chips=document.querySelectorAll('#chips .fchip');
  for(var k=0;k<chips.length;k++)chips[k].setAttribute('aria-pressed',String((chips[k].getAttribute('data-style')||'')===state.style));
}

/* ---------- phương pháp và giới hạn ---------- */
function renderMethod(){
  var flow=[['Đọc lối chơi','Mô tả OKX công bố: cách chơi, vì sao thắng, rủi ro.'],
    ['Đặt giả thuyết','Từ mô tả và số liệu lệnh: bước add, mức chốt, phiên giờ, loại mã.'],
    ['Họ luật','Vào lệnh, thêm tầng, thoát: bước %, ATR, chỉ báo nến đóng, trailing, giờ phiên.'],
    ['Backtest cùng mã, cùng kỳ','Nến 1 phút của đúng các mã và khoảng thời gian bot đã chạy, phí 3,5 bps mỗi chiều.'],
    ['So với lệnh thật','Giờ thoát, add, điểm vào, PnL từng rổ; tất cả có mốc ngẫu nhiên.']];
  $('mflow').innerHTML=flow.map(function(f){return '<li><i class="nd"></i><b class="t">'+esc(f[0])+'</b><span class="s">'+esc(f[1])+'</span></li>';}).join('');
  var gl=[['Chia 60/40 theo thời gian','60% rổ đầu (theo giờ fill đầu) là train, 40% cuối là test. Luật và tham số chỉ được chọn trên train, điểm báo cáo là điểm test. Nhóm dưới 40 rổ dùng thêm bỏ-một-ra (LOO) và walk-forward.'],
    ['Mốc ngẫu nhiên','Thoát: TP ngẫu nhiên rút từ phân phối train, hoặc hoán vị thời gian giữ lệnh, hoặc time-stop rỗng. Vào lệnh: ngẫu nhiên đều và ngẫu nhiên khớp giờ. Chỉ tính là vượt khi lớn hơn p95 của mốc.'],
    ['Level A: điều kiện hoá','Dùng fill đầu thật (và với nhóm replay, cả các fill thật) rồi chỉ mô phỏng phần còn lại; so giờ thoát trong ±5/15/60 phút, add, số tầng, dấu và tương quan PnL từng rổ.'],
    ['Level B: điểm vào tự do','Luật vào chạy một mình trên nến; recall là phần điểm vào thật có tín hiệu trong ±15/60 phút, precision là phần tín hiệu trúng điểm vào thật.'],
    ['Level S: backtest tự chạy','Vào, add, thoát đều do luật mô phỏng, chạy trên đúng cửa sổ của bot với quy mô lệnh học từ lệnh thật; so các chỉ số thống kê (12 chỉ số lõi trong ±20%), PnL theo ngày, trùng lặp rổ.'],
    ['Giai đoạn 1 và 2','Giai đoạn 1: luật viết tay rồi grid search. Giai đoạn 2: dựng bảng mọi thời điểm bot có thể hành động, học xem trạng thái nào dự đoán hành động, rút luật đơn giản nhất giữ được độ chính xác.']];
  $('mgrid').innerHTML=gl.map(function(x){return '<div><h3>'+esc(x[0])+'</h3><p>'+esc(x[1])+'</p></div>';}).join('');
  var lim=[
    'Cross margin: OKX chỉ công bố từng sub-position đã đóng. Quy mô, đòn bẩy và thanh lý của cả tài khoản không quan sát được; PnL mô phỏng dùng notional của lệnh thật, không mô hình thanh lý.',
    'OKX ẩn vị thế đang mở: '+num(A.hidden,0)+' vị thế mở của '+BOTS.filter(function(b){return b.facts.nOpen;}).length+' bot không có trong dữ liệu, nên các rổ chưa đóng và lỗ treo không được đối chiếu.',
    'So sánh nhiều lần: mỗi bot thử hàng trăm luật vào ('+num(A.rules,0)+' luật tổng cộng) và nhiều họ thoát. Chọn trên train rồi báo cáo trên test, kèm mốc ngẫu nhiên, giảm nhưng không loại bỏ rủi ro chọn trúng do may. Kết quả vượt p95 ở một bot nhỏ chưa phải bằng chứng.',
    'Mẫu nhỏ: '+num(A.small.length,0)+' bot có tập test dưới 20 rổ hoặc unit. Chia 60/40 trên mẫu như vậy chỉ đủ để bác bỏ, không đủ để xác nhận.',
    'Mô phỏng khớp tại giá mở nến 1 phút kế tiếp, phí 3,5 bps mỗi chiều, không funding. Bot dùng lệnh limit hoặc khớp trong nến có thể lệch vài bps đến vài chục bps so với giá mô phỏng.',
    'Chỉ có dữ liệu giá nến. Không có sổ lệnh, không có tín hiệu bên ngoài (tin tức, dòng tiền, các bot khác), và bot có thể can thiệp bằng tay (nhiều bot ngủ theo giờ người).',
    'Tên đặc trưng của giai đoạn 2 là mã nội bộ: upnl là lãi lỗ chưa thực hiện (%), hậu tố a1m, a15m, a1h là chia cho ATR 1 phút, 15 phút, 1 giờ; mfe, gb, mae là lãi lớn nhất đã đạt, phần trả lại từ đỉnh, mức đi ngược tối đa; mins_first, mins_last là số phút từ fill đầu, fill cuối; volz là khối lượng 1 phút theo z-score; cal_ là đặc trưng lịch (giờ trong ngày, cách mở cửa Mỹ 13:30 UTC); tiền tố s_ là chuẩn hoá theo từng mã. Diễn giải gần đúng, xem DISCOVERY_SPEC.md mục 1.'];
  $('limits-body').innerHTML='<ul>'+lim.map(function(t){return '<li>'+esc(t)+'</li>';}).join('')+'</ul>';
}

/* ---------- ngăn chi tiết ---------- */
function kpi(l,v,s){return '<div><dt>'+esc(l)+'</dt><dd>'+v+(s?' <small>'+esc(s)+'</small>':'')+'</dd></div>';}
function table(head,rows,cls){
  return '<div class="tablewrap"><table class="grid mt'+(cls?' '+cls:'')+'"><thead><tr>'+head.map(function(h,i){return '<th'+(i?' class="r"':'')+'>'+esc(h)+'</th>';}).join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';
}
function td(v,c){return '<td class="num'+(c?' '+c:'')+'">'+v+'</td>';}

function blockTable(bk){
  var cols=bk.cols,head=['Chỉ số','Train','Test'];
  if(cols.loo)head.push('LOO');
  if(cols.wf)head.push('Walk-forward');
  if(cols.p95)head.push('p95 ngẫu nhiên');
  if(cols.null)head.push('Mốc rỗng');
  var rows=bk.rows.map(function(r){
    var d=r.unit==='r'?2:1;
    var win=(r.unit==='%'||r.unit==='r')&&beats(r.test,r.p95);
    var t='<tr><td>'+esc(r.label)+'</td>'+td(fv(r.unit,r.train,d))+td(fv(r.unit,r.test,d),win?'pos':'');
    if(cols.loo)t+=td(fv(r.unit,r.loo,d));
    if(cols.wf)t+=td(fv(r.unit,r.wf,d));
    if(cols.p95)t+=td(ok(r.p95)?fv(r.unit,r.p95,d):DASH);
    if(cols.null)t+=td(ok(r.null)?fv(r.unit,r.null,d):DASH);
    return t+'</tr>';
  });
  var cap=[];
  if(bk.base_kind)cap.push('p95 ngẫu nhiên: '+bk.base_kind+'.');
  if(cols.null)cap.push('Mốc rỗng: một fill, không add, thoát theo time-stop bằng bội trung vị thời gian giữ của train.');
  cap.push('Chữ xanh: điểm test vượt p95 ngẫu nhiên. USDT: PnL cộng dồn cả tập (mô phỏng dùng notional thật).');
  return '<h4>'+esc(bk.title)+(bk.name?' <span class="code">'+esc(bk.name)+'</span>':'')+'</h4>'+table(head,rows)+'<p class="tcap">'+esc(cap.join(' '))+'</p>';
}
function levelBTable(lb){
  if(!lb)return '<p class="sub">Không có kết quả Level B cho bot này.</p>';
  var rows=lb.rows.map(function(r){
    var win=beats(r.test,r.hour_p95)&&beats(r.test,r.rand_p95);
    return '<tr><td>'+esc(r.label)+'</td>'+td(pct(r.train,1))+td(pct(r.test,1),win?'pos':'')+td(ok(r.hits)?num(r.hits,0):DASH)+td(pct(r.hour_mean,1))+td(pct(r.hour_p95,1))+td(pct(r.rand_p95,1))+'</tr>';
  });
  return '<h4>Level B: điểm vào lệnh tự do (luật vào tốt nhất theo train)</h4>'
    +(lb.rule?'<p class="sub">Luật: <span class="code">'+esc(lb.rule)+'</span>. Tập test có '+num(lb.n_actual,0)+' điểm vào thật, luật phát '+num(lb.n_sim,0)+' tín hiệu'+(ok(lb.n_rules)?'; đã thử '+num(lb.n_rules,0)+' luật trên train':'')+'.</p>':'')
    +table(['Chỉ số','Train','Test','Số trúng','Khớp giờ: trung bình','Khớp giờ: p95','Ngẫu nhiên: p95'],rows)
    +'<p class="tcap">'+esc('Khớp giờ: tín hiệu ngẫu nhiên đặt trong đúng các giờ bot hay vào lệnh. Chữ xanh khi điểm test vượt cả hai p95. '+(lb.strength?'Nhận xét của phép thử: '+pm(lb.strength)+'.':''))+'</p>';
}
function extraTable(ex){
  if(!ex||!ex.length)return '';
  function c(x){return x?(num(x.hits,0)+'/'+num(x.n,0)+' ('+pct(x.recall,1)+')'):DASH;}
  var rows=ex.map(function(r){
    return '<tr><td>'+esc(r.label)+'</td>'+td(c(r.loo))+td(r.loo?num(r.loo.exp,1):DASH)+td(r.loo?num(r.loo.p,4):DASH)+td(c(r.wf))+td(r.wf?num(r.wf.exp,1):DASH)+td(r.wf?num(r.wf.p,4):DASH)+'</tr>';
  });
  return '<h4>Kiểm tra bổ sung cho mẫu nhỏ: bỏ-một-ra (LOO) và walk-forward</h4>'
    +table(['Chỉ số','LOO: trúng/tổng','Kỳ vọng ngẫu nhiên','p','Walk-forward: trúng/tổng','Kỳ vọng ngẫu nhiên','p'],rows)
    +'<p class="tcap">Kỳ vọng ngẫu nhiên là số lần trúng trung bình khi đặt tín hiệu ngẫu nhiên; p là xác suất đạt từ mức này trở lên chỉ do ngẫu nhiên. Dải ±4 giờ rộng nên dễ trúng hơn dải ±15 phút.</p>';
}
var LA_ROWS=[['Thoát khớp ±5 phút','%','close_match_5'],['Thoát khớp ±15 phút','%','close_match_15'],['Thoát khớp ±60 phút','%','close_match_60'],
  ['Add khớp giờ và giá','%','tr_add_match'],['Add khớp riêng về giờ','%','tr_add_time_match'],['Số tầng bằng số tầng thật','%','tr_layer_eq'],
  ['Dấu PnL cùng dấu thật','%','pnl_sign_agree'],['Tương quan lợi suất','r','pnl_corr'],['Tỷ lệ thắng thật','%','act_win_pct'],['Tỷ lệ thắng mô phỏng','%','sim_win_pct'],
  ['PnL cộng dồn thật (USDT)','usdt','act_pnl_sum'],['PnL cộng dồn mô phỏng (USDT)','usdt','sim_pnl_sum']];
function p2LevelA(p2){
  var la=p2.level_a||{},ex=la.exit_only,fu=la.full,nu=(p2.base||{}).null,sh=(p2.base||{}).shuffled;
  if(!ex&&!fu)return '';
  var head=['Chỉ số'],cols=[];
  if(ex){head.push('Chỉ thoát (replay)');cols.push('ex');}
  if(fu){head.push('Đầy đủ: add và thoát');cols.push('fu');}
  if(nu){head.push('Mốc rỗng');cols.push('nu');}
  if(sh){head.push('p95 TP ngẫu nhiên');cols.push('sh');}
  var rows=LA_ROWS.map(function(r){
    var trivial=/^(tr_add_match|tr_add_time_match|tr_layer_eq)$/.test(r[2]);
    var vals={ex:ex&&!trivial?ex[r[2]]:null,fu:fu?fu[r[2]]:null,nu:nu?nu[r[2]]:null,sh:sh&&sh[r[2]]?sh[r[2]].p95:null};
    if(!cols.some(function(c){return ok(vals[c]);}))return '';
    var d=r[1]==='r'?2:1;
    return '<tr><td>'+esc(r[0])+'</td>'+cols.map(function(c){
      var win=(c==='ex'||c==='fu')&&ok(vals[c])&&(r[1]==='%'||r[1]==='r')&&ok(vals.sh)&&vals[c]>vals.sh&&(r[2].indexOf('close')===0||r[2]==='pnl_corr');
      return td(fv(r[1],vals[c],d),win?'pos':'');
    }).join('')+'</tr>';
  }).filter(Boolean);
  var ci=p2.ci&&ok(p2.ci[0])?' Khoảng tin cậy 95% của thoát ±15 phút (mô hình chính): '+pct(p2.ci[0],1)+' đến '+pct(p2.ci[1],1)+'.':'';
  return '<h4>Level A, giai đoạn 2: luật học từ điểm quyết định (tập test)</h4>'+table(head,rows)
    +'<p class="tcap">'+esc('Mô hình chính: '+(p2.primary||DASH)+'. Chữ xanh: vượt p95 của TP ngẫu nhiên.'+ci)+'</p>';
}
function p2Panels(p2){
  var pn=p2.panels||{},keys=['exit','add','entry'].filter(function(k){return pn[k]&&!pn[k].skipped&&ok(pn[k].auc);});
  var lab={exit:'Thoát',add:'Add',entry:'Vào lệnh'};
  var h='';
  if(keys.length){
    var rows=keys.map(function(k){var p=pn[k];
      return '<tr><td>'+lab[k]+'</td>'+td(ok(p.n_rows)?num(p.n_rows,0):DASH)+td(ok(p.n_pos)?num(p.n_pos,0):DASH)+td(num(p.auc,3),p.auc>=0.65?'pos':'')+td(ok(p.tree_auc)?num(p.tree_auc,3):DASH)+td(ok(p.pair_auc)?num(p.pair_auc,3):DASH)
        +'<td>'+(p.auc>=0.65?'<span class="pill yes">dự đoán được</span>':'<span class="pill no">không dự đoán được</span>')+'</td></tr>';});
    h+='<h4>Độ dự đoán hành động từ trạng thái giá, vị thế và giờ</h4>'+table(['Hành động','Số hàng','Số hàng dương','AUC GBM (test)','AUC cây sâu 3','AUC luật cặp','Kết luận'],rows)
      +'<p class="tcap">AUC dưới 0,65 nghĩa là hành động không dự đoán được từ trạng thái quan sát. AUC cao ở bảng thoát có thể chỉ phản ánh thoát khi đang lãi, nên phải đọc cùng độ khớp giờ ở Level A.</p>';
    var top=keys.filter(function(k){return (pn[k].imp||[]).length;}).map(function(k){return '<li><b>'+lab[k]+'</b>: <span class="code">'+esc(pn[k].imp.join(', '))+'</span>'+(pn[k].pair?'; luật cặp: <span class="code">'+esc(pn[k].pair)+'</span>':'')+'</li>';});
    if(top.length)h+='<p class="sub" style="margin-top:10px">Đặc trưng quan trọng nhất (hoán vị trên test):</p><ul class="bl">'+top.join('')+'</ul>';
  }
  var mech=p2.mechanism||{},mt=['exit','add','entry'].map(function(k){
    var t=mech[k];if(!t||typeof t!=='string'||t.indexOf('xem panels')>=0)return '';
    t=t.replace(/\s*\(AUC GBM test \?\)/,'').replace(/;?\s*luật cặp: None/,'').replace(/Luật cặp: None\.?/,'');
    return '<li>'+esc(t.trim())+'</li>';}).filter(Boolean);
  if(mt.length)h+='<h4>Cơ chế rút ra (giai đoạn 2)</h4><ul class="bl">'+mt.join('')+'</ul>';
  return h;
}
var LS_META={perDay:['Lệnh mỗi ngày',2],win:['Thắng (% lệnh)',1],pf:['Profit factor',2],payoff:['Payoff (lãi TB chia lỗ TB)',2],longPct:['Long (%)',1],holdMed:['Giữ lệnh trung vị (giờ)',2],
  top5Share:['5 lệnh lãi lớn nhất chiếm (% lãi)',1],addPct:['Lệnh là tầng thêm (%)',1],addDownPct:['Thêm tầng khi giá đi ngược (%)',1],stepMed:['Bước giá giữa tầng, trung vị (%)',2],maxLayers:['Số tầng tối đa',0],
  baskets:['Số rổ',0],levMed:['Đòn bẩy trung vị',1],holdWin:['Giữ lệnh thắng (giờ)',2],holdLoss:['Giữ lệnh lỗ (giờ)',2],maxLoss:['Lỗ lớn nhất (USDT)',0],maxWin:['Lãi lớn nhất (USDT)',0],
  realized:['PnL thực hiện (USDT)',0],momPct:['Vào cùng chiều đà 24 giờ (%)',1],winMaeMed:['Giá đi ngược trung vị của lệnh thắng (%)',2],n:['Số lệnh con',0]};
var LS_ORDER=['perDay','win','pf','payoff','longPct','holdMed','top5Share','addPct','addDownPct','stepMed','maxLayers','baskets','levMed','holdWin','holdLoss','maxLoss','maxWin','realized','momPct','winMaeMed','n'];
var LS_CORE={perDay:1,win:1,pf:1,payoff:1,longPct:1,holdMed:1,top5Share:1,addPct:1,addDownPct:1,stepMed:1,maxLayers:1,baskets:1};
function levelS(b){
  var ls=b.p2&&b.p2.level_s;
  if(!ls||!ls.windows)return '<h4>Level S: backtest tự chạy</h4><div class="empty2">Chưa có kết quả Level S cho bot này. Khi giai đoạn 2 (run_disc.py) chạy xong, chạy lại build_report.py để hiện bảng so sánh thật với mô phỏng.</div>';
  var ws=Object.keys(ls.windows);if(ws.indexOf(state.lsw)<0)state.lsw=ws.indexOf('test')>=0?'test':ws[0];
  var w=ls.windows[state.lsw];
  var WL={test:'Cửa sổ test (40% cuối)',full:'Toàn bộ cửa sổ'};
  var tabs=ws.length>1?'<div class="tabsx" role="group" aria-label="Cửa sổ Level S">'+ws.map(function(k){return '<button type="button" data-ls="'+esc(k)+'" aria-pressed="'+(k===state.lsw)+'">'+esc(WL[k]||k)+'</button>';}).join('')+'</div>':'';
  var rows=LS_ORDER.filter(function(k){return w.rows&&w.rows[k];}).map(function(k){
    var r=w.rows[k],m=LS_META[k]||[k,2],core=LS_CORE[k];
    return '<tr'+(core?'':' class="muted"')+'><td>'+esc(m[0])+(core?'':' <span class="sm">(không tính điểm)</span>')+'</td>'+td(num(r.real,m[1]))+td(num(r.sim,m[1]))+td(ok(r.rel_err)?sgn(r.rel_err*100,0)+'%':DASH)
      +'<td class="r">'+(core?(r.ok?'<span class="pill yes">trong ngưỡng</span>':'<span class="pill no">lệch</span>'):'')+'</td></tr>';
  });
  var ov=w.overlap||{},dl=w.daily||{};
  var kv='<dl class="kvg" style="margin-top:12px">'
    +'<div><dt>Điểm khớp thống kê</dt><dd>'+(ok(w.score)?pct(w.score*100,0)+' ('+num(w.n_ok,0)+'/'+num(w.n_core,0)+')':DASH)+'</dd></div>'
    +'<div><dt>Tương quan PnL theo ngày</dt><dd>'+(ok(dl.daily_corr)?num(dl.daily_corr,2):DASH)+'</dd></div>'
    +'<div><dt>Cùng dấu lãi lỗ theo ngày</dt><dd>'+(ok(dl.day_sign_agree)?pct(dl.day_sign_agree*100,0):DASH)+'</dd></div>'
    +'<div><dt>Trùng cơ cấu mã</dt><dd>'+(ok(w.mix)?pct(w.mix*100,0):DASH)+'</dd></div>'
    +'<div><dt>Rổ thật có rổ mô phỏng ±15 phút</dt><dd>'+pct(ov.recall_15,1)+'</dd></div>'
    +'<div><dt>Rổ mô phỏng trúng rổ thật ±15 phút</dt><dd>'+pct(ov.precision_15,1)+'</dd></div>'
    +'<div><dt>Rổ thật có rổ mô phỏng ±60 phút</dt><dd>'+pct(ov.recall_60,1)+'</dd></div>'
    +'<div><dt>Số rổ thật, số rổ mô phỏng</dt><dd>'+(ok(ov.n_real_baskets)?num(ov.n_real_baskets,0)+', '+num(ov.n_sim_baskets,0):DASH)+'</dd></div></dl>';
  var ct=(w.window&&w.window.length===2)?fmtDate(w.window[0])+' đến '+fmtDate(w.window[1]):'';
  var smp='';
  if(w.trades&&w.trades.length){
    smp='<details class="dd"><summary>Mẫu '+num(Math.min(10,w.trades.length),0)+' lệnh mô phỏng đầu tiên</summary>'+table(['Mã','Chiều','Đòn bẩy','Vào (giờ VN)','Ra (giờ VN)','Giá vào','Giá ra','PnL (USDT)','% ký quỹ'],
      w.trades.slice(0,10).map(function(t){return '<tr><td>'+esc(t.sym)+'</td>'+td(esc(t.side==='long'?'long':'short'))+td(num(t.lev,0)+'x')+td(fmtVN(t.o))+td(fmtVN(t.c))+td(price(t.po))+td(price(t.pc))+td(num(t.pnl,1),cls(t.pnl))+td(pct(t.pr,1))+'</tr>';}))+'</details>';
  }
  return '<h4>Level S: backtest tự chạy trên cửa sổ của bot (mô hình '+esc(ls.model)+')</h4>'+tabs
    +'<p class="sub">'+esc((ct?'Cửa sổ '+ct+'. ':'')+'Vào, add, thoát đều do luật mô phỏng, quy mô lệnh học từ train. Điểm khớp thống kê là tỷ lệ trong 12 chỉ số lõi nằm trong ±20% (hoặc ±5 điểm với chỉ số phần trăm).')+'</p>'
    +table(['Chỉ số','Thật','Mô phỏng','Sai số tương đối',''],rows)+kv+smp
    +'<div class="cblock"><p class="tcap" style="margin:0 0 6px">PnL thực hiện cộng dồn theo ngày đóng (UTC): thật và mô phỏng</p><div class="chartbox"><div class="clegend" id="ls-legend"></div><div class="chart eq" id="ls-chart"></div><div class="cempty" id="ls-empty" hidden></div></div></div>';
}

/* ---------- giai đoạn 3: playbook ---------- */
var PROF_DIR_MIN=50;
function bestDir(prof){
  var d=prof.dir_share_pct,best=null;
  if(!d)return null;
  Object.keys(d).forEach(function(h){var v=d[h];if(ok(v)&&(!best||Math.abs(v-50)>Math.abs(best.v-50)))best={h:+h,v:v};});
  return best;
}
function profileKv(p3){
  var P=p3.profile||{},out=[];
  function add(l,v){if(v!=null&&v!==DASH&&v!=='')out.push([l,v]);}
  add('Số rổ, lệnh con (train)',ok(P.n_baskets)?num(P.n_baskets,0)+', '+num(P.n_trades,0):null);
  add('Long (% lệnh)',ok(P.long_pct)?pct(P.long_pct,1):null);
  add('Rổ mở khi rổ ngược chiều cùng mã đang mở',ok(P.opp_side_open_pct)?pct(P.opp_side_open_pct,1):null);
  add('Vào lại trong 5 phút sau khi đóng',ok(P.reentry_within_5min_pct)?pct(P.reentry_within_5min_pct,1):null);
  var bd=bestDir(P);
  if(bd)add('Hướng giá trước khi vào (khung '+bd.h+' phút)',pct(bd.v,1)+' cùng chiều đà'+(Math.abs(bd.v-50)<8?' (gần 50%: không thiên hướng)':bd.v<50?' (thiên về bắt hồi)':' (thiên về theo đà)'));
  if(P.vol_auc){var vk=Object.keys(P.vol_auc).sort(function(a,b){return P.vol_auc[b]-P.vol_auc[a];})[0];add('Biến động lúc vào so với ngẫu nhiên (AUC, khung '+vk+' phút)',num(P.vol_auc[vk],2)+' (0,5 là như nhau)');}
  add('Thắng (% rổ)',ok(P.win_pct)?pct(P.win_pct,1):null);
  if(P.gret_win_pct)add('Lãi mỗi rổ thắng, trung vị (% notional)',num(P.gret_win_pct['50'],2)+'% (p25 '+num(P.gret_win_pct['25'],2)+', p75 '+num(P.gret_win_pct['75'],2)+')');
  add('Lệnh thua: lợi suất đóng chia mức đi ngược tối đa',ok(P.loser_ret_over_mae)?num(P.loser_ret_over_mae,2)+(P.loser_ret_over_mae>=0.8?' (cắt lỗ ở đáy)':P.loser_ret_over_mae<=0.6?' (giữ chờ hồi)':' (trung gian)'):null);
  add('Mức đi ngược trung vị của lệnh thua (%)',ok(P.mae_loser_pct_med)?num(P.mae_loser_pct_med,2):null);
  if(P.hold_min)add('Giữ rổ, trung vị (phút)',num(P.hold_min['50'],0)+' (p95 '+num(P.hold_min['95'],0)+')');
  add('Giữ rổ thắng, thua (phút)',ok(P.hold_win_min_med)?num(P.hold_win_min_med,0)+', '+num(P.hold_loser_min_med,0):null);
  add('Rổ có thêm tầng (%)',ok(P.add_basket_pct)?pct(P.add_basket_pct,1):null);
  add('Bước thêm tầng, trung vị (%)',ok(P.step_pct_med)?num(P.step_pct_med,2)+' (hệ số biến thiên '+num(P.step_cv,2)+')':null);
  add('Size tầng thêm chia size tầng đầu, trung vị',ok(P.add_ratio_med)?num(P.add_ratio_med,2):null);
  add('Số tầng tối đa (p95)',ok(P.n_tr_p95)?num(P.n_tr_p95,0):null);
  add('Notional vào đầu, trung vị (USDT)',ok(P.n0_med)?num(P.n0_med,0):null);
  add('Đòn bẩy trung vị',ok(P.lev_med)?num(P.lev_med,0)+'x':null);
  add('Số rổ tối đa cùng lúc',ok(P.max_concurrent)?num(P.max_concurrent,0):null);
  return out;
}
function playSection(b){
  var p3=b.p3;
  if(!p3)return '<div class="empty2">Chưa có playbook cho bot này (không có out/playbook_'+esc(b.slug)+'.json). Khi giai đoạn 3 chạy xong, chạy lại build_report.py.</div>';
  var R=p3.rules||{},h='';
  var G=[['entry','Vào lệnh'],['add','Thêm tầng'],['exit','Thoát'],['sizing','Quy mô lệnh']];
  G.forEach(function(g){var a=R[g[0]];if(a&&a.length)h+='<h4>'+g[1]+'</h4><ul class="bl">'+a.map(function(t){return '<li>'+esc(pm(t))+'</li>';}).join('')+'</ul>';});
  var kv=profileKv(p3);
  if(kv.length)h+='<h4>Số liệu pháp y của bot trên tập train (cơ sở cho các tham số)</h4><dl class="kvg">'+kv.map(function(x){return '<div><dt>'+esc(x[0])+'</dt><dd>'+esc(x[1])+'</dd></div>';}).join('')+'</dl>';
  var pc=p3.profile&&p3.profile.per_class;
  if(pc&&Object.keys(pc).length){
    h+=table(['Lớp mã','Số rổ','Long (%)','TP trung vị (%)','Giữ trung vị (phút)','Notional trung vị'],Object.keys(pc).map(function(k){var r=pc[k];return '<tr><td>'+esc(k)+'</td>'+td(num(r.n,0))+td(pct(r.long_pct,1))+td(num(r.tp_pct_med,2))+td(num(r.hold_med_min,0))+td(num(r.n0_med,0))+'</tr>';}));
  }
  if(p3.kv&&p3.kv.length)h+='<details class="dd"><summary>Tham số đã ước lượng ('+p3.kv.length+')</summary><dl class="kvg">'+p3.kv.map(function(x){return '<div><dt>'+esc(x[0])+'</dt><dd>'+esc(typeof x[1]==='number'?num(x[1],x[1]%1?3:0):String(x[1]))+'</dd></div>';}).join('')+'</dl>'
    +(p3.calibration&&p3.calibration.target?'<p class="tcap">'+esc('Hiệu chỉnh tần suất vào lệnh theo lớp mã (rổ mỗi ngày ở train): '+Object.keys(p3.calibration.target).map(function(k){return k+' '+num(p3.calibration.target[k],2);}).join(', ')+'.')+'</p>':'')+'</details>';
  if(p3.iterations&&p3.iterations.length)h+='<details class="dd"><summary>Các vòng chỉnh luật ('+p3.iterations.length+')</summary>'+table(['Vòng','Thay đổi','Nhận','Điểm train','Điểm test','Tương quan ngày (test)','Trùng ±60p (test)'],p3.iterations.map(function(it){return '<tr><td class="code" style="text-align:left">'+esc(it.name||it.i)+'</td><td style="text-align:left;white-space:normal;min-width:30ch">'+esc(pm(it.change||''))+'</td><td class="r">'+(it.acc?'có':'không')+'</td>'+td(ok(it.train)?num(it.train,3):DASH)+td(ok(it.s_test)?pct(it.s_test*100,0):DASH)+td(ok(it.c_test)?num(it.c_test,2):DASH)+td(pct(it.r60,1))+'</tr>';}))+'<p class="tcap">Các vòng chỉnh theo quy tắc từ tập train; điểm test chỉ để báo cáo, không dùng để chọn.</p></details>';
  return h;
}
function statLine(base,key,f){var s=base&&base[key];return s&&ok(s.mean)?' (mốc ngẫu nhiên: trung bình '+f(s.mean)+', p95 '+f(s.p95)+')':'';}
function lsSection(b){
  var p3=b.p3;if(!p3||!p3.windows)return '<div class="empty2">Chưa có Level S của playbook.</div>';
  var ws=Object.keys(p3.windows);if(!ws.length)return '<div class="empty2">Chưa có Level S của playbook.</div>';
  if(ws.indexOf(state.p3w)<0)state.p3w=ws.indexOf('test')>=0?'test':ws[0];
  var w=p3.windows[state.p3w],base=(p3.base||{})[state.p3w]||{};
  var WL={test:'Cửa sổ test (40% cuối, ngoài mẫu)',full:'Toàn bộ cửa sổ (60% đầu là trong mẫu)'};
  var tabs='<div class="tabsx" role="group" aria-label="Cửa sổ Level S">'+ws.map(function(k){return '<button type="button" data-p3w="'+esc(k)+'" aria-pressed="'+(k===state.p3w)+'">'+esc(WL[k]||k)+'</button>';}).join('')+'</div>';
  var okr=base.metric_ok_rate||{};
  var rows=LS_ORDER.filter(function(k){return w.rows&&w.rows[k];}).map(function(k){
    var r=w.rows[k],m=LS_META[k]||[k,2],core=LS_CORE[k];
    return '<tr'+(core?'':' class="muted"')+'><td>'+esc(m[0])+(core?'':' <span class="sm">(không tính điểm)</span>')+'</td>'+td(num(r.real,m[1]))+td(num(r.sim,m[1]))+td(ok(r.rel_err)?sgn(r.rel_err*100,0)+'%':DASH)
      +'<td class="r">'+(core?(r.ok?'<span class="pill yes">trong ngưỡng</span>':'<span class="pill no">lệch</span>'):'')+'</td>'+td(core&&ok(okr[k])?pct(okr[k]*100,0):DASH)+'</tr>';
  });
  var sb=base.stats_match||{};
  var win=beats(w.score,sb.p95);
  var h=tabs+'<p class="sub"><b>Điểm khớp thống kê: '+(ok(w.score)?pct(w.score*100,0):DASH)+'</b> ('+num(w.n_ok,0)+'/'+num(w.n_core,0)+' chỉ số lõi trong ±20% hoặc ±5 điểm phần trăm)'
    +(ok(sb.mean)?'; mốc ngẫu nhiên cùng cổng giờ và tần suất ('+num(base.n_seeds,0)+' seed): trung bình '+pct(sb.mean*100,0)+', p95 '+pct(sb.p95*100,0)+' &rarr; '+(win?'<span class="pos">vượt p95</span>':'không vượt p95'):'')+'. '
    +esc(w.window&&w.window.length===2?'Cửa sổ '+fmtDate(w.window[0])+' đến '+fmtDate(w.window[1])+'. ':'')+esc('Thật: '+num(w.baskets_real,0)+' rổ, mô phỏng: '+num(w.baskets_sim,0)+' rổ.')+'</p>'
    +table(['Chỉ số','Thật','Mô phỏng','Sai số tương đối','','Mốc ngẫu nhiên đạt (% seed)'],rows)
    +'<p class="tcap">'+esc('Cột cuối: tỷ lệ seed của mốc ngẫu nhiên (vào ngẫu nhiên có cùng cổng giờ, tần suất, luật add và thoát) mà chỉ số này cũng nằm trong ngưỡng. Chỉ số mà ngẫu nhiên cũng đạt gần 100% thì khớp không chứng tỏ playbook đúng.'+(state.p3w==='full'&&p3.insample_note?' '+p3.insample_note+'.':''))+'</p>';
  return h;
}
function pnlSection(b){
  var p3=b.p3;if(!p3||!p3.windows)return '<div class="empty2">Chưa có đường PnL của playbook.</div>';
  var kv='',sec='';
  ['test','full'].forEach(function(k){
    var w=p3.windows[k],base=(p3.base||{})[k]||{};if(!w||!w.daily)return;
    var dl=w.daily,bc=base.daily_corr||{},bs=base.day_sign_agree||{};
    kv+='<div><dt>Tương quan PnL theo ngày, '+(k==='test'?'test':'toàn cửa sổ')+'</dt><dd class="'+(beats(dl.daily_corr,bc.p95)?'pos':'')+'">'+num(dl.daily_corr,2)+(ok(bc.p95)?' <small>p95 ngẫu nhiên '+num(bc.p95,2)+'</small>':'')+'</dd></div>'
      +'<div><dt>Cùng dấu lãi lỗ theo ngày, '+(k==='test'?'test':'toàn cửa sổ')+'</dt><dd>'+pct((dl.day_sign_agree||0)*100,0)+(ok(bs.p95)?' <small>p95 ngẫu nhiên '+pct(bs.p95*100,0)+'</small>':'')+'</dd></div>';
  });
  var wf=p3.windows.full||p3.windows.test;
  var sp=p3.split&&p3.split.split_t;
  return '<div class="chartbox"><div class="clegend" id="p3c-legend"></div><div class="chart eq" id="p3c-chart"></div><div class="cempty" id="p3c-empty" hidden></div></div>'
    +'<p class="tcap">'+esc('PnL thực hiện cộng dồn theo ngày đóng (UTC), toàn cửa sổ của bot'+(sp?'; tập test bắt đầu từ '+fmtDate(sp)+', phần trước đó là dữ liệu train mà tham số được ước lượng':'')+'. Đường thật là PnL USDT từ OKX; đường mô phỏng dùng notional và đòn bẩy trung vị của bot, nên cỡ tuyệt đối chỉ để tham khảo, hình dạng và dấu mới đáng so.')+'</p>'
    +'<dl class="kvg" style="margin-top:10px">'+kv+'</dl>';
}
function overlapSection(b){
  var p3=b.p3;if(!p3||!p3.windows)return '<div class="empty2">Chưa có số liệu trùng lặp.</div>';
  var w=p3.windows[state.p3w]||p3.windows.test||p3.windows.full;if(!w)return '';
  var base=(p3.base||{})[state.p3w]||{},ov=w.overlap||{};
  var tols=[['15','±15 phút'],['60','±60 phút'],['240','±4 giờ']];
  var rows=tols.map(function(t){
    function c(kind,side){var k=kind+'_'+side+'_'+t[0],v=ov[k],bs=(base[k]||{}).p95;return td(pct(v,1),beats(v,bs)?'pos':'')+td(ok(bs)?pct(bs,1):DASH);}
    return '<tr><td>'+t[1]+'</td>'+c('recall','same')+c('recall','any')+c('precision','same')+c('precision','any')+'</tr>';
  });
  return '<p class="sub">'+esc('Cửa sổ '+(state.p3w==='test'?'test':'toàn bộ')+': '+num(ov.n_real,0)+' rổ thật, '+num(ov.n_sim,0)+' rổ mô phỏng. Recall là phần rổ thật có rổ mô phỏng cùng mã mở trong khoảng này; precision là phần rổ mô phỏng có rổ thật tương ứng.')+'</p>'
    +table(['Khoảng lệch giờ mở','Recall cùng chiều','p95 ngẫu nhiên','Recall bất kỳ chiều','p95 ngẫu nhiên','Precision cùng chiều','p95 ngẫu nhiên','Precision bất kỳ chiều','p95 ngẫu nhiên'],rows)
    +'<p class="tcap">'+esc('Mốc ngẫu nhiên: mở rổ ngẫu nhiên trong cùng cổng giờ, cùng tần suất, '+num(base.n_seeds,0)+' seed. Chữ xanh khi vượt p95. Trùng cùng mã trong ±4 giờ dễ xảy ra ngẫu nhiên với bot vào lệnh dày.'+' Trùng mix mã: '+(ok(w.mix)?pct(w.mix*100,0):DASH)+'.')+'</p>';
}
function daySection(b){
  var p3=b.p3;
  if(!p3||!p3.days||!p3.days.length)return '<div class="empty2">Không có ngày nào có cả lệnh thật và lệnh mô phỏng trên cùng một mã để vẽ.</div>';
  return '<div class="toolbar"><label>Ngày và mã <select id="dy-select" data-kind="dy" aria-label="Chọn ngày và mã"></select></label><button type="button" class="btn" data-fit="dy">Xem toàn bộ</button></div>'
    +'<div class="chartbox"><div class="clegend" id="dy-legend"></div><div class="chart px" id="dy-chart"></div><canvas class="ovl" id="dy-ovl" aria-hidden="true"></canvas><div class="cempty" id="dy-empty" hidden></div></div>'
    +legendHtml()+'<p class="chartnote" id="dy-note"></p><div id="dy-events"></div>';
}
function legendHtml(){
  return '<ul class="legend" aria-label="Chú giải ký hiệu">'
    +'<li><svg viewBox="0 0 14 14" aria-hidden="true"><path class="i-long" d="M7 1 L13 12 H1 Z"/></svg>Thật: vào, thêm tầng long</li>'
    +'<li><svg viewBox="0 0 14 14" aria-hidden="true"><path class="i-short" d="M7 13 L13 2 H1 Z"/></svg>Thật: vào, thêm tầng short</li>'
    +'<li><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="i-win" cx="7" cy="7" r="4.5"/></svg>Thật: thoát có lãi</li>'
    +'<li><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="i-loss" cx="7" cy="7" r="4.5"/></svg>Thật: thoát bị lỗ</li>'
    +'<li style="color:var(--long)"><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="lg-sim" cx="7" cy="7" r="4.5"/></svg>Mô phỏng: vào, thêm tầng long</li>'
    +'<li style="color:var(--short)"><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="lg-sim" cx="7" cy="7" r="4.5"/></svg>Mô phỏng: vào, thêm tầng short</li>'
    +'<li style="color:var(--profit)"><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="lg-sim" cx="7" cy="7" r="5"/></svg>Mô phỏng: thoát lãi</li>'
    +'<li style="color:var(--loss)"><svg viewBox="0 0 14 14" aria-hidden="true"><circle class="lg-sim" cx="7" cy="7" r="5"/></svg>Mô phỏng: thoát lỗ</li></ul>';
}

/* ---------- giai đoạn 4: tiệm cận TP/SL với điểm vào thật ---------- */
function genTable(t){
  if(!t||!t.rows||!t.rows.length)return '';
  var head=t.cols.map(function(c){return c;});
  var rows=t.rows.map(function(r){return '<tr>'+r.map(function(v,i){
    var s=typeof v==='number'?num(v,Math.abs(v)<10&&v%1?3:(v%1?1:0)):(v==null?DASH:(typeof v==='boolean'?(v?'có':'không'):String(v)));
    return i===0?'<td style="text-align:left;white-space:normal">'+esc(pm(s))+'</td>':'<td class="num" style="white-space:normal;text-align:left;min-width:8ch">'+esc(pm(s))+'</td>';}).join('')+'</tr>';});
  return table(head,rows);
}
function implSection(b){
  var p=b.p4;
  if(!p)return '<div class="empty2">Chưa có kết quả tiệm cận TP/SL cho bot này (không có out/implied_'+esc(b.slug)+'.json). Khi giai đoạn 4 chạy xong, chạy lại build_report.py.</div>';
  var h='<p class="cmpnote" style="margin-top:0"><b>Phép khớp trong mẫu (in-sample).</b> '+esc('Mọi fill vào và thêm tầng được phát lại đúng như thật; chỉ luật thoát (chốt lời, cắt lỗ, trailing, hoà vốn, giới hạn thời gian) là giả định, được chỉnh để gần nhất với các điểm thoát thật trên toàn bộ dữ liệu. Đây là mô tả, không phải dự báo, và không có tập test.')+'</p>';
  h+='<div class="verdict-line" style="margin-top:10px">'+(p.label?vchip(p.cls,p.label):'<span class="sub">Chưa có nhãn kết luận</span>')+'</div>';
  if(p.text)h+='<h4>Luật thoát tốt nhất</h4>'+String(p.text).split(/\n+/).map(function(t){return '<p>'+esc(pm(t))+'</p>';}).join('');
  if(p.params&&p.params.length)h+='<details class="dd"><summary>Tham số của luật ('+p.params.length+')</summary><dl class="kvg">'+p.params.map(function(x){return '<div><dt>'+esc(x[0])+'</dt><dd>'+esc(typeof x[1]==='number'?num(x[1],x[1]%1?3:0):String(x[1]))+'</dd></div>';}).join('')+'</dl></details>';
  if(p.formulas){h+='<h4>Công thức mức chốt, cắt lỗ, trailing (hệ số và độ lệch dư)</h4>'+genTable(p.formulas);}
  if(p.class_mix&&p.class_mix.length)h+='<h4>Cơ cấu kiểu thoát thật</h4>'+table(['Kiểu thoát','Tỷ lệ'],p.class_mix.map(function(r){return '<tr><td>'+esc(String(r[0]))+'</td>'+td(ok(r[1])?(r[1]<=1&&r[1]>0?pct(r[1]*100,1):num(r[1],r[1]%1?1:0)):DASH)+'</tr>';}))+'<p class="tcap">Phân loại: chốt limit, trailing hoặc hồi từ đỉnh, cắt lỗ sát đáy, hoà vốn, khác (tay, thời gian, không giải thích được).</p>';
  if(p.metrics&&p.metrics.length){
    var hasN=p.metrics.some(function(r){return ok(r.null);}),hasS=p.metrics.some(function(r){return ok(r.shuf_p95);});
    var head=['Chỉ số','Luật tiệm cận'];if(hasN)head.push('Mốc rỗng (time-stop)');if(hasS)head.push('TP ngẫu nhiên: trung bình','TP ngẫu nhiên: p95');
    var rows=p.metrics.map(function(r){
      var lower=r.unit==='bps',d=r.unit==='r'?2:1,win=!lower&&ok(r.shuf_p95)&&r.sim>r.shuf_p95||(lower&&ok(r.shuf_p95)&&r.sim<r.shuf_p95);
      return '<tr><td>'+esc(r.label)+'</td>'+td(fv(r.unit==='bps'?'h':r.unit,r.sim,d),win?'pos':'')+(hasN?td(ok(r.null)?fv(r.unit==='bps'?'h':r.unit,r.null,d):DASH):'')+(hasS?td(ok(r.shuf_mean)?fv(r.unit==='bps'?'h':r.unit,r.shuf_mean,d):DASH)+td(ok(r.shuf_p95)?fv(r.unit==='bps'?'h':r.unit,r.shuf_p95,d):DASH):'')+'</tr>';});
    h+='<h4>Độ gần của điểm thoát mô phỏng với điểm thoát thật</h4>'+table(head,rows)+'<p class="tcap">'+esc('Chữ xanh: tốt hơn p95 của mốc TP ngẫu nhiên rút từ chính phân phối của bot (sai số giá: nhỏ hơn). Vì luật được chỉnh trên chính dữ liệu này, mọi chỉ số đều lạc quan so với dự báo ngoài mẫu.')+'</p>';
  }
  if(p.pnl&&(ok(p.pnl.real)||ok(p.pnl.sim)))h+='<dl class="kvg" style="margin-top:12px"><div><dt>PnL thực hiện thật (USDT)</dt><dd>'+num(p.pnl.real,0)+'</dd></div><div><dt>PnL thực hiện mô phỏng (USDT)</dt><dd>'+num(p.pnl.sim,0)+'</dd></div>'+(ok(p.pnl.real)&&p.pnl.real&&ok(p.pnl.sim)?'<div><dt>Sai số tương đối</dt><dd>'+sgn((p.pnl.sim-p.pnl.real)/Math.abs(p.pnl.real)*100,0)+'%</dd></div>':'')+(p.n_sim?'<div><dt>Số lệnh con mô phỏng</dt><dd>'+num(p.n_sim,0)+'</dd></div>':'')+'</dl>';
  if(p.cum&&p.cum.length)h+='<h4>PnL thực hiện cộng dồn: thật và mô phỏng</h4><div class="chartbox"><div class="clegend" id="i4-legend"></div><div class="chart eq" id="i4-chart"></div><div class="cempty" id="i4-empty" hidden></div></div>';
  if(p.report&&p.report.length){
    var rr=p.report.map(function(r){var m=LS_META[r.k]||[r.k,2];return '<tr><td>'+esc(m[0])+'</td>'+td(num(r.real,m[1]))+td(num(r.sim,m[1]))+td(ok(r.rel)?sgn(r.rel*100,0)+'%':DASH)+'<td class="r">'+(r.ok==null?'':(r.ok?'<span class="pill yes">trong ngưỡng</span>':'<span class="pill no">lệch</span>'))+'</td></tr>';});
    h+='<h4>Chỉ số theo cách OKX báo cáo: thật và mô phỏng (cùng điểm vào thật)</h4>'+table(['Chỉ số','Thật','Mô phỏng','Sai số tương đối',''],rr);
  }
  if(p.ablation)h+='<h4>Đóng góp từng thành phần (ablation)</h4>'+genTable(p.ablation)+'<p class="tcap">Mỗi dòng thêm một thành phần vào luật thoát: chỉ TP, cộng cắt lỗ, cộng trailing, cộng hoà vốn, cộng tách theo chế độ thị trường.</p>';
  if(p.regimes){
    var rg=p.regimes,h2='';
    if(rg.method)h2+='<p class="sub">Cách tách chế độ: '+esc(pm(String(rg.method)))+'.</p>';
    if(Array.isArray(rg.segments)&&rg.segments.length&&typeof rg.segments[0]==='object')h2+=genTable({cols:Object.keys(rg.segments[0]).slice(0,9),rows:rg.segments.slice(0,40).map(function(s){return Object.keys(rg.segments[0]).slice(0,9).map(function(k){var v=s[k];return (v!==null&&typeof v==='object')?JSON.stringify(v).slice(0,120):v;});})});
    var gains=['gain','gain_pp','improvement','delta'].map(function(k){return rg[k];}).filter(function(v){return v!=null;});
    if(gains.length)h2+='<p class="sub">Mức cải thiện khi tách chế độ: '+esc(typeof gains[0]==='number'?num(gains[0],2):JSON.stringify(gains[0]).slice(0,200))+'.</p>';
    if(h2)h+='<h4>Thay đổi theo chế độ thị trường</h4>'+h2;
  }
  if(p.top5)h+='<details class="dd"><summary>Các luật thay thế gần nhất</summary>'+genTable(p.top5)+'</details>';
  if(p.baskets&&p.baskets.length)h+='<h4>Rổ đại diện trên nến: thoát thật và thoát mô phỏng</h4><div class="toolbar"><label>Rổ <select id="ib-select" data-kind="ib" aria-label="Chọn rổ"></select></label><button type="button" class="btn" data-fit="ib">Xem toàn bộ</button></div>'
    +'<div class="chartbox"><div class="clegend" id="ib-legend"></div><div class="chart px" id="ib-chart"></div><canvas class="ovl" id="ib-ovl" aria-hidden="true"></canvas><div class="cempty" id="ib-empty" hidden></div></div>'+legendHtml()+'<p class="chartnote" id="ib-note"></p><div id="ib-events"></div>';
  if(p.why)h+='<details class="dd" open><summary>Chi tiết kết luận</summary><p>'+esc(pm(p.why))+'</p><p class="tcap">Kết luận này là trong mẫu: luật được chọn trên chính các thoát cần giải thích.</p></details>';
  return h;
}
function initI4(b){
  var el=$('i4-chart');if(!el)return;
  if(!HAS_LW){showEmpty('i4-empty','Không tải được thư viện biểu đồ.');return;}
  var cv=b.p4.cum;if(!cv||cv.length<2){showEmpty('i4-empty','Không có đường cộng dồn.');return;}
  var ch=LightweightCharts.createChart(el,baseOpts({}));
  var a=ch.addLineSeries({color:COL.accent,lineWidth:2,priceLineVisible:false});
  var s=ch.addLineSeries({color:COL.short,lineWidth:2,lineStyle:2,priceLineVisible:false});
  a.setData(monotone(cumPts(cv,1,null)));s.setData(monotone(cumPts(cv,2,null)));
  $('i4-legend').innerHTML='<span class="sw2" style="color:'+COL.accent+'"></span>Thật <span class="sw2 dash" style="color:'+COL.short+';margin-left:10px"></span>Thoát mô phỏng, điểm vào thật <span class="muted" style="margin-left:10px">USDT, giờ VN</span>';
  ch.timeScale().fitContent();state.charts.i4={chart:ch};
}

function evidenceList(b){
  var e=b.p1.evidence||[];
  if(!e.length)return '<p class="sub">Chưa có bằng chứng định lượng cho bot này.</p>';
  return '<ul class="bl">'+e.map(function(t){return '<li>'+esc(pm(t))+'</li>';}).join('')+'</ul>';
}
function rulesSection(b){
  var p=b.p1,h='';
  h+=String(p.rules||'Không có luật nào vượt được mốc rỗng.').split(' | ').map(function(t){return '<p>'+esc(pm(t))+'</p>';}).join('');
  if(p.model)h+='<p class="sub" style="margin-top:6px">Họ luật được chọn theo train: <span class="code">'+esc(p.model)+'</span>'+(p.exit_only?'; luật thoát tốt nhất khi giữ nguyên fill thật: <span class="code">'+esc(p.exit_only.model)+'</span> ('+esc(pm(p.exit_only.rules||''))+')':'')+'.</p>';
  if(p.params&&p.params.length)h+='<details class="dd"><summary>Tham số của mô hình ('+p.params.length+')</summary><dl class="kvg">'+p.params.map(function(kv){return '<div><dt>'+esc(kv[0])+'</dt><dd>'+esc(typeof kv[1]==='number'?num(kv[1],kv[1]%1?3:0):kv[1])+'</dd></div>';}).join('')+'</dl></details>';
  return h;
}
function p1Match(b){
  var p=b.p1,h='';
  var pr=p.periods||{};
  h+='<p class="splitnote">'+esc('Chia theo thời gian: train '+(pr.train&&pr.train.length?fmtDate(pr.train[0])+' đến '+fmtDate(pr.train[1]):DASH)+' ('+num(p.ov.n_train,0)+' '+p.ov.unit+'), test '+(pr.test&&pr.test.length?fmtDate(pr.test[0])+' đến '+fmtDate(pr.test[1]):DASH)+' ('+num(p.ov.n_test,0)+' '+p.ov.unit+').'+(p.big?' Một rổ có thể gồm nhiều unit (tranche và lệnh đóng của nó); '+num(p.ov.n_baskets_big,0)+' rổ.':''))+'</p>';
  p.blocks.forEach(function(bk){if(bk.rows&&bk.rows.length)h+=blockTable(bk);});
  h+=levelBTable(p.levelB);
  h+=extraTable(p.extra);
  if(p.sim_note)h+='<p class="tcap">'+esc('Cách mô phỏng: '+p.sim_note)+'</p>';
  if(p.iterations&&p.iterations.length){
    h+='<details class="dd"><summary>Các họ luật đã thử ở giai đoạn 1 ('+p.iterations.length+')</summary>'+table(['Họ luật','Train: thoát ±15p','Test: thoát ±15p','Kiểu'],p.iterations.map(function(r){return '<tr><td><span class="code">'+esc(r[0])+'</span></td>'+td(pct(r[1],1))+td(pct(r[2],1))+'<td class="r">'+esc(r[3]||'')+'</td></tr>';}))+'<p class="tcap">Chọn họ luật theo train; cột test chỉ để báo cáo. Nhiều họ luật được thử nên điểm test tốt nhất có thể do may mắn.</p></details>';
  }
  return h;
}
function p2Match(b){
  var h='';
  if(b.p2){
    h+=p2LevelA(b.p2)+p2Panels(b.p2)+levelS(b);
    if(b.p2.iterations&&b.p2.iterations.length)h+='<details class="dd"><summary>Các vòng lặp giai đoạn 2 ('+b.p2.iterations.length+')</summary>'+table(['Vòng','Thay đổi','Mô hình chọn','Train ±15p','Test ±15p','AUC GBM test'],b.p2.iterations.map(function(it){return '<tr><td>'+esc(it.name||it.i)+'</td><td style="text-align:left;white-space:normal">'+esc(pm(it.change||''))+'</td>'+td('<span class="code">'+esc(it.best||'')+'</span>')+td(pct(it.tr,1))+td(pct(it.te,1))+td(ok(it.auc)?num(it.auc,3):DASH)+'</tr>';}))+'</details>';
  }else{
    h+='<div class="empty2">Giai đoạn 2 chưa có kết quả cho bot này (không có out/disc_'+esc(b.slug)+'.json). Khi run_disc.py chạy xong, chạy lại build_report.py: các bảng AUC, cơ chế, Level A và Level S sẽ hiện ở đây.</div>';
  }
  return h;
}
function factsOf(o,tag){
  var f=[];
  if(ok(o.exit15))f.push('Thoát ±15 phút ở tập test: '+pct(o.exit15,1)+(ok(o.exit_p95)?(beats(o.exit15,o.exit_p95)?', vượt':', không vượt')+' mốc ngẫu nhiên p95 '+pct(o.exit_p95,1):'')+(o.exit_alt&&ok(o.exit_alt.val)&&tag==='p1'?'; '+o.exit_alt.label+' '+pct(o.exit_alt.val,1):'')+(ok(o.n_test)?' (test '+num(o.n_test,0)+' '+o.unit+')':'')+'.');
  if(ok(o.entry))f.push('Vào lệnh ±15 phút: recall '+pct(o.entry,1)+(ok(o.entry_p95)?(beats(o.entry,o.entry_p95)?', vượt':', không vượt')+' mốc khớp giờ p95 '+pct(o.entry_p95,1):'')+'.');
  if(ok(o.add))f.push('Add khớp giờ và giá: '+pct(o.add,1)+(o.add_note?' ('+o.add_note+')':'')+'.');
  if(ok(o.pnl_corr))f.push('Tương quan lợi suất mỗi rổ '+num(o.pnl_corr,2)+(ok(o.pnl_corr_p95)?' so với p95 ngẫu nhiên '+num(o.pnl_corr_p95,2):'')+'.');
  return f;
}
function ulist(f){return f.length?'<ul class="bl" style="margin-top:6px">'+f.map(function(t){return '<li>'+esc(t)+'</li>';}).join('')+'</ul>':'';}
function p1Why(b){
  var v=b.p1.verdict,h='';
  h+='<div class="verdict-line">'+vchip(v.cls)+'<span class="sub">Kết luận giai đoạn 1</span></div>';
  h+=(cap1(pm(v.label))!==VLAB[v.cls]?'<p style="margin-top:8px"><b>'+esc(cap1(pm(v.label)))+'</b></p>':'')+ulist(factsOf(b.p1.ov,'p1'));
  if(v.why)h+='<details class="dd"><summary>Chi tiết kết luận giai đoạn 1</summary><p>'+esc(pm(v.why))+'</p>'+(v.exit?'<p><b>Thoát:</b> '+esc(pm(v.exit))+'. <b>Vào mới:</b> '+esc(pm(v.entry_first_tight||DASH))+'.</p>':'')+(v.caveat?'<p class="sub">'+esc(pm(v.caveat))+'</p>':'')+(v.highlights&&v.highlights.length?'<p class="sub" style="margin-top:8px">Thành phần vững qua LOO và walk-forward:</p><ul class="bl">'+v.highlights.map(function(t){return '<li>'+esc(pm(t))+'</li>';}).join('')+'</ul>':'')+(v.criteria?'<p class="tcap">Tiêu chí: '+esc(pm(v.criteria))+'</p>':'')+'</details>';
  return h;
}
function p2Why(b){
  var v2=b.p2,h='';if(!v2)return '';
  var f2=factsOf(b.ov,'p2');
  if(ok(b.ov.s_score))f2.push('Level S: '+pct(b.ov.s_score*100,0)+' trong 12 chỉ số lõi khớp trong ±20%.');
  h+='<div class="verdict-line">'+vchip(v2.cls)+'<span class="sub">Kết luận giai đoạn 2</span></div>'+ulist(f2);
  if(v2.why)h+='<details class="dd"><summary>Chi tiết kết luận giai đoạn 2</summary><p>'+esc(pm(v2.why))+'</p></details>';
  else if(v2.numbers){var n=v2.numbers;h+='<details class="dd"><summary>Chi tiết kết luận giai đoạn 2</summary><ul class="bl"><li>'+esc('Thoát ±15 phút '+pct(n.exit15,1)+' (khoảng tin cậy 95%: '+pct(n.exit15_ci95&&n.exit15_ci95[0],1)+' đến '+pct(n.exit15_ci95&&n.exit15_ci95[1],1)+') so với mốc ngẫu nhiên p95 '+pct(n.baseline_exit15_p95,1)+'.')+'</li><li>'+esc('Add khớp '+pct(n.add_match,1)+' so với mốc '+pct(n.add_baseline,1)+'; tương quan PnL '+num(n.pnl_corr,2)+' so với p95 ngẫu nhiên '+num(n.baseline_pnl_corr_p95,2)+'.')+'</li></ul>'+(v2.passes?'<p class="sub">Điều kiện: thoát ≥ 60% và vượt mốc: '+(v2.passes.exit15_ge60_and_beats_baseline?'đạt':'không đạt')+'; add ≥ 50% và vượt mốc: '+(v2.passes.add_ge50_and_beats_baseline?'đạt':'không đạt')+'; tương quan PnL ≥ 0,7 và vượt mốc: '+(v2.passes.pnl_corr_ge07_and_beats_baseline?'đạt':'không đạt')+'.</p>':'')+'</details>';}
  return h;
}
function conclusion(b){
  var ck=p3checks(b),h='',v=b.p1.verdict,v2=b.p2;
  if(ck){
    var o=b.ov3,P=b.p3;
    h+='<p><b>Playbook (giai đoạn 3) vượt mốc ngẫu nhiên p95 ở '+ck.n+'/3 phép đo trên tập test.</b></p><ul class="bl" style="margin-top:6px">'
      +ck.list.map(function(c){return '<li>'+esc(c.label+': '+c.f(c.v)+(ok(c.base)?(c.pass?', vượt':', không vượt')+' p95 ngẫu nhiên '+c.f(c.base):'')+'.')+'</li>';}).join('')+'</ul>';
    var okN=(o.ok_test||[]).map(lsName),offN=(o.off_test||[]).map(lsName);
    h+='<p class="sub" style="margin-top:8px">'+esc('Chỉ số thống kê khớp ở tập test: '+(okN.length?okN.join(', '):'không có')+'. Lệch: '+(offN.length?offN.join(', '):'không có')+'.')+'</p>';
    h+='<p class="sub" style="margin-top:6px">'+esc('Toàn bộ cửa sổ (60% đầu là trong mẫu): điểm khớp '+pct((o.s_full||0)*100,0)+(ok(o.s_full_p95)?' so với p95 ngẫu nhiên '+pct(o.s_full_p95*100,0):'')+'; trùng rổ ±60 phút '+pct(o.rec60_full,1)+(ok(o.rec60_full_p95)?' so với '+pct(o.rec60_full_p95,1):'')+'.')+'</p>';
    if(ok(b.ov.n_test)&&b.ov.n_test<20)h+='<p class="sub" style="margin-top:6px">'+esc('Tập test chỉ có '+num(b.ov.n_test,0)+' '+b.ov.unit+', nên các mốc p95 rất thô và kết quả chỉ mang tính bác bỏ.')+'</p>';
    if(P&&P.info&&ok(P.info.n_hold_gt8h)&&P.info.n_hold_gt8h>0)h+='<p class="tcap">'+esc('Có '+num(P.info.n_hold_gt8h,0)+' rổ mô phỏng giữ trên 8 giờ; funding không được áp dụng (không có dữ liệu funding).')+'</p>';
  }else h+='<p class="sub">Chưa có playbook cho bot này.</p>';
  h+='<p style="margin-top:14px"><b>Các cách đã thử trước</b>, xem phần cuối ngăn này:</p><div class="verdict-line">'+vchip(v.cls)+'<span class="sub">Giai đoạn 1</span>'+(v2?vchip(v2.cls)+'<span class="sub">Giai đoạn 2</span>':'')+'</div>';
  return h;
}
function triedSummary1(b){
  var o=b.p1.ov,s=[];
  if(ok(o.exit15))s.push('thoát ±15 phút '+pct(o.exit15,1)+(ok(o.exit_p95)?' (p95 ngẫu nhiên '+pct(o.exit_p95,1)+')':''));
  if(ok(o.entry))s.push('recall vào lệnh '+pct(o.entry,1));
  if(ok(o.add))s.push('add khớp '+pct(o.add,1));
  return s.join('; ');
}
function triedSummary2(b){
  var s=[];
  if(!b.p2)return 'chưa có kết quả';
  var ex=b.p2.panels&&b.p2.panels.exit;
  if(ex&&ok(ex.auc))s.push('AUC thoát '+num(ex.auc,2));
  if(ok(b.ov.s_score))s.push('Level S '+pct(b.ov.s_score*100,0));
  if(ok(b.ov.exit15))s.push('thoát ±15 phút '+pct(b.ov.exit15,1));
  return s.join('; ');
}
function okxHtml(b){
  return '<div class="prose">'
    +(b.okx.how?'<div class="how"><h4>Cách chơi</h4><p>'+esc(b.okx.how)+'</p></div>':'')
    +(b.okx.edge?'<div class="edge"><h4>Vì sao thắng</h4><p>'+esc(b.okx.edge)+'</p></div>':'')
    +(b.okx.risk?'<div class="risk"><h4>Rủi ro</h4><p>'+esc(b.okx.risk)+'</p></div>':'')+'</div>';
}
function sec(id,title,body){return '<section class="dsec" aria-labelledby="'+id+'"><h3 id="'+id+'">'+esc(title)+'</h3>'+body+'</section>';}
function bxHtml(b){
  if(!b.baskets.length)return '<div class="empty2">Không có rổ đại diện nào có nến để vẽ cho bot này.</div>';
  return '<div class="toolbar"><label>Rổ đại diện <select id="bx-select" data-kind="bx" aria-label="Chọn rổ đại diện"></select></label><button type="button" class="btn" data-fit="bx">Xem toàn bộ</button></div>'
    +'<div class="chartbox"><div class="clegend" id="bx-legend"></div><div class="chart px" id="bx-chart"></div><canvas class="ovl" id="bx-ovl" aria-hidden="true"></canvas><div class="cempty" id="bx-empty" hidden></div></div>'
    +legendHtml()+'<p class="chartnote" id="bx-note"></p><div id="bx-events"></div>';
}
function tried(b){
  var oi=state.openIds,o1=oi['d-p1'],o2=oi['d-p2'];
  if(o1==null)o1=!b.p3;
  var h='<details class="dd2" id="d-p1"'+(o1?' open':'')+'><summary><b>Giai đoạn 1: luật viết tay, tìm trên lưới</b><span class="sm">'+esc(triedSummary1(b))+'</span></summary><div class="dbody">'
    +'<h4>Giả thuyết</h4><p>'+esc(pm(b.p1.hypothesis||DASH))+'</p>'
    +'<h4>Bằng chứng từ dữ liệu</h4>'+evidenceList(b)
    +'<h4>Quy tắc mô phỏng tốt nhất</h4>'+rulesSection(b)
    +'<h4>Kết quả khớp</h4>'+p1Match(b)
    +'<h4>So sánh trên nến: các rổ đại diện</h4>'+bxHtml(b)
    +'<h4>PnL cộng dồn trên tập test: thật và mô phỏng</h4><div class="chartbox"><div class="clegend" id="eq-legend"></div><div class="chart eq" id="eq-chart"></div><div class="cempty" id="eq-empty" hidden></div></div>'
    +'<p class="tcap">'+esc('Mỗi điểm là một rổ đóng, theo giờ đóng thật. Đường mô phỏng dùng fill đầu thật rồi chạy luật mô phỏng nên không so được tuyệt đối về độ lớn.')+'</p>'
    +p1Why(b)+'</div></details>';
  h+='<details class="dd2" id="d-p2"'+(o2?' open':'')+'><summary><b>Giai đoạn 2: học cơ chế từ điểm quyết định</b><span class="sm">'+esc(triedSummary2(b))+'</span></summary><div class="dbody">'+p2Match(b)+p2Why(b)+'</div></details>';
  return h;
}
function renderDrawer(i){
  var b=BOTS[i],f=b.facts,o=b.ov;
  $('d-rank').textContent='Hạng OKX '+b.rank;
  $('d-name').textContent=b.name;
  $('d-chip').innerHTML=chip(b.style,b.styleKey);
  $('d-pos').textContent=(i+1)+' / '+BOTS.length;
  $('d-meta').innerHTML=(b.url?'<a href="'+esc(b.url)+'" target="_blank" rel="noopener noreferrer">Trang OKX</a>':'')
    +'<span>Lead '+num(f.leadDays,0)+' ngày</span><span>'+num(f.copiers,0)+' người copy</span><span>Dữ liệu lệnh từ '+fmtDate(f.first)+' đến '+fmtDate(f.last)+'</span>';
  var ck=p3checks(b);
  $('d-kpi').innerHTML=kpi('PnL 90 ngày (USDT, OKX)','<span class="'+cls(f.pnl90)+'">'+num(f.pnl90,0)+'</span>')
    +kpi('ROI 90 ngày (OKX)',pct(f.roi90,1))
    +kpi('Lệnh con đã đóng',num(f.n,0))
    +kpi('Đòn bẩy, giữ lệnh TV',(ok(f.levMed)?num(f.levMed,0)+'x':DASH)+' <small>'+(ok(f.holdMed)?num(f.holdMed,1)+' giờ':'')+'</small>')
    +kpi('Playbook vượt p95 ngẫu nhiên',ck?ck.n+'/3 <small>phép đo, test</small>':DASH)
    +(b.ov4&&ok(b.ov4.exit15)?kpi('Thoát ±15 phút, TP/SL tiệm cận',pct(b.ov4.exit15,1)+' <small>trong mẫu</small>'):'');
  var sc=[];
  if(b.p4||META.n_p4>0)sc.push(sec('s-impl','Tiệm cận TP/SL với điểm vào thật',implSection(b)));
  sc.push(sec('s-play','Playbook tự chạy: cách bot đánh dựng lại từ lệnh thật',playSection(b)));
  sc.push(sec('s-ls','Backtest tự chạy so với bot thật (Level S)',lsSection(b)));
  sc.push(sec('s-pnl','PnL thực hiện cộng dồn và PnL theo ngày',pnlSection(b)));
  sc.push(sec('s-ov','Trùng thời điểm vào rổ so với ngẫu nhiên',overlapSection(b)));
  sc.push(sec('s-day','Một ngày trên nến: lệnh thật và lệnh mô phỏng',daySection(b)));
  sc.push(sec('s-kl','Kết luận',conclusion(b)));
  sc.push(sec('s-okx','Mô tả của OKX, nguồn của giả thuyết',okxHtml(b)));
  sc.push(sec('s-tried','Các cách đã thử trước',tried(b)));
  $('d-body').innerHTML=sc.join('');
}

/* ---------- biểu đồ ---------- */
var COL={};
function readColors(){
  var cs=getComputedStyle(document.documentElement);
  function g(n){return cs.getPropertyValue(n).trim();}
  COL={surface:g('--surface'),text:g('--text-2'),text3:g('--text-3'),grid:g('--grid'),line:g('--line-strong'),accent:g('--accent'),up:g('--candle-up'),down:g('--candle-down'),
    profit:g('--profit'),loss:g('--loss'),long:g('--long'),short:g('--short'),swing:g('--st-swing'),cross:g('--text-3'),crossLabel:g('--cross-label'),font:getComputedStyle(document.body).fontFamily};
}
function baseOpts(extra){
  var CT=LightweightCharts.ColorType;
  var o={layout:{background:{type:CT?CT.Solid:'solid',color:COL.surface},textColor:COL.text,fontFamily:COL.font,fontSize:12},
    grid:{vertLines:{color:COL.grid},horzLines:{color:COL.grid}},
    rightPriceScale:{borderColor:COL.line,scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:COL.line,timeVisible:true,secondsVisible:false,rightOffset:2},
    crosshair:{vertLine:{color:COL.cross,labelBackgroundColor:COL.crossLabel},horzLine:{color:COL.cross,labelBackgroundColor:COL.crossLabel}},
    localization:{priceFormatter:function(v){return price(v);}},
    handleScale:{axisPressedMouseMove:true},autoSize:true};
  if(extra)for(var k in extra)o[k]=extra[k];
  return o;
}
function disposeCharts(){
  ['dy','bx','ib','eq','ls','p3c','i4'].forEach(function(k){var c=state.charts[k];if(c&&c.chart){try{c.chart.remove();}catch(e){}}state.charts[k]=null;});
  if(state.raf){cancelAnimationFrame(state.raf);state.raf=0;}
}
function showEmpty(id,msg){var e=$(id);if(e){e.textContent=msg;e.hidden=false;}}
var SHIFT=25200; /* hiển thị giờ Việt Nam: lùi trục UTC của thư viện 7 giờ */
function monotone(arr){var out=[],prev=-1;arr.forEach(function(p){var t=p[0];if(t<=prev)t=prev+1;prev=t;out.push({time:t,value:p[1]});});return out;}

function cumPts(cv,idx,split){
  var pts=cv.filter(function(p){return ok(p[idx]);}).map(function(p){return [Math.floor(p[0]/1000)+SHIFT,p[idx]];});
  if(split&&cv.length&&cv[0][0]>split)pts.unshift([Math.floor(split/1000)+SHIFT,0]);
  return pts;
}
function initEq(b){
  var el=$('eq-chart');if(!el)return;
  if(!HAS_LW){showEmpty('eq-empty','Không tải được thư viện biểu đồ.');return;}
  var cv=(b.p1.cum&&b.p1.cum.test)||[];
  if(cv.length<1){showEmpty('eq-empty','Không có đường cộng dồn cho bot này.');return;}
  var split=b.p1.periods&&b.p1.periods.split_t;
  var ch=LightweightCharts.createChart(el,baseOpts({}));
  var sr=ch.addLineSeries({color:COL.accent,lineWidth:2,priceLineVisible:false,lastValueVisible:true});
  sr.setData(monotone(cumPts(cv,1,split)));
  var ss=ch.addLineSeries({color:COL.short,lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:true});
  ss.setData(monotone(cumPts(cv,2,split)));
  var leg='<span class="sw2" style="color:'+COL.accent+'"></span>Thật <span class="sw2 dash" style="color:'+COL.short+';margin-left:10px"></span>Mô phỏng giai đoạn 1';
  if(b.p2&&b.p2.cum&&b.p2.cum.length){
    var s3=ch.addLineSeries({color:COL.swing,lineWidth:2,lineStyle:1,priceLineVisible:false,lastValueVisible:true});
    s3.setData(monotone(cumPts(b.p2.cum,2,split)));
    leg+=' <span class="sw2 dash" style="color:'+COL.swing+';margin-left:10px"></span>Mô phỏng giai đoạn 2';
  }
  $('eq-legend').innerHTML=leg+' <span class="muted" style="margin-left:10px">USDT, giờ VN</span>';
  ch.timeScale().fitContent();
  state.charts.eq={chart:ch};
}
function initLs(b){
  var el=$('ls-chart');if(!el)return;
  if(!HAS_LW){showEmpty('ls-empty','Không tải được thư viện biểu đồ.');return;}
  var w=b.p2&&b.p2.level_s&&b.p2.level_s.windows[state.lsw];
  var dl=w&&w.daily;
  if(!dl||!dl.days||!dl.days.length){showEmpty('ls-empty','Không có chuỗi theo ngày.');return;}
  var ch=LightweightCharts.createChart(el,baseOpts({timeScale:{borderColor:COL.line,timeVisible:false,rightOffset:1}}));
  var a=ch.addLineSeries({color:COL.accent,lineWidth:2,priceLineVisible:false});
  var s=ch.addLineSeries({color:COL.short,lineWidth:2,lineStyle:2,priceLineVisible:false});
  a.setData(dl.days.map(function(d,i){return {time:d*86400,value:dl.real_cum[i]};}));
  s.setData(dl.days.map(function(d,i){return {time:d*86400,value:dl.sim_cum[i]};}));
  $('ls-legend').innerHTML='<span class="sw2" style="color:'+COL.accent+'"></span>Thật <span class="sw2 dash" style="color:'+COL.short+';margin-left:10px"></span>Mô phỏng Level S <span class="muted" style="margin-left:10px">USDT, ngày UTC</span>';
  ch.timeScale().fitContent();
  state.charts.ls={chart:ch};
}

/* biểu đồ nến + lớp phủ canvas (mũi tên đặc = thật, vòng rỗng = mô phỏng) */
function pxList(b,kind){return kind==='dy'?((b.p3&&b.p3.days)||[]):(kind==='ib'?((b.p4&&b.p4.baskets)||[]):b.baskets);}
function fillSelect(b,kind){
  var sel=$(kind+'-select');if(!sel)return;
  var list=pxList(b,kind),h='';
  if(kind==='dy'){
    h=list.map(function(k,idx){return '<option value="'+idx+'">'+esc(k.tag+': '+k.n_real+' thật, '+k.n_sim+' mô phỏng')+'</option>';}).join('');
  }else{
    var g1=[],g2=[];
    list.forEach(function(k,idx){
      var lab=k.tag+': '+k.sym+' '+(k.side==='long'?'long':'short')+' '+(k.split==='test'?'(test)':'(train)')+' '+fmtVN(k.t0);
      (k.src==='p2'?g2:g1).push('<option value="'+idx+'">'+esc(lab)+'</option>');
    });
    if(g1.length)h+=(g2.length?'<optgroup label="Mô phỏng giai đoạn 1 (luật viết tay)">':'')+g1.join('')+(g2.length?'</optgroup>':'');
    if(g2.length)h+='<optgroup label="Mô phỏng giai đoạn 2 (học từ dữ liệu)">'+g2.join('')+'</optgroup>';
  }
  sel.innerHTML=h;sel.value=String(state.sel[kind]||0);
}
function snapTime(times,t){
  var s=Math.floor(t/1000),lo=0,hi=times.length-1,r=0;
  if(s<times[0])return times[0]+SHIFT;
  while(lo<=hi){var m=(lo+hi)>>1;if(times[m]<=s){r=m;lo=m+1;}else hi=m-1;}
  return times[r]+SHIFT;
}
function drawOverlay(kind){
  var c=state.charts[kind];if(!c||!c.chart)return;
  var cv=$(kind+'-ovl');if(!cv)return;
  var box=cv.parentNode,w=box.clientWidth,h=box.clientHeight,dpr=window.devicePixelRatio||1;
  if(cv.width!==Math.round(w*dpr)||cv.height!==Math.round(h*dpr)){cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);}
  var x=cv.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,w,h);
  var k=c.k,ts=c.chart.timeScale(),ser=c.series,times=c.times;
  function pos(e){var tx=ts.timeToCoordinate(snapTime(times,e.t)),ty=ser.priceToCoordinate(e.px);if(tx==null||ty==null||tx<0||tx>w)return null;return [tx,ty];}
  function tri(p,up,col,sz){x.beginPath();if(up){x.moveTo(p[0],p[1]);x.lineTo(p[0]-sz*0.62,p[1]+sz);x.lineTo(p[0]+sz*0.62,p[1]+sz);}else{x.moveTo(p[0],p[1]);x.lineTo(p[0]-sz*0.62,p[1]-sz);x.lineTo(p[0]+sz*0.62,p[1]-sz);}x.closePath();x.fillStyle=col;x.fill();x.lineWidth=1;x.strokeStyle=COL.surface;x.stroke();}
  function side(e){return e.s||k.side;}
  k.sim.forEach(function(e){
    var p=pos(e);if(!p)return;
    x.beginPath();
    if(e.k==='out'){x.arc(p[0],p[1],6.5,0,6.2832);x.lineWidth=2;x.strokeStyle=e.w?COL.profit:COL.loss;x.setLineDash(e.open?[3,2.5]:[]);x.stroke();x.setLineDash([]);}
    else{x.arc(p[0],p[1],4.5,0,6.2832);x.lineWidth=1.8;x.strokeStyle=side(e)==='long'?COL.long:COL.short;x.stroke();}
  });
  k.real.forEach(function(e){
    var p=pos(e);if(!p)return;
    if(e.k==='out'){x.beginPath();x.arc(p[0],p[1],4,0,6.2832);x.fillStyle=e.w?COL.profit:COL.loss;x.fill();x.lineWidth=1;x.strokeStyle=COL.surface;x.stroke();}
    else tri(p,side(e)==='long',side(e)==='long'?COL.long:COL.short,e.k==='in'&&k.src!=='p3'?10:8);
  });
}
function overlayLoop(){
  var any=false;
  ['dy','bx','ib'].forEach(function(kind){
    var c=state.charts[kind];if(!c||!c.chart)return;
    any=true;
    var ts=c.chart.timeScale(),r=ts.getVisibleLogicalRange(),box=$(kind+'-ovl')&&$(kind+'-ovl').parentNode;
    var y0=c.series.priceToCoordinate(c.k.candles[0][1]),y1=c.series.priceToCoordinate(c.k.candles[0][1]*1.01);
    var sig=(r?r.from.toFixed(2)+'|'+r.to.toFixed(2):'')+'|'+(y0==null?'':y0.toFixed(1))+'|'+(y1==null?'':y1.toFixed(1))+'|'+(box?box.clientWidth+'x'+box.clientHeight:'');
    if(sig!==c.sig){c.sig=sig;drawOverlay(kind);}
  });
  state.raf=any?requestAnimationFrame(overlayLoop):0;
}
function eventTable(k){
  var ev=[];
  k.real.forEach(function(e){ev.push({t:e.t,src:'Thật',k:e.k,px:e.px,s:e.s});});
  k.sim.forEach(function(e){ev.push({t:e.t,src:'Mô phỏng',k:e.k,px:e.px,open:e.open,s:e.s});});
  ev.sort(function(a,b){return a.t-b.t||(a.src==='Thật'?-1:1);});
  var KL={in:'Vào',add:'Thêm tầng',out:'Thoát'};
  var rows=ev.slice(0,80).map(function(e){
    return '<tr><td>'+(e.src==='Thật'?'<span class="pill">Thật</span>':'<span class="pill yes" style="color:var(--accent);border-color:var(--accent)">Mô phỏng</span>')+'</td><td style="text-align:left">'+KL[e.k]+(e.s?' '+(e.s==='long'?'long':'short'):'')+(e.open?' <span class="sm">(chưa đóng, theo giá thị trường tại horizon)</span>':'')+'</td>'+td(fmtVN(e.t,true))+td(price(e.px))+'</tr>';
  });
  return '<details class="dd"><summary>Bảng sự kiện ('+num(ev.length,0)+')</summary>'+table(['Nguồn','Loại','Giờ VN','Giá'],rows)+(ev.length>80?'<p class="tcap">Hiển thị 80 sự kiện đầu.</p>':'')+'</details>';
}
function initPx(b,kind){
  disposePx(kind);
  var k=pxList(b,kind)[state.sel[kind]||0];if(!k||!$(kind+'-chart'))return;
  var txt;
  if(k.src==='p3'){
    txt='Mã '+k.sym+', ngày '+fmtDate(k.day)+' (giờ VN): '+num(k.n_real,0)+' lệnh con thật ('+num(k.n_long_real,0)+' long) và '+num(k.n_sim,0)+' lệnh con mô phỏng của playbook ('+num(k.n_long_sim,0)+' long). PnL các lệnh mở trong ngày: thật '+sgn(k.pnl_real,0)+' USDT, mô phỏng '+sgn(k.pnl_sim,0)+' USDT (cỡ lệnh khác nhau nên chỉ so dấu và hình dạng). Mỗi lệnh có ký hiệu ở giá vào và ở giá ra (chỉ hiện thoát nằm trong khung nến). Khung nến '+num(k.tf,0)+' phút, trục giờ Việt Nam.';
  }else if(k.src==='p4'){
    txt='Rổ '+k.sym+' '+(k.side==='long'?'long':'short')+(ok(k.lev)?' '+num(k.lev,0)+'x':'')+': mọi fill vào và thêm tầng là fill thật ('+num(k.real.filter(function(e){return e.k!=='out';}).length,0)+'); thoát thật là ký hiệu đặc, thoát mô phỏng là vòng rỗng. Lợi suất thật '+(ok(k.ret_real)?num(k.ret_real,2)+'%':DASH)+', mô phỏng '+(ok(k.ret_sim)?num(k.ret_sim,2)+'%':DASH)+'. Khung nến '+(k.tf>=60?num(k.tf/60,0)+' giờ':num(k.tf,0)+' phút')+', trục giờ Việt Nam; kết quả trong mẫu.';
  }else{
    var realOut=k.real.filter(function(e){return e.k==='out';}),simOut=k.sim.filter(function(e){return e.k==='out';});
    var lastReal=realOut.length?Math.max.apply(null,realOut.map(function(e){return e.t;})):null;
    var firstSim=simOut.length?Math.min.apply(null,simOut.map(function(e){return e.t;})):null;
    var d=(lastReal&&firstSim)?(firstSim-lastReal)/60000:null,simOpen=simOut.some(function(e){return e.open;});
    txt='Rổ '+k.sym+' '+(k.side==='long'?'long':'short')+(ok(k.lev)?' '+num(k.lev,0)+'x':'')+', '+num(k.real.filter(function(e){return e.k!=='out';}).length,0)+' fill thật, '+num(k.sim.filter(function(e){return e.k==='add';}).length,0)+' tầng thêm mô phỏng. Lợi suất thật '+(ok(k.ret_real)?num(k.ret_real,2)+'%':DASH)+', mô phỏng '+(ok(k.ret_sim)?num(k.ret_sim,2)+'%':DASH)+'.';
    if(simOpen)txt+=' Mô phỏng chưa thoát trong horizon (đến giờ thoát thật cộng 60 phút): vòng nét đứt là giá thị trường tại đó.';
    else if(d!=null)txt+=' Mô phỏng thoát '+(d>=0?'muộn hơn':'sớm hơn')+' lệnh thật cuối cùng '+num(Math.abs(d),1)+' phút'+(Math.abs(d)<=15?' (trong ±15 phút)':'')+'.';
    txt+=' Fill đầu của mô phỏng là fill thật (điều kiện hoá), nên chỉ hiện ký hiệu thật. Khung nến '+(k.tf>=60?num(k.tf/60,0)+' giờ':num(k.tf,0)+' phút')+', trục giờ Việt Nam.';
  }
  $(kind+'-note').textContent=txt;
  $(kind+'-events').innerHTML=eventTable(k);
  var em=$(kind+'-empty');em.hidden=true;
  if(!HAS_LW){showEmpty(kind+'-empty','Không tải được thư viện biểu đồ (cần mạng để lấy lightweight-charts từ unpkg).');return;}
  if(!k.candles||k.candles.length<2){showEmpty(kind+'-empty','Không có dữ liệu nến cho mã này trong khoảng thời gian đã chọn.');$(kind+'-legend').textContent='';return;}
  var ch=LightweightCharts.createChart($(kind+'-chart'),baseOpts({}));
  var ser=ch.addCandlestickSeries({upColor:COL.up,downColor:COL.down,borderVisible:false,wickUpColor:COL.up,wickDownColor:COL.down,priceLineVisible:false,lastValueVisible:false,
    priceFormat:{type:'custom',minMove:0.0000001,formatter:price}});
  var times=k.candles.map(function(c){return c[0];});
  ser.setData(k.candles.map(function(c){return {time:c[0]+SHIFT,open:c[1],high:c[2],low:c[3],close:c[4]};}));
  ch.timeScale().fitContent();
  state.charts[kind]={chart:ch,series:ser,k:k,times:times,sig:''};
  var tfl=k.tf>=60?(k.tf/60)+'h':k.tf+'m';
  ch.subscribeCrosshairMove(function(p){
    var lg=$(kind+'-legend');if(!lg)return;
    var dd=p&&p.seriesData&&p.seriesData.get(ser);
    if(!dd){lg.textContent=k.sym+' '+tfl;return;}
    lg.textContent=k.sym+' '+fmtVN((p.time-SHIFT)*1000)+'  O '+price(dd.open)+'  H '+price(dd.high)+'  L '+price(dd.low)+'  C '+price(dd.close);
  });
  $(kind+'-legend').textContent=k.sym+' '+tfl;
  drawOverlay(kind);
  if(!state.raf)state.raf=requestAnimationFrame(overlayLoop);
}
function disposePx(kind){var c=state.charts[kind];if(c&&c.chart){try{c.chart.remove();}catch(e){}}state.charts[kind]=null;}
function initP3c(b){
  var el=$('p3c-chart');if(!el)return;
  if(!HAS_LW){showEmpty('p3c-empty','Không tải được thư viện biểu đồ.');return;}
  var W=b.p3&&b.p3.windows,w=W&&(W.full||W.test),dl=w&&w.daily;
  if(!dl||!dl.days||!dl.days.length){showEmpty('p3c-empty','Không có chuỗi PnL theo ngày.');return;}
  var ch=LightweightCharts.createChart(el,baseOpts({timeScale:{borderColor:COL.line,timeVisible:false,rightOffset:1}}));
  var a=ch.addLineSeries({color:COL.accent,lineWidth:2,priceLineVisible:false});
  var s=ch.addLineSeries({color:COL.short,lineWidth:2,lineStyle:2,priceLineVisible:false});
  a.setData(dl.days.map(function(d,i){return {time:d*86400,value:dl.real_cum[i]};}));
  s.setData(dl.days.map(function(d,i){return {time:d*86400,value:dl.sim_cum[i]};}));
  var sp=b.p3.split&&b.p3.split.split_t;
  if(sp){try{a.setMarkers([{time:Math.floor(sp/86400000)*86400,position:'aboveBar',color:COL.text,shape:'arrowDown',text:'bắt đầu test'}]);}catch(e){}}
  $('p3c-legend').innerHTML='<span class="sw2" style="color:'+COL.accent+'"></span>Thật <span class="sw2 dash" style="color:'+COL.short+';margin-left:10px"></span>Playbook mô phỏng <span class="muted" style="margin-left:10px">USDT, ngày UTC</span>';
  ch.timeScale().fitContent();
  state.charts.p3c={chart:ch};
}

/* ---------- mở, đóng ngăn chi tiết ---------- */
function openDrawer(i,opener){
  state.i=i;state.sel={dy:0,bx:0,ib:0};state.lsw='test';state.p3w='test';state.openIds={};
  if(opener)state.opener=opener;
  disposeCharts();readColors();
  renderDrawer(i);
  var d=$('drawer');d.classList.add('open');d.setAttribute('aria-hidden','false');$('scrim').classList.add('open');document.body.classList.add('locked');
  state.open=true;
  $('dscroll').scrollTop=0;
  try{history.replaceState(null,'','#'+BOTS[i].slug);}catch(e){}
  var rows=document.querySelectorAll('#ranks-body tr');for(var r=0;r<rows.length;r++)rows[r].classList.toggle('sel',+rows[r].getAttribute('data-i')===i);
  requestAnimationFrame(function(){initCharts(BOTS[i]);d.focus({preventScroll:true});});
}
function initLazy(id,b){
  if(id==='d-p1'){if(b.baskets.length){fillSelect(b,'bx');initPx(b,'bx');}initEq(b);}
  else if(id==='d-p2'){if(b.p2&&b.p2.level_s)initLs(b);}
}
function initCharts(b){
  if(b.p4){if(b.p4.baskets&&b.p4.baskets.length){fillSelect(b,'ib');initPx(b,'ib');}initI4(b);}
  if(b.p3&&b.p3.days&&b.p3.days.length){fillSelect(b,'dy');initPx(b,'dy');}
  initP3c(b);
  ['d-p1','d-p2'].forEach(function(id){var d=$(id);if(d&&d.open)initLazy(id,b);});
}
function closeDrawer(){
  var d=$('drawer');d.classList.remove('open');d.setAttribute('aria-hidden','true');$('scrim').classList.remove('open');document.body.classList.remove('locked');
  state.open=false;disposeCharts();
  var rows=document.querySelectorAll('#ranks-body tr.sel');for(var r=0;r<rows.length;r++)rows[r].classList.remove('sel');
  try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}
  if(state.opener&&state.opener.focus)state.opener.focus({preventScroll:true});
}
function visIdx(){var a=[];BOTS.forEach(function(b,i){if(!state.style||b.styleKey===state.style)a.push(i);});return a;}
function step(dir){var v=visIdx();if(!v.length)return;var p=v.indexOf(state.i);var n=v[((p<0?0:p)+dir+v.length)%v.length];openDrawer(n,state.opener);}

/* ---------- sự kiện ---------- */
document.addEventListener('click',function(e){
  var t=e.target;
  var tr=t.closest&&t.closest('#ranks-body tr[data-i]');
  if(tr&&!t.closest('a')){openDrawer(+tr.getAttribute('data-i'),tr);return;}
  var fc=t.closest&&t.closest('#chips .fchip');
  if(fc){state.style=fc.getAttribute('data-style')||'';renderRanks();return;}
  var ls=t.closest&&t.closest('button[data-ls]');
  if(ls){state.lsw=ls.getAttribute('data-ls');renderDrawerKeep($('dscroll').scrollTop);return;}
  var pw=t.closest&&t.closest('button[data-p3w]');
  if(pw){state.p3w=pw.getAttribute('data-p3w');renderDrawerKeep($('dscroll').scrollTop);return;}
  var ft=t.closest&&t.closest('button[data-fit]');
  if(ft){var cc=state.charts[ft.getAttribute('data-fit')];if(cc&&cc.chart)cc.chart.timeScale().fitContent();return;}
  if(t.id==='scrim'||t.closest('#d-close'))closeDrawer();
  else if(t.closest('#d-prev'))step(-1);
  else if(t.closest('#d-next'))step(1);
});
function renderDrawerKeep(y){
  var b=BOTS[state.i];
  disposeCharts();readColors();renderDrawer(state.i);
  $('dscroll').scrollTop=y;
  requestAnimationFrame(function(){initCharts(b);$('dscroll').scrollTop=y;});
}
document.addEventListener('change',function(e){
  var kd=e.target.getAttribute&&e.target.getAttribute('data-kind');
  if(kd){state.sel[kd]=+e.target.value;initPx(BOTS[state.i],kd);}
});
document.addEventListener('keydown',function(e){
  if(state.open){
    if(e.key==='Escape'){e.preventDefault();closeDrawer();return;}
    if(e.key==='Tab'){
      var d=$('drawer'),f=d.querySelectorAll('a[href],button,select,summary,[tabindex]:not([tabindex="-1"])'),fl=[];
      for(var k=0;k<f.length;k++){if(f[k].offsetParent!==null)fl.push(f[k]);}
      if(!fl.length)return;
      var first=fl[0],last=fl[fl.length-1];
      if(e.shiftKey&&(document.activeElement===first||document.activeElement===d)){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
    return;
  }
  if((e.key==='Enter'||e.key===' ')&&e.target.matches&&e.target.matches('#ranks-body tr[data-i]')){e.preventDefault();openDrawer(+e.target.getAttribute('data-i'),e.target);}
});
function applyTheme(){
  readColors();
  var c=state.charts;
  ['dy','bx','ib','eq','ls','p3c','i4'].forEach(function(k){
    var x=c[k];if(!x||!x.chart)return;
    x.chart.applyOptions({layout:{background:{type:'solid',color:COL.surface},textColor:COL.text},grid:{vertLines:{color:COL.grid},horzLines:{color:COL.grid}},rightPriceScale:{borderColor:COL.line},timeScale:{borderColor:COL.line}});
  });
  if(state.open){var y=$('dscroll').scrollTop;renderDrawerKeep(y);}
}
if(window.matchMedia){var mq=matchMedia('(prefers-color-scheme: dark)');if(mq.addEventListener)mq.addEventListener('change',applyTheme);else if(mq.addListener)mq.addListener(applyTheme);}
new MutationObserver(applyTheme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
document.addEventListener('toggle',function(e){var d=e.target;if(!d||!d.id||d.tagName!=='DETAILS')return;state.openIds[d.id]=d.open;if(d.open&&state.open&&(d.id==='d-p1'||d.id==='d-p2'))initLazy(d.id,BOTS[state.i]);},true);
addEventListener('hashchange',function(){var h=location.hash.slice(1);var i=BOTS.findIndex(function(b){return b.slug===h;});if(i>=0&&(!state.open||state.i!==i))openDrawer(i,null);});
/* mục lục: đánh dấu mục đang xem */
function navSpy(){
  var secs=['overview','bots','method','limits'],cur=secs[0],y=window.scrollY+80;
  secs.forEach(function(s){var el=$(s);if(el&&el.offsetTop<=y)cur=s;});
  var as=document.querySelectorAll('.snav a');for(var i=0;i<as.length;i++)as[i].setAttribute('aria-current',String(as[i].getAttribute('data-sec')===cur));
}
addEventListener('scroll',navSpy,{passive:true});

readColors();
renderSide();renderOverview();renderHead();renderRanks();renderMethod();navSpy();
var h0=location.hash.slice(1);
if(h0){var i0=BOTS.findIndex(function(b){return b.slug===h0;});if(i0>=0)openDrawer(i0,null);}
})();
'''

HTML_TPL = r'''<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Mô phỏng lại 10 bot top OKX</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
__CSS__
</style>
</head><body>

<div class="app">
  <aside class="side" aria-label="Điều hướng và bộ lọc">
    <div class="brand">
      <h1>Mô phỏng lại 10 bot top OKX</h1>
      <p class="asof" id="asof"></p>
    </div>
    <nav class="snav" aria-label="Mục lục">
      <a href="#overview" data-sec="overview"><b>Tổng quan</b><span>Đã thử gì, kết luận trung thực</span></a>
      <a href="#bots" data-sec="bots"><b>Bảng 10 bot</b><span>Bấm một bot để xem nến và chi tiết</span></a>
      <a href="#method" data-sec="method"><b>Phương pháp</b><span>Chia 60/40, mốc ngẫu nhiên, Level A/B/S</span></a>
      <a href="#limits" data-sec="limits"><b>Giới hạn</b><span>Điều dữ liệu không cho biết</span></a>
    </nav>
    <div class="sblock">
      <h2>Lối chơi</h2>
      <div class="chips" id="chips" role="group" aria-label="Lọc theo lối chơi"></div>
    </div>
    <div class="sblock mkt">
      <h2>Tiến độ</h2>
      <div class="prog" id="prog"></div>
    </div>
  </aside>

  <main class="main">
    <section class="msec" id="overview" aria-labelledby="ov-h">
      <h2 id="ov-h">Tổng quan</h2>
      <p class="lead" style="margin-bottom:14px">Đã thử suy ngược luật giao dịch của 10 lead copy-trade hàng đầu OKX: đọc cách chơi họ mô tả, đặt giả thuyết, dựng các họ luật vào lệnh, thêm tầng, thoát; backtest cùng lúc, trên cùng mã, rồi so với lệnh thật.</p>
      <p class="headline" id="headline"></p>
      <ul class="points" id="points"></ul>
    </section>

    <section class="msec" id="bots" aria-labelledby="bt-h">
      <h2 id="bt-h">Mười bot theo hạng OKX</h2>
      <p class="hint">Bấm một hàng để mở chi tiết: giả thuyết, bằng chứng, luật mô phỏng, bảng khớp, nến thật và mô phỏng.</p>
      <div class="tablewrap">
        <table class="grid ranks" id="ranks">
          <thead id="ranks-head"></thead>
          <tbody id="ranks-body"></tbody>
        </table>
      </div>
      <p class="tnote">Thoát: tỷ lệ rổ mà giờ thoát mô phỏng lệch không quá 15 phút so với thật, ở tập test (40% cuối theo thời gian); chữ xanh kèm nhãn "vượt" khi lớn hơn p95 của mốc ngẫu nhiên. Với nhóm DCA, cột thoát là mô phỏng riêng luật thoát khi giữ nguyên các fill thật; các nhóm mẫu nhỏ ghi thêm kết quả LOO. Add: khớp cả giờ và giá (bot mẫu nhỏ: LOO ±15 phút). Level S: tỷ lệ 12 chỉ số thống kê của backtest tự chạy nằm trong ±20% so với bot thật; "—" nếu giai đoạn 2 chưa chạy. Kết luận lấy từ giai đoạn 2 nếu có (GĐ2), nếu không thì giai đoạn 1 (GĐ1).</p>
    </section>

    <section class="msec" id="method" aria-labelledby="mt-h">
      <h2 id="mt-h">Phương pháp</h2>
      <ol class="flow2" id="mflow"></ol>
      <div class="mgrid" id="mgrid"></div>
    </section>

    <section class="msec" id="limits" aria-labelledby="lm-h">
      <h2 id="lm-h">Giới hạn và lưu ý</h2>
      <div class="limits" id="limits-body"></div>
      <p class="srcnote">Nguồn: OKX public API v5 (copytrading public-*, nến 1 phút các mã đã giao dịch). Báo cáo do build_report.py sinh từ okx-top10/bots.json, summary.json và kết quả trong test/scripts/okx_top10/out.</p>
    </section>
  </main>
</div>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="d-name" aria-hidden="true" tabindex="-1">
  <div class="dhead">
    <div class="dtop">
      <div class="dtitle">
        <span class="rk" id="d-rank"></span>
        <h2 id="d-name"></h2>
        <span id="d-chip"></span>
      </div>
      <div class="dnav">
        <button type="button" class="ib" id="d-prev" aria-label="Bot trước"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 L5 8 L10 13"/></svg></button>
        <span class="pos-i" id="d-pos" aria-live="polite"></span>
        <button type="button" class="ib" id="d-next" aria-label="Bot sau"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3 L11 8 L6 13"/></svg></button>
        <button type="button" class="ib" id="d-close" aria-label="Đóng"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5 L12.5 12.5 M12.5 3.5 L3.5 12.5"/></svg></button>
      </div>
    </div>
    <div class="dmeta" id="d-meta"></div>
  </div>
  <div class="dscroll" id="dscroll">
    <dl class="kpi" id="d-kpi" style="margin-top:0"></dl>
    <div id="d-body" style="margin-top:26px"></div>
  </div>
</aside>

<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script type="application/json" id="data">__DATA__</script>
<script>
__JS__
</script>
</body></html>
'''


# ------------------------------------------------------------------ xuất HTML
def sanitize(o):
    """Thay NaN/inf bằng None để JSON.parse hợp lệ."""
    if isinstance(o, dict):
        return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else v
    return o


def render(D, out_path):
    payload = json.dumps(sanitize(D), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = HTML_TPL.replace("__CSS__", CSS).replace("__JS__", JS).replace("__DATA__", payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return len(html.encode("utf-8")), len(payload.encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disc-dir", default=P1_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    if os.path.abspath(a.out) == os.path.join(NONE_DIR, "okx-report.html"):
        sys.exit("Không ghi đè okx-report.html")
    D = build_data(a.disc_dir)
    size, dsize = render(D, a.out)
    n_c = sum(len(b["candles"] or []) for x in D["bots"] for b in x["baskets"])
    print(f"ghi {a.out}: {size / 1e6:.2f} MB (dữ liệu JSON {dsize / 1e6:.2f} MB, {n_c} nến, "
          f"{sum(len(x['baskets']) for x in D['bots'])} rổ đại diện); giai đoạn 2 có cho {D['meta']['n_p2']}/{len(D['bots'])} bot")


if __name__ == "__main__":
    main()
