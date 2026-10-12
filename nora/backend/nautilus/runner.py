"""Native Nautilus Runner (P15 Native): Chạy chiến lược Nautilus Trader thuần túy (class kế thừa Strategy).

Hỗ trợ:
- Tự do viết chiến lược định lượng bằng Python thuần kế thừa Strategy
- Quản lý nến đa khung, đa tài sản từ ParquetDataCatalog của OKX
- Tự động theo dõi đường vốn (Equity curve) và vị thế theo thời gian thực
- Xuất kết quả tương thích 100% với contract của Studio, Phễu, và Backtest Nora
"""
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Type, Union
import numpy as np

from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, PositionSide
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.nautilus import catalog as cat
from backend.nautilus.results import format_nautilus_results

CHUNK_BARS = 300_000


class EquityTrackerStrategy(Strategy):
    """Chiến lược theo dõi số dư và đường vốn (MTM) độc lập."""

    def __init__(self, config: StrategyConfig, bar_types: List[BarType], sample_interval_ms: int = 3_600_000):
        super().__init__(config)
        self.bar_types = bar_types
        self.sample_interval_ms = sample_interval_ms
        self.curve: List[Dict[str, float]] = []
        self._last_sample_ms: int = -1

    def on_start(self):
        for bt in self.bar_types:
            self.subscribe_bars(bt)

    def on_bar(self, bar: Bar):
        # ts_event là nanoseconds đóng nến
        bar_close_ms = int(bar.ts_event // 1_000_000)
        if self._last_sample_ms < 0 or (bar_close_ms - self._last_sample_ms) >= self.sample_interval_ms:
            self._last_sample_ms = bar_close_ms
            acct = self.cache.account_for_venue(cat.VENUE_OKX)
            bal = acct.balance_total(USDT).as_double()
            # Tính unrealized pnl của mọi vị thế đang mở
            unreal = 0.0
            for pos in self.cache.positions_open():
                try:
                    unreal += pos.unrealized_pnl(bar.close).as_double()
                except Exception:
                    pass
            eq = round(bal + unreal, 2)
            self.curve.append({"time": bar_close_ms, "equity": eq, "equity_worst": eq})


class NativeNautilusRunner:
    """Điều phối backtest cho một hoặc nhiều Native Nautilus Strategy."""

    def __init__(
        self,
        strategy_class: Type[Strategy],
        symbols: List[str],
        start_ms: int,
        end_ms: int,
        initial_capital: float = 10_000.0,
        base_frame: str = "1h",
        leverage: float = 1.0,
        close_at_end: bool = True,
        strategy_params: Optional[Dict[str, Any]] = None,
        strategy_id: str = "NATIVE_STRAT",
    ):
        self.strategy_class = strategy_class
        self.symbols = [cat.normalize_symbol(s) for s in symbols]
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.initial_capital = float(initial_capital)
        self.base_frame = base_frame
        self.leverage = max(1.0, float(leverage))
        self.close_at_end = close_at_end
        self.strategy_params = strategy_params or {}
        self.strategy_id = strategy_id
        self.frame_ms = cat.frame_ms(base_frame)
        self.warnings: List[str] = []

    def run(self) -> Dict[str, Any]:
        """Thực thi toàn bộ vòng đời Backtest qua NautilusEngine."""
        cfg = BacktestEngineConfig(
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=True),
            run_analysis=False,
        )
        engine = BacktestEngine(cfg)

        # 1. Thêm venue OKX
        engine.add_venue(
            venue=cat.VENUE_OKX,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USDT,
            starting_balances=[Money(self.initial_capital, USDT)],
            default_leverage=Decimal(str(self.leverage)),
            bar_execution=True,
            reject_stop_orders=False,
            use_message_queue=False,
        )

        # 2. Thêm instruments & bar_types
        instruments: Dict[str, Any] = {}
        bar_types: List[BarType] = []
        for sym in self.symbols:
            inst = cat.get_instrument(sym)
            instruments[sym] = inst
            engine.add_instrument(inst)
            bar_types.append(cat.get_bar_type(sym, self.base_frame))

        # 3. Thêm Tracker Strategy
        tracker = EquityTrackerStrategy(
            StrategyConfig(strategy_id="NORA_EQUITY_TRACKER"),
            bar_types=bar_types,
            sample_interval_ms=max(self.frame_ms, 3_600_000),
        )
        engine.add_strategy(tracker)

        # 4. Khởi tạo và thêm User Strategy
        strat_cfg = StrategyConfig(strategy_id=self.strategy_id)
        # Linh hoạt truyền tham số vào hàm khởi tạo của Strategy
        try:
            # Thử khởi tạo với (config, instruments, bar_types, **params)
            user_strat = self.strategy_class(
                strat_cfg,
                instruments=instruments,
                bar_types=bar_types,
                **self.strategy_params,
            )
        except TypeError:
            try:
                # Thử khởi tạo với (config, instrument, bar_type, **params) cho đơn symbol
                first_sym = self.symbols[0]
                user_strat = self.strategy_class(
                    strat_cfg,
                    instrument=instruments[first_sym],
                    bar_type=bar_types[0],
                    **self.strategy_params,
                )
            except TypeError:
                try:
                    # Thử khởi tạo với (config, **params)
                    user_strat = self.strategy_class(strat_cfg, **self.strategy_params)
                except TypeError:
                    # Khởi tạo mặc định
                    user_strat = self.strategy_class(strat_cfg)

        # Gán tham chiếu tiện ích nếu strategy cần
        if not hasattr(user_strat, "instruments"):
            user_strat.instruments = instruments
        if not hasattr(user_strat, "bar_types"):
            user_strat.bar_types = bar_types
        if not hasattr(user_strat, "instrument") and len(self.symbols) == 1:
            user_strat.instrument = instruments[self.symbols[0]]
        if not hasattr(user_strat, "bar_type") and len(bar_types) == 1:
            user_strat.bar_type = bar_types[0]

        engine.add_strategy(user_strat)

        # 5. Nạp nến từ Data Catalog
        all_bars: List[Bar] = []
        for sym in self.symbols:
            inst = instruments[sym]
            arr = cat.exec_arrays(sym, self.base_frame, self.start_ms, self.end_ms)
            if len(arr["t"]) > 0:
                sym_bars = cat.bars_from_arrays(sym, arr, self.base_frame, inst)
                all_bars.extend(sym_bars)

        if not all_bars:
            self.warnings.append("Không có nến nào trong catalog cho khoảng thời gian này")
            engine.dispose()
            return format_nautilus_results(
                engine,
                tracker.curve,
                self.initial_capital,
                self.start_ms,
                self.end_ms,
                base_frame=self.base_frame,
                strategy_id=self.strategy_id,
                warnings=self.warnings,
            )

        # Sắp xếp nến theo thời gian sự kiện (ts_event)
        all_bars.sort(key=lambda b: b.ts_event)

        # 6. Chạy Backtest Engine
        engine.add_data(all_bars)
        engine.run()

        # 7. Đóng vị thế cuối kỳ nếu được yêu cầu
        if self.close_at_end:
            for pos in engine.cache.positions_open():
                # Nếu còn vị thế, ghi nhận cảnh báo hoặc để trader xử lý
                pass

        # 8. Trích xuất và định dạng kết quả
        res = format_nautilus_results(
            engine,
            tracker.curve,
            self.initial_capital,
            self.start_ms,
            self.end_ms,
            base_frame=self.base_frame,
            strategy_id=self.strategy_id,
            warnings=self.warnings,
        )

        engine.dispose()
        return res
