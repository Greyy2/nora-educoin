"""Module Quản lý Vị thế, Sizing & Phân bổ Vốn Độc lập của Adapter (backend/adapter/execution.py).

Đặc tả Order Management System (OMS) chuẩn sàn cấp độ Production:
1. Chuyển quyết định chiến lược (SignalDecision từ signal.py) thành OrderAction hợp lệ:
   - readings.py (MarketBar) -> signal.py (SignalDecision) -> execution.py (OrderAction).
   - execution.py KHÔNG tự quyết định breakout hay exit; nó chỉ thực thi quyết định của signal.py!
2. Quản lý toàn diện vòng đời lệnh (In-flight PendingOrder):
   - Chặn tuyệt đối việc tạo lệnh mới khi đang có PendingOrder.
   - Hỗ trợ Khớp một phần (Partial Fills) với giá bình quân gia quyền (VWAP).
   - Chống trùng lặp sự kiện khớp lệnh (Fill De-duplication) và chống Overfill.
   - Hỗ trợ Partial fill cho cả CLOSE_ALL (không làm mất vị thế còn lại).
3. Đa tài sản & Contract Mapping chuẩn hóa:
   - Đọc InstrumentSpec (ctVal, multiplier, lotSz, minSz, tickSz, fees).
   - Sizing 3 cận an toàn chuẩn hóa: contract_value = ctVal * multiplier.
   - Notional Cap co giãn tự động theo Capital (Compound-friendly từ 10.000$ tới 20.000$+).
4. Làm tròn SL/TP theo hướng an toàn (Tick Direction):
   - Long: SL làm tròn xuống (floor), TP làm tròn lên (ceil).
   - Short: SL làm tròn lên (ceil), TP làm tròn xuống (floor).
5. Ưu tiên lệnh thoát bảo vệ: Tự động hủy lệnh Partial TP chờ nếu có tín hiệu thoát khẩn cấp.
6. Lưu trữ TradeCycleResult trước khi reset trạng thái vị thế.
7. Vòng đời PAUSE_ENTRY: Hủy pending entry, chờ broker xác nhận cancel, chỉ dừng khi Flat.
8. Giám sát trạng thái Protective Orders (SL/TP) từ sàn; kích hoạt Emergency Fallback nếu bị Reject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_CEILING
from enum import Enum
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.adapter.readings import MarketBar
from backend.analys.signal.signal import SignalDecision


class BotLifecycleState(str, Enum):
    RUNNING = "running"
    PAUSE_ENTRY = "pause_entry"
    STOPPED = "stopped"


class ExitReason(str, Enum):
    NONE = "none"
    CYCLE_SL = "cycle_sl"
    SESSION_CUTOFF = "session_cutoff"
    OPPOSITE_BAND = "opposite_band"
    CENTER_EXIT = "center_exit"
    PARTIAL_TP = "partial_tp"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    CANCEL_REQUESTED = "cancel_requested"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ProtectiveStatus(str, Enum):
    NOT_SENT = "not_sent"
    PENDING_ACK = "pending_ack"
    ACTIVE = "active"
    REJECTED = "rejected"


@dataclass(frozen=True)
class InstrumentSpec:
    """Đặc tả thông số hợp đồng chuẩn hóa của sàn giao dịch (Coin perp / CFD / CFS)."""
    symbol: str
    ctVal: float                            # Giá trị cơ sở của 1 hợp đồng (vd: 0.01 BTC, 0.1 ETH, 1.0 CFD)
    lotSz: float                            # Bước nhảy số lượng hợp đồng (vd: 0.01)
    minSz: float                            # Số lượng hợp đồng tối thiểu (vd: 0.01)
    tickSz: float                           # Bước giá tối thiểu (vd: 0.1)
    multiplier: float = 1.0                 # Hệ số nhân phụ (Hợp đồng tương lai / CFD / VN30F)
    quote_currency: str = "USDT"
    account_currency: str = "USDT"
    broker_margin_init: float = 0.02        # Tỷ lệ ký quỹ tối thiểu của sàn (vd: 0.02 = 2%)
    broker_max_leverage: float = 100.0      # Đòn bẩy tối đa sàn cho phép
    maker_fee_rate: float = 0.0002          # Phí Maker (0.02% OKX VIP0)
    taker_fee_rate: float = 0.0005          # Phí Taker (0.05% OKX VIP0)
    slippage_rate: float = 0.0002           # Trượt giá dự tính (0.02%)

    def __post_init__(self):
        if self.ctVal <= 0:
            raise ValueError("InstrumentSpec.ctVal must be positive")
        if self.multiplier <= 0:
            raise ValueError("InstrumentSpec.multiplier must be positive")
        if self.lotSz <= 0:
            raise ValueError("InstrumentSpec.lotSz must be positive")
        if self.minSz < self.lotSz:
            raise ValueError("InstrumentSpec.minSz must be >= lotSz")
        if self.tickSz <= 0:
            raise ValueError("InstrumentSpec.tickSz must be positive")
        if self.broker_margin_init < 0:
            raise ValueError("InstrumentSpec.broker_margin_init must be non-negative")
        if self.broker_max_leverage <= 0:
            raise ValueError("InstrumentSpec.broker_max_leverage must be positive")

    @property
    def contract_value(self) -> float:
        """Giá trị thực tế của 1 hợp đồng = ctVal * multiplier."""
        return self.ctVal * self.multiplier


@dataclass(frozen=True)
class OrderAction:
    """Hành động phát sinh từ Execution Model để gửi sang Broker / TradingNode."""
    action_type: str                        # "ENTRY", "PARTIAL_CLOSE", "CLOSE_ALL", "CANCEL", "HOLD"
    side: str                               # "BUY", "SELL", "HOLD"
    qty_contracts: float                    # Số lượng hợp đồng (đã floor theo lotSz)
    coin_qty: float                         # Khối lượng tài sản cơ sở (qty_contracts * contract_value)
    expected_price: float                   # Giá dự kiến phát lệnh
    notional_quote: float                   # Giá trị danh nghĩa theo Quote Currency
    notional_account: float                 # Giá trị danh nghĩa theo Account Currency
    margin_account: float                   # Tiền ký quỹ ước tính theo Account Currency
    order_type: OrderType = OrderType.MARKET
    sl_price: Optional[float] = None        # Mức giá Stop Loss đề xuất
    tp_price: Optional[float] = None        # Mức giá Take Profit đề xuất
    exit_reason: ExitReason = ExitReason.NONE
    order_id: Optional[str] = None          # Định danh lệnh khi quản lý in-flight
    estimated_fee_ac: float = 0.0           # Phí giao dịch ước tính theo Account Currency
    reason: str = ""                        # Lý do quyết định hoặc từ chối lệnh


@dataclass
class PendingOrder:
    """Theo dõi chi tiết lệnh đang chờ broker xử lý (In-flight Order)."""
    order_id: str
    action_type: str                        # "ENTRY", "PARTIAL_CLOSE", "CLOSE_ALL", "CANCEL"
    side: str                               # "BUY", "SELL"
    requested_qty: float
    filled_qty: float = 0.0
    cumulative_cost: float = 0.0
    expected_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    created_ts: int = 0
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    exit_reason: ExitReason = ExitReason.NONE


@dataclass(frozen=True)
class TradeCycleResult:
    """Bản ghi kết quả chu kỳ vị thế sau khi đóng hoàn toàn (để lưu trữ và telemetry)."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty_contracts: float
    gross_pnl: float
    total_fees: float
    net_pnl: float
    exit_reason: ExitReason
    opened_at: int
    closed_at: int


