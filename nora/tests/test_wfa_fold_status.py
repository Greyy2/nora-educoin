"""
test_wfa_fold_status.py — Đợt 3.1, 3.2, 3.3: WFA fold status + schema validation

3.1: Fold không đủ lệnh IS → status NO_TRADE, oos_trades=[], không đưa sang MC
3.2: param_grid validation trong schema (key bogus, >50 combos, list rỗng, string)
3.3: param_stability là None khi không có grid; min_positive_ratio=0.0 không bị coi là 0.6
"""
import math
import pytest
from pydantic import ValidationError

from backend.studio_pipeline.schemas import (
    StrategySnapshot, WfaFoldConfig, WfaFoldResult,
)


# ─── Đợt 3.1: WFA NO_TRADE fold ─────────────────────────────────────────────

def test_wfa_no_trade_fold_requires_status_field():
    """WfaFoldResult phải có trường status (TRADED / NO_TRADE)."""
    fold = WfaFoldResult(
        fold_index=0,
        train_start_ts=0, train_end_ts=1,
        train_start_date="2024-01-01", train_end_date="2024-01-31",
        test_start_ts=1, test_end_ts=2,
        test_start_date="2024-02-01", test_end_date="2024-02-10",
        is_return_pct=0.0, is_max_drawdown_pct=0.0, is_trades_count=0, is_win_rate=0.0,
        oos_return_pct=0.0, oos_max_drawdown_pct=0.0, oos_trades_count=0, oos_win_rate=0.0,
        oos_profit_factor=0.0,
        passed_gate=False,
        status="NO_TRADE",
    )
    assert fold.status == "NO_TRADE"


def _run_wfa_all_no_trade():
    """Helper: chạy WFA với min_is_trades rất lớn → tất cả fold phải NO_TRADE."""
    import tempfile, os
    import pandas as pd
    import numpy as np
    from backend.studio_pipeline.wfa import execute_wfa_pipeline
    from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job, init_db

    init_db()

    # Tạo dữ liệu 1m sạch đủ dài (100 ngày)
    t0 = 1700000000000
    n = 144_000  # 100 ngày × 1440 phút/ngày
    times = [t0 + i * 60_000 for i in range(n)]
    prices = list(np.random.default_rng(42).lognormal(0, 0.0005, size=n).cumprod() * 100)

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "TESTSYM"), exist_ok=True)
        df = pd.DataFrame({
            "open_time": times,
            "open": prices, "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices, "volume": [100.0] * n,
        })
        from backend.core.resampler import save_resampled_dataset
        save_resampled_dataset(
            symbol="TESTSYM",
            output_dir=tmp,
            df_1m_raw=df,
            pool_address="0xtest",
            timeframes=("15m", "1h", "4h"),
            synthetic=False,
            crawl_ok=True,
        )

        snapshot = StrategySnapshot(
            name="NoTrade Test",
            symbol="TESTSYM",
            flows=[{"id": "f1", "type": "LONG", "ast": {"type": "LONG", "nodes": []}}],
            initial_capital=10000.0,
            param_grid={"stop_loss_rate": [0.01, 0.02]},
        )
        # min_is_trades = 10**6: không bao giờ đủ lệnh
        cfg = WfaFoldConfig(
            train_days=10, test_days=5, fold_count=4,
            min_is_trades=1_000_000,  # impossibly high
            min_positive_folds=0,
        )

        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp
        job_id = create_wfa_job("TESTSYM", "NoTrade Test", 4)
        execute_wfa_pipeline(job_id, snapshot, cfg, source_handle="test")

        job = get_wfa_job(job_id)
        return job


def test_wfa_all_no_trade_status():
    """Khi min_is_trades quá cao: tất cả fold là NO_TRADE."""
    job = _run_wfa_all_no_trade()
    assert job is not None
    result = job.get("result") or {}
    folds = result.get("folds", [])
    assert len(folds) > 0, "Phải có ít nhất 1 fold"
    for fold in folds:
        assert fold.get("status") == "NO_TRADE", (
            f"Fold {fold.get('fold_index')} phải là NO_TRADE khi min_is_trades quá cao"
        )


def test_wfa_all_no_trade_zero_oos():
    """NO_TRADE folds: total_oos_trades == 0, positive_folds_count == 0."""
    job = _run_wfa_all_no_trade()
    result = job.get("result") or {}
    assert result.get("total_oos_trades", -1) == 0, (
        f"total_oos_trades phải = 0, got {result.get('total_oos_trades')}"
    )
    assert result.get("positive_folds_count", -1) == 0, (
        f"positive_folds_count phải = 0, got {result.get('positive_folds_count')}"
    )


def test_wfa_all_no_trade_gate_false():
    """NO_TRADE → acceptance_gate_passed phải False."""
    job = _run_wfa_all_no_trade()
    result = job.get("result") or {}
    assert result.get("acceptance_gate_passed") is False


def test_wfa_all_no_trade_empty_aggregate_oos():
    """NO_TRADE folds không đưa lệnh sang MC: aggregate_oos_trades phải rỗng."""
    job = _run_wfa_all_no_trade()
    result = job.get("result") or {}
    trades = result.get("aggregate_oos_trades", None)
    assert trades is not None, "aggregate_oos_trades phải là list, không phải None"
    assert len(trades) == 0, (
        f"aggregate_oos_trades phải rỗng với tất cả fold NO_TRADE, got {len(trades)}"
    )


