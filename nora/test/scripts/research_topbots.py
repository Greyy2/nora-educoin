"""Nghiên cứu: tái tạo lối đánh của bot copy-trading top (okx-report.html) trên nến 1m thật và đo cái mà con số
"toàn thắng" của họ che đi (đuôi lỗ không cắt, lỗ treo, thanh lý, cháy tài khoản).

Nguồn tham số: `const BOTS = [...]` trong okx-report.html (parse bằng JSON, không chép tay).
  p = thống kê đo được (lev_med, hold_med, win, long_pct, top_syms, pf, momentum, days, per_day ...)
  v = biến thể DCA suy ra (spacing = bước DCA % giá, stack = số tầng tối đa, size = hệ số khối lượng tầng,
      tp = chốt lời theo % KÝ QUỸ -> chốt theo % GIÁ = tp / đòn bẩy)

Ánh xạ sang tham số vị thế của Nora (market="perp", ký quỹ isolated, thanh lý bật, KHÔNG stop-loss, KHÔNG timeout):
  leverage = lev; dca_step_pct = spacing; dca_max_layers = stack − 1 (giảm nếu ngân sách engine không cho: xem
  `feasible_layers`); dca_size_multiplier = size; take_profit_rate = tp / lev; order_size_pct = LỚN NHẤT thoả
  `dca_budget_check` cho mọi tầng (chia đôi mỗi chiều khi bot đánh hai chiều); phí Binance USDT-M VIP0.

GIẢ ĐỊNH VỀ ĐIỂM VÀO (báo cáo không tiết lộ trigger của bot): hai biến thể
  "reentry"   : vào lại ngay khi trống (sau cooldown 5 phút); chiều theo long_pct; nếu momentum <= 30% (ngược đà)
                chỉ vào khi 24h trước đó đi ngược chiều lệnh, momentum >= 60% (theo đà) chỉ vào cùng chiều 24h.
  "reversion" : tín hiệu bắt hồi có sẵn (strategy_library: dip_5m_rsi_bb_ranging / rip_5m_rsi_bb_ranging).

Chạy: ops/run_limited.sh -- -m backend.core.research.research_topbots [--bots a,b] [--windows A,B] [--workers auto|8]
Kết quả: data/cache/process/research/topbots/<ts>.json + bảng in ra stdout. Tất định (không ngẫu nhiên).
"""
import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

DAY = 86_400_000
WARMUP = 20 * DAY                      # khởi động chỉ báo trước ngày bắt đầu giao dịch
INITIAL = 10000.0
COOLDOWN_MIN = 5                       # phút chờ sau khi đóng vị thế mới được vào lại
MIN_ORDER_SIZE_PCT = 0.01              # sàn khả thi của ký quỹ lệnh đầu (% vốn); dưới mức này coi như không thể
RUIN_FRAC = 0.10                       # "cháy" = vốn MTM xấu nhất <= 10% vốn đầu (−90%)
BOTS_HTML = os.path.abspath(os.path.join(NORA_ROOT, "..", "okx-report.html"))
OUT_DIR = os.path.join(NORA_ROOT, "data", "_cache", "research", "topbots")

# Bot được tái tạo (tên đúng như trong BOTS). 5 bot theo yêu cầu + 1 bot Binance "lướt ngắn / vào–ra dứt khoát"
# (星火研究院-大象: tp 1,4% ký quỹ, giữ trung vị 0,77h, thắng 99%, không có tầng DCA).
SELECTED = ["maomao12345", "好望角9999", "xiaojian888999", "Shallow-Pair-Frog", "BestMax", "星火研究院-大象"]
WINDOWS = ("A", "B")
VARIANTS = ("reentry", "reversion")


