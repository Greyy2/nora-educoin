"""
test_data_paths_p93b.py — P9.3b: người gọi (API/optimize/wfa/live) dùng helper đường dẫn của crawl/store.py.

- book.py `_job_run_dir`: gốc chặn path traversal = is_within(path, "runs") (symlink-safe).
- promote mặc định: staging nằm trong cache/process/<job>/staging, chuyển nguyên tử sang market, rồi xoá staging.
- Lịch sử: cây đã chuyển thì job xong trong cache/process KHÔNG phải lịch sử; đọc từ backtest|wfa|carlo/<id>.
- job crawl lỗi giữ log 7 ngày.
"""
import json
import os
import time

import pytest
from fastapi import HTTPException

from backend.optimize.process import process as bj
from backend.routes import book as book_router
from backend.crawl import store as st
from test_data_layout import _save


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "data"
    h.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(h))
    return h


JOB = "20261007_120000_abcdef"


def _job_with_run(home, run_dir, jobs_sub):
    jd = home / jobs_sub / JOB
    jd.mkdir(parents=True)
    (jd / "progress.json").write_text(json.dumps({"run_dir": str(run_dir)}))


def _run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.sqlite").write_text("x")
    return path


def test_job_run_dir_guard_accepts_runs_and_rejects_traversal_and_symlink_escape(home, tmp_path):
    jobs, book = "cache/process", "alpha/book"
    ok = _run(home / book / "run1")
    _job_with_run(home, ok, jobs)
    assert book_router._job_run_dir(JOB) == os.path.realpath(ok)

    outside = _run(tmp_path / "outside")
    for evil in (home / book / ".." / ".." / ".." / "outside",          # ../ thoát gốc
                 home / book / "link"):                                  # symlink thoát gốc
        if evil.name == "link":
            os.symlink(outside, evil)
        (home / jobs / JOB / "progress.json").write_text(json.dumps({"run_dir": str(evil)}))
        with pytest.raises(HTTPException) as e:
            book_router._job_run_dir(JOB)
        assert e.value.status_code == 404
    # tên 'gần giống' gốc (tiền tố chuỗi) cũng bị chặn
    sib = _run(home / (book.split("/")[0] + "_evil") / "run")
    (home / jobs / JOB / "progress.json").write_text(json.dumps({"run_dir": str(sib)}))
    with pytest.raises(HTTPException):
        book_router._job_run_dir(JOB)


def test_promote_default_staging_in_job_process_dir(home):
    jd = home / "cache" / "process" / JOB
    _save(str(jd / "staging"), "cex", "ETH")                 # crawl ghi vào <job>/staging/cex/ETH
    assert os.path.isdir(jd / "staging" / "cex" / "ETH")
    plan = st.run_job({"apply": False})
    assert [a["kind"] for a in plan["actions"]] == ["move"] and os.path.isdir(jd / "staging")   # dry-run không đụng gì
    out = st.run_job({"apply": True})
    assert out["applied"] and os.path.isfile(st.market_dir(venue="cex", symbol="ETH") + "/1m.pkl")
    assert not os.path.exists(jd / "staging")                 # staging bị xoá sau khi chuyển hết
    assert not [n for n in os.listdir(home / "cex") if n.startswith(".promote_")]   # không để lại tên tạm


def test_promote_keeps_staging_when_gate_blocks(home):
    jd = home / "cache" / "process" / JOB
    _save(str(jd / "staging"), "cex", "ETH", days=1)          # quá mỏng -> NEEDS_MORE_DATA
    out = st.run_job({"apply": True})
    assert out["actions"] == [] and os.path.isdir(jd / "staging" / "cex" / "ETH")


def test_launch_sets_crawl_output_dir_into_job_process_dir(home, monkeypatch):
    from test_book_api import FakePopen
    monkeypatch.setattr(bj.subprocess, "Popen", FakePopen)
    jid = bj.launch("data_crawl_okx", {"symbols": ["BTC"], "years": 1})
    p = json.load(open(os.path.join(bj.job_dir(jid), "params.json")))["params"]
    assert p["output_dir"] == os.path.join(bj.jobs_root(), jid, "staging", "cex")


def _mkjob(d, state, kind="book_backtest", age_days=0):
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"id": d.name, "kind": kind, "params": {}, "state": state, "pid": 1, "created": time.time()}))
    t = time.time() - age_days * 86400
    os.utime(d / "job.json", (t, t))


def test_history_reads_persisted_dirs_and_hides_done_process_jobs_after_migration(home):
    (home / "market").mkdir()                                
    _mkjob(home / "cache" / "process" / "20261007_100000_aaaaaa", "done")        # đã xong, còn trong process: KHÔNG phải lịch sử
    _mkjob(home / "cache" / "process" / "20261007_110000_bbbbbb", "running")     # đang chạy: hiện
    _mkjob(home / "backtest" / "20261007_090000_cccccc", "done")                 # kết quả lâu dài: hiện
    (home / "backtest" / "education").mkdir()                                    # không phải job
    ids = [j["id"] for j in bj.list_jobs(50)]
    assert ids == ["20261007_110000_bbbbbb", "20261007_090000_cccccc"]
    assert bj.job_dir("20261007_090000_cccccc") == str(home / "backtest" / "20261007_090000_cccccc")   # cổng đọc kết quả theo id
    assert bj.job_dir("20261007_100000_aaaaaa") == str(home / "cache" / "process" / "20261007_100000_aaaaaa")


def test_prune_failed_crawl_jobs_after_7_days(home):
    root = home / "cache" / "process"
    old_fail = root / "20261001_100000_aaaaaa"; _mkjob(old_fail, "failed", "data_crawl", age_days=8)
    new_fail = root / "20261006_100000_bbbbbb"; _mkjob(new_fail, "failed", "data_crawl_okx", age_days=2)
    old_bt = root / "20261001_100000_cccccc"; _mkjob(old_bt, "failed", "book_backtest", age_days=30)
    old_ok = root / "20261001_100000_dddddd"; _mkjob(old_ok, "done", "data_crawl", age_days=30)
    assert bj.prune_failed_crawl_jobs() == ["20261001_100000_aaaaaa"]
    assert not old_fail.exists() and new_fail.exists() and old_bt.exists() and old_ok.exists()
