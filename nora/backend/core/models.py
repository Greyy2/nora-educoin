"""Mô hình + sự kiện + kế toán của engine (P9.4): lệnh/vị thế (OrderModel, PositionModel), sự kiện (Fill, FundingApplied, ...), Account/PositionBook, CapitalLedger.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.4).
"""
import itertools
import os
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Dict, Optional, List, Protocol, Union

_cand = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.basename(_cand) == "test":
    _cand = os.path.abspath(os.path.join(_cand, ".."))
NORA_DIR = _cand
DATA_DIR = os.path.join(NORA_DIR, "data")   # cây dữ liệu mặc định (crawl/store, alpha/compile)

# Bộ đếm id toàn cục (lệnh / vị thế), tăng dần và không trùng (int(time.time()*1000) trùng khi nhiều lệnh mở trong cùng 1 ms).
# Bắt đầu từ epoch-ms * 1000 để vẫn sắp xếp theo thời gian. Kernel, tracker và sim venue cùng rút từ MỘT dãy này.
_ID_SEQ = itertools.count(int(time.time() * 1000) * 1000)


def next_id() -> int:
    return next(_ID_SEQ)


# ══════════════════════════════════════════════════════════════════════════
# Mô hình vị thế / lệnh của engine (dataclass + enum loại vị thế, loại lệnh, trạng thái).
# ══════════════════════════════════════════════════════════════════════════

class PositionType(IntEnum):
    """Loại vị thế."""
    LONG = 1
    SHORT = 2


class OrderType(IntEnum):
    """Hành động lệnh."""
    BUY = 1
    SELL = 2


class PositionStatus(IntEnum):
    """Trạng thái vị thế."""
    INIT = 0
    OPEN = 1
    TP = 2      # Chốt lãi (Take Profit)
    SL = 3      # Cắt lỗ (Stop Loss / Stop Trend)
    CANCEL = 4  # Huỷ lệnh
    LIQ = 5     # Bị thanh lý (perp, đòn bẩy)
    WAIT = 6    # Đang chờ / Đang mở


@dataclass
class PositionModel:
    """Mô hình vị thế giao dịch (lab_results)."""
    result_id: int = 0
    account_id: int = 0
    campaign_id: int = 0
    symbol: str = ""
    pos_type: PositionType = PositionType.LONG
    phase: int = 0
    enter_time: int = 0       # ms
    enter_price: float = 0.0
    close_time: Optional[int] = None  # ms
    close_price: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    real_pnl: float = 0.0
    profit_pct: float = 0.0
    flow: str = ""
    start_reason: str = ""
    close_reason: str = ""
    max_price: float = 0.0
    min_price: float = 0.0
    qty: float = 0.0
    entry_equity: float = 0.0
    entry_margin_usd: float = 0.0
    entry_notional_usd: float = 0.0
    entry_fee_usd: float = 0.0
    exit_fee_usd: float = 0.0
    layers: int = 1                 # số lần vào lệnh (1 = không DCA)
    avg_price: float = 0.0          # giá trung bình sau các tầng DCA
    total_margin_usd: float = 0.0   # tổng ký quỹ đã dùng
    mae_pct: float = 0.0            # lỗ treo tối đa trong lệnh (% vốn ban đầu, số âm)
    fees_usd: float = 0.0           # tổng phí mọi tầng + thoát
    funding_usd: float = 0.0        # funding đã trả (+) / nhận (−) trong lệnh (perp)
    unit_pct: float = 0.0           # exit_unit="atr": ATR% lúc vào lệnh (SL/TP/trailing = bội số của nó)
    leverage_used: float = 1.0      # đòn bẩy thực dùng cho vị thế (có thể < tham số để thanh lý xa SL)
    risk_usd: float = 0.0           # sizing="risk": số tiền dự kiến mất nếu chạm SL
    strategy_id: str = ""           # backtest danh mục: id chiến lược sinh ra vị thế

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "PositionModel":
        raw_type = row.get("lab_result_type", 1)
        raw_status = row.get("lab_result_status", 1)
        return cls(
            result_id=row.get("lab_result_id") or 0,
            account_id=row.get("lab_result_account") or 0,
            campaign_id=row.get("lab_result_campaign") or 0,
            symbol=row.get("lab_result_symbol") or "",
            pos_type=PositionType(raw_type) if raw_type in (1, 2) else PositionType.LONG,
            phase=int(row.get("lab_result_phase") or 0),
            enter_time=int(row.get("lab_result_chart") or row.get("lab_result_enter_time") or 0),
            enter_price=float(row.get("lab_result_chart_price") or row.get("lab_result_enter_price") or 0.0),
            close_time=int(row.get("lab_result_close_time")) if row.get("lab_result_close_time") else None,
            close_price=float(row.get("lab_result_sell_price")) if row.get("lab_result_sell_price") else None,
            status=PositionStatus(raw_status) if raw_status in [0, 1, 2, 3, 4, 5, 6] else PositionStatus.OPEN,
            real_pnl=float(row.get("lab_result_realpnl") or row.get("lab_result_profit") or 0.0),
            profit_pct=float(row.get("lab_result_realprofit") or row.get("lab_result_eventprofit") or 0.0),
            flow=row.get("lab_result_flow") or "",
            start_reason=row.get("lab_result_start_reason") or "",
            close_reason=row.get("lab_result_close_reason") or "",
            max_price=float(row.get("lab_result_max_price") or 0.0),
            min_price=float(row.get("lab_result_min_price") or 0.0),
        )


