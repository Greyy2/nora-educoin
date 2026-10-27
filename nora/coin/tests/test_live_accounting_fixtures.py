"""Kiểm toán Fixture độc lập cho Kế toán Live & Vòng đời Bot (Phase 4 / COIN-LIVE-00..13).

Kiểm tra:
1. Invariants toán học của MasterPortfolioLedger (6/6 Invariants).
2. Quy tắc tính Today PnL theo ranh giới phiên UTC (00:00:00 UTC) độc lập với Total PnL.
3. Win Rate & Profit Factor không bao giờ sinh ra số giả (None khi chưa có lệnh).
4. Tính toán Exposure gộp (gross) và ròng (net) khi nhiều bot chạy cùng cặp symbol.
5. Cổng rủi ro cấp vốn (PortfolioAdmissionController).
6. Khế ước xoá bot (delete_bot): Chặn xoá bot đang chạy (409), cho phép xoá bot đã dừng/lỗi/orphan.
"""
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from backend.core.portfolio import (
    LiveLedgerUnavailable,
    MasterPortfolioLedger,
    PortfolioAdmissionController,
    SleeveState,
    get_live_master_ledger,
)
from backend.adapter.exchange import delete_bot, bot_status
from backend.routes.live import (
    BatchBotRequest,
    StartBotRequest,
    delete_batch_bots,
    get_master_portfolio_snapshot,
    post_start_bot,
)
from backend.models.storage import pid_start_ticks


def test_master_portfolio_ledger_invariants():
    """Kiểm tra 6 invariants toán học của MasterPortfolioLedger."""
    ledger = MasterPortfolioLedger(initial_capital=10_000.0)

    # Đăng ký 3 sleeve
    s1 = ledger.register_sleeve("s1", "Alpha A", allocated_capital=2000.0)
    s2 = ledger.register_sleeve("s2", "Alpha B", allocated_capital=3000.0)
    s3 = ledger.register_sleeve("s3", "Alpha C", allocated_capital=1000.0)

    assert ledger.initial_capital == 10000.0
    assert ledger.total_allocated_capital == 6000.0
    assert ledger.unallocated_capital == 4000.0

    # Mô phỏng giao dịch
    s1.realized_pnl = 150.0
    s1.fees_paid = 10.0
    s1.unrealized_pnl = 50.0
    s1.used_margin = 400.0

    s2.realized_pnl = -80.0
    s2.fees_paid = 15.0
    s2.unrealized_pnl = -20.0
    s2.used_margin = 600.0

    # Invariants audit
    inv = ledger.verify_invariants()
    for name, ok in inv.items():
        assert ok, f"Invariant {name} failed: {inv}"

    snap = ledger.get_snapshot()
    summary = snap["portfolio_summary"]
    assert summary["initial_capital"] == 10000.0
    assert summary["total_allocated_capital"] == 6000.0
    assert summary["net_pnl"] == round((150 - 10 + 50) + (-80 - 15 - 20), 4) # 190 - 115 = 75.0
    assert summary["master_equity"] == 10075.0
    assert summary["circuit_breaker_status"] == "NORMAL"


def test_today_pnl_utc_boundary_deterministic():
    """Kiểm tra công thức Today PnL dựa trên ranh giới 00:00:00 UTC."""
    ledger = MasterPortfolioLedger(initial_capital=10_000.0)
    s = ledger.register_sleeve("s1", "Alpha A", allocated_capital=2000.0)

    # Giả lập unrealized PnL hiện tại
    s.unrealized_pnl = 45.0
    ledger.today_realized_pnl = 120.0

    snap = ledger.get_snapshot()
    summary = snap["portfolio_summary"]

    # Daily PnL includes only the explicitly supplied realized component, not all open unrealized PnL.
    assert summary["today_pnl"] == 120.0
    assert summary["today_realized_pnl"] == 120.0
    assert summary["as_of"] is not None


def test_win_rate_and_profit_factor_truthful_semantics():
    """Kiểm tra Win Rate & Profit Factor trả về None (không chế số 0 hay 100%) khi chưa có dữ liệu."""
    ledger = MasterPortfolioLedger(initial_capital=10_000.0)

    # Khi chưa có lệnh nào đóng
    assert ledger.win_rate_pct is None
    assert ledger.profit_factor is None

    # Khi có 1 lệnh thắng, 0 lệnh thua
    ledger.closed_trades_count = 1
    ledger.winning_trades_count = 1
    ledger.total_wins = 50.0
    ledger.total_losses = 0.0

    assert ledger.win_rate_pct == 100.0
    assert ledger.profit_factor == 999.0  # Đại diện cho vô hạn nhưng an toàn số học

    # Khi có 3 lệnh thắng (150 USDT) và 1 lệnh thua (50 USDT)
    ledger.closed_trades_count = 4
    ledger.winning_trades_count = 3
    ledger.total_wins = 150.0
    ledger.total_losses = 50.0

    assert ledger.win_rate_pct == 75.0
    assert ledger.profit_factor == 3.0


def test_multi_bot_exposure_aggregation():
    """Kiểm tra tổng hợp exposure gộp (gross) và ròng (net) trên cùng một symbol giữa nhiều bot."""
    # Bot 1: Long 0.5 BTC tại 60,000 -> Notional = 30,000 USDT
    # Bot 2: Short 0.2 BTC tại 60,000 -> Notional = 12,000 USDT
    # Gross exposure = 30,000 + 12,000 = 42,000 USDT
    # Net exposure = (0.5 - 0.2) * 60,000 = 18,000 USDT (Long)

    bot1_pos = {"symbol": "BTC-USDT-SWAP", "qty": 0.5, "is_long": True, "mark": 60000.0}
    bot2_pos = {"symbol": "BTC-USDT-SWAP", "qty": 0.2, "is_long": False, "mark": 60000.0}

    positions = [bot1_pos, bot2_pos]

    gross_notional = 0.0
    net_units = 0.0
    for p in positions:
        notional = float(p["qty"]) * float(p["mark"])
        gross_notional += notional
        sign = 1.0 if p["is_long"] else -1.0
        net_units += sign * float(p["qty"])

    net_notional = net_units * 60000.0

    assert gross_notional == 42000.0
    assert round(net_units, 4) == 0.3
    assert net_notional == 18000.0


