"""Khớp SL "extreme" không phụ thuộc khung chạy: ở khung chạy > 1m lệnh stop khớp ở giá xấu nhất của NẾN 1m đầu tiên chạm mức (đường giá 1m
trong nến chạy — engine.minute_path), đúng như khi chạy khung 1m; trước đây khớp ở đáy/đỉnh của cả nến 15m/1h (bi quan gấp nhiều lần)."""
import numpy as np

from backend.core.strategy.book import f
from test_strategy_book import T0, market  # noqa: F401  (market là fixture: 70 ngày, 3 tài sản)

DAY = 86_400_000
POS = {"market": "perp", "order_size_usd": 1000, "leverage": 2, "stop_loss_rate": 1.0, "take_profit_rate": 3.0, "timeout": 2880}
LONG = {"id": "rsi15_long", "side": "LONG", "tree": [[[f("15m", "rsi_14"), "<", 35]]], "position": POS}


def _run(base_frame, stop_fill):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    st = {**LONG, "position": {**POS, "stop_fill": stop_fill}}
    eng = PortfolioEngine(["BBB@perp"], [st], T0 + 2 * DAY, T0 + 68 * DAY, trade_start_ts=T0 + 10 * DAY,
                          risk=RiskConfig.from_dict({"max_positions": 99, "max_per_symbol": 99, "max_gross_exposure": 1e9, "kill_switch_dd_pct": 0}),
                          use_cache=False, base_frame=base_frame)
    eng.run()
    return {p.enter_time: p for p in eng.get_results()["positions"]}


def test_minute_path_offsets_cover_each_base_bar(market):
    from backend.core.backtest.engine import BacktestEngine
    eng = BacktestEngine(0, 0, "BBB@perp", T0 + 2 * DAY, T0 + 5 * DAY, base_frame="15m")
    t = T0 + 3 * DAY + np.arange(4, dtype=np.int64) * 900_000
    mp = eng.minute_path(t)
    assert (mp["m_b"] - mp["m_a"] == 15).all() and mp["m_a"][1] == mp["m_b"][0]
    assert len(eng.minute_path(np.zeros(0, dtype=np.int64))["m_l"]) == 0
    assert BacktestEngine(0, 0, "BBB@perp", T0, T0 + DAY).minute_path(t)["m_l"].size == 0     # khung chạy 1m: không cần


def test_extreme_sl_fill_at_15m_matches_1m(market):
    one, fif = _run("1m", "extreme"), _run("15m", "extreme")
    lvl = _run("15m", "level")
    common = [k for k in one if k in fif and one[k].close_reason.startswith("Stop-loss") and fif[k].close_reason.startswith("Stop-loss")]
    assert len(common) >= 5
    same = sum(1 for k in common if abs(one[k].close_price - fif[k].close_price) < 1e-9)
    assert same / len(common) >= 0.9                                  # cùng nến 1m chạm mức -> cùng giá khớp
    for k in common:                                                  # bi quan hơn "level", nhưng không bao giờ tệ hơn đáy nến 15m
        if k in lvl and lvl[k].close_reason.startswith("Stop-loss"):
            assert fif[k].close_price <= lvl[k].close_price + 1e-9
