"""Một lần chạy PortfolioEngine cho sổ chiến lược (job nền của API: POST /api/studio/book/backtest).

Nguồn sổ (chọn một):
  --book alphas/book.json                                  (mặc định) chiến lược + tham số + rủi ro/lệnh + giới hạn danh mục của sổ đã chốt
  --strategies '[{"id":"trend_long","params":{...}}]'      tự chỉ định; tham số thiếu lấy mức GIỮA của không gian tham số ứng viên
Cửa sổ: --start/--end (YYYY-MM-DD, UTC; ngày kết thúc tính CẢ ngày); mặc định = windows() của build_strategy_book (toàn bộ dữ liệu sau warmup).
Rủi ro/lệnh: --risk-per-trade (mặc định: của sổ, hoặc mức chuẩn 0,5%). SL: --stop-fill level|extreme (mặc định level).
Kết quả: số đo danh mục (portfolio_metrics) + by_symbol/by_strategy + lệnh + đường vốn (<= 2000 điểm) -> --out và/hoặc $NORA_JOB_DIR/result.json.

Dùng: scripts/run_limited.sh -- scripts/run_book_backtest.py --start 2025-03-01 --end 2025-04-30 --symbols BTC@perp,SOL@perp --out /tmp/r.json
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import argparse
import contextlib
import io
import json
import sys
import time
import warnings

import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

from backend.backtest.portfolio_metrics import portfolio_metrics  # noqa: E402
from backend.utils.jobresult import write_job_result  # noqa: E402
from backend.utils.jsonsafe import json_default  # noqa: E402

DAY = 86_400_000
WARMUP = 20 * DAY            # bằng build_strategy_book.WARMUP (chỉ số đo từ start trở đi)
MAX_CURVE_POINTS = 2000


def _ts(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").value // 1_000_000)


def _mid_params(candidate, params):
    """Điền tham số thiếu bằng mức giữa của không gian tham số (để {"id": "trend_long"} chạy được)."""
    out = dict(params or {})
    for key, values in candidate["space"].items():
        out.setdefault(key, values[len(values) // 2])
    return out


def load_items(a):
    """-> (items [(id, params)], rủi ro/lệnh mặc định, dict RiskConfig)."""
    from backend.alpha.strategy_book import BASE_RISK_PER_TRADE_PCT, CANDIDATES, RISK
    by_id = {c["id"]: c for c in CANDIDATES}
    if a.strategies:
        raw = json.loads(a.strategies)
        if not isinstance(raw, list) or not raw:
            raise SystemExit("--strategies phải là danh sách JSON không rỗng")
        items = []
        for s in raw:
            if s.get("id") not in by_id:
                raise SystemExit(f"Không có chiến lược: {s.get('id')}; có: {sorted(by_id)}")
            items.append((s["id"], _mid_params(by_id[s["id"]], s.get("params"))))
        return items, BASE_RISK_PER_TRADE_PCT, RISK
    path = a.book or os.path.join(NORA_ROOT, "alphas", "book.json")
    with open(path, encoding="utf-8") as fh:
        book = json.load(fh)
    items = [(s["id"], s["params"]) for s in book["strategies"]]
    bad = [i for i, _ in items if i not in by_id]
    if bad:
        raise SystemExit(f"book {path} có chiến lược không còn trong thư viện: {bad}")
    return items, book.get("risk_per_trade_pct") or BASE_RISK_PER_TRADE_PCT, book.get("risk") or RISK


def downsample(curve, limit=MAX_CURVE_POINTS):
    """<= limit điểm, cách đều theo chỉ số, luôn giữ điểm cuối (tất định)."""
    n = len(curve)
    if n <= limit:
        return list(curve)
    idx = sorted({round(i * (n - 1) / (limit - 1)) for i in range(limit)})
    return [curve[i] for i in idx]


def daily_nav(curve, end):
    """Vốn MTM cuối mỗi ngày UTC (từ đường vốn ĐẦY ĐỦ, chưa downsample) -> [{date, equity}]; dashboard dùng khi dữ liệu dài.
    Mẫu cuối đúng mốc `end` (loại trừ) tính vào ngày cuối thật (end - 1ms), không tạo thêm ngày 00:00."""
    last = {}
    for c in curve:
        last[pd.Timestamp(min(c["time"], end - 1), unit="ms").strftime("%Y-%m-%d")] = float(c["equity"])
    return [{"date": d, "equity": e} for d, e in last.items()]


def run(items, symbols, start, end, rpt, stop_fill, risk):
    from backend.alpha.strategy_book import CANDIDATES, materialize
    from backend.backtest.portfolio import PortfolioEngine, RiskConfig
    from backend.utils.memwatch import peak_rss_mb
    by_id = {c["id"]: c for c in CANDIDATES}
    strategies = [materialize(by_id[cid], prm, stop_fill=stop_fill, risk_per_trade_pct=rpt) for cid, prm in items]
    t0 = time.time()
    eng = PortfolioEngine(symbols, strategies, start - WARMUP, end, trade_start_ts=start, risk=RiskConfig.from_dict(risk))
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    out = portfolio_metrics(res, start)
    out["trade_list"] = [{
        "symbol": p.symbol, "strategy": p.strategy_id, "side": p.pos_type.name,
        "enter_time": p.enter_time, "enter_price": p.enter_price, "close_time": p.close_time, "close_price": p.close_price,
        "pnl": round(p.real_pnl, 4), "status": p.status.name, "close_reason": p.close_reason,
        # khối lượng + danh nghĩa (qty × giá vào trung bình sau DCA) + ký quỹ: để tính exposure/trọng số ở dashboard
        "qty": round(p.qty, 8), "notional": round(p.qty * (p.avg_price or p.enter_price), 2),
        "margin_usd": round(p.total_margin_usd or 0.0, 2),
    } for p in res["positions"]]
    curve = [{"time": c["time"], "equity": round(c["equity"], 2), "equity_worst": round(c["equity_worst"], 2)}
             for c in res["equity_curve"] if c["time"] >= start]
    out["equity_curve"] = downsample(curve)
    out["daily_nav"] = daily_nav(curve, end)
    out["config"] = {"strategies": [{"id": i, "params": p} for i, p in items], "symbols": symbols, "risk_per_trade_pct": rpt,
                     "stop_fill": stop_fill, "risk": res["risk"], "start": start, "end": end,
                     "initial_capital": res["initial_capital"]}
    out["final_equity"] = round(res["final_equity"], 2)
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}  # không tất định -> tách riêng
    return out


def main(argv=None):
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="", help="đường dẫn book.json (mặc định alphas/book.json)")
    ap.add_argument("--strategies", default="", help='JSON: [{"id": ..., "params": {...}}] (thay cho --book)')
    ap.add_argument("--symbols", default="", help="vd BTC@perp,SOL@perp (mặc định cả vũ trụ của sổ chiến lược)")
    ap.add_argument("--start", default="", help="YYYY-MM-DD UTC (mặc định đầu dữ liệu sau warmup)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD UTC, gồm cả ngày này (mặc định cuối dữ liệu)")
    ap.add_argument("--risk-per-trade", type=float, default=None)
    ap.add_argument("--stop-fill", default="level", choices=("level", "extreme"))
    ap.add_argument("--out", default="", help="ghi kết quả JSON ra đường dẫn này")
    a = ap.parse_args(argv)
    if a.book and a.strategies:
        ap.error("chọn một: --book hoặc --strategies")
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("run_book_backtest")
    from backend.alpha.strategy_book import perp_symbols

    symbols = [s if "@" in s else f"{s}@perp" for s in a.symbols.split(",") if s] or perp_symbols()
    items, rpt, risk = load_items(a)
    if a.risk_per_trade is not None:
        rpt = a.risk_per_trade
    if not (a.start and a.end):  # thiếu một đầu -> lấy theo dữ liệu có sẵn
        from backend.db.local_pkl import read_manifest
        ms = [read_manifest(s) for s in symbols]
        if not all(ms):
            raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
        data_start = max(int(m["start_ts"]) for m in ms) + WARMUP
        data_end = min(int(m["end_ts"]) for m in ms)
    start = _ts(a.start) if a.start else data_start
    end = _ts(a.end) + DAY if a.end else data_end
    if end <= start:
        raise SystemExit("--end phải sau --start")
    print(f"sổ {[i for i, _ in items]} | {len(symbols)} tài sản | {pd.Timestamp(start, unit='ms'):%Y-%m-%d} → "
          f"{pd.Timestamp(end, unit='ms'):%Y-%m-%d} | rủi ro/lệnh {rpt}% | SL {a.stop_fill}", flush=True)
    out = run(items, symbols, start, end, rpt, a.stop_fill, risk)
    print(f"lãi {out['ret_pct']}%  MDD {out['mdd_pct']}%  sharpe {out['sharpe']}  lệnh {out['trades']}  "
          f"+{out['symbols_positive']}/{len(symbols)}  kill={'có' if out['halted_at'] else 'không'}  "
          f"{json.dumps(out['by_strategy'], ensure_ascii=False, default=json_default)}", flush=True)
    print(f"thời gian {out['meta']['wall_s']}s | đỉnh RAM {out['meta']['peak_rss_mb']} MB", flush=True)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, default=json_default)
        print("ghi:", a.out)
    write_job_result(out)  # chỉ khi chạy như job API (env NORA_JOB_DIR)
    return out


if __name__ == "__main__":
    main()