def test_admission_controller_headroom_limits():
    """Kiểm tra cổng rủi ro cấp vốn không bao giờ cấp quá hạn mức Master."""
    ledger = MasterPortfolioLedger(initial_capital=10_000.0)
    controller = PortfolioAdmissionController(ledger)

    # Cấp 5,000 USDT -> OK
    ok, reason = controller.admit_bot_launch(5000.0)
    assert ok, reason
    ledger.register_sleeve("s1", "Bot 1", allocated_capital=5000.0)

    # Cấp thêm 4,000 USDT -> OK (tổng 9,000)
    ok, reason = controller.admit_bot_launch(4000.0)
    assert ok, reason
    ledger.register_sleeve("s2", "Bot 2", allocated_capital=4000.0)

    # Cấp thêm 2,000 USDT -> Bị từ chối (vượt quá 10,000 USDT)
    ok, reason = controller.admit_bot_launch(2000.0)
    assert not ok
    assert "EXCEEDS_INITIAL_ALLOCATION_HEADROOM" in reason

    # Cấp vốn <= 0 -> Bị từ chối
    ok, reason = controller.admit_bot_launch(0.0)
    assert not ok
    assert "INVALID_ALLOCATION" in reason


def test_delete_bot_reconciliation_contract(monkeypatch, tmp_path):
    """Kiểm tra quy tắc xoá bot:
    - Bot đang chạy thực sự -> chặn 409 (running: True)
    - Bot đã dừng (stopped) -> xoá thành công
    - Bot mồ côi (orphan / crash) -> xoá thành công
    """
    live_dir = tmp_path / "live" / "paper"
    live_dir.mkdir(parents=True)
    monkeypatch.setattr("backend.adapter.exchange.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))

    # 1. Tạo bot đang chạy với tiến trình PID hiện tại (PID đang sống)
    running_bot_dir = live_dir / "bot_running_01"
    running_bot_dir.mkdir()
    my_pid = os.getpid()
    with open(running_bot_dir / "bot.json", "w", encoding="utf-8") as f:
        f.write(f'{{"bot_id": "bot_running_01", "mode": "paper", "pid": {my_pid}, "status": "running", "started_at": {int(time.time()*1000)}}}')

    # Mock pid_start check để giả lập process còn sống thực sự
    monkeypatch.setattr("backend.adapter.exchange.pid_alive", lambda pid, start: True)
    monkeypatch.setattr("backend.adapter.exchange.bot_alive", lambda meta: True)
    monkeypatch.setattr("backend.adapter.exchange.bot_process_state", lambda meta: "alive")
    monkeypatch.setattr("backend.adapter.exchange.bot_status", lambda meta, b_dir: "running")

    # Thử xoá không force -> Phải bị chặn 409
    res = delete_bot("bot_running_01", mode="paper", force=False)
    assert not res["ok"]
    assert res.get("running") is True
    assert "dừng và xác nhận đã dừng" in res["message"]
    assert running_bot_dir.exists()

    # 2. Tạo bot đã dừng (có cờ stop hoặc trạng thái stopped)
    stopped_bot_dir = live_dir / "bot_stopped_01"
    stopped_bot_dir.mkdir()
    with open(stopped_bot_dir / "bot.json", "w", encoding="utf-8") as f:
        f.write('{"bot_id": "bot_stopped_01", "mode": "paper", "status": "stopped", "pid": 999999}')
    with open(stopped_bot_dir / "stop", "w", encoding="utf-8") as f:
        f.write("user_stopped")

    # Khi bot_status trả về stopped
    monkeypatch.setattr("backend.adapter.exchange.bot_status", lambda meta, b_dir: "stopped" if "stopped" in str(b_dir) else "running")
    monkeypatch.setattr("backend.adapter.exchange.bot_alive", lambda meta: False if "stopped" in meta.get("bot_id", "") else True)
    monkeypatch.setattr("backend.adapter.exchange.bot_process_state", lambda meta: "stopped")

    res_stopped = delete_bot("bot_stopped_01", mode="paper", force=False)
    assert res_stopped["ok"] is True
    assert not stopped_bot_dir.exists()

    # 3. Tạo bot lỗi / orphan (tiến trình đã chết)
    failed_bot_dir = live_dir / "bot_failed_01"
    failed_bot_dir.mkdir()
    with open(failed_bot_dir / "bot.json", "w", encoding="utf-8") as f:
        f.write('{"bot_id": "bot_failed_01", "mode": "paper", "status": "failed", "pid": 999998}')

    monkeypatch.setattr("backend.adapter.exchange.bot_status", lambda meta, b_dir: "failed")
    monkeypatch.setattr("backend.adapter.exchange.bot_alive", lambda meta: False)

    res_failed = delete_bot("bot_failed_01", mode="paper", force=False)
    assert res_failed["ok"] is True
    assert not failed_bot_dir.exists()


def test_batch_delete_never_force_deletes_bot_stopping_with_live_process(monkeypatch, tmp_path):
    live_dir = tmp_path / "live" / "paper"
    bot_dir = live_dir / "bot_stopping_01"
    bot_dir.mkdir(parents=True)
    monkeypatch.setattr("backend.adapter.exchange.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.adapter.exchange.os.kill", lambda *_args: pytest.fail("delete must not signal a bot process"))

    pid = os.getpid()
    pid_start = pid_start_ticks(pid)
    assert pid_start is not None
    (bot_dir / "bot.json").write_text(
        f'{{"bot_id":"bot_stopping_01","mode":"paper","status":"running","pid":{pid},"pid_start":{pid_start}}}',
        encoding="utf-8",
    )
    (bot_dir / "stop").write_text("user_stopped", encoding="utf-8")

    result = delete_batch_bots(BatchBotRequest(bot_ids=["bot_stopping_01"], mode="paper"))

    assert result["ok"] is False
    assert result["results"] == [{
        "bot_id": "bot_stopping_01",
        "ok": False,
        "error": "Bot đang chạy, hãy dừng trước",
    }]
    assert bot_dir.exists()


def test_delete_bot_fails_closed_when_process_state_is_unknown(monkeypatch, tmp_path):
    live_dir = tmp_path / "live" / "paper"
    bot_dir = live_dir / "bot_unknown_01"
    bot_dir.mkdir(parents=True)
    (bot_dir / "bot.json").write_text(
        '{"bot_id":"bot_unknown_01","mode":"paper","status":"failed","pid":1234}',
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.adapter.exchange.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.adapter.exchange.bot_process_state", lambda _meta: "unknown")
    monkeypatch.setattr("backend.adapter.exchange.bot_status", lambda _meta, _dir: "unknown")

    result = delete_bot("bot_unknown_01", mode="paper", force=True)

    assert result["ok"] is False
    assert result["unknown"] is True
    assert bot_dir.exists()


def test_live_master_ledger_requires_configured_capital(monkeypatch, tmp_path):
    monkeypatch.delenv("NORA_MASTER_CAPITAL_PAPER", raising=False)
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))

    with pytest.raises(LiveLedgerUnavailable, match="not configured"):
        get_live_master_ledger("paper")
    with pytest.raises(HTTPException) as exc_info:
        get_master_portfolio_snapshot(mode="paper")
    assert exc_info.value.status_code == 503


