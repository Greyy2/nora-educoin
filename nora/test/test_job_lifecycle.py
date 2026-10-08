"""ADR-P9 §4 bước 2–3: ghi kết quả lâu dài khi job xong, dọn process, giữ log job lỗi 7 ngày, ngoại lệ chạy tạm."""
import json
import os
import time

import pytest

from backend.optimize.process import process as bj


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "data"
    h.mkdir()
    (h / "market").mkdir()   # cây đã chuyển (v2)
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(h))
    bj._SUMMARY_CACHE.clear()
    return h


def _job(home, jid, kind, state="running", result=None, age_days=0, extra=None):
    d = home / "cache" / "process" / jid
    d.mkdir(parents=True)
    t = time.time() - age_days * 86400
    (d / "job.json").write_text(json.dumps({"id": jid, "kind": kind, "params": {"symbols": ["BTC@perp"]}, "state": state, "pid": 1, "created": t,
                                              "finished": t if state != "running" else None, "exit_code": 0 if state == "done" else None}))
    (d / "params.json").write_text(json.dumps({"kind": kind, "params": {}}))
    (d / "out.log").write_text("log\n")
    (d / "checkpoint.tmp").write_text("x")
    if result is not None:
        (d / "result.json").write_text(json.dumps(result))
    for k, v in (extra or {}).items():
        (d / k).mkdir()
        (d / k / "book.json").write_text(v)
    os.utime(d / "job.json", (t, t))
    return d


A, B, C, D = ("20261007_100000_aaaaaa", "20261007_100001_bbbbbb", "20261007_100002_cccccc", "20261007_100003_dddddd")


def test_success_persists_and_cleans_process(home):
    d = _job(home, A, "book_backtest", result={"metrics": {"n": 1}})
    bj._finish(str(d), 0)
    dest = home / "backtest" / A
    assert not d.exists()
    assert sorted(os.listdir(dest)) == ["job.json", "out.log", "params.json", "result.json"]   # không có checkpoint tạm
    meta = json.load(open(dest / "job.json"))
    assert meta["state"] == "done" and meta["persisted"]["from"] == str(d)
    assert bj.job_dir(A) == str(dest)
    s = bj.status(A)
    assert s["status"] == "done" and s["result"] == {"metrics": {"n": 1}} and s["log_tail"] == ["log"]
    assert [j["id"] for j in bj.list_jobs(10)] == [A]


def test_wfa_links_report_and_build_keeps_alphas_and_funnel_record(home):
    w = _job(home, A, "book_wfa", result={"report_path": str(home / "wfa" / "20261007_0900" / "report.json")})
    b = _job(home, B, "book_build", result={"run_dir": "x"}, extra={"alphas": "{}"})
    f = _job(home, C, "funnel_run", result={"ok": 1})
    for d in (w, b, f):
        bj._finish(str(d), 0)
    assert json.load(open(home / "wfa" / A / "job.json"))["report_dir"] == str(home / "wfa" / "20261007_0900")
    assert (home / "alpha" / "book" / B / "alphas" / "book.json").is_file()
    assert (home / "alpha" / "funnel" / C / "job.json").is_file()
    assert bj.job_dir(B) == str(home / "alpha" / "book" / B) and bj.status(C)["status"] == "done"
    assert not any((home / "cache" / "process").iterdir())


def test_custom_goes_to_memory_live_bot_cleaned_edu_cleaned(home):
    c = _job(home, A, "custom_backtest", result={"r": 1})
    l = _job(home, B, "live_bot", result={"r": 1})
    e = _job(home, C, "edu_precompute", result={"r": 1})
    for d in (c, l, e):
        bj._finish(str(d), 0)
    assert not c.exists() and not l.exists() and not e.exists()                  # job tạm: vào bộ nhớ API; bot xong: chỉ còn log -> xoá
    assert bj.status(A)["result"] == {"r": 1} and bj.status(A)["status"] == "done"    # đọc lại từ bộ nhớ
    assert bj.status_etag(A) and bj.status(B) is None
    assert not (home / "backtest").exists() or not os.listdir(home / "backtest")


