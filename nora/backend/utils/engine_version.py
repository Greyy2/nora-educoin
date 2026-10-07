"""Phiên bản ENGINE (một nguồn duy nhất) cho sổ chiến lược: sổ nào dựng bằng engine khác engine hiện hành thì kết quả (lãi/MDD/bằng chứng) trong sổ
có thể không còn tái lập được -> giao diện cảnh báo "cần dựng lại".

engine_version() = {"hash": sha256 của MÃ NGUỒN engine, "commit": git HEAD ngắn, "dirty": có thay đổi chưa commit trong mã engine, "files": số file}.
Mã engine = mọi *.py trong backend/core/backtest và backend/core/execute (theo tên file + nội dung, xếp theo tên), TRỪ các module sản phẩm không ảnh hưởng
kết quả sổ (ENGINE_EXCLUDE: custom_run — backtest tạm của người dùng, edu_precompute — dựng mẫu Education). So sánh chỉ dùng `hash`; `commit` để người đọc
biết sổ dựng ở đâu. Cùng hàm cho mọi nơi ghi (optimize/registry.build_book: sổ chính + sổ explore + xuất bản phễu) và đọc (API).
Kết quả được nhớ theo (đường dẫn, mtime_ns, size) của các file -> gọi mỗi request không đọc lại file.
"""
import hashlib
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE_DIRS = ("backend/core/backtest", "backend/core/execute")
ENGINE_EXCLUDE = frozenset({"custom_run.py", "edu_precompute.py"})
REASON_NO_VERSION = "sổ dựng trước khi có phiên bản engine"

GIT_TTL_S = 60.0   # commit / dirty đổi mà không đổi file (git commit) -> làm tươi sau tối đa ngần này giây; hash không phụ thuộc git
_cache: Dict[str, Any] = {"sig": None, "value": None, "at": 0.0}


def _engine_files() -> List[Tuple[str, str]]:
    out = []
    for d in ENGINE_DIRS:
        base = os.path.join(NORA_DIR, d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.endswith(".py") and name not in ENGINE_EXCLUDE:
                out.append((f"{d}/{name}", os.path.join(base, name)))
    return out


def _git(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", NORA_DIR, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:   # noqa: BLE001  (git thiếu / bị monkeypatch trong test / không phải repo: commit chỉ để tham khảo, hash mới là so sánh)
        return None


def engine_version() -> Dict[str, Any]:
    files = _engine_files()
    sig = tuple((rel, os.stat(p).st_mtime_ns, os.stat(p).st_size) for rel, p in files)
    if _cache["sig"] == sig and time.time() - _cache["at"] < GIT_TTL_S:
        return dict(_cache["value"])
    h = hashlib.sha256()
    for rel, p in files:
        with open(p, "rb") as fh:
            h.update(rel.encode("utf-8") + b"\0" + fh.read() + b"\0")
    status = _git("status", "--porcelain", "--", *ENGINE_DIRS)
    value = {"hash": h.hexdigest(), "commit": _git("rev-parse", "--short", "HEAD"), "dirty": (bool(status) if status is not None else None),
             "files": len(files)}
    _cache.update(sig=sig, value=value, at=time.time())
    return dict(value)


def book_engine_status(book: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"stored": engine_version lúc dựng | None, "current", "needs_rebuild", "reason"}. Sổ chưa có engine_version -> needs_rebuild True + REASON_NO_VERSION.
    book=None (chưa có sổ) -> needs_rebuild None (không có gì để dựng lại)."""
    cur = engine_version()
    if book is None:
        return {"stored": None, "current": cur, "needs_rebuild": None, "reason": "chưa có sổ"}
    stored = book.get("engine_version")
    if not isinstance(stored, dict) or not stored.get("hash"):
        return {"stored": None, "current": cur, "needs_rebuild": True, "reason": REASON_NO_VERSION}
    if stored["hash"] != cur["hash"]:
        return {"stored": stored, "current": cur, "needs_rebuild": True,
                "reason": (f"engine (core/backtest, core/execute) đã đổi từ khi dựng sổ: dựng ở commit {stored.get('commit') or '?'} "
                           f"(hash {stored['hash'][:8]}), hiện là commit {cur.get('commit') or '?'} (hash {cur['hash'][:8]})")}
    return {"stored": stored, "current": cur, "needs_rebuild": False, "reason": None}
