"""Kiểm tra tín hiệu: tín hiệu có mang THÔNG TIN về giá tương lai không — trước khi ghép thành chiến lược.

Với mỗi tín hiệu (cây điều kiện AST trên kernel) và mỗi tài sản:
- Sự kiện = nến 1m (có giao dịch) mà tín hiệu đúng; vào ở OPEN của phút có giao dịch kế tiếp
  (giống engine, không nhìn trước).
- Lợi suất tương lai ở các mốc h (15m, 1h, 4h, 24h) = close của nến đóng muộn nhất trong h phút.
- Mỗi mốc h chỉ giữ các sự kiện CÁCH NHAU >= h (không chồng lấp) để t-stat không bị thổi phồng.
- Đối chứng = vào ở MỌI phút (lấy mẫu đều) trong cùng khoảng thời gian: edge = TB sự kiện − TB đối chứng.
- Ổn định = edge cùng dấu ở 60% sự kiện đầu và 40% sau.
- Sau phí = TB sự kiện − chi phí khứ hồi theo venue (CEX spot ~24 bps, DEX ~80 bps).

Kết luận mỗi tín hiệu (mốc h tốt nhất theo |t|):
    CO_THONG_TIN   |t| >= 3 và ổn định
    YEU            2 <= |t| < 3 hoặc không ổn định
    KHONG          |t| < 2 hoặc quá ít sự kiện
Ngưỡng |t| >= 3 (không phải 2) vì kiểm nhiều tín hiệu × nhiều tài sản × nhiều mốc cùng lúc.
"""
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

HORIZONS_MIN = (15, 60, 240, 1440)
MIN_EVENTS = 30


def _thin(entry_times: np.ndarray, gap_ms: int) -> np.ndarray:
    """Giữ các sự kiện cách nhau >= gap (tham lam theo thời gian)."""
    keep, last = [], None
    for idx, t in enumerate(entry_times):
        if last is None or t - last >= gap_ms:
            keep.append(idx)
            last = t
    return np.asarray(keep, dtype=int)


def _forward_bps(times, opens, closes, entry_idx, horizon_ms, sign):
    """Lợi suất (bps) từ open của nến entry tới close nến cuối cùng đóng trong horizon."""
    t_entry = times[entry_idx]
    k = np.searchsorted(times, t_entry + horizon_ms - 60_000, side="right") - 1
    valid = (k > entry_idx) & (t_entry + horizon_ms <= times[-1] + 60_000)
    ret = np.full(len(entry_idx), np.nan)
    ret[valid] = sign * (closes[k[valid]] / opens[entry_idx[valid]] - 1.0) * 1e4
    return ret


def _stats(ev: np.ndarray, base: np.ndarray, cost_bps: float) -> Dict[str, Any]:
    ev = ev[np.isfinite(ev)]
    base = base[np.isfinite(base)]
    n = len(ev)
    if n < 2 or len(base) < 2:
        return {"n": int(n)}
    edge = ev.mean() - base.mean()
    se = ev.std(ddof=1) / np.sqrt(n)
    split = int(n * 0.6)
    first, last = ev[:split], ev[split:]
    edge_first = first.mean() - base.mean() if len(first) else np.nan
    edge_last = last.mean() - base.mean() if len(last) else np.nan
    return {
        "n": int(n),
        "mean_bps": round(float(ev.mean()), 2),
        "median_bps": round(float(np.median(ev)), 2),
        "hit_rate": round(float((ev > 0).mean() * 100), 1),
        "baseline_mean_bps": round(float(base.mean()), 2),
        "baseline_hit_rate": round(float((base > 0).mean() * 100), 1),
        "edge_bps": round(float(edge), 2),
        "t_stat": round(float(edge / se), 2) if se > 0 else 0.0,
        "edge_first60_bps": round(float(edge_first), 2),
        "edge_last40_bps": round(float(edge_last), 2),
        "stable": bool(np.sign(edge_first) == np.sign(edge_last) and np.sign(edge_first) != 0),
        "net_after_cost_bps": round(float(ev.mean() - cost_bps), 2),
    }


