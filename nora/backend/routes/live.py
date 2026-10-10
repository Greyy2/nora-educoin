"""Live (/api/studio/live, /api/studio/environments): đang chuyển sang Nautilus TradingNode (P15 phase 6).

Chưa có logic live thật -> mọi endpoint bot/lệnh/vị thế/số dư trả 501 `NOT_READY` (UI hiện "chưa hỗ trợ"), tuyệt đối không trả số giả hay mã lệnh giả.
Chỉ kiểm tra môi trường + kết nối OKX là thật (backend/nautilus/live.py; khoá chỉ đọc từ ~/.config/nora/okx.env, không bao giờ trả ra ngoài)."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.nautilus.live import NOT_READY as NOT_READY_LIVE, get_environments_status, test_okx_api_connection

router = APIRouter(prefix="/api/studio", tags=["live"])


def not_ready_live() -> HTTPException:
    return HTTPException(501, detail=dict(NOT_READY_LIVE))


class TestConnectionRequest(BaseModel):
    mode: str = Field("demo", pattern="^(demo|live)$", description="demo: OKX Demo Trading; live: tài khoản thật")


@router.get("/environments")
@router.get("/live/environments")
def get_environments() -> Dict[str, Any]:
    """Trạng thái từng môi trường: backtest sẵn sàng (Nautilus BacktestEngine); paper/testnet/live chưa chạy được (chờ TradingNode), `configured` = đã có khoá OKX."""
    return get_environments_status()


@router.post("/live/test_connection")
def post_test_connection(body: Optional[TestConnectionRequest] = None) -> Dict[str, Any]:
    """Kiểm tra kết nối OKX thật (không đặt lệnh). Không trả khoá, kể cả dạng che."""
    return test_okx_api_connection(mode=body.mode if body else "demo")


@router.post("/live/bot")
@router.get("/live/bot")
@router.get("/live/trades")
@router.get("/live/compare")
@router.get("/live/compare_events")
@router.get("/live/positions")
@router.get("/live/balance")
@router.get("/live/status")
@router.post("/live/order")
@router.post("/live/cancel")
def live_not_ready() -> Any:
    raise not_ready_live()


ROUTERS = [router]
