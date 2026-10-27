"""Gate 1.3: Risk Policy Sizing & Master Circuit Breaker Enforcement (EDU Side).

Tiêu chí nghiệm thu Gate 1.3:
1. Sizing qua production path (PortfolioAdmissionController.calculate_max_safe_order_qty / admit_order):
   - Tính toán và kiểm tra toàn bộ chi phí: biến động giá tại SL, phí 2 chiều, slippage vào (3 bps), slippage stop (6 bps), và lot rounding.
   - Sizing budget bị ràng buộc đồng thời bởi Sleeve (2.5% của 1,000 USDT = 25 USDT) VÀ Master Equity (0.25% của Master Equity).
   - Từ chối lệnh khi rủi ro vượt trần (RISK_PER_TRADE_EXCEEDED).
   - Chấp nhận lệnh khi rủi ro nằm trong giới hạn an toàn; tổng lỗ ròng tại SL <= 25.0 USDT.
2. Master Circuit Breaker:
   - 2% Master equity (200 USDT) kích hoạt Circuit Breaker khóa mở vị thế.
   - Chặn đứng mọi lệnh mở mới khi Circuit Breaker kích hoạt với lý do MASTER_CIRCUIT_BREAKER_TRIGGERED.
   - Lệnh giảm/đóng vị thế (reduce-only) luôn được chấp nhận (ADMITTED_REDUCE_ONLY).
"""
import pytest
import math
import os
import json
from decimal import Decimal
from pathlib import Path

from backend.core.portfolio import (
    MasterPortfolioLedger,
    PortfolioAdmissionController,
    RiskPolicyConfig,
)


def test_gate1_3_production_sizing_admission_gate():
    """Kiểm tra sizing trực tiếp qua production path: PortfolioAdmissionController."""
    policy = RiskPolicyConfig(
        max_loss_per_trade_pct=0.025,           # 2.5% của 1,000 USDT = 25 USDT max risk
        master_max_risk_per_trade_pct=0.0025,   # 0.25% của 10,000 USDT = 25 USDT max risk
        master_circuit_breaker_pct=0.02,
    )
    ledger = MasterPortfolioLedger(initial_capital=10_000.0, risk_policy=policy)
    sleeve = ledger.register_sleeve("bot_fast_dip", "Fast Dip Harvester", allocated_capital=1000.0)
    ctrl = PortfolioAdmissionController(ledger)

    price = 60_000.0
    sl_pct = 0.02      # 2% SL
    sl_price = price * (1.0 - sl_pct)  # 58,800.0
    contract_val = 1.0
    margin_rate = 0.1
    lot_size = 0.001

    # 1. Thử lệnh Sizing ngây thơ (Naive sizing) bỏ qua chi phí hoặc tính vượt 25 USDT:
    naive_qty = 0.022
    admitted, reason = ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="BUY",
        requested_qty=naive_qty,
        price=price,
        contract_value=contract_val,
        margin_rate=margin_rate,
        sl_price=sl_price,
    )
    assert admitted is False, "Production controller phải chặn lệnh naive sizing vượt trần 25 USDT!"
    assert "RISK_PER_TRADE_EXCEEDED" in reason

    # 2. Sizing an toàn được tính trực tiếp từ production method calculate_max_safe_order_qty
    safe_qty = ctrl.calculate_max_safe_order_qty(
        sleeve_id="bot_fast_dip",
        price=price,
        sl_price=sl_price,
        contract_value=contract_val,
        taker_fee_rate=0.0005,    # 5 bps
        entry_slippage=0.0003,    # 3 bps
        stop_slippage=0.0006,     # 6 bps
        lot_size=lot_size,
    )
    assert safe_qty > 0

    admitted, reason = ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="BUY",
        requested_qty=safe_qty,
        price=price,
        contract_value=contract_val,
        margin_rate=margin_rate,
        sl_price=sl_price,
        taker_fee_rate=0.0005,
        entry_slippage=0.0003,
        stop_slippage=0.0006,
    )
    assert admitted is True, f"Lệnh sizing an toàn ({safe_qty} BTC) phải được chấp nhận: reason={reason}"
    assert reason == "ADMITTED"

    # 3. Kiểm chứng toán học chi tiết toàn bộ drag
    notional = safe_qty * price
    price_loss = notional * sl_pct
    entry_fee = notional * 0.0005
    exit_fee = safe_qty * sl_price * 0.0005
    entry_slippage_cost = notional * 0.0003
    exit_slippage_cost = safe_qty * sl_price * 0.0006

    actual_net_loss = price_loss + entry_fee + exit_fee + entry_slippage_cost + exit_slippage_cost
    assert actual_net_loss <= 25.0, f"Tổng lỗ ròng tại SL {actual_net_loss:.4f} USDT vượt trần 25 USDT!"
    assert actual_net_loss >= 22.0, f"Sizing quá thấp ({actual_net_loss:.4f} USDT), không tận dụng vốn!"

    # 4. Thử lệnh với quantity vượt quá 1 lot so với safe_qty -> Phải bị từ chối
    over_qty = round(safe_qty + lot_size, 8)
    admitted_over, reason_over = ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="BUY",
        requested_qty=over_qty,
        price=price,
        contract_value=contract_val,
        margin_rate=margin_rate,
        sl_price=sl_price,
        taker_fee_rate=0.0005,
        entry_slippage=0.0003,
        stop_slippage=0.0006,
    )
    assert admitted_over is False, f"Lệnh {over_qty} BTC vượt trần rủi ro phải bị từ chối!"
    assert "RISK_PER_TRADE_EXCEEDED" in reason_over

    # 5. Kiểm tra ràng buộc theo Master Equity:
    reduced_ledger = MasterPortfolioLedger(initial_capital=8_000.0, risk_policy=policy)
    reduced_ledger.register_sleeve("bot_fast_dip", "Fast Dip Harvester", allocated_capital=1000.0)
    reduced_ctrl = PortfolioAdmissionController(reduced_ledger)

    scaled_qty = reduced_ctrl.calculate_max_safe_order_qty(
        sleeve_id="bot_fast_dip",
        price=price,
        sl_price=sl_price,
        contract_value=contract_val,
        taker_fee_rate=0.0005,
        entry_slippage=0.0003,
        stop_slippage=0.0006,
        lot_size=lot_size,
    )
    assert scaled_qty < safe_qty, "Khi Master Equity giảm, safe quantity phải tự động scale down!"

    adm_scaled, r_scaled = reduced_ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="BUY",
        requested_qty=safe_qty,
        price=price,
        contract_value=contract_val,
        margin_rate=margin_rate,
        sl_price=sl_price,
    )
    assert adm_scaled is False
    assert "RISK_PER_TRADE_EXCEEDED" in r_scaled


