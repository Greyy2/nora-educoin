"""Gate 1.1: Signal Fixture & Oracle Verification for Fast Dip Harvester Strategy (EDU Side).

Yêu cầu nghiệm thu Gate 1.1:
1. Fixture OHLCV cố định (deterministic) 120 nến, đủ warmup cho RSI(10), SMA(15), EMA(50).
2. Oracle độc lập tính toán giá trị indicator, tín hiệu boolean entry/exit và timestamp từng bar.
3. Bao gồm các kịch bản bắt buộc:
   - Clean Entry (crossover RSI qua 40 & Close > SMA & Close > EMA)
   - Signal Exit qua RSI > 65
   - Signal Exit qua Close crossunder SMA
   - Trùng điều kiện Entry/Exit cùng bar (kiểm tra thứ tự ưu tiên trong DSL)
   - Tín hiệu ở nến cuối cùng (final bar guard)
4. Tiêu chí PASS: Khớp 100% tín hiệu và intent; nếu có sai khác phải có trace bar chi tiết.
"""
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

# ── 1. ĐỘC LẬP: ORACLE TOÁN HỌC THUẦN (INDEPENDENT MATHEMATICAL ORACLE) ──

def oracle_sma(prices: np.ndarray, period: int = 15) -> np.ndarray:
    """SMA chuẩn: trung bình trượt đơn giản."""
    out = np.full_like(prices, np.nan, dtype=np.float64)
    for i in range(period - 1, len(prices)):
        out[i] = np.mean(prices[i - period + 1 : i + 1])
    return out

def oracle_ema(prices: np.ndarray, period: int = 50) -> np.ndarray:
    """EMA chuẩn TradingView (ta.ema): n nến đầu là NaN, nến n-1 là SMA n nến đầu, sau đó s = alpha*x + (1-alpha)*s."""
    out = np.full_like(prices, np.nan, dtype=np.float64)
    if len(prices) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        out[i] = alpha * prices[i] + (1.0 - alpha) * out[i - 1]
    return out

def oracle_rsi(prices: np.ndarray, period: int = 10) -> np.ndarray:
    """RSI chuẩn Wilder: phương pháp làm mịn mũ của J. Welles Wilder."""
    out = np.full_like(prices, np.nan, dtype=np.float64)
    deltas = np.diff(prices)
    if len(prices) <= period:
        return out

    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(prices)):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out

def oracle_crossover(series: np.ndarray, threshold: float) -> np.ndarray:
    """Crossover vượt qua ngưỡng: series[t] > threshold và series[t-1] <= threshold."""
    out = np.zeros(len(series), dtype=bool)
    for t in range(1, len(series)):
        if np.isnan(series[t]) or np.isnan(series[t - 1]):
            continue
        out[t] = bool(series[t] > threshold and series[t - 1] <= threshold)
    return out

def oracle_crossunder(series_a: np.ndarray, series_b: np.ndarray) -> np.ndarray:
    """Crossunder cắt xuống: a[t] < b[t] và a[t-1] >= b[t-1]."""
    out = np.zeros(len(series_a), dtype=bool)
    for t in range(1, len(series_a)):
        if np.isnan(series_a[t]) or np.isnan(series_b[t]) or np.isnan(series_a[t - 1]) or np.isnan(series_b[t - 1]):
            continue
        out[t] = bool(series_a[t] < series_b[t] and series_a[t - 1] >= series_b[t - 1])
    return out


# ── 2. FIXTURE DỮ LIỆU TẤT ĐỊNH 120 BARS (DETERMINISTIC OHLCV FIXTURE) ──

