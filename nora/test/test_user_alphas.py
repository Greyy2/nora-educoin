"""Unit test cho C1 — Kho Alpha người dùng và catalog.

Kiểm thử:
1. Lưu/đọc alpha người dùng từ kết quả job
2. Chống giả mạo: code hash lệch thì từ chối (HTTP 409)
3. Không ghi đè registry.json hay ảnh hưởng chiến lược lõi
4. Checklist 5 tiêu chí tính toán chính xác
5. catalog() hiển thị nhóm Alpha người dùng cùng định dạng thẻ
6. Vòng đời: SAVED -> CANDIDATE -> ARCHIVED
"""
import json
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import alpha
from backend.alpha import strategies as strategy_doc, strategies as user_alphas
from backend.alpha.compile import compile_code

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data


def _make_mock_job(tmp_path, code, job_id="job_test_123", finish=True):
    prog = compile_code(code, register=False)
    job_dir = tmp_path / "_cache" / "api_jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "program_hash": prog.code_hash,
        "config": {
            "symbols": ["BTC"],
            "start": "2020-01-02",
            "end": "2024-12-31",
            "train_ratio": 0.7,
            "initial_capital": 100000.0,
            "timeframe": "24h",
            "program": {"name": prog.name, "legs": ["LONG"]},
        },
        "metrics": {
            "simulate": {"sharpe": 1.5, "ret_pct": 120.0, "mdd_pct": 25.0, "trades": 35},
            "test": {"sharpe": 1.2, "ret_pct": 40.0, "mdd_pct": 18.0},
        },
        "series": {
            "times": [1000, 2000, 3000],
            "equity": [100000.0, 150000.0, 220000.0],
        },
        "trades": [{"symbol": "BTC", "pnl": 100.0}] * 35,
        "insights": [{"id": "tp_dominant_exit", "severity": "good"}],
        "diagnostics": {},
        "final_equity": 220000.0,
    }

    (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id,
        "state": "done" if finish else "running",
        "created": 1000,
    }), encoding="utf-8")
    return job_id, result


def test_user_alpha_lifecycle_and_security(tmp_path, monkeypatch):
    code = """
class MyAlgo(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 20)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), 1.0)
        self.set_positions(self.op.crossed_below(self.data.pv_close, ema), 0.0)
"""
    job_id, res = _make_mock_job(tmp_path, code, "job_alpha_01")
    monkeypatch.setenv("NORA_DATA_DIR", str(tmp_path))
    user_alphas_dir = str(tmp_path / "alphas")

    # 1. Lưu hợp lệ
    # Mock batch.status
    from backend.jobs import runner as batch
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res} if jid == job_id else None)

    rec, act = user_alphas.save_user_alpha(job_id, code, "Alpha Thử Nghiệm", note="Ghi chú test", base_dir=user_alphas_dir)
    assert act == "created"
    assert rec["name"] == "Alpha Thử Nghiệm"
    assert rec["status"] == "SAVED"
    alpha_id = rec["id"]

    # Đảm bảo file được tạo trong data/alpha/user/<alpha_id>.json và KHÔNG chạm vào registry.json
    assert os.path.isfile(os.path.join(user_alphas_dir, "user", f"{alpha_id}.json"))
    assert not os.path.exists(os.path.join(user_alphas_dir, "registry.json"))

    # 2. Đọc lại
    got = user_alphas.get_user_alpha(alpha_id, base_dir=user_alphas_dir)
    assert got is not None
    assert got["id"] == alpha_id

    # 3. Chống giả mạo: code lệch hash -> từ chối
    code_tampered = code.replace("20", "50")
    with pytest.raises(ValueError, match="Mã băm chương trình không khớp"):
        user_alphas.save_user_alpha(job_id, code_tampered, "Alpha Tampered", base_dir=user_alphas_dir)

    # 4. Cập nhật trạng thái
    assert user_alphas.update_user_alpha_status(alpha_id, "CANDIDATE", base_dir=user_alphas_dir)
    assert user_alphas.get_user_alpha(alpha_id, base_dir=user_alphas_dir)["status"] == "CANDIDATE"

    # 5. Lưu trữ (archive)
    assert user_alphas.update_user_alpha_status(alpha_id, "ARCHIVED", base_dir=user_alphas_dir)
    assert user_alphas.get_user_alpha(alpha_id, base_dir=user_alphas_dir)["status"] == "ARCHIVED"


