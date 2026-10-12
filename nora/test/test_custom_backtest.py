"""P7 — job custom_backtest (core/backtest/custom_run.py) + API (/strategies/compile, /custom/backtest) trên dữ liệu tổng hợp.
Không chạy job thật qua API: Popen bị thay bằng bản giả; run_job được gọi trực tiếp trong tiến trình test."""
import json
import os

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import golden_scenarios as gs
from backend.jobs import runner as batch_jobs
from backend.routes import alpha
from backend.routes import alpha
from job_modules import launched

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

CODE_DAILY = '''
class Hold(SimpleAlgorithm):
    timeframe = "24h"
    def __algorithm__(self):
        close = self.data.pv_close
        self.set_positions(close > 0, position=1)
'''

CODE_1H = '''
class Rsi(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi > 55, position=1)
        self.set_positions(rsi < 45, position=0)
'''


@pytest.fixture
def market(tmp_path, monkeypatch):
    gs.write_synthetic_market(tmp_path / "data")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    gs.clear_caches()
    yield tmp_path
    gs.clear_caches()


def _params(**kw):
    return {"start": "2023-11-22", "end": "2023-12-18", "symbols": ["AAA", "BBB"], **kw}


def test_run_reports_everything_with_one_flat_metric_set(market, monkeypatch):
    from backend.jobs import tasks as custom_run
    (market / "job").mkdir(exist_ok=True)
    os.makedirs(market / "job", exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(market / "job"))
    out = custom_run.run_custom_backtest(_params(code=CODE_DAILY, initial_capital=100_000))
    assert os.path.isfile(market / "job" / "result.json")
    json.dumps(out, allow_nan=False)                                        # JSON hợp lệ, không NaN
    for key in ("config", "program_hash", "data", "metrics", "yearly", "series", "trades", "positions_open", "by_symbol", "warnings"):
        assert key in out
    assert "profile" not in out["config"] and out["config"]["run_frame"] == "1m" and out["config"]["symbols"] == ["AAA", "BBB"]
    s = out["series"]
    assert len(s["times"]) == len(s["equity"]) == len(s["drawdown"]) == len(s["pnl"]) and s["times"][0] == 1700611200   # 2023-11-22
    assert all(t2 - t1 == 86400 for t1, t2 in zip(s["times"], s["times"][1:]))
    sim = out["metrics"]["simulate"]
    assert {"ret_pct", "mdd_pct", "sharpe", "sortino", "cagr_pct", "calmar", "trades", "fees_usd"} <= set(sim)
    assert not any(isinstance(v, dict) for v in sim.values()) and set(out["metrics"]) == {"simulate", "train", "test", "notes"}
    assert out["metrics"]["notes"]["annualization_days"] == 365
    assert s["times"][0] < s["stage_split"] < s["times"][-1]
    assert {b["symbol"] for b in out["by_symbol"]} == {"AAA@perp", "BBB@perp"}
    assert out["final_equity"] == pytest.approx(s["equity"][-1], abs=0.01)


def test_runs_on_1m_with_perp_and_echoes_position(market):
    from backend.jobs import tasks as custom_run
    out = custom_run.run_custom_backtest(_params(code=CODE_1H, symbols=["AAA", "BBB", "CCC"], initial_capital=10_000,
                                     position={"risk_per_trade_pct": 0.25}))
    assert out["config"]["run_frame"] == "1m" and out["config"]["data_symbols"] == ["AAA@perp", "BBB@perp", "CCC@perp"]
    assert out["config"]["position"]["risk_per_trade_pct"] == 0.25
    assert any("mặc định" in w for w in out["warnings"])
    assert len(out["trades"]) + len(out["positions_open"]) > 0
    assert out["metrics"]["simulate"]["trades"] == len(out["trades"])


def test_job_rejects_bad_input_clearly(market):
    from backend.jobs import tasks as custom_run
    with pytest.raises(ValueError, match=r"dòng 4, cột \d+"):
        custom_run.run_custom_backtest(_params(code="class S(SimpleAlgorithm):\n    def __algorithm__(self):\n        x = self.data.pv_close\n        y = x and x\n"))
    with pytest.raises(ValueError, match="Không có dữ liệu"):
        custom_run.run_custom_backtest(_params(code=CODE_DAILY, symbols=["ZZZ"]))
    for gone in ("profile", "exchange", "universe", "market"):             # tham số đã gỡ: không còn chế độ / nguồn / rổ cố định
        with pytest.raises(ValueError, match="tham số lạ"):
            custom_run.run_custom_backtest(_params(code=CODE_DAILY, **{gone: "x"}))
    with pytest.raises(ValueError, match="tham số lạ"):
        custom_run.run_custom_backtest(_params(code=CODE_DAILY, bogus=1))


