"""Xuất bản SỔ chung vốn từ các alpha FINAL của một lượt phễu (job API `funnel_book`) -> data/alphas/book.json (+ testnet/book.json khi holdout đạt).

Quy trình (bằng chứng do người dùng chạy trước, job chỉ đọc lại + chấm holdout MỘT lần):
  1. alpha_ids: alpha FINAL của lượt, MỖI chiến lược một alpha (sổ khoá theo id chiến lược). Khoá regime "learn" bị bỏ (bản off/learn trùng).
  2. wfa_job_id: job book_wfa (advanced, đúng các cấu hình này, cùng risk_per_trade_pct, cùng khung) — gate WFA danh mục phải QUA.
  3. Holdout (dev2_end -> end của lượt, khung của lượt, kill switch bật): khớp "level" và "extreme" -> gates.evaluate_s6.
Sổ ghi ra theo registry.write_book: status READY_FOR_TESTNET khi holdout đạt (kèm testnet/book.json), không thì HOLDOUT_FAILED.

explore=True (sổ THỬ NGHIỆM cho demo, không phải sổ đã kiểm định): nhận alpha đã qua S1 (chưa cần FINAL), WFA tuỳ chọn và không bắt qua,
holdout chỉ để tham khảo -> data/alphas/explore/book.json, status EXPLORE_DEMO (bot chỉ chạy được ở paper/demo, không bao giờ live).
"""
import os
import time
import warnings
from typing import Any, Dict, List

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"run_id": "", "alpha_ids": "", "risk_per_trade_pct": None, "wfa_job_id": "", "dry_run": False, "explore": False}
EXPLORE_MIN_STAGE = 2      # sổ thử nghiệm: alpha phải qua S1 (stage_idx >= 2 = đã vào S2)


def _metrics(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("ret_pct", "mdd_pct", "sharpe", "trades", "win_rate", "profit_factor", "halted_at")}