@dataclass
class OrderModel:
    """Mô hình lệnh khớp chi tiết (lab_order)."""
    order_id: int = 0
    account_id: int = 0
    position_id: int = 0      # lab_order_action
    order_time: int = 0       # ms
    order_type: OrderType = OrderType.BUY
    order_price: float = 0.0
    qty: float = 0.0
    phase: int = 0
    fee_usd: float = 0.0          # phí của riêng lệnh này
    liquidity: str = ""           # "maker" (limit) | "taker" (market) | "liquidation"
    slippage: float = 0.0         # tỉ lệ trượt giá đã áp lên giá khớp (lệnh taker; không gồm phí)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "OrderModel":
        raw_type = row.get("lab_order_type", 1)
        return cls(
            order_id=row.get("lab_order_id") or 0,
            account_id=row.get("lab_order_account") or 0,
            position_id=row.get("lab_order_action") or 0,
            order_time=int(row.get("lab_order_time") or 0),
            order_type=OrderType(raw_type) if raw_type in (1, 2) else OrderType.BUY,
            order_price=float(row.get("lab_order_price") or 0.0),
            qty=float(row.get("lab_order_qty") or 0.0),
            phase=int(row.get("lab_order_phase") or 0),
        )


# ══════════════════════════════════════════════════════════════════════════
# Sự kiện thực thi (P6.3): nguồn thay đổi DUY NHẤT của sổ vốn (Account) và vị thế (PositionBook).
#
# Mỗi sự kiện là dữ liệu bất biến; phát lại cùng chuỗi sự kiện vào Account + PositionBook mới cho đúng từng bit
# vốn, ký quỹ giữ chỗ và PositionModel/OrderModel của lần chạy gốc (test/test_account_replay.py).
# Đặc tả: docs/bmad/p6_execution_design.md §2.
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Fill:
    """Một lệnh khớp. kind: "entry" | "dca" (mở/nhồi tầng) hoặc "sl" | "trail" | "tp" | "exit" | "timeout" | "liq" | "kill" | "end" (đóng hết)."""
    slot: int            # chỉ số slot (symbol × chiến lược) trong runner
    order_id: int
    kind: str
    t: int               # open_time của nến (ms)
    price: float         # giá khớp cuối cùng (đã gồm trượt giá với lệnh taker)
    raw_price: float     # giá trước trượt (để tái hiện thứ tự phép toán)
    notional: float      # entry/dca: margin × leverage (qty = notional / price); lệnh đóng: 0 (đóng hết)
    margin: float        # entry/dca: ký quỹ; lệnh đóng: 0
    fee: float
    slip: float
    liquidity: str       # "maker" | "taker" | "liquidation"
    # ── bổ sung ngoài đặc tả §2 (đều có mặc định): thông tin do manager/policy quyết định, book chỉ ghi lại ──
    reason: str = ""             # start_reason (entry) / close_reason (lệnh đóng)
    status: int = 0              # PositionStatus của lệnh đóng (sl/trail/tp không suy ra được chỉ từ kind)
    mae_usd: float = 0.0         # lệnh đóng: lỗ treo tối đa của vị thế (manager theo dõi)
    unit_pct: float = 0.0        # entry: ATR% lúc vào lệnh
    leverage_used: float = 1.0   # entry: đòn bẩy thực dùng
    risk_usd: float = 0.0        # entry: rủi ro dự kiến tới SL


