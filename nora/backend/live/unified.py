"""Bot sàn trên kiến trúc thực thi THỐNG NHẤT (P6.8b) — `engine="unified"` của job `live_bot` (demo / live). Mặc định vẫn là `legacy` (bot.py).

ADR-P6 (docs/bmad/adr-p6-unified-execution.md) §2.3 quyết định 3 và §2.4 D1–D6:
  một OkxVenue (slot = một symbol) + một Account ẢO (sổ vốn đã chốt + funding, khởi tạo bằng `capital`) + một PositionManager mỗi (symbol, chiến lược),
  điều khiển bởi một Runner. Sizing, đặt SL/TP/DCA/TRAIL, thoát, hết giờ, cooldown, `risk.admit_entry`, kill switch là CÙNG mã với sim.

Hai lần chạy Runner mỗi mốc nến `now` (sàn không khớp "ở open của nến" mà khớp ngay bây giờ):
  A  `step_bar(t, nến ĐÃ ĐÓNG t, tín hiệu t)`  — cập nhật đỉnh / MAE, cờ vào / thoát chờ, kill switch theo H/L nến. Nhiều nến bị bỏ lỡ (bot nghỉ) được gộp thành MỘT
     nến (open đầu, H/L toàn đoạn, close cuối; tín hiệu của nến cuối) — khác sim ở chỗ tín hiệu các nến giữa bị bỏ (sàn không chạy bù lệnh quá khứ).
  B  `step_bar(now, nến phẳng ở giá last hiện tại, không tín hiệu)` — begin của nến mới: thực thi lệnh vào / thoát chờ NGAY (market) rồi đặt SL/TP/DCA/TRAIL từ giá TB.
`watch()` (mỗi WATCH_S giây): poll venue -> sự kiện (DCA khớp -> manager đặt lại SL/TP/... từ avg mới NGAY; sàn đóng vị thế -> ghi nhận) + lấy mẫu giá last để kiểm
kill switch (D3). Lệnh bảo vệ nằm sẵn trên sàn (D2): manager chạy `sticky_orders` nên không huỷ/đặt lại mỗi nến; trailing là lệnh gốc của sàn.

Các quyết định:
  D1  từ chối khởi động nếu `max_per_symbol` != 1 (hoặc symbol trùng trong universe): OKX net mode chỉ có một vị thế và một giá TB mỗi symbol. Nhiều chiến lược
      trên cùng symbol dùng CHUNG một slot venue và thay nhau (admit_entry chặn khi symbol đang có vị thế) — chỉ manager đang mở nhận sự kiện của slot.
  D3  kill switch trên sổ ảo: MTM xấu nhất theo H/L cuối nến (Runner) + mẫu last mỗi WATCH_S giây (`Runner.sample`; không nâng đỉnh MTM). Vốn sàn
      (`client.equity()`) CHỈ để cảnh báo lệch: |sàn − ảo| / ảo > `equity_drift_halt_pct` -> sự kiện "crit" + dừng vào lệnh mới (KHÔNG tự đóng vị thế); 0 = tắt.
      Vốn ảo khởi tạo bằng `capital` nên `capital` phải xấp xỉ vốn sàn (run_job từ chối khởi động nếu đã lệch quá ngưỡng).
  D4/D5 bóng PaperBook (SimVenue) chạy cùng nến; cả hai phía ghi Fill vào events.jsonl: {evt:"fill", src:"exec"|"sim", symbol, side, ...Fill}; Fill SL của sim kèm
      `level` (giá SL, đã tính gap) và `extreme` (cực trị nến) cho `compare_events` (độ trễ, bps, dải SL, slippage hiệu chỉnh). Fill sàn: `t` = giờ thật (đo độ trễ D5),
      `t_bar` = giờ nến mà manager dùng (đồng hồ venue = mốc nến để hết giờ / cooldown trùng nhịp sim).

Trạng thái: state.json (thư mục RIÊNG cho unified, xem bot.state_key) + paper.pkl (bóng) + unified.pkl (Runner + OkxVenue + Account ảo; client / khoá API KHÔNG được pickle).
Giới hạn đã biết: giá DCA khớp = mức đặt (maker); phí vào lệnh = 0 ở Fill (sàn không trả khi đặt) — phí cả vòng nằm ở Fill đóng (positions-history).
"""
import dataclasses
import os
import pickle
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from backend.core.execute.account import Account
from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.manager import PositionManager
from backend.core.execute.runner import Runner
from backend.live import bot as lb
from backend.live import signals as ls
from backend.live.okx_venue import OkxVenue

STEP_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
WARN_EVERY_MS = 300_000     # chống lặp cảnh báo lỗi mạng của watch()
CLOSE_KINDS = ("sl", "tp", "trail", "exit", "timeout", "kill", "liq", "end")


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


class UnifiedBot(lb.Bot):
    def __init__(self, book: Dict[str, Any], mode: str, client, state: lb.State, log, filters: Optional[Dict[str, Any]] = None, paper=None,
                 capital: float = 10000.0, exec_blob: Optional[Dict[str, Any]] = None, equity_drift_halt_pct: float = 5.0,
                 exec_path: str = ""):
        from backend.live.paper import PaperBook
        check_book_d1(book)
        if mode not in lb.EXEC_MODES:
            raise SystemExit("UnifiedBot chỉ cho demo | live (paper: dùng Bot — PaperBook đã là đường event)")
        if paper is None:
            tf = book.get("timeframe", "1m")
            paper = PaperBook(lb.book_strategies(book), [s.split("@")[0] for s in book["universe"]], tf, float(capital), book["risk"],
                              record_events=True)
        super().__init__(book, mode, client, state, log, filters, paper, capital)
        self.drift_halt_pct = float(equity_drift_halt_pct)
        self.exec_path = exec_path
        self.clock_t = 0
        self.wall_ms = lb._now_ms                                # giờ thật (ms); test ghi đè để kiểm độ trễ D5
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
                _, pairs = ls._engine(sym, self.strategies, self.tf, 0, ls.DAY)
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
        now = lb._now_ms()
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
        live = {s for s, v in self.client.positions().items() if abs(v[0]) > lb.EPS}
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
        live = {s for s, v in self.client.positions().items() if abs(v[0]) > lb.EPS}
        last_done = d.get("exec_last_bar")
        hlc, bars, s_at, fund, sig_last = {}, {}, {}, {}, {}
        t_a = max(int(v["t"][-1]) for v in sig.values())
        for sym, v in sig.items():
            ts, n = v["t"], len(v["t"])
            sig_last[sym] = lb._bar_sig(v, n - 1)
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
        """now = open của nến chạy mới; data (test) = {sym: kết quả signals.evaluate}."""
        d = self.state.d
        sig = data or {s: ls.evaluate(f"{s}@perp", self.strategies, self.frames(s, now), self.tf) for s in self.symbols}
        if funding is None and data is None:
            since = (self.paper.last_t or now) - 2 * 86_400_000
            funding = {s: self.funding(s, since) for s in self.symbols}
        self.clock_t = now
        closed_sim = self.advance_paper(sig, funding)          # bóng sim (xả sự kiện từng nến qua _after_sim_bar)
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
