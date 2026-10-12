"""Routes tối ưu hoá (P11): phễu kiểm duyệt, dựng sổ alpha, danh mục đầu tư.

Gộp từ: book.py, portfolio.py, funnel.py.
"""
"""API sổ chiến lược (strategy book): xem sổ hiện tại + chạy backtest danh mục / WFA danh mục / dựng sổ như job nền.

Job nặng chạy ở tiến trình riêng qua ops/run_limited.sh (xem backend/optimize/process/process.py), handler ở đây chỉ
khởi chạy / đọc file nên nhanh và là `def` thường (FastAPI chạy trong threadpool).
"""
import json
import math
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.routes import process as modes
from backend.optimize.process import process as batch_jobs
from backend.routes import process as batch_jobs_routes
from backend.crawl.store import alpha_dir, alpha_file
from backend.nautilus.engine import provenance as engine_provenance
from backend.routes.process import STRESS_VERTICAL
from backend.carlo.carlo import with_gate_thresholds, MC_MAX_RUIN_PCT as MC_RUIN_MAX_PCT, MC_MAX_SIMULATIONS, MC_MIN_SIMULATIONS, MC_RUIN_THRESHOLD_PCT, STRESS_MAX_MDD_PCT, STRESS_SCENARIOS

book_router = APIRouter(prefix="/api/studio/book", tags=["book"])
alphas_router = APIRouter(prefix="/api/studio", tags=["book"])

MC_MIN_DAYS, MC_MAX_DAYS = 20, 5000
from backend.optimize.book.build import _metrics   # P9.6: MỘT định nghĩa (build.py), cùng khoá/logic


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
MODE_FIELD = dict(pattern="^(basic|advanced)$", description="basic: máy chủ BỎ QUA tham số client, dùng preset (data/alpha/presets.json); "
                                                          "advanced: kiểm mọi tham số theo params_schema (xem docs/ui_contract.md §\"Chế độ chạy\")")


class StrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Chỉ dùng ở mode=advanced: khoá theo params_schema (số hoặc khung thời gian \"4h\"); "
                                                                      "thiếu khoá nào lấy từ preset. mode=basic: bỏ qua")


class _DateRange(BaseModel):
    @field_validator("start", "end", check_fields=False)
    @classmethod
    def _date(cls, v):
        return batch_jobs_routes.check_date(v) if v else v


class BacktestRequest(_DateRange):
    strategies: Optional[List[StrategyIn]] = Field(None, max_length=16, description="Bỏ trống = dùng data/alpha/book.json")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ (perp). Tài sản DEX bị từ chối 501 NOT_READY (Nautilus không hỗ trợ AMM)")
    start: str
    end: str
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    stop_fill: str = Field("level", pattern="^(level|extreme)$")
    regime: bool = Field(False, description="Bật lọc regime + cầu chì (regime/regime.py, core/params.py REGIME_MAP)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    mode: str = Field("basic", **MODE_FIELD)
    data: str = Field("candle", pattern="^(candle|tick)$", description="candle: nến; tick: 501 NOT_READY (backtest tick/AMM chỉ dành cho DEX, Nautilus không hỗ trợ)")
    latency_ms: Optional[int] = Field(None, ge=0, le=3_600_000, description="Chỉ data=tick: trễ từ lúc nến đóng tới lúc bot hành động; bỏ trống = thời gian một block của mạng")
    gas_usd: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Chỉ data=tick: gas mỗi swap (USD); bỏ trống = cấu hình của mạng")


class WfaStrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    configs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=batch_jobs_routes.MAX_WFA_CONFIGS,
                                          description="1 cấu hình = tham số cố định (WFA chỉ kiểm OOS cuộn); mode=basic: bỏ qua, dùng preset")


class WfaRequest(_DateRange):
    report_dir: Optional[str] = Field(None, max_length=256, description="Lần chạy build_strategy_book trong data/alpha/book/")
    include_rejected: bool = False
    candidates: Optional[List[str]] = Field(None, max_length=16)
    strategies: Optional[List[WfaStrategyIn]] = Field(None, max_length=batch_jobs_routes.MAX_WFA_STRATEGIES,
                                                       description="Cấu hình do người dùng chọn: dùng ĐÚNG các cấu hình này")
    symbols: Optional[List[str]] = Field(None, max_length=16)
    n: int = Field(3, ge=1, le=50)
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = Field(None, ge=7, le=1000)
    test_days: Optional[int] = Field(None, ge=1, le=365)
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    mode: str = Field("basic", **MODE_FIELD)
    step_days: Optional[int] = Field(None, ge=1, le=365, description="Chỉ advanced: bước trượt fold (mặc định = test_days)")
    embargo_days: Optional[int] = Field(None, ge=0, le=30, description="Chỉ advanced: chưa hỗ trợ (>0 -> 422)")
    sims: Optional[int] = Field(None, ge=100, le=MC_MAX_SIMULATIONS, description="Chỉ advanced: số kịch bản MC của gate WFA; < 10.000 -> custom_gates")
    mc_seed: Optional[int] = Field(None, ge=0, le=2**31 - 1)
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    regime: str = Field("off", pattern="^(off|learn)$",
                        description="learn: mỗi fold học bảng regime ↔ chiến lược trên train rồi áp lên test (regime/regime.learn_map)")

    @model_validator(mode="after")
    def _one_source(self):
        if sum(map(bool, (self.report_dir, self.candidates, self.strategies))) != 1:
            raise ValueError("chọn đúng một: report_dir, candidates hoặc strategies")
        return self


class McRequest(BaseModel):
    wfa_job_id: Optional[str] = Field(None, max_length=64, description="Job book_wfa đã xong (lấy chuỗi lợi suất ngày OOS)")
    daily_returns: Optional[List[float]] = Field(None, min_length=MC_MIN_DAYS, max_length=MC_MAX_DAYS,
                                                 description="Lợi suất ngày dạng số thập phân (0.01 = 1%)")
    basis: str = Field("extreme", pattern="^(extreme|level)$", description="Cơ sở chuỗi lợi suất ngày OOS của job WFA: extreme (điểm xấu nhất trong ngày) hoặc level (đóng cửa ngày)")
    simulations: int = Field(MC_MIN_SIMULATIONS, ge=100, le=MC_MAX_SIMULATIONS,
                             description="Số kịch bản bootstrap; < 10.000 vẫn chạy nhưng gate.gate_eligible = false (không dùng làm gate); tối đa 50.000")
    block_days: int = Field(5, ge=1, le=30, description="Độ dài khối bootstrap (số ngày liên tiếp mỗi lần lấy mẫu)")
    horizon_days: int = Field(365, ge=5, le=730, description="Chân trời mô phỏng: số ngày của mỗi kịch bản")
    ruin_threshold_pct: float = Field(MC_RUIN_THRESHOLD_PCT, gt=0.0, le=100.0, description="Ngưỡng phá sản: một đường mô phỏng tính là cháy khi MDD >= ngưỡng này (%)")
    seed: int = Field(7, ge=0, le=2**31 - 1, description="Hạt giống ngẫu nhiên (cùng seed cho cùng kết quả)")
    scale: float = Field(1.0, gt=0.0, le=10.0, description="Hệ số nhân lên chuỗi lợi suất ngày (kích cỡ vị thế)")
    stress_max_mdd_pct: float = Field(STRESS_MAX_MDD_PCT, gt=0.0, le=100.0, description="MDD tối đa cho phép của MỌI kịch bản cực xấu (gate)")
    extra_cost_daily_pct: Optional[float] = Field(None, ge=0.0, le=5.0,
                                                  description="Phí bổ sung (%/ngày hoạt động) cho kịch bản cost_x2; bỏ trống = hằng số bảo thủ 0,07%")
    mode: str = Field("basic", **MODE_FIELD)
    stress_scenarios: Optional[List[str]] = Field(None, max_length=len(STRESS_SCENARIOS), description="Chỉ advanced: tập con kịch bản cực xấu (mặc định đủ cả); thiếu -> custom_gates")

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.wfa_job_id) == bool(self.daily_returns):
            raise ValueError("chọn đúng một: wfa_job_id hoặc daily_returns")
        return self


class PublishRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64, description="Job book_build đã xong và có sổ dựng (book.json)")


class BuildRequest(BaseModel):
    only: Optional[List[str]] = Field(None, max_length=16)
    n: Optional[int] = Field(None, ge=1, le=batch_jobs_routes.MAX_BUILD_CONFIGS,
                             description="Số cấu hình thử mỗi chiến lược ở dev1 (mặc định 24). Tổng > 200.000 cần force_large")
    keep_top: Optional[int] = Field(None, ge=3, le=5000, description="Số hàng tốt nhất mỗi chiến lược giữ trong kết quả (mặc định 50)")
    force_large: bool = Field(False, description="Cho phép tổng số cấu hình vượt trần 200.000 của CLI (--force-large)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")


# ─── Đọc sổ / báo cáo ───────────────────────────────────────────────────────
def book_path() -> str:
    """Sổ đang dùng (crawl.store.alpha_file: alpha/book.json; NORA_BOOK_PATH / NORA_ALPHAS_DIR ghi đè)."""
    return alpha_file("book")




