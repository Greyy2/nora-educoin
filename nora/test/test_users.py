"""Kiểm thử quản lý người dùng và phiên đăng nhập (P17 T2)."""
import os
import pytest
from backend import users


@pytest.fixture(autouse=True)
def isolated_users_dir(tmp_path, monkeypatch):
    """Cô lập thư mục data/users trong thư mục tạm khi chạy test."""
    u_dir = str(tmp_path / "users")
    os.makedirs(u_dir, exist_ok=True)
    monkeypatch.setattr("backend.models.storage.users_dir", lambda *parts: os.path.join(u_dir, *parts))
    monkeypatch.setattr(users, "users_dir", lambda *parts: os.path.join(u_dir, *parts))
    monkeypatch.setattr(users, "_CACHE_MTIME", -1.0)
    monkeypatch.setattr(users, "_HANDLE_MAP", {})
    return u_dir


def test_create_and_get_user():
    u = users.create_user(handle="nguyen_an", display_name="Nguyễn An", bio="Học viên Nora")
    assert u["id"] and len(u["id"]) == 12
    assert u["handle"] == "nguyen_an"
    assert u["display_name"] == "Nguyễn An"
    assert u["bio"] == "Học viên Nora"
    assert u["role"] == "learner"
    assert "avatar" in u and "emoji" in u["avatar"] and "color" in u["avatar"]

    # Đọc lại bằng ID và bằng handle
    fetched_id = users.get_user(u["id"])
    assert fetched_id == u

    fetched_handle = users.get_by_handle("nguyen_an")
    assert fetched_handle == u

    # Case-insensitive handle
    assert users.get_by_handle("NGUYEN_AN") == u


def test_handle_validation_and_uniqueness():
    # Quá ngắn (< 3)
    with pytest.raises(ValueError, match="Handle không hợp lệ"):
        users.create_user(handle="ab", display_name="AB")

    # Ký tự đặc biệt không hợp lệ
    with pytest.raises(ValueError, match="Handle không hợp lệ"):
        users.create_user(handle="an-nguyen", display_name="An")

    # Tạo thành công
    users.create_user(handle="user_one", display_name="User One")

    # Trùng handle
    with pytest.raises(ValueError, match="đã tồn tại"):
        users.create_user(handle="user_one", display_name="User Trùng")

    with pytest.raises(ValueError, match="đã tồn tại"):
        users.create_user(handle="USER_ONE", display_name="User Trùng hoa")


def test_deterministic_avatar():
    av1 = users.default_avatar("satoshi")
    av2 = users.default_avatar("satoshi")
    av3 = users.default_avatar("SATOSHI")
    assert av1 == av2 == av3
    assert av1["emoji"] in users.AVATAR_EMOJIS
    assert av1["color"] in users.AVATAR_COLORS


def test_update_user():
    u = users.create_user(handle="trader_x", display_name="Trader X")
    updated = users.update_user(u["id"], display_name="Trader Pro", bio="Chuyên gia định lượng", avatar={"emoji": "🚀", "color": "#10B981"})
    assert updated["display_name"] == "Trader Pro"
    assert updated["bio"] == "Chuyên gia định lượng"
    assert updated["avatar"] == {"emoji": "🚀", "color": "#10B981"}

    # Đọc lại từ disk
    reloaded = users.get_user(u["id"])
    assert reloaded["display_name"] == "Trader Pro"
    assert reloaded["bio"] == "Chuyên gia định lượng"
    assert reloaded["avatar"] == {"emoji": "🚀", "color": "#10B981"}


def test_session_signing_and_verification():
    uid = "a1b2c3d4e5f6"
    cookie = users.sign_uid(uid)
    assert cookie.startswith(f"{uid}.")
    assert users.verify_uid(cookie) == uid

    # Sửa 1 ký tự -> giả mạo
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    assert users.verify_uid(tampered) is None

    # Null / rỗng / sai định dạng
    assert users.verify_uid(None) is None
    assert users.verify_uid("") is None
    assert users.verify_uid("invalid_cookie_without_dot") is None


def test_users_api_flow():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # 1. Chưa đăng nhập -> /api/me trả {"user": None}
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"user": None}

    # 2. PUT /api/me khi chưa login -> 401
    r = client.put("/api/me", json={"display_name": "Hack"})
    assert r.status_code == 401

    # 3. Tạo user mới -> 200 + set cookie
    r = client.post("/api/users", json={"handle": "alice_vn", "display_name": "Alice Nguyễn", "bio": "Trader"})
    assert r.status_code == 200
    user_data = r.json()
    assert user_data["handle"] == "alice_vn"
    assert "nora_uid" in client.cookies

    # 4. GET /api/me trả thông tin user đã tạo
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["user"]["handle"] == "alice_vn"

    # 5. Tạo trùng handle -> 409
    r_dup = client.post("/api/users", json={"handle": "alice_vn", "display_name": "Alice 2"})
    assert r_dup.status_code == 409

    # 6. GET /api/users/{handle}
    r_get = client.get("/api/users/alice_vn")
    assert r_get.status_code == 200
    assert r_get.json()["display_name"] == "Alice Nguyễn"

    r_none = client.get("/api/users/non_existent_user")
    assert r_none.status_code == 404

    # 7. PUT /api/me cập nhật thông tin
    r_put = client.put("/api/me", json={"display_name": "Alice Pro", "bio": "Quant Trader"})
    assert r_put.status_code == 200
    assert r_put.json()["display_name"] == "Alice Pro"

    # 8. POST /api/me/logout -> /api/me trả null
    r_out = client.post("/api/me/logout")
    assert r_out.status_code == 200
    r_after_logout = client.get("/api/me")
    assert r_after_logout.json() == {"user": None}

    # 9. POST /api/me/login đăng nhập lại bằng handle
    r_in = client.post("/api/me/login", json={"handle": "alice_vn"})
    assert r_in.status_code == 200
    assert r_in.json()["user"]["handle"] == "alice_vn"


