"""Kiểm thử tính độc lập của dự án nora/coin."""
import os
import json
import math
import sys
import tempfile
import time
from pathlib import Path

COIN_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = COIN_ROOT / "frontend"
sys.path.insert(0, str(COIN_ROOT))
os.environ["NORA_DATA_ROOT"] = str(COIN_ROOT / "data")

def test_coin_imports_and_routes():
    from backend.main import app
    assert app is not None
    assert app.title == "Nora COIN API"

    paths = list(app.openapi().get("paths", {}).keys())
    print(f"Total COIN routes: {len(paths)}")
    assert any("/live" in p for p in paths)
    assert any("/portfolio" in p for p in paths)
    assert any("/api/studio/meta" in p for p in paths)
    assert any("/data" in p for p in paths)
    assert not any("/api/edu" in p for p in paths), "Không được có route /api/edu trong COIN!"
    print("✅ COIN project routes test passed!")

def test_coin_data_isolation():
    from backend.models.storage import data_home
    home = data_home()
    assert "coin/data" in home or "coin" in home, f"Data root không trỏ vào coin: {home}"
    print(f"✅ COIN data root verified: {home}")

def test_coin_frontend_build_scripts():
    package = json.loads((FRONTEND_ROOT / "package.json").read_text())
    scripts = package["scripts"]
    assert scripts["build:coin"] == "vite build --config vite.config.js"
    assert scripts["build:edu"] == "npm --prefix ../../edu/frontend run build"
    assert scripts["build:all"] == "npm run build:coin && npm run build:edu"
    assert (FRONTEND_ROOT / "vite.config.js").is_file()
    assert (COIN_ROOT.parent / "edu" / "frontend" / "package.json").is_file()
    assert not (FRONTEND_ROOT / "vite.coin.config.js").exists()
    assert not (FRONTEND_ROOT / "vite.edu.config.js").exists()

    html = (FRONTEND_ROOT / "index.html").read_text()
    assert '/src/main.coin.jsx' in html, "COIN index must load the COIN application entrypoint"
    print("✅ COIN frontend build scripts and product entrypoint verified")

def test_coin_dev_proxy_targets_coin_service():
    config = (FRONTEND_ROOT / "vite.config.js").read_text()
    assert "'/api': 'http://127.0.0.1:18012'" in config
    assert "'/charts': 'http://127.0.0.1:18012'" in config
    assert "target: 'ws://127.0.0.1:18012'" in config
    assert "18010" not in config, "COIN dev proxy must not route to legacy service"
    print("✅ COIN dev API, charts, and websocket proxies target port 18012")

def test_coin_health_api_identity():
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).get("/api/health")
    assert response.status_code == 200, response.text
    assert response.json().get("product") == "coin"
    print("✅ COIN health API reports the correct product identity")

def test_coin_auth_audience_isolation():
    from backend.users import store

    original_get_secret = store.get_app_secret
    store.get_app_secret = lambda: "coin-regression-test-secret"
    try:
        token = store.sign_uid("usr_coin_test")
        assert store.verify_uid(token) == "usr_coin_test"
        assert store.verify_uid(token, audience="nora_edu") is None
        assert store.verify_uid("invalid-token") is None
    finally:
        store.get_app_secret = original_get_secret
    print("✅ COIN token verifies only for the COIN audience")


