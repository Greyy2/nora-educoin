"""
Test xác minh cơ chế định cỡ (Sizing Mechanism Contract) trong Nora Coin:
1. Chứng minh: Khi sizing="margin_pct", qty hoàn toàn độc lập với stop_loss_rate (sizing theo % vốn cố định).
2. Chứng minh: Khi sizing="risk", qty co giãn tỉ lệ nghịch với stop_loss_rate (nhân đôi SL -> giảm 1/2 qty).
3. Chứng minh: Default fallback của build_params khi không có key 'sizing' là 'margin_pct' với order_size_pct=100%.
"""
import sys
from pathlib import Path
import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))

from backend.analys.param.params import build_params, BASE_POSITION
from backend.analys.position import position_size as policy

def test_build_params_default_sizing_fallback():
    """Khi không truyền 'sizing', build_params fallback về 'margin_pct' và order_size_pct=100%."""
    bp = build_params("test", {}, "entry", {"market": "perp"}, "cex")
    assert bp.sizing == "margin_pct"
    assert bp.order_size_pct == 100.0
    assert bp.risk_per_trade_pct == 0.5  # default từ position.get("risk_per_trade_pct") or 0.5

def test_margin_pct_sizing_does_not_scale_with_stop_loss():
    """Trong chế độ margin_pct (hiện tại), đổi SL gấp đôi thì margin/notional/qty KHÔNG đổi."""
    eq = 10000.0
    price = 27000.0
    
    bp_sl25 = build_params("test", {}, "entry", {"market": "perp", "stop_loss_rate": 2.5, "risk_per_trade_pct": 0.25}, "cex")
    bp_sl50 = build_params("test", {}, "entry", {"market": "perp", "stop_loss_rate": 5.0, "risk_per_trade_pct": 0.25}, "cex")
    
    assert bp_sl25.sizing == "margin_pct"
    assert bp_sl50.sizing == "margin_pct"
    
    m25 = policy.flat_margin(eq, bp_sl25.order_size_pct)
    m50 = policy.flat_margin(eq, bp_sl50.order_size_pct)
    
    # Ký quỹ và notional bằng nhau (100% equity)
    assert m25 == m50 == 10000.0
    qty25 = (m25 * bp_sl25.leverage) / price
    qty50 = (m50 * bp_sl50.leverage) / price
    assert qty25 == qty50
    
    # Lỗ khi dính SL tăng gấp đôi và vượt xa mục tiêu 25 USDT
    loss25 = qty25 * (price * 0.025)
    loss50 = qty50 * (price * 0.050)
    assert loss25 == 250.0  # gấp 10 lần 25 USDT
    assert loss50 == 500.0  # gấp 20 lần 25 USDT

def test_risk_sizing_halves_qty_when_stop_loss_doubles():
    """Khi bật sizing='risk', tăng gấp đôi stop_loss_rate sẽ giảm kích thước lệnh xấp xỉ một nửa và giữ mức lỗ tại SL ~ rủi ro mục tiêu."""
    eq = 10000.0
    price = 27000.0
    
    bp_sl25 = build_params("test", {}, "entry", {"market": "perp", "sizing": "risk", "stop_loss_rate": 2.5, "risk_per_trade_pct": 0.25}, "cex")
    bp_sl50 = build_params("test", {}, "entry", {"market": "perp", "sizing": "risk", "stop_loss_rate": 5.0, "risk_per_trade_pct": 0.25}, "cex")
    
    assert bp_sl25.sizing == "risk"
    assert bp_sl50.sizing == "risk"
    
    m25, lev25, _ = policy.risk_margin(eq, bp_sl25.risk_per_trade_pct, bp_sl25.max_notional_pct, 2.5, bp_sl25.fee_rate, 0.0, None, True, bp_sl25.leverage, bp_sl25.maintenance_margin_rate, bp_sl25.leverage, 1.0)
    m50, lev50, _ = policy.risk_margin(eq, bp_sl50.risk_per_trade_pct, bp_sl50.max_notional_pct, 5.0, bp_sl50.fee_rate, 0.0, None, True, bp_sl50.leverage, bp_sl50.maintenance_margin_rate, bp_sl50.leverage, 1.0)
    
    notional25 = m25 * lev25
    notional50 = m50 * lev50
    qty25 = notional25 / price
    qty50 = notional50 / price
    
    # Tỷ lệ qty50 / qty25 phải xấp xỉ 0.5 (giảm một nửa)
    ratio = qty50 / qty25
    assert 0.48 <= ratio <= 0.52, f"Tỷ lệ khi nhân đôi SL phải xấp xỉ 0.5, got {ratio}"
    
    # Mức lỗ thực tế tại SL được kiểm soát sát mức 25 USDT (± 1 USDT do phí)
    loss25 = notional25 * 0.025
    loss50 = notional50 * 0.050
    assert abs(loss25 - 25.0) < 1.5
    assert abs(loss50 - 25.0) < 1.5

