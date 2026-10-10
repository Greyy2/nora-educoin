"""Routes alpha (P11): viết, sửa, biên dịch, chạy thử, giải thích chiến lược, kho alpha người dùng, giáo dục.

Gộp từ: alphas.py, strategies.py, custom.py, chart.py, education.py.
"""
"""Thư viện chiến lược (/api/studio/alphas): mỗi chiến lược = ý tưởng + công thức bằng lời + công thức toán (ký hiệu) + thống kê alpha đã đạt, theo NGUỒN.

GET /api/studio/alphas/catalog  {"sources": [{"key": "nora", "label": "Nora", "strategies": [...]}]} — nguồn ngoài thêm sau cùng định dạng.
Dựng từ optimize/book/build.py (cây khuôn + params_schema) + data/alpha/book.json, explore/book.json qua optimize/book/registry.strategy_doc (đọc thuần).
Và kho Alpha người dùng (/api/studio/alphas/user).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.optimize.book import registry as strategy_doc, registry as top_agents, registry as user_alphas

alphas_router = APIRouter(prefix="/api/studio/alphas", tags=["alphas"])


@alphas_router.get("/catalog")
def get_alpha_catalog() -> Dict[str, Any]:
    return strategy_doc.catalog()


@alphas_router.get("/top_agents")
def get_top_agents() -> Dict[str, Any]:
    return top_agents.top_agents()


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
        record, action = user_alphas.save_user_alpha(
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
    return user_alphas.list_user_alphas(sort=sort, status=status)


@alphas_router.get("/user/{alpha_id}")
def get_user_alpha_detail(alpha_id: str) -> Dict[str, Any]:
    """Lấy chi tiết một Alpha người dùng."""
    rec = user_alphas.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rec


@alphas_router.get("/user/{alpha_id}/code")
def get_user_alpha_code(alpha_id: str) -> Dict[str, Any]:
    """Mã nguồn để nạp vào trình soạn tạm (sửa -> chạy lại -> Lưu thành phiên bản mới qua POST /user với alpha_id)."""
    import hashlib
    rec = user_alphas.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    code = rec.get("code") or ""
    return {"id": rec["id"], "code": code, "version": rec.get("version", 1), "program_hash": rec.get("program_hash"),
            "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "name": rec.get("name"), "note": rec.get("note", "")}


@alphas_router.get("/user/{alpha_id}/versions")
def get_user_alpha_versions(alpha_id: str) -> List[Dict[str, Any]]:
    rows = user_alphas.list_user_alpha_versions(alpha_id)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rows


@alphas_router.get("/user/{alpha_id}/versions/{version}")
def get_user_alpha_version(alpha_id: str, version: int) -> Dict[str, Any]:
    rec = user_alphas.get_user_alpha_version(alpha_id, version)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không có phiên bản {version} của alpha {alpha_id}")
    return rec


@alphas_router.post("/user/{alpha_id}/archive")
def post_archive_user_alpha(alpha_id: str) -> Dict[str, Any]:
    """Lưu trữ (archive) một Alpha người dùng (không xóa cứng)."""
    ok = user_alphas.update_user_alpha_status(alpha_id, "ARCHIVED")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": "ARCHIVED"}


@alphas_router.post("/user/{alpha_id}/status")
def post_update_user_alpha_status(alpha_id: str, req: UpdateStatusRequest) -> Dict[str, Any]:
    """Cập nhật trạng thái Alpha người dùng: SAVED | CANDIDATE | ARCHIVED."""
    if req.status not in ("SAVED", "CANDIDATE", "ARCHIVED"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ: phải là SAVED, CANDIDATE hoặc ARCHIVED")
    ok = user_alphas.update_user_alpha_status(alpha_id, req.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": req.status}



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 2: CHIẾN LƯỢC HỆ THỐNG VÀ SOẠN THẢO (gộp từ strategies.py)
# ══════════════════════════════════════════════════════════════════════════

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.routes import process as batch_jobs
from backend.optimize.book import build as presets_mod
from backend.routes import process as rm
from backend.core.params import FRAMES
from backend.alpha import compile as dsl

strategies_router = APIRouter(prefix="/api/studio/strategies", tags=["strategies"])


class ValidateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Khoá thiếu lấy từ preset")


@strategies_router.get("")
@strategies_router.get("/")
def get_strategies() -> List[Dict[str, Any]]:
    presets = presets_mod.load_presets()
    return [{"id": c["id"], "strategy": c.get("strategy"), "family": c["family"], "side": c["side"], "description": c["description"],
             "params_schema": c["params_schema"], "preset": presets[c["id"]], "frames_allowed": list(FRAMES)}
            for c in presets_mod.CANDIDATES]


@strategies_router.get("/catalog")
def get_strategy_catalog() -> List[Dict[str, Any]]:
    """3 chiến lược (KEMA / Sideway / DCA) và các chân theo chiều: legs = {LONG: id, SHORT: id}. Mỗi bộ tham số của một chân = một alpha;
    "Cả hai" = chạy cả hai chân. coming = chưa có chân nào (đang xây dựng)."""
    return presets_mod.STRATEGIES


@strategies_router.post("/validate")
def post_validate(req: ValidateRequest):
    cand = presets_mod.BY_ID.get(req.id)
    if cand is None:
        raise HTTPException(404, f"Không có chiến lược '{req.id}'; có: {[c['id'] for c in presets_mod.CANDIDATES]}")
    full, errors = rm.validate_params(cand, req.params, presets_mod.load_presets()[req.id]["params"], "params")
    return {"ok": not errors, "errors": [{"field": f, "message": m} for f, m in errors], "resolved": None if errors else full}


@strategies_router.post("/presets")
def post_build_presets():
    """Dựng lại data/alpha/presets.json từ sổ đã chốt + lần dựng sổ mới nhất (job nền presets_build, không chạy backtest)."""
    return batch_jobs.http_launch("presets_build", {})


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



@strategies_router.get("/dsl")
def get_dsl_reference() -> Dict[str, Any]:
    """Danh sách những gì DSL hỗ trợ (chỉ đọc): cột dữ liệu self.data.pv_*, chỉ báo self.feat.*, operator self.op.*."""
    from backend.core import indicator as feat_mod, indicator as ops_mod
    from backend.core.signal import DATA_COLUMNS
    return {"data": [{"name": f"pv_{c}", "signature": f"self.data.pv_{c}", "doc": _DATA_DOC.get(c, c)} for c in DATA_COLUMNS],
            "features": _spec_rows(feat_mod.FEATURES, "self.feat"), "operators": _spec_rows(ops_mod.OPS, "self.op")}




# ─── P10: sửa tại chỗ + trợ lý viết code ─────────────────────────────────────

class SourcePut(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000)
    sha256: str = Field(..., min_length=64, max_length=64, description="sha256 của file lúc mở (khoá lạc quan)")


def _live_bot_guard(removed: List[str]) -> None:
    if not removed:
        return
    from backend.optimize.process import process as jobs_store
    active = [j for j in jobs_store.list_jobs(limit=50, kind="live_bot") if j.get("status") in ("running", "queued")]
    if not active:
        return
    used = set()
    for j in active:
        p = j.get("params") or {}
        if p.get("strategy"):
            used.add(p["strategy"])
        book_id = p.get("book") or "main"
        try:
            from backend.optimize.book.build import load_book
            b = load_book(book_id)
            for c in b.get("candidates", []):
                used.add(c.get("strategy") or c.get("id"))
                used.add(c.get("id"))
        except Exception:
            pass
    conflict = [rid for rid in removed if rid in used]
    if conflict:
        raise dsl.StrategyEditError(409, "LIVE_BOT_RUNNING", f"Bot live đang chạy sử dụng chiến lược/chân {conflict}: không được đổi tên/bỏ id này. Dừng bot rồi sửa, hoặc giữ nguyên id.", removed=conflict)


@strategies_router.get("/source/{strategy_id}")
def get_source(strategy_id: str) -> Dict[str, Any]:
    try:
        return dsl.read_source(strategy_id)
    except dsl.StrategyEditError as e:
        raise HTTPException(e.status, e.detail()) from None


@strategies_router.put("/source/{strategy_id}")
def put_source(strategy_id: str, req: SourcePut) -> Dict[str, Any]:
    try:
        out = dsl.write_source(strategy_id, req.code, req.sha256, guard=_live_bot_guard)
        presets_mod.reload_system_strategies()
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


# ══════════════════════════════════════════════════════════════════════════
# PHẦN 3: BACKTEST TỰ CHỌN (gộp từ custom.py)
# ══════════════════════════════════════════════════════════════════════════

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.optimize.process import process as batch_jobs
from backend.routes import process as batch_jobs_routes

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
    from backend.crawl.store import run_defaults
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



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 4: GIẢI THÍCH BIỂU ĐỒ (gộp từ chart.py)
# ══════════════════════════════════════════════════════════════════════════

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.params import FRAME_MS

chart_router = APIRouter(prefix="/api/studio/chart", tags=["chart"])
MAX_BARS = 5000          # nến tối đa trong cửa sổ trả về
OKX_LIMIT = 1500         # như bot: đủ khởi động chỉ báo (signals khớp engine với 1500 nến)


class ChartExplainRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Za-z0-9]{2,12}(@perp)?$")
    start: int = Field(..., ge=0, description="ms, mở cửa sổ")
    end: int = Field(..., ge=0, description="ms, đóng cửa sổ")
    run_id: Optional[str] = Field(None, max_length=64, description="alpha của lượt phễu (cùng alpha_id)")
    alpha_id: Optional[str] = Field(None, pattern=r"^[0-9a-f]{16}$")
    book: Optional[str] = Field(None, pattern="^(main|explore)$", description="sổ đang chạy (cùng strategy_id)")
    strategy_id: Optional[str] = Field(None, max_length=64)
    source: str = Field("data", pattern="^(data|okx)$")


def _strategy(req: ChartExplainRequest):
    """-> (chiến lược đã materialize, khung chạy, thông tin hiển thị)."""
    from backend.optimize.book.build import lift_frames
    from backend.core.params import materialize
    from backend.optimize.book.build import BY_ID
    by = BY_ID
    if req.run_id and req.alpha_id:
        from backend.routes.optimize import open_run
        from backend.optimize.search.generate import split_regime
        st = open_run(req.run_id)
        try:
            al = st.get_alpha(req.alpha_id)
            tf = (st.read_run().get("config") or {}).get("timeframe", "1m")
        finally:
            st.close()
        if al is None:
            raise HTTPException(404, f"không có alpha {req.alpha_id}")
        params, regime = split_regime(al["params"])
        cid, src = al["strategy"], {"run_id": req.run_id, "alpha_id": req.alpha_id, "regime": regime}
    elif req.book and req.strategy_id:
        from backend.live.live import load_book
        try:
            book = load_book(kind=req.book, mode="paper")
        except (SystemExit, OSError) as e:
            raise HTTPException(404, str(e))
        item = next((s for s in book["strategies"] if s["id"] == req.strategy_id), None)
        if item is None:
            raise HTTPException(404, f"sổ {req.book} không có chiến lược {req.strategy_id}")
        params, regime, tf, cid = item["params"], None, book.get("timeframe", "1m"), item["id"]
        src = {"book": req.book, "book_source": book.get("source"), "unvalidated": cid in (book.get("unvalidated") or [])}
    else:
        raise HTTPException(422, "cần (run_id + alpha_id) hoặc (book + strategy_id)")
    if cid not in by:
        raise HTTPException(404, f"chiến lược {cid} không còn trong danh sách")
    params = {k: v for k, v in params.items() if k != "risk_per_trade_pct"}
    st = materialize(by[cid], lift_frames(by[cid], params, tf), risk_per_trade_pct=1.0, stop_fill="level")
    meta = {"id": cid, "side": by[cid]["side"], "family": by[cid].get("family"), "description": by[cid].get("description"),
            "params": params, **src}
    return st, tf, meta


_FRAME_CACHE = None     # ByteLRU nến thô đọc từ pkl, khoá (đường dẫn, mtime_ns, size); engine copy khi _prepare_candles nên dùng chung được


def _read_frame(path: str):
    """pd.read_pickle có đệm theo mtime/size (explain nào cũng nạp lại cả file nến). Không có file -> None. Ngân sách: NORA_CHART_CACHE_MB (256)."""
    global _FRAME_CACHE
    import pandas as pd
    try:
        st = os.stat(path)
    except OSError:
        return None
    if _FRAME_CACHE is None:
        from backend.crawl.store import ByteLRU, env_mb
        _FRAME_CACHE = ByteLRU(env_mb("NORA_CHART_CACHE_MB", 256))
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _FRAME_CACHE.get(key)
    if hit is not None:
        return hit
    df = pd.read_pickle(path)
    try:
        nbytes = int(df.memory_usage(index=True, deep=False).sum())
    except Exception:
        nbytes = st.st_size * 4
    _FRAME_CACHE.put(key, df, nbytes)
    return df


_OKX = None             # một adapter dùng chung: bộ đệm nến theo (mã, khung) -> lần sau chỉ 1 request /candles mỗi khung


def _okx():
    global _OKX
    if _OKX is None:
        from backend.live.live import OkxAdapter
        _OKX = OkxAdapter(None, demo=False)
    return _OKX


def _frames(symbol: str, st: Dict[str, Any], tf: str, source: str) -> Dict[str, Any]:
    """data: kho nến của sàn đang dùng (toàn bộ lịch sử). okx: kho nến + nến OKX mới nhất nối vào sau (lệnh live gần đây)."""
    import time
    import pandas as pd
    from backend.crawl.store import market_dir
    from backend.core.backtest import klines_frame, required_frames
    need = required_frames(symbol, [st], tf)
    root = market_dir(venue="cex", symbol=symbol, instrument="perp")
    now = int(time.time() * 1000)
    out = {}
    for fr in need:
        path = os.path.join(root, f"{fr}.pkl")
        hist = _read_frame(path)
        if source == "okx":
            last = int(hist["open_time"].iloc[-1]) if hist is not None and len(hist) else 0
            gap = (now - last) // FRAME_MS[fr] + 3 if last else OKX_LIMIT
            live = klines_frame(_okx().klines(symbol, fr, int(min(max(gap, 10), OKX_LIMIT)), now), now)
            if hist is not None:
                live = pd.concat([hist[[c for c in live.columns if c in hist.columns]], live], ignore_index=True)
                live = live.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
            hist = live
        if hist is None:
            raise HTTPException(404, f"chưa có dữ liệu {symbol} khung {fr} ({path})")
        out[fr] = hist
    return out


@chart_router.post("/explain")
def post_chart_explain(req: ChartExplainRequest) -> Dict[str, Any]:
    """Nến + chỉ báo + tín hiệu vào/thoát (kèm từng điều kiện và giá trị lúc đó) của một chiến lược trên một mã, trong cửa sổ [start, end]."""
    from backend.metrics.charts import explain
    symbol = req.symbol.split("@")[0].upper()
    st, tf, meta = _strategy(req)
    start, end = int(req.start), int(req.end)
    if end <= start:
        raise HTTPException(422, "end phải sau start")
    if (end - start) // FRAME_MS[tf] > MAX_BARS:
        start = end - MAX_BARS * FRAME_MS[tf]
    frames = _frames(symbol, st, tf, req.source)
    try:
        out = explain(symbol, st, tf, frames, start, end)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**out, "strategy": meta, "source": req.source}



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 5: GIÁO DỤC VÀ MẪU ĐỊNH LƯỢNG (gộp từ education.py)
# ══════════════════════════════════════════════════════════════════════════

import json
import os
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    """Trả về 50 mẫu chiến lược giáo dục chuẩn từ data/alpha/education/samples.json."""
    from backend.crawl.store import alpha_education_samples
    samples_path = alpha_education_samples()
    data = _read(samples_path)
    if data is None:
        raise HTTPException(404, "Không tìm thấy file mẫu education/samples.json")
    return data





ROUTERS = [alphas_router, strategies_router, custom_router, education_router, chart_router]