@dataclass(frozen=True)
class FundingApplied:
    slot: int
    t: int
    rate: float
    price: float
    payment: float       # (+) trả, (−) nhận


@dataclass(frozen=True)
class OrderRejected:
    """Lệnh bị từ chối. reason: "budget" (vượt ngân sách vị thế — không đổi sổ vốn), "capital" (không giữ chỗ được
    từ vốn trống) hoặc "no_margin" (khối lượng <= 0 / không còn vốn) — hai loại sau cộng Account.rejected."""
    slot: int
    order_id: int
    kind: str
    reason: str


@dataclass(frozen=True)
class PositionMarked:
    """Nến mới của vị thế đang mở: cập nhật đỉnh/đáy (max_price/min_price) của PositionModel."""
    slot: int
    high: float
    low: float


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — chuyển từ core/execute/policy.py (pnl_move, gross_pnl, unrealized_pnl): Account/PositionBook cần chúng, mà models đứng TRƯỚC position_size
# trong thứ tự core (models ← params ← indicator ← signal ← position_size ← backtest). position_size import lại đúng các hàm này từ đây (cùng đối tượng).
# ══════════════════════════════════════════════════════════════════════════

def pnl_move(price: float, avg: float, is_long: bool) -> float:
    """Lãi/lỗ trên một đơn vị: long price−avg, short avg−price."""
    return (price - avg) if is_long else (avg - price)


def gross_pnl(qty: float, avg: float, price: float, is_long: bool) -> float:
    return qty * pnl_move(price, avg, is_long)


def unrealized_pnl(qty: float, avg: float, price: float, fees_paid: float, is_long: bool) -> float:
    """PnL chưa chốt sau phí đã trả (funding đã nằm trong ledger)."""
    return qty * pnl_move(price, avg, is_long) - fees_paid


# ══════════════════════════════════════════════════════════════════════════
# Kế toán thực thi (P6.3): Account (sổ vốn chung) + PositionBook (kế toán một slot).
#
# Hai lớp này là nơi DUY NHẤT thay đổi vốn và vị thế; chỉ thay đổi qua sự kiện (events.py) nên phát lại chuỗi
# sự kiện vào đối tượng mới cho đúng từng bit. Mọi biểu thức giữ nguyên thứ tự phép toán float của tracker cũ
# (sao chép nguyên văn / qua policy.py). Kiểm tra trước giao dịch (`can_add`, `can_reserve`) gọi TRƯỚC khi
# chấp nhận Fill; bị từ chối thì ghi OrderRejected (`PositionBook.reject`).
# ══════════════════════════════════════════════════════════════════════════

Event = Union[Fill, FundingApplied, OrderRejected, PositionMarked]


