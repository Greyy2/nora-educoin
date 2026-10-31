"""Runner cho các tác vụ Backtest: custom backtest, book backtest, education warming và thư viện PortfolioEngine.

Consolidated into backend/jobs/runner/backtest.py.
"""
from __future__ import annotations

import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import hashlib
import io
import itertools
import json
import logging
import math
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.analys.param import DAY_MS as DAY
from backend.analys.alpha.code.plan import display_name
from backend.data.data import catalog_digest, default_catalog_path, read_manifest, read_1m, aggregate_frame, load_candles
from backend.analys.metrics.metrics import portfolio_metrics, result_payload
from backend.models.models import NORA_DIR
from backend.jobs.worker import pool_imap_bounded, pool_map_safe
from backend.models.storage import json_default, data_home, write_json_atomic

if TYPE_CHECKING:
    from backend.core.engine import BacktestEngine, PortfolioEngine

logger = logging.getLogger("nora.jobs.runner.backtest")

WARMUP = 20 * DAY
PER_WORKER_MB = 800
MAX_DAYS = 4000


def windows(symbols):
    """Cửa sổ dev1/dev2 (ms) theo dữ liệu thật của các tài sản: bắt đầu sau WARMUP, dev1 = 40%, dev2 đến 80%."""
    ms = [m for s in symbols if (m := read_manifest(s)) is not None]
    if not ms:
        return {"start": 0, "dev1_end": 0, "dev2_end": 0, "end": 0}
    start = max(int(m["start_ts"]) for m in ms) + WARMUP
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    return {"start": start, "dev1_end": start + int(span * 0.4), "dev2_end": start + int(span * 0.8), "end": end}


def execute(plan, start: int, end: int, initial_capital: float, close_at_end: bool = False, loaded=None):
    """PortfolioEngine cho một Plan -> (get_results(), engine)."""
    from backend.core.engine import BacktestEngine, PortfolioEngine
    from backend.analys.alpha.code.plan import RiskConfig
    setattr(BacktestEngine, "MAX_BACKTEST_DAYS", max(int(getattr(BacktestEngine, "MAX_BACKTEST_DAYS", 1100)), MAX_DAYS))
    eng = PortfolioEngine(plan.symbols, plan.strategies, start - WARMUP, end, trade_start_ts=start, initial_capital=initial_capital,
                          risk=RiskConfig.from_dict(plan.risk), venue=plan.venue, close_at_end=close_at_end, base_frame=plan.base_frame,
                          shared_dir=None)
    if loaded is not None:
        try:
            eng.load_data()
        finally:
            loaded.set()
        eng.run()
        return eng.get_results(), eng
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    return eng.get_results(), eng


BENCH_CODE = ('class AlwaysLong(SimpleAlgorithm):\n    timeframe = "{tf}"\n    def __algorithm__(self):\n'
              '        self.set_positions(self.data.pv_close > 0, position=1)\n')
NO_EXIT_POSITION = {"stop_loss_rate": 0.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0}
_BENCH_CACHE: Dict[str, Dict[str, Any]] = {}


