"""F1 ngân sách DCA + F2 cooldown sau thoát + lấy mẫu cấu hình hợp lệ của optimize_alphas.

- dca_budget_check: lệnh đầu + mọi tầng DCA (kèm phí) phải vừa max_capital_usage, nếu không tầng cuối bị bỏ âm thầm.
- build_params từ chối cấu hình không vừa; PositionTracker đếm tầng bị từ chối (dca_layers_rejected).
- cooldown: chặn tín hiệu vào lại trong N phút sau khi đóng; cooldown=0 y hệt cũ; bật/tắt _SKIP_IDLE cho kết quả y hệt.
"""
import importlib.util
import itertools
import os
import sys

import numpy as np
import pandas as pd
import pytest

from backend.core.backtest.engine import BacktestEngine
from backend.core.backtest.execution import PositionTracker
from backend.core.backtest.params_builder import build_params, dca_budget_check, resolve_costs
from backend.core.strategy.params import StrategyParams
from backend.db.models import PositionType
from test_signals_strategies import M, _engine, _ohlcv, _path

SPOT = resolve_costs("cex", "spot", None, None)   # taker 0,10% / maker 0,10%
PERP = resolve_costs("cex", "perp", None, None)   # taker 0,05% / maker 0,02%


def _pos(**kw):
    return {"market": "spot", "order_size_pct": 20.0, "dca_step_pct": 0.5, "dca_max_layers": 4,
            "dca_size_multiplier": 1.0, **kw}


# ─── dca_budget_check ───────────────────────────────────────────────────────

def test_budget_20pct_x5_layers_fails_19pct_passes():
    bad = dca_budget_check(_pos(), SPOT)
    assert not bad["ok"] and bad["layers"] == 4 and bad["cap_pct"] == pytest.approx(100.0)
    assert bad["need_pct"] == pytest.approx(20.0 * (5 + 5 * 0.001))      # 5 lệnh × (1 + phí 0,1%)
    assert 19.0 < bad["max_order_size_pct"] < 20.0
    assert dca_budget_check(_pos(order_size_pct=19.0), SPOT)["ok"]
    assert dca_budget_check(_pos(order_size_pct=bad["max_order_size_pct"]), SPOT)["ok"]


def test_budget_multipliers_and_lists():
    # hệ số 1,5: tổng khối lượng = 1 + 1,5 + 2,25 + 3,375 + 5,0625 = 13,1875 lệnh đầu
    total = 1 + 1.5 + 1.5 ** 2 + 1.5 ** 3 + 1.5 ** 4
    r = dca_budget_check(_pos(order_size_pct=7.0, dca_size_multiplier=1.5), SPOT)
    assert r["ok"] and r["need_pct"] == pytest.approx(7.0 * total * 1.001)
    assert not dca_budget_check(_pos(order_size_pct=8.0, dca_size_multiplier=1.5), SPOT)["ok"]
    # dca_steps / dca_multipliers riêng từng tầng ghi đè dca_max_layers / dca_size_multiplier
    r = dca_budget_check(_pos(order_size_pct=10.0, dca_steps=[1.0, 1.0], dca_multipliers=[2.0, 2.0]), SPOT)
    assert r["layers"] == 2 and r["need_pct"] == pytest.approx(10.0 * (1 + 2 + 4) * 1.001) and r["ok"]
    assert not dca_budget_check(_pos(order_size_pct=15.0, dca_steps=[1.0, 1.0], dca_multipliers=[2.0, 2.0]), SPOT)["ok"]


def test_budget_perp_leverage_and_cap():
    r = dca_budget_check(_pos(market="perp", leverage=5.0), PERP)
    unit = (1 + 5 * 0.0005) + 4 * (1 + 5 * 0.0002)
    assert r["need_pct"] == pytest.approx(20.0 * unit) and not r["ok"]
    assert dca_budget_check(_pos(market="perp", leverage=5.0, order_size_pct=19.0), PERP)["ok"]
    # đòn bẩy cao -> phí trên danh nghĩa lớn hơn -> trần order_size thấp hơn
    assert (dca_budget_check(_pos(market="perp", leverage=10.0), PERP)["max_order_size_pct"]
            < dca_budget_check(_pos(market="perp", leverage=2.0), PERP)["max_order_size_pct"])
    # max_capital_usage hạ trần
    r = dca_budget_check(_pos(order_size_pct=15.0, max_capital_usage=0.7), SPOT)
    assert r["cap_pct"] == pytest.approx(70.0) and not r["ok"]


def test_budget_not_applicable():
    assert dca_budget_check(_pos(dca_max_layers=0), SPOT)["ok"]                      # không DCA
    assert dca_budget_check(_pos(dca_step_pct=0.0), SPOT)["ok"]                      # bước 0 = tắt DCA
    assert dca_budget_check(_pos(sizing="risk", order_size_pct=100.0), SPOT)["ok"]   # khối lượng theo rủi ro
    assert dca_budget_check({"order_size_pct": 100.0}, SPOT)["ok"]


