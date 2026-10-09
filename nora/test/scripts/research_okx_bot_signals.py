"""Tham khảo tín hiệu vào lệnh của các bot trade top trên OKX (CHỈ THAM KHẢO): báo cáo OKX không công bố điều kiện vào lệnh, nên dựng
"dấu vân tay" tín hiệu từ lịch sử lệnh công khai của họ — trạng thái thị trường lúc họ mở rổ lệnh so với mọi thời điểm khác cùng mã.

Nguồn lệnh: .agent/.../bots50/okx_bots_raw.json.gz (26 bot, ~11 nghìn lệnh con, 29/06–29/09/2026; mỗi lần dồn = một lệnh con).
Rổ lệnh = chuỗi lệnh con cùng bot + mã + chiều chồng thời gian; lệnh con đầu = điểm VÀO (tín hiệu), các lệnh sau = tầng DCA.
Đặc trưng lấy ở nến ĐÃ ĐÓNG ngay trước lúc vào (như bot Nora thấy): lợi nhuận 4h/24h, RSI14 (15m, 1h), vị trí trong Bollinger 1h,
ER20 và ADX14 khung 4h (đi ngang hay xu hướng), khoảng cách tới EMA200 1h, ATR% 1h.
AUC = xác suất giá trị lúc vào > giá trị ở một nến ngẫu nhiên cùng mã: 0,5 = không có thông tin; < 0,35 hoặc > 0,65 = dấu hiệu rõ.
Bước dồn được đo theo bội số ATR% lúc vào (để so trực tiếp với dca_step_pct của Nora).

Chạy: ops/run_limited.sh --no-lock -- test/scripts/research_okx_bot_signals.py
"""
import gzip
import json
import os
import statistics as S
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(NORA, "docs", "bmad", "research",
                   "market-okx-ai-fintech-agent-economy-2026-09-28", "digests", "bots50")
FMS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def features(root, sym):
    from backend.core.indicator import compute
    fr = {f: pd.read_pickle(os.path.join(root, sym, "perp", f"{f}.pkl")) for f in ("15m", "1h", "4h")}
    h = fr["1h"]
    c = h["close"]
    bbl, bbu = compute(h, "bbl_20_2"), compute(h, "bbu_20_2")
    f1 = pd.DataFrame({"t_close": h["open_time"] + FMS["1h"], "r4h": c.pct_change(4) * 100, "r24h": c.pct_change(24) * 100,
                       "rsi_1h": compute(h, "rsi_14"), "bb_pos_1h": (c - bbl) / (bbu - bbl), "ema200_dist_1h": (c / compute(h, "ema_200") - 1) * 100,
                       "atr_pct_1h": compute(h, "natr_14")})
    q = fr["15m"]
    f15 = pd.DataFrame({"t_close": q["open_time"] + FMS["15m"], "rsi_15m": compute(q, "rsi_14")})
    g = fr["4h"]
    f4 = pd.DataFrame({"t_close": g["open_time"] + FMS["4h"], "er_4h": compute(g, "er_20"), "adx_4h": compute(g, "adx_14")})
    return f1, f15, f4


def at(df, t):
    i = np.searchsorted(df["t_close"].to_numpy(), t, side="right") - 1      # nến đã đóng gần nhất trước t
    return df.iloc[i] if i >= 0 else None


