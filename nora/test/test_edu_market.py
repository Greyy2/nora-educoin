"""Market Education: số liệu tổng hợp = tổng từ kết quả đã lưu; luật hiện mẫu; seed idempotent (data root tạm)."""
import importlib.util
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import users
from backend.alpha import store
from backend.alpha.compile import compile_code
from backend.routes import edu, users as users_routes

_SAMPLES = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "alpha", "education", "samples.json"), encoding="utf-8"))
_SEED = os.path.join(os.path.dirname(__file__), "scripts", "seed_edu_users.py")


def _result_for(code, k):
    """Kết quả mô phỏng có cấu trúc như cache thật; số đo khác nhau theo k để kiểm tổng/ max."""
    return {
        "program_hash": compile_code(code, register=False).code_hash,
        "config": {"symbols": ["BTC"], "initial_capital": 10000.0, "timeframe": "24h"},
        "metrics": {"simulate": {"ret_pct": 10.0 + k, "mdd_pct": 5.0 + k, "sharpe": 1.0 + k / 10, "win_rate_trades": 50.0, "trades": 30 + k},
                    "test": {"sharpe": 0.5}},
        "trades": [{"pnl": 1.0}] * 30,
        "final_equity": 10000.0 + 100.0 * (k + 1),
    }


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(store, "_education_samples", lambda: _SAMPLES)
    idx = {s["key"]: i for i, s in enumerate(_SAMPLES)}
    monkeypatch.setattr(store, "sample_lookup", lambda s, spec=None: _result_for(s["code"], idx[s["key"]] % 7))
    a = FastAPI()
    a.include_router(edu.edu_router)
    a.include_router(users_routes.users_router)
    return a


def _uniq(prefix):
    return f"{prefix}{os.urandom(3).hex()}"


def test_market_aggregates_equal_sums(app):
    u = users.create_user(_uniq("agg"), "Tác giả", role="demo")
    picks = _SAMPLES[:3]
    for i, s in enumerate(picks):
        store.save_user_alpha_from_result(u["id"], s["code"], s["name"], _result_for(s["code"], i), source="seed", sample_key=s["key"])
    c = TestClient(app)
    row = next(r for r in c.get("/api/edu/market").json()["users"] if r["handle"] == u["handle"])
    assert row["n_strategies"] == 3
    assert row["total_pnl_usd"] == pytest.approx(sum(100.0 * (i + 1) for i in range(3)))
    assert row["max_mdd_pct"] == pytest.approx(5.0 + 2)
    assert row["best"]["name"] == picks[2]["name"]            # ret_pct lớn nhất = k lớn nhất
    d = c.get(f"/api/edu/users/{u['handle']}").json()
    assert len(d["strategies"]) == 3 and d["summary"]["total_pnl_usd"] == row["total_pnl_usd"]
    assert {"ret_pct", "mdd_pct", "sharpe", "win_rate", "trades", "category"} <= set(d["strategies"][0])
    det = c.get(f"/api/edu/strategies/{d['strategies'][0]['id']}").json()
    assert det["code"] and det["result"] and det["owner"]["handle"] == u["handle"]


def test_user_without_strategies(app):
    u = users.create_user(_uniq("empty"), "Người xem")
    row = next(r for r in TestClient(app).get("/api/edu/market").json()["users"] if r["handle"] == u["handle"])
    assert row["n_strategies"] == 0 and row["total_pnl_usd"] is None and row["max_mdd_pct"] is None and row["best"] is None


def test_show_samples_three_states(app):
    c = TestClient(app)
    guest = c.get("/api/edu/samples/visible").json()
    assert guest["show_samples"] and len(guest["samples"]) == 1 and guest["samples"][0]["difficulty"] == "Beginner"

    u = users.create_user(_uniq("newbie"), "Người mới")
    c.cookies.set("nora_uid", users.sign_uid(u["id"]))
    new = c.get("/api/edu/samples/visible").json()
    assert new["show_samples"] and len(new["samples"]) == 1

    s = _SAMPLES[0]
    store.save_user_alpha_from_result(u["id"], s["code"], s["name"], _result_for(s["code"], 1), source="education")
    after = c.get("/api/edu/samples/visible").json()
    assert after == {"show_samples": False, "samples": []}


def test_seed_idempotent(app):
    spec = importlib.util.spec_from_file_location("seed_edu_users", _SEED)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    plan = seed.assignment(_SAMPLES)
    assert len(plan) == 10 and all(len(v) == 5 for v in plan.values())
    assert len({s["key"] for v in plan.values() for s in v}) == 50
    assert all(len({s["category"] for s in v}) == 5 for v in plan.values())

    n_users0 = len(users.list_users())
    assert seed.seed(log=lambda *_: None) == 50
    n_users1 = len(users.list_users())
    assert n_users1 - n_users0 >= 10                              # 10 tác giả + 1 người xem (tối thiểu tác giả chưa có)
    assert seed.seed(log=lambda *_: None) == 0                    # chạy lại: không nhân đôi
    assert len(users.list_users()) == n_users1
    for handle, _, _ in seed.AUTHORS:
        assert len(store.list_user_alphas(owner_id=users.get_by_handle(handle)["id"])) == 5
    viewer = users.get_by_handle("nguoi_xem")
    assert viewer and store.count_by_owner().get(viewer["id"], 0) == 0


def test_fork_strategy(app):
    c = TestClient(app)
    u_author = users.create_user(_uniq("author"), "Tác giả", role="demo")
    s = _SAMPLES[0]
    rec, _ = store.save_user_alpha_from_result(u_author["id"], s["code"], s["name"], _result_for(s["code"], 1), source="seed", sample_key=s["key"])
    alpha_id = rec["id"]

    # 1. Chưa đăng nhập -> 401
    r_unauth = c.post(f"/api/edu/strategies/{alpha_id}/fork")
    assert r_unauth.status_code == 401

    # 2. Đăng nhập -> tạo draft thành công
    u_me = users.create_user(_uniq("forker"), "Người chép")
    c.cookies.set("nora_uid", users.sign_uid(u_me["id"]))
    r_ok = c.post(f"/api/edu/strategies/{alpha_id}/fork")
    assert r_ok.status_code == 200
    res = r_ok.json()
    assert res.get("ok") is True
    assert "draft" in res
    assert res["draft"]["code"] == s["code"]
    assert res["draft"]["forked_from"]["alpha_id"] == alpha_id
    assert res["draft"]["forked_from"]["owner_handle"] == u_author["handle"]

    # 3. 404 khi alpha không tồn tại
    assert c.post("/api/edu/strategies/nonexistent_id/fork").status_code == 404


def test_card_index_invalidates_after_save(app):
    c = TestClient(app)
    u = users.create_user(_uniq("idx"), "Chỉ mục", role="demo")
    row = lambda: next(r for r in c.get("/api/edu/market").json()["users"] if r["id"] == u["id"])
    assert row()["n_strategies"] == 0
    s0, s1 = _SAMPLES[0], _SAMPLES[1]
    store.save_user_alpha_from_result(u["id"], s0["code"], s0["name"], _result_for(s0["code"], 0), source="seed", sample_key=s0["key"])
    assert row()["n_strategies"] == 1
    p1 = row()["total_pnl_usd"]
    store.save_user_alpha_from_result(u["id"], s1["code"], s1["name"], _result_for(s1["code"], 1), source="seed", sample_key=s1["key"])
    r = row()
    assert r["n_strategies"] == 2 and r["total_pnl_usd"] > p1
    assert len(c.get(f"/api/edu/users/{r['handle']}").json()["strategies"]) == 2
