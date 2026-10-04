"""Bot giao dịch theo sổ đã xuất bản (E9-S1/S2/S5) — job API `live_bot`. Mọi chiến lược của sổ: theo xu hướng lẫn DCA.

Chế độ:
  paper    dữ liệu thị trường THẬT (REST công khai, mặc định mainnet); khớp lệnh bằng PaperBook = đúng PositionTracker + vòng danh mục của
           engine (test: cùng nến + tín hiệu -> cùng lệnh với PortfolioEngine, gồm DCA, trailing, kill switch). Bot nghỉ bao lâu thì nến bỏ lỡ
           được chạy bù theo đúng thứ tự.
  testnet  Binance Futures testnet, lệnh thật (khoá: secrets.py). Vào lệnh MARKET đầu nến kế tín hiệu; tầng DCA = LIMIT GTX (post-only, khớp
           maker như engine) đặt sẵn cả thang theo đúng bước/hệ số; SL = STOP_MARKET closePosition và TP = LIMIT reduce-only tính từ GIÁ TRUNG
           BÌNH, đặt lại mỗi khi một tầng DCA khớp; trailing / timeout / tín hiệu thoát = MARKET reduce-only ở nến kế. Đối soát vị thế mỗi bước.
           Chạy kèm một PaperBook "bóng" trên cùng nến để đối chiếu thật / mô phỏng (events + state).
Khối lượng = PositionTracker._risk_margin / order_size_pct (cùng mã engine); giới hạn danh mục và kill switch như PortfolioEngine.
"""
import json
import os
import pickle
import signal
import time
import warnings
from typing import Any, Dict, List, Optional

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"mode": "paper", "once": False, "max_steps": 0, "data_url": "", "capital": 10000.0, "state_dir": ""}
KLINE_LIMIT = 1500
EPS = 1e-12


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
        self.d: Dict[str, Any] = {"positions": {}, "last_close": {}, "peak_equity": capital, "halted": False, "last_bar": None,
                                  "trades": [], "external": []}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.d.update(json.load(fh))

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.d, fh, ensure_ascii=False, indent=1, default=float)
        os.replace(tmp, self.path)


def _bar_sig(v: Dict[str, Any], i: int) -> List[Dict[str, Any]]:
    return [{"match": bool(e["match"][i]), "stop": bool(e["stop"][i]), "vol": (float(e["vol"][i]) if e["vol"] is not None else None)}
            for e in v["entries"]]


