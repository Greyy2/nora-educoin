"""Routes alpha: thư viện chiến lược (catalog + top agents), alpha người dùng, chiến lược hệ thống và soạn thảo (compile/annotate/assist), chạy thử
tuỳ chỉnh (custom backtest), giải thích biểu đồ, mẫu giáo dục. Logic nằm ở backend/strategies.py và backend/alpha/; file này chỉ validate + gọi."""
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend import strategies
from backend.routes import process as batch_jobs_routes
from backend.models.params import FRAMES, FRAME_MS
from backend.alpha import compile as dsl
from backend.jobs import runner as batch_jobs


alphas_router = APIRouter(prefix="/api/studio/alphas", tags=["alphas"])


@alphas_router.get("/catalog")
def get_alpha_catalog() -> Dict[str, Any]:
    return strategies.catalog()


@alphas_router.get("/top_agents")
def get_top_agents() -> Dict[str, Any]:
    return strategies.top_agents()


# ─── ALPHA NGƯỜI DÙNG (C1) ───────────────────────────────────────────────────

class SaveUserAlphaRequest(BaseModel):
    job_id: str = Field(..., description="Mã job custom_backtest đã hoàn tất")
    code: str = Field(..., description="Mã Python của chiến lược")
    name: str = Field(..., min_length=1, max_length=100, description="Tên alpha")
    note: Optional[str] = Field("", max_length=2000, description="Ghi chú chiến lược")
    source: Optional[str] = Field("alpha-create", description="Nguồn đẩy (alpha-create | education)")
    alpha_id: Optional[str] = Field(None, max_length=64, description="Có = lưu PHIÊN BẢN MỚI của alpha đã có (giữ id; bản cũ vào user/_versions)")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="Trạng thái mới: SAVED | CANDIDATE | ARCHIVED")


@alphas_router.post("/user")
def post_user_alpha(req: SaveUserAlphaRequest) -> Dict[str, Any]:
    """Đẩy chiến lược vào kho Alpha người dùng sau khi chạy backtest thành công."""
    try:
        record, action = strategies.save_user_alpha(
            job_id=req.job_id,
            code=req.code,
            name=req.name,
            note=req.note or "",
            source=req.source or "alpha-create",
            alpha_id=req.alpha_id,
        )
        return {
            "ok": True,
            "alpha_id": record["id"],
            "action": action,
            "version": record.get("version", 1),
            "status": record["status"],
            "checklist": record.get("checklist"),
            "record": record,
        }
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@alphas_router.get("/user")
def get_user_alphas(
    sort: Optional[str] = Query(None, description="Tiêu chí sắp xếp: date | sharpe | cagr"),
    status: Optional[str] = Query(None, description="Lọc trạng thái: SAVED | CANDIDATE | ARCHIVED"),
) -> List[Dict[str, Any]]:
    """Lấy danh sách các Alpha người dùng đã lưu."""
    return strategies.list_user_alphas(sort=sort, status=status)


def _load_samples():
    from backend.models.storage import alpha_education_samples
    return _read(alpha_education_samples()) or []


def _not_ready(what: str):
    return HTTPException(404, {"code": "NOT_READY", "message": f"Chưa có kết quả backtest thật cho {what} (chạy job education_warm)."})


@alphas_router.get("/user/{alpha_id}")
def get_user_alpha_detail(alpha_id: str) -> Dict[str, Any]:
    """Lấy chi tiết một Alpha người dùng hoặc chiến lược mẫu đã có kết quả."""
    rec = strategies.get_user_alpha(alpha_id)
    if not rec:
        # Fallback: mẫu giáo dục, CHỈ khi có kết quả thật trong cache
        sample_item = next((x for x in _load_samples() if x.get("key") == alpha_id or x.get("name") == alpha_id), None)
        s_res = strategies.sample_lookup(sample_item) if sample_item else None
        if s_res is not None:
            return {
                "id": alpha_id,
                "name": sample_item.get("name", alpha_id),
                "code": sample_item.get("code", ""),
                "config": s_res.get("config", {}),
                "metrics": s_res.get("metrics", {}),
                "result": s_res,
                "status": "SAVED",
                "version": 1,
            }
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rec


