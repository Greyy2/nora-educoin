"""KEMA (theo xu hướng) — kênh Keltner EMA ± k·ATR: vào khi giá đóng cửa phá kênh, thoát khi cắt ngược kênh.

Nguồn gốc của chiến lược hệ thống `kema` (dạng đã biên dịch: cây AST trong sổ chiến lược, sinh lại từ file này, không sửa tay).
"""
STRATEGY = {
    "id": "kema",
    "name": "KEMA",
    "kind": "Theo xu hướng",
    "description": "Theo xu hướng bằng kênh Keltner: vào khi giá phá kênh, thoát khi giá cắt ngược kênh. Cả hai chiều = đảo chiều liên tục.",
    "idea": "Theo xu hướng: giá đóng cửa phá ra ngoài kênh EMA ± k·ATR báo hiệu xu hướng mới có quán tính; đi theo hướng phá kênh, thoát khi giá cắt ngược kênh. Lãi đến từ ít lệnh thắng lớn khi xu hướng chạy dài.",
    "order": 0,
}


class KemaLong(SimpleAlgorithm):
    id = "kema_long"
    family = "KEMA (theo xu hướng)"
    description = "Giá đóng cửa cắt LÊN dải trên kênh Keltner (EMA + k × ATR) → mua. Thoát khi giá cắt XUỐNG dải dưới (đảo chiều) hoặc chạm SL."
    position = {'atr_frame': '4h'}

    def __algorithm__(self):
        tf = self.frame(p('signal_tf', '4h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung tín hiệu",
              help="Khung nến tính kênh Keltner và xét điểm cắt."))
        close = tf.pv_close
        high = tf.pv_high
        low = tf.pv_low
        ema = self.feat.ema(close, timeperiod=p('ema_n', 30,
              lo=5,
              hi=200,
              step=1,
              unit="nến",
              label="Chu kỳ EMA (đường giữa)",
              help="EMA đường giữa của kênh Keltner.",
              grid=(20, 30, 50)))
        atr = self.feat.atr(high, low, close, timeperiod=p('atr_n', 14,
              lo=5,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ ATR của kênh",
              help="ATR (Wilder) đo độ rộng kênh."))
        k_up = p('k_up', 2.0,
              lo=0.5,
              hi=5.0,
              step=0.1,
              unit="× ATR",
              label="Hệ số dải trên",
              help="Dải trên = EMA + hệ số × ATR.",
              grid=(1.5, 2.0, 2.5))
        k_dn = p('k_dn', 2.0,
              lo=0.5,
              hi=5.0,
              step=0.1,
              unit="× ATR",
              label="Hệ số dải dưới",
              help="Dải dưới = EMA − hệ số × ATR.",
              grid=(1.5, 2.0, 2.5))
        kc_up = ema + atr * k_up
        kc_dn = ema - atr * k_dn
        p('stop_loss_rate', 3.0, grid=(2.0, 3.0, 4.0))
        p('atr_frame', '4h')
        self.set_positions(self.op.crossed_above(close, kc_up), position=1)     # vào: giá cắt LÊN dải trên
        self.set_positions(self.op.crossed_below(close, kc_dn), position=0)     # thoát: giá cắt XUỐNG dải dưới


class KemaShort(SimpleAlgorithm):
    id = "kema_short"
    family = "KEMA (theo xu hướng)"
    description = "Giá đóng cửa cắt XUỐNG dải dưới kênh Keltner (EMA − k × ATR) → bán. Thoát khi giá cắt LÊN dải trên (đảo chiều) hoặc chạm SL."
    position = {'atr_frame': '4h'}

    def __algorithm__(self):
        tf = self.frame(p('signal_tf', '4h',
              choices=('15m', '1h', '4h', '24h'),
              label="Khung tín hiệu",
              help="Khung nến tính kênh Keltner và xét điểm cắt."))
        close = tf.pv_close
        high = tf.pv_high
        low = tf.pv_low
        ema = self.feat.ema(close, timeperiod=p('ema_n', 30,
              lo=5,
              hi=200,
              step=1,
              unit="nến",
              label="Chu kỳ EMA (đường giữa)",
              help="EMA đường giữa của kênh Keltner.",
              grid=(20, 30, 50)))
        atr = self.feat.atr(high, low, close, timeperiod=p('atr_n', 14,
              lo=5,
              hi=50,
              step=1,
              unit="nến",
              label="Chu kỳ ATR của kênh",
              help="ATR (Wilder) đo độ rộng kênh."))
        k_up = p('k_up', 2.0,
              lo=0.5,
              hi=5.0,
              step=0.1,
              unit="× ATR",
              label="Hệ số dải trên",
              help="Dải trên = EMA + hệ số × ATR.",
              grid=(1.5, 2.0, 2.5))
        k_dn = p('k_dn', 2.0,
              lo=0.5,
              hi=5.0,
              step=0.1,
              unit="× ATR",
              label="Hệ số dải dưới",
              help="Dải dưới = EMA − hệ số × ATR.",
              grid=(1.5, 2.0, 2.5))
        kc_up = ema + atr * k_up
        kc_dn = ema - atr * k_dn
        p('stop_loss_rate', 3.0, grid=(2.0, 3.0, 4.0))
        p('atr_frame', '4h')
        self.set_positions(self.op.crossed_below(close, kc_dn), position=-1)    # vào: giá cắt XUỐNG dải dưới
        self.set_positions(self.op.crossed_above(close, kc_up), position=0)     # thoát: giá cắt LÊN dải trên
