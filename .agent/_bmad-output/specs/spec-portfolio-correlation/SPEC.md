# SPEC: Multi-Bot Portfolio Correlation and Joint Risk Engine

> **BMAD Document Standard (Derived Spec)**  
> **Source Memory:** `_bmad-output/specs/spec-portfolio-correlation/.memlog.md`  
> **Topic:** Multi-Bot Portfolio Correlation and Joint Risk Engine  
> **Goal:** Quantify cross-bot correlation, detect diversification illusion, joint Monte Carlo stress test  
> **Status:** APPROVED / PRODUCTION READY  
> **Date:** 2026-09-23  

---

## 1. Why (Problem Statement & Business Value)

In cryptocurrency copy-trading on OKX, investors routinely attempt to diversify risk by following 2 to 8 different bots operating across different asset pairs (e.g. BTC, ETH, SOL). However, they frequently fall victim to the **Diversification Illusion**:
- Bots running on separate tickers frequently utilize identical breakout or momentum logic, entering and exiting positions concurrently.
- Simultaneous drawdown occurs during broad market sell-offs ($MDD_{joint} \approx \sum w_i MDD_i$), rendering the portfolio as volatile as holding a single over-leveraged asset.
- Opposing positions on the same coin neutralize net market exposure while accumulating double transaction fees and funding costs.

This engine provides automated, quantitative portfolio supervision, computing real cross-bot return correlation, exit-rule strategy distances, synchronized joint bootstrap stress tests, and exposure concentration to protect copier capital.

---

## 2. Capabilities (Derived from Memlog)

- **CAP-1 [TimeSeriesMerger]:** Synchronizes tick-level trade series of 2 to 8 bots onto a shared 1-hour candle time-grid with zero-fill interpolation for inactive intervals.
- **CAP-2 [CorrelationAnalyzer]:** Computes pairwise Pearson and Spearman return correlation matrices alongside normalized Euclidean exit-rule distances to uncover hidden strategy synchronization.
- **CAP-3 [JointMonteCarloEngine]:** Simulates 10,000 synthetic return trajectories via Synchronous Stationary Bootstrap (Politis & Romano 1994) across portfolio equity vectors, preserving cross-sectional correlation and volatility clustering.
- **CAP-4 [PortfolioRiskAssessment]:** Quantifies the Diversification Benefit metric $\Delta_{div} = 1 - \frac{MDD_{joint, 95\%}}{\sum w_i MDD_{i, 95\%}}$ and assigns a `DIVERSIFICATION_ILLUSION` warning verdict when $\Delta_{div} < 10\%$.
- **CAP-5 [ExposureConcentration]:** Calculates net directional bias ratio ($Bias_{net}$) and symbol notional allocation, issuing alerts when net exposure exceeds 70% in a single market direction.
- **CAP-6 [Bidirectional Cache Re-Use]:** Reuses single-bot analysis dossiers when assembling a portfolio, dropping evaluation latency from 15 seconds to under 50 milliseconds.
- **CAP-7 [Partial Portfolio Tolerance]:** Records member bots with private or restricted ledgers (OKX Error 60004) into a structured `failures` array, allowing the remaining bots to complete analysis without breaking report persistence.

---

## 3. Constraints (Derived from Memlog)

- **CON-1 [Member Bounds]:** Portfolios are strictly constrained between 2 and 8 bots (`PORTFOLIO_MIN_CODES = 2`, `PORTFOLIO_MAX_CODES = 8`). Inputs outside this boundary trigger immediate HTTP 400 validation errors prior to network fetching. Duplicate bot IDs are automatically merged into single positions.
- **CON-2 [Read-Only Isolation]:** The system operates strictly as an independent quantitative auditor with zero order-routing, zero withdrawal, and zero fund transfer capabilities.
- **CON-3 [Deterministic Grounding]:** All narrative assertions and AI inferences are bound to verified mathematical metrics within the sealed analysis dossier; free-form numerical hallucination is blocked by a 5-gate editorial firewall.

---

## 4. Non-Goals

- Autonomous automated trade execution or order rebalancing on user exchange accounts (delegated to human confirmation or external execution smart contracts).
- Portfolio optimization beyond 8 simultaneous bots (bounded to respect OKX API rate-limiting budgets and gateway read timeouts).
- Real-time millisecond high-frequency tick monitoring (evaluation is anchored to closed candle intervals and snapshot audit ledgers).

---

## 5. Success Signals & Verification Evidence

- **Automated Verification:** 76/76 automated unit and integration tests passed across `test_portfolio_pipeline.py` (32 tests) and `test_portfolio_web.py` (44 tests) in 465 seconds.
- **Static Code Hygiene:** `python -m ruff check Agent/backend/` passes with 0 errors and 0 warnings.
- **Frontend Bundle Integrity:** `npm run build` completes in 1.70 seconds with 0 warnings or syntax errors.
- **End-to-End Acceptance:** Fully compatible with OKX Dev Day 2026 5-Pillar Project Report specifications and FastMCP JSON-RPC protocol server.
