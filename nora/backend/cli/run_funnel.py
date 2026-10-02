"""Phễu kiểm duyệt alpha S0 → FINAL (hợp đồng: docs/funnel_contract.md). Kho: data/_cache/funnel/<run_id>/ (run.json, results.sqlite, trades/, daily/, mc/).

Tầng: S0 sinh alpha → S1 backtest dev1 → S2 chống ăn may (DSR / lân cận / PBO) → S3 walk-forward dev2 (tham số cố định) → S4 Monte Carlo →
S5 khối lượng sống sót (tìm s + xác nhận thật) → S6 holdout (một lần) → FINAL. Mọi dữ liệu thật: quality gate bắt buộc, không mock.

Dùng (BẮT BUỘC dưới trần RAM):
  backend/ops/run_limited.sh -- -m backend.cli.run_funnel --strategies breakout_4h_long,trend_long --n-per-strategy 200 --seed 7
  backend/ops/run_limited.sh -- -m backend.cli.run_funnel --strategies trend_long --full-grid
  backend/ops/run_limited.sh -- -m backend.cli.run_funnel --resume fr-20261002-ab12cd          # chạy tiếp lượt bị ngắt (cùng cấu hình)
Đối số theo body của POST /api/studio/funnel/runs: strategies, n_per_strategy | full_grid, seed, symbols, windows (--windows-json), resume.
  --until <tầng>   dừng sau tầng này (vd. S2_antiluck); chạy tiếp sau bằng --resume.
SIGTERM (nút Huỷ của API) -> flush lô đang ghi rồi thoát; --resume tiếp tục đúng chỗ dừng.
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import argparse
import json
import sys
import time
import warnings

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Phễu kiểm duyệt alpha S0 → FINAL")
    ap.add_argument("--strategies", default="", help="id chiến lược, phân tách bằng dấu phẩy (strategy_book.CANDIDATES)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--n-per-strategy", type=int, default=None, help="số alpha mỗi chiến lược (lấy mẫu ngẫu nhiên theo --seed)")
    g.add_argument("--full-grid", action="store_true", help="toàn bộ lưới tham số của mỗi chiến lược")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--symbols", default="", help="vd BTC@perp,ETH@perp (mặc định cả vũ trụ)")
    ap.add_argument("--windows-json", default="", help='ghi đè mốc: {"start":"YYYY-MM-DD","dev1_end":...,"dev2_end":...,"end":...}')
    ap.add_argument("--train-days", type=int, default=None)
    ap.add_argument("--test-days", type=int, default=None)
    ap.add_argument("--run-id", default="", help="đặt run_id (API truyền vào); mặc định tự sinh")
    ap.add_argument("--resume", default="", help="run_id của lượt bị ngắt: chạy tiếp (cấu hình lấy từ run.json)")
    ap.add_argument("--until", default="", help="dừng sau tầng này")
    ap.add_argument("--workers", default="auto")
    ap.add_argument("--per-worker-mb", type=float, default=None)
    ap.add_argument("--max-alphas", type=int, default=200_000, help="từ chối khi tổng số alpha vượt ngưỡng (trừ --force-large; trần cứng 1.000.000)")
    ap.add_argument("--force-large", action="store_true")
    return ap


def main(argv=None):
    warnings.filterwarnings("ignore")
    a = build_parser().parse_args(argv)
    from backend.utils.memwatch import check_memory_gate, require_memory_limit
    require_memory_limit("run_funnel")
    from backend.funnel import orchestrator as orch
    from backend.funnel.orchestrator import FunnelConfig
    from backend.utils.parallel import resolve_workers

    run_id = a.resume or a.run_id or orch.new_run_id()
    resume_dir = os.path.join(orch.funnel_root(), run_id)
    if a.resume and not os.path.isfile(os.path.join(resume_dir, "results.sqlite")):
        raise SystemExit(f"--resume: {resume_dir} không có results.sqlite")
    saved = {}
    if a.resume:
        with open(os.path.join(resume_dir, "run.json"), encoding="utf-8") as fh:
            saved = json.load(fh).get("config", {})
    strategies = [s for s in (a.strategies.split(",") if a.strategies else saved.get("strategies", [])) if s]
    if not strategies:
        raise SystemExit("cần --strategies (hoặc --resume)")
    if not a.resume and a.n_per_strategy is None and not a.full_grid:
        raise SystemExit("cần --n-per-strategy N hoặc --full-grid")
    cfg = FunnelConfig(
        strategies=strategies,
        n_per_strategy=a.n_per_strategy if not a.resume else saved.get("n_per_strategy"),
        full_grid=a.full_grid if not a.resume else bool(saved.get("full_grid")),
        seed=a.seed if not a.resume else saved.get("seed", a.seed),
        symbols=[x for x in a.symbols.split(",") if x] or saved.get("symbols"),
        windows=json.loads(a.windows_json) if a.windows_json else saved.get("windows"),
        **{k: v for k, v in (("train_days", a.train_days), ("test_days", a.test_days)) if v})
    planned = orch.planned_alphas(cfg)
    total = sum(planned.values())
    cap = 1_000_000 if a.force_large else a.max_alphas
    if total > cap:
        raise SystemExit(f"Từ chối: {total:,} alpha ({planned}) vượt --max-alphas {cap:,}. Giảm --n-per-strategy / số chiến lược hoặc thêm --force-large (trần cứng 1.000.000).")

    from backend.core.strategy.strategy_book import perp_symbols
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit(cfg.symbols or perp_symbols())   # cổng chất lượng dữ liệu BẮT BUỘC, trước mọi việc khác và trước khi fork pool

    per_worker_mb = a.per_worker_mb or orch.PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "run_funnel")
    check_memory_gate(workers * per_worker_mb, f"run_funnel --workers {workers}")
    print(f"run_id {run_id} | {total:,} alpha {planned} | seed {cfg.seed} | workers={workers}", flush=True)
    t0 = time.time()
    res = orch.run_funnel(cfg, run_id=run_id, workers=workers, until=a.until or None, check_data=False, max_alphas=1_000_000)

    print(f"\n== Phễu {res['run_id']} ({res['status']}, {res['wall_s']:.0f}s) ==", flush=True)
    for c in res["counts"]:
        print(f"  {c['stage']:14s} vào {c['input']:>8,} | đã chấm {c['done']:>8,} | qua {c['passed']:>8,} | loại {c['rejected']:>8,}", flush=True)
    for fa in res["final_alphas"]:
        print(f"  FINAL {fa['alpha_id']} {fa['strategy']} s={fa['final_scale']} {json.dumps(fa['params'], ensure_ascii=False)}", flush=True)
    print(f"dung lượng kho {res['disk_bytes'] / 1048576:.1f} MB | {res['run_dir']}", flush=True)
    from backend.utils.jobresult import write_job_result
    write_job_result({k: res[k] for k in ("run_id", "run_dir", "status", "counts", "final_alphas", "disk_bytes", "wall_s")})   # chỉ khi chạy như job API
    return res


if __name__ == "__main__":
    main()