# ─── Đợt 3.2: param_grid validation trong schema ─────────────────────────────

def test_param_grid_bogus_key_rejected():
    """Key không nằm trong ALLOWED_GRID_KEYS phải raise ValidationError."""
    with pytest.raises((ValidationError, ValueError)):
        StrategySnapshot(
            name="Test", symbol="X",
            param_grid={"bogus_key": [1, 2, 3]},
        )


def test_param_grid_too_many_combos():
    """Grid > 50 tổ hợp phải raise ValidationError KHÔNG treo máy."""
    # 7×8=56 > 50
    with pytest.raises((ValidationError, ValueError)):
        StrategySnapshot(
            name="Test", symbol="X",
            param_grid={
                "stop_loss_rate": [0.01 * i for i in range(1, 8)],
                "take_profit_rate": [0.01 * i for i in range(1, 9)],
            },
        )


def test_param_grid_empty_list_rejected():
    """List rỗng trong param_grid phải bị từ chối."""
    with pytest.raises((ValidationError, ValueError)):
        StrategySnapshot(
            name="Test", symbol="X",
            param_grid={"stop_loss_rate": []},
        )


def test_param_grid_string_value_rejected():
    """Giá trị kiểu string trong param_grid phải bị từ chối."""
    with pytest.raises((ValidationError, ValueError)):
        StrategySnapshot(
            name="Test", symbol="X",
            param_grid={"stop_loss_rate": ["low", "medium", "high"]},
        )


def test_param_grid_large_product_rejected_fast():
    """
    Grid 10000×10000=10**8 tổ hợp phải bị từ chối NGAY (không dựng list tổ hợp).
    Nếu dùng itertools.product(...) sẽ treo máy — test này kiểm tra điều đó không xảy ra.
    """
    import time
    start = time.monotonic()
    with pytest.raises((ValidationError, ValueError)):
        StrategySnapshot(
            name="Test", symbol="X",
            param_grid={
                "stop_loss_rate": [0.001 * i for i in range(1, 10001)],
                "take_profit_rate": [0.001 * i for i in range(1, 10001)],
            },
        )
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"Validation mất {elapsed:.2f}s (quá chậm, có thể dùng itertools.product)"


def test_param_grid_valid_accepted():
    """Grid hợp lệ phải được accept."""
    snap = StrategySnapshot(
        name="Test", symbol="X",
        param_grid={
            "stop_loss_rate": [0.01, 0.02, 0.03],
            "take_profit_rate": [0.02, 0.04],
        },
    )
    # 3×2=6 combos, valid
    assert snap.param_grid == {
        "stop_loss_rate": [0.01, 0.02, 0.03],
        "take_profit_rate": [0.02, 0.04],
    }


# ─── Đợt 3.3: param_stability và min_positive_ratio ─────────────────────────

def test_wfa_no_grid_param_stability_none():
    """Khi không có grid, param_stability phải là None (không bịa giá trị 1.0)."""
    import tempfile, os, json
    import pandas as pd
    import numpy as np
    from backend.studio_pipeline.wfa import execute_wfa_pipeline
    from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job, init_db

    init_db()
    t0 = 1700000000000
    n = 50_400  # 35 ngày
    times = [t0 + i * 60_000 for i in range(n)]
    prices = list(np.random.default_rng(99).lognormal(0, 0.001, n).cumprod() * 100)

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "SYM"), exist_ok=True)
        df = pd.DataFrame({
            "open_time": times,
            "open": prices, "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices, "volume": [10.0] * n,
        })
        from backend.core.resampler import save_resampled_dataset
        save_resampled_dataset(
            symbol="SYM",
            output_dir=tmp,
            df_1m_raw=df,
            pool_address="0xtest",
            timeframes=("15m", "1h", "4h"),
            synthetic=False,
            crawl_ok=True,
        )

        snapshot = StrategySnapshot(
            name="NoGrid", symbol="SYM",
            flows=[{"id": "f1", "type": "LONG", "ast": {"type": "LONG", "nodes": []}}],
            # param_grid rỗng = None
        )
        cfg = WfaFoldConfig(train_days=5, test_days=2, fold_count=3)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp
        job_id = create_wfa_job("SYM", "NoGrid", 3)
        execute_wfa_pipeline(job_id, snapshot, cfg, "test_h")

        job = get_wfa_job(job_id)
        assert job.get("status") == "completed", f"Job failed: {job.get('error')}"
        result = job.get("result") or {}
        assert result.get("param_stability") is None, (
            f"Không có grid → param_stability phải None, got {result.get('param_stability')}"
        )


def test_wfa_fold_config_min_positive_ratio_zero():
    """
    cfg.min_positive_ratio = 0.0 phải được giữ nguyên là 0.0.
    Code cũ dùng `or` nên 0.0 bị đổi thành 0.6 default.
    """
    cfg = WfaFoldConfig(min_positive_ratio=0.0)
    # Kiểm tra schema lưu đúng
    assert cfg.min_positive_ratio == 0.0, (
        f"min_positive_ratio bị thay đổi từ 0.0 thành {cfg.min_positive_ratio}"
    )


def test_wfa_fold_config_extra_forbid():
    """WfaFoldConfig cấm field lạ (extra='forbid') như train_window_months."""
    with pytest.raises(ValidationError):
        WfaFoldConfig(train_window_months=1)

