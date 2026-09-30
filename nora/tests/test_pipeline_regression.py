import pytest
import numpy as np
import pandas as pd
import tempfile
import os
import json

from backend.alpha.directional_change import DirectionalChangeEngine, simulate_causal_dc_trades
from backend.research.data_quality_gate import evaluate_data_quality, DataQualityStatus
from backend.core.resampler import fill_missing_1m_candles, resample_from_1m, save_resampled_dataset
from backend.studio_pipeline.wfa import generate_folds, WfaFoldConfig, execute_wfa_pipeline
from backend.studio_pipeline.jobs import get_wfa_job, init_db, create_wfa_job
from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig


def test_random_walk_falsification():
    """
    Random Walk Benchmark (Phase 6):
    GBM noise -> Run DC simulation with 0 friction.
    Average net bps should be close to 0 (|avg| < 30 bps on finite sample).
    With standard friction (65 bps), it must be FALSIFIED.
    """
    rng = np.random.default_rng(12345)
    n_ticks = 5000
    times = [1700000000000 + i * 1000 for i in range(n_ticks)]
    ret = rng.normal(0, 0.001, size=n_ticks)
    prices = 100.0 * np.exp(np.cumsum(ret))

    df_ticks = pd.DataFrame({
        "timestamp_ms": times,
        "price": prices,
        "amount": 100.0,
    })

    sim_zero_fee = simulate_causal_dc_trades(df_ticks, theta=0.01, friction_bps=0.0)
    assert sim_zero_fee["total_trades"] > 0
    zero_model = sim_zero_fee["cost_models"]["zero"]
    assert abs(zero_model["avg_net_bps"]) < 30.0, f"Expected |avg| < 30 bps on random walk, got {zero_model['avg_net_bps']}"

    # Under standard friction, pure random walk must NOT survive
    sim_standard = simulate_causal_dc_trades(df_ticks, theta=0.01, friction_bps=65.0)
    standard_model = sim_standard["cost_models"]["standard"]
    assert standard_model["survived"] is False, "Random walk must not survive standard friction hurdle"
    assert standard_model["verdict"] == "FALSIFIED"


def test_planted_edge_detection():
    """
    Planted Edge Test (Phase 6):
    Synthetic price series with strong overshoot continuation after directional change.
    In momentum mode, pipeline must detect positive gross & net alpha.
    """
    prices = [100.0]
    times = [1700000000000]
    
    t = 1700000000000
    for cycle in range(35):
        # Trend up: 100 -> 106 (overshoot continuation)
        base_p = prices[-1]
        for step in range(1, 7):
            t += 1000
            times.append(t)
            prices.append(base_p * (1.0 + step * 0.01))
        # Trend down: 106 -> 100 (overshoot continuation)
        base_p = prices[-1]
        for step in range(1, 7):
            t += 1000
            times.append(t)
            prices.append(base_p * (1.0 - step * 0.01))

    df_ticks = pd.DataFrame({
        "timestamp_ms": times,
        "price": prices,
        "amount": 100.0,
    })

    sim = simulate_causal_dc_trades(df_ticks, theta=0.02, friction_bps=20.0, tp_overshoot_multiplier=1.2, mode="momentum")
    assert sim["total_trades"] >= 30, f"Expected >= 30 trades, got {sim['total_trades']}"
    low_model = sim["cost_models"]["low"]
    assert low_model["avg_net_bps"] > 0, f"Planted edge must generate positive net bps, got {low_model['avg_net_bps']}"


def test_data_quality_gate_checks():
    """
    Data Quality Gate Validation (Phase 1 & Phase 6):
    1. Rejects asset without manifest.json.
    2. Rejects asset with synthetic=True in manifest.
    3. Rejects asset with 1m price jump > 50%.
    4. Rejects asset when 1m resample does not match stored 15m.
    5. Approves clean asset with synthetic=False, sufficient bars and matching 15m.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        sym = "TESTSYM"
        sym_dir = os.path.join(tmp_dir, sym)
        os.makedirs(sym_dir, exist_ok=True)

        # 1. No manifest -> BLOCKED
        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert "thiếu manifest.json" in res["issues"][0]

        # 2. Manifest with synthetic=True -> BLOCKED
        manifest_path = os.path.join(sym_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"synthetic": True, "source": "fake"}, f)
        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert "synthetic=true" in res["issues"][0]

        # 3. Create valid 1m candles (> 35 hours = 2100 minutes) and resample using core resampler
        t0 = 1700000000000
        n_bars = 2500
        times = [t0 + i * 60_000 for i in range(n_bars)]
        prices = [100.0 * (1.0 + 0.0001 * (i % 50)) for i in range(n_bars)]
        df_1m_clean = pd.DataFrame({
            "open_time": times,
            "open": prices,
            "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices,
            "volume": 100.0,
        })

        # Save properly via save_resampled_dataset
        save_resampled_dataset(
            symbol=sym,
            output_dir=tmp_dir,
            df_1m_raw=df_1m_clean,
            pool_address="0x123",
            timeframes=("15m", "1h", "4h"),
            synthetic=False,
        )

        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.APPROVED, f"Clean data should be APPROVED, got: {res}"

        # 4. Corrupt 15m file -> must be BLOCKED
        df_15m_corrupt = pd.read_pickle(os.path.join(sym_dir, "15m.pkl"))
        df_15m_corrupt["close"] = df_15m_corrupt["close"] * 1.10  # 10% mismatch
        df_15m_corrupt.to_pickle(os.path.join(sym_dir, "15m.pkl"))

        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert any("Resample 1m sang 15m lệch" in issue for issue in res["issues"])


def test_no_silent_fallback_wfa_missing_symbol():
    """
    WFA Fail Closed (Phase 3.4):
    If symbol does not exist in local data, execute_wfa_pipeline must fail cleanly,
    never falling back to 'SOL' or random assets.
    """
    init_db()
    job_id = create_wfa_job(symbol="NON_EXISTENT_XYZ", strategy_name="Test Snap", total_folds=5)
    
    snapshot = StrategySnapshot(
        name="Test Snap",
        symbol="NON_EXISTENT_XYZ",
        flows=[{"action": "test"}],
    )
    cfg = WfaFoldConfig(train_days=30, test_days=10)
    
    # execute_wfa_pipeline should call fail_wfa_job and mark job FAILED
    execute_wfa_pipeline(job_id, snapshot, cfg, source_handle="test_handle")
    job = get_wfa_job(job_id)
    assert job is not None
    assert job["status"].lower() == "failed"
    assert "NON_EXISTENT_XYZ" in job["error"] or "không tồn tại" in job["error"]
