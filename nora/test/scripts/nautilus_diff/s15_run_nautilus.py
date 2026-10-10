"""Run NautilusTrader side of S15 matching engine parity tests.
Executes native Nautilus BacktestEngine on synthetic bar data across all cases and path modes (ohlc, adaptive).
Outputs to out/s15/nautilus_<case>_<mode>.json.
"""
import json
import os
import sys
from decimal import Decimal

import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType, Bar, BarType, BookType, ClientOrderId, CryptoPerpetual,
    Currency, InstrumentId, Money, OmsType, OrderSide, Price, Quantity,
    Symbol, TimeInForce, TraderId, TrailingOffsetType, Venue
)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from s15_common import CAPITAL, MAKER, MIN_NS, OUT, SYM, TAKER, VENUE, T0_NS
from s15_cases import CASES

USDT = Currency.from_str("USDT")
INST_ID = InstrumentId(Symbol("BTC-USDT-SWAP"), Venue(VENUE))


class S15Strategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, case, mode, bar_type):
        super().__init__(config)
        self.bar_type = bar_type
        self.case = case
        self.mode = mode
        self.is_long = case["side"] == "LONG"
        self.entry_side = OrderSide.BUY if self.is_long else OrderSide.SELL
        self.exit_side = OrderSide.SELL if self.is_long else OrderSide.BUY
        self.sign = 1.0 if self.is_long else -1.0
        self.lev = float(case["lev"])
        self.mmr = float(case.get("mmr", 0.005))
        self.sl_pct = float(case["sl"])
        self.tp_pct = float(case["tp"])
        self.dca = case["dca"]
        self.trail = case["trail"]

        self.order_kinds = {}
        self.fills = []
        self.entry_submitted = False
        self.sl_order_ids = []
        self.dca_order_ids = []
        self.peak_price = 0.0

    def on_start(self):
        self.inst = self.cache.instrument(INST_ID)
        self.subscribe_bars(self.bar_type)

    def _px(self, v):
        return self.inst.make_price(v)

    def _qty(self, v):
        return self.inst.make_qty(v)

    def _submit(self, order, kind):
        self.order_kinds[str(order.client_order_id)] = kind
        self.submit_order(order)

    def on_bar(self, bar):
        # Entry trigger only once at bar 0
        if not self.entry_submitted:
            self.entry_submitted = True
            entry_qty = 1.0 * self.lev
            order = self.order_factory.market(
                INST_ID, self.entry_side, self._qty(entry_qty)
            )
            self._submit(order, "ENTRY")

    def on_order_filled(self, event):
        coid = str(event.client_order_id)
        kind = self.order_kinds.get(coid, "UNKNOWN")
        px = float(event.last_px)
        qty = float(event.last_qty)
        fee = float(event.commission.as_double()) if event.commission else 0.0
        t_ms = int(event.ts_event) // 1_000_000

        self.fills.append({
            "t": t_ms,
            "side": "BUY" if event.is_buy else "SELL",
            "px": px,
            "qty": qty,
            "fee": fee,
            "liq": str(event.liquidity_side).lower(),
            "kind": kind,
        })

        if kind == "ENTRY":
            self.entry_filled = True
            self.peak_price = px
            pos = self.cache.positions_open(instrument_id=INST_ID)
            pos_qty = float(pos[0].quantity) if pos else qty

            # Calculate total planned qty if DCA fills
            total_planned_qty = pos_qty
            if self.dca:
                steps = self.dca["steps"]
                mults = self.dca["mults"]
                curr_px = px
                for j, (step, mult) in enumerate(zip(steps, mults)):
                    curr_px = curr_px * (1.0 - self.sign * step / 100.0)
                    layer_qty = (100.0 * mult * self.lev) / curr_px
                    total_planned_qty += layer_qty

            # 1. Place TP if configured
            if self.tp_pct > 0:
                tp_px = px * (1.0 + self.sign * self.tp_pct / 100.0)
                tp_order = self.order_factory.limit(
                    INST_ID, self.exit_side, self._qty(pos_qty), self._px(tp_px),
                    time_in_force=TimeInForce.GTC
                )
                self._submit(tp_order, "TP")

            # 2. Place SL if configured (sized for total_planned_qty with reduce_only)
            if self.sl_pct > 0:
                sl_px = px * (1.0 - self.sign * self.sl_pct / 100.0)
                sl_order = self.order_factory.stop_market(
                    INST_ID, self.exit_side, self._qty(total_planned_qty), self._px(sl_px),
                    reduce_only=True
                )
                self.sl_order_ids.append(str(sl_order.client_order_id))
                self._submit(sl_order, "SL")

            # 3. Place DCA layers if configured
            if self.dca:
                steps = self.dca["steps"]
                mults = self.dca["mults"]
                curr_px = px
                for j, (step, mult) in enumerate(zip(steps, mults)):
                    curr_px = curr_px * (1.0 - self.sign * step / 100.0)
                    layer_qty = (100.0 * mult * self.lev) / curr_px
                    dca_order = self.order_factory.limit(
                        INST_ID, self.entry_side, self._qty(layer_qty), self._px(curr_px),
                        time_in_force=TimeInForce.GTC
                    )
                    self.dca_order_ids.append(str(dca_order.client_order_id))
                    self._submit(dca_order, "DCA")

            # 4. Place Trailing stop if configured
            if self.trail:
                trail_act = float(self.trail["act"])
                trail_offset = float(self.trail["offset"])
                act_px = self._px(px * (1.0 + self.sign * trail_act / 100.0))
                trail_order = self.order_factory.trailing_stop_market(
                    INST_ID, self.exit_side, self._qty(pos_qty),
                    Decimal(str(round(trail_offset * 100.0, 8))),
                    TrailingOffsetType.BASIS_POINTS,
                    activation_price=act_px,
                    reduce_only=True
                )
                self._submit(trail_order, "TRAIL")

            # 5. Place Liquidation order if lev >= 10
            if self.lev >= 10 and self.sl_pct == 0:
                liq_px = px * (1.0 - 1.0 / self.lev + self.mmr) if self.is_long else px * (1.0 + 1.0 / self.lev - self.mmr)
                liq_order = self.order_factory.stop_market(
                    INST_ID, self.exit_side, self._qty(pos_qty), self._px(liq_px),
                    reduce_only=True
                )
                self._submit(liq_order, "LIQ")

        elif kind in ("SL", "TP", "TRAIL", "LIQ"):
            # Position closed
            pos = self.cache.positions_open(instrument_id=INST_ID)
            if not pos:
                self.cancel_all_orders(INST_ID)

    def on_order_rejected(self, event):
        print(f"[{self.case['desc']}] ORDER REJECTED: {event}")

    def on_order_denied(self, event):
        print(f"[{self.case['desc']}] ORDER DENIED: {event}")


