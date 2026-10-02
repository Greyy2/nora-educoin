"""Dữ liệu giá + cột kernel dùng CHUNG giữa các tiến trình qua mmap (chỉ đọc), lưu THEO CỘT.

Vì sao: mỗi worker từng tự dựng `data` của 8 tài sản perp (~1,3 GB) trong _DATA_CACHE riêng; khi phễu sinh tham số theo schema (chu kỳ /
khung đổi theo alpha) mỗi nhóm tín hiệu cần bộ cột khác -> worker dựng lại liên tục, RAM vượt ngân sách. Ở đây nền (giá, funding) và
TỪNG cột kernel là một file; nhóm nào cũng dùng lại phần đã có, chỉ tính thêm cột còn thiếu. Trang file nằm trong page cache của kernel
nên N worker đọc chung không nhân bản RAM.

Bố cục <out_dir>/:
  base/<khoá nền>/{t,o,h,l,c,v,f_t,f_r}.npy + meta.json
  cols/<khoá cột>.npy

Khoá phải tái lập ĐÚNG dữ liệu mà engine tự dựng (bằng từng bit):
  khoá nền = sha1(tài sản, nguồn, cửa sổ, điểm bắt đầu nạp 1m (= start − warmup 1m theo refs 1m), perp, vân tay 1m.pkl + funding.pkl)
  khoá cột = sha1(khoá nền, "khung|cột[__lagN]", điểm bắt đầu nạp của KHUNG đó (= start − max warmup các cột cùng khung, như
             BacktestEngine.load_data), vân tay file của khung)
  -> cột chỉ báo đệ quy (EMA, RSI...) phụ thuộc điểm bắt đầu nạp, nên cùng tên cột nhưng khác điểm bắt đầu là hai file khác nhau.
Ghi nguyên tử (thư mục / file tạm + rename): người đọc không bao giờ thấy dữ liệu dở; hai tiến trình ghi cùng khoá thì một bản thắng.

Dùng:
  export() (tiến trình cha làm nóng trước pool: sổ, WFA, phễu) ghi nền + cột — các job sau dùng lại đúng bộ cột đó.
  PortfolioEngine._load_shared (worker, khi có shared_dir): đủ thì đọc mmap; thiếu nền thì tự ghi nền (một lần cho cả pool);
  cột thiếu thì tính NGAY TRONG RAM từ file khung (15m/1h/4h, nhỏ) căn theo lưới `t` của nền — KHÔNG ghi ra đĩa: với tham số
  sinh theo schema, điểm bắt đầu nạp khung đổi theo từng nhóm nên cột gần như không dùng lại (đo: ~5 MB/cột, 2354 file / 900 alpha).
"""
import hashlib
import json
import os
import shutil
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Set

import numpy as np

if TYPE_CHECKING:  # tránh import vòng (portfolio import module này)
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.backtest.portfolio import PortfolioEngine

FORMAT_VERSION = 3
BASE_ARRAYS = ("t", "o", "h", "l", "c", "v", "f_t", "f_r")   # v: khối lượng phút thật — để tính cột 1m từ nền
STATS = {"fills": 0, "cols_written": 0, "bases_written": 0, "cols_in_memory": 0}   # theo tiến trình (giám sát / test)


def _sha1(payload: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _stat(path: Optional[str]):
    try:
        st = os.stat(path) if path else None
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size] if st else None