def test_coin_change_password_requires_current_password():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    handle = f"pw_{os.urandom(5).hex()}"
    old_password = "old-test-password"
    new_password = "new-test-password"
    created = client.post("/api/users", json={
        "handle": handle,
        "display_name": f"Password Change {handle}",
        "password": old_password,
    })
    assert created.status_code == 200, created.text
    from backend import users
    try:
        users.create_user(
            name=f"PASSWORD CHANGE {handle}",
            handle=f"{handle}_2",
            password=old_password,
        )
    except ValueError as err:
        assert "đã tồn tại" in str(err)
    else:
        raise AssertionError("Duplicate display name was accepted with a distinct handle")

    assert TestClient(app).post("/api/me/password", json={
        "current_password": old_password,
        "new_password": new_password,
    }).status_code == 401
    assert client.post("/api/me/password", json={
        "current_password": "wrong-password",
        "new_password": new_password,
    }).status_code == 401
    assert client.post("/api/me/password", json={
        "current_password": old_password,
        "new_password": "short",
    }).status_code == 422

    changed = client.post("/api/me/password", json={
        "current_password": old_password,
        "new_password": new_password,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"ok": True}
    assert client.post("/api/me/login", json={"handle": handle, "password": old_password}).status_code == 401
    assert client.post("/api/me/login", json={"handle": handle, "password": new_password}).status_code == 200


def test_coin_identity_entry_cannot_impersonate_existing_users():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    handle = f"p1{time.time_ns() % 10**16}"
    disp_name = f"Phase 1 COIN Identity {handle}"
    created = client.post("/api/users", json={
        "handle": handle,
        "display_name": disp_name,
    })
    assert created.status_code == 200, created.text
    original_uid = created.json()["id"]

    handle_login = client.post("/api/me/login", json={"handle": handle})
    assert handle_login.status_code == 400
    assert "coin_session" not in handle_login.cookies

    name_entry = client.post("/api/me/enter", json={"name": disp_name})
    assert name_entry.status_code == 409, name_entry.text
    assert "coin_session" not in name_entry.cookies

    print("✅ COIN handle-only login and duplicate-name quick entry are rejected")

def test_coin_risk_policy_limits():
    from backend.analys.position.position_size import admit_entry, kill_triggered

    allowed = admit_entry(0, 0, 10000, 10000, 0, 0, 3, 1, 1.0)
    assert allowed.can_open and allowed.max_new_notional == 10000

    at_position_limit = admit_entry(3, 0, 10000, 10000, 0, 0, 3, 1, 1.0)
    assert not at_position_limit.can_open

    at_exposure_limit = admit_entry(0, 0, 10000, 10000, 10000, 0, 3, 1, 1.0)
    assert not at_exposure_limit.can_open

    risk_limited = admit_entry(0, 0, 10000, 10000, 0, 50, 3, 1, 1.0, max_open_risk_pct=1.0)
    assert risk_limited.can_open and risk_limited.max_new_risk == 50

    throttled = admit_entry(0, 0, 9000, 10000, 0, 0, 3, 1, 1.0,
                            dd_throttle_pct=10, dd_throttle_floor=0.25)
    assert throttled.can_open and throttled.risk_scale == 0.25
    assert kill_triggered(9000, 10000, 10)
    assert not kill_triggered(9000.01, 10000, 10)
    print("✅ COIN admission, exposure, risk, drawdown throttle, and kill-switch boundaries verified")

def test_coin_job_input_allowlist():
    from backend.jobs.runner import runner

    valid = {
        "code": "class Audit(SimpleAlgorithm): pass",
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-01-02",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "position": {},
        "run_frame": "1h",
    }
    runner._check_params("custom_backtest", valid)
    for kind, params in (
        ("not_a_job", {}),
        ("custom_backtest", {"../../escape": "x"}),
        ("custom_backtest", {**valid, "unexpected": True}),
        ("custom_backtest", {**valid, "initial_capital": math.nan}),
    ):
        try:
            runner._check_params(kind, params)
        except runner.JobError:
            continue
        raise AssertionError(f"Unsafe job input unexpectedly accepted: kind={kind!r}, params={params!r}")
    print("✅ COIN job allowlist, parameter allowlist, and JSON-safe input validation verified")

def test_coin_custom_backtest_api_validation_and_launch():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.routes import studio

    client = TestClient(app)
    launch_calls = []
    original_launch = studio.http_launch
    studio.http_launch = lambda kind, params: launch_calls.append((kind, params)) or {"job_id": "audit-job-1"}
    code = '''class AuditStrategy(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        self.set_positions(close > 0, position=1)
'''
    try:
        invalid = client.post("/api/studio/custom/backtest", json={
            "code": code, "symbols": ["???"], "start": "2025-01-01", "end": "2025-01-02",
        })
        assert invalid.status_code == 422, invalid.text
        assert not launch_calls, "Invalid request must not launch a job"

        valid = client.post("/api/studio/custom/backtest", json={
            "code": code, "symbols": ["BTC"], "start": "2025-01-01", "end": "2025-01-02",
            "train_ratio": 0.8, "initial_capital": 10000, "run_frame": "1h",
        })
        assert valid.status_code == 200, valid.text
        assert valid.json() == {"job_id": "audit-job-1"}
        assert len(launch_calls) == 1 and launch_calls[0][0] == "custom_backtest"
        assert launch_calls[0][1]["symbols"] == ["BTC"]
    finally:
        studio.http_launch = original_launch
    print("✅ COIN custom-backtest API validates input and launches only valid requests")

def test_coin_job_cancel_not_found_contract():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    missing = client.post("/api/studio/book/jobs/20250101_000000_deadbe/cancel")
    assert missing.status_code == 404, missing.text

    invalid = client.post("/api/studio/book/jobs/not-a-job-id/cancel")
    assert invalid.status_code == 422, invalid.text
    print("✅ COIN job cancel returns explicit not-found/invalid-id errors")

def test_coin_trade_metrics_oracle():
    from backend.analys.metrics.trades import NOTE_NO_TRADES, trade_metrics

    rows = [
        {"close_time": 7_200_000, "enter_time": 3_600_000, "pnl_usd": 10.0, "pnl_pct": 10.0,
         "fees_usd": 0.75, "funding_usd": 0.0, "side": "LONG", "layers": 1, "mae_pct": -2.0},
        {"close_time": 14_400_000, "enter_time": 7_200_000, "pnl_usd": -5.0, "pnl_pct": -5.0,
         "fees_usd": 0.25, "funding_usd": 0.0, "side": "SHORT", "layers": 1, "mae_pct": -3.0},
    ]
    metrics = trade_metrics(rows)
    assert metrics["trades"] == 2
    assert metrics["wins"] == 1 and metrics["losses"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["pnl_usd"] == 5.0
    assert metrics["fees_usd"] == 1.0 and metrics["funding_usd"] == 0.0
    assert metrics["avg_hold_h"] == 1.5

    empty = trade_metrics([])
    assert empty["trades"] == 0
    assert empty["win_rate"] is None
    assert empty["profit_factor"] is None
    assert empty["profit_factor_note"] == NOTE_NO_TRADES
    print("✅ COIN trade metrics match an independent two-trade oracle and empty-ledger conventions")


def _synthetic_binance_klines(now_ms, stale_15m_ms=0):
    import numpy as np
    import pandas as pd

    steps = {"15m": 15 * 60_000, "1h": 60 * 60_000, "4h": 4 * 60 * 60_000}
    frames = {}
    for interval, step in steps.items():
        age = stale_15m_ms if interval == "15m" else 0
        last_close = ((now_ms - age) // step) * step
        close_times = last_close - np.arange(999, -1, -1, dtype=np.int64) * step
        index = np.arange(len(close_times), dtype=np.float64)
        close = 100.0 * np.exp(index * 0.0001 + np.sin(index / 11.0) * 0.001)
        frames[interval] = pd.DataFrame({
            "open_time": close_times - step,
            "close_time": close_times,
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.ones(len(close_times)),
        })
    return frames


def test_coin_market_regime_categorical_contract():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.analys.signal.signal import REGIME_NAMES, LABEL_VI
    from backend.routes import data

    client = TestClient(app)
    original_fetch = data._fetch_binance_klines
    frames = _synthetic_binance_klines(int(time.time() * 1000))
    data._fetch_binance_klines = lambda symbol, interval: frames[interval]
    with data._LOCK:
        data._CACHE.clear()
    try:
        res = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert res.status_code == 200, res.text
        payload = res.json()
    finally:
        data._fetch_binance_klines = original_fetch
        with data._LOCK:
            data._CACHE.clear()
    assert payload.get("days") == 7
    assert payload.get("frame") == "15m"
    assert tuple(payload.get("names", [])) == tuple(REGIME_NAMES)
    assert payload.get("labels_vi") == LABEL_VI

    # DEC-05 / COIN-HOME-01: Top-level schema assertions
    assert "as_of" in payload
    assert "as_of_iso" in payload
    assert payload.get("regime") in {"BULL", "BEAR", "RANGE", "VOLATILE", "UNKNOWN"}
    assert payload.get("confidence") is None, "Không đo lường xác suất hậu nghiệm; không được gán confidence giả tạo"
    assert payload.get("cadence_sec") == 60
    assert payload.get("source") == "live_binance_feed"
    assert payload.get("source_type") == "closed_candle"
    assert payload.get("feed_status") in {"active", "stale"}
    assert isinstance(payload.get("is_stale"), bool)

    symbols = payload.get("symbols", [])
    assert isinstance(symbols, list)
    for sym in symbols:
        assert "symbol" in sym
        assert "regime" in sym
        assert "is_stale" in sym
        current = sym.get("current", {})
        state = current.get("state")
        assert state in REGIME_NAMES, f"Unexpected regime state: {state!r}"
        assert current.get("label") == LABEL_VI[state]
        assert "score" not in current, "Regime API must strictly expose discrete categorical states, never an unverified continuous numeric float score"
        assert isinstance(sym.get("strategies_on", []), list)
        assert isinstance(sym.get("strategies_off", []), list)
    print("✅ COIN market regime API strictly adheres to discrete categorical contract with DEC-05 schema")

def test_coin_market_regime_truthful_failure_handling():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    # The service only accepts the configured COIN perpetual universe.
    res = client.get("/api/studio/market/regime?symbols=NONEXISTENT_XYZ&days=7")
    assert res.status_code == 422
    print("✅ COIN live regime rejects symbols outside its configured perpetual universe")

def test_coin_portfolio_dashboard_profit_metric_contract():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    res = client.get("/api/studio/portfolio/dashboard?period=ALL")
    assert res.status_code == 200, res.text
    data = res.json()
    if data.get("available") is not False:
        stats = data.get("stats", {})
        trades = stats.get("trades", {})
        assert "pnl_usd" in trades, "Trades stats must provide authoritative realized pnl_usd"
        assert "trades" in trades, "Trades count must be distinct from profit"
        assert trades["pnl_usd"] != trades["trades"], "Trade count must never be conflated with profit"
        kpis = data.get("kpis", {})
        assert "pnl_today" in kpis
        assert "ret_period_pct" in kpis
    print("✅ COIN portfolio dashboard exposes distinct, authoritative profit and trade metrics")

def test_coin_backtest_resource_caps():
    from backend.jobs.worker import resource

    runner = (COIN_ROOT / "ops" / "run_limited.sh").read_text()
    service = (COIN_ROOT / "ops" / "systemd" / "nora-coin.service").read_text()
    assert 'MEM="${NORA_MEM_MAX:-4G}"' in runner
    assert 'MemoryMax=$MEM' in runner and 'MemorySwapMax=0' in runner
    assert "MemoryMax=4G" in service and "MemorySwapMax=0" in service

    old_paths = resource._cgroup_paths
    old_available = resource.mem_available_mb
    old_reserve = resource.host_reserve_mb
    try:
        with tempfile.TemporaryDirectory() as tmp:
            scope = Path(tmp) / "job.scope"
            parent = Path(tmp) / "nora.slice"
            scope.mkdir()
            parent.mkdir()
            (scope / "memory.max").write_text(str(4 * 1024**3))
            (scope / "memory.current").write_text(str(3 * 1024**3))
            (parent / "memory.max").write_text(str(10 * 1024**3))
            (parent / "memory.current").write_text(str(int(9.5 * 1024**3)))
            resource._cgroup_paths = lambda: [str(scope), str(parent)]
            resource.mem_available_mb = lambda: 100_000.0
            resource.host_reserve_mb = lambda: 0.0
            assert resource.cgroup_limit_mb() == 4096.0
            assert resource.cgroup_usage_mb() == 3072.0
            assert resource.cgroup_free_mb() == 512.0
            assert abs(resource.planning_budget_mb() - 435.2) < 1e-6
    finally:
        resource._cgroup_paths = old_paths
        resource.mem_available_mb = old_available
        resource.host_reserve_mb = old_reserve
    print("✅ COIN backtest resource gate honors per-job and parent cgroup limits")

def test_coin_wfa_folds_oracle_and_boundaries():
    from backend.analys.metrics.wfa import generate_folds, is_score
    import pytest

    # Test OOS non-overlapping boundaries
    start_ts = 1700000000000
    end_ts = start_ts + 200 * 86_400_000
    folds = generate_folds(start_ts, end_ts, train_days=60, test_days=20, step_days=20)
    assert len(folds) >= 5, f"Expected at least 5 folds, got {len(folds)}"
    for i in range(len(folds) - 1):
        assert folds[i]["test_end_ts"] <= folds[i+1]["test_start_ts"], "OOS windows must never overlap"
        assert folds[i]["train_end_ts"] <= folds[i]["test_start_ts"], "IS train window must finish before OOS test start"

    # Test step_days < test_days rejection
    with pytest.raises(ValueError, match="chồng lấp"):
        generate_folds(start_ts, end_ts, train_days=60, test_days=20, step_days=10)

    # Test is_score
    m_few_trades = {"trades": 5, "ret_pct": 25.0, "mdd_pct": 5.0}
    assert is_score(m_few_trades, min_trades=10) is None
    m_valid = {"trades": 15, "ret_pct": 30.0, "mdd_pct": 10.0}
    assert is_score(m_valid, min_trades=10) == 3.0
    print("✅ COIN WFA folds oracle enforces strict non-overlapping boundaries and score calculation")


def test_coin_monte_carlo_oracle_and_reproducibility():
    import pytest
    from backend.analys.metrics.carlo import run_monte_carlo_daily
    from backend.analys.validation.carlo.carlo import evaluate_mc_gate, stress_scenarios

    # 1. Independent Analytical Oracle: Constant positive drift (+1.0% daily for 30 days)
    # Mathematical ground truth:
    # Terminal compounded return: (1.01)^30 - 1 = 34.7848915...% -> rounds to 34.8%
    # Drawdown is identically 0.0% across all paths (every day sets a new peak)
    # Ruin probability must be exactly 0.0%
    pos_returns = [0.01] * 30
    res_pos = run_monte_carlo_daily(pos_returns, simulations=50, block_days=2, horizon_days=30, seed=123)
    assert abs(res_pos["median_ret_pct"] - 34.8) <= 0.1, f"Expected ~34.8%, got {res_pos['median_ret_pct']}"
    assert abs(res_pos["p05_ret_pct"] - 34.8) <= 0.1
    assert res_pos["mdd_p50_pct"] == 0.0, "Constant upward drift must have exactly 0.0% MDD"
    assert res_pos["mdd_p95_pct"] == 0.0
    assert res_pos["p_mdd_ge_ruin_pct"] == 0.0

    # 2. Independent Analytical Oracle: Constant negative drift (-2.0% daily for 10 days)
    # Mathematical ground truth:
    # Terminal compounded return: (0.98)^10 - 1 = -18.2927% -> rounds to -18.3%
    # Maximum Drawdown: (1.0 - 0.98^10) * 100 = 18.2927% -> rounds to 18.3%
    neg_returns = [-0.02] * 10
    res_neg_15 = run_monte_carlo_daily(neg_returns, simulations=50, block_days=2, horizon_days=10, ruin_threshold_pct=15.0, seed=123)
    assert abs(res_neg_15["median_ret_pct"] - (-18.3)) <= 0.1
    assert abs(res_neg_15["mdd_p50_pct"] - 18.3) <= 0.1
    # Since MDD (18.3%) exceeds 15.0% threshold on every path, ruin probability MUST be 100.0%
    assert res_neg_15["p_mdd_ge_ruin_pct"] == 100.0, "Expected 100% ruin probability when MDD exceeds threshold"

    # For ruin threshold of 25.0%, since MDD (18.3%) < 25.0%, ruin probability MUST be 0.0%
    res_neg_25 = run_monte_carlo_daily(neg_returns, simulations=50, block_days=2, horizon_days=10, ruin_threshold_pct=25.0, seed=123)
    assert res_neg_25["p_mdd_ge_ruin_pct"] == 0.0, "Expected 0% ruin probability when MDD is strictly under threshold"

    # 3. Error Handling: Empty returns must fail closed with ValueError
    with pytest.raises(ValueError, match="Cần ít nhất một lợi suất ngày"):
        run_monte_carlo_daily([], simulations=10)

    # 4. Bit-identical seed reproducibility on non-trivial series
    daily_returns = [0.01, -0.005, 0.02, -0.012, 0.004, 0.018, -0.022, 0.007, 0.003, -0.001] * 10
    r1 = run_monte_carlo_daily(daily_returns, simulations=100, block_days=3, horizon_days=60, seed=42)
    r2 = run_monte_carlo_daily(daily_returns, simulations=100, block_days=3, horizon_days=60, seed=42)
    assert r1 == r2, "Monte Carlo with identical seed must produce bit-identical results"

    # Independent arithmetic oracle for compounding, drawdown and explicit extra-cost stress.
    cost_rows = stress_scenarios([0.10, -0.05, 0.0], extra_cost_daily=0.01, with_path=False)
    cost_row = next(row for row in cost_rows if row["name"] == "cost_x2")
    expected_equity = (1.0 + 0.10 - 0.01) * (1.0 - 0.05 - 0.01)
    assert cost_row["terminal_ret_pct"] == pytest.approx((expected_equity - 1.0) * 100.0)
    assert cost_row["mdd_pct"] == pytest.approx(6.0)
    assert cost_row["worst_day_pct"] == pytest.approx(-6.0)

    # Missing measured turnover must remain unavailable and fail the stress gate, never assume a fee.
    unmeasured_rows = stress_scenarios([0.10, -0.05, 0.0], extra_cost_daily=None, with_path=False)
    unmeasured_cost = next(row for row in unmeasured_rows if row["name"] == "cost_x2")
    assert unmeasured_cost["measured"] is False
    assert unmeasured_cost["mdd_pct"] is None
    gate = evaluate_mc_gate(10_000, 0.0, unmeasured_rows)
    assert gate["checks"]["stress_measured"]["passed"] is False

    print("✅ COIN Monte Carlo daily bootstrap matches independent analytical mathematical oracle and seed reproducibility")


def test_coin_prompt_research_registry_and_review_contract():
    import json
    import os
    import shutil
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.studio import research_router, _prompt_alphas_dir
    from backend.analys.alpha.prompt import research, llm
    from backend.users import store

    app = FastAPI(title="Nora COIN API")
    app.include_router(research_router)
    client = TestClient(app)

    # 1. Engine status - Zero secret leak
    resp = client.get("/api/studio/research/engine/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert "provider" in status_data
    assert "model" in status_data
    assert "providers" in status_data
    raw_text = resp.text.lower()
    assert "sk-" not in raw_text
    assert "api_key" not in raw_text or "key_configured" in raw_text

    # 2. Config validate
    valid_resp = client.post("/api/studio/research/config/validate", json={"provider": "builtin_quant", "timeframe": "1h", "side": "both"})
    assert valid_resp.status_code == 200
    assert valid_resp.json()["valid"] is True

    invalid_resp = client.post("/api/studio/research/config/validate", json={"timeframe": "invalid_tf"})
    assert invalid_resp.status_code == 400

    # 3. Prompt Validation Fail-Closed when provider returns None/invalid
    orig_complete = llm.complete
    try:
        llm.complete = lambda **kwargs: None
        val_fail = research.validate_prompt("Một prompt nghiên cứu giả định đủ độ dài ký tự")
        assert val_fail["valid"] is False, "validate_prompt must fail closed when provider returns None"
        assert "không nhận được phản hồi" in val_fail["reason"].lower()

        # The provider contract requires a real JSON boolean; strings and numbers are malformed.
        for malformed_value in ("true", "false", 1, None):
            llm.complete = lambda value=malformed_value, **kwargs: {"valid": value}
            val_malformed = research.validate_prompt("Một prompt nghiên cứu giả định đủ độ dài ký tự")
            assert val_malformed["valid"] is False, f"Provider value {malformed_value!r} must fail closed"
        llm.complete = lambda **kwargs: {"valid": True, "reason": ["not", "a", "string"]}
        val_malformed_reason = research.validate_prompt("Một prompt nghiên cứu giả định đủ độ dài ký tự")
        assert val_malformed_reason["valid"] is False
        assert "reason" in val_malformed_reason["reason"]
        llm.complete = lambda **kwargs: {"valid": True, "reason": "Provider boolean accepted"}
        val_boolean_true = research.validate_prompt("Một prompt nghiên cứu giả định đủ độ dài ký tự")
        assert val_boolean_true["valid"] is True
    finally:
        llm.complete = orig_complete

    # 4. Source Citations Truthfulness (no fabricated verified citations)
    llm.set_mock_completer(lambda **kwargs: {"ideas": [{"id": 1, "name": "Test Idea", "citations": []}]})
    try:
        ideas = research.generate_ideas("Prompt kiểm tra citation rỗng")
        assert len(ideas) > 0
        assert ideas[0]["citations"] == [], "Empty citations must NOT fallback to fabricated verified citations"
    finally:
        llm.set_mock_completer(None)

    # 5. Prompt Alpha Registry & Human Review Authentication and Authorization
    import time
    ts_suffix = str(int(time.time() * 1000))[-6:]
    u_alice = store.create_user(handle=f"al_{ts_suffix}", display_name="Alice Author")
    u_bob = store.create_user(handle=f"bob_{ts_suffix}", display_name="Bob Trader")
    u_reviewer = store.create_user(handle=f"adm_{ts_suffix}", display_name="Senior Reviewer")
    store.update_user(u_reviewer["id"], role="admin")

    alice_id = u_alice["id"]
    bob_id = u_bob["id"]
    reviewer_id = u_reviewer["id"]

    alice_cookie = store.sign_uid(alice_id)
    bob_cookie = store.sign_uid(bob_id)
    reviewer_cookie = store.sign_uid(reviewer_id)

    # Anonymous access is strictly rejected with 401
    anon_list = client.get("/api/studio/research/registry")
    assert anon_list.status_code == 401, "Anonymous registry list must return 401"

    anon_review = client.post("/api/studio/research/registry/some_alpha/review", json={"status": "validated"})
    assert anon_review.status_code == 401, "Anonymous review must return 401"

    pdir = _prompt_alphas_dir()
    test_id = f"test_pa_auth_{time.time_ns()}"
    fpath = os.path.join(pdir, f"{test_id}.json")
    try:
        # Create draft alpha owned by Alice
        draft_record = {
            "id": test_id,
            "name": "Alice Alpha",
            "owner_id": alice_id,
            "status": "draft",
            "hypothesis": {
                "economic_mechanism": "Momentum overflow",
                "falsifiable_conditions": "Sharpe < 0.5",
                "rejection_rules": "MDD > 20%",
            },
            "citations": [{
                "title": "A DOI citation requiring verification",
                "url": "https://doi.org/10.1000/example",
                "doi": "10.1000/example",
                "verified": False,
            }],
            "metrics": {},
        }
        with open(fpath, "x", encoding="utf-8") as fh:
            json.dump(draft_record, fh)

        # Alice sees her own alpha
        alice_client = TestClient(app, cookies={"coin_session": alice_cookie})
        a_list = alice_client.get("/api/studio/research/registry")
        assert a_list.status_code == 200
        assert test_id in [x["id"] for x in a_list.json()]

        # Bob CANNOT see Alice's alpha in his registry list
        bob_client = TestClient(app, cookies={"coin_session": bob_cookie})
        b_list = bob_client.get("/api/studio/research/registry")
        assert b_list.status_code == 200
        assert test_id not in [x["id"] for x in b_list.json()], "Bob must not see Alice's prompt alpha"

        # Bob CANNOT view or delete Alice's alpha directly (403)
        b_detail = bob_client.get(f"/api/studio/research/registry/{test_id}")
        assert b_detail.status_code == 403

        b_verify = bob_client.post(f"/api/studio/research/registry/{test_id}/citations/verify", json={})
        assert b_verify.status_code == 403

        b_del = bob_client.delete(f"/api/studio/research/registry/{test_id}")
        assert b_del.status_code == 403

        # Bob (non-reviewer, non-admin) CANNOT review Alice's alpha (neither rejected nor needs_evidence) -> 403
        bob_reject = bob_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "rejected",
            "reviewer": "Forged Admin Name",
            "review_notes": "Unauthorized review attempt",
        })
        assert bob_reject.status_code == 403, "Non-reviewer must not be able to review another user's alpha"

        # Conflict of Interest: Author Alice CANNOT approve her own alpha to validated (403)
        draft_record["status"] = "tested"
        draft_record["metrics"] = {"simulate": {"total_trades": 25, "sharpe_ratio": 1.4, "total_return": 0.18}}
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(draft_record, fh)

        self_approve = alice_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "validated",
            "review_notes": "Author trying to self-validate own strategy",
        })
        assert self_approve.status_code == 403, "Author must not self-validate own strategy without admin/reviewer role"

        # Reviewer validation checks:
        reviewer_client = TestClient(app, cookies={"coin_session": reviewer_cookie})

        # Insufficient notes (< 10 chars) rejected with 400
        short_notes = reviewer_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "validated",
            "review_notes": "Too short",
        })
        assert short_notes.status_code == 400

        # Insufficient trades (< 10 trades) rejected with 400
        draft_record["metrics"] = {"simulate": {"total_trades": 3, "sharpe_ratio": 1.4, "total_return": 0.18}}
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(draft_record, fh)

        few_trades = reviewer_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "validated",
            "review_notes": "Detailed review notes explaining verification",
        })
        assert few_trades.status_code == 400
        assert "tối thiểu 10 giao dịch" in few_trades.json()["detail"]

        # Valid approval still fails until the saved citation has been checked against Crossref.
        draft_record["metrics"] = {"simulate": {"total_trades": 28, "sharpe_ratio": 1.6, "total_return": 0.22}}
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(draft_record, fh)

        missing_verified_citation = reviewer_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "validated",
            "review_notes": "Verified against out-of-sample data with acceptable risk parameters",
        })
        assert missing_verified_citation.status_code == 400
        assert "citation DOI" in missing_verified_citation.json()["detail"]

        original_verify_citation = research.verify_citation
        def crossref_unavailable(citation):
            import httpx
            request = httpx.Request("GET", "https://api.crossref.org/works/10.1000/example")
            raise httpx.ConnectError("fixture disconnect", request=request)

        try:
            research.verify_citation = crossref_unavailable
            unavailable = alice_client.post(f"/api/studio/research/registry/{test_id}/citations/verify", json={})
            assert unavailable.status_code == 502
            with open(fpath, "r", encoding="utf-8") as fh:
                assert json.load(fh)["citations"][0]["verified"] is False

            research.verify_citation = lambda citation: {
                "doi": "10.1000/example",
                "title": "Canonical Crossref title",
                "publisher": "Crossref Test",
                "published": {"date-parts": [[2020]]},
                "url": "https://doi.org/10.1000/example",
                "authors": [],
                "provider": "Crossref",
                "verified": True,
                "status": "verified",
                "retrieval_time": "2026-10-24T18:00:00+00:00",
                "metadata_sha256": "a" * 64,
            }
            verified_response = alice_client.post(f"/api/studio/research/registry/{test_id}/citations/verify", json={})
        finally:
            research.verify_citation = original_verify_citation
        assert verified_response.status_code == 200, verified_response.text
        assert verified_response.json()["record"]["citations"][0]["provider"] == "Crossref"

        def verify_during_rejection(citation):
            concurrent_rejection = reviewer_client.post(f"/api/studio/research/registry/{test_id}/review", json={
                "status": "rejected",
                "review_notes": "Reviewer rejected while Crossref was being checked",
            })
            assert concurrent_rejection.status_code == 200
            return {
                "doi": "10.1000/example",
                "title": "Canonical Crossref title",
                "publisher": "Crossref Test",
                "published": {"date-parts": [[2020]]},
                "url": "https://doi.org/10.1000/example",
                "authors": [],
                "provider": "Crossref",
                "verified": True,
                "status": "verified",
                "retrieval_time": "2026-10-24T18:00:00+00:00",
                "metadata_sha256": "a" * 64,
            }

        research.verify_citation = verify_during_rejection
        try:
            concurrent_verify = alice_client.post(f"/api/studio/research/registry/{test_id}/citations/verify", json={})
        finally:
            research.verify_citation = original_verify_citation
        assert concurrent_verify.status_code == 200, concurrent_verify.text
        with open(fpath, "r", encoding="utf-8") as fh:
            rejected_after_verify = json.load(fh)
        assert rejected_after_verify["status"] == "rejected"
        assert rejected_after_verify["review"]["reviewer_id"] == reviewer_id
        assert rejected_after_verify["review"]["notes"] == "Reviewer rejected while Crossref was being checked"
        assert rejected_after_verify["citations"][0]["verified"] is True

        rejected_after_verify["status"] = "tested"
        rejected_after_verify.pop("review", None)
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(rejected_after_verify, fh)

        # Client-supplied reviewer string MUST be ignored; identity derived 100% from session
        ok_review = reviewer_client.post(f"/api/studio/research/registry/{test_id}/review", json={
            "status": "validated",
            "reviewer": "Forged Impersonator Name",
            "review_notes": "Verified against out-of-sample data with acceptable risk parameters",
        })
        assert ok_review.status_code == 200
        saved_rec = ok_review.json()["record"]
        assert saved_rec["status"] == "validated"
        assert saved_rec["review"]["reviewer_id"] == reviewer_id
        assert saved_rec["review"]["reviewer"] == "Senior Reviewer", "Reviewer display name must not be forged by caller"

        # Alice can archive and delete her own alpha
        arch_res = alice_client.post(f"/api/studio/research/registry/{test_id}/archive")
        assert arch_res.status_code == 200
        assert arch_res.json()["record"]["status"] == "archived"

        del_res = alice_client.delete(f"/api/studio/research/registry/{test_id}")
        assert del_res.status_code == 200
        assert not os.path.exists(fpath)

        # Ownerless alpha isolation check (policy: hidden from regular users, visible only to admin/reviewer)
        ownerless_id = f"test_pa_ownerless_{time.time_ns()}"
        ownerless_path = os.path.join(pdir, f"{ownerless_id}.json")
        try:
            with open(ownerless_path, "x", encoding="utf-8") as fh:
                json.dump({"id": ownerless_id, "name": "System Alpha", "status": "draft"}, fh)

            bob_list_ownerless = bob_client.get("/api/studio/research/registry").json()
            assert ownerless_id not in [x["id"] for x in bob_list_ownerless], "Ownerless alpha must not be exposed to regular users"
            assert bob_client.get(f"/api/studio/research/registry/{ownerless_id}").status_code == 403

            rev_list_ownerless = reviewer_client.get("/api/studio/research/registry").json()
            assert ownerless_id in [x["id"] for x in rev_list_ownerless], "Ownerless alpha must be visible to admin/reviewer"
        finally:
            if os.path.exists(ownerless_path):
                os.remove(ownerless_path)

    finally:
        if os.path.exists(fpath):
            os.remove(fpath)
        for uid in (alice_id, bob_id, reviewer_id):
            upath = store.users_dir(f"{uid}.json")
            if os.path.exists(upath):
                os.remove(upath)

    print("✅ COIN prompt research registry and review gate enforce authentication, author isolation, and OOS proof")


