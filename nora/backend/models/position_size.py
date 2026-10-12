"""Chính sách vị thế + khối lượng + kiểm rủi ro (P9.4): hàm THUẦN số học cho mọi mức giá / khối lượng / admit_entry.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.4).
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from backend.models.models import PositionType
from backend.models.params import DEFAULT_CAPITAL, StrategyParams
from backend.models.models import gross_pnl, pnl_move, unrealized_pnl   # noqa: F401  (P9.4: ba hàm này chuyển sang models; policy.gross_pnl... vẫn là cùng đối tượng)


# ══════════════════════════════════════════════════════════════════════════
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


def sl_price_for_anchor(anchor: str, entry_price: float, avg_price: float, sl_pct: float,
                        sign: float, dca_steps: Sequence[float] = (),
                        sl_beyond_last_pct: float = 0.0) -> float:
    """Tính mức giá Stop Loss tuyệt đối theo điểm neo:
    - 'avg': neo giá TB hiện tại: avg * (1 - sign * sl_pct / 100)
    - 'entry': neo giá mở vị thế ban đầu: entry * (1 - sign * sl_pct / 100)
    - 'last_layer': neo sau tầng DCA cuối cùng:
        p_last = entry; duyệt qua dca_steps (p_last = p_last * (1 - sign * step / 100));
        sl_level = p_last * (1 - sign * beyond / 100) (nếu beyond == 0 thì dùng sl_pct)
    - 'none': 0.0 (không có SL)
    """
    if anchor == "none" or (sl_pct <= 0.0 and sl_beyond_last_pct <= 0.0):
        return 0.0
    if anchor == "entry":
        return entry_price * (1.0 - sign * sl_pct / 100.0)
    if anchor == "last_layer":
        p_last = entry_price
        for s in dca_steps:
            p_last = p_last * (1.0 - sign * s / 100.0)
        beyond = sl_beyond_last_pct if sl_beyond_last_pct > 0.0 else sl_pct
        return p_last * (1.0 - sign * beyond / 100.0)
    return avg_price * (1.0 - sign * sl_pct / 100.0)


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
# Quy tắc rủi ro danh mục — NGUỒN DUY NHẤT cho sim/paper/live: hàm thuần, đầu vào là số thường (không đối tượng sổ vốn/tracker),
# nên PaperBook, runner và bot sàn dùng chung với số của riêng mình.
#
# Bản numba trong core/backtest.py (kernel) giữ bản sao riêng của các quy tắc này (để chạy nhanh); hai bản được khoá bằng test parity
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
                dd_throttle_pct: float = 0.0, dd_throttle_floor: float = 0.25,
                bucket_open: int = 0, bucket_max_positions: int = 0,
                bucket_open_risk: float = 0.0, bucket_max_open_risk_pct: float = 0.0,
                bucket_gross: float = 0.0, bucket_max_gross_exposure: float = 0.0) -> Admission:
    """Xét một lệnh vào mới ở giá mở nến.
    n_open / per_symbol_open: số vị thế đang mở toàn danh mục / của tài sản này. equity / peak: vốn đã chốt LÚC MỞ NẾN (chưa gồm lệnh thoát trong nến) và đỉnh của nó.
    gross: tổng danh nghĩa đang mở, định giá theo đóng nến TRƯỚC (người gọi tính ở pha mở nến, P6.12: không nhìn giá nến hiện tại). open_risk: Σ planned_risk của vị thế mở.
    max_open_risk_pct / dd_throttle_pct = 0 -> tắt quy tắc; peak <= 0 -> bỏ qua dd_throttle.
    Hỗ trợ kiểm tra theo bucket phân bổ (P14-B5): nếu bucket_max_positions > 0 thì kiểm thêm trần bucket.
    Nếu bucket_* = 0 -> không áp trần bucket (legacy bit-identical)."""
    max_new_notional, max_new_risk, risk_scale = INF, INF, 1.0
    blocked = n_open >= int(max_positions) or per_symbol_open >= int(max_per_symbol)
    if not blocked and bucket_max_positions > 0:
        blocked = bucket_open >= int(bucket_max_positions)
    if blocked:
        return Admission(False, max_new_notional, max_new_risk, risk_scale)
    room = float(max_gross_exposure) * equity - gross
    if bucket_max_gross_exposure > 0:
        b_room = float(bucket_max_gross_exposure) * equity - bucket_gross
        room = min(room, b_room)
    max_new_notional = max(0.0, room)
    can_open = room > 0
    risk_cap = float(max_open_risk_pct or 0.0) / 100.0
    if can_open and risk_cap != 0.0:                 # trần Σ rủi ro tới SL của vị thế mở (như kernel)
        max_new_risk = risk_cap * equity - open_risk
        if bucket_max_open_risk_pct > 0:
            b_risk_cap = float(bucket_max_open_risk_pct) / 100.0
            b_new_risk = b_risk_cap * equity - bucket_open_risk
            max_new_risk = min(max_new_risk, b_new_risk)
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
# P14-B2 — Strategy Risk Controller: 5 họ quản lý rủi ro (legacy, trend, breakout, mean_reversion, dca)
# Nguồn sự thật duy nhất cho phân loại, luật hợp lệ, điểm neo SL, thoát lệnh, và phân bổ danh mục.
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RiskIssue:
    code: str
    message_vi: str
    suggestion: str


@dataclass(frozen=True)
class RiskProfile:
    name: str
    label_vi: str
    description: str
    sl_anchor: str          # "avg" | "entry" | "last_layer" | "none"
    sl_required: bool
    dca_mode: str           # "allowed" | "forbidden" | "limited" | "required"
    dca_max_limit: int      # 0 nếu forbidden/allowed, 2 nếu limited
    exits_allowed: Tuple[str, ...]
    exits_required_any: Tuple[str, ...]
    sizing_default: str     # "margin_pct" | "risk"
    reentry_rule: str
    portfolio_bucket: str


RISK_PROFILES: Dict[str, RiskProfile] = {
    "legacy": RiskProfile(
        name="legacy",
        label_vi="Hiện tại (Legacy)",
        description="Giữ nguyên hành vi hiện tại của hệ thống, không áp luật rủi ro bổ sung (bit-identical).",
        sl_anchor="avg",
        sl_required=False,
        dca_mode="allowed",
        dca_max_limit=0,
        exits_allowed=("signal", "sl", "tp", "trail", "timeout"),
        exits_required_any=(),
        sizing_default="margin_pct",
        reentry_rule="Hành vi hiện tại",
        portfolio_bucket="legacy",
    ),
    "trend": RiskProfile(
        name="trend",
        label_vi="Theo xu hướng (Trend)",
        description="Giao dịch theo xu hướng: không dùng DCA ngược chiều, bắt buộc có cắt lỗ hoặc trailing stop.",
        sl_anchor="entry",
        sl_required=False,
        dca_mode="forbidden",
        dca_max_limit=0,
        exits_allowed=("signal", "trail", "sl", "tp", "timeout"),
        exits_required_any=("sl", "trail"),
        sizing_default="risk",
        reentry_rule="Sự kiện tín hiệu + cooldown 1 nến",
        portfolio_bucket="trend",
    ),
    "breakout": RiskProfile(
        name="breakout",
        label_vi="Phá vỡ vùng (Breakout)",
        description="Giao dịch bứt phá ngưỡng: không DCA, bắt buộc cắt lỗ cứng và ít nhất 1 cơ chế trailing hoặc timeout.",
        sl_anchor="entry",
        sl_required=True,
        dca_mode="forbidden",
        dca_max_limit=0,
        exits_allowed=("sl", "trail", "timeout", "signal"),
        exits_required_any=("trail", "timeout"),
        sizing_default="risk",
        reentry_rule="Sự kiện tín hiệu",
        portfolio_bucket="breakout",
    ),
    "mean_reversion": RiskProfile(
        name="mean_reversion",
        label_vi="Đảo chiều về TB (Mean Reversion)",
        description="Đánh hồi quy trung bình: bắt buộc SL, giới hạn tối đa 2 tầng DCA, mọi tầng DCA phải nằm trước SL.",
        sl_anchor="avg",
        sl_required=True,
        dca_mode="limited",
        dca_max_limit=2,
        exits_allowed=("tp", "signal", "sl", "timeout"),
        exits_required_any=(),
        sizing_default="risk",
        reentry_rule="Sự kiện tín hiệu",
        portfolio_bucket="mean_reversion",
    ),
    "dca": RiskProfile(
        name="dca",
        label_vi="Bình quân giá (DCA)",
        description="Dồn lệnh kéo giá trung bình: bắt buộc >= 1 tầng DCA, tầng cuối nằm trước SL hoặc neo sau tầng cuối.",
        sl_anchor="last_layer",
        sl_required=False,
        dca_mode="required",
        dca_max_limit=0,
        exits_allowed=("tp", "signal", "timeout", "sl"),
        exits_required_any=(),
        sizing_default="margin_pct",
        reentry_rule="Sau khi đóng rổ",
        portfolio_bucket="dca",
    ),
}


def get_risk_profile(name_or_alias: str) -> RiskProfile:
    """Lấy profile theo tên họ (mặc định 'legacy' nếu không tìm thấy)."""
    key = str(name_or_alias or "legacy").lower().strip()
    return RISK_PROFILES.get(key, RISK_PROFILES["legacy"])


def validate_strategy_risk(params: Any, profile_name: Optional[str] = None) -> List[RiskIssue]:
    """Kiểm tra tính hợp lệ của tham số chiến lược theo Risk Profile đã chọn."""
    if isinstance(params, dict):
        p_dict = params
        def _get(k, d=None):
            return p_dict.get(k, d)
    else:
        def _get(k, d=None):
            return getattr(params, k, d)

    p_name = profile_name or _get("risk_profile") or "legacy"
    profile = get_risk_profile(str(p_name))

    if profile.name == "legacy":
        return []

    issues: List[RiskIssue] = []

    sl_rate = float(_get("stop_loss_rate") or 0.0)
    trail = float(_get("trailing_stop") or 0.0)
    timeout = int(_get("timeout") or 0)
    dca_layers = int(_get("dca_max_layers") or 0)
    dca_step = float(_get("dca_step_pct") or 0.0)
    dca_steps = [float(x) for x in (_get("dca_steps") or [])]
    if not dca_steps and dca_layers > 0 and dca_step > 0:
        dca_steps = [dca_step] * dca_layers
    has_dca = dca_layers > 0 or len(dca_steps) > 0 or dca_step > 0

    if profile.name == "trend":
        if has_dca:
            issues.append(RiskIssue(
                code="TREND_DCA_FORBIDDEN",
                message_vi="Chiến lược theo xu hướng (trend) không được dùng DCA để tránh gồng lỗ ngược xu hướng.",
                suggestion="Bỏ tham số dca_max_layers hoặc đặt dca_max_layers = 0.",
            ))
        if sl_rate <= 0.0 and trail <= 0.0:
            issues.append(RiskIssue(
                code="TREND_EXIT_REQUIRED",
                message_vi="Chiến lược trend bắt buộc có cắt lỗ (stop_loss_rate > 0) hoặc trailing stop (trailing_stop > 0).",
                suggestion="Khai báo stop_loss_rate > 0 hoặc trailing_stop > 0.",
            ))

    elif profile.name == "breakout":
        if has_dca:
            issues.append(RiskIssue(
                code="BREAKOUT_DCA_FORBIDDEN",
                message_vi="Chiến lược phá vỡ (breakout) không được dùng DCA.",
                suggestion="Bỏ tham số dca_max_layers hoặc đặt dca_max_layers = 0.",
            ))
        if sl_rate <= 0.0:
            issues.append(RiskIssue(
                code="BREAKOUT_SL_REQUIRED",
                message_vi="Chiến lược breakout bắt buộc có mức cắt lỗ cứng (stop_loss_rate > 0).",
                suggestion="Khai báo stop_loss_rate > 0.",
            ))
        if trail <= 0.0 and timeout <= 0:
            issues.append(RiskIssue(
                code="BREAKOUT_TIMEOUT_OR_TRAIL_REQUIRED",
                message_vi="Chiến lược breakout cần có trailing_stop hoặc timeout để đóng lệnh khi bứt phá thất bại.",
                suggestion="Thêm trailing_stop > 0 hoặc timeout > 0.",
            ))

    elif profile.name == "mean_reversion":
        if sl_rate <= 0.0:
            issues.append(RiskIssue(
                code="REVERT_SL_REQUIRED",
                message_vi="Chiến lược đảo chiều (mean_reversion) bắt buộc có stop_loss_rate để bảo vệ vốn khi thị trường vào xu hướng mạnh.",
                suggestion="Khai báo stop_loss_rate > 0.",
            ))
        if dca_layers > 2 or len(dca_steps) > 2:
            issues.append(RiskIssue(
                code="REVERT_DCA_LIMIT_EXCEEDED",
                message_vi="Chiến lược mean_reversion chỉ cho phép tối đa 2 tầng DCA (dca_max_layers <= 2).",
                suggestion="Đặt dca_max_layers <= 2.",
            ))
        if len(dca_steps) > 0 and sl_rate > 0.0:
            dca_depth = sum(dca_steps)
            if dca_depth >= sl_rate:
                issues.append(RiskIssue(
                    code="REVERT_DCA_BEYOND_SL",
                    message_vi=f"Tổng khoảng lùi các tầng DCA ({dca_depth:.2f}%) nằm sau hoặc trùng với mức Stop Loss ({sl_rate:.2f}%).",
                    suggestion="Đặt stop_loss_rate lớn hơn tổng khoảng lùi các tầng DCA, hoặc giảm dca_step_pct.",
                ))

    elif profile.name == "dca":
        if dca_layers < 1 and len(dca_steps) < 1:
            issues.append(RiskIssue(
                code="DCA_LAYERS_REQUIRED",
                message_vi="Chiến lược họ DCA bắt buộc có ít nhất 1 tầng dồn lệnh (dca_max_layers >= 1).",
                suggestion="Đặt dca_max_layers >= 1 kèm dca_step_pct.",
            ))
        sl_anchor = str(_get("sl_anchor") or "last_layer").lower()
        if sl_anchor == "avg" and sl_rate > 0.0 and len(dca_steps) > 0:
            dca_depth = sum(dca_steps)
            if dca_depth >= sl_rate:
                issues.append(RiskIssue(
                    code="DCA_SL_CONFLICT",
                    message_vi=f"Mức Stop Loss ({sl_rate:.2f}% từ TB) nông hơn hoặc cắt ngang các tầng DCA (độ sâu {dca_depth:.2f}%).",
                    suggestion="Dùng neo sl_anchor='last_layer' (kèm sl_beyond_last_pct) hoặc nâng stop_loss_rate lớn hơn độ sâu tầng cuối.",
                ))
    return issues


# ══════════════════════════════════════════════════════════════════════════
# P9.4b T4 — SlotSpec: chuẩn hoá tham số một slot (flow) cho kernel, NGUYÊN VĂN từ PositionTracker.__init__ (cùng mặc định, cùng trường dẫn xuất,
# cùng ngoại lệ + thông báo + thứ tự kiểm). PositionTracker dựng từ SlotSpec nên chỉ còn MỘT bản logic này.
# ══════════════════════════════════════════════════════════════════════════
class SlotSpec:
    """Tham số đã chuẩn hoá + trạng thái khởi đầu của một slot. Tên thuộc tính trùng PositionTracker (pack_slots đọc được cả hai)."""

    def __init__(self, account_id: int, campaign_id: int, symbol: str, flow_name: str, params: "StrategyParams",
                 pos_type: PositionType, initial_capital: float = DEFAULT_CAPITAL, entry_equity: Optional[float] = None):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.params = params
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG

        self.risk_profile = str(getattr(params, "risk_profile", "legacy") or "legacy").lower()
        profile = get_risk_profile(self.risk_profile)
        if self.risk_profile != "legacy":
            issues = validate_strategy_risk(params, self.risk_profile)
            if issues:
                raise ValueError(f"Flow '{flow_name}': vi phạm quy tắc Risk Profile '{self.risk_profile}' — {issues[0].message_vi} (Gợi ý: {issues[0].suggestion})")

        self.sl_anchor = str(getattr(params, "sl_anchor", "") or profile.sl_anchor or "avg").lower()
        self.sl_beyond_last_pct = max(0.0, float(getattr(params, "sl_beyond_last_pct", 0.0) or 0.0))
        # sl_anchor_mode: 0 = avg (% từ giá TB, legacy bit-identical), 1 = neo tuyệt đối (entry hoặc last_layer)
        self.sl_anchor_mode = 1 if (self.sl_anchor in ("entry", "last_layer") and self.risk_profile != "legacy") else 0

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
        self.signal_mode = str(getattr(params, "signal_mode", "event") or "event").lower()    # "event" | "level": core/backtest.py::entry_event_mask
        if self.signal_mode not in ("event", "level"):
            raise ValueError(f"signal_mode phải là 'event' hoặc 'level', nhận '{self.signal_mode}'")
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
