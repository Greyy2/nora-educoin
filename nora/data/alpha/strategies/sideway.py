"""Sideway (đi ngang) — hồi quy về trung bình: chỉ đánh khi Efficiency Ratio thấp (thị trường đi ngang), RSI cực trị và giá ngoài dải Bollinger.

Dạng đã biên dịch (cây AST của sổ chiến lược) sinh lại từ file này, không sửa tay.
"""
STRATEGY = {
    "id": "sideway",
    "name": "Sideway",
    "kind": "Đi ngang",
    "doc": "combined",
    "description": "Đánh biên khi thị trường đi ngang: mua vùng quá bán, bán vùng quá mua; đứng ngoài khi có xu hướng.",
    "idea": "Hồi quy về trung bình khi thị trường đi ngang: giá chạm cực trị dải Bollinger lúc xu hướng yếu thường là phản ứng thái quá, kỳ vọng quay về đường giữa.",
    "order": 1,
}


class SidewayLong(SimpleAlgorithm):
    id = "sideway_long"
    family = "Sideway (đi ngang)"
    description = "Chỉ đánh khi thị trường đi ngang (ER thấp): RSI quá bán và giá dưới dải Bollinger dưới → mua. Chốt lời / cắt lỗ theo ATR."

    def __algorithm__(self):
        e = self.frame(p('entry_tf', '5m',
              choices=('1m', '5m', '15m', '1h'),
              label="Khung điểm vào",
              help="Khung nến tính RSI và dải Bollinger."))
        rsi = self.feat.rsi(e.pv_close, timeperiod=p('rsi_n', 14,
              lo=2,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ RSI",
              help="Chu kỳ RSI (Wilder)."))
        rsi_lo = p('rsi_lo', 25,
              lo=10.0,
              hi=45.0,
              step=1.0,
              label="Ngưỡng RSI quá bán",
              help="Ngưỡng RSI kích hoạt bắt hồi.",
              grid=(20, 25, 30))
        bb_n = p('bb_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ Bollinger",
              help="Chu kỳ đường giữa của dải Bollinger.")
        bb_k = p('bb_k', 2.0,
              lo=1.0,
              hi=4.0,
              step=0.1,
              unit="σ",
              label="Độ rộng Bollinger (k)",
              help="Dải cách đường giữa k độ lệch chuẩn.")
        bb_upper, bb_mid, bb_lower = self.feat.bbands(e.pv_close, timeperiod=bb_n, nbdevup=bb_k, nbdevdn=bb_k)
        r = self.frame(p('regime_tf', '1h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung regime",
              help="Khung đo mức đi ngang bằng Efficiency Ratio."))
        er = self.feat.er(r.pv_close, timeperiod=p('er_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ ER",
              help="Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."))
        er_max = p('er_max', 0.3,
              lo=0.1,
              hi=0.6,
              step=0.05,
              label="Ngưỡng ER tối đa",
              help="Chỉ bắt hồi khi ER thấp hơn mức này (thị trường đi ngang).",
              grid=(0.2, 0.3))
        p('stop_loss_rate', 1.5, grid=(1.0, 1.5, 2.5))
        p('take_profit_rate', 1.5, grid=(0.75, 1.0, 1.5, 2.5))
        p('timeout', 1440, grid=(240, 1440))
        self.set_positions((rsi < rsi_lo) & (e.pv_close < bb_lower) & (er < er_max), position=1)


class SidewayShort(SimpleAlgorithm):
    id = "sideway_short"
    family = "Sideway (đi ngang)"
    description = "Chỉ đánh khi thị trường đi ngang (ER thấp): RSI quá mua và giá trên dải Bollinger trên → bán. Chốt lời / cắt lỗ theo ATR."

    def __algorithm__(self):
        e = self.frame(p('entry_tf', '5m',
              choices=('1m', '5m', '15m', '1h'),
              label="Khung điểm vào",
              help="Khung nến tính RSI và dải Bollinger."))
        rsi = self.feat.rsi(e.pv_close, timeperiod=p('rsi_n', 14,
              lo=2,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ RSI",
              help="Chu kỳ RSI (Wilder)."))
        rsi_hi = p('rsi_hi', 75,
              lo=55.0,
              hi=90.0,
              step=1.0,
              label="Ngưỡng RSI quá mua",
              help="Ngưỡng RSI kích hoạt bắt hồi.",
              grid=(70, 75, 80))
        bb_n = p('bb_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ Bollinger",
              help="Chu kỳ đường giữa của dải Bollinger.")
        bb_k = p('bb_k', 2.0,
              lo=1.0,
              hi=4.0,
              step=0.1,
              unit="σ",
              label="Độ rộng Bollinger (k)",
              help="Dải cách đường giữa k độ lệch chuẩn.")
        bb_upper, bb_mid, bb_lower = self.feat.bbands(e.pv_close, timeperiod=bb_n, nbdevup=bb_k, nbdevdn=bb_k)
        r = self.frame(p('regime_tf', '1h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung regime",
              help="Khung đo mức đi ngang bằng Efficiency Ratio."))
        er = self.feat.er(r.pv_close, timeperiod=p('er_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ ER",
              help="Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."))
        er_max = p('er_max', 0.3,
              lo=0.1,
              hi=0.6,
              step=0.05,
              label="Ngưỡng ER tối đa",
              help="Chỉ bắt hồi khi ER thấp hơn mức này (thị trường đi ngang).",
              grid=(0.2, 0.3))
        p('stop_loss_rate', 1.5, grid=(1.0, 1.5, 2.5))
        p('take_profit_rate', 1.5, grid=(0.75, 1.0, 1.5, 2.5))
        p('timeout', 1440, grid=(240, 1440))
        self.set_positions((rsi > rsi_hi) & (e.pv_close > bb_upper) & (er < er_max), position=-1)
