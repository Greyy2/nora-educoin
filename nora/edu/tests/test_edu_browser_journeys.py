"""Deterministic browser journeys for EDU Phase 2 acceptance."""

import json
import os
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright  # type: ignore

from backend.users.store import sign_uid


TEST_UID = os.environ.get("NORA_EDU_BROWSER_TEST_UID", "034633bfd1dc")
BASE_URL = os.environ.get("NORA_EDU_BROWSER_BASE_URL", "http://edu.expsolution.io").rstrip("/")
VALID_DSL = '''class QuickRsi(SimpleAlgorithm):
    id = "quick_rsi"
    timeframe = "1h"

    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        self.set_positions(rsi < 35, position=1)
        self.set_positions(rsi > 65, position=0)
'''


def run_result_fixture(job_id):
    return {
        "job_id": job_id,
        "program_hash": "a" * 64,
        "metrics": {
            "simulate": {"trades": 2, "ret_pct": 1.0, "cagr_pct": 1.0, "mdd_pct": -0.5, "sharpe": 1.0},
            "test": {"sharpe": 1.0},
        },
        "config": {
            "symbols": ["BTC-USDT"],
            "start": "2026-01-01",
            "end": "2026-02-01",
            "train_ratio": 0.8,
            "initial_capital": 10000,
            "timeframe": "1h",
            "position": {},
        },
        "series": {"stages": {}},
        "trades": [],
        "by_symbol": [],
        "checklist": {"items": []},
    }


def install_run_defaults_fixture(page):
    page.route(
        "**/api/studio/custom/defaults",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "symbols": ["BTC@perp"],
                    "available_symbols": ["BTC@perp", "ETH@perp", "SOL@perp"],
                    "start": "2026-01-01",
                    "end": "2026-02-01",
                    "train_ratio": 0.8,
                    "initial_capital": 10000,
                }
            ),
        ),
    )


def install_done_job_fixture(page, job_id, result=None):
    result = result or run_result_fixture(job_id)

    def get_job(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": job_id,
                    "job_id": job_id,
                    "kind": "custom_backtest",
                    "status": "done",
                    "result": result,
                    "log_tail": [],
                }
            ),
        )

    page.route(f"**/api/studio/book/jobs/{job_id}*", get_job)
    return result


def get_auth_token():
    return sign_uid(TEST_UID)


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


