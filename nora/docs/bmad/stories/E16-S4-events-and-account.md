# E16-S4 — Kế toán vị thế theo sự kiện (P6.3)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn kế toán vị thế và vốn (`Account`, `PositionBook`) được điều khiển qua các sự kiện lệnh (`Fill`, `OrderPlaced`, `OrderCancelled`, `FundingApplied`), thay thế cho `CapitalLedger` nội tuyến, để mô phỏng và bot live ghi nhận vốn giống nhau.

## Acceptance Criteria

1. Given chuỗi lệnh thực hiện, When phát lại qua `Account` và `PositionBook`, Then equity, reserved margin, peak vốn và PnL khớp từng bit với `CapitalLedger`.
2. Given `PositionTracker`, When ghi nhận lệnh và funding, Then uỷ quyền phần kế toán cho `PositionBook`.

## Evidence

- Commit: `bf0906f` (P6.3 events.py, account.py).
- Kiểm chứng: Replay sự kiện bit-for-bit trên 14 seed × 4 slot.