class Bot:
    def __init__(self, book: Dict[str, Any], mode: str, client, state: State, log, filters: Optional[Dict[str, Any]] = None,
                 paper=None, capital: float = 10000.0):
        from backend.live.paper import PaperBook
        self.book, self.mode, self.client, self.state, self.log = book, mode, client, state, log
        self.tf = book.get("timeframe", "1m")
        self.strategies = book_strategies(book)
        self.symbols = [s.split("@")[0] for s in book["universe"]]
        self.limits = book["risk"]
        self.filters = filters or {}
        self.paper = paper or PaperBook(self.strategies, self.symbols, self.tf, capital, self.limits)

    # ── dữ liệu ──
    def frames(self, sym: str, now: int) -> Dict[str, Any]:
        from backend.live import signals as ls
        return {fr: ls.klines_frame(self.client.klines(f"{sym}USDT", fr, KLINE_LIMIT), now)
                for fr in ls.required_frames(f"{sym}@perp", self.strategies, self.tf)}

    def funding(self, sym: str, since: int) -> List:
        try:
            rows = self.client.funding(f"{sym}USDT", since)
        except Exception:                      # funding không lấy được: bỏ qua bước này (không chặn giao dịch)
            return []
        return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]

    def event(self, kind: str, **kw) -> None:
        self.log({"t": _now_ms(), "kind": kind, **kw})

    # ── paper / bóng: chạy bù mọi nến chưa xử lý ──
    def advance_paper(self, sig: Dict[str, Dict[str, Any]], funding: Optional[Dict[str, List]] = None) -> List[Dict[str, Any]]:
        pb = self.paper
        pos = {sym: {int(t): i for i, t in enumerate(v["t"])} for sym, v in sig.items()}
        times = sorted({t for p in pos.values() for t in p if pb.last_t is None or t > pb.last_t})
        if pb.last_t is None:
            times = times[-1:]                 # khởi động: chỉ nến đóng mới nhất (không giao dịch lùi lịch sử)
        closed = []
        for t in times:
            prev = pb.last_t if pb.last_t is not None else t - 1
            bars, s_at, fund = {}, {}, {}
            for sym, v in sig.items():
                i = pos[sym].get(t)
                if i is None:
                    continue
                bars[sym] = (float(v["open"][i]), float(v["high"][i]), float(v["low"][i]), float(v["close"][i]))
                s_at[sym] = _bar_sig(v, i)
                fund[sym] = [(ft, r) for ft, r in (funding or {}).get(sym, []) if prev < ft <= t]
            closed += pb.step_bar(t, bars, s_at, fund)
        return closed

    # ── testnet ──
    def _protect(self, sym: str, p: Dict[str, Any]) -> None:
        """(Đặt lại) SL / TP từ giá trung bình hiện tại + các tầng DCA chưa khớp."""
        s, f = f"{sym}USDT", self.filters.get(sym)
        rnd = f.price if f is not None else (lambda x: x)
        rq = f.qty if f is not None else (lambda x: x)
        sign = 1 if p["side"] == "LONG" else -1
        exit_side, entry_side = ("SELL", "BUY") if sign > 0 else ("BUY", "SELL")
        self.client.cancel_all(s)
        if p["sl_pct"]:
            self.client.order(symbol=s, side=exit_side, type="STOP_MARKET", stopPrice=rnd(p["avg"] * (1 - sign * p["sl_pct"] / 100.0)),
                              closePosition="true", workingType="MARK_PRICE")
        if p["tp_pct"]:
            self.client.order(symbol=s, side=exit_side, type="LIMIT", timeInForce="GTC", quantity=rq(p["qty"]), reduceOnly="true",
                              price=rnd(p["avg"] * (1 + sign * p["tp_pct"] / 100.0)))
        for lay in p["ladder"][p["filled_layers"]:]:
            try:
                self.client.order(symbol=s, side=entry_side, type="LIMIT", timeInForce="GTX", quantity=lay["qty"], price=lay["price"])
            except Exception as e:             # GTX bị từ chối (sẽ khớp ngay = taker): bỏ tầng, KHÔNG đổi sang market (E9-S2 AC2)
                self.event("skip", symbol=sym, reason=f"tầng DCA {lay['price']} bị từ chối: {e}")

    def _open_testnet(self, sym: str, e: Dict[str, Any], i: int, price: float, equity: float, room: float, now: int) -> None:
        from backend.core.execute.ledger import CapitalLedger
        tr = e["tracker"]
        vol = float(e["vol"][i]) if e["vol"] is not None else float("nan")
        if tr.exit_unit == "atr" and not vol > 0:
            return self.event("skip", symbol=sym, strategy=e["strategy"], reason="chưa có ATR")
        tr.ledger = CapitalLedger(equity)
        tr._apply_exit_unit(vol if tr.exit_unit == "atr" else 1.0)
        tr.max_leverage = tr.leverage
        tr.pos_leverage = tr.leverage
        margin = tr._risk_margin() if tr.sizing == "risk" else equity * tr.order_size_pct / 100.0
        lev = float(tr.pos_leverage)
        notional = min(margin * lev, room)
        f = self.filters.get(sym)
        qty = f.qty(notional / price) if f is not None else notional / price
        why = f.check(qty, price) if f is not None else (None if qty > 0 else "khối lượng 0")
        if why:
            return self.event("skip", symbol=sym, strategy=e["strategy"], reason=why)
        sign = 1 if e["side"] == "LONG" else -1
        s = f"{sym}USDT"
        self.client.set_margin_isolated(s)
        self.client.set_leverage(s, int(lev))
        r = self.client.order(symbol=s, side="BUY" if sign > 0 else "SELL", type="MARKET", quantity=qty, newOrderRespType="RESULT")
        fill = float(r.get("avgPrice") or price)
        ladder, level, m = [], fill, notional / lev
        for step, mult in zip(tr.dca_steps, tr.dca_mults):
            level = level * (1 - sign * step / 100.0)
            m *= mult
            q = f.qty(m * lev / level) if f is not None else m * lev / level
            ladder.append({"price": f.price(level) if f is not None else level, "qty": q})
        p = {"strategy": e["strategy"], "side": e["side"], "qty": qty, "avg": fill, "entry_price": fill, "entry_time": now, "leverage": int(lev),
             "sl_pct": tr.sl_pct, "tp_pct": tr.tp_pct, "trail_pct": tr.trail_pct, "trail_act_pct": tr.trail_activation_pct, "peak": fill,
             "timeout_ms": tr.timeout_ms, "ladder": ladder, "filled_layers": 0}
        self.state.d["positions"][sym] = p
        self._protect(sym, p)
        self.event("open", symbol=sym, strategy=e["strategy"], side=e["side"], qty=qty, price=fill, leverage=int(lev),
                   sl_pct=round(tr.sl_pct, 4), tp_pct=round(tr.tp_pct, 4), dca_layers=len(ladder))

    def _close_testnet(self, sym: str, reason: str, now: int) -> None:
        p = self.state.d["positions"].pop(sym)
        s = f"{sym}USDT"
        self.client.cancel_all(s)
        amt = next((float(x["positionAmt"]) for x in self.client.positions() if x["symbol"] == s), 0.0)
        if abs(amt) > EPS:
            self.client.order(symbol=s, side="SELL" if amt > 0 else "BUY", type="MARKET", quantity=abs(amt), reduceOnly="true")
        self.state.d["last_close"][f"{p['strategy']}|{sym}"] = now
        self.state.d["trades"].append({**{k: p[k] for k in ("strategy", "side", "qty", "avg", "entry_time")}, "symbol": sym, "close_time": now,
                                       "reason": reason, "layers": 1 + p["filled_layers"]})
        self.event("close", symbol=sym, strategy=p["strategy"], reason=reason)

    def reconcile(self, now: int) -> None:
        """Vị thế sàn là sự thật: sàn đã đóng (SL/TP) -> ghi nhận; khối lượng tăng (tầng DCA khớp) -> cập nhật giá TB, đặt lại SL/TP;
        vị thế không do bot mở -> không mở thêm trên tài sản đó (E9-S1 AC5)."""
        d = self.state.d
        live = {x["symbol"][:-4]: (float(x["positionAmt"]), float(x.get("entryPrice") or 0)) for x in self.client.positions()
                if abs(float(x["positionAmt"])) > EPS}
        d["external"] = sorted(s for s in live if s not in d["positions"])
        for sym in list(d["positions"]):
            p = d["positions"][sym]
            if sym not in live:
                d["positions"].pop(sym)
                self.client.cancel_all(f"{sym}USDT")
                d["last_close"][f"{p['strategy']}|{sym}"] = now
                d["trades"].append({**{k: p[k] for k in ("strategy", "side", "qty", "avg", "entry_time")}, "symbol": sym, "close_time": now,
                                    "reason": "Sàn đã đóng (SL/TP)", "layers": 1 + p["filled_layers"]})
                self.event("close", symbol=sym, strategy=p["strategy"], reason="Sàn đã đóng (SL/TP)")
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

    def step_testnet(self, now: int, sig: Dict[str, Dict[str, Any]]) -> None:
        d = self.state.d
        self.reconcile(now)
        last = {s: len(v["t"]) - 1 for s, v in sig.items()}
        marks = {s: float(v["close"][last[s]]) for s, v in sig.items()}
        for sym in list(d["positions"]):
            p, v, i = d["positions"][sym], sig[sym], last[sym]
            sign = 1 if p["side"] == "LONG" else -1
            e = next(x for x in v["entries"] if x["strategy"] == p["strategy"])
            hi, lo = float(v["high"][i]), float(v["low"][i])
            if p["trail_pct"]:
                gain = sign * (p["peak"] - p["avg"]) / p["avg"] * 100.0
                level = p["peak"] * (1 - sign * p["trail_pct"] / 100.0)
                if gain >= p["trail_act_pct"] and (lo <= level if sign > 0 else hi >= level):
                    self._close_testnet(sym, "Trailing stop", now)
                    continue
            p["peak"] = max(p["peak"], hi) if sign > 0 else min(p["peak"], lo)
            if bool(e["stop"][i]):
                self._close_testnet(sym, "Tín hiệu thoát", now)
            elif p["timeout_ms"] and now - p["entry_time"] >= p["timeout_ms"]:
                self._close_testnet(sym, "Hết thời gian giữ lệnh", now)
        eq = float(self.client.account()["totalMarginBalance"])
        d["peak_equity"] = max(d["peak_equity"], eq)
        kill = float(self.limits.get("kill_switch_dd_pct") or 0)
        if kill and not d["halted"] and eq <= d["peak_equity"] * (1 - kill / 100.0):
            d["halted"] = True
            for sym in list(d["positions"]):
                self._close_testnet(sym, "Kill switch", now)
            self.event("crit", reason=f"kill switch: vốn {eq:.2f} <= {100 - kill:.0f}% đỉnh {d['peak_equity']:.2f}")
        if not d["halted"]:
            for sym in self.symbols:
                if sym in d["positions"] or sym in d["external"]:
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
                        self._open_testnet(sym, e, i, marks[sym], eq, room, now)
                    break
        d["equity"] = eq

    # ── một bước ──
    def step(self, now: int, data: Optional[Dict[str, Dict[str, Any]]] = None, funding: Optional[Dict[str, List]] = None) -> Dict[str, Any]:
        """now = open của nến chạy mới; data (test) = {sym: kết quả signals.evaluate}."""
        from backend.live import signals as ls
        d = self.state.d
        sig = data or {s: ls.evaluate(f"{s}@perp", self.strategies, self.frames(s, now), self.tf) for s in self.symbols}
        if funding is None and data is None:
            since = (self.paper.last_t or now) - 2 * 86_400_000
            funding = {s: self.funding(s, since) for s in self.symbols}
        closed = self.advance_paper(sig, funding)
        if self.mode == "testnet":
            self.step_testnet(now, sig)
        else:
            mtm, worst = self.paper.mtm()
            d.update(equity=round(mtm, 4), equity_worst=round(worst, 4), halted=self.paper.halted_at is not None,
                     positions={p["symbol"]: p for p in self.paper.positions()}, trades=self.paper.trades[-200:])
        for tr in closed:
            self.event("paper_close" if self.mode == "testnet" else "close", **tr)
        d["last_bar"] = now
        d["paper"] = {"equity": round(self.paper.mtm()[0], 4), "positions": len(self.paper.positions()), "trades": len(self.paper.trades),
                      "halted_at": self.paper.halted_at}
        self.state.save()
        return {"equity": d.get("equity"), "positions": len(d["positions"]), "halted": d["halted"]}


