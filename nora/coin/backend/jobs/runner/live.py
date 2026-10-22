"""Runner cho các tác vụ Live Trading: Bot execution, Live Supervisor, Live Chart streaming.

Consolidated into backend/jobs/runner/live.py.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.data import data as dat
from backend.data.data import EngineData, FRAME_MS, MINUTE_MS, read_manifest, read_1m, aggregate_frame
from backend.adapter.exchange import find_bot_dir, get_bot_trades, _read_json
from backend.jobs import runner
from backend.core import live as lv
from backend.models.storage import json_default

log = logging.getLogger("backend.jobs.runner.live")
INTERVAL_S = 30.0
_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None

MAX_CANDLES = 6000
MAX_SIGNALS = 3000
_CACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}
_CACHE_MAX = 24
_RCACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}
EXITS = ("SL", "TP", "TRAIL", "TIMEOUT", "SIGNAL")


# ── Supervisor ──────────────────────────────────────────────────────────────
def _launch_params(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = meta.get("launch_params")
    if not p and meta.get("job_id"):
        try:
            p = (runner._read_meta(runner._job_dir(meta["job_id"])) or {}).get("params")
        except runner.JobError:
            p = None
    return dict(p) if p else None


def supervise_once(launch: Optional[Callable[[str, Dict[str, Any]], str]] = None) -> List[Dict[str, Any]]:
    """Một vòng: chạy lại mọi bot ở trạng thái `resuming`. Trả [{bot_id, action, job_id?}]."""
    launch = launch or runner.launch
    acts: List[Dict[str, Any]] = []
    with _LOCK:
        for mode in lv.MODES:
            root = os.path.join(lv.data_home(), "live", mode)
            for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
                d = os.path.join(root, name)
                meta = lv._read_json(os.path.join(d, "bot.json"))
                if not meta or lv.bot_status(meta, d) != "resuming":
                    continue
                jid = meta.get("job_id")
                jm = runner._read_meta(runner.job_dir(jid)) if jid else None
                if jm and jm.get("state") == "running" and runner._alive(jm.get("pid")):
                    continue
                params = _launch_params(meta)
                if not params:
                    acts.append({"bot_id": name, "action": "no_params"})
                    continue
                fails = int(meta.get("resume_failures") or 0) + 1
                if fails > lv.MAX_RESUME_FAILURES:
                    lv.set_status(d, "failed", resume_failures=fails)
                    acts.append({"bot_id": name, "action": "failed"})
                    continue
                params.update(bot_id=name, mode=mode, resume=True)
                try:
                    job_id = launch("live_bot", params)
                except Exception as e:
                    log.warning("không chạy lại được %s: %s", name, e)
                    acts.append({"bot_id": name, "action": "launch_error", "error": str(e)})
                    continue
                lv.set_status(d, meta.get("status") or "running", job_id=job_id, resume_failures=fails, resume_count=int(meta.get("resume_count") or 0) + 1,
                              last_resume_at=int(time.time() * 1000))
                acts.append({"bot_id": name, "action": "resumed", "job_id": job_id})
    return acts


def _loop(interval: float) -> None:
    while True:
        try:
            for a in supervise_once():
                log.info("supervisor: %s", a)
        except Exception:
            log.exception("supervisor lỗi")
        time.sleep(interval)


def start(interval: float = INTERVAL_S) -> Optional[threading.Thread]:
    """Bật luồng supervisor (một lần). NORA_LIVE_SUPERVISOR=0 tắt."""
    global _THREAD
    if os.environ.get("NORA_LIVE_SUPERVISOR", "1") == "0" or (_THREAD is not None and _THREAD.is_alive()):
        return _THREAD
    _THREAD = threading.Thread(target=_loop, args=(interval,), name="live-supervisor", daemon=True)
    _THREAD.start()
    return _THREAD


# ── Chart and Replay ────────────────────────────────────────────────────────
def _put(cache: Dict, key: Tuple, val: Dict[str, Any]) -> None:
    cache[key] = (time.time(), val)
    while len(cache) > _CACHE_MAX:
        cache.pop(min(cache, key=lambda k: cache[k][0]))


def _frame_of(spec_frames: List[str], base: str, frame: Optional[str]) -> str:
    if frame:
        if frame not in FRAME_MS:
            raise ValueError(f"Khung {frame!r} không hợp lệ")
        return frame
    return max(spec_frames + [base], key=lambda f: FRAME_MS[f])


class GapData(EngineData):
    """Nguồn dữ liệu cho replay: catalog + nến 1m REST (đoạn catalog chưa phủ)."""

    def __init__(self, gap_1m: Dict[str, pd.DataFrame]):
        super().__init__()
        self.gap = {dat.normalize_symbol(s): g for s, g in gap_1m.items() if g is not None and not g.empty}
        self._tails: Dict[Tuple[str, str], pd.DataFrame] = {}

    def _cat_close(self, symbol: str) -> int:
        m = read_manifest(symbol)
        return int(m["end_ts"]) + MINUTE_MS if m else 0

    def _tail_start(self, symbol: str, frame: str) -> int:
        f = FRAME_MS[frame]
        return self._cat_close(symbol) // f * f

    def _tail(self, symbol: str, frame: str) -> pd.DataFrame:
        norm = dat.normalize_symbol(symbol)
        key = (norm, frame)
        if key in self._tails:
            return self._tails[key]
        g = self.gap.get(norm)
        cols = ["open_time", "open", "high", "low", "close", "volume"]
        if g is None:
            out = pd.DataFrame(columns=cols)
        else:
            ts, cc = self._tail_start(symbol, frame), self._cat_close(symbol)
            cat = dat.load_candles(symbol, "1m", ts, cc - MINUTE_MS) if ts < cc else pd.DataFrame(columns=cols)
            m1 = dat.fill_missing_1m_candles(pd.concat([cat[cols], g[cols]], ignore_index=True).sort_values("open_time")
                                             .drop_duplicates("open_time", keep="last").reset_index(drop=True))
            from backend.analys.signal import LiveSignals
            out = LiveSignals._aggregate(m1[cols], frame, MINUTE_MS)
            out = out[out["open_time"] >= ts].reset_index(drop=True)
        self._tails[key] = out
        return out

    def candles(self, symbol, frame, start, end, columns=None, use_cache=True):
        norm = dat.normalize_symbol(symbol)
        if norm not in self.gap:
            return super().candles(symbol, frame, start, end, columns, use_cache)
        ts = self._tail_start(symbol, frame)
        parts = []
        if start < ts:
            parts.append(super().candles(symbol, frame, start, min(end, ts - 1), None, use_cache))
        tail = self._tail(symbol, frame)
        if not tail.empty:
            parts.append(tail[(tail["open_time"] >= start) & (tail["open_time"] <= end)])
        parts = [p for p in parts if p is not None and len(p)]
        if not parts:
            return super().candles(symbol, frame, start, min(end, ts - 1), columns, use_cache)
        df = pd.concat(parts, ignore_index=True).drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
        return df[[c for c in columns if c in df.columns]] if columns else df

    def exec_arrays(self, symbol, frame, start, end):
        norm = dat.normalize_symbol(symbol)
        g = self.gap.get(norm)
        if g is None:
            return super().exec_arrays(symbol, frame, start, end)
        cc = self._cat_close(symbol)
        cat = read_1m(symbol, max(start, 0), min(end, cc - MINUTE_MS)) if start < cc else None
        real = g[(g["is_filled"] == 0) & (g["open_time"] >= max(start, cc)) & (g["open_time"] <= end)] if "is_filled" in g.columns \
            else g[(g["open_time"] >= max(start, cc)) & (g["open_time"] <= end)]
        add = {"t": real["open_time"].to_numpy(dtype=np.int64), "o": real["open"].to_numpy(dtype=np.float64), "h": real["high"].to_numpy(dtype=np.float64),
               "l": real["low"].to_numpy(dtype=np.float64), "c": real["close"].to_numpy(dtype=np.float64), "v": real["volume"].to_numpy(dtype=np.float64)}
        arr = add if cat is None or len(cat["t"]) == 0 else {k: np.concatenate([cat[k], add[k]]) for k in add}
        return aggregate_frame(arr, frame)

    def manifest(self, symbol):
        m = super().manifest(symbol)
        g = self.gap.get(dat.normalize_symbol(symbol))
        if m and g is not None:
            m = dict(m)
            m["end_ts"] = int(g["open_time"].iloc[-1])
        return m

    def shared_plan(self, eng):
        return None


def _candle_rows(df: pd.DataFrame) -> List[List[float]]:
    return [[int(r.open_time), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)] for r in df.itertuples(index=False)]


candle_points = _candle_rows


def _norm_fill(e: Dict[str, Any]) -> Dict[str, Any]:
    kind = e.get("kind") or e.get("tag") or "ENTRY"
    price = e.get("price") if e.get("price") is not None else e.get("px")
    return {"t": e.get("ts") or e.get("t"), "symbol": e.get("symbol"), "side": e.get("side"), "kind": kind, "price": price,
            "qty": e.get("qty"), "fee": e.get("fee"), "strategy": e.get("strategy"), "catchup": bool(e.get("catchup", False))}


def _exit_kind(pos: Any) -> str:
    st = getattr(getattr(pos, "status", None), "name", "")
    if st in ("TP", "SL"):
        return st
    r = str(getattr(pos, "close_reason", "") or "").lower()
    return "TIMEOUT" if "thời gian" in r else "TRAIL" if "trail" in r else "SIGNAL"


def _replay_fills(positions: List[Any], orders: List[Any], open_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_pos: Dict[int, List[Any]] = {}
    for o in orders:
        by_pos.setdefault(o.position_id, []).append(o)
    out: List[Dict[str, Any]] = []
    for p in positions:
        entry_side = "BUY" if getattr(p.pos_type, "name", "") == "LONG" else "SELL"
        n_in = 0
        for o in sorted(by_pos.get(p.result_id, []), key=lambda x: x.order_time):
            side = o.order_type.name
            kind = ("ENTRY" if n_in == 0 else "DCA") if side == entry_side else _exit_kind(p)
            n_in += side == entry_side
            out.append({"t": int(o.order_time), "symbol": p.symbol, "side": side, "kind": kind, "price": float(o.order_price), "qty": float(o.qty),
                        "fee": float(o.fee_usd), "catchup": False})
    for q in open_positions:
        out.append({"t": int(q["opened"]), "symbol": q["symbol"], "side": "BUY" if q["side"] == "LONG" else "SELL", "kind": "ENTRY",
                    "price": float(q["entry_price"]), "qty": float(q["qty"]), "fee": None, "catchup": False, "open": True})
    return sorted(out, key=lambda r: r["t"])


def _group(kind: str) -> str:
    return "entry" if kind == "ENTRY" else "dca" if kind == "DCA" else "exit"


def match_fills(live: List[Dict[str, Any]], replay: List[Dict[str, Any]], tol_ms: int) -> Dict[str, Any]:
    matched, only_live, used = [], [], set()
    for lf in live:
        best, bd = None, None
        for i, rf in enumerate(replay):
            if i in used or rf["symbol"] != lf["symbol"] or _group(rf["kind"]) != _group(lf["kind"]) or rf["side"] != lf["side"]:
                continue
            d = abs((rf["t"] or 0) - (lf["t"] or 0))
            if d <= tol_ms and (bd is None or d < bd):
                best, bd = i, d
        if best is None:
            only_live.append(lf)
            continue
        used.add(best)
        rf = replay[best]
        adverse = 1 if str(lf["side"]).upper() in ("BUY", "LONG") else -1
        bps = (lf["price"] - rf["price"]) / rf["price"] * 1e4 * adverse if rf["price"] else None
        matched.append({"symbol": lf["symbol"], "group": _group(lf["kind"]), "kind_live": lf["kind"], "kind_replay": rf["kind"], "side": lf["side"],
                        "t_live": lf["t"], "t_replay": rf["t"], "dt_ms": (lf["t"] or 0) - (rf["t"] or 0),
                        "price_live": lf["price"], "price_replay": rf["price"], "bps": None if bps is None else round(bps, 2)})
    only_replay = [rf for i, rf in enumerate(replay) if i not in used]
    return {"matched": matched, "only_live": only_live, "only_replay": only_replay, "tol_ms": tol_ms}


def _signals(symbol: str, strategies: List[Dict[str, Any]], frames: Dict[str, pd.DataFrame], base: str, view_start: int, started: int,
             vol_out: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    from backend.analys.signal.compute import evaluate_signals
    res = evaluate_signals(symbol, strategies, frames, base)
    t = res["t"]
    sel = t >= view_start
    out: List[Dict[str, Any]] = []
    for e in res["entries"]:
        if vol_out is not None and e.get("vol") is not None:
            vol_out[e["strategy"]] = (np.asarray(t, dtype=np.int64), np.asarray(e["vol"], dtype=float))
        for kind, arr in (("entry", e["match"]), ("exit", e["stop"]), ("dca", e.get("dca"))):
            if arr is None:
                continue
            idx = np.flatnonzero(np.asarray(arr, dtype=bool) & sel)
            for i in idx:
                out.append({"t": int(t[i]), "kind": kind, "strategy": e["strategy"], "side": e["side"], "price": float(res["close"][i]), "live": bool(t[i] >= started)})
    out.sort(key=lambda r: r["t"])
    return out[-MAX_SIGNALS:]


def _cycles(fills: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    net: Dict[Tuple[str, str], float] = {}
    cyc: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in sorted(fills, key=lambda r: r["t"] or 0):
        key = (f["symbol"], f.get("strategy") or "")
        q = float(f["qty"] or 0) * (1 if str(f["side"]).upper() == "BUY" else -1)
        n0 = net.get(key, 0.0)
        if abs(n0) < 1e-12:
            cyc[key] = {"t0": f["t"], "layers": 0, "last": None}
        if f["kind"] in ("ENTRY", "DCA"):
            c = cyc[key]
            c["layers"] += 1
            c["last"] = float(f["price"])
        net[key] = n0 + q
        if abs(net[key]) < 1e-12:
            net[key] = 0.0
    return {k: c for k, c in cyc.items() if abs(net.get(k, 0.0)) > 1e-12}


def _levels(position: Dict[str, Any], avg: float, last_fill: Optional[float], layers: int, sign: float, vol_pct: Optional[float]) -> Dict[str, Any]:
    from backend.analys.position import position_size as ps
    unit_mode = str(position.get("exit_unit") or "pct")
    if unit_mode == "atr":
        if not vol_pct or not vol_pct > 0:
            return {"sl": None, "tp": None, "dca": None, "source": "thiếu ATR lúc vào"}
        unit = float(vol_pct)
    else:
        unit = 1.0
    sl_pct = float(position.get("stop_loss_rate") or 0.0) * unit
    tp_pct = float(position.get("take_profit_rate") or 0.0) * unit
    n_dca = int(position.get("dca_max_layers") or 0)
    step = float(position.get("dca_step_pct") or 0.0) * unit
    out: Dict[str, Any] = {"sl": None, "tp": None, "dca": None, "source": "theo cấu hình chiến lược"}
    if sl_pct > 0 and str(position.get("sl_anchor") or "avg") == "avg":
        out["sl"] = ps.sl_level(avg, sl_pct, sign)
    if tp_pct > 0:
        out["tp"] = ps.tp_level(avg, tp_pct, sign)
    if n_dca > 0 and step > 0 and layers - 1 < n_dca and last_fill:
        out["dca"] = ps.dca_level(last_fill, step, sign)
    return out


def _positions_view(b_dir: str, bot: Dict[str, Any], strategies: List[Dict[str, Any]], fills: List[Dict[str, Any]], vols: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    from backend.core import live_ledger as led
    snap = led.snapshot(b_dir, bot)
    cyc = _cycles(fills)
    pos_of = {st["id"]: st.get("position") or {} for st in strategies}
    out = []
    for p in snap["positions"]:
        c = cyc.get((p["symbol"], p["strategy"]))
        sign = 1.0 if p["is_long"] else -1.0
        vol = None
        tv = vols.get(p["symbol"], {}).get(p["strategy"])
        if tv is not None and c is not None and c["t0"]:
            i = int(np.searchsorted(tv[0], int(c["t0"]), side="right")) - 1
            if i >= 0 and np.isfinite(tv[1][i]):
                vol = float(tv[1][i])
        lv = _levels(pos_of.get(p["strategy"], {}), p["avg_price"], c["last"] if c else None, c["layers"] if c else 1, sign, vol)
        out.append({"symbol": p["symbol"], "strategy": p["strategy"], "side": p["side"], "qty": p["qty"], "avg_price": p["avg_price"], "mark": p["mark"],
                    "unrealized_usd": p["unrealized_usd"], "t0": c["t0"] if c else None, "layers": c["layers"] if c else None, "levels": lv})
    return out, snap["trades"]


def _replay(bot: Dict[str, Any], src: Dict[str, Any], warmed: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
    from backend.jobs.runner.backtest import WARMUP
    from backend.core.engine import PortfolioEngine
    from backend.analys.alpha.code.plan import RiskConfig
    start = int(bot["started_at"]) // MINUTE_MS * MINUTE_MS
    end = now_ms // MINUTE_MS * MINUTE_MS - MINUTE_MS
    if end <= start:
        return {"fills": [], "window": [start, end], "note": "Bot chưa chạy đủ một nến để replay"}
    gap = {s: w["gap"] for s, w in warmed.items()}
    eng = PortfolioEngine(src["symbols"], src["strategies"], start - WARMUP, end, trade_start_ts=start, initial_capital=float(bot.get("capital") or 1000.0),
                          risk=RiskConfig.from_dict(src["risk"]), close_at_end=False, base_frame=src["base_frame"], shared_dir=None, data=GapData(gap))
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    fills = _replay_fills(res["positions"], res["orders"], eng.open_positions())
    return {"fills": fills, "window": [start, end], "note": "Replay bắt đầu từ lúc bot khởi động (không có lệnh vào bù khi khởi động)"}


def build_chart(bot_id: str, frame: Optional[str] = None, replay: bool = False, now_ms: Optional[int] = None) -> Dict[str, Any]:
    b_dir = find_bot_dir(bot_id)
    if b_dir is None:
        raise LookupError(f"Không tìm thấy bot {bot_id}")
    bot = _read_json(os.path.join(b_dir, "bot.json"))
    now_ms = int(now_ms or time.time() * 1000)
    trades = get_bot_trades(bot_id)
    fills_live = [_norm_fill(t) for t in trades]
    last_fill = max([f["t"] or 0 for f in fills_live] + [0])
    ckey = (bot_id, frame or "", bool(replay), last_fill, now_ms // 60000)
    hit = _CACHE.get(ckey)
    if hit:
        return hit[1]

    lp = bot.get("launch_params") or {}
    src = resolve_live_source(lp)
    if not src["strategies"]:
        raise ValueError("Bot dùng chiến lược bản địa (không có cây tín hiệu): chưa hỗ trợ biểu đồ tín hiệu")
    base = src["base_frame"]
    warnings: List[str] = []
    started = int(bot.get("started_at") or now_ms)
    signal_tf = lp.get("signal_tf") or lp.get("base_frame") or bot.get("base_frame") or base or "1h"
    vols: Dict[str, Dict[str, Any]] = {}

    out_candles: Dict[str, Any] = {}
    out_signals: Dict[str, Any] = {}
    warmed: Dict[str, Any] = {}
    sig_frames: List[str] = []
    disp = None
    from backend.analys.signal import LiveSignals

    for symbol in src["symbols"]:
        groups: Dict[frozenset, Tuple[LiveSignals, List[Dict[str, Any]]]] = {}
        for st in src["strategies"]:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            ls = LiveSignals(symbol, st, base)
            key = frozenset(ls.required_frames)
            if key in groups:
                groups[key][1].append(st)
            else:
                groups[key] = (ls, [st])
        sigs: List[Dict[str, Any]] = []
        candles_df = None
        for key, (ls, sts) in groups.items():
            sig_frames += [f for f in ls.required_frames if f != base]
            disp = disp or _frame_of([signal_tf], base, frame)
            try:
                ls.warm_start(now_ms)
            except Exception as e:
                warnings.append(f"{symbol}: warm_start: {e}")
            fview = disp
            view_start = started - min(ls.warmup_ms, 300 * FRAME_MS[fview])
            try:
                sigs += _signals(symbol, sts, {fr: ls.frames[fr] for fr in ls.required_frames if fr in ls.frames}, base, view_start, started, vols.setdefault(symbol, {}))
            except Exception as e:
                warnings.append(f"{symbol}: _signals: {e}")
            if candles_df is None:
                if fview in ls.frames and not ls.frames[fview].empty:
                    candles_df = ls.frames[fview]
                elif "1m" in ls.frames and not ls.frames["1m"].empty and FRAME_MS[fview] >= MINUTE_MS:
                    m1 = ls.frames["1m"]
                    candles_df = LiveSignals._aggregate(m1[["open_time", "open", "high", "low", "close", "volume"]], fview, MINUTE_MS)
                else:
                    bars_file = os.path.join(b_dir, "bars.jsonl")
                    if os.path.isfile(bars_file):
                        try:
                            import json as _json
                            rows_b = []
                            norm_sym = symbol.replace("@perp", "").split("-")[0]
                            with open(bars_file, "r", encoding="utf-8") as bf:
                                for line in bf:
                                    line = line.strip()
                                    if line:
                                        item = _json.loads(line)
                                        if norm_sym in str(item.get("symbol", "")):
                                            rows_b.append({
                                                "open_time": int(item.get("ts_open") or 0),
                                                "open": float(item.get("open") or 0.0),
                                                "high": float(item.get("high") or 0.0),
                                                "low": float(item.get("low") or 0.0),
                                                "close": float(item.get("close") or 0.0),
                                                "volume": float(item.get("volume") or 0.0),
                                            })
                            if rows_b:
                                b_df = pd.DataFrame(rows_b).sort_values("open_time").drop_duplicates("open_time", keep="last")
                                candles_df = LiveSignals._aggregate(b_df, fview, MINUTE_MS)
                        except Exception:
                            pass
                if candles_df is None or candles_df.empty:
                    warnings.append(f"{symbol}: không dựng được nến khung {fview}")
                else:
                    candles_df = candles_df[candles_df["open_time"] >= view_start].tail(MAX_CANDLES)
                    candles_df = candles_df.sort_values("open_time", ascending=True).drop_duplicates("open_time", keep="last")
            if replay:
                try:
                    m = read_manifest(symbol)
                    cc = int(m["end_ts"]) + MINUTE_MS if m else 0
                    last_closed = now_ms // MINUTE_MS * MINUTE_MS
                    gap = ls.rest_1m(cc, last_closed - MINUTE_MS) if last_closed - MINUTE_MS >= cc else pd.DataFrame()
                    warmed.setdefault(symbol, {"gap": gap})
                except Exception:
                    pass
        out_signals[symbol] = sigs
        out_candles[symbol] = _candle_rows(candles_df) if candles_df is not None else []
    result: Dict[str, Any] = {"bot_id": bot_id, "frame": disp or base, "base_frame": base, "signal_frames": sorted(set(sig_frames)), "signal_tf": signal_tf, "symbols": src["symbols"],
                              "started_at": started, "now": now_ms, "candles": out_candles, "signals": out_signals, "fills_live": fills_live,
                              "positions": [], "trades": [], "fills_replay": [], "compare": None, "replay": None, "warnings": warnings}
    try:
        result["positions"], result["trades"] = _positions_view(b_dir, bot, src["strategies"], fills_live, vols)
    except Exception as e:
        warnings.append(f"Không dựng được vị thế/mức giá: {type(e).__name__}: {e}")
    if replay:
        rkey = (bot_id, last_fill, now_ms // 600000)
        rhit = _RCACHE.get(rkey)
        if rhit is None:
            try:
                r = _replay(bot, src, warmed, now_ms)
            except Exception as e:
                r = {"fills": [], "window": None, "note": None, "error": f"{type(e).__name__}: {e}"}
                warnings.append(f"Replay lỗi: {r['error']}")
            else:
                _put(_RCACHE, rkey, r)
        else:
            r = rhit[1]
        result["fills_replay"] = r["fills"]
        result["replay"] = {"window": r.get("window"), "note": r.get("note")}
        result["compare"] = match_fills(fills_live, r["fills"], 2 * FRAME_MS[base] + 60_000)
    result["parity"] = None
    _put(_CACHE, ckey, result)
    return result


# ── Live Execution ──────────────────────────────────────────────────────────
def _picker_store() -> str:
    from backend.models.storage import data_home
    return os.path.join(data_home(), "alpha", "picker_backtest.json")


def picker_backtest_record(job_id: str, config: Dict[str, Any]) -> None:
    path = _picker_store()
    try:
        with open(path, encoding="utf-8") as fh:
            db = json.load(fh)
    except (OSError, ValueError):
        db = {}
    db[str(job_id)] = {**config, "ts": time.time()}
    for k in sorted(db, key=lambda x: db[x].get("ts", 0))[:-200]:
        db.pop(k, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, default=json_default)
    os.replace(tmp, path)


def picker_backtest_get(job_id: str):
    try:
        with open(_picker_store(), encoding="utf-8") as fh:
            return json.load(fh).get(str(job_id))
    except (OSError, ValueError):
        return None


def resolve_live_source(params: Dict[str, Any]) -> Dict[str, Any]:
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.code.plan import build_plan
    from backend.analys.alpha import strategies as alpha_store
    from backend.data.data import resolve_symbols
    from backend.jobs.tasks import resolve_strategy

    symbols = params.get("symbols") or ["BTC-USDT-SWAP"]
    if isinstance(symbols, str):
        symbols = [x.strip() for x in symbols.split(",") if x.strip()]
    names = resolve_symbols(list(symbols))

    if params.get("strategy_type") == "proxima" or params.get("alpha_id") == "proxima":
        return {
            "strategies": [{"id": "proxima_decoupled"}],
            "risk": None,
            "symbols": [f"{n}@perp" for n in names],
            "base_frame": params.get("base_frame") or "1m",
            "native": None,
            "label": "strategy:proxima_decoupled",
            "name": "proxima_decoupled",
            "strategy_type": "proxima",
        }
    signal_tf = params.get("signal_tf") or None
    run_frame = params.get("base_frame") or signal_tf or None
    if signal_tf:
        from backend.analys.param import FRAME_MS
        if signal_tf not in FRAME_MS:
            raise ValueError(f"signal_tf {signal_tf!r} không hợp lệ")
        if run_frame and FRAME_MS[run_frame] > FRAME_MS[signal_tf]:
            raise ValueError(f"Khung chạy {run_frame} lớn hơn khung tín hiệu {signal_tf}")
    code, position, risk, label, name = params.get("code"), dict(params.get("position") or {}), None, "custom", None
    if code and not params.get("alpha_id") and params.get("params"):
        position.update(resolve_strategy(code=code, signal_tf=signal_tf, params=params["params"])["params"])
    if not code and params.get("alpha_id"):
        rec = alpha_store.get_user_alpha(str(params["alpha_id"]))
        if rec is not None:
            code, label, name = rec["code"], f"alpha:{rec['id']}", rec.get("name")
            cfg = rec.get("config") or {}
            position = {**(cfg.get("position") or {}), **position, **resolve_strategy(params["alpha_id"], None, signal_tf, params.get("params"))["params"]}
            risk = cfg.get("risk")
        else:
            rs = resolve_strategy(params["alpha_id"], None, signal_tf, params.get("params"), names, params.get("book_source"))
            return {"strategies": [rs["strategy"]], "risk": None, "symbols": [f"{n}@perp" for n in names], "base_frame": run_frame or "1h", "native": None,
                    "label": f"system:{params['alpha_id']}", "name": params["alpha_id"]}
    if not code:
        raise ValueError("Cần code hoặc alpha_id để chạy bot")
    program = compile_code(code)
    if signal_tf and not getattr(program, "is_native", False) and program.timeframe != signal_tf:
        raise ValueError(f"Chiến lược khai báo timeframe {program.timeframe}, không phải khung đã backtest lãi {signal_tf}: không thể chạy bot ở khung khác")
    if getattr(program, "is_native", False):
        return {"strategies": [], "risk": None, "symbols": [f"{n}@perp" for n in (resolve_symbols(program.symbols) if program.symbols and not params.get("symbols") else names)],
                "base_frame": run_frame or getattr(program, "timeframe", None) or "1h",
                "native": {"cls": program.strategy_cls, "id": program.name, "params": {}}, "label": f"native:{program.name}", "name": program.name}
    plan = build_plan(program, names, position=position or None, run_frame=run_frame)
    return {"strategies": plan.strategies, "risk": risk or plan.risk, "symbols": plan.symbols, "base_frame": plan.base_frame, "native": None, "label": label, "name": name or getattr(program, "name", None) or plan.strategies[0]["id"]}


def launch_fingerprint(params: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core import live as lv
    if not src.get("strategies"):
        return {"strategy_fingerprint": None, "fingerprint_expected": None, "fingerprint_match": None}
    fp = lv.strategy_fingerprint(src["strategies"], src["symbols"], src["base_frame"])
    exp, match = None, None
    if params.get("signal_tf") and (params.get("alpha_id") or params.get("code")):
        base = {k: params[k] for k in ("alpha_id", "code", "symbols", "signal_tf", "book_source") if params.get(k)}
        if not base.get("code") and not base.get("alpha_id") and params.get("backtest_job_id"):
            rec = picker_backtest_get(params["backtest_job_id"])
            base = {k: rec[k] for k in ("alpha_id", "signal_tf", "symbols", "params", "book_source") if rec and rec.get(k) is not None} if rec else None
        try:
            if base is None:
                raise ValueError(f"không có cấu hình đã lưu cho job backtest {params['backtest_job_id']}")
            ref = resolve_live_source({**base, "base_frame": params["signal_tf"]})
            exp = lv.strategy_fingerprint(ref["strategies"], ref["symbols"], ref["base_frame"])
            if ref["base_frame"] != src["base_frame"]:
                exp = lv.strategy_fingerprint(ref["strategies"], ref["symbols"], src["base_frame"])
            match = exp == fp
        except Exception as e:
            exp, match = f"error: {type(e).__name__}: {e}", False
    return {"strategy_fingerprint": fp, "fingerprint_expected": exp, "fingerprint_match": match}


def run_live_bot(params: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core import live as lv

    mode = str(params.get("mode", "paper"))
    capital = float(params.get("capital") or 1000.0)
    confirm_live = bool(params.get("confirm_live", False))
    resume = bool(params.get("resume", False))
    bot_id = str(params.get("bot_id") or lv.new_bot_id(mode))
    launch_params = {k: v for k, v in params.items() if k != "resume"}
    src = resolve_live_source(params)
    is_proxima = (params.get("strategy_type") == "proxima" or params.get("alpha_id") == "proxima" or src.get("strategy_type") == "proxima")
    if is_proxima:
        if params.get("execution_client") == "sandbox" or params.get("use_sandbox"):
            from backend.core.strategy_proxima import ProximaNativeStrategy
            src["native"] = {
                "cls": ProximaNativeStrategy,
                "id": "PROXIMA_NATIVE",
                "params": {
                    "sleeve_id": f"sleeve_{bot_id}",
                    "sleeve_capital": capital,
                    "r_ratio": float(params.get("r_ratio") or 0.15),
                    "vl_mult": float(params.get("vl_mult") or 1.0),
                    "tp_mult": float(params.get("tp_mult") or 0.8),
                    "f_mult": float(params.get("f_mult") or 1.0),
                    "anchor_frame": str(params.get("anchor_tf") or "1h"),
                    "shadow_mode": bool(params.get("shadow", False)),
                }
            }
            src["strategies"] = []
            src["label"] = f"Proxima Native ({len(src.get('symbols', []))} markets) · Nora Sandbox Paper"
        else:
            from backend.adapter.runner import run_decoupled_proxima_live
            return run_decoupled_proxima_live(params)
    if mode == "testnet":
        print(f"[TESTNET] chế độ vị thế OKX demo: {lv.ensure_net_position_mode()}", flush=True)
    bot_dir = None

    def start_node(resume_: bool):
        nonlocal bot_dir
        nd = lv.build_node(mode, src["strategies"], src["symbols"], capital, base_frame=src["base_frame"], confirm_live=confirm_live, bot_id=bot_id,
                           risk=src["risk"], native=src["native"], enter_on_start=bool(params.get("enter_on_start", False)) and not resume_, resume=resume_,
                           launch_params=launch_params)
        bot_dir = nd.nora.bot_dir
        print(f"[{mode.upper()}] {bot_id}{' (chạy lại)' if resume_ else ''}: {src['label']} · {len(nd.nora.slots)} slot · {len(src['symbols'])} tài sản · khung {src['base_frame']}", flush=True)
        if nd.nora.signals:
            t0 = time.time()
            stats = lv.warm_start(nd)
            print(f"[{mode.upper()}] nạp lịch sử tín hiệu xong ({time.time() - t0:.0f}s): " + ", ".join(f"{x['symbol']}:+{x['rest_rows']}rest" for x in stats), flush=True)
        return nd

    try:
        node = start_node(resume)
    except Exception:
        if bot_dir:
            lv.set_status(bot_dir, "failed")
        raise
    try:
        ident = launch_fingerprint(params, src)
    except Exception as e:
        ident = {"strategy_fingerprint": None, "fingerprint_expected": None, "fingerprint_match": None, "fingerprint_error": f"{type(e).__name__}: {e}"}
    node.nora.recorder.record_event("strategy_identity", ident)
    lv.set_status(bot_dir, "starting", strategy=src.get("name") or src["label"], job_id=os.path.basename(os.environ.get("NORA_JOB_DIR", "")) or None, **ident)
    stop_file = os.path.join(bot_dir, "stop")

    def stop_watcher():
        while True:
            flag = lv.stop_flag(bot_dir)
            if flag is not None:
                close = bool(flag.get("close", True))
                print(f"[{mode.upper()}] Nhận cờ dừng cho {bot_id} (close={close}), đang dừng...", flush=True)
                node.kernel.loop.call_soon_threadsafe(lv.apply_stop, node, close)
                deadline = time.time() + 45.0
                while close and not lv.own_flat(node) and time.time() < deadline:
                    time.sleep(0.5)
                node.kernel.loop.call_soon_threadsafe(node.stop)
                break
            time.sleep(2.0)

    threading.Thread(target=stop_watcher, daemon=True).start()
    from backend.models.storage import pid_start_ticks
    lv.set_status(bot_dir, "running", pid=os.getpid(), pid_start=pid_start_ticks(os.getpid()), resume_failures=0)
    print(f"[{mode.upper()}] Bot {bot_id} đang chạy...", flush=True)
    failures = 0
    while True:
        reason = None
        try:
            reason = lv.run_node(node)
        finally:
            node.dispose()
        if os.path.isfile(stop_file):
            lv.set_status(bot_dir, "stopped")
            break
        if reason is None:
            node.nora.recorder.record_event("process_exit", {"note": "tiến trình thoát không do người dùng dừng; không đóng vị thế, chờ supervisor chạy lại"})
            break
        failures = 1 if getattr(node.nora, "was_ready", False) else failures + 1
        if failures >= lv.MAX_DATA_ATTEMPTS:
            msg = f"dữ liệu OKX không lên/đứng ({reason}) sau {failures} lần kết nối lại"
            node.nora.recorder.record_event("error", {"error": msg, "reason": reason, "attempts": failures})
            lv.set_status(bot_dir, "failed", error=msg, error_reason=reason)
            print(f"[{mode.upper()}] {bot_id} THẤT BẠI: {msg}", flush=True)
            return {"bot_id": bot_id, "mode": mode, "status": "failed", "error": msg}
        wait = lv.BACKOFF_S[min(failures - 1, len(lv.BACKOFF_S) - 1)]
        node.nora.recorder.record_event("data_retry", {"reason": reason, "attempt": failures, "wait_s": wait})
        print(f"[{mode.upper()}] {bot_id}: dữ liệu lỗi ({reason}), dựng lại node sau {wait:.0f}s (lần {failures}/{lv.MAX_DATA_ATTEMPTS})", flush=True)
        time.sleep(wait)
        node = start_node(True)
        lv.set_status(bot_dir, "running", pid=os.getpid(), pid_start=pid_start_ticks(os.getpid()))

    return {"bot_id": bot_id, "mode": mode, "status": "stopped" if os.path.isfile(stop_file) else "running"}


__all__ = [
    "run_live_bot",
    "resolve_live_source",
    "launch_fingerprint",
    "supervise_once",
    "start",
    "build_chart",
    "candle_points",
    "match_fills",
    "GapData",
    "INTERVAL_S",
    "picker_backtest_record",
    "picker_backtest_get",
]
