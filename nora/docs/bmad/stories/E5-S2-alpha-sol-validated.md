# Story E5-S2: Alpha trend_long_perp__SOL: kiểm lại và ghi nhận

## Status
Done

## Story
Là người nghiên cứu, tôi muốn kiểm lại alpha SOL bằng code hiện tại và cùng dữ liệu để chắc kết quả không đổi, để có một alpha đáng tin làm ứng viên testnet.

## Acceptance Criteria
1. **Given** cùng dữ liệu (`sha256_1m = 5c9f6ad4…cd89a`) và cùng seed, **When** chạy lại pipeline với code hiện tại, **Then** screen 3/60 cấu hình qua, tham số chọn giống hệt, WFA 14 fold với 9 fold OOS có lãi, OOS +35,97% (`evidence.screen`, `evidence.wfa` trong `registry.json`).
2. **Given** holdout 2026-02-23 đến 2026-09-30, **When** chạy cấu hình đã chọn, **Then** lãi +14,71%, MDD 12,23%, 35 lệnh (≥ 10) (`evidence.holdout`).
3. **Given** MC ngày trên chuỗi 434 ngày OOS (bootstrap khối 5 ngày, 2000 mô phỏng, seed 7, số bước = số ngày OOS), **When** đo, **Then** P(MDD ≥ 30%) = 0,80% ≤ 5% (`evidence.monte_carlo.risk_of_ruin_pct`).
4. **Given** 6 điều kiện `checks`, **When** đọc registry, **Then** cả 6 đều `true` (`wfa_gate, mc_ruin_le_5, holdout_profit, holdout_mdd_le_30, holdout_trades, leverage_le_10`).
5. **Given** hệ số vốn, **When** bootstrap ngân sách rủi ro, **Then** tối đa 0,5x (extreme) và 0,75x (level) (`portfolio_trend_long_perp__SOL__SOL.json`).

## Tasks / Subtasks
- [x] Chạy `optimize_alphas` cho SOL (`data/_cache/optimize/20261001_1440`)
- [x] Chạy `robustness_check` và `portfolio_sizing`
- [x] Làm mới `registry.json`, `testnet/`, `portfolio_*.json`
- [x] Ghi kết quả khớp bản gốc

## Dev Notes
- Tham số alpha: `leverage 1`, `order_size_pct 50`, `stop_loss_rate 4,0`, `timeout 4320`, `trailing_stop 5,0`, `trailing_activation_pct 1,5`, `adx_min 25`; AST: 1h `ema_50 > ema_200`, 1h `adx_14 > 25`, 15m `close > dch_20`. Vào MARKET, thoát bằng SL/trailing/timeout.
- Không gian 5184 tổ hợp, thử 60. `param_stability 0,8571`, `wfe 0,89`.
- **Cảnh báo đọc số:** `robustness.neighbors_profitable = 9/9` nhưng `other_assets_profitable = 1/7` (chỉ DOGE; BTC, ETH, BNB, XRP, ADA, AVAX đều không lãi ở cả dev2 và holdout). Edge hiện là edge của SOL riêng lẻ (R-3). Một lân cận (`trailing_stop=3,0`) chỉ cho +3,12% ở dev2, cho thấy độ nhạy với trailing.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `45f734e` (message: screen 3/60, tham số giống hệt, WFA 14 fold, 9 fold có lãi, OOS +35,97%, holdout +14,71% / MDD 12,23%, MC ngày ruin 0,80% so với MC lệnh 0,55%).
- Hiện vật: `data/alphas/registry.json`, `data/alphas/testnet/trend_long_perp__SOL.json`, `data/alphas/portfolio_trend_long_perp__SOL__SOL.json`, `..._SOL_DOGE.json`.
- Chưa làm: hiệu chỉnh đa kiểm định (R-1, E10-S1/S2), holdout mới (R-2, E10-S3).

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
