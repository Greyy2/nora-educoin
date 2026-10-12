"""Test hàm thuần của core/position_size.py (mức giá + khối lượng của chính sách vị thế).
Tracker uỷ quyền vào policy; kết quả tracker không đổi được bảo chứng bởi golden + parity kernel."""
import math

import pytest

from backend.models import position_size as P

L, S = 1.0, -1.0


def test_dca_level_and_trigger():
    assert P.dca_level(100.0, 2.0, L) == 100.0 * (1 - 1.0 * 2.0 / 100.0)
    assert P.dca_level(100.0, 2.0, S) == pytest.approx(102.0)
    assert P.dca_level(100.0, 2.0, L) == pytest.approx(98.0)
    # limit_through: long đòi giá xuống THẤP hơn mức, short đòi CAO hơn
    assert P.dca_trigger(98.0, 0.001, L) == pytest.approx(98.0 * 0.999)
    assert P.dca_trigger(102.0, 0.001, S) == pytest.approx(102.0 * 1.001)
    assert P.dca_trigger(98.0, 0.0, L) == 98.0


def test_sl_level():
    assert P.sl_level(100.0, 5.0, L) == pytest.approx(95.0)
    assert P.sl_level(100.0, 5.0, S) == pytest.approx(105.0)


def test_trail_active_and_level():
    # long: đỉnh 110 so avg 100 -> lãi 10%
    assert P.trail_active(110.0, 100.0, 10.0, L)
    assert not P.trail_active(109.0, 100.0, 10.0, L)
    assert P.trail_active(100.0, 100.0, 0.0, L)            # activation 0: luôn bật
    # short: đáy 90 -> lãi 10%
    assert P.trail_active(90.0, 100.0, 10.0, S)
    assert not P.trail_active(110.0, 100.0, 1.0, S)        # giá lên = lỗ
    assert P.trail_active(0.0, 0.0, 0.0, L)                # avg = 0 -> gain 0
    assert not P.trail_active(5.0, 0.0, 1.0, L)
    assert P.trail_level(110.0, 2.0, L) == pytest.approx(107.8)
    assert P.trail_level(90.0, 2.0, S) == pytest.approx(91.8)


def test_tp_level_need_hit_fill():
    assert P.tp_level(100.0, 3.0, L) == pytest.approx(103.0)
    assert P.tp_level(100.0, 3.0, S) == pytest.approx(97.0)
    assert P.tp_need(103.0, 0.001, L) == pytest.approx(103.0 * 1.001)
    assert P.tp_need(97.0, 0.001, S) == pytest.approx(97.0 * 0.999)
    assert P.tp_need(103.0, 0.0, L) == 103.0
    assert P.tp_hit(103.0, 103.0, True) and not P.tp_hit(102.9, 103.0, True)
    assert P.tp_hit(97.0, 97.0, False) and not P.tp_hit(97.1, 97.0, False)
    # kiểu SWAP (AMM, limit_taker): gap có lợi, open vượt mức -> khớp ở open. Lệnh limit chờ sẵn KHÔNG dùng hàm này (khớp ở mức, test_conservative_fills.py)
    assert P.tp_fill_price(103.0, 105.0, True) == 105.0
    assert P.tp_fill_price(103.0, 100.0, True) == 103.0
    assert P.tp_fill_price(97.0, 95.0, False) == 95.0
    assert P.tp_fill_price(97.0, 100.0, False) == 97.0


def test_liq_price():
    assert P.liq_price(100.0, 10.0, 0.005, True) == 100.0 * (1.0 - 1.0 / 10.0 + 0.005)
    assert P.liq_price(100.0, 10.0, 0.005, True) == pytest.approx(90.5)
    assert P.liq_price(100.0, 10.0, 0.005, False) == pytest.approx(109.5)


