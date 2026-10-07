"""Thư viện chiến lược (/api/studio/alphas): mỗi chiến lược = ý tưởng + công thức bằng lời + công thức toán (ký hiệu) + thống kê alpha đã đạt, theo NGUỒN.

GET /api/studio/alphas/catalog  {"sources": [{"key": "nora", "label": "Nora", "strategies": [...]}]} — nguồn ngoài thêm sau cùng định dạng.
Dựng từ strategy/book.py (cây khuôn + params_schema) + data/alphas/book.json, explore/book.json qua core/analytics/strategy_doc.py (đọc thuần).
Và kho Alpha người dùng (/api/studio/alphas/user).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.analytics import strategy_doc, top_agents, user_alphas

router = APIRouter(prefix="/api/studio/alphas", tags=["alphas"])


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return strategy_doc.catalog()


@router.get("/top_agents")
def get_top_agents() -> Dict[str, Any]:
    return top_agents.top_agents()


# ─── ALPHA NGƯỜI DÙNG (C1) ───────────────────────────────────────────────────

class SaveUserAlphaRequest(BaseModel):
    job_id: str = Field(..., description="Mã job custom_backtest đã hoàn tất")
    code: str = Field(..., description="Mã Python của chiến lược")
    name: str = Field(..., min_length=1, max_length=100, description="Tên alpha")
    note: Optional[str] = Field("", max_length=2000, description="Ghi chú chiến lược")
    source: Optional[str] = Field("alpha-create", description="Nguồn đẩy (alpha-create | education)")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="Trạng thái mới: SAVED | CANDIDATE | ARCHIVED")


@router.post("/user")
def post_user_alpha(req: SaveUserAlphaRequest) -> Dict[str, Any]:
    """Đẩy chiến lược vào kho Alpha người dùng sau khi chạy backtest thành công."""
    try:
        record, action = user_alphas.save_user_alpha(
            job_id=req.job_id,
            code=req.code,
            name=req.name,
            note=req.note or "",
            source=req.source or "alpha-create",
        )
        return {
            "ok": True,
            "alpha_id": record["id"],
            "action": action,
            "status": record["status"],
            "checklist": record.get("checklist"),
            "record": record,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/user")
def get_user_alphas(
    sort: Optional[str] = Query(None, description="Tiêu chí sắp xếp: date | sharpe | cagr"),
    status: Optional[str] = Query(None, description="Lọc trạng thái: SAVED | CANDIDATE | ARCHIVED"),
) -> List[Dict[str, Any]]:
    """Lấy danh sách các Alpha người dùng đã lưu."""
    return user_alphas.list_user_alphas(sort=sort, status=status)


@router.get("/user/{alpha_id}")
def get_user_alpha_detail(alpha_id: str) -> Dict[str, Any]:
    """Lấy chi tiết một Alpha người dùng."""
    rec = user_alphas.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rec


@router.post("/user/{alpha_id}/archive")
def post_archive_user_alpha(alpha_id: str) -> Dict[str, Any]:
    """Lưu trữ (archive) một Alpha người dùng (không xóa cứng)."""
    ok = user_alphas.update_user_alpha_status(alpha_id, "ARCHIVED")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": "ARCHIVED"}


@router.post("/user/{alpha_id}/status")
def post_update_user_alpha_status(alpha_id: str, req: UpdateStatusRequest) -> Dict[str, Any]:
    """Cập nhật trạng thái Alpha người dùng: SAVED | CANDIDATE | ARCHIVED."""
    if req.status not in ("SAVED", "CANDIDATE", "ARCHIVED"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ: phải là SAVED, CANDIDATE hoặc ARCHIVED")
    ok = user_alphas.update_user_alpha_status(alpha_id, req.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": req.status}
