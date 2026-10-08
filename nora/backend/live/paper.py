"""Hồ sơ môi trường PAPER (mode "paper"): chỉ dữ liệu thị trường CÔNG KHAI của sàn (không khoá, không đặt lệnh); khớp lệnh mô phỏng bằng KernelPaperBook (core/backtest.py).
Bot / run_job dùng chung ở live/live.py; hồ sơ khác: live/testnet.py (mode "demo"), live/live.py (mode "live")."""
from backend.live import live as lv


def _paper_adapter(venue: str):
    if venue == "okx":
        return lv.OkxAdapter(None, demo=False), None
    if venue == "binance":
        return lv.BinanceAdapter(None, lv.MAINNET_URL), None
    lv.unsupported_venue(venue)


PROFILE = lv.Profile("paper", _paper_adapter)
