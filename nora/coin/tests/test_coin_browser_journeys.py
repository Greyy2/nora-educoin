"""Deterministic browser journeys for COIN Phase 3 acceptance."""

import json
import os
from pathlib import Path
import uuid

import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("NORA_DATA_ROOT", str(COIN_ROOT / "data"))

from playwright.sync_api import sync_playwright

from backend.models.storage import data_home
from backend.users.store import sign_uid, create_user, get_user, get_by_handle, get_by_display_name

TEST_HANDLE = os.environ.get("NORA_COIN_BROWSER_TEST_HANDLE", "browser_tester_coin")
BASE_URL = os.environ.get("NORA_COIN_BROWSER_BASE_URL", "http://coin.expsolution.io").rstrip("/")


def get_or_create_test_user():
    user = get_user("011ad081739b")
    if user:
        return user
    user = get_by_handle(TEST_HANDLE) or get_by_display_name("Browser Tester COIN")
    if user:
        return user
    return create_user(handle=TEST_HANDLE, display_name="Browser Tester COIN")


def get_auth_token():
    u = get_or_create_test_user()
    return sign_uid(u["id"])


@pytest.fixture(scope="module")
def browser_instance():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=[
                "--host-rules=MAP coin.expsolution.io 127.0.0.1, MAP edu.expsolution.io 127.0.0.1",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        yield browser
        browser.close()


def create_auth_context(browser, viewport=None):
    vp = viewport or {"width": 1280, "height": 800}
    context = browser.new_context(viewport=vp)
    context.add_cookies(
        [
            {
                "name": "coin_session",
                "value": get_auth_token(),
                "domain": "coin.expsolution.io",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )
    return context


def test_coin_journey_1_portfolio_home_regime_and_metrics(browser_instance):
    """COIN-HOME-01..06: PageHead, RegimeScale, Authoritative Profit, Compact MDD."""
    context = create_auth_context(browser_instance)
    page = context.new_page()

    page.goto(f"{BASE_URL}/coin/portfolio", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(1000)

    # 1. PageHead title/kicker
    body_text = page.locator("body").inner_text()
    assert "Danh mục COIN" in body_text or "Nora COIN" in page.title()

    # 2. Legacy elements must NOT be visible (no 30-day history table)
    assert page.locator("table.history-30d").count() == 0

    # 3. Regime scale with categorical status and neutral center
    regime_el = page.locator(".regime-scale, [data-testid='regime-scale'], .regime-badge, :has-text('Regime')").first
    assert regime_el.is_visible()

    # 4. Authoritative profit / PnL metric instead of trade count
    profit_metric = page.locator(":has-text('Lợi nhuận'), :has-text('Profit'), :has-text('PnL')").first
    assert profit_metric.is_visible()

    # 5. Compact MDD (underwater chart)
    underwater = page.locator(".underwater-chart, .n-dd-compact, [data-testid='underwater-strip']").first
    if underwater.count() > 0:
        assert underwater.is_visible()

    context.close()


def test_coin_journey_2_studio_workspace_and_syntax_modal(browser_instance):
    """COIN-ALPHA-01..06: Code editor, strategy documentation modal."""
    context = create_auth_context(browser_instance)
    page = context.new_page()

    page.goto(f"{BASE_URL}/coin/alpha/create", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(1000)

    # 1. Strategy Documentation Modal Trigger
    doc_btn = page.locator("button:has-text('📖')")
    assert doc_btn.count() > 0, "Documentation trigger button (📖) must be present in Studio"
    doc_btn.click()
    page.wait_for_timeout(500)

    # 2. Modal opens with syntax guidance
    doc_modal = page.locator("div[role='dialog'][aria-label='Tài liệu cú pháp Nora']")
    assert doc_modal.is_visible(), "Syntax documentation modal must open on click"
    assert "SimpleAlgorithm" in doc_modal.inner_text()

    # 3. Modal close button works
    close_btn = page.locator("button:has-text('Đóng')")
    close_btn.click()
    page.wait_for_timeout(300)
    assert not doc_modal.is_visible(), "Modal must close on clicking Đóng"

    context.close()


def test_coin_journey_4_custom_backtest_ui_poll_and_recovery(browser_instance):
    """UI-only API fixture: run form -> queued/running/result -> same job after reload."""
    context = create_auth_context(browser_instance)
    page = context.new_page()
    page.goto(f"{BASE_URL}/coin/alpha/create", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(1200)
    editor = page.locator(".cm-content")
    page.wait_for_function("document.querySelector('.cm-content')?.innerText.includes('class ')", timeout=10000)
    code = editor.inner_text()
    page.locator("button[aria-label='Kiểm tra code']").click()
    page.locator(".se-out").get_by_text("Hợp lệ").wait_for(timeout=10000)

    job_id = "browser-ui-job"
    launch_payload = {}
    poll_count = [0]
    result = {
        "config": {},
        "program_hash": "fixture-program-hash",
        "provenance": {
            "base_frame": "15m",
            "engine": "NautilusTrader",
            "version": "fixture",
            "slippage_modeled": False,
            "funding_modeled": False,
            "liquidation_modeled": False,
        },
        "metrics": {
            "train": {"ret_pct": 4.0, "sharpe_ratio": 1.1, "max_drawdown_pct": 2.0, "total_trades": 2, "fees_usd": 0.5},
            "test": {"ret_pct": 3.0, "sharpe_ratio": 0.9, "max_drawdown_pct": 2.5, "total_trades": 1, "fees_usd": 0.25},
            "simulate": {"ret_pct": 7.0, "sharpe_ratio": 1.0, "max_drawdown_pct": 2.5, "total_trades": 3, "fees_usd": 0.75},
        },
        "series": {
            "stages": {
                stage: {
                    "times": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"],
                    "equity": [10000.0, 10400.0, 10700.0],
                    "pnl": [0.0, 400.0, 700.0],
                    "drawdown_pct": [0.0, 0.0, -1.0],
                    "ret_pct": [0.0, 4.0, 2.88],
                }
                for stage in ("all", "train", "test")
            }
        },
    }

    def launch_backtest(route):
        launch_payload.update(route.request.post_data_json)
        result["config"] = launch_payload.copy()
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"job_id": job_id}))

    def poll_job(route):
        states = ("queued", "running", "running", "done")
        state = states[min(poll_count[0], len(states) - 1)]
        poll_count[0] += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job_id": job_id,
                "kind": "custom_backtest",
                "status": state,
                "created": "2026-10-24T18:00:00Z",
                "started": "2026-10-24T18:00:01Z" if state != "queued" else None,
                "finished": "2026-10-24T18:00:03Z" if state == "done" else None,
                "progress": {"done": 5 if state == "done" else 2, "total": 5, "stage": "Hoàn tất" if state == "done" else "Nạp dữ liệu"},
                "log_tail": ["[18:00:00] [1/5] Biên dịch · fixture", "[18:00:02] [2/5] Nạp dữ liệu · fixture"],
                "result": result if state == "done" else None,
            }),
        )

    page.route("**/api/studio/custom/backtest", launch_backtest)
    page.route(f"**/api/studio/book/jobs/{job_id}*", poll_job)
    run_button = page.locator("button.se-run")
    page.wait_for_function("!document.querySelector('button.se-run')?.disabled", timeout=15000)
    assert "Chạy backtest" in run_button.inner_text(), "This regression must never enter paper/testnet/live mode"
    run_button.click()

    page.get_by_text("Đang chạy", exact=True).wait_for(timeout=10000)
    page.locator(".se-res .n-tag").get_by_text("Khớp bar (15m)").wait_for(timeout=10000)
    editor_lines = [line.rstrip() for line in code.splitlines() if line.strip()]
    launch_lines = [line.rstrip() for line in launch_payload["code"].splitlines() if line.strip()]
    assert launch_lines == editor_lines
    assert poll_count[0] >= 4, "The UI should poll through queued, running, and done states"
    assert launch_payload["symbols"]
    assert launch_payload["start"] < launch_payload["end"]
    assert page.locator(".se-res").get_by_text("Dữ liệu tổng hợp").is_visible()
    assert page.get_by_text(job_id, exact=True).is_visible()

    page.get_by_role("button", name="Performance").click()
    assert page.locator(".se-res .se-tiles").get_by_text("Lợi nhuận").is_visible()
    page.reload(wait_until="networkidle", timeout=15000)
    page.get_by_text(job_id, exact=True).wait_for(timeout=10000)
    assert page.locator(".se-res").get_by_text("Dữ liệu tổng hợp").is_visible()
    context.close()


