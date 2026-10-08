import pytest


def test_generate_folds_no_overlap():
    """
    Test Phase 3.1: Fold theo ngày, OOS không chồng lấp.
    step < test -> raise ValueError
    test_start[i+1] >= test_end[i]
    """
    # Import generate_folds from wfa
    from backend.wfa.wfa import generate_folds
    
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
