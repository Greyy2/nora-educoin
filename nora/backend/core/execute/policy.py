# P9-SHIM — P9.4 (ADR-P9): module đã chuyển sang backend.core.position_size; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.execute.policy` == `backend.core.position_size` (cùng một module: cache/trạng thái module-level chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.core import position_size as _target

sys.modules[__name__] = _target