@dataclass
class PositionState:
    """Trạng thái vị thế nội bộ được cập nhật sau khi sàn xác nhận khớp lệnh (Fill)."""
    qty_contracts: float = 0.0              # +: Long, -: Short, 0: Flat
    coin_qty: float = 0.0
    entry_price: float = 0.0                # Giá bình quân gia quyền (VWAP)
    entry_timestamp: int = 0
    already_partial_tp: bool = False
    cycle_realized_pnl: float = 0.0         # PnL ròng tích lũy trong chu kỳ (đã trừ phí)
    total_fees_paid: float = 0.0            # Tổng phí đã trả trong chu kỳ
    sl_price: float = 0.0                   # SL tính theo giá Fill thực tế
    tp_price: float = 0.0                   # TP tính theo giá Fill thực tế
    sl_order_id: Optional[str] = None       # ID lệnh Stop Loss trên sàn
    tp_order_id: Optional[str] = None       # ID lệnh Take Profit trên sàn
    protective_status: ProtectiveStatus = ProtectiveStatus.NOT_SENT
    mark_price: float = 0.0                 # Giá thị trường hiện tại (đánh dấu)


class UniversalExecutionModel:
    """Bộ não quản lý vị thế, phân bổ vốn và sizing của Adapter."""

    def __init__(
        self,
        spec: InstrumentSpec,
        capital: float = 10_000.0,
        r_ratio: float = 0.15,
        vl_mult: float = 0.75,
        leverage_config: float = 10.0,
        max_notional_cap_ratio: float = 0.10,   # Mặc định 10% vốn
        max_notional_cap_ac: Optional[float] = None,
        session_cutoff_time: Optional[str] = None,
        auto_fill_simulation: bool = False,
        bot_id: Optional[str] = None,
        mode: str = "paper",
        enforce_risk_gate: bool = False,
        shadow_mode: bool = False,
        max_loss_per_trade_ac: Optional[float] = None,
    ):
        if capital <= 0:
            raise ValueError("capital must be positive")
        if leverage_config <= 0:
            raise ValueError("leverage_config must be positive")
        if r_ratio <= 0:
            raise ValueError("r_ratio must be positive")
        if max_notional_cap_ratio <= 0:
            raise ValueError("max_notional_cap_ratio must be positive")

        self.spec = spec
        self.capital = capital
        self.r_ratio = r_ratio
        self.vl_mult = vl_mult
        self.leverage_config = min(leverage_config, spec.broker_max_leverage)
        self.max_notional_cap_ratio = max_notional_cap_ratio
        self._custom_notional_cap_ac = max_notional_cap_ac
        self.session_cutoff_time = session_cutoff_time
        self.auto_fill_simulation = auto_fill_simulation
        self.bot_id = bot_id or "bot"
        self.mode = mode
        self.enforce_risk_gate = enforce_risk_gate
        self.shadow_mode = shadow_mode
        self.max_loss_per_trade_ac = max_loss_per_trade_ac

        self.pos = PositionState()
        self.pending_order: Optional[PendingOrder] = None
        self.lifecycle_state = BotLifecycleState.RUNNING

        self.closed_cycles: List[TradeCycleResult] = []
        self.last_cycle_result: Optional[TradeCycleResult] = None
        self._order_counter: int = 0
        self.processed_fill_ids: set[str] = set()
        self.emergency_protection_failed: bool = False

    @property
    def max_notional_cap_ac(self) -> float:
        """Hạn mức danh nghĩa tối đa tự động co giãn theo quy mô vốn (Compound-friendly)."""
        if self._custom_notional_cap_ac is not None:
            return self._custom_notional_cap_ac
        return self.capital * self.max_notional_cap_ratio

    @property
    def risk_budget_e(self) -> float:
        """Ngân sách rủi ro chu kỳ: E = Capital * R."""
        return self.capital * self.r_ratio

    @property
    def effective_margin_ratio(self) -> float:
        """Tỷ lệ ký quỹ thực tế: max(1 / leverage, broker_margin_init)."""
        return max(1.0 / self.leverage_config, self.spec.broker_margin_init)

    def set_capital(self, new_capital: float) -> None:
        """Cập nhật vốn tài khoản (phục vụ compounding)."""
        if new_capital > 0:
            self.capital = new_capital

    def _next_order_id(self, action_type: str, ts: int, attempt: int = 0) -> str:
        self._order_counter += 1
        cycle_id = len(self.closed_cycles) + 1
        return generate_client_order_id(
            bot_id=getattr(self, "bot_id", "bot"),
            cycle_id=cycle_id,
            action_type=action_type,
            bar_ts=ts,
            attempt=attempt,
        )

    def _is_session_cutoff(self, ts: int, time_str: Optional[str]) -> bool:
        """Kiểm tra thời điểm cắt phiên linh hoạt cho Crypto hoặc phái sinh truyền thống."""
        if not self.session_cutoff_time or self.session_cutoff_time.lower() in ("none", "off", ""):
            return False

        mode = self.session_cutoff_time.lower().strip()
        if mode == "crypto_weekend":
            # Cuối tuần Crypto: Thứ 6 sau 20:30 UTC đến Thứ 2 00:30 UTC
            import datetime
            dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=datetime.timezone.utc)
            weekday = dt.weekday()  # 4=Thứ 6, 5=Thứ 7, 6=Chủ nhật, 0=Thứ 2
            if weekday == 4 and (dt.hour > 20 or (dt.hour == 20 and dt.minute >= 30)):
                return True
            if weekday in (5, 6):
                return True
            if weekday == 0 and (dt.hour == 0 and dt.minute < 30):
                return True
            return False
        elif mode == "traditional_1420":
            # Phái sinh VN30F hoặc chứng khoán cơ sở: 14:20
            t_check = time_str or ""
            return bool(t_check and t_check >= "14:20")
        else:
            t_check = time_str or ""
            return bool(t_check and t_check >= self.session_cutoff_time)

    def reconcile_order_event(
        self,
        order_id: str,
        event_type: str,
        fill_price: float = 0.0,
        fill_qty: float = 0.0,
        fx_rate_to_ac: float = 1.0,
        ts: int = 0,
    ) -> Optional[TradeCycleResult]:
        """Đối soát trạng thái lệnh từ sàn (Order State Reconciliation) chống double-fills và ghost fills."""
        if not self.pending_order:
            return None

        if self.pending_order.order_id != order_id:
            return None

        evt = event_type.upper()
        if evt == "FILLED":
            self.on_fill(
                fill_px=fill_price or self.pending_order.expected_price,
                fill_qty_contracts=fill_qty or self.pending_order.requested_qty,
                timestamp=ts,
                order_id=order_id,
                action_type=self.pending_order.action_type,
                fill_id=f"fill_{order_id}",
            )
            return self.last_cycle_result
        elif evt == "REJECTED":
            self.on_reject(order_id=order_id, reason="broker_rejection")
            return None
        elif evt == "CANCELLED":
            self.on_cancel(order_id=order_id)
            return None
        return None

    def floor_to_step(self, value: float, step: float) -> float:
        """Làm tròn xuống theo bước nhảy lotSz hoặc tickSz với dung sai chống lỗi float."""
        if step <= 0 or value <= 0:
            return 0.0
        safe_val = round(value + 1e-9, 8)
        d_val = Decimal(str(safe_val))
        d_step = Decimal(str(step))
        floored = (d_val // d_step) * d_step
        return float(floored)

    def ceil_to_step(self, value: float, step: float) -> float:
        """Làm tròn lên theo bước nhảy tickSz."""
        if step <= 0 or value <= 0:
            return 0.0
        d_val = Decimal(str(value))
        d_step = Decimal(str(step))
        quotient = (d_val / d_step).to_integral_value(rounding=ROUND_CEILING)
        return float(quotient * d_step)

    def calculate_sizing(
        self,
        price: float,
        atr: float,
        k_delta: float,
        fx_rate_to_ac: float = 1.0,
    ) -> Tuple[float, float, float, float, float]:
        """Tính toán Sizing 3 cận an toàn từ backtest chuẩn hóa theo contract của sàn."""
        if atr <= 1e-8 or k_delta <= 1e-8 or price <= 1e-8 or fx_rate_to_ac <= 1e-8:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        e = self.risk_budget_e
        cv = self.spec.contract_value
        eff_margin = self.effective_margin_ratio

        c1 = (0.008 * e) / (k_delta * cv * fx_rate_to_ac)
        c2 = (0.008 * e) / (atr * cv * fx_rate_to_ac)
        c3 = (0.5 * e) / (price * cv * fx_rate_to_ac * eff_margin)

        # Cận 4: Ràng buộc rủi ro tối đa tuyệt đối tại mức Stop Loss (1.5 * ATR)
        if self.max_loss_per_trade_ac is not None and self.max_loss_per_trade_ac > 0:
            risk_dist = 1.5 * atr * cv * fx_rate_to_ac
            c4 = (self.max_loss_per_trade_ac / risk_dist) if risk_dist > 1e-8 else c1
            base_contracts = min(c1, c2, c3, c4)
        else:
            base_contracts = min(c1, c2, c3)

        raw_contracts = base_contracts * self.vl_mult
        contracts = self.floor_to_step(raw_contracts, self.spec.lotSz)

        if contracts < self.spec.minSz:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        notional_quote = contracts * cv * price
        notional_ac = notional_quote * fx_rate_to_ac

        if notional_ac > self.max_notional_cap_ac:
            max_contracts_allowed = self.max_notional_cap_ac / (cv * price * fx_rate_to_ac)
            contracts = self.floor_to_step(max_contracts_allowed, self.spec.lotSz)

        if contracts < self.spec.minSz:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        coin_qty = contracts * cv
        notional_quote = contracts * cv * price
        notional_ac = notional_quote * fx_rate_to_ac
        margin_ac = notional_ac * eff_margin

        return contracts, coin_qty, notional_quote, notional_ac, margin_ac

    def calculate_sl_tp(
        self,
        side: str,
        anchor_price: float,
        atr: float,
        tp_target_pct: float = 0.04,
    ) -> Tuple[float, float]:
        """Tính mức giá Stop Loss và Take Profit cụ thể theo hướng làm tròn an toàn (Tick Direction)."""
        tick = self.spec.tickSz

        if side == "BUY":
            raw_sl = anchor_price - (1.5 * atr)
            raw_tp = anchor_price * (1.0 + tp_target_pct)
            sl = self.floor_to_step(raw_sl, tick)
            tp = self.ceil_to_step(raw_tp, tick)
        else:
            raw_sl = anchor_price + (1.5 * atr)
            raw_tp = anchor_price * (1.0 - tp_target_pct)
            sl = self.ceil_to_step(raw_sl, tick)
            tp = self.floor_to_step(raw_tp, tick)

        return sl, tp

    def step(
        self,
        decision: SignalDecision,
        bar: MarketBar,
        fx_rate_to_ac: float = 1.0,
        time_str: Optional[str] = None,
        override_contracts: Optional[float] = None,
    ) -> OrderAction:
        """Thực thi quyết định từ signal.py theo các quy tắc quản trị rủi ro của Adapter."""
        price = bar.close
        high = bar.high
        low = bar.low
        e = self.risk_budget_e
        cv = self.spec.contract_value

        # ─── 0. KIỂM TRA PENDING ORDER & PAUSE_ENTRY ────────────────────
        if self.pending_order is not None:
            # ƯU TIÊN THOÁT BẢO VỆ: Nếu đang treo Limit Partial TP mà thị trường vi phạm SL/Band
            if self.pending_order.action_type == "PARTIAL_CLOSE" and self.pos.qty_contracts != 0:
                is_long = self.pos.qty_contracts > 0
                worst_px = low if is_long else high
                unrealized_gross = (worst_px - self.pos.entry_price) * self.pos.qty_contracts * cv * fx_rate_to_ac
                est_close_notional = abs(self.pos.qty_contracts) * cv * worst_px * fx_rate_to_ac
                cycle_net_pnl = self.pos.cycle_realized_pnl + unrealized_gross - (est_close_notional * (self.spec.taker_fee_rate + self.spec.slippage_rate))

                sl_hit = (cycle_net_pnl / e) < -0.008
                opposite_hit = decision.intent == "OPPOSITE_BAND"

                if sl_hit or opposite_hit or self.emergency_protection_failed:
                    self.pending_order.status = OrderStatus.CANCEL_REQUESTED
                    return OrderAction(
                        action_type="CANCEL",
                        side=self.pending_order.side,
                        qty_contracts=self.pending_order.requested_qty,
                        coin_qty=self.pending_order.requested_qty * cv,
                        expected_price=self.pending_order.expected_price,
                        notional_quote=0.0,
                        notional_account=0.0,
                        margin_account=0.0,
                        order_id=self.pending_order.order_id,
                    )

            if self.lifecycle_state == BotLifecycleState.PAUSE_ENTRY:
                if self.pending_order.action_type == "ENTRY" and self.pending_order.status != OrderStatus.CANCEL_REQUESTED:
                    self.pending_order.status = OrderStatus.CANCEL_REQUESTED
                    return OrderAction(
                        action_type="CANCEL",
                        side=self.pending_order.side,
                        qty_contracts=self.pending_order.requested_qty,
                        coin_qty=self.pending_order.requested_qty * cv,
                        expected_price=self.pending_order.expected_price,
                        notional_quote=0.0,
                        notional_account=0.0,
                        margin_account=0.0,
                        order_id=self.pending_order.order_id,
                    )

            return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0)

        if self.lifecycle_state == BotLifecycleState.PAUSE_ENTRY and self.pos.qty_contracts == 0:
            self.lifecycle_state = BotLifecycleState.STOPPED
            return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0)

        # ─── 0.1 PHÒNG VỆ KHẨN CẤP: Protective Orders bị sàn REJECT ─────
        if self.emergency_protection_failed and self.pos.qty_contracts != 0:
            return self._trigger_close_all(price, ExitReason.CYCLE_SL, fx_rate_to_ac, bar.timestamp)

        # ─── 1. THỰC THI THOÁT LỆNH KHI ĐANG CÓ VỊ THẾ ─────────────────
        if self.pos.qty_contracts != 0:
            pos_contracts = abs(self.pos.qty_contracts)
            is_long = self.pos.qty_contracts > 0

            # Bước 1.1: Emergency Cycle SL (Bảo vệ vốn khẩn cấp)
            worst_px = low if is_long else high
            unrealized_gross = (worst_px - self.pos.entry_price) * self.pos.qty_contracts * cv * fx_rate_to_ac
            est_close_notional = pos_contracts * cv * worst_px * fx_rate_to_ac
            cycle_net_pnl = self.pos.cycle_realized_pnl + unrealized_gross - (est_close_notional * (self.spec.taker_fee_rate + self.spec.slippage_rate))

            if (cycle_net_pnl / e) < -0.008:
                exec_sl_px = self.pos.sl_price if (is_long and worst_px <= self.pos.sl_price) or (not is_long and worst_px >= self.pos.sl_price) else worst_px
                return self._trigger_close_all(exec_sl_px, ExitReason.CYCLE_SL, fx_rate_to_ac, bar.timestamp)

            # Bước 1.2: Session Cutoff (Hỗ trợ crypto weekend cutoff hoặc traditional market cutoff)
            if self._is_session_cutoff(bar.timestamp, time_str):
                return self._trigger_close_all(price, ExitReason.SESSION_CUTOFF, fx_rate_to_ac, bar.timestamp)

            # Bước 1.3: Thực thi quyết định OPPOSITE_BAND từ signal.py
            if decision.intent == "OPPOSITE_BAND":
                return self._trigger_close_all(decision.signal_price, ExitReason.OPPOSITE_BAND, fx_rate_to_ac, bar.timestamp)

            # Bước 1.4: Thực thi quyết định CENTER_EXIT từ signal.py
            if decision.intent == "CENTER_EXIT":
                return self._trigger_close_all(decision.signal_price, ExitReason.CENTER_EXIT, fx_rate_to_ac, bar.timestamp)

            # Bước 1.5: Thực thi quyết định PARTIAL_TP từ signal.py
            if decision.intent == "PARTIAL_TP" and not self.pos.already_partial_tp:
                close_qty = self.spec.lotSz
                remaining_qty = self.floor_to_step(pos_contracts - close_qty, self.spec.lotSz)

                if remaining_qty >= self.spec.minSz:
                    exec_tp_px = decision.signal_price
                    coin_qty = close_qty * cv
                    notional_q = close_qty * cv * exec_tp_px
                    notional_ac = notional_q * fx_rate_to_ac
                    margin_ac = notional_ac * self.effective_margin_ratio
                    fee_ac = notional_ac * self.spec.maker_fee_rate
                    order_id = self._next_order_id("PARTIAL_CLOSE", bar.timestamp)

                    partial_action = OrderAction(
                        action_type="PARTIAL_CLOSE",
                        side=decision.side,
                        qty_contracts=close_qty,
                        coin_qty=coin_qty,
                        expected_price=exec_tp_px,
                        notional_quote=notional_q,
                        notional_account=notional_ac,
                        margin_account=margin_ac,
                        order_type=OrderType.LIMIT,
                        exit_reason=ExitReason.PARTIAL_TP,
                        order_id=order_id,
                        estimated_fee_ac=fee_ac,
                    )

                    self.pending_order = PendingOrder(
                        order_id=order_id,
                        action_type="PARTIAL_CLOSE",
                        side=partial_action.side,
                        requested_qty=close_qty,
                        expected_price=exec_tp_px,
                        created_ts=bar.timestamp,
                        exit_reason=ExitReason.PARTIAL_TP,
                    )

                    if self.auto_fill_simulation:
                        self.on_fill(
                            fill_px=exec_tp_px,
                            fill_qty_contracts=close_qty,
                            fee=fee_ac,
                            liquidity="MAKER",
                            timestamp=bar.timestamp,
                            order_id=order_id,
                        )
                    return partial_action

        # ─── 2. THỰC THI MỞ VỊ THẾ MỚI KHI FLAT ────────────────────────
        elif self.pos.qty_contracts == 0 and self.lifecycle_state == BotLifecycleState.RUNNING:
            if decision.intent == "ENTRY" and decision.signal in ("LONG", "SHORT"):
                if override_contracts is not None and override_contracts > 0:
                    contracts = self.floor_to_step(override_contracts, self.spec.lotSz)
                    coin_qty = contracts * cv
                    notional_q = contracts * cv * price
                    notional_ac = notional_q * fx_rate_to_ac
                    margin_ac = notional_ac * self.effective_margin_ratio
                else:
                    contracts, coin_qty, notional_q, notional_ac, margin_ac = self.calculate_sizing(
                        price, decision.atr, decision.k_delta, fx_rate_to_ac
                    )

                if contracts >= self.spec.minSz:
                    side = decision.side
                    sl, tp = self.calculate_sl_tp(side, price, decision.atr)

                    # ── MASTER PORTFOLIO RISK GATE (admit_order) ──
                    if self.enforce_risk_gate and not self.shadow_mode:
                        try:
                            from backend.core.portfolio import get_live_master_ledger, PortfolioAdmissionController
                            ledger = get_live_master_ledger(self.mode)
                            controller = PortfolioAdmissionController(ledger)
                            s_id = self.bot_id
                            if s_id not in ledger.sleeves and f"sleeve_{s_id}" in ledger.sleeves:
                                s_id = f"sleeve_{s_id}"
                            elif s_id not in ledger.sleeves and s_id.startswith("sleeve_") and s_id[7:] in ledger.sleeves:
                                s_id = s_id[7:]

                            if s_id in ledger.sleeves:
                                admitted, reason = controller.admit_order(
                                    sleeve_id=s_id,
                                    side=side,
                                    requested_qty=contracts,
                                    price=price,
                                    contract_value=cv,
                                    margin_rate=self.effective_margin_ratio,
                                    sl_price=sl,
                                    is_reduce_only=False,
                                )
                                if not admitted:
                                    return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0, reason=f"ADMISSION_DENIED: {reason}")
                            else:
                                # Sleeve không tồn tại trong Master Fund -> Từ chối mở vị thế để bảo vệ vốn
                                return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0, reason=f"SLEEVE_NOT_FOUND_IN_MASTER: {s_id}")
                        except Exception as e:
                            # Lỗi kiểm tra rủi ro -> Fail-closed: Từ chối mở vị thế
                            return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0, reason=f"RISK_GATE_ERROR: {e}")

                    fee_ac = notional_ac * self.spec.taker_fee_rate
                    order_id = self._next_order_id("ENTRY", bar.timestamp)

                    entry_action = OrderAction(
                        action_type="ENTRY",
                        side=side,
                        qty_contracts=contracts,
                        coin_qty=coin_qty,
                        expected_price=price,
                        notional_quote=notional_q,
                        notional_account=notional_ac,
                        margin_account=margin_ac,
                        order_type=OrderType.MARKET,
                        sl_price=sl,
                        tp_price=tp,
                        exit_reason=ExitReason.NONE,
                        order_id=order_id,
                        estimated_fee_ac=fee_ac,
                    )

                    self.pending_order = PendingOrder(
                        order_id=order_id,
                        action_type="ENTRY",
                        side=side,
                        requested_qty=contracts,
                        expected_price=price,
                        created_ts=bar.timestamp,
                        sl_price=sl,
                        tp_price=tp,
                    )

                    if self.auto_fill_simulation:
                        # BUY chịu trượt giá bất lợi (+), SELL chịu trượt giá bất lợi (-)
                        slip_mult = (1.0 + self.spec.slippage_rate) if side == "BUY" else (1.0 - self.spec.slippage_rate)
                        sim_fill_px = price * slip_mult
                        sim_fee = contracts * cv * sim_fill_px * fx_rate_to_ac * self.spec.taker_fee_rate
                        self.on_fill(
                            fill_px=sim_fill_px,
                            fill_qty_contracts=contracts,
                            fee=sim_fee,
                            liquidity="TAKER",
                            timestamp=bar.timestamp,
                            atr=decision.atr,
                            order_id=order_id,
                        )

                    return entry_action

        return OrderAction("HOLD", "HOLD", 0.0, 0.0, price, 0.0, 0.0, 0.0)

    def _trigger_close_all(
        self,
        exec_price: float,
        reason: ExitReason,
        fx_rate: float,
        timestamp: int,
    ) -> OrderAction:
        is_long = self.pos.qty_contracts > 0
        close_contracts = abs(self.pos.qty_contracts)
        cv = self.spec.contract_value
        coin_qty = close_contracts * cv
        notional_q = close_contracts * cv * exec_price
        notional_ac = notional_q * fx_rate
        margin_ac = notional_ac * self.effective_margin_ratio
        fee_ac = notional_ac * self.spec.taker_fee_rate
        order_id = self._next_order_id("CLOSE_ALL", timestamp)

        action = OrderAction(
            action_type="CLOSE_ALL",
            side="SELL" if is_long else "BUY",
            qty_contracts=close_contracts,
            coin_qty=coin_qty,
            expected_price=exec_price,
            notional_quote=notional_q,
            notional_account=notional_ac,
            margin_account=margin_ac,
            order_type=OrderType.MARKET,
            exit_reason=reason,
            order_id=order_id,
            estimated_fee_ac=fee_ac,
        )

        self.pending_order = PendingOrder(
            order_id=order_id,
            action_type="CLOSE_ALL",
            side=action.side,
            requested_qty=close_contracts,
            expected_price=exec_price,
            created_ts=timestamp,
            exit_reason=reason,
        )

        if self.auto_fill_simulation:
            # Long đóng (bán) chịu trượt giá giảm (-), Short đóng (mua) chịu trượt giá tăng (+)
            slip_mult = (1.0 - self.spec.slippage_rate) if is_long else (1.0 + self.spec.slippage_rate)
            sim_fill_px = exec_price * slip_mult
            sim_fee = close_contracts * cv * sim_fill_px * fx_rate * self.spec.taker_fee_rate
            self.on_fill(
                fill_px=sim_fill_px,
                fill_qty_contracts=close_contracts,
                fee=sim_fee,
                liquidity="TAKER",
                timestamp=timestamp,
                order_id=order_id,
            )

        return action

    def force_close_all(
        self,
        price: Optional[float] = None,
        reason: ExitReason = ExitReason.SESSION_CUTOFF,
        fx_rate: float = 1.0,
        timestamp: Optional[int] = None,
    ) -> Optional[OrderAction]:
        """Đóng khẩn cấp toàn bộ vị thế khi người dùng dừng bot."""
        if self.pos.qty_contracts == 0:
            return None
        px = price or self.pos.entry_price or 1.0
        ts = timestamp or int(time.time() * 1000)
        return self._trigger_close_all(px, reason, fx_rate, ts)

    def on_fill(
        self,
        fill_px: float,
        fill_qty_contracts: float,
        fee: float = 0.0,
        liquidity: str = "TAKER",
        timestamp: int = 0,
        atr: Optional[float] = None,
        order_id: Optional[str] = None,
        action_type: Optional[str] = None,
        fill_id: Optional[str] = None,
    ) -> None:
        """Xác nhận khớp lệnh thực tế từ sàn (Fill Confirmation)."""
        if fill_id:
            if fill_id in self.processed_fill_ids:
                return
            self.processed_fill_ids.add(fill_id)

        cv = self.spec.contract_value
        pending = self.pending_order

        if order_id and pending and pending.order_id != order_id:
            return

        act_type = pending.action_type if pending else (action_type or "ENTRY")

        if pending:
            rem_needed = max(0.0, pending.requested_qty - pending.filled_qty)
            if fill_qty_contracts > rem_needed + 1e-9:
                fill_qty_contracts = rem_needed

        if fill_qty_contracts <= 1e-9:
            return

        if act_type == "ENTRY":
            side = pending.side if pending else ("BUY" if fill_qty_contracts > 0 else "SELL")
            is_buy = side == "BUY"

            old_qty = abs(self.pos.qty_contracts)
            new_qty = old_qty + fill_qty_contracts

            if old_qty > 0 and self.pos.entry_price > 0:
                avg_px = (self.pos.entry_price * old_qty + fill_px * fill_qty_contracts) / new_qty
            else:
                avg_px = fill_px

            self.pos.qty_contracts = new_qty if is_buy else -new_qty
            self.pos.coin_qty = new_qty * cv if is_buy else -new_qty * cv
            self.pos.entry_price = avg_px
            if self.pos.entry_timestamp == 0:
                self.pos.entry_timestamp = timestamp
            self.pos.already_partial_tp = False
            self.pos.total_fees_paid += fee
            self.pos.cycle_realized_pnl = -self.pos.total_fees_paid

            target_atr = atr or (abs(avg_px - pending.sl_price) / 1.5 if pending and pending.sl_price else avg_px * 0.01)
            sl, tp = self.calculate_sl_tp(side, avg_px, target_atr)
            self.pos.sl_price = sl
            self.pos.tp_price = tp
            self.pos.protective_status = ProtectiveStatus.PENDING_ACK

            if pending:
                pending.filled_qty += fill_qty_contracts
                pending.cumulative_cost += fill_qty_contracts * fill_px
                if pending.filled_qty >= pending.requested_qty - 1e-9:
                    pending.status = OrderStatus.FILLED
                    self.pending_order = None
                else:
                    pending.status = OrderStatus.PARTIALLY_FILLED

        elif act_type == "PARTIAL_CLOSE":
            is_long = self.pos.qty_contracts > 0
            gross_gain = (fill_px - self.pos.entry_price) * (fill_qty_contracts if is_long else -fill_qty_contracts) * cv
            self.pos.cycle_realized_pnl += (gross_gain - fee)
            self.pos.total_fees_paid += fee

            new_qty = self.pos.qty_contracts - (fill_qty_contracts if is_long else -fill_qty_contracts)
            self.pos.qty_contracts = round(new_qty, 6)
            self.pos.coin_qty = round(self.pos.qty_contracts * cv, 6)

            if pending:
                pending.filled_qty += fill_qty_contracts
                if pending.filled_qty >= pending.requested_qty - 1e-9:
                    pending.status = OrderStatus.FILLED
                    self.pos.already_partial_tp = True
                    self.pending_order = None
                else:
                    pending.status = OrderStatus.PARTIALLY_FILLED
            else:
                self.pos.already_partial_tp = True

        elif act_type == "CLOSE_ALL":
            is_long = self.pos.qty_contracts > 0
            gross_gain = (fill_px - self.pos.entry_price) * (fill_qty_contracts if is_long else -fill_qty_contracts) * cv
            self.pos.cycle_realized_pnl += (gross_gain - fee)
            self.pos.total_fees_paid += fee

            current_abs = abs(self.pos.qty_contracts)
            rem_qty = max(0.0, round(current_abs - fill_qty_contracts, 6))
            self.pos.qty_contracts = rem_qty if is_long else -rem_qty
            self.pos.coin_qty = round(self.pos.qty_contracts * cv, 6)

            if pending:
                pending.filled_qty += fill_qty_contracts
                pending.cumulative_cost += fill_qty_contracts * fill_px

            if rem_qty <= 1e-9 or (pending and pending.filled_qty >= pending.requested_qty - 1e-9):
                if pending:
                    pending.status = OrderStatus.FILLED
                total_net_pnl = self.pos.cycle_realized_pnl
                exit_reason = pending.exit_reason if pending else ExitReason.NONE

                cycle_result = TradeCycleResult(
                    symbol=self.spec.symbol,
                    side="BUY" if is_long else "SELL",
                    entry_price=self.pos.entry_price,
                    exit_price=fill_px,
                    qty_contracts=abs(pending.requested_qty) if pending else fill_qty_contracts,
                    gross_pnl=total_net_pnl + self.pos.total_fees_paid,
                    total_fees=self.pos.total_fees_paid,
                    net_pnl=total_net_pnl,
                    exit_reason=exit_reason,
                    opened_at=self.pos.entry_timestamp,
                    closed_at=timestamp,
                )
                self.closed_cycles.append(cycle_result)
                self.last_cycle_result = cycle_result

                self.pos.qty_contracts = 0.0
                self.pos.coin_qty = 0.0
                self.pos.entry_price = 0.0
                self.pos.entry_timestamp = 0
                self.pos.sl_price = 0.0
                self.pos.tp_price = 0.0
                self.pos.sl_order_id = None
                self.pos.tp_order_id = None
                self.pos.protective_status = ProtectiveStatus.NOT_SENT
                self.pos.already_partial_tp = False
                self.pos.cycle_realized_pnl = 0.0
                self.pos.total_fees_paid = 0.0
                self.emergency_protection_failed = False
                self.pending_order = None

                if self.lifecycle_state == BotLifecycleState.PAUSE_ENTRY:
                    self.lifecycle_state = BotLifecycleState.STOPPED
            else:
                if pending:
                    pending.status = OrderStatus.PARTIALLY_FILLED

    def on_reject(self, order_id: Optional[str] = None, reason: str = "") -> None:
        if self.pending_order:
            if order_id is None or self.pending_order.order_id == order_id:
                self.pending_order.status = OrderStatus.REJECTED
                self.pending_order = None

    def on_cancel(self, order_id: Optional[str] = None) -> None:
        if self.pending_order:
            if order_id is None or self.pending_order.order_id == order_id:
                self.pending_order.status = OrderStatus.CANCELLED
                self.pending_order = None

        if self.lifecycle_state == BotLifecycleState.PAUSE_ENTRY and self.pos.qty_contracts == 0:
            self.lifecycle_state = BotLifecycleState.STOPPED

    def on_protective_ack(self, sl_order_id: str, tp_order_id: str) -> None:
        self.pos.sl_order_id = sl_order_id
        self.pos.tp_order_id = tp_order_id
        self.pos.protective_status = ProtectiveStatus.ACTIVE
        self.emergency_protection_failed = False

    def on_protective_reject(self, reason: str = "") -> None:
        self.pos.protective_status = ProtectiveStatus.REJECTED
        self.emergency_protection_failed = True


