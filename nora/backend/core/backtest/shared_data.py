"""Dữ liệu giá + kernel theo (tài sản, cửa sổ, refs) dùng CHUNG giữa các tiến trình qua mmap (chỉ đọc).

Vì sao: mỗi worker của pool từng tự dựng `data` (t/o/h/l/c + cột kernel + funding, ~1,3 GB cho 8 tài sản perp) trong
_DATA_CACHE riêng. Ở đây tiến trình cha dựng MỘT lần cho mỗi giai đoạn (export), worker chỉ np.load(mmap_mode="r") —
trang file được page cache của kernel chia sẻ giữa các worker nên RAM mỗi worker giảm mạnh.

Cấu trúc: <out_dir>/<key>/{t,o,h,l,c,f_t,f_r}.npy + cols/<tên an toàn>.npy + meta.json (tên an toàn -> khoá `frame|col`).
Khoá = sha1(symbol, cửa sổ, refs, perp, nguồn dữ liệu, dấu vân tay (mtime_ns, size) của 1m.pkl + mọi khung được dùng +
funding.pkl) -> dữ liệu cũ không bao giờ khớp khi file nguồn đổi. Ghi nguyên tử (thư mục tạm + rename).
Kết quả load() bằng từng bit với dict do PortfolioEngine._build_symbol_data dựng (test/test_shared_data.py).
"""
import hashlib
import json
import os
import re
import shutil
from typing import TYPE_CHECKING, Any, Dict, Optional

import numpy as np

if TYPE_CHECKING:  # tránh import vòng (portfolio import module này)
    from backend.core.backtest.portfolio import PortfolioEngine

FORMAT_VERSION = 1
BASE_ARRAYS = ("t", "o", "h", "l", "c", "f_t", "f_r")


def _fingerprints(symbol: str, refs_signature) -> Dict[str, Any]:
    from backend.core.backtest.engine import FRAME_MS
    from backend.core.data.loader import _file_fingerprint
    from backend.db.local_pkl import default_data_root, resolve_symbol_dir
    root = default_data_root()
    frames = ["1m"] + sorted(({f for f, _ in refs_signature} | {"4h"}) - {"1m"})
    fps = {f: _file_fingerprint(symbol, f, root) for f in frames if f == "1m" or f in FRAME_MS}
    sym_dir = resolve_symbol_dir(symbol)
    funding = os.path.join(sym_dir, "funding.pkl") if sym_dir else None
    try:
        st = os.stat(funding) if funding else None
        fps["funding"] = (st.st_mtime_ns, st.st_size) if st else None
    except OSError:
        fps["funding"] = None
    return {"root": root, "fps": fps}


def data_key(symbol: str, start_ts: int, end_ts: int, refs_signature, perp: bool) -> Optional[str]:
    """sha1 hex ổn định của một bộ dữ liệu. None nếu không có dấu vân tay file 1m (Mongo/không tìm thấy) -> không chia sẻ."""
    if os.environ.get("NORA_DATA_SOURCE", "auto").strip().lower() == "mongo":
        return None
    info = _fingerprints(symbol, refs_signature)
    if info["fps"].get("1m") is None:
        return None
    payload = {"v": FORMAT_VERSION, "symbol": symbol, "start": int(start_ts), "end": int(end_ts),
               "refs": [[f, [[c, int(lag)] for c, lag in sorted(r)]] for f, r in refs_signature],
               "perp": bool(perp), "root": info["root"],
               "fps": {k: (list(v) if v is not None else None) for k, v in sorted(info["fps"].items())}}
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _safe_name(i: int, key: str) -> str:
    return f"{i:04d}_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", key)


def _dir_size(path: str) -> int:
    total = 0
    for base, _, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(base, fn))
            except OSError:
                pass
    return total


def export(engine: "PortfolioEngine", out_dir: str) -> Dict[str, Any]:
    """Dựng `data` của từng tài sản của engine (đúng đường _make_trackers + _build_symbol_data, không qua cache)
    rồi ghi vào out_dir/<key>/. Trả {"keys": {symbol: key}, "written": [symbol], "skipped": [symbol], "bytes": int}."""
    os.makedirs(out_dir, exist_ok=True)
    out = {"keys": {}, "written": [], "skipped": [], "bytes": 0}
    for sym in engine.symbols:
        eng, _ = engine._make_trackers(sym, engine.ledger)
        key = engine._shared_key(sym, eng)
        if key is None:
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (thiếu 1m.pkl hoặc nguồn Mongo)")
        out["keys"][sym] = key
        final = os.path.join(out_dir, key)
        if os.path.isdir(final):
            out["skipped"].append(sym)
            out["bytes"] += _dir_size(final)
            continue
        data = engine._build_symbol_data(eng)
        tmp = os.path.join(out_dir, f".tmp-{key}-{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "cols"))
        meta = {"version": FORMAT_VERSION, "symbol": sym, "arrays": {}, "cols": []}
        for name in BASE_ARRAYS:
            np.save(os.path.join(tmp, f"{name}.npy"), data[name], allow_pickle=False)
            meta["arrays"][name] = str(data[name].dtype)
        for i, (k, arr) in enumerate(data["cols"].items()):
            safe = _safe_name(i, k)
            np.save(os.path.join(tmp, "cols", f"{safe}.npy"), arr, allow_pickle=False)
            meta["cols"].append({"file": safe, "key": k, "dtype": str(arr.dtype)})
        with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
        del data
        try:
            os.rename(tmp, final)  # nguyên tử; người đọc không bao giờ thấy thư mục dở dang
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)  # tiến trình khác đã ghi xong cùng khoá
            if not os.path.isdir(final):
                raise
        out["written"].append(sym)
        out["bytes"] += _dir_size(final)
    return out


def _load_array(path: str) -> np.ndarray:
    try:
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
    except ValueError:  # mảng rỗng không mmap được
        return np.load(path, allow_pickle=False)
    return np.asarray(arr)  # ndarray thường (không phải np.memmap: index từng phần tử nhanh hơn), vẫn chia sẻ mmap, chỉ đọc


def load(out_dir: str, key: str) -> Optional[Dict[str, Any]]:
    """Dict giống `data` của _build_symbol_data nhưng mọi mảng là view mmap chỉ đọc; None nếu chưa có / hỏng."""
    base = os.path.join(out_dir, key)
    try:
        with open(os.path.join(base, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        if meta.get("version") != FORMAT_VERSION:
            return None
        arrays = {name: _load_array(os.path.join(base, f"{name}.npy")) for name in BASE_ARRAYS}
        cols = {c["key"]: _load_array(os.path.join(base, "cols", f"{c['file']}.npy")) for c in meta["cols"]}
        data: Dict[str, Any] = {k: arrays[k] for k in ("t", "o", "h", "l", "c")}
        data["cols"] = cols
        data["f_t"], data["f_r"] = arrays["f_t"], arrays["f_r"]
    except (OSError, ValueError, KeyError):
        return None
    return data
