# E1-S1: Crawl nến Binance spot/perp và funding có checksum

- **Epic:** E1 Dữ liệu thị trường
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn nạp nến 1m spot và USDT-M perp cùng lịch sử funding từ nguồn chính thức có checksum, để backtest chạy trên dữ liệu thật và chứng minh được nguồn gốc.

## Acceptance Criteria

1. **Given** một tháng thiếu trên data.binance.vision, **When** chạy crawl, **Then** manifest có `crawl_ok=false` và `crawl_issues` ghi tháng thiếu (`test_binance_missing_month_marks_crawl_not_ok`).
2. **Given** file ZIP có checksum SHA-256 sai, **When** tải, **Then** bị từ chối (`test_fetch_vision_zip_rejects_bad_checksum`); checksum đúng thì dùng được và cache (`test_fetch_vision_zip_ok_and_cached`).
3. **Given** CSV kline có timestamp micro giây và volume theo coin, **When** parse, **Then** timestamp chuẩn hoá về ms và volume là quote USDT (`test_parse_kline_csv_normalizes_microseconds_and_uses_quote_volume`).
4. **Given** crawl bị ngắt giữa chừng, **When** chạy lại, **Then** tiếp tục từ checkpoint, giữ `filled_ratio` (`test_crawler_resume_preserves_filled_ratio`) và xoá checkpoint khi thành công (`test_crawler_removes_checkpoint_after_success`).
5. **Given** `--market um`, **When** crawl, **Then** dữ liệu ghi vào `<SYM>/perp/` kèm `funding.pkl` (kiểm bằng manifest `funding.rows` > 0 trên dữ liệu thật).

## Tasks / Subtasks

- [x] Tải ZIP tháng/ngày từ data.binance.vision, kiểm SHA-256
- [x] Bổ sung phần mới nhất qua REST
- [x] Hỗ trợ `--market spot|um` và funding
- [x] Checkpoint/resume, ghi manifest
- [x] Test crawler bằng dữ liệu giả (không gọi mạng)

## Dev Notes

- Code: `backend/core/data/crawler/crawl_binance_klines.py` (CLI: `python -m backend.core.data.crawler.crawl_binance_klines --symbols BTC,ETH --years 3 --output-dir data_staging`; perp thêm `--market um`).
- Tài sản: 8 (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX), mặc định 3 năm. Crawler ghi vào `data_staging/` rồi `promote_staging` mới chuyển vào `data/` (E1-S5).
- Các crawler GeckoTerminal (`crawl_geckoterminal_*`, `okx_dex_candle_crawler`) thuộc E1-S6.

## Evidence

- Commit: `c5d700b` (commit gộp: đưa phần pipeline chưa được git theo dõi vào repo; ngày commit không phản ánh ngày viết code).
- Tests: `test/test_round4_venue_and_fills.py` (checksum, parse CSV, tháng thiếu, resume), `test/test_crawler_and_gate.py` (crawl lỗi → `crawl_ok=false`).
- Đo trên dữ liệu thật (`data/cex/SOL/perp/manifest.json`): 1.577.881 nến 1m, 1095,75 ngày (2023-09-30 đến 2026-09-30), 36 file tháng + 29 file ngày + 1029 dòng REST, `checksums_verified=true`, `crawl_issues=[]`, funding 3288 dòng.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
