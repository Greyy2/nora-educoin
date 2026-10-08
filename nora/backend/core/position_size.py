"""Chính sách vị thế + khối lượng + kiểm rủi ro (P9.4): hàm THUẦN số học cho mọi mức giá / khối lượng / admit_entry.

Hợp nhất NGUYÊN VĂN từ core/execute/{policy,risk}.py (xem docs/bmad/p9_review_log.md, mục P9.4 part 1). Đường dẫn cũ là alias (shim).
"""
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from backend.core.models import PositionType
from backend.core.params import StrategyParams
from backend.core.models import gross_pnl, pnl_move, unrealized_pnl   # noqa: F401  (P9.4: ba hàm này chuyển sang models; policy.gross_pnl... vẫn là cùng đối tượng)


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/execute/policy.py
#
# Chính sách vị thế (position policy) — hàm THUẦN cho mọi mức giá và công thức khối lượng.
#
# Một nguồn duy nhất cho công thức: `PositionTracker` (backtest) uỷ quyền vào đây; PositionManager và bot live (P6.4+)
# sẽ gọi cùng các hàm này. Không trạng thái, không I/O, không import model — chỉ số học.
#
# Quy ước:
# - `sign` = +1.0 (LONG) / -1.0 (SHORT); `is_long` là bool tương ứng. Hàm nào nhận `sign` hay `is_long` giữ đúng
#   dạng biểu thức của code gốc trong tracker để thứ tự phép toán float giống từng bit (golden + parity kernel).
# - Mức giá (level) là giá trị tuyệt đối; `*_pct` là phần trăm (1.0 = 1%); `limit_through` là tỉ lệ (0.001 = 0.1%).
# ══════════════════════════════════════════════════════════════════════════

ImpactFn = Optional[Callable[[float, bool], float]]


INTRABAR_PATHS = ("ohlc", "adaptive", "adverse_first")


def sign_of(is_long: bool) -> float:
    return 1.0 if is_long else -1.0


# ─── Đường giá trong nến (intrabar_path) ────────────────────────────────────
def bar_points(path: str, o: float, h: float, l: float, c: float) -> Tuple[float, float, float, float]:
    """Bốn điểm giá nến đi qua theo thứ tự (chỉ cho "ohlc" / "adaptive"; "adverse_first" xử lý riêng, không theo điểm).
    "ohlc" (mặc định, = NautilusTrader): Open -> High -> Low -> Close. "adaptive" (= `bar_adaptive_high_low_ordering=True`): cực gần open
    ghé trước — Nautilus `bar_high_first = high - open < open - low` (HOÀ khoảng cách -> Low trước)."""
    if path == "ohlc" or h - o < o - l:
        return (o, h, l, c)
    return (o, l, h, c)


def peak_step(peak: float, price: float, is_long: bool) -> float:
    """Đỉnh (long) / đáy (short) có lợi chạy dọc đường giá: cập nhật sau mỗi chặng (max/min kiểu Python)."""
    if is_long:
        return price if price > peak else peak
    return price if price < peak else peak


def tick_stop_price(level: float, open_price: float, is_long: bool, at_open: bool) -> float:
    """Giá khớp lệnh STOP-market / thanh lý khi bị một chặng đường giá xuyên qua (đường ohlc/adaptive): chặng mở cửa (gap) -> open
    (`gap_fill`); chặng trong nến -> đúng mức kích hoạt (NautilusTrader `fill_at_market=False`: stop khớp ở trigger)."""
    return gap_fill(level, open_price, is_long) if at_open else level


# ─── Mức giá ────────────────────────────────────────────────────────────────
def dca_level(last_fill: float, step_pct: float, sign: float) -> float:
    """Mức đặt tầng DCA kế tiếp: lùi `step_pct`% khỏi giá khớp gần nhất (long: xuống, short: lên)."""
    return last_fill * (1 - sign * step_pct / 100.0)


def dca_trigger(level: float, limit_through: float, sign: float) -> float:
    """Giá phải đi tới mới tính là lệnh limit DCA khớp: xuyên QUA mức `limit_through` (0 = chạm là khớp)."""
    return level * (1 - sign * limit_through) if limit_through else level


