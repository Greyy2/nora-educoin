# ops — vận hành Nora

Mọi lệnh dưới đây chạy từ thư mục `nora/` (hoặc dùng đường dẫn tuyệt đối; script tự tìm `nora/`).

| File | Là gì | Cách chạy |
|---|---|---|
| `run_limited.sh` | Chạy lệnh Python trong `nora.slice` (trần RAM chung 12G, không swap), xếp hàng tuần tự bằng flock, giới hạn CPU bằng taskset | API gọi `run_limited.sh -- -m backend.jobs.runner <job_dir>` cho mọi job · test: `ops/run_limited.sh -- -m pytest test -q -p no:cacheprovider` |
| `install_user_units.sh` | Cài systemd user unit `nora.slice` + `nora-api.service` (không enable/start); chạy lại được nhiều lần | `ops/install_user_units.sh` rồi `systemctl --user restart nora-api` (hoặc `nora/start.sh`) |
| `systemd/nora.slice` | Mẫu slice: ngân sách RAM chung cho API, script nặng và test | do `install_user_units.sh` chép đi |
| `systemd/nora-api.service.in` | Mẫu unit API (uvicorn, cổng 18010); `@NORA_DIR@`/`@NORA_PYTHON@` được điền khi cài | do `install_user_units.sh` sinh ra |

Việc nghiệp vụ không có lệnh terminal riêng: chạy qua endpoint API (bảng "Chạy việc gì ở đâu" ở `docs/README.md`).
Script kiểm tra/nghiên cứu ở `test/scripts/`, vd `ops/run_limited.sh -- test/scripts/make_golden.py` (chỉ khi CHỦ ĐÍCH đổi ngữ nghĩa backtest),
`test/scripts/check_tests_vs_ref.sh <git-ref>` (chạy test hiện tại trên code tại ref cũ).
