"""Cache kết quả THẬT cho mẫu giáo dục (/alpha/education): mỗi mẫu = một lần chạy Nautilus giống hệt backtest tuỳ chỉnh của Studio.

Không có số liệu dựng sẵn: chưa có file cache cho khoá hiện tại -> `get` trả None -> API trả 404 NOT_READY. Khoá đổi khi mã, thiết lập chạy, phiên bản Nautilus
hoặc dữ liệu catalog đổi. Job `education_warm` (tasks.education_warm) là nơi DUY NHẤT ghi cache (`put`)."""
import functools
import hashlib
import json
import os
import re
from typing import Any, Dict, Optional

_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_SPEC_FIELDS = ("symbols", "start", "end", "train_ratio", "initial_capital", "run_frame")


def _dir() -> str:
    from backend.models.storage import alpha_dir
    return alpha_dir("education", "results")


@functools.lru_cache(maxsize=256)
def _program_info(code: str) -> tuple:
    """(program_hash, timeframe) của mã — hash do compile_code tính; DslError nếu mã không biên dịch."""
    from backend.alpha.compile import compile_code
    prog = compile_code(code)
    h = getattr(prog, "code_hash", None) or hashlib.sha256(code.encode("utf-8")).hexdigest()
    return h, getattr(prog, "timeframe", None)


def cache_key(code: str, run_spec: dict) -> str:
    """sha256 của {program_hash, run_spec, phiên bản Nautilus, dấu vân tay catalog, base_frame}."""
    from backend.nautilus.version import NAUTILUS_VERSION
    phash, tf = _program_info(code)
    base_frame = run_spec.get("run_frame") or tf or "1h"
    try:
        from backend.data.data import resolve_symbols
        from backend.data.data import catalog_digest
        digest = catalog_digest(resolve_symbols(run_spec.get("symbols")))
    except Exception:   # noqa: BLE001 — chưa có catalog/dữ liệu: khoá vẫn xác định, chạy sẽ báo lỗi dữ liệu rõ ràng
        digest = ""
    payload = {"program_hash": phash, "run_spec": run_spec, "nautilus": NAUTILUS_VERSION, "catalog": digest, "base_frame": base_frame}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _path(key: str) -> str:
    if not _KEY_RE.match(key):
        raise ValueError("khoá cache không hợp lệ")
    return os.path.join(_dir(), f"{key}.json")


def get(key: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_path(key), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return None


def put(key: str, result: Dict[str, Any]) -> None:
    from backend.models.storage import write_json_atomic
    os.makedirs(_dir(), exist_ok=True)
    write_json_atomic(_path(key), result)


def sample_run_spec(sample: dict, defaults: Optional[dict] = None) -> dict:
    """Thiết lập chạy của mẫu = mặc định của Studio (data.run_defaults, chế độ 'Nhanh': run_frame rỗng = khung tín hiệu) + trường riêng của mẫu."""
    if defaults is None:
        from backend.data.data import run_defaults
        defaults = run_defaults()
    spec = dict(defaults)
    for f in SAMPLE_SPEC_FIELDS:
        if sample.get(f) not in (None, ""):
            spec[f] = sample[f]
    if sample.get("timeframe"):
        spec["run_frame"] = sample["timeframe"]
    spec.setdefault("run_frame", "")
    return spec


def lookup(sample: dict, spec: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Kết quả thật đã cache cho mẫu (khoá hiện hành) hoặc None (chưa chạy / mã không biên dịch / thiếu dữ liệu)."""
    try:
        spec = spec if spec is not None else sample_run_spec(sample)
        return get(cache_key(sample.get("code", ""), spec))
    except Exception:   # noqa: BLE001 — không tính được khoá = chưa có kết quả thật
        return None
