"""scripts/run_book_backtest.py trên thị trường giả lập (3 tài sản perp): khoá kết quả, result.json theo NORA_JOB_DIR, tất định."""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

from backend.core.resampler import save_resampled_dataset

T0 = 1_700_006_400_000
SYMS = ("AAA", "BBB", "CCC")
STRATS = [{"id": "t_long", "params": {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720}},
          {"id": "t_short"}]   # t_short: tham số thiếu -> mức giữa của không gian


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
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    for k, sym in enumerate(SYMS):
        df = _series(70, 20 + k, 0.0008 * (k + 1))
        end = int(df.open_time.max())
        for name, out, extra in ((sym, root / "cex", {}), ("perp", root / "cex" / sym,
                                                         {"exchange": "binance_usdm", "market": "perp"})):
            save_resampled_dataset(symbol=name, output_dir=str(out), df_1m_raw=df, pool_address="x", crawl_ok=True,
                                   requested_start_ts=T0, requested_end_ts=end, extra_meta={**meta, **extra})
        ft = T0 + np.arange(1, 70 * 3) * 8 * 3_600_000
        pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001}).to_pickle(root / "cex" / sym / "perp" / "funding.pkl")
    from backend.alpha import strategy_book as sb
    f = sb.f
    monkeypatch.setattr(sb, "UNIVERSE", list(SYMS))
    monkeypatch.setattr(sb, "CANDIDATES", [
        {"id": "t_long", "family": "x", "side": "LONG", "description": "test",
         "tree": sb.cond((f("15m", "rsi_14"), "<", sb.p("lo", 40))), "position": {},
         "space": {"sig.lo": [35, 40], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}},
        {"id": "t_short", "family": "x", "side": "SHORT", "description": "test",
         "tree": sb.cond((f("15m", "rsi_14"), ">", 60)), "position": {"atr_frame": "4h"},
         "space": {"stop_loss_rate": [1.5, 2.5], "trailing_stop": [2.0], "timeout": [720]}}])
    return root


def _load_script():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "run_book_backtest.py")
    spec = importlib.util.spec_from_file_location("run_book_backtest", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_book_backtest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _argv(out):
    return ["--strategies", json.dumps(STRATS), "--symbols", "AAA@perp,BBB@perp,CCC",
            "--start", "2023-12-10", "--end", "2024-01-15", "--out", str(out)]


def test_main_writes_result_json_with_expected_keys(market, tmp_path, monkeypatch):
    job_dir = tmp_path / "job"
    monkeypatch.setenv("NORA_JOB_DIR", str(job_dir))
    mod = _load_script()
    out = mod.main(_argv(tmp_path / "out.json"))
    res = json.loads((job_dir / "result.json").read_text())
    assert json.loads((tmp_path / "out.json").read_text()).keys() == res.keys()
    for k in ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "by_symbol", "by_strategy", "daily",
              "halted_at", "rejected_for_risk", "trade_list", "equity_curve", "config", "final_equity", "meta"):
        assert k in res, k
    assert res["trades"] == len(res["trade_list"]) > 0
    assert set(res["by_symbol"]) <= set(SYMS) and set(res["by_strategy"]) <= {"t_long", "t_short"}
    t = res["trade_list"][0]
    assert set(t) >= {"symbol", "strategy", "side", "enter_time", "enter_price", "close_time", "close_price", "pnl", "status"}
    assert t["side"] in ("LONG", "SHORT") and t["symbol"].endswith("@perp")
    cur = res["equity_curve"]
    assert 0 < len(cur) <= 2000 and set(cur[0]) == {"time", "equity", "equity_worst"}
    assert cur[0]["time"] >= mod._ts("2023-12-10") and all(a["time"] < b["time"] for a, b in zip(cur, cur[1:]))
    cfg = res["config"]
    assert cfg["symbols"] == ["AAA@perp", "BBB@perp", "CCC@perp"] and cfg["strategies"][1]["params"]["stop_loss_rate"] == 2.5  # mức giữa
    assert out["final_equity"] == res["final_equity"]


def test_deterministic(market, tmp_path, monkeypatch):
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    mod = _load_script()
    a = mod.main(_argv(tmp_path / "a.json"))
    b = mod.main(_argv(tmp_path / "b.json"))
    assert not (tmp_path / "result.json").exists()   # không đặt NORA_JOB_DIR -> không ghi result.json
    for r in (a, b):
        r.pop("meta")                                # thời gian chạy / RAM không tất định
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_downsample_keeps_ends_and_limit():
    mod = _load_script()
    curve = [{"time": i} for i in range(10_001)]
    d = mod.downsample(curve)
    assert len(d) <= 2000 and d[0] == curve[0] and d[-1] == curve[-1]
    assert mod.downsample(curve[:50]) == curve[:50]


def test_rejects_unknown_strategy_and_bad_window(market, tmp_path):
    mod = _load_script()
    with pytest.raises(SystemExit):
        mod.main(["--strategies", '[{"id": "khong_co"}]', "--start", "2023-12-10", "--end", "2024-01-15"])
    with pytest.raises(SystemExit):
        mod.main(["--strategies", json.dumps(STRATS), "--start", "2024-01-15", "--end", "2023-12-10"])
