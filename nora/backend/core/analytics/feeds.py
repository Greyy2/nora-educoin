"""Nguồn dữ liệu cho trang Danh mục (docs/ui_contract.md §3) — CHỈ backtest.

Dashboard (`dashboard.build_dashboard`) chỉ cần một dict dạng kết quả `book_backtest`:
  equity_curve / daily_nav (vốn MTM), trade_list (qty, notional, margin_usd), config (initial_capital, strategies, symbols, start, end, risk),
  by_strategy, halted_at, rejected_for_risk.
`BacktestFeed` bọc kết quả một job book_backtest đã xong thành `FeedSnapshot`. Dữ liệu bot live (OKX paper/demo) nằm ở trang Live
(api/routers/live.py), không đi qua đây.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FeedSnapshot:
    kind: str
    result: Dict[str, Any]                      # dict dạng kết quả book_backtest
    source: Dict[str, Any] = field(default_factory=dict)   # bổ sung payload["source"] (job_id, label)


class BacktestFeed:
    kind = "backtest"

    def __init__(self, result: Dict[str, Any], job_id: Optional[str] = None, label: Optional[str] = None):
        self.result, self.job_id, self.label = result, job_id, label

    def fetch(self) -> FeedSnapshot:
        return FeedSnapshot("backtest", self.result, {"job_id": self.job_id, "label": self.label})
