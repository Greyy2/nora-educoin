"""Danh mục alpha dạng tài liệu: ý tưởng + công thức toán tài chính (LaTeX) + thống kê, theo NGUỒN (hiện chỉ "Nora").

GET /api/studio/alphas/catalog  {"sources": [{"key", "label", "books", "alphas": [...]}]} — sổ chính rồi sổ thử nghiệm; nguồn ngoài thêm sau cùng định dạng.
Dựng từ data/alphas/book.json + explore/book.json qua core/analytics/alpha_doc.py (đọc thuần, không chạy job).
"""
from typing import Any, Dict

from fastapi import APIRouter

from backend.core.analytics import alpha_doc

router = APIRouter(prefix="/api/studio/alphas", tags=["alphas"])


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return alpha_doc.catalog()
