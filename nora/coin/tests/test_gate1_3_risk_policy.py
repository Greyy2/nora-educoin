"""Gate 1.3: Risk Policy Sizing & Master Circuit Breaker Enforcement.

Tiêu chí nghiệm thu Gate 1.3:
1. Sizing qua production path (PortfolioAdmissionController.calculate_max_safe_order_qty / admit_order):
   - Tính toán và kiểm tra toàn bộ chi phí: biến động giá tại SL, phí 2 chiều, slippage vào (3 bps), slippage stop (6 bps), và lot rounding.
   - Sizing budget bị ràng buộc đồng thời bởi Sleeve (2.5% của 1,000 USDT = 25 USDT) VÀ Master Equity (0.25% của Master Equity).
   - Từ chối lệnh khi rủi ro vượt trần (RISK_PER_TRADE_EXCEEDED).
   - Chấp nhận lệnh khi rủi ro nằm trong giới hạn an toàn; tổng lỗ ròng tại SL <= 25.0 USDT.
2. Daily loss lock và persistence:
   - Dùng đúng daily baseline UTC 00:00 midnight. Các lệnh đóng trước 00:00 UTC không tính vào daily loss hôm nay.
   - Kiểm tra ranh giới: dưới ngưỡng, tại ngưỡng, trên ngưỡng (Sleeve 3% = 30 USDT, Master 2% = 200 USDT).
   - Sau restart/reload từ ledger trên đĩa, trạng thái khóa được khôi phục chính xác.
   - Khi bị khóa (Sleeve LOCKED hoặc Master Circuit Breaker TRIGGERED), lệnh mở mới bị chặn, lệnh giảm/đóng vị thế (reduce-only) vẫn được chấp nhận.
"""
import pytest
import math
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.core.portfolio import (
    MasterPortfolioLedger,
    PortfolioAdmissionController,
    RiskPolicyConfig,
    get_live_master_ledger,
)


def _make_running_bot_meta(bot_id: str, strategy: str, capital: float = 1000.0) -> dict:
    curr_pid = os.getpid()
    with open(f"/proc/{curr_pid}/stat", "rb") as fh:
        pid_start = int(fh.read().rsplit(b")", 1)[1].split()[19])
    return {
        "bot_id": bot_id,
        "strategy": strategy,
        "capital": capital,
        "sleeve_status": "ACTIVE",
        "status": "running",
        "pid": curr_pid,
        "pid_start": pid_start,
    }


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
    # Nếu Master Equity sụt giảm xuống 8,000 USDT,
    # thì hạn mức rủi ro Master là 8,000 * 0.0025 = 20.0 USDT (< 25.0 USDT của sleeve)
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

    # Thử vào lệnh safe_qty (25 USDT) trên tài khoản Master Equity 8,000 USDT -> Phải bị từ chối vì trần Master 20 USDT
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


