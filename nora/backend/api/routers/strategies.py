"""API chiến lược lõi + lược đồ tham số + bộ tham số tốt nhất (preset) cho chế độ Cơ bản / Nâng cao (docs/ui_contract.md §"Chế độ chạy").

GET  /api/studio/strategies           7 chiến lược lõi: params_schema (mọi tham số chỉnh được), preset {params, source, evidence}, frames_allowed.
POST /api/studio/strategies/validate  Kiểm thử tham số một chiến lược theo params_schema (không chạy job): {ok, errors[{field, message}], resolved}.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.params import presets as presets_mod
from backend.core.params import modes as rm
from backend.core.params.template import FRAMES
from backend.core.strategy.book import CANDIDATES

router = APIRouter(prefix="/api/studio/strategies", tags=["strategies"])


class ValidateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Khoá thiếu lấy từ preset")


@router.get("")
@router.get("/")
def get_strategies() -> List[Dict[str, Any]]:
    presets = presets_mod.load_presets()
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "params_schema": c["params_schema"], "preset": presets[c["id"]], "frames_allowed": list(FRAMES)}
            for c in CANDIDATES]


@router.post("/validate")
def post_validate(req: ValidateRequest):
    cand = next((c for c in CANDIDATES if c["id"] == req.id), None)
    if cand is None:
        raise HTTPException(404, f"Không có chiến lược '{req.id}'; có: {[c['id'] for c in CANDIDATES]}")
    full, errors = rm.validate_params(cand, req.params, presets_mod.load_presets()[req.id]["params"], "params")
    return {"ok": not errors, "errors": [{"field": f, "message": m} for f, m in errors], "resolved": None if errors else full}
