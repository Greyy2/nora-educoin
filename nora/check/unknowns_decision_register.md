# Architecture & Product Unknowns Decision Register

**Status:** APPROVED & LOCKED  
**Date:** 2026-10-24  
**Applies to:** COIN and EDU Platforms (Nora Quant System)  
**Parent Gate:** Phase 2 Foundation Entry Gate (`ux-phase-0-foundation`)

---

## 1. Executive Summary

This register formally records the architectural, quantitative, and product decisions for all open unknowns across the COIN and EDU platforms. Per system quality requirements, **no unresolved decision may be silently replaced with default, success-shaped, or fabricated values** (such as hardcoded `RANGE` regime, 10,000 USDT capital, or unverified Sharpe ratios). Every downstream task in Phase 2, Phase 3, and Phase 4 must implement and adhere to the contracts specified herein.

---

## 2. Decision Index

| Decision ID | Scope / Requirements | Subject | Owner | Status |
|---|---|---|---|---|
| **DEC-01** | EDU-01, EDU-02 | Market Metric Normalization & Strategy Comparability | Quant/Backend | APPROVED |
| **DEC-02** | EDU-03, EDU-04, EDU-05, EDU-07, EDU-10, COIN-BT-01, COIN-BT-04 | Immutable Run Provenance Contract | Engine/Backend | APPROVED |
| **DEC-03** | EDU-05, EDU-06, EDU-07 | Strategy Save, Versioning & Fork Semantics | Backend/Auth | APPROVED |
| **DEC-04** | EDU-08, EDU-09 | Guided Onboarding Persistence & Dismissal Contract | Frontend/Arch | APPROVED |
| **DEC-05** | COIN-HOME-01, COIN-HOME-02, COIN-HOME-03 | Live Market Regime Source & Truthful Fallbacks | Quant/Live | APPROVED |
| **DEC-06** | COIN-LIVE-01, COIN-LIVE-03, COIN-LIVE-04, COIN-LIVE-09 | Live Ledger, Capital & Position Truthfulness | Trading/Live | APPROVED |
| **DEC-07** | EDU-14, CROSS-05 | Guest Capabilities, Concurrency & Resource Enforcement | Infra/Engine | APPROVED |

---

## 3. Detailed Decision Records

### DEC-01: Market Metric Normalization & Strategy Comparability (EDU-01, EDU-02)

#### Problem
The Market tab lists user and community strategies with metrics such as Return, Sharpe, and Max Drawdown (MDD). However, if backtest windows, sample sizes, and asset classes vary wildly (e.g. 5 trades over 3 days vs 500 trades over 1 year), raw sorting produces misleading rankings that reward curve-fitted flukes.

#### Approved Resolution
1. **Eligible Run Statuses:** Only backtest runs with state `COMPLETED` and clean execution logs are eligible for ranking consideration. Failed, timed-out, canceled, or out-of-memory jobs are excluded from leaderboards.
2. **Minimum Statistical Sample Threshold:**
   - A strategy must have executed at least **$N \ge 20$ trades** over a minimum evaluation span of **30 closed calendar days** (or at least 500 bars on sub-hourly frames).
   - Strategies not meeting this threshold are clearly badged: `UNRANKED (Insufficient sample size: <N>/20 trades)`. They may still be viewed in author profiles but are not ranked in competitive leaderboards.
3. **Partitioned Comparability:**
   - Strategies must not be ranked against each other across different asset classes or timeframes without clear filtering.
   - The Market view provides explicit filter facets: `Asset` (e.g. BTC-USDT, ETH-USDT), `Timeframe` (e.g. 15m, 1h, 4h), and `Market Regime Context`.
4. **Truthful Metric Rendering:**
   - If a metric cannot be calculated mathematically (e.g. standard deviation of returns is 0, giving an undefined Sharpe ratio), the UI renders `--` or `N/A`, never `0.00` or a dummy value.
   - Win Rate is defined strictly as $\frac{\text{Winning Trades}}{\text{Total Closed Trades}}$. Breakeven trades count toward the denominator.

#### Owner clarification and implementation contract (2026-10-24)

The owner confirmed that regime context in EDU Market is a compact reference, not an input to strategy calculations, and should describe the same window used by the backtest. Accordingly, the saved EDU run records a descriptive dominant label plus per-label distribution and classified-bar coverage, derived from actual closed 15m bars in that exact backtest window using EDU's existing causal regime classifier. The Market facet is only enabled with the same symbol, timeframe, and start/end window required for comparable metrics.

This context does not change strategy signals, fills, PnL, or ranking thresholds. It is bound to the run's symbol-specific dataset SHA-256. Unknown/unclassified or unavailable windows have explicit `unavailable` status and are excluded from regime-filtered results; no COIN live-regime value or fabricated fallback is used.

---

