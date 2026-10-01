"""
test_data_layout.py — kiến trúc thư mục dữ liệu thị trường data/{cex,dex}/<SYM>.

- Phân giải ký hiệu: "BTC", "cex:BTC", "dex/AERO", "BTCUSDT" -> đúng thư mục.
- Trùng tên giữa cex/dex mà không ghi venue -> lỗi rõ ràng (không đoán).
- Đọc KHÔNG tạo thư mục (lỗi cũ: symbol_dir tạo thư mục rỗng mỗi lần gọi).
- Thư mục '_meta', '_cache', '_archive_invalid' không bị coi là tài sản.
- Studio /datasets, WFA, Research chạy được trên layout mới và trả venue.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from backend.core.resampler import save_resampled_dataset
from backend.db import data_layout as dl

T0 = 1_700_006_400_000
D = 86_400_000


def _rw_1m(days: int, seed: int = 3) -> pd.DataFrame:
    n = days * 1440
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": open_,
                         "high": np.maximum(open_, close) * 1.0003, "low": np.minimum(open_, close) * 0.9997,
                         "close": close, "volume": rng.uniform(10, 100, n)})


def _save(root, venue, sym, days=35):
    df = _rw_1m(days)
    return save_resampled_dataset(
        symbol=sym, output_dir=os.path.join(root, venue), df_1m_raw=df, pool_address="x", crawl_ok=True,
        requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
        extra_meta={"venue": venue, "exchange": "binance" if venue == "cex" else "geckoterminal"},
    )


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", root)
    _save(root, "cex", "BTC")
    _save(root, "dex", "AERO")
    for d in ("_meta", "_cache/research", "_archive_invalid/OLD"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    pd.DataFrame({"open_time": [T0]}).to_pickle(os.path.join(root, "_archive_invalid/OLD/15m.pkl"))
    return root


def test_resolve_symbols_in_venue_layout(layout):
    from backend.db.local_pkl import resolve_symbol_dir
    assert resolve_symbol_dir("BTC", layout) == os.path.join(layout, "cex", "BTC")
    assert resolve_symbol_dir("btcusdt", layout) == os.path.join(layout, "cex", "BTC")
    assert resolve_symbol_dir("cex:BTC", layout) == os.path.join(layout, "cex", "BTC")
    assert resolve_symbol_dir("dex/aero", layout) == os.path.join(layout, "dex", "AERO")
    assert resolve_symbol_dir("dex:BTC", layout) is None


def test_ambiguous_symbol_requires_venue(layout):
    from backend.db.local_pkl import list_asset_dirs, resolve_symbol_dir
    _save(layout, "dex", "BTC")
    with pytest.raises(dl.AmbiguousSymbolError):
        resolve_symbol_dir("BTC", layout)
    assert resolve_symbol_dir("dex:BTC", layout) == os.path.join(layout, "dex", "BTC")
    assert set(list_asset_dirs(layout)) == {"cex:BTC", "dex:BTC", "AERO"}


def test_listing_skips_meta_cache_archive(layout):
    items = dl.list_assets(layout)
    assert {(i["venue"], i["symbol"]) for i in items} == {("cex", "BTC"), ("dex", "AERO")}


def test_reading_never_creates_directories(layout):
    from backend.db.tick_storage import load_candle_df, load_ticks_df, symbol_dir
    before = sorted(os.walk(layout))
    symbol_dir("KHONG_TON_TAI", layout)
    load_candle_df("KHONG_TON_TAI", "1h", layout)
    load_ticks_df("KHONG_TON_TAI", data_root=layout)
    assert sorted(os.walk(layout)) == before


def test_tick_writer_goes_to_dex_folder(layout):
    from backend.db.tick_storage import save_ticks_and_sync_candles
    ticks = pd.DataFrame({"timestamp_ms": T0 + np.arange(10) * 1000, "price": np.linspace(1, 2, 10),
                          "amount": 1.0, "volume_usd": 1.0, "side": 1, "block_number": 1,
                          "tx_hash": [f"0x{i:064x}" for i in range(10)]})
    save_ticks_and_sync_candles(ticks, "NEWPOOL", data_root=layout)
    assert os.path.isfile(os.path.join(layout, "dex", "NEWPOOL", "ticks.parquet"))


def test_data_root_env_is_single_source(monkeypatch, tmp_path):
    from backend.db import local_pkl, tick_storage
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "a"))
    monkeypatch.setenv("NORA_DATA_ROOT", str(tmp_path / "b"))
    assert local_pkl.default_data_root() == tick_storage.default_data_root() == str(tmp_path / "a")


def test_research_cache_lives_under_cache_dir(layout):
    from backend.research.market_analyzer import get_cache_dir
    assert get_cache_dir(layout).startswith(os.path.join(layout, "_cache"))


def test_datasets_endpoint_reports_venue(layout):
    from backend.api.routers.studio import get_datasets
    rows = {d["symbol"]: d for d in get_datasets()["datasets"]}
    assert set(rows) == {"BTC", "AERO"}
    assert rows["BTC"]["venue"] == "cex" and rows["BTC"]["exchange"] == "binance"
    assert rows["AERO"]["venue"] == "dex" and rows["AERO"]["has_required_frames"] is True


def test_simulate_and_wfa_work_on_venue_layout(layout):
    from backend.api.routers.studio import SimulateRequest, run_simulation
    from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job
    from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.wfa import execute_wfa_pipeline
    flow = {"id": "f", "type": "LONG", "ast": {"type": "LONG",
            "match": [{"condition": [[[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]]}],
            "stop": [{"condition": [[[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]]}]}}
    res = run_simulation(SimulateRequest(symbol="cex:BTC", start_ts=T0 + 6 * D, end_ts=T0 + 20 * D, flows=[flow]))
    assert res["metrics"]["total_trades"] > 0
    job = create_wfa_job("AERO", "S", 0)
    execute_wfa_pipeline(job, StrategySnapshot(name="S", symbol="AERO", flows=[flow], start_ts=T0 + 6 * D,
                                               end_ts=T0 + 34 * D), WfaFoldConfig(train_days=10, test_days=5, min_folds=2), "h")
    assert get_wfa_job(job)["status"] == "completed", get_wfa_job(job).get("error")


def test_promote_script_places_assets_by_venue(tmp_path):
    import importlib.util
    staging, data = tmp_path / "staging", tmp_path / "data"
    _save(str(staging), "cex", "ETH")               # save_resampled_dataset ghi vào staging/cex/ETH
    os.rename(staging / "cex" / "ETH", staging / "ETH")  # staging là phẳng, venue lấy từ manifest
    spec = importlib.util.spec_from_file_location(
        "promote", os.path.join(os.path.dirname(__file__), "..", "scripts", "promote_staging.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(["--staging", str(staging), "--data", str(data), "--apply"])
    assert os.path.isfile(data / "cex" / "ETH" / "manifest.json")
    assert json.load(open(data / "cex" / "ETH" / "manifest.json"))["venue"] == "cex"


def test_instrument_symbol_never_falls_back_to_spot(layout):
    """Lỗi đã gặp: 'BTC@perp' không có dữ liệu perp -> bị phân giải thành thư mục spot BTC (qua hậu tố PERP)."""
    from backend.backtest.params_builder import data_symbol
    from backend.db.local_pkl import resolve_symbol_dir
    assert resolve_symbol_dir("BTC@perp", layout) is None
    assert data_symbol("BTC", "perp") == ("BTC", "spot_proxy")