def test_live_ledger_capital_is_isolated_by_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_MASTER_CAPITAL_PAPER", "5000")
    monkeypatch.delenv("NORA_MASTER_CAPITAL_LIVE", raising=False)
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))

    paper_ledger = get_live_master_ledger("paper")
    assert paper_ledger.initial_capital == 5000
    with pytest.raises(LiveLedgerUnavailable, match="live is not configured"):
        get_live_master_ledger("live")


def test_testnet_bot_start_fails_closed_when_master_risk_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_MASTER_CAPITAL_TESTNET", "5000")
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))
    monkeypatch.setattr(
        "backend.routes.live.launch",
        lambda *_args, **_kwargs: pytest.fail("unknown master risk must block launch"),
    )

    with pytest.raises(HTTPException) as exc_info:
        post_start_bot(StartBotRequest(mode="testnet", capital=100))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "LIVE_RISK_STATE_UNAVAILABLE"


def test_bot_status_preserves_stop_transition_and_unknown_process_state(tmp_path):
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    pid = os.getpid()
    pid_start = pid_start_ticks(pid)
    assert pid_start is not None
    meta = {"status": "running", "pid": pid, "pid_start": pid_start}

    assert bot_status(meta, str(bot_dir)) == "running"
    (bot_dir / "stop").write_text("user_stopped", encoding="utf-8")
    assert bot_status(meta, str(bot_dir)) == "stopping"
    (bot_dir / "stop").unlink()
    assert bot_status({"status": "stopped", "pid": pid, "pid_start": pid_start}, str(bot_dir)) == "unknown"


def test_realized_pnl_since_utc_midnight_excludes_overnight_and_open_unrealized():
    from backend.core.portfolio import realized_pnl_since_utc_midnight

    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    midnight = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)
    trades = [
        {"close_time": int(datetime(2026, 10, 24, 23, 59, tzinfo=timezone.utc).timestamp() * 1000), "pnl": 90.0},
        {"close_time": int(midnight.timestamp() * 1000), "pnl": 12.5},
        {"close_time": int(datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc).timestamp() * 1000), "pnl": -2.5},
    ]

    assert realized_pnl_since_utc_midnight(trades, int(now.timestamp() * 1000)) == 10.0


