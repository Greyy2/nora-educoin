"""Nguồn dữ liệu (feed) cho trang Danh mục (docs/ui_contract.md §3).

Dashboard (`portfolio_dashboard.build_dashboard`) chỉ cần một dict dạng kết quả `book_backtest`:
  equity_curve / daily_nav (vốn MTM), trade_list (qty, notional, margin_usd), config (initial_capital, strategies, symbols, start, end, risk),
  by_strategy, halted_at, rejected_for_risk, và (tuỳ chọn) `positions` = vị thế đang mở.
Mỗi feed trả `FeedSnapshot` gói dict đó cùng mô tả nguồn:
  BacktestFeed   — bọc kết quả một job book_backtest đã xong (vị thế cuối kỳ đã bị engine đóng nên `positions` rỗng).
  MockFeed       — đọc file giả lập do `python -m backend.core.analytics.make_mock_feeds` ghi ở data/_cache/mock_feeds/<kind>.json.
  LiveFeed / TestnetFeed — CHƯA có tài khoản: luôn NotAvailable. Khi nối Binance (lịch sử lệnh + số dư + vị thế) chỉ cần cài `fetch()`
                   trả đúng dạng FeedSnapshot; router và UI không đổi.
`get_snapshot(kind)` = feed thật nếu có, không thì rơi về MockFeed (snapshot.mock = True, kèm mock_note); thiếu file giả lập -> NotAvailable.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from backend.db.data_layout import cache_dir

KINDS = ("live", "testnet", "backtest")
MOCK_KINDS = ("live", "testnet")
KIND_VI = {"live": "Live", "testnet": "Testnet", "backtest": "Backtest"}
MAKE_MOCK_CMD = "python -m backend.core.analytics.make_mock_feeds"


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
