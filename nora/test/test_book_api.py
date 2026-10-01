"""API sổ chiến lược (/api/studio/book): kiểm đối số, danh sách trắng, trạng thái job, GET / trên book.json tạm.

Không bao giờ chạy job thật: Popen bị thay bằng bản giả ghi lại lệnh.
"""
import json
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import book as book_router
from backend.api.jobs import batch as batch_jobs


class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 12345   # không tồn tại trong /proc
        self.returncode = None

    def wait(self):
        return 0


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("NORA_BOOK_PATH", str(tmp_path / "book.json"))
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    app = FastAPI()
    app.include_router(book_router.router)
    return TestClient(app)


BT = {"start": "2025-03-01", "end": "2025-04-30"}


def _write_book(tmp_path, **extra):
    book = {"status": "HOLDOUT_FAILED", "holdout_pass": False, "generated_at": 1, "risk_per_trade_pct": 0.5,
            "risk": {"max_positions": 8}, "universe": ["BTC@perp"], "windows": {},
            "strategies": [{"id": "breakout_4h_long", "family": "f", "side": "LONG", "description": "d",
                            "params": {"stop_loss_rate": 3.0},
                            "evidence": {"accepted": True, "stability": "2/3", "dev1_tried": 24,
                                         "dev1_top": [{"params": {}, "dev1": {"ret_pct": 5.0, "mdd_pct": 2.0, "daily": [1]},
                                                       "dev2_level": {"ret_pct": 1.0, "trades": 50}}]}}],
            "evidence": {"final": {"holdout_level": {"ret_pct": -1.0, "mdd_pct": 9.0, "trades": 30, "by_symbol": {}}}},
            "rejected_candidates": {"trend_long": {}}, **extra}
    (tmp_path / "book.json").write_text(json.dumps(book), encoding="utf-8")


# ─── Khởi chạy + danh sách trắng ────────────────────────────────────────────
def test_backtest_launches_via_run_limited_without_shell(client, tmp_path):
    _write_book(tmp_path)
    r = client.post("/api/studio/book/backtest", json={**BT, "symbols": ["BTC", "SOL@perp"], "risk_per_trade_pct": 0.75})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    cmd, kw = FakePopen.calls[0]
    assert cmd[0].endswith("scripts/run_limited.sh") and cmd[1:3] == ["--", "scripts/run_book_backtest.py"]
    assert cmd[cmd.index("--symbols") + 1] == "BTC@perp,SOL@perp"
    assert cmd[cmd.index("--risk-per-trade") + 1] == "0.75" and "--strategies" not in cmd   # mặc định: alphas/book.json
    assert kw["start_new_session"] is True and not kw.get("shell")
    assert kw["env"]["NORA_JOB_DIR"].endswith(job_id)
    assert kw["env"]["DBUS_SESSION_BUS_ADDRESS"] and kw["env"]["XDG_RUNTIME_DIR"]
    assert os.path.isfile(os.path.join(kw["env"]["NORA_JOB_DIR"], "job.json"))


def test_backtest_with_explicit_strategies(client):
    r = client.post("/api/studio/book/backtest", json={**BT, "strategies": [
        {"id": "trend_long", "params": {"stop_loss_rate": 2.5}}]})
    assert r.status_code == 200, r.text
    cmd = FakePopen.calls[0][0]
    assert json.loads(cmd[cmd.index("--strategies") + 1]) == [{"id": "trend_long", "params": {"stop_loss_rate": 2.5}}]


@pytest.mark.parametrize("body", [
    {"start": "2025-3-01", "end": "2025-04-30"},                    # sai định dạng ngày
    {"start": "2025-02-30", "end": "2025-04-30"},                    # ngày không tồn tại
    {"start": "2025-05-01", "end": "2025-04-30"},                    # start sau end
    {**BT, "symbols": ["DOGE@spot"]},                                # không phải perp
    {**BT, "symbols": ["PEPE"]},                                     # ngoài vũ trụ
    {**BT, "symbols": ["BTC; rm -rf /"]},                            # chuỗi tuỳ ý
    {**BT, "strategies": [{"id": "khong_co"}]},                      # id lạ
    {**BT, "strategies": [{"id": "trend_long"}, {"id": "trend_long"}]},   # lặp id
    {**BT, "stop_fill": "worst"},
    {**BT, "risk_per_trade_pct": 50},
    {**BT, "risk_per_trade_pct": 0},
    {**BT, "strategies": [{"id": "trend_long", "params": {"stop_loss_rate": "abc"}}]},
])
def test_backtest_rejects_bad_requests(client, tmp_path, body):
    _write_book(tmp_path)
    r = client.post("/api/studio/book/backtest", json=body)
    assert r.status_code == 422, r.text
    assert not FakePopen.calls