def build_gate1_1_fixture_df() -> pd.DataFrame:
    n = 120
    day_ms = 86400 * 1000
    times = np.arange(n, dtype=np.int64) * day_ms

    closes = np.full(n, 50000.0, dtype=np.float64)
    # 0..59: Warmup dao động nhẹ quanh 50,000 để ổn định EMA(50) và SMA(15)
    for i in range(60):
        closes[i] = 50000.0 + 150.0 * np.sin(i * 0.4)

    # 60..64: Giá giảm tạo đáy cho RSI rớt về vùng < 35
    closes[60] = 49500.0
    closes[61] = 49000.0
    closes[62] = 48500.0
    closes[63] = 47800.0
    closes[64] = 47200.0

    # 65: Bứt phá tạo Clean Entry 1 (RSI cắt lên 40, Close > SMA15, Close > EMA50)
    closes[65] = 50800.0

    # 66..71: Tăng giá liên tục
    closes[66] = 51600.0
    closes[67] = 52500.0
    closes[68] = 53500.0
    closes[69] = 54800.0
    closes[70] = 55900.0
    closes[71] = 57200.0

    # 72: Tăng vọt tạo Signal Exit 1 (RSI > 65)
    closes[72] = 59000.0

    # 73..77: Hạ nhiệt giá
    closes[73] = 57000.0
    closes[74] = 55000.0
    closes[75] = 53500.0
    closes[76] = 52000.0
    closes[77] = 50500.0

    # 78..79: Tạo dip và Entry 2
    closes[78] = 49500.0
    closes[79] = 54500.0

    # 80..83: Duy trì trên SMA15
    closes[80] = 55000.0
    closes[81] = 55200.0
    closes[82] = 55100.0
    closes[83] = 55000.0

    # 84: Giá rơi đột ngột thủng SMA15 tạo Signal Exit 2 (Close crossunder SMA15)
    closes[84] = 50000.0

    # 85..109: Vùng giá đi ngang 50,000
    for i in range(85, 110):
        closes[i] = 50000.0 + 100.0 * np.cos(i * 0.3)

    # 110: Kịch bản trùng điều kiện (Edge case: Close > SMA & Close > EMA nhưng đồng thời gán exit)
    closes[110] = 50500.0

    # 111..116: Dao động bình thường
    for i in range(111, 117):
        closes[i] = 50000.0 + 80.0 * np.sin(i * 0.5)

    # 117..118: Tạo dip trước nến cuối
    closes[117] = 48000.0
    closes[118] = 47500.0

    # 119 (Nến cuối cùng): Bứt phá tạo Entry tại nến cuối cùng
    closes[119] = 51000.0

    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    highs = np.maximum(opens, closes) + 200.0
    lows = np.minimum(opens, closes) - 200.0
    volumes = np.full(n, 100.0, dtype=np.float64)

    return pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


# ── 3. TEST CASES GATE 1.1 ──

FAST_DIP_CODE = """class FastDipHarvesterStrategy(NoraStrategy):
    timeframe = '24h'
    rsi_period = 10
    sma_period = 15
    macro_period = 50
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        rsi_val = rsi(close, self.rsi_period)
        sma_val = sma(close, self.sma_period)
        macro = ema(close, self.macro_period)

        self.close((rsi_val > 65.0) | crossunder(close, sma_val))
        self.buy(crossover(rsi_val, 40.0) & (close > sma_val) & (close > macro))
"""

def test_gate1_1_indicator_precision_against_oracle():
    """Kiểm tra độ chính xác chỉ báo Nora kernels so với Independent Oracle."""
    from backend.analys.indicator import compute

    df = build_gate1_1_fixture_df()
    closes = df["close"].to_numpy()

    oracle_r = oracle_rsi(closes, period=10)
    oracle_s = oracle_sma(closes, period=15)
    oracle_e = oracle_ema(closes, period=50)

    nora_r = compute(df, "rsi_10").to_numpy()
    nora_s = compute(df, "sma_15").to_numpy()
    nora_e = compute(df, "ema_50").to_numpy()

    # So sánh sau warmup (bar 60 trở đi)
    for t in range(60, len(df)):
        assert abs(nora_r[t] - oracle_r[t]) < 1e-6, f"Bar {t}: RSI Nora={nora_r[t]} vs Oracle={oracle_r[t]}"
        assert abs(nora_s[t] - oracle_s[t]) < 1e-6, f"Bar {t}: SMA Nora={nora_s[t]} vs Oracle={oracle_s[t]}"
        assert abs(nora_e[t] - oracle_e[t]) < 1e-6, f"Bar {t}: EMA Nora={nora_e[t]} vs Oracle={oracle_e[t]}"