def test_coin_journey_3_prompt_research_workspace_and_registry(browser_instance):
    """COIN-PROMPT-01..09: 3 tabs, provider status (no secret leak), config validate, registry."""
    # Ensure test prompt alpha exists in registry
    prompt_alphas_dir = Path(data_home()) / "prompt_alphas"
    prompt_alphas_dir.mkdir(parents=True, exist_ok=True)
    sample_pa_id = f"pa_browser_test_{uuid.uuid4().hex}"
    sample_pa_path = prompt_alphas_dir / f"{sample_pa_id}.json"
    created_fixture = False
    u = get_or_create_test_user()
    sample_pa = {
        "id": sample_pa_id,
        "type": "prompt_alpha",
        "name": "Donchian 20 ATR Trend Filter",
        "owner_id": u["id"],
        "status": "tested",
        "prompt": "Breakout kênh Donchian 20 có lọc biến động bằng ATR",
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "side": "both",
        "hypothesis": {
            "economic_mechanism": "Trend risk premium in crypto momentum",
            "falsifiable_conditions": "Sharpe OOS < 0.6",
            "rejection_rules": "MDD > 25%",
        },
        "citations": [{
            "provider": "LLM Suggested Reference",
            "title": "Unverified test citation",
            "url": "https://doi.org/10.1000/example",
            "doi": "10.1000/example",
            "verified": False,
            "status": "unverified_reference",
        }],
        "code": "# SimpleAlgorithm demo code\n",
        "metrics": {
            "simulate": {
                "total_trades": 28,
                "sharpe_ratio": 1.45,
                "total_return": 0.18,
                "max_drawdown": 0.09,
            }
        },
        "created_at": "2026-10-24T18:00:00Z",
        "updated_at": "2026-10-24T18:00:00Z",
    }
    try:
        with sample_pa_path.open("x", encoding="utf-8") as fixture_file:
            json.dump(sample_pa, fixture_file, indent=2)
        created_fixture = True

        context = create_auth_context(browser_instance)
        page = context.new_page()

        page.goto(f"{BASE_URL}/coin/alpha/create", wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(1000)

        # 1. Switch to Prompt Mode
        prompt_mode_btn = page.locator(".se-mode button:has-text('Prompt')")
        assert prompt_mode_btn.count() > 0, "Prompt mode button must exist"
        prompt_mode_btn.click()
        page.wait_for_timeout(800)

        # 2. Verify tabs exist
        tab_research = page.locator("button:has-text('Ý tưởng')")
        tab_config = page.locator("button:has-text('Cấu hình')")
        tab_registry = page.locator("button:has-text('Kho ý tưởng')")

        assert tab_research.count() > 0, "Tab 1: Ý tưởng must exist"
        assert tab_config.count() > 0, "Tab 2: Cấu hình must exist"
        assert tab_registry.count() > 0, "Tab 3: Kho ý tưởng must exist"

        # 3. Tab 2: Config tab & zero secret leak
        tab_config.click()
        page.wait_for_timeout(800)
        body_text = page.locator("body").inner_text()
        assert "sk-" not in body_text, "No OpenAI/Anthropic api keys may leak in DOM"

        validate_btn = page.locator("button:has-text('Kiểm tra Cấu hình')")
        if validate_btn.count() > 0:
            validate_btn.click()
            page.wait_for_timeout(800)
            assert page.locator(":has-text('Cấu hình hợp lệ')").count() > 0

        # 4. Tab 3: Registry tab & Review Gate modal
        tab_registry.click()
        page.wait_for_timeout(800)
        assert page.locator(":has-text('Donchian 20 ATR Trend Filter')").count() > 0

        alpha_card = page.locator(f"[data-testid='prompt-alpha-{sample_pa_id}']")
        assert alpha_card.locator("text=· Chưa xác minh").count() == 1
        verified_record = {
            **sample_pa,
            "citations": [{
                "provider": "Crossref",
                "title": "Canonical Crossref test citation",
                "url": "https://doi.org/10.1000/example",
                "doi": "10.1000/example",
                "verified": True,
                "status": "verified",
                "retrieval_time": "2026-10-24T18:00:00+00:00",
                "metadata_sha256": "a" * 64,
            }],
        }

        verification_route_hit = []

        def fulfill_citation_verification(route):
            verification_route_hit.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "record": verified_record}),
            )

        page.route("**/citations/verify", fulfill_citation_verification)
        alpha_card.locator("button:has-text('Xác minh DOI với Crossref')").click()
        verified_status = alpha_card.locator("text=· DOI đã đối chiếu Crossref")
        verified_status.wait_for(state="visible", timeout=5000)
        assert verification_route_hit

        review_btn = page.locator("button:has-text('Đánh giá (Review Gate)')").first
        if review_btn.count() > 0:
            review_btn.click()
            page.wait_for_timeout(500)
            modal = page.locator(":has-text('Cổng đánh giá con người (Human Review Gate)')").first
            assert modal.is_visible()
            # Cancel/close modal
            cancel_btn = page.locator("button:has-text('Hủy')")
            if cancel_btn.count() > 0:
                cancel_btn.click()
                page.wait_for_timeout(300)

        context.close()
    finally:
        if created_fixture and sample_pa_path.exists():
            sample_pa_path.unlink()


