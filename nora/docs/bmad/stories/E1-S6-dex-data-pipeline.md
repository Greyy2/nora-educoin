# E1-S6: Dữ liệu DEX (pool AMM) và chính sách tick

- **Epic:** E1 Dữ liệu thị trường
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn giữ dữ liệu DEX với quy tắc không bao giờ sinh tick giả, để các nghiên cứu vi cấu trúc cũ còn tái lập được dù DEX không phải trọng tâm.

## Acceptance Criteria

1. **Given** manifest không khai báo `ticks` với `synthetic: false`, **When** nghiên cứu cần tick, **Then** không dùng tick (`test_has_ticks_requires_manifest_declaration`).
2. **Given** tick thật chỉ phủ một đoạn ngắn, **When** dựng đường giá, **Then** vẫn dùng close 1m dài hơn (`test_short_real_ticks_do_not_replace_long_1m_path`).
3. **Given** tick tổng hợp, **When** nạp đường giá, **Then** bị bỏ qua (`test_load_price_path_ignores_synthetic_ticks`).
4. **Given** DEX spot, **When** cấu hình `market="perp"`, **Then** bị từ chối và phí theo phí pool thật (`test_dex_perp_rejected_and_venue_fees`, `test_dex_uses_verified_pool_fee`).

## Tasks / Subtasks

- [x] Crawl GeckoTerminal OHLCV 1m (tối đa 179 ngày), pool AERO và VVV
- [x] `crawl_dex_ticks.py` tích luỹ tick thật dần
- [x] Phí pool thật (0,30%) từ manifest `pool_fee_rate`
- [x] Nến điền không tạo lệnh (engine bỏ qua)

## Dev Notes

- Code: `backend/core/data/crawler/crawl_geckoterminal_*.py`, `crawl_dex_ticks.py`, `okx_dex_candle_crawler.py`.
- Giới hạn: API miễn phí chỉ trả khoảng 300 giao dịch của 24 giờ gần nhất, nên không có tick lịch sử; lịch sử 179 ngày.
- Tài sản DEX còn dữ liệu: `data/dex/AERO`, `data/dex/VVV`. Không dùng trong sổ chiến lược (vũ trụ chỉ gồm 8 perp CEX).

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_round3_completion.py`, `test/test_research_dc_enhancements.py`, `test/test_signals_strategies.py::test_dex_perp_rejected_and_venue_fees`, `test/test_optimization_plumbing.py::test_dex_uses_verified_pool_fee`.
- Phí pool 0,30% do manifest ghi (xác minh on-chain qua `PoolFactory.getFee`, theo `docs/data_layout.md`); chưa kiểm lại trong đợt này.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