def run_case_nautilus(case_name, case, mode="ohlc"):
    adaptive = (mode == "adaptive")
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId(f"S15-{case_name[:8]}"),
        risk_engine=RiskEngineConfig(bypass=True),
    ))

    engine.add_venue(
        venue=Venue(VENUE),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USDT,
        starting_balances=[Money(CAPITAL, USDT)],
        book_type=BookType.L1_MBP,
        bar_execution=True,
        bar_adaptive_high_low_ordering=adaptive,
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))),
    )

    mmr_dec = Decimal(str(round(case.get("mmr", 0.005) * float(case["lev"]), 6)))
    inst = CryptoPerpetual(
        instrument_id=INST_ID,
        raw_symbol=Symbol("BTC-USDT-SWAP"),
        base_currency=Currency.from_str("BTC"),
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=4,
        size_precision=8,
        price_increment=Price.from_str("0.0001"),
        size_increment=Quantity.from_str("0.00000001"),
        margin_init=Decimal("0.01"),
        margin_maint=mmr_dec,
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(inst)

    bar_type = BarType.from_str("BTC-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL")
    strat = S15Strategy(StrategyConfig(), case, mode, bar_type)
    engine.add_strategy(strat)

    # Convert bars to Nautilus Bars
    bars_df = case["bars"]
    nautilus_bars = []
    for _, row in bars_df.iterrows():
        t_open_ns = int(row["open_time"]) * 1_000_000
        t_close_ns = t_open_ns + MIN_NS
        b = Bar(
            bar_type,
            Price.from_str(f"{row['open']:.4f}"),
            Price.from_str(f"{row['high']:.4f}"),
            Price.from_str(f"{row['low']:.4f}"),
            Price.from_str(f"{row['close']:.4f}"),
            Quantity.from_str(f"{row['volume']:.8f}"),
            t_open_ns,
            t_close_ns,
        )
        nautilus_bars.append(b)

    engine.add_data(nautilus_bars)
    engine.run()

    # Get realized equity
    acct = engine.portfolio.account(Venue(VENUE))
    bal = float(acct.balance_total(USDT).as_double())

    open_pos = engine.cache.positions_open(instrument_id=INST_ID)
    open_at_end = []
    for p in open_pos:
        open_at_end.append({
            "sym": SYM,
            "enter_time": int(p.ts_opened) // 1_000_000,
            "avg_price": float(p.avg_px_open),
            "qty": float(p.quantity),
        })

    return {
        "case": case_name,
        "mode": mode,
        "fills": strat.fills,
        "n_fills": len(strat.fills),
        "open_at_end": open_at_end,
        "realized_equity": bal,
    }


def main():
    only_case = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in ("all", "ohlc", "adaptive") else None
    modes = ["ohlc", "adaptive"]
    if len(sys.argv) > 1 and sys.argv[1] in ("ohlc", "adaptive"):
        modes = [sys.argv[1]]

    cases_to_run = [only_case] if only_case else list(CASES.keys())

    for case_name in cases_to_run:
        for mode in modes:
            case = CASES[case_name]
            res = run_case_nautilus(case_name, case, mode)
            out_file = os.path.join(OUT, f"nautilus_{case_name}_{mode}.json")
            with open(out_file, "w") as f:
                json.dump(res, f, indent=2)
            print(f"Nautilus {case_name} [{mode}]: {res['n_fills']} fills, eq={res['realized_equity']:.2f}")


if __name__ == "__main__":
    main()