def test_coin_live_transitional_bot_cannot_be_deleted(browser_instance):
    """Live UI must preserve stopping state and withhold destructive actions."""
    context = create_auth_context(browser_instance)
    page = context.new_page()
    bots = [{
        "bot_id": "browser_stopping_fixture",
        "mode": "live",
        "status": "stopping",
        "strategy": "Lifecycle fixture",
        "strategies": [],
        "symbols": ["BTC-USDT-SWAP"],
        "capital": 1000,
        "equity": 1000,
        "pnl_pct": 0,
        "pnl_usd": 0,
        "positions": [],
        "positions_count": 0,
        "mdd_pct": 0,
        "uptime_seconds": 1,
    }]
    page.route("**/api/studio/live/bots**", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": bots}),
    ))
    page.route("**/api/studio/live/archive", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": []}),
    ))
    page.route("**/api/studio/live/resource_status", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({}),
    ))
    page.route("**/api/studio/portfolio/master**", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"code": "LIVE_LEDGER_UNAVAILABLE", "message": "fixture unavailable"}}),
    ))

    page.goto(f"{BASE_URL}/coin/live", wait_until="networkidle", timeout=15000)
    page.get_by_text("Đang dừng", exact=True).wait_for(timeout=10000)
    assert page.locator("button:has-text('Xoá')").count() == 0
    assert page.get_by_text("Đang dừng — chỉ xoá sau khi xác nhận đã dừng", exact=True).count() == 1
    context.close()


