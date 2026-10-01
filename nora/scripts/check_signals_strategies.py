"""Bước 2: kiểm tra TÍN HIỆU và CHIẾN LƯỢC trên toàn bộ dữ liệu thật (data/cex + data/dex).

1. Tín hiệu (alpha/strategy_library.SIGNALS): có thông tin về giá tương lai không (signals/diagnostics.py).
2. Chiến lược (alpha/strategy_library.KERNEL_STRATEGIES): backtest toàn kỳ dữ liệu của từng tài sản,
   đo lợi nhuận, MDD mark-to-market (thấy lỗ treo), lỗ treo tối đa trong lệnh, số tầng DCA, thanh lý.

Kết quả: data/_cache/reports/step2_<ngày>.json + bảng tóm tắt in ra màn hình.
Dùng:  PYTHONPATH=. python scripts/check_signals_strategies.py [--assets BTC,AERO] [--workers auto|4]
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)


def run_asset(symbol: str) -> dict:
    import io
    import contextlib
    from backend.alpha.strategy_library import KERNEL_STRATEGIES, SIGNALS
    from backend.backtest.engine import BacktestEngine
    from backend.backtest.metrics import MetricsCalculator
    from backend.backtest.params_builder import build_params, venue_of_symbol
    from backend.db.local_pkl import read_manifest
    from backend.signals.diagnostics import check_signals

    manifest = read_manifest(symbol) or {}
    venue = venue_of_symbol(symbol)
    start, end = int(manifest["start_ts"]), int(manifest["end_ts"])
    out = {"symbol": symbol, "venue": venue, "days": manifest.get("coverage_days"), "signals": {}, "strategies": {}}

    started = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        out["signals"] = check_signals(symbol, SIGNALS)["signals"]
    out["signals_seconds"] = round(time.time() - started, 1)

    for strat in KERNEL_STRATEGIES:
        params = {k: v for k, v in strat["default_params"].items() if k != "initial_capital"}
        if venue == "dex" and params.get("market") == "perp":
            out["strategies"][strat["id"]] = {"skipped": "DEX không có perp"}
            continue
        flow = strat["flows"][0]
        t0 = time.time()
        engine = BacktestEngine(0, 0, symbol, start, end, initial_capital=10000.0)
        engine.add_strategy_flow(flow["name"], build_params(flow["name"], flow["ast"], flow["type"], params, venue, symbol))
        with contextlib.redirect_stdout(io.StringIO()):
            engine.load_data()
            engine.run()
        pos = engine.closed_positions
        mtm = MetricsCalculator.calculate(pos, 10000.0, equity_curve=engine.equity_curve)
        closed = MetricsCalculator.calculate(pos, 10000.0)
        out["strategies"][strat["id"]] = {
            "trades": len(pos),
            "return_pct": mtm["total_pnl_pct"],
            "mdd_mtm_pct": mtm["max_drawdown_pct"],
            "mdd_closed_trades_pct": closed["max_drawdown_pct"],
            "win_rate": closed["winrate"],
            "profit_factor": closed["profit_factor"],
            "avg_layers": round(sum(p.layers for p in pos) / len(pos), 2) if pos else 0,
            "worst_mae_pct": round(min((p.mae_pct for p in pos), default=0.0), 2),
            "liquidations": sum(1 for p in pos if int(p.status) == 5),
            "fees_pct_of_capital": round(sum(p.fees_usd for p in pos) / 10000.0 * 100, 2),
            "seconds": round(time.time() - t0, 1),
        }
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--assets", default=None)
    p.add_argument("--workers", default="auto",
                   help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    args = p.parse_args(argv)
    from backend.db.data_layout import cache_dir, list_assets
    from backend.utils.memwatch import require_memory_limit, worker_init
    from backend.utils.parallel import resolve_workers
    require_memory_limit("check_signals_strategies")
    # 1200 MB/worker: mỗi job nạp TOÀN BỘ nến một tài sản (nhiều khung) cho check_signals + backtest từng chiến lược (chưa đo thực)
    workers = resolve_workers(args.workers, 1200, "check_signals_strategies")
    assets = [a["qualified"] for a in list_assets() if a["venue"] in ("cex", "dex")]
    if args.assets:
        wanted = {s.strip().upper() for s in args.assets.split(",")}
        assets = [a for a in assets if a.split(":")[-1] in wanted]

    results = []
    with ProcessPoolExecutor(max_workers=workers, initializer=worker_init) as pool:
        futures = {pool.submit(run_asset, a): a for a in assets}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            print(f"[done] {res['symbol']} ({res['venue']})", flush=True)
    results.sort(key=lambda r: (r["venue"], r["symbol"]))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = os.path.join(cache_dir(None, "reports"), f"step2_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1, default=str)
    print(f"\nĐã lưu: {path}\n")

    print("== TÍN HIỆU (mốc tốt nhất; CO_THONG_TIN = |t|>=3 và ổn định) ==")
    for r in results:
        for name, s in r["signals"].items():
            print(f"{r['venue']}/{r['symbol']:5s} {name:32s} {s['verdict']:13s} {s.get('reason', '')}")
    print("\n== CHIẾN LƯỢC (toàn kỳ; MDD tính cả lỗ treo) ==")
    for r in results:
        for sid, s in r["strategies"].items():
            if "skipped" in s:
                continue
            print(f"{r['venue']}/{r['symbol']:5s} {sid:30s} lệnh={s['trades']:5d} lãi={s['return_pct']:8.2f}% "
                  f"MDD={s['mdd_mtm_pct']:6.2f}% (đóng lệnh {s['mdd_closed_trades_pct']:6.2f}%) WR={s['win_rate']:5.1f}% "
                  f"PF={s['profit_factor']:5.2f} tầng={s['avg_layers']} MAE={s['worst_mae_pct']}% "
                  f"liq={s['liquidations']} phí={s['fees_pct_of_capital']}%")


if __name__ == "__main__":
    main()