def test_compiler_warns_on_dead_risk_config_and_leverage():
    """Trình biên dịch phải sinh warning khi khai báo risk_per_trade_pct mà thiếu sizing='risk', hoặc leverage > 10."""
    from backend.analys.alpha.code.compile import compile_code
    
    # 1. Khai báo risk_per_trade_pct nhưng thiếu sizing='risk'
    code_dead_risk = """class DeadRiskAlpha(NoraStrategy):
    timeframe = '24h'
    risk_per_trade_pct = 0.25
    stop_loss_rate = 2.5
    def on_bar(self):
        self.buy(close > open)
"""
    prog1 = compile_code(code_dead_risk)
    assert any("không khai báo 'sizing = \"risk\"'" in w for w in prog1.warnings), f"Thiếu cảnh báo sizing: {prog1.warnings}"
    
    # 2. Khai báo đòn bẩy > 10x
    code_high_lev = """class HighLevAlpha(NoraStrategy):
    timeframe = '24h'
    sizing = 'risk'
    leverage = 20
    def on_bar(self):
        self.buy(close > open)
"""
    prog2 = compile_code(code_high_lev)
    assert any("vượt quá trần Master Risk" in w for w in prog2.warnings), f"Thiếu cảnh báo leverage: {prog2.warnings}"

