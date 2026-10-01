"""
test_optimization_plumbing.py — hạ tầng cho bước B (tối ưu) và A3/A4 (perp, phí pool).

- Tham số tín hiệu {"param": ...}: thay đúng, thiếu/sai kiểu -> lỗi rõ.
- WFA nhận param_candidates (danh sách tổ hợp cụ thể, gồm cả "sig.*"), fold chọn đúng một ứng viên.
- Ký hiệu "BTC@perp": engine dùng dữ liệu perp + funding; data_symbol trả nguồn giá đúng.
- DEX dùng phí pool đã xác minh trong manifest thay cho mặc định.
- Script tối ưu: chia cửa sổ không chồng lấn, lấy mẫu cấu hình tái lập được.
"""
import importlib.util
import json
import os

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.core.strategy.params_template import collect_placeholders, resolve_placeholders, split_params
from backend.core.data.resampler import save_resampled_dataset

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


def test_snapshot_candidates_validation():
    from backend.core.contracts import StrategySnapshot
    StrategySnapshot(symbol="X", param_candidates=[{"leverage": 2, "sig.rsi_lo": 25}])
    with pytest.raises(ValidationError):
        StrategySnapshot(symbol="X", param_candidates=[{"bogus": 1}])
    with pytest.raises(ValidationError):
        StrategySnapshot(symbol="X", param_candidates=[{"leverage": 1}] * 51)


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


def test_perp_symbol_uses_perp_prices_and_funding(perp_root):
    from backend.api.routers.studio import SimulateRequest, run_simulation
    from backend.core.backtest.params_builder import data_symbol
    assert data_symbol("BTC", "perp") == ("BTC@perp", "perp")
    assert data_symbol("BTC", "spot") == ("BTC", "spot")
    flow = {"id": "f", "type": "LONG", "ast": {"type": "LONG", "match": [{"condition": [[[
        {"frame": "1m", "column": "open_time"}, "==", T0 + 7 * D]]]}], "stop": []}}
    res = run_simulation(SimulateRequest(symbol="BTC", start_ts=T0 + 6 * D, end_ts=T0 + 30 * D, flows=[flow],
                                         market="perp", leverage=3, order_size_pct=50))
    m = res["metrics"]
    assert m["data_symbol"] == "BTC@perp" and m["price_source"] == "perp" and m["funding_modeled"] is True
    trade = res["trades"][0]
    spot_open = _rw(40, 1).set_index("open_time").loc[T0 + 7 * D + 60_000, "open"]
    assert trade["entry_price"] == pytest.approx(spot_open * 1.001 * (1 + 0.0002), rel=1e-9)  # giá perp + trượt