def test_gate1_3_daily_loss_utc_baseline_and_master_circuit_breaker(tmp_path, monkeypatch):
    """Kiểm tra daily loss tính từ mốc UTC midnight và Master Circuit Breaker 2% (200 USDT)."""
    monkeypatch.setenv("NORA_MASTER_CAPITAL_PAPER", "10000.0")

    now_ms = int(time.time() * 1000)
    now_utc = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    day_start_ms = int(datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc).timestamp() * 1000)

    # ── TRƯỜNG HỢP 1: Trade hôm qua (close_time < day_start_ms) không tính vào daily loss hôm nay ──
    root1 = tmp_path / "c1"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root1))
    b_yest = root1 / "live" / "paper" / "bot_yesterday"
    b_yest.mkdir(parents=True, exist_ok=True)
    meta_yest = _make_running_bot_meta("bot_yesterday", "FastDipHarvesterStrategy", 1000.0)
    (b_yest / "bot.json").write_text(json.dumps(meta_yest), encoding="utf-8")
    (b_yest / "positions.json").write_text("[]", encoding="utf-8")
    (b_yest / "heartbeat.json").write_text(json.dumps({"updated_at": now_ms}), encoding="utf-8")

    yesterday_ts = day_start_ms - 3600_000
    entry_yest = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "BUY", "px": 60000.0, "qty": 0.05, "fee": 0.0, "ts": yesterday_ts - 60000, "kind": "ENTRY",
    }
    exit_yest = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "SELL", "px": 57000.0, "qty": 0.05, "fee": 0.0, "ts": yesterday_ts, "kind": "SL",
    }
    with open(b_yest / "events.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(entry_yest) + "\n" + json.dumps(exit_yest) + "\n")

    reloaded_yest = get_live_master_ledger(mode="paper")
    assert reloaded_yest.today_realized_pnl == 0.0
    assert reloaded_yest.circuit_breaker_triggered is False

    # ── TRƯỜNG HỢP 2: Trade hôm nay ngay dưới ngưỡng 2% Master (lỗ 190 USDT < 200 USDT) ──
    # Với vốn sleeve 7,000 USDT, ngưỡng 3% sleeve là 210 USDT; do đó lỗ 190 USDT không khóa sleeve mà kiểm tra đúng ngưỡng Master
    root2 = tmp_path / "c2"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root2))
    b_sub = root2 / "live" / "paper" / "bot_sub"
    b_sub.mkdir(parents=True, exist_ok=True)
    meta_sub = _make_running_bot_meta("bot_sub", "FastDipHarvesterStrategy", 7000.0)
    (b_sub / "bot.json").write_text(json.dumps(meta_sub), encoding="utf-8")
    (b_sub / "positions.json").write_text("[]", encoding="utf-8")
    (b_sub / "heartbeat.json").write_text(json.dumps({"updated_at": now_ms}), encoding="utf-8")

    today_ts = day_start_ms + 10000
    entry_today_sub = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "BUY", "px": 60000.0, "qty": 0.1, "fee": 0.0, "ts": today_ts, "kind": "ENTRY",
    }
    exit_today_sub = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "SELL", "px": 58100.0, "qty": 0.1, "fee": 0.0, "ts": today_ts + 60000, "kind": "SL",
    }
    with open(b_sub / "events.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(entry_today_sub) + "\n" + json.dumps(exit_today_sub) + "\n")

    reloaded_sub = get_live_master_ledger(mode="paper")
    assert reloaded_sub.today_realized_pnl == -190.0
    assert reloaded_sub.circuit_breaker_triggered is False
    ctrl_sub = PortfolioAdmissionController(reloaded_sub)
    adm_sub, r_sub = ctrl_sub.admit_order(
        sleeve_id="sleeve_bot_sub", side="BUY", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, sl_price=59000.0,
    )
    assert adm_sub is True, f"Dưới ngưỡng 2% (lỗ 190 USDT), lệnh phải được duyệt: {r_sub}"

    # ── TRƯỜNG HỢP 3: Trade hôm nay vượt ngưỡng 2% Master (lỗ 205 USDT >= 200 USDT) ──
    root3 = tmp_path / "c3"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root3))
    b_exact = root3 / "live" / "paper" / "bot_exact"
    b_exact.mkdir(parents=True, exist_ok=True)
    meta_exact = _make_running_bot_meta("bot_exact", "FastDipHarvesterStrategy", 7000.0)
    (b_exact / "bot.json").write_text(json.dumps(meta_exact), encoding="utf-8")
    (b_exact / "positions.json").write_text("[]", encoding="utf-8")
    (b_exact / "heartbeat.json").write_text(json.dumps({"updated_at": now_ms}), encoding="utf-8")

    entry_exact = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "BUY", "px": 60000.0, "qty": 0.1, "fee": 0.0, "ts": today_ts, "kind": "ENTRY",
    }
    exit_exact = {
        "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDipHarvesterStrategy",
        "side": "SELL", "px": 57950.0, "qty": 0.1, "fee": 0.0, "ts": today_ts + 60000, "kind": "SL",
    }
    with open(b_exact / "events.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(entry_exact) + "\n" + json.dumps(exit_exact) + "\n")

    reloaded_exact = get_live_master_ledger(mode="paper")
    assert reloaded_exact.today_realized_pnl == -205.0
    assert reloaded_exact.circuit_breaker_triggered is True

    ctrl_exact = PortfolioAdmissionController(reloaded_exact)
    # Lệnh mở mới phải bị từ chối
    adm_new, r_new = ctrl_exact.admit_order(
        sleeve_id="sleeve_bot_exact", side="BUY", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, sl_price=59000.0,
    )
    assert adm_new is False
    assert r_new == "MASTER_CIRCUIT_BREAKER_TRIGGERED"

    # Lệnh giảm/đóng vị thế (reduce-only) vẫn được chấp nhận
    adm_red, r_red = ctrl_exact.admit_order(
        sleeve_id="sleeve_bot_exact", side="SELL", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, is_reduce_only=True,
    )
    assert adm_red is True
    assert r_red == "ADMITTED_REDUCE_ONLY"


def test_gate1_3_sleeve_daily_loss_3_pct_isolation(tmp_path, monkeypatch):
    """Kiểm tra khóa riêng từng sleeve khi daily loss chạm 3% sleeve (30 USDT) mà Master (<200 USDT) chưa bị khóa."""
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("NORA_MASTER_CAPITAL_PAPER", "10000.0")

    now_ms = int(time.time() * 1000)
    now_utc = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    day_start_ms = int(datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc).timestamp() * 1000)

    # Bot 1: Fast Dip Harvester (lỗ 32 USDT hôm nay >= 30 USDT = 3% của 1000 USDT)
    b1_dir = tmp_path / "live" / "paper" / "bot1"
    b1_dir.mkdir(parents=True, exist_ok=True)
    b1_meta = _make_running_bot_meta("bot1", "FastDip", 1000.0)
    (b1_dir / "bot.json").write_text(json.dumps(b1_meta), encoding="utf-8")
    (b1_dir / "positions.json").write_text("[]", encoding="utf-8")
    (b1_dir / "heartbeat.json").write_text(json.dumps({"updated_at": now_ms}), encoding="utf-8")

    e1_in = {"type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDip", "side": "BUY", "px": 60000.0, "qty": 0.01, "fee": 0.0, "ts": day_start_ms + 1000, "kind": "ENTRY"}
    e1_out = {"type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "FastDip", "side": "SELL", "px": 56800.0, "qty": 0.01, "fee": 0.0, "ts": day_start_ms + 2000, "kind": "SL"}
    with open(b1_dir / "events.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(e1_in) + "\n" + json.dumps(e1_out) + "\n")

    # Bot 2: Momentum Bot (hôm nay không lỗ, hoạt động bình thường)
    b2_dir = tmp_path / "live" / "paper" / "bot2"
    b2_dir.mkdir(parents=True, exist_ok=True)
    b2_meta = _make_running_bot_meta("bot2", "Momentum", 1000.0)
    (b2_dir / "bot.json").write_text(json.dumps(b2_meta), encoding="utf-8")
    (b2_dir / "positions.json").write_text("[]", encoding="utf-8")
    (b2_dir / "heartbeat.json").write_text(json.dumps({"updated_at": now_ms}), encoding="utf-8")
    with open(b2_dir / "events.jsonl", "w", encoding="utf-8") as f:
        pass

    reloaded = get_live_master_ledger(mode="paper")
    # Master Circuit Breaker KHÔNG kích hoạt vì tổng lỗ chỉ là 32 USDT (< 200 USDT)
    assert reloaded.circuit_breaker_triggered is False

    # Bot 1 bị khóa do vượt 3% daily loss của sleeve
    sleeve1 = reloaded.sleeves["sleeve_bot1"]
    assert sleeve1.status == "LOCKED"
    assert sleeve1.daily_realized_pnl == -32.0

    # Bot 2 vẫn ACTIVE
    sleeve2 = reloaded.sleeves["sleeve_bot2"]
    assert sleeve2.status == "ACTIVE"

    ctrl = PortfolioAdmissionController(reloaded)
    # Lệnh mở mới trên Bot 1 bị từ chối
    adm_b1, r_b1 = ctrl.admit_order(
        sleeve_id="sleeve_bot1", side="BUY", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, sl_price=59000.0,
    )
    assert adm_b1 is False
    assert r_b1 == "SLEEVE_LOCKED_MAX_LOSS"

    # Lệnh reduce-only trên Bot 1 vẫn được duyệt
    adm_b1_red, r_b1_red = ctrl.admit_order(
        sleeve_id="sleeve_bot1", side="SELL", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, is_reduce_only=True,
    )
    assert adm_b1_red is True
    assert r_b1_red == "ADMITTED_REDUCE_ONLY"

    # Lệnh mở mới trên Bot 2 vẫn được duyệt bình thường
    adm_b2, r_b2 = ctrl.admit_order(
        sleeve_id="sleeve_bot2", side="BUY", requested_qty=0.001, price=60000.0,
        contract_value=1.0, margin_rate=0.1, sl_price=59000.0,
    )
    assert adm_b2 is True
    assert r_b2 == "ADMITTED"
