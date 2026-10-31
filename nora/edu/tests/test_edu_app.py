"""Kiểm thử tính độc lập của dự án nora/edu."""
import os
import re
import sys
import tempfile
from pathlib import Path

EDU_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDU_ROOT))
os.environ["NORA_DATA_ROOT"] = str(EDU_ROOT / "data")

def test_edu_imports_and_routes():
    from backend.main import app
    assert app is not None
    assert app.title == "Nora EDU API"

    paths = list(app.openapi().get("paths", {}).keys())
    print(f"Total EDU routes: {len(paths)}")
    assert any("/api/edu" in p for p in paths), "Thiếu route /api/edu trong EDU!"
    assert any("/api/studio" in p for p in paths), "Thiếu route /api/studio trong EDU!"
    assert any("/api/users" in p for p in paths), "Thiếu route /api/users trong EDU!"
    assert any("/api/me" in p for p in paths), "Thiếu route /api/me trong EDU!"
    assert not any("/live" in p for p in paths), "Không được có route /live trong EDU!"
    assert not any("/data/crawl" in p for p in paths), "Không được có route crawl trong EDU!"
    print("✅ EDU project routes test passed!")

def test_edu_data_isolation():
    from backend.models.storage import data_home
    home = data_home()
    assert "edu/data" in home or "edu" in home, f"Data root không trỏ vào edu: {home}"
    print(f"✅ EDU data root verified: {home}")

def test_edu_backtest_pipeline():
    """Kiểm thử pipeline load chiến lược hệ thống và biên dịch thuật toán trong EDU."""
    from backend.analys.alpha.code.compile import load_system_strategies, compile_code
    sys_strats = load_system_strategies()
    assert sys_strats and len(sys_strats.get("strategies", [])) > 0, "Không tải được chiến lược hệ thống!"
    print(f"✅ EDU loaded {len(sys_strats['strategies'])} system strategies: {[s['id'] for s in sys_strats['strategies']]}")

    user_code = '''class DemoStrategy(SimpleAlgorithm):
    id = "demo_strat"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 30, position=1)
        self.set_positions(rsi > 70, position=0)
'''
    res = compile_code(user_code)
    assert hasattr(res, "id") or hasattr(res, "name"), f"Biên dịch thất bại: {res}"
    print(f"✅ EDU user strategy compile verified! Program: {getattr(res, 'id', getattr(res, 'name', res))}")

def test_edu_job_boundary_and_isolation():
    """Kiểm thử giới hạn job EDU: từ chối live_bot, kiểm tra ops script và quyền."""
    from backend.jobs.runner import launch, JobError
    from backend.jobs.runner.live import run_live_bot

    # 1. Thử gọi run_live_bot -> Bắt buộc ném PermissionError
    try:
        run_live_bot()
        assert False, "run_live_bot() không được phép chạy trong EDU!"
    except PermissionError:
        print("✅ EDU correctly raised PermissionError on direct run_live_bot call")

    # 2. Thử submit live_bot qua launch() -> Phải bị từ chối bằng JobError
    try:
        launch("live_bot", {"bot_id": "test_bot"})
        assert False, "launch('live_bot') không được phép trong EDU!"
    except JobError as e:
        print(f"✅ EDU correctly rejected forbidden job 'live_bot': {e}")

    # 3. Kiểm tra file script chạy giới hạn của EDU
    runner_script = EDU_ROOT / "ops" / "run_limited.sh"
    assert runner_script.is_file(), f"Thiếu file {runner_script}!"
    assert os.access(runner_script, os.X_OK), f"File {runner_script} chưa có quyền execute (+x)!"
    print(f"✅ EDU local runner script verified: {runner_script}")


def test_edu_backtest_execution():
    """Kiểm thử thực thi backtest thật (Nautilus engine + provenance) trong EDU."""
    from backend.jobs.tasks import run_custom

    code = '''class QuickRsi(SimpleAlgorithm):
    id = "quick_rsi"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)
'''
    params = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "test_start": "2025-01-15",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }
    print("⏳ Đang thực thi real backtest trên nến BTC OKX catalog...")
    res = run_custom(params)
    assert res is not None, "Không nhận được kết quả từ run_custom!"
    assert "metrics" in res, "Kết quả thiếu trường 'metrics'!"
    assert "provenance" in res, "Kết quả thiếu trường 'provenance'!"
    assert "alpha_id" in res, "Kết quả thiếu trường 'alpha_id'!"
    from backend.analys.param import date_ms
    assert res["config"]["test_start"] == "2025-01-15"
    assert res["config"]["split_source"] == "test_start"
    assert res["config"]["effective_train_ratio"] == 0.4375
    assert res["series"]["stage_split"] == date_ms("2025-01-15") // 1000
    assert isinstance(res.get("test_trades"), list)
    assert len(res["test_trades"]) == res["metrics"]["test"]["trades"]
    assert all(trade["enter_time"] >= date_ms("2025-01-15") for trade in res["test_trades"])
    prov = res["provenance"]
    sim_m = res["metrics"]["simulate"]
    print(f"✅ EDU real backtest executed successfully! Alpha ID: {res['alpha_id']}")
    print(f"   Provenance: engine={prov.get('engine')} version={prov.get('engine_version')}")
    assert prov.get("slippage_modeled") is True
    assert prov.get("slippage_measured") is False
    assert prov.get("research_cost_proxy") == "SYNTHETIC_OHLC_OPEN_SPREAD"
    assert prov.get("quote_depth_modeled") is False
    print(f"   Metrics (simulate): trades={sim_m.get('trades')}, pnl={sim_m.get('ret_pct')}%, mdd={sim_m.get('mdd_pct')}%")
    assert sim_m.get("trades") is not None and sim_m.get("trades") > 0, "Thiếu số lệnh trong metrics.simulate!"
    assert sim_m.get("ret_pct") is not None, "Thiếu PnL trong metrics.simulate!"


def test_edu_custom_backtest_exact_test_start_validation():
    from backend.jobs.runner import KINDS, JobError
    from backend.routes.studio import CustomBacktestRequest, build_job

    code = '''class DemoStrategy(SimpleAlgorithm):
    id = "exact_split"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        self.set_positions(close > 0, position=1)
'''
    params = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "test_start": "2025-01-15",
    }

    request = CustomBacktestRequest(**params)
    assert request.test_start == "2025-01-15"
    assert "test_start" in KINDS["custom_backtest"]["params"]
    built = build_job("custom_backtest", params)
    assert built["test_start"] == "2025-01-15"

    for invalid_test_start in ("2024-12-31", "2025-02-02"):
        try:
            build_job("custom_backtest", {**params, "test_start": invalid_test_start})
        except JobError:
            continue
        raise AssertionError(f"Invalid test_start was accepted: {invalid_test_start}")


def test_edu_bounded_scan_runs_steps_sequentially():
    from backend.jobs.tasks import CUSTOM_BACKTEST_DEFAULTS, run_sequential

    order = []

    def step(name):
        def run(loaded):
            assert not loaded.is_set()
            order.append(name)
            return name
        return run

    result = run_sequential([("main", step("main")), ("test", step("test"))])
    assert order == ["main", "test"]
    assert result == {"main": "main", "test": "test"}
    assert CUSTOM_BACKTEST_DEFAULTS["include_benchmark"] is True
    assert CUSTOM_BACKTEST_DEFAULTS["include_diagnostics"] is True
    assert CUSTOM_BACKTEST_DEFAULTS["parallel_runs"] is True

    def fail(_loaded):
        raise RuntimeError("expected test failure")

    skipped = run_sequential([("main", fail), ("test", step("should-not-run"))])
    assert isinstance(skipped["main"], RuntimeError)
    assert "test" not in skipped
    assert order == ["main", "test"]


def test_edu_import_origin_isolation():
    """Kiểm tra nguồn gốc import: tất cả module backend.* phải nằm trong nora/edu/backend/."""
    edu_backend_prefix = str(EDU_ROOT / "backend")
    root_backend_prefix = str(EDU_ROOT.parent / "backend")
    coin_backend_prefix = str(EDU_ROOT.parent / "coin" / "backend")

    violations = []
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("backend.") or mod_name == "backend":
            mod_file = getattr(mod, "__file__", None)
            if mod_file:
                mod_file = os.path.abspath(mod_file)
                if mod_file.startswith(root_backend_prefix) and not mod_file.startswith(edu_backend_prefix):
                    violations.append(f"{mod_name} -> {mod_file} (từ root backend!)")
                elif mod_file.startswith(coin_backend_prefix):
                    violations.append(f"{mod_name} -> {mod_file} (từ COIN backend!)")
    assert not violations, f"Phát hiện module backend không nằm trong EDU: {violations}"
    print(f"✅ EDU import origin isolation verified! (0 violations across {len([m for m in sys.modules if m.startswith('backend')])} backend modules)")


def test_edu_job_smoke_and_path_traversal():
    """Chạy một smoke job qua launch(), xác nhận file tạo đúng trong edu/data/cache/process/ và chặn path traversal."""
    from backend.jobs.runner import launch, status, job_dir, JobError

    # 1. Chặn path traversal với param độc hại
    try:
        launch("presets_build", {"../../evil": "escape"})
        assert False, "launch() phải từ chối tham số lạ / path traversal!"
    except JobError:
        print("✅ EDU correctly rejected malicious param keys")

    # 2. Khởi chạy 1 job hợp lệ của EDU (custom_backtest)
    code = '''class QuickRsi(SimpleAlgorithm):
    id = "quick_rsi"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)
'''
    params = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }
    job_id = launch("custom_backtest", params)
    assert job_id and "/" not in job_id and "\\" not in job_id, f"job_id không hợp lệ: {job_id}"

    d = job_dir(job_id)
    assert d.startswith(str(EDU_ROOT / "data")), f"Thư mục job nằm ngoài EDU data: {d}"
    assert os.path.realpath(d).startswith(str(EDU_ROOT / "data")), f"Symlink escape: {os.path.realpath(d)}"
    assert os.path.isdir(d), f"Thư mục job không tồn tại: {d}"
    assert os.path.isfile(os.path.join(d, "params.json")), "Thiếu params.json"
    assert os.path.isfile(os.path.join(d, "job.json")), "Thiếu job.json"

    # Chờ tiến trình worker hoàn tất đến trạng thái done
    import time
    final_status = None
    final_st = None
    for _ in range(60):
        st = status(job_id)
        if st:
            final_st = st
            final_status = st.get("status")
            if final_status in ("done", "succeeded"):
                break
        time.sleep(1)

    assert final_status in ("done", "succeeded"), f"Job chưa hoàn tất (trạng thái: {final_status})"
    assert final_st and final_st.get("result") is not None, "Kết quả job thiếu result.json!"
    print(f"✅ EDU smoke job executed and verified in edu/data: job_id={job_id}, status={final_status}")


