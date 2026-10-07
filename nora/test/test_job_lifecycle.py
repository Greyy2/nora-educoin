"""ADR-P9 §4 bước 2–3: ghi kết quả lâu dài khi job xong, dọn process, giữ log job lỗi 7 ngày, ngoại lệ chạy tạm."""
import json
import os
import time

import pytest

from backend.api.jobs import batch as bj


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


def test_temporary_and_live_kinds_untouched_edu_cleaned(home):
    c = _job(home, A, "custom_backtest", result={"r": 1})
    l = _job(home, B, "live_bot", result={"r": 1})
    e = _job(home, C, "edu_precompute", result={"r": 1})
    for d in (c, l, e):
        bj._finish(str(d), 0)
    assert c.exists() and l.exists() and not e.exists()
    assert not (home / "backtest").exists() or not os.listdir(home / "backtest")


def test_other_kinds_cleaned_on_done_and_crawl_kept_only_while_staged(home):
    pr = _job(home, A, "presets_build", result={"r": 1})
    c1 = _job(home, B, "data_crawl_okx", result={"r": 1})          # không staging -> dọn khi xong
    c2 = _job(home, C, "data_crawl", result={"r": 1})
    asset = c2 / "staging" / "cex" / "BTC"
    asset.mkdir(parents=True)
    (asset / "manifest.json").write_text("{}")
    for d in (pr, c1, c2):
        bj._finish(str(d), 0)
    assert not pr.exists() and not c1.exists() and c2.exists()      # c2 còn tài sản chờ promote
    pm = _job(home, D, "data_promote", result={"r": 1})
    (asset / "manifest.json").unlink(); asset.rmdir()               # promote đã chuyển hết
    bj._finish(str(pm), 0)
    assert not pm.exists() and not c2.exists()


def test_failed_keeps_log_7_days_then_pruned(home):
    old = _job(home, A, "book_backtest", state="failed", age_days=8)
    new = _job(home, B, "book_wfa", state="failed", age_days=2)
    live = _job(home, C, "live_bot", state="failed", age_days=30)
    cust = _job(home, D, "custom_backtest", state="failed", age_days=30)
    bj._finish(str(new), 1)   # đã failed -> không lưu
    assert bj.prune_failed_jobs() == [A]
    assert not old.exists() and new.exists() and live.exists() and cust.exists()
    assert [j["id"] for j in bj.list_jobs(10)] == [D, C, B]   # job lỗi còn hiện trong Lịch sử


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
    assert [(r["id"], r["action"]) for r in rows] == [(A, "would_persist")]
    assert (home / "cache" / "process" / A).exists() and not (home / "backtest" / A).exists()
    assert [r["action"] for r in bj.persist_finished_jobs(apply=True)] == ["persisted"]
    assert (home / "backtest" / A / "result.json").is_file() and (home / "cache" / "process" / B).exists()


def test_portfolio_dashboard_reads_persisted_book_backtest(home):
    from backend.api.routers import portfolio
    res = {"metrics": {}, "daily_returns": [], "trade_list": []}
    d = _job(home, A, "book_backtest", result=res)
    bj._finish(str(d), 0)
    assert portfolio._latest_done_backtest() == A
    r, jid = portfolio._result_for(A)
    assert jid == A and r == res
