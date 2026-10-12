"""P17 — so sánh số đo CŨ (công thức tự cài của Nora) với MỚI (thống kê NautilusTrader qua backend/nautilus/stats.py) trên 3 lần chạy THẬT.

Đường chạy: backend.jobs.tasks.run_custom (đúng đường của nút "Chạy", chế độ Nhanh = run_frame rỗng), mẫu giáo dục
data/alpha/education/samples.json: KEMA (trend_kema_breakout), RSI+BB đảo chiều có DCA (revert_rsi_bb + position.dca_*), Donchian (breakout_donchian_turtle).
Mỗi lần chạy, `trades._metric_block` được bọc để bắt (lợi suất ngày, lệnh) của từng giai đoạn simulate/train/test; MỚI = chính hàm của Nora (đã đổi
sang Nautilus), CŨ = bản sao công thức cũ nằm trong file này (CHỈ để so sánh, không dùng ở nơi khác).

Chạy: ops/run_limited.sh --no-lock -- test/scripts/p17_metrics_compare.py [--start 2025-01-01 --end 2025-06-30]
Ghi: test/fixtures/p17_metrics_compare.json. Thoát 1 nếu có chênh lệch KHÔNG giải thích được.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)

from backend.metrics import metrics as mm                      # noqa: E402
from backend.metrics import trades as tr                       # noqa: E402
from backend.jobs import tasks                     # noqa: E402

ANN = 365
RUNS = [
    {"key": "trend_kema_breakout", "label": "KEMA", "position": None},
    {"key": "revert_rsi_bb", "label": "DCA (RSI+BB, dca_step 2% x 2 tầng)", "position": {"dca_step_pct": 2.0, "dca_max_layers": 2}},
    {"key": "breakout_donchian_turtle", "label": "Donchian breakout", "position": None},
]


# ── CÔNG THỨC CŨ (bản sao từ git HEAD trước P17-stats; chỉ để so sánh) ─────────────────────────────────────────────
def old_returns(r):
    r = np.asarray(r, dtype=float)
    out = {"sharpe": None, "sortino": None, "vol_ann_pct": None, "cagr_pct": None, "mdd_daily_pct": 0.0, "calmar": None}
    if r.size:
        g = float(np.prod(1.0 + r))
        out["cagr_pct"] = -100.0 if g <= 0 else float((g ** (ANN / r.size) - 1.0) * 100.0)
        eq = np.cumprod(np.maximum(0.0, 1.0 + r))
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        out["mdd_daily_pct"] = float(((peak - eq) / peak).max() * 100.0)
    if r.size >= 2:
        sd = float(np.std(r, ddof=1))
        out["sharpe"] = float(np.mean(r) / sd * math.sqrt(ANN)) if sd > 1e-12 else None
        dd = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))
        out["sortino"] = float(np.mean(r) / dd * math.sqrt(ANN)) if dd > 1e-12 else None
        out["vol_ann_pct"] = float(sd * math.sqrt(ANN) * 100.0)
    if out["cagr_pct"] is not None and abs(out["mdd_daily_pct"]) > 1e-9:
        out["calmar"] = out["cagr_pct"] / abs(out["mdd_daily_pct"])
    return out


def old_trades(rows):
    pnl = np.asarray([r["pnl_usd"] for r in rows], dtype=float)
    pct = np.asarray([r["pnl_pct"] for r in rows if r["pnl_pct"] is not None], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gl = float(-losses.sum())
    return {"win_rate": float(wins.size / pnl.size * 100.0) if pnl.size else None,
            "profit_factor_trades": float(wins.sum() / gl) if gl > 0 else None,
            "avg_win_usd": float(wins.mean()) if wins.size else None, "avg_loss_usd": float(losses.mean()) if losses.size else None,
            "expectancy_usd": float(pnl.mean()) if pnl.size else None, "expectancy_pct": float(pct.mean()) if pct.size else None,
            "breakeven": int(pnl.size - wins.size - losses.size)}


def new_values(ret, rows):
    rm = mm.return_metrics(np.asarray(ret, dtype=float))
    tm = tr.trade_metrics(rows)
    blk = mm.series_metrics(np.asarray(ret, dtype=float), rows)
    return {"sharpe": rm["sharpe"], "sortino": rm["sortino"], "vol_ann_pct": rm["vol_ann_pct"], "cagr_pct": rm["cagr_pct"],
            "mdd_daily_pct": rm["mdd_daily_pct"], "calmar": rm["calmar"], "win_rate": tm["win_rate"],
            "profit_factor_trades": blk["profit_factor"],            # khoá phẳng của giai đoạn: Nautilus ProfitFactor trên lợi suất NGÀY
            "profit_factor_trade_level": tm["profit_factor"],          # stats.trades.profit_factor: Nautilus ProfitFactor trên PnL từng lệnh
            "avg_win_usd": tm["avg_win_usd"], "avg_loss_usd": tm["avg_loss_usd"], "expectancy_usd": tm["expectancy_usd"],
            "expectancy_pct": tm["expectancy_pct"]}


def close(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def explain(name, old, new, extra):
    """(giải thích, có_giải_thích_được). Trùng -> 'khớp'."""
    if name in ("sharpe", "sortino", "vol_ann_pct", "cagr_pct", "mdd_daily_pct", "calmar", "win_rate", "avg_win_usd", "avg_loss_usd"):
        why = {"sharpe": "cùng công thức (mean/std ddof=1 x sqrt(365)); Nautilus SharpeRatio(period=365)",
               "sortino": "cùng công thức (độ lệch xuống so với 0, chia N); Nautilus SortinoRatio(period=365)",
               "vol_ann_pct": "cùng công thức (std ddof=1 x sqrt(365)); Nautilus ReturnsVolatility(365)",
               "cagr_pct": "cùng công thức (tích (1+r)^(365/n) - 1); Nautilus CAGR(365)",
               "mdd_daily_pct": "cùng công thức (sụt giảm của vốn nối từ r ngày); Nautilus MaxDrawdown (dấu âm, phân số)",
               "calmar": "CAGR / |MDD| như cũ; Nautilus CalmarRatio(365)",
               "win_rate": "cùng định nghĩa: lệnh PnL > 0 / mọi lệnh (hoà làm giảm); Nautilus WinRate",
               "avg_win_usd": "TB PnL > 0; Nautilus AvgWinner", "avg_loss_usd": "TB PnL < 0 (âm); Nautilus AvgLoser"}[name]
        return (why, close(old, new)) if close(old, new) else ("KHÔNG GIẢI THÍCH ĐƯỢC: công thức tương đương nhưng giá trị lệch", False)
    if name == "expectancy_usd" or name == "expectancy_pct":
        if close(old, new):
            return "khớp (không có lệnh hoà)", True
        if extra["breakeven"] > 0 or name == "expectancy_pct":
            return "Nautilus Expectancy = TB PnL các lệnh KHÁC 0 (bỏ lệnh hoà) trong khi Nora cũ chia cho mọi lệnh", extra["breakeven"] > 0
        return "KHÔNG GIẢI THÍCH ĐƯỢC", False
    if name == "profit_factor_trades":
        return ("Định nghĩa khác: Nautilus ProfitFactor = Σ lợi suất ngày dương / |Σ lợi suất ngày âm| (trên chuỗi NGÀY mark-to-market); "
                "Nora cũ = Σ lãi / Σ lỗ trên LỆNH ĐÃ ĐÓNG. Hai khái niệm khác nhau nên số khác nhau là bình thường"), True
    if name == "profit_factor_trade_level":
        return ("Cùng khái niệm cũ (lớp Nautilus ProfitFactor áp lên PnL từng lệnh): phải khớp", close(old, new))
    raise KeyError(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2025-06-30")
    ap.add_argument("--symbols", default="BTC@perp,ETH@perp")
    ap.add_argument("--out", default=os.path.join(NORA, "test", "fixtures", "p17_metrics_compare.json"))
    args = ap.parse_args()
    with open(os.path.join(NORA, "data", "alpha", "education", "samples.json"), encoding="utf-8") as f:
        samples = {s["key"]: s for s in json.load(f)}
    captured = []
    orig = tr._metric_block

    def spy(ret, rows, fees):
        captured.append((np.asarray(ret, dtype=float).copy(), [dict(r) for r in rows]))
        return orig(ret, rows, fees)

    tr._metric_block = spy
    report, bad = [], 0
    try:
        for run in RUNS:
            captured.clear()
            params = {"code": samples[run["key"]]["code"], "start": args.start, "end": args.end, "symbols": args.symbols.split(","), "train_ratio": 0.7,
                      "initial_capital": 10_000, "run_frame": ""}
            if run["position"]:
                params["position"] = run["position"]
            tasks._clear_data_caches()
            out = tasks.run_custom(params)
            stages = {}
            names = ["simulate", "train"] + (["test"])
            for stage, (ret, rows) in zip(names, captured[:3]):
                r = ret[1:] if ret.size else ret          # như _metric_block: bỏ phần tử 0 đứng đầu
                o = {**old_returns(r), **old_trades(rows)}
                n = new_values(r, rows)
                o["profit_factor_trade_level"] = o["profit_factor_trades"]
                table = {}
                for name in n:
                    old_v = o["profit_factor_trades"] if name == "profit_factor_trades" else o[name]
                    why, ok = explain(name, old_v, n[name], {"breakeven": o["breakeven"], "old_pf": o["profit_factor_trades"]})
                    if not ok:
                        bad += 1
                    table[name] = {"old": old_v, "new": n[name], "equal": close(old_v, n[name]), "explained": ok, "note": why}
                stages[stage] = {"days": int(r.size), "trades": len(rows), "breakeven_trades": o["breakeven"], "metrics": table,
                                 "payload_block": out["metrics"]["simulate" if stage == "simulate" else stage]}
            report.append({"sample": run["key"], "label": run["label"], "position": run["position"], "stages": stages})
    finally:
        tr._metric_block = orig
    doc = {"window": [args.start, args.end], "symbols": args.symbols.split(","), "mode": "Nhanh (run_frame rỗng)", "annualization_days": ANN,
           "global_notes": [
               "Nautilus mặc định period=252; Nora truyền period=365 vào chính các lớp Nautilus (SharpeRatio/SortinoRatio/ReturnsVolatility/CAGR/CalmarRatio) nên số khớp công thức cũ.",
               "Sharpe/Sortino/Vol của Nautilus gom lợi suất theo NGÀY lịch (Nora đã dùng chuỗi ngày nên không đổi).",
               "Khác biệt thật: (1) Profit factor ở khối giai đoạn nay là Nautilus ProfitFactor trên lợi suất NGÀY (không còn trên lệnh); (2) Expectancy bỏ lệnh hoà.",
               "Giữ nguyên Nora (Nautilus không có thống kê tương ứng): ret_pct, fees_usd, trades, MDD trong nến (equity_worst), var/cvar, bảng phụ.",
           ],
           "unexplained_differences": bad, "runs": report}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, default=float, allow_nan=False)
    for r in report:
        for st, v in r["stages"].items():
            diffs = [f"{k}: {m['old']!r:.9} -> {m['new']!r:.9}" for k, m in v["metrics"].items() if not m["equal"]]
            print(f"{r['sample']:28s} {st:9s} days={v['days']:4d} trades={v['trades']:3d} be={v['breakeven_trades']}  diffs: {diffs or 'none'}")
    print("unexplained:", bad, "->", args.out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
