# E16-S2 — Risk engine độc lập (P6.1)

- **Epic:** E16 Kiến trúc thực thi thống nhất
- **Trạng thái:** done
- **Cập nhật:** 2026-10-06

**Story.** Là lập trình viên hệ thống, tôi muốn logic kiểm tra rủi ro danh mục và kill switch được cô lập thành các hàm thuần trong `backend/core/execute/risk.py` (`admit_entry`, `kill_check`) để mọi môi trường (kernel, sim, PaperBook, bot) dùng chung cùng một quy tắc rủi ro và điều kiện vốn.

## Acceptance Criteria

1. Given các giới hạn danh mục (max_positions, max_per_symbol, max_gross_exposure, max_open_risk_pct, dd_throttle), When gọi `admit_entry`, Then trả về kết quả cho phép/từ chối kèm khối lượng tối đa được phép mở.
2. Given sụt giảm vốn MTM từ đỉnh, When vượt quá `kill_switch_dd_pct`, Then `kill_check` trả về cờ kích hoạt dừng khẩn cấp.
3. Given `PaperBook`, When nạp nến mới, Then uỷ quyền cho `risk.py` thay vì giữ code rủi ro nội tuyến.

## Evidence

- Commit: `8b553b2` (P6.1 risk engine).
- Kiểm chứng: PaperBook = kernel trên 100 cấu hình ngẫu nhiên đủ 7 trần rủi ro.
