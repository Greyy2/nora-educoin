"""Kiểm tra đồng nhất khung chạy (B7): thiếu run_frame -> Nhanh = khung tín hiệu; run_frame="1m" -> Chuẩn."""
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.alpha.compile import compile_code
from backend.alpha.plan import build_plan, resolve_run_frame
from backend.main import app
from backend.analys.param import DEFAULT_SIGNAL_FRAME, STANDARD_FRAME
from backend.alpha.strategies import sample_cache_key, sample_run_spec


DSL_CODE_1H = """
class TestStrat1h(SimpleAlgorithm):
    timeframe = "1h"
    def on_bar(self):
        c = self.data.pv_close
        self.set_positions(c > c.shift(1), position=1)
"""

DSL_CODE_4H = """
class TestStrat4h(SimpleAlgorithm):
    timeframe = "4h"
    def on_bar(self):
        c = self.data.pv_close
        self.set_positions(c > c.shift(1), position=1)
"""

NATIVE_CODE = """
from nautilus_trader.trading.strategy import Strategy

class MyNativeStrategy(Strategy):
    timeframe = "4h"
    def on_start(self):
        pass
"""


def test_dsl_missing_run_frame_uses_signal_timeframe():
    """(a) DSL thiếu run_frame -> plan.base_frame == program.timeframe."""
    prog1h = compile_code(DSL_CODE_1H)
    plan1h = build_plan(prog1h, ["BTC@perp"])
    assert plan1h.base_frame == "1h"

    prog4h = compile_code(DSL_CODE_4H)
    plan4h = build_plan(prog4h, ["BTC@perp"])
    assert plan4h.base_frame == "4h"


def test_native_missing_run_frame_uses_signal_timeframe():
    """(b) Native thiếu run_frame -> resolve_run_frame dùng timeframe của program."""
    prog = compile_code(NATIVE_CODE)
    bf = resolve_run_frame(None, getattr(prog, "timeframe", None))
    assert bf == "4h"


def test_explicit_standard_run_frame_is_1m():
    """(c) run_frame='1m' -> 1m (Chế độ Chuẩn)."""
    prog1h = compile_code(DSL_CODE_1H)
    plan = build_plan(prog1h, ["BTC@perp"], run_frame=STANDARD_FRAME)
    assert plan.base_frame == "1m"

    bf = resolve_run_frame("1m", "4h")
    assert bf == "1m"


def test_sample_run_spec_and_cache_key_use_same_frame():
    """(d) sample_run_spec + cache_key dùng cùng khung thực chạy."""
    sample = {
        "key": "test_kema",
        "timeframe": "4h",
        "code": DSL_CODE_4H,
        "symbols": ["BTC-USDT-SWAP"],
    }
    spec = sample_run_spec(sample)
    assert spec["run_frame"] == "4h"

    # cache key tính theo spec thực chạy
    k1 = sample_cache_key(sample["code"], spec)
    assert isinstance(k1, str) and len(k1) == 64


def test_api_custom_backtest_receives_run_frame():
    """(e) API /api/studio/custom/backtest nhận run_frame đúng hoặc None khi thiếu."""
    client = TestClient(app)
    received = {}

    def fake_launch(kind, params, run_dir=None):
        received.update(params)
        return "job_test_123"

    with patch("backend.jobs.runner.launch", side_effect=fake_launch):
        # 1. Chế độ Nhanh (không gửi run_frame)
        payload_fast = {
            "code": DSL_CODE_1H,
            "start": "2024-01-01",
            "end": "2024-01-10",
        }
        res = client.post("/api/studio/custom/backtest", json=payload_fast)
        assert res.status_code == 200
        assert received.get("run_frame") is None

        # 2. Chế độ Chuẩn (gửi run_frame="1m")
        payload_std = {
            "code": DSL_CODE_1H,
            "start": "2024-01-01",
            "end": "2024-01-10",
            "run_frame": "1m",
        }
        res2 = client.post("/api/studio/custom/backtest", json=payload_std)
        assert res2.status_code == 200
        assert received.get("run_frame") == "1m"
