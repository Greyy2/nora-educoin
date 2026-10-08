"""Đường giá trong nến `intrabar_path` ("ohlc" mặc định = NautilusTrader, "adaptive") — nến dựng tay cho từng điểm của quy tắc.

Nguồn ngữ nghĩa: NautilusTrader `matching_engine::process_bar` + `iterate` (đã kiểm bằng thực nghiệm trên bản 2.0.0rc6, xem
test/scripts/nautilus_diff/REPORT.md và adr-p6-unified-execution.md mục 9):
1. nến là đường O -> H -> L -> C (adaptive: cực gần open trước; HOÀ khoảng cách -> Low trước); chặng không đổi giá không có tick;
2. mỗi chặng là MỘT tick: nhóm DCA (mọi tầng bị xuyên qua) -> chốt lời -> stop (SL / trailing / thanh lý), không theo thứ tự mức giá;
   stop-market khớp ở mức kích hoạt (tick mở cửa/gap: ở open), limit (DCA, TP) khớp ở mức đặt;
3. SL / TP đã nằm trên sàn từ cuối nến trước: mức cố định cả nến; đặt lại từ avg mới sau fill DCA chỉ có hiệu lực từ nến sau,
   riêng TP mới đã "trong giá" ở close thì khớp ngay ở close (taker);
4. TP vẫn khớp trong nến có DCA nếu một chặng sau chạm mức TP (cũ);
5. trailing: đỉnh chạy theo từng chặng, mức dùng ở một chặng là mức tính sau chặng trước.
Mỗi kịch bản chạy qua BỐN cài đặt (tracker, PositionManager+SimVenue, oracle đóng băng, kernel numba) phải ra cùng kết quả, cho long và short.
Giá chọn để tính tay: phí = trượt = 0, ký quỹ mỗi tầng 20% vốn, vào ở open 100 (nến đầu của kịch bản).
"""
import pytest

from backend.core import position_size as policy
from backend.core.models import PositionType
from backend.core.backtest import PositionTracker
from backend.core.params import StrategyParams
from test_conservative_fills import _all, _params, _pos

FLAT1 = (100.0, 100.0, 100.0, 100.0)
AVG2 = 2 / (1 / 100 + 1 / 99)          # avg long sau tầng DCA @99 (hai tầng cùng ký quỹ)
AVG2_S = 2 / (1 / 100 + 1 / 101)       # avg short sau tầng DCA @101


def _run(side, bars, path, **pos):
    return _all(side, [FLAT1] + list(bars), intrabar_path=path, **pos)


# ─── mặc định, tham số, hàm thuần ───────────────────────────────────────────
def test_default_is_ohlc_and_validation():
    from backend.core.params import build_params
    assert StrategyParams().intrabar_path == "ohlc"
    p = build_params("f", {"match": [], "stop": []}, "LONG", {"market": "spot"}, "cex")
    assert p.intrabar_path == "ohlc"
    assert PositionTracker(0, 0, "T", "f", p, PositionType.LONG).intrabar_path == "ohlc"
    with pytest.raises(ValueError):
        PositionTracker(0, 0, "T", "f", _params("LONG", _pos("LONG", intrabar_path="zigzag")), PositionType.LONG)


def test_bar_points_nautilus_tie_rule():
    assert policy.bar_points("ohlc", 100, 103, 99, 101) == (100, 103, 99, 101)
    assert policy.bar_points("adaptive", 100, 101, 97, 99) == (100, 101, 97, 99)       # open gần high hơn -> High trước
    assert policy.bar_points("adaptive", 100, 103, 99, 101) == (100, 99, 103, 101)     # open gần low hơn -> Low trước
    assert policy.bar_points("adaptive", 100, 102, 98, 100) == (100, 98, 102, 100)     # HOÀ -> Low trước (Nautilus: high - open < open - low)