class Account:
    """Sổ vốn chung của một lần chạy — nguồn sự thật duy nhất cho phân bổ vốn.

    equity   : vốn đã chốt (vốn đầu + Σ lãi/lỗ đã đóng + funding đã trả/nhận).
    reserved : tiền đang bị khoá trong các vị thế mở (ký quỹ + phí vào lệnh đã trả).
    free     : equity × usage − reserved. Mọi lệnh vào / tầng DCA phải giữ chỗ được từ free,
               nên nhiều flow cùng lúc KHÔNG thể dùng quá vốn (lỗi cũ: mỗi flow tự dùng 100%).
    (Trước P6.3 tên là CapitalLedger — vẫn import được từ backend.core.models.)
    """

    def __init__(self, capital: float, usage: float = 1.0):
        self.initial = float(capital)
        self.equity = float(capital)
        self.reserved = 0.0
        self.usage = max(0.0, min(float(usage), 1.0))
        self.rejected = 0  # số lần vào lệnh/tầng bị từ chối vì không đủ vốn
        self.peak = float(capital)   # đỉnh vốn ĐÃ CHỐT (cho giảm rủi ro theo mức sụt — dd_throttle_pct)

    def free(self) -> float:
        return self.equity * self.usage - self.reserved

    def can_reserve(self, amount: float) -> bool:
        """Kiểm tra thuần (không đổi sổ): có giữ chỗ được `amount` từ vốn trống không."""
        return not (amount <= 0 or amount > self.free() + 1e-9)

    def reserve(self, amount: float) -> bool:
        if amount <= 0 or amount > self.free() + 1e-9:
            self.rejected += 1
            return False
        self.reserved += amount
        return True

    def release(self, amount: float) -> None:
        self.reserved = max(0.0, self.reserved - amount)

    def settle(self, cash_delta: float) -> None:
        self.equity += cash_delta
        if self.equity > self.peak:
            self.peak = self.equity

    def close_trade(self, reserved: float, trade_cash: float) -> None:
        """Quyết toán đóng vị thế: nhả phần giữ chỗ rồi ghi lãi/lỗ giao dịch sau phí (funding đã vào sổ từ trước)."""
        self.release(reserved)
        self.settle(trade_cash)

    def apply(self, ev: Event) -> None:
        """Phần SỔ VỐN của một sự kiện (phần vị thế do PositionBook xử lý; đóng vị thế qua close_trade vì cần tiền lãi/lỗ)."""
        if isinstance(ev, Fill):
            if ev.kind in ("entry", "dca"):
                self.reserved += ev.margin + ev.fee        # đã qua can_reserve nên giữ chỗ chắc chắn được
        elif isinstance(ev, FundingApplied):
            self.settle(-ev.payment)
        elif isinstance(ev, OrderRejected):
            if ev.reason in ("capital", "no_margin"):
                self.rejected += 1