def test_dex_uses_verified_pool_fee(tmp_path, monkeypatch):
    from backend.core.backtest.params_builder import build_params
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw(35)
    save_resampled_dataset(symbol="POOL", output_dir=str(root / "dex"), df_1m_raw=df, pool_address="0x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                           extra_meta={"venue": "dex", "pool_fee_rate": 0.0005})
    params = build_params("LONG_x", {"match": [], "stop": []}, "LONG", {}, "dex", "POOL")
    assert params.fee_rate == 0.0005 and params.maker_fee_rate == 0.0005
    assert build_params("LONG_x", {"match": [], "stop": []}, "LONG", {}, "dex", None).fee_rate == 0.003


def test_wfa_param_candidates_with_signal_params(tmp_path, monkeypatch):
    from backend.api.jobs.store import create_wfa_job, get_wfa_job
    from backend.core.contracts import StrategySnapshot, WfaFoldConfig
    from backend.wfa.walk_forward import execute_wfa_pipeline
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw(40, 3)
    save_resampled_dataset(symbol="RW", output_dir=str(root / "cex"), df_1m_raw=df, pool_address="x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                           extra_meta={"venue": "cex", "checksums_verified": True})
    tree = [[[{"frame": "1m", "column": "rsi_7"}, "<", {"param": "rsi_lo", "default": 30}]]]
    flows = [{"id": "f", "type": "LONG", "ast": {"type": "LONG", "match": [{"condition": tree}], "stop": []}}]
    cands = [{"sig.rsi_lo": 25, "take_profit_rate": 0.3}, {"sig.rsi_lo": 35, "take_profit_rate": 0.6}]
    snap = StrategySnapshot(name="c", symbol="RW", flows=flows, start_ts=T0 + 2 * D, end_ts=T0 + 38 * D,
                            param_candidates=cands, timeout=240)
    job = create_wfa_job("RW", "c", 0)
    execute_wfa_pipeline(job, snap, WfaFoldConfig(train_days=10, test_days=5, min_folds=2), "h")
    res = get_wfa_job(job)
    assert res["status"] == "completed", res.get("error")
    for fold in res["result"]["folds"]:
        picked = {k: fold["chosen_params"][k] for k in ("sig.rsi_lo", "take_profit_rate")}
        assert picked in cands
    assert res["result"]["param_stability"] is not None


def _load_script(name):
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_optimizer_windows_and_sampling_are_honest():
    opt = _load_script("optimize_alphas")
    w = opt.windows({"start_ts": T0, "end_ts": T0 + 1000 * D}, "cex")
    assert w["start"] < w["dev1_end"] < w["holdout"] < w["end"]
    assert (w["holdout"] - w["start"]) / (w["end"] - w["start"]) == pytest.approx(0.8, abs=0.01)
    space = {"a": [1, 2, 3], "b": [4, 5], "c": [6, 7, 8, 9]}
    c1, total = opt.sample_configs(space, 10, seed=7)
    c2, _ = opt.sample_configs(space, 10, seed=7)
    assert total == 24 and c1 == c2 and len({json.dumps(c, sort_keys=True) for c in c1}) == 10


def _wait_scan(job_id, timeout=120):
    import time as _t
    from backend.api.jobs.scan import get_scan_job
    end = _t.time() + timeout
    while _t.time() < end:
        job = get_scan_job(job_id)
        if job and job.get("status") in ("completed", "failed"):
            return job
        _t.sleep(0.2)
    raise AssertionError("scan không kết thúc")


def test_scan_multi_asset_skips_invalid_and_is_deterministic(tmp_path, monkeypatch):
    from backend.api.routers.studio import ScanRequest, start_scan
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    for i, (venue, sym) in enumerate((("cex", "AAA"), ("cex", "BBB"), ("dex", "CCC"))):
        df = _rw(40, 10 + i)
        save_resampled_dataset(symbol=sym, output_dir=str(root / venue), df_1m_raw=df, pool_address="x", crawl_ok=True,
                               requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                               extra_meta={"venue": venue, "checksums_verified": True})
    flows = [{"id": "f", "type": "LONG", "ast": {"type": "LONG", "match": [{"condition": [[[
        {"frame": "1m", "column": "rsi_7"}, "<", {"param": "lo", "default": 30}]]]}], "stop": []}}]
    req = dict(flows=flows, days=20, position={"market": "perp", "leverage": 3, "take_profit_rate": 0.4,
                                                "stop_loss_rate": 0.8, "timeout": 120}, signal_params={"lo": 25})
    first = _wait_scan(start_scan(ScanRequest(**req))["job_id"])
    assert first["status"] == "completed", first.get("error")
    rows = {r["symbol"]: r for r in first["result"]["rows"]}
    assert set(rows) == {"AAA", "BBB"}, "perp chỉ quét tài sản CEX"
    assert all(r["total_trades"] > 0 and r["days"] == 20.0 for r in rows.values())
    second = _wait_scan(start_scan(ScanRequest(**req))["job_id"])
    for r in second["result"]["rows"]:
        assert r["return_pct"] == rows[r["symbol"]]["return_pct"]
        assert r["total_trades"] == rows[r["symbol"]]["total_trades"]
    spot = _wait_scan(start_scan(ScanRequest(flows=flows, symbols=["CCC"], position={"market": "perp"}))["job_id"])
    assert "skipped" in spot["result"]["rows"][0]
