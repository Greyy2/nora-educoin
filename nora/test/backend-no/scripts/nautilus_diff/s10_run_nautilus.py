"""S10 Nautilus side (pattern of s9_run_nautilus.py): BacktestEngine (L1 bar execution, NETTING MARGIN), two instruments, each with a 1-MINUTE-LAST-EXTERNAL
stream (matching) and a signal-frame stream (1/4-HOUR-LAST-EXTERNAL, ts = bar CLOSE). Entry = market at the signal-bar close (= last 1m close = Nora's next
1m open on the ALIGNED data), decided in the signal bar's on_bar (symbols in book order, +1 ns spacing, admission via Nora's own pure npolicy formulas).
Exit mechanics (all levels computed with the SAME float expressions as test/backend-no/backend/core/backtest.py::_intrabar_path):
  unit      = natr_<period> of the last atr_frame candle CLOSED at the entry instant (precomputed in s10_export_data.py; "pct": 1.0); NaN -> entry skipped.
  SL        level = avg*(1 - sl*unit/100)
  TP        level = avg*(1 + tp*unit/100) -> reduce-only LIMIT SELL (maker fee, fills at the level)
  trailing  NATIVE reduce-only TRAILING_STOP_MARKET (offset type BASIS_POINTS = trail*unit*100, activation_price = avg*(1+act*unit/100)) next to the SL
            STOP_MARKET: the matching engine ratchets the trigger tick by tick over each 1m bar's O,H,L,C ticks = Nora's intrabar "ohlc" path (the bar's own high
            raises the peak before its low is tested). A first attempt that emulated it on the 1m stream (modify a single stop after each bar) differed on the
            trades where one 1m bar both set a new high and fell trail% from it (Nora exits inside that bar) - see EXT_REPORT S10.
  timeout   after the 1m bar whose close time - entry time >= timeout minutes: cancel stops + market SELL at that bar's close (= Nora: market at the next bar open).
Run from nora/: systemd-run --user --scope --slice=nora.slice -p MemoryMax=6G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/s10_run_nautilus.py [stages|all]
Writes out/s10/nautilus_<stage>.json.
"""
import json
import os
import sys
from decimal import Decimal

import numpy as np
import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.common import LogLevel
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (AccountType, Bar, BarType, BookType, Currency, Money, OmsType, OrderSide, Quantity, TraderId, TrailingOffsetType, Venue)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s10_common import CAPITAL, FRAME_MS, MAKER, OUT, PORT, STAGES, SYMS, TAKER  # noqa: E402
from ext_run_nautilus import build_trades, inst_id, make_instrument      # noqa: E402
from backend.models import position_size as npolicy                        # noqa: E402

USDT = Currency.from_str("USDT")
VENUE = Venue("OKX")
MIN_NS = 60_000_000_000
M = 60_000


def bt(sym, frame):
    n = 1 if frame == "m" else int(frame[:-1])
    return BarType.from_str(f"{sym}USDT-PERP.OKX-{n}-{'MINUTE' if frame == 'm' else 'HOUR'}-LAST-EXTERNAL")


class S10Config(StrategyConfig):
    def __init__(self, **_kw):
        super().__init__()


class Sym:
    def __init__(self, sym, ent, atr_close, natr):
        self.sym, self.ent, self.atr_close, self.natr = sym, ent, atr_close, natr
        self.nb = 0
        self.last_close = float("nan")
        self.live = False
        self.closing = False
        self.closed_bar = -1
        self.qty_plan = self.reserved = self.fees_open = 0.0
        self.entry_equities = []
        self.fills = []
        self.stop_id = None
        self.stop_kind = "SL"
        self.stop_px = None
        self.avg = self.peak = self.unit = 0.0
        self.entry_ms = 0
        self.units = []