class PositionBook:
    """Kế toán một slot: qty, avg, ký quỹ, phí, tầng, PositionModel/OrderModel. Đổi trạng thái chỉ qua apply_* / apply(event)."""

    def __init__(self, account: Account, account_id: int, campaign_id: int, symbol: str, flow_name: str,
                 pos_type: PositionType, slot: int = 0, events: Optional[List[Event]] = None):
        self.account = account
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG
        self.slot = slot
        self.events = events          # chuỗi sự kiện đã áp (None = không ghi); dùng chung giữa các book để giữ thứ tự toàn cục
        self.position: Optional[PositionModel] = None
        self.orders: List[OrderModel] = []
        self.reset()

    def reset(self) -> None:
        self.qty = 0.0
        self.avg = 0.0
        self.margin_used = 0.0
        self.fees_paid = 0.0
        self.layer_count = 0
        self.last_fill = 0.0
        self.entry_time = 0
        self.reserved_here = 0.0   # tiền đã giữ chỗ trong sổ vốn cho vị thế này
        self.funding_paid = 0.0    # funding đã trả (+) / nhận (−), đã hạch toán thẳng vào sổ vốn
        self.entry_equity = self.account.equity

    # ─── kiểm tra trước giao dịch ───────────────────────────────────────────
    def can_add(self, margin: float, fee: float, max_capital: float) -> bool:
        """Ngân sách một vị thế: ký quỹ + phí đã dùng + tầng mới không vượt max_capital."""
        return not (self.margin_used + margin + self.fees_paid + fee > max_capital + 1e-9)

    def reject(self, reason: str, kind: str, order_id: int = 0) -> None:
        ev = OrderRejected(self.slot, order_id, kind, reason)
        self.account.apply(ev)
        if self.events is not None:
            self.events.append(ev)

    # ─── sự kiện ────────────────────────────────────────────────────────────
    def apply(self, ev: Event) -> Optional[PositionModel]:
        """Áp một sự kiện (dùng khi phát lại). Trả vị thế vừa đóng nếu là Fill đóng."""
        if isinstance(ev, Fill):
            if ev.kind in ("entry", "dca"):
                self.apply_fill(ev)
                return None
            return self.apply_close(ev)
        if isinstance(ev, FundingApplied):
            self.apply_funding(ev)
        elif isinstance(ev, OrderRejected):
            self.account.apply(ev)
            if self.events is not None:
                self.events.append(ev)
        elif isinstance(ev, PositionMarked):
            self.mark(ev.high, ev.low)
        return None

    def mark(self, high: float, low: float) -> None:
        """Đầu nến của vị thế đang mở: đỉnh/đáy của PositionModel."""
        if self.position is not None:
            self.position.max_price = max(self.position.max_price, high)
            self.position.min_price = min(self.position.min_price, low)
            if self.events is not None:
                self.events.append(PositionMarked(self.slot, high, low))

    def apply_fill(self, fill: Fill) -> None:
        """Lệnh vào / nhồi tầng đã được chấp nhận (đã qua can_add + can_reserve)."""
        margin, fee, price = fill.margin, fill.fee, fill.price
        self.account.apply(fill)
        self.reserved_here += margin + fee
        qty = fill.notional / price
        new_qty = self.qty + qty
        self.avg = (self.avg * self.qty + price * qty) / new_qty
        self.qty = new_qty
        self.margin_used += margin
        self.fees_paid += fee
        self.layer_count += 1
        self.last_fill = price
        if self.position is None:
            self.entry_time = fill.t
            self.entry_equity = self.account.equity
            self.position = PositionModel(
                result_id=fill.order_id, account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol,
                pos_type=self.pos_type, phase=0, enter_time=fill.t, enter_price=price, status=PositionStatus.OPEN,
                flow=self.flow_name, start_reason=fill.reason, max_price=price, min_price=price,
                entry_equity=self.account.equity, entry_margin_usd=margin, entry_notional_usd=fill.notional, entry_fee_usd=fee,
            )
            self.position.unit_pct = fill.unit_pct
            self.position.leverage_used = fill.leverage_used
            self.position.risk_usd = fill.risk_usd
        self.orders.append(OrderModel(
            order_id=fill.order_id, account_id=self.account_id, position_id=self.position.result_id, order_time=fill.t,
            order_type=OrderType.BUY if self.is_long else OrderType.SELL, order_price=price, qty=qty,
            phase=self.layer_count - 1, fee_usd=fee, liquidity=fill.liquidity, slippage=fill.slip,
        ))
        if self.events is not None:
            self.events.append(fill)

    def apply_close(self, fill: Fill, status: Optional[PositionStatus] = None, reason: Optional[str] = None,
                    mae_usd: Optional[float] = None) -> PositionModel:
        """Đóng hết vị thế: lãi/lỗ gộp, phí thoát, trần thanh lý, nhả giữ chỗ, quyết toán sổ vốn, điền PositionModel + OrderModel đóng."""
        status = PositionStatus(fill.status) if status is None else status
        reason = fill.reason if reason is None else reason
        mae = fill.mae_usd if mae_usd is None else mae_usd
        price, exit_fee, slip, t = fill.price, fill.fee, fill.slip, fill.t
        gross = gross_pnl(self.qty, self.avg, price, self.is_long)
        trade_cash = gross - self.fees_paid - exit_fee          # phần chưa vào sổ vốn (funding đã vào)
        if status == PositionStatus.LIQ:                         # isolated: mất tối đa ký quỹ + phí đã trả
            trade_cash = max(trade_cash, -(self.margin_used + self.fees_paid + exit_fee))
        # Nhả phần giữ chỗ (ký quỹ + phí vào lệnh), vốn thay đổi đúng bằng lãi/lỗ giao dịch sau phí.
        self.account.close_trade(self.reserved_here, trade_cash)
        net = trade_cash - self.funding_paid
        pos = self.position
        pos.close_time = t
        pos.close_price = price
        pos.status = status
        pos.close_reason = reason
        pos.exit_fee_usd = exit_fee
        pos.real_pnl = net
        pos.entry_equity = self.entry_equity
        pos.profit_pct = net / self.entry_equity * 100.0 if self.entry_equity > 0 else 0.0
        pos.qty = self.qty
        pos.layers = self.layer_count
        pos.avg_price = self.avg
        pos.total_margin_usd = self.margin_used
        pos.fees_usd = self.fees_paid + exit_fee
        pos.funding_usd = self.funding_paid
        pos.mae_pct = min(0.0, mae / self.entry_equity * 100.0) if self.entry_equity > 0 else 0.0
        self.orders.append(OrderModel(
            order_id=fill.order_id, account_id=self.account_id, position_id=pos.result_id, order_time=t,
            order_type=OrderType.SELL if self.is_long else OrderType.BUY, order_price=price, qty=self.qty,
            phase=self.layer_count, fee_usd=exit_fee, liquidity=fill.liquidity, slippage=slip,
        ))
        self.position = None
        self.reset()
        if self.events is not None:
            self.events.append(fill)
        return pos

    def apply_funding(self, ev: FundingApplied) -> float:
        self.funding_paid += ev.payment
        self.account.apply(ev)
        if self.events is not None:
            self.events.append(ev)
        return ev.payment

    def unrealized_pnl(self, price: float) -> float:
        if self.qty <= 0:
            return 0.0
        return unrealized_pnl(self.qty, self.avg, price, self.fees_paid, self.is_long)  # funding đã nằm trong equity của Account


