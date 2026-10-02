"""
test_signals_strategies.py — bước 2: kernel tín hiệu + quản lý vị thế.

A. Kernel: causal (prefix-invariance), khớp công thức tham chiếu, NaN trong giai đoạn khởi động.
B. VectorEvaluator == LogicEvaluator (từng phần tử) trên AST ngẫu nhiên.
C. Kernel đa khung chỉ nhìn thấy khi nến khung đó đã đóng; index (nến trước) đúng.
D. Quản lý vị thế: DCA (khớp tầng, giá TB), TP từ giá TB, không TP trong nến vừa DCA,
   stop-loss / trailing / timeout, thanh lý perp, spot không short, phí theo venue,
   MDD mark-to-market thấy được lỗ treo.
"""
import numpy as np
import pandas as pd
import pytest

from backend.core.signals import kernels

T0 = 1_700_006_400_000
M = 60_000


def _ohlcv(n=3000, seed=0, t0=T0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    return pd.DataFrame({"open_time": t0 + np.arange(n, dtype=np.int64) * M, "open": open_, "high": high,
                         "low": low, "close": close, "volume": rng.uniform(1, 100, n)})


ALL_KERNEL_COLUMNS = [k["example"] for k in kernels.catalog()]


# ─── A. Kernel ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("column", ALL_KERNEL_COLUMNS)
def test_kernel_is_causal_prefix_invariant(column):
    df = _ohlcv(800, seed=1)
    full = kernels.compute(df, column).to_numpy()
    for t in (150, 333, 600, 799):
        part = kernels.compute(df.iloc[:t].reset_index(drop=True), column).to_numpy()
        np.testing.assert_allclose(part, full[:t], rtol=1e-9, atol=1e-12, equal_nan=True,
                                   err_msg=f"{column} dùng dữ liệu tương lai (khác khi cắt tại {t})")


@pytest.mark.parametrize("column", ALL_KERNEL_COLUMNS)
def test_kernel_nan_during_warmup_then_values(column):
    df = _ohlcv(800, seed=2)
    values = kernels.compute(df, column)
    assert pd.isna(values.iloc[0]), f"{column}: nến đầu tiên phải là NaN (chưa đủ dữ liệu)"
    assert values.iloc[kernels.warmup_bars(column):].notna().mean() > 0.95


def test_kernel_reference_values():
    df = _ohlcv(400, seed=3)
    c = df["close"]
    np.testing.assert_allclose(kernels.compute(df, "sma_20"), c.rolling(20).mean(), equal_nan=True)
    # EMA / RMA chuẩn TradingView (ta.ema / ta.rma): giá trị đầu = SMA của n nến đầu, sau đó đệ quy
    def tv(x, alpha, n):
        out = [np.nan] * len(x)
        e = float(np.mean(x[:n]))
        out[n - 1] = e
        for i in range(n, len(x)):
            e = alpha * x[i] + (1 - alpha) * e
            out[i] = e
        return pd.Series(out)
    np.testing.assert_allclose(kernels.compute(df, "ema_50"), tv(c.to_numpy(), 2 / 51, 50), rtol=1e-12, equal_nan=True)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift(1)).abs(), (df["low"] - c.shift(1)).abs()], axis=1).max(axis=1)
    np.testing.assert_allclose(kernels.compute(df, "atr_14"), tv(tr.to_numpy(), 1 / 14, 14), rtol=1e-12, equal_nan=True)
    # RSI Wilder: giá trị nằm trong [0, 100]
    r = kernels.compute(df, "rsi_14")
    assert r.dropna().between(0, 100).all()
    # Donchian KHÔNG gồm nến hiện tại
    dch = kernels.compute(df, "dch_20")
    np.testing.assert_allclose(dch.iloc[25], df["high"].iloc[5:25].max())
    # Z-score
    z = kernels.compute(df, "bbz_20")
    mid, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    np.testing.assert_allclose(z, (c - mid) / sd, equal_nan=True, rtol=1e-9)


