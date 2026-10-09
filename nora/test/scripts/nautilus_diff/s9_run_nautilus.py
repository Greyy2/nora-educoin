"""S9 Nautilus side: BacktestEngine (L1 bar execution, NETTING MARGIN, same venue config as the ext harness), two instruments, each with TWO bar
subscriptions: 1-MINUTE-LAST-EXTERNAL (the execution/matching stream - Nautilus uses the finest external bar type per instrument for matching and
ignores the 1-DAY bars there) and 1-DAY-LAST-EXTERNAL (signal stream, ts = bar CLOSE). The strategy acts ONLY in on_bar of the daily bar (-> one
decision per daily close = the event semantics P12 A1 gives Nora); the 1m on_bar only counts bars / remembers the last close. Daily bars are emitted
right after the two 1m bars with the same ts (stable order), so every 1m bar of the day has been matched when the daily bar arrives.
Signals are precomputed in pandas (s9_export_data.py). Entry = market at the daily close (fills at the last 1m close = Nora's next-1m OPEN on the
ALIGNED data); stop = reduce-only STOP_MARKET at avg*(1-sl%) placed on the entry fill, matched on the 1m path; exit = market at the daily close.
Symbols act in book order with 1 ns spacing (alerts) so that a close/entry of the previous symbol has settled (balance, open flag) - Nora's per-minute
sequential slot order (exit -> entry symbol by symbol, max_positions=1 seen live).
Run from nora/: systemd-run --user --scope --slice=nora.slice -p MemoryMax=4G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/s9_run_nautilus.py [stages|all]
Writes out/s9/nautilus_<stage>.json.
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
from nautilus_trader.model import (AccountType, Bar, BarType, BookType, ClientOrderId, Currency, Money, OmsType, OrderSide, Price, Quantity,
                                   TraderId, Venue)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s9_common import CAPITAL, DAY, MAKER, OUT, PORT, STAGES, SYMS, TAKER  # noqa: E402
from ext_run_nautilus import build_trades, inst_id, make_instrument      # noqa: E402  (the same trade reconstruction as S4-S8)
from backend.core import position_size as npolicy                        # noqa: E402  (Nora's own pure sizing / admission formulas)

USDT = Currency.from_str("USDT")
VENUE = Venue("OKX")
MIN_NS = 60_000_000_000


def bt(sym, kind):
    return BarType.from_str(f"{sym}USDT-PERP.OKX-1-{'MINUTE' if kind == 'm' else 'DAY'}-LAST-EXTERNAL")


class S9Config(StrategyConfig):
    def __init__(self, **_kw):
        super().__init__()


class Sym:
    def __init__(self, sym, ent, ext):
        self.sym, self.ent, self.ext = sym, ent, ext     # daily flags indexed by day number
        self.nb = 0              # 1m bars dispatched; a fill during matching of bar j happens while nb == j
        self.day = 0
        self.last_close = float("nan")
        self.live = False
        self.closing = False
        self.closed_bar = -1     # 1m bar index in which the last position was closed by the stop
        self.qty_plan = 0.0
        self.reserved = 0.0
        self.fees_open = 0.0
        self.entry_equity = CAPITAL
        self.entry_equities = []
        self.entry_margin = 0.0
        self.fills = []
        self.sl_id = None


class S9Strategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, cfg, sigs):
        super().__init__(config)
        self.cfg = cfg
        self.S = {s: Sym(s, *sigs[s]) for s in SYMS}
        self.by_inst = {str(inst_id(s)): s for s in SYMS}
        self.kind = {}
        self.admit_log = []      # [day, sym, can_open, n_open, gross, eq, max_new_notional]
        self.acts = []           # [day, sym, action] for the report
        self.d0 = int(pd.read_csv(os.path.join(OUT, f"daily_{SYMS[0]}.csv")).open_time.iloc[0]) // DAY    # absolute day number of daily index 0

    def on_start(self):
        self.inst = {s: self.cache.instrument(inst_id(s)) for s in SYMS}
        for s in SYMS:
            self.subscribe_bars(bt(s, "m"))
            self.subscribe_bars(bt(s, "d"))

    def bal(self):
        return float(self.portfolio.account(VENUE).balance_total(USDT).as_double())

    def eq_nora(self):
        return self.bal() + sum(st.fees_open for st in self.S.values() if st.live)

    def on_order_filled(self, event):
        coid = str(event.client_order_id)
        sym = self.by_inst[str(event.instrument_id)]
        st = self.S[sym]
        kind = self.kind.get(coid, "?")
        fee = float(event.commission.as_double()) if event.commission else 0.0
        px, qty = float(event.last_px), float(event.last_qty)
        bar = st.nb if kind == "SL" else st.day * 1440 + 1439          # SL: the 1m bar being matched; ENTRY/SIG: acted at the daily close
        rec = {"stray": False, "t": int(event.ts_event) // 1_000_000, "side": "BUY" if event.is_buy else "SELL", "px": px, "qty": qty, "fee": fee,
               "liq": str(event.liquidity_side), "kind": kind, "bar": bar, "equity_after": self.bal(), "sym": sym}
        st.fills.append(rec)
        st.fees_open += fee
        if kind == "ENTRY":
            st.reserved += qty * px / self.cfg["lev"] + fee
            pos = self.cache.positions_open(instrument_id=inst_id(sym))[0]
            sl = self.order_factory.stop_market(inst_id(sym), OrderSide.SELL, pos.quantity,
                                                self.inst[sym].make_price(float(pos.avg_px_open) * (1 - self.cfg["sl"] / 100.0)), reduce_only=True)
            self.kind[str(sl.client_order_id)] = "SL"
            st.sl_id = str(sl.client_order_id)
            self.submit_order(sl)
        elif kind in ("SL", "SIG") and not self.cache.positions_open(instrument_id=inst_id(sym)):
            rec["adj"] = []
            self.cancel_all_orders(inst_id(sym))
            if kind == "SL":
                st.closed_bar = st.nb
            st.live = st.closing = False
            st.qty_plan = st.reserved = st.fees_open = 0.0
            st.sl_id = None

    def on_bar(self, bar):
        sym = self.by_inst[str(bar.bar_type.instrument_id)]
        st = self.S[sym]
        if bar.bar_type.spec.aggregation.name == "MINUTE":
            st.nb += 1
            st.last_close = float(bar.close)
            return
        st.day = int(bar.ts_event) // (DAY * 1_000_000) - 1 - self.d0     # daily bar index (ts = close = next midnight)
        k = SYMS.index(sym)
        self.clock.set_time_alert_ns(f"act-{sym}-{st.day}", int(bar.ts_init) + 1 + k, self._on_alert)

    def _on_alert(self, event):
        _, sym, day = str(event.name).split("-")
        self._act(self.S[sym], int(day))

    def _act(self, st, d):
        sym, c = st.sym, self.cfg
        i = st.nb - 1                                                     # index of the last 1m bar of the day just closed
        iid = inst_id(sym)
        if st.live:
            if st.closing or not self.cache.positions_open(instrument_id=iid):
                return
            if st.ext[d]:
                self.cancel_all_orders(iid)
                st.closing = True
                self.acts.append([d, sym, "exit"])
                pos = self.cache.positions_open(instrument_id=iid)[0]
                o = self.order_factory.market(iid, OrderSide.SELL, pos.quantity, reduce_only=True)
                self.kind[str(o.client_order_id)] = "SIG"
                st.live = False                                           # closing: not counted as open for max_positions
                self.submit_order(o)
        elif st.ent[d] and st.closed_bar != i:                            # a stop-out in the signal bar itself blocks the entry (Nora P6.12 / A3)
            eq = self.eq_nora()
            n_open = sum(1 for s in self.S.values() if s.live)
            gross = 0.0
            if n_open < int(PORT["max_positions"]):
                gross = sum(s.qty_plan * s.last_close for s in self.S.values() if s.live)
            adm = npolicy.admit_entry(n_open, 0, eq, eq, gross, 0.0, PORT["max_positions"], PORT["max_per_symbol"], PORT["max_gross_exposure"], 0.0, 0.0)
            self.admit_log.append([d, sym, adm.can_open, n_open, gross, eq, adm.max_new_notional])
            if not adm.can_open:
                return
            reserved = sum(s.reserved for s in self.S.values() if s.live)
            margin = npolicy.clamp_margin(npolicy.flat_margin(eq, c["osp"]), min(eq, eq - reserved), float(c["lev"]), TAKER, adm.max_new_notional)
            if margin <= 0:
                return
            qty = self.inst[sym].make_qty(margin * c["lev"] / st.last_close)
            st.entry_margin, st.entry_equity = margin, eq
            st.entry_equities.append(eq)
            st.live, st.qty_plan, st.reserved, st.fees_open = True, float(qty), 0.0, 0.0
            self.acts.append([d, sym, "enter"])
            o = self.order_factory.market(iid, OrderSide.BUY, qty)
            self.kind[str(o.client_order_id)] = "ENTRY"
            self.submit_order(o)


def run_one(stname):
    st = STAGES[stname]
    cfg = dict(st, mmr=0.005)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-009"), risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(st["lev"]), book_type=BookType.L1_MBP, bar_execution=True,
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))))
    m, dly, sigs, insts = {}, {}, {}, {}
    for sym in SYMS:
        insts[sym] = make_instrument(sym, cfg)
        engine.add_instrument(insts[sym])
        m[sym] = pd.read_csv(os.path.join(OUT, f"bars1m_{sym}.csv"))
        dly[sym] = pd.read_csv(os.path.join(OUT, f"daily_{sym}.csv"))
        sigs[sym] = (dly[sym][f"ent_{stname}"].values.astype(bool), dly[sym][f"ext_{stname}"].values.astype(bool))
    vol = insts[SYMS[0]].make_qty(1000)
    items = []
    n = len(m[SYMS[0]])
    arr = {s: [m[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    darr = {s: [dly[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    for i in range(n):
        for s in SYMS:
            t, o, h, l, c = (a[i] for a in arr[s])
            ts = int(t) * 1_000_000 + MIN_NS
            p = insts[s].make_price
            items.append(Bar(bt(s, "m"), p(o), p(h), p(l), p(c), vol, ts, ts))
        if (i + 1) % 1440 == 0:
            j = (i + 1) // 1440 - 1
            for s in SYMS:
                t, o, h, l, c = (a[j] for a in darr[s])
                ts = int(t) * 1_000_000 + DAY * 1_000_000
                p = insts[s].make_price
                items.append(Bar(bt(s, "d"), p(o), p(h), p(l), p(c), vol, ts, ts))
    engine.add_data(items)
    strat = S9Strategy(S9Config(), cfg, sigs)
    engine.add_strategy(strat)
    engine.run()
    acct = engine.portfolio.account(VENUE)
    res = {"stage": stname, "trades": [], "open_at_end": [], "admit_log": strat.admit_log, "acts": strat.acts}
    all_trades = []
    for sym in SYMS:
        ss = strat.S[sym]
        fl = []
        for f in ss.fills:
            f = dict(f)
            f["is_entry"] = f["side"] == "BUY"
            fl.append(f)
        trades, cur = build_trades(fl, ss.entry_equities, 1)
        for t in trades:
            t["sym"] = sym
        all_trades += trades
        if cur is not None:
            res["open_at_end"].append({"sym": sym, "enter_time": cur["enter_time"], "fees_open": cur["fees"]})
    all_trades.sort(key=lambda t: (t["enter_time"], t["sym"]))
    res["trades"] = all_trades
    res["final_equity"] = float(acct.balance_total(USDT).as_double())
    res["realized_equity_nora_def"] = res["final_equity"] + sum(o["fees_open"] for o in res["open_at_end"])
    engine.dispose()
    return res


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    for name in only:
        r = run_one(name)
        json.dump(r, open(os.path.join(OUT, f"nautilus_{name}.json"), "w"))
        print(name, "trades", len(r["trades"]), "realized(nora def)", round(r["realized_equity_nora_def"], 4), "open_at_end", len(r["open_at_end"]), flush=True)


if __name__ == "__main__":
    main()
