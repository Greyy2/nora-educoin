"""Kiểm tra nhanh simulator trên nến tổng hợp (chạy: run_limited.sh --no-lock -- test/scripts/okx_top10/check_sim.py)."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim


def run(o, h, l, c, side, p0, N0, params, i0=0):
    n = len(o)
    P = sim.pvec(params); M = sim.MAXL
    f = [np.zeros(M, np.int64), np.zeros(M), np.zeros(M)]; cc = [np.zeros(2 * M, np.int64), np.zeros(2 * M), np.zeros(2 * M), np.zeros(2 * M, np.int64)]
    sc = np.ones(n)
    nf, nc, closed = sim._run(np.array(o, float), np.array(h, float), np.array(l, float), np.array(c, float), sc, i0, n - 1, side, p0, N0, P, f[0], f[1], f[2], cc[0], cc[1], cc[2], cc[3])
    return nf, nc, closed, f, cc


# 1) long: giá 100, add -1% (99) rồi TP 0.5% từ avg: nến1 low 98.9 -> add ở 99; nến2 high 100 -> TP avg(99.5)*1.005=99.9975 -> khớp
o = [100, 100, 99.2]; h = [100, 100.1, 100.0]; l = [100, 98.9, 99.0]; c = [100, 99.2, 99.9]
nf, nc, closed, f, cc = run(o, h, l, c, 1, 100.0, 1000.0, dict(add_ref=0, step_pct=1.0, max_layers=2, size_mult=1.0, size_ref=1, tp_pct=0.5))
assert nf == 2 and abs(f[1][1] - 99.0) < 1e-9, (nf, f[1][:2])
avg = (1000 + 1000) / (1000 / 100 + 1000 / 99)
assert closed == 1 and nc == 2 and abs(cc[1][0] - avg * 1.005) < 1e-6, (closed, nc, cc[1][:2], avg * 1.005)
# 2) short đối xứng
o = [100, 100, 100.8]; h = [100, 101.1, 101.0]; l = [100, 100, 99.9]; c = [100, 100.8, 100.0]
nf, nc, closed, f, cc = run(o, h, l, c, -1, 100.0, 1000.0, dict(add_ref=0, step_pct=1.0, max_layers=2, size_mult=1.0, size_ref=1, tp_pct=0.5))
assert nf == 2 and abs(f[1][1] - 101.0) < 1e-9 and closed == 1
# 3) worst-case: cùng nến chạm SL và TP -> SL trước (long, SL 1% từ avg, TP 1%)
o = [100, 100]; h = [100, 101.5]; l = [100, 98.5]
nf, nc, closed, f, cc = run(o, h, l, [100, 100], 1, 100.0, 1000.0, dict(max_layers=1, tp_pct=1.0, sl_pct=1.0))
assert closed == 1 and abs(cc[1][0] - 99.0) < 1e-9, cc[1][:2]
# 4) gap xuống qua SL -> khớp ở open
o = [100, 97]; h = [100, 97.5]; l = [100, 96.5]
nf, nc, closed, f, cc = run(o, h, l, [100, 97], 1, 100.0, 1000.0, dict(max_layers=1, sl_pct=1.0))
assert abs(cc[1][0] - 97.0) < 1e-9
# 5) per-layer TP: layer0 TP 1% ở 101 khi giá hồi; layer1 (add 99) TP ở 99.99
o = [100, 100, 99.5, 99.5]; h = [100, 100, 100.2, 101.2]; l = [100, 98.9, 99.0, 99.4]
nf, nc, closed, f, cc = run(o, h, l, [100] * 4, 1, 100.0, 1000.0, dict(add_ref=0, step_pct=1.0, max_layers=2, size_mult=1.0, tp_pct=1.0, tp_mode=1))
assert nf == 2 and nc == 2 and closed == 1 and abs(sorted(cc[1][:2])[0] - 99 * 1.01) < 1e-6 and abs(sorted(cc[1][:2])[1] - 101.0) < 1e-6, cc[1][:2]
# 6) time-stop
o = [100] * 6; h = [100.1] * 6; l = [99.9] * 6
nf, nc, closed, f, cc = run(o, h, l, o, 1, 100.0, 1000.0, dict(max_layers=1, max_hold_bars=3))
assert closed == 1 and cc[0][0] == 3
print("check_sim OK")
