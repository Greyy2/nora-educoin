"""Unit test cho B3 & B4: Module diagnose.py và insights.py (không dùng LLM).

Kiểm thử tính toán chẩn đoán trên dữ liệu dựng tay (xác định) và bộ quy tắc sinh nhận xét. Kiểm thử trên lần chạy engine THẬT: test_diagnostics_real.py.
"""
import numpy as np
import pandas as pd

from backend.core.analytics import insights
from backend.core.metrics import diagnose

DAY = 86_400_000
T0 = 1_577_836_800_000     # 2020-01-01 00:00 UTC


def _closed(sym, enter_day, close_day, pnl, reason, side="LONG", qty=1.0, status=None):
    return {"symbol": sym, "side": side, "enter_time": T0 + enter_day * DAY, "close_time": T0 + close_day * DAY, "pnl": pnl, "qty": qty, "notional": 100.0 * qty,
            "status": status or ("TP" if pnl > 0 else "SL"), "close_reason": reason}


def test_exit_category_uses_real_close_reason_not_status():
    cat = diagnose.exit_category
    assert cat("Tín hiệu thoát (AST stop)") == "signal"
    assert cat("Stop-loss (từ giá TB)") == "stop_loss"
    assert cat("Take-profit (từ giá TB)") == "take_profit"
    assert cat("Trailing stop") == "trailing"
    assert cat("Hết thời gian giữ lệnh") == "timeout"
    assert cat("Kill switch danh mục") == "kill_switch"
    assert cat("End of Backtest") == "open_at_end"
    assert cat("Thanh lý (perp)") == "liquidation"
    assert cat("") == "unknown" and cat(None) == "unknown"
    # engine gán status SL/TP theo dấu lãi/lỗ cho thoát theo tín hiệu: KHÔNG được coi là Stop-loss/Take-profit
    tr = [_closed("BTC", 0, 3, 50.0, "Tín hiệu thoát (AST stop)", status="TP"), _closed("BTC", 5, 8, -20.0, "Tín hiệu thoát (AST stop)", status="SL")]
    act = diagnose.compute_signal_activity(tr, T0, T0 + 10 * DAY)
    assert act["exit_reason_counts"] == {"signal": 2} and act["exit_reasons"] == {"signal": 100.0}


def test_exposure_and_days_in_market_hand_made():
    times = T0 + np.arange(0, 11) * DAY                       # 10 ngày giao dịch
    eq = np.full(11, 1000.0)
    # BTC mở ngày 2..5 (4 ngày), ETH mở ngày 4..7 (4 ngày) -> ngày có vị thế: 2..7 = 6/10; chồng nhau ở ngày 4,5
    trades = [_closed("BTC", 2, 6, 10.0, "Tín hiệu thoát (AST stop)", qty=2.0), _closed("ETH", 4, 8, 5.0, "Tín hiệu thoát (AST stop)", qty=1.0)]
    prices = {"BTC": (T0 + np.arange(0, 12) * DAY, np.full(12, 100.0)), "ETH": (T0 + np.arange(0, 12) * DAY, np.full(12, 50.0))}
    series = {"times": times, "equity": eq}
    act = diagnose.compute_signal_activity(trades, T0, T0 + 10 * DAY, series, None, prices)
    assert act["days_in_market_pct"] == 60.0
    # exposure ngày: BTC 2 × 100 = 200 (ngày 2..5), ETH 50 (ngày 4..7) -> tổng = 4 × 200 + 4 × 50 + 4 × 200(chồng: tính ở trên) ... tính tay bên dưới
    expo = [0, 0, 200, 200, 250, 250, 50, 50, 0, 0]
    assert act["avg_exposure_pct"] == round(float(np.mean(expo)) / 1000 * 100, 2)
    assert act["avg_exposure_pct"] < 100.0 and act["days_in_market_pct"] < 100.0
    assert act["time_in_market_by_coin"] == {"BTC": 40.0, "ETH": 40.0}