def run_benchmark(program, a, plan, names: List[str], start: int, end: int, capital: float, data: Dict[str, Any], loaded=None) -> Optional[Dict[str, Any]]:
    """Benchmark "luôn long" self.set_positions(self.data.pv_close > 0, position=1) chạy qua CÙNG đường engine."""
    from backend.analys.param import FRAME_MS, resolve_costs
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.code.plan import build_plan
    from backend.analys.metrics.trades import daily_series
    position = {**(program.position_overrides or {}), **(a.position or {})}
    taker = resolve_costs(plan.venue, "perp", position.get("fee_rate"), position.get("slippage_rate"), position.get("maker_fee_rate"))[0]
    bench_position: Dict[str, Any] = dict(NO_EXIT_POSITION)
    bench_position.update(
        cooldown=0,
        sizing="margin_pct",
        leverage=1,
        order_size_pct=100.0 / len(names) / (1.0 + taker) * (1.0 - 1e-9),
        fee_rate=taker,
    )
    try:
        import nautilus_trader
        nt_version = getattr(nautilus_trader, "__version__", "1.0.0")
    except Exception:
        nt_version = "1.0.0"
    bench_code_str = BENCH_CODE.format(tf=plan.base_frame)
    bench_code_sha = hashlib.sha256(bench_code_str.encode("utf-8")).hexdigest()[:10]
    runner_sha = "v2"
    try:
        p_runner = Path(__file__)
        p_core = p_runner.parent.parent.parent / "core" / "backtest.py"
        h_runner = hashlib.sha256(p_runner.read_bytes())
        if p_core.is_file():
            h_runner.update(p_core.read_bytes())
        runner_sha = h_runner.hexdigest()[:10]
    except Exception:
        pass
    BENCH_ENGINE_VERSION = f"nautilus-{nt_version}-nora-{runner_sha}-bench-{bench_code_sha}"
    content_hash = data.get("content_sha256_1m") or data.get("sha256_1m")
    if content_hash:
        data_fingerprint = f"content_sha256:{json.dumps(content_hash, sort_keys=True) if isinstance(content_hash, dict) else str(content_hash)}"
    else:
        # Fallback rõ ràng kèm nhãn fallback để không nhầm lẫn với content sha256
        data_fingerprint = f"catalog_fallback:{data.get('catalog_digest') or data.get('data_digest') or ''}"
    norm_symbols = sorted(names)
    key = json.dumps([
        BENCH_ENGINE_VERSION,
        norm_symbols,
        plan.base_frame,
        start,
        end,
        float(capital),
        round(float(taker), 6),
        data.get("source"),
        data_fingerprint,
    ], sort_keys=True, default=str)
    hit = _BENCH_CACHE.get(key)
    if hit is not None:
        if loaded is not None:
            loaded.set()
        return hit
    bench_dir = os.path.join(data_home(), "cache", "benchmarks")
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    fpath = os.path.join(bench_dir, f"{h}.json")
    if os.path.isfile(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                hit = json.load(fh)
            _BENCH_CACHE[key] = hit
            if loaded is not None:
                loaded.set()
            return hit
        except Exception:
            pass
    bench_prog = compile_code(BENCH_CODE.format(tf=plan.base_frame))
    bplan = build_plan(bench_prog, names, position=bench_position, run_frame=plan.base_frame)
    bplan.risk = {"max_positions": max(1, len(names)), "max_per_symbol": 1, "max_gross_exposure": 1e6, "kill_switch_dd_pct": 0.0, "max_open_risk_pct": 0.0, "dd_throttle_pct": 0.0}
    res, _ = execute(bplan, start, end, capital, loaded=loaded) if loaded is not None else execute(bplan, start, end, capital)
    ser = daily_series(res["equity_curve"], start, end, FRAME_MS[bplan.base_frame], capital)
    out = {"times": ser["times"], "equity": ser["equity"], "program_hash": bench_prog.code_hash, "strategies": [s["id"] for s in bplan.strategies],
           "label": "Luôn long (position=1) cùng rổ/ngày/vốn, chia đều, đòn bẩy 1, không SL/TP/trailing/timeout/kill-switch", "symbols": bplan.symbols}
    _BENCH_CACHE[key] = out
    try:
        os.makedirs(bench_dir, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    except Exception:
        pass
    return out


def _mid_params(candidate, params):
    out = dict(params or {})
    for key, values in candidate["space"].items():
        out.setdefault(key, values[len(values) // 2])
    return out


def load_items(a):
    from backend.analys.param import BASE_RISK_PER_TRADE_PCT, RISK
    from backend.analys.alpha.strategies import BY_ID
    by_id = BY_ID
    if a.strategies:
        raw = a.strategies
        if not isinstance(raw, list) or not raw:
            raise SystemExit("strategies phải là danh sách không rỗng")
        items = []
        for s in raw:
            if s.get("id") not in by_id:
                raise SystemExit(f"Không có chiến lược: {s.get('id')}; có: {sorted(by_id)}")
            items.append((s["id"], _mid_params(by_id[s["id"]], s.get("params"))))
        return items, BASE_RISK_PER_TRADE_PCT, RISK
    from backend.models.storage import alpha_file
    path = a.book or alpha_file("book")
    if not os.path.isfile(path):
        alt = os.path.join(NORA_DIR, "data", "alpha", "book.json")
        if os.path.isfile(alt):
            path = alt
    with open(path, encoding="utf-8") as fh:
        book = json.load(fh)
    items = [(s["id"], s["params"]) for s in book["strategies"]]
    bad = [i for i, _ in items if i not in by_id]
    if bad:
        raise SystemExit(f"book {path} có chiến lược không còn trong thư viện: {bad}")
    return items, book.get("risk_per_trade_pct") or BASE_RISK_PER_TRADE_PCT, book.get("risk") or RISK


class BacktestJob(NamedTuple):
    items: List[Tuple[str, Dict[str, Any]]]
    window: Tuple[int, int]
    stop_fill: str
    risk: Dict[str, Any]
    rpt: float
    symbols: Optional[List[str]] = None
    shared_dir: Optional[str] = None
    base_frame: str = "1m"
    regime: Optional[Dict[str, Any]] = None


def make_engine(job: BacktestJob):
    from backend.core.engine import PortfolioEngine
    from backend.analys.alpha.code.plan import RiskConfig
    from backend.analys.alpha.strategies import lift_frames, perp_symbols, BY_ID
    from backend.analys.param import materialize
    by_id = BY_ID
    regime = job.regime or {}
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, job.base_frame), regime=regime.get(cid) or False,
                              stop_fill=job.stop_fill, risk_per_trade_pct=job.rpt) for cid, prm in job.items]
    start, end = job.window
    return PortfolioEngine(list(job.symbols or perp_symbols()), strategies, start - WARMUP, end, trade_start_ts=start,
                           risk=RiskConfig.from_dict(job.risk), shared_dir=job.shared_dir, base_frame=job.base_frame), start


def run(items, symbols, start, end, rpt, stop_fill, risk, extra_strategies=None, initial_capital=None, close_at_end=True,
        warmup=WARMUP, regime=False, base_frame="1m", venue="cex"):
    from backend.analys.param import materialize
    from backend.analys.alpha.strategies import BY_ID, lift_frames
    from backend.core.engine import PortfolioEngine
    from backend.analys.alpha.code.plan import RiskConfig
    from backend.jobs.worker import peak_rss_mb
    by_id = BY_ID
    spot = {}
    if venue == "dex":
        from backend.analys.alpha.code import plan as dex
        dex.require_long_legs([cid for cid, _ in items], BY_ID)
        spot = dex.SPOT_POSITION
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, base_frame), regime=regime, stop_fill=stop_fill,
                              risk_per_trade_pct=rpt, **spot) for cid, prm in items]
    strategies += list(extra_strategies or [])
    t0 = time.time()
    kw: Dict[str, Any] = {} if initial_capital is None else {"initial_capital": float(initial_capital)}
    eng = PortfolioEngine(symbols, strategies, start - warmup, end, trade_start_ts=start, risk=RiskConfig.from_dict(risk),
                          close_at_end=close_at_end, base_frame=base_frame, venue=venue, **kw)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    out = result_payload(res, start, end)
    out["config"] = {"strategies": [{"id": i, "params": p} for i, p in items]
                     + [{"id": x["id"], "params": x["position"]} for x in extra_strategies or []], "symbols": symbols, "risk_per_trade_pct": rpt,
                     "stop_fill": stop_fill, "risk": res["risk"], "start": start, "end": end,
                     "initial_capital": res["initial_capital"]}
    if venue == "dex":
        out["config"].update(venue="dex", data="candle", symbols=[display_name(x) for x in symbols])
    if regime:
        out["config"]["regime"] = True
    if base_frame != "1m":
        out["config"]["timeframe"] = base_frame
    out["final_equity"] = round(res["final_equity"], 2)
    if not close_at_end:
        out["open_positions"] = eng.open_positions()
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}
    return out