def sl_level(avg: float, sl_pct: float, sign: float) -> float:
    """Mức stop-loss tính từ giá trung bình."""
    return avg * (1 - sign * sl_pct / 100.0)


def trail_active(peak: float, avg: float, activation_pct: float, sign: float) -> bool:
    """Trailing chỉ bật khi lãi tại đỉnh/đáy có lợi (so với giá TB) đạt `activation_pct`%."""
    gain_pct = sign * (peak - avg) / avg * 100.0 if avg else 0.0
    return gain_pct >= activation_pct


def trail_level(peak: float, trail_pct: float, sign: float) -> float:
    """Mức trailing stop: lùi `trail_pct`% khỏi đỉnh (long) / đáy (short) có lợi."""
    return peak * (1 - sign * trail_pct / 100.0)


def tp_level(avg: float, tp_pct: float, sign: float) -> float:
    """Mức chốt lời tính từ giá trung bình."""
    return avg * (1 + sign * tp_pct / 100.0)


def tp_need(level: float, limit_through: float, sign: float) -> float:
    """Giá có lợi phải đi tới để lệnh limit chốt lời khớp (xuyên qua mức `limit_through`)."""
    return level * (1 + sign * limit_through) if limit_through else level


def tp_hit(favorable: float, need: float, is_long: bool) -> bool:
    return (favorable >= need) if is_long else (favorable <= need)


def tp_fill_price(level: float, open_price: float, is_long: bool) -> float:
    """Giá khớp chốt lời kiểu SWAP (AMM, `limit_taker`): open đã vượt mức (gap có lợi) thì khớp ở open.
    Lệnh limit chờ sẵn (sàn thật / SimVenue) KHÔNG dùng hàm này: khớp đúng ở mức (quy tắc bảo thủ 2026-10-06)."""
    return max(level, open_price) if is_long else min(level, open_price)


def liq_price(avg: float, leverage: float, mmr: float, is_long: bool) -> float:
    """Giá thanh lý isolated perp: long avg×(1−1/L+mmr), short avg×(1+1/L−mmr)."""
    if is_long:
        return avg * (1.0 - 1.0 / leverage + mmr)
    return avg * (1.0 + 1.0 / leverage - mmr)


def reached(level: float, extreme: float, is_long: bool) -> bool:
    """Phía bất lợi của nến (long: low, short: high) đã chạm mức chưa."""
    return extreme <= level if is_long else extreme >= level


def gap_fill(level: float, open_price: float, is_long: bool) -> float:
    """Giá khớp lệnh STOP-market / thanh lý khi chạm mức bất lợi: nếu open đã vượt qua mức (gap) thì khớp ở open.
    Không dùng cho lệnh limit chờ sẵn (tầng DCA, chốt lời): chúng khớp ở mức đặt."""
    if is_long:
        return min(level, open_price)
    return max(level, open_price)


def stop_extreme_fill(price: float, adverse: float, is_long: bool) -> float:
    """stop_fill='extreme': stop-market khớp ở giá xấu nhất của nến (bi quan)."""
    return min(price, adverse) if is_long else max(price, adverse)


def pick_first_touched(events: Sequence[Tuple[float, int, str]], is_long: bool) -> Tuple[float, int, str]:
    """Trong các mức đã chạm, mức giá chạm TRƯỚC: long = cao nhất (giá rơi xuống), short = thấp nhất;
    hoà mức -> ưu tiên thoát (số ưu tiên nhỏ hơn)."""
    if is_long:
        return max(events, key=lambda e: (e[0], -e[1]))
    return min(events, key=lambda e: (e[0], e[1]))


# ─── Giá khớp, phí, PnL ─────────────────────────────────────────────────────
def slip_rate(slippage_rate: float, impact_fn: ImpactFn, notional: float, is_buy: bool) -> float:
    """Tỉ lệ trượt giá lệnh taker: impact_fn theo khối lượng (AMM) hoặc slippage_rate cố định."""
    return slippage_rate if impact_fn is None else float(impact_fn(float(notional), bool(is_buy)))


