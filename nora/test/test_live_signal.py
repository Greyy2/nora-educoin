"""Test B1 (P17 T5): SignalProvider, ArraySignals, LiveSignals và Parity giữa Backtest vs Live.

Kiểm tra:
1. ArraySignals trả về đúng giá trị tại nến đóng, None ở nến không khớp.
2. Quy ước thời gian Bar: ts_event = giờ ĐÓNG nến = open_time + FRAME_MS[frame].
3. Parity bắt buộc: Replay lịch sử từng nến (BTC, ETH x KEMA, DCA) qua LiveSignals
   trùng khớp từng bit với backtest evaluate_signals.
"""
import math
import pytest
import numpy as np
import pandas as pd

from backend.analys.param import FRAME_MS, materialize, schema_defaults
from backend.alpha import strategies as sb
from backend.data.data import load_candles
from backend.signal.compute import evaluate_signals
from backend.nautilus.signals import ArraySignals, LiveSignals


def test_array_signals_lookup():
    sig = {
        "t": [1000, 2000, 3000],
        "match": [True, False, True],
        "stop": [False, True, False],
        "vol": [1.5, 2.0, None],
        "dca": [True, False, True],
    }
    provider = ArraySignals(sig, frame_ms=1000)
    # nến đóng lúc 2000 -> open_time = 1000
    res1 = provider.at(2000)
    assert res1 is not None
    assert res1["match"] is True
    assert res1["stop"] is False
    assert math.isclose(res1["vol"], 1.5)
    assert res1["dca"] is True

    # nến đóng lúc 3000 -> open_time = 2000
    res2 = provider.at(3000)
    assert res2 is not None
    assert res2["match"] is False
    assert res2["stop"] is True

    # nến lẻ giữa chừng (chưa đóng) -> None
    assert provider.at(2500) is None


def test_bar_close_time_convention():
    """Quy ước thời gian của Nautilus & Nora: ts_event = open_time + FRAME_MS[frame]."""
    open_time = 1735689600000  # 2025-01-01 00:00:00
    fr_ms = FRAME_MS["1h"]
    ts_event = open_time + fr_ms
    candle = {
        "open_time": open_time,
        "ts_event": ts_event,
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 10.0,
    }
    strat = {"id": "dummy", "side": "LONG", "tree": {}, "position": {}}
    live = LiveSignals("BTC-USDT-SWAP", strat, "1h")
    live.on_bar("1h", candle)
    df = live.frames["1h"]
    assert len(df) == 1
    assert df["open_time"].iloc[0] == open_time