def run_tick(items, symbols: List[str], start: Optional[int], end: Optional[int], rpt: float, risk: Dict[str, Any], stop_fill: str, base_frame: str,
             capital: float, latency_ms: Optional[int] = None, gas_usd: Optional[float] = None) -> Dict[str, Any]:
    from backend.jobs.runner import DEX_UNSUPPORTED, NotReady
    raise NotReady(DEX_UNSUPPORTED)


def risk_dict(kill: bool) -> Dict[str, Any]:
    from backend.analys.param import RISK
    return {**RISK, "kill_switch_dd_pct": RISK["kill_switch_dd_pct"] if kill else 0}


def to_job(job: Dict[str, Any]) -> BacktestJob:
    rmap = job.get("regime_map")
    return BacktestJob([(job["strategy"], job["params"])], (int(job["window"][0]), int(job["window"][1])), job["stop_fill"],
                       risk_dict(job["kill"]), job["rpt"], list(job["symbols"]), job.get("shared_dir"), job.get("base_frame", "1m"),
                       {job["strategy"]: rmap} if rmap else None)


def print_summary(res: Dict[str, Any], t_elapsed: float) -> None:
    cfg = res.get("config", {})
    metrics = res.get("metrics", {})
    print(f"Hoàn tất! Vốn cuối {res.get('final_equity', 0):.2f} | Lãi {metrics.get('ret_pct', 0):.2f}% | "
          f"MDD {metrics.get('mdd_pct', 0):.2f}% | Lệnh {metrics.get('trades', 0)} | {t_elapsed:.1f}s", flush=True)


