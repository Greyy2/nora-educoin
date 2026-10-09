# Story E21-S1: G1 - Quy ước khớp lệnh trên dữ liệu có gap (S12)

## Status
Done

## Story
Là quant researcher, tôi muốn đối chiếu quy ước khớp lệnh giữa Nora (next-bar open) và NautilusTrader (close-vs-next-open) trên dữ liệu thô (raw data có gap), để chứng minh sự khác biệt chỉ do quy ước khớp lệnh chứ không phải lỗi logic.

## Acceptance Criteria
1. Đối chiếu S12 (tương đương S9/S10) trên tập dữ liệu RAW có price gaps giữa các nến.
2. Nautilus được cấu hình hoặc mô phỏng lệnh tại next-open (đặt tại `on_bar` của nến 1m kế tiếp hoặc `ts_init` tại open nến kế).
3. Sai số khớp từng lệnh đạt chuẩn: giá rel < 1e-9, khối lượng rel < 1e-7, vốn < 1e-3.
4. Ghi nhận rõ bảng so sánh "close-fill vs next-open" trong báo cáo đối chiếu.

## Tasks / Subtasks
- [x] Thiết lập kịch bản S12 với RAW data có gaps (AC: 1)
- [x] Cài đặt mô phỏng next-open phía NautilusTrader (AC: 2)
- [x] Chạy compare và kiểm tra sai số lệnh (AC: 3)
- [x] Cập nhật báo cáo đối chiếu (AC: 4)

## Dev Notes
- Tham chiếu: `nora/docs/bmad/archive/p13_nautilus_gaps_plan.md` mục G1 (S12).
- Harness: `nora/test/scripts/nautilus_diff/`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Đã xây dựng hoàn tất harness S12 (s12_common.py, s12_export_data.py, s12_run_nora.py, s12_run_nautilus.py, s12_compare.py). Kết quả 120/120 trades (S12a 15/15, S12b 37/37, S12c 68/68) khớp tuyệt đối giữa Nora và NautilusTrader trên dữ liệu RAW thực tế.
- **File List:**
  - `test/scripts/nautilus_diff/s12_common.py`
  - `test/scripts/nautilus_diff/s12_export_data.py`
  - `test/scripts/nautilus_diff/s12_run_nora.py`
  - `test/scripts/nautilus_diff/s12_run_nautilus.py`
  - `test/scripts/nautilus_diff/s12_compare.py`
  - `test/scripts/nautilus_diff/s12_results.json`

## QA Results
- **Gate:** PASS
- **Commit:** `5e4c01b`
- **Tests:**
  - `python test/scripts/nautilus_diff/s12_compare.py all` PASS (120/120 trades khớp 100%)
  - `python test/scripts/nautilus_diff/check_baseline.py` PASS (353/353)

## Change Log
| Ngày | Thay đổi |
|---|---|
| 2026-10-09 | Tạo story từ kế hoạch P13, trạng thái `backlog`. |
| 2026-10-09 | Hoàn thành harness S12 đối chiếu G1, 100% test pass, chuyển `done`. |

