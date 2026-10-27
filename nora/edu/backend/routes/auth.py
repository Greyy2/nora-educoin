"""Routes quản lý người dùng và phiên đăng nhập (P17 T2 B2).

Endpoints:
- GET /api/users: danh sách công khai kèm số chiến lược n_strategies
- POST /api/users: tạo người dùng mới, tự động đăng nhập (set cookie)
- GET /api/users/{handle}: thông tin một người dùng
- GET /api/users/{handle}/strategies: danh sách chiến lược của người dùng
- GET /api/me: thông tin người dùng hiện tại (trả {user: null} nếu chưa đăng nhập)
- POST /api/me/enter: chỉ nhập tên, có thì vào, chưa có thì tạo
- POST /api/me/login: đăng nhập không mật khẩu bằng handle
- POST /api/me/logout: đăng xuất, xóa cookie
- PUT /api/me: cập nhật hồ sơ cá nhân (yêu cầu đăng nhập)
"""
import os
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend import users
from backend.analys.alpha import strategies as store

users_router = APIRouter(tags=["users"])


def _get_cookie_key_for_request(request: Request) -> str:
    """Xác định đúng key cookie theo ứng dụng và host: cô lập hoàn toàn giữa edu và coin."""
    app_title = str(getattr(getattr(request, "app", None), "title", ""))
    host = (request.headers.get("host") or "").lower()
    if "EDU" in app_title or "edu." in host:
        return "edu_session"
    if "COIN" in app_title or "coin." in host:
        return "coin_session"
    return "nora_uid"


def current_uid(request: Request) -> Optional[str]:
    """Lấy UID từ cookie phiên đã xác thực (HMAC hợp lệ theo product audience)."""
    cookie_key = _get_cookie_key_for_request(request)
    cookie_val = request.cookies.get(cookie_key)
    if not cookie_val:
        raw_cookie = request.headers.get("cookie", "")
        for part in raw_cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip() == cookie_key:
                    cookie_val = v.strip()
                    break
    if not cookie_val and cookie_key == "nora_uid":
        cookie_val = request.cookies.get("nora_uid")
    if not cookie_val:
        return None
    return users.verify_uid(cookie_val)


