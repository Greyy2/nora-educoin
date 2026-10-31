# Nora Product Surface Inventory & Acceptance Mapping (63 Requirements)

**Initial inventory:** 2026-10-24
**Current scope update:** 2026-10-29 — EDU-15/16 added; see their Phase 2 follow-up criteria.
**Deliverable ID:** `p0-product-surface-inventory`  
**Scope:** Rigorous mapping of all 63 current requirements across EDU, COIN Home/Portfolio, Alpha Authoring/Results, Prompt Research, Backtest/WFA/Monte Carlo, Live Operations/Leverage, and Cross-Product Isolation/Performance. The original foundation inventory had 58 requirements; later additions are assigned to their own phase gates and do not retroactively change historical acceptance.
**Document contract:** `product_ux_acceptance_matrix.md` is canonical for requirement status, owner, acceptance criteria and phase gates. This file records surface/architecture context. For new EDU-15/16 and CROSS-04/05 follow-ups, refer to the matrix rather than maintaining a second copy of their acceptance checklist here.

---

## Mục lục phân nhóm 63 yêu cầu

1. [EDU: Market, authoring, learning, identity, and backtest (EDU-01 – EDU-16)](#1-edu-market-authoring-learning-identity-and-backtest)
2. [COIN: Home and Portfolio (COIN-HOME-01 – COIN-HOME-06)](#2-coin-home-and-portfolio)
3. [COIN: Alpha authoring and results (COIN-ALPHA-01 – COIN-ALPHA-06)](#3-coin-alpha-authoring-and-results)
4. [COIN: Prompt / idea research (COIN-PROMPT-01 – COIN-PROMPT-09)](#4-coin-prompt--idea-research)
5. [COIN: Backtest, WFA, Monte Carlo, charts and runs (COIN-BT-01 – COIN-BT-06)](#5-coin-backtest-wfa-monte-carlo-charts-and-runs)
6. [COIN: Intraday, live operation, leverage and history (COIN-LIVE-00 – COIN-LIVE-13)](#6-coin-intraday-live-operation-leverage-and-history)
7. [Cross-product isolation, performance and operations (CROSS-01 – CROSS-06)](#7-cross-product-isolation-performance-and-operations)

---

## 1. EDU: Market, authoring, learning, identity, and backtest

### EDU-01 — Make Market/recommendations credible for quant use
- **Product & Route/View:** EDU — `/market` ([`EduMarket.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/EduMarket.jsx))
- **UI States:** Loading (skeleton), Empty (no alphas match filter), Error (fetch error alert), Success (rendered card grid).
- **API Endpoint:** `GET /api/edu/market` ([`system.py:645`](file:///home/vmc03/norabt/nora/edu/backend/routes/system.py#L645))
- **Request / Response Schema:** Query: none. Response: `List[AuthorMarketSummary]` (`id`, `handle`, `display_name`, `avatar`, `strategies: [{id, name, sharpe, ret_pct, mdd_pct, trades, win_rate, timeframe, created_at}]`).
- **Auth & Ownership:** Public read-only; aggregates alphas saved by users in `data/alpha/user/{uid}/`.
- **Data Source & Engine:** Stored Nautilus backtest metrics in user alpha directories.
- **Verified Evidence:** Route exists, UI card grid renders, `test_edu_imports_and_routes` checks endpoint existence.
- **Missing Evidence & Unknowns:** Metric calculation windows, sample size rules (e.g. min 30 trades), out-of-sample comparability, survivorship bias handling.

### EDU-02 — Make interactions with other authors/users correct
- **Product & Route/View:** EDU — `/u/:handle` ([`EduUser.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/EduUser.jsx)), `/s/:id` ([`EduStrategy.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/EduStrategy.jsx))
- **UI States:** Loading, 404 (user/strategy not found), Empty (author has no public alphas), Success.
- **API Endpoint:** `GET /api/users/{handle}`, `GET /api/users/{handle}/strategies`, `GET /api/edu/strategies/{alpha_id}`
- **Auth & Ownership:** Public author profiles show only public metadata; private settings remain restricted to session owner.
- **Data Source & Engine:** Filesystem user directory `data/users/{uid}.json` and `data/alpha/user/{uid}/`.
- **Verified Evidence:** Profile loading and strategy enumeration tested in `test_edu_account_bootstrap_and_lifecycle`.
- **Missing Evidence & Unknowns:** Browser journey verifying search/sort, author navigation in guest vs logged-in context, attribution persistence on direct URL refresh.

### EDU-03 — Open/run an existing alpha
- **Product & Route/View:** EDU — `/studio?id={alpha_id}` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx))
- **UI States:** Loading alpha content, Ready in CodeMirror, Compiling/Submitting, Queued/Running progress, Done/Error.
- **API Endpoint:** `GET /api/edu/strategies/{alpha_id}`, `POST /api/studio/custom/backtest`, `GET /api/studio/jobs/{job_id}`
- **Auth & Ownership:** Saved alpha loaded from user's directory. Custom backtest tagged with `owner_uid` (authenticated `usr_...` or guest `gst_...`).
- **Data Source & Engine:** EDU backtest engine (`backend.jobs.runner`), bounded to 2 GB RAM.
- **Verified Evidence:** Runner launch and job polling verified via `test_edu_guest_backtest_policy_and_isolation`.
- **Missing Evidence & Unknowns:** Browser journey loading an existing saved alpha, launching backtest, refreshing page, and recovering identical job/result state.

### EDU-04 — Change parameters of an existing alpha and run it
- **Product & Route/View:** EDU — `/studio` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx)), `ConfigForm` / parameter panel
- **UI States:** Parameter inputs, Validation state, Running, Result view with updated metrics.
- **API Endpoint:** `POST /api/studio/custom/backtest` (submitting modified parameter dictionary in payload).
- **Auth & Ownership:** Effective caller identity (`owner_uid`); does not mutate the saved alpha on disk until explicit Save.
- **Data Source & Engine:** Stored in `params.json` in job directory; executed by Nautilus runner.
- **Verified Evidence:** Parameter parsing in `batch_jobs_routes.build_job("custom_backtest", data)`.
- **Missing Evidence & Unknowns:** Proving that modifying parameters and running does not silently mutate the stored original alpha, and that reopening reproduces effective parameters.

### EDU-05 — Add/change logic in an existing alpha
- **Product & Route/View:** EDU — `/studio` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx)), `CodeEditor.jsx`
- **UI States:** Code typing, Syntax lint error banner (line, column), Running, Success result, Save Version modal.
- **API Endpoint:** `POST /api/studio/custom/backtest`, `POST /api/studio/alpha/user`
- **Auth & Ownership:** Stored under caller's alpha history.
- **Data Source & Engine:** Python/Nora DSL compiler `backend.analys.alpha.code.compile.compile_code`.
- **Verified Evidence:** `test_edu_backtest_pipeline` tests compilation of DSL code.
- **Missing Evidence & Unknowns:** Verification that syntax/compilation errors precisely map to line/col in UI, and draft code is preserved in localStorage upon run failure.

### EDU-06 — Copy/fork another author's Market strategy
- **Product & Route/View:** EDU — `/s/:id` ([`EduStrategy.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/EduStrategy.jsx)) -> Fork CTA -> `/studio`
- **UI States:** Forking indicator, Redirect to Studio with draft initialized, Original author attribution badge.
- **API Endpoint:** `POST /api/edu/strategies/{alpha_id}/fork`
- **Auth & Ownership:** Cloned draft is owned by current user (`usr_...` or `gst_...`); original strategy remains strictly immutable.
- **Data Source & Engine:** Reads source `alpha/user/{author_uid}/{alpha_id}/alpha.json`, clones to draft.
- **Verified Evidence:** Endpoint registered in `system.py`.
- **Missing Evidence & Unknowns:** Full browser journey proving source immutability, attribution retention, editing the fork, compiling, and saving.

### EDU-07 — Create a new alpha
- **Product & Route/View:** EDU — `/studio` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx))
- **UI States:** Clean/default template, Code editing, Validation/compile, Running, Save alpha dialog.
- **API Endpoint:** `POST /api/studio/custom/backtest`, `POST /api/studio/alpha/user`
- **Auth & Ownership:** Owned by current user identity; no cross-talk with COIN storage.
- **Data Source & Engine:** EDU Nautilus backtest runner (2 GB RAM).
- **Verified Evidence:** Custom backtest endpoint verified.
- **Missing Evidence & Unknowns:** Browser acceptance of a new alpha lifecycle (blank draft -> run -> save -> catalog -> reopen) without any COIN state leakage.

### EDU-08 — Show a 5–8 step guide to first-time users with no alpha
- **Product & Route/View:** EDU — `/studio` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx))
- **UI States:** First-time onboarding overlay, Step progression (1 of 8), Dismissed state, Resumed state.
- **API Endpoint:** `GET /api/users/me`, `GET /api/edu/samples/visible`
- **Auth & Ownership:** Triggers only when active identity has 0 saved alphas; dismissal preference stored in session/localStorage.
- **Data Source & Engine:** Static educational steps with embedded DSL examples.
- **Verified Evidence:** Sample strategies route exists.
- **Missing Evidence & Unknowns:** Ordered 5–8 step component with accessible keyboard navigation, dismissal, and persistent resume state.

### EDU-09 — Make the guide teach correct coding and what can be built
- **Product & Route/View:** EDU — `/studio` onboarding stepper content
- **UI States:** Interactive code snippets, Explainers for entry/exit rules, Indicator concepts.
- **Compiler / Engine:** Every code snippet must compile cleanly via `backend.analys.alpha.code.compile`.
- **Data Source & Engine:** Real historical OHLCV data assumptions.
- **Verified Evidence:** Compiler tests in `test_edu_backtest_pipeline`.
- **Missing Evidence & Unknowns:** Automated test asserting that all 5–8 guide code snippets pass the DSL compiler without errors or deprecations.

### EDU-10 — Ensure sample, copied and user-written strategies run smoothly and accurately in the view
- **Product & Route/View:** EDU — `/studio` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Studio.jsx))
- **UI States:** Form submission, Job progress bar, Log tail streaming, Result display (Equity, Trades, KPIs).
- **API Endpoint:** `POST /api/studio/custom/backtest`, `GET /api/studio/jobs/{job_id}`
- **Auth & Ownership:** Scoped to `owner_uid` (exact match required; fails closed for ownerless jobs).
- **Data Source & Engine:** EDU backtest engine (`ops/run_limited.sh -- -m backend.jobs.runner`), 2 GB RAM limit.
- **Verified Evidence:** `test_edu_guest_backtest_policy_and_isolation` and `test_edu_job_ownership_fails_closed_for_ownerless_jobs`.
- **Missing Evidence & Unknowns:** Combined browser journey covering all 4 strategy origins (sample, fork, new, edited) with deterministic oracle parity.

### EDU-11 — Make account creation easy and reliable
- **Product & Route/View:** EDU — `/login` ([`Login.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Login.jsx)), `EnterForm.jsx`
- **UI States:** Name input, Submitting spinner, Error text, Redirect.
- **API Endpoint:** `POST /api/me/enter`, `POST /api/me/logout`
- **Auth & Ownership:** Generates a fresh unique profile (`usr_...`); handle-only login returns 400; duplicate display name generates a distinct new user. UI explicitly warns this is quick-entry, not secure authentication.
- **Verified Evidence:** **PASS.** `test_edu_account_bootstrap_and_lifecycle` asserts 400 on handle-only login and fresh identity generation.

### EDU-12 — Add professional Google sign-in
- **Product & Route/View:** EDU — `/login`
- **Status:** **BLOCKED / ABSENT (PASS).**
- **Verified Evidence:** Verified absent from frontend and backend; no stub or fake button displayed. `test_edu_google_oauth_readiness_and_absence` PASSED.

### EDU-13 — Initialize new-user data correctly
- **Product & Route/View:** EDU — `/me` ([`MyProfile.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/MyProfile.jsx))
- **UI States:** Initialized profile, Default avatar, Empty strategy list, 0 count.
- **API Endpoint:** `GET /api/me`, `GET /api/users/{handle}/strategies`
- **Auth & Ownership:** Strictly scoped to new user ID; zero initial strategies; completely isolated from COIN state.
- **Verified Evidence:** **PASS.** `test_edu_account_bootstrap_and_lifecycle` PASSED.

### EDU-14 — Backtest allowed for an unauthenticated user must be real and accurate
- **Product & Route/View:** EDU — `/studio`
- **UI States:** Unauthenticated guest submission, Progress, Result view, Login prompt only when saving.
- **API Endpoint:** `POST /api/studio/custom/backtest`, `GET /api/studio/jobs/{job_id}`
- **Auth & Ownership:** Per-session 128-bit `edu_guest_id` (`gst_<32hex>`), exact owner job scoping, atomic admission lock (1 active/guest, 3 active aggregate), 2 GB/job limit.
- **Verified Evidence:** **PASS.** `test_edu_guest_backtest_policy_and_isolation` and `test_edu_guest_admission_quota_is_atomic_and_counts_all_active_jobs` PASSED.

### EDU-15 — Forked/copied alpha parameters must remain editable, valid and reproducible
- **Surface:** EDU — Market strategy -> fork -> `/studio`, parameter form and run result.
- **Scope/status:** See canonical EDU-15 row and `p2-edu-alpha-parameter-fidelity` in [product_ux_acceptance_matrix.md](./product_ux_acceptance_matrix.md). Prior representative fork/edit evidence does not establish arbitrary parameter or timeframe coverage.

### EDU-16 — Market result availability and detail must identify the same completed run
- **Surface:** EDU — `/market` alpha card -> exact backtest result/detail view.
- **Scope/status:** User-reported mismatch is not yet reproduced. See canonical EDU-16 row and `p2-edu-market-result-reconciliation` in [product_ux_acceptance_matrix.md](./product_ux_acceptance_matrix.md); do not infer a cause from this inventory.

---

## 2. COIN: Home and Portfolio

### COIN-HOME-01 — Regime represents current live market, not historical regime
- **Product & Route/View:** COIN — `/coin/portfolio` ([`Portfolio.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Portfolio.jsx)), `RegimePanel.jsx`
- **UI States:** Live indicator, Stale warning, Error notice, Loading skeleton.
- **API Endpoint:** `GET /api/studio/market/regime` ([`routes/data.py`](file:///home/vmc03/norabt/nora/coin/backend/routes/data.py))
- **Data Source & Engine:** Evaluated on 15m closed bars from market manifest.
- **Gap & Required Contract:** Define authoritative feed cadence, intrabar vs closed-bar semantics, `as_of` timestamp, freshness window (<15m), and explicit error handling without falling back to historical `RANGE`.

### COIN-HOME-02 — Display regime name/status on a bar with 0 center, red short/bear and green long/bull
- **Product & Route/View:** COIN — `/coin/portfolio`, `RegimeScale.jsx`
- **UI States:** Center 0 (`RANGE`), Left negative (`TREND_DOWN`, `CRASH`), Right positive (`TREND_UP`, `SURGE`), Ancillary badge (`VOL_EXPANSION`).
- **Contract Specification:** Discrete mapping to `[-2, -1, 0, +1, +2]`. No fabricated floating-point scores. Accessible ARIA attributes (`role="meter"`).
- **Verified Evidence:** Backend categorical states verified in `test_coin_market_regime_categorical_contract`.
- **Missing Evidence:** Component implementation and browser validation.

### COIN-HOME-03 — Remove old regime title/legend, active-strategy list, 30-day history, candle timeframe and "from" decoration
- **Product & Route/View:** COIN — `RegimePanel.jsx`
- **UI States:** Clean, compact card with only the directional scale, current regime name/status, and `as_of` time.
- **Missing Evidence:** Removing obsolete DOM elements while preserving error/stale status.

### COIN-HOME-04 — Make MDD/drawdown compact
- **Product & Route/View:** COIN — `/coin/portfolio`, `Kpi.jsx` / `OverviewExtras.jsx`
- **UI States:** Compact metric card showing Max Drawdown percentage, period, and value without dominating screen space.
- **Missing Evidence:** Component layout adjustment and viewport responsive verification.

### COIN-HOME-05 — Replace "Số lệnh" parameter with Profit
- **Product & Route/View:** COIN — `/coin/portfolio`
- **UI States:** Metric display with authoritative currency (USDT) and percentage.
- **Requirement:** Must use legitimate profit calculation; never relabel trade count as profit. If no valid profit metric exists, display explicit unavailable state.
- **Missing Evidence:** Tracing authoritative profit field in overview payload.

### COIN-HOME-06 — Remove legacy "Hệ thống", system performance and specified regime/active-strategy panels
- **Product & Route/View:** COIN — `/coin/portfolio` ([`Portfolio.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Portfolio.jsx))
- **UI States:** Streamlined portfolio dashboard focused on personal capital, positions, and live operations.
- **Missing Evidence:** DOM pruning and browser visual validation.

---

## 3. COIN: Alpha authoring and results

### COIN-ALPHA-01 — Support complex/detailed strategy authoring and clear interactions
- **Product & Route/View:** COIN — `/coin/alpha/create` ([`Studio.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Studio.jsx)), `CodeEditor.jsx`
- **UI States:** Code editing, Python syntax highlighting, Validation feedback, Unsaved changes guard.
- **API Endpoint:** `POST /api/studio/custom/backtest`
- **Data Source & Engine:** Supported Nora Python/DSL engine.
- **Missing Evidence:** Documenting supported API surfaces and verifying error recovery in CodeEditor.

### COIN-ALPHA-02 — Run authoring-view backtest smoothly and accurately on Nora engine
- **Product & Route/View:** COIN — `/coin/alpha/create`
- **API Endpoint:** `POST /api/studio/custom/backtest`, `GET /api/studio/jobs/{job_id}`
- **Engine:** COIN Nautilus runner (4 GB RAM limit).
- **Missing Evidence:** Verifying end-to-end lifecycle (compile -> queue -> progress -> cancel -> result) matches independent accounting oracle.

### COIN-ALPHA-03 — Fix broken Strategy-tab result metrics
- **Product & Route/View:** COIN — `/coin/alpha/create`, `CustomResult.jsx`, `StrategyTab.jsx`
- **UI States:** Metrics table, Equity chart, Trade list.
- **Symptom & Gap:** Specific alpha IDs reported to produce mismatched or empty metrics in the Strategy tab. Needs payload reproduction and fix.

### COIN-ALPHA-04 — Remove "Khớp Nhanh" from requested result
- **Product & Route/View:** COIN — `CustomResult.jsx`, `ProvenanceBadge.jsx`
- **Requirement:** Remove misleading "Khớp Nhanh" badge while retaining truthful execution timeframe/fill provenance.

### COIN-ALPHA-05 — Display 10 trades per page
- **Product & Route/View:** COIN — `CustomResult.jsx` (Trades table pagination)
- **UI States:** Exactly 10 rows per page, accessible pagination controls (Previous, Next, Page Numbers).
- **Missing Evidence:** Frontend table pagination state update from default 50 to 10.

### COIN-ALPHA-06 — Zoom Equity, PnL and Drawdown charts using pointer/wheel
- **Product & Route/View:** COIN — `CustomResult.jsx`, `AreaLine.jsx`
- **UI States:** Mouse wheel zoom, Pan along time axis, Double-click / button reset, Synchronized crosshair.
- **Engine:** TradingView lightweight-charts configuration.

---

## 4. COIN: Prompt / idea research

### COIN-PROMPT-01 — Professional visual design inspired by Sova Quanta research
- **Product & Route/View:** COIN — `/coin/alpha/create` (mode="research"), `PromptResearchView.jsx`
- **UI States:** Clean 3-tab layout, Dense quantitative typography, Responsive sidebar.

### COIN-PROMPT-02 — Tab 1: idea input, run and progress/log
- **UI States:** Hypothesis input textarea, Generation parameters, Step-by-step progress, Live log stream.
- **API Endpoint:** `POST /api/studio/alpha/prompt/generate`, `GET /api/studio/jobs/{job_id}`

### COIN-PROMPT-03 — Separate prompt-alpha library, distinct from strategy/scan alpha
- **Requirement:** Dedicated storage, list, detail, and lifecycle API for prompt-generated hypotheses, distinct from production book strategies.
- **API Endpoint:** `/api/studio/alpha/prompt/*`

### COIN-PROMPT-04 — Include LLM capability/settings
- **UI States:** Provider selector (Anthropic, OpenAI, Local), Model selection, Temperature/MaxTokens settings (without exposing API keys).

### COIN-PROMPT-05 — Combine LLM with research from external sources
- **Requirement:** Grounded generation with cited sources carrying URL, timestamp, excerpt, or content hash; explicit failure when sources unreachable.

### COIN-PROMPT-06 — Create new hypotheses, not parameter tuning; separate generation and validation
- **Requirement:** Structure hypothesis into economic rationale, testable condition, out-of-sample validation plan, and distinct statuses (`generated`, `tested`, `validated`).

### COIN-PROMPT-07 — Tab 3: research/run configuration
- **UI States:** Symbol universe, Timeframe, Slippage/Fee assumptions, Train/Test split ratio.

### COIN-PROMPT-08 — Run through Nora's own backtest engine
- **Requirement:** Prompt backtest execution must route directly to the genuine Nora Nautilus engine (4 GB cap), not an external or stub engine.

### COIN-PROMPT-09 — Three tabs fit intended view sizes
- **Requirement:** Responsive verification of Idea/Run, Registry, and Config tabs across 1280px, 1440px, and 1920px viewports without clipping.

---

## 5. COIN: Backtest, WFA, Monte Carlo, charts and runs

### COIN-BT-01 — Backtest/scan and all run features are correct and smooth
- **Product & Route/View:** COIN — `/coin/backtest` ([`Backtest.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Backtest.jsx))
- **Engine:** Nautilus backtest, Scan runner, WFA engine, Monte Carlo engine.

### COIN-BT-02 — Progress/log updates are accurate and stable
- **Component:** `JobPanel.jsx`
- **UI States:** Queued, Running with percentage, Log tail streaming, Cancel button, Finished/Failed transition.

### COIN-BT-03 — Make charts large and visually balanced in each tab
- **Component:** `Backtest.jsx`, `AreaLine.jsx`
- **UI States:** Maximized chart width, Balanced aspect ratio, Readable axes and legends.

### COIN-BT-04 — Ensure every chart maps to exact evaluation parameters
- **Requirement:** Assert plotted data points match backend JSON series (Equity, PnL, Drawdown) without interpolated or invented values.

### COIN-BT-05 — WFA logic and UI are correct
- **Component:** `WfaResult.jsx`
- **Data Source:** Walk-forward in-sample and out-of-sample window folds; verify fold boundaries and aggregate efficiency ratio.

### COIN-BT-06 — Monte Carlo logic and UI are correct
- **Component:** `McResult.jsx`
- **Data Source:** 10,000 simulation runs; verify confidence interval bands (5%, 50%, 95%) and ruin probability against independent oracle.

---

## 6. COIN: Intraday, live operation, leverage and history

### COIN-LIVE-00 — Focus Live on intraday alpha operation without lowering risk guards
- **Product & Route/View:** COIN — `/coin/live` ([`Live.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Live.jsx))
- **Requirement:** Intraday bot management, multi-symbol constraints, emergency kill-switch; 4 GB RAM cap.

### COIN-LIVE-01 — Show total capital, today/total PnL, win rate, MDD, open positions, PF and Sharpe
- **Component:** `LiveOverview.jsx`
- **Data Source:** Authoritative master ledger snapshot from `/api/live/portfolio/master`.

### COIN-LIVE-02 — Show a small intraday PnL chart
- **Component:** Intraday PnL sparkline/area chart anchored to UTC/local day boundary.

### COIN-LIVE-03 — Replace oversized capital area with compact reconciled resource bar
- **Component:** `ResourceBar.jsx`
- **UI States:** Compact bar displaying total equity, margin used, and available headroom.

### COIN-LIVE-04 — Remove specified allocated/unallocated/equity-headroom/free-cash/margin/master-risk figures
- **Requirement:** Clean up redundant and non-authoritative metrics from Live header.

### COIN-LIVE-05 — Expand bot/position list with strategy, mode, venue, symbol, side, entry/current, value, leverage, unrealized PnL, hold time and actions
- **Component:** `LiveBotTable.jsx`, `PositionsTable.jsx`
- **UI States:** Comprehensive columns with real-time updates and manual close/stop controls.

### COIN-LIVE-06 — Selecting/starting a bot must operate correctly from UI
- **API Endpoint:** `POST /api/live/bot`, `POST /api/live/bot/{id}/resume`, `POST /api/live/bot/{id}/stop`
- **Verification:** Test bot lifecycle transitions (creating, starting, pausing, stopping) via testnet.

### COIN-LIVE-07 — Rename page to “Giao dịch” and remove obsolete helper copy
- **UI States:** Page header and navigation link updated to "Giao dịch".

### COIN-LIVE-08 — Show portfolio risk for symbols traded by enabled bots
- **Component:** `PortfolioRiskPanel.jsx`
- **Data Source:** Net exposure and concentration across all active bots.

### COIN-LIVE-09 — Apply correct leverage semantics based on Nautilus/TradingView/venue behavior
- **Requirement:** Differentiate TradingView display leverage from OKX executable margin/leverage rules.

### COIN-LIVE-10 — Make history accurate
- **Product & Route/View:** COIN — `/coin/history` ([`History.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/History.jsx))
- **Data Source:** SQLite archive `/api/live/archive`. Deduplicated trades, accurate PnL, UTC timestamps.

### COIN-LIVE-11 — Nora-owned execution/fill/close logic should follow Nautilus reference semantics and match Nora backtest where configured
- **Requirement:** Execution engine parity testing against exchange stub/testnet fixtures.

### COIN-LIVE-12 — Bot start/select must update list and report outcomes
- **Product & Route/View:** COIN — `/coin/live` ([`Live.jsx`](../coin/frontend/src/pages/Live.jsx))
- **Relevant API:** `POST /api/live/bot`, `GET /api/live/bots`, `GET /api/live/bot/{bot_id}`.
- **Reported symptoms (not yet reproduced):** start errors; successfully enabled bots absent from the visible list; no clear success confirmation.
- **Acceptance:** follow the real start response through bot ID/status, list/detail refresh and selected row; confirm success only after backend acceptance and visibility; make errors actionable. Test loading, empty, timeout/retry and page reload in paper/testnet or stub only.

### COIN-LIVE-13 — Reconcile stale bot status before deletion
- **Product & Route/View:** COIN — `/coin/live` bot actions in [`Live.jsx`](../coin/frontend/src/pages/Live.jsx)
- **Relevant API:** `GET /api/live/bots`, `DELETE /api/live/bot/{bot_id}`, `POST /api/live/bot/{bot_id}/stop`.
- **Reported symptoms (not yet reproduced):** old failed/zero-activity bots appear stopped but deletion reports “stop bot first.”
- **Acceptance:** compare UI status with persisted bot status, process/worker liveness and heartbeat. Never delete a genuinely running/starting bot; permit safe cleanup of confirmed stopped/failed orphan records; stale/unknown state must trigger refresh/reconciliation rather than a false running conflict. Test running, stopped, failed, stale and missing-process cases.

---

## 7. Cross-product isolation, performance and operations

### CROSS-01 — Remove visible COIN↔EDU switch buttons
- **Status:** **PASS.** Layouts separated in `CoinLayout.jsx` and `EduLayout.jsx`; verified in source and headless Chrome DOM.

### CROSS-02 — Make each Home independent and product-only
- **Status:** **PASS.** COIN Home ([`coin/pages/Home.jsx`](file:///home/vmc03/norabt/nora/coin/frontend/src/pages/Home.jsx)) and EDU Home ([`edu/pages/Home.jsx`](file:///home/vmc03/norabt/nora/edu/frontend/src/pages/Home.jsx)) verified independently via headless Chrome DOM dumps.

### CROSS-03 — Make each Login independent and product-only
- **Status:** **PASS.** Login pages branded separately; name quick-entry hardened against account takeover; Google button absent.

### CROSS-04 — Make all requested views/runs fast, smooth, responsive and accessible
- **Status:** **PARTIAL.** EDU backtest performance acceptance is open. The historical 10-market, 1h sample was about 180.5 seconds and 1,795 MB cgroup peak on a 2 GiB limit; this is one prior observation, not a current baseline or SLO.
- **Scope:** See canonical CROSS-04 and `p2-edu-performance-and-resource-followup` in [product_ux_acceptance_matrix.md](./product_ux_acceptance_matrix.md).

### CROSS-05 — Keep both backtest systems resource-bounded
- **Status:** **PARTIAL.** Hard caps remain verified: COIN 4 GB/job, EDU 2 GB/job. The historical EDU job reached about 88% of its job cgroup limit; this is a safety signal to remeasure, not proof of a universal workload ceiling.
- **Scope:** See canonical CROSS-05 and `p2-edu-performance-and-resource-followup` in [product_ux_acceptance_matrix.md](./product_ux_acceptance_matrix.md). Keep the shared market catalog read-only and distinguish it from product-local caches/results.

### CROSS-06 — Split oversized route modules into domain-focused files
- **Product & Route/View:** COIN and EDU backend route packages. This is a historical modularization requirement; the route extraction is already implemented and verified.
- **Goal:** reduce concentration of unrelated route handlers and make ownership/testing/navigation clearer without changing runtime behavior.
- **Acceptance:** inventory route domains, schemas, shared dependencies, startup hooks and import relationships; split into cohesive modules and register routers explicitly. Preserve every public HTTP method/path, request/response and OpenAPI schema/security, auth/ownership behavior, tags/prefixes, startup behavior and compatibility imports. Avoid circular imports, duplicate route registration and catch-all replacement modules.
- **Verification:** focused domain tests and both full product suites; before/after OpenAPI contract comparison (paths, methods, request/response schemas and security); product import-origin/isolation tests; frontend API path check; route registration count and `git diff --check`.
- **Status:** **VERIFIED** — `p4-route-modularization`; see canonical matrix row for OpenAPI and test evidence. The old source line-count snapshot is intentionally omitted because it no longer describes the current modules.
