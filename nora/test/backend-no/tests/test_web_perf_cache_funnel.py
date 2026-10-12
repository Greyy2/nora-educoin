"""Đã chuyển khỏi test/: đệm API của phễu (thống kê tầng, danh sách lượt, tính lại lệnh) — phễu đã gỡ ở P17 T1-B5c (tag pre-p17-research)."""
import json
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mk_run(run_id, stages_done=True):
    d = os.path.join(optimize.funnel_root(), run_id)
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
    monkeypatch.setattr(optimize, "stage_stats", fake_stats)
    app = FastAPI()
    app.include_router(optimize.funnel_router)
    return TestClient(app), calls


def test_stage_stats_cache_hit_identical_and_invalidates_on_store_change(funnel_client):
    c, calls = funnel_client
    d = _mk_run("fr-t1", stages_done=False)
    optimize.LIVE_MIN_INTERVAL_S = 0.0          # chỉ thử đệm theo chữ ký (nhịp tối thiểu có test riêng)
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
        optimize.LIVE_MIN_INTERVAL_S = 15.0


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
    optimize._STATS_LAST.put(("fr-live", "S0_generate", 21), (time.monotonic() - 16, optimize._STATS_LAST.get(("fr-live", "S0_generate", 21))[1]))
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


def test_runs_list_counts_cached_and_equal(monkeypatch):
    opened = []
    real = optimize.RunStore

    def spy(d, read_only=False):
        opened.append(d)
        return real(d, read_only=read_only)
    monkeypatch.setattr(optimize, "RunStore", spy)
    d = _mk_run("fr-r1")
    app = FastAPI()
    app.include_router(optimize.funnel_router)
    c = TestClient(app)
    c.get("/api/studio/funnel/runs")          # lần mở đầu tiên có thể tạo results.sqlite-wal (đổi chữ ký) -> khởi động ấm trước khi đếm
    optimize._COUNTS_CACHE.clear()
    optimize._COUNTS_LAST.clear()
    del opened[:]
    a = c.get("/api/studio/funnel/runs").json()
    n = len(opened)
    assert n >= 1
    b = c.get("/api/studio/funnel/runs").json()
    assert a == b and len(opened) == n                              # lần 2 không mở kho
    _bump(os.path.join(d, "results.sqlite"))
    c.get("/api/studio/funnel/runs")
    assert len(opened) == n + 1                                     # chữ ký đổi: đếm lại


def test_recompute_bounded_returns_202_then_completes(monkeypatch):
    done = []

    def slow(run_id, alpha_id):
        time.sleep(0.5)
        done.append(alpha_id)
    monkeypatch.setattr(optimize, "_run_recompute_subprocess", slow)
    monkeypatch.setattr(optimize, "RECOMPUTE_WAIT_S", 0.1)
    r = optimize._recompute_bounded("fr-x", "a1")
    assert r.status_code == 202 and json.loads(r.body)["status"] == "computing" and r.headers["retry-after"] == "30"
    assert optimize._recompute_bounded("fr-x", "a1").status_code == 202       # vẫn đang chạy: không chạy thêm bản thứ hai
    monkeypatch.setattr(optimize, "RECOMPUTE_WAIT_S", 5.0)
    assert optimize._recompute_bounded("fr-x", "a1") is None and done == ["a1"]
    assert ("fr-x", "a1") not in optimize._RECOMPUTE_INFLIGHT


def test_recompute_bounded_propagates_errors(monkeypatch):
    from fastapi import HTTPException

    def boom(run_id, alpha_id):
        raise HTTPException(500, "tính lại lệnh thất bại: x")
    monkeypatch.setattr(optimize, "_run_recompute_subprocess", boom)
    with pytest.raises(HTTPException) as e:
        optimize._recompute_bounded("fr-x", "a2")
    assert e.value.status_code == 500