def _evidence_summary(ev: Dict[str, Any]) -> Dict[str, Any]:
    top = (ev.get("dev1_top") or [{}])[0]
    return {"accepted": ev.get("accepted"), "stability": ev.get("stability"), "dev1_tried": ev.get("dev1_tried"),
            "dev1": _metrics(top.get("dev1")), "dev2_level": _metrics(top.get("dev2_level")),
            "dev2_extreme": _metrics(top.get("dev2_extreme"))}


def _book_summary(book: Dict[str, Any]) -> Dict[str, Any]:
    final = (book.get("evidence") or {}).get("final") or {}
    return {
        "status": book.get("status"), "holdout_pass": book.get("holdout_pass"), "generated_at": book.get("generated_at"),
        "source": book.get("source"), "code": book.get("code"), "universe": book.get("universe"), "windows": book.get("windows"),
        "risk": book.get("risk"), "risk_per_trade_pct": book.get("risk_per_trade_pct"),
        "strategies": [{"id": s["id"], "family": s.get("family"), "side": s.get("side"), "description": s.get("description"),
                        "params": s.get("params"), "evidence": _evidence_summary(s.get("evidence") or {})}
                       for s in book.get("strategies", [])],
        "evidence": {k: _metrics(v) for k, v in final.items()},
        "rejected_candidates": sorted((book.get("rejected_candidates") or {})),
    }


