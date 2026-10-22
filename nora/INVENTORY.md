# Giai đoạn 0 — Inventory & Hiện trạng Hệ thống Nora

Thời điểm kiểm kê: 2026-10-22
Thư mục gốc: `/home/vmc03/norabt/nora`

## 1. Dịch vụ và tiến trình đang chạy
- `nora-api.service`: Đang chạy trên port `18010` (monolith legacy, Main PID: 2093144). Đang phục vụ API studio và duy trì trạng thái bot cũ.
- `nora-edu.service`: Đang chạy trên port `18020` (EDU API, Main PID: 396221).
- `nora-coin.service`: Đã cài đặt nhưng chưa start để tránh xung đột port 18010 với legacy monolith.

## 2. Trạng thái Bot & Vốn
- Bot ID: `bot_1792596143_bb83cd_paper` (chiến lược `proxima_decoupled`, status: `stopped`, sleeve: 2,000 USDT).
- Master Capital: Initial $10,000, unallocated $4,000, master equity ~$9,752.99.
- Dữ liệu bot lưu tại: `data/live/`

## 3. Dữ liệu và Kho nến
- Nguồn nến duy nhất (Single Source of Truth): `data/market/okx/catalog/` (ParquetDataCatalog chuẩn NautilusTrader cho 10 cặp perp).
- Chiến lược & Presets: `data/alpha/` (`registry.json`, `presets.json`, `user/`, `education/`).
- Người dùng: `data/users/users.json`.
- Kết quả kiểm định: `data/backtest/`, `data/wfa/`, `data/research/`.

## 4. Biến môi trường & Secrets
- `~/.config/nora/okx.env`: Chứa API key, secret, passphrase sàn OKX (chỉ COIN được dùng).
- `~/.config/nora/app.env`: Cấu hình ứng dụng và secret ký HMAC session.
- `~/.config/nora/llm.env`: API keys cho LLM alpha research.

## 5. Kế hoạch di chuyển & Rollback
- Nguyên tắc: COPY sang `nora/coin/` và `nora/edu/`, không xoá bỏ thư mục nguồn hiện hành.
- Sau khi kiểm thử độc lập, staging port mới cho COIN (port 18012) và EDU (port 18022) trước khi cutover domain.
- Rollback tức thì: Giữ nguyên `nora-api.service` và vhost cũ.
