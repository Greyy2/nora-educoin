"""Job nền nặng (backtest, WFA, dựng sổ, phễu, dữ liệu...), chạy NGOÀI tiến trình API qua MỘT cửa: backend/api/jobs/runner.py.

Vì sao: API có trần RAM riêng (3G) nên không được chạy việc nặng trong tiến trình. Mỗi job là một tiến trình con
`backend/utils/ops/run_limited.sh -- -m backend.api.jobs.runner <job_dir>`: tự có scope riêng trong nora.slice (trần chung 12G), xếp hàng
tuần tự (flock) và tự chia worker theo RAM còn trống. runner đọc job.json {kind, params} rồi gọi run_job(params) của module trong KINDS.
API chỉ khởi chạy, theo dõi và đọc kết quả. UI, terminal (curl) và script đều đi qua cùng endpoint -> cùng job.

Mỗi job có thư mục <data>/_cache/api_jobs/<job_id>/:
  params.json đầu vào của runner {kind, params}
  job.json    siêu dữ liệu (id, kind, params, pid, created/started/finished, state, exit_code)
  out.log     stdout+stderr của job
  result.json báo cáo cuối do script ghi (quy ước env NORA_JOB_DIR, xem backend/utils/jobs.py)
  alphas/     (chỉ job book_build) sổ vừa dựng: book.json [+ testnet/book.json]; KHÔNG ghi đè nora/data/alphas/ — xuất bản qua POST /book/publish
  progress.json  (job tối ưu quy mô lớn) tiến độ do job ghi mỗi <= 5 giây: stage, done, total, rate, eta_s, peak_rss_mb (xem backend/utils/jobs.py)
Trạng thái trả ra: queued (đang chờ hàng đợi run_limited) | running | done | failed | cancelled. Trạng thái bền (job.json) chỉ có running/done/failed/cancelled;
queued suy ra từ out.log. Huỷ: cancel(job_id) gửi SIGTERM cho CẢ nhóm tiến trình (job flush kho kết quả rồi thoát -> chạy lại bằng resume). Không dùng shell.
"""
import calendar
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RUN_LIMITED = os.path.join(NORA_DIR, "backend", "utils", "ops", "run_limited.sh")

# Danh sách trắng: loại job -> (module có run_job(params), các khoá tham số được phép)
RUNNER = "backend.api.jobs.runner"
KINDS: Dict[str, Dict[str, Any]] = {
    "book_backtest": {"module": "backend.core.backtest.run",
                      "params": {"book", "strategies", "symbols", "start", "end", "risk_per_trade", "stop_fill", "regime", "timeframe", "data", "latency_ms", "gas_usd"}},
    "book_wfa": {"module": "backend.wfa.run",
                 "params": {"report", "include_rejected", "candidates", "strategies", "symbols", "n", "start", "end", "train_days",
                            "test_days", "step_days", "sims", "mc_seed", "risk_per_trade", "workers", "resume", "max_configs", "force_large",
                            "timeframe", "regime"}},
    "book_build": {"module": "backend.optimize.book",
                   "params": {"only", "n", "workers", "keep_top", "resume", "max_configs", "force_large", "timeframe"}},   # out do launch() đặt
    "funnel_run": {"module": "backend.optimize.funnel.run",
                   "params": {"strategies", "n_per_strategy", "full_grid", "seed", "symbols", "windows", "run_id", "resume", "force_large",
                              "train_days", "test_days", "space", "timeframe", "regime"}},
    "funnel_recompute": {"module": "backend.optimize.funnel.recompute", "params": {"run_id", "alpha_id"}},
    "live_bot": {"module": "backend.live.bot", "params": {"mode", "venue", "once", "max_steps", "capital", "confirm_live", "book",
                                                                 "engine", "equity_drift_halt_pct"}},
    "funnel_book": {"module": "backend.optimize.funnel.publish",
                    "params": {"run_id", "alpha_ids", "risk_per_trade_pct", "wfa_job_id", "dry_run", "explore"}},
    "presets_build": {"module": "backend.core.params.presets", "params": set()},
    "data_crawl": {"module": "backend.core.data.crawler", "params": {"symbols", "market", "years", "output_dir"}},   # output_dir do router đặt
    "data_crawl_okx": {"module": "backend.core.data.okx_crawler", "params": {"symbols", "years", "output_dir"}},
    "data_crawl_ticks": {"module": "backend.core.data.tick_crawler", "params": {"symbols", "days"}},
    "data_promote": {"module": "backend.core.data.promote", "params": {"apply", "archive_legacy"}},
    "alpha_revalidate": {"module": "backend.optimize.revalidate", "params": {"alpha_id", "apply"}},
    "custom_backtest": {"module": "backend.core.backtest.custom_run",
                        "params": {"code", "profile", "universe", "symbols", "start", "end", "train_ratio", "initial_capital", "position", "exchange",
                                   "run_frame", "market"}},
    "edu_precompute": {"module": "backend.core.backtest.edu_precompute", "params": {"only", "start", "end", "train_ratio", "initial_capital"}},
    "regime_report": {"module": "backend.core.regime.report", "params": {"symbols", "start", "end", "event_pct", "backtest", "timeframe"}},
}
NO_LOCK_KINDS = {"live_bot"}
MAX_BUILD_CONFIGS = 1_000_000   # trần cứng của API cho --n (mỗi chiến lược); CLI còn có --max-configs (mặc định 200000) + --force-large
MAX_ACTIVE = 8          # số job đang chạy/chờ tối đa cùng lúc (mỗi job chờ là một tiến trình bash nhỏ)
LOG_TAIL_LINES = 40
WAITING_MARK = "đang chờ job khác của Nora"   # dòng run_limited.sh in khi xếp hàng
_JOB_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXIT_RE = re.compile(r"\[run_limited\] peak RAM .*\| exit (\d+)")
MAX_WFA_STRATEGIES, MAX_WFA_CONFIGS = 16, 50
_LOCK = threading.Lock()


