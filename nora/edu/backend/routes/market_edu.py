"""Routes Market Education (P17 T3): lưới user, chiến lược theo user, chi tiết công khai, mẫu hướng dẫn.

Mọi số liệu tính từ kết quả Nautilus đã lưu trong alpha người dùng — không số giả.
"""
import math
from datetime import date
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


def _build_market_rows(
    timeframe: Optional[str] = None,
    symbol: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    regime: Optional[str] = None,
    ranked_only: bool = False,
) -> list:
    """Xây dựng Market partition theo symbol, timeframe, window và regime context tham khảo (DEC-01)."""
    idx = store.card_index()
    rows = []
    tf_clean = timeframe.lower() if timeframe else None
    sym_clean = symbol.upper() if symbol else None

    for u in users.list_users():
        user_cards = idx.get(u["id"], [])
        if tf_clean:
            user_cards = [c for c in user_cards if str(c.get("timeframe") or "").lower() == tf_clean]
        if sym_clean:
            user_cards = [c for c in user_cards if str(c.get("symbol") or "").upper() == sym_clean]
        if start_date:
            user_cards = [c for c in user_cards if str(c.get("start_date") or "") == start_date.isoformat()]
        if end_date:
            user_cards = [c for c in user_cards if str(c.get("end_date") or "") == end_date.isoformat()]
        if regime:
            user_cards = [
                c for c in user_cards
                if (c.get("market_context") or {}).get("status") == "available"
                and (c.get("market_context") or {}).get("dominant") == regime
            ]
        if ranked_only:
            user_cards = [c for c in user_cards if c.get("is_ranked")]

        if user_cards:
            rows.append({**_public_user(u), **store.aggregate_cards(user_cards)})
    return rows