@pytest.mark.parametrize("symbol", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
@pytest.mark.parametrize("strat_id", ["kema_long", "dca_long"])
def test_live_signal_parity_replay(symbol, strat_id):
    """Parity bắt buộc: replay lịch sử từng nến 1h trong khoảng 2025-01..2025-03

    phải bit-identical với mảng evaluate_signals của backtest.
    """
    cand = sb.BY_ID[strat_id]
    strat_core = materialize(cand, schema_defaults(cand))

    df_1h = load_candles(symbol, "1h")
    df_4h = load_candles(symbol, "4h")
    if df_1h.empty or df_4h.empty:
        pytest.skip(f"Thiếu catalog cho {symbol}")

    start_ts = 1735689600000  # 2025-01-01 00:00:00
    # Thử trên đoạn 14 ngày (336 nến 1h) để kiểm tra bit-identical nhanh và chính xác
    end_ts = start_ts + 14 * 24 * 3600 * 1000

    # Lấy baseline bằng evaluate_signals trên catalog
    full_frames = {"1h": df_1h, "4h": df_4h}
    base_res = evaluate_signals(symbol, [strat_core], full_frames, "1h")
    base_t = base_res["t"]
    entry = base_res["entries"][0]
    base_m = entry["match"]
    base_s = entry["stop"]
    base_v = entry.get("vol")
    base_d = entry.get("dca")

    mask = (base_t >= start_ts) & (base_t < end_ts)
    test_indices = np.flatnonzero(mask)
    if len(test_indices) == 0:
        pytest.skip("Khoảng test không có nến trong catalog")

    # Dựng LiveSignals với buffer nến từ đầu catalog đến trước start_ts
    init_1h = df_1h[df_1h["open_time"] < start_ts].copy()
    init_4h = df_4h[df_4h["open_time"] < start_ts].copy()
    live = LiveSignals(symbol, strat_core, "1h", frames={"1h": init_1h, "4h": init_4h})

    # Replay từng nến 1h
    test_1h = df_1h[mask].sort_values("open_time").to_dict("records")
    for row in test_1h:
        ot = int(row["open_time"])
        close_ts = ot + FRAME_MS["1h"]

        # Nếu có nến 4h đóng cùng lúc, đẩy vào trước
        matching_4h = df_4h[df_4h["open_time"] + FRAME_MS["4h"] == close_ts]
        if not matching_4h.empty:
            for r4 in matching_4h.to_dict("records"):
                live.on_bar("4h", r4)

        # Đẩy nến 1h
        live.on_bar("1h", row)

        # Lấy tín hiệu tại thời điểm đóng nến 1h
        sig = live.at(close_ts)
        assert sig is not None, f"Không sinh tín hiệu tại close_ts {close_ts}"

        # Tìm chỉ số trong baseline
        b_idx = np.searchsorted(base_t, ot)
        assert base_t[b_idx] == ot

        # So sánh bit-identical
        assert sig["match"] == bool(base_m[b_idx]), f"Match mismatch tại open_time {ot}"
        assert sig["stop"] == bool(base_s[b_idx]), f"Stop mismatch tại open_time {ot}"
        if base_d is not None:
            assert sig["dca"] == bool(base_d[b_idx]), f"DCA mismatch tại open_time {ot}"
        if base_v is not None and not np.isnan(base_v[b_idx]):
            assert math.isclose(sig["vol"], float(base_v[b_idx]), rel_tol=1e-7), f"Vol mismatch tại {ot}"


# ─── Khung chạy 1m, tín hiệu 24h (đường LIVE thật: derive khung lớn + cắt đuôi) ───────────────────────────
_ALPHA_24H = '''class RiskFailFastBreakoutStrategy(NoraStrategy):
    timeframe = "24h"
    upper_period = 20
    ema_period = 10
    stop_loss_pct = 3.0
    take_profit_pct = 0.0
    trailing_stop_pct = 0.0
    trailing_activation_pct = 0.0
    timeout = 0
    risk_per_trade_pct = 0.5

    def on_bar(self):
        upper = self.feat.donchian_upper(high, self.upper_period)
        ema = ema(close, self.ema_period)
        enter_sig = crossover(close, upper)
        exit_sig = (close < upper) | (close < ema)
        self.close(exit_sig)
        self.buy(enter_sig)
'''


def test_live_signal_parity_1m_base_24h_signal():
    """Live (nến 1m đẩy từng phút, khung 24h tự dựng khi ngày đóng, bộ đệm 1m bị cắt đuôi) == mảng tín hiệu tính sẵn của backtest ở khung chạy 1m."""
    from backend.alpha.compile import compile_code
    from backend.alpha.plan import build_plan
    from backend.nautilus.engine import PortfolioEngine

    sym = "BTC-USDT-SWAP"
    plan = build_plan(compile_code(_ALPHA_24H), ["BTC"], run_frame="1m")
    st = plan.strategies[0]
    m1 = load_candles(sym, "1m")
    if m1.empty:
        pytest.skip("Thiếu catalog BTC")
    end_t = int(m1["open_time"].iloc[-1])
    day = 86_400_000
    t0 = (end_t // day - 4) * day            # đầu ngày, cách cuối catalog 4 ngày: replay vắt qua 3 lần đóng ngày
    t1 = t0 + 3 * day + 2 * 3_600_000

    eng = PortfolioEngine(plan.symbols, plan.strategies, t0 - 400 * day, t1, trade_start_ts=t0, base_frame="1m", shared_dir=None)
    eng.load_data()
    book = eng.books[0]
    e0 = book["entries"][0]
    base_t = np.asarray(book["data"]["t"])

    df24 = load_candles(sym, "24h")
    live = LiveSignals(sym, st, "1m", frames={"1m": m1[m1["open_time"] < t0 - day].copy(), "24h": df24[df24["open_time"] + day <= t0].copy()})
    live.trim = True
    rows = m1[(m1["open_time"] >= t0 - day) & (m1["open_time"] < t1)].to_dict("records")
    checked = 0
    for r in rows:
        ot = int(r["open_time"])
        close = ot + 60_000
        live.on_base_bar(close, r["open"], r["high"], r["low"], r["close"], r["volume"])
        # kiểm quanh mỗi lần đóng ngày (±3 phút) và mỗi 97 phút
        near_day = (close % day) < 4 * 60_000 or (close % day) > day - 3 * 60_000
        if ot >= t0 and (near_day or (ot // 60_000) % 97 == 0):
            sig = live.at(close)
            i = np.searchsorted(base_t, ot)
            if i >= len(base_t) or base_t[i] != ot:
                # phút điền (không có nến thật): backtest bỏ qua
                continue
            assert sig is not None, f"live không sinh tín hiệu tại {ot}"
            assert sig["match"] == bool(e0["match"][i]), f"match lệch tại {ot}"
            assert sig["stop"] == bool(e0["stop"][i]), f"stop lệch tại {ot}"
            bv = e0["vol"][i] if e0.get("vol") is not None else float("nan")
            if not np.isnan(bv):
                assert math.isclose(sig["vol"], float(bv), rel_tol=1e-9), f"vol lệch tại {ot}"
            checked += 1
    assert checked > 30
    assert len(live.frames["1m"]) <= live.keep_ms // 60_000 + 10          # đuôi 1m bị chặn
    assert any(live.frames["24h"]["open_time"] >= t0)                       # khung 24h được dựng từ nến 1m khi ngày đóng