def test_edu_api_job_lifecycle():
    """Kiểm tra toàn diện API endpoints submit, status, cancel qua FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # 1. Defaults endpoint
    res_def = client.get("/api/studio/custom/defaults")
    assert res_def.status_code == 200, f"Lỗi get defaults: {res_def.text}"
    defaults = res_def.json()
    assert "symbols" in defaults and "start" in defaults
    assert defaults.get("available_symbols"), "Defaults API phải công bố toàn bộ tài sản khả dụng riêng với rổ mặc định"
    print(f"✅ EDU API GET /api/studio/custom/defaults passed (symbols: {len(defaults.get('symbols', []))})")

    # 2. Submit custom backtest qua API
    code = '''class ApiRsi(SimpleAlgorithm):
    id = "api_rsi"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 30, position=1)
        self.set_positions(rsi > 70, position=0)
'''
    body = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }
    res_sub = client.post("/api/studio/custom/backtest", json=body)
    assert res_sub.status_code == 200, f"Submit backtest qua API thất bại: {res_sub.text}"
    job_info = res_sub.json()
    assert "job_id" in job_info
    job_id = job_info["job_id"]
    print(f"✅ EDU API POST /api/studio/custom/backtest passed: job_id={job_id}")

    # 3. GET /api/studio/jobs/{job_id}
    res_st = client.get(f"/api/studio/jobs/{job_id}")
    assert res_st.status_code == 200, f"Get job status qua API thất bại: {res_st.text}"
    job_snap = res_st.json()
    assert job_snap.get("id") == job_id
    assert job_snap.get("kind") == "custom_backtest"
    print(f"✅ EDU API GET /api/studio/jobs/{job_id} passed (status: {job_snap.get('status')})")

    # 4. GET /api/studio/jobs
    res_list = client.get("/api/studio/jobs?limit=10")
    assert res_list.status_code == 200, f"List jobs qua API thất bại: {res_list.text}"
    jobs_list = res_list.json().get("jobs", [])
    assert any(j.get("id") == job_id for j in jobs_list), f"job_id {job_id} không có trong danh sách jobs!"
    print(f"✅ EDU API GET /api/studio/jobs passed (found submitted job in list of {len(jobs_list)} jobs)")

    # 5. POST /api/studio/jobs/{job_id}/cancel
    res_cancel = client.post(f"/api/studio/jobs/{job_id}/cancel")
    # Cancel có thể thành công 200 hoặc 409 nếu job đã kết thúc
    assert res_cancel.status_code in (200, 409), f"Lỗi cancel job: {res_cancel.text}"
    print(f"✅ EDU API POST /api/studio/jobs/{job_id}/cancel verified (status_code: {res_cancel.status_code})")


def test_edu_auth_token_audience_isolation():
    """Kiểm thử cô lập chữ ký token/cookie theo product audience (Gate Workstream 4)."""
    from backend.users.store import sign_uid, verify_uid

    test_uid = "usr_edu_9999"

    # 1. Ký token với audience của EDU
    edu_token = sign_uid(test_uid)
    assert verify_uid(edu_token) == test_uid, "Verify token EDU hợp lệ thất bại!"

    # 2. Đưa token EDU sang verify với audience COIN -> BẮT BUỘC trả về None
    assert verify_uid(edu_token, audience="nora_coin") is None, "Lỗ hổng: Token EDU được chấp nhận bởi COIN audience!"

    # 3. Giả lập token COIN được ký
    coin_token = sign_uid(test_uid, audience="nora_coin")
    # Đưa token COIN vào verify trong EDU -> BẮT BUỘC trả về None
    assert verify_uid(coin_token) is None, "Lỗ hổng: Token COIN được chấp nhận bởi EDU audience!"

    print("✅ EDU auth token audience isolation verified! (Cross-product token use is 100% blocked)")


def test_edu_golden_parity():
    """Kiểm thử đối chiếu Golden Parity giữa Engine Monolith gốc và Engine EDU (Gate 2)."""
    import subprocess
    import json
    from backend.jobs.tasks import run_custom as edu_run_custom

    code = '''class QuickRsi(SimpleAlgorithm):
    id = "quick_rsi"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)
'''
    params = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }
    edu_res = edu_run_custom(params)
    edu_sim = edu_res["metrics"]["simulate"]

    # Chạy trực tiếp engine Monolith gốc để đối soát live 1:1
    mono_runner_script = f"""
