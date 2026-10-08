"""Dữ liệu giá + chỉ báo dùng CHUNG giữa các tiến trình qua mmap (chỉ đọc) — kho tính sẵn kiểu "ma trận chỉ báo" (học từ sova/prepare.py).

Chỉ báo tính từ gốc cố định (đầu lịch sử, BacktestEngine.frame_values) nên giá trị của một cột trên nến khung chỉ phụ thuộc
(tài sản, khung, cột, file dữ liệu, mốc cuối) — KHÔNG phụ thuộc cửa sổ hay các cột khác. Vì vậy mỗi cột của mỗi khung tính đúng MỘT lần
cho cả lần chạy (mọi nhóm alpha dùng lại), ở dạng nến khung (nhỏ: 15m ~100k nến), rồi mỗi worker căn về phút bằng chỉ số dùng chung.

Bố cục <out_dir>/:
  base/<khoá nền>/{t,o,h,l,c,f_t,f_r}.npy + meta.json   nến khung chạy (thật) + funding của cửa sổ (theo engine.load_data)
  ft/<khoá khung>.npy                                     open_time các nến của khung (khung 1m: các phút có giao dịch)
  fv/<khoá cột>.npy                                       giá trị cột trên các nến đó
  ix/<khoá căn>.npy                                       chỉ số nến khung dùng ở từng phút của nền (-1 = chưa có)
Khoá:
  nền  = sha1(tài sản, nguồn, cửa sổ, khung chạy, điểm bắt đầu nạp, perp, vân tay file khung chạy + funding.pkl)
  khung = sha1(tài sản, nguồn, khung, vân tay file khung, mốc cuối)       cột = sha1(khung, cột)       căn = sha1(nền, khung)
Ghi nguyên tử (file / thư mục tạm + rename): người đọc không bao giờ thấy dữ liệu dở; hai tiến trình ghi cùng khoá thì một bản thắng.

Dùng:
  export()  — tiến trình cha làm nóng trước khi chạy pool (sổ, WFA, phễu).
  PortfolioEngine._load_shared — worker: đủ thì đọc; thiếu thì fill() đúng phần thiếu (nền / cột / chỉ số căn) rồi đọc lại.
Kết quả bằng từng bit với PortfolioEngine._build_symbol_data (test/test_shared_data.py).
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

FORMAT_VERSION = 6   # 6: nền có thể kèm đường giá 1m trong nến chạy (MINUTE_ARRAYS) cho khớp "extreme" ở khung chạy > 1m
BASE_ARRAYS = ("t", "o", "h", "l", "c", "f_t", "f_r")
MINUTE_ARRAYS = ("m_a", "m_b", "m_l", "m_h")
STATS = {"fills": 0, "bases_written": 0, "cols_written": 0, "frames_written": 0, "index_written": 0}   # theo tiến trình (giám sát / test)


def _sha1(payload: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _stat(path: Optional[str]):
    try:
        st = os.stat(path) if path else None
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size] if st else None


def plan(eng: "BacktestEngine") -> Optional[Dict[str, Any]]:
    """Khoá nền + khoá từng khung / cột / chỉ số căn cho đúng bộ dữ liệu `eng` sẽ dựng. None nếu không có 1m.pkl."""
    from backend.core.backtest.engine import FRAME_MS, needs_minute_path
    from backend.core.data.loader import _file_fingerprint
    from backend.core.signals.evaluator import lag_key
    from backend.db.data_layout import default_data_root
    from backend.db.local_pkl import resolve_symbol_dir
    root = default_data_root()
    base_fr = eng.base_frame
    fp1 = _file_fingerprint(eng.symbol, base_fr, root)
    if fp1 is None:
        return None
    refs = eng._refs_by_frame()
    if any(col.startswith("py_") for rs in refs.values() for col, _ in rs):
        return None   # cột chương trình Python (P7) tính trong tiến trình, KHÔNG ghi vào kho dùng chung
    perp = any(tr.market == "perp" for tr in eng.slots)
    sym_dir = resolve_symbol_dir(eng.symbol)
    base = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "start": int(eng.start_ts), "end": int(eng.end_ts),
                  "base_frame": base_fr, "load_base": int(eng.start_ts - eng._warmup_ms(base_fr, refs.get(base_fr, set()))),
                  "perp": perp, "fp_base": list(fp1), "minute": needs_minute_path(eng),
                  "fp_1m": list(_file_fingerprint(eng.symbol, "1m", root) or []) if needs_minute_path(eng) else None,
                  "fp_funding": _stat(os.path.join(sym_dir, "funding.pkl")) if (perp and sym_dir) else None})
    frames: Dict[str, Dict[str, str]] = {}
    cols: Dict[str, Dict[str, str]] = {}
    for frame in ([base_fr] if base_fr in refs else []) + [f for f in refs if f != base_fr]:   # cùng thứ tự với _build_matrix
        if frame not in FRAME_MS:
            continue
        fp = _file_fingerprint(eng.symbol, frame, root)
        tkey = _sha1({"v": FORMAT_VERSION, "sym": eng.symbol, "root": root, "frame": frame, "fp": list(fp) if fp else None,
                      "end": int(eng.end_ts)})
        frames[frame] = {"t": tkey, "ix": _sha1({"base": base, "frame": tkey, "base_frame": base_fr})}
        for col, lag in sorted(refs[frame]):
            cid = f"{frame}|{lag_key(col, lag)}"
            cols[cid] = {"frame": frame, "v": _sha1({"frame": tkey, "cid": cid})}
    return {"base": base, "frames": frames, "cols": cols, "minute": needs_minute_path(eng)}


def _base_dir(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "base", key)


def _file(out_dir: str, kind: str, key: str) -> str:
    return os.path.join(out_dir, kind, f"{key}.npy")


def paths(p: Dict[str, Any]) -> Set[str]:
    """Đường dẫn tương đối (trong out_dir) của mọi phần thuộc kế hoạch `p` — để dọn theo giai đoạn (remove)."""
    out = {os.path.join("base", p["base"])}
    for f in p["frames"].values():
        out |= {os.path.join("ft", f"{f['t']}.npy"), os.path.join("ix", f"{f['ix']}.npy")}
    return out | {os.path.join("fv", f"{c['v']}.npy") for c in p["cols"].values()}


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
        names = BASE_ARRAYS + (MINUTE_ARRAYS if p.get("minute") else ())
        return {name: _load_array(os.path.join(bdir, f"{name}.npy")) for name in names}
    except (OSError, ValueError):
        return None


def load(out_dir: str, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dict giống PortfolioEngine._build_symbol_data: nền là view mmap chỉ đọc, cột = giá trị khung (mmap) căn theo chỉ số dùng chung.
    None nếu thiếu / hỏng bất kỳ phần nào."""
    from backend.core.backtest.engine import BacktestEngine
    base = load_base(out_dir, p)
    if base is None:
        return None
    try:
        idx = {fr: _load_array(_file(out_dir, "ix", f["ix"])) for fr, f in p["frames"].items()}
        cols = {cid: BacktestEngine.gather(_load_array(_file(out_dir, "fv", c["v"])), idx[c["frame"]]) for cid, c in p["cols"].items()}
    except (OSError, ValueError):
        return None
    data: Dict[str, Any] = {k: base[k] for k in ("t", "o", "h", "l", "c")}
    data["cols"] = cols
    data["f_t"], data["f_r"] = base["f_t"], base["f_r"]
    if p.get("minute"):
        data["minute"] = {k: base[k] for k in MINUTE_ARRAYS}
    return data


