"""Metadata tài sản nằm trong attrs của pkl/parquet (không còn manifest.json / dex_pool.json): asset_meta, digest_1m, biên engine, migration."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from backend.crawl import store
from backend.crawl.store import DataQualityStatus, asset_meta, evaluate_data_quality, manifest_of_dir, read_manifest, save_resampled_dataset
from data_helpers import patch_meta, set_ticks_attrs

T0 = 1_700_006_400_000


def _df(n=1440 * 35, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.05, n))
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c + 0.01,
                         "volume": rng.random(n) + 1.0})


@pytest.fixture
def asset(tmp_path):
    save_resampled_dataset("AAA", str(tmp_path / "cex"), _df(), "x", source="binance_spot",
                           extra_meta={"venue": "cex", "exchange": "binance", "checksums_verified": True, "market": "spot"})
    return tmp_path, str(tmp_path / "cex" / "AAA")


def test_writer_stamps_every_frame_and_no_json(asset):
    root, d = asset
    names = sorted(os.listdir(d))
    assert names == ["15m.pkl", "1h.pkl", "1m.pkl", "24h.pkl", "4h.pkl", "5m.pkl"]          # không manifest.json
    attrs = [pd.read_pickle(os.path.join(d, n)).attrs[store.ATTR_KEY] for n in names]
    assert all(a == attrs[0] for a in attrs)
    a = attrs[0]
    df1 = pd.read_pickle(os.path.join(d, "1m.pkl"))
    assert a["rows_1m"] == len(df1) and a["start_ts"] == int(df1.open_time.iloc[0]) and a["end_ts"] == int(df1.open_time.iloc[-1])
    assert a["sha256_1m"] == store.compute_df_sha256(df1) and a["digest_1m"] == store.compute_df_digest(df1)
    assert a["venue"] == "cex" and a["synthetic"] is False and "rows" not in a and "coverage_days" not in a


def test_asset_meta_and_read_manifest_shape(asset):
    root, d = asset
    m = manifest_of_dir(d)
    assert m["coverage_days"] == 35.0 and m["base_resolution"] == "1m" and m["rows"]["1m"] == m["rows_1m"] and m["venue"] == "cex"
    assert read_manifest("AAA", data_root=str(root)) == m
    meta = asset_meta(d)
    assert meta["ticks"] is None and meta["funding"] is None and meta["onchain"] is None
    meta["dataset"]["venue"] = "dex"                                  # bản sao: sửa không ảnh hưởng lần đọc sau
    assert asset_meta(d)["dataset"]["venue"] == "cex"


def test_asset_meta_cache_follows_file_changes(asset):
    _, d = asset
    assert asset_meta(d)["dataset"]["crawl_ok"] is True
    patch_meta(d, crawl_ok=False)
    assert asset_meta(d)["dataset"]["crawl_ok"] is False


def test_attrs_cleared_at_engine_boundary(asset):
    root, d = asset
    stored = pd.read_pickle(os.path.join(d, "4h.pkl"))
    assert stored.attrs                                               # file có attrs
    for compat in (True, False):
        df = store.fetch_candles_df("AAA", "4h", data_root=str(root), compat=compat)
        assert df.attrs == {}
    loaded = store.CandleLoader("AAA", "4h")
    loaded.local_data_root = str(root)
    out = loaded.load_data(T0, T0 + 10 * 86_400_000)
    assert out.attrs == {}
    ref = store.fetch_candles_df("AAA", "4h", data_root=str(root), compat=False)
    assert np.array_equal(ref["close"].to_numpy(), stored["close"].to_numpy()) and ref.dtypes.equals(stored[ref.columns].dtypes)


def test_gate_blocks_on_digest_tamper_and_missing_meta(asset):
    root, d = asset
    assert evaluate_data_quality("AAA", "1m", data_root=str(root))["status"] in (DataQualityStatus.APPROVED, DataQualityStatus.WARNING)
    p = os.path.join(d, "1m.pkl")
    df = pd.read_pickle(p)
    df.loc[10, "volume"] += 1e-9                                      # đổi 1 bit-cỡ nhỏ: sha CSV vẫn có thể khớp ở 6 chữ số nhưng digest bắt được
    df.to_pickle(p)
    res = evaluate_data_quality("AAA", "1m", data_root=str(root))
    assert res["status"] == DataQualityStatus.BLOCKED and "digest_1m" in res["issues"][0]
    # mất attrs (ghi lại pkl không kèm metadata) -> không còn nguồn gốc -> BLOCKED
    for n in os.listdir(d):
        x = pd.read_pickle(os.path.join(d, n))
        x.attrs = {}
        x.to_pickle(os.path.join(d, n))
    store._META_CACHE.clear()
    res = evaluate_data_quality("AAA", "1m", data_root=str(root))
    assert res["status"] == DataQualityStatus.BLOCKED and "thiếu metadata" in res["issues"][0]


def test_funding_and_ticks_metadata_in_attrs(tmp_path):
    from backend.crawl.dex import save_ticks, tick_coverage
    save_resampled_dataset("DDD", str(tmp_path / "dex"), _df(), "0x1", extra_meta={"venue": "dex", "network": "base", "pool_fee_rate": 0.003})
    d = str(tmp_path / "dex" / "DDD")
    now = int(pd.Timestamp.now().timestamp() * 1000)
    tk = pd.DataFrame({"timestamp_ms": [now - 1000, now], "price": 1.0, "volume_usd": 1.0, "amount": 1.0, "side": "buy", "tx_hash": ["a:1", "b:2"]})
    save_ticks(tk, "DDD", retention_days=3, source="evm_swaps", data_root=str(tmp_path), extra_meta={"fee_rate": 0.003}, onchain={"pool_address": "0x1", "fee_rate": 0.003})
    meta = asset_meta(d)
    assert meta["ticks"]["rows"] == 2 and meta["ticks"]["fee_rate"] == 0.003 and meta["onchain"]["pool_address"] == "0x1"
    save_ticks(tk.assign(tx_hash=["c:3", "d:4"]), "DDD", retention_days=3, source="evm_swaps", data_root=str(tmp_path))
    assert asset_meta(d)["onchain"]["pool_address"] == "0x1" and asset_meta(d)["ticks"]["rows"] == 4   # onchain giữ khi không truyền lại
    assert [c["symbol"] for c in tick_coverage(str(tmp_path))] == ["DDD"]
    assert manifest_of_dir(d)["ticks"]["rows"] == 4
    f = pd.DataFrame({"funding_time": [1, 2], "interval_h": np.nan, "rate": [0.1, 0.2]})
    store.write_pickle_atomic(store.stamp_attrs(f, {"funding": {"file": "funding.pkl", "rows": 2}}), os.path.join(d, "funding.pkl"))
    assert manifest_of_dir(d)["funding"]["rows"] == 2
    set_ticks_attrs(d, ticks=None, onchain=None)
    assert not store.has_ticks("DDD", data_root=str(tmp_path))                                           # không khai báo -> không phải tick thật


# ─── migration: manifest.json / dex_pool.json -> attrs ───────────────────────
def _legacy_tree(root):
    """Dựng tài sản kiểu CŨ: pkl không attrs + manifest.json (+ dex_pool.json + ticks.parquet)."""
    save_resampled_dataset("OLD", str(root / "dex"), _df(), "0xpool", extra_meta={"venue": "dex", "network": "base", "pool_fee_rate": 0.003})
    d = root / "dex" / "OLD"
    man = manifest_of_dir(str(d))
    man["rows"] = {"1m": 1}                                            # manifest cũ lỗi thời: phải tính lại từ khung
    for n in os.listdir(d):
        x = pd.read_pickle(d / n)
        x.attrs = {}
        x.to_pickle(d / n)
    now = int(pd.Timestamp.now().timestamp() * 1000)
    tk = pd.DataFrame({"timestamp_ms": [now - 1000, now], "price": 1.0, "volume_usd": 1.0, "amount": 1.0, "side": "buy", "tx_hash": ["a:1", "b:2"]})
    tk.to_parquet(d / "ticks.parquet", index=False)
    man["ticks"] = {"source": "evm_swaps", "synthetic": False, "start_ts": now - 1000, "end_ts": now, "rows": 2, "window_days": 3, "fee_rate": 0.003}
    (d / "manifest.json").write_text(json.dumps(man))
    (d / "dex_pool.json").write_text(json.dumps({"onchain": {"pool_address": "0xpool", "fee_rate": 0.003, "stable": False}}))
    return d, man


def test_migration_round_trip_is_bit_identical_idempotent_and_archives_json(tmp_path):
    from scripts import migrate_pkl_meta as mig
    d, man = _legacy_tree(tmp_path)
    before = {n: pd.read_pickle(d / n) for n in os.listdir(d) if n.endswith(".pkl")}
    store._META_CACHE.clear()
    assert read_manifest("OLD", data_root=str(tmp_path)) is None                 # không còn đường đọc manifest.json: tài sản cũ chỉ đọc được sau khi migrate
    archive = tmp_path / "arch"
    dry = mig.migrate_dir(str(d), "x/OLD", str(archive), apply=False)
    assert dry["status"].startswith("dry-run") and (d / "manifest.json").exists() and not pd.read_pickle(d / "1m.pkl").attrs     # dry-run không ghi
    assert any("rows_1m" in n for n in dry["notes"])                                                                        # cảnh báo rows lỗi thời
    res = mig.migrate_dir(str(d), "x/OLD", str(archive), apply=True)
    assert res["status"] == "migrated" and not res["problems"], res
    assert not (d / "manifest.json").exists() and not (d / "dex_pool.json").exists()
    assert (archive / "x" / "OLD" / "manifest.json").exists() and (archive / "x" / "OLD" / "dex_pool.json").exists()      # cất, không xoá
    for n, old in before.items():
        assert mig.same_frame(pd.read_pickle(d / n), old), n
    store._META_CACHE.clear()
    new = read_manifest("OLD", data_root=str(tmp_path))
    for k in ("venue", "network", "pool_fee_rate", "sha256_1m", "start_ts", "end_ts", "synthetic", "crawl_ok", "coverage_days"):
        assert new[k] == man[k], k
    assert new["rows"]["1m"] == len(before["1m.pkl"]) and new["digest_1m"] == store.compute_df_digest(before["1m.pkl"])
    assert new["ticks"] == man["ticks"] and asset_meta(str(d))["onchain"]["pool_address"] == "0xpool"
    assert mig.migrate_dir(str(d), "x/OLD", str(archive), apply=True)["status"].startswith("ok")                           # idempotent


def test_migration_refuses_when_sha_does_not_match_manifest(tmp_path):
    from scripts import migrate_pkl_meta as mig
    d, man = _legacy_tree(tmp_path)
    man["sha256_1m"] = "0" * 64
    (d / "manifest.json").write_text(json.dumps(man))
    res = mig.migrate_dir(str(d), "x/OLD", str(tmp_path / "arch"), apply=True)
    assert res["status"] == "FAIL" and any("sha256" in p for p in res["problems"]) and (d / "manifest.json").exists()
    assert not pd.read_pickle(d / "1m.pkl").attrs                                                                          # không ghi gì