def test_market_comparison_from_benchmark_series():
    t = T0 + np.arange(0, 6) * DAY
    bench_eq = np.array([100.0, 110.0, 99.0, 108.9, 119.79, 107.811])
    half = 100.0 * np.cumprod(np.r_[1.0, 1.0 + 0.5 * (bench_eq[1:] / bench_eq[:-1] - 1.0)])     # chiến lược = 0,5 × thị trường -> beta 0,5, tương quan 1
    out = diagnose.compute_market_comparison(half, t, 100.0, {"times": t, "equity": bench_eq, "label": "test"})
    assert out["available"] and out["beta"] == 0.5 and out["correlation"] == 1.0
    assert out["market_mdd"] == round(abs(107.811 / 119.79 - 1) * 100, 2)
    assert out["excess_cagr"] == round(out["strategy_cagr"] - out["market_cagr"], 2)
    none = diagnose.compute_market_comparison(half, t, 100.0, None)           # không benchmark -> không bịa beta/tương quan/thị trường
    assert none["available"] is False and none["beta"] is None and none["correlation"] is None and none["market_cagr"] is None and none["market_mdd"] is None


def _market(n=700, seed=3):
    rng = np.random.default_rng(seed)
    lab = T0 + (np.arange(n) + 1) * DAY
    # nửa đầu tăng, nửa sau giảm -> cả hai chế độ đều có ngày sau 200 nến khởi động
    drift = np.r_[np.full(n // 2, 0.004), np.full(n - n // 2, -0.004)]
    return {"label_times": lab, "close": 100.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.003, n)), "source": "BTC"}


def test_regime_days_sum_and_split_by_sma200():
    mk = _market()
    n_days = 400
    times = T0 + 200 * DAY + np.arange(0, n_days + 1) * DAY            # bắt đầu sau 200 nến thị trường (có SMA200 ngay)
    eq = 1000.0 + np.cumsum(np.r_[0.0, np.arange(1, n_days + 1) % 7 - 3.0])
    trades = [_closed("BTC", 210, 220, 5.0, "Tín hiệu thoát (AST stop)"), _closed("BTC", 380, 390, -2.0, "Tín hiệu thoát (AST stop)")]
    reg = diagnose.compute_regime_analysis({"times": times, "equity": eq}, trades, None, mk, None, 1000.0)
    assert reg["available"] and reg["total_days"] == n_days
    assert reg["bull"]["days"] + reg["bear"]["days"] + reg["unknown"]["days"] == n_days
    assert reg["bull"]["days"] > 0 and reg["bear"]["days"] > 0 and reg["unknown"]["days"] == 0
    assert reg["bull"]["trades_entered"] + reg["bear"]["trades_entered"] + reg["unknown"]["trades_entered"] == 2
    assert abs(reg["bull"]["pnl_usd"] + reg["bear"]["pnl_usd"] + reg["unknown"]["pnl_usd"] - (eq[-1] - eq[0])) < 0.05
    # chế độ phải nhân quả: đổi giá TƯƠNG LAI không đổi nhãn các ngày trước
    mk2 = dict(mk, close=mk["close"].copy())
    mk2["close"][400:] *= 0.1
    reg2 = diagnose.compute_regime_analysis({"times": times, "equity": eq}, trades, None, mk2, None, 1000.0)
    st1 = diagnose._market_state(mk, times[:-1])
    st2 = diagnose._market_state(mk2, times[:-1])
    first_changed = int(np.argmax(st1 != st2))
    assert times[first_changed] >= mk["label_times"][399]
    assert reg2["available"]
    assert diagnose.compute_regime_analysis({"times": times, "equity": eq}, trades, None, None)["available"] is False      # thiếu giá thị trường -> không bịa


def _frame(n=600, seed=11):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0, 0.02, n))
    return pd.DataFrame({"open_time": T0 + np.arange(n) * DAY, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": np.full(n, 10.0)})


def test_binding_condition_identifies_the_blocking_conjunct():
    from backend.core.strategy.pydsl import compile_code
    code = """
class Three(SimpleAlgorithm):
    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, timeperiod=10)
        rsi = self.feat.rsi(close, timeperiod=14)
        a = close > 0
        b = rsi > 40
        c = close > ema * 1.03
        self.set_positions(a & b & c, position=1)
"""
    prog = compile_code(code, register=False)
    df = _frame()
    out = diagnose.compute_binding_condition(prog, {"BTC": df}, int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]) + DAY)
    assert out["available"] and len(out["rules"]) == 1
    rule = out["rules"][0]
    assert rule["n_conjuncts"] == 3
    c_a, c_b, c_c = rule["conjuncts"]
    assert c_a["pct_true"] == 100.0 and c_a["only_false_bars"] == 0
    assert c_c["pct_true"] < c_b["pct_true"] < 100.0
    assert rule["binding"]["index"] == 3 and "EMA" in rule["binding"]["text_vi"]
    assert rule["binding"]["share_of_near_miss_pct"] >= 50.0
    assert rule["bars"] == len(df) and rule["all_true_bars"] > 0
    d = {"binding_condition": out}
    ins = [i for i in insights.generate_insights(d, {}) if i["id"] == "binding_condition"]
    assert ins and ins[0]["evidence"]["conjunct_index"] == 3 and ins[0]["evidence"]["share_of_near_miss_pct"] == rule["binding"]["share_of_near_miss_pct"]
    assert rule["binding"]["text_vi"] in ins[0]["message_vi"]


