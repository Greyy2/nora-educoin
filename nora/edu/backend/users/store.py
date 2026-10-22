"""Quản lý người dùng và phiên đăng nhập (P17 T2).

User = {id, handle, display_name, avatar, bio, role, created_at}.
Lưu trữ dạng file JSON nguyên tử tại data/users/<id>.json.
Phiên đăng nhập: cookie nora_uid ký HMAC-SHA256, secret lưu tại ~/.config/nora/app.env.
Bản đầu không dùng mật khẩu (chọn user = đăng nhập) — giới hạn demo nội bộ cho T2/T3.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import stat
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.models.storage import users_dir, write_json_atomic, read_json

logger = logging.getLogger("nora.users")

HANDLE_REGEX = re.compile(r"^[a-z0-9_]{3,20}$")

AVATAR_EMOJIS = [
    "🦊", "🦉", "🐱", "🐼", "🦁", "🐨", "🐸", "🐧",
    "🚀", "⚡", "🍀", "💎", "🎯", "🎨", "🧩", "🌟",
]

AVATAR_COLORS = [
    "#3B82F6",  # Blue
    "#10B981",  # Emerald
    "#F59E0B",  # Amber
    "#EF4444",  # Red
    "#8B5CF6",  # Purple
    "#EC4899",  # Pink
    "#06B6D4",  # Cyan
    "#84CC16",  # Lime
    "#F97316",  # Orange
    "#6366F1",  # Indigo
]

_APP_SECRET: Optional[str] = None
_CACHE_MTIME: float = -1.0
_HANDLE_MAP: Dict[str, str] = {}


def default_avatar(handle: str) -> Dict[str, str]:
    """Sinh avatar tất định từ handle: emoji + màu từ danh sách cố định."""
    h = hashlib.sha256(handle.lower().strip().encode("utf-8")).digest()
    emoji = AVATAR_EMOJIS[h[0] % len(AVATAR_EMOJIS)]
    color = AVATAR_COLORS[h[1] % len(AVATAR_COLORS)]
    return {"emoji": emoji, "color": color}


def get_app_secret() -> str:
    """Lấy hoặc sinh khóa bí mật HMAC từ env hoặc ~/.config/nora/app.env."""
    global _APP_SECRET
    if _APP_SECRET:
        return _APP_SECRET

    env_val = os.environ.get("NORA_APP_SECRET")
    env_val = os.environ.get("NORA_EDU_SECRET") or os.environ.get("NORA_APP_SECRET")
    if env_val:
        _APP_SECRET = env_val.strip()
        return _APP_SECRET

    conf_dir = os.path.expanduser("~/.config/nora")
    env_file = os.path.join(conf_dir, "app.env")

    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("NORA_EDU_SECRET="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            _APP_SECRET = val
                            return _APP_SECRET
                    elif line.startswith("NORA_APP_SECRET=") and not _APP_SECRET:
                        val = line.split("=", 1)[1].strip()
                        if val:
                            _APP_SECRET = val
            if _APP_SECRET:
                return _APP_SECRET
        except OSError:
            pass

    # Sinh khóa mới nếu chưa có
    try:
        os.makedirs(conf_dir, exist_ok=True)
        secret = secrets.token_hex(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = stat.S_IRUSR | stat.S_IWUSR  # 0600
        with open(os.open(env_file, flags, mode), "w", encoding="utf-8") as fh:
            fh.write(f"NORA_APP_SECRET={secret}\n")
        logger.info("[users] Generated new app secret in %s", env_file)
        _APP_SECRET = secret
        return _APP_SECRET
    except OSError as err:
        # Fallback in-memory nếu không có quyền ghi disk (ví dụ container sandbox)
        logger.warning("[users] Could not write secret to %s (%s), using ephemeral secret", env_file, err)
        _APP_SECRET = secrets.token_hex(32)
        return _APP_SECRET


PRODUCT_AUDIENCE = "nora_edu"


def sign_uid(user_id: str, audience: str = PRODUCT_AUDIENCE) -> str:
    """Ký định danh user_id thành chuỗi cookie '<id>.<hmac>' gắn kèm product audience claim."""
    secret = get_app_secret()
    payload = f"{user_id}:{audience}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{sig}"


def verify_uid(cookie: Optional[str], audience: str = PRODUCT_AUDIENCE) -> Optional[str]:
    """Xác thực chuỗi cookie phiên kèm product audience claim. Từ chối nếu cookie từ product khác."""
    if not cookie or "." not in cookie:
        return None
    parts = cookie.split(".", 1)
    if len(parts) != 2:
        return None
    user_id = parts[0]
    expected = sign_uid(user_id, audience=audience)
    if hmac.compare_digest(cookie, expected):
        return user_id
    return None


def _refresh_index(force: bool = False) -> Dict[str, str]:
    """Cập nhật chỉ mục handle -> id dựa vào mtime của thư mục users_dir()."""
    global _CACHE_MTIME, _HANDLE_MAP
    d = users_dir()
    if not os.path.isdir(d):
        _CACHE_MTIME = -1.0
        _HANDLE_MAP = {}
        return _HANDLE_MAP

    try:
        current_mtime = os.path.getmtime(d)
    except OSError:
        current_mtime = 0.0

    if not force and current_mtime == _CACHE_MTIME:
        return _HANDLE_MAP

    new_map: Dict[str, str] = {}
    try:
        for fname in os.listdir(d):
            if fname.endswith(".json"):
                fpath = os.path.join(d, fname)
                try:
                    data = read_json(fpath)
                    if isinstance(data, dict) and "id" in data and "handle" in data:
                        new_map[str(data["handle"]).lower().strip()] = str(data["id"])
                except Exception:
                    continue
    except OSError:
        pass

    _CACHE_MTIME = current_mtime
    _HANDLE_MAP = new_map
    return _HANDLE_MAP


def slugify_handle(name: str) -> str:
    """Tên hiển thị -> handle: bỏ dấu tiếng Việt, chữ thường, ký tự lạ thành '_', dài 3-20."""
    t = unicodedata.normalize("NFD", (name or "").replace("đ", "d").replace("Đ", "D"))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    t = re.sub(r"[^a-z0-9_]+", "_", t).strip("_")[:20].strip("_")
    if len(t) < 3:
        t = (t + "_user")[:20] if t else "user"
    return t


def unique_handle(name: str) -> str:
    """Handle tự sinh từ tên; thêm hậu tố số nếu đã có người dùng."""
    base = slugify_handle(name)
    index = _refresh_index(force=True)
    if base not in index:
        return base
    n = 2
    while True:
        suf = str(n)
        cand = base[: 20 - len(suf)] + suf
        if cand not in index:
            return cand
        n += 1


def get_by_display_name(name: str) -> Optional[Dict[str, Any]]:
    """Tìm người dùng theo tên hiển thị (không phân biệt hoa thường, đã trim)."""
    key = (name or "").strip().casefold()
    if not key:
        return None
    for u in list_users():
        if str(u.get("display_name", "")).strip().casefold() == key:
            return u
    return None


def create_user(
    handle: str,
    display_name: str,
    avatar: Optional[Dict[str, str]] = None,
    bio: str = "",
    role: str = "learner",
) -> Dict[str, Any]:
    """Tạo user mới và lưu vào data/users/<id>.json."""
    norm_handle = handle.lower().strip()
    if not HANDLE_REGEX.match(norm_handle):
        raise ValueError(f"Handle không hợp lệ (phải từ 3-20 ký tự thường/số/gạch dưới): {handle!r}")

    disp = (display_name or "").strip()
    if not (1 <= len(disp) <= 40):
        raise ValueError(f"Tên hiển thị phải từ 1 đến 40 ký tự (nhận {len(disp)})")

    bio_str = (bio or "").strip()
    if len(bio_str) > 200:
        raise ValueError(f"Tiểu sử tối đa 200 ký tự (nhận {len(bio_str)})")

    if role not in ("learner", "demo"):
        role = "learner"

    # Kiểm tra trùng handle
    index = _refresh_index(force=True)
    if norm_handle in index:
        raise ValueError(f"Handle @{norm_handle} đã tồn tại")

    user_id = secrets.token_hex(6)  # 12 hex chars
    d_avatar = avatar if (isinstance(avatar, dict) and "emoji" in avatar and "color" in avatar) else default_avatar(norm_handle)

    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "id": user_id,
        "handle": norm_handle,
        "display_name": disp,
        "avatar": d_avatar,
        "bio": bio_str,
        "role": role,
        "created_at": now_iso,
    }

    fpath = users_dir(f"{user_id}.json")
    write_json_atomic(fpath, record)
    _HANDLE_MAP[norm_handle] = user_id
    try:
        _CACHE_MTIME = os.path.getmtime(users_dir())
    except OSError:
        pass
    return record


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Lấy thông tin người dùng theo user_id."""
    if not user_id:
        return None
    fpath = users_dir(f"{user_id}.json")
    if not os.path.isfile(fpath):
        return None
    data = read_json(fpath)
    return data if isinstance(data, dict) else None