def test_build_params_rejects_over_budget_with_clear_message():
    with pytest.raises(ValueError) as exc:
        build_params("LONG_x", {"match": [], "stop": []}, "LONG", _pos(), "cex")
    msg = str(exc.value)
    assert "DCA" in msg and "4 tầng" in msg and "100.0%" in msg and "19." in msg   # nêu số tầng, cần/trần, order_size tối đa
    ok = build_params("LONG_x", {"match": [], "stop": []}, "LONG", _pos(order_size_pct=19.0), "cex")
    assert ok.order_size_pct == 19.0


def test_library_dca_bots_fit_budget():
    from backend.core.strategy.strategy_library import KERNEL_STRATEGIES
    dca = [s for s in KERNEL_STRATEGIES if s["default_params"].get("dca_max_layers")]
    assert len(dca) == 3
    for s in dca:
        pos = s["default_params"]
        build_params("f", {"match": [], "stop": []}, s["flows"][0]["type"], pos, "cex")   # không raise
        assert pos["order_size_pct"] == 19.0


# ─── Tầng DCA bị từ chối được đếm ───────────────────────────────────────────

def _tracker(order_size_pct, layers=4):
    params = StrategyParams(name="LONG_t", market="spot", order_size_pct=order_size_pct, dca_step_pct=0.5,
                            dca_max_layers=layers, dca_size_multiplier=1.0, fee_rate=0.001, maker_fee_rate=0.001,
                            slippage_rate=0.0, extra={"ast": {"match": [], "stop": []}})
    return PositionTracker(0, 0, "X", "LONG_t", params, PositionType.LONG, initial_capital=10000.0)


def test_refused_dca_layer_is_counted_and_fill_logic_unchanged():
    tr = _tracker(20.0)                  # tạo trực tiếp (bỏ qua build_params): 5 × 20% + phí > 100%
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    tr.on_bar(M, 100, 100, 90, 90, entry_signal=False, stop_signal=False)   # giá rơi xuyên mọi tầng
    assert tr.layer_count == 4 and tr.dca_rejected == 1
    ok = _tracker(19.0)
    ok.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    ok.on_bar(M, 100, 100, 90, 90, entry_signal=False, stop_signal=False)
    assert ok.layer_count == 5 and ok.dca_rejected == 0


def test_get_results_exposes_dca_layers_rejected():
    df = _path([100] * 5 + [100, 90, 90, 90, 90, 90])
    eng = _engine(df, [[[{"frame": "1m", "column": "open_time"}, "==", int(df.open_time[4])]]],
                  order_size_pct=19.0, dca_step_pct=0.5, dca_max_layers=4, fee_rate=0.001, slippage_rate=0.0)
    eng.run()
    assert eng.get_results()["dca_layers_rejected"] == 0
    # ép tracker tạo trực tiếp (vượt ngân sách) -> kết quả ghi nhận tầng bị bỏ
    eng2 = BacktestEngine(0, 0, "T", int(df.open_time.min()), int(df.open_time.max()))
    eng2.trackers.append(_tracker(20.0))
    eng2.trackers[0].dca_rejected = 3
    assert eng2.get_results()["dca_layers_rejected"] == 3


def test_portfolio_get_results_has_dca_layers_rejected(tmp_path):
    import golden_scenarios as gs
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    gs.write_synthetic_market(tmp_path / "data")
    with gs.data_root_env(str(tmp_path / "data")):
        eng = PortfolioEngine(["AAA@perp"], [{**gs.LONG, "id": "rsi_long"}], gs.T0, gs.T0 + 20 * gs.DAY,
                              trade_start_ts=gs.T0 + 3 * gs.DAY, use_cache=False, risk=RiskConfig())
        eng.run()
        assert eng.get_results()["dca_layers_rejected"] == 0
        eng.books[0]["entries"][0]["tracker"].dca_rejected = 2
        assert eng.get_results()["dca_layers_rejected"] == 2


# ─── F2 cooldown ────────────────────────────────────────────────────────────

ALWAYS = [[[{"frame": "1m", "column": "close"}, ">", 0]]]   # tín hiệu là TRẠNG THÁI: luôn đúng


def _stop_then_flat(**pos):
    df = _path([100] * 10 + [98] * 80)           # nến 10 chạm SL 1% rồi đi ngang
    eng = _engine(df, ALWAYS, order_size_pct=50.0, stop_loss_rate=1.0, fee_rate=0.0, slippage_rate=0.0, **pos)
    eng.run()
    return df, eng.closed_positions


def test_reentry_blocked_within_cooldown_allowed_after():
    df, base = _stop_then_flat()
    t = lambda i: int(df.open_time[i])
    assert base[0].close_time == t(10) and base[1].enter_time == t(12)   # không cooldown: vào lại sau 2 phút
    _, cd = _stop_then_flat(cooldown=30)
    assert cd[0].close_time == t(10)
    assert cd[1].enter_time >= cd[0].close_time + 30 * M + M            # tín hiệu hợp lệ đầu tiên rồi vào ở open nến kế
    assert cd[1].enter_time == t(41)                                    # tín hiệu ở nến 40 (= 10 + 30), vào ở nến 41
    assert cd[1].enter_time - cd[0].close_time > 2 * M