def test_full_pipeline_alpha_to_nautilus_ledger_risk_scaling_and_min_lot():
    """Đi hết đường: Alpha code -> build_plan -> NautilusRun -> Ledger.
    1. Khi sizing='risk', gấp đôi SL thì qty giảm một nửa.
    2. Khi SL quá rộng khiến qty < lot tối thiểu (min_lot=0.01 BTC), lệnh bị từ chối an toàn.
    """
    import numpy as np
    import pandas as pd
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.code.plan import build_plan
    from backend.analys.position import SlotSpec
    from backend.models.models import PositionType
    from backend.core.backtest import NautilusRun
    from backend.analys.alpha import RiskConfig
    from tests.test_execution_realism_fixtures import SimpleStubDataSource
    
    # Fixture nến: nến 0 kích hoạt tín hiệu buy, nến 1 khớp tại open
    times = [0, 86_400_000, 2 * 86_400_000]
    opens = [25000.0, 27000.0, 27500.0]
    highs = [25500.0, 28000.0, 28000.0]
    lows = [24500.0, 26500.0, 27000.0]
    closes = [25200.0, 27800.0, 27600.0]
    vols = [100.0, 100.0, 100.0]
    
    symbol = "BTC-USDT-SWAP"
    # Dùng lot_sz="0.001" để kiểm tra tỷ lệ scaling toán học chính xác không bị méo bởi bước làm tròn quá thô
    ds = SimpleStubDataSource(symbol, "24h", times, opens, highs, lows, closes, vols, tick_sz="0.1", lot_sz="0.001")
    
    # ── Kịch bản A: SL = 2.5% vs SL = 5.0% với sizing='risk' (0.25% vốn = 25 USDT)
    def run_alpha_with_sl(sl_rate: float, lot_step="0.001"):
        ds_local = SimpleStubDataSource(symbol, "24h", times, opens, highs, lows, closes, vols, tick_sz="0.1", lot_sz=lot_step)
        code = f"""class TestRiskAlpha(NoraStrategy):
    timeframe = '24h'
    sizing = 'risk'
    risk_per_trade_pct = 0.25
    stop_loss_rate = {sl_rate}
    exit_unit = 'pct'
    leverage = 1.0
    def on_bar(self):
        self.buy(close > open)
"""
        prog = compile_code(code)
        plan = build_plan(prog, ["BTC"], position=prog.position_overrides, run_frame="24h")
        st = plan.strategies[0]
        # Match ở bar 0, vào ở bar 1
        match_arr = np.array([True, False, False], dtype=bool)
        stop_arr = np.array([False, False, False], dtype=bool)
        bp = build_params(st["id"], {"type": "LONG", "match": [], "stop": []}, "LONG", st["position"], "cex")
        slot = SlotSpec(account_id=0, campaign_id=0, symbol=symbol, flow_name=st["id"], params=bp, pos_type=PositionType.LONG, initial_capital=10_000.0)
        book = {"symbol": symbol, "data": {"t": np.array(times, dtype=np.int64)}, "entries": [{"strategy": st["id"], "slot": slot, "match": match_arr, "stop": stop_arr, "vol": None}]}
        risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0)
        res = NautilusRun(books=[book], initial_capital=10_000.0, risk=risk, trade_start_ts=0, end_ts=2*86_400_000, base_frame="24h", close_at_end=True, data=ds_local, execution_target="next_open").run()
        orders = [o for o in res["orders"] if o.order_type.name == "BUY"]
        if not orders:
            return 0.0
        return float(orders[0].qty)

    # 1. Đo với lot_sz=0.001: qty lý thuyết 0.037 -> 0.037, 0.0185 -> 0.018 (tỷ lệ xấp xỉ 0.5)
    qty_sl25 = run_alpha_with_sl(2.5, lot_step="0.001")
    qty_sl50 = run_alpha_with_sl(5.0, lot_step="0.001")
    assert qty_sl25 > 0 and qty_sl50 > 0
    ratio = qty_sl50 / qty_sl25
    assert 0.45 <= ratio <= 0.55, f"Tỷ lệ qty với lot_sz=0.001 phải ~0.5, got {ratio} (qty25={qty_sl25}, qty50={qty_sl50})"

    # 2. Đo hiệu ứng lượng tử hoá khi sàn yêu cầu lot_sz=0.01:
    # 0.0370 làm tròn xuống 0.030, 0.0185 làm tròn xuống 0.010
    qty25_coarse = run_alpha_with_sl(2.5, lot_step="0.01")
    qty50_coarse = run_alpha_with_sl(5.0, lot_step="0.01")
    assert qty25_coarse == 0.03
    assert qty50_coarse == 0.01

    # ── Kịch bản B: SL quá rộng khiến qty < lot tối thiểu 0.01 BTC (Ví dụ SL = 15% -> risk 25 / (27000*0.15) = 0.0061 BTC < 0.01)
    ds_coarse = SimpleStubDataSource(symbol, "24h", times, opens, highs, lows, closes, vols, tick_sz="0.1", lot_sz="0.01")
    code_huge_sl = """class HugeSlAlpha(NoraStrategy):
    timeframe = '24h'
    sizing = 'risk'
    risk_per_trade_pct = 0.25
    stop_loss_rate = 15.0
    exit_unit = 'pct'
    leverage = 1.0
    def on_bar(self):
        self.buy(close > open)
"""
    prog_huge = compile_code(code_huge_sl)
    plan_huge = build_plan(prog_huge, ["BTC"], position=prog_huge.position_overrides, run_frame="24h")
    st_huge = plan_huge.strategies[0]
    bp_huge = build_params(st_huge["id"], {"type": "LONG", "match": [], "stop": []}, "LONG", st_huge["position"], "cex")
    slot_huge = SlotSpec(account_id=0, campaign_id=0, symbol=symbol, flow_name=st_huge["id"], params=bp_huge, pos_type=PositionType.LONG, initial_capital=10_000.0)
    book_huge = {"symbol": symbol, "data": {"t": np.array(times, dtype=np.int64)}, "entries": [{"strategy": st_huge["id"], "slot": slot_huge, "match": np.array([True, False, False]), "stop": np.array([False, False, False]), "vol": None}]}
    res_huge = NautilusRun(books=[book_huge], initial_capital=10_000.0, risk=RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=3.0, kill_switch_dd_pct=50.0), trade_start_ts=0, end_ts=2*86_400_000, base_frame="24h", close_at_end=True, data=ds_coarse, execution_target="next_open").run()
    
    # Lệnh bị reject do < min_quantity (0.01 BTC) -> 0 lệnh mở!
    orders_huge = [o for o in res_huge["orders"] if o.order_type.name == "BUY"]
    assert len(orders_huge) == 0, f"Lệnh có qty < min_lot (0.01) phải bị reject, nhưng lại submit {len(orders_huge)} lệnh!"

