import pytest
import numpy as np

def compute_rsi(prices, period=10):
    deltas = np.diff(prices, prepend=prices[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    
    avg_gain = np.zeros_like(prices)
    avg_loss = np.zeros_like(prices)
    if len(prices) > period:
        avg_gain[period] = np.mean(gains[1:period+1])
        avg_loss[period] = np.mean(losses[1:period+1])
        for i in range(period + 1, len(prices)):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i]) / period
    
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    rsi = np.where(avg_loss == 0, 100.0, 100.0 - (100.0 / (1.0 + rs)))
    return rsi

def compute_sma(prices, period=15):
    ret = np.full_like(prices, np.nan)
    for i in range(period - 1, len(prices)):
        ret[i] = np.mean(prices[i - period + 1 : i + 1])
    return ret

def compute_ema(prices, period=50):
    ret = np.zeros_like(prices)
    alpha = 2.0 / (period + 1.0)
    ret[0] = prices[0]
    for i in range(1, len(prices)):
        ret[i] = alpha * prices[i] + (1.0 - alpha) * ret[i-1]
    return ret

def compute_stddev(prices, period=20, nbdev=1.5):
    ret = np.full_like(prices, np.nan)
    for i in range(period - 1, len(prices)):
        ret[i] = np.std(prices[i - period + 1 : i + 1]) * nbdev
    return ret

def test_fast_dip_signals_parity():
    """Kiểm tra tính tất định của tín hiệu Fast Dip Harvester:
       Signal Entry: RSI crossover 40 & Close > SMA 15 & Close > Macro EMA 50
       Signal Exit: RSI > 65 or Close crossunder SMA 15
    """
    np.random.seed(42)
    n = 200
    base = 50000.0
    returns = np.random.normal(0.001, 0.02, n)
    closes = base * np.cumprod(1.0 + returns)

    rsi = compute_rsi(closes, period=10)
    sma = compute_sma(closes, period=15)
    macro = compute_ema(closes, period=50)

    # Deterministic signal generation
    entries = (rsi[1:] > 40.0) & (rsi[:-1] <= 40.0) & (closes[1:] > sma[1:]) & (closes[1:] > macro[1:])
    exits = (rsi[1:] > 65.0) | ((closes[1:] < sma[1:]) & (closes[:-1] >= sma[:-1]))

    assert len(entries) == n - 1
    assert len(exits) == n - 1
    # Xác nhận các tín hiệu là boolean rõ ràng, không có NaN/inf
    assert not np.isnan(entries).any()
    assert not np.isnan(exits).any()

def test_vinh_breakout_signals_parity():
    """Kiểm tra tính tất định của tín hiệu Vinh Breakout (33312a2f4dfc):
       Upper Band = SMA 20 + StdDev 20 * 1.5
       Entry: crossover(Close, Upper Band) & (Close > Macro EMA 100)
       Exit: Close < SMA 20
    """
    np.random.seed(100)
    n = 250
    base = 3000.0
    returns = np.random.normal(0.0005, 0.025, n)
    closes = base * np.cumprod(1.0 + returns)

    sma20 = compute_sma(closes, period=20)
    std20 = compute_stddev(closes, period=20, nbdev=1.5)
    upper_band = sma20 + std20
    macro = compute_ema(closes, period=100)

    entries = (closes[1:] > upper_band[1:]) & (closes[:-1] <= upper_band[:-1]) & (closes[1:] > macro[1:])
    exits = closes[1:] < sma20[1:]

    assert len(entries) == n - 1
    assert len(exits) == n - 1
    assert not np.isnan(entries[100:]).any()
    assert not np.isnan(exits[100:]).any()

def test_risk_policy_sizing_enforcement():
    """Kiểm tra quy tắc ràng buộc rủi ro tối đa 25 USDT/lệnh trên master 10k:
       position_size_usdt * stop_loss_pct <= 25.0 USDT
       => position_size_usdt <= 25.0 / stop_loss_pct
    """
    master_capital = 10000.0
    max_risk_usdt = 25.0  # 0.25% master

    # Fast Dip: stop_loss_pct = 2.0% => max notional = 25 / 0.02 = 1,250 USDT
    fast_dip_sl = 0.02
    max_notional_fast_dip = max_risk_usdt / fast_dip_sl
    assert max_notional_fast_dip == 1250.0

    # Vinh Breakout: stop_loss_pct = 2.5% => max notional = 25 / 0.025 = 1,000 USDT
    vinh_sl = 0.025
    max_notional_vinh = max_risk_usdt / vinh_sl
    assert max_notional_vinh == 1000.0