# ══════════════════════════════════════════════════════════════════════════
# Tương thích ngược: CapitalLedger là tên cũ của Account — cùng một lớp.
# ══════════════════════════════════════════════════════════════════════════

CapitalLedger = Account


# ══════════════════════════════════════════════════════════════════════════
# Nguồn dữ liệu của engine (engine-API pass, ADR-P9: core không I/O, không import gì ngoài core)
#
# Engine (BacktestEngine / PortfolioEngine / build_plan / signal_snapshot / check_signals) KHÔNG tự đọc đĩa: mọi nến, funding, manifest, cổng chất
# lượng, kho mmap dùng chung và bộ nhớ đệm mảng đi qua MỘT đối tượng `DataSource` truyền vào (`data=`). Bản cài đặt thật nằm NGOÀI core
# (backend/optimize/search/evaluate.py: EngineData bọc crawl/store + kho mmap dùng chung). `data=None` = nguồn mặc định của tiến
# trình, do tầng trên đăng ký bằng set_default_data_source (backend/optimize/__init__.py — mọi lối vào: API, job, worker, test, live).
# ══════════════════════════════════════════════════════════════════════════

class DataMemo(Protocol):
    """Bộ nhớ đệm mảng đã dựng (theo byte) của tiến trình: get(key) -> giá trị | None; put(key, giá trị, số byte); clear(); used (byte)."""
    used: int

    def get(self, key: Any) -> Any: ...

    def put(self, key: Any, value: Any, nbytes: int) -> None: ...

    def clear(self) -> None: ...