class JobError(ValueError):
    """Đối số/loại job không hợp lệ (router đổi thành HTTP 422)."""


class JobBusy(RuntimeError):
    """Quá nhiều job đang chạy (router đổi thành HTTP 429)."""


# ─── Đường dẫn ──────────────────────────────────────────────────────────────
def jobs_root() -> str:
    from backend.db.data_layout import cache_dir
    return cache_dir(None, "api_jobs")


def job_dir(job_id: str) -> str:
    return _job_dir(job_id)


def _job_dir(job_id: str) -> str:
    if not _JOB_ID_RE.match(str(job_id)):
        raise JobError(f"job_id không hợp lệ: {job_id!r}")
    return os.path.join(jobs_root(), job_id)


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
    from backend.core.backtest import dex
    from backend.core.strategy.book import UNIVERSE
    try:
        dex.require_perp(symbols, "WFA / phễu")
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
    from backend.core.backtest import dex
    flags = [dex.is_dex_symbol(str(s)) for s in symbols]
    if not any(flags):
        return check_symbols(symbols), "cex"
    if not all(flags):
        raise JobError("không chạy chung tài sản perp (CEX) với tài sản DEX trong một lần backtest — chọn một loại")
    from backend.db.data_layout import clean_name, parse_symbol, resolve_asset_dir
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
    from backend.core.backtest import dex
    if not p.get("strategies"):
        raise JobError("backtest DEX cần chọn chiến lược (chân LONG): sổ data/alphas/book.json là sổ perp")
    try:
        dex.require_long_legs([s["id"] for s in p["strategies"]])
        if p.get("data") == "tick":
            from backend.db.local_pkl import _frame_ms
            infos = [dex.pool_info(s) for s in symbols]
            for i in infos:
                dex.check_amm_pool(i)
            dex.tick_window(infos, _day_ms(p["start"]), _day_ms(p["end"], 1), _frame_ms(out.get("timeframe") or "1m"))
    except ValueError as e:
        raise JobError(str(e))


def check_candidate_ids(ids: List[str]) -> List[str]:
    from backend.core.strategy.book import BY_ID
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
    """Thư mục lần chạy build_strategy_book: tên thư mục hoặc đường dẫn nằm TRONG <data>/_cache/book/, có stage_a.json + report.json."""
    from backend.db.data_layout import cache_dir
    base = os.path.realpath(cache_dir(None, "book"))
    path = os.path.realpath(report_dir if os.path.isabs(report_dir) else os.path.join(base, report_dir))
    if os.path.dirname(path) != base:
        raise JobError("report_dir phải là một lần chạy trong data/_cache/book/")
    for name in ("stage_a.json", "report.json"):
        if not os.path.isfile(os.path.join(path, name)):
            raise JobError(f"report_dir thiếu {name}")
    return path


