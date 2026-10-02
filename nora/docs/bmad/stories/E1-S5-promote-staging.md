# E1-S5: Chuyển dữ liệu từ staging sang data/ chỉ khi qua gate

- **Epic:** E1 Dữ liệu thị trường
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn dữ liệu mới crawl nằm ở vùng đệm cho tới khi qua gate, để dữ liệu hỏng không bao giờ chạm tới bộ dữ liệu đang dùng cho backtest.

## Acceptance Criteria

1. **Given** staging có tài sản `BLOCKED` hoặc `NEEDS_MORE_DATA`, **When** chạy `promote_staging --apply`, **Then** tài sản đó bị bỏ qua và lý do được in ra.
2. **Given** không có `--apply`, **When** chạy, **Then** chỉ in kế hoạch (dry-run) và không di chuyển file.
3. **Given** thư mục đích đã có, **When** promote, **Then** bản cũ được cất vào `data/_archive_invalid/legacy_<thời điểm>/` thay vì bị xoá.
4. **Given** manifest thiếu `venue` hợp lệ, **When** promote, **Then** bỏ qua (`[skip]`) và không đoán venue (`test_promote_script_places_assets_by_venue` kiểm đặt theo venue).

## Tasks / Subtasks

- [x] Dry-run mặc định, `--apply`
- [x] `--archive-legacy` cất thư mục không có manifest
- [x] Đặt tài sản theo `manifest.venue`

## Dev Notes

- Code: `backend/core/data/promote_staging.py`. `BLOCKING = (BLOCKED, NEEDS_MORE_DATA)`; trạng thái `WARNING` vẫn được promote.
- Chạy: `python -m backend.core.data.promote_staging [--apply] [--archive-legacy]` (script nhẹ, không cần `run_limited`).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code); chuyển sang `backend/cli/` ở `4e8dd61`.
- Test: `test/test_data_layout.py::test_promote_script_places_assets_by_venue`. Hai nhánh dry-run và lý do bỏ qua chưa có test riêng (chưa đo).

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
