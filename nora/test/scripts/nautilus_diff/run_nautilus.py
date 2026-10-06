"""Run the same signals/bars through NautilusTrader (BacktestEngine, L1 bar execution, NETTING MARGIN venue).
Writes out/nautilus_<inst>_<dataset>_<signal>_<stage>[_adaptive].json with every fill and the reconstructed trades.
Run with the nautilus venv:  ~/.venvs/nautilus/bin/python test/scripts/nautilus_diff/run_nautilus.py [inst=fine|okx] [adaptive=0|1]
(under memory limit: systemd-run --user --scope --slice=nora.slice -p MemoryMax=4G ...)
"""
import json
import os
import sys
from decimal import Decimal

import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.common import LogLevel
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (AccountType, Bar, BarType, BookType, ClientOrderId, Currency, CryptoPerpetual, InstrumentId, Money,
                                   OmsType, OrderSide, Price, Quantity, Symbol, TimeInForce, TraderId, Venue)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, DATASETS, MAKER, ORDER_SIZE_PCT, SIGNALS, STAGES, TAKER  # noqa: E402

OUT = os.path.join(HERE, "out")
USDT, BTC = Currency.from_str("USDT"), Currency.from_str("BTC")
VENUE = Venue("OKX")
INST_ID = InstrumentId(Symbol("BTCUSDT-PERP"), VENUE)
BAR_TYPE = BarType.from_str("BTCUSDT-PERP.OKX-1-HOUR-LAST-EXTERNAL")
HOUR_NS = 3_600_000_000_000
# fine: tick/lot small enough that rounding is negligible. okx: BTC-USDT-SWAP tick 0.1, lot 0.0001 BTC (0.01 contract * 0.01 BTC).
PRECISION = {"fine": (8, 8), "okx": (1, 4)}


def make_instrument(inst):
    pp, sp = PRECISION[inst]
    return CryptoPerpetual(
        instrument_id=INST_ID, raw_symbol=Symbol("BTCUSDT-PERP"), base_currency=BTC, quote_currency=USDT,
        settlement_currency=USDT, is_inverse=False, price_precision=pp, size_precision=sp,
        price_increment=Price.from_str(f"{10 ** -pp:.{pp}f}"), size_increment=Quantity.from_str(f"{10 ** -sp:.{sp}f}"),
        ts_event=0, ts_init=0, margin_init=Decimal("0.01"), margin_maint=Decimal("0.005"))


class DiffConfig(StrategyConfig):
    def __init__(self, *, instrument_id, bar_type, **_kw):
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type


class DiffStrategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, entry, exit_, st, order_pct):
        super().__init__(config)
        self.entry, self.exit_, self.st, self.order_pct = entry, exit_, st, order_pct
        self.nb = 0                    # bars dispatched so far (== index of the bar whose ticks are being matched)
        self.closed_bar = -1           # Nora-equivalent bar index in which the last position was closed
        self.sig_exit_inflight = False
        self.kind = {}                 # client_order_id -> kind
        self.fills = []
        self.planned = []              # DCA ladder [(level, qty)] still to place
        self.dca_ids = []
        self.prot_ids = []
        self.prot_log = []

    def on_start(self):
        self.inst = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    # ── helpers ──
    def equity(self):
        return float(self.portfolio.account(VENUE).balance_total(USDT).as_double())

    def _px(self, v):
        return self.inst.make_price(v)

    def _qty(self, v):
        return self.inst.make_qty(v)

    def _position(self):
        pos = self.cache.positions_open(instrument_id=self.config.instrument_id)
        return pos[0] if pos else None

    def _submit(self, order, kind):
        self.kind[str(order.client_order_id)] = kind
        if kind in ("SL", "TP"):
            self.prot_ids.append(str(order.client_order_id))
        self.submit_order(order)

    def _place_protection(self):
        pos = self._position()
        if pos is None:
            return
        avg, qty = float(pos.avg_px_open), pos.quantity
        self.prot_log.append({"nb": self.nb, "avg": avg, "qty": float(qty), "fills_seen": len(self.fills)})
        for oid in self.prot_ids:                      # cancel ONLY the previous SL/TP (never the resting DCA ladder)
            o = self.cache.order(ClientOrderId(oid))
            if o is not None and not o.is_closed:
                self.cancel_order(o.client_order_id)
        self.prot_ids = []
        sl, tp = self.st.get("sl", 0.0), self.st.get("tp", 0.0)
        if sl:
            self._submit(self.order_factory.stop_market(self.config.instrument_id, OrderSide.SELL, qty,
                                                        self._px(avg * (1 - sl / 100.0)), reduce_only=True), "SL")
        if tp:
            self._submit(self.order_factory.limit(self.config.instrument_id, OrderSide.SELL, qty,
                                                  self._px(avg * (1 + tp / 100.0)), reduce_only=True,
                                                  time_in_force=TimeInForce.GTC), "TP")

    def _place_dca(self, base_px, base_margin):
        """Place the whole remaining ladder from the last fill price (levels chain from the previous layer's fill)."""
        steps, mults = self.st.get("dca_steps", []), self.st.get("dca_mults", [])
        self.dca_state = (base_px, base_margin, 0)
        self._arm_next_dca()

    def _arm_next_dca(self):
        steps, mults = self.st.get("dca_steps", []), self.st.get("dca_mults", [])
        px, margin, k = self.dca_state
        # Resting ladder: every remaining layer is placed up front, each chained from the PLANNED fill of the previous one.
        for j in range(k, len(steps)):
            px = px * (1 - steps[j] / 100.0)
            margin = margin * mults[j]
            o = self.order_factory.limit(self.config.instrument_id, OrderSide.BUY, self._qty(margin / px), self._px(px),
                                         time_in_force=TimeInForce.GTC)
            self.dca_ids.append(str(o.client_order_id))
            self.layer_of = getattr(self, "layer_of", {})
            self.layer_of[str(o.client_order_id)] = (j, float(self._px(px)), margin)
            self._submit(o, "DCA")

    # ── events ──
    def on_order_filled(self, event):
        coid = str(event.client_order_id)
        kind = self.kind.get(coid, "?")
        self.fills.append({"t": int(event.ts_event) // 1_000_000, "side": "BUY" if event.is_buy else "SELL",
                           "px": float(event.last_px), "qty": float(event.last_qty),
                           "fee": float(event.commission.as_double()) if event.commission else 0.0,
                           "liq": str(event.liquidity_side), "kind": kind, "bar": self.nb,
                           "equity_after": self.equity()})
        pos = self._position()
        if kind == "ENTRY":
            self._place_protection()
            if self.st.get("dca_steps"):
                self._place_dca(float(event.last_px), self.entry_margin)
        elif kind == "DCA":
            j, planned_px, margin = self.layer_of[coid]
            self._place_protection()
            # Nora chains the next level from the ACTUAL fill price; if it differs from plan, re-ladder the remainder.
            if abs(float(event.last_px) - planned_px) > 1e-9:
                for oid in [o for o in self.dca_ids if o != coid]:
                    o = self.cache.order(ClientOrderId(oid))
                    if o is not None and not o.is_closed:
                        self.cancel_order(o.client_order_id)
                self.dca_state = (float(event.last_px), margin, j + 1)
                self._arm_next_dca()
        elif kind in ("SL", "TP", "SIG") and pos is None:
            self.cancel_all_orders(self.config.instrument_id)
            # signal exit decided at close of bar i -> Nora closes it at the open of bar i+1 (that bar's entry signal is ignored);
            # SL/TP fill while bar `nb`'s ticks are matched -> Nora bar index == nb.
            self.closed_bar = self.sig_bar if kind == "SIG" else self.nb
            self.sig_exit_inflight = False
            self.dca_ids = []

    def on_bar(self, bar):
        i = self.nb
        pos = self._position()
        if pos is not None:
            if self.exit_[i]:
                self.cancel_all_orders(self.config.instrument_id)
                self.sig_exit_inflight = True
                self.sig_bar = i + 1
                self._submit(self.order_factory.market(self.config.instrument_id, OrderSide.SELL, pos.quantity,
                                                       reduce_only=True), "SIG")
        elif not self.sig_exit_inflight and self.entry[i] and self.closed_bar != i:
            eq = self.equity()
            self.entry_margin = eq * self.order_pct / 100.0
            qty = self.entry_margin / float(bar.close)          # leverage 1: notional = margin; qty = notional / price
            self._submit(self.order_factory.market(self.config.instrument_id, OrderSide.BUY, self._qty(qty)), "ENTRY")
        self.nb += 1

    def on_stop(self):
        pass