import sys, json
sys.path.insert(0, '/home/vmc03/norabt/nora/coin')
from backend.jobs.tasks import run_custom
params = json.loads({repr(json.dumps(params))})
res = run_custom(params)
print('__JSON_PARITY__:' + json.dumps(res['metrics']['simulate']))
"""
    cmd = ["/home/vmc03/.venvs/nora312/bin/python", "-c", mono_runner_script]
    mono_out = subprocess.check_output(cmd, text=True)
    json_line = [ln for ln in mono_out.splitlines() if ln.startswith('__JSON_PARITY__:')][0]
    mono_sim = json.loads(json_line.replace('__JSON_PARITY__:', ''))

    # Golden baseline after applying the same native stop-loss proxy as COIN.
    # Nautilus account balance already includes realized PnL; the portfolio
    # equity curve must not add the realized accumulator a second time.
    GOLDEN_ORACLE = {
        "trades": 11,
        "ret_pct": -1.4,
        "mdd_pct": 2.25,
        "win_rate_trades": 36.4,
        "fees_usd": 17.95,
    }
    for field, expected in GOLDEN_ORACLE.items():
        assert abs(float(edu_sim[field]) - expected) < 1e-4, f"EDU {field}={edu_sim[field]} vs golden={expected}"
        assert abs(float(mono_sim[field]) - expected) < 1e-4, f"COIN {field}={mono_sim[field]} vs golden={expected}"

    print(f"✅ EDU/COIN golden parity verified: trades={edu_sim['trades']}, pnl={edu_sim['ret_pct']}%, mdd={edu_sim['mdd_pct']}%")


def test_edu_api_to_worker_e2e_and_ownership():
    """Kiểm thử API -> Worker -> Done -> Result có phân quyền và kiểm soát ownership (Gate 2)."""
    import time
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.users.store import sign_uid

    client = TestClient(app)
    alice_token = sign_uid("usr_alice")
    bob_token = sign_uid("usr_bob")

    code = '''class QuickRsi(SimpleAlgorithm):
    id = "quick_rsi"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)
'''
    body = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }

    # 1. Alice submit custom backtest qua API
    headers_alice = {"Cookie": f"edu_session={alice_token}"}
    res_sub = client.post("/api/studio/custom/backtest", json=body, headers=headers_alice)
    assert res_sub.status_code == 200, f"Submit failed: {res_sub.text}"
    job_id = res_sub.json()["job_id"]

    # 2. Bob cố huỷ job của Alice -> BẮT BUỘC nhận HTTP 403 Forbidden
    headers_bob = {"Cookie": f"edu_session={bob_token}"}
    res_unauth_cancel = client.post(f"/api/studio/jobs/{job_id}/cancel", headers=headers_bob)
    assert res_unauth_cancel.status_code == 403, f"Lỗ hổng: Kỳ vọng 403 Forbidden nhưng nhận {res_unauth_cancel.status_code}: {res_unauth_cancel.text}"
    print(f"✅ Ownership isolation verified: unauthorized cancel strictly rejected with 403 Forbidden")

    # 3. Chờ worker hoàn tất đến trạng thái done
    done = False
    final_data = None
    for _ in range(60):
        st_res = client.get(f"/api/studio/jobs/{job_id}", headers=headers_alice)
        if st_res.status_code == 200:
            final_data = st_res.json()
            if final_data.get("status") == "done":
                done = True
                break
        time.sleep(1)

    assert done and isinstance(final_data, dict), f"Job không kết thúc với trạng thái done! Dữ liệu: {final_data}"
    assert final_data.get("result") is not None, "Kết quả trả về không có result.json!"
    sim = final_data["result"]["metrics"]["simulate"]
    assert sim.get("trades") == 11, f"Lệnh trong result không đúng: {sim.get('trades')}"
    prov = final_data["result"].get("provenance", {})
    assert prov.get("engine") == "nautilus_trader"
    print(f"✅ EDU API -> Worker -> Result E2E verified with full metrics & provenance!")


def test_edu_secret_isolation():
    """Chứng minh EDU không tiếp cận, không nạp và không đọc được exchange secrets (Gate 4)."""
    # 1. Tiến trình test không có secret
    for forbidden_key in ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"]:
        assert forbidden_key not in os.environ, f"Phát hiện secret cấm trong EDU environment: {forbidden_key}!"

    # 2. Kiểm tra service config EDU không có dòng trỏ vào okx.env
    edu_service_file = EDU_ROOT / "ops" / "systemd" / "nora-edu.service"
    if edu_service_file.exists():
        content = edu_service_file.read_text(encoding="utf-8")
        assert "okx.env" not in content, f"Service unit EDU có chứa tham chiếu okx.env: {edu_service_file}"

    # 3. Kiểm tra app.env nạp vào EDU chỉ chứa NORA_APP_SECRET, không có bất kỳ exchange secret nào
    app_env_path = Path(os.path.expanduser("~/.config/nora/app.env"))
    if app_env_path.exists():
        for line in app_env_path.read_text(encoding="utf-8").splitlines():
            k = line.split("=", 1)[0].strip()
            assert not any(forbidden in k.upper() for forbidden in ["OKX", "BINANCE", "API_KEY", "SECRET_KEY", "PASSPHRASE"]), f"Phát hiện secret giao dịch trong app.env: {k}"

    print("✅ EDU exchange secret isolation verified! (Zero access to OKX API keys/secrets in env or unit)")

def test_edu_backtest_resource_caps():
    from backend.jobs.worker import resource

    runner = (EDU_ROOT / "ops" / "run_limited.sh").read_text()
    service = (EDU_ROOT / "ops" / "systemd" / "nora-edu.service").read_text()
    assert 'MEM="${NORA_MEM_MAX:-2G}"' in runner
    assert 'MemoryMax=$MEM' in runner and 'MemorySwapMax=0' in runner
    assert "MemoryMax=2G" in service and "MemorySwapMax=0" in service

    old_paths = resource._cgroup_paths
    old_available = resource.mem_available_mb
    old_reserve = resource.host_reserve_mb
    try:
        with tempfile.TemporaryDirectory() as tmp:
            scope = Path(tmp) / "job.scope"
            parent = Path(tmp) / "nora.slice"
            scope.mkdir()
            parent.mkdir()
            (scope / "memory.max").write_text(str(2 * 1024**3))
            (scope / "memory.current").write_text(str(1536 * 1024**2))
            (parent / "memory.max").write_text(str(10 * 1024**3))
            (parent / "memory.current").write_text(str(9 * 1024**3))
            resource._cgroup_paths = lambda: [str(scope), str(parent)]
            resource.mem_available_mb = lambda: 100_000.0
            resource.host_reserve_mb = lambda: 0.0
            assert resource.cgroup_limit_mb() == 2048.0
            assert resource.cgroup_usage_mb() == 1536.0
            assert resource.cgroup_free_mb() == 512.0
            assert abs(resource.planning_budget_mb() - 435.2) < 1e-6
    finally:
        resource._cgroup_paths = old_paths
        resource.mem_available_mb = old_available
        resource.host_reserve_mb = old_reserve
    print("✅ EDU backtest resource gate honors per-job and parent cgroup limits")


def test_edu_account_bootstrap_and_lifecycle():
    """Kiểm thử chu trình tài khoản EDU (Phase 1 Gate: edu-account-bootstrap):
    - Đăng ký tài khoản mới POST /api/users
    - Bắt lỗi trùng lặp handle (409 Conflict)
    - Cơ chế Onboarding POST /api/me/enter (chỉ dùng cho onboarding/quick-entry, không phải secure password auth)
    - Trạng thái phiên GET /api/me
    - Đăng xuất POST /api/me/logout xóa cookie phiên
    """
    import time
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # 1. Ban đầu chưa đăng nhập: GET /api/me trả {"user": null}
    res_me_init = client.get("/api/me")
    assert res_me_init.status_code == 200
    assert res_me_init.json().get("user") is None

    # 2. Tạo tài khoản mới hợp lệ POST /api/users
    unique_handle = f"learner_{int(time.time() * 1000) % 100000}"
    create_body = {
        "handle": unique_handle,
        "display_name": f"Học Viên {unique_handle}",
        "bio": "Nghiên cứu thuật toán",
        "avatar": {"emoji": "🎓", "color": "#4f8ef7"},
    }
    res_create = client.post("/api/users", json=create_body)
    assert res_create.status_code == 200, f"Tạo tài khoản thất bại: {res_create.text}"
    user_data = res_create.json()
    assert user_data["handle"] == unique_handle
    uid = user_data["id"]
    assert "edu_session" in res_create.cookies or "nora_uid" in res_create.cookies

    # 3. Thử tạo lại với trùng handle -> BẮT BUỘC nhận HTTP 409 Conflict
    res_dup = client.post("/api/users", json=create_body)
    assert res_dup.status_code == 409, f"Kỳ vọng 409 Conflict cho trùng handle nhưng nhận {res_dup.status_code}"

    # 4. Kiểm tra session sau khi tạo: GET /api/me bằng cookie vừa nhận
    session_cookie = res_create.cookies.get("edu_session") or res_create.cookies.get("nora_uid")
    headers = {"Cookie": f"edu_session={session_cookie}"}
    res_me_auth = client.get("/api/me", headers=headers)
    assert res_me_auth.status_code == 200
    assert res_me_auth.json().get("user", {}).get("id") == uid

    # 5. Ngăn chặn hoàn toàn chiếm quyền tài khoản (Account Takeover Protection):
    # a) Đăng nhập chỉ bằng handle POST /api/me/login BẮT BUỘC nhận 400 Bad Request
    res_login_handle = client.post("/api/me/login", json={"handle": unique_handle})
    assert res_login_handle.status_code == 400, f"Lỗ hổng: Đăng nhập được bằng handle trơn! status: {res_login_handle.status_code}"

    # b) Quick-enter rejects an existing name instead of creating a duplicate or taking over its account.
    res_enter_exist = client.post("/api/me/enter", json={"name": f"Học Viên {unique_handle}"})
    assert res_enter_exist.status_code == 409
    assert "edu_session" not in res_enter_exist.cookies

    # c) Nhập tên chưa từng có -> tự động tạo user mới
    new_name = f"Người Mới {int(time.time() * 1000) % 100000}"
    res_enter_new = client.post("/api/me/enter", json={"name": new_name})
    assert res_enter_new.status_code == 200
    new_uid = res_enter_new.json().get("user", {}).get("id")
    assert new_uid != uid

    # 6. Đăng xuất POST /api/me/logout
    res_logout = client.post("/api/me/logout", headers=headers)
    assert res_logout.status_code == 200
    assert res_logout.json().get("ok") is True

    print("✅ EDU account bootstrap & session lifecycle verified (Create, 409 duplicate, No takeover via handle or name, Enter, Logout)")


def test_edu_google_oauth_readiness_and_absence():
    """Kiểm tra điều kiện Google OAuth (Phase 1 Gate: edu-google-oauth-readiness):
    - Kiểm tra cấu hình và secrets thực của Google OAuth
    - Khẳng định khi chưa có client_id / secret / callback flow thật thì nút Google và endpoint stub KHÔNG ĐƯỢC PHÉP hiển thị hay giả lập
    """
    # 1. Xác nhận không có credentials giả/lộ trong env
    for k in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_SECRET"]:
        assert not os.environ.get(k), f"Cảnh báo: Phát hiện biến {k} trong môi trường test"

    # 2. Xác nhận OpenAPI của EDU không có route OAuth giả lập (stub endpoint)
    from backend.main import app
    paths = app.openapi().get("paths", {})
    oauth_paths = [p for p in paths if "oauth" in p.lower() or "google" in p.lower()]
    assert not oauth_paths, f"Phát hiện endpoint OAuth chưa được bảo vệ / stub trong EDU: {oauth_paths}"

    # 3. Xác nhận file frontend EnterForm.jsx không chứa nút Google khi chưa cấu hình OAuth thật
    frontend_enter_form = EDU_ROOT / "frontend" / "src" / "components" / "user" / "EnterForm.jsx"
    if frontend_enter_form.exists():
        content = frontend_enter_form.read_text(encoding="utf-8")
        assert "google" not in content.lower(), "Nút Google OAuth giả lập không được phép xuất hiện trong frontend EnterForm!"

    print("✅ EDU Google OAuth readiness verified: No fake/stub button or endpoints; blocked pending real OAuth config")


def test_edu_guest_backtest_policy_and_isolation():
    """Kiểm tra chính sách chạy backtest cho khách vãng lai và phân quyền đọc/huỷ job (Phase 1 Gate: edu-guest-backtest-policy):
    - Cho phép khách chưa đăng nhập gửi job custom backtest trên engine EDU
    - Mỗi khách có định danh/phiên guest riêng biệt (gst_<hex>), không dùng chung một owner toàn cục
    - Giới hạn lạm dụng khách: tối đa 1 job chạy/chờ cho mỗi khách (429 Too Many Requests)
    - Phân quyền đọc job nghiêm ngặt:
        * GET /api/studio/jobs chỉ liệt kê các job thuộc sở hữu của người gọi (Alice chỉ thấy Alice, Bob chỉ thấy Bob, Khách chỉ thấy Khách của mình)
        * GET /api/studio/jobs/{job_id} trả về 404 Not Found nếu người gọi không phải chủ sở hữu (chống quét ID và rò rỉ metadata/log/result/ETag)
    - Phân quyền huỷ job:
        * 403 Forbidden khi khách thử huỷ job của Alice hoặc Bob
        * 403 Forbidden khi Alice thử huỷ job của khách
        * 403 Forbidden khi Khách 1 thử huỷ job của Khách 2
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.users.store import sign_uid

    client = TestClient(app)
    alice_token = sign_uid("usr_alice_phase1")
    bob_token = sign_uid("usr_bob_phase1")

    code = '''class DemoGuest(SimpleAlgorithm):
    id = "demo_guest"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 30, position=1)
        self.set_positions(rsi > 70, position=0)
'''
    body = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }

    # 1. Alice gửi job
    res_alice = client.post("/api/studio/custom/backtest", json=body, headers={"Cookie": f"edu_session={alice_token}"})
    assert res_alice.status_code == 200
    alice_job_id = res_alice.json()["job_id"]

    # 2. Bob gửi job
    res_bob = client.post("/api/studio/custom/backtest", json=body, headers={"Cookie": f"edu_session={bob_token}"})
    assert res_bob.status_code == 200
    bob_job_id = res_bob.json()["job_id"]

    # 3. Phân quyền danh sách job (GET /api/studio/jobs):
    # Alice gọi -> thấy job của Alice, KHÔNG thấy job của Bob
    res_alice_jobs = client.get("/api/studio/jobs", headers={"Cookie": f"edu_session={alice_token}"})
    assert res_alice_jobs.status_code == 200
    alice_jids = [j["id"] for j in res_alice_jobs.json().get("jobs", [])]
    assert alice_job_id in alice_jids
    assert bob_job_id not in alice_jids

    # Bob gọi -> thấy job của Bob, KHÔNG thấy job của Alice
    res_bob_jobs = client.get("/api/studio/jobs", headers={"Cookie": f"edu_session={bob_token}"})
    assert res_bob_jobs.status_code == 200
    bob_jids = [j["id"] for j in res_bob_jobs.json().get("jobs", [])]
    assert bob_job_id in bob_jids
    assert alice_job_id not in bob_jids

    # 4. Phân quyền đọc chi tiết / kết quả job (GET /api/studio/jobs/{job_id}):
    # Alice đọc job của mình -> 200 OK
    res_alice_read_own = client.get(f"/api/studio/jobs/{alice_job_id}", headers={"Cookie": f"edu_session={alice_token}"})
    assert res_alice_read_own.status_code == 200
    assert res_alice_read_own.json().get("params", {}).get("owner_uid") == "usr_alice_phase1"

    # Bob đọc job của Alice -> BẮT BUỘC nhận 404 (không làm lộ sự tồn tại của job)
    res_bob_read_alice = client.get(f"/api/studio/jobs/{alice_job_id}", headers={"Cookie": f"edu_session={bob_token}"})
    assert res_bob_read_alice.status_code == 404, f"Lỗ hổng: Bob đọc được job của Alice! status: {res_bob_read_alice.status_code}"

    # Alice đọc job của Bob -> BẮT BUỘC nhận 404
    res_alice_read_bob = client.get(f"/api/studio/jobs/{bob_job_id}", headers={"Cookie": f"edu_session={alice_token}"})
    assert res_alice_read_bob.status_code == 404, f"Lỗ hổng: Alice đọc được job của Bob! status: {res_alice_read_bob.status_code}"

    # 5. Khách 1 (chưa đăng nhập, có cookie riêng) gửi job
    client_guest1 = TestClient(app)
    res_guest1 = client_guest1.post("/api/studio/custom/backtest", json=body)
    assert res_guest1.status_code == 200, f"Khách 1 không gửi được job: {res_guest1.text}"
    g1_job_id = res_guest1.json()["job_id"]
    g1_cookie = client_guest1.cookies.get("edu_guest_id")
    assert g1_cookie and re.fullmatch(r"gst_[a-f0-9]{32}", g1_cookie), f"Guest capability không hợp lệ: {g1_cookie}"

    # Khách 1 đọc job của chính mình -> 200 OK
    res_g1_read_own = client_guest1.get(f"/api/studio/jobs/{g1_job_id}")
    assert res_g1_read_own.status_code == 200
    assert res_g1_read_own.json().get("params", {}).get("owner_uid") == g1_cookie

    # 6. Khách 2 (phiên khác) không được phép đọc job của Khách 1 -> 404
    client_guest2 = TestClient(app)
    # Trigger cookie riêng cho guest 2
    res_guest2 = client_guest2.get("/api/studio/jobs")
    g2_cookie = client_guest2.cookies.get("edu_guest_id")
    assert g2_cookie != g1_cookie

    res_g2_read_g1 = client_guest2.get(f"/api/studio/jobs/{g1_job_id}")
    assert res_g2_read_g1.status_code == 404, f"Lỗ hổng: Khách 2 đọc được job của Khách 1! status: {res_g2_read_g1.status_code}"

    # Khách 2 không thấy job của Khách 1 trong list
    res_g2_jobs = client_guest2.get("/api/studio/jobs")
    g2_jids = [j["id"] for j in res_g2_jobs.json().get("jobs", [])]
    assert g1_job_id not in g2_jids

    # 7. Huỷ chéo (Cancel Protection):
    # Khách 1 thử huỷ job của Alice -> 403
    res_g1_cancel_alice = client_guest1.post(f"/api/studio/jobs/{alice_job_id}/cancel")
    assert res_g1_cancel_alice.status_code == 403, f"Lỗ hổng: Khách huỷ được job của Alice! status: {res_g1_cancel_alice.status_code}"

    # Alice thử huỷ job của Khách 1 -> 403
    res_alice_cancel_g1 = client.post(f"/api/studio/jobs/{g1_job_id}/cancel", headers={"Cookie": f"edu_session={alice_token}"})
    assert res_alice_cancel_g1.status_code == 403, f"Lỗ hổng: Alice huỷ được job của khách! status: {res_alice_cancel_g1.status_code}"

    # Khách 2 thử huỷ job của Khách 1 -> 403
    res_g2_cancel_g1 = client_guest2.post(f"/api/studio/jobs/{g1_job_id}/cancel")
    assert res_g2_cancel_g1.status_code == 403, f"Lỗ hổng: Khách 2 huỷ được job của Khách 1! status: {res_g2_cancel_g1.status_code}"

    # 8. Chống lạm dụng khách (Concurrency / Abuse Limit):
    # Khách 1 gửi tiếp job thứ 2 khi job 1 đang chạy/chờ -> BẮT BUỘC nhận 429 Too Many Requests
    res_g1_second = client_guest1.post("/api/studio/custom/backtest", json=body)
    assert res_g1_second.status_code == 429, f"Kỳ vọng 429 khi khách gửi spam job đồng thời nhưng nhận: {res_g1_second.status_code}"

    print("✅ EDU guest backtest policy, job read ownership & concurrency isolation verified (404 read guard, 403 cancel guard, 429 rate limit)")


