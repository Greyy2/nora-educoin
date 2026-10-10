"""Live qua Nautilus (P15 phase 6): CHƯA có TradingNode -> chỉ báo cáo môi trường + kiểm tra khoá OKX (chữ ký thật, không đặt lệnh).

Khoá chỉ đọc từ biến môi trường / ~/.config/nora/okx.env; không bao giờ trả ra ngoài (kể cả dạng che) và không in log.
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests

CONFIG_ENV_PATH = os.path.expanduser("~/.config/nora/okx.env")
OKX_REST = "https://www.okx.com"
NOT_READY = {"code": "NOT_READY", "message": "Live đang chuyển sang Nautilus TradingNode"}


def load_okx_credentials() -> Dict[str, Any]:
    """Nạp API key, secret, passphrase, cờ demo từ biến môi trường rồi ghi đè bằng file config (nếu có)."""
    creds = {"key": os.environ.get("NORA_OKX_KEY", ""), "secret": os.environ.get("NORA_OKX_SECRET", ""),
             "passphrase": os.environ.get("NORA_OKX_PASSPHRASE", ""), "is_demo": bool(int(os.environ.get("NORA_OKX_DEMO", "1")))}
    names = {"NORA_OKX_KEY": "key", "NORA_OKX_SECRET": "secret", "NORA_OKX_PASSPHRASE": "passphrase"}
    if os.path.isfile(CONFIG_ENV_PATH):
        with open(CONFIG_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k in names:
                    creds[names[k]] = v
                elif k == "NORA_OKX_DEMO":
                    creds["is_demo"] = (v == "1")
    return creds


def _has_keys(creds: Dict[str, Any]) -> bool:
    return bool(creds["key"] and creds["secret"] and creds["passphrase"])


def test_okx_api_connection(mode: str = "demo") -> Dict[str, Any]:
    """Xác thực khoá bằng endpoint RIÊNG TƯ có chữ ký (GET /api/v5/account/balance, chỉ đọc). Chưa cấu hình khoá -> báo thẳng, không gọi mạng."""
    creds = load_okx_credentials()
    is_demo = mode.lower() in ("demo", "testnet") or creds["is_demo"]
    label = "demo" if is_demo else "live"
    if not _has_keys(creds):
        return {"ok": False, "mode": label, "has_credentials": False, "message": "Chưa cấu hình API Key/Secret/Passphrase tại ~/.config/nora/okx.env"}
    path = "/api/v5/account/balance"
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    sign = base64.b64encode(hmac.new(creds["secret"].encode(), f"{ts}GET{path}".encode(), hashlib.sha256).digest()).decode()
    headers = {"OK-ACCESS-KEY": creds["key"], "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": creds["passphrase"]}
    if is_demo:
        headers["x-simulated-trading"] = "1"
    try:
        resp = requests.get(OKX_REST + path, headers=headers, timeout=8)
        body = resp.json()
    except Exception as e:
        return {"ok": False, "mode": label, "has_credentials": True, "message": f"Lỗi kết nối tới OKX API: {type(e).__name__}"}
    if resp.status_code == 200 and str(body.get("code")) == "0":
        return {"ok": True, "mode": label, "has_credentials": True, "environment": "OKX Demo" if is_demo else "OKX Live",
                "message": f"Khoá OKX hợp lệ (xác thực chữ ký thành công, {'Demo' if is_demo else 'Thật'})."}
    return {"ok": False, "mode": label, "has_credentials": True, "status_code": resp.status_code, "okx_code": body.get("code"),
            "message": f"OKX từ chối khoá: {body.get('msg') or resp.status_code}"}


def get_environments_status() -> Dict[str, Any]:
    """Trạng thái từng môi trường. Chỉ backtest sẵn sàng; paper/testnet/live chưa có TradingNode -> ready False (+ not_ready); `configured` = đã có khoá OKX."""
    creds = load_okx_credentials()
    has_keys = _has_keys(creds)
    return {
        "backtest": {"name": "Backtest", "ready": True, "engine": "NautilusTrader BacktestEngine", "data_source": "Nautilus ParquetDataCatalog (data/market/okx/catalog)",
                     "description": "Chạy khớp lệnh mô phỏng với dữ liệu lịch sử đã crawl sẵn."},
        "paper": {"name": "Paper Trading", "ready": False, "not_ready": dict(NOT_READY), "engine": "NautilusTrader (chưa triển khai)",
                  "description": "Giao dịch realtime mô phỏng — chưa hỗ trợ."},
        "testnet": {"name": "Testnet / Demo", "ready": False, "not_ready": dict(NOT_READY), "configured": has_keys,
                    "engine": "NautilusTrader OKX Adapter (chưa triển khai)", "description": "Đặt lệnh trên OKX Demo Trading — chưa hỗ trợ."},
        "live": {"name": "Live Real Trading", "ready": False, "not_ready": dict(NOT_READY), "configured": has_keys, "demo_lock": creds["is_demo"],
                 "engine": "NautilusTrader OKX Adapter (chưa triển khai)", "description": "Đặt lệnh trên tài khoản thật OKX — chưa hỗ trợ."},
    }