def build_trades(fills):
    trades, cur = [], None
    for f in fills:
        if cur is None:
            cur = {"enter_time": f["t"], "buys": [], "sells": [], "fees": 0.0, "entry_equity": None, "layers": 0, "fills": []}
        cur["fees"] += f["fee"]
        if f["side"] == "BUY":
            cur["fills"].append(f)
        if f["side"] == "BUY":
            cur["buys"].append((f["px"], f["qty"]))
            cur["layers"] += 1
            if cur["entry_equity"] is None:
                cur["entry_equity"] = f["entry_equity_before"]
        else:
            cur["sells"].append((f["px"], f["qty"]))
            bq = sum(q for _, q in cur["buys"])
            sq = sum(q for _, q in cur["sells"])
            if abs(bq - sq) < 1e-12:
                bn, sn = sum(p * q for p, q in cur["buys"]), sum(p * q for p, q in cur["sells"])
                trades.append({"enter_time": cur["enter_time"], "enter_price": cur["buys"][0][0], "close_time": f["t"],
                               "close_price": sn / sq, "qty": bq, "avg_price": bn / bq, "fees": cur["fees"],
                               "pnl": sn - bn - cur["fees"], "reason": f["kind"], "entry_equity": cur["entry_equity"],
                               "layers": cur["layers"], "bar_exit": f["bar"], "equity_after": f["equity_after"],
                               "fills": cur["fills"] + [f]})
                cur = None
    return trades, cur


def run_one(inst, ds, sname, stname, sigdf, adaptive):
    bars = pd.read_csv(os.path.join(OUT, f"bars_{ds}.csv"))
    instrument = make_instrument(inst)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-001"),
                                                 risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(1), book_type=BookType.L1_MBP,
                     bar_execution=True, bar_adaptive_high_low_ordering=adaptive,
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))))
    engine.add_instrument(instrument)
    vol = instrument.make_qty(1000)
    data = []
    for t, o, h, l, c in zip(bars.open_time, bars.open, bars.high, bars.low, bars.close):
        ts = (int(t) * 1_000_000) + HOUR_NS            # ts_init = ts_event = bar CLOSE
        data.append(Bar(BAR_TYPE, instrument.make_price(o), instrument.make_price(h), instrument.make_price(l),
                        instrument.make_price(c), vol, ts, ts))
    engine.add_data(data)
    st = STAGES[stname]
    cfg = DiffConfig(instrument_id=INST_ID, bar_type=BAR_TYPE)
    strat = DiffStrategy(cfg, sigdf[sname + "_entry"].values, sigdf[sname + "_exit"].values, st,
                         st.get("osp", ORDER_SIZE_PCT))
    engine.add_strategy(strat)
    engine.run()
    # equity before each entry = equity_after of the previous flat point (or the starting capital)
    fills, eq = strat.fills, CAPITAL
    pos_qty = 0.0
    for f in fills:
        f["entry_equity_before"] = eq
        pos_qty += f["qty"] if f["side"] == "BUY" else -f["qty"]
        if abs(pos_qty) < 1e-12:
            eq = f["equity_after"]
            pos_qty = 0.0
    trades, open_cur = build_trades(fills)
    res = {"trades": trades, "final_equity": strat.equity(), "open_at_end": open_cur is not None,
           "n_fills": len(fills), "fills": fills, "prot_log": strat.prot_log}
    engine.dispose()
    return res


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else "fine"
    adaptive = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
    only_ds = sys.argv[3].split(",") if len(sys.argv) > 3 else DATASETS
    only_st = sys.argv[4].split(",") if len(sys.argv) > 4 else list(STAGES)
    sigdf = pd.read_csv(os.path.join(OUT, "signals.csv"))
    for ds in only_ds:
        for sname in SIGNALS:
            for stname in only_st:
                r = run_one(inst, ds, sname, stname, sigdf, adaptive)
                tag = f"{inst}_{ds}_{sname}_{stname}" + ("_adaptive" if adaptive else "")
                json.dump(r, open(os.path.join(OUT, f"nautilus_{tag}.json"), "w"))
                print(tag, "trades", len(r["trades"]), "final", round(r["final_equity"], 4), flush=True)


if __name__ == "__main__":
    main()
