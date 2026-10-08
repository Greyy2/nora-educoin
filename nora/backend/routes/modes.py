"""Chế độ chạy Cơ bản / Nâng cao (P9.8): hằng số + gộp tham số job (core/params/modes, phần chỉ-API) và lớp API (api/modes.py): preset, kiểm params_schema, nhãn custom_gates/promotable.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8). Nhóm dùng cho engine/phễu (FieldError, check_value, validate_params, schema_space, SCHEMA_SPACE_EXCLUDE, frame_keys, lift_frame, lift_frames, _num, _unit) nằm ở optimize/book/build.py và được import lại ở đây.
"""
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from backend.optimize.process import process as batch_jobs
from backend.routes import jobs as batch_jobs_routes
from backend.carlo.carlo import STRESS_LABELS_VI, VERTICAL_NAMES
from backend.core.params import BASE_RISK_PER_TRADE_PCT
from backend.optimize.book.build import BY_ID
from backend.crawl.store import read_json
from backend.optimize.book import build as presets_mod
from backend.optimize.book.build import FieldError, lift_frames, validate_params


# ══════════════════════════════════════════════════════════════════════════
# Chế độ chạy: Cơ bản (basic = preset khoá sẵn) / Nâng cao (advanced = mọi tham số chỉnh được, kiểm theo params_schema).
#
# Module thuần (không FastAPI): kiểm tham số theo params_schema của chiến lược, điền khoá thiếu từ preset, rút tham số tối thiểu cho job,
# và phân loại "custom_gates" (kết quả dùng ngưỡng gate khác chuẩn -> không được xuất bản/promote). Lớp API: backend/routes/modes.py.
# Mọi thông báo lỗi bằng tiếng Việt, gắn theo TRƯỜNG: [{"field": "strategies[0].params.sig.ema_fast", "message": "..."}].
# ══════════════════════════════════════════════════════════════════════════

MODES = ("basic", "advanced")
MAX_STRATEGIES = 9                 # số chiến lược lõi (strategy.book.CANDIDATES)
DEFAULT_TRAIN_DAYS, DEFAULT_TEST_DAYS = 120, 30   # fold mặc định của WFA (validate_book)
STANDARD_MC_SIMULATIONS = 10_000    # = carlo.carlo.MC_MIN_SIMULATIONS
STANDARD_MC = {"block_days": 5, "horizon_days": 365, "ruin_threshold_pct": 30.0, "seed": 7, "scale": 1.0}
# 6 kịch bản luôn có + 3 kịch bản trend thẳng đứng (chỉ có khi nguồn biết vị thế, vd. WFA — carlo.vertical_exposure)
STRESS_VERTICAL = VERTICAL_NAMES
STRESS_BASE = tuple(n for n in STRESS_LABELS_VI if n not in VERTICAL_NAMES)     # ("worst_days_first", "reversed_order", "crash_day", "cost_x2", "longest_losing_streak_x2", "worst_bootstrap")
STRESS_NAMES = STRESS_BASE + STRESS_VERTICAL


