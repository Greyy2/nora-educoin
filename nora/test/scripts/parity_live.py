#!/usr/bin/env python3
"""Script kiểm tra đồng nhất 4 tầng giữa Backtest và Live/Paper bot (P18 B2-B5).

4 Tầng:
- Tầng 1 (Dữ liệu): so `bars.jsonl` với nến REST OKX (1m gộp lên khung chạy, có cache) trong cửa sổ chạy của bot — OHLC
- Tầng 2 (Tín hiệu): `signals.jsonl` (mỗi nến một dòng, ghi luôn bật) so với tín hiệu TÍNH LẠI bằng code backend trên cùng dữ liệu
- Tầng 3 (Ý định lệnh): phát lại máy trạng thái vào/thoát theo tín hiệu đã ghi, so với fill thật (vào lệnh phải có nến match; nến match khi đang flat phải có fill hoặc reject)
- Tầng 4 (Giá khớp): đo độ trượt giá market (bps, trung vị/p95), độ trễ đặt lệnh (ms)

Mọi tầng có 0 mục được so sánh (hoặc ít hơn --min-bars ở Tầng 1-2) -> "KHÔNG ĐỦ DỮ LIỆU" (status INSUFFICIENT) và KHÔNG tính là đạt; tổng thể chỉ đạt khi cả 4 tầng PASS.
"""
import argparse
import json
import math
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import numpy as np
import pandas as pd

from backend.data import data as dat
from backend.data.data import FRAME_MS, MINUTE_MS
from backend.nautilus.live import find_bot_dir, _read_json, data_home
from backend.models.storage import NORA_DATA_ROOT
from backend.jobs.tasks import resolve_live_source


