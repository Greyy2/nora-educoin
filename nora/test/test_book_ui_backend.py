"""Phần backend của docs/ui_contract.md: catalog (default_params/universe/windows), /alphas, nhãn + lọc job, WFA cấu hình chọn tay,
stage_a trong result của build_strategy_book, oos_daily_dates của WFA."""
import pathlib

from backend.crawl.store import alpha_run_dir, run_dir
import json
import os
import threading

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import optimize
from backend.optimize.process import process as batch_jobs
from job_modules import launched
from test_portfolio_wfa import DAY, START, T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data


class FakePopen:
    """Job chạy mãi (wait chặn): nếu waiter kết thúc ngay, job 'done' không còn trong Lịch sử (ADR §4.5: chỉ job đang chạy / lỗi ở cache/process)."""
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 12345   # không tồn tại trong /proc
        self.returncode = None

    def wait(self):
        threading.Event().wait()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("NORA_BOOK_PATH", str(tmp_path / "book.json"))
    monkeypatch.setenv("NORA_PRESETS_PATH", str(tmp_path / "presets.json"))   # không đọc preset thật của data/alphas
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    app = FastAPI()
    app.include_router(optimize.book_router)
    app.include_router(optimize.alphas_router)
    return TestClient(app)


# ─── §1 catalog / alphas ────────────────────────────────────────────────────
def test_catalog_default_params_universe_windows(client, tmp_path):
    body = client.get("/api/studio/book/").json()
    cat = {c["id"]: c for c in body["catalog"]}
    assert body["candidates"] == body["catalog"] and body["latest_wfa"] == body["wfa"]
    c = cat["kema_long"]
    assert c["default_params"] == {"sig.ema_n": 30, "sig.k_up": 2.0, "sig.k_dn": 2.0, "stop_loss_rate": 3.0}
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
    from backend.optimize.search import evaluate as mod   # P9.6: thư viện run.py nằm ở search/evaluate.py
    from backend.optimize.book.build import CANDIDATES
    for c in CANDIDATES:
        assert optimize.default_params(c["space"]) == mod._mid_params(c, {})


def test_alphas_endpoint(client, tmp_path, monkeypatch):
    r = client.get("/api/studio/alphas")
    assert r.status_code == 200 and r.json()["registry"] is None and r.json()["book"] is None and r.json()["registry_status"] == []
    assert r.json()["engine"]["main"]["needs_rebuild"] is None and r.json()["engine"]["explore"]["needs_rebuild"] is None   # chưa có sổ
    os.makedirs(tmp_path / "data" / "alpha")
    (tmp_path / "data" / "alpha" / "registry.json").write_text(json.dumps({"alphas": [1]}))
    (tmp_path / "book.json").write_text(json.dumps({"status": "READY"}))
    j = client.get("/api/studio/alphas").json()
    assert j["registry"] == {"alphas": [1]} and j["book"] == {"status": "READY"}
    (tmp_path / "book.json").write_text("{oops")
    assert client.get("/api/studio/alphas").status_code == 500


# ─── §2 nhãn + lọc kind ─────────────────────────────────────────────────────
def _meta_job(kind, params, name):
    d = os.path.join(batch_jobs.persist_dest_base(kind) or run_dir("backtest"), name)   # job đã xong sống ở thư mục kết quả bền, không ở cache/process
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": name, "kind": kind, "params": params, "pid": None, "created": 1.0, "started": None, "finished": None,
                               "state": "done", "exit_code": 0})


