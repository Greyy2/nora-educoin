#!/usr/bin/env python
"""Gộp data/binance_hist/cex (spot 1m 2019-10 .. 2025-01) vào data/market/binance/cex (spot 2023-09-30 .. nay) thành MỘT chuỗi liên tục mỗi mã.

    ~/.venvs/nora/bin/python test/scripts/merge_binance_hist.py [--apply] [--hist data/binance_hist] [--dst data/binance]

Luật: giữ NGUYÊN nến hiện có của binance/cex; chỉ lấy 1m của hist TRƯỚC nến 1m đầu tiên của binance/cex (không chồng); sinh lại MỌI khung (5m..24h) từ 1m gộp
bằng bộ resample hiện có (save_resampled_dataset: một nguồn 1m); gắn attrs + sha256_1m (sha CSV) + digest_1m. Mã chỉ có ở hist (BCH, LINK, TRX) thành thư mục mới.
Chỉ spot (cex/<SYM>); perp (cex/<SYM>/perp) không đụng tới. Kiểm chứng: phần 1m trùng binance/cex cũ bằng từng bit; khung lớn cũ == khung mới từ ngày thứ 2 trở đi.
Mặc định dry-run. KHÔNG xoá binance_hist. Sao lưu trước (cp -a) là việc của người chạy --apply.
"""
import argparse
import os
import sys
import time

import pandas as pd

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)
from backend.core.models import DATA_DIR  # noqa: E402
from backend.crawl import store  # noqa: E402
from migrate_pkl_meta import same_frame  # noqa: E402

COLS = ["open_time", "open", "high", "low", "close", "volume", "is_filled"]


def merge_symbol(sym: str, hist_cex: str, dst_cex: str, apply: bool, archive: str) -> dict:
    hdir, ddir = os.path.join(hist_cex, sym), os.path.join(dst_cex, sym)
    hist = pd.read_pickle(os.path.join(hdir, "1m.pkl"))
    hman = store.manifest_of_dir(hdir) or {}
    cur_path = os.path.join(ddir, "1m.pkl")
    cur = pd.read_pickle(cur_path) if os.path.isfile(cur_path) else None
    cman = (store.manifest_of_dir(ddir) or {}) if cur is not None else {}
    out = {"symbol": sym, "hist_rows": len(hist), "cur_rows": 0 if cur is None else len(cur)}
    if cur is not None:
        first = int(cur["open_time"].iloc[0])
        pre = hist[hist["open_time"] < first]
        # nến trùng phải giống nhau (báo cáo): dữ liệu cũ thắng
        ov = hist[hist["open_time"] >= first].merge(cur, on="open_time", suffixes=("_h", "_c"))
        out["overlap_rows"] = len(ov)
        out["overlap_close_equal"] = bool((ov["close_h"] == ov["close_c"]).all()) if len(ov) else None
        raw = pd.concat([pre[COLS], cur[COLS]], ignore_index=True)
    else:
        first, pre, raw = None, hist, hist[COLS]
    out["pre_rows"] = len(pre)
    merged, ratio = store._fill_missing_1m_candles_with_ratio(raw)
    out["merged_rows"] = len(merged)
    out["start"] = pd.Timestamp(int(merged["open_time"].iloc[0]), unit="ms").isoformat()
    out["end"] = pd.Timestamp(int(merged["open_time"].iloc[-1]), unit="ms").isoformat()
    out["filled_ratio"] = round(ratio, 5)
    if cur is not None:   # phần hiện có phải còn nguyên từng bit
        keep = merged[merged["open_time"] >= first].reset_index(drop=True)
        out["cur_part_identical"] = same_frame(keep[cur.columns.tolist()], cur.reset_index(drop=True))
    if not apply:
        return out
    base_meta = {k: cman.get(k, hman.get(k)) for k in ("venue", "exchange", "market", "base_symbol", "market_symbol", "volume_unit")}
    issues = list(cman.get("crawl_issues") or []) + [f"hist: {x}" for x in (hman.get("crawl_issues") or [])]
    extra = {**base_meta, "checksums_verified": bool(cman.get("checksums_verified", True)) and bool(hman.get("checksums_verified", True)),
             "crawl_issues": issues,
             "source_files": {"current": cman.get("source_files"), "hist": hman.get("source_files"),
                              "hist_merge": {"hist_rows_used": len(pre), "before_ts": first, "merged_at": int(time.time())}}}
    start, end = int(merged["open_time"].iloc[0]), int(merged["open_time"].iloc[-1])
    old_frames = {f: pd.read_pickle(os.path.join(ddir, f"{f}.pkl")) for f in ("5m", "15m", "1h", "4h", "24h") if os.path.isfile(os.path.join(ddir, f"{f}.pkl"))}
    man = store.save_resampled_dataset(symbol=sym, output_dir=dst_cex, df_1m_raw=merged, pool_address=f"binance:spot:{sym}USDT",
                                       source="binance_spot", synthetic=False, crawl_ok=not issues, requested_start_ts=start, requested_end_ts=end,
                                       extra_meta=extra)
    old_json = os.path.join(ddir, "manifest.json")
    if os.path.isfile(old_json):   # manifest cũ đã lỗi thời (sha/rows của chuỗi chưa gộp): cất, không xoá
        os.makedirs(os.path.join(archive, "binance", "cex", sym), exist_ok=True)
        os.replace(old_json, os.path.join(archive, "binance", "cex", sym, "manifest.json.premerge"))
    out["rows"] = man["rows"]
    out["sha256_1m"] = man["sha256_1m"][:12]
    # khung lớn cũ == khung mới (trừ nến biên đầu: ngày/khung đầu của dữ liệu cũ chỉ có một phần)
    chk = {}
    for f, old in old_frames.items():
        new = pd.read_pickle(os.path.join(ddir, f"{f}.pkl"))
        sub = new[new["open_time"] >= int(old["open_time"].iloc[1])].reset_index(drop=True)
        chk[f] = same_frame(sub, old.iloc[1:].reset_index(drop=True))
    out["old_frames_identical_from_2nd_bar"] = chk
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hist", default=os.path.join(DATA_DIR, "binance_hist"))
    ap.add_argument("--dst", default=os.path.join(DATA_DIR, "binance"))
    ap.add_argument("--archive", default=os.path.join(DATA_DIR, "_migration", "merge"), help="nơi cất manifest.json cũ của mã đã gộp")
    ap.add_argument("symbols", nargs="*")
    args = ap.parse_args()
    hist_cex, dst_cex = os.path.join(args.hist, "cex"), os.path.join(args.dst, "cex")
    syms = args.symbols or sorted(d for d in os.listdir(hist_cex) if os.path.isfile(os.path.join(hist_cex, d, "1m.pkl")))
    bad = False
    for sym in syms:
        r = merge_symbol(sym, hist_cex, dst_cex, args.apply, args.archive)
        print(r, flush=True)
        bad |= r.get("cur_part_identical") is False or r.get("overlap_close_equal") is False or not all((r.get("old_frames_identical_from_2nd_bar") or {}).values())
    print("FAILED" if bad else ("APPLIED" if args.apply else "dry-run OK"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