def check_wfa_strategies(items: Any) -> List[Dict[str, Any]]:
    """[{"id", "configs": [{tham số: giá trị}]}] do người dùng chọn: id thuộc thư viện; khoá thuộc `space` hoặc `params_schema` của ứng viên;
    giá trị là số hữu hạn, riêng khoá kiểu "choice" (khung thời gian) là chuỗi nằm trong danh sách lựa chọn."""
    from backend.core.strategy.book import BY_ID
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
_EXCHANGE_RE = re.compile(r"^[a-z0-9_]{2,24}$")


def build_custom_backtest(p: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số job custom_backtest (chiến lược Python): kiểm code bằng chính trình biên dịch (lỗi -> JobError kèm dòng/cột), hồ sơ, rổ, ngày, vốn, vị thế."""
    from backend.core.params.builder import POSITION_KEYS
    from backend.core.strategy.pydsl import DslError, compile_code
    from backend.core.strategy.pydsl.parser import MAX_CODE_CHARS
    from backend.core.strategy.pydsl.profiles import FRAMES, base_name
    out: Dict[str, Any] = {}
    code = p.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
        raise JobError(f"code phải là chuỗi không rỗng, tối đa {MAX_CODE_CHARS} ký tự")
    try:
        compile_code(code, register=False)
    except DslError as e:
        raise JobError(f"Lỗi biên dịch chiến lược: {e}")
    out["code"] = code
    profile = p.get("profile") or "xno"
    if profile not in ("xno", "nora"):
        raise JobError("profile phải là xno|nora")
    out["profile"] = profile
    if p.get("universe"):
        if str(p["universe"]).upper() != "TOP10":
            raise JobError("universe chỉ hỗ trợ TOP10")
        out["universe"] = "TOP10"
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
    if p.get("exchange"):
        if not _EXCHANGE_RE.match(str(p["exchange"])):
            raise JobError("exchange phải dạng chữ thường/số/gạch dưới (vd. okx, binance)")
        out["exchange"] = str(p["exchange"])
    if p.get("run_frame"):
        if p["run_frame"] not in FRAMES:
            raise JobError(f"run_frame phải thuộc {list(FRAMES)}")
        out["run_frame"] = p["run_frame"]
    if p.get("market"):
        if p["market"] not in ("perp", "spot"):
            raise JobError("market phải là perp|spot")
        out["market"] = p["market"]
    return out


def build_edu_precompute(p: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số job edu_precompute: only (key mẫu có trong data/education/samples.json), start/end, train_ratio, initial_capital; trống = mặc định của job."""
    out: Dict[str, Any] = {}
    if p.get("only"):
        from backend.core.backtest.edu_precompute import load_samples
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


def _check_params(kind: str, params: Dict[str, Any]) -> None:
    if kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    if not isinstance(params, dict):
        raise JobError("params phải là dict")
    bad = sorted(set(params) - KINDS[kind]["params"])
    if bad:
        raise JobError(f"tham số không được phép cho {kind}: {bad}")
    try:
        json.dumps(params, allow_nan=False)   # phải ghi được ra params.json (không NaN/kiểu lạ)
    except (TypeError, ValueError) as e:
        raise JobError(f"params không ghi được JSON: {e}")


# ─── Lưu/đọc job.json ───────────────────────────────────────────────────────
def _read_meta(job_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_meta(job_dir: str, meta: Dict[str, Any]) -> None:
    tmp = os.path.join(job_dir, "job.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(job_dir, "job.json"))


def _finish(job_dir: str, exit_code: Optional[int]) -> Dict[str, Any]:
    """Ghi kết thúc một lần (waiter thread hoặc status() phát hiện): done nếu thoát 0 / có result.json khi không rõ mã thoát."""
    with _LOCK:
        meta = _read_meta(job_dir) or {}
        if meta.get("state") in ("done", "failed"):
            return meta
        has_result = os.path.isfile(os.path.join(job_dir, "result.json"))
        if exit_code is None:  # tiến trình mất dấu (API khởi động lại): thử mã thoát ở dòng cuối run_limited, rồi tới result.json
            m = _EXIT_RE.findall(_tail_text(os.path.join(job_dir, "out.log"), 8192))
            exit_code = int(m[-1]) if m else (0 if has_result else None)
        state = "done" if exit_code == 0 else "failed"
        if meta.get("cancel_requested") and exit_code != 0 and not has_result:
            state = "cancelled"   # người dùng bấm Huỷ: SIGTERM -> CLI flush kho rồi thoát khác 0 (chạy lại bằng --resume)
        meta.update(state=state, exit_code=exit_code, finished=time.time())
        if exit_code is None and state != "cancelled":
            meta["error"] = "tiến trình kết thúc không rõ mã thoát và không có result.json"
        _write_meta(job_dir, meta)
        return meta


def _waiter(proc: "subprocess.Popen", job_dir: str) -> None:
    try:
        code = proc.wait()
    except Exception:
        code = None
    _finish(job_dir, code)


# ─── Khởi chạy ──────────────────────────────────────────────────────────────
def _active_count() -> int:
    n = 0
    root = jobs_root()
    for name in os.listdir(root):
        meta = _read_meta(os.path.join(root, name))
        if meta and meta.get("state") == "running" and _alive(meta.get("pid")):
            n += 1
    return n


def _env() -> Dict[str, str]:
    env = dict(os.environ)
    # Khi API chạy từ user service, run_limited.sh cần bus của user session để gọi systemd-run --user.
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    env["PYTHONUNBUFFERED"] = "1"     # log của job hiện ngay trong out.log (không chờ đầy bộ đệm)
    return env


def launch(kind: str, params: Dict[str, Any]) -> str:
    """Khởi chạy job nền, trả job_id ngay (không chờ). params đã qua build_job / router."""
    params = dict(params)
    _check_params(kind, params)
    if _active_count() >= MAX_ACTIVE:
        raise JobBusy(f"đang có >= {MAX_ACTIVE} job chạy/chờ; thử lại sau")
    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job_dir = os.path.join(jobs_root(), job_id)
    os.makedirs(job_dir)
    if kind == "book_build":   # sổ dựng xong nằm trong thư mục job; alphas/ chỉ đổi khi người dùng xuất bản (book_export.publish_book)
        params["out"] = os.path.join(job_dir, "alphas")
    with open(os.path.join(job_dir, "params.json"), "w", encoding="utf-8") as fh:   # đầu vào của runner (ghi TRƯỚC khi chạy)
        json.dump({"kind": kind, "params": params}, fh, ensure_ascii=False)
    env = dict(_env(), NORA_JOB_DIR=job_dir)
    # bot chạy lâu (live_bot): không giữ khoá hàng đợi job nặng, vẫn trong nora.slice
    cmd = [RUN_LIMITED] + (["--no-lock"] if kind in NO_LOCK_KINDS else []) + ["--", "-m", RUNNER, job_dir]
    log = open(os.path.join(job_dir, "out.log"), "ab")
    try:
        proc = subprocess.Popen(cmd, cwd=NORA_DIR, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()  # tiến trình con giữ bản riêng của fd
    with _LOCK:
        _write_meta(job_dir, {"id": job_id, "kind": kind, "params": params, "pid": proc.pid, "created": time.time(), "started": None,
                              "finished": None, "state": "running", "exit_code": None})
    threading.Thread(target=_waiter, args=(proc, job_dir), name=f"batch-job-{job_id}", daemon=True).start()
    return job_id


def http_launch(kind: str, params: Dict[str, Any]) -> Dict[str, str]:
    """launch() cho router: JobError -> HTTP 422, JobBusy -> 429. Trả {"job_id"}."""
    from fastapi import HTTPException
    try:
        return {"job_id": launch(kind, params)}
    except JobError as e:
        raise HTTPException(422, str(e))
    except JobBusy as e:
        raise HTTPException(429, str(e))


def run_sync(kind: str, params: Dict[str, Any], job_dir: str, timeout: float = 1800) -> None:
    """Chạy một job NGAY và chờ xong (không qua hàng đợi: run_limited --no-lock, vẫn trong nora.slice). Dùng cho việc ngắn mà API cần
    kết quả tại chỗ (vd. tính lại lệnh một alpha). Lỗi -> RuntimeError kèm đuôi log; quá thời gian -> TimeoutError."""
    _check_params(kind, params)
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "params.json"), "w", encoding="utf-8") as fh:
        json.dump({"kind": kind, "params": params}, fh, ensure_ascii=False)
    try:
        p = subprocess.run([RUN_LIMITED, "--no-lock", "--", "-m", RUNNER, job_dir], cwd=NORA_DIR, env=dict(_env(), NORA_JOB_DIR=job_dir),
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"{kind}: quá {timeout:.0f} giây")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "")[-400:])


