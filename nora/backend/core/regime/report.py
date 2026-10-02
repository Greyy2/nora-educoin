"""Báo cáo độ chính xác regime + so sánh backtest bật/tắt regime (job API `regime_report`, POST /api/studio/regime/report).

Phần A — nhãn regime (core/regime/classifier.series, đúng đường dữ liệu của engine) trên dữ liệu thật từng tài sản:
  tỷ trọng thời gian, số đợt, thời lượng trung bình, số lần đổi / 30 ngày; lợi suất 24h TIẾP THEO theo nhãn (lấy mẫu mỗi giờ):
  trung bình, trung vị, % dương, |lợi suất| trung bình -> nhãn xu hướng phải có lợi suất tiếp theo cùng chiều, RANGE có biên độ nhỏ.
Phần B — sự kiện thẳng đứng (định nghĩa SAU sự việc, chỉ để chấm điểm): giờ h có lợi suất 24h tới <= -event_pct (sập) / >= +event_pct
  (tăng dựng). Gộp giờ liên tiếp thành đợt. Phát hiện = nhãn CRASH/SURGE xuất hiện trong [đầu đợt, đầu đợt + 24h):
  tỷ lệ phát hiện, độ trễ (phút), % quãng giá đã đi trước khi phát hiện. Cảnh báo: mỗi đợt CRASH/SURGE (nhãn) -> lợi suất 24h sau khi bật
  (cầu chì đúng khi giá tiếp tục đi ngược vị thế bị cắt).
Phần C — sổ mọi chiến lược lõi (presets) chạy 2 lần trên cùng dữ liệu: tắt / bật regime. Kết quả tổng + theo chiến lược, và lãi/lỗ theo
  (chiến lược, regime lúc vào lệnh) của lần tắt -> kiểm chứng bảng REGIME_MAP (chiến lược nào lỗ ở regime nào).
"""
import time
import warnings
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backend.core.regime import classifier as rg
from backend.utils.jobs import as_list, options, write_job_result

DEFAULTS = {"symbols": "", "start": "", "end": "", "event_pct": 12.0, "backtest": True}
MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000