### DEC-02: Immutable Run Provenance Contract (EDU-03, EDU-04, EDU-05, EDU-07, EDU-10, COIN-BT-01, COIN-BT-04)

#### Problem
Users need to know with 100% certainty that a displayed backtest result corresponds to the exact code, parameters, dataset, and engine configuration that produced it, and that refreshing or reopening the result will not alter or mutate the findings.

#### Approved Resolution
1. **Mandatory Stamped Run Metadata:** Every run executed by the Nora engine (EDU DSL or COIN Nautilus/Nora) must stamp an immutable `run_manifest.json` containing:
   ```json
   {
     "job_id": "job_<uuid4>",
     "owner_uid": "<uid_or_guest_capability>",
     "product": "EDU" | "COIN",
     "code_hash": "<sha256_of_normalized_source>",
     "effective_params": {
       "<param_name>": "<param_value>"
     },
     "dataset": {
       "symbol": "BTC-USDT",
       "timeframe": "15m",
       "start_date": "2024-01-01T00:00:00Z",
       "end_date": "2024-06-01T00:00:00Z",
       "bar_count": 14592,
       "data_digest": "sha256:<hash>"
     },
     "engine": {
       "name": "nora-edu-dsl",
       "version": "1.0.0",
       "memory_cap_bytes": 2147483648
     },
     "timestamps": {
       "queued_at": "2026-10-24T08:00:00Z",
       "started_at": "2026-10-24T08:00:01Z",
       "completed_at": "2026-10-24T08:00:08Z",
       "duration_ms": 7140
     },
     "execution_metrics": {
       "peak_rss_bytes": 284344320,
       "exit_code": 0,
       "status": "COMPLETED"
     }
   }
   ```
2. **UI Verification & Display:**
   - The result panel renders a `ProvenanceBadge` displaying the shortened `code_hash` (e.g., `sha256:7f3a...`), dataset period, and effective parameters.
   - When a result is reloaded from `job_id`, the UI populates directly from the immutable manifest.
   - If the code currently in the editor differs from `code_hash`, the UI flags: `KẾT QUẢ CỦA BẢN TRƯỚC (Code modified since this run)`.

---

### DEC-03: Strategy Save, Versioning & Fork Semantics (EDU-05, EDU-06, EDU-07)

#### Problem
Editing or forking strategies must not overwrite prior working versions, lose uncommitted edits during compilation errors, or mutate the original author's strategy.

#### Approved Resolution
1. **Versioning Model:**
   - Each strategy has an immutable identifier `alpha_id` (e.g. `alp_<uuid4>`) and a monotonic integer `version` (starts at `1`).
   - Saving a modified strategy creates a new immutable version record (`version + 1`).
   - Prior versions remain retrievable via history (`/api/edu/strategy/{alpha_id}/history`).
2. **Draft Safety & Compilation Failure:**
   - Unsaved or in-progress edits in the web editor are mirrored to browser `localStorage` under `edu_draft_{alpha_id}`.
   - If compilation fails, the server rejects saving as a published version. The user's in-editor draft is preserved locally with line-mapped error annotations, while the server-side latest valid version remains untouched.
3. **Fork Semantics:**
   - Endpoint: `POST /api/edu/strategy/{alpha_id}/fork`.
   - Behavior:
     - Generates a new `alpha_id` owned by the calling user (`owner_uid = current_user.uid`).
     - Deep-copies code and default parameters.
     - Stamped immutable provenance:
       ```json
       "forked_from": {
         "alpha_id": "<original_alpha_id>",
         "version": 2,
         "author_uid": "<original_author_uid>",
         "author_handle": "@alice",
         "code_hash": "<sha256_at_time_of_fork>",
         "forked_at": "2026-10-24T08:30:00Z"
       }
       ```
     - The original author's strategy is 100% immutable to the forker; editing or running the fork has zero side effects on the source.

---

### DEC-04: Guided Onboarding Persistence & Dismissal Contract (EDU-08, EDU-09)

#### Problem
First-time users need clear pedagogical guidance through the quant authoring lifecycle without creating an annoying, un-dismissible popup that re-appears on every page refresh or irritates returning users.

#### Approved Resolution
1. **8-Step Educational Sequence:**
   - **Step 1:** Giới thiệu Studio (Studio layout, editor vs result views).
   - **Step 2:** Cấu trúc DSL Nora (Indicators, condition blocks, entry/exit rules).
   - **Step 3:** Khám phá Mẫu có sẵn (Loading pre-built SMA/RSI strategies).
   - **Step 4:** Tinh chỉnh tham số (Editing stop loss, take profit, lookback periods).
   - **Step 5:** Kiểm tra cú pháp (Compiler validation and line-mapped diagnostics).
   - **Step 6:** Chạy kiểm thử (Executing backtest on historical OHLCV data).
   - **Step 7:** Đọc hiểu kết quả (Interpreting Equity curve, Sharpe, MDD, win rate).
   - **Step 8:** Lưu & Quản lý phiên bản (Version control, cataloging, next steps).