def current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Dependency lấy thông tin người dùng từ cookie phiên cô lập theo product.
    Tuyệt đối không fallback chéo giữa edu_session và coin_session.
    """
    uid = current_uid(request)
    if not uid:
        return None
    return users.get_user(uid)


def set_uid_cookie(response: Response, user_id: str, request: Request) -> None:
    """Ghi cookie phiên có chữ ký HMAC (host-only, HttpOnly, SameSite lax), cô lập theo product."""
    cookie_val = users.sign_uid(user_id)
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_key = _get_cookie_key_for_request(request)

    response.set_cookie(
        key=cookie_key,
        value=cookie_val,
        max_age=31536000,
        httponly=True,
        samesite="lax",
        path="/",
        secure=is_https,
    )


def clear_uid_cookie(response: Response) -> None:
    """Xóa cookie phiên tương ứng (xóa cả session và guest ID để dọn dẹp sạch)."""
    for key in ["nora_uid", "edu_session", "coin_session", "edu_guest_id"]:
        response.delete_cookie(key=key, path="/")


def get_or_create_guest_id(request: Request, response: Optional[Response] = None) -> str:
    """Tạo hoặc lấy định danh riêng biệt (unguessable capability) cho khách vãng lai, ngăn ngừa dùng chung danh tính."""
    guest_id = request.cookies.get("edu_guest_id")
    if not guest_id:
        raw_cookie = request.headers.get("cookie", "")
        for part in raw_cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip() == "edu_guest_id":
                    guest_id = v.strip()
                    break
    if not guest_id or not re.match(r"^gst_[a-f0-9]{32}$", guest_id):
        guest_id = f"gst_{secrets.token_hex(16)}"
        if response:
            is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
            response.set_cookie(
                key="edu_guest_id",
                value=guest_id,
                max_age=86400 * 7,
                httponly=True,
                samesite="lax",
                path="/",
                secure=is_https,
            )
    return guest_id


def get_effective_identity(request: Request, response: Optional[Response] = None) -> Tuple[str, bool]:
    """Trả về (identity_id, is_guest): nếu có user thật thì dùng user_id, ngược lại dùng guest_id độc nhất."""
    uid = current_uid(request)
    if uid:
        return uid, False
    return get_or_create_guest_id(request, response), True


# ─── Schema Pydantic ─────────────────────────────────────────────────────────

class CreateUserReq(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=40)
    display_name: Optional[str] = Field(None, min_length=1, max_length=40)
    handle: Optional[str] = Field(None, min_length=1, max_length=40)
    bio: str = Field("", max_length=200)
    avatar: Optional[Dict[str, str]] = None
    password: Optional[str] = Field(None, min_length=1, max_length=128)


class EnterReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)


class LoginReq(BaseModel):
    handle: Optional[str] = None
    name: Optional[str] = None
    password: Optional[str] = None


class ChangePasswordReq(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class UpdateProfileReq(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=40)
    avatar: Optional[Dict[str, str]] = None
    bio: Optional[str] = Field(None, max_length=200)


class SocialLoginReq(BaseModel):
    provider: str = Field("google", max_length=20)
    credential: str = Field(..., min_length=10)


# ─── Endpoints ──────────────────────────────────────────────────────────────


@users_router.get("/api/users")
def get_users_list() -> List[Dict[str, Any]]:
    """Danh sách người dùng công khai kèm số chiến lược đã lưu."""
    raw_users = users.list_users()
    counts = store.count_by_owner()
    out = []
    for u in raw_users:
        out.append({
            "id": u.get("id"),
            "handle": u.get("handle"),
            "display_name": u.get("display_name"),
            "avatar": u.get("avatar"),
            "bio": u.get("bio", ""),
            "role": u.get("role", "learner"),
            "n_strategies": counts.get(u.get("id", ""), 0),
            "created_at": u.get("created_at"),
        })
    return out


@users_router.post("/api/users")
def create_new_user(req: CreateUserReq, request: Request, response: Response) -> Dict[str, Any]:
    """Tạo người dùng mới chỉ bằng Tên + Mật khẩu (tên đăng nhập = tên hiển thị) và tự động đăng nhập."""
    target_name = (req.name or req.display_name or req.handle or "").strip()
    if not target_name:
        raise HTTPException(status_code=422, detail="Vui lòng nhập tên")
    target_pw = req.password if (req.password is not None and req.password != "") else "1"
    try:
        u = users.create_user(
            name=target_name,
            handle=req.handle,
            password=target_pw,
            avatar=req.avatar,
            bio=req.bio,
        )
    except ValueError as err:
        msg = str(err)
        if "đã tồn tại" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    set_uid_cookie(response, u["id"], request)
    return u


@users_router.get("/api/users/{handle}")
def get_user_profile(handle: str) -> Dict[str, Any]:
    """Thông tin hồ sơ một người dùng theo handle."""
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    counts = store.count_by_owner()
    return {
        "id": u.get("id"),
        "handle": u.get("handle"),
        "display_name": u.get("display_name"),
        "avatar": u.get("avatar"),
        "bio": u.get("bio", ""),
        "role": u.get("role", "learner"),
        "n_strategies": counts.get(u.get("id", ""), 0),
        "created_at": u.get("created_at"),
    }


@users_router.get("/api/users/{handle}/strategies")
def get_user_strategies(handle: str) -> List[Dict[str, Any]]:
    """Chiến lược người dùng đã lưu (chỉ lấy các bản ghi có owner khớp)."""
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return store.list_user_alphas(owner_id=u["id"])


@users_router.get("/api/me")
def get_current_me(request: Request) -> Dict[str, Any]:
    """Thông tin phiên người dùng hiện tại (trả {user: null} nếu chưa đăng nhập)."""
    me = current_user(request)
    return {"user": me}


@users_router.post("/api/me/login")
def login_with_handle(req: LoginReq, request: Request, response: Response) -> Dict[str, Any]:
    """Đăng nhập bằng tên đăng nhập / tên hiển thị và mật khẩu."""
    login_key = (req.name or req.handle or "").strip()
    if not login_key:
        raise HTTPException(status_code=422, detail="Vui lòng nhập tên đăng nhập")
    if not req.password:
        raise HTTPException(
            status_code=400,
            detail="Đăng nhập chỉ bằng handle không được hỗ trợ để đảm bảo an toàn danh tính tài khoản. Vui lòng cung cấp mật khẩu.",
        )
    pw = req.password
    try:
        u = users.authenticate_user(login_key, pw)
    except ValueError as err:
        raise HTTPException(status_code=401, detail=str(err))

    set_uid_cookie(response, u["id"], request)
    return {"user": u}


@users_router.post("/api/me/enter")
def enter_with_name(req: EnterReq, request: Request, response: Response) -> Dict[str, Any]:
    """Onboarding nhanh cho học viên mới: luôn tạo một tài khoản học viên mới riêng biệt, tuyệt đối không cấp phiên của tài khoản đã tồn tại."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Vui lòng nhập tên")
    try:
        u = users.create_user(handle=users.unique_handle(name), display_name=name, password="1")
    except ValueError as err:
        if "đã tồn tại" in str(err):
            raise HTTPException(status_code=409, detail=str(err))
        raise HTTPException(status_code=422, detail=str(err))
    set_uid_cookie(response, u["id"], request)
    return {"user": u}


