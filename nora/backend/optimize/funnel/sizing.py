"""Khối lượng sống sót (S5): tìm nhị phân hệ số vốn s ∈ [S_MIN, S_MAX] rồi XÁC NHẬN bằng chạy thật ở s.

Quy đổi s -> khối lượng thật: các chiến lược của sổ dùng sizing="risk" (khối lượng = vốn × risk_per_trade% / (SL% + chi phí)), nên
`risk_per_trade_pct = BASE_RISK_PER_TRADE_PCT × s` làm khối lượng (qty) mọi lệnh tỉ lệ với s. Với sizing="margin_pct" thì nhân
`order_size_pct` với s (cùng ý nghĩa). Không tuyệt đối tỉ lệ vì trần danh nghĩa (max_notional_pct), trần tổng danh nghĩa của danh mục và
đòn bẩy tối đa chặn lệnh lớn -> lợi suất ngày ở size s không đúng bằng s × lợi suất ngày ở s = 1. Vì thế tìm nhị phân trên chuỗi ngày nhân s chỉ cho
ứng viên; kết luận chỉ khi chạy lại backtest + WFA + Monte Carlo THẬT ở s qua (xác nhận); trượt thì hạ s từng bước rồi xác nhận lại.
"""
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import gates

Check = Callable[[float], Dict[str, Any]]   # s -> {"passed": bool, "p_mdd_ge_30": %, "stress_max_mdd": %}


def floor_scale(s: float, step: float = 0.01) -> float:
    """Làm tròn XUỐNG theo bước 0,01 (không bao giờ vượt mức đã kiểm)."""
    return round(math.floor(s / step + 1e-9) * step, 2)


def scale_position(position: Dict[str, Any], s: float) -> Dict[str, Any]:
    """Bản sao `position` với khối lượng nhân s (xem docstring module)."""
    out = dict(position)
    if str(out.get("sizing") or "margin_pct").lower() == "risk":
        out["risk_per_trade_pct"] = round(float(out.get("risk_per_trade_pct") or gates.BASE_RISK_PER_TRADE_PCT) * s, 6)
    else:
        out["order_size_pct"] = round(float(out.get("order_size_pct") if out.get("order_size_pct") is not None else 100.0) * s, 6)
    return out


def risk_for_scale(s: float) -> float:
    """Rủi ro/lệnh (% vốn) ở hệ số s cho các chiến lược của sổ (sizing="risk")."""
    return round(gates.BASE_RISK_PER_TRADE_PCT * s, 6)


def search_scale(check: Check, lo: Optional[float] = None, hi: Optional[float] = None, tol: Optional[float] = None
                 ) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Hệ số s lớn nhất ∈ [lo, hi] mà check(s)["passed"] (giả định đơn điệu: s nhỏ hơn luôn dễ qua hơn). -> (s hoặc None, các bước).
    Thử hi trước (qua -> xong), rồi lo (trượt -> None = s < lo), rồi chia đôi tới khi hi - lo <= tol. s trả về = lo đã qua, làm tròn xuống 0,01."""
    lo = gates.S5_S_MIN if lo is None else lo
    hi = gates.S5_S_MAX if hi is None else hi
    tol = gates.S5_TOLERANCE if tol is None else tol
    steps: List[Dict[str, Any]] = []

    def probe(s: float) -> bool:
        r = check(s)
        steps.append({"s": round(s, 4), "passed": bool(r["passed"]), "p_mdd_ge_30": r.get("p_mdd_ge_30"), "stress_max_mdd": r.get("stress_max_mdd")})
        return bool(r["passed"])

    if probe(hi):
        return floor_scale(hi), steps
    if not probe(lo):
        return None, steps
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if probe(mid):
            lo = mid
        else:
            hi = mid
    return floor_scale(lo), steps


def confirm_with_stepdown(s0: float, confirm: Callable[[float], Dict[str, Any]], step: Optional[float] = None,
                          max_tries: Optional[int] = None, s_min: Optional[float] = None) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Xác nhận ở s0; trượt thì hạ s (s <= 1: trừ step; s > 1: nhân (1 − S5_CONFIRM_REL_STEP)), tối đa max_tries lần thử, s không xuống
    dưới s_min. confirm(s) -> {"passed": bool, ...}.
    -> (s đã xác nhận hoặc None, các lần thử [{s, passed, ...}]). Hết lượt/ s < s_min -> None."""
    step = gates.S5_CONFIRM_STEP if step is None else step
    max_tries = gates.S5_CONFIRM_MAX_TRIES if max_tries is None else max_tries
    s_min = gates.S5_S_MIN if s_min is None else s_min
    attempts: List[Dict[str, Any]] = []
    s = s0
    for _ in range(max_tries):
        if s < s_min - 1e-9:
            break
        r = confirm(s)
        attempts.append({"s": s, **r})
        if r["passed"]:
            return s, attempts
        s = round(s - step, 4) if s <= 1.0 + 1e-9 else max(1.0, round(s * (1.0 - gates.S5_CONFIRM_REL_STEP), 2))
    return None, attempts