def test_coin_prompt_research_sources_and_inbox():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # 1. Danh sách nguồn
    src_res = client.get("/api/studio/research/sources")
    assert src_res.status_code == 200
    sources = src_res.json()
    assert len(sources) >= 10
    source_ids = {s["id"] for s in sources}
    assert "arxiv_qfin_tr" in source_ids
    assert "openalex_ts" in source_ids

    # 2. Thu thập nguồn
    collect_res = client.post("/api/studio/research/sources/collect")
    assert collect_res.status_code == 200
    collect_data = collect_res.json()
    assert collect_data.get("ok") is True

    # 3. Lấy hộp thư
    inbox_res = client.get("/api/studio/research/inbox")
    assert inbox_res.status_code == 200
    inbox_data = inbox_res.json()
    assert "stats" in inbox_data
    assert "items" in inbox_data
    assert len(inbox_data["items"]) > 0

    # 4. Lọc hộp thư theo điểm
    filtered_res = client.get("/api/studio/research/inbox?min_score=3")
    assert filtered_res.status_code == 200
    filtered_items = filtered_res.json()["items"]
    for it in filtered_items:
        assert it.get("score", 0) >= 3

    # 5. Cập nhật trạng thái item
    first_item_id = inbox_data["items"][0]["id"]
    status_res = client.post(
        f"/api/studio/research/inbox/{first_item_id}/status",
        json={"status": "interesting"},
    )
    assert status_res.status_code == 200
    assert status_res.json()["item"]["status"] == "interesting"

    # 6. Chuyển thành thẻ ý tưởng (promote)
    promote_res = client.post(f"/api/studio/research/inbox/{first_item_id}/promote")
    assert promote_res.status_code == 200
    card = promote_res.json()
    assert card.get("ok") is True
    assert "prompt_text" in card
    assert "edge" in card
    assert "entry" in card
    assert "exit" in card

    # 7. Bỏ qua lọc
    dismiss_res = client.post(
        "/api/studio/research/inbox/dismiss_filtered",
        json={"min_score": 99},
    )
    assert dismiss_res.status_code == 200
    assert "dismissed_count" in dismiss_res.json()