def test_default_universe_and_window_come_from_the_store(market):
    from backend.data import data as run_defaults
    uni = run_defaults.default_universe()
    assert {"AAA", "BBB", "CCC"} <= set(uni) and uni == sorted(uni)
    assert run_defaults.resolve_symbols(["BBB@perp", "AAA"]) == ["BBB", "AAA"] and run_defaults.resolve_symbols(None) == uni
    d = run_defaults.run_defaults()
    assert d["symbols"] == [f"{n}@perp" for n in uni] and d["start"] < d["end"] and d["initial_capital"] == 10_000.0 and d["train_ratio"] == 0.7


def test_daily_series_labels_and_returns():
    from backend.models.params import DAY_MS as DAY
    from backend.metrics.trades import daily_series
    start = 10 * DAY
    curve = [{"time": start + h * 3_600_000, "equity": 100.0 + h} for h in range(0, 24 * 3)]
    s = daily_series(curve, start, start + 3 * DAY, 3_600_000, 100.0)
    assert list(s["times"]) == [start + k * DAY for k in range(4)]
    assert s["equity"][0] == 100.0 and s["equity"][1] == 123.0 and s["equity"][3] == 171.0        # mẫu cuối có nhãn <= mốc
    assert s["returns"][0] == 0 and s["returns"][1] == pytest.approx(0.23)


# ─── API ────────────────────────────────────────────────────────────────────

class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 12345
        self.returncode = None

    def wait(self):
        return 0


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    app = FastAPI()
    app.include_router(alpha.strategies_router)
    app.include_router(alpha.custom_router)
    return TestClient(app)


def test_api_defaults_endpoint_reads_the_store(client, market):
    d = client.get("/api/studio/custom/defaults").json()
    assert {"AAA@perp", "BBB@perp", "CCC@perp"} <= set(d["symbols"]) and d["start"] < d["end"] and set(d) == {"symbols", "start", "end", "train_ratio", "initial_capital"}


def test_api_compile_ok_and_error_shape(client):
    ok = client.post("/api/studio/strategies/compile", json={"code": CODE_1H}).json()
    assert ok["ok"] and len(ok["program_hash"]) == 12 and ok["meta"]["timeframe"] == "1h" and ok["meta"]["legs"] == ["LONG"]
    assert ok["meta"]["position_levels"] == [0.0, 1.0] and ok["meta"]["warmup_bars"] > 0 and ok["error"] is None
    bad = client.post("/api/studio/strategies/compile", json={"code": CODE_1H.replace("rsi > 55", "rsi > 55 and rsi < 99")}).json()
    assert not bad["ok"] and bad["error"]["line"] == 7 and bad["error"]["col"] >= 1 and "&" in bad["error"]["message"]


def test_custom_storage_endpoints_are_retired(client):
    """Lưu code đơn thuần đã gỡ: chỉ còn POST /api/studio/alphas/user (kèm kết quả chạy)."""
    assert client.get("/api/studio/strategies/custom").status_code in (404, 405)
    assert client.post("/api/studio/strategies/custom", json={"name": "x", "code": CODE_DAILY}).status_code in (404, 405)
    assert client.delete("/api/studio/strategies/custom/x").status_code in (404, 405)


def test_api_custom_backtest_launches_job_with_validated_params(client):
    body = {"code": CODE_DAILY, "start": "2020-01-02", "end": "2024-12-31", "train_ratio": 0.7, "initial_capital": 100000}
    r = client.post("/api/studio/custom/backtest", json=body)
    assert r.status_code == 200 and "job_id" in r.json()
    kind, params = launched(FakePopen.calls[0])
    assert kind == "custom_backtest" and "profile" not in params and params["initial_capital"] == 100000
    assert set(params) <= batch_jobs.KINDS["custom_backtest"]["params"]
    bad = client.post("/api/studio/custom/backtest", json={**body, "code": "class S(SimpleAlgorithm):\n  def __algorithm__(self):\n    x = y\n"})
    assert bad.status_code == 422 and "dòng 3" in bad.json()["detail"]
    assert client.post("/api/studio/custom/backtest", json={**body, "start": "2025-01-01"}).status_code == 422
    assert client.post("/api/studio/custom/backtest", json={**body, "start": "2000-01-01"}).status_code == 422       # > 4000 ngày
    assert client.post("/api/studio/custom/backtest", json={**body, "position": {"nope": 1}}).status_code == 422
    assert client.post("/api/studio/custom/backtest", json={**body, "symbols": ["B" * 40]}).status_code == 422
    assert client.post("/api/studio/custom/backtest", json={**body, "initial_capital": -5}).status_code == 422
    assert len(FakePopen.calls) == 1