def round_trip_cost(fee_rate: float, slippage_rate: float, impact_fn: ImpactFn, notional: float) -> float:
    """Chi phí KHỨ HỒI (phí taker + trượt giá) trên danh nghĩa `notional`."""
    if impact_fn is None:
        return 2.0 * (fee_rate + slippage_rate)
    return 2.0 * fee_rate + slip_rate(slippage_rate, impact_fn, notional, True) \
        + slip_rate(slippage_rate, impact_fn, notional, False)


def entry_fill_price(price: float, slip: float, is_long: bool) -> float:
    """Giá khớp lệnh MUA/BÁN vào kiểu taker: long trả cao hơn, short bán thấp hơn."""
    return price * (1 + slip if is_long else 1 - slip)


def exit_fill_price(raw_price: float, slip: float, is_long: bool) -> float:
    """Giá khớp lệnh thoát kiểu taker: long bán thấp hơn, short mua cao hơn."""
    return raw_price * (1 - slip if is_long else 1 + slip)


def entry_fee(notional: float, rate: float) -> float:
    return notional * rate


def exit_fee(qty: float, price: float, rate: float) -> float:
    return qty * price * rate


def in_profit(price: float, avg: float, is_long: bool) -> bool:
    """Thoát ở `price` đang lãi (-> trạng thái TP) hay lỗ (-> SL)."""
    return pnl_move(price, avg, is_long) > 0


def funding_payment(qty: float, price: float, rate: float, is_long: bool) -> float:
    """Funding perp: long trả qty·giá·rate khi rate > 0 (short nhận), và ngược lại."""
    return qty * price * rate * (1.0 if is_long else -1.0)


# ─── Khối lượng ─────────────────────────────────────────────────────────────
def layer_mult_total(dca_mults: Sequence[float], n_steps: int) -> float:
    """Tổng khối lượng các tầng (lệnh đầu = 1) theo hệ số DCA."""
    total, m = 1.0, 1.0
    for k in dca_mults[:n_steps]:
        m *= k
        total += m
    return total


def exit_params_scaled(unit: float, base_sl: float, base_tp: float, base_trail: float, base_trail_act: float,
                       base_dca_steps: Sequence[float]) -> Tuple[float, float, float, float, List[float]]:
    """Quy đổi tham số thoát sang % (unit = 1 với 'pct', = ATR% với 'atr').
    Trả (sl_pct, tp_pct, trail_pct, trail_activation_pct, dca_steps)."""
    return (base_sl * unit, base_tp * unit, base_trail * unit, base_trail_act * unit,
            [x * unit for x in base_dca_steps])


def flat_margin(equity: float, order_size_pct: float) -> float:
    """Ký quỹ tầng đầu theo % vốn hiện tại (sizing='margin_pct')."""
    return equity * order_size_pct / 100.0


def risk_margin(equity: float, risk_pct: float, max_notional_pct: float, sl_pct: float, fee_rate: float,
                slippage_rate: float, impact_fn: ImpactFn, is_perp: bool, max_leverage: float, mmr: float,
                pos_leverage: float, total_mult: float) -> Tuple[float, float, float]:
    """Khối lượng theo rủi ro: chạm SL (cả mọi tầng DCA dự kiến + phí khứ hồi) thì mất ~risk_pct% vốn;
    danh nghĩa chặn bởi max_notional_pct% vốn. Perp: đòn bẩy thực = min(đòn bẩy tham số, mức để giá thanh lý
    cách giá vào >= 1,5 × khoảng SL). Trả (ký quỹ tầng đầu, đòn bẩy vị thế, rủi ro dự kiến)."""
    sl = sl_pct / 100.0
    cap = equity * max_notional_pct / 100.0
    if impact_fn is None:
        cost = round_trip_cost(fee_rate, slippage_rate, impact_fn, 0.0)
        notional = equity * risk_pct / 100.0 / (sl + cost)
        notional = min(notional, cap)
    else:   # trượt giá phụ thuộc khối lượng: lần 1 chưa tính trượt (chỉ phí), lần 2 tính trượt theo khối lượng dự kiến của lần 1
        notional = min(equity * risk_pct / 100.0 / (sl + 2.0 * fee_rate), cap)
        cost = round_trip_cost(fee_rate, slippage_rate, impact_fn, notional)
        notional = min(equity * risk_pct / 100.0 / (sl + cost), cap)
    if is_perp:
        safe = int(1.0 / (1.5 * sl + mmr)) if sl > 0 else int(max_leverage)
        pos_leverage = float(max(1, min(int(max_leverage), safe)))
    planned_risk = notional * (sl + cost)
    return notional / total_mult / pos_leverage, pos_leverage, planned_risk


