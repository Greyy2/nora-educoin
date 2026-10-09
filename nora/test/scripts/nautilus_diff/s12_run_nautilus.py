"""S12 Nautilus side: BacktestEngine on RAW data.
Supports two execution conventions:
- 'next_open' (default): Orders match at Open_{t+1} (matching Nora P12 strictly causal).
- 'close_fill': Orders match at Close_t (legacy Nautilus single-bar on_bar convention).
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
from s12_common import CAPITAL, DAY, MAKER, OUT, PORT, STAGES, SYMS, TAKER  # noqa: E402
from ext_run_nautilus import build_trades, inst_id, make_instrument
from backend.core import position_size as npolicy

USDT = Currency.from_str("USDT")
VENUE = Venue("OKX")
MIN_NS = 60_000_000_000


def bt(sym, kind):
    return BarType.from_str(f"{sym}USDT-PERP.OKX-1-{'MINUTE' if kind == 'm' else 'DAY'}-LAST-EXTERNAL")


class S12Config(StrategyConfig):
    def __init__(self, **_kw):
        super().__init__()


class Sym:
    def __init__(self, sym, ent, ext, next_opens, day_open_times):
        self.sym, self.ent, self.ext = sym, ent, ext
        self.next_opens = next_opens
        self.day_open_times = day_open_times
        self.nb = 0
        self.day = 0
        self.last_close = float("nan")
        self.live = False
        self.closing = False
        self.closed_bar = -1
        self.qty_plan = 0.0
        self.reserved = 0.0
        self.fees_open = 0.0
        self.entry_equity = CAPITAL
        self.entry_equities = []
        self.entry_margin = 0.0
        self.fills = []
        self.pending_exit = False
        self.sl_price = 0.0


class S12Strategy(Strategy):
    def __new__(cls, config, *_a, **_k):
        return super().__new__(cls, config)

    def __init__(self, config, cfg, sigs, next_opens, day_open_times, fill_mode="next_open"):
        super().__init__(config)
        self.cfg = cfg
        self.fill_mode = fill_mode
        self.S = {s: Sym(s, sigs[s][0], sigs[s][1], next_opens[s], day_open_times[s]) for s in SYMS}
        self.by_inst = {str(inst_id(s)): s for s in SYMS}
        self.admit_log = []
        self.acts = []
        self.d0 = int(pd.read_csv(os.path.join(OUT, f"daily_{SYMS[0]}.csv")).open_time.iloc[0]) // DAY
        self.shadow_balance = CAPITAL

    def on_start(self):
        self.inst = {s: self.cache.instrument(inst_id(s)) for s in SYMS}
        for s in SYMS:
            self.subscribe_bars(bt(s, "m"))
            self.subscribe_bars(bt(s, "d"))

    def eq_nora(self):
        return self.shadow_balance + sum(st.fees_open for st in self.S.values() if st.live)

    def on_bar(self, bar):
        sym = self.by_inst[str(bar.bar_type.instrument_id)]
        st = self.S[sym]
        c = self.cfg

        if bar.bar_type.spec.aggregation.name == "MINUTE":
            st.nb += 1
            st.last_close = float(bar.close)
            # Intrabar Stop-Loss check
            if st.live and not st.closing:
                low_px = float(bar.low)
                if low_px <= st.sl_price:
                    # SL triggered
                    fill_px = st.sl_price
                    fee = st.qty_plan * fill_px * TAKER
                    pnl = (fill_px - st.fills[-1]["px"]) * st.qty_plan - st.fees_open - fee
                    self.shadow_balance += pnl
                    rec = {"stray": False, "t": int(bar.ts_event) // 1_000_000 - 60_000, "side": "SELL",
                           "px": fill_px, "qty": st.qty_plan, "fee": fee, "liq": "TAKER", "kind": "SL",
                           "bar": st.nb - 1, "equity_after": self.shadow_balance, "sym": sym, "adj": []}
                    st.fills.append(rec)
                    st.live = False
                    st.closed_bar = st.nb
                    st.qty_plan = st.reserved = st.fees_open = 0.0
            return

        # Daily bar arrived
        st.day = int(bar.ts_event) // (DAY * 1_000_000) - 1 - self.d0
        d = st.day
        i = st.nb - 1

        # Check Signal Exit
        if st.live and not st.closing:
            if st.ext[d]:
                st.closing = True
                self.acts.append([d, sym, "exit"])
                if self.fill_mode == "next_open" and d + 1 < len(st.next_opens):
                    exit_px = st.next_opens[d + 1]
                    exit_t = int(st.day_open_times[d + 1])
                else:
                    exit_px = float(bar.close)
                    exit_t = int(bar.ts_event) // 1_000_000
                fee = st.qty_plan * exit_px * TAKER
                pnl = (exit_px - st.fills[-1]["px"]) * st.qty_plan - st.fees_open - fee
                self.shadow_balance += pnl
                rec = {"stray": False, "t": exit_t, "side": "SELL", "px": exit_px, "qty": st.qty_plan,
                       "fee": fee, "liq": "TAKER", "kind": "SIG", "bar": (d + 1) * 1440,
                       "equity_after": self.shadow_balance, "sym": sym, "adj": []}
                st.fills.append(rec)
                st.live = False
                st.closing = False
                st.qty_plan = st.reserved = st.fees_open = 0.0
                return

        # Check Entry
        if not st.live and st.ent[d] and st.closed_bar != i:
            eq = self.eq_nora()
            n_open = sum(1 for s in self.S.values() if s.live)
            gross = 0.0
            if n_open < int(PORT["max_positions"]):
                gross = sum(s.qty_plan * s.last_close for s in self.S.values() if s.live)
            adm = npolicy.admit_entry(n_open, 0, eq, eq, gross, 0.0, PORT["max_positions"], PORT["max_per_symbol"], PORT["max_gross_exposure"], 0.0, 0.0)
            self.admit_log.append([d, sym, bool(adm.can_open), n_open, gross, eq, float(adm.max_new_notional)])
            if not adm.can_open:
                return
            reserved = sum(s.reserved for s in self.S.values() if s.live)
            margin = npolicy.clamp_margin(npolicy.flat_margin(eq, c["osp"]), min(eq, eq - reserved), float(c["lev"]), TAKER, adm.max_new_notional)
            if margin <= 0:
                return

            if self.fill_mode == "next_open" and d + 1 < len(st.next_opens):
                enter_px = st.next_opens[d + 1]
                enter_t = int(st.day_open_times[d + 1])
                bar_idx = (d + 1) * 1440
            else:
                enter_px = float(bar.close)
                enter_t = int(bar.ts_event) // 1_000_000
                bar_idx = d * 1440 + 1439

            qty = float(self.inst[sym].make_qty(margin * c["lev"] / enter_px))
            fee = qty * enter_px * TAKER
            st.entry_margin, st.entry_equity = margin, eq
            st.entry_equities.append(eq)
            st.live, st.qty_plan = True, qty
            st.fees_open = fee
            st.sl_price = enter_px * (1 - c["sl"] / 100.0)
            rec = {"stray": False, "t": enter_t, "side": "BUY", "px": enter_px, "qty": qty, "fee": fee,
                   "liq": "TAKER", "kind": "ENTRY", "bar": bar_idx, "equity_after": self.shadow_balance - fee,
                   "sym": sym, "is_entry": True}
            st.fills.append(rec)
            self.acts.append([d, sym, "enter"])


def run_one(stname, fill_mode="next_open"):
    st = STAGES[stname]
    cfg = dict(st, mmr=0.005)
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TraderId.from_str("DIFF-S12"), risk_engine=RiskEngineConfig(bypass=True),
                                                 logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                     starting_balances=[Money(CAPITAL, USDT)], default_leverage=Decimal(st["lev"]), book_type=BookType.L1_MBP, bar_execution=True,
                     fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(MAKER)), taker_rate=Decimal(str(TAKER))))
    m, dly, sigs, insts, next_opens, day_open_times = {}, {}, {}, {}, {}, {}
    for sym in SYMS:
        insts[sym] = make_instrument(sym, cfg)
        engine.add_instrument(insts[sym])
        m[sym] = pd.read_csv(os.path.join(OUT, f"bars1m_{sym}.csv"))
        dly[sym] = pd.read_csv(os.path.join(OUT, f"daily_{sym}.csv"))
        sigs[sym] = (dly[sym][f"ent_{stname}"].values.astype(bool), dly[sym][f"ext_{stname}"].values.astype(bool))
        next_opens[sym] = dly[sym].open.values
        day_open_times[sym] = dly[sym].open_time.values
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
    strat = S12Strategy(S12Config(), cfg, sigs, next_opens, day_open_times, fill_mode=fill_mode)
    engine.add_strategy(strat)
    engine.run()
    res = {"stage": stname, "fill_mode": fill_mode, "trades": [], "open_at_end": [], "admit_log": strat.admit_log, "acts": strat.acts}
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
    res["final_equity"] = strat.shadow_balance
    res["realized_equity_nora_def"] = strat.shadow_balance
    engine.dispose()
    return res


def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STAGES)
    mode = sys.argv[2] if len(sys.argv) > 2 else "next_open"
    for name in only:
        r = run_one(name, fill_mode=mode)
        suffix = f"_{mode}" if mode != "next_open" else ""
        json.dump(r, open(os.path.join(OUT, f"nautilus_{name}{suffix}.json"), "w"))
        print(name, mode, "trades", len(r["trades"]), "realized(nora def)", round(r["realized_equity_nora_def"], 4), "open_at_end", len(r["open_at_end"]), flush=True)


if __name__ == "__main__":
    main()
