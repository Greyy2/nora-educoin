"""Kiểm tra nhanh families_swing (chạy: run_limited.sh --no-lock -- test/scripts/okx_top10/check_swing.py).
 1) _run2 trùng sim._run trên tập tham số chung (TP/SL/trailing/add/time-stop) cho 60 basket thật;
 2) hoà vốn (be_act), time-exit có cổng, cờ chỉ báo/phiên hoạt động trên nến tổng hợp."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import families_swing as fs
import load, sim

bs = load.build_baskets(load.get_bot("Dark-Wood-Dahlia"))
p1 = dict(add_ref=0, step_pct=1.0, max_layers=4, size_mult=0.5, size_ref=1, tp_pct=1.2, sl_pct=3.0, trail_act=0.8, trail_dist=0.4, max_hold_bars=3000)
p2 = dict(add_ref=0, step=1.0, maxL=4, size_mult=0.5, size_ref=1, tp=1.2, sl=3.0, tr_act=0.8, tr_dist=0.4, maxhold=3000)
n = bad = 0
for B in bs[:60]:
    a = sim.simulate(B, p1); b = fs.simulate2(B, p2)
    if a is None: continue
    n += 1; bad += abs(a["pnl"] - b["pnl"]) > 1e-6 or len(a["closes"]) != len(b["closes"])
assert bad == 0, (bad, n)


def run(o, h, l, c, side, p0, N0, params, xf=None, sf=None):
    k = len(o); M = fs.MAXL2; P = fs.pvec2(params); z = np.zeros(k, np.int8)
    f = [np.zeros(M, np.int64), np.zeros(M), np.zeros(M)]; cc = [np.zeros(2 * M, np.int64), np.zeros(2 * M), np.zeros(2 * M), np.zeros(2 * M, np.int64)]
    nf, nc, closed = fs._run2(*(np.array(x, float) for x in (o, h, l, c)), np.ones(k), z if xf is None else xf, z if sf is None else sf, 0, k - 1, side, p0, N0, P, f[0], f[1], f[2], cc[0], cc[1], cc[2], cc[3])
    return nf, nc, closed, f, cc


# hoà vốn: lên +1.5% rồi về 100 -> thoát tại 100 (SL dời về giá TB)
o = [100, 100, 101.5, 100.5, 99.9]; h = [100, 101.6, 101.6, 100.6, 100.0]; l = [100, 100, 100.4, 99.9, 99.5]
nf, nc, closed, f, cc = run(o, h, l, o, 1, 100.0, 1000.0, dict(be_act=1.0, sl=2.0))
assert closed == 1 and abs(cc[1][0] - 100.0) < 1e-9 and cc[0][0] == 3
# time-exit chỉ khi chưa có lãi: giá đi xuống -> đóng ở nến T
o = [100, 99.5, 99.4, 99.3, 99.2, 99.1]; h = [100] * 6; l = [100, 99.4, 99.3, 99.2, 99.1, 99.0]
nf, nc, closed, f, cc = run(o, h, l, o, 1, 100.0, 1000.0, dict(tx_bars=3, tx_gate=2))
assert closed == 1 and cc[0][0] == 3
# cùng tình huống nhưng đang lãi (short) -> cổng 'chỉ khi chưa lãi' không đóng
nf, nc, closed, f, cc = run(o, h, l, o, -1, 100.0, 1000.0, dict(tx_bars=3, tx_gate=2))
assert closed == 0
# cờ chỉ báo: đóng tại nến có cờ
xf = np.zeros(6, np.int8); xf[4] = 1
nf, nc, closed, f, cc = run(o, h, l, o, 1, 100.0, 1000.0, dict(xgate=0), xf=xf)
assert closed == 1 and cc[0][0] == 4
# sl_roi -> % giá = ROI/đòn bẩy
assert abs(fs.roi_params(dict(sl_roi=30), 20.0)["sl"] - 1.5) < 1e-12
print("check_swing OK (%d basket trùng sim.py)" % n)
