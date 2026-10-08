"""Lớp dùng chung cho các router (P11): kiểm tham số, khởi chạy job, chế độ Cơ bản/Nâng cao, metadata UI.

Gộp từ: jobs.py, modes.py, meta.py.
"""
"""Kiểm tham số job (P9.8): ngày, tài sản, số, thư mục báo cáo, chiến lược WFA, dựng params cho book_backtest/book_wfa/book_build/custom_backtest, http_launch.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8). `http_launch` gọi `_proc.launch` (tra cứu thuộc tính lúc gọi nên monkeypatch `launch` có hiệu lực).
"""
import calendar
import math
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from backend.optimize.process import process as _proc
from backend.optimize.process.process import JobBusy, JobError, KINDS


# ══════════════════════════════════════════════════════════════════════════
# Job nền nặng (backtest, WFA, dựng sổ, phễu, dữ liệu...), chạy NGOÀI tiến trình API qua MỘT cửa: backend/optimize/process/process.py.
#
# Vì sao: API có trần RAM riêng (3G) nên không được chạy việc nặng trong tiến trình. Mỗi job là một tiến trình con
# `ops/run_limited.sh -- -m backend.optimize.process.process <job_dir>`: tự có scope riêng trong nora.slice (trần chung 12G), xếp hàng
# tuần tự (flock) và tự chia worker theo RAM còn trống. runner đọc job.json {kind, params} rồi gọi run_job(params) của module trong KINDS.
# API chỉ khởi chạy, theo dõi và đọc kết quả. UI, terminal (curl) và script đều đi qua cùng endpoint -> cùng job.
#
# Mỗi job có thư mục <data>/cache/process/<job_id>/ (kết quả lâu dài: backtest|wfa|carlo/<job_id>):
#   params.json đầu vào của runner {kind, params}
#   job.json    siêu dữ liệu (id, kind, params, pid, created/started/finished, state, exit_code)
#   out.log     stdout+stderr của job
#   result.json báo cáo cuối do script ghi (quy ước env NORA_JOB_DIR, xem backend/optimize/process/process.py)
#   alphas/     (chỉ job book_build) sổ vừa dựng: book.json [+ testnet/book.json]; KHÔNG ghi đè nora/data/alpha/ — xuất bản qua POST /book/publish
#   progress.json  (job tối ưu quy mô lớn) tiến độ do job ghi mỗi <= 5 giây: stage, done, total, rate, eta_s, peak_rss_mb (xem backend/optimize/process/process.py)
# Trạng thái trả ra: queued (đang chờ hàng đợi run_limited) | running | done | failed | cancelled. Trạng thái bền (job.json) chỉ có running/done/failed/cancelled;
# queued suy ra từ out.log. Huỷ: cancel(job_id) gửi SIGTERM cho CẢ nhóm tiến trình (job flush kho kết quả rồi thoát -> chạy lại bằng resume). Không dùng shell.
# ══════════════════════════════════════════════════════════════════════════

# Danh sách trắng: loại job -> (module có run_job(params), các khoá tham số được phép)
MAX_BUILD_CONFIGS = 1_000_000   # trần cứng của API cho --n (mỗi chiến lược); CLI còn có --max-configs (mặc định 200000) + --force-large
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_WFA_STRATEGIES, MAX_WFA_CONFIGS = 16, 50


# ─── Đường dẫn ──────────────────────────────────────────────────────────────


# Kết quả lâu dài của job đã xong (ADR-P9 §4): backtest|wfa|carlo/<id>. Cùng tệp như thư mục job (job.json, params.json, result.json, ...).


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
    from backend.crawl.store import require_perp
    from backend.optimize.book.build import UNIVERSE
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


def check_backtest_symbols(symbols: List[str]) -> Tuple[List[str], str]:
    """Ký hiệu backtest -> (ký hiệu engine, venue): toàn perp -> check_symbols ('cex'); toàn DEX -> 'dex:AERO' có trong kho ('dex'); trộn hai loại bị từ chối."""
    from backend.crawl.store import is_dex_symbol
    flags = [is_dex_symbol(str(s)) for s in symbols]
    if not any(flags):
        return check_symbols(symbols), "cex"
    if not all(flags):
        raise JobError("không chạy chung tài sản perp (CEX) với tài sản DEX trong một lần backtest — chọn một loại")
    from backend.crawl.store import clean_name, parse_symbol, resolve_asset_dir
    out = []
    for s in symbols:
        name = clean_name(parse_symbol(str(s))[1])
        if not name or not resolve_asset_dir(f"dex:{name}"):
            raise JobError(f"không có tài sản DEX {s!r} trong kho dữ liệu")
        if f"dex:{name}" not in out:
            out.append(f"dex:{name}")
    return out, "dex"


