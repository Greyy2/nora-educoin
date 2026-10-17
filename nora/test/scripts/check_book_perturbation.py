#!/usr/bin/env python
# Chạy: ops/run_limited.sh --no-lock -- test/scripts/check_book_perturbation.py (từ thư mục nora)
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
"""Kiểm overfit: đổi từng tham số của alpha ±1-2 bước schema, chấm trên holdout (bi quan). Plateau thật -> đa số lân cận vẫn lãi."""
import json
import warnings
import statistics as S
warnings.filterwarnings("ignore")
import pandas as pd
from backend.jobs.evaluate import run
from backend.analys.param import RISK
from backend.alpha.strategies import BY_ID, perp_symbols
b = json.load(open("data/alpha/book.json"))
w = b["windows"]; ms = lambda d: int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)
start, end = ms(w["dev2_end"]), ms(w["end"])
for s in b["strategies"]:
    cid, base = s["id"], s["params"]
    sch = BY_ID[cid]["params_schema"]
    def score(p):
        r = run([(cid, p)], perp_symbols(), start, end, 1.0, "extreme", RISK, base_frame="1h")
        return r["ret_pct"], r["mdd_pct"], r["trades"]
    b0 = score(base)
    rows = []
    for k, spec in sch.items():
        if k not in base or spec["type"] == "choice" or k == "risk_per_trade_pct":
            continue
        for mult in (-2, -1, 1, 2):
            v = base[k] + mult * spec["step"] * (2 if spec["type"] == "int" and spec["step"] == 1 and base[k] > 20 else 1)
            v = round(v, 6) if spec["type"] == "float" else int(v)
            if not (spec["min"] <= v <= spec["max"]) or v == base[k]:
                continue
            try:
                rows.append((k, v, *score({**base, k: v})))
            except Exception as e:
                rows.append((k, v, None, None, 0))
    rets = [r[2] for r in rows if r[2] is not None]
    pos = sum(1 for x in rets if x > 0)
    print(f"{cid}: gốc {b0[0]:+.2f}% MDD {b0[1]:.2f}% ({b0[2]} lệnh) | {len(rets)} lân cận: {pos} lãi ({pos/len(rets)*100:.0f}%), "
          f"trung vị {S.median(rets):+.2f}%, tệ nhất {min(rets):+.2f}%", flush=True)
    worst = sorted([r for r in rows if r[2] is not None], key=lambda r: r[2])[:5]
    print("   nhạy nhất:", [(r[0], r[1], round(r[2], 2)) for r in worst], flush=True)