def job_params(candidate: Dict[str, Any], full: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số TỐI THIỂU truyền cho job: mọi khoá của `space` (để run_book_backtest không điền mức giữa đè lên) + khoá khác mặc định schema.
    `risk_per_trade_pct` không đi theo tham số (job nhận qua --risk-per-trade)."""
    schema, space = candidate["params_schema"], candidate["space"]
    out = {}
    for key, value in full.items():
        if key == "risk_per_trade_pct":
            continue
        if key in space or value != schema[key]["default"]:
            out[key] = value
    return out


def common_risk(items: List[Tuple[str, Dict[str, Any]]], override: Optional[float] = None) -> Tuple[Optional[float], List[FieldError]]:
    """Mức rủi ro/lệnh dùng chung cho cả lần chạy: `override` nếu có, không thì mọi chiến lược phải cùng một mức (job chỉ nhận một --risk-per-trade)."""
    if override is not None:
        return float(override), []
    values = {}
    for i, (cid, full) in enumerate(items):
        values.setdefault(full.get("risk_per_trade_pct"), []).append((i, cid))
    values.pop(None, None)
    if len(values) <= 1:
        return (next(iter(values)) if values else None), []
    detail = "; ".join(f"{v}% ({', '.join(c for _, c in rows)})" for v, rows in values.items())
    i = list(values.values())[1][0][0]
    return None, [(f"strategies[{i}].params.risk_per_trade_pct",
                   f"Rủi ro mỗi lệnh phải GIỐNG NHAU giữa các chiến lược trong một lần chạy (danh mục dùng chung một mức): {detail}")]


def mc_standard(simulations: int, ruin_threshold_pct: float, stress_max_mdd_pct: float, stress: Optional[List[str]],
                standard_stress_max_mdd_pct: float) -> bool:
    """True nếu cấu hình MC là gate CHUẨN (>= 10.000 kịch bản, ngưỡng cháy 30%, MDD cực xấu chuẩn, đủ 6 kịch bản cực xấu cơ bản).
    Bỏ kịch bản trend thẳng đứng khi nguồn có vị thế -> API /mc tự gắn custom (chỉ ở đó mới biết nguồn)."""
    full_set = stress is None or set(STRESS_BASE) <= set(stress)
    return (simulations >= STANDARD_MC_SIMULATIONS and float(ruin_threshold_pct) == STANDARD_MC["ruin_threshold_pct"]
            and float(stress_max_mdd_pct) == float(standard_stress_max_mdd_pct) and full_set)


# ─── Khung chạy (nến mô phỏng) ───────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════
# Chế độ chạy Cơ bản / Nâng cao cho backtest, WFA, Monte Carlo (lớp API; logic kiểm tham số ở backend/optimize/book/build.py).
#
# basic     MÁY CHỦ bỏ qua tham số do client gửi, dùng preset (data/alpha/presets.json) của các chiến lược được chọn (tối đa 7);
#           WFA fold mặc định 120/30 và gate chuẩn; MC 10.000 kịch bản + đủ 6 kịch bản cực xấu + gate chuẩn.
# advanced  kiểm MỌI tham số theo params_schema (kiểu, khoảng, khung thời gian, cột kernel, ngân sách DCA) -> 422 tiếng Việt theo từng trường.
#           Đổi ngưỡng gate / < 10.000 kịch bản MC => `custom_gates: true`, `promotable: false` (publish/promote trả 409).
# Job nền giữ `mode`, `resolved` (tham số ĐẦY ĐỦ đã giải quyết), `custom_gates`, `promotable` trong job.json -> GET /jobs/{id} trả lại nguyên vẹn.
# ══════════════════════════════════════════════════════════════════════════

# WFA nhận tham số ngoài `space` (chu kỳ chỉ báo, khung thời gian...): validate_book.candidates_from_json và
# batch.check_wfa_strategies chấp nhận khoá của params_schema.
WFA_SCHEMA_KEYS_SUPPORTED = True


def http_422(errors: List[FieldError]) -> HTTPException:
    """422 theo dạng lỗi chuẩn của FastAPI (loc/msg/type) + `field` dễ đọc."""
    return HTTPException(422, detail=[{"loc": ["body", field], "field": field, "msg": msg, "type": "value_error"} for field, msg in errors])


# ─── Ghi nhãn vào bản ghi job ────────────────────────────────────────────────
def stamp_job(job_id: str, **fields: Any) -> None:
    """Gộp trường vào job.json (dưới cùng khoá với waiter/_finish nên không đua)."""
    jd = batch_jobs.job_dir(job_id)
    with batch_jobs._LOCK:
        meta = batch_jobs._read_meta(jd) or {}
        meta.update(fields)
        batch_jobs._write_meta(jd, meta)


def launch(kind: str, params: Dict[str, Any], stamp: Dict[str, Any]) -> Dict[str, Any]:
    out = batch_jobs_routes.http_launch(kind, params)
    stamp_job(out["job_id"], **stamp)
    tf_mismatch = stamp.get("resolved", {}).get("timeframe_mismatch")
    if tf_mismatch:
        out["timeframe_mismatch"] = tf_mismatch
    return out


def _stamp(mode: str, custom: bool, resolved: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {"mode": mode, "custom_gates": bool(custom), "promotable": not custom, "resolved": resolved, **extra}


def decorate(job: Dict[str, Any]) -> Dict[str, Any]:
    """Phản ánh mode/custom_gates/promotable vào `result` của job đã xong (nếu có) để UI đọc ở một chỗ."""
    if isinstance(job, dict) and job.get("mode"):
        res = job.get("result")
        if isinstance(res, dict):
            res.setdefault("mode", job["mode"])
            res.setdefault("custom_gates", bool(job.get("custom_gates")))
            res.setdefault("promotable", not job.get("custom_gates"))
    return job


# ─── Dùng chung ──────────────────────────────────────────────────────────────
def _check_ids(items: List[Any], field: str) -> List[FieldError]:
    errors: List[FieldError] = []
    ids = [s.id if hasattr(s, "id") else s for s in items]
    if len(ids) > MAX_STRATEGIES:
        errors.append((field, f"Tối đa {MAX_STRATEGIES} chiến lược, nhận {len(ids)}"))
    for i, cid in enumerate(ids):
        if cid not in BY_ID:
            errors.append((f"{field}[{i}].id", f"Không có chiến lược '{cid}'; có: {sorted(BY_ID)}"))
    dup = sorted({c for c in ids if ids.count(c) > 1})
    if dup:
        errors.append((field, f"id chiến lược bị lặp: {dup}"))
    return errors


def _book_strategies() -> List[Dict[str, Any]]:
    book = read_json(presets_mod.book_path())
    return [{"id": s["id"], "params": s.get("params") or {}, "source": "book.json"} for s in (book or {}).get("strategies", [])]


def _basic_risk(items: List[Tuple[str, Dict[str, Any]]]) -> float:
    vals = [full.get("risk_per_trade_pct") for _, full in items if full.get("risk_per_trade_pct") is not None]
    return min(vals) if vals else BASE_RISK_PER_TRADE_PCT


def _timeframe_errors(fulls: List[Tuple[str, Dict[str, Any]]], timeframe: str, field: str) -> List[FieldError]:
    """Khung tín hiệu không nâng lên được tới khung chạy (vd. trend_long entry_tf tối đa 1h, chạy 4h) -> lỗi 422 trước khi tạo job
    (trước đây job chạy rồi mới hỏng)."""
    errs: List[FieldError] = []
    for i, (cid, full) in enumerate(fulls):
        try:
            lift_frames(BY_ID[cid], full, timeframe)
        except ValueError as e:
            errs.append((f"{field}[{i}]", f"{e}. Chọn khung chạy nhỏ hơn hoặc bỏ chiến lược này"))
    return errs


# ─── Backtest ────────────────────────────────────────────────────────────────
def launch_backtest(req) -> Dict[str, Any]:
    mode = req.mode
    presets = presets_mod.load_presets()
    resolved: Dict[str, Any] = {"symbols": req.symbols, "start": req.start, "end": req.end, "timeframe": req.timeframe, "data": req.data}
    ignored = False
    if not req.strategies:   # không chọn chiến lược: dùng nguyên sổ data/alpha/book.json (như trước)
        book_tf = presets_mod.book_timeframe()
        if mode == "basic" and req.timeframe != book_tf:
            resolved["timeframe_mismatch"] = f"Khung chạy ({req.timeframe}) khác khung của sổ ({book_tf})"
        payload = {"symbols": req.symbols, "start": req.start, "end": req.end, "risk_per_trade_pct": req.risk_per_trade_pct if mode == "advanced" else None,
                   "stop_fill": req.stop_fill if mode == "advanced" else "level", "regime": req.regime,
                   "timeframe": req.timeframe, "data": req.data, "latency_ms": req.latency_ms, "gas_usd": req.gas_usd}
        resolved.update(regime=req.regime, source="book.json", strategies=_book_strategies(), risk_per_trade_pct=payload["risk_per_trade_pct"],
                        stop_fill=payload["stop_fill"])
        return launch("book_backtest", _build("book_backtest", payload), _stamp(mode, False, resolved, ignored_client_params=False))
    errors = _check_ids(req.strategies, "strategies")
    if errors:
        raise http_422(errors)
    fulls: List[Tuple[str, Dict[str, Any]]] = []
    mismatches: Dict[str, str] = {}
    for i, s in enumerate(req.strategies):
        cand = BY_ID[s.id]
        if mode == "basic":
            ignored = ignored or bool(s.params)
            p_tf = presets[s.id].get("timeframe")
            if p_tf and req.timeframe != p_tf:
                mismatches[s.id] = p_tf
            fulls.append((s.id, dict(presets[s.id]["params"])))
        else:
            full, errs = validate_params(cand, s.params or {}, presets[s.id]["params"], f"strategies[{i}].params")
            errors += errs
            fulls.append((s.id, full))
    errors += _timeframe_errors(fulls, req.timeframe, "strategies")
    if errors:
        raise http_422(errors)
    if mode == "basic" and mismatches:
        detail_tf = ", ".join(f"{cid}: {tf}" for cid, tf in mismatches.items())
        resolved["timeframe_mismatch"] = f"Khung chạy ({req.timeframe}) khác khung tối ưu của preset ({detail_tf})"
    if mode == "basic":
        rpt, stop_fill = _basic_risk(fulls), "level"
    else:
        rpt, errs = common_risk(fulls, req.risk_per_trade_pct)
        if errs:
            raise http_422(errs)
        rpt, stop_fill = (rpt if rpt is not None else BASE_RISK_PER_TRADE_PCT), req.stop_fill
    fulls = [(cid, {**full, "risk_per_trade_pct": rpt}) for cid, full in fulls]
    items = [{"id": cid, "params": job_params(BY_ID[cid], full)} for cid, full in fulls]
    payload = {"symbols": req.symbols, "start": req.start, "end": req.end, "risk_per_trade_pct": rpt, "stop_fill": stop_fill,
               "regime": req.regime, "timeframe": req.timeframe, "data": req.data, "latency_ms": req.latency_ms, "gas_usd": req.gas_usd,
               "strategies": [{"id": cid} for cid, _ in fulls]}   # chỉ để build_job kiểm id (+ chân LONG khi chạy DEX); tham số đầy đủ gắn lại ngay dưới
    params = {**_build("book_backtest", payload), "strategies": items}
    resolved.update(regime=req.regime, source="presets" if mode == "basic" else "client+presets", risk_per_trade_pct=rpt, stop_fill=stop_fill,
                    strategies=[{"id": cid, "params": full,
                                 "preset_source": presets[cid]["source"] if mode == "basic" else None} for cid, full in fulls])
    return launch("book_backtest", params, _stamp(mode, False, resolved, ignored_client_params=ignored))


def _build(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return batch_jobs_routes.build_job(kind, payload)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


# ─── WFA ─────────────────────────────────────────────────────────────────────
def _with_configs(params: Dict[str, Any], cfgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """build_job dựng nguồn `candidates`; thay bằng đúng các cấu hình đã giải quyết (tầng job kiểm lại, không tin router)."""
    out = {k: v for k, v in params.items() if k != "candidates"}
    out["strategies"] = batch_jobs_routes.check_wfa_strategies(cfgs)
    return out


def launch_wfa(req) -> Dict[str, Any]:
    mode = req.mode
    presets = presets_mod.load_presets()
    resolved: Dict[str, Any] = {"symbols": req.symbols, "start": req.start, "end": req.end, "timeframe": req.timeframe, "regime": req.regime}
    errors: List[FieldError] = []
    custom = False
    payload: Dict[str, Any] = {"symbols": req.symbols, "start": req.start, "end": req.end, "timeframe": req.timeframe, "regime": req.regime}

    if mode == "basic":
        if req.report_dir:
            raise http_422([("report_dir", "Chế độ Cơ bản không dùng report_dir — chọn chiến lược (candidates/strategies) để chạy bằng bộ tham số tốt nhất")])
        ids = list(req.candidates or [s.id for s in req.strategies or []])
        errors = _check_ids(ids, "candidates" if req.candidates else "strategies")
        if errors:
            raise http_422(errors)
        mismatches: Dict[str, str] = {}
        for cid in ids:
            p_tf = presets[cid].get("timeframe")
            if p_tf and req.timeframe != p_tf:
                mismatches[cid] = p_tf
        if mismatches:
            detail_tf = ", ".join(f"{cid}: {tf}" for cid, tf in mismatches.items())
            resolved["timeframe_mismatch"] = f"Khung chạy ({req.timeframe}) khác khung tối ưu của preset ({detail_tf})"
        fulls = [(cid, dict(presets[cid]["params"])) for cid in ids]
        tf_errs = _timeframe_errors(fulls, req.timeframe, "candidates" if req.candidates else "strategies")
        if tf_errs:
            raise http_422(tf_errs)
        rpt = _basic_risk(fulls)
        cfgs = [{"id": cid, "configs": [job_params(BY_ID[cid], full)]} for cid, full in fulls]
        payload.update(candidates=ids, risk_per_trade_pct=rpt)    # chỉ để build_job dựng các cờ chung; nguồn thật là strategies.json
        resolved.update(source="presets", train_days=DEFAULT_TRAIN_DAYS, test_days=DEFAULT_TEST_DAYS, risk_per_trade_pct=rpt,
                        strategies=[{"id": cid, "configs": [full], "preset_source": presets[cid]["source"]} for cid, full in fulls])
        ignored = bool(req.strategies and any(s.configs for s in req.strategies)) or req.train_days is not None or req.test_days is not None
        return launch("book_wfa", _with_configs(_build("book_wfa", payload), cfgs), _stamp(mode, False, resolved, ignored_client_params=ignored))

    # advanced
    payload.update(train_days=req.train_days, test_days=req.test_days, risk_per_trade_pct=req.risk_per_trade_pct,
                   step_days=req.step_days, sims=req.sims, mc_seed=req.mc_seed)
    if getattr(req, "embargo_days", None):
        errors.append(("embargo_days", "Máy chủ chưa hỗ trợ embargo cho WFA danh mục (validate_book chưa có tham số này); đặt 0 hoặc bỏ trống"))
    if req.sims is not None and req.sims < STANDARD_MC_SIMULATIONS:
        custom = True
    resolved.update(train_days=req.train_days or DEFAULT_TRAIN_DAYS, test_days=req.test_days or DEFAULT_TEST_DAYS,
                    step_days=req.step_days, sims=req.sims, mc_seed=req.mc_seed, risk_per_trade_pct=req.risk_per_trade_pct)
    if req.strategies:
        errors += _check_ids(req.strategies, "strategies")
        cfgs: List[Dict[str, Any]] = []
        res_items = []
        for i, s in enumerate(req.strategies):
            if s.id not in BY_ID:
                continue
            cand = BY_ID[s.id]
            out_cfgs, full_cfgs = [], []
            for j, c in enumerate(s.configs):
                full, errs = validate_params(cand, c, presets[s.id]["params"], f"strategies[{i}].configs[{j}]")
                errors += errs
                if errs:
                    continue
                prm = job_params(cand, full)
                outside = sorted(set(prm) - set(cand["space"]))
                if outside and not WFA_SCHEMA_KEYS_SUPPORTED:
                    errors.append((f"strategies[{i}].configs[{j}]",
                                   f"{s.id}: WFA hiện chỉ nhận tham số thuộc không gian tối ưu {sorted(cand['space'])}; "
                                   f"chưa hỗ trợ đổi {outside} (chu kỳ chỉ báo/khung thời gian). Dùng backtest để thử các tham số này."))
                    continue
                tf_errs = _timeframe_errors([(s.id, full)], req.timeframe, f"strategies[{i}].configs[{j}]")
                if tf_errs:
                    errors.append((f"strategies[{i}].configs[{j}]", tf_errs[0][1]))
                    continue
                out_cfgs.append(prm)
                full_cfgs.append(full)
            cfgs.append({"id": s.id, "configs": out_cfgs})
            res_items.append({"id": s.id, "configs": full_cfgs})
        if errors:
            raise http_422(errors)
        payload["candidates"] = [c["id"] for c in cfgs]
        resolved.update(source="client+presets", strategies=res_items)
        params = _with_configs(_build("book_wfa", payload), cfgs)
    else:   # grid / candidates / report_dir: như trước (số), chỉ thêm cờ mở rộng
        if errors:
            raise http_422(errors)
        payload.update(report_dir=req.report_dir, include_rejected=req.include_rejected, candidates=req.candidates, n=req.n)
        resolved.update(source="report_dir" if req.report_dir else "candidates", report_dir=req.report_dir,
                        candidates=req.candidates, n=req.n)
        params = _build("book_wfa", payload)
    return launch("book_wfa", params, _stamp(mode, custom, resolved, ignored_client_params=False))


# ─── Monte Carlo ─────────────────────────────────────────────────────────────
def resolve_mc(req) -> Dict[str, Any]:
    """Cấu hình MC hiệu lực + cờ custom_gates. basic: bỏ qua mọi tham số client (10.000 kịch bản, đủ kịch bản cực xấu, gate chuẩn)."""
    from backend.carlo.carlo import MC_MIN_SIMULATIONS, STRESS_MAX_MDD_PCT
    if req.mode == "basic":
        return {"mode": "basic", "simulations": MC_MIN_SIMULATIONS, **STANDARD_MC, "stress_max_mdd_pct": STRESS_MAX_MDD_PCT,
                "extra_cost_daily_pct": None, "stress": None, "custom_gates": False,
                "ignored_client_params": req.model_fields_set & {"simulations", "block_days", "horizon_days", "ruin_threshold_pct", "seed", "scale",
                                                                 "stress_max_mdd_pct", "extra_cost_daily_pct", "stress_scenarios"} != set()}
    subset = req.stress_scenarios
    if subset is not None:
        bad = [n for n in subset if n not in STRESS_NAMES]
        if bad or not subset:
            raise http_422([("stress_scenarios", f"Kịch bản cực xấu phải thuộc {list(STRESS_NAMES)} và không rỗng; không hợp lệ: {bad or '[]'}")])
    custom = not mc_standard(req.simulations, req.ruin_threshold_pct, req.stress_max_mdd_pct, subset, STRESS_MAX_MDD_PCT)
    return {"mode": "advanced", "simulations": req.simulations, "block_days": req.block_days, "horizon_days": req.horizon_days,
            "ruin_threshold_pct": req.ruin_threshold_pct, "seed": req.seed, "scale": req.scale, "stress_max_mdd_pct": req.stress_max_mdd_pct,
            "extra_cost_daily_pct": req.extra_cost_daily_pct, "stress": subset, "custom_gates": custom, "ignored_client_params": False}


# Re-export (P9.8): nhóm kiểm tham số dùng cho engine/phễu sống ở optimize/book/build.py (MỘT định nghĩa); giữ truy cập qua routes.modes (đường cũ core.params.modes).
from backend.optimize.book.build import SCHEMA_SPACE_EXCLUDE, check_value, frame_keys, lift_frame, schema_space  # noqa: E402,F401  (FieldError, lift_frames, validate_params đã import ở đầu file)