def plan(eng: "BacktestEngine") -> Optional[Dict[str, Any]]:
    """Khoá nền + khoá từng cột cho đúng bộ dữ liệu `eng` sẽ dựng (refs, cửa sổ nạp từng khung như load_data). None nếu không có 1m.pkl."""
    from backend.core.backtest.engine import FRAME_MS
    from backend.core.data.loader import _file_fingerprint
    from backend.core.signals.evaluator import lag_key
    from backend.db.local_pkl import default_data_root, resolve_symbol_dir
    root = default_data_root()
    fp1 = _file_fingerprint(eng.symbol, "1m", root)
    if fp1 is None:
        return None
    refs = eng._refs_by_frame()
    perp = any(tr.market == "perp" for tr in eng.trackers)
    sym_dir = resolve_symbol_dir(eng.symbol)
    base = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "start": int(eng.start_ts), "end": int(eng.end_ts),
                  "load_1m": int(eng.start_ts - eng._warmup_ms("1m", refs.get("1m", set()))), "perp": perp, "fp_1m": list(fp1),
                  "fp_funding": _stat(os.path.join(sym_dir, "funding.pkl")) if (perp and sym_dir) else None})
    cols: Dict[str, str] = {}
    order = (["1m"] if "1m" in refs else []) + [f for f in refs if f != "1m"]   # cùng thứ tự với _build_matrix
    for frame in order:
        if frame != "1m" and frame not in FRAME_MS:
            continue                                    # engine không dựng cột cho khung lạ
        if frame == "1m":
            start, fp = None, None                      # cột 1m chỉ phụ thuộc dữ liệu 1m (đã ở khoá nền)
        else:
            buffer_ms = max(eng._warmup_ms(frame, refs[frame]), 5 * 86_400_000 if frame == "4h" else 0)
            start = int(eng.start_ts - buffer_ms)
            fp = _file_fingerprint(eng.symbol, frame, root)
            fp = list(fp) if fp is not None else None
        for col, lag in sorted(refs[frame]):
            cid = f"{frame}|{lag_key(col, lag)}"
            cols[cid] = _sha1({"base": base, "cid": cid, "start": start, "fp": fp})
    return {"base": base, "cols": cols}


def _base_dir(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "base", key)


def _col_path(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "cols", f"{key}.npy")


def paths(p: Dict[str, Any]) -> Set[str]:
    """Đường dẫn tương đối (trong out_dir) của mọi phần thuộc kế hoạch `p` — để dọn theo giai đoạn (remove)."""
    return {os.path.join("base", p["base"])} | {os.path.join("cols", f"{k}.npy") for k in p["cols"].values()}


def missing(out_dir: str, p: Dict[str, Any]) -> Dict[str, Any]:
    return {"base": not os.path.isfile(os.path.join(_base_dir(out_dir, p["base"]), "meta.json")),
            "cols": [cid for cid, k in p["cols"].items() if not os.path.isfile(_col_path(out_dir, k))]}


def _load_array(path: str) -> np.ndarray:
    try:
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
    except ValueError:  # mảng rỗng không mmap được
        return np.load(path, allow_pickle=False)
    return np.asarray(arr)  # ndarray thường (index từng phần tử nhanh hơn np.memmap), vẫn chia sẻ mmap, chỉ đọc


def load_base(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, np.ndarray]]:
    """Mảng nền {t,o,h,l,c,f_t,f_r} (mmap chỉ đọc); None nếu chưa có / hỏng."""
    bdir = _base_dir(out_dir, p["base"])
    try:
        with open(os.path.join(bdir, "meta.json"), encoding="utf-8") as fh:
            if json.load(fh).get("version") != FORMAT_VERSION:
                return None
        return {name: _load_array(os.path.join(bdir, f"{name}.npy")) for name in BASE_ARRAYS}
    except (OSError, ValueError):
        return None


