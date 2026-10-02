"""Thống kê một tầng (docs/funnel_contract.md §3): nhóm vào/ra, lý do loại, theo chiến lược, sống sót theo tham số, top alpha.

Chỉ đọc kho SQLite bằng truy vấn tổng hợp (GROUP BY) hoặc duyệt streaming các cột số -> bộ nhớ O(số alpha × 8 byte × 7 cột) dù tới 1.000.000 alpha.
`in` = nhóm được chấm ở tầng (đã có số đo tầng đó), `out` = phần qua. Mọi phân phối dùng CÙNG 30 bin cố định chia đều khoảng phân vị 1–99 của nhóm `in`
(giá trị ngoài khoảng được dồn vào bin đầu/cuối nên tổng số đếm = quy mô nhóm).
"""
import json
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from . import gates
from .storage import RunStore

N_BINS = 30
P_LO, P_HI = 1, 99
DIST_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_rate", "profit_factor")
TOP_N = 20


def r3(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if math.isfinite(v) else None


def scalar_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
    """Chỉ giữ giá trị vô hướng của metrics_json (bỏ danh sách/dict lớn như fold_detail, by_symbol)."""
    return {k: v for k, v in m.items() if isinstance(v, (int, float, bool, str)) or v is None}


def make_edges(vals: np.ndarray) -> Optional[np.ndarray]:
    v = vals[np.isfinite(vals)]
    if v.size == 0:
        return None
    lo, hi = float(np.percentile(v, P_LO)), float(np.percentile(v, P_HI))
    if not hi > lo:
        pad = max(abs(lo) * 1e-6, 1e-6)
        lo, hi = lo - pad, hi + pad
    return np.linspace(lo, hi, N_BINS + 1)


def histogram(vals: np.ndarray, edges: Optional[np.ndarray]) -> Dict[str, Any]:
    v = vals[np.isfinite(vals)]
    if edges is None:
        return {"bins": [], "n": int(v.size), "p5": None, "p50": None, "p95": None}
    counts, _ = np.histogram(np.clip(v, edges[0], edges[-1]), bins=edges)
    out = {"bins": [{"lo": r3(edges[i]), "hi": r3(edges[i + 1]), "count": int(counts[i])} for i in range(N_BINS)], "n": int(v.size)}
    for name, q in (("p5", 5), ("p50", 50), ("p95", 95)):
        out[name] = r3(np.percentile(v, q)) if v.size else None
    return out


def _fetch_numeric(store: RunStore, stage: str):
    cols = ("m.passed", "m.ret_pct", "m.mdd_pct", "m.sharpe", "m.trades", "m.win_rate", "m.profit_factor", "m.score")
    strat: List[str] = []
    data: List[List[float]] = [[] for _ in cols]
    with store._lock:
        cur = store._con.cursor()
        cur.execute(f"SELECT a.strategy, {', '.join(cols)} FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id WHERE m.stage=?", (stage,))
    while True:
        with store._lock:
            batch = cur.fetchmany(20000)
        if not batch:
            break
        for row in batch:
            strat.append(row[0])
            for i, x in enumerate(row[1:]):
                data[i].append(float("nan") if x is None else float(x))
    arr = {c.split(".")[1]: np.asarray(d, dtype=float) for c, d in zip(cols, data)}
    return np.asarray(strat, dtype=object), arr


def stage_stats(store: RunStore, stage: str, top_n: int = TOP_N) -> Dict[str, Any]:
    if stage not in gates.STAGE_IDX:
        raise KeyError(stage)
    k = gates.STAGE_IDX[stage]
    counts = store.stage_counts()[k]
    out: Dict[str, Any] = {"stage": stage, "label": gates.STAGE_LABELS[stage], "input": counts["done"], "eligible": counts["input"],
                           "passed": counts["passed"], "rejected": counts["rejected"]}
    with store._lock:
        reasons = store._con.execute("SELECT reject_code, COUNT(*) FROM alphas WHERE rejected_stage=? GROUP BY reject_code ORDER BY COUNT(*) DESC, reject_code",
                                     (stage,)).fetchall()
    out["reject_reasons"] = [{"code": c, "label": gates.reason_label(c), "count": int(n)} for c, n in reasons]

    if k == 0:
        return {**out, **_stats_s0(store, top_n)}

    strat, a = _fetch_numeric(store, stage)
    passed = a["passed"] == 1
    dists: Dict[str, Any] = {}
    for key in DIST_KEYS:
        v = a[key]
        edges = make_edges(v)
        dists[key] = {"in": histogram(v, edges), "out": histogram(v[passed], edges)}
    out["distributions"] = dists

    by = []
    best_pass = _best_per_strategy(store, stage, True)
    best_any = _best_per_strategy(store, stage, False)
    for s in sorted(set(strat.tolist())):
        sel = strat == s
        n_in, n_pass = int(sel.sum()), int((sel & passed).sum())
        by.append({"strategy": s, "input": n_in, "passed": n_pass, "pass_rate": round(n_pass / n_in * 100, 1) if n_in else 0.0,
                   "median_ret_pct": r3(np.nanmedian(a["ret_pct"][sel])) if n_in else None,
                   "median_mdd_pct": r3(np.nanmedian(a["mdd_pct"][sel])) if n_in else None,
                   "best_alpha_id": best_pass.get(s) or best_any.get(s)})
    out["by_strategy"] = by
    out["param_survival"] = _param_survival(store, stage)
    out["top"] = _top(store, stage, top_n)
    if stage == "S2_antiluck":
        out["strategy_level"] = {s: store.get_kv(f"s2:{s}") for s in sorted(set(strat.tolist()))}
    return out


def _best_per_strategy(store: RunStore, stage: str, only_passed: bool) -> Dict[str, str]:
    q = ("SELECT a.strategy, m.alpha_id, MAX(m.score) FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id WHERE m.stage=? "
         + ("AND m.passed=1 " if only_passed else "") + "AND m.score IS NOT NULL GROUP BY a.strategy")
    with store._lock:
        return {s: a for s, a, _ in store._con.execute(q, (stage,)).fetchall()}


def _param_survival(store: RunStore, stage: str) -> List[Dict[str, Any]]:
    """Mỗi (chiến lược, tham số, giá trị): số alpha vào / số qua. Gộp theo params_json trong SQL (số tổ hợp <= kích thước lưới) rồi cộng dồn theo giá trị."""
    if stage == "S0_generate":
        q = "SELECT strategy, params_json, COUNT(*), SUM(CASE WHEN rejected_idx IS NULL THEN 1 ELSE 0 END) FROM alphas GROUP BY strategy, params_json"
        args: tuple = ()
    else:
        q = ("SELECT a.strategy, a.params_json, COUNT(*), SUM(m.passed) FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
             "WHERE m.stage=? GROUP BY a.strategy, a.params_json")
        args = (stage,)
    acc: Dict[tuple, List[int]] = defaultdict(lambda: [0, 0])
    with store._lock:
        rows = store._con.execute(q, args).fetchall()
    for s, pj, n, p in rows:
        for key, val in json.loads(pj).items():
            c = acc[(s, key, json.dumps(val))]
            c[0] += n
            c[1] += int(p or 0)
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for (s, key, vj), (n, p) in acc.items():
        grouped[(s, key)].append({"value": json.loads(vj), "input": n, "passed": p})
    out = []
    for (s, key) in sorted(grouped):
        vals = sorted(grouped[(s, key)], key=lambda x: (not isinstance(x["value"], (int, float)), x["value"] if isinstance(x["value"], (int, float)) else str(x["value"])))
        out.append({"strategy": s, "param": key, "values": vals})
    return out


def _top(store: RunStore, stage: str, n: int) -> List[Dict[str, Any]]:
    with store._lock:
        rows = store._con.execute(
            "SELECT m.alpha_id, a.strategy, a.params_json, m.metrics_json, a.final_scale FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
            "WHERE m.stage=? AND m.passed=1 ORDER BY m.score IS NULL, m.score DESC, a.ord LIMIT ?", (stage, int(n))).fetchall()
    return [{"alpha_id": a, "strategy": s, "params": json.loads(p), "metrics": scalar_metrics(json.loads(m)), "final_scale": fs} for a, s, p, m, fs in rows]


def _stats_s0(store: RunStore, top_n: int) -> Dict[str, Any]:
    with store._lock:
        rows = store._con.execute("SELECT strategy, COUNT(*), SUM(CASE WHEN rejected_idx IS NULL THEN 1 ELSE 0 END) FROM alphas GROUP BY strategy ORDER BY strategy").fetchall()
    best = _best_per_strategy(store, "S1_backtest", False)
    by = [{"strategy": s, "input": int(n), "passed": int(p), "pass_rate": round(p / n * 100, 1) if n else 0.0,
           "median_ret_pct": None, "median_mdd_pct": None, "best_alpha_id": best.get(s)} for s, n, p in rows]
    top = []
    with store._lock:
        trows = store._con.execute(
            "SELECT m.alpha_id, a.strategy, a.params_json, m.metrics_json, a.final_scale FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
            "WHERE m.stage='S1_backtest' ORDER BY m.score IS NULL, m.score DESC, a.ord LIMIT ?", (int(top_n),)).fetchall()
    for a, s, p, m, fs in trows:
        top.append({"alpha_id": a, "strategy": s, "params": json.loads(p), "metrics": scalar_metrics(json.loads(m)), "final_scale": fs})
    return {"distributions": {}, "by_strategy": by, "param_survival": _param_survival(store, "S0_generate"), "top": top}