@edu_router.get("/market")
def market(
    request: Request,
    sort: str = "best",
    ranked_only: bool = False,
    timeframe: Optional[str] = None,
    asset: Optional[str] = None,
    symbol: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    regime: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Lưới user; competitive metrics require exact symbol, timeframe, and evaluation window."""
    target_sym = symbol or asset
    has_window = start_date is not None and end_date is not None and start_date <= end_date
    if regime:
        from backend.analys.param import REGIME_NAMES
        if regime not in REGIME_NAMES or regime == "UNKNOWN":
            raise HTTPException(status_code=422, detail="Regime không hợp lệ hoặc chưa đủ dữ liệu để phân loại.")
    if (sort in ("pnl", "sharpe") or ranked_only or regime) and not (
        timeframe and target_sym and has_window
    ):
        raise HTTPException(
            status_code=422,
            detail="Để xếp hạng theo PnL/Sharpe hoặc chỉ hiện chiến lược đạt chuẩn, hãy chọn symbol, timeframe, ngày bắt đầu và ngày kết thúc để so sánh cùng cấu hình.",
        )
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")
    if timeframe or target_sym or start_date or end_date or ranked_only:
        rows = _build_market_rows(
            timeframe=timeframe,
            symbol=target_sym,
            start_date=start_date,
            end_date=end_date,
            regime=regime,
            ranked_only=ranked_only,
        )
    else:
        rows = list(_market_rows())

    me = current_user(request) if request else None
    if me:
        rows = [r for r in rows if r.get("id") != me.get("id") and r.get("handle") != me.get("handle")]
    if ranked_only and not (timeframe or target_sym):
        rows = [r for r in rows if (r.get("ranked_strategies") or 0) > 0]

    if sort == "best":
        def _best_key(r):
            best = r.get("best") or {}
            ret = best.get("ret_pct")
            return (
                0 if best.get("is_ranked") else (1 if best else 2),
                -(ret if ret is not None else -float("inf")),
                -(r.get("n_strategies") or 0),
                (r.get("display_name") or "").lower(),
            )
        rows.sort(key=_best_key)
    elif sort == "name":
        rows.sort(key=lambda r: (r.get("display_name") or "").lower())
    elif sort == "new":
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    elif sort == "sharpe":
        # Sắp xếp theo Sharpe: ưu tiên tác giả có chiến lược đạt chuẩn xếp hạng (DEC-01), theo best_sharpe giảm dần
        rows.sort(
            key=lambda r: (
                0 if (r.get("best_sharpe") and r["best_sharpe"].get("is_ranked") and r["best_sharpe"].get("sharpe") is not None) else 1,
                -(r.get("best_sharpe", {}).get("sharpe") or -999) if (r.get("best_sharpe") and r["best_sharpe"].get("is_ranked")) else 999
            )
        )
    elif sort == "pnl":
        # Sắp xếp theo PnL: ưu tiên tác giả có chiến lược đạt chuẩn xếp hạng / checklist (DEC-01), theo PnL giảm dần
        def _pnl_key(r):
            best = r.get("best") or {}
            is_eligible = bool(best.get("is_ranked") or best.get("checklist_pass"))
            pnl_val = best.get("pnl_usd") if is_eligible else None
            if pnl_val is None and is_eligible:
                pnl_val = r.get("total_pnl_usd")
            return (
                0 if (is_eligible and pnl_val is not None) else 1,
                -(pnl_val or 0) if is_eligible else 0,
                -(r.get("total_pnl_usd") or 0) if r.get("total_pnl_usd") is not None else 999999,
            )
        rows.sort(key=_pnl_key)
    else:
        rows.sort(key=lambda r: (r["total_pnl_usd"] is None, -(r["total_pnl_usd"] or 0)))

    # Phân trang (mặc định 9 thẻ / trang)
    total = len(rows)
    if page is not None or page_size is not None:
        safe_page_size = max(1, min(page_size or 9, 100))
        total_pages = max(1, math.ceil(total / safe_page_size))
        current_page = max(1, min(page or 1, total_pages)) if total > 0 else 1
        start_idx = (current_page - 1) * safe_page_size
        paged_rows = rows[start_idx : start_idx + safe_page_size]
        pagination_info = {
            "page": current_page,
            "page_size": safe_page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": current_page < total_pages,
            "has_prev": current_page > 1,
        }
    else:
        paged_rows = rows
        pagination_info = {
            "page": 1,
            "page_size": total,
            "total": total,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
        }

    return {
        "users": paged_rows,
        "pagination": pagination_info,
        "facets": {
            "timeframe": timeframe,
            "symbol": target_sym,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "regime_context": regime,
            "ranked_only": ranked_only,
            "sort": sort,
            "comparability_mode": "partitioned" if (timeframe and target_sym and has_window) else "author_portfolio_only",
        }
    }


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
    """(Đăng nhập) sao chép code về user hiện tại: tạo bản nháp độc lập kèm attribution chuẩn DEC-03."""
    import hashlib
    from datetime import datetime, timezone
    me = current_user(request)
    if not me:
        raise HTTPException(401, "Cần đăng nhập để sao chép chiến lược")
    rec = store.get_user_alpha(alpha_id)
    if not rec or rec.get("status") == "ARCHIVED" or not rec.get("owner_id"):
        raise HTTPException(404, "Không tìm thấy chiến lược")
    owner = users.get_user(rec["owner_id"])
    owner_tag = f"@{owner.get('handle')}" if (owner and owner.get("handle")) else (owner.get("display_name") if owner else "")
    suffix = f" (bản sao từ {owner_tag})" if owner_tag else " (bản sao)"

    code_str = rec.get("code", "")
    code_hash = rec.get("program_hash") or hashlib.sha256(code_str.encode("utf-8")).hexdigest()[:16]
    fork_attribution = {
        "alpha_id": rec["id"],
        "version": rec.get("version", 1),
        "author_uid": rec.get("owner_id"),
        "author_handle": owner.get("handle") if owner else None,
        "author_name": owner.get("display_name") if owner else "Tác giả",
        "code_hash": code_hash,
        "forked_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "ok": True,
        "forked_from": fork_attribution,
        "draft": {
            "name": f"{rec.get('name', 'Chiến lược')}{suffix}",
            "code": code_str,
            "config": rec.get("config", {}),
            "forked_from": fork_attribution,
        },
    }


@edu_router.get("/samples/visible")
def samples_visible(request: Request) -> Dict[str, Any]:
    """Khách hoặc user chưa lưu chiến lược nào -> đúng 1 mẫu hướng dẫn; user đã có >= 1 chiến lược -> không mẫu."""
    me: Optional[Dict[str, Any]] = current_user(request)
    show = me is None or store.count_by_owner().get(me["id"], 0) == 0
    sample = store.guide_sample() if show else None
    return {"show_samples": bool(show and sample), "samples": [sample] if show and sample else []}
