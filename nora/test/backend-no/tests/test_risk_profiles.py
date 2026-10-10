"""Unit tests cho Strategy Risk Controller & Core Execution theo P14 (P14-C1, C2, C4).
Kiểm tra 5 họ: legacy, trend, breakout, mean_reversion, dca.
Chạy từ test/backend-no để bảo đảm tính cô lập.
"""
import sys
import os

# Ưu tiên nạp từ test/backend-no
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_NO = os.path.join(TEST_DIR, "backend-no")
if BACKEND_NO not in sys.path:
    sys.path.insert(0, BACKEND_NO)

import pytest
import numpy as np

from backend.core.params import StrategyParams, DEFAULT_ALLOCATION
from backend.core.position_size import (
    RiskProfile, RiskIssue, RISK_PROFILES, get_risk_profile,
    validate_strategy_risk, sl_price_for_anchor, SlotSpec, admit_entry
)
from backend.core.models import PositionType
from backend.core.backtest import SlotDriver


def test_risk_profiles_definitions():
    """B2: Đủ 5 họ profile với thuộc tính bất biến chuẩn."""
    assert set(RISK_PROFILES.keys()) == {"legacy", "trend", "breakout", "mean_reversion", "dca"}
    for name, p in RISK_PROFILES.items():
        assert isinstance(p, RiskProfile)
        assert p.name == name
        assert p.sl_anchor in ("avg", "entry", "last_layer", "none")
        assert p.dca_mode in ("allowed", "forbidden", "limited", "required")

    assert get_risk_profile("trend").name == "trend"
    assert get_risk_profile("non_existent").name == "legacy"


def test_validate_legacy_always_clean():
    """B2: legacy không sinh issue nào -> bit-identical."""
    params = {"risk_profile": "legacy", "dca_max_layers": 5, "stop_loss_rate": 0.0}
    assert validate_strategy_risk(params) == []


def test_validate_trend():
    """B2: trend cấm DCA, bắt buộc SL hoặc trailing."""
    # Vi phạm DCA
    issues = validate_strategy_risk({"risk_profile": "trend", "dca_max_layers": 1, "stop_loss_rate": 2.0})
    assert any(i.code == "TREND_DCA_FORBIDDEN" for i in issues)

    # Vi phạm thiếu thoát
    issues = validate_strategy_risk({"risk_profile": "trend", "stop_loss_rate": 0.0, "trailing_stop": 0.0})
    assert any(i.code == "TREND_EXIT_REQUIRED" for i in issues)

    # Hợp lệ
    assert validate_strategy_risk({"risk_profile": "trend", "stop_loss_rate": 2.0, "trailing_stop": 0.0}) == []
    assert validate_strategy_risk({"risk_profile": "trend", "stop_loss_rate": 0.0, "trailing_stop": 1.5}) == []


def test_validate_breakout():
    """B2: breakout cấm DCA, bắt buộc SL và bắt buộc trailing hoặc timeout."""
    # Vi phạm DCA
    issues = validate_strategy_risk({"risk_profile": "breakout", "dca_step_pct": 1.0, "stop_loss_rate": 2.0, "timeout": 60})
    assert any(i.code == "BREAKOUT_DCA_FORBIDDEN" for i in issues)

    # Vi phạm thiếu SL
    issues = validate_strategy_risk({"risk_profile": "breakout", "stop_loss_rate": 0.0, "timeout": 60})
    assert any(i.code == "BREAKOUT_SL_REQUIRED" for i in issues)

    # Vi phạm thiếu cả trailing lẫn timeout
    issues = validate_strategy_risk({"risk_profile": "breakout", "stop_loss_rate": 2.0, "trailing_stop": 0.0, "timeout": 0})
    assert any(i.code == "BREAKOUT_TIMEOUT_OR_TRAIL_REQUIRED" for i in issues)

    # Hợp lệ
    assert validate_strategy_risk({"risk_profile": "breakout", "stop_loss_rate": 2.0, "timeout": 120}) == []


