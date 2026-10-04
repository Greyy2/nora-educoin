"""Bot giao dịch theo sổ đã xuất bản (E9-S1/S2/S5) — job API `live_bot`.

Chế độ:
  paper    dữ liệu thị trường THẬT (REST công khai, mặc định mainnet), khớp lệnh mô phỏng cùng quy tắc engine — kiểm forward không cần khoá.
  testnet  Binance Futures testnet: lệnh thật trên tài khoản testnet (cần khoá, secrets.py). SL = STOP_MARKET reduce-only, TP = LIMIT reduce-only,
           trailing / timeout / tín hiệu thoát = MARKET reduce-only do bot đóng ở nến kế.
Mỗi nến chạy (khung của sổ) đã đóng: nạp nến các khung -> live.signals.evaluate (đúng đường engine) -> xử lý thoát -> kill switch -> vào lệnh.
Quy tắc khớp engine: tín hiệu ở nến đã đóng -> lệnh ở đầu nến kế; mỗi tài sản tối đa 1 vị thế (max_per_symbol = 1 — khớp chế độ one-way của
sàn); tối đa max_positions vị thế; tổng danh nghĩa <= max_gross_exposure × vốn; cooldown theo (chiến lược, tài sản); khối lượng theo đúng
PositionTracker._risk_margin (cùng mã engine). Kill switch: vốn MTM sụt >= kill_switch_dd_pct từ đỉnh -> đóng hết, huỷ lệnh, dừng mở mới tới
khi người vận hành xoá cờ halted trong state.json.
Khác engine (ghi rõ): trailing chỉ xét ở nến đóng và đóng MARKET ở nến kế (engine khớp ngay trong nến ở mức trailing); paper khớp SL/TP trong
nến như engine. Chưa hỗ trợ DCA (sổ có tầng DCA -> từ chối chạy).
"""
import json
import os
import signal
import time
import warnings
from typing import Any, Dict, List, Optional

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"mode": "paper", "once": False, "max_steps": 0, "data_url": "", "capital": 10000.0, "state_dir": ""}
KLINE_LIMIT = 1500
FEE_TAKER, FEE_MAKER, SLIP = 0.0005, 0.0002, 0.0002


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_book(alphas: Optional[str] = None) -> Dict[str, Any]:
    from backend.core.params.presets import alphas_dir
    base = alphas or alphas_dir()
    with open(os.path.join(base, "book.json"), encoding="utf-8") as fh:
        book = json.load(fh)
    if book.get("status") != "READY_FOR_TESTNET":
        raise SystemExit(f"book.json trạng thái {book.get('status')} — chỉ chạy sổ READY_FOR_TESTNET")
    return book


def book_strategies(book: Dict[str, Any]) -> List[Dict[str, Any]]:
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import CANDIDATES, materialize
    by = {c["id"]: c for c in CANDIDATES}
    tf = book.get("timeframe", "1m")
    return [materialize(by[s["id"]], lift_frames(by[s["id"]], s["params"], tf), risk_per_trade_pct=book["risk_per_trade_pct"],
                        stop_fill="level") for s in book["strategies"]]