class S10Strategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, cfg, data):
        super().__init__(config)
        self.cfg = cfg
        self.S = {s: Sym(s, *data[s]) for s in SYMS}
        self.by_inst = {str(inst_id(s)): s for s in SYMS}
        self.kind = {}
        self.admit_log = []
        self.fms = FRAME_MS[cfg["frame"]]
        self.t_first = int(pd.read_csv(os.path.join(OUT, f"bars1m_{SYMS[0]}.csv")).open_time.iloc[0])

    def on_start(self):
        self.inst = {s: self.cache.instrument(inst_id(s)) for s in SYMS}
        for s in SYMS:
            self.subscribe_bars(bt(s, "m"))
            self.subscribe_bars(bt(s, self.cfg["frame"]))

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
        rec = {"stray": False, "t": int(event.ts_event) // 1_000_000, "side": "BUY" if event.is_buy else "SELL", "px": px, "qty": qty, "fee": fee,
               "liq": str(event.liquidity_side), "kind": kind, "bar": st.nb, "equity_after": self.bal(), "sym": sym}
        st.fills.append(rec)
        st.fees_open += fee
        iid = inst_id(sym)
        if kind == "ENTRY":
            st.reserved += qty * px / self.cfg["lev"] + fee
            pos = self.cache.positions_open(instrument_id=iid)[0]
            st.avg = st.peak = float(pos.avg_px_open)
            st.entry_ms = rec["t"]
            c = self.cfg
            if c["sl"]:
                sl_lv = st.avg * (1.0 - 1.0 * (c["sl"] * st.unit) / 100.0)
                o = self.order_factory.stop_market(iid, OrderSide.SELL, pos.quantity, self.inst[sym].make_price(sl_lv), reduce_only=True)
                self.kind[str(o.client_order_id)] = "SL"
                self.submit_order(o)
            if c["trail"]:
                kw = {}
                if c["act"]:
                    kw["activation_price"] = self.inst[sym].make_price(st.avg * (1.0 + 1.0 * (c["act"] * st.unit) / 100.0))
                o = self.order_factory.trailing_stop_market(iid, OrderSide.SELL, pos.quantity, Decimal(str(round(c["trail"] * st.unit * 100.0, 9))),
                                                            trailing_offset_type=TrailingOffsetType.BASIS_POINTS, reduce_only=True, **kw)
                self.kind[str(o.client_order_id)] = "TRAIL"
                self.submit_order(o)
            if c["tp"]:
                tp_lv = st.avg * (1.0 + 1.0 * (c["tp"] * st.unit) / 100.0)
                o = self.order_factory.limit(iid, OrderSide.SELL, pos.quantity, self.inst[sym].make_price(tp_lv), reduce_only=True)
                self.kind[str(o.client_order_id)] = "TP"
                self.submit_order(o)
        elif kind != "?" and not self.cache.positions_open(instrument_id=iid):
            rec["adj"] = []
            self.cancel_all_orders(iid)
            if kind != "ENTRY":
                st.closed_bar = st.nb
            st.live = st.closing = False
            st.qty_plan = st.reserved = st.fees_open = 0.0
            st.stop_id = None

    def on_bar(self, bar):
        sym = self.by_inst[str(bar.bar_type.instrument_id)]
        st = self.S[sym]
        if bar.bar_type.spec.aggregation.name == "MINUTE":
            st.nb += 1
            st.last_close = float(bar.close)
            if st.live and not st.closing:
                self._manage(st, sym, bar)
            return
        k = SYMS.index(sym)
        self.clock.set_time_alert_ns(f"act-{sym}-{int(bar.ts_event)}", int(bar.ts_init) + 1 + k, self._on_alert)

    def _manage(self, st, sym, bar):
        c = self.cfg
        iid = inst_id(sym)
        if not self.cache.positions_open(instrument_id=iid):
            return
        close_ms = int(bar.ts_event) // 1_000_000                      # = this bar's open + 1m = Nora's next bar open
        if c["timeout"] and close_ms - st.entry_ms >= c["timeout"] * M:
            self.clock.set_time_alert_ns(f"to-{sym}-{close_ms}", int(bar.ts_init) + 1 + SYMS.index(sym), self._on_alert)
            st.closing = True
            return

    def _on_alert(self, event):
        parts = str(event.name).split("-")
        if parts[0] == "to":
            st = self.S[parts[1]]
            iid = inst_id(st.sym)
            if not st.live or not self.cache.positions_open(instrument_id=iid):
                st.closing = False
                return
            self.cancel_all_orders(iid)
            pos = self.cache.positions_open(instrument_id=iid)[0]
            o = self.order_factory.market(iid, OrderSide.SELL, pos.quantity, reduce_only=True)
            self.kind[str(o.client_order_id)] = "TO"
            st.live = False
            self.submit_order(o)
            return
        self._enter(self.S[parts[1]], int(parts[2]))

    def _enter(self, st, ts_ns):
        sym, c = st.sym, self.cfg
        i = st.nb - 1
        iid = inst_id(sym)
        close_ms = ts_ns // 1_000_000
        k = (close_ms - self.fms - self.t_first) // self.fms          # signal-bar index
        if st.live or not st.ent[k] or st.closed_bar == i:
            return
        if c["unit"] == "atr":
            j = int(np.searchsorted(st.atr_close, close_ms, side="right")) - 1     # last atr candle closed at the entry instant
            unit = float(st.natr[j]) if j >= 0 else float("nan")
            if not (unit > 0.0):
                return
        else:
            unit = 1.0
        eq = self.eq_nora()
        n_open = sum(1 for s in self.S.values() if s.live)
        gross = 0.0
        if n_open < int(PORT["max_positions"]):
            gross = sum(s.qty_plan * s.last_close for s in self.S.values() if s.live)
        adm = npolicy.admit_entry(n_open, 0, eq, eq, gross, 0.0, PORT["max_positions"], PORT["max_per_symbol"], PORT["max_gross_exposure"], 0.0, 0.0)
        self.admit_log.append([close_ms, sym, adm.can_open, n_open])
        if not adm.can_open:
            return
        reserved = sum(s.reserved for s in self.S.values() if s.live)
        margin = npolicy.clamp_margin(npolicy.flat_margin(eq, c["osp"]), min(eq, eq - reserved), float(c["lev"]), TAKER, adm.max_new_notional)
        if margin <= 0:
            return
        qty = self.inst[sym].make_qty(margin * c["lev"] / st.last_close)
        st.entry_equities.append(eq)
        st.units.append(unit if c["unit"] == "atr" else 0.0)
        st.unit = unit
        st.live, st.closing, st.qty_plan, st.reserved, st.fees_open = True, False, float(qty), 0.0, 0.0
        o = self.order_factory.market(iid, OrderSide.BUY, qty)
        self.kind[str(o.client_order_id)] = "ENTRY"
        self.submit_order(o)


