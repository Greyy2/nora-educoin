"""REST Binance USD-M Futures (testnet / mainnet) — chỉ thư viện chuẩn. Ký HMAC-SHA256; bộ lọc giá/khối lượng (E9-S2).

Endpoint công khai (klines, exchangeInfo) dùng được không cần khoá (chế độ paper đọc dữ liệu thị trường thật). Endpoint riêng cần khoá.
Lỗi sàn -> ExchangeError (thông điệp đã redact)."""
import hashlib
import hmac
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from backend.live.secrets import redact

TESTNET_URL = "https://testnet.binancefuture.com"
MAINNET_URL = "https://fapi.binance.com"
INTERVAL = {"15m": "15m", "1h": "1h", "4h": "4h", "24h": "1d"}   # khung engine -> khoảng nến của sàn


class ExchangeError(RuntimeError):
    pass


class BinanceFutures:
    def __init__(self, base_url: str = TESTNET_URL, keys: Optional[Tuple[str, str]] = None, timeout: float = 15.0):
        self.base, self.keys, self.timeout = base_url.rstrip("/"), keys, timeout

    def _req(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
        q = dict(params or {})
        headers = {}
        if signed:
            if not self.keys:
                raise ExchangeError("cần khoá API cho endpoint riêng")
            q["timestamp"] = int(time.time() * 1000)
            q.setdefault("recvWindow", 5000)
            body = urllib.parse.urlencode(q)
            q["signature"] = hmac.new(self.keys[1].encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self.keys[0]
        url = f"{self.base}{path}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise ExchangeError(redact(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}", self.keys)) from None
        except urllib.error.URLError as e:
            raise ExchangeError(redact(f"{method} {path} -> {e.reason}", self.keys)) from None

    # ── công khai ──
    def exchange_info(self) -> Dict[str, Any]:
        return self._req("GET", "/fapi/v1/exchangeInfo")

    def klines(self, symbol: str, frame: str, limit: int = 1000) -> List[List[Any]]:
        return self._req("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": INTERVAL[frame], "limit": limit})

    def funding(self, symbol: str, since: int) -> List[Dict[str, Any]]:
        return self._req("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "startTime": int(since), "limit": 100})

    # ── riêng ──
    def account(self) -> Dict[str, Any]:
        return self._req("GET", "/fapi/v2/account", signed=True)

    def positions(self) -> List[Dict[str, Any]]:
        return self._req("GET", "/fapi/v2/positionRisk", signed=True)

    def open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._req("GET", "/fapi/v1/openOrders", {"symbol": symbol} if symbol else {}, signed=True)

    def set_margin_isolated(self, symbol: str) -> None:
        try:
            self._req("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"}, signed=True)
        except ExchangeError as e:
            if "-4046" not in str(e):     # "No need to change margin type"
                raise

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self._req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)}, signed=True)

    def order(self, **p) -> Dict[str, Any]:
        return self._req("POST", "/fapi/v1/order", p, signed=True)

    def cancel_all(self, symbol: str) -> None:
        self._req("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol}, signed=True)


# ── bộ lọc sàn ──
class Filters:
    """tickSize / stepSize / minNotional của một mã (exchangeInfo)."""

    def __init__(self, tick: float, step: float, min_qty: float, min_notional: float):
        self.tick, self.step, self.min_qty, self.min_notional = tick, step, min_qty, min_notional

    @classmethod
    def from_info(cls, info: Dict[str, Any], symbol: str) -> "Filters":
        s = next((x for x in info["symbols"] if x["symbol"] == symbol), None)
        if s is None:
            raise ExchangeError(f"sàn không có {symbol}")
        f = {x["filterType"]: x for x in s["filters"]}
        return cls(float(f["PRICE_FILTER"]["tickSize"]), float(f["LOT_SIZE"]["stepSize"]), float(f["LOT_SIZE"]["minQty"]),
                   float((f.get("MIN_NOTIONAL") or {}).get("notional", 0.0)))

    @staticmethod
    def _floor(x: float, step: float) -> float:
        n = math.floor(x / step + 1e-9)
        dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return round(n * step, dec)

    def qty(self, q: float) -> float:
        return self._floor(q, self.step)

    def price(self, p: float) -> float:
        return self._floor(p, self.tick)

    def check(self, qty: float, price: float) -> Optional[str]:
        """None nếu gửi được; ngược lại lý do (E9-S2: bỏ lệnh dưới minQty / minNotional, ghi log)."""
        if qty < self.min_qty:
            return f"khối lượng {qty} < minQty {self.min_qty}"
        if qty * price < self.min_notional:
            return f"danh nghĩa {qty * price:.2f} < minNotional {self.min_notional}"
        return None
