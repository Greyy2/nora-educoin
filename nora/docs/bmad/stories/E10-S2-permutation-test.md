# E10-S2: Permutation test cho chiến lược

- **Epic:** E10 Nghiên cứu chiến lược mới & phương pháp
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn kiểm hoán vị để ước lượng xác suất đạt kết quả tương đương nếu tín hiệu vô nghĩa, để bổ sung cho kiểm null trên random walk.

## Acceptance Criteria

1. **Given** một chiến lược và dữ liệu OOS, **When** hoán vị thời điểm tín hiệu (giữ phân phối độ dài vị thế) ≥ 1000 lần, **Then** trả p-value của Sharpe/lãi thực so với phân phối hoán vị.
2. **Given** random walk, **When** chạy trên nhiều chuỗi, **Then** tỉ lệ p < 0,05 không vượt 5% cộng dung sai thống kê (test).
3. **Given** cùng seed, **When** chạy hai lần, **Then** cùng p-value (tất định).
4. **Given** alpha SOL, **When** chạy, **Then** p-value ghi vào `evidence` kèm số hoán vị và seed.

## Tasks / Subtasks

- [ ] Thiết kế hoán vị không phá cấu trúc vị thế
- [ ] Cài đặt chạy song song trong ngân sách RAM
- [ ] Test random walk và edge cài sẵn
- [ ] Ghi vào registry

## Dev Notes

- Mở rộng `test/test_research_null.py` (hiện chỉ bộ quét limit-scalp). Phải chạy qua `run_limited`.
- Chi phí tính toán chưa đo.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