def run_one(stname):
    st = STAGES[stname]
    cfg = dict(st, mmr=0.005)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-010"), risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(st["lev"]), book_type=BookType.L1_MBP, bar_execution=True,
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))))
    fr, fms, afr = st["frame"], FRAME_MS[st["frame"]], st["atr_frame"]
    m, sg, data, insts = {}, {}, {}, {}
    for sym in SYMS:
        insts[sym] = make_instrument(sym, cfg)
        engine.add_instrument(insts[sym])
        m[sym] = pd.read_csv(os.path.join(OUT, f"bars1m_{sym}.csv"))
        sg[sym] = pd.read_csv(os.path.join(OUT, f"sig_{fr}_{sym}.csv"))
        at = pd.read_csv(os.path.join(OUT, f"atr_{afr}_{sym}.csv"))
        data[sym] = (sg[sym][f"ent_{stname}"].values.astype(bool), at.open_time.values.astype("int64") + FRAME_MS[afr], at.natr14.values)
    vol = insts[SYMS[0]].make_qty(1000)
    n = len(m[SYMS[0]])
    per = fms // M
    arr = {s: [m[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    sarr = {s: [sg[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    items = []
    for i in range(n):
        for s in SYMS:
            t, o, h, l, c = (a[i] for a in arr[s])
            ts = int(t) * 1_000_000 + MIN_NS
            p = insts[s].make_price
            items.append(Bar(bt(s, "m"), p(o), p(h), p(l), p(c), vol, ts, ts))
        if (i + 1) % per == 0:
            j = (i + 1) // per - 1
            for s in SYMS:
                t, o, h, l, c = (a[j] for a in sarr[s])
                ts = int(t) * 1_000_000 + fms * 1_000_000
                p = insts[s].make_price
                items.append(Bar(bt(s, fr), p(o), p(h), p(l), p(c), vol, ts, ts))
    engine.add_data(items)
    strat = S10Strategy(S10Config(), cfg, data)
    engine.add_strategy(strat)
    engine.run()
    acct = engine.portfolio.account(VENUE)
    res = {"stage": stname, "trades": [], "open_at_end": [], "admit_log": strat.admit_log}
    all_trades = []
    for sym in SYMS:
        ss = strat.S[sym]
        fl = [dict(f, is_entry=f["side"] == "BUY") for f in ss.fills]
        trades, cur = build_trades(fl, ss.entry_equities, 1)
        for t, u in zip(trades, ss.units):
            t["sym"], t["unit_pct"] = sym, u
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
        from collections import Counter
        print(name, "trades", len(r["trades"]), dict(Counter(t["reason"] for t in r["trades"])), "realized(nora def)", round(r["realized_equity_nora_def"], 4),
              "open_at_end", len(r["open_at_end"]), flush=True)


if __name__ == "__main__":
    main()
