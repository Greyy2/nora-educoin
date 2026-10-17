"""Bot live: dữ liệu không mất, id duy nhất, sở hữu lệnh theo clOrdId, vốn/PnL RIÊNG của bot, một nguồn trạng thái, supervisor.
Không mạng, không đặt lệnh sàn: thư mục dữ liệu tạm, _okx_signed giả."""
import json
import os

import pytest

from backend.jobs import live_supervisor as sup
from backend.jobs import runner
from backend.nautilus import live as lv
from backend.nautilus import live_ledger as led

DEAD_PID = 2 ** 22 + 777            # vượt pid_max mặc định -> không tồn tại
TAG, OTHER = "AAAA1111", "BBBB2222"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "data"
    h.mkdir()
    (h / "market").mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(h))
    runner._SUMMARY_CACHE.clear()
    led._CACHE.clear()
    monkeypatch.setattr(led, "okx_marks", lambda syms, now=None: {})      # không mạng: REST công khai bị chặn mặc định
    return h


def cid(tag, n=1, strat="001"):
    return f"O20261013010101{tag}{strat}{n}"


def fill(sym, side, qty, px, tag, fee=0.0, ts=1000, kind="ENTRY", strat="s1", n=1):
    return {"t": ts, "type": "fill", "symbol": sym, "strategy": strat, "kind": kind, "side": side, "px": px, "qty": qty, "fee": fee, "ts": ts,
            "client_order_id": cid(tag, n)}


def make_bot(home, bot_id, mode="testnet", status="running", pid=None, events=(), tag=TAG, instruments=("BTC-USDT-SWAP.OKX",), stop=None, job_id=None, **extra):
    d = home / "live" / mode / bot_id
    d.mkdir(parents=True)
    meta = {"bot_id": bot_id, "mode": mode, "capital": 1000.0, "status": status, "cl_tag": tag, "instruments": list(instruments), "symbols": ["BTC@perp"],
            "started_at": 1_000_000, "pid": pid, "strategies": ["s1"], **extra}
    if job_id:
        meta["job_id"] = job_id
    (d / "bot.json").write_text(json.dumps(meta))
    if events:
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if stop is not None:
        (d / "stop").write_text(f"stopped_at=1\nclose={stop}\n")
    return d


# ─── vốn / PnL riêng, không dùng số dư tài khoản ─────────────────────────────
def test_zero_fill_bot_equity_is_capital_even_if_equity_rows_use_shared_balance(home):
    d = make_bot(home, "b_zero", pid=os.getpid())
    (d / "equity.jsonl").write_text(json.dumps({"time": 5000, "equity": 9998.56, "balance": 9998.56, "equity_worst": 9998.56, "open_positions": 0}) + "\n")
    (d / "positions.json").write_text("[]")
    b = lv.list_bots("testnet")[0]
    assert b["equity"] == 1000.0 and b["pnl_usd"] == 0.0 and b["pnl_pct"] == 0.0
    det = lv.get_bot_detail("b_zero")
    assert det["equity"] == 1000.0 and det["equity_series"][-1]["equity"] == 1000.0 and det["metrics"]["trades"] == 0 and det["trades"] == []


