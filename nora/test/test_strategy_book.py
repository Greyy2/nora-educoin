"""Sổ chiến lược: tham số theo chiến lược (dùng chung mọi tài sản), xuất sổ + cấu hình testnet danh mục.

Dữ liệu giả lập 3 tài sản perp (không gọi mạng). Kiểm:
- chia giai đoạn đúng thứ tự (dev1 < dev2 < holdout), luồng A→B→C→D chạy hết và ghi báo cáo;
- MỌI tài sản dùng cùng một bộ tham số của chiến lược (không có tham số theo tài sản);
- sổ xuất ra mô tả đúng quy tắc khối lượng theo rủi ro + giới hạn danh mục đã mô phỏng.
"""
import pathlib

from backend.models.storage import alpha_run_dir
import importlib.util
import json

import numpy as np
import pandas as pd
import pytest

from data_helpers import save_synthetic

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

T0 = 1_700_006_400_000
SYMS = ("AAA", "BBB", "CCC")


def _series(days, seed, vol):
    n = days * 1440
    rng = np.random.default_rng(seed)
    r = rng.normal(0.00002, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": o,
                         "high": np.maximum(o, c) * (1 + vol / 3), "low": np.minimum(o, c) * (1 - vol / 3),
                         "close": c, "volume": 10.0})


@pytest.fixture
def market(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    for k, sym in enumerate(SYMS):
        df = _series(70, 20 + k, 0.0008 * (k + 1))
        save_synthetic(symbol=sym, output_dir=str(root / "cex"), df_1m_raw=df)
    return root


def _load_script(name):
    from job_modules import job_path
    path = job_path(name)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = mod  # để ProcessPoolExecutor pickle được hàm của script
    spec.loader.exec_module(mod)
    return mod


def _small_book(monkeypatch):
    from backend import strategies as sb
    from backend.alpha.compile import cond, f, tree_p
    cands = [
        {"id": "t_long", "family": "x", "side": "LONG", "description": "test",
         "tree": cond((f("15m", "rsi_14"), "<", tree_p("lo", 40))), "position": {},
         "space": {"sig.lo": [35, 40], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}},
        {"id": "t_short", "family": "x", "side": "SHORT", "description": "test",
         "tree": cond((f("15m", "rsi_14"), ">", 60)), "position": {"atr_frame": "4h"},
         "space": {"stop_loss_rate": [1.5, 2.5], "trailing_stop": [2.0], "timeout": [720]}},
    ]
    monkeypatch.setattr(sb, "UNIVERSE", list(SYMS))
    monkeypatch.setattr(sb, "CANDIDATES", cands)
    return sb


def _book_report(holdout_pass):
    return {
        "windows": {"start": "a", "dev1_end": "b", "dev2_end": "c", "end": "d"}, "gates": {},
        "candidates": {"trend_long": {"accepted": True}, "trend_short": {"accepted": False}},
        "book": {"strategies": [{"id": "trend_long", "params": {"sig.adx_min": 25, "stop_loss_rate": 2.5, "timeout": 4320}}],
                 "risk_per_trade_pct": 0.75, "risk": {"max_positions": 8, "max_per_symbol": 1,
                                                       "max_gross_exposure": 3.0, "kill_switch_dd_pct": 30.0},
                 "risk_scale_bootstrap": {}, "dev2_base_risk": {}, "final": {}, "holdout_pass": holdout_pass},
    }


def test_json_default_numpy_types():
    from backend.models.storage import json_default
    obj = {"b": np.bool_(False), "i": np.int64(3), "f": np.float64(1.5), "nan": np.float32("nan"),
           "inf": np.float32("inf"), "a": np.array([1, 2]), "t": pd.Timestamp("2026-01-02")}
    out = json.loads(json.dumps(obj, default=json_default))
    assert out == {"b": False, "i": 3, "f": 1.5, "nan": None, "inf": None, "a": [1, 2], "t": "2026-01-02T00:00:00"}
    assert json.loads(json.dumps({"x": object()}, default=json_default))["x"].startswith("<object")