def load_live_bars(bot_dir: str) -> Dict[str, pd.DataFrame]:
    """Đọc `bars.jsonl` của bot thành DataFrame theo từng symbol."""
    bars_file = os.path.join(bot_dir, "bars.jsonl")
    if not os.path.isfile(bars_file):
        return {}
    records: Dict[str, List[Dict[str, Any]]] = {}
    with open(bars_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                sym = row.get("symbol")
                if sym:
                    records.setdefault(sym, []).append(row)
            except Exception:
                continue
    dfs = {}
    for sym, rows in records.items():
        df = pd.DataFrame(rows)
        if not df.empty:
            df["open_time"] = df["ts_open"]
            df = df.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
            dfs[sym] = df
    return dfs


def load_live_events(bot_dir: str) -> List[Dict[str, Any]]:
    """Đọc `events.jsonl` của bot."""
    ev_file = os.path.join(bot_dir, "events.jsonl")
    if not os.path.isfile(ev_file):
        return []
    events = []
    with open(ev_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT"
DEFAULT_MIN_BARS = 4
PRICE_RTOL = 1e-6


def _status(checked: int, ok: bool, need: int = 1) -> str:
    """0 mục (hoặc ít hơn `need`) được so sánh -> INSUFFICIENT, không bao giờ PASS."""
    if checked < max(1, need):
        return INSUFFICIENT
    return PASS if ok else FAIL


def load_live_signals(bot_dir: str) -> List[Dict[str, Any]]:
    """Đọc `signals.jsonl` (ts = giờ đóng nến, symbol, slot, match, stop, dca)."""
    path = os.path.join(bot_dir, "signals.jsonl")
    out: List[Dict[str, Any]] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out


def _bot_frame(bot_dir: str) -> str:
    return str(_read_json(os.path.join(bot_dir, "bot.json")).get("base_frame") or "1m")


def rest_1m_cached(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Nến 1m ĐÃ ĐÓNG [start_ms, end_ms] (open_time) từ REST OKX (crawl.fetch_rest_candles), nhớ trên đĩa data/cache/parity_rest/<BASE>.pkl: lần sau chỉ tải phần chưa có."""
    import requests
    from backend.data.crawl import fetch_rest_candles
    base = dat.base_name(symbol)
    d = os.path.join(NORA_DATA_ROOT, "cache", "parity_rest")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{base}.pkl")
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    cached = pd.read_pickle(path) if os.path.isfile(path) else pd.DataFrame(columns=cols)
    have = (not cached.empty) and int(cached["open_time"].min()) <= start_ms and int(cached["open_time"].max()) >= end_ms
    if not have:
        with requests.Session() as sess:
            new = fetch_rest_candles(sess, base, int(start_ms), int(end_ms))
        cached = pd.concat([x[cols] for x in (cached, new) if not x.empty] or [cached[cols]], ignore_index=True).sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
        cached.to_pickle(path)
    return cached[(cached["open_time"] >= start_ms) & (cached["open_time"] <= end_ms)].reset_index(drop=True)


def check_level1_data(bot_dir: str, live_bars: Dict[str, pd.DataFrame], rest_fetch: Optional[Callable[[str, int, int], pd.DataFrame]] = None,
                      min_bars: int = DEFAULT_MIN_BARS) -> Dict[str, Any]:
    """Tầng 1 (Dữ liệu): `bars.jsonl` vs nến REST OKX (1m gộp lên khung chạy) cùng open_time. Chỉ đếm nến mà REST có ĐỦ mọi phút của nến đó."""
    frame = _bot_frame(bot_dir)
    fr_ms = FRAME_MS.get(frame, MINUTE_MS)
    fetch = rest_fetch or rest_1m_cached
    total = matched = 0
    max_rel = 0.0
    errors: List[str] = []
    for sym, df in live_bars.items():
        if df.empty:
            continue
        opens = (df["ts_close"].astype("int64") - fr_ms) if "ts_close" in df.columns else df["open_time"].astype("int64")     # ts_open cũ có thể sai (ghi theo 1m): dùng giờ đóng - khung
        try:
            m1 = fetch(sym, int(opens.min()), int(opens.max()) + fr_ms - MINUTE_MS)
        except Exception as e:
            errors.append(f"{sym}: {type(e).__name__}: {e}")
            continue
        if m1 is None or m1.empty:
            continue
        agg = m1.copy()
        if fr_ms > MINUTE_MS:
            g = agg.assign(b=(agg["open_time"] // fr_ms) * fr_ms).groupby("b")
            agg = pd.DataFrame({"open_time": list(g.groups.keys()), "open": g["open"].first().values, "high": g["high"].max().values, "low": g["low"].min().values,
                                "close": g["close"].last().values, "n": g.size().values})
            agg = agg[agg["n"] == fr_ms // MINUTE_MS]
        ref = agg.set_index("open_time")
        for (_, row), op_t in zip(df.iterrows(), opens):
            op_t = int(op_t)
            if op_t not in ref.index:
                continue
            r = ref.loc[op_t]
            total += 1
            rel = max(abs(float(row[k]) - float(r[k])) / max(abs(float(r[k])), 1e-12) for k in ("open", "high", "low", "close"))
            max_rel = max(max_rel, rel)
            if rel <= PRICE_RTOL:
                matched += 1
    pct = (matched / total * 100.0) if total else 0.0
    ok = total > 0 and matched == total
    out = {"ok": False, "level": 1, "name": "Dữ liệu", "bars_checked": total, "matched_bars": matched, "match_pct": round(pct, 2), "max_rel_diff": max_rel, "ts_shift": 0,
           "source": "OKX REST 1m", "frame": frame, "min_bars": min_bars}
    out["status"] = _status(total, ok, min_bars)
    out["ok"] = out["status"] == PASS
    if errors:
        out["errors"] = errors
    if total == 0:
        out["note"] = "Không so sánh được nến nào (bars.jsonl rỗng/không có hoặc REST không có đủ nến trong cửa sổ)"
    return out


def recompute_signals(symbol: str, strategy: Dict[str, Any], base_frame: str, now_ms: Optional[int] = None) -> Dict[int, Tuple[bool, bool, bool]]:
    """Tín hiệu tính lại bằng code backend (CÙNG evaluate_signals của backtest/live) trên dữ liệu catalog + REST tới hiện tại: {open_time nến chạy: (match, stop, dca)}."""
    import time as _time
    from backend.nautilus.signals import LiveSignals
    from backend.signal.compute import evaluate_signals
    sg = LiveSignals(dat.normalize_symbol(symbol), strategy, base_frame)
    sg.warm_start(int(now_ms if now_ms is not None else _time.time() * 1000))
    res = evaluate_signals(sg.symbol, [strategy], sg.frames, base_frame)
    e = res["entries"][0]
    dca = e.get("dca")
    return {int(t): (bool(e["match"][i]), bool(e["stop"][i]), bool(dca[i]) if dca is not None else True) for i, t in enumerate(res["t"])}


def check_level2_signals(bot_dir: str, live_bars: Dict[str, pd.DataFrame], events: List[Dict[str, Any]],
                         recompute: Optional[Callable[[str, Dict[str, Any], str], Dict[int, Tuple[bool, bool, bool]]]] = None,
                         strategies: Optional[List[Dict[str, Any]]] = None, min_bars: int = DEFAULT_MIN_BARS) -> Dict[str, Any]:
    """Tầng 2 (Tín hiệu): mỗi dòng `signals.jsonl` (match/stop/dca của bot lúc chạy) so với tín hiệu tính lại bằng backend trên cùng dữ liệu — phải khớp 100%."""
    rows = [r for r in load_live_signals(bot_dir) if r.get("match") is not None]
    base = {"level": 2, "name": "Tín hiệu", "min_bars": min_bars}
    if not rows:
        return {**base, "ok": False, "status": INSUFFICIENT, "signals_checked": 0, "matched": 0, "match_pct": 0.0, "note": "Không có dòng tín hiệu nào trong signals.jsonl (bot chạy bản cũ hoặc chưa có nến)"}
    frame = _bot_frame(bot_dir)
    fr_ms = FRAME_MS.get(frame, MINUTE_MS)
    if strategies is None:
        try:
            strategies = resolve_live_source(_read_json(os.path.join(bot_dir, "bot.json")).get("launch_params") or {}).get("strategies") or []
        except Exception as e:
            return {**base, "ok": False, "status": INSUFFICIENT, "signals_checked": 0, "matched": 0, "match_pct": 0.0, "note": f"Không dựng lại được chiến lược từ bot.json: {type(e).__name__}: {e}"}
    by_id = {st["id"]: st for st in strategies}
    rec = recompute or recompute_signals
    cache: Dict[Tuple[str, str], Dict[int, Tuple[bool, bool, bool]]] = {}
    total = matched = 0
    mism: List[Dict[str, Any]] = []
    for r in rows:
        st = by_id.get(r.get("slot"))
        if st is None:
            continue
        key = (r["symbol"], r["slot"])
        if key not in cache:
            cache[key] = rec(r["symbol"], st, frame)
        exp = cache[key].get(int(r["ts"]) - fr_ms)
        if exp is None:
            continue
        total += 1
        got = (bool(r["match"]), bool(r["stop"]), bool(r["dca"]) if r.get("dca") is not None else exp[2])
        if got == exp:
            matched += 1
        elif len(mism) < 10:
            mism.append({"symbol": r["symbol"], "slot": r["slot"], "ts": r["ts"], "bot": got, "recomputed": exp})
    pct = (matched / total * 100.0) if total else 0.0
    status = _status(total, matched == total, min_bars)
    out = {**base, "ok": status == PASS, "status": status, "signals_checked": total, "matched": matched, "match_pct": round(pct, 2)}
    if mism:
        out["mismatches"] = mism
    if total == 0:
        out["note"] = "Không dòng tín hiệu nào có nến tương ứng trong dữ liệu tính lại"
    return out


def check_level3_orders(bot_dir: str, live_bars: Dict[str, pd.DataFrame], events: List[Dict[str, Any]], slack_ms: int = 120_000) -> Dict[str, Any]:
    """Tầng 3 (Ý định lệnh): phát lại máy trạng thái FLAT -> ENTRY (khi match) -> EXIT (khi stop) từ `signals.jsonl` rồi so với fill thật.
    (a) mỗi fill ENTRY không phải catch-up phải đứng ngay sau một nến match của chính slot đó; fill EXIT phải sau nến stop; fill catch-up phải có sự kiện `catchup` match.
    (b) mỗi nến match khi slot đang flat (theo fill đã ghi) phải có fill ENTRY hoặc sự kiện reject/signal trong cửa sổ. Kích cỡ lệnh/SL/TP do Nautilus + chính sách chung với backtest, không phát lại ở đây."""
    sig_rows = [r for r in load_live_signals(bot_dir) if r.get("match") is not None]
    fills = sorted([e for e in events if e.get("type") == "fill"], key=lambda e: int(e.get("ts") or e.get("t") or 0))
    rejects = [e for e in events if e.get("type") in ("reject", "signal")]
    base = {"level": 3, "name": "Ý định lệnh", "initial_catchup_count": sum(1 for f in fills if f.get("catchup"))}
    by_slot: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in sig_rows:
        by_slot.setdefault((r["symbol"], r["slot"]), []).append(r)
    checked = matched = 0
    bad: List[Dict[str, Any]] = []

    def flag(kind: str, **kw: Any) -> None:
        if len(bad) < 10:
            bad.append({"kind": kind, **kw})

    for f in fills:
        k = f.get("kind")
        if k not in ("ENTRY", "EXIT"):
            continue
        ts = int(f.get("ts") or f.get("t") or 0)
        rows = by_slot.get((f.get("symbol"), f.get("strategy")), [])
        if f.get("catchup"):
            ok = any(e.get("type") == "catchup" and e.get("symbol") == f.get("symbol") and e.get("match") for e in events)
        elif not rows:
            continue
        else:
            field = "match" if k == "ENTRY" else "stop"
            ok = any(r.get(field) and 0 <= ts - int(r["ts"]) <= slack_ms for r in rows)
        checked += 1
        matched += int(ok)
        if not ok:
            flag(f"{k}_without_signal", symbol=f.get("symbol"), ts=ts)
    entries = [(f.get("symbol"), f.get("strategy"), int(f.get("ts") or f.get("t") or 0)) for f in fills if f.get("kind") == "ENTRY"]
    closes = [(f.get("symbol"), f.get("strategy"), int(f.get("ts") or f.get("t") or 0)) for f in fills if f.get("kind") not in ("ENTRY", "DCA")]
    for (sym, slot), rows in by_slot.items():
        for r in rows:
            if not r.get("match"):
                continue
            ts = int(r["ts"])
            opened = sum(1 for s, sl, t in entries if s == sym and sl == slot and t <= ts) - sum(1 for s, sl, t in closes if s == sym and sl == slot and t <= ts)
            if opened > 0:
                continue                      # đang có vị thế: tín hiệu vào bị bỏ qua đúng luật
            checked += 1
            hit = any(s == sym and sl == slot and 0 <= t - ts <= slack_ms for s, sl, t in entries) or any(
                e.get("symbol") == sym and e.get("strategy") == slot and 0 <= int(e.get("t") or 0) - ts <= slack_ms for e in rejects) or any(
                e.get("type") == "catchup" and e.get("symbol") == sym for e in events)
            matched += int(hit)
            if not hit:
                flag("match_without_order", symbol=sym, slot=slot, ts=ts)
    status = _status(checked, matched == checked)
    out = {**base, "ok": status == PASS, "status": status, "orders_checked": checked, "matched_orders": matched,
           "match_pct": round(matched / checked * 100.0, 2) if checked else 0.0}
    if bad:
        out["mismatches"] = bad
    if checked == 0:
        out["note"] = "Không có quyết định vào/thoát nào để so (chưa có nến match/stop hay fill)"
    return out


def check_level4_slippage(bot_dir: str, live_bars: Dict[str, pd.DataFrame], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tầng 4 (Giá khớp): báo cáo lệch giá market (bps), độ trễ đặt lệnh (ms).
    Ngưỡng đề xuất: market trung vị <= 3 bps; limit/TP = 0 bps.
    """
    fills = [e for e in events if e.get("type") == "fill"]
    if not fills:
        return {
            "ok": False,
            "status": INSUFFICIENT,
            "level": 4,
            "name": "Giá khớp & Độ trượt",
            "fills_checked": 0,
            "median_bps": 0.0,
            "p95_bps": 0.0,
            "max_bps": 0.0,
            "avg_latency_ms": 0.0,
            "note": "Chưa có lệnh khớp nào để đo độ trượt",
        }

    market_bps: List[float] = []
    latencies: List[float] = []

    for f in fills:
        px = float(f.get("px") or f.get("price") or 0.0)
        sym = f.get("symbol")
        ts = int(f.get("ts") or f.get("t") or 0)
        if px <= 0 or not sym:
            continue

        df = live_bars.get(sym)
        bar_close = px
        if df is not None and not df.empty:
            match_row = df[(df["open_time"] <= ts) & (ts <= df["ts_close"] + 5000)]
            if not match_row.empty:
                bar_close = float(match_row.iloc[-1]["close"])
                bar_ts = int(match_row.iloc[-1]["ts_close"])
                latency = max(0, ts - bar_ts)
                latencies.append(latency)

        if bar_close > 0:
            bps = abs(px - bar_close) / bar_close * 10_000.0
            market_bps.append(bps)

    if market_bps:
        arr = np.array(market_bps)
        median_bps = float(np.median(arr))
        p95_bps = float(np.percentile(arr, 95))
        max_bps = float(np.max(arr))
    else:
        median_bps, p95_bps, max_bps = 0.0, 0.0, 0.0

    avg_latency = float(np.mean(latencies)) if latencies else 0.0
    status = _status(len(market_bps), median_bps <= 3.0)

    return {
        "ok": status == PASS,
        "status": status,
        "level": 4,
        "name": "Giá khớp & Độ trượt",
        "fills_checked": len(fills),
        "median_bps": round(median_bps, 2),
        "p95_bps": round(p95_bps, 2),
        "max_bps": round(max_bps, 2),
        "avg_latency_ms": round(avg_latency, 1),
    }


def run_full_parity(bot_dir_or_id: str, min_bars: int = DEFAULT_MIN_BARS, rest_fetch: Optional[Callable] = None, recompute: Optional[Callable] = None,
                    strategies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Thực thi đầy đủ 4 tầng kiểm tra đồng nhất. rest_fetch / recompute / strategies: thay nguồn mạng bằng dữ liệu cho sẵn (test)."""
    bot_dir = bot_dir_or_id
    if not os.path.isdir(bot_dir):
        found = find_bot_dir(bot_dir_or_id)
        if found:
            bot_dir = found
        else:
            raise FileNotFoundError(f"Không tìm thấy thư mục bot {bot_dir_or_id}")

    live_bars = load_live_bars(bot_dir)
    events = load_live_events(bot_dir)

    l1 = check_level1_data(bot_dir, live_bars, rest_fetch=rest_fetch, min_bars=min_bars)
    l2 = check_level2_signals(bot_dir, live_bars, events, recompute=recompute, strategies=strategies, min_bars=min_bars)
    l3 = check_level3_orders(bot_dir, live_bars, events)
    l4 = check_level4_slippage(bot_dir, live_bars, events)

    levels = (l1, l2, l3, l4)
    all_ok = all(x["status"] == PASS for x in levels)
    return {
        "ok": all_ok,
        "insufficient": [x["level"] for x in levels if x["status"] == INSUFFICIENT],
        "bot_dir": bot_dir,
        "min_bars": min_bars,
        "level1_data": l1,
        "level2_signals": l2,
        "level3_orders": l3,
        "level4_slippage": l4,
    }


def print_parity_report(res: Dict[str, Any]) -> None:
    """In bảng báo cáo kết quả 4 tầng."""
    print("=" * 68)
    print(f"BÁO CÁO ĐỒNG NHẤT 4 TẦNG (PARITY REPORT): {os.path.basename(res['bot_dir'])}")
    print("=" * 68)

    l1 = res["level1_data"]
    l2 = res["level2_signals"]
    l3 = res["level3_orders"]
    l4 = res["level4_slippage"]

    def badge(x: Dict[str, Any]) -> str:
        return {PASS: "[✓ ĐẠT]", FAIL: "[✗ LỆCH]", INSUFFICIENT: "[? KHÔNG ĐỦ DỮ LIỆU]"}[x["status"]]

    print(f"1. Tầng 1 (Dữ liệu vs REST): {badge(l1)} | Nến so: {l1.get('bars_checked', 0)}, Khớp: {l1.get('match_pct', 0)}%")
    print(f"2. Tầng 2 (Tín hiệu):        {badge(l2)} | Tín hiệu: {l2.get('signals_checked', 0)}, Khớp: {l2.get('match_pct', 0)}%")
    print(f"3. Tầng 3 (Ý định lệnh):     {badge(l3)} | Quyết định: {l3.get('orders_checked', 0)}, Khớp: {l3.get('match_pct', 0)}% (catchup: {l3.get('initial_catchup_count', 0)})")
    print(f"4. Tầng 4 (Độ trượt giá):    {badge(l4)} | Fills: {l4.get('fills_checked', 0)}, Trung vị: {l4.get('median_bps', 0)} bps (p95: {l4.get('p95_bps', 0)} bps, trễ: {l4.get('avg_latency_ms', 0)} ms)")
    for x in (l1, l2, l3, l4):
        if x.get("note"):
            print(f"   ghi chú tầng {x['level']}: {x['note']}")
        for m in (x.get("mismatches") or [])[:3]:
            print(f"   lệch tầng {x['level']}: {m}")
    print("-" * 68)
    if res["ok"]:
        print("TỔNG THỂ: ✓ TẤT CẢ ĐẠT YÊU CẦU")
    elif res["insufficient"]:
        print(f"TỔNG THỂ: KHÔNG ĐỦ DỮ LIỆU ở tầng {res['insufficient']} — chưa thể kết luận đồng nhất (cần thêm nến/tín hiệu/lệnh; --min-bars {res['min_bars']})")
    else:
        print("TỔNG THỂ: CẦN KIỂM TRA LẠI (có tầng lệch)")
    print("=" * 68)


def main():
    parser = argparse.ArgumentParser(description="Kiểm tra đồng nhất 4 tầng Backtest ↔ Live Bot")
    parser.add_argument("--bot", "-b", help="ID bot hoặc đường dẫn thư mục bot")
    parser.add_argument("--min-bars", type=int, default=DEFAULT_MIN_BARS, help="số nến/tín hiệu tối thiểu được so ở Tầng 1-2 (ít hơn = KHÔNG ĐỦ DỮ LIỆU)")
    parser.add_argument("--json", action="store_true", help="Xuất kết quả dưới dạng JSON")
    args = parser.parse_args()

    target = args.bot
    if not target:
        base_dir = os.path.join(data_home(), "live")
        candidates = []
        for m in ("paper", "testnet", "live"):
            p = os.path.join(base_dir, m)
            if os.path.isdir(p):
                for b in os.listdir(p):
                    full = os.path.join(p, b)
                    if os.path.isdir(full):
                        candidates.append(full)
        if not candidates:
            print("Không tìm thấy bot nào trong data/live/")
            sys.exit(1)
        candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        target = candidates[0]

    report = run_full_parity(target, min_bars=args.min_bars)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_parity_report(report)

    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
