"""FastDip strategy source used for the Nora backtest evidence run.

This is Nora DSL source, not a standalone Python application. It is compiled
by the EDU/COIN custom strategy compiler.
"""


class FastDipHarvesterStrategy(NoraStrategy):
    timeframe = "24h"
    rsi_period = 10
    sma_period = 15
    macro_period = 50
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        rsi_val = rsi(close, self.rsi_period)
        sma_val = sma(close, self.sma_period)
        macro = ema(close, self.macro_period)

        self.close(
            (rsi_val > 65.0) | crossunder(close, sma_val)
        )
        self.buy(
            crossover(rsi_val, 40.0)
            & (close > sma_val)
            & (close > macro)
        )
