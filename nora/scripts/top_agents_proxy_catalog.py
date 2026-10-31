"""Top Agent OKX Proxy — catalog tập trung 3 chiến lược proxy nghiên cứu trích xuất từ copy-trade OKX.

ĐÂY LÀ SCRIPT / FIXTURE NGHIÊN CỨU NGOÀI CORE:
- Không đặt trong nora/coin/data/alpha/strategies/ vì strategies/ là strategy engine nạp chiến lược hệ thống chính thức.
- Chỉ có tham số thoát lệnh (Exit Structure) trích xuất từ nghiên cứu OKX copy-trade.
- Dữ liệu OKX gốc hoàn toàn không có logic vào lệnh (Entry Signal). Phần entry bên dưới là giả định proxy.
- Gắn nhãn [DRAFT_UNVERIFIED] và [PROXY_EXIT_FIT], dùng cho mục đích đối sánh nghiên cứu (RESEARCH_ONLY_NO_DECISION).
"""

CODE_01PP = """class ProxyExitFit01pp(SimpleAlgorithm):
    \"\"\"[DRAFT_UNVERIFIED] [PROXY_EXIT_FIT] OKX Top Agent 01pp.
    CẢNH BÁO QUAN TRỌNG:
    - File này chỉ mô phỏng tham số thoát lệnh (Exit Structure) trích xuất từ nghiên cứu OKX copy-trade.
    - Dữ liệu OKX gốc HOÀN TOÀN KHÔNG CÓ LOGIC VÀO LỆNH (Entry Signal). Phần entry bên dưới là GIẢ ĐỊNH PROXY.
    - Không dùng để so sánh hiệu suất hay xếp hạng với bot OKX thật.
    \"\"\"
    timeframe = "1h"
    period_fast = 10  # [GIẢ ĐỊNH PROXY]
    period_slow = 30  # [GIẢ ĐỊNH PROXY]

    # Tham số vị thế & quản lý rủi ro
    sizing = "risk"                      # [TƯỜNG MINH SIZING RỦI RO]
    exit_unit = "pct"                    # [TỪ OKX]: Công thức TP tính theo % giá
    take_profit_rate = 0.931             # [TỪ OKX]: TP = 0.931% giá (formula_summary)
    stop_loss_rate = 3.0                 # [GIẢ ĐỊNH PROXY]: OKX dùng SL = (46.15 + 1.009·ATR1h%·lev)% ROI ký quỹ
    leverage = 15                        # [TỪ OKX]: Median levMed = 15.0 (Cảnh báo: Master Risk kẹp trần <= 10x ở runtime)
    cooldown = 60                        # [GIẢ ĐỊNH PROXY]: 1 nến 1h
    risk_per_trade_pct = 0.25            # [CHUẨN NORA MASTER RISK]: Tối đa 0.25%/lệnh

    def __algorithm__(self):
        close = self.data.pv_close
        fast = self.feat.sma(close, self.period_fast)
        slow = self.feat.sma(close, self.period_slow)
        # [CẢNH BÁO / GIẢ ĐỊNH PROXY]: Logic vào lệnh không có trong dữ liệu OKX
        self.set_positions(fast > slow, position=1)
        self.set_positions(fast < slow, position=0)
"""

CODE_AURORA = """class ProxyExitFitAuroraxwt(SimpleAlgorithm):
    \"\"\"[DRAFT_UNVERIFIED] [PROXY_EXIT_FIT] OKX Top Agent Auroraxwt.
    CẢNH BÁO QUAN TRỌNG:
    - File này chỉ mô phỏng tham số thoát lệnh (Exit Structure) trích xuất từ nghiên cứu OKX copy-trade.
    - Dữ liệu OKX gốc HOÀN TOÀN KHÔNG CÓ LOGIC VÀO LỆNH (Entry Signal). Phần entry bên dưới là GIẢ ĐỊNH PROXY.
    - Không dùng để so sánh hiệu suất hay xếp hạng với bot OKX thật.
    \"\"\"
    timeframe = "1h"
    rsi_period = 14  # [GIẢ ĐỊNH PROXY]

    # Tham số vị thế & quản lý rủi ro
    sizing = "risk"                      # [TƯỜNG MINH SIZING RỦI RO]
    exit_unit = "pct"                    # [TỪ OKX]: Công thức SL tính theo % giá
    stop_loss_rate = 0.218               # [TỪ OKX]: SL = 0.218% giá (formula_summary)
    take_profit_rate = 2.0               # [GIẢ ĐỊNH PROXY]: TP kỳ vọng
    leverage = 20                        # [TỪ OKX]: Median levMed = 20.0 (Cảnh báo: Master Risk kẹp trần <= 10x ở runtime)
    cooldown = 60                        # [GIẢ ĐỊNH PROXY]: 1 nến 1h
    risk_per_trade_pct = 0.25            # [CHUẨN NORA MASTER RISK]: Tối đa 0.25%/lệnh

    def __algorithm__(self):
        close = self.data.pv_close
        rsi_val = self.feat.rsi(close, self.rsi_period)
        # [CẢNH BÁO / GIẢ ĐỊNH PROXY]: Logic vào lệnh không có trong dữ liệu OKX
        self.set_positions(rsi_val < 30, position=1)
        self.set_positions(rsi_val > 70, position=0)
"""

CODE_DAHLIA = """class ProxyExitFitDarkWoodDahlia(SimpleAlgorithm):
    \"\"\"[DRAFT_UNVERIFIED] [PROXY_EXIT_FIT] OKX Top Agent Dark Wood Dahlia.
    CẢNH BÁO QUAN TRỌNG:
    - File này chỉ mô phỏng tham số thoát lệnh (Exit Structure) trích xuất từ nghiên cứu OKX copy-trade.
    - Dữ liệu OKX gốc HOÀN TOÀN KHÔNG CÓ LOGIC VÀO LỆNH (Entry Signal). Phần entry bên dưới là GIẢ ĐỊNH PROXY.
    - Không dùng để so sánh hiệu suất hay xếp hạng với bot OKX thật.
    \"\"\"
    timeframe = "15m"
    bb_period = 20  # [GIẢ ĐỊNH PROXY]
    bb_dev = 2.0    # [GIẢ ĐỊNH PROXY]

    # Tham số vị thế & quản lý rủi ro
    sizing = "risk"                      # [TƯỜNG MINH SIZING RỦI RO]
    exit_unit = "pct"                    # [TỪ OKX]: Công thức TP tính theo % giá
    take_profit_rate = 3.159             # [TỪ OKX]: TP = 3.159% giá (formula_summary)
    stop_loss_rate = 2.0                 # [GIẢ ĐỊNH PROXY]: SL phòng hộ
    leverage = 10                        # [TỪ OKX]: Median levMed = 10.0
    cooldown = 15                        # [GIẢ ĐỊNH PROXY]: 1 nến 15m
    risk_per_trade_pct = 0.25            # [CHUẨN NORA MASTER RISK]: Tối đa 0.25%/lệnh

    def __algorithm__(self):
        close = self.data.pv_close
        mid = self.feat.sma(close, self.bb_period)
        dev = self.feat.stddev(close, self.bb_period, self.bb_dev)
        # [CẢNH BÁO / GIẢ ĐỊNH PROXY]: Logic vào lệnh không có trong dữ liệu OKX
        self.set_positions(close < (mid - dev), position=1)
        self.set_positions(close > mid, position=0)
"""

TOP_AGENT_PROXY_CODES = {
    "okx_01pp": CODE_01PP,
    "okx_auroraxwt": CODE_AURORA,
    "okx_dark_wood_dahlia": CODE_DAHLIA,
}
