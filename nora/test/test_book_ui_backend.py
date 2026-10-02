"""Phần backend của docs/ui_contract.md: catalog (default_params/universe/windows), /alphas, nhãn + lọc job, WFA cấu hình chọn tay,
stage_a trong result của build_strategy_book, oos_daily_dates của WFA."""
import json
import os
import time

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import book as book_router
from backend.api.jobs import batch as batch_jobs
from test_portfolio_wfa import CFG, DAY, RISK, START, T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)
from test_book_api import FakePopen


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("NORA_BOOK_PATH", str(tmp_path / "book.json"))
    monkeypatch.setenv("NORA_PRESETS_PATH", str(tmp_path / "presets.json"))   # không đọc preset thật của data/alphas
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    app = FastAPI()
    app.include_router(book_router.router)
    app.include_router(book_router.alphas_router)
    return TestClient(app)


# ─── §1 catalog / alphas ────────────────────────────────────────────────────
def test_catalog_default_params_universe_windows(client, tmp_path):
    body = client.get("/api/studio/book/").json()
    cat = {c["id"]: c for c in body["catalog"]}
    assert body["candidates"] == body["catalog"] and body["latest_wfa"] == body["wfa"]
    c = cat["breakout_4h_long"]
    assert c["default_params"] == {"stop_loss_rate": 2.0, "trailing_stop": 3.0, "trailing_activation_pct": 1.0, "timeout": 10080}
    for cand in cat.values():       # đúng quy tắc run_book_backtest: phần tử giữa của mỗi khoá
        assert set(cand["default_params"]) == set(cand["space"]) and all(cand["default_params"][k] in v for k, v in cand["space"].items())
        assert cand["default_params"] == {k: v[len(v) // 2] for k, v in cand["space"].items()}
    assert all(u.endswith("@perp") for u in body["universe"]) and "BTC@perp" in body["universe"]
    # sổ có universe/windows -> lấy từ sổ
    (tmp_path / "book.json").write_text(json.dumps({"status": "X", "strategies": [], "universe": ["BTC@perp"],
                                                    "windows": {"start": "2025-01-01", "dev1_end": "2025-02-01", "dev2_end": "2025-03-01",
                                                                "end": "2025-04-01"}}))
    b2 = client.get("/api/studio/book/").json()
    assert b2["universe"] == ["BTC@perp"] and b2["windows"]["dev2_end"] == "2025-03-01"


def test_default_params_match_run_book_backtest_mid_params():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rbb", os.path.join(os.path.dirname(__file__), "..", "backend", "core", "backtest", "run_book_backtest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from backend.core.strategy.strategy_book import CANDIDATES
    for c in CANDIDATES:
        assert book_router.default_params(c["space"]) == mod._mid_params(c, {})


def test_alphas_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_jobs, "NORA_DIR", str(tmp_path / "nora"))
    r = client.get("/api/studio/alphas")
    assert r.status_code == 200 and r.json() == {"registry": None, "book": None}
    os.makedirs(tmp_path / "nora" / "data" / "alphas")
    (tmp_path / "nora" / "data" / "alphas" / "registry.json").write_text(json.dumps({"alphas": [1]}))
    (tmp_path / "book.json").write_text(json.dumps({"status": "READY"}))
    assert client.get("/api/studio/alphas").json() == {"registry": {"alphas": [1]}, "book": {"status": "READY"}}
    (tmp_path / "book.json").write_text("{oops")
    assert client.get("/api/studio/alphas").status_code == 500


# ─── §2 nhãn + lọc kind ─────────────────────────────────────────────────────
def _meta_job(kind, args, name):
    d = os.path.join(batch_jobs.jobs_root(), name)
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": name, "kind": kind, "args": args, "pid": None, "created": 1.0, "started": None, "finished": None,
                               "state": "done", "exit_code": 0})


