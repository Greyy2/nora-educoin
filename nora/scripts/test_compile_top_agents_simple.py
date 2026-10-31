import os, sys, json
sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code

code_01pp = '''class OkxTopAgent01pp(SimpleAlgorithm):
    """[DRAFT_UNVERIFIED] OKX Top Agent 01pp.
    Nguồn: data/alpha/research/okx_top10_agents.json.
    Tham số trích xuất từ formula_summary: TP = 0.931% giá, đòn bẩy median = 15x.
    """
    timeframe = "1h"
    period_fast = 10
    period_slow = 30

    exit_unit = "pct"
    take_profit_rate = 0.931
    stop_loss_rate = 3.0
    leverage = 15
    cooldown = 60
    risk_per_trade_pct = 0.25

    def __algorithm__(self):
        close = self.data.pv_close
        fast = self.feat.sma(close, self.period_fast)
        slow = self.feat.sma(close, self.period_slow)
        self.set_positions(fast > slow, position=1)
        self.set_positions(fast < slow, position=0)
'''

code_aurora = '''class OkxTopAgentAuroraxwt(SimpleAlgorithm):
    """[DRAFT_UNVERIFIED] OKX Top Agent Auroraxwt.
    Nguồn: data/alpha/research/okx_top10_agents.json.
    Tham số trích xuất từ formula_summary: SL = 0.218% giá, đòn bẩy median = 20x.
    """
    timeframe = "1h"
    rsi_period = 14

    exit_unit = "pct"
    stop_loss_rate = 0.218
    take_profit_rate = 2.0
    leverage = 20
    cooldown = 60
    risk_per_trade_pct = 0.25

    def __algorithm__(self):
        close = self.data.pv_close
        rsi_val = self.feat.rsi(close, self.rsi_period)
        self.set_positions(rsi_val < 30, position=1)
        self.set_positions(rsi_val > 70, position=0)
'''

code_dahlia = '''class OkxTopAgentDarkWoodDahlia(SimpleAlgorithm):
    """[DRAFT_UNVERIFIED] OKX Top Agent Dark Wood Dahlia.
    Nguồn: data/alpha/research/okx_top10_agents.json.
    Tham số trích xuất từ formula_summary: TP = 3.159% giá, đòn bẩy median = 10x.
    """
    timeframe = "15m"
    bb_period = 20
    bb_std = 2.0

    exit_unit = "pct"
    take_profit_rate = 3.159
    stop_loss_rate = 2.0
    leverage = 10
    cooldown = 15
    risk_per_trade_pct = 0.25

    def __algorithm__(self):
        close = self.data.pv_close
        mid = self.feat.sma(close, self.bb_period)
        dev = self.feat.stddev(close, self.bb_period, self.bb_std)
        self.set_positions(close < (mid - dev), position=1)
        self.set_positions(close > mid, position=0)
'''

bots = [
    ("okx_01pp", code_01pp, "01pp"),
    ("okx_auroraxwt", code_aurora, "auroraxwt"),
    ("okx_dark_wood_dahlia", code_dahlia, "dark_wood_dahlia")
]

for bid, code, slug in bots:
    prog = compile_code(code)
    print(f"SUCCESS compile {bid} ({slug}):")
    print(f"  Program name: {prog.name}")
    print(f"  Timeframe: {prog.timeframe}")
    print(f"  position_overrides: {prog.position_overrides}")
    print(f"  features: {sorted(prog.features)}")
