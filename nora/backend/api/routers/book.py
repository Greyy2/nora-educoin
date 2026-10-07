"""API sổ chiến lược (strategy book): xem sổ hiện tại + chạy backtest danh mục / WFA danh mục / dựng sổ như job nền.

Job nặng chạy ở tiến trình riêng qua backend/utils/ops/run_limited.sh (xem backend/api/jobs/batch.py), handler ở đây chỉ
khởi chạy / đọc file nên nhanh và là `def` thường (FastAPI chạy trong threadpool).
"""
import json
import math
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.api import modes
from backend.api.jobs import batch as batch_jobs
from backend.crawl.store import alpha_dir, alpha_file
from backend.core.params.modes import STRESS_VERTICAL
from backend.carlo.monte_carlo import (with_gate_thresholds, MC_MAX_RUIN_PCT as MC_RUIN_MAX_PCT, MC_MAX_SIMULATIONS, MC_MIN_SIMULATIONS,
                                       STRESS_MAX_MDD_PCT)

router = APIRouter(prefix="/api/studio/book", tags=["book"])
alphas_router = APIRouter(prefix="/api/studio", tags=["book"])

MC_MIN_DAYS, MC_MAX_DAYS = 20, 5000
_METRIC_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "halted_at")


# ─── Mô hình yêu cầu ────────────────────────────────────────────────────────
MODE_FIELD = dict(pattern="^(basic|advanced)$", description="basic: máy chủ BỎ QUA tham số client, dùng preset (data/alphas/presets.json); "
                                                          "advanced: kiểm mọi tham số theo params_schema (xem docs/ui_contract.md §\"Chế độ chạy\")")


class StrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    params: Dict[str, Any] = Field(default_factory=dict, description="Chỉ dùng ở mode=advanced: khoá theo params_schema (số hoặc khung thời gian \"4h\"); "
                                                                      "thiếu khoá nào lấy từ preset. mode=basic: bỏ qua")


class _DateRange(BaseModel):
    @field_validator("start", "end", check_fields=False)
    @classmethod
    def _date(cls, v):
        return batch_jobs.check_date(v) if v else v


class BacktestRequest(_DateRange):
    strategies: Optional[List[StrategyIn]] = Field(None, max_length=16, description="Bỏ trống = dùng data/alphas/book.json")
    symbols: Optional[List[str]] = Field(None, max_length=16, description="Mặc định cả vũ trụ (perp). Hoặc tài sản DEX (\"AERO\" / \"dex:AERO\": spot, chỉ chân LONG; "
                                                                          "bắt buộc chọn strategies) — không trộn perp với DEX; WFA / phễu chưa hỗ trợ DEX")
    start: str
    end: str
    risk_per_trade_pct: Optional[float] = Field(None, gt=0.0, le=5.0)
    stop_fill: str = Field("level", pattern="^(level|extreme)$")
    regime: bool = Field(False, description="Bật lọc regime + cầu chì (core/regime, strategy.book.REGIME_MAP)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    mode: str = Field("basic", **MODE_FIELD)
    data: str = Field("candle", pattern="^(candle|tick)$", description="candle: engine nến; tick: mỗi swap on-chain là một bước khớp lệnh (chỉ DEX có tick đã crawl; "
                                                                      "cửa sổ cắt theo độ phủ tick) — chi phí AMM đúng theo dự trữ pool")
    latency_ms: Optional[int] = Field(None, ge=0, le=3_600_000, description="Chỉ data=tick: trễ từ lúc nến đóng tới lúc bot hành động; bỏ trống = thời gian một block của mạng")
    gas_usd: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Chỉ data=tick: gas mỗi swap (USD); bỏ trống = cấu hình của mạng")


class WfaStrategyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    configs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=batch_jobs.MAX_WFA_CONFIGS,
                                          description="1 cấu hình = tham số cố định (WFA chỉ kiểm OOS cuộn); mode=basic: bỏ qua, dùng preset")


class WfaRequest(_DateRange):
    report_dir: Optional[str] = Field(None, max_length=256, description="Lần chạy build_strategy_book trong data/_cache/book/")
    include_rejected: bool = False
    candidates: Optional[List[str]] = Field(None, max_length=16)
    strategies: Optional[List[WfaStrategyIn]] = Field(None, max_length=batch_jobs.MAX_WFA_STRATEGIES,
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
                        description="learn: mỗi fold học bảng regime ↔ chiến lược trên train rồi áp lên test (core/regime/learn.py)")

    @model_validator(mode="after")
    def _one_source(self):
        if sum(map(bool, (self.report_dir, self.candidates, self.strategies))) != 1:
            raise ValueError("chọn đúng một: report_dir, candidates hoặc strategies")
        return self


