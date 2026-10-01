"""Trend danh mục kiểu CTA: MỘT bộ tham số chung cho mọi tài sản CEX perp, hai chiều, engine thật.

Vì sao: tối ưu riêng từng cặp (34 cặp × 60 cấu hình) chỉ ra 1 alpha — dễ là may mắn. Bộ tham số chung
cho 8 tài sản có ít bậc tự do hơn nhiều; lãi đến từ việc cộng nhiều edge nhỏ, ít tương quan.

Quy trình chống overfit:
1. dev = 80% đầu dữ liệu. Mỗi cấu hình chạy trên cả 8 tài sản (long + short cùng một sổ vốn / tài sản).
   Danh mục = chia đều vốn cho 8 tài sản (đường vốn MTM theo giờ, gồm funding, SL khớp bi quan).
2. Chọn cấu hình CHỈ theo dev: lãi danh mục / MDD danh mục, yêu cầu >= 5/8 tài sản có lãi.
3. Holdout 20% cuối: chạy đúng các cấu hình đã chọn (không chọn lại).

Dùng: PYTHONPATH=. python scripts/research_trend_portfolio.py [--workers auto|12] [--top 5]
"""
import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]
DAY = 86_400_000
WARMUP = 20 * DAY


def _families():
    from backend.alpha.strategy_library import cond, f, p
    return {
        # 1h xu hướng + phá đỉnh/đáy 15m (họ của alpha SOL)
        "ema1h_dch15m": {
            "LONG": cond((f("1h", "ema_50"), ">", f("1h", "ema_200")), (f("1h", "adx_14"), ">", p("adx_min", 20)),
                         (f("15m", "close"), ">", f("15m", "dch_20"))),
            "SHORT": cond((f("1h", "ema_50"), "<", f("1h", "ema_200")), (f("1h", "adx_14"), ">", p("adx_min", 20)),
                          (f("15m", "close"), "<", f("15m", "dcl_20"))),
        },
        # 4h phá đỉnh/đáy N nến (Turtle) theo xu hướng 4h
        "dch4h": {
            "LONG": cond((f("4h", "ema_50"), ">", f("4h", "ema_200")), (f("4h", "close"), ">", f("4h", "dch_20"))),
            "SHORT": cond((f("4h", "ema_50"), "<", f("4h", "ema_200")), (f("4h", "close"), "<", f("4h", "dcl_20"))),
        },
    }


def _grid():
    base = {"market": "perp", "leverage": 1, "order_size_pct": 100, "stop_fill": "extreme"}
    out = []
    for adx, sl, tr, to in itertools.product([20, 25], [3.0, 4.0], [3.0, 5.0], [4320, 0]):
        out.append(("ema1h_dch15m", {**base, "stop_loss_rate": sl, "trailing_stop": tr, "trailing_activation_pct": 1.5,
                                     "timeout": to, "sig.adx_min": adx}))
    for sl, tr, act in itertools.product([4.0, 6.0], [5.0, 8.0], [0.0, 3.0]):
        out.append(("dch4h", {**base, "stop_loss_rate": sl, "trailing_stop": tr, "trailing_activation_pct": act,
                              "timeout": 0}))
    return out


def _run(args):
    """Một tài sản, một cấu hình, một khoảng: đường vốn MTM theo giờ (tỉ lệ so với vốn đầu) + thống kê lệnh."""
    import contextlib
    import io
    from backend.alpha.params_template import resolve_placeholders, split_params
    from backend.backtest.engine import BacktestEngine
    from backend.backtest.params_builder import build_params
    family, params, symbol, start, end, sides = args
    signal, position = split_params(dict(params))
    fam = _families()[family]
    eng = BacktestEngine(0, 0, f"{symbol}@perp", start - WARMUP, end, trade_start_ts=start, initial_capital=10000.0)
    for side in sides:
        tree = resolve_placeholders(fam[side], signal)
        eng.add_strategy_flow(f"{side}_{family}", build_params(
            f"{side}_{family}", {"type": side, "match": [{"condition": tree}], "stop": []}, side, position, "cex",
            symbol=f"{symbol}@perp"))
    with contextlib.redirect_stdout(io.StringIO()):
        eng.load_data()
        eng.run()
    res = eng.get_results()
    curve = pd.DataFrame(res["equity_curve"])
    curve = curve[curve["time"] >= start]
    pos = res["positions"]
    pnl = np.array([p.real_pnl for p in pos]) if pos else np.array([])
    return {"symbol": symbol, "family": family, "params": params,
            "t": curve["time"].to_numpy().tolist(), "eq": (curve["equity"] / 10000.0).round(6).tolist(),
            "eq_worst": (curve["equity_worst"] / 10000.0).round(6).tolist(),
            "n": int(len(pos)), "win": float((pnl > 0).mean() * 100) if len(pnl) else 0.0,
            "pf": float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else None,
            "funding_usd": float(sum(p.funding_usd or 0 for p in pos)),
            "ret_pct": float((res["final_equity"] / 10000.0 - 1) * 100)}