def create_auth_context(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.add_cookies(
        [
            {
                "name": "edu_session",
                "value": get_auth_token(),
                "url": BASE_URL,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )
    return context


def test_journey_1_market_ranking_credibility_and_filters(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    requests = []

    def market_fixture(route):
        params = parse_qs(urlparse(route.request.url).query)
        requests.append(params)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "users": [
                        {
                            "id": "phase2-ranked-user",
                            "handle": "phase2_ranked",
                            "display_name": "Phase 2 Ranked Fixture",
                            "n_strategies": 1,
                            "total_pnl_usd": 1500,
                            "max_mdd_pct": 8,
                            "ranked_strategies": 1,
                            "primary_unranked_reason": None,
                            "best": {
                                "name": "Fixture Alpha",
                                "sharpe": 2.5,
                                "market_context": {
                                    "status": "available",
                                    "dominant": "RANGE",
                                    "classified_bars": 100,
                                    "coverage_pct": 100.0,
                                },
                            },
                        }
                    ],
                    "facets": {
                        "timeframe": params.get("timeframe", [None])[0],
                        "symbol": params.get("symbol", [None])[0],
                        "regime_context": params.get("regime", [None])[0],
                        "ranked_only": params.get("ranked_only", ["false"])[0] == "true",
                        "sort": params.get("sort", ["name"])[0],
                        "comparability_mode": "partitioned",
                    },
                }
            ),
        )

    page.route("**/api/edu/market*", market_fixture)
    page.goto(f"{BASE_URL}/market", wait_until="networkidle", timeout=15000)
    assert "Nora EDU" in page.title()
    assert "Market" in page.locator("h1").first.inner_text()
    assert page.get_by_text("Phase 2 Ranked Fixture").is_visible()
    assert page.get_by_text("Regime tham khảo: Đi ngang").is_visible()
    assert page.locator("input[type='checkbox']").is_disabled()
    assert page.locator("select[aria-label='Sắp xếp'] option[value='sharpe']").is_disabled()
    assert page.get_by_label("Regime tham khảo").is_disabled()

    page.locator("select[aria-label='Khung thời gian']").select_option("1h")
    page.locator("select[aria-label='Cặp tài sản']").select_option("BTC-USDT")
    page.get_by_label("Ngày bắt đầu").fill("2026-01-01")
    page.get_by_label("Ngày kết thúc").fill("2026-03-01")
    regime_select = page.get_by_label("Regime tham khảo")
    assert regime_select.is_enabled()
    with page.expect_response(
        lambda response: response.url.startswith(f"{BASE_URL}/api/edu/market")
        and parse_qs(urlparse(response.url).query).get("regime") == ["RANGE"]
    ):
        regime_select.select_option("RANGE")
    ranked_checkbox = page.locator("input[type='checkbox']")
    assert ranked_checkbox.is_enabled()
    ranked_checkbox.check()
    sort_select = page.locator("select[aria-label='Sắp xếp']")
    assert sort_select.locator("option[value='sharpe']").is_enabled()
    with page.expect_response(
        lambda response: response.url.startswith(f"{BASE_URL}/api/edu/market")
        and parse_qs(urlparse(response.url).query).get("sort") == ["sharpe"]
    ):
        sort_select.select_option("sharpe")

    assert requests[-1]["timeframe"] == ["1h"]
    assert requests[-1]["symbol"] == ["BTC-USDT"]
    assert requests[-1]["start_date"] == ["2026-01-01"]
    assert requests[-1]["end_date"] == ["2026-03-01"]
    assert requests[-1]["regime"] == ["RANGE"]
    assert requests[-1]["ranked_only"] == ["true"]
    assert requests[-1]["sort"] == ["sharpe"]
    assert page.get_by_text("Phase 2 Ranked Fixture").is_visible()
    context.close()


def test_journey_2_onboarding_guided_steps_dismiss_resume(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    page.route(
        "**/api/studio/alphas/user",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"items":[]}'),
    )
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.evaluate(
        """() => {
            localStorage.removeItem('nora_edu_onboarding');
            sessionStorage.removeItem('nora_studio_state_education');
        }"""
    )
    page.reload(wait_until="networkidle")

    overlay = page.locator(".edu-onboarding-overlay")
    assert overlay.is_visible(), "Fresh Studio with no saved alpha must show onboarding"
    step_indicator = overlay.locator(".rt-step").first
    assert "1/" in step_indicator.inner_text()
    overlay.locator(".rt-ft button.primary").click()
    assert "2/" in step_indicator.inner_text()
    overlay.locator(".rt-ft button:has-text('Bỏ qua')").click()
    assert not overlay.is_visible()

    persisted = json.loads(page.evaluate("() => localStorage.getItem('nora_edu_onboarding')"))
    assert persisted["dismissed"] is True
    assert persisted["current_step"] == 1
    page.reload(wait_until="networkidle")
    assert not overlay.is_visible(), "Dismissed onboarding must stay closed after reload"
    page.get_by_role("button", name="Hướng dẫn Studio").click()
    assert overlay.is_visible()
    page.wait_for_function("() => document.querySelector('.edu-onboarding-overlay .rt-step')?.textContent.includes('2/')")
    assert "2/" in step_indicator.inner_text(), "Manual reopening must resume the saved step"
    context.close()


def test_journey_3_alpha_authoring_and_compile_check(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    install_run_defaults_fixture(page)
    job_id = "phase2_new_alpha_job"
    result_fixture = install_done_job_fixture(page, job_id)
    page.route(
        "**/api/studio/custom/backtest",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"job_id": job_id}),
        ),
    )
    saved_items = []
    save_requests = []

    def alpha_user_fixture(route):
        if route.request.method == "POST":
            payload = json.loads(route.request.post_data or "{}")
            save_requests.append(payload)
            saved_items[:] = [
                {
                    "id": "phase2_new_alpha",
                    "owner_id": TEST_UID,
                    "name": payload["name"],
                    "code": payload["code"],
                    "version": 1,
                    "program_hash": result_fixture["program_hash"],
                    "result": result_fixture,
                }
            ]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "action": "created",
                        "version": 1,
                        "alpha_id": "phase2_new_alpha",
                        "checklist": {"items": []},
                    }
                ),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"items": saved_items}),
        )

    page.route("**/api/studio/alphas/user", alpha_user_fixture)
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.evaluate(
        """() => {
            localStorage.setItem('nora_edu_onboarding', JSON.stringify({completed: true, dismissed: true}));
            sessionStorage.removeItem('nora_studio_state_education');
        }"""
    )
    page.reload(wait_until="networkidle")
    page.get_by_role("button", name="Hướng dẫn Studio").click()
    page.locator(".edu-onboarding-overlay .rt-ft button.primary").click()
    page.locator(".edu-onboarding-overlay").get_by_role("button", name="Nạp mã mẫu này vào Editor").click()

    editor = page.locator(".cm-content").first
    assert "QuickRsi" in editor.inner_text()
    compile_button = page.get_by_role("button", name="Kiểm tra code")
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/strategies/compile")
        and response.request.method == "POST"
    ) as response_info:
        compile_button.click()
    result = response_info.value.json()
    assert result["ok"] is True, result
    assert "Hợp lệ" in page.locator(".se-strip-s").inner_text()
    page.locator(".se-strip-h").click()

    page.get_by_role("button", name="Thêm bản nháp").click()
    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(VALID_DSL)
    assert "QuickRsi" in editor.inner_text()
    save_button = page.get_by_role("button", name="Lưu chiến lược")
    assert save_button.is_disabled(), "A new alpha cannot be saved without a completed backtest"
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.get_by_text(job_id, exact=True).wait_for(state="visible", timeout=10000)
    page.wait_for_function(
        "() => !document.querySelector('.se-save')?.disabled",
        timeout=10000,
    )
    save_button.click()
    dialog = page.get_by_role("dialog", name="Lưu chiến lược")
    dialog.locator("#alpha-name").fill("New Alpha Fixture")
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/alphas/user")
        and response.request.method == "POST"
    ):
        dialog.get_by_role("button", name="Lưu chiến lược").click()
    page.get_by_role("heading", name="Đã lưu chiến lược").wait_for(state="visible")
    assert len(save_requests) == 1
    assert save_requests[0]["job_id"] == job_id
    assert save_requests[0]["code"] == VALID_DSL

    page.wait_for_timeout(500)
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    assert "QuickRsi" in page.locator(".cm-content").first.inner_text()
    page.get_by_text(job_id).wait_for(state="visible", timeout=10000)
    context.close()