def test_coin_live_starting_bot_can_be_stopped(browser_instance):
    """An active startup/recovery bot must expose a safe stop action, not an unusable delete state."""
    context = create_auth_context(browser_instance)
    page = context.new_page()
    bots = [{
        "bot_id": "browser_starting_fixture",
        "mode": "testnet",
        "status": "starting",
        "strategy": "Lifecycle fixture",
        "strategies": [],
        "symbols": ["BTC-USDT-SWAP"],
        "capital": 1000,
        "equity": 1000,
        "pnl_pct": 0,
        "pnl_usd": 0,
        "positions": [],
        "positions_count": 0,
        "mdd_pct": 0,
        "uptime_seconds": 1,
    }]
    stop_requests = []
    page.route("**/api/studio/live/bots**", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": bots}),
    ))
    page.route("**/api/studio/live/archive", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": []}),
    ))
    page.route("**/api/studio/live/resource_status", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({}),
    ))
    page.route("**/api/studio/portfolio/master**", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"code": "LIVE_LEDGER_UNAVAILABLE", "message": "fixture unavailable"}}),
    ))
    page.route("**/api/studio/live/bot/browser_starting_fixture/stop**", lambda route: (
        stop_requests.append(route.request.post_data_json),
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "status": "stopping"})),
    ))
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{BASE_URL}/coin/live", wait_until="networkidle", timeout=15000)
    page.get_by_text("Đang khởi động", exact=True).wait_for(timeout=10000)
    page.get_by_role("button", name="Dừng", exact=True).click()
    page.wait_for_timeout(300)
    assert stop_requests == [None]
    assert page.locator("button:has-text('Xoá')").count() == 0
    context.close()


@pytest.mark.parametrize(
    ("error_code", "expected_message"),
    [
        (
            "LIVE_LEDGER_UNAVAILABLE",
            "Không thể bật bot: sổ cái Master chưa có dữ liệu authoritative.",
        ),
        (
            "LIVE_RISK_STATE_UNAVAILABLE",
            "Không thể bật bot: trạng thái Master Risk chưa xác định.",
        ),
    ],
)
def test_coin_live_start_explains_master_risk_block(browser_instance, error_code, expected_message):
    """The UI must explain why the backend fail-closed start gate rejected a launch."""
    context = create_auth_context(browser_instance)
    page = context.new_page()
    candidate = {
        "id": "browser_start_fixture",
        "name": "Start fixture",
        "source": "fixture",
        "timeframe": "1h",
        "signal_tf": "1h",
        "symbols": ["BTC-USDT-SWAP"],
        "ret_pct": 10,
        "mdd_pct": 2,
        "sharpe": 1.5,
        "win_rate": 60,
        "trades": 4,
        "backtested_at": "2026-10-25T00:00:00Z",
    }
    page.route("**/api/studio/live/bots**", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": []}),
    ))
    page.route("**/api/studio/live/archive", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bots": []}),
    ))
    page.route("**/api/studio/live/resource_status", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({}),
    ))
    page.route("**/api/studio/portfolio/master**", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"code": error_code, "message": "fixture unavailable"}}),
    ))
    page.route("**/api/studio/live/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"candidates": [candidate], "n": 1}),
    ))
    page.route("**/api/studio/live/bot", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"code": error_code, "message": "fixture unavailable"}}),
    ))

    page.goto(f"{BASE_URL}/coin/live", wait_until="networkidle", timeout=15000)
    page.locator("#live-btn-start").click()
    page.get_by_role("button", name="Bật bot", exact=True).first.click()
    form = page.locator(".push-alpha-modal form")
    form.get_by_role("button", name="Bật bot", exact=True).click()
    page.get_by_text(expected_message, exact=False).wait_for(timeout=5000)
    context.close()