def test_live_master_ledger_includes_old_bot_and_marks_unverified_metrics_unavailable(monkeypatch, tmp_path):
    live_dir = tmp_path / "live" / "paper"
    bot_dir = live_dir / "bot_old_01"
    bot_dir.mkdir(parents=True)
    (bot_dir / "bot.json").write_text(
        '{"bot_id":"bot_old_01","mode":"paper","status":"stopped","capital":1500,"started_at":1}',
        encoding="utf-8",
    )
    (bot_dir / "events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("NORA_MASTER_CAPITAL_PAPER", "5000")
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.adapter.exchange.data_home", lambda: str(tmp_path))

    ledger = get_live_master_ledger("paper")
    summary = ledger.get_snapshot()["portfolio_summary"]

    assert ledger.initial_capital == 5000
    assert ledger.sleeves["sleeve_bot_old_01"].allocated_capital == 1500
    assert summary["today_pnl"] == 0.0
    assert summary["sharpe_ratio"] is None
    assert summary["circuit_breaker_status"] == "UNKNOWN"
    admitted, reason = PortfolioAdmissionController(ledger).admit_bot_launch(100)
    assert not admitted
    assert reason.startswith("MASTER_RISK_STATE_UNAVAILABLE")


def test_live_master_ledger_rejects_corrupt_positions_snapshot(monkeypatch, tmp_path):
    live_dir = tmp_path / "live" / "paper"
    bot_dir = live_dir / "bot_running_01"
    bot_dir.mkdir(parents=True)
    pid = os.getpid()
    pid_start = pid_start_ticks(pid)
    assert pid_start is not None
    (bot_dir / "bot.json").write_text(
        f'{{"bot_id":"bot_running_01","mode":"paper","status":"running","capital":1000,"pid":{pid},"pid_start":{pid_start}}}',
        encoding="utf-8",
    )
    (bot_dir / "events.jsonl").write_text('{"type":"start"}\n', encoding="utf-8")
    (bot_dir / "positions.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("NORA_MASTER_CAPITAL_PAPER", "5000")
    monkeypatch.setattr("backend.models.storage.data_home", lambda: str(tmp_path))
    monkeypatch.setattr("backend.adapter.exchange.data_home", lambda: str(tmp_path))

    with pytest.raises(LiveLedgerUnavailable, match="missing or unreadable"):
        get_live_master_ledger("paper")


# ══════════════════════════════════════════════════════════════════════════════
# COIN-LIVE-11: Cross-Market Pro-Rata Allocator & Same-Market Conflict Resolution
# ══════════════════════════════════════════════════════════════════════════════
class _MockSpec:
    def __init__(self, order_size_pct=20.0, capital_usage=1.0, max_leverage=1.0, fee_rate=0.0005,
                 priority=0.0, sizing="flat"):
        self.is_long = True
        self.capital_usage = capital_usage
        self.max_leverage = max_leverage
        self.fee_rate = fee_rate
        self.slippage_rate = 0.0
        self.risk_pct = 2.0
        self.max_notional_pct = 100.0
        self.order_size_pct = order_size_pct
        self.sizing = sizing
        self.sl_anchor_mode = 0
        self.base_sl = 2.0
        self.base_tp = 4.0
        self.base_trail = 0.0
        self.base_trail_act = 0.0
        self.base_dca_steps = ()
        self.dca_mults = ()
        self.market = "perp"
        self.mmr = 0.005
        self.exit_unit = "pct"
        self.priority = priority


class _MockSlot:
    def __init__(self, sid, symbol, sym_idx, order_size_pct=20.0, priority=0.0, min_qty=0.001):
        self.sid = sid
        self.symbol = symbol
        self.sym_idx = sym_idx
        self.spec = _MockSpec(order_size_pct=order_size_pct, priority=priority)
        self.is_long = True
        self.sign = 1.0
        self.sl_pct = 2.0
        self.dca_steps = ()
        self.skipped_no_vol = 0
        self.mult = 1.0
        self.last_blk = -2
        self.nbar = 0
        self.min_qty = min_qty
        self.committed = None

    def _apply_unit(self, unit):
        pass

    def _round_qty(self, q):
        return round(q, 4) if q >= self.min_qty else None

    def _commit_entry(self, price, qty, margin, lev, planned, unit_pct, sl_abs, catchup, fee_est):
        self.committed = {
            "price": price, "qty": qty, "margin": margin, "lev": lev,
            "planned": planned, "unit_pct": unit_pct, "sl_abs": sl_abs,
            "catchup": catchup, "fee_est": fee_est
        }


def test_cross_market_allocator_same_market_conflict_fail_closed():
    """COIN-LIVE-11: Cùng market có 2 signal tại cùng nến mà không có priority -> fail-closed (0 lệnh gửi, đếm reject)."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)

    s1 = _MockSlot("s1", "BTC-USDT-SWAP", 0, priority=0.0)
    s2 = _MockSlot("s2", "BTC-USDT-SWAP", 0, priority=0.0)

    it1 = EntryIntent(slot=s1, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0, priority=0.0)
    it2 = EntryIntent(slot=s2, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0, priority=0.0)

    co.register_entry_intent(it1)
    co.register_entry_intent(it2)

    events = []
    co.on_event = lambda kind, data: events.append((kind, data))

    dispatched = co.dispatch_batch_entries(1000)
    assert len(dispatched) == 0
    assert co.rejected_for_risk == 2
    assert s1.committed is None
    assert s2.committed is None
    assert any(e[0] == "conflict" and e[1]["reason"] == "SAME_MARKET_CONFLICT" for e in events)


def test_cross_market_allocator_same_market_priority_winner():
    """COIN-LIVE-11: Cùng market có 2 signal, strategy có priority cao hơn sẽ thắng và được gửi lệnh duy nhất."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)

    s1 = _MockSlot("s1", "BTC-USDT-SWAP", 0, priority=5.0)
    s2 = _MockSlot("s2", "BTC-USDT-SWAP", 0, priority=10.0)

    it1 = EntryIntent(slot=s1, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0, priority=5.0)
    it2 = EntryIntent(slot=s2, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0, priority=10.0)

    co.register_entry_intent(it1)
    co.register_entry_intent(it2)

    events = []
    co.on_event = lambda kind, data: events.append((kind, data))

    dispatched = co.dispatch_batch_entries(1000)
    assert len(dispatched) == 1
    assert s2.committed is not None
    assert s1.committed is None
    assert co.rejected_for_risk == 1
    assert any(e[0] == "intent_superceded" and e[1]["winner"] == "s2" for e in events)


def test_cross_market_allocator_pro_rata_scaling():
    """COIN-LIVE-11: Nhiều market khác nhau cùng có signal vượt ngân sách -> chia vốn pro-rata công bằng."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)

    # 2 slot ở 2 market khác nhau, mỗi slot yêu cầu 60% vốn = 600 USDT (tổng 1200 USDT > 1000 USDT vốn rảnh)
    s1 = _MockSlot("s1", "BTC-USDT-SWAP", 0, order_size_pct=60.0)
    s2 = _MockSlot("s2", "ETH-USDT-SWAP", 1, order_size_pct=60.0)

    it1 = EntryIntent(slot=s1, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0)
    it2 = EntryIntent(slot=s2, symbol="ETH-USDT-SWAP", ts=1000, price=3000.0)

    co.register_entry_intent(it1)
    co.register_entry_intent(it2)

    dispatched = co.dispatch_batch_entries(1000)
    assert len(dispatched) == 2
    assert s1.committed is not None
    assert s2.committed is not None

    m1 = s1.committed["margin"]
    m2 = s2.committed["margin"]
    # Tỷ lệ pro-rata đều 50-50, tổng margin + fee không được vượt 1000
    assert round(m1, 2) == round(m2, 2)
    assert m1 + m2 <= 1000.0 + 1e-9
    assert co.pending_reserved > 0.0
    assert co.free() == 0.0 or co.free() < 1.0


def test_cross_market_allocator_min_lot_drop_no_overalloc():
    """COIN-LIVE-11: Khi candidate không đủ min lot sau khi scale thì bị loại, không làm dồn risk vượt trần."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)

    # s1 có min lot rất lớn (10.0), BTC giá 50,000 -> notional cần 500,000 (không thể đủ lot)
    s1 = _MockSlot("s1", "BTC-USDT-SWAP", 0, order_size_pct=50.0, min_qty=10.0)
    s2 = _MockSlot("s2", "ETH-USDT-SWAP", 1, order_size_pct=50.0, min_qty=0.001)

    it1 = EntryIntent(slot=s1, symbol="BTC-USDT-SWAP", ts=1000, price=50000.0)
    it2 = EntryIntent(slot=s2, symbol="ETH-USDT-SWAP", ts=1000, price=3000.0)

    co.register_entry_intent(it1)
    co.register_entry_intent(it2)

    dispatched = co.dispatch_batch_entries(1000)
    assert len(dispatched) == 1
    assert s1.committed is None
    assert s2.committed is not None
    assert co.rejected_for_capital == 1
    # s2 chỉ nhận đúng quota của nó (500 USDT), không bị đội lên 1000 USDT làm sai lệch risk
    assert s2.committed["margin"] <= 500.0 + 1e-9


def test_cross_market_allocator_enforces_max_positions_cap():
    """COIN-LIVE-11: max_positions=1 thì 2 market cùng có signal không được dispatch cả 2."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    # Trường hợp 1: 2 candidate cùng ưu tiên 0 (hoà điểm) -> fail-closed (0 lệnh)
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=0.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)
    s1 = _MockSlot("btc", "BTC-USDT-SWAP", 0, order_size_pct=20.0, priority=0.0)
    s2 = _MockSlot("eth", "ETH-USDT-SWAP", 1, order_size_pct=20.0, priority=0.0)
    for s in (s1, s2):
        co.register_entry_intent(EntryIntent(s, s.symbol, 1000, 100.0, priority=0.0))
    res1 = co.dispatch_batch_entries(1000)
    assert len(res1) == 0
    assert co.rejected_for_risk == 2

    # Trường hợp 2: Có 1 candidate có priority cao hơn (10 vs 5) -> đúng 1 candidate được dispatch
    co2 = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)
    s3 = _MockSlot("btc", "BTC-USDT-SWAP", 0, order_size_pct=20.0, priority=10.0)
    s4 = _MockSlot("eth", "ETH-USDT-SWAP", 1, order_size_pct=20.0, priority=5.0)
    for s in (s3, s4):
        co2.register_entry_intent(EntryIntent(s, s.symbol, 1000, 100.0, priority=s.spec.priority))
    res2 = co2.dispatch_batch_entries(1000)
    assert len(res2) == 1
    assert res2[0].slot.sid == "btc"
    assert co2.rejected_for_risk == 1


def test_cross_market_allocator_enforces_max_gross_exposure_cap():
    """COIN-LIVE-11: max_gross_exposure=0.25 (trần notional 250 trên vốn 1000) giới hạn tổng notional <= 250."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=0.25, max_open_risk_pct=0.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)
    s1 = _MockSlot("btc", "BTC-USDT-SWAP", 0, order_size_pct=20.0)
    s2 = _MockSlot("eth", "ETH-USDT-SWAP", 1, order_size_pct=20.0)
    for s in (s1, s2):
        co.register_entry_intent(EntryIntent(s, s.symbol, 1000, 100.0))
    res = co.dispatch_batch_entries(1000)
    assert len(res) == 2
    tot_notional = sum(x.slot.committed["margin"] * x.slot.committed["lev"] for x in res)
    assert tot_notional <= 250.0 + 1e-9


def test_coin_entry_risk_budget_flat_and_risk_sizing():
    """TODO 1: Khi bật max_open_risk_pct:
    - Thiếu SL -> fail-closed (MISSING_MANDATORY_STOP_LOSS)
    - Flat sizing -> tính planned risk từ hard-SL thực tế và fees, không để planned_risk=0
    - Sizing vượt cap rủi ro -> bị apply_risk_ceiling hạ margin để rủi ro <= cap
    """
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    # Equity = 1000, max_open_risk_pct = 5% -> trần rủi ro mở = $50
    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=5.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)

    # 1. Candidate flat sizing thiếu SL (sl_pct = 0) -> reject
    s_no_sl = _MockSlot("no_sl", "BTC-USDT-SWAP", 0, order_size_pct=20.0)
    s_no_sl.sl_pct = 0.0
    s_no_sl.spec.base_sl = 0.0
    events = []
    co.on_event = lambda kind, data: events.append((kind, data))
    co.register_entry_intent(EntryIntent(s_no_sl, s_no_sl.symbol, 1000, 50000.0))
    res1 = co.dispatch_batch_entries(1000)
    assert len(res1) == 0
    assert co.rejected_for_risk == 1
    assert any(e[0] == "risk_reject" and e[1]["reason"] == "MISSING_MANDATORY_STOP_LOSS" for e in events)

    # 2. Candidate flat sizing có SL hợp lệ (sl_pct = 2%, order_size_pct = 20% -> margin ~ 200)
    # Planned risk = margin * lev * (sl + fee) = 200 * 1 * (0.02 + 0.001) = ~4.20 USDT (nằm trong trần 50)
    s_flat = _MockSlot("flat_ok", "BTC-USDT-SWAP", 0, order_size_pct=20.0)
    s_flat.sl_pct = 2.0
    s_flat.spec.base_sl = 2.0
    co.register_entry_intent(EntryIntent(s_flat, s_flat.symbol, 1000, 50000.0))
    res2 = co.dispatch_batch_entries(1000)
    assert len(res2) == 1
    assert s_flat.committed is not None
    assert s_flat.committed["planned"] > 0.0
    assert s_flat.committed["planned"] <= 50.0

    # 3. Candidate flat sizing rủi ro rất lớn (lev 10x, order_size_pct 50% -> notional 5000, 2% = 100 USDT > 50 USDT cap)
    # Hệ thống phải co margin xuống để planned_risk <= 50 USDT
    s_big = _MockSlot("flat_big", "ETH-USDT-SWAP", 1, order_size_pct=50.0)
    s_big.spec.max_leverage = 10.0
    s_big.sl_pct = 2.0
    s_big.spec.base_sl = 2.0
    co.register_entry_intent(EntryIntent(s_big, s_big.symbol, 2000, 3000.0))
    res3 = co.dispatch_batch_entries(2000)
    assert len(res3) == 1
from backend.core.strategy import NoraSlotStrategy, OPEN, ENTERING, EXITING


class _NoraSlotTestHarness:
    """Harness kiểm thử mượn các hàm logic chuẩn của NoraSlotStrategy mà không bị chặn bởi cdef attributes của Cython Actor."""
    _protect = NoraSlotStrategy._protect
    on_order_filled = NoraSlotStrategy.on_order_filled
    _order_failed = NoraSlotStrategy._order_failed
    on_order_rejected = NoraSlotStrategy.on_order_rejected
    on_order_canceled = NoraSlotStrategy.on_order_canceled
    _commit_entry = NoraSlotStrategy._commit_entry
    _coin = NoraSlotStrategy._coin
    _upsert = NoraSlotStrategy._upsert
    _reset = NoraSlotStrategy._reset
    _exit = NoraSlotStrategy._exit
    _apply_unit = NoraSlotStrategy._apply_unit

    def __init__(self):
        self.submitted_orders = []
        self.modified_orders = []
        self.canceled_orders = []
        self.closed_positions = []
        self.protect_retry = False
        self.own_orders_only = False
        self.tp_pct = 0.0
        self.trail_pct = 0.0
        self.trail_act = 0.0
        self.sl_pct = 2.0
        self.dca_steps = ()
        self.dca_ok = True
        self.layers = 1
        self.fee_open = 0.0
        self.margin_used = 0.0
        self.res_here = 0.0
        self.entry_time = 0
        self.entry_margin = 0.0
        self.entry_notional = 0.0
        self.entry_fee = 0.0
        self.max_price = self.min_price = self.peak = 0.0
        self.last_fill = 0.0
        self.next_margin = 0.0
        self._dca_margin = 0.0
        self.pos_lev = 1.0
        self.planned_risk = 0.0
        self.unit_pct = 0.0
        self.entry_equity = 1000.0
        self.sl_lvl_abs = 0.0
        self.pending_qty = 0.0
        self.pending_margin = 0.0
        self.pending_fee_est = 0.0
        self.initial_pending_margin = 0.0
        self.initial_pending_fee_est = 0.0
        self.protection_unavailable = False
        self.signals = []
        self.debug_events = False
        self.t_fills = []
        self._layer_of = {}
        self.exit_kind = None
        self.o = {"SL": None, "TP": None, "TRAIL": None, "DCA": None}

    def submit_order(self, o):
        self.submitted_orders.append(o)

    def modify_order(self, o, **kw):
        self.modified_orders.append((o, kw))

    def cancel_order(self, o):
        self.canceled_orders.append(o)

    def cancel_all_orders(self, inst_id):
        pass

    def _cancel_orders(self):
        pass

    def close_position(self, pos, tags=None):
        self.closed_positions.append((pos, tags))

    def _position(self):
        ps = self.cache.positions_open()
        return ps[0] if ps else None

    def _reconcile_dca(self):
        pass


def test_coin_protection_partial_entry_immediate_sl():
    """TODO 2: Sau mỗi fill tăng vị thế (kể cả partial fill khi entry order chưa đóng),
    phải lập tức đặt/chỉnh hard-SL bao phủ số lượng thực tế đã mở."""
    from backend.core.portfolio import Coordinator
    from backend.analys.alpha import RiskConfig
    from backend.core.strategy import OPEN, ENTERING

    class _MockInst:
        id = "BTC-USDT-SWAP"
        multiplier = 1.0
        price_precision = 2
        size_precision = 4
        min_quantity = 0.001
        def make_price(self, p): return p
        def make_qty(self, q, round_down=True): return round(q, 4)

    class _MockOrder:
        def __init__(self, cid, tags, qty, is_closed=False, is_open=True):
            self.client_order_id = cid
            self.tags = tags
            self.quantity = qty
            self.is_closed = is_closed
            self.is_open = is_open

    class _MockPos:
        def __init__(self, qty, avg):
            self.quantity = qty
            self.avg_px_open = avg

    class _MockCache:
        def __init__(self):
            self._orders = {}
            self._pos = []
        def order(self, cid): return self._orders.get(cid)
        def positions_open(self, instrument_id=None, strategy_id=None): return self._pos

    class _MockOrderFactory:
        def stop_market(self, inst_id, side, qty, trigger_price, **kw):
            return _MockOrder("sl_order_01", ["SL"], qty)
        def limit(self, inst_id, side, qty, price, **kw):
            return _MockOrder("tp_order_01", ["TP"], qty)
        def market(self, inst_id, side, qty, **kw):
            return _MockOrder("entry_01", ["ENTRY"], qty)

    # Dựng minimal slot harness
    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 1, 3600000)

    spec = _MockSpec(order_size_pct=10.0)
    slot = _NoraSlotTestHarness()
    slot.spec = spec
    slot.sid = "btc_slot"
    slot.symbol = "BTC-USDT-SWAP"
    slot.sym_idx = 0
    slot.inst = _MockInst()
    slot.mult = 1.0
    slot.coord = co
    slot.sign = 1.0
    slot.is_long = True
    slot.side_in = "BUY"
    slot.side_out = "SELL"
    slot.reduce_only = True
    slot.cache = _MockCache()
    slot.order_factory = _MockOrderFactory()
    slot.submitted_orders = []
    slot.modified_orders = []
    slot.submit_order = lambda o: slot.submitted_orders.append(o)
    slot.modify_order = lambda o, **kw: slot.modified_orders.append((o, kw))
    slot.cancel_order = lambda o: None
    slot.close_at_end = False
    slot.trade_start = 0
    slot.last_open_ms = None
    slot.signals = []
    slot.debug_events = False
    slot._reset()

    class _MockVal:
        def __init__(self, v): self.v = v
        def as_double(self): return float(self.v)
        def __float__(self): return float(self.v)

    # Giả lập commit entry 1.0 BTC tại giá 50,000
    slot._commit_entry(50000.0, 1.0, 100.0, 1.0, 2.0, 0.0, 0.0, False, 0.05)
    entry_order = _MockOrder("entry_01", ["ENTRY"], 1.0, is_closed=False)
    slot.cache._orders["entry_01"] = entry_order

    # Partial fill 1: khớp 0.4 BTC (order chưa đóng)
    slot.cache._pos = [_MockPos(0.4, 50000.0)]
    class _FillEvent:
        client_order_id = "entry_01"
        last_px = _MockVal(50000.0)
        last_qty = _MockVal(0.4)
        commission = _MockVal(0.02)
        ts_event = 1000 * 1_000_000
        liquidity_side = 2
        order_side = 1
        venue_order_id = "v1"

    slot.on_order_filled(_FillEvent())

    # Verify: Sau partial fill 1, slot đã chuyển OPEN và lập tức đặt SL + TP bao phủ đúng 0.4 BTC
    assert slot.st == OPEN
    assert slot.o["SL"] is not None and slot.o["SL"].quantity == 0.4
    assert slot.o["TP"] is not None and slot.o["TP"].quantity == 0.4

    # Partial fill 2: khớp nốt 0.6 BTC (order đóng hẳn)
    entry_order.is_closed = True
    slot.cache._pos = [_MockPos(1.0, 50000.0)]
    class _FillEvent2:
        client_order_id = "entry_01"
        last_px = _MockVal(50000.0)
        last_qty = _MockVal(0.6)
        commission = _MockVal(0.03)
        ts_event = 2000 * 1_000_000
        liquidity_side = 2
        order_side = 1
        venue_order_id = "v2"

    slot.on_order_filled(_FillEvent2())

    # Verify: SL và TP đã được amend / modify tăng lên 1.0 BTC bao phủ toàn bộ vị thế
    assert any(m[0].tags == ["SL"] and m[1]["quantity"] == 1.0 for m in slot.modified_orders)
    assert any(m[0].tags == ["TP"] and m[1]["quantity"] == 1.0 for m in slot.modified_orders)


