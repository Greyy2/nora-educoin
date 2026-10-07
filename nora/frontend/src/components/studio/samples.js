// Mẫu chiến lược tĩnh theo ngôn ngữ chiến lược (docs/bmad/p7_python_strategies.md §3): chỉ các câu lệnh gán và self.set_positions,
// mặc định xử lý theo nến ngày. Code không được thực thi ở trình duyệt; máy chủ biên dịch bằng ast + danh sách trắng.

export const SAMPLES = [
  {
    key: 'kema_long',
    name: 'KEMA long 24h',
    note: 'Kênh Keltner: mua khi giá vượt dải trên EMA + 2 ATR, thoát khi giá xuống dưới EMA.',
    code: `class KemaLong(SimpleAlgorithm):
    """Kênh Keltner (KEMA) chỉ long, nến ngày."""
    timeframe = "24h"

    def __algorithm__(self):
        high = self.data.pv_high
        low = self.data.pv_low
        close = self.data.pv_close

        mid = self.feat.ema(close, 20)
        atr = self.feat.atr(high, low, close, 14)
        upper = mid + 2.0 * atr

        enter = self.op.crossed_above(close, upper)
        leave = close < mid

        # lệnh gọi sau ghi đè lệnh trước: thoát trước, vào sau
        self.set_positions(leave, position=0)
        self.set_positions(enter, position=1)
`,
  },
  {
    key: 'rsi_bb_revert',
    name: 'RSI + Bollinger hồi quy',
    note: 'Mua khi quá bán (RSI thấp và giá dưới dải dưới), thoát khi RSI hồi hoặc giá chạm dải trên.',
    code: `class RsiBollingerRevert(SimpleAlgorithm):
    """Hồi quy về trung bình: RSI quá bán + giá dưới dải Bollinger dưới."""
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        rsi = self.feat.rsi(close, 14)
        upper, middle, lower = self.feat.bbands(close, 20, 2.0)

        oversold = (rsi < 30) & (close < lower)
        recovered = (rsi > 55) | (close > upper)

        self.set_positions(recovered, position=0)
        self.set_positions(oversold, position=1)
`,
  },
  {
    key: 'ema_cross_ls',
    name: 'EMA cắt nhau long/short',
    note: 'Long khi EMA 20 cắt lên EMA 50, short khi cắt xuống. Chân short cần hồ sơ nora.',
    code: `class EmaCrossLongShort(SimpleAlgorithm):
    """EMA nhanh cắt EMA chậm: long khi cắt lên, short khi cắt xuống."""
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close

        fast = self.feat.ema(close, 20)
        slow = self.feat.ema(close, 50)

        go_long = self.op.crossed_above(fast, slow)
        go_short = self.op.crossed_below(fast, slow)

        self.set_positions(go_long, position=1)
        self.set_positions(go_short, position=-1)
`,
  },
]

/** Khung trống cho tab mới. */
export const BLANK_CODE = `class MyStrategy(SimpleAlgorithm):
    timeframe = "24h"

    def __algorithm__(self):
        close = self.data.pv_close
        fast = self.feat.ema(close, 20)
        slow = self.feat.ema(close, 50)
        self.set_positions(fast > slow, position=1)
        self.set_positions(fast <= slow, position=0)
`
