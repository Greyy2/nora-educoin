# P9-SHIM — P9.2 (ADR-P9): module đã chuyển sang backend.crawl.cex; đường dẫn cũ là ALIAS của cùng một đối tượng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.data.crawler` == `backend.crawl.cex` (cùng một module: cache/trạng thái module-level chỉ có một bản; monkeypatch qua đường cũ có hiệu lực)."""
import sys

from backend.crawl import cex as _target

sys.modules[__name__] = _target