def test_diagnose_calculations():
    trades = [
        _closed("BTC", 0, 2, 500.0, "Take-profit (từ giá TB)"),
        _closed("BTC", 5, 9, -200.0, "Stop-loss (từ giá TB)"),
        _closed("ETH", 10, 13, 300.0, "Tín hiệu thoát (AST stop)", side="SHORT"),
    ]
    eq = np.array([10000.0, 10500.0, 10300.0, 10600.0])
    times = T0 + np.arange(4) * DAY
    series = {"equity": eq, "times": times}
    metrics = {
        "simulate": {"nora": {"sharpe": 1.5, "cagr_pct": 25.0, "mdd_pct": 10.0}},
        "train": {"nora": {"sharpe": 1.8, "cagr_pct": 30.0, "mdd_pct": 8.0}},
        "test": {"nora": {"sharpe": 0.9, "cagr_pct": 15.0, "mdd_pct": 12.0}},
    }
    diag = diagnose.diagnose_run(program=None, series=series, trades=trades, metrics=metrics, initial_capital=10000.0, start=int(times[0]), end=int(times[-1]), fees_total=50.0)

    sig = diag["signal_activity"]
    assert sig["total_trades"] == 3 and sig["closed_trades"] == 3 and sig["open_trades"] == 0
    assert sig["long_trades"] == 2 and sig["short_trades"] == 1
    assert sig["exit_reason_counts"] == {"take_profit": 1, "stop_loss": 1, "signal": 1}
    assert "holding_time_pct" not in sig                                    # đã thay bằng days_in_market_pct + avg_exposure_pct

    pnl = diag["pnl_structure"]
    assert pnl["win_rate"] == round(2 / 3 * 100, 2) and pnl["max_consecutive_losses"] == 1
    assert set(pnl["by_coin"]) == {"BTC", "ETH"} and pnl["by_coin"]["BTC"] == 300.0
    assert pnl["fee_drag_pct"] == round(50.0 / (600.0 + 50.0) * 100, 2)      # phí / lãi gộp trước phí theo đường vốn (10600 - 10000 + 50)
    assert pnl["short_pnl_usd"] == 300.0 and pnl["short_closed_trades"] == 1
    # số hiển thị ở Education đọc từ backend (giao diện không tự tính): thắng 500 + 300, thua 200
    assert (pnl["winning_trades"], pnl["losing_trades"]) == (2, 1)
    assert (pnl["avg_win"], pnl["avg_loss"], pnl["max_win"], pnl["max_loss"]) == (400.0, 200.0, 500.0, 200.0)   # độ lớn dương
    assert pnl["payoff"] == 2.0

    tvt = diag["train_vs_test"]
    assert (tvt["train_sharpe"], tvt["test_sharpe"], tvt["sharpe_decay"]) == (1.8, 0.9, 0.5)
    assert (tvt["train_cagr"], tvt["test_cagr"], tvt["train_mdd"], tvt["test_mdd"]) == (30.0, 15.0, 8.0, 12.0)

    mc = diag["market_comparison"]                                          # không benchmark -> không số giả
    assert mc["available"] is False and mc["beta"] is None and mc["market_cagr"] is None
    assert diag["regime_analysis"]["available"] is False
    assert diag["binding_condition"]["available"] is False


def test_train_vs_test_without_train_sharpe_has_no_fake_decay():
    out = diagnose.compute_train_vs_test({"train": {"nora": {"sharpe": 0.0}}, "test": {"nora": {"sharpe": 1.0}}})
    assert out["sharpe_decay"] is None


