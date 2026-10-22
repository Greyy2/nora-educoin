"""Điều phối danh mục cho các NoraSlotStrategy (P15): luật rủi ro của `_admit` / kill switch của kernel cũ, trên số liệu của Nautilus.

Thuần Python (không import nautilus_trader): vốn, hoa hồng, vị thế đều do slot đọc từ Nautilus rồi báo vào đây.
- equity()      = số dư tài khoản Nautilus + hoa hồng của vị thế đang mở  (= "vốn đã chốt" của sổ vốn cũ: phí vào lệnh chỉ trừ khi đóng).
- mtm / worst   = số dư Nautilus + Σ lãi/lỗ chưa chốt của vị thế mở, mỗi vị thế theo giá đóng / giá xấu nhất của CHÍNH tài sản của nó.
- admit()       = policy.admit_entry (max_positions, max_per_symbol, max_gross_exposure, max_open_risk_pct, dd_throttle).
- finish_ts()   = chạy SAU khi mọi slot đã xử lý nến ở thời điểm ts: đỉnh MTM, kill switch (đóng hết, tag KILL), mẫu đường vốn.
Đường vốn: mỗi MTM_SAMPLE_MINUTES phút (mặc định 60) và mẫu cuối; trường {time (open nến), equity, equity_worst} như `_round_curve` cũ.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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


# ─── MASTER PORTFOLIO LEDGER & VIRTUAL SLEEVE ARCHITECTURE ─────────────────

@dataclass
class RiskPolicyConfig:
    max_loss_per_trade_pct: float = 0.015    # 1.5% của sleeve (15 USDT trên 1,000 USDT)
    max_daily_sleeve_loss_pct: float = 0.03  # 3.0% của sleeve (30 USDT trên 1,000 USDT)
    max_sleeve_drawdown_pct: float = 0.15    # 15.0% của sleeve (150 USDT trên 1,000 USDT)
    master_circuit_breaker_pct: float = 0.20 # 20.0% của Master (2,000 USDT trên 10,000 USDT)


@dataclass
class SleeveState:
    sleeve_id: str
    name: str = ""
    allocated_capital: float = 1000.0        # Hạn mức phân bổ hiện tại (Active: 1000, Closed: 0)
    initial_allocated: float = 1000.0        # Hạn mức cấu hình ban đầu
    realized_pnl: float = 0.0                # PnL đã chốt (gộp)
    fees_paid: float = 0.0                   # Phí sàn đã trả
    unrealized_pnl: float = 0.0              # Lãi/lỗ thả nổi hiện tại
    used_margin: float = 0.0                 # Ký quỹ đang cam kết
    daily_realized_pnl: float = 0.0          # PnL đã chốt trong ngày
    peak_equity: float = 1000.0              # Đỉnh vốn của sleeve
    status: str = "ACTIVE"                   # ACTIVE | ONLY_REDUCE | LOCKED | CLOSED | STOPPED

    @property
    def net_realized_pnl(self) -> float:
        return self.realized_pnl - self.fees_paid

    @property
    def sleeve_cash(self) -> float:
        return self.allocated_capital + self.net_realized_pnl

    @property
    def sleeve_equity(self) -> float:
        return self.sleeve_cash + self.unrealized_pnl

    @property
    def drawdown_from_peak_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        dd = (self.peak_equity - self.sleeve_equity) / self.peak_equity * 100.0
        return max(0.0, dd)

    @property
    def drawdown_from_allocated_pct(self) -> float:
        base = self.initial_allocated if self.initial_allocated > 0 else self.allocated_capital
        if base <= 0:
            return 0.0
        eq = (self.initial_allocated + self.net_realized_pnl) if self.status == "CLOSED" else self.sleeve_equity
        dd = (base - eq) / base * 100.0
        return max(0.0, dd)


class MasterPortfolioLedger:
    """Sổ cái Master Quỹ quản lý 1 Master Wallet (10,000 USDT) và các Virtual Sleeves linh hoạt.
    
    Tuân thủ nghiêm ngặt các Accounting Invariants:
    1. initial_capital bất biến = 10,000 USDT (hoặc cấu hình vốn gốc).
    2. master_cash = initial_capital + sum(realized_pnl) - sum(fees).
    3. master_equity = master_cash + sum(unrealized_pnl).
    4. sum(sleeve_equity_i) + unallocated_capital == master_equity.
    5. initial_capital == total_allocated_capital + unallocated_capital.
    6. sum(committed_margin) <= master_cash.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        reserve_floor: float = 0.0,
        risk_policy: Optional[RiskPolicyConfig] = None,
    ):
        self.initial_capital: float = float(initial_capital)
        self.reserve_floor: float = float(reserve_floor)
        self.risk_policy: RiskPolicyConfig = risk_policy or RiskPolicyConfig()

        self.sleeves: Dict[str, SleeveState] = {}
        self.processed_fill_ids: Set[str] = set()
        self.peak_master_equity: float = float(initial_capital)
        self.circuit_breaker_triggered: bool = False
        self.total_wins: float = 0.0
        self.total_losses: float = 0.0
        self.closed_trades_count: int = 0
        self.winning_trades_count: int = 0

    @property
    def profit_factor(self) -> Optional[float]:
        if self.total_losses > 0:
            return round(self.total_wins / self.total_losses, 2)
        if self.total_wins > 0:
            return 999.0
        return None

    @property
    def win_rate_pct(self) -> Optional[float]:
        if self.closed_trades_count > 0:
            return round((self.winning_trades_count / self.closed_trades_count) * 100.0, 2)
        return None

    def register_sleeve(
        self,
        sleeve_id: str,
        name: str = "",
        allocated_capital: float = 1000.0,
        initial_allocated: Optional[float] = None,
    ) -> SleeveState:
        if sleeve_id in self.sleeves:
            return self.sleeves[sleeve_id]
        init_cap = initial_allocated if initial_allocated is not None else (allocated_capital if allocated_capital > 0 else 1000.0)
        sleeve = SleeveState(
            sleeve_id=sleeve_id,
            name=name,
            allocated_capital=allocated_capital,
            initial_allocated=init_cap,
            peak_equity=init_cap,
        )
        self.sleeves[sleeve_id] = sleeve
        return sleeve

    @property
    def master_realized_pnl(self) -> float:
        return sum(s.realized_pnl for s in self.sleeves.values())

    @property
    def master_fees(self) -> float:
        return sum(s.fees_paid for s in self.sleeves.values())

    @property
    def master_unrealized_pnl(self) -> float:
        return sum(s.unrealized_pnl for s in self.sleeves.values())

    @property
    def master_cash(self) -> float:
        # Invariant 2
        return self.initial_capital + self.master_realized_pnl - self.master_fees

    @property
    def master_equity(self) -> float:
        # Invariant 3
        return self.master_cash + self.master_unrealized_pnl

    @property
    def total_allocated_capital(self) -> float:
        """Tổng vốn phân bổ theo cấu hình của toàn bộ các bot (chưa đóng/giải phóng)."""
        return sum(s.allocated_capital for s in self.sleeves.values() if s.status != "CLOSED")

    @property
    def allocation_headroom_from_initial(self) -> float:
        """Hạn mức chưa phân bổ theo vốn gốc cấu hình danh mục (10,000 USDT - sum(allocated_capital))."""
        return max(0.0, self.initial_capital - self.total_allocated_capital)

    @property
    def capital_headroom_from_equity(self) -> float:
        """Hạn mức vốn thực tế còn lại theo Master Equity danh mục (master_equity - sum(allocated_capital)).
        
        Nếu danh mục đang lỗ, Master Equity giảm -> hạn mức tiền thực tế có thể cấp cho bot mới
        phải giảm theo tương ứng để không cấp tiền khống (phantom capital).
        """
        return max(0.0, self.master_equity - self.total_allocated_capital)

    @property
    def committed_margin(self) -> float:
        """Ký quỹ đang bị sàn khóa cho các vị thế mở."""
        return sum(s.used_margin for s in self.sleeves.values())

    @property
    def free_cash(self) -> float:
        """Tiền mặt rảnh rỗi chưa bị khóa margin (master_cash - committed_margin).
        
        Lưu ý: free_cash chỉ có nghĩa là tiền chưa bị khóa làm margin.
        Nó không đồng nghĩa toàn bộ số đó được cấp cho bot mới.
        """
        return max(0.0, self.master_cash - self.committed_margin)

    @property
    def deployable_headroom_for_new_bot(self) -> float:
        """Số vốn thực tế an toàn tối đa có thể cấp ngay cho bot mới.
        
        Phải thỏa mãn đồng thời cả 3 điều kiện:
        1. Không vượt quá hạn mức vốn gốc chưa cấp (allocation_headroom_from_initial).
        2. Không vượt quá Master Equity thực tế còn lại (capital_headroom_from_equity).
        3. Không vượt quá tiền mặt tự do chưa ký quỹ (free_cash).
        """
        return max(0.0, min(
            self.allocation_headroom_from_initial,
            self.capital_headroom_from_equity,
            self.free_cash,
        ))

    @property
    def unallocated_capital(self) -> float:
        """Alias cho allocation_headroom_from_initial (giữ tương thích)."""
        return self.allocation_headroom_from_initial

    @property
    def available_to_allocate(self) -> float:
        """Hạn mức an toàn thực tế có thể cấp cho bot mới (= deployable_headroom_for_new_bot)."""
        return self.deployable_headroom_for_new_bot

    @property
    def deployable_cash(self) -> float:
        return max(0.0, self.master_cash - self.reserve_floor)

    @property
    def drawdown_from_initial_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        dd = (self.initial_capital - self.master_equity) / self.initial_capital * 100.0
        return max(0.0, dd)

    @property
    def drawdown_from_peak_pct(self) -> float:
        if self.peak_master_equity <= 0:
            return 0.0
        dd = (self.peak_master_equity - self.master_equity) / self.peak_master_equity * 100.0
        return max(0.0, dd)

    def record_fill(
        self,
        fill_id: str,
        sleeve_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee: float = 0.0,
        realized_gain: float = 0.0,
        margin_delta: float = 0.0,
        timestamp: int = 0,
    ) -> bool:
        """Xử lý sự kiện fill bảo đảm tính idempotent (đúng một lần duy nhất)."""
        if fill_id in self.processed_fill_ids:
            return False  # Bỏ qua trùng lặp
        self.processed_fill_ids.add(fill_id)

        sleeve = self.sleeves.get(sleeve_id)
        if not sleeve:
            sleeve = self.register_sleeve(sleeve_id)

        sleeve.realized_pnl += realized_gain
        sleeve.fees_paid += fee
        sleeve.daily_realized_pnl += (realized_gain - fee)
        sleeve.used_margin = max(0.0, sleeve.used_margin + margin_delta)

        # Cập nhật peak equity của sleeve
        if sleeve.sleeve_equity > sleeve.peak_equity:
            sleeve.peak_equity = sleeve.sleeve_equity

        # Kiểm tra ngưỡng Drawdown của Sleeve
        max_sleeve_dd = sleeve.allocated_capital * self.risk_policy.max_sleeve_drawdown_pct
        if (sleeve.allocated_capital - sleeve.sleeve_equity) >= max_sleeve_dd:
            sleeve.status = "LOCKED"

        # Cập nhật peak master equity & Master Circuit Breaker
        current_eq = self.master_equity
        if current_eq > self.peak_master_equity:
            self.peak_master_equity = current_eq

        max_master_loss = self.initial_capital * self.risk_policy.master_circuit_breaker_pct
        if (self.initial_capital - current_eq) >= max_master_loss:
            self.circuit_breaker_triggered = True
            for s in self.sleeves.values():
                s.status = "LOCKED"

        return True

    def update_unrealized(self, sleeve_id: str, unrealized: float, used_margin: Optional[float] = None) -> None:
        sleeve = self.sleeves.get(sleeve_id)
        if sleeve:
            sleeve.unrealized_pnl = unrealized
            if used_margin is not None:
                sleeve.used_margin = max(0.0, used_margin)
            if sleeve.sleeve_equity > sleeve.peak_equity:
                sleeve.peak_equity = sleeve.sleeve_equity
            if self.master_equity > self.peak_master_equity:
                self.peak_master_equity = self.master_equity

    def verify_invariants(self) -> Dict[str, bool]:
        """Kiểm toán tự động các Invariants toán học của hệ thống."""
        inv1 = abs(self.initial_capital - 10000.0) < 1e-6
        inv2 = abs(self.master_cash - (self.initial_capital + self.master_realized_pnl - self.master_fees)) < 1e-6
        inv3 = abs(self.master_equity - (self.master_cash + self.master_unrealized_pnl)) < 1e-6

        # Invariant 4: master_equity == sum(sleeve_equity) + unallocated_capital
        total_sleeve_equity = sum(s.sleeve_equity for s in self.sleeves.values())
        inv4 = abs(self.master_equity - (total_sleeve_equity + self.unallocated_capital)) < 1e-4

        # Invariant 5: initial_capital == total_allocated_capital + unallocated_capital
        inv5 = abs(self.initial_capital - (self.total_allocated_capital + self.unallocated_capital)) < 1e-4

        # Invariant 6: master_net_pnl == sum(sleeve_net_realized + sleeve_unrealized)
        net_pnl = self.master_equity - self.initial_capital
        total_sleeve_net_pnl = sum((s.net_realized_pnl + s.unrealized_pnl) for s in self.sleeves.values())
        inv6 = abs(net_pnl - total_sleeve_net_pnl) < 1e-4

        return {
            "initial_capital_constant": inv1,
            "master_cash_exact": inv2,
            "master_equity_exact": inv3,
            "master_equity_equals_sum_sleeves_plus_unallocated": inv4,
            "capital_allocation_identity": inv5,
            "master_net_pnl_equals_sum_sleeves": inv6,
        }

    def get_snapshot(self) -> Dict[str, Any]:
        """Snapshot đơn nguồn (Single Source of Truth) chuẩn hóa cho UI & API."""
        net_pnl = self.master_equity - self.initial_capital
        roi_pct = (net_pnl / self.initial_capital * 100.0) if self.initial_capital > 0 else 0.0

        total_allocated = self.total_allocated_capital
        alloc_headroom_init = self.allocation_headroom_from_initial
        cap_headroom_eq = self.capital_headroom_from_equity
        deployable_hd = self.deployable_headroom_for_new_bot
        free_c = self.free_cash
        sum_bot_equity = sum(s.sleeve_equity for s in self.sleeves.values())
        sum_bot_net_pnl = sum((s.net_realized_pnl + s.unrealized_pnl) for s in self.sleeves.values())

        return {
            "portfolio_summary": {
                "initial_capital": self.initial_capital,
                "total_allocated_capital": round(total_allocated, 4),
                "allocation_headroom_from_initial": round(alloc_headroom_init, 4),
                "capital_headroom_from_equity": round(cap_headroom_eq, 4),
                "deployable_headroom_for_new_bot": round(deployable_hd, 4),
                "unallocated_capital": round(alloc_headroom_init, 4),
                "available_to_allocate": round(deployable_hd, 4),
                "master_cash": round(self.master_cash, 4),
                "master_equity": round(self.master_equity, 4),
                "realized_pnl": round(self.master_realized_pnl, 4),
                "unrealized_pnl": round(self.master_unrealized_pnl, 4),
                "total_fees": round(self.master_fees, 4),
                "net_pnl": round(net_pnl, 4),
                "roi_pct": round(roi_pct, 2),
                "profit_factor": self.profit_factor,
                "win_rate_pct": self.win_rate_pct,
                "closed_trades_count": self.closed_trades_count,
                "winning_trades_count": self.winning_trades_count,
                "deployable_cash": round(self.master_cash, 4),
                "committed_margin": round(self.committed_margin, 4),
                "free_cash": round(free_c, 4),
                "margin_utilization_pct": round((self.committed_margin / self.master_cash * 100.0) if self.master_cash > 0 else 0.0, 2),
                "open_risk": round(sum(s.used_margin for s in self.sleeves.values()), 4),
                "drawdown_from_initial_pct": round(self.drawdown_from_initial_pct, 4),
                "drawdown_from_peak_pct": round(self.drawdown_from_peak_pct, 4),
                "circuit_breaker_status": "TRIGGERED" if self.circuit_breaker_triggered else "NORMAL",
            },
            "reconciliation": {
                "master_initial_capital": self.initial_capital,
                "total_allocated_capital": round(total_allocated, 4),
                "allocation_headroom_from_initial": round(alloc_headroom_init, 4),
                "capital_headroom_from_equity": round(cap_headroom_eq, 4),
                "unallocated_capital": round(alloc_headroom_init, 4),
                "capital_allocation_sum": round(total_allocated + alloc_headroom_init, 4),
                "capital_discrepancy": round(self.initial_capital - (total_allocated + alloc_headroom_init), 4),
                "master_equity": round(self.master_equity, 4),
                "active_sleeves_equity": round(sum(s.sleeve_equity for s in self.sleeves.values() if s.status != "CLOSED"), 4),
                "closed_sleeves_net_pnl": round(sum(s.net_realized_pnl for s in self.sleeves.values() if s.status == "CLOSED"), 4),
                "total_sleeves_equity": round(sum_bot_equity, 4),
                "unallocated_cash": round(self.master_cash - sum(s.sleeve_cash for s in self.sleeves.values() if s.status != "CLOSED"), 4),
                "calculated_master_equity": round(sum_bot_equity + alloc_headroom_init, 4),
                "equity_discrepancy": round(self.master_equity - (sum_bot_equity + alloc_headroom_init), 4),
                "master_net_pnl": round(net_pnl, 4),
                "sum_bot_net_pnl": round(sum_bot_net_pnl, 4),
                "pnl_discrepancy": round(net_pnl - sum_bot_net_pnl, 4),
            },
            "sleeves": [
                {
                    "sleeve_id": s.sleeve_id,
                    "name": s.name,
                    "configured_allocation": s.allocated_capital,
                    "initial_allocation": s.initial_allocated,
                    "sleeve_limit": s.allocated_capital,
                    "sleeve_cash": round(s.sleeve_cash, 4),
                    "current_equity": round(s.sleeve_equity, 4),
                    "sleeve_equity": round(s.sleeve_equity, 4),
                    "settled_balance": round(s.initial_allocated + s.net_realized_pnl, 4) if s.status == "CLOSED" else round(s.sleeve_cash, 4),
                    "net_realized_pnl": round(s.net_realized_pnl, 4),
                    "unrealized_pnl": round(s.unrealized_pnl, 4),
                    "used_margin": round(s.used_margin, 4),
                    "status": s.status,
                    "drawdown_pct": round(s.drawdown_from_allocated_pct, 2),
                }
                for s in self.sleeves.values()
            ],
            "invariants_audit": self.verify_invariants(),
        }