# ─── Theo dõi ───────────────────────────────────────────────────────────────
def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            state = fh.read().rsplit(b")", 1)[1].split()[0]
        return state != b"Z"
    except (OSError, IndexError, ValueError):
        return False


def _tail_text(path: str, nbytes: int) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - nbytes))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _summary(job_dir: str) -> Optional[Dict[str, Any]]:
    meta = _read_meta(job_dir)
    if not meta:
        return None
    if meta.get("state") == "running" and not _alive(meta.get("pid")):
        meta = _finish(job_dir, None)   # waiter không còn (API khởi động lại) hoặc đã ghi xong
    tail = _tail_text(os.path.join(job_dir, "out.log"), 65536)
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    waiting = (meta.get("state") == "running" and bool(lines)
               and all(WAITING_MARK in ln for ln in lines))
    if meta.get("state") == "running" and not waiting and not meta.get("started"):
        with _LOCK:
            fresh = _read_meta(job_dir) or meta
            fresh["started"] = fresh.get("started") or time.time()
            _write_meta(job_dir, fresh)
            meta = fresh
    status = "queued" if waiting else meta["state"]
    out = {**meta, "status": status, "waiting_in_queue": waiting}
    out["progress"] = _read_progress(job_dir) if status in ("running", "done", "cancelled", "failed") else None
    out["_lines"] = lines
    return out