def test_user_alpha_in_catalog(tmp_path, monkeypatch):
    code = """
class MyAlgo2(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 30)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), 1.0)
"""
    job_id, res = _make_mock_job(tmp_path, code, "job_alpha_02")
    user_alphas_dir = str(tmp_path / "alphas")

    from backend.jobs import runner as batch
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res})

    rec, _ = user_alphas.save_user_alpha(job_id, code, "Alpha Đỉnh Cao", base_dir=user_alphas_dir)
    alpha_id = rec["id"]

    # Catalog đọc base_dir và hiển thị cả lõi + alpha người dùng
    cat = strategy_doc.catalog(alphas_dir=user_alphas_dir)
    nora_src = next(s for s in cat["sources"] if s["key"] == "nora")
    user_cards = [s for s in nora_src["strategies"] if s.get("is_user_alpha")]
    assert len(user_cards) == 1
    uc = user_cards[0]
    assert uc["name"] == "Alpha Đỉnh Cao"
    assert uc["alpha_id"] == alpha_id
    assert uc["kind"] == "Alpha người dùng"
    assert len(uc["plain"]) > 0


def test_user_alpha_api_router(tmp_path, monkeypatch):
    code = """
class ApiAlgo(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 20)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), 1.0)
"""
    job_id, res = _make_mock_job(tmp_path, code, "job_alpha_03")

    from backend.jobs import runner as batch
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res} if jid == job_id else None)
    monkeypatch.setattr(user_alphas, "get_user_alphas_dir", lambda base=None: str(tmp_path / "alphas" / "user"))

    app = FastAPI()
    app.include_router(alpha.alphas_router)
    client = TestClient(app)

    # Đẩy hợp lệ
    r = client.post("/api/studio/alphas/user", json={"job_id": job_id, "code": code, "name": "API Alpha"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    aid = j["alpha_id"]

    # Đẩy với code sửa -> 409
    r_bad = client.post("/api/studio/alphas/user", json={"job_id": job_id, "code": code.replace("20", "100"), "name": "Fake Alpha"})
    assert r_bad.status_code == 409

    # Liệt kê
    r_list = client.get("/api/studio/alphas/user")
    assert r_list.status_code == 200
    assert any(x["id"] == aid for x in r_list.json())

    # Archive
    r_arc = client.post(f"/api/studio/alphas/user/{aid}/archive")
    assert r_arc.status_code == 200
    assert r_arc.json()["status"] == "ARCHIVED"


def test_beta_driven_id_is_single_source_in_backend_and_ui_has_no_checklist_logic():
    import re
    from backend.metrics import charts as insights
    assert insights.BETA_DRIVEN_ID == "beta_driven" and insights.BETA_DRIVEN_ID in {r.id for r in insights.RULES}
    ins = [{"id": insights.BETA_DRIVEN_ID, "severity": "warning", "message_vi": "x", "evidence": {"beta": 1}}]
    res = {"trades": [{}] * 30, "metrics": {"simulate": {"trades": 30, "mdd_pct": 10.0}, "test": {"sharpe": 1.0}}, "insights": ins}
    items = {i["id"]: i for i in user_alphas.evaluate_checklist(res)["items"]}
    assert items["not_pure_beta"]["state"] == "fail" and items["not_pure_beta"]["passed"] is False and insights.BETA_DRIVEN_ID in items["not_pure_beta"]["required"]
    # giao diện chỉ hiển thị checklist của backend: không còn chuỗi id insight / phép tính tiêu chí trong modal lưu
    src = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "components", "alpha", "studio")
    if not os.path.exists(src):
        src = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "components", "studio")
    assert not os.path.exists(os.path.join(src, "PushToAlphaModal.jsx"))
    jsx = open(os.path.join(src, "SaveStrategyModal.jsx"), encoding="utf-8").read()
    assert insights.BETA_DRIVEN_ID not in jsx and not re.search(r"hasBetaDriven|testSharpe\s*>|mddPct\s*<|nTrades\s*>=", jsx)