def test_journey_8_studio_run_settings_multi_asset_frame_and_stale_state(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    install_run_defaults_fixture(page)
    job_id = "studio_run_settings_contract"
    result_fixture = install_done_job_fixture(page, job_id)
    requests = []

    def submit_backtest(route):
        payload = json.loads(route.request.post_data or "{}")
        requests.append(payload)
        result_fixture["config"].update({
            "symbols": [symbol.split("@")[0].split("-")[0] for symbol in payload["symbols"]],
            "data_symbols": [f"{symbol.split('@')[0].split('-')[0]}@perp" for symbol in payload["symbols"]],
            "run_frame": payload.get("run_frame", "1h"),
            "position_overrides": payload.get("position", {}),
        })
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"job_id": job_id}))

    page.route("**/api/studio/custom/backtest", submit_backtest)
    page.route("**/api/studio/alphas/user*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"items": []}),
    ))
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.evaluate(
        """() => {
          localStorage.setItem('nora_edu_onboarding', JSON.stringify({completed: true, dismissed: true}));
          sessionStorage.setItem('nora_studio_state_education', JSON.stringify({
            drafts: [{id: 'run-settings-draft', name: 'Run settings fixture', code: %s,
              baseCode: %s, jobId: '', sampleKey: '', runAlpha: '', saved: null, stored: null}],
            active: 'run-settings-draft',
            form: {symbols: ['BTC@perp'], start: '2026-01-01', end: '2026-02-01',
              train_ratio: '0.8', capital: '10000', pos: {}}
          }));
        }""" % (json.dumps(VALID_DSL), json.dumps(VALID_DSL))
    )
    page.reload(wait_until="networkidle", timeout=15000)
    page.get_by_role("button", name="Cài đặt chạy").click()
    assert page.locator(".n-chip-lbl").count() == 3, "Studio phải hiển thị toàn bộ available_symbols"
    for symbol in ("ETH", "SOL"):
        checkbox = page.locator(".n-chip-lbl").filter(has_text=symbol).locator("input")
        if checkbox.is_checked():
            checkbox.uncheck()
    btc = page.locator(".n-chip-lbl").filter(has_text="BTC").locator("input")
    if not btc.is_checked():
        btc.check()
    page.locator(".n-chip-lbl").filter(has_text="SOL").locator("input").check()
    assert page.locator(".n-chip-lbl input:checked").count() == 2
    page.locator("#se-mode").select_option("standard")
    assert "Khung mô phỏng: 1m" in page.locator(".se-set").inner_text()
    page.get_by_role("button", name="Đóng", exact=True).click()
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.locator(".se-res").wait_for(state="visible", timeout=10000)
    assert requests[-1]["symbols"] == ["BTC@perp", "SOL@perp"]
    assert requests[-1]["run_frame"] == "1m"
    assert page.locator(".edu-stale-banner").count() == 0
    page.get_by_role("button", name="Cài đặt chạy").click()
    page.locator(".n-chip-lbl").filter(has_text="SOL").locator("input").uncheck()
    assert page.locator(".edu-stale-banner").count() == 0
    context.close()


