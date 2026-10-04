"""Bot giao dịch theo sổ (/api/studio/live): khởi chạy job nền `live_bot` (paper | testnet) và xem trạng thái (state.json + sự kiện cuối).
Dừng bot: POST /api/studio/book/jobs/{job_id}/cancel (SIGTERM -> bot thoát sau bước hiện tại, trạng thái đã lưu)."""
import json
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/studio/live", tags=["live"])


class BotRequest(BaseModel):
    mode: str = Field("paper", pattern="^(paper|testnet)$", description="paper: dữ liệu thật, khớp mô phỏng; testnet: lệnh thật trên testnet (cần khoá)")
    once: bool = Field(False, description="chỉ chạy một bước (kiểm tra)")
    capital: float = Field(10000.0, gt=0, le=1e9, description="vốn ban đầu của chế độ paper")


def _running(mode: str):
    return [j for j in batch_jobs.list_jobs(limit=50, kind="live_bot")
            if j.get("status") in ("running", "queued") and (j.get("params") or {}).get("mode") == mode]


@router.post("/bot")
def start_bot(req: BotRequest) -> Dict[str, Any]:
    if _running(req.mode):
        raise HTTPException(409, f"bot {req.mode} đang chạy (job {_running(req.mode)[0].get('id')})")
    return batch_jobs.http_launch("live_bot", {"mode": req.mode, "once": req.once, "capital": req.capital})


@router.get("/bot")
def bot_status(mode: str = Query("paper", pattern="^(paper|testnet)$"), events: int = Query(50, ge=0, le=500)) -> Dict[str, Any]:
    from backend.db.data_layout import cache_dir
    d = cache_dir(None, "live", mode)
    state, evs = None, []
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as fh:
            evs = [json.loads(x) for x in fh.readlines()[-events:]] if events else []
    except (OSError, ValueError):
        pass
    if state:
        state = {**state, "trades": (state.get("trades") or [])[-100:]}
    return {"mode": mode, "running": [j.get("id") for j in _running(mode)], "state": state, "events": evs}
