import os
import sys
from pathlib import Path
import pytest

EDU_ROOT = Path(__file__).resolve().parent.parent
if str(EDU_ROOT) not in sys.path:
    sys.path.insert(0, str(EDU_ROOT))
os.environ["NORA_DATA_ROOT"] = str(EDU_ROOT / "data")


def test_compile_report_declared_params():
    """Kiểm tra compile_report trích xuất chính xác các tham số vị thế khai báo trong class."""
    from backend.analys.alpha.code.compile import compile_report

    code = """class QuickRsiEdu(SimpleAlgorithm):
    id = "quick_rsi_edu"
    timeframe = "1h"
    leverage = 1
    exit_unit = "pct"
    stop_loss_rate = 0.02
    take_profit_rate = 0.04
    risk_per_trade_pct = 0.5

    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)"""

    rep = compile_report(code)
    assert rep["ok"] is True
    assert "declared_params" in rep
    d = rep["declared_params"]
    assert d.get("stop_loss_rate") == 0.02
    assert d.get("take_profit_rate") == 0.04
    assert d.get("leverage") == 1
    assert d.get("exit_unit") == "pct"
    assert d.get("risk_per_trade_pct") == 0.5


def test_build_plan_provenance_and_conflict():
    """Kiểm tra build_plan xác định nguồn tham số (code vs ui) và cảnh báo khi có xung đột."""
    from backend.analys.alpha.code.compile import compile_code
    from backend.analys.alpha.code.plan import build_plan

    code = """class EmaTest(SimpleAlgorithm):
    id = "ema_test"
    timeframe = "1h"
    leverage = 1
    exit_unit = "pct"
    stop_loss_rate = 0.02
    take_profit_rate = 0.04

    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, timeperiod=20)
        self.set_positions(close > ema, position=1)
        self.set_positions(close < ema, position=0)"""

    prog = compile_code(code)

    # 1. Ca A: Không bị UI đè -> Nguồn gốc phải là 'code'
    plan_a = build_plan(prog, ["BTC"])
    assert plan_a.echo["param_provenance"]["stop_loss_rate"]["source"] == "code"
    assert plan_a.echo["param_provenance"]["stop_loss_rate"]["value"] == 0.02
    assert plan_a.echo["param_provenance"]["stop_loss_rate"]["unit"] == "%"
    assert len(plan_a.echo["conflicts"]) == 0

    # 2. Ca B: Bị UI đè -> Nguồn gốc chuyển thành 'ui', có conflict cảnh báo
    plan_b = build_plan(prog, ["BTC"], position={"stop_loss_rate": 0.05})
    assert plan_b.echo["param_provenance"]["stop_loss_rate"]["source"] == "ui"
    assert plan_b.echo["param_provenance"]["stop_loss_rate"]["value"] == 0.05
    assert len(plan_b.echo["conflicts"]) == 1
    assert "bị cấu hình giao diện ghi đè" in plan_b.echo["conflicts"][0]
    assert any("bị cấu hình giao diện ghi đè" in w for w in plan_b.warnings)


def test_run_custom_provenance_end_to_end():
    """Kiểm tra đường chạy thật run_custom: result.json ghi nhận param_provenance và warnings."""
    from backend.jobs.tasks import run_custom

    code = """class QuickRsiEduEndToEnd(SimpleAlgorithm):
    id = "quick_rsi_edu_e2e"
    timeframe = "1h"
    leverage = 1
    exit_unit = "pct"
    stop_loss_rate = 0.02
    take_profit_rate = 0.04
    risk_per_trade_pct = 0.5

    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)"""

    params_no_override = {
        "code": code,
        "symbols": ["BTC"],
        "start": "2025-01-01",
        "end": "2025-01-15",
        "train_ratio": 0.8,
        "initial_capital": 10000,
        "run_frame": "1h",
    }
    res1 = run_custom(params_no_override)
    assert res1 is not None
    assert "config" in res1
    cfg1 = res1["config"]
    assert "param_provenance" in cfg1
    assert cfg1["param_provenance"]["stop_loss_rate"]["source"] == "code"
    assert cfg1["param_provenance"]["stop_loss_rate"]["value"] == 0.02
    assert len(cfg1.get("conflicts", [])) == 0

    # Ca 2: UI gửi position ghi đè stop_loss_rate thành 0.05
    params_with_override = {
        **params_no_override,
        "position": {"stop_loss_rate": 0.05},
    }
    res2 = run_custom(params_with_override)
    assert res2 is not None
    cfg2 = res2["config"]
    assert cfg2["param_provenance"]["stop_loss_rate"]["source"] == "ui"
    assert cfg2["param_provenance"]["stop_loss_rate"]["value"] == 0.05
    assert len(cfg2.get("conflicts", [])) >= 1
    assert any("ghi đè" in w for w in res2.get("warnings", []))


