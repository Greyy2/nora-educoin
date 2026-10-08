"""Kiểm tham số job (P9.8): ngày, tài sản, số, thư mục báo cáo, chiến lược WFA, dựng params cho book_backtest/book_wfa/book_build/custom_backtest/edu_precompute, http_launch.

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
    elif kind == "edu_precompute":
        out = build_edu_precompute(p)
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


def build_edu_precompute(p: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số job edu_precompute: only (key mẫu có trong data/education/samples.json), start/end, train_ratio, initial_capital; trống = mặc định của job."""
    out: Dict[str, Any] = {}
    if p.get("only"):
        from backend.optimize.process.tasks import load_samples
        if not isinstance(p["only"], list) or not all(isinstance(k, str) for k in p["only"]):
            raise JobError("only phải là danh sách key mẫu")
        known = {s["key"] for s in load_samples()}
        bad = sorted(set(p["only"]) - known)
        if bad:
            raise JobError(f"mẫu không tồn tại: {bad}")
        out["only"] = list(dict.fromkeys(p["only"]))
    if p.get("start") or p.get("end"):
        if not (p.get("start") and p.get("end")):
            raise JobError("cần cả start và end")
        out["start"], out["end"] = check_date(p["start"]), check_date(p["end"])
        if p["start"] >= p["end"]:
            raise JobError("start phải trước end")
        if (_day_ms(p["end"], 1) - _day_ms(p["start"])) / 86_400_000 > MAX_CUSTOM_DAYS:
            raise JobError(f"khoảng chạy tối đa {MAX_CUSTOM_DAYS} ngày")
    if p.get("train_ratio") is not None:
        out["train_ratio"] = check_number(p["train_ratio"], "train_ratio", 0.1, 0.95)
    if p.get("initial_capital") is not None:
        out["initial_capital"] = check_number(p["initial_capital"], "initial_capital", 100.0, 1e9)
    return out


# ─── Lưu/đọc job.json ───────────────────────────────────────────────────────


# ─── Khởi chạy ──────────────────────────────────────────────────────────────


# ─── Vòng đời kết quả (ADR-P9 §4 bước 2–3) ──────────────────────────────────
# Loại khác (edu_precompute, presets_build, alpha_revalidate, regime_report, funnel_book, funnel_recompute, data_promote): kết quả bền do chính job ghi
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
