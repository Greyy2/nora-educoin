"""Kiểm thử tính độc lập của dự án nora/coin."""
import os
import json
import math
import sys
import tempfile
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

def test_coin_market_regime_categorical_contract():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.analys.signal.signal import REGIME_NAMES, LABEL_VI

    client = TestClient(app)
    res = client.get("/api/studio/market/regime?symbols=BTC&days=7")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload.get("days") == 7
    assert payload.get("frame") == "15m"
    assert tuple(payload.get("names", [])) == tuple(REGIME_NAMES)
    assert payload.get("labels_vi") == LABEL_VI

    symbols = payload.get("symbols", [])
    assert isinstance(symbols, list)
    for sym in symbols:
        assert "symbol" in sym
        current = sym.get("current", {})
        state = current.get("state")
        assert state in REGIME_NAMES, f"Unexpected regime state: {state!r}"
        assert current.get("label") == LABEL_VI[state]
        assert "score" not in current, "Regime API must strictly expose discrete categorical states, never an unverified continuous numeric float score"
        assert isinstance(sym.get("strategies_on", []), list)
        assert isinstance(sym.get("strategies_off", []), list)
    print("✅ COIN market regime API strictly adheres to discrete categorical contract with no fabricated float scores")

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

if __name__ == "__main__":
    test_coin_imports_and_routes()
    test_coin_data_isolation()
    test_coin_frontend_build_scripts()
    test_coin_dev_proxy_targets_coin_service()
    test_coin_health_api_identity()
    test_coin_auth_audience_isolation()
    test_coin_risk_policy_limits()
    test_coin_job_input_allowlist()
    test_coin_custom_backtest_api_validation_and_launch()
    test_coin_job_cancel_not_found_contract()
    test_coin_trade_metrics_oracle()
    test_coin_market_regime_categorical_contract()
    test_coin_backtest_resource_caps()
    print("🎉 ALL COIN PROJECT TESTS PASSED!")
