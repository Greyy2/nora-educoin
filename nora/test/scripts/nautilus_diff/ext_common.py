"""Shared config for the EXTENDED Nora vs NautilusTrader differential test (S4-S8).
Imports the S1-S3 constants from common.py (read-only), adds the short / leverage / trailing / timeout / funding / portfolio stages.
Everything of this extension lives in ext_*.py + EXT_REPORT.md; the S1-S3 files are not touched.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CAPITAL, TAKER, MAKER, ORDER_SIZE_PCT  # noqa: E402,F401

OUT = os.path.join(HERE, "out", "ext")
SYMS = ["BTC", "ETH", "SOL"]
SIGNALS = ["ema20_50", "ema5_13"]
DATASETS = ["aligned", "gapped"]
H = 3_600_000

# Stage config keys: side L|S, lev, osp (% of equity as margin of the first layer), sl/tp (% from avg), dca_steps/dca_mults,
# trail (% from peak), trail_act (% profit at peak before the trail is armed), timeout (bars), mmr (Nora maintenance margin rate),
# liq (Nautilus venue liquidation_enabled), fund (None | "bar" | "real"), port (portfolio risk caps, S8 only), syms.
_S3 = {"sl": 1.5, "tp": 1.0, "dca_steps": [0.5, 0.7, 1.0], "dca_mults": [1.5, 1.5, 1.5], "osp": 10.0}
_BASE = {"lev": 1, "osp": ORDER_SIZE_PCT, "mmr": 0.005}


def _mk(**kw):
    d = dict(_BASE)
    d.update(kw)
    return d


STAGES = {
    # S4 short side: mirror of S1-S3 (short entry = EMA down-cross, short exit = EMA up-cross)
    "S4a_S": _mk(side="S"),
    "S4b_S": _mk(side="S", sl=0.8, tp=1.0),
    "S4c_S": _mk(side="S", **_S3),
    # S5 leverage + liquidation (isolated-like single position per symbol)
    "S5a_L": _mk(side="L", lev=5, sl=0.8, tp=1.0, liq=True),                  # PnL / fee / margin scaling, SL fires before liquidation
    "S5a_S": _mk(side="S", lev=5, sl=0.8, tp=1.0, liq=True),
    "S5b_L": _mk(side="L", lev=10, osp=100.0, liq=True),                       # signal exits only: liquidation is the only protective exit
    "S5b_S": _mk(side="S", lev=10, osp=100.0, liq=True),
    "S5c_L": _mk(side="L", lev=25, osp=50.0, sl=5.0, tp=2.0, liq=True),        # liquidation distance (3.5%) is inside the SL (5%)
    "S5c_S": _mk(side="S", lev=25, osp=50.0, sl=5.0, tp=2.0, liq=True),
    "S5d_L": _mk(side="L", lev=25, osp=100.0, liq=True, only_sig=["ema20_50"]),                       # full-equity margin: Nautilus cross threshold == Nora isolated level
    "S5d_S": _mk(side="S", lev=25, osp=100.0, liq=True, only_sig=["ema20_50"]),
    # S6 trailing stop (+activation) and timeout
    "S6a_L": _mk(side="L", trail=0.8),
    "S6a_S": _mk(side="S", trail=0.8),
    "S6b_L": _mk(side="L", trail=0.8, trail_act=0.5),
    "S6b_S": _mk(side="S", trail=0.8, trail_act=0.5),
    "S6c_L": _mk(side="L", trail=1.0, sl=0.8, tp=2.0),
    "S6c_S": _mk(side="S", trail=1.0, sl=0.8, tp=2.0),
    "S6d_L": _mk(side="L", timeout=6),
    "S6d_S": _mk(side="S", timeout=6),
    "S6e_L": _mk(side="L", timeout=12, sl=0.8, tp=1.0),
    "S6e_S": _mk(side="S", timeout=12, sl=0.8, tp=1.0),
    "S6f_L": _mk(side="L", trail=0.6, timeout=24),
    "S6f_S": _mk(side="S", trail=0.6, timeout=24),
    # S7 funding (OKX BTC perp funding.pkl as FundingRateUpdate). fund="bar": settlement boundary = Nora's application bar open;
    # fund="real": boundary = the true funding_time (a few seconds after the hour).
    "S7a_L_bar": _mk(side="L", fund="bar"),
    "S7a_S_bar": _mk(side="S", fund="bar"),
    "S7b_L_bar": _mk(side="L", lev=3, osp=50.0, sl=1.5, tp=2.0, fund="bar"),
    "S7a_L_real": _mk(side="L", fund="real"),
    "S7a_S_real": _mk(side="S", fund="real"),
    "S7b_L_real": _mk(side="L", lev=3, osp=50.0, sl=1.5, tp=2.0, fund="real"),
    # S8 portfolio: 3 symbols, one account, Nora risk caps as pre-trade logic
    "S8a": _mk(side="L", lev=2, osp=30.0, sl=1.5, tp=2.0, syms=SYMS, port={"max_positions": 3, "max_per_symbol": 1, "max_gross_exposure": 10.0}),
    "S8b": _mk(side="L", lev=2, osp=30.0, sl=1.5, tp=2.0, syms=SYMS, port={"max_positions": 2, "max_per_symbol": 1, "max_gross_exposure": 10.0}),
    "S8c": _mk(side="L", lev=2, osp=30.0, sl=1.5, tp=2.0, syms=SYMS, port={"max_positions": 3, "max_per_symbol": 1, "max_gross_exposure": 1.0}),
    "S8d": _mk(side="L", lev=2, osp=30.0, sl=1.5, tp=2.0, syms=SYMS, port={"max_positions": 2, "max_per_symbol": 1, "max_gross_exposure": 0.8}),
}
for _k, _v in STAGES.items():
    _v.setdefault("syms", ["BTC"])


def stages_of(group):
    """group: 'S4'..'S8' -> stage names."""
    return [k for k in STAGES if k.startswith(group)]


def tag(ds, sname, stname, path):
    return f"{ds}_{sname}_{stname}_{path}"


def skip(stname, sname):
    """Stage restricted to some signals (S5d: full-equity 25x ruins the account with the 160-trade signal; relative rounding noise then dominates)."""
    return bool(STAGES[stname].get("only_sig")) and sname not in STAGES[stname]["only_sig"]
