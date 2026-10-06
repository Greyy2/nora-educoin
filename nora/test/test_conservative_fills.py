"""(Từ 2026-10-06 lần 2 các quy tắc này chỉ còn áp cho `intrabar_path="adverse_first"`; mặc định mới "ohlc" khớp NautilusTrader.)
Quy tắc khớp BẢO THỦ có chủ đích (2026-10-06, duyệt sau test chéo engine với NautilusTrader — xem adr-p6-unified-execution.md):

1. SL CŨ sau fill DCA: lệnh SL đang nằm trên sàn không dời được ngay, nên trong phần còn lại của nến mức SL dùng là mức lúc tầng DCA đầu
   tiên của nến khớp; SL tính từ avg mới chỉ có hiệu lực từ nến sau.
2. Lệnh LIMIT chờ sẵn (tầng DCA, chốt lời) khớp ĐÚNG ở mức đặt kể cả khi nến mở cửa gap qua mức; stop-market (SL) vẫn khớp ở open.

Mỗi kịch bản chạy qua BỐN cài đặt phải ra cùng kết quả: PositionTracker (Python), PositionManager + SimVenue (đường sự kiện),
RefPositionTracker (oracle đóng băng) và kernel numba (qua BacktestEngine). Giá/phí chọn để tính tay: phí = trượt = 0, spot (long) / perp đòn bẩy 1 (short),
ký quỹ mỗi tầng 20% vốn, một tầng DCA bước 1%, tín hiệu vào ở nến 4 -> vào lệnh ở open nến 5 (= nến đầu của kịch bản).
"""
import pytest

from backend.core.execute.account import Account
from backend.core.execute.manager import PositionManager
from backend.core.execute.models import PositionType
from backend.core.execute.sim_venue import SimVenue
from backend.core.execute.tracker import PositionTracker
from backend.core.params.builder import build_params
from reference_engine import RefCapitalLedger, RefPositionTracker
from test_signals_strategies import M, T0, _engine, _signal_at

import pandas as pd

FLAT = [(100.0, 100.0, 100.0, 100.0)] * 5      # nến 0..4: phẳng; tín hiệu vào ở nến 4
IMPLS = ("tracker", "event", "reference", "kernel")


def _pos(side, **kw):
    p = {"order_size_pct": 20.0, "dca_step_pct": 1.0, "dca_max_layers": 1, "fee_rate": 0.0, "maker_fee_rate": 0.0, "slippage_rate": 0.0,
         "market": "spot" if side == "LONG" else "perp", "leverage": 1,
         "intrabar_path": "adverse_first"}      # quy tắc bảo thủ 2026-10-06 gắn với đường cũ (mặc định mới là "ohlc": test_intrabar_path.py)
    p.update(kw)
    return p


def _params(side, pos):
    return build_params(f"{side}_f", {"match": [], "stop": []}, side, pos, "cex")


def _drive(actor, bars):
    closed = []
    for i, (o, h, l, c) in enumerate(bars):
        pos = actor.on_bar(T0 + i * M, o, h, l, c, entry_signal=(i == 4), stop_signal=False)
        if pos is not None:
            closed.append(pos)
    last = len(bars) - 1
    end = actor.force_close(T0 + last * M, bars[-1][3])
    if end is not None:
        closed.append(end)
    return closed


def _run(impl, side, bars, **pos):
    """Chạy kịch bản bằng một cài đặt; trả danh sách vị thế đã đóng (cuối kịch bản đóng nốt ở close nến cuối)."""
    bars = FLAT + list(bars)
    pt = PositionType.LONG if side == "LONG" else PositionType.SHORT
    pos = _pos(side, **pos)
    if impl == "kernel":
        df = pd.DataFrame({"open_time": T0 + pd.RangeIndex(len(bars)).to_numpy().astype("int64") * M,
                           "open": [b[0] for b in bars], "high": [b[1] for b in bars], "low": [b[2] for b in bars],
                           "close": [b[3] for b in bars], "volume": 1.0})
        eng = _engine(df, _signal_at(df, 4), side=side, **pos)
        eng.run()
        return eng.closed_positions
    params = _params(side, pos)
    if impl == "tracker":
        return _drive(PositionTracker(0, 0, "T", "f", params, pt, initial_capital=10000.0), bars)
    if impl == "reference":
        return _drive(RefPositionTracker(0, 0, "T", "f", params, pt, initial_capital=10000.0, ledger=RefCapitalLedger(10000.0)), bars)
    acct = Account(10000.0)
    tr = PositionTracker(0, 0, "T", "f", params, pt, initial_capital=10000.0, ledger=acct)
    return _drive(PositionManager(tr, SimVenue(), slot=0, account=acct, events=[]), bars)


def _all(side, bars, **pos):
    """Chạy cả bốn cài đặt, khẳng định chúng khớp nhau từng trường; trả kết quả của tracker."""
    res = {impl: _run(impl, side, bars, **pos) for impl in IMPLS}
    key = lambda ps: [(p.status.name, p.layers, p.close_price, p.avg_price, p.qty, p.real_pnl) for p in ps]  # noqa: E731
    for impl in IMPLS[1:]:
        assert key(res[impl]) == key(res["tracker"]), f"{impl} lệch tracker"
    return res["tracker"]


