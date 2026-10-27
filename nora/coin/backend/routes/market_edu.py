"""Routes Market Education (P17 T3): lưới user, chiến lược theo user, chi tiết công khai, mẫu hướng dẫn.

Mọi số liệu tính từ kết quả Nautilus đã lưu trong alpha người dùng — không số giả.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from backend import users
from backend.analys.alpha import store
from backend.routes.auth import current_user

edu_router = APIRouter(prefix="/api/edu", tags=["edu"])


def _public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    return {k: u.get(k) for k in ("id", "handle", "display_name", "avatar", "bio", "role", "created_at")}


_MARKET: Dict[str, Any] = {"sig": None, "rows": []}


def _market_rows() -> list:
    """Hàng user + tổng hợp, cache theo chữ ký thư mục alpha/user và users."""
    sig = store.dir_signature(store.get_user_alphas_dir(), users.users_dir())
    if _MARKET["sig"] != sig:
        idx = store.card_index()
        rows = []
        for u in users.list_users():
            user_cards = idx.get(u["id"], [])
            rows.append({**_public_user(u), **store.aggregate_cards(user_cards)})
        _MARKET["rows"] = rows
        _MARKET["sig"] = sig
    return _MARKET["rows"]


def warm_market_cache() -> None:
    import threading
    threading.Thread(target=_market_rows, daemon=True).start()


@edu_router.get("/market")
def market(request: Request, sort: str = "pnl") -> Dict[str, Any]:
    """Lưới user kèm tổng hợp: số chiến lược, tổng PnL, MDD lớn nhất, chiến lược tốt nhất. sort: pnl | new | name."""
    rows = list(_market_rows())
    me = current_user(request) if request else None
    if me:
        rows = [r for r in rows if r.get("id") != me.get("id") and r.get("handle") != me.get("handle")]
    if sort == "name":
        rows.sort(key=lambda r: (r.get("display_name") or "").lower())
    elif sort == "new":
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    else:
        rows.sort(key=lambda r: (r["total_pnl_usd"] is None, -(r["total_pnl_usd"] or 0)))
    return {"users": rows}


@edu_router.get("/users/{handle}")
def user_strategies(handle: str, request: Request) -> Dict[str, Any]:
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(404, "Không tìm thấy người dùng")
    cards = store.owner_strategy_cards(u["id"])
    cards.sort(key=lambda c: (c["ret_pct"] is None, -(c["ret_pct"] or 0)))
    return {"user": _public_user(u), "summary": store.aggregate_cards(cards), "strategies": cards}


@edu_router.get("/strategies/{alpha_id}")
def strategy_detail(alpha_id: str) -> Dict[str, Any]:
    """Chi tiết công khai (chỉ đọc): code + kết quả + chủ sở hữu."""
    rec = store.get_user_alpha(alpha_id)
    if not rec or rec.get("status") == "ARCHIVED" or not rec.get("owner_id"):
        raise HTTPException(404, "Không tìm thấy chiến lược")
    owner = users.get_user(rec["owner_id"])
    card = store.strategy_card(rec, store._sample_meta())
    return {
        "id": rec["id"], "name": rec.get("name"), "code": rec.get("code"),
        "result": rec.get("result"), "card": card,
        "owner": _public_user(owner) if owner else None,
    }


@edu_router.post("/strategies/{alpha_id}/fork")
def fork_strategy(alpha_id: str, request: Request) -> Dict[str, Any]:
    """(Đăng nhập) sao chép code về user hiện tại: tạo bản nháp (chưa có kết quả) để mở Studio."""
    me = current_user(request)
    if not me:
        raise HTTPException(401, "Cần đăng nhập để sao chép chiến lược")
    rec = store.get_user_alpha(alpha_id)
    if not rec or rec.get("status") == "ARCHIVED" or not rec.get("owner_id"):
        raise HTTPException(404, "Không tìm thấy chiến lược")
    owner = users.get_user(rec["owner_id"])
    owner_tag = f"@{owner.get('handle')}" if (owner and owner.get("handle")) else (owner.get("display_name") if owner else "")
    suffix = f" (bản sao từ {owner_tag})" if owner_tag else " (bản sao)"
    return {
        "ok": True,
        "draft": {
            "name": f"{rec.get('name', 'Chiến lược')}{suffix}",
            "code": rec.get("code", ""),
            "forked_from": {
                "alpha_id": rec["id"],
                "owner_handle": owner.get("handle") if owner else None,
                "owner_name": owner.get("display_name") if owner else None,
            },
        },
    }


@edu_router.get("/samples/visible")
def samples_visible(request: Request) -> Dict[str, Any]:
    """Khách hoặc user chưa lưu chiến lược nào -> đúng 1 mẫu hướng dẫn; user đã có >= 1 chiến lược -> không mẫu."""
    me: Optional[Dict[str, Any]] = current_user(request)
    show = me is None or store.count_by_owner().get(me["id"], 0) == 0
    sample = store.guide_sample() if show else None
    return {"show_samples": bool(show and sample), "samples": [sample] if show and sample else []}
