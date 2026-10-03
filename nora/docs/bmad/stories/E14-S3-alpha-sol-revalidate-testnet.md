# E14-S3: Kiểm lại alpha SOL bằng engine hiện hành; registry + testnet đúng trạng thái

- **Epic:** E14 Phễu kiểm duyệt
- **Trạng thái:** done
- **Cập nhật:** 2026-10-03

## Story

Là người vận hành testnet, tôi muốn alpha trong kho được kiểm lại bằng engine hiện hành theo cổng phễu, để testnet chỉ chạy alpha còn hợp lệ.

## Acceptance Criteria

1. **Given** alpha trong registry, **When** chạy job `alpha_revalidate`, **Then** chạy lại đúng cây tín hiệu + tham số đã lưu: WFA dev2 (S3) → hệ số s qua MC có trend thẳng đứng (S5) → holdout ở s (S6).
2. **Given** alpha trượt, **When** apply=true, **Then** registry `status=retired` + bằng chứng, cấu hình testnet chuyển sang `testnet/_retired/`, feed live bỏ qua alpha.
3. **Given** sổ `book.json` HOLDOUT_FAILED, **When** xuất testnet, **Then** không có `testnet/book.json` (lý do ghi ở sổ).

## Tasks

- [x] `backend/optimize/revalidate.py`, route `POST /api/studio/alphas/{id}/revalidate`
- [x] feeds bỏ qua alpha retired

## Dev Notes

`trend_long_perp__SOL` (khung 15m, dev2 2024-12-24 → 2026-02-27): 10 fold, lãi kép OOS +14,04%, MDD fold xấu nhất 6,97%, nhưng fold dương 50% < 60% → **retired** (S3.positive_ratio). Bằng chứng cũ của alpha đến từ engine trước P1 và đường đơn tài sản đã xoá nên không tái lập được. Sổ hiện hành `HOLDOUT_FAILED` → không có cấu hình testnet nào đang hoạt động.

## Evidence

- Commit: `dc08366`.
- Test: `test/test_revalidate.py`.
- Số đo: `data/alphas/registry.json` (khoá `revalidation`), job `20261003_120901_e9b209`.

## Change Log

| Ngày | Thay đổi | Commit |
|---|---|---|
| 2026-10-03 | Tạo + chạy thật | dc08366 |
