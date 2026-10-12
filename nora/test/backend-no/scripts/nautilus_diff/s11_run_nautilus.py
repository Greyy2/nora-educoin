"""S11 Nautilus side: BacktestEngine (L1 bar execution, NETTING MARGIN), per instrument 1-MINUTE-LAST-EXTERNAL (matching) + 1-HOUR-LAST-EXTERNAL (signal, ts on
close). Same architecture as s9_run_nautilus.py (acts only in the 1h on_bar via a +k ns alert; entry = market at the 1h close; SL = reduce-only STOP_MARKET
from the average price, re-placed after every DCA fill) plus:
 (a) cooldown: entry at boundary T_e is skipped (and LOST) iff cool>0 and (T_e - 1min) - C < cool, C = Nora numbering of the last close
     (SL: open_time of the 1m bar being matched; signal exit: its boundary).
 (b) DCA: resting post-only-style LIMIT ladder placed on the entry fill (all layers up front, each chained from the planned fill price, margin_j = margin_(j-1)*mult_j,
     qty = margin_j*lev/price) as ext_run_nautilus.py S3; fills as maker. limit_through_pct = 0 (touch fills) in this scenario.
 (c) funding: Nautilus has no native funding cash flow in a bar backtest. Applied in the strategy as a SHADOW LEDGER (documented in README/EXT_REPORT): on each 1m
     on_bar (bar close ts == Nora bar open t) every funding row with t_apply = ceil(funding_time/1min)*1min <= t is charged to the position that is open at that moment
     (entry submitted at the same instant is not yet open, an exit at the same instant still is) with payment = qty*close(prev bar)*rate*sign (price = Nora open[t] on
     the ALIGNED data). The shadow total reduces the sizing equity exactly as Nora's ledger (eq_nora = balance + open entry fees - funding paid) and the trade pnl
     (pnl = gross - fees - funding); the Nautilus account itself is not touched.
Run from nora/: systemd-run --user --scope --slice=nora.slice -p MemoryMax=6G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/s11_run_nautilus.py [stages|all]
Writes out/s11/nautilus_<stage>.json.
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
from nautilus_trader.model import (AccountType, Bar, BarType, BookType, ClientOrderId, Currency, Money, OmsType, OrderSide, TimeInForce,
                                   TraderId, Venue)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from s11_common import CAPITAL, HOUR, M, MAKER, OUT, PORT, STAGES, SYMS, TAKER, dca_lists  # noqa: E402
from ext_run_nautilus import build_trades, inst_id, make_instrument      # noqa: E402
from backend.models import position_size as npolicy                        # noqa: E402

USDT = Currency.from_str("USDT")
VENUE = Venue("OKX")
MIN_NS = 60_000_000_000
HOUR_NS = HOUR * 1_000_000


def bt(sym, kind):
    return BarType.from_str(f"{sym}USDT-PERP.OKX-1-{'MINUTE' if kind == 'm' else 'HOUR'}-LAST-EXTERNAL")


class S11Config(StrategyConfig):
    def __init__(self, **_kw):
        super().__init__()


class Sym:
    def __init__(self, sym, ent, ext, fund_t, fund_r):
        self.sym, self.ent, self.ext = sym, ent, ext
        self.fund_t, self.fund_r, self.fi = fund_t, fund_r, 0
        self.nb = 0
        self.hour = 0
        self.last_close = float("nan")
        self.live = False
        self.closing = False
        self.closed_bar = -1
        self.last_close_t = None     # Nora numbering (ms) of the last close, for the cooldown
        self.qty_plan = 0.0
        self.reserved = 0.0
        self.fees_open = 0.0
        self.fund_pos = 0.0          # funding paid by the current position
        self.fund_total = 0.0        # all funding paid so far (closed + open)
        self.entry_equity = CAPITAL
        self.entry_equities = []
        self.entry_margin = 0.0
        self.fills = []
        self.dca_ids, self.prot_ids = [], []
        self.layer_of = {}
        self.cool_skips = 0


class S11Strategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, cfg, sigs, t_first):
        super().__init__(config)
        self.cfg = cfg
        self.t_first = t_first
        self.side = 1.0 if cfg["side"] == "L" else -1.0
        self.entry_side = OrderSide.BUY if self.side > 0 else OrderSide.SELL
        self.exit_side = OrderSide.SELL if self.side > 0 else OrderSide.BUY
        self.steps, self.mults = dca_lists(cfg)
        self.S = {s: Sym(s, *sigs[s]) for s in SYMS}
        self.by_inst = {str(inst_id(s)): s for s in SYMS}
        self.kind = {}
        self.admit_log = []
        self.acts = []
        self.h0 = int(pd.read_csv(os.path.join(OUT, f"hourly_{SYMS[0]}.csv")).open_time.iloc[0]) // HOUR
        self.funding_log = []

    def on_start(self):
        self.inst = {s: self.cache.instrument(inst_id(s)) for s in SYMS}
        for s in SYMS:
            self.subscribe_bars(bt(s, "m"))
            self.subscribe_bars(bt(s, "h"))

    def bal(self):
        return float(self.portfolio.account(VENUE).balance_total(USDT).as_double())

    def eq_nora(self):
        return self.bal() + sum(st.fees_open for st in self.S.values() if st.live) - sum(st.fund_total for st in self.S.values())

    def _px(self, sym, v):
        return self.inst[sym].make_price(v)

    def _qty(self, sym, v):
        return self.inst[sym].make_qty(v)

    def _position(self, sym):
        pos = self.cache.positions_open(instrument_id=inst_id(sym))
        return pos[0] if pos else None

    def _submit(self, st, order, kind):
        self.kind[str(order.client_order_id)] = kind
        if kind == "SL":
            st.prot_ids.append(str(order.client_order_id))
        self.submit_order(order)

    def _place_sl(self, st):
        pos = self._position(st.sym)
        if pos is None:
            return
        for oid in st.prot_ids:
            o = self.cache.order(ClientOrderId(oid))
            if o is not None and not o.is_closed:
                self.cancel_order(o.client_order_id)
        st.prot_ids = []
        avg = float(pos.avg_px_open)
        self._submit(st, self.order_factory.stop_market(inst_id(st.sym), self.exit_side, pos.quantity,
                                                        self._px(st.sym, avg * (1 - self.side * self.cfg["sl"] / 100.0)), reduce_only=True), "SL")

    def _arm_dca(self, st, px, margin, k):
        c = self.cfg
        for j in range(k, len(self.steps)):
            px = px * (1 - self.side * self.steps[j] / 100.0)
            margin = margin * self.mults[j]
            o = self.order_factory.limit(inst_id(st.sym), self.entry_side, self._qty(st.sym, margin * c["lev"] / px), self._px(st.sym, px),
                                         time_in_force=TimeInForce.GTC)
            st.dca_ids.append(str(o.client_order_id))
            st.layer_of[str(o.client_order_id)] = (j, float(self._px(st.sym, px)), margin)
            self._submit(st, o, "DCA")

    def on_order_filled(self, event):
        coid = str(event.client_order_id)
        sym = self.by_inst[str(event.instrument_id)]
        st = self.S[sym]
        kind = self.kind.get(coid, "?")
        fee = float(event.commission.as_double()) if event.commission else 0.0
        px, qty = float(event.last_px), float(event.last_qty)
        t_ms = int(event.ts_event) // 1_000_000
        bar = st.nb if kind in ("SL", "DCA") else st.hour * 60 + 59 + 0      # unused for SIG/ENTRY (time = event ts)
        stray = kind == "DCA" and not st.live
        if stray:
            st.live, st.qty_plan, st.reserved, st.fees_open, st.fund_pos = True, 0.0, 0.0, 0.0, 0.0
            st.entry_equities.append(self.bal() + fee)
        rec = {"stray": stray, "t": t_ms, "side": "BUY" if event.is_buy else "SELL", "px": px, "qty": qty, "fee": fee,
               "liq": str(event.liquidity_side), "kind": kind, "bar": bar, "equity_after": self.bal(), "sym": sym}
        st.fills.append(rec)
        st.fees_open += fee
        is_entry_side = event.is_buy == (self.side > 0)
        if is_entry_side:
            st.reserved += qty * px / self.cfg["lev"] + fee
            if kind != "ENTRY":
                st.qty_plan += qty
        if kind == "ENTRY":
            self._place_sl(st)
            if self.steps:
                self._arm_dca(st, px, st.entry_margin, 0)
        elif kind == "DCA":
            j, planned_px, margin = st.layer_of[coid]
            self._place_sl(st)
            if abs(px - planned_px) > 1e-9:
                for oid in [o for o in st.dca_ids if o != coid]:
                    o = self.cache.order(ClientOrderId(oid))
                    if o is not None and not o.is_closed:
                        self.cancel_order(o.client_order_id)
                self._arm_dca(st, px, margin, j + 1)
        if kind in ("SL", "SIG") and self._position(sym) is None:
            rec["adj"] = []
            rec["funding"] = st.fund_pos
            self.cancel_all_orders(inst_id(sym))
            if kind == "SL":
                st.closed_bar = st.nb
                st.last_close_t = self.t_first + st.nb * M
            else:
                st.last_close_t = t_ms
            st.live = st.closing = False
            st.qty_plan = st.reserved = st.fees_open = st.fund_pos = 0.0
            st.dca_ids, st.prot_ids = [], []

    def on_bar(self, bar):
        sym = self.by_inst[str(bar.bar_type.instrument_id)]
        st = self.S[sym]
        if bar.bar_type.spec.aggregation.name == "MINUTE":
            st.nb += 1
            st.last_close = float(bar.close)
            t = int(bar.ts_event) // 1_000_000          # == Nora open_time of the NEXT 1m bar
            while st.fi < len(st.fund_t) and st.fund_t[st.fi] <= t:
                pos = self._position(sym)
                if pos is not None:
                    pay = float(pos.quantity) * float(bar.close) * float(st.fund_r[st.fi]) * self.side
                    st.fund_pos += pay
                    st.fund_total += pay
                    self.funding_log.append([sym, t, int(st.fund_t[st.fi]), float(pos.quantity), float(bar.close), float(st.fund_r[st.fi]), pay])
                st.fi += 1
            return
        st.hour = int(bar.ts_event) // HOUR_NS - 1 - self.h0
        k = SYMS.index(sym)
        self.clock.set_time_alert_ns(f"act-{sym}-{st.hour}", int(bar.ts_init) + 1 + k, self._on_alert)

    def _on_alert(self, event):
        _, sym, h = str(event.name).split("-")
        self._act(self.S[sym], int(h))

    def _act(self, st, h):
        sym, c = st.sym, self.cfg
        i = st.nb - 1
        iid = inst_id(sym)
        if st.live:
            if st.closing or self._position(sym) is None:
                return
            if st.ext[h]:
                self.cancel_all_orders(iid)
                st.closing = True
                self.acts.append([h, sym, "exit"])
                o = self.order_factory.market(iid, self.exit_side, self._position(sym).quantity, reduce_only=True)
                self.kind[str(o.client_order_id)] = "SIG"
                st.live = False
                self.submit_order(o)
        elif st.ent[h] and st.closed_bar != i:
            t_e = self.t_first + st.nb * M                           # entry boundary = open_time of the next 1m bar
            if c["cool"] > 0 and st.last_close_t is not None and (t_e - M) - st.last_close_t < c["cool"] * M:
                st.cool_skips += 1
                return
            eq = self.eq_nora()
            n_open = sum(1 for s in self.S.values() if s.live)
            gross = 0.0
            if n_open < int(PORT["max_positions"]):
                gross = sum(s.qty_plan * s.last_close for s in self.S.values() if s.live)
            adm = npolicy.admit_entry(n_open, 0, eq, eq, gross, 0.0, PORT["max_positions"], PORT["max_per_symbol"], PORT["max_gross_exposure"], 0.0, 0.0)
            self.admit_log.append([h, sym, adm.can_open, n_open, gross, eq, adm.max_new_notional])
            if not adm.can_open:
                return
            reserved = sum(s.reserved for s in self.S.values() if s.live)
            margin = npolicy.clamp_margin(npolicy.flat_margin(eq, c["osp"]), min(eq, eq - reserved), float(c["lev"]), TAKER, adm.max_new_notional)
            if margin <= 0:
                return
            qty = self._qty(sym, margin * c["lev"] / st.last_close)
            st.entry_margin, st.entry_equity = margin, eq
            st.entry_equities.append(eq)
            st.live, st.qty_plan, st.reserved, st.fees_open, st.fund_pos = True, float(qty), 0.0, 0.0, 0.0
            self.acts.append([h, sym, "enter"])
            o = self.order_factory.market(iid, self.entry_side, qty)
            self.kind[str(o.client_order_id)] = "ENTRY"
            self.submit_order(o)


def run_one(stname):
    st = STAGES[stname]
    cfg = dict(st, mmr=0.005)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-011"), risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(st["lev"]), book_type=BookType.L1_MBP, bar_execution=True,
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))))
    m, hr, sigs, insts = {}, {}, {}, {}
    for sym in SYMS:
        insts[sym] = make_instrument(sym, cfg)
        engine.add_instrument(insts[sym])
        m[sym] = pd.read_csv(os.path.join(OUT, f"bars1m_{sym}.csv"))
        hr[sym] = pd.read_csv(os.path.join(OUT, f"hourly_{sym}.csv"))
        fu = pd.read_csv(os.path.join(OUT, f"funding_{sym}.csv"))
        t_ap = ((fu.funding_time.values + M - 1) // M) * M          # first 1m bar open_time >= funding_time
        sigs[sym] = (hr[sym][f"ent_{stname}"].values.astype(bool), hr[sym][f"ext_{stname}"].values.astype(bool), t_ap, fu.rate.values)
    t_first = int(m[SYMS[0]].open_time.iloc[0])
    vol = insts[SYMS[0]].make_qty(1000)
    items = []
    n = len(m[SYMS[0]])
    arr = {s: [m[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    harr = {s: [hr[s][c].values for c in ("open_time", "open", "high", "low", "close")] for s in SYMS}
    for i in range(n):
        for s in SYMS:
            t, o, h, l, c = (a[i] for a in arr[s])
            ts = int(t) * 1_000_000 + MIN_NS
            p = insts[s].make_price
            items.append(Bar(bt(s, "m"), p(o), p(h), p(l), p(c), vol, ts, ts))
        if (i + 1) % 60 == 0:
            j = (i + 1) // 60 - 1
            for s in SYMS:
                t, o, h, l, c = (a[j] for a in harr[s])
                ts = int(t) * 1_000_000 + HOUR_NS
                p = insts[s].make_price
                items.append(Bar(bt(s, "h"), p(o), p(h), p(l), p(c), vol, ts, ts))
    engine.add_data(items)
    strat = S11Strategy(S11Config(), cfg, sigs, t_first)
    engine.add_strategy(strat)
    engine.run()
    acct = engine.portfolio.account(VENUE)
    res = {"stage": stname, "trades": [], "open_at_end": [], "admit_log": strat.admit_log, "acts": strat.acts, "funding_log": strat.funding_log,
           "cool_skips": {s: strat.S[s].cool_skips for s in SYMS}}
    all_trades = []
    for sym in SYMS:
        ss = strat.S[sym]
        fl = []
        for f in ss.fills:
            f = dict(f)
            f["is_entry"] = (f["side"] == "BUY") == (strat.side > 0)
            fl.append(f)
        trades, cur = build_trades(fl, ss.entry_equities, int(strat.side))
        for t in trades:
            t["sym"] = sym
            t["funding"] = t["fills"][-1].get("funding", 0.0)
            t["pnl"] = t["pnl_trade"] - t["funding"]
            t["layers"] = sum(1 for f in t["fills"] if f["is_entry"])
        all_trades += trades
        if cur is not None:
            res["open_at_end"].append({"sym": sym, "enter_time": cur["enter_time"], "fees_open": cur["fees"], "funding": ss.fund_pos})
    all_trades.sort(key=lambda t: (t["enter_time"], t["sym"]))
    res["trades"] = all_trades
    ftot = sum(strat.S[s].fund_total for s in SYMS)
    res["final_equity"] = float(acct.balance_total(USDT).as_double())
    res["funding_total_all"] = ftot
    res["realized_equity_nora_def"] = res["final_equity"] + sum(o["fees_open"] for o in res["open_at_end"]) - ftot
    engine.dispose()
    return res


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    for name in only:
        r = run_one(name)
        json.dump(r, open(os.path.join(OUT, f"nautilus_{name}.json"), "w"))
        print(name, "trades", len(r["trades"]), "realized(nora def)", round(r["realized_equity_nora_def"], 4), "open_at_end", len(r["open_at_end"]),
              "cool_skips", r["cool_skips"], "funding", round(sum(t["funding"] for t in r["trades"]), 4), flush=True)


if __name__ == "__main__":
    main()