def _ts(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


def _episodes(mask: np.ndarray):
    """[(đầu, cuối+1)] các đoạn True liên tiếp."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def label_stats(s: Dict[str, np.ndarray], start: int) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    n = len(t)
    days = (t[-1] - t[0]) / DAY if n > 1 else 0.0
    # mẫu mỗi giờ: lợi suất 24h tới (phút cuối cùng <= t + 24h)
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    ok = (t[fwd_idx] >= t[hourly] + DAY - HOUR)
    h, fi = hourly[ok], fwd_idx[ok]
    fwd = (close[fi] / close[h] - 1.0) * 100.0
    out: Dict[str, Any] = {"minutes": int(n), "days": round(days, 1), "states": {}}
    switches = int((np.diff(lab.astype(np.int16)) != 0).sum())
    out["switches_per_30d"] = round(switches / days * 30, 2) if days else None
    for code, name in enumerate(rg.NAMES):
        m = lab == code
        if not m.any():
            continue
        eps = _episodes(m)
        dur = [(t[e - 1] - t[b]) / HOUR + 1 / 60 for b, e in eps]
        r = fwd[lab[h] == code]
        out["states"][name] = {
            "share_pct": round(100 * m.mean(), 2), "episodes": len(eps), "avg_hours": round(float(np.mean(dur)), 1),
            "fwd24_n": int(r.size),
            "fwd24_mean_pct": round(float(r.mean()), 3) if r.size else None,
            "fwd24_median_pct": round(float(np.median(r)), 3) if r.size else None,
            "fwd24_up_pct": round(float((r > 0).mean() * 100), 1) if r.size else None,
            "fwd24_abs_pct": round(float(np.abs(r).mean()), 3) if r.size else None,
        }
    return out


def shock_stats(s: Dict[str, np.ndarray], start: int, event_pct: float) -> Dict[str, Any]:
    t, lab, close, real = s["t"], s["labels"], s["close"], s["real"]
    keep = (t >= start) & real
    t, lab, close = t[keep], lab[keep], close[keep]
    hourly = np.flatnonzero((t % HOUR) == 0)
    fwd_idx = np.searchsorted(t, t[hourly] + DAY, side="right") - 1
    fwd = (close[fwd_idx] / close[hourly] - 1.0) * 100.0
    out = {}
    for name, code, sign in (("CRASH", rg.CRASH, -1), ("SURGE", rg.SURGE, 1)):
        ev = sign * fwd >= event_pct
        rows = []
        for b, e in _episodes(ev):
            i0 = hourly[b]
            i1 = int(np.searchsorted(t, t[i0] + DAY, side="right"))
            hit = np.flatnonzero(lab[i0:i1] == code)
            already = None
            # cực trị của đợt trong 24h sau đầu đợt (đáy với sập, đỉnh với tăng)
            seg = close[i0:i1]
            ext = int(np.argmin(seg) if sign < 0 else np.argmax(seg))
            total = seg[ext] / close[i0] - 1.0
            lag = None
            if hit.size:
                k = int(hit[0])
                lag = int((t[i0 + k] - t[i0]) // MINUTE)
                already = round(100 * (close[i0 + k] / close[i0] - 1.0) / total, 1) if total else None
            rows.append({"start": int(t[i0]), "move_pct": round(100 * total, 2), "detected": bool(hit.size), "lag_min": lag,
                         "move_done_pct": already})
        det = [r for r in rows if r["detected"]]
        alarms = []
        for b, e in _episodes(lab == code):
            j = int(np.searchsorted(t, t[b] + DAY, side="right")) - 1
            if t[j] >= t[b] + DAY - HOUR:
                alarms.append((close[j] / close[b] - 1.0) * 100.0)
        alarms = np.asarray(alarms)
        out[name] = {
            "events": len(rows), "detected": len(det),
            "recall_pct": round(100 * len(det) / len(rows), 1) if rows else None,
            "median_lag_min": int(np.median([r["lag_min"] for r in det])) if det else None,
            "median_move_done_pct": float(np.median([r["move_done_pct"] for r in det if r["move_done_pct"] is not None]))
            if det else None,
            "alarms": int(alarms.size),
            # cầu chì đúng khi sau khi bật giá TIẾP TỤC cùng chiều sốc (vị thế ngược chiều bị cắt là tránh lỗ thêm)
            "alarm_continuation_pct": round(float((sign * alarms > 0).mean() * 100), 1) if alarms.size else None,
            "alarm_fwd24_mean_pct": round(float(alarms.mean()), 3) if alarms.size else None,
            "worst_events": sorted(rows, key=lambda r: sign * -r["move_pct"])[:5],
        }
    return out


def _book_items():
    from backend.core.params.presets import load_presets
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, CANDIDATES
    presets = load_presets()
    items, rpts = [], []
    for c in CANDIDATES:
        prm = dict(presets[c["id"]]["params"])
        if prm.get("risk_per_trade_pct") is not None:
            rpts.append(float(prm["risk_per_trade_pct"]))
        prm.pop("risk_per_trade_pct", None)
        items.append((c["id"], prm))
    return items, (min(rpts) if rpts else BASE_RISK_PER_TRADE_PCT)


def _summary(out: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("ret_pct", "mdd_pct", "sharpe", "sortino", "calmar", "trades", "win_rate", "profit_factor", "final_equity", "halted_at")
    return {**{k: out.get(k) for k in keys}, "by_strategy": out.get("by_strategy")}


def by_regime(trades: List[Dict[str, Any]], labels: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Any]:
    """Lãi/lỗ theo (chiến lược, regime ở phút đã đóng ngay trước khi vào lệnh)."""
    agg: Dict[str, Dict[str, Dict[str, float]]] = {}
    for tr in trades:
        s = labels.get(tr["symbol"])
        if s is None:
            continue
        i = int(np.searchsorted(s["t"], int(tr["enter_time"]), side="left")) - 1
        name = rg.NAMES[int(s["labels"][max(i, 0)])]
        a = agg.setdefault(tr["strategy"], {}).setdefault(name, {"trades": 0, "wins": 0, "pnl_usd": 0.0, "pnl_pct_sum": 0.0})
        a["trades"] += 1
        a["wins"] += tr["pnl"] > 0
        a["pnl_usd"] += tr["pnl"]
        a["pnl_pct_sum"] += tr.get("pnl_pct") or 0.0
    for st in agg.values():
        for a in st.values():
            a["win_rate"] = round(100 * a["wins"] / a["trades"], 1)
            a["avg_pnl_pct"] = round(a.pop("pnl_pct_sum") / a["trades"], 3)
            a["pnl_usd"] = round(a["pnl_usd"], 2)
    return agg


def run_job(params=None):
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("regime_report")
    from backend.core.strategy.book import REGIME_MAP, perp_symbols
    from backend.core.backtest.run import WARMUP, run
    from backend.db.local_pkl import read_manifest
    symbols = [s if "@" in s else f"{s}@perp" for s in as_list(a.symbols)] or perp_symbols()
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    start = _ts(a.start) if a.start else max(int(m["start_ts"]) for m in ms) + WARMUP
    end = _ts(a.end) + DAY if a.end else min(int(m["end_ts"]) for m in ms)
    t0 = time.time()
    report: Dict[str, Any] = {"config": {"symbols": symbols, "start": start, "end": end, "event_pct": float(a.event_pct),
                                         "classifier": rg.DEFAULTS, "regime_map": REGIME_MAP},
                              "labels": {}, "shocks": {}}
    series = {}
    for sym in symbols:
        s = rg.series(sym, start - WARMUP, end)
        series[sym] = {"t": s["t"], "labels": s["labels"]}
        report["labels"][sym] = label_stats(s, start)
        report["shocks"][sym] = shock_stats(s, start, float(a.event_pct))
        sh = report["shocks"][sym]
        print(f"{sym}: đổi {report['labels'][sym]['switches_per_30d']}/30 ngày | sập {sh['CRASH']['detected']}/{sh['CRASH']['events']} "
              f"trễ {sh['CRASH']['median_lag_min']}p | tăng dựng {sh['SURGE']['detected']}/{sh['SURGE']['events']}", flush=True)
        del s
    report["labels_all"] = _pool_states(report["labels"])
    if a.backtest:
        items, rpt = _book_items()
        off = run(items, symbols, start, end, rpt, "level", None)
        print(f"tắt regime: lãi {off['ret_pct']}% MDD {off['mdd_pct']}% sharpe {off['sharpe']} lệnh {off['trades']}", flush=True)
        on = run(items, symbols, start, end, rpt, "level", None, regime=True)
        print(f"bật regime: lãi {on['ret_pct']}% MDD {on['mdd_pct']}% sharpe {on['sharpe']} lệnh {on['trades']}", flush=True)
        report["backtest"] = {"risk_per_trade_pct": rpt, "off": _summary(off), "on": _summary(on),
                              "off_by_regime": by_regime(off["trade_list"], series),
                              "on_by_regime": by_regime(on["trade_list"], series),
                              "equity_off": off.get("daily_nav"), "equity_on": on.get("daily_nav")}
    report["meta"] = {"wall_s": round(time.time() - t0, 1)}
    print(f"thời gian {report['meta']['wall_s']}s", flush=True)
    write_job_result(report)
    return report


def _pool_states(per_symbol: Dict[str, Any]) -> Dict[str, Any]:
    """Gộp các tài sản: tỷ trọng theo phút, lợi suất 24h tới theo trọng số số mẫu."""
    tot = sum(v["minutes"] for v in per_symbol.values()) or 1
    out = {}
    for name in rg.NAMES:
        rows = [(v["minutes"], v["states"][name]) for v in per_symbol.values() if name in v["states"]]
        if not rows:
            continue
        n = sum(r["fwd24_n"] for _, r in rows) or 1
        avg = lambda k: round(sum((r[k] or 0) * r["fwd24_n"] for _, r in rows) / n, 3)  # noqa: E731
        out[name] = {"share_pct": round(sum(m * r["share_pct"] for m, r in rows) / tot, 2),
                     "fwd24_mean_pct": avg("fwd24_mean_pct"), "fwd24_up_pct": avg("fwd24_up_pct"), "fwd24_abs_pct": avg("fwd24_abs_pct")}
    return out

