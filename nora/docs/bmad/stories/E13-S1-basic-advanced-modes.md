# E13-S1: Chế độ Cơ bản / Nâng cao cho Backtest, WFA, Monte Carlo

- **Epic:** E13 Hai chế độ chạy
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là người dùng UI, tôi muốn chế độ Cơ bản khoá tham số bằng preset đã kiểm chứng và chế độ Nâng cao sửa được từng tham số, để vừa chạy nhanh vừa thử nghiệm được mà không nhầm kết quả tuỳ chỉnh với gate chuẩn.

## Acceptance Criteria

1. **Given** mode=basic, **When** gửi tham số, **Then** tham số bị bỏ qua, dùng preset; rủi ro = mức nhỏ nhất của preset.
2. **Given** mode=advanced với gate khác chuẩn, **When** chạy MC/WFA, **Then** `custom_gates=true`, không promote/xuất bản được.
3. **Given** lỗi tham số, **When** gửi, **Then** 422 theo từng trường (`strategies[i].params.<khoá>`).

## Tasks

- [x] `core/params/modes.py`, `api/modes.py`
- [x] `GET /api/studio/strategies` (lược đồ + preset)
- [x] UI ModeSwitch, StrategyCard, PresetNote

## Dev Notes

Roadmap P0.3, P0.3b, P4.1; hợp đồng ui_contract §7.

## Evidence

- Commit: `197bfc0`, `1fc23aa`.
- Test: `test/test_run_modes.py`.
- Số đo: không áp dụng (tính năng).

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story ghi nhận P0.3/P4.1 | 197bfc0 |
