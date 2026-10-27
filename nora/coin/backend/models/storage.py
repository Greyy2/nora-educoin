"""Quản lý đường dẫn, gốc dữ liệu và thao tác IO/cache nguyên tử của Nora (ADR-P9 / P17 T1).

Đường dẫn + IO + cache dùng chung (tách khỏi kho dữ liệu thị trường, nay ở backend/data/).
"""
import datetime as _dt
import json
import math
import os
import threading
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, Dict, Hashable, List, Optional

import numpy as np


# ─── Gốc dữ liệu ─────────────────────────────────────────────────────────────
from pathlib import Path as _Path
_DEFAULT_DATA_ROOT = str(_Path(__file__).resolve().parent.parent.parent / "data")
NORA_DATA_ROOT = os.environ.get("NORA_DATA_ROOT", _DEFAULT_DATA_ROOT)
DATA_DIR = NORA_DATA_ROOT
VENUES = ("cex", "dex")


def iso_date(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def data_home() -> str:
    """Gốc cây dữ liệu, theo env tại thời điểm gọi: NORA_LOCAL_DATA_ROOT (test) > NORA_DATA_ROOT > nora/data."""
    return os.environ.get("NORA_LOCAL_DATA_ROOT") or os.environ.get("NORA_DATA_ROOT") or DATA_DIR


def _kind_path(home: str, kind: str) -> str:
    j = os.path.join
    table = {
        "alpha": j(home, "alpha"),
        "funnel": j(home, "alpha", "funnel"),
        "book": j(home, "alpha", "book"),
        "backtest": j(home, "backtest"),
        "wfa": j(home, "wfa"),
        "carlo": j(home, "carlo"),
        "live": j(home, "live"),
        "users": j(home, "users"),
        "process": j(home, "cache", "process"),
        "mem": j(home, "cache", "process", "_mem"),
        "shared": j(home, "cache", "shared"),
    }
    return table[kind]


_SHARED_CACHE_KINDS = ("shared",)


def _under(home: str, kind: str, *parts: str) -> str:
    """Đường dưới gốc của `kind`. Cache dùng chung (shared) không bao giờ nằm trong market/: khi home là market/<sàn>
    (chế độ phẳng trỏ vào cây thật, vd. golden NORA_DATA_ROOT=data/market/binance) thì dùng gốc cây data/ chứa nó."""
    if kind in _SHARED_CACHE_KINDS:
        parent = os.path.dirname(os.path.abspath(home))
        if os.path.basename(parent) == "market":
            home = os.path.dirname(parent)
    return os.path.join(_kind_path(home, kind), *parts)


LEGACY_CACHE_NAMES = {
    "api_jobs": "process",
    "book": "book",
    "funnel": "funnel",
    "book_wfa": "wfa",
    "live": "live",
    "runs": "mem",
}


# ─── Alpha / Run / Live ──────────────────────────────────────────────────────
def alpha_dir(*parts: str) -> str:
    """Kho alpha: alpha/. NORA_ALPHAS_DIR (nếu đặt) ghi đè gốc — một chỗ thay các bản sao alphas_dir()."""
    env = os.environ.get("NORA_ALPHAS_DIR")
    return os.path.join(env, *parts) if env else _under(data_home(), "alpha", *parts)


def alpha_file(*parts: str) -> str:
    """File tên cố định trong kho alpha ('book' | 'registry' | 'presets' hoặc 'x.json'). NORA_BOOK_PATH / NORA_PRESETS_PATH ghi đè book/presets."""
    if len(parts) == 1:
        name = parts[0]
        fname = name if "." in name else f"{name}.json"
        override = {"book.json": "NORA_BOOK_PATH", "presets.json": "NORA_PRESETS_PATH"}.get(fname)
        if override and os.environ.get(override):
            return os.environ[override]
        return alpha_dir(fname)
    return alpha_dir(*parts)


def alpha_user_dir() -> str:
    """alpha/user: alpha người dùng."""
    return alpha_dir("user")


def users_dir(*parts: str) -> str:
    """data/users: thư mục lưu thông tin người dùng."""
    return _under(data_home(), "users", *parts)


def alpha_education_samples() -> str:
    """alpha/education/samples.json."""
    return os.path.join(data_home(), "alpha", "education", "samples.json")


def alpha_run_dir(kind: str, run_id: Optional[str] = None) -> str:
    """Thư mục lượt chạy phễu/sổ: alpha/<kind>[/<id>]; kind ∈ {funnel, book}."""
    if kind not in ("funnel", "book"):
        raise ValueError(f"kind phải là funnel|book, nhận {kind!r}")
    return _under(data_home(), kind, *([run_id] if run_id else []))


def run_dir(kind: str, run_id: Optional[str] = None) -> str:
    """Kết quả lâu dài: <kind>[/<id>]; kind ∈ {backtest, wfa, carlo}."""
    if kind not in ("backtest", "wfa", "carlo"):
        raise ValueError(f"kind phải là backtest|wfa|carlo, nhận {kind!r}")
    return _under(data_home(), kind, *([run_id] if run_id else []))


LIVE_MODE_DIR = {"paper": "paper", "demo": "testnet", "live": "live"}   # chế độ bot -> thư mục con của data/live (chỉ 3 thư mục)


def default_engine(mode: str) -> str:
    """Engine mặc định của chế độ: paper = legacy (PaperBook event); demo/live = unified (Runner + OkxVenue)."""
    return "legacy" if mode == "paper" else "unified"


def live_state_key(venue: str, mode: str, book: str = "main", engine: Optional[str] = None) -> str:
    """Thư mục trạng thái của một bot, tương đối so với data/live (MỘT định nghĩa; live/live.py dùng lại qua live_dir):
    <paper|testnet|live>/<sàn>_<sổ>[_<engine> chỉ khi engine khác mặc định của chế độ]. Paper luôn chung một thư mục (unified = PaperBook event như nhau)."""
    eng = engine or default_engine(mode)
    suffix = f"_{eng}" if mode != "paper" and eng != default_engine(mode) else ""
    return f"{LIVE_MODE_DIR[mode]}/{venue}_{book}{suffix}"


def live_dir(venue: str, mode: str, book: str = "main", engine: Optional[str] = None) -> str:
    """Trạng thái bot: live/<paper|testnet|live>/<sàn>_<sổ>[_engine]; lâu dài, không phải cache. KHÔNG tạo thư mục (chỉ đường ghi của bot tạo)."""
    return _under(data_home(), "live", *live_state_key(venue, mode, book, engine).split("/"))


# ─── Cache ───────────────────────────────────────────────────────────────────
def cache_process_dir(job_id: Optional[str] = None) -> str:
    """Thư mục job đang chạy: cache/process[/<id>]."""
    return _under(data_home(), "process", *([job_id] if job_id else []))


_ROOT_GROUPS = {"runs": ("book", "funnel", "wfa", "backtest", "carlo", "process")}


def allowed_roots(kind: str) -> List[str]:
    """realpath của gốc cho `kind`. Dùng làm gốc chặn path traversal:
    os.path.realpath(path) phải nằm trong một gốc (xem is_within). kind: một trong alpha|funnel|book|backtest|wfa|carlo|live|process|mem|shared|
    hoặc nhóm 'runs' (book+funnel+wfa+backtest+carlo+process)."""
    home = data_home()
    kinds = _ROOT_GROUPS.get(kind) or (kind,)
    out: List[str] = []
    for k in kinds:
        try:
            real = os.path.realpath(_kind_path(home, k))
        except KeyError:
            raise ValueError(f"allowed_roots: kind không rõ {kind!r}") from None
        if real not in out:
            out.append(real)
    return out


def is_within(path: str, kind: str) -> bool:
    """True nếu realpath(path) nằm trong (hoặc bằng) một gốc của allowed_roots(kind)."""
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r.rstrip(os.sep) + os.sep) for r in allowed_roots(kind))


