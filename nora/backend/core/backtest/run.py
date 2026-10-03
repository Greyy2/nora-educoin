"""Job backtest (POST /api/studio/book/backtest -> api/jobs/runner.py -> run_job): một lần PortfolioEngine cho sổ chiến lược.

Tham số (run_job params; mặc định ở DEFAULTS):
  book        đường dẫn book.json (mặc định data/alphas/book.json) — chiến lược + tham số + rủi ro/lệnh + giới hạn danh mục của sổ đã chốt
  strategies  [{"id": "trend_long", "params": {...}}] thay cho book; tham số thiếu lấy mức GIỮA của không gian tham số ứng viên
  start, end  YYYY-MM-DD UTC (ngày kết thúc tính CẢ ngày); mặc định = toàn bộ dữ liệu sau warmup
  risk_per_trade  % vốn rủi ro mỗi lệnh (mặc định: của sổ, hoặc mức chuẩn 0,5%); stop_fill level|extreme (mặc định level)
  out         (tuỳ chọn) ghi kết quả JSON ra đường dẫn này
Kết quả: số đo danh mục (portfolio_metrics) + by_symbol/by_strategy + lệnh + đường vốn (<= 2000 điểm) -> $NORA_JOB_DIR/result.json.
"""
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")

import contextlib
import io
import json
import time
import warnings
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import pandas as pd

from backend.core.metrics.portfolio import portfolio_metrics
from backend.utils.jobs import as_list, options, write_job_result
from backend.utils.jsonsafe import json_default

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULTS = {"book": "", "strategies": None, "symbols": "", "start": "", "end": "", "risk_per_trade": None, "stop_fill": "level", "regime": False, "timeframe": "1m", "out": ""}

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
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, CANDIDATES, RISK
    by_id = {c["id"]: c for c in CANDIDATES}
    if a.strategies:
        raw = a.strategies
        if not isinstance(raw, list) or not raw:
            raise SystemExit("strategies phải là danh sách không rỗng")
        items = []
        for s in raw:
            if s.get("id") not in by_id:
                raise SystemExit(f"Không có chiến lược: {s.get('id')}; có: {sorted(by_id)}")
            items.append((s["id"], _mid_params(by_id[s["id"]], s.get("params"))))
        return items, BASE_RISK_PER_TRADE_PCT, RISK
    path = a.book or os.path.join(NORA_ROOT, "data", "alphas", "book.json")
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


class BacktestJob(NamedTuple):
    """Đặc tả MỘT lần backtest danh mục — dùng chung cho dựng sổ (optimize/book), WFA (wfa/walk_forward) và phễu (optimize/funnel).
    items: [(id chiến lược lõi, tham số)]; window: (start, end) ms — chỉ số đo từ start, nạp thêm WARMUP trước đó; symbols None = vũ trụ
    perp của sổ; shared_dir None = env NORA_SHARED_DATA_DIR (core/data/shared); base_frame = khung chạy (nến mô phỏng)."""
    items: List[Tuple[str, Dict[str, Any]]]
    window: Tuple[int, int]
    stop_fill: str
    risk: Dict[str, Any]
    rpt: float
    symbols: Optional[List[str]] = None
    shared_dir: Optional[str] = None
    base_frame: str = "1m"
    regime: Optional[Dict[str, Any]] = None   # {id chiến lược: cấu hình regime} (core/regime/learn.py); thiếu id -> không lọc


def make_engine(job: BacktestJob):
    """PortfolioEngine của job (chưa nạp dữ liệu) + mốc bắt đầu đo. Khung tín hiệu nhỏ hơn khung chạy được nâng lên (params.modes.lift_frames)."""
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import CANDIDATES, materialize, perp_symbols
    by_id = {c["id"]: c for c in CANDIDATES}
    regime = job.regime or {}
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, job.base_frame), regime=regime.get(cid) or False,
                              stop_fill=job.stop_fill, risk_per_trade_pct=job.rpt) for cid, prm in job.items]
    start, end = job.window
    return PortfolioEngine(list(job.symbols or perp_symbols()), strategies, start - WARMUP, end, trade_start_ts=start,
                           risk=RiskConfig.from_dict(job.risk), shared_dir=job.shared_dir, base_frame=job.base_frame), start