def test_own_ledger_pnl_fees_unrealized_and_only_own_prefix(home):
    ev = [fill("BTC@perp", "BUY", 0.1, 100.0, TAG, fee=0.5, ts=1000),
          fill("BTC@perp", "SELL", 0.1, 110.0, TAG, fee=0.5, ts=2000, kind="TP", n=2),           # +1.0 gộp, -1.0 phí -> lệnh 0.0
          fill("BTC@perp", "BUY", 0.2, 100.0, TAG, fee=0.2, ts=3000, n=3),                        # đang mở
          fill("BTC@perp", "BUY", 5.0, 100.0, OTHER, fee=9.0, ts=3500, n=4)]                      # bot khác trên cùng tài khoản: KHÔNG tính
    d = make_bot(home, "b_pnl", pid=os.getpid(), events=ev)
    (d / "positions.json").write_text(json.dumps([{"symbol": "BTC@perp", "mark": 105.0, "qty": 0.2, "avg_price": 100.0, "is_long": True}]))
    det = lv.get_bot_detail("b_pnl")
    # vốn 1000 + 1.0 gộp − 1.2 phí + 0.2 × 5 chưa chốt
    assert det["equity"] == pytest.approx(1000 + 1.0 - 1.2 + 1.0)
    assert det["metrics"]["fees_usd"] == pytest.approx(1.2, abs=0.01) and det["metrics"]["trades"] == 1
    assert det["positions"][0]["qty"] == pytest.approx(0.2)
    t = det["trades"][0]
    assert t["symbol"] == "BTC@perp" and t["pnl"] == pytest.approx(0.0) and t["close_reason"] and {"enter_time", "close_time", "fees_usd", "pnl_pct", "status"} <= set(t)
    assert [f["qty"] for f in lv.get_bot_trades("b_pnl")] == [0.1, 0.1, 0.2]
    # /live/bots, chi tiết, summary: cùng một hàm -> cùng con số
    assert lv.list_bots()[0]["equity"] == det["equity"]
    from backend.routes.live import get_live_summary
    assert get_live_summary()["live"]["pnl_usd"] == pytest.approx(det["pnl_usd"], abs=1e-3)


def test_cl_tag_attribution_helpers():
    assert led.cl_tag_of(cid(TAG)) == TAG and led.cl_tag_of("junk") is None
    assert led.owns(TAG, cid(TAG, 7)) and not led.owns(TAG, cid(OTHER)) and led.owns(None, cid(OTHER))
    assert len(cid(TAG, 123456)) <= 32 and "-" not in cid(TAG)
    tags = {led.new_cl_tag() for _ in range(50)}
    assert len(tags) == 50 and all(len(t) == led.TAG_LEN and t.isalnum() for t in tags)


# ─── id duy nhất, không ghi đè ───────────────────────────────────────────────
def test_unique_ids_and_refuse_existing_dir(home):
    ids = {lv.new_bot_id("paper") for _ in range(100)}
    assert len(ids) == 100
    make_bot(home, "dup", mode="paper")
    with pytest.raises(ValueError):
        lv.open_bot_dir("testnet", "dup", resume=False)           # id đã có ở mode khác cũng bị từ chối
    assert lv.open_bot_dir("paper", "dup", resume=True).endswith("dup")


# ─── resume nối thêm, không cắt ──────────────────────────────────────────────
def test_resume_appends_and_keeps_tag_and_ledger(home, monkeypatch):
    from test.test_live_node import CODE, FAKE_DEMO  # noqa
    monkeypatch.setattr(lv, "load_okx_credentials", lambda: dict(FAKE_DEMO))
    from backend.alpha.compile import compile_code
    from backend.alpha.plan import build_plan
    plan = build_plan(compile_code(CODE), ["BTC"], run_frame="1m")
    ev = [fill("BTC@perp", "BUY", 0.1, 100.0, TAG, fee=0.5, ts=1000)]
    d = make_bot(home, "b_res", mode="paper", status="running", pid=DEAD_PID, events=ev, capital=1000.0)
    (d / "equity.jsonl").write_text(json.dumps({"time": 1, "equity": 1000.0}) + "\n")
    before_ev, before_eq = (d / "events.jsonl").read_text(), (d / "equity.jsonl").read_text()
    node = lv.build_node("paper", plan.strategies, plan.symbols, 1000.0, bot_id="b_res", base_frame="1m", resume=True)
    assert node.nora.cl_tag == TAG and node.nora.ledger.balance() == pytest.approx(1000 - 0.5)       # sổ dựng lại từ fill cũ
    node.nora.recorder.record_event("resumed_marker", {})
    node.nora.recorder.record_equity(2)
    assert (d / "events.jsonl").read_text().startswith(before_ev) and "resumed_marker" in (d / "events.jsonl").read_text()
    assert (d / "equity.jsonl").read_text().startswith(before_eq) and len((d / "equity.jsonl").read_text().splitlines()) == 2
    meta = json.loads((d / "bot.json").read_text())
    assert meta["bot_id"] == "b_res" and meta["cl_tag"] == TAG and meta["started_at"] == 1_000_000 and meta["pid"] == os.getpid()
    assert node.nora.slots and all(s.resume is False for s in node.nora.slots)        # paper: sandbox riêng, không có vị thế sàn để nhận lại
    node.dispose()