class State:
    def __init__(self, path: str, capital: float):
        self.path = path
        self.d: Dict[str, Any] = {"positions": {}, "last_close": {}, "cash": capital, "peak_equity": capital, "halted": False,
                                  "last_bar": None, "trades": []}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.d.update(json.load(fh))

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class Bot:
    def __init__(self, book: Dict[str, Any], mode: str, client, state: State, log, broker_filters: Optional[Dict[str, Any]] = None):
        self.book, self.mode, self.client, self.state, self.log = book, mode, client, state, log
        self.tf = book.get("timeframe", "1m")
        self.strategies = book_strategies(book)
        self.symbols = [s.split("@")[0] for s in book["universe"]]
        self.limits = book["risk"]
        self.filters = broker_filters or {}

    # ── dữ liệu ──
    def frames(self, sym: str, now: int) -> Dict[str, Any]:
        from backend.live import signals as ls
        return {fr: ls.klines_frame(self.client.klines(f"{sym}USDT", fr, KLINE_LIMIT), now)
                for fr in ls.required_frames(f"{sym}@perp", self.strategies, self.tf)}

    # ── vốn ──
    def equity(self, marks: Dict[str, float]) -> float:
        if self.mode == "testnet":
            return float(self.client.account()["totalMarginBalance"])
        eq = self.state.d["cash"]
        for sym, p in self.state.d["positions"].items():
            px = marks.get(sym, p["entry_price"])
            eq += p["qty"] * (px - p["entry_price"]) * (1 if p["side"] == "LONG" else -1)
        return eq

    def event(self, kind: str, **kw) -> None:
        self.log({"t": _now_ms(), "kind": kind, **kw})

    # ── khớp lệnh ──
    def _close(self, sym: str, price: float, reason: str, now: int, market: bool = True) -> None:
        p = self.state.d["positions"].pop(sym)
        sign = 1 if p["side"] == "LONG" else -1
        if self.mode == "testnet":
            self.client.cancel_all(f"{sym}USDT")
            self.client.order(symbol=f"{sym}USDT", side="SELL" if sign > 0 else "BUY", type="MARKET", quantity=p["qty"], reduceOnly="true")
        fill = price * (1 - sign * SLIP) if market else price
        pnl = p["qty"] * (fill - p["entry_price"]) * sign - p["qty"] * fill * (FEE_TAKER if market else FEE_MAKER)
        self.state.d["cash"] += pnl
        self.state.d["last_close"][f"{p['strategy']}|{sym}"] = now
        self.state.d["trades"].append({**p, "close_time": now, "close_price": fill, "pnl": round(pnl, 4), "reason": reason})
        self.event("close", symbol=sym, strategy=p["strategy"], reason=reason, price=fill, pnl=round(pnl, 4))

    def _open(self, sym: str, e: Dict[str, Any], i: int, price: float, equity: float, room: float, now: int) -> None:
        from backend.core.execute.ledger import CapitalLedger
        tr = e["tracker"]
        vol = float(e["vol"][i]) if e["vol"] is not None else float("nan")
        if tr.exit_unit == "atr" and not vol > 0:
            return self.event("skip", symbol=sym, strategy=e["strategy"], reason="chưa có ATR")
        tr.ledger = CapitalLedger(equity)
        tr._apply_exit_unit(vol if tr.exit_unit == "atr" else 1.0)
        tr.max_leverage = tr.leverage
        margin = tr._risk_margin() if tr.sizing == "risk" else equity * tr.order_size_pct / 100.0
        notional = min(margin * tr.pos_leverage, room)
        qty = notional / price
        f = self.filters.get(sym)
        if f is not None:
            qty = f.qty(qty)
            why = f.check(qty, price)
            if why:
                return self.event("skip", symbol=sym, strategy=e["strategy"], reason=why)
        if qty <= 0:
            return
        sign = 1 if e["side"] == "LONG" else -1
        sl = price * (1 - sign * tr.sl_pct / 100.0) if tr.sl_pct else None
        tp = price * (1 + sign * tr.tp_pct / 100.0) if tr.tp_pct else None
        fill = price * (1 + sign * SLIP)
        if self.mode == "testnet":
            s = f"{sym}USDT"
            self.client.set_margin_isolated(s)
            self.client.set_leverage(s, int(tr.pos_leverage))
            r = self.client.order(symbol=s, side="BUY" if sign > 0 else "SELL", type="MARKET", quantity=qty, newOrderRespType="RESULT")
            fill = float(r.get("avgPrice") or price)
            rnd = f.price if f is not None else (lambda x: x)
            if sl:
                self.client.order(symbol=s, side="SELL" if sign > 0 else "BUY", type="STOP_MARKET", stopPrice=rnd(fill * (1 - sign * tr.sl_pct / 100.0)),
                                  closePosition="true", workingType="MARK_PRICE")
            if tp:
                self.client.order(symbol=s, side="SELL" if sign > 0 else "BUY", type="LIMIT", timeInForce="GTC", quantity=qty, reduceOnly="true",
                                  price=rnd(fill * (1 + sign * tr.tp_pct / 100.0)))
        self.state.d["cash"] -= qty * fill * FEE_TAKER
        self.state.d["positions"][sym] = {
            "strategy": e["strategy"], "side": e["side"], "qty": qty, "entry_price": fill, "entry_time": now, "leverage": int(tr.pos_leverage),
            "sl_price": fill * (1 - sign * tr.sl_pct / 100.0) if sl else None, "tp_price": fill * (1 + sign * tr.tp_pct / 100.0) if tp else None,
            "trail_pct": tr.trail_pct, "trail_act_pct": tr.trail_activation_pct, "peak": fill, "timeout_ms": tr.timeout_ms}
        self.event("open", symbol=sym, strategy=e["strategy"], side=e["side"], qty=qty, price=fill, leverage=int(tr.pos_leverage),
                   sl_pct=round(tr.sl_pct, 4), tp_pct=round(tr.tp_pct, 4))

    # ── một nến ──
    def step(self, now: int, data: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Xử lý nến chạy vừa đóng (now = open của nến mới). data (test): {sym: kết quả signals.evaluate}."""
        from backend.live import signals as ls
        d = self.state.d
        sig = data or {s: ls.evaluate(f"{s}@perp", self.strategies, self.frames(s, now), self.tf) for s in self.symbols}
        last = {s: len(v["t"]) - 1 for s, v in sig.items()}
        marks = {s: float(v["close"][last[s]]) for s, v in sig.items()}
        if self.mode == "testnet":
            self.reconcile()
        # 1. thoát (ở đầu nến mới, cùng thứ tự engine: tín hiệu thoát / hết giờ, rồi SL-TP-trailing trong nến vừa đóng)
        for sym in list(d["positions"]):
            p, v, i = d["positions"][sym], sig[sym], last[sym]
            sign = 1 if p["side"] == "LONG" else -1
            e = next(x for x in v["entries"] if x["strategy"] == p["strategy"])
            hi, lo = float(v["high"][i]), float(v["low"][i])
            if self.mode == "paper" and p["sl_price"] and (lo <= p["sl_price"] if sign > 0 else hi >= p["sl_price"]):
                self._close(sym, p["sl_price"], "Stop-loss", now)
                continue
            if self.mode == "paper" and p["tp_price"] and (hi >= p["tp_price"] if sign > 0 else lo <= p["tp_price"]):
                self._close(sym, p["tp_price"], "Take-profit", now, market=False)
                continue
            if p["trail_pct"]:
                gain = sign * (p["peak"] - p["entry_price"]) / p["entry_price"] * 100.0
                level = p["peak"] * (1 - sign * p["trail_pct"] / 100.0)
                if gain >= p["trail_act_pct"] and (lo <= level if sign > 0 else hi >= level):
                    self._close(sym, marks[sym], "Trailing stop", now)
                    continue
            p["peak"] = max(p["peak"], hi) if sign > 0 else min(p["peak"], lo)
            if bool(e["stop"][i]):
                self._close(sym, marks[sym], "Tín hiệu thoát", now)
            elif p["timeout_ms"] and now - p["entry_time"] >= p["timeout_ms"]:
                self._close(sym, marks[sym], "Hết thời gian giữ lệnh", now)
        # 2. kill switch
        eq = self.equity(marks)
        d["peak_equity"] = max(d["peak_equity"], eq)
        kill = float(self.limits.get("kill_switch_dd_pct") or 0)
        if kill and not d["halted"] and eq <= d["peak_equity"] * (1 - kill / 100.0):
            d["halted"] = True
            for sym in list(d["positions"]):
                self._close(sym, marks[sym], "Kill switch", now)
            self.event("crit", reason=f"kill switch: vốn {eq:.2f} <= {100 - kill:.0f}% đỉnh {d['peak_equity']:.2f}")
        # 3. vào lệnh (thứ tự engine: tài sản theo vũ trụ sổ, chiến lược theo thứ tự sổ)
        if not d["halted"]:
            for sym in self.symbols:
                if sym in d["positions"] or sym in d.get("external", []):
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
                    gross = sum(p["qty"] * marks.get(s, p["entry_price"]) for s, p in d["positions"].items())
                    room = float(self.limits["max_gross_exposure"]) * eq - gross
                    if room <= 0:
                        break
                    self._open(sym, e, i, marks[sym], eq, room, now)
                    break
        d["last_bar"] = now
        d["equity"] = round(self.equity(marks), 4)
        self.state.save()
        return {"equity": d["equity"], "positions": len(d["positions"]), "halted": d["halted"]}

    # ── đối soát sàn (E9-S1 AC5) ──
    def reconcile(self) -> None:
        d = self.state.d
        live = {p["symbol"][:-4]: float(p["positionAmt"]) for p in self.client.positions() if float(p["positionAmt"]) != 0.0}
        d["external"] = sorted(s for s in live if s not in d["positions"])       # vị thế không do bot mở: không mở thêm trên tài sản đó
        for sym in list(d["positions"]):
            if sym not in live:                                                     # sàn đã đóng (SL/TP) -> ghi nhận, huỷ lệnh còn treo
                p = d["positions"].pop(sym)
                self.client.cancel_all(f"{sym}USDT")
                d["last_close"][f"{p['strategy']}|{sym}"] = _now_ms()
                self.event("close", symbol=sym, strategy=p["strategy"], reason="Sàn đã đóng (SL/TP)")


def check_book(strategies: List[Dict[str, Any]]) -> None:
    for st in strategies:
        p = st["position"]
        if p.get("dca_steps") or int(p.get("dca_max_layers") or 0):
            raise SystemExit(f"{st['id']}: bot chưa hỗ trợ DCA")


def run_job(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.live.exchange import MAINNET_URL, TESTNET_URL, BinanceFutures, Filters
    from backend.live.secrets import load_keys, redact
    from backend.db.data_layout import cache_dir
    if a.mode not in ("paper", "testnet"):
        raise SystemExit("mode phải là paper | testnet")
    book = load_book()
    keys = load_keys() if a.mode == "testnet" else None
    if a.mode == "testnet" and not keys:
        raise SystemExit("testnet cần khoá: NORA_BINANCE_TESTNET_KEY/SECRET hoặc ~/.config/nora/binance_testnet.env (quyền 600)")
    client = BinanceFutures(a.data_url or (TESTNET_URL if a.mode == "testnet" else MAINNET_URL), keys)
    sdir = a.state_dir or cache_dir(None, "live", a.mode)
    os.makedirs(sdir, exist_ok=True)
    events = os.path.join(sdir, "events.jsonl")

    def log(ev):
        line = redact(json.dumps(ev, ensure_ascii=False, default=str), keys)
        with open(events, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)
    info = client.exchange_info()
    filters = {s.split("@")[0]: Filters.from_info(info, s.split("@")[0] + "USDT") for s in book["universe"]}
    bot = Bot(book, a.mode, client, State(os.path.join(sdir, "state.json"), float(a.capital)), log, filters)
    check_book(bot.strategies)
    if a.mode == "testnet":
        if client._req("GET", "/fapi/v1/positionSide/dual", signed=True).get("dualSidePosition"):
            raise SystemExit("tài khoản đang ở chế độ hedge — bot cần one-way (khớp max_per_symbol = 1)")
        bot.reconcile()
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    step_ms = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[bot.tf]
    log({"t": _now_ms(), "kind": "start", "mode": a.mode, "book": book.get("source"), "timeframe": bot.tf, "symbols": bot.symbols})
    n, res = 0, {}
    while not stop["flag"]:
        now = _now_ms() // step_ms * step_ms
        if bot.state.d.get("last_bar") != now:
            try:
                res = bot.step(now)
                log({"t": _now_ms(), "kind": "step", "bar": now, **res})
            except Exception as e:   # lỗi mạng / sàn: ghi lại, thử ở vòng sau (không mở trùng: đối soát đầu mỗi bước)
                log({"t": _now_ms(), "kind": "error", "error": redact(str(e), keys)})
            n += 1
            if a.once or (a.max_steps and n >= a.max_steps):
                break
        time.sleep(min(30.0, max(1.0, (now + step_ms + 10_000 - _now_ms()) / 1000.0)))
    out = {"mode": a.mode, "steps": n, "last": res, "state": os.path.join(sdir, "state.json"), "events": events}
    write_job_result(out)
    return out
