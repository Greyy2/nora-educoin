"""Lớp dùng chung cho các router: kiểm tham số job (ngày, tài sản, số, thư mục báo cáo, cấu hình WFA), dựng params cho book_backtest / book_wfa /
custom_backtest, http_launch, chế độ chạy Cơ bản/Nâng cao (preset khoá sẵn vs mọi tham số chỉnh được) và endpoint GET /api/studio/meta.

`http_launch` gọi `_proc.launch` (tra cứu thuộc tính lúc gọi nên monkeypatch `launch` có hiệu lực). Job chạy ở tiến trình riêng: backend/jobs/runner.py.
"""
import calendar
import math
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

from fastapi import HTTPException, APIRouter, Header, Response

from backend.jobs import runner as _proc, runner as batch_jobs
from backend.jobs.runner import DEX_UNSUPPORTED, JobBusy, JobError, KINDS, NotReady
from backend.carlo.carlo import MC_RUIN_THRESHOLD_PCT, STRESS_LABELS_VI, VERTICAL_NAMES
from backend.models.params import BASE_RISK_PER_TRADE_PCT
from backend.strategies import BY_ID, FieldError, lift_frames, validate_params
from backend.models.storage import read_json
from backend import strategies as presets_mod
from backend.models.meta import build_meta


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_WFA_STRATEGIES, MAX_WFA_CONFIGS = 16, 50


