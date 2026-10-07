"""Đệm tầng API (việc nặng không tính lại trong request): thống kê tầng phễu, danh sách lượt, GET job (lite + ETag), list_jobs,
trang lệnh portfolio, chuỗi vốn bot live, nến của chart, tính lại lệnh bị chặn thời gian. Mọi đệm phải trả ĐÚNG những gì đường không đệm trả."""
import json
import os
import time

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.jobs import batch as batch_jobs
from backend.api.routers import chart, funnel as fr, live, portfolio
from backend.optimize.funnel.storage import RunStore, atomic_write_json


@pytest.fixture(autouse=True)
def _root(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    for c in (fr._STATS_CACHE, fr._STATS_LAST, fr._COUNTS_CACHE, fr._COUNTS_LAST, portfolio._CACHE):
        c.clear()
    batch_jobs._SUMMARY_CACHE.clear()
    live._EQ_CACHE.clear()


def _fake_job(name, kind="book_backtest", state="done", log="", result=None, progress=None, pid=2 ** 22 + 1, params=None):
    d = os.path.join(batch_jobs.jobs_root(), name)
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": name, "kind": kind, "params": params or {}, "pid": pid, "created": 1.0, "started": 2.0,
                               "finished": 3.0 if state != "running" else None, "state": state, "exit_code": 0 if state == "done" else None})
    open(os.path.join(d, "out.log"), "w", encoding="utf-8").write(log)
    if result is not None:
        json.dump(result, open(os.path.join(d, "result.json"), "w"))
    if progress is not None:
        json.dump(progress, open(os.path.join(d, "progress.json"), "w"))
    return d


