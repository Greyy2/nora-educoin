"""Phiên bản engine Nautilus (/api/studio/nautilus): chỉ BÁO cáo, không bao giờ tự cài/nâng cấp."""
from typing import Any, Dict

from fastapi import APIRouter

from backend.nautilus.version import check_for_updates, get_version_info

router = APIRouter(prefix="/api/studio/nautilus", tags=["engine"])


@router.get("/version")
def get_nautilus_version() -> Dict[str, Any]:
    return get_version_info()


@router.get("/check_update")
def get_nautilus_check_update() -> Dict[str, Any]:
    """Hỏi PyPI bản mới nhất. Không trả lệnh cài: nâng cấp là thao tác thủ công có kiểm thử."""
    return check_for_updates()


ROUTERS = [router]
