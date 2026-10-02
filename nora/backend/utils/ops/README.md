# backend/utils/ops — vận hành Nora

Mọi lệnh dưới đây chạy từ thư mục `nora/` (hoặc dùng đường dẫn tuyệt đối; script tự tìm `nora/`).

| File | Là gì | Cách chạy |
|---|---|---|
| `run_limited.sh` | Chạy lệnh Python trong `nora.slice` (trần RAM chung 12G, không swap), xếp hàng tuần tự bằng flock, giới hạn CPU bằng taskset | `backend/utils/ops/run_limited.sh -- -m backend.optimize.build_strategy_book --n 24` · `backend/utils/ops/run_limited.sh -- -m pytest test -q -p no:cacheprovider` |
| `install_user_units.sh` | Cài systemd user unit `nora.slice` + `nora-api.service` (không enable/start); chạy lại được nhiều lần | `backend/utils/ops/install_user_units.sh` rồi `systemctl --user restart nora-api` (hoặc `./start_nora.sh` ở gốc repo) |
| `systemd/nora.slice` | Mẫu slice: ngân sách RAM chung cho API, script nặng và test | do `install_user_units.sh` chép đi |
| `systemd/nora-api.service.in` | Mẫu unit API (uvicorn, cổng 18010); `@NORA_DIR@`/`@NORA_PYTHON@` được điền khi cài | do `install_user_units.sh` sinh ra |
| `check_tests_vs_ref.sh` | Chạy bộ test HIỆN TẠI trên code backend tại một git ref cũ để xác nhận test bắt được lỗi cũ | `backend/utils/ops/check_tests_vs_ref.sh <git-ref>` |

Lệnh nghiệp vụ nằm trong gói của nó (bảng "Lệnh chạy nằm ở đâu" ở `docs/README.md`), chạy bằng `-m backend.<gói>.<lệnh>`; `make_golden.py` nằm ở `test/`:
`backend/utils/ops/run_limited.sh -- test/make_golden.py` (chỉ khi CHỦ ĐÍCH đổi ngữ nghĩa backtest).