def clamp_margin(margin: float, budget: float, leverage: float, fee_rate: float, max_new_notional: float) -> float:
    """Chặn ký quỹ tầng đầu bởi ngân sách trống (chừa phí vào lệnh) và trần danh nghĩa của danh mục."""
    return min(margin, budget / (1.0 + leverage * fee_rate), max_new_notional / leverage)


def planned_risk_cap(margin: float, leverage: float, sl_pct: float, cost: float, total_mult: float) -> float:
    """Rủi ro tới SL (cả rổ DCA) của ký quỹ đã bị chặn — dùng để hạ planned_risk khi margin bị cắt."""
    return margin * leverage * (sl_pct / 100.0 + cost) * total_mult


def apply_risk_ceiling(margin: float, planned_risk: float, max_new_risk: float) -> Tuple[float, float]:
    """Trần rủi ro đang mở của danh mục: trần <= 0 -> không mở; vượt trần -> co ký quỹ theo tỉ lệ.
    Trả (ký quỹ, rủi ro dự kiến)."""
    if max_new_risk != float("inf") and planned_risk > max_new_risk:
        if max_new_risk <= 0:
            margin = 0.0
        else:
            margin = margin * (max_new_risk / planned_risk)
            planned_risk = max_new_risk
    return margin, planned_risk


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/execute/risk.py
#
# Quy tắc rủi ro danh mục — NGUỒN DUY NHẤT cho sim/paper/live: hàm thuần, đầu vào là số thường (không đối tượng sổ vốn/tracker),
# nên PaperBook, runner và bot sàn dùng chung với số của riêng mình.
#
# Bản numba trong core/backtest/kernel.py giữ bản sao riêng của các quy tắc này (để chạy nhanh); hai bản được khoá bằng test parity
# (test/test_risk_engine.py, test/test_kernel_parity.py) — sửa quy tắc ở đây thì phải sửa kernel và chạy lại parity.
#
# Thứ tự phép toán float và cấu trúc điều kiện giữ y nguyên code gốc của PaperBook.step_bar (so sánh tường minh, không dùng max/min,
# trừ max(0.0, room)) để kết quả trùng từng bit.
# ══════════════════════════════════════════════════════════════════════════

INF = float("inf")


class Admission(NamedTuple):
    """Kết quả xét mở lệnh mới: can_open=False -> lệnh bị chặn (người gọi tăng rejected_for_risk). Ba trần còn lại đặt vào tracker
    trước on_bar (mặc định inf/inf/1.0 khi quy tắc tương ứng không áp dụng)."""
    can_open: bool
    max_new_notional: float
    max_new_risk: float
    risk_scale: float


def admit_entry(n_open: int, per_symbol_open: int, equity: float, peak: float, gross: float, open_risk: float,
                max_positions, max_per_symbol, max_gross_exposure: float, max_open_risk_pct: float = 0.0,
                dd_throttle_pct: float = 0.0, dd_throttle_floor: float = 0.25) -> Admission:
    """Xét một lệnh vào mới ở giá mở nến.
    n_open / per_symbol_open: số vị thế đang mở toàn danh mục / của tài sản này. equity / peak: vốn đã chốt LÚC MỞ NẾN (chưa gồm lệnh thoát trong nến) và đỉnh của nó.
    gross: tổng danh nghĩa đang mở, định giá theo đóng nến TRƯỚC (người gọi tính ở pha mở nến, P6.12: không nhìn giá nến hiện tại). open_risk: Σ planned_risk của vị thế mở.
    max_open_risk_pct / dd_throttle_pct = 0 -> tắt quy tắc; peak <= 0 -> bỏ qua dd_throttle."""
    max_new_notional, max_new_risk, risk_scale = INF, INF, 1.0
    blocked = n_open >= int(max_positions) or per_symbol_open >= int(max_per_symbol)
    if blocked:
        return Admission(False, max_new_notional, max_new_risk, risk_scale)
    room = float(max_gross_exposure) * equity - gross
    max_new_notional = max(0.0, room)
    can_open = room > 0
    risk_cap = float(max_open_risk_pct or 0.0) / 100.0
    if can_open and risk_cap != 0.0:                 # trần Σ rủi ro tới SL của vị thế mở (như kernel)
        max_new_risk = risk_cap * equity - open_risk
        can_open = max_new_risk > 0.0
    thr = float(dd_throttle_pct or 0.0) / 100.0
    if can_open and thr != 0.0 and peak > 0.0:       # giảm rủi ro theo mức sụt vốn đã chốt
        floor = float(dd_throttle_floor)
        rs = 1.0 - (1.0 - equity / peak) / thr
        rs = floor if rs < floor else rs
        risk_scale = 1.0 if rs > 1.0 else rs
    return Admission(can_open, max_new_notional, max_new_risk, risk_scale)