# ─── Nguồn tham số ──────────────────────────────────────────────────────────
def parse_bots(path: str = BOTS_HTML) -> List[Dict[str, Any]]:
    """Đọc `const BOTS = [...]` từ file HTML (JSON thuần)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    key = "const BOTS = "
    i = text.index(key) + len(key)
    bots, _ = json.JSONDecoder().raw_decode(text[i:])
    if not isinstance(bots, list):
        raise ValueError("BOTS không phải mảng JSON")
    return bots


def tp_price_pct(tp_margin_pct: float, leverage: float) -> float:
    """Chốt lời của bot đo theo % KÝ QUỸ -> % GIÁ."""
    return float(tp_margin_pct) / max(1.0, float(leverage))


def feasible_layers(leverage: float, step: float, layers_req: int, mult: float, costs: Tuple[float, float, float],
                    min_pct: float = MIN_ORDER_SIZE_PCT) -> Tuple[int, float]:
    """Số tầng DCA lớn nhất <= layers_req mà ký quỹ lệnh đầu lớn nhất (theo dca_budget_check) >= min_pct.
    -> (số tầng, order_size_pct lớn nhất cho phép)."""
    from backend.models.params import dca_budget_check
    taker = costs[0]
    for n in range(max(0, int(layers_req)), -1, -1):
        if n == 0 or step <= 0:   # không DCA: ký quỹ + phí vào lệnh <= 100% vốn (đúng PositionTracker._open)
            mx = 100.0 / (1.0 + leverage * taker)
            n = 0
        else:
            chk = dca_budget_check({"market": "perp", "leverage": leverage, "order_size_pct": 100.0,
                                    "dca_max_layers": n, "dca_step_pct": step, "dca_size_multiplier": mult,
                                    "sizing": "margin_pct"}, costs)
            mx = float(chk["max_order_size_pct"])
        if mx >= min_pct:
            return n, mx
    return 0, 100.0 / (1.0 + leverage * taker)


def _floor4(x: float) -> float:
    return math.floor(x * 1e4) / 1e4


def momentum_mode(momentum: Optional[float]) -> str:
    """momentum = % lệnh vào cùng chiều biến động 24h trước đó."""
    if momentum is None:
        return "neutral"
    if momentum <= 30:
        return "counter"
    if momentum >= 60:
        return "trend"
    return "neutral"


def map_bot(bot: Dict[str, Any], available: List[str], costs: Tuple[float, float, float]) -> Dict[str, Any]:
    """Bot (một phần tử BOTS) -> đặc tả tái tạo trên Nora."""
    p, v = bot["p"], bot["v"]
    lev = float(v.get("lev") or p["lev_med"])
    stack = v.get("stack")
    layers_req = max(0, int(stack) - 1) if stack else 0
    step = float(v.get("spacing") or 0.0)
    mult = float(v.get("size") or 1.0)
    layers, mx = feasible_layers(lev, step, layers_req, mult, costs)
    lp = float(p["long_pct"])
    sides = ["LONG"] if lp >= 65 else (["SHORT"] if lp <= 35 else ["LONG", "SHORT"])
    per_side = _floor4(mx / len(sides))
    tops = [s for s, _ in p["top_syms"]]
    symbols = [s for s in tops if s in available]
    tp_margin = float(v["tp"])
    liq_dist = 100.0 / lev - 0.5                      # % từ giá TB tới giá thanh lý (mmr 0,5%)
    span = step * layers                              # biên độ DCA (% giá)
    sl_ctrl = round(min(2.0 * span, 0.5 * liq_dist) if span > 0 else 0.5 * liq_dist, 4)
    return {
        "name": bot["name"], "exchange": bot.get("where"), "variant_report": v.get("variant"),
        "leverage": lev, "step_pct": step, "stack_report": stack, "layers_requested": layers_req, "layers": layers,
        "layers_capped": layers < layers_req, "size_mult": mult,
        "tp_margin_pct": tp_margin, "tp_price_pct": round(tp_price_pct(tp_margin, lev), 6),
        "sides": sides, "long_pct": lp, "momentum": p.get("momentum"), "momentum_mode": momentum_mode(p.get("momentum")),
        "max_order_size_pct": round(mx, 6), "order_size_pct_per_side": per_side,
        "dca_span_pct": round(span, 4), "sl2span_pct": round(2.0 * span, 4), "liq_dist_pct": round(liq_dist, 4),
        "sl2span_beyond_liq": bool(span > 0 and 2.0 * span >= liq_dist),
        "sl_control_pct": sl_ctrl,
        "top_syms": p["top_syms"], "symbols": symbols, "symbols_missing": [s for s in tops if s not in available],
        "days": int(p["days"]),
        "published": {"win": p.get("win"), "pf": p.get("pf"), "hold_med_h": p.get("hold_med"),
                      "per_day": p.get("per_day"), "payoff": p.get("payoff"), "n": p.get("n"),
                      "momentum": p.get("momentum"), "long_pct": p.get("long_pct"), "lev_med": p.get("lev_med"),
                      "roi": v.get("roi"), "mdd": v.get("mdd")},
    }


def available_symbols() -> List[str]:
    from backend.crawl.store import resolve_asset_dir
    names = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]
    return [s for s in names if resolve_asset_dir(f"{s}@perp")]


# ─── Chiến lược ─────────────────────────────────────────────────────────────
def entry_tree(variant: str, side: str, mode: str):
    from backend.alpha.compile import cond, f
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # test/ chứa legacy_library (SIGNALS: mẫu nghiên cứu)
    from legacy_library import SIGNALS
    if variant == "reversion":
        return SIGNALS["dip_5m_rsi_bb_ranging" if side == "LONG" else "rip_5m_rsi_bb_ranging"]["tree"]
    base = [(f("1m", "close"), ">", 0)]
    if mode == "counter":      # ngược đà: LONG sau khi 24h giảm, SHORT sau khi 24h tăng
        base.append((f("1h", "roc_24"), "<" if side == "LONG" else ">", 0))
    elif mode == "trend":      # theo đà: cùng chiều 24h trước đó
        base.append((f("1h", "roc_24"), ">" if side == "LONG" else "<", 0))
    return cond(*base)


def build_strategies(spec: Dict[str, Any], variant: str, sl_pct: float, stop_fill: str) -> List[Dict[str, Any]]:
    out = []
    for side in spec["sides"]:
        pos = {"market": "perp", "leverage": spec["leverage"], "order_size_pct": spec["order_size_pct_per_side"],
               "dca_step_pct": spec["step_pct"] if spec["layers"] else 0.0, "dca_max_layers": spec["layers"],
               "dca_size_multiplier": spec["size_mult"], "take_profit_rate": spec["tp_price_pct"],
               "stop_loss_rate": float(sl_pct), "trailing_stop": 0.0, "timeout": 0, "stop_fill": stop_fill,
               "cooldown": COOLDOWN_MIN, "max_open_trades": 45}
        out.append({"id": f"{side.lower()}_{variant}", "side": side, "tree": entry_tree(variant, side, spec["momentum_mode"]),
                    "position": pos})
    return out


# ─── Đo lường ───────────────────────────────────────────────────────────────
def _union_ms(intervals: List[Tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def hourly_frame(t, eq, worst) -> pd.DataFrame:
    """Đường vốn -> lưới 1 giờ, chuẩn hoá theo vốn đầu (eq: lấy cuối giờ; worst: lấy thấp nhất trong giờ)."""
    idx = pd.to_datetime(np.asarray(t, dtype="int64"), unit="ms")
    e = pd.Series(np.asarray(eq, dtype="float64") / INITIAL, index=idx)
    w = pd.Series(np.asarray(worst, dtype="float64") / INITIAL, index=idx)
    e = e[~e.index.duplicated(keep="last")].resample("1h").last().ffill()
    w = w.groupby(level=0).min().resample("1h").min()
    w = w.reindex(e.index).fillna(e)
    return pd.DataFrame({"eq": e, "worst": np.minimum(w, e)})


def curve_stats(df: pd.DataFrame, trade_start_ms: int) -> Dict[str, Any]:
    """MDD MTM gồm lỗ treo (peak của eq, đáy của worst), vốn thấp nhất, thời điểm cháy (−90%)."""
    d = df[df.index >= pd.to_datetime(trade_start_ms, unit="ms")]
    if d.empty:
        return {"mdd_pct": 0.0, "min_equity_pct": 100.0, "ruin_days": None, "min_equity_date": None}
    peak = np.maximum(d["eq"].cummax(), 1.0)
    dd = ((peak - d["worst"]) / peak).clip(upper=1.0)
    ruined = d.index[(d["worst"] <= RUIN_FRAC).to_numpy()]
    t0 = pd.to_datetime(trade_start_ms, unit="ms")
    return {"mdd_pct": float(dd.max() * 100.0), "min_equity_pct": float(d["worst"].min() * 100.0),
            "min_equity_date": str(d["worst"].idxmin().date()),
            "ruin_days": float((ruined[0] - t0).total_seconds() / 86400.0) if len(ruined) else None}


def compute_metrics(res: Dict[str, Any], trade_start: int, end: int) -> Dict[str, Any]:
    """Thống kê một lần chạy (một tài sản, một cấu hình) từ kết quả PortfolioEngine.get_results()."""
    from backend.models.models import PositionStatus
    pos = res["positions"]
    forced = [p for p in pos if p.close_reason == "End of Backtest"]
    closed = [p for p in pos if p.close_reason != "End of Backtest"]
    wins = [p for p in closed if p.real_pnl > 0]
    losses = [p for p in closed if p.real_pnl <= 0]
    gw, gl = sum(p.real_pnl for p in wins), -sum(p.real_pnl for p in losses)
    liq = [p for p in closed if p.status == PositionStatus.LIQ]
    days = max(1e-9, (end - trade_start) / DAY)
    holds = [(p.close_time - p.enter_time) / 3_600_000.0 for p in closed if p.close_time]
    intervals = [(int(p.enter_time), int(p.close_time)) for p in pos if p.close_time]
    t = np.array([c["time"] for c in res["equity_curve"]], dtype="int64")
    eq = np.array([c["equity"] for c in res["equity_curve"]], dtype="float64")
    wq = np.array([c["equity_worst"] for c in res["equity_curve"]], dtype="float64")
    df = hourly_frame(t, eq, wq)
    cs = curve_stats(df, trade_start)
    init = float(res["initial_capital"])
    return {
        "trades": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": 100.0 * len(wins) / len(closed) if closed else None,
        "sum_win_pct": float(sum(p.profit_pct for p in wins)), "sum_loss_pct": float(sum(p.profit_pct for p in losses)),
        "gross_win_usd": float(gw), "gross_loss_usd": float(gl),
        "pf": float(gw / gl) if gl > 0 else None,
        "ret_pct": (float(res["final_equity"]) / init - 1.0) * 100.0,
        "mdd_pct": cs["mdd_pct"], "min_equity_pct": cs["min_equity_pct"], "min_equity_date": cs["min_equity_date"],
        "ruin_days": cs["ruin_days"], "ruined_ledger": res.get("ruined_at") is not None,
        "mae_max_pct": float(-min([p.mae_pct for p in pos] or [0.0])),
        "worst_trade_pct": float(-min([p.profit_pct for p in closed] or [0.0])),
        "n_liq": len(liq), "liq_loss_pct": float(sum(p.profit_pct for p in liq)),
        "first_liq_days": float((min(p.close_time for p in liq) - trade_start) / DAY) if liq else None,
        "max_layers": int(max([p.layers for p in pos] or [0])),
        "layers_sum": int(sum(p.layers for p in closed)),
        "time_open_pct": 100.0 * _union_ms(intervals) / max(1, end - trade_start),
        "holds_h": holds, "days": days,
        "funding_pct": float(sum((p.funding_usd or 0.0) for p in pos) / init * 100.0),
        "fees_pct": float(sum((p.fees_usd or 0.0) for p in pos) / init * 100.0),
        "end_open": len(forced), "end_open_pnl_pct": float(sum(p.profit_pct for p in forced)),
        "dca_rejected": int(res.get("dca_layers_rejected", 0)), "rejected_for_capital": int(res.get("rejected_for_capital", 0)),
        "_curve": (t, eq, wq),
    }


# ─── Chạy ───────────────────────────────────────────────────────────────────
def window_bounds(window: str, spec: Dict[str, Any], data_start: int, data_end: int) -> Tuple[int, int, int]:
    """-> (start_ts nạp dữ liệu, trade_start_ts, end_ts)."""
    if window == "A":
        trade_start = max(data_end - spec["days"] * DAY, data_start + WARMUP)
        return trade_start - WARMUP, trade_start, data_end
    return data_start, data_start + WARMUP, data_end


def run_config(symbol: str, strategies: List[Dict[str, Any]], start: int, trade_start: int, end: int) -> Dict[str, Any]:
    """Một lần chạy PortfolioEngine trên MỘT tài sản (một sổ vốn riêng), không kill-switch, không trần rủi ro."""
    import contextlib
    import io
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.dsl.strategy import RiskConfig
    risk = RiskConfig(max_positions=10, max_per_symbol=4, max_gross_exposure=1e9, kill_switch_dd_pct=0.0)
    eng = PortfolioEngine([symbol], strategies, start, end, trade_start_ts=trade_start, initial_capital=INITIAL,
                          risk=risk, venue="cex")
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
        eng.run()
    return compute_metrics(eng.get_results(), trade_start, end)


def run_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Một (bot, tài sản, biến thể vào lệnh, cửa sổ): baseline + đối chứng SL cứng (stop_fill extreme và level).
    Gộp chung để cache dữ liệu theo tiến trình được dùng lại."""
    spec, sym, variant, window = job["spec"], job["symbol"], job["variant"], job["window"]
    start, trade_start, end = window_bounds(window, spec, job["data_start"], job["data_end"])
    symbol = f"{sym}@perp"
    runs = {}
    plan = [("base", 0.0, "extreme")]
    if job.get("controls", True):
        plan += [("sl_extreme", spec["sl_control_pct"], "extreme"), ("sl_level", spec["sl_control_pct"], "level")]
        if spec["sl2span_pct"] > 0:   # đối chứng đúng đặc tả: SL = 2 × biên độ DCA (thường nằm SAU giá thanh lý -> vô hiệu)
            plan.append(("sl_2span", spec["sl2span_pct"], "extreme"))
    for tag, sl, fill in plan:
        m = run_config(symbol, build_strategies(spec, variant, sl, fill), start, trade_start, end)
        runs[tag] = m
    return {"bot": spec["name"], "symbol": sym, "variant": variant, "window": window, "start": start,
            "trade_start": trade_start, "end": end, "runs": runs}


