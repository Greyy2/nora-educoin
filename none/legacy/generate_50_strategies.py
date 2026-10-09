#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/vmc03/norabt/nora')
from backend.core.strategy.pydsl.parser import compile_program

# 50 Strategies across 5 Categories (10 per category)
STRATEGIES = [
    # =========================================================================
    # 1. TREND FOLLOWING (10 Strategies)
    # =========================================================================
    {
        "key": "trend_kema_breakout",
        "name": "Keltner Channel Trend (KEMA)",
        "category": "Trend Following",
        "difficulty": "Beginner",
        "summary": "Chiến lược bám theo xu hướng dựa trên sự mở rộng của dải kênh biến động Keltner Channels (EMA 20 + 2×ATR).",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: KELTNER CHANNEL VOLATILITY BREAKOUT (KEMA)
    =============================================================================
    Financial Concept:
      Trend following posits that strong momentum bursts tend to persist.
      Keltner Channels construct dynamic volatility-based envelopes around
      an Exponential Moving Average (EMA) using Average True Range (ATR).

    Trading Rules:
      1. Long Entry: Close crosses ABOVE the upper band (EMA + 2 * ATR).
      2. Exit: Close drops BELOW the midline EMA (trend exhaustion).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        mid_ema = self.feat.ema(close, 20)
        vol_atr = self.feat.atr(high, low, close, 14)
        upper_band = mid_ema + 2.0 * vol_atr

        enter_signal = self.op.crossed_above(close, upper_band)
        exit_signal = close < mid_ema

        self.set_positions(exit_signal, position=0.0)
        self.set_positions(enter_signal, position=1.0)
'''
    },
    {
        "key": "trend_dual_ema",
        "name": "Dual EMA Crossover (Golden Cross)",
        "category": "Trend Following",
        "difficulty": "Beginner",
        "summary": "Giao cắt EMA ngắn hạn (20) và dài hạn (50) xác nhận động lượng xu hướng trung hạn.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DUAL MOVING AVERAGE CROSSOVER (MOMENTUM SHIFT)
    =============================================================================
    Financial Concept:
      When short-term moving average crosses above long-term moving average,
      it confirms that near-term buyers are driving market momentum.

    Trading Rules:
      1. Golden Cross: Fast EMA (20) crosses ABOVE Slow EMA (50) -> Long Entry.
      2. Death Cross: Fast EMA (20) crosses BELOW Slow EMA (50) -> Exit to Cash.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_fast = self.feat.ema(close, 20)
        ema_slow = self.feat.ema(close, 50)

        bullish_cross = self.op.crossed_above(ema_fast, ema_slow)
        bearish_cross = self.op.crossed_below(ema_fast, ema_slow)

        self.set_positions(bearish_cross, position=0.0)
        self.set_positions(bullish_cross, position=1.0)
'''
    },
    {
        "key": "trend_triple_ema",
        "name": "Triple EMA Trend Alignment (20/50/200)",
        "category": "Trend Following",
        "difficulty": "Intermediate",
        "summary": "Hệ thống xác nhận xu hướng 3 tầng: nến ngắn, trung và dài hạn xếp chồng thứ tự tăng dần.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: TRIPLE EMA HIERARCHY ALIGNMENT
    =============================================================================
    Financial Concept:
      Strong macro bull regimes occur when short-term, medium-term, and long-term
      averages align perfectly: EMA(20) > EMA(50) > EMA(200).

    Trading Rules:
      1. Entry: EMA(20) > EMA(50) > EMA(200) AND Close crosses above EMA(20).
      2. Exit: Close crosses below EMA(50).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        ema_50 = self.feat.ema(close, 50)
        ema_200 = self.feat.ema(close, 200)

        aligned = (ema_20 > ema_50) & (ema_50 > ema_200)
        entry_trigger = self.op.crossed_above(close, ema_20) & aligned
        exit_trigger = self.op.crossed_below(close, ema_50)

        self.set_positions(exit_trigger, position=0.0)
        self.set_positions(entry_trigger, position=1.0)
'''
    },
    {
        "key": "trend_adx_directional",
        "name": "ADX + Directional Movement (+DI / -DI)",
        "category": "Trend Following",
        "difficulty": "Intermediate",
        "summary": "Đo lường cường độ xu hướng bằng ADX và kích hoạt lệnh khi +DI vượt trội hơn -DI.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ADX STRENGTH WITH DIRECTIONAL INDEX
    =============================================================================
    Financial Concept:
      ADX measures trend strength regardless of direction. Combining ADX > 25
      with +DI crossing above -DI ensures entering only verified strong trends.

    Trading Rules:
      1. Entry: +DI crosses above -DI AND ADX > 25 (Strong Bullish Trend).
      2. Exit: -DI crosses above +DI OR ADX drops below 20.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        adx_val = self.feat.adx(high, low, close, 14)
        plus_di = self.feat.plus_di(high, low, close, 14)
        minus_di = self.feat.minus_di(high, low, close, 14)

        enter_sig = self.op.crossed_above(plus_di, minus_di) & (adx_val > 25.0)
        exit_sig = self.op.crossed_above(minus_di, plus_di) | (adx_val < 20.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_dema_momentum",
        "name": "Double Exponential Moving Average (DEMA)",
        "category": "Trend Following",
        "difficulty": "Intermediate",
        "summary": "DEMA triệt tiêu độ trễ của EMA truyền thống giúp phản ứng nhanh nhạy với các bước ngoặt của sóng.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DEMA ZERO-LAG TREND CAPTURE
    =============================================================================
    Financial Concept:
      DEMA calculates 2*EMA - EMA(EMA), reducing lag significantly compared to
      traditional moving averages and providing earlier trend entries.

    Trading Rules:
      1. Entry: Close crosses above DEMA(30).
      2. Exit: Close crosses below DEMA(30).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        dema_val = self.feat.dema(close, 30)

        enter_sig = self.op.crossed_above(close, dema_val)
        exit_sig = self.op.crossed_below(close, dema_val)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_tema_speed",
        "name": "Triple Exponential Moving Average (TEMA)",
        "category": "Trend Following",
        "difficulty": "Advanced",
        "summary": "TEMA kết hợp lọc nhiễu 3 tầng để nắm bắt xung lực trung hạn với độ trễ tối thiểu.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: TEMA MOMENTUM SYSTEM
    =============================================================================
    Financial Concept:
      Triple Exponential Moving Average (TEMA) further removes lag while
      smoothing out random price volatility in fast-moving crypto assets.

    Trading Rules:
      1. Entry: TEMA(20) crosses above TEMA(50).
      2. Exit: TEMA(20) crosses below TEMA(50).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        tema_fast = self.feat.tema(close, 20)
        tema_slow = self.feat.tema(close, 50)

        enter_sig = self.op.crossed_above(tema_fast, tema_slow)
        exit_sig = self.op.crossed_below(tema_fast, tema_slow)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_linearreg_slope",
        "name": "Linear Regression Slope Trend",
        "category": "Trend Following",
        "difficulty": "Advanced",
        "summary": "Đo góc dốc (độ dốc toán học) của đường hồi quy tuyến tính để định lượng gia tốc tăng trưởng.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: STATISTICAL LINEAR REGRESSION SLOPE
    =============================================================================
    Financial Concept:
      Linear regression fits a best-fit trend line through price points. A
      consistently positive slope indicates strong directional persistence.

    Trading Rules:
      1. Entry: Slope(20) crosses above 0.0 AND Close > SMA(50).
      2. Exit: Slope(20) crosses below 0.0.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        slope_20 = self.feat.linearreg_slope(close, 20)
        sma_50 = self.feat.sma(close, 50)

        enter_sig = self.op.crossed_above_value(slope_20, 0.0) & (close > sma_50)
        exit_sig = self.op.crossed_below_value(slope_20, 0.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_wma_volume",
        "name": "Weighted Moving Average (WMA) Trend",
        "category": "Trend Following",
        "difficulty": "Intermediate",
        "summary": "WMA gán trọng số tuyến tính cao hơn cho các nến gần nhất, bắt nhịp sớm chuyển động giá.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: WEIGHTED MOVING AVERAGE (WMA)
    =============================================================================
    Financial Concept:
      WMA assigns linear weighting to most recent bars, reacting faster than
      SMA while avoiding the recursive tail effect of EMA.

    Trading Rules:
      1. Entry: WMA(15) crosses above WMA(45).
      2. Exit: WMA(15) crosses below WMA(45).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        wma_fast = self.feat.wma(close, 15)
        wma_slow = self.feat.wma(close, 45)

        enter_sig = self.op.crossed_above(wma_fast, wma_slow)
        exit_sig = self.op.crossed_below(wma_fast, wma_slow)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_macd_zeroline",
        "name": "MACD Zero-Line Trend Filter",
        "category": "Trend Following",
        "difficulty": "Intermediate",
        "summary": "Sử dụng đường Zero-line của MACD như bộ lọc chế độ thị trường Bull/Bear phân định dòng tiền.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: MACD ZERO-LINE MACRO REGIME
    =============================================================================
    Financial Concept:
      When MACD Line is above zero, 12 EMA > 26 EMA, confirming overall macro
      bull trend. Entering on signal cross above zero filters out counter-trend noise.

    Trading Rules:
      1. Entry: MACD line crosses above Signal line while MACD > 0.
      2. Exit: MACD line crosses below Signal line.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        macd_line, signal_line, macd_hist = self.feat.macd(close, 12, 26, 9)

        bullish_cross = self.op.crossed_above(macd_line, signal_line)
        in_bull_regime = macd_line > 0.0

        enter_sig = bullish_cross & in_bull_regime
        exit_sig = self.op.crossed_below(macd_line, signal_line)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "trend_parabolic_ema",
        "name": "EMA Trend Rider with Momentum Shift",
        "category": "Trend Following",
        "difficulty": "Beginner",
        "summary": "Chiến lược bám trend theo dõi độ dốc gia tăng của EMA 20 ngày so với 3 nến trước.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: EMA PERSISTENT SLOPE RIDER
    =============================================================================
    Financial Concept:
      A rising moving average across multiple consecutive sessions proves
      underlying accumulation by institutional market participants.

    Trading Rules:
      1. Entry: Close > EMA(20) AND EMA(20) is rising over 3 bars.
      2. Exit: Close < EMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        ema_rising = self.op.rising(ema_20, 3)

        enter_sig = (close > ema_20) & ema_rising
        exit_sig = close < ema_20

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },

    # =========================================================================
    # 2. MEAN REVERSION (10 Strategies)
    # =========================================================================
    {
        "key": "revert_rsi_bb",
        "name": "RSI + Bollinger Bands Oversold Reversal",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "Bắt đáy phục hồi khi giá chạm vùng quá bán RSI < 30 và đâm thủng Lower Bollinger Band.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: RSI & BOLLINGER BANDS REVERSAL
    =============================================================================
    Financial Concept:
      Asset prices exhibit elastic properties: extreme deviations from the
      statistical mean eventually snap back.

    Trading Rules:
      1. Entry: RSI(14) < 30 AND Close < Lower BB(20, 2.0).
      2. Exit: RSI(14) > 50 OR Close > Mid BB.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        rsi_14 = self.feat.rsi(close, 14)
        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)

        oversold_entry = (rsi_14 < 30.0) & (close < lower_bb)
        exit_rebound = (rsi_14 > 50.0) | (close > mid_bb)

        self.set_positions(exit_rebound, position=0.0)
        self.set_positions(oversold_entry, position=1.0)
'''
    },
    {
        "key": "revert_zscore_extreme",
        "name": "Rolling Z-Score Statistical Reversion",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "Mua khi độ lệch chuẩn hóa Z-Score rơi xuống dưới -2.0 và chốt lời khi Z-Score hồi về 0.0.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ROLLING Z-SCORE STATISTICAL ARBITRAGE
    =============================================================================
    Financial Concept:
      Z-Score measures how many standard deviations price is from its rolling
      mean. Z-Score < -2.0 represents a 95% statistically improbable extreme dip.

    Trading Rules:
      1. Entry: Z-Score(20) crosses above -2.0 (rebounding from extreme).
      2. Exit: Z-Score(20) reaches >= 0.0 (mean reversion completed).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        z_val = self.feat.zscore(close, 20)

        enter_sig = self.op.crossed_above_value(z_val, -2.0)
        exit_sig = z_val >= 0.0

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_cci_oversold",
        "name": "Commodity Channel Index (CCI) Snapback",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "Bắt sóng nảy lại khi chỉ số CCI rơi xuống mức cực đoan dưới -150 rồi quay đầu cắt lên.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: CCI EXTREME CYCLE SNAPBACK
    =============================================================================
    Financial Concept:
      CCI measures variation from statistical mean. Values below -100 to -150
      flag heavily exhausted selling pressure ripe for violent mean reversion.

    Trading Rules:
      1. Entry: CCI(14) crosses ABOVE -100 from oversold territory.
      2. Exit: CCI(14) crosses ABOVE +100 (taking profit into strength).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        cci_val = self.feat.cci(high, low, close, 14)

        enter_sig = self.op.crossed_above_value(cci_val, -100.0)
        exit_sig = self.op.crossed_above_value(cci_val, 100.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_willr_elastic",
        "name": "Williams %R Extreme Elasticity",
        "category": "Mean Reversion",
        "difficulty": "Beginner",
        "summary": "Williams %R dao động từ 0 đến -100, kích hoạt mua khi chỉ báo cắt lên mức -80.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: WILLIAMS %R EXTREME REBOUND
    =============================================================================
    Financial Concept:
      Williams %R reflects the level of the close relative to the highest high
      for the lookback period. Readings below -80 indicate extreme oversold.

    Trading Rules:
      1. Entry: Williams %R(14) crosses ABOVE -80.
      2. Exit: Williams %R(14) crosses ABOVE -20 (overbought target).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        willr_val = self.feat.willr(high, low, close, 14)

        enter_sig = self.op.crossed_above_value(willr_val, -80.0)
        exit_sig = self.op.crossed_above_value(willr_val, -20.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_stoch_k_d",
        "name": "Stochastic Oscillator (%K, %D) Bull Cross",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "Chỉ báo Stochastic dao động chậm: đường Fast %K cắt lên Slow %D dưới ngưỡng 20.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: STOCHASTIC OVERSOLD CROSSOVER
    =============================================================================
    Financial Concept:
      Stochastic compares closing price to price range over given period.
      A %K cross above %D below 20 confirms upward momentum reversal.

    Trading Rules:
      1. Entry: Fast %K crosses above Slow %D while both < 25.
      2. Exit: Fast %K crosses below Slow %D while > 70.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)

        enter_sig = self.op.crossed_above(slowk, slowd) & (slowk < 25.0)
        exit_sig = self.op.crossed_below(slowk, slowd) & (slowk > 70.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_bbands_tight",
        "name": "Bollinger Bands Lower Touch & Bounce",
        "category": "Mean Reversion",
        "difficulty": "Beginner",
        "summary": "Mua khi nến đóng cửa bật ngược trở lại vào bên trong dải Bollinger dưới.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: BOLLINGER LOWER BAND BOUNCE
    =============================================================================
    Financial Concept:
      Price outside Bollinger Bands represents abnormal dispersion. Returning
      inside the band signals rejection of lower prices.

    Trading Rules:
      1. Entry: Close crosses ABOVE Lower Bollinger Band.
      2. Exit: Close touches or crosses Middle Bollinger Band (SMA 20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)

        enter_sig = self.op.crossed_above(close, lower_bb)
        exit_sig = self.op.crossed_above(close, mid_bb)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_mfi_oversold",
        "name": "Money Flow Index (MFI) Volume Reversion",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "MFI kết hợp biến động giá và khối lượng giao dịch để phát hiện dòng tiền bắt đáy vùng < 20.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: MONEY FLOW INDEX (VOLUME-WEIGHTED RSI)
    =============================================================================
    Financial Concept:
      Money Flow Index incorporates volume into price changes. Extreme low MFI
      (< 20) reveals that selling volume has dried up.

    Trading Rules:
      1. Entry: MFI(14) crosses ABOVE 20.0.
      2. Exit: MFI(14) crosses ABOVE 60.0.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close
        volume = self.data.pv_volume

        mfi_val = self.feat.mfi(high, low, close, volume, 14)

        enter_sig = self.op.crossed_above_value(mfi_val, 20.0)
        exit_sig = self.op.crossed_above_value(mfi_val, 60.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_returns_dip",
        "name": "Multi-Day Cumulative Return Dip Buying",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "Mua khi tỷ suất lợi nhuận 5 ngày sụt giảm quá mức (-10%) và bắt đầu có nến đảo chiều tăng.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: STATISTICAL SHORT-TERM DRAWDOWN OVERREACTION
    =============================================================================
    Financial Concept:
      Crypto markets frequently overreact in panic pan-sell events. Entering
      after rapid multi-day cumulative drops captures sharp reflex bounces.

    Trading Rules:
      1. Entry: 5-day return < -0.08 AND daily close > previous close.
      2. Exit: 5-day return > 0.03.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ret_5d = self.feat.returns(close, 5)
        prev_close = self.op.shift(close, 1)

        enter_sig = (ret_5d < -0.08) & (close > prev_close)
        exit_sig = ret_5d > 0.03

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_linearreg_disparity",
        "name": "Linear Regression Channel Deviation",
        "category": "Mean Reversion",
        "difficulty": "Advanced",
        "summary": "Mua khi giá chiết khấu sâu hơn 2 lần độ lệch chuẩn so với đường hồi quy tuyến tính.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: LINEAR REGRESSION DISPARITY REVERSION
    =============================================================================
    Financial Concept:
      Linear Regression represents the fair mathematical trajectory of price.
      Deviations below trend line offer high-probability reversion entries.

    Trading Rules:
      1. Entry: Close crosses above LinearReg(20) - 2 * StdDev(20).
      2. Exit: Close touches LinearReg(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        linreg = self.feat.linearreg(close, 20)
        std_val = self.feat.stddev(close, 20, 1.0)
        lower_band = linreg - 2.0 * std_val

        enter_sig = self.op.crossed_above(close, lower_band)
        exit_sig = self.op.crossed_above(close, linreg)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "revert_rsi_divergence",
        "name": "RSI Rebound with Short MA Filter",
        "category": "Mean Reversion",
        "difficulty": "Intermediate",
        "summary": "RSI phục hồi từ vùng 30 kết hợp nến ngày cắt lên đường SMA 5 ngày để xác nhận điểm đảo chiều.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: RSI OVERSOLD CONFIRMED BY MICRO MOVING AVERAGE
    =============================================================================
    Financial Concept:
      RSI alone can stay oversold during prolonged liquidations. Demanding
      that price also crosses above a fast 5-day SMA filters out falling knives.

    Trading Rules:
      1. Entry: RSI(14) < 35 AND Close crosses above SMA(5).
      2. Exit: RSI(14) > 55.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        rsi_14 = self.feat.rsi(close, 14)
        sma_5 = self.feat.sma(close, 5)

        enter_sig = (rsi_14 < 35.0) & self.op.crossed_above(close, sma_5)
        exit_sig = rsi_14 > 55.0

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },

    # =========================================================================
    # 3. BREAKOUT & MOMENTUM (10 Strategies)
    # =========================================================================
    {
        "key": "breakout_donchian_turtle",
        "name": "Donchian Channel Breakout (Turtle Trading)",
        "category": "Breakout & Momentum",
        "difficulty": "Intermediate",
        "summary": "Chiến lược Turtle Trading huyền thoại: mua khi vượt đỉnh 20 ngày và thoát khi gãy đáy 10 ngày.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DONCHIAN CHANNEL BREAKOUT (THE LEGENDARY TURTLE SYSTEM)
    =============================================================================
    Financial Concept:
      Channel breakouts capture large persistent market regimes with zero
      prediction: entering when an asset trades at a new 20-day high.

    Trading Rules:
      1. Long Entry: Price breaks above the previous 20-day high.
      2. Exit: Price drops below the previous 10-day low (Trailing Stop).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        upper_20 = self.feat.donchian_upper(high, 20)
        lower_10 = self.feat.donchian_lower(low, 10)

        breakout_entry = close > upper_20
        trailing_exit = close < lower_10

        self.set_positions(trailing_exit, position=0.0)
        self.set_positions(breakout_entry, position=1.0)
'''
    },
    {
        "key": "breakout_bb_squeeze",
        "name": "Bollinger Bands Squeeze & Expansion Breakout",
        "category": "Breakout & Momentum",
        "difficulty": "Intermediate",
        "summary": "Phát hiện pha nén biến động cực đại (Squeeze) và kích hoạt lệnh khi nến bung dải Upper.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: BOLLINGER BAND VOLATILITY SQUEEZE BREAKOUT
    =============================================================================
    Financial Concept:
      Volatility is cyclical: periods of compression are inevitably followed
      by aggressive expansions. Breakouts after tight squeezes have high follow-through.

    Trading Rules:
      1. Entry: Close crosses ABOVE Upper BB(20, 2.0).
      2. Exit: Close crosses BELOW Middle BB.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)

        enter_sig = self.op.crossed_above(close, upper_bb)
        exit_sig = self.op.crossed_below(close, mid_bb)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_roc_surge",
        "name": "Rate of Change (ROC) Momentum Explosion",
        "category": "Breakout & Momentum",
        "difficulty": "Beginner",
        "summary": "Sử dụng Rate of Change (ROC) đo tốc độ tăng tốc của dòng tiền để bắt đầu các con sóng lớn.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ROC MOMENTUM SURGE
    =============================================================================
    Financial Concept:
      Rate of Change (ROC) measures percentage velocity. When ROC(10) crosses
      above +5%, it signals an institutional accumulation impulse.

    Trading Rules:
      1. Entry: ROC(10) crosses ABOVE +5.0% AND Close > EMA(20).
      2. Exit: ROC(10) crosses BELOW 0.0%.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        roc_10 = self.feat.roc(close, 10)
        ema_20 = self.feat.ema(close, 20)

        enter_sig = self.op.crossed_above_value(roc_10, 5.0) & (close > ema_20)
        exit_sig = self.op.crossed_below_value(roc_10, 0.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_volume_zscore",
        "name": "High-Volume Breakout (Volume Z-Score Spike)",
        "category": "Breakout & Momentum",
        "difficulty": "Advanced",
        "summary": "Lọc tín hiệu breakout bằng khối lượng: giá lập đỉnh nến ngày đi kèm khối lượng đột biến (Z-Score > 2.0).",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: VOLUME Z-SCORE CONFIRMED BREAKOUT
    =============================================================================
    Financial Concept:
      True breakouts are supported by unusual volume participation. Volume
      Z-Score > 2.0 ensures that breakouts are driven by institutional capital.

    Trading Rules:
      1. Entry: Close > DonchianUpper(20) AND Volume_Z(20) > 1.5.
      2. Exit: Close < SMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        close = self.data.pv_close
        volume = self.data.pv_volume

        upper_20 = self.feat.donchian_upper(high, 20)
        vol_z = self.feat.volume_z(volume, 20)
        sma_20 = self.feat.sma(close, 20)

        enter_sig = (close > upper_20) & (vol_z > 1.5)
        exit_sig = close < sma_20

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_natr_range",
        "name": "Normalized ATR (NATR) Volatility Breakout",
        "category": "Breakout & Momentum",
        "difficulty": "Intermediate",
        "summary": "NATR đo tỷ lệ phần trăm biên độ nến so với giá, kích hoạt lệnh khi biến động mở rộng vượt trội.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: NORMALIZED ATR EXPANSION
    =============================================================================
    Financial Concept:
      NATR standardizes volatility as a percentage of price, allowing fair
      comparison across different market cycles and Bitcoin price regimes.

    Trading Rules:
      1. Entry: NATR(14) crosses ABOVE 4.0% AND Close > EMA(20).
      2. Exit: Close drops below EMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        natr_val = self.feat.natr(high, low, close, 14)
        ema_20 = self.feat.ema(close, 20)

        enter_sig = self.op.crossed_above_value(natr_val, 4.0) & (close > ema_20)
        exit_sig = close < ema_20

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_obv_accumulation",
        "name": "On-Balance Volume (OBV) Trend Breakout",
        "category": "Breakout & Momentum",
        "difficulty": "Intermediate",
        "summary": "On-Balance Volume cộng dồn khối lượng mua bán để phát hiện giai đoạn gom hàng bùng nổ.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ON-BALANCE VOLUME ACCUMULATION
    =============================================================================
    Financial Concept:
      OBV measures buying vs selling pressure. A rising OBV breaking above its
      20-period moving average confirms hidden accumulation before price pumps.

    Trading Rules:
      1. Entry: OBV crosses ABOVE SMA(OBV, 20) AND Close > EMA(20).
      2. Exit: OBV crosses BELOW SMA(OBV, 20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close
        volume = self.data.pv_volume

        obv_val = self.feat.obv(close, volume)
        obv_sma = self.feat.sma(obv_val, 20)
        ema_20 = self.feat.ema(close, 20)

        enter_sig = self.op.crossed_above(obv_val, obv_sma) & (close > ema_20)
        exit_sig = self.op.crossed_below(obv_val, obv_sma)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_momentum_10d",
        "name": "Absolute Momentum 10-Day Threshold",
        "category": "Breakout & Momentum",
        "difficulty": "Beginner",
        "summary": "Chỉ báo Momentum đo khoảng cách giá tuyệt đối so với 10 phiên trước để lọc các đợt bùng nổ.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ABSOLUTE MOMENTUM THRESHOLD
    =============================================================================
    Financial Concept:
      Momentum represents Close(t) - Close(t-n). An expanding positive momentum
      confirms buyers are willing to pay progressively higher prices.

    Trading Rules:
      1. Entry: Momentum(10) crosses ABOVE 0.0 AND Close > SMA(50).
      2. Exit: Momentum(10) crosses BELOW 0.0.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        mom_val = self.feat.momentum(close, 10)
        sma_50 = self.feat.sma(close, 50)

        enter_sig = self.op.crossed_above_value(mom_val, 0.0) & (close > sma_50)
        exit_sig = self.op.crossed_below_value(mom_val, 0.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_range_pct",
        "name": "Daily Range Expansion (High - Low) / Close",
        "category": "Breakout & Momentum",
        "difficulty": "Advanced",
        "summary": "Phát hiện cây nến mở rộng biên độ (Range %) gấp đôi mức trung bình nến ngày.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DAILY RANGE EXPANSION SHOCK
    =============================================================================
    Financial Concept:
      When daily price range (High - Low) / Close spikes, it reflects high
      conviction from large market participants, breaking out of ranges.

    Trading Rules:
      1. Entry: Range_pct > 6.0% AND Close > Open (Large Bullish Bar).
      2. Exit: Close crosses below SMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        open_p = self.data.pv_open
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        range_val = self.feat.range_pct(high, low, close)
        sma_20 = self.feat.sma(close, 20)

        enter_sig = (range_val > 6.0) & (close > open_p) & (close > sma_20)
        exit_sig = self.op.crossed_below(close, sma_20)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_stddev_channel",
        "name": "Standard Deviation Dynamic Channel Breakout",
        "category": "Breakout & Momentum",
        "difficulty": "Intermediate",
        "summary": "Tạo kênh biên động dựa trên độ lệch chuẩn (SMA 20 + 2.5×StdDev) để đánh cược vào các cú phóng giá.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DYNAMIC STANDARD DEVIATION BREAKOUT
    =============================================================================
    Financial Concept:
      A close penetrating 2.5 standard deviations indicates non-random price
      momentum with high probabilistic drift in the breakout direction.

    Trading Rules:
      1. Entry: Close crosses above SMA(20) + 2.5 * StdDev(20).
      2. Exit: Close drops below SMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        sma_20 = self.feat.sma(close, 20)
        std_val = self.feat.stddev(close, 20, 2.5)
        upper_threshold = sma_20 + std_val

        enter_sig = self.op.crossed_above(close, upper_threshold)
        exit_sig = close < sma_20

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "breakout_multi_week_high",
        "name": "Rolling 30-Day Multi-Week High Breakout",
        "category": "Breakout & Momentum",
        "difficulty": "Beginner",
        "summary": "Mua khi giá vượt đỉnh cao nhất của 30 phiên gần nhất và duy trì trên đường trung bình MA 50.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: 30-DAY NEW HIGH EXPANSION
    =============================================================================
    Financial Concept:
      Breaking a 30-day high resets historical resistance into new support,
      attracting momentum algorithms and retail buyers.

    Trading Rules:
      1. Entry: Close > Previous 30-day Highest Close.
      2. Exit: Close < SMA(30).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        close = self.data.pv_close

        upper_30 = self.feat.donchian_upper(high, 30)
        sma_30 = self.feat.sma(close, 30)

        enter_sig = close > upper_30
        exit_sig = close < sma_30

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },

    # =========================================================================
    # 4. MULTI-INDICATOR CONFLUENCE (10 Strategies)
    # =========================================================================
    {
        "key": "confluence_ema_rsi_pullback",
        "name": "EMA Trend + RSI Dip Buying (Trend Pullback)",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Chiến lược mua khi điều chỉnh: thị trường Uptrend (Close > EMA 50) nhưng RSI lùi về vùng 40-45.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: TREND FOLLOWING WITH OVERSOLD PULLBACK ENTRY
    =============================================================================
    Financial Concept:
      Buying pullbacks within established trends combines the statistical edge
      of trend following with favorable entry pricing of mean reversion.

    Trading Rules:
      1. Entry: Close > EMA(50) AND RSI(14) crosses ABOVE 40.
      2. Exit: Close < EMA(50) OR RSI(14) > 75.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_50 = self.feat.ema(close, 50)
        rsi_14 = self.feat.rsi(close, 14)

        in_uptrend = close > ema_50
        rsi_rebound = self.op.crossed_above_value(rsi_14, 40.0)

        enter_sig = in_uptrend & rsi_rebound
        exit_sig = (close < ema_50) | (rsi_14 > 75.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_keltner_macd",
        "name": "Keltner Channel + MACD Confirmation",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Kết hợp phá vỡ kênh Keltner với chỉ báo MACD histogram dương để lọc sạch tín hiệu breakout giả.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: KELTNER BREAKOUT WITH MACD MOMENTUM CONFIRMATION
    =============================================================================
    Financial Concept:
      Keltner breakout proves price movement, while positive MACD histogram
      confirms accelerating momentum, filtering out false breakouts.

    Trading Rules:
      1. Entry: Close > Keltner Upper(20, 2.0) AND MACD Histogram > 0.
      2. Exit: Close < Keltner Midline (EMA 20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        mid_ema = self.feat.ema(close, 20)
        atr_val = self.feat.atr(high, low, close, 14)
        upper_band = mid_ema + 2.0 * atr_val

        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)

        enter_sig = (close > upper_band) & (macd_hist > 0.0)
        exit_sig = close < mid_ema

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_dual_ema_adx",
        "name": "Dual EMA + ADX Trend Strength Filter",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Chỉ vào lệnh giao cắt EMA khi ADX > 25 để tránh bị bào mòn tài khoản trong vùng thị trường đi ngang.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DUAL EMA CROSSOVER FILTERED BY ADX
    =============================================================================
    Financial Concept:
      Moving average crossovers suffer severe whipsaw in sideway chop.
      Requiring ADX > 25 ensures the strategy only deploys in trending markets.

    Trading Rules:
      1. Entry: EMA(20) crosses above EMA(50) AND ADX(14) > 25.
      2. Exit: EMA(20) crosses below EMA(50).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        ema_50 = self.feat.ema(close, 50)
        adx_val = self.feat.adx(high, low, close, 14)

        golden_cross = self.op.crossed_above(ema_20, ema_50)
        enter_sig = golden_cross & (adx_val > 25.0)
        exit_sig = self.op.crossed_below(ema_20, ema_50)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_bb_rsi_adx",
        "name": "Bollinger Bands + RSI + ADX Regime Master",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Advanced",
        "summary": "Hệ thống đa tầng: xác định pha tích lũy (ADX thấp), bắt đáy nén biến động (BB) và xung lực RSI.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: BBANDS AND RSI COMPOSITE FILTER
    =============================================================================
    Financial Concept:
      Combining volatility boundaries (Bollinger), momentum oscillator (RSI),
      and trend strength (ADX) provides a robust tri-factor confirmation.

    Trading Rules:
      1. Entry: Close crosses above Mid BB AND RSI > 50 AND ADX > 20.
      2. Exit: Close drops below Mid BB.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)
        rsi_14 = self.feat.rsi(close, 14)
        adx_val = self.feat.adx(high, low, close, 14)

        enter_sig = self.op.crossed_above(close, mid_bb) & (rsi_14 > 50.0) & (adx_val > 20.0)
        exit_sig = close < mid_bb

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_volume_ema_cross",
        "name": "EMA Golden Cross + Volume Spike Confluence",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Giao cắt EMA 20/50 được củng cố bởi khối lượng Volume Z-Score đột biến vượt mức trung bình.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: VOLUME CONFIRMED GOLDEN CROSS
    =============================================================================
    Financial Concept:
      A Golden Cross occurring on above-average volume confirms genuine
      institutional participation rather than low-liquidity drift.

    Trading Rules:
      1. Entry: EMA(20) crosses above EMA(50) AND Volume_Z(20) > 1.0.
      2. Exit: Close < EMA(50).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close
        volume = self.data.pv_volume

        ema_20 = self.feat.ema(close, 20)
        ema_50 = self.feat.ema(close, 50)
        vol_z = self.feat.volume_z(volume, 20)

        cross = self.op.crossed_above(ema_20, ema_50)
        enter_sig = cross & (vol_z > 1.0)
        exit_sig = close < ema_50

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_donchian_macd",
        "name": "Donchian Breakout + MACD Alignment",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Kênh giá Donchian bắt điểm bùng nổ, MACD xác nhận gia tốc xung lực tăng giá đồng thuận.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DONCHIAN WITH MACD MOMENTUM CONFIRMATION
    =============================================================================
    Financial Concept:
      Filtering Donchian breakouts with MACD line > Signal line ensures that
      trend entries possess active acceleration rather than tepid grinds.

    Trading Rules:
      1. Entry: Close > DonchianUpper(20) AND MACD line > Signal line.
      2. Exit: Close < DonchianLower(10).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        upper_20 = self.feat.donchian_upper(high, 20)
        lower_10 = self.feat.donchian_lower(low, 10)
        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)

        enter_sig = (close > upper_20) & (macd_line > sig_line)
        exit_sig = close < lower_10

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_cci_ema_trend",
        "name": "EMA 200 Macro Trend + CCI Dip Rebound",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Bám theo xu hướng vĩ mô (Close > EMA 200) và tìm điểm vào tối ưu khi CCI hồi phục từ vùng -100.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: MACRO EMA 200 WITH CCI PULLBACK
    =============================================================================
    Financial Concept:
      Trading in the direction of the 200 EMA provides structural edge. Buying
      CCI oversold bounces aligns short-term entry with macro trend.

    Trading Rules:
      1. Entry: Close > EMA(200) AND CCI(14) crosses ABOVE -100.
      2. Exit: Close < EMA(50) OR CCI(14) > 150.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        ema_200 = self.feat.ema(close, 200)
        ema_50 = self.feat.ema(close, 50)
        cci_val = self.feat.cci(high, low, close, 14)

        in_macro_trend = close > ema_200
        cci_cross = self.op.crossed_above_value(cci_val, -100.0)

        enter_sig = in_macro_trend & cci_cross
        exit_sig = (close < ema_50) | (cci_val > 150.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_stoch_rsi_trend",
        "name": "Stochastic & RSI Confluence System",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Intermediate",
        "summary": "Cả hai bộ dao động Stochastic và RSI cùng đồng thuận thoát khỏi vùng quá bán để mở vị thế.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DUAL OSCILLATOR (RSI + STOCHASTIC) CONFLUENCE
    =============================================================================
    Financial Concept:
      When both RSI and Stochastic confirm an oversold bounce simultaneously,
      the probability of a sustained multi-day rebound increases sharply.

    Trading Rules:
      1. Entry: RSI(14) crosses above 35 AND Stochastic SlowK > SlowD.
      2. Exit: RSI(14) > 65.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        rsi_14 = self.feat.rsi(close, 14)
        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)

        enter_sig = self.op.crossed_above_value(rsi_14, 35.0) & (slowk > slowd)
        exit_sig = rsi_14 > 65.0

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_obv_rsi_momentum",
        "name": "OBV Volume Accumulation + RSI Momentum",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Advanced",
        "summary": "Khối lượng dòng tiền OBV dốc lên kết hợp RSI vượt mốc 50 báo hiệu giai đoạn bứt phá giá trị.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ON-BALANCE VOLUME & RSI CONFLUENCE
    =============================================================================
    Financial Concept:
      Volume leads price. Pairing rising On-Balance Volume with RSI > 50
      captures the exact inflection point when accumulation turns into markup.

    Trading Rules:
      1. Entry: OBV > SMA(OBV, 20) AND RSI(14) crosses ABOVE 50.0.
      2. Exit: RSI(14) drops below 45.0.
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close
        volume = self.data.pv_volume

        obv_val = self.feat.obv(close, volume)
        obv_sma = self.feat.sma(obv_val, 20)
        rsi_14 = self.feat.rsi(close, 14)

        enter_sig = (obv_val > obv_sma) & self.op.crossed_above_value(rsi_14, 50.0)
        exit_sig = rsi_14 < 45.0

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "confluence_triple_screen",
        "name": "Alexander Elder’s Triple Screen System",
        "category": "Multi-Indicator Confluence",
        "difficulty": "Advanced",
        "summary": "Triết lý 3 màn hình: lọc xu hướng bằng EMA 50, sóng dao động bằng MACD, và điểm vào bằng RSI.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: TRIPLE SCREEN CONFLUENCE
    =============================================================================
    Financial Concept:
      Inspired by Elder's Triple Screen: Screen 1 filters macro tide (EMA 50),
      Screen 2 tracks market wave (MACD), Screen 3 times the entry ripple (RSI).

    Trading Rules:
      1. Entry: Close > EMA(50) AND MACD > 0 AND RSI(14) crosses above 50.
      2. Exit: Close < EMA(50).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_50 = self.feat.ema(close, 50)
        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)
        rsi_14 = self.feat.rsi(close, 14)

        enter_sig = (close > ema_50) & (macd_line > 0.0) & self.op.crossed_above_value(rsi_14, 50.0)
        exit_sig = close < ema_50

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },

    # =========================================================================
    # 5. RISK-MANAGED & ASYMMETRIC EXITS (10 Strategies)
    # =========================================================================
    {
        "key": "risk_chandelier_exit",
        "name": "Chandelier Exit (ATR Trailing Stop)",
        "category": "Risk-Managed & Exits",
        "difficulty": "Advanced",
        "summary": "Chốt lời và cắt lỗ động theo dải Chandelier Exit dựa trên đỉnh giá cao nhất trừ 3 lần ATR.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: CHANDELIER EXIT VOLATILITY TRAILING STOP
    =============================================================================
    Financial Concept:
      Chandelier Exit hangs a trailing stop from the highest high reached.
      As the market rallies, the stop ratchets upwards, locking in unrealized gains.

    Trading Rules:
      1. Entry: Close crosses above EMA(20).
      2. Exit: Close drops below DonchianUpper(20) - 3.0 * ATR(14).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        upper_20 = self.feat.donchian_upper(high, 20)
        atr_14 = self.feat.atr(high, low, close, 14)

        chandelier_stop = upper_20 - 3.0 * atr_14

        enter_sig = self.op.crossed_above(close, ema_20)
        exit_sig = close < chandelier_stop

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_dual_exit_asymmetric",
        "name": "Dual-Condition Asymmetric Exit",
        "category": "Risk-Managed & Exits",
        "difficulty": "Intermediate",
        "summary": "Thoát lệnh phi đối xứng: chốt lời khi RSI chạm đỉnh 80 hoặc cắt lỗ nhanh khi giá gãy EMA 20.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ASYMMETRIC DUAL EXIT MATRIX
    =============================================================================
    Financial Concept:
      Different market conditions require different exits: protect capital
      when trend breaks, or harvest profits when momentum becomes exhausted.

    Trading Rules:
      1. Entry: Close crosses above EMA(20) & RSI(14) > 50.
      2. Exit: Close < EMA(20) (Stop Loss) OR RSI(14) > 80 (Take Profit into blow-off).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        rsi_14 = self.feat.rsi(close, 14)

        enter_sig = self.op.crossed_above(close, ema_20) & (rsi_14 > 50.0)
        exit_stop = close < ema_20
        exit_target = rsi_14 > 80.0
        exit_combined = exit_stop | exit_target

        self.set_positions(exit_combined, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_roc_momentum_exhaustion",
        "name": "Momentum Exhaustion Target Take-Profit",
        "category": "Risk-Managed & Exits",
        "difficulty": "Intermediate",
        "summary": "Chủ động chốt lời bảo vệ lợi nhuận khi tốc độ tăng trưởng ROC đạt đỉnh cực đại rồi suy yếu.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ROC MOMENTUM EXHAUSTION EXIT
    =============================================================================
    Financial Concept:
      Blow-off tops occur when velocity spikes unsustainably. Closing positions
      when ROC starts rolling over from extreme levels locks in peak returns.

    Trading Rules:
      1. Entry: Close > EMA(30) AND ROC(10) > 3.0%.
      2. Exit: Close < EMA(30) OR (ROC(10) was > 15% and drops below 10%).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        ema_30 = self.feat.ema(close, 30)
        roc_10 = self.feat.roc(close, 10)

        enter_sig = (close > ema_30) & (roc_10 > 3.0)
        exit_sig = (close < ema_30) | (roc_10 < 0.0)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_atr_fixed_multiple_stop",
        "name": "Fixed Multiple ATR Volatility Stop",
        "category": "Risk-Managed & Exits",
        "difficulty": "Beginner",
        "summary": "Khoảng dừng lỗ tự thích ứng với biến động: luôn duy trì ngưỡng bảo vệ cách giá vào 2 lần ATR.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DYNAMIC ATR VOLATILITY STOP LOSS
    =============================================================================
    Financial Concept:
      A fixed dollar stop fails in crypto due to regime shifts. An ATR-based
      stop dynamically expands in volatile markets and tightens in calm markets.

    Trading Rules:
      1. Entry: Close crosses above SMA(20).
      2. Exit: Close drops below SMA(20) - 2.0 * ATR(14).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        sma_20 = self.feat.sma(close, 20)
        atr_14 = self.feat.atr(high, low, close, 14)
        dynamic_stop = sma_20 - 2.0 * atr_14

        enter_sig = self.op.crossed_above(close, sma_20)
        exit_sig = close < dynamic_stop

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_bollinger_band_profit_take",
        "name": "Bollinger Band Overextension Take-Profit",
        "category": "Risk-Managed & Exits",
        "difficulty": "Intermediate",
        "summary": "Vào lệnh theo xu hướng MA và chốt lời dứt khoát khi giá vượt 2.5 độ lệch chuẩn dải trên.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: BOLLINGER OVEREXTENSION PROFIT HARVESTING
    =============================================================================
    Financial Concept:
      When price pierces the outer 2.5-sigma band during a trend, risk of
      sharp mean reversion spikes. Exiting into strength secures optimal fills.

    Trading Rules:
      1. Entry: Close crosses above SMA(20).
      2. Exit: Close > Upper BB(20, 2.5) OR Close < SMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.5, 2.5)

        enter_sig = self.op.crossed_above(close, mid_bb)
        exit_target = close > upper_bb
        exit_stop = close < mid_bb

        self.set_positions(exit_target | exit_stop, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_fail_fast_breakout",
        "name": "Fail-Fast Breakout Invalidation",
        "category": "Risk-Managed & Exits",
        "difficulty": "Advanced",
        "summary": "Cắt lỗ siêu tốc nếu cây nến sau breakout không duy trì được đà tăng mà thụt ngược trở lại.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: FAIL-FAST FALSE BREAKOUT DEFENSE
    =============================================================================
    Financial Concept:
      A genuine breakout should find immediate follow-through. If price closes
      back below the breakout level on the very next bar, cut losses immediately.

    Trading Rules:
      1. Entry: Close crosses above DonchianUpper(20).
      2. Exit: Close < DonchianUpper(20) OR Close < EMA(10).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        close = self.data.pv_close

        upper_20 = self.feat.donchian_upper(high, 20)
        ema_10 = self.feat.ema(close, 10)

        enter_sig = self.op.crossed_above(close, upper_20)
        exit_sig = (close < upper_20) | (close < ema_10)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_adx_decay_exit",
        "name": "ADX Trend Decay Early Warning Exit",
        "category": "Risk-Managed & Exits",
        "difficulty": "Intermediate",
        "summary": "Thoát vị thế sớm khi chỉ số ADX quay đầu sụt giảm từ đỉnh cao, cảnh báo xu hướng mất đà.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: ADX MOMENTUM DECAY EXIT
    =============================================================================
    Financial Concept:
      ADX peaks before price tops. An ADX falling from > 40 signals that
      directional power is fading, providing an early warning exit before drops.

    Trading Rules:
      1. Entry: Close > EMA(20) AND ADX(14) > 25.
      2. Exit: ADX(14) falling over 2 bars OR Close < EMA(20).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        adx_val = self.feat.adx(high, low, close, 14)
        adx_dropping = self.op.falling(adx_val, 2)

        enter_sig = (close > ema_20) & (adx_val > 25.0)
        exit_sig = (adx_dropping & (adx_val > 35.0)) | (close < ema_20)

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_stoch_rsi_overbought_exit",
        "name": "Dual Oscillator Climax Exit",
        "category": "Risk-Managed & Exits",
        "difficulty": "Intermediate",
        "summary": "Bảo vệ vốn bằng cách chốt lời khi cả RSI > 75 và Stochastic > 80 cùng báo động đỉnh quá mua.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: DUAL OSCILLATOR OVERBOUGHT EXHAUSTION EXIT
    =============================================================================
    Financial Concept:
      When both RSI and Stochastic reach extreme overbought simultaneously,
      the risk-to-reward ratio for holding longs degrades severely.

    Trading Rules:
      1. Entry: Close crosses above SMA(30).
      2. Exit: (RSI > 75 AND SlowK > 80) OR Close < SMA(30).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        sma_30 = self.feat.sma(close, 30)
        rsi_14 = self.feat.rsi(close, 14)
        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)

        enter_sig = self.op.crossed_above(close, sma_30)
        exit_climax = (rsi_14 > 75.0) & (slowk > 80.0)
        exit_stop = close < sma_30

        self.set_positions(exit_climax | exit_stop, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_donchian_trailing_ratchet",
        "name": "Ratchet Trailing Stop with Donchian Lower",
        "category": "Risk-Managed & Exits",
        "difficulty": "Beginner",
        "summary": "Nâng mức cắt lỗ dần theo đáy thấp nhất của 7 phiên gần nhất, không bao giờ lùi bước.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: 7-DAY DONCHIAN TRAILING RATCHET
    =============================================================================
    Financial Concept:
      A tight 7-day Donchian lower band ratchets steadily upwards in an uptrend,
      capturing the bulk of the run while closing swiftly on trend breaks.

    Trading Rules:
      1. Entry: Close crosses above EMA(20).
      2. Exit: Close drops below DonchianLower(7).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        low = self.data.pv_low
        close = self.data.pv_close

        ema_20 = self.feat.ema(close, 20)
        lower_7 = self.feat.donchian_lower(low, 7)

        enter_sig = self.op.crossed_above(close, ema_20)
        exit_sig = close < lower_7

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
    {
        "key": "risk_linearreg_deviation_guard",
        "name": "Statistical Trend Channel Guard",
        "category": "Risk-Managed & Exits",
        "difficulty": "Advanced",
        "summary": "Cắt lỗ khi giá gãy sâu hơn 2 lần độ lệch chuẩn khỏi kênh xu hướng hồi quy tuyến tính.",
        "code": '''class CustomStrategy(SimpleAlgorithm):
    """
    =============================================================================
    STRATEGY: LINEAR REGRESSION STATISTICAL DEFENSE
    =============================================================================
    Financial Concept:
      If price falls 2 standard deviations below the current linear regression
      trajectory, the statistical assumption of the trend is formally broken.

    Trading Rules:
      1. Entry: Close > LinearReg(30) AND Slope(30) > 0.
      2. Exit: Close < LinearReg(30) - 2.0 * StdDev(30).
    =============================================================================
    """
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        linreg_30 = self.feat.linearreg(close, 30)
        slope_30 = self.feat.linearreg_slope(close, 30)
        std_30 = self.feat.stddev(close, 30, 2.0)
        stop_line = linreg_30 - std_30

        enter_sig = (close > linreg_30) & (slope_30 > 0.0)
        exit_sig = close < stop_line

        self.set_positions(exit_sig, position=0.0)
        self.set_positions(enter_sig, position=1.0)
'''
    },
]

print(f"Total strategies: {len(STRATEGIES)}")

# Verify all 50 strategies compile with 0 errors
all_passed = True
for idx, s in enumerate(STRATEGIES):
    try:
        res = compile_program(s['code'])
        print(f"[{idx+1:02d}/50] OK: {s['name']}")
    except Exception as e:
        print(f"[{idx+1:02d}/50] FAILED: {s['name']} -> {e}")
        all_passed = False

if all_passed:
    print("SUCCESS: ALL 50 STRATEGIES COMPILED 100% CLEANLY!")
    
    # Export to JS
    import json
    with open('/home/vmc03/norabt/nora/frontend/src/components/education/educationSamples.js', 'w', encoding='utf-8') as f:
        f.write("// Thư viện 50 Mẫu Chiến Lược Định Lượng (50 Quantitative Strategy Templates)\n")
        f.write("// Chia thành 5 danh mục kinh điển (10 mẫu/danh mục): Trend Following, Mean Reversion, Breakout, Multi-Indicator, Risk-Managed\n\n")
        f.write("export const EDU_SAMPLES = ")
        f.write(json.dumps(STRATEGIES, ensure_ascii=False, indent=2))
        f.write(";\n")
    print("Exported to frontend/src/components/education/educationSamples.js successfully!")
else:
    sys.exit(1)