# ── Shared Data Exporter & Helpers ──────────────────────────────────────────
FORMAT_VERSION = 1
BASE_ARRAYS = ("t", "o", "h", "l", "c", "f_t", "f_r")
MINUTE_ARRAYS = ("minute_t", "minute_o", "minute_h", "minute_l", "minute_c", "minute_v")
STATS = {"bases_written": 0, "cols_written": 0, "frames_written": 0, "index_written": 0, "fills": 0}


def _file(out_dir: str, section: str, key: str) -> str:
    return os.path.join(out_dir, section, f"{key}.npy")


def _base_dir(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "base", key)


def _load_array(path: str) -> np.ndarray:
    return np.load(path, mmap_mode="r")


def paths(p: Dict[str, Any]) -> Set[str]:
    out: Set[str] = {os.path.join("base", p["base"])}
    for fr, f in p["frames"].items():
        out.add(os.path.join("ft", f"{f['t']}.npy"))
        out.add(os.path.join("ix", f"{f['ix']}.npy"))
    for cid, c in p["cols"].items():
        out.add(os.path.join("fv", f"{c['v']}.npy"))
    return out


def plan(eng: Any) -> Optional[Dict[str, Any]]:
    from backend.analys.signal.signal import lag_key
    from backend.analys.signal.compute import slot_fresh_frames, needs_minute_path
    m = read_manifest(eng.symbol)
    if not m:
        return None
    d_hash = m.get("sha256_1m") or hashlib.sha1(f"{m.get('start_ts')}_{m.get('end_ts')}".encode()).hexdigest()[:16]
    has_minute = needs_minute_path(eng)

    base_key = hashlib.sha1(f"v{FORMAT_VERSION}|{eng.symbol}|{eng.base_frame}|{d_hash}|{eng.start_ts}|{eng.end_ts}|m:{has_minute}".encode()).hexdigest()
    refs = eng._refs_by_frame()
    frames = {}
    for fr in sorted(refs):
        t_key = hashlib.sha1(f"{eng.symbol}|{fr}|t|{d_hash}|{eng.end_ts}".encode()).hexdigest()
        ix_key = hashlib.sha1(f"{eng.symbol}|{fr}|ix|{eng.base_frame}|{d_hash}|{base_key}".encode()).hexdigest()
        frames[fr] = {"t": t_key, "ix": ix_key}
    cols = {}
    for fr in sorted(refs):
        t_key = frames[fr]["t"]
        for col, lag in sorted(refs[fr]):
            cid = f"{fr}|{lag_key(col, lag)}"
            v_key = hashlib.sha1(f"{eng.symbol}|{cid}|{t_key}".encode()).hexdigest()
            cols[cid] = {"v": v_key, "frame": fr}
    fresh_frames = sorted(slot_fresh_frames(getattr(eng, "slots", ()), eng.base_frame))
    return {"base": base_key, "frames": frames, "cols": cols, "minute": has_minute, "fresh": fresh_frames}


