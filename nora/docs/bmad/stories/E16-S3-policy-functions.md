# E16-S3 — Hàm thuần chính sách vị thế (P6.2)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn các công thức tính toán mức giá (DCA, SL, TP, trailing, liquidation, gap fill, layer margin) được gom vào `backend/core/execute/policy.py` dưới dạng các hàm thuần, để PositionTracker và PositionManager dùng chung nguyên văn phép toán float.

## Acceptance Criteria

1. Given mức giá và cấu hình vị thế, When tính toán các mốc DCA/SL/TP/trailing/thanh lý, Then `policy.py` trả về kết quả giống hệt `PositionTracker`.
2. Given `PositionTracker`, When chạy các bước intrabar, Then uỷ quyền cho `policy.py` mà không làm thay đổi kết quả số.
3. Given các bài test golden và parity, When chạy lại, Then bảo toàn bit-identical 100%.

## Evidence

- Commit: `0aa01e1` (P6.2 policy.py).
- Kiểm chứng: Golden, parity, pack_trackers bit-identical.
