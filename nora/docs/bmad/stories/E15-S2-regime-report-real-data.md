# E15-S2: Báo cáo độ chuẩn regime trên 8 tài sản thật

- **Epic:** E15 Regime
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là nhà nghiên cứu, tôi muốn đo nhãn regime causal so với diễn biến thật và lãi/lỗ từng chiến lược theo regime, để biết bảng regime ↔ chiến lược có đúng không trước khi dùng.

## Acceptance Criteria

1. **Given** dữ liệu thật 8 perp (2023-10 → 2026-09), **When** chạy job `regime_report` ở khung 15m, **Then** có tỷ trọng, lợi suất 24h tới theo nhãn, recall/độ trễ sự kiện thẳng đứng và backtest tắt/bật regime.
2. **Given** kết quả, **When** đối chiếu với bảng tĩnh `REGIME_MAP`, **Then** ghi nhận trung thực chiến lược nào lãi/lỗ ở regime nào (không nới, không chọn số đẹp).

## Tasks

- [x] Job `regime_report` nhận `timeframe` (mặc định 15m)
- [x] `classifier.series(..., base_frame)`
- [x] `by_regime` chuyển sang `core/regime/learn.py` (dùng chung)

## Dev Notes

Kết quả (job `20261003_114116_8f0064`, 7,5 s): RANGE 66% thời gian; nhãn xu hướng gần như không dự báo lợi suất 24h tới (TREND_UP +0,26%, TREND_DOWN +0,06%); sau CRASH giá hồi +2,5% (cầu chì cắt LONG là sai chiều; alarm continuation 0–46%). Recall sự kiện ±12%/24h: 67–94%, trễ trung vị ~20 h (nhãn cần roc_24 đã đi). Sổ preset tắt regime +29,6% / MDD 29,5%; bật bảng tĩnh −26,0% / MDD 30,1%. Bảng tĩnh không khớp dữ liệu (vd. momentum_long lãi ở RANGE nhưng chỉ được TREND_UP/SURGE) → AC P2.4 "chiến lược lãi trong regime của nó" KHÔNG đạt với bảng tĩnh; hướng xử lý = học trên train (E15-S3).

## Evidence

- Commit: `dc08366`.
- Test: `test/test_regime.py`.
- Số đo: `data/_cache/api_jobs/20261003_114116_8f0064/result.json`.

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Chạy dữ liệu thật, thêm timeframe | dc08366 |
