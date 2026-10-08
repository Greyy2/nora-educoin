# P9-SHIM — P9.5 (ADR-P9): module đã chuyển sang backend.carlo.carlo; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.carlo.monte_carlo` == `backend.carlo.carlo` (cùng một module: cache/trạng thái module-level chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.carlo import carlo as _target

sys.modules[__name__] = _target
