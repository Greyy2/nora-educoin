"""GET /api/studio/overview — số liệu tổng hợp chung cho Backtest + Paper + Live (chỉ đọc, tính từ dữ liệu đã có)."""
import json
import os
import time
from typing import Any, Dict, Optional, cast

import numpy as np
import pandas as pd
from fastapi import APIRouter

from backend.jobs import runner as batch_jobs
from backend.data.data import daily_close
from backend.analys.metrics import stats as nstats
try:
    from backend.adapter import exchange as led
    from backend.adapter.exchange import find_bot_dir, get_bot_trades, list_bots
except ImportError:
    led = None
    def find_bot_dir(*args, **kwargs): return None
    def get_bot_trades(*args, **kwargs): return []
    def list_bots(*args, **kwargs): return []
from backend.routes.studio import _bt_row

overview_router = APIRouter(prefix="/api/studio", tags=["overview"])
_TR_CACHE: Dict[str, Any] = {}


def _bt_trades(job_id: str) -> Optional[Dict[str, Any]]:
    """Lệnh đã đóng của 1 backtest: số lệnh, số thắng, tổng lãi, tổng lỗ (đệm theo mtime)."""
    path = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _TR_CACHE.get(job_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            tl = json.load(fh).get("trade_list") or []
    except (OSError, ValueError):
        return None
    p = [t["pnl"] for t in tl if isinstance(t.get("pnl"), (int, float))]
    agg = {"n": len(p), "wins": sum(1 for x in p if x > 0), "gain": sum(x for x in p if x > 0), "loss": -sum(x for x in p if x < 0)}
    _TR_CACHE[job_id] = (mt, agg)
    return agg


def _group(bots, mode_paper: bool) -> Dict[str, Any]:
    g = {"bots": 0, "running": 0, "pnl_usd": 0.0, "capital": 0.0, "closed": 0, "wins": 0, "gain": 0.0, "loss": 0.0, "mdd_pct": None}
    for b in bots:
        if (b.get("mode") == "paper") != mode_paper:
            continue
        g["bots"] += 1
        g["running"] += b.get("status") == "running"
        g["pnl_usd"] += float(b.get("pnl_usd") or 0.0)
        g["capital"] += float(b.get("capital") or 0.0)
        if isinstance(b.get("mdd_pct"), (int, float)):
            g["mdd_pct"] = b["mdd_pct"] if g["mdd_pct"] is None else max(g["mdd_pct"], b["mdd_pct"])
        for t in get_bot_trades(b["bot_id"]):
            if isinstance(t.get("pnl"), (int, float)):
                g["closed"] += 1
                g["wins"] += t["pnl"] > 0
                g["gain"] += max(t["pnl"], 0.0)
                g["loss"] += max(-t["pnl"], 0.0)
    g["pnl_usd"] = round(g["pnl_usd"], 4)
    g["pnl_pct"] = round(g["pnl_usd"] / g["capital"] * 100, 4) if g["capital"] else None
    return g


@overview_router.get("/overview")
def get_overview() -> Dict[str, Any]:
    rows = [x for x in (_bt_row(j) for j in batch_jobs.list_jobs(500, "book_backtest") if j.get("status") == "done") if x]
    bt: Dict[str, Any] = {"runs": len(rows), "closed": 0, "wins": 0, "gain": 0.0, "loss": 0.0}
    for r in rows:
        a = _bt_trades(r["id"])
        if a:
            bt["closed"] += a["n"]; bt["wins"] += a["wins"]; bt["gain"] += a["gain"]; bt["loss"] += a["loss"]
    rets = [r["ret_pct"] for r in rows if isinstance(r.get("ret_pct"), (int, float))]
    mdds = [r["mdd_pct"] for r in rows if isinstance(r.get("mdd_pct"), (int, float))]
    bt["avg_ret_pct"] = round(sum(rets) / len(rets), 4) if rets else None
    bt["mdd_pct"] = max(mdds) if mdds else None
    pnl = [r["pnl_usd"] for r in rows if isinstance(r.get("pnl_usd"), (int, float))]
    bt["pnl_usd"] = round(sum(pnl), 2) if pnl else None
    bots = list_bots()
    paper, live = _group(bots, True), _group(bots, False)
    parts = (bt, paper, live)
    closed = sum(p["closed"] for p in parts)
    gain, loss = sum(p["gain"] for p in parts), sum(p["loss"] for p in parts)
    all_mdd = [m for m in (bt["mdd_pct"], paper["mdd_pct"], live["mdd_pct"]) if m is not None]
    for p in parts:
        p["win_pct"] = round(p["wins"] / p["closed"] * 100, 2) if p["closed"] else None
        p["gain"], p["loss"] = round(p["gain"], 4), round(p["loss"], 4)
    bot_n = paper["bots"] + live["bots"]
    total = {"active_bots": paper["running"] + live["running"], "runs": bt["runs"] + bot_n, "trades": closed,
             "win_pct": round(sum(p["wins"] for p in parts) / closed * 100, 2) if closed else None,
             "profit_factor": round(gain / loss, 3) if loss > 0 else None,
             "bot_pnl_usd": round(paper["pnl_usd"] + live["pnl_usd"], 4) if bot_n else None,
             "avg_bt_ret_pct": bt["avg_ret_pct"], "max_mdd_pct": max(all_mdd) if all_mdd else None}
    return {"total": total, "backtest": bt, "paper": paper, "live": live}


# ─── Đánh giá tổng hợp: mỗi lần backtest và mỗi bot là một chuỗi lợi suất ngày, gộp đều theo ngày ───
_DAY = 86_400_000
_SRC_CACHE: Dict[str, Any] = {}     # khoá nguồn -> (mtime, chuỗi lợi suất ngày | None)
_SERIES_CACHE: Dict[str, Any] = {}


def _daily_returns(times, equity, base: float) -> Optional[pd.Series]:
    """Đường vốn (ms, equity) -> lợi suất ngày (đóng cuối ngày UTC; ngày thiếu giữ nguyên = lợi suất 0). `base`: vốn đầu để tính ngày đầu."""
    if len(times) < 2 or not base or base <= 0:
        return None
    df = pd.Series(np.asarray(equity, dtype=float), index=(np.asarray(times, dtype=np.int64) // _DAY)).groupby(level=0).last()
    df = df.reindex(range(int(df.index.values[0]), int(df.index.values[-1]) + 1)).ffill()
    prev = df.shift(1)
    prev.iloc[0] = base
    r = (df / prev - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    return r if len(r) else None


def _src_backtest(job_id: str) -> Optional[pd.Series]:
    path = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _SRC_CACHE.get("bt:" + job_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            eq = json.load(fh).get("equity_curve") or []
    except (OSError, ValueError):
        return None
    r = _daily_returns([e["time"] for e in eq], [e["equity"] for e in eq], eq[0]["equity"]) if len(eq) > 1 else None
    _SRC_CACHE["bt:" + job_id] = (mt, r)
    return r


def _src_bot(bot_id: str) -> Optional[pd.Series]:
    b_dir = find_bot_dir(bot_id)
    if not b_dir:
        return None
    try:
        mt = os.path.getmtime(os.path.join(b_dir, "equity.jsonl"))
    except OSError:
        return None
    hit = _SRC_CACHE.get("bot:" + bot_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(os.path.join(b_dir, "bot.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        snap = led.snapshot(b_dir, meta) if led is not None else {}       # chỉ đọc
    except (OSError, ValueError):
        return None
    ser = snap.get("series") or []
    cap = float(snap.get("capital") or 10000.0)
    r = _daily_returns([x["time"] for x in ser], [x["equity"] for x in ser], cap) if ser else None
    _SRC_CACHE["bot:" + bot_id] = (mt, r)
    return r


def _rolling_sharpe(r: np.ndarray, w: int):
    out = []
    for i in range(len(r)):
        v = nstats.returns_stats(r[i - w + 1:i + 1], keys=("sharpe",))["sharpe"] if i >= w - 1 else None
        out.append(round(v, 4) if v is not None else None)
    return out


def _monthly(dates: pd.DatetimeIndex, nav: np.ndarray) -> list:
    s = pd.Series(nav, index=dates)
    ym = s.groupby([dates.year, dates.month]).last()  # type: ignore[attr-defined]
    out, prev = [], 10000.0
    for key, v in ym.items():
        y, m = key  # type: ignore
        out.append({"y": int(y), "m": int(m), "ret": round((float(v) / prev - 1.0) * 100.0, 4)})
        prev = float(v)
    return out


@overview_router.get("/overview/series")
def get_overview_series() -> Dict[str, Any]:
    """Đường NAV tổng hợp: trung bình đều lợi suất ngày của mọi nguồn (backtest xong + bot Paper/Live) có dữ liệu ngày đó."""
    srcs, n_bt, n_paper, n_live = [], 0, 0, 0
    for j in batch_jobs.list_jobs(500, "book_backtest"):
        if j.get("status") == "done":
            r = _src_backtest(j["id"])
            if r is not None:
                srcs.append(r); n_bt += 1
    for b in list_bots():
        r = _src_bot(b["bot_id"])
        if r is not None:
            srcs.append(r)
            if b.get("mode") == "paper":
                n_paper += 1
            else:
                n_live += 1
    key = f"{len(srcs)}:{sum(len(x) for x in srcs)}:{sum(float(x.iloc[-1]) for x in srcs):.10f}"
    hit = _SERIES_CACHE.get("v")
    if hit and hit[0] == key:
        return hit[1]
    meta = {"sources": {"backtest": n_bt, "paper": n_paper, "live": n_live, "total": len(srcs)}}
    if not srcs:
        return {**meta, "dates": [], "available": False}
    df = pd.concat(srcs, axis=1)
    cnt = df.notna().sum(axis=1)
    r = cast(pd.Series, df.mean(axis=1, skipna=True)).dropna().sort_index()
    cnt = cnt.reindex(r.index)
    idx = pd.to_datetime(r.index.to_numpy() * _DAY, unit="ms")
    nav = 10000.0 * np.cumprod(1.0 + r.to_numpy())
    peak = np.maximum.accumulate(np.r_[10000.0, nav])[1:]
    dd = (nav / peak - 1.0) * 100.0
    bench = None
    bc = daily_close("BTC@perp", int(time.time() * 1000))
    if bc is not None:
        lab = pd.Series(bc[1], index=(bc[0] - _DAY) // _DAY)
        lab = lab[~lab.index.duplicated(keep="last")]
        b = lab.reindex(r.index).ffill()
        if b.notna().any() and float(b.dropna().iloc[0]) > 0:
            b = b.bfill()
            bench = [round(float(x), 2) for x in 10000.0 * b.to_numpy() / float(b.iloc[0])]
    ra = r.to_numpy()
    st = nstats.returns_stats(ra, keys=("sharpe", "sortino", "cagr"))
    pct = lambda v: round(v * 100.0, 4) if v is not None else None
    rnd = lambda v: round(v, 4) if v is not None else None
    out = {**meta, "available": True, "dates": [f"{d:%Y-%m-%d}" for d in idx], "nav": [round(float(x), 2) for x in nav],
           "drawdown": [round(float(x), 4) for x in dd], "benchmark_nav": bench, "benchmark": "BTC",
           "monthly": _monthly(idx, nav), "rolling_sharpe": {"d30": _rolling_sharpe(ra, 30), "d90": _rolling_sharpe(ra, 90)},
           "active_sources": [int(x) for x in cnt.to_numpy()],
           "kpi": {"ret_pct": round(float(nav[-1] / 10000.0 - 1.0) * 100.0, 4), "cagr_pct": pct(st["cagr"]), "mdd_pct": round(float(dd.min()), 4),
                   "sharpe": rnd(st["sharpe"]), "sortino": rnd(st["sortino"]), "win_days_pct": round(float((ra > 0).mean()) * 100.0, 2),
                   "bench_ret_pct": round(bench[-1] / 10000.0 * 100.0 - 100.0, 4) if bench else None}}
    _SERIES_CACHE["v"] = (key, out)
    return out