def test_backtest_without_book_or_strategies_is_409(client):
    r = client.post("/api/studio/book/backtest", json=BT)   # fixture không ghi book.json
    assert r.status_code == 409 and not FakePopen.calls


def test_wfa_requires_exactly_one_source_and_valid_ids(client, tmp_path):
    ok = {"candidates": ["breakout_4h_long", "breakout_4h_short"], "n": 2, "start": "2025-01-01", "end": "2025-09-30",
          "train_days": 90, "test_days": 30}
    r = client.post("/api/studio/book/wfa", json=ok)
    assert r.status_code == 200, r.text
    cmd = FakePopen.calls[0][0]
    assert cmd[2] == "scripts/validate_book.py"
    assert cmd[cmd.index("--candidates") + 1] == "breakout_4h_long,breakout_4h_short"
    assert cmd[cmd.index("--train-days") + 1] == "90" and cmd[cmd.index("--n") + 1] == "2"
    for bad in ({}, {**ok, "report_dir": "x"}, {**ok, "candidates": ["nope"]}, {**ok, "train_days": 1}, {**ok, "n": 0},
                {**ok, "start": "2025-10-01"}):
        assert client.post("/api/studio/book/wfa", json=bad).status_code == 422, bad
    assert len(FakePopen.calls) == 1


def test_wfa_report_dir_must_be_a_book_run(client, tmp_path):
    run = tmp_path / "data" / "_cache" / "book" / "20260101_000000"
    run.mkdir(parents=True)
    r = client.post("/api/studio/book/wfa", json={"report_dir": "20260101_000000"})
    assert r.status_code == 422                                  # thiếu stage_a.json / report.json
    (run / "stage_a.json").write_text("{}")
    (run / "report.json").write_text("{}")
    r = client.post("/api/studio/book/wfa", json={"report_dir": "20260101_000000", "include_rejected": True})
    assert r.status_code == 200, r.text
    cmd = FakePopen.calls[0][0]
    assert cmd[cmd.index("--report") + 1] == str(run) and "--include-rejected" in cmd
    for evil in ("../../etc", "/etc", str(tmp_path)):
        assert client.post("/api/studio/book/wfa", json={"report_dir": evil}).status_code == 422


def test_build_args_and_whitelist(client):
    r = client.post("/api/studio/book/build", json={"only": ["trend_long"], "n": 6})
    assert r.status_code == 200
    cmd = FakePopen.calls[0][0]
    assert cmd[2] == "scripts/build_strategy_book.py" and cmd[cmd.index("--only") + 1] == "trend_long"
    out = cmd[cmd.index("--out") + 1]           # build luôn ghi vào thư mục job, không đụng nora/alphas
    job_id = os.path.basename(os.path.dirname(out))
    assert out == os.path.join(batch_jobs.jobs_root(), job_id, "alphas") and out != os.path.join(batch_jobs.NORA_DIR, "alphas")
    assert cmd.count("--out") == 1
    assert client.post("/api/studio/book/build", json={"only": ["x"]}).status_code == 422
    assert client.post("/api/studio/book/build", json={"n": 0}).status_code == 422
    # tầng batch_jobs không tin router: loại job lạ / cờ lạ / byte NUL bị chặn
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("shell", ["-c", "id"])
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("book_build", ["--out", "/etc"])
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("book_build", ["--n", "1\0"])
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.build_args("rm", {})


# ─── Xuất bản sổ đã dựng ────────────────────────────────────────────────────
def _built_job(state="done", book=True, testnet=False, name=None, kind="book_build"):
    jid, d = _fake_job(kind=kind, pid=os.getpid() if state == "running" else None, state=state, name=name, log="x\n")
    if book:
        os.makedirs(os.path.join(d, "alphas", "testnet"), exist_ok=True)
        open(os.path.join(d, "alphas", "book.json"), "w").write(json.dumps({"status": "READY_FOR_TESTNET" if testnet else "HOLDOUT_FAILED",
                                                                           "holdout_pass": testnet, "generated_at": 7,
                                                                           "strategies": [{"id": "trend_long"}]}))
        if testnet:
            open(os.path.join(d, "alphas", "testnet", "book.json"), "w").write(json.dumps({"mode": "testnet"}))
        else:
            os.rmdir(os.path.join(d, "alphas", "testnet"))
    return jid