def test_other_kinds_cleaned_on_done_and_crawl_kept_only_while_staged(home):
    pr = _job(home, A, "presets_build", result={"r": 1})
    c1 = _job(home, B, "data_crawl_okx", result={"r": 1})          # không staging -> dọn khi xong
    c2 = _job(home, C, "data_crawl", result={"r": 1})
    asset = c2 / "staging" / "cex" / "BTC"
    asset.mkdir(parents=True)
    (asset / "1m.pkl").write_bytes(b"")            # tài sản = thư mục có .pkl
    for d in (pr, c1, c2):
        bj._finish(str(d), 0)
    assert not pr.exists() and not c1.exists() and c2.exists()      # c2 còn tài sản chờ promote
    pm = _job(home, D, "data_promote", result={"r": 1})
    (asset / "1m.pkl").unlink(); asset.rmdir()               # promote đã chuyển hết
    bj._finish(str(pm), 0)
    assert not pm.exists() and not c2.exists()


def test_failed_and_cancelled_pruned_at_next_cleanup(home):
    old = _job(home, A, "book_backtest", state="failed", age_days=8)
    new = _job(home, B, "book_wfa", state="failed", age_days=2)
    live = _job(home, C, "live_bot", state="failed", age_days=30)
    cust = _job(home, D, "custom_backtest", state="failed", age_days=30)
    bj._finish(str(new), 1)   # đã failed -> không lưu
    assert sorted(bj.prune_failed_jobs()) == sorted([A, B, C, D])   # cache chỉ giữ tiến trình đang chạy (người dùng chốt 2026-10-08)
    assert not old.exists() and not new.exists() and not live.exists() and not cust.exists()
    assert bj.list_jobs(10) == []


def test_cancelled_with_progress_kept_7_days_else_pruned(home):
    paused = _job(home, A, "funnel_run", state="cancelled", age_days=3)        # huỷ giữa chừng, còn tiến độ -> chạy tiếp được
    (paused / "progress.json").write_text("{}")
    stale = _job(home, B, "funnel_run", state="cancelled", age_days=8)         # tạm dừng quá 7 ngày
    (stale / "progress.json").write_text("{}")
    empty = _job(home, C, "book_backtest", state="cancelled", age_days=0)      # huỷ mà không có gì -> xoá ngay
    gone = sorted(bj.prune_failed_jobs())
    assert gone == sorted([B, C])
    assert paused.exists() and not stale.exists() and not empty.exists()


def test_kill_mid_persist_then_rerun_idempotent(home, monkeypatch):
    d = _job(home, A, "book_backtest", state="done", result={"k": 1})
    with monkeypatch.context() as m:
        m.setattr(bj.os, "rename", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))   # chết đúng lúc rename
        with pytest.raises(KeyboardInterrupt):
            bj.persist_job(str(d))
    assert d.exists() and not (home / "backtest" / A).exists()               # nguồn còn nguyên, đích chưa có
    assert not [n for n in os.listdir(home / "backtest") if n.startswith(".")]   # thư mục tạm đã dọn
    assert bj.persist_job(str(d))["action"] == "persisted" and not d.exists()
    # chết SAU rename, TRƯỚC khi xoá process: dựng lại nguồn từ đích rồi chạy lại -> chỉ dọn process
    d2 = _job(home, A, "book_backtest", state="done", result={"k": 1})
    assert bj.persist_job(str(d2))["action"] == "exists" and not d2.exists()
    assert json.load(open(home / "backtest" / A / "result.json")) == {"k": 1}


def test_persist_finished_jobs_dry_run_default_then_apply(home):
    _job(home, A, "book_backtest", state="done", result={"k": 1})
    _job(home, B, "custom_backtest", state="done", result={"k": 1})
    rows = bj.persist_finished_jobs()
    assert [(r["id"], r["action"]) for r in rows] == [(A, "would_persist"), (B, "would_clean")]
    assert (home / "cache" / "process" / A).exists() and not (home / "backtest" / A).exists()
    assert [r["action"] for r in bj.persist_finished_jobs(apply=True)] == ["persisted", "cleaned"]
    assert (home / "backtest" / A / "result.json").is_file() and not (home / "cache" / "process" / B).exists() and bj.status(B)["result"] == {"k": 1}


def test_portfolio_dashboard_reads_persisted_book_backtest(home):
    from backend.routes import optimize
    res = {"metrics": {}, "daily_returns": [], "trade_list": []}
    d = _job(home, A, "book_backtest", result=res)
    bj._finish(str(d), 0)
    assert optimize._latest_done_backtest() == A
    r, jid = optimize._result_for(A)
    assert jid == A and r == res