def test_browser_studio_provenance_and_conflict_display():
    """Kiểm tra trên trình duyệt: bảng Cấu hình hiệu lực, banner xung đột, banner trượt giá, và xử lý run cũ."""
    from playwright.sync_api import sync_playwright
    import json

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        from backend.users.store import sign_uid
        context.add_cookies([{
            "name": "edu_session",
            "value": sign_uid("034633bfd1dc"),
            "domain": "127.0.0.1",
            "path": "/",
        }])
        page = context.new_page()

        # 1. Ca kết quả mới có provenance, xung đột và trượt giá > 0
        modern_result = {
            "ok": True,
            "final_equity": 10129.05,
            "metrics": {
                "simulate": {"trades": 3, "ret_pct": 1.29, "pnl_usd": 129.05, "mdd_pct": 0.21, "sharpe": 2.1, "win_rate": 100},
                "test": {"sharpe": 2.0},
            },
            "config": {
                "initial_capital": 10000,
                "symbols": ["BTC@perp"],
                "start": "2023-10-06",
                "end": "2026-10-03",
                "timeframe": "1h",
                "position": {
                    "leverage": 1,
                    "stop_loss_rate": 0.05,
                    "take_profit_rate": 0.04,
                    "exit_unit": "pct",
                    "slippage_rate": 0.0005,
                    "fee_rate": 0.0005,
                },
                "param_provenance": {
                    "leverage": {"source": "code", "value": 1, "unit": "x", "declared_in_code": 1},
                    "stop_loss_rate": {"source": "ui", "value": 0.05, "unit": "%", "declared_in_code": 0.02},
                    "take_profit_rate": {"source": "code", "value": 0.04, "unit": "%", "declared_in_code": 0.04},
                    "slippage_rate": {"source": "ui", "value": 0.0005, "unit": "%", "declared_in_code": None},
                },
                "conflicts": [
                    "Tham số vị thế 'stop_loss_rate' khai báo trong code là 0.02 nhưng đang bị cấu hình giao diện ghi đè thành 0.05."
                ],
            },
            "trades": [],
        }

        # Routes setup
        page.route("**/api/studio/custom/defaults", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"symbols": ["BTC@perp"], "available_symbols": ["BTC@perp"], "start": "2026-01-01", "end": "2026-02-01", "train_ratio": 0.8, "initial_capital": 10000})
        ))
        page.route("**/api/studio/alphas/user*", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps({"alphas": []})
        ))

        job_id = "job_test_provenance_ui"

        def route_submit(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": job_id, "job_id": job_id, "status": "running"}),
            )

        def route_job(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": job_id,
                    "job_id": job_id,
                    "kind": "custom_backtest",
                    "status": "done",
                    "result": modern_result,
                    "log_tail": [],
                }),
            )

        page.route("**/api/studio/custom/backtest*", route_submit)
        page.route(f"**/api/studio/book/jobs/{job_id}*", route_job)

        page.goto("http://127.0.0.1:18022/studio", wait_until="networkidle", timeout=15000)

        # Bấm Chạy backtest
        run_btn = page.get_by_role("button", name="Chạy backtest", exact=True)
        assert run_btn.is_visible()
        run_btn.click()

        # Đợi kết quả hiển thị
        conflict_el = page.locator(".edu-conflict-notice")
        conflict_el.wait_for(state="visible", timeout=10000)
        assert "Cảnh báo: Cấu hình giao diện đang ghi đè tham số" in conflict_el.inner_text()
        assert "stop_loss_rate" in conflict_el.inner_text()

        # Kiểm tra banner trượt giá động (0.05% mỗi chiều)
        slip_el = page.locator(".edu-slippage-notice")
        assert slip_el.is_visible()
        assert "mô phỏng trượt giá 0.05%" in slip_el.inner_text()

        # Chuyển sang tab Analysis để xem bảng Cấu hình hiệu lực & Nguồn tham số
        analysis_tab = page.locator("button:has-text('Analysis')").first
        analysis_tab.wait_for(state="visible", timeout=10000)
        analysis_tab.click()
        page.wait_for_timeout(300)

        table_heading = page.locator("text=Cấu hình hiệu lực & Nguồn tham số")
        assert table_heading.is_visible()
        assert page.locator("text=📄 Từ Code").first.is_visible()
        assert page.locator("text=⚙️ Từ Giao diện").first.is_visible()

        # 2. Ca kết quả cũ không có param_provenance -> Hiện "Không có dữ liệu nguồn (run cũ)"
        legacy_result = {
            "ok": True,
            "final_equity": 10050.0,
            "metrics": {
                "simulate": {"trades": 1, "ret_pct": 0.5, "pnl_usd": 50.0, "mdd_pct": 0.1, "sharpe": 1.5, "win_rate": 100},
            },
            "config": {
                "initial_capital": 10000,
                "position": {"leverage": 1, "stop_loss_rate": 0.02, "take_profit_rate": 0.04},
            },
            "trades": [],
        }
        legacy_job_id = "job_legacy_ui"
        page.route("**/api/studio/custom/backtest*", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"id": legacy_job_id, "job_id": legacy_job_id, "status": "running"})
        ))
        page.route(f"**/api/studio/book/jobs/{legacy_job_id}*", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"id": legacy_job_id, "job_id": legacy_job_id, "kind": "custom_backtest", "status": "done", "result": legacy_result, "log_tail": []})
        ))

        with page.expect_response(lambda r: f"jobs/{legacy_job_id}" in r.url):
            run_btn.click()
        page.wait_for_timeout(500)
        slip_legacy = page.locator(".edu-slippage-notice")
        slip_legacy.wait_for(state="visible", timeout=10000)
        assert "giả định trượt giá bằng 0" in slip_legacy.inner_text()

        # Mở tab Analysis
        page.locator("button:has-text('Analysis')").first.click()
        page.wait_for_timeout(300)
        assert page.locator("text=Không có dữ liệu nguồn (run cũ)").first.is_visible()

        browser.close()

