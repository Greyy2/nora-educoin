"""Job nền nặng của sổ chiến lược (backtest danh mục / WFA danh mục / dựng sổ), chạy NGOÀI tiến trình API.

Vì sao: API có trần RAM riêng (3G) nên không được chạy backtest/WFA nặng trong tiến trình. Mỗi job là một tiến trình con
`scripts/run_limited.sh -- scripts/<script>.py ...`: tự có scope riêng trong nora.slice (trần chung 12G), xếp hàng tuần tự
(flock) và tự chia worker theo RAM còn trống. API chỉ khởi chạy, theo dõi và đọc kết quả.

Mỗi job có thư mục <data>/_cache/api_jobs/<job_id>/:
  job.json    siêu dữ liệu (id, kind, args, pid, created/started/finished, state, exit_code)
  out.log     stdout+stderr của job
  result.json báo cáo cuối do script ghi (quy ước env NORA_JOB_DIR, xem backend/utils/jobresult.py)
  alphas/     (chỉ job book_build) sổ vừa dựng: book.json [+ testnet/book.json]; KHÔNG ghi đè nora/alphas/ — xuất bản qua POST /book/publish
Trạng thái trả ra: queued (đang chờ hàng đợi run_limited) | running | done | failed. Trạng thái bền (job.json) chỉ có running/done/failed;
queued suy ra từ out.log. Không dùng shell: danh sách đối số đi thẳng vào Popen.
"""
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN_LIMITED = os.path.join(NORA_DIR, "scripts", "run_limited.sh")

# Danh sách trắng: loại job -> (script, các cờ được phép)
KINDS: Dict[str, Dict[str, Any]] = {
    "book_backtest": {"script": "scripts/run_book_backtest.py",
                      "flags": {"--book", "--strategies", "--symbols", "--start", "--end", "--risk-per-trade", "--stop-fill"}},
    "book_wfa": {"script": "scripts/validate_book.py",
                 "flags": {"--report", "--include-rejected", "--candidates", "--strategies-json", "--symbols", "--n", "--start",
                           "--end", "--train-days", "--test-days", "--risk-per-trade", "--workers"}},
    "book_build": {"script": "scripts/build_strategy_book.py", "flags": {"--only", "--n", "--workers"}},
}
MAX_ACTIVE = 8          # số job đang chạy/chờ tối đa cùng lúc (mỗi job chờ là một tiến trình bash nhỏ)
LOG_TAIL_LINES = 40
WAITING_MARK = "đang chờ job khác của Nora"   # dòng run_limited.sh in khi xếp hàng
_JOB_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXIT_RE = re.compile(r"\[run_limited\] peak RAM .*\| exit (\d+)")
JOBDIR_TOKEN = "@JOBDIR"   # trong args: launch() thay bằng thư mục job (để ghi file đầu vào cho script)
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
    """Chuẩn hoá 'BTC' / 'BTC@perp' -> 'BTC@perp'; chỉ nhận tài sản trong vũ trụ của sổ chiến lược."""
    from backend.alpha.strategy_book import UNIVERSE
    out = []
    for s in symbols:
        base = str(s).split("@")[0].upper()
        if (("@" in str(s)) and str(s).split("@", 1)[1] != "perp") or base not in UNIVERSE:
            raise JobError(f"tài sản không thuộc vũ trụ {UNIVERSE} (perp): {s!r}")
        if f"{base}@perp" not in out:
            out.append(f"{base}@perp")
    return out


def check_candidate_ids(ids: List[str]) -> List[str]:
    from backend.alpha.strategy_book import CANDIDATES
    known = {c["id"] for c in CANDIDATES}
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
    return str(int(x)) if integer else repr(x)


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
    """[{"id", "configs": [{tham số: số}]}] do người dùng chọn: id thuộc thư viện, khoá thuộc không gian tham số của ứng viên."""
    from backend.alpha.strategy_book import CANDIDATES
    by_id = {c["id"]: c for c in CANDIDATES}
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
        for c in cfgs:
            if not isinstance(c, dict) or not all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                                  and math.isfinite(v) for k, v in c.items()):
                raise JobError(f"{s['id']}: mỗi cấu hình phải là {{tên: số}}")
            bad = sorted(set(c) - set(by_id[s["id"]]["space"]))
            if bad:
                raise JobError(f"{s['id']}: khoá không thuộc không gian tham số: {bad}")
        out.append({"id": s["id"], "configs": cfgs})
    return out


