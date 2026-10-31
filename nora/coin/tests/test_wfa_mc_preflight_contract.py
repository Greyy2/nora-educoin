import importlib.util
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wfa_mc_independent_engine.py"
SPEC = importlib.util.spec_from_file_location("wfa_mc_runner", SCRIPT_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_structural_cohort_label_rejects_executable_signal_logic():
    with pytest.raises(RuntimeError, match="stale"):
        runner._validate_cohort_source_labels(
            [{"id": "bad", "source_classification": "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC"}],
            {"bad": "class S(NoraStrategy):\n    def on_bar(self):\n        self.buy(close > 0)\n"},
        )


def test_stationary_bootstrap_is_compounded_and_uses_mdd_names():
    result = runner.run_stationary_block_bootstrap_compounded(
        [0.01, -0.01, 0.0, 0.005],
        n_sims=32,
        block_days=2,
        horizon_days=20,
        seed=7,
    )
    assert result["status"] == "COMPLETED"
    assert result["simulations"] == 32
    assert "prob_mdd_ge_15_pct" in result
    assert "prob_mdd_ge_20_pct" in result
    assert not any("ruin" in key.lower() for key in result)
    assert np.isfinite(result["median_terminal_ret_pct"])
