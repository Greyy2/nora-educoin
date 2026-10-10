"""Bot giao dịch theo sổ đã xuất bản (E9) — job API `live_bot`: bộ chạy THỜI GIAN THỰC dùng chung cho mọi môi trường. Sàn triển khai: OKX (Binance chỉ tham khảo).

P9.10c (live/ chia theo MÔI TRƯỜNG chạy): file này gộp live/{bot, okx, state_migrate}.py (xem ba khối PHẦN A / B / C bên dưới) + hồ sơ môi trường THẬT (mode "live", cuối file).
Hai hồ sơ còn lại là file riêng: live/testnet.py (mode "demo": OKX Demo Trading + Binance testnet) và live/paper.py (mode "paper": chỉ dữ liệu công khai).
Mỗi hồ sơ = một `Profile(mode, make_adapter(venue), check(args))`; `run_job` (điểm vào job duy nhất) chọn hồ sơ theo `mode` qua `profile_for` (nạp lười, vì testnet/paper import runner từ file này).
Phần thuần engine (tín hiệu `evaluate_signals`, sổ `PaperBook` / `KernelPaperBook`) ở core/backtest.py. Đường dẫn module cũ trong pickle trạng thái: OLD_MODULES / OLD_CLASSES (PHẦN B).
"""
import base64
import collections
import dataclasses
import hashlib
import hmac
import importlib
import json
import math
import os
import pickle
import re
import signal
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple, Union

import numpy as np

from backend.core import backtest as bt
from backend.core.backtest import (DAY, KernelPaperBook, Order, OrderKind, PaperBook, PositionManager, Runner, VenueCaps, _bar_sig, _engine,
                                   evaluate_signals, klines_frame, required_frames)
from backend.core.models import Account, Fill, OrderRejected
from backend.core.params import DEFAULT_CAPITAL, FRAME_MS as FRAME_MS_ALL
from backend.crawl.cex import REST as OKX_URL   # MỘT định nghĩa URL OKX (crawl/cex.py)
from backend.crawl.store import options, write_job_result
from backend.metrics.trades import CLOSE_KINDS


# ══════════════════════════════════════════════════════════════════════════
# PHẦN A — SÀN: khoá API, ngoại lệ + bộ lọc + Binance, OkxAdapter, OkxVenue (trước đây live/okx.py)
#
# OKX v5 (USDT-margined perpetual SWAP) — sàn triển khai của Nora. demo = "Demo Trading" (header x-simulated-trading: 1, khoá demo),
# live = tài khoản thật (cùng mã, chỉ khác khoá + cờ demo). Chỉ thư viện chuẩn.
#
# Quy đổi: mã sổ "BTC" -> instId "BTC-USDT-SWAP"; khối lượng bot tính theo COIN, sàn nhận số HỢP ĐỒNG (sz = coin / ctVal, làm tròn xuống lotSz).
# Nến: /market/history-candles (100 nến/lần, phân trang) lần đầu, sau đó /market/candles (300 nến mới) gộp vào bộ đệm — mỗi bước chỉ vài request.
# Khung ngày dùng "1Dutc" (nến ngày theo UTC như dữ liệu backtest; "1D" của OKX theo giờ Hồng Kông).
# Lệnh: vào MARKET; DCA = post_only (bị huỷ nếu sẽ khớp ngay = taker); TP = limit reduceOnly; SL = lệnh điều kiện (order-algo, conditional,
# slOrdPx = -1 -> khớp market) reduceOnly; đóng = close-position. Ký: base64(HMAC-SHA256(timestamp + method + path + body)).
#
#
# Thứ tự: [1] khoá API (trước đây secrets) -> [2] ngoại lệ + Filters + Binance (trước đây exchange) -> [3] OkxAdapter (client REST) -> [4] OkxVenue (cổng I/O của engine).
# Các file cũ live/{okx, okx_venue, exchange, secrets}.py đã xoá (không còn alias); pickle cũ lưu đường dẫn đó nạp được nhờ OLD_MODULES (PHẦN B).
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# [1] Khoá API sàn (trước đây live/secrets.py)
#
# Khoá API sàn (E9-S7): nạp từ biến môi trường hoặc file ngoài repo (~/.config/nora/binance_testnet.env, quyền 600). Không bao giờ ghi
# khoá / chữ ký vào log, payload hay result.json (redact).
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_FILE = os.path.expanduser("~/.config/nora/binance_testnet.env")
KEY_ENV, SECRET_ENV = "NORA_BINANCE_TESTNET_KEY", "NORA_BINANCE_TESTNET_SECRET"


