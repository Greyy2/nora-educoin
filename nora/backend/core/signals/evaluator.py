# P9-SHIM — P9.4 part 2 (ADR-P9): module đã chuyển sang backend.core.signal; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.signals.evaluator` == `backend.core.signal` (cùng một module: cache/trạng thái module-level — vd. kernels.PROGRAMS/REGISTRY — chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.core import signal as _target

sys.modules[__name__] = _target