# ─── checklist: thiếu dữ liệu ≠ đạt / trượt ──────────────────────────────────

def test_checklist_missing_metrics_are_missing_not_passed_or_failed():
    cl = user_alphas.evaluate_checklist({"metrics": {"simulate": {}, "test": {"sharpe": None}}})
    st = {i["id"]: i for i in cl["items"]}
    for k in ("trades_ge_20", "test_sharpe_positive", "mdd_under_50", "not_pure_beta"):
        assert st[k]["state"] == "missing" and st[k]["passed"] is None and st[k]["value"] == "không có dữ liệu", k
    assert st["has_test_stage"]["state"] == "pass"           # có khối test (dù rỗng chỉ số) -> khối tồn tại
    assert cl["all_passed"] is False and cl["n_missing"] == 4
    empty = user_alphas.evaluate_checklist({})
    assert {i["id"]: i["state"] for i in empty["items"]}["has_test_stage"] == "fail" and empty["all_passed"] is False


def test_checklist_units_come_from_explicit_fields_and_zero_is_a_real_value():
    nora = user_alphas.evaluate_checklist({"trades": [{}] * 20, "insights": [], "metrics": {"simulate": {"mdd_pct": 49.9}, "test": {"sharpe": 0.0}}})
    st = {i["id"]: i for i in nora["items"]}
    assert st["trades_ge_20"]["state"] == "pass" and st["mdd_under_50"]["state"] == "pass" and st["mdd_under_50"]["value"] == "49.9%"
    assert st["test_sharpe_positive"]["state"] == "fail" and st["test_sharpe_positive"]["value"] == "0.00"      # 0 thật không bị thay bằng fallback
    bad = user_alphas.evaluate_checklist({"trades": [], "insights": [], "metrics": {"simulate": {"mdd_pct": -55.0}, "test": {"sharpe": 0.4}}})
    sb = {i["id"]: i for i in bad["items"]}
    assert sb["mdd_under_50"]["state"] == "fail" and sb["mdd_under_50"]["value"] == "55.0%"                      # mdd_pct đã là %, lấy trị tuyệt đối
    assert sb["trades_ge_20"]["state"] == "fail" and sb["test_sharpe_positive"]["state"] == "pass"


# ─── Lưu: chỉ từ kết quả job, ảnh chụp đầy đủ, lưu lại = cập nhật ───────────

CODE_SAVE = """
class SnapAlgo(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 20)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), 1.0)
        self.set_positions(self.op.crossed_below(self.data.pv_close, ema), 0.0)
"""
SNAPSHOT_KEYS = ("config", "data", "metrics", "yearly", "series", "trades", "positions_open", "by_symbol", "warnings", "diagnostics", "insights", "program_hash", "final_equity")


def _full_result(tmp_path, code, job_id):
    job_id, res = _make_mock_job(tmp_path, code, job_id)
    res.update({
        "data": {"source": "okx", "sha256_1m": {"BTC@perp": "abc123"}},
        "yearly": [{"year": 2021, "stage": "train", "cagr": 0.5}],
        "series": {"times": [1, 2, 3], "equity": [1.0, 2.0, 3.0], "benchmark": {"times": [1, 2, 3], "equity": [1.0, 1.5, 2.0], "label": "Luôn long"},
                   "stages": {"all": {"times": [1, 2, 3], "equity": [1.0, 2.0, 3.0], "benchmark": {"equity": [1.0, 1.5, 2.0]}}, "train": None, "test": None}},
        "positions_open": [], "by_symbol": [{"symbol": "BTC", "pnl_usd": 1.0}], "warnings": ["w"],
        "diagnostics": {"pnl_structure": {"win_rate": 55.0}}, "insights": [{"id": "high_win_rate", "severity": "good", "evidence": {"win_rate": 55.0}}],
    })
    return job_id, res