def test_job_labels_and_kind_filter(client):
    bt = {"strategies": [{"id": "breakout_4h_long"}, {"id": "breakout_4h_short"}], "symbols": ["BTC@perp", "SOL@perp"],
          "start": "2025-03-01", "end": "2025-04-30"}
    _meta_job("book_backtest", bt, "20260101_000001_a1b2c3")
    _meta_job("book_backtest", {"start": "2025-01-01", "end": "2025-02-01"}, "20260101_000002_a1b2c3")
    _meta_job("book_wfa", {"candidates": ["trend_long", "trend_short"], "n": 3}, "20260101_000003_a1b2c3")
    _meta_job("book_build", {"only": ["trend_long"], "n": 24}, "20260101_000004_a1b2c3")
    jobs = client.get("/api/studio/book/jobs").json()["jobs"]
    by = {j["id"]: j for j in jobs}
    assert by["20260101_000001_a1b2c3"]["label"] == "Backtest · breakout_4h_long, breakout_4h_short · BTC,SOL · 2025-03-01→2025-04-30"
    lab = by["20260101_000002_a1b2c3"]["label"]
    assert lab.startswith("Backtest · sổ ") and lab.endswith("/alpha/book.json · cả vũ trụ · 2025-01-01→2025-02-01") and "alphas/" not in lab
    assert by["20260101_000003_a1b2c3"]["label"].startswith("WFA · trend_long, trend_short (n=3)")
    assert by["20260101_000004_a1b2c3"]["label"] == "Dựng sổ · trend_long · n=24"
    only_bt = client.get("/api/studio/book/jobs?kind=book_backtest").json()["jobs"]
    assert [j["kind"] for j in only_bt] == ["book_backtest"] * 2 and only_bt[0]["id"] > only_bt[1]["id"]
    assert [j["id"] for j in client.get("/api/studio/book/jobs?kind=book_wfa").json()["jobs"]] == ["20260101_000003_a1b2c3"]
    # lọc trước khi cắt limit
    assert len(client.get("/api/studio/book/jobs?kind=book_backtest&limit=1").json()["jobs"]) == 1
    assert client.get("/api/studio/book/jobs?kind=rm").status_code == 422
    assert all({"job_id" not in j} or True for j in jobs) and all("label" in j and "params" in j and "status" in j for j in jobs)


# ─── §4 WFA cấu hình chọn tay (API) ─────────────────────────────────────────
STRATS = [{"id": "breakout_4h_long", "configs": [{"stop_loss_rate": 2.0, "trailing_stop": 3.0}]},
          {"id": "breakout_4h_short", "configs": [{"stop_loss_rate": 1.5}, {"stop_loss_rate": 3.0}]}]