def test_coin_market_regime_freshness_and_transition_contract():
    import time
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.routes import data

    client = TestClient(app)

    # 1. State to Regime mapping truthfulness
    assert data.STATE_TO_REGIME["TREND_UP"] == "BULL"
    assert data.STATE_TO_REGIME["SURGE"] == "BULL"
    assert data.STATE_TO_REGIME["TREND_DOWN"] == "BEAR"
    assert data.STATE_TO_REGIME["CRASH"] == "BEAR"
    assert data.STATE_TO_REGIME["RANGE"] == "RANGE"
    assert data.STATE_TO_REGIME["VOL_EXPANSION"] == "VOLATILE"
    assert data.STATE_TO_REGIME["UNKNOWN"] == "UNKNOWN"

    # 2. Fresh vs Stale transition testing
    now_ms = int(time.time() * 1000)
    orig_history = data.regime_history

    try:
        # Mocking fresh feed (as_of is 5 minutes ago)
        fresh_as_of = now_ms - (5 * 60 * 1000)
        data.regime_history = lambda symbol, days: {
            "symbol": symbol,
            "as_of": fresh_as_of,
            "as_of_iso": "2026-10-24T18:00:00+00:00",
            "regime": "BULL",
            "is_stale": False,
            "feed_status": "active",
            "source": "live_binance_feed",
            "current": {"state": "TREND_UP", "label": "Tăng xu hướng", "since": fresh_as_of},
            "segments": [],
            "share_pct": {"TREND_UP": 100.0},
            "strategies_on": ["trend_pilot"],
            "strategies_off": [],
        }
        res_fresh = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert res_fresh.status_code == 200
        p_fresh = res_fresh.json()
        assert p_fresh["regime"] == "BULL"
        assert p_fresh["is_stale"] is False
        assert p_fresh["feed_status"] == "active"
        assert p_fresh["confidence"] is None, "Phân loại categorical trên nến đóng, không được bịa xác suất"

        # Mocking stale feed (as_of is 45 minutes ago, > 30m threshold)
        stale_as_of = now_ms - (45 * 60 * 1000)
        data.regime_history = lambda symbol, days: {
            "symbol": symbol,
            "as_of": stale_as_of,
            "as_of_iso": "2026-10-24T17:00:00+00:00",
            "regime": "BEAR",
            "is_stale": True,
            "feed_status": "stale",
            "source": "live_binance_feed",
            "current": {"state": "TREND_DOWN", "label": "Giảm xu hướng", "since": stale_as_of},
            "segments": [],
            "share_pct": {"TREND_DOWN": 100.0},
            "strategies_on": [],
            "strategies_off": ["trend_pilot"],
        }
        res_stale = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert res_stale.status_code == 200
        p_stale = res_stale.json()
        assert p_stale["regime"] == "BEAR"
        assert p_stale["is_stale"] is True
        assert p_stale["feed_status"] == "stale"
        assert p_stale["confidence"] is None

    finally:
        data.regime_history = orig_history

    print("✅ COIN market regime freshness thresholds and categorical transitions verified")