def test_reached_and_gap_fill():
    assert P.reached(95.0, 94.0, True) and P.reached(95.0, 95.0, True) and not P.reached(95.0, 96.0, True)
    assert P.reached(105.0, 106.0, False) and P.reached(105.0, 105.0, False) and not P.reached(105.0, 104.0, False)
    assert P.gap_fill(95.0, 100.0, True) == 95.0       # chạm bình thường: khớp ở mức
    assert P.gap_fill(95.0, 90.0, True) == 90.0        # gap xuống qua mức: khớp ở open
    assert P.gap_fill(105.0, 100.0, False) == 105.0
    assert P.gap_fill(105.0, 110.0, False) == 110.0
    assert P.stop_extreme_fill(95.0, 92.0, True) == 92.0
    assert P.stop_extreme_fill(95.0, 97.0, True) == 95.0
    assert P.stop_extreme_fill(105.0, 108.0, False) == 108.0


def test_pick_first_touched_tie_prefers_exit():
    ev = [(95.0, 1, "dca"), (95.0, 0, "sl"), (97.0, 0, "trail")]
    assert P.pick_first_touched(ev, True)[2] == "trail"              # long: mức cao nhất trước
    assert P.pick_first_touched(ev[:2], True)[2] == "sl"             # hoà mức -> thoát
    ev_s = [(105.0, 1, "dca"), (105.0, 0, "sl"), (103.0, 0, "trail")]
    assert P.pick_first_touched(ev_s, False)[2] == "trail"
    assert P.pick_first_touched(ev_s[:2], False)[2] == "sl"


def test_fills_fees_pnl():
    assert P.entry_fill_price(100.0, 0.001, True) == 100.0 * (1 + 0.001)
    assert P.entry_fill_price(100.0, 0.001, False) == 100.0 * (1 - 0.001)
    assert P.exit_fill_price(100.0, 0.001, True) == 100.0 * (1 - 0.001)
    assert P.exit_fill_price(100.0, 0.001, False) == 100.0 * (1 + 0.001)
    assert P.entry_fee(1000.0, 0.0005) == pytest.approx(0.5)
    assert P.exit_fee(2.0, 500.0, 0.0005) == 2.0 * 500.0 * 0.0005
    assert P.gross_pnl(2.0, 100.0, 105.0, True) == 10.0
    assert P.gross_pnl(2.0, 100.0, 105.0, False) == -10.0
    assert P.unrealized_pnl(2.0, 100.0, 105.0, 1.5, True) == 8.5
    assert P.unrealized_pnl(2.0, 100.0, 95.0, 1.5, False) == 8.5
    assert P.in_profit(101.0, 100.0, True) and not P.in_profit(100.0, 100.0, True)
    assert P.in_profit(99.0, 100.0, False) and not P.in_profit(101.0, 100.0, False)


def test_funding_payment_sign():
    assert P.funding_payment(2.0, 100.0, 0.0001, True) == pytest.approx(0.02)     # long trả khi rate > 0
    assert P.funding_payment(2.0, 100.0, 0.0001, False) == pytest.approx(-0.02)   # short nhận
    assert P.funding_payment(2.0, 100.0, -0.0001, True) == pytest.approx(-0.02)


def test_slip_and_round_trip_cost():
    assert P.slip_rate(0.0005, None, 1000.0, True) == 0.0005
    impact = lambda n, buy: 0.0001 * n / 1000.0 * (1.0 if buy else 2.0)
    assert P.slip_rate(0.0005, impact, 1000.0, True) == pytest.approx(0.0001)
    assert P.slip_rate(0.0005, impact, 1000.0, False) == pytest.approx(0.0002)
    assert P.round_trip_cost(0.001, 0.0005, None, 0.0) == 2.0 * (0.001 + 0.0005)
    assert P.round_trip_cost(0.001, 0.0005, impact, 1000.0) == pytest.approx(2 * 0.001 + 0.0001 + 0.0002)