def test_save_stores_full_snapshot_independent_of_job_dir_and_resave_updates(tmp_path, monkeypatch):
    import shutil
    from backend.jobs import runner as batch
    job_id, res = _full_result(tmp_path, CODE_SAVE, "job_snap_01")
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res, "created": 111.0, "finished": 222.0} if jid == job_id else None)
    base = str(tmp_path / "alphas")
    rec, act = user_alphas.save_user_alpha(job_id, CODE_SAVE, "Snap", note="n", base_dir=base)
    assert act == "created"
    shutil.rmtree(tmp_path / "_cache")                                   # thư mục job biến mất: bản ghi vẫn đủ
    monkeypatch.setattr(batch, "status", lambda jid: None)
    got = user_alphas.get_user_alpha(rec["id"], base_dir=base)
    assert got["code"] == CODE_SAVE and got["program_hash"] == res["program_hash"] and "profile" not in got["config"] and "profile" not in got
    for k in SNAPSHOT_KEYS:
        assert k in got["result"], k
    assert got["result"]["series"]["benchmark"]["equity"] == [1.0, 1.5, 2.0] and got["result"]["series"]["stages"]["all"]["benchmark"]["equity"] == [1.0, 1.5, 2.0]
    assert len(got["result"]["trades"]) == 35 and got["result"]["insights"][0]["evidence"] == {"win_rate": 55.0}
    ev = got["evidence"]
    assert ev["job_id"] == job_id and ev["program_hash"] == res["program_hash"] and ev["data_sha256_1m"] == {"BTC@perp": "abc123"} and ev["data_source"] == "okx"
    assert "git_commit" in ev and ev["job_finished"] == 222.0
    assert got["checklist"]["items"] and got["result"]["checklist"] == got["checklist"] and got["explain"] and got["explain"].get("rules")
    # danh sách gọn: không kèm ảnh chụp; chi tiết có đủ
    lst = user_alphas.list_user_alphas(base_dir=base)
    assert len(lst) == 1 and "result" not in lst[0] and "explain" not in lst[0] and lst[0]["has_result"] is True
    # lưu lại cùng chương trình -> bị từ chối (409 ở API), không nhân bản
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res} if jid == "job_snap_02" else None)
    with pytest.raises(ValueError, match="đã được lưu"):
        user_alphas.save_user_alpha("job_snap_02", CODE_SAVE, "Snap v2", base_dir=base)
    assert len([f for f in os.listdir(os.path.join(base, "user")) if f.endswith(".json")]) == 1


def test_save_rejects_unfinished_missing_or_incomplete_results(tmp_path, monkeypatch):
    from backend.jobs import runner as batch
    _, res = _full_result(tmp_path, CODE_SAVE, "job_bad_01")
    base = str(tmp_path / "alphas")
    cases = {"j_run": {"status": "running"}, "j_none": None, "j_empty": {"status": "done", "result": {}},
             "j_nometrics": {"status": "done", "result": {**res, "metrics": {}}}}
    monkeypatch.setattr(batch, "status", lambda jid: cases.get(jid))
    for jid in cases:
        with pytest.raises(ValueError):
            user_alphas.save_user_alpha(jid, CODE_SAVE, "x", base_dir=base)
    assert not os.path.isdir(os.path.join(base, "user")) or not os.listdir(os.path.join(base, "user"))