def test_user_alphas_owner_isolation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.jobs import runner as batch
    from backend.alpha import store

    client = TestClient(app)

    # Tạo 2 user
    u1 = users.create_user("owner_one", "Owner 1")
    u2 = users.create_user("owner_two", "Owner 2")

    code = "trend_following: ema_fast > ema_slow"
    # Giả lập job xong
    res = {
        "program_hash": "hash_shared_123",
        "config": {"symbols": ["BTC@perp"], "timeframe": "1h"},
        "metrics": {"simulate": {"sharpe": 1.5, "mdd_pct": 10.0}},
        "trades": [{} for _ in range(25)],
    }
    monkeypatch.setattr("backend.alpha.compile.compile_code", lambda c, register=False: type("Prog", (), {"code_hash": "hash_shared_123"})())
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": res, "created": 1, "finished": 2})

    # Owner 1 lưu code
    r1, _ = store.save_user_alpha("job1", code, "Alpha 1", owner_id=u1["id"])
    assert r1["owner_id"] == u1["id"]

    # Owner 1 lưu LẠI cùng code -> 409 / ValueError (chống trùng cùng owner)
    with pytest.raises(ValueError, match="đã được lưu"):
        store.save_user_alpha("job1_dup", code, "Alpha 1 trùng", owner_id=u1["id"])

    # Owner 2 lưu CÙNG CODE -> thành công (2 owner khác nhau lưu cùng code được)
    r2, _ = store.save_user_alpha("job2", code, "Alpha 2 của Owner 2", owner_id=u2["id"])
    assert r2["owner_id"] == u2["id"]

    # Lọc theo owner_id
    alphas_u1 = store.list_user_alphas(owner_id=u1["id"])
    assert len(alphas_u1) == 1 and alphas_u1[0]["id"] == r1["id"]

    alphas_u2 = store.list_user_alphas(owner_id=u2["id"])
    assert len(alphas_u2) == 1 and alphas_u2[0]["id"] == r2["id"]

    # Đếm theo owner
    counts = store.count_by_owner()
    assert counts[u1["id"]] == 1
    assert counts[u2["id"]] == 1

    # Kiểm tra quyền qua API: đăng nhập là u2 nhưng cố archive alpha của u1 -> 403
    client.post("/api/me/login", json={"handle": "owner_two"})
    r_arch_forbidden = client.post(f"/api/studio/alphas/user/{r1['id']}/archive")
    assert r_arch_forbidden.status_code == 403

    # Đăng nhập là u1 -> archive được
    client.post("/api/me/login", json={"handle": "owner_one"})
    r_arch_ok = client.post(f"/api/studio/alphas/user/{r1['id']}/archive")
    assert r_arch_ok.status_code == 200
    assert r_arch_ok.json()["status"] == "ARCHIVED"


def test_home_summary_api():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/home/summary")
    assert r.status_code == 200
    data = r.json()
    assert "edu" in data and "coin" in data
    edu = data["edu"]
    coin = data["coin"]

    assert "users" in edu and isinstance(edu["users"], int)
    assert "strategies" in edu and isinstance(edu["strategies"], int)
    assert "samples" in edu and isinstance(edu["samples"], int)
    assert "samples_ready" in edu and isinstance(edu["samples_ready"], int)

    assert "system_strategies" in coin and isinstance(coin["system_strategies"], int)
    assert "symbols" in coin and coin["symbols"] == 10
    assert "engine" not in coin
    assert "data_end" in coin




def test_slug_and_unique_handle():
    assert users.slugify_handle("Nguyễn Văn Đạt") == "nguyen_van_dat"
    assert users.slugify_handle("An") == "an_user"
    assert users.slugify_handle("!!") == "user"
    assert 3 <= len(users.slugify_handle("x" * 50)) <= 20
    users.create_user(handle=users.unique_handle("Trần Bình"), display_name="Trần Bình")
    assert users.unique_handle("Tran Binh") == "tran_binh2"
    users.create_user(handle="tran_binh2", display_name="Khác")
    assert users.unique_handle("Trần Bình") == "tran_binh3"


def test_enter_by_name_flow():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    # POST /api/users chỉ cần display_name
    r = client.post("/api/users", json={"display_name": "Lê Hoa"})
    assert r.status_code == 200 and r.json()["handle"] == "le_hoa"
    r = client.post("/api/users", json={"display_name": "Lê Hoa 2"})
    assert r.json()["handle"] == "le_hoa_2"
    client.post("/api/me/logout")

    # Tên đã có (không phân biệt hoa thường, trim) -> vào đúng user cũ, không tạo mới
    n_before = len(users.list_users())
    r = client.post("/api/me/enter", json={"name": "  LÊ hoa "})
    assert r.status_code == 200 and r.json()["user"]["handle"] == "le_hoa"
    assert client.get("/api/me").json()["user"]["handle"] == "le_hoa"
    assert len(users.list_users()) == n_before

    # Tên mới -> tạo và đăng nhập
    client.post("/api/me/logout")
    r = client.post("/api/me/enter", json={"name": "Phạm Minh"})
    assert r.status_code == 200 and r.json()["user"]["handle"] == "pham_minh"
    assert client.get("/api/me").json()["user"]["display_name"] == "Phạm Minh"
    assert len(users.list_users()) == n_before + 1

    # Tên trống -> 422
    assert client.post("/api/me/enter", json={"name": "   "}).status_code == 422