def test_coin_crossref_citation_verification_contract():
    import httpx
    from backend.analys.alpha.prompt import research

    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={
            "message": {
                "DOI": "10.1234/example.doi",
                "title": ["Canonical Crossref work"],
                "publisher": "Test Publisher",
                "published-print": {"date-parts": [[2022, 3]]},
                "URL": "https://doi.org/10.1234/example.doi",
                "author": [{"given": "Test", "family": "Author"}],
            }
        })

    original_get = research.httpx.get
    research.httpx.get = fake_get
    try:
        citation = research.verify_citation({
            "doi": "10.1234/example.doi",
            "url": "https://attacker.invalid/should-not-be-fetched",
            "title": "Untrusted model title",
        })
        assert requested_urls == ["https://api.crossref.org/works/10.1234/example.doi"]
        assert citation["title"] == "Canonical Crossref work"
        assert citation["provider"] == "Crossref"
        assert citation["verified"] is True
        assert citation["status"] == "verified"
        assert len(citation["metadata_sha256"]) == 64
        assert citation["retrieval_time"]

        try:
            research.verify_citation({"url": "https://attacker.invalid/metadata"})
        except ValueError as exc:
            assert "doi.org" in str(exc)
        else:
            raise AssertionError("Arbitrary citation URLs must not be fetched")
        assert len(requested_urls) == 1
    finally:
        research.httpx.get = original_get
    print("✅ Citation verification uses canonical Crossref DOI metadata and rejects arbitrary fetch URLs")


