"""Chạy thử các truy vấn thống kê trên dữ liệu thật."""
import os, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.stats import queries as q

RUN = 3379
for name, fn in [
    ("run_info", lambda: q.run_info(RUN)),
    ("overview", lambda: q.overview(RUN)),
    ("by_flow", lambda: q.by_flow(RUN)),
    ("behavior", lambda: q.behavior(RUN)),
    ("by_symbol", lambda: q.by_symbol(RUN, 5)),
    ("timeline", lambda: q.timeline(RUN)),
    ("trades", lambda: q.trades(RUN, 1, 3)),
    ("insights", lambda: q.insights(RUN)),
]:
    t0 = time.time()
    try:
        r = fn()
        ms = int((time.time() - t0) * 1000)
        n = len(r) if isinstance(r, (list, dict)) else 1
        print(f"{name:<12} {ms:>6} ms   OK ({n} phần tử)")
    except Exception as e:
        print(f"{name:<12}        LỖI: {str(e)[:110]}")