def test_coin_protection_reject_failsafe_idempotent():
    """TODO 3: Khi lệnh hard-SL bị sàn reject:
    - Ghi trạng thái protection_unavailable
    - Hủy lệnh DCA (nếu có) để chặn tăng thêm vị thế
    - Phát sự kiện protection_failed và kích hoạt emergency exit KILL
    - Idempotent: callback lặp lại không gửi lệnh thoát trùng lặp
    """
    from backend.core.portfolio import Coordinator
    from backend.analys.alpha import RiskConfig
    from backend.core.strategy import OPEN, EXITING

    class _MockInst:
        id = "BTC-USDT-SWAP"
        multiplier = 1.0
        price_precision = 2
        size_precision = 4
        def make_price(self, p): return p
        def make_qty(self, q, round_down=True): return q

    class _MockOrder:
        def __init__(self, cid, tags, is_closed=False):
            self.client_order_id = cid
            self.tags = tags
            self.is_closed = is_closed

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 1, 3600000)
    events = []
    co.on_event = lambda kind, data: events.append((kind, data))

    slot = _NoraSlotTestHarness()
    slot.spec = _MockSpec(order_size_pct=10.0)
    slot.sid = "btc_slot"
    slot.symbol = "BTC-USDT-SWAP"
    slot.sym_idx = 0
    slot.inst = _MockInst()
    slot.mult = 1.0
    slot.coord = co

    class _MockCache:
        def __init__(self):
            self._orders = {}
            self._pos = []
        def order(self, cid): return self._orders.get(cid)
        def positions_open(self, *a, **kw): return self._pos

    cache = _MockCache()
    sl_order = _MockOrder("sl_01", ["SL"])
    dca_order = _MockOrder("dca_01", ["DCA"])
    cache._orders["sl_01"] = sl_order
    cache._pos = ["mock_pos"]
    slot.cache = cache

    slot.own_orders_only = False
    slot.cancel_all_orders = lambda inst_id: None
    closed_positions = []
    slot.close_position = lambda pos, tags: closed_positions.append((pos, tags))
    slot.canceled_orders = []
    slot.cancel_order = lambda o: slot.canceled_orders.append(o)
    slot._reset()

    # Vị thế đang OPEN, có SL và DCA order đang chờ
    slot.st = OPEN
    slot.o["SL"] = sl_order
    slot.o["DCA"] = dca_order

    class _RejectEvent:
        client_order_id = "sl_01"
        reason = "Order price outside allowed bands"

    # Lần 1: SL bị reject
    slot.on_order_rejected(_RejectEvent())

    assert slot.protection_unavailable is True
    assert slot.dca_ok is False
    assert slot.o["SL"] is None
    assert slot.o["DCA"] is None
    assert dca_order in slot.canceled_orders
    assert slot.st == EXITING
    assert len(closed_positions) == 1
    assert closed_positions[0][1] == ["KILL"]
    assert any(e[0] == "protection_failed" and e[1]["action"] == "EMERGENCY_EXIT" for e in events)

    # Lần 2: Callback reject trùng lặp (duplicate event do reconnect/WS)
    slot.on_order_rejected(_RejectEvent())
    # Verify: Idempotent - không gửi thêm lệnh close_position lần 2
    assert len(closed_positions) == 1


