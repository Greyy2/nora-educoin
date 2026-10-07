"""P7 — parity nội bộ: `kema_long` viết bằng DSL Python, hồ sơ `nora`, CÙNG dict vị thế như materialize() -> lệnh, lệnh con và đường vốn TRÙNG TỪNG BIT
với chiến lược lõi (cùng PortfolioEngine). Dữ liệu tổng hợp (luôn chạy) + dữ liệu thật ngắn (bỏ qua khi không có)."""
import os

import pandas as pd
import pytest

import golden_scenarios as gs
from backend.core.strategy import book as sb
from backend.core.strategy.pydsl import compile_code, profiles

KEMA_CODE = '''
class KemaLong(SimpleAlgorithm):
    timeframe = "4h"
    def __algorithm__(self):
        close = self.data.pv_close
        high = self.data.pv_high
        low = self.data.pv_low
        ema = self.feat.ema(close, timeperiod=30)
        atr = self.feat.atr(high, low, close, timeperiod=14)
        kc_up = ema + 2.0 * atr
        kc_dn = ema - 2.0 * atr
        self.set_positions(self.op.crossed_below(close, kc_dn), position=0)
        self.set_positions(self.op.crossed_above(close, kc_up), position=1)
'''


def _core_strategy():
    cand = sb.BY_ID["kema_long"]
    return sb.materialize(cand, sb.schema_defaults(cand))


def _run(strategies, symbols, start_ms, end_ms, trade_start, root):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    with gs.data_root_env(str(root)):
        eng = PortfolioEngine(symbols, strategies, start_ms, end_ms, trade_start_ts=trade_start, risk=RiskConfig.from_dict(sb.RISK),
                              use_cache=False)
        eng.run()
        return gs.canonicalize(eng.get_results())


def _parity(root, symbols, start_ms, end_ms, trade_start):
    core = _core_strategy()
    prog = compile_code(KEMA_CODE)
    plan = profiles.build_plan(prog, "nora", symbols, position=core["position"], strategy_id="kema_long", exact_id=True)
    assert len(plan.strategies) == 1
    assert {k: plan.strategies[0]["position"][k] for k in core["position"]} == core["position"]
    a = _run([core], symbols, start_ms, end_ms, trade_start, root)
    b = _run(plan.strategies, symbols, start_ms, end_ms, trade_start, root)
    return a, b


def test_kema_long_dsl_equals_core_synthetic(tmp_path):
    gs.write_synthetic_market(tmp_path / "data")
    syms = ["AAA@perp", "BBB@perp", "CCC@perp"]
    a, b = _parity(tmp_path / "data", syms, gs.T0, gs.T0 + 38 * gs.DAY, gs.T0 + 18 * gs.DAY)
    assert len(a["positions"]) > 0, "kịch bản phải có lệnh để so sánh"
    assert a["positions"] == b["positions"]
    assert a["equity_curve"] == b["equity_curve"]
    assert a == b


def test_kema_long_dsl_equals_core_real_data():
    root = os.path.abspath(os.environ.get("NORA_PARITY_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data", "okx"))
    syms = ["BTC@perp", "SOL@perp"]
    if not all(os.path.isfile(os.path.join(root, "cex", s.split("@")[0], "perp", "1m.pkl")) for s in syms):
        pytest.skip(f"không có dữ liệu thật perp tại {root}")
    t = lambda d: int(pd.Timestamp(d, tz="UTC").timestamp() * 1000)  # noqa: E731
    a, b = _parity(root, syms, t("2026-03-01") - 20 * gs.DAY, t("2026-04-15"), t("2026-03-01"))
    assert len(a["positions"]) > 0
    assert a == b