def test_validate_mean_reversion():
    """B2: mean_reversion bắt buộc SL, tối đa 2 tầng DCA, mọi tầng nằm trước SL."""
    # Vi phạm thiếu SL
    issues = validate_strategy_risk({"risk_profile": "mean_reversion", "stop_loss_rate": 0.0})
    assert any(i.code == "REVERT_SL_REQUIRED" for i in issues)

    # Vi phạm quá 2 tầng DCA
    issues = validate_strategy_risk({"risk_profile": "mean_reversion", "stop_loss_rate": 5.0, "dca_max_layers": 3, "dca_step_pct": 1.0})
    assert any(i.code == "REVERT_DCA_LIMIT_EXCEEDED" for i in issues)

    # Vi phạm tầng DCA vượt SL (tổng lùi 2 * 2% = 4% >= SL 3%)
    issues = validate_strategy_risk({"risk_profile": "mean_reversion", "stop_loss_rate": 3.0, "dca_max_layers": 2, "dca_step_pct": 2.0})
    assert any(i.code == "REVERT_DCA_BEYOND_SL" for i in issues)

    # Hợp lệ
    assert validate_strategy_risk({"risk_profile": "mean_reversion", "stop_loss_rate": 5.0, "dca_max_layers": 2, "dca_step_pct": 1.5}) == []


def test_validate_dca():
    """B2: dca bắt buộc >= 1 tầng, SL avg không được nông hơn tổng tầng DCA."""
    # Thiếu tầng DCA
    issues = validate_strategy_risk({"risk_profile": "dca", "dca_max_layers": 0})
    assert any(i.code == "DCA_LAYERS_REQUIRED" for i in issues)

    # SL avg mâu thuẫn (cắt ngang tầng DCA)
    issues = validate_strategy_risk({"risk_profile": "dca", "dca_max_layers": 2, "dca_step_pct": 2.0, "stop_loss_rate": 3.0, "sl_anchor": "avg"})
    assert any(i.code == "DCA_SL_CONFLICT" for i in issues)

    # Hợp lệ khi neo last_layer
    assert validate_strategy_risk({"risk_profile": "dca", "dca_max_layers": 2, "dca_step_pct": 2.0, "stop_loss_rate": 1.0, "sl_anchor": "last_layer"}) == []


def test_sl_price_for_anchor():
    """B3: sl_price_for_anchor tính đúng cho 4 kiểu neo."""
    entry = 100.0
    avg = 98.0
    sl_pct = 2.0

    # Long:
    # 1. avg
    assert sl_price_for_anchor("avg", entry, avg, sl_pct, 1.0) == pytest.approx(98.0 * 0.98)
    # 2. entry
    assert sl_price_for_anchor("entry", entry, avg, sl_pct, 1.0) == pytest.approx(100.0 * 0.98)
    # 3. last_layer (tầng 1 lùi 1% -> 99; tầng 2 lùi 2% -> 99 * 0.98 = 97.02; SL lùi thêm 1% sau tầng 2)
    p_last = 100.0 * 0.99 * 0.98
    expected_sl = p_last * 0.99
    assert sl_price_for_anchor("last_layer", entry, avg, sl_pct, 1.0, dca_steps=[1.0, 2.0], sl_beyond_last_pct=1.0) == pytest.approx(expected_sl)
    # 4. none
    assert sl_price_for_anchor("none", entry, avg, sl_pct, 1.0) == 0.0


def test_slotspec_risk_profile_integration():
    """B4: SlotSpec đọc profile, kiểm tra và thiết lập sl_anchor_mode."""
    # Legacy: sl_anchor_mode luôn = 0
    p_leg = StrategyParams(risk_profile="legacy", stop_loss_rate=2.0)
    spec_leg = SlotSpec(0, 0, "BTC", "leg", p_leg, PositionType.LONG, 10000.0)
    assert spec_leg.risk_profile == "legacy"
    assert spec_leg.sl_anchor_mode == 0

    # Trend: sl_anchor_mode = 1
    p_trend = StrategyParams(risk_profile="trend", stop_loss_rate=2.0)
    spec_trend = SlotSpec(0, 0, "BTC", "tr", p_trend, PositionType.LONG, 10000.0)
    assert spec_trend.risk_profile == "trend"
    assert spec_trend.sl_anchor_mode == 1

    # Vi phạm luật trend -> raise ValueError
    p_bad = StrategyParams(risk_profile="trend", stop_loss_rate=0.0)
    with pytest.raises(ValueError, match="vi phạm quy tắc Risk Profile 'trend'"):
        SlotSpec(0, 0, "BTC", "bad", p_bad, PositionType.LONG, 10000.0)


