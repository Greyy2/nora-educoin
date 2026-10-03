# E14-S2: Chạy phễu thật 9 chiến lược có regime, thống kê từng tầng

- **Epic:** E14 Phễu kiểm duyệt
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là nhà nghiên cứu, tôi muốn chạy phễu end-to-end trên dữ liệu thật với 9 chiến lược và biến thể regime, để có số liệu từng tầng và biết có alpha nào đủ điều kiện testnet không.

## Acceptance Criteria

1. **Given** 9 chiến lược × 2.000 cấu hình (không gian schema) × regime both ở khung 15m, **When** chạy, **Then** chạy hết S0 → FINAL, không lỗi, không OOM.
2. **Given** kết quả, **When** xem thống kê tầng, **Then** có số lượng, lý do loại và danh sách lệnh từng tầng (ví dụ số liệu kiểu 100k → 1k → 10).
3. **Given** không alpha nào đạt FINAL, **When** kết luận, **Then** ghi trung thực lý do, không nới gate.

## Tasks

- [x] Lượt `fr-20261003-4ab03b` (job `20261003_120902_bc5bca`)
- [x] Kiểm nhánh lỗi thật: 422 theo trường, promote 400/409, tính lại lệnh, POST /runs nhỏ (`fr-20261003-971bd4`)

## Dev Notes

Kết quả (16,4 phút, RAM worker ≤ 390 MB): S0 36.000 (1.520 tham số không hợp lệ) → S1 34.480 → 12.881 qua → S2 **1** qua (PBO > 0,5 gắn cờ cả trend_long, momentum_long, keltner_trend_long, breakout_4h_long, reversion_long: 10.365 alpha; DSR < 0,95: 2.515) → S3 0 qua (alpha reversion_short learn duy nhất: 8/10 fold dương nhưng lãi kép OOS −1,02%) → FINAL **0**. Biến thể learn qua S1 nhiều hơn off (lọc trong mẫu) nhưng bị DSR/PBO phạt đúng như thiết kế. Không có alpha mới cho testnet.

**Khắc phục 03/10 (chiều).** (1) Cổng S3 mới không phụ thuộc độ lệch (574e6a6): t-stat lãi theo fold ≥ 1, bỏ fold tốt nhất ≥ −2%, fold 0 lệnh trung tính
— cổng cũ "≥ 60% fold lãi" loại 124/145 alpha có lãi OOS. (2) DSR dùng N hiệu dụng (80bbc58): N ~4000 → 184–577/chiến lược.
Lượt 1h `fr-20261003-c25fcd` (engine đã sửa khớp extreme): 36.000 → S1 10.596 → **S2 0** (DSR 5.469, PBO 5.127; DSR cao nhất 0,52 với N thô, 0,87 với N hiệu dụng).
Chẩn đoán bỏ qua S2 (270 alpha qua S1): 48% có lãi OOS; cổng S3 mới qua 19 (7%); holdout một lần của 19 alpha này: 10/19 lãi, TB **+2,0%**
(30 alpha ngẫu nhiên qua S1: TB −2,1%) — nhóm LONG (breakout_4h_long, trend_long, momentum_long) tốt nhất, nhóm SHORT âm. Edge yếu, chưa đủ ý nghĩa thống kê theo DSR.

## Evidence

- Commit: `dc08366`.
- Test: `test/test_funnel.py`.
- Số đo: `data/_cache/funnel/fr-20261003-4ab03b/results.sqlite`, `run.json`.

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Chạy thật + ghi nhận | dc08366 |
| 2026-10-03 | Cổng S3 mới + N hiệu dụng; lượt 1h; chẩn đoán holdout | 574e6a6, 80bbc58 |
