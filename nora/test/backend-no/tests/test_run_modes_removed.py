# Đã chuyển khỏi test/ (P17 T1-B5c): presets từ lần tối ưu stage A, publish, space_for/validate_alpha và API phễu đã gỡ cùng kho tối ưu; bản gốc ở tag pre-p17-research.
"""Chế độ Cơ bản / Nâng cao: cây tham số hoá, params_schema, preset, validate 422, custom_gates, API.

Không chạy job thật: Popen bị thay bằng bản giả ghi lại lệnh (như test_book_api).
"""
import json
import os
import time
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.jobs import runner as batch_jobs
from backend.routes import process as process_routes
from job_modules import launched
from backend.routes import book as optimize
from backend.routes import alpha
from backend.analys.param import POSITION_KEYS
from backend import strategies as pr
from backend.routes import process as process_routes
from backend.analys.param import FRAMES, collect_placeholders, collect_string_placeholders, resolve_placeholders
from backend.analys.param import BASE_POSITION, materialize, resolve_position_auto, schema_defaults
from backend.strategies import BY_ID, CANDIDATES
from legacy_candidates import LEGACY
from backend.alpha.compile import calc, cond, cross_over, cross_under, f, tree_p


def test_presets_priority_book_then_latest_stage_a_then_defaults(tmp_path):
    runs = tmp_path / "book"
    # run cũ: có trend_long tốt (điểm 2), reversion_long (điểm 1)
    _run(runs, "20260101_000000", {"trend_long": [_row({"sig.adx_min": 20, "stop_loss_rate": 1.5}, 2.0)],
                                   "reversion_long": [_row({"sig.rsi_lo": 30}, 1.0)]})
    # run mới: trend_long top-1 (điểm 5) trước top-2 (điểm 7: phải chọn theo ĐIỂM, không theo thứ tự); breakout_4h_long cũng có (nhưng sổ thắng)
    _run(runs, "20260102_000000", {"trend_long": [_row({"sig.adx_min": 25, "stop_loss_rate": 3.5}, 5.0), _row({"sig.adx_min": 30}, 7.0), _row({}, NEG)],
                                   "breakout_4h_long": [_row({"stop_loss_rate": 1.5}, 3.0)],
                                   "trend_short": [_row({"stop_loss_rate": 1.5}, NEG)],               # không qua cổng -> bỏ
                                   "momentum_long": [_row({"sig.roc_min": 5}, None)]},                # score null (stage_a_rows) -> bỏ
         {"trend_long": {"dev1_tried": 24, "accepted": False, "stability": "0/2",
                         "dev1_top": [{"params": {"sig.adx_min": 30}, "dev2_pass": False, "dev2_extreme": {"ret_pct": -3.0}}]}})
    book = {"generated_at": 1790856748686, "risk_per_trade_pct": 0.5, "strategies": [
        {"id": "breakout_4h_long", "params": {"stop_loss_rate": 3.0, "timeout": 10080, "trailing_activation_pct": 1.0, "trailing_stop": 3.0, "bogus": 1},
         "evidence": {"accepted": True, "stability": "2/3", "dev1_tried": 24, "dev1_top": [{"dev1": {"ret_pct": 19.5, "daily": [1]}}]}}]}
    doc = pr.build_presets(book=book, runs_dir=str(runs))
    P = doc["presets"]
    assert set(P) == set(BY_ID)
    # 1. sổ thắng stage A; khoá lạ bị bỏ; thiếu khoá thì mặc định schema
    b = P["breakout_4h_long"]
    assert b["source_kind"] == "book" and b["source"] == "book.json (sổ đã build 01/10)" and b["params"]["stop_loss_rate"] == 3.0
    assert "bogus" not in b["params"] and b["params"]["sig.ema_fast"] == 50 and b["evidence"]["dev1"] == {"ret_pct": 19.5}
    assert b["timeframe"] == "1m" and b["evidence"]["timeframe"] == "1m"
    # 2. run mới nhất có cấu hình qua cổng; chọn điểm cao nhất (7.0), kèm dev2
    t = P["trend_long"]
    assert "build 20260102_000000 stage A" in t["source"] and t["params"]["sig.adx_min"] == 30
    assert t["evidence"]["score"] == 7.0 and t["evidence"]["accepted"] is False and t["evidence"]["dev2_extreme"] == {"ret_pct": -3.0}
    assert t["timeframe"] == "1m" and t["evidence"]["timeframe"] == "1m"
    # run cũ chỉ dùng khi run mới không có cấu hình qua cổng
    assert "build 20260101_000000 stage A" in P["reversion_long"]["source"] and P["reversion_long"]["params"]["sig.rsi_lo"] == 30
    # 3. còn lại: mặc định schema, timeframe=None
    for cid in ("trend_short", "momentum_long", "reversion_short", "breakout_4h_short"):
        assert P[cid]["source"] == pr.SOURCE_DEFAULT and P[cid]["source_kind"] == "default" and P[cid]["evidence"] is None
        assert P[cid]["params"] == schema_defaults(BY_ID[cid])
        assert P[cid]["timeframe"] is None
    for cid, preset in P.items():                       # params luôn đầy đủ và hợp lệ theo schema
        assert set(preset["params"]) == set(BY_ID[cid]["params_schema"])
        _, errs = process_routes.validate_params(BY_ID[cid], preset["params"], preset["params"])
        assert not errs, (cid, errs)