def test_coin_binance_klines_filter_closed_and_reorder_bars():
    import httpx
    from backend.routes import data

    now_ms = int(time.time() * 1000)
    earlier_close = now_ms - 20_000
    later_close = now_ms - 10_000
    unclosed_close = now_ms + 10_000

    def row(close_time, close):
        return [close_time - 900_000, str(close), str(close + 1), str(close - 1), str(close), "1", close_time]

    requested = []
    rows = [
        row(later_close, 102),
        row(earlier_close, 100),
        row(earlier_close, 999),
        row(unclosed_close, 103),
    ]

    def fake_get(url, **kwargs):
        requested.append((url, kwargs))
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json=rows)

    original_get = data.httpx.get
    data.httpx.get = fake_get
    try:
        frame = data._fetch_binance_klines("BTC@perp", "15m")
    finally:
        data.httpx.get = original_get

    assert requested[0][0] == "https://fapi.binance.com/fapi/v1/klines"
    assert requested[0][1]["params"] == {"symbol": "BTCUSDT", "interval": "15m", "limit": 1000}
    assert frame["close_time"].tolist() == [earlier_close + 1, later_close + 1]
    assert frame["close"].tolist() == [100.0, 102.0]
    assert frame["close_time"].max() <= now_ms
    print("✅ Binance feed helper rejects unclosed bars, de-duplicates, sorts, and uses fixed USDⓈ-M host")


