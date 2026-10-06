"""Thư viện chiến lược (/api/studio/alphas): mỗi chiến lược = ý tưởng + công thức bằng lời + công thức toán (ký hiệu) + thống kê alpha đã đạt, theo NGUỒN.

GET /api/studio/alphas/catalog  {"sources": [{"key": "nora", "label": "Nora", "strategies": [...]}]} — nguồn ngoài thêm sau cùng định dạng.
Dựng từ strategy/book.py (cây khuôn + params_schema) + data/alphas/book.json, explore/book.json qua core/analytics/strategy_doc.py (đọc thuần).
"""
from typing import Any, Dict

from fastapi import APIRouter

from backend.core.analytics import strategy_doc

router = APIRouter(prefix="/api/studio/alphas", tags=["alphas"])


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return strategy_doc.catalog()
