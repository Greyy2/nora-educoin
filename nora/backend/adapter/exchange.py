"""Sổ lệnh RIÊNG của từng bot live (MỘT định nghĩa): vốn / PnL / vị thế / lệnh / số đo của bot CHỈ tính từ fill của chính nó.

Vì sao: nhiều bot dùng chung MỘT tài khoản OKX (demo/thật). Số dư tài khoản (và vị thế net của tài khoản) gồm cả bot khác, vị thế mồ côi và phí cũ,
nên KHÔNG BAO GIỜ dùng làm vốn của bot. Ở đây:
  equity = capital + Σ PnL đã chốt − Σ phí (mọi fill của bot) + Σ lãi/lỗ chưa chốt của vị thế bot đang giữ (net vị thế × (giá − giá vốn TB của bot)).
Fill của bot = sự kiện `fill` trong events.jsonl do CHÍNH các chiến lược của bot phát; khi bot có `cl_tag` thì chỉ nhận fill có client_order_id mang tag đó
(OKX clOrdId do Nautilus sinh dạng `O<yyyymmddHHMMSS><trader tag><strategy tag><số đếm>` không dấu gạch, ≤ 32 ký tự: trader tag = cl_tag riêng từng bot).

Giá tham chiếu: heartbeat.json `marks` (Recorder ghi, còn mới ≤ 5 phút) -> ticker REST công khai OKX -> positions.json.
Dùng ở: RecorderActor (vốn/equity khi chạy + vị thế), live.list_bots / get_bot_detail / live-summary (cùng hàm `snapshot`), cân vị thế khi dừng.
"""
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

TAG_LEN = 8                 # độ dài cố định của cl_tag (chữ hoa + số) -> cắt tag từ client_order_id theo vị trí, không nhập nhằng
_TS_LEN = 14                # `O` + 14 chữ số thời gian rồi tới trader tag
_ENTRY = ("ENTRY", "DCA")
_CANCEL_KINDS = ("END", "KILL", "STOP")


