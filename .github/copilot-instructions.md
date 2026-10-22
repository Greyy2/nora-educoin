# HƯỚNG DẪN DỰ ÁN & BỐI CẢNH NỀN TẢNG (NoraBT System Instructions)

> **Mục tiêu dự án:** Tách biệt và tối ưu hóa hệ thống NoraBT thành hai dự án con độc lập:
> 1. **EDU (Educational Backtest & Alpha Studio):** Quản lý DSL, phân tích chiến lược, giả lập backtest trên nến BTC/crypto.
> 2. **COIN (Live Trading Bot & Production):** Chạy bot giao dịch tự động trực tiếp trên sàn.

---

### 1. Kiến Trúc Cốt Lõi & Quy Tắc Cô Lập (Đã Hoàn Tất)
- **Workstream 1 (Import Origin Isolation & Containment):**
  - Mọi module của EDU phải resolve 100% từ `/home/vmc03/norabt/nora/edu/backend/`, tuyệt đối không dùng ngược module monolith hay của COIN.
  - Bộ nhớ RAM cho các job nặng của EDU bị giới hạn tối đa 2GB qua `nora/edu/ops/run_limited.sh` và khóa file lock độc lập `nora-edu-heavy.lock`.
- **Workstream 2 (EDU Backtest / Jobs API):**
  - Đã kích hoạt 44 routes cho EDU tại `nora/edu/backend/routes/studio.py`:
    - `POST /api/studio/custom/backtest`: Nhận mã DSL, validate, enqueue job, trả về `job_id`.
    - `GET /api/studio/jobs/{job_id}`: Truy vấn tiến độ `progress.json` và log `out.log`.
    - `POST /api/studio/jobs/{job_id}/cancel`: Huỷ job qua tín hiệu SIGTERM.
- **Workstream 4 (Tách Biệt Xác Thực Token):**
  - Phân tách qua Audience Claim: `PRODUCT_AUDIENCE = "nora_edu"` và `"nora_coin"`. Token sinh ra từ sản phẩm này không thể gọi API hay thao tác trên sản phẩm kia.

---

### 2. Môi Trường Python & Lệnh Kiểm Thử Chuẩn
- Virtualenv EDU/COIN: `/home/vmc03/.venvs/nora312/bin/python`
- Chạy test kiểm tra toàn bộ suite EDU:
  `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/edu/tests/test_edu_app.py`
- Chạy test kiểm tra toàn bộ suite COIN:
  `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/coin/tests/test_coin_app.py`
- File tài liệu kiến trúc tham chiếu chi tiết:
  `nora/docs/architecture-edu-coin-backtest.md`

---

### 3. Phong Cách Làm Việc Của Copilot
- Luôn nắm rõ ngữ cảnh trên, không hỏi lại các kiến thức cơ bản đã cấu hình.
- Khi người dùng yêu cầu tiếp tục, tập trung trực tiếp vào phân tích hệ thống scan backtest, tối ưu logic DSL, xử lý các job queue và tiếp tục các workstream còn lại theo kế hoạch.
