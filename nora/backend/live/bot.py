"""Bot giao dịch theo sổ đã xuất bản (E9-S1/S2/S5) — job API `live_bot`. Sàn triển khai: OKX (Binance chỉ để tham khảo / đối chiếu).
Mọi chiến lược của sổ: theo xu hướng lẫn DCA.

Chế độ:
  paper  dữ liệu thị trường THẬT của sàn (REST công khai); khớp lệnh bằng PaperBook = đúng PositionTracker + vòng danh mục của engine
         (test: cùng nến + tín hiệu -> cùng lệnh với PortfolioEngine, gồm DCA, trailing, kill switch). Nến bỏ lỡ được chạy bù theo thứ tự.
  demo   OKX Demo Trading (khoá demo, vốn ảo) — "testnet / live mô phỏng".
  live   OKX tài khoản thật: CÙNG mã với demo, chỉ khác khoá (NORA_OKX_DEMO=0) và cần confirm_live=true.
demo/live: vào lệnh MARKET đầu nến kế tín hiệu; tầng DCA = lệnh post-only (khớp maker như engine) đặt sẵn cả thang theo đúng bước/hệ số;
SL = lệnh điều kiện reduce-only và TP = limit reduce-only tính từ GIÁ TRUNG BÌNH, đặt lại mỗi khi một tầng DCA khớp; trailing / timeout /
tín hiệu thoát = đóng market ở nến kế. Đối soát vị thế với sàn mỗi bước; chạy kèm PaperBook "bóng" trên cùng nến để đối chiếu thật / mô phỏng.
Khối lượng = PositionTracker._risk_margin / order_size_pct (cùng mã engine); giới hạn danh mục và kill switch như PortfolioEngine.

engine (tham số job): "legacy" (mặc định) = mã ở file này, không đổi. "unified" (chỉ demo/live, OKX) = live/unified.py: Runner + PositionManager + OkxVenue + sổ vốn ảo
(ADR-P6 P6.8b, D1–D5) — trạng thái ở thư mục riêng `<sàn>_<chế độ>_unified`. Paper + unified = chạy đường Bot thường (PaperBook đã là đường event).
"""
import json
import os
import pickle
import signal
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"mode": "paper", "venue": "okx", "once": False, "max_steps": 0, "capital": 10000.0, "state_dir": "", "confirm_live": False,
            "book": "main", "engine": "legacy", "equity_drift_halt_pct": 5.0}
ENGINES = ("legacy", "unified")   # legacy = Bot tự đặt lệnh (code cũ); unified = Runner + PositionManager + OkxVenue (live/unified.py, ADR-P6 P6.8b)
BOOKS = ("main", "explore")     # main = data/alphas/book.json (READY_FOR_TESTNET); explore = data/alphas/explore/book.json (EXPLORE_DEMO)
EXEC_MODES = ("demo", "live")   # đặt lệnh thật trên sàn: demo = OKX Demo Trading (vốn ảo), live = tài khoản thật
KLINE_LIMIT = 1500
WATCH_S = 10.0     # giây giữa hai lần đối soát nhanh của bot sàn (tầng DCA khớp -> SL/TP mới; sàn đóng lệnh -> ghi nhận)
EPS = 1e-12


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_book(alphas: Optional[str] = None, kind: str = "main", mode: str = "paper") -> Dict[str, Any]:
    """main: sổ đã kiểm định (READY_FOR_TESTNET). explore: sổ thử nghiệm (EXPLORE_DEMO) — chỉ paper/demo, không bao giờ live."""
    from backend.core.params.presets import alphas_dir
    from backend.optimize.registry import EXPLORE_STATUS
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
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import materialize, BY_ID
    by = BY_ID
    tf = book.get("timeframe", "1m")
    return [materialize(by[s["id"]], lift_frames(by[s["id"]], s["params"], tf), risk_per_trade_pct=book["risk_per_trade_pct"],
                        stop_fill="level") for s in book["strategies"]]


def state_key(venue: str, mode: str, book: str = "main", engine: str = "legacy") -> str:
    """Thư mục trạng thái của một bot: mỗi (sàn, chế độ, sổ) một thư mục — sổ thử nghiệm chạy song song sổ chính không giẫm trạng thái.
    engine="unified" ở demo/live có thư mục RIÊNG (hậu tố _unified): state.json của hai engine khác hình dạng, đổi engine không làm hỏng trạng thái cũ.
    Paper: unified = legacy (cùng PaperBook event) nên dùng chung thư mục."""
    return f"{venue}_{mode}" + ("_explore" if book == "explore" else "") + ("_unified" if engine == "unified" and mode in EXEC_MODES else "")


def _archive_stale_state(sdir: str, spath: str, book: Dict[str, Any]) -> None:
    """Trạng thái của sổ KHÁC (book.generated_at khác) -> cất state.json / paper.pkl / events.jsonl vào sdir/archive_<giờ>/ (không xoá)."""
    names = [n for n in ("state.json", "paper.pkl", "unified.pkl", "events.jsonl") if os.path.isfile(os.path.join(sdir, n))]
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
        with open(path, "rb") as fh:
            return pickle.load(fh)
    except Exception as e:                    # EOFError, UnpicklingError, AttributeError (class đổi tên), ImportError ...
        dst = f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"
        os.replace(path, dst)
        log({"t": _now_ms(), "kind": "warn", "msg": f"{what} hỏng ({type(e).__name__}: {e}) — đã cất sang {dst}, bắt đầu lại từ trạng thái mới"})
        return None


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