2. **Persistence Schema:**
   - Stored in browser `localStorage` under key `nora_edu_onboarding`:
     ```json
     {
       "completed": false,
       "dismissed": false,
       "current_step": 3,
       "last_active": "2026-10-24T08:35:00Z"
     }
     ```
3. **Behavioral Triggers:**
   - A user with 0 saved strategies and no `nora_edu_onboarding` record receives the onboarding banner/modal.
   - Clicking **"Bỏ qua / Đóng"** immediately sets `dismissed: true`; the tour closes and will NOT auto-open again.
   - Re-engagement: A permanent **"Hướng dẫn / Tour"** button in the Studio navigation allows any user to manually launch or resume the tour at any time.

---

### DEC-05: Live Market Regime Source & Truthful Fallbacks (COIN-HOME-01, COIN-HOME-02, COIN-HOME-03)

#### Problem
Legacy views rendered historical candle regime classification and defaulted to `RANGE` whenever live feeds were unavailable. This misleads users into believing a live market detector is active.

#### Approved Resolution
1. **Authoritative Source & Schema:**
   - Live regime endpoint: `/api/studio/market/regime` must provide:
     ```json
     {
       "as_of": "2026-10-24T08:35:00Z",
       "regime": "BULL" | "BEAR" | "RANGE" | "VOLATILE",
       "confidence": 0.82,
       "cadence_sec": 60,
       "source": "live_binance_feed",
       "is_stale": false
     }
     ```
2. **Staleness & Disconnection Boundaries:**
   - If `as_of` timestamp is older than **30 minutes**, or the backend feed is unreachable, `is_stale` is set to `true`.
   - UI display:
     - Normal: Directional visual (Green Bull, Red Bear, Neutral Range, Amber Volatile) with explicit `as_of` time.
     - Stale / Errored: Renders greyed-out badge `DỮ LIỆU CŨ / MẤT KẾT NỐI (Feed Stale)` and an explicit warning.
     - **FORBIDDEN:** Never silently fall back to historical `RANGE` or fabricate a 0-centered score when real feed data is missing.

---

### DEC-06: Live Ledger, Capital & Position Truthfulness (COIN-LIVE-01, COIN-LIVE-03, COIN-LIVE-04, COIN-LIVE-09)

#### Problem
Live and paper trading views previously displayed arbitrary capital numbers (like 10,000 USDT) and estimated leverage without reconciliation against the real trading node or exchange balances.

#### Approved Resolution
1. **Master Capital Reconciliation:**
   - Master ledger values (Total Balance, Free Margin, Used Margin, Unrealized PnL) must be retrieved directly from the live Nautilus node or exchange balance query.
   - If the trading node is disconnected or initializing, capital renders as `ĐANG TẢI...` or `-- USDT`, never hardcoded placeholder figures.
2. **Leverage Semantics:**
   - Leverage must reflect the actual exchange contract specification (e.g. OKX cross margin 3x, 5x, 10x).
   - If leverage is dynamic or not explicitly reported by the venue API, it must render as `--` or `Unspecified`, rather than assuming 1x.
3. **Daily PnL Boundary:**
   - Today's PnL is computed strictly from **00:00:00 UTC** of the current calendar day to current timestamp.
   - Realized and unrealized PnL are reported distinctly:
     $$\text{Total Today PnL} = \text{Realized PnL Today} + \Delta\text{Unrealized PnL Today} - \text{Fees/Funding Today}$$

---

### DEC-07: Guest Capabilities, Concurrency & Resource Enforcement (EDU-14, CROSS-05)

#### Problem
Anonymous guests must be able to explore EDU backtests without creating Denial of Service (DoS) risks or exhausting server memory.

#### Approved Resolution
1. **128-bit Capability:**
   - Every guest receives a cryptographically secure 128-bit cookie `edu_guest_id` (`gst_<32hex>`).
   - Guest backtest jobs are owned strictly by this capability.
2. **Atomic Quota Gate:**
   - **Per-guest limit:** Maximum **1 active job** per guest capability.
   - **Aggregate guest limit:** Maximum **3 active guest jobs** system-wide.
   - File-locking serialization (`_guest_job_admission_lock()`) ensures zero race conditions across multi-worker deployments.
3. **Memory Caps:**
   - EDU jobs: strictly capped at **2 GB RSS**.
   - COIN jobs: strictly capped at **4 GB RSS**.
   - Jobs exceeding limits are terminated immediately by process monitor with an explicit `OUT_OF_MEMORY` status code.

---

## 4. Verification and Enforcement

Every code change in Phase 2, Phase 3, and Phase 4 must cite these decision IDs (`DEC-01` through `DEC-07`) in comments, commit messages, and test cases. Automated unit and integration tests must assert compliance with these contracts.