# ─── Kiểm đối số ────────────────────────────────────────────────────────────
def check_date(value: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise JobError(f"ngày phải dạng YYYY-MM-DD: {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise JobError(f"ngày không tồn tại: {value!r}")
    return value


def check_symbols(symbols: List[str]) -> List[str]:
    """Chuẩn hoá 'BTC' / 'BTC@perp' -> 'BTC@perp'; chỉ nhận tài sản trong vũ trụ của sổ chiến lược (WFA, phễu: chưa hỗ trợ DEX)."""
    from backend.data.data import require_perp
    from backend.strategies import UNIVERSE
    try:
        require_perp(symbols, "WFA / phễu")
    except ValueError as e:
        raise JobError(str(e))
    out = []
    for s in symbols:
        base = str(s).split("@")[0].upper()
        if (("@" in str(s)) and str(s).split("@", 1)[1] != "perp") or base not in UNIVERSE:
            raise JobError(f"tài sản không thuộc vũ trụ {UNIVERSE} (perp): {s!r}")
        if f"{base}@perp" not in out:
            out.append(f"{base}@perp")
    return out


def check_backtest_symbols(symbols: List[str]) -> List[str]:
    """Ký hiệu backtest -> ký hiệu engine (perp, qua check_symbols). Tài sản DEX -> NotReady (501): Nautilus không có AMM."""
    from backend.data.data import parse_symbol
    if any(parse_symbol(str(s))[0] == "dex" for s in symbols):
        raise NotReady(DEX_UNSUPPORTED)
    return check_symbols(symbols)


def _day_ms(day: str, plus_days: int = 0) -> int:
    return (calendar.timegm(time.strptime(day, "%Y-%m-%d")) + plus_days * 86_400) * 1000


def check_candidate_ids(ids: List[str]) -> List[str]:
    from backend.strategies import BY_ID
    known = set(BY_ID)
    bad = [i for i in ids if i not in known]
    if bad:
        raise JobError(f"không có chiến lược {bad}; có: {sorted(known)}")
    return list(dict.fromkeys(ids))


def check_number(value: Any, name: str, lo: float, hi: float, integer: bool = False) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise JobError(f"{name} phải là số: {value!r}")
    if not math.isfinite(x) or not lo <= x <= hi:
        raise JobError(f"{name} ngoài khoảng [{lo}, {hi}]: {value!r}")
    return int(x) if integer else x


def check_report_dir(report_dir: str) -> str:
    """Thư mục lần chạy build_strategy_book: tên thư mục hoặc đường dẫn nằm TRONG alpha_run_dir("book") (cũ <data>/alpha/book/), có stage_a.json + report.json."""
    from backend.models.storage import alpha_run_dir
    base = os.path.realpath(alpha_run_dir("book"))
    path = os.path.realpath(report_dir if os.path.isabs(report_dir) else os.path.join(base, report_dir))
    if os.path.dirname(path) != base:
        raise JobError("report_dir phải là một lần chạy trong thư mục sổ (data/alpha/book/)")
    for name in ("stage_a.json", "report.json"):
        if not os.path.isfile(os.path.join(path, name)):
            raise JobError(f"report_dir thiếu {name}")
    return path


def check_wfa_strategies(items: Any) -> List[Dict[str, Any]]:
    """[{"id", "configs": [{tham số: giá trị}]}] do người dùng chọn: id thuộc thư viện; khoá thuộc `space` hoặc `params_schema` của ứng viên;
    giá trị là số hữu hạn, riêng khoá kiểu "choice" (khung thời gian) là chuỗi nằm trong danh sách lựa chọn."""
    from backend.strategies import BY_ID
    by_id = BY_ID
    if not isinstance(items, list) or not items or len(items) > MAX_WFA_STRATEGIES:
        raise JobError(f"strategies phải là danh sách 1..{MAX_WFA_STRATEGIES} chiến lược")
    ids = check_candidate_ids([s.get("id") if isinstance(s, dict) else None for s in items])
    if len(ids) != len(items):
        raise JobError("id chiến lược bị lặp")
    out = []
    for s in items:
        cfgs = s.get("configs")
        if not isinstance(cfgs, list) or not 1 <= len(cfgs) <= MAX_WFA_CONFIGS:
            raise JobError(f"{s['id']}: configs phải có 1..{MAX_WFA_CONFIGS} cấu hình")
        cand = by_id[s["id"]]
        schema = cand.get("params_schema") or {}
        for c in cfgs:
            if not isinstance(c, dict) or not all(isinstance(k, str) for k in c):
                raise JobError(f"{s['id']}: mỗi cấu hình phải là {{tên: giá trị}}")
            bad = sorted(set(c) - set(cand["space"]) - set(schema))
            if bad:
                raise JobError(f"{s['id']}: khoá không thuộc không gian tham số / lược đồ tham số: {bad}")
            for k, v in c.items():
                spec = schema.get(k) or {}
                if spec.get("type") == "choice":
                    if v not in spec["choices"]:
                        raise JobError(f"{s['id']}: {k} phải là một trong {spec['choices']}")
                elif not (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)):
                    raise JobError(f"{s['id']}: {k} phải là số hữu hạn")
        out.append({"id": s["id"], "configs": cfgs})
    return out


RUN_TIMEFRAMES = ("1m", "15m", "1h", "4h")   # khung chạy (nến mô phỏng); API mở 15m/1h/4h, 1m giữ cho đường nội bộ


def check_timeframe(value: Any) -> str:
    if value not in RUN_TIMEFRAMES:
        raise JobError(f"timeframe phải là một trong {list(RUN_TIMEFRAMES)}")
    return str(value)


def build_job(kind: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Từ tham số đã qua pydantic -> params của job (kiểm lại ở đây: tầng này không tin router)."""
    if kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    out: Dict[str, Any] = {}
    if kind == "book_backtest":
        if p.get("strategies"):
            ids = check_candidate_ids([s["id"] for s in p["strategies"]])
            if len(ids) != len(p["strategies"]):
                raise JobError("id chiến lược bị lặp")
            items = []
            for s in p["strategies"]:
                prm = s.get("params") or {}
                if not isinstance(prm, dict) or not all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                                        and math.isfinite(v) for k, v in prm.items()):
                    raise JobError("params phải là {tên: số}")
                items.append({"id": s["id"], "params": prm})
            out["strategies"] = items
        if p.get("symbols"):
            out["symbols"] = check_backtest_symbols(p["symbols"])
        out["start"], out["end"] = check_date(p["start"]), check_date(p["end"])
        if p["start"] >= p["end"]:
            raise JobError("start phải trước end")
        if p.get("risk_per_trade_pct") is not None:
            out["risk_per_trade"] = check_number(p["risk_per_trade_pct"], "risk_per_trade_pct", 0.01, 5.0)
        if p.get("stop_fill"):
            if p["stop_fill"] not in ("level", "extreme"):
                raise JobError("stop_fill phải là level|extreme")
            out["stop_fill"] = p["stop_fill"]
        if p.get("regime"):
            out["regime"] = True
        if p.get("timeframe"):
            out["timeframe"] = check_timeframe(p["timeframe"])
        if (p.get("data") or "candle") not in ("candle", "tick"):
            raise JobError("data phải là candle|tick")
        if p.get("data") == "tick":
            raise NotReady(DEX_UNSUPPORTED)   # backtest tick = swap AMM on-chain (chỉ DEX)
    elif kind == "book_wfa":
        if p.get("timeframe"):
            out["timeframe"] = check_timeframe(p["timeframe"])
        if p.get("regime", "off") != "off":
            if p["regime"] != "learn":
                raise JobError("regime phải là off|learn")
            out["regime"] = "learn"
        if sum(map(bool, (p.get("report_dir"), p.get("candidates"), p.get("strategies")))) != 1:
            raise JobError("chọn đúng một: report_dir, candidates hoặc strategies")
        if p.get("report_dir"):
            out["report"] = check_report_dir(p["report_dir"])
            if p.get("include_rejected"):
                out["include_rejected"] = True
        elif p.get("strategies"):
            out["strategies"] = check_wfa_strategies(p["strategies"])
        else:
            out["candidates"] = check_candidate_ids(p["candidates"])
        out["n"] = check_number(p.get("n", 3), "n", 1, 50, integer=True)
        for key in ("start", "end"):
            if p.get(key):
                out[key] = check_date(p[key])
        if p.get("start") and p.get("end") and p["start"] >= p["end"]:
            raise JobError("start phải trước end")
        if p.get("symbols"):
            out["symbols"] = check_symbols(p["symbols"])
        for key, lo, hi in (("train_days", 7, 1000), ("test_days", 1, 365), ("step_days", 1, 365), ("sims", 100, 50_000), ("mc_seed", 0, 2 ** 31 - 1)):
            if p.get(key) is not None:
                out[key] = check_number(p[key], key, lo, hi, integer=True)
        if p.get("risk_per_trade_pct") is not None:
            out["risk_per_trade"] = check_number(p["risk_per_trade_pct"], "risk_per_trade_pct", 0.01, 5.0)
    elif kind == "custom_backtest":
        out = build_custom_backtest(p)
    else:
        raise JobError(f"{kind}: dựng params ở router của nó")
    return out


MAX_CUSTOM_DAYS = 4000
MAX_CUSTOM_SYMBOLS = 16
_BASE_RE = re.compile(r"^[A-Z0-9]{2,12}$")


def build_custom_backtest(p: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số job custom_backtest (chiến lược Python): kiểm code bằng chính trình biên dịch (lỗi -> JobError kèm dòng/cột), rổ, ngày, vốn, vị thế."""
    from backend.models.params import POSITION_KEYS
    from backend.signal.nodes import DslError
    from backend.alpha.compile import compile_code
    from backend.alpha.contract import MAX_CODE_CHARS
    from backend.models.params import FRAMES
    from backend.data.data import base_name
    out: Dict[str, Any] = {}
    code = p.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
        raise JobError(f"code phải là chuỗi không rỗng, tối đa {MAX_CODE_CHARS} ký tự")
    try:
        compile_code(code, register=False)
    except DslError as e:
        raise JobError(f"Lỗi biên dịch chiến lược: {e}")
    out["code"] = code
    if p.get("symbols"):
        if not isinstance(p["symbols"], list) or len(p["symbols"]) > MAX_CUSTOM_SYMBOLS:
            raise JobError(f"symbols phải là danh sách tối đa {MAX_CUSTOM_SYMBOLS} tài sản")
        names = list(dict.fromkeys(base_name(str(s)) for s in p["symbols"]))
        bad = [n for n in names if not _BASE_RE.match(n)]
        if bad:
            raise JobError(f"tên tài sản không hợp lệ: {bad}")
        out["symbols"] = names
    out["start"], out["end"] = check_date(p["start"]), check_date(p["end"])
    if p["start"] >= p["end"]:
        raise JobError("start phải trước end")
    if (_day_ms(p["end"], 1) - _day_ms(p["start"])) / 86_400_000 > MAX_CUSTOM_DAYS:
        raise JobError(f"khoảng chạy tối đa {MAX_CUSTOM_DAYS} ngày")
    if p.get("train_ratio") is not None:
        out["train_ratio"] = check_number(p["train_ratio"], "train_ratio", 0.1, 0.95)
    if p.get("initial_capital") is not None:
        out["initial_capital"] = check_number(p["initial_capital"], "initial_capital", 100.0, 1e9)
    if p.get("position"):
        pos = p["position"]
        if not isinstance(pos, dict):
            raise JobError("position phải là {khoá: giá trị}")
        bad = sorted(set(map(str, pos)) - set(POSITION_KEYS))
        if bad:
            raise JobError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
        for k, v in pos.items():
            if isinstance(v, bool) or not (isinstance(v, str) or (isinstance(v, (int, float)) and math.isfinite(v))):
                raise JobError(f"position.{k} phải là số hữu hạn hoặc chuỗi")
        out["position"] = pos
    if p.get("run_frame"):
        if p["run_frame"] not in FRAMES:
            raise JobError(f"run_frame phải thuộc {list(FRAMES)}")
        out["run_frame"] = p["run_frame"]
    return out


# ─── Khởi chạy job ───────────────────────────────────────────────────────────


def http_launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    """launch() cho router: JobError -> HTTP 422, JobBusy -> 429. Trả {"job_id"}."""
    from fastapi import HTTPException
    try:
        return {"job_id": _proc.launch(kind, params)}
    except JobError as e:
        raise HTTPException(422, str(e))
    except JobBusy as e:
        raise HTTPException(429, str(e))




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
STANDARD_MC = {"block_days": 5, "horizon_days": 365, "ruin_threshold_pct": MC_RUIN_THRESHOLD_PCT, "seed": 7, "scale": 1.0}
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
# Chế độ chạy Cơ bản / Nâng cao cho backtest, WFA, Monte Carlo (lớp API; logic kiểm tham số ở backend/strategies.py).
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
    out = http_launch(kind, params)
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
        return build_job(kind, payload)
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


# ─── WFA ─────────────────────────────────────────────────────────────────────
def _with_configs(params: Dict[str, Any], cfgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """build_job dựng nguồn `candidates`; thay bằng đúng các cấu hình đã giải quyết (tầng job kiểm lại, không tin router)."""
    out = {k: v for k, v in params.items() if k != "candidates"}
    out["strategies"] = check_wfa_strategies(cfgs)
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


# ─── Metadata cho UI (lắp ráp ở models/meta.py) ─────────────────────────────


meta_router = APIRouter(prefix="/api/studio", tags=["meta"])


def _limit_models() -> Dict[str, Any]:
    from backend.routes.alpha import CustomBacktestRequest
    from backend.routes.book import BacktestRequest, McRequest, WfaStrategyIn, _DateRange
    from backend.routes.data import CrawlRequest
    return {"custom_backtest": CustomBacktestRequest, "book_backtest": _DateRange, "book_wfa": WfaStrategyIn, "book_mc": McRequest,
            "data_update": CrawlRequest, "book_backtest_req": BacktestRequest}


@meta_router.get("/meta")
def get_studio_meta(response: Response, if_none_match: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Metadata UI từ nguồn thật, kèm ETag (If-None-Match khớp -> 304)."""
    meta = build_meta(_limit_models())
    etag = f'"{meta["version"]}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return meta


ROUTERS = [meta_router]