def test_api_ignores_client_supplied_result_and_serves_stored_detail(tmp_path, monkeypatch):
    from backend.jobs import runner as batch
    job_id, res = _full_result(tmp_path, CODE_SAVE, "job_api_09")
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res} if jid == job_id else None)
    monkeypatch.setattr(user_alphas, "get_user_alphas_dir", lambda base=None: str(tmp_path / "alphas" / "user"))
    app = FastAPI()
    app.include_router(alpha.alphas_router)
    client = TestClient(app)
    fake = {**res, "metrics": {"simulate": {"sharpe": 99.0}}}
    r = client.post("/api/studio/alphas/user", json={"job_id": job_id, "code": CODE_SAVE, "name": "A", "result": fake, "metrics": fake["metrics"]})
    assert r.status_code == 200 and r.json()["record"]["metrics"] == res["metrics"] and r.json()["checklist"]["items"]
    aid = r.json()["alpha_id"]
    det = client.get(f"/api/studio/alphas/user/{aid}").json()
    assert det["result"]["metrics"] == res["metrics"] and det["result"]["series"]["benchmark"]["label"] == "Luôn long"
    assert "result" not in client.get("/api/studio/alphas/user").json()[0]
    dup = client.post("/api/studio/alphas/user", json={"job_id": job_id, "code": CODE_SAVE, "name": "A lần 2"})      # cùng program_hash -> 409 tiếng Việt
    assert dup.status_code == 409 and "đã được lưu" in dup.json()["detail"]


def test_sort_cagr_uses_cagr_pct_not_ret_pct_and_missing_goes_last(tmp_path):
    base = str(tmp_path / "alphas")
    os.makedirs(os.path.join(base, "user"))

    def put(i, sim, test=None):
        rec = {"id": i, "name": i, "created_at": "2026-01-0%dT00:00:00" % int(i[-1]), "updated_at": "2026-01-0%dT00:00:00" % int(i[-1]),
               "metrics": {"simulate": sim, **({"test": test} if test else {})}}
        (tmp_path / "alphas" / "user" / f"{i}.json").write_text(json.dumps(rec), encoding="utf-8")
    put("a1", {"ret_pct": 500.0, "cagr_pct": 10.0})        # lợi nhuận tổng lớn nhưng CAGR thấp
    put("a2", {"ret_pct": 50.0, "cagr_pct": 40.0})
    put("a3", {"ret_pct": 900.0})                           # thiếu CAGR -> cuối
    put("a4", {"ret_pct": 1.0, "cagr_pct": 0.0})            # CAGR = 0 thật, không bị coi là thiếu
    assert [x["id"] for x in user_alphas.list_user_alphas(sort="cagr", base_dir=base)] == ["a2", "a1", "a4", "a3"]
    put("a1", {}, {"sharpe": 0.3})
    put("a2", {}, {"sharpe": 1.1})
    assert [x["id"] for x in user_alphas.list_user_alphas(sort="sharpe", base_dir=base)][:2] == ["a2", "a1"]


def test_catalog_user_card_has_none_not_zero_for_missing_metrics(tmp_path):
    base = str(tmp_path / "alphas")
    os.makedirs(os.path.join(base, "user"))
    rec = {"id": "m1", "name": "M", "code": "x", "status": "SAVED", "config": {"symbols": ["BTC"], "program": {"legs": ["LONG"]}}, "created_at": "a", "updated_at": "a",
           "metrics": {"simulate": {"ret_pct": 0.0, "mdd_pct": None, "sharpe": 0.0, "trades": 0}}}
    (tmp_path / "alphas" / "user" / "m1.json").write_text(json.dumps(rec), encoding="utf-8")
    card = next(s for s in strategy_doc.catalog(alphas_dir=base)["sources"][0]["strategies"] if s.get("alpha_id") == "m1")
    st = card["stats"][0]
    assert st["ret_pct"] == 0.0 and st["sharpe"] == 0.0 and st["trades"] == 0           # số 0 thật được giữ
    assert st["mdd_pct"] is None and st["sortino"] is None and st["win_rate"] is None and st["profit_factor"] is None   # thiếu -> None, không 0 giả
    assert card["summary"]["mdd_pct"] is None