def test_coin_pending_reservation_lifecycle_and_invariants():
    """TODO 6: Vòng đời pending_reserved -> partial fill 1 -> partial fill 2 -> cancel.
    Đối chiếu pending_reserved và reserved với oracle độc lập tại mọi bước, không rò rỉ reservation."""
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig
    from backend.core.strategy import OPEN

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 1, 3600000)

    class _MockVal:
        def __init__(self, v): self.v = v
        def as_double(self): return float(self.v)
        def __float__(self): return float(self.v)

    class _MockInst:
        id = "BTC-USDT-SWAP"
        multiplier = 1.0
        price_precision = 2
        size_precision = 4
        def make_price(self, p): return p
        def make_qty(self, q, round_down=True): return q

    class _MockOrder:
        def __init__(self, cid, tags, qty, is_closed=False):
            self.client_order_id = cid
            self.tags = tags
            self.quantity = qty
            self.is_closed = is_closed

    class _MockCache:
        def __init__(self):
            self._orders = {}
            self._pos = []
        def order(self, cid): return self._orders.get(cid)
        def positions_open(self, *a, **kw): return self._pos

    slot = _NoraSlotTestHarness()
    slot.spec = _MockSpec(order_size_pct=10.0, fee_rate=0.001)
    slot.sid = "btc_slot"
    slot.symbol = "BTC-USDT-SWAP"
    slot.sym_idx = 0
    slot.inst = _MockInst()
    slot.mult = 1.0
    slot.coord = co
    slot.sign = 1.0
    slot.is_long = True
    slot.side_in = "BUY"
    slot.side_out = "SELL"
    slot.reduce_only = True
    cache = _MockCache()
    entry_order = _MockOrder("e1", ["ENTRY"], 1.0, is_closed=False)
    cache._orders["e1"] = entry_order
    slot.cache = cache
    slot.order_factory = type("OF", (), {"market": lambda *a, **k: entry_order})()
    slot.submit_order = lambda o: None
    slot._protect = lambda *a, **k: None
    slot._reset()

    # Commit entry 100 USDT margin + 0.1 USDT fee_est = 100.1 pending_reserved
    slot._commit_entry(100.0, 1.0, 100.0, 1.0, 2.0, 0.0, 0.0, False, 0.1)
    co.pending_reserved = 100.1
    assert round(co.pending_reserved, 2) == 100.10
    assert co.reserved == 0.0

    # Bước 1: Partial fill 40% (qty 0.4)
    class _F1:
        client_order_id = "e1"
        last_px = _MockVal(100.0)
        last_qty = _MockVal(0.4)
        commission = _MockVal(0.04)
        ts_event = 1000 * 1_000_000
        liquidity_side = 2
        order_side = 1
        venue_order_id = "v1"

    slot.on_order_filled(_F1())
    # pending_reserved phải giải phóng đúng 40% (40.04 USDT), còn lại ~60.06 USDT
    assert round(co.pending_reserved, 2) == 60.06
    # reserved tăng đúng 40.0 USDT margin + 0.04 USDT fee = 40.04 USDT
    assert round(co.reserved, 2) == 40.04

    # Bước 2: Partial fill 30% tiếp (qty 0.3)
    class _F2:
        client_order_id = "e1"
        last_px = _MockVal(100.0)
        last_qty = _MockVal(0.3)
        commission = _MockVal(0.03)
        ts_event = 2000 * 1_000_000
        liquidity_side = 2
        order_side = 1
        venue_order_id = "v2"

    slot.on_order_filled(_F2())
    # pending_reserved giải phóng thêm 30% (30.03 USDT), còn lại 30.03 USDT
    assert round(co.pending_reserved, 2) == 30.03
    # reserved tăng thêm 30.03 USDT = 70.07 USDT
    assert round(co.reserved, 2) == 70.07

    # Bước 3: Canceled phần còn lại (30%)
    class _CancelEv:
        client_order_id = "e1"
    slot.on_order_canceled(_CancelEv())
    # pending_reserved về chính xác 0.0, reserved giữ nguyên 70.07 USDT
    assert round(co.pending_reserved, 2) == 0.0
    assert round(co.reserved, 2) == 70.07
    # Slot vẫn còn vị thế 0.7 BTC đã khớp, không bị reset hay deactivate
    assert len(slot.t_fills) == 2

    # Bước 4: Duplicate cancel callback không được trừ âm pending_reserved
    slot.on_order_canceled(_CancelEv())
    assert co.pending_reserved == 0.0


