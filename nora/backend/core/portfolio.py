"""Điều phối danh mục cho các NoraSlotStrategy (P15): luật rủi ro của `_admit` / kill switch của kernel cũ, trên số liệu của Nautilus.

Thuần Python (không import nautilus_trader): vốn, hoa hồng, vị thế đều do slot đọc từ Nautilus rồi báo vào đây.
- equity()      = số dư tài khoản Nautilus + hoa hồng của vị thế đang mở  (= "vốn đã chốt" của sổ vốn cũ: phí vào lệnh chỉ trừ khi đóng).
- mtm / worst   = số dư Nautilus + Σ lãi/lỗ chưa chốt của vị thế mở, mỗi vị thế theo giá đóng / giá xấu nhất của CHÍNH tài sản của nó.
- admit()       = policy.admit_entry (max_positions, max_per_symbol, max_gross_exposure, max_open_risk_pct, dd_throttle).
- finish_ts()   = chạy SAU khi mọi slot đã xử lý nến ở thời điểm ts: đỉnh MTM, kill switch (đóng hết, tag KILL), mẫu đường vốn.
Đường vốn: mỗi MTM_SAMPLE_MINUTES phút (mặc định 60) và mẫu cuối; trường {time (open nến), equity, equity_worst} như `_round_curve` cũ.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from backend.analys.position import position_size as policy
from backend.analys.alpha import RiskConfig

MTM_SAMPLE_MINUTES = 60


class Coordinator:
    def __init__(self, risk: RiskConfig, initial_capital: float, trade_start_ms: int, balance_fn: Callable[[], float], n_symbols: int,
                 frame_ms: int, sample_ms: int = MTM_SAMPLE_MINUTES * 60_000):
        self.risk = risk
        self.initial = float(initial_capital)
        self.trade_start = int(trade_start_ms)
        self._balance = balance_fn
        self.balance = balance_fn
        self.frame_ms = int(frame_ms)
        self.sample_ms = int(sample_ms)
        self.kill_pct = float(risk.kill_switch_dd_pct or 0.0)
        self.slots: List[Any] = []
        self.active: List[Any] = []                 # slot đang ENTERING / OPEN
        self.last: List[Tuple[float, float, float]] = [(float("nan"),) * 3] * n_symbols   # (close, low, high) nến cuối của từng tài sản
        self.reserved = 0.0                         # ký quỹ + phí vào lệnh đang giữ chỗ (sổ vốn cũ)
        self.open_fees = 0.0                        # hoa hồng Nautilus đã trừ khỏi số dư cho vị thế đang mở
        self.peak = float(initial_capital)          # đỉnh vốn đã chốt
        self.peak_mtm = float(initial_capital)
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_capital = 0
        self.venue_rejects: List[Tuple[str, str, str, str]] = []   # lệnh bị sàn mô phỏng từ chối (symbol, chiến lược, loại, lý do)
        self.rejected_for_risk = 0
        self.risk_blocked_attempts = 0
        self.positions: List[Any] = []              # PositionModel theo thứ tự đóng
        self.orders: List[Any] = []                 # OrderModel gom theo vị thế đã đóng
        self.curve: List[Dict[str, float]] = []
        self._last_sample: Optional[int] = None
        # lưới thời điểm của chunk dữ liệu hiện tại: bao nhiêu slot sẽ xử lý nến ở mỗi ts (đóng nến, ms)
        self._need_ts = np.zeros(0, dtype=np.int64)
        self._need_n = np.zeros(0, dtype=np.int64)
        self._ptr = 0
        self._cur_ts: Optional[int] = None
        self._left = 0
        self.last_bar_open: Optional[int] = None
        self.live_n = 0                             # live: số slot (mỗi ts có tối đa live_n nến, một nến/slot); 0 = backtest dùng lưới set_grid
        self.on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None   # live: Recorder nhận fill / reject / position_closed

    # ─── lưới nến ───────────────────────────────────────────────────────────
    def emit(self, kind: str, data: Dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def set_grid(self, ts: np.ndarray, counts: np.ndarray) -> None:
        self._need_ts, self._need_n, self._ptr = ts, counts, 0

    def bar_done(self, ts: int) -> None:
        """Mỗi slot gọi khi xử lý xong nến đóng ở `ts`; slot cuối cùng của ts kích hoạt finish_ts."""
        nt = self._need_ts
        if len(nt) == 0:
            # Chế độ Live: không có lưới chunk tính trước; finish_ts chạy khi đủ live_n nến của cùng ts (hoặc khi ts mới tới mà ts cũ còn thiếu)
            if not self.live_n:
                self.finish_ts(ts)
                return
            if ts != self._cur_ts:
                if self._cur_ts is not None and self._left > 0:
                    self.finish_ts(self._cur_ts)
                self._cur_ts, self._left = ts, self.live_n
            self._left -= 1
            if self._left <= 0:
                self.finish_ts(ts)
            return

        if ts != self._cur_ts:
            p = self._ptr
            while p < len(nt) and nt[p] < ts:
                p += 1
            self._ptr = p
            self._cur_ts = ts
            self._left = int(self._need_n[p]) if p < len(nt) and nt[p] == ts else 1
        self._left -= 1
        if self._left <= 0:
            self.finish_ts(ts)

    def sample_live(self, ts: int) -> Dict[str, Any]:
        """Lấy mẫu equity bằng timer khi chạy live; kiểm tra kill switch."""
        mtm, worst = self.mtm()
        if mtm > self.peak_mtm:
            self.peak_mtm = mtm
        point = {"time": int(ts), "equity": round(mtm, 4), "equity_worst": round(worst, 4)}
        self.curve.append(point)
        self._last_sample = ts
        if self.kill_pct and self.halted_at is None and self.active and policy.kill_triggered(worst, self.peak_mtm, self.kill_pct):
            self.halted_at = ts
            for s in list(self.slots):
                try:
                    if hasattr(s, "_cancel_orders"):
                        s._cancel_orders()
                except Exception:
                    pass
                s.kill()
        return point


    # ─── số liệu vốn ────────────────────────────────────────────────────────
    def equity(self) -> float:
        return self._balance() + self.open_fees

    def free(self) -> float:
        return self.equity() - self.reserved

    def mtm(self) -> Tuple[float, float]:
        """(MTM theo giá đóng, MTM xấu nhất) = số dư Nautilus + lãi/lỗ chưa chốt của vị thế mở."""
        mtm = worst = self._balance()
        for s in self.active:
            if s.qty > 0.0:
                c, lo, hi = self.last[s.sym_idx]
                mtm += s.unrealized(c)
                worst += s.unrealized(lo if s.is_long else hi)
        return mtm, worst

    def gross(self) -> float:
        tot = 0.0
        for s in self.active:
            c = self.last[s.sym_idx][0]
            if c == c:
                tot += s.exposure_qty() * c
        return tot

    def open_risk(self) -> float:
        return sum(s.planned_risk for s in self.active)

    # ─── xét hạn mức mở lệnh ────────────────────────────────────────────────
    def admit(self, slot: Any) -> Optional[policy.Admission]:
        """None = bị chặn bởi giới hạn rủi ro (đã đếm). Ngược lại Admission (trần danh nghĩa / rủi ro, hệ số rủi ro)."""
        r = self.risk
        n_open = len(self.active)
        per = sum(1 for s in self.active if s.sym_idx == slot.sym_idx)
        gross = open_risk = 0.0
        if n_open < int(r.max_positions) and per < int(r.max_per_symbol):
            gross, open_risk = self.gross(), self.open_risk()
        adm = policy.admit_entry(n_open, per, self.equity(), self.peak, gross, open_risk, r.max_positions, r.max_per_symbol,
                                 r.max_gross_exposure, r.max_open_risk_pct or 0.0, r.dd_throttle_pct or 0.0, r.dd_throttle_floor)
        if not adm.can_open:
            self.rejected_for_risk += 1
            if slot.last_blk != slot.nbar - 1:
                self.risk_blocked_attempts += 1
            slot.last_blk = slot.nbar
            return None
        return adm

    # ─── sự kiện slot ───────────────────────────────────────────────────────
    def activate(self, slot: Any) -> None:
        self.active.append(slot)

    def deactivate(self, slot: Any) -> None:
        if slot in self.active:
            self.active.remove(slot)

    def on_closed(self, slot: Any, open_ms: int, model: Any, orders: List[Any]) -> None:
        """Slot vừa đóng một vị thế (PositionClosed của Nautilus): giải phóng giữ chỗ, đỉnh vốn, cháy tài khoản, ghi lệnh."""
        self.reserved = max(0.0, self.reserved - slot.res_here)
        self.open_fees -= slot.fee_open
        eq = self.equity()
        if eq > self.peak:
            self.peak = eq
        if eq <= 0.0 and self.ruined_at is None:
            self.ruined_at = open_ms
        self.positions.append(model)
        self.orders.extend(orders)
        self.deactivate(slot)

    # ─── cuối mỗi thời điểm ─────────────────────────────────────────────────
    def finish_ts(self, ts: int) -> None:
        open_ms = ts - self.frame_ms
        due = self._last_sample is None or open_ms - self._last_sample >= self.sample_ms
        if not self.active and not due:
            return
        mtm, worst = self.mtm()
        if mtm > self.peak_mtm:
            self.peak_mtm = mtm
        if self.kill_pct and self.halted_at is None and self.active and policy.kill_triggered(worst, self.peak_mtm, self.kill_pct):
            self.halted_at = open_ms
            for s in list(self.slots):
                s.kill()
            due = True
        if due:
            self.curve.append({"time": open_ms, "equity": round(mtm, 4), "equity_worst": round(worst, 4)})
            self._last_sample = open_ms

    def final_sample(self, t_open: Optional[int], init_if_empty: float) -> None:
        """Mẫu cuối (sau khi đóng hết ở cuối dữ liệu)."""
        if t_open is None:
            self.curve.append({"time": 0, "equity": round(init_if_empty, 4), "equity_worst": round(init_if_empty, 4)})
            return
        mtm, worst = self.mtm()
        point = {"time": int(t_open), "equity": round(mtm, 4), "equity_worst": round(worst, 4)}
        if self.curve and self.curve[-1]["time"] == point["time"]:     # nến cuối đã có mẫu (đang có vị thế): thay bằng mẫu sau khi đóng hết, không trùng thời điểm
            self.curve[-1] = point
        else:
            self.curve.append(point)
