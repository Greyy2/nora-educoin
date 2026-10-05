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


class NotPermitted(ExchangeError):
    """Khoá API không có quyền giao dịch mã / thị trường này (vd. OKX 50123: mã không nằm trong danh sách Crypto của khoá)."""


class BinanceFutures:
    def __init__(self, base_url: str = TESTNET_URL, keys: Optional[Tuple[str, str]] = None, timeout: float = 15.0):
        self.base, self.keys, self.timeout = base_url.rstrip("/"), keys, timeout

    def _req(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
        q = dict(params or {})
        headers = {"User-Agent": "nora-bot/1.0"}
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

    def qty_close(self, q: float) -> float:
        """Khối lượng cho lệnh ĐÓNG (reduce-only: SL/TP/trailing): làm tròn tới bước GẦN NHẤT — làm tròn xuống có thể để lại một bước lẻ
        (sai số dấu phẩy động), vị thế còn sót không bao giờ đóng hết; sàn tự giới hạn lệnh reduce-only theo vị thế thật."""
        return self._floor(q + self.step / 2.0, self.step)

    def price(self, p: float) -> float:
        return self._floor(p, self.tick)

    def check(self, qty: float, price: float) -> Optional[str]:
        """None nếu gửi được; ngược lại lý do (E9-S2: bỏ lệnh dưới minQty / minNotional, ghi log)."""
        if qty < self.min_qty:
            return f"khối lượng {qty} < minQty {self.min_qty}"
        if qty * price < self.min_notional:
            return f"danh nghĩa {qty * price:.2f} < minNotional {self.min_notional}"
        return None


class BinanceAdapter:
    """Binance USD-M (chỉ để THAM KHẢO / đối chiếu; sàn triển khai là OKX) — cùng giao diện với live.okx.OkxAdapter."""
    venue = "binance"

    def __init__(self, keys: Optional[Tuple[str, str]] = None, base_url: str = TESTNET_URL):
        self.c = BinanceFutures(base_url, keys)
        self._f: Dict[str, Filters] = {}

    def filters(self, sym: str) -> Filters:
        if not self._f:
            info = self.c.exchange_info()
            for s in info["symbols"]:
                if s["symbol"].endswith("USDT"):
                    try:
                        self._f[s["symbol"][:-4]] = Filters.from_info(info, s["symbol"])
                    except (KeyError, ExchangeError):
                        pass
        return self._f[sym]

    def klines(self, sym: str, frame: str, limit: int, now: int) -> List[List[Any]]:
        """-> [[open_time, o, h, l, c, quote_volume, close_time]]: volume theo USDT như dữ liệu backtest (r[5] của Binance là base)."""
        return [[r[0], r[1], r[2], r[3], r[4], r[7], r[6]] for r in self.c.klines(f"{sym}USDT", frame, limit)]

    def funding(self, sym: str, since: int) -> List[Tuple[int, float]]:
        return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in self.c.funding(f"{sym}USDT", since)]

    def check_account(self) -> None:
        if self.c._req("GET", "/fapi/v1/positionSide/dual", signed=True).get("dualSidePosition"):
            raise SystemExit("Binance: tài khoản đang ở hedge mode — bot cần one-way")

    def equity(self) -> float:
        return float(self.c.account()["totalMarginBalance"])

    def positions(self) -> Dict[str, Tuple[float, float]]:
        return {p["symbol"][:-4]: (float(p["positionAmt"]), float(p.get("entryPrice") or 0)) for p in self.c.positions()
                if float(p["positionAmt"]) != 0.0}

    def prepare(self, sym: str, leverage: int) -> None:
        self.c.set_margin_isolated(f"{sym}USDT")
        self.c.set_leverage(f"{sym}USDT", int(leverage))

    def market_open(self, sym: str, side: str, qty: float) -> float:
        r = self.c.order(symbol=f"{sym}USDT", side="BUY" if side == "LONG" else "SELL", type="MARKET", quantity=qty, newOrderRespType="RESULT")
        return float(r.get("avgPrice") or 0)

    def place_sl(self, sym: str, side: str, qty: float, trigger: float) -> None:
        self.c.order(symbol=f"{sym}USDT", side="SELL" if side == "LONG" else "BUY", type="STOP_MARKET", stopPrice=trigger, closePosition="true",
                     workingType="MARK_PRICE")

    def place_tp(self, sym: str, side: str, qty: float, px: float) -> None:
        self.c.order(symbol=f"{sym}USDT", side="SELL" if side == "LONG" else "BUY", type="LIMIT", timeInForce="GTC", quantity=qty,
                     reduceOnly="true", price=px)

    def place_post_only(self, sym: str, side: str, qty: float, px: float) -> None:
        self.c.order(symbol=f"{sym}USDT", side="BUY" if side == "LONG" else "SELL", type="LIMIT", timeInForce="GTX", quantity=qty, price=px)

    def cancel_all(self, sym: str) -> None:
        self.c.cancel_all(f"{sym}USDT")

    def close_market(self, sym: str) -> None:
        amt = self.positions().get(sym, (0.0, 0.0))[0]
        if amt:
            self.c.order(symbol=f"{sym}USDT", side="SELL" if amt > 0 else "BUY", type="MARKET", quantity=abs(amt), reduceOnly="true")