def test_rsi_flat_series_is_50():
    df = _ohlcv(100)
    df[["open", "high", "low", "close"]] = 5.0
    assert (kernels.compute(df, "rsi_14").dropna() == 50.0).all()


def test_parse_column_rejects_bad_names():
    for bad in ("rsi", "rsi_0", "rsi_14_2", "ema_3.5", "bbu_20_0", "bbu_20_11", "foo_14", "rsi_99999"):
        assert kernels.parse_column(bad) is None, bad
    assert kernels.parse_column("bbu_20_2.5") is not None


# ─── B. VectorEvaluator == LogicEvaluator ───────────────────────────────────

def _random_value(rng, depth=0):
    r = rng.random()
    if depth > 2 or r < 0.35:
        return {"frame": rng.choice(["1m", "15m"]), "column": rng.choice(["close", "open", "rsi_14", "ema_20", "bbz_20"]),
                "index": int(rng.integers(0, 3))}
    if r < 0.55:
        return float(rng.choice([0, 1, 30, 70, 100.5, -2]))
    if r < 0.8:
        return {"type": "calculate", "logic": rng.choice(["+", "-", "*", "/"]), "multiply": float(rng.choice([1, 0.5, 2])),
                "number_1": _random_value(rng, depth + 1), "number_2": _random_value(rng, depth + 1)}
    return {"type": rng.choice(["min", "max"]), "numbers": [_random_value(rng, depth + 1) for _ in range(3)]}


def test_vector_evaluator_matches_scalar_on_random_asts():
    from backend.core.signals.evaluator import LogicEvaluator, VectorEvaluator, lag_key
    rng = np.random.default_rng(7)
    n = 300
    data = {}
    for frame in ("1m", "15m"):
        for col in ("close", "open", "rsi_14", "ema_20", "bbz_20"):
            arr = rng.normal(50, 30, n)
            arr[rng.random(n) < 0.15] = np.nan
            arr[rng.random(n) < 0.05] = 0.0
            for lag in range(3):
                data[(frame, lag_key(col, lag))] = np.roll(arr, lag)
    get = lambda f, c, lag: data.get((f, lag_key(c, lag)), np.full(n, np.nan))  # noqa: E731
    vec = VectorEvaluator(n, get)
    for _ in range(300):
        tree = [[[_random_value(rng), rng.choice([">", "<", ">=", "<=", "==", "!="]), _random_value(rng)]
                 for _ in range(int(rng.integers(1, 3)))] for _ in range(int(rng.integers(1, 3)))]
        v = vec.tree(tree)
        for i in range(0, n, 7):
            ctx = {f: {k: (None if np.isnan(data[(f2, k)][i]) else float(data[(f2, k)][i]))
                       for (f2, k) in data if f2 == f} for f in ("1m", "15m")}
            assert bool(v[i]) == LogicEvaluator.evaluate_tree_ctx(tree, ctx), (tree, i)


# ─── C. Đa khung + index ────────────────────────────────────────────────────

