"""
test_optimization_plumbing.py — hạ tầng cho bước B (tối ưu) và A3/A4 (perp, phí pool).

- Tham số tín hiệu {"param": ...}: thay đúng, thiếu/sai kiểu -> lỗi rõ.
- WFA nhận param_candidates (danh sách tổ hợp cụ thể, gồm cả "sig.*"), fold chọn đúng một ứng viên.
- Ký hiệu "BTC@perp": engine dùng dữ liệu perp + funding; data_symbol trả nguồn giá đúng.
- DEX dùng phí pool đã xác minh trong manifest thay cho mặc định.
- Script tối ưu: chia cửa sổ không chồng lấn, lấy mẫu cấu hình tái lập được.
"""
import importlib.util

import numpy as np
import pandas as pd
import pytest

from backend.core.params import collect_placeholders, resolve_placeholders, split_params
from backend.crawl.store import save_resampled_dataset

T0 = 1_700_006_400_000
D = 86_400_000


def _rw(days, seed=1):
    n = days * 1440
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": o,
                         "high": np.maximum(o, c) * 1.0004, "low": np.minimum(o, c) * 0.9996, "close": c, "volume": 5.0})


def test_placeholders_resolve_and_errors():
    tree = [[[{"frame": "5m", "column": "rsi_14"}, "<", {"param": "rsi_lo", "default": 30}]]]
    assert collect_placeholders(tree) == {"rsi_lo": 30.0}
    assert resolve_placeholders(tree, {})[0][0][2] == 30.0
    assert resolve_placeholders(tree, {"rsi_lo": 22})[0][0][2] == 22.0
    with pytest.raises(ValueError):
        resolve_placeholders([{"param": "x"}], {})
    with pytest.raises(ValueError):
        resolve_placeholders(tree, {"rsi_lo": "abc"})
    assert split_params({"sig.a": 1, "leverage": 2}) == ({"a": 1}, {"leverage": 2})


@pytest.fixture
def perp_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    spot = _rw(40, 1)
    save_resampled_dataset(symbol="BTC", output_dir=str(root / "cex"), df_1m_raw=spot, pool_address="s", crawl_ok=True,
                           requested_start_ts=int(spot.open_time.min()), requested_end_ts=int(spot.open_time.max()),
                           extra_meta={"venue": "cex", "exchange": "binance", "checksums_verified": True})
    perp = spot.assign(open=spot.open * 1.001, high=spot.high * 1.001, low=spot.low * 1.001, close=spot.close * 1.001)
    save_resampled_dataset(symbol="perp", output_dir=str(root / "cex" / "BTC"), df_1m_raw=perp, pool_address="p",
                           crawl_ok=True, requested_start_ts=int(perp.open_time.min()),
                           requested_end_ts=int(perp.open_time.max()),
                           extra_meta={"venue": "cex", "exchange": "binance_usdm", "market": "perp",
                                       "checksums_verified": True})
    ft = T0 + np.arange(1, 40 * 3) * 8 * 3_600_000
    pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001}).to_pickle(root / "cex" / "BTC" / "perp" / "funding.pkl")
    return str(root)


def test_dex_uses_verified_pool_fee(tmp_path, monkeypatch):
    from backend.core.params import build_params
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw(35)
    save_resampled_dataset(symbol="POOL", output_dir=str(root / "dex"), df_1m_raw=df, pool_address="0x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                           extra_meta={"venue": "dex", "pool_fee_rate": 0.0005})
    from backend.core.models import data_source
    from backend.core.params import manifest_pool_fee
    params = build_params("LONG_x", {"match": [], "stop": []}, "LONG", {}, "dex", manifest_pool_fee(data_source().manifest("POOL")))
    assert params.fee_rate == 0.0005 and params.maker_fee_rate == 0.0005
    assert build_params("LONG_x", {"match": [], "stop": []}, "LONG", {}, "dex", None).fee_rate == 0.003


def _load_script(name):
    from job_modules import job_path
    path = job_path(name)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


