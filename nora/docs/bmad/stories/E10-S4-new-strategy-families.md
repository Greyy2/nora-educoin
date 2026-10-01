# E10-S4: Nghiên cứu họ chiến lược mới để có sổ qua holdout

- **Epic:** E10 Nghiên cứu chiến lược mới & phương pháp
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn thử các họ chiến lược mới qua đúng pipeline hiện có, để tìm được sổ đạt holdout hoặc ghi nhận trung thực rằng không có.

## Acceptance Criteria

1. **Given** một họ chiến lược mới, **When** thêm vào `CANDIDATES`, **Then** qua phép kiểm tín hiệu (E2-S3) và kiểm null (E4-S6) trước khi chạy `build_strategy_book`.
2. **Given** sổ mới, **When** chạy A-D và WFA danh mục, **Then** kết luận `READY_FOR_TESTNET` chỉ khi qua đủ gate hiện có; không nới gate.
3. **Given** không sổ nào đạt, **When** kết thúc, **Then** ghi báo cáo âm tính (họ đã thử, số cấu hình, lý do loại) vào `docs/alpha_pipeline.md`.
4. **Given** số lần thử tăng, **When** báo cáo, **Then** kèm DSR/permutation p-value nếu E10-S1/S2 đã có.

## Tasks / Subtasks

- [ ] Liệt kê họ chiến lược (ví dụ momentum cắt ngang tài sản, mean-reversion có điều kiện regime; do người nghiên cứu chọn)
- [ ] Chạy kiểm tín hiệu và null
- [ ] Chạy sổ và WFA danh mục
- [ ] Ghi kết quả (dương hoặc âm)

## Dev Notes

- R-4. Đã thử và thất bại: maker scalp, trend chung hai chiều cho 8 tài sản, funding carry (xem E4-S6). Sổ `breakout_4h_*` trượt holdout (E5-S5).
- Mọi lượt chạy phải qua `run_limited` và tôn trọng ngân sách 12 GB.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
