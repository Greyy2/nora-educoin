# Story E15-S3: WFA học bảng regime ↔ chiến lược chỉ trên train

## Status
Done

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

## Tasks / Subtasks
- [x] Hoàn thành triển khai và kiểm thử

## Dev Notes
Kết quả thật (báo cáo 20261003_035715, top-3 mỗi chiến lược, 15m, 10 fold dev2): tắt — lãi kép OOS extreme −26,45%, MDD fold xấu nhất 17,3%, P(MDD≥30%) 81,9%; learn — −15,99%, 11,8%, 59,6%. Learn cải thiện rõ nhưng gate vẫn trượt (fold dương 30% < 60%). Bảng học đổi nhiều giữa các fold (quan hệ regime ↔ lãi không bền) → AC roadmap "sổ nhiều chiến lược qua WFA" CHƯA đạt; ghi nhận trung thực.

**Khắc phục 03/10.** Luật học chặt: ≥ 30 lệnh/ô và t-stat ≤ −2; WFA học trên cửa sổ mở rộng (đầu dev1 → hết train). Bảng học giờ ổn định (gần như mọi fold chặn reversion_long/short ở RANGE). WFA preset 9 chiến lược: tắt −27,3% / học −22,7% lãi kép OOS extreme (ruin 81% → 74%); gate vẫn trượt. Sổ 5 chiến lược dev1 dương cũng trượt (fold dương 30%). Nguyên nhân gốc: chiến lược đổi dấu từ dev1 sang dev2 (vd. keltner_trend_long +5.003$ → −724$) — regime không tạo được edge. Ghi chú: khớp SL "level" OOS dương (+5,5% / +8,1%) còn "extreme" âm → nhạy với giả định trượt giá khi cắt lỗ.

**Sửa engine + lưới thử 03/10.** Khớp SL "extreme" ở khung chạy > 1m từng lấy giá xấu nhất của cả nến 15m/1h — OOS extreme bị phạt sai theo khung
(trend_short dev2: 1m +21,8%, 15m +2,9%). Nay lấy nến 1m đầu tiên chạm mức (15m +17,5%, 1h +17,1%; commit d1e9b3d). Lưới WFA sau sửa: 1h tốt hơn 15m;
"học regime" không giúp ở 1h; bộ 5 chiến lược dương trên dev1 kém hơn cả 9 chiến lược (chọn theo dev1 không bền). Cấu hình qua gate WFA: 1h, 9 chiến lược preset,
rủi ro 0,15%/lệnh, test 60 ngày (fold dương 3/5, OOS +2,1%, stress MDD 44,6%) — mong manh, chọn sau ~20 lần thử; holdout một lần −4,4% / −7,25% → không đạt thực chất.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Story được triển khai và ghi nhận bằng chứng.
- **File List:** Tham chiếu mục Dev Notes.

## QA Results
- **Gate:** PASS
- Commit: `dc08366`.
- Test: `test/test_regime.py`, `test/test_portfolio_wfa.py::test_wfa_regime_learn_maps_come_from_train_only`.
- Số đo: `data/_cache/book_wfa/20261003_120508/report.json` (off), `data/_cache/book_wfa/20261003_120612/report.json` (learn).

## Change Log
| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo + chạy thật | dc08366 |
| 2026-10-03 | Luật học chặt + cửa sổ mở rộng; WFA lại với preset bền | a06efb9 |
| 2026-10-03 | Sửa khớp extreme theo nến 1m; lưới WFA khung/bộ/rủi ro; holdout một lần trượt | d1e9b3d |
