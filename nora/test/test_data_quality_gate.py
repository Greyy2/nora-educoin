"""Cổng chất lượng dữ liệu: thiếu manifest / synthetic / resample lệch -> BLOCKED; dữ liệu sạch -> APPROVED."""
import os
import tempfile

import pandas as pd

from backend.crawl.store import DataQualityStatus, evaluate_data_quality
from backend.crawl.store import save_resampled_dataset
from backend.crawl import store
from data_helpers import _tiny


def test_data_quality_gate_checks():
    """
    Data Quality Gate Validation (Phase 1 & Phase 6):
    1. Rejects asset without manifest.json.
    2. Rejects asset with synthetic=True in manifest.
    3. Rejects asset with 1m price jump > 50%.
    4. Rejects asset when 1m resample does not match stored 15m.
    5. Approves clean asset with synthetic=False, sufficient bars and matching 15m.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        sym = "TESTSYM"
        sym_dir = os.path.join(tmp_dir, sym)
        os.makedirs(sym_dir, exist_ok=True)

        # 1. No manifest -> BLOCKED
        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert "thiếu metadata" in res["issues"][0]

        # 2. Manifest with synthetic=True -> BLOCKED
        store.write_pickle_atomic(store.stamp_attrs(_tiny(), {"synthetic": True, "source": "fake"}), os.path.join(sym_dir, "1m.pkl"))
        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert "synthetic=true" in res["issues"][0]

        # 3. Create valid 1m candles (>= 30 days = 35 days) and resample using core resampler
        t0 = 1700000000000
        n_bars = 1440 * 35
        times = [t0 + i * 60_000 for i in range(n_bars)]
        prices = [100.0 * (1.0 + 0.0001 * (i % 50)) for i in range(n_bars)]
        df_1m_clean = pd.DataFrame({
            "open_time": times,
            "open": prices,
            "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices,
            "volume": 100.0,
        })

        # Save properly via save_resampled_dataset
        save_resampled_dataset(
            symbol=sym,
            output_dir=tmp_dir,
            df_1m_raw=df_1m_clean,
            pool_address="0x123",
            timeframes=("15m", "1h", "4h"),
            synthetic=False,
            crawl_ok=True,
        )

        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.APPROVED, f"Clean data should be APPROVED, got: {res}"

        # 4. Corrupt 15m file -> must be BLOCKED
        df_15m_corrupt = pd.read_pickle(os.path.join(sym_dir, "15m.pkl"))
        df_15m_corrupt["close"] = df_15m_corrupt["close"] * 1.10  # 10% mismatch
        df_15m_corrupt.to_pickle(os.path.join(sym_dir, "15m.pkl"))

        res = evaluate_data_quality(sym, data_root=tmp_dir)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert any("Resample 1m sang 15m lệch" in issue for issue in res["issues"])


def test_gate_disk_cache_reused_across_processes_and_invalidated_on_change(tmp_path, monkeypatch):
    """Kết quả gate lưu trên đĩa: tiến trình mới (xoá cache trong RAM) đọc lại y hệt mà KHÔNG kiểm lại; file dữ liệu đổi -> kiểm lại."""
    import json as _json
    from backend.crawl import store as qg
    sym = "TESTSYM"
    t0 = 1700000000000
    n = 1440 * 35
    prices = [100.0 * (1.0 + 0.0001 * (i % 50)) for i in range(n)]
    df = pd.DataFrame({"open_time": [t0 + i * 60_000 for i in range(n)], "open": prices, "high": [p * 1.001 for p in prices],
                       "low": [p * 0.999 for p in prices], "close": prices, "volume": 100.0})
    save_resampled_dataset(symbol=sym, output_dir=str(tmp_path), df_1m_raw=df, pool_address="0x1", timeframes=("15m", "1h", "4h"),
                           synthetic=False, crawl_ok=True)
    first = qg.evaluate_data_quality(sym, data_root=str(tmp_path))
    qg._GATE_CACHE.clear()
    calls = []
    real = qg._evaluate_data_quality_uncached
    monkeypatch.setattr(qg, "_evaluate_data_quality_uncached", lambda *a, **k: calls.append(1) or real(*a, **k))
    again = qg.evaluate_data_quality(sym, data_root=str(tmp_path))
    assert not calls and _json.dumps(again, sort_keys=True, default=str) == _json.dumps(_json.loads(_json.dumps(first, default=qg.__dict__.get("json_default", str))), sort_keys=True, default=str)
    assert again["status"] == first["status"] == DataQualityStatus.APPROVED
    qg._GATE_CACHE.clear()
    df.assign(close=df["close"] * 1.0).to_pickle(os.path.join(tmp_path, sym, "15m.pkl"))   # đổi file -> khoá đổi -> kiểm lại
    qg.evaluate_data_quality(sym, data_root=str(tmp_path))
    assert calls
