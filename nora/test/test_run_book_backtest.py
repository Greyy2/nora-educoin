"""backend/cli/run_book_backtest.py trên thị trường giả lập (3 tài sản perp): khoá kết quả, result.json theo NORA_JOB_DIR, tất định."""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

from backend.core.data.resampler import save_resampled_dataset

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
    from backend.core.strategy import strategy_book as sb
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
    path = os.path.join(os.path.dirname(__file__), "..", "backend", "cli", "run_book_backtest.py")
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


def test_trade_list_has_notional_and_daily_nav(market, tmp_path):
    """Dashboard cần khối lượng/danh nghĩa/ký quỹ mỗi lệnh và vốn cuối ngày chính xác (daily_nav)."""
    mod = _load_script()
    out = mod.main(_argv(tmp_path / "o.json"))
    assert out["trade_list"], "cần có lệnh"
    for t in out["trade_list"]:
        assert t["qty"] > 0 and t["notional"] > 0 and t["margin_usd"] > 0
        assert t["notional"] == pytest.approx(t["qty"] * t["enter_price"], rel=0.2)       # giá TB sau DCA lệch giá vào không nhiều
    nav = out["daily_nav"]
    assert nav and nav[0]["date"] == "2023-12-10" and nav[-1]["date"] == "2024-01-15"       # --end gồm cả ngày 15, không có ngày 16
    days = [pd.Timestamp(n["date"]) for n in nav]
    assert days == sorted(set(days))
    assert nav[-1]["equity"] == out["equity_curve"][-1]["equity"]                          # ngày cuối = mẫu vốn cuối


# ─── Feed giả lập (make_mock_feeds): vị thế cuối dữ liệu không bị đóng ép ─────────────────────────────────────
def _mock_plan():
    return {"days": 25, "capital": 5_000.0, "alpha": False}


def _feed(end_ms):
    from backend.cli import make_mock_feeds as mmf
    return mmf.make_feed("testnet", symbols=[f"{s}@perp" for s in SYMS], end_ms=end_ms, plan=_mock_plan(),
                         book_args=type("A", (), {"strategies": json.dumps(STRATS), "book": ""})())


def test_make_mock_feed_keeps_open_positions_and_is_deterministic(market):
    end0 = T0 + 69 * 86_400_000
    feeds = [(e, _feed(e)) for e in (end0 - k * 7_200_000 for k in range(0, 40, 10))]
    with_open = [(e, f) for e, f in feeds if f["positions"]]
    assert with_open, "cần ít nhất một mốc cuối dữ liệu còn vị thế mở"
    end, f = with_open[0]
    assert f["mock"] is True and f["kind"] == "testnet" and f["config"]["initial_capital"] == 5_000.0
    assert all(t["close_reason"] != "End of Backtest" for t in f["trade_list"])          # không đóng ép
    for p in f["positions"]:
        assert set(p) >= {"symbol", "strategy", "side", "qty", "entry_price", "mark_price", "notional", "unrealized_pnl", "opened", "margin_usd"}
        assert p["qty"] > 0 and p["notional"] == pytest.approx(p["qty"] * p["mark_price"], rel=1e-9) and p["opened"] <= end
    again = _feed(end)
    for x in (f, again):
        x.pop("source_desc", None)
    assert json.dumps(f, sort_keys=True, default=str) == json.dumps(again, sort_keys=True, default=str)
    # vốn cuối (MTM) = vốn ban đầu + lãi đã chốt + lãi/lỗ chưa chốt, lệch tối đa bằng funding của vị thế đang mở (<= 1% vốn ở đây)
    realised = sum(t["pnl"] for t in f["trade_list"])
    unreal = sum(p["unrealized_pnl"] for p in f["positions"])
    assert f["final_equity"] == pytest.approx(5_000.0 + realised + unreal, abs=50.0)


def test_strategy_symbols_filter_restricts_markets(market):
    """Khoá "symbols" của chiến lược dựng sẵn (alpha trong kho) -> chỉ chạy trên các tài sản đó; mặc định vẫn là mọi tài sản."""
    from backend.core.strategy import strategy_book as sb
    mod = _load_script()
    cand = next(c for c in sb.CANDIDATES if c["id"] == "t_long")
    base = sb.materialize(cand, {"sig.lo": 45, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720})
    syms = [f"{s}@perp" for s in SYMS]
    kw = dict(items=[], symbols=syms, start=mod._ts("2023-12-10"), end=mod._ts("2024-01-15") + 86_400_000, rpt=0.5, stop_fill="level",
              risk={"max_positions": 8, "max_per_symbol": 1, "max_gross_exposure": 3.0, "kill_switch_dd_pct": 0})
    only = mod.run(extra_strategies=[{**base, "id": "only_aaa", "symbols": ["AAA@perp"]}], **kw)
    allm = mod.run(extra_strategies=[{**base, "id": "all_mkts"}], **kw)
    assert only["trade_list"] and {t["symbol"] for t in only["trade_list"]} == {"AAA@perp"}
    assert len({t["symbol"] for t in allm["trade_list"]}) > 1
    assert [s["id"] for s in only["config"]["strategies"]] == ["only_aaa"]


def test_alpha_strategy_scales_order_size_by_max_scale(tmp_path, monkeypatch):
    from backend.cli import make_mock_feeds as mmf
    ast = {"type": "LONG", "match": [{"condition": [[["x"]]]}], "stop": []}
    reg = {"alphas": [{"alpha_id": "a__SOL", "side": "LONG", "symbol": "SOL", "data_symbol": "SOL@perp",
                       "position": {"market": "perp", "leverage": 1, "order_size_pct": 50}, "flows": [{"ast": ast}]}]}
    (tmp_path / "registry.json").write_text(json.dumps(reg))
    st, scale = mmf.alpha_strategy("a__SOL", str(tmp_path))
    assert scale is None and st["position"]["order_size_pct"] == 50 and st["symbols"] == ["SOL@perp"] and st["tree"] == ast["match"][0]["condition"]
    (tmp_path / "portfolio_a__SOL__SOL.json").write_text(json.dumps({"modes": {"extreme": {"max_scale_within_budget": 0.5}}}))
    st, scale = mmf.alpha_strategy("a__SOL", str(tmp_path))
    assert scale == 0.5 and st["position"]["order_size_pct"] == 25.0
