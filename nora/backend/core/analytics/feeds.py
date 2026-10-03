"""Nguồn dữ liệu (feed) cho trang Danh mục (docs/ui_contract.md §3).

Dashboard (`dashboard.build_dashboard`) chỉ cần một dict dạng kết quả `book_backtest`:
  equity_curve / daily_nav (vốn MTM), trade_list (qty, notional, margin_usd), config (initial_capital, strategies, symbols, start, end, risk),
  by_strategy, halted_at, rejected_for_risk, và (tuỳ chọn) `positions` = vị thế đang mở.
Mỗi feed trả `FeedSnapshot` gói dict đó cùng mô tả nguồn:
  BacktestFeed   — bọc kết quả một job book_backtest đã xong (vị thế cuối kỳ đã bị engine đóng nên `positions` rỗng).
  MockFeed       — đọc file giả lập do job `mock_feeds` (POST /api/studio/portfolio/mock-feeds, run_job cuối file này) ghi ở
                   data/_cache/mock_feeds/<kind>.json: engine thật trên dữ liệu MỚI NHẤT, tất định; vị thế còn mở cuối dữ liệu KHÔNG bị đóng ép.
  LiveFeed / TestnetFeed — CHƯA có tài khoản: luôn NotAvailable. Khi nối Binance (lịch sử lệnh + số dư + vị thế) chỉ cần cài `fetch()`
                   trả đúng dạng FeedSnapshot; router và UI không đổi.
`get_snapshot(kind)` = feed thật nếu có, không thì rơi về MockFeed (snapshot.mock = True, kèm mock_note); thiếu file giả lập -> NotAvailable.
"""
import json
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, Optional

from backend.db.data_layout import cache_dir

KINDS = ("live", "testnet", "backtest")
MOCK_KINDS = ("live", "testnet")
KIND_VI = {"live": "Live", "testnet": "Testnet", "backtest": "Backtest"}
MAKE_MOCK_CMD = "POST /api/studio/portfolio/mock-feeds"


class NotAvailable(Exception):
    """Feed chưa dùng được; str(e) là lý do hiển thị cho người dùng."""


@dataclass
class FeedSnapshot:
    kind: str
    result: Dict[str, Any]                      # dict dạng kết quả book_backtest (+ `positions`)
    source: Dict[str, Any] = field(default_factory=dict)   # ghi đè/bổ sung payload["source"] (job_id, label, ...)
    mock: bool = False
    mock_note: Optional[str] = None


class Feed:
    kind = ""

    def fetch(self) -> FeedSnapshot:
        raise NotImplementedError


class BacktestFeed(Feed):
    kind = "backtest"

    def __init__(self, result: Dict[str, Any], job_id: Optional[str] = None, label: Optional[str] = None):
        self.result, self.job_id, self.label = result, job_id, label

    def fetch(self) -> FeedSnapshot:
        return FeedSnapshot("backtest", self.result, {"job_id": self.job_id, "label": self.label})


class _NoAccountFeed(Feed):
    def fetch(self) -> FeedSnapshot:
        raise NotAvailable(f"Chưa kết nối tài khoản {KIND_VI[self.kind]}.")


class LiveFeed(_NoAccountFeed):
    kind = "live"          # TODO: lịch sử lệnh + số dư + vị thế từ tài khoản Binance Futures thật


class TestnetFeed(_NoAccountFeed):
    __test__ = False       # tên bắt đầu bằng "Test": pytest đừng thu thập
    kind = "testnet"       # TODO: như LiveFeed nhưng trên testnet.binancefuture.com


def mock_path(kind: str) -> str:
    return os.path.join(cache_dir(None, "mock_feeds"), f"{kind}.json")


def mock_note(kind: str) -> str:
    return f"Dữ liệu giả lập — chưa kết nối tài khoản {KIND_VI[kind]}"


class MockFeed(Feed):
    """Đọc file giả lập; kết quả có mock=True để UI báo rõ đây không phải số liệu thật."""

    def __init__(self, kind: str):
        if kind not in MOCK_KINDS:
            raise ValueError(f"MockFeed chỉ có cho {MOCK_KINDS}")
        self.kind = kind

    def mtime(self) -> Optional[float]:
        p = mock_path(self.kind)
        return os.path.getmtime(p) if os.path.isfile(p) else None

    def fetch(self) -> FeedSnapshot:
        p = mock_path(self.kind)
        if not os.path.isfile(p):
            raise NotAvailable(f"Chưa có dữ liệu giả lập cho {KIND_VI[self.kind]} — chạy `{MAKE_MOCK_CMD}` để tạo.")
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            raise NotAvailable(f"File giả lập {KIND_VI[self.kind]} hỏng ({e}) — chạy lại `{MAKE_MOCK_CMD}`.")
        return FeedSnapshot(self.kind, data, {"label": data.get("source_desc"), "mock": True}, mock=True, mock_note=mock_note(self.kind))


def real_feed(kind: str) -> Feed:
    return {"live": LiveFeed, "testnet": TestnetFeed}[kind]()


def get_snapshot(kind: str) -> FeedSnapshot:
    """Live/Testnet: feed thật nếu kết nối được, nếu không dùng giả lập. Raise NotAvailable(lý do) khi cả hai đều không có."""
    if kind not in MOCK_KINDS:
        raise ValueError(f"nguồn không hỗ trợ: {kind}")
    try:
        return real_feed(kind).fetch()
    except NotAvailable:
        return MockFeed(kind).fetch()


