# Mô hình dữ liệu & Vòng đời Cache (Data Models & Cache Lifecycle)

Tài liệu đặc tả kiến trúc lưu trữ dữ liệu thị trường, mô hình kết quả và quy tắc quản lý vòng đời bộ đệm trong hệ thống Nora.

---

## 1. Cấu trúc cây dữ liệu (`nora/data/`)

Toàn bộ dữ liệu được tổ chức dưới thư mục gốc `nora/data/` (được cấu hình qua `crawl/store.py`):

```
data/
├── market/                           # Dữ liệu thị trường CEX & DEX đã kiểm định
│   ├── okx/                          # Sàn triển khai chính (OKX)
│   │   ├── cex/<SYM>/                # Giao dịch Spot: {1m, 5m, 15m, 1h, 4h, 24h}.pkl, manifest.json
│   │   │   └── perp/                 # Hợp đồng Perpetual: {1m..24h}.pkl, funding.pkl, manifest.json
│   │   └── dex/<chain>/<pool>/       # Giao dịch DEX: {1m..24h}.pkl, ticks.parquet, manifest.json
│   └── binance/                      # Sàn tham chiếu phụ (Binance)
│       └── cex/<SYM>/...
├── alpha/                            # Kho lưu trữ chiến lược định lượng
│   ├── strategies/                   # Định nghĩa chiến lược hệ thống (*.py)
│   ├── user/<id>.json                # Chiến lược người dùng lưu vĩnh viễn (code + hash + metrics)
│   ├── education/samples.json        # 50 mẫu chiến lược giáo trình
│   ├── presets.json                  # Bộ tham số tối ưu sẵn cho chế độ Cơ bản
│   ├── registry.json                 # Danh mục alpha đã được phê duyệt qua phễu
│   └── book.json                     # Cấu hình sổ chiến lược danh mục xuất bản
├── backtest/<job_id>/                # Kết quả backtest lưu trữ lâu dài (result.json, params.json)
├── wfa/<job_id>/                     # Kết quả phân tích Walk-Forward Analysis
├── carlo/<job_id>/                   # Kết quả phân tích rủi ro Monte Carlo
├── live/<venue_mode>/                # Trạng thái bot live (state.json, events.jsonl)
└── cache/                            # BỘ ĐỆM TẠM THỜI (chỉ 2 thư mục)
    ├── process/<job_id>/             # Dữ liệu tạm thời khi tiến trình đang chạy
    └── shared/                       # Bộ nhớ chia sẻ mmap (chỉ báo tính trước)
```

---

## 2. Chuẩn hoá dữ liệu nến (.pkl) & Metadata

Mỗi file nến là một pandas DataFrame tuần tự thời gian lưu dưới dạng `.pkl`:
- Cột bắt buộc: `open`, `high`, `low`, `close`, `volume`.
- Index: `pd.DatetimeIndex` dạng UTC timestamp, sắp xếp tăng dần và không có bản ghi trùng lặp.
- Metadata được đính kèm trực tiếp trong thuộc tính `df.attrs`:
  ```python
  df.attrs = {
      "exchange": "okx",
      "symbol": "BTC",
      "timeframe": "1m",
      "market_type": "perp",
      "sha256": "...",
      "rows": 1576800,
      "start": "2022-01-01T00:00:00Z",
      "end": "2025-01-01T00:00:00Z"
  }
  ```
- File `manifest.json`: Chứa báo cáo xác thực của Quality Gate (`APPROVED` / `WARNING` / `BLOCKED`), độ phủ dữ liệu, tỷ lệ nến thiếu và băm `sha256_1m`.

---

## 3. Vòng đời Cache (Cache Lifecycle)

1. **Khi tiến trình bắt đầu**:
   - Mọi file tạm, checkpoint, log RAM được tạo trong `data/cache/process/<job_id>/`.
2. **Khi tiến trình hoàn tất thành công**:
   - Toàn bộ kết quả `result.json` và tham số `params.json` được chuyển nguyên tử sang thư mục lưu trữ lâu dài (`data/backtest/<job_id>/` hoặc `data/wfa/`, `data/carlo/`).
   - Thư mục `data/cache/process/<job_id>/` được xoá ngay lập tức.
3. **Khi tiến trình gặp lỗi hoặc bị huỷ**:
   - Được dọn dẹp ở lượt quét kế tiếp của tiến trình dọn dẹp nền hoặc khi API khởi động lại.
4. **Quy tắc cho lượt chạy tạm thời (Custom Backtest & Education)**:
   - Các lượt chạy thử nghiệm trên giao diện được giữ tại `data/cache/process/<job_id>/` tối đa 24 giờ để người dùng xem kết quả.
   - Khi người dùng bấm nút **Lưu (Save)**: Hệ thống xác thực `program_hash`, ghi `data/alpha/user/<id>.json` và giải phóng thư mục cache.
   - Sau 24 giờ không được lưu, tác vụ dọn dẹp tự động xoá bỏ thư mục cache này.
