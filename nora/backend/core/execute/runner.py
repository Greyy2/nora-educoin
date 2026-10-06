"""Runner (P6.5) — chạy MỘT nến của cả danh mục qua một Venue: nguồn duy nhất của vòng danh mục cho paper / bot (docs/bmad/p6_execution_design.md §5).

Thứ tự y hệt vòng lặp gốc (test/reference_engine.py::RefPortfolioEngine.run), HAI PHA mỗi nến (ADR P6 §10, P6.12):
pha 1 (mở nến, tài sản theo thứ tự sổ) funding -> từng slot: luật bỏ qua, `risk.admit_entry` (trạng thái LÚC MỞ NẾN, gross theo `last_close` = đóng nến
trước, chỉ khi qua trần số vị thế) -> đặt trần (max_new_notional / max_new_risk / risk_scale) -> `on_bar_open` -> xả trần -> thu lệnh đóng ở open;
pha 2 (trong nến, tài sản theo thứ tự sổ) `on_bar_rest` -> thu lệnh đóng -> cập nhật last_close/low/high/open;
pha 3: MTM (mtm, worst) -> `peak_mtm` -> `risk.kill_triggered` -> đóng hết ("Kill switch danh mục").
Trước P6.12 mỗi tài sản chạy TRỌN nến rồi mới tới tài sản kế -> lệnh vào của B ở open thấy SL/TP trong nến của A (nhìn trước); nay thì không.

Runner KHÔNG biết slot khớp lệnh thế nào: mỗi slot ("tracker" trong `books`) là một "actor" có giao diện chung của `PositionManager` (đường event,
điều khiển Venue) và `PositionTracker` (đường cũ): is_open, pending_entry, qty, planned_risk, max_new_*, risk_scale, on_bar_open, on_bar_rest, apply_funding,
force_close, unrealized_pnl_usd. Nên cùng một vòng danh mục chạy được cho cả hai — test_runner_parity.py dựa vào đó để khoá bit-identical.
`venue` chỉ được giữ để chủ sở hữu (PaperBook / bot) truy cập; Runner không gọi nó (venue None = đường tracker cũ, không có sàn).
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.core.execute.risk import admit_entry, kill_triggered


class Runner:
    def __init__(self, venue, account, books: List[Dict[str, Any]], risk: Dict[str, Any], trade_start: int = 0,
                 collect: Optional[Callable[..., None]] = None, initial_capital: Optional[float] = None):
        """books = [{"symbol", "entries": [{"strategy", "side", "tracker": actor}]}] theo thứ tự sổ (tài sản, rồi chiến lược).
        collect(sym, e, pos, low, high) thay `record` nếu chủ sở hữu muốn móc thêm khi ghi lệnh đóng (TickBook)."""
        self.venue = venue
        self.account = account
        self.books = books
        self.risk = dict(risk)
        self.trade_start = int(trade_start)
        self.collect = collect
        n = len(books)
        nan = float("nan")
        self.last_close, self.last_low, self.last_high, self.last_open = [nan] * n, [nan] * n, [nan] * n, [nan] * n
        self.peak_mtm = float(account.initial if initial_capital is None else initial_capital)
        self.halted_at: Optional[int] = None
        self.last_t: Optional[int] = None
        self.trades: List[Dict[str, Any]] = []
        self.rejected_for_risk = 0

    def __getstate__(self) -> Dict[str, Any]:
        """Pickle (paper.pkl của bot): bỏ móc `collect` (hàm gắn của chủ sở hữu) — PaperBook.__setstate__ gắn lại sau khi nạp."""
        d = dict(self.__dict__)
        d["collect"] = None
        return d

    # ── danh mục ──
    def _gross(self) -> float:
        tot = 0.0
        for b, bk in enumerate(self.books):
            px = self.last_close[b]
            if px != px:
                continue
            tot += sum(e["tracker"].qty * px for e in bk["entries"] if e["tracker"].is_open)
        return tot

    def _open_risk(self) -> float:
        """Σ rủi ro tới SL (planned_risk) của mọi vị thế đang mở."""
        tot = 0.0
        for bk in self.books:
            for e in bk["entries"]:
                if e["tracker"].is_open:
                    tot += e["tracker"].planned_risk
        return tot

    def _counts(self) -> Tuple[int, List[int]]:
        per = [sum(1 for e in bk["entries"] if e["tracker"].is_open) for bk in self.books]
        return sum(per), per

    def mtm(self) -> Tuple[float, float]:
        """(vốn theo giá đóng nến, vốn theo giá xấu nhất của nến) = vốn đã chốt + lãi/lỗ chưa chốt của mọi vị thế mở."""
        mtm = worst = self.account.equity
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    mtm += tr.unrealized_pnl_usd(self.last_close[b])
                    worst += tr.unrealized_pnl_usd(self.last_low[b] if tr.is_long else self.last_high[b])
        return mtm, worst

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    out.append({"symbol": bk["symbol"], "strategy": e["strategy"], "side": e["side"], "qty": tr.qty, "avg": tr.avg,
                                "layers": tr.layer_count, "entry_time": tr.entry_time, "unrealized": tr.unrealized_pnl_usd(self.last_close[b])})
        return out

    # ── lệnh đóng ──
    def record(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        """Ghi lệnh đóng; fees/funding = chi phí cộng dồn (dương = trả), bar_low/bar_high = nến đóng (đối chiếu kịch bản SL bi quan)."""
        self.trades.append({"symbol": sym, "strategy": e["strategy"], "side": pos.pos_type.name, "enter_time": int(pos.enter_time),
                            "enter_price": float(pos.enter_price), "avg_price": float(pos.avg_price or pos.enter_price),
                            "close_time": int(pos.close_time), "close_price": float(pos.close_price), "qty": float(pos.qty),
                            "layers": int(pos.layers or 1), "pnl": round(float(pos.real_pnl), 6), "reason": pos.close_reason,
                            "fees": round(float(pos.fees_usd or 0), 6), "funding": round(float(pos.funding_usd or 0), 6),
                            "bar_low": float(low), "bar_high": float(high)})

    def _collect(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        (self.collect or self.record)(sym, e, pos, low, high)

    # ── một nến ──
    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến chạy ở thời điểm t (open_time), HAI PHA (ADR P6 §10). bars[sym] = (o, h, l, c) (tài sản không có nến: bỏ qua);
        sig[sym] = [{match, stop, vol}] theo thứ tự chiến lược; funding[sym] = [(funding_time, rate)] đến hạn <= t. -> các lệnh đóng ở nến này.

        Pha 1 — MỞ NẾN, mọi tài sản theo thứ tự sổ: funding -> từng slot: luật bỏ qua, `admit_entry` (trạng thái LÚC MỞ NẾN: vị thế mở
        sau các lệnh thoát/vào ở open của tài sản đứng trước; chưa tài sản nào chạy trong nến; gross định giá theo `last_close` = đóng nến
        TRƯỚC; vốn = sổ vốn sau funding + lệnh thoát ở open) -> đặt trần -> `on_bar_open` (thoát chờ / hết hạn, vào lệnh ở open) -> xả trần.
        Pha 2 — TRONG NẾN, mọi tài sản theo thứ tự sổ: `on_bar_rest` (SL / TP / DCA / trailing / thanh lý theo đường giá + sổ sách cuối nến),
        rồi cập nhật last_close/low/high/open. Pha 3: MTM -> peak_mtm -> kill switch.
        Nhờ vậy lệnh vào của tài sản B ở open t KHÔNG thấy lệnh thoát trong nến (SL/TP) hay giá đóng nến của tài sản A đứng trước (không nhìn trước)."""
        n0 = len(self.trades)
        cap = float(self.risk["max_gross_exposure"])
        kill_pct = float(self.risk.get("kill_switch_dd_pct") or 0)
        can_trade = t >= self.trade_start and self.halted_at is None
        touched = False
        todo: List[Tuple[int, str, Tuple[float, float, float, float], List[Tuple[Dict[str, Any], Dict[str, Any], bool, Any]]]] = []
        # ── Pha 1: mở nến ──
        for b, bk in enumerate(self.books):
            sym = bk["symbol"]
            if sym not in bars:
                continue
            o, h, l, c = bars[sym]
            for ft, rate in (funding or {}).get(sym, []):
                for e in bk["entries"]:
                    e["tracker"].apply_funding(float(rate), float(o))
            acts: List[Tuple[Dict[str, Any], Dict[str, Any], bool, Any]] = []
            for e, s in zip(bk["entries"], sig[sym]):
                tr = e["tracker"]
                m = bool(s["match"])
                if not tr.is_open and not tr.pending_entry and not m:
                    continue
                can_open = False
                if can_trade and tr.pending_entry and not tr.is_open:
                    n_open, per = self._counts()
                    gross = open_risk = 0.0
                    if n_open < int(self.risk["max_positions"]) and per[b] < int(self.risk["max_per_symbol"]):
                        gross = self._gross()
                        open_risk = self._open_risk()
                    adm = admit_entry(n_open, per[b], self.account.equity, self.account.peak, gross, open_risk,
                                      self.risk["max_positions"], self.risk["max_per_symbol"], cap,
                                      self.risk.get("max_open_risk_pct") or 0.0, self.risk.get("dd_throttle_pct") or 0.0,
                                      self.risk.get("dd_throttle_floor", 0.25))
                    can_open = adm.can_open
                    tr.max_new_notional, tr.max_new_risk, tr.risk_scale = adm.max_new_notional, adm.max_new_risk, adm.risk_scale
                    if not can_open:
                        self.rejected_for_risk += 1
                closed_open = tr.on_bar_open(t, o, h, l, c, can_open=can_open)
                tr.max_new_notional = float("inf")
                tr.max_new_risk = float("inf")
                tr.risk_scale = 1.0
                if closed_open is not None:
                    self._collect(sym, e, closed_open, l, h)
                acts.append((e, s, m, closed_open))
            todo.append((b, sym, (o, h, l, c), acts))
        # ── Pha 2: trong nến ──
        for b, sym, (o, h, l, c), acts in todo:
            for e, s, m, closed_open in acts:
                tr = e["tracker"]
                vol = s.get("vol")
                pos = tr.on_bar_rest(t, o, h, l, c, entry_signal=m and can_trade, stop_signal=bool(s["stop"]), closed=closed_open,
                                     vol=float(vol) if vol is not None else float("nan"), dca_gate=bool(s.get("dca", True)))
                if pos is not None and pos is not closed_open:
                    self._collect(sym, e, pos, l, h)
            self.last_close[b], self.last_low[b], self.last_high[b], self.last_open[b] = float(c), float(l), float(h), float(o)
            touched = True
        self.last_t = t
        if touched:
            mtm, worst = self.mtm()
            self.peak_mtm = max(self.peak_mtm, mtm)
            if self.halted_at is None and kill_triggered(worst, self.peak_mtm, kill_pct):
                self._kill(t)
        return self.trades[n0:]

    def _kill(self, t: int) -> None:
        """Kill switch: dừng giao dịch mới và đóng hết vị thế ở giá đóng nến gần nhất."""
        self.halted_at = t
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                tr.pending_entry = False
                pos = tr.force_close(t, self.last_close[b], "Kill switch danh mục")
                if pos is not None:
                    self._collect(bk["symbol"], e, pos, self.last_low[b], self.last_high[b])

    # ── bot sàn (P6.8b): sự kiện venue đến giữa hai nến ──
    def sync_events(self) -> List[Dict[str, Any]]:
        """Áp các sự kiện venue đã có (DCA khớp, sàn đóng vị thế...) của mọi slot đang mở -> lệnh đóng mới. Chỉ actor có `sync_events` (manager)."""
        n0 = len(self.trades)
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                sync = getattr(e["tracker"], "sync_events", None)
                if sync is None or not e["tracker"].is_open:
                    continue
                pos = sync()
                if pos is not None:
                    self._collect(bk["symbol"], e, pos, self.last_low[b], self.last_high[b])
        return self.trades[n0:]

    def sample(self, t: int, marks: Dict[str, float]) -> Tuple[float, bool]:
        """Mẫu giá giữa hai nến (ADR D3): vốn MTM tại giá mẫu `marks[sym]` (thiếu -> giá đóng nến gần nhất) so với `peak_mtm` — cùng `risk.kill_triggered`
        như cuối nến, chỉ khác điểm giá. KHÔNG nâng peak_mtm (peak chỉ theo MTM đóng nến như sim). -> (vốn MTM theo mẫu, kill có kích hoạt)."""
        m = self.account.equity
        for b, bk in enumerate(self.books):
            px = marks.get(bk["symbol"])
            if px is not None and px == px:
                self.last_close[b] = float(px)
            px = self.last_close[b]
            if px != px:
                continue
            for e in bk["entries"]:
                if e["tracker"].is_open:
                    m += e["tracker"].unrealized_pnl_usd(px)
        if self.halted_at is None and kill_triggered(m, self.peak_mtm, float(self.risk.get("kill_switch_dd_pct") or 0)):
            self._kill(t)
            return m, True
        return m, False