def test_layer_mult_total_and_exit_scaling():
    assert P.layer_mult_total([], 0) == 1.0
    assert P.layer_mult_total([2.0, 2.0, 2.0], 2) == 1.0 + 2.0 + 4.0      # chỉ n_steps hệ số đầu
    assert P.layer_mult_total([1.5, 2.0], 2) == 1.0 + 1.5 + 3.0
    sl, tp, tr, act, steps = P.exit_params_scaled(2.0, 1.0, 3.0, 0.5, 0.25, [1.0, 2.0])
    assert (sl, tp, tr, act, steps) == (2.0, 6.0, 1.0, 0.5, [2.0, 4.0])


def test_flat_margin_and_clamps():
    assert P.flat_margin(10000.0, 5.0) == 500.0
    assert P.clamp_margin(500.0, 10000.0, 1.0, 0.001, math.inf) == 500.0
    assert P.clamp_margin(500.0, 100.0, 1.0, 0.0, math.inf) == 100.0         # ngân sách chặn
    assert P.clamp_margin(500.0, 10000.0, 5.0, 0.0, 1000.0) == 200.0         # trần danh nghĩa / đòn bẩy
    assert P.planned_risk_cap(100.0, 2.0, 5.0, 0.002, 3.0) == 100.0 * 2.0 * (5.0 / 100.0 + 0.002) * 3.0


def test_apply_risk_ceiling():
    assert P.apply_risk_ceiling(100.0, 10.0, math.inf) == (100.0, 10.0)
    assert P.apply_risk_ceiling(100.0, 10.0, 20.0) == (100.0, 10.0)           # chưa vượt
    assert P.apply_risk_ceiling(100.0, 10.0, 5.0) == (50.0, 5.0)              # co tỉ lệ
    assert P.apply_risk_ceiling(100.0, 10.0, 0.0) == (0.0, 10.0)              # trần 0 -> không mở


def test_risk_margin_spot_and_perp():
    # spot: sl 2%, phí 0.1% + trượt 0.05% -> cost 0.003; notional = 10000*0.5%/(0.02+0.003)
    m, lev, risk = P.risk_margin(10000.0, 0.5, 100.0, 2.0, 0.001, 0.0005, None, False, 1.0, 0.005, 1.0, 1.0)
    notional = 10000.0 * 0.5 / 100.0 / (0.02 + 0.003)
    assert lev == 1.0 and m == pytest.approx(notional) and risk == pytest.approx(notional * 0.023)
    # perp: đòn bẩy bị chặn theo khoảng SL: int(1/(1.5*0.02+0.005)) = 28 -> min(10, 28) = 10
    m, lev, _ = P.risk_margin(10000.0, 0.5, 1000.0, 2.0, 0.001, 0.0005, None, True, 10.0, 0.005, 10.0, 2.0)
    assert lev == 10.0 and m == pytest.approx(notional / 2.0 / 10.0)
    # SL rộng 20%: int(1/(0.3+0.005)) = 3 -> đòn bẩy 3
    _, lev, _ = P.risk_margin(10000.0, 0.5, 1000.0, 20.0, 0.001, 0.0005, None, True, 10.0, 0.005, 10.0, 1.0)
    assert lev == 3.0
    # trần danh nghĩa 1% vốn = 100
    m, _, _ = P.risk_margin(10000.0, 0.5, 1.0, 2.0, 0.001, 0.0005, None, False, 1.0, 0.005, 1.0, 1.0)
    assert m == pytest.approx(100.0)


def test_risk_margin_impact_two_pass():
    impact = lambda n, buy: 0.00001 * n / 100.0
    m, lev, risk = P.risk_margin(10000.0, 0.5, 100.0, 2.0, 0.001, 0.0005, impact, False, 1.0, 0.005, 1.0, 1.0)
    n1 = min(10000.0 * 0.5 / 100.0 / (0.02 + 2.0 * 0.001), 10000.0)
    cost = 2.0 * 0.001 + impact(n1, True) + impact(n1, False)
    n2 = min(10000.0 * 0.5 / 100.0 / (0.02 + cost), 10000.0)
    assert lev == 1.0 and m == n2 and risk == n2 * (0.02 + cost)
