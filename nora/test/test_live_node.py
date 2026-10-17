"""Test B3 (P17 T5): build_node, RecorderActor, quản lý bot live (không mạng)."""
import os
import pytest
from nautilus_trader.adapters.okx.config import OKXExecClientConfig
from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.core.nautilus_pyo3 import OKXContractType, OKXInstrumentType, OKXMarginMode

from backend.alpha.compile import compile_code
from backend.alpha.plan import RiskConfig, build_plan
from backend.jobs import tasks
from backend.nautilus import live as lv
from backend.nautilus.live import OKXEnvironment, RecorderActor
from backend.nautilus.portfolio import Coordinator
from backend.nautilus.signals import LiveSignals
from backend.nautilus.strategy import NoraSlotStrategy


CODE = """class RiskFailFastBreakoutStrategy(NoraStrategy):
    timeframe = "24h"
    upper_period = 20
    ema_period = 10
    stop_loss_pct = 3.0
    risk_per_trade_pct = 0.5

    def on_bar(self):
        upper = self.feat.donchian_upper(high, self.upper_period)
        ema = ema(close, self.ema_period)
        enter_sig = crossover(close, upper)
        exit_sig = (close < upper) | (close < ema)
        self.close(exit_sig)
        self.buy(enter_sig)
"""
FAKE_DEMO = {"key": "k", "secret": "s", "passphrase": "p", "is_demo": True}


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Thư mục bot ra tmp_path; không nạp lịch sử / không chạy node (không mạng)."""
    monkeypatch.setattr(lv, "data_home", lambda: str(tmp_path))
    monkeypatch.setattr(lv, "load_okx_credentials", lambda: dict(FAKE_DEMO))
    return tmp_path


def _plan(symbols=("BTC", "ETH"), run_frame="1m"):
    plan = build_plan(compile_code(CODE), list(symbols), run_frame=run_frame)
    return plan


def test_build_node_paper_wires_strategies_factories_and_clients(isolated):
    plan = _plan()
    node = lv.build_node("paper", plan.strategies, plan.symbols, 10000.0, base_frame="1m", bot_id="t_paper", risk=plan.risk)
    try:
        n = node.nora
        # mỗi (chiến lược × tài sản) một NoraSlotStrategy, đã nằm trong trader, tín hiệu live
        assert len(n.slots) == 2 and len(node.trader.strategy_ids()) == 2
        assert all(isinstance(s, NoraSlotStrategy) and isinstance(s.signals, LiveSignals) for s in n.slots)
        assert [str(i) for i in n.instrument_ids] == ["BTC-USDT-SWAP.OKX", "ETH-USDT-SWAP.OKX"]
        assert n.coord.live_n == 2 and n.coord.slots == n.slots
        assert len(node.trader.actor_ids()) == 1                                  # RecorderActor
        # factory + client đã đăng ký (node.build() đã chạy)
        assert [str(c) for c in node.kernel.data_engine.registered_clients] == ["OKX"]
        assert len(node.kernel.exec_engine.registered_clients) == 1
        cfg = node._config
        d = cfg.data_clients["OKX"]
        assert d.environment == OKXEnvironment.LIVE and d.instrument_types == (OKXInstrumentType.SWAP,) and d.contract_types == (OKXContractType.LINEAR,)
        assert len(d.instrument_provider.load_ids) == 2
        assert isinstance(cfg.exec_clients["SANDBOX"], SandboxExecutionClientConfig)
        assert cfg.exec_clients["SANDBOX"].starting_balances == ["10000 USDT"]
        assert cfg.risk_engine.bypass is False
        assert cfg.exec_engine.reconciliation is False
    finally:
        node.dispose()


def test_build_node_testnet_uses_okx_demo_exec(isolated):
    plan = _plan(("BTC",))
    node = lv.build_node("testnet", plan.strategies, plan.symbols, 5000.0, base_frame="1m", bot_id="t_testnet", risk=plan.risk)
    try:
        cfg = node._config
        assert cfg.data_clients["OKX"].environment == OKXEnvironment.DEMO
        ex = cfg.exec_clients["OKX"]
        assert isinstance(ex, OKXExecClientConfig) and ex.environment == OKXEnvironment.DEMO and ex.margin_mode == OKXMarginMode.CROSS
        assert ex.instrument_types == (OKXInstrumentType.SWAP,) and len(ex.instrument_provider.load_ids) == 1
        assert cfg.exec_engine.reconciliation is True and cfg.risk_engine.bypass is False
        assert len(node.nora.slots) == 1 and len(node.trader.strategy_ids()) == 1
    finally:
        node.dispose()


def test_build_node_live_requires_confirm(isolated):
    plan = _plan(("BTC",))
    with pytest.raises(ValueError, match="confirm_live=True"):
        lv.build_node("live", plan.strategies, plan.symbols, 1000.0, confirm_live=False, bot_id="t_live", base_frame="1m")
    with pytest.raises(ValueError, match="DEMO"):     # khoá demo không được dùng cho live
        lv.build_node("live", plan.strategies, plan.symbols, 1000.0, confirm_live=True, bot_id="t_live2", base_frame="1m")


def _run_job(monkeypatch, params):
    """run_live_bot với node.run / warm_start vô hiệu (không mạng); trả về node đã dựng."""
    from nautilus_trader.live.node import TradingNode
    built = []
    real_build = lv.build_node
    monkeypatch.setattr(lv, "build_node", lambda *a, **k: built.append(real_build(*a, **k)) or built[-1])
    monkeypatch.setattr(lv, "warm_start", lambda node, now_ms=None: [])
    monkeypatch.setattr(TradingNode, "run", lambda self, *a, **k: None)
    out = tasks.run_live_bot(params)
    assert out["status"] == "running"        # thoát không do người dùng dừng -> giữ "running" (supervisor chạy lại), không đóng vị thế
    return built[0]


def test_run_live_bot_dsl_code_path(isolated, monkeypatch):
    node = _run_job(monkeypatch, {"mode": "paper", "code": CODE, "symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"], "capital": 1000, "base_frame": "1m", "bot_id": "t_code"})
    assert len(node.nora.slots) == 2 and node.nora.signals[0].strategy["side"] == "LONG"
    assert node.nora.signals[0].required_frames == {"1m", "24h"}


def test_run_live_bot_user_alpha_id(isolated, monkeypatch):
    monkeypatch.setattr("backend.alpha.store.get_user_alpha", lambda aid, base_dir=None: {"id": aid, "code": CODE, "config": {"position": {"leverage": 5}, "risk": {"max_positions": 3}}})
    node = _run_job(monkeypatch, {"mode": "paper", "alpha_id": "abc123", "symbols": ["BTC"], "capital": 1000, "base_frame": "1m", "bot_id": "t_alpha"})
    assert len(node.nora.slots) == 1
    assert node.nora.coord.risk.max_positions == 3                      # rủi ro đã lưu của alpha
    assert node.nora.slots[0].spec.max_leverage == 5                    # vị thế đã lưu của alpha


def test_run_live_bot_system_strategy_id(isolated, monkeypatch):
    monkeypatch.setattr("backend.alpha.store.get_user_alpha", lambda aid, base_dir=None: None)
    node = _run_job(monkeypatch, {"mode": "paper", "alpha_id": "kema_long", "symbols": ["BTC"], "capital": 1000, "base_frame": "1h", "bot_id": "t_sys"})
    assert len(node.nora.slots) == 1


def test_build_slots_shared_with_backtest():
    """Backtest và live dựng slot qua CÙNG hàm (không copy)."""
    import inspect
    from backend.nautilus import backtest
    assert "build_slots(" in inspect.getsource(backtest.NautilusRun.run)
    assert "build_slots(" in inspect.getsource(lv.build_node)


def test_recorder_actor_and_bot_lifecycle(tmp_path):
    bot_dir = str(tmp_path / "bot_test_123")
    os.makedirs(bot_dir, exist_ok=True)
    coord = Coordinator(RiskConfig(), 1000.0, 0, lambda: 1000.0, 1, 3600_000)
    recorder = RecorderActor(bot_dir, coord)

    # Ghi sự kiện
    recorder.record_event("test_event", {"status": "ok", "msg": "hello"})
    ev_file = os.path.join(bot_dir, "events.jsonl")
    assert os.path.isfile(ev_file)
    with open(ev_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "test_event" in content
        assert "hello" in content

    # Ghi equity
    recorder.record_equity(3600_000)
    eq_file = os.path.join(bot_dir, "equity.jsonl")
    assert os.path.isfile(eq_file)
    with open(eq_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "equity" in content


def test_delete_bot_rules(isolated):
    import json
    run = isolated / "live" / "paper" / "b_run"
    run.mkdir(parents=True)
    (run / "bot.json").write_text(json.dumps({"bot_id": "b_run", "status": "running", "pid": os.getpid()}))
    old = isolated / "live" / "paper" / "b_old"
    old.mkdir(parents=True)
    (old / "bot.json").write_text(json.dumps({"bot_id": "b_old", "status": "stopped"}))
    assert lv.delete_bot("b_run")["running"] is True and run.exists()          # đang chạy -> không xoá
    assert lv.delete_bot("b_old")["ok"] is True and not old.exists()
    assert lv.delete_bot("../x")["ok"] is False


# ─── DataWatch: dữ liệu không lên / đứng (không mạng) ───────────────────────
def _fake_node(frame="1m", nslots=2):
    from types import SimpleNamespace as NS
    slots = [NS(nbar=0, last_bar_wall=0.0) for _ in range(nslots)]
    n = NS(nora=NS(base_frame=frame, slots=slots, recorder=None), kernel=NS(data_engine=NS(ok=False, check_connected=lambda: n.kernel.data_engine.ok)))
    return n


def test_datawatch_connect_timeout_then_ready_then_stall():
    t = [1000.0]
    n = _fake_node("1m")
    w = lv.DataWatch(n, clock=lambda: t[0])
    assert w.verdict(1010.0) is None
    assert w.verdict(1000.0 + w.ready_s + 1) == "connect_timeout"
    w = lv.DataWatch(n, clock=lambda: t[0])
    n.kernel.data_engine.ok = True
    assert w.verdict(1010.0) is None and w.ready_at is None                # nối được nhưng chưa có nến -> chưa ready (khung 1m)
    assert w.verdict(1000.0 + w.ready_s + 1) == "no_bars"
    w = lv.DataWatch(n, clock=lambda: t[0])
    for s in n.nora.slots:
        s.nbar, s.last_bar_wall = 1, 1020.0
    assert w.verdict(1030.0) is None and w.ready_at == 1030.0
    assert w.verdict(1030.0 + 3 * 60 + 30) is None
    assert w.verdict(1030.0 + 3 * 60 + 61) == "data_stall"


def test_datawatch_big_frame_needs_connection_only():
    n = _fake_node("1h")
    n.kernel.data_engine.ok = True
    w = lv.DataWatch(n, clock=lambda: 0.0)
    assert not w.need_bars and w.verdict(5.0) is None and w.ready_at == 5.0


def test_data_client_net_and_debug_events_default_off(isolated):
    plan = _plan()
    node = lv.build_node("paper", plan.strategies, plan.symbols, 1000.0, base_frame="1m", bot_id="t_net", risk=plan.risk)
    assert node.nora.slots and all(s.debug_events is False for s in node.nora.slots)
    assert lv.DATA_CLIENT_NET["max_retries"] == 5


# ─── enter_on_start catch-up (khung 24h, không chờ nến), heartbeat theo timer, dấu vân tay chiến lược ───────────
def _slot_24h(isolated):
    plan = _plan(("BTC",), run_frame="24h")
    node = lv.build_node("paper", plan.strategies, plan.symbols, 1000.0, base_frame="24h", bot_id="t_24h", risk=plan.risk, enter_on_start=True)
    return node, node.nora.slots[0]


def test_catchup_runs_at_start_for_24h_frame_without_any_bar(isolated):
    node, s = _slot_24h(isolated)
    try:
        events, calls = [], []
        s.coord.emit = lambda t, d: events.append((t, d))
        s._enter = lambda price, vol, catchup=False: (calls.append((price, catchup)), setattr(s, "st", 1))[0]
        s.signals.latest_event = lambda now: {"match": True, "stop": False, "open_time": 111, "signal_open_time": 111, "last_open_time": 111, "vol": 1.0}
        assert s.nbar == 0                                              # chưa có nến khung chạy nào
        assert s.run_catch_up(1_000_000_000, price=50000.0) is True
        assert calls == [(50000.0, True)]
        t, d = events[-1]
        assert t == "catchup" and d["entered"] is True and d["signal_open_time"] == 111       # không còn null
        assert s.run_catch_up(1_000_000_001, price=50000.0) is False and len(calls) == 1      # chỉ MỘT lần
    finally:
        node.dispose()


def test_catchup_no_match_records_latest_signal_bar(isolated):
    node, s = _slot_24h(isolated)
    try:
        events = []
        s.coord.emit = lambda t, d: events.append((t, d))
        s._enter = lambda *a, **k: pytest.fail("không được vào lệnh khi không match")
        s.signals.latest_event = lambda now: {"match": False, "stop": False, "open_time": None, "signal_open_time": 222, "last_open_time": 222}
        s.run_catch_up(1_000_000_000, price=10.0)
        assert events[-1][1]["entered"] is False and events[-1][1]["signal_open_time"] == 222
    finally:
        node.dispose()


def test_latest_event_always_reports_signal_open_time():
    import pandas as pd
    from backend.nautilus.signals import LiveSignals
    DAY = 86_400_000
    n = 60
    rows = [{"open_time": i * DAY, "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i, "volume": 1.0} for i in range(n)]
    sg = LiveSignals("BTC-USDT-SWAP", _plan(("BTC",), run_frame="24h").strategies[0], "24h", frames={"24h": pd.DataFrame(rows)})
    ev = sg.latest_event(n * DAY + 5 * 3600_000)             # 05:00 sau nến cuối đã đóng: nến tín hiệu đóng gần nhất = nến n-1
    assert ev is not None and ev["signal_open_time"] is not None and ev["last_open_time"] == (n - 1) * DAY


def test_heartbeat_timer_writes_without_bars(tmp_path):
    import json
    from types import SimpleNamespace as NS
    coord = Coordinator(RiskConfig(), 1000.0, 0, lambda: 1000.0, 1, 24 * 3600_000)
    rec = RecorderActor(str(tmp_path), coord)
    assert rec.heartbeat_s == 60
    rec.touch_data("quote")
    rec.seed_signal("BTC@perp", 5 * 86_400_000, {"match": True, "stop": False})
    hb_path = tmp_path / "heartbeat.json"
    hb_path.unlink()
    now = 5 * 86_400_000 + 3 * 3600_000
    rec._on_heartbeat_timer(NS(ts_event=now * 1_000_000))                 # timer: KHÔNG có nến nào
    hb = json.loads(hb_path.read_text())
    assert hb["updated_at"] == now and hb["last_data_ms"] and hb["last_data_kind"] == "quote"
    assert hb["next_bar_close_ms"] == 6 * 86_400_000 and hb["frame_ms"] == 24 * 3600_000
    assert hb["symbols"]["BTC@perp"]["last_signal"]["match"] is True
    rec.record_signal("BTC@perp", "s1", now, {"match": True, "stop": False, "dca": True})
    rec.record_signal("BTC@perp", "s1", now + 1, None)
    rows = [json.loads(x) for x in (tmp_path / "signals.jsonl").read_text().splitlines()]
    assert rows[0] == {"ts": now, "symbol": "BTC@perp", "slot": "s1", "match": True, "stop": False, "dca": True} and rows[1]["match"] is None


def test_big_frame_testnet_subscribes_1m_health_bars_only(isolated):
    plan = _plan(("BTC",), run_frame="24h")
    node = lv.build_node("testnet", plan.strategies, plan.symbols, 1000.0, base_frame="24h", bot_id="t_health", risk=plan.risk)
    try:
        hb = node.nora.recorder.health_bar_types
        assert len(hb) == 1 and "1-MINUTE" in str(hb[0])
        assert all("MINUTE" not in str(s.bar_type) for s in node.nora.slots)       # tín hiệu vẫn chỉ theo khung chạy
    finally:
        node.dispose()


def test_fingerprint_picker_default_matches_backtest_config(isolated, monkeypatch):
    monkeypatch.setattr("backend.alpha.store.get_user_alpha", lambda aid, base_dir=None: None)
    params = {"mode": "paper", "alpha_id": "kema_long", "signal_tf": "1h", "symbols": ["BTC", "ETH"], "base_frame": "1h"}
    src = tasks.resolve_live_source(params)
    ident = tasks.launch_fingerprint(params, src)
    assert ident["fingerprint_match"] is True and ident["strategy_fingerprint"] == ident["fingerprint_expected"] and len(ident["strategy_fingerprint"]) == 16
    other = tasks.resolve_live_source({**params, "symbols": ["SOL"]})                       # tài sản khác không đổi cấu hình chiến lược
    assert tasks.launch_fingerprint(params, other)["strategy_fingerprint"] == ident["strategy_fingerprint"]
    src["strategies"][0]["position"] = {**src["strategies"][0]["position"], "leverage": 3}   # đổi vị thế -> dấu vân tay đổi
    assert tasks.launch_fingerprint(params, src)["fingerprint_match"] is False


def test_fingerprint_user_alpha_override_flags_mismatch(isolated, monkeypatch):
    monkeypatch.setattr("backend.alpha.store.get_user_alpha", lambda aid, base_dir=None: {"id": aid, "code": CODE, "config": {"position": {"leverage": 5}}})
    base = {"mode": "paper", "alpha_id": "abc", "signal_tf": "24h", "symbols": ["BTC"], "base_frame": "24h"}
    assert tasks.launch_fingerprint(base, tasks.resolve_live_source(base))["fingerprint_match"] is True
    over = {**base, "position": {"leverage": 2}}                                             # ghi đè vị thế lúc chạy -> lệch backtest đã lưu
    assert tasks.launch_fingerprint(over, tasks.resolve_live_source(over))["fingerprint_match"] is False