class DataSource(Protocol):
    """Mọi thứ engine cần từ dữ liệu (đúng các thao tác engine dùng; cài đặt: backend/optimize/search/evaluate.py::EngineData)."""

    def candles(self, symbol: str, frame: str, start: int, end: int, columns: Optional[List[str]] = None,
                use_cache: bool = True) -> Any:
        """Nến [start, end] (gồm hai đầu) của khung `frame` (DataFrame như CandleLoader.load_data)."""

    def exec_arrays(self, symbol: str, frame: str, start: int, end: int) -> Dict[str, Any]:
        """Nến THỰC THI của engine: nến 1m THẬT (không nến bù) gộp thành khung `frame`, theo open_time trong [start, end] ->
        {"t" (open_time ms, int64), "o", "h", "l", "c", "v"} (numpy). Engine đổi mảng này thành Bar Nautilus."""

    def instrument_spec(self, symbol: str) -> Dict[str, Any]:
        """Spec hợp đồng của tài sản: tickSz, lotSz, ctVal, minSz, margin_init, margin_maint, maker_fee, taker_fee (+ base_symbol).
        Engine dựng Instrument Nautilus (độ chính xác giá/khối lượng) từ đây."""

    def funding(self, symbol: str) -> Any:
        """Toàn bộ funding.pkl của instrument perp (DataFrame) hoặc None nếu không có."""

    def require_ok(self, symbols: List[str]) -> Any:
        """Cổng chất lượng dữ liệu BẮT BUỘC (raise nếu synthetic / sai sha256 / thiếu dữ liệu)."""

    def manifest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Manifest của tài sản (venue, pool_fee_rate, start_ts, end_ts, ...) hoặc None."""

    def base_name(self, symbol: str) -> str:
        """Tên tài sản trần: 'cex:btc@perp' -> 'BTC'."""

    def shared_plan(self, eng: Any) -> Optional[Dict[str, Any]]:
        """Khoá kho mmap dùng chung cho đúng bộ dữ liệu engine `eng` sẽ dựng (None: không dùng kho)."""

    def shared_load(self, out_dir: str, plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dữ liệu của `plan` từ kho (giống PortfolioEngine._build_symbol_data) hoặc None nếu thiếu / hỏng."""

    def shared_fill(self, out_dir: str, pe: Any, eng: Any, plan: Dict[str, Any]) -> Any:
        """Tính (qua đúng hàm của engine) và ghi phần còn thiếu của `plan` vào kho."""

    def release(self) -> None:
        """Nhả bộ nhớ đệm nến của tiến trình (sau khi điền kho)."""

    @property
    def memo(self) -> DataMemo:
        """Bộ nhớ đệm mảng đã dựng của tiến trình (PortfolioEngine._load_symbol)."""


_DEFAULT_DATA: List[Any] = [None]
_DEFAULT_FACTORY: List[Any] = [None]


def set_default_data_source(src: Optional[DataSource]) -> None:
    """Đăng ký nguồn dữ liệu mặc định của tiến trình (gọi ở tầng trên — backend/optimize/__init__.py; test có thể thay)."""
    _DEFAULT_DATA[0] = src
    _DEFAULT_FACTORY[0] = None


def set_default_data_factory(factory: Optional[Callable[[], DataSource]]) -> None:
    """Như set_default_data_source nhưng LƯỜI: `factory()` chỉ chạy ở lần data_source() đầu tiên (gói đăng ký không phải import nặng khi nạp)."""
    _DEFAULT_DATA[0] = None
    _DEFAULT_FACTORY[0] = factory


def data_source(data: Optional[DataSource] = None) -> DataSource:
    """`data` nếu có, không thì nguồn mặc định đã đăng ký; chưa đăng ký -> RuntimeError rõ ràng."""
    src = data if data is not None else _DEFAULT_DATA[0]
    if src is None and _DEFAULT_FACTORY[0] is not None:
        src = _DEFAULT_DATA[0] = _DEFAULT_FACTORY[0]()
    if src is None:
        raise RuntimeError("engine chưa có nguồn dữ liệu: truyền data=... hoặc import backend.optimize (đăng ký EngineData mặc định)")
    return src