def kill_triggered(worst: float, peak_mtm: float, kill_switch_dd_pct: float) -> bool:
    """Kill switch: vốn xấu nhất của nến chạm/thủng (1 - kill) × đỉnh MTM. kill_switch_dd_pct = 0 -> không bao giờ kích hoạt.
    Người gọi tự kiểm "chưa halt" (halted_at is None)."""
    kill = float(kill_switch_dd_pct or 0) / 100.0
    return bool(kill) and worst <= peak_mtm * (1.0 - kill)


# ══════════════════════════════════════════════════════════════════════════
# P9.4b T4 — SlotSpec: chuẩn hoá tham số một slot (flow) cho kernel, NGUYÊN VĂN từ PositionTracker.__init__ (cùng mặc định, cùng trường dẫn xuất,
# cùng ngoại lệ + thông báo + thứ tự kiểm). PositionTracker dựng từ SlotSpec nên chỉ còn MỘT bản logic này.
# ══════════════════════════════════════════════════════════════════════════
class SlotSpec:
    """Tham số đã chuẩn hoá + trạng thái khởi đầu của một slot. Tên thuộc tính trùng PositionTracker (pack_slots đọc được cả hai)."""

    def __init__(self, account_id: int, campaign_id: int, symbol: str, flow_name: str, params: "StrategyParams",
                 pos_type: PositionType, initial_capital: float = 10000.0, entry_equity: Optional[float] = None):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.params = params
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG

        self.market = str(getattr(params, "market", "spot") or "spot").lower()
        if self.market not in ("spot", "perp"):
            raise ValueError(f"market phải là 'spot' hoặc 'perp', nhận '{self.market}'")
        if self.market == "spot" and not self.is_long:
            raise ValueError(f"Flow '{flow_name}': thị trường spot không bán khống được — dùng market='perp' cho SHORT.")
        self.leverage = 1.0 if self.market == "spot" else max(1.0, float(params.leverage or 1.0))
        self.mmr = max(0.0, float(getattr(params, "maintenance_margin_rate", 0.005) or 0.0))
        # Phí: taker cho lệnh market (vào ở open, SL, trailing, timeout, tín hiệu thoát);
        #      maker cho lệnh limit (tầng DCA, chốt lời). fee_rate cũ = taker.
        self.fee_rate = max(0.0, float(params.fee_rate or 0.0))
        maker = getattr(params, "maker_fee_rate", None)
        self.maker_fee_rate = self.fee_rate if maker is None else max(0.0, float(maker))
        self.slippage_rate = max(0.0, float(params.slippage_rate or 0.0))
        self.capital = float(initial_capital)
        self.capital_usage = max(0.0, min(float(params.max_capital_usage or 1.0), 1.0))
        self.entry_equity = self.capital if entry_equity is None else float(entry_equity)   # vốn đã chốt lúc dựng slot (sổ vốn chung)
        self.max_capital = self.capital * self.capital_usage

        # Giá trị gốc của tham số thoát lệnh; mỗi vị thế quy đổi sang % lúc vào lệnh.
        self.base_sl = max(0.0, float(params.stop_loss_rate or 0.0))
        self.base_tp = max(0.0, float(params.take_profit_rate or 0.0))
        self.base_trail = max(0.0, float(params.trailing_stop or 0.0))
        self.base_trail_act = max(0.0, float(getattr(params, "trailing_activation_pct", 0.0) or 0.0))
        self.timeout_ms = max(0, int(params.timeout or 0)) * 60_000
        self.cooldown_ms = max(0, int(getattr(params, "cooldown", 0) or 0)) * 60_000
        self.stop_fill = str(getattr(params, "stop_fill", "level") or "level").lower()
        # lệnh limit (tầng DCA, chốt lời) chỉ khớp khi giá đi QUA mức bấy nhiêu % (hàng đợi sổ lệnh); 0 = chạm là khớp
        self.limit_through = max(0.0, float(getattr(params, "limit_through_pct", 0.0) or 0.0)) / 100.0
        if self.stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{self.stop_fill}'")
        self.intrabar_path = str(getattr(params, "intrabar_path", "ohlc") or "ohlc").lower()
        if self.intrabar_path not in INTRABAR_PATHS:
            raise ValueError(f"intrabar_path phải là một trong {INTRABAR_PATHS}, nhận '{self.intrabar_path}'")
        self.exit_unit = str(getattr(params, "exit_unit", "pct") or "pct").lower()
        if self.exit_unit not in ("pct", "atr"):
            raise ValueError(f"exit_unit phải là 'pct' hoặc 'atr', nhận '{self.exit_unit}'")
        self.atr_frame = str(getattr(params, "atr_frame", "1h") or "1h")
        self.atr_period = int(getattr(params, "atr_period", 14) or 14)
        self.sizing = str(getattr(params, "sizing", "margin_pct") or "margin_pct").lower()
        if self.sizing not in ("margin_pct", "risk"):
            raise ValueError(f"sizing phải là 'margin_pct' hoặc 'risk', nhận '{self.sizing}'")
        self.risk_pct = max(0.0, float(getattr(params, "risk_per_trade_pct", 0.5) or 0.0))
        self.max_notional_pct = max(0.0, float(getattr(params, "max_notional_pct", 100.0) or 0.0))
        if self.sizing == "risk" and self.base_sl <= 0:
            raise ValueError(f"Flow '{flow_name}': sizing='risk' cần stop_loss_rate > 0 (rủi ro đo tại SL).")

        layers = max(0, int(getattr(params, "dca_max_layers", 0) or 0))
        step = float(getattr(params, "dca_step_pct", 0.0) or 0.0)
        mult = float(getattr(params, "dca_size_multiplier", 1.0) or 1.0)
        steps = [float(x) for x in (params.dca_steps or [])] or ([step] * layers if step > 0 else [])
        mults = [float(x) for x in (params.dca_multipliers or [])] or [mult] * len(steps)
        if len(mults) < len(steps):
            mults += [mults[-1] if mults else 1.0] * (len(steps) - len(mults))
        if any(s <= 0 for s in steps) or any(m <= 0 for m in mults):
            raise ValueError("Bước DCA và hệ số khối lượng phải > 0")
        self.base_dca_steps = [abs(s) for s in steps]
        self.dca_mults = mults[: len(steps)]
        self.max_leverage = self.leverage
        self.pos_leverage = self.leverage
        self.planned_risk = 0.0
        self.unit_pct = 0.0
        (self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct,
         self.dca_steps) = exit_params_scaled(1.0, self.base_sl, self.base_tp, self.base_trail,
                                                     self.base_trail_act, self.base_dca_steps)
        self.order_size_pct = max(0.0, float(params.order_size_pct or 0.0))
        self.max_open_trades = int(getattr(params, "max_open_trades", 45) or 45)

        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        self.match_tree = self._combine_conditions(ast.get("match", []))
        self.stop_tree = self._combine_conditions(ast.get("stop", []))
        # Điều kiện cho phép DCA (dồn có điều kiện): rỗng = luôn được dồn.
        self.dca_tree = self._combine_conditions(ast.get("dca", []))
        self.dca_ok = True

    @staticmethod
    def _combine_conditions(blocks: List[Dict[str, Any]]) -> List[Any]:
        combined: List[Any] = []
        if not isinstance(blocks, list):
            return combined
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("condition", []), list):
                combined.extend(block.get("condition", []))
        return combined
