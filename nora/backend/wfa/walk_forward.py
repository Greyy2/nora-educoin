"""Chia cửa sổ walk-forward: fold train/test theo ngày, OOS không chồng lấp."""
from typing import Dict, List, Optional


def generate_folds(
    start_ts: int,
    end_ts: int,
    train_days: int = 30,
    test_days: int = 10,
    step_days: Optional[int] = None,
    embargo_days: int = 0,
    anchored: bool = False,
    **kwargs,
) -> List[Dict[str, int]]:
    """
    Sinh các cửa sổ fold theo ngày, đảm bảo OOS không chồng lấp (Phase 3.1).
    Nếu step_days < test_days, raise ValueError để ngăn chặn OOS chồng lấp.
    """
    D = 86_400_000
    step = (step_days or test_days) * D
    if step < test_days * D:
        raise ValueError(f"step ({step // D}d) < test ({test_days}d) -> OOS chồng lấp! Không được phép.")

    folds = []
    test_start = start_ts + (train_days + embargo_days) * D
    while test_start + test_days * D <= end_ts:
        train_end = test_start - embargo_days * D
        train_start = start_ts if anchored else train_end - train_days * D
        folds.append({
            "train_start_ts": int(train_start),
            "train_end_ts": int(train_end),
            "test_start_ts": int(test_start),
            "test_end_ts": int(test_start + test_days * D),
        })
        test_start += step
    return folds