def test_publish_copies_book_and_testnet_and_cleans_stale(client, tmp_path, monkeypatch):
    dest = tmp_path / "published"
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(dest))
    monkeypatch.delenv("NORA_BOOK_PATH")
    j1 = _built_job(testnet=True, name="20260101_000001_aaaaaa")
    r = client.post("/api/studio/book/publish", json={"job_id": j1})
    assert r.status_code == 200, r.text
    assert r.json()["published"] and r.json()["status"] == "READY_FOR_TESTNET" and r.json()["strategies"] == ["trend_long"]
    assert json.loads((dest / "book.json").read_text())["generated_at"] == 7
    assert json.loads((dest / "testnet" / "book.json").read_text()) == {"mode": "testnet"}
    # sổ trượt holdout (không có testnet/book.json) -> testnet cũ ở đích bị xoá
    j2 = _built_job(testnet=False, name="20260101_000002_bbbbbb")
    r = client.post("/api/studio/book/publish", json={"job_id": j2})
    assert r.status_code == 200 and r.json()["testnet_removed"] is True
    assert json.loads((dest / "book.json").read_text())["status"] == "HOLDOUT_FAILED"
    assert not (dest / "testnet" / "book.json").exists()
    assert not list(dest.rglob("*.tmp"))


def test_publish_errors(client, tmp_path, monkeypatch):
    dest = tmp_path / "published"
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(dest))
    monkeypatch.delenv("NORA_BOOK_PATH")
    no_book = _built_job(book=False, name="20260101_000003_cccccc")
    assert client.post("/api/studio/book/publish", json={"job_id": no_book}).status_code == 409      # job xong nhưng không có book.json
    running = _built_job(state="running", name="20260101_000004_dddddd")
    assert client.post("/api/studio/book/publish", json={"job_id": running}).status_code == 409
    other = _built_job(kind="book_wfa", name="20260101_000005_eeeeee")
    assert client.post("/api/studio/book/publish", json={"job_id": other}).status_code == 422
    assert client.post("/api/studio/book/publish", json={"job_id": "20260101_000000_ffffff"}).status_code == 404
    assert client.post("/api/studio/book/publish", json={"job_id": "../../etc"}).status_code == 422
    assert not dest.exists()


# ─── Trạng thái job (thư mục giả) ───────────────────────────────────────────
def _fake_job(kind="book_backtest", pid=2 ** 22 + 1, state="running", log="", result=None, name=None):
    d = os.path.join(batch_jobs.jobs_root(), name or f"{time.strftime('%Y%m%d_%H%M%S')}_abc123")
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": os.path.basename(d), "kind": kind, "args": [], "pid": pid, "created": 1.0, "started": None,
                               "finished": None, "state": state, "exit_code": None})
    open(os.path.join(d, "out.log"), "w", encoding="utf-8").write(log)
    if result is not None:
        json.dump(result, open(os.path.join(d, "result.json"), "w"))
    return os.path.basename(d), d


def test_job_status_transitions(client):
    # xếp hàng: pid còn sống + log chỉ có dòng chờ
    wait_line = "[run_limited] đang chờ job khác của Nora chạy xong...\n"
    jid, d = _fake_job(pid=os.getpid(), log=wait_line)
    s = client.get(f"/api/studio/book/jobs/{jid}").json()
    assert s["status"] == "queued" and s["waiting_in_queue"] is True and s["result"] is None
    # có thêm output -> running
    open(os.path.join(d, "out.log"), "a").write("sổ ['x'] | 2 tài sản\n")
    s = client.get(f"/api/studio/book/jobs/{jid}").json()
    assert s["status"] == "running" and not s["waiting_in_queue"] and s["started"]
    assert s["log_tail"][-1].startswith("sổ")
    # tiến trình chết, log có mã thoát 0 + result.json -> done kèm kết quả
    jid2, d2 = _fake_job(log="x\n[run_limited] peak RAM 10 MB / limit nora.slice | exit 0\n", result={"ret_pct": 1.5}, name="20260101_000001_abc123")
    s = client.get(f"/api/studio/book/jobs/{jid2}").json()
    assert s["status"] == "done" and s["exit_code"] == 0 and s["result"] == {"ret_pct": 1.5} and s["finished"]
    # chết, mã thoát khác 0 -> failed, không có result
    jid3, _ = _fake_job(log="Traceback\n[run_limited] peak RAM 10 MB / limit nora.slice | exit 1\n", name="20260101_000002_abc123")
    s = client.get(f"/api/studio/book/jobs/{jid3}").json()
    assert s["status"] == "failed" and s["exit_code"] == 1 and s["result"] is None
    # chết không rõ mã thoát, không result -> failed
    jid4, _ = _fake_job(log="bị kill\n", name="20260101_000003_abc123")
    assert client.get(f"/api/studio/book/jobs/{jid4}").json()["status"] == "failed"
    # danh sách: mới nhất trước, không kèm log/result
    jobs = client.get("/api/studio/book/jobs?limit=3").json()["jobs"]
    assert [j["id"] for j in jobs] == sorted((j["id"] for j in jobs), reverse=True) and len(jobs) == 3
    assert all("log_tail" not in j and "result" not in j for j in jobs)