def get_by_handle(handle: str) -> Optional[Dict[str, Any]]:
    """Lấy thông tin người dùng theo handle."""
    if not handle:
        return None
    norm = handle.lower().strip()
    index = _refresh_index()
    uid = index.get(norm)
    if not uid:
        return None
    return get_user(uid)


def list_users() -> List[Dict[str, Any]]:
    """Liệt kê danh sách tất cả người dùng, sắp xếp theo ngày tạo."""
    d = users_dir()
    if not os.path.isdir(d):
        return []
    users = []
    for fname in sorted(os.listdir(d)):
        if fname.endswith(".json"):
            data = read_json(os.path.join(d, fname))
            if isinstance(data, dict) and "id" in data:
                users.append(data)
    users.sort(key=lambda u: u.get("created_at") or "")
    return users


def update_user(user_id: str, **fields) -> Dict[str, Any]:
    """Cập nhật thông tin người dùng (chỉ cho phép sửa display_name, avatar, bio)."""
    user = get_user(user_id)
    if not user:
        raise KeyError(f"Không tìm thấy người dùng với id={user_id}")

    changed = False
    if "display_name" in fields:
        disp = str(fields["display_name"] or "").strip()
        if not (1 <= len(disp) <= 40):
            raise ValueError(f"Tên hiển thị phải từ 1 đến 40 ký tự (nhận {len(disp)})")
        user["display_name"] = disp
        changed = True

    if "avatar" in fields:
        av = fields["avatar"]
        if isinstance(av, dict) and "emoji" in av and "color" in av:
            user["avatar"] = {"emoji": str(av["emoji"]), "color": str(av["color"])}
            changed = True

    if "bio" in fields:
        bio_str = str(fields["bio"] or "").strip()
        if len(bio_str) > 200:
            raise ValueError(f"Tiểu sử tối đa 200 ký tự (nhận {len(bio_str)})")
        user["bio"] = bio_str
        changed = True

    if changed:
        fpath = users_dir(f"{user_id}.json")
        write_json_atomic(fpath, user)

    return user