def test_diagnostics_use_real_benchmark_and_market(market, monkeypatch):
    """Chẩn đoán lấy từ chính lần chạy: benchmark luôn long chạy qua cùng engine , series.benchmark, chế độ thị trường (chuỗi ngắn -> unknown), lý do thoát thật."""
    from backend.jobs import tasks as custom_run
    (market / "job").mkdir(exist_ok=True)
    os.makedirs(market / "job", exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(market / "job"))
    out = custom_run.run_custom_backtest(_params(code=CODE_1H, initial_capital=100_000))
    d = out["diagnostics"]
    mc = d["market_comparison"]
    assert mc["available"], out["warnings"]
    assert "benchmark" in out["series"] and len(out["series"]["benchmark"]["equity"]) == len(out["series"]["equity"])
    assert out["series"]["benchmark"]["equity"][0] == out["series"]["equity"][0] == 100_000
    assert -1.0 <= mc["correlation"] <= 1.0 and mc["beta"] is not None
    nora_cagr = out["metrics"]["simulate"]["cagr_pct"]                            # cùng định nghĩa/số ngày với metrics: 365/(số mẫu - 1)
    assert mc["strategy_cagr"] == pytest.approx(nora_cagr, abs=0.011)
    assert (mc["market_cagr"], mc["market_mdd"]) != (40.0, 75.0) and (mc["beta"], mc["correlation"]) != (0.95, 0.85)
    sig = d["signal_activity"]
    assert sum(sig["exit_reason_counts"].values()) == sig["total_trades"] == len(out["trades"]) + len(out["positions_open"])
    assert 0.0 <= sig["days_in_market_pct"] <= 100.0 and sig["avg_exposure_pct"] >= 0.0
    reg = d["regime_analysis"]
    assert reg["available"] and reg["unknown"]["days"] == reg["total_days"]               # 27 ngày dữ liệu tổng hợp: chưa đủ 200 nến cho SMA200 -> toàn bộ unknown
    json.dumps(out, allow_nan=False)


def test_benchmark_aligned_with_strategy_start_and_holds_without_risk_sizing(market, monkeypatch):
    """Cả hai đường vốn cùng lưới ngày và bắt đầu ở đúng vốn đầu; benchmark nắm giữ chia đều (không định cỡ theo rủi ro, không SL) nên khác chiến lược."""
    from backend.jobs import tasks as custom_run
    (market / "job").mkdir(exist_ok=True)
    os.makedirs(market / "job", exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(market / "job"))
    out = custom_run.run_custom_backtest(_params(code=CODE_DAILY, initial_capital=100_000))
    s = out["series"]
    b = s["benchmark"]
    assert b["times"] == s["times"] and b["equity"][0] == s["equity"][0] == 100_000
    assert b["final_equity"] == b["equity"][-1] and "Luôn long" in b["label"] and b["equity"] != s["equity"]


