# P9-SHIM — P9.4 part 2 (ADR-P9): module đã chuyển sang backend.core.indicator; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.strategy.pydsl.spec` == `backend.core.indicator` (cùng một module: cache/trạng thái module-level — vd. kernels.PROGRAMS/REGISTRY — chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.core import indicator as _target

sys.modules[__name__] = _target
