# Tiêu chuẩn lập trình & Luật thép Nora (Coding Standards)

Tài liệu này ghi lại các nguyên tắc kỹ thuật bắt buộc áp dụng cho toàn bộ mã nguồn của hệ thống Nora. Mọi đóng góp mã nguồn (của lập trình viên và AI agent) đều phải tuân thủ nghiêm ngặt các điều luật này.

---

## 1. Luật thép kiến trúc (Architectural Invariants)

1. **Một Engine duy nhất (`core/backtest.py`)**:
   - Mọi chế độ Backtest, Paper trading, Testnet và Live bot đều chạy trên cùng một engine `core/backtest.py`.
   - Tuyệt đối không xây dựng engine thứ hai cho mô phỏng sự kiện hay chạy live. Nếu muốn tăng tốc, tối ưu hoá thuật toán bên trong `backend/optimize/`.

2. **Mỗi logic đúng một định nghĩa (Single Source of Truth)**:
   - Nghiêm cấm sao chép nhân bản các khối logic tính toán giá, khớp lệnh, phân bổ vốn hay tính toán chỉ số.
   - Cổng kiểm định chất lượng: Lệnh kiểm tra `python test/scripts/p9_ledger.py --dups` bắt buộc phải trả về 0 trùng lặp.

3. **Phân tầng kiến trúc nghiêm ngặt (Strict Layering)**:
   - Thứ tự phụ thuộc một chiều: `core` → `alpha` / `metrics` / `regime` / `wfa` / `carlo` → `crawl` → `optimize` → `live` / `routes`.
   - `backend/core/` là logic thuần túy: tuyệt đối không thực hiện I/O (không đọc ghi file, không kết nối mạng, không import các module bên ngoài core).
   - `backend/metrics/` chỉ tính toán thuần túy: đầu vào là mảng số liệu/dict, đầu ra là chỉ số; không thực hiện I/O hay kiểm định cổng.
   - Cổng kiểm định: `pytest test/test_layering.py` ở chế độ strict bắt buộc phải đạt 0 lỗi vi phạm.

4. **Hợp đồng chiến lược thống nhất (Strategy Contract)**:
   - Mọi chiến lược (do người dùng viết hoặc chiến lược hệ thống) đều phải qua `backend/alpha/contract.py` và biên dịch về dạng IR chuẩn (`core/signal.Program`).
   - Xử lý theo 3 trạng thái rõ ràng: **RUN** (chuẩn native), **ADAPT** (chuyển đổi tương thích), **REJECT** (từ chối mã vi phạm danh sách trắng an toàn). Tuyệt đối không suy đoán logic khi mã không hợp lệ.

5. **Cấu trúc dữ liệu và vòng đời Cache**:
   - Cây dữ liệu thị trường chuẩn hoá dưới `data/market/<sàn>/{cex,dex}`. Chỉ sử dụng định dạng `.pkl` kèm metadata lưu trong thuộc tính DataFrame `attrs`.
   - Thư mục `data/cache/process/<job_id>/` chỉ được phép tồn tại khi tiến trình đang chạy. Khi tác vụ hoàn tất, kết quả phải được chuyển sang thư mục lưu trữ lâu dài (`data/backtest|wfa|carlo|alpha/`) và dọn sạch cache ngay lập tức.
   - Ngoại lệ: Lượt chạy thử nghiệm tạm thời của người học (Education) được lưu tối đa 24h trong cache; chỉ khi người dùng bấm Lưu mới chuyển thành file `data/alpha/user/<id>.json`.

6. **Kiểm soát tài nguyên hệ thống**:
   - Mọi script Python nặng hoặc tác vụ tính toán backtest/phễu phải được khởi chạy qua `ops/run_limited.sh` (áp dụng cgroup slice với giới hạn trần 12GB RAM).
   - Tác vụ nền từ giao diện người dùng phải đi qua hàng đợi API runner chuẩn; các script phân tích nghiên cứu phải nằm trong `test/scripts/`.

7. **Giao diện chỉ là lớp hiển thị (Presentation Layer Only)**:
   - Backend là nguồn sự thật duy nhất (`/api/studio/meta`).
   - Frontend không tự tính toán số liệu tài chính, không giữ logic kinh doanh, chỉ nhận dữ liệu và thực hiện định dạng hiển thị.

8. **Bảo toàn tính xác thực (Golden Tests Bit-Identical)**:
   - Các bộ kiểm thử Golden Scenarios và đối chiếu chuẩn NautilusTrader (`nautilus_diff`) phải ra kết quả bit-identical. Nếu có sự sai lệch số liệu, phải tìm nguyên nhân sửa code logic, tuyệt đối không được nới lỏng ngưỡng sai số của test.
   - Thông tin khoá API sàn OKX chỉ được phép đọc từ file cấu hình bảo mật `~/.config/nora/okx.env`. Chế độ Live tiền thật bắt buộc phải có cờ xác nhận tường minh `confirm_live`.

9. **Không Mock dữ liệu trong tính toán tài chính**:
   - Tuyệt đối không sử dụng mock trong các pipeline Backtest, Walk-Forward Analysis (WFA) hay Monte Carlo. Mọi phân tích phải chạy trên dữ liệu nến thật đã đóng.

---

## 2. Quy tắc mã nguồn Python

- **Chuẩn cú pháp**: Tuân thủ PEP 8, tương thích Python 3.11+.
- **Docstrings & Comments**: Viết chú thích tiếng Anh rõ ràng cho các thuật toán định lượng, công thức toán học và logic tín hiệu.
- **Tính nhân quả (Strict Causality)**: Mọi phép toán chỉ báo và tín hiệu chỉ được tính trên nến đã đóng (`close[t]`), tuyệt đối không được sử dụng thông tin của nến tương lai (`t+1`).