def portfolio(runs):
    """Chia đều vốn: đường vốn danh mục = trung bình các đường vốn (theo giờ, ffill)."""
    frames = []
    for r in runs:
        s = pd.Series(r["eq"], index=pd.to_datetime(r["t"], unit="ms"), name=r["symbol"])
        w = pd.Series(r["eq_worst"], index=s.index)
        frames.append((s[~s.index.duplicated()], w[~w.index.duplicated()]))
    eq = pd.concat([f[0] for f in frames], axis=1).sort_index().ffill().bfill()
    worst = pd.concat([f[1] for f in frames], axis=1).sort_index().ffill().bfill()
    port = eq.mean(axis=1)
    # điểm xấu nhất: mỗi tài sản ở mức worst của giờ đó (bi quan — các đáy không nhất thiết cùng lúc)
    port_worst = worst.mean(axis=1)
    peak = port.cummax()
    mdd = float(((peak - port_worst) / peak).max() * 100)
    daily = port.resample("1D").last().pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0
    days = (port.index[-1] - port.index[0]).days or 1
    ret = float((port.iloc[-1] - 1) * 100)
    cagr = float(((port.iloc[-1]) ** (365 / days) - 1) * 100) if port.iloc[-1] > 0 else -100.0
    return {"ret_pct": round(ret, 2), "cagr_pct": round(cagr, 2), "mdd_pct": round(mdd, 2),
            "sharpe": round(sharpe, 2), "days": days, "corr_mean": round(float(
                eq.resample("1D").last().pct_change().corr().where(~np.eye(eq.shape[1], dtype=bool)).stack().mean()), 2),
            "series": port}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "data", "_cache", "reports"))
    a = ap.parse_args(argv)
    from backend.db.local_pkl import read_manifest
    from backend.utils.memwatch import require_memory_limit, worker_init
    from backend.utils.parallel import resolve_workers
    require_memory_limit("research_trend_portfolio")
    # 900 MB/worker: mỗi job (_run) backtest MỘT tài sản × một cấu hình × một khoảng — danh mục 8 tài sản chỉ gộp đường vốn
    # ở tiến trình chính, không nạp 8 tài sản trong một worker (chưa đo thực)
    workers = resolve_workers(a.workers, 900, "research_trend_portfolio")
    starts, ends = [], []
    for s in ASSETS:
        m = read_manifest(f"{s}@perp")
        starts.append(int(m["start_ts"]))
        ends.append(int(m["end_ts"]))
    start, end = max(starts) + WARMUP, min(ends)
    split = start + int((end - start) * 0.8)
    print(f"dev {pd.Timestamp(start, unit='ms'):%Y-%m-%d} → {pd.Timestamp(split, unit='ms'):%Y-%m-%d}, "
          f"holdout → {pd.Timestamp(end, unit='ms'):%Y-%m-%d}", flush=True)

    grid = _grid()
    t0 = time.time()
    jobs = [(fam, prm, sym, start, split, ("LONG", "SHORT")) for fam, prm in grid for sym in ASSETS]
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        runs = list(pool.map(_run, jobs, chunksize=1))
    print(f"dev: {len(jobs)} lần chạy, {time.time() - t0:.0f}s", flush=True)

    table = []
    for gi, (fam, prm) in enumerate(grid):
        rr = runs[gi * len(ASSETS):(gi + 1) * len(ASSETS)]
        pf = portfolio(rr)
        pos_assets = sum(r["ret_pct"] > 0 for r in rr)
        table.append({"i": gi, "family": fam, "params": prm, "dev": {k: v for k, v in pf.items() if k != "series"},
                      "dev_assets_positive": pos_assets,
                      "dev_by_asset": {r["symbol"]: round(r["ret_pct"], 1) for r in rr},
                      "score": pf["ret_pct"] / max(pf["mdd_pct"], 1.0) if pos_assets >= 5 else -1e9})
    table.sort(key=lambda x: -x["score"])
    for row in table[:10]:
        print(f"#{row['i']:2d} {row['family']:13s} {json.dumps({k: v for k, v in row['params'].items() if k not in ('market', 'leverage', 'order_size_pct', 'stop_fill')})}"
              f"\n     dev: {row['dev']}  +{row['dev_assets_positive']}/8  {row['dev_by_asset']}")

    chosen = [r for r in table if r["score"] > 0][: a.top]
    jobs = [(r["family"], r["params"], sym, split, end, ("LONG", "SHORT")) for r in chosen for sym in ASSETS]
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        hruns = list(pool.map(_run, jobs, chunksize=1))
    print("\n== HOLDOUT (chỉ các cấu hình đã chọn trên dev) ==")
    for ci, row in enumerate(chosen):
        rr = hruns[ci * len(ASSETS):(ci + 1) * len(ASSETS)]
        pf = portfolio(rr)
        row["holdout"] = {k: v for k, v in pf.items() if k != "series"}
        row["holdout_by_asset"] = {r["symbol"]: round(r["ret_pct"], 1) for r in rr}
        row["holdout_trades"] = sum(r["n"] for r in rr)
        print(f"#{row['i']:2d} {row['family']:13s} holdout: {row['holdout']}  lệnh {row['holdout_trades']}  {row['holdout_by_asset']}")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"trend_portfolio_{time.strftime('%Y%m%d_%H%M')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"dev_window": [start, split], "holdout_window": [split, end], "table": table}, fh, default=str)
    print("lưu:", path)


if __name__ == "__main__":
    main()