def test_job_status_log_tail_and_bad_ids(client):
    jid, _ = _fake_job(state="failed", pid=None, log="\n".join(f"dòng {i}" for i in range(100)) + "\n")
    s = client.get(f"/api/studio/book/jobs/{jid}").json()
    assert len(s["log_tail"]) == 40 and s["log_tail"][-1] == "dòng 99"
    assert client.get("/api/studio/book/jobs/20260101_000000_ffffff").status_code == 404
    assert client.get("/api/studio/book/jobs/..%2F..%2Fetc").status_code in (404, 422)
    assert client.get("/api/studio/book/jobs/not-an-id").status_code == 422


def test_waiter_thread_records_exit_code(client, tmp_path):
    jid = batch_jobs.launch("book_build", ["--n", "2"])
    deadline = time.time() + 5
    while time.time() < deadline and batch_jobs._read_meta(os.path.join(batch_jobs.jobs_root(), jid))["state"] == "running":
        time.sleep(0.05)
    meta = batch_jobs._read_meta(os.path.join(batch_jobs.jobs_root(), jid))
    assert meta["state"] == "done" and meta["exit_code"] == 0 and meta["finished"]


def test_too_many_active_jobs_is_429(client, monkeypatch):
    monkeypatch.setattr(batch_jobs, "MAX_ACTIVE", 1)
    _fake_job(pid=os.getpid(), log="x\n")
    assert client.post("/api/studio/book/build", json={}).status_code == 429


# ─── GET / ───────────────────────────────────────────────────────────────────
def test_get_book_summary(client, tmp_path):
    r = client.get("/api/studio/book/")
    assert r.status_code == 200 and r.json()["book"] is None and r.json()["wfa"] is None
    assert {c["id"] for c in r.json()["candidates"]} >= {"trend_long", "breakout_4h_short"}
    _write_book(tmp_path)
    wfa = tmp_path / "data" / "_cache" / "book_wfa" / "20260101_000000"
    wfa.mkdir(parents=True)
    (wfa / "report.json").write_text(json.dumps({
        "window": ["a", "b"], "gate": {"passed": True, "checks": {}}, "config": {"train_days": 90}, "candidates": [{"id": "x", "configs": [1, 2]}],
        "summary": {"n_folds": 7, "oos_days": 200, "oos_daily": [0.1] * 200, "mc": {"p_mdd_ge_ruin_pct": 1.0}}}))
    body = client.get("/api/studio/book/").json()
    b = body["book"]
    assert b["status"] == "HOLDOUT_FAILED" and b["holdout_pass"] is False
    s = b["strategies"][0]
    assert s["id"] == "breakout_4h_long" and s["params"] == {"stop_loss_rate": 3.0}
    assert s["evidence"]["dev1"] == {"ret_pct": 5.0, "mdd_pct": 2.0} and s["evidence"]["stability"] == "2/3"   # đã bỏ chuỗi 'daily'
    assert b["evidence"]["holdout_level"]["mdd_pct"] == 9.0 and "by_symbol" not in b["evidence"]["holdout_level"]
    assert body["wfa"]["report_dir"] == "20260101_000000" and body["wfa"]["gate"]["passed"] is True
    assert body["wfa"]["summary"]["n_folds"] == 7 and "oos_daily" not in body["wfa"]["summary"]
    assert body["wfa"]["candidates"] == [{"id": "x", "configs": 2}]


def test_router_is_wired_into_main():
    from backend.main import app
    paths = app.openapi()["paths"]
    assert "/api/studio/book/backtest" in paths and "/api/studio/book/jobs/{job_id}" in paths