def test_cooldown_zero_is_identical_to_default():
    _, a = _stop_then_flat()
    _, b = _stop_then_flat(cooldown=0)
    key = lambda ps: [(p.enter_time, p.close_time, p.real_pnl, p.layers) for p in ps]
    assert key(a) == key(b) and len(a) > 1


def test_cooldown_applies_after_force_close_and_timeout():
    tr = _tracker(10.0, layers=0)
    tr.cooldown_ms = 10 * M
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    tr.on_bar(M, 100, 100, 100, 100, entry_signal=False, stop_signal=False)
    assert tr.is_open
    tr.force_close(2 * M, 100.0)
    assert tr.last_close_time == 2 * M
    tr.on_bar(3 * M, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    assert not tr.pending_entry                                           # trong cooldown
    tr.on_bar(12 * M, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    assert tr.pending_entry                                               # đủ 10 phút kể từ lúc đóng


@pytest.mark.parametrize("cooldown", [0, 45])
def test_skip_idle_identical_with_cooldown(monkeypatch, cooldown):
    df = _ohlcv(4000, seed=5)
    tree = [[[{"frame": "1m", "column": "rsi_14"}, "<", 35]]]

    def run():
        eng = _engine(df, tree, order_size_pct=50.0, take_profit_rate=0.2, stop_loss_rate=0.2, cooldown=cooldown,
                      fee_rate=0.0005, slippage_rate=0.0002)
        eng.run()
        return [(p.enter_time, p.close_time, p.real_pnl, p.status.name) for p in eng.closed_positions], eng.equity_curve

    monkeypatch.setattr(BacktestEngine, "_SKIP_IDLE", False)
    off = run()
    monkeypatch.setattr(BacktestEngine, "_SKIP_IDLE", True)
    on = run()
    assert len(off[0]) > 5 and off == on
    if cooldown:
        monkeypatch.setattr(BacktestEngine, "_SKIP_IDLE", True)
        eng0 = _engine(df, tree, order_size_pct=50.0, take_profit_rate=0.2, stop_loss_rate=0.2,
                       fee_rate=0.0005, slippage_rate=0.0002)
        eng0.run()
        assert len(eng0.closed_positions) > len(off[0])                    # cooldown thực sự chặn bớt lệnh


def test_cooldown_in_params_snapshot_and_book():
    from backend.core.strategy.strategy_book import BASE_POSITION
    from backend.core.backtest.params_builder import POSITION_KEYS
    from backend.core.contracts import StrategySnapshot
    assert "cooldown" in POSITION_KEYS and BASE_POSITION["cooldown"] == 60
    assert StrategySnapshot(symbol="BTC").cooldown == 0
    with pytest.raises(Exception):
        StrategySnapshot(symbol="BTC", cooldown=-1)
    p = build_params("LONG_x", {"match": [], "stop": []}, "LONG", {"cooldown": 60}, "cex")
    assert p.cooldown == 60 and p.to_dict()["cooldown"] == 60


# ─── optimize_alphas.sample_configs ─────────────────────────────────────────

def _load_script(name):
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sample_configs_filters_invalid_before_sampling_and_is_deterministic():
    oa = _load_script("optimize_alphas")
    space = {"order_size_pct": [10, 20, 30], "dca_max_layers": [2, 4], "dca_step_pct": [0.5],
             "leverage": [1, 5], "take_profit_rate": [0.5, 1.0, 2.0], "sig.rsi_lo": [20, 25]}
    fixed = {"market": "perp"}
    # perp: hợp lệ khi order_size × ~(1 + layers) ≤ 100: 10%×3 ok, 10%×5 ok, 20%×3 ok, 20%×5 FAIL, 30%×3 ok(90,2%), 30%×5 FAIL
    all_c, total = oa.sample_configs(space, 10_000, 1, fixed=fixed, venue="cex")
    invalid = oa.configs_invalid(space, fixed, "cex")
    assert total == 3 * 2 * 1 * 2 * 3 * 2 and invalid == 2 * 2 * 3 * 2 and len(all_c) == total - invalid
    costs = resolve_costs("cex", "perp", None, None)
    assert all(dca_budget_check({**fixed, **{k: v for k, v in c.items() if not k.startswith("sig.")}}, costs)["ok"]
               for c in all_c)
    a, _ = oa.sample_configs(space, 20, 7, fixed=fixed, venue="cex")
    b, _ = oa.sample_configs(space, 20, 7, fixed=fixed, venue="cex")
    assert a == b and len(a) == 20                    # đủ N cấu hình hợp lệ, tái lập
    assert all(c in all_c for c in a)
