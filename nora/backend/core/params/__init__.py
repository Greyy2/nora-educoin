# P9-SHIM — P9.4 (ADR-P9): `backend.core.params` là FILE core/params.py; thư mục gói này còn giữ các module chưa chuyển (presets, modes).
"""Stub gói: nạp core/params.py làm module `backend.core.params` (một đối tượng duy nhất, có __path__ để `backend.core.params.<module chưa chuyển>` vẫn import được).
Xoá file này (và thư mục gói) khi các module còn lại đã chuyển (P9.10)."""
import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(__name__, os.path.join(os.path.dirname(_here), "params.py"), submodule_search_locations=[_here])
_mod = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _mod
_spec.loader.exec_module(_mod)