def test_journey_4_strategy_fork_attribution_and_save(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    install_run_defaults_fixture(page)
    job_id = "phase2_fork_backtest"
    install_done_job_fixture(page, job_id)
    page.route(
        "**/api/studio/custom/backtest",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"job_id": job_id}),
        ),
    )
    source_id = "phase2_fork_source"
    source = {
        "id": source_id,
        "name": "Forkable Fixture",
        "code": VALID_DSL,
        "result": None,
        "owner": {"handle": "source_author", "display_name": "Source Author"},
        "version": 3,
        "card": {"code_hash": "a" * 64},
    }
    page.route(
        f"**/api/edu/strategies/{source_id}",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(source)),
    )
    save_requests = []

    def save_fixture(route):
        if route.request.method != "POST":
            route.fulfill(status=200, content_type="application/json", body='{"items":[]}')
            return
        save_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "action": "created",
                    "version": 1,
                    "alpha_id": "phase2_saved_fork",
                    "checklist": {"items": []},
                }
            ),
        )

    page.route("**/api/studio/alphas/user", save_fixture)
    page.goto(
        f"{BASE_URL}/studio?fork={source_id}",
        wait_until="networkidle",
        timeout=15000,
    )
    assert "Nora EDU" in page.title()
    assert "QuickRsi" in page.locator(".cm-content").inner_text()
    status_note = page.locator("p[role='status']")
    assert "Đã sao chép “Forkable Fixture” của @source_author" in status_note.inner_text()

    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("Control+A")
    edited_code = VALID_DSL.replace("35", "34")
    page.keyboard.insert_text(edited_code)
    assert "rsi < 34" in editor.inner_text()
    save_button = page.get_by_role("button", name="Lưu chiến lược")
    assert save_button.is_disabled(), "Forks must be rerun before saving a result-backed alpha"
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.get_by_text(job_id).wait_for(state="visible", timeout=10000)
    page.wait_for_function(
        "() => !document.querySelector('.se-save')?.disabled",
        timeout=10000,
    )
    page.wait_for_function("() => !document.querySelector('.se-save')?.disabled")
    save_button.click()
    dialog = page.get_by_role("dialog", name="Lưu chiến lược")
    assert dialog.is_visible()
    assert "Nguồn gốc sao chép" in dialog.inner_text()
    assert "@source_author" in dialog.inner_text()
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/alphas/user")
        and response.request.method == "POST"
    ) as response_info:
        dialog.get_by_role("button", name="Lưu chiến lược").click()
    assert response_info.value.status == 200
    assert len(save_requests) == 1
    assert save_requests[0]["job_id"] == job_id
    assert save_requests[0]["code"] == edited_code
    assert save_requests[0]["forked_from"] == {
        "alpha_id": source_id,
        "owner_handle": "source_author",
        "owner_name": "Source Author",
        "version": 3,
        "code_hash": "a" * 64,
    }
    page.get_by_role("dialog", name="Lưu chiến lược").get_by_role("heading", name="Đã lưu chiến lược").wait_for(state="visible")
    context.close()


