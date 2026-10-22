from __future__ import annotations

"""Phân hệ Studio API (backend/routes/studio.py):
Gộp toàn bộ các endpoint phục vụ Studio:
- Process / Jobs / Meta / Custom Backtest
- Book Backtest / WFA / Monte Carlo
- Strategy Alpha Compiler / Presets / Catalog / Assist
- Alpha Research / Top Agents
- Universe Scan
"""

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
from backend.analys.validation.carlo.carlo import MC_RUIN_THRESHOLD_PCT, STRESS_LABELS_VI, VERTICAL_NAMES
from backend.analys.param import BASE_RISK_PER_TRADE_PCT
from backend.analys.alpha.strategies import BY_ID, FieldError, lift_frames, validate_params
from backend.models.storage import read_json
from backend.analys.alpha import strategies as presets_mod
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
    from backend.analys.alpha.strategies import UNIVERSE
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
    from backend.analys.alpha.strategies import BY_ID
    known = set(BY_ID)
    bad = [i for i in ids if i not in known]
    if bad:
        raise JobError(f"không có chiến lược {bad}; có: {sorted(known)}")
    return list(dict.fromkeys(ids))


def check_number(value: Any, name: str, lo: float, hi: float, integer: bool = False) -> Any:
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
    from backend.analys.alpha.strategies import BY_ID
    by_id = BY_ID
    if not isinstance(items, list) or not items or len(items) > MAX_WFA_STRATEGIES:
        raise JobError(f"strategies phải là danh sách 1..{MAX_WFA_STRATEGIES} chiến lược")
    raw_ids = [s.get("id") for s in items if isinstance(s, dict) and s.get("id")]
    if len(raw_ids) != len(items):
        raise JobError("mỗi mục phải là dict có trường 'id' hợp lệ")
    ids = check_candidate_ids([str(i) for i in raw_ids])
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
    from backend.analys.param import POSITION_KEYS
    from backend.analys.signal.signal import DslError
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.code.contract import MAX_CODE_CHARS
    from backend.analys.param import FRAMES
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
# Chế độ chạy Cơ bản / Nâng cao cho backtest, WFA, Monte Carlo (lớp API; logic kiểm tham số ở backend/alpha/strategies.py).
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
    from backend.analys.validation.carlo.carlo import MC_MIN_SIMULATIONS, STRESS_MAX_MDD_PCT
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
    from backend.routes.data import CrawlRequest
    return {
        "custom_backtest": globals().get("CustomBacktestRequest"),
        "book_backtest": globals().get("_DateRange"),
        "book_wfa": globals().get("WfaStrategyIn"),
        "book_mc": globals().get("McRequest"),
        "data_update": CrawlRequest,
        "book_backtest_req": globals().get("BacktestRequest"),
    }



@meta_router.get("/meta")
def get_studio_meta(response: Response, if_none_match: Optional[str] = Header(None)) -> Any:
    """Metadata UI từ nguồn thật, kèm ETag (If-None-Match khớp -> 304)."""
    meta = build_meta(_limit_models())
    etag = f'"{meta["version"]}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return meta




import sys as _sys
batch_jobs_routes = _sys.modules[__name__]
modes = _sys.modules[__name__]
_proc_route = _sys.modules[__name__]

"""API sổ chiến lược: xem sổ hiện tại, chạy backtest / WFA danh mục / Monte Carlo như job nền, trạng thái job, dashboard + lệnh danh mục.

Job nặng chạy ở tiến trình riêng qua ops/run_limited.sh (backend/jobs/runner.py); handler ở đây chỉ validate + khởi chạy / đọc file
nên nhanh và là `def` thường (FastAPI chạy trong threadpool). Logic Monte Carlo ở carlo/carlo.py (mc_report).
"""
import json
import math
import os
import threading
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.data.data import benchmark_daily_closes
from backend.analys.metrics import charts as feeds
from backend.analys.metrics import charts as pd_mod
# process merged
from backend.jobs import runner as batch_jobs
# process merged
from backend.models.storage import alpha_file
from backend.analys.validation.carlo.carlo import mc_report, MC_MAX_SIMULATIONS, MC_MIN_SIMULATIONS, MC_RUIN_THRESHOLD_PCT, STRESS_MAX_MDD_PCT, STRESS_SCENARIOS

book_router = APIRouter(prefix="/api/studio/book", tags=["book"])

MC_MIN_DAYS, MC_MAX_DAYS = 20, 5000
from backend.analys.alpha.strategies import metrics_row as _metrics   # MỘT định nghĩa (strategies.py), cùng khoá/logic


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
    regime: bool = Field(False, description="Bật lọc regime + cầu chì (metrics/regime.py, models/params.py REGIME_MAP)")
    timeframe: str = Field("15m", pattern="^(15m|1h|4h)$", description="Khung chạy (nến mô phỏng); khung tín hiệu nhỏ hơn được nâng lên")
    run_frame: Optional[str] = Field(None, pattern="^(15m|1h|4h)$", description="Khung chạy (engine base_frame); có thì ghi đè timeframe. Giá trị hợp lệ = meta.frames.book")
    mode: str = Field("basic", **MODE_FIELD)
    data: str = Field("candle", pattern="^(candle|tick)$", description="candle: nến; tick: 501 NOT_READY (backtest tick/AMM chỉ dành cho DEX, Nautilus không hỗ trợ)")
    latency_ms: Optional[int] = Field(None, ge=0, le=3_600_000, description="Chỉ data=tick: trễ từ lúc nến đóng tới lúc bot hành động; bỏ trống = thời gian một block của mạng")
    gas_usd: Optional[float] = Field(None, ge=0.0, le=1000.0, description="Chỉ data=tick: gas mỗi swap (USD); bỏ trống = cấu hình của mạng")


    @model_validator(mode="after")
    def _run_frame(self):
        if self.run_frame:
            self.timeframe = self.run_frame
        return self


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
                        description="learn: mỗi fold học bảng regime ↔ chiến lược trên train rồi áp lên test (metrics/regime.learn_map)")

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


