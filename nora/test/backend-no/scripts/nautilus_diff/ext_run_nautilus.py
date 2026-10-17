"""Nautilus side of the extended differential test (S4-S8): BacktestEngine, L1 bar execution, NETTING MARGIN venue, default leverage = stage
leverage, liquidation_enabled for S5, FundingRateUpdate data for S7, three instruments on one account for S8.
Writes out/ext/nautilus_<ds>_<signal>_<stage>_<path>.json with every fill, the reconstructed trades (incl. funding adjustments) and balances.
Run with the nautilus venv from nora/:
  systemd-run --user --scope --slice=nora.slice -p MemoryMax=4G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/ext_run_nautilus.py [ohlc|adaptive] [stages|all] [datasets|all] [signals|all]
(path "ohlc" = Nautilus default O->H->L->C; "adaptive" = bar_adaptive_high_low_ordering=True.)
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
from nautilus_trader.model import (AccountType, Bar, BarType, BookType, ClientOrderId, Currency, CryptoPerpetual, FundingRateUpdate,
                                   InstrumentId, Money, OmsType, OrderSide, Price, QuoteTick, Quantity, Symbol, TimeInForce, TraderId,
                                   TrailingOffsetType, Venue)
from nautilus_trader.trading import Strategy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NORA = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, NORA)
from ext_common import skip, CAPITAL, DATASETS, MAKER, OUT, SIGNALS, STAGES, TAKER, tag  # noqa: E402
# Nora's own pure functions (no numba / no I/O): the pre-trade risk caps and the sizing clamp, used verbatim as the "same formulas"
from backend.analys.position import position_size as npolicy  # noqa: E402
from backend.analys.position import position_size as nrisk      # noqa: E402

USDT = Currency.from_str("USDT")
BASES = {"BTC": Currency.from_str("BTC"), "ETH": Currency.from_str("ETH"), "SOL": Currency.from_str("SOL")}
VENUE = Venue("OKX")
HOUR_NS = 3_600_000_000_000
PP, SP = 8, 8                                   # "fine" precision: rounding negligible (rounding effects were covered by S1-S3 `okx` config)


def inst_id(sym):
    return InstrumentId(Symbol(f"{sym}USDT-PERP"), VENUE)


def bar_type(sym):
    return BarType.from_str(f"{sym}USDT-PERP.OKX-1-HOUR-LAST-EXTERNAL")


def make_instrument(sym, st):
    # LeveragedMarginModel: maintenance = notional / leverage * margin_maint  ->  margin_maint = mmr * leverage gives maintenance = notional * mmr
    maint = Decimal(str(round(st["mmr"] * st["lev"], 10)))
    return CryptoPerpetual(
        instrument_id=inst_id(sym), raw_symbol=Symbol(f"{sym}USDT-PERP"), base_currency=BASES[sym], quote_currency=USDT,
        settlement_currency=USDT, is_inverse=False, price_precision=PP, size_precision=SP,
        price_increment=Price.from_str(f"{10 ** -PP:.{PP}f}"), size_increment=Quantity.from_str(f"{10 ** -SP:.{SP}f}"),
        ts_event=0, ts_init=0, margin_init=Decimal("0.01"), margin_maint=maint)


class ExtConfig(StrategyConfig):
    def __init__(self, **_kw):
        super().__init__()


class SymState:
    def __init__(self, sym, entry, exit_):
        self.sym, self.entry, self.exit_ = sym, entry, exit_
        self.nb = 0                    # bars of this instrument dispatched so far (== index of the bar whose ticks are being matched)
        self.closed_bar = -1           # Nora-equivalent bar index in which the last position closed (entry signal on that bar is ignored)
        self.sig_inflight = False
        self.live = False              # position open or entry submitted (strategy-side flag; orders are queued, fills come after on_bar returns)
        self.qty_plan = 0.0            # position quantity (planned at entry submit, then actual fills)
        self.reserved = 0.0            # Nora Account.reserved share: sum(layer margin + layer entry fee)
        self.fees_open = 0.0           # fees paid on the open position so far (Nora books them into equity only at close)
        self.entry_i = -1              # on_bar index at which the entry was submitted (timeout base)
        self.entry_equity = CAPITAL
        self.entry_equities = []
        self.entry_margin = 0.0
        self.act_i = -1
        self.sig_bar = -1
        self.fills = []
        self.dca_ids, self.prot_ids = [], []
        self.layer_of = {}
        self.dca_state = None
        self.last_close = float("nan")
        self.open_adj = []


class ExtStrategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, cfg, syms, sigs, delay):
        super().__init__(config)
        self.cfg, self.syms, self.delay = cfg, list(syms), delay
        self.S = {s: SymState(s, sigs[s][0], sigs[s][1]) for s in syms}
        self.by_inst = {str(inst_id(s)): s for s in syms}
        self.kind = {}                 # client_order_id -> kind
        self.arrived = {}
        self.side = 1.0 if cfg["side"] == "L" else -1.0
        self.entry_side = OrderSide.BUY if self.side > 0 else OrderSide.SELL
        self.exit_side = OrderSide.SELL if self.side > 0 else OrderSide.BUY
        self.admit_log = []            # [bar, sym, can_open, n_open, gross, eq, max_new_notional]

    def on_start(self):
        self.inst = {s: self.cache.instrument(inst_id(s)) for s in self.syms}
        for s in self.syms:
            self.subscribe_bars(bar_type(s))

    # ── helpers ──
    def bal(self):
        return float(self.portfolio.account(VENUE).balance_total(USDT).as_double())

    def eq_nora(self):
        """Nora ledger equity = realised equity: Nautilus balance + entry fees of positions still open (Nora books them at close)."""
        return self.bal() + sum(st.fees_open for st in self.S.values() if st.live)

    def _px(self, sym, v):
        return self.inst[sym].make_price(v)

    def _qty(self, sym, v):
        return self.inst[sym].make_qty(v)

    def _position(self, sym):
        pos = self.cache.positions_open(instrument_id=inst_id(sym))
        return pos[0] if pos else None

    def _submit(self, st, order, kind):
        self.kind[str(order.client_order_id)] = kind
        if kind in ("SL", "TP", "TRAIL"):
            st.prot_ids.append(str(order.client_order_id))
        self.submit_order(order)

    def _place_protection(self, st):
        sym = st.sym
        pos = self._position(sym)
        if pos is None:
            return
        avg, qty = float(pos.avg_px_open), pos.quantity
        for oid in st.prot_ids:                      # cancel ONLY the previous SL/TP (never the resting DCA ladder / trailing)
            if self.kind.get(oid) == "TRAIL":
                continue
            o = self.cache.order(ClientOrderId(oid))
            if o is not None and not o.is_closed:
                self.cancel_order(o.client_order_id)
        st.prot_ids = [o for o in st.prot_ids if self.kind.get(o) == "TRAIL"]
        c, s, iid = self.cfg, self.side, inst_id(sym)
        if c.get("sl"):
            self._submit(st, self.order_factory.stop_market(iid, self.exit_side, qty, self._px(sym, avg * (1 - s * c["sl"] / 100.0)),
                                                            reduce_only=True), "SL")
        if c.get("tp"):
            self._submit(st, self.order_factory.limit(iid, self.exit_side, qty, self._px(sym, avg * (1 + s * c["tp"] / 100.0)),
                                                      reduce_only=True, time_in_force=TimeInForce.GTC), "TP")

    def _place_trail(self, st, avg_px, qty):
        c, s, sym = self.cfg, self.side, st.sym
        act = None
        if c.get("trail_act"):
            act = self._px(sym, avg_px * (1 + s * c["trail_act"] / 100.0))
        self._submit(st, self.order_factory.trailing_stop_market(
            inst_id(sym), self.exit_side, qty, Decimal(str(round(c["trail"] * 100.0, 8))), TrailingOffsetType.BASIS_POINTS,
            activation_price=act, reduce_only=True), "TRAIL")

    def _arm_next_dca(self, st):
        c, s = self.cfg, self.side
        steps, mults = c.get("dca_steps", []), c.get("dca_mults", [])
        px, margin, k = st.dca_state
        for j in range(k, len(steps)):               # resting ladder: every remaining layer up front, each chained from the PLANNED fill
            px = px * (1 - s * steps[j] / 100.0)
            margin = margin * mults[j]
            o = self.order_factory.limit(inst_id(st.sym), self.entry_side, self._qty(st.sym, margin * c["lev"] / px), self._px(st.sym, px),
                                         time_in_force=TimeInForce.GTC)
            st.dca_ids.append(str(o.client_order_id))
            st.layer_of[str(o.client_order_id)] = (j, float(self._px(st.sym, px)), margin)
            self._submit(st, o, "DCA")

    # ── events ──
    def on_order_filled(self, event):
        coid = str(event.client_order_id)
        sym = self.by_inst[str(event.instrument_id)]
        st = self.S[sym]
        kind = self.kind.get(coid, "LIQ" if coid.startswith("LIQUIDATION") else "?")
        is_entry_side = event.is_buy == (self.side > 0)
        fee = float(event.commission.as_double()) if event.commission else 0.0
        px, qty = float(event.last_px), float(event.last_qty)
        # bar index (Nora numbering) of the fill: entry/signal/timeout fills belong to the bar whose on_bar acted (Nora executes them at the
        # open of the NEXT bar); stops/limits to the bar being matched; liquidation (after on_bar) to nb-1
        if kind in ("ENTRY", "SIG", "TIMEOUT"):
            bar = st.act_i
        elif kind == "LIQ":
            bar = st.nb - 1
        else:
            bar = st.nb
        stray = kind == "DCA" and not st.live        # resting DCA limit filled in the same tick AFTER a stop closed the position (cancel is queued)
        if stray:
            st.live, st.qty_plan, st.reserved, st.fees_open, st.entry_i = True, 0.0, 0.0, 0.0, st.nb - 1
            st.entry_equities.append(self.bal() + fee)
        rec = {"stray": stray, "t": int(event.ts_event) // 1_000_000, "side": "BUY" if event.is_buy else "SELL", "px": px, "qty": qty, "fee": fee,
               "liq": str(event.liquidity_side), "kind": kind, "bar": bar, "equity_after": self.bal(), "sym": sym}
        st.fills.append(rec)
        st.fees_open += fee
        if is_entry_side:
            st.reserved += qty * px / self.cfg["lev"] + fee
            if kind != "ENTRY":
                st.qty_plan += qty
        pos = self._position(sym)
        if kind == "ENTRY":
            self._place_protection(st)
            if self.cfg.get("trail"):
                self._place_trail(st, float(pos.avg_px_open), pos.quantity)
            if self.cfg.get("dca_steps"):
                st.dca_state = (px, st.entry_margin, 0)
                self._arm_next_dca(st)
        elif kind == "DCA":
            j, planned_px, margin = st.layer_of[coid]
            self._place_protection(st)
            if abs(px - planned_px) > 1e-9:          # Nora chains the next level from the ACTUAL fill price: re-ladder the remainder
                for oid in [o for o in st.dca_ids if o != coid]:
                    o = self.cache.order(ClientOrderId(oid))
                    if o is not None and not o.is_closed:
                        self.cancel_order(o.client_order_id)
                st.dca_state = (px, margin, j + 1)
                self._arm_next_dca(st)
        if kind in ("SL", "TP", "TRAIL", "SIG", "TIMEOUT", "LIQ") and pos is None:
            adj = []
            for p in self.cache.positions(instrument_id=inst_id(sym)):
                if p.is_closed:
                    adj = [[int(a.ts_event) // 1_000_000, float(a.pnl_change.as_double())] for a in p.adjustments()]
            rec["adj"] = adj
            self.cancel_all_orders(inst_id(sym))
            st.closed_bar = st.sig_bar if kind in ("SIG", "TIMEOUT") else rec["bar"]
            st.sig_inflight = False
            st.dca_ids, st.prot_ids = [], []
            st.live, st.qty_plan, st.reserved, st.fees_open = False, 0.0, 0.0, 0.0

    def on_bar(self, bar):
        sym = self.by_inst[str(bar.bar_type.instrument_id)]
        st = self.S[sym]
        i = st.nb
        st.nb += 1
        st.last_close = float(bar.close)
        self.arrived[i] = self.arrived.get(i, 0) + 1
        if self.arrived[i] == len(self.syms):        # barrier: all instruments of bar i have closed -> act in Nora's book order
            if self.delay:
                self.clock.set_time_alert_ns(f"act-{i}", int(bar.ts_init) + 1, self._on_alert)
            else:
                self._act_all(i)

    def _on_alert(self, event):
        self._act_all(int(str(event.name).split("-")[1]))

    def _act_all(self, i):
        for sym in self.syms:
            self._act(self.S[sym], i)

    def _act(self, st, i):
        sym, c = st.sym, self.cfg
        st.act_i = i
        iid = inst_id(sym)
        if st.live:
            pos = self._position(sym)
            if pos is None:
                return                                   # entry still queued / just closed by a stop
            kind = "SIG" if st.exit_[i] else ("TIMEOUT" if c.get("timeout") and i - st.entry_i >= c["timeout"] else None)
            if kind:
                self.cancel_all_orders(iid)
                st.sig_inflight = True
                st.sig_bar = i + 1
                st.live = False                           # closing: no longer counts as open for the portfolio caps
                self._submit(st, self.order_factory.market(iid, self.exit_side, pos.quantity, reduce_only=True), kind)
        elif not st.sig_inflight and st.entry[i] and st.closed_bar != i:
            eq = self.eq_nora()
            if eq <= 0:
                return
            port = c.get("port")
            max_new_notional = float("inf")
            if port:
                n_open = sum(1 for s in self.S.values() if s.live)
                per = 0
                gross = 0.0
                if n_open < int(port["max_positions"]) and per < int(port["max_per_symbol"]):
                    gross = sum(s.qty_plan * s.last_close for s in self.S.values() if s.live)
                adm = nrisk.admit_entry(n_open, per, eq, eq, gross, 0.0, port["max_positions"], port["max_per_symbol"],
                                        port["max_gross_exposure"], 0.0, 0.0)
                self.admit_log.append([i, sym, adm.can_open, n_open, gross, eq, adm.max_new_notional])
                if not adm.can_open:
                    return
                max_new_notional = adm.max_new_notional
            reserved = sum(s.reserved for s in self.S.values() if s.live)
            budget = min(eq, eq - reserved)
            margin = npolicy.flat_margin(eq, c["osp"])
            margin = npolicy.clamp_margin(margin, budget, float(c["lev"]), TAKER, max_new_notional)
            if margin <= 0:
                return
            qty = margin * c["lev"] / st.last_close
            st.entry_margin, st.entry_equity, st.entry_i = margin, eq, i
            st.entry_equities.append(eq)
            st.live, st.qty_plan, st.reserved, st.fees_open = True, float(self._qty(sym, qty)), 0.0, 0.0
            self._submit(st, self.order_factory.market(iid, self.entry_side, self._qty(sym, qty)), "ENTRY")

    def on_stop(self):
        for s in self.syms:
            st = self.S[s]
            for p in self.cache.positions_open(instrument_id=inst_id(s)):
                st.open_adj = [[int(a.ts_event) // 1_000_000, float(a.pnl_change.as_double())] for a in p.adjustments()]


def build_trades(fills, entry_equities, side_sign):
    """Fills of ONE instrument -> trades (netting: a trade ends when the position is flat again)."""
    trades, cur = [], None
    eqs = list(entry_equities)
    for f in fills:
        if cur is None:
            cur = {"enter_time": f["t"], "entry": [], "exit": [], "fees": 0.0, "layers": 0, "fills": []}
        cur["fees"] += f["fee"]
        if f["is_entry"]:
            cur["fills"].append(f)
            cur["entry"].append((f["px"], f["qty"]))
            cur["layers"] += 1
        else:
            cur["exit"].append((f["px"], f["qty"]))
            eq_, xq = sum(q for _, q in cur["entry"]), sum(q for _, q in cur["exit"])
            if abs(eq_ - xq) < 1e-12:
                en, ex = sum(p * q for p, q in cur["entry"]), sum(p * q for p, q in cur["exit"])
                adj = f.get("adj", [])
                fund_cash = sum(a[1] for a in adj)         # cash flow: negative = paid
                entry_eq = eqs[len(trades)]
                gross = (ex - en) if side_sign > 0 else (en - ex)
                trades.append({"enter_time": cur["enter_time"], "enter_price": cur["entry"][0][0], "close_time": f["t"],
                               "close_price": ex / xq, "qty": eq_, "avg_price": en / eq_, "fees": cur["fees"],
                               "pnl_trade": gross - cur["fees"], "funding": -fund_cash, "pnl": gross - cur["fees"] + fund_cash,
                               "reason": f["kind"], "entry_equity": entry_eq, "stray": cur["fills"][0]["kind"] != "ENTRY",
                               "layers": cur["layers"], "bar_exit": f["bar"], "equity_after": f["equity_after"],
                               "fills": cur["fills"] + [f], "adj": adj})
                cur = None
    return trades, cur


def load_run(ds, sname, st):
    data = {}
    for sym in st["syms"]:
        bars = pd.read_csv(os.path.join(OUT, f"bars_{sym}_{ds}.csv"))
        sg = pd.read_csv(os.path.join(OUT, f"signals_{sym}.csv"))
        fu = pd.read_csv(os.path.join(OUT, f"funding_{sym}.csv"))
        up, dn = sg[sname + "_up"].values, sg[sname + "_dn"].values
        data[sym] = (bars, (up, dn) if st["side"] == "L" else (dn, up), fu)
    return data


def run_one(ds, sname, stname, path):
    st = STAGES[stname]
    data = load_run(ds, sname, st)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-001"), risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    kw = {}
    if st.get("liq"):
        kw = dict(liquidation_enabled=True, liquidation_trigger_ratio=1.0, liquidation_cancel_open_orders=True)
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(st["lev"]), book_type=BookType.L1_MBP,
                     bar_execution=True, bar_adaptive_high_low_ordering=(path == "adaptive"),
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))), **kw)
    items = []
    for sym in st["syms"]:
        instrument = make_instrument(sym, st)
        engine.add_instrument(instrument)
        bars, _, fu = data[sym]
        vol = instrument.make_qty(1000)
        for t, o, h, l, c in zip(bars.open_time, bars.open, bars.high, bars.low, bars.close):
            ts = int(t) * 1_000_000 + HOUR_NS            # ts_init = ts_event = bar CLOSE
            items.append(Bar(bar_type(sym), instrument.make_price(o), instrument.make_price(h), instrument.make_price(l),
                             instrument.make_price(c), vol, ts, ts))
            if st.get("liq"):
                # Nautilus' liquidation check prices positions from Cache.quote(); a bar-only backtest has none and the check silently defers
                # forever. A bid=ask=close quote right AFTER each bar (same ts, stable sort) makes the bar-close equity check work.
                items.append(QuoteTick(inst_id(sym), instrument.make_price(c), instrument.make_price(c), vol, vol, ts, ts))
        if st.get("fund"):
            open_times = bars.open_time.values
            for ft, rate in zip(fu.funding_time.values, fu.rate.values):
                ft = int(ft)
                if st["fund"] == "bar":
                    # Nora applies funding at the open of the first bar with open_time >= funding_time (before that bar's pending exit/entry)
                    nb_ = open_times[open_times >= ft]
                    if len(nb_) == 0:
                        continue
                    boundary = int(nb_[0]) * 1_000_000
                else:
                    boundary = ft * 1_000_000
                ts = boundary - 1_800_000_000_000
                items.append(FundingRateUpdate(inst_id(sym), Decimal(repr(float(rate))), ts, ts, interval=480, next_funding_ns=boundary))
    engine.add_data(items)
    sigs = {s: data[s][1] for s in st["syms"]}
    strat = ExtStrategy(ExtConfig(), st, st["syms"], sigs, delay=(st.get("fund") == "bar"))
    engine.add_strategy(strat)
    engine.run()
    acct = engine.portfolio.account(VENUE)
    res = {"stage": stname, "path": path, "trades": [], "open_at_end": [], "admit_log": strat.admit_log}
    all_trades = []
    sign = 1 if st["side"] == "L" else -1
    for sym in st["syms"]:
        ss = strat.S[sym]
        fl = []
        for f in ss.fills:
            f = dict(f)
            f["is_entry"] = (f["side"] == "BUY") == (sign > 0)
            fl.append(f)
        trades, cur = build_trades(fl, ss.entry_equities, sign)
        for t in trades:
            t["sym"] = sym
        all_trades += trades
        if cur is not None:
            res["open_at_end"].append({"sym": sym, "enter_time": cur["enter_time"], "fees_open": cur["fees"], "adj": ss.open_adj,
                                       "funding": -sum(a[1] for a in ss.open_adj)})
    all_trades.sort(key=lambda t: (t["enter_time"], t["sym"]))
    res["trades"] = all_trades
    res["final_equity"] = float(acct.balance_total(USDT).as_double())
    res["final_equity_nora_def"] = res["final_equity"] + sum(o["fees_open"] for o in res["open_at_end"])
    engine.dispose()
    return res


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "ohlc"
    only_st = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] != "all" else list(STAGES)
    only_ds = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] != "all" else DATASETS
    only_sig = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] != "all" else SIGNALS
    os.makedirs(OUT, exist_ok=True)
    for ds in only_ds:
        for sname in only_sig:
            for stname in only_st:
                if skip(stname, sname):
                    continue
                r = run_one(ds, sname, stname, path)
                json.dump(r, open(os.path.join(OUT, f"nautilus_{tag(ds, sname, stname, path)}.json"), "w"))
                print(tag(ds, sname, stname, path), "trades", len(r["trades"]), "final", round(r["final_equity_nora_def"], 4), flush=True)


if __name__ == "__main__":
    main()