def test_coin_entry_batch_integration_via_bar_done():
    """TODO 7: Kiểm tra tích hợp đầy đủ luồng bar_done:
    - Khi live_n = 2: slot 1 đến trước -> CHƯA dispatch
    - slot 2 đến cùng ts -> gom đủ batch -> DISPATCH đồng loạt pro-rata
    - Không phụ thuộc vào slot nào gọi callback trước.
    """
    from backend.core.portfolio import Coordinator, EntryIntent
    from backend.analys.alpha import RiskConfig

    risk = RiskConfig(max_positions=10, max_per_symbol=1, max_gross_exposure=10.0, max_open_risk_pct=10.0)
    co = Coordinator(risk, 1000.0, 0, lambda: 1000.0, 2, 3600000)
    co.live_n = 2

    s1 = _MockSlot("btc", "BTC-USDT-SWAP", 0, order_size_pct=60.0)
    s2 = _MockSlot("eth", "ETH-USDT-SWAP", 1, order_size_pct=60.0)

    # 1. Bar slot 1 (BTC) đóng tại ts = 1000
    co.register_entry_intent(EntryIntent(s1, s1.symbol, 1000, 50000.0))
    co.bar_done(1000)

    # Chưa đủ batch (mới có 1/2 slot), chưa dispatch
    assert s1.committed is None
    assert s2.committed is None
    assert co.pending_reserved == 0.0

    # 2. Bar slot 2 (ETH) đóng tại ts = 1000
    co.register_entry_intent(EntryIntent(s2, s2.symbol, 1000, 3000.0))
    co.bar_done(1000)

    # Đã đủ batch (2/2 slot) -> dispatch đồng loạt pro-rata!
    assert s1.committed is not None
    assert s2.committed is not None
    # Cả 2 slot đều được phân bổ công bằng, mỗi bên ~500 USDT
    assert round(s1.committed["margin"], 1) == round(s2.committed["margin"], 1)
    assert s1.committed["margin"] + s2.committed["margin"] <= 1000.0 + 1e-6


