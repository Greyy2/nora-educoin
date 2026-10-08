"""P9.4b T4 — SlotSpec (core/params.py) chuẩn hoá tham số y hệt PositionTracker.__init__: mọi nhánh ValueError / TypeError cho CÙNG ngoại lệ + thông báo,
mọi trường dẫn xuất khớp tracker; id lệnh/vị thế rút từ models.next_id (một dãy với backtest.next_id: tracker dùng đúng hàm này)."""
import re

import pytest

from backend.core import backtest as bt
from backend.core import models
from backend.core.backtest import SlotDriver, pack_slots, PositionTracker
from backend.core.models import PositionType
from backend.core.params import StrategyParams
from backend.core.position_size import SlotSpec

L, S = PositionType.LONG, PositionType.SHORT
AST = {"ast": {"match": [{"condition": [1, 2]}, {"condition": [3]}], "stop": [{"condition": [4]}], "dca": [{"condition": [5]}]}}


def _p(**kw):
    kw.setdefault("name", "LONG_t")
    kw.setdefault("extra", {"ast": {"match": [], "stop": []}})
    return StrategyParams(**kw)


# (kwargs StrategyParams, pos_type, regex của thông báo, loại ngoại lệ) — mỗi nhánh raise của __init__ + vài lỗi chuyển kiểu
ERR_CASES = [
    (dict(market="futures"), L, re.escape("market phải là 'spot' hoặc 'perp', nhận 'futures'"), ValueError),
    (dict(market="spot"), S, re.escape("Flow 'LONG_t': thị trường spot không bán khống được — dùng market='perp' cho SHORT."), ValueError),
    (dict(market="perp", stop_fill="worst"), L, re.escape("stop_fill phải là 'level' hoặc 'extreme', nhận 'worst'"), ValueError),
    (dict(market="perp", intrabar_path="zigzag"), L, re.escape("intrabar_path phải là một trong ('ohlc', 'adaptive', 'adverse_first'), nhận 'zigzag'"), ValueError),
    (dict(market="perp", exit_unit="usd"), L, re.escape("exit_unit phải là 'pct' hoặc 'atr', nhận 'usd'"), ValueError),
    (dict(market="perp", sizing="kelly"), L, re.escape("sizing phải là 'margin_pct' hoặc 'risk', nhận 'kelly'"), ValueError),
    (dict(market="perp", sizing="risk", stop_loss_rate=0.0), L, re.escape("Flow 'LONG_t': sizing='risk' cần stop_loss_rate > 0 (rủi ro đo tại SL)."), ValueError),
    (dict(dca_steps=[1.0, -2.0]), L, re.escape("Bước DCA và hệ số khối lượng phải > 0"), ValueError),
    (dict(dca_steps=[1.0], dca_multipliers=[0.0]), L, re.escape("Bước DCA và hệ số khối lượng phải > 0"), ValueError),
    (dict(dca_steps=["x"]), L, "could not convert string to float", ValueError),
    (dict(market="perp", leverage="abc"), L, "could not convert string to float", ValueError),
    (dict(timeout=[5]), L, "int", TypeError),
    (dict(fee_rate=object()), L, "float", TypeError),
]


def _both(kw, pos):
    out = []
    for build in (lambda p: SlotSpec(0, 0, "X", "LONG_t", p, pos, 10000.0),
                  lambda p: PositionTracker(0, 0, "X", "LONG_t", p, pos, initial_capital=10000.0)):
        try:
            build(_p(**kw))
            out.append(None)
        except Exception as e:   # noqa: BLE001
            out.append((type(e), str(e)))
    return out


@pytest.mark.parametrize("kw,pos,pat,exc", ERR_CASES, ids=[str(i) for i in range(len(ERR_CASES))])
def test_error_parity(kw, pos, pat, exc):
    spec_err, trk_err = _both(kw, pos)
    assert spec_err is not None and spec_err[0] is exc and re.search(pat, spec_err[1]), spec_err
    assert spec_err == trk_err                                  # tracker (dựng từ spec) cùng ngoại lệ + thông báo


