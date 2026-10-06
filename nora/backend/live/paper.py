"""Sổ PAPER: khớp lệnh mô phỏng bằng đúng PositionTracker của engine (vào lệnh, DCA, SL/TP, trailing, timeout, thanh lý, funding) và đúng vòng
danh mục của PortfolioEngine (giới hạn vị thế / tài sản / tổng danh nghĩa, kill switch trên vốn xấu nhất) — từng nến chạy một, nên chạy được
theo thời gian thực (bot paper) và tái hiện được lịch sử (test: cùng nến + tín hiệu -> cùng lệnh với PortfolioEngine/kernel).

Một nến (t, o, h, l, c) của mỗi tài sản + tín hiệu tại nến đó (match / stop / vol mỗi chiến lược) + funding đến hạn -> step_bar.
Thứ tự y như vòng lặp gốc (test/reference_engine.py::RefPortfolioEngine.run): tài sản theo vũ trụ sổ, chiến lược theo thứ tự sổ.
"""
from typing import Any, Dict, List, Optional, Tuple

from backend.core.execute.ledger import CapitalLedger


class PaperBook:
    def __init__(self, strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str, capital: float, risk: Dict[str, Any],
                 trade_start: int = 0):
        from backend.live import signals as ls
        self.symbols = list(symbols)
        self.ledger = CapitalLedger(float(capital))
        self.risk = dict(risk)
        self.trade_start = int(trade_start)
        self.books: List[Dict[str, Any]] = []
        for sym in self.symbols:
            eng, pairs = ls._engine(sym, strategies, base_frame, 0, ls.DAY)
            entries = []
            for st, tr in pairs:
                tr.ledger = self.ledger                    # một sổ vốn chung (như PortfolioEngine)
                tr.capital = self.ledger.initial
                entries.append({"strategy": st["id"], "side": st["side"], "tracker": tr})
            self.books.append({"symbol": sym, "entries": entries})
        n = len(self.books)
        self.last_close, self.last_low, self.last_high, self.last_open = [float("nan")] * n, [float("nan")] * n, [float("nan")] * n, [float("nan")] * n
        self.peak_mtm = float(capital)
        self.halted_at: Optional[int] = None
        self.last_t: Optional[int] = None
        self.trades: List[Dict[str, Any]] = []
        self.rejected_for_risk = 0

    # ── danh mục ──
    def _gross(self) -> float:
        tot = 0.0
        for b, bk in enumerate(self.books):
            px = self.last_close[b]
            if px != px:
                continue
            tot += sum(e["tracker"].qty * px for e in bk["entries"] if e["tracker"].is_open)
        return tot

    def _counts(self) -> Tuple[int, List[int]]:
        per = [sum(1 for e in bk["entries"] if e["tracker"].is_open) for bk in self.books]
        return sum(per), per

    def mtm(self) -> Tuple[float, float]:
        mtm = worst = self.ledger.equity
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    mtm += tr.unrealized_pnl_usd(self.last_close[b])
                    worst += tr.unrealized_pnl_usd(self.last_low[b] if tr.is_long else self.last_high[b])
        return mtm, worst

    def _collect(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        """Ghi lệnh đóng; fees/funding = chi phí cộng dồn (dương = trả), bar_low/bar_high = nến đóng (đối chiếu kịch bản SL bi quan)."""
        self.trades.append({"symbol": sym, "strategy": e["strategy"], "side": pos.pos_type.name, "enter_time": int(pos.enter_time),
                            "enter_price": float(pos.enter_price), "avg_price": float(pos.avg_price or pos.enter_price),
                            "close_time": int(pos.close_time), "close_price": float(pos.close_price), "qty": float(pos.qty),
                            "layers": int(pos.layers or 1), "pnl": round(float(pos.real_pnl), 6), "reason": pos.close_reason,
                            "fees": round(float(pos.fees_usd or 0), 6), "funding": round(float(pos.funding_usd or 0), 6),
                            "bar_low": float(low), "bar_high": float(high)})

    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến chạy ở thời điểm t (open_time). bars[sym] = (o, h, l, c) (tài sản không có nến: bỏ qua); sig[sym] = [{match, stop, vol}]
        theo thứ tự chiến lược; funding[sym] = [(funding_time, rate)] đến hạn <= t. -> các lệnh đóng ở nến này."""
        n0 = len(self.trades)
        cap = float(self.risk["max_gross_exposure"])
        kill = float(self.risk.get("kill_switch_dd_pct") or 0) / 100.0
        can_trade = t >= self.trade_start and self.halted_at is None
        touched = False
        for b, bk in enumerate(self.books):
            sym = bk["symbol"]
            if sym not in bars:
                continue
            o, h, l, c = bars[sym]
            for ft, rate in (funding or {}).get(sym, []):
                for e in bk["entries"]:
                    e["tracker"].apply_funding(float(rate), float(o))
            for e, s in zip(bk["entries"], sig[sym]):
                tr = e["tracker"]
                m = bool(s["match"])
                if not tr.is_open and not tr.pending_entry and not m:
                    continue
                can_open = False
                if can_trade and tr.pending_entry and not tr.is_open:
                    n_open, per = self._counts()
                    blocked = n_open >= int(self.risk["max_positions"]) or per[b] >= int(self.risk["max_per_symbol"])
                    if not blocked:
                        self.last_close[b] = float(o)
                        room = cap * self.ledger.equity - self._gross()
                        tr.max_new_notional = max(0.0, room)
                        can_open = room > 0
                        risk_cap = float(self.risk.get("max_open_risk_pct") or 0.0) / 100.0
                        if can_open and risk_cap != 0.0:          # trần Σ rủi ro tới SL của vị thế mở (như kernel)
                            open_risk = 0.0
                            for bk2 in self.books:
                                for e2 in bk2["entries"]:
                                    if e2["tracker"].is_open:
                                        open_risk += e2["tracker"].planned_risk
                            tr.max_new_risk = risk_cap * self.ledger.equity - open_risk
                            can_open = tr.max_new_risk > 0.0
                        thr = float(self.risk.get("dd_throttle_pct") or 0.0) / 100.0
                        if can_open and thr != 0.0 and self.ledger.peak > 0.0:   # giảm rủi ro theo mức sụt vốn đã chốt
                            floor = float(self.risk.get("dd_throttle_floor", 0.25))
                            rs = 1.0 - (1.0 - self.ledger.equity / self.ledger.peak) / thr
                            rs = floor if rs < floor else rs
                            tr.risk_scale = 1.0 if rs > 1.0 else rs
                        blocked = not can_open
                    if blocked:
                        self.rejected_for_risk += 1
                vol = s.get("vol")
                pos = tr.on_bar(t, o, h, l, c, entry_signal=m and can_trade, stop_signal=bool(s["stop"]), can_open=can_open,
                                vol=float(vol) if vol is not None else float("nan"), dca_gate=bool(s.get("dca", True)))
                tr.max_new_notional = float("inf")
                tr.max_new_risk = float("inf")
                tr.risk_scale = 1.0
                if pos is not None:
                    self._collect(sym, e, pos, l, h)
            self.last_close[b], self.last_low[b], self.last_high[b], self.last_open[b] = float(c), float(l), float(h), float(o)
            touched = True
        self.last_t = t
        if touched:
            mtm, worst = self.mtm()
            self.peak_mtm = max(self.peak_mtm, mtm)
            if kill and self.halted_at is None and worst <= self.peak_mtm * (1.0 - kill):
                self.halted_at = t
                for b, bk in enumerate(self.books):
                    for e in bk["entries"]:
                        tr = e["tracker"]
                        tr.pending_entry = False
                        pos = tr.force_close(t, self.last_close[b], "Kill switch danh mục")
                        if pos is not None:
                            self._collect(bk["symbol"], e, pos, self.last_low[b], self.last_high[b])
        return self.trades[n0:]

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    out.append({"symbol": bk["symbol"], "strategy": e["strategy"], "side": e["side"], "qty": tr.qty, "avg": tr.avg,
                                "layers": tr.layer_count, "entry_time": tr.entry_time, "unrealized": tr.unrealized_pnl_usd(self.last_close[b])})
        return out
