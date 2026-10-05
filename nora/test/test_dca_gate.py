"""DCA có điều kiện: tầng DCA chỉ khớp khi điều kiện dồn (giá trị ở nến đã đóng trước) đang đúng; không có điều kiện -> như cũ."""
from backend.core.execute.models import PositionType
from backend.core.execute.tracker import PositionTracker
from backend.core.params.builder import build_params
from backend.core.strategy import book as sb

POS = {"market": "perp", "leverage": 3, "exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 10.0, "stop_loss_rate": 20.0,
       "take_profit_rate": 0.0, "dca_step_pct": 1.0, "dca_max_layers": 3, "dca_size_multiplier": 1.0, "timeout": 0}


def _tracker(gate):
    flow = {"type": "LONG", "match": [{"condition": [[[1, ">", 0]]]}], "stop": [], "dca": gate}
    return PositionTracker(0, 0, "X", "LONG_t", build_params("LONG_t", flow, "LONG", POS, "cex"), PositionType.LONG, 10000.0)


def _drive(tr, gates):
    """Nến 0: tín hiệu vào; nến 1: vào lệnh ở 100; các nến sau giảm 1,2% mỗi nến (mỗi nến chạm một mức DCA)."""
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False, dca_gate=gates[0])
    px = 100.0
    for i, g in enumerate(gates[1:], start=1):
        lo = px * 0.988
        tr.on_bar(i * 60_000, px, px, lo, lo, entry_signal=False, stop_signal=False, dca_gate=g)
        px = lo
    return tr.layer_count


def test_no_gate_fills_every_layer():
    assert _drive(_tracker([]), [True] * 6) == 4                       # lệnh đầu + 3 tầng


def test_gate_closed_blocks_layers_and_reopens():
    gate = [{"condition": [[[1, ">", 0]]]}]
    # điều kiện tắt từ nến tín hiệu: nến vào lệnh và các nến sau đều không dồn dù giá chạm mức
    assert _drive(_tracker(gate), [False] * 6) == 1
    # đúng ở nến tín hiệu -> nến vào lệnh được dồn một tầng; tắt ở cuối nến 1 -> nến 2, 3 không dồn
    assert _drive(_tracker(gate), [True, False, False, False]) == 2
    # bật lại ở cuối nến 3 -> nến 4 dồn tiếp: giá đã đi xa nên khớp 2 tầng trong nến 4 (tầng đầu ở giá mở do gap, tầng sau ở mức)
    assert _drive(_tracker(gate), [True, False, False, True, True]) == 4


def test_dca_legs_materialize_gate_and_validate():
    from backend.optimize.funnel import generate as gen
    for cid in ("dca_long", "dca_short"):
        c = sb.BY_ID[cid]
        st = sb.materialize(c, sb.schema_defaults(c))
        assert st["dca"] and st["position"]["dca_max_layers"] == 3 and st["position"]["exit_unit"] == "atr"
        prm = {k: v for k, v in sb.schema_defaults(c).items() if k != "risk_per_trade_pct"}   # phễu cố định rủi ro/lệnh
        assert gen.validate_alpha(c, prm, "schema", "1h") is None
    cat = {s["id"]: s for s in sb.STRATEGIES}
    assert cat["dca"]["legs"] == {"LONG": "dca_long", "SHORT": "dca_short"} and not cat["dca"].get("coming")


def test_limit_through_requires_price_beyond_level_and_fills_at_limit():
    """limit_through_pct: tầng DCA / chốt lời chỉ khớp khi giá đi QUA mức; khớp ở đúng giá đặt (không lấy giá tốt hơn)."""
    def run(through, low):
        pos = {**POS, "limit_through_pct": through}
        flow = {"type": "LONG", "match": [{"condition": [[[1, ">", 0]]]}], "stop": []}
        tr = PositionTracker(0, 0, "X", "LONG_t", build_params("LONG_t", flow, "LONG", pos, "cex"), PositionType.LONG, 10000.0)
        tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
        tr.on_bar(60_000, 100, 100, low, low, entry_signal=False, stop_signal=False)   # mức DCA đầu = 99
        return tr
    assert run(0.0, 99.0).layer_count == 2                     # chạm là khớp
    assert run(0.2, 99.0).layer_count == 1                     # chỉ chạm: chưa khớp
    tr = run(0.2, 98.7)                                        # đi qua 99 × (1 − 0,2%) = 98,80 -> khớp ở 99
    assert tr.layer_count == 2 and abs(tr.last_fill - 99.0 * (1 + tr.slippage_rate)) < 1e-9     # giá đặt 99 (+ trượt giá như mọi lệnh)