def auc(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if not len(a) or not len(b):
        return None
    r = pd.Series(np.r_[a, b]).rank().to_numpy()
    return round((r[: len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)), 3)


def main():
    from backend.crawl.store import default_data_root
    root = os.path.join(default_data_root(), "cex")
    have = {s for s in os.listdir(root) if os.path.isdir(os.path.join(root, s, "perp"))}
    raw = json.load(gzip.open(os.path.join(RAW, "okx_bots_raw.json.gz")))
    variants = {r["name"]: r["variant"] for r in json.load(open(os.path.join(RAW, "dca_variants.json")))["bots"] if r["ex"] == "OKX"}
    baskets = []
    for b in raw:
        by = defaultdict(list)
        for t in b["trades"]:
            sym = t["instId"].split("-")[0]
            if sym in have and t["instId"].endswith("-USDT-SWAP"):
                by[(sym, t["posSide"])].append(t)
        for (sym, side), ts in by.items():
            ts.sort(key=lambda x: int(x["openTime"]))
            cur, end = None, 0
            for t in ts:
                o, c = int(t["openTime"]), int(t["closeTime"] or 0) or 10 ** 15   # lệnh con chưa đóng: coi như còn mở
                if cur is None or o > end:
                    cur = {"bot": b["name"], "dca": variants.get(b["name"], "?").startswith("DCA"), "sym": sym, "side": side, "t": o,
                           "px": float(t["openAvgPx"]), "adds": []}
                    baskets.append(cur)
                else:
                    cur["adds"].append(float(t["openAvgPx"]))
                end = max(end, c)
    feats, base = {}, defaultdict(list)
    t_lo, t_hi = min(x["t"] for x in baskets), max(x["t"] for x in baskets)
    for sym in sorted({x["sym"] for x in baskets}):
        f1, f15, f4 = features(root, sym)
        feats[sym] = (f1, f15, f4)
        m = f1[(f1["t_close"] >= t_lo) & (f1["t_close"] <= t_hi)]
        for _, row in m.iterrows():
            r = {**row.to_dict(), **at(f15, row["t_close"]).to_dict(), **at(f4, row["t_close"]).to_dict()}
            base[sym].append(r)
    rows = []
    for x in baskets:
        f1, f15, f4 = feats[x["sym"]]
        a, b_, c = at(f1, x["t"]), at(f15, x["t"]), at(f4, x["t"])
        if a is None or b_ is None or c is None:
            continue
        r = {**a.to_dict(), **b_.to_dict(), **c.to_dict(), **x}
        atr = r["atr_pct_1h"]
        sgn = 1 if x["side"] == "long" else -1
        r["steps_atr"] = [(sgn * (prev - px) / prev * 100) / atr for prev, px in zip([x["px"]] + x["adds"][:-1], x["adds"])] if atr else []
        rows.append(r)
    keys = ["r4h", "r24h", "rsi_15m", "rsi_1h", "bb_pos_1h", "ema200_dist_1h", "er_4h", "adx_4h", "atr_pct_1h"]
    print(f"{len(rows)} rổ lệnh (điểm vào) của {len({r['bot'] for r in rows})} bot trên {len(feats)} mã có dữ liệu OKX của Nora")
    for grp, cond in (("Bot DCA", lambda r: r["dca"]), ("Mọi bot", lambda r: True)):
        for side in ("long", "short"):
            sel = [r for r in rows if cond(r) and r["side"] == side]
            if len(sel) < 20:
                continue
            w = defaultdict(int)
            for r in sel:
                w[r["sym"]] += 1
            bl = [b for s, n in w.items() for b in base[s][:: max(1, len(base[s]) // (n * 20) or 1)]]
            print(f"\n== {grp} · {side.upper()} · {len(sel)} điểm vào ==")
            print(f"{'đặc trưng':16s} {'lúc vào (trung vị)':>20s} {'bình thường':>12s} {'AUC':>6s}")
            for k in keys:
                ev = [r[k] for r in sel if np.isfinite(r[k])]
                bv = [b[k] for b in bl if np.isfinite(b[k])]
                a = auc(ev, bv)
                mark = " <-- rõ" if a is not None and (a < 0.35 or a > 0.65) else ""
                print(f"{k:16s} {S.median(ev):20.3f} {S.median(bv):12.3f} {a if a is not None else '—':>6}{mark}")
            st = [s for r in sel for s in r["steps_atr"] if np.isfinite(s)]
            nl = [len(r["adds"]) for r in sel]
            if st:
                print(f"bước dồn (× ATR% 1h lúc vào): trung vị {S.median(st):.2f}, P25 {np.percentile(st, 25):.2f}, P75 {np.percentile(st, 75):.2f}"
                      f" | số tầng dồn/rổ: trung vị {S.median(nl):.0f}, P90 {np.percentile(nl, 90):.0f}, rổ có dồn {sum(1 for n in nl if n) / len(nl) * 100:.0f}%")


if __name__ == "__main__":
    main()