@alphas_router.get("/user/{alpha_id}/code")
def get_user_alpha_code(alpha_id: str) -> Dict[str, Any]:
    """Mã nguồn để nạp vào trình soạn tạm (sửa -> chạy lại -> Lưu thành phiên bản mới qua POST /user với alpha_id)."""
    import hashlib
    rec = strategies.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    code = rec.get("code") or ""
    return {"id": rec["id"], "code": code, "version": rec.get("version", 1), "program_hash": rec.get("program_hash"),
            "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "name": rec.get("name"), "note": rec.get("note", "")}


@alphas_router.get("/user/{alpha_id}/versions")
def get_user_alpha_versions(alpha_id: str) -> List[Dict[str, Any]]:
    rows = strategies.list_user_alpha_versions(alpha_id)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rows


@alphas_router.get("/user/{alpha_id}/versions/{version}")
def get_user_alpha_version(alpha_id: str, version: int) -> Dict[str, Any]:
    rec = strategies.get_user_alpha_version(alpha_id, version)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không có phiên bản {version} của alpha {alpha_id}")
    return rec


@alphas_router.post("/user/{alpha_id}/archive")
def post_archive_user_alpha(alpha_id: str) -> Dict[str, Any]:
    """Lưu trữ (archive) một Alpha người dùng (không xóa cứng)."""
    ok = strategies.update_user_alpha_status(alpha_id, "ARCHIVED")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": "ARCHIVED"}


@alphas_router.post("/user/{alpha_id}/status")
def post_update_user_alpha_status(alpha_id: str, req: UpdateStatusRequest) -> Dict[str, Any]:
    """Cập nhật trạng thái Alpha người dùng: SAVED | CANDIDATE | ARCHIVED."""
    if req.status not in ("SAVED", "CANDIDATE", "ARCHIVED"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ: phải là SAVED, CANDIDATE hoặc ARCHIVED")
    ok = strategies.update_user_alpha_status(alpha_id, req.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": req.status}


strategies_router = APIRouter(prefix="/api/studio/strategies", tags=["strategies"])


class ValidateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Khoá thiếu lấy từ preset")


@strategies_router.get("")
@strategies_router.get("/")
def get_strategies() -> List[Dict[str, Any]]:
    presets = strategies.load_presets()
    return [{"id": c["id"], "strategy": c.get("strategy"), "family": c["family"], "side": c["side"], "description": c["description"],
             "params_schema": c["params_schema"], "preset": presets[c["id"]], "frames_allowed": list(FRAMES)}
            for c in strategies.CANDIDATES]


@strategies_router.get("/catalog")
def get_strategy_catalog() -> List[Dict[str, Any]]:
    """3 chiến lược (KEMA / Sideway / DCA) và các chân theo chiều: legs = {LONG: id, SHORT: id}. Mỗi bộ tham số của một chân = một alpha;
    "Cả hai" = chạy cả hai chân. coming = chưa có chân nào (đang xây dựng)."""
    return strategies.STRATEGIES


@strategies_router.post("/validate")
def post_validate(req: ValidateRequest):
    cand = strategies.BY_ID.get(req.id)
    if cand is None:
        raise HTTPException(404, f"Không có chiến lược '{req.id}'; có: {[c['id'] for c in strategies.CANDIDATES]}")
    full, errors = strategies.validate_params(cand, req.params, strategies.load_presets()[req.id]["params"], "params")
    return {"ok": not errors, "errors": [{"field": f, "message": m} for f, m in errors], "resolved": None if errors else full}


@strategies_router.post("/presets")
def post_build_presets():
    """Dựng lại data/alpha/presets.json từ sổ đã chốt + lần dựng sổ mới nhất (job nền presets_build, không chạy backtest)."""
    return batch_jobs_routes.http_launch("presets_build", {})


class CompileRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")


@strategies_router.post("/compile")
def post_compile(req: CompileRequest) -> Dict[str, Any]:
    """Biên dịch thử (không chạy, không lưu): {ok, program_hash, meta{timeframe, features, legs, position_levels, warmup_bars, ...}, warnings[],
    error{line, col, message} | null}. Lỗi code trả 200 với ok=false (UI tô đúng dòng/cột)."""
    return dsl.compile_report(req.code)


class AnnotateRequest(CompileRequest):
    as_comments: bool = Field(False, description="Trả thêm annotated_code: giải thích chèn thành dòng `# ▸` trên từng dòng (idempotent)")
    strip: bool = Field(False, description="Chỉ gỡ các dòng `# ▸` tự sinh, trả {stripped_code}")


@strategies_router.post("/annotate")
def post_strategy_annotate(req: AnnotateRequest) -> Dict[str, Any]:
    """Giải thích từng dòng mã bằng tiếng Việt (trang /education), tất định từ AST + IR + catalog: {lines:[{line,end_line,kind,text_vi,refs}], verdict, style, kind,
    normalized_code, diagnostics}. Không chạy backtest, không dùng AI."""
    if req.strip:
        return {"stripped_code": dsl.strip_annotations(req.code)}
    return dsl.annotate_report(req.code, as_comments=req.as_comments)


class StrategyExplainRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")
    position: Optional[Dict[str, Any]] = Field(None, description="Tham số vị thế như khi chạy backtest")


@strategies_router.post("/explain")
def post_strategy_explain(req: StrategyExplainRequest) -> Dict[str, Any]:
    """Giải thích cấu trúc chiến lược từ cây biểu thức đã biên dịch (B2): {ok, indicators[], rules[], execution[], warnings[], error}."""
    return dsl.explain_report(req.code, position=req.position)


_DATA_DOC = {"open": "Giá mở cửa", "high": "Giá cao nhất", "low": "Giá thấp nhất", "close": "Giá đóng cửa", "volume": "Khối lượng"}


def _sig_param(p) -> str:
    from backend.signal.indicator import REQUIRED
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


@strategies_router.get("/dsl")
def get_dsl_reference() -> Dict[str, Any]:
    """Danh sách những gì DSL hỗ trợ (chỉ đọc): cột dữ liệu self.data.pv_*, chỉ báo self.feat.*, operator self.op.*."""
    from backend.signal import indicator as feat_mod, indicator as ops_mod
    from backend.signal.nodes import DATA_COLUMNS
    return {"data": [{"name": f"pv_{c}", "signature": f"self.data.pv_{c}", "doc": _DATA_DOC.get(c, c)} for c in DATA_COLUMNS],
            "features": _spec_rows(feat_mod.FEATURES, "self.feat"), "operators": _spec_rows(ops_mod.OPS, "self.op")}


# ─── P10: sửa tại chỗ + trợ lý viết code ─────────────────────────────────────

class SourcePut(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000)
    sha256: str = Field(..., min_length=64, max_length=64, description="sha256 của file lúc mở (khoá lạc quan)")


@strategies_router.get("/source/{strategy_id}")
def get_source(strategy_id: str) -> Dict[str, Any]:
    try:
        return dsl.read_source(strategy_id)
    except dsl.StrategyEditError as e:
        raise HTTPException(e.status, e.detail()) from None


@strategies_router.put("/source/{strategy_id}")
def put_source(strategy_id: str, req: SourcePut) -> Dict[str, Any]:
    try:
        out = dsl.write_source(strategy_id, req.code, req.sha256)
        strategies.reload_system_strategies()
        return out
    except dsl.StrategyEditError as e:
        raise HTTPException(e.status, e.detail()) from None


class AssistCheck(BaseModel):
    code: str = Field(..., max_length=60_000)


class AssistPos(BaseModel):
    code: str = Field(..., max_length=60_000)
    line: int = Field(..., ge=1)
    col: int = Field(..., ge=1)


@strategies_router.get("/assist/catalog")
def get_assist_catalog() -> Dict[str, Any]:
    from backend.alpha import contract
    return {k: v for k, v in contract.catalog().items() if not k.startswith("_")}


@strategies_router.post("/assist/check")
def post_assist_check(req: AssistCheck) -> Dict[str, Any]:
    from backend.alpha import contract
    res = contract.check_contract(req.code)
    ir = res.pop("ir", None)
    meta = None
    if ir is not None:
        meta = ir.meta() if res["kind"] == contract.KIND_ALPHA else {"strategy_id": ir["strategy"]["id"], "legs": [c["id"] for c in ir["candidates"]]}
    return {**res, "meta": meta}


@strategies_router.post("/assist/complete")
def post_assist_complete(req: AssistPos) -> Dict[str, Any]:
    from backend.alpha import contract
    return contract.complete(req.code, req.line, req.col)


@strategies_router.post("/assist/hover")
def post_assist_hover(req: AssistPos) -> Dict[str, Any]:
    from backend.alpha import contract
    return contract.hover(req.code, req.line, req.col)


custom_router = APIRouter(prefix="/api/studio/custom", tags=["custom"])


class CustomBacktestRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Mã Python class X(SimpleAlgorithm)")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="BTC hoặc BTC@perp; bỏ trống = cả 10 tài sản OKX trong kho dữ liệu")
    start: str
    end: str
    train_ratio: float = Field(0.7, ge=0.05, le=0.95)
    initial_capital: Optional[float] = Field(None, gt=0, le=1e9, description="Mặc định 10000")
    position: Optional[Dict[str, Any]] = Field(None, description="Ghi đè tham số vị thế (khoá của params.builder.POSITION_KEYS)")
    run_frame: Optional[str] = Field(None, pattern="^(1m|5m|15m|1h|4h|24h)$", description="Khung chạy; mặc định 1m")

    @field_validator("start", "end")
    @classmethod
    def _date(cls, v):
        return batch_jobs_routes.check_date(v)


@custom_router.get("/defaults")
def get_run_defaults() -> Dict[str, Any]:
    """Mặc định của form chạy, tính từ kho dữ liệu OKX: {symbols (rổ perp), start, end (phần dữ liệu chung), train_ratio, initial_capital}."""
    from backend.data.data import run_defaults
    try:
        return run_defaults()
    except ValueError as e:
        raise HTTPException(503, str(e))


@custom_router.post("/backtest")
def post_custom_backtest(req: CustomBacktestRequest) -> Dict[str, str]:
    """Khởi chạy job custom_backtest -> {"job_id"}. Lỗi code: 422 với thông điệp 'Lỗi biên dịch: dòng L, cột C: ...'."""
    try:
        params = batch_jobs_routes.build_job("custom_backtest", req.model_dump(exclude_none=True))
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    launched = batch_jobs_routes.http_launch("custom_backtest", params)
    return launched


chart_router = APIRouter(prefix="/api/studio/chart", tags=["chart"])
MAX_BARS = 5000          # nến tối đa trong cửa sổ trả về


class ChartExplainRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Za-z0-9]{2,12}(@perp)?$")
    start: int = Field(..., ge=0, description="ms, mở cửa sổ")
    end: int = Field(..., ge=0, description="ms, đóng cửa sổ")
    book: Optional[str] = Field(None, pattern="^(main|explore)$", description="sổ đang chạy (cùng strategy_id)")
    strategy_id: Optional[str] = Field(None, max_length=64)
    source: str = Field("data", pattern="^(data|okx)$")


def _load_book(kind: str) -> Dict[str, Any]:
    """Sổ main (READY_FOR_TESTNET) hoặc explore (EXPLORE_DEMO) từ data/alpha; không có / sai trạng thái -> 404."""
    from backend.models.storage import alpha_dir, alpha_file
    from backend.models.storage import read_json
    book = read_json(alpha_dir("explore", "book.json") if kind == "explore" else alpha_file("book"))
    want = "EXPLORE_DEMO" if kind == "explore" else "READY_FOR_TESTNET"
    if book is None or book.get("status") != want:
        raise HTTPException(404, f"chưa có sổ {kind} ở trạng thái {want}")
    return book


def _strategy(req: ChartExplainRequest):
    """-> (chiến lược đã materialize, khung chạy, thông tin hiển thị)."""
    from backend.models.params import materialize
    by = strategies.BY_ID
    if req.book and req.strategy_id:
        book = _load_book(req.book)
        item = next((s for s in book["strategies"] if s["id"] == req.strategy_id), None)
        if item is None:
            raise HTTPException(404, f"sổ {req.book} không có chiến lược {req.strategy_id}")
        params, tf, cid = item["params"], book.get("timeframe", "1m"), item["id"]
        src = {"book": req.book, "book_source": book.get("source"), "unvalidated": cid in (book.get("unvalidated") or [])}
    else:
        raise HTTPException(422, "cần book + strategy_id")
    if cid not in by:
        raise HTTPException(404, f"chiến lược {cid} không còn trong danh sách")
    params = {k: v for k, v in params.items() if k != "risk_per_trade_pct"}
    st = materialize(by[cid], strategies.lift_frames(by[cid], params, tf), risk_per_trade_pct=1.0, stop_fill="level")
    meta = {"id": cid, "side": by[cid]["side"], "family": by[cid].get("family"), "description": by[cid].get("description"),
            "params": params, **src}
    return st, tf, meta


def _frames(symbol: str, st: Dict[str, Any], tf: str) -> Dict[str, Any]:
    """Nến các khung cần cho chiến lược (toàn bộ lịch sử) từ catalog OKX — cùng nguồn với engine (data.load_candles, có cache)."""
    from backend.signal.compute import required_frames
    from backend.data.data import CatalogError, load_candles
    need = required_frames(symbol, [st], tf)
    out = {}
    for fr in need:
        try:
            hist = load_candles(symbol, fr)
        except (CatalogError, ValueError) as exc:
            raise HTTPException(404, f"chưa có dữ liệu {symbol} khung {fr} ({exc})")
        if hist.empty:
            raise HTTPException(404, f"chưa có dữ liệu {symbol} khung {fr}")
        out[fr] = hist
    return out


@chart_router.post("/explain")
def post_chart_explain(req: ChartExplainRequest) -> Dict[str, Any]:
    """Nến + chỉ báo + tín hiệu vào/thoát (kèm từng điều kiện và giá trị lúc đó) của một chiến lược trên một mã, trong cửa sổ [start, end]."""
    from backend.metrics.charts import explain
    if req.source == "okx":
        raise HTTPException(501, detail={"code": "NOT_READY", "message": "Nến OKX trực tiếp đang chuyển sang Nautilus TradingNode"})
    symbol = req.symbol.split("@")[0].upper()
    st, tf, meta = _strategy(req)
    start, end = int(req.start), int(req.end)
    if end <= start:
        raise HTTPException(422, "end phải sau start")
    if (end - start) // FRAME_MS[tf] > MAX_BARS:
        start = end - MAX_BARS * FRAME_MS[tf]
    frames = _frames(symbol, st, tf)
    try:
        out = explain(symbol, st, tf, frames, start, end)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**out, "strategy": meta, "source": req.source}


education_router = APIRouter(prefix="/api/studio/education", tags=["education"])
_KEY_RE = re.compile(r"^[a-z0-9_]{1,80}$")


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise HTTPException(500, "file dữ liệu hỏng")


@education_router.get("/samples")
def get_education_samples():
    """Danh sách mẫu giáo dục. Chỉ mẫu có kết quả backtest THẬT trong cache mới kèm metrics/final_equity/pnl_usd/initial_capital; còn lại result_status = NOT_READY."""
    samples = _load_samples()
    if not samples:
        raise HTTPException(404, "Không tìm thấy file mẫu education/samples.json")
    try:
        spec = strategies.sample_run_spec({})
    except ValueError:
        spec = None   # kho dữ liệu trống -> không mẫu nào có kết quả thật
    out = []
    for s in samples:
        item = dict(s)
        r = strategies.sample_lookup(s, strategies.sample_run_spec(s, spec)) if spec else None
        if r is None:
            item["result_status"] = "NOT_READY"
        else:
            item["metrics"] = r.get("metrics")
            init_cap = r.get("config", {}).get("initial_capital", spec.get("initial_capital"))
            fin_eq = r.get("final_equity")
            item["initial_capital"] = init_cap
            item["final_equity"] = fin_eq
            if fin_eq is not None and init_cap is not None:
                item["pnl_usd"] = round(fin_eq - init_cap, 2)
        out.append(item)
    return out


@education_router.get("/samples/{key}/result")
def get_education_sample_result(key: str):
    """Kết quả backtest thật (cache) của 1 mẫu; chưa có -> 404 NOT_READY."""
    sample = next((x for x in _load_samples() if x.get("key") == key), None)
    if sample is None:
        raise HTTPException(404, f"Không tìm thấy mẫu {key}")
    r = strategies.sample_lookup(sample)
    if r is None:
        raise _not_ready(f"mẫu {key}")
    return r


ROUTERS = [alphas_router, strategies_router, custom_router, education_router, chart_router]