def test_journey_6_existing_alpha_version_edit_run_and_reopen(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    install_run_defaults_fixture(page)
    alpha_id = "phase2_existing_alpha"
    job_id = "phase2_existing_alpha_job"
    result = install_done_job_fixture(page, job_id)
    version1 = VALID_DSL
    version2 = VALID_DSL.replace("35", "36")
    version3 = version1
    alpha_items = [
        {
            "id": alpha_id,
            "owner_id": TEST_UID,
            "name": "Existing Alpha Fixture",
            "code": version2,
            "version": 2,
            "program_hash": result["program_hash"],
        }
    ]
    save_requests = []

    def alpha_user_fixture(route):
        if route.request.method == "POST":
            payload = json.loads(route.request.post_data or "{}")
            save_requests.append(payload)
            alpha_items[:] = [
                {
                    "id": alpha_id,
                    "owner_id": TEST_UID,
                    "name": payload["name"],
                    "code": version3,
                    "version": 3,
                    "program_hash": result["program_hash"],
                }
            ]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "action": "versioned",
                        "version": 3,
                        "alpha_id": alpha_id,
                        "checklist": {"items": []},
                    }
                ),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"items": alpha_items}),
        )

    page.route("**/api/studio/alphas/user", alpha_user_fixture)
    page.route(
        f"**/api/studio/alphas/user/{alpha_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": alpha_id,
                    "name": "Existing Alpha Fixture",
                    "code": version2,
                    "version": 2,
                    "result": None,
                    "config": result["config"],
                }
            ),
        ),
    )
    page.route(
        f"**/api/studio/alphas/user/{alpha_id}/versions",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {"version": 2, "name": "Existing Alpha Fixture"},
                    {"version": 1, "name": "Existing Alpha Fixture"},
                ]
            ),
        ),
    )
    page.route(
        f"**/api/studio/alphas/user/{alpha_id}/versions/2",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"version": 2, "name": "Existing Alpha Fixture", "code": version2}),
        ),
    )
    page.route(
        f"**/api/studio/alphas/user/{alpha_id}/versions/1",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"version": 1, "name": "Existing Alpha Fixture", "code": version1}),
        ),
    )
    page.route(
        "**/api/studio/custom/backtest",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"job_id": job_id}),
        ),
    )
    page.goto(
        f"{BASE_URL}/studio?alpha={alpha_id}&version=2",
        wait_until="networkidle",
        timeout=15000,
    )
    editor = page.locator(".cm-content").first
    page.wait_for_function(
        "expected => document.querySelector('.cm-content')?.textContent.includes(expected)",
        arg="rsi < 36",
        timeout=10000,
    )
    page.get_by_role("button", name="v2 (lịch sử)").click()
    history = page.get_by_role("dialog", name="Lịch sử phiên bản")
    history.get_by_role("button", name="v1").click()
    history.get_by_role("button", name="Nạp v1 vào trình soạn").click()
    page.wait_for_function(
        "expected => document.querySelector('.cm-content')?.textContent.includes(expected)",
        arg="rsi < 35",
        timeout=10000,
    )
    save_button = page.get_by_role("button", name="Lưu chiến lược", exact=True)
    assert save_button.is_disabled()

    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.get_by_text(job_id).wait_for(state="visible", timeout=10000)
    page.wait_for_function("() => !document.querySelector('.se-save')?.disabled", timeout=10000)
    save_button.click()
    dialog = page.get_by_role("dialog", name="Lưu chiến lược")
    assert "Lưu thành phiên bản 2" in dialog.inner_text()
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/alphas/user")
        and response.request.method == "POST"
    ):
        dialog.get_by_role("button", name="Lưu chiến lược").click()
    page.get_by_role("heading", name="Đã lưu phiên bản 3 của chiến lược").wait_for(state="visible")
    assert len(save_requests) == 1
    assert save_requests[0]["alpha_id"] == alpha_id
    assert save_requests[0]["job_id"] == job_id
    assert save_requests[0]["code"] == version1

    page.wait_for_function(
        """expected => {
            const state = JSON.parse(sessionStorage.getItem('nora_studio_state_education') || '{}');
            return state.drafts?.some(d =>
                d.alphaId === 'phase2_existing_alpha' &&
                d.alphaVersion === 3 &&
                d.code === expected &&
                d.jobId === 'phase2_existing_alpha_job'
            );
        }""",
        arg=version1,
        timeout=5000,
    )
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.wait_for_function(
        "expected => document.querySelector('.cm-content')?.textContent.includes(expected)",
        arg="rsi < 35",
        timeout=10000,
    )
    page.get_by_text(job_id).wait_for(state="visible", timeout=10000)
    context.close()