class PortfolioAdmissionController:
    """Cổng soát vé rủi ro trước khi vào lệnh (Pre-Trade Risk Gate)."""

    def __init__(self, ledger: MasterPortfolioLedger):
        self.ledger = ledger

    def admit_order(
        self,
        sleeve_id: str,
        side: str,
        requested_qty: float,
        price: float,
        contract_value: float,
        margin_rate: float,
        sl_price: Optional[float] = None,
        is_reduce_only: bool = False,
    ) -> Tuple[bool, str]:
        # Lệnh đóng vị thế (reduce-only) luôn được chấp nhận để giảm rủi ro
        if is_reduce_only:
            return True, "ADMITTED_REDUCE_ONLY"

        # 1. Kiểm tra Circuit Breaker toàn Master
        if self.ledger.circuit_breaker_triggered:
            return False, "MASTER_CIRCUIT_BREAKER_TRIGGERED"

        # 2. Kiểm tra Sleeve tồn tại
        sleeve = self.ledger.sleeves.get(sleeve_id)
        if not sleeve:
            return False, "SLEEVE_NOT_FOUND"

        # 3. Kiểm tra trạng thái Sleeve
        if sleeve.status == "LOCKED":
            return False, "SLEEVE_LOCKED_MAX_LOSS"
        if sleeve.status == "ONLY_REDUCE":
            return False, "SLEEVE_ONLY_REDUCE"

        # 4. Kiểm tra Max Loss Per Trade nếu có Stop Loss
        if sl_price is not None and sl_price > 0:
            loss_per_coin = abs(price - sl_price)
            max_loss_trade = loss_per_coin * requested_qty * contract_value
            max_allowed = sleeve.allocated_capital * self.ledger.risk_policy.max_loss_per_trade_pct
            if max_loss_trade > (max_allowed + 1e-6):
                return False, f"RISK_PER_TRADE_EXCEEDED: {max_loss_trade:.2f} > limit {max_allowed:.2f}"

        # 5. Kiểm tra Ký quỹ của Sleeve
        notional = requested_qty * contract_value * price
        req_margin = notional * margin_rate
        if sleeve.used_margin + req_margin > (sleeve.allocated_capital + 1e-6):
            return False, f"SLEEVE_MARGIN_EXCEEDED: need {req_margin:.2f}, sleeve cap {sleeve.allocated_capital:.2f}"

        # 6. Kiểm tra Tiền mặt khả dụng của Master
        if self.ledger.committed_margin + req_margin > (self.ledger.deployable_cash + 1e-6):
            return False, f"PORTFOLIO_CASH_EXCEEDED: req_margin {req_margin:.2f} exceeds deployable_cash {self.ledger.deployable_cash:.2f}"

        return True, "ADMITTED"

    def admit_bot_launch(self, requested_allocation: float) -> Tuple[bool, str]:
        """Kiểm tra hạn mức cấp vốn khi người dùng bật bot mới (Admission Gate for New Bots).
        
        Quy tắc nghiêm ngặt:
        1. requested_allocation > 0
        2. Không vượt hạn mức vốn gốc cấu hình: requested_allocation <= allocation_headroom_from_initial
        3. Không vượt hạn mức Master Equity thực tế: requested_allocation <= capital_headroom_from_equity
           (Tránh cấp vốn khống / phantom capital khi danh mục đang lỗ hoặc sụt giảm equity)
        4. Không vượt tiền mặt tự do chưa ký quỹ: requested_allocation <= free_cash
        """
        if requested_allocation <= 0:
            return False, "INVALID_ALLOCATION: Vốn phân bổ cho bot phải lớn hơn 0"

        # 1. Kiểm tra hạn mức từ vốn gốc cấu hình
        if requested_allocation > (self.ledger.allocation_headroom_from_initial + 1e-6):
            return False, (
                f"EXCEEDS_INITIAL_ALLOCATION_HEADROOM: Yêu cầu {requested_allocation:.2f} USDT vượt quá "
                f"hạn mức vốn gốc chưa cấp ({self.ledger.allocation_headroom_from_initial:.2f} USDT) từ tổng 10,000 USDT"
            )

        # 2. Kiểm tra hạn mức từ Master Equity thực tế
        if requested_allocation > (self.ledger.capital_headroom_from_equity + 1e-6):
            return False, (
                f"EXCEEDS_EQUITY_HEADROOM: Master Equity hiện tại là {self.ledger.master_equity:.2f} USDT, "
                f"sau khi trừ vốn đã cấp ({self.ledger.total_allocated_capital:.2f} USDT), "
                f"hạn mức thực tế chỉ còn {self.ledger.capital_headroom_from_equity:.2f} USDT"
            )

        # 3. Kiểm tra tiền mặt tự do (Free Cash) chưa bị giữ làm margin
        if requested_allocation > (self.ledger.free_cash + 1e-6):
            return False, (
                f"INSUFFICIENT_FREE_CASH: Tiền mặt rảnh rỗi chưa ký quỹ chỉ còn {self.ledger.free_cash:.2f} USDT, "
                f"không đủ để cấp {requested_allocation:.2f} USDT"
            )

        return True, "ALLOCATION_ADMITTED"