def _diag(**over):
    base = {
        "market_comparison": {"available": True, "correlation": 0.95, "beta": 0.95, "excess_cagr": 2.1, "strategy_cagr": 40.0, "market_cagr": 37.9, "strategy_mdd": 20.0, "market_mdd": 70.0},
        "train_vs_test": {"train_sharpe": 1.5, "test_sharpe": 1.3, "sharpe_decay": 0.87},
        "pnl_structure": {"fee_drag_pct": 25.5, "fees_usd": 255.0, "gross_pnl_before_fees_usd": 1000.0, "top5_profit_pct": 30.0, "win_rate": 55.0, "payoff": 1.2,
                          "max_consecutive_losses": 3, "closed_trades": 35, "by_coin": {}, "short_pnl_usd": 0.0, "short_closed_trades": 0},
        "signal_activity": {"days_in_market_pct": 50.0, "avg_exposure_pct": 30.0, "total_trades": 35, "closed_trades": 35, "open_trades": 0, "long_trades": 35,
                            "short_trades": 0, "exit_reason_counts": {"signal": 35}},
        "regime_analysis": {"available": True, "market": "BTC", "sma_days": 200, "initial_capital": 10000.0,
                            "bull": {"days": 500, "trades_entered": 25, "pnl_usd": 3000.0}, "bear": {"days": 300, "trades_entered": 10, "pnl_usd": -800.0}},
        "binding_condition": {"available": False, "rules": []},
    }
    base.update(over)
    return base


def _ids(d):
    return [i["id"] for i in insights.generate_insights(d, {})]


def test_insight_rules_trigger_from_measured_fields():
    ins = insights.generate_insights(_diag(), {})
    ids = [i["id"] for i in ins]
    assert {"beta_driven", "fee_drag", "only_long_bias", "bear_loss"} <= set(ids)
    for item in ins:                                                        # mỗi nhận xét có bằng chứng = số đo cụ thể
        assert item["id"] and item["severity"] in ("warning", "good", "info")
        assert isinstance(item["message_vi"], str) and len(item["message_vi"]) > 10
        assert isinstance(item["evidence"], dict) and item["evidence"]
    beta = next(i for i in ins if i["id"] == "beta_driven")
    assert beta["evidence"]["beta"] == 0.95 and f"{0.95:.2f}" in beta["message_vi"]

    d2 = _diag(
        train_vs_test={"train_sharpe": 2.0, "test_sharpe": 0.6, "sharpe_decay": 0.30},
        market_comparison={"available": True, "correlation": 0.5, "beta": 0.4, "excess_cagr": 15.0, "strategy_cagr": 50.0, "market_cagr": 35.0, "strategy_mdd": 45.0, "market_mdd": 70.0},
        pnl_structure={"fee_drag_pct": 5.0, "top5_profit_pct": 65.0, "win_rate": 70.0, "payoff": 2.5, "max_consecutive_losses": 7, "closed_trades": 12, "by_coin": {},
                       "short_pnl_usd": 100.0, "short_closed_trades": 4},
        signal_activity={"days_in_market_pct": 3.0, "avg_exposure_pct": 2.0, "total_trades": 12, "closed_trades": 12, "open_trades": 0, "long_trades": 8, "short_trades": 4,
                         "exit_reason_counts": {"stop_loss": 6, "signal": 6}},
    )
    ins2 = insights.generate_insights(d2, {})
    ids2 = [i["id"] for i in ins2]
    assert {"overfit_gap", "tail_dependent", "rarely_in_market", "drawdown_heavy", "high_consecutive_losses", "low_trade_count", "sl_dominant_exit"} <= set(ids2)
    sl = next(i for i in ins2 if i["id"] == "sl_dominant_exit")
    assert sl["evidence"] == {"stop_loss_pct_of_closed": 50.0, "stop_loss_trades": 6, "closed_trades": 12}
    assert "beta_driven" not in ids2 and "short_profitable" not in ids2          # tương quan thấp; short < 5 lệnh đã đóng
    severities = [i["severity"] for i in ins2]
    first_good_or_info = next((idx for idx, s in enumerate(severities) if s in ("good", "info")), len(severities))
    assert all(sv == "warning" for sv in severities[:first_good_or_info])


