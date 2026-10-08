#!/usr/bin/env python
"""Chuyển metadata tài sản từ manifest.json / dex_pool.json vào attrs của chính file dữ liệu (pkl / parquet).

    ~/.venvs/nora/bin/python test/scripts/migrate_pkl_meta.py --root data/binance            # dry-run (mặc định): đo + kiểm chứng, KHÔNG ghi
    ~/.venvs/nora/bin/python test/scripts/migrate_pkl_meta.py --root data/binance --apply    # ghi thật

Với MỖI thư mục tài sản (cex/<SYM>, cex/<SYM>/perp, dex/<SYM>, phẳng):
  * attrs["nora"] của mọi <khung>.pkl = manifest (bỏ rows/coverage_*/ticks/funding là phần suy ra) + start_ts/end_ts/rows_1m/filled_ratio_1m TÍNH LẠI từ khung 1m
    (manifest cũ của OKX có thể lỗi thời) + digest_1m (mới). sha256_1m giữ NGUYÊN giá trị manifest (định danh dữ liệu của job_key) sau khi kiểm sha CSV của khung == giá trị đó.
  * ticks.parquet: attrs["nora"] = {"ticks": manifest["ticks"], "onchain": dex_pool.json["onchain"]}. Không có parquet mà có onchain -> onchain vào attrs nến.
  * funding.pkl: attrs["nora"] = {"funding": manifest["funding"]}.
  * Ghi nguyên tử (tên tạm + os.replace, 24h.pkl cuối); đọc lại và so TỪNG CỘT (np.array_equal) với bản trước khi ghi.
  * manifest.json / dex_pool.json được CHUYỂN (không xoá) sang <archive>/<tên gốc>/<đường dẫn tương đối>/.
Idempotent: tài sản đã có attrs đủ và không còn json thì bỏ qua. Mặc định archive = <nora>/data/_migration/<stamp>
(KHÔNG tạo data/cache/: sự tồn tại của nó đổi các helper đường dẫn cache sang cây mới — việc của phiên data-layout).
"""
import argparse
import json
import os
import shutil
import sys
import time

import numpy as np
import pandas as pd

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)

from backend.crawl import store  # noqa: E402

LEGACY_FILES = ("manifest.json", "dex_pool.json")
DERIVED = ("ticks", "funding", "rows", "coverage_days", "coverage_ratio", "base_resolution")
FRAME_NAMES = ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "24h")