def latest_wfa_summary() -> Optional[Dict[str, Any]]:
    from backend.crawl.store import run_dir
    base = run_dir("wfa")
    for name in sorted(os.listdir(base) if os.path.isdir(base) else (), reverse=True):
        path = os.path.join(base, name, "report.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        s = r.get("summary") or {}
        return {
            "report_dir": name, "window": r.get("window"), "config": r.get("config"), "risk_per_trade_pct": r.get("risk_per_trade_pct"),
            "candidates": [{"id": c.get("id"), "configs": len(c.get("configs") or [])} for c in r.get("candidates") or []],
            "gate": r.get("gate"), "source": r.get("source"),
            "summary": {k: s.get(k) for k in ("n_folds", "n_traded_folds", "positive_folds", "positive_ratio_pct", "avg_is_ret_pct",
                                              "compounded_oos_ret_pct", "worst_fold_mdd_pct", "oos_days", "oos_trades", "mc")},
        }
    return None


def default_params(space: Dict[str, List[Any]]) -> Dict[str, Any]:
    """Giá trị GIỮA của mỗi khoá trong không gian tham số (cùng quy tắc backend/optimize/search/evaluate._mid_params)."""
    return {k: v[len(v) // 2] for k, v in space.items()}


def _assets() -> List[Dict[str, Any]]:
    """Tài sản có dữ liệu: [{symbol, venue cex, market perp, candles{start_ts,end_ts}, ticks null}]. DEX/AMM không được Nautilus hỗ trợ nên không được đưa ra (dữ liệu DEX vẫn nằm trong kho)."""
    from backend.crawl.store import list_assets, manifest_of_dir
    out = []
    for it in list_assets():
        if it["venue"] != "cex":
            continue
        manifest = manifest_of_dir(it["path"]) or {}
        out.append({"symbol": it["symbol"], "venue": "cex", "market": "perp" if it["instrument"] == "perp" else "spot",
                    "candles": {"start_ts": manifest.get("start_ts"), "end_ts": manifest.get("end_ts")}, "ticks": None})
    return out


def _catalog() -> List[Dict[str, Any]]:
    from backend.optimize.book.build import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"], "default_params": default_params(c["space"])} for c in CANDIDATES]


def _universe_windows(book: Optional[Dict[str, Any]]):
    """(universe, windows dạng ngày): lấy từ sổ nếu có, không thì từ vũ trụ + dữ liệu hiện có (như build_strategy_book.windows)."""
    from backend.optimize.book.build import perp_symbols
    universe = (book or {}).get("universe") or perp_symbols()
    windows = (book or {}).get("windows")
    if not windows:
        try:
            import pandas as pd
            from backend.crawl.store import read_manifest
            ms = [read_manifest(s) for s in universe]
            start = max(int(m["start_ts"]) for m in ms) + 20 * 86_400_000
            end = min(int(m["end_ts"]) for m in ms)
            span = end - start
            fmt = lambda t: f"{pd.Timestamp(int(t), unit='ms'):%Y-%m-%d}"
            windows = {"start": fmt(start), "dev1_end": fmt(start + int(span * 0.4)), "dev2_end": fmt(start + int(span * 0.8)),
                       "end": fmt(end)}
        except (TypeError, ValueError, KeyError):   # thiếu dữ liệu/manifest
            windows = None
    return universe, windows


# ─── Điểm cuối ──────────────────────────────────────────────────────────────
@book_router.get("/")
def get_book():
    book, raw = None, None
    path = book_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            book = _book_summary(raw)
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(500, f"book.json hỏng: {e}")
    wfa = latest_wfa_summary()
    universe, windows = _universe_windows(raw)
    # "wfa" giữ cho client cũ; "latest_wfa" + "catalog" theo docs/ui_contract.md §1 ("candidates" cũng giữ nguyên)
    catalog = _catalog()
    return {"book": book, "wfa": wfa, "latest_wfa": wfa, "candidates": catalog, "catalog": catalog,
            "universe": universe, "windows": windows, "assets": _assets()}


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"{os.path.basename(path)} hỏng: {e}")


_STATUS_LABEL = {"validated": "đã kiểm lại, đạt", "retired": "đã nghỉ hưu (kiểm lại không đạt cổng)"}


def registry_provenance(reg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mỗi alpha của registry: trạng thái (retired / validated / None = chưa từng kiểm lại bằng engine hiện hành) + lý do + ghi chú NGUỒN GỐC
    (commit/sàn dữ liệu/lượt tối ưu lúc dựng, và registry có engine_version hay không). Giao diện chỉ hiển thị — không tự suy ra gì (P9.14)."""
    from backend.optimize.book.registry import book_engine_status
    if not reg:
        return []
    eng = book_engine_status(reg)
    code = reg.get("code") or {}
    out = []
    for a in (x for x in reg.get("alphas") or [] if isinstance(x, dict)):
        rv = a.get("revalidation") or {}
        status = a.get("status")
        data = a.get("data") or {}
        bits = [f"registry dựng {'ở commit ' + str(code['commit'])[:7] if code.get('commit') else 'không rõ commit'}"
                + (" (có sửa đổi backend chưa commit)" if code.get("dirty_backend") else ""),
                f"dữ liệu sàn {data['exchange']}" if data.get("exchange") else "không ghi sàn dữ liệu"]
        if reg.get("source_optimization"):
            bits.append(f"từ lượt tối ưu {os.path.basename(str(reg['source_optimization']))}")
        if eng["needs_rebuild"]:
            bits.append(eng["reason"])
        out.append({"alpha_id": a.get("alpha_id"), "status": status, "status_label": _STATUS_LABEL.get(status) if status else None,
                    "status_note": (rv.get("reason") or None) if status else "chưa kiểm lại bằng engine hiện hành",
                    "checked_at": rv.get("checked_at"), "provenance": "; ".join(bits), "needs_rebuild": eng["needs_rebuild"]})
    return out


@alphas_router.get("/alphas")
def get_book_alphas():
    """Kho alpha: registry.json + book.json (null nếu chưa có)."""
    from backend.optimize.book.registry import book_engine_status, engine_version
    book = _read_json(book_path())
    explore = _read_json(alpha_dir("explore", "book.json"))
    # P9.15: sổ dựng bằng engine khác engine hiện hành -> needs_rebuild (giao diện cảnh báo "cần dựng lại")
    registry = _read_json(alpha_file("registry"))
    return {"registry": registry, "registry_status": registry_provenance(registry),
            "book": book,
            "engine": {"current": engine_version(), "main": book_engine_status(book), "explore": book_engine_status(explore)}}


@alphas_router.post("/alphas/{alpha_id}/revalidate")
def post_alpha_revalidate(alpha_id: str, apply: bool = False):
    """Kiểm lại alpha trong kho bằng engine hiện hành theo cổng phễu (WFA dev2 -> hệ số s qua MC -> holdout) — job nền alpha_revalidate.
    apply=true: ghi status (validated / retired) vào registry; retired -> cấu hình testnet chuyển sang testnet/_retired/."""
    reg = _read_json(alpha_file("registry")) or {}
    if not any(a.get("alpha_id") == alpha_id for a in reg.get("alphas") or []):
        raise HTTPException(404, f"không có alpha {alpha_id} trong registry.json")
    return batch_jobs_routes.http_launch("alpha_revalidate", {"alpha_id": alpha_id, "apply": bool(apply)})


@book_router.post("/backtest")
def post_backtest(req: BacktestRequest):
    if not req.strategies and not os.path.isfile(book_path()):
        raise HTTPException(409, "chưa có data/alpha/book.json — truyền strategies hoặc dựng sổ trước (POST /build)")
    return modes.launch_backtest(req)


@book_router.post("/wfa")
def post_wfa(req: WfaRequest):
    return modes.launch_wfa(req)


@book_router.post("/build")
def post_build(req: BuildRequest):
    return batch_jobs_routes.build_and_launch("book_build", req.model_dump())


@book_router.post("/publish")
def post_publish(req: PublishRequest):
    """Xuất bản sổ của một job book_build đã xong sang kho alpha (thay sổ hiện hành). Build KHÔNG tự ghi đè kho alpha."""
    from backend.optimize.book.registry import publish_book
    try:
        job = batch_jobs.status(req.job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_build":
        raise HTTPException(422, "job_id phải là job book_build")
    if job.get("custom_gates"):
        raise HTTPException(409, "job này dùng ngưỡng gate tuỳ chỉnh (custom_gates) nên KHÔNG được xuất bản/promote — chạy lại ở chế độ Cơ bản (gate chuẩn)")
    if job.get("status") != "done":
        raise HTTPException(409, f"job build chưa xong (trạng thái {job.get('status')})")
    src = os.path.join(batch_jobs.job_dir(req.job_id), "alphas")
    try:
        out = publish_book(src, os.path.dirname(os.path.abspath(book_path())))
    except FileNotFoundError:
        raise HTTPException(409, "job này không có sổ dựng (book.json) để xuất bản (không dựng ra sổ, hoặc chạy trước khi build tách khỏi kho alpha)")
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"không xuất bản được: {e}")
    return {"published": True, "job_id": req.job_id, **out}


@book_router.get("/jobs")
def get_jobs(limit: int = 20, kind: Optional[str] = None):
    try:
        return {"jobs": batch_jobs.list_jobs(limit, kind)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


@book_router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, response: Response, lite: bool = False):
    """lite=true: bỏ result.trade_list (UI phân trang lệnh qua /api/studio/portfolio/trades). Job done/failed/cancelled: ETag + Cache-Control
    private, max-age=86400 và If-None-Match -> 304 (không đọc result.json); đang chạy/queued: no-store."""
    try:
        etag = batch_jobs.status_etag(job_id, lite)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    cc = "private, max-age=86400"
    if etag:
        inm = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
        if etag in inm or "*" in inm:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cc})
    try:
        s = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if s is None:
        if batch_jobs.ephemeral_gone(job_id):
            raise batch_jobs.EphemeralGone(job_id)
        raise HTTPException(404, "không có job này")
    if s.get("status") in batch_jobs.TERMINAL_STATES:
        etag = batch_jobs.status_etag(job_id, lite) or etag   # tính lại sau status(): job vừa được _finish ghi job.json
        response.headers["Cache-Control"] = cc
        if etag:
            response.headers["ETag"] = etag
    else:
        response.headers["Cache-Control"] = "no-store"
    s = modes.decorate(s)
    return batch_jobs.status_lite(s) if lite else s


@book_router.post("/jobs/{job_id}/cancel")
def post_cancel(job_id: str):
    """Huỷ job đang chạy/chờ: SIGTERM cả nhóm tiến trình; CLI flush kho kết quả rồi thoát -> có thể chạy tiếp bằng --resume <run_dir>."""
    try:
        s = batch_jobs.cancel(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(409 if "không còn chạy" in str(e) else 422, str(e))
    if s is None:
        raise HTTPException(404, "không có job này")
    return s


def _job_run_dir(job_id: str) -> str:
    """Thư mục lần chạy (có results.sqlite) của một job build: progress.json (khi đang chạy) hoặc result.json (khi xong); phải nằm trong thư mục lượt chạy (crawl.store.is_within(…, "runs"))."""
    from backend.crawl.store import is_within
    jd = batch_jobs.job_dir(job_id)
    run_dir = None
    for name in ("progress.json", "result.json"):
        data = _read_json(os.path.join(jd, name))
        if isinstance(data, dict) and data.get("run_dir"):
            run_dir = data["run_dir"]
            break
    if not run_dir:
        raise HTTPException(404, "job chưa có thư mục kết quả (chưa bắt đầu hoặc không phải job dựng sổ)")
    real = os.path.realpath(run_dir)
    if not is_within(real, "runs") or not os.path.isfile(os.path.join(real, "results.sqlite")):
        raise HTTPException(404, "không có kho kết quả của job này")
    return real


@book_router.get("/jobs/{job_id}/stage_a")
def get_stage_a(job_id: str, candidate: Optional[str] = None, offset: int = 0, limit: int = 100, sort: str = "order"):
    """Phân trang MỌI cấu hình dev1 đã chạy (đọc kho results.sqlite của job dựng sổ; result.stage_a chỉ có top-K).
    sort=order (thứ tự lấy mẫu) | score (điểm cao -> thấp). Mỗi hàng: {ord, params, dev1{ret_pct,mdd_pct,trades,symbols_positive,sharpe}, score|null, passed}."""
    from backend.optimize.funnel.storage import ResultsStore
    if sort not in ("order", "score"):
        raise HTTPException(422, "sort phải là order|score")
    if offset < 0 or not 1 <= limit <= 1000:
        raise HTTPException(422, "offset >= 0 và 1 <= limit <= 1000")
    try:
        run_dir = _job_run_dir(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    store = ResultsStore(run_dir, read_only=True)
    try:
        if candidate is not None and candidate not in store.candidates("A"):
            raise HTTPException(404, f"không có chiến lược {candidate!r} trong kho (có: {store.candidates('A')})")
        rows = store.page("A", candidate, offset, limit, sort)
        total = store.count("A", candidate)
        return {"job_id": job_id, "candidate": candidate, "offset": offset, "limit": limit, "sort": sort, "total": total,
                "candidates": store.candidates("A"),
                "rows": [{"candidate": r["candidate"], "ord": r["ord"], "params": r["params"],
                          "dev1": {k: r["metrics"].get(k) for k in ("ret_pct", "mdd_pct", "trades", "symbols_positive", "sharpe")},
                          "score": r["score"], "passed": r["score"] is not None} for r in rows]}
    finally:
        store.close()


# ─── Monte Carlo ngày (đồng bộ, nhẹ) ────────────────────────────────────────
@book_router.post("/mc")
def post_mc(req: McRequest):
    """Block bootstrap (mặc định 10.000 kịch bản) lợi suất ngày OOS của một job book_wfa (hoặc chuỗi tự gửi); trả tóm tắt + fan + histogram
    + `stress` (kịch bản cực xấu tất định + worst_bootstrap) + `worst_path` + `gate` (checks thực tế/yêu cầu, gate_eligible).
    mode=basic: bỏ qua mọi tham số MC của client (10.000 kịch bản, đủ 6 kịch bản cực xấu, gate chuẩn).
    mode=advanced: dùng tham số client; ngưỡng gate khác chuẩn / < 10.000 kịch bản / thiếu kịch bản cực xấu -> params.custom_gates=true (không promote được)."""
    from backend.carlo.carlo import evaluate_mc_gate, extra_cost_from_turnover, run_monte_carlo_daily_detail
    cfg = modes.resolve_mc(req)
    custom = cfg["custom_gates"]
    if req.wfa_job_id:
        try:
            job = batch_jobs.status(req.wfa_job_id)
        except batch_jobs.JobError as e:
            raise HTTPException(422, str(e))
        if job is None:
            raise HTTPException(404, "không có job này")
        if job.get("kind") != "book_wfa":
            raise HTTPException(422, "wfa_job_id phải là job book_wfa")
        if job.get("status") != "done" or not job.get("result"):
            raise HTTPException(409, f"job WFA chưa xong (trạng thái {job.get('status')})")
        custom = custom or bool(job.get("custom_gates"))   # nguồn đã dùng gate tuỳ chỉnh -> kết quả cũng không promote được
        summary = job["result"].get("summary") or {}
        daily = (summary.get("oos_daily") or {}).get(req.basis) or []
        shock = summary.get("shock")   # WFA ghi vị thế ngược chiều lớn nhất -> thêm kịch bản trend thẳng đứng
        turnover = summary.get("turnover_daily")   # WFA ghi vòng quay vốn đo từ lệnh OOS -> kịch bản cost_x2 (job cũ không có -> không đo được)
        source = {"kind": "wfa", "job_id": req.wfa_job_id, "basis": req.basis}
        provenance = job["result"].get("provenance")   # nguồn gốc của lần chạy engine tạo ra chuỗi OOS
    else:
        provenance = None   # chỉ chuỗi ngày người dùng gửi: không có lần chạy engine nào
        daily, source, shock, turnover = req.daily_returns, {"kind": "daily_returns"}, None, None   # chỉ chuỗi ngày: không biết vòng quay
        # kiểm ở đây (không trong validator pydantic): lỗi validator kèm đầu vào NaN làm FastAPI không dựng được phản hồi 422
        if not all(math.isfinite(x) and x > -1.0 for x in daily):
            raise HTTPException(422, "daily_returns phải hữu hạn và > -1 (-100%)")
    if len(daily) < MC_MIN_DAYS:
        raise HTTPException(422, f"cần >= {MC_MIN_DAYS} lợi suất ngày (có {len(daily)})")
    if shock and cfg["stress"] is not None and not set(STRESS_VERTICAL) <= set(cfg["stress"]):
        custom = True   # nguồn biết vị thế mà bỏ kịch bản trend thẳng đứng -> gate không chuẩn
    extra = cfg["extra_cost_daily_pct"]            # người dùng nhập (advanced) ưu tiên; không thì vòng quay đo từ lệnh; không có -> cost_x2 "không đo được"
    extra_daily = extra / 100.0 if extra is not None else extra_cost_from_turnover(turnover)
    out = run_monte_carlo_daily_detail(daily, simulations=cfg["simulations"], block_days=cfg["block_days"], horizon_days=cfg["horizon_days"],
                                       ruin_threshold_pct=cfg["ruin_threshold_pct"], seed=cfg["seed"], scale=cfg["scale"],
                                       max_ruin_pct=MC_RUIN_MAX_PCT, stress_max_mdd_pct=cfg["stress_max_mdd_pct"],
                                       extra_cost_daily=extra_daily, shock=shock)
    if cfg["stress"] is not None:   # tập con kịch bản cực xấu: lọc + tính lại gate trên đúng tập đó
        keep = set(cfg["stress"])
        out["stress"] = [r for r in out["stress"] if r["name"] in keep]
        out["gate"] = evaluate_mc_gate(cfg["simulations"], out["summary"]["p_mdd_ge_ruin_pct"], out["stress"], max_ruin_pct=MC_RUIN_MAX_PCT,
                                       ruin_threshold_pct=cfg["ruin_threshold_pct"], stress_max_mdd_pct=cfg["stress_max_mdd_pct"])
    out["provenance"] = provenance
    out["gate"]["custom_gates"] = custom
    if custom:
        out["gate"]["gate_eligible"] = False   # kết quả dùng ngưỡng tuỳ chỉnh không bao giờ là gate
    out = with_gate_thresholds(out)
    out["params"].update(turnover_daily=turnover, source=source, basis=req.basis, mode=cfg["mode"], custom_gates=custom, promotable=not custom,
                         ignored_client_params=cfg["ignored_client_params"])
    return out



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 2: DANH MỤC ĐẦU TƯ (gộp từ portfolio.py)
# ══════════════════════════════════════════════════════════════════════════

import os
import threading
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.crawl.store import benchmark_daily_closes
from backend.metrics import charts as feeds
from backend.metrics import charts as pd_mod
from backend.optimize.process import process as batch_jobs

portfolio_router = APIRouter(prefix="/api/studio/portfolio", tags=["portfolio"])

_CACHE = pd_mod.LruCache(32)
_LOCK = threading.Lock()


def snapshot_benchmark(result: Dict[str, Any], benchmark: str = "BTC@perp") -> Optional[pd.Series]:
    """Giá đóng cửa ngày của benchmark trong cửa sổ của `result`; None nếu thiếu cấu hình/dữ liệu (bench = null)."""
    cfg = result.get("config") or {}
    if not (cfg.get("start") and cfg.get("end")):
        return None
    try:
        return benchmark_daily_closes(benchmark, cfg["start"], cfg["end"])
    except Exception:   # noqa: BLE001  (thiếu dữ liệu benchmark thì vẫn trả dashboard)
        return None


def _latest_done_backtest() -> Optional[str]:
    for j in batch_jobs.list_jobs(100, "book_backtest"):
        if j.get("status") == "done":
            return j["id"]
    return None


@portfolio_router.get("/dashboard")
def get_dashboard(source: str = Query("backtest", pattern="^backtest$"), job_id: Optional[str] = None,
                  period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$")):
    if not job_id:   # không truyền job: lấy job backtest xong gần nhất (payload.source.job_id cho biết đã dùng job nào)
        job_id = _latest_done_backtest()
        if not job_id:
            return {"available": False, "reason": "Chưa có job backtest nào hoàn tất — chạy Backtest trước."}
    try:
        rpath = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    key = (job_id, period, os.path.getmtime(rpath) if os.path.isfile(rpath) else None)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest":
        raise HTTPException(422, "job_id phải là job book_backtest")
    if job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, f"job chưa xong (trạng thái {job.get('status')})")
    res = job["result"]
    feed = feeds.BacktestFeed(res, job_id, batch_jobs.job_label(job["kind"], job.get("params")))
    snap = feed.fetch()
    payload = pd_mod.build_from_snapshot(snap, period, snapshot_benchmark(res))
    with _LOCK:
        _CACHE.put(key, payload)
    return payload


def _result_for(job_id: Optional[str]):
    """Kết quả book_backtest của job: (result, job_id)."""
    job_id = job_id or _latest_done_backtest()
    if not job_id:
        raise HTTPException(404, "Chưa có job backtest nào hoàn tất — chạy Backtest trước.")
    try:   # trang/bộ lọc khác nhau của cùng job: không parse lại result.json (đệm theo job + mtime/size; chỉ nạp sau khi đã qua kiểm tra bên dưới)
        st = os.stat(os.path.join(batch_jobs.job_dir(job_id), "result.json"))
        rkey = ("result", job_id, st.st_mtime_ns, st.st_size)
    except (OSError, batch_jobs.JobError):
        rkey = None
    if rkey is not None:
        with _LOCK:
            hit = _CACHE.get(rkey)
        if hit is not None:
            return hit, job_id
    try:
        job = batch_jobs.status(job_id)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if job is None:
        raise HTTPException(404, "không có job này")
    if job.get("kind") != "book_backtest" or job.get("status") != "done" or not job.get("result"):
        raise HTTPException(409, "job phải là book_backtest đã xong")
    if rkey is not None:
        with _LOCK:
            _CACHE.put(rkey, job["result"])
    return job["result"], job_id


TRADE_SORT = {"close_time", "enter_time", "pnl", "pnl_pct", "mae_pct", "notional", "symbol", "strategy"}


@portfolio_router.get("/trades")
def get_portfolio_trades(source: str = Query("backtest", pattern="^backtest$"), job_id: Optional[str] = None,
               period: str = Query("ALL", pattern="^(1M|3M|YTD|1Y|ALL)$"), strategy: Optional[str] = None, symbol: Optional[str] = None,
               side: Optional[str] = Query(None, pattern="^(LONG|SHORT)$"), outcome: Optional[str] = Query(None, pattern="^(win|loss|breakeven)$"),
               sort: str = "-close_time", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=2000),
               format: str = Query("json", pattern="^(json|csv)$")):
    """Danh sách lệnh đã đóng của job backtest (lọc: kỳ / chiến lược — id hoặc HỌ chiến lược / tài sản / chiều / kết quả), sắp xếp, phân trang;
    format=csv trả toàn bộ hàng đã lọc (không phân trang)."""
    from backend.metrics.trades import strategy_family
    res, jid = _result_for(job_id)
    rows = [t for t in res.get("trade_list") or [] if t.get("close_time") is not None]
    if period != "ALL":
        nav = pd_mod.daily_nav_series(res)
        if len(nav):
            cut = pd_mod._cutoff(nav.index[-1], period)
            if cut is not None:
                start_ms = int((cut + pd_mod.pd.Timedelta(days=1)).value // 1_000_000)
                rows = [t for t in rows if t["close_time"] >= start_ms]
    if strategy:
        rows = [t for t in rows if t.get("strategy") == strategy or strategy_family(t.get("strategy")) == strategy]
    if symbol:
        want = symbol if "@" in symbol else f"{symbol.upper()}@perp"
        rows = [t for t in rows if t.get("symbol") in (symbol, want)]
    if side:
        rows = [t for t in rows if t.get("side") == side]
    if outcome:
        rows = [t for t in rows if (outcome == "win" and t["pnl"] > 0) or (outcome == "loss" and t["pnl"] < 0) or (outcome == "breakeven" and t["pnl"] == 0)]
    key = sort.lstrip("-")
    if key not in TRADE_SORT:
        raise HTTPException(422, f"sort phải là một trong {sorted(TRADE_SORT)} (thêm '-' để giảm dần)")
    rows = sorted(rows, key=lambda t: (t.get(key) is None, t.get(key) if t.get(key) is not None else 0), reverse=sort.startswith("-"))
    if format == "csv":
        import csv
        import io
        from fastapi.responses import Response
        cols = ["close_time", "enter_time", "symbol", "strategy", "side", "enter_price", "avg_price", "close_price", "qty", "notional",
                "margin_usd", "leverage", "layers", "pnl", "pnl_pct", "fees_usd", "funding_usd", "mae_pct", "status", "close_reason"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="trades_backtest_{jid}.csv"'})
    total = len(rows)
    return {"items": rows[offset:offset + limit], "total": total, "offset": offset, "limit": limit, "job_id": jid,
            "strategies": sorted({t.get("strategy") for t in res.get("trade_list") or [] if t.get("strategy")}),
            "families": sorted({strategy_family(t.get("strategy")) for t in res.get("trade_list") or [] if t.get("strategy")}),
            "symbols": sorted({t.get("symbol") for t in res.get("trade_list") or [] if t.get("symbol")})}



# ══════════════════════════════════════════════════════════════════════════
# PHẦN 3: PHỄU KIỂM DUYỆT CHIẾN LƯỢC (gộp từ funnel.py)
# ══════════════════════════════════════════════════════════════════════════

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.optimize.process import process as batch_jobs
from backend.routes import process as batch_jobs_routes
from backend.optimize.funnel import stages as gates
from backend.optimize.search.generate import count_params
from backend.optimize.funnel.stages import read_cached
from backend.carlo.carlo import with_gate_thresholds
from backend.models.params import DEFAULT_CAPITAL
from backend.crawl.store import read_json
from backend.metrics.charts import LruCache
from backend.optimize.funnel.stages import scalar_metrics, stage_stats
from backend.optimize.funnel.storage import RunStore, atomic_write_json

funnel_router = APIRouter(prefix="/api/studio/funnel", tags=["funnel"])

KIND = "funnel_run"
assert KIND in batch_jobs.KINDS

MAX_ALPHAS = 1_000_000
LARGE_ALPHAS = 200_000
_RUN_RE = re.compile(r"^fr-[0-9A-Za-z_-]{1,40}$|^[0-9A-Za-z_-]{3,48}$")
_ALPHA_RE = re.compile(r"^[0-9a-f]{8,64}$")
SORT_COLS = {"ret_pct": "m.ret_pct", "mdd_pct": "m.mdd_pct", "sharpe": "m.sharpe", "trades": "m.trades", "win_rate": "m.win_rate",
             "profit_factor": "m.profit_factor", "score": "m.score", "order": "a.ord", "ord": "a.ord", "final_scale": "a.final_scale",
             # số đo mở rộng (metrics_json; metrics/metrics.flat_extras) — sắp xếp qua json_extract
             **{k: f"json_extract(m.metrics_json, '$.{k}')" for k in (
                 "cagr_pct", "calmar", "cvar95_pct", "max_dd_days", "payoff", "expectancy_pct", "max_consec_losses", "top5_share_pct",
                 "mae_worst_pct", "liq_proximity_max_pct", "liquidations", "fee_drag_pct", "mdd_daily_pct", "mdd_intrabar_pct", "sortino")}}


# ─── Đường dẫn / mở kho ─────────────────────────────────────────────────────
from backend.optimize.funnel.stages import funnel_root   # P9.6: MỘT định nghĩa (stages.py); router chỉ import


from backend.crawl.store import alpha_dir as alphas_dir   # P9.6: MỘT định nghĩa (crawl/store.alpha_dir, tôn trọng NORA_ALPHAS_DIR); monkeypatch fr.alphas_dir vẫn hiệu lực


def _run_dir(run_id: str) -> str:
    if not _RUN_RE.match(run_id):
        raise HTTPException(422, "run_id không hợp lệ")
    return os.path.join(funnel_root(), run_id)


def open_run(run_id: str) -> RunStore:
    d = _run_dir(run_id)
    if not os.path.isfile(os.path.join(d, "results.sqlite")):
        raise HTTPException(404, f"không có lượt phễu {run_id} (hoặc chưa bắt đầu chạy)")
    return RunStore(d, read_only=True)


def _stage(stage: str) -> str:
    if stage not in gates.ALL_STAGE_IDX:   # kèm tầng cũ S2_antiluck của lượt chạy trước 08/10/2026
        raise HTTPException(404, f"không có tầng {stage!r}; có: {gates.STAGES}")
    return stage


def _alpha_id(alpha_id: str) -> str:
    if not _ALPHA_RE.match(alpha_id):
        raise HTTPException(422, "alpha_id không hợp lệ")
    return alpha_id


# ─── Đệm kết quả nặng (tính lại trong request ăn GIL của mọi request khác) ──────────────────────────────────
LIVE_MIN_INTERVAL_S = 15.0      # lượt đang chạy: kho đổi liên tục nhưng không tính lại thống kê/đếm tầng thường hơn mức này

_STATS_CACHE = LruCache(32)         # (run_id, stage, top, chữ ký kho) -> kết quả stage_stats
_STATS_LAST = LruCache(128)         # (run_id, stage, top) -> (monotonic lúc tính, kết quả): cho nhịp tính tối thiểu của lượt đang chạy
_COUNTS_CACHE = LruCache(256)       # (run_id, chữ ký kho) -> counts (stage_counts + top_reject) của _run_summary
_COUNTS_LAST = LruCache(256)        # run_id -> (monotonic, counts)
_FLIGHT: Dict[Any, threading.Lock] = {}
_FLIGHT_LOCK = threading.Lock()


def _flight(key) -> threading.Lock:
    """Khoá theo khoá đệm: nhiều request cùng hỏi một thứ -> một cái tính, số còn lại chờ rồi đọc đệm."""
    with _FLIGHT_LOCK:
        return _FLIGHT.setdefault(key, threading.Lock())


def _store_sig(d: str):
    """Chữ ký kho: (mtime_ns, size) của results.sqlite + -wal (WAL: ghi mới nằm ở -wal, file chính chỉ đổi khi checkpoint)."""
    out = []
    for n in ("results.sqlite", "results.sqlite-wal"):
        try:
            st = os.stat(os.path.join(d, n))
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
class FunnelRunRequest(BaseModel):
    strategies: List[str] = Field(..., min_length=1, max_length=16)
    n_per_strategy: Optional[int] = Field(None, ge=1, le=MAX_ALPHAS, description="số alpha mỗi chiến lược (lấy mẫu theo seed)")
    full_grid: bool = False
    seed: int = Field(7, ge=0, le=2 ** 31 - 1)
    symbols: Optional[List[str]] = Field(None, max_length=16)
    windows: Optional[Dict[str, str]] = Field(None, description="ghi đè mốc YYYY-MM-DD: start, dev1_end, dev2_end, end")
    resume_run_id: Optional[str] = None
    force_large: bool = False
    space: str = Field("grid", pattern="^(grid|schema)$", description="grid = lưới nhỏ của chiến lược; schema = mọi tham số theo min/max/bước")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$",
                           description="khung chạy (nến mô phỏng): 15m / 1h / 4h; khung tín hiệu của mọi alpha >= khung này")
    regime: str = Field("off", pattern="^(off|learn|both)$",
                        description="learn: alpha học bảng regime trên train; both: mỗi bộ tham số chạy cả off và learn (DSR/PBO đếm cả hai)")

    @field_validator("windows")
    @classmethod
    def _win(cls, v):
        if v:
            bad = sorted(set(v) - {"start", "dev1_end", "dev2_end", "end"})
            if bad:
                raise ValueError(f"windows: khoá lạ {bad}")
            for d in v.values():
                batch_jobs_routes.check_date(d)
        return v

    @model_validator(mode="after")
    def _one(self):
        if not self.resume_run_id and bool(self.n_per_strategy) == bool(self.full_grid):
            raise ValueError("chọn đúng một: n_per_strategy hoặc full_grid")
        return self


def _planned(strategies: List[str], n: Optional[int], full_grid: bool, space: str = "grid", timeframe: str = "15m",
             regime: str = "off") -> Dict[str, int]:
    from backend.optimize.book.build import BY_ID
    from backend.optimize.search.generate import incompatible, space_for
    by_id = BY_ID
    bad = incompatible([by_id[s] for s in strategies], space, timeframe)
    if bad:
        raise HTTPException(422, f"chiến lược không chạy được ở khung {timeframe} (khung tín hiệu tối đa nhỏ hơn khung chạy): "
                                 + "; ".join(f"{k} ({', '.join(v)})" for k, v in bad.items()))
    from backend.optimize.search.generate import regime_variants
    k = len(regime_variants({}, regime))
    return {s: k * count_params(space_for(by_id[s], space, timeframe), n, full_grid) for s in strategies}


# ─── Tạo lượt / ước tính ────────────────────────────────────────────────────
@funnel_router.post("/runs")
def post_run(req: FunnelRunRequest):
    """Khởi chạy phễu như job nền (hàng đợi run_limited). -> {run_id, job_id}. resume_run_id: chạy tiếp lượt đó (cấu hình lấy từ run.json)."""
    try:
        strategies = batch_jobs_routes.check_candidate_ids(req.strategies)
        symbols = batch_jobs_routes.check_symbols(req.symbols) if req.symbols else None
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    from backend.optimize.funnel.stages import new_run_id
    if req.resume_run_id:
        run_id = req.resume_run_id
        if not os.path.isfile(os.path.join(_run_dir(run_id), "results.sqlite")):
            raise HTTPException(404, f"không có lượt {run_id} để chạy tiếp")
        params = {"resume": run_id}
        planned = None
    else:
        planned = _planned(strategies, req.n_per_strategy, req.full_grid, req.space, req.timeframe, req.regime)
        total = sum(planned.values())
        if total > MAX_ALPHAS or (total > LARGE_ALPHAS and not req.force_large):
            raise HTTPException(422, f"{total:,} alpha vượt giới hạn ({LARGE_ALPHAS:,}; trần cứng {MAX_ALPHAS:,}); giảm n_per_strategy hoặc đặt force_large")
        run_id = new_run_id()
        params = {"strategies": strategies, "seed": req.seed, "run_id": run_id, "space": req.space, "timeframe": req.timeframe, "regime": req.regime}
        params.update({"full_grid": True} if req.full_grid else {"n_per_strategy": req.n_per_strategy})
        if symbols:
            params["symbols"] = symbols
        if req.windows:
            params["windows"] = req.windows
        if total > LARGE_ALPHAS:
            params["force_large"] = True
        # bản run.json "queued" TRƯỚC khi chạy: danh sách lượt thấy ngay lượt đang xếp hàng; CLI ghi đè bằng run.json đầy đủ khi bắt đầu
        atomic_write_json(os.path.join(_run_dir(run_id), "run.json"), {
            "run_id": run_id, "status": "queued", "created": time.time(), "started": None, "finished": None, "total_alphas": total,
            "planned": planned, "config": {"strategies": strategies, "n_per_strategy": req.n_per_strategy, "full_grid": req.full_grid, "space": req.space,
                                           "timeframe": req.timeframe, "regime": req.regime, "seed": req.seed, "symbols": symbols,
                                           "windows": req.windows},
            "stages": {s: {"status": "pending"} for s in gates.STAGES}})
    try:
        job_id = batch_jobs.launch(KIND, params)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    except batch_jobs.JobBusy as e:
        raise HTTPException(429, str(e))
    atomic_write_json(os.path.join(_run_dir(run_id), "api_job.json"), {"job_id": job_id, "kind": KIND, "params": params, "launched": time.time()})
    return {"run_id": run_id, "job_id": job_id}


@funnel_router.get("/estimate")
def get_estimate(strategies: str = Query(..., description="id phân tách bằng dấu phẩy"), n_per_strategy: Optional[int] = Query(None, ge=1, le=MAX_ALPHAS),
                 full_grid: bool = False, workers: Optional[int] = Query(None, ge=1, le=64, description="bỏ trống = số worker mặc định của máy chủ"),
                 space: str = Query("grid", pattern="^(grid|schema)$"),
                 timeframe: str = Query("15m", pattern="^(15m|1h|4h)$"),
                 regime: str = Query("off", pattern="^(off|learn|both)$")):
    """Ước tính thời gian S1 (tầng chiếm gần hết thời gian) TRƯỚC khi chạy: alpha × giây/backtest / số worker, giây/backtest = TRUNG VỊ số đo của các lượt
    đã xong cùng khung + regime (optimize/funnel/stages.py). Chưa có lượt khớp -> sec_per_backtest = null, s1_eta_s = null, measure.reason nêu lý do.
    workers bỏ trống = số worker mặc định của máy chủ (optimize/process/workers.default_workers, cùng số `--workers auto`). Các tầng sau chỉ chạy cho alpha còn sống."""
    try:
        ids = batch_jobs_routes.check_candidate_ids([s for s in strategies.split(",") if s])
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    if bool(n_per_strategy) == bool(full_grid):
        raise HTTPException(422, "chọn đúng một: n_per_strategy hoặc full_grid")
    planned = _planned(ids, n_per_strategy, full_grid, space, timeframe, regime)
    total = sum(planned.values())
    from backend.optimize.funnel.stages import measured_s1_rate
    from backend.optimize.funnel.stages import PER_WORKER_MB
    from backend.optimize.process.workers import default_workers
    w = workers if workers is not None else default_workers(PER_WORKER_MB)
    m = measured_s1_rate(funnel_root(), timeframe, regime, jobs_root=batch_jobs.jobs_root())
    spb = m["sec_per_backtest"]
    return {"space": space, "per_strategy": planned, "total_alphas": total, "sec_per_backtest": spb, "workers": w,
            "workers_source": "client" if workers is not None else "server_default",
            "s1_eta_s": round(total * spb / w, 1) if spb is not None else None, "measure": m}


# ─── Danh sách / chi tiết lượt ──────────────────────────────────────────────
def _job_status(run: Dict[str, Any], d: str) -> Dict[str, Any]:
    job_id = run.get("job_id")
    if not job_id:
        try:
            with open(os.path.join(d, "api_job.json"), encoding="utf-8") as fh:
                job_id = json.load(fh).get("job_id")
        except (OSError, ValueError):
            job_id = None
    status = run.get("status") or "unknown"
    if job_id and status in ("queued", "running"):
        try:
            j = batch_jobs.status(job_id)
        except batch_jobs.JobError:
            j = None
        if j and j.get("status") in ("queued", "running", "done", "failed", "cancelled"):
            status = j["status"]
    return {"job_id": job_id, "status": status}


def _read_run_json(d: str) -> Dict[str, Any]:
    return read_json(os.path.join(d, "run.json"), {})


def _progress(d: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(d, "progress.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        return {"stage": p.get("stage"), "done": p.get("done"), "total": p.get("total"), "eta_s": p.get("eta_s"), "rate": p.get("rate"),
                "peak_rss_mb": p.get("peak_rss_mb"), "status": p.get("status")}
    except (OSError, ValueError):
        return None


def _stage_counts(run_id: str, d: str, live: bool) -> List[Dict[str, Any]]:
    """Đếm theo tầng + lý do loại nhiều nhất của một lượt. Đệm theo chữ ký kho (mtime/size results.sqlite + -wal); lượt đang chạy:
    kho đổi mà lần tính trước < LIVE_MIN_INTERVAL_S thì dùng lại kết quả trước (danh sách lượt được poll liên tục)."""
    sig = _store_sig(d)
    key = (run_id, sig)
    hit = _COUNTS_CACHE.get(key)
    if hit is not None:
        return hit
    if live:
        last = _COUNTS_LAST.get(run_id)
        if last is not None and time.monotonic() - last[0] < LIVE_MIN_INTERVAL_S:
            return last[1]
    with _flight(("counts", run_id)):
        hit = _COUNTS_CACHE.get(key)
        if hit is not None:
            return hit
        store = RunStore(d, read_only=True)
        try:
            counts = store.stage_counts()
            tops = store.top_rejects()
        finally:
            store.close()
        for c in counts:
            t = tops.get(c["stage"])
            c["top_reject"] = {"code": t["code"], "label": gates.reason_label(t["code"]), "count": t["count"]} if t else None
        counts = [c for c in counts if c["input"] > 0 or c["done"] > 0]   # bỏ các tầng chưa có alpha nào
        _COUNTS_CACHE.put(key, counts)
        _COUNTS_LAST.put(run_id, (time.monotonic(), counts))
        return counts


def _run_summary(run_id: str, detail: bool) -> Optional[Dict[str, Any]]:
    d = os.path.join(funnel_root(), run_id)
    run = _read_run_json(d)
    if not run and not os.path.isfile(os.path.join(d, "results.sqlite")):
        return None
    st = _job_status(run, d)
    cfg = run.get("config") or {}
    counts: List[Dict[str, Any]] = []
    if os.path.isfile(os.path.join(d, "results.sqlite")):
        counts = _stage_counts(run_id, d, st["status"] in ("queued", "running"))
    prog = _progress(d) if st["status"] in ("running", "queued") else None
    out = {"run_id": run_id, "job_id": st["job_id"], "status": st["status"], "created": run.get("created"), "started": run.get("started"),
           "finished": run.get("finished"), "strategies": cfg.get("strategies"), "n_per_strategy": cfg.get("n_per_strategy"),
           "full_grid": cfg.get("full_grid"), "total_alphas": run.get("total_alphas"), "counts": counts, "progress": prog}
    if detail:
        out.update({"config": cfg, "stages": run.get("stages"), "until": run.get("until"), "wall_s": run.get("wall_s"),
                    "windows_ms": run.get("windows_ms"), "kind": KIND})
    return out


@funnel_router.get("/runs")
def get_runs(limit: int = Query(50, ge=1, le=200)):
    root = funnel_root()
    rows = []
    for name in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        if not os.path.isdir(os.path.join(root, name)):
            continue
        s = _run_summary(name, detail=False)
        if s:
            rows.append(s)
    rows.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return {"runs": rows[:limit]}


@funnel_router.get("/runs/{run_id}")
def get_run(run_id: str):
    _run_dir(run_id)
    s = _run_summary(run_id, detail=True)
    if s is None:
        raise HTTPException(404, f"không có lượt phễu {run_id}")
    return s


@funnel_router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    """Huỷ job của lượt (SIGTERM -> flush kho; chạy tiếp bằng POST /runs {resume_run_id})."""
    s = _run_summary(run_id, detail=False)
    if s is None or not s.get("job_id"):
        raise HTTPException(404, "không có job của lượt này")
    try:
        return batch_jobs.cancel(s["job_id"]) or {}
    except batch_jobs.JobError as e:
        raise HTTPException(409, str(e))


# ─── Thống kê tầng ──────────────────────────────────────────────────────────
@funnel_router.get("/runs/{run_id}/stages/{stage}/stats")
def get_stage_stats(run_id: str, stage: str, top: int = Query(20, ge=1, le=100)):
    # đệm GIÁ TRỊ là body JSON đã render (bytes): jsonable_encoder + dumps ~0,2 s CPU cho 450 KB, mỗi lần poll sẽ ăn GIL nếu chỉ đệm dict
    return Response(_stage_stats_body(run_id, stage, top), media_type="application/json")


def _stage_stats_body(run_id: str, stage: str, top: int) -> bytes:
    stage = _stage(stage)
    d = _run_dir(run_id)
    key = (run_id, stage, top, _store_sig(d))
    hit = _STATS_CACHE.get(key)
    if hit is not None:
        return hit
    with _flight(("stats", run_id, stage, top)):
        hit = _STATS_CACHE.get(key)     # request khác vừa tính xong trong lúc chờ khoá
        if hit is not None:
            return hit
        store = open_run(run_id)
        try:
            run = store.read_run()
            done = (run.get("stages", {}).get(stage, {}) or {}).get("status") == "done"
            lk = (run_id, stage, top)
            if not done:   # lượt đang chạy: kho đổi liên tục -> không tính lại thường hơn LIVE_MIN_INTERVAL_S, trả kết quả trước
                last = _STATS_LAST.get(lk)
                if last is not None and time.monotonic() - last[0] < LIVE_MIN_INTERVAL_S:
                    return last[1]
            cache = os.path.join(store.run_dir, "stats", f"{stage}.json")
            out = None
            if done and top == 20:
                try:
                    with open(cache, encoding="utf-8") as fh:
                        out = json.load(fh)
                except (OSError, ValueError):
                    pass
            if out is None:
                try:
                    out = stage_stats(store, stage, top)
                except KeyError:   # tầng cũ S2_antiluck không có trong lượt này
                    raise HTTPException(404, f"lượt {run_id} không có tầng {stage!r}")
                if done and top == 20:
                    try:
                        atomic_write_json(cache, out)
                    except OSError:
                        pass
            body = JSONResponse(jsonable_encoder(out)).body   # đúng đường FastAPI sẽ render dict trả về
            _STATS_CACHE.put(key, body)
            _STATS_LAST.put(lk, (time.monotonic(), body))
            return body
        finally:
            store.close()


# ─── Bảng alpha ─────────────────────────────────────────────────────────────
def _parse_sort(sort: Optional[str], has_metrics: bool) -> str:
    """`-ret_pct` = giảm dần, `ret_pct` = tăng dần; mặc định: điểm cao trước (có tầng) / thứ tự sinh. Hoà -> thứ tự sinh. NULL luôn cuối."""
    if not sort:
        sort = "-score" if has_metrics else "order"
    desc = sort.startswith("-")
    key = sort.lstrip("-+ ")
    if key not in SORT_COLS or (not has_metrics and key not in ("order", "ord", "final_scale")):
        raise HTTPException(422, f"sort không hợp lệ: {sort!r}; có: {sorted(SORT_COLS)} (thêm '-' đầu = giảm dần)")
    col = SORT_COLS[key]
    return f"{col} IS NULL, {col} {'DESC' if desc else 'ASC'}, a.ord"


@funnel_router.get("/runs/{run_id}/alphas")
def get_funnel_alphas(run_id: str, stage: Optional[str] = None, status: Optional[str] = Query(None, pattern="^(passed|rejected)$"),
               strategy: Optional[str] = None, sort: Optional[str] = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    """{total, offset, limit, items:[{alpha_id, strategy, params, stage_reached, rejected_stage, reject_code, reject_msg, final_scale, metrics}]};
    `metrics` phẳng của tầng được hỏi (không có `stage`: của tầng alpha đã tới)."""
    store = open_run(run_id)
    try:
        where, args = [], []
        if strategy:
            where.append("a.strategy=?")
            args.append(strategy)
        if stage:
            stage = _stage(stage)
        if stage and stage != "S0_generate":
            base = "FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id"
            where.insert(0, "m.stage=?")
            args.insert(0, stage)
            if status:
                where.append("m.passed=?")
                args.append(1 if status == "passed" else 0)
            order = _parse_sort(sort, True)
            cols = "a.alpha_id, a.strategy, a.params_json, a.stage_reached, a.rejected_stage, a.reject_code, a.reject_msg, a.final_scale, m.metrics_json"
        else:
            base = "FROM alphas a"
            if stage == "S0_generate" and status:
                where.append("a.rejected_idx IS " + ("NULL" if status == "passed" else "NOT NULL"))
            elif status:   # không chọn tầng: qua = còn sống tới nay, loại = đã bị loại ở bất kỳ tầng nào
                where.append("a.rejected_idx IS " + ("NULL" if status == "passed" else "NOT NULL"))
            order = _parse_sort(sort, False)
            cols = "a.alpha_id, a.strategy, a.params_json, a.stage_reached, a.rejected_stage, a.reject_code, a.reject_msg, a.final_scale, NULL"
        w = (" WHERE " + " AND ".join(where)) if where else ""
        with store._lock:
            total = store._con.execute(f"SELECT COUNT(*) {base}{w}", args).fetchone()[0]
            rows = store._con.execute(f"SELECT {cols} {base}{w} ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        items = []
        need = [r[0] for r in rows if r[8] is None]
        fallback = {}
        if need:   # không chọn tầng: lấy số đo của tầng alpha đã tới
            for r in rows:
                if r[8] is None and r[3] in gates.ALL_STAGE_IDX:
                    fallback[r[0]] = store.metrics_of([r[0]], r[3]).get(r[0])
        for a, s, p, sr, rs, rc, rm, fs, mj in rows:
            m = json.loads(mj) if mj else fallback.get(a)
            items.append({"alpha_id": a, "strategy": s, "params": json.loads(p), "stage_reached": sr, "rejected_stage": rs, "reject_code": rc,
                          "reject_msg": rm, "final_scale": fs, "metrics": scalar_metrics(m) if m else {}})
        return {"total": int(total), "offset": offset, "limit": limit, "stage": stage, "items": items}
    finally:
        store.close()


# ─── Chi tiết alpha ─────────────────────────────────────────────────────────
def _nav(rows: List[Dict[str, Any]], initial: float = DEFAULT_CAPITAL) -> Optional[Dict[str, List[Any]]]:
    """Nối các hàng daily (theo fold) thành một đường vốn: lãi kép liên tục từ `initial`."""
    if not rows:
        return None
    dates: List[str] = []
    values: List[float] = []
    eq = initial
    for r in rows:
        if not r["rets"]:
            continue
        for d, x in zip(pd.date_range(r["start_date"], periods=len(r["rets"]), freq="D"), r["rets"]):
            eq *= 1.0 + x
            dates.append(f"{d:%Y-%m-%d}")
            values.append(round(eq, 2))
    return {"dates": dates, "values": values}


@funnel_router.get("/runs/{run_id}/alphas/{alpha_id}")
def get_alpha(run_id: str, alpha_id: str):
    """Alpha + `stage_metrics:{tầng: số đo}` + `nav:{tầng:{dates,values}}` + `mc` (cùng dạng POST /book/mc: summary, fan, stress, gate, ...) + `scale_search`."""
    _alpha_id(alpha_id)
    store = open_run(run_id)
    try:
        a = store.get_alpha(alpha_id)
        if a is None:
            raise HTTPException(404, f"không có alpha {alpha_id}")
        sm = store.alpha_metrics(alpha_id)
        nav: Dict[str, Any] = {}
        for st in gates.TRADE_STAGES:
            n = _nav(store.read_daily(alpha_id, st, st))
            if n:
                nav[st] = n
        mcfile = store.read_mc(alpha_id) or {}
        timeframe = (_read_run_json(_run_dir(run_id)).get("config") or {}).get("timeframe") or "1m"
        a.pop("ord", None)
        a.pop("stage_idx", None)
        return {**a, "stage_metrics": sm, "metrics": sm.get(a["stage_reached"]) or {}, "nav": nav, "mc": with_gate_thresholds(mcfile.get("mc")),
                "mc_full_size": with_gate_thresholds(mcfile.get("mc_full_size")), "scale_search": mcfile.get("scale_search") or [], "verified": mcfile.get("verified"),
                "confirm_attempts": mcfile.get("attempts") or [], "min_size": mcfile.get("min_size"),
                "stored_trades": {st: store.has_trades(alpha_id, st) for st in gates.TRADE_STAGES},
                "provenance": engine_provenance(timeframe)}
    finally:
        store.close()


# ─── Lệnh ───────────────────────────────────────────────────────────────────
def _iso(ms: int) -> str:
    return f"{pd.Timestamp(int(ms), unit='ms'):%Y-%m-%dT%H:%M:%S.%f}"[:-3] + "Z"


def _trade_item(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"fold": r.get("fold"), "symbol": r["symbol"], "side": r["side"], "enter_time": _iso(r["enter_time"]), "close_time": _iso(r["close_time"]),
            "enter_price": r["enter_price"], "close_price": r["close_price"], "qty": r["qty"], "pnl_usd": r["pnl_usd"], "pnl_pct": r["pnl_pct"],
            "fees_usd": r["fees_usd"], "funding_usd": r["funding_usd"], "status": r["status"], "layers": r["layers"], "mae_pct": r["mae_pct"]}


def _run_recompute_subprocess(run_id: str, alpha_id: str) -> None:
    """Tính lại S1 ngoài tiến trình API (job funnel_recompute qua runner, run_limited --no-lock: nằm trong nora.slice); ghi đệm vào
    <run>/recomputed/. Test thay hàm này."""
    job_dir = os.path.join(_run_dir(run_id), "recomputed", f"{alpha_id}.job")
    try:
        batch_jobs.run_sync("funnel_recompute", {"run_id": run_id, "alpha_id": alpha_id}, job_dir, timeout=1800)
    except TimeoutError:
        raise HTTPException(504, "tính lại lệnh quá thời gian (30 phút)")
    except RuntimeError as e:
        raise HTTPException(500, f"tính lại lệnh thất bại: {e}")


RECOMPUTE_WAIT_S = 85.0         # request chờ tối đa ngần này (< 100 s của Cloudflare); tính tiếp ở nền, client gọi lại sẽ thấy đệm
_RECOMPUTE_POOL = ThreadPoolExecutor(2, thread_name_prefix="funnel-recompute")
_RECOMPUTE_INFLIGHT: Dict[Any, Any] = {}
_RECOMPUTE_LOCK = threading.RLock()   # RLock: add_done_callback chạy ngay trong luồng gọi nếu việc đã xong


def _recompute_done(k) -> None:
    with _RECOMPUTE_LOCK:
        _RECOMPUTE_INFLIGHT.pop(k, None)


def _recompute_bounded(run_id: str, alpha_id: str) -> Optional[JSONResponse]:
    """Chạy _run_recompute_subprocess (vẫn timeout 1800 s) ở luồng nền và chờ <= RECOMPUTE_WAIT_S. Hết hạn mà chưa xong -> 202 (việc vẫn chạy;
    gọi lại cùng URL: đang chạy thì lại chờ, xong thì đọc đệm). Xong -> None. Lỗi của việc tính (504/500) ném lại như cũ."""
    k = (run_id, alpha_id)
    with _RECOMPUTE_LOCK:
        fut = _RECOMPUTE_INFLIGHT.get(k)
        if fut is None:
            if len(_RECOMPUTE_INFLIGHT) >= 4:
                raise HTTPException(429, "đang tính lại lệnh cho nhiều alpha khác; thử lại sau")
            fut = _RECOMPUTE_INFLIGHT[k] = _RECOMPUTE_POOL.submit(_run_recompute_subprocess, run_id, alpha_id)
            fut.add_done_callback(lambda _f, k=k: _recompute_done(k))
    try:
        fut.result(timeout=RECOMPUTE_WAIT_S)
    except FutureTimeout:
        return JSONResponse({"status": "computing", "recompute": True, "retry_after_s": 30,
                             "message": "đang tính lại lệnh (có thể mất vài phút); gọi lại cùng URL sau ít phút"},
                            status_code=202, headers={"Retry-After": "30"})
    return None


@funnel_router.get("/runs/{run_id}/alphas/{alpha_id}/trades")
def get_funnel_trades(run_id: str, alpha_id: str, stage: Optional[str] = None, fold: Optional[int] = Query(None, ge=1), offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=1000), recompute: bool = False):
    """{items, total, offset, limit, stage, fold, folds?, stored}. Chưa lưu lệnh (alpha bị loại ở S1): stored=false, items rỗng; `recompute=true`
    tính lại tất định rồi trả thêm `recomputed: true`. stage: S1_backtest | S3_wfa (lệnh OOS, lọc theo fold) | S5_sizing | S6_holdout | S6_holdout_extreme."""
    _alpha_id(alpha_id)
    store = open_run(run_id)
    try:
        a = store.get_alpha(alpha_id)
        if a is None:
            raise HTTPException(404, f"không có alpha {alpha_id}")
        if stage is None:   # mặc định: tầng cuối cùng có lệnh đã lưu
            stage = next((s for s in reversed(gates.TRADE_STAGES) if store.has_trades(alpha_id, s)), "S1_backtest")
        if stage not in gates.ALL_STAGE_IDX and stage != "S6_holdout_extreme":
            raise HTTPException(404, f"tầng không có lệnh: {stage!r}")
        dir_stage = "S6_holdout" if stage.startswith("S6_holdout") else stage
        rows = [r for r in store.read_trades(alpha_id, dir_stage, fold) if r["stage"] == stage]
        folds = sorted({r["fold"] for r in rows if r["fold"] is not None}) if dir_stage in ("S3_wfa", "S5_sizing") else None
        if rows:
            out = {"items": [_trade_item(r) for r in rows[offset:offset + limit]], "total": len(rows), "stored": True}
            if folds is not None:
                out["folds"] = sorted({r["fold"] for r in store.read_trades(alpha_id, dir_stage) if r["fold"] is not None})
            return {**out, "offset": offset, "limit": limit, "stage": stage, "fold": fold}
        if stage != "S1_backtest" or not recompute:
            return {"items": [], "total": 0, "offset": offset, "limit": limit, "stage": stage, "fold": fold, "stored": False,
                    "can_recompute": stage == "S1_backtest" and a["rejected_stage"] == "S1_backtest"}
        if a["rejected_stage"] != "S1_backtest" and a["stage_idx"] >= 1:
            raise HTTPException(409, "alpha đã qua S1 — lệnh phải có trong kho")
        cached = read_cached(store.run_dir, alpha_id)
        if cached is None:
            pending = _recompute_bounded(run_id, alpha_id)
            if pending is not None:
                return pending
            cached = read_cached(store.run_dir, alpha_id)
            if cached is None:
                raise HTTPException(500, "tính lại lệnh không tạo ra kết quả")
        tr = cached["trades"]
        tr.sort(key=lambda r: r["enter_time"])
        return {"items": [_trade_item({**r, "fold": None}) for r in tr[offset:offset + limit]], "total": len(tr), "offset": offset, "limit": limit,
                "stage": stage, "fold": fold, "stored": False, "recomputed": True}
    finally:
        store.close()


# ─── Xuất bản sổ chung vốn từ alpha FINAL ──────────────────────────────────
class FunnelBookRequest(BaseModel):
    alpha_ids: List[str] = Field(..., min_length=1, max_length=9, description="alpha FINAL (explore: đã qua S1), mỗi chiến lược một alpha")
    risk_per_trade_pct: float = Field(..., gt=0.0, le=5.0)
    wfa_job_id: str = Field("", description="job book_wfa (advanced) đã chạy ĐÚNG các cấu hình này ở cùng rủi ro; gate phải qua "
                                            "(explore: tuỳ chọn, không bắt qua)")
    dry_run: bool = False
    explore: bool = Field(False, description="sổ thử nghiệm cho demo -> data/alpha/explore/book.json (EXPLORE_DEMO), không bao giờ live")


@funnel_router.post("/runs/{run_id}/book")
def post_funnel_book(run_id: str, req: FunnelBookRequest):
    """Job nền funnel_book (optimize/funnel/stages.py): kiểm WFA sổ, chấm holdout MỘT lần, ghi data/alpha/book.json
    (+ testnet/book.json khi holdout đạt). dry_run: chỉ báo cáo, không ghi."""
    open_run(run_id).close()
    for a in req.alpha_ids:
        _alpha_id(a)
    params = {"run_id": run_id, "alpha_ids": ",".join(req.alpha_ids), "risk_per_trade_pct": req.risk_per_trade_pct,
              "wfa_job_id": req.wfa_job_id, "dry_run": req.dry_run, "explore": req.explore}
    if not req.explore and not req.wfa_job_id:
        raise HTTPException(422, "sổ chính cần wfa_job_id (gate WFA danh mục phải qua)")
    try:
        return {"job_id": batch_jobs.launch("funnel_book", params)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    except batch_jobs.JobBusy as e:
        raise HTTPException(429, str(e))


# ─── Đưa vào kho alpha ──────────────────────────────────────────────────────
class PromoteRequest(BaseModel):
    confirm: bool = Field(False, description="UI phải xác nhận rõ (true) — không có thì từ chối")
    note: Optional[str] = Field(None, max_length=500)


@funnel_router.post("/runs/{run_id}/alphas/{alpha_id}/promote")
def post_promote(run_id: str, alpha_id: str, req: PromoteRequest):
    """Ghi alpha FINAL vào data/alpha/registry.json (khoá mới `funnel`: s + bằng chứng) + cấu hình testnet. -> {registry_path, alpha_id, final_scale, testnet_config}."""
    _alpha_id(alpha_id)
    if not req.confirm:
        raise HTTPException(400, "cần confirm=true (xác nhận đưa alpha vào kho alpha)")
    open_run(run_id).close()
    from backend.optimize.book.registry import promote_alpha
    try:
        return promote_alpha(_run_dir(run_id), alpha_id, alphas_dir(), req.note)
    except KeyError:
        raise HTTPException(404, f"không có alpha {alpha_id}")
    except ValueError as e:
        raise HTTPException(409, str(e))



ROUTERS = [book_router, alphas_router, portfolio_router, funnel_router]