def test_gate1_3_master_circuit_breaker_locks_at_2_percent():
    """Kiểm tra Circuit Breaker khóa giao dịch khi lỗ chạm 2% Master (200 USDT)."""
    policy = RiskPolicyConfig(master_circuit_breaker_pct=0.02)
    ledger = MasterPortfolioLedger(initial_capital=10_000.0, risk_policy=policy)
    sleeve = ledger.register_sleeve("bot_fast_dip", "Fast Dip Harvester", allocated_capital=1000.0)

    # 1. Bình thường: Lỗ 100 USDT (< 200 USDT)
    ledger.record_fill(
        fill_id="fill_loss_minor",
        sleeve_id="bot_fast_dip",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        qty=0.01,
        price=50000.0,
        fee=0.0,
        realized_gain=-100.0,
        margin_delta=0.0,
    )
    snap = ledger.get_snapshot()
    assert snap["portfolio_summary"]["circuit_breaker_status"] == "NORMAL"
    assert ledger.circuit_breaker_triggered is False

    # 2. Chạm ngưỡng: Thêm lệnh lỗ 110 USDT -> Tổng lỗ 210 USDT (> 200 USDT = 2% của 10k)
    ledger.record_fill(
        fill_id="fill_loss_trigger",
        sleeve_id="bot_fast_dip",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        qty=0.01,
        price=50000.0,
        fee=0.0,
        realized_gain=-110.0,
        margin_delta=0.0,
    )
    snap = ledger.get_snapshot()
    assert ledger.circuit_breaker_triggered is True
    assert snap["portfolio_summary"]["circuit_breaker_status"] == "TRIGGERED"
    assert sleeve.status == "LOCKED"

    # Admission controller phải chặn đứng mọi lệnh mở mới
    ctrl = PortfolioAdmissionController(ledger)
    admitted, reason = ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="BUY",
        requested_qty=0.01,
        price=50000.0,
        contract_value=1.0,
        margin_rate=0.1,
        sl_price=49000.0,
    )
    assert admitted is False
    assert reason == "MASTER_CIRCUIT_BREAKER_TRIGGERED"

    # Lệnh reduce-only vẫn được chấp nhận
    admitted_red, reason_red = ctrl.admit_order(
        sleeve_id="bot_fast_dip",
        side="SELL",
        requested_qty=0.01,
        price=50000.0,
        contract_value=1.0,
        margin_rate=0.1,
        is_reduce_only=True,
    )
    assert admitted_red is True
    assert reason_red == "ADMITTED_REDUCE_ONLY"