def aggregate(items: List[Dict[str, Any]], trade_start: int, end: int) -> Dict[str, Any]:
    """Gộp các tài sản của một bot (vốn chia đều, không tái cân bằng): đường vốn = trung bình các đường vốn."""
    n = len(items)
    trades = sum(m["trades"] for m in items)
    wins = sum(m["wins"] for m in items)
    losses = sum(m["losses"] for m in items)
    gw, gl = sum(m["gross_win_usd"] for m in items), sum(m["gross_loss_usd"] for m in items)
    frames = [hourly_frame(*m["_curve"]) for m in items]
    eq = pd.concat([f["eq"] for f in frames], axis=1).sort_index().ffill().bfill().mean(axis=1)
    wo = pd.concat([f["worst"] for f in frames], axis=1).sort_index().ffill().bfill().mean(axis=1)
    agg_df = pd.DataFrame({"eq": eq, "worst": np.minimum(wo, eq)})
    cs = curve_stats(agg_df, trade_start)
    holds = sorted(h for m in items for h in m["holds_h"])
    liqs = [m["first_liq_days"] for m in items if m["first_liq_days"] is not None]
    ruins = [m["ruin_days"] for m in items if m["ruin_days"] is not None]
    days = max(1e-9, (end - trade_start) / DAY)
    daily = agg_df[agg_df.index >= pd.to_datetime(trade_start, unit="ms")].resample("1D").agg({"eq": "last", "worst": "min"})
    return {
        "n_assets": n, "trades": trades, "wins": wins, "losses": losses,
        "win_rate": 100.0 * wins / trades if trades else None,
        "avg_win_pct": (sum(m["sum_win_pct"] for m in items) / wins) if wins else None,
        "avg_loss_pct": (sum(m["sum_loss_pct"] for m in items) / losses) if losses else None,
        "pf": gw / gl if gl > 0 else None,
        "ret_pct": float(np.mean([m["ret_pct"] for m in items])),
        "ret_by_asset": [round(m["ret_pct"], 2) for m in items],
        "mdd_pct": cs["mdd_pct"], "min_equity_pct": cs["min_equity_pct"], "min_equity_date": cs["min_equity_date"],
        "mdd_by_asset": [round(m["mdd_pct"], 2) for m in items],
        "ruin_days": cs["ruin_days"], "ruined_assets": len(ruins),
        "ruin_first_days_any": min(ruins) if ruins else None,
        "mae_max_pct": max(m["mae_max_pct"] for m in items), "worst_trade_pct": max(m["worst_trade_pct"] for m in items),
        "n_liq": sum(m["n_liq"] for m in items), "liq_loss_pct": sum(m["liq_loss_pct"] for m in items) / n,
        "first_liq_days": min(liqs) if liqs else None,
        "max_layers": max(m["max_layers"] for m in items),
        "mean_layers": sum(m["layers_sum"] for m in items) / trades if trades else None,
        "time_open_pct": float(np.mean([m["time_open_pct"] for m in items])),
        "hold_med_h": float(np.median(holds)) if holds else None,
        "trades_per_day": trades / days,   # tổng số lệnh/ngày trên mọi tài sản (so với per_day của bot)
        "funding_pct": float(np.mean([m["funding_pct"] for m in items])),
        "fees_pct": float(np.mean([m["fees_pct"] for m in items])),
        "end_open": sum(m["end_open"] for m in items), "end_open_pnl_pct": float(np.mean([m["end_open_pnl_pct"] for m in items])),
        "dca_rejected": sum(m["dca_rejected"] for m in items),
        "daily": [[str(i.date()), round(float(r["eq"]), 4), round(float(r["worst"]), 4)] for i, r in daily.iterrows()],
    }