def _day_ms(day: str, plus_days: int = 0) -> int:
    return (calendar.timegm(time.strptime(day, "%Y-%m-%d")) + plus_days * 86_400) * 1000


def check_dex_backtest(p: Dict[str, Any], out: Dict[str, Any], symbols: List[str]) -> None:
    """Điều kiện riêng của backtest DEX: có chiến lược LONG được chọn; data=tick cần tick đã crawl, pool mô hình hoá được, cửa sổ >= một nến cơ sở."""
    from backend.core import backtest as dex
    if not p.get("strategies"):
        raise JobError("backtest DEX cần chọn chiến lược (chân LONG): sổ data/alpha/book.json là sổ perp")
    try:
        from backend.optimize.book.build import BY_ID
        dex.require_long_legs([s["id"] for s in p["strategies"]], BY_ID)
        if p.get("data") == "tick":
            from backend.crawl.store import _frame_ms
            from backend.crawl.dex import pool_info
            infos = [pool_info(s) for s in symbols]
            for i in infos:
                dex.check_amm_pool(i)
            dex.tick_window(infos, _day_ms(p["start"]), _day_ms(p["end"], 1), _frame_ms(out.get("timeframe") or "1m"))
    except ValueError as e:
        raise JobError(str(e))


def check_candidate_ids(ids: List[str]) -> List[str]:
    from backend.optimize.book.build import BY_ID
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
    from backend.crawl.store import alpha_run_dir
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
    from backend.optimize.book.build import BY_ID
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
        venue = "cex"
        if p.get("symbols"):
            out["symbols"], venue = check_backtest_symbols(p["symbols"])
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
        data = p.get("data") or "candle"
        if data not in ("candle", "tick"):
            raise JobError("data phải là candle|tick")
        if data == "tick":
            if venue != "dex":
                raise JobError("data=tick chỉ dành cho tài sản DEX (chỉ DEX có tick swap on-chain)")
            out["data"] = "tick"
            if p.get("latency_ms") is not None:
                out["latency_ms"] = check_number(p["latency_ms"], "latency_ms", 0, 3_600_000, integer=True)
            if p.get("gas_usd") is not None:
                out["gas_usd"] = check_number(p["gas_usd"], "gas_usd", 0.0, 1000.0)
        if venue == "dex":
            check_dex_backtest({**p, "data": data}, out, out["symbols"])
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
    elif kind == "book_build":
        if p.get("only"):
            out["only"] = check_candidate_ids(p["only"])
        if p.get("n") is not None:
            out["n"] = check_number(p["n"], "n", 1, MAX_BUILD_CONFIGS, integer=True)
        if p.get("keep_top") is not None:
            out["keep_top"] = check_number(p["keep_top"], "keep_top", 3, 5000, integer=True)
        if p.get("force_large"):
            out["force_large"] = True
        if p.get("timeframe"):
            out["timeframe"] = check_timeframe(p["timeframe"])
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
    from backend.core.params import POSITION_KEYS
    from backend.core.signal import DslError
    from backend.alpha.compile import compile_code
    from backend.alpha.contract import MAX_CODE_CHARS
    from backend.core.params import FRAMES
    from backend.crawl.store import base_name
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


# ─── Lưu/đọc job.json ───────────────────────────────────────────────────────


# ─── Khởi chạy ──────────────────────────────────────────────────────────────


# ─── Vòng đời kết quả (ADR-P9 §4 bước 2–3) ──────────────────────────────────
# Loại khác (presets_build, alpha_revalidate, regime_report, funnel_book, funnel_recompute, data_promote): kết quả bền do chính job ghi
# -> xong là dọn thư mục process (không chép). Crawl: giữ tới khi staging/ hết tài sản chưa promote (xem _crawl_staged).


def http_launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    """launch() cho router: JobError -> HTTP 422, JobBusy -> 429. Trả {"job_id"}."""
    from fastapi import HTTPException
    try:
        return {"job_id": _proc.launch(kind, params)}
    except JobError as e:
        raise HTTPException(422, str(e))
    except JobBusy as e:
        raise HTTPException(429, str(e))


def build_and_launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    """build_job + http_launch cho router (P9.10a: gộp `_launch` của routes/book.py và routes/education.py): JobError khi kiểm tham số -> HTTP 422."""
    from fastapi import HTTPException
    try:
        job_params = build_job(kind, params)
    except JobError as e:
        raise HTTPException(422, str(e))
    return http_launch(kind, job_params)


# ─── Theo dõi ───────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════
# PHẦN 2: CHẾ ĐỘ CHẠY CƠ BẢN / NÂNG CAO (gộp từ modes.py)
# ══════════════════════════════════════════════════════════════════════════

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from backend.optimize.process import process as batch_jobs
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




