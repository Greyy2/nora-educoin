"""OKX v5 (USDT-margined perpetual SWAP) — sàn triển khai của Nora. demo = "Demo Trading" (header x-simulated-trading: 1, khoá demo),
live = tài khoản thật (cùng mã, chỉ khác khoá + cờ demo). Chỉ thư viện chuẩn.

Quy đổi: mã sổ "BTC" -> instId "BTC-USDT-SWAP"; khối lượng bot tính theo COIN, sàn nhận số HỢP ĐỒNG (sz = coin / ctVal, làm tròn xuống lotSz).
Nến: /market/history-candles (100 nến/lần, phân trang) lần đầu, sau đó /market/candles (300 nến mới) gộp vào bộ đệm — mỗi bước chỉ vài request.
Khung ngày dùng "1Dutc" (nến ngày theo UTC như dữ liệu backtest; "1D" của OKX theo giờ Hồng Kông).
Lệnh: vào MARKET; DCA = post_only (bị huỷ nếu sẽ khớp ngay = taker); TP = limit reduceOnly; SL = lệnh điều kiện (order-algo, conditional,
slOrdPx = -1 -> khớp market) reduceOnly; đóng = close-position. Ký: base64(HMAC-SHA256(timestamp + method + path + body)).
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.live.exchange import ExchangeError, Filters, NotPermitted
from backend.live.secrets import redact

OKX_URL = "https://www.okx.com"
NOT_PERMITTED = {"50120", "50123", "50124"}   # khoá thiếu quyền: chung / theo mã Crypto / theo thị trường
BAR = {"15m": "15m", "1h": "1H", "4h": "4H", "24h": "1Dutc"}
FRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}


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
        """-> [[open_time, o, h, l, c, quote_volume, close_time]] tăng dần (volume = volCcyQuote, USDT như dữ liệu backtest), tối đa `limit` nến (gồm cả nến đang chạy — signals.klines_frame bỏ)."""
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

    # ── tài khoản ──
    def check_account(self) -> None:
        cfg = self._req("GET", "/api/v5/account/config", signed=True)[0]
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