def load_cols(out_dir: str, p: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """Các cột ĐÃ có trên đĩa của kế hoạch (mmap chỉ đọc); cột chưa có thì không có trong dict."""
    out = {}
    for cid, k in p["cols"].items():
        path = _col_path(out_dir, k)
        if os.path.isfile(path):
            try:
                out[cid] = _load_array(path)
            except (OSError, ValueError):
                pass
    return out


def assemble(base: Dict[str, np.ndarray], cols: Dict[str, np.ndarray], order) -> Dict[str, Any]:
    """Dict giống PortfolioEngine._build_symbol_data (cột theo thứ tự `order`)."""
    data: Dict[str, Any] = {k: base[k] for k in ("t", "o", "h", "l", "c")}
    data["cols"] = {cid: cols[cid] for cid in order}
    data["f_t"], data["f_r"] = base["f_t"], base["f_r"]
    return data


def load(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dict giống PortfolioEngine._build_symbol_data, mọi mảng là view mmap chỉ đọc; None nếu thiếu / hỏng bất kỳ phần nào."""
    base = load_base(out_dir, p)
    if base is None:
        return None
    cols = load_cols(out_dir, p)
    if len(cols) != len(p["cols"]):
        return None
    return assemble(base, cols, p["cols"])


def _save(path: str, arr: np.ndarray) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "wb") as fh:
        np.save(fh, np.ascontiguousarray(arr), allow_pickle=False)
    os.replace(tmp, path)


def fill(out_dir: str, pe: "PortfolioEngine", eng: "BacktestEngine", p: Dict[str, Any]) -> Dict[str, Any]:
    """Tính và ghi phần còn thiếu của kế hoạch `p` (nền nếu chưa có + đúng các cột thiếu), qua đúng đường dựng của engine."""
    need = missing(out_dir, p)
    if not need["base"] and not need["cols"]:
        return {"base": False, "cols": 0}
    data = pe._build_symbol_data(eng, only=set(need["cols"]), with_volume=need["base"])
    if need["base"]:
        final = _base_dir(out_dir, p["base"])
        os.makedirs(os.path.dirname(final), exist_ok=True)
        tmp = f"{final}.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for name in BASE_ARRAYS:
            with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
                np.save(fh, data[name], allow_pickle=False)
        with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": FORMAT_VERSION, "symbol": eng.symbol}, fh)
        try:
            os.rename(tmp, final)
        except OSError:                 # tiến trình khác đã ghi xong cùng khoá
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.isdir(final):
                raise
        STATS["bases_written"] += 1
    if need["cols"]:
        os.makedirs(os.path.join(out_dir, "cols"), exist_ok=True)
        for cid in need["cols"]:
            _save(_col_path(out_dir, p["cols"][cid]), data["cols"][cid])
        STATS["cols_written"] += len(need["cols"])
    STATS["fills"] += 1
    return {"base": need["base"], "cols": len(need["cols"])}


def export(pe: "PortfolioEngine", out_dir: str) -> Dict[str, Any]:
    """Làm nóng: điền nền + cột cho mọi tài sản của `pe`. Trả {"paths": tập đường dẫn tương đối, "written": [tài sản có ghi mới]}."""
    os.makedirs(out_dir, exist_ok=True)
    out: Dict[str, Any] = {"paths": set(), "written": []}
    for sym in pe.symbols:
        eng, _ = pe._make_trackers(sym, pe.ledger)
        p = plan(eng)
        if p is None:
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (thiếu 1m.pkl)")
        r = fill(out_dir, pe, eng, p)
        if r["base"] or r["cols"]:
            out["written"].append(sym)
        out["paths"] |= paths(p)
    return out


def remove(out_dir: str, rel_paths: Iterable[str]) -> None:
    """Xoá các phần (thư mục nền / file cột) theo đường dẫn tương đối — dọn sau một giai đoạn."""
    for rel in rel_paths:
        path = os.path.join(out_dir, rel)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def size_mb(out_dir: str, rel_paths: Optional[Iterable[str]] = None) -> float:
    """Dung lượng (MB) của các phần chỉ định, hoặc cả out_dir."""
    targets = [os.path.join(out_dir, r) for r in rel_paths] if rel_paths is not None else [out_dir]
    total = 0
    for t in targets:
        if os.path.isfile(t):
            total += os.path.getsize(t)
            continue
        for base, _, files in os.walk(t):
            total += sum(os.path.getsize(os.path.join(base, f)) for f in files)
    return total / 1048576