# ══════════════════════════════════════════════════════════════════════════
# PHẦN 3: METADATA API CHO UI (gộp từ meta.py)
# ══════════════════════════════════════════════════════════════════════════

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Response

from backend.core.params import FRAME_MS
from backend.crawl import store
from backend.live import live as live_mod
from backend.metrics.charts import EDUCATION_HIDDEN_SECTIONS, NOTE_TOUR
from backend.metrics.metrics import METRIC_DEFS, METRIC_GROUPS
from backend.optimize.book import registry as book_reg
from backend.optimize.funnel import stages as funnel_stages
from backend.optimize.process import process as batch_process

meta_router = APIRouter(prefix="/api/studio", tags=["meta"])

_BOUNDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems")
_PREFIX_RE = re.compile(r"^(S\d)_")


def _get_limit_models() -> Dict[str, Any]:
    from backend.routes.optimize import FunnelRunRequest, FunnelBookRequest, _DateRange, WfaStrategyIn, McRequest, BuildRequest
    from backend.routes.alpha import CustomBacktestRequest
    from backend.routes.live import BotRequest
    from backend.routes.data import CrawlRequest, TicksRequest, RegimeReportRequest
    return {
        "funnel_run": FunnelRunRequest, "funnel_book": FunnelBookRequest, "custom_backtest": CustomBacktestRequest,
        "book_backtest": _DateRange, "book_wfa": WfaStrategyIn, "book_mc": McRequest,
        "book_build": BuildRequest, "live_bot": BotRequest, "regime_report": RegimeReportRequest,
        "data_crawl": CrawlRequest, "data_crawl_ticks": TicksRequest,
    }


def _prop(model, field: str) -> Dict[str, Any]:
    p = model.model_json_schema()["properties"][field]
    for alt in p.get("anyOf", []):   # Optional[...] -> nhánh không-null
        if alt.get("type") != "null":
            return {**alt, **{k: v for k, v in p.items() if k != "anyOf"}}
    return p


def _choices(model, field: str) -> List[str]:
    """Tập giá trị mà validator của route chấp nhận: pattern `^(a|b|c)$` hoặc enum/Literal (Pydantic schema)."""
    p = _prop(model, field)
    if "enum" in p:
        return list(p["enum"])
    m = re.match(r"^\^\(([^()]*)\)\$$", p.get("pattern", ""))
    return m.group(1).split("|") if m else []


def _limits() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, model in _get_limit_models().items():
        fields = {}
        for f in model.model_json_schema()["properties"]:
            p = _prop(model, f)
            b = {k: p[k] for k in _BOUNDS if k in p}
            if b:
                if "default" in p:
                    b["default"] = p["default"]
                fields[f] = b
        out[name] = fields
    return out


def _stage_of_prefix(prefix: str) -> Optional[str]:
    idx = int(prefix[1])
    for s, i in funnel_stages.ALL_STAGE_IDX.items():
        if i == idx:
            return s
    return None


def _funnel() -> Dict[str, Any]:
    st = funnel_stages
    stages = [{"id": s, "label": st.STAGE_LABELS.get(s), "idx": st.STAGE_IDX[s], "has_trades": s in st.TRADE_STAGES, "legacy": False} for s in st.STAGES]
    stages.append({"id": st.LEGACY_STAGE, "label": st.STAGE_LABELS.get(st.LEGACY_STAGE), "idx": st.LEGACY_STAGE_IDX[st.LEGACY_STAGE],
                   "has_trades": st.LEGACY_STAGE in st.TRADE_STAGES, "legacy": True})
    gates = []
    for name, value in st.thresholds_snapshot().items():   # hằng số ngưỡng hiện hành của stages.py (tên = tên hằng, giá trị = giá trị thật)
        m = _PREFIX_RE.match(name)
        if m:
            gates.append({"key": name, "value": value, "stage": _stage_of_prefix(m.group(1)), "source": "optimize/funnel/stages.py"})
    from backend.carlo import carlo
    for name in ("MC_MIN_SIMULATIONS", "MC_MAX_SIMULATIONS", "MC_RUIN_THRESHOLD_PCT", "MC_MAX_RUIN_PCT", "STRESS_MAX_MDD_PCT"):
        gates.append({"key": name, "value": getattr(carlo, name), "stage": "S4_montecarlo", "source": "carlo/carlo.py"})
    return {"stages": stages, "gates": gates}


