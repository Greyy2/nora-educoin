"""API chiến lược lõi + lược đồ tham số + bộ tham số tốt nhất (preset) cho chế độ Cơ bản / Nâng cao (docs/ui_contract.md §"Chế độ chạy").

GET  /api/studio/strategies           các chiến lược lõi: params_schema (mọi tham số chỉnh được), preset {params, source, evidence}, frames_allowed.
POST /api/studio/strategies/validate  Kiểm thử tham số một chiến lược theo params_schema (không chạy job): {ok, errors[{field, message}], resolved}.
POST /api/studio/strategies/compile   Biên dịch code Python (DSL SimpleAlgorithm, alpha/compile.compile_code; KHÔNG exec): {ok, program_hash, meta, warnings, error{line, col, message}}.
GET  /api/studio/strategies/dsl        Tham chiếu DSL chỉ đọc: {data[{name, doc}], features[{name, signature, doc, returns, outputs}], operators[...]} dựng từ core/indicator.py (spec).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.routes import jobs as batch_jobs
from backend.optimize.book import build as presets_mod
from backend.routes import modes as rm
from backend.core.params import FRAMES
from backend.alpha import compile as dsl

router = APIRouter(prefix="/api/studio/strategies", tags=["strategies"])


class ValidateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Khoá thiếu lấy từ preset")


@router.get("")
@router.get("/")
def get_strategies() -> List[Dict[str, Any]]:
    presets = presets_mod.load_presets()
    return [{"id": c["id"], "strategy": c.get("strategy"), "family": c["family"], "side": c["side"], "description": c["description"],
             "params_schema": c["params_schema"], "preset": presets[c["id"]], "frames_allowed": list(FRAMES)}
            for c in presets_mod.CANDIDATES]


@router.get("/catalog")
def get_catalog() -> List[Dict[str, Any]]:
    """3 chiến lược (KEMA / Sideway / DCA) và các chân theo chiều: legs = {LONG: id, SHORT: id}. Mỗi bộ tham số của một chân = một alpha;
    "Cả hai" = chạy cả hai chân. coming = chưa có chân nào (đang xây dựng)."""
    return presets_mod.STRATEGIES


@router.post("/validate")
def post_validate(req: ValidateRequest):
    cand = presets_mod.BY_ID.get(req.id)
    if cand is None:
        raise HTTPException(404, f"Không có chiến lược '{req.id}'; có: {[c['id'] for c in presets_mod.CANDIDATES]}")
    full, errors = rm.validate_params(cand, req.params, presets_mod.load_presets()[req.id]["params"], "params")
    return {"ok": not errors, "errors": [{"field": f, "message": m} for f, m in errors], "resolved": None if errors else full}


@router.post("/presets")
def post_build_presets():
    """Dựng lại data/alpha/presets.json từ sổ đã chốt + lần dựng sổ mới nhất (job nền presets_build, không chạy backtest)."""
    return batch_jobs.http_launch("presets_build", {})


class CompileRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")


@router.post("/compile")
def post_compile(req: CompileRequest) -> Dict[str, Any]:
    """Biên dịch thử (không chạy, không lưu): {ok, program_hash, meta{timeframe, features, legs, position_levels, warmup_bars, ...}, warnings[],
    error{line, col, message} | null}. Lỗi code trả 200 với ok=false (UI tô đúng dòng/cột)."""
    return dsl.compile_report(req.code)


class ExplainRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")
    position: Optional[Dict[str, Any]] = Field(None, description="Tham số vị thế như khi chạy backtest")


@router.post("/explain")
def post_explain(req: ExplainRequest) -> Dict[str, Any]:
    """Giải thích cấu trúc chiến lược từ cây biểu thức đã biên dịch (B2): {ok, indicators[], rules[], execution[], warnings[], error}."""
    return dsl.explain_report(req.code, position=req.position)



_DATA_DOC = {"open": "Giá mở cửa", "high": "Giá cao nhất", "low": "Giá thấp nhất", "close": "Giá đóng cửa", "volume": "Khối lượng"}


def _sig_param(p) -> str:
    from backend.core.indicator import REQUIRED
    return p.name if p.default is REQUIRED else f"{p.name}={p.default!r}"


def _spec_rows(specs: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    rows = []
    for name in sorted(specs):
        sp = specs[name]
        ret = sp.ret if isinstance(sp.ret, str) else "num"
        rows.append({
            "name": name,
            "signature": f"{prefix}.{name}({', '.join(_sig_param(p) for p in sp.params)})",
            "doc": sp.doc or "",
            "returns": ret,
            "outputs": sp.nout,
            "label_vi": sp.label_vi or "",
            "formula": sp.formula or "",
            "meaning_vi": sp.meaning_vi or "",
            "read_vi": sp.read_vi or "",
            "warmup": sp.warmup if isinstance(sp.warmup, (int, str)) else 0,
            "category": sp.category or "",
        })
    return rows



@router.get("/dsl")
def get_dsl_reference() -> Dict[str, Any]:
    """Danh sách những gì DSL hỗ trợ (chỉ đọc): cột dữ liệu self.data.pv_*, chỉ báo self.feat.*, operator self.op.*."""
    from backend.core import indicator as feat_mod, indicator as ops_mod
    from backend.core.signal import DATA_COLUMNS
    return {"data": [{"name": f"pv_{c}", "signature": f"self.data.pv_{c}", "doc": _DATA_DOC.get(c, c)} for c in DATA_COLUMNS],
            "features": _spec_rows(feat_mod.FEATURES, "self.feat"), "operators": _spec_rows(ops_mod.OPS, "self.op")}

