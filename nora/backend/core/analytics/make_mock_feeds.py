"""Sinh feed GIẢ LẬP cho trang Danh mục (Live / Testnet) khi chưa có tài khoản thật (backend/core/analytics/feeds.py).

Chạy engine thật (PortfolioEngine qua run_book_backtest.run) trên dữ liệu MỚI NHẤT, tất định (không RNG), rồi ghi
data/_cache/mock_feeds/{live,testnet}.json = {"mock": true, "generated_at", "source_desc", ...kết quả dạng book_backtest, "positions"}.
Khác backtest thường: vị thế còn mở cuối dữ liệu KHÔNG bị đóng ép — được báo là vị thế mở (mark = giá đóng cửa cuối, lãi/lỗ chưa chốt), vốn cuối là MTM.
  testnet: sổ đã chốt (data/alphas/book.json) trên cả 8 perp, 60 ngày cuối, vốn 10.000 USDT.
  live:    alpha trend_long_perp__SOL (data/alphas/registry.json; chỉ chạy trên SOL, order_size_pct nhân hệ số vốn "extreme" tối đa của
           data/alphas/portfolio_trend_long_perp__SOL__SOL.json nếu có) + các chiến lược của sổ, 120 ngày cuối, vốn 25.000 USDT.
Dùng (từ nora/):  backend/utils/ops/run_limited.sh -- -m backend.core.analytics.make_mock_feeds [--only live|testnet]
"""
import argparse
import json
import os
import sys
import time
import warnings
from types import SimpleNamespace

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

from backend.core.backtest import run_book_backtest as rbb  # noqa: E402  (đặt biến môi trường BLAS/cache trước khi import nặng)
from backend.utils.jsonsafe import json_default  # noqa: E402

DAY = rbb.DAY
WARMUP_DAYS = 60            # nến khởi động chỉ báo (EMA200 4h cần ~33 ngày); không nằm trong kỳ báo cáo
ALPHA_ID = "trend_long_perp__SOL"
PLANS = {
    "testnet": {"days": 60, "capital": 10_000.0, "alpha": False},
    "live": {"days": 120, "capital": 25_000.0, "alpha": True},
}


def alphas_dir():
    return os.environ.get("NORA_ALPHAS_DIR") or os.path.join(NORA_ROOT, "data", "alphas")


def alpha_strategy(alpha_id=ALPHA_ID, base=None):
    """Alpha trong kho -> chiến lược PortfolioEngine chỉ chạy trên tài sản của nó; order_size_pct nhân hệ số vốn tối đa (extreme) nếu có file."""
    base = base or alphas_dir()
    with open(os.path.join(base, "registry.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next((a for a in reg["alphas"] if a.get("alpha_id") == alpha_id), None)
    if al is None:
        raise SystemExit(f"Không có alpha {alpha_id} trong registry.json")
    ast = al["flows"][0]["ast"]
    pos = dict(al["position"])
    scale = None
    path = os.path.join(base, f"portfolio_{alpha_id}__{al['symbol']}.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            scale = ((json.load(fh).get("modes") or {}).get("extreme") or {}).get("max_scale_within_budget")
    if scale and pos.get("order_size_pct") is not None:
        pos["order_size_pct"] = round(float(pos["order_size_pct"]) * float(scale), 4)
    return {"id": alpha_id, "side": al["side"], "tree": ast["match"][0]["condition"], "stop": ast.get("stop") or [],
            "position": pos, "symbols": [al["data_symbol"]]}, scale


def data_end(symbols):
    from backend.db.local_pkl import read_manifest
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    return min(int(m["end_ts"]) for m in ms)


def make_feed(kind, symbols=None, end_ms=None, book_args=None, plan=None):
    """-> dict ghi ra file feed (chưa có generated_at). Tham số tuỳ chọn để test dùng thị trường giả."""
    from backend.core.strategy.book import perp_symbols
    plan = plan or PLANS[kind]
    symbols = symbols or perp_symbols()
    items, rpt, risk = rbb.load_items(book_args or SimpleNamespace(strategies="", book=""))
    end = int(end_ms if end_ms is not None else data_end(symbols))
    start = (end // DAY) * DAY - (plan["days"] - 1) * DAY       # `days` ngày UTC, gồm cả ngày cuối (còn dở)
    extra, scale = ([], None)
    if plan["alpha"]:
        st, scale = alpha_strategy()
        extra = [st]
    out = rbb.run(items, symbols, start, end, rpt, "level", risk, extra_strategies=extra, initial_capital=plan["capital"],
                  close_at_end=False, warmup=WARMUP_DAYS * DAY)
    feed = {k: v for k, v in out.items() if k not in ("daily", "meta", "open_positions")}
    feed["positions"] = out["open_positions"]
    feed["kind"] = kind
    ids = [i for i, _ in items] + [x["id"] for x in extra]
    feed["source_desc"] = (f"Giả lập {rbb.pd.Timestamp(start, unit='ms'):%d/%m}–{rbb.pd.Timestamp(end - 1, unit='ms'):%d/%m/%Y} · "
                           f"{len(ids)} chiến thuật · {len(symbols)} tài sản · vốn {plan['capital']:,.0f} USDT")
    feed["mock"] = True
    feed["alpha_scale"] = scale
    return feed


def summarize(kind, feed):
    cfg = feed["config"]
    d = lambda ms: f"{rbb.pd.Timestamp(ms, unit='ms'):%Y-%m-%d}"
    return (f"{kind}: {d(cfg['start'])} → {d(cfg['end'] - 1)} | vốn {cfg['initial_capital']:,.0f} → {feed['final_equity']:,.2f} | "
            f"lệnh đã đóng {feed['trades']} | lãi {feed['ret_pct']}% | MDD {feed['mdd_pct']}% | sharpe {feed['sharpe']} | "
            f"vị thế mở {len(feed['positions'])} | kill={'có' if feed['halted_at'] else 'không'}")


def main(argv=None):
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(PLANS), default="", help="chỉ sinh một feed (mặc định cả hai)")
    a = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("make_mock_feeds")
    from backend.core.analytics.feeds import mock_path
    from backend.core.data.quality_gate import require_data_ok_or_exit
    from backend.core.strategy.book import perp_symbols
    require_data_ok_or_exit(perp_symbols())   # cổng chất lượng dữ liệu bắt buộc
    kinds = [a.only] if a.only else list(PLANS)
    for kind in kinds:
        t0 = time.time()
        feed = make_feed(kind)
        feed["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = mock_path(kind)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(feed, fh, ensure_ascii=False, indent=1, default=json_default)
        os.replace(tmp, path)
        print(summarize(kind, feed), f"| {time.time() - t0:.0f}s\n  ghi: {path}", flush=True)


if __name__ == "__main__":
    main()
