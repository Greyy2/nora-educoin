"""Kiểm thử sandbox an toàn cho Native Nautilus (P17 T4).

Đảm bảo kiểm tĩnh AST chặn tất cả các import, builtins và dunder nguy hiểm
trước khi bất kỳ lệnh exec nào được thực thi.
"""
import pytest
from backend.alpha.route import verify_native_sandbox
from backend.signal.nodes import DslError


def test_sandbox_allowed_imports():
    safe_code = """
import numpy as np
import pandas as pd
import math
import statistics
import collections
import dataclasses
import typing
import decimal
import datetime
import enum
from nautilus_trader.trading.strategy import Strategy

class SafeStrategy(Strategy):
    def on_bar(self, bar):
        pass
"""
    # Không ném lỗi
    verify_native_sandbox(safe_code)


@pytest.mark.parametrize("banned_module", [
    "os", "sys", "subprocess", "socket", "shutil",
    "pathlib", "importlib", "ctypes", "pickle", "requests", "urllib"
])
def test_sandbox_banned_imports(banned_module):
    bad_code = f"""
import {banned_module}
from nautilus_trader.trading.strategy import Strategy

class MyStrategy(Strategy):
    pass
"""
    with pytest.raises(DslError) as exc_info:
        verify_native_sandbox(bad_code)
    assert f"Cấm import '{banned_module}'" in str(exc_info.value) or f"Cấm import từ '{banned_module}'" in str(exc_info.value)
    assert exc_info.value.line == 2


@pytest.mark.parametrize("banned_func", [
    "open", "exec", "eval", "compile", "__import__",
    "globals", "locals", "vars", "getattr", "setattr"
])
def test_sandbox_banned_builtins(banned_func):
    bad_code = f"""
from nautilus_trader.trading.strategy import Strategy

class HackStrategy(Strategy):
    def on_bar(self, bar):
        {banned_func}('test')
"""
    with pytest.raises(DslError) as exc_info:
        verify_native_sandbox(bad_code)
    assert f"Cấm gọi hàm nguy hiểm '{banned_func}'" in str(exc_info.value)


def test_sandbox_banned_dunder_attributes():
    bad_code = """
from nautilus_trader.trading.strategy import Strategy

class HackStrategy(Strategy):
    def on_bar(self, bar):
        x = bar.__dict__
"""
    with pytest.raises(DslError) as exc_info:
        verify_native_sandbox(bad_code)
    assert "Cấm truy cập thuộc tính nội bộ '__dict__'" in str(exc_info.value)


def test_sandbox_allowed_dunders():
    ok_code = """
from nautilus_trader.trading.strategy import Strategy

class MyStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.doc = self.__doc__
        self.name = self.__name__
"""
    verify_native_sandbox(ok_code)
