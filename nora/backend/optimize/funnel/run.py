"""Job phễu kiểm duyệt alpha S0 → FINAL (POST /api/studio/funnel/runs -> api/jobs/runner.py -> run_job). Hợp đồng: docs/funnel_contract.md.
Kho: data/_cache/funnel/<run_id>/ (run.json, results.sqlite, trades/, daily/, mc/).

Tầng: S0 sinh alpha → S1 backtest dev1 → S2 chống ăn may (DSR / lân cận / PBO) → S3 walk-forward dev2 (tham số cố định) → S4 Monte Carlo →
S5 khối lượng sống sót (tìm s + xác nhận thật) → S6 holdout (một lần) → FINAL. Mọi dữ liệu thật: quality gate bắt buộc, không mock.

Tham số (DEFAULTS): strategies, space (grid | schema), timeframe (khung chạy 15m | 1h | 4h; mặc định 15m), n_per_strategy | full_grid, seed, symbols, windows, train_days, test_days, run_id, resume (run_id của lượt
bị ngắt: cấu hình lấy từ run.json), until (dừng sau tầng này), workers, per_worker_mb, max_alphas, force_large.
SIGTERM (nút Huỷ của API) -> flush lô đang ghi rồi thoát; resume tiếp tục đúng chỗ dừng.
"""
import json
import os
import warnings

from backend.utils.jobs import as_list, options, write_job_result

DEFAULTS = {"strategies": "", "n_per_strategy": None, "full_grid": False, "seed": 7, "symbols": "", "windows": None, "train_days": None,
            "test_days": None, "run_id": "", "resume": "", "until": "", "workers": "auto", "per_worker_mb": None, "max_alphas": 200_000,
            "force_large": False, "space": "grid", "timeframe": "15m"}


def run_job(params=None):
    """Chạy phễu với `params` (xem DEFAULTS) -> kết quả lượt chạy (cũng ghi $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    if a.n_per_strategy is not None and a.full_grid:
        raise ValueError("chọn một: n_per_strategy hoặc full_grid")
    from backend.utils.memwatch import check_memory_gate, require_memory_limit
    require_memory_limit("run_funnel")
    from backend.optimize.funnel import orchestrator as orch
    from backend.optimize.funnel.orchestrator import FunnelConfig
    from backend.utils.parallel import resolve_workers

    run_id = a.resume or a.run_id or orch.new_run_id()
    resume_dir = os.path.join(orch.funnel_root(), run_id)
    if a.resume and not os.path.isfile(os.path.join(resume_dir, "results.sqlite")):
        raise SystemExit(f"resume: {resume_dir} không có results.sqlite")
    saved = {}
    if a.resume:
        with open(os.path.join(resume_dir, "run.json"), encoding="utf-8") as fh:
            saved = json.load(fh).get("config", {})
    strategies = as_list(a.strategies) or list(saved.get("strategies", []))
    if not strategies:
        raise SystemExit("cần strategies (hoặc resume)")
    if not a.resume and a.n_per_strategy is None and not a.full_grid:
        raise SystemExit("cần n_per_strategy hoặc full_grid")
    cfg = FunnelConfig(
        strategies=strategies,
        n_per_strategy=a.n_per_strategy if not a.resume else saved.get("n_per_strategy"),
        full_grid=a.full_grid if not a.resume else bool(saved.get("full_grid")),
        seed=a.seed if not a.resume else saved.get("seed", a.seed),
        symbols=as_list(a.symbols) or saved.get("symbols"),
        windows=a.windows or saved.get("windows"),
        space=a.space if not a.resume else saved.get("space", "grid"),
        timeframe=a.timeframe if not a.resume else saved.get("timeframe", "1m"),
        **{k: v for k, v in (("train_days", a.train_days), ("test_days", a.test_days)) if v})
    orch.check_timeframe(cfg)
    planned = orch.planned_alphas(cfg)
    total = sum(planned.values())
    cap = 1_000_000 if a.force_large else a.max_alphas
    if total > cap:
        raise SystemExit(f"Từ chối: {total:,} alpha ({planned}) vượt max_alphas {cap:,}. Giảm n_per_strategy / số chiến lược hoặc đặt force_large (trần cứng 1.000.000).")

    from backend.core.strategy.book import perp_symbols
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit(cfg.symbols or perp_symbols())   # cổng chất lượng dữ liệu BẮT BUỘC, trước mọi việc khác và trước khi fork pool

    per_worker_mb = a.per_worker_mb or orch.PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "run_funnel")
    check_memory_gate(workers * per_worker_mb, f"run_funnel --workers {workers}")
    print(f"run_id {run_id} | {total:,} alpha {planned} | seed {cfg.seed} | workers={workers}", flush=True)
    res = orch.run_funnel(cfg, run_id=run_id, workers=workers, until=a.until or None, check_data=False, max_alphas=1_000_000)

    print(f"\n== Phễu {res['run_id']} ({res['status']}, {res['wall_s']:.0f}s) ==", flush=True)
    for c in res["counts"]:
        print(f"  {c['stage']:14s} vào {c['input']:>8,} | đã chấm {c['done']:>8,} | qua {c['passed']:>8,} | loại {c['rejected']:>8,}", flush=True)
    for fa in res["final_alphas"]:
        print(f"  FINAL {fa['alpha_id']} {fa['strategy']} s={fa['final_scale']} {json.dumps(fa['params'], ensure_ascii=False)}", flush=True)
    print(f"dung lượng kho {res['disk_bytes'] / 1048576:.1f} MB | {res['run_dir']}", flush=True)
    write_job_result({k: res[k] for k in ("run_id", "run_dir", "status", "counts", "final_alphas", "disk_bytes", "wall_s")})   # chỉ khi chạy như job API
    return res
