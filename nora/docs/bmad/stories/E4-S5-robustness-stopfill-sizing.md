# E4-S5: Kiểm độ bền, SL khớp bi quan và hệ số vốn theo ngân sách rủi ro

- **Epic:** E4 Kiểm chứng WFA / Monte Carlo / holdout
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn biết alpha có nằm trên đỉnh nhọn tham số không, kết quả thế nào khi SL khớp bi quan và mức vốn nào còn trong ngân sách rủi ro, để chọn cấu hình testnet an toàn.

## Acceptance Criteria

1. **Given** alpha ứng viên, **When** đổi từng tham số sang mức kề bên, **Then** báo từng lân cận có lãi ở cả dev2 và holdout hay không (`robustness.neighbors[*].profitable_both` trong `registry.json`).
2. **Given** cùng tham số, **When** chạy với `stop_fill="level"` và `"extreme"`, **Then** báo cả hai, `level` là cận trên và `extreme` là cận dưới.
3. **Given** lợi suất ngày OOS, **When** bootstrap theo hệ số vốn, **Then** tìm hệ số lớn nhất sao cho P(MDD ≥ 30%) ≤ 5% (`portfolio_sizing`).

## Tasks / Subtasks

- [x] `backend/optimize/robustness_check.py` (lân cận, chuyển tài sản)
- [x] `backend/optimize/portfolio_sizing.py` (hệ số vốn, hai chế độ SL)
- [x] Gắn `robustness` vào registry
- [x] Tài liệu `alpha_pipeline.md` §3, §6

## Dev Notes

- Chạy: `ops/run_limited.sh -- -m backend.optimize.robustness_check data/_cache/optimize/<thời điểm>/results.json trend_long_perp SOL`.
- Kết quả `portfolio_*.json` nằm ở `data/alphas/` (được commit).

## Evidence

- Commits: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code), `45f734e` (làm mới robustness và sizing cho SOL).
- SOL `trend_long_perp__SOL`: WFA-test level +36,4% / extreme +28,3%; holdout level +14,7% / extreme +12,3% (`docs/alpha_pipeline.md` §6).
- Hệ số vốn tối đa trong ngân sách: 0,75x (level), 0,5x (extreme) (`data/alphas/portfolio_trend_long_perp__SOL__SOL.json`: `max_scale_within_budget`). Ở level: 0,75x cho P(MDD ≥ 30%) = 4,5%, 1,0x cho 16,1%.
- Gộp SOL+DOGE kém hơn SOL một mình (`docs/alpha_pipeline.md` §7).
- Robustness SOL (`registry.json`): `neighbors_profitable = 9/9`, `other_assets_profitable = 1/7` (chỉ DOGE lãi ở cả dev2 và holdout).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