def load_base(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, np.ndarray]]:
    bdir = _base_dir(out_dir, p["base"])
    meta_path = os.path.join(bdir, "meta.json")
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as fh:
            if json.load(fh).get("version") != FORMAT_VERSION:
                return None
        names = BASE_ARRAYS + (MINUTE_ARRAYS if p.get("minute") else ())
        return {name: _load_array(os.path.join(bdir, f"{name}.npy")) for name in names}
    except (OSError, ValueError):
        return None


def load(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from backend.analys.signal.compute import FRESH, SignalEngine, frame_fresh
    base = load_base(out_dir, p)
    if base is None:
        return None
    try:
        idx = {fr: _load_array(_file(out_dir, "ix", f["ix"])) for fr, f in p["frames"].items()}
        cols = {}
        for fr in p["frames"]:
            for cid, c in p["cols"].items():
                if c["frame"] == fr:
                    cols[cid] = SignalEngine.gather(_load_array(_file(out_dir, "fv", c["v"])), idx[fr])
            if fr in p.get("fresh", ()):
                cols[f"{fr}|{FRESH}"] = frame_fresh(idx[fr])
    except (OSError, ValueError):
        return None
    data: Dict[str, Any] = {k: base[k] for k in ("t", "o", "h", "l", "c")}
    data["cols"] = cols
    data["f_t"], data["f_r"] = base["f_t"], base["f_r"]
    if p.get("minute"):
        data["minute"] = {k: base[k] for k in MINUTE_ARRAYS}
    return data


def _save(path: str, arr: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "wb") as fh:
        np.save(fh, np.ascontiguousarray(arr), allow_pickle=False)
    os.replace(tmp, path)


def _write_base(out_dir: str, key: str, symbol: str, data: Dict[str, Any]) -> None:
    final = _base_dir(out_dir, key)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    tmp = f"{final}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for name in BASE_ARRAYS:
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, data[name], allow_pickle=False)
    for name, arr in (data.get("minute") or {}).items():
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, arr, allow_pickle=False)
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": FORMAT_VERSION, "symbol": symbol}, fh)
    try:
        os.rename(tmp, final)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        if not os.path.isdir(final):
            raise


def fill(out_dir: str, pe: "PortfolioEngine", eng: Any, p: Dict[str, Any]) -> Dict[str, int]:
    from backend.analys.signal.signal import lag_key
    wrote = {"base": 0, "cols": 0, "frames": 0, "index": 0}
    loaded_b = load_base(out_dir, p)
    if loaded_b is None:
        sym_data = pe._build_symbol_data(eng, only=set())
        if p.get("minute") and "minute" not in sym_data and hasattr(eng, "minute_path"):
            sym_data["minute"] = eng.minute_path(sym_data["t"])
        _write_base(out_dir, p["base"], eng.symbol, sym_data)
        wrote["base"] = 1
        loaded_b = sym_data
    base_t = loaded_b["t"] if loaded_b is not None else np.array([])
    refs = eng._refs_by_frame()
    loaded = False
    for frame, f in p["frames"].items():
        miss_cols = {cid for cid, c in p["cols"].items() if c["frame"] == frame and not os.path.isfile(_file(out_dir, "fv", c["v"]))}
        t_path, ix_path = _file(out_dir, "ft", f["t"]), _file(out_dir, "ix", f["ix"])
        if not miss_cols and os.path.isfile(t_path) and os.path.isfile(ix_path):
            continue
        if frame != eng.base_frame and not loaded:
            eng.load_frames(refs)
            loaded = True
        sub = {(col, lag) for col, lag in refs[frame] if f"{frame}|{lag_key(col, lag)}" in miss_cols}
        if sub or not os.path.isfile(t_path):
            t_frame, vals = eng.frame_values(frame, sub or {sorted(refs[frame])[0]})
            for cid in miss_cols:
                _save(_file(out_dir, "fv", p["cols"][cid]["v"]), vals[cid])
            wrote["cols"] += len(miss_cols)
            if not os.path.isfile(t_path):
                _save(t_path, t_frame)
                wrote["frames"] += 1
        if not os.path.isfile(ix_path):
            _save(ix_path, eng.align_index(frame, _load_array(t_path), base_t, eng.base_frame))
            wrote["index"] += 1
    STATS["fills"] += 1
    for k, n in wrote.items():
        STATS[{"base": "bases_written", "cols": "cols_written", "frames": "frames_written", "index": "index_written"}[k]] += n
    return wrote