def _live() -> Dict[str, Any]:
    from backend.routes.live import BotRequest
    modes = []
    for mode in live_mod.PROFILE_MODULES:
        modes.append({
            "mode": mode,
            "dir": "live/" + store.live_state_key("_", mode).split("/")[0],
            "engines": list(live_mod.ENGINES), "default_engine": store.default_engine(mode),
            "books": [b for b in live_mod.BOOKS if not (mode == "live" and b == "explore")],
            "exec": mode in live_mod.EXEC_MODES,
        })
    return {"modes": modes, "venues": _choices(BotRequest, "venue"), "books": list(live_mod.BOOKS), "engines": list(live_mod.ENGINES)}


def _jobs() -> Dict[str, Any]:
    kinds = []
    for kind, entry in batch_process.KINDS.items():
        dest = batch_process.persist_dest_base(kind)
        kinds.append({"kind": kind, "label": kind, "persist_to": os.path.relpath(dest, store.data_home()) if dest else None,
                      "ephemeral": kind in batch_process.EPHEMERAL_KINDS, "crawl": kind in batch_process.CRAWL_KINDS,
                      "params": sorted(entry["params"])})
    return {"kinds": kinds}


def _book_rel(book: Optional[Dict[str, Any]]) -> List[str]:
    return list(book.get("universe") or []) if book else []


def _fix(book: Optional[Dict[str, Any]], explore: bool) -> Dict[str, Any]:
    """Cách dựng lại sổ, lấy từ chính sổ: source -> run_id/wfa_job_id; strategies[].evidence.funnel_alpha_id; risk_per_trade_pct. Không từ phễu -> book_build."""
    src = book_reg.parse_book_source((book or {}).get("source"))
    if not src:
        return {"action": "book_build", "endpoint": "/api/studio/book/build"}
    ids = [(s.get("evidence") or {}).get("funnel_alpha_id") for s in (book or {}).get("strategies", [])]
    return {"action": "funnel_book", "endpoint": f"/api/studio/funnel/runs/{src['run_id']}/book",
            "body": {"alpha_ids": [i for i in ids if i], "risk_per_trade_pct": book.get("risk_per_trade_pct"),
                     "wfa_job_id": src["wfa_job_id"] or "", "explore": explore},
            "run_id": src["run_id"], "wfa_job_id": src["wfa_job_id"], "source": book["source"]}


def _book_status(book: Optional[Dict[str, Any]], explore: bool) -> Dict[str, Any]:
    st = book_reg.book_engine_status(book)
    if st.get("needs_rebuild"):
        st["fix"] = _fix(book, explore)
    return st


def _build_meta() -> Dict[str, Any]:
    from backend.routes.alpha import CustomBacktestRequest
    from backend.routes.optimize import FunnelRunRequest
    home = store.data_home()
    rel = lambda p: os.path.relpath(p, home)   # noqa: E731
    main_path, explore_path = store.alpha_file("book"), store.alpha_dir("explore", "book.json")
    main_book, explore_book = store.read_json(main_path), store.read_json(explore_path)
    ex = store.exchange()
    perp = [a["symbol"] for a in store.list_assets() if a.get("instrument") == "perp"]
    payload = {
        "funnel": _funnel(),
        "frames": {"all": list(FRAME_MS), "custom_backtest": _choices(CustomBacktestRequest, "run_frame"),
                   "funnel": _choices(FunnelRunRequest, "timeframe")},
        "live": _live(),
        "jobs": _jobs(),
        "universe": {"data": {"exchange": ex, "instrument": "perp", "assets": perp,
                              "markets": {e: rel(store.market_root(e)) for e in store.EXCHANGES}},
                     "book": _book_rel(main_book), "explore": _book_rel(explore_book)},
        "limits": _limits(),
        "metrics": {"defs": METRIC_DEFS, "groups": METRIC_GROUPS},
        "explain_tour": NOTE_TOUR,
        "education_hidden_sections": EDUCATION_HIDDEN_SECTIONS,
        "engine": book_reg.engine_version(),
        "books": {"main": _book_status(main_book, False), "explore": _book_status(explore_book, True)},
        "paths": {"book": rel(main_path), "explore_book": rel(explore_path), "registry": rel(store.alpha_file("registry")),
                  "presets": rel(store.alpha_file("presets")), "alpha_user": rel(store.alpha_user_dir()), "cache_process": rel(store.cache_process_dir()),
                  "market": {e: rel(store.market_root(e)) for e in store.EXCHANGES},
                  "live": rel(os.path.dirname(os.path.dirname(store.live_dir("_", "paper", "main"))))},
    }
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    return payload


@meta_router.get("/meta")
def get_studio_meta(response: Response, if_none_match: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Metadata UI từ nguồn thật, kèm ETag (If-None-Match khớp -> 304)."""
    meta = _build_meta()
    etag = f'"{meta["version"]}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return meta


ROUTERS = [meta_router]