def test_dca_last_layer_scenario_c1():
    """C1: Kiểm chứng Ca B - dca neo last_layer:
    Entry 100 -> nến quét 96 (khớp tầng 99 và 97), KHÔNG bị SL cắt sớm vì SL neo dưới tầng cuối (vd: 95.06).
    Sau đó giá bật lên 130 -> TP theo giá TB khớp rổ thành công.
    """
    params = StrategyParams(
        market="spot",
        order_size_pct=30.0,
        dca_steps=[1.0, 2.0],        # tầng 1: 99.0, tầng 2: 97.02
        dca_multipliers=[1.0, 1.0],
        take_profit_rate=5.0,        # TP 5% từ giá TB
        stop_loss_rate=2.0,          # 2% sau tầng cuối
        risk_profile="dca",
        sl_anchor="last_layer",
        sl_beyond_last_pct=2.0,      # SL tại 97.02 * 0.98 = 95.0796
        intrabar_path="ohlc",
    )
    spec = SlotSpec(0, 0, "BTC", "dca_flow", params, PositionType.LONG, 10000.0)
    assert spec.sl_anchor_mode == 1

    driver = SlotDriver([spec])
    view = driver[0]

    # Nến 1: Open 100 -> vào lệnh entry tại 100.
    # Low 96 -> khớp tầng 99 và 97.02. Mức SL là 95.0796 nên ở 96 KHÔNG bị cắt!
    # Close 98.
    view.on_bar(0, 100.0, 100.5, 96.0, 98.0, entry_signal=True)

    assert view.is_open
    assert view.layer_count == 3   # Entry + 2 tầng DCA đều đã khớp!
    assert view.avg < 100.0        # Giá TB đã được kéo xuống ~98.66

    # Nến 2: Giá bật lên High 130 -> chốt lời TP!
    view.on_bar(60000, 98.0, 130.0, 97.5, 125.0)
    assert not view.is_open        # Vị thế đã đóng thành công có lãi!


def test_dca_last_layer_sl_trigger():
    """C1 biến thể: Khi giá rơi thủng mức SL sau tầng cuối (rơi qua 95.0) -> đóng lệnh đúng tại SL."""
    params = StrategyParams(
        market="spot",
        order_size_pct=30.0,
        dca_steps=[1.0, 2.0],        # tầng 1: 99.0, tầng 2: 97.02
        dca_multipliers=[1.0, 1.0],
        stop_loss_rate=2.0,          # 2% sau tầng cuối -> 95.0796
        risk_profile="dca",
        sl_anchor="last_layer",
        sl_beyond_last_pct=2.0,
        intrabar_path="ohlc",
    )
    spec = SlotSpec(0, 0, "BTC", "dca_sl", params, PositionType.LONG, 10000.0)
    driver = SlotDriver([spec])
    view = driver[0]

    # Nến 1: Open 100 -> rơi thẳng xuống Low 94 (xuyên qua cả 2 tầng DCA và xuyên qua cả mức SL 95.0796)
    view.on_bar(0, 100.0, 100.0, 94.0, 94.5, entry_signal=True)

    assert not view.is_open        # Vị thế đã bị cắt lỗ đúng mức


def test_allocation_bucket_admit():
    """B5: admit_entry kiểm trần theo bucket."""
    # Bucket dca chỉ cho tối đa 2 vị thế (trong khi toàn danh mục cho 8)
    a = admit_entry(
        n_open=1, per_symbol_open=1, equity=1000.0, peak=1000.0, gross=500.0, open_risk=10.0,
        max_positions=8, max_per_symbol=2, max_gross_exposure=3.0, max_open_risk_pct=6.0,
        bucket_open=2, bucket_max_positions=2
    )
    assert not a.can_open          # Bị chặn bởi trần bucket!

    a_ok = admit_entry(
        n_open=1, per_symbol_open=1, equity=1000.0, peak=1000.0, gross=500.0, open_risk=10.0,
        max_positions=8, max_per_symbol=2, max_gross_exposure=3.0, max_open_risk_pct=6.0,
        bucket_open=1, bucket_max_positions=2
    )
    assert a_ok.can_open           # Vẫn còn chỗ trong bucket