def strip(m: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in m.items() if k not in ("_curve", "holds_h")}


def build_jobs(specs: List[Dict[str, Any]], windows, variants, extents: Dict[str, Tuple[int, int]],
               controls: bool = True) -> List[Dict[str, Any]]:
    jobs = []
    for spec in specs:
        for window in windows:
            for variant in variants:
                for sym in spec["symbols"]:
                    ds, de = extents[sym]
                    jobs.append({"spec": spec, "symbol": sym, "variant": variant, "window": window,
                                 "data_start": ds, "data_end": de, "controls": controls})
    return jobs


def _fmt(x, nd=1, suffix=""):
    return "—" if x is None else f"{x:.{nd}f}{suffix}"


def print_table(rows: List[Dict[str, Any]]) -> None:
    head = (f"{'bot':20s} {'vào':9s} {'cs':2s} {'cfg':10s} {'lệnh':>6s} {'win%':>6s} {'PF':>6s} {'ret%':>8s} {'MDD%':>6s} "
            f"{'liq':>4s} {'liq1(d)':>7s} {'cháy(d)':>7s} {'tầng':>4s} {'mở%':>5s}")
    print(head)
    for r in rows:
        a = r["agg"]
        print(f"{r['bot'][:20]:20s} {r['variant']:9s} {r['window']:2s} {r['cfg']:10s} {a['trades']:6d} "
              f"{_fmt(a['win_rate']):>6s} {_fmt(a['pf'], 2):>6s} {_fmt(a['ret_pct']):>8s} {_fmt(a['mdd_pct']):>6s} "
              f"{a['n_liq']:4d} {_fmt(a['first_liq_days']):>7s} {_fmt(a['ruin_days']):>7s} {a['max_layers']:4d} "
              f"{_fmt(a['time_open_pct']):>5s}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", default=",".join(SELECTED), help="tên bot (đúng như trong BOTS), phân tách bằng dấu phẩy")
    ap.add_argument("--windows", default="A,B")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--no-controls", action="store_true", help="bỏ qua các lần chạy đối chứng SL cứng")
    ap.add_argument("--size-scale", type=float, default=1.0,
                    help="nhân ký quỹ lệnh đầu với hệ số này (độ nhạy; 1 = LỚN NHẤT thoả dca_budget_check)")
    ap.add_argument("--workers", default="auto", help="số tiến trình; 'auto' = theo RAM (gồm cgroup) và CPU")
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args(argv)

    from backend.models.params import resolve_costs
    from backend.crawl.store import require_data_ok_or_exit
    from backend.crawl.store import read_manifest
    from backend.optimize.process.workers import require_memory_limit, worker_init
    from backend.optimize.process.workers import resolve_workers
    require_memory_limit("research_topbots")
    t0 = time.time()
    costs = resolve_costs("cex", "perp", None, None)
    avail = available_symbols()
    names = [s.strip() for s in a.bots.split(",") if s.strip()]
    by_name = {b["name"]: b for b in parse_bots() if b.get("grp") == "Trade" and b.get("v")}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise SystemExit(f"Không có bot trong BOTS: {missing}")
    specs = [map_bot(by_name[n], avail, costs) for n in names]
    if not 0 < a.size_scale <= 1.0:
        raise SystemExit("--size-scale phải trong (0, 1]")
    for s in specs:
        s["size_scale"] = a.size_scale
        s["order_size_pct_per_side"] = _floor4(s["order_size_pct_per_side"] * a.size_scale)
        if not s["symbols"]:
            raise SystemExit(f"{s['name']}: không tài sản nào của top_syms có dữ liệu ({s['top_syms']})")
    syms = sorted({x for s in specs for x in s["symbols"]})
    # Cổng chất lượng dữ liệu BẮT BUỘC (không nới); gọi ở tiến trình cha để worker thừa kế cache khi fork.
    gate = require_data_ok_or_exit([f"{x}@perp" for x in syms])
    extents = {}
    for x in syms:
        m = read_manifest(f"{x}@perp")
        extents[x] = (int(m["start_ts"]), int(m["end_ts"]))
    end_common = min(e for _, e in extents.values())
    extents = {k: (v[0], end_common) for k, v in extents.items()}
    windows = [w.strip().upper() for w in a.windows.split(",") if w.strip()]
    variants = [v.strip() for v in a.variants.split(",") if v.strip()]
    jobs = build_jobs(specs, windows, variants, extents, controls=not a.no_controls)
    # 1500 MB/worker: nạp 1m cả 3 năm + cột kernel của một tài sản (tối đa ~1,1 triệu nến thật) — ước lượng, chưa đo
    workers = min(resolve_workers(a.workers, 1500, "research_topbots"), len(jobs))
    print(f"{len(specs)} bot, {len(jobs)} job (mỗi job 1-3 lần chạy), {workers} worker; dữ liệu đến "
          f"{pd.Timestamp(end_common, unit='ms'):%Y-%m-%d %H:%M}", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        results = list(pool.map(run_job, jobs, chunksize=1))

    # Gộp theo (bot, biến thể, cửa sổ, cấu hình)
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for r in results:
        groups.setdefault((r["bot"], r["variant"], r["window"]), []).append(r)
    rows, per_asset = [], []
    for (bot, variant, window), items in groups.items():
        for cfg in items[0]["runs"]:
            agg = aggregate([it["runs"][cfg] for it in items], items[0]["trade_start"], items[0]["end"])
            rows.append({"bot": bot, "variant": variant, "window": window, "cfg": cfg, "agg": agg,
                         "trade_start": items[0]["trade_start"], "end": items[0]["end"],
                         "symbols": [it["symbol"] for it in items]})
        for it in items:
            per_asset.append({"bot": bot, "variant": variant, "window": window, "symbol": it["symbol"],
                              "runs": {c: strip(m) for c, m in it["runs"].items()}})
    order = {n: i for i, n in enumerate(names)}
    rows.sort(key=lambda r: (order[r["bot"]], r["window"], r["variant"], ("base", "sl_extreme", "sl_level", "sl_2span").index(r["cfg"])))
    per_asset.sort(key=lambda r: (order[r["bot"]], r["window"], r["variant"], r["symbol"]))
    print_table(rows)

    os.makedirs(a.out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(a.out, f"{ts}.json" if a.size_scale == 1.0 else f"{ts}_scale{a.size_scale:g}.json")
    import os as _os
    import sys as _sys
    payload = {
        "ts": ts, "size_scale": a.size_scale, "source_html": BOTS_HTML, "data_end": end_common, "costs_taker_maker_slip": list(costs),
        "constants": {"COOLDOWN_MIN": COOLDOWN_MIN, "MIN_ORDER_SIZE_PCT": MIN_ORDER_SIZE_PCT, "RUIN_FRAC": RUIN_FRAC,
                      "INITIAL": INITIAL, "WARMUP_DAYS": WARMUP // DAY},
        "reversion_trees": {k: SIGNALS[k]["tree"] for k in ("dip_5m_rsi_bb_ranging", "rip_5m_rsi_bb_ranging")},
        "data_gate": {k: {"status": v.get("status"), "score": v.get("score")} for k, v in gate.items()},
        "specs": specs, "aggregates": rows, "per_asset": per_asset, "elapsed_s": round(time.time() - t0, 1),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"lưu: {path}  ({time.time() - t0:.0f}s)")
    return path


if __name__ == "__main__":
    main()