def test_ephemeral_lru_bounded_and_enforce_lifecycle_on_start(home, monkeypatch):
    bj._EPH.clear()
    monkeypatch.setattr(bj, "EPHEMERAL_MAX", 2)
    ids = ["20261007_100000_aaaaaa", "20261007_100001_aaaaaa", "20261007_100002_aaaaaa"]
    for i in ids:
        bj._finish(str(_job(home, i, "custom_backtest", result={"i": i})), 0)
    assert bj.status(ids[0]) is None and bj.status(ids[2])["result"] == {"i": ids[2]} and list(bj._EPH) == ids[1:]
    # A5: job tạm bị đẩy khỏi LRU -> "đã hết hạn" (410), id chưa từng có -> không (404)
    assert bj.ephemeral_gone(ids[0]) and not bj.ephemeral_gone(ids[2]) and not bj.ephemeral_gone("20261007_999999_ffffff")
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.optimize.book import registry as reg
    c = TestClient(app)
    r = c.get(f"/api/studio/book/jobs/{ids[0]}")
    assert r.status_code == 410 and r.json()["detail"]["code"] == "EPHEMERAL_GONE"
    assert c.get("/api/studio/book/jobs/20261007_999999_ffffff").status_code == 404
    assert c.get(f"/api/studio/book/jobs/{ids[2]}").status_code == 200
    with pytest.raises(bj.EphemeralGone, match="hết hạn"):
        reg.save_user_alpha(ids[0], "x", "n")
    with pytest.raises(ValueError):
        reg.save_user_alpha("20261007_999999_ffffff", "x", "n")
    # API vừa khởi động: custom xong còn sót + bot đã dừng + job lỗi bị dọn; chỉ bot đang chạy giữ nguyên (cache chỉ giữ tiến trình đang chạy)
    stale = _job(home, "20261007_110000_bbbbbb", "custom_backtest", state="done", result={"r": 1})
    dead_bot = _job(home, "20261007_110001_bbbbbb", "live_bot", state="cancelled")
    run_bot = _job(home, "20261007_110002_bbbbbb", "live_bot", state="running", extra={})
    bj_pid = os.getpid()
    meta = json.loads((run_bot / "job.json").read_text())
    meta["pid"] = bj_pid
    (run_bot / "job.json").write_text(json.dumps(meta))
    fresh_fail = _job(home, "20261007_110003_bbbbbb", "book_wfa", state="failed")
    bj.enforce_lifecycle()
    assert not stale.exists() and not dead_bot.exists() and run_bot.exists() and not fresh_fail.exists()


def test_writer_does_not_recreate_removed_job_dir_and_orphans_are_pruned(home, monkeypatch):
    from backend.crawl.store import write_job_result
    root = home / "cache" / "process"
    d = _job(home, A, "live_bot", state="cancelled")
    os.makedirs(d, exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(d))
    assert write_job_result({"ok": 1}) == str(d / "result.json") and (d / "result.json").exists()   # job còn: ghi bình thường
    import shutil
    shutil.rmtree(d)                                  # API xoá thư mục job, bot ghi result.json sau đó
    assert write_job_result({"ok": 1}) is None and not d.exists()
    old = time.time() - 3600
    orphans = []
    for name, fn in ((B, "result.json"), (C, "out.log")):   # mồ côi: không job.json
        o = root / name
        o.mkdir()
        (o / fn).write_text("{}")
        os.utime(o / fn, (old, old))
        os.utime(o, (old, old))
        orphans.append(o)
    fresh = root / D
    fresh.mkdir()
    (fresh / "out.log").write_text("x")               # mồ côi nhưng mới (< 10 phút): giữ
    for keep in ("_mem", "_staging"):
        (root / keep).mkdir()
        os.utime(root / keep, (old, old))
    running = _job(home, "20261007_100004_eeeeee", "live_bot")
    assert sorted(bj.enforce_lifecycle()["pruned"]) == sorted([B, C])
    assert not any(o.exists() for o in orphans) and fresh.exists() and running.exists()
    assert (root / "_mem").exists() and (root / "_staging").exists()