def test_new_bot_refused_when_id_exists(home, monkeypatch):
    from test.test_live_node import CODE, FAKE_DEMO  # noqa
    monkeypatch.setattr(lv, "load_okx_credentials", lambda: dict(FAKE_DEMO))
    from backend.alpha.compile import compile_code
    from backend.alpha.plan import build_plan
    plan = build_plan(compile_code(CODE), ["BTC"], run_frame="1m")
    make_bot(home, "b_exists", mode="paper")
    with pytest.raises(ValueError):
        lv.build_node("paper", plan.strategies, plan.symbols, 1000.0, bot_id="b_exists", base_frame="1m")


# ─── chỉ stop mới đóng, và chỉ đúng cỡ của bot ───────────────────────────────
def _fake_okx(monkeypatch):
    calls = []
    monkeypatch.setattr(lv, "_okx_signed", lambda method, path, is_demo, body=None: calls.append((method, path, is_demo, body)) or (200, {"code": "0"}))
    return calls


def test_stop_closes_only_own_net_reduce_only(home, monkeypatch):
    calls = _fake_okx(monkeypatch)
    ev = [fill("BTC@perp", "BUY", 0.3, 100.0, TAG, ts=1000), fill("BTC@perp", "BUY", 99.0, 100.0, OTHER, ts=1100, n=2)]    # bot khác giữ 99 trên cùng tài khoản
    make_bot(home, "b_stop", pid=DEAD_PID, events=ev)
    res = lv.stop_bot("b_stop", close_positions=True)
    assert res["status"] == "stopped" and len(calls) == 1
    m, path, demo, body = calls[0]
    assert (m, path, demo) == ("POST", "/api/v5/trade/order", True)
    assert body["reduceOnly"] is True and body["side"] == "sell" and body["ordType"] == "market" and body["clOrdId"].startswith("O") and TAG in body["clOrdId"]
    assert len(body["clOrdId"]) <= 32 and body["clOrdId"].isalnum()
    from backend.nautilus import catalog as cat
    assert float(body["sz"]) * float(cat.instrument_spec("BTC-USDT-SWAP")["ctVal"]) == pytest.approx(0.3, rel=1e-6)    # đúng 0.3 của bot, không phải 99.3


def test_stop_without_close_and_process_exit_never_close(home, monkeypatch):
    calls = _fake_okx(monkeypatch)
    make_bot(home, "b_keep", pid=DEAD_PID, events=[fill("BTC@perp", "BUY", 0.3, 100.0, TAG)])
    assert lv.stop_bot("b_keep", close_positions=False)["status"] == "stopped" and calls == []
    make_bot(home, "b_crash", pid=DEAD_PID, events=[fill("BTC@perp", "BUY", 0.3, 100.0, TAG)])
    assert lv.bot_status(json.loads((home / "live/testnet/b_crash/bot.json").read_text()), str(home / "live/testnet/b_crash")) == "resuming"
    assert calls == []                                           # tiến trình chết không đóng gì


def test_apply_stop_only_acts_when_close_true():
    from types import SimpleNamespace
    seen = []
    slot = SimpleNamespace(stop_close=lambda c: seen.append(c))
    node = SimpleNamespace(nora=SimpleNamespace(slots=[slot], user_strategies=[], instrument_ids=[]))
    lv.apply_stop(node, False)
    assert seen == []
    lv.apply_stop(node, True)
    assert seen == [True]