# ─── 1. SL cũ sau fill DCA trong cùng nến ───────────────────────────────────
def test_long_old_sl_fires_after_dca_in_same_bar():
    # nến đi 100 -> 97.8: chạm tầng DCA @99, rồi mức SL CŨ 98 (= 100 x 0.98) trước SL mới (avg x 0.98 = 97.51, chưa chạm)
    ps = _all("LONG", [(100.0, 100.0, 97.8, 97.8)], stop_loss_rate=2.0)
    assert len(ps) == 1 and ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].close_price == pytest.approx(98.0)


def test_long_new_sl_only_from_next_bar_and_survives_between():
    avg = 2 / (1 / 100 + 1 / 99)
    sl_new = avg * 0.98                                    # ~97.5075: THẤP hơn SL cũ 98
    ps = _all("LONG", [(100.0, 100.0, 98.5, 98.6),        # DCA @99 khớp, SL cũ 98 chưa chạm -> còn sống
                       (98.6, 98.6, 97.9, 98.0),          # xuyên SL cũ 98 nhưng chưa tới SL mới -> SL mới đã có hiệu lực: còn sống
                       (98.0, 98.0, 97.4, 97.4)],         # tới SL mới -> đóng ở SL mới
              stop_loss_rate=2.0)
    assert len(ps) == 1 and ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].avg_price == pytest.approx(avg)
    assert ps[0].close_price == pytest.approx(sl_new)


def test_short_old_sl_fires_after_dca_in_same_bar():
    ps = _all("SHORT", [(100.0, 102.2, 100.0, 102.2)], stop_loss_rate=2.0)   # DCA @101 rồi SL cũ 102 (SL mới = avg x 1.02 = 102.51)
    assert len(ps) == 1 and ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].close_price == pytest.approx(102.0)


def test_short_new_sl_only_from_next_bar_and_survives_between():
    avg = 2 / (1 / 100 + 1 / 101)
    ps = _all("SHORT", [(100.0, 101.5, 100.0, 101.4),
                        (101.4, 102.1, 101.4, 102.0),
                        (102.0, 102.6, 102.0, 102.6)],
              stop_loss_rate=2.0)
    assert len(ps) == 1 and ps[0].layers == 2 and ps[0].status.name == "SL"
    assert ps[0].close_price == pytest.approx(avg * 1.02)


def test_sl_before_any_dca_unchanged():
    # SL 0.5% (mức 99.5) nằm TRÊN tầng DCA @99: SL chạm trước, không có DCA nào khớp
    ps = _all("LONG", [(100.0, 100.0, 98.0, 98.0)], stop_loss_rate=0.5)
    assert ps[0].layers == 1 and ps[0].close_price == pytest.approx(99.5)


# ─── 2. Gap xuyên lệnh limit chờ sẵn ────────────────────────────────────────
def test_long_gap_below_resting_dca_fills_at_limit_level():
    ps = _all("LONG", [(100.0, 100.0, 100.0, 100.0), (98.0, 98.2, 97.9, 98.0)])   # nến 2 mở ở 98 < tầng DCA 99
    assert ps[0].layers == 2
    assert ps[0].avg_price == pytest.approx(2 / (1 / 100 + 1 / 99))            # khớp @99 (mức), KHÔNG phải @98 (open)


def test_short_gap_above_resting_dca_fills_at_limit_level():
    ps = _all("SHORT", [(100.0, 100.0, 100.0, 100.0), (102.0, 102.1, 101.8, 102.0)])
    assert ps[0].layers == 2
    assert ps[0].avg_price == pytest.approx(2 / (1 / 100 + 1 / 101))


def test_long_gap_above_resting_tp_fills_at_tp_level():
    ps = _all("LONG", [(100.0, 100.0, 100.0, 100.0), (102.0, 102.5, 101.9, 102.2)], take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(101.0)    # không phải open 102


def test_short_gap_below_resting_tp_fills_at_tp_level():
    ps = _all("SHORT", [(100.0, 100.0, 100.0, 100.0), (98.0, 98.1, 97.5, 97.8)], take_profit_rate=1.0, dca_max_layers=0)
    assert ps[0].status.name == "TP" and ps[0].close_price == pytest.approx(99.0)


@pytest.mark.parametrize("side, bars, sl_fill", [
    ("LONG", [(100.0, 100.0, 100.0, 100.0), (96.0, 96.5, 95.0, 95.5)], 96.0),
    ("SHORT", [(100.0, 100.0, 100.0, 100.0), (104.0, 105.0, 103.5, 104.5)], 104.0),
])
def test_gap_through_stop_market_sl_still_fills_at_open(side, bars, sl_fill):
    ps = _all(side, bars, stop_loss_rate=2.0, dca_max_layers=0)
    assert ps[0].status.name == "SL" and ps[0].close_price == pytest.approx(sl_fill)
