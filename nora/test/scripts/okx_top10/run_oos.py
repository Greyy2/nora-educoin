#!/usr/bin/env python3
"""Kiểm tra ngoài mẫu (Out-Of-Sample - OOS) cho 10 bot top OKX.
Quy trình chuẩn:
1. Dữ liệu sắp theo thời gian vào lệnh t0.
2. 60% thời gian đầu dùng làm tập DÒ LUẬT (Train).
3. 40% thời gian sau dùng làm tập CHẤM ĐIỂM (Test / Out-Of-Sample).
4. Đo nghiêm ngặt theo đủ 7 tiêu chí trên 40% dữ liệu Test.
"""
import os, sys, json, time, argparse
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import load, implied

def run_bot_oos(name, out_dir=None, verbose=True):
    t0_start = time.time()
    bot = load.get_bot(name)
    slug = load.slug(name)
    P = (lambda *a: print(f"[{name}|OOS]", *a, flush=True)) if verbose else (lambda *a: None)
    
    D = implied.Data(bot, verbose=False)
    n = D.n
    if n < 4:
        P(f"Số rổ quá ít ({n}), bỏ qua.")
        return None
        
    order = np.argsort(D.t0, kind="stable")
    n_tr = int(round(0.6 * n))
    tr_mask = np.zeros(n, bool); tr_mask[order[:n_tr]] = True
    te_mask = ~tr_mask
    n_te = int(te_mask.sum())
    P(f"Tổng {n} rổ -> Train (60%): {n_tr} rổ, Test (40%): {n_te} rổ")
    
    df = implied.facts(D); cl = implied.classify(df); df["cl"] = cl
    mix = implied.class_mix(df)
    ld = implied.layer_facts(D); lcl = implied.classify(ld); ld["cl"] = lcl
    
    # 1. Khớp các công thức cơ bản trên tập Train
    df_tr = df.iloc[order[:n_tr]].copy()
    cl_tr = cl[order[:n_tr]]
    ld_tr = ld.copy() # layer facts
    
    fits = {an: implied.fit_elements(df_tr, cl_tr, an) for an in ("avg", "first", "last")}
    fits["layer"] = implied.fit_elements(ld, lcl, "layer")
    
    # 2. Khởi tạo Searcher
    S = implied.Searcher(D, df, fits)
    
    # Thiết lập ràng buộc theo loại bot
    sl_share = float((mix["SL"]) / n)
    bot_type = "cutter" if sl_share >= 0.12 else "hold"
    
    if bot_type == "hold":
        S.allowed = {"tp", "tpk", "tpt", "tpsw", "sl", "tr", "brd", "sig"}
        S.sig_gates = [0.0, 0.002, 0.005, 0.01]
    
    # Các điều chỉnh đặc thù
    if "dark_wood" in slug:
        S.allowed.discard("tc")
        S.allowed.add("sig")
        S.allowed.add("tr")
        P("Dark-Wood: Cấm time-cap cứng (tc), bắt buộc dùng trailing/chỉ báo")
        
    if "01pp" in slug:
        S.sig_tight_grid = [0.0, 0.2, 0.35, 0.5]
        P("01pp: Bật cơ chế 2-bước (chỉ báo kích hoạt tight trailing)")
        
    # 3. Dò luật trên 60% Train (thử các anchor)
    per_anchor = {}
    for ai, an in enumerate(implied.ANCHORS):
        if an not in fits:
            continue
        # Chạy ablation canonical CHỈ TRÊN TẬP TRAIN
        S.grp = np.zeros(n, np.int64); S.G = 1
        cfg = dict(anchor=ai)
        steps = [implied._row(S, cfg, "không luật", None, None)]
        prev = S.score(cfg, idx=tr_mask)["obj"]
        
        for elem_name, label in implied.ELEM_ORDER:
            if elem_name not in S.allowed:
                continue
            if elem_name in ("tpk", "tpt", "tpsw") and cfg.get("tp") is None:
                continue
            if elem_name == "tpsw" and not cfg.get("tpt"):
                continue
            trial = implied._cp(cfg); S.init_elem(trial, elem_name)
            S.tune(trial, idx=tr_mask)
            sc = S.score(trial, idx=tr_mask)["obj"]
            acc = bool(sc - prev >= implied.MIN_GAIN)
            if acc:
                cfg = trial; prev = sc
        per_anchor[an] = dict(cfg=cfg, obj=prev)
        
    best_an = max(per_anchor, key=lambda a: per_anchor[a]["obj"])
    cfg_base = per_anchor[best_an]["cfg"]
    P(f"Neo tốt nhất trên Train: {best_an}, cấu trúc={implied.structure(cfg_base)}")
    
    # 4. Tách chế độ trên tập Train (nếu bot đủ lớn)
    if "physical" in slug:
        sp_defs = [("lớp mã", implied.group_class(D, min_n=15)), ("tuần lịch", implied.group_week(D, min_n=15, max_groups=2))]
    elif n <= 25:
        sp_defs = [] # Mẫu nhỏ không chia nhóm để chống overfit
    else:
        sp_defs = [("lớp mã", implied.group_class(D)), ("tuần lịch", implied.group_week(D, min_n=12, max_groups=6))]
        
    chosen_split = None; final_cfg = implied._cp(cfg_base)
    best_obj = S.score(cfg_base, idx=tr_mask)["obj"]
    best_grp = np.zeros(n, np.int64); best_G = 1
    
    for sp_name, (grp, info) in sp_defs:
        G = int(grp.max()) + 1
        if G < 2:
            continue
        c2, o2 = implied.split_tune(S, cfg_base, grp, G, idx=tr_mask)
        if o2 - best_obj >= 0.01:
            best_obj = o2; chosen_split = sp_name
            final_cfg = c2; best_grp = grp; best_G = G
            P(f"Tập Train nhận tách {sp_name} (G={G}, gain=+{o2 - best_obj:.3f})")
            
    S.grp = best_grp; S.G = best_G
    # Polish nhẹ trên Train
    final_cfg = implied.clean(implied.polish(S, final_cfg, n=2000, seed=42, idx=tr_mask))
    final_cfg = implied.clean(final_cfg)
    
    # 5. ĐO LƯỜNG NGOÀI MẪU TRÊN 40% TEST
    m_tr, o_tr = S.score(final_cfg, idx=tr_mask, keep=True)
    m_te, o_te = S.score(final_cfg, idx=te_mask, keep=True)
    
    crit_tr = m_tr["crit"]; crit_te = m_te["crit"]
    
    # Tính 7 tiêu chí trên Test:
    ratio_te = crit_te.get("pnl_ratio", 0.0)
    c1 = bool(0.80 <= ratio_te <= 1.20)
    
    w_diff_te = crit_te.get("win_sim", 0.0) - crit_te.get("win_real", 0.0)
    c2 = bool(abs(w_diff_te) <= 8.0)
    
    bw_te = crit_te.get("both_win_ratio", np.nan)
    bl_te = crit_te.get("both_lose_ratio", np.nan)
    c3_w = bool(0.75 <= bw_te <= 1.33) if np.isfinite(bw_te) else True
    c3_l = bool(0.75 <= bl_te <= 1.33) if np.isfinite(bl_te) else True
    c3 = c3_w and c3_l
    
    sign_te = crit_te.get("sign_agree", 0.0)
    c4 = bool(sign_te >= 0.80)
    
    cu_te = crit_te.get("corr_usdt", 0.0)
    sp_te = crit_te.get("spearman", 0.0)
    c3_ex_te = crit_te.get("corr_usdt_ex_top3", 0.0)
    c5 = bool(cu_te >= 0.75 and sp_te >= 0.60 and c3_ex_te >= 0.60)
    
    quads = crit_te.get("quadrants", {})
    c6 = all(q.get("ok", False) for q in quads.values()) if quads else True
    
    m60_te = m_te.get("m60", 0.0)
    hw_te = m_te["hold"].get("win", np.nan)
    hl_te = m_te["hold"].get("loss", np.nan)
    c7_m60 = bool(m60_te >= 0.50)
    c7_hw = bool(0.6 <= hw_te <= 1.6) if np.isfinite(hw_te) else True
    c7_hl = bool(0.6 <= hl_te <= 1.6) if np.isfinite(hl_te) else True
    c7 = c7_m60 and c7_hw and c7_hl
    
    passed_7 = c1 and c2 and c3 and c4 and c5 and c6 and c7
    pass_cnt = sum([c1, c2, c3, c4, c5, c6, c7])
    
    P(f"KẾT QUẢ TEST OOS: {pass_cnt}/7 tiêu chí đạt | OOS Khớp Tốt = {passed_7}")
    P(f"  #1 PnL Ratio: {ratio_te:.3f} ({'PASS' if c1 else 'FAIL'})")
    P(f"  #2 Win diff: {w_diff_te:+.1f}% ({'PASS' if c2 else 'FAIL'})")
    P(f"  #3 Med Win/Loss: {bw_te:.2f} / {bl_te:.2f} ({'PASS' if c3 else 'FAIL'})")
    P(f"  #4 Sign agree: {sign_te*100:.1f}% ({'PASS' if c4 else 'FAIL'})")
    P(f"  #5 Corr USDT: {cu_te:.3f} | Spear: {sp_te:.3f} ({'PASS' if c5 else 'FAIL'})")
    P(f"  #6 4 Quadrants: {'PASS' if c6 else 'FAIL'}")
    P(f"  #7 Exit <=60p: {m60_te*100:.1f}% ({'PASS' if c7_m60 else 'FAIL'}) | Hold: {hw_te:.2f}/{hl_te:.2f}")
    
    res = {
        "bot": name,
        "slug": slug,
        "n_total": n,
        "n_train": n_tr,
        "n_test": n_te,
        "structure": list(implied.structure(final_cfg)),
        "split": chosen_split,
        "train_metrics": {
            "obj": round(float(m_tr["obj"]), 4),
            "pnl_ratio": round(float(crit_tr.get("pnl_ratio", 0)), 3),
            "sign_agree": round(float(crit_tr.get("sign_agree", 0) * 100), 1),
            "corr_usdt": round(float(crit_tr.get("corr_usdt", 0)), 3),
            "exit60": round(float(m_tr.get("m60", 0) * 100), 1),
        },
        "test_metrics": {
            "obj": round(float(m_te["obj"]), 4),
            "viol": round(float(m_te["viol"]), 3),
            "pnl_ratio": round(float(ratio_te), 3),
            "win_real": round(float(crit_te.get("win_real", 0)), 1),
            "win_sim": round(float(crit_te.get("win_sim", 0)), 1),
            "win_diff": round(float(w_diff_te), 1),
            "both_win_ratio": round(float(bw_te), 3) if np.isfinite(bw_te) else None,
            "both_lose_ratio": round(float(bl_te), 3) if np.isfinite(bl_te) else None,
            "sign_agree": round(float(sign_te * 100), 1),
            "corr_usdt": round(float(cu_te), 3),
            "spearman": round(float(sp_te), 3),
            "corr_ex_top3": round(float(c3_ex_te), 3),
            "exit5": round(float(m_te.get("m5", 0) * 100), 1),
            "exit15": round(float(m_te.get("m15", 0) * 100), 1),
            "exit60": round(float(m60_te * 100), 1),
            "hold_win_ratio": round(float(hw_te), 3) if np.isfinite(hw_te) else None,
            "hold_loss_ratio": round(float(hl_te), 3) if np.isfinite(hl_te) else None,
            "criteria_pass": {
                "c1_pnl_ratio": c1,
                "c2_win_rate": c2,
                "c3_median_ret": c3,
                "c4_sign_agree": c4,
                "c5_correlation": c5,
                "c6_quadrants": c6,
                "c7_exit_timing": c7
            },
            "criteria_passed_count": pass_cnt,
            "khop_tot_oos": passed_7
        },
        "elapsed_sec": round(time.time() - t0_start, 1)
    }
    
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"oos_{slug}.json")
        with open(out_file, "w") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
            
    return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", nargs="*", help="Tên bot cần chạy (mặc định: tất cả 10)")
    parser.add_argument("--out", default=os.path.join(HERE, "out"))
    args = parser.parse_args()
    
    all_bots = load.load_bots()
    if args.bot:
        names = [b["name"] for b in all_bots if any(k.lower() in b["name"].lower() or k.lower() in load.slug(b["name"]) for k in args.bot)]
    else:
        names = [b["name"] for b in all_bots]
        
    print(f"BẮT ĐẦU CHẠY KIỂM NGOÀI MẪU (OOS 60% Train / 40% Test) CHO {len(names)} BOTS...")
    results = []
    for n in names:
        r = run_bot_oos(n, args.out)
        if r:
            results.append(r)
            
    summary_path = os.path.join(args.out, "oos_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    print("\n" + "=" * 115)
    print(f"{'Bot':<22} | {'N':<4} | {'N_te':<4} | {'PnL_Ratio':<9} | {'Win_Diff':<8} | {'Sign%':<6} | {'CorrUSDT':<8} | {'Exit60%':<7} | {'Passed':<6} | {'OOS Khớp Tốt?'}")
    print("-" * 115)
    for r in results:
        tm = r["test_metrics"]
        bname = r["bot"]
        n_tot = r["n_total"]
        n_te = r["n_test"]
        pnl = tm["pnl_ratio"]
        wd = tm["win_diff"]
        sg = tm["sign_agree"]
        cu = tm["corr_usdt"]
        e60 = tm["exit60"]
        cnt = tm["criteria_passed_count"]
        ok = "KHỚP TỐT (PASS)" if tm["khop_tot_oos"] else f"TRƯỢT ({cnt}/7)"
        print(f"{bname:<22} | {n_tot:<4} | {n_te:<4} | {pnl:8.3f}  | {wd:+7.1f}% | {sg:5.1f}% | {cu:8.3f} | {e60:6.1f}% | {cnt}/7   | {ok}")
    print("=" * 115)