# ─── một nguồn trạng thái: /live/bots == Công việc ───────────────────────────
def _job(home, jid, bot_id, pid, state="running"):
    d = home / "cache" / "process" / jid
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"id": jid, "kind": "live_bot", "params": {"bot_id": bot_id, "mode": "testnet"}, "state": state, "pid": pid, "created": 1.0,
                                            "finished": None, "exit_code": None, "started": 1.0}))
    (d / "params.json").write_text("{}")
    (d / "out.log").write_text("x\n")


def test_status_consistent_between_bots_and_jobs(home):
    J = ["20261013_010000_00000%d" % i for i in range(1, 5)]
    make_bot(home, "b_run", pid=os.getpid(), job_id=J[0])
    _job(home, J[0], "b_run", os.getpid())
    make_bot(home, "b_stopped", status="running", pid=DEAD_PID, job_id=J[1], stop=True)
    _job(home, J[1], "b_stopped", DEAD_PID, state="done")
    make_bot(home, "b_resum", status="running", pid=DEAD_PID, job_id=J[2])
    _job(home, J[2], "b_resum", DEAD_PID, state="failed")                                   # job đã ghi failed nhưng bot đang chạy lại
    make_bot(home, "b_old", status="running", pid=DEAD_PID, job_id=J[3])
    _job(home, J[3], "b_old", DEAD_PID, state="failed")
    bots = {b["bot_id"]: b["status"] for b in lv.list_bots()}
    jobs = {j["params"]["bot_id"]: j["status"] for j in runner.list_jobs(limit=50, kind="live_bot")}
    assert bots == jobs
    assert bots["b_run"] == "running" and bots["b_stopped"] == "stopped" and bots["b_resum"] == "resuming"
    # job cũ bị thay bằng job chạy lại thì không hiện lại
    _job(home, "20261013_010000_000009", "b_run", DEAD_PID, state="failed")
    assert [j["id"] for j in runner.list_jobs(limit=50, kind="live_bot") if j["params"]["bot_id"] == "b_run"] == [J[0]]
    # prune không xoá job của bot đang chạy lại
    runner.prune_failed_jobs()
    assert (home / "cache" / "process" / J[2]).exists()


# ─── supervisor ──────────────────────────────────────────────────────────────
def test_supervisor_ignores_alive_relaunches_dead_same_id(home):
    make_bot(home, "b_alive", pid=os.getpid(), pid_start=__import__("backend.models.storage", fromlist=["x"]).pid_start_ticks(os.getpid()),
             launch_params={"mode": "testnet", "symbols": ["BTC-USDT-SWAP"], "alpha_id": "x", "bot_id": "b_alive"})
    make_bot(home, "b_dead", pid=DEAD_PID, launch_params={"mode": "testnet", "symbols": ["BTC-USDT-SWAP"], "alpha_id": "x", "capital": 1000.0}, events=[fill("BTC@perp", "BUY", 0.1, 1.0, TAG)])
    make_bot(home, "b_usr", pid=DEAD_PID, stop=False, launch_params={"mode": "testnet"})
    make_bot(home, "b_done", status="stopped", pid=DEAD_PID, launch_params={"mode": "testnet"})
    launched = []

    def fake_launch(kind, params):
        launched.append((kind, params))
        jid = "20261013_020000_0000%02d" % len(launched)
        _job(home, jid, params["bot_id"], os.getpid())
        return jid

    ev_before = (home / "live/testnet/b_dead/events.jsonl").read_text()
    acts = sup.supervise_once(fake_launch)
    assert [(a["bot_id"], a["action"]) for a in acts] == [("b_dead", "resumed")]
    kind, p = launched[0]
    assert kind == "live_bot" and p["bot_id"] == "b_dead" and p["resume"] is True and p["mode"] == "testnet" and p["alpha_id"] == "x"
    meta = json.loads((home / "live/testnet/b_dead/bot.json").read_text())
    assert meta["job_id"].startswith("20261013_020000") and meta["resume_failures"] == 1 and meta["bot_id"] == "b_dead"
    assert (home / "live/testnet/b_dead/events.jsonl").read_text() == ev_before                   # supervisor không đụng dữ liệu
    assert sup.supervise_once(fake_launch) == [] and len(launched) == 1                          # job chạy lại còn sống -> không chạy trùng
    assert not os.path.exists(home / "live/testnet/b_alive/stop")


