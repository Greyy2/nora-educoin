"""Unit test cho B2 — Giải thích cấu trúc chiến lược Python từ cây biểu thức đã biên dịch (không dùng LLM).

5 dạng tiêu biểu:
1. Cắt nhau (crossed_above / crossed_below)
2. Ngưỡng (crossed_above_value / threshold)
3. Kết hợp logic & / |
4. Duy trì qua n nến (hold_for)
5. Nhiều mức position (nhiều quy tắc set_positions ghi đè)
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import strategies as strategies_router
from backend.core.strategy.pydsl import compile_code, explain_program, explain_report


def test_explain_form_1_crossover():
    """Dạng 1: Cắt nhau giữa giá và đường EMA."""
    code = """
class EmaCross(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema20 = self.feat.ema(self.data.pv_close, 20)
        crossover = self.op.crossed_above(self.data.pv_close, ema20)
        crossunder = self.op.crossed_below(self.data.pv_close, ema20)
        self.set_positions(crossover, 1.0)
        self.set_positions(crossunder, 0.0)
"""
    prog = compile_code(code, register=False)
    exp = explain_program(prog)

    assert len(exp["indicators"]) == 1
    assert exp["indicators"][0]["name"] == "ema"
    assert "EMA" in exp["indicators"][0]["call"]

    assert len(exp["rules"]) == 2
    r1, r2 = exp["rules"][0], exp["rules"][1]
    assert r1["level"] == 1.0 and r1["type"] == "entry_long"
    assert "cắt lên" in r1["action_vi"]
    assert r2["level"] == 0.0 and r2["type"] == "exit"
    assert "cắt xuống" in r2["action_vi"]

    assert any("Khớp ở giá mở cửa" in e["desc"] for e in exp["execution"])
    assert any("Perpetual" in e["desc"] for e in exp["execution"])


def test_explain_form_2_threshold():
    """Dạng 2: Cắt ngưỡng hằng số (RSI cắt lên 30)."""
    code = """
class RsiReversal(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        rsi14 = self.feat.rsi(self.data.pv_close, 14)
        buy_sig = self.op.crossed_above_value(rsi14, 30.0)
        sell_sig = self.op.crossed_below_value(rsi14, 70.0)
        self.set_positions(buy_sig, 1.0)
        self.set_positions(sell_sig, 0.0)
"""
    prog = compile_code(code, register=False)
    exp = explain_program(prog)

    assert any(ind["name"] == "rsi" for ind in exp["indicators"])
    r1, r2 = exp["rules"][0], exp["rules"][1]
    assert "cắt lên mức 30" in r1["action_vi"]
    assert "cắt xuống mức 70" in r2["action_vi"]

    # mô tả SL động theo ATR và đòn bẩy
    assert any("Stop-Loss" in e["desc"] for e in exp["execution"])


def test_explain_form_3_logic_and_or():
    """Dạng 3: Kết hợp logic & và | giữa nhiều điều kiện."""
    code = """
class TrendFilter(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        sma50 = self.feat.sma(self.data.pv_close, 50)
        rsi14 = self.feat.rsi(self.data.pv_close, 14)
        trend_up = self.data.pv_close > sma50
        pullback = rsi14 < 40.0
        cond_in = trend_up & pullback
        self.set_positions(cond_in, 1.0)
"""
    prog = compile_code(code, register=False)
    exp = explain_program(prog)

    assert len(exp["indicators"]) == 2
    names = {ind["name"] for ind in exp["indicators"]}
    assert "sma" in names and "rsi" in names

    r1 = exp["rules"][0]
    assert "VÀ" in r1["action_vi"]
    assert "lớn hơn" in r1["action_vi"]
    assert "nhỏ hơn" in r1["action_vi"]

    # Cảnh báo không có điều kiện thoát
    assert any("không có quy tắc thoát lệnh" in w for w in exp["warnings"])


def test_explain_form_4_hold_for():
    """Dạng 4: Giữ tín hiệu n nến với hold_for."""
    code = """
class BreakoutHold(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        dch = self.feat.donchian_upper(self.data.pv_high, 20)
        breakout = self.op.crossed_above(self.data.pv_close, dch)
        held = self.op.hold_for(breakout, 3)
        self.set_positions(held, 1.0)
"""
    prog = compile_code(code, register=False)
    exp = explain_program(prog)

    assert any(ind["name"] == "donchian_upper" for ind in exp["indicators"])
    r1 = exp["rules"][0]
    assert "duy trì" in r1["action_vi"] and "3 nến" in r1["action_vi"]


def test_explain_form_5_multiple_position_levels():
    """Dạng 5: Nhiều mức vị thế (bậc thang tỷ trọng 50%, 100%, thoát 0%)."""
    code = """
class MultiScale(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema20 = self.feat.ema(self.data.pv_close, 20)
        ema50 = self.feat.ema(self.data.pv_close, 50)
        c1 = self.op.crossed_above(self.data.pv_close, ema20)
        c2 = self.op.crossed_above(self.data.pv_close, ema50)
        c_exit = self.op.crossed_below(self.data.pv_close, ema20)
        self.set_positions(c1, 0.5)
        self.set_positions(c2, 1.0)
        self.set_positions(c_exit, 0.0)
"""
    prog = compile_code(code, register=False)
    exp = explain_program(prog)

    assert len(exp["rules"]) == 3
    assert exp["rules"][0]["level"] == 0.5
    assert any("không đổi khối lượng lệnh" in w for w in exp["warnings"])
    assert exp["rules"][1]["level"] == 1.0
    assert "LONG khi" in exp["rules"][1]["action_vi"]
    assert exp["rules"][2]["level"] == 0.0
    assert "Thoát vị thế" in exp["rules"][2]["action_vi"]


def test_explain_api_endpoint():
    """Test router POST /api/studio/strategies/explain."""
    app = FastAPI()
    app.include_router(strategies_router.router)
    client = TestClient(app)

    code = """
class Demo(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 20)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), 1.0)
        self.set_positions(self.op.crossed_below(self.data.pv_close, ema), 0.0)
"""
    r = client.post("/api/studio/strategies/explain", json={"code": code})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert len(j["indicators"]) == 1
    assert len(j["rules"]) == 2
    assert len(j["execution"]) >= 4

    # Test mã sai trả về ok=False
    r_bad = client.post("/api/studio/strategies/explain", json={"code": "broken code"})
    assert r_bad.status_code == 200
    assert r_bad.json()["ok"] is False
    assert r_bad.json()["error"] is not None


def test_nora_risk_text_follows_actual_position():
    """Câu 'Quản trị rủi ro' của hồ sơ nora chỉ nhắc cơ chế thực sự bật, theo tham số vị thế được gửi."""
    from backend.core.strategy.pydsl import compile_code
    from backend.core.strategy.pydsl.explain import explain_program
    code = ("class S(SimpleAlgorithm):\n    timeframe = '24h'\n    def __algorithm__(self):\n"
            "        c = self.data.pv_close\n        self.set_positions(c < self.feat.sma(c, 20), position=0)\n"
            "        self.set_positions(c > self.feat.sma(c, 20), position=1)\n")
    prog = compile_code(code, register=False)
    risk = lambda pos: next(e["desc"] for e in explain_program(prog, position=pos)["execution"] if e["title"] == "Quản trị rủi ro")
    plain = risk({"stop_loss_rate": 2.0, "atr_frame": "24h"})
    assert "Stop-Loss 2×ATR" in plain and "trailing" not in plain and "Take-Profit" not in plain and "khung 24h" in plain
    trail = risk({"stop_loss_rate": 3.0, "trailing_stop": 3.0})
    assert "trailing stop 3×ATR" in trail
    none = risk({"stop_loss_rate": 0, "cooldown": 0})
    assert none.startswith("Chỉ thoát theo tín hiệu")
