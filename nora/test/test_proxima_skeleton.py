"""Unit tests for Proxima Native Strategy Research Skeleton (Phase 1).

Verifies:
1. 3-Tier Taxonomy: runtime_safety_policy, fixture_verified, experimental_logic.
2. Metadata & Schema: Unverified flags on anchor_frame, z/w variants, TP variants, R semantics, exit precedence.
3. Contract-aware risk sizing: Includes fee rate, slippage rate, adverse price distance, lotSz floor, and 15$ risk cap.
4. Dual signal formula variants: Variant A (Keltner distance) vs Variant B (Normalized band breakout).
5. Exit State Machine Precedence & Conflict Resolution: Cycle SL must supersede Center Exit and Partial TP.
6. Master Admission Controller integration.
"""

import pytest
from backend.adapter.execution import InstrumentSpec, ExitReason
from backend.core.strategy_proxima import (
    RUNTIME_SAFETY_POLICY,
    EXPERIMENTAL_LOGIC_SCHEMA,
    ProximaNativeStrategy,
    ProximaNativeStrategyConfig,
    calculate_contract_aware_sizing,
    evaluate_signal_variant_a,
    evaluate_signal_variant_b,
    resolve_exit_state_machine,
    floor_to_step,
)
from backend.core.portfolio import MasterPortfolioLedger, PortfolioAdmissionController


def test_proxima_3_tier_taxonomy_and_unverified_flags():
    """Kiểm tra phân tầng 3 lớp và các cờ unverified bắt buộc."""
    # 1. Runtime Safety Policy
    assert RUNTIME_SAFETY_POLICY["nora_sleeve_risk_limit"] == 15.0
    assert RUNTIME_SAFETY_POLICY["master_reserve_floor"] == 5000.0
    assert RUNTIME_SAFETY_POLICY["shared_execution_required"] is True

    # 2. Experimental Logic Schema
    exp = EXPERIMENTAL_LOGIC_SCHEMA
    assert exp["anchor_frame"]["source_verified"] is False
    assert exp["signal_formula_variants"]["variant_a"]["verified"] is False
    assert exp["signal_formula_variants"]["variant_b"]["verified"] is False
    assert exp["tp_formula_variants"]["variant_a_atr_distance"]["verified"] is False
    assert exp["tp_formula_variants"]["variant_b_pnl_equity"]["verified"] is False
    assert exp["r_ratio"]["proxima_original_risk"] == "unverified"
    assert exp["exit_order_precedence"]["verified"] is False
    assert exp["execution_feed"]["sub_minute_ticks_required"] is True
    assert exp["execution_feed"]["ready"] is False


def test_contract_aware_sizing_btc_and_eth():
    """Kiểm tra sizing tính đầy đủ contract spec, bước nhảy lotSz, phí và trượt giá."""
    btc_spec = InstrumentSpec(
        symbol="BTC-USDT-SWAP",
        ctVal=0.01,
        multiplier=1.0,
        lotSz=1.0,      # OKX SWAP BTC: 1 hợp đồng = 0.01 BTC
        minSz=1.0,
        tickSz=0.1,
    )

    # Giá BTC = 80,000$, khoảng cách SL 0.8%, ngân sách rủi ro Nora cap = 15$
    contracts, notional, worst_loss = calculate_contract_aware_sizing(
        spec=btc_spec,
        price=80000.0,
        sleeve_capital=1000.0,
        adverse_price_pct=0.008,
        vl_mult=0.75,
        nora_max_risk_usd=15.0,
        max_notional_cap_usd=2500.0,
    )

    # 1 hợp đồng BTC = 0.01 BTC = 800$ notional
    # Lỗ trên 1 hợp đồng: 0.01 * (80000 * 0.008 + 80000 * 0.0014) = 0.01 * (640 + 112) = 7.52$
    # Cận 1: 15 / 7.52 = 1.99 hợp đồng * 0.75 VL = 1.49 -> floor 1.0 hợp đồng
    assert contracts == 1.0
    assert notional == 800.0
    assert worst_loss <= 15.0  # Rủi ro tối đa luôn <= 15$

    # Kiểm tra với lotSz bước nhỏ hơn
    eth_spec = InstrumentSpec(
        symbol="ETH-USDT-SWAP",
        ctVal=0.1,
        multiplier=1.0,
        lotSz=1.0,
        minSz=1.0,
        tickSz=0.01,
    )
    eth_contracts, eth_notional, eth_loss = calculate_contract_aware_sizing(
        spec=eth_spec,
        price=2500.0,
        sleeve_capital=1000.0,
        adverse_price_pct=0.008,
        vl_mult=0.75,
        nora_max_risk_usd=15.0,
    )
    assert eth_contracts >= 1.0
    assert eth_loss <= 15.0