def _read_progress(job_dir: str) -> Optional[Dict[str, Any]]:
    """progress.json do CLI ghi (stage/done/total/rate/eta_s/peak_rss_mb); None nếu job không có/chưa ghi."""
    try:
        with open(os.path.join(job_dir, "progress.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        return p if isinstance(p, dict) else None
    except (OSError, ValueError):
        return None


def cancel(job_id: str) -> Optional[Dict[str, Any]]:
    """Huỷ job đang chạy/chờ: SIGTERM cho CẢ nhóm tiến trình (job chạy với start_new_session -> pgid = pid). CLI bắt SIGTERM, flush kho
    kết quả rồi thoát nên có thể chạy tiếp bằng --resume <run_dir>. Sau 20 giây nhóm còn sống thì SIGKILL. Trả trạng thái mới;
    None nếu không có job. Job đã kết thúc -> JobError."""
    job_dir = _job_dir(job_id)
    meta = _read_meta(job_dir)
    if meta is None:
        return None
    pid = meta.get("pid")
    if meta.get("state") != "running" or not _alive(pid):
        raise JobError(f"job không còn chạy (trạng thái {meta.get('state')})")
    with _LOCK:
        fresh = _read_meta(job_dir) or meta
        fresh["cancel_requested"] = time.time()
        _write_meta(job_dir, fresh)
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise JobError(f"không gửi được SIGTERM cho nhóm tiến trình {pid}: {exc}")

    def _hard_kill():
        try:
            os.killpg(int(pid), 0)            # nhóm còn sống?
            os.killpg(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    timer = threading.Timer(20.0, _hard_kill)
    timer.daemon = True
    timer.start()
    return status(job_id)


def status(job_id: str) -> Optional[Dict[str, Any]]:
    """Trạng thái một job (làm mới theo pid/mã thoát) + 40 dòng log cuối + result.json khi đã xong. None nếu không có job."""
    job_dir = _job_dir(job_id)
    out = _summary(job_dir)
    if out is None:
        return None
    out["log_tail"] = out.pop("_lines")[-LOG_TAIL_LINES:]
    out["result"] = None
    if out["status"] == "done":
        try:
            with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as fh:
                out["result"] = json.load(fh)
        except (OSError, ValueError):
            out["result"] = None
    return out


def _names(v: Any) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) else str(v or "").replace(",", ", ")


def job_label(kind: str, params: Optional[Dict[str, Any]]) -> str:
    """Nhãn ngắn cho người đọc, vd "Backtest · breakout_4h_long, breakout_4h_short · BTC,SOL · 2025-03-01→2025-04-30"."""
    p = params if isinstance(params, dict) else {}
    syms = ",".join(str(x).split("@")[0].split(":")[-1] for x in p["symbols"]) if p.get("symbols") else "cả vũ trụ"
    rng = f"{p.get('start') or '…'}→{p.get('end') or '…'}"
    if kind == "book_backtest":
        ids = ", ".join(s["id"] for s in p["strategies"]) if p.get("strategies") else "sổ alphas/book.json"
        return f"Backtest{' tick' if p.get('data') == 'tick' else ''} · {ids} · {syms} · {rng}"
    if kind == "book_wfa":
        if p.get("candidates"):
            src = f"{_names(p['candidates'])} (n={p.get('n') or 3})"
        elif p.get("strategies"):
            src = ", ".join(f"{s['id']}×{len(s['configs'])}" for s in p["strategies"])
        else:
            src = f"báo cáo {os.path.basename(p.get('report') or '?')}"
        return f"WFA · {src} · {syms} · {rng}" if (p.get("start") or p.get("symbols")) else f"WFA · {src}"
    if kind == "funnel_run":
        if p.get("resume"):
            return f"Phễu · chạy tiếp {p['resume']}"
        n = "lưới đủ" if p.get("full_grid") else f"n={p.get('n_per_strategy') or '?'}/chiến lược"
        return f"Phễu · {_names(p.get('strategies')) or '?'} · {n} · {syms}"
    if kind == "funnel_recompute":
        return f"Phễu · tính lại lệnh {p.get('alpha_id')}"
    if kind == "live_bot":
        return (f"Bot sổ · {p.get('venue', 'okx')} {p.get('mode')}" + (" · sổ thử nghiệm" if p.get("book") == "explore" else "")
                + (" · một bước" if p.get("once") else "") + (" · unified" if p.get("engine") == "unified" else ""))
    if kind == "funnel_book":
        return (f"Phễu · xuất bản sổ {'thử nghiệm ' if p.get('explore') else ''}từ {p.get('run_id')} ({p.get('alpha_ids')}) "
                f"rủi ro {p.get('risk_per_trade_pct')}%")
    if kind == "presets_build":
        return "Dựng presets.json"
    if kind == "data_crawl":
        return f"Tải dữ liệu · {_names(p.get('symbols'))} · {p.get('market', 'spot')} · {p.get('years', 3)} năm"
    if kind == "data_crawl_okx":
        return f"Tải dữ liệu OKX · {_names(p.get('symbols'))} · perp · {p.get('years', 3)} năm"
    if kind == "data_crawl_ticks":
        return f"Tải tick · {_names(p.get('symbols'))} · {p.get('days')} ngày"
    if kind == "data_promote":
        return f"Đưa dữ liệu staging vào kho · {'thực hiện' if p.get('apply') else 'xem trước'}"
    return f"Dựng sổ · {_names(p.get('only')) or 'mọi chiến lược'} · n={p.get('n') or 24}"


def list_jobs(limit: int = 20, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Job mới nhất trước (không kèm log/result), có `label`. `kind` lọc theo loại job (lọc TRƯỚC khi cắt limit)."""
    limit = max(1, min(int(limit), 100))
    if kind is not None and kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    rows = []
    for n in sorted((n for n in os.listdir(jobs_root()) if _JOB_ID_RE.match(n)), reverse=True):
        s = _summary(os.path.join(jobs_root(), n))
        if not s or (kind and s.get("kind") != kind):
            continue
        s.pop("_lines", None)
        s["label"] = job_label(s.get("kind"), s.get("params"))
        rows.append(s)
        if len(rows) >= limit:
            break
    return rows
