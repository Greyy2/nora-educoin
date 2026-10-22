"""Phân hệ Adapter (backend/adapter): Kiến trúc 3-File Độc Lập cho Vận Hành Live & Paper Trading.

Phân tách trách nhiệm chuẩn mực 3 file:
1. backend/adapter/readings.py: Market Ingestion, Resampling nến 1h, Data Integrity, đa tài sản Coin/CFD/CFS & Bối cảnh Regime tham khảo nhẹ.
2. backend/adapter/execution.py: Order Management System (OMS), Sizing 3 cận, 6 bước thoát lệnh Proxima & Universal Specs Catalog đa tài sản.
3. backend/adapter/runner.py: Bộ điều phối vòng lặp nến 1m, Broker Routing, 3 Lớp Bảo Vệ, Persistence Nora & Kiến trúc 2 Worker qua RedisBus.

(File backend/adapter/exchange.py phục vụ tương thích ngược với Nautilus TradingNode và các bot hiện hành của Nora).
"""

from backend.adapter import exchange
from backend.adapter.readings import MarketDataReader, MarketBar, MarketReading
from backend.adapter.execution import (
    BotLifecycleState,
    ExitReason,
    InstrumentSpec,
    OrderAction,
    OrderStatus,
    PendingOrder,
    PositionState,
    ProtectiveStatus,
    SPEC_CATALOG,
    TradeCycleResult,
    UniversalExecutionModel,
    generate_client_order_id,
    determine_execution_td_mode,
    get_universal_spec,
    sync_okx_specs,
)
from backend.adapter.runner import (
    AdapterRunner,
    ExecutionWorker,
    MarketListenerWorker,
    RedisBus,
    create_decoupled_proxima_bot,
    run_decoupled_proxima_live,
)

__all__ = [
    "exchange",
    "MarketDataReader",
    "MarketBar",
    "MarketReading",
    "BotLifecycleState",
    "ExitReason",
    "InstrumentSpec",
    "OrderAction",
    "OrderStatus",
    "PendingOrder",
    "PositionState",
    "ProtectiveStatus",
    "TradeCycleResult",
    "UniversalExecutionModel",
    "SPEC_CATALOG",
    "generate_client_order_id",
    "determine_execution_td_mode",
    "get_universal_spec",
    "sync_okx_specs",
    "RedisBus",
    "AdapterRunner",
    "MarketListenerWorker",
    "ExecutionWorker",
    "create_decoupled_proxima_bot",
    "run_decoupled_proxima_live",
]