def run(items, symbols, start, end, rpt, stop_fill, risk, extra_strategies=None, initial_capital=None, close_at_end=True,
        warmup=WARMUP, regime=False, base_frame="1m"):
    """extra_strategies: chiến lược dựng sẵn (dict của PortfolioEngine, có thể có khoá "symbols") chạy cùng sổ — dùng cho feed
    giả lập. close_at_end=False: giữ vị thế còn mở cuối dữ liệu (kết quả thêm `open_positions`); mặc định như backtest thường."""
    from backend.core.strategy.book import CANDIDATES, materialize
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    from backend.utils.memwatch import peak_rss_mb
    by_id = {c["id"]: c for c in CANDIDATES}
    from backend.core.params.modes import lift_frames
    strategies = [materialize(by_id[cid], lift_frames(by_id[cid], prm, base_frame), regime=regime, stop_fill=stop_fill,
                              risk_per_trade_pct=rpt) for cid, prm in items]
    strategies += list(extra_strategies or [])
    t0 = time.time()
    kw = {} if initial_capital is None else {"initial_capital": float(initial_capital)}
    eng = PortfolioEngine(symbols, strategies, start - warmup, end, trade_start_ts=start, risk=RiskConfig.from_dict(risk),
                          close_at_end=close_at_end, base_frame=base_frame, **kw)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    res = eng.get_results()
    out = portfolio_metrics(res, start)
    out["risk_blocked_attempts"] = res["risk_blocked_attempts"]   # số lần vào lệnh bị chặn (rejected_for_risk đếm phút)
    out["trade_list"] = [{
        "symbol": p.symbol, "strategy": p.strategy_id, "side": p.pos_type.name,
        "enter_time": p.enter_time, "enter_price": p.enter_price, "close_time": p.close_time, "close_price": p.close_price,
        "pnl": round(p.real_pnl, 4), "status": p.status.name, "close_reason": p.close_reason,
        # khối lượng + danh nghĩa (qty × giá vào trung bình sau DCA) + ký quỹ: để tính exposure/trọng số ở dashboard
        "qty": round(p.qty, 8), "notional": round(p.qty * (p.avg_price or p.enter_price), 2),
        "margin_usd": round(p.total_margin_usd or 0.0, 2),
        # thêm cho bảng lệnh + số đo theo chiến lược (core/metrics/trades.rows_from_trade_list)
        "avg_price": round(p.avg_price or p.enter_price, 8), "pnl_pct": round(p.profit_pct, 4), "fees_usd": round(p.fees_usd or 0.0, 4),
        "funding_usd": round(p.funding_usd or 0.0, 4), "layers": int(p.layers or 0), "mae_pct": round(p.mae_pct or 0.0, 4),
        "leverage": float(p.leverage_used or 1.0), "entry_equity": round(p.entry_equity or 0.0, 2),
    } for p in res["positions"]]
    curve = [{"time": c["time"], "equity": round(c["equity"], 2), "equity_worst": round(c["equity_worst"], 2)}
             for c in res["equity_curve"] if c["time"] >= start]
    out["equity_curve"] = downsample(curve)
    out["daily_nav"] = daily_nav(curve, end)
    out["config"] = {"strategies": [{"id": i, "params": p} for i, p in items]
                     + [{"id": x["id"], "params": x["position"]} for x in extra_strategies or []], "symbols": symbols, "risk_per_trade_pct": rpt,
                     "stop_fill": stop_fill, "risk": res["risk"], "start": start, "end": end,
                     "initial_capital": res["initial_capital"]}
    if regime:
        out["config"]["regime"] = True
    if base_frame != "1m":
        out["config"]["timeframe"] = base_frame
    out["final_equity"] = round(res["final_equity"], 2)
    if not close_at_end:
        out["open_positions"] = eng.open_positions()
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}  # không tất định -> tách riêng
    return out


def run_job(params=None):
    """Chạy job backtest với `params` (xem docstring module) -> dict kết quả (cũng ghi $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    if a.stop_fill not in ("level", "extreme"):
        raise ValueError("stop_fill phải là level|extreme")
    if a.book and a.strategies:
        raise ValueError("chọn một: book hoặc strategies")
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("run_book_backtest")
    from backend.core.strategy.book import perp_symbols

    symbols = [s if "@" in s else f"{s}@perp" for s in as_list(a.symbols)] or perp_symbols()
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit(symbols)   # cổng chất lượng dữ liệu bắt buộc (synthetic / sai sha256 / thiếu dữ liệu -> từ chối)
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
        raise SystemExit("end phải sau start")
    print(f"sổ {[i for i, _ in items]} | {len(symbols)} tài sản | {pd.Timestamp(start, unit='ms'):%Y-%m-%d} → "
          f"{pd.Timestamp(end, unit='ms'):%Y-%m-%d} | rủi ro/lệnh {rpt}% | SL {a.stop_fill}", flush=True)
    out = run(items, symbols, start, end, rpt, a.stop_fill, risk, regime=bool(a.regime), base_frame=a.timeframe or "1m")
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
