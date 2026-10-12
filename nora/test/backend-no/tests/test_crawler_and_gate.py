# ARCHIVED (P17-T1 B4): kiểm bố cục thư mục pkl / manifest-trong-attrs / staging-promote / Binance của backend.crawl cũ (không còn: dữ liệu = ParquetDataCatalog OKX).
"""
test_crawler_and_gate.py — Đợt 2: Crawler reliability + Data Quality Gate enhancements

Quy tắc: Viết test trước, chạy thấy FAIL, rồi sửa code để PASS.

2.1: UnboundLocalError: minute_pages và crawl_ok=False khi crawl lỗi
2.2: save_resampled_dataset ghi crawl_ok, requested_start_ts, requested_end_ts, coverage_days, coverage_ratio
2.3: Crawler universe lookback pages calculation
2.4: Checkpoint dùng 1m_raw.partial.pkl; gate kiểm tra sha256 của 1m.pkl
2.5: save_ticks_and_sync_candles không sửa .pkl; ghi manifest["ticks"] riêng; has_ticks đọc ticks
"""
import os
import time
import tempfile
import pandas as pd

from backend.crawl.store import save_resampled_dataset
from backend.crawl.store import evaluate_data_quality, DataQualityStatus
from backend.crawl.dex import save_ticks
from backend.crawl.store import has_ticks, manifest_of_dir


def _create_sample_1m_data(n: int = 1440, t0: int = 1700000000000) -> pd.DataFrame:
    """Tạo DataFrame 1m hợp lệ."""
    times = [t0 + i * 60_000 for i in range(n)]
    prices = [100.0 + (i * 0.01) for i in range(n)]
    return pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [10.0] * n,
    })


# ─── 2.1: _process_asset handle exception, minute_pages defined, crawl_ok=False ───


# ─── 2.2: crawl_ok=False → Gate BLOCKED; coverage_days < 30 → NEEDS_MORE_DATA ───

def test_gate_crawl_ok_false_is_blocked():
    """Manifest có crawl_ok == False → Gate phải trả BLOCKED."""
    with tempfile.TemporaryDirectory() as tmp:
        asset = "TESTGATE"
        df = _create_sample_1m_data(n=1440 * 35) # 35 ngày
        save_resampled_dataset(
            symbol=asset,
            output_dir=tmp,
            df_1m_raw=df,
            pool_address="0xpool",
            crawl_ok=False,
        )
        res = evaluate_data_quality(asset, data_root=tmp)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert any("crawl" in str(iss).lower() for iss in res["issues"])


def test_gate_coverage_days_low_needs_more_data():
    """Manifest có coverage_days < 30 → Gate phải trả NEEDS_MORE_DATA."""
    with tempfile.TemporaryDirectory() as tmp:
        asset = "TESTCOV"
        df = _create_sample_1m_data(n=1440 * 10) # 10 ngày
        save_resampled_dataset(
            symbol=asset,
            output_dir=tmp,
            df_1m_raw=df,
            pool_address="0xpool",
            crawl_ok=True,
        )
        res = evaluate_data_quality(asset, data_root=tmp)
        assert res["status"] == DataQualityStatus.NEEDS_MORE_DATA
        assert any("coverage" in str(iss).lower() or "ngày" in str(iss).lower() for iss in res["issues"])


# ─── 2.4: sha256 mismatch → Gate BLOCKED ──────────────────────────────────────

def test_gate_sha256_mismatch_blocked():
    """Nếu 1m.pkl bị sửa sau khi lưu metadata (attrs), Gate phải trả BLOCKED vì digest_1m không khớp."""
    with tempfile.TemporaryDirectory() as tmp:
        asset = "TESTSHA"
        df = _create_sample_1m_data(n=1440 * 35)
        save_resampled_dataset(
            symbol=asset,
            output_dir=tmp,
            df_1m_raw=df,
            pool_address="0xpool",
            crawl_ok=True,
        )
        # Sửa 1 dòng trong 1m.pkl
        pkl_path = os.path.join(tmp, asset, "1m.pkl")
        df_mod = pd.read_pickle(pkl_path)
        df_mod.loc[0, "close"] = df_mod.loc[0, "close"] * 1.5
        df_mod.to_pickle(pkl_path)

        res = evaluate_data_quality(asset, data_root=tmp)
        assert res["status"] == DataQualityStatus.BLOCKED
        assert any("digest_1m" in str(iss).lower() for iss in res["issues"])


# ─── 2.5: save_ticks does NOT modify pkl and sets ticks manifest ─

def test_save_ticks_does_not_modify_pkl():
    """save_ticks không được ghi đè hay thay đổi bất kỳ file .pkl nào."""
    with tempfile.TemporaryDirectory() as tmp:
        asset = "TESTTICKS"
        df = _create_sample_1m_data(n=1440 * 35)
        save_resampled_dataset(
            symbol=asset,
            output_dir=os.path.join(tmp, "dex"),
            df_1m_raw=df,
            pool_address="0xpool",
            crawl_ok=True,
        )
        asset_dir = os.path.join(tmp, "dex", asset)
        pkl_1m = os.path.join(asset_dir, "1m.pkl")
        pkl_4h = os.path.join(asset_dir, "4h.pkl")
        mtime_1m_before = os.path.getmtime(pkl_1m)
        mtime_4h_before = os.path.getmtime(pkl_4h)

        # Chờ 1 chút để mtime khác nếu có ghi
        time.sleep(0.05)

        now_ms = int(time.time() * 1000) - 100_000
        ticks_df = pd.DataFrame({
            "timestamp_ms": [now_ms + i * 1000 for i in range(10)],
            "price": [100.0] * 10,
            "volume_usd": [100.0] * 10,
            "amount": [1.0] * 10,
            "side": ["buy"] * 10,
            "tx_hash": [f"0x{i:064x}:0" for i in range(10)],
        })
        save_ticks(ticks_df, asset, retention_days=3, source="evm_swaps", data_root=tmp)

        assert os.path.getmtime(pkl_1m) == mtime_1m_before, "1m.pkl không được bị thay đổi"
        assert os.path.getmtime(pkl_4h) == mtime_4h_before, "4h.pkl không được bị thay đổi"

        # Metadata (attrs ticks.parquet) phải có khối ticks; không còn manifest.json
        assert not os.path.exists(os.path.join(asset_dir, "manifest.json"))
        manifest = manifest_of_dir(asset_dir)
        assert "ticks" in manifest
        assert manifest["ticks"]["synthetic"] is False
        assert manifest["ticks"]["rows"] == 10

        # has_ticks phải trả True
        assert has_ticks(asset, data_root=tmp) is True