class McRequest(BaseModel):
    wfa_job_id: Optional[str] = Field(None, max_length=64, description="Job book_wfa đã xong (lấy chuỗi lợi suất ngày OOS)")
    daily_returns: Optional[List[float]] = Field(None, min_length=MC_MIN_DAYS, max_length=MC_MAX_DAYS,
                                                 description="Lợi suất ngày dạng số thập phân (0.01 = 1%)")
    basis: str = Field("extreme", pattern="^(extreme|level)$")
    simulations: int = Field(MC_MIN_SIMULATIONS, ge=100, le=MC_MAX_SIMULATIONS,
                             description="< 10.000 vẫn chạy nhưng gate.gate_eligible = false (không dùng làm gate); tối đa 50.000")
    block_days: int = Field(5, ge=1, le=30)
    horizon_days: int = Field(365, ge=5, le=730)
    ruin_threshold_pct: float = Field(30.0, gt=0.0, le=100.0)
    seed: int = Field(7, ge=0, le=2**31 - 1)
    scale: float = Field(1.0, gt=0.0, le=10.0)
    stress_max_mdd_pct: float = Field(STRESS_MAX_MDD_PCT, gt=0.0, le=100.0, description="MDD tối đa cho phép của MỌI kịch bản cực xấu (gate)")
    extra_cost_daily_pct: Optional[float] = Field(None, ge=0.0, le=5.0,
                                                  description="Phí bổ sung (%/ngày hoạt động) cho kịch bản cost_x2; bỏ trống = hằng số bảo thủ 0,07%")
    mode: str = Field("basic", **MODE_FIELD)
    stress_scenarios: Optional[List[str]] = Field(None, max_length=9, description="Chỉ advanced: tập con kịch bản cực xấu (mặc định đủ cả); thiếu -> custom_gates")

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.wfa_job_id) == bool(self.daily_returns):
            raise ValueError("chọn đúng một: wfa_job_id hoặc daily_returns")
        return self


class PublishRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64, description="Job book_build đã xong có alphas/book.json")


class BuildRequest(BaseModel):
    only: Optional[List[str]] = Field(None, max_length=16)
    n: Optional[int] = Field(None, ge=1, le=batch_jobs.MAX_BUILD_CONFIGS,
                             description="Số cấu hình thử mỗi chiến lược ở dev1 (mặc định 24). Tổng > 200.000 cần force_large")
    keep_top: Optional[int] = Field(None, ge=3, le=5000, description="Số hàng tốt nhất mỗi chiến lược giữ trong kết quả (mặc định 50)")
    force_large: bool = Field(False, description="Cho phép tổng số cấu hình vượt trần 200.000 của CLI (--force-large)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")


# ─── Đọc sổ / báo cáo ───────────────────────────────────────────────────────
def book_path() -> str:
    """Sổ đang dùng (crawl.store.alpha_file: alpha/book.json, cũ alphas/book.json; NORA_BOOK_PATH / NORA_ALPHAS_DIR ghi đè)."""
    return alpha_file("book")


def _metrics(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: m[k] for k in _METRIC_KEYS if k in m} if isinstance(m, dict) else None


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
    """Giá trị GIỮA của mỗi khoá trong không gian tham số (cùng quy tắc backend/core/backtest/run_book_backtest._mid_params)."""
    return {k: v[len(v) // 2] for k, v in space.items()}


def _assets() -> List[Dict[str, Any]]:
    """Tài sản có dữ liệu: [{symbol, venue cex|dex, market perp|spot, candles{start_ts,end_ts}, ticks{start_ts,end_ts,rows,window_days}|null, network?, fee_rate?}]
    — để UI chọn tài sản + chế độ (nến / tick). Chỉ DEX có tick; network / fee_rate (phí pool) của DEX lấy từ manifest / dex_pool.json."""
    from backend.core.backtest import dex
    from backend.db.data_layout import list_assets
    from backend.db.tick_storage import tick_coverage
    ticks = {c["symbol"]: {k: c[k] for k in ("start_ts", "end_ts", "rows", "window_days")} for c in tick_coverage()}
    out = []
    for it in list_assets():
        if it["venue"] not in ("cex", "dex"):
            continue
        manifest = _read_json(os.path.join(it["path"], "manifest.json")) or {}
        row = {"symbol": it["symbol"], "venue": it["venue"], "market": "perp" if it["instrument"] == "perp" else "spot",
               "candles": {"start_ts": manifest.get("start_ts"), "end_ts": manifest.get("end_ts")}, "ticks": ticks.get(it["symbol"]) if it["venue"] == "dex" else None}
        if it["venue"] == "dex":
            row["network"] = manifest.get("network")
            try:
                row["fee_rate"] = dex.pool_info(it["symbol"])["fee_rate"]
            except ValueError:
                row["fee_rate"] = None
        out.append(row)
    return out


def _catalog() -> List[Dict[str, Any]]:
    from backend.core.strategy.book import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"], "default_params": default_params(c["space"])} for c in CANDIDATES]


def _universe_windows(book: Optional[Dict[str, Any]]):
    """(universe, windows dạng ngày): lấy từ sổ nếu có, không thì từ vũ trụ + dữ liệu hiện có (như build_strategy_book.windows)."""
    from backend.core.strategy.book import perp_symbols
    universe = (book or {}).get("universe") or perp_symbols()
    windows = (book or {}).get("windows")
    if not windows:
        try:
            import pandas as pd
            from backend.db.local_pkl import read_manifest
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
@router.get("/")
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
    from backend.utils.engine_version import book_engine_status
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
def get_alphas():
    """Kho alpha: registry.json + book.json (null nếu chưa có)."""
    from backend.utils.engine_version import book_engine_status, engine_version
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
    return batch_jobs.http_launch("alpha_revalidate", {"alpha_id": alpha_id, "apply": bool(apply)})


def _launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    try:
        job_params = batch_jobs.build_job(kind, params)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))
    return batch_jobs.http_launch(kind, job_params)


