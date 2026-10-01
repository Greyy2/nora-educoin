# E10-S3: Chính sách dùng lại holdout và holdout tiến tới (forward)

- **Epic:** E10 Nghiên cứu chiến lược mới & phương pháp
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn mỗi lần chạm holdout được ghi nhận và có holdout mới từ dữ liệu tích luỹ thêm, để ước lượng ngoài mẫu không bị lạc quan vì dùng holdout nhiều lần.

## Acceptance Criteria

1. **Given** mỗi lần `optimize_alphas`/`build_strategy_book` chấm holdout, **When** xong, **Then** ghi một dòng vào sổ chạm holdout (thời điểm, cửa sổ, chiến lược, kết quả) append-only.
2. **Given** sổ chạm holdout, **When** một chiến lược đã chạm holdout cùng cửa sổ, **Then** CLI cảnh báo và yêu cầu cờ xác nhận rõ ràng để chấm lại.
3. **Given** dữ liệu mới sau ngày chốt (đề xuất 2026-10-01), **When** có đủ độ dài theo chính sách, **Then** pipeline chấm một holdout tiến tới riêng và báo cáo tách khỏi holdout cũ.
4. **Given** alpha SOL, **When** holdout tiến tới chạy, **Then** kết quả ghi vào `evidence` (không thay `holdout` cũ).

## Tasks / Subtasks

- [ ] Định dạng sổ chạm holdout (`data/alphas/`)
- [ ] Gắn vào hai CLI
- [ ] Định nghĩa độ dài holdout tiến tới (Q-1)
- [ ] Báo cáo và UI

## Dev Notes

- R-2, Q-1. Hiện: giai đoạn D của sổ đã chấm ít nhất 2 lần; holdout SOL dùng lại khi tái kiểm (`45f734e`).
- Cần chủ sở hữu duyệt chính sách (độ dài, ngưỡng) trước khi coi là cổng.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