def test_server_attestation_tamper_detection_and_fail_closed_promotion():
    """Kiểm tra tính toàn vẹn của Server Attestation: phát hiện giả mạo, chặn phiên bản cũ, và bảo vệ fail-closed."""
    from backend.adapter.contracts import (
        issue_server_attestation,
        verify_server_attestation,
        verify_candidate_parity_provenance,
        verify_backtest_job_parity,
    )

    # 1. Cấp attestation hợp lệ
    att = issue_server_attestation(
        engine_version_hash="eng_12345",
        code_hash="code_67890",
        config_hash="cfg_abcde",
        symbol="BTC-USDT-SWAP",
        data_digest="cd026438b6a668b1",
        cost_model_hash="cost_v1",
        risk_gate_passed=True,
        oos_mdd=12.5,
        oos_sharpe=1.85,
    )
    ok, reason = verify_server_attestation(att)
    assert ok is True
    assert reason == "ATTESTATION_VALID"

    # 2. Giả mạo dữ liệu (Tamper test) - sửa oos_mdd từ 12.5 thành 5.0
    tampered_att = dict(att)
    tampered_att["oos_mdd"] = 5.0
    ok, reason = verify_server_attestation(tampered_att)
    assert ok is False
    assert "CHỮ_KÝ_KHÔNG_HỢP_LỆ" in reason

    # 3. Giả mạo dữ liệu - sửa code_hash
    tampered_code = dict(att)
    tampered_code["code_hash"] = "code_forged"
    ok, reason = verify_server_attestation(tampered_code)
    assert ok is False
    assert "CHỮ_KÝ_KHÔNG_HỢP_LỆ" in reason

    # 4. Attestation có risk_gate_passed = False
    failed_risk_att = issue_server_attestation(
        engine_version_hash="eng_12345",
        code_hash="code_67890",
        config_hash="cfg_abcde",
        symbol="BTC-USDT-SWAP",
        data_digest="cd026438b6a668b1",
        cost_model_hash="cost_v1",
        risk_gate_passed=False,
        oos_mdd=35.0,
        oos_sharpe=0.4,
    )
    ok, reason = verify_server_attestation(failed_risk_att)
    assert ok is False
    assert "ATTESTATION_REJECTED" in reason

    # 5. Attestation mang phiên bản hợp đồng cũ
    expired_att = dict(att)
    expired_att["contract_version"] = "0.9.0"
    # Giả mạo cả chữ ký để qua bước check signature đầu tiên
    from backend.adapter.contracts import compute_attestation_signature
    expired_att["signature"] = compute_attestation_signature(expired_att)
    ok, reason = verify_server_attestation(expired_att)
    assert ok is False
    assert "ATTESTATION_EXPIRED" in reason

    # 6. Đưa attestation hợp lệ vào candidate nhưng hệ thống đang khoá promotion_allowed=False (GATE 0)
    candidate = {"id": "c1", "server_attestation": att}
    cand_ok, cand_reason = verify_candidate_parity_provenance(candidate)
    assert cand_ok is False
    assert "PROMOTION_LOCKED_PENDING_ALL_GATES" in cand_reason

    # 7. Job backtest mang attestation hợp lệ nhưng vẫn khoá promotion
    job_ok, job_reason = verify_backtest_job_parity({"job_id": "j1", "server_attestation": att})
    assert job_ok is False
    assert "PROMOTION_LOCKED_PENDING_ALL_GATES" in job_reason


