"""Kiểm sổ chiến lược bằng Walk-Forward danh mục + Monte Carlo trên lợi suất ngày MTM (backend/studio_pipeline/portfolio_wfa.py).

Mỗi fold: IS chọn lại cấu hình của TỪNG chiến lược (top-K ứng viên), OOS chạy CẢ sổ chung vốn (kill switch bật, SL "level" và
"extreme"). Sau đó nối lợi suất ngày OOS (extreme) -> Monte Carlo 1 năm. Gate: xem hằng số đầu portfolio_wfa.py.

Nguồn ứng viên (chọn một):
  --report <thư mục lần chạy build_strategy_book>   đọc stage_a.json + report.json; top-N cấu hình mỗi chiến lược theo điểm dev1;
                                                     mặc định chỉ chiến lược ĐẠT trong report.json (--include-rejected: cả loại)
  --candidates id1,id2 --n K                        lấy mẫu K cấu hình mỗi chiến lược như build_strategy_book.configs(seed)
  --strategies-json <file>                          [{"id": ..., "configs": [{...}, ...]}] do người dùng chọn; DÙNG ĐÚNG các cấu hình
                                                     này (1 cấu hình mỗi chiến lược = tham số cố định, WFA chỉ kiểm OOS cuộn)
Cửa sổ mặc định: dev1_end -> dev2_end (từ report, hoặc windows() của build_strategy_book); --start/--end (YYYY-MM-DD) ghi đè.
Rủi ro mỗi lệnh: lấy từ report["book"] nếu có, không thì mức chuẩn 0,5% (--risk-per-trade ghi đè).

Dùng: scripts/run_limited.sh -- scripts/validate_book.py --candidates trend_long,reversion_short --n 3 --workers auto
Kết quả: <data>/_cache/book_wfa/<thời điểm>/report.json. BẮT BUỘC chạy dưới trần RAM (run_limited.sh).
"""
# ── Đặt TRƯỚC mọi import numpy/backend: tiến trình con kế thừa qua fork ──────
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import json
import shutil
import sys
import time
import warnings

import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import build_strategy_book as bsb  # noqa: E402  (windows, configs, PER_WORKER_MB, _dir_mb)
from backend.utils.jobresult import write_job_result  # noqa: E402
from backend.utils.jsonsafe import json_default  # noqa: E402


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
    from backend.alpha.strategy_book import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": bsb.configs(by_id[i], n, seed)} for i in ids]


def candidates_from_json(path):
    """Cấu hình do người dùng chọn: [{"id", "configs": [{tham số}]}] -> đúng như vậy (kiểm id/khoá tham số theo thư viện ứng viên)."""
    from backend.alpha.strategy_book import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list) or not raw:
        raise SystemExit("--strategies-json phải là danh sách JSON không rỗng")
    out, seen = [], set()
    for s in raw:
        cid, cfgs = s.get("id"), s.get("configs")
        if cid not in by_id or cid in seen:
            raise SystemExit(f"Chiến lược lạ hoặc bị lặp: {cid!r}; có: {sorted(by_id)}")
        if not isinstance(cfgs, list) or not cfgs or not all(isinstance(c, dict) for c in cfgs):
            raise SystemExit(f"{cid}: configs phải là danh sách không rỗng các dict tham số")
        bad = sorted({k for c in cfgs for k in c} - set(by_id[cid]["space"]))
        if bad:
            raise SystemExit(f"{cid}: khoá tham số không thuộc không gian tham số: {bad}")
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


