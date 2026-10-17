#!/usr/bin/env python
# Chạy: ops/run_limited.sh --no-lock -- test/scripts/check_book_out_of_universe.py (từ thư mục nora; cần dữ liệu OKX của 8 mã ngoài vũ trụ)
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
"""Kiểm ngoài vũ trụ: sổ hiện tại chạy trên 8 mã CHƯA TỪNG dùng khi tối ưu/kiểm định, toàn bộ 3 năm, khớp bi quan."""
import json
import os
import warnings
warnings.filterwarnings("ignore")
import pandas as pd
from backend.jobs.evaluate import run
from backend.analys.param import RISK
b = json.load(open("data/alpha/book.json"))
items = [(s["id"], s["params"]) for s in b["strategies"]]
syms = [s for s in ("LINK", "LTC", "DOT", "TRX", "BCH", "NEAR", "UNI", "ATOM") if os.path.isdir(f"data/market/okx/cex/{s}/perp")]
start = int(pd.Timestamp("2023-12-01", tz="UTC").timestamp() * 1000); end = int(pd.Timestamp("2026-10-03", tz="UTC").timestamp() * 1000)
for sf in ("level", "extreme"):
    r = run(items, [f"{s}@perp" for s in syms], start, end, b["risk_per_trade_pct"], sf, RISK, base_frame="1h")
    by = r.get("by_symbol") or {}
    print(sf, syms, {k: r.get(k) for k in ("ret_pct", "mdd_pct", "sharpe", "trades")}, flush=True)
    if by: print("   theo mã:", {k: (round(v, 2) if isinstance(v, (int, float)) else v) for k, v in by.items()}, flush=True)
for s in ("dca_long", "dca_short", "kema_long"):
    it = [x for x in items if x[0] == s]
    r = run(it, [f"{x}@perp" for x in syms], start, end, b["risk_per_trade_pct"], "extreme", RISK, base_frame="1h")
    print("  ", s, {k: r.get(k) for k in ("ret_pct", "mdd_pct", "sharpe", "trades")}, flush=True)