def same_frame(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """Hai khung bằng nhau từng bit: cột, dtype, độ dài, index và từng cột np.array_equal (NaN == NaN)."""
    if list(a.columns) != list(b.columns) or len(a) != len(b) or not a.index.equals(b.index):
        return False
    for c in a.columns:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype != y.dtype:
            return False
        if x.dtype.kind == "f":
            if not np.array_equal(x, y, equal_nan=True):
                return False
        elif not np.array_equal(x, y):
            return False
    return True


def frame_order(names):
    """24h cuối (khung đọc metadata); phần còn lại theo thứ tự ổn định."""
    return sorted(names, key=lambda n: (store.META_FRAMES.index(n) if n in store.META_FRAMES else len(store.META_FRAMES)), reverse=True)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def derive_meta(man: dict, onchain, df1: pd.DataFrame, problems: list, notes: list) -> dict:
    """attrs nến từ manifest cũ + số liệu tính lại từ khung 1m."""
    meta = {k: v for k, v in man.items() if k not in DERIVED}
    start, end = int(df1["open_time"].iloc[0]), int(df1["open_time"].iloc[-1])
    filled = round(float((df1["is_filled"] == 1).mean()), 4) if "is_filled" in df1.columns else 0.0
    for key, new in (("start_ts", start), ("end_ts", end), ("filled_ratio_1m", filled)):
        if man.get(key) is not None and man.get(key) != new:
            notes.append(f"{key}: manifest {man.get(key)} != khung {new} (dùng khung)")
        meta[key] = new
    rows_m = (man.get("rows") or {}).get("1m")
    if rows_m is not None and rows_m != len(df1):
        notes.append(f"rows_1m: manifest {rows_m} != khung {len(df1)} (dùng khung)")
    meta["rows_1m"] = len(df1)
    sha_man = man.get("sha256_1m")
    sha = store.compute_df_sha256(df1)
    if sha_man and sha != sha_man:
        problems.append(f"sha256 CSV của 1m ({sha[:12]}) != manifest ({sha_man[:12]}) — dữ liệu không khớp manifest, KHÔNG migrate")
    meta["sha256_1m"] = sha_man or sha
    meta["digest_1m"] = store.compute_df_digest(df1)
    if onchain:
        meta["onchain"] = onchain
    return meta


def migrate_dir(a_dir: str, rel: str, archive: str, apply: bool) -> dict:
    res = {"dir": rel, "status": "", "notes": [], "problems": []}
    legacy = {n: os.path.join(a_dir, n) for n in LEGACY_FILES if os.path.isfile(os.path.join(a_dir, n))}
    frames = [n for n in FRAME_NAMES if os.path.isfile(os.path.join(a_dir, f"{n}.pkl"))]
    if not frames:
        res["status"] = "skip: không có khung pkl"
        return res
    tick_path = os.path.join(a_dir, "ticks.parquet")
    fund_path = os.path.join(a_dir, "funding.pkl")
    attrs_ok = all(isinstance(pd.read_pickle(os.path.join(a_dir, f"{n}.pkl")).attrs.get(store.ATTR_KEY), dict) for n in ("24h" if "24h" in frames else frames[0],))

    if not legacy and attrs_ok:
        res["status"] = "ok (đã migrate)"
        return res
    if not legacy and not attrs_ok:
        res["status"] = "skip: không có manifest.json và không có attrs"
        return res

    man = read_json(legacy["manifest.json"]) if "manifest.json" in legacy else {}
    pool = read_json(legacy["dex_pool.json"]) if "dex_pool.json" in legacy else {}
    if attrs_ok:                                 # đã có attrs (vd. vừa gộp binance_hist): không dựng lại từ json cũ, chỉ cất json
        man, pool = None, {}
    original = {n: pd.read_pickle(os.path.join(a_dir, f"{n}.pkl")) for n in frames}
    plan = {}                                    # tên file -> (frame đã gán attrs)
    if man is not None:
        if "1m" not in original:
            res["problems"].append("thiếu 1m.pkl")
            res["status"] = "FAIL"
            return res
        meta = derive_meta(man, None if os.path.isfile(tick_path) else pool.get("onchain"), original["1m"], res["problems"], res["notes"])
        for n in frames:
            df = original[n].copy()
            plan[f"{n}.pkl"] = store.stamp_attrs(df, meta)
    # ticks.parquet
    tick_df = None
    tick_meta = None
    if os.path.isfile(tick_path):
        tick_df = pd.read_parquet(tick_path)
        have = store._read_parquet_attrs(tick_path)
        t_new = (man or {}).get("ticks")
        if t_new is not None or pool.get("onchain") is not None:
            tick_meta = {"ticks": t_new if t_new is not None else (have or {}).get("ticks"),
                         "onchain": pool.get("onchain") if pool.get("onchain") is not None else (have or {}).get("onchain")}
        elif not have:
            res["notes"].append("ticks.parquet không có khối ticks trong manifest (giữ nguyên)")
    elif man and man.get("ticks"):
        res["problems"].append("manifest có khối ticks nhưng không có ticks.parquet")
    # funding.pkl
    fund_df = None
    if os.path.isfile(fund_path) and man and man.get("funding") is not None:
        fund_df = pd.read_pickle(fund_path)
    if res["problems"]:
        res["status"] = "FAIL"
        return res

    if not apply:   # kiểm chứng đầy đủ trong bộ nhớ: pickle/parquet khứ hồi phải khớp từng bit và giữ attrs
        import io
        import pickle
        for fname, df in plan.items():
            back = pickle.loads(pickle.dumps(df))
            if not same_frame(back, original[fname[:-4]]) or back.attrs != df.attrs:
                res["problems"].append(f"{fname}: khứ hồi pickle không khớp")
        if tick_meta is not None:
            buf = io.BytesIO()
            t = tick_df.copy()
            t.attrs = {store.ATTR_KEY: store.plain(tick_meta)}
            t.to_parquet(buf, engine="pyarrow", compression="snappy", index=False)
            buf.seek(0)
            back = pd.read_parquet(buf)
            if not back.equals(tick_df) or back.attrs != t.attrs:
                res["problems"].append("ticks.parquet: khứ hồi không khớp")
        if res["problems"]:
            res["status"] = "FAIL"
            return res
        res["status"] = f"dry-run: sẽ ghi {len(plan)} khung" + (" + ticks" if tick_meta else "") + (" + funding" if fund_df is not None else "") + f", chuyển {sorted(legacy)}"
        return res

    # ── ghi nguyên tử + kiểm chứng từng cột ──
    for fname in [f"{n}.pkl" for n in frame_order(frames)]:
        if fname not in plan:
            continue
        path = os.path.join(a_dir, fname)
        store.write_pickle_atomic(plan[fname], path)
        back = pd.read_pickle(path)
        if not same_frame(back, original[fname[:-4]]) or back.attrs.get(store.ATTR_KEY) != store.plain(plan[fname].attrs[store.ATTR_KEY]):
            res["problems"].append(f"{fname}: đọc lại không khớp bản gốc")
    if tick_meta is not None:
        store.write_parquet_atomic(tick_df.copy(), tick_path, tick_meta)
        back = pd.read_parquet(tick_path)
        if not back.equals(tick_df) or store._read_parquet_attrs(tick_path) != store.plain(tick_meta):
            res["problems"].append("ticks.parquet: đọc lại không khớp")
    if fund_df is not None:
        orig_f = fund_df.copy()
        store.write_pickle_atomic(store.stamp_attrs(fund_df, {"funding": man["funding"]}), fund_path)
        if not same_frame(pd.read_pickle(fund_path), orig_f):
            res["problems"].append("funding.pkl: đọc lại không khớp")
    if res["problems"]:
        res["status"] = "FAIL (đã ghi, KHÔNG chuyển json — kiểm tra)"
        return res
    # asset_meta phải trả lại đúng metadata (không dựa vào json)
    am = store.asset_meta(a_dir)
    if am["dataset"] is None:
        res["problems"].append("asset_meta không đọc được attrs sau khi ghi")
        res["status"] = "FAIL"
        return res
    dst = os.path.join(archive, rel)
    os.makedirs(dst, exist_ok=True)
    for name, src in legacy.items():
        shutil.move(src, os.path.join(dst, name))
    res["status"] = "migrated"
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", required=True, help="gốc dữ liệu thị trường (vd. data/binance); nhắc lại được")
    ap.add_argument("--apply", action="store_true", help="ghi thật (mặc định dry-run)")
    ap.add_argument("--archive", help="thư mục cất manifest.json/dex_pool.json (mặc định <nora>/data/_migration/<stamp>)")
    ap.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M%S"))
    args = ap.parse_args()
    archive = os.path.abspath(args.archive or os.path.join(store.DATA_HOME, "_migration", args.stamp))
    bad = 0
    for root in args.root:
        root = os.path.abspath(root)
        print(f"== {root} ({'APPLY' if args.apply else 'dry-run'})")
        for item in store.list_assets(root):
            rel = os.path.join(os.path.basename(root), os.path.relpath(item["path"], root))
            t0 = time.time()
            res = migrate_dir(item["path"], rel, archive, args.apply)
            print(f"  {item['qualified']:14s} [{item['path'][len(root) + 1:]}] {res['status']} ({time.time() - t0:.1f}s)")
            for n in res["notes"]:
                print(f"      note: {n}")
            for p in res["problems"]:
                print(f"      PROBLEM: {p}")
            bad += bool(res["problems"])
    if args.apply:
        print(f"archive: {archive}")
    print("FAILED" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
