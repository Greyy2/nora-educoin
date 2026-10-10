"""P12-A: tín hiệu VÀO khung lớn hơn khung chạy kích theo SỰ KIỆN (nến khung vừa đóng), không phải trạng thái lặp ở mọi nến chạy.
core/backtest.py::entry_event_mask là MỘT định nghĩa cho batch / KernelBook (live) / snapshot / reference_engine."""
import numpy as np
import pandas as pd
import pytest

from backend.core import strategy as bt
from backend.core.strategy import entry_event_mask, evaluate_signals, matrix_evaluator
from backend.nautilus.engine import BacktestEngine
from backend.core.params import build_params
from test_kernel_parity import hexify

M = 60_000
DAY = 86_400_000
T0 = 19_700 * DAY                     # 00:00 UTC, trùng biên nến ngày
FR_MIN = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
F = lambda fr, c, i=0: {"frame": fr, "column": c, "index": i}  # noqa: E731


def _walk(n, seed=3, vol=0.0015):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0005, n)))
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1.0, "is_filled": 0})


def _frames(df1):
    out = {}
    for fr, mins in FR_MIN.items():
        tmp = df1.assign(dt=pd.to_datetime(df1.open_time, unit="ms", utc=True)).set_index("dt")
        agg = tmp.resample(f"{mins}min", closed="left", label="left").agg(
            {"open_time": "first", "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        agg["open_time"] = (agg.index.asi8 // 10**6).astype("int64")
        out[fr] = agg.reset_index(drop=True)
    return out


def _engine(df1, tree, signal_mode=None, **pos):
    eng = BacktestEngine(0, 0, "T", int(df1.open_time.min()), int(df1.open_time.max()), initial_capital=10000.0)
    if signal_mode:
        pos["signal_mode"] = signal_mode
    params = build_params("LONG_f", {"match": [{"condition": tree}], "stop": [{"condition": []}]}, "LONG",
                          {"market": "spot", "fee_rate": 0.0, "slippage_rate": 0.0, "cooldown": 0, **pos}, "cex")
    eng.add_strategy_flow("LONG_f", params)
    eng.df_base = eng._prepare_candles(df1)
    eng.frames = {fr: eng._prepare_candles(d) for fr, d in _frames(df1).items()}
    eng.df_4h = eng.frames["4h"]
    return eng


def _masks(eng):
    df1, cols = eng._build_matrix()
    vec = matrix_evaluator(cols, len(df1))
    return df1, entry_event_mask(vec, cols, eng.slots[0], eng.base_frame), vec.tree(eng.slots[0].match_tree)


DAILY = [[[F("24h", "close"), ">", 0]]]       # luôn đúng từ khi có nến ngày đầu tiên đóng


def test_a_daily_signal_stop_out_no_reentry_until_next_daily_close():
    df = _walk(4 * 1440 + 5)
    ev, lv = (_engine(df, DAILY, mode, stop_loss_rate=0.15) for mode in ("event", "level"))
    ev.run(); lv.run()
    et = [p.enter_time for p in ev.closed_positions]
    lt = [p.enter_time for p in lv.closed_positions]
    assert len(lt) > len(et) >= 2, (len(lt), len(et))                   # level: mua lại ngay sau cắt lỗ; event thì không
    assert all(t % DAY == 0 for t in et), [(t - T0) / M for t in et]    # chỉ vào ở nến chạy đầu tiên sau khi nến ngày đóng
    assert len(set(et)) == len(et) and len(et) <= 4
    assert len(ev.closed_positions) < len(lv.closed_positions) and len(ev.closed_positions) > 1   # có cắt lỗ trong ngày mà không mua lại


def test_b_frame_equals_base_bit_identical_to_level():
    df = _walk(3000, seed=5)
    tree = [[[F("1m", "close"), ">", F("1m", "sma_20")], [F("1m", "rsi_14"), "<", 60]]]
    runs = []
    for mode in ("event", "level"):
        eng = _engine(df, tree, mode, stop_loss_rate=0.3, take_profit_rate=0.4)
        eng.run()
        runs.append(([hexify(p) for p in eng.closed_positions], [hexify(o) for o in eng.orders]))
    assert runs[0][0] and runs[0] == runs[1]
    _, ev, lv = _masks(_engine(df, tree, "event"))
    assert np.array_equal(ev, lv)


def test_c_mixed_frame_tree_uses_largest_frame():
    df = _walk(3 * 1440, seed=8)
    # AND giữa 1m và 1h -> khung tín hiệu 1h ; OR thêm khối 4h -> khung tín hiệu 4h (khung lớn nhất trong lá)
    t1 = [[[F("1m", "close"), ">", 0], [F("1h", "close"), ">", 0]]]
    t2 = [[[F("1m", "close"), ">", 0]], [[F("4h", "close"), ">", 0]]]
    d1, m1, lvl1 = _masks(_engine(df, t1))
    d2, m2, lvl2 = _masks(_engine(df, t2))
    t = d1.open_time.to_numpy()
    h1 = (t + M) % (60 * M) == 0           # nến chạy đóng cùng lúc nến 1h đóng
    h4 = (t + M) % (240 * M) == 0
    assert np.array_equal(m1, lvl1 & h1) and np.array_equal(m2, lvl2 & h4)
    assert 0 < m1.sum() < lvl1.sum() and 0 < m2.sum() < m1.sum()


def test_fresh_column_carries_over_filled_minutes():
    df = _walk(2 * 1440, seed=9)
    df.loc[1439, "is_filled"] = 1          # phút đóng nến ngày 1 là nến điền: sự kiện chuyển sang nến thực kế tiếp
    eng = _engine(df, DAILY)
    d1, ev, _ = _masks(eng)
    fire = np.flatnonzero(ev)
    assert list(fire[:1]) == [1440] and d1.open_time[1440] == T0 + DAY


def test_d_live_step_equals_batch():
    """Đường live (evaluate_signals trên nến đã đóng tới thời điểm hiện tại) cho cùng tín hiệu vào với batch ở từng nến đo."""
    df = _walk(3 * 1440, seed=11)
    st = {"id": "s", "side": "LONG", "tree": DAILY, "stop": [], "position": {"market": "spot", "fee_rate": 0.0, "slippage_rate": 0.0}}
    full = evaluate_signals("T@perp", [st], {"1m": df, **_frames(df)}, "1m")["entries"][0]["match"]
    assert full.sum() == 3                                             # 3 nến ngày đóng trong dữ liệu
    for k in (1438, 1439, 1440, 1441, 2000, 2878, 2879, 2880, 4318, 4319):
        part = df.iloc[: k + 1].reset_index(drop=True)
        frames = _frames(part)
        frames = {fr: d[d.open_time + FR_MIN[fr] * M <= part.open_time.iloc[-1] + M] for fr, d in frames.items()}   # chỉ nến khung đã đóng
        live = evaluate_signals("T@perp", [st], {"1m": part, **frames}, "1m")["entries"][0]["match"]
        assert bool(live[-1]) == bool(full[k]), k


def test_signal_mode_level_keeps_old_state_semantics():
    df = _walk(2 * 1440, seed=2)
    _, ev, lv = _masks(_engine(df, DAILY, "level"))
    assert np.array_equal(ev, lv) and lv.sum() > 1000


def test_bad_signal_mode_rejected():
    with pytest.raises(ValueError):
        _engine(_walk(100), DAILY, "bogus")
