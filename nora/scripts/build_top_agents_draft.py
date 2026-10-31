import os
import json
import sys

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code

# Build / compile test for top agent proxies (in scripts, out of core)

# 1. 01pp
code_01pp = """class ProxyExitFit01pp(SimpleAlgorithm):
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

# 2. auroraxwt
code_aurora = """class ProxyExitFitAuroraxwt(SimpleAlgorithm):
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

# 3. dark_wood_dahlia
code_dark_wood = """class ProxyExitFitDarkWoodDahlia(SimpleAlgorithm):
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

items = [
    ("okx_01pp.py", code_01pp),
    ("okx_auroraxwt.py", code_aurora),
    ("okx_dark_wood_dahlia.py", code_dark_wood),
]

for fname, code in items:
    prog = compile_code(code)
    print(f"Validated & compiled {fname}: hash={prog.code_hash}")