def new_cl_tag(taken: Iterable[str] = ()) -> str:
    """Tag clOrdId duy nhất cho một bot (8 ký tự HEX HOA), khác mọi tag trong `taken`."""
    taken_set = set(taken)
    while True:
        tag = secrets.token_hex(TAG_LEN // 2).upper()
        if tag not in taken_set:
            return tag


def cl_tag_of(client_order_id: Any) -> Optional[str]:
    """Tag bot trong một client_order_id dạng không gạch (None nếu không đúng dạng)."""
    s = str(client_order_id or "")
    if len(s) < 1 + _TS_LEN + TAG_LEN or s[0] != "O" or not s[1:1 + _TS_LEN].isdigit():
        return None
    return s[1 + _TS_LEN:1 + _TS_LEN + TAG_LEN]


def owns(cl_tag: Optional[str], client_order_id: Any) -> bool:
    """Lệnh thuộc bot? Bot cũ không có cl_tag -> nhận tất cả; có tag -> phải khớp tag trong client_order_id."""
    return True if not cl_tag else cl_tag_of(client_order_id) == cl_tag


@dataclass
class _PositionState:
    net: float = 0.0
    avg: float = 0.0
    fees: float = 0.0
    gross: float = 0.0
    t0: int = 0
    px0: float = 0.0
    layers: int = 0
    entry_equity: float = 0.0
    peak: float = 0.0
    kinds: List[str] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __setitem__(self, item: str, value: Any) -> None:
        setattr(self, item, value)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def update(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class OwnLedger:
    """Sổ vị thế bình quân giá vốn theo (symbol, strategy) từ fill của MỘT bot. qty tính bằng COIN, fee > 0 là chi phí."""

    def __init__(self, capital: float, cl_tag: Optional[str] = None):
        self.capital = float(capital)
        self.cl_tag = cl_tag
        self.realized = 0.0                      # PnL gộp đã chốt (chưa trừ phí)
        self.fees = 0.0                          # mọi phí đã trả (kể cả của vị thế đang mở)
        self.fills = 0
        self.pos: Dict[Tuple[str, str], _PositionState] = {}
        self.trades: List[Dict[str, Any]] = []   # lệnh đã đóng, dạng trade_list của backtest
        self.cash_steps: List[Tuple[int, float]] = []   # (ts, realized − fees tích luỹ) để dựng lại số dư theo thời gian

    # ── nạp fill ────────────────────────────────────────────────────────────
    def add_event(self, e: Dict[str, Any]) -> bool:
        """Nạp một sự kiện events.jsonl; chỉ `fill` của bot mới được tính. True nếu đã tính."""
        if e.get("type") != "fill" or not owns(self.cl_tag, e.get("client_order_id")):
            return False
        try:
            qty, px, fee = float(e["qty"]), float(e["px"]), float(e.get("fee") or 0.0)
        except (KeyError, TypeError, ValueError):
            return False
        if not qty > 0:
            return False
        ts = int(e.get("ts") or e.get("t") or 0)
        key = (str(e.get("symbol")), str(e.get("strategy") or ""))
        signed = qty if str(e.get("side")).upper() == "BUY" else -qty
        kind = str(e.get("kind") or "")
        self.fills += 1
        self.fees += fee
        p = self.pos.get(key)
        if p is None:
            p = _PositionState(
                net=0.0, avg=0.0, fees=0.0, gross=0.0, t0=ts, px0=px,
                layers=0, entry_equity=self.capital + self._cash(), peak=0.0, kinds=[]
            )
            self.pos[key] = p
        p.fees += fee
        if p.net == 0.0:
            p.update(t0=ts, px0=px, layers=0, entry_equity=self.capital + self._cash() - fee, gross=0.0, fees=fee, peak=0.0, kinds=[])
        p.kinds.append(kind)
        same_dir = p.net == 0.0 or (p.net > 0) == (signed > 0)
        if same_dir:
            tot = abs(p.net) + qty
            p.avg = (p.avg * abs(p.net) + px * qty) / tot
            p.net += signed
            p.layers += 1 if kind in _ENTRY or p.layers == 0 else 0
            p.peak = max(p.peak, abs(p.net))
        else:
            close_q = min(qty, abs(p.net))
            sign = 1.0 if p.net > 0 else -1.0
            gross = (px - p.avg) * close_q * sign
            self.realized += gross
            p.gross += gross
            p.net += signed
            if abs(p.net) < 1e-12:
                p.net = 0.0
            if p.net == 0.0 or (p.net > 0) != (sign > 0):          # đóng hết (hoặc đảo chiều): chốt một lệnh
                self._close_trade(key, p, ts, px, sign, kind, qty - close_q)
        self.cash_steps.append((ts, self._cash()))
        return True

    def _close_trade(self, key: Tuple[str, str], p: _PositionState, ts: int, px: float, sign: float, kind: str, flip_qty: float) -> None:
        from backend.core.strategy import REASONS
        pnl = p.gross - p.fees
        ee = p.entry_equity
        qmax = p.peak or abs(p.net) or 0.0
        if kind == "TP":
            status = "TP"
        elif kind == "SL":
            status = "SL"
        elif kind in _CANCEL_KINDS:
            status = "CANCEL"
        else:
            status = "TP" if pnl > 0 else "SL"
        self.trades.append({
            "symbol": key[0], "strategy": key[1], "side": "LONG" if sign > 0 else "SHORT", "enter_time": p.t0, "enter_price": p.px0,
            "close_time": ts, "close_price": px, "pnl": round(pnl, 4), "status": status, "close_reason": REASONS.get(kind, kind), "qty": round(qmax, 8),
            "notional": round(qmax * p.avg, 2), "margin_usd": None, "avg_price": round(p.avg, 8),
            "pnl_pct": round(pnl / ee * 100.0, 4) if ee > 0 else None, "fees_usd": round(p.fees, 4), "funding_usd": 0.0, "layers": p.layers or 1,
            "mae_pct": None, "leverage": None, "entry_equity": round(ee, 2)})
        if flip_qty > 1e-12:                                          # phần dư đảo chiều = vị thế mới tại px
            p.update(avg=px, t0=ts, px0=px, layers=1, gross=0.0, fees=0.0, entry_equity=self.capital + self._cash(), peak=abs(p.net), kinds=[])
        else:
            p.update(avg=0.0, layers=0, gross=0.0, fees=0.0, peak=0.0)

    # ── số liệu ─────────────────────────────────────────────────────────────
    def _cash(self) -> float:
        return self.realized - self.fees

    def balance(self) -> float:
        """Số dư RIÊNG của bot = vốn + PnL đã chốt − phí (không gồm lãi/lỗ chưa chốt)."""
        return self.capital + self._cash()

    def open_positions(self) -> List[Dict[str, Any]]:
        return [{"symbol": k[0], "strategy": k[1], "net": p.net, "avg": p.avg} for k, p in self.pos.items() if abs(p.net) > 1e-12]

    def net_by_symbol(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k, p in self.pos.items():
            if abs(p.net) > 1e-12:
                out[k[0]] = out.get(k[0], 0.0) + p.net
        return out

    def unrealized(self, marks: Dict[str, float]) -> float:
        tot = 0.0
        for k, p in self.pos.items():
            if abs(p.net) > 1e-12:
                m = marks.get(k[0])
                if m is not None and m == m:
                    tot += (m - p.avg) * p.net
        return tot

    def equity(self, marks: Optional[Dict[str, float]] = None) -> float:
        return self.balance() + self.unrealized(marks or {})

    def cash_asof(self, ts: int) -> float:
        """realized − fees tích luỹ tới thời điểm ts (ms)."""
        v = 0.0
        for t, c in self.cash_steps:
            if t > ts:
                break
            v = c
        return v

    def positions_view(self, marks: Dict[str, float]) -> List[Dict[str, Any]]:
        out = []
        for o in self.open_positions():
            m = marks.get(o["symbol"])
            has = m is not None and m == m
            out.append({"strategy": o["strategy"], "symbol": o["symbol"], "is_long": o["net"] > 0, "side": "LONG" if o["net"] > 0 else "SHORT", "qty": abs(o["net"]),
                        "avg_price": o["avg"], "mark": m if has else None, "mark_price": m if has else None, "unrealized_usd": round((m - o["avg"]) * o["net"], 6) if has else None, "unrealized_pnl": round((m - o["avg"]) * o["net"], 6) if has else None})
        return out


def read_events(path: str) -> List[Dict[str, Any]]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        pass
    return out


_CACHE: Dict[str, Tuple[Tuple[int, int, float, Optional[str]], OwnLedger]] = {}
_CACHE_LOCK = threading.Lock()


def ledger_from_dir(bot_dir: str, capital: float, cl_tag: Optional[str]) -> OwnLedger:
    """Sổ của bot dựng lại từ events.jsonl (đệm theo mtime+size: API gọi dày)."""
    path = os.path.join(bot_dir, "events.jsonl")
    try:
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size, float(capital), cl_tag)
    except OSError:
        sig = (0, 0, float(capital), cl_tag)
    with _CACHE_LOCK:
        hit = _CACHE.get(bot_dir)
        if hit is not None and hit[0] == sig:
            return hit[1]
    led = OwnLedger(capital, cl_tag)
    for e in read_events(path):
        led.add_event(e)
    with _CACHE_LOCK:
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[bot_dir] = (sig, led)
    return led


def marks_from_positions(path: str) -> Dict[str, float]:
    """Giá tham chiếu từng tài sản từ positions.json do Recorder ghi (`mark`; bản cũ chỉ có avg + unrealized -> suy ra)."""
    try:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError):
        return {}
    marks: Dict[str, float] = {}
    for r in rows if isinstance(rows, list) else []:
        try:
            if r.get("mark") is not None:
                marks[r["symbol"]] = float(r["mark"])
            elif r.get("unrealized_pnl") is not None and float(r.get("qty") or 0) > 0:
                sign = 1.0 if r.get("is_long", True) else -1.0
                marks[r["symbol"]] = float(r["avg_price"]) + sign * float(r["unrealized_pnl"]) / float(r["qty"])
        except (KeyError, TypeError, ValueError):
            continue
    return marks


MARK_STALE_S = 300           # giá tham chiếu cũ hơn 5 phút -> lấy lại từ REST công khai
_TICKER_TTL_S = 15
_TICKERS: Dict[str, Tuple[float, float]] = {}      # instId -> (thời điểm lấy, giá)
_TICKER_LOCK = threading.Lock()
_SESSION: Optional[Any] = None


def _get_session() -> Any:
    global _SESSION
    if _SESSION is None:
        import requests
        _SESSION = requests.Session()
    return _SESSION


def okx_marks(symbols: Iterable[str], now: Optional[float] = None) -> Dict[str, float]:
    """Giá last hiện tại từ ticker REST CÔNG KHAI của OKX (chỉ đọc, không khoá; đệm 15 s). Lỗi mạng -> bỏ qua ký hiệu đó."""
    from backend.data.data import normalize_symbol
    now = time.time() if now is None else now
    out: Dict[str, float] = {}
    session = None
    for sym in symbols:
        try:
            inst = normalize_symbol(sym)
        except ValueError:
            continue
        with _TICKER_LOCK:
            hit = _TICKERS.get(inst)
        if hit is None or now - hit[0] > _TICKER_TTL_S:
            if session is None:
                session = _get_session()
            try:
                r = session.get("https://www.okx.com/api/v5/market/ticker", params={"instId": inst}, timeout=1.5).json()
                price = float(r["data"][0]["last"])
                hit = (now, price)
            except Exception:
                # Tránh hammering khi lỗi mạng: cache tạm 5 giây với giá 0
                hit = (now - _TICKER_TTL_S + 5.0, 0.0)
            with _TICKER_LOCK:
                _TICKERS[inst] = hit
        if hit is not None and hit[1] > 0.0:
            out[sym] = hit[1]
    return out


def fresh_marks(bot_dir: str, open_symbols: Iterable[str], now: Optional[float] = None) -> Dict[str, float]:
    """Giá tham chiếu cho vị thế mở: heartbeat.json `marks` (nếu còn mới), rồi positions.json (nếu file còn mới), thiếu/cũ -> ticker REST công khai."""
    now = time.time() if now is None else now
    need = list(open_symbols)
    if not need:
        return {}
    marks: Dict[str, float] = {}
    try:
        with open(os.path.join(bot_dir, "heartbeat.json"), encoding="utf-8") as fh:
            hb = json.load(fh)
        if now - float(hb.get("marks_ts") or 0) / 1000.0 <= MARK_STALE_S:
            marks.update({k: float(v) for k, v in (hb.get("marks") or {}).items() if v == v})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    missing = [s for s in need if s not in marks]
    if missing:
        marks.update(okx_marks(missing, now))
    still = [s for s in need if s not in marks]
    if still:                                      # REST lỗi: dùng giá cuối ghi trong positions.json còn hơn không có
        for k, v in marks_from_positions(os.path.join(bot_dir, "positions.json")).items():
            marks.setdefault(k, v)
    return marks


def equity_rows(path: str) -> List[Dict[str, Any]]:
    return read_events(path)


def snapshot(bot_dir: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """MỘT hàm cho mọi nơi hiển thị bot (/live/bots, /live/bot/{id}, /live/summary): vốn/PnL/vị thế/lệnh/đường vốn RIÊNG của bot.
    Trả {ledger, capital, equity, balance, unrealized, pnl_usd, pnl_pct, positions, trades, series, fees_usd, marks}.
    Đường vốn: dòng equity.jsonl mới (có `unrealized`) giữ nguyên; dòng bản cũ (đo bằng số dư tài khoản chung, SAI) dựng lại = vốn + (PnL đã chốt − phí) tại thời điểm đó
    (bản cũ không lưu giá nên không có phần chưa chốt); điểm cuối luôn là vốn hiện tại tính từ fill + giá tham chiếu mới nhất."""
    capital = float(meta.get("capital") or 0.0)
    led = ledger_from_dir(bot_dir, capital, meta.get("cl_tag"))
    marks = fresh_marks(bot_dir, led.net_by_symbol().keys())
    unreal = led.unrealized(marks)
    equity = led.balance() + unreal
    series = []
    for r in equity_rows(os.path.join(bot_dir, "equity.jsonl")):
        t = r.get("time")
        if t is None:
            continue
        eq = float(r["equity"]) if "unrealized" in r else capital + led.cash_asof(int(t))
        series.append({"time": int(t), "equity": round(eq, 4), "balance": round(float(r["balance"]), 4) if "unrealized" in r and r.get("balance") is not None else round(capital + led.cash_asof(int(t)), 4),
                       "equity_worst": round(float(r.get("equity_worst", eq)), 4) if "unrealized" in r else round(eq, 4)})
    if series:
        series[-1] = {**series[-1], "equity": round(equity, 4)}
    pnl = equity - capital
    return {"ledger": led, "capital": capital, "equity": equity, "balance": led.balance(), "unrealized": unreal, "pnl_usd": pnl,
            "pnl_pct": pnl / capital * 100.0 if capital else 0.0, "positions": led.positions_view(marks), "trades": list(led.trades), "series": series,
            "fees_usd": led.fees, "marks": marks}


# ============================================================
# LIVE TRADING NODE & ADAPTER
# ============================================================

class _LedProxy:
    OwnLedger: Any = OwnLedger
    snapshot: Any = staticmethod(snapshot)
    new_cl_tag: Any = staticmethod(new_cl_tag)
    cl_tag_of: Any = staticmethod(cl_tag_of)
    owns: Any = staticmethod(owns)
    read_events: Any = staticmethod(read_events)
    ledger_from_dir: Any = staticmethod(ledger_from_dir)
    marks_from_positions: Any = staticmethod(marks_from_positions)
    okx_marks: Any = staticmethod(okx_marks)
    fresh_marks: Any = staticmethod(fresh_marks)

led = _LedProxy()
"""Live TradingNode qua Nautilus (P17 T5): Paper, Testnet và Live.

- build_node: dựng TradingNode (OKXDataClient + SandboxExecutionClient cho Paper / OKXExecClient cho Testnet & Live).
- RecorderActor: Actor ghi nhận sự kiện (events.jsonl, equity.jsonl, positions.json) vào data/live/<mode>/<bot_id>/.
- Quản lý vòng đời bot (start, stop, list, detail, trades, compare).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import signal
import threading
import time
import zlib
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import pandas as pd
import numpy as np

from datetime import timedelta
from types import SimpleNamespace

from nautilus_trader.adapters.okx.config import OKXDataClientConfig, OKXExecClientConfig
from nautilus_trader.adapters.okx.factories import OKXLiveDataClientFactory, OKXLiveExecClientFactory
from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.execution import SandboxExecutionClient
from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory as _SandboxFactory
from nautilus_trader.core.data import Data
from nautilus_trader.model.instruments import CryptoPerpetual, Instrument
from nautilus_trader.common.actor import Actor
from enum import Enum
from nautilus_trader.config import InstrumentProviderConfig, LoggingConfig
import nautilus_trader.core.nautilus_pyo3 as _pyo3

try:
    from nautilus_trader.core.nautilus_pyo3 import OKXEnvironment
except ImportError:
    class OKXEnvironment(str, Enum):
        LIVE = "LIVE"
        DEMO = "DEMO"
    setattr(_pyo3, "OKXEnvironment", OKXEnvironment)

from nautilus_trader.core.nautilus_pyo3 import OKXContractType, OKXInstrumentType, OKXMarginMode
from nautilus_trader.live.config import LiveExecEngineConfig, LiveRiskEngineConfig
from nautilus_trader.live.node import TradingNode, TradingNodeConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from backend.analys.alpha import RiskConfig
from backend.data import data as dat
from backend.analys.param import FRAME_MS
from backend.models.storage import data_home, pid_alive, pid_start_ticks, write_json_atomic
# live_ledger embedded
from backend.core import catalog as cat
from backend.core.backtest import book_instruments, build_slots, build_user_strategy
from backend.core.portfolio import Coordinator
from backend.analys.signal import LiveSignals
from backend.analys.signal.compute import slot_pairs


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


def _okx_signed(method: str, path: str, is_demo: bool, body: Optional[Dict[str, Any]] = None) -> Any:
    """Gọi REST OKX riêng tư có chữ ký (MỘT nơi ký). Trả (http_status, json). Khoá chỉ đọc từ okx.env, không in ra."""
    creds = load_okx_credentials()
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    payload = json.dumps(body) if body is not None else ""
    sign = base64.b64encode(hmac.new(creds["secret"].encode(), f"{ts}{method}{path}{payload}".encode(), hashlib.sha256).digest()).decode()
    headers = {"OK-ACCESS-KEY": creds["key"], "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": creds["passphrase"],
               "Content-Type": "application/json"}
    if is_demo:
        headers["x-simulated-trading"] = "1"
    resp = requests.request(method, OKX_REST + path, headers=headers, data=payload or None, timeout=8)
    return resp.status_code, resp.json()


def ensure_net_position_mode() -> str:
    """Testnet: lệnh reduce-only (SL/TP) của OKX chỉ dùng được ở chế độ vị thế 'net_mode' (khớp NETTING của Nora). Đang long/short thì đổi (chỉ khi không có vị thế mở)."""
    _, cfg = _okx_signed("GET", "/api/v5/account/config", True)
    mode = ((cfg.get("data") or [{}])[0]).get("posMode")
    if mode == "net_mode":
        return mode
    _, res = _okx_signed("POST", "/api/v5/account/set-position-mode", True, {"posMode": "net_mode"})
    if str(res.get("code")) != "0":
        raise RuntimeError(f"Không đổi được chế độ vị thế OKX demo sang net_mode ({mode}): {res.get('msg')}")
    return "net_mode"


def test_okx_api_connection(mode: str = "demo") -> Dict[str, Any]:
    """Xác thực khoá bằng endpoint RIÊNG TƯ có chữ ký (GET /api/v5/account/balance, chỉ đọc)."""
    creds = load_okx_credentials()
    is_demo = mode.lower() in ("demo", "testnet") or creds["is_demo"]
    label = "demo" if is_demo else "live"
    if not _has_keys(creds):
        return {"ok": False, "mode": label, "has_credentials": False, "message": "Chưa cấu hình API Key/Secret/Passphrase tại ~/.config/nora/okx.env"}
    try:
        status, body = _okx_signed("GET", "/api/v5/account/balance", is_demo)
    except Exception as e:
        return {"ok": False, "mode": label, "has_credentials": True, "message": f"Lỗi kết nối tới OKX API: {type(e).__name__}"}
    if status == 200 and str(body.get("code")) == "0":
        return {"ok": True, "mode": label, "has_credentials": True, "environment": "OKX Demo" if is_demo else "OKX Live",
                "message": f"Khoá OKX hợp lệ (xác thực chữ ký thành công, {'Demo' if is_demo else 'Thật'})."}
    return {"ok": False, "mode": label, "has_credentials": True, "status_code": status, "okx_code": body.get("code"),
            "message": f"OKX từ chối khoá: {body.get('msg') or status}"}


def get_environments_status() -> Dict[str, Any]:
    """Trạng thái từng môi trường: backtest, paper, testnet, live."""
    creds = load_okx_credentials()
    has_keys = _has_keys(creds)
    return {
        "backtest": {"name": "Backtest", "ready": True, "engine": "NautilusTrader BacktestEngine", "data_source": "Nautilus ParquetDataCatalog",
                     "description": "Chạy khớp lệnh mô phỏng với dữ liệu lịch sử."},
        "paper": {"name": "Paper Trading", "ready": True, "engine": "NautilusTrader TradingNode (Sandbox Execution)",
                  "description": "Dữ liệu thị trường OKX thật, khớp lệnh giả lập qua Nautilus Sandbox."},
        "testnet": {"name": "Testnet / Demo", "ready": has_keys, "configured": has_keys,
                    "engine": "NautilusTrader OKX Adapter (DEMO)", "description": "Đặt lệnh thật trên môi trường OKX Demo Trading."},
        "live": {"name": "Live Real Trading", "ready": False, "configured": has_keys, "demo_lock": True,
                 "engine": "NautilusTrader OKX Adapter (LIVE)", "description": "Giao dịch tiền thật trên sàn OKX (chỉ dựng sẵn, khoá ở T5)."},
    }


# ─── Quản lý thư mục bot ─────────────────────────────────────────────────────

MODES = ("paper", "testnet", "live")


def new_bot_id(mode: str) -> str:
    """Id bot DUY NHẤT: bot_<epoch giây>_<6 hex ngẫu nhiên>_<mode> (hai bot cùng giây vẫn khác nhau)."""
    return f"bot_{int(time.time())}_{secrets.token_hex(3)}_{mode}"


def find_bot_dir(bot_id: str) -> Optional[str]:
    """Thư mục data/live/<mode>/<bot_id> nếu tồn tại (mọi mode), ngược lại None. bot_id có ký tự đường dẫn -> None."""
    if not bot_id or bot_id != os.path.basename(bot_id) or bot_id.startswith("."):
        return None
    for m in MODES:
        d = os.path.join(data_home(), "live", m, bot_id)
        if os.path.isdir(d):
            return d
    return None


def get_bot_dir(mode: str, bot_id: str) -> str:
    path = os.path.join(data_home(), "live", mode, bot_id)
    os.makedirs(path, exist_ok=True)
    return path


def open_bot_dir(mode: str, bot_id: str, resume: bool) -> str:
    """Tạo thư mục bot MỚI (từ chối nếu bot_id đã có ở BẤT KỲ mode nào — không bao giờ ghi đè dữ liệu bot) hoặc mở lại thư mục có sẵn khi resume (giữ nguyên file)."""
    if resume:
        d = os.path.join(data_home(), "live", mode, bot_id)
        if not os.path.isfile(os.path.join(d, "bot.json")):
            raise ValueError(f"Không có bot {bot_id} để chạy lại")
        return d
    if find_bot_dir(bot_id) is not None:
        raise ValueError(f"Bot {bot_id} đã tồn tại — không tạo trùng")
    d = os.path.join(data_home(), "live", mode, bot_id)
    os.makedirs(d, exist_ok=False)
    return d


def _all_cl_tags() -> List[str]:
    out = []
    for m in MODES:
        root = os.path.join(data_home(), "live", m)
        for n in (os.listdir(root) if os.path.isdir(root) else []):
            t = _read_json(os.path.join(root, n, "bot.json")).get("cl_tag")
            if t:
                out.append(t)
    return out


HEARTBEAT_S = 60              # nhịp ghi heartbeat.json theo timer (không phụ thuộc nến)
HEALTH_BARS_ABOVE_MS = 15 * 60_000     # khung chạy lớn hơn mức này: thêm nến 1m chỉ để theo dõi sức khoẻ dữ liệu


class RecorderActor(Actor):
    """Actor ghi nhận trạng thái bot vào đĩa: events.jsonl (fill / reject / position_closed), equity.jsonl + positions.json mỗi `interval_s` giây (timer của Nautilus).
    Với Paper còn đăng ký QuoteTick các instrument để Sandbox khớp lệnh theo giá thị trường thật."""

    def __init__(self, bot_dir: str, coord: Coordinator, quote_ids: Optional[List[InstrumentId]] = None, interval_s: int = 60, ledger: Optional[led.OwnLedger] = None,
                 health_bar_types: Optional[List[Any]] = None, heartbeat_s: int = HEARTBEAT_S):
        super().__init__()
        self.health_bar_types = list(health_bar_types or [])      # khung chạy lớn (> 15m): thêm nến 1m CHỈ để biết dữ liệu còn tới (không đưa vào tín hiệu)
        self.heartbeat_s = heartbeat_s
        self.last_data_wall = 0                                    # ms: lần cuối nhận BẤT KỲ dữ liệu nào (nến hoặc quote)
        self.last_data_kind = None
        self.bot_dir = bot_dir
        self.coord = coord
        self.ledger = ledger if ledger is not None else led.OwnLedger(coord.initial)
        self.quote_ids = list(quote_ids or [])
        self.interval_s = interval_s
        self.events_path = os.path.join(bot_dir, "events.jsonl")
        self.equity_path = os.path.join(bot_dir, "equity.jsonl")
        self.positions_path = os.path.join(bot_dir, "positions.json")
        self.bars_path = os.path.join(bot_dir, "bars.jsonl")
        self.heartbeat_path = os.path.join(bot_dir, "heartbeat.json")
        self.signals_path = os.path.join(bot_dir, "signals.jsonl")
        self._heartbeat_state: Dict[str, Any] = {
            "updated_at": int(time.time() * 1000),
            "last_bar_ts": 0,
            "last_bar_wall": 0,
            "bars_received": 0,
            "symbols": {},
        }
        self._marks: Dict[str, float] = {}                         # giá mới nhất từng tài sản (quote / nến 1m)
        self._marks_ts = 0
        coord.on_event = self.record_event

    def record_bar(self, symbol: str, bar: Any, ts: int) -> None:
        """Ghi nến live (B1): nguồn sự thật cho kiểm tra đồng nhất 4 tầng."""
        if not hasattr(self, "_last_recorded_bars"):
            self._last_recorded_bars = {}
        if self._last_recorded_bars.get(symbol) == ts:
            return
        self._last_recorded_bars[symbol] = ts

        fr_ms = getattr(self.coord, "frame_ms", 60_000)
        row = {
            "symbol": symbol,
            "ts_open": ts - fr_ms,
            "ts_close": ts,
            "open": bar.open.as_double(),
            "high": bar.high.as_double(),
            "low": bar.low.as_double(),
            "close": bar.close.as_double(),
            "volume": bar.volume.as_double(),
        }
        try:
            with open(self.bars_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass

    def record_signal(self, symbol: str, slot: str, ts: int, sig: Optional[Dict[str, Any]]) -> None:
        """signals.jsonl (luôn bật ở live): MỘT dòng gọn mỗi (nến, slot) — ts = giờ đóng nến, match/stop/dca (None nếu chưa có tín hiệu). Tầng 2 của parity tính lại rồi so."""
        row = {"ts": ts, "symbol": symbol, "slot": slot, "match": None if sig is None else bool(sig.get("match")),
               "stop": None if sig is None else bool(sig.get("stop")), "dca": None if sig is None else bool(sig.get("dca", True))}
        try:
            with open(self.signals_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception:
            pass

    def touch_data(self, kind: str) -> None:
        self.last_data_wall, self.last_data_kind = int(time.time() * 1000), kind

    def _sym_of(self, instrument_id: Any) -> Optional[str]:
        if not hasattr(self, "_iid_sym"):
            self._iid_sym = {str(_iid(s.symbol)): s.symbol for s in getattr(self.coord, "slots", [])}
        return self._iid_sym.get(str(instrument_id))

    def set_mark(self, symbol: Optional[str], price: float, ts_ms: Optional[int] = None) -> None:
        """Giá tham chiếu mới nhất của tài sản (QuoteTick mid / close nến 1m) -> marks() và heartbeat.json."""
        if symbol and price == price and price > 0:
            self._marks[symbol] = float(price)
            self._marks_ts = int(ts_ms if ts_ms is not None else time.time() * 1000)

    def on_quote_tick(self, tick) -> None:
        self.touch_data("quote")
        try:
            self.set_mark(self._sym_of(tick.instrument_id), (tick.bid_price.as_double() + tick.ask_price.as_double()) / 2.0)
        except Exception:
            pass

    def on_bar(self, bar) -> None:
        self.touch_data("bar_1m")
        try:
            self.set_mark(self._sym_of(bar.bar_type.instrument_id), bar.close.as_double())
        except Exception:
            pass

    def seed_signal(self, symbol: str, close_ts: int, ev: Dict[str, Any]) -> None:
        """Trạng thái tín hiệu từ LỊCH SỬ lúc khởi động (nến tín hiệu đóng gần nhất) để heartbeat có ngay, trước cả nến đầu tiên của khung lớn."""
        st = self._heartbeat_state["symbols"].setdefault(symbol, {})
        if "last_signal" not in st:
            st["last_signal"] = {"ts": int(close_ts), "has_sig": True, "match": bool(ev.get("match")), "stop": bool(ev.get("stop")), "source": "history"}
        self.write_heartbeat()

    def record_heartbeat(self, symbol: str, ts: int, nbar: int, last_signal: Optional[Dict[str, Any]] = None) -> None:
        """Ghi heartbeat khi có nến khung chạy (D1) + trạng thái tín hiệu; xem thêm write_heartbeat (timer 60 s)."""
        sym_state = self._heartbeat_state["symbols"].setdefault(symbol, {})
        sym_state["last_bar_ts"] = ts
        sym_state["bars_received"] = nbar
        if last_signal is not None:
            sym_state["last_signal"] = {
                "ts": ts,
                "has_sig": bool(last_signal),
                "match": bool(last_signal.get("match")),
                "stop": bool(last_signal.get("stop")),
            }
        self._heartbeat_state["last_bar_ts"] = ts
        self._heartbeat_state["last_bar_wall"] = int(time.time() * 1000)
        self.touch_data("base_bar")
        self.write_heartbeat()

    def next_close_ms(self, now_ms: int) -> int:
        """Giờ đóng nến khung chạy kế tiếp: theo nến cuối đã có (ưu tiên) hoặc lưới thời gian."""
        fr_ms = int(getattr(self.coord, "frame_ms", 60_000))
        last = int(self._heartbeat_state.get("last_bar_ts") or 0)
        if last:
            nxt = last + fr_ms
            if nxt <= now_ms:
                nxt += ((now_ms - nxt) // fr_ms + 1) * fr_ms
            return nxt
        for sl in getattr(self.coord, "slots", []):
            df = getattr(getattr(sl, "signals", None), "frames", {}).get(getattr(getattr(sl, "signals", None), "base_frame", ""))
            if df is not None and len(df):
                nxt = int(df["open_time"].iloc[-1]) + 2 * fr_ms
                return nxt if nxt > now_ms else nxt + ((now_ms - nxt) // fr_ms + 1) * fr_ms
        return (now_ms // fr_ms + 1) * fr_ms

    def write_heartbeat(self, now_ms: Optional[int] = None) -> None:
        """heartbeat.json: ghi theo nến VÀ theo timer (heartbeat_s) để bot khung 24h không trông như đã chết. Gồm: lần cuối nhận dữ liệu (nến/quote), giờ đóng nến kế, tín hiệu cuối từng tài sản."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        st = self._heartbeat_state
        st["updated_at"] = now
        st["last_data_ms"] = self.last_data_wall or None
        st["last_data_kind"] = self.last_data_kind
        st["bars_received"] = sum(s.get("bars_received", 0) for s in st["symbols"].values())
        st["next_bar_close_ms"] = self.next_close_ms(now)
        st["frame_ms"] = int(getattr(self.coord, "frame_ms", 60_000))
        st["interval_s"] = self.heartbeat_s
        st["marks"] = self.marks()
        st["marks_ts"] = self._marks_ts          # 0 = chưa có quote/nến 1m -> API coi là cũ
        try:
            write_json_atomic(self.heartbeat_path, st, indent=2)
        except Exception:
            pass

    def _on_heartbeat_timer(self, event) -> None:
        self.write_heartbeat(int(event.ts_event // 1_000_000))

    def on_start(self) -> None:
        for iid in self.quote_ids:
            self.subscribe_quote_ticks(iid)
        for bt in self.health_bar_types:
            self.subscribe_bars(bt)
        self.clock.set_timer("nora_heartbeat", interval=timedelta(seconds=self.heartbeat_s), callback=self._on_heartbeat_timer)
        self.write_heartbeat()
        self.clock.set_timer("nora_recorder", interval=timedelta(seconds=self.interval_s), callback=self._on_timer)
        self.record_event("start", {"instruments": len(self.cache.instruments()), "quotes": len(self.quote_ids)})

    def on_stop(self) -> None:
        self.record_event("stop", {})

    def _on_timer(self, event) -> None:
        self.record_equity(int(event.ts_event // 1_000_000))
        self.record_positions()

    def marks(self) -> Dict[str, float]:
        out = {}
        for s in getattr(self.coord, "slots", []):
            last = self.coord.last[s.sym_idx][0]
            if last == last:
                out[s.symbol] = float(last)
        out.update(self._marks)                          # quote / nến 1m mới hơn nến khung chạy
        return out

    def record_event(self, event_type: str, data: Dict[str, Any]) -> None:
        row = {"t": int(time.time() * 1000), "type": event_type, **data}
        self.ledger.add_event(row)                       # sổ RIÊNG của bot (vốn / PnL) chỉ từ fill của bot
        try:
            with open(self.events_path, "a", encoding="utf-8") as f:       # luôn nối thêm, không bao giờ cắt / tạo lại
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def record_equity(self, ts: int) -> None:
        """Điểm vốn RIÊNG của bot: vốn + PnL đã chốt − phí + chưa chốt (từ fill của bot) — KHÔNG đọc số dư tài khoản sàn (dùng chung nhiều bot)."""
        point = self.coord.sample_live(ts)               # cũng chạy kill-switch
        unreal = self.ledger.unrealized(self.marks())
        eq = self.ledger.balance() + unreal
        point = {**point, "equity": round(eq, 4), "equity_worst": round(min(float(point.get("equity_worst", eq)), eq), 4), "balance": round(self.ledger.balance(), 4),
                 "unrealized": round(unreal, 4), "open_positions": len(self.ledger.open_positions())}
        try:
            with open(self.equity_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(point) + "\n")
        except Exception:
            pass

    def record_positions(self) -> None:
        try:
            write_json_atomic(self.positions_path, self.ledger.positions_view(self.marks()), indent=2)
        except Exception:
            pass


# ─── Dựng TradingNode ───────────────────────────────────────────────────────

# ─── Sandbox (Paper) có biểu phí OKX ────────────────────────────────────────
def with_fee_schedule(inst: Instrument) -> Instrument:
    """Instrument của adapter OKX không có phí / ký quỹ (=0): Paper lấy phí maker/taker + ký quỹ từ instruments.json (CÙNG nguồn với backtest) để hoa hồng Sandbox = backtest."""
    if not isinstance(inst, CryptoPerpetual):
        return inst
    try:
        spec = cat.instrument_spec(str(inst.id.symbol))
    except Exception:
        return inst
    d = CryptoPerpetual.to_dict(inst)
    d.update(maker_fee=str(spec["maker_fee"]), taker_fee=str(spec["taker_fee"]), margin_init=str(spec["margin_init"]), margin_maint=str(spec["margin_maint"]))
    return CryptoPerpetual.from_dict(d)


class NoraSandboxExecutionClient(SandboxExecutionClient):
    """SandboxExecutionClient nạp instrument của sàn kèm biểu phí (with_fee_schedule), kể cả khi adapter tải lại instrument."""

    def connect(self) -> None:
        self._log.info("Connecting...")
        self._msgbus.subscribe(f"data.*.{self.venue}.*", handler=self.on_data)
        for instrument in self.exchange.cache.instruments(venue=self.venue):
            self.exchange.add_instrument(with_fee_schedule(instrument))
        self._client._set_connected(True)
        self._set_connected(True)
        self._log.info("Connected")

    def on_data(self, data: Data) -> None:
        super().on_data(with_fee_schedule(data) if isinstance(data, Instrument) else data)


class SandboxLiveExecClientFactory(_SandboxFactory):
    """Trùng tên với factory gốc có chủ ý: TradingNodeBuilder chỉ truyền `portfolio` cho factory tên "SandboxLiveExecClientFactory"."""
    @staticmethod
    def create(loop, name, config, portfolio, msgbus, cache, clock):          # type: ignore
        return NoraSandboxExecutionClient(loop=loop, clock=clock, portfolio=portfolio, msgbus=msgbus, cache=cache, config=config)


def _iid(symbol: str) -> InstrumentId:
    return InstrumentId.from_str(f"{cat.normalize_symbol(symbol)}.OKX")


def _canon(o: Any, depth: int = 0) -> Any:
    """Dạng chuẩn tắc (JSON) của cây/slot để băm: khoá sắp xếp, float làm tròn 12 chữ số, enum theo tên, đối tượng theo __dict__ (không có địa chỉ bộ nhớ)."""
    if depth > 12:
        return "…"
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return o
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return "nan" if f != f else ("inf" if f == float("inf") else ("-inf" if f == float("-inf") else round(f, 12)))
    if isinstance(o, dict):
        return {str(k): _canon(v, depth + 1) for k, v in sorted(o.items(), key=lambda kv: str(kv[0]))}
    if isinstance(o, (list, tuple, set, frozenset)):
        items = sorted(o, key=str) if isinstance(o, (set, frozenset)) else o
        return [_canon(v, depth + 1) for v in items]
    if isinstance(o, np.ndarray):
        return _canon(o.tolist(), depth + 1)
    if hasattr(o, "name") and hasattr(o, "value") and not hasattr(o, "__dict__"):
        return str(o.name)
    if hasattr(o, "__dict__"):
        return {"_t": type(o).__name__, **{k: _canon(v, depth + 1) for k, v in sorted(vars(o).items()) if not k.startswith("_")}}
    return str(o)


def strategy_fingerprint(strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str) -> str:
    """Dấu vân tay cấu hình chiến lược của bot = băm các slot ĐÃ GIẢI (cùng slot_pairs với backtest): id, chiều, cây điều kiện, stop, tham số vị thế, SlotSpec (không gồm tài sản/tài khoản).
    Hai lần chạy cùng (chiến lược, khung tín hiệu, vị thế) cho cùng dấu vân tay; đổi tham số/cây/khung thì đổi."""
    sym = dat.data_symbol(symbols[0])[0] if symbols else "BTC@perp"
    out = []
    for st, sp in slot_pairs(sym, strategies, base_frame):
        spec = {k: v for k, v in vars(sp).items() if k not in ("account_id", "campaign_id", "symbol", "entry_equity", "initial_capital")}
        out.append({"id": st.get("id"), "side": st.get("side"), "tree": st.get("tree"), "stop": st.get("stop"), "position": st.get("position"),
                    "regime": st.get("regime"), "spec": spec})
    blob = json.dumps({"base_frame": base_frame, "slots": _canon(out)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def live_books(strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str) -> List[Dict[str, Any]]:
    """`books` của live = cùng dạng books của backtest (tài sản + [{strategy, slot}]) nhưng chưa có mảng tín hiệu — slot dựng bằng CÙNG slot_pairs của backtest."""
    books = []
    for sym in symbols:
        pairs = slot_pairs(sym, strategies, base_frame)
        if pairs:
            books.append({"symbol": sym, "entries": [{"strategy": st["id"], "slot": sp} for st, sp in pairs]})
    if not books:
        raise ValueError("Không có chiến lược nào chạy trên các tài sản đã chọn")
    return books


# Mạng của client dữ liệu OKX: HTTP chờ tối đa 20s, thử lại 5 lần với backoff 1s -> 15s (mặc định 60s/3 lần: nối WS lỗi thì treo lâu mà vẫn "chạy").
DATA_CLIENT_NET = dict(http_timeout_secs=20, max_retries=5, retry_delay_initial_ms=1000, retry_delay_max_ms=15000)
READY_BASE_S = 120.0          # hạn dựng kết nối dữ liệu (cộng 2 khung nếu khung chạy <= 5m còn đòi có nến đầu)
STALL_FRAMES = 3              # không nến nào tới trong chừng này khung -> data_stall
MAX_DATA_ATTEMPTS = 3         # số lần dựng lại node vì dữ liệu hỏng (liên tiếp) trước khi bot "failed"
BACKOFF_S = (5.0, 15.0, 45.0)


def build_node(mode: str, strategies: List[Dict[str, Any]], symbols: List[str],
               capital: float, base_frame: str = "1h", confirm_live: bool = False,
               bot_id: Optional[str] = None, risk: Optional[Dict[str, Any]] = None,
               native: Optional[Dict[str, Any]] = None, enter_on_start: bool = False, resume: bool = False,
               launch_params: Optional[Dict[str, Any]] = None) -> TradingNode:
    """Dựng TradingNode Nautilus (đã `build()`: client + factory đã đăng ký, Strategy + RecorderActor đã thêm) cho Paper, Testnet hoặc Live.

    strategies: chiến lược của Plan (id, side, tree, stop, position) — mỗi (chiến lược × tài sản) thành một NoraSlotStrategy qua backtest.build_slots (cùng đường với backtest).
    native: {"cls": Strategy do người dùng viết, "params": {...}, "id": str} -> dựng như run_native (build_user_strategy), không có slot DSL.
    resume=True: chạy lại bot ĐÃ CÓ (cùng thư mục, cùng cl_tag; events/equity chỉ NỐI THÊM; Nautilus đối soát vị thế/lệnh của sàn rồi chiến lược nhận lại vị thế).
    Không gọi mạng: nạp lịch sử tín hiệu là `warm_start(node)`; kết nối sàn xảy ra khi `node.run()`."""
    if mode not in ("paper", "testnet", "live"):
        raise ValueError(f"Mode không hợp lệ: {mode}")

    if mode == "live" and not confirm_live:
        raise ValueError("Chế độ Live tiền thật bị khoá — yêu cầu confirm_live=True để xác nhận!")
    if base_frame not in FRAME_MS:
        raise ValueError(f"Khung không hợp lệ: {base_frame!r}")

    bot_id = bot_id or new_bot_id(mode)
    creds = load_okx_credentials()
    if mode in ("testnet", "live") and not _has_keys(creds):
        raise ValueError("Thiếu khoá OKX (~/.config/nora/okx.env) cho mode " + mode)
    if mode == "testnet" and not creds["is_demo"]:
        raise ValueError("Testnet yêu cầu khoá OKX DEMO (NORA_OKX_DEMO=1)")
    if mode == "live" and creds["is_demo"]:
        raise ValueError("Live yêu cầu khoá OKX thật, nhưng okx.env đang là khoá DEMO")

    bot_dir = open_bot_dir(mode, bot_id, resume)                  # bot mới: từ chối nếu id đã tồn tại; resume: mở lại thư mục cũ
    prev = _read_json(os.path.join(bot_dir, "bot.json")) if resume else {}
    legacy = bool(resume and not prev.get("cl_tag"))             # bot cũ (trước cl_tag): giữ trader id cũ, sổ nhận mọi fill đã ghi
    cl_tag = None if legacy else (prev.get("cl_tag") or led.new_cl_tag(_all_cl_tags()))     # tiền tố clOrdId RIÊNG của bot: sở hữu lệnh/fill trên tài khoản sàn dùng chung
    own = led.OwnLedger(capital, cl_tag)
    for e in led.read_events(os.path.join(bot_dir, "events.jsonl")):      # resume: dựng lại sổ vốn từ fill đã ghi
        own.add_event(e)
    write_json_atomic(os.path.join(bot_dir, "bot.json"), {**prev, "bot_id": bot_id, "mode": mode, "capital": capital, "cl_tag": cl_tag, "status": "starting",
                                                          "pid": os.getpid(), "pid_start": pid_start_ticks(os.getpid()), "started_at": prev.get("started_at") or int(time.time() * 1000),
                                                          **({"launch_params": launch_params} if launch_params else {})}, indent=2)
    syms = list(dict.fromkeys(dat.data_symbol(s)[0] for s in symbols))
    ids = [_iid(s) for s in syms]
    id_strs = frozenset(str(i) for i in ids)
    books = live_books(strategies, syms, base_frame) if native is None else []
    max_lev = max([float(e["slot"].max_leverage) for b in books for e in b["entries"]] + [1.0])
    prov = InstrumentProviderConfig(load_ids=id_strs)

    # ── client dữ liệu: nến + giá thị trường thật của OKX (Paper dùng dữ liệu công khai LIVE, Testnet/Live dùng môi trường của chính chúng) ──
    env = OKXEnvironment.DEMO if mode == "testnet" else OKXEnvironment.LIVE
    keyed = mode in ("testnet", "live")
    common = dict(instrument_types=(OKXInstrumentType.SWAP,), contract_types=(OKXContractType.LINEAR,), environment=env, instrument_provider=prov)
    # Client HTTP Rust của adapter đòi có khoá (config hoặc biến môi trường OKX_API_*) dù chỉ lấy dữ liệu công khai, còn WS "business" (nến) mà có khoá thì đăng nhập
    # và sẽ lỗi nếu khoá sai môi trường. Paper: để config không có khoá (WS công khai, không đăng nhập) + chuỗi giữ chỗ trong env cho client HTTP
    # (không phải khoá thật; chỉ gọi endpoint công khai).
    if not keyed:
        for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
            os.environ.setdefault(var, "nora-paper-public")
    data_cfg = OKXDataClientConfig(api_key=creds["key"] if keyed else None, api_secret=creds["secret"] if keyed else None,
                                   api_passphrase=creds["passphrase"] if keyed else None, **DATA_CLIENT_NET, **common)

    # ── client khớp lệnh: Paper = Sandbox (khớp theo QuoteTick thật), Testnet/Live = OKX ──
    if mode == "paper":
        exec_cfg = SandboxExecutionClientConfig(venue="OKX", starting_balances=[f"{capital:g} USDT"], base_currency="USDT", oms_type="NETTING",
                                                account_type="MARGIN", default_leverage=Decimal(str(max_lev)), bar_execution=False, trade_execution=False,
                                                reject_stop_orders=False, instrument_provider=prov)
        exec_clients: Dict[str, Any] = {"SANDBOX": exec_cfg}
    else:
        exec_clients = {"OKX": OKXExecClientConfig(api_key=creds["key"], api_secret=creds["secret"], api_passphrase=creds["passphrase"],
                                                   margin_mode=OKXMarginMode.CROSS, **common)}

    node_cfg = TradingNodeConfig(
        trader_id=TraderId(f"NORA-{cl_tag}" if cl_tag else f"NORA-{mode.upper()}-{zlib.crc32(bot_id.encode()) % 10 ** 6:06d}"),
        logging=LoggingConfig(log_level="INFO", log_level_file="INFO", log_directory=bot_dir, log_file_name="nautilus", log_colors=False),
        data_clients={"OKX": data_cfg},
        exec_clients=exec_clients,
        exec_engine=LiveExecEngineConfig(reconciliation=(mode != "paper"), reconciliation_lookback_mins=(1440 if resume else 5), reconciliation_instrument_ids=ids),
        risk_engine=LiveRiskEngineConfig(bypass=False, max_notional_per_order={str(i): int(capital * max_lev) for i in ids}),
        timeout_connection=120.0, timeout_reconciliation=60.0,
    )
    node = TradingNode(config=node_cfg)
    node.add_data_client_factory("OKX", OKXLiveDataClientFactory)
    node.add_exec_client_factory("OKX" if mode != "paper" else "SANDBOX", OKXLiveExecClientFactory if mode != "paper" else SandboxLiveExecClientFactory)
    node.build()

    # ── số dư RIÊNG của bot = vốn + PnL đã chốt − phí, từ fill của chính bot (OwnLedger). KHÔNG đọc số dư tài khoản sàn: tài khoản dùng chung nhiều bot,
    #    có vị thế mồ côi / phí cũ -> đọc vào sẽ sai vốn và sai cỡ lệnh. ──
    venue = cat.VENUE_OKX
    fr_ms = FRAME_MS[base_frame]

    def balance_fn() -> float:
        return own.balance()

    start_ms = int(time.time() * 1000)
    rk = RiskConfig.from_dict(risk) if risk else RiskConfig()
    coord = Coordinator(rk, capital, start_ms, balance_fn, max(len(books), 1), fr_ms)

    sigs: List[LiveSignals] = []
    if native is None:
        insts = book_instruments(books, cat.instrument_spec)
        by_id = {st["id"]: st for st in strategies}

        def live_sig(b_i: int, b: Dict[str, Any], e: Dict[str, Any]) -> LiveSignals:
            sig = LiveSignals(dat.normalize_symbol(b["symbol"]), by_id[e["strategy"]], base_frame)
            sigs.append(sig)
            return sig
        slots = build_slots(books, insts, base_frame, coord, lambda i: None, False, start_ms, live_sig, hyphens=False, claim_external=bool(resume and mode != "paper"))
        coord.live_n = len(slots)
        for s in slots:
            s.enter_on_start = bool(enter_on_start)
            s.reduce_only = mode == "paper"
            s.own_orders_only, s.resume = True, bool(resume and mode != "paper")
            s.bar_ts_shift_ms = fr_ms          # adapter OKX đặt ts_event = GIỜ MỞ nến (đo thực tế); catalog/backtest = giờ ĐÓNG -> cộng 1 khung
        for s in slots:
            node.trader.add_strategy(s)
        user_strategies: List[Any] = []
    else:
        insts = {dat.normalize_symbol(s): cat.get_instrument(s) for s in syms}
        bar_types = [cat.get_bar_type(s, base_frame) for s in syms]
        user = build_user_strategy(native["cls"], native.get("id") or "NATIVE_STRAT", insts, bar_types, native.get("params") or {})
        node.trader.add_strategy(user)
        slots, user_strategies = [], [user]

    health = [cat.get_bar_type(s, "1m") for s in syms] if (fr_ms > HEALTH_BARS_ABOVE_MS and mode != "paper") else []     # paper đã có QuoteTick; testnet/live: nến 1m (chỉ để biết dữ liệu còn tới)
    recorder = RecorderActor(bot_dir, coord, quote_ids=ids if mode == "paper" else [], ledger=own, health_bar_types=health)
    coord.recorder = recorder
    node.trader.add_actor(recorder)

    node.nora = SimpleNamespace(bot_id=bot_id, mode=mode, bot_dir=bot_dir, slots=slots, signals=sigs, coord=coord, recorder=recorder, ledger=own, cl_tag=cl_tag, user_strategies=user_strategies,
                                instrument_ids=[str(i) for i in ids], base_frame=base_frame)
    spec = {**prev, "bot_id": bot_id, "mode": mode, "symbols": syms, "instruments": [str(i) for i in ids],
            "strategies": [x.get("id") for x in strategies] if native is None else [native.get("id") or "NATIVE_STRAT"],
            "slots": len(slots), "capital": capital, "base_frame": base_frame, "started_at": prev.get("started_at") or start_ms, "status": "starting",
            "cl_tag": cl_tag, "pid": os.getpid(), "pid_start": pid_start_ticks(os.getpid()), **({"launch_params": launch_params} if launch_params else {})}
    write_json_atomic(os.path.join(bot_dir, "bot.json"), spec, indent=2)
    return node


def warm_start(node: Any, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
    """Nạp lịch sử cho mọi LiveSignals của bot: catalog + REST OKX tới nến đóng gần nhất (CÓ MẠNG). Trả thống kê từng slot."""
    from concurrent.futures import ThreadPoolExecutor
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    with ThreadPoolExecutor(max_workers=2) as pool:        # 2 luồng: REST history-candles của OKX giới hạn ~10 yêu cầu/giây/IP
        return list(pool.map(lambda sg: {"symbol": sg.symbol, **sg.warm_start(now)}, node.nora.signals))


class DataWatch(threading.Thread):
    """Giám sát dữ liệu của node đang chạy: (1) khởi động — client dữ liệu phải nối được (và với khung <= 5m, mọi slot phải nhận nến đầu) trong READY_BASE_S;
    (2) đang chạy — không nến nào tới trong STALL_FRAMES khung, hoặc client mất kết nối quá lâu -> `data_stall`. Hỏng thì ghi `self.failure` và dừng node
    (run_node dựng lại). Khung lớn (> 5m) không thể chờ nến đầu (1h = hàng giờ) nên chỉ đòi kết nối."""

    def __init__(self, node: Any, ready_s: float = READY_BASE_S, poll_s: float = 2.0, clock=time.time):
        super().__init__(daemon=True, name="nora-datawatch")
        self.node: Any = node
        self.poll_s: float = poll_s
        self.clock = clock
        fr_s = FRAME_MS[node.nora.base_frame] / 1000.0
        self.frame_s = fr_s
        self.need_bars = fr_s <= 300 and bool(node.nora.slots)
        self.ready_s = ready_s + (2 * fr_s if self.need_bars else 0.0)
        self.ready_at: Optional[float] = None
        self.t0: float = clock()
        self.disc_since: Optional[float] = None
        self.failure: Optional[str] = None
        self.done = threading.Event()

    def connected(self) -> bool:
        try:
            return bool(self.node.kernel.data_engine.check_connected())
        except Exception:
            return False

    def last_bar_wall(self) -> float:
        return max([getattr(s, "last_bar_wall", 0.0) for s in self.node.nora.slots] + [0.0])

    def verdict(self, now: float) -> Optional[str]:
        """None = ổn; chuỗi = lý do hỏng (`connect_timeout` | `no_bars` | `data_stall` | `disconnected`)."""
        conn = self.connected()
        if self.ready_at is None:
            bars = (not self.need_bars) or all(getattr(s, "nbar", 0) > 0 for s in self.node.nora.slots)
            if conn and bars:
                self.ready_at = now
                return None
            if now - self.t0 > self.ready_s:
                return "no_bars" if conn else "connect_timeout"
            return None
        if not conn:
            self.disc_since = self.disc_since or now
            return "disconnected" if now - self.disc_since > 60.0 else None
        self.disc_since = None
        if self.node.nora.slots:
            ref = max(self.last_bar_wall(), self.ready_at)
            if now - ref > STALL_FRAMES * self.frame_s + 60.0:
                return "data_stall"
        return None

    def run(self) -> None:
        while not self.done.wait(self.poll_s):
            why = self.verdict(self.clock())
            if why:
                self.failure = why
                try:
                    self.node.nora.recorder.record_event("data_stall", {"reason": why, "frame_s": self.frame_s, "last_bar_ms": int(self.last_bar_wall() * 1000)})
                except Exception:
                    pass
                loop = self.node.kernel.loop
                loop.call_soon_threadsafe(self.node.stop)
                if not self.done.wait(30.0):                  # node.stop treo (client chưa nối) -> dừng thẳng vòng lặp
                    loop.call_soon_threadsafe(loop.stop)
                return


def run_node(node: Any) -> Optional[str]:
    """node.run() kèm DataWatch. Trả về lý do hỏng dữ liệu (xem DataWatch.verdict) hoặc None nếu node thoát bình thường / do người dùng dừng."""
    watch = DataWatch(node)
    watch.start()
    try:
        node.run()
    finally:
        watch.done.set()
    node.nora.was_ready = watch.ready_at is not None        # đã từng nhận dữ liệu ổn: lần hỏng sau đếm lại từ đầu
    return watch.failure


def set_status(bot_dir: str, status: str, **extra: Any) -> None:
    """Cập nhật bot.json (status: starting | running | stopped | failed). Chỉ TIẾN TRÌNH BOT ghi trường status (người dùng dừng = file cờ `stop`, không sửa bot.json)."""
    path = os.path.join(bot_dir, "bot.json")
    meta = _read_json(path)
    meta.update(status=status, **extra)
    if status in ("stopped", "failed") and not meta.get("stopped_at"):
        meta["stopped_at"] = int(time.time() * 1000)
    if status in ("starting", "running"):
        meta.pop("stopped_at", None)
    write_json_atomic(path, meta, indent=2)


# ─── Trạng thái bot: MỘT nguồn (bot.json + tiến trình còn sống + cờ người dùng dừng) ─────────────────────
MAX_RESUME_FAILURES = 5          # chạy lại liên tiếp mà không lên được "running" quá số này -> failed (vòng lặp sập)
ACTIVE_STATES = ("starting", "running", "resuming", "stopping")


def stop_flag(b_dir: str) -> Optional[Dict[str, Any]]:
    """Cờ người dùng dừng bot (file `stop` do POST /live/bot/{id}/stop ghi): {stopped_at, close} hoặc None."""
    path = os.path.join(b_dir, "stop")
    if not os.path.isfile(path):
        return None
    out: Dict[str, Any] = {"close": True}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                if k == "close":
                    out["close"] = v.strip().lower() == "true"
                elif k == "stopped_at" and v.strip().isdigit():
                    out["stopped_at"] = int(v)
    except OSError:
        pass
    return out


def bot_alive(meta: Dict[str, Any]) -> bool:
    return pid_alive(meta.get("pid"), meta.get("pid_start"))


def bot_status(meta: Dict[str, Any], b_dir: str) -> str:
    """starting | running | resuming | stopping | stopped | failed — MỘT hàm cho /live/bots, chi tiết bot và danh sách Công việc.
    Người dùng đã dừng: còn tiến trình = stopping, hết = stopped. Còn lại theo bot.json + tiến trình: đang chạy mà tiến trình chết (sập / API khởi động lại /
    máy khởi động lại) = resuming (supervisor chạy lại CÙNG bot_id), quá MAX_RESUME_FAILURES lần liền = failed."""
    alive = bot_alive(meta)
    if stop_flag(b_dir) is not None:
        return "stopping" if alive else "stopped"
    st = meta.get("status")
    if st == "stopped":
        return "stopped"
    if st == "failed":
        return "failed"
    if st in ("running", "starting"):
        if alive:
            return st
        return "failed" if int(meta.get("resume_failures") or 0) >= MAX_RESUME_FAILURES else "resuming"
    return "stopped"


def _mdd_pct(values: List[float]) -> float:
    peak, mdd = float("-inf"), 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100.0)
    return round(mdd, 4)


def _bot_summary(meta: Dict[str, Any], b_dir: str, mode: str, snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snap = snap or led.snapshot(b_dir, meta)
    status = bot_status(meta, b_dir)
    started = meta.get("started_at")
    out = {
        "bot_id": meta.get("bot_id", os.path.basename(b_dir)), "mode": mode,
        "strategy": meta.get("strategy") or ", ".join(meta.get("strategies") or []),
        "symbols": meta.get("symbols", []), "strategies": meta.get("strategies", []), "capital": snap["capital"],
        "equity": round(snap["equity"], 4), "pnl_usd": round(snap["pnl_usd"], 4), "pnl_pct": round(snap["pnl_pct"], 4),
        "mdd_pct": _mdd_pct([snap["capital"]] + [r["equity"] for r in snap["series"]]), "status": status,
        "started_at": started, "stopped_at": meta.get("stopped_at") if status == "stopped" else None,
        "samples": len(snap["series"]), "job_id": meta.get("job_id"), "cl_tag": meta.get("cl_tag"),
    }
    if status in ("running", "stopping") and started:
        out["uptime_seconds"] = max(0, int(time.time() - started / 1000))
    hb = _read_json(os.path.join(b_dir, "heartbeat.json"))
    if hb:
        out["heartbeat"] = hb
    if mode == "paper" and (not meta.get("cl_tag") or "sandbox" in str(meta.get("engine", "")).lower()):
        out["sub_note"] = "mô phỏng nội bộ"
    return out


def list_bots(mode: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lấy danh sách các bot (paper/testnet/live) trên đĩa."""
    bots_dir = os.path.join(data_home(), "live")
    items = []
    for m in ([mode] if mode else list(MODES)):
        m_dir = os.path.join(bots_dir, m)
        if not os.path.isdir(m_dir):
            continue
        for b_name in os.listdir(m_dir):
            meta = _read_json(os.path.join(m_dir, b_name, "bot.json"))
            if meta:
                items.append((meta, os.path.join(m_dir, b_name), m))
    if not items:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(24, len(items))) as pool:
        res = list(pool.map(lambda it: _bot_summary(it[0], it[1], it[2]), items))
    return sorted(res, key=lambda x: x.get("started_at") or 0, reverse=True)


def shared_instruments(bot_id: str, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cảnh báo dùng chung tài khoản: bot khác ĐANG HOẠT ĐỘNG cùng mode testnet/live (cùng một tài khoản OKX) giao dịch cùng instrument.
    Paper: mỗi bot có Sandbox riêng -> không bao giờ dùng chung."""
    mode = meta.get("mode")
    if mode not in ("testnet", "live"):
        return []
    mine = set(meta.get("instruments") or [])
    if not mine:
        return []
    out = []
    root = os.path.join(data_home(), "live", mode)
    if not os.path.isdir(root):
        return []
    for other_id in os.listdir(root):
        if other_id == bot_id:
            continue
        d = os.path.join(root, other_id)
        om = _read_json(os.path.join(d, "bot.json"))
        if not om or bot_status(om, d) not in ACTIVE_STATES:
            continue
        for inst in sorted(mine & set(om.get("instruments") or [])):
            out.append({"instrument": inst, "bot_id": other_id})
    return out


def bot_metrics(snap: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Số đo của bot = CÙNG hàm của backtest (metrics/metrics + metrics/trades + nautilus/stats) áp lên fill + đường vốn RIÊNG của bot."""
    from backend.analys.metrics import metrics as mt
    from backend.analys.metrics.trades import rows_from_trade_list, trade_metrics, trade_stats
    capital = snap["capital"]
    curve = [{"time": r["time"], "equity": r["equity"], "equity_worst": r.get("equity_worst", r["equity"])} for r in snap["series"]]
    start = int(meta.get("started_at") or (curve[0]["time"] if curve else 0))
    daily = mt.daily_returns_from_curve(curve, start, capital) if capital > 0 else []
    rows = rows_from_trade_list(snap["trades"])
    ts = trade_stats(rows)
    rm = mt.return_metrics(daily)
    n_closed = len(rows)
    n_open = len(snap.get("positions") or [])
    reasons: Dict[str, Optional[str]] = {"sharpe": None, "win_rate": None, "profit_factor": None}
    if rm["sharpe"] is None:
        reasons["sharpe"] = "Cần ≥ 2 ngày dữ liệu" if rm["days"] < 2 else "Không xác định (lợi suất ngày không biến động)"
    if ts["win_rate"] is None:
        reasons["win_rate"] = "Chưa có lệnh đóng"
    if ts["profit_factor"] is None:
        note = ts["profit_factor_note"]
        reasons["profit_factor"] = "Chưa có lệnh đóng" if n_closed == 0 else ("Chưa có lệnh thua" if note == "không có lệnh thua" else note)
    return {"ret_pct": round(snap["pnl_pct"], 2), "mdd_pct": round(mt.curve_mdd_pct(curve, start, capital), 2) if curve else 0.0,
            "mdd_basis": "intrabar", "sharpe": mt._r(rm["sharpe"]), "sortino": mt._r(rm["sortino"]), "profit_factor": ts["profit_factor"], "profit_factor_note": ts["profit_factor_note"],
            "win_rate": ts["win_rate"], "trades": n_closed, "trades_closed": n_closed, "trades_open": n_open, "days": int(rm["days"]), "reasons": reasons,
            "fees_usd": round(snap["fees_usd"], 6), "pnl_usd": round(snap["pnl_usd"], 4),
            "equity": round(snap["equity"], 4), "balance": round(snap["balance"], 4), "unrealized_usd": round(snap["unrealized"], 4),
            "stats": {"returns": rm, "trades": trade_metrics(rows)}}


def get_bot_detail(bot_id: str) -> Optional[Dict[str, Any]]:
    """Chi tiết 1 bot: tóm tắt + spec + số đo (cùng hàm backtest) + lệnh (dạng trade_list backtest) + đường vốn + vị thế mở + fill gần đây + cảnh báo dùng chung instrument."""
    b_dir = find_bot_dir(bot_id)
    if b_dir is None:
        return None
    meta = _read_json(os.path.join(b_dir, "bot.json"))
    if not meta:
        return None
    mode = os.path.basename(os.path.dirname(b_dir))
    snap = led.snapshot(b_dir, meta)
    summ = _bot_summary(meta, b_dir, mode, snap)
    series = [{"t": r["time"], "time": r["time"], "equity": r["equity"], "balance": r.get("balance")} for r in snap["series"][-1000:]]
    fp = {"strategy_fingerprint": meta.get("strategy_fingerprint"), "expected": meta.get("fingerprint_expected"), "match": meta.get("fingerprint_match")}
    return {**summ, "fingerprint": fp, "spec": meta, "metrics": bot_metrics(snap, meta), "trades": snap["trades"], "equity_series": series, "positions": snap["positions"],
            "fills": get_bot_trades(bot_id)[-50:], "shared_instruments": shared_instruments(bot_id, meta),
            "user_stopped": stop_flag(b_dir) is not None}


def stop_bot(bot_id: str, close_positions: bool = True) -> Dict[str, Any]:
    """ĐƯỜNG DUY NHẤT dừng bot (và duy nhất đóng vị thế): ghi cờ `stop` {close}. Tiến trình bot thấy cờ -> (close) huỷ lệnh chờ + đóng đúng vị thế của bot -> dừng node.
    Tiến trình đã chết (chưa kịp dọn): close=True ở testnet/live -> đóng phần net của RIÊNG bot (tổng fill của bot) bằng lệnh reduce-only đúng cỡ; rồi chốt stopped."""
    b_dir = find_bot_dir(bot_id)
    if b_dir is None:
        return {"ok": False, "message": f"Không tìm thấy bot {bot_id}"}
    meta = _read_json(os.path.join(b_dir, "bot.json"))
    mode = os.path.basename(os.path.dirname(b_dir))
    with open(os.path.join(b_dir, "stop"), "w", encoding="utf-8") as f:
        f.write(f"stopped_at={int(time.time() * 1000)}\nclose={bool(close_positions)}\n")
    if bot_alive(meta):
        return {"ok": True, "bot_id": bot_id, "status": "stopping", "close": bool(close_positions)}
    closed: List[Dict[str, Any]] = []
    if close_positions and mode in ("testnet", "live") and meta.get("status") in ("running", "starting"):
        closed = close_own_via_rest(b_dir, meta, mode)
    if meta.get("status") != "stopped":
        set_status(b_dir, "stopped")
    return {"ok": True, "bot_id": bot_id, "status": "stopped", "close": bool(close_positions), "closed": closed}


def apply_stop(node: Any, close: bool) -> None:
    """Chạy TRÊN LUỒNG SỰ KIỆN của node khi người dùng dừng bot. close=True: mỗi chiến lược huỷ lệnh chờ CỦA NÓ rồi đóng đúng vị thế CỦA NÓ (reduce-only đúng cỡ);
    close=False: giữ nguyên lệnh + vị thế (người dùng chọn). Không bao giờ đụng vị thế/lệnh bot khác."""
    if not close:
        return
    for sl in node.nora.slots:
        sl.stop_close(True)
    for u in node.nora.user_strategies:
        for iid in node.nora.instrument_ids:
            ii = InstrumentId.from_str(iid)
            own = [o for o in u.cache.orders_open(instrument_id=ii, strategy_id=u.id) if not o.is_closed]
            if own:
                u.cancel_orders(own)
            if u.cache.positions_open(instrument_id=ii, strategy_id=u.id):
                u.close_all_positions(ii, tags=["STOP"])


def own_flat(node: Any) -> bool:
    """Bot không còn vị thế mở nào (theo sổ riêng của bot)."""
    return not node.nora.ledger.open_positions()


def close_own_via_rest(b_dir: str, meta: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    """Bot đã chết mà người dùng bấm dừng + đóng: với MỖI instrument chỉ đóng net RIÊNG của bot (Σ fill của bot theo cl_tag) bằng một lệnh market reduce-only đúng cỡ,
    clOrdId mang cl_tag của bot. KHÔNG đóng vị thế net của tài khoản (có thể gồm bot khác). Trả danh sách lệnh đã gửi."""
    ledger = led.ledger_from_dir(b_dir, float(meta.get("capital") or 0.0), meta.get("cl_tag"))
    sent = []
    for i, (symbol, net) in enumerate(sorted(ledger.net_by_symbol().items())):
        inst = cat.normalize_symbol(symbol)
        ct_val = float(cat.instrument_spec(inst)["ctVal"])
        sz = abs(net) / ct_val
        cl = f"O{time.strftime('%Y%m%d%H%M%S', time.gmtime())}{meta.get('cl_tag') or ''}X{i:02d}"[:32]
        body = {"instId": inst, "tdMode": "cross", "side": "sell" if net > 0 else "buy", "ordType": "market", "sz": f"{sz:.8f}".rstrip("0").rstrip("."),
                "reduceOnly": True, "clOrdId": cl}
        status, res = _okx_signed("POST", "/api/v5/trade/order", mode != "live", body)
        sent.append({"instrument": inst, "side": body["side"], "sz": body["sz"], "clOrdId": cl, "http": status, "code": str(res.get("code"))})
    return sent


def delete_bot(bot_id: str, mode: Optional[str] = None) -> Dict[str, Any]:
    """Xoá thư mục data/live/<mode>/<bot_id>/ (kể cả bot cũ đã lưu trữ). Bot đang hoạt động (kể cả đang chạy lại) -> {"ok": False, "running": True}; không thấy -> {"ok": False}."""
    import shutil
    if not bot_id or bot_id != os.path.basename(bot_id) or bot_id.startswith("."):
        return {"ok": False, "message": "bot_id không hợp lệ"}
    for m in ((mode,) if mode in MODES else MODES):
        b_dir = os.path.join(data_home(), "live", m, bot_id)
        if os.path.isdir(b_dir):
            meta = _read_json(os.path.join(b_dir, "bot.json"))
            if meta and bot_status(meta, b_dir) in ACTIVE_STATES:
                return {"ok": False, "running": True, "message": "Dừng bot trước khi xoá"}
            shutil.rmtree(b_dir)
            return {"ok": True, "bot_id": bot_id, "mode": m, "deleted": True}
    return {"ok": False, "message": f"Không tìm thấy bot {bot_id}"}


def get_bot_trades(bot_id: str, raw: bool = False) -> List[Dict[str, Any]]:
    """Lệnh khớp của bot từ events.jsonl (chỉ fill của CHÍNH bot — theo cl_tag): {t, symbol, side, qty, price, pnl, tag} (pnl = lãi/lỗ đã chốt của vị thế khi fill đóng nó, ngược lại None).
    raw=True: sự kiện gốc (cho compare_events)."""
    b_dir = find_bot_dir(bot_id)
    if b_dir is None or not os.path.isfile(os.path.join(b_dir, "events.jsonl")):
        return []
    tag = _read_json(os.path.join(b_dir, "bot.json")).get("cl_tag")
    evs = [e for e in _read_events(os.path.join(b_dir, "events.jsonl")) if e.get("type") != "fill" or led.owns(tag, e.get("client_order_id"))]
    if raw:
        return [e for e in evs if e.get("type") in ("fill", "reject")]
    out: List[Dict[str, Any]] = []
    last_exit: Dict[str, Dict[str, Any]] = {}
    for e in evs:
        if e.get("type") == "fill":
            row = {"t": e.get("ts") or e.get("t"), "symbol": e.get("symbol"), "side": e.get("side"), "qty": e.get("qty"), "price": e.get("px"),
                   "pnl": None, "tag": e.get("kind"), "fee": e.get("fee")}
            out.append(row)
            if e.get("kind") not in ("ENTRY", "DCA"):
                last_exit[e.get("symbol")] = row
        elif e.get("type") == "position_closed" and last_exit.get(e.get("symbol")) is not None:
            last_exit[e.get("symbol")]["pnl"] = e.get("pnl")
    return out


# ── Lịch sử bot cũ (CHỈ ĐỌC) ──────────────────────────────────────────────────
ARCHIVE_NOTE = "Dữ liệu bot cũ (đã dừng)"


def archived_dir(venue: str, mode: str, book: str = "main", engine: Any = None) -> str:
    from backend.models.storage import live_dir
    return live_dir(venue, mode, book, engine if isinstance(engine, str) and engine else None)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_events(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        pass
    return out


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def archived_bot(venue: str, mode: str, book: str = "main", engine: Any = None, events: int = 50) -> Dict[str, Any]:
    d = archived_dir(venue, mode, book, engine)
    state = _read_json(os.path.join(d, "state.json")) or None
    evs = _read_events(os.path.join(d, "events.jsonl"))[-events:] if events else []
    if state:
        state = {**state, "trades": (state.get("trades") or [])[-100:]}
    return {"venue": venue, "mode": mode, "status": "archived", "archived": True, "note": ARCHIVE_NOTE, "running": [], "state": state,
            "events": evs, "book": book, "engine": engine or ("legacy" if mode == "paper" else "unified")}


def archived_trades(venue: str, mode: str, book: str = "main", engine: Any = None, limit: int = 200) -> Dict[str, Any]:
    from backend.analys.metrics.metrics import equity_series_summary, pnl_since_start
    d = archived_dir(venue, mode, book, engine)
    state = _read_json(os.path.join(d, "state.json"))
    evs = _read_events(os.path.join(d, "events.jsonl"))
    by_bar, started, alerts, start_evt = {}, None, [], {}
    for e in evs:
        k = e.get("kind")
        if k == "start":
            started = e.get("t") if started is None else started
            alerts, start_evt = [], e
        elif k in ("crit", "warn"):
            alerts = (alerts + [e])[-5:]
        elif k == "step" and _num(e.get("bar")) and _num(e.get("equity")):
            by_bar[int(e["bar"])] = float(e["equity"])
    ordered = sorted(by_bar.items())
    summ = equity_series_summary([v for _, v in ordered])
    raw_cur = state.get("equity")
    cur = float(raw_cur) if raw_cur is not None and _num(raw_cur) else summ["last"]
    stats = {"bars": summ["bars"], "start": summ["start"], "equity": cur, "mdd_pct": summ["mdd_pct"], "mdd_note": summ["mdd_note"], **pnl_since_start(summ["start"], cur)}
    trades = (state.get("trades") or [])[-limit:]
    positions = [{"symbol": s, **p} for s, p in (state.get("positions") or {}).items()]
    ex = {"trades": [], "positions": []} if mode == "paper" else {"trades": trades, "positions": positions}
    pa = {"trades": trades, "positions": positions, "summary": state.get("paper")} if mode == "paper" else {"trades": [], "positions": [], "summary": state.get("paper")}
    strategies = [{"id": s, "unvalidated": s in (start_evt.get("unvalidated") or [])} for s in (start_evt.get("strategies") or [])]
    has = bool(state or evs)
    return {"venue": venue, "mode": mode, "engine": engine or ("legacy" if mode == "paper" else "unified"), "archived": True, "has_data": has, "note": ARCHIVE_NOTE,
            "dir": "/".join(d.rstrip("/").split("/")[-3:]),
            "book_kind": state.get("book_kind") or book, "strategies": strategies, "symbols": start_evt.get("symbols") or [], "timeframe": start_evt.get("timeframe"),
            "running": [], "equity": state.get("equity"), "equity_series": [{"t": t, "equity": v} for t, v in ordered][-2000:], "equity_stats": stats,
            "started": started, "ended": evs[-1].get("t") if evs else None, "halted": bool(state.get("halted")), "peak_equity": state.get("peak_equity"),
            "alerts": alerts, "exec": ex, "paper": pa}


def archived_compare_events(venue: str, mode: str, book: str = "main", engine: Any = None) -> Dict[str, Any]:
    from backend.analys.metrics.trades import compare_events
    d = archived_dir(venue, mode, book, engine)
    path = os.path.join(d, "events.jsonl")
    if not os.path.isfile(path) and engine is None:
        for fallback_eng in ("legacy", "unified"):
            d_fb = archived_dir(venue, mode, book, fallback_eng)
            p_fb = os.path.join(d_fb, "events.jsonl")
            if os.path.isfile(p_fb):
                d = d_fb
                path = p_fb
                engine = fallback_eng
                break
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ex, sm, eq_ex, eq_sm = [], [], [], []
    for e in _read_events(path):
        if e.get("evt") in ("fill", "reject") and e.get("src") in ("exec", "sim"):
            (ex if e["src"] == "exec" else sm).append(e)
        elif e.get("kind") == "step" and _num(e.get("bar")) and _num(e.get("exchange_equity")) and _num(e.get("sim_equity")):
            eq_ex.append({"t": int(e["bar"]), "equity": float(e["exchange_equity"])})
            eq_sm.append({"t": int(e["bar"]), "equity": float(e["sim_equity"])})
    tf = next((e.get("timeframe") for e in _read_events(path) if e.get("kind") == "start" and e.get("timeframe")), None)
    return {"venue": venue, "mode": mode, "book": book, "archived": True, "timeframe": tf, "n_exec": len(ex), "n_sim": len(sm),
            **compare_events(ex, sm, tf or "1h", exec_equity=eq_ex or None, sim_equity=eq_sm or None)}


def archived_bots_index() -> list:
    from backend.models.storage import data_home
    combos = [("paper", "main", None), ("paper", "explore", None), ("demo", "main", "unified"), ("demo", "main", "legacy"), ("live", "main", None)]
    out = []
    for mode, book, eng in combos:
        d = archived_dir("okx", mode, book, eng)
        if not os.path.isfile(os.path.join(d, "state.json")):
            continue
        t = archived_trades("okx", mode, book, eng)
        out.append({"symbols": t["symbols"] or sorted((_read_json(os.path.join(d, "state.json")).get("positions") or {}).keys()), "mode": mode, "tab": {"paper": "paper", "demo": "testnet", "live": "live"}[mode], "book": book, "engine": eng or "legacy", "dir": os.path.relpath(d, data_home()),
                    "started": t["started"], "ended": t["ended"], "equity": t["equity"], "start_equity": t["equity_stats"]["start"], "mdd_pct": t["equity_stats"]["mdd_pct"],
                    "pnl_pct": t["equity_stats"].get("pnl_pct"), "trades": len(t["exec"]["trades"] or t["paper"]["trades"]), "halted": t["halted"], "status": "archived"})
    return out
