"""Quy tắc rủi ro danh mục — NGUỒN DUY NHẤT cho sim/paper/live: hàm thuần, đầu vào là số thường (không đối tượng sổ vốn/tracker),
nên PaperBook, runner và bot sàn dùng chung với số của riêng mình.

Bản numba trong core/backtest/kernel.py giữ bản sao riêng của các quy tắc này (để chạy nhanh); hai bản được khoá bằng test parity
(test/test_risk_engine.py, test/test_kernel_parity.py) — sửa quy tắc ở đây thì phải sửa kernel và chạy lại parity.

Thứ tự phép toán float và cấu trúc điều kiện giữ y nguyên code gốc của PaperBook.step_bar (so sánh tường minh, không dùng max/min,
trừ max(0.0, room)) để kết quả trùng từng bit.
"""
from typing import NamedTuple

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