# ─── Đọc sổ / báo cáo ───────────────────────────────────────────────────────
def book_path() -> str:
    """Sổ đang dùng (models/storage.alpha_file: alpha/book.json; NORA_BOOK_PATH / NORA_ALPHAS_DIR ghi đè)."""
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
    from backend.models.storage import run_dir
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
    """Giá trị GIỮA của mỗi khoá trong không gian tham số (cùng quy tắc backend/jobs/evaluate.py._mid_params)."""
    return {k: v[len(v) // 2] for k, v in space.items()}


def _assets() -> List[Dict[str, Any]]:
    """Tài sản có dữ liệu: [{symbol, venue cex, market perp, candles{start_ts,end_ts}, ticks null}]. DEX/AMM không được Nautilus hỗ trợ nên không được đưa ra (dữ liệu DEX vẫn nằm trong kho)."""
    from backend.data.data import coverage
    return [{"symbol": a["symbol"], "venue": "cex", "market": "perp",
             "candles": {"start_ts": a["start_ts"], "end_ts": a["end_ts"]}, "ticks": None} for a in coverage()]


def _catalog() -> List[Dict[str, Any]]:
    from backend.analys.alpha.strategies import CANDIDATES
    return [{"id": c["id"], "family": c["family"], "side": c["side"], "description": c["description"],
             "space": c["space"], "default_params": default_params(c["space"])} for c in CANDIDATES]


def _universe_windows(book: Optional[Dict[str, Any]]):
    """(universe, windows dạng ngày): lấy từ sổ nếu có, không thì từ vũ trụ + dữ liệu hiện có (như build_strategy_book.windows)."""
    from backend.analys.alpha.strategies import perp_symbols
    universe = (book or {}).get("universe") or perp_symbols()
    windows = (book or {}).get("windows")
    if not windows:
        try:
            import pandas as pd
            from backend.data.data import read_manifest
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


@book_router.post("/backtest")
def post_backtest(req: BacktestRequest):
    if not req.strategies and not os.path.isfile(book_path()):
        raise HTTPException(409, "chưa có data/alpha/book.json — truyền strategies hoặc dựng sổ trước (POST /build)")
    return modes.launch_backtest(req)


@book_router.post("/wfa")
def post_wfa(req: WfaRequest):
    return modes.launch_wfa(req)


@book_router.get("/jobs")
def get_jobs(limit: int = 20, kind: Optional[str] = None):
    try:
        return {"jobs": batch_jobs.list_jobs(limit, kind)}
    except batch_jobs.JobError as e:
        raise HTTPException(422, str(e))


_BT_SUM_CACHE: Dict[str, Any] = {}


def _bt_row(j: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Số đo gọn của 1 backtest đã xong (vốn đầu/cuối từ đường vốn, MDD, số lệnh); đệm theo mtime result.json."""
    path = os.path.join(batch_jobs.job_dir(j["id"]), "result.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _BT_SUM_CACHE.get(j["id"])
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        return None
    eq = r.get("equity_curve") or []
    cap = eq[0].get("equity") if eq else None
    end = eq[-1].get("equity") if eq else None
    row = {"id": j["id"], "created": j.get("created"), "label": j.get("label"), "capital": cap,
           "pnl_usd": (end - cap) if cap is not None and end is not None else None,
           "ret_pct": r.get("ret_pct"), "mdd_pct": r.get("mdd_pct"), "trades": r.get("trades")}
    _BT_SUM_CACHE[j["id"]] = (mt, row)
    return row


@book_router.get("/backtest_summary")
def get_backtest_summary(limit: int = 100):
    """Tổng hợp các lần backtest đã xong: số lần, tổng PnL (USDT), MDD lớn nhất, tổng số lệnh, lần gần nhất, các lần gần đây."""
    rows = [x for x in (_bt_row(j) for j in batch_jobs.list_jobs(limit, "book_backtest") if j.get("status") == "done") if x]
    nums = lambda k: [x[k] for x in rows if isinstance(x.get(k), (int, float))]
    pnl, cap, mdd = nums("pnl_usd"), nums("capital"), nums("mdd_pct")
    return {"runs": len(rows), "pnl_usd": round(sum(pnl), 2) if pnl else None,
            "capital": round(sum(cap), 2) if cap else None,
            "pnl_pct": round(sum(pnl) / sum(cap) * 100, 4) if pnl and sum(cap) else None,
            "mdd_pct": max(mdd) if mdd else None, "trades": int(sum(nums("trades"))),
            "last": rows[0] if rows else None, "recent": rows[:10]}


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


# ─── Monte Carlo ngày (đồng bộ, nhẹ) ────────────────────────────────────────
@book_router.post("/mc")
def post_mc(req: McRequest):
    """Block bootstrap (mặc định 10.000 kịch bản) lợi suất ngày OOS của một job book_wfa (hoặc chuỗi tự gửi); trả tóm tắt + fan + histogram
    + `stress` (kịch bản cực xấu tất định + worst_bootstrap) + `worst_path` + `gate` (checks thực tế/yêu cầu, gate_eligible).
    mode=basic: bỏ qua mọi tham số MC của client (10.000 kịch bản, đủ 6 kịch bản cực xấu, gate chuẩn).
    mode=advanced: dùng tham số client; ngưỡng gate khác chuẩn / < 10.000 kịch bản / thiếu kịch bản cực xấu -> params.custom_gates=true (không promote được)."""
    cfg = modes.resolve_mc(req)
    custom = False
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
        custom = bool(job.get("custom_gates"))   # nguồn đã dùng gate tuỳ chỉnh -> kết quả cũng không promote được
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
    return mc_report(daily, cfg, shock=shock, turnover=turnover, provenance=provenance, source=source, basis=req.basis, custom=custom)



# ─── Danh mục đầu tư (dashboard + lệnh của job backtest) ──────────────────────
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
    from backend.analys.metrics.trades import strategy_family
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


ROUTERS = [book_router, portfolio_router]
"""Routes alpha: thư viện chiến lược (catalog + top agents), alpha người dùng, chiến lược hệ thống và soạn thảo (compile/annotate/assist), chạy thử
tuỳ chỉnh (custom backtest), giải thích biểu đồ, mẫu giáo dục. Logic nằm ở backend/alpha/strategies.py và backend/alpha/; file này chỉ validate + gọi."""
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from backend.analys.alpha import strategies as store, strategies
import sys as _sys
batch_jobs_routes = _sys.modules[__name__]
from backend.analys.param import FRAMES, FRAME_MS
from backend.analys.alpha.code import compile as dsl
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
    job_id: Optional[str] = Field(None, description="Mã job custom_backtest đã hoàn tất (tuỳ chọn nếu lưu nháp)")
    code: str = Field(..., description="Mã Python của chiến lược")
    name: str = Field(..., min_length=1, max_length=100, description="Tên alpha")
    note: Optional[str] = Field("", max_length=2000, description="Ghi chú chiến lược")
    source: Optional[str] = Field("alpha-create", description="Nguồn đẩy (alpha-create | education)")
    alpha_id: Optional[str] = Field(None, max_length=64, description="Có = lưu PHIÊN BẢN MỚI của alpha đã có (giữ id; bản cũ vào user/_versions)")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="Trạng thái mới: SAVED | CANDIDATE | ARCHIVED")


@alphas_router.post("/user")
def post_user_alpha(req: SaveUserAlphaRequest, request: Request) -> Dict[str, Any]:
    """Đẩy chiến lược vào kho Alpha người dùng sau khi chạy backtest thành công."""
    from backend.routes.system import current_user
    me = current_user(request)
    owner_id = me.get("id") if me else None
    try:
        record, action = store.save_user_alpha(
            job_id=req.job_id,
            code=req.code,
            name=req.name,
            note=req.note or "",
            source=req.source or "alpha-create",
            alpha_id=req.alpha_id,
            owner_id=owner_id,
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
    request: Request,
    sort: Optional[str] = Query(None, description="Tiêu chí sắp xếp: date | sharpe | cagr"),
    status: Optional[str] = Query(None, description="Lọc trạng thái: SAVED | CANDIDATE | ARCHIVED"),
    owner_id: Optional[str] = Query(None, description="Lọc theo người dùng sở hữu"),
    all_users: Optional[bool] = Query(False, description="Lấy tất cả alpha của mọi user"),
) -> List[Dict[str, Any]]:
    """Lấy danh sách các Alpha người dùng đã lưu (mặc định theo người dùng hiện tại nếu đăng nhập)."""
    if all_users:
        return store.list_user_alphas(sort=sort, status=status)
    from backend.routes.system import current_user
    me = current_user(request)
    target_owner = owner_id or (me.get("id") if me else None)
    if target_owner:
        return store.list_user_alphas(sort=sort, status=status, owner_id=target_owner)
    # Chưa đăng nhập và không truyền owner_id: chỉ trả về alpha không gán chủ sở hữu (hoặc rỗng)
    return store.list_user_alphas(sort=sort, status=status, owner_id="")


def _load_samples():
    from backend.models.storage import alpha_education_samples
    return _read(alpha_education_samples()) or []


def _not_ready(what: str):
    return HTTPException(404, {"code": "NOT_READY", "message": f"Chưa có kết quả backtest thật cho {what} (chạy job education_warm)."})


@alphas_router.get("/user/{alpha_id}")
def get_user_alpha_detail(alpha_id: str) -> Dict[str, Any]:
    """Lấy chi tiết một Alpha người dùng hoặc chiến lược mẫu đã có kết quả."""
    rec = store.get_user_alpha(alpha_id)
    if not rec:
        # Fallback: mẫu giáo dục, CHỈ khi có kết quả thật trong cache
        sample_item = next((x for x in _load_samples() if x.get("key") == alpha_id or x.get("name") == alpha_id), None)
        if sample_item is not None:
            s_res = store.sample_lookup(sample_item)
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
    rec = store.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    code = rec.get("code") or ""
    return {"id": rec["id"], "code": code, "version": rec.get("version", 1), "program_hash": rec.get("program_hash"),
            "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "name": rec.get("name"), "note": rec.get("note", "")}


@alphas_router.get("/user/{alpha_id}/versions")
def get_user_alpha_versions(alpha_id: str) -> List[Dict[str, Any]]:
    rows = store.list_user_alpha_versions(alpha_id)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return rows


@alphas_router.get("/user/{alpha_id}/versions/{version}")
def get_user_alpha_version(alpha_id: str, version: int) -> Dict[str, Any]:
    rec = store.get_user_alpha_version(alpha_id, version)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không có phiên bản {version} của alpha {alpha_id}")
    return rec


@alphas_router.post("/user/{alpha_id}/archive")
def post_archive_user_alpha(alpha_id: str, request: Request) -> Dict[str, Any]:
    """Lưu trữ (archive) một Alpha người dùng (không xóa cứng)."""
    rec = store.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    owner_id = rec.get("owner_id")
    if owner_id:
        from backend.routes.system import current_user
        me = current_user(request)
        if not me or me.get("id") != owner_id:
            raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu mới có quyền lưu trữ chiến lược này")
    ok = store.update_user_alpha_status(alpha_id, "ARCHIVED")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": "ARCHIVED"}


@alphas_router.post("/user/{alpha_id}/status")
def post_update_user_alpha_status(alpha_id: str, req: UpdateStatusRequest, request: Request) -> Dict[str, Any]:
    """Cập nhật trạng thái Alpha người dùng: SAVED | CANDIDATE | ARCHIVED."""
    if req.status not in ("SAVED", "CANDIDATE", "ARCHIVED"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ: phải là SAVED, CANDIDATE hoặc ARCHIVED")
    rec = store.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    owner_id = rec.get("owner_id")
    if owner_id:
        from backend.routes.system import current_user
        me = current_user(request)
        if not me or me.get("id") != owner_id:
            raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu mới có quyền thay đổi trạng thái chiến lược này")
    ok = store.update_user_alpha_status(alpha_id, req.status)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    return {"ok": True, "alpha_id": alpha_id, "status": req.status}


@alphas_router.delete("/user/{alpha_id}")
def delete_user_alpha_endpoint(alpha_id: str, request: Request) -> Dict[str, Any]:
    """Xóa vĩnh viễn một Alpha người dùng."""
    rec = store.get_user_alpha(alpha_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy alpha {alpha_id}")
    owner_id = rec.get("owner_id")
    if owner_id:
        from backend.routes.system import current_user
        me = current_user(request)
        if not me or me.get("id") != owner_id:
            raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu mới có quyền xóa chiến lược này")
    ok = store.delete_user_alpha(alpha_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Không thể xóa chiến lược")
    return {"ok": True, "alpha_id": alpha_id, "deleted": True}


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
    from backend.analys.indicator import REQUIRED
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
    from backend.analys.indicator import indicator as feat_mod, indicator as ops_mod
    from backend.analys.signal.signal import DATA_COLUMNS
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
    from backend.analys.alpha.code import contract
    return {k: v for k, v in contract.catalog().items() if not k.startswith("_")}


@strategies_router.post("/assist/check")
def post_assist_check(req: AssistCheck) -> Dict[str, Any]:
    from backend.analys.alpha.code import contract
    res = contract.check_contract(req.code)
    ir = res.pop("ir", None)
    meta = None
    if ir is not None:
        meta = ir.meta() if res["kind"] == contract.KIND_ALPHA else {"strategy_id": ir["strategy"]["id"], "legs": [c["id"] for c in ir["candidates"]]}
    return {**res, "meta": meta}


@strategies_router.post("/assist/complete")
def post_assist_complete(req: AssistPos) -> Dict[str, Any]:
    from backend.analys.alpha.code import contract
    return contract.complete(req.code, req.line, req.col)


@strategies_router.post("/assist/hover")
def post_assist_hover(req: AssistPos) -> Dict[str, Any]:
    from backend.analys.alpha.code import contract
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
    run_frame: Optional[str] = Field(None, pattern="^(1m|5m|15m|1h|4h|24h)$", description="Khung chạy; thiếu = Nhanh (khung tín hiệu); '1m' = Chuẩn")

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
    from backend.analys.param import materialize
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
    from backend.analys.signal.compute import required_frames
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
    from backend.analys.metrics.charts import explain
    if req.source == "okx":
        raise HTTPException(501, detail={"code": "NOT_READY", "message": "Nến OKX trực tiếp đang chuyển sang Nautilus TradingNode"})
    symbol = req.symbol.split("@")[0].upper()
    st, tf, meta = _strategy(req)
    start, end = req.start, req.end
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
            default_cap = spec.get("initial_capital") if spec is not None else None
            init_cap = r.get("config", {}).get("initial_capital", default_cap)
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



"""Routes cho Alpha Research (Man Group AlphaTrend) trên Coin Studio (P17 T7).

Endpoints:
- POST /api/studio/research: Khởi tạo phiên nghiên cứu, chạy bước 1 (validate) và bước 2 (ideas) -> waiting_pick
- GET /api/studio/research/{job_id}: Lấy trạng thái và dữ liệu 6 bước
- POST /api/studio/research/{job_id}/pick: Chọn ý tưởng, tiếp tục bước 3, 4, 5, 6
- POST /api/studio/research/{job_id}/rerun: Chạy lại từ bước bất kỳ (hỗ trợ sửa trước khi chạy)
- POST /api/studio/research/{job_id}/save: Lưu chiến lược vào Alpha người dùng (source="research")
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.analys.alpha.prompt import research
from backend.analys.alpha import strategies as store
from backend.data.data import coverage
from backend.jobs.runner import new_job_id, inject_ephemeral_result
from backend.models.storage import data_home
from backend.routes.system import current_user

logger = logging.getLogger("backend.routes.research")
research_router = APIRouter(prefix="/api/studio/research", tags=["research"])


def _research_base_dir() -> str:
    d = os.path.join(data_home(), "research")
    os.makedirs(d, exist_ok=True)
    return d


def _job_dir(job_id: str) -> str:
    # Bảo vệ path traversal theo định dạng job chuẩn của Nora
    if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{6}", job_id):
        raise HTTPException(status_code=400, detail="Mã job không hợp lệ")
    d = os.path.join(_research_base_dir(), job_id)
    return d


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: str) -> Optional[Any]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _load_job_data(job_id: str) -> Dict[str, Any]:
    jd = _job_dir(job_id)
    meta = _read_json(os.path.join(jd, "job.json"))
    if not meta:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiên nghiên cứu {job_id}")

    steps_dir = os.path.join(jd, "steps")
    steps = {
        "step1": _read_json(os.path.join(steps_dir, "1_prompt.json")),
        "step2": _read_json(os.path.join(steps_dir, "2_ideas.json")),
        "picked_idea": _read_json(os.path.join(steps_dir, "picked_idea.json")),
        "step3": _read_json(os.path.join(steps_dir, "3_formula.json")),
        "step4": _read_json(os.path.join(steps_dir, "4_code.json")),
        "step5": _read_json(os.path.join(steps_dir, "5_backtest.json")),
        "step6": _read_json(os.path.join(steps_dir, "6_synthesis.json")),
    }

    return {
        "job_id": job_id,
        "state": meta.get("state", "unknown"),
        "current_step": meta.get("current_step", 1),
        "prompt": meta.get("prompt", ""),
        "opts": meta.get("opts", {}),
        "error": meta.get("error"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "steps": steps,
    }


# ─── Request Models ─────────────────────────────────────────────────────────

class StartResearchRequest(BaseModel):
    prompt: str = Field(..., description="Prompt ý tưởng giao dịch của người dùng")
    opts: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Tùy chọn: symbol, timeframe, side...")


class PickIdeaRequest(BaseModel):
    idea_index: int = Field(0, description="Chỉ số ý tưởng người dùng chọn (0, 1, 2)")


class RerunStepRequest(BaseModel):
    from_step: int = Field(..., description="Chạy lại từ bước nào (1 đến 6)")
    edits: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Dữ liệu chỉnh sửa trước khi chạy lại")


class SaveResearchStrategyRequest(BaseModel):
    name: Optional[str] = Field(None, description="Tên chiến lược lưu trữ")
    note: Optional[str] = Field(None, description="Ghi chú người dùng")


def data_window(symbol: str) -> Dict[str, str]:
    """Cửa sổ ngày thật của dữ liệu catalog cho tài sản (start/end 'YYYY-MM-DD'); {} nếu chưa có dữ liệu."""
    base = str(symbol).split("-")[0].split("@")[0].upper()
    for a in coverage():
        if a["base"] == base and a.get("start_ts") and a.get("end_ts"):
            f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")
            return {"start": f(a["start_ts"]), "end": f(a["end_ts"])}
    return {}


def backtest_spec(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Spec backtest từ opts; start/end thiếu -> lấy từ phạm vi dữ liệu thật của tài sản."""
    sym = opts.get("symbol") or "BTC-USDT"
    win = data_window(sym)
    start, end = opts.get("start") or win.get("start"), opts.get("end") or win.get("end")
    if not (start and end):
        raise ValueError(f"Không có dữ liệu cho {sym}: hãy cập nhật dữ liệu hoặc chọn khoảng ngày")
    return {"symbols": [sym], "timeframe": opts.get("timeframe") or "1h", "start": start, "end": end,
            "initial_capital": opts.get("capital") or 10_000.0}


def run_backtest(code: str, spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Thực thi backtest thật trên NautilusTrader bằng run_custom + benchmark buy&hold."""
    spec = spec or {}
    symbols = spec.get("symbols") or [spec.get("asset") or "BTC-USDT"]
    win = data_window(symbols[0]) if not (spec.get("start") and spec.get("end")) else {}
    start = spec.get("start") or win.get("start")
    end = spec.get("end") or win.get("end")
    if not (start and end):
        raise ValueError(f"Không có dữ liệu cho {symbols[0]}")
    run_frame = spec.get("timeframe") or "1h"
    train_ratio = float(spec.get("train_ratio", 0.7))
    initial_capital = float(spec.get("initial_capital", 10_000.0))

    params = {
        "code": code,
        "symbols": symbols,
        "start": start,
        "end": end,
        "run_frame": run_frame,
        "train_ratio": train_ratio,
        "initial_capital": initial_capital,
    }

    from backend.jobs.tasks import run_custom      # nạp lười: tasks đặt biến môi trường BLAS/cache cho tiến trình job, không áp vào API
    return run_custom(params)


def _spec_or_400(opts: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return backtest_spec(opts or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Endpoints ──────────────────────────────────────────────────────────────

@research_router.post("")
def start_research(req: StartResearchRequest) -> Dict[str, Any]:
    """Khởi tạo phiên Alpha Research, thực hiện bước 1 (validate) và bước 2 (ideas)."""
    now = datetime.now(timezone.utc)
    job_id = new_job_id()
    jd = _job_dir(job_id)
    steps_dir = os.path.join(jd, "steps")
    os.makedirs(steps_dir, exist_ok=True)

    meta = {
        "job_id": job_id,
        "kind": "alpha_research",
        "state": "running",
        "current_step": 1,
        "prompt": req.prompt,
        "opts": req.opts or {},
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    _write_json(os.path.join(jd, "job.json"), meta)

    # Bước 1: Validate prompt
    try:
        s1 = research.validate_prompt(req.prompt, req.opts)
    except ValueError as e:
        meta["state"] = "failed"
        meta["error"] = str(e)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(os.path.join(jd, "job.json"), meta)
        raise HTTPException(status_code=400, detail=str(e)) from None

    _write_json(os.path.join(steps_dir, "1_prompt.json"), s1)

    if not s1.get("valid"):
        meta["state"] = "failed"
        meta["error"] = s1.get("reason", "Prompt không hợp lệ")
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(os.path.join(jd, "job.json"), meta)
        return _load_job_data(job_id)

    # Bước 2: Sinh ý tưởng
    meta["current_step"] = 2
    try:
        ideas = research.generate_ideas(s1.get("normalized_prompt") or req.prompt, req.opts)
    except ValueError as e:
        meta["state"] = "failed"
        meta["error"] = str(e)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(os.path.join(jd, "job.json"), meta)
        raise HTTPException(status_code=400, detail=str(e)) from None
    _write_json(os.path.join(steps_dir, "2_ideas.json"), ideas)

    meta["state"] = "waiting_pick"
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(os.path.join(jd, "job.json"), meta)

    return _load_job_data(job_id)


@research_router.get("/engine/status")
def get_research_engine_status() -> Dict[str, Any]:
    """Trả về thông tin LLM / Quant Engine đang được kích hoạt."""
    from backend.analys.alpha.prompt import llm
    has_gemini = bool(llm.load_gemini_key())
    has_anthropic = bool(llm.load_api_key())
    if has_gemini:
        provider = "gemini"
        model = "Gemini 2.5 Flash"
    elif has_anthropic:
        provider = "anthropic"
        model = "Claude 3.5 Sonnet"
    else:
        provider = "builtin_quant"
        model = "Nora Rule Quant Engine"
    return {
        "provider": provider,
        "model": model,
        "active": True,
    }


@research_router.get("/{job_id}")
def get_research_job(job_id: str) -> Dict[str, Any]:
    """Lấy trạng thái và kết quả các bước của phiên nghiên cứu."""
    return _load_job_data(job_id)


@research_router.post("/{job_id}/pick")
def pick_idea_and_implement(job_id: str, req: PickIdeaRequest) -> Dict[str, Any]:
    """Người dùng chọn ý tưởng, hệ thống chạy tiếp bước 3, 4, 5, 6."""
    jd = _job_dir(job_id)
    steps_dir = os.path.join(jd, "steps")
    meta = _read_json(os.path.join(jd, "job.json"))
    if not meta:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên nghiên cứu")

    ideas = _read_json(os.path.join(steps_dir, "2_ideas.json"))
    if not ideas or not isinstance(ideas, list):
        raise HTTPException(status_code=400, detail="Không có ý tưởng nào để chọn")

    idx = req.idea_index
    if idx < 0 or idx >= len(ideas):
        idx = 0
    picked_idea = ideas[idx]
    _write_json(os.path.join(steps_dir, "picked_idea.json"), picked_idea)

    opts = meta.get("opts", {})

    meta["state"] = "running"
    meta["current_step"] = 3
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(os.path.join(jd, "job.json"), meta)

    try:
        # Bước 3: To formula
        formula = research.to_formula(picked_idea, opts)
        _write_json(os.path.join(steps_dir, "3_formula.json"), formula)

        # Bước 4: To code
        meta["current_step"] = 4
        _write_json(os.path.join(jd, "job.json"), meta)
        code_res = research.to_code(formula, opts)
        _write_json(os.path.join(steps_dir, "4_code.json"), code_res)

        if not code_res.get("compiled"):
            meta["state"] = "failed"
            meta["error"] = code_res.get("error", "Lỗi biên dịch mã nguồn chiến lược")
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(os.path.join(jd, "job.json"), meta)
            return _load_job_data(job_id)

        # Bước 5: Run backtest
        meta["current_step"] = 5
        _write_json(os.path.join(jd, "job.json"), meta)
        bt_spec = _spec_or_400(opts)
        bt_res = run_backtest(code_res["code"], bt_spec)
        _write_json(os.path.join(steps_dir, "5_backtest.json"), bt_res)

        # Bước 6: Synthesize
        meta["current_step"] = 6
        _write_json(os.path.join(jd, "job.json"), meta)
        synth = research.synthesize(bt_res, idea=picked_idea)
        _write_json(os.path.join(steps_dir, "6_synthesis.json"), synth)

        meta["state"] = "done"
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(os.path.join(jd, "job.json"), meta)

    except Exception as e:
        logger.exception("Lỗi khi thực thi Alpha Research %s: %s", job_id, e)
        meta["state"] = "failed"
        meta["error"] = str(e)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(os.path.join(jd, "job.json"), meta)

    return _load_job_data(job_id)


@research_router.post("/{job_id}/rerun")
def rerun_research_step(job_id: str, req: RerunStepRequest) -> Dict[str, Any]:
    """Chạy lại từ bước bất kỳ (từ 1 đến 6)."""
    jd = _job_dir(job_id)
    steps_dir = os.path.join(jd, "steps")
    meta = _read_json(os.path.join(jd, "job.json"))
    if not meta:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên nghiên cứu")

    from_step = req.from_step
    opts = meta.get("opts", {})

    if from_step == 1:
        # Chạy lại từ đầu
        prompt = (req.edits or {}).get("prompt") or meta.get("prompt", "")
        meta["prompt"] = prompt
        meta["state"] = "running"
        meta["current_step"] = 1
        _write_json(os.path.join(jd, "job.json"), meta)

        s1 = research.validate_prompt(prompt, opts)
        _write_json(os.path.join(steps_dir, "1_prompt.json"), s1)
        if not s1.get("valid"):
            meta["state"] = "failed"
            meta["error"] = s1.get("reason")
            _write_json(os.path.join(jd, "job.json"), meta)
            return _load_job_data(job_id)

        meta["current_step"] = 2
        ideas = research.generate_ideas(s1.get("normalized_prompt") or prompt, opts)
        _write_json(os.path.join(steps_dir, "2_ideas.json"), ideas)
        meta["state"] = "waiting_pick"
        _write_json(os.path.join(jd, "job.json"), meta)
        return _load_job_data(job_id)

    if from_step == 3:
        # Sửa/chạy lại từ công thức
        picked_idea = _read_json(os.path.join(steps_dir, "picked_idea.json")) or {}
        formula = (req.edits or {}).get("formula")
        if not formula:
            formula = research.to_formula(picked_idea, opts)
        _write_json(os.path.join(steps_dir, "3_formula.json"), formula)

        # Chạy tiếp bước 4, 5, 6
        code_res = research.to_code(formula, opts)
        _write_json(os.path.join(steps_dir, "4_code.json"), code_res)
        if not code_res.get("compiled"):
            meta["state"] = "failed"
            meta["error"] = code_res.get("error")
            _write_json(os.path.join(jd, "job.json"), meta)
            return _load_job_data(job_id)

        bt_spec = _spec_or_400(opts)
        bt_res = run_backtest(code_res["code"], bt_spec)
        _write_json(os.path.join(steps_dir, "5_backtest.json"), bt_res)

        synth = research.synthesize(bt_res, idea=picked_idea)
        _write_json(os.path.join(steps_dir, "6_synthesis.json"), synth)

        meta["state"] = "done"
        meta["current_step"] = 6
        _write_json(os.path.join(jd, "job.json"), meta)
        return _load_job_data(job_id)

    if from_step == 4:
        # Sửa/chạy lại từ code
        code = (req.edits or {}).get("code")
        if not code:
            formula = _read_json(os.path.join(steps_dir, "3_formula.json")) or {}
            code_res = research.to_code(formula, opts)
        else:
            # Biên dịch lại code sửa đổi
            try:
                from backend.analys.alpha.code.compile import compile_code
                from backend.analys.alpha.code.route import classify
                compile_code(code)
                rt = classify(code)
                code_res = {"code": code, "compiled": True, "error": None, "route": rt}
            except Exception as e:
                code_res = {"code": code, "compiled": False, "error": str(e), "route": None}

        _write_json(os.path.join(steps_dir, "4_code.json"), code_res)
        if not code_res.get("compiled"):
            meta["state"] = "failed"
            meta["error"] = code_res.get("error")
            _write_json(os.path.join(jd, "job.json"), meta)
            return _load_job_data(job_id)

        # Chạy tiếp 5, 6
        bt_spec = _spec_or_400(opts)
        code_str = str(code_res.get("code") or "")
        bt_res = run_backtest(code_str, bt_spec)
        _write_json(os.path.join(steps_dir, "5_backtest.json"), bt_res)

        picked_idea = _read_json(os.path.join(steps_dir, "picked_idea.json")) or {}
        synth = research.synthesize(bt_res, idea=picked_idea)
        _write_json(os.path.join(steps_dir, "6_synthesis.json"), synth)

        meta["state"] = "done"
        meta["current_step"] = 6
        _write_json(os.path.join(jd, "job.json"), meta)
        return _load_job_data(job_id)

    if from_step == 5:
        # Chạy lại backtest
        code_res = _read_json(os.path.join(steps_dir, "4_code.json")) or {}
        code = code_res.get("code")
        if not code:
            raise HTTPException(status_code=400, detail="Chưa có mã nguồn ở bước 4")

        bt_spec = _spec_or_400(opts)
        bt_res = run_backtest(str(code), bt_spec)
        _write_json(os.path.join(steps_dir, "5_backtest.json"), bt_res)

        picked_idea = _read_json(os.path.join(steps_dir, "picked_idea.json")) or {}
        synth = research.synthesize(bt_res, idea=picked_idea)
        _write_json(os.path.join(steps_dir, "6_synthesis.json"), synth)

        meta["state"] = "done"
        meta["current_step"] = 6
        _write_json(os.path.join(jd, "job.json"), meta)
        return _load_job_data(job_id)

    if from_step == 6:
        # Chạy lại nhận xét
        bt_res = _read_json(os.path.join(steps_dir, "5_backtest.json")) or {}
        picked_idea = _read_json(os.path.join(steps_dir, "picked_idea.json")) or {}
        synth = research.synthesize(bt_res, idea=picked_idea)
        _write_json(os.path.join(steps_dir, "6_synthesis.json"), synth)
        return _load_job_data(job_id)

    raise HTTPException(status_code=400, detail=f"Bước {from_step} không hỗ trợ chạy lại trực tiếp")


@research_router.post("/{job_id}/save")
def save_research_strategy(job_id: str, req: SaveResearchStrategyRequest, request: Request) -> Dict[str, Any]:
    """Lưu chiến lược thành công từ Alpha Research vào Alpha người dùng (source='research')."""
    jd = _job_dir(job_id)
    steps_dir = os.path.join(jd, "steps")
    code_step = _read_json(os.path.join(steps_dir, "4_code.json"))
    bt_step = _read_json(os.path.join(steps_dir, "5_backtest.json"))
    picked_idea = _read_json(os.path.join(steps_dir, "picked_idea.json")) or {}
    formula = _read_json(os.path.join(steps_dir, "3_formula.json")) or {}
    meta = _read_json(os.path.join(jd, "job.json")) or {}

    if not code_step or not code_step.get("code"):
        raise HTTPException(status_code=400, detail="Không tìm thấy mã nguồn chiến lược đã hoàn thành")
    if not bt_step:
        raise HTTPException(status_code=400, detail="Không tìm thấy kết quả backtest của chiến lược")

    code = code_step["code"]
    strat_name = (req.name or picked_idea.get("name") or "alpha_research_strat").strip()
    note = (req.note or picked_idea.get("rationale") or f"Tạo từ prompt: {meta.get('prompt', '')[:100]}").strip()

    me = current_user(request)
    owner_id = me.get("id") if me else None

    # Đưa kết quả bt_step vào ephemerals của runner để store.save_user_alpha đọc được
    inject_ephemeral_result(job_id, "custom_backtest", bt_step)

    try:
        record, action = store.save_user_alpha(
            job_id=job_id,
            code=code,
            name=strat_name,
            note=note,
            source="research",
            owner_id=owner_id,
        )

        # Bổ sung metadata research vào alpha file
        user_alphas_dir = store.get_user_alphas_dir()
        alpha_path = os.path.join(user_alphas_dir, f"{record['id']}.json")
        if os.path.isfile(alpha_path):
            try:
                with open(alpha_path, "r", encoding="utf-8") as fh:
                    alpha_data = json.load(fh)
                alpha_data["research"] = {
                    "job_id": job_id,
                    "prompt": meta.get("prompt"),
                    "idea": picked_idea,
                    "formula": formula,
                }
                store.write_json_atomic(alpha_path, alpha_data, indent=1, clean=True, allow_nan=False)
                record["research"] = alpha_data["research"]
            except Exception as e:
                logger.warning("Không thể bổ sung research metadata vào alpha %s: %s", record['id'], e)

        return {
            "ok": True,
            "alpha_id": record["id"],
            "action": action,
            "record": record,
        }
    except Exception as e:
        logger.exception("Lỗi lưu alpha từ research: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from None



"""Routes cho Universe Scan 100 coin (/api/studio/scan)."""

import os
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.jobs import runner
from backend.models.storage import data_home, read_json
from backend.data.crawl import load_scan_universe
from backend.jobs.runner.alpha import load_universe_sectors

scan_router = APIRouter(prefix="/api/studio/scan", tags=["scan"])


class ScanUniverseRequest(BaseModel):
    alpha_id: str = Field("dca_long", description="ID chiến lược (mặc định dca_long)")
    signal_tf: str = Field("15m", description="Khung thời gian tín hiệu (mặc định 15m)")
    book_source: str = Field("explore", description="Nguồn sổ (explore hoặc main)")
    is_start: Optional[str] = Field(None, description="Bắt đầu In-Sample (YYYY-MM-DD)")
    is_end: Optional[str] = Field(None, description="Kết thúc In-Sample (YYYY-MM-DD)")
    oos_start: Optional[str] = Field(None, description="Bắt đầu Out-of-Sample (YYYY-MM-DD)")
    oos_end: Optional[str] = Field(None, description="Kết thúc Out-of-Sample (YYYY-MM-DD)")
    capital: float = Field(1000.0, description="Vốn mỗi coin ($)")
    coins: Optional[List[str]] = Field(None, description="Danh sách coin quét (None = cả 100 coin)")


@scan_router.post("/universe")
def launch_universe_scan(req: ScanUniverseRequest) -> Dict[str, Any]:
    """Khởi chạy job quét thị trường 100 coin qua runner tiến trình riêng."""
    params = req.model_dump(exclude_none=True)
    try:
        job_id = runner.launch("universe_scan", params)
        return {"job_id": job_id, "status": "queued"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@scan_router.get("/universe_info")
def get_universe_info() -> Dict[str, Any]:
    """Thông tin 100 coin trong universe quét: hạng thanh khoản, ngành, volume 24h."""
    coins = load_scan_universe()
    sectors = load_universe_sectors()
    enriched = []
    for c in coins:
        enriched.append({
            **c,
            "sector": sectors.get(c.get("base", ""), "Other"),
        })
    return {"total": len(enriched), "coins": enriched}


@scan_router.get("/universe/{run_id}")
def get_universe_scan_result(run_id: str) -> Dict[str, Any]:
    """Lấy kết quả quét thị trường theo run_id hoặc job_id. Hỗ trợ run_id='latest'."""
    scan_dir = os.path.join(data_home(), "backtest", "scan")
    
    # 1. Nếu yêu cầu 'latest'
    if run_id == "latest":
        latest_file = os.path.join(scan_dir, "latest_result.json")
        data = read_json(latest_file)
        if data is None:
            raise HTTPException(status_code=404, detail="Chưa có kết quả quét nào")
        return data

    # 2. Nếu là job_id của runner
    if "_" in run_id and len(run_id.split("_")[0]) == 8:
        st = runner.status(run_id)
        if st is not None:
            if st.get("status") in ("queued", "running"):
                return {"job_id": run_id, "status": st.get("status"), "progress": st.get("progress")}
            if st.get("status") == "failed":
                raise HTTPException(status_code=500, detail=f"Job {run_id} thất bại: {st.get('error')}")
            # Nếu done, đọc kết quả từ job directory
            try:
                jdir = runner.job_dir(run_id)
                res_path = os.path.join(jdir, "result.json")
                if os.path.exists(res_path):
                    res = read_json(res_path)
                    if res:
                        return res
            except Exception:
                pass

    # 3. Tìm theo thư mục scan_<ts>_<alpha>
    run_file = os.path.join(scan_dir, run_id, "result.json")
    if os.path.exists(run_file):
        data = read_json(run_file)
        if data is not None:
            return data

    raise HTTPException(status_code=404, detail=f"Không tìm thấy kết quả quét '{run_id}'")


@scan_router.get("/runs")
def list_universe_scan_runs() -> Dict[str, Any]:
    """Danh sách các lần quét thị trường đã lưu."""
    scan_dir = os.path.join(data_home(), "backtest", "scan")
    if not os.path.exists(scan_dir):
        return {"runs": []}

    runs = []
    for item in os.listdir(scan_dir):
        item_path = os.path.join(scan_dir, item)
        if os.path.isdir(item_path):
            res_path = os.path.join(item_path, "result.json")
            if os.path.exists(res_path):
                data = read_json(res_path)
                if data:
                    runs.append({
                        "run_id": item,
                        "alpha_id": data.get("alpha_id"),
                        "signal_tf": data.get("signal_tf"),
                        "elapsed_s": data.get("elapsed_s"),
                        "verdict": data.get("evaluation", {}).get("verdict"),
                        "has_edge": data.get("evaluation", {}).get("has_edge"),
                    })

    runs.sort(key=lambda x: x["run_id"], reverse=True)
    return {"runs": runs}


@scan_router.get("/sweep/latest")
def get_latest_parameter_sweep() -> Dict[str, Any]:
    """Kết quả lần quét lưới 100 tham số gần nhất trên BTC (Bước 3)."""
    sweep_file = os.path.join(data_home(), "backtest", "scan", "parameter_sweep_btc_100.json")
    data = read_json(sweep_file)
    if data is None:
        raise HTTPException(status_code=404, detail="Chưa có kết quả Parameter Sweep nào")
    return data


@scan_router.get("/wfa_carlo/latest")
def get_latest_wfa_carlo() -> Dict[str, Any]:
    """Kết quả kiểm định WFA và Monte Carlo cho cả 2 chiến lược (Bước 2 & Bước 3)."""
    report_file = os.path.join(data_home(), "backtest", "scan", "step3_wfa_carlo_final_report.json")
    data = read_json(report_file)
    if data is None:
        raise HTTPException(status_code=404, detail="Chưa có báo cáo WFA & Monte Carlo nào")
    return data
# ─── Allow-list Routers an toàn dành riêng cho EDU (chỉ đọc & biên dịch kiểm tra) ──────
edu_strategies_router = APIRouter(prefix="/api/studio/strategies", tags=["edu_strategies"])
edu_strategies_router.add_api_route("", get_strategies, methods=["GET"])
edu_strategies_router.add_api_route("/", get_strategies, methods=["GET"])
edu_strategies_router.add_api_route("/catalog", get_strategy_catalog, methods=["GET"])
edu_strategies_router.add_api_route("/validate", post_validate, methods=["POST"])
edu_strategies_router.add_api_route("/compile", post_compile, methods=["POST"])
edu_strategies_router.add_api_route("/annotate", post_strategy_annotate, methods=["POST"])
edu_strategies_router.add_api_route("/explain", post_strategy_explain, methods=["POST"])
edu_strategies_router.add_api_route("/dsl", get_dsl_reference, methods=["GET"])
edu_strategies_router.add_api_route("/source/{strategy_id}", get_source, methods=["GET"])
edu_strategies_router.add_api_route("/assist/catalog", get_assist_catalog, methods=["GET"])
edu_strategies_router.add_api_route("/assist/check", post_assist_check, methods=["POST"])
edu_strategies_router.add_api_route("/assist/complete", post_assist_complete, methods=["POST"])
edu_strategies_router.add_api_route("/assist/hover", post_assist_hover, methods=["POST"])

edu_custom_router = APIRouter(prefix="/api/studio/custom", tags=["edu_custom"])
edu_custom_router.add_api_route("/defaults", get_run_defaults, methods=["GET"])
edu_custom_router.add_api_route("/backtest", post_custom_backtest, methods=["POST"])

edu_jobs_router = APIRouter(prefix="/api/studio/jobs", tags=["edu_jobs"])
edu_jobs_router.add_api_route("", get_jobs, methods=["GET"])
edu_jobs_router.add_api_route("/", get_jobs, methods=["GET"])
edu_jobs_router.add_api_route("/{job_id}", get_job, methods=["GET"])
edu_jobs_router.add_api_route("/{job_id}/cancel", post_cancel, methods=["POST"])

edu_book_jobs_router = APIRouter(prefix="/api/studio/book", tags=["edu_book_jobs"])
edu_book_jobs_router.add_api_route("/jobs", get_jobs, methods=["GET"])
edu_book_jobs_router.add_api_route("/jobs/{job_id}", get_job, methods=["GET"])
edu_book_jobs_router.add_api_route("/jobs/{job_id}/cancel", post_cancel, methods=["POST"])

EDU_STUDIO_ROUTERS = [meta_router, education_router, chart_router, edu_custom_router, edu_strategies_router, edu_jobs_router, edu_book_jobs_router]

ROUTERS = [meta_router, book_router, portfolio_router, alphas_router, strategies_router, custom_router, education_router, chart_router, research_router, scan_router]
router = meta_router
portfolio = portfolio_router

