# P9-SHIM — P9.2 (ADR-P9): module đã chuyển sang backend.crawl.cex; đường dẫn cũ là VIEW trong suốt của cùng module (gỡ ở P9.10).
"""Shim tương thích: `backend.core.data.okx_crawler` -> `backend.crawl.cex`.

Bốn tên trùng với crawler Binance được đổi phía OKX trong cex.py; view này dịch ngược tên cũ (đọc, ghi/monkeypatch, xoá) nên
`run_job`, `crawl`, `crawl_funding`, `DEFAULT_CACHE_DIR` của đường cũ vẫn là bản OKX, mọi tên khác đi thẳng tới cex (một bản trạng thái duy nhất).
"""
import sys
import types

from backend.crawl import cex as _target

_RENAMED = {
    "crawl": "okx_crawl",
    "crawl_funding": "okx_crawl_funding",
    "run_job": "okx_run_job",
    "DEFAULT_CACHE_DIR": "OKX_DEFAULT_CACHE_DIR",
}


class _OkxView(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(_target, _RENAMED.get(name, name))

    def __setattr__(self, name, value):
        if name.startswith("__") and name.endswith("__"):
            return super().__setattr__(name, value)
        setattr(_target, _RENAMED.get(name, name), value)

    def __delattr__(self, name):
        delattr(_target, _RENAMED.get(name, name))

    def __dir__(self):
        return sorted(set(dir(_target)) | set(_RENAMED))


sys.modules[__name__] = _OkxView(__name__, __doc__)