_MASTER_LEDGER_INSTANCE: Optional[MasterPortfolioLedger] = None
_ADMISSION_CONTROLLER_INSTANCE: Optional[PortfolioAdmissionController] = None


def get_master_portfolio_ledger() -> MasterPortfolioLedger:
    global _MASTER_LEDGER_INSTANCE
    if _MASTER_LEDGER_INSTANCE is None:
        _MASTER_LEDGER_INSTANCE = MasterPortfolioLedger(initial_capital=10_000.0, reserve_floor=0.0)
        # Khởi tạo 5 sleeve mặc định đề xuất: 1,000 USDT mỗi bot
        for i, code in enumerate(["A", "B", "C", "D", "E"], 1):
            _MASTER_LEDGER_INSTANCE.register_sleeve(f"sleeve_{code.lower()}", f"Bot {code} Sleeve", 1000.0)
    return _MASTER_LEDGER_INSTANCE


def get_portfolio_admission_controller() -> PortfolioAdmissionController:
    global _ADMISSION_CONTROLLER_INSTANCE
    if _ADMISSION_CONTROLLER_INSTANCE is None:
        _ADMISSION_CONTROLLER_INSTANCE = PortfolioAdmissionController(get_master_portfolio_ledger())
    return _ADMISSION_CONTROLLER_INSTANCE