def test_error_order_first_failure_wins():
    """Nhiều lỗi cùng lúc: nhánh kiểm đầu tiên thắng (market -> spot short -> stop_fill -> intrabar -> exit_unit -> sizing -> risk -> DCA)."""
    kw = dict(market="spot", stop_fill="bad", intrabar_path="bad", exit_unit="bad", sizing="bad", dca_steps=[-1.0])
    assert _both(kw, S)[0][1].startswith("Flow 'LONG_t': thị trường spot")
    kw.update(market="perp")
    assert "stop_fill" in _both(kw, L)[0][1]
    kw.update(stop_fill="level")
    assert "intrabar_path" in _both(kw, L)[0][1]
    kw.update(intrabar_path="ohlc")
    assert "exit_unit" in _both(kw, L)[0][1]
    kw.update(exit_unit="pct")
    assert "sizing" in _both(kw, L)[0][1]
    kw.update(sizing="margin_pct")
    assert "DCA" in _both(kw, L)[0][1]


def test_derived_fields_match_tracker():
    p = _p(market="perp", leverage=5, fee_rate=0.001, maker_fee_rate=None, slippage_rate=0.0003, stop_loss_rate=2.0, take_profit_rate=4.0,
           trailing_stop=1.0, trailing_activation_pct=0.5, timeout=30, cooldown=15, limit_through_pct=0.2, exit_unit="atr", atr_frame="4h",
           atr_period=20, dca_step_pct=1.5, dca_max_layers=3, dca_multipliers=[2.0], max_capital_usage=0.6, order_size_pct=12.0,
           max_open_trades=7, extra=AST)
    sp = SlotSpec(1, 2, "X", "LONG_t", p, L, 5000.0)
    tr = PositionTracker(1, 2, "X", "LONG_t", p, L, initial_capital=5000.0)
    for a in ("market", "leverage", "mmr", "fee_rate", "maker_fee_rate", "slippage_rate", "capital", "capital_usage", "max_capital", "base_sl",
              "base_tp", "base_trail", "base_trail_act", "timeout_ms", "cooldown_ms", "stop_fill", "limit_through", "intrabar_path",
              "exit_unit", "atr_frame", "atr_period", "sizing", "risk_pct", "max_notional_pct", "base_dca_steps", "dca_mults", "max_leverage",
              "pos_leverage", "planned_risk", "unit_pct", "sl_pct", "tp_pct", "trail_pct", "trail_activation_pct", "dca_steps", "order_size_pct",
              "max_open_trades", "match_tree", "stop_tree", "dca_tree", "dca_ok", "is_long", "entry_equity"):
        assert getattr(sp, a) == getattr(tr, a), a
    assert sp.base_dca_steps == [1.5] * 3 and sp.dca_mults == [2.0, 2.0, 2.0] and sp.max_open_trades == 7
    assert sp.match_tree == [1, 2, 3] and sp.stop_tree == [4] and sp.dca_tree == [5] and sp.maker_fee_rate == 0.001
    assert sp.max_capital == 3000.0 and sp.limit_through == 0.2 / 100.0
    P1, PI1, F1, I1 = pack_slots([sp])
    P2, PI2, F2, I2 = pack_slots([tr])
    assert (P1 == P2).all() and (PI1 == PI2).all() and ((F1 == F2) | (F1 != F1)).all() and (I1 == I2).all()


def test_slot_driver_accepts_specs():
    sp = SlotSpec(0, 0, "X", "LONG_t", _p(), L, 10000.0)
    drv = SlotDriver([sp])
    drv[0].on_bar(0, 100, 101, 99, 100, entry_signal=True)
    drv[0].on_bar(60_000, 100, 102, 99, 101)
    assert drv[0].is_open and drv[0].qty > 0 and drv[0].is_long and drv[0].market == "spot"
    assert drv.ledger.initial == 10000.0 and drv[0].position is not None


def test_ids_share_one_sequence():
    assert bt.next_id is models.next_id
    a = models.next_id()
    assert bt.next_id() == a + 1 and models.next_id() == a + 2
