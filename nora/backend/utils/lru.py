# P9-SHIM — P9.2 (ADR-P9): module đã chuyển sang backend.crawl.store; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.utils.lru` == `backend.crawl.store` (cùng một module: cache/trạng thái module-level chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.crawl import store as _target

sys.modules[__name__] = _target