def _save(path: str, arr: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "wb") as fh:
        np.save(fh, np.ascontiguousarray(arr), allow_pickle=False)
    os.replace(tmp, path)


def _write_base(out_dir: str, key: str, symbol: str, data: Dict[str, Any]) -> None:
    final = _base_dir(out_dir, key)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    tmp = f"{final}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for name in BASE_ARRAYS:
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, data[name], allow_pickle=False)
    for name, arr in (data.get("minute") or {}).items():
        with open(os.path.join(tmp, f"{name}.npy"), "wb") as fh:
            np.save(fh, arr, allow_pickle=False)
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": FORMAT_VERSION, "symbol": symbol}, fh)
    try:
        os.rename(tmp, final)
    except OSError:                 # tiến trình khác đã ghi xong cùng khoá
        shutil.rmtree(tmp, ignore_errors=True)
        if not os.path.isdir(final):
            raise


def fill(out_dir: str, pe: "PortfolioEngine", eng: "BacktestEngine", p: Dict[str, Any]) -> Dict[str, int]:
    """Tính và ghi phần còn thiếu của kế hoạch `p`: nền, giá trị cột theo khung, chỉ số căn — qua đúng hàm của engine."""
    from backend.core.signals.evaluator import lag_key
    wrote = {"base": 0, "cols": 0, "frames": 0, "index": 0}
    if load_base(out_dir, p) is None:
        _write_base(out_dir, p["base"], eng.symbol, pe._build_symbol_data(eng, only=set()))
        wrote["base"] = 1
    base_t = load_base(out_dir, p)["t"]
    refs = eng._refs_by_frame()
    loaded = False
    for frame, f in p["frames"].items():
        miss_cols = {cid for cid, c in p["cols"].items() if c["frame"] == frame and not os.path.isfile(_file(out_dir, "fv", c["v"]))}
        t_path, ix_path = _file(out_dir, "ft", f["t"]), _file(out_dir, "ix", f["ix"])
        if not miss_cols and os.path.isfile(t_path) and os.path.isfile(ix_path):
            continue
        if frame != eng.base_frame and not loaded:
            eng.load_frames(refs)               # khung lớn từ đầu lịch sử (gốc cố định)
            loaded = True
        sub = {(col, lag) for col, lag in refs[frame] if f"{frame}|{lag_key(col, lag)}" in miss_cols}
        if sub or not os.path.isfile(t_path):
            t_frame, vals = eng.frame_values(frame, sub or {sorted(refs[frame])[0]})
            for cid in miss_cols:
                _save(_file(out_dir, "fv", p["cols"][cid]["v"]), vals[cid])
            wrote["cols"] += len(miss_cols)
            if not os.path.isfile(t_path):
                _save(t_path, t_frame)
                wrote["frames"] += 1
        if not os.path.isfile(ix_path):
            _save(ix_path, eng.align_index(frame, _load_array(t_path), base_t, eng.base_frame))
            wrote["index"] += 1
    STATS["fills"] += 1
    for k, n in wrote.items():
        STATS[{"base": "bases_written", "cols": "cols_written", "frames": "frames_written", "index": "index_written"}[k]] += n
    return wrote


def export(pe: "PortfolioEngine", out_dir: str) -> Dict[str, Any]:
    """Làm nóng: điền nền + cột + chỉ số cho mọi tài sản của `pe`. Trả {"paths": tập đường dẫn tương đối, "written": [tài sản có ghi mới]}."""
    os.makedirs(out_dir, exist_ok=True)
    out: Dict[str, Any] = {"paths": set(), "written": []}
    for sym in pe.symbols:
        eng, _ = pe._make_slots(sym, pe.ledger)
        p = plan(eng)
        if p is None:
            raise RuntimeError(f"{sym}: không tạo được khoá dữ liệu dùng chung (thiếu 1m.pkl)")
        if any(fill(out_dir, pe, eng, p).values()):
            out["written"].append(sym)
        out["paths"] |= paths(p)
    return out


def remove(out_dir: str, rel_paths: Iterable[str]) -> None:
    """Xoá các phần (thư mục nền / file) theo đường dẫn tương đối — dọn sau một giai đoạn."""
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
