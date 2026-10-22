"""Bộ kiểm thử đơn vị toàn diện cho Kiến trúc Alpha Decoupled và Adapter 3-File của Nora.

Kiểm tra:
1. backend/adapter/readings.py: Data normalization, multi-anchor, late bar recomputing anchor, incomplete bucket lifecycle.
2. backend/analys/signal/signal.py: Proxima Alpha engine theo Cách A chuẩn gốc (Upper=EMA+F*ATR, Lower=EMA-F*ATR, K_delta=2*F*ATR, z>F).
3. backend/adapter/execution.py: OMS chuẩn sàn (Sizing 3 cận, Dynamic cap, In-flight Pending, VWAP partial fill, PAUSE_ENTRY).
4. backend/adapter/runner.py: Dispatcher điều phối (1m event loop, routing broker, audit log, graceful pause).
5. backend/adapter/specs.py: Quy chuẩn sàn Universal Specs (Crypto SWAP, CFS Vàng XAUUSD, Ngoại hối EURUSD, Phái sinh VN30F).
6. backend/adapter/redis_bus.py: Redis Pub/Sub Bus kết nối Worker 1 (Listener) và Worker 2 (Execution).
7. 3 Lớp Bảo Vệ & Persistence Nora:
   - Đo trượt giá Execution Delta (bps > 15 bps)
   - Order Rejection Watcher auto-retry với Fallback Size 50%
   - Feed Latency Guard (> 3.0s ngắt lệnh Entry)
   - Persistence chuẩn Nora: bot.json, events.jsonl, equity.jsonl, positions.json, heartbeat.json.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Đảm bảo import được backend khi chạy trực tiếp từ bất kỳ thư mục nào
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from backend.adapter.readings import MarketDataReader, MarketBar, MarketReading
from backend.analys.signal.signal import ProximaSignalEngine, SignalDecision
from backend.adapter.execution import (
    BotLifecycleState,
    ExitReason,
    InstrumentSpec,
    OrderAction,
    OrderStatus,
    PendingOrder,
    ProtectiveStatus,
    SPEC_CATALOG,
    TradeCycleResult,
    UniversalExecutionModel,
    generate_client_order_id,
    get_universal_spec,
    sync_okx_specs,
)
from backend.adapter.runner import (
    AdapterRunner,
    MarketListenerWorker,
    ExecutionWorker,
    RedisBus,
    create_decoupled_proxima_bot,
)


def get_btc_spec() -> InstrumentSpec:
    """Spec OKX thật từ instruments.json."""
    return get_universal_spec("BTC-USDT-SWAP")


def test_adapter_readings_late_bar_recomputes_anchor():
    """Kiểm tra adapter/readings.py: Late bar thực sự recompute Anchor Bar và chuyển WAITING_CATCHUP thành complete."""
    reader = MarketDataReader(symbol="BTC-USDT-SWAP", anchor_hours=1, warmup_required=1, grace_period_minutes=15)

    start_ts = (1700000000000 // 3600000) * 3600000
    base_price = 80000.0

    # 1. Nạp 53 nến cho giờ 1 (thiếu 1 nến so với ngưỡng tối thiểu 54)
    for i in range(53):
        ts = start_ts + (i * 60000)
        px = base_price + (i * 2)
        reader.feed_1m_bar({"timestamp": ts, "open": px, "high": px + 5, "low": px - 5, "close": px, "volume": 10.0})

    # Dòng thời gian bước sang giờ 2 (phút 65)
    reader.feed_1m_bar({"timestamp": start_ts + (65 * 60000), "open": 80200.0, "high": 80205.0, "low": 80195.0, "close": 80200.0, "volume": 10.0})

    # Giờ 1 chưa đủ 54 nến -> Nằm trong incomplete_buckets (WAITING_CATCHUP), CHƯA có trong closed_1h_bars
    assert len(reader.closed_1h_bars) == 0
    assert start_ts in reader.incomplete_buckets
    assert reader.incomplete_buckets[start_ts]["status"] == "WAITING_CATCHUP"

    # 2. Bây giờ nến muộn thứ 54 của giờ 1 đến (vẫn trong grace period 15 phút)
    late_ts = start_ts + (53 * 60000)
    late_bar = {"timestamp": late_ts, "open": 80110.0, "high": 80500.0, "low": 80100.0, "close": 80110.0, "volume": 25.0}  # Tạo đỉnh High mới
    res_late = reader.feed_1m_bar(late_bar)
    assert res_late is not None

    # TỰ ĐỘNG RECOMPUTE: Giờ 1 đã đủ 54 nến -> Xóa khỏi incomplete và đưa vào closed_1h_bars!
    assert start_ts not in reader.incomplete_buckets
    assert len(reader.closed_1h_bars) == 1
    anchor_1 = reader.closed_1h_bars[0]
    assert anchor_1["timestamp"] == start_ts
    assert anchor_1["high"] == 80500.0  # Cập nhật đúng High mới từ late bar!


def test_analys_signal_cach_a_parity():
    """Kiểm tra analys/signal/signal.py: Parity chính xác theo Cách A (Upper=EMA+F*ATR, Lower=EMA-F*ATR, K_delta=2*F*ATR, z>F)."""
    engine = ProximaSignalEngine(ema_k=20, atr_period=14, f_multiplier=1.0, warmup_required=14)

    start_ts = 1700000000000
    closed_1h_bars = []
    # Nạp 15 nến 1h đóng với ATR ~ 200, Close ~ 80000
    for i in range(15):
        closed_1h_bars.append({
            "timestamp": start_ts + (i * 3600000),
            "open": 80000.0, "high": 80100.0, "low": 79900.0, "close": 80000.0, "volume": 100.0,
        })
    engine.update_anchor_indicators(closed_1h_bars)
    assert engine.is_warmed_up is True
    ema = engine._ema_val
    atr = engine._atr_val
    assert ema is not None and atr is not None
    assert atr > 0

    # Test trường hợp 1: High_1m = EMA + 2 * ATR (Vượt Upper nhưng chưa đủ z > 1.0 vì z = 0.5) -> FLAT/HOLD
    mild_breakout = {
        "timestamp": start_ts + 20 * 3600000,
        "open": ema + 1.5 * atr,
        "high": ema + 2.0 * atr,  # z = (EMA + 2ATR - (EMA + ATR)) / (2ATR) = 0.5 <= 1.0
        "low": ema + 1.0 * atr,
        "close": ema + 1.8 * atr,
        "volume": 10.0,
    }
    dec_mild = engine.evaluate(mild_breakout, position_context={"qty_contracts": 0.0})
    assert dec_mild.signal == "FLAT"
    assert dec_mild.intent == "HOLD"
    assert abs(dec_mild.z_score - 0.5) < 1e-4

    # Test trường hợp 2: High_1m = EMA + 3.5 * ATR (z = 1.25 > 1.0) -> PHÁT SIGNAL LONG CHUẨN CÁCH A
    strong_breakout = {
        "timestamp": start_ts + 20 * 3600000,
        "open": ema + 2.0 * atr,
        "high": ema + 3.5 * atr,  # z = (EMA + 3.5ATR - (EMA + ATR)) / (2ATR) = 1.25 > 1.0
        "low": ema + 1.5 * atr,
        "close": ema + 3.0 * atr,
        "volume": 50.0,
    }
    dec_strong = engine.evaluate(strong_breakout, position_context={"qty_contracts": 0.0})
    assert dec_strong.signal == "LONG"
    assert dec_strong.intent == "ENTRY"
    assert dec_strong.z_score > 1.0


def test_readings_regime_light_reference():
    """Kiểm tra Bước 1 (readings.py) tích hợp phân loại bối cảnh thị trường Regime tham khảo nhẹ."""
    reader = MarketDataReader(symbol="BTC-USDT-SWAP", anchor_hours=1, warmup_required=14)
    start_ts = 1700000000000
    base_px = 80000.0

    # Nạp 15 giờ nến 1h đóng với ATR ~ 200
    for h in range(15):
        h_ts = start_ts + (h * 3600000)
        for m in range(60):
            ts = h_ts + (m * 60000)
            reader.feed_1m_bar({
                "timestamp": ts,
                "open": base_px,
                "high": base_px + 100,
                "low": base_px - 100,
                "close": base_px,
                "volume": 10.0,
            })

    assert reader.is_warmed_up is True

    # Nến giá đóng vọt lên cao (> 0.8 ATR so với EMA) -> TREND_UP
    reading_trend = reader.feed_1m_bar({
        "timestamp": start_ts + (15 * 3600000) + 60000,
        "open": base_px + 250,
        "high": base_px + 300,
        "low": base_px + 240,
        "close": base_px + 280,
        "volume": 20.0,
    })
    assert reading_trend is not None
    assert reading_trend.regime in ("TREND_UP", "VOL_EXPANSION")
    assert "dist_from_ema_atr" in reading_trend.regime_context
    assert "strength" in reading_trend.regime_context
    assert reading_trend.to_dict()["regime"] == reading_trend.regime


def test_adapter_execution_oms_rules():
    """Kiểm tra adapter/execution.py tuân thủ toàn bộ quy tắc OMS chuẩn sàn."""
    spec = get_btc_spec()
    model = UniversalExecutionModel(spec=spec, capital=10000.0, auto_fill_simulation=False)

    # 1. Test Dynamic Cap theo vốn
    assert model.max_notional_cap_ac == 1000.0
    model.set_capital(20000.0)
    assert model.max_notional_cap_ac == 2000.0

    # 2. Test Sizing 3 cận an toàn
    contracts, coin_qty, notional_q, notional_ac, margin_ac = model.calculate_sizing(80000.0, 500.0, 1000.0)
    assert contracts > 0
    assert notional_ac <= 2000.0

    # 3. Test Tick-directed Rounding
    sl_buy, tp_buy = model.calculate_sl_tp("BUY", 80000.05, 500.0)
    assert sl_buy == 79250.0  # Floor
    assert tp_buy == 83200.1  # Ceil


def test_adapter_runner_full_cycle_and_audit():
    """Kiểm tra adapter/runner.py điều phối toàn trình: readings -> signal -> execution -> broker."""
    spec = get_btc_spec()
    reader = MarketDataReader(symbol="BTC-USDT-SWAP", warmup_required=1)
    model = UniversalExecutionModel(spec=spec, capital=10000.0, auto_fill_simulation=False)
    signal_engine = ProximaSignalEngine(warmup_required=1, atr_period=1)

    submitted_orders = []

    def mock_submit(action: OrderAction) -> str:
        submitted_orders.append(action)
        return "ack_ok"

    runner = AdapterRunner(
        reader=reader,
        execution_model=model,
        signal_engine=signal_engine,
        broker_order_submitter=mock_submit,
    )

    # Giả lập 65 nến 1m để hoàn tất 1 giờ nến
    start_ts = (1700000000000 // 3600000) * 3600000
    for i in range(65):
        ts = start_ts + (i * 60000)
        px = 80000.0 + (i * 20)
        bar = {
            "timestamp": ts,
            "open": px,
            "high": px + 15000 if i == 64 else px + 5,  # Breakout cực mạnh z > 1.0
            "low": px - 5,
            "close": px,
            "volume": 10.0,
        }
        runner.on_1m_bar(bar)

    assert runner.is_running is True

    # Nếu có lệnh phát sinh, gửi callback Fill
    if submitted_orders:
        action = submitted_orders[0]
        runner.handle_broker_fill(
            fill_px=action.expected_price,
            fill_qty=action.qty_contracts,
            fee=0.2,
            order_id=action.order_id,
            timestamp=start_ts + (65 * 60000),
            fill_id="fill_1",
        )
        assert runner.exec_model.pos.qty_contracts == action.qty_contracts

    # Test Graceful Pause
    runner.request_graceful_pause()
    assert runner.lifecycle_state == BotLifecycleState.PAUSE_ENTRY

    # Kiểm tra telemetry snapshot
    snap = runner.get_status_snapshot()
    assert snap["symbol"] == "BTC-USDT-SWAP"
    assert snap["lifecycle_state"] == "pause_entry"
    assert len(runner.execution_audit_log) > 0


def test_universal_specs_and_cfd_forex_cfs():
    """Kiểm tra Quy chuẩn sàn Đa tài sản: Crypto, CFS Vàng XAUUSD, Forex EURUSD, Phái sinh VN30F."""
    # 1. Crypto Perp
    btc = get_universal_spec("BTC-USDT-SWAP")
    assert btc.contract_value == 0.01
    assert btc.quote_currency == "USDT"

    # 2. Commodities CFS: XAUUSD (Gold)
    gold = get_universal_spec("XAUUSD")
    assert gold.contract_value == 100.0  # 1 lot = 100 oz
    assert gold.multiplier == 100.0
    assert gold.broker_margin_init == 0.01  # Đòn bẩy 1:100

    # 3. Forex CFS: EURUSD
    eur = get_universal_spec("EURUSD")
    assert eur.contract_value == 100_000.0  # 1 lot = 100k EUR
    assert eur.tickSz == 0.00001

    # 4. Index Futures: VN30F
    vn30 = get_universal_spec("VN30F")
    assert vn30.contract_value == 100_000.0  # 1 điểm = 100k VNĐ
    assert vn30.broker_margin_init == 0.17

    # 5. Sizing trên XAUUSD với vốn 50.000 USD (1 lot = 100 oz = $260.000; minSz = 0.01 lot = 1 oz = $2.600, vl_mult=1.0)
    gold_model = UniversalExecutionModel(spec=gold, capital=50000.0, vl_mult=1.0)
    gold_contracts, gold_qty, notional_q, notional_ac, margin_ac = gold_model.calculate_sizing(2600.0, 30.0, 60.0)
    assert gold_contracts >= gold.minSz
    assert notional_ac <= 5000.0  # Cap vốn


def test_redis_bus_and_two_workers_flow():
    """Kiểm tra kiến trúc 2 Worker qua Redis Bus: Worker 1 (Listener) -> Redis -> Worker 2 (Execution)."""
    bus = RedisBus(in_memory_only=True)
    spec = get_universal_spec("ETH-USDT-SWAP")

    received_readings = []
    received_actions = []

    def mock_broker_submit(action: OrderAction) -> str:
        received_actions.append(action)
        return "order_ok"

    listener, exec_worker, runner = create_decoupled_proxima_bot(
        symbol="ETH-USDT-SWAP",
        spec=spec,
        capital=10000.0,
        redis_bus=bus,
        broker_order_submitter=mock_broker_submit,
    )

    # Đăng ký nhận market reading từ bus để xác minh Worker 1 bắn lên Redis
    bus.subscribe_market("ETH-USDT-SWAP", lambda reading: received_readings.append(reading))

    # Nạp 1 nến vào Worker 1
    start_ts = 1700000000000
    bar = {
        "timestamp": start_ts,
        "open": 3000.0,
        "high": 3010.0,
        "low": 2990.0,
        "close": 3005.0,
        "volume": 200.0,
    }
    reading = listener.on_raw_bar(bar)

    assert reading is not None
    # Xác minh Worker 1 đã publish reading lên Redis và Subscriber đã nhận
    assert len(received_readings) >= 1
    assert received_readings[-1]["symbol"] == "ETH-USDT-SWAP"
    assert received_readings[-1]["close"] == 3005.0

    # 2. Xác minh Worker 2 xử lý tiếp nến breakout từ Redis và phát sinh lệnh mà KHÔNG bị chặn bởi duplicate bar
    runner.signal_engine._ema_val = 3000.0
    runner.signal_engine._atr_val = 10.0
    runner.reader._cached_ema = 3000.0
    runner.reader._cached_atr = 10.0

    bar_breakout = {
        "timestamp": start_ts + 60000,
        "open": 3000.0,
        "high": 3050.0,
        "low": 2995.0,
        "close": 3045.0,
        "volume": 200.0,
    }
    reading2 = listener.on_raw_bar(bar_breakout)
    assert reading2 is not None

    # Xác minh Worker 2 đã nhận MarketReading từ Redis và phát lệnh thành công sang Broker
    assert len(received_actions) >= 1
    assert received_actions[-1].action_type == "ENTRY"
    assert received_actions[-1].side == "BUY"
    assert received_actions[-1].qty_contracts > 0


def test_execution_safeguards_and_persistence():
    """Kiểm tra 3 chốt bảo vệ thực thi và hệ thống persistence chuẩn Nora:
    1. Trượt giá Execution Delta (bps > 15 bps cảnh báo).
    2. Order Rejection Watcher auto-retry với Fallback Size 50%.
    3. Feed Latency Guard (> 3.0s ngắt lệnh mới).
    4. Ghi file persistence: bot.json, events.jsonl, equity.jsonl, positions.json, heartbeat.json.
    """
    temp_dir = tempfile.mkdtemp(prefix="nora_test_bot_")
    try:
        spec = get_btc_spec()
        reader = MarketDataReader(symbol="BTC-USDT-SWAP", warmup_required=1)
        model = UniversalExecutionModel(spec=spec, capital=10000.0, auto_fill_simulation=False)

        submitted_orders = []

        def mock_submit(action: OrderAction) -> str:
            submitted_orders.append(action)
            return "ok"

        runner = AdapterRunner(
            reader=reader,
            execution_model=model,
            broker_order_submitter=mock_submit,
            bot_dir=temp_dir,
            bot_id="test_bot_p1",
            mode="paper",
            max_execution_delta_bps=15.0,
            max_rejection_retries=2,
            max_feed_latency_s=3.0,
            check_latency=True,
        )

        # ── Test 1: Kiểm tra Persistence Files đã được sinh ──
        assert os.path.isfile(os.path.join(temp_dir, "bot.json"))
        with open(os.path.join(temp_dir, "bot.json")) as f:
            bot_data = json.load(f)
            assert bot_data["bot_id"] == "test_bot_p1"
            assert bot_data["status"] == "running"

        # ── Test 2: Feed Latency Guard (> 3.0s) ──
        # Nến cũ cách đây 10 giây (10.000 ms)
        stale_ts = int(time.time() * 1000) - 10_000
        stale_bar = {
            "timestamp": stale_ts,
            "open": 80000.0, "high": 80005.0, "low": 79995.0, "close": 80000.0, "volume": 10.0,
        }
        res_stale = runner.on_1m_bar(stale_bar)
        # Nến trễ > 3.0s bị chặn không phát lệnh
        assert res_stale is None
        # Kiểm tra event audit đã ghi FEED_LATENCY_EXCEEDED
        events = [e for e in runner.execution_audit_log if e["event"] == "FEED_LATENCY_EXCEEDED"]
        assert len(events) >= 1

        # ── Test 3: Trượt giá Execution Delta Watcher (> 15 bps) ──
        # Giả lập phát một lệnh mong đợi giá 80.000, nhưng sàn khớp 80.200 (lệch 25 bps > 15 bps)
        order_action = OrderAction(
            action_type="ENTRY",
            side="BUY",
            qty_contracts=0.10,
            coin_qty=0.001,
            expected_price=80000.0,
            notional_quote=80.0,
            notional_account=80.0,
            margin_account=1.6,
            order_id="ord_test_slippage",
        )
        if order_action.order_id:
            runner._last_orders[order_action.order_id] = order_action

        runner.handle_broker_fill(
            fill_px=80200.0,  # Lệch 25 bps
            fill_qty=0.10,
            order_id="ord_test_slippage",
            timestamp=int(time.time() * 1000),
        )

        delta_warnings = [e for e in runner.execution_audit_log if e["event"] == "EXECUTION_DELTA_WARNING"]
        assert len(delta_warnings) >= 1
        assert delta_warnings[-1]["payload"]["delta_bps"] == 25.0

        # ── Test 4: Order Rejection Watcher & Auto-retry Fallback Size (50%) ──
        rej_order = OrderAction(
            action_type="ENTRY",
            side="BUY",
            qty_contracts=0.04,  # Gốc 4 lot
            coin_qty=0.0004,
            expected_price=80000.0,
            notional_quote=32.0,
            notional_account=32.0,
            margin_account=0.64,
            order_id="ord_to_reject",
        )
        if rej_order.order_id:
            runner._last_orders[rej_order.order_id] = rej_order
        sub_len_before = len(submitted_orders)

        runner.handle_broker_reject(order_id="ord_to_reject", reason="Margin exceeded")

        # Tự động retry với 50% size: 0.04 * 0.5 = 0.02
        assert len(submitted_orders) == sub_len_before + 1
        retried_order = submitted_orders[-1]
        assert retried_order.qty_contracts == 0.02
        assert "retry" in retried_order.order_id

        # ── Test 5: Xác minh nội dung persistence files ──
        assert os.path.isfile(os.path.join(temp_dir, "events.jsonl"))
        assert os.path.isfile(os.path.join(temp_dir, "equity.jsonl"))
        assert os.path.isfile(os.path.join(temp_dir, "positions.json"))
        assert os.path.isfile(os.path.join(temp_dir, "heartbeat.json"))

        with open(os.path.join(temp_dir, "positions.json")) as f:
            pos_json = json.load(f)
            assert len(pos_json) == 1
            assert pos_json[0]["symbol"] == "BTC-USDT-SWAP"
            assert pos_json[0]["qty"] == 0.10

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_proxima_parameter_sweep_scan():
    """Kiểm tra Scan Backtest quét ma trận tham số Proxima (R10/R15/R25, VL, TP)."""
    from backend.jobs.runner.alpha import run_proxima_parameter_sweep

    # Tạo chuỗi 70 nến 1m nhân tạo có cả trend và biến động
    start_ts = (1700000000000 // 3600000) * 3600000
    candles = []
    base_px = 80000.0
    for i in range(70):
        ts = start_ts + (i * 60000)
        px = base_px + (i * 15)
        # Nến 65 tạo breakout cực mạnh
        high = px + 15000 if i == 65 else px + 10
        candles.append({
            "timestamp": ts,
            "open": px,
            "high": high,
            "low": px - 10,
            "close": px,
            "volume": 50.0,
        })

    out = run_proxima_parameter_sweep({
        "symbol": "BTC-USDT-SWAP",
        "capital": 10000.0,
        "candles": candles,
        "r_grid": [0.10, 0.15, 0.25],
        "vl_grid": [0.75, 1.0, 1.25],
        "tp_grid": [0.8, 1.0],
        "f_grid": [1.0],
    })

    assert out["status"] == "success"
    # 3 (R) * 3 (VL) * 2 (TP) * 1 (F) = 18 cấu hình
    assert out["variants_tested"] == 18
    assert len(out["results"]) == 18
    assert out["best_variant"] is not None
    # Xác minh các cấu hình được sắp xếp theo net_pnl giảm dần
    for i in range(len(out["results"]) - 1):
        assert out["results"][i]["net_pnl"] >= out["results"][i + 1]["net_pnl"]


def test_live_runner_proxima_dispatch_and_stop():
    """Kiểm tra live runner tích hợp Proxima: resolve_live_source, factory, và force close khi dừng bot."""
    from backend.jobs.runner.live import resolve_live_source
    from backend.jobs import tasks
    from backend.adapter.runner import create_decoupled_proxima_bot
    from backend.adapter.execution import get_universal_spec, ExitReason

    # 1. Kiểm tra resolve_live_source với Proxima
    src = resolve_live_source({
        "strategy_type": "proxima",
        "symbols": ["BTC-USDT-SWAP"],
        "base_frame": "1m",
    })
    assert src["strategy_type"] == "proxima"
    assert src["base_frame"] == "1m"
    assert "BTC@perp" in src["symbols"]

    # 2. Kiểm tra create_decoupled_proxima_bot với config sếp (R=0.15, VL=0.75, TP=0.8, F=1.0)
    spec = get_universal_spec("BTC-USDT-SWAP")
    temp_dir = tempfile.mkdtemp(prefix="nora_proxima_live_")
    try:
        listener, exec_worker, runner = create_decoupled_proxima_bot(
            symbol="BTC-USDT-SWAP",
            spec=spec,
            capital=10000.0,
            r_ratio=0.15,
            vl_mult=0.75,
            tp_mult=0.8,
            f_mult=1.0,
            mode="paper",
            bot_dir=temp_dir,
            bot_id="proxima_btc_test",
        )
        assert runner.exec_model.r_ratio == 0.15
        assert runner.exec_model.vl_mult == 0.75
        assert runner.signal_engine.f_multiplier == 1.0
        assert runner.signal_engine.tp_mult == 0.8

        # Giả lập mở vị thế và đóng khẩn cấp khi người dùng gửi cờ dừng
        runner.exec_model.pos.qty_contracts = 0.5
        runner.exec_model.pos.entry_price = 80000.0
        action = runner.force_close_all_positions(price=80500.0, reason=ExitReason.SESSION_CUTOFF)
        assert action is not None
        assert action.action_type == "CLOSE_ALL"
        assert action.side == "SELL"
        assert runner.exec_model.pos.qty_contracts == 0.0

        # 3. Kiểm tra tasks.run_proxima_sweep với tập nến mô phỏng nhanh
        mock_candles = [
            {
                "timestamp": 1700000000000 + i * 60000,
                "open": 80000.0 + (i % 5) * 10,
                "high": 80050.0 + (i % 5) * 10,
                "low": 79950.0 + (i % 5) * 10,
                "close": 80010.0 + (i % 5) * 10,
                "volume": 5.0,
            }
            for i in range(35)
        ]
        sweep_out = tasks.run_proxima_sweep({
            "symbol": "BTC-USDT-SWAP",
            "r_list": [0.15],
            "vl_list": [0.75],
            "tp_list": [0.8],
            "f_list": [1.0],
            "capital": 10000.0,
            "candles": mock_candles,
        })
        assert sweep_out["results"][0]["r_ratio"] == 0.15
        assert sweep_out["results"][0]["vl_mult"] == 0.75
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_adapter_flexible_anchor_and_direction():
    """Kiểm tra Step 2 & 3: Đa khung Anchor linh hoạt (15m, 30m) & Chiều tín hiệu Breakout vs Mean Reversion."""
    # 1. Khung Anchor 15m
    reader_15m = MarketDataReader(symbol="BTC-USDT-SWAP", anchor_tf="15m", warmup_required=5)
    base_ts = (1700000000000 // (15 * 60000)) * (15 * 60000)  # Căn chỉnh chuẩn mốc biên 15m (900,000ms)
    
    # Nạp 5 khung 15m (mỗi khung 15 nến 1m + nến kích hoạt chốt khung cuối = 76 nến 1m)
    for i in range(76):
        t = base_ts + i * 60000
        p = 80000.0 + (i % 10) * 5.0
        reading = reader_15m.feed_1m_bar({
            "timestamp": t,
            "open": p,
            "high": p + 10.0,
            "low": p - 10.0,
            "close": p + 2.0,
            "volume": 1.0,
        })
    assert reader_15m.is_warmed_up
    assert len(reader_15m.closed_1h_bars) >= 5
    assert reader_15m.anchor_minutes == 15

    # 2. Chiều tín hiệu Mean Reversion vs Breakout
    reader_mr = MarketDataReader(symbol="BTC-USDT-SWAP", anchor_tf="1h", warmup_required=1, signal_mode="mean_reversion")
    # Nạp nến khởi tạo để có EMA và ATR
    reader_mr.closed_1h_bars = [
        {"timestamp": 1000, "open": 80000.0, "high": 80500.0, "low": 79500.0, "close": 80000.0, "volume": 100.0}
    ]
    reader_mr._cached_ema = 80000.0
    reader_mr._cached_atr = 200.0

    # Nến 1m vượt đỉnh cực mạnh: High = 80800 (> Upper 80200) -> z > 1
    # Với Mean Reversion: Đánh SHORT (khi quá mua)
    bar_high = {"timestamp": 2000, "open": 80000.0, "high": 80800.0, "low": 80000.0, "close": 80750.0, "volume": 10.0}
    read_mr = reader_mr.feed_1m_bar(bar_high)
    assert read_mr is not None
    assert read_mr.z_score > 1.0
    assert read_mr.breakout_signal == "SHORT"  # Mean Reversion


def test_adapter_running_bar_and_feed_tick():
    """Kiểm tra Step 2 & Risk 2: Cơ chế luồng tick 1s & nến chạy (running 1m bar)."""
    reader = MarketDataReader(symbol="BTC-USDT-SWAP", anchor_tf="1h", warmup_required=1)
    reader._cached_ema = 80000.0
    reader._cached_atr = 100.0

    t0 = 1700000000000  # Khởi đầu phút
    # Tick 1: Giá mở 80000
    r1 = reader.feed_tick(price=80000.0, size=0.5, timestamp_ms=t0)
    assert r1 is not None
    assert r1.open == 80000.0
    assert r1.high == 80000.0
    assert r1.low == 80000.0

    # Tick 2: Giật lên 80350 (vượt Upper 80100 + K_delta 200) lúc giây thứ 15
    r2 = reader.feed_tick(price=80350.0, size=1.0, timestamp_ms=t0 + 15000)
    assert r2.high == 80350.0
    assert r2.close == 80350.0
    assert r2.z_score > 1.0
    assert r2.breakout_signal == "LONG"  # Phát hiện breach tức thời tại t mà không cần đợi nến đóng!


def test_adapter_redis_delivery_guarantees():
    """Kiểm tra Step 4 & Risk 6: Đảm bảo độ tin cậy bus truyền tin (Seq ID, Backlog, Gap Detection, ACK)."""
    bus = RedisBus(in_memory_only=True)
    received = []

    def on_market(reading):
        received.append(reading)

    bus.subscribe_market("BTC-USDT-SWAP", on_market)

    # Bắn 3 tin nhắn
    bus.publish_market_reading("BTC-USDT-SWAP", {"seq_mock": 1, "p": 80000.0})
    bus.publish_market_reading("BTC-USDT-SWAP", {"seq_mock": 2, "p": 80100.0})
    bus.publish_market_reading("BTC-USDT-SWAP", {"seq_mock": 3, "p": 80200.0})

    assert len(received) == 3
    assert received[0]["seq_mock"] == 1
    assert received[2]["seq_mock"] == 3

    # Kiểm tra backlog buffer có lưu đúng 3 envelopes
    channel = "nora:market:BTC-USDT-SWAP"
    backlog = bus.get_backlog(channel)
    assert len(backlog) == 3
    assert backlog[0]["_seq_id"] == 1
    assert backlog[2]["_seq_id"] == 3

    # Kiểm tra cơ chế ACK
    bus.ack(channel, seq_id=1)
    assert 1 in bus._acks_received.get(channel, set())


def test_adapter_idempotent_order_ids_and_reconciliation():
    """Kiểm tra Step 5 & Risk 7: Idempotent Client Order ID & Order State Reconciliation."""
    cl_id1 = generate_client_order_id("bot_paper_01", cycle_id=1, action_type="ENTRY", bar_ts=1700000000000, attempt=0)
    cl_id2 = generate_client_order_id("bot_paper_01", cycle_id=1, action_type="ENTRY", bar_ts=1700000000000, attempt=0)
    cl_id_retry = generate_client_order_id("bot_paper_01", cycle_id=1, action_type="ENTRY", bar_ts=1700000000000, attempt=1)

    assert cl_id1 == cl_id2  # Bất biến tuyệt đối
    assert cl_id1 == cl_id_retry  # Retry giữ nguyên logical clOrdId để tránh double fill
    
    cl_id_other = generate_client_order_id("bot_paper_01", cycle_id=1, action_type="CLOSE", bar_ts=1700000000000)
    assert cl_id1 != cl_id_other
    assert len(cl_id1) <= 32  # Chuẩn OKX

    # Kiểm tra Reconciliation
    spec = get_universal_spec("BTC-USDT-SWAP")
    model = UniversalExecutionModel(spec=spec, capital=10000.0, auto_fill_simulation=False)
    model.pending_order = PendingOrder(
        order_id=cl_id1,
        action_type="ENTRY",
        side="BUY",
        requested_qty=0.1,
        expected_price=80000.0,
        created_ts=1700000000000,
    )

    # Trùng fill sai order_id -> từ chối
    assert model.reconcile_order_event(order_id="wrong_id", event_type="FILLED", fill_price=80000.0) is None
    assert model.pos.qty_contracts == 0.0

    # Khớp đúng order_id -> cập nhật vị thế chuẩn xác
    model.reconcile_order_event(order_id=cl_id1, event_type="FILLED", fill_price=80000.0, fill_qty=0.1)
    assert model.pos.qty_contracts == 0.1
    assert model.pos.entry_price == 80000.0


def test_master_portfolio_ledger_accounting_invariants():
    """Kiểm tra MasterPortfolioLedger và 5 Invariants Kế toán Quỹ chuẩn xác."""
    from backend.core.portfolio import MasterPortfolioLedger, RiskPolicyConfig

    ledger = MasterPortfolioLedger(initial_capital=10_000.0, reserve_floor=0.0)
    # Đăng ký 5 sleeve tương ứng 5 bot với mức cấu hình mặc định đề xuất: 1,000 USDT mỗi bot
    for code in ["a", "b", "c", "d", "e"]:
        ledger.register_sleeve(f"sleeve_{code}", f"Bot {code.upper()} Sleeve", 1000.0)

    # Trạng thái ban đầu:
    assert ledger.initial_capital == 10000.0
    assert ledger.total_allocated_capital == 5000.0
    assert ledger.unallocated_capital == 5000.0
    assert ledger.available_to_allocate == 5000.0
    assert ledger.master_cash == 10000.0
    assert ledger.master_equity == 10000.0
    assert ledger.deployable_cash == 10000.0
    assert ledger.committed_margin == 0.0
    assert ledger.free_cash == 10000.0

    # 1. Khớp fill cho Sleeve A: Lãi +100 USDT, phí 2 USDT
    res1 = ledger.record_fill(
        fill_id="fill_001",
        sleeve_id="sleeve_a",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        qty=0.1,
        price=81000.0,
        fee=2.0,
        realized_gain=100.0,
    )
    assert res1 is True
    # Kiểm tra Idempotent: Gửi lại fill_001 bị từ chối
    assert ledger.record_fill(fill_id="fill_001", sleeve_id="sleeve_a", symbol="BTC-USDT-SWAP", side="SELL", qty=0.1, price=81000.0) is False

    # 2. Khớp fill cho Sleeve B: Lỗ -40 USDT, phí 2 USDT
    ledger.record_fill(
        fill_id="fill_002",
        sleeve_id="sleeve_b",
        symbol="ETH-USDT-SWAP",
        side="SELL",
        qty=1.0,
        price=2400.0,
        fee=2.0,
        realized_gain=-40.0,
    )

    # 3. Cập nhật lãi thả nổi
    ledger.update_unrealized(sleeve_id="sleeve_a", unrealized=25.0, used_margin=200.0)
    ledger.update_unrealized(sleeve_id="sleeve_c", unrealized=-10.0, used_margin=150.0)

    # Kiểm tra các giá trị kế toán Master:
    # Net realized: (100 - 2) + (-40 - 2) = 98 - 42 = +56 USDT
    assert ledger.master_realized_pnl == 60.0
    assert ledger.master_fees == 4.0
    assert ledger.master_cash == 10056.0
    # Equity = 10056 + (25 - 10) = 10071.0 USDT
    assert ledger.master_equity == 10071.0
    assert ledger.committed_margin == 350.0
    # Free cash = 10056 - 350 = 9706.0 USDT (tiền mặt chưa ký quỹ)
    assert ledger.free_cash == 9706.0
    assert ledger.deployable_cash == 10056.0

    # 4. Kiểm toán toàn bộ 6 Invariants toán học
    invariants = ledger.verify_invariants()
    for name, ok in invariants.items():
        assert ok is True, f"Invariant {name} violated!"

    # Snapshot UI không lỗi và đối soát khớp tuyệt đối 0.0
    snap = ledger.get_snapshot()
    assert snap["portfolio_summary"]["initial_capital"] == 10000.0
    assert snap["portfolio_summary"]["total_allocated_capital"] == 5000.0
    assert snap["portfolio_summary"]["unallocated_capital"] == 5000.0
    assert snap["portfolio_summary"]["available_to_allocate"] == 5000.0
    assert snap["portfolio_summary"]["free_cash"] == 9706.0
    assert snap["portfolio_summary"]["master_cash"] == 10056.0
    assert snap["portfolio_summary"]["master_equity"] == 10071.0
    assert snap["reconciliation"]["capital_discrepancy"] == 0.0
    assert snap["reconciliation"]["equity_discrepancy"] == 0.0
    assert snap["reconciliation"]["pnl_discrepancy"] == 0.0
    assert len(snap["sleeves"]) == 5


def test_portfolio_admission_controller_rules():
    """Kiểm tra Cổng soát vé rủi ro PortfolioAdmissionController & Dynamic Isolated Margin."""
    from backend.core.portfolio import MasterPortfolioLedger, PortfolioAdmissionController
    from backend.adapter.execution import determine_execution_td_mode

    ledger = MasterPortfolioLedger(initial_capital=10_000.0, reserve_floor=0.0)
    ledger.register_sleeve("sleeve_a", "Bot A Sleeve", 1000.0)
    controller = PortfolioAdmissionController(ledger)

    # 0. Kiểm tra admit_bot_launch khi bật bot mới
    # Đang có sleeve_a chiếm 1,000 USDT -> còn 9,000 USDT unallocated
    ok_launch, _ = controller.admit_bot_launch(4000.0)
    assert ok_launch is True

    # 0a. Vượt quá hạn mức vốn gốc chưa cấp (9,000 USDT)
    ok_over, reason_over = controller.admit_bot_launch(9500.0)
    assert ok_over is False
    assert "EXCEEDS_INITIAL_ALLOCATION_HEADROOM" in reason_over

    # 0b. Vượt quá hạn mức Master Equity thực tế (tránh cấp tiền ảo khi danh mục đang lỗ)
    eq_ledger = MasterPortfolioLedger(initial_capital=10_000.0, reserve_floor=0.0)
    eq_ledger.register_sleeve("sleeve_test", "Bot Test", 1000.0)
    eq_controller = PortfolioAdmissionController(eq_ledger)

    eq_ledger.record_fill(
        fill_id="fill_macro_loss",
        sleeve_id="sleeve_test",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        qty=1.0,
        price=1000.0,
        fee=0.0,
        realized_gain=-4000.0,
    )
    # Master cash = 6,000, Master equity = 6,000. Đã cấp: 1,000. Headroom từ equity = 5,000.
    assert eq_ledger.capital_headroom_from_equity == 5000.0
    ok_eq_over, reason_eq_over = eq_controller.admit_bot_launch(5500.0)
    assert ok_eq_over is False
    assert "EXCEEDS_EQUITY_HEADROOM" in reason_eq_over

    # 1. Lệnh bình thường trong hạn mức -> Chấp nhận
    ok, reason = controller.admit_order(
        sleeve_id="sleeve_a",
        side="BUY",
        requested_qty=0.01,
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,  # 10x
        sl_price=79000.0,
    )
    assert ok is True
    assert reason == "ADMITTED"

    # 2. Lệnh rủi ro SL vượt ngưỡng max_loss_per_trade (15 USDT)
    # Lỗ: |80000 - 60000| * 0.1 * 0.01 = 20000 * 0.001 = 20 USDT > 15 USDT
    ok, reason = controller.admit_order(
        sleeve_id="sleeve_a",
        side="BUY",
        requested_qty=0.1,
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,
        sl_price=60000.0,
    )
    assert ok is False
    assert "RISK_PER_TRADE_EXCEEDED" in reason

    # 3. Lệnh vượt hạn mức Sleeve Margin (cần 1,200 USDT ký quỹ > 1,000 USDT)
    ok, reason = controller.admit_order(
        sleeve_id="sleeve_a",
        side="BUY",
        requested_qty=12.0,
        price=10000.0,
        contract_value=0.1,
        margin_rate=0.1,  # 12 * 0.1 * 10000 * 0.1 = 1200 USDT
    )
    assert ok is False
    assert "SLEEVE_MARGIN_EXCEEDED" in reason

    # 4. Giả lập Sleeve Drawdown vượt ngưỡng (mất > 150 USDT trên 1,000 USDT)
    ledger.record_fill(
        fill_id="fill_loss_deep",
        sleeve_id="sleeve_a",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        qty=1.0,
        price=80000.0,
        fee=10.0,
        realized_gain=-160.0,
    )
    assert ledger.sleeves["sleeve_a"].status == "LOCKED"

    # Khi đã LOCKED -> Từ chối vào lệnh mới
    ok, reason = controller.admit_order(
        sleeve_id="sleeve_a",
        side="BUY",
        requested_qty=0.01,
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,
    )
    assert ok is False
    assert "SLEEVE_LOCKED_MAX_LOSS" in reason

    # Lệnh đóng vị thế (reduce-only) thì vẫn luôn được chấp nhận
    ok, reason = controller.admit_order(
        sleeve_id="sleeve_a",
        side="SELL",
        requested_qty=0.01,
        price=80000.0,
        contract_value=0.01,
        margin_rate=0.1,
        is_reduce_only=True,
    )
    assert ok is True
    assert reason == "ADMITTED_REDUCE_ONLY"

    # 5. Kiểm tra determine_execution_td_mode theo Account Mode
    td_mode, pos_side = determine_execution_td_mode({"posMode": "net_mode"}, "SWAP")
    assert td_mode == "isolated"
    assert pos_side == "net"

    td_mode2, pos_side2 = determine_execution_td_mode({"posMode": "long_short_mode"}, "SWAP")
    assert td_mode2 == "isolated"
    assert pos_side2 == "long"



def test_adapter_shadow_mode_and_specs_sync():
    """Kiểm tra Step 6 & Risk 9: Đồng bộ OKX Specs và Chế độ Shadow Mode an toàn không lệnh ngoài sàn."""
    # 1. Kiểm tra sync_okx_specs
    spec = sync_okx_specs("BTC-USDT-SWAP", timeout=2.0)
    assert spec.symbol == "BTC-USDT-SWAP"
    assert spec.ctVal == 0.01
    assert spec.lotSz == 0.01

    # 2. Kiểm tra Shadow Mode: Không gửi lệnh ra ngoài sàn, tự khớp mô phỏng nội bộ
    temp_dir = tempfile.mkdtemp()
    try:
        listener, worker, runner = create_decoupled_proxima_bot(
            symbol="BTC-USDT-SWAP",
            spec=spec,
            capital=10000.0,
            bot_dir=temp_dir,
            shadow_mode=True,
        )
        assert runner.shadow_mode is True

        # Giả lập nến có tín hiệu Long
        runner.reader._cached_ema = 80000.0
        runner.reader._cached_atr = 200.0
        runner.signal_engine._ema_val = 80000.0
        runner.signal_engine._atr_val = 200.0

        bar_breakout = {
            "timestamp": 1700000000000,
            "open": 80000.0,
            "high": 80700.0,
            "low": 79900.0,
            "close": 80600.0,
            "volume": 10.0,
        }
        action = runner.on_1m_bar(bar_breakout)
        assert action is not None
        assert action.action_type == "ENTRY"

        # Vì chạy shadow_mode -> vị thế nội bộ đã được khớp mô phỏng ngay mà không có lệnh broker ra ngoài!
        assert runner.exec_model.pos.qty_contracts > 0
        assert any(e["event"] == "SHADOW_FILL" for e in runner.execution_audit_log)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    print("Executing comprehensive decoupled adapter test suite...")
    test_adapter_readings_late_bar_recomputes_anchor()
    print("  ✓ test_adapter_readings_late_bar_recomputes_anchor PASSED")
    test_analys_signal_cach_a_parity()
    print("  ✓ test_analys_signal_cach_a_parity PASSED")
    test_adapter_execution_oms_rules()
    print("  ✓ test_adapter_execution_oms_rules PASSED")
    test_adapter_runner_full_cycle_and_audit()
    print("  ✓ test_adapter_runner_full_cycle_and_audit PASSED")
    test_universal_specs_and_cfd_forex_cfs()
    print("  ✓ test_universal_specs_and_cfd_forex_cfs PASSED")
    test_redis_bus_and_two_workers_flow()
    print("  ✓ test_redis_bus_and_two_workers_flow PASSED")
    test_execution_safeguards_and_persistence()
    print("  ✓ test_execution_safeguards_and_persistence PASSED")
    test_proxima_parameter_sweep_scan()
    print("  ✓ test_proxima_parameter_sweep_scan PASSED")
    test_adapter_flexible_anchor_and_direction()
    print("  ✓ test_adapter_flexible_anchor_and_direction PASSED")
    test_adapter_running_bar_and_feed_tick()
    print("  ✓ test_adapter_running_bar_and_feed_tick PASSED")
    test_adapter_redis_delivery_guarantees()
    print("  ✓ test_adapter_redis_delivery_guarantees PASSED")
    test_adapter_idempotent_order_ids_and_reconciliation()
    print("  ✓ test_adapter_idempotent_order_ids_and_reconciliation PASSED")
    test_adapter_shadow_mode_and_specs_sync()
    print("  ✓ test_adapter_shadow_mode_and_specs_sync PASSED")
    print(">>> ALL 13 DECOUPLED ADAPTER & SHADOW VERIFICATION TESTS PASSED! <<<")