def _parse(path: str) -> Dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_keys(path: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """(key, secret) hoặc None. File phải chỉ chủ sở hữu đọc được (600) — lỏng hơn thì từ chối."""
    key, sec = os.environ.get(KEY_ENV), os.environ.get(SECRET_ENV)
    if key and sec:
        return key, sec
    path = path or os.environ.get("NORA_BINANCE_KEYS_FILE") or DEFAULT_FILE
    if not os.path.isfile(path):
        return None
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise PermissionError(f"{path}: quyền {oct(mode)} quá lỏng — chmod 600")
    d = _parse(path)
    key, sec = d.get(KEY_ENV), d.get(SECRET_ENV)
    return (key, sec) if key and sec else None


OKX_FILE = os.path.expanduser("~/.config/nora/okx.env")
OKX_ENV = ("NORA_OKX_KEY", "NORA_OKX_SECRET", "NORA_OKX_PASSPHRASE")


def load_okx(path: Optional[str] = None) -> Optional[Tuple[Tuple[str, str, str], bool]]:
    """((key, secret, passphrase), demo) hoặc None. Biến môi trường hoặc ~/.config/nora/okx.env (quyền 600). NORA_OKX_DEMO=1 (mặc định):
    khoá Demo Trading; =0: khoá tài khoản thật."""
    vals = {k: os.environ.get(k) for k in OKX_ENV + ("NORA_OKX_DEMO",)}
    if not all(vals[k] for k in OKX_ENV):
        path = path or os.environ.get("NORA_OKX_KEYS_FILE") or OKX_FILE
        if not os.path.isfile(path):
            return None
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            raise PermissionError(f"{path}: quyền {oct(mode)} quá lỏng — chmod 600")
        vals.update({k: v for k, v in _parse(path).items() if k in vals})
    if not all(vals.get(k) for k in OKX_ENV):
        return None
    return tuple(vals[k] for k in OKX_ENV), str(vals.get("NORA_OKX_DEMO") or "1").strip() != "0"


_HEX = re.compile(r"[A-Za-z0-9]{32,}")


def redact(text: str, keys: Optional[Tuple[str, str]] = None) -> str:
    """Thay khoá / chữ ký / chuỗi dài giống khoá bằng ***."""
    s = str(text)
    for k in keys or ():
        if k:
            s = s.replace(k, "***")
    s = re.sub(r"signature=[0-9a-fA-F]+", "signature=***", s)
    return _HEX.sub("***", s)


# ══════════════════════════════════════════════════════════════════════════
# [2] Ngoại lệ sàn, bộ lọc giá / khối lượng, Binance (trước đây live/exchange.py)
#
# REST Binance USD-M Futures (testnet / mainnet) — chỉ thư viện chuẩn. Ký HMAC-SHA256; bộ lọc giá/khối lượng (E9-S2).
#
# Endpoint công khai (klines, exchangeInfo) dùng được không cần khoá (chế độ paper đọc dữ liệu thị trường thật). Endpoint riêng cần khoá.
# Lỗi sàn -> ExchangeError (thông điệp đã redact).
# ══════════════════════════════════════════════════════════════════════════

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
    """Binance USD-M (chỉ để THAM KHẢO / đối chiếu; sàn triển khai là OKX) — cùng giao diện với OkxAdapter."""
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


# ══════════════════════════════════════════════════════════════════════════
# [3] OkxAdapter — client REST OKX v5 (docstring module gốc ở đầu file)
# ══════════════════════════════════════════════════════════════════════════

NOT_PERMITTED = {"50120", "50123", "50124"}   # khoá thiếu quyền: chung / theo mã Crypto / theo thị trường
BAR = {"15m": "15m", "1h": "1H", "4h": "4H", "24h": "1Dutc"}
FRAME_MS = {f: FRAME_MS_ALL[f] for f in ("15m", "1h", "4h", "24h")}      # khung bot/OKX hỗ trợ (bản đầy đủ: core.params.FRAME_MS)


def inst(sym: str) -> str:
    return f"{sym}-USDT-SWAP"


class OkxAdapter:
    venue = "okx"

    def __init__(self, keys: Optional[Tuple[str, str, str]] = None, demo: bool = True, base_url: str = OKX_URL, timeout: float = 15.0,
                 pause: float = 0.12):
        self.keys, self.demo, self.base, self.timeout, self.pause = keys, bool(demo), base_url.rstrip("/"), timeout, pause
        self._inst: Dict[str, Dict[str, Any]] = {}
        self._candles: Dict[Tuple[str, str], Dict[int, List[Any]]] = {}

    # ── HTTP ──
    def _req(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Any = None, signed: bool = False) -> Any:
        q = "?" + urllib.parse.urlencode(params) if params else ""
        raw = json.dumps(body) if body is not None else ""
        headers = {"Content-Type": "application/json", "User-Agent": "nora-bot/1.0"}   # UA mặc định của urllib bị Cloudflare chặn (403/1010)
        if self.demo:
            headers["x-simulated-trading"] = "1"
        if signed:
            if not self.keys:
                raise ExchangeError("OKX: cần khoá API (key, secret, passphrase)")
            now = datetime.now(timezone.utc)
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
            sign = base64.b64encode(hmac.new(self.keys[1].encode(), (ts + method + path + q + raw).encode(), hashlib.sha256).digest()).decode()
            headers.update({"OK-ACCESS-KEY": self.keys[0], "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.keys[2]})
        req = urllib.request.Request(self.base + path + q, data=raw.encode() if raw else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            try:
                code = str(json.loads(body).get("code"))
            except ValueError:
                code = ""
            err = NotPermitted if code in NOT_PERMITTED else ExchangeError
            raise err(redact(f"OKX {method} {path} -> {e.code}: {body}", self.keys)) from None
        except urllib.error.URLError as e:
            raise ExchangeError(redact(f"OKX {method} {path} -> {e.reason}", self.keys)) from None
        if str(out.get("code")) != "0":
            raise (NotPermitted if str(out.get("code")) in NOT_PERMITTED else ExchangeError)(redact(f"OKX {method} {path} -> {out.get('code')}: {out.get('msg')} {json.dumps(out.get('data'))[:300]}", self.keys))
        for d in out.get("data") or []:              # lỗi từng lệnh nằm trong data[].sCode
            if isinstance(d, dict) and str(d.get("sCode", "0")) not in ("0", ""):
                raise ExchangeError(redact(f"OKX {path} -> sCode {d.get('sCode')}: {d.get('sMsg')}", self.keys))
        return out.get("data") or []

    # ── công cụ ──
    def instrument(self, sym: str) -> Dict[str, Any]:
        if sym not in self._inst:
            d = self._req("GET", "/api/v5/public/instruments", {"instType": "SWAP", "instId": inst(sym)})
            if not d:
                raise ExchangeError(f"OKX không có {inst(sym)}")
            self._inst[sym] = d[0]
        return self._inst[sym]

    def filters(self, sym: str) -> Filters:
        i = self.instrument(sym)
        ct = float(i["ctVal"])
        return Filters(float(i["tickSz"]), float(i["lotSz"]) * ct, float(i["minSz"]) * ct, 0.0)

    def contracts(self, sym: str, qty_coin: float) -> str:
        i = self.instrument(sym)
        lot = float(i["lotSz"])
        n = int(round(qty_coin / float(i["ctVal"]) / lot, 6)) * lot   # làm tròn 6 số lẻ trước khi lấy phần nguyên: 566.99999 -> 567
        dec = max(0, len(i["lotSz"].rstrip("0").split(".")[1]) if "." in i["lotSz"] else 0)
        return f"{n:.{dec}f}"

    # ── dữ liệu thị trường ──
    def klines(self, sym: str, frame: str, limit: int, now: int) -> List[List[Any]]:
        """-> [[open_time, o, h, l, c, quote_volume, close_time]] tăng dần (volume = volCcyQuote, USDT như dữ liệu backtest), tối đa `limit` nến (gồm cả nến đang chạy — klines_frame (core/backtest.py) bỏ)."""
        key = (sym, frame)
        cache = self._candles.setdefault(key, {})
        step = FRAME_MS[frame]

        def add(rows):
            for r in rows:
                t = int(r[0])
                cache[t] = [t, r[1], r[2], r[3], r[4], r[7], t + step - 1]
        add(self._req("GET", "/api/v5/market/candles", {"instId": inst(sym), "bar": BAR[frame], "limit": 300}))
        after = min(cache) if cache else now
        while len(cache) < limit:
            rows = self._req("GET", "/api/v5/market/history-candles", {"instId": inst(sym), "bar": BAR[frame], "after": after, "limit": 100})
            if not rows:
                break
            add(rows)
            after = min(int(r[0]) for r in rows)
            time.sleep(self.pause)
        keep = sorted(cache)[-limit:]
        for t in list(cache):
            if t < keep[0]:
                del cache[t]
        return [cache[t] for t in keep]

    def funding(self, sym: str, since: int) -> List[Tuple[int, float]]:
        rows = self._req("GET", "/api/v5/public/funding-rate-history", {"instId": inst(sym), "limit": 100})
        return sorted((int(r["fundingTime"]), float(r["realizedRate"] or r["fundingRate"])) for r in rows if int(r["fundingTime"]) >= since)

    def last_price(self, sym: str) -> float:
        """Giá giao dịch gần nhất (ticker công khai) — bot sàn lấy mẫu giá giữa hai nến (kill switch D3, giá tham chiếu lệnh vào)."""
        d = self._req("GET", "/api/v5/market/ticker", {"instId": inst(sym)})
        if not d or not float(d[0].get("last") or 0):
            raise ExchangeError(f"OKX không có giá last của {inst(sym)}")
        return float(d[0]["last"])

    # ── tài khoản ──
    def check_account(self) -> None:
        cfg = self._req("GET", "/api/v5/account/config", signed=True)[0]
        if "withdraw" in str(cfg.get("perm") or ""):
            raise SystemExit("OKX: khoá API có quyền RÚT TIỀN — tạo khoá chỉ đọc + giao dịch rồi chạy lại (E9-S7)")
        if cfg.get("posMode") != "net_mode":
            raise SystemExit("OKX: tài khoản đang ở long_short_mode — bot cần net_mode (một vị thế mỗi mã, khớp max_per_symbol = 1)")

    def equity(self) -> float:
        """Vốn dùng được cho hợp đồng USDT. Chế độ ký quỹ đơn tiền (acctLv 1/2, mặc định của Futures mode): CHỈ số dư USDT (coin khác như
        BTC/OKB trong ví không làm ký quỹ được — lấy totalEq sẽ tính khối lượng quá vốn, lệnh bị từ chối 51008). Đa tiền / danh mục
        (acctLv 3/4): adjEq (vốn điều chỉnh dùng làm ký quỹ)."""
        if getattr(self, "_acct_lv", None) is None:
            self._acct_lv = int(self._req("GET", "/api/v5/account/config", signed=True)[0].get("acctLv") or 2)
        b = self._req("GET", "/api/v5/account/balance", {"ccy": "USDT"}, signed=True)[0]
        if self._acct_lv >= 3 and b.get("adjEq"):
            return float(b["adjEq"])
        usdt = next((d for d in b.get("details") or [] if d.get("ccy") == "USDT"), None)
        return float(usdt["eq"]) if usdt else 0.0

    def positions(self) -> Dict[str, Tuple[float, float]]:
        out = {}
        for p in self._req("GET", "/api/v5/account/positions", {"instType": "SWAP"}, signed=True):
            if not p.get("instId", "").endswith("-USDT-SWAP") or not float(p.get("pos") or 0):
                continue
            sym = p["instId"].split("-")[0]
            out[sym] = (float(p["pos"]) * float(self.instrument(sym)["ctVal"]), float(p.get("avgPx") or 0))
        return out

    def closed_since(self, sym: str, since: int) -> Dict[str, Any]:
        """Vị thế vừa đóng của mã (lịch sử vị thế sàn, mới nhất có thời điểm mở >= since - 1 phút): giá đóng TB, lãi lỗ, phí thật."""
        rows = self._req("GET", "/api/v5/account/positions-history", {"instType": "SWAP", "instId": inst(sym), "limit": 20}, signed=True)
        rows = [r for r in rows if int(r.get("cTime") or 0) >= since - 60_000]
        if not rows:
            return {}
        r = max(rows, key=lambda x: int(x.get("uTime") or 0))
        return {"close_price": float(r.get("closeAvgPx") or 0) or None, "open_price": float(r.get("openAvgPx") or 0) or None,
                "pnl": float(r.get("realizedPnl") or 0), "fee": float(r.get("fee") or 0), "funding": float(r.get("fundingFee") or 0),
                "exchange_close_time": int(r.get("uTime") or 0)}

    # ── lệnh ──
    def prepare(self, sym: str, leverage: int) -> None:
        self._req("POST", "/api/v5/account/set-leverage", body={"instId": inst(sym), "lever": str(int(leverage)), "mgnMode": "isolated"},
                  signed=True)

    def market_open(self, sym: str, side: str, qty: float) -> float:
        self._req("POST", "/api/v5/trade/order", body={"instId": inst(sym), "tdMode": "isolated", "side": "buy" if side == "LONG" else "sell",
                                                         "ordType": "market", "sz": self.contracts(sym, qty)}, signed=True)
        for _ in range(10):                          # giá khớp trung bình từ vị thế
            pos = self.positions().get(sym)
            if pos and pos[1]:
                return pos[1]
            time.sleep(0.5)
        raise ExchangeError(f"OKX: không thấy vị thế {sym} sau lệnh market")

    def place_sl(self, sym: str, side: str, qty: float, trigger: float) -> None:
        self._req("POST", "/api/v5/trade/order-algo", body={
            "instId": inst(sym), "tdMode": "isolated", "side": "sell" if side == "LONG" else "buy", "ordType": "conditional",
            "sz": self.contracts(sym, qty), "slTriggerPx": str(trigger), "slOrdPx": "-1", "slTriggerPxType": "last", "reduceOnly": "true"},
                  signed=True)                         # kích hoạt theo giá giao dịch (như engine dùng nến giá giao dịch)

    def place_trailing(self, sym: str, side: str, qty: float, callback_pct: float, active_px: float) -> None:
        """Trailing stop GỐC của sàn (move_order_stop): sàn tự bám đỉnh/đáy từ lúc giá chạm active_px, đóng market khi giá lùi callback_pct%.
        Khớp ngay trong nến như engine, không phụ thuộc bot đang chạy."""
        self._req("POST", "/api/v5/trade/order-algo", body={
            "instId": inst(sym), "tdMode": "isolated", "side": "sell" if side == "LONG" else "buy", "ordType": "move_order_stop",
            "sz": self.contracts(sym, qty), "callbackRatio": f"{min(max(callback_pct / 100.0, 0.001), 0.3):.4f}",
            "activePx": str(active_px), "reduceOnly": "true"}, signed=True)

    def place_tp(self, sym: str, side: str, qty: float, px: float) -> None:
        self._req("POST", "/api/v5/trade/order", body={"instId": inst(sym), "tdMode": "isolated", "side": "sell" if side == "LONG" else "buy",
                                                         "ordType": "limit", "px": str(px), "sz": self.contracts(sym, qty), "reduceOnly": "true"},
                  signed=True)

    def place_post_only(self, sym: str, side: str, qty: float, px: float) -> None:
        self._req("POST", "/api/v5/trade/order", body={"instId": inst(sym), "tdMode": "isolated", "side": "buy" if side == "LONG" else "sell",
                                                         "ordType": "post_only", "px": str(px), "sz": self.contracts(sym, qty)}, signed=True)

    def cancel_all(self, sym: str) -> None:
        pend = self._req("GET", "/api/v5/trade/orders-pending", {"instId": inst(sym)}, signed=True)
        for k in range(0, len(pend), 20):
            self._req("POST", "/api/v5/trade/cancel-batch-orders", body=[{"instId": inst(sym), "ordId": o["ordId"]} for o in pend[k:k + 20]],
                      signed=True)
        for kind in ("conditional", "move_order_stop"):
            algos = self._req("GET", "/api/v5/trade/orders-algo-pending", {"instId": inst(sym), "ordType": kind}, signed=True)
            if algos:
                self._req("POST", "/api/v5/trade/cancel-algos", body=[{"instId": inst(sym), "algoId": a["algoId"]} for a in algos], signed=True)

    def close_market(self, sym: str) -> None:
        try:
            self._req("POST", "/api/v5/trade/close-position", body={"instId": inst(sym), "mgnMode": "isolated"}, signed=True)
        except ExchangeError as e:
            if "51023" not in str(e):                # "Position does not exist"
                raise


# ══════════════════════════════════════════════════════════════════════════
# [4] OkxVenue — cài Venue Protocol trên OkxAdapter (trước đây live/okx_venue.py)
#
# OkxVenue (P6.7): cài `Venue` Protocol (core/backtest.py) trên client `OkxAdapter` — dịch I/O THUẦN, không chứa chính sách.
# Đặc tả: docs/bmad/p6_execution_design.md §3 + §6. Sizing, mức SL/TP/DCA, kill switch ở PositionManager/policy; venue chỉ đổi Order <-> lệnh OKX
# và đổi trạng thái vị thế OKX <-> Fill / OrderRejected. Không tự HTTP/ký: gọi lại các hàm của `okx.OkxAdapter`.
#
# Ánh xạ lệnh
#   ENTRY  prepare(lev) + market_open(sym, side, qty); qty = Filters.qty(notional / giá tham chiếu); Fill("entry") ở GIÁ KHỚP THẬT (vị thế sàn).
#   EXIT   cancel_all + close_market; Fill đóng lấy giá/phí từ `closed_since` (lịch sử vị thế), kind = "exit" (hoặc kind của lệnh gọi — xem _exit).
#   SL     place_sl (điều kiện, trigger theo giá giao dịch cuối, reduce-only); TP  place_tp (limit reduce-only).
#   DCA    place_post_only; qty = Filters.qty(notional / level) (lệnh dưới minQty -> OrderRejected("min_size")).
#   TRAIL  place_trailing (sàn bám đỉnh) khi client có hàm này (caps.native_trailing); ngược lại giữ làm lệnh CỤC BỘ (như Bot cũ: không gửi sàn),
#          poll(now, bars) kiểm high/low của nến: chạm `level` thì đóng market và phát Fill("trail").
#          Quy ước TRAIL gốc (P6.8b): Order.activation = giá KÍCH HOẠT (activePx), Order.callback_pct = callback % (vd 1.5 = 1.5%); Order.level là mức stop TĨNH
#          của sim, KHÔNG dùng. Thiếu hai trường mới (nan) -> rơi về quy ước cũ (level = kích hoạt, trigger = callback). Thiếu callback -> OrderRejected.
#
# Sự kiện (kéo): `submit` đẩy Fill/OrderRejected tức thì vào hàng đợi của slot (ENTRY/EXIT đồng bộ); `poll(now[, bars])` đọc positions() một lần cho mọi slot:
#   - khối lượng tăng so với đã biết -> Fill("dca") cho từng tầng DCA chờ mà phần tăng phủ được (cùng suy luận Bot.reconcile; giá = mức tầng, maker);
#   - vị thế biến mất -> Fill đóng; kind suy từ lệnh bảo vệ GẦN giá đóng nhất (sl / tp, trong dung sai `match_tol`), ngược lại "trail" nếu còn trailing
#     chờ, ngược lại "exit". Dọn mọi lệnh còn sót (cancel_all) như Bot.reconcile.
#
# Giới hạn so với SimVenue (cố ý, ghi rõ):
#   - OkxAdapter KHÔNG có huỷ từng lệnh: `cancel_slot` = cancel_all(symbol) (không để lại lệnh bảo vệ mồ côi); `cancel(order_id)` = bỏ lệnh khỏi sổ rồi cancel_all +
#     đặt lại các lệnh còn lại (SL, TP, TRAIL, DCA) — có khoảng ngắn không có SL giữa hai bước; cancel_all huỷ cả lệnh không do venue đặt trên mã đó.
#   - Một slot / symbol (OKX net mode, ADR D1 max_per_symbol = 1): bind slot thứ hai trên cùng symbol -> SlotConflict.
#   - Phí: Fill vào lệnh/DCA có fee = 0 (OKX không trả phí trong phản hồi đặt lệnh); Fill đóng mang TỔNG phí cả vòng (|fee| của positions-history) nên tổng phí đúng.
#   - Fill.order_id = Order.id của lệnh (adapter không trả ordId của sàn); lãi lỗ thật lưu ở `last_close[slot]` (Fill không có trường pnl).
#   - Không sinh Fill thanh lý (caps.generates_liquidation=False): thanh lý chỉ quan sát như vị thế biến mất.
#   - Khối lượng giảm một phần (TP khớp một phần...) chỉ cập nhật qty đã biết, không phát sự kiện.
# ══════════════════════════════════════════════════════════════════════════

EPS = 1e-12
MIN_SIZE_CODES = ("51020", "51121")          # OKX: dưới khối lượng tối thiểu / không là bội lotSz
PRIORITY = (OrderKind.SL, OrderKind.TP, OrderKind.TRAIL, OrderKind.DCA)   # thứ tự đặt lại: bảo vệ trước, tầng DCA sau
KIND_NAME = {OrderKind.ENTRY: "entry", OrderKind.EXIT: "exit", OrderKind.DCA: "dca", OrderKind.SL: "sl", OrderKind.TRAIL: "trail",
             OrderKind.TP: "tp"}


class SlotConflict(RuntimeError):
    """Hai slot cùng một symbol: OKX net mode chỉ có một vị thế và một giá TB mỗi symbol (ADR-P6 D1: max_per_symbol = 1)."""


@dataclass
class _Pos:
    side: str                  # "LONG" | "SHORT"
    qty: float                 # khối lượng (coin) đã biết
    avg: float
    leverage: float
    entry_time: int
    order_id: int


@dataclass
class _Slot:
    sym: str
    pos: Optional[_Pos] = None
    orders: Dict[int, Order] = field(default_factory=dict)      # lệnh chờ theo thứ tự đặt (DCA: thứ tự tầng)
    placed: set = field(default_factory=set)                    # id lệnh đã gửi sàn (TRAIL cục bộ thì không)
    dca_qty: Dict[int, float] = field(default_factory=dict)
    events: Deque[Union[Fill, OrderRejected]] = field(default_factory=deque)


class OkxVenue:
    def __init__(self, client, slots: Optional[Dict[int, str]] = None, clock: Optional[Callable[[], int]] = None,
                 match_tol: float = 0.005, close_retries: int = 3, settle_s: float = 0.5):
        self.client = client
        self.caps = VenueCaps(generates_liquidation=False, native_trailing=getattr(client, "place_trailing", None) is not None,
                              post_only=True, rounds_qty=True)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.match_tol, self.close_retries, self.settle_s = match_tol, max(1, int(close_retries)), settle_s
        self._slots: Dict[int, _Slot] = {}
        self._ref: Dict[int, float] = {}
        self.last_close: Dict[int, Dict[str, Any]] = {}          # dữ liệu closed_since của lần đóng gần nhất của slot (pnl, phí, giá...)
        for s, sym in (slots or {}).items():
            self.bind(s, sym)

    # ── pickle (unified.pkl của bot): bỏ client (giữ khoá API!) và đồng hồ; bot gắn lại sau khi nạp ──
    def __getstate__(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["client"] = None
        d["_clock"] = None
        return d

    # ── slot <-> symbol ──
    def bind(self, slot: int, sym: str) -> None:
        for s, st in self._slots.items():
            if st.sym == sym and s != slot:
                raise SlotConflict(f"OKX net mode: symbol {sym} đã gắn slot {s}, không thể gắn thêm slot {slot} (max_per_symbol = 1)")
        if slot in self._slots and self._slots[slot].sym != sym:
            raise SlotConflict(f"slot {slot} đã gắn symbol {self._slots[slot].sym}, không đổi sang {sym}")
        self._slots.setdefault(slot, _Slot(sym))

    def release(self, slot: int) -> None:
        st = self._slots.get(slot)
        if st is not None and (st.pos is not None or st.orders):
            raise SlotConflict(f"slot {slot} còn vị thế / lệnh chờ — đóng hoặc cancel_slot trước khi release")
        self._slots.pop(slot, None)

    def set_ref(self, slot: int, price: float) -> None:
        """Giá tham chiếu cho ENTRY (qty = notional / giá, slip so với giá này): thường là close nến cuối. Order.level hữu hạn thì ưu tiên."""
        self._ref[slot] = float(price)

    def _st(self, slot: int) -> _Slot:
        if slot not in self._slots:
            raise KeyError(f"slot {slot} chưa gắn symbol (gọi bind(slot, sym) hoặc truyền slots={{...}})")
        return self._slots[slot]

    # ── Venue ──
    def submit(self, order: Order) -> None:
        st = self._st(order.slot)
        if order.kind == OrderKind.ENTRY:
            return self._entry(st, order)
        if order.kind == OrderKind.EXIT:
            return self._exit(st, order.slot, "exit", order.id, order.reason)
        if st.pos is None:
            return self._reject(st, order, "no_position")
        st.orders[order.id] = order
        why = self._place(order.slot, st, order)
        if why:
            st.orders.pop(order.id, None)
            self._reject(st, order, why)

    def cancel(self, order_id: int) -> None:
        for slot, st in self._slots.items():
            o = st.orders.pop(order_id, None)
            if o is None:
                continue
            if order_id in st.placed:                  # adapter không huỷ từng lệnh: huỷ hết rồi đặt lại phần còn lại
                st.placed.discard(order_id)
                self._resync(slot, st)
            return

    def cancel_slot(self, slot: int) -> None:
        st = self._st(slot)
        if st.placed or st.orders or st.pos is not None:   # có thể còn lệnh sàn dù sổ trống (vừa lỗi giữa chừng): luôn dọn theo symbol
            self.client.cancel_all(st.sym)
        st.orders.clear()
        st.placed.clear()
        st.dca_qty.clear()

    def open_orders(self, slot: int) -> List[Order]:
        return list(self._st(slot).orders.values())

    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]:
        st = self._st(slot)
        return st.events.popleft() if st.events else None

    # ── poll: đọc vị thế sàn, suy ra Fill ──
    def poll(self, now: int, bars: Optional[Dict[str, Tuple[float, float, float]]] = None) -> int:
        """Đọc positions() một lần cho mọi slot đang có vị thế; trả số sự kiện mới. `bars` = {sym: (high, low, close)} (tuỳ chọn): cập nhật giá tham
        chiếu và kiểm TRAIL cục bộ (client không có trailing gốc)."""
        n0 = sum(len(s.events) for s in self._slots.values())
        live = {s: v for s, v in self.client.positions().items() if abs(v[0]) > EPS}
        for slot, st in self._slots.items():
            if st.pos is None:
                continue
            if bars and st.sym in bars:
                self._ref[slot] = float(bars[st.sym][2])
            cur = live.get(st.sym)
            if cur is None:
                self._on_gone(slot, st, now)
                continue
            amt, entry = abs(cur[0]), cur[1]
            p = st.pos
            if amt > p.qty * (1 + 1e-6):
                self._on_increase(slot, st, amt, entry, now)
            elif amt < p.qty * (1 - 1e-6):
                p.qty = amt                              # đóng một phần: chỉ đồng bộ khối lượng (xem docstring)
            if bars and st.sym in bars:
                self._local_trail(slot, st, bars[st.sym], now)
        return sum(len(s.events) for s in self._slots.values()) - n0

    # ── nội bộ: đặt lệnh ──
    def _entry(self, st: _Slot, o: Order) -> None:
        if st.pos is not None:
            return self._reject(st, o, "position_exists")
        f = self.client.filters(st.sym)
        ref = o.level if math.isfinite(o.level) and o.level > 0 else self._ref.get(o.slot, float("nan"))
        if not (math.isfinite(ref) and ref > 0):
            raise ValueError(f"ENTRY slot {o.slot}: thiếu giá tham chiếu (set_ref hoặc Order.level)")
        qty = f.qty(o.notional / ref)
        if f.check(qty, ref):
            return self._reject(st, o, "min_size")
        lev = max(1, int(round(o.notional / o.margin))) if o.margin > 0 else 1
        side = "LONG" if o.is_buy else "SHORT"
        try:
            self.client.prepare(st.sym, lev)
            px = float(self.client.market_open(st.sym, side, qty) or ref)
        except Exception as e:
            why = self._classify(o, e)
            if why is None:
                raise
            return self._reject(st, o, why)
        notional = qty * px
        slip = (px - ref) / ref * (1 if o.is_buy else -1)
        now = self._clock()
        st.pos = _Pos(side, qty, px, float(lev), now, o.id)
        st.events.append(Fill(slot=o.slot, order_id=o.id, kind="entry", t=now, price=px, raw_price=ref, notional=notional, margin=notional / lev,
                              fee=0.0, slip=slip, liquidity="taker", reason=o.reason, leverage_used=float(lev)))

    def _place(self, slot: int, st: _Slot, o: Order) -> Optional[str]:
        """Gửi một lệnh bảo vệ / DCA lên sàn. None = ổn; chuỗi = lý do từ chối (đã phân loại). Lỗi lạ -> ném lại."""
        f = self.client.filters(st.sym)
        side = st.pos.side
        try:
            if o.kind == OrderKind.SL:
                self.client.place_sl(st.sym, side, f.qty_close(st.pos.qty), f.price(o.level))
            elif o.kind == OrderKind.TP:
                self.client.place_tp(st.sym, side, f.qty_close(st.pos.qty), f.price(o.level))
            elif o.kind == OrderKind.TRAIL:
                if not self.caps.native_trailing:        # cục bộ: không gửi sàn, poll(bars) kiểm
                    return None
                cb = o.callback_pct if math.isfinite(o.callback_pct) else o.trigger      # thiếu trường mới -> quy ước cũ (trigger = callback %)
                act = o.activation if math.isfinite(o.activation) else o.level           # ... (level = giá kích hoạt)
                if not (cb > 0 and math.isfinite(cb)) or not (act > 0 and math.isfinite(act)):
                    return "no_callback"
                self.client.place_trailing(st.sym, side, f.qty_close(st.pos.qty), float(cb), f.price(act))
            elif o.kind == OrderKind.DCA:
                q = st.dca_qty.get(o.id)
                if q is None:
                    q = st.dca_qty[o.id] = f.qty(o.notional / o.level)
                px = f.price(o.level)
                if f.check(q, px):
                    return "min_size"
                self.client.place_post_only(st.sym, side, q, px)
            else:
                raise ValueError(f"loại lệnh không đặt chờ: {o.kind!r}")
        except ValueError:
            raise
        except Exception as e:
            why = self._classify(o, e)
            if why is None:
                raise
            return why
        st.placed.add(o.id)
        return None

    @staticmethod
    def _classify(o: Order, e: Exception) -> Optional[str]:
        """Lỗi sàn -> lý do OrderRejected; None = lỗi không phân loại được (ném lại cho caller)."""
        if isinstance(e, NotPermitted):
            return "not_permitted"
        if not isinstance(e, ExchangeError):
            return None
        msg = str(e)
        if any(c in msg for c in MIN_SIZE_CODES):
            return "min_size"
        if o.kind == OrderKind.DCA or o.post_only:      # như Bot._protect: post-only bị từ chối -> bỏ tầng, không đổi sang market
            return "post_only"
        return None

    def _reject(self, st: _Slot, o: Order, why: str) -> None:
        st.events.append(OrderRejected(slot=o.slot, order_id=o.id, kind=KIND_NAME[o.kind], reason=why))

    def _resync(self, slot: int, st: _Slot) -> None:
        keep = sorted(st.orders.values(), key=lambda x: PRIORITY.index(x.kind))
        self.client.cancel_all(st.sym)
        st.placed.clear()
        for o in keep:
            why = self._place(slot, st, o)
            if why:
                st.orders.pop(o.id, None)
                self._reject(st, o, why)

    # ── nội bộ: đóng ──
    def _close_info(self, sym: str, since: int) -> Dict[str, Any]:
        fetch = getattr(self.client, "closed_since", None)
        if fetch is None:
            return {}
        err = ""
        for k in range(self.close_retries):
            try:
                info = fetch(sym, int(since)) or {}
            except Exception as e:                       # không đọc được: vẫn đóng sổ, thiếu giá/phí thật
                info, err = {}, f"{type(e).__name__}: {e}"
            if info.get("close_price"):
                return info
            if k + 1 < self.close_retries and self.settle_s:
                time.sleep(self.settle_s)
        return {**info, "error": err} if err else info

    def _emit_close(self, slot: int, st: _Slot, kind: str, order_id: int, reason: str, now: int, fallback_px: float,
                    info: Optional[Dict[str, Any]] = None) -> None:
        p = st.pos
        if info is None:
            info = self._close_info(st.sym, p.entry_time)
        self.last_close[slot] = info
        px = float(info.get("close_price") or fallback_px or p.avg)
        lvl = next((o.level for o in st.orders.values() if KIND_NAME[o.kind] == kind and math.isfinite(o.level)), float("nan"))
        raw = lvl if math.isfinite(lvl) and lvl > 0 else px
        slip = (raw - px) / raw * (1 if p.side == "LONG" else -1) if kind in ("sl", "trail") else 0.0   # SL/trailing: market sau trigger
        st.events.append(Fill(slot=slot, order_id=order_id, kind=kind, t=now, price=px, raw_price=raw, notional=0.0, margin=0.0,
                              fee=abs(float(info.get("fee") or 0.0)), slip=slip, liquidity="maker" if kind == "tp" else "taker", reason=reason))
        st.pos = None
        st.orders.clear()
        st.placed.clear()
        st.dca_qty.clear()

    def _exit(self, st: _Slot, slot: int, kind: str, order_id: int, reason: str) -> None:
        self.client.cancel_all(st.sym)
        self.client.close_market(st.sym)
        if st.pos is None:
            return                                       # đã phẳng (close_market bỏ qua 51023): không có gì để ghi
        self._emit_close(slot, st, kind, order_id, reason, self._clock(), self._ref.get(slot, 0.0))

    def _on_gone(self, slot: int, st: _Slot, now: int) -> None:
        """Vị thế sàn biến mất (SL/TP/trailing khớp hoặc thanh lý): suy kind theo lệnh bảo vệ gần giá đóng nhất."""
        p = st.pos
        info = self._close_info(st.sym, p.entry_time)
        px = float(info.get("close_price") or 0.0)
        near = [(abs(o.level - px) / px, o) for o in st.orders.values() if o.kind in (OrderKind.SL, OrderKind.TP) and px > 0 and math.isfinite(o.level)]
        near.sort(key=lambda x: x[0])
        trail = next((o for o in st.orders.values() if o.kind == OrderKind.TRAIL), None)
        guard = [o for o in st.orders.values() if o.kind in (OrderKind.SL, OrderKind.TP, OrderKind.TRAIL)]
        if near and near[0][0] <= self.match_tol:
            o = near[0][1]
        elif trail is not None and (px > 0 or len(guard) == 1):
            o = trail
        elif px <= 0 and len(guard) == 1:
            o = guard[0]
        else:
            o = None
        kind = KIND_NAME[o.kind] if o is not None else "exit"
        self.client.cancel_all(st.sym)                   # dọn lệnh chờ còn sót (tầng DCA, bảo vệ đối ứng)
        self._emit_close(slot, st, kind, o.id if o is not None else p.order_id, "", now, self._ref.get(slot, 0.0), info)

    def _local_trail(self, slot: int, st: _Slot, bar: Tuple[float, float, float], now: int) -> None:
        if st.pos is None:
            return
        o = next((x for x in st.orders.values() if x.kind == OrderKind.TRAIL and x.id not in st.placed and math.isfinite(x.level)), None)
        if o is None:
            return
        hi, lo = float(bar[0]), float(bar[1])
        hit = lo <= o.level if st.pos.side == "LONG" else hi >= o.level
        if hit:
            self._exit(st, slot, "trail", o.id, o.reason)

    def _on_increase(self, slot: int, st: _Slot, amt: float, entry: float, now: int) -> None:
        """Khối lượng tăng: tầng DCA chờ nào phủ được phần tăng -> Fill("dca") (cùng suy luận Bot.reconcile, tolerance 1e-6)."""
        p = st.pos
        cum = p.qty
        for o in [x for x in st.orders.values() if x.kind == OrderKind.DCA]:
            q = st.dca_qty.get(o.id, 0.0)
            if q <= 0 or cum + q > amt * (1 + 1e-6):
                break
            cum += q
            f = self.client.filters(st.sym)
            px = f.price(o.level)
            notional = q * px
            st.events.append(Fill(slot=slot, order_id=o.id, kind="dca", t=now, price=px, raw_price=px, notional=notional,
                                  margin=notional / p.leverage, fee=0.0, slip=0.0, liquidity="maker", reason=o.reason))
            st.orders.pop(o.id, None)
            st.placed.discard(o.id)
            st.dca_qty.pop(o.id, None)
        p.qty, p.avg = amt, entry or p.avg


# ══════════════════════════════════════════════════════════════════════════
# PHẦN B — NẠP TRẠNG THÁI CŨ: StateUnpickler, OLD_MODULES, chuyển paper.pkl -> KernelBook (trước đây live/state_migrate.py)
#
# P9.4b T7 — chuyển trạng thái paper CŨ (paper.pkl: PaperBook = Runner + PositionTracker / PositionManager) sang KernelBook (paper_state.npz + paper.json).
#
# An toàn: pickle cũ KHÔNG bao giờ được nạp bằng pickle.load thường. `StateUnpickler(bag=True).find_class` (sau khi đổi đường dẫn module qua OLD_MODULES) ánh xạ MỌI lớp cũ (PaperBook, PositionTracker, PositionManager, Runner,
# SimVenue + _Slot, Account / CapitalLedger, PositionBook, _ExecVenue, okx_venue._Slot / _Pos, Order, OrderKind, VenueCaps, StrategyParams, OrderModel / PositionModel /
# OrderType / PositionStatus / PositionType) sang `_Bag` (chỉ giữ __dict__ + đối số dựng), không import tracker / manager / runner; chỉ cho thêm collections.deque và
# builtins.getattr (bound method trong pickle: trả giá trị thuộc tính của _Bag, không bao giờ gọi gì); mọi global khác -> UnpicklingError.
#
# Hai định dạng cũ:
# - "tracker": PaperBook.__dict__ phẳng (ledger, books, last_*, peak_mtm, halted_at, last_t, trades, rejected_for_risk) với PositionTracker mỗi slot;
# - "event": PaperBook.__dict__ = {engine, symbols, events, runner}; runner mang account + books + các trường danh mục; PositionManager mỗi slot (qty / avg / ... nằm ở mgr.book).
#
# Ánh xạ trường -> KernelBook (mọi slot k):
#   F : qty->F_QTY, avg->F_AVG, margin_used->F_MU, fees_paid->F_FP, last_fill->F_LAST_FILL, next_margin->F_NEXT, peak->F_PEAK, mae_usd->F_MAE, reserved_here->F_RES_HERE,
#       funding_paid->F_FUND, entry_equity->F_ENTRY_EQ, max_capital->F_MAXCAP, pos_leverage->F_POS_LEV, planned_risk->F_PLANNED, pending_vol->F_PVOL, sl_pct/tp_pct/trail_pct/
#       trail_activation_pct->F_SL/F_TP/F_TRAIL/F_TACT, unit_pct->F_UNIT, dca_steps->F_DS0+j (+ I_NST)
#   I : is_open->I_OPEN, pending_entry->I_PE, pending_exit->I_PX, layer_count->I_LAYERS, entry_time->I_ENTRY_T, last_close_time->I_LASTCLOSE / I_HASLC, dca_rejected->I_DCAREJ,
#       skipped_no_vol->I_SKIP, dca_ok->I_DCAOK, I_BLK = -2 (bộ đếm lưới bắt đầu lại), I_POS = hàng outF của vị thế mở
#   vị thế mở -> một hàng outF / outI (enter_price, entry_margin / notional / fee, max / min price, unit_pct, leverage_used, risk_usd, enter_time, start_reason) + các hàng ordF / ordI
#       của lệnh thuộc vị thế đó (price, qty, fee, phase, liquidity; raw / slip suy từ OrderModel.slippage hoặc slippage_rate của slot khi là taker)
#   sổ vốn: equity / reserved / peak -> LG (peak thiếu = max(initial, equity)), rejected -> G_REJ; runner: peak_mtm -> PS_PEAK_MTM, halted_at -> PSI_HALTED / PSI_HALT_AT,
#       rejected_for_risk -> G_RISKMIN (+ G_ATT), last_close / low / high / open -> LPX, last_t -> _last_t / PSI_LAST_T, trades -> trades (nguyên dict)
#   Không chuyển (không còn ý nghĩa trong kernel): lệnh chờ trên SimVenue (dựng lại từ trạng thái slot ở nến kế), max_new_* / risk_scale (tạm thời), events, lịch sử orders
#   của vị thế đã đóng, đường vốn theo giờ (eqT/eqM/eqW bắt đầu lại; PSI_HAS_SMP = 0).
#
# Tham số: `kernel_book_from_old` dựng KernelBook từ CHÍNH các thuộc tính chuẩn hoá trong pickle (không cần book.json; dùng cho test); `check_params` so P / PI / cfg của sổ mới
# (dựng từ chiến lược HIỆN TẠI) với pickle — lệch thì ParamsMismatch.
# ══════════════════════════════════════════════════════════════════════════


_MODULE_PREFIXES = ("backend.core.", "backend.live.")
_OLD_NAMES = frozenset({
    "PaperBook", "PositionTracker", "PositionManager", "Runner", "SimVenue", "_Slot", "Account", "CapitalLedger", "PositionBook", "_ExecVenue", "_Pos",
    "Order", "OrderKind", "VenueCaps", "StrategyParams", "OrderModel", "PositionModel", "OrderType", "PositionStatus", "PositionType",
})
_LIQ = {"maker": 1, "taker": 2, "liquidation": 3}


class MigrationError(ValueError):
    """Pickle cũ không chuyển được (hỏng / định dạng lạ)."""


class ParamsMismatch(MigrationError):
    """Tham số trong pickle khác cấu hình hiện tại: không chuyển, cất pickle cũ và bắt đầu sạch."""


# ── nạp pickle hạn chế ─────────────────────────────────────────────────────────────────────────────────────────────────────
class _Bag:
    """Túi giữ __dict__ của một đối tượng cũ (và đối số dựng, vd. giá trị enum). Không có hành vi nào của lớp gốc."""

    _cls = ""

    def __init__(self, *args):
        self.__dict__["_args"] = args

    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) == 2:       # (dict, slotstate)
            for part in state:
                if part:
                    self.__dict__.update(part)
        elif isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.__dict__["_state"] = state

    def __repr__(self):
        return f"<_Bag {self._cls}>"


_BAG_CLASSES: Dict[str, type] = {}


def _bag_class(module: str, name: str) -> type:
    key = f"{module}.{name}"
    if key not in _BAG_CLASSES:
        _BAG_CLASSES[key] = type(name, (_Bag,), {"_cls": key})
    return _BAG_CLASSES[key]


def _safe_getattr(obj, name, *default):
    """builtins.getattr của pickle (bound method của slot / venue): chỉ đọc __dict__ của _Bag, thiếu -> None; không bao giờ gọi hay đọc đối tượng thật."""
    if isinstance(obj, _Bag) and isinstance(name, str):
        return obj.__dict__.get(name, default[0] if default else None)
    raise pickle.UnpicklingError("getattr chỉ cho phép trên đối tượng cũ đã bọc")


# MỘT bảng duy nhất: đường dẫn module cũ trong pickle trạng thái bot -> module hiện tại (các shim/alias đã xoá; tên lớp giữ nguyên). Mọi nơi nạp trạng thái bot
# (load_pickle, load_paper_state, load_old) đi qua StateUnpickler.find_class nên đều dùng bảng này.
OLD_MODULES: Dict[str, str] = {
    # backend/core/execute/* (gộp vào core/models.py, core/position_size.py, core/backtest.py)
    "backend.core.execute.models": "backend.core.models",
    "backend.core.execute.events": "backend.core.models",
    "backend.core.execute.account": "backend.core.models",
    "backend.core.execute.ledger": "backend.core.models",
    "backend.core.execute.policy": "backend.core.position_size",
    "backend.core.execute.risk": "backend.core.position_size",
    "backend.core.execute.venue": "backend.core.backtest",
    "backend.core.execute.amm": "backend.core.backtest",
    "backend.core.execute.tracker": "backend.core.backtest",
    "backend.core.execute.manager": "backend.core.backtest",
    "backend.core.execute.sim_venue": "backend.core.backtest",
    "backend.core.execute.runner": "backend.core.backtest",
    # backend/core/backtest/* (package cũ -> một file) và backend/core/params/* (package cũ -> core/params.py)
    "backend.core.backtest.engine": "backend.core.backtest",
    "backend.core.backtest.portfolio": "backend.core.backtest",
    "backend.core.backtest.kernel": "backend.core.backtest",
    "backend.core.backtest.dex": "backend.core.backtest",
    "backend.core.backtest.run": "backend.optimize.search.evaluate",
    "backend.core.backtest.tick_run": "backend.optimize.search.evaluate",
    "backend.core.backtest.run_defaults": "backend.optimize.process.tasks",
    "backend.core.backtest.custom_run": "backend.optimize.process.tasks",
    "backend.core.backtest.edu_precompute": "backend.optimize.process.tasks",
    "backend.core.params.schema": "backend.core.params",
    "backend.core.params.builder": "backend.core.params",
    "backend.core.params.modes": "backend.routes.process",
    "backend.core.params.presets": "backend.optimize.book.build",
    "backend.core.params.template": "backend.core.params",
    # backend/core/strategy/* (P9.9: sổ chiến lược -> optimize/book/build.py; hàm dựng cây -> core/signal.py)
    "backend.core.strategy.book": "backend.optimize.book.build",
    "backend.core.strategy.library": "backend.core.signal",
    # backend/live/* (P9.7: gộp vào bot.py, okx.py và metrics/trades.py; bot.py / okx.py nay đã vào live/live.py — mục bên dưới)
    "backend.live.unified": "backend.live.live",
    "backend.live.signals": "backend.live.live",
    "backend.live.okx_venue": "backend.live.live",
    "backend.live.exchange": "backend.live.live",
    "backend.live.secrets": "backend.live.live",
    "backend.live.compare": "backend.metrics.trades",
    # backend/live/* (P9.10c: live/ chia theo MÔI TRƯỜNG chạy — bot.py + okx.py + state_migrate.py gộp vào live/live.py; paper.py / testnet.py là hồ sơ môi trường)
    "backend.live.bot": "backend.live.live",
    "backend.live.okx": "backend.live.live",
    "backend.live.state_migrate": "backend.live.live",
    # P9.10a: module đã xoá khi gộp file (bảng sinh từ các shim cũ; mục có nhiều đích ghi đích đầu, phần còn lại trong chú thích)
    "backend.core.signals.evaluator": "backend.core.signal",
    "backend.core.signals.snapshot": "backend.core.signal",
    "backend.core.signals.diagnostics": "backend.core.signal",
    "backend.core.signals.kernels": "backend.core.indicator",
    "backend.core.strategy.pydsl": "backend.core.signal",
    "backend.core.strategy.pydsl.parser": "backend.core.signal",
    "backend.core.strategy.pydsl.program": "backend.core.signal",
    "backend.core.strategy.pydsl.errors": "backend.core.signal",
    "backend.core.strategy.pydsl.explain": "backend.core.signal",
    "backend.core.strategy.pydsl.spec": "backend.core.indicator",
    "backend.core.strategy.pydsl.features": "backend.core.indicator",
    "backend.core.strategy.pydsl.ops": "backend.core.indicator",
    "backend.core.strategy.pydsl.profiles": "backend.core.backtest",   # (build_plan, Plan, ...); constants -> backend.core.params
    "backend.core.metrics.returns": "backend.metrics.metrics",
    "backend.core.metrics.portfolio": "backend.metrics.metrics",
    "backend.core.metrics.trades": "backend.metrics.trades",
    "backend.core.metrics.diagnose": "backend.metrics.trades",
    "backend.core.metrics.series_stages": "backend.metrics.charts",
    "backend.core.metrics.diagnose_inputs": "backend.metrics.trades",   # (market_series); rest -> backend.optimize.process.tasks
    "backend.core.analytics.dashboard": "backend.metrics.charts",
    "backend.core.analytics.signal_explain": "backend.metrics.charts",
    "backend.core.analytics.feeds": "backend.metrics.charts",
    "backend.core.analytics.insights": "backend.metrics.charts",
    "backend.core.analytics.user_alphas": "backend.optimize.book.registry",
    "backend.core.analytics.strategy_doc": "backend.optimize.book.registry",
    "backend.core.analytics.top_agents": "backend.optimize.book.registry",
    "backend.optimize.registry": "backend.optimize.book.registry",
    "backend.utils.engine_version": "backend.optimize.book.registry",
    "backend.optimize.funnel.antiluck": "backend.carlo.carlo",   # (DSR, effective_trials); backend.wfa.wfa (pbo_cscv, align_daily, neighbours)
    "backend.verdict.verdict": "backend.carlo.carlo",   # (same split as antiluck; diagnostics -> backend.metrics.trades; insights -> backend.metrics.charts)
    "backend.core.regime.classifier": "backend.regime.regime",
    "backend.core.regime.learn": "backend.regime.regime",
    "backend.core.regime.report": "backend.optimize.process.tasks",   # (run_job -> run_regime_report)
    "backend.core.data.loader": "backend.crawl.store",
    "backend.core.data.resampler": "backend.crawl.store",
    "backend.core.data.quality_gate": "backend.crawl.store",
    "backend.core.data.promote": "backend.crawl.store",
    "backend.core.data.shared": "backend.crawl.store",
    "backend.db.data_layout": "backend.crawl.store",
    "backend.db.local_pkl": "backend.crawl.store",
    "backend.utils.lru": "backend.crawl.store",
    "backend.utils.jsonsafe": "backend.crawl.store",
    "backend.core.data.crawler": "backend.crawl.cex",
    "backend.core.data.okx_crawler": "backend.crawl.cex",   # (crawl->okx_crawl, crawl_funding->okx_crawl_funding, run_job->okx_run_job, DEFAULT_CACHE_DIR->OKX_DEFAULT_CACHE_DIR)
    "backend.core.data.tick_crawler": "backend.crawl.dex",
    "backend.db.tick_storage": "backend.crawl.dex",
    "backend.api.routers.alphas": "backend.routes.alpha",
    "backend.api.routers.book": "backend.routes.optimize",
    "backend.api.routers.chart": "backend.routes.alpha",
    "backend.api.routers.custom": "backend.routes.alpha",
    "backend.api.routers.data": "backend.routes.data",
    "backend.api.routers.education": "backend.routes.alpha",
    "backend.api.routers.funnel": "backend.routes.optimize",
    "backend.api.routers.live": "backend.routes.live",
    "backend.api.routers.market": "backend.routes.data",
    "backend.api.routers.portfolio": "backend.routes.optimize",
    "backend.api.routers.strategies": "backend.routes.alpha",
    "backend.api.modes": "backend.routes.process",
    "backend.api.jobs.batch": "backend.optimize.process.process",   # + backend.routes.process
    "backend.api.jobs.runner": "backend.optimize.process.process",
    "backend.utils.jobs": "backend.optimize.process.process",
    "backend.utils.memwatch": "backend.optimize.process.workers",
    "backend.utils.parallel": "backend.optimize.process.workers",
    "backend.optimize.shared": "backend.optimize.search.evaluate",
    "backend.optimize.funnel.evaluate": "backend.optimize.search.evaluate",   # (make_engine -> make_engine_from_dict)
    "backend.optimize.funnel.generate": "backend.optimize.search.generate",
    "backend.optimize.funnel.gates": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.sizing": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.stats": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.estimate": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.orchestrator": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.promote": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.publish": "backend.optimize.funnel.stages",   # (*_DEFAULTS, run_funnel_*)
    "backend.optimize.funnel.recompute": "backend.optimize.funnel.stages",
    "backend.optimize.funnel.run": "backend.optimize.funnel.stages",
    "backend.optimize.store": "backend.optimize.funnel.storage",   # (_SCHEMA->_RESULTS_SCHEMA, _dumps->_results_dumps)
    "backend.optimize.revalidate": "backend.optimize.book.registry",   # (run_job->run_alpha_revalidate, DEFAULTS->ALPHA_REVALIDATE_DEFAULTS, wfa->wfa_check)
    "backend.wfa.walk_forward": "backend.wfa.wfa",
    "backend.wfa.run": "backend.optimize.process.tasks",   # (run_book_wfa, BOOK_WFA_DEFAULTS)
    "backend.carlo.monte_carlo": "backend.carlo.carlo",
}


# Pickle cũ lưu lớp ở module KHÔNG còn chứa lớp đó mà module VẪN tồn tại (nên không thể đổi cả module qua OLD_MODULES): (module, tên lớp) -> module hiện tại.
# live/paper.py nay là hồ sơ môi trường paper; PaperBook / KernelPaperBook / _SlotRO đã chuyển về core/backtest.py.
OLD_CLASSES: Dict[Tuple[str, str], str] = {
    ("backend.live.paper", "PaperBook"): "backend.core.backtest",
    ("backend.live.paper", "KernelPaperBook"): "backend.core.backtest",
    ("backend.live.paper", "_SlotRO"): "backend.core.backtest",
}


class StateUnpickler(pickle.Unpickler):
    """Unpickler DUY NHẤT cho trạng thái bot. Mọi global được đổi đường dẫn module qua OLD_MODULES rồi mới tra.
    bag=False (mặc định): nạp lớp THẬT (load_pickle: paper.pkl / unified.pkl của bóng sim, load_paper_state cho routes/live.py).
    bag=True: nạp hạn chế (load_old) — chỉ lớp cũ trong _OLD_NAMES, thành _Bag; global khác -> UnpicklingError."""

    def __init__(self, file, bag: bool = False, **kw):
        super().__init__(file, **kw)
        self._bag = bag

    def find_class(self, module: str, name: str):
        module = OLD_MODULES.get(module, module)
        if not self._bag:
            return super().find_class(OLD_CLASSES.get((module, name), module), name)
        if module == "collections" and name == "deque":
            return collections.deque
        if module == "builtins" and name == "getattr":
            return _safe_getattr
        if module.startswith(_MODULE_PREFIXES) and name in _OLD_NAMES:
            return _bag_class(module, name)
        raise pickle.UnpicklingError(f"pickle cũ: không cho phép global {module}.{name}")

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("pickle trạng thái bot: persistent id không được hỗ trợ")


def load_state(path: str) -> Any:
    """Nạp trạng thái bot (pickle) thành đối tượng THẬT, đường dẫn module cũ đổi qua OLD_MODULES."""
    with open(path, "rb") as fh:
        return StateUnpickler(fh).load()


def load_old(path: str) -> _Bag:
    """Nạp paper.pkl cũ bằng unpickler hạn chế -> _Bag của PaperBook."""
    with open(path, "rb") as fh:
        obj = StateUnpickler(fh, bag=True).load()
    if not isinstance(obj, _Bag) or "books" not in obj.__dict__ and "runner" not in obj.__dict__:
        raise MigrationError("paper.pkl không phải PaperBook cũ")
    return obj


# ── đọc định dạng cũ ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _ledger_of(old: _Bag) -> _Bag:
    return old.runner.account if "runner" in old.__dict__ else old.ledger


def _port(old: _Bag) -> Dict[str, Any]:
    """Trường danh mục (Runner hoặc PaperBook phẳng)."""
    return (old.runner if "runner" in old.__dict__ else old).__dict__


def kind(old: _Bag) -> str:
    return "event" if "runner" in old.__dict__ else "tracker"


def _slot_fields(tr: _Bag) -> Dict[str, Any]:
    """Trường chuẩn hoá của một slot (tracker hoặc manager+book) -> dict phẳng; thiếu -> bỏ."""
    d = dict(tr.__dict__)
    bk = d.get("book")
    if isinstance(bk, _Bag):                      # manager: qty / avg / orders... nằm ở book
        for k, v in bk.__dict__.items():
            d.setdefault(k, v)
    return d


def old_slots(old: _Bag) -> List[Tuple[int, str, str, Dict[str, Any]]]:
    """[(book_index, symbol, strategy, side, fields)] theo thứ tự slot cũ (tài sản, rồi chiến lược)."""
    out = []
    for b, bk in enumerate(_port(old)["books"]):
        for e in bk["entries"]:
            out.append((b, bk["symbol"], e["strategy"], e["side"], _slot_fields(e["tracker"])))
    return out


class _Duck:
    """Giả lập SlotSpec để pack_slots đọc: thuộc tính chuẩn hoá lấy từ slot cũ."""

    def __init__(self, f: Dict[str, Any], capital: float):
        sp = f.get("params")
        self.is_long = bool(f["is_long"])
        self.market = f["market"]
        self.fee_rate, self.maker_fee_rate, self.slippage_rate, self.mmr = f["fee_rate"], f["maker_fee_rate"], f["slippage_rate"], f["mmr"]
        self.max_leverage, self.capital_usage = f["max_leverage"], f["capital_usage"]
        self.base_sl, self.base_tp, self.base_trail, self.base_trail_act = f["base_sl"], f["base_tp"], f["base_trail"], f["base_trail_act"]
        self.risk_pct, self.max_notional_pct, self.order_size_pct = f["risk_pct"], f["max_notional_pct"], f["order_size_pct"]
        self.limit_through = f["limit_through"]
        self.base_dca_steps, self.dca_mults = list(f["base_dca_steps"]), list(f["dca_mults"])
        self.timeout_ms, self.cooldown_ms, self.stop_fill = f["timeout_ms"], f["cooldown_ms"], f["stop_fill"]
        self.intrabar_path = f.get("intrabar_path") or "ohlc"
        self.exit_unit, self.sizing = f["exit_unit"], f["sizing"]
        self.max_open_trades = int(getattr(sp, "max_open_trades", 45) or 45) if sp is not None else 45
        self.entry_equity, self.max_capital, self.pos_leverage = capital, capital * self.capital_usage, f["max_leverage"]
        self.planned_risk, self.unit_pct = 0.0, 0.0
        self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct = self.base_sl, self.base_tp, self.base_trail, self.base_trail_act
        self.dca_steps = list(self.base_dca_steps)
        self.dca_ok = True


def _spec_of(sym: str, f: Dict[str, Any], capital: float):
    """SlotSpec của slot cũ: tracker mang StrategyParams -> dựng lại bằng chuẩn hoá HIỆN TẠI (SlotSpec); manager không mang params -> _Duck từ thuộc tính chuẩn hoá."""
    sp = f.get("params")
    if not isinstance(sp, _Bag):
        return _Duck(f, capital)
    import dataclasses
    from backend.core.models import PositionType
    from backend.core.params import StrategyParams
    from backend.core.position_size import SlotSpec
    names = {x.name for x in dataclasses.fields(StrategyParams)}
    params = StrategyParams(**{k: v for k, v in sp.__dict__.items() if k in names})
    try:
        return SlotSpec(0, 0, sym, f.get("flow_name") or params.name, params, PositionType.LONG if f["is_long"] else PositionType.SHORT, capital)
    except ValueError as e:
        raise MigrationError(f"tham số trong pickle không hợp lệ: {e}")


def _specs(old: _Bag, capital: float) -> list:
    return [_spec_of(sym, f, capital) for _, sym, _, _, f in old_slots(old)]


def _new_book(cls, specs, slots, symbols, base_frame, capital, risk, trade_start):
    """Cùng thân với KernelBook.__init__ nhưng từ SlotSpec (hoặc duck) có sẵn."""
    kb = cls.__new__(cls)
    kb._setup(list(symbols), slots, base_frame, float(capital), dict(risk), int(trade_start), False, 0)
    P, PI, F, I = bt.pack_slots(specs)
    F[:, bt.F_ENTRY_EQ] = float(capital)
    for k, tr in enumerate(specs):
        F[k, bt.F_MAXCAP] = float(capital) * tr.capital_usage
    kb.P, kb.PI, kb.F, kb.I = P, PI, F, I
    kb.cfg_i, kb.cfg_f = bt._cfg_arrays(capital, risk, trade_start, kb.MTM_SAMPLE_MINUTES * 60_000)
    kb.PS, kb.PSI, kb.LPX = bt.new_portfolio_state(len(symbols), float(capital))
    kb.LG = np.array([float(capital), 0.0, float(capital)])
    kb.G = np.zeros(bt.NG, dtype=np.int64)
    kb._alloc_buffers(max(64, 8 * len(specs)), max(256, 32 * len(specs)), 256)
    kb.record_full = False
    kb._specs = None
    kb._arm_adm(0)
    return kb


def _meta(old: _Bag) -> Tuple[List[str], List[Dict[str, Any]], float]:
    symbols = [bk["symbol"] for bk in _port(old)["books"]]
    slots = [{"book": b, "symbol": s, "strategy": st, "side": sd} for b, s, st, sd, _ in old_slots(old)]
    return symbols, slots, float(_ledger_of(old).initial)


def kernel_book_from_old(old: _Bag, base_frame: str, cls=None, trade_start: Optional[int] = None) -> "bt.KernelBook":
    """KernelBook có tham số = tham số CHUẨN HOÁ trong pickle cũ (không dùng book.json) + trạng thái đã chuyển. Dùng cho test và công cụ."""
    cls = cls or KernelPaperBook
    symbols, slots, capital = _meta(old)
    specs = _specs(old, capital)
    kb = _new_book(cls, specs, slots, symbols, base_frame, capital, dict(_port(old)["risk"]),
                   int(_port(old).get("trade_start", 0)) if trade_start is None else trade_start)
    return apply_state(old, kb)


def check_params(old: _Bag, fresh: "bt.KernelBook") -> None:
    """Tham số trong pickle (P / PI / cấu hình rủi ro, danh tính slot) phải TRÙNG sổ mới dựng từ cấu hình hiện tại, nếu không ParamsMismatch."""
    symbols, slots, capital = _meta(old)
    if symbols != fresh.symbols or [(s["symbol"], s["strategy"], s["side"]) for s in slots] != [(s["symbol"], s["strategy"], s["side"]) for s in fresh.slots]:
        raise ParamsMismatch("tài sản / chiến lược khác sổ hiện tại")
    specs = _specs(old, capital)
    ref = _new_book(type(fresh), specs, slots, symbols, fresh.base_frame, capital, dict(_port(old)["risk"]), int(_port(old).get("trade_start", 0)))
    if ref.P.shape != fresh.P.shape or not np.array_equal(ref.P, fresh.P):
        raise ParamsMismatch("tham số số (phí / SL / TP / DCA / rủi ro...) khác chiến lược hiện tại")
    keep = [c for c in range(bt.NPI) if c != bt.PI_MAXOPEN]       # max_open_trades không có trong PositionManager cũ và kernel không đọc để quyết định
    if not np.array_equal(ref.PI[:, keep], fresh.PI[:, keep]):
        raise ParamsMismatch("tham số nguyên (hướng / thị trường / timeout / cooldown / đường giá...) khác chiến lược hiện tại")
    if not (np.array_equal(ref.cfg_i[:5], fresh.cfg_i[:5]) and np.array_equal(ref.cfg_f, fresh.cfg_f)):
        raise ParamsMismatch("giới hạn rủi ro danh mục khác cấu hình hiện tại")


# ── ghi trạng thái vào KernelBook ──────────────────────────────────────────────────────────────────────────────────────────
def _f(v, default=0.0) -> float:
    return float(default if v is None else v)


def apply_state(old: _Bag, kb: "bt.KernelBook") -> "bt.KernelBook":
    """Ghi trạng thái của PaperBook cũ vào kb (tham số đã khớp). Trả kb."""
    port, led = _port(old), _ledger_of(old)
    slots = old_slots(old)
    if len(slots) != kb.nt:
        raise ParamsMismatch("số slot khác")
    ml = (kb.P.shape[1] - bt.P_FIXED) // 2
    F, I, G, PS, PSI = kb.F, kb.I, kb.G, kb.PS, kb.PSI
    equity = _f(led.equity)
    kb.LG[:] = (equity, _f(led.reserved), _f(led.__dict__.get("peak"), max(_f(led.initial), equity)))
    G[bt.G_REJ] = int(led.__dict__.get("rejected", 0) or 0)
    n_open = n_ord = 0
    for k, (b, sym, st, side, f) in enumerate(slots):
        steps = [float(x) for x in (f.get("dca_steps") or [])]
        if len(steps) > ml:
            raise ParamsMismatch("số tầng DCA nhiều hơn tham số hiện tại")
        for col, name in ((bt.F_QTY, "qty"), (bt.F_AVG, "avg"), (bt.F_MU, "margin_used"), (bt.F_FP, "fees_paid"), (bt.F_LAST_FILL, "last_fill"),
                          (bt.F_NEXT, "next_margin"), (bt.F_PEAK, "peak"), (bt.F_MAE, "mae_usd"), (bt.F_RES_HERE, "reserved_here"), (bt.F_FUND, "funding_paid"),
                          (bt.F_ENTRY_EQ, "entry_equity"), (bt.F_MAXCAP, "max_capital"), (bt.F_POS_LEV, "pos_leverage"), (bt.F_PLANNED, "planned_risk"),
                          (bt.F_SL, "sl_pct"), (bt.F_TP, "tp_pct"), (bt.F_TRAIL, "trail_pct"), (bt.F_TACT, "trail_activation_pct"), (bt.F_UNIT, "unit_pct")):
            if f.get(name) is not None:
                F[k, col] = float(f[name])
        F[k, bt.F_PVOL] = float(f["pending_vol"]) if f.get("pending_vol") is not None else np.nan
        F[k, bt.F_DS0:bt.F_DS0 + ml] = 0.0
        for j, s in enumerate(steps):
            F[k, bt.F_DS0 + j] = s
        I[k, bt.I_NST] = len(steps)
        opened = bool(f.get("is_open"))
        I[k, bt.I_OPEN], I[k, bt.I_PE], I[k, bt.I_PX] = int(opened), int(bool(f.get("pending_entry"))), int(bool(f.get("pending_exit")))
        I[k, bt.I_LAYERS], I[k, bt.I_ENTRY_T] = int(f.get("layer_count") or 0), int(f.get("entry_time") or 0)
        lc = f.get("last_close_time")
        I[k, bt.I_HASLC], I[k, bt.I_LASTCLOSE] = (0, 0) if lc is None else (1, int(lc))
        I[k, bt.I_DCAREJ], I[k, bt.I_SKIP] = int(f.get("dca_rejected") or 0), int(f.get("skipped_no_vol") or 0)
        I[k, bt.I_DCAOK] = int(bool(f.get("dca_ok", True)))
        I[k, bt.I_BLK], I[k, bt.I_POS] = -2, -1
        if opened:
            n_open, n_ord = _write_position(kb, k, f, n_open, n_ord)
    G[bt.G_NPOS], G[bt.G_NORD], G[bt.G_NCL] = n_open, n_ord, 0
    G[bt.G_RISKMIN] = G[bt.G_ATT] = int(port.get("rejected_for_risk") or 0)
    for b in range(kb.nb):
        kb.LPX[b] = [float(port[n][b]) for n in ("last_close", "last_low", "last_high", "last_open")]
    PS[bt.PS_PEAK_MTM] = _f(port.get("peak_mtm"), kb.capital)
    halted = port.get("halted_at")
    PSI[bt.PSI_HALTED], PSI[bt.PSI_HALT_AT] = (0, bt.NONE_I) if halted is None else (1, int(halted))
    PSI[bt.PSI_RUIN_AT], PSI[bt.PSI_HAS_SMP], PSI[bt.PSI_G] = bt.NONE_I, 0, 0
    PSI[bt.PSI_BUSY] = int(any(I[k, bt.I_OPEN] == 1 or I[k, bt.I_PE] == 1 for k in range(kb.nt)))
    lt = port.get("last_t")
    kb._last_t = None if lt is None else int(lt)
    PSI[bt.PSI_LAST_T] = 0 if lt is None else int(lt)
    kb.trades = [dict(t) for t in port.get("trades", [])]
    kb.mtm()
    return kb


def _write_position(kb, k: int, f: Dict[str, Any], n_open: int, n_ord: int) -> Tuple[int, int]:
    pos = f.get("position")
    if not isinstance(pos, _Bag):
        raise MigrationError(f"slot {k} đang mở nhưng không có PositionModel")
    pd_ = pos.__dict__
    if n_open >= kb.outF.shape[0]:
        raise MigrationError("quá nhiều vị thế mở cho bộ đệm")
    rid = pd_.get("result_id")
    orders = [o for o in (f.get("orders") or []) if o.__dict__.get("position_id") == rid]
    if len(orders) + n_ord > kb.ordF.shape[0]:
        raise MigrationError("quá nhiều lệnh của vị thế mở cho bộ đệm")
    outF, outI, ordF, ordI = kb.outF, kb.outI, kb.ordF, kb.ordI
    row = n_open
    long_ = bool(f["is_long"])
    outF[row, bt.O_ENTER_PRICE] = float(pd_["enter_price"])
    outF[row, bt.O_ENTRY_MARGIN] = _f(pd_.get("entry_margin_usd"))
    outF[row, bt.O_ENTRY_NOTIONAL] = _f(pd_.get("entry_notional_usd"))
    outF[row, bt.O_ENTRY_FEE] = _f(pd_.get("entry_fee_usd"))
    outF[row, bt.O_MAXP] = _f(pd_.get("max_price"), pd_["enter_price"])
    outF[row, bt.O_MINP] = _f(pd_.get("min_price"), pd_["enter_price"])
    outF[row, bt.O_UNIT] = _f(pd_.get("unit_pct"))
    outF[row, bt.O_LEVUSED] = _f(pd_.get("leverage_used"), 1.0)
    outF[row, bt.O_RISK] = _f(pd_.get("risk_usd"))
    sr = pd_.get("start_reason")
    outI[row, bt.OI_TR], outI[row, bt.OI_ENTER_T] = k, int(pd_["enter_time"])
    outI[row, bt.OI_STATUS], outI[row, bt.OI_LAYERS] = 1, int(pd_.get("layers") or 1)
    outI[row, bt.OI_REASON] = 0
    outI[row, bt.OI_START] = bt.REASONS.index(sr) if sr in bt.REASONS else 0
    outI[row, bt.OI_FIRST_ORD] = n_ord
    slip_rate = _f(f.get("slippage_rate"))
    if not orders:                                     # pickle thiếu lịch sử lệnh: dựng lệnh vào từ vị thế
        orders = [None]
    for o in orders:
        if o is None:
            price, qty, fee, phase, t, liq, slip = float(pd_["enter_price"]), _f(f.get("qty")), _f(pd_.get("entry_fee_usd")), 0, int(pd_["enter_time"]), 2, slip_rate
        else:
            od = o.__dict__
            liq = _LIQ.get(od.get("liquidity", "taker"), 2)
            price, qty, fee, phase, t = float(od["order_price"]), float(od["qty"]), _f(od.get("fee_usd")), int(od.get("phase") or 0), int(od["order_time"])
            slip = _f(od.get("slippage"), slip_rate if liq == 2 else 0.0)
        raw = price / (1.0 + slip) if long_ else price / (1.0 - slip)
        j = n_ord
        ordF[j, bt.OR_PRICE], ordF[j, bt.OR_QTY], ordF[j, bt.OR_FEE], ordF[j, bt.OR_RAW], ordF[j, bt.OR_SLIP] = price, qty, fee, raw, slip
        ordI[j, bt.ORI_POS], ordI[j, bt.ORI_TIME], ordI[j, bt.ORI_PHASE], ordI[j, bt.ORI_EXIT], ordI[j, bt.ORI_LIQ] = row, t, phase, 0, liq
        n_ord += 1
    kb.I[k, bt.I_POS] = row
    return n_open + 1, n_ord


# ── đọc tóm tắt (API) ──────────────────────────────────────────────────────────────────────────────────────────────────────
def read_summary(path: str) -> Dict[str, Any]:
    """Cho API: {"trades": [...], "positions": [...]} từ paper.pkl cũ (unpickler hạn chế, đúng khuôn Runner.positions)."""
    old = load_old(path)
    port = _port(old)
    pos = []
    for b, sym, st, side, f in old_slots(old):
        if f.get("is_open"):
            px = float(port["last_close"][b])
            move = (px - f["avg"]) if f.get("is_long", side == "LONG") else (f["avg"] - px)
            pos.append({"symbol": sym, "strategy": st, "side": side, "qty": float(f["qty"]), "avg": float(f["avg"]), "layers": int(f["layer_count"]),
                        "entry_time": int(f["entry_time"]), "unrealized": float(f["qty"] * move - f["fees_paid"])})
    return {"trades": list(port.get("trades", [])), "positions": pos}


# ══════════════════════════════════════════════════════════════════════════
# PHẦN C — BOT: Bot (legacy) / UnifiedBot, run_job (trước đây live/bot.py)
#
# Bot giao dịch theo sổ đã xuất bản (E9-S1/S2/S5) — job API `live_bot`. Sàn triển khai: OKX (Binance chỉ để tham khảo / đối chiếu).
# Mọi chiến lược của sổ: theo xu hướng lẫn DCA.
#
# Chế độ:
#   paper  dữ liệu thị trường THẬT của sàn (REST công khai); khớp lệnh bằng KernelPaperBook = KernelBook (kernel của backtest, từng nến; P9.4b T7)
#          (test: cùng nến + tín hiệu -> cùng lệnh với PortfolioEngine, gồm DCA, trailing, kill switch). Nến bỏ lỡ được chạy bù theo thứ tự.
#          Trạng thái: paper_state.npz + paper.json (KernelBook.save/load); paper.pkl cũ được chuyển một lần (PHẦN B: load_old / apply_state) rồi cất đi.
#   demo   OKX Demo Trading (khoá demo, vốn ảo) — "testnet / live mô phỏng".
#   live   OKX tài khoản thật: CÙNG mã với demo, chỉ khác khoá (NORA_OKX_DEMO=0) và cần confirm_live=true.
# demo/live: vào lệnh MARKET đầu nến kế tín hiệu; tầng DCA = lệnh post-only (khớp maker như engine) đặt sẵn cả thang theo đúng bước/hệ số;
# SL = lệnh điều kiện reduce-only và TP = limit reduce-only tính từ GIÁ TRUNG BÌNH, đặt lại mỗi khi một tầng DCA khớp; trailing / timeout /
# tín hiệu thoát = đóng market ở nến kế. Đối soát vị thế với sàn mỗi bước; chạy kèm PaperBook "bóng" trên cùng nến để đối chiếu thật / mô phỏng.
# Khối lượng = PositionTracker._risk_margin / order_size_pct (cùng mã engine); giới hạn danh mục và kill switch như PortfolioEngine.
#
# engine (tham số job): rỗng = mặc định của chế độ (paper legacy, demo/live unified); "legacy" = lớp Bot ở đầu file, không đổi. "unified" (chỉ demo/live, OKX) = UnifiedBot (mục "Bot sàn trên kiến trúc THỐNG NHẤT" cuối file): Runner + PositionManager + OkxVenue + sổ vốn ảo
# (ADR-P6 P6.8b, D1–D5) — trạng thái ở thư mục riêng `<sàn>_<chế độ>_unified`. Paper + unified = chạy đường Bot thường (PaperBook đã là đường event).
#
# Thứ tự: Bot + run_job (đầu) -> UnifiedBot, _ExecVenue, check_book_d1 (cuối). Phần tín hiệu (klines_frame, evaluate_signals, ...) ở core/backtest.py.
# Các file live/{bot,unified,signals,okx,okx_venue,exchange,secrets,state_migrate,compare}.py đã xoá (không còn alias); pickle cũ lưu đường dẫn đó nạp được nhờ OLD_MODULES (PHẦN B).
# ══════════════════════════════════════════════════════════════════════════


DEFAULTS = {"mode": "paper", "venue": "okx", "once": False, "max_steps": 0, "capital": DEFAULT_CAPITAL, "state_dir": "", "confirm_live": False,
            "book": "main", "engine": "", "equity_drift_halt_pct": 5.0}
ENGINES = ("legacy", "unified")   # legacy = Bot tự đặt lệnh (code cũ); unified = Runner + PositionManager + OkxVenue (UnifiedBot cuối file, ADR-P6 P6.8b)
BOOKS = ("main", "explore")     # main = data/alpha/book.json (READY_FOR_TESTNET); explore = data/alpha/explore/book.json (EXPLORE_DEMO)
EXEC_MODES = ("demo", "live")   # đặt lệnh thật trên sàn: demo = OKX Demo Trading (vốn ảo), live = tài khoản thật
KLINE_LIMIT = 1500
WATCH_S = 10.0     # giây giữa hai lần đối soát nhanh của bot sàn (tầng DCA khớp -> SL/TP mới; sàn đóng lệnh -> ghi nhận)


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_book(alphas: Optional[str] = None, kind: str = "main", mode: str = "paper") -> Dict[str, Any]:
    """main: sổ đã kiểm định (READY_FOR_TESTNET). explore: sổ thử nghiệm (EXPLORE_DEMO) — chỉ paper/demo, không bao giờ live."""
    from backend.crawl.store import alpha_dir as alphas_dir
    from backend.optimize.book.registry import EXPLORE_STATUS
    if kind not in BOOKS:
        raise SystemExit(f"book phải là một trong {BOOKS}")
    base = alphas or alphas_dir()
    if kind == "explore":
        base = os.path.join(base, "explore")
    with open(os.path.join(base, "book.json"), encoding="utf-8") as fh:
        book = json.load(fh)
    want = EXPLORE_STATUS if kind == "explore" else "READY_FOR_TESTNET"
    if book.get("status") != want:
        raise SystemExit(f"{base}/book.json trạng thái {book.get('status')} — sổ {kind} cần {want}")
    if kind == "explore" and mode == "live":
        raise SystemExit("sổ thử nghiệm (chưa kiểm định đủ) không bao giờ chạy live — chỉ paper/demo")
    return book


def book_strategies(book: Dict[str, Any]) -> List[Dict[str, Any]]:
    from backend.optimize.book.build import lift_frames
    from backend.core.params import materialize
    from backend.optimize.book.build import BY_ID
    by = BY_ID
    tf = book.get("timeframe", "1m")
    return [materialize(by[s["id"]], lift_frames(by[s["id"]], s["params"], tf), risk_per_trade_pct=book["risk_per_trade_pct"],
                        stop_fill="level") for s in book["strategies"]]


def _archive_stale_state(sdir: str, spath: str, book: Dict[str, Any]) -> None:
    """Trạng thái của sổ KHÁC (book.generated_at khác) -> cất state.json / paper.pkl / events.jsonl vào sdir/archive_<giờ>/ (không xoá)."""
    names = [n for n in ("state.json", "paper.pkl", "paper.json", "paper_state.npz", "unified.pkl", "events.jsonl") if os.path.isfile(os.path.join(sdir, n))]
    if not names:
        return
    old = None
    if os.path.isfile(spath):
        with open(spath, encoding="utf-8") as fh:
            old = json.load(fh).get("book")
    if old == book.get("generated_at"):
        return
    dst = os.path.join(sdir, time.strftime("archive_%Y%m%d_%H%M%S"))
    os.makedirs(dst, exist_ok=True)
    for n in names:
        os.replace(os.path.join(sdir, n), os.path.join(dst, n))
    print(f"trạng thái của sổ cũ ({old}) -> {dst}", flush=True)


def load_pickle(path: str, log, what: str) -> Any:
    """Nạp pickle trạng thái; file hỏng / không đọc được -> cất sang <path>.corrupt_<giờ>, ghi sự kiện warn, trả None (bắt đầu lại)."""
    if not os.path.isfile(path):
        return None
    try:
        return load_state(path)               # StateUnpickler: đường dẫn module cũ (OLD_MODULES) nạp được
    except Exception as e:                    # EOFError, UnpicklingError, AttributeError (class đổi tên), ImportError ...
        dst = f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"
        os.replace(path, dst)
        log({"t": _now_ms(), "kind": "warn", "msg": f"{what} hỏng ({type(e).__name__}: {e}) — đã cất sang {dst}, bắt đầu lại từ trạng thái mới"})
        return None


def save_kernel_book(kb: "bt.KernelBook", dirpath: str) -> None:
    """paper_state.npz (mọi mảng, đã nén) + paper.json (phiên bản, tài sản, chiến lược, băm tham số, lệnh đã đóng, vị thế); không pickle lớp.
    Trạng thái thuần do `KernelBook.state_arrays()` dựng; đây là phần ghi tệp nguyên tử (tệp tạm + os.replace)."""
    os.makedirs(dirpath, exist_ok=True)
    arrays, meta = kb.state_arrays()
    tmp = os.path.join(dirpath, "paper_state.tmp.npz")
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, os.path.join(dirpath, "paper_state.npz"))
    tmpj = os.path.join(dirpath, "paper.json.tmp")
    with open(tmpj, "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    os.replace(tmpj, os.path.join(dirpath, "paper.json"))


def load_kernel_book(dirpath: str, strategies: Optional[List[Dict[str, Any]]] = None, cls=None) -> "bt.KernelBook":
    """Nạp sổ đã lưu bởi save_kernel_book (mặc định thành KernelPaperBook). strategies (tuỳ chọn): so băm tham số với chiến lược hiện tại — lệch thì ValueError."""
    with open(os.path.join(dirpath, "paper.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    cls = cls or KernelPaperBook
    cls.check_state_meta(meta)                    # sai phiên bản / loại thì báo trước khi đụng tới npz
    z = np.load(os.path.join(dirpath, "paper_state.npz"), allow_pickle=False)
    return cls.from_state(meta, z, strategies)


def _save_paper(paper, sdir: str, pkl: str) -> None:
    """KernelBook -> paper_state.npz + paper.json (không pickle); bóng PaperBook cũ của UnifiedBot (T8/T9) vẫn pickle vào paper.pkl."""
    if hasattr(paper, "state_arrays"):
        save_kernel_book(paper, sdir)
        return
    with open(pkl + ".tmp", "wb") as fh:
        pickle.dump(paper, fh)
    os.replace(pkl + ".tmp", pkl)


def _archive_files(sdir: str, names: List[str], tag: str) -> str:
    dst = os.path.join(sdir, time.strftime(f"archive_{tag}_%Y%m%d_%H%M%S"))
    os.makedirs(dst, exist_ok=True)
    for n in names:
        if os.path.isfile(os.path.join(sdir, n)):
            os.replace(os.path.join(sdir, n), os.path.join(dst, n))
    return dst


def load_paper(sdir: str, book: Dict[str, Any], capital: float, log):
    """Sổ paper KernelBook của bot (không unified): paper.json + npz -> nạp (tham số phải khớp sổ hiện tại); không có -> chuyển paper.pkl cũ (PHẦN B)
    (khớp tham số thì chuyển, pickle cũ cất vào archive_p94b_*; lệch / hỏng thì cất pickle, bắt đầu sạch, ghi cảnh báo); không có gì -> None (Bot dựng sổ mới)."""
    strategies = book_strategies(book)
    symbols = [s.split("@")[0] for s in book["universe"]]
    sim_tf = book.get("sim_timeframe") or ("15m" if book.get("timeframe") == "1h" else book.get("timeframe", "1m"))
    state_files = ["paper.json", "paper_state.npz"]
    if os.path.isfile(os.path.join(sdir, "paper.json")):
        try:
            return load_kernel_book(sdir, strategies)
        except Exception as e:                    # băm tham số lệch (cấu hình đổi) / tệp hỏng: cất, bắt đầu sạch
            dst = _archive_files(sdir, state_files, "paper")
            log({"t": _now_ms(), "kind": "warn", "msg": f"paper.json không nạp được ({type(e).__name__}: {e}) — đã cất sang {dst}, bắt đầu lại từ trạng thái mới"})
            return None
    pkl = os.path.join(sdir, "paper.pkl")
    if os.path.isfile(pkl):
        try:
            old = load_old(pkl)
            fresh = KernelPaperBook(strategies, symbols, sim_tf, float(_ledger_of(old).initial), book["risk"], 0)
            check_params(old, fresh)
            paper = apply_state(old, fresh)
        except Exception as e:                    # ParamsMismatch / MigrationError / pickle lạ
            dst = _archive_files(sdir, ["paper.pkl"], "p94b")
            log({"t": _now_ms(), "kind": "warn", "msg": f"paper.pkl cũ không chuyển được sang KernelBook ({type(e).__name__}: {e}) — đã cất sang {dst}, bắt đầu lại từ trạng thái mới"})
            return None
        dst = _archive_files(sdir, ["paper.pkl"], "p94b")
        log({"t": _now_ms(), "kind": "info", "msg": f"paper.pkl cũ đã chuyển sang KernelBook (bản gốc cất ở {dst})"})
        return paper
    return None


def load_paper_state(state_dir: str):
    """Sổ paper ĐÃ LƯU của một thư mục trạng thái bot (cho API đọc, không chạy): paper.json + paper_state.npz (KernelPaperBook, bot không unified từ P9.4b T7)
    nếu có, ngược lại paper.pkl (bóng PaperBook của UnifiedBot, hoặc bản trước T7) qua StateUnpickler. Không có file nào -> OSError (FileNotFoundError);
    tệp hỏng -> ValueError / KeyError / pickle.UnpicklingError / EOFError / AttributeError. Trả đối tượng có .trades và .positions()."""
    if os.path.isfile(os.path.join(state_dir, "paper.json")):
        return load_kernel_book(state_dir)
    with open(os.path.join(state_dir, "paper.pkl"), "rb") as fh:
        return StateUnpickler(fh).load()


class State:
    def __init__(self, path: str):
        self.path = path
        # đỉnh vốn chỉ lấy từ vốn sàn ĐO ĐƯỢC (0 = chưa đo): vốn danh nghĩa `capital` có thể khác số dư tài khoản -> kill switch giả
        self.d: Dict[str, Any] = {"positions": {}, "last_close": {}, "peak_equity": 0.0, "halted": False, "last_bar": None,
                                  "trades": [], "external": []}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.d.update(json.load(fh))

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.d, fh, ensure_ascii=False, indent=1, default=float)
        os.replace(tmp, self.path)


class Bot:
    def __init__(self, book: Dict[str, Any], mode: str, client, state: State, log, filters: Optional[Dict[str, Any]] = None,
                 paper=None, capital: float = DEFAULT_CAPITAL):
        self.book, self.mode, self.client, self.state, self.log = book, mode, client, state, log
        self.tf = book.get("timeframe", "1m")
        self.sim_tf = book.get("sim_timeframe") or ("15m" if self.tf == "1h" else self.tf)
        self.strategies = book_strategies(book)
        self.symbols = [s.split("@")[0] for s in book["universe"]]
        self.limits = book["risk"]
        self.filters = filters or {}
        self.blocked: Dict[str, str] = {}      # mã khoá API không được giao dịch (sàn báo thiếu quyền): bỏ qua tới lần khởi động sau
        self.paper = paper or KernelPaperBook(self.strategies, self.symbols, self.sim_tf, capital, self.limits)

    # ── dữ liệu ──
    def frames(self, sym: str, now: int) -> Dict[str, Any]:
        req = set(required_frames(f"{sym}@perp", self.strategies, self.tf))
        if getattr(self, "sim_tf", None) and self.sim_tf != self.tf:
            req.add(self.sim_tf)
        return {fr: klines_frame(self.client.klines(sym, fr, KLINE_LIMIT, now), now)
                for fr in sorted(req)}

    def funding(self, sym: str, since: int) -> List:
        try:
            return self.client.funding(sym, since)
        except Exception:                      # funding không lấy được: bỏ qua bước này (không chặn giao dịch)
            return []

    def event(self, kind: str, **kw) -> None:
        self.log({"t": _now_ms(), "kind": kind, **kw})

    # ── paper / bóng: chạy bù mọi nến chưa xử lý ──
    def advance_paper(self, sig: Dict[str, Dict[str, Any]], funding: Optional[Dict[str, List]] = None,
                      sub_frames: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        pb = self.paper
        pos = {sym: {int(t): i for i, t in enumerate(v["t"])} for sym, v in sig.items()}
        times = sorted({t for p in pos.values() for t in p if pb.last_t is None or t > pb.last_t})
        if pb.last_t is None:
            times = times[-1:]                 # khởi động: chỉ nến đóng mới nhất (không giao dịch lùi lịch sử)
        step_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}.get(self.tf, 3_600_000)
        closed = []
        for t in times:
            prev = pb.last_t if pb.last_t is not None else t - 1
            # Nếu có sub_frames (nến con khung 15m hoặc 1m): nạp từng nến con vào bóng sim
            sub_avail = bool(sub_frames and any(sub_frames.get(s) is not None and len(sub_frames[s]) > 0 for s in self.symbols))
            if sub_avail:
                sub_ts = sorted({int(r["open_time"]) for s in self.symbols if sub_frames.get(s) is not None
                                 for _, r in sub_frames[s][(sub_frames[s]["open_time"] >= t) & (sub_frames[s]["open_time"] < t + step_ms)].iterrows()})
                if sub_ts:
                    for sub_idx, st_t in enumerate(sub_ts):
                        sub_prev = pb.last_t if pb.last_t is not None else st_t - 1
                        bars, s_at, fund = {}, {}, {}
                        for sym in self.symbols:
                            sdf = sub_frames.get(sym)
                            if sdf is None:
                                continue
                            crow = sdf[sdf["open_time"] == st_t]
                            if crow.empty:
                                continue
                            r = crow.iloc[0]
                            bars[sym] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
                            i = pos[sym].get(t)
                            if sub_idx == 0 and i is not None:
                                s_at[sym] = _bar_sig(sig[sym], i)
                            else:
                                v_sig = sig.get(sym)
                                n_ent = len(v_sig["entries"]) if v_sig else len(self.strategies)
                                s_at[sym] = [{"match": False, "stop": False, "vol": None, "dca": True} for _ in range(n_ent)]
                            fund[sym] = [(ft, r_rate) for ft, r_rate in (funding or {}).get(sym, []) if sub_prev < ft <= st_t]
                        if bars:
                            closed += pb.step_bar(st_t, bars, s_at, fund)
                            self._after_sim_bar(st_t, bars)
                    continue

            bars, s_at, fund = {}, {}, {}
            for sym, v in sig.items():
                i = pos[sym].get(t)
                if i is None:
                    continue
                bars[sym] = (float(v["open"][i]), float(v["high"][i]), float(v["low"][i]), float(v["close"][i]))
                s_at[sym] = _bar_sig(v, i)
                fund[sym] = [(ft, r) for ft, r in (funding or {}).get(sym, []) if prev < ft <= t]
            closed += pb.step_bar(t, bars, s_at, fund)
            self._after_sim_bar(t, bars)
        return closed

    def _after_sim_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]]) -> None:
        """Móc sau mỗi nến của bóng sim (UnifiedBot xả sự kiện sim ra events.jsonl). Legacy: không làm gì."""

    # ── sàn (demo / live) ──
    def _protect(self, sym: str, p: Dict[str, Any]) -> None:
        """(Đặt lại) SL / TP từ giá trung bình hiện tại + các tầng DCA chưa khớp (chỉ khi điều kiện dồn đang cho phép: p["dca_ok"])."""
        f = self.filters.get(sym)
        rnd = f.price if f is not None else (lambda x: x)
        rq = f.qty_close if f is not None else (lambda x: x)
        sign = 1 if p["side"] == "LONG" else -1
        self.client.cancel_all(sym)
        if p["sl_pct"]:
            self.client.place_sl(sym, p["side"], rq(p["qty"]), rnd(p["avg"] * (1 - sign * p["sl_pct"] / 100.0)))
        if p["tp_pct"]:
            self.client.place_tp(sym, p["side"], rq(p["qty"]), rnd(p["avg"] * (1 + sign * p["tp_pct"] / 100.0)))
        native = getattr(self.client, "place_trailing", None)
        p["native_trail"] = bool(p.get("trail_pct")) and native is not None
        if p["native_trail"]:                          # trailing do SÀN giữ: bám đỉnh và khớp ngay trong nến như engine
            native(sym, p["side"], rq(p["qty"]), p["trail_pct"], rnd(p["avg"] * (1 + sign * p["trail_act_pct"] / 100.0)))
        p["ladder_live"] = bool(p.get("dca_ok", True))
        for lay in (p["ladder"][p["filled_layers"]:] if p["ladder_live"] else []):
            try:
                self.client.place_post_only(sym, p["side"], lay["qty"], lay["price"])
            except Exception as e:             # GTX bị từ chối (sẽ khớp ngay = taker): bỏ tầng, KHÔNG đổi sang market (E9-S2 AC2)
                self.event("skip", symbol=sym, reason=f"tầng DCA {lay['price']} bị từ chối: {e}")

    def _risk_controls(self, equity: float) -> Tuple[float, float]:
        """(trần rủi ro cho lệnh mới, hệ số rủi ro) như danh mục engine: max_open_risk_pct (Σ rủi ro tới SL của vị thế mở) và
        dd_throttle_pct (sụt so với đỉnh vốn -> thu nhỏ lệnh mới). Sàn: đỉnh = đỉnh vốn sàn (gồm lãi lỗ chưa chốt)."""
        d = self.state.d
        room, scale = float("inf"), 1.0
        cap = float(self.limits.get("max_open_risk_pct") or 0.0) / 100.0
        if cap:
            room = cap * equity - sum(float(p.get("risk_usd") or 0.0) for p in d["positions"].values())
        thr = float(self.limits.get("dd_throttle_pct") or 0.0) / 100.0
        peak = float(d.get("peak_equity") or 0.0)
        if thr and peak > 0:
            floor = float(self.limits.get("dd_throttle_floor", 0.25))
            scale = min(1.0, max(floor, 1.0 - (1.0 - equity / peak) / thr))
        return room, scale

    def _open_exec(self, sym: str, e: Dict[str, Any], i: int, price: float, equity: float, room: float, now: int) -> None:
        from backend.core.models import CapitalLedger
        tr = e["tracker"]
        vol = float(e["vol"][i]) if e["vol"] is not None else float("nan")
        if tr.exit_unit == "atr" and not vol > 0:
            return self.event("skip", symbol=sym, strategy=e["strategy"], reason="chưa có ATR")
        tr.ledger = CapitalLedger(equity)
        tr._apply_exit_unit(vol if tr.exit_unit == "atr" else 1.0)
        tr.max_leverage = tr.leverage
        tr.pos_leverage = tr.leverage
        tr.planned_risk = 0.0
        margin = tr._risk_margin() if tr.sizing == "risk" else equity * tr.order_size_pct / 100.0
        risk_room, scale = self._risk_controls(equity)
        if scale != 1.0:                               # đang sụt vốn: lệnh mới nhỏ lại
            margin, tr.planned_risk = margin * scale, tr.planned_risk * scale
        if risk_room != float("inf") and tr.planned_risk > risk_room:   # vượt trần rủi ro đang mở
            if risk_room <= 0:
                return self.event("skip", symbol=sym, strategy=e["strategy"], reason="đủ trần rủi ro đang mở của danh mục")
            margin, tr.planned_risk = margin * risk_room / tr.planned_risk, risk_room
        lev = float(tr.pos_leverage)
        notional = min(margin * lev, room)
        f = self.filters.get(sym)
        qty = f.qty(notional / price) if f is not None else notional / price
        why = f.check(qty, price) if f is not None else (None if qty > 0 else "khối lượng 0")
        if why:
            return self.event("skip", symbol=sym, strategy=e["strategy"], reason=why)
        sign = 1 if e["side"] == "LONG" else -1
        try:
            self.client.prepare(sym, int(lev))
            fill = float(self.client.market_open(sym, e["side"], qty) or price)
        except NotPermitted as ex:
            self.blocked[sym] = str(ex)[-160:]
            return self.event("warn", symbol=sym, strategy=e["strategy"],
                              reason="khoá API không có quyền giao dịch mã này — bỏ qua mã (paper vẫn theo dõi); thêm quyền rồi khởi động lại bot")
        ladder, level, m = [], fill, notional / lev
        for step, mult in zip(tr.dca_steps, tr.dca_mults):
            level = level * (1 - sign * step / 100.0)
            m *= mult
            q = f.qty(m * lev / level) if f is not None else m * lev / level
            ladder.append({"price": f.price(level) if f is not None else level, "qty": q})
        p = {"strategy": e["strategy"], "side": e["side"], "qty": qty, "avg": fill, "entry_price": fill, "entry_time": now, "leverage": int(lev),
             "sl_pct": tr.sl_pct, "tp_pct": tr.tp_pct, "trail_pct": tr.trail_pct, "trail_act_pct": tr.trail_activation_pct, "peak": fill,
             "timeout_ms": tr.timeout_ms, "ladder": ladder, "filled_layers": 0,
             "dca_ok": bool(e["dca"][i]) if e.get("dca") is not None else True, "risk_usd": tr.planned_risk}
        self.state.d["positions"][sym] = p
        self._protect(sym, p)
        self.event("open", symbol=sym, strategy=e["strategy"], side=e["side"], qty=qty, price=fill, leverage=int(lev),
                   sl_pct=round(tr.sl_pct, 4), tp_pct=round(tr.tp_pct, 4), dca_layers=len(ladder))

    def _record_close(self, sym: str, p: Dict[str, Any], reason: str, now: int) -> None:
        """Ghi lệnh đã đóng; giá đóng / lãi lỗ / phí THẬT lấy từ lịch sử vị thế của sàn (nếu sàn hỗ trợ) để so với paper."""
        rec = {**{k: p[k] for k in ("strategy", "side", "qty", "avg", "entry_time")}, "symbol": sym, "close_time": now,
               "reason": reason, "layers": 1 + p["filled_layers"], "entry_price": p.get("entry_price")}
        fetch = getattr(self.client, "closed_since", None)
        if fetch is not None:
            try:
                rec.update(fetch(sym, int(p["entry_time"])) or {})
            except Exception as e:                     # không lấy được: vẫn ghi lệnh, thiếu giá đóng thật
                self.event("warn", symbol=sym, reason=f"không đọc được lịch sử vị thế: {e}")
        self.state.d["last_close"][f"{p['strategy']}|{sym}"] = now
        self.state.d["trades"].append(rec)
        self.event("close", symbol=sym, strategy=p["strategy"], reason=reason, close_price=rec.get("close_price"), pnl=rec.get("pnl"))

    def _close_exec(self, sym: str, reason: str, now: int) -> None:
        p = self.state.d["positions"].pop(sym)
        self.client.cancel_all(sym)
        self.client.close_market(sym)
        self._record_close(sym, p, reason, now)

    def reconcile(self, now: int) -> None:
        """Vị thế sàn là sự thật: sàn đã đóng (SL/TP) -> ghi nhận; khối lượng tăng (tầng DCA khớp) -> cập nhật giá TB, đặt lại SL/TP;
        vị thế không do bot mở -> không mở thêm trên tài sản đó (E9-S1 AC5)."""
        d = self.state.d
        live = {s: v for s, v in self.client.positions().items() if abs(v[0]) > EPS}
        d["external"] = sorted(s for s in live if s not in d["positions"])
        for sym in list(d["positions"]):
            p = d["positions"][sym]
            if sym not in live:
                d["positions"].pop(sym)
                self.client.cancel_all(sym)
                self._record_close(sym, p, "Sàn đã đóng (SL/TP)", now)
                continue
            amt, entry = live[sym]
            if abs(amt) > p["qty"] * (1 + 1e-6):
                filled, cum = p["filled_layers"], p["qty"]
                while filled < len(p["ladder"]) and cum + p["ladder"][filled]["qty"] <= abs(amt) * (1 + 1e-6):
                    cum += p["ladder"][filled]["qty"]
                    filled += 1
                p.update(qty=abs(amt), avg=entry or p["avg"], filled_layers=filled)
                self._protect(sym, p)
                self.event("dca", symbol=sym, strategy=p["strategy"], layers=1 + filled, avg=p["avg"], qty=p["qty"])

    def watch(self, now: int) -> None:
        """Đối soát nhanh giữa hai nến (chỉ khi có vị thế): engine cập nhật SL/TP từ giá TB ngay khi tầng DCA khớp, nên bot cũng phải đặt lại
        ngay — để SL cũ (tính từ giá vào đầu tiên) không cắt cả rổ khi giá đi tiếp xuống."""
        if self.state.d["positions"]:
            n = len(self.state.d["trades"])
            before = {s: (p["qty"], p["filled_layers"]) for s, p in self.state.d["positions"].items()}
            self.reconcile(now)
            after = {s: (p["qty"], p["filled_layers"]) for s, p in self.state.d["positions"].items()}
            if before != after or len(self.state.d["trades"]) != n:
                self.state.save()

    def step_exec(self, now: int, sig: Dict[str, Dict[str, Any]]) -> None:
        d = self.state.d
        self.reconcile(now)
        last = {s: len(v["t"]) - 1 for s, v in sig.items()}
        marks = {s: float(v["close"][last[s]]) for s, v in sig.items()}
        for sym in list(d["positions"]):
            p, v, i = d["positions"][sym], sig[sym], last[sym]
            sign = 1 if p["side"] == "LONG" else -1
            e = next(x for x in v["entries"] if x["strategy"] == p["strategy"])
            ok = bool(e["dca"][i]) if e.get("dca") is not None else True
            if p["ladder"][p["filled_layers"]:] and ok != p.get("ladder_live", True):   # điều kiện dồn đổi: rút / đặt lại các tầng chờ
                p["dca_ok"] = ok
                self._protect(sym, p)
                self.event("dca_gate", symbol=sym, strategy=p["strategy"], allowed=ok)
            hi, lo = float(v["high"][i]), float(v["low"][i])
            if p["trail_pct"] and not p.get("native_trail"):   # sàn không có trailing gốc: kiểm ở cuối nến (kém chính xác hơn)
                gain = sign * (p["peak"] - p["avg"]) / p["avg"] * 100.0
                level = p["peak"] * (1 - sign * p["trail_pct"] / 100.0)
                if gain >= p["trail_act_pct"] and (lo <= level if sign > 0 else hi >= level):
                    self._close_exec(sym, "Trailing stop", now)
                    continue
            p["peak"] = max(p["peak"], hi) if sign > 0 else min(p["peak"], lo)
            if bool(e["stop"][i]):
                self._close_exec(sym, "Tín hiệu thoát", now)
            elif p["timeout_ms"] and now - p["entry_time"] >= p["timeout_ms"]:
                self._close_exec(sym, "Hết thời gian giữ lệnh", now)
        eq = float(self.client.equity())
        d["peak_equity"] = max(d["peak_equity"], eq)
        kill = float(self.limits.get("kill_switch_dd_pct") or 0)
        if kill and not d["halted"] and eq <= d["peak_equity"] * (1 - kill / 100.0):
            d["halted"] = True
            for sym in list(d["positions"]):
                self._close_exec(sym, "Kill switch", now)
            self.event("crit", reason=f"kill switch: vốn {eq:.2f} <= {100 - kill:.0f}% đỉnh {d['peak_equity']:.2f}")
        if not d["halted"]:
            for sym in self.symbols:
                if sym in d["positions"] or sym in d["external"] or sym in self.blocked:
                    continue
                if len(d["positions"]) >= int(self.limits["max_positions"]):
                    break
                v, i = sig[sym], last[sym]
                for e in v["entries"]:
                    if not bool(e["match"][i]):
                        continue
                    lc = d["last_close"].get(f"{e['strategy']}|{sym}")
                    if lc is not None and e["tracker"].cooldown_ms and now - lc < e["tracker"].cooldown_ms:
                        continue
                    gross = sum(p["qty"] * marks.get(s, p["avg"]) for s, p in d["positions"].items())
                    room = float(self.limits["max_gross_exposure"]) * eq - gross
                    if room > 0:
                        self._open_exec(sym, e, i, marks[sym], eq, room, now)
                    break
        d["equity"] = eq
        d["blocked"] = sorted(self.blocked)

    # ── một bước ──
    def step(self, now: int, data: Optional[Dict[str, Dict[str, Any]]] = None, funding: Optional[Dict[str, List]] = None) -> Dict[str, Any]:
        """now = open của nến chạy mới; data (test) = {sym: kết quả evaluate_signals}."""
        d = self.state.d
        sig = data or {s: evaluate_signals(f"{s}@perp", self.strategies, self.frames(s, now), self.tf) for s in self.symbols}
        if funding is None and data is None:
            since = (self.paper.last_t or now) - 2 * 86_400_000
            funding = {s: self.funding(s, since) for s in self.symbols}
        closed = self.advance_paper(sig, funding)
        if self.mode in EXEC_MODES:
            self.step_exec(now, sig)
        else:
            mtm, worst = self.paper.mtm()
            d.update(equity=round(mtm, 4), equity_worst=round(worst, 4), halted=self.paper.halted_at is not None,
                     positions={p["symbol"]: p for p in self.paper.positions()}, trades=self.paper.trades[-200:])
        for tr in closed:
            self.event("paper_close" if self.mode in EXEC_MODES else "close", **tr)
        d["last_bar"] = now
        d["paper"] = {"equity": round(self.paper.mtm()[0], 4), "positions": len(self.paper.positions()), "trades": len(self.paper.trades),
                      "halted_at": self.paper.halted_at}
        self.state.save()
        return {"equity": d.get("equity"), "positions": len(d["positions"]), "halted": d["halted"]}


@dataclasses.dataclass(frozen=True)
class Profile:
    """Hồ sơ MÔI TRƯỜNG chạy của bot (live/{paper,testnet,live}.py): `mode` (paper | demo | live), `make_adapter(venue) -> (client, keys)` (sàn + khoá của môi trường đó)
    và `check(args)` (kiểm tham số job riêng của môi trường; SystemExit khi sai). Bot / UnifiedBot / run_job dùng chung, KHÔNG biết môi trường nào."""
    mode: str
    make_adapter: Callable[[str], Tuple[Any, Any]]
    check: Callable[[Any], None] = lambda args: None


# mode -> module chứa PROFILE. Nạp LƯỜI (importlib) vì testnet.py / paper.py import runner từ file này.
PROFILE_MODULES = {"paper": "backend.live.paper", "demo": "backend.live.testnet", "live": "backend.live.live"}


def profile_for(mode: str) -> Profile:
    if mode not in PROFILE_MODULES:
        raise SystemExit("mode phải là paper | demo | live")
    return importlib.import_module(PROFILE_MODULES[mode]).PROFILE


def unsupported_venue(venue: str):
    raise SystemExit(f"sàn không hỗ trợ: {venue}")


def require_okx() -> Tuple[Tuple[str, str, str], bool]:
    """((key, secret, passphrase), demo) của OKX; thiếu khoá -> SystemExit. Dùng chung cho hồ sơ demo và live."""
    got = load_okx()
    if not got:
        raise SystemExit("OKX cần khoá: NORA_OKX_KEY / NORA_OKX_SECRET / NORA_OKX_PASSPHRASE (+ NORA_OKX_DEMO) trong môi trường hoặc "
                         "~/.config/nora/okx.env (quyền 600)")
    return got


def make_adapter(venue: str, mode: str):
    """Sàn + khoá theo chế độ (hồ sơ môi trường của mode). paper: chỉ dữ liệu công khai. demo/live: khoá bắt buộc; live cần NORA_OKX_DEMO=0 (khoá thật)."""
    return profile_for(mode).make_adapter(venue)


def run_job(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.crawl.store import default_engine, live_dir
    profile = profile_for(a.mode)
    a.engine = a.engine or default_engine(a.mode)   # rỗng = engine mặc định của chế độ (paper legacy, demo/live unified)
    if a.engine not in ENGINES:
        raise SystemExit(f"engine phải là một trong {ENGINES}")
    profile.check(a)
    unified = a.engine == "unified" and a.mode in EXEC_MODES      # paper + unified = PaperBook event (đã là mặc định): chạy đường Bot thường
    if unified and a.venue != "okx":
        raise SystemExit("engine=unified chỉ hỗ trợ sàn OKX (OkxVenue)")
    book = load_book(kind=a.book, mode=a.mode)
    if unified:
        check_book_d1(book)                                       # D1: từ chối sớm, trước khi chạm sàn
    client, keys = make_adapter(a.venue, a.mode)
    sdir = a.state_dir or live_dir(a.venue, a.mode, a.book, a.engine)
    os.makedirs(sdir, exist_ok=True)
    events, pkl, spath = os.path.join(sdir, "events.jsonl"), os.path.join(sdir, "paper.pkl"), os.path.join(sdir, "state.json")
    upkl = os.path.join(sdir, "unified.pkl")
    _archive_stale_state(sdir, spath, book)

    def log(ev):
        line = redact(json.dumps(ev, ensure_ascii=False, default=str), keys)
        with open(events, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)
    symbols = [s.split("@")[0] for s in book["universe"]]
    filters = {sym: client.filters(sym) for sym in symbols}
    paper = load_pickle(pkl, log, "paper.pkl") if unified else load_paper(sdir, book, float(a.capital), log)
    state = State(spath)
    state.d["book"] = book.get("generated_at")
    state.d["book_kind"] = a.book
    if unified:
        blob = load_pickle(upkl, log, "unified.pkl")
        if blob is None:                                          # khởi động mới: vốn ảo = capital phải xấp xỉ vốn sàn (D3), không thì cảnh báo lệch bắn ngay
            ex = float(client.equity())
            drift = abs(ex - float(a.capital)) / float(a.capital) * 100.0
            if a.equity_drift_halt_pct > 0 and drift > a.equity_drift_halt_pct:
                raise SystemExit(f"capital={a.capital:g} lệch vốn sàn {ex:.2f} ({drift:.1f}% > equity_drift_halt_pct={a.equity_drift_halt_pct:g}%): "
                                 f"vốn ảo của engine=unified khởi tạo bằng capital — đặt capital ≈ vốn sàn")
        try:
            bot = UnifiedBot(book, a.mode, client, state, log, filters, paper, float(a.capital), blob, float(a.equity_drift_halt_pct), upkl)
        except ValueError as e:                                   # unified.pkl của sổ / chiến lược khác: cất đi, bắt đầu lại (vị thế sàn thành "external", có cảnh báo)
            dst = f"{upkl}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(upkl, dst)
            log({"t": _now_ms(), "kind": "warn", "msg": f"unified.pkl không khớp sổ ({e}) — đã cất sang {dst}, bắt đầu lại"})
            bot = UnifiedBot(book, a.mode, client, state, log, filters, paper, float(a.capital), None, float(a.equity_drift_halt_pct), upkl)
    else:
        bot = Bot(book, a.mode, client, state, log, filters, paper, float(a.capital))
    if a.mode in EXEC_MODES:
        client.check_account()
        bot.reconcile(_now_ms())
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    step_ms = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[bot.tf]
    data_ex = book.get("data_exchange", "binance")
    log({"t": _now_ms(), "kind": "start", "venue": a.venue, "mode": a.mode, "book": book.get("source"), "book_kind": a.book,
         "engine": a.engine, "strategies": [x["id"] for x in book["strategies"]], "unvalidated": book.get("unvalidated", []), "timeframe": bot.tf,
         "symbols": bot.symbols, "data_exchange": data_ex})
    if data_ex != a.venue:
        log({"t": _now_ms(), "kind": "warn", "msg": f"sổ được kiểm định trên dữ liệu {data_ex}, bot chạy trên {a.venue} — tín hiệu có thể lệch"})
    n, res = 0, {}
    while not stop["flag"]:
        now = _now_ms() // step_ms * step_ms
        if bot.state.d.get("last_bar") != now:
            try:
                res = bot.step(now)
                _save_paper(bot.paper, sdir, pkl)
                log({"t": _now_ms(), "kind": "step", "bar": now, **res})
            except Exception as e:   # lỗi mạng / sàn: ghi lại, thử ở vòng sau (không mở trùng: đối soát đầu mỗi bước)
                log({"t": _now_ms(), "kind": "error", "error": redact(f"{type(e).__name__}: {e}", keys)})
            n += 1
            if a.once or (a.max_steps and n >= a.max_steps):
                break
        if a.mode in EXEC_MODES and not stop["flag"]:
            try:                                       # giữa các nến: đối soát nhanh — tầng DCA vừa khớp thì đặt lại SL/TP/trailing ngay
                bot.watch(_now_ms())
            except Exception as e:
                log({"t": _now_ms(), "kind": "error", "error": redact(f"watch {type(e).__name__}: {e}", keys)})
        time.sleep(min(WATCH_S, max(1.0, (now + step_ms + 10_000 - _now_ms()) / 1000.0)))
    out = {"venue": a.venue, "mode": a.mode, "steps": n, "last": res, "state": os.path.join(sdir, "state.json"), "events": events}
    write_job_result(out)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Bot sàn trên kiến trúc THỐNG NHẤT (trước đây live/unified.py)
#
# Bot sàn trên kiến trúc thực thi THỐNG NHẤT (P6.8b) — `engine="unified"` của job `live_bot` (demo / live). Mặc định vẫn là `legacy` (lớp Bot ở PHẦN C).
#
# ADR-P6 (docs/bmad/adr-p6-unified-execution.md) §2.3 quyết định 3 và §2.4 D1–D6:
#   một OkxVenue (slot = một symbol) + một Account ẢO (sổ vốn đã chốt + funding, khởi tạo bằng `capital`) + một PositionManager mỗi (symbol, chiến lược),
#   điều khiển bởi một Runner. Sizing, đặt SL/TP/DCA/TRAIL, thoát, hết giờ, cooldown, `risk.admit_entry`, kill switch là CÙNG mã với sim.
#
# Hai lần chạy Runner mỗi mốc nến `now` (sàn không khớp "ở open của nến" mà khớp ngay bây giờ):
#   A  `step_bar(t, nến ĐÃ ĐÓNG t, tín hiệu t)`  — cập nhật đỉnh / MAE, cờ vào / thoát chờ, kill switch theo H/L nến. Nhiều nến bị bỏ lỡ (bot nghỉ) được gộp thành MỘT
#      nến (open đầu, H/L toàn đoạn, close cuối; tín hiệu của nến cuối) — khác sim ở chỗ tín hiệu các nến giữa bị bỏ (sàn không chạy bù lệnh quá khứ).
#   B  `step_bar(now, nến phẳng ở giá last hiện tại, không tín hiệu)` — begin của nến mới: thực thi lệnh vào / thoát chờ NGAY (market) rồi đặt SL/TP/DCA/TRAIL từ giá TB.
# `watch()` (mỗi WATCH_S giây): poll venue -> sự kiện (DCA khớp -> manager đặt lại SL/TP/... từ avg mới NGAY; sàn đóng vị thế -> ghi nhận) + lấy mẫu giá last để kiểm
# kill switch (D3). Lệnh bảo vệ nằm sẵn trên sàn (D2): manager chạy `sticky_orders` nên không huỷ/đặt lại mỗi nến; trailing là lệnh gốc của sàn.
#
# Các quyết định:
#   D1  từ chối khởi động nếu `max_per_symbol` != 1 (hoặc symbol trùng trong universe): OKX net mode chỉ có một vị thế và một giá TB mỗi symbol. Nhiều chiến lược
#       trên cùng symbol dùng CHUNG một slot venue và thay nhau (admit_entry chặn khi symbol đang có vị thế) — chỉ manager đang mở nhận sự kiện của slot.
#   D3  kill switch trên sổ ảo: MTM xấu nhất theo H/L cuối nến (Runner) + mẫu last mỗi WATCH_S giây (`Runner.sample`; không nâng đỉnh MTM). Vốn sàn
#       (`client.equity()`) CHỈ để cảnh báo lệch: |sàn − ảo| / ảo > `equity_drift_halt_pct` -> sự kiện "crit" + dừng vào lệnh mới (KHÔNG tự đóng vị thế); 0 = tắt.
#       Vốn ảo khởi tạo bằng `capital` nên `capital` phải xấp xỉ vốn sàn (run_job từ chối khởi động nếu đã lệch quá ngưỡng).
#   D4/D5 bóng PaperBook (SimVenue) chạy cùng nến; cả hai phía ghi Fill vào events.jsonl: {evt:"fill", src:"exec"|"sim", symbol, side, ...Fill}; Fill SL của sim kèm
#       `level` (giá SL, đã tính gap) và `extreme` (cực trị nến) cho `compare_events` (độ trễ, bps, dải SL, slippage hiệu chỉnh). Fill sàn: `t` = giờ thật (đo độ trễ D5),
#       `t_bar` = giờ nến mà manager dùng (đồng hồ venue = mốc nến để hết giờ / cooldown trùng nhịp sim).
#
# Trạng thái: state.json (thư mục RIÊNG cho unified, xem crawl.store.live_state_key) + paper.pkl (bóng) + unified.pkl (Runner + OkxVenue + Account ảo; client / khoá API KHÔNG được pickle).
# Giới hạn đã biết: giá DCA khớp = mức đặt (maker); phí vào lệnh = 0 ở Fill (sàn không trả khi đặt) — phí cả vòng nằm ở Fill đóng (positions-history).
# ══════════════════════════════════════════════════════════════════════════

STEP_MS = {f: FRAME_MS_ALL[f] for f in ("15m", "1h", "4h")}      # khung bot chạy (không gồm 24h)
WARN_EVERY_MS = 300_000     # chống lặp cảnh báo lỗi mạng của watch()


def check_book_d1(book: Dict[str, Any]) -> None:
    """D1: unified chỉ chạy khi mỗi symbol tối đa MỘT vị thế (OKX net mode). Sai -> SystemExit rõ ràng."""
    mps = (book.get("risk") or {}).get("max_per_symbol")
    if mps is None or int(mps) != 1:
        raise SystemExit(f"engine=unified cần book risk max_per_symbol = 1 (ADR-P6 D1: OKX net mode chỉ có một vị thế / một giá TB mỗi symbol), "
                         f"sổ đang là {mps} — dùng engine=legacy hoặc sửa sổ")
    syms = [s.split("@")[0] for s in book["universe"]]
    dup = sorted({s for s in syms if syms.count(s) > 1})
    if dup:
        raise SystemExit(f"engine=unified: universe có symbol trùng {dup} — hai slot cùng symbol cần hai vị thế net (ADR-P6 D1)")


class _ExecVenue(OkxVenue):
    """OkxVenue + ghi giờ THẬT lúc Fill được kéo ra (manager dùng đồng hồ mốc nến; events.jsonl cần giờ thật để đo độ trễ D5)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.wall: List[Tuple[int, int, int]] = []     # (slot, order_id, ms)
        self.wall_ms = lambda: int(time.time() * 1000)

    def __getstate__(self) -> Dict[str, Any]:
        d = super().__getstate__()
        d["wall_ms"] = None
        return d

    def next_event(self, slot: int):
        ev = super().next_event(slot)
        if isinstance(ev, Fill):
            self.wall.append((ev.slot, ev.order_id, int(self.wall_ms())))
            del self.wall[:-500]
        return ev

    def pop_wall(self, slot: int, order_id: int) -> Optional[int]:
        for i, (s, oid, ts) in enumerate(self.wall):
            if s == slot and oid == order_id:
                del self.wall[i]
                return ts
        return None


class UnifiedBot(Bot):
    def __init__(self, book: Dict[str, Any], mode: str, client, state: State, log, filters: Optional[Dict[str, Any]] = None, paper=None,
                 capital: float = DEFAULT_CAPITAL, exec_blob: Optional[Dict[str, Any]] = None, equity_drift_halt_pct: float = 5.0,
                 exec_path: str = ""):
        check_book_d1(book)
        if mode not in EXEC_MODES:
            raise SystemExit("UnifiedBot chỉ cho demo | live (paper: dùng Bot — PaperBook đã là đường event)")
        if paper is None:
            sim_tf = book.get("sim_timeframe") or ("15m" if book.get("timeframe") == "1h" else book.get("timeframe", "1m"))
            paper = PaperBook(book_strategies(book), [s.split("@")[0] for s in book["universe"]], sim_tf, float(capital), book["risk"],
                              record_events=True, post_only=True, rounds_qty=True)
        super().__init__(book, mode, client, state, log, filters, paper, capital)
        self.drift_halt_pct = float(equity_drift_halt_pct)
        self.exec_path = exec_path
        self.clock_t = 0
        self.wall_ms = _now_ms                                # giờ thật (ms); test ghi đè để kiểm độ trễ D5
        self._warned: Dict[str, int] = {}
        self._attach_sim_events()
        self._build_exec(float(capital), exec_blob)
        if len(self.strategies) > 1:
            self.event("warn", msg=f"{len(self.strategies)} chiến lược dùng chung một vị thế net mỗi symbol (D1): thay nhau theo thứ tự sổ, "
                                   f"admit_entry chặn khi symbol đang có vị thế")

    # ── dựng ──────────────────────────────────────────────────────────────────
    def _build_exec(self, capital: float, blob: Optional[Dict[str, Any]]) -> None:
        if blob is not None:
            runner = blob["runner"]
            if [bk["symbol"] for bk in runner.books] != self.symbols or [[e["strategy"] for e in bk["entries"]] for bk in runner.books] != \
                    [[st["id"] for st in self.strategies] for _ in self.symbols]:
                raise ValueError("unified.pkl của sổ / chiến lược / symbol khác")
            self.runner = runner
        else:
            venue = _ExecVenue(self.client)
            account = Account(capital)
            books = []
            for idx, sym in enumerate(self.symbols):
                venue.bind(idx, sym)
                _, pairs = _engine(sym, self.strategies, self.tf, 0, DAY)
                entries = []
                for st, tr in pairs:
                    mgr = PositionManager(tr, venue, slot=idx, account=account, events=[])
                    mgr.sticky_orders = True
                    entries.append({"strategy": st["id"], "side": st["side"], "tracker": mgr})
                books.append({"symbol": sym, "entries": entries})
            self.runner = Runner(venue, account, books, self.limits, 0, initial_capital=capital)
        self.venue = self.runner.venue
        self.venue.client = self.client                          # unpickle bỏ client + đồng hồ (không lưu khoá API): gắn lại
        self.venue._clock = lambda: self.clock_t
        self.venue.wall_ms = lambda: self.wall_ms()

    def _attach_sim_events(self) -> None:
        """Bóng PaperBook ghi chuỗi sự kiện (xả mỗi nến). Bản pickle cũ chưa ghi: gắn danh sách vào mọi book."""
        pb = self.paper
        self._sim_slots: Dict[int, Tuple[str, str]] = {}
        if getattr(pb, "engine", "") != "event":
            return
        if pb.events is None:
            pb.events = []
        for bk in pb.books:
            for e in bk["entries"]:
                mgr = e["tracker"]
                mgr.book.events = pb.events
                self._sim_slots[mgr.slot] = (bk["symbol"], "LONG" if mgr.is_long else "SHORT")

    # ── trạng thái ────────────────────────────────────────────────────────────
    def save_exec(self) -> None:
        if not self.exec_path:
            return
        tmp = self.exec_path + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump({"v": 1, "runner": self.runner}, fh)
        os.replace(tmp, self.exec_path)

    def _open_syms(self) -> Set[str]:
        return {bk["symbol"] for bk in self.runner.books if any(e["tracker"].is_open for e in bk["entries"])}

    def _throttled(self, key: str) -> bool:
        now = _now_ms()
        if now - self._warned.get(key, 0) < WARN_EVERY_MS:
            return True
        self._warned[key] = now
        return False

    # ── giá / vốn sàn ─────────────────────────────────────────────────────────
    def _prices(self, syms, fallback: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Giá last (ticker) của từng symbol; lỗi / thiếu hàm -> giá dự phòng (nếu có)."""
        lp = getattr(self.client, "last_price", None)
        out: Dict[str, float] = {}
        for s in syms:
            px = None
            if lp is not None:
                try:
                    px = float(lp(s))
                except Exception as e:
                    if not self._throttled("price"):
                        self.event("warn", symbol=s, reason=f"không lấy được giá last: {type(e).__name__}: {e}")
            if not (px and px > 0) and fallback and fallback.get(s):
                px = fallback[s]
            if px and px > 0:
                out[s] = float(px)
        return out

    def _set_refs(self, prices: Dict[str, float]) -> None:
        for idx, sym in enumerate(self.symbols):
            if sym in prices:
                self.venue.set_ref(idx, prices[sym])

    def _drift(self, virtual: float, t: int) -> Optional[float]:
        """D3: vốn sàn chỉ để cảnh báo lệch với vốn ảo; vượt ngưỡng -> crit + dừng vào lệnh mới (không đóng vị thế)."""
        d = self.state.d
        try:
            ex = float(self.client.equity())
        except Exception as e:
            if not self._throttled("equity"):
                self.event("warn", reason=f"không đọc được vốn sàn: {type(e).__name__}: {e}")
            return None
        d["exchange_equity"] = round(ex, 4)
        if virtual > 0:
            pct = abs(ex - virtual) / virtual * 100.0
            d["equity_drift_pct"] = round(pct, 4)
            if self.drift_halt_pct > 0 and self.runner.halted_at is None and pct > self.drift_halt_pct:
                self.runner.halted_at = t
                d["halt_reason"] = "equity_drift"
                self.event("crit", reason=f"vốn sàn {ex:.2f} lệch vốn ảo {virtual:.2f} ({pct:.2f}% > {self.drift_halt_pct:g}%): dừng vào lệnh mới "
                                          f"(vị thế đang mở giữ nguyên — kiểm tra rồi khởi động lại bot)")
        return ex

    # ── ghi sự kiện ───────────────────────────────────────────────────────────
    def _after_sim_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]]) -> None:
        """Xả sự kiện của bóng sim sau mỗi nến: Fill / từ chối kèm symbol, side; Fill SL thêm level + extreme (cho compare_events)."""
        evs = self.paper.events
        if not evs:
            return
        items = list(evs)
        del evs[:]
        for ev in items:
            if not isinstance(ev, (Fill, OrderRejected)):
                continue
            sym, side = self._sim_slots.get(ev.slot, (None, None))
            if sym is None:
                continue
            row = {**dataclasses.asdict(ev), "evt": "fill" if isinstance(ev, Fill) else "reject", "src": "sim", "symbol": sym, "side": side}
            if isinstance(ev, Fill) and ev.kind == "sl":
                row["level"] = ev.raw_price
                b = bars.get(sym)
                if b is not None:
                    row["extreme"] = b[2] if side == "LONG" else b[1]
            self.log(row)

    def _flush_exec_events(self) -> None:
        """Xả sự kiện của sổ ảo (Fill đã áp / từ chối) ra events.jsonl với giờ thật; cảnh báo lệnh bảo vệ bị từ chối / thiếu quyền."""
        wall_now = int(self.wall_ms())
        for bk in self.runner.books:
            for e in bk["entries"]:
                mgr = e["tracker"]
                evs = mgr.book.events
                items = list(evs)
                del evs[:]
                for ev in items:
                    if isinstance(ev, Fill):
                        ts = self.venue.pop_wall(ev.slot, ev.order_id)
                        if ev.kind in CLOSE_KINDS:
                            ts = self.venue.last_close.get(ev.slot, {}).get("exchange_close_time") or ts
                        self.log({**dataclasses.asdict(ev), "evt": "fill", "src": "exec", "symbol": bk["symbol"], "strategy": e["strategy"],
                                  "side": "LONG" if mgr.is_long else "SHORT", "t_bar": ev.t, "t": int(ts or wall_now)})
                    elif isinstance(ev, OrderRejected):
                        self.log({**dataclasses.asdict(ev), "evt": "reject", "src": "exec", "symbol": bk["symbol"], "strategy": e["strategy"],
                                  "t": wall_now})
                        if ev.reason == "not_permitted":
                            self.blocked[bk["symbol"]] = "khoá API không có quyền giao dịch mã này"
                            self.event("warn", symbol=bk["symbol"], strategy=e["strategy"],
                                       reason="khoá API không có quyền giao dịch mã này — bỏ qua mã (bóng sim vẫn theo dõi); thêm quyền rồi khởi động lại bot")
                        elif ev.kind in ("sl", "tp", "trail"):
                            self.event("crit", symbol=bk["symbol"], strategy=e["strategy"],
                                       reason=f"lệnh bảo vệ {ev.kind} bị sàn từ chối ({ev.reason}) — vị thế thiếu bảo vệ, nến sau sẽ đặt lại")
                        elif ev.kind == "entry":
                            self.event("skip", symbol=bk["symbol"], strategy=e["strategy"], reason=f"lệnh vào bị từ chối: {ev.reason}")

    # ── sàn: đối soát / watch ────────────────────────────────────────────────
    def _drain_strays(self) -> None:
        """Sự kiện venue của slot KHÔNG có manager đang mở (lệch trạng thái): bỏ và cảnh báo — không để lệnh vào kế tiếp nhặt nhầm."""
        open_syms = self._open_syms()
        for idx, sym in enumerate(self.symbols):
            if sym in open_syms:
                continue
            while (ev := self.venue.next_event(idx)) is not None:
                self.event("warn", symbol=sym, reason=f"bỏ sự kiện venue mồ côi: {ev}")

    def _external(self, live: Set[str]) -> List[str]:
        open_syms = self._open_syms()
        ext = sorted(s for s in live if s not in open_syms)
        new = [s for s in ext if s not in (self.state.d.get("external") or []) and s in self.symbols]
        if new:
            self.event("warn", symbols=new, reason="vị thế trên sàn không do bot quản lý (lệnh vào lỗi giữa chừng / mất unified.pkl / mở tay): "
                                                   "không vào lệnh mới trên mã đó và KHÔNG có SL của bot — kiểm tra tay")
        return ext

    def reconcile(self, now: int) -> None:
        """Poll venue một lần + áp sự kiện (gọi lúc khởi động và đầu mỗi bước)."""
        self.clock_t = now // STEP_MS[self.tf] * STEP_MS[self.tf]
        live = {s for s, v in self.client.positions().items() if abs(v[0]) > EPS}
        self.venue.poll(self.clock_t)
        for tr in self.runner.sync_events():
            self.event("close", **tr)
        self._drain_strays()
        self.state.d["external"] = self._external(live)

    def watch(self, now: int) -> None:
        """Giữa hai nến (chỉ khi có vị thế): poll venue -> DCA khớp thì manager đặt lại SL/TP/... từ avg mới NGAY, sàn đóng vị thế thì ghi nhận;
        lấy mẫu giá last kiểm kill switch trên sổ ảo (D3); đối chiếu vốn sàn (chỉ cảnh báo)."""
        open_syms = self._open_syms()
        if not open_syms:
            return
        rn, d = self.runner, self.state.d
        self.clock_t = now // STEP_MS[self.tf] * STEP_MS[self.tf]
        marks = self._prices(sorted(open_syms))
        self._set_refs(marks)
        n_ev = self.venue.poll(self.clock_t)
        closed = rn.sync_events()
        virtual, killed = rn.sample(self.clock_t, marks) if marks else (rn.mtm()[0], False)
        for tr in closed:
            self.event("close", **tr)
        if killed:
            d["halt_reason"] = "kill_switch"
            self.event("crit", reason=f"kill switch (mẫu giá giữa nến): vốn ảo {virtual:.2f} <= đỉnh MTM {rn.peak_mtm:.2f} x (1 - "
                                      f"{float(self.limits.get('kill_switch_dd_pct') or 0):g}%) — đã đóng hết")
        self._drift(virtual, self.clock_t)
        self._flush_exec_events()
        if n_ev or closed or killed:
            self._refresh_state()
            self.state.save()
            self.save_exec()

    # ── một bước ──────────────────────────────────────────────────────────────
    def _refresh_state(self) -> None:
        d, rn = self.state.d, self.runner
        mtm, worst = rn.mtm()
        d.update(engine="unified", equity=round(mtm, 4), equity_worst=round(worst, 4), peak_equity=round(rn.peak_mtm, 4),
                 halted=rn.halted_at is not None, blocked=sorted(self.blocked),
                 positions={p["symbol"]: p for p in rn.positions()},
                 trades=[{**t, "entry_time": t["enter_time"], "avg": t["avg_price"], "entry_price": t["enter_price"]} for t in rn.trades[-200:]])

    def step_exec(self, now: int, sig: Dict[str, Dict[str, Any]], funding: Optional[Dict[str, List]]) -> List[Dict[str, Any]]:
        d, rn = self.state.d, self.runner
        self.clock_t = now
        trades0 = len(rn.trades)
        close_c = {s: float(v["close"][-1]) for s, v in sig.items()}
        live = {s for s, v in self.client.positions().items() if abs(v[0]) > EPS}
        last_done = d.get("exec_last_bar")
        hlc, bars, s_at, fund, sig_last = {}, {}, {}, {}, {}
        t_a = max(int(v["t"][-1]) for v in sig.values())
        for sym, v in sig.items():
            ts, n = v["t"], len(v["t"])
            sig_last[sym] = _bar_sig(v, n - 1)
            if int(ts[-1]) != t_a:
                continue
            i0 = n - 1 if last_done is None else int(np.searchsorted(ts, last_done, side="right"))
            if i0 > n - 1:
                continue
            sl = slice(i0, n)
            hi, lo = float(np.max(v["high"][sl])), float(np.min(v["low"][sl]))
            bars[sym] = (float(v["open"][i0]), hi, lo, float(v["close"][n - 1]))
            hlc[sym] = (hi, lo, float(v["close"][n - 1]))
            s_at[sym] = sig_last[sym]
            prev = last_done if last_done is not None else t_a - 1
            fund[sym] = [(ft, r) for ft, r in (funding or {}).get(sym, []) if prev < ft <= t_a]
        # 0. sự kiện sàn từ lần poll trước (DCA khớp, SL/TP/trailing khớp ...) áp trước mọi hành động của nến
        self.venue.poll(now, hlc or None)
        rn.sync_events()
        self._drain_strays()
        d["external"] = self._external(live)
        skip = set(self.blocked) | set(d["external"])
        self._set_refs(close_c)                 # giá tham chiếu dự phòng cho mọi lệnh thị trường trong pha A (pha B đặt lại bằng giá last)
        for bk in rn.books:                     # mã đang bị chặn (vị thế ngoài / thiếu quyền): lệnh vào chờ từ trước không được thực thi muộn
            if bk["symbol"] in skip:
                for e in bk["entries"]:
                    if not e["tracker"].is_open:
                        e["tracker"].pending_entry = False
        # A. nến đã đóng
        bars_a = {s: b for s, b in bars.items() if s not in skip}
        if bars_a:
            d["exec_last_bar"] = t_a            # TRƯỚC khi chạy: lỗi giữa chừng không chạy lại cùng nến (funding / lệnh vào không bị nhân đôi)
            rn.step_bar(t_a, bars_a, {s: s_at[s] for s in bars_a}, {s: fund[s] for s in bars_a})
        # B. nến mới mở: thực thi lệnh chờ ngay ở giá hiện tại rồi đặt lệnh bảo vệ
        need = sorted(bk["symbol"] for bk in rn.books if bk["symbol"] not in skip and
                      any(e["tracker"].is_open or e["tracker"].pending_entry for e in bk["entries"]))
        if need:
            px = self._prices(need, close_c)
            need = [s for s in need if s in px]
            self._set_refs(px)
            flat = {s: (px[s], px[s], px[s], px[s]) for s in need}
            sig_b = {s: [{"match": False, "stop": False, "vol": None, "dca": x["dca"]} for x in sig_last[s]] for s in need}
            rn.step_bar(now, flat, sig_b, None)
        return rn.trades[trades0:]

    def step(self, now: int, data: Optional[Dict[str, Dict[str, Any]]] = None, funding: Optional[Dict[str, List]] = None) -> Dict[str, Any]:
        """now = open của nến chạy mới; data (test) = {sym: kết quả evaluate_signals}."""
        d = self.state.d
        all_frames = {s: self.frames(s, now) for s in self.symbols} if data is None else None
        sig = data or {s: evaluate_signals(f"{s}@perp", self.strategies, all_frames[s], self.tf) for s in self.symbols}
        sub_frames = {s: all_frames[s].get(self.sim_tf) for s in self.symbols} if (all_frames and self.sim_tf != self.tf) else None
        if funding is None and data is None:
            since = (self.paper.last_t or now) - 2 * 86_400_000
            funding = {s: self.funding(s, since) for s in self.symbols}
        self.clock_t = now
        closed_sim = self.advance_paper(sig, funding, sub_frames=sub_frames)          # bóng sim (xả sự kiện từng nến qua _after_sim_bar)
        halted_before = self.runner.halted_at
        closed = self.step_exec(now, sig, funding)
        for tr in closed:
            self.event("close", **tr)
        for tr in closed_sim:
            self.event("paper_close", **tr)
        if halted_before is None and self.runner.halted_at is not None and not d.get("halt_reason"):
            d["halt_reason"] = "kill_switch"
            self.event("crit", reason=f"kill switch: MTM xấu nhất của nến chạm {float(self.limits.get('kill_switch_dd_pct') or 0):g}% dưới đỉnh MTM "
                                      f"{self.runner.peak_mtm:.2f} — đã đóng hết, dừng vào lệnh")
        mtm = self.runner.mtm()[0]
        self._drift(mtm, now)
        self._flush_exec_events()
        self._refresh_state()
        d["last_bar"] = now
        sim_mtm = self.paper.mtm()[0]
        d["paper"] = {"equity": round(sim_mtm, 4), "positions": len(self.paper.positions()), "trades": len(self.paper.trades),
                      "halted_at": self.paper.halted_at}
        self.state.save()
        self.save_exec()
        return {"equity": d.get("equity"), "positions": len(d["positions"]), "halted": d["halted"],
                "exchange_equity": d.get("exchange_equity"), "sim_equity": round(sim_mtm, 4)}


# ══════════════════════════════════════════════════════════════════════════
# Hồ sơ môi trường LIVE (mode "live", tiền thật). Hồ sơ demo = live/testnet.py, paper = live/paper.py.
#   check: đặt lệnh bằng VỐN THẬT cần confirm_live=true. (Sổ thử nghiệm không bao giờ chạy live: load_book chặn.)
#   OKX: khoá tài khoản THẬT (NORA_OKX_DEMO=0). Binance chỉ để tham khảo: không chạy live.
# ══════════════════════════════════════════════════════════════════════════

def _check_live(a) -> None:
    if not a.confirm_live:
        raise SystemExit("mode live đặt lệnh bằng VỐN THẬT — cần confirm_live=true")


def _live_adapter(venue: str):
    if venue == "okx":
        keys, demo = require_okx()
        if demo:
            raise SystemExit("mode live cần khoá tài khoản thật (NORA_OKX_DEMO=0)")
        return OkxAdapter(keys, demo=demo), keys
    if venue == "binance":
        raise SystemExit("Binance chỉ để tham khảo: không chạy live")
    unsupported_venue(venue)


PROFILE = Profile("live", _live_adapter, _check_live)