def build_args(kind: str, p: Dict[str, Any]) -> List[str]:
    """Từ tham số đã qua pydantic -> danh sách đối số CLI (đã kiểm lại ở đây: tầng này không tin router)."""
    return build_job(kind, p)[0]


def build_job(kind: str, p: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    """(đối số CLI, {tên file: nội dung JSON} cần ghi vào thư mục job trước khi chạy). Đối số trỏ tới file đó bằng `@JOBDIR/<tên>`."""
    if kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    a: List[str] = []
    files: Dict[str, Any] = {}
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
            a += ["--strategies", json.dumps(items, ensure_ascii=False)]
        if p.get("symbols"):
            a += ["--symbols", ",".join(check_symbols(p["symbols"]))]
        a += ["--start", check_date(p["start"]), "--end", check_date(p["end"])]
        if p["start"] >= p["end"]:
            raise JobError("start phải trước end")
        if p.get("risk_per_trade_pct") is not None:
            a += ["--risk-per-trade", check_number(p["risk_per_trade_pct"], "risk_per_trade_pct", 0.01, 5.0)]
        if p.get("stop_fill"):
            if p["stop_fill"] not in ("level", "extreme"):
                raise JobError("stop_fill phải là level|extreme")
            a += ["--stop-fill", p["stop_fill"]]
    elif kind == "book_wfa":
        if sum(map(bool, (p.get("report_dir"), p.get("candidates"), p.get("strategies")))) != 1:
            raise JobError("chọn đúng một: report_dir, candidates hoặc strategies")
        if p.get("report_dir"):
            a += ["--report", check_report_dir(p["report_dir"])]
            if p.get("include_rejected"):
                a += ["--include-rejected"]
        elif p.get("strategies"):
            files["strategies.json"] = check_wfa_strategies(p["strategies"])
            a += ["--strategies-json", f"{JOBDIR_TOKEN}/strategies.json"]
        else:
            a += ["--candidates", ",".join(check_candidate_ids(p["candidates"]))]
        a += ["--n", check_number(p.get("n", 3), "n", 1, 50, integer=True)]
        for key, flag in (("start", "--start"), ("end", "--end")):
            if p.get(key):
                a += [flag, check_date(p[key])]
        if p.get("start") and p.get("end") and p["start"] >= p["end"]:
            raise JobError("start phải trước end")
        if p.get("symbols"):
            a += ["--symbols", ",".join(check_symbols(p["symbols"]))]
        if p.get("train_days") is not None:
            a += ["--train-days", check_number(p["train_days"], "train_days", 7, 1000, integer=True)]
        if p.get("test_days") is not None:
            a += ["--test-days", check_number(p["test_days"], "test_days", 1, 365, integer=True)]
        if p.get("risk_per_trade_pct") is not None:
            a += ["--risk-per-trade", check_number(p["risk_per_trade_pct"], "risk_per_trade_pct", 0.01, 5.0)]
    else:  # book_build
        if p.get("only"):
            a += ["--only", ",".join(check_candidate_ids(p["only"]))]
        if p.get("n") is not None:
            a += ["--n", check_number(p["n"], "n", 1, 200, integer=True)]
    return a, files


def _check_launch_args(kind: str, args: List[str]) -> None:
    if kind not in KINDS:
        raise JobError(f"loại job không có trong danh sách trắng: {kind!r}")
    if not isinstance(args, list) or not all(isinstance(x, str) and "\0" not in x for x in args):
        raise JobError("args phải là danh sách chuỗi")
    allowed = KINDS[kind]["flags"]
    bad = [x for x in args if x.startswith("--") and x not in allowed]
    if bad:
        raise JobError(f"cờ không được phép cho {kind}: {bad}")


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
        meta.update(state="done" if exit_code == 0 else "failed", exit_code=exit_code, finished=time.time())
        if exit_code is None:
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


def launch(kind: str, args: List[str], files: Optional[Dict[str, Any]] = None) -> str:
    """Khởi chạy job nền, trả job_id ngay (không chờ). args/files đã qua build_job (`@JOBDIR/<tên>` -> file trong thư mục job)."""
    _check_launch_args(kind, args)
    if _active_count() >= MAX_ACTIVE:
        raise JobBusy(f"đang có >= {MAX_ACTIVE} job chạy/chờ; thử lại sau")
    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job_dir = os.path.join(jobs_root(), job_id)
    os.makedirs(job_dir)
    for name, content in (files or {}).items():
        with open(os.path.join(job_dir, os.path.basename(name)), "w", encoding="utf-8") as fh:
            json.dump(content, fh, ensure_ascii=False)
    args = [os.path.join(job_dir, x[len(JOBDIR_TOKEN) + 1:]) if x.startswith(JOBDIR_TOKEN + "/") else x for x in args]
    if kind == "book_build":   # sổ dựng xong nằm trong thư mục job; alphas/ chỉ đổi khi người dùng xuất bản (book_export.publish_book)
        args += ["--out", os.path.join(job_dir, "alphas")]
    env = dict(os.environ, NORA_JOB_DIR=job_dir)
    # Khi API chạy từ user service, run_limited.sh cần bus của user session để gọi systemd-run --user.
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    cmd = [RUN_LIMITED, "--", KINDS[kind]["script"], *args]
    log = open(os.path.join(job_dir, "out.log"), "ab")
    try:
        proc = subprocess.Popen(cmd, cwd=NORA_DIR, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()  # tiến trình con giữ bản riêng của fd
    now = time.time()
    with _LOCK:
        _write_meta(job_dir, {"id": job_id, "kind": kind, "args": args, "pid": proc.pid, "created": now, "started": None,
                              "finished": None, "state": "running", "exit_code": None})
    threading.Thread(target=_waiter, args=(proc, job_dir), name=f"batch-job-{job_id}", daemon=True).start()
    return job_id


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
    out["_lines"] = lines
    return out


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


def _arg(args: List[str], flag: str) -> Optional[str]:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def job_label(kind: str, args: List[str]) -> str:
    """Nhãn ngắn cho người đọc, vd "Backtest · breakout_4h_long, breakout_4h_short · BTC,SOL · 2025-03-01→2025-04-30"."""
    args = args or []
    syms = _arg(args, "--symbols")
    syms = ",".join(x.split("@")[0] for x in syms.split(",") if x) if syms else "cả vũ trụ"
    rng = f"{_arg(args, '--start') or '…'}→{_arg(args, '--end') or '…'}"
    if kind == "book_backtest":
        ids = "sổ alphas/book.json"
        raw = _arg(args, "--strategies")
        if raw:
            try:
                ids = ", ".join(s["id"] for s in json.loads(raw))
            except (ValueError, KeyError, TypeError):
                ids = "tự chọn"
        return f"Backtest · {ids} · {syms} · {rng}"
    if kind == "book_wfa":
        if _arg(args, "--candidates"):
            src = f"{_arg(args, '--candidates').replace(',', ', ')} (n={_arg(args, '--n') or 3})"
        elif _arg(args, "--strategies-json"):
            src = "cấu hình chọn tay"
            try:
                with open(_arg(args, "--strategies-json"), encoding="utf-8") as fh:
                    src = ", ".join(f"{s['id']}×{len(s['configs'])}" for s in json.load(fh))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        else:
            src = f"báo cáo {os.path.basename(_arg(args, '--report') or '?')}"
        return f"WFA · {src} · {syms} · {rng}" if (_arg(args, "--start") or _arg(args, "--symbols")) else f"WFA · {src}"
    only = _arg(args, "--only")
    return f"Dựng sổ · {only.replace(',', ', ') if only else 'mọi chiến lược'} · n={_arg(args, '--n') or 24}"


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
        s["label"] = job_label(s.get("kind"), s.get("args") or [])
        rows.append(s)
        if len(rows) >= limit:
            break
    return rows
