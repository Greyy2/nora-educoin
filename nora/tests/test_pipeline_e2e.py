"""
test_pipeline_e2e.py — C4: toàn bộ luồng data -> signal/strategy -> backtest -> WFA -> Monte Carlo -> alpha.

Dữ liệu giả lập nhỏ (CEX spot + perp + funding), không gọi mạng. Kiểm:
- không giai đoạn nào nhìn dữ liệu của giai đoạn sau (sàng lọc < WFA-test < holdout);
- hợp đồng dữ liệu giữa các bước (WFA -> MC -> registry -> cấu hình testnet);
- tái lập: chạy lại cho cùng kết quả.
"""
import importlib.util
import json
import os

import numpy as np
import pandas as pd
import pytest

from backend.core.resampler import save_resampled_dataset

T0 = 1_700_006_400_000
DAY = 86_400_000


def _series(days, seed):
    n = days * 1440
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    eps = rng.normal(0, 0.0012, n)
    for i in range(1, n):  # hồi về nhẹ để chiến lược bắt hồi có lệnh
        r[i] = -0.2 * r[i - 1] + eps[i]
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * 60_000, "open": o,
                         "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995, "close": c,
                         "volume": 10.0})


@pytest.fixture
def market(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _series(90, 5)
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    save_resampled_dataset(symbol="SIM", output_dir=str(root / "cex"), df_1m_raw=df, pool_address="s", crawl_ok=True,
                           requested_start_ts=T0, requested_end_ts=int(df.open_time.max()), extra_meta=meta)
    save_resampled_dataset(symbol="perp", output_dir=str(root / "cex" / "SIM"), df_1m_raw=df, pool_address="p",
                           crawl_ok=True, requested_start_ts=T0, requested_end_ts=int(df.open_time.max()),
                           extra_meta={**meta, "exchange": "binance_usdm", "market": "perp"})
    ft = T0 + np.arange(1, 90 * 3) * 8 * 3_600_000
    pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001}).to_pickle(root / "cex" / "SIM" / "perp" / "funding.pkl")
    return root


SPACE = {
    "id": "e2e_dca_long_perp", "family": "Bắt hồi + DCA", "side": "LONG", "venue": "cex", "fixed": {"market": "perp"},
    "tree": [[[{"frame": "5m", "column": "rsi_14"}, "<", {"param": "rsi_lo", "default": 35}]]],
    "space": {"leverage": [2, 3], "order_size_pct": [20], "dca_step_pct": [0.4, 0.8], "dca_max_layers": [2],
              "take_profit_rate": [0.3, 0.6], "stop_loss_rate": [3], "timeout": [720], "sig.rsi_lo": [30, 40]},
}


def _load(name):
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patched_run(monkeypatch, opt, db, n=6):
    from backend.alpha import strategy_library
    monkeypatch.setattr(strategy_library, "OPTIMIZATION_SPACES", [SPACE])
    monkeypatch.setattr(opt, "MAX_MDD", 100.0)          # dữ liệu nhỏ: nới gate để đi hết mọi giai đoạn
    return opt.run_pair(SPACE["id"], "SIM", n, 1, db)


def test_full_pipeline_stages_contracts_and_reproducibility(market, monkeypatch, tmp_path):
    opt = _load("optimize_alphas")
    db = str(tmp_path / "pipe.db")
    r1 = _patched_run(monkeypatch, opt, db)
    assert r1["data_symbol"] == "SIM@perp" and r1["price_source"] == "perp"
    assert r1["screen"]["passed"] >= 1, r1

    # Thứ tự thời gian: sàng lọc (dev1) < WFA test < holdout
    w = {k: pd.Timestamp(v) for k, v in r1["windows"].items()}
    assert w["start"] < w["dev1_end"] < w["holdout"] < w["end"]
    assert r1["wfa"]["total_folds"] >= 1

    # MC + holdout có mặt, cấu hình cuối nằm trong không gian đã khai báo
    assert "risk_of_ruin_pct" in r1["mc"]
    for k, v in r1["final_params"].items():
        if k in SPACE["space"]:
            assert v in SPACE["space"][k]
    assert set(r1["checks"]) >= {"wfa_gate", "mc_ruin_le_5", "holdout_profit", "holdout_mdd_le_30"}

    # Tái lập
    r2 = _patched_run(monkeypatch, opt, db)
    for key in ("screen", "wfa", "mc", "final_params", "holdout", "verdict"):
        assert json.dumps(r1[key], sort_keys=True, default=str) == json.dumps(r2[key], sort_keys=True, default=str), key


def test_registry_and_testnet_export(market, monkeypatch, tmp_path):
    from backend.alpha.registry import build_registry, testnet_config, write_registry
    opt = _load("optimize_alphas")
    r = _patched_run(monkeypatch, opt, str(tmp_path / "pipe.db"), n=4)
    r["verdict"] = "ALPHA"  # ép qua để kiểm định dạng xuất (không phải kết luận về lợi nhuận)
    reg = build_registry([r, {**r, "verdict": "KHONG_DAT", "symbol": "X"}], [SPACE], source="test")
    assert reg["pairs_evaluated"] == 2 and len(reg["alphas"]) == 1
    alpha = reg["alphas"][0]
    assert alpha["data"]["sha256_1m"] and alpha["market"] == "perp"
    assert "param" not in json.dumps(alpha["flows"]), "AST phải đã thay hết tham số"
    cfg = testnet_config(alpha)
    assert cfg["symbol"] == "SIMUSDT" and cfg["margin_type"] == "ISOLATED" and cfg["leverage"] == alpha["position"]["leverage"]
    assert cfg["dca"]["time_in_force"] == "GTX" and cfg["stop_loss"]["reduce_only"] is True
    files = write_registry(reg, str(tmp_path / "alphas"))
    assert any(f.endswith("registry.json") for f in files) and any("/testnet/" in f for f in files)
    spot_alpha = {**alpha, "market": "spot"}
    with pytest.raises(ValueError):
        testnet_config(spot_alpha)