def check_testnet_account(client) -> None:
    if client._req("GET", "/fapi/v1/positionSide/dual", signed=True).get("dualSidePosition"):
        raise SystemExit("tài khoản đang ở chế độ hedge — bot cần one-way (khớp max_per_symbol = 1)")


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
    events, pkl = os.path.join(sdir, "events.jsonl"), os.path.join(sdir, "paper.pkl")

    def log(ev):
        line = redact(json.dumps(ev, ensure_ascii=False, default=str), keys)
        with open(events, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)
    info = client.exchange_info()
    filters = {s.split("@")[0]: Filters.from_info(info, s.split("@")[0] + "USDT") for s in book["universe"]}
    paper = None
    if os.path.isfile(pkl):
        with open(pkl, "rb") as fh:
            paper = pickle.load(fh)
    bot = Bot(book, a.mode, client, State(os.path.join(sdir, "state.json"), float(a.capital)), log, filters, paper, float(a.capital))
    if a.mode == "testnet":
        check_testnet_account(client)
        bot.reconcile(_now_ms())
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
                with open(pkl + ".tmp", "wb") as fh:
                    pickle.dump(bot.paper, fh)
                os.replace(pkl + ".tmp", pkl)
                log({"t": _now_ms(), "kind": "step", "bar": now, **res})
            except Exception as e:   # lỗi mạng / sàn: ghi lại, thử ở vòng sau (không mở trùng: đối soát đầu mỗi bước)
                log({"t": _now_ms(), "kind": "error", "error": redact(f"{type(e).__name__}: {e}", keys)})
            n += 1
            if a.once or (a.max_steps and n >= a.max_steps):
                break
        time.sleep(min(30.0, max(1.0, (now + step_ms + 10_000 - _now_ms()) / 1000.0)))
    out = {"mode": a.mode, "steps": n, "last": res, "state": os.path.join(sdir, "state.json"), "events": events}
    write_job_result(out)
    return out
