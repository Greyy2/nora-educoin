"""backend/optimize/search/evaluate.py::run trên thị trường giả lập (3 tài sản perp): khoá kết quả, result.json theo NORA_JOB_DIR, tất định."""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

from backend.analys.param import date_ms
from data_helpers import save_synthetic

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

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
    for k, sym in enumerate(SYMS):
        df = _series(70, 20 + k, 0.0008 * (k + 1))
        save_synthetic(symbol=sym, output_dir=str(root / "cex"), df_1m_raw=df)
    from backend.alpha import strategies as sb
    from backend.alpha.compile import cond, f, tree_p
    monkeypatch.setattr(sb, "UNIVERSE", list(SYMS))
    monkeypatch.setattr(sb, "CANDIDATES", [
        {"id": "t_long", "family": "x", "side": "LONG", "description": "test",
         "tree": cond((f("15m", "rsi_14"), "<", tree_p("lo", 40))), "position": {},
         "space": {"sig.lo": [35, 40], "stop_loss_rate": [2.0], "take_profit_rate": [2.0], "timeout": [720]}},
        {"id": "t_short", "family": "x", "side": "SHORT", "description": "test",
         "tree": cond((f("15m", "rsi_14"), ">", 60)), "position": {"atr_frame": "4h"},
         "space": {"stop_loss_rate": [1.5, 2.5], "trailing_stop": [2.0], "timeout": [720]}}])
    return root


def _load_script():
    from job_modules import job_path   # P9.6: run.py gộp vào optimize/process/tasks.py (run_book_backtest)
    path = job_path("run_book_backtest")
    spec = importlib.util.spec_from_file_location("run_book_backtest", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_book_backtest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _params(out):
    return {"strategies": STRATS, "symbols": "AAA@perp,BBB@perp,CCC", "start": "2023-12-10", "end": "2024-01-15", "out": str(out)}


def test_main_writes_result_json_with_expected_keys(market, tmp_path, monkeypatch):
    job_dir = tmp_path / "job"
    os.makedirs(job_dir, exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(job_dir))
    mod = _load_script()
    out = mod.run_job(_params(tmp_path / "out.json"))
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
    assert cur[0]["time"] >= date_ms("2023-12-10") and all(a["time"] < b["time"] for a, b in zip(cur, cur[1:]))
    cfg = res["config"]
    assert cfg["symbols"] == ["AAA@perp", "BBB@perp", "CCC@perp"] and cfg["strategies"][1]["params"]["stop_loss_rate"] == 2.5  # mức giữa
    assert out["final_equity"] == res["final_equity"]


def test_deterministic(market, tmp_path, monkeypatch):
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    mod = _load_script()
    a = mod.run_job(_params(tmp_path / "a.json"))
    b = mod.run_job(_params(tmp_path / "b.json"))
    assert not (tmp_path / "result.json").exists()   # không đặt NORA_JOB_DIR -> không ghi result.json
    for r in (a, b):
        r.pop("meta")                                # thời gian chạy / RAM không tất định
        r["provenance"].pop("computed_at")           # dấu thời gian tính (tasks.stamp_provenance) khác nhau theo từng lần chạy; phần engine của provenance vẫn so
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_downsample_keeps_ends_and_limit():
    from backend.metrics.metrics import downsample
    curve = [{"time": i} for i in range(10_001)]
    d = downsample(curve)
    assert len(d) <= 2000 and d[0] == curve[0] and d[-1] == curve[-1]
    assert downsample(curve[:50]) == curve[:50]


def test_rejects_unknown_strategy_and_bad_window(market, tmp_path):
    mod = _load_script()
    with pytest.raises(SystemExit):
        mod.run_job({"strategies": [{"id": "khong_co"}], "start": "2023-12-10", "end": "2024-01-15"})
    with pytest.raises(SystemExit):
        mod.run_job({"strategies": STRATS, "start": "2024-01-15", "end": "2023-12-10"})


def test_trade_list_has_notional_and_daily_nav(market, tmp_path):
    """Dashboard cần khối lượng/danh nghĩa/ký quỹ mỗi lệnh và vốn cuối ngày chính xác (daily_nav)."""
    mod = _load_script()
    out = mod.run_job(_params(tmp_path / "o.json"))
    assert out["trade_list"], "cần có lệnh"
    for t in out["trade_list"]:
        assert t["qty"] > 0 and t["notional"] > 0 and t["margin_usd"] > 0
        assert t["notional"] == pytest.approx(t["qty"] * t["enter_price"], rel=0.2)       # giá TB sau DCA lệch giá vào không nhiều
    nav = out["daily_nav"]
    assert nav and nav[0]["date"] == "2023-12-10" and nav[-1]["date"] == "2024-01-15"       # --end gồm cả ngày 15, không có ngày 16
    days = [pd.Timestamp(n["date"]) for n in nav]
    assert days == sorted(set(days))
    assert nav[-1]["equity"] == out["equity_curve"][-1]["equity"]                          # ngày cuối = mẫu vốn cuối


def test_strategy_symbols_filter_restricts_markets(market):
    """Khoá "symbols" của chiến lược dựng sẵn (alpha trong kho) -> chỉ chạy trên các tài sản đó; mặc định vẫn là mọi tài sản."""
    from backend.alpha import strategies as sb
    from backend.analys.param import materialize
    mod = _load_script()
    cand = sb.BY_ID["t_long"]
    base = materialize(cand, {"sig.lo": 45, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720})
    syms = [f"{s}@perp" for s in SYMS]
    kw = dict(items=[], symbols=syms, start=date_ms("2023-12-10"), end=date_ms("2024-01-15") + 86_400_000, rpt=0.5, stop_fill="level",
              risk={"max_positions": 8, "max_per_symbol": 1, "max_gross_exposure": 3.0, "kill_switch_dd_pct": 0})
    only = mod.run(extra_strategies=[{**base, "id": "only_aaa", "symbols": ["AAA@perp"]}], **kw)
    allm = mod.run(extra_strategies=[{**base, "id": "all_mkts"}], **kw)
    assert only["trade_list"] and {t["symbol"] for t in only["trade_list"]} == {"AAA@perp"}
    assert len({t["symbol"] for t in allm["trade_list"]}) > 1
    assert [s["id"] for s in only["config"]["strategies"]] == ["only_aaa"]
