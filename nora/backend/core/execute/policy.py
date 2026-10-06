"""Chính sách vị thế (position policy) — hàm THUẦN cho mọi mức giá và công thức khối lượng.

Một nguồn duy nhất cho công thức: `PositionTracker` (backtest) uỷ quyền vào đây; PositionManager và bot live (P6.4+)
sẽ gọi cùng các hàm này. Không trạng thái, không I/O, không import model — chỉ số học.

Quy ước:
- `sign` = +1.0 (LONG) / -1.0 (SHORT); `is_long` là bool tương ứng. Hàm nào nhận `sign` hay `is_long` giữ đúng
  dạng biểu thức của code gốc trong tracker để thứ tự phép toán float giống từng bit (golden + parity kernel).
- Mức giá (level) là giá trị tuyệt đối; `*_pct` là phần trăm (1.0 = 1%); `limit_through` là tỉ lệ (0.001 = 0.1%).
"""
from typing import Callable, List, Optional, Sequence, Tuple

ImpactFn = Optional[Callable[[float, bool], float]]


def sign_of(is_long: bool) -> float:
    return 1.0 if is_long else -1.0


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
    """Giá khớp chốt lời: open đã vượt mức (gap có lợi) thì khớp ở open."""
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
    """Giá khớp khi chạm mức bất lợi: nếu open đã vượt qua mức (gap) thì khớp ở open."""
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


def pnl_move(price: float, avg: float, is_long: bool) -> float:
    """Lãi/lỗ trên một đơn vị: long price−avg, short avg−price."""
    return (price - avg) if is_long else (avg - price)


def gross_pnl(qty: float, avg: float, price: float, is_long: bool) -> float:
    return qty * pnl_move(price, avg, is_long)


def unrealized_pnl(qty: float, avg: float, price: float, fees_paid: float, is_long: bool) -> float:
    """PnL chưa chốt sau phí đã trả (funding đã nằm trong ledger)."""
    return qty * pnl_move(price, avg, is_long) - fees_paid


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
