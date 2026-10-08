"""Hồ sơ môi trường TESTNET (mode "demo"): OKX Demo Trading (khoá demo bắt buộc, từ chối khoá thật) và Binance testnet (khoá bắt buộc). Vốn ảo, lệnh THẬT trên sàn thử nghiệm.
Bot / run_job dùng chung ở live/live.py; hồ sơ khác: live/paper.py (mode "paper"), live/live.py (mode "live")."""
from backend.live import live as lv


def _demo_adapter(venue: str):
    if venue == "okx":
        keys, demo = lv.require_okx()
        if not demo:
            raise SystemExit("mode demo nhưng khoá là tài khoản thật (NORA_OKX_DEMO=0) — dùng khoá Demo Trading")
        return lv.OkxAdapter(keys, demo=demo), keys
    if venue == "binance":
        keys = lv.load_keys()
        if not keys:
            raise SystemExit("Binance testnet cần khoá (NORA_BINANCE_TESTNET_KEY/SECRET)")
        return lv.BinanceAdapter(keys, lv.TESTNET_URL), keys
    lv.unsupported_venue(venue)


PROFILE = lv.Profile("demo", _demo_adapter)