def main(argv=None):
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="", help="thư mục lần chạy build_strategy_book (có stage_a.json + report.json)")
    ap.add_argument("--include-rejected", action="store_true", help="với --report: kiểm cả chiến lược bị loại")
    ap.add_argument("--candidates", default="", help="id chiến lược, phân tách bằng dấu phẩy (không dùng report)")
    ap.add_argument("--strategies-json", default="", help="file JSON [{id, configs:[...]}]: dùng đúng các cấu hình này (không report/candidates)")
    ap.add_argument("--symbols", default="", help="vd BTC@perp,SOL@perp (mặc định cả vũ trụ của sổ chiến lược)")
    ap.add_argument("--n", type=int, default=3, help="số cấu hình mỗi chiến lược (top-N theo report, hoặc lấy mẫu)")
    ap.add_argument("--seed", type=int, default=7, help="seed lấy mẫu cấu hình (--candidates)")
    ap.add_argument("--start", default="", help="YYYY-MM-DD (mặc định dev1_end)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD (mặc định dev2_end)")
    ap.add_argument("--train-days", type=int, default=120)
    ap.add_argument("--test-days", type=int, default=30)
    ap.add_argument("--step-days", type=int, default=None)
    ap.add_argument("--min-is-trades", type=int, default=10)
    ap.add_argument("--sims", type=int, default=4000, help="số lần mô phỏng Monte Carlo")
    ap.add_argument("--mc-seed", type=int, default=1)
    ap.add_argument("--risk-per-trade", type=float, default=None, help="%% vốn rủi ro mỗi lệnh (mặc định: report.book hoặc 0,5)")
    ap.add_argument("--workers", default="auto")
    ap.add_argument("--per-worker-mb", type=float, default=None)
    a = ap.parse_args(argv)
    if sum(map(bool, (a.report, a.candidates, a.strategies_json))) != 1:
        ap.error("chọn đúng một: --report, --candidates hoặc --strategies-json")

    from backend.utils.memwatch import check_memory_gate, require_memory_limit
    require_memory_limit("validate_book")
    from backend.alpha.strategy_book import BASE_RISK_PER_TRADE_PCT, RISK, perp_symbols
    from backend.db.data_layout import cache_dir
    from backend.studio_pipeline.portfolio_wfa import PortfolioWfaConfig, run_portfolio_wfa
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
        cands = (candidates_from_json(a.strategies_json) if a.strategies_json
                 else candidates_from_ids([c for c in a.candidates.split(",") if c], a.n, a.seed))
        w = bsb.windows(perp_symbols())
    symbols = [x if "@" in x else f"{x}@perp" for x in a.symbols.split(",") if x] or perp_symbols()
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if not cands:
        raise SystemExit("Không có chiến lược nào để kiểm (report không có chiến lược đạt? thử --include-rejected)")
    start = _ts(a.start) if a.start else w["dev1_end"]
    end = _ts(a.end) if a.end else w["dev2_end"]

    run_dir = cache_dir(None, "book_wfa", time.strftime("%Y%m%d_%H%M%S"))
    shared_dir = os.path.join(run_dir, "_shared")
    cfg = PortfolioWfaConfig(train_days=a.train_days, test_days=a.test_days, step_days=a.step_days,
                             min_is_trades=a.min_is_trades, mc_simulations=a.sims, mc_seed=a.mc_seed)
    print(f"chiến lược {[(c['id'], len(c['configs'])) for c in cands]} | workers={workers} | trần mỗi worker {per_worker_mb:.0f} MB", flush=True)
    t0 = time.time()
    res = run_portfolio_wfa(cands, symbols, start, end, cfg, risk, rpt, workers, shared_dir)
    res["source"] = {"report": os.path.abspath(a.report) if a.report else None, "include_rejected": a.include_rejected,
                     "strategies_json": bool(a.strategies_json),
                     "wall_s": round(time.time() - t0, 1)}
    if os.path.isdir(shared_dir):  # chạy xong thành công: dọn (lỗi thì không tới đây -> còn nguyên để gỡ lỗi)
        shutil.rmtree(shared_dir, ignore_errors=True)
    path = os.path.join(run_dir, "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=json_default)
    print_summary(res)
    print(f"thời gian {res['source']['wall_s']:.0f}s | báo cáo: {path}")
    write_job_result({**res, "report_path": path})  # chỉ khi chạy như job API (env NORA_JOB_DIR)
    return res


if __name__ == "__main__":
    main()
