# E15-S3: WFA học bảng regime ↔ chiến lược chỉ trên train

- **Epic:** E15 Regime
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là nhà nghiên cứu, tôi muốn mỗi fold WFA tự học regime nào chiến lược lỗ (chỉ từ train) rồi chặn ở test, để dùng regime mà không nhìn tương lai.

## Acceptance Criteria

1. **Given** `regime=learn`, **When** chạy WFA, **Then** mỗi fold chạy thêm job quan sát trên ĐÚNG cửa sổ train (kill tắt) và bảng học được áp vào OOS của fold đó (`test_wfa_regime_learn_maps_come_from_train_only`).
2. **Given** chế độ quan sát (`OBSERVE`), **When** chạy, **Then** lệnh trùng bit với tắt regime (`test_observe_regime_keeps_trades_identical`).
3. **Given** luật học, **When** regime có ≥ 5 lệnh và tổng lãi ≤ 0, **Then** bị chặn; ít lệnh hơn thì giữ (`test_learn_map_blocks_only_losing_regimes_with_enough_trades`).
4. **Given** chọn cấu hình IS, **When** bật learn, **Then** lựa chọn không đổi so với tắt.

## Tasks

- [x] `core/regime/learn.py` (OBSERVE, by_regime, learn_map)
- [x] `BacktestJob.regime`, `materialize(regime=dict)`
- [x] `wfa/walk_forward.py` regime=learn, khoá resume có regime
- [x] API/UI WFA trường `regime`

## Dev Notes

Kết quả thật (báo cáo 20261003_035715, top-3 mỗi chiến lược, 15m, 10 fold dev2): tắt — lãi kép OOS extreme −26,45%, MDD fold xấu nhất 17,3%, P(MDD≥30%) 81,9%; learn — −15,99%, 11,8%, 59,6%. Learn cải thiện rõ nhưng gate vẫn trượt (fold dương 30% < 60%). Bảng học đổi nhiều giữa các fold (quan hệ regime ↔ lãi không bền) → AC roadmap "sổ nhiều chiến lược qua WFA" CHƯA đạt; ghi nhận trung thực.

## Evidence

- Commit: `dc08366`.
- Test: `test/test_regime.py`, `test/test_portfolio_wfa.py::test_wfa_regime_learn_maps_come_from_train_only`.
- Số đo: `data/_cache/book_wfa/20261003_120508/report.json` (off), `data/_cache/book_wfa/20261003_120612/report.json` (learn).

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo + chạy thật | dc08366 |
