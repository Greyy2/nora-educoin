"""Job WFA danh mục (POST /api/studio/book/wfa -> api/jobs/runner.py -> run_job): Walk-Forward cả sổ + Monte Carlo lợi suất ngày MTM.

Mỗi fold: IS chọn lại cấu hình của TỪNG chiến lược (top-K ứng viên), OOS chạy CẢ sổ chung vốn (kill switch bật, SL "level" và
"extreme"). Sau đó nối lợi suất ngày OOS (extreme) -> Monte Carlo 1 năm. Gate: xem hằng số đầu walk_forward.py.

Nguồn ứng viên (chọn một tham số):
  report       thư mục lần dựng sổ (optimize/book.py): top-N cấu hình mỗi chiến lược theo điểm dev1; mặc định chỉ chiến lược ĐẠT
               (include_rejected=True: cả loại)
  candidates   "id1,id2" hoặc [id...]: lấy mẫu n cấu hình mỗi chiến lược như optimize.book.configs(seed)
  strategies   [{"id": ..., "configs": [{...}, ...]}] do người dùng chọn; DÙNG ĐÚNG các cấu hình này
Cửa sổ mặc định: dev1_end -> dev2_end; start/end (YYYY-MM-DD) ghi đè. Rủi ro/lệnh: report["book"] hoặc 0,5% (risk_per_trade ghi đè).
regime "learn": mỗi fold học bảng regime ↔ chiến lược trên train (core/regime/learn.py) rồi áp lên OOS; "off" (mặc định): không lọc.
Kết quả: <data>/_cache/book_wfa/<thời điểm>/report.json + $NORA_JOB_DIR/result.json.
"""
# ── Đặt TRƯỚC mọi import numpy/backend: tiến trình con kế thừa qua fork ──────
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")
# ─────────────────────────────────────────────────────────────────────────────

import itertools
import json
import shutil
import time
import warnings

import pandas as pd

from backend.optimize import book as bsb   # windows, configs, PER_WORKER_MB
from backend.utils.jobs import as_list, options, write_job_result
from backend.utils.jsonsafe import json_default

DEFAULTS = {"report": "", "include_rejected": False, "candidates": "", "strategies": None, "symbols": "", "n": 3, "seed": 7,
            "start": "", "end": "", "train_days": 120, "test_days": 30, "step_days": None, "min_is_trades": 10, "sims": 10_000,
            "mc_seed": 1, "timeframe": "1m", "regime": "off", "risk_per_trade": None, "workers": "auto", "per_worker_mb": None, "resume": "", "max_configs": 200_000,
            "force_large": False}