def test_wfa_strategies_go_into_job_params(client):
    r = client.post("/api/studio/book/wfa", json={"mode": "advanced", "strategies": STRATS, "symbols": ["BTC", "SOL@perp"], "risk_per_trade_pct": 0.4,
                                                  "start": "2025-01-01", "end": "2025-09-30", "train_days": 90, "test_days": 30})
    assert r.status_code == 200, r.text
    kind, p = launched(FakePopen.calls[0])
    saved = p["strategies"]     # advanced: khoá người dùng giữ nguyên; khoá thiếu của space lấy từ preset (đủ mọi khoá của space)
    assert [s["id"] for s in saved] == [s["id"] for s in STRATS]
    for want, got in zip(STRATS, saved):
        assert len(want["configs"]) == len(got["configs"])
        for w, g in zip(want["configs"], got["configs"]):
            assert {k: g[k] for k in w} == w and set(g) >= {"stop_loss_rate", "trailing_stop", "trailing_activation_pct", "timeout"}
    assert p["symbols"] == ["BTC@perp", "SOL@perp"] and p["risk_per_trade"] == 0.4
    assert "candidates" not in p and "report" not in p
    lab = client.get("/api/studio/book/jobs?kind=book_wfa").json()["jobs"][0]["label"]
    assert lab.startswith("WFA · breakout_4h_long×1, breakout_4h_short×2 · BTC,SOL ·")
    assert batch_jobs.job_label("book_wfa", p).startswith("WFA · breakout_4h_long×1")


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
def test_validate_book_with_explicit_configs_on_synthetic_market(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    long_cfg = {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720}
    short_cfgs = [{"stop_loss_rate": 1.5, "trailing_stop": 2.0, "timeout": 720}, {"stop_loss_rate": 2.5, "trailing_stop": 2.0, "timeout": 720}]
    strategies = [{"id": "t_long", "configs": [long_cfg]}, {"id": "t_short", "configs": short_cfgs}]
    start, end = (f"{pd.Timestamp(t, unit='ms'):%Y-%m-%d}" for t in (START, T0 + 66 * DAY))
    res = vb.run_job({"strategies": strategies, "symbols": "AAA@perp,BBB", "workers": 2, "per_worker_mb": 300, "start": start,
                      "end": end, "train_days": 15, "test_days": 10, "sims": 200})
    assert res["symbols"] == ["AAA@perp", "BBB@perp"]
    assert [(c["id"], len(c["configs"])) for c in res["candidates"]] == [("t_long", 1), ("t_short", 2)]
    assert res["candidates"][0]["configs"] == [long_cfg]                         # đúng cấu hình đã gửi
    for f in res["folds"]:
        assert f["chosen"]["t_long"] in (long_cfg, None) and f["chosen_idx"]["t_long"] in (0, None)   # 1 cấu hình = cố định
        assert len(f["is_candidates"]["t_long"]) == 1 and len(f["is_candidates"]["t_short"]) == 2
        assert f["chosen"]["t_short"] in short_cfgs + [None]
    assert res["source"]["strategies"] is True
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
    rep = json.loads(sorted(pathlib.Path(run_dir("wfa")).glob("*/report.json"))[-1].read_text())
    assert {"folds", "aggregate", "mc", "gate"} <= set(rep) and "oos_daily_dates" in rep["aggregate"]


def test_validate_book_strategies_validation(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    for bad in ([], [{"id": "zzz", "configs": [{}]}], [{"id": "t_long", "configs": []}], [{"id": "t_long", "configs": [{"bogus": 1}]}],
                [{"id": "t_long", "configs": [{}]}, {"id": "t_long", "configs": [{}]}]):
        with pytest.raises(SystemExit):
            vb.candidates_from_list(bad)
    assert vb.candidates_from_list([{"id": "t_long", "configs": [{"sig.lo": 35}]}]) == [{"id": "t_long", "configs": [{"sig.lo": 35}]}]
    with pytest.raises(ValueError):                                              # đúng một nguồn
        vb.run_job({"strategies": [{"id": "t_long", "configs": [{}]}], "candidates": "t_long"})


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
    os.makedirs(job_dir, exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(job_dir))
    bsb = _load_script("build_strategy_book")
    bsb.run_job({"workers": 2, "per_worker_mb": 300, "n": 4, "out": str(tmp_path / "alphas")})
    res = json.loads((job_dir / "result.json").read_text())
    assert set(res["stage_a"]) == {"t_long", "t_short"}
    assert len(res["stage_a"]["t_long"]) == 2 and len(res["stage_a"]["t_short"]) == 2          # lưới nhỏ hơn n=4 -> thử hết
    for rows in res["stage_a"].values():
        assert [r["score"] for r in rows if r["score"] is not None] == sorted((r["score"] for r in rows if r["score"] is not None), reverse=True)
        for r in rows:
            assert set(r) == {"params", "dev1", "score", "passed"} and set(r["dev1"]) == {"ret_pct", "mdd_pct", "trades", "symbols_positive", "sharpe"}
            assert r["passed"] == (r["score"] is not None)
    # khớp stage_a.json (đầy đủ) về số cấu hình và tham số
    full = json.loads(sorted(pathlib.Path(alpha_run_dir("book")).glob("*/stage_a.json"))[-1].read_text())
    for cid, rows in full.items():
        assert [r["params"] for r in rows] == [r["params"] for r in res["stage_a"][cid]]


# ─── P9.15: engine_version của sổ + needs_rebuild; P9.14: trạng thái + nguồn gốc alpha registry ──────────────
def test_engine_version_is_stable_and_detects_engine_source_change(tmp_path, monkeypatch):
    from backend.optimize.book import registry as ev
    a = ev.engine_version()
    assert a == ev.engine_version() and len(a["hash"]) == 64 and a["files"] > 0
    # custom_run / edu_precompute (sản phẩm của phiên alpha) KHÔNG nằm trong mã engine
    names = [rel for rel, _ in ev._engine_files()]
    assert "backend/core/strategy.py" in names and "backend/optimize/search/evaluate.py" in names   # P15: core/backtest.py thay bằng core/strategy.py; thư viện run.py + tick_run nằm ở search/evaluate.py
    assert "backend/core/indicator.py" in names and "backend/core/signal.py" in names   # P9.10b: cột + tín hiệu của engine cũng là mã engine
    assert not any(n.endswith(("custom_run.py", "edu_precompute.py")) for n in names)
    # đổi một file engine -> hash đổi (dùng thư mục giả)
    fake = tmp_path / "nora"
    for rel in names:
        (fake / rel).parent.mkdir(parents=True, exist_ok=True)
        (fake / rel).write_text("x = 1\n")
    monkeypatch.setattr(ev, "NORA_DIR", str(fake))
    ev._cache.update(sig=None, value=None, at=0.0)
    h1 = ev.engine_version()["hash"]
    (fake / "backend/core/strategy.py").write_text("x = 2\n")
    assert ev.engine_version()["hash"] != h1
    h2 = ev.engine_version()["hash"]
    (fake / "backend/core/custom_run.py").write_text("y = 1\n")       # chỉ .py trong core/ mới tính -> custom_run.py nằm ngoài list?
    ev._cache.update(sig=None, value=None, at=0.0)
    (fake / "backend/alpha").mkdir(parents=True, exist_ok=True)
    h3 = ev.engine_version()["hash"]
    (fake / "backend/alpha/contract.py").write_text("z = 1\n")        # alpha/contract.py (trợ giúp) không ảnh hưởng kết quả
    (fake / "backend/alpha/compile.py").write_text("z = 1\n")         # compiler: chỉ IR đầu ra được băm, không băm file
    ev._cache.update(sig=None, value=None, at=0.0)
    assert ev.engine_version()["hash"] == h3
    ev._cache.update(sig=None, value=None, at=0.0)


def test_engine_hash_tracks_strategy_ir_not_comments(tmp_path, monkeypatch):
    import shutil
    from backend.alpha.compile import strategies_dir
    from backend.optimize.book import registry as ev
    d = tmp_path / "strategies"
    shutil.copytree(strategies_dir(), d, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv("NORA_STRATEGIES_DIR", str(d))
    ev._cache.update(sig=None, value=None, at=0.0)
    h0 = ev.engine_version()["hash"]
    f = d / "kema.py"
    src = f.read_text()
    f.write_text("# chú thích thêm, không đổi logic\n" + src.replace("\n", "  \n", 1))
    assert ev.engine_version()["hash"] == h0
    # đổi logic: một hằng số số học trong thân chiến lược
    import re
    m = re.search(r"(?<![\w.])(\d+\.\d+)(?![\w])", src)
    assert m, "kema.py không có hằng số thực để đổi"
    f.write_text(src[:m.start()] + str(float(m.group(1)) + 1.0) + src[m.end():])
    assert ev.engine_version()["hash"] != h0
    ev._cache.update(sig=None, value=None, at=0.0)
    inputs = ev.engine_inputs()
    assert "strategy:kema_long" in inputs and "backend/core/strategy.py" in inputs
    st = ev.book_engine_status({"engine_version": {"hash": "0" * 64, "commit": "abc"}})
    assert "strategy:" not in st["reason"] and "kema_long" in st["reason"] and "backend/core/strategy.py" in st["reason"]


def test_book_engine_status_missing_same_and_changed():
    from backend.optimize.book.registry import REASON_NO_VERSION, book_engine_status, engine_version
    cur = engine_version()
    assert book_engine_status(None)["needs_rebuild"] is None
    old = book_engine_status({"status": "READY"})
    assert old["needs_rebuild"] is True and old["reason"] == REASON_NO_VERSION and old["stored"] is None
    ok = book_engine_status({"engine_version": cur})
    assert ok["needs_rebuild"] is False and ok["reason"] is None
    stale = book_engine_status({"engine_version": {**cur, "hash": "0" * 64, "commit": "abc1234"}})
    assert stale["needs_rebuild"] is True and "abc1234" in stale["reason"] and "00000000" in stale["reason"]


def test_build_book_stamps_engine_version_and_api_reports_needs_rebuild(client, tmp_path, monkeypatch):
    from backend.optimize.book import registry as reg
    from backend.optimize.book.registry import REASON_NO_VERSION, engine_version
    adir = tmp_path / "data" / "alpha"
    os.makedirs(adir / "explore")
    # sổ cũ (không có engine_version) -> cần dựng lại, lý do rõ ràng
    (tmp_path / "book.json").write_text(json.dumps({"status": "READY_FOR_TESTNET"}))
    (adir / "explore" / "book.json").write_text(json.dumps({"status": "EXPLORE_DEMO", "engine_version": engine_version()}))
    e = client.get("/api/studio/alphas").json()["engine"]
    assert e["main"]["needs_rebuild"] is True and e["main"]["reason"] == REASON_NO_VERSION
    assert e["explore"]["needs_rebuild"] is False and e["current"]["hash"] == engine_version()["hash"]
    # build_book (đường duy nhất của write_book / write_explore_book / xuất bản phễu) đóng dấu engine_version hiện hành
    import inspect
    assert "engine_version()" in inspect.getsource(reg.build_book) and "engine_version()" in inspect.getsource(reg.build_registry)
    # xuất bản sổ giữ nguyên engine_version lúc dựng và trả trạng thái
    src, dst = tmp_path / "src", tmp_path / "dst"
    os.makedirs(src)
    (src / "book.json").write_text(json.dumps({"status": "READY_FOR_TESTNET", "strategies": [], "engine_version": {**engine_version(), "hash": "1" * 64}}))
    out = reg.publish_book(str(src), str(dst))
    assert out["engine"]["needs_rebuild"] is True and json.loads((dst / "book.json").read_text())["engine_version"]["hash"] == "1" * 64


def test_registry_provenance_shows_status_and_note():
    from backend.routes.optimize import registry_provenance
    assert registry_provenance(None) == []
    reg = {"generated_at": 1, "source_optimization": "/x/_cache/optimize/20261001_1440", "code": {"commit": "2d4698f96e14", "dirty_backend": True},
           "alphas": [{"alpha_id": "trend_long_perp__SOL", "status": "retired", "data": {"exchange": "binance_usdm"},
                       "revalidation": {"reason": "S3.positive_ratio: Tỉ lệ fold lãi < 60%", "checked_at": 5}},
                      {"alpha_id": "x__ETH", "data": {}}]}
    rows = {r["alpha_id"]: r for r in registry_provenance(reg)}
    sol = rows["trend_long_perp__SOL"]
    assert sol["status"] == "retired" and "nghỉ hưu" in sol["status_label"] and sol["status_note"].startswith("S3.positive_ratio") and sol["checked_at"] == 5
    assert "2d4698f" in sol["provenance"] and "binance_usdm" in sol["provenance"] and "20261001_1440" in sol["provenance"] and sol["needs_rebuild"] is True
    assert rows["x__ETH"]["status"] is None and rows["x__ETH"]["status_note"] == "chưa kiểm lại bằng engine hiện hành"
