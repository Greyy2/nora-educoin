# Báo cáo Đánh giá Chuỗi Alpha (GATE 6 - Alpha Rerun Pipeline Report)

**Status:** UNVERIFIED — historical summary is not reproducible from per-variant artifacts  
**Date:** 2026-10-25  
**Total Finite Manifest Universe:** 72 variants (Track 1: 60 swing, Track 2: 12 scalp)  
**Catalog Inputs Digest:** BTC: `cd026438b6a668b1`, ETH: `8d62dc2d69c4d5cf`  
**Execution Target:** Nautilus Trader native matching engine (`execution_target="nautilus"`)  

---

## 1. Phương pháp Đánh giá Khắt khe (Methodology)

Tuân thủ nguyên tắc không overfit và không thiên vị:
1. **Phân chia Dữ liệu:**
   - Dữ liệu lịch sử 1,097 ngày được chia thành: Train/Dev (Cửa sổ tối ưu hoá) và Untouched Final Holdout (Cửa sổ nghiệm thu cuối cùng không chạm vào).
   - Rolling Walk-Forward Analysis (WFA): 120 ngày Train, 30 ngày Test OOS liền kề, tối thiểu 5 Folds.
2. **Các Bộ lọc Rào chắn Bắt buộc (Predeclared Gates):**
   - **Chi phí Stress:** Bắt buộc có lãi sau khi nhân đôi chi phí (Swing x2) và nhân đôi/gấp ba (Scalp x2/x3).
   - **Deflated Sharpe Ratio (DSR):** $\ge 0.95$ trên không gian tìm kiếm 72 biến thể để loại bỏ may mắn ngẫu nhiên.
   - **Loại bỏ tháng tốt nhất (Best-Month Removal):** Lãi OOS sau khi loại bỏ tháng có lợi nhuận cao nhất vẫn phải $\ge -2.0\%$.
   - **Kiểm định Monte Carlo Block Bootstrap:** $\ge 10,000$ đường mô phỏng; $P(\text{MDD} \ge 30\%) \le 5\%$.
   - **T-stat lợi nhuận OOS:** $\ge 1.0$.

---

## 2. Trạng thái bằng chứng hiện có

The report package currently contains the finite inventory and this group-level summary, but no raw per-variant run artifacts, fold-level metrics, gate receipts, Monte Carlo paths/seeds, or reproducible DSR inputs were located during the current review. Therefore, the historical claim that all 72 variants were evaluated and that `N = 0` is **not independently verified** and must not be used as a current alpha ranking, a reason to reject any individual candidate, or evidence for bot eligibility.

The methodology and thresholds in Section 1 are the recorded research plan; this audit did not verify that the split, stress costs, DSR, Monte Carlo, or holdout procedure was actually executed as described.

No formal 72-variant rerun was performed for this report update. It remains blocked until the Backtest–Live execution producer and independent fixtures, causal data/funding/spec inputs, cost calibration or explicitly approved conservative proxy, and durable risk policy pass their gates. Existing candidate records remain stale/quarantined; do not start bots or send orders.

The group-level rejection explanations below are retained only as **unverified historical hypotheses**. They are not per-variant measurements.

## 3. Historical group-level summary (unverified)

| Historical group claim (not revalidated) | Số biến thể | Kết quả lịch sử được ghi (chưa xác minh) | Lý do lịch sử được nêu (chưa có per-variant evidence) |
|---|---|---|---|
| **KEMA Swing (`kema_long`, `kema_short`)** | 20 variants (5m, 15m, 1h, 4h, 24h trên BTC & ETH) | Historical summary: 0; unverified | Historical claims: x2 cost rejection on 5m/15m; low OOS sample count or DSR on longer frames. No variant/fold artifacts found. |
| **Sideway Mean Reversion (`sideway_long`, `sideway_short`)** | 20 variants (5m, 15m, 1h, 4h, 24h trên BTC & ETH) | Historical summary: 0; unverified | Historical claim: Monte Carlo/MDD rejection in trending regimes. No paths, seeds, or per-variant metrics found. |
| **DCA Grid (`dca_long`, `dca_short`)** | 20 variants (5m, 15m, 1h, 4h, 24h trên BTC & ETH) | Historical summary: 0; unverified | Historical claims: exposure and hard-stop incompatibility. No run configs or gate receipts found. |
| **Scalp Track 1m (KEMA, Sideway, DCA)** | 12 variants (1m trên BTC & ETH) | Historical summary: 0; unverified | Historical claim: x2/x3 cost rejection. No per-variant cost/PnL artifacts found. |

### Per-candidate status from the current evidence audit

`NOT RUN / UNKNOWN` means no verified metric is available; it does not mean zero trades, zero return, or a failed strategy.

| Candidate | Variants in manifest | Current verified OOS net return | Trades / expectancy | Max drawdown | Cost stress | DSR / Monte Carlo | Current decision |
|---|---:|---|---|---|---|---|---|
| `kema_long` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| `kema_short` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| `sideway_long` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| `sideway_short` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| `dca_long` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| `dca_short` | 12 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | BLOCKED |
| **Total** | **72** | **NOT EVALUATED** | **NOT EVALUATED** | **NOT EVALUATED** | **NOT EVALUATED** | **NOT EVALUATED** | **0 eligible for promotion pending evidence** |

---

## 4. Required per-variant deliverable for the next formal run

Create exactly one immutable result row for each of the 72 manifest variants, keyed by `variant_id`, strategy/candidate, side, symbol, timeframe, and manifest hash. Store source/code/config/data/instrument-spec/cost-model/engine hashes; run timestamp and command; date windows and fold definitions; warm-up and bar counts; signal/trade counts; gross and net PnL/return; fees, spread/slippage, funding and liquidation separately (unknown values must remain null and block gates); daily equity returns, expectancy, drawdown, Sharpe/t-stat with sample counts; stress-case metrics; DSR inputs/result; Monte Carlo parameters/seed and ruin probability; holdout status; each gate's PASS/FAIL/BLOCKED plus numeric evidence and rejection reason. Preserve run logs and raw trade/fill/equity records so an independent reviewer can recompute aggregates.

Do not open the final holdout during development or parameter changes. The formal run must preserve the finite 72-row universe and report all variants, including failures and blocked rows; never omit losing, errored, or insufficient-sample candidates.

Implemented schema tooling:
- `alpha_rerun_schema.py` expands the approved manifest deterministically, writes fail-closed `BLOCKED_NOT_EVALUATED` rows, and validates manifest hash, exact variant set, duplicate IDs, missing evidence and fabricated metrics.
- `alpha_variant_status.json` is the current 72-row status artifact. All metric fields are `null`; this explicitly means not evaluated, not zero.
- Validate with `/home/vmc03/.venvs/nora312/bin/python nora/check/alpha_rerun_schema.py --validate nora/check/alpha_variant_status.json`; schema regression with `/home/vmc03/.venvs/nora312/bin/pytest -q nora/check/test_alpha_rerun_schema.py`.

## 5. Formal GATE 6 conclusion

- **Historically claimed qualifying candidates:** **$N = 0$; unverified.**
- **Current verified qualifying candidates:** **not evaluated / unknown**. This is not equivalent to zero measured winners.
- **Nguyên tắc tuân thủ:**
  > *"Report zero only after a reproducible run proves zero pass. Until then report NOT EVALUATED, retain all variants, and do not promote."*
- The 72-variant manifest is inventory only; per-variant evaluation and immutable gate receipts remain outstanding.
