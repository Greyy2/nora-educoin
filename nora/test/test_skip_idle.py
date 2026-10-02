"""Bỏ qua phút rảnh (_SKIP_IDLE) phải cho kết quả BIT-IDENTICAL với vòng lặp từng phút (tắt cờ) — và thực sự bỏ qua.

Kiểm trên vòng lặp Python THAM CHIẾU (test/reference_engine.py): kernel numba của engine thật bỏ qua phút rảnh theo đúng luật này và đã được
chứng minh trùng từng bit với tham chiếu (test_kernel_parity) -> bỏ qua đúng ở tham chiếu => đúng ở kernel."""
import os

import pytest

import golden_scenarios as gs
import reference_engine as ref
from backend.core.backtest import engine as _engine_mod, portfolio as _portfolio_mod
from backend.core.backtest.portfolio import RiskConfig

BacktestEngine, PortfolioEngine = ref.RefBacktestEngine, ref.RefPortfolioEngine


@pytest.fixture(autouse=True)
def _reference_engines(monkeypatch):
    """Kịch bản golden dựng engine qua module backend -> trỏ sang lớp tham chiếu trong file này."""
    monkeypatch.setattr(_portfolio_mod, "PortfolioEngine", PortfolioEngine)
    monkeypatch.setattr(_engine_mod, "BacktestEngine", BacktestEngine)

DAY = gs.DAY
T0 = gs.T0


def _both(monkeypatch, cls, fn):
    """Chạy fn() với cờ tắt rồi bật; trả (kết quả tắt, kết quả bật, số lần nhảy)."""
    calls = {"n": 0}
    orig = cls._skip_idle if hasattr(cls, "_skip_idle") else None
    if orig is not None:
        def counted(self, *a, **k):
            calls["n"] += 1
            return orig(self, *a, **k)
        monkeypatch.setattr(cls, "_skip_idle", counted)
    monkeypatch.setattr(cls, "_SKIP_IDLE", False)
    off = fn()
    monkeypatch.setattr(cls, "_SKIP_IDLE", True)
    on = fn()
    return off, on, calls["n"]


def _check(off, on):
    assert off["positions"], "kịch bản phải có lệnh"
    assert off == on, gs.diff_canonical(off, on)


def test_portfolio_synthetic_skip_equals_full_loop(tmp_path, monkeypatch):
    off, on, jumps = _both(monkeypatch, PortfolioEngine, lambda: gs.scenario_portfolio_synthetic(tmp_path / "data"))
    _check(off, on)
    assert jumps > 0, "cờ bật mà không nhảy lần nào — test không chứng minh được gì"


def _kill_switch_run(root):
    big = {**gs._POSITION, "risk_per_trade_pct": 5.0, "max_notional_pct": 1000, "stop_loss_rate": 6.0,
           "take_profit_rate": 0, "trailing_stop": 0, "timeout": 0}
    strategies = [{**gs.LONG, "position": big}, {**gs.SHORT, "position": big}]
    gs.write_synthetic_market(root)
    with gs.data_root_env(str(root)):
        eng = PortfolioEngine(["AAA@perp", "BBB@perp", "CCC@perp"], strategies, T0, T0 + 30 * DAY,
                              trade_start_ts=T0 + 3 * DAY, use_cache=False,
                              risk=RiskConfig(max_positions=6, max_per_symbol=2, max_gross_exposure=10, kill_switch_dd_pct=5))
        eng.run()
        return gs.canonicalize(eng.get_results())


def test_portfolio_kill_switch_halt_skip_equals_full_loop(tmp_path, monkeypatch):
    off, on, jumps = _both(monkeypatch, PortfolioEngine, lambda: _kill_switch_run(tmp_path / "data"))
    assert off["halted_at"] is not None
    _check(off, on)
    assert jumps > 0  # sau halt: nhảy thẳng tới hết lưới


def _sparse_run(root):
    """Tín hiệu hiếm (RSI 15m < 25) + trade_start muộn: nhiều đoạn rảnh dài, lệnh chờ/mở xen kẽ."""
    tree = [[[gs._f("15m", "rsi_14"), "<", 25]]]
    strategies = [{**gs.LONG, "id": "rare_long", "tree": tree}, {**gs.SHORT, "id": "rare_short",
                                                               "tree": [[[gs._f("15m", "rsi_14"), ">", 75]]]}]
    gs.write_synthetic_market(root)
    with gs.data_root_env(str(root)):
        eng = PortfolioEngine(["AAA@perp", "BBB@perp", "CCC@perp"], strategies, T0, T0 + 33 * DAY,
                              trade_start_ts=T0 + 5 * DAY + 7 * 60_000, use_cache=False, risk=RiskConfig())
        eng.run()
        return gs.canonicalize(eng.get_results())


def test_portfolio_sparse_signals_skip_equals_full_loop(tmp_path, monkeypatch):
    off, on, jumps = _both(monkeypatch, PortfolioEngine, lambda: _sparse_run(tmp_path / "data"))
    _check(off, on)
    assert jumps > 5


def test_single_engine_with_filled_minutes_skip_equals_full_loop(tmp_path, monkeypatch):
    off, on, _ = _both(monkeypatch, BacktestEngine, lambda: gs.scenario_single_dca_filled(tmp_path / "data"))
    _check(off, on)


def test_skip_is_disabled_when_bar_hook_set(tmp_path, monkeypatch):
    calls = {"hook": 0, "skip": 0}
    orig = PortfolioEngine._skip_idle
    monkeypatch.setattr(PortfolioEngine, "_skip_idle", lambda self, *a, **k: calls.__setitem__("skip", calls["skip"] + 1) or orig(self, *a, **k))
    gs.write_synthetic_market(tmp_path / "data")
    with gs.data_root_env(str(tmp_path / "data")):
        eng = PortfolioEngine(["AAA@perp"], [gs.LONG], T0, T0 + 6 * DAY, trade_start_ts=T0 + 3 * DAY,
                              use_cache=False, risk=RiskConfig())
        eng.bar_hook = lambda e, t: calls.__setitem__("hook", calls["hook"] + 1)
        eng.run()
    assert calls["skip"] == 0 and calls["hook"] == 6 * 1440 + 1  # mọi phút (cửa sổ gồm cả hai đầu)


def test_golden_real_skip_equals_full_loop(monkeypatch):
    root = os.path.abspath(os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data"))
    if not gs.real_data_available(root):
        pytest.skip(f"Không có dữ liệu thật tại {root}")
    monkeypatch.setattr(PortfolioEngine, "_SKIP_IDLE", False)
    off = gs.scenario_portfolio_real(root, end="2025-04-10")
    monkeypatch.setattr(PortfolioEngine, "_SKIP_IDLE", True)
    on = gs.scenario_portfolio_real(root, end="2025-04-10")
    _check(off, on)
