"""Điều phối phễu S0 → FINAL: tầng chạy TUẦN TỰ, mỗi tầng STREAMING (job sinh lười -> pool_imap_bounded -> lô kết quả ghi ngay vào kho).

- RAM cha phẳng: chỉ giữ một lô (FLUSH_N alpha) + các trang `pending` (1000 hàng); worker trả dict thuần dữ liệu.
- RESUME theo run_id: kho là sổ cam kết (xem storage.py). Chạy lại = mỗi tầng chỉ chấm alpha chưa có hàng stage_metrics của tầng đó.
- S2 là tầng CHÉO alpha: số liệu mức chiến lược (N lần thử, phương sai Sharpe, PBO) tính một lần/chiến lược và lưu vào bảng kv (resume không tính lại).
- Tiến độ/ETA: backend.optimize.progress.Progress (progress.json mỗi <= 5 giây, cũng ghi vào $NORA_JOB_DIR để API hiển thị).
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from backend.optimize.progress import Progress, graceful_sigterm

from . import antiluck, backtest as bt, gates, sizing
from .generate import alpha_id_of, count_params, iter_params, validate_alpha
from .storage import RunStore, StageResult
from .windows import compute_windows, windows_iso, wfa_folds

PER_WORKER_MB = 800            # như build_strategy_book (đo thực, dữ liệu dùng chung qua mmap)
GEN_BATCH = 5000               # alpha ghi mỗi giao dịch ở S0
PAGE = 1000                    # số alpha nạp mỗi lần từ `pending`
S2_CHUNK = 2000                # số alpha S2 xử lý mỗi lượt (bộ nhớ + gom điểm lân cận cần chạy)
FLUSH_SECONDS = 20.0
FLUSH_N = {"S1_backtest": 200, "S2_antiluck": 2000, "S3_wfa": 8, "S4_montecarlo": 16, "S5_sizing": 4, "S6_holdout": 8, "FINAL": 2000}
MAX_ALPHAS_DEFAULT = 1_000_000


@dataclass
class FunnelConfig:
    strategies: List[str]
    n_per_strategy: Optional[int] = None
    full_grid: bool = False
    seed: int = 7
    symbols: Optional[List[str]] = None            # mặc định cả vũ trụ (perp)
    windows: Optional[Dict[str, str]] = None       # ghi đè mốc YYYY-MM-DD: start, dev1_end, dev2_end, end
    train_days: int = gates.S3_TRAIN_DAYS
    test_days: int = gates.S3_TEST_DAYS

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def new_run_id() -> str:
    import uuid
    return f"fr-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def funnel_root() -> str:
    from backend.db.data_layout import cache_dir
    return cache_dir(None, "funnel")


def git_info() -> Dict[str, Any]:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", root, "status", "--porcelain", "backend"], capture_output=True, text=True, timeout=10).stdout.strip())
        return {"commit": head or None, "dirty_backend": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty_backend": None}


def _candidates(strategies: List[str]) -> Dict[str, Dict[str, Any]]:
    from backend.core.strategy import strategy_book as sb
    by_id = {c["id"]: c for c in sb.CANDIDATES}
    bad = [s for s in strategies if s not in by_id]
    if bad:
        raise ValueError(f"không có chiến lược {bad}; có: {sorted(by_id)}")
    return {s: by_id[s] for s in strategies}


def planned_alphas(cfg: FunnelConfig) -> Dict[str, int]:
    cands = _candidates(cfg.strategies)
    return {s: count_params(c["space"], cfg.n_per_strategy, cfg.full_grid) for s, c in cands.items()}


# ── Bối cảnh chạy ───────────────────────────────────────────────────────────
class Ctx:
    def __init__(self, store: RunStore, cfg: FunnelConfig, windows: Dict[str, int], workers: int, progress: Progress, log: Callable[[str], None]):
        self.store, self.cfg, self.windows, self.workers, self.progress, self.log = store, cfg, windows, workers, progress, log
        self.serial = workers <= 0
        self.shared_dir = None if self.serial else os.path.join(store.run_dir, "_shared")
        self.symbols = list(cfg.symbols)
        self.cands = _candidates(cfg.strategies)
        self.exporter = bt.SharedExporter(self.shared_dir, workers, "funnel")
        self.folds = bt.fold_job_plan(wfa_folds(windows, cfg.train_days, cfg.test_days))

    def imap(self, fn: Callable, jobs: Iterable, label: str) -> Iterator[Tuple[int, Any]]:
        if self.serial:
            return ((i, fn(j)) for i, j in enumerate(jobs))
        from backend.utils.parallel import pool_imap_bounded
        return pool_imap_bounded(fn, jobs, self.workers, label, self.workers * 4)

    def s1_job(self, strategy: str, params: Dict[str, Any], rpt: float = gates.BASE_RISK_PER_TRADE_PCT, trades: Any = False) -> Dict[str, Any]:
        w = self.windows
        return {**bt.base_job(strategy, params, (w["start"], w["dev1_end"]), "level", False, rpt, self.symbols, self.shared_dir), "trades": trades}

    def tick(self) -> None:
        self.progress.tick()


def _stream(ctx: Ctx, stage: str, pages: Iterator[Dict[str, Any]], make_job: Callable[[Dict[str, Any]], Dict[str, Any]], fn: Callable,
            on_result: Callable[[Dict[str, Any], Any], StageResult], neighbours: bool = False) -> int:
    """Khung dùng chung: `pages` yield hàng alpha (lười) -> job -> pool -> on_result -> lô -> commit. -> số alpha đã chấm."""
    pending: Dict[int, Dict[str, Any]] = {}
    batch: List[StageResult] = []
    flush_n = FLUSH_N.get(stage, 100)
    t_flush = time.time()
    t_log = time.time()
    done = 0

    def feeder():
        for n, row in enumerate(pages):
            pending[n] = row
            yield make_job(row)

    for i, res in ctx.imap(fn, feeder(), f"[{stage}]"):
        row = pending.pop(i)
        batch.append(on_result(row, res))
        done += 1
        ctx.tick()
        if len(batch) >= flush_n or time.time() - t_flush > FLUSH_SECONDS:
            ctx.store.commit_results(batch, neighbours=neighbours)
            batch, t_flush = [], time.time()
        if time.time() - t_log > 30:
            snap = ctx.progress.snapshot()
            ctx.log(f"[{stage}] {snap['done']}/{snap['total']}  ETA {_fmt_eta(snap.get('eta_s'))}")
            t_log = time.time()
    if batch:
        ctx.store.commit_results(batch, neighbours=neighbours)
    return done


def _fmt_eta(s: Optional[float]) -> str:
    if s is None:
        return "?"
    return f"{s:.0f}s" if s < 90 else (f"{s / 60:.1f} phút" if s < 5400 else f"{s / 3600:.1f} giờ")


def _pages(store: RunStore, prev_idx: int, strategy: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    last = -1
    while True:
        rows = store.pending(prev_idx, strategy, after_ord=last, limit=PAGE)
        if not rows:
            return
        for r in rows:
            yield r
        last = rows[-1]["ord"]


def _scalar_base(m: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("ret_pct", "mdd_pct", "sharpe", "sortino", "trades", "win_rate", "profit_factor", "symbols_positive")
    return {k: m[k] for k in keys if k in m}


# ── Từng tầng ───────────────────────────────────────────────────────────────
def stage_s0(ctx: Ctx) -> None:
    store, cfg = ctx.store, ctx.cfg
    total = sum(planned_alphas(cfg).values())
    ctx.progress.start_stage("S0_generate", total)
    ord_ = 0
    buf: List[Dict[str, Any]] = []
    bad = 0
    for strategy in cfg.strategies:
        cand = ctx.cands[strategy]
        for params in iter_params(cand["space"], cfg.n_per_strategy, cfg.seed, cfg.full_grid):
            err = validate_alpha(cand, params)
            row = {"alpha_id": alpha_id_of(strategy, params), "strategy": strategy, "params": params, "ord": ord_}
            if err:
                row.update(reject_code="S0.invalid_params", reject_msg=f"S0.invalid_params: {gates.reason_label('S0.invalid_params')} ({err})")
                bad += 1
            buf.append(row)
            ord_ += 1
            if len(buf) >= GEN_BATCH:
                store.add_alphas(buf)
                ctx.progress.tick(len(buf))
                buf = []
    if buf:
        store.add_alphas(buf)
        ctx.progress.tick(len(buf))
    ctx.log(f"[S0_generate] {ord_} alpha ({bad} không hợp lệ)")


def stage_s1(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S1_backtest", store.count_pending(0))
    reps = []
    for s in ctx.cfg.strategies:
        r = store.pending(0, s, limit=1)
        if r:
            reps.append(ctx.s1_job(s, r[0]["params"]))
    ctx.exporter.ensure(reps)

    def on_result(row, res):
        if "error" in res:
            return StageResult(row["alpha_id"], "S1_backtest", {"error": res["error"]}, False, "S1.error",
                               f"S1.error: {gates.reason_label('S1.error')} ({res['error']})")
        m = res["metrics"]
        ok, code, msg = gates.evaluate_s1(m)
        daily = [("S1_backtest", [{"fold": None, "start": res["daily_start"], "rets": res["daily"]}])]
        trades = [("S1_backtest", res["trades"])] if ok and res["trades"] is not None else []
        return StageResult(row["alpha_id"], "S1_backtest", m, ok, code, msg, trades=trades, daily=daily)

    _stream(ctx, "S1_backtest", _pages(store, 0), lambda r: ctx.s1_job(r["strategy"], r["params"], trades="pass"), bt.w_backtest, on_result)
    # KHÔNG dọn dữ liệu dùng chung ở đây: S2 chạy các điểm lân cận trên cùng cửa sổ dev1 (S2 dọn).


def _s2_strategy_level(ctx: Ctx, strategy: str) -> Dict[str, Any]:
    """N lần thử, phương sai Sharpe các lần thử và PBO (CSCV) của chiến lược — tính từ MỌI alpha đã qua S0 và chạy xong S1 (cả alpha bị loại ở S1)."""
    store = ctx.store
    key = f"s2:{strategy}"
    cached = store.get_kv(key)
    if cached is not None:
        return cached
    srs = [m["sr_daily"] for _, _, m, _ in store.iter_stage_metrics("S1_backtest", strategy) if "sr_daily" in m]
    info: Dict[str, Any] = {"n_trials": len(srs), "sr_var": antiluck.trial_sr_variance(srs), "pbo": None, "pbo_alphas": 0, "pbo_days": 0}
    ids = store.top_by_score("S1_backtest", strategy, gates.S2_PBO_MAX_ALPHAS)
    if len(ids) >= gates.S2_PBO_MIN_ALPHAS:
        daily = store.read_daily_many(ids, "S1_backtest")
        series = [{"start": rows[0]["start_date"], "rets": rows[0]["rets"]} for a in ids for rows in [daily.get(a)] if rows]
        if len(series) >= gates.S2_PBO_MIN_ALPHAS:
            r = antiluck.pbo_cscv(antiluck.align_daily(series), gates.S2_PBO_BLOCKS)
            info.update(pbo=r["pbo"], pbo_alphas=r["n_alphas"], pbo_days=r["n_days"], pbo_logit_median=r["logit_median"], pbo_splits=r["n_splits"])
    info["flag"] = bool(info["pbo"] is not None and info["pbo"] > gates.S2_PBO_MAX)
    store.set_kv(key, info)
    ctx.log(f"[S2_antiluck] {strategy}: N={info['n_trials']} sr_var={info['sr_var']:.2e} PBO={info['pbo']}")
    return info


def stage_s2(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S2_antiluck", store.count_pending(1))
    t_log = time.time()
    for strategy in store.strategies_at(1):
        cand = ctx.cands[strategy]
        info = _s2_strategy_level(ctx, strategy)
        while True:
            chunk = store.pending(1, strategy, after_ord=-1, limit=S2_CHUNK)
            if not chunk:
                break
            ids = [r["alpha_id"] for r in chunk]
            m1 = store.metrics_of(ids, "S1_backtest")
            ev: Dict[str, Dict[str, Any]] = {}
            for r in chunk:
                m = m1[r["alpha_id"]]
                d = antiluck.deflated_sharpe(m["sr_daily"], m["n_days"], m["skew"], m["kurt"], info["n_trials"], info["sr_var"])
                ev[r["alpha_id"]] = {"dsr": d["dsr"], "sr0": d["sr0"]}
            # điểm lân cận: chỉ cho alpha còn sống sau PBO + DSR (tiết kiệm backtest)
            survivors = [r for r in chunk if not info["flag"] and ev[r["alpha_id"]]["dsr"] >= gates.S2_DSR_MIN]
            nb_ratio = _neighbour_ratios(ctx, strategy, cand, survivors)
            results = []
            for r in chunk:
                a = r["alpha_id"]
                nb = nb_ratio.get(a)
                ratio, n_nb = (nb if nb else (None, 0))
                ok, code, msg = gates.evaluate_s2(ev[a]["dsr"], ratio, info["pbo"])
                m = {**_scalar_base(m1[a]), "dsr": round(ev[a]["dsr"], 4), "dsr_sr0": round(ev[a]["sr0"], 6), "neighbor_ratio": ratio,
                     "neighbor_n": n_nb, "pbo_strategy": info["pbo"], "pbo_flag": info["flag"], "n_trials": info["n_trials"]}
                results.append(StageResult(a, "S2_antiluck", m, ok, code, msg))
                ctx.tick()
            store.commit_results(results)
            if time.time() - t_log > 30:
                snap = ctx.progress.snapshot()
                ctx.log(f"[S2_antiluck] {snap['done']}/{snap['total']}  ETA {_fmt_eta(snap.get('eta_s'))}")
                t_log = time.time()
    ctx.exporter.cleanup()


def _neighbour_ratios(ctx: Ctx, strategy: str, cand: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Tuple[Optional[float], int]]:
    """{alpha_id: (tỉ lệ điểm lân cận có lãi (ret_pct > 0) hoặc None nếu không có lân cận, số lân cận hợp lệ)}.
    Kết quả S1 đã lưu (kể cả điểm bị loại ở S1) được dùng lại; điểm chưa có -> chạy backtest dev1 (như S1) và GHI vào stage_metrics['S2_neighbour']."""
    store = ctx.store
    plan: Dict[str, List[str]] = {}
    nb_params: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ids = []
        for p in antiluck.neighbours(cand["space"], r["params"]):
            nid = alpha_id_of(strategy, p)
            nb_params[nid] = p
            ids.append(nid)
        plan[r["alpha_id"]] = ids
    all_ids = sorted(nb_params)
    known = store.metrics_of(all_ids, "S1_backtest")
    known_nb = store.metrics_of([i for i in all_ids if i not in known], "S2_neighbour")
    missing = [i for i in all_ids if i not in known and i not in known_nb and validate_alpha(cand, nb_params[i]) is None]
    if missing:
        ctx.exporter.ensure([ctx.s1_job(strategy, nb_params[missing[0]])])
        got: List[StageResult] = []
        jobs = [ctx.s1_job(strategy, nb_params[i]) for i in missing]
        for i, res in ctx.imap(bt.w_backtest, iter(jobs), "[S2 lân cận]"):
            m = {"error": res["error"]} if "error" in res else res["metrics"]
            got.append(StageResult(missing[i], gates.NEIGHBOUR_STAGE, {**m, "strategy": strategy, "params": nb_params[missing[i]]}, False))
        store.commit_results(got, neighbours=True)
        known_nb = store.metrics_of([i for i in all_ids if i not in known], "S2_neighbour")
    out: Dict[str, Tuple[Optional[float], int]] = {}
    for a, ids in plan.items():
        vals = []
        for i in ids:
            m = known.get(i) or known_nb.get(i)
            if m and "ret_pct" in m:
                vals.append(m["ret_pct"] > 0)
        out[a] = ((sum(vals) / len(vals)) if vals else None, len(vals))
    return out


def _series_of(daily_rows: List[Dict[str, Any]]) -> List[float]:
    return [x for r in daily_rows for x in r["rets"]]


def _export_wfa_windows(ctx: Ctx, strategy: str, params: Dict[str, Any], dev1: bool = False) -> None:
    jobs = []
    if dev1:
        jobs.append(ctx.s1_job(strategy, params))
    for f in ctx.folds:
        for win, fill, kill in ((f["train"], "level", False), (f["test"], "extreme", True)):
            jobs.append(bt.base_job(strategy, params, win, fill, kill, gates.BASE_RISK_PER_TRADE_PCT, ctx.symbols, ctx.shared_dir))
    ctx.exporter.ensure(jobs)


def stage_s3(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S3_wfa", store.count_pending(2))
    if not ctx.folds:
        raise ValueError("dev2 không đủ dài để tạo fold WFA (train/test ngày)")
    for s in store.strategies_at(2):
        r = store.pending(2, s, limit=1)
        _export_wfa_windows(ctx, s, r[0]["params"])

    def make_job(row):
        return {"strategy": row["strategy"], "params": row["params"], "folds": ctx.folds, "symbols": ctx.symbols,
                "rpt": gates.BASE_RISK_PER_TRADE_PCT, "shared_dir": ctx.shared_dir}

    def on_result(row, res):
        if "error" in res:
            return StageResult(row["alpha_id"], "S3_wfa", {"error": res["error"]}, False, "S3.folds",
                               f"S3.folds: lỗi chạy WFA ({res['error']})")
        agg = bt.aggregate_wfa(res["folds"])
        ok, code, msg = gates.evaluate_s3(agg["summary"])
        return StageResult(row["alpha_id"], "S3_wfa", agg["metrics"], ok, code, msg, trades=[("S3_wfa", agg["trades"])],
                           daily=[("S3_wfa", agg["daily"])])

    _stream(ctx, "S3_wfa", _pages(store, 2), make_job, bt.w_wfa, on_result)
    ctx.exporter.cleanup()


def _page_chunks(store: RunStore, prev_idx: int, size: int) -> Iterator[List[Dict[str, Any]]]:
    chunk: List[Dict[str, Any]] = []
    for r in _pages(store, prev_idx):
        chunk.append(r)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _with_series(ctx: Ctx, prev_idx: int, from_stage: str, size: int = 64) -> Iterator[Dict[str, Any]]:
    """Alpha đang chờ tầng kế + chuỗi ngày OOS nối của S3 (đọc parquet theo lô) -> hàng có khoá "series"."""
    for chunk in _page_chunks(ctx.store, prev_idx, size):
        daily = ctx.store.read_daily_many([r["alpha_id"] for r in chunk], from_stage, stage_col=from_stage)
        for r in chunk:
            yield {**r, "series": _series_of(daily.get(r["alpha_id"], []))}


def stage_s4(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S4_montecarlo", store.count_pending(3))

    def on_result(row, res):
        a = row["alpha_id"]
        m3 = store.metrics_of([a], "S3_wfa").get(a, {})
        base = {k: v for k, v in m3.items() if k in ("ret_pct", "mdd_pct", "sharpe", "sortino", "trades", "win_rate", "profit_factor",
                                                      "oos_days", "folds", "positive_ratio", "worst_fold_mdd", "is_ret_avg")}
        if res["detail"] is None:
            code = "S4.days"
            return StageResult(a, "S4_montecarlo", {**base, "days": res["days"]}, False, code,
                               f"{code}: {gates.reason_label(code)} ({res['days']} < {gates.S4_MIN_DAYS})")
        d, mn = res["detail"], res["min_size"]
        stress_max = max((x["mdd_pct"] for x in d["stress"]), default=None)
        m = {**base, "p_mdd_ge_30": d["summary"]["p_mdd_ge_ruin_pct"], "stress_max_mdd": stress_max, "simulations": d["summary"]["simulations"],
             "mdd_p95": d["summary"]["mdd_p95_pct"], "passes_full_size": bool(d["gate"]["passed"]), "min_size_s": mn["s"],
             "min_size_p_mdd_ge_30": mn["p_mdd_ge_30"], "min_size_stress_max_mdd": mn["stress_max_mdd"]}
        ok, code, msg = gates.evaluate_mc_checks(mn["gate"], "S4")
        store.write_mc(a, {"mc": d, "min_size": {k: mn[k] for k in ("s", "passed", "p_mdd_ge_30", "stress_max_mdd")}, "scale_search": [], "verified": None})
        return StageResult(a, "S4_montecarlo", m, ok, code, msg)

    _stream(ctx, "S4_montecarlo", _with_series(ctx, 3, "S3_wfa"), lambda r: {"series": r["series"]}, bt.w_mc, on_result)


def stage_s5(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S5_sizing", store.count_pending(4))
    for s in store.strategies_at(4):
        r = store.pending(4, s, limit=1)
        _export_wfa_windows(ctx, s, r[0]["params"], dev1=True)

    def make_job(row):
        return {"strategy": row["strategy"], "params": row["params"], "series": row["series"], "windows": ctx.windows, "folds": ctx.folds,
                "symbols": ctx.symbols, "shared_dir": ctx.shared_dir}

    def on_result(row, res):
        a = row["alpha_id"]
        old = store.read_mc(a) or {}
        verified = None
        if res["s"] is not None:
            last = res["attempts"][-1]
            verified = {"backtest": bool(last["backtest"]), "wfa": bool(last["wfa"]), "mc": bool(last["mc"])}
        store.write_mc(a, {**old, **({"mc_full_size": old.get("mc"), "mc": res["mc_detail"]} if res["s"] is not None else {}),
                           "scale_search": res["search"], "attempts": res["attempts"], "verified": verified})
        if res["s"] is None:
            code = "S5.scale_low" if res.get("reason") == "scale_low" else "S5.confirm"
            why = (res["attempts"][-1].get("reason") if res["attempts"] else None) or "không tìm được s qua kiểm tra MC"
            detail = f"s < {gates.S5_S_MIN}" if code == "S5.scale_low" else str(why)
            return StageResult(a, "S5_sizing", {"final_scale": None, "search_steps": len(res["search"]), "confirm_attempts": len(res["attempts"])},
                               False, code, f"{code}: {gates.reason_label(code)} ({detail})")
        wfa = res["wfa"]
        m = {**wfa["metrics"], "final_scale": res["s"], "search_s": res["s_search"], "search_steps": len(res["search"]),
             "confirm_attempts": len(res["attempts"]), "backtest_ret_pct": res["backtest"]["metrics"]["ret_pct"],
             "backtest_mdd_pct": res["backtest"]["metrics"]["mdd_pct"]}
        return StageResult(a, "S5_sizing", m, True, trades=[("S5_sizing", wfa["trades"])], daily=[("S5_sizing", wfa["daily"])])

    _stream(ctx, "S5_sizing", _with_series(ctx, 4, "S3_wfa", 16), make_job, bt.w_sizing, on_result)
    ctx.exporter.cleanup()


def stage_s6(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S6_holdout", store.count_pending(5))
    w = ctx.windows
    for s in store.strategies_at(5):
        r = store.pending(5, s, limit=1)
        ctx.exporter.ensure([bt.base_job(s, r[0]["params"], (w["dev2_end"], w["end"]), "level", True, gates.BASE_RISK_PER_TRADE_PCT, ctx.symbols, ctx.shared_dir)])

    def rows_with_scale() -> Iterator[Dict[str, Any]]:
        for chunk in _page_chunks(store, 5, 200):
            m5 = store.metrics_of([r["alpha_id"] for r in chunk], "S5_sizing")
            for r in chunk:
                yield {**r, "scale": m5[r["alpha_id"]]["final_scale"]}

    def make_job(row):
        return {"strategy": row["strategy"], "params": row["params"], "windows": w, "rpt": sizing.risk_for_scale(row["scale"]),
                "symbols": ctx.symbols, "shared_dir": ctx.shared_dir}

    def on_result(row, res):
        lv, ex = res["level"], res["extreme"]
        ml, me = lv["metrics"], ex["metrics"]
        m = {**_scalar_base(ml), "final_scale": row["scale"], "extreme_ret_pct": me["ret_pct"], "extreme_mdd_pct": me["mdd_pct"],
             "extreme_trades": me["trades"], "halted": ml["halted"] or me["halted"]}
        ok, code, msg = gates.evaluate_s6(ml, me)
        return StageResult(row["alpha_id"], "S6_holdout", m, ok, code, msg,
                           trades=[("S6_holdout", lv["trades"]), ("S6_holdout_extreme", ex["trades"])],
                           daily=[("S6_holdout", [{"fold": None, "start": lv["daily_start"], "rets": lv["daily"]}]),
                                  ("S6_holdout_extreme", [{"fold": None, "start": ex["daily_start"], "rets": ex["daily"]}])])

    _stream(ctx, "S6_holdout", rows_with_scale(), make_job, bt.w_holdout, on_result)
    ctx.exporter.cleanup()


def stage_final(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("FINAL", store.count_pending(6))
    batch = []
    for chunk in _page_chunks(store, 6, 500):
        m6 = store.metrics_of([r["alpha_id"] for r in chunk], "S6_holdout")
        for r in chunk:
            m = dict(m6[r["alpha_id"]])
            batch.append(StageResult(r["alpha_id"], "FINAL", m, True, final_scale=m["final_scale"]))
        store.commit_results(batch)
        ctx.progress.tick(len(batch))
        batch = []


STAGE_FUNCS: Dict[str, Callable[[Ctx], None]] = {
    "S0_generate": stage_s0, "S1_backtest": stage_s1, "S2_antiluck": stage_s2, "S3_wfa": stage_s3, "S4_montecarlo": stage_s4,
    "S5_sizing": stage_s5, "S6_holdout": stage_s6, "FINAL": stage_final,
}


# ── Chạy cả phễu ────────────────────────────────────────────────────────────
def run_funnel(cfg: FunnelConfig, run_id: Optional[str] = None, workers: int = 0, until: Optional[str] = None, base_dir: Optional[str] = None,
               log: Callable[[str], None] = lambda s: print(s, flush=True), check_data: bool = True, max_alphas: int = MAX_ALPHAS_DEFAULT,
               ) -> Dict[str, Any]:
    """Chạy (hoặc chạy tiếp) một lượt phễu. workers = 0: tuần tự trong tiến trình (test); > 0: pool_imap_bounded. Trả tóm tắt (counts, run_dir...)."""
    from backend.core.strategy import strategy_book as sb
    from backend.optimize.results_store import data_fingerprint
    if until is not None and until not in gates.STAGE_IDX:
        raise ValueError(f"until phải thuộc {gates.STAGES}")
    run_id = run_id or new_run_id()
    run_dir = os.path.join(base_dir or funnel_root(), run_id)
    resuming = os.path.isfile(os.path.join(run_dir, "results.sqlite"))
    try:   # run.json có thể đã có (API ghi bản "queued" trước khi CLI chạy) — giữ job_id/created
        with open(os.path.join(run_dir, "run.json"), encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    if resuming and old.get("config"):   # resume: dùng đúng cấu hình đã lưu (không cho đổi giữa chừng)
        saved = old["config"]
        cfg = FunnelConfig(**{k: saved[k] for k in FunnelConfig.__dataclass_fields__ if k in saved})
    cfg.symbols = cfg.symbols or sb.perp_symbols()
    cfg.symbols = [s if "@" in s else f"{s}@perp" for s in cfg.symbols]
    planned = planned_alphas(cfg)
    if sum(planned.values()) > max_alphas:
        raise ValueError(f"{sum(planned.values()):,} alpha vượt giới hạn {max_alphas:,} (giảm n_per_strategy hoặc số chiến lược)")
    if check_data:
        from backend.core.data.quality_gate import require_data_ok
        require_data_ok(cfg.symbols)   # cổng chất lượng dữ liệu BẮT BUỘC, trước khi tạo kho / fork pool
    if resuming and old.get("windows_ms"):
        windows = old["windows_ms"]
    else:
        windows = compute_windows(cfg.symbols, cfg.windows)
    store = RunStore(run_dir)
    progress = Progress(run_dir)
    job_dir = os.environ.get("NORA_JOB_DIR")
    cfg_out = {**cfg.to_dict(), "windows": windows_iso(windows), **git_info(),
               "data_sha256": hashlib.sha256(json.dumps(data_fingerprint(cfg.symbols), sort_keys=True).encode()).hexdigest(),
               "thresholds": gates.thresholds_snapshot()}
    store.update_run({"run_id": run_id, "job_id": os.path.basename(job_dir) if job_dir else old.get("job_id"), "status": "running",
                      "created": old.get("created") or time.time(), "started": time.time(), "finished": None,
                      "config": {**(old.get("config") or {}), **cfg_out} if resuming else cfg_out, "windows_ms": windows,
                      "planned": planned, "total_alphas": sum(planned.values()), "until": until,
                      "stages": old.get("stages") or {s: {"status": "pending"} for s in gates.STAGES}})
    ctx = Ctx(store, cfg, windows, workers, progress, log)
    if resuming:
        log(f"[resume] {run_id}: {store.count_alphas():,} alpha trong kho")
    t_run = time.time()
    status = "done"
    try:
        with graceful_sigterm(progress):
            for stage in gates.STAGES:
                st = store.read_run().get("stages", {}).get(stage, {})
                if st.get("status") == "done":
                    if until == stage:
                        break
                    continue
                t0 = time.time()
                store.update_run({"stages": {stage: {"status": "running", "started": t0}}})
                STAGE_FUNCS[stage](ctx)
                counts = {c["stage"]: c for c in store.stage_counts()}[stage]
                store.update_run({"stages": {stage: {"status": "done", "started": t0, "finished": time.time(), "wall_s": round(time.time() - t0, 1),
                                                     "input": counts["input"], "passed": counts["passed"], "rejected": counts["rejected"]}}})
                _log_stage(ctx, stage, counts, time.time() - t0)
                if until == stage:
                    break
    except SystemExit as exc:
        status = "cancelled" if exc.code == 143 else ("failed" if exc.code else "done")
        raise
    except BaseException:
        status = "failed"
        raise
    finally:
        try:
            ctx.exporter.cleanup()
            if ctx.shared_dir and os.path.isdir(ctx.shared_dir):
                shutil.rmtree(ctx.shared_dir, ignore_errors=True)
            store.update_run({"status": status, "finished": time.time(), "wall_s": round(time.time() - t_run, 1)})
        finally:
            store.close()
    progress.finish(status)
    final_store = RunStore(run_dir, read_only=True)
    try:
        counts = final_store.stage_counts()
        final = final_store.final_alphas()
        disk = final_store.disk_bytes()
    finally:
        final_store.close()
    return {"run_id": run_id, "run_dir": run_dir, "status": status, "counts": counts, "final_alphas": final, "disk_bytes": disk,
            "wall_s": round(time.time() - t_run, 1)}


def _log_stage(ctx: Ctx, stage: str, c: Dict[str, Any], wall: float) -> None:
    with ctx.store._lock:
        rs = ctx.store._con.execute("SELECT reject_code, COUNT(*) FROM alphas WHERE rejected_stage=? GROUP BY reject_code ORDER BY COUNT(*) DESC LIMIT 4",
                                    (stage,)).fetchall()
    top = "; ".join(f"{code} ×{n}" for code, n in rs) or "-"
    ctx.log(f"[{stage}] vào {c['input']} → qua {c['passed']}, loại {c['rejected']} ({wall:.0f}s) | lý do chính: {top}")