def test_yearly_table_drops_years_with_fewer_than_two_return_days():
    import pandas as pd
    from backend.models.params import DAY_MS as DAY
    from backend.metrics.trades import yearly_table
    start = int(pd.Timestamp("2019-12-31", tz="UTC").value // 1_000_000)
    times = start + np.arange(0, 6) * DAY                    # nhãn 12-31, 01-01 .. 01-05
    eq = np.array([100.0, 100.0, 101.0, 102.0, 101.0, 103.0])
    ret = np.zeros(6)
    ret[1:] = eq[1:] / eq[:-1] - 1.0
    rows = yearly_table({"times": times, "equity": eq, "returns": ret}, times[-1] + DAY, [])
    assert [r["year"] for r in rows] == [2020]               # 2019 chỉ có 1 ngày lợi suất (nhãn 01-01 thuộc nến 12-31) -> bỏ
    assert rows[0]["days"] == 4 and rows[0]["sharpe"] is not None


def test_stage_series_are_computed_in_backend_with_benchmark_per_stage(market, monkeypatch):
    """series.stages = {all, train, test} đã tính ở backend trên chuỗi ngày đầy đủ (equity, pnl, drawdown_pct, ret_pct, benchmark); test = lần chạy lại từ vốn đầu
    + benchmark chạy lại cùng cửa sổ (series.test.benchmark), KHÔNG co dãn; giao diện không phải tính lại."""
    from backend.jobs import tasks as custom_run
    (market / "job").mkdir(exist_ok=True)
    os.makedirs(market / "job", exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(market / "job"))
    out = custom_run.run_custom_backtest(_params(code=CODE_1H, initial_capital=100_000))
    s = out["series"]
    st = s["stages"]
    assert set(st) == {"all", "train", "test"} and all(st[k] for k in st)
    for name, blk in st.items():
        n = len(blk["times"])
        for k in ("equity", "pnl", "drawdown_pct", "ret_pct"):
            assert len(blk[k]) == n, (name, k)
        assert blk["pnl"][0] == 0.0 and blk["ret_pct"][0] == 0.0 and max(blk["drawdown_pct"]) <= 0.0
        assert blk["equity"][0] == 100_000                                         # mỗi giai đoạn bắt đầu từ vốn đầu (test chạy lại từ vốn mới)
        assert blk["downsample"]["step"] == 1 and blk["downsample"]["source_points"] == n   # chuỗi ngắn: không hạ mẫu
        bm = blk["benchmark"]
        assert bm and len(bm["equity"]) == n and bm["equity"][0] == 100_000 and bm["pnl"][0] == 0.0, name
    # toàn kỳ khớp chuỗi đầy đủ + drawdown tính ở backend (%) khớp drawdown phân số
    assert st["all"]["equity"] == s["equity"] and st["all"]["drawdown_pct"] == pytest.approx([d * 100 for d in s["drawdown"]], abs=1e-3)
    # train = phần đầu của toàn kỳ đến mốc chia
    nt = len(st["train"]["times"])
    assert st["train"]["times"] == s["times"][:nt] and st["train"]["times"][-1] <= s["stage_split"] < st["all"]["times"][nt] if nt < len(s["times"]) else True
    # test: lần chạy lại + benchmark cùng cửa sổ, đúng series.test
    t = s["test"]
    assert st["test"]["times"] == t["times"] and st["test"]["equity"] == t["equity"]
    assert t["benchmark"]["times"] == t["times"] and t["benchmark"]["equity"] == st["test"]["benchmark"]["equity"]
    assert t["benchmark"]["final_equity"] == t["benchmark"]["equity"][-1]
    json.dumps(out, allow_nan=False)


def test_stage_downsample_is_explicit_and_composable():
    """Hạ mẫu chỉ để vẽ: nhóm step điểm (điểm 0 riêng), equity/pnl = cuối nhóm, drawdown = đáy nhóm, ret = lãi kép nhóm; ghi rõ trong `downsample`."""
    from backend.metrics.charts import downsample_stage, stage_block
    rng = np.random.default_rng(1)
    n = 101
    eq = 100_000 * np.cumprod(np.r_[1.0, 1.0 + rng.normal(0, 0.01, n - 1)])
    times = np.arange(n, dtype="int64") * 86_400_000
    full = stage_block(times, eq, eq * 1.01, "bench")
    ds = downsample_stage(full, 26)
    assert ds["downsample"] == {**full["downsample"], "step": 4, "points": 26, "source_points": n}
    assert len(ds["times"]) == len(ds["equity"]) == len(ds["drawdown_pct"]) == len(ds["ret_pct"]) == len(ds["benchmark"]["equity"]) == 26
    assert ds["times"][0] == full["times"][0] and ds["times"][-1] == full["times"][-1] and ds["equity"][-1] == full["equity"][-1]
    assert min(ds["drawdown_pct"]) == min(full["drawdown_pct"])                      # đáy nhóm: không mất đáy sâu nhất
    compounded = (np.prod(1 + np.asarray(ds["ret_pct"]) / 100) - 1) * 100
    assert compounded == pytest.approx((eq[-1] / eq[0] - 1) * 100, abs=1e-3)       # lãi kép các nhóm = lãi toàn kỳ
    again = downsample_stage(ds, 11)                                                  # gọi lại được, ghi nhận nguồn gốc
    assert again["downsample"]["source_points"] == n and again["downsample"]["step"] > 4 and len(again["times"]) <= 11
    assert again["equity"][-1] == full["equity"][-1]
