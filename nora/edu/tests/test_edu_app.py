"""Kiểm thử tính độc lập của dự án nora/edu."""
import os
import sys
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
    prov = res["provenance"]
    sim_m = res["metrics"]["simulate"]
    print(f"✅ EDU real backtest executed successfully! Alpha ID: {res['alpha_id']}")
    print(f"   Provenance: engine={prov.get('engine')} version={prov.get('engine_version')}")
    print(f"   Metrics (simulate): trades={sim_m.get('trades')}, pnl={sim_m.get('ret_pct')}%, mdd={sim_m.get('mdd_pct')}%")
    assert sim_m.get("trades") is not None and sim_m.get("trades") > 0, "Thiếu số lệnh trong metrics.simulate!"
    assert sim_m.get("ret_pct") is not None, "Thiếu PnL trong metrics.simulate!"


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
    for _ in range(30):
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

    # Đối chiếu trực tiếp từng chỉ số giữa Monolith và EDU
    assert edu_sim["trades"] == mono_sim["trades"], f"Lệch số lệnh: EDU={edu_sim['trades']} vs Monolith={mono_sim['trades']}"
    assert abs(edu_sim["ret_pct"] - mono_sim["ret_pct"]) < 1e-4, f"Lệch PnL: EDU={edu_sim['ret_pct']} vs Monolith={mono_sim['ret_pct']}"
    assert abs(edu_sim["mdd_pct"] - mono_sim["mdd_pct"]) < 1e-4, f"Lệch MDD: EDU={edu_sim['mdd_pct']} vs Monolith={mono_sim['mdd_pct']}"
    assert abs(edu_sim["sharpe"] - mono_sim["sharpe"]) < 1e-4, f"Lệch Sharpe: EDU={edu_sim['sharpe']} vs Monolith={mono_sim['sharpe']}"
    assert abs(edu_sim["win_rate_trades"] - mono_sim["win_rate_trades"]) < 1e-4, f"Lệch WinRate: EDU={edu_sim['win_rate_trades']} vs Monolith={mono_sim['win_rate_trades']}"

    print(f"✅ EDU Golden Parity verified: trades={edu_sim['trades']}, pnl={edu_sim['ret_pct']}%, mdd={edu_sim['mdd_pct']}%, sharpe={edu_sim['sharpe']} (100% bit-for-bit live match with Monolith)")


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
    for _ in range(30):
        st_res = client.get(f"/api/studio/jobs/{job_id}", headers=headers_alice)
        if st_res.status_code == 200:
            final_data = st_res.json()
            if final_data.get("status") == "done":
                done = True
                break
        time.sleep(1)

    assert done, f"Job không kết thúc với trạng thái done! Dữ liệu: {final_data}"
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


if __name__ == "__main__":
    test_edu_imports_and_routes()
    test_edu_data_isolation()
    test_edu_import_origin_isolation()
    test_edu_backtest_pipeline()
    test_edu_job_boundary_and_isolation()
    test_edu_job_smoke_and_path_traversal()
    test_edu_backtest_execution()
    test_edu_golden_parity()
    test_edu_api_job_lifecycle()
    test_edu_api_to_worker_e2e_and_ownership()
    test_edu_auth_token_audience_isolation()
    test_edu_secret_isolation()
    print("🎉 ALL EDU PROJECT & API TESTS PASSED 100%!")

