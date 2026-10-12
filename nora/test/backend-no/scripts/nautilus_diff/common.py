"""Shared config for the Nora vs NautilusTrader differential test."""
CAPITAL = 10_000.0
ORDER_SIZE_PCT = 20.0
TAKER, MAKER = 0.0005, 0.0002
SIGNALS = ["ema20_50", "ema5_13"]
DATASETS = ["aligned", "raw", "gapped"]
# sl/tp in percent of average entry price. Tight so the same-bar ambiguity and gaps are exercised often on 1h bars.
STAGES = {
    "S1": {},
    "S2": {"sl": 0.8, "tp": 1.0},
    # S3: smaller first order so the whole ladder fits max_capital_usage=1 (Nora would otherwise reject layers, which Nautilus does not model)
    "S3": {"sl": 1.5, "tp": 1.0, "dca_steps": [0.5, 0.7, 1.0], "dca_mults": [1.5, 1.5, 1.5], "osp": 10.0},
}