def test_gate1_1_signals_parity_and_oracle_trace():
    """Kiểm tra 100% khớp tín hiệu giữa Oracle độc lập và Nora Compiler trên từng bar."""
    from backend.analys.alpha.code.compile import compile_code

    df = build_gate1_1_fixture_df()
    closes = df["close"].to_numpy()

    # 1. Oracle tính toán tín hiệu
    o_rsi = oracle_rsi(closes, period=10)
    o_sma = oracle_sma(closes, period=15)
    o_ema = oracle_ema(closes, period=50)

    o_cross_rsi = oracle_crossover(o_rsi, 40.0)
    o_crossunder_sma = oracle_crossunder(closes, o_sma)

    oracle_buy = o_cross_rsi & (closes > o_sma) & (closes > o_ema)
    oracle_exit = (o_rsi > 65.0) | o_crossunder_sma

    # 2. Nora Compiler tính toán qua IR
    prog = compile_code(FAST_DIP_CODE, register=False)
    from backend.analys.signal.signal import Ctx
    n, data = prog._data(df)
    ctx = Ctx(n, data)
    nora_exit = np.asarray(prog.calls[0][0].ev(ctx), dtype=bool)
    nora_buy = np.asarray(prog.calls[1][0].ev(ctx), dtype=bool)

    # 3. Đối soát 100% từng bar cho CẢ Entry và Exit
    entry_mismatches = []
    exit_mismatches = []
    for t in range(len(df)):
        exp_buy = bool(oracle_buy[t])
        act_buy = bool(nora_buy[t])
        if exp_buy != act_buy:
            entry_mismatches.append({
                "bar": t, "close": float(closes[t]),
                "oracle_buy": exp_buy, "nora_buy": act_buy,
            })
        exp_exit = bool(oracle_exit[t])
        act_exit = bool(nora_exit[t])
        if exp_exit != act_exit:
            exit_mismatches.append({
                "bar": t, "close": float(closes[t]),
                "oracle_exit": exp_exit, "nora_exit": act_exit,
            })

    assert len(entry_mismatches) == 0, f"Phát hiện {len(entry_mismatches)} bar lệch tín hiệu Entry: {entry_mismatches}"
    assert len(exit_mismatches) == 0, f"Phát hiện {len(exit_mismatches)} bar lệch tín hiệu Exit: {exit_mismatches}"

    # 4. Kiểm tra các mốc sự kiện cụ thể đã thiết kế
    # Clean Entry 1 tại Bar 65
    assert bool(nora_buy[65]) is True, "Bar 65 phải kích hoạt Clean Entry 1"
    assert bool(oracle_buy[65]) is True

    # Signal Exit 1 tại Bar 72 (RSI > 65)
    assert bool(nora_exit[72]) is True, "Bar 72 phải kích hoạt Exit do RSI > 65"
    assert bool(oracle_exit[72]) is True
    assert o_rsi[72] > 65.0

    # Clean Entry 2 tại Bar 79
    assert bool(nora_buy[79]) is True, "Bar 79 phải kích hoạt Entry 2"
    assert bool(oracle_buy[79]) is True

    # Signal Exit 2 tại Bar 84 (Close crossunder SMA15)
    assert bool(nora_exit[84]) is True, "Bar 84 phải kích hoạt Exit do thủng SMA15"
    assert bool(oracle_exit[84]) is True
    assert bool(o_crossunder_sma[84]) is True

    # Final Bar Guard tại Bar 119
    assert bool(nora_buy[119]) is True, "Bar 119 (nến cuối) ghi nhận tín hiệu Entry"
    assert bool(oracle_buy[119]) is True