def test_journey_5_error_handling_and_draft_safety(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    page.route(
        "**/api/edu/samples/visible",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"samples":[]}'),
    )
    page.route(
        "**/api/studio/education/samples",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    page.route(
        "**/api/studio/alphas/user",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"items":[]}'),
    )
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.evaluate(
        """() => {
            localStorage.setItem('nora_edu_onboarding', JSON.stringify({completed: true, dismissed: true}));
            sessionStorage.removeItem('nora_studio_state_education');
            localStorage.removeItem('nora_edu_draft_backup');
        }"""
    )
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1000)

    invalid_code = "class Broken(:\n    pass"
    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(invalid_code)
    assert editor.inner_text().strip() == invalid_code
    page.wait_for_function(
        """expected => {
            const raw = localStorage.getItem('nora_edu_draft_backup');
            return raw && JSON.parse(raw).code === expected;
        }""",
        arg=invalid_code,
        timeout=5000,
    )
    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/strategies/compile")
        and response.request.method == "POST"
    ) as response_info:
        page.get_by_role("button", name="Kiểm tra code").click()
    compile_result = response_info.value.json()
    assert compile_result["ok"] is False
    assert compile_result.get("error"), "Compiler must return a source-located error"
    assert "Lỗi" in page.locator(".se-strip-s").inner_text()

    page.reload(wait_until="networkidle")
    assert page.locator(".cm-content").inner_text().strip() == invalid_code
    backup = json.loads(page.evaluate("() => localStorage.getItem('nora_edu_draft_backup')"))
    assert backup["code"] == invalid_code
    context.close()