def _verdict(by_h: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    usable = {h: s for h, s in by_h.items() if s.get("n", 0) >= MIN_EVENTS and "t_stat" in s}
    if not usable:
        return {"verdict": "KHONG", "reason": f"ít hơn {MIN_EVENTS} sự kiện không chồng lấp", "best_horizon_min": None}
    h, s = max(usable.items(), key=lambda kv: abs(kv[1]["t_stat"]))
    t = s["t_stat"]
    if abs(t) >= 3 and s["stable"]:
        verdict = "CO_THONG_TIN"
    elif abs(t) >= 2:
        verdict = "YEU"
    else:
        verdict = "KHONG"
    direction = "đúng chiều" if t > 0 else "NGƯỢC chiều (tín hiệu báo sai hướng)"
    return {
        "verdict": verdict,
        "best_horizon_min": h,
        "t_stat": t,
        "direction": direction,
        "covers_cost": bool(t >= 3 and s["net_after_cost_bps"] > 0),
        "reason": f"mốc {h} phút: edge {s['edge_bps']} bps, t={t}, {'ổn định' if s['stable'] else 'KHÔNG ổn định'} "
                  f"giữa 60% đầu/40% sau, sau phí {s['net_after_cost_bps']} bps",
    }


def check_signals(symbol: str, signals: Dict[str, Dict[str, Any]], start_ts: Optional[int] = None,
                  end_ts: Optional[int] = None, horizons_min: Iterable[int] = HORIZONS_MIN,
                  baseline_step: int = 7) -> Dict[str, Any]:
    """Kiểm tra nhiều tín hiệu trên một tài sản (nạp dữ liệu + tính kernel một lần)."""
    from backend.backtest.engine import BacktestEngine
    from backend.backtest.params_builder import VENUE_COSTS, build_params, venue_of_symbol
    from backend.core.evaluator import VectorEvaluator, lag_key
    from backend.db.local_pkl import read_manifest

    manifest = read_manifest(symbol) or {}
    venue = venue_of_symbol(symbol)
    start_ts = int(start_ts or manifest.get("start_ts"))
    end_ts = int(end_ts or manifest.get("end_ts"))

    engine = BacktestEngine(0, 0, symbol, start_ts, end_ts)
    names = list(signals)
    for name in names:  # flow LONG giả chỉ để engine biết cần tính kernel nào
        engine.add_strategy_flow(f"LONG_{name}", build_params(
            f"LONG_{name}", {"match": [{"condition": signals[name]["tree"]}], "stop": []}, "LONG", {}, venue))
    engine.load_data()
    df1, cols = engine._build_matrix()
    n = len(df1)
    vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))

    real = df1["is_filled"].to_numpy() == 0
    in_range = df1["open_time"].to_numpy() >= start_ts
    times = df1["open_time"].to_numpy(dtype="int64")[real]
    opens = df1["open"].to_numpy(dtype="float64")[real]
    closes = df1["close"].to_numpy(dtype="float64")[real]
    pos_of_row = np.cumsum(real) - 1  # vị trí trong mảng phút-thật của mỗi dòng
    base_idx = np.arange(0, len(times) - 1, baseline_step)
    base_idx = base_idx[times[base_idx] >= start_ts]

    results: Dict[str, Any] = {}
    for name in names:
        sig = signals[name]
        sign = 1.0 if sig.get("side", "LONG") == "LONG" else -1.0
        fire = vec.tree(sig["tree"]) & real & in_range
        entry = pos_of_row[np.nonzero(fire)[0]] + 1           # vào ở phút thật kế tiếp
        entry = np.unique(entry[entry < len(times)])
        costs = VENUE_COSTS[(venue, "spot" if sign > 0 else ("perp" if venue == "cex" else "spot"))]
        cost_bps = 2 * (costs[0] + costs[2]) * 1e4  # taker + trượt, hai chiều
        by_h = {}
        for h in horizons_min:
            ev_idx = entry[_thin(times[entry], h * 60_000)] if len(entry) else entry
            ev = _forward_bps(times, opens, closes, ev_idx, h * 60_000, sign) if len(ev_idx) else np.array([])
            base = _forward_bps(times, opens, closes, base_idx, h * 60_000, sign)
            by_h[h] = _stats(ev, base, cost_bps)
        results[name] = {
            "side": sig.get("side", "LONG"),
            "family": sig.get("family"),
            "raw_signal_minutes": int(fire.sum()),
            "cost_bps_round_trip": round(cost_bps, 1),
            "horizons": by_h,
            **_verdict(by_h),
        }
    return {"symbol": symbol, "venue": venue, "start_ts": start_ts, "end_ts": end_ts, "signals": results}