def test_presets_new_verified_run_beats_old_book_unverified_does_not(tmp_path):
    book = {"generated_at": 1790856748686, "timeframe": "15m", "strategies": [
        {"id": "breakout_4h_long", "params": {"stop_loss_rate": 3.0}, "evidence": {}}]}
    # run mới hơn sổ nhưng top-K không qua dev2 -> sổ (đã qua dev2) vẫn thắng
    _run(tmp_path / "a", "20261003_120000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]})
    b = pr.build_presets(book=book, runs_dir=str(tmp_path / "a"))["presets"]["breakout_4h_long"]
    assert b["source_kind"] == "book" and b["timeframe"] == "15m"
    # run mới hơn sổ, có cấu hình qua dev2 -> stage A thắng
    _run(tmp_path / "b", "20261003_120000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]},
         {"breakout_4h_long": {"dev1_top": [{"params": {"stop_loss_rate": 2.0}, "dev2_pass": True}]}})
    b = pr.build_presets(book=book, runs_dir=str(tmp_path / "b"))["presets"]["breakout_4h_long"]
    assert b["source_kind"] == "stage_a" and "20261003_120000" in b["source"] and b["params"]["stop_loss_rate"] == 2.0
    assert b["evidence"]["dev2_verified"] is True and b["timeframe"] == "1m"
    # run cũ hơn sổ, dù qua dev2 -> sổ thắng (cùng mức kiểm chứng, sổ mới hơn)
    _run(tmp_path / "c", "20260101_000000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]},
         {"breakout_4h_long": {"dev1_top": [{"params": {"stop_loss_rate": 2.0}, "dev2_pass": True}]}})
    assert pr.build_presets(book=book, runs_dir=str(tmp_path / "c"))["presets"]["breakout_4h_long"]["source_kind"] == "book"


def test_presets_stage_a_picks_robust_plateau_on_dev1_only(tmp_path):
    # đỉnh nhọn adx=30 (điểm 9, hai lân cận trượt cổng) vs vùng phẳng adx=20..25 (điểm 4, 4) -> chọn vùng phẳng; dev2 KHÔNG ảnh hưởng lựa chọn
    rows = [_row({"sig.adx_min": 15}, NEG), _row({"sig.adx_min": 20}, 4.0), _row({"sig.adx_min": 25}, 4.0),
            _row({"sig.adx_min": 30}, 9.0), _row({"sig.adx_min": 35}, NEG)]
    rob = pr.robust_scores(rows)
    assert rob[1] == pytest.approx((0 + 4 + 4) / 3) and rob[2] == pytest.approx((4 + 4 + 9) / 3) and rob[3] == pytest.approx((4 + 9 + 0) / 3)
    _run(tmp_path, "20261003_000000", {"trend_long": rows},
         {"trend_long": {"dev1_top": [{"params": {"sig.adx_min": 30}, "dev2_pass": True}]}})       # đỉnh qua dev2 vẫn không được chọn
    t = pr.build_presets(book=None, runs_dir=str(tmp_path), use_book_file=False)["presets"]["trend_long"]
    assert t["params"]["sig.adx_min"] == 25 and t["evidence"]["score"] == 4.0
    assert t["evidence"]["robust_score"] == pytest.approx(17 / 3, abs=1e-4) and t["evidence"]["dev2_verified"] is None
    assert "bền vững dev1" in t["source"]


def test_presets_write_load_roundtrip_and_fallbacks(tmp_path):
    doc = pr.build_presets(book=None, runs_dir=str(tmp_path / "none"), use_book_file=False)
    path = tmp_path / "presets.json"
    pr.write_presets(doc, str(path))
    assert pr.load_presets(str(path)) == {k: {**v} for k, v in doc["presets"].items()}
    assert pr.load_presets(str(tmp_path / "missing.json"))["trend_long"]["source"] == pr.SOURCE_DEFAULT
    path.write_text("{hỏng")
    assert pr.load_presets(str(path))["trend_long"]["source_kind"] == "default"
    # file có khoá lạ / thiếu khoá -> chuẩn hoá theo schema hiện hành
    path.write_text(json.dumps({"presets": {"trend_long": {"params": {"stop_loss_rate": 3.0, "zzz": 1, "sig.trend_tf": "9h"}, "source": "x"}}}))
    got = pr.load_presets(str(path))["trend_long"]
    assert got["params"]["stop_loss_rate"] == 3.0 and "zzz" not in got["params"] and got["params"]["sig.trend_tf"] == "1h" and got["source"] == "x"


def test_publish_refuses_custom_gates_job(client, tmp_path):
    jid, d = _stamped_job("book_build", name="20260101_000001_aaaaaa", custom_gates=True, mode="advanced", promotable=False)
    os.makedirs(os.path.join(d, "alphas"))
    json.dump({"status": "x"}, open(os.path.join(d, "alphas", "book.json"), "w"))
    r = client.post("/api/studio/book/publish", json={"job_id": jid})
    assert r.status_code == 409 and "custom_gates" in r.json()["detail"] and "KHÔNG" in r.json()["detail"]
    assert not (tmp_path / "alphas").exists()                                  # không ghi gì ra data/alphas


def test_presets_evidence_bools_are_real_bools(tmp_path):
    run = tmp_path / "20260101_000000"
    run.mkdir()
    cand = BY_ID["trend_long"]
    params = {k: v[0] for k, v in cand["space"].items()}
    (run / "stage_a.json").write_text(json.dumps({"trend_long": [{"score": 1.0, "params": params, "dev1": {}}]}))
    (run / "report.json").write_text(json.dumps({"candidates": {"trend_long": {"accepted": "False", "dev1_top": [{"params": params, "dev2_pass": "True"}]}}}))
    ev = pr.from_build_runs(str(tmp_path), [cand])["trend_long"]["evidence"]
    assert ev["accepted"] is False and ev["dev2_pass"] is True
    out = tmp_path / "p.json"
    pr.write_presets({"x": np.bool_(True)}, str(out))
    assert json.loads(out.read_text()) == {"x": True}


def test_timeframe_lifts_frames_and_blocks_incompatible_strategies():
    """Khung chạy: lựa chọn khung < khung chạy được nâng lên (nếu là lựa chọn hợp lệ) hoặc bỏ; chiến lược không còn khung hợp lệ bị báo."""
    from backend.optimize.search import generate as gen
    by = BY_ID
    sp = gen.space_for(by["trend_long"], "schema", "1h")
    assert set(sp["sig.entry_tf"]) == {"1h"} and set(sp["sig.trend_tf"]) == {"1h", "4h", "24h"}
    grid = gen.space_for(by["reversion_long"], "grid", "15m")
    assert grid["sig.entry_tf"] == ["15m"]                                     # mặc định 5m -> 15m
    p = next(gen.iter_params(grid, 1, 1))
    assert gen.validate_alpha(by["reversion_long"], p, "grid", "15m") is None
    assert gen.validate_alpha(by["reversion_long"], {**p, "sig.entry_tf": "5m"}, "grid", "15m")
    bad = gen.incompatible([by["trend_long"], by["keltner_trend_long"]], "schema", "4h")
    assert "trend_long" in bad and "keltner_trend_long" not in bad


def test_api_rejects_strategy_incompatible_with_timeframe():
    from fastapi.testclient import TestClient
    from backend.main import app
    r = TestClient(app).post("/api/studio/funnel/runs", json={"strategies": ["trend_long"], "n_per_strategy": 5, "timeframe": "4h"})
    assert r.status_code == 422 and "khung 4h" in r.text