# ─── Sinh feed giả lập (job mock_feeds) ─────────────────────────────────────
# testnet: sổ đã chốt (data/alphas/book.json) trên cả 8 perp, 60 ngày cuối, vốn 10.000 USDT.
# live:    alpha trend_long_perp__SOL (registry.json; chỉ chạy trên SOL, order_size_pct nhân hệ số vốn "extreme" tối đa của
#          portfolio_trend_long_perp__SOL__SOL.json nếu có) + các chiến lược của sổ, 120 ngày cuối, vốn 25.000 USDT.
DAY = 86_400_000
WARMUP_DAYS = 60            # nến khởi động chỉ báo (EMA200 4h cần ~33 ngày); không nằm trong kỳ báo cáo
ALPHA_ID = "trend_long_perp__SOL"
PLANS = {
    "testnet": {"days": 60, "capital": 10_000.0, "alpha": False},
    "live": {"days": 120, "capital": 25_000.0, "alpha": True},
}


def alphas_dir():
    return os.environ.get("NORA_ALPHAS_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "alphas")


def alpha_strategy(alpha_id=ALPHA_ID, base=None):
    """Alpha trong kho -> chiến lược PortfolioEngine chỉ chạy trên tài sản của nó; order_size_pct nhân hệ số vốn tối đa (extreme) nếu có file."""
    base = base or alphas_dir()
    with open(os.path.join(base, "registry.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next((a for a in reg["alphas"] if a.get("alpha_id") == alpha_id), None)
    if al is None:
        raise SystemExit(f"Không có alpha {alpha_id} trong registry.json")
    if al.get("status") == "retired":   # kiểm lại bằng engine hiện hành đã loại (optimize/revalidate.py) -> không chạy nữa
        return None, None
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
    from backend.core.backtest import run as rbb
    from backend.core.strategy.book import perp_symbols
    plan = plan or PLANS[kind]
    symbols = symbols or perp_symbols()
    items, rpt, risk = rbb.load_items(book_args or SimpleNamespace(strategies="", book=""))
    end = int(end_ms if end_ms is not None else data_end(symbols))
    start = (end // DAY) * DAY - (plan["days"] - 1) * DAY       # `days` ngày UTC, gồm cả ngày cuối (còn dở)
    extra, scale = ([], None)
    if plan["alpha"]:
        st, scale = alpha_strategy()
        extra = [st] if st else []
    out = rbb.run(items, symbols, start, end, rpt, "level", risk, extra_strategies=extra, initial_capital=plan["capital"],
                  close_at_end=False, warmup=WARMUP_DAYS * DAY)
    feed = {k: v for k, v in out.items() if k not in ("daily", "meta", "open_positions")}
    feed["positions"] = out["open_positions"]
    feed["kind"] = kind
    ids = [i for i, _ in items] + [x["id"] for x in extra]
    import pandas as pd
    feed["source_desc"] = (f"Giả lập {pd.Timestamp(start, unit='ms'):%d/%m}–{pd.Timestamp(end - 1, unit='ms'):%d/%m/%Y} · "
                           f"{len(ids)} chiến thuật · {len(symbols)} tài sản · vốn {plan['capital']:,.0f} USDT")
    feed["mock"] = True
    feed["alpha_scale"] = scale
    return feed


def summarize(kind, feed):
    import pandas as pd
    cfg = feed["config"]
    d = lambda ms: f"{pd.Timestamp(ms, unit='ms'):%Y-%m-%d}"
    return (f"{kind}: {d(cfg['start'])} → {d(cfg['end'] - 1)} | vốn {cfg['initial_capital']:,.0f} → {feed['final_equity']:,.2f} | "
            f"lệnh đã đóng {feed['trades']} | lãi {feed['ret_pct']}% | MDD {feed['mdd_pct']}% | sharpe {feed['sharpe']} | "
            f"vị thế mở {len(feed['positions'])} | kill={'có' if feed['halted_at'] else 'không'}")


def run_job(params=None):
    """Job `mock_feeds`: chạy engine thật trên dữ liệu MỚI NHẤT (tất định) rồi ghi data/_cache/mock_feeds/{live,testnet}.json.
    params: {"only": "live" | "testnet" | ""} (mặc định cả hai)."""
    import time
    import warnings
    from backend.utils.jobs import options, write_job_result
    from backend.utils.jsonsafe import json_default
    from backend.utils.memwatch import require_memory_limit
    from backend.core.data.quality_gate import require_data_ok_or_exit
    from backend.core.strategy.book import perp_symbols
    warnings.filterwarnings("ignore")
    a = options({"only": ""}, params)
    if a.only and a.only not in PLANS:
        raise ValueError(f"only phải là một trong {sorted(PLANS)}")
    require_memory_limit("mock_feeds")
    require_data_ok_or_exit(perp_symbols())   # cổng chất lượng dữ liệu bắt buộc
    done = {}
    for kind in ([a.only] if a.only else list(PLANS)):
        t0 = time.time()
        feed = make_feed(kind)
        feed["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = mock_path(kind)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(feed, fh, ensure_ascii=False, indent=1, default=json_default)
        os.replace(tmp, path)
        print(summarize(kind, feed), f"| {time.time() - t0:.0f}s\n  ghi: {path}", flush=True)
        done[kind] = path
    write_job_result({"written": done})
    return done