def test_dual_signal_formula_variants():
    """Kiểm tra tính toán hai biến thể tín hiệu A và B."""
    ema = 80000.0
    atr = 500.0
    f_mult = 1.0

    # Kịch bản 1: Giá đỉnh vượt EMA + 1.2*ATR -> Long Breakout trên Variant A
    running_high = 80650.0  # z = (80650 - 80000) / 500 = 1.3 > 1.0
    running_low = 80050.0   # w = (80000 - 80050) / 500 = -0.1
    long_a, short_a, z_a, w_a = evaluate_signal_variant_a(running_high, running_low, ema, atr, f_mult)
    assert long_a is True
    assert short_a is False
    assert z_a > f_mult

    # Kịch bản 2: Variant B yêu cầu vượt Upper thêm một khoảng chuẩn hóa K_delta
    # Upper = 80500, K_delta = 2 * 1.0 * 500 = 1000
    # Với high = 80650: z = (80650 - 80500) / 1000 = 0.15 < 1.0 -> Variant B chưa Long!
    long_b, short_b, z_b, w_b = evaluate_signal_variant_b(running_high, running_low, ema, atr, f_mult)
    assert long_b is False  # Thể hiện rõ sự khác biệt giữa 2 biến thể toán học!

    # Kịch bản 3: Short Breakout trên Variant A
    running_high_s = 79950.0
    running_low_s = 79300.0  # w = (80000 - 79300) / 500 = 1.4 > 1.0
    long_s, short_s, z_s, w_s = evaluate_signal_variant_a(running_high_s, running_low_s, ema, atr, f_mult)
    assert long_s is False
    assert short_s is True
    assert w_s > f_mult


def test_exit_state_machine_conflict_resolution():
    """Kiểm tra máy trạng thái thoát lệnh và giải quyết xung đột đa điều kiện."""
    # Kịch bản xung đột: Đồng thời chạm ngưỡng Cycle SL (-15$) và giá chạm Partial TP (+5% ATR)
    # Lệnh bảo vệ vốn (CYCLE_SL) PHẢI thắng tuyệt đối!
    exit_reason = resolve_exit_state_machine(
        is_long=True,
        price=81000.0,
        ema=80000.0,
        atr=500.0,
        f_mult=1.0,
        cycle_realized_usd=-10.0,
        cycle_unrealized_usd=-5.0,  # Tổng -15$, trên budget 15$ -> -100% E <= -0.8%
        sleeve_risk_budget_usd=15.0,
        is_session_cutoff=False,
        tp_formula_variant="atr_distance",
        tp_mult=0.8,
        already_partial_tp=False,
        entry_price=80000.0,
    )
    assert exit_reason == ExitReason.CYCLE_SL

    # Kịch bản 2: Session Cutoff thắng Center Exit & Partial TP
    exit_reason_cutoff = resolve_exit_state_machine(
        is_long=True,
        price=80500.0,
        ema=80000.0,
        atr=500.0,
        f_mult=1.0,
        cycle_realized_usd=0.0,
        cycle_unrealized_usd=5.0,
        sleeve_risk_budget_usd=15.0,
        is_session_cutoff=True,
        already_partial_tp=False,
        entry_price=80000.0,
    )
    assert exit_reason_cutoff == ExitReason.SESSION_CUTOFF

    # Kịch bản 3: Center Exit (Giá Long quay về dưới EMA 80,000)
    exit_reason_center = resolve_exit_state_machine(
        is_long=True,
        price=79900.0,  # Dưới EMA 80,000
        ema=80000.0,
        atr=500.0,
        f_mult=1.0,
        cycle_realized_usd=0.0,
        cycle_unrealized_usd=-1.0,
        sleeve_risk_budget_usd=15.0,
        is_session_cutoff=False,
        already_partial_tp=False,
        entry_price=80000.0,
    )
    assert exit_reason_center == ExitReason.CENTER_EXIT

    # Kịch bản 4: Partial TP kích hoạt khi không có điều kiện bảo vệ nào vi phạm
    exit_reason_tp = resolve_exit_state_machine(
        is_long=True,
        price=80025.0,  # entry 80000 + 0.05 * 500 * 0.8 = 80000 + 20 = 80020 <= 80025
        ema=80000.0,
        atr=500.0,
        f_mult=1.0,
        cycle_realized_usd=0.0,
        cycle_unrealized_usd=2.0,
        sleeve_risk_budget_usd=15.0,
        is_session_cutoff=False,
        already_partial_tp=False,
        entry_price=80000.0,
    )
    assert exit_reason_tp == ExitReason.PARTIAL_TP


def test_proxima_strategy_native_contract_and_admission():
    """Kiểm tra hợp đồng ProximaNativeStrategy kết nối Master Admission."""
    ledger = MasterPortfolioLedger(initial_capital=10000.0, reserve_floor=5000.0)
    ledger.register_sleeve("sleeve_proxima", "Proxima Research Sleeve", 1000.0)
    admission = PortfolioAdmissionController(ledger)

    cfg = ProximaNativeStrategyConfig(
        instrument_id="BTC-USDT-SWAP",
        sleeve_id="sleeve_proxima",
        sleeve_capital=1000.0,
        shadow_mode=False,
    )
    strat = ProximaNativeStrategy(cfg, admission_controller=admission)

    assert strat.is_native is True
    assert strat.timeframe == "1m"
    assert strat.symbols == ["BTC"]

    # Thử nghiệm Admission: Lệnh trong hạn mức được chấp nhận
    ok, msg = strat.check_pre_trade_admission(
        side="BUY",
        requested_qty=1.0,
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,
        sl_price=79360.0,
    )
    assert ok is True
    assert msg == "ADMITTED"

    # Thử nghiệm Admission: Lệnh vượt hạn mức ký quỹ deployable cash sẽ bị từ chối
    ok_huge, msg_huge = strat.check_pre_trade_admission(
        side="BUY",
        requested_qty=1000.0,   # Cần 80,000$ margin -> vi phạm trần 5000$ deployable cash
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,
    )
    assert ok_huge is False
    assert "BREACH_PREVENTED" in msg_huge or "SLEEVE_MARGIN_EXCEEDED" in msg_huge
