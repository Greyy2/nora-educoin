# Đặc tả giao diện lập trình ứng dụng (API Specification)

Hợp nhất các hợp đồng giao tiếp giữa FastAPI Backend (`:18010`) và Frontend React SPA (`:18011`).

---

## 1. Nguồn sự thật toàn cục: `/api/studio/meta`

Endpoint cung cấp toàn bộ metadata, tham số danh mục, danh sách tài sản khả dụng và phiên bản engine:
- **Phương thức**: `GET /api/studio/meta`
- **Cấu trúc trả về**:
  ```json
  {
    "engine_version": "...",
    "code_version": "...",
    "universes": {
      "xno": ["BTC@perp", "ETH@perp", "SOL@perp", "..."],
      "custom": [...]
    },
    "default_symbols": ["BTC@perp"],
    "date_bounds": {
      "start": "2022-01-01",
      "end": "2025-01-01"
    },
    "timeframes": ["1m", "5m", "15m", "1h", "4h", "24h"],
    "indicators_catalog": [...]
  }
  ```

---

## 2. Danh mục các nhóm Endpoint chính

### 2.1 Bảng điều khiển danh mục (`/api/studio/portfolio`)
- `GET /api/studio/portfolio/dashboard`: Trả về số liệu tổng quan vốn, PnL ngày/tháng/năm, Sharpe, Drawdown, đường vốn và phân bổ tài sản.
- `GET /api/studio/portfolio/trades`: Danh sách các lệnh đã đóng kèm PnL thực tế và thời gian nắm giữ.

### 2.2 Sổ chiến lược & Backtest (`/api/studio/book`)
- `GET /api/studio/book/current`: Cấu hình sổ chiến lược hiện tại.
- `POST /api/studio/book/backtest`: Khởi chạy job backtest sổ danh mục (bất đồng bộ).
- `POST /api/studio/book/wfa`: Khởi chạy job Walk-Forward Analysis danh mục.

### 2.3 Phễu duyệt Alpha (`/api/studio/funnel`)
- `POST /api/studio/funnel/runs`: Tạo mới một lượt chạy tối ưu hoá phễu.
- `GET /api/studio/funnel/runs`: Danh sách các lượt chạy phễu.
- `GET /api/studio/funnel/runs/{run_id}/stages`: Thống kê tỷ lệ vượt qua từng tầng (S0 đến S6).
- `GET /api/studio/funnel/runs/{run_id}/alphas`: Bảng danh sách các alpha đạt chuẩn.

### 2.4 Trình soạn thảo chiến lược Studio (`/api/studio/custom` & `/api/studio/strategies`)
- `POST /api/studio/strategies/compile`: Biên dịch và kiểm tra cú pháp AST theo Strategy Contract.
- `POST /api/studio/custom/backtest`: Khởi chạy job backtest chiến lược tùy chỉnh của người dùng (`custom_backtest`).
- `POST /api/studio/strategies/save`: Lưu trữ chiến lược vào thư mục `data/alpha/user/`.

### 2.5 Giáo trình định lượng Education (`/api/studio/education`)
- `GET /api/studio/education/samples`: Danh mục 50 mẫu chiến lược phân loại theo 5 trường phái định lượng.
- `POST /api/studio/education/run`: Khởi chạy thử nghiệm cho một mẫu chiến lược.

### 2.6 Quản lý Job nền (`/api/studio/jobs`)
- `GET /api/studio/jobs/{job_id}`: Kiểm tra trạng thái job (`queued`, `running`, `done`, `failed`).
- `POST /api/studio/jobs/{job_id}/cancel`: Huỷ bỏ một job đang chạy.

### 2.7 Bot giao dịch Live (`/api/studio/live`)
- `POST /api/studio/live/start`: Khởi chạy bot nền theo cấu hình sổ (`mode`: `paper`, `demo`, `live`).
- `GET /api/studio/live/status`: Giám sát trạng thái bot thời gian thực, vị thế mở và nhật ký lệnh.
- `POST /api/studio/live/stop`: Dừng bot an toàn.