def cache_dir(data_root: Optional[str] = None, *parts: str) -> str:
    """Cache tính toán / kho lượt chạy theo tên thư mục (xem LEGACY_CACHE_NAMES):
    api_jobs -> cache/process; book -> alpha/book; funnel -> alpha/funnel; book_wfa -> wfa; live -> live;
    runs -> cache/process/_mem; tên khác và không tên -> cache/process[/<tên>] (không sinh thư mục cache cấp 1 khác).
    `data_root` tường minh được coi là home (vd. root test). Tạo thư mục (makedirs)."""
    home = data_root or data_home()
    kind = LEGACY_CACHE_NAMES.get(parts[0]) if parts else None
    if kind:
        path = _under(home, kind, *parts[1:])
    else:
        path = _under(home, "process", *parts)
    os.makedirs(path, exist_ok=True)
    return path


# ─── IO & Bộ đệm ─────────────────────────────────────────────────────────────
def json_default(o):
    # Lưu ý: np.float64 là lớp con của float nên json xử lý trực tiếp (NaN vẫn ra "NaN"); default chỉ gọi cho kiểu json không biết.
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)) or hasattr(o, "isoformat"):  # gồm pd.Timestamp
        return o.isoformat()
    if isinstance(o, np.datetime64):
        return str(o)
    return str(o)


