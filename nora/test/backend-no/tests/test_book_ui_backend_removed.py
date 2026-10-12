# Đã chuyển khỏi test/ (P17 T1-B5c): endpoint kho alpha/registry, kết quả dựng sổ (stage A) và registry_provenance đã gỡ; bản gốc ở tag pre-p17-research.
"""Phần backend của docs/ui_contract.md: catalog (default_params/universe/windows), /alphas, nhãn + lọc job, WFA cấu hình chọn tay,
stage_a trong result của build_strategy_book, oos_daily_dates của WFA."""
import pathlib
from backend.models.storage import alpha_run_dir, run_dir
import json
import os
import threading
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.routes import book as optimize
from backend.jobs import runner as batch_jobs
from job_modules import launched
from test_portfolio_wfa import DAY, START, T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)


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


def test_build_book_stamps_engine_version_and_api_reports_needs_rebuild(client, tmp_path, monkeypatch):
    from backend import strategies as reg
    from backend.strategies import REASON_NO_VERSION, engine_version
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
    from backend.routes.book import registry_provenance
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