def test_coin_live_binance_regime_pipeline_and_feed_errors():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.routes import data
    import httpx

    client = TestClient(app)
    original_fetch = data._fetch_binance_klines
    current_frames = _synthetic_binance_klines(int(time.time() * 1000))
    data._fetch_binance_klines = lambda symbol, interval: current_frames[interval]
    with data._LOCK:
        data._CACHE.clear()
    try:
        active = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert active.status_code == 200, active.text
        active_payload = active.json()
        assert active_payload["source"] == "live_binance_feed"
        assert active_payload["cadence_sec"] == 60
        assert active_payload["feed_status"] == "active"
        assert active_payload["is_stale"] is False
        assert active_payload["as_of"] is not None
        assert active_payload["symbols"][0]["source"] == "live_binance_feed"

        stale_frames = _synthetic_binance_klines(int(time.time() * 1000), stale_15m_ms=45 * 60_000)
        data._fetch_binance_klines = lambda symbol, interval: stale_frames[interval]
        with data._LOCK:
            data._CACHE.clear()
        stale = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert stale.status_code == 200, stale.text
        assert stale.json()["feed_status"] == "stale"
        assert stale.json()["is_stale"] is True

        def disconnected(symbol, interval):
            request = httpx.Request("GET", "https://api.binance.com/api/v3/klines")
            raise httpx.ConnectError("fixture disconnect", request=request)

        data._fetch_binance_klines = disconnected
        with data._LOCK:
            data._CACHE.clear()
        failed = client.get("/api/studio/market/regime?symbols=BTC&days=7")
        assert failed.status_code == 200, failed.text
        failed_payload = failed.json()
        assert failed_payload["feed_status"] == "error"
        assert failed_payload["is_stale"] is True
        assert failed_payload["regime"] == "UNKNOWN"
        assert failed_payload["symbols"][0]["error"]
        assert failed_payload["symbols"][0]["share_pct"] == {}
    finally:
        data._fetch_binance_klines = original_fetch
        with data._LOCK:
            data._CACHE.clear()
    print("✅ COIN regime pipeline uses closed Binance fixtures and reports stale/disconnected states without catalog fallback")


def test_coin_execution_contract_draft_and_inspectable():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.adapter import contracts

    client = TestClient(app)
    res = client.get("/api/studio/live/execution_contract")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["version"] == "1.0.0"
    assert data["status"] == "DRAFT_UNVERIFIED"
    assert data["parameters_authoritative"] is False
    proxy = data["research_cost_proxy"]
    assert proxy["status"] == "APPROVED_PROXY"
    assert proxy["measured"] is False
    assert proxy["promotion_allowed"] is False
    assert proxy["slippage_taker_bps_per_side"]["BTC"] == 3.0
    assert proxy["slippage_taker_bps_per_side"]["ETH"] == 5.0
    assert proxy["stop_slippage_multiplier"] == 2.0
    assert proxy["entry_fill_timing"] == "NEXT_CANDLE_OPEN"
    assert proxy["signal_exit_fill_timing"] == "NEXT_CANDLE_OPEN"
    assert proxy["observed_engine_fill_timing"] == "NEXT_CANDLE_OPEN_SYNTHETIC_QUOTE"
    assert proxy["swing_stress_multiplier"] == 2.0
    assert proxy["scalp_stress_multipliers"] == [2.0, 3.0]
    assert proxy["fee_status"] == "UNVERIFIED"
    assert proxy["funding_status"] == "PARTIAL_PUBLIC_HISTORY"
    assert proxy["next_open_proxy_implemented"] is True
    assert proxy["matching_engine"] == "NAUTILUS_ORDER_MATCHING_ENGINE"
    assert proxy["quote_source"] == "SYNTHETIC_OHLC_OPEN"
    assert proxy["quote_depth_modeled"] is False
    assert proxy["measured_latency"] is False
    assert proxy["execution_implemented"] is False
    assert data["invariants"]["signal_decision_rule"] == "CLOSED_BAR_ONLY"
    assert data["invariants"]["execution_timing"] == "NEXT_CANDLE_OPEN"
    assert data["invariants"]["prohibit_future_data"] is True
    assert data["invariants"]["default_order_type"] == "TAKER"
    assert data["parameters"]["taker_fee_rate"] == 0.0005
    assert data["parameters"]["funding_settlement_hours_utc"] == [0, 8, 16]
    assert data["tolerances"]["fixture_decision_parity"] == 1.0
    assert data["tolerances"]["replay_decision_parity"] == 0.99
    assert data["tolerances"]["max_cost_model_deviation"] == 0.30
    assert data["tolerances"]["max_expectancy_drift"] == 0.30
    print("✅ COIN execution contract is explicitly marked draft and unverified")


