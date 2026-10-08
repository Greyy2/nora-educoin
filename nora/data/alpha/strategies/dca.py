"""DCA (bắt hồi + dồn có điều kiện) — RSI cực trị và giá ngoài dải Bollinger khi thị trường đi ngang; dồn thêm tầng theo bước ATR CHỈ khi vẫn đi ngang.

Dạng đã biên dịch (cây AST + cổng dồn tầng của sổ chiến lược) sinh lại từ file này, không sửa tay.
"""
STRATEGY = {
    "id": "dca",
    "name": "DCA",
    "kind": "Bắt hồi + dồn lệnh có điều kiện",
    "description": "Bắt hồi ở vùng quá bán/quá mua khi đi ngang; chỉ dồn thêm tầng khi thị trường vẫn đi ngang (ER, ADX thấp), ngừng dồn khi bắt đầu có xu hướng. Cắt lỗ cứng cho cả rổ.",
    "idea": "Bắt hồi ở vùng quá bán/quá mua khi đi ngang, dồn thêm tầng theo bước ATR chỉ khi thị trường vẫn đi ngang; rủi ro cả rổ cố định bằng cắt lỗ từ giá trung bình.",
    "order": 2,
}


class DcaLong(SimpleAlgorithm):
    id = "dca_long"
    family = "DCA (bắt hồi + dồn có điều kiện)"
    description = "RSI quá bán và giá dưới dải Bollinger dưới khi thị trường đi ngang → mua; giá giảm tiếp thì dồn thêm tầng theo bước ATR CHỈ khi vẫn đi ngang (ER, ADX thấp). Chốt lời và cắt lỗ cả rổ tính từ giá trung bình."
    position = {'exit_unit': 'atr'}

    def __algorithm__(self):
        e = self.frame(p('entry_tf', '1h',
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
        rsi_lo = p('rsi_lo', 30,
              lo=10.0,
              hi=45.0,
              step=1.0,
              label="RSI quá bán",
              help="Ngưỡng RSI kích hoạt lệnh đầu.",
              grid=(25, 30, 35))
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
        r = self.frame(p('regime_tf', '4h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung chế độ thị trường",
              help="Khung đo đi ngang (ER) và độ mạnh xu hướng (ADX)."))
        er = self.feat.er(r.pv_close, timeperiod=p('er_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ ER",
              help="Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."))
        er_max = p('er_max', 0.35,
              lo=0.1,
              hi=0.7,
              step=0.05,
              label="Vào lệnh khi ER dưới",
              help="Chỉ mở lệnh đầu khi thị trường đi ngang.")
        adx = self.feat.adx(r.pv_high, r.pv_low, r.pv_close, timeperiod=p('adx_n', 14,
              lo=5,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ ADX",
              help="Chu kỳ ADX đo độ mạnh xu hướng."))
        # dồn tầng DCA: bước theo ATR, số tầng, hệ số khối lượng; cắt lỗ/chốt lời tính từ giá trung bình của rổ
        p('dca_step_pct', 1.0,
              lo=0.25,
              hi=4.0,
              step=0.25,
              unit="× ATR",
              label="Bước dồn lệnh",
              help="Giá đi ngược bấy nhiêu × ATR so với lần khớp trước thì dồn thêm một tầng.",
              group="dca",
              grid=(0.5, 1.0, 1.5))
        p('dca_max_layers', 3,
              lo=1,
              hi=6,
              step=1,
              unit="tầng",
              label="Số tầng dồn tối đa",
              help="Số lần dồn thêm sau lệnh đầu.",
              group="dca",
              grid=(2, 3, 4))
        p('dca_size_multiplier', 1.5,
              lo=1.0,
              hi=2.5,
              step=0.1,
              unit="×",
              label="Hệ số khối lượng tầng sau",
              help="Mỗi tầng sau lớn gấp bấy nhiêu lần tầng trước.",
              group="dca",
              grid=(1.0, 1.5, 2.0))
        p('stop_loss_rate', 6.0, grid=(4.0, 6.0, 8.0))
        p('take_profit_rate', 1.5, grid=(1.0, 1.5, 2.5))
        p('timeout', 4320)
        # cổng cho phép dồn tầng: chỉ khi thị trường VẪN đi ngang (ER, ADX thấp) và RSI còn cực trị
        gate_er_max = p('gate_er_max', 0.4,
              lo=0.1,
              hi=0.8,
              step=0.05,
              label="Chỉ dồn khi ER dưới",
              help="Tầng DCA chỉ khớp khi ER còn thấp; ER tăng (bắt đầu có xu hướng) thì ngừng dồn.",
              grid=(0.3, 0.4, 0.5))
        gate_adx_max = p('gate_adx_max', 25.0,
              lo=10.0,
              hi=50.0,
              step=1.0,
              label="Chỉ dồn khi ADX dưới",
              help="Tầng DCA chỉ khớp khi chưa có xu hướng mạnh.")
        gate_rsi = p('gate_rsi', 101.0,
              lo=10.0,
              hi=101.0,
              step=1.0,
              label="Chỉ dồn khi RSI còn dưới",
              help="Tầng DCA chỉ khớp khi RSI vẫn quá bán (giá còn bị bán quá đà, chưa đảo chiều thành xu hướng giảm); 101 = không lọc.")
        self.set_positions((rsi < rsi_lo) & (e.pv_close < bb_lower) & (er < er_max), position=1)
        self.set_dca_gate((er < gate_er_max) & (adx < gate_adx_max) & (rsi < gate_rsi))


class DcaShort(SimpleAlgorithm):
    id = "dca_short"
    family = "DCA (bắt hồi + dồn có điều kiện)"
    description = "RSI quá mua và giá trên dải Bollinger trên khi thị trường đi ngang → bán; giá tăng tiếp thì dồn thêm tầng theo bước ATR CHỈ khi vẫn đi ngang (ER, ADX thấp). Chốt lời và cắt lỗ cả rổ tính từ giá trung bình."
    position = {'exit_unit': 'atr'}

    def __algorithm__(self):
        e = self.frame(p('entry_tf', '1h',
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
        rsi_hi = p('rsi_hi', 70,
              lo=55.0,
              hi=90.0,
              step=1.0,
              label="RSI quá mua",
              help="Ngưỡng RSI kích hoạt lệnh đầu.",
              grid=(65, 70, 75))
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
        r = self.frame(p('regime_tf', '4h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung chế độ thị trường",
              help="Khung đo đi ngang (ER) và độ mạnh xu hướng (ADX)."))
        er = self.feat.er(r.pv_close, timeperiod=p('er_n', 20,
              lo=5,
              hi=100,
              step=1,
              unit="nến",
              label="Chu kỳ ER",
              help="Chu kỳ Efficiency Ratio (1 = xu hướng, 0 = đi ngang)."))
        er_max = p('er_max', 0.35,
              lo=0.1,
              hi=0.7,
              step=0.05,
              label="Vào lệnh khi ER dưới",
              help="Chỉ mở lệnh đầu khi thị trường đi ngang.")
        adx = self.feat.adx(r.pv_high, r.pv_low, r.pv_close, timeperiod=p('adx_n', 14,
              lo=5,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ ADX",
              help="Chu kỳ ADX đo độ mạnh xu hướng."))
        # dồn tầng DCA: bước theo ATR, số tầng, hệ số khối lượng; cắt lỗ/chốt lời tính từ giá trung bình của rổ
        p('dca_step_pct', 1.0,
              lo=0.25,
              hi=4.0,
              step=0.25,
              unit="× ATR",
              label="Bước dồn lệnh",
              help="Giá đi ngược bấy nhiêu × ATR so với lần khớp trước thì dồn thêm một tầng.",
              group="dca",
              grid=(0.5, 1.0, 1.5))
        p('dca_max_layers', 3,
              lo=1,
              hi=6,
              step=1,
              unit="tầng",
              label="Số tầng dồn tối đa",
              help="Số lần dồn thêm sau lệnh đầu.",
              group="dca",
              grid=(2, 3, 4))
        p('dca_size_multiplier', 1.5,
              lo=1.0,
              hi=2.5,
              step=0.1,
              unit="×",
              label="Hệ số khối lượng tầng sau",
              help="Mỗi tầng sau lớn gấp bấy nhiêu lần tầng trước.",
              group="dca",
              grid=(1.0, 1.5, 2.0))
        p('stop_loss_rate', 6.0, grid=(4.0, 6.0, 8.0))
        p('take_profit_rate', 1.5, grid=(1.0, 1.5, 2.5))
        p('timeout', 4320)
        # cổng cho phép dồn tầng: chỉ khi thị trường VẪN đi ngang (ER, ADX thấp) và RSI còn cực trị
        gate_er_max = p('gate_er_max', 0.4,
              lo=0.1,
              hi=0.8,
              step=0.05,
              label="Chỉ dồn khi ER dưới",
              help="Tầng DCA chỉ khớp khi ER còn thấp; ER tăng (bắt đầu có xu hướng) thì ngừng dồn.",
              grid=(0.3, 0.4, 0.5))
        gate_adx_max = p('gate_adx_max', 25.0,
              lo=10.0,
              hi=50.0,
              step=1.0,
              label="Chỉ dồn khi ADX dưới",
              help="Tầng DCA chỉ khớp khi chưa có xu hướng mạnh.")
        gate_rsi = p('gate_rsi', -1.0,
              lo=-1.0,
              hi=90.0,
              step=1.0,
              label="Chỉ dồn khi RSI còn trên",
              help="Tầng DCA chỉ khớp khi RSI vẫn quá mua; −1 = không lọc.")
        self.set_positions((rsi > rsi_hi) & (e.pv_close > bb_upper) & (er < er_max), position=-1)
        self.set_dca_gate((er < gate_er_max) & (adx < gate_adx_max) & (rsi > gate_rsi))