def test_supervisor_gives_up_after_repeated_failures(home):
    make_bot(home, "b_loop", pid=DEAD_PID, resume_failures=lv.MAX_RESUME_FAILURES, launch_params={"mode": "testnet"})
    assert lv.list_bots()[0]["status"] == "failed"
    assert sup.supervise_once(lambda k, p: "x") == []


# ─── cảnh báo dùng chung instrument ──────────────────────────────────────────
def test_shared_instruments_warning(home):
    make_bot(home, "b_a", pid=os.getpid(), instruments=("BTC-USDT-SWAP.OKX", "ETH-USDT-SWAP.OKX"))
    make_bot(home, "b_b", pid=os.getpid(), tag=OTHER, instruments=("ETH-USDT-SWAP.OKX",))
    make_bot(home, "b_c", pid=os.getpid(), tag="CCCC3333", instruments=("SOL-USDT-SWAP.OKX",))
    make_bot(home, "p_a", mode="paper", pid=os.getpid(), tag="DDDD4444", instruments=("ETH-USDT-SWAP.OKX",))
    sh = lv.get_bot_detail("b_a")["shared_instruments"]
    assert sh == [{"instrument": "ETH-USDT-SWAP.OKX", "bot_id": "b_b"}]
    assert lv.get_bot_detail("b_c")["shared_instruments"] == [] and lv.get_bot_detail("p_a")["shared_instruments"] == []


def test_running_real_style_bot_json_without_new_fields_stays_running(home):
    """Bot cũ (không cl_tag / pid_start / launch_params) đang sống: vẫn running, supervisor bỏ qua."""
    d = home / "live" / "paper" / "legacy"
    d.mkdir(parents=True)
    (d / "bot.json").write_text(json.dumps({"bot_id": "legacy", "mode": "paper", "capital": 10000.0, "status": "running", "pid": os.getpid(), "started_at": 1}))
    assert lv.list_bots()[0]["status"] == "running" and lv.list_bots()[0]["equity"] == 10000.0
    assert sup.supervise_once(lambda k, p: 1 / 0) == []


def _open_bot(tmp_path):
    d = tmp_path / "b"
    d.mkdir()
    with open(d / "events.jsonl", "w") as f:
        f.write(json.dumps({"type": "fill", "symbol": "BTC@perp", "strategy": "s", "side": "BUY", "qty": 2.0, "px": 100.0, "fee": 0.5, "ts": 1, "client_order_id": "x"}) + "\n")
    return d


def test_unrealized_from_fresh_heartbeat_marks(tmp_path, monkeypatch):
    import time
    d = _open_bot(tmp_path)
    (d / "heartbeat.json").write_text(json.dumps({"marks": {"BTC@perp": 110.0}, "marks_ts": int(time.time() * 1000)}))
    monkeypatch.setattr(led, "okx_marks", lambda syms, now=None: pytest.fail("REST must not be used"))
    s = led.snapshot(str(d), {"capital": 1000.0})
    assert s["unrealized"] == pytest.approx(20.0)
    assert s["equity"] == pytest.approx(1000.0 - 0.5 + 20.0)
    assert s["positions"][0]["mark_price"] == 110.0 and s["positions"][0]["unrealized_usd"] == pytest.approx(20.0)


def test_stale_marks_use_rest_ticker(tmp_path, monkeypatch):
    d = _open_bot(tmp_path)
    (d / "heartbeat.json").write_text(json.dumps({"marks": {"BTC@perp": 50.0}, "marks_ts": 1000}))
    seen = []
    monkeypatch.setattr(led, "okx_marks", lambda syms, now=None: seen.append(list(syms)) or {"BTC@perp": 105.0})
    s = led.snapshot(str(d), {"capital": 1000.0})
    assert seen == [["BTC@perp"]]
    assert s["unrealized"] == pytest.approx(10.0)
    assert s["equity"] == pytest.approx(1000.0 - 0.5 + 10.0)