# ─── 1-2. SL và TP cùng nến: thứ tự đường giá ───────────────────────────────
def test_long_ohlc_takes_tp_first_when_both_inside():
    ps = _run("LONG", [(100.0, 102.0, 97.0, 100.0)], "ohlc", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(101.0)


def test_long_adaptive_low_first_takes_sl():
    # open 100 gần low 97.5 hơn high 103 -> L trước: SL 98 thắng TP 101 (ohlc vẫn lấy TP)
    bar = [(100.0, 103.0, 97.5, 100.0)]
    ps = _run("LONG", bar, "adaptive", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "SL" and ps[0].close_price == pytest.approx(98.0)
    ps = _run("LONG", bar, "ohlc", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP"


def test_adaptive_tie_goes_low_first_long():
    ps = _run("LONG", [(100.0, 102.0, 98.0, 100.0)], "adaptive", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "SL"


def test_short_ohlc_takes_sl_first_adaptive_low_first_takes_tp():
    # short: SL 102 (trên), TP 99 (dưới), nến (100, 103, 97.5, 100): ohlc đi H trước -> SL; adaptive: H-O = 3 >= O-L = 2.5 -> L trước -> TP
    bar = [(100.0, 103.0, 97.5, 100.0)]
    ps = _run("SHORT", bar, "ohlc", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "SL" and ps[0].close_price == pytest.approx(102.0)
    ps = _run("SHORT", bar, "adaptive", stop_loss_rate=2.0, take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(99.0)


# ─── 2. nhóm DCA khớp trước stop trong cùng tick (kể cả tầng nằm dưới SL) ────
@pytest.mark.parametrize("path", ["ohlc", "adaptive"])
def test_long_every_crossed_dca_fills_before_stop_in_same_tick(path):
    # DCA @99 và @97.515, SL 98 (cố định từ avg 100): nến rơi tới 97 -> cả hai tầng khớp RỒI SL cũ 98 đóng cả vị thế (Nautilus)
    ps = _run("LONG", [(100.0, 100.0, 97.0, 97.0)], path, stop_loss_rate=2.0, dca_steps=[1.0, 1.5], dca_multipliers=[1.0, 1.0], dca_max_layers=2)
    assert len(ps) == 1 and ps[0].layers == 3 and ps[0].status.name == "SL"
    assert ps[0].close_price == pytest.approx(98.0)


@pytest.mark.parametrize("path", ["ohlc", "adaptive"])
def test_short_every_crossed_dca_fills_before_stop_in_same_tick(path):
    ps = _run("SHORT", [(100.0, 103.0, 100.0, 103.0)], path, stop_loss_rate=2.0, dca_steps=[1.0, 1.5], dca_multipliers=[1.0, 1.0], dca_max_layers=2)
    assert len(ps) == 1 and ps[0].layers == 3 and ps[0].status.name == "SL"
    assert ps[0].close_price == pytest.approx(102.0)


# ─── 1. tick mở cửa (gap): limit ở mức đặt, stop ở open ─────────────────────
def test_long_gap_through_dca_and_sl_dca_at_limit_then_stop_at_open():
    ps = _run("LONG", [(96.0, 96.5, 95.0, 95.5)], "ohlc", stop_loss_rate=2.0)
    assert ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].avg_price == pytest.approx(AVG2) and ps[0].close_price == pytest.approx(96.0)


def test_short_gap_through_dca_and_sl_dca_at_limit_then_stop_at_open():
    ps = _run("SHORT", [(104.0, 105.0, 103.5, 104.5)], "adaptive", stop_loss_rate=2.0)
    assert ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].avg_price == pytest.approx(AVG2_S) and ps[0].close_price == pytest.approx(104.0)


def test_gap_above_tp_fills_at_tp_level():
    ps = _run("LONG", [(102.0, 102.5, 101.9, 102.2)], "ohlc", take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(101.0)


# ─── 3. SL / TP cố định cả nến, mức mới từ nến sau ──────────────────────────
def test_long_old_sl_fires_in_same_bar_new_sl_from_next_bar():
    ps = _run("LONG", [(100.0, 100.0, 97.8, 97.8)], "ohlc", stop_loss_rate=2.0)
    assert ps[0].layers == 2 and ps[0].close_price == pytest.approx(98.0)
    ps = _run("LONG", [(100.0, 100.0, 98.5, 98.6), (98.6, 98.6, 97.9, 98.0), (98.0, 98.0, 97.4, 97.4)], "ohlc", stop_loss_rate=2.0)
    assert ps[0].layers == 2 and ps[0].close_price == pytest.approx(AVG2 * 0.98)


def test_short_old_sl_fires_in_same_bar():
    ps = _run("SHORT", [(100.0, 102.2, 100.0, 102.2)], "ohlc", stop_loss_rate=2.0)
    assert ps[0].layers == 2 and ps[0].close_price == pytest.approx(102.0)


# ─── 4. TP không bị bỏ qua trong nến có DCA ─────────────────────────────────
def test_long_tp_still_fills_after_dca_in_same_bar_at_old_level():
    # adaptive: L trước (open 100 gần low 98.8 hơn high 101.5? H-O = 1.5 >= O-L = 1.2 -> Low trước): DCA @99 rồi TP CŨ 101 (avg 100 x 1.01)
    ps = _run("LONG", [(100.0, 101.5, 98.8, 101.2)], "adaptive", take_profit_rate=1.0)
    assert ps[0].layers == 2 and ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(101.0)


def test_short_tp_still_fills_after_dca_in_same_bar_at_old_level():
    # adaptive: H-O = 1.2 < O-L = 1.5 -> High trước: DCA @101, rồi L chạm TP CŨ 99 (avg 100 x 0.99) -> khớp ở 99
    ps = _run("SHORT", [(100.0, 101.2, 98.5, 99.0)], "adaptive", take_profit_rate=1.0)
    assert ps[0].layers == 2 and ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(99.0)


def test_long_replaced_tp_already_in_the_money_at_close_fills_at_close():
    # DCA @99 ở L, TP mới = AVG2 x 1.01 = 100.4925 (< close 100.7 < TP cũ 101): TP đặt lại thấy sổ lệnh ở close -> khớp ngay ở close
    ps = _run("LONG", [(100.0, 100.9, 98.8, 100.7)], "ohlc", take_profit_rate=1.0)
    assert ps[0].layers == 2 and ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(100.7)


def test_short_replaced_tp_already_in_the_money_at_close_fills_at_close():
    # DCA @101 ở H, TP mới = AVG2_S x 0.99 = 99.4925 (> close 99.3): khớp ở close
    ps = _run("SHORT", [(100.0, 101.2, 99.1, 99.3)], "ohlc", take_profit_rate=1.0)
    assert ps[0].layers == 2 and ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(99.3)


def test_replaced_tp_not_in_the_money_at_close_stays_open():
    # close 100.2 < TP mới 100.4925 -> vẫn mở; nến phẳng cuối để cả bốn cài đặt cùng đóng nốt ở 100.2
    ps = _run("LONG", [(100.0, 100.9, 98.8, 100.2), (100.2, 100.2, 100.2, 100.2)], "ohlc", take_profit_rate=1.0)
    assert ps[0].layers == 2 and ps[0].status.name == "CANCEL"


# ─── 5. trailing theo từng chặng ────────────────────────────────────────────
def test_long_trailing_peak_runs_per_leg_ohlc():
    # H 103 trước, rồi rơi xuống 99.5: trailing 1% từ đỉnh 103 = 101.97 bị xuyên ngay trong nến, khớp ở mức đó
    ps = _run("LONG", [(100.0, 103.0, 99.5, 102.0)], "ohlc", trailing_stop=1.0, dca_max_layers=0)
    assert ps[0].close_reason == "Trailing stop" and ps[0].close_price == pytest.approx(103.0 * 0.99)


def test_long_trailing_adaptive_low_first_no_exit_then_exit_next_bar():
    # L trước (dùng đỉnh cũ 100 -> mức 99, L = 99.5 chưa chạm), sau đó H 103, C 102 > 101.97: nến này không thoát
    ps = _run("LONG", [(100.0, 103.0, 99.5, 102.0), (102.0, 102.0, 101.0, 101.0)], "adaptive", trailing_stop=1.0, dca_max_layers=0)
    assert ps[0].close_reason == "Trailing stop" and ps[0].close_price == pytest.approx(103.0 * 0.99)


def test_long_trailing_activation_checked_per_leg():
    ps = _run("LONG", [(100.0, 103.0, 99.5, 102.0), (102.0, 102.0, 102.0, 102.0)], "ohlc", trailing_stop=1.0, trailing_activation_pct=5.0, dca_max_layers=0)
    assert ps[0].status.name == "CANCEL"        # lãi tại đỉnh 3% < 5%: trailing chưa bật


def test_short_trailing_peak_runs_per_leg():
    # short: đáy chạy 100 -> 97 (chặng L), C 98.5 vượt trailing 1% từ đáy 97 = 97.97 -> khớp đúng ở mức đó
    ps = _run("SHORT", [(100.0, 100.5, 97.0, 98.5)], "ohlc", trailing_stop=1.0, dca_max_layers=0)
    assert ps[0].close_reason == "Trailing stop" and ps[0].close_price == pytest.approx(97.0 * 1.01)
