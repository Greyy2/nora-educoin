"""Quản lý phiên bản và cập nhật Nautilus Trader.
Theo dõi version hiện hành và kiểm tra bản phát hành mới trên PyPI / GitHub.
"""
import json
import urllib.request
from typing import Dict, Any

try:
    import nautilus_trader
    NAUTILUS_VERSION = nautilus_trader.__version__
    NAUTILUS_AVAILABLE = True
except ImportError:
    NAUTILUS_VERSION = "not_installed"
    NAUTILUS_AVAILABLE = False


ENGINE_NAME = "nautilus_trader"   # tên engine công bố cho UI / health (nơi DUY NHẤT ngoài import)


def get_version_info() -> Dict[str, Any]:
    """Trả thông tin phiên bản NautilusTrader hiện tại và đường dẫn tài liệu chuẩn."""
    return {
        "installed": NAUTILUS_AVAILABLE,
        "version": NAUTILUS_VERSION,
        "docs_url": "https://nautilustrader.io/docs/",
        "github_url": "https://github.com/nautechsystems/nautilus_trader",
        "pypi_url": "https://pypi.org/project/nautilus-trader/",
    }


def check_for_updates() -> Dict[str, Any]:
    """Kiểm tra xem có bản phát hành NautilusTrader mới hơn trên PyPI không."""
    info = get_version_info()
    if not NAUTILUS_AVAILABLE:
        return {**info, "has_update": True, "latest_version": "unknown", "message": "Chưa cài đặt nautilus-trader"}
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/nautilus-trader/json",
            headers={"User-Agent": "Nora-Backtest-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("info", {}).get("version", NAUTILUS_VERSION)
            has_update = latest != NAUTILUS_VERSION
            return {
                **info,
                "latest_version": latest,
                "has_update": has_update,
                "message": f"Đã có phiên bản mới: {latest}" if has_update else "Đang dùng phiên bản mới nhất."
            }
    except Exception as e:
        return {
            **info,
            "has_update": False,
            "latest_version": NAUTILUS_VERSION,
            "error": str(e),
            "message": "Không kết nối được PyPI để kiểm tra cập nhật."
        }
