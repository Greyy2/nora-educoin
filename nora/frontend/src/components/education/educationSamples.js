// Thư viện 50 Mẫu Chiến Lược Định Lượng (50 Quantitative Strategy Templates)
// 5 danh mục x 10 mẫu: Trend Following, Mean Reversion, Breakout & Momentum, Multi-Indicator Confluence, Risk-Managed & Exits.
// Mỗi mẫu: profile ('xno' mặc định | 'nora') và position (chỉ nora) được Education.jsx gửi kèm khi chạy.
// Docstring chỉ là phần lý thuyết; quy tắc / chỉ báo / thực thi do explain.py sinh lúc chạy.
// Kiểm tra: test/scripts/lint_edu_samples.py (nghiêm ngặt). Xuất JSON cho backend: test/scripts/export_edu_samples.py.

export const EDU_SAMPLES = [
  {
    "key": "trend_kema_breakout",
    "name": "Keltner Channel Trend (KEMA)",
    "category": "Trend Following",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa vượt lên trên dải trên của kênh Keltner (EMA 20 + 2×ATR 14); thoát khi giá đóng cửa xuống dưới EMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Theo xu hướng giả định rằng các nhịp tăng mạnh có xu hướng kéo dài. Kênh\n    Keltner dựng một dải biến động quanh đường EMA bằng ATR: giá đóng cửa vượt\n    dải trên nghĩa là mức tăng đã lớn hơn biên độ dao động thông thường.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        mid_ema = self.feat.ema(close, 20)\n        vol_atr = self.feat.atr(high, low, close, 14)\n        upper_band = mid_ema + 2.0 * vol_atr\n\n        # Điều kiện vào / thoát lệnh\n        enter_signal = self.op.crossed_above(close, upper_band)\n        exit_signal = close < mid_ema\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_signal, position=0.0)\n        self.set_positions(enter_signal, position=1.0)\n"
  },
  {
    "key": "trend_dual_ema",
    "name": "Dual EMA Crossover (Golden Cross)",
    "category": "Trend Following",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi EMA 20 cắt lên EMA 50; thoát khi EMA 20 cắt xuống EMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Khi đường trung bình ngắn hạn cắt lên đường trung bình dài hạn, đà tăng gần\n    đây mạnh hơn xu hướng nền (giao cắt vàng); chiều ngược lại gọi là giao cắt\n    tử thần.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_fast = self.feat.ema(close, 20)\n        ema_slow = self.feat.ema(close, 50)\n\n        # Điều kiện vào / thoát lệnh\n        bullish_cross = self.op.crossed_above(ema_fast, ema_slow)\n        bearish_cross = self.op.crossed_below(ema_fast, ema_slow)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(bearish_cross, position=0.0)\n        self.set_positions(bullish_cross, position=1.0)\n"
  },
  {
    "key": "trend_triple_ema",
    "name": "Triple EMA Trend Alignment (20/50/200)",
    "category": "Trend Following",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi EMA 20 > EMA 50 > EMA 200 và giá đóng cửa cắt lên EMA 20; thoát khi giá đóng cửa cắt xuống EMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Ba đường trung bình xếp theo thứ tự ngắn trên trung trên dài là dấu hiệu xu\n    hướng tăng đồng thuận ở nhiều thang thời gian; bộ lọc này loại bớt các nhịp\n    hồi trong xu hướng giảm.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        ema_50 = self.feat.ema(close, 50)\n        ema_200 = self.feat.ema(close, 200)\n\n        # Điều kiện vào / thoát lệnh\n        aligned = (ema_20 > ema_50) & (ema_50 > ema_200)\n        entry_trigger = self.op.crossed_above(close, ema_20) & aligned\n        exit_trigger = self.op.crossed_below(close, ema_50)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_trigger, position=0.0)\n        self.set_positions(entry_trigger, position=1.0)\n"
  },
  {
    "key": "trend_adx_directional",
    "name": "ADX + Directional Movement (+DI / -DI)",
    "category": "Trend Following",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi +DI cắt lên -DI và ADX > 25; thoát khi -DI cắt lên +DI hoặc ADX < 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    ADX đo độ mạnh của xu hướng bất kể chiều, còn +DI và -DI so sánh sức mua với\n    sức bán. Kết hợp hai thành phần để chỉ vào lệnh khi xu hướng tăng đã đủ\n    mạnh.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        adx_val = self.feat.adx(high, low, close, 14)\n        plus_di = self.feat.plus_di(high, low, close, 14)\n        minus_di = self.feat.minus_di(high, low, close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(plus_di, minus_di) & (adx_val > 25.0)\n        exit_sig = self.op.crossed_above(minus_di, plus_di) | (adx_val < 20.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_dema_momentum",
    "name": "Double Exponential Moving Average (DEMA)",
    "category": "Trend Following",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên DEMA 30; thoát khi giá đóng cửa cắt xuống DEMA 30.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    DEMA kết hợp một EMA với EMA của chính nó để giảm độ trễ so với EMA thông\n    thường, nên phản ứng sớm hơn ở các điểm đổi chiều của sóng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        dema_val = self.feat.dema(close, 30)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, dema_val)\n        exit_sig = self.op.crossed_below(close, dema_val)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_tema_speed",
    "name": "Triple Exponential Moving Average (TEMA)",
    "category": "Trend Following",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi TEMA 20 cắt lên TEMA 50; thoát khi TEMA 20 cắt xuống TEMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    TEMA kết hợp ba lớp EMA lồng nhau để giảm thêm độ trễ trong khi vẫn làm mượt\n    nhiễu giá, nên bắt nhịp xu hướng trung hạn nhanh hơn EMA.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        tema_fast = self.feat.tema(close, 20)\n        tema_slow = self.feat.tema(close, 50)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(tema_fast, tema_slow)\n        exit_sig = self.op.crossed_below(tema_fast, tema_slow)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_linearreg_slope",
    "name": "Linear Regression Slope Trend",
    "category": "Trend Following",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi độ dốc hồi quy tuyến tính 20 nến cắt lên mức 0 và giá đóng cửa trên SMA 50; thoát khi độ dốc cắt xuống mức 0.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Hồi quy tuyến tính khớp một đường thẳng tốt nhất qua các mức giá gần đây; độ\n    dốc chuyển sang dương cho thấy giá đang đi lên một cách có hướng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        slope_20 = self.feat.linearreg_slope(close, 20)\n        sma_50 = self.feat.sma(close, 50)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(slope_20, 0.0) & (close > sma_50)\n        exit_sig = self.op.crossed_below_value(slope_20, 0.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_wma_volume",
    "name": "Weighted Moving Average (WMA) Crossover",
    "category": "Trend Following",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi WMA 15 cắt lên WMA 45; thoát khi WMA 15 cắt xuống WMA 45.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    WMA gán trọng số tuyến tính, nến càng gần càng nặng, nên phản ứng nhanh hơn\n    trung bình giản đơn mà không mang đuôi đệ quy như đường trung bình mũ.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        wma_fast = self.feat.wma(close, 15)\n        wma_slow = self.feat.wma(close, 45)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(wma_fast, wma_slow)\n        exit_sig = self.op.crossed_below(wma_fast, wma_slow)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_macd_zeroline",
    "name": "MACD Zero-Line Trend Filter",
    "category": "Trend Following",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi đường MACD cắt lên đường tín hiệu trong lúc MACD > 0; thoát khi đường MACD cắt xuống đường tín hiệu.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    MACD là hiệu của đường trung bình mũ nhanh và chậm; MACD dương nghĩa là\n    đường nhanh nằm trên đường chậm, tức xu hướng nền đang tăng. Chỉ nhận giao\n    cắt lên khi MACD ở vùng dương để lọc bớt nhiễu ngược xu hướng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        macd_line, signal_line, macd_hist = self.feat.macd(close, 12, 26, 9)\n        in_bull_regime = macd_line > 0.0\n\n        # Điều kiện vào / thoát lệnh\n        bullish_cross = self.op.crossed_above(macd_line, signal_line)\n        enter_sig = bullish_cross & in_bull_regime\n        exit_sig = self.op.crossed_below(macd_line, signal_line)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "trend_parabolic_ema",
    "name": "EMA Trend Rider (Rising Slope)",
    "category": "Trend Following",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên EMA 20 và EMA 20 tăng liên tục 3 nến; thoát khi giá đóng cửa xuống dưới EMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Đường trung bình đi lên nhiều nến liên tiếp cho thấy xu hướng nền đang được\n    củng cố; lọc theo độ dốc giúp tránh mua khi đường trung bình còn đi ngang.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        ema_rising = self.op.rising(ema_20, 3)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > ema_20) & ema_rising\n        exit_sig = close < ema_20\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_rsi_bb",
    "name": "RSI + Bollinger Bands Oversold Reversal",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi RSI(14) < 30 và giá đóng cửa dưới dải dưới Bollinger (20, 2.0); thoát khi RSI(14) > 50 hoặc giá đóng cửa trên đường giữa Bollinger.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giá có tính đàn hồi: khi lệch quá xa khỏi mức trung bình, nó có xu hướng\n    quay lại. RSI thấp và giá thủng dải dưới Bollinger là hai dấu hiệu độc lập\n    của trạng thái bán quá mức.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        rsi_14 = self.feat.rsi(close, 14)\n        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)\n\n        # Điều kiện vào / thoát lệnh\n        oversold_entry = (rsi_14 < 30.0) & (close < lower_bb)\n        exit_rebound = (rsi_14 > 50.0) | (close > mid_bb)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_rebound, position=0.0)\n        self.set_positions(oversold_entry, position=1.0)\n"
  },
  {
    "key": "revert_zscore_extreme",
    "name": "Rolling Z-Score Statistical Reversion",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi Z-Score 20 nến cắt lên mức -2; thoát khi Z-Score ≥ 0.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Z-Score cho biết giá đang cách trung bình trượt bao nhiêu độ lệch chuẩn. Giá\n    rơi xa dưới trung bình rồi bắt đầu quay lên là kịch bản hồi quy về trung\n    bình điển hình.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        z_val = self.feat.zscore(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(z_val, -2.0)\n        exit_sig = z_val >= 0.0\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_cci_oversold",
    "name": "Commodity Channel Index (CCI) Snapback",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi CCI(14) cắt lên mức -100; thoát khi CCI(14) cắt lên mức 100.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    CCI đo mức lệch của giá điển hình so với trung bình của nó; giá trị rất thấp\n    báo hiệu áp lực bán đã cạn, và khi CCI quay lên khỏi vùng đó nhịp hồi thường\n    bắt đầu.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        cci_val = self.feat.cci(high, low, close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(cci_val, -100.0)\n        exit_sig = self.op.crossed_above_value(cci_val, 100.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_willr_elastic",
    "name": "Williams %R Extreme Elasticity",
    "category": "Mean Reversion",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi Williams %R(14) cắt lên mức -80; thoát khi Williams %R(14) cắt lên mức -20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Williams %R cho biết giá đóng cửa nằm ở đâu so với vùng giá cao nhất và thấp\n    nhất trong kỳ quan sát, trên thang từ 0 đến -100; dưới -80 là vùng bán quá\n    mức.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        willr_val = self.feat.willr(high, low, close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(willr_val, -80.0)\n        exit_sig = self.op.crossed_above_value(willr_val, -20.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_stoch_k_d",
    "name": "Stochastic Oscillator (%K, %D) Bull Cross",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi %K cắt lên %D trong lúc %K < 25; thoát khi %K cắt xuống %D trong lúc %K > 70.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Stochastic so sánh giá đóng cửa với biên độ giá trong kỳ quan sát. Đường %K\n    (đã làm mượt) cắt lên đường %D từ vùng thấp báo hiệu động lượng giảm đang\n    đảo chiều.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(slowk, slowd) & (slowk < 25.0)\n        exit_sig = self.op.crossed_below(slowk, slowd) & (slowk > 70.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_bbands_tight",
    "name": "Bollinger Bands Lower Touch & Bounce",
    "category": "Mean Reversion",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên dải dưới Bollinger (20, 2.0); thoát khi giá đóng cửa cắt lên đường giữa Bollinger.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giá nằm ngoài dải Bollinger là độ phân tán bất thường; khi đóng cửa quay lại\n    bên trong dải, đó là dấu hiệu mức giá thấp đã bị từ chối.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, lower_bb)\n        exit_sig = self.op.crossed_above(close, mid_bb)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_mfi_oversold",
    "name": "Money Flow Index (MFI) Volume Reversion",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi MFI(14) cắt lên mức 20; thoát khi MFI(14) cắt lên mức 60.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    MFI là chỉ báo dao động đưa cả biến động giá lẫn khối lượng giao dịch vào\n    dòng tiền; MFI rất thấp cho thấy lực bán kèm khối lượng đã suy yếu.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n        volume = self.data.pv_volume\n\n        # Chỉ báo\n        mfi_val = self.feat.mfi(high, low, close, volume, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(mfi_val, 20.0)\n        exit_sig = self.op.crossed_above_value(mfi_val, 60.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_returns_dip",
    "name": "Multi-Day Cumulative Return Dip Buying",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi lợi suất 5 nến thấp hơn -8% và giá đóng cửa cao hơn giá đóng cửa nến trước; thoát khi lợi suất 5 nến vượt 3%.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Thị trường tiền mã hoá thường phản ứng thái quá khi bán tháo; sau chuỗi giảm\n    mạnh nhiều phiên, nến hồi đầu tiên là dấu hiệu của một nhịp bật lại ngắn\n    hạn.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ret_5d = self.feat.returns(close, 5)\n        prev_close = self.op.shift(close, 1)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (ret_5d < -0.08) & (close > prev_close)\n        exit_sig = ret_5d > 0.03\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_linearreg_disparity",
    "name": "Linear Regression Channel Deviation",
    "category": "Mean Reversion",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên đường hồi quy tuyến tính 20 nến trừ 2 độ lệch chuẩn; thoát khi giá đóng cửa cắt lên chính đường hồi quy.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Đường hồi quy tuyến tính là quỹ đạo giá hợp lý theo thống kê; giá thấp hơn\n    quỹ đạo đó một khoảng lớn thì có xu hướng quay về đường này.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        linreg = self.feat.linearreg(close, 20)\n        std_val = self.feat.stddev(close, 20, 1.0)\n        lower_band = linreg - 2.0 * std_val\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, lower_band)\n        exit_sig = self.op.crossed_above(close, linreg)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "revert_rsi_divergence",
    "name": "RSI Rebound with Fast SMA Filter",
    "category": "Mean Reversion",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi RSI(14) < 35 và giá đóng cửa cắt lên SMA 5; thoát khi RSI(14) > 55.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    RSI có thể kẹt ở vùng bán quá mức trong các đợt thanh lý kéo dài; đòi hỏi\n    giá đóng cửa cắt lên một đường trung bình rất ngắn giúp loại bớt các pha\n    giảm chưa dừng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        rsi_14 = self.feat.rsi(close, 14)\n        sma_5 = self.feat.sma(close, 5)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (rsi_14 < 35.0) & self.op.crossed_above(close, sma_5)\n        exit_sig = rsi_14 > 55.0\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_donchian_turtle",
    "name": "Donchian Channel Breakout (Turtle Trading)",
    "category": "Breakout & Momentum",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa vượt đỉnh cao nhất của 20 nến trước đó; thoát khi giá đóng cửa xuống dưới đáy thấp nhất của 10 nến trước đó.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Phá vỡ kênh giá giúp bám theo các giai đoạn xu hướng lớn mà không cần dự\n    đoán: mua khi giá lập đỉnh mới và rời đi khi giá thủng đáy gần hơn. Đây là ý\n    tưởng cốt lõi của hệ thống Turtle.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_20 = self.feat.donchian_upper(high, 20)\n        lower_10 = self.feat.donchian_lower(low, 10)\n\n        # Điều kiện vào / thoát lệnh\n        breakout_entry = close > upper_20\n        trailing_exit = close < lower_10\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(trailing_exit, position=0.0)\n        self.set_positions(breakout_entry, position=1.0)\n"
  },
  {
    "key": "breakout_bb_squeeze",
    "name": "Bollinger Upper Band Breakout",
    "category": "Breakout & Momentum",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên dải trên Bollinger (20, 2.0); thoát khi giá đóng cửa cắt xuống đường giữa Bollinger.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Biến động có tính chu kỳ: sau giai đoạn nén thường là giai đoạn bung rộng.\n    Giá đóng cửa vượt dải trên là dấu hiệu biến động đang mở rộng theo chiều\n    tăng; mẫu này không tự đo mức nén, chỉ phản ứng khi giá đã vượt dải.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, upper_bb)\n        exit_sig = self.op.crossed_below(close, mid_bb)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_roc_surge",
    "name": "ROC Momentum Surge",
    "category": "Breakout & Momentum",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi ROC(10) cắt lên mức 5 và giá đóng cửa trên EMA 20; thoát khi ROC(10) cắt xuống mức 0.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    ROC là phần trăm thay đổi của giá so với n nến trước, tức tốc độ tăng. Khi\n    tốc độ vượt một ngưỡng dương, đà tăng đang tăng tốc.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        roc_10 = self.feat.roc(close, 10)\n        ema_20 = self.feat.ema(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(roc_10, 5.0) & (close > ema_20)\n        exit_sig = self.op.crossed_below_value(roc_10, 0.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_volume_zscore",
    "name": "High-Volume Breakout (Volume Z-Score Spike)",
    "category": "Breakout & Momentum",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa vượt đỉnh cao nhất của 20 nến trước đó cùng Z-Score khối lượng vượt 1.5; thoát khi giá đóng cửa xuống dưới SMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Phá vỡ thật thường đi kèm sự tham gia bất thường của khối lượng. Z-Score\n    khối lượng cao cho thấy phiên đó giao dịch sôi động hơn hẳn mức thường lệ.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        close = self.data.pv_close\n        volume = self.data.pv_volume\n\n        # Chỉ báo\n        upper_20 = self.feat.donchian_upper(high, 20)\n        vol_z = self.feat.volume_z(volume, 20)\n        sma_20 = self.feat.sma(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > upper_20) & (vol_z > 1.5)\n        exit_sig = close < sma_20\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_natr_range",
    "name": "Normalized ATR (NATR) Volatility Breakout",
    "category": "Breakout & Momentum",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi NATR(14) cắt lên mức 4 và giá đóng cửa trên EMA 20; thoát khi giá đóng cửa xuống dưới EMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    NATR là ATR chuẩn hoá theo phần trăm giá nên so sánh được biên độ dao động\n    giữa các giai đoạn giá khác nhau; NATR tăng vọt cho thấy biến động đang mở\n    rộng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        natr_val = self.feat.natr(high, low, close, 14)\n        ema_20 = self.feat.ema(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(natr_val, 4.0) & (close > ema_20)\n        exit_sig = close < ema_20\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_obv_accumulation",
    "name": "On-Balance Volume (OBV) Trend Breakout",
    "category": "Breakout & Momentum",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi OBV cắt lên đường SMA 20 của chính nó và giá đóng cửa trên EMA 20; thoát khi OBV cắt xuống đường SMA 20 của OBV.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    OBV cộng khối lượng của các phiên tăng và trừ khối lượng của các phiên giảm.\n    OBV vượt đường trung bình của chính nó cho thấy dòng tiền mua đang chiếm ưu\n    thế.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n        volume = self.data.pv_volume\n\n        # Chỉ báo\n        obv_val = self.feat.obv(close, volume)\n        obv_sma = self.feat.sma(obv_val, 20)\n        ema_20 = self.feat.ema(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(obv_val, obv_sma) & (close > ema_20)\n        exit_sig = self.op.crossed_below(obv_val, obv_sma)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_momentum_10d",
    "name": "Absolute Momentum 10-Day Threshold",
    "category": "Breakout & Momentum",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi Momentum(10) cắt lên mức 0 và giá đóng cửa trên SMA 50; thoát khi Momentum(10) cắt xuống mức 0.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Momentum là chênh lệch tuyệt đối giữa giá đóng cửa hiện tại và giá đóng cửa\n    của n nến trước; chuyển từ âm sang dương nghĩa là giá đã cao hơn mức của n\n    nến trước.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        mom_val = self.feat.momentum(close, 10)\n        sma_50 = self.feat.sma(close, 50)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(mom_val, 0.0) & (close > sma_50)\n        exit_sig = self.op.crossed_below_value(mom_val, 0.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_range_pct",
    "name": "Daily Range Expansion (High - Low) / Close",
    "category": "Breakout & Momentum",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi biên độ nến (cao - thấp)/đóng cửa > 6%, nến tăng (đóng cửa > mở cửa) và giá đóng cửa trên SMA 20; thoát khi giá đóng cửa cắt xuống SMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Biên độ nến lớn thể hiện sự quyết liệt của dòng tiền; nến tăng với biên độ\n    rộng phá vỡ trạng thái đi ngang thường là điểm khởi đầu của một nhịp chạy.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        open_p = self.data.pv_open\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        range_val = self.feat.range_pct(high, low, close)\n        sma_20 = self.feat.sma(close, 20)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (range_val > 6.0) & (close > open_p) & (close > sma_20)\n        exit_sig = self.op.crossed_below(close, sma_20)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_stddev_channel",
    "name": "Standard Deviation Dynamic Channel Breakout",
    "category": "Breakout & Momentum",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên SMA 20 + 2.5×StdDev; thoát khi giá đóng cửa xuống dưới SMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giá đóng cửa vượt trung bình cộng một khoảng bằng vài độ lệch chuẩn là biến\n    động hiếm gặp, thường đi cùng một đà tăng mạnh.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        sma_20 = self.feat.sma(close, 20)\n        std_val = self.feat.stddev(close, 20, 2.5)\n        upper_threshold = sma_20 + std_val\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, upper_threshold)\n        exit_sig = close < sma_20\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "breakout_multi_week_high",
    "name": "Rolling 30-Day Multi-Week High Breakout",
    "category": "Breakout & Momentum",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa vượt đỉnh cao nhất của 30 nến trước đó; thoát khi giá đóng cửa xuống dưới SMA 30.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Phá đỉnh nhiều tuần biến vùng kháng cự cũ thành hỗ trợ mới và thu hút dòng\n    tiền đi theo đà.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_30 = self.feat.donchian_upper(high, 30)\n        sma_30 = self.feat.sma(close, 30)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = close > upper_30\n        exit_sig = close < sma_30\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_ema_rsi_pullback",
    "name": "EMA Trend + RSI Dip Buying (Trend Pullback)",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên EMA 50 và RSI(14) cắt lên mức 40; thoát khi giá đóng cửa xuống dưới EMA 50 hoặc RSI(14) > 75.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Mua nhịp điều chỉnh trong xu hướng tăng kết hợp lợi thế của việc đi theo xu\n    hướng với vùng giá vào lệnh thuận lợi của hồi quy về trung bình.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_50 = self.feat.ema(close, 50)\n        rsi_14 = self.feat.rsi(close, 14)\n        in_uptrend = close > ema_50\n        rsi_rebound = self.op.crossed_above_value(rsi_14, 40.0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = in_uptrend & rsi_rebound\n        exit_sig = (close < ema_50) | (rsi_14 > 75.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_keltner_macd",
    "name": "Keltner Channel + MACD Confirmation",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên dải trên Keltner (EMA 20 + 2×ATR 14) và histogram MACD > 0; thoát khi giá đóng cửa xuống dưới EMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giá vượt dải Keltner xác nhận biến động tăng, còn histogram MACD dương cho\n    thấy đà tăng đang được củng cố, giúp lọc bớt các cú vượt dải giả.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        mid_ema = self.feat.ema(close, 20)\n        atr_val = self.feat.atr(high, low, close, 14)\n        upper_band = mid_ema + 2.0 * atr_val\n        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > upper_band) & (macd_hist > 0.0)\n        exit_sig = close < mid_ema\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_dual_ema_adx",
    "name": "Dual EMA + ADX Trend Strength Filter",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi EMA 20 cắt lên EMA 50 và ADX > 25; thoát khi EMA 20 cắt xuống EMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Hệ thống giao cắt đường trung bình hay bị nhiễu khi thị trường đi ngang; yêu\n    cầu ADX cao giúp chỉ vào lệnh khi xu hướng đã đủ rõ.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        ema_50 = self.feat.ema(close, 50)\n        adx_val = self.feat.adx(high, low, close, 14)\n        golden_cross = self.op.crossed_above(ema_20, ema_50)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = golden_cross & (adx_val > 25.0)\n        exit_sig = self.op.crossed_below(ema_20, ema_50)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_bb_rsi_adx",
    "name": "Bollinger Mid + RSI + ADX Filter",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên đường giữa Bollinger (20, 2.0), RSI(14) > 50 và ADX > 20; thoát khi giá đóng cửa xuống dưới đường giữa Bollinger.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Ba nhóm thông tin cùng đồng thuận: vị trí giá so với đường giữa của dải biến\n    động (Bollinger), động lượng (RSI) và độ mạnh xu hướng (ADX).\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.0, 2.0)\n        rsi_14 = self.feat.rsi(close, 14)\n        adx_val = self.feat.adx(high, low, close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, mid_bb) & (rsi_14 > 50.0) & (adx_val > 20.0)\n        exit_sig = close < mid_bb\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_volume_ema_cross",
    "name": "EMA Golden Cross + Volume Spike Confluence",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi EMA 20 cắt lên EMA 50 và Z-Score khối lượng vượt 1.0; thoát khi giá đóng cửa xuống dưới EMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giao cắt vàng đi kèm khối lượng trên mức bình thường cho thấy có sự tham gia\n    thực sự của dòng tiền, thay vì trôi giá khi thanh khoản mỏng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n        volume = self.data.pv_volume\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        ema_50 = self.feat.ema(close, 50)\n        vol_z = self.feat.volume_z(volume, 20)\n        cross = self.op.crossed_above(ema_20, ema_50)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = cross & (vol_z > 1.0)\n        exit_sig = close < ema_50\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_donchian_macd",
    "name": "Donchian Breakout + MACD Alignment",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa vượt đỉnh cao nhất của 20 nến trước đó và đường MACD nằm trên đường tín hiệu; thoát khi giá đóng cửa xuống dưới đáy thấp nhất của 10 nến trước đó.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Lọc các cú phá kênh Donchian bằng MACD để chỉ nhận những lần phá vỡ có động\n    lượng tăng đi kèm, tránh các nhịp trôi yếu.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_20 = self.feat.donchian_upper(high, 20)\n        lower_10 = self.feat.donchian_lower(low, 10)\n        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > upper_20) & (macd_line > sig_line)\n        exit_sig = close < lower_10\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_cci_ema_trend",
    "name": "EMA 200 Macro Trend + CCI Dip Rebound",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên EMA 200 và CCI(14) cắt lên mức -100; thoát khi giá đóng cửa xuống dưới EMA 50 hoặc CCI(14) > 150.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Giao dịch cùng chiều với đường EMA dài hạn tạo lợi thế về cấu trúc; mua nhịp\n    hồi của CCI trong xu hướng lớn đi lên giúp điểm vào ngắn hạn thuận chiều xu\n    hướng vĩ mô.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_200 = self.feat.ema(close, 200)\n        ema_50 = self.feat.ema(close, 50)\n        cci_val = self.feat.cci(high, low, close, 14)\n        in_macro_trend = close > ema_200\n        cci_cross = self.op.crossed_above_value(cci_val, -100.0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = in_macro_trend & cci_cross\n        exit_sig = (close < ema_50) | (cci_val > 150.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_stoch_rsi_trend",
    "name": "Stochastic & RSI Confluence System",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi RSI(14) cắt lên mức 35 và %K lớn hơn %D; thoát khi RSI(14) > 65.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Khi cả RSI và Stochastic cùng xác nhận một nhịp bật khỏi vùng bán quá mức,\n    tín hiệu được kiểm chứng chéo bởi hai chỉ báo thay vì một.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        rsi_14 = self.feat.rsi(close, 14)\n        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above_value(rsi_14, 35.0) & (slowk > slowd)\n        exit_sig = rsi_14 > 65.0\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_obv_rsi_momentum",
    "name": "OBV Volume Accumulation + RSI Momentum",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi OBV nằm trên đường SMA 20 của chính nó và RSI(14) cắt lên mức 50; thoát khi RSI(14) < 45.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Khối lượng thường đi trước giá: OBV cao hơn đường trung bình của chính nó\n    cho thấy dòng tiền đang tích luỹ, còn RSI vượt mốc giữa xác nhận đà giá bắt\n    đầu đi lên.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n        volume = self.data.pv_volume\n\n        # Chỉ báo\n        obv_val = self.feat.obv(close, volume)\n        obv_sma = self.feat.sma(obv_val, 20)\n        rsi_14 = self.feat.rsi(close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (obv_val > obv_sma) & self.op.crossed_above_value(rsi_14, 50.0)\n        exit_sig = rsi_14 < 45.0\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "confluence_triple_screen",
    "name": "Triple Filter: EMA + MACD + RSI",
    "category": "Multi-Indicator Confluence",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên EMA 50, MACD > 0 và RSI(14) cắt lên mức 50; thoát khi giá đóng cửa xuống dưới EMA 50.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Phiên bản đơn giản hoá của ý tưởng ba màn hình của Elder: lớp thứ nhất lọc\n    xu hướng chính (EMA), lớp thứ hai đo nhịp sóng (MACD), lớp thứ ba chọn điểm\n    vào (RSI).\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_50 = self.feat.ema(close, 50)\n        macd_line, sig_line, macd_hist = self.feat.macd(close, 12, 26, 9)\n        rsi_14 = self.feat.rsi(close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > ema_50) & (macd_line > 0.0) & self.op.crossed_above_value(rsi_14, 50.0)\n        exit_sig = close < ema_50\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_chandelier_exit",
    "name": "Chandelier Exit (ATR Trailing Stop)",
    "category": "Risk-Managed & Exits",
    "difficulty": "Advanced",
    "profile": "nora",
    "position": {
      "stop_loss_rate": 3.0,
      "trailing_stop": 3.0,
      "atr_frame": "24h"
    },
    "summary": "Mua khi giá đóng cửa cắt lên EMA 20; cắt lỗ ban đầu 3×ATR và trailing stop 3×ATR bám theo đỉnh giá kể từ lúc vào lệnh.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Chandelier Exit treo mức dừng lỗ từ đỉnh giá cao nhất đạt được: khi giá\n    tăng, mức dừng được nâng dần theo, nhờ đó khoá lại một phần lợi nhuận chưa\n    chốt.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n\n        # Chỉ có luật vào; thoát bằng cắt lỗ và trailing stop của hồ sơ nora (khai báo trong position)\n        enter_sig = self.op.crossed_above(close, ema_20)\n\n        # Vị thế: 1 = LONG\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_dual_exit_asymmetric",
    "name": "Dual-Condition Asymmetric Exit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên EMA 20 và RSI(14) > 50; thoát theo tín hiệu khi giá đóng cửa xuống dưới EMA 20 hoặc RSI(14) > 80.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Mỗi lý do thoát lệnh ứng với một trạng thái thị trường khác nhau: thoát khi\n    xu hướng gãy để bảo toàn vốn, hoặc thoát khi động lượng cạn kiệt để giữ lại\n    phần lợi nhuận đã có.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        rsi_14 = self.feat.rsi(close, 14)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, ema_20) & (rsi_14 > 50.0)\n        exit_stop = close < ema_20\n        exit_target = rsi_14 > 80.0\n        exit_combined = exit_stop | exit_target\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_combined, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_roc_momentum_exhaustion",
    "name": "ROC Momentum Exhaustion with Take-Profit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Intermediate",
    "profile": "nora",
    "position": {
      "stop_loss_rate": 3.0,
      "take_profit_rate": 5.0,
      "atr_frame": "24h"
    },
    "summary": "Mua khi giá đóng cửa trên EMA 30 và ROC(10) > 3; chốt lời cố định 5×ATR, cắt lỗ 3×ATR, và thoát theo tín hiệu khi giá đóng cửa xuống dưới EMA 30 hoặc ROC(10) < 0.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Đà tăng cực đại thường không bền: khi tốc độ tăng suy yếu hoặc giá đã đạt\n    mục tiêu lợi nhuận, đóng vị thế giúp giữ lại phần lợi nhuận cao nhất.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_30 = self.feat.ema(close, 30)\n        roc_10 = self.feat.roc(close, 10)\n\n        # Điều kiện vào / thoát theo tín hiệu; chốt lời và cắt lỗ khai báo trong position của hồ sơ nora\n        enter_sig = (close > ema_30) & (roc_10 > 3.0)\n        exit_sig = (close < ema_30) | (roc_10 < 0.0)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_atr_fixed_multiple_stop",
    "name": "Fixed Multiple ATR Volatility Stop",
    "category": "Risk-Managed & Exits",
    "difficulty": "Beginner",
    "profile": "nora",
    "position": {
      "stop_loss_rate": 2.0,
      "atr_frame": "24h"
    },
    "summary": "Mua khi giá đóng cửa cắt lên SMA 20; cắt lỗ cố định 2×ATR tính từ giá vào lệnh, và thoát theo tín hiệu khi giá đóng cửa xuống dưới SMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Mức dừng lỗ tính bằng số tiền cố định thường không hợp với tiền mã hoá vì\n    biến động đổi theo từng giai đoạn. Mức dừng theo ATR tự giãn ra khi thị\n    trường dao động mạnh và co lại khi thị trường yên ắng.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        sma_20 = self.feat.sma(close, 20)\n\n        # Điều kiện vào / thoát theo tín hiệu; cắt lỗ 2×ATR khai báo trong position của hồ sơ nora\n        enter_sig = self.op.crossed_above(close, sma_20)\n        exit_sig = close < sma_20\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_bollinger_band_profit_take",
    "name": "Bollinger Band Overextension Exit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên đường giữa Bollinger (20, 2.5); thoát theo tín hiệu khi giá đóng cửa vượt dải trên Bollinger hoặc xuống dưới đường giữa.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Khi giá vọt ra ngoài dải trên Bollinger giữa một xu hướng tăng, nguy cơ quay\n    về trung bình tăng lên, nên có thể thoát khi giá đã đi một đoạn dài.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_bb, mid_bb, lower_bb = self.feat.bbands(close, 20, 2.5, 2.5)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, mid_bb)\n        exit_target = close > upper_bb\n        exit_stop = close < mid_bb\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_target | exit_stop, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_fail_fast_breakout",
    "name": "Fail-Fast Breakout Invalidation",
    "category": "Risk-Managed & Exits",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên đỉnh cao nhất của 20 nến trước đó; thoát theo tín hiệu khi giá đóng cửa xuống dưới đỉnh cao nhất của 20 nến trước đó (tính lại ở mỗi nến) hoặc xuống dưới EMA 10.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Một cú phá vỡ thật nên có lực đi tiếp ngay. Vì đỉnh 20 nến được tính lại ở\n    mỗi nến, điều kiện thoát này rất khắt khe: nến sau cú phá vỡ phải đóng cửa\n    không thấp hơn đỉnh cao nhất của 20 nến gần nhất thì vị thế mới còn được\n    giữ.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        close = self.data.pv_close\n\n        # Chỉ báo\n        upper_20 = self.feat.donchian_upper(high, 20)\n        ema_10 = self.feat.ema(close, 10)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, upper_20)\n        exit_sig = (close < upper_20) | (close < ema_10)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_adx_decay_exit",
    "name": "ADX Trend Decay Early Warning Exit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên EMA 20 và ADX > 25; thoát theo tín hiệu khi ADX giảm liên tục 2 nến trong lúc ADX > 35, hoặc khi giá đóng cửa xuống dưới EMA 20.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    ADX thường đạt đỉnh trước khi giá đạt đỉnh; ADX cao nhưng bắt đầu giảm cho\n    thấy sức mạnh của xu hướng đang suy yếu, đó là cảnh báo sớm trước khi giá\n    đảo chiều.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        adx_val = self.feat.adx(high, low, close, 14)\n        adx_dropping = self.op.falling(adx_val, 2)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > ema_20) & (adx_val > 25.0)\n        exit_sig = (adx_dropping & (adx_val > 35.0)) | (close < ema_20)\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_stoch_rsi_overbought_exit",
    "name": "Dual Oscillator Climax Exit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Intermediate",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên SMA 30; thoát theo tín hiệu khi RSI(14) > 75 và %K > 80, hoặc khi giá đóng cửa xuống dưới SMA 30.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Khi cả RSI và Stochastic cùng ở vùng quá mua, tỷ lệ lợi nhuận kỳ vọng so với\n    rủi ro của việc tiếp tục giữ vị thế mua giảm đi.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        high = self.data.pv_high\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        sma_30 = self.feat.sma(close, 30)\n        rsi_14 = self.feat.rsi(close, 14)\n        slowk, slowd = self.feat.stoch(high, low, close, 14, 3, 0, 3, 0)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, sma_30)\n        exit_climax = (rsi_14 > 75.0) & (slowk > 80.0)\n        exit_stop = close < sma_30\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_climax | exit_stop, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_donchian_trailing_ratchet",
    "name": "Donchian Lower Channel Exit",
    "category": "Risk-Managed & Exits",
    "difficulty": "Beginner",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa cắt lên EMA 20; thoát theo tín hiệu khi giá đóng cửa xuống dưới đáy thấp nhất của 7 nến trước đó.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Đáy thấp nhất của vài nến gần nhất thường được nâng lên khi giá đi lên\n    (nhưng không đơn điệu), nên dùng nó làm mức thoát giúp bám sát xu hướng. Mức\n    này chỉ là điều kiện tín hiệu trên giá đóng cửa, không phải lệnh trailing\n    stop của hồ sơ.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        low = self.data.pv_low\n        close = self.data.pv_close\n\n        # Chỉ báo\n        ema_20 = self.feat.ema(close, 20)\n        lower_7 = self.feat.donchian_lower(low, 7)\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = self.op.crossed_above(close, ema_20)\n        exit_sig = close < lower_7\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  },
  {
    "key": "risk_linearreg_deviation_guard",
    "name": "Statistical Trend Channel Guard",
    "category": "Risk-Managed & Exits",
    "difficulty": "Advanced",
    "profile": "xno",
    "summary": "Mua khi giá đóng cửa trên đường hồi quy tuyến tính 30 nến và độ dốc hồi quy > 0; thoát theo tín hiệu khi giá đóng cửa xuống dưới đường hồi quy trừ 2 độ lệch chuẩn.",
    "code": "class CustomStrategy(SimpleAlgorithm):\n    \"\"\"\n    Nếu giá rơi xuống dưới quỹ đạo hồi quy một khoảng bằng vài độ lệch chuẩn,\n    giả định về xu hướng tăng hiện tại coi như đã bị phá vỡ về mặt thống kê.\n    \"\"\"\n    timeframe = \"24h\"\n\n    def __algorithm__(self):\n        # Dữ liệu nến đã đóng cửa\n        close = self.data.pv_close\n\n        # Chỉ báo\n        linreg_30 = self.feat.linearreg(close, 30)\n        slope_30 = self.feat.linearreg_slope(close, 30)\n        std_30 = self.feat.stddev(close, 30, 2.0)\n        stop_line = linreg_30 - std_30\n\n        # Điều kiện vào / thoát lệnh\n        enter_sig = (close > linreg_30) & (slope_30 > 0.0)\n        exit_sig = close < stop_line\n\n        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước\n        self.set_positions(exit_sig, position=0.0)\n        self.set_positions(enter_sig, position=1.0)\n"
  }
]
