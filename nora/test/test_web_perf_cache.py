"""Đệm tầng API (việc nặng không tính lại trong request): GET job (lite + ETag), list_jobs,
trang lệnh portfolio, chuỗi vốn bot live, nến của chart, tính lại lệnh bị chặn thời gian. Mọi đệm phải trả ĐÚNG những gì đường không đệm trả."""
import json
import os
import time

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.jobs import runner as batch_jobs
from backend.routes import alpha, book as optimize


@pytest.fixture(autouse=True)
def _root(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    optimize._CACHE.clear()
    batch_jobs._SUMMARY_CACHE.clear()


def _fake_job(name, kind="book_backtest", state="done", log="", result=None, progress=None, pid=2 ** 22 + 1, params=None):
    base = (batch_jobs.persist_dest_base(kind) if state == "done" else None) or batch_jobs.jobs_root()   # job đã xong sống ở thư mục kết quả bền (ADR §4.5)
    d = os.path.join(base, name)
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
    for n, d in batch_jobs._history_dirs():
        s = batch_jobs._summary(d)
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
    _fake_job("20261001_100001_000002", state="failed", kind="book_wfa", log="x" * 100_000 + "\nboom\n", params={"candidates": ["a"], "n": 5})
    _fake_job("20261001_100002_000003", state="cancelled", kind="book_wfa", log="c\n", progress={"stage": "S3", "done": 1, "total": 9})
    _fake_job("20261001_100003_000004", state="done", log="", progress=None)
    _fake_job("20261001_100004_000005", state="running", pid=os.getpid(), log="working\n", progress={"done": 1})
    _fake_job("20261001_100005_000006", state="running", pid=os.getpid(), log=wait)                   # xếp hàng
    _fake_job("20261001_100006_000007", state="running", kind="book_backtest", pid=2 ** 22 + 9, log="y\n[run_limited] exit 0\n", result={"z": 1})   # chết -> done -> lưu sang backtest/
    batch_jobs._summary(os.path.join(batch_jobs.jobs_root(), "20261001_100006_000007"))      # chốt job chết ngay (done -> lưu sang backtest/) để hai lần đọc thấy cùng một cây
    batch_jobs._SUMMARY_CACHE.clear()
    os.makedirs(os.path.join(batch_jobs.jobs_root(), "20261001_100007_000008"))                       # thư mục không có job.json
    os.makedirs(os.path.join(batch_jobs.jobs_root(), "not_a_job"))


def test_list_jobs_equals_uncached_version_cold_and_warm():
    _mk_many()
    old = _old_list_jobs(100)
    for _ in range(2):                                   # lần 1: đệm trống; lần 2: đệm đã điền
        got = batch_jobs.list_jobs(100)
        assert got == old
    for kind in ("book_wfa", "presets_build", "book_backtest"):
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
    app.include_router(optimize.portfolio_router)
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


def test_chart_frames_come_from_catalog_loader(monkeypatch):
    """Biểu đồ nạp nến qua data.load_candles (cache ở đó theo digest catalog); thiếu dữ liệu -> 404."""
    from fastapi import HTTPException
    from backend.data import data as D
    seen = []
    df = pd.DataFrame({"open_time": [1, 2, 3], "open": [1.0, 2.0, 3.0]})
    monkeypatch.setattr(D, "load_candles", lambda sym, fr, *a, **k: (seen.append((sym, fr)), df)[1])
    out = alpha._frames("BTC", {"id": "x", "side": "LONG", "tree": [[[{"frame": "1h", "column": "close"}, ">", 0]]], "position": {}}, "1h")
    assert seen and all(v is df for v in out.values())

    def missing(sym, fr, *a, **k):
        raise D.CatalogError("thiếu")
    monkeypatch.setattr(D, "load_candles", missing)
    with pytest.raises(HTTPException) as e:
        alpha._frames("BTC", {"id": "x", "side": "LONG", "tree": [[[{"frame": "1h", "column": "close"}, ">", 0]]], "position": {}}, "1h")
    assert e.value.status_code == 404


# ─── 8. tính lại lệnh: chặn thời gian của request ────────────────────────────


