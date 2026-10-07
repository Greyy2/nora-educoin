# P9-SHIM — P9.4 (ADR-P9): `backend.core.backtest` là FILE core/backtest.py; thư mục gói này còn giữ các module chưa chuyển (run, custom_run, tick_run, edu_precompute).
"""Stub gói: nạp core/backtest.py làm module `backend.core.backtest` (một đối tượng duy nhất, có __path__ để `backend.core.backtest.<module chưa chuyển>` vẫn import được).
Xoá file này (và thư mục gói) khi các module còn lại đã chuyển (P9.10)."""
import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(__name__, os.path.join(os.path.dirname(_here), "backtest.py"), submodule_search_locations=[_here])
_mod = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _mod
_spec.loader.exec_module(_mod)