def _get_google_client_id() -> Optional[str]:
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    if cid:
        return cid.strip()
    from pathlib import Path
    import json
    secret_path = Path(__file__).resolve().parent.parent / "data" / "secrets" / "google_oauth.json"
    if secret_path.is_file():
        try:
            raw = json.loads(secret_path.read_text(encoding="utf-8"))
            return raw.get("web", {}).get("client_id") or raw.get("client_id")
        except Exception:
            pass
    return None


@users_router.post("/api/me/social-login")
def social_login(req: SocialLoginReq, request: Request, response: Response) -> Dict[str, Any]:
    """Đăng nhập bằng tài khoản liên kết (Google Identity Services)."""
    if req.provider.lower() != "google":
        raise HTTPException(status_code=400, detail=f"Nhà cung cấp {req.provider} chưa được hỗ trợ.")

    import json
    import urllib.request
    import urllib.parse

    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(req.credential)}"
        req_ext = urllib.request.Request(url, headers={"User-Agent": "Nora-Server/1.0"})
        with urllib.request.urlopen(req_ext, timeout=8) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Không thể xác thực danh tính với Google: {str(e)}")

    expected_cid = _get_google_client_id()
    if expected_cid and info.get("aud") != expected_cid and info.get("azp") != expected_cid:
        raise HTTPException(status_code=401, detail="Google Client ID không khớp với hệ thống.")

    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Không tìm thấy email từ tài khoản Google.")
    if info.get("email_verified") not in [True, "true", "True"]:
        raise HTTPException(status_code=401, detail="Email Google chưa được kích hoạt xác thực.")

    sub = info.get("sub") or ""
    name = (info.get("name") or email.split("@")[0]).strip()

    all_users = users.list_users()
    matched_user = None
    for item in all_users:
        u_full = users.get_user(item["id"])
        if not u_full:
            continue
        if u_full.get("google_sub") == sub or u_full.get("email") == email:
            matched_user = u_full
            break
        if u_full.get("handle") == email.split("@")[0].lower():
            matched_user = u_full
            break

    if not matched_user:
        base_h = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower())
        if len(base_h) < 3:
            base_h = f"u_{base_h}"
        base_h = base_h[:20]
        handle = users.unique_handle(base_h)
        avatar = {"emoji": "🌐", "color": "#4285F4"}
        matched_user = users.create_user(
            name=name,
            handle=handle,
            password=secrets.token_hex(16),
            avatar=avatar,
            bio=f"Học viên xác thực qua Google ({email})",
        )
        users.update_user(matched_user["id"], email=email, google_sub=sub)
        matched_user["email"] = email
        matched_user["google_sub"] = sub
    else:
        updates = {}
        if not matched_user.get("google_sub") and sub:
            updates["google_sub"] = sub
        if not matched_user.get("email") and email:
            updates["email"] = email
        if updates:
            matched_user = users.update_user(matched_user["id"], **updates)

    set_uid_cookie(response, matched_user["id"], request)
    return {"ok": True, "user": matched_user}


@users_router.post("/api/me/logout")

def logout_current_me(response: Response) -> Dict[str, Any]:
    """Đăng xuất, xóa cookie phiên."""
    clear_uid_cookie(response)
    return {"ok": True}


@users_router.post("/api/me/password")
def change_current_password(
    req: ChangePasswordReq,
    me: Optional[Dict[str, Any]] = Depends(current_user),
) -> Dict[str, bool]:
    """Change the current user's password after verifying the existing password."""
    if not me:
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để đổi mật khẩu")
    try:
        users.change_password(me["id"], req.current_password, req.new_password)
    except ValueError as err:
        raise HTTPException(status_code=401, detail=str(err))
    return {"ok": True}


@users_router.put("/api/me")
def update_current_me(
    req: UpdateProfileReq,
    request: Request,
    me: Optional[Dict[str, Any]] = Depends(current_user),
) -> Dict[str, Any]:
    """Cập nhật thông tin tài khoản đang đăng nhập."""
    if not me:
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để cập nhật hồ sơ")

    fields = {}
    if req.display_name is not None:
        fields["display_name"] = req.display_name
    if req.avatar is not None:
        fields["avatar"] = req.avatar
    if req.bio is not None:
        fields["bio"] = req.bio

    try:
        updated = users.update_user(me["id"], **fields)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))

    return updated
