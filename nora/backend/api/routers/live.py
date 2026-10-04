"""Bot giao dịch theo sổ (/api/studio/live): khởi chạy job nền `live_bot` (OKX: paper | demo | live) và xem trạng thái (state.json + sự kiện).
Dừng bot: POST /api/studio/book/jobs/{job_id}/cancel (SIGTERM -> bot thoát sau bước hiện tại, trạng thái đã lưu)."""
import json
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.jobs import batch as batch_jobs

router = APIRouter(prefix="/api/studio/live", tags=["live"])


class BotRequest(BaseModel):
    mode: str = Field("paper", pattern="^(paper|demo|live)$",
                      description="paper: dữ liệu thật, khớp mô phỏng; demo: OKX Demo Trading (vốn ảo); live: OKX tài khoản thật")
    venue: str = Field("okx", pattern="^(okx|binance)$", description="okx = sàn triển khai; binance chỉ để tham khảo (paper / testnet)")
    once: bool = Field(False, description="chỉ chạy một bước (kiểm tra)")
    capital: float = Field(10000.0, gt=0, le=1e9, description="vốn ban đầu của chế độ paper")
    confirm_live: bool = Field(False, description="bắt buộc true với mode live (vốn thật)")
    book: str = Field("main", pattern="^(main|explore)$",
                      description="main = sổ đã kiểm định; explore = sổ thử nghiệm data/alphas/explore (chỉ paper/demo)")


def _running(venue: str, mode: str):
    return [j for j in batch_jobs.list_jobs(limit=50, kind="live_bot")
            if j.get("status") in ("running", "queued") and (j.get("params") or {}).get("mode") == mode
            and (j.get("params") or {}).get("venue", "okx") == venue]


@router.post("/bot")
def start_bot(req: BotRequest) -> Dict[str, Any]:
    if req.mode == "live" and not req.confirm_live:
        raise HTTPException(422, "mode live đặt lệnh bằng vốn thật — cần confirm_live=true")
    if req.mode == "live" and req.book == "explore":
        raise HTTPException(422, "sổ thử nghiệm không chạy live")
    if _running(req.venue, req.mode):
        raise HTTPException(409, f"bot {req.venue} {req.mode} đang chạy (job {_running(req.venue, req.mode)[0].get('id')})")
    return batch_jobs.http_launch("live_bot", {"mode": req.mode, "venue": req.venue, "once": req.once, "capital": req.capital,
                                               "confirm_live": req.confirm_live, "book": req.book})


@router.get("/bot")
def bot_status(mode: str = Query("paper", pattern="^(paper|demo|live)$"), venue: str = Query("okx", pattern="^(okx|binance)$"),
               events: int = Query(50, ge=0, le=500)) -> Dict[str, Any]:
    from backend.db.data_layout import cache_dir
    d = cache_dir(None, "live", f"{venue}_{mode}")
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
    return {"venue": venue, "mode": mode, "running": [j.get("id") for j in _running(venue, mode)], "state": state, "events": evs}


@router.get("/trades")
def bot_trades(mode: str = Query("paper", pattern="^(paper|demo|live)$"), venue: str = Query("okx", pattern="^(okx|binance)$"),
               limit: int = Query(200, ge=1, le=2000)) -> Dict[str, Any]:
    """Lệnh của bot để xem biểu đồ tín hiệu: lệnh sàn (demo/live: state.json) + lệnh paper (paper.pkl, cùng engine backtest), vị thế đang mở.
    Thời gian theo ms. book_kind cho biết sổ (main | explore) để gọi POST /api/studio/chart/explain (book + strategy_id)."""
    import pickle
    from backend.db.data_layout import cache_dir
    d = cache_dir(None, "live", f"{venue}_{mode}")
    state: Dict[str, Any] = {}
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    paper_trades, paper_pos = [], []
    try:
        with open(os.path.join(d, "paper.pkl"), "rb") as fh:
            pb = pickle.load(fh)
        paper_trades, paper_pos = list(pb.trades)[-limit:], pb.positions()
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError):
        pass
    exec_pos = [{"symbol": s, **p} for s, p in (state.get("positions") or {}).items()]
    kind = state.get("book_kind")
    if kind is None:                                   # trạng thái cũ chưa ghi book_kind: nhận theo generated_at của sổ thử nghiệm
        try:
            from backend.core.params.presets import alphas_dir
            with open(os.path.join(alphas_dir(), "explore", "book.json"), encoding="utf-8") as fh:
                kind = "explore" if json.load(fh).get("generated_at") == state.get("book") else "main"
        except (OSError, ValueError):
            kind = "main"
    return {"venue": venue, "mode": mode, "book_kind": kind, "running": [j.get("id") for j in _running(venue, mode)],
            "equity": state.get("equity"), "exec": {"trades": (state.get("trades") or [])[-limit:], "positions": exec_pos},
            "paper": {"trades": paper_trades, "positions": paper_pos, "summary": state.get("paper")}}