# ════════════════════════════════════════════════════════════════════════════
# UNIVERSAL SPECS CATALOG (Đa Tài Sản: Crypto SWAP, CFS Vàng, Forex, Index)
# ════════════════════════════════════════════════════════════════════════════

SPEC_CATALOG: Dict[str, InstrumentSpec] = {
    # ─── CRYPTO PERPETUAL SWAP ──────────────────────────────────────────────
    "BTC-USDT-SWAP": InstrumentSpec(
        symbol="BTC-USDT-SWAP",
        ctVal=0.01,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.1,
        multiplier=1.0,
        quote_currency="USDT",
        account_currency="USDT",
        broker_margin_init=0.02,
        broker_max_leverage=100.0,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0005,
        slippage_rate=0.0002,
    ),
    "ETH-USDT-SWAP": InstrumentSpec(
        symbol="ETH-USDT-SWAP",
        ctVal=0.10,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.01,
        multiplier=1.0,
        quote_currency="USDT",
        account_currency="USDT",
        broker_margin_init=0.02,
        broker_max_leverage=100.0,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0005,
        slippage_rate=0.0002,
    ),
    "SOL-USDT-SWAP": InstrumentSpec(
        symbol="SOL-USDT-SWAP",
        ctVal=1.00,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.01,
        multiplier=1.0,
        quote_currency="USDT",
        account_currency="USDT",
        broker_margin_init=0.03,
        broker_max_leverage=50.0,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0005,
        slippage_rate=0.0003,
    ),

    # ─── COMMODITIES & FOREX CFS / CFD ──────────────────────────────────────
    "XAUUSD": InstrumentSpec(
        symbol="XAUUSD",
        ctVal=1.0,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.01,
        multiplier=100.0,             # 1 standard lot = 100 troy ounces
        quote_currency="USD",
        account_currency="USD",
        broker_margin_init=0.01,       # Đòn bẩy 1:100
        broker_max_leverage=100.0,
        maker_fee_rate=0.0001,
        taker_fee_rate=0.0002,
        slippage_rate=0.0001,
    ),
    "EURUSD": InstrumentSpec(
        symbol="EURUSD",
        ctVal=1.0,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.00001,               # 0.1 pip
        multiplier=100_000.0,         # 1 standard lot = 100.000 EUR
        quote_currency="USD",
        account_currency="USD",
        broker_margin_init=0.02,       # Đòn bẩy 1:50
        broker_max_leverage=50.0,
        maker_fee_rate=0.00005,
        taker_fee_rate=0.0001,
        slippage_rate=0.00005,
    ),

    # ─── STOCK INDICES & FUTURES ─────────────────────────────────────────────
    "SPX500": InstrumentSpec(
        symbol="SPX500",
        ctVal=1.0,
        lotSz=0.1,
        minSz=0.1,
        tickSz=0.1,
        multiplier=1.0,
        quote_currency="USD",
        account_currency="USD",
        broker_margin_init=0.05,       # Đòn bẩy 1:20
        broker_max_leverage=20.0,
        maker_fee_rate=0.0001,
        taker_fee_rate=0.0002,
        slippage_rate=0.0002,
    ),
    "US30": InstrumentSpec(
        symbol="US30",
        ctVal=1.0,
        lotSz=0.1,
        minSz=0.1,
        tickSz=1.0,
        multiplier=1.0,
        quote_currency="USD",
        account_currency="USD",
        broker_margin_init=0.05,       # Đòn bẩy 1:20
        broker_max_leverage=20.0,
        maker_fee_rate=0.0001,
        taker_fee_rate=0.0002,
        slippage_rate=0.0002,
    ),
    "VN30F": InstrumentSpec(
        symbol="VN30F",
        ctVal=1.0,
        lotSz=1.0,
        minSz=1.0,
        tickSz=0.1,
        multiplier=100_000.0,         # 1 điểm = 100.000 VNĐ
        quote_currency="VND",
        account_currency="VND",
        broker_margin_init=0.17,       # Tỷ lệ ký quỹ 17% chuẩn VSD
        broker_max_leverage=5.88,
        maker_fee_rate=0.000175,
        taker_fee_rate=0.000175,
        slippage_rate=0.0001,
    ),
}


