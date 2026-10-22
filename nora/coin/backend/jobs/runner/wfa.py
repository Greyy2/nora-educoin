"""Runner cho các tác vụ Walk-Forward Analysis (WFA) và xác thực đa chu kỳ.

Consolidated into backend/jobs/runner/wfa.py.
"""
from __future__ import annotations

import heapq
import itertools
import json
import logging
import math
import os
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.models.storage import json_default
from backend.jobs.worker import pool_imap_bounded
from backend.jobs.runner.backtest import (
    BacktestJob,
    _pool_shared,
    _strip,
    load_items,
    normalize,
)

logger = logging.getLogger("nora.jobs.runner.wfa")

DB_NAME = "results.sqlite"
COMMIT_EVERY = 200
COMMIT_SECONDS = 3.0
SCHEMA_VERSION = 1

_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS results(
    job_key TEXT PRIMARY KEY, stage TEXT NOT NULL, candidate TEXT NOT NULL, ord INTEGER,
    params_json TEXT NOT NULL, metrics_json TEXT NOT NULL, score REAL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS results_rank ON results(stage, candidate, score DESC, ord);
CREATE INDEX IF NOT EXISTS results_ord ON results(stage, candidate, ord);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _results_dumps(obj: Any) -> str:
    return json.dumps(obj, default=json_default, allow_nan=True)


class ResultsStore:
    """Kho kết quả của MỘT lần chạy (một file SQLite trong run_dir). An toàn đa luồng; nhiều tiến trình cùng ghi được (WAL + busy_timeout)."""

    def __init__(self, run_dir: str, name: str = DB_NAME, read_only: bool = False):
        self.path = run_dir if run_dir.endswith(".sqlite") else os.path.join(run_dir, name)
        if not read_only:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.read_only = read_only
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, timeout=60.0, check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA busy_timeout=60000")
        if read_only:
            self._con.execute("PRAGMA query_only=1")
        else:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_RESULTS_SCHEMA)
        self._pending = 0
        self._in_tx = False
        self._last_commit = time.time()
        self._puts = 0
        self._fail_after = int(os.environ.get("NORA_TEST_FAIL_AFTER_PUTS") or 0)

    def put(self, job_key: str, stage: str, candidate: str, params: Any, metrics: Any, ord: Optional[int] = None,
            score: Optional[float] = None) -> bool:
        sc = None if score is None or (isinstance(score, float) and not math.isfinite(score)) else float(score)
        with self._lock:
            if not self._in_tx:
                self._con.execute("BEGIN")
                self._in_tx = True
            cur = self._con.execute(
                "INSERT OR IGNORE INTO results(job_key, stage, candidate, ord, params_json, metrics_json, score, created) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (job_key, stage, candidate, ord, _results_dumps(params), _results_dumps(metrics), sc, time.time()))
            inserted = cur.rowcount == 1
            self._pending += 1
            if self._pending >= COMMIT_EVERY or time.time() - self._last_commit >= COMMIT_SECONDS:
                self._commit()
            if inserted:
                self._puts += 1
                if self._fail_after and self._puts >= self._fail_after:
                    self._commit()
                    raise RuntimeError(f"[test] mô phỏng sập sau {self._puts} job (NORA_TEST_FAIL_AFTER_PUTS)")
            return inserted

    def _commit(self) -> None:
        if self._in_tx:
            self._con.execute("COMMIT")
            self._in_tx = False
        self._pending = 0
        self._last_commit = time.time()

    def flush(self) -> None:
        with self._lock:
            if not self.read_only:
                self._commit()

    def close(self) -> None:
        with self._lock:
            try:
                self.flush()
            finally:
                self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            self._con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, _results_dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _row(r) -> Dict[str, Any]:
        return {"job_key": r[0], "stage": r[1], "candidate": r[2], "ord": r[3], "params": json.loads(r[4]),
                "metrics": json.loads(r[5]), "score": r[6]}

    _COLS = "job_key, stage, candidate, ord, params_json, metrics_json, score"

    def has(self, job_key: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM results WHERE job_key=?", (job_key,)).fetchone() is not None

    def get(self, job_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._con.execute(f"SELECT {self._COLS} FROM results WHERE job_key=?", (job_key,)).fetchone()
        return self._row(r) if r else None

    def count(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> int:
        q, args = "SELECT COUNT(*) FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        with self._lock:
            return int(self._con.execute(q, args).fetchone()[0])

    def done_keys(self, stage: Optional[str] = None, candidate: Optional[str] = None) -> Iterator[str]:
        q, args = "SELECT job_key FROM results", []
        cond = []
        if stage is not None:
            cond.append("stage=?"); args.append(stage)
        if candidate is not None:
            cond.append("candidate=?"); args.append(candidate)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        con = self._con
        with self._lock:
            keys = con.execute(q, args)
            for (k,) in keys:
                yield k

    def iter_rows(self, stage: str, candidate: str) -> Iterator[Dict[str, Any]]:
        with self._lock:
            cur = self._con.cursor()
            cur.execute(f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? ORDER BY ord", (stage, candidate))
        while True:
            with self._lock:
                batch = cur.fetchmany(500)
            if not batch:
                break
            for r in batch:
                yield self._row(r)

    def top_k(self, stage: str, candidate: str, k: int, score_fn: Optional[Callable[[Dict[str, Any]], float]] = None) -> List[Dict[str, Any]]:
        k = max(0, int(k))
        if score_fn is None:
            with self._lock:
                rs = self._con.execute(
                    f"SELECT {self._COLS} FROM results WHERE stage=? AND candidate=? "
                    f"ORDER BY score IS NULL, score DESC, ord LIMIT ?", (stage, candidate, k)).fetchall()
            return [self._row(r) for r in rs]

        def keyed():
            for row in self.iter_rows(stage, candidate):
                sc = score_fn(row)
                yield (-sc, row["ord"] if row["ord"] is not None else 0), row["job_key"], row
        best = heapq.nsmallest(k, keyed(), key=lambda t: t[0])
        return [t[2] for t in best]

    def page(self, stage: str, candidate: Optional[str] = None, offset: int = 0, limit: int = 100,
             sort: str = "order") -> List[Dict[str, Any]]:
        order = "ORDER BY score IS NULL, score DESC, ord" if sort == "score" else "ORDER BY ord"
        q, args = f"SELECT {self._COLS} FROM results WHERE stage=?", [stage]
        if candidate is not None:
            q += " AND candidate=?"
            args.append(candidate)
        q += f" {order} LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 1000)), max(0, int(offset))]
        with self._lock:
            rs = self._con.execute(q, args).fetchall()
        return [self._row(r) for r in rs]

    def candidates(self, stage: str) -> List[str]:
        with self._lock:
            return [r[0] for r in self._con.execute("SELECT DISTINCT candidate FROM results WHERE stage=? ORDER BY candidate", (stage,))]


def stream_stage(items: Iterable[Tuple[int, Any, Any]], fn: Callable, *, workers: int, label: str,
                 store: Optional[ResultsStore], stage: str, candidate: str,
                 key_of: Callable[[int, Any, Any], str],
                 handle: Callable[[int, Any, Dict[str, Any], bool], Tuple[Dict[str, Any], Optional[float]]],
                 progress=None, max_inflight: Optional[int] = None,
                 prepare: Optional[Callable[[Any], None]] = None) -> Dict[str, int]:
    pending: Dict[int, Tuple[int, Any, str]] = {}
    counts = {"new": 0, "resumed": 0}

    def feeder():
        seq = itertools.count()
        for ord_, params, job in items:
            key = key_of(ord_, params, job)
            row = store.get(key) if store is not None else None
            if row is not None:
                handle(ord_, params, row["metrics"], True)
                counts["resumed"] += 1
                if progress is not None:
                    progress.tick(resumed=True)
                continue
            if prepare is not None:
                prepare(job)
            pending[next(seq)] = (ord_, params, key)
            yield job

    for i, res in pool_imap_bounded(fn, feeder(), workers, max_inflight=max_inflight, label=label or "wfa"):
        ord_, params, key = pending.pop(i)
        metrics = normalize(res)
        to_store, score = handle(ord_, params, metrics, False)
        if store is not None:
            store.put(key, stage, candidate, params, to_store, ord=ord_, score=score)
        counts["new"] += 1
        if progress is not None:
            progress.tick(worker_peak_mb=metrics.get("_peak_rss_mb") if isinstance(metrics, dict) else None)
    return counts


# ── Candidates & Planning ───────────────────────────────────────────────────
def candidates_from_report(stage_a, report, n, include_rejected, only=None):
    out = []
    for cid, rows in stage_a.items():
        if only and cid not in only:
            continue
        accepted = (report.get("candidates", {}).get(cid) or {}).get("accepted")
        if not include_rejected and not (accepted is True or accepted == "True"):
            continue
        ranked = sorted((r for r in rows if r["score"] is not None and r["score"] > float("-inf")), key=lambda r: -r["score"])
        if ranked:
            out.append({"id": cid, "configs": [r["params"] for r in ranked[:n]]})
    return out


def candidates_from_ids(ids, n, seed):
    from backend.analys.alpha.strategies import BY_ID, configs
    by_id = BY_ID
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Không có chiến lược: {missing}; có: {sorted(by_id)}")
    return [{"id": i, "configs": configs(by_id[i], n, seed)} for i in ids]


def candidates_from_list(raw):
    from backend.analys.alpha.strategies import BY_ID
    by_id = BY_ID
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


def plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_dir, base_frame="1m"):
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        for cand in candidates:
            for ci, cfg_params in enumerate(cand["configs"]):
                keys.append((fi, cand["id"], ci))
                jobs.append(BacktestJob([(cand["id"], cfg_params)], (fold["train_start_ts"], fold["train_end_ts"]), "level", is_risk,
                                        rpt, symbols, shared_dir, base_frame))
    return keys, jobs


def plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_dir, base_frame="1m", regime_maps=None):
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if not chosen[fi]:
            continue
        rmap = regime_maps[fi] if regime_maps else None
        for sf in ("level", "extreme"):
            keys.append((fi, sf))
            jobs.append(BacktestJob(chosen[fi], (fold["test_start_ts"], fold["test_end_ts"]), sf, risk, rpt, symbols, shared_dir, base_frame,
                                    rmap))
    return keys, jobs


def plan_regime_jobs(chosen, folds, symbols, risk, rpt, shared_dir, base_frame="1m", learn_from=None):
    from backend.analys.metrics.regime import OBSERVE
    is_risk = {**risk, "kill_switch_dd_pct": 0}
    keys, jobs = [], []
    for fi, fold in enumerate(folds):
        if chosen[fi]:
            keys.append(fi)
            lo = fold["train_start_ts"] if learn_from is None else min(int(learn_from), fold["train_start_ts"])
            jobs.append(BacktestJob(chosen[fi], (lo, fold["train_end_ts"]), "level", is_risk, rpt, symbols, shared_dir,
                                    base_frame, {cid: OBSERVE for cid, _ in chosen[fi]}))
    return keys, jobs


def run_portfolio_wfa(candidates, symbols, start_ts, end_ts, cfg, risk, risk_per_trade_pct, workers, shared_root,
                      store=None, progress=None, base_frame="1m", regime="off", regime_learn_from=None) -> Dict[str, Any]:
    from dataclasses import asdict
    from backend.analys.param import iso_date
    from backend.analys.validation.wfa.wfa import PortfolioWfaConfig, aggregate_folds, evaluate_gate, generate_folds, is_score, select_best
    from backend.analys.validation.carlo.carlo import measure_turnover
    cfg = cfg if isinstance(cfg, PortfolioWfaConfig) else PortfolioWfaConfig.from_dict(cfg)
    symbols, rpt = list(symbols), float(risk_per_trade_pct)
    folds = generate_folds(int(start_ts), int(end_ts), cfg.train_days, cfg.test_days, cfg.step_days)
    if not folds:
        raise ValueError("Khoảng thời gian không đủ để tạo ít nhất 1 fold")
    os.makedirs(shared_root, exist_ok=True)
    t0 = time.time()

    is_keys, is_jobs = plan_is_jobs(candidates, folds, symbols, risk, rpt, shared_root, base_frame)
    if progress is not None:
        progress.start_stage("WFA-IS", len(is_jobs))
    is_res = _pool_shared(is_jobs, workers, f"[WFA-IS] {len(folds)} fold × {len(is_jobs) // len(folds)} job", shared_root,
                          store, "wfa_is", progress)
    is_by = {k: m for k, m in zip(is_keys, is_res)}
    print(f"[WFA-IS] {len(is_jobs)} job IS xong ({time.time() - t0:.0f}s)", flush=True)

    chosen: List[List[Tuple[str, Dict[str, Any]]]] = []
    picks: List[Dict[str, Optional[int]]] = []
    for fi in range(len(folds)):
        pick, items = {}, []
        for cand in candidates:
            rows = [is_by[(fi, cand["id"], ci)] for ci in range(len(cand["configs"]))]
            best = select_best(rows, cfg.min_is_trades)
            pick[cand["id"]] = best
            if best is not None:
                items.append((cand["id"], cand["configs"][best]))
        chosen.append(items)
        picks.append(pick)

    regime_maps, train_regime = None, {}
    if regime == "learn":
        from backend.analys.metrics.regime import learn_map
        rg_keys, rg_jobs = plan_regime_jobs(chosen, folds, symbols, risk, rpt, shared_root, base_frame, regime_learn_from)
        if progress is not None:
            progress.start_stage("WFA-REGIME", len(rg_jobs))
        rg_res = _pool_shared(rg_jobs, workers, f"[WFA-REGIME] {len(rg_jobs)} job", shared_root, store, "wfa_regime", progress) if rg_jobs else []
        train_regime = {fi: m.get("by_regime") or {} for fi, m in zip(rg_keys, rg_res)}
        regime_maps = [{cid: rc for cid, rc in learn_map(train_regime.get(fi, {}), [c for c, _ in chosen[fi]]).items() if rc}
                       for fi in range(len(folds))]
        print(f"[WFA-REGIME] {len(rg_jobs)} job học regime xong ({time.time() - t0:.0f}s)", flush=True)
    elif regime != "off":
        raise ValueError(f"regime phải là off|learn (nhận {regime!r})")

    oos_keys, oos_jobs = plan_oos_jobs(chosen, folds, symbols, risk, rpt, shared_root, base_frame, regime_maps)
    if progress is not None:
        progress.start_stage("WFA-OOS", len(oos_jobs))
    oos_res = _pool_shared(oos_jobs, workers, f"[WFA-OOS] {len(oos_jobs)} job", shared_root, store, "wfa_oos", progress) if oos_jobs else []
    oos_by = {k: m for k, m in zip(oos_keys, oos_res)}
    print(f"[WFA-OOS] {len(oos_jobs)} job OOS xong ({time.time() - t0:.0f}s)", flush=True)

    fold_records = []
    for fi, fold in enumerate(folds):
        cids = [c["id"] for c in candidates]
        is_sel = {cid: _strip(is_by[(fi, cid, picks[fi][cid])]) | {"score": round(is_score(is_by[(fi, cid, picks[fi][cid])],
                                                                                          cfg.min_is_trades), 4)}
                  for cid in cids if picks[fi][cid] is not None}
        rec = {
            "fold": fi + 1,
            "train": [iso_date(fold["train_start_ts"]), iso_date(fold["train_end_ts"])],
            "test": [iso_date(fold["test_start_ts"]), iso_date(fold["test_end_ts"])],
            "train_ts": [fold["train_start_ts"], fold["train_end_ts"]], "test_ts": [fold["test_start_ts"], fold["test_end_ts"]],
            "status": "TRADED" if chosen[fi] else "NO_TRADE",
            "chosen_idx": picks[fi],
            "chosen": {cid: (candidates[i]["configs"][picks[fi][cid]] if picks[fi][cid] is not None else None)
                       for i, cid in enumerate(cids)},
            "is": is_sel,
            "is_ret_pct": round(sum(m["ret_pct"] for m in is_sel.values()) / len(is_sel), 2) if is_sel else 0.0,
            "is_candidates": {cid: [{"ret_pct": m["ret_pct"], "mdd_pct": m["mdd_pct"], "trades": m["trades"],
                                     "score": is_score(m, cfg.min_is_trades)}
                                    for m in (is_by[(fi, cid, ci)] for ci in range(len(candidates[i]["configs"])))]
                              for i, cid in enumerate(cids)},
        }
        trades_map = {}
        for sf in ("level", "extreme"):
            m = oos_by.get((fi, sf))
            m_stripped = None if m is None else _strip(m)
            rec[sf] = m_stripped
            rec[f"oos_{sf}"] = m_stripped
            daily_list = list(m.get("daily", [])) if m and m.get("daily") is not None else [0.0] * cfg.test_days
            first = (m or {}).get("_daily_start") or iso_date(fold["test_start_ts"])
            dates_list = [f"{d:%Y-%m-%d}" for d in pd.date_range(first, periods=len(daily_list), freq="D")]
            rec[f"{sf}_daily"] = daily_list
            rec[f"oos_daily_{sf}"] = daily_list
            rec[f"oos_daily_dates_{sf}"] = dates_list
            rec[f"{sf}_stats"] = None if m is None else m.get("stats")
            t_count = len(m.get("trades_detail", [])) if m and m.get("trades_detail") else (m.get("trades", 0) if m else 0)
            rec[f"{sf}_trades_count"] = t_count
            trades_map[sf] = t_count
            rec[f"{sf}_shock"] = None if m is None else m.get("shock")
            rec[f"{sf}_turnover"] = None if m is None else m.get("turnover")
        rec["shock"] = (oos_by.get((fi, "extreme")) or {}).get("shock")
        m_ext = oos_by.get((fi, "extreme"))
        if m_ext is None:
            rec["turnover"] = measure_turnover([], len(rec["oos_daily_extreme"]))
        else:
            rec["turnover"] = m_ext.get("turnover") or {"turnover_daily": None, "note": "kết quả fold cũ không lưu vòng quay", "sum": 0.0,
                                                        "days": len(rec["oos_daily_extreme"]), "trades": 0, "measurable": 0}
        rec["trades"] = {sf: (rec[f"oos_{sf}"]["trades"] if rec[f"oos_{sf}"] else 0) for sf in ("level", "extreme")}
        rec["halted_at"] = {sf: (rec[f"oos_{sf}"]["halted_at"] if rec[f"oos_{sf}"] else None) for sf in ("level", "extreme")}
        if regime_maps is not None:
            rec["regime_map"] = regime_maps[fi]
            rec["train_by_regime"] = train_regime.get(fi, {})
        if rec["extreme"] and rec["level"] and rec["extreme"].get("trades") and rec["level"].get("trades"):
            diff = rec["extreme"]["ret_pct"] - rec["level"]["ret_pct"]
            rec["extreme_edge"] = round(diff, 2)
            rec["extreme_edge_per_trade_bps"] = round(diff / rec["level"]["trades"] * 100, 1)
        fold_records.append(rec)

    summary = aggregate_folds(fold_records, cfg)
    gate = evaluate_gate(summary)
    all_res = [m for m in list(is_res) + list(oos_res) if m]

    return {
        "config": asdict(cfg),
        "risk": risk,
        "risk_per_trade_pct": rpt,
        "symbols": symbols,
        **({"regime": regime} if regime != "off" else {}),
        **({"regime_learn_from": iso_date(regime_learn_from)} if regime != "off" and regime_learn_from else {}),
        "window": [iso_date(start_ts), iso_date(end_ts)],
        "candidates": [{"id": c["id"], "configs": c["configs"]} for c in candidates],
        "folds": fold_records,
        "summary": summary,
        "gate": gate,
        "aggregate": summary,
        "mc": summary.get("mc"),
        "mem": {
            "peak_rss_mb": max([(m.get("_peak_rss_mb") or 0.0) for m in all_res], default=0.0),
            "rss_anon_mb": max([(m.get("_rss_anon_mb") or 0.0) for m in all_res], default=0.0),
        },
    }


def print_summary(res: Dict[str, Any]) -> None:
    s, g = res["summary"], res["gate"]
    print(f"\ncửa sổ {res['window'][0]} → {res['window'][1]} | train {res['config']['train_days']}d test {res['config']['test_days']}d "
          f"| rủi ro/lệnh {res['risk_per_trade_pct']}% | {s['n_folds']} fold")
    print(f"{'#':>2} {'train':23s} {'test':23s} {'IS%':>7} {'OOSlv%':>7} {'OOSex%':>7} {'MDDex':>6} {'lệnh':>5} {'kill':>4}  chọn")
    for f in res["folds"]:
        ex, lv = f.get("oos_extreme"), f.get("oos_level")
        pick = ",".join(f"{cid}#{i}" for cid, i in f["chosen_idx"].items() if i is not None) or "-"
        trades_ex = f.get("trades", {}).get("extreme", 0) if isinstance(f.get("trades"), dict) else 0
        halted = f.get("halted_at", {}).get("extreme") if isinstance(f.get("halted_at"), dict) else None
        print(f"{f['fold']:>2} {f['train'][0]}→{f['train'][1]:10s} {f['test'][0]}→{f['test'][1]:10s} {f['is_ret_pct']:7.2f} "
              f"{(lv['ret_pct'] if lv else 0.0):7.2f} {(ex['ret_pct'] if ex else 0.0):7.2f} {(ex['mdd_pct'] if ex else 0.0):6.2f} "
              f"{trades_ex:5d} {'có' if halted else '-':>4}  {pick}")
    if "param_stability" in s:
        print("ổn định tham số: " + "; ".join(f"{cid} {v['share'] * 100:.0f}% ({v['distinct']} cấu hình/{v['folds_chosen']} fold)"
                                              for cid, v in s["param_stability"].items()))
    c, w = s.get("compounded_oos_ret_pct", {}), s.get("worst_fold_mdd_pct", {})
    oos_trades = s.get("oos_trades", {}).get("extreme", 0) if isinstance(s.get("oos_trades"), dict) else 0
    print(f"OOS lãi kép: level {c.get('level')}% | extreme {c.get('extreme')}% | MDD fold tệ nhất: level {w.get('level')}% | extreme {w.get('extreme')}% "
          f"| {s.get('oos_days', 0)} ngày, lệnh {oos_trades}")
    mc = s.get("mc")
    if mc:
        print(f"MC {mc.get('simulations')}×{mc.get('horizon_days')}d (block {mc.get('block_days')}, ngày MTM extreme): lãi trung vị {mc.get('median_ret_pct')}%, "
              f"p05 {mc.get('p05_ret_pct')}%, MDD p50 {mc.get('mdd_p50_pct')}% / p95 {mc.get('mdd_p95_pct')}%, P(MDD>=30%) {mc.get('p_mdd_ge_ruin_pct')}%")
    else:
        print("MC: không đủ ngày OOS")
    print("GATE: " + ("ĐẠT" if g.get("passed") else "KHÔNG ĐẠT"))
    for c_item in g.get("checks", {}).values():
        print(f"  [{'ok' if c_item.get('passed') else 'XX'}] {c_item.get('label')}: {c_item.get('actual')} (cần {c_item.get('required')})")
    m = res.get("mem", {})
    print(f"đỉnh RAM/worker {m.get('peak_rss_mb', 0):.0f} MB (riêng {m.get('rss_anon_mb', 0):.0f} MB + mmap dùng chung)", flush=True)


def run_book_wfa(*args, **kwargs):
    from backend.jobs.tasks import run_book_wfa as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "run_book_wfa",
    "run_portfolio_wfa",
    "plan_is_jobs",
    "plan_oos_jobs",
    "plan_regime_jobs",
    "ResultsStore",
    "stream_stage",
    "candidates_from_ids",
    "candidates_from_list",
    "candidates_from_report",
    "load_items",
    "print_summary",
    "DB_NAME",
    "COMMIT_EVERY",
    "COMMIT_SECONDS",
    "SCHEMA_VERSION",
]