def get_live_master_ledger(mode: str = "paper") -> MasterPortfolioLedger:
    """Tạo hoặc đồng bộ MasterPortfolioLedger từ các bot đang chạy thực tế trên đĩa."""
    import os
    import json
    from backend.models.storage import data_home
    from backend.adapter.exchange import bot_status, ledger_from_dir, _read_json

    root = os.path.join(data_home(), "live", mode)
    ledger = MasterPortfolioLedger(initial_capital=10_000.0, reserve_floor=0.0)
    if not os.path.isdir(root):
        return ledger

    # Quét các bot đang trong thư mục chính và thư mục archived (thuộc session Master hiện tại)
    bot_dirs = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            if d != "archived" and os.path.isdir(os.path.join(root, d)):
                bot_dirs.append((d, os.path.join(root, d), False))

    arch_root = os.path.join(root, "archived")
    if os.path.isdir(arch_root):
        for d in sorted(os.listdir(arch_root)):
            arch_dir = os.path.join(arch_root, d)
            if os.path.isdir(arch_dir):
                bot_dirs.append((d, arch_dir, True))

    for d, b_dir, is_archived in bot_dirs:
        meta = _read_json(os.path.join(b_dir, "bot.json"))
        if not meta:
            continue

        started_at = int(meta.get("started_at") or 0)
        # Chỉ nạp các bot thuộc phiên Master Fund hiện tại (bỏ qua bot cũ từ các đợt test trước 1792485960)
        if started_at < 1792485960000:
            continue

        st = bot_status(meta, b_dir)
        is_running = (st == "running")
        is_closed = (meta.get("sleeve_status") == "CLOSED") or (is_archived and st == "stopped")

        if not is_running and st != "stopped":
            continue

        b_id = meta.get("bot_id", d)
        # Vốn phân bổ cấu hình gốc của bot
        orig_cap = float(meta.get("capital") or 1000.0)
        strat_name = meta.get("strategy") or b_id

        # Đọc Realized PnL & Phí sàn tích lũy từ events.jsonl qua OwnLedger
        led = ledger_from_dir(b_dir, orig_cap, meta.get("cl_tag"))

        # Tích lũy số lệnh thắng/thua để tính Profit Factor & Win Rate chuẩn xác
        for t in led.trades:
            ledger.closed_trades_count += 1
            pnl = float(t.get("pnl") or 0.0)
            if pnl > 0:
                ledger.total_wins += pnl
                ledger.winning_trades_count += 1
            elif pnl < 0:
                ledger.total_losses += abs(pnl)

        if is_closed:
            # Bot đã đóng và quyết toán: Vốn phân bổ được thu hồi về Master (allocated_capital = 0.0)
            sleeve = ledger.register_sleeve(
                f"sleeve_{b_id}",
                strat_name,
                allocated_capital=0.0,
                initial_allocated=orig_cap,
            )
            sleeve.realized_pnl = led.realized
            sleeve.fees_paid = led.fees
            sleeve.unrealized_pnl = 0.0
            sleeve.used_margin = 0.0
            sleeve.status = "CLOSED"
        elif is_running:
            # Bot đang chạy: Hạn mức vốn phân bổ đang hoạt động
            sleeve = ledger.register_sleeve(
                f"sleeve_{b_id}",
                strat_name,
                allocated_capital=orig_cap,
                initial_allocated=orig_cap,
            )
            sleeve.realized_pnl = led.realized
            sleeve.fees_paid = led.fees

            # Đọc vị thế mở thực tế từ positions.json
            pos_file = os.path.join(b_dir, "positions.json")
            positions = []
            if os.path.exists(pos_file):
                try:
                    with open(pos_file, encoding="utf-8") as f:
                        positions = json.load(f)
                except Exception:
                    pass

            unreal = sum(float(p.get("unrealized_usd") or 0.0) for p in positions)
            sleeve.unrealized_pnl = unreal

            # Ký quỹ thực tế đã cam kết: notional / 10.0 (đòn bẩy chuẩn 10x của OKX SWAP)
            used_m = 0.0
            for p in positions:
                q = float(p.get("qty") or 0.0)
                px = float(p.get("mark") or p.get("mark_price") or p.get("avg_price") or 0.0)
                used_m += (q * px) / 10.0
            sleeve.used_margin = used_m
            sleeve.status = "ACTIVE"
        else:
            # Bot đã dừng nhưng chưa quyết toán đóng sleeve
            sleeve = ledger.register_sleeve(
                f"sleeve_{b_id}",
                strat_name,
                allocated_capital=orig_cap,
                initial_allocated=orig_cap,
            )
            sleeve.realized_pnl = led.realized
            sleeve.fees_paid = led.fees
            sleeve.unrealized_pnl = 0.0
            sleeve.used_margin = 0.0
            sleeve.status = "STOPPED"

    return ledger