@router.post("/backtest")
def post_backtest(req: BacktestRequest):
    if not req.strategies and not os.path.isfile(book_path()):
        raise HTTPException(409, "chưa có data/alphas/book.json — truyền strategies hoặc dựng sổ trước (POST /build)")
    return modes.launch_backtest(req)


@router.post("/wfa")
def post_wfa(req: WfaRequest):
    return modes.launch_wfa(req)


@router.post("/build")
def post_build(req: BuildRequest):
    return _launch("book_build", req.model_dump())


@router.post("/publish")
def post_publish(req: PublishRequest):
    """Xuất bản sổ của một job book_build đã xong sang alphas/ (thay sổ hiện hành). Build KHÔNG tự ghi đè alphas/."""
    from backend.optimize.registry import publish_book
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
        raise HTTPException(409, "job này không có alphas/book.json (không dựng ra sổ, hoặc chạy trước khi build tách khỏi alphas/)")
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"không xuất bản được: {e}")
    return {"published": True, "job_id": req.job_id, **out}


@router.get("/jobs")
def get_jobs(limit: int = 20, kind: Optional[str] = None):
    try:
        return {"jobs": batch_jobs.list_jobs(limit, kind)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


@router.get("/jobs/{job_id}")
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


@router.post("/jobs/{job_id}/cancel")
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
    """Thư mục lần chạy (có results.sqlite) của một job build: progress.json (khi đang chạy) hoặc result.json (khi xong); phải nằm trong thư mục lượt chạy (crawl.store.is_within(…, "runs"); cũ: data/_cache/)."""
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


@router.get("/jobs/{job_id}/stage_a")
def get_stage_a(job_id: str, candidate: Optional[str] = None, offset: int = 0, limit: int = 100, sort: str = "order"):
    """Phân trang MỌI cấu hình dev1 đã chạy (đọc kho results.sqlite của job dựng sổ; result.stage_a chỉ có top-K).
    sort=order (thứ tự lấy mẫu) | score (điểm cao -> thấp). Mỗi hàng: {ord, params, dev1{ret_pct,mdd_pct,trades,symbols_positive,sharpe}, score|null, passed}."""
    from backend.optimize.store import ResultsStore
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
@router.post("/mc")
def post_mc(req: McRequest):
    """Block bootstrap (mặc định 10.000 kịch bản) lợi suất ngày OOS của một job book_wfa (hoặc chuỗi tự gửi); trả tóm tắt + fan + histogram
    + `stress` (kịch bản cực xấu tất định + worst_bootstrap) + `worst_path` + `gate` (checks thực tế/yêu cầu, gate_eligible).
    mode=basic: bỏ qua mọi tham số MC của client (10.000 kịch bản, đủ 6 kịch bản cực xấu, gate chuẩn).
    mode=advanced: dùng tham số client; ngưỡng gate khác chuẩn / < 10.000 kịch bản / thiếu kịch bản cực xấu -> params.custom_gates=true (không promote được)."""
    from backend.carlo.monte_carlo import evaluate_mc_gate, extra_cost_from_turnover, run_monte_carlo_daily_detail
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
    else:
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
    out["gate"]["custom_gates"] = custom
    if custom:
        out["gate"]["gate_eligible"] = False   # kết quả dùng ngưỡng tuỳ chỉnh không bao giờ là gate
    out = with_gate_thresholds(out)
    out["params"].update(turnover_daily=turnover, source=source, basis=req.basis, mode=cfg["mode"], custom_gates=custom, promotable=not custom,
                         ignored_client_params=cfg["ignored_client_params"])
    return out
