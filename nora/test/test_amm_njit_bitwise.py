"""P9.4b T6: toán AMM trong kernel (core/backtest.py: _amm_impact, _amm_out_raw, ...) và vỏ Python (amm_amount_out / amm_price_impact / AmmImpact) phải BIT-IDENTICAL (float.hex) với bản đóng băng
của core/execute/amm.py cũ (test/reference_engine.py: RefAmmImpact, ref_*) trên 10k dự trữ / phí / gas / khối lượng ngẫu nhiên, pool volatile và stable.

Giá biên (reserve_price) tính bằng NumPy ở Python rồi ghi vào F_MID (KernelBook.set_amm): NumPy >= 2 (AVX512/SVML) tính `y ** 3` khác libm pow ở bit cuối
(~5% đầu vào) nên bản njit math.pow không thể trùng từng bit — test cuối khoá lý do này (không phải test hành vi: nếu máy khác không còn khác biệt thì chỉ in cảnh báo)."""
import math
import random

import numpy as np
import pytest

from reference_engine import RefAmmImpact, ref_amount_out, ref_price_impact, ref_reserve_price
from backend.core import backtest as bt

N = 10_000


def _draw(rng):
    rq = 10 ** rng.uniform(2, 9)
    rb = rq / 10 ** rng.uniform(-2, 3) * math.exp(rng.gauss(0, 0.3))
    fee = rng.choice([0.0, 1e-4, 5e-4, 0.003, 0.01, 0.05, rng.uniform(0, 0.2)])
    gas = rng.choice([0.0, 0.0, 0.02, 0.5, rng.uniform(0, 5)])
    qu = 10 ** rng.uniform(-2, 3)
    notional = 10 ** rng.uniform(-1, 7.5)
    return rb, rq, fee, gas, qu, notional, rng.random() < 0.5


def _slot_arrays(fee, stable, gas, rb, rq, qu):
    P = np.zeros((1, bt.P_FIXED + 2))
    F = np.zeros((1, bt.F_FIXED + 1))
    P[0, bt.P_AFEE], P[0, bt.P_ASTABLE], P[0, bt.P_AGAS] = fee, 1.0 if stable else 0.0, gas
    F[0, bt.F_RB], F[0, bt.F_RQ], F[0, bt.F_QU] = rb, rq, qu
    with np.errstate(all="ignore"):
        F[0, bt.F_MID] = float(bt.reserve_price(rb, rq, stable))
    return P, F, np.zeros(bt.NG, dtype=np.int64)


@pytest.mark.parametrize("stable", [False, True], ids=["volatile", "stable"])
def test_kernel_impact_equals_frozen_amm_impact(stable):
    rng = random.Random(41_000 + stable)
    for i in range(N):
        rb, rq, fee, gas, qu, n, buy = _draw(rng)
        ref = RefAmmImpact(fee, stable, gas)
        ref.set_state(rb, rq, qu)
        P, F, G = _slot_arrays(fee, stable, gas, rb, rq, qu)
        got = bt._amm_impact(0, n, buy, P, F, G)
        want = ref(n, buy)
        assert got.hex() == want.hex() and G[bt.G_AMERR] == 0, (i, stable, rb, rq, fee, gas, qu, n, buy, got.hex(), want.hex())
        # notional không dương -> 0.0 (kể cả NaN)
        assert bt._amm_impact(0, 0.0, buy, P, F, G) == 0.0 and bt._amm_impact(0, float("nan"), buy, P, F, G) == 0.0 and ref(-1.0, buy) == 0.0


@pytest.mark.parametrize("stable", [False, True], ids=["volatile", "stable"])
def test_amm_shim_equals_frozen_math(stable):
    rng = random.Random(42_000 + stable)
    for i in range(N // 2):
        rb, rq, fee, gas, qu, n, buy = _draw(rng)
        assert bt.reserve_price(rb, rq, stable).hex() == float(ref_reserve_price(rb, rq, stable)).hex()
        assert bt.amm_price_impact(n, buy, rb, rq, qu, fee, stable).hex() == ref_price_impact(n, buy, rb, rq, qu, fee, stable).hex(), (i, stable)
        spend = n / qu
        assert bt.amm_amount_out(spend, rq, rb, fee, stable).hex() == ref_amount_out(spend, rq, rb, fee, stable).hex()
        m = bt.AmmImpact(fee, stable, gas)
        r = RefAmmImpact(fee, stable, gas)
        m.set_state(rb, rq, qu)
        r.set_state(rb, rq, qu)
        assert m(n, buy).hex() == r(n, buy).hex()
        assert bt._stable_k(rb, rq).hex() == float(rb * rb * rb * rq + rb * rq * rq * rq).hex()


def test_stable_bisection_hits_the_iteration_cap_identically():
    """Pool lệch cực đoan: chia đôi chạy đủ/ gần trần 200 vòng — cùng kết quả bit với bản đóng băng."""
    for rb, rq, n in ((1e-2, 1e6, 1e3), (1e6, 1e-2, 1.0), (1.0, 1.0, 1e5), (1e9, 1e9, 1e-3), (1e3, 1e3, 1e3)):
        P, F, G = _slot_arrays(0.003, True, 0.0, rb, rq, 1.0)
        for buy in (True, False):
            r = RefAmmImpact(0.003, True, 0.0)
            r.set_state(rb, rq, 1.0)
            assert bt._amm_impact(0, n, buy, P, F, G).hex() == r(n, buy).hex()


def test_invalid_state_raises_same_valueerror_and_kernel_flags_error():
    r = RefAmmImpact(0.003, False, 0.0)
    with pytest.raises(ValueError) as want:
        r.set_state(0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="dự trữ pool không hợp lệ") as got:
        bt._amm_state(0.0, 1.0, 1.0, False)
    assert str(got.value) == str(want.value)
    with pytest.raises(ValueError, match="phí pool phải trong"):
        bt.AmmImpact(1.0, False)
    with pytest.raises(ValueError, match="swap không hợp lệ"):
        bt.amm_amount_out(0.0, 1.0, 1.0, 0.003, False)
    # kernel: dự trữ chưa đặt (0) -> cờ lỗi, trả 0.0; Python (_amm_check) ném ValueError
    P, F, G = _slot_arrays(0.003, False, 0.0, 0.0, 0.0, 0.0)
    assert bt._amm_impact(0, 100.0, True, P, F, G) == 0.0 and G[bt.G_AMERR] == 1
    with pytest.raises(ValueError, match="swap không hợp lệ"):
        bt._amm_check(G)
    assert G[bt.G_AMERR] == 0


def test_numpy_cube_is_not_libm_pow_on_this_machine():
    """Vì sao giá biên không nằm trong njit: ghi nhận khác biệt NumPy ** 3 vs libm pow (math.pow, = numba) trên máy chạy test."""
    rng = random.Random(7)
    diff = 0
    for _ in range(20_000):
        x = 10 ** rng.uniform(-3, 8)
        diff += float(np.asarray(x) ** 3) != math.pow(x, 3.0)
    if diff == 0:
        pytest.skip("máy này NumPy ** 3 == libm pow: njit math.pow cũng trùng (vẫn dùng NumPy để giữ bit trên mọi máy)")
    assert diff > 0
