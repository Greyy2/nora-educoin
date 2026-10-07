# P9-SHIM — P9.4 part 2 (ADR-P9): build_plan/Plan/... đã chuyển sang backend.core.backtest, hằng số profile sang backend.core.params (gỡ ở P9.10).
"""Shim tương thích: hằng số (NORA_DEFAULTS, FRAMES, FRAME_ORDER, RUN_FRAME) lấy từ core.params; các tên kế hoạch (Plan, build_plan, base_name, leg_level, ...)
nạp LƯỜI từ core.backtest (PEP 562) để import `profiles` chỉ để lấy hằng số/`FRAMES` không kéo cả engine numba như trước."""
from backend.core.params import FRAME_ORDER, FRAMES, NORA_DEFAULTS, RUN_FRAME  # noqa: F401

_BACKTEST_NAMES = ("Plan", "base_name", "leg_level", "build_plan", "_ref", "_tree", "_leg_signals", "_check_position")


def __getattr__(name):
    if name in _BACKTEST_NAMES:
        from backend.core import backtest
        return getattr(backtest, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