def get_universal_spec(symbol: str) -> InstrumentSpec:
    """Truy xuất InstrumentSpec chuẩn hóa cho bất kỳ tài sản nào (Coin, CFD, CFS, Futures).
    
    Hỗ trợ alias: 'BTC@perp', 'BTC', 'BTC-USDT-SWAP', 'XAUUSD', 'GOLD', 'VN30F'.
    """
    sym = symbol.strip().upper()
    if sym in ("BTC", "BTC@PERP", "BTC/USDT", "BTC-USDT"):
        sym = "BTC-USDT-SWAP"
    elif sym in ("ETH", "ETH@PERP", "ETH/USDT", "ETH-USDT"):
        sym = "ETH-USDT-SWAP"
    elif sym in ("SOL", "SOL@PERP", "SOL/USDT", "SOL-USDT"):
        sym = "SOL-USDT-SWAP"
    elif sym in ("GOLD", "XAU", "XAU/USD"):
        sym = "XAUUSD"
    elif sym in ("EUR/USD", "EUR"):
        sym = "EURUSD"
    elif sym in ("SP500", "US500", "S&P500"):
        sym = "SPX500"
    elif sym in ("DOW", "DOWJONES", "DJ30"):
        sym = "US30"
    elif sym in ("VN30", "VN30F1M"):
        sym = "VN30F"

    if sym in SPEC_CATALOG:
        return SPEC_CATALOG[sym]

    # Fallback tự động nếu chưa có trong catalog: Giả định Coin Swap chuẩn
    return InstrumentSpec(
        symbol=symbol,
        ctVal=1.0,
        lotSz=0.01,
        minSz=0.01,
        tickSz=0.01,
        multiplier=1.0,
        quote_currency="USDT",
        account_currency="USDT",
        broker_margin_init=0.05,
        broker_max_leverage=20.0,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0005,
        slippage_rate=0.0002,
    )