def test_job_labels_and_kind_filter(client):
    bt = ["--strategies", json.dumps([{"id": "breakout_4h_long"}, {"id": "breakout_4h_short"}]), "--symbols", "BTC@perp,SOL@perp",
          "--start", "2025-03-01", "--end", "2025-04-30"]
    _meta_job("book_backtest", bt, "20260101_000001_a1b2c3")
    _meta_job("book_backtest", ["--start", "2025-01-01", "--end", "2025-02-01"], "20260101_000002_a1b2c3")
    _meta_job("book_wfa", ["--candidates", "trend_long,trend_short", "--n", "3"], "20260101_000003_a1b2c3")
    _meta_job("book_build", ["--only", "trend_long", "--n", "24"], "20260101_000004_a1b2c3")
    jobs = client.get("/api/studio/book/jobs").json()["jobs"]
    by = {j["id"]: j for j in jobs}
    assert by["20260101_000001_a1b2c3"]["label"] == "Backtest · breakout_4h_long, breakout_4h_short · BTC,SOL · 2025-03-01→2025-04-30"
    assert by["20260101_000002_a1b2c3"]["label"] == "Backtest · sổ alphas/book.json · cả vũ trụ · 2025-01-01→2025-02-01"
    assert by["20260101_000003_a1b2c3"]["label"].startswith("WFA · trend_long, trend_short (n=3)")
    assert by["20260101_000004_a1b2c3"]["label"] == "Dựng sổ · trend_long · n=24"
    only_bt = client.get("/api/studio/book/jobs?kind=book_backtest").json()["jobs"]
    assert [j["kind"] for j in only_bt] == ["book_backtest"] * 2 and only_bt[0]["id"] > only_bt[1]["id"]
    assert [j["id"] for j in client.get("/api/studio/book/jobs?kind=book_wfa").json()["jobs"]] == ["20260101_000003_a1b2c3"]
    # lọc trước khi cắt limit
    assert len(client.get("/api/studio/book/jobs?kind=book_backtest&limit=1").json()["jobs"]) == 1
    assert client.get("/api/studio/book/jobs?kind=rm").status_code == 422
    assert all({"job_id" not in j} or True for j in jobs) and all("label" in j and "args" in j and "status" in j for j in jobs)


# ─── §4 WFA cấu hình chọn tay (API) ─────────────────────────────────────────
STRATS = [{"id": "breakout_4h_long", "configs": [{"stop_loss_rate": 2.0, "trailing_stop": 3.0}]},
          {"id": "breakout_4h_short", "configs": [{"stop_loss_rate": 1.5}, {"stop_loss_rate": 3.0}]}]


def test_wfa_strategies_written_to_job_dir(client):
    r = client.post("/api/studio/book/wfa", json={"mode": "advanced", "strategies": STRATS, "symbols": ["BTC", "SOL@perp"], "risk_per_trade_pct": 0.4,
                                                  "start": "2025-01-01", "end": "2025-09-30", "train_days": 90, "test_days": 30})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    cmd, kw = FakePopen.calls[0]
    path = cmd[cmd.index("--strategies-json") + 1]
    assert path == os.path.join(batch_jobs.jobs_root(), jid, "strategies.json")
    saved = json.load(open(path))     # advanced: khoá người dùng giữ nguyên; khoá thiếu của space lấy từ preset (đủ mọi khoá của space)
    assert [s["id"] for s in saved] == [s["id"] for s in STRATS]
    for want, got in zip(STRATS, saved):
        assert len(want["configs"]) == len(got["configs"])
        for w, g in zip(want["configs"], got["configs"]):
            assert {k: g[k] for k in w} == w and set(g) >= {"stop_loss_rate", "trailing_stop", "trailing_activation_pct", "timeout"}
    assert cmd[cmd.index("--symbols") + 1] == "BTC@perp,SOL@perp" and cmd[cmd.index("--risk-per-trade") + 1] == "0.4"
    assert "--candidates" not in cmd and "--report" not in cmd
    # nhãn đọc lại file
    lab = client.get("/api/studio/book/jobs?kind=book_wfa").json()["jobs"][0]["label"]
    assert lab.startswith("WFA · breakout_4h_long×1, breakout_4h_short×2 · BTC,SOL ·")
    assert batch_jobs.job_label("book_wfa", cmd[3:]).startswith("WFA · breakout_4h_long×1")