def test_coin_parity_verifiers_reject_forged_flags():
    from backend.adapter.contracts import (
        verify_backtest_job_parity,
        verify_candidate_parity_provenance,
    )

    forged_candidate = {
        "id": "forged",
        "provenance": {"parity_verified": True, "parity_contract": "1.0.0"},
    }
    forged_job = {
        "provenance": {"parity_verified": True, "parity_contract": "1.0.0"},
    }
    candidate_ok, candidate_reason = verify_candidate_parity_provenance(forged_candidate)
    job_ok, job_reason = verify_backtest_job_parity(forged_job)
    assert not candidate_ok
    assert not job_ok
    assert "PARITY_VALIDATION_NOT_IMPLEMENTED" in candidate_reason
    assert "PARITY_VALIDATION_NOT_IMPLEMENTED" in job_reason


def test_coin_live_candidate_ignores_stored_parity_flags(monkeypatch, tmp_path):
    from backend.analys.alpha import strategies

    alpha_id = next(iter(strategies.BY_ID))
    main_book = {
        "universe": ["BTC-USDT-SWAP"],
        "timeframe": "1h",
        "strategies": [{
            "id": alpha_id,
            "params": {},
            "evidence": {
                "parity_verified": True,
                "stage_metrics": {
                    "S1_backtest": {
                        "ret_pct": 12.0,
                        "sharpe": 1.2,
                        "parity_verified": True,
                    },
                },
            },
        }],
    }
    monkeypatch.setattr(strategies, "_alpha_dir", lambda: str(tmp_path))
    monkeypatch.setattr(strategies, "get_user_alphas_dir", lambda base: str(tmp_path / "user"))
    monkeypatch.setattr(strategies, "read_json", lambda path: main_book if path.endswith("/book.json") and "/explore/" not in path else {})
    monkeypatch.setattr(strategies, "list_user_alphas", lambda base_dir=None: [])
    monkeypatch.setitem(strategies._CAND_CACHE, "sig", None)
    monkeypatch.setitem(strategies._CAND_CACHE, "rows", [])

    candidates = strategies.live_candidates()
    assert len(candidates) == 1
    assert candidates[0]["promotable"] is False
    assert candidates[0]["quarantine_status"] == "QUARANTINED"
    assert candidates[0]["provenance"]["parity_verified"] is False


def test_coin_live_start_quarantines_stale_pre_parity_candidates(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.routes import live as live_routes

    client = TestClient(app)
    launch_calls = []

    def unexpected_launch(*args, **kwargs):
        launch_calls.append((args, kwargs))
        raise AssertionError("Quarantined strategy must not reach the live job launcher")

    monkeypatch.setattr(live_routes, "launch", unexpected_launch)
    # 1. Kiểm tra API live/candidates gắn nhãn cách ly cho kết quả cũ
    c_res = client.get("/api/studio/live/candidates")
    assert c_res.status_code == 200, c_res.text
    candidates = c_res.json()["candidates"]
    assert len(candidates) > 0, "Cần có ít nhất một candidate để kiểm tra cách ly"
    for cand in candidates:
        assert cand.get("promotable") is False
        assert cand.get("quarantine_status") == "QUARANTINED"
        assert "PARITY_VALIDATION_NOT_IMPLEMENTED" in cand.get("quarantine_reason", "")
        assert cand.get("provenance", {}).get("parity_verified") is False

    # 2. Thử bật bot từ picker với candidate bị cách ly -> Bắt buộc bị từ chối 400
    target = candidates[0]
    picker_launch = client.post("/api/studio/live/bot", json={
        "mode": "paper",
        "from_picker": True,
        "alpha_id": target["id"],
        "signal_tf": target["timeframe"],
        "capital": 1000,
        "symbols": target.get("symbols") or ["BTC-USDT-SWAP"],
    })
    assert picker_launch.status_code == 400, picker_launch.text
    err = picker_launch.json().get("detail", {})
    assert err.get("code") == "ALPHA_RESULT_STALE_OR_UNPROVEN"
    assert "cách ly" in err.get("message", "").lower() or "stale" in err.get("message", "").lower()

    # 3. Thử bật bot trực tiếp không qua picker với alpha cũ -> Cũng bị từ chối 400
    direct_launch = client.post("/api/studio/live/bot", json={
        "mode": "paper",
        "alpha_id": target["id"],
        "capital": 1000,
        "symbols": ["BTC-USDT-SWAP"],
    })
    assert direct_launch.status_code == 400, direct_launch.text
    direct_err = direct_launch.json().get("detail", {})
    assert direct_err.get("code") == "ALPHA_RESULT_STALE_OR_UNPROVEN"

    # 4. Thử bật bot với custom code chưa qua backtest parity -> Bị từ chối 400
    code_launch = client.post("/api/studio/live/bot", json={
        "mode": "paper",
        "code": "def on_bar(): pass",
        "capital": 1000,
    })
    assert code_launch.status_code == 400, code_launch.text
    assert code_launch.json()["detail"]["code"] == "ALPHA_RESULT_STALE_OR_UNPROVEN"

    # 5. A forged parity flag on a stored backtest job must not reach launch.
    from backend.jobs import tasks
    original_picker_get = tasks.picker_backtest_get
    tasks.picker_backtest_get = lambda job_id: {
        "provenance": {"parity_verified": True, "parity_contract": "1.0.0"}
    }
    try:
        job_launch = client.post("/api/studio/live/bot", json={
            "mode": "paper",
            "backtest_job_id": "forged-job",
            "capital": 1000,
        })
    finally:
        tasks.picker_backtest_get = original_picker_get
    assert job_launch.status_code == 400, job_launch.text
    assert job_launch.json()["detail"]["code"] == "ALPHA_RESULT_STALE_OR_UNPROVEN"
    assert launch_calls == []

    print("✅ COIN server-side stale-result quarantine gate actively rejects pre-parity alpha on all bot start paths")


if __name__ == "__main__":
    test_coin_imports_and_routes()
    test_coin_data_isolation()
    test_coin_frontend_build_scripts()
    test_coin_dev_proxy_targets_coin_service()
    test_coin_health_api_identity()
    test_coin_auth_audience_isolation()
    test_coin_change_password_requires_current_password()
    test_coin_identity_entry_cannot_impersonate_existing_users()
    test_coin_risk_policy_limits()
    test_coin_job_input_allowlist()
    test_coin_custom_backtest_api_validation_and_launch()
    test_coin_job_cancel_not_found_contract()
    test_coin_trade_metrics_oracle()
    test_coin_market_regime_categorical_contract()
    test_coin_market_regime_freshness_and_transition_contract()
    test_coin_crossref_citation_verification_contract()
    test_coin_binance_klines_filter_closed_and_reorder_bars()
    test_coin_live_binance_regime_pipeline_and_feed_errors()
    test_coin_execution_contract_draft_and_inspectable()
    test_coin_parity_verifiers_reject_forged_flags()
    test_coin_live_candidate_ignores_stored_parity_flags()
    test_coin_live_start_quarantines_stale_pre_parity_candidates()
    test_coin_backtest_resource_caps()
    test_coin_wfa_folds_oracle_and_boundaries()
    test_coin_monte_carlo_oracle_and_reproducibility()
    test_coin_prompt_research_registry_and_review_contract()
    print("🎉 ALL COIN PROJECT TESTS PASSED!")