def export(pe: "PortfolioEngine", out_dir: str) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    out: Dict[str, Any] = {"paths": set(), "written": []}
    for sym in pe.symbols:
        eng, _ = pe._make_slots(sym, pe.ledger)
        p = plan(eng)
        if p is None:
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (catalog chưa có nến)")
        if any(fill(out_dir, pe, eng, p).values()):
            out["written"].append(sym)
        out["paths"] |= paths(p)
    return out


def remove(out_dir: str, rel_paths: Iterable[str]) -> None:
    for rel in rel_paths:
        path = os.path.join(out_dir, rel)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def size_mb(out_dir: str, rel_paths: Optional[Iterable[str]] = None) -> float:
    targets = [os.path.join(out_dir, r) for r in rel_paths] if rel_paths is not None else [out_dir]
    total = 0
    for t in targets:
        if os.path.isfile(t):
            total += os.path.getsize(t)
            continue
        for base, _, files in os.walk(t):
            total += sum(os.path.getsize(os.path.join(base, f)) for f in files)
    return total / 1048576


STORE_DIRS = ("base", "ft", "fv", "ix")


def release_memory() -> None:
    import ctypes
    import gc
    from backend.analys.signal.compute import data_cache_clear
    from backend.data.data import clear_caches
    clear_caches()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def export_job(job: BacktestJob) -> List[str]:
    eng, _ = make_engine(job)
    if not job.shared_dir:
        return []
    info = export(eng, job.shared_dir)
    release_memory()
    return sorted(info["paths"])


class SharedExporter:
    def __init__(self, shared_dir: Optional[str], label: str = "", workers: int = 1,
                 to_job: Optional[Callable[[Any], BacktestJob]] = None):
        self.shared_dir, self.label, self.workers, self.to_job = shared_dir, label, max(1, workers), to_job
        self.seen: Set[Tuple] = set()
        self.t0 = time.time()

    def ensure(self, jobs: Iterable[Any]) -> None:
        if not self.shared_dir:
            return
        todo = []
        for j in jobs:
            job = self.to_job(j) if self.to_job else j
            memo = (tuple(cid for cid, _ in job.items), tuple(job.window), job.base_frame)
            if memo in self.seen:
                continue
            self.seen.add(memo)
            todo.append(job._replace(shared_dir=self.shared_dir))
        if not todo:
            return
        os.makedirs(self.shared_dir, exist_ok=True)
        if self.workers <= 1 or len(todo) == 1:
            for job in todo:
                export_job(job)
        else:
            pool_map_safe(export_job, todo, min(self.workers, len(todo)), f"[shared] {self.label}")

    def __call__(self, job: Any) -> None:
        self.ensure([job])

    def cleanup(self) -> None:
        if not self.shared_dir:
            return
        mb = size_mb(self.shared_dir) if os.path.isdir(self.shared_dir) else 0.0
        for sub in STORE_DIRS:
            shutil.rmtree(os.path.join(self.shared_dir, sub), ignore_errors=True)
        if self.label:
            print(f"[shared] {self.label}: dọn {mb:.0f} MB ({time.time() - self.t0:.0f}s)", flush=True)
        self.seen.clear()