def _engine(df1, match, stop=None, **pos):
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.params.builder import build_params
    eng = BacktestEngine(0, 0, "T", int(df1.open_time.min()), int(df1.open_time.max()),
                         initial_capital=pos.pop("capital", 10000.0))
    flow_type = pos.pop("side", "LONG")
    venue = pos.pop("venue", "cex")
    if "fee_rate" in pos and "maker_fee_rate" not in pos:
        pos["maker_fee_rate"] = pos["fee_rate"]  # test chỉ ghi một mức phí -> dùng cho cả maker
    params = build_params(f"{flow_type}_f", {"match": [{"condition": match}], "stop": [{"condition": stop or []}]},
                          flow_type, pos, venue)
    eng.add_strategy_flow(f"{flow_type}_f", params)
    eng.df_base = eng._prepare_candles(df1)
    for frame, ms in (("15m", 900_000), ("1h", 3_600_000), ("4h", 14_400_000)):
        tmp = df1.assign(dt=pd.to_datetime(df1.open_time, unit="ms", utc=True)).set_index("dt")
        agg = tmp.resample(f"{ms // 60000}min", closed="left", label="left").agg(
            {"open_time": "first", "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        agg["open_time"] = (agg.index.asi8 // 10**6).astype("int64")
        eng.frames[frame] = eng._prepare_candles(agg.reset_index(drop=True))
    eng.df_4h = eng.frames["4h"]
    return eng


def test_higher_frame_kernel_visible_only_after_close():
    from backend.core.backtest.engine import FRAME_MS
    df = _ohlcv(3000, seed=4)
    eng = _engine(df, [[[{"frame": "15m", "column": "rsi_14"}, ">", -1]]])
    frame_df, cols = eng._build_matrix()
    vals = cols["15m|rsi_14"]
    f15 = eng.frames["15m"]
    rsi15 = kernels.compute(f15, "rsi_14").to_numpy()
    for i in range(0, 3000, 37):
        decision = int(frame_df.open_time[i]) + 60_000
        closed = f15.open_time.to_numpy() + FRAME_MS["15m"] <= decision
        expected = rsi15[closed][-1] if closed.any() else np.nan
        np.testing.assert_allclose(vals[i], expected, equal_nan=True)


def test_index_reads_previous_bar():
    df = _ohlcv(500, seed=5)
    eng = _engine(df, [[[{"frame": "1m", "column": "close", "index": 1}, ">", 0]]])
    _, cols = eng._build_matrix()
    np.testing.assert_allclose(cols["1m|close__lag1"][1:], df.close.to_numpy()[:-1])
    assert np.isnan(cols["1m|close__lag1"][0])


def test_one_minute_kernels_ignore_filled_minutes():
    df = _ohlcv(600, seed=6)
    df["is_filled"] = 0
    df.loc[100:400:3, "is_filled"] = 1
    eng = _engine(df, [[[{"frame": "1m", "column": "sma_5"}, ">", 0]]])
    _, cols = eng._build_matrix()
    real = df[df.is_filled == 0].reset_index(drop=True)
    expect = real.close.rolling(5).mean().to_numpy()
    got = cols["1m|sma_5"][df.is_filled.to_numpy() == 0]
    np.testing.assert_allclose(got, expect, equal_nan=True)


# ─── D. Quản lý vị thế ──────────────────────────────────────────────────────

def _path(prices, t0=T0):
    """Chuỗi nến 1m đi qua các mức giá cho trước (open=close trước, high/low bao quanh)."""
    closes = np.asarray(prices, dtype=float)
    opens = np.r_[closes[0], closes[:-1]]
    return pd.DataFrame({"open_time": t0 + np.arange(len(closes), dtype=np.int64) * M, "open": opens,
                         "high": np.maximum(opens, closes), "low": np.minimum(opens, closes), "close": closes,
                         "volume": 1.0})


def _signal_at(df, i):
    return [[[{"frame": "1m", "column": "open_time"}, "==", int(df.open_time[i])]]]


def test_dca_layers_average_price_and_tp_from_average():
    # vào ở 100 -> giảm tới 98.9 (tầng 1 @99.5, tầng 2 @99.0025) -> hồi 100
    prices = [100] * 5 + [100, 99.8, 99.4, 98.9, 99.2, 99.6, 100.0, 100.4] + [100.4] * 5
    df = _path(prices)
    eng = _engine(df, _signal_at(df, 4), order_size_pct=20, dca_step_pct=0.5, dca_max_layers=3,
                  dca_size_multiplier=1.0, take_profit_rate=0.5, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    assert pos.layers == 3
    fills = np.array([100.0, 99.5, 99.5 * 0.995])
    # cùng ký quỹ mỗi tầng -> giá TB theo khối lượng = trung bình điều hoà của giá khớp
    assert pos.avg_price == pytest.approx(len(fills) / np.sum(1 / fills))
    assert pos.status.name == "TP"
    assert pos.close_price == pytest.approx(pos.avg_price * 1.005)
    assert pos.close_time > int(df.open_time[8]), "Không được chốt lời trong nến vừa khớp tầng DCA"


def test_no_take_profit_in_same_bar_as_dca_fill():
    df = _path([100] * 5 + [100, 99.4, 100.8, 100.8])
    df.loc[6, "high"] = 100.9  # nến 6: vừa chạm tầng DCA (99.5) vừa vượt TP của giá TB
    eng = _engine(df, _signal_at(df, 4), order_size_pct=20, dca_step_pct=0.5, dca_max_layers=1,
                  take_profit_rate=0.3, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    assert pos.layers == 2 and pos.close_time >= int(df.open_time[7])


def test_stop_loss_from_average_after_dca_and_ordering():
    # giá rơi thẳng 100 -> 96 trong một nến: tầng DCA @99 khớp trước, rồi SL tính từ giá TB mới
    df = _path([100] * 5 + [100, 96, 96])
    eng = _engine(df, _signal_at(df, 4), order_size_pct=50, dca_step_pct=1.0, dca_max_layers=1,
                  stop_loss_rate=2.0, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    avg = 2 / (1 / 100 + 1 / 99)  # giá TB theo khối lượng
    assert pos.layers == 2 and pos.status.name == "SL"
    assert pos.close_price == pytest.approx(avg * 0.98)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_stop_fill_extreme_uses_worst_price_of_bar(side):
    # nến 6 giật xuyên SL 2% tới 95 (long) / 105 (short): "level" khớp đúng mức, "extreme" khớp ở đáy/đỉnh nến
    move = [100] * 5 + ([100, 97, 97] if side == "LONG" else [100, 103, 103])
    df = _path(move)
    df.loc[6, "low" if side == "LONG" else "high"] = 95.0 if side == "LONG" else 105.0
    closes = {}
    for mode in ("level", "extreme"):
        eng = _engine(df, _signal_at(df, 4), side=side, market="perp", stop_loss_rate=2.0, fee_rate=0.0,
                      slippage_rate=0.0, stop_fill=mode)
        eng.run()
        pos = eng.closed_positions[0]
        assert pos.status.name == "SL"
        closes[mode] = pos.close_price
    assert closes["level"] == pytest.approx(98.0 if side == "LONG" else 102.0)
    assert closes["extreme"] == pytest.approx(95.0 if side == "LONG" else 105.0)


def test_stop_fill_rejects_unknown_mode():
    df = _path([100] * 10)
    with pytest.raises(ValueError, match="stop_fill"):
        _engine(df, _signal_at(df, 4), stop_fill="median")


def test_trailing_stop_uses_previous_peak():
    df = _path([100] * 5 + [100, 101, 103, 105, 104, 103.9, 103.0])
    eng = _engine(df, _signal_at(df, 4), trailing_stop=1.0, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    assert pos.close_price == pytest.approx(105 * 0.99) and pos.status.name == "TP"


def test_timeout_closes_at_open():
    df = _path(np.linspace(100, 101, 200))
    eng = _engine(df, _signal_at(df, 4), timeout=30, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    assert (pos.close_time - pos.enter_time) == 30 * M
    assert pos.close_reason == "Hết thời gian giữ lệnh"


def test_perp_liquidation_caps_loss_at_margin():
    df = _path([100] * 5 + [100, 94, 90, 90])
    eng = _engine(df, _signal_at(df, 4), market="perp", leverage=20, order_size_pct=10,
                  fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    liq = 100 * (1 - 1 / 20 + 0.005)
    assert pos.status.name == "LIQ" and pos.close_price == pytest.approx(liq)
    assert pos.real_pnl >= -1000.0 - 1e-6  # mất tối đa ký quỹ 10% vốn
    assert pos.real_pnl == pytest.approx(-1000.0 * (1 - 0.005 * 20), rel=1e-6)


def test_spot_rejects_short_and_leverage():
    df = _path([100] * 20)
    with pytest.raises(ValueError, match="spot"):
        _engine(df, _signal_at(df, 4), side="SHORT")
    with pytest.raises(ValueError, match="đòn bẩy"):
        _engine(df, _signal_at(df, 4), leverage=5)


def test_dex_perp_rejected_and_venue_fees():
    from backend.core.params.builder import resolve_costs
    assert resolve_costs("cex", "spot", None, None) == (0.001, 0.001, 0.0002)
    assert resolve_costs("cex", "perp", None, None) == (0.0005, 0.0002, 0.0002)  # Binance USDT-M VIP0
    assert resolve_costs("dex", "spot", None, None) == (0.003, 0.003, 0.001)
    with pytest.raises(ValueError):
        resolve_costs("dex", "perp", None, None)


def test_fees_charged_on_every_layer_and_exit():
    df = _path([100] * 5 + [100, 99.4, 99.4, 101, 101])
    eng = _engine(df, _signal_at(df, 4), order_size_pct=10, dca_step_pct=0.5, dca_max_layers=1,
                  take_profit_rate=0.5, fee_rate=0.001, slippage_rate=0.0)
    eng.run()
    pos = eng.closed_positions[0]
    notional = 1000 + 1000
    exit_fee = pos.qty * pos.close_price * 0.001
    assert pos.fees_usd == pytest.approx(notional * 0.001 + exit_fee)
    gross = pos.qty * (pos.close_price - pos.avg_price)
    assert pos.real_pnl == pytest.approx(gross - pos.fees_usd)


def test_mark_to_market_drawdown_sees_floating_loss():
    # lệnh lỗ treo sâu (-8%) rồi hồi về có lãi: MDD theo lệnh đóng = 0, MDD MTM phải thấy lỗ treo
    from backend.core.metrics.portfolio import curve_mdd_pct
    from backend.core.metrics.returns import equity_mdd_pct
    prices = [100] * 5 + list(np.linspace(100, 92, 120)) + list(np.linspace(92, 101, 120))
    df = _path(prices)
    eng = _engine(df, _signal_at(df, 4), take_profit_rate=0.8, fee_rate=0.0, slippage_rate=0.0)
    eng.run()
    closed_only = equity_mdd_pct([p.profit_pct / 100.0 for p in eng.closed_positions])   # vốn chỉ đổi khi đóng lệnh
    mtm = curve_mdd_pct(eng.equity_curve, 0, 10000.0)
    assert closed_only == 0.0
    assert mtm > 7.5
    assert eng.closed_positions[0].mae_pct < -7.5


def test_prefix_check_detects_a_lookahead_kernel():
    """Chính phép kiểm causal phải bắt được một kernel nhìn tương lai (trung bình trượt căn giữa)."""
    df = _ohlcv(400, seed=9)
    leaky = lambda d: d["close"].rolling(21, center=True, min_periods=21).mean()  # noqa: E731
    full = leaky(df).to_numpy()
    part = leaky(df.iloc[:300].reset_index(drop=True)).to_numpy()
    assert not np.allclose(part, full[:300], equal_nan=True)


# ─── E. Công cụ kiểm tra tín hiệu phải phân biệt được edge thật và nhiễu ─────

def _dataset(tmp_path, monkeypatch, returns, name):
    from backend.core.data.resampler import save_resampled_dataset
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    df = pd.DataFrame({"open_time": T0 + np.arange(len(close), dtype=np.int64) * M, "open": open_,
                       "high": np.maximum(open_, close) * 1.0001, "low": np.minimum(open_, close) * 0.9999,
                       "close": close, "volume": 10.0})
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    save_resampled_dataset(symbol=name, output_dir=str(root / "cex"), df_1m_raw=df, pool_address="x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                           extra_meta={"venue": "cex", "exchange": "test", "checksums_verified": True})


DOWN_MINUTE = {"t": {"side": "LONG", "tree": [[[{"frame": "1m", "column": "roc_3"}, "<", -0.25]]]}}


def test_diagnostics_detects_planted_edge(tmp_path, monkeypatch):
    from backend.core.signals.diagnostics import check_signals
    rng = np.random.default_rng(11)
    n = 40 * 1440
    eps = rng.normal(0, 0.001, n)
    r = np.zeros(n)
    for i in range(1, n):  # hồi về mạnh: sau nhịp giảm là nhịp tăng
        r[i] = -0.45 * r[i - 1] + eps[i]
    _dataset(tmp_path, monkeypatch, r, "EDGE")
    res = check_signals("EDGE", DOWN_MINUTE, horizons_min=(15, 60))["signals"]["t"]
    assert res["verdict"] == "CO_THONG_TIN" and res["t_stat"] > 3, res


def test_diagnostics_rejects_random_walk(tmp_path, monkeypatch):
    from backend.core.signals.diagnostics import check_signals
    rng = np.random.default_rng(12)
    _dataset(tmp_path, monkeypatch, rng.normal(0, 0.001, 40 * 1440), "NOISE")
    res = check_signals("NOISE", DOWN_MINUTE, horizons_min=(15, 60))["signals"]["t"]
    assert res["verdict"] != "CO_THONG_TIN", res


def test_spot_equity_never_negative_and_size_follows_equity():
    """Lỗi đã gặp: khối lượng theo vốn cố định -> thua liên tục vẫn vào lệnh 10.000 USD, lỗ -898%."""
    rng = np.random.default_rng(21)
    prices = 100 * np.exp(np.cumsum(rng.normal(-0.0004, 0.002, 6000)))  # xu hướng giảm đều
    df = _path(prices)
    eng = _engine(df, [[[{"frame": "1m", "column": "close"}, ">", 0]]], stop_loss_rate=0.3, take_profit_rate=0.3,
                  fee_rate=0.003, slippage_rate=0.001)
    eng.run()
    equity = [p["equity"] for p in eng.equity_curve]
    assert min(equity) > -1e-6, "Spot không thể mất quá 100% vốn"
    first, last = eng.closed_positions[0], eng.closed_positions[-1]
    assert last.entry_margin_usd < first.entry_margin_usd * 0.5, "Khối lượng phải co lại theo vốn hiện tại"


def test_cross_over_is_an_event_on_the_frame_bar():
    """cross_over(a, b) = a > b và a[1] <= b[1] trên nến của khung (ta.crossover, KEMA của sova): đúng ở nến cắt, không đúng suốt đoạn
    a > b. Ở lưới 1m, tín hiệu chỉ bật trong các phút thuộc nến 15m ngay sau nến cắt đóng."""
    from backend.core.strategy.library import cross_over
    df = _ohlcv(6000, seed=11)
    a, b = {"frame": "15m", "column": "close"}, {"frame": "15m", "column": "dch_20"}
    eng = _engine(df, [[list(t) for t in cross_over(a, b)]])
    df1, cols = eng._build_matrix()
    from backend.core.signals.evaluator import VectorEvaluator, lag_key
    vec = VectorEvaluator(len(df1), lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(len(df1), np.nan)))
    cross = vec.tree([[list(t) for t in cross_over(a, b)]])
    state = vec.tree([[[a, ">", b]]])
    f15 = eng.frames["15m"]
    close, dch = f15["close"].to_numpy(), kernels.compute(f15, "dch_20").to_numpy()
    with np.errstate(invalid="ignore"):
        n_cross = int(np.sum((close[1:] > dch[1:]) & (close[:-1] <= dch[:-1])))
    starts = np.flatnonzero(np.diff(np.r_[0, cross.astype(np.int8)]) == 1)
    assert 0 < len(starts) == n_cross                          # mỗi điểm cắt trên khung -> một đoạn tín hiệu
    assert cross.sum() < state.sum() and not (cross & ~state).any()
