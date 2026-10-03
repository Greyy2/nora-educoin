# E13-S2: Preset ghi khung tối ưu, ưu tiên nguồn qua dev2

- **Epic:** E13 Hai chế độ chạy
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là người dùng chế độ Cơ bản, tôi muốn preset ghi rõ khung đã tối ưu và đã qua kiểm chứng dev2 hay chưa, để không chạy nhầm cấu hình khớp quá mức.

## Acceptance Criteria

1. **Given** sổ và lần dựng sổ, **When** dựng presets, **Then** nguồn qua dev2 thắng; cùng mức thì bằng chứng mới hơn thắng.
2. **Given** stage A không có cấu hình top-K qua dev2, **When** dựng, **Then** preset gắn nhãn "chưa kiểm chứng dev2" (`dev2_verified=false`).
3. **Given** khung chạy khác khung preset ở chế độ Cơ bản, **When** tạo job, **Then** API trả `timeframe_mismatch` và UI cảnh báo, không chặn.

## Tasks

- [x] `core/params/presets.py`
- [x] `api/modes.py`
- [x] UI `timeframeMismatch`, nhãn khung trên thẻ preset

## Dev Notes

Roadmap P0.3c. Kết quả: 5/7 preset stage A chưa qua dev2; sổ `HOLDOUT_FAILED`.

## Evidence

- Commit: `21d8adb`.
- Test: `test/test_run_modes.py::test_presets_new_verified_run_beats_old_book_unverified_does_not`, `test_presets_stage_a_prefers_dev2_pass_in_top_k`.
- Số đo: `data/alphas/presets.json`, roadmap mục Kết quả P0.3c.

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo story | 21d8adb |
