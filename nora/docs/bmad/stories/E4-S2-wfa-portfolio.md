# E4-S2: Walk-forward danh mục với IS chọn lại và OOS chung vốn

- **Epic:** E4 Kiểm chứng WFA / Monte Carlo / holdout
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn kiểm cả sổ chiến lược bằng WFA trượt với một sổ vốn, để phản ánh cạnh tranh vốn và giới hạn danh mục ngoài mẫu.

## Acceptance Criteria

1. **Given** các fold, **When** kiểm cửa sổ, **Then** OOS không chồng và lợi suất ngày OOS chỉ lấy từ cửa sổ test (`test_folds_do_not_overlap_and_oos_daily_only_from_test_windows`).
2. **Given** việc chọn cấu hình ở IS, **When** thay đổi dữ liệu OOS, **Then** lựa chọn không đổi (`test_is_selection_never_sees_oos_data`).
3. **Given** điểm IS = lãi/max(MDD,1) bằng nhau, **When** chọn, **Then** cấu hình đứng trước thắng và cấu hình dưới `min_is_trades` bị loại (`test_select_best_ties_go_to_first_and_min_trades`).
4. **Given** kết quả tạo tay, **When** đánh giá, **Then** gate có đúng 6 check (`folds`, `avg_is_return`, `positive_folds`, `worst_fold_mdd`, `compounded_oos`, `mc_ruin`) (`test_gate_checks_on_crafted_result`).
5. **Given** cùng đầu vào, **When** chạy hai lần, **Then** cùng kết quả (`test_wfa_is_deterministic`); chạy đầu-cuối trên thị trường tổng hợp (`test_validate_book_main_end_to_end`).
6. **Given** báo cáo cũ có chuỗi `"False"`, **When** đọc ứng viên, **Then** không coi là chiến lược đạt (`test_candidates_from_report_old_report_with_string_bools`).

## Tasks / Subtasks

- [x] `run_portfolio_wfa`: hai pool (IS, OOS) trên dữ liệu mmap
- [x] `aggregate_folds`, `evaluate_gate`
- [x] CLI `validate_book` (`--report`, `--candidates`, `--strategies-json`)
- [x] Báo cáo `report.json` có `aggregate`/`mc` bí danh
- [x] Cấu hình do người dùng chọn (`strategies[{id, configs}]`)

## Dev Notes

- Code: `backend/wfa/portfolio_wfa.py`, `backend/cli/validate_book.py`, `backend/core/backtest/portfolio_metrics.py`. Đặc tả và hằng số gate: `architecture.md` §7.2.
- Cơ sở kết luận là SL "extreme"; "level" chỉ để so sánh.

## Evidence

- Commit: `e334716` (message: dữ liệu thật `trend_long + reversion_short`, dev2, 10 fold: gate trượt, OOS −49% level / −65% extreme, P(MDD ≥ 30%) 99,8%, 121 s, ~114 MB RAM riêng mỗi worker).
- Báo cáo thật `data/_cache/book_wfa/20261001_121903` (hai chiến lược `breakout_4h_*`, 10 fold): 6/6 check qua, MC ngày P(MDD ≥ 30%) = 3,62%; `20261001_151908` (6 fold): 6/6 qua, MC 0,0%; `20261001_153224` (10 fold): trượt `positive_folds`.
- Tests: `test/test_portfolio_wfa.py` (12). Job qua API: `data/_cache/api_jobs/20261001_153224_2af533` xong trong 53,5 s.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
