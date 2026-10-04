"""Kiểm tra KHÔNG NHÌN TRƯỚC cho mọi chiến lược của sổ: tín hiệu tính trên dữ liệu bị cắt tại T phải TRÙNG KHỚP tín hiệu tính trên dữ liệu
đầy đủ ở mọi nến trước T. Nếu một chỉ báo/khung lớn dùng nến chưa đóng (dữ liệu tương lai), tín hiệu gần T sẽ đổi khi thêm dữ liệu sau T.

Cắt: mỗi khung chỉ giữ nến ĐÃ ĐÓNG tại T (open_time + độ dài khung <= T) — đúng như bot thấy lúc T.
Chạy: backend/utils/ops/run_limited.sh --no-lock -- test/scripts/check_signal_lookahead.py [--book explore] [--symbols BTC,ETH] [--cuts 6]
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)
FRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="explore", choices=("main", "explore"))
    ap.add_argument("--symbols", default="BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX")
    ap.add_argument("--bars", type=int, default=3000)
    ap.add_argument("--cuts", type=int, default=6)
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    from backend.core.params.presets import alphas_dir
    from backend.db.data_layout import default_data_root
    from backend.live import signals as ls
    from backend.live.bot import book_strategies
    path = os.path.join(alphas_dir(), "explore" if a.book == "explore" else "", "book.json")
    book = json.load(open(path, encoding="utf-8"))
    sts, tf = book_strategies(book), book["timeframe"]
    root = os.path.join(default_data_root(), "cex")
    rng = np.random.default_rng(7)
    total = 0
    for sym in a.symbols.split(","):
        need = ls.required_frames(sym, sts, tf)
        full = {fr: pd.read_pickle(os.path.join(root, sym, "perp", f"{fr}.pkl")) for fr in need}
        t_end = int(full[tf]["open_time"].iloc[-1]) + FRAME_MS[tf]
        t_start = t_end - a.bars * FRAME_MS[tf]
        full = {fr: df[df["open_time"] >= t_start - 400 * FRAME_MS[fr]].reset_index(drop=True) for fr, df in full.items()}
        ref = ls.evaluate(sym, sts, full, tf)
        tt = ref["t"]
        cuts = sorted(rng.choice(np.arange(len(tt) // 2, len(tt) - 1), a.cuts, replace=False))
        bad = 0
        for c in cuts:
            T = int(tt[c])                                                          # bot đang ở đầu nến tt[c]: mọi nến trước đã đóng
            cut = {fr: df[df["open_time"] + FRAME_MS[fr] <= T].reset_index(drop=True) for fr, df in full.items()}
            got = ls.evaluate(sym, sts, cut, tf)
            n = len(got["t"])
            assert (got["t"] == tt[:n]).all()
            for e_ref, e_got in zip(ref["entries"], got["entries"]):
                for key in ("match", "stop"):
                    d = np.flatnonzero(np.asarray(e_ref[key][:n], bool) != np.asarray(e_got[key], bool))
                    if len(d):
                        bad += len(d)
                        when = pd.Timestamp(int(tt[d[0]]), unit="ms", tz="UTC")
                        print(f"  {sym} {e_ref['strategy']} {key}: {len(d)} nến khác khi cắt tại {pd.Timestamp(T, unit='ms', tz='UTC')} "
                              f"(đầu tiên {when})")
        n_sig = {e["strategy"]: int(np.asarray(e["match"], bool).sum()) for e in ref["entries"]}
        print(f"{sym:5s} {len(cuts)} điểm cắt, {len(sts)} chiến lược, lệch {bad} | số nến có tín hiệu vào: {n_sig}", flush=True)
        total += bad
    print(f"TỔNG LỆCH: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
