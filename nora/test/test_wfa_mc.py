import pytest
import numpy as np


def test_generate_folds_no_overlap():
    """
    Test Phase 3.1: Fold theo ngày, OOS không chồng lấp.
    step < test -> raise ValueError
    test_start[i+1] >= test_end[i]
    """
    # Import generate_folds from wfa
    from backend.wfa.walk_forward import generate_folds
    
    start_ts = 1700000000000
    D = 86_400_000
    end_ts = start_ts + 90 * D
    
    # 1. step < test must raise ValueError
    with pytest.raises(ValueError, match="chồng lấp"):
        generate_folds(start_ts, end_ts, train_days=30, test_days=10, step_days=5)
        
    # 2. Standard rolling folds
    folds = generate_folds(start_ts, end_ts, train_days=30, test_days=10, step_days=10)
    assert len(folds) >= 4, f"Cần ít nhất 4 folds cho 90 ngày, got {len(folds)}"
    
    # Verify no OOS overlap
    for i in range(len(folds) - 1):
        assert folds[i+1]["test_start_ts"] >= folds[i]["test_end_ts"], (
            f"OOS overlap detected between fold {i} and {i+1}!"
        )
        assert folds[i]["test_end_ts"] - folds[i]["test_start_ts"] == 10 * D
        assert folds[i]["train_end_ts"] <= folds[i]["test_start_ts"]


def test_mc_reproducible_and_mdd():
    """
    Test Phase 4:
    - Hai lần chạy cùng seed cho kết quả giống hệt nhau
    - Trade list có lệnh lỗ -> MDD > 0
    - quantile_curves có trong kết quả
    """
    from backend.carlo.monte_carlo import run_monte_carlo_simulation
    
    # Mock trades list with 40 trades (some winning, some losing)
    rng = np.random.default_rng(42)
    mock_trades = []
    for i in range(40):
        pnl = float(rng.normal(-10.0, 50.0))  # has negative returns
        mock_trades.append({
            "trade_id": i + 1,
            "pnl_usd": pnl,
            "estimated_pnl_usd": pnl,
            "profit_pct": pnl / 1000.0 * 100.0,
        })
        
    res1 = run_monte_carlo_simulation(mock_trades, simulations=200, seed=12345)
    res2 = run_monte_carlo_simulation(mock_trades, simulations=200, seed=12345)
    
    assert res1["percentile_mdd"]["p50"] > 0, "MDD phải lớn hơn 0 khi có lệnh lỗ"
    assert res1["percentile_mdd"] == res2["percentile_mdd"], "Cùng seed phải cho kết quả giống hệt nhau"
    assert "quantile_curves" in res1, "Phải có quantile_curves để vẽ fan chart"