from backend.data.data import EngineData, make_engine_data, ENGINE_DATA


ENGINE_DATA = EngineData()


def make_engine_data() -> EngineData:
    return ENGINE_DATA


# ── Canonical hashing & job key ─────────────────────────────────────────────
_CODE_FILES = (
    "backend/analys/signal/compute.py", "backend/analys/alpha/code/plan.py", "backend/models/models.py",
    "backend/analys/param/params.py", "backend/analys/position/position_size.py",
    "backend/core/engine.py",
    "backend/analys/metrics/metrics.py", "backend/analys/metrics/trades.py",
    "backend/data/data.py", "backend/analys/signal/signal.py", "backend/analys/alpha/code/contract.py",
    "backend/analys/alpha/code/compile.py", "backend/analys/indicator/indicator.py",
    "backend/analys/alpha/strategies.py", "backend/analys/validation/wfa/wfa.py",
)
_CODE_VERSION: Optional[str] = None


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=json_default, allow_nan=True)


def code_version() -> str:
    global _CODE_VERSION
    env = os.environ.get("NORA_CODE_VERSION")
    if env:
        return env
    if _CODE_VERSION is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        try:
            import nautilus_trader
            NAUTILUS_VERSION = getattr(nautilus_trader, "__version__", "0.0.0")
        except Exception:
            NAUTILUS_VERSION = "0.0.0"
        h = hashlib.sha1(f"v{FORMAT_VERSION}|nautilus {NAUTILUS_VERSION}".encode())
        for rel in _CODE_FILES:
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    h.update(rel.encode() + b"\0" + fh.read())
            except OSError:
                h.update(rel.encode() + b"\0missing")
        _CODE_VERSION = h.hexdigest()[:16]
    return _CODE_VERSION


def data_fingerprint(symbols: Iterable[str]) -> List[Any]:
    return [[s, catalog_digest([s])] for s in symbols]


def make_job_key(stage: str, candidate: str, params: Any, window: Any = None, stop_fill: Any = None, risk: Any = None,
                 data: Any = None, code: Optional[str] = None, extra: Any = None) -> str:
    payload = canonical([stage, candidate, params, window, stop_fill, risk, data, code or code_version(), extra])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalize(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=json_default, allow_nan=True))


def run_wfa_job(job):
    from backend.jobs.worker import peak_rss_mb, rss_anon_mb
    from backend.analys.validation.carlo.carlo import measure_turnover, vertical_exposure
    from backend.analys.param import iso_date
    eng, start = make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    result = portfolio_metrics(res, start)
    from backend.analys.metrics.trades import trade_rows
    rows = trade_rows(res["positions"])
    result["shock"] = vertical_exposure(rows, job.rpt)
    result["turnover"] = measure_turnover(rows, len(result["daily"]))
    if job.regime:
        from backend.analys.metrics.regime import engine_by_regime
        result["by_regime"] = engine_by_regime(eng, res["positions"])
    first = next((c["time"] for c in res["equity_curve"] if c["time"] >= start), None)
    result["_daily_start"] = iso_date(first) if first is not None else None
    result["_peak_rss_mb"] = round(peak_rss_mb(), 1)
    result["_rss_anon_mb"] = round(rss_anon_mb(), 1)
    return result


def _strip(m):
    from backend.analys.alpha.strategies import strip_metrics
    return strip_metrics(m, ("_daily_start", "by_regime", "shock", "turnover"))


def _pool_map(fn, items, workers, label, on_done=None):
    from backend.jobs.worker import pool_map_safe
    return pool_map_safe(fn, items, workers, label, on_done=on_done)