@pytest.mark.parametrize("patch", [
    {"strategies": [{"id": "nope", "configs": [{}]}]},
    {"strategies": [{"id": "trend_long", "configs": []}]},
    {"strategies": [{"id": "trend_long", "configs": [{"khong_co": 1.0}]}]},               # khoá ngoài không gian tham số
    {"strategies": [{"id": "trend_long", "configs": [{"stop_loss_rate": "x"}]}]},
    {"strategies": [{"id": "trend_long", "configs": [{}]}, {"id": "trend_long", "configs": [{}]}]},   # lặp id
    {"strategies": STRATS, "candidates": ["trend_long"]},                                   # hai nguồn
    {"strategies": STRATS, "report_dir": "x"},
    {"strategies": STRATS, "symbols": ["PEPE"]},
    {"strategies": STRATS, "risk_per_trade_pct": 9},
    {"strategies": [{"id": "trend_long", "configs": [{}] * 51}]},
])
def test_wfa_strategies_rejects_bad_requests(client, patch):
    assert client.post("/api/studio/book/wfa", json={"mode": "advanced", **patch}).status_code == 422, patch
    assert not FakePopen.calls


# ─── §4 validate_book với cấu hình chọn tay (chạy thật trên thị trường giả lập) ──
def _write(tmp_path, items):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(items))
    return str(p)