def test_rules_stay_silent_without_measured_inputs():
    """Thiếu benchmark / thị trường / điều kiện -> các quy tắc phụ thuộc không kích hoạt (không bịa)."""
    d = _diag(market_comparison={"available": False, "beta": None, "correlation": None, "excess_cagr": None, "strategy_cagr": 10.0, "market_cagr": None,
                                 "strategy_mdd": 20.0, "market_mdd": None},
              regime_analysis={"available": False})
    ids = _ids(d)
    assert not {"beta_driven", "negative_excess", "strong_alpha", "bear_loss", "positive_bear_performance", "binding_condition"} & set(ids)
    assert not _ids({})                                                      # chẩn đoán rỗng -> không có nhận xét nào


def test_exit_rules_ignore_open_positions_and_status_labels():
    d = _diag(signal_activity={"days_in_market_pct": 99.0, "avg_exposure_pct": 100.0, "total_trades": 10, "closed_trades": 0, "open_trades": 10, "long_trades": 10, "short_trades": 0,
                               "exit_reason_counts": {"open_at_end": 10}})
    ids = _ids(d)
    assert "sl_dominant_exit" not in ids and "tp_dominant_exit" not in ids and "always_in" in ids


def test_binding_rule_needs_three_conjuncts_and_half_of_near_misses():
    def bc(n, share, near=100):
        b = {"index": 2, "text_vi": "RSI lớn hơn 50", "pct_true": 12.0, "only_false_bars": int(near * share / 100), "share_of_near_miss_pct": share}
        return {"binding_condition": {"available": True, "rules": [{"index": 1, "line": 9, "side": "LONG", "n_conjuncts": n, "near_miss_bars": near, "all_true_bars": 5, "binding": b}]}}
    assert "binding_condition" in _ids(_diag(**bc(3, 60.0)))
    assert "binding_condition" not in _ids(_diag(**bc(3, 49.0)))
    assert "binding_condition" not in _ids(_diag(**bc(2, 90.0)))
    assert "binding_condition" not in _ids(_diag(**bc(3, 90.0, near=10)))


def test_single_conjunct_rule_reports_pct_true_without_binding():
    from backend.core.strategy.pydsl import compile_code
    code = """
class One(SimpleAlgorithm):
    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, timeperiod=10)
        self.set_positions(close > ema, position=1)
"""
    prog = compile_code(code, register=False)
    df = _frame()
    out = diagnose.compute_binding_condition(prog, {"BTC": df}, int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]) + DAY)
    rule = out["rules"][0]
    assert rule["n_conjuncts"] == 1 and rule["binding"] is None
    c = rule["conjuncts"][0]
    assert 0.0 < c["pct_true"] < 100.0 and "only_false_bars" not in c
    assert rule["bars"] == len(df) and rule["all_true_bars"] == round(c["pct_true"] / 100.0 * len(df))
    assert c["per_symbol"]["BTC"]["pct_true"] == c["pct_true"]


def test_market_comparison_cagr_uses_metrics_definition():
    """strategy_cagr/market_cagr = (vốn cuối/vốn đầu)^(365/số ngày lợi suất) - 1, số ngày = số mẫu - 1 (cùng metrics/returns.cagr_pct)."""
    times = T0 + np.arange(0, 731) * DAY                       # 730 ngày lợi suất
    eq = 100.0 * np.linspace(1.0, 2.0, 731)
    bench = {"times": times, "equity": eq * 1.0, "label": "x"}
    out = diagnose.compute_market_comparison(eq, times, 100.0, bench)
    expected = round(((eq[-1] / eq[0]) ** (365.0 / 730.0) - 1.0) * 100.0, 2)
    assert out["strategy_cagr"] == expected == out["market_cagr"]


def test_pnl_structure_new_fields_missing_when_no_trade_of_that_kind():
    """Không có lệnh thắng/thua thì avg/max = None (không phải 0 giả); không có lệnh nào -> tất cả None."""
    only_wins = diagnose.compute_pnl_structure([_closed("BTC", 0, 2, 120.0, "Take-profit"), _closed("BTC", 3, 5, 80.0, "Take-profit")], 0.0, 1000.0)
    assert (only_wins["winning_trades"], only_wins["losing_trades"]) == (2, 0)
    assert (only_wins["avg_win"], only_wins["max_win"]) == (100.0, 120.0) and only_wins["avg_loss"] is None and only_wins["max_loss"] is None
    assert only_wins["payoff"] is None
    none = diagnose.compute_pnl_structure([], 0.0, 1000.0)
    assert all(none[k] is None for k in ("winning_trades", "losing_trades", "avg_win", "avg_loss", "max_win", "max_loss", "win_rate", "payoff"))
