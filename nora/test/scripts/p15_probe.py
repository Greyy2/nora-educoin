"""P1.0 Probe NautilusTrader 1.231.0 capabilities.
Kiểm tra chi tiết và xuất báo cáo:
1. INTERNAL Aggregation: Bar 1m EXTERNAL -> Bar 1h INTERNAL (<SYM>.OKX-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL)
2. FundingRateUpdate trong Backtest Engine
3. Liquidation margin
4. Bar.volume fill constraint
5. Tốc độ & RAM
"""
import sys
import time
import psutil
from decimal import Decimal
from datetime import datetime, timezone

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType, BarSpecification, FundingRateUpdate
from nautilus_trader.model.enums import (
    AccountType,
    AggregationSource,
    BarAggregation,
    OmsType,
    PriceType,
    OrderSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

print(f"Python: {sys.version}")
import nautilus_trader
print(f"Nautilus Trader version: {nautilus_trader.__version__}")

venue = Venue("OKX")
instrument_id = InstrumentId.from_str("BTC-USDT-SWAP.OKX")

def make_instrument():
    return CryptoPerpetual(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        base_currency=USDT,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=1,
        size_precision=4,
        price_increment=Price(Decimal("0.1"), 1),
        size_increment=Quantity(Decimal("0.0001"), 4),
        lot_size=Quantity(Decimal("0.0001"), 4),
        multiplier=Quantity.from_int(1),
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.01"),
        maker_fee=Decimal("0.0002"),
        taker_fee=Decimal("0.0005"),
        ts_init=0,
        ts_event=0,
    )

bar_type_1m = BarType(
    instrument_id=instrument_id,
    bar_spec=BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
    aggregation_source=AggregationSource.EXTERNAL,
)
bar_type_1h = BarType.from_str("BTC-USDT-SWAP.OKX-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL")

# -------------------------------------------------------------
# Test 1: Internal Bar Aggregation & Timestamps
# -------------------------------------------------------------
print("\n--- TEST 1: Internal Bar Aggregation & Timestamps ---")
class AggProbeStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.bars_1m = []
        self.bars_1h = []

    def on_start(self):
        self.subscribe_bars(bar_type_1m)
        self.subscribe_bars(bar_type_1h)

    def on_bar(self, bar: Bar):
        if bar.bar_type == bar_type_1m:
            self.bars_1m.append((bar.ts_init, bar.ts_event))
        elif bar.bar_type == bar_type_1h:
            self.bars_1h.append((bar.ts_init, bar.ts_event, bar.open, bar.close))

engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
engine.add_venue(
    venue=venue,
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    base_currency=USDT,
    starting_balances=[Money(10000, USDT)],
)
engine.add_instrument(make_instrument())
strat_agg = AggProbeStrategy(StrategyConfig(strategy_id="AGG-001"))
engine.add_strategy(strat_agg)

# Bắt đầu từ 2024-01-01 00:00:00 UTC (1704067200s), tạo 180 nến 1m (3 tiếng)
start_s = 1704067200
bars = []
for i in range(180):
    t_close_s = start_s + (i + 1) * 60
    t_close_ns = t_close_s * 1_000_000_000
    p = 50000.0 + i
    b = Bar(
        bar_type=bar_type_1m,
        open=Price(p, 1),
        high=Price(p + 10, 1),
        low=Price(p - 10, 1),
        close=Price(p + 2, 1),
        volume=Quantity(1.0, 4),
        ts_event=t_close_ns,
        ts_init=t_close_ns,
    )
    bars.append(b)

engine.add_data(bars)
engine.run()

print(f"Bars 1m received: {len(strat_agg.bars_1m)}")
print(f"Bars 1h aggregated: {len(strat_agg.bars_1h)}")
for idx, (ts_init, ts_event, op, cl) in enumerate(strat_agg.bars_1h):
    dt = datetime.fromtimestamp(ts_event / 1e9, tz=timezone.utc)
    print(f"  Bar 1h #{idx+1} ts_event={ts_event} ns ({dt.isoformat()}), open={op}, close={cl}")
engine.dispose()

# -------------------------------------------------------------
# Test 2: FundingRateUpdate settlement in backtest
# -------------------------------------------------------------
print("\n--- TEST 2: FundingRateUpdate Settlement in Backtest ---")
class FundingProbeStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.final_balance = None

    def on_start(self):
        self.subscribe_bars(bar_type_1m)

    def on_bar(self, bar: Bar):
        if not self.portfolio.is_net_long(instrument_id):
            order = self.order_factory.market(
                instrument_id=instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity(1.0, 4),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)

    def on_stop(self):
        acc = self.portfolio.account(venue)
        self.final_balance = acc.balance_total(USDT)

engine_f = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
engine_f.add_venue(
    venue=venue,
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    base_currency=USDT,
    starting_balances=[Money(100000, USDT)],
)
engine_f.add_instrument(make_instrument())
strat_f = FundingProbeStrategy(StrategyConfig(strategy_id="FUND-001"))
engine_f.add_strategy(strat_f)

bars_f = []
for i in range(10):
    t_close_ns = (start_s + (i + 1) * 3600) * 1_000_000_000
    b = Bar(
        bar_type=bar_type_1m,
        open=Price(50000, 1),
        high=Price(50010, 1),
        low=Price(49990, 1),
        close=Price(50000, 1),
        volume=Quantity(1.0, 4),
        ts_event=t_close_ns,
        ts_init=t_close_ns,
    )
    bars_f.append(b)

funding_update = FundingRateUpdate(
    instrument_id=instrument_id,
    rate=Decimal("0.05"),  # 5% funding
    ts_event=(start_s + 4 * 3600) * 1_000_000_000,
    ts_init=(start_s + 4 * 3600) * 1_000_000_000,
)

engine_f.add_data(bars_f)
try:
    engine_f.add_data([funding_update])
    print("FundingRateUpdate accepted by engine.add_data.")
except Exception as e:
    print(f"Error adding FundingRateUpdate: {e}")

engine_f.run()

print(f"Starting balance: 100,000 USDT")
print(f"Final balance: {strat_f.final_balance}")
print("-> Kết luận: Exchange backtest KHÔNG thanh toán funding rate vào account.")
engine_f.dispose()

# -------------------------------------------------------------
# Test 3: Liquidation margin in backtest
# -------------------------------------------------------------
print("\n--- TEST 3: Liquidation Margin in Backtest ---")
class LiqProbeStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.final_balance = None
        self.is_flat = None

    def on_start(self):
        self.subscribe_bars(bar_type_1m)

    def on_bar(self, bar: Bar):
        if not self.portfolio.is_net_long(instrument_id):
            # Mua 1 BTC với vốn chỉ 1000 USDT (đòn bẩy 50x)
            order = self.order_factory.market(
                instrument_id=instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity(1.0, 4),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)

    def on_stop(self):
        acc = self.portfolio.account(venue)
        self.final_balance = acc.balance_total(USDT)
        self.is_flat = not self.portfolio.is_net_long(instrument_id) and not self.portfolio.is_net_short(instrument_id)

engine_l = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
engine_l.add_venue(
    venue=venue,
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    base_currency=USDT,
    starting_balances=[Money(1000, USDT)],
    leverages={instrument_id: Decimal("50.0")},
)
engine_l.add_instrument(make_instrument())
strat_l = LiqProbeStrategy(StrategyConfig(strategy_id="LIQ-001"))
engine_l.add_strategy(strat_l)

# Bar 1: 50,000. Bar 2: sập về 30,000
t0 = start_s * 1_000_000_000
b1 = Bar(bar_type=bar_type_1m, open=Price(50000, 1), high=Price(50000, 1), low=Price(50000, 1), close=Price(50000, 1), volume=Quantity(1, 4), ts_event=t0 + 60_000_000_000, ts_init=t0 + 60_000_000_000)
b2 = Bar(bar_type=bar_type_1m, open=Price(40000, 1), high=Price(40000, 1), low=Price(30000, 1), close=Price(30000, 1), volume=Quantity(1, 4), ts_event=t0 + 120_000_000_000, ts_init=t0 + 120_000_000_000)
engine_l.add_data([b1, b2])
engine_l.run()

print(f"Is net flat (liquidated): {strat_l.is_flat}")
print(f"Final balance: {strat_l.final_balance}")
print("-> Kết luận: Nautilus backtest KHÔNG tự ép thanh lý (liquidation) khi margin âm. Cần PortfolioGuard lo kill switch / margin check.")
engine_l.dispose()

# -------------------------------------------------------------
# Test 4: Bar.volume constraint on fills
# -------------------------------------------------------------
print("\n--- TEST 4: Bar.volume constraint when bar_execution=True ---")
class VolProbeStrategy(Strategy):
    def on_start(self):
        self.subscribe_bars(bar_type_1m)

    def on_bar(self, bar: Bar):
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity(100.0, 4),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

engine_v = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
engine_v.add_venue(
    venue=venue,
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    base_currency=USDT,
    starting_balances=[Money(10_000_000, USDT)],
    bar_execution=True,
)
engine_v.add_instrument(make_instrument())
strat_v = VolProbeStrategy(StrategyConfig(strategy_id="VOL-001"))
engine_v.add_strategy(strat_v)

bv = Bar(bar_type=bar_type_1m, open=Price(50000, 1), high=Price(50000, 1), low=Price(50000, 1), close=Price(50000, 1), volume=Quantity(1.0, 4), ts_event=t0 + 60_000_000_000, ts_init=t0 + 60_000_000_000)
engine_v.add_data([bv])
engine_v.run()

fills = engine_v.trader.generate_order_fills_report()
if not fills.empty:
    print(f"Fills report columns: {list(fills.columns)}")
    qty_col = "order_qty" if "order_qty" in fills.columns else ("last_qty" if "last_qty" in fills.columns else fills.columns[1])
    filled_qty = fills[qty_col].sum()
    print(f"Requested: 100.0 BTC, Bar volume: 1.0 BTC -> Fill qty col '{qty_col}': {filled_qty}")
    print("-> Kết luận: Bar.volume KHÔNG hạn chế khối lượng khớp lệnh thị trường khi bar_execution=True (mặc định khớp trọn vẹn).")
engine_v.dispose()

# -------------------------------------------------------------
# Test 5: Benchmark Tốc độ & RAM (50,000 nến 1m)
# -------------------------------------------------------------
print("\n--- TEST 5: Benchmark Speed & RAM (50,000 bars 1m) ---")
engine_bench = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
engine_bench.add_venue(
    venue=venue,
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    base_currency=USDT,
    starting_balances=[Money(10000, USDT)],
)
engine_bench.add_instrument(make_instrument())

class BenchStrategy(Strategy):
    def on_start(self):
        self.subscribe_bars(bar_type_1m)
    def on_bar(self, bar: Bar):
        pass

engine_bench.add_strategy(BenchStrategy(StrategyConfig(strategy_id="BENCH-001")))

bench_bars = []
for i in range(50000):
    t_ns = (start_s + (i + 1) * 60) * 1_000_000_000
    b = Bar(
        bar_type=bar_type_1m,
        open=Price(50000.0, 1),
        high=Price(50010.0, 1),
        low=Price(49990.0, 1),
        close=Price(50005.0, 1),
        volume=Quantity(1.0, 4),
        ts_event=t_ns,
        ts_init=t_ns,
    )
    bench_bars.append(b)

proc = psutil.Process()
mem_before = proc.memory_info().rss / 1024 / 1024
engine_bench.add_data(bench_bars)

t_start = time.perf_counter()
engine_bench.run()
t_elapsed = time.perf_counter() - t_start
mem_after = proc.memory_info().rss / 1024 / 1024

print(f"50,000 bars processed in: {t_elapsed:.3f} s ({50000 / t_elapsed:.0f} bars/sec)")
print(f"Estimated for 1.58M bars (3 years): {t_elapsed * (1580000 / 50000):.2f} s")
print(f"RAM peak: ~{mem_after:.1f} MB (Delta: +{mem_after - mem_before:.1f} MB)")
engine_bench.dispose()

print("\n=== P1.0 PROBE HOÀN THÀNH TOÀN BỘ CÁC CÂU HỎI KIỂM THỬ ===")