def pid_start_ticks(pid: Any) -> Optional[int]:
    """Thời điểm tiến trình bắt đầu (clock ticks từ lúc boot, /proc/<pid>/stat trường 22); None nếu không đọc được. Dùng nhận biết PID bị tái sử dụng."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            return int(fh.read().rsplit(b")", 1)[1].split()[19])
    except (OSError, IndexError, ValueError, TypeError):
        return None


def pid_alive(pid: Any, start_ticks: Optional[int] = None) -> bool:
    """MỘT định nghĩa "tiến trình còn sống" (đọc /proc, zombie = chết). `start_ticks` (nếu biết) phải khớp thời điểm bắt đầu — PID bị tái sử dụng = chết."""
    if not pid:
        return False
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            parts = fh.read().rsplit(b")", 1)[1].split()
    except (OSError, IndexError, ValueError, TypeError):
        return False
    if parts[0] == b"Z":
        return False
    return start_ticks is None or int(parts[19]) == start_ticks


def read_json(path: str, default: Any = None) -> Any:
    """Nội dung JSON của file; `default` nếu file thiếu / không đọc được / không phải JSON hợp lệ (OSError, ValueError)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _clean(o: Any) -> Any:
    """Thay NaN/inf bằng None (JSON hợp lệ cho trình duyệt)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def write_json_atomic(path: str, obj: Any, *, indent: Optional[int] = None, clean: bool = False, allow_nan: bool = True) -> None:
    """MỘT bộ ghi JSON nguyên tử (json.dump default=json_default ra tên tạm cạnh đích rồi os.replace: người đọc không bao giờ thấy file dở;
    lỗi -> xoá file tạm rồi ném lại). `clean` thay NaN/inf bằng null trước khi ghi (JSON chuẩn cho trình duyệt; kèm allow_nan=False);
    `allow_nan` cho phép token NaN/Infinity; `indent` tuỳ chọn."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_clean(obj) if clean else obj, fh, ensure_ascii=False, indent=indent, allow_nan=allow_nan, default=json_default)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_job_result(result: Any) -> Optional[str]:
    job_dir = os.environ.get("NORA_JOB_DIR")
    if not job_dir or not os.path.isdir(job_dir):   # thư mục job đã bị API xoá (huỷ/xong): KHÔNG tạo lại làm thư mục mồ côi
        return None
    path = os.path.join(job_dir, "result.json")
    write_json_atomic(path, result)  # ghi nguyên tử: API không bao giờ đọc file dở
    return path


def options(defaults: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> SimpleNamespace:
    """Tham số của một job: `defaults` ghi đè bởi `params`. Khoá lạ -> ValueError (không âm thầm bỏ qua lỗi gõ tên)."""
    params = dict(params or {})
    unknown = sorted(set(params) - set(defaults))
    if unknown:
        raise ValueError(f"tham số lạ: {unknown}; có: {sorted(defaults)}")
    return SimpleNamespace(**{**defaults, **params})


def as_list(value) -> list:
    """Danh sách từ tham số job: None/"" -> [], "a,b" -> ["a", "b"], list/tuple -> list."""
    if not value:
        return []
    if isinstance(value, str):
        return [x for x in value.split(",") if x]
    return list(value)


def env_mb(name: str, default: float) -> float:
    """Đọc ngân sách MB từ biến môi trường; giá trị hỏng -> default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


class ByteLRU:
    def __init__(self, budget_mb: float):
        self.budget = int(max(0.0, float(budget_mb)) * 1024 * 1024)
        self.used = 0
        self._d: "OrderedDict[Hashable, tuple]" = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return None
            self._d.move_to_end(key)
            return item[0]

    def put(self, key: Hashable, value: Any, nbytes: int) -> None:
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self.used -= old[1]
            if nbytes > self.budget:
                return
            while self._d and self.used + nbytes > self.budget:
                _, (_, n) = self._d.popitem(last=False)
                self.used -= n
            self._d[key] = (value, nbytes)
            self.used += nbytes

    def evict(self, key: Hashable) -> None:
        with self._lock:
            item = self._d.pop(key, None)
            if item is not None:
                self.used -= item[1]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self.used = 0

    def used_mb(self) -> float:
        return self.used / (1024 * 1024)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)


def load_samples(path: Optional[str] = None) -> List[Dict[str, Any]]:
    with open(path or alpha_education_samples(), encoding="utf-8") as fh:
        return json.load(fh)


def load_report(report_dir):
    """(stage_a, report) từ thư mục lần chạy build_strategy_book."""
    with open(os.path.join(report_dir, "stage_a.json"), encoding="utf-8") as fh:
        stage_a = json.load(fh)
    with open(os.path.join(report_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    return stage_a, report