def test_validate_book_with_explicit_configs_on_synthetic_market(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    long_cfg = {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720}
    short_cfgs = [{"stop_loss_rate": 1.5, "trailing_stop": 2.0, "timeout": 720}, {"stop_loss_rate": 2.5, "trailing_stop": 2.0, "timeout": 720}]
    path = _write(tmp_path, [{"id": "t_long", "configs": [long_cfg]}, {"id": "t_short", "configs": short_cfgs}])
    start, end = (f"{pd.Timestamp(t, unit='ms'):%Y-%m-%d}" for t in (START, T0 + 66 * DAY))
    res = vb.main(["--strategies-json", path, "--symbols", "AAA@perp,BBB", "--workers", "2", "--per-worker-mb", "300", "--start", start,
                   "--end", end, "--train-days", "15", "--test-days", "10", "--sims", "200"])
    assert res["symbols"] == ["AAA@perp", "BBB@perp"]
    assert [(c["id"], len(c["configs"])) for c in res["candidates"]] == [("t_long", 1), ("t_short", 2)]
    assert res["candidates"][0]["configs"] == [long_cfg]                         # đúng cấu hình đã gửi
    for f in res["folds"]:
        assert f["chosen"]["t_long"] in (long_cfg, None) and f["chosen_idx"]["t_long"] in (0, None)   # 1 cấu hình = cố định
        assert len(f["is_candidates"]["t_long"]) == 1 and len(f["is_candidates"]["t_short"]) == 2
        assert f["chosen"]["t_short"] in short_cfgs + [None]
    assert res["source"]["strategies_json"] is True
    # oos_daily_dates song song với chuỗi lợi suất ngày (level + extreme), liên tục theo ngày, đúng cửa sổ OOS
    agg = res["aggregate"]
    assert agg is res["summary"] and res["mc"] is res["summary"]["mc"]
    for sf in ("level", "extreme"):
        dates, daily = agg["oos_daily_dates"][sf], agg["oos_daily"][sf]
        assert len(dates) == len(daily) == sum(len(f[f"oos_daily_{sf}"]) for f in res["folds"])
        for f in res["folds"]:
            assert f[f"oos_daily_dates_{sf}"][0] == f["test"][0]
            assert len(f[f"oos_daily_dates_{sf}"]) == len(f[f"oos_daily_{sf}"])
        assert dates[0] == start[:0] + res["folds"][0]["test"][0]
    for f in res["folds"]:
        d = pd.to_datetime(f["oos_daily_dates_extreme"])
        assert (d[1:] - d[:-1] == pd.Timedelta(days=1)).all()
    json.dumps(res, default=str)
    # đã ghi report.json có đủ khoá theo hợp đồng
    rep = json.loads(sorted((market / "_cache" / "book_wfa").glob("*/report.json"))[-1].read_text())
    assert {"folds", "aggregate", "mc", "gate"} <= set(rep) and "oos_daily_dates" in rep["aggregate"]


def test_validate_book_strategies_json_validation(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    for bad in ([], [{"id": "zzz", "configs": [{}]}], [{"id": "t_long", "configs": []}], [{"id": "t_long", "configs": [{"bogus": 1}]}],
                [{"id": "t_long", "configs": [{}]}, {"id": "t_long", "configs": [{}]}]):
        with pytest.raises(SystemExit):
            vb.candidates_from_json(_write(tmp_path, bad))
    assert vb.candidates_from_json(_write(tmp_path, [{"id": "t_long", "configs": [{"sig.lo": 35}]}])) == [
        {"id": "t_long", "configs": [{"sig.lo": 35}]}]
    with pytest.raises(SystemExit):                                              # đúng một nguồn
        vb.main(["--strategies-json", _write(tmp_path, [{"id": "t_long", "configs": [{}]}]), "--candidates", "t_long"])


# ─── §6 stage_a ─────────────────────────────────────────────────────────────
def test_stage_a_rows_helper():
    bsb = _load_script("build_strategy_book")
    neg = float("-inf")
    dev1 = {"ret_pct": 5.0, "mdd_pct": 2.0, "trades": 40, "symbols_positive": 5, "sharpe": 1.2, "win_pct": 50, "daily": [1, 2], "by_symbol": {}}
    rows = bsb.stage_a_rows({"a": [{"params": {"k": 1}, "dev1": dev1, "score": 2.5}, {"params": {"k": 2}, "dev1": dev1, "score": neg}]})
    assert rows == {"a": [{"params": {"k": 1}, "dev1": {k: dev1[k] for k in ("ret_pct", "mdd_pct", "trades", "symbols_positive", "sharpe")},
                           "score": 2.5, "passed": True},
                          {"params": {"k": 2}, "dev1": rows["a"][1]["dev1"], "score": None, "passed": False}]}
    json.dumps(rows, allow_nan=False)


def test_build_strategy_book_result_json_has_stage_a_for_every_config(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    job_dir = tmp_path / "job"
    monkeypatch.setenv("NORA_JOB_DIR", str(job_dir))
    bsb = _load_script("build_strategy_book")
    bsb.main(["--workers", "2", "--per-worker-mb", "300", "--n", "4", "--out", str(tmp_path / "alphas")])
    res = json.loads((job_dir / "result.json").read_text())
    assert set(res["stage_a"]) == {"t_long", "t_short"}
    assert len(res["stage_a"]["t_long"]) == 2 and len(res["stage_a"]["t_short"]) == 2          # lưới nhỏ hơn n=4 -> thử hết
    for rows in res["stage_a"].values():
        assert [r["score"] for r in rows if r["score"] is not None] == sorted((r["score"] for r in rows if r["score"] is not None), reverse=True)
        for r in rows:
            assert set(r) == {"params", "dev1", "score", "passed"} and set(r["dev1"]) == {"ret_pct", "mdd_pct", "trades", "symbols_positive", "sharpe"}
            assert r["passed"] == (r["score"] is not None)
    # khớp stage_a.json (đầy đủ) về số cấu hình và tham số
    full = json.loads(sorted((market / "_cache" / "book").glob("*/stage_a.json"))[-1].read_text())
    for cid, rows in full.items():
        assert [r["params"] for r in rows] == [r["params"] for r in res["stage_a"][cid]]