def _ts(date_str):
    return int(pd.Timestamp(date_str, tz="UTC").value // 1_000_000)


def load_report(report_dir):
    """(stage_a, report) từ thư mục lần chạy build_strategy_book."""
    with open(os.path.join(report_dir, "stage_a.json"), encoding="utf-8") as fh:
        stage_a = json.load(fh)
    with open(os.path.join(report_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    return stage_a, report


def candidates_from_report(stage_a, report, n, include_rejected, only=None):
    """Top-n cấu hình (điểm dev1 cao nhất, bỏ điểm -inf) mỗi chiến lược; mặc định chỉ chiến lược ĐẠT."""
    out = []
    for cid, rows in stage_a.items():
        if only and cid not in only:
            continue
        accepted = (report.get("candidates", {}).get(cid) or {}).get("accepted")
        if not include_rejected and not (accepted is True or accepted == "True"):  # báo cáo cũ lưu chuỗi 'False' (default=str)
            continue
        ranked = sorted((r for r in rows if r["score"] is not None and r["score"] > float("-inf")), key=lambda r: -r["score"])
        if ranked:
            out.append({"id": cid, "configs": [r["params"] for r in ranked[:n]]})
    return out


def candidates_from_ids(ids, n, seed):
    from backend.core.strategy.book import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": bsb.configs(by_id[i], n, seed)} for i in ids]


def candidates_from_list(raw):
    """Cấu hình do người dùng chọn: [{"id", "configs": [{tham số}]}] -> đúng như vậy (kiểm id/khoá tham số theo `space` + `params_schema`)."""
    from backend.core.strategy.book import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
    if not isinstance(raw, list) or not raw:
        raise SystemExit("strategies phải là danh sách không rỗng")
    out, seen = [], set()
    for s in raw:
        cid, cfgs = s.get("id"), s.get("configs")
        if cid not in by_id or cid in seen:
            raise SystemExit(f"Chiến lược lạ hoặc bị lặp: {cid!r}; có: {sorted(by_id)}")
        if not isinstance(cfgs, list) or not cfgs or not all(isinstance(c, dict) for c in cfgs):
            raise SystemExit(f"{cid}: configs phải là danh sách không rỗng các dict tham số")
        bad = sorted({k for c in cfgs for k in c} - set(by_id[cid]["space"]) - set(by_id[cid].get("params_schema") or {}))
        if bad:
            raise SystemExit(f"{cid}: khoá tham số không thuộc không gian tham số / lược đồ tham số: {bad}")
        seen.add(cid)
        out.append({"id": cid, "configs": cfgs})
    return out


def print_summary(res):
    s, g = res["summary"], res["gate"]
    print(f"\ncửa sổ {res['window'][0]} → {res['window'][1]} | train {res['config']['train_days']}d test {res['config']['test_days']}d "
          f"| rủi ro/lệnh {res['risk_per_trade_pct']}% | {s['n_folds']} fold")
    print(f"{'#':>2} {'train':23s} {'test':23s} {'IS%':>7} {'OOSlv%':>7} {'OOSex%':>7} {'MDDex':>6} {'lệnh':>5} {'kill':>4}  chọn")
    for f in res["folds"]:
        ex, lv = f["oos_extreme"], f["oos_level"]
        pick = ",".join(f"{cid}#{i}" for cid, i in f["chosen_idx"].items() if i is not None) or "-"
        print(f"{f['fold']:>2} {f['train'][0]}→{f['train'][1]:10s} {f['test'][0]}→{f['test'][1]:10s} {f['is_ret_pct']:7.2f} "
              f"{(lv['ret_pct'] if lv else 0.0):7.2f} {(ex['ret_pct'] if ex else 0.0):7.2f} {(ex['mdd_pct'] if ex else 0.0):6.2f} "
              f"{f['trades']['extreme']:5d} {'có' if f['halted_at']['extreme'] else '-':>4}  {pick}")
    print("ổn định tham số: " + "; ".join(f"{cid} {v['share'] * 100:.0f}% ({v['distinct']} cấu hình/{v['folds_chosen']} fold)"
                                          for cid, v in s["param_stability"].items()))
    c, w = s["compounded_oos_ret_pct"], s["worst_fold_mdd_pct"]
    print(f"OOS lãi kép: level {c['level']}% | extreme {c['extreme']}% | MDD fold tệ nhất: level {w['level']}% | extreme {w['extreme']}% "
          f"| {s['oos_days']} ngày, lệnh {s['oos_trades']['extreme']}")
    mc = s["mc"]
    if mc:
        print(f"MC {mc['simulations']}×{mc['horizon_days']}d (block {mc['block_days']}, ngày MTM extreme): lãi trung vị {mc['median_ret_pct']}%, "
              f"p05 {mc['p05_ret_pct']}%, MDD p50 {mc['mdd_p50_pct']}% / p95 {mc['mdd_p95_pct']}%, P(MDD>=30%) {mc['p_mdd_ge_ruin_pct']}%")
    else:
        print("MC: không đủ ngày OOS")
    print("GATE: " + ("ĐẠT" if g["passed"] else "KHÔNG ĐẠT"))
    for c in g["checks"].values():
        print(f"  [{'ok' if c['passed'] else 'XX'}] {c['label']}: {c['actual']} (cần {c['required']})")
    m = res["mem"]
    print(f"đỉnh RAM/worker {m['peak_rss_mb']:.0f} MB (riêng {m['rss_anon_mb']:.0f} MB + mmap dùng chung)", flush=True)


def run_job(params=None):
    """Chạy job WFA với `params` (xem docstring module) -> báo cáo (cũng ghi report.json + $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    if sum(map(bool, (a.report, a.candidates, a.strategies))) != 1:
        raise ValueError("chọn đúng một: report, candidates hoặc strategies")

    from backend.utils.memwatch import check_memory_gate, require_memory_limit
    require_memory_limit("validate_book")
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, RISK, perp_symbols
    from backend.db.data_layout import cache_dir
    from backend.wfa.walk_forward import PortfolioWfaConfig, run_portfolio_wfa
    from backend.utils.parallel import resolve_workers

    per_worker_mb = a.per_worker_mb or bsb.PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "validate_book")
    check_memory_gate(workers * per_worker_mb, f"validate_book --workers {workers}")

    risk, rpt, report = RISK, BASE_RISK_PER_TRADE_PCT, None
    if a.report:
        stage_a, report = load_report(a.report)
        cands = candidates_from_report(stage_a, report, a.n, a.include_rejected)
        risk = report.get("risk") or RISK
        rpt = ((report.get("book") or {}).get("risk_per_trade_pct")) or rpt
        w = {k: _ts(v) for k, v in report["windows"].items()}
    else:
        cands = (candidates_from_list(a.strategies) if a.strategies
                 else candidates_from_ids(as_list(a.candidates), a.n, a.seed))
        w = bsb.windows(perp_symbols())
    symbols = [x if "@" in x else f"{x}@perp" for x in as_list(a.symbols)] or perp_symbols()
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (trước khi fork pool để worker thừa kế cache gate)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if not cands:
        raise SystemExit("Không có chiến lược nào để kiểm (report không có chiến lược đạt? thử include_rejected)")
    start = _ts(a.start) if a.start else w["dev1_end"]
    end = _ts(a.end) if a.end else w["dev2_end"]

    from backend.utils.jobs import Progress, graceful_sigterm
    from backend.optimize.store import ResultsStore
    from backend.wfa import walk_forward as pw
    from backend.wfa.walk_forward import generate_folds

    # Ước lượng + trần số job TRƯỚC khi chạy: IS = fold × tổng số cấu hình; OOS = 2 × fold
    folds = generate_folds(int(start), int(end), a.train_days, a.test_days, a.step_days)
    n_cfg = sum(len(c["configs"]) for c in cands)
    is_total = len(folds) * n_cfg
    if is_total > a.max_configs and not a.force_large:
        raise SystemExit(f"Từ chối: {is_total:,} job IS ({len(folds)} fold × {n_cfg} cấu hình) vượt max_configs {a.max_configs:,}. "
                         f"Giảm n / số chiến lược hoặc đặt force_large.")
    if a.resume:
        run_dir = os.path.abspath(a.resume if os.path.isabs(a.resume) or os.path.isdir(a.resume)
                                  else os.path.join(cache_dir(None, "book_wfa"), a.resume))
        if not os.path.isfile(os.path.join(run_dir, "results.sqlite")):
            raise SystemExit(f"resume: {run_dir} không có results.sqlite")
    else:
        base = time.strftime("%Y%m%d_%H%M%S")
        for k in itertools.count(1):
            run_dir = cache_dir(None, "book_wfa", base if k == 1 else f"{base}_{k}")
            if not os.path.exists(os.path.join(run_dir, "results.sqlite")):
                break
    shared_dir = os.path.join(run_dir, "_shared")
    cfg = PortfolioWfaConfig(train_days=a.train_days, test_days=a.test_days, step_days=a.step_days,
                             min_is_trades=a.min_is_trades, mc_simulations=a.sims, mc_seed=a.mc_seed)
    print(f"chiến lược {[(c['id'], len(c['configs'])) for c in cands]} | workers={workers} | trần mỗi worker {per_worker_mb:.0f} MB", flush=True)
    store = ResultsStore(run_dir)
    progress = Progress(run_dir)
    t0 = time.time()
    try:
        with graceful_sigterm(progress):
            if a.resume:
                print(f"[resume] {run_dir}: kho đã có {store.count():,} kết quả", flush=True)
            # Hiệu chỉnh: chạy 1 job IS đầu (1 worker, ghi vào kho như job thường) -> ước lượng thời gian
            os.makedirs(shared_dir, exist_ok=True)
            _, is_jobs0 = pw.plan_is_jobs(cands, folds, symbols, risk, rpt, shared_dir, a.timeframe or "1m")
            t_cal = time.time()
            pw._pool_shared(is_jobs0[:1], 1, "[WFA] hiệu chỉnh", shared_dir, store, "wfa_is", None)
            sec = time.time() - t_cal
            n_jobs = is_total + 2 * len(folds)
            est = {"is_jobs": is_total, "oos_jobs": 2 * len(folds), "sec_per_job": round(sec, 3), "workers": workers,
                   "eta_s": round(n_jobs * sec / workers, 1)}
            print(f"[estimate] {n_jobs:,} job ({is_total:,} IS + {2 * len(folds)} OOS) × {sec:.1f} s/job / {workers} worker ≈ "
                  f"{est['eta_s'] / 60:.1f} phút", flush=True)
            with open(os.path.join(run_dir, "estimate.json"), "w", encoding="utf-8") as fh:
                json.dump(est, fh, ensure_ascii=False, indent=1)
            progress.set_estimate(est)
            res = run_portfolio_wfa(cands, symbols, start, end, cfg, risk, rpt, workers, shared_dir, store=store, progress=progress,
                                    base_frame=a.timeframe or "1m", regime=a.regime or "off")
            res["source"] = {"report": os.path.abspath(a.report) if a.report else None, "include_rejected": a.include_rejected,
                             "strategies": bool(a.strategies),
                             "wall_s": round(time.time() - t0, 1)}
            if os.path.isdir(shared_dir):  # chạy xong thành công: dọn (lỗi thì không tới đây -> còn nguyên để gỡ lỗi)
                shutil.rmtree(shared_dir, ignore_errors=True)
            path = os.path.join(run_dir, "report.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1, default=json_default)
            print_summary(res)
            print(f"thời gian {res['source']['wall_s']:.0f}s | báo cáo: {path}")
            store.flush()
            progress.finish("done")
            write_job_result({**res, "report_path": path})  # chỉ khi chạy như job API (env NORA_JOB_DIR)
    finally:
        store.close()   # flush lô ghi cuối (cả khi SIGTERM/ngoại lệ) -> --resume dùng được
    return res