def _bump(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


# ─── 1. thống kê tầng phễu ───────────────────────────────────────────────────
def _mk_run(run_id, stages_done=True):
    d = os.path.join(fr.funnel_root(), run_id)
    RunStore(d).close()   # results.sqlite rỗng
    atomic_write_json(os.path.join(d, "run.json"), {"run_id": run_id, "status": "done" if stages_done else "running", "created": 1.0,
                                                    "stages": {"S0_generate": {"status": "done" if stages_done else "running"}}})
    return d


@pytest.fixture
def funnel_client(monkeypatch):
    calls = []

    def fake_stats(store, stage, top_n=20):
        calls.append((stage, top_n))
        return {"stage": stage, "top_n": top_n, "n": len(calls), "x": [1.5, None, "ă"]}
    monkeypatch.setattr(fr, "stage_stats", fake_stats)
    app = FastAPI()
    app.include_router(fr.router)
    return TestClient(app), calls


def test_stage_stats_cache_hit_identical_and_invalidates_on_store_change(funnel_client):
    c, calls = funnel_client
    d = _mk_run("fr-t1", stages_done=False)
    fr.LIVE_MIN_INTERVAL_S = 0.0          # chỉ thử đệm theo chữ ký (nhịp tối thiểu có test riêng)
    url = "/api/studio/funnel/runs/fr-t1/stages/S0_generate/stats?top=21"
    try:
        a = c.get(url)
        b = c.get(url)
        assert a.status_code == 200 and a.content == b.content and len(calls) == 1          # lần 2: đệm, không tính
        assert a.json() == {"stage": "S0_generate", "top_n": 21, "n": 1, "x": [1.5, None, "ă"]}
        assert c.get(url.replace("top=21", "top=22")).json()["top_n"] == 22 and len(calls) == 2   # tham số khác: khoá khác
        _bump(os.path.join(d, "results.sqlite"))
        assert c.get(url).json()["n"] == 3 and len(calls) == 3                               # mtime đổi: tính lại
        wal = os.path.join(d, "results.sqlite-wal")                                          # WAL đổi cũng làm mất đệm
        open(wal, "ab").write(b"x")
        assert c.get(url).json()["n"] == 4
    finally:
        fr.LIVE_MIN_INTERVAL_S = 15.0


def test_stage_stats_body_is_what_fastapi_would_render(funnel_client, monkeypatch):
    c, calls = funnel_client
    _mk_run("fr-t2")
    got = c.get("/api/studio/funnel/runs/fr-t2/stages/S0_generate/stats?top=33")
    app = FastAPI()

    @app.get("/x")
    def x():
        return {"stage": "S0_generate", "top_n": 33, "n": 1, "x": [1.5, None, "ă"]}
    assert got.content == TestClient(app).get("/x").content and got.headers["content-type"] == "application/json"


def test_stage_stats_live_run_min_interval_and_done_run_not_throttled(funnel_client):
    c, calls = funnel_client
    d = _mk_run("fr-live", stages_done=False)
    url = "/api/studio/funnel/runs/fr-live/stages/S0_generate/stats?top=21"
    first = c.get(url).json()
    _bump(os.path.join(d, "results.sqlite"))
    assert c.get(url).json() == first and len(calls) == 1          # kho đổi nhưng < 15 s: trả kết quả trước
    fr._STATS_LAST.put(("fr-live", "S0_generate", 21), (time.monotonic() - 16, fr._STATS_LAST.get(("fr-live", "S0_generate", 21))[1]))
    assert c.get(url).json()["n"] == 2                              # quá 15 s: tính lại
    # lượt đã xong: không có nhịp tối thiểu
    d2 = _mk_run("fr-done", stages_done=True)
    u2 = "/api/studio/funnel/runs/fr-done/stages/S0_generate/stats?top=21"
    c.get(u2)
    _bump(os.path.join(d2, "results.sqlite"))
    c.get(u2)
    assert [k for k in calls].count(("S0_generate", 21)) == 4


def test_stage_stats_errors_unchanged(funnel_client):
    c, _ = funnel_client
    assert c.get("/api/studio/funnel/runs/fr-none/stages/S0_generate/stats").status_code == 404
    assert c.get("/api/studio/funnel/runs/fr-none/stages/S9_nope/stats").status_code == 404
    assert c.get("/api/studio/funnel/runs/ab/stages/S0_generate/stats").status_code == 422


# ─── 2. danh sách lượt ───────────────────────────────────────────────────────
def test_runs_list_counts_cached_and_equal(monkeypatch):
    opened = []
    real = fr.RunStore

    def spy(d, read_only=False):
        opened.append(d)
        return real(d, read_only=read_only)
    monkeypatch.setattr(fr, "RunStore", spy)
    d = _mk_run("fr-r1")
    app = FastAPI()
    app.include_router(fr.router)
    c = TestClient(app)
    c.get("/api/studio/funnel/runs")          # lần mở đầu tiên có thể tạo results.sqlite-wal (đổi chữ ký) -> khởi động ấm trước khi đếm
    fr._COUNTS_CACHE.clear()
    fr._COUNTS_LAST.clear()
    del opened[:]
    a = c.get("/api/studio/funnel/runs").json()
    n = len(opened)
    assert n >= 1
    b = c.get("/api/studio/funnel/runs").json()
    assert a == b and len(opened) == n                              # lần 2 không mở kho
    _bump(os.path.join(d, "results.sqlite"))
    c.get("/api/studio/funnel/runs")
    assert len(opened) == n + 1                                     # chữ ký đổi: đếm lại


# ─── 3. GET job: lite + ETag ─────────────────────────────────────────────────
@pytest.fixture
def app_client():
    from backend.main import app
    return TestClient(app)


JID = "20261001_120000_abc123"
RES = {"ret_pct": 1.5, "trade_list": [{"symbol": "A@perp", "pnl": 1.0, "close_time": 5}], "summary": {"n": 1}}


def test_job_get_default_payload_has_trade_list_and_lite_omits_it(app_client):
    _fake_job(JID, result=RES, log="x\n[run_limited] peak RAM 10 MB | exit 0\n")
    full = app_client.get(f"/api/studio/book/jobs/{JID}")
    lite = app_client.get(f"/api/studio/book/jobs/{JID}?lite=true")
    assert full.status_code == lite.status_code == 200
    assert full.json()["result"] == RES and "trade_list" in full.json()["result"]
    expect = json.loads(full.content)
    expect["result"].pop("trade_list")
    assert lite.json() == expect and "trade_list" not in lite.json()["result"]
    assert app_client.get(f"/api/studio/book/jobs/{JID}?lite=false").content == full.content
    assert app_client.get("/api/studio/book/jobs/nope").status_code == 422
    assert app_client.get("/api/studio/book/jobs/20261001_120000_ffffff").status_code == 404


def test_job_get_etag_304_and_cache_control(app_client):
    d = _fake_job(JID, result=RES)
    r = app_client.get(f"/api/studio/book/jobs/{JID}?lite=true")
    et = r.headers["etag"]
    assert r.headers["cache-control"] == "private, max-age=86400" and et.startswith('"')
    r2 = app_client.get(f"/api/studio/book/jobs/{JID}?lite=true", headers={"If-None-Match": et})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == et and r2.headers["cache-control"] == "private, max-age=86400"
    assert app_client.get(f"/api/studio/book/jobs/{JID}?lite=true", headers={"If-None-Match": f'W/{et}, "zzz"'}).status_code == 304
    # lite và đầy đủ là hai biểu diễn khác nhau -> ETag khác, không 304 nhầm
    full = app_client.get(f"/api/studio/book/jobs/{JID}", headers={"If-None-Match": et})
    assert full.status_code == 200 and full.headers["etag"] != et
    # result.json đổi (mtime) -> ETag cũ không còn khớp
    _bump(os.path.join(d, "result.json"))
    r3 = app_client.get(f"/api/studio/book/jobs/{JID}?lite=true", headers={"If-None-Match": et})
    assert r3.status_code == 200 and r3.headers["etag"] != et


def test_job_get_304_does_not_read_result(app_client, monkeypatch):
    _fake_job(JID, result=RES)
    et = app_client.get(f"/api/studio/book/jobs/{JID}").headers["etag"]
    monkeypatch.setattr(batch_jobs, "status", lambda *a, **k: (_ for _ in ()).throw(AssertionError("không được đọc job khi 304")))
    assert app_client.get(f"/api/studio/book/jobs/{JID}", headers={"If-None-Match": et}).status_code == 304


def test_job_get_running_no_store_and_failed_cacheable(app_client):
    _fake_job(JID, state="running", pid=os.getpid(), log="đang chạy\n")
    r = app_client.get(f"/api/studio/book/jobs/{JID}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store" and "etag" not in r.headers
    assert app_client.get(f"/api/studio/book/jobs/{JID}", headers={"If-None-Match": '"*"'}).status_code == 200
    j2 = "20261001_120001_abc123"
    _fake_job(j2, state="failed", log="boom\n")
    r = app_client.get(f"/api/studio/book/jobs/{j2}")
    assert r.json()["status"] == "failed" and r.headers["cache-control"] == "private, max-age=86400" and "etag" in r.headers


def test_job_get_dead_running_job_becomes_terminal_and_cacheable(app_client):
    _fake_job(JID, state="running", pid=2 ** 22 + 5, result=RES, log="[run_limited] x | exit 0\n")   # job.json còn running, tiến trình đã chết
    r = app_client.get(f"/api/studio/book/jobs/{JID}")
    assert r.json()["status"] == "done" and r.headers["cache-control"] == "private, max-age=86400" and "etag" in r.headers


# ─── 4. list_jobs ────────────────────────────────────────────────────────────
def _old_list_jobs(limit=20, kind=None):
    """Bản list_jobs trước khi có đệm (mọi job đều qua _summary: đọc đuôi log + job.json + progress.json)."""
    rows = []
    for n in sorted((n for n in os.listdir(batch_jobs.jobs_root()) if batch_jobs._JOB_ID_RE.match(n)), reverse=True):
        s = batch_jobs._summary(os.path.join(batch_jobs.jobs_root(), n))
        if not s or (kind and s.get("kind") != kind):
            continue
        s.pop("_lines", None)
        s["label"] = batch_jobs.job_label(s.get("kind"), s.get("params"))
        rows.append(s)
        if len(rows) >= limit:
            break
    return rows


def _mk_many():
    wait = "[run_limited] đang chờ job khác của Nora chạy xong...\n"
    _fake_job("20261001_100000_000001", state="done", log="a\n[run_limited] exit 0\n", result={"r": 1}, progress={"stage": "S1", "done": 3, "total": 3})
    _fake_job("20261001_100001_000002", state="failed", kind="funnel_run", log="x" * 100_000 + "\nboom\n", params={"strategies": ["a"], "n_per_strategy": 5})
    _fake_job("20261001_100002_000003", state="cancelled", kind="book_wfa", log="c\n", progress={"stage": "S3", "done": 1, "total": 9})
    _fake_job("20261001_100003_000004", state="done", log="", progress=None)
    _fake_job("20261001_100004_000005", state="running", pid=os.getpid(), log="working\n", progress={"done": 1})
    _fake_job("20261001_100005_000006", state="running", pid=os.getpid(), log=wait)                   # xếp hàng
    _fake_job("20261001_100006_000007", state="running", kind="custom_backtest", pid=2 ** 22 + 9, log="y\n[run_limited] exit 0\n", result={"z": 1})   # chết -> done   # custom_backtest: chạy tạm, KHÔNG lưu sang thư mục kết quả (ADR §4.6)
    os.makedirs(os.path.join(batch_jobs.jobs_root(), "20261001_100007_000008"))                       # thư mục không có job.json
    os.makedirs(os.path.join(batch_jobs.jobs_root(), "not_a_job"))


def test_list_jobs_equals_uncached_version_cold_and_warm():
    _mk_many()
    old = _old_list_jobs(100)
    for _ in range(2):                                   # lần 1: đệm trống; lần 2: đệm đã điền
        got = batch_jobs.list_jobs(100)
        assert got == old
    for kind in ("book_wfa", "funnel_run", "book_backtest"):
        assert batch_jobs.list_jobs(100, kind) == _old_list_jobs(100, kind)
    assert [x["id"] for x in batch_jobs.list_jobs(3)] == [x["id"] for x in _old_list_jobs(3)]


def test_list_jobs_warm_skips_log_tail_for_terminal_and_keeps_live_ones_fresh(monkeypatch):
    _mk_many()
    batch_jobs.list_jobs(100)
    tails = []
    real = batch_jobs._tail_text
    monkeypatch.setattr(batch_jobs, "_tail_text", lambda p, n: (tails.append(p), real(p, n))[1])
    got = batch_jobs.list_jobs(100)
    read = {os.path.basename(os.path.dirname(p)) for p in tails}
    assert read <= {"20261001_100004_000005", "20261001_100005_000006"}   # chỉ job còn chạy/queued
    st = {j["id"]: j["status"] for j in got}
    assert st["20261001_100005_000006"] == "queued" and st["20261001_100004_000005"] == "running"
    assert st["20261001_100006_000007"] == "done" and st["20261001_100001_000002"] == "failed"
    # job running ghi thêm output -> hết "queued" ngay (không đệm)
    open(os.path.join(batch_jobs.jobs_root(), "20261001_100005_000006", "out.log"), "a").write("output\n")
    assert {j["id"]: j["status"] for j in batch_jobs.list_jobs(100)}["20261001_100005_000006"] == "running"


def test_list_jobs_cache_invalidates_when_job_json_or_progress_changes():
    d = _fake_job("20261001_100000_000001", state="done", progress={"done": 1})
    assert batch_jobs.list_jobs(5)[0]["progress"] == {"done": 1}
    json.dump({"done": 2}, open(os.path.join(d, "progress.json"), "w"))
    _bump(os.path.join(d, "progress.json"))
    assert batch_jobs.list_jobs(5)[0]["progress"] == {"done": 2}
    meta = batch_jobs._read_meta(d)
    meta["exit_code"] = 7
    batch_jobs._write_meta(d, meta)
    _bump(os.path.join(d, "job.json"))
    assert batch_jobs.list_jobs(5)[0]["exit_code"] == 7


def test_list_jobs_returned_rows_are_independent_copies():
    _fake_job("20261001_100000_000001", state="done", params={"a": [1]})
    batch_jobs.list_jobs(5)[0]["params"]["a"].append(2)
    assert batch_jobs.list_jobs(5)[0]["params"] == {"a": [1]}


# ─── 5. portfolio: trang lệnh không parse lại result.json ────────────────────────
def test_portfolio_trades_reuses_parsed_result_and_invalidates_on_mtime(monkeypatch):
    trades = [{"symbol": "A@perp", "strategy": "s", "side": "LONG", "pnl": float(i), "pnl_pct": 1.0, "close_time": 1000 + i, "enter_time": 900 + i}
              for i in range(10)]
    d = _fake_job(JID, result={"trade_list": trades})
    calls = []
    real = batch_jobs.status
    monkeypatch.setattr(batch_jobs, "status", lambda j: (calls.append(j), real(j))[1])
    app = FastAPI()
    app.include_router(portfolio.router)
    c = TestClient(app)
    url = f"/api/studio/portfolio/trades?job_id={JID}&limit=4"
    p1 = c.get(url + "&offset=0").json()
    p2 = c.get(url + "&offset=4").json()
    p3 = c.get(url + "&offset=0&side=LONG").json()
    assert len(calls) == 1 and [t["pnl"] for t in p1["items"]] == [9.0, 8.0, 7.0, 6.0] and [t["pnl"] for t in p2["items"]] == [5.0, 4.0, 3.0, 2.0]
    assert p3["total"] == 10
    json.dump({"trade_list": trades[:3]}, open(os.path.join(d, "result.json"), "w"))
    _bump(os.path.join(d, "result.json"))
    assert c.get(url).json()["total"] == 3 and len(calls) == 2
    # job sai loại / chưa xong vẫn bị từ chối như cũ (không lọt qua đệm)
    _fake_job("20261001_120009_abc123", kind="book_wfa", result={"trade_list": trades})
    assert c.get("/api/studio/portfolio/trades?job_id=20261001_120009_abc123").status_code == 409


# ─── 6. live: chuỗi vốn ──────────────────────────────────────────────────────
def test_equity_series_cache_equal_and_invalidates(tmp_path):
    p = tmp_path / "events.jsonl"
    rows = [{"kind": "start", "t": 5}] + [{"kind": "step", "bar": i, "equity": 100.0 + i} for i in range(6)] + [{"kind": "warn", "t": 9}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    a = live._equity_series(str(tmp_path), cap=4)
    assert a == live._equity_series_uncached(str(tmp_path), cap=4) and len(a[0]) == 4 and a[1] == 5 and a[2] == [{"kind": "warn", "t": 9}]
    assert live._equity_series(str(tmp_path), cap=4) is live._equity_series(str(tmp_path), cap=4)          # đệm
    assert live._equity_series(str(tmp_path), cap=2) == live._equity_series_uncached(str(tmp_path), cap=2)  # cap khác: khoá khác
    with open(p, "a") as fh:
        fh.write(json.dumps({"kind": "step", "bar": 99, "equity": 7.0}) + "\n")
    b = live._equity_series(str(tmp_path), cap=4)
    assert b == live._equity_series_uncached(str(tmp_path), cap=4) and b[0][-1] == {"t": 99, "equity": 7.0}
    assert live._equity_series(str(tmp_path / "nope")) == ([], None, [], live._equity_series_uncached(str(tmp_path / "nope"))[3])
    assert a[3]["bars"] == 6 and a[3]["start"] == 100.0 and a[3]["last"] == 105.0   # tóm tắt trên TOÀN đường vốn, không bị cắt cap=4


# ─── 7. chart: nến đọc từ pkl ────────────────────────────────────────────────
def test_chart_frame_cache_hit_and_invalidates(tmp_path, monkeypatch):
    monkeypatch.setattr(chart, "_FRAME_CACHE", None)
    p = str(tmp_path / "1h.pkl")
    df = pd.DataFrame({"open_time": [1, 2, 3], "open": [1.0, 2.0, 3.0]})
    df.to_pickle(p)
    reads = []
    real = pd.read_pickle
    monkeypatch.setattr(pd, "read_pickle", lambda *a, **k: (reads.append(a), real(*a, **k))[1])
    a = chart._read_frame(p)
    assert a.equals(df) and chart._read_frame(p) is a and len(reads) == 1
    pd.DataFrame({"open_time": [1, 2], "open": [1.0, 2.0]}).to_pickle(p)
    _bump(p)
    b = chart._read_frame(p)
    assert len(b) == 2 and len(reads) == 2
    assert chart._read_frame(str(tmp_path / "none.pkl")) is None


# ─── 8. tính lại lệnh: chặn thời gian của request ────────────────────────────
def test_recompute_bounded_returns_202_then_completes(monkeypatch):
    done = []

    def slow(run_id, alpha_id):
        time.sleep(0.5)
        done.append(alpha_id)
    monkeypatch.setattr(fr, "_run_recompute_subprocess", slow)
    monkeypatch.setattr(fr, "RECOMPUTE_WAIT_S", 0.1)
    r = fr._recompute_bounded("fr-x", "a1")
    assert r.status_code == 202 and json.loads(r.body)["status"] == "computing" and r.headers["retry-after"] == "30"
    assert fr._recompute_bounded("fr-x", "a1").status_code == 202       # vẫn đang chạy: không chạy thêm bản thứ hai
    monkeypatch.setattr(fr, "RECOMPUTE_WAIT_S", 5.0)
    assert fr._recompute_bounded("fr-x", "a1") is None and done == ["a1"]
    assert ("fr-x", "a1") not in fr._RECOMPUTE_INFLIGHT


def test_recompute_bounded_propagates_errors(monkeypatch):
    from fastapi import HTTPException

    def boom(run_id, alpha_id):
        raise HTTPException(500, "tính lại lệnh thất bại: x")
    monkeypatch.setattr(fr, "_run_recompute_subprocess", boom)
    with pytest.raises(HTTPException) as e:
        fr._recompute_bounded("fr-x", "a2")
    assert e.value.status_code == 500