def _bar_sig(v: Dict[str, Any], i: int) -> List[Dict[str, Any]]:
    return [{"match": bool(e["match"][i]), "stop": bool(e["stop"][i]), "vol": (float(e["vol"][i]) if e["vol"] is not None else None),
             "dca": bool(e["dca"][i]) if e.get("dca") is not None else True}
            for e in v["entries"]]


class Bot:
    def __init__(self, book: Dict[str, Any], mode: str, client, state: State, log, filters: Optional[Dict[str, Any]] = None,
                 paper=None, capital: float = 10000.0):
        from backend.live.paper import PaperBook
        self.book, self.mode, self.client, self.state, self.log = book, mode, client, state, log
        self.tf = book.get("timeframe", "1m")
        self.sim_tf = book.get("sim_timeframe") or ("15m" if self.tf == "1h" else self.tf)
        self.strategies = book_strategies(book)
        self.symbols = [s.split("@")[0] for s in book["universe"]]
        self.limits = book["risk"]
        self.filters = filters or {}
        self.blocked: Dict[str, str] = {}      # mã khoá API không được giao dịch (sàn báo thiếu quyền): bỏ qua tới lần khởi động sau
        self.paper = paper or PaperBook(self.strategies, self.symbols, self.sim_tf, capital, self.limits)

    # ── dữ liệu ──
    def frames(self, sym: str, now: int) -> Dict[str, Any]:
        from backend.live import signals as ls
        req = set(ls.required_frames(f"{sym}@perp", self.strategies, self.tf))
        if getattr(self, "sim_tf", None) and self.sim_tf != self.tf:
            req.add(self.sim_tf)
        return {fr: ls.klines_frame(self.client.klines(sym, fr, KLINE_LIMIT, now), now)
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
        from backend.core.execute.ledger import CapitalLedger
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
        from backend.live.exchange import NotPermitted
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
        """now = open của nến chạy mới; data (test) = {sym: kết quả signals.evaluate}."""
        from backend.live import signals as ls
        d = self.state.d
        sig = data or {s: ls.evaluate(f"{s}@perp", self.strategies, self.frames(s, now), self.tf) for s in self.symbols}
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


def make_adapter(venue: str, mode: str):
    """Sàn + khoá theo chế độ. paper: chỉ dữ liệu công khai. demo/live: khoá bắt buộc; live cần NORA_OKX_DEMO=0 (khoá thật)."""
    from backend.live.secrets import load_keys, load_okx
    if venue == "okx":
        from backend.live.okx import OkxAdapter
        if mode == "paper":
            return OkxAdapter(None, demo=False), None
        got = load_okx()
        if not got:
            raise SystemExit("OKX cần khoá: NORA_OKX_KEY / NORA_OKX_SECRET / NORA_OKX_PASSPHRASE (+ NORA_OKX_DEMO) trong môi trường hoặc "
                             "~/.config/nora/okx.env (quyền 600)")
        keys, demo = got
        if mode == "demo" and not demo:
            raise SystemExit("mode demo nhưng khoá là tài khoản thật (NORA_OKX_DEMO=0) — dùng khoá Demo Trading")
        if mode == "live" and demo:
            raise SystemExit("mode live cần khoá tài khoản thật (NORA_OKX_DEMO=0)")
        return OkxAdapter(keys, demo=demo), keys
    if venue == "binance":
        from backend.live.exchange import MAINNET_URL, TESTNET_URL, BinanceAdapter
        if mode == "paper":
            return BinanceAdapter(None, MAINNET_URL), None
        if mode == "live":
            raise SystemExit("Binance chỉ để tham khảo: không chạy live")
        keys = load_keys()
        if not keys:
            raise SystemExit("Binance testnet cần khoá (NORA_BINANCE_TESTNET_KEY/SECRET)")
        return BinanceAdapter(keys, TESTNET_URL), keys
    raise SystemExit(f"sàn không hỗ trợ: {venue}")


def run_job(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.live.secrets import redact
    from backend.db.data_layout import cache_dir
    if a.mode not in ("paper",) + EXEC_MODES:
        raise SystemExit("mode phải là paper | demo | live")
    if a.engine not in ENGINES:
        raise SystemExit(f"engine phải là một trong {ENGINES}")
    if a.mode == "live" and not a.confirm_live:
        raise SystemExit("mode live đặt lệnh bằng VỐN THẬT — cần confirm_live=true")
    unified = a.engine == "unified" and a.mode in EXEC_MODES      # paper + unified = PaperBook event (đã là mặc định): chạy đường Bot thường
    if unified and a.venue != "okx":
        raise SystemExit("engine=unified chỉ hỗ trợ sàn OKX (OkxVenue)")
    book = load_book(kind=a.book, mode=a.mode)
    if unified:
        from backend.live.unified import check_book_d1
        check_book_d1(book)                                       # D1: từ chối sớm, trước khi chạm sàn
    client, keys = make_adapter(a.venue, a.mode)
    sdir = a.state_dir or cache_dir(None, "live", state_key(a.venue, a.mode, a.book, a.engine))
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
    paper = load_pickle(pkl, log, "paper.pkl")
    state = State(spath)
    state.d["book"] = book.get("generated_at")
    state.d["book_kind"] = a.book
    if unified:
        from backend.live.unified import UnifiedBot
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
                with open(pkl + ".tmp", "wb") as fh:
                    pickle.dump(bot.paper, fh)
                os.replace(pkl + ".tmp", pkl)
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