def test_journey_7_backtest_failure_retry_and_result_recovery(browser_instance):
    context = create_auth_context(browser_instance)
    page = context.new_page()
    install_run_defaults_fixture(page)
    page.route(
        "**/api/edu/samples/visible",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"samples":[]}'),
    )
    page.route(
        "**/api/studio/education/samples",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    page.route(
        "**/api/studio/alphas/user",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"items":[]}'),
    )

    failed_job_id = "phase2_failed_job"
    recovered_job_id = "phase2_recovered_job"
    recovered_result = run_result_fixture(recovered_job_id)
    recovered_result["metrics"]["simulate"].update({
        "trades": 0,
        "ret_pct": 0.0,
        "cagr_pct": 0.0,
        "mdd_pct": 0.0,
        "fees_usd": 0.0,
    })
    recovered_result["diagnostics"] = {
        "binding_condition": {
            "available": True,
            "rules": [{"index": 1, "all_true_bars": 0, "bars": 100}],
        },
    }
    install_done_job_fixture(page, recovered_job_id, recovered_result)
    failure_states = [
        {
            "status": "queued",
            "progress": {"pct": 4, "done": 0, "total": 5, "stage": "Biên dịch"},
            "log_tail": ["QUEUED-FIXTURE-LOG"],
        },
        {
            "status": "running",
            "progress": {"pct": 20, "done": 1, "total": 5, "stage": "Biên dịch"},
            "log_tail": ["QUEUED-FIXTURE-LOG", "RUNNING-FIXTURE-LOG"],
        },
        {
            "status": "failed",
            "error": "Fixture worker failure",
            "log_tail": ["QUEUED-FIXTURE-LOG", "RUNNING-FIXTURE-LOG", "Fixture worker failure"],
        },
    ]

    def failed_job(route):
        state = failure_states.pop(0) if len(failure_states) > 1 else failure_states[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": failed_job_id,
                    "job_id": failed_job_id,
                    "kind": "custom_backtest",
                    **state,
                }
            ),
        )

    page.route(f"**/api/studio/book/jobs/{failed_job_id}*", failed_job)
    submissions = []

    def submit_backtest(route):
        job_id = failed_job_id if not submissions else recovered_job_id
        submissions.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"job_id": job_id}),
        )

    page.route("**/api/studio/custom/backtest", submit_backtest)
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    page.evaluate(
        """() => {
            localStorage.setItem('nora_edu_onboarding', JSON.stringify({completed: true, dismissed: true}));
            sessionStorage.removeItem('nora_studio_state_education');
            localStorage.removeItem('nora_edu_draft_backup');
        }"""
    )
    page.reload(wait_until="networkidle")
    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(VALID_DSL)

    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.get_by_text(failed_job_id).wait_for(state="visible", timeout=10000)
    page.get_by_text("Đang chờ hàng đợi", exact=True).wait_for(state="visible", timeout=5000)
    page.get_by_text("QUEUED-FIXTURE-LOG", exact=True).wait_for(state="visible", timeout=5000)
    page.get_by_text("Đang chạy", exact=True).wait_for(state="visible", timeout=5000)
    page.get_by_text("RUNNING-FIXTURE-LOG", exact=True).wait_for(state="visible", timeout=5000)
    page.get_by_role("progressbar").wait_for(state="visible", timeout=5000)
    page.get_by_text("Thất bại", exact=True).wait_for(state="visible", timeout=10000)
    assert "QuickRsi" in editor.inner_text(), "A failed job must preserve the edited source"

    with page.expect_response(
        lambda response: response.url.endswith("/api/studio/custom/backtest")
        and response.request.method == "POST"
    ):
        page.get_by_role("button", name="Chạy backtest", exact=True).click()
    page.get_by_text(recovered_job_id).wait_for(state="visible", timeout=10000)
    assert "QuickRsi" in editor.inner_text()
    assert len(submissions) == 2
    assert submissions[0]["code"] == submissions[1]["code"] == VALID_DSL

    page.wait_for_function(
        """expected => {
            const state = JSON.parse(sessionStorage.getItem('nora_studio_state_education') || '{}');
            return state.drafts?.some(d => d.code === expected && d.jobId === 'phase2_recovered_job');
        }""",
        arg=VALID_DSL,
        timeout=5000,
    )
    page.goto(f"{BASE_URL}/studio", wait_until="networkidle", timeout=15000)
    assert "QuickRsi" in page.locator(".cm-content").first.inner_text()
    page.get_by_text(recovered_job_id).wait_for(state="visible", timeout=10000)
    results_tab = page.get_by_role("tab", name="Kết quả")
    assert results_tab.is_visible()
    results_tab.click()
    page.get_by_role("status").filter(has_text="Không có lệnh đóng hoặc vị thế mở trong kỳ").wait_for(timeout=5000)
    assert page.get_by_text("cả 1 quy tắc vào lệnh đều có 0 nến thỏa điều kiện").is_visible()
    context.close()


if __name__ == "__main__":
    pytest.main(["-v", __file__])
