# E6-S5: Bố cục package gọn và môi trường tái lập

- **Epic:** E6 Hạ tầng vận hành & bộ nhớ
- **Trạng thái:** done
- **Cập nhật:** 2026-10-01

## Story

Là người phát triển, tôi muốn thư mục `nora/` chỉ còn backend, data, docs, frontend, test và một `requirements.txt` ghim phiên bản, để dễ định vị code và dựng lại môi trường.

## Acceptance Criteria

1. **Given** bố cục mới, **When** import các module, **Then** 107 module import được (kiểm bằng tay ở `4e8dd61`).
2. **Given** `backend/cli/<tên>.py`, **When** chạy `python -m backend.cli.<tên>`, **Then** chạy được từ `nora/` với `PYTHONPATH=nora`.
3. **Given** `requirements.txt`, **When** tạo venv Python 3.11 bằng `uv`, **Then** cài đủ để chạy test (httpx có cho `TestClient`).
4. **Given** di chuyển file, **When** xem lịch sử, **Then** dùng `git mv` nên giữ được lịch sử file.
5. **Given** tái cấu trúc, **When** chạy golden, **Then** bit-identical và một backtest sổ thật cho output giống hệt trước/sau.

## Tasks / Subtasks

- [x] `core/ db/ api/ optimize/ wfa/ carlo/ utils/` (`6d35c0d`)
- [x] `scripts/` → `backend/cli/`, `ops/` → `backend/ops/`, `alphas/` → `data/alphas/` (`4e8dd61`)
- [x] `tests/` → `test/`, cập nhật `pytest.ini`, `.gitignore`
- [x] Xoá mã chết `backend/db.py` (bị `db/` che)
- [>] `requirements.txt` còn ghi "265 test" (lỗi thời) — việc nhỏ, ghi nhận ở E11-S7

## Dev Notes

- `.gitignore`: `nora/data/*` bị bỏ qua, ngoại lệ `nora/data/alphas/`.
- `check_tests_vs_ref.sh <git-ref>` chỉ dùng được cho ref từ `6d35c0d` trở đi (đường import đã đổi).
- `backend/main.py` vẫn 2261 dòng chứa route cũ (E11-S5).

## Evidence

- Commits: `6d35c0d` (94 module import được, 430 test qua, golden bit-identical, `smoke_check` 0 FAIL, backtest sổ thật giống hệt), `4e8dd61` (107 module, 430 test qua, golden không đổi, `smoke_check` 0 FAIL, API chạy job xếp hàng xong).
- Dữ liệu ghi trong message commit; không có test tự động cho việc import toàn bộ module.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story và ghi nhận trạng thái `done` theo code tại `a3202c9` (nhánh `fix/pipeline-audit`); bằng chứng lấy từ `git log`, test và số liệu trong `data/`. |
