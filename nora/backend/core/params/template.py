# P9-SHIM — P9.4 (ADR-P9): module đã chuyển sang backend.core.params; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.params.template` == `backend.core.params` (cùng một module: cache/trạng thái module-level chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.core import params as _target

sys.modules[__name__] = _target