def build_report(run_dir: str, alpha_ids: List[str], rpt: float, wfa: Dict[str, Any], explore: bool = False) -> Dict[str, Any]:
    from backend.core.backtest.run import run
    from backend.core.strategy.book import RISK
    from backend.optimize.funnel import gates
    from backend.optimize.funnel.generate import split_regime
    from backend.optimize.funnel.storage import RunStore
    st = RunStore(run_dir, read_only=True)
    try:
        run_info = st.read_run()
        items, cands, seen = [], {}, set()
        for aid in alpha_ids:
            al = st.get_alpha(aid)
            if al is None:
                raise ValueError(f"không có alpha {aid}")
            final = al["stage_reached"] == "FINAL" and not al["rejected_stage"]
            if not final and not (explore and int(al["stage_idx"]) >= EXPLORE_MIN_STAGE):
                raise ValueError(f"{aid} chưa đạt {'S1' if explore else 'FINAL'} (dừng ở {al['stage_reached']})")
            if al["strategy"] in seen:
                raise ValueError(f"mỗi chiến lược một alpha: {al['strategy']} bị lặp")
            seen.add(al["strategy"])
            params, _ = split_regime(al["params"])
            params = {k: v for k, v in params.items() if k != "risk_per_trade_pct"}
            items.append({"id": al["strategy"], "params": params})
            cands[al["strategy"]] = {"accepted": True, "funnel_alpha_id": aid, "final_scale": al["final_scale"], "validated": final,
                                     "stage_reached": al["stage_reached"], "reject_code": al["reject_code"],
                                     "stage_metrics": st.alpha_metrics(aid)}
    finally:
        st.close()
    cfg, w = run_info["config"], run_info["windows_ms"]
    tf = cfg.get("timeframe", "1m")
    from backend.db.data_layout import exchange
    data_ex = cfg.get("data_exchange", "binance")           # run trước khi tách dữ liệu theo sàn = dữ liệu Binance
    if data_ex != exchange():
        raise ValueError(f"run phễu chạy trên dữ liệu {data_ex}, đang dùng {exchange()} (NORA_EXCHANGE) — holdout phải cùng dữ liệu")
    if wfa or not explore:
        wfa_items = sorted((s["id"], s["configs"][0]) for s in wfa.get("candidates") or [] if s.get("configs"))
        want = sorted((i["id"], {k: v for k, v in i["params"].items()}) for i in items)
        if [x[0] for x in wfa_items] != [x[0] for x in want] or any(
                {k: b[1].get(k) for k in a[1]} != a[1] for a, b in zip(wfa_items, want)):   # WFA chỉ ghi khoá khác mặc định
            raise ValueError("job WFA không chạy đúng các cấu hình của sổ")
        if float(wfa.get("risk_per_trade_pct") or -1) != float(rpt):
            raise ValueError(f"job WFA chạy rủi ro {wfa.get('risk_per_trade_pct')}% khác {rpt}%")
        if not explore and not (wfa.get("gate") or {}).get("passed"):
            raise ValueError("gate WFA danh mục của sổ chưa qua")
    hold = {}
    for sf in ("level", "extreme"):
        r = run([(i["id"], i["params"]) for i in items], cfg["symbols"], int(w["dev2_end"]), int(w["end"]), rpt, sf, RISK, base_frame=tf)
        hold[sf] = _metrics(r)
    ok, code, msg = gates.evaluate_s6(hold["level"], hold["extreme"])
    return {
        "timeframe": tf,
        "data_exchange": data_ex,
        "windows": gates.windows_iso(w),
        "gates": {"funnel_thresholds": cfg.get("thresholds"), "wfa_gate": wfa.get("gate"), "holdout": {"min_ret_pct": gates.S6_MIN_RET_PCT,
                                                                                                      "max_mdd_pct": gates.S6_MAX_MDD_PCT}},
        "book": {"strategies": items, "risk_per_trade_pct": float(rpt), "risk": RISK, "risk_scale_bootstrap": None,
                 "dev2_base_risk": {"wfa_summary": {k: v for k, v in (wfa.get("summary") or {}).items() if k not in ("oos_daily", "oos_daily_dates")}},
                 "explore": bool(explore),
                 "final": {"holdout": hold, "holdout_reason": msg}, "holdout_pass": bool(ok)},
        "candidates": cands,
    }


def run_job(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("funnel_book")
    from backend.api.jobs import batch as batch_jobs
    from backend.core.params.presets import alphas_dir
    from backend.optimize.funnel.orchestrator import funnel_root
    from backend.optimize.registry import write_book
    from backend.utils.jobs import as_list
    from backend.optimize.registry import write_explore_book
    run_dir = os.path.join(funnel_root(), a.run_id)
    wfa = {}
    if a.wfa_job_id or not a.explore:
        job = batch_jobs.status(a.wfa_job_id)
        if not job or job.get("kind") != "book_wfa" or job.get("status") != "done":
            raise SystemExit(f"wfa_job_id {a.wfa_job_id} không phải job book_wfa đã xong")
        wfa = job["result"]
    rep = build_report(run_dir, as_list(a.alpha_ids), float(a.risk_per_trade_pct), wfa, explore=bool(a.explore))
    h = rep["book"]["final"]["holdout"]
    print(f"holdout level {h['level']['ret_pct']}% / extreme {h['extreme']['ret_pct']}% (MDD {h['extreme']['mdd_pct']}%) -> "
          f"{'ĐẠT' if rep['book']['holdout_pass'] else 'TRƯỢT'}", flush=True)
    out = {"report": rep, "written": []}
    if not a.dry_run:
        source = f"funnel {a.run_id} (wfa {a.wfa_job_id or '-'}) {time.strftime('%Y-%m-%d')}"
        repo = os.path.abspath(os.path.join(alphas_dir(), "..", ".."))
        out["written"] = (write_explore_book(rep, os.path.join(alphas_dir(), "explore"), source=source, repo_dir=repo) if a.explore
                          else write_book(rep, alphas_dir(), source=source, repo_dir=repo))
        print("ghi:", out["written"], flush=True)
    write_job_result(out)
    return out
