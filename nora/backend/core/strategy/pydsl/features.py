# P9-SHIM — P9.4 part 2 (ADR-P9): module đã chuyển sang backend.core.indicator; đường dẫn cũ tái xuất MỌI tên của module gộp (gỡ ở P9.10).
"""Shim tương thích: `backend.core.strategy.pydsl.features` tái xuất tên của `backend.core.indicator`. Không alias nguyên module vì `features.evaluate` và `ops.evaluate` là hai hàm khác nhau,
nay đổi tên `evaluate_feature` / `evaluate_op` trong module gộp. FEATURES/OPS/KERNEL REGISTRY là cùng đối tượng với module gộp."""
from backend.core import indicator as _t

globals().update({_k: _v for _k, _v in vars(_t).items() if not _k.startswith("__")})
evaluate = _t.evaluate_feature