def test_edu_job_ownership_fails_closed_for_ownerless_jobs(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.jobs import runner
    from backend.main import app

    job = {
        "id": "20261024_120000_abcdef",
        "kind": "custom_backtest",
        "status": "running",
        "state": "running",
        "params": {},
    }
    monkeypatch.setattr(runner, "status", lambda job_id: dict(job))

    def fail_if_etag_checked(*args):
        raise AssertionError("ETag checked before owner")

    monkeypatch.setattr(runner, "status_etag", fail_if_etag_checked)
    cancelled = []
    monkeypatch.setattr(runner, "cancel", lambda job_id: cancelled.append(job_id))

    client = TestClient(app)
    headers = {"Cookie": "edu_guest_id=gst_0123456789abcdef0123456789abcdef"}
    assert client.get(f"/api/studio/jobs/{job['id']}", headers=headers).status_code == 404
    assert client.post(f"/api/studio/jobs/{job['id']}/cancel", headers=headers).status_code == 403
    assert cancelled == []

    monkeypatch.setattr(runner, "list_jobs", lambda *args, **kwargs: [dict(job)])
    listed = client.get("/api/studio/jobs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["jobs"] == []


def test_edu_guest_admission_quota_is_atomic_and_counts_all_active_jobs(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from fastapi.testclient import TestClient
    from backend.jobs import runner
    from backend.jobs.runner import runner as runner_impl
    from backend.main import app
    owners = []
    owners_lock = threading.Lock()

    def fake_history_dirs():
        with owners_lock:
            return [(str(i), str(i)) for i in range(len(owners))]

    def fake_summary(job_dir):
        with owners_lock:
            owner = owners[int(job_dir)]
        return {"status": "running", "params": {"owner_uid": owner}}

    def fake_launch(kind, params):
        with owners_lock:
            owners.append(params["owner_uid"])
            return f"fake-job-{len(owners)}"

    monkeypatch.setattr(runner_impl, "_history_dirs", fake_history_dirs)
    monkeypatch.setattr(runner_impl, "_summary_cached", fake_summary)
    monkeypatch.setattr(runner, "launch", fake_launch)

    body = {
        "code": '''class QuotaDemo(SimpleAlgorithm):
    id = "quota_demo"
    timeframe = "1h"
    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 30, position=1)
        self.set_positions(rsi > 70, position=0)
''',
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }

    def submit(guest_id):
        client = TestClient(app)
        return client.post(
            "/api/studio/custom/backtest",
            json=body,
            headers={"Cookie": f"edu_guest_id={guest_id}"},
        ).status_code

    guest_ids = [f"gst_{i:032x}" for i in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        aggregate_results = list(pool.map(submit, guest_ids))
    assert aggregate_results.count(200) == 3
    assert aggregate_results.count(429) == 2
    assert len(owners) == 3

    with owners_lock:
        owners.clear()
    same_guest = "gst_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with ThreadPoolExecutor(max_workers=5) as pool:
        per_guest_results = list(pool.map(submit, [same_guest] * 5))
    assert per_guest_results.count(200) == 1
    assert per_guest_results.count(429) == 4
    assert owners == [same_guest]

    with owners_lock:
        owners[:] = [f"user_{i}" for i in range(119)] + [same_guest]
    assert submit(same_guest) == 429


def test_edu_market_ranking_credibility_and_filters(request=None):
    """Kiểm tra ma trận xếp hạng EDU Market theo DEC-01:
    1. Ngưỡng mẫu N >= 20 lệnh VÀ thời gian kiểm thử >= 30 ngày (hoặc >= 500 nến khung ngắn).
    2. Lý do unranked cụ thể, chính xác.
    3. Bộ lọc phân vùng timeframe, symbol và sắp xếp theo Sharpe giảm dần.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.analys.alpha.strategies import _user_card_metrics

    # 1. Kiểm tra trực tiếp hàm đánh giá _user_card_metrics theo DEC-01
    # 1.1. Mẫu nhỏ: < 20 trades
    m_small = _user_card_metrics({"closed": 15, "all": {"sharpe": 1.5, "pnl": 500}}, {"timeframe": "1h", "start_date": "2026-01-01", "end_date": "2026-03-01"})
    # 1.1. Thiếu số lệnh (< 20 trades)
    m_small = _user_card_metrics({"closed": 15, "all": {"sharpe": 1.5, "pnl": 500}}, {"timeframe": "1h", "start_date": "2026-01-01", "end_date": "2026-03-01"})
    assert m_small["is_ranked"] is False
    assert "Mẫu nhỏ (15/20 lệnh)" in m_small["unranked_reason"]

    # 1.2. Đủ trades (>= 20) nhưng span < 30 ngày trên khung 1h
    m_short_span = _user_card_metrics({"closed": 25, "all": {"sharpe": 1.8, "pnl": 1200}}, {"timeframe": "1h", "start_date": "2026-01-01", "end_date": "2026-01-15"})
    assert m_short_span["is_ranked"] is False
    assert "Thời gian kiểm thử ngắn" in m_short_span["unranked_reason"]

    # 1.3. Đủ trades (>= 20) và span >= 30 ngày -> PASS
    m_valid = _user_card_metrics({"closed": 28, "all": {"sharpe": 2.1, "pnl": 2500}}, {"timeframe": "1h", "start_date": "2026-01-01", "end_date": "2026-03-01"})
    assert m_valid["is_ranked"] is True
    assert m_valid["unranked_reason"] is None

    # 1.4. Khung ngắn (15m): thiếu số nến (< 500 nến)
    m_short_bars = _user_card_metrics({"closed": 30, "bar_count": 350, "all": {"sharpe": 1.2, "pnl": 400}}, {"timeframe": "15m", "bar_count": 350})
    assert m_short_bars["is_ranked"] is False
    assert "Chưa đủ nến kiểm định" in m_short_bars["unranked_reason"]

    # 1.5. Khung ngắn (15m): đủ số nến (>= 500 nến) -> PASS
    m_valid_bars = _user_card_metrics({"closed": 30, "bar_count": 600, "all": {"sharpe": 1.4, "pnl": 600}}, {"timeframe": "15m", "bar_count": 600})
    assert m_valid_bars["is_ranked"] is True
    assert m_valid_bars["unranked_reason"] is None

    # 1.6. FAIL-CLOSED: Đủ 25 trades nhưng thiếu ngày (start/end) trên khung 1h -> Bắt buộc unranked
    m_missing_dates = _user_card_metrics({"closed": 25, "all": {"sharpe": 1.9, "pnl": 800}}, {"timeframe": "1h"})
    assert m_missing_dates["is_ranked"] is False, "Thiếu thời gian đánh giá bắt buộc phải fail-closed thành unranked"
    assert "Thiếu dữ liệu thời gian" in m_missing_dates["unranked_reason"]

    # 1.7. FAIL-CLOSED: Đủ 25 trades nhưng thiếu cả ngày lẫn số nến trên khung 15m -> Bắt buộc unranked
    m_missing_subhourly = _user_card_metrics({"closed": 25, "all": {"sharpe": 1.9, "pnl": 800}}, {"timeframe": "15m"})
    assert m_missing_subhourly["is_ranked"] is False, "Thiếu cả ngày lẫn số nến bắt buộc phải fail-closed thành unranked"
    assert "Thiếu dữ liệu thời gian" in m_missing_subhourly["unranked_reason"]

    # 1.8. FAIL-CLOSED: Đủ 25 trades, 500 nến nhưng THIẾU KHUNG THỜI GIAN (timeframe) -> Bắt buộc unranked (DEC-01)
    m_missing_tf = _user_card_metrics({"closed": 25, "total_bars": 500, "all": {"sharpe": 1.8, "pnl": 500}}, {})
    assert m_missing_tf["is_ranked"] is False, "Thiếu timeframe tuyệt đối không được tự động mặc định 15m để xếp hạng"
    assert "Thiếu thông tin khung thời gian" in m_missing_tf["unranked_reason"]

    # 2. Tạo fixture đa tác giả, đa khung thời gian, đa symbol để kiểm tra API filter và sort chặt chẽ
    import uuid
    from backend import users
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.strategies import save_user_alpha_from_result

    fx_u1 = users.create_user(f"fx_u1_{uuid.uuid4().hex[:6]}", "FX Author BTC 1h")
    fx_u2 = users.create_user(f"fx_u2_{uuid.uuid4().hex[:6]}", "FX Author ETH 15m")
    fx_u3 = users.create_user(f"fx_u3_{uuid.uuid4().hex[:6]}", "FX Author BTC Small")
    fx_u4 = users.create_user(f"fx_u4_{uuid.uuid4().hex[:6]}", "FX Author BTC Different Window")
    test_uids = {fx_u1["id"], fx_u2["id"], fx_u3["id"], fx_u4["id"]}

    from pathlib import Path
    from backend.analys.alpha.strategies import get_user_alphas_dir

    def _cleanup_fixtures():
        for uid in test_uids:
            try:
                up = Path(users.users_dir(f"{uid}.json"))
                if up.exists():
                    up.unlink()
            except Exception:
                pass
        try:
            alphas_d = get_user_alphas_dir()
            for ap in Path(alphas_d).glob("*.json"):
                try:
                    import json
                    d = json.loads(ap.read_text())
                    if d.get("owner_id") in test_uids:
                        ap.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    if request:
        request.addfinalizer(_cleanup_fixtures)

    code_1 = "class U1Algo(SimpleAlgorithm):\n    def __algorithm__(self):\n        self.set_positions(self.data.pv_close > 0, 1)\n"
    code_2 = "class U2Algo(SimpleAlgorithm):\n    def __algorithm__(self):\n        self.set_positions(self.data.pv_close > 10, 1)\n"
    code_3 = "class U3Algo(SimpleAlgorithm):\n    def __algorithm__(self):\n        self.set_positions(self.data.pv_close < 0, 1)\n"
    code_4 = "class U4Algo(SimpleAlgorithm):\n    def __algorithm__(self):\n        self.set_positions(self.data.pv_close > 1, 1)\n"

    p1 = compile_code(code_1, register=False)
    p2 = compile_code(code_2, register=False)
    p3 = compile_code(code_3, register=False)
    p4 = compile_code(code_4, register=False)

    # Strategy 1 (U1): BTC 1h, 35 trades, 60 days, Sharpe 2.5 (Ranked)
    save_user_alpha_from_result(
        owner_id=fx_u1["id"],
        code=code_1,
        name="U1_BTC_1h_Alpha",
        source="education",
        result={
            "program_hash": p1.code_hash,
            "config": {"symbols": ["BTC-USDT"], "timeframe": "1h", "start": "2026-01-01", "end": "2026-03-01", "initial_capital": 10000},
            "metrics": {"simulate": {"closed": 35, "sharpe": 2.50, "pnl_usd": 1500, "mdd_pct": 8.0, "ret_pct": 25.0}},
            "final_equity": 11500,
            "market_context": {"status": "available", "dominant": "RANGE", "classified_bars": 100, "coverage_pct": 100.0},
        },
    )
    # Strategy 2 (U2): ETH 15m, 40 trades, 800 bars, Sharpe 1.80 (Ranked)
    save_user_alpha_from_result(
        owner_id=fx_u2["id"],
        code=code_2,
        name="U2_ETH_15m_Alpha",
        source="education",
        result={
            "program_hash": p2.code_hash,
            "config": {"symbols": ["ETH-USDT"], "timeframe": "15m", "bar_count": 800, "initial_capital": 10000},
            "metrics": {"simulate": {"closed": 40, "bars": 800, "total_bars": 800, "sharpe": 1.80, "pnl_usd": 900, "mdd_pct": 12.0, "ret_pct": 18.0}},
            "final_equity": 10900,
            "market_context": {"status": "available", "dominant": "TREND_UP", "classified_bars": 100, "coverage_pct": 100.0},
        },
    )
    # Strategy 3 (U3): BTC 1h, 8 trades (<20), Sharpe 3.20 (Unranked mẫu nhỏ)
    save_user_alpha_from_result(
        owner_id=fx_u3["id"],
        code=code_3,
        name="U3_BTC_Small_Alpha",
        source="education",
        result={
            "program_hash": p3.code_hash,
            "config": {"symbols": ["BTC-USDT"], "timeframe": "1h", "start": "2026-01-01", "end": "2026-03-01", "initial_capital": 10000},
            "metrics": {"simulate": {"closed": 8, "sharpe": 3.20, "pnl_usd": 200, "mdd_pct": 4.0, "ret_pct": 5.0}},
            "final_equity": 10200,
            "market_context": {"status": "available", "dominant": "VOL_EXPANSION", "classified_bars": 100, "coverage_pct": 100.0},
        },
    )
    save_user_alpha_from_result(
        owner_id=fx_u4["id"],
        code=code_4,
        name="U4_BTC_1h_Different_Window",
        source="education",
        result={
            "program_hash": p4.code_hash,
            "config": {"symbols": ["BTC-USDT"], "timeframe": "1h", "start": "2025-11-01", "end": "2026-01-01", "initial_capital": 10000},
            "metrics": {"simulate": {"closed": 30, "sharpe": 4.00, "pnl_usd": 5000, "mdd_pct": 5.0, "ret_pct": 50.0}},
            "final_equity": 15000,
            "market_context": {"status": "available", "dominant": "RANGE", "classified_bars": 100, "coverage_pct": 100.0},
        },
    )

    client = TestClient(app)

    # 3. Kiểm tra filter timeframe:
    res_1h = client.get("/api/edu/market?timeframe=1h")
    assert res_1h.status_code == 200
    u_1h_ids = [u["id"] for u in res_1h.json()["users"]]
    assert fx_u1["id"] in u_1h_ids, "User 1 (1h) phải có trong kết quả filter 1h"
    assert fx_u3["id"] in u_1h_ids, "User 3 (1h) phải có trong kết quả filter 1h"
    assert fx_u2["id"] not in u_1h_ids, "User 2 (15m) tuyệt đối không được xuất hiện khi filter 1h"

    res_15m = client.get("/api/edu/market?timeframe=15m")
    assert res_15m.status_code == 200
    u_15m_ids = [u["id"] for u in res_15m.json()["users"]]
    assert fx_u2["id"] in u_15m_ids, "User 2 (15m) phải có trong filter 15m"
    assert fx_u1["id"] not in u_15m_ids, "User 1 (1h) không được xuất hiện trong filter 15m"

    # 4. Kiểm tra filter symbol:
    res_eth = client.get("/api/edu/market?symbol=ETH-USDT")
    assert res_eth.status_code == 200
    u_eth_ids = [u["id"] for u in res_eth.json()["users"]]
    assert fx_u2["id"] in u_eth_ids, "User 2 (ETH) phải xuất hiện khi filter ETH"
    assert fx_u1["id"] not in u_eth_ids, "User 1 (BTC) không được xuất hiện khi filter ETH"

    # 5. Ranked filtering is only meaningful within one symbol/timeframe partition.
    res_ranked_unfiltered = client.get("/api/edu/market?ranked_only=true")
    assert res_ranked_unfiltered.status_code == 422
    market_window = "start_date=2026-01-01&end_date=2026-03-01"
    res_ranked = client.get(f"/api/edu/market?ranked_only=true&timeframe=1h&symbol=BTC-USDT&{market_window}")
    assert res_ranked.status_code == 200
    data_ranked = res_ranked.json()["users"]
    ranked_ids = [u["id"] for u in data_ranked]
    assert fx_u1["id"] in ranked_ids, "User 1 (ranked) phải có trong ranked_only"
    assert fx_u2["id"] not in ranked_ids, "ETH/15m không được xuất hiện trong bảng BTC/1h"
    assert fx_u4["id"] not in ranked_ids, "Run ở cửa sổ ngày khác không được trộn vào bảng xếp hạng"
    assert fx_u3["id"] not in ranked_ids, "User 3 (unranked 8 lệnh) không được xuất hiện trong ranked_only"

    # 6. Kiểm tra sort theo Sharpe có căn cứ và bảo vệ tính tương đồng (DEC-01):
    res_unfiltered_sharpe = client.get("/api/edu/market?sort=sharpe")
    assert res_unfiltered_sharpe.status_code == 422
    assert client.get("/api/edu/market?regime=RANGE").status_code == 422
    res_sharpe = client.get(f"/api/edu/market?sort=sharpe&timeframe=1h&symbol=BTC-USDT&{market_window}")
    assert res_sharpe.status_code == 200
    users_sharpe = res_sharpe.json()["users"]

    # 6.1. Sharpe ordering is scoped to BTC/1h; unrelated ETH/15m data is excluded.
    pos_u1 = next(i for i, u in enumerate(users_sharpe) if u["id"] == fx_u1["id"])
    assert fx_u2["id"] not in [u["id"] for u in users_sharpe]
    assert fx_u4["id"] not in [u["id"] for u in users_sharpe]

    # 6.2. Unranked U3 (Sharpe 3.20) cannot outrank the ranked U1.
    pos_u3 = next(i for i, u in enumerate(users_sharpe) if u["id"] == fx_u3["id"])
    assert pos_u3 > pos_u1, f"Chiến lược unranked U3 không được đứng trước U1 trong partition BTC/1h"
    res_regime = client.get(f"/api/edu/market?regime=RANGE&timeframe=1h&symbol=BTC-USDT&{market_window}")
    assert res_regime.status_code == 200
    regime_ids = [u["id"] for u in res_regime.json()["users"]]
    assert fx_u1["id"] in regime_ids
    assert fx_u2["id"] not in regime_ids, "Regime filter không được trộn symbol/timeframe khác"
    assert fx_u3["id"] not in regime_ids, "Regime filter phải loại run có dominant regime khác"
    assert fx_u4["id"] not in regime_ids, "Regime filter vẫn phải giữ đúng evaluation window"
    assert res_regime.json()["facets"]["regime_context"] == "RANGE"
    res_reverse_window = client.get(
        "/api/edu/market?sort=name&timeframe=1h&symbol=BTC-USDT&start_date=2026-03-01&end_date=2026-01-01"
    )
    assert res_reverse_window.status_code == 422
    _cleanup_fixtures()


def test_edu_strategy_fork_attribution_and_immutability(request=None):
    """Kiểm tra sao chép (fork) chiến lược theo DEC-03:
    1. Server-authoritative lookup nguồn gốc tác giả và code_hash.
    2. API POST /api/edu/strategies/{id}/fork trả về đầy đủ attribution.
    3. Không thể giả mạo author attribution từ client qua API POST /api/studio/alphas/user.
    4. Bản ghi gốc bất biến, không bị sửa đổi.
    """
    import uuid
    from pathlib import Path
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend import users
    from backend.analys.alpha.strategies import save_user_alpha, get_user_alpha, get_user_alphas_dir

    created_uids = []
    created_aids = []

    def _cleanup():
        for uid in created_uids:
            try:
                Path(users.users_dir(f"{uid}.json")).unlink(missing_ok=True)
            except Exception:
                pass
        for aid in created_aids:
            try:
                Path(get_user_alphas_dir(f"{aid}.json")).unlink(missing_ok=True)
            except Exception:
                pass

    if request:
        request.addfinalizer(_cleanup)

    # 1. Tạo tác giả A và chiến lược gốc
    u_handle_a = f"mary_{uuid.uuid4().hex[:6]}"
    user_a = users.create_user(u_handle_a, "Author Mary")
    author_a_id = user_a["id"]
    created_uids.append(author_a_id)
    code_a = '''class OriginalStrategy(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        c = self.data.pv_close
        self.set_positions(c > 0, position=1)
'''
    source_alpha, _ = save_user_alpha(
        alpha_id=None,
        name="Chiến lược gốc của Mary",
        code=code_a,
        owner_id=author_a_id,
        source="education",
    )
    source_id = source_alpha["id"]
    created_aids.append(source_id)

    # 2. Học viên B chuẩn bị sao chép chiến lược
    u_handle_b = f"student_{uuid.uuid4().hex[:6]}"
    user_b = users.create_user(u_handle_b, "Hoc vien B")
    student_b_id = user_b["id"]
    created_uids.append(student_b_id)

    # 3. Gọi API POST /api/edu/strategies/{id}/fork với session của học viên B
    client = TestClient(app)
    client.cookies.set("edu_session", users.sign_uid(student_b_id))
    fork_resp = client.post(f"/api/edu/strategies/{source_id}/fork")
    assert fork_resp.status_code == 200, fork_resp.text
    fork_data = fork_resp.json()
    assert fork_data["ok"] is True
    assert "forked_from" in fork_data
    ff = fork_data["forked_from"]
    assert ff["alpha_id"] == source_id
    assert ff["author_uid"] == author_a_id
    assert ff["author_handle"] == user_a["handle"]
    assert ff["version"] == 1

    # 4. Kiểm thử CHỐNG GIẢ MẠO QUA API (DEC-03):
    # Case 4.1: Client cố tình fork từ một alpha_id không tồn tại -> API phải từ chối (HTTP 409 hoặc 400)
    fake_fork_req = {
        "name": "Bản fork lừa đảo",
        "code": code_a,
        "forked_from": {
            "alpha_id": f"non_existent_{uuid.uuid4().hex[:8]}",
            "author_name": "Tác giả giả",
        }
    }
    bad_resp = client.post("/api/studio/alphas/user", json=fake_fork_req)
    assert bad_resp.status_code in (400, 404, 409, 422), "API phải từ chối fork từ chiến lược nguồn không tồn tại"

    # Case 4.2: Client fork từ source_id thật nhưng cố tình gửi author_handle và author_name bịa đặt
    spoofed_req = {
        "name": "Bản fork chân chính",
        "code": code_a,
        "forked_from": {
            "alpha_id": source_id,
            "author_handle": "hacker_spoofed",
            "author_name": "Fake Hacker Name",
            "code_hash": "fake_hash_12345",
        }
    }
    good_resp = client.post("/api/studio/alphas/user", json=spoofed_req)
    assert good_resp.status_code == 200, good_resp.text
    saved_fork = good_resp.json()["record"]
    assert saved_fork is not None
    real_ff = saved_fork["forked_from"]
    assert real_ff["author_handle"] == user_a["handle"], "Server phải tra cứu đúng handle gốc của Mary từ DB, không tin client"
    assert real_ff["author_name"] == user_a["display_name"], "Server phải tra cứu đúng display_name gốc của Mary"
    assert real_ff["author_uid"] == author_a_id
    assert real_ff["version"] == 1
    assert saved_fork["owner_id"] == student_b_id

    # 5. Xác minh bản ghi gốc hoàn toàn bất biến, không bị sửa đổi
    original_check = get_user_alpha(source_id)
    assert original_check is not None
    assert original_check["owner_id"] == author_a_id
    assert original_check.get("forked_from") is None

    # Run the persisted fork code through the production EDU engine, not a UI-side fill fixture.
    import os
    import tempfile
    from backend.jobs.tasks import run_custom_backtest

    old_job_dir = os.environ.get("NORA_JOB_DIR")
    with tempfile.TemporaryDirectory() as job_dir:
        os.environ["NORA_JOB_DIR"] = job_dir
        try:
            fork_run = run_custom_backtest(
                {
                    "job_id": f"job_test_fork_{uuid.uuid4().hex[:8]}",
                    "owner_uid": student_b_id,
                    "product": "EDU",
                    "code": saved_fork["code"],
                    "symbols": ["BTC-USDT"],
                    "start": "2025-01-01",
                    "end": "2025-02-01",
                }
            )
        finally:
            if old_job_dir:
                os.environ["NORA_JOB_DIR"] = old_job_dir
            else:
                os.environ.pop("NORA_JOB_DIR", None)
    assert fork_run["manifest"]["owner_uid"] == student_b_id
    assert fork_run["manifest"]["product"] == "EDU"
    assert fork_run["manifest"]["code_hash"]
    assert fork_run["metrics"]["simulate"] is not None
    _cleanup()


def test_edu_regime_window_context_is_descriptive_and_fail_closed():
    """DEC-01: regime summary is window-scoped, descriptive, and unavailable without classified bars."""
    import numpy as np
    from backend.analys.metrics.regime import RANGE, TREND_UP, UNKNOWN, summarize_window_labels

    context = summarize_window_labels(
        "BTC-USDT",
        np.array([0, 15, 30, 45, 60]),
        np.array([RANGE, TREND_UP, TREND_UP, RANGE, UNKNOWN]),
        np.array([True, True, True, False, True]),
        15,
        60,
    )
    assert context["status"] == "available"
    assert context["dominant"] == "TREND_UP"
    assert context["classified_bars"] == 2
    assert context["window_bars"] == 2
    assert context["coverage_pct"] == 100.0
    assert context["reference_only"] is True

    unavailable = summarize_window_labels(
        "BTC-USDT",
        np.array([15, 30]),
        np.array([UNKNOWN, UNKNOWN]),
        np.array([True, True]),
        15,
        60,
    )
    assert unavailable["status"] == "unavailable"
    assert "No classified real 15m bars" in unavailable["reason"]
    assert "dominant" not in unavailable


def test_edu_alpha_authoring_versioning_and_provenance(request=None):
    """Kiểm tra lưu phiên bản (versioning) và Run Manifest provenance theo DEC-02."""
    import uuid
    import os
    import json
    import tempfile
    from pathlib import Path
    from backend import users
    from backend.analys.alpha.strategies import save_user_alpha, get_user_alpha, list_user_alpha_versions, get_user_alphas_dir
    from backend.jobs.tasks import run_custom_backtest

    u_handle = f"dev_{uuid.uuid4().hex[:6]}"
    user = users.create_user(u_handle, "Dev Version")
    user_id = user["id"]

    alpha_ids = []

    def _cleanup():
        try:
            Path(users.users_dir(f"{user_id}.json")).unlink(missing_ok=True)
        except Exception:
            pass
        for aid in alpha_ids:
            try:
                Path(get_user_alphas_dir(f"{aid}.json")).unlink(missing_ok=True)
            except Exception:
                pass

    if request:
        request.addfinalizer(_cleanup)

    code_v1 = '''class VersionDemo(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        c = self.data.pv_close
        self.set_positions(c > 0, position=1)
'''
    rec_v1, _ = save_user_alpha(
        alpha_id=None,
        name="Version Demo",
        code=code_v1,
        owner_id=user_id,
        source="education",
    )
    alpha_id = rec_v1["id"]
    alpha_ids.append(alpha_id)
    assert rec_v1["version"] == 1
    assert "program_hash" in rec_v1

    # Lưu tiếp phiên bản 2 cho cùng alpha_id
    code_v2 = '''class VersionDemo(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        c = self.data.pv_close
        rsi = self.feat.rsi(c, timeperiod=14)
        self.set_positions(rsi < 30, position=1)
'''
    rec_v2, action_v2 = save_user_alpha(
        alpha_id=alpha_id,
        name="Version Demo v2",
        code=code_v2,
        owner_id=user_id,
        source="education",
        note="Nâng cấp v2",
    )
    assert rec_v2["id"] == alpha_id
    assert rec_v2["version"] == 2
    assert action_v2 == "versioned"

    # Kiểm tra lịch sử phiên bản
    versions = list_user_alpha_versions(alpha_id)
    assert versions is not None
    assert len(versions) >= 2
    ver_nums = [v["version"] for v in versions]
    assert 1 in ver_nums
    assert 2 in ver_nums

    # 2. Kiểm tra Run Manifest DEC-02 thực chứng trong quá trình chạy backtest
    with tempfile.TemporaryDirectory() as job_dir:
        old_job_dir = os.environ.get("NORA_JOB_DIR")
        os.environ["NORA_JOB_DIR"] = job_dir
        try:
            params = {
                "job_id": f"job_test_{uuid.uuid4().hex[:8]}",
                "owner_uid": user_id,
                "product": "EDU",
                "code": code_v1,
                "symbols": ["BTC-USDT"],
                "start": "2026-01-01",
                "end": "2026-02-01",
            }
            res = run_custom_backtest(params)
            assert "manifest" in res, "Kết quả backtest phải chứa khối manifest theo DEC-02"
            manifest = res["manifest"]
            assert manifest["product"] == "EDU"
            assert manifest["owner_uid"] == user_id
            market_context = res["market_context"]
            assert market_context["status"] == "available"
            assert market_context["symbol"] == "BTC-USDT"
            assert market_context["timeframe"] == "15m"
            assert market_context["reference_only"] is True
            assert market_context["dataset_digest"] == manifest["dataset"]["data_digests"]["BTC-USDT"]
            assert manifest["dataset"]["market_context"] == market_context
            assert "code_hash" in manifest
            assert manifest["engine"]["name"] == "nora-edu-dsl"
            assert manifest["engine"]["memory_cap_bytes"] == 2 * 1024 * 1024 * 1024
            assert "timestamps" in manifest
            assert "queued_at" in manifest["timestamps"]
            assert "completed_at" in manifest["timestamps"]

            # Đo lường bộ nhớ thực tế và dataset SHA256 thật (không fake code hash, không unmeasured)
            import re
            peak_rss = manifest["execution_metrics"].get("peak_rss_bytes")
            assert peak_rss is not None and peak_rss > 0, "peak_rss_bytes phải được đo từ OS (> 0)"
            data_digest = manifest["dataset"].get("data_digest")
            assert data_digest not in ("unmeasured", "sha256:unmeasured"), "data_digest của job backtest thực tế không được là unmeasured"
            assert re.match(r"^sha256:[0-9a-f]{64}$", data_digest), f"data_digest phải là SHA256 hex đầy đủ, nhận {data_digest}"
            assert set(manifest["dataset"]["data_digests"]) == {"BTC-USDT"}
            assert re.match(r"^sha256:[0-9a-f]{64}$", manifest["dataset"]["data_digests"]["BTC-USDT"])
            assert manifest["dataset"]["data_digest_method"] == "sha256_of_canonical_symbol_to_content_sha256_map"
            assert manifest["execution_metrics"]["peak_rss_scope"] == "worker_process_lifetime"
            # Tuyệt đối không được lấy tiền tố code_hash để gán vào data_digest
            assert not data_digest.endswith(manifest["code_hash"][:16]), "data_digest không được fake từ code_hash"

            # Kiểm tra file run_manifest.json tồn tại trên đĩa trong thư mục job
            manifest_file = os.path.join(job_dir, "run_manifest.json")
            assert os.path.isfile(manifest_file), "run_manifest.json phải được ghi vào thư mục job"
            with open(manifest_file, "r", encoding="utf-8") as f:
                disk_manifest = json.load(f)
            assert disk_manifest["job_id"] == params["job_id"]
            assert disk_manifest["code_hash"] == manifest["code_hash"]
            assert disk_manifest["dataset"]["data_digest"] == data_digest

            # Bất biến (DEC-02): Chạy lại lần 2 với cùng job_dir không được ghi đè hay làm thay đổi file
            original_content = open(manifest_file, "r", encoding="utf-8").read()
            res_rerun = run_custom_backtest(params)
            assert res_rerun["manifest"]["job_id"] == params["job_id"]
            assert open(manifest_file, "r", encoding="utf-8").read() == original_content, "run_manifest.json không được bị sửa đổi hay ghi đè"

            edited_job_dir = os.path.join(job_dir, "edited")
            os.mkdir(edited_job_dir)
            os.environ["NORA_JOB_DIR"] = edited_job_dir
            edited_params = {
                **params,
                "job_id": f"job_test_edited_{uuid.uuid4().hex[:8]}",
                "code": code_v2,
            }
            edited_result = run_custom_backtest(edited_params)
            assert edited_result["manifest"]["owner_uid"] == user_id
            assert edited_result["manifest"]["job_id"] == edited_params["job_id"]
            assert edited_result["manifest"]["code_hash"] != manifest["code_hash"]
            assert edited_result["metrics"]["simulate"] is not None
        finally:
            if old_job_dir:
                os.environ["NORA_JOB_DIR"] = old_job_dir
            else:
                os.environ.pop("NORA_JOB_DIR", None)
    _cleanup()


def test_edu_run_manifest_fails_closed_without_dataset_content_digest(monkeypatch, tmp_path):
    import pytest
    from backend.jobs import tasks

    monkeypatch.setenv("NORA_JOB_DIR", str(tmp_path))
    monkeypatch.setattr(
        tasks,
        "run_custom",
        lambda params: {
            "config": {"symbols": ["BTC-USDT"], "timeframe": "1h"},
            "metrics": {"simulate": {}},
            "data": {"catalog_digest": {"BTC-USDT": "metadata-only"}},
        },
    )

    with pytest.raises(RuntimeError, match="SHA-256 content hashes"):
        tasks.run_custom_backtest(
            {"job_id": "missing-content-hash", "code": "class MissingHash: pass", "symbols": ["BTC-USDT"]}
        )
def test_edu_onboarding_dsl_samples_clean_compilation():
    """Kiểm tra toàn bộ mẫu DSL được export trực tiếp từ component EduStudioOnboarding.jsx biên dịch sạch 100%."""
    import re
    from pathlib import Path
    from backend.analys.alpha.code.compile import compile_code

    jsx_file = Path(__file__).resolve().parent.parent / "frontend" / "src" / "components" / "alpha" / "studio" / "EduStudioOnboarding.jsx"
    assert jsx_file.is_file(), f"Không tìm thấy file UI: {jsx_file}"
    content = jsx_file.read_text(encoding="utf-8")

    # Trích xuất trực tiếp các khối code: `...` nằm trong ONBOARDING_DSL_SAMPLES
    samples_match = re.search(r"export const ONBOARDING_DSL_SAMPLES\s*=\s*\[(.*?)\]\s*export const EDU_STUDIO_STEPS", content, re.DOTALL)
    assert samples_match, "Không trích xuất được ONBOARDING_DSL_SAMPLES từ EduStudioOnboarding.jsx"
    samples_block = samples_match.group(1)

    # Lấy các đoạn code nằm trong dấu backtick (code: `...`)
    codes = re.findall(r"code:\s*`([^`]+)`", samples_block)
    assert len(codes) >= 3, f"Phải tìm thấy ít nhất 3 mẫu DSL trong component UI, tìm thấy: {len(codes)}"

    for idx, sample_code in enumerate(codes, start=1):
        clean_code = sample_code.strip()
        prog = compile_code(clean_code, register=False)
        assert prog.name, f"Mẫu {idx} từ EduStudioOnboarding.jsx thiếu name"
        assert prog.code_hash, f"Mẫu {idx} từ EduStudioOnboarding.jsx thiếu code_hash"


def test_education_sample_defaults_to_full_catalog_universe():
    from backend.analys.alpha.strategies import sample_run_spec
    from backend.data.data import default_universe

    spec = sample_run_spec({"code": "class Sample: pass"})
    expected = default_universe()
    assert spec["symbols"] == expected
    assert len(spec["symbols"]) == 10


def test_custom_backtest_accepts_expanded_user_selected_universe():
    from backend.routes.studio import build_custom_backtest
    from backend.analys.alpha.strategies import _education_samples

    params = build_custom_backtest({
        "code": _education_samples()[0]["code"],
        "symbols": [f"ASSET{i:02d}" for i in range(20)],
        "start": "2024-01-01",
        "end": "2024-02-01",
    })
    assert len(params["symbols"]) == 20


def test_run_defaults_exposes_catalog_assets_without_changing_default_run():
    from backend.data.data import available_universe, run_defaults

    defaults = run_defaults()
    assert defaults["symbols"] == ["BTC@perp", "ETH@perp"]
    raw_avail = defaults.get("available_symbols")
    avail = raw_avail if isinstance(raw_avail, list) else []
    assert len(avail) == len(available_universe())
    assert len(avail) >= 20



def test_edu_integrated_api_worker_manifest_reload_journey(tmp_path, monkeypatch):
    """Kiểm tra tích hợp API -> Worker EDU -> Lưu trữ Manifest & Kết quả -> Reload đúng job ID (EDU-P4-JOURNEY).

    Bao gồm:
    1. Danh tính EDU cô lập + token phiên EDU.
    2. Gửi DSL xác định qua API POST /api/studio/custom/backtest.
    3. Thực thi worker thật, ghi manifest và kết quả vào đĩa.
    4. Tải lại (reload) qua GET /api/studio/book/jobs/{job_id} đối soát kết quả và cấu hình.
    5. Kiểm tra quyền sở hữu tuyệt đối (người dùng khác không đọc được job).
    6. Kiểm tra cô lập sản phẩm (tuyệt đối không truy cập được API/route của COIN).
    """
    import uuid
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.users.store import sign_uid
    from backend.jobs import tasks, runner

    job_root = tmp_path / "edu_jobs"
    job_root.mkdir()
    monkeypatch.setenv("NORA_JOB_DIR", str(job_root))

    owner_uid = f"usr_edu_p4_{uuid.uuid4().hex[:8]}"
    other_uid = f"usr_edu_other_{uuid.uuid4().hex[:8]}"
    owner_token = sign_uid(owner_uid)
    other_token = sign_uid(other_uid)

    client_owner = TestClient(app, cookies={"edu_session": owner_token})
    client_other = TestClient(app, cookies={"edu_session": other_token})

    # 1. DSL xác định
    dsl_code = """class DeterministicEma(SimpleAlgorithm):
    id = "det_ema"
    timeframe = "1h"

    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, timeperiod=10)
        self.set_positions(close > ema, position=1)
        self.set_positions(close <= ema, position=0)
"""

    # 2. Gửi backtest qua API
    submit_res = client_owner.post("/api/studio/custom/backtest", json={
        "code": dsl_code,
        "symbols": ["BTC-USDT"],
        "timeframe": "1h",
        "start": "2026-01-01",
        "end": "2026-02-01",
        "initial_capital": 10000,
        "train_ratio": 0.8,
    })
    assert submit_res.status_code == 200, submit_res.text
    job_id = submit_res.json()["job_id"]
    assert job_id, "API phải trả về job_id hợp lệ"

    # 3. Chạy qua worker thật
    raw_job = runner.status(job_id)
    assert raw_job is not None, f"Worker runner phải tìm thấy job {job_id}"
    params = raw_job["params"]
    params["owner_uid"] = owner_uid
    result = tasks.run_custom_backtest(params)

    # Ghi result.json và cập nhật hoàn tất bằng helper nội bộ của runner
    jdir = runner._job_dir(job_id)
    import json
    with open(os.path.join(jdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f)
    runner._finish(jdir, 0)

    # 4. Reload job qua API với đúng owner
    reload_res = client_owner.get(f"/api/studio/book/jobs/{job_id}")
    assert reload_res.status_code == 200, reload_res.text
    reloaded_data = reload_res.json()
    assert reloaded_data.get("id") == job_id or reloaded_data.get("job_id") == job_id
    assert reloaded_data["status"] == "done"
    assert reloaded_data["result"]["metrics"]["simulate"] is not None
    assert reloaded_data["result"]["config"]["symbols"] in (["BTC"], ["BTC-USDT"])
    assert reloaded_data["result"]["config"]["run_frame"] == "1h"
    assert reloaded_data["result"]["config"]["position_overrides"] == {}
    assert reloaded_data["result"]["manifest"]["owner_uid"] == owner_uid
    assert reloaded_data["result"]["manifest"]["code_hash"]

    # 5. Kiểm tra quyền sở hữu tuyệt đối: User khác đọc job này -> 404 Fail Closed
    other_read_res = client_other.get(f"/api/studio/book/jobs/{job_id}")
    assert other_read_res.status_code == 404, "User khác không được phép đọc job của owner"

    # 6. Kiểm tra cô lập sản phẩm: EDU API tuyệt đối không có routes của COIN
    assert client_owner.get("/api/studio/live/bots").status_code == 404
    assert client_owner.get("/api/studio/portfolio/master").status_code == 404

    print("✅ EDU integrated API -> real worker -> manifest persistence -> reload journey verified with complete isolation")


def test_edu_custom_backtest_run_frame_and_multi_asset_plan(monkeypatch):
    """Worker phải giữ 1m tường minh và lập plan với toàn bộ rổ tài sản được gửi."""
    from backend.jobs import tasks, worker

    code = '''class FrameAndBasket(SimpleAlgorithm):
    id = "frame_and_basket"
    timeframe = "1h"

    def __algorithm__(self):
        close = self.data.pv_close
        self.set_positions(close > 0, position=1)
'''
    monkeypatch.setattr(worker, "require_memory_limit", lambda _: None)
    monkeypatch.setattr(tasks, "check_data", lambda _: None)
    monkeypatch.setattr(tasks, "data_info", lambda *args: ({"source": "okx"}, []))
    monkeypatch.setattr(tasks, "run_parallel", lambda _: {})
    monkeypatch.setattr(tasks, "_finish", lambda program, plan, *args, **kwargs: {
        "run_frame": plan.base_frame,
        "symbols": plan.symbols,
    })
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    monkeypatch.setenv("NORA_SHARED_DATA_DIR", "test-value")

    common = {
        "code": code,
        "symbols": ["BTC@perp", "ETH@perp", "SOL@perp"],
        "start": "2026-01-01",
        "end": "2026-02-01",
        "train_ratio": 0.8,
        "initial_capital": 10000,
    }
    standard = tasks.run_custom({**common, "run_frame": "1m"})
    fast = tasks.run_custom(common)

    assert standard["run_frame"] == "1m"
    assert fast["run_frame"] == "1h"
    assert standard["symbols"] == ["BTC@perp", "ETH@perp", "SOL@perp"]
    assert fast["symbols"] == standard["symbols"]


def test_edu_password_auth_and_symbol_guard():
    """Kiểm thử xác thực mật khẩu và cho phép launch backtest với symbol có dữ liệu:
    1. Đăng ký tài khoản mới có password.
    2. Đăng nhập sai password -> 401 Unauthorized.
    3. Đăng nhập đúng password -> 200 OK kèm session cookie, không rò rỉ password_hash.
    4. SOL@perp được chấp nhận tại launch boundary; worker vẫn kiểm tra catalog trước khi chạy.
    """
    import time
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    ts = int(time.time() * 1000) % 100000
    handle = f"user_pwd_{ts}"
    password = "SuperSecretPassword123!"

    # 1. Đăng ký có password
    res_reg = client.post("/api/users", json={
        "handle": handle,
        "display_name": f"Tester {handle}",
        "password": password,
    })
    assert res_reg.status_code == 200, res_reg.text
    user = res_reg.json()
    assert "password_hash" not in user, "Lỗ hổng: password_hash bị rò rỉ trong response đăng ký!"
    assert user["handle"] == handle

    # 2. Đăng nhập sai password -> 401
    res_fail = client.post("/api/me/login", json={
        "handle": handle,
        "password": "WrongPassword!",
    })
    assert res_fail.status_code == 401, f"Kỳ vọng 401 nhưng nhận {res_fail.status_code}"

    # 3. Đăng nhập đúng password -> 200 OK
    res_ok = client.post("/api/me/login", json={
        "handle": handle,
        "password": password,
    })
    assert res_ok.status_code == 200, res_ok.text
    login_user = res_ok.json().get("user", {})
    assert "password_hash" not in login_user, "Lỗ hổng: password_hash bị rò rỉ trong response đăng nhập!"
    assert login_user["id"] == user["id"]
    assert "edu_session" in res_ok.cookies or "nora_uid" in res_ok.cookies

    # 4. Một symbol ngoài cặp mặc định được chấp nhận tại launch boundary.
    valid_code = """class SolMultiAssetAlgo(SimpleAlgorithm):
    timeframe = "24h"
    def on_bar(self):
        self.set_positions(self.data.pv_close > 0, position=1)
"""
    res_sol = client.post("/api/studio/custom/backtest", json={
        "code": valid_code,
        "symbols": ["SOL@perp"],
        "start": "2024-01-01",
        "end": "2024-02-01",
        "train_ratio": 0.7,
        "initial_capital": 10000,
    })
    assert res_sol.status_code == 200, f"Kỳ vọng 200 khi chạy SOL@perp nhưng nhận {res_sol.status_code}: {res_sol.text}"
    assert "job_id" in res_sol.json()

    print("✅ EDU password auth (PBKDF2) and multi-asset backtest launch verified")


def test_edu_change_password_requires_current_password():
    import time
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    handle = f"pwchange_{int(time.time() * 1000) % 100000}"
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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main(["-v", __file__]))