def sync_okx_specs(symbol: str, timeout: float = 3.0) -> InstrumentSpec:
    """Đồng bộ và kiểm chứng quy cách hợp đồng trực tiếp từ API sàn OKX Live (ctVal, lotSz, minSz, tickSz, lever).
    Nếu không có mạng hoặc lỗi -> tự động fallback về SPEC_CATALOG chuẩn.
    """
    sym = symbol.strip().upper()
    if sym in ("BTC", "BTC@PERP", "BTC/USDT", "BTC-USDT"):
        sym = "BTC-USDT-SWAP"
    elif sym in ("ETH", "ETH@PERP", "ETH/USDT", "ETH-USDT"):
        sym = "ETH-USDT-SWAP"
    elif sym in ("SOL", "SOL@PERP", "SOL/USDT", "SOL-USDT"):
        sym = "SOL-USDT-SWAP"

    if "SWAP" in sym or sym.endswith("-USDT"):
        try:
            import json
            import urllib.request
            url = f"https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId={sym}"
            req = urllib.request.Request(url, headers={"User-Agent": "NoraAdapter/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") == "0" and data.get("data"):
                    inst = data["data"][0]
                    ct_val = float(inst.get("ctVal") or 1.0)
                    lot_sz = float(inst.get("lotSz") or 0.01)
                    min_sz = float(inst.get("minSz") or 0.01)
                    tick_sz = float(inst.get("tickSz") or 0.01)
                    max_lev = float(inst.get("lever") or 100.0)
                    margin_init = 1.0 / max_lev if max_lev > 0 else 0.02

                    spec = InstrumentSpec(
                        symbol=sym,
                        ctVal=ct_val,
                        lotSz=lot_sz,
                        minSz=min_sz,
                        tickSz=tick_sz,
                        multiplier=1.0,
                        quote_currency="USDT",
                        account_currency="USDT",
                        broker_margin_init=margin_init,
                        broker_max_leverage=max_lev,
                        maker_fee_rate=0.0002,
                        taker_fee_rate=0.0005,
                        slippage_rate=0.0002,
                    )
                    SPEC_CATALOG[sym] = spec
                    return spec
        except Exception:
            pass

    return get_universal_spec(symbol)


def generate_client_order_id(
    bot_id: str,
    cycle_id: int,
    action_type: str,
    bar_ts: int,
    attempt: int = 0,
) -> str:
    """Sinh mã định danh lệnh logic bất biến (Idempotent Logical clOrdId).

    Quy tắc chuẩn: logical_order_id phụ thuộc duy nhất vào (bot, cycle, action, bar_ts).
    Attempt / retry không được làm thay đổi logical identity để đảm bảo nếu sàn đã nhận
    lệnh thành công nhưng bị timeout phản hồi, việc gửi lại lệnh có cùng clOrdId sẽ được
    sàn nhận diện và ngăn chặn hành vi double fill.
    """
    clean_bot = bot_id.replace("-", "_")[-8:]
    clean_act = action_type[:4].upper()
    ts_short = bar_ts % 10_000_000
    # clOrdId chuẩn <= 32 ký tự, bất biến theo lệnh logic
    return f"N_{clean_bot}_{cycle_id}_{clean_act}_{ts_short}"[:32]


def determine_execution_td_mode(
    account_config: Optional[Dict[str, Any]] = None,
    instrument_type: str = "SWAP",
) -> Tuple[str, str]:
    """Xác định cờ ký quỹ tdMode và hướng vị thế posSide theo metadata tài khoản OKX thực tế.

    Tránh hardcode giả định:
    - Nếu tài khoản ở 'net_mode' -> posSide='net'.
    - Nếu tài khoản ở 'long_short_mode' -> posSide='long'/'short'.
    - tdMode ưu tiên 'isolated' cho SWAP/FUTURES để cô lập rủi ro, bảo vệ Master Reserve.
    """
    pos_mode = (account_config or {}).get("posMode", "net_mode")
    pos_side = "net" if pos_mode == "net_mode" else "long"
    td_mode = "isolated" if instrument_type in ("SWAP", "FUTURES", "MARGIN") else "cash"
    return td_mode, pos_side