def test_gate1_1_final_bar_signal_has_no_fill_on_production_path():
    """Kiểm tra tín hiệu tại nến cuối cùng không bao giờ sinh fill trên production engine vì thiếu nến kế tiếp."""
    from backend.core.backtest import NautilusRun
    from backend.analys.alpha import RiskConfig
    from backend.analys.param import StrategyParams
    from backend.analys.position import SlotSpec
    from backend.models.models import PositionType

    class LocalStubDataSource:
        def __init__(self, symbol, frame, times, opens, highs, lows, closes, vols):
            self.symbol = symbol
            self.frame = frame
            self._arrays = {
                "t": np.array(times, dtype=np.int64),
                "o": np.array(opens, dtype=np.float64),
                "h": np.array(highs, dtype=np.float64),
                "l": np.array(lows, dtype=np.float64),
                "c": np.array(closes, dtype=np.float64),
                "v": np.array(vols, dtype=np.float64),
            }
            self._spec = {
                "tickSz": "0.1", "lotSz": "0.01", "ctVal": "1.0", "minSz": "0.01",
                "margin_init": "0.1", "margin_maint": "0.05", "maker_fee": "0.0002", "taker_fee": "0.0005",
                "base_symbol": "BTC",
            }
        def exec_arrays(self, symbol, frame, start, end): return self._arrays
        def instrument_spec(self, symbol): return self._spec
        def require_ok(self, symbols): pass

    def local_make_slot(symbol):
        params = StrategyParams(
            market="perp", leverage=1, stop_loss_rate=0.0, take_profit_rate=0.0,
            fee_rate=0.0005, maker_fee_rate=0.0002, slippage_rate=0.0003,
            order_size_pct=0.1, max_capital_usage=1.0,
        )
        return SlotSpec(
            account_id=0,
            campaign_id=0,
            symbol=symbol,
            flow_name="test_flow",
            params=params,
            pos_type=PositionType.LONG,
            initial_capital=10_000.0,
        )

    symbol = "BTC-USDT-SWAP"
    frame = "24h"
    fr_ms = 86400 * 1000
    times = [0]  # Nến đơn lẻ cuối cùng
    ds = LocalStubDataSource(
        symbol=symbol,
        frame=frame,
        times=times,
        opens=[50000.0],
        highs=[50500.0],
        lows=[49800.0],
        closes=[50200.0],
        vols=[100.0],
    )

    slot = local_make_slot(symbol)
    book = {
        "symbol": symbol,
        "data": {"t": np.array(times, dtype=np.int64)},
        "entries": [{
            "strategy": "FINAL_BAR_SIGNAL",
            "slot": slot,
            "match": np.array([True], dtype=bool),  # Tín hiệu sinh tại nến cuối cùng
            "stop": np.array([False], dtype=bool),
            "vol": None,
            "dca": None,
        }],
    }

    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=fr_ms,
        base_frame=frame,
        close_at_end=False,
        data=ds,
        execution_target="next_open",
    ).run()

    # Tiêu chí: Nến cuối cùng có tín hiệu nhưng KHÔNG ĐƯỢC sinh lệnh hoặc vị thế vì thiếu next observation open!
    assert len(res["orders"]) == 0, f"Thất bại: Nến cuối không có next-open nhưng sinh {len(res['orders'])} lệnh!"
    assert len(res["open_positions"]) == 0, f"Thất bại: Nến cuối sinh {len(res['open_positions'])} vị thế mở!"
    assert len(res["positions"]) == 0, "Không được có vị thế nào được tạo!"


def test_gate1_1_dsl_precedence_on_simultaneous_signals():
    """Kiểm tra thứ tự ưu tiên khi cùng lúc có tín hiệu Exit và Buy:
    Trong FastDip: self.close() được gọi trước self.buy().
    Theo quy ước DSL của Nora: lệnh gọi sau ghi đè lệnh trước => buy chiếm ưu thế.
    """
    from backend.analys.alpha.code.compile import compile_code

    code_conflict = """class ConflictTest(NoraStrategy):
    timeframe = '24h'
    def on_bar(self):
        # Cả hai điều kiện đều là True
        self.close(close > 0)
        self.buy(close > 0)
"""
    prog = compile_code(code_conflict, register=False)
    df = pd.DataFrame({
        "open_time": [0, 86400000],
        "open": [100.0, 100.0],
        "high": [105.0, 105.0],
        "low": [95.0, 95.0],
        "close": [100.0, 100.0],
        "volume": [10.0, 10.0]
    })
    explicit = prog.explicit(df)
    # Vì buy gọi sau close nên explicit phải là 1.0 (LONG), không bị close thành NaN/0
    assert explicit[0] == 1.0
    assert explicit[1] == 1.0