def _pool_shared(jobs, workers, label, shared_dir, store=None, stage=None, progress=None):
    if store is None and progress is None:
        exporter = SharedExporter(shared_dir, label)
        exporter.ensure(jobs)
        res = _pool_map(run_wfa_job, jobs, workers, label)
        exporter.cleanup()
        return res
    stage = stage or "wfa"
    results: List[Any] = [None] * len(jobs)
    keys_of: List[Optional[str]] = [None] * len(jobs)
    missing = []
    fp = data_fingerprint(jobs[0].symbols) if (store is not None and jobs) else None
    for i, job in enumerate(jobs):
        if store is not None:
            extra = {"rpt": job.rpt, "symbols": list(job.symbols)}
            if job.base_frame != "1m":
                extra["base_frame"] = job.base_frame
            if job.regime:
                extra["regime"] = job.regime
            keys_of[i] = make_job_key(stage, "-", [[c, p] for c, p in job.items], list(job.window), job.stop_fill, job.risk, fp,
                                      extra=extra)
            row = store.get(keys_of[i])
            if row is not None:
                results[i] = row["metrics"]
                if progress is not None:
                    progress.tick(resumed=True)
                continue
        missing.append(i)
    if missing:
        sub = [jobs[i] for i in missing]
        exporter = SharedExporter(shared_dir, label)
        exporter.ensure(sub)

        def _done(j, res):
            i = missing[j]
            m = normalize(res)
            if stage == "wfa_is":
                m.pop("daily", None)
                m.pop("stats", None)
            results[i] = m
            if store is not None:
                store.put(keys_of[i], stage, "-", [[c, p] for c, p in jobs[i].items], m, ord=i)
            if progress is not None:
                progress.tick(worker_peak_mb=m.get("_peak_rss_mb"))
        _pool_map(run_wfa_job, sub, workers, label, on_done=_done)
        exporter.cleanup()
    return results


# ── Lazy import of tasks to avoid circular dependencies ─────────────────────
def run_custom_backtest(*args, **kwargs):
    from backend.jobs.tasks import run_custom_backtest as _fn
    return _fn(*args, **kwargs)


def run_custom(*args, **kwargs):
    from backend.jobs.tasks import run_custom as _fn
    return _fn(*args, **kwargs)


def run_book_backtest(*args, **kwargs):
    from backend.jobs.tasks import run_book_backtest as _fn
    return _fn(*args, **kwargs)


def education_warm(*args, **kwargs):
    from backend.jobs.tasks import education_warm as _fn
    return _fn(*args, **kwargs)


if TYPE_CHECKING:
    from backend.jobs.runner.wfa import (
        run_portfolio_wfa,
        candidates_from_report,
        candidates_from_ids,
        candidates_from_list,
        ResultsStore,
        stream_stage,
    )


__all__ = [
    "run_custom_backtest",
    "run_custom",
    "run_book_backtest",
    "education_warm",
    "BacktestJob",
    "make_engine",
    "run",
    "execute",
    "run_tick",
    "WARMUP",
    "PER_WORKER_MB",
    "print_summary",
    "run_benchmark",
    "windows",
    "load_items",
    "risk_dict",
    "to_job",
    "SharedExporter",
    "export_job",
    "export",
    "fill",
    "load",
    "load_base",
    "paths",
    "plan",
    "remove",
    "size_mb",
    "STORE_DIRS",
    "release_memory",
    "EngineData",
    "make_engine_data",
    "canonical",
    "code_version",
    "data_fingerprint",
    "make_job_key",
    "normalize",
    "run_portfolio_wfa",
    "candidates_from_report",
    "candidates_from_ids",
    "candidates_from_list",
    "ResultsStore",
    "stream_stage",
    "portfolio_metrics",
    "_strip",
    "_pool_shared",
    "_pool_map",
]


def __getattr__(name: str) -> Any:
    if name in (
        "run_portfolio_wfa",
        "candidates_from_report",
        "candidates_from_ids",
        "candidates_from_list",
        "ResultsStore",
        "stream_stage",
    ):
        import backend.jobs.runner.wfa as _wfa
        val = getattr(_wfa, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

