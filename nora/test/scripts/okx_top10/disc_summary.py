"""In bảng tóm tắt từ out/disc_*.json (không phải playbook_*)."""
import json, glob, os
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
for p in sorted(glob.glob(os.path.join(D, "disc_*.json"))):
    d = json.load(open(p)); print("=====", d["bot"], os.path.getsize(p) // 1000, "KB n", d["n_baskets"])
    if d.get("tiny"):
        print(" tiny", d["verdict"]["label"]); continue
    sp = d["split"]; pn = d["panels"]; s = d["sim"]; pm = s["primary_model"]; b = s["baselines"]
    print(" split", sp["n_train"], sp["n_test"], "LOO" if sp["loo"] else "", "scalp", d["n_scalp_sub_minute"], "selfcheck_bad", d["selfcheck_no_lookahead"]["n_bad"])
    print(" AUC gbm exit/add/entry", pn["exit"]["gbm"]["auc_test"], pn["add"]["gbm"].get("auc_test") if "gbm" in pn["add"] else None, pn["entry"]["gbm"]["auc_test"],
          "| tree3", pn["exit"]["tree3"]["auc_test"], pn["add"].get("tree3", {}).get("auc_test"), pn["entry"]["tree3"]["auc_test"],
          "| pair", pn["exit"]["pair"]["auc_test"], pn["add"].get("pair", {}).get("auc_test"), pn["entry"]["pair"]["auc_test"])
    print(" iters", [(i["name"], i["train_close15"], i.get("train_sel_score"), i["test_close15"]) for i in d["iterations"]], "-> cfg", d["selected_exit_config"]["name"])
    t = s["level_a_test_exit_only_replay_fills"][pm]; f = s["level_a_test_full_sim_add_plus_exit"].get(pm, {})
    print(" primary", pm, "exit-only m5/15/60", t.get("close_match_5"), t.get("close_match_15"), t.get("close_match_60"), "CI15", s["exit15_ci95_primary"], "pnl_corr", t.get("pnl_corr"), "sign", t.get("pnl_sign_agree"))
    print(" full(add+exit) m15", f.get("close_match_15"), "add_match", f.get("add_match"), "tr_add", f.get("tr_add_match"), "pnl_corr", f.get("pnl_corr"), "layer_eq", f.get("tr_layer_eq"))
    sh = b["shuffled_tp"] or {}
    print(" baselines: null m15", b["null"].get("close_match_15"), "corr", b["null"].get("pnl_corr"), "| shufTP m15 mean/p95", sh.get("close_match_15", {}).get("mean"), sh.get("close_match_15", {}).get("p95"), "corr p95", sh.get("pnl_corr", {}).get("p95"), "| phase1 add", s["phase1_best_mechanical_add_match_test"])
    for n, v in d["sim_entry_levelB"].items():
        print("  entry", n, "global", v["test"]["strength"][:28], v["test"]["recall_15"], v["test"]["precision_15"], "| rate-matched", v["rate_matched"]["test"]["recall_15"], v["rate_matched"]["test"]["precision_15"], "n_sim", v["rate_matched"]["test"]["n_sim_starts"], "n_act", v["rate_matched"]["test"]["n_actual_starts"])
    print(" verdict", d["verdict"]["label"], d["verdict"]["passes"])
    for n, v in d["level_s"].items():
        if n.startswith("_"): continue
        for w in ("test", "full"):
            if w in v:
                r = v[w]; rp = r.get("replay_entries", {})
                sm = r.get("sim") or {}
                print("  S", n, w, "match", (r.get("compare") or {}).get("stats_match_score"), "dcorr", (r.get("daily") or {}).get("daily_corr"), "overlap15 rec/prec", (r.get("basket_overlap") or {}).get("recall_15"), (r.get("basket_overlap") or {}).get("precision_15"),
                      "mix", r.get("mix_overlap"), "holdMed", sm.get("holdMed"), "win", sm.get("win"), "| replay-entries match", (rp.get("compare") or {}).get("stats_match_score"), "dcorr", (rp.get("daily") or {}).get("daily_corr"))
