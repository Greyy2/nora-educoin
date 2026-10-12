# Luật cho agent triển khai (Gemini qua agy) — Opus điều phối

1. Chỉ làm đúng task được giao (file/bước ghi trong brief). Không refactor ngoài phạm vi.
2. KHÔNG `git commit`, KHÔNG `git add`, KHÔNG `git push`, KHÔNG xoá dữ liệu trong `data/` (chỉ `mv` khi brief yêu cầu).
3. Chạy Python CHỈ qua: `cd /home/vmc03/norabt/nora && ops/run_limited.sh --no-lock -- <args>` (venv ~/.venvs/nora312 tự dùng). Không cài package.
4. Không sửa `nautilus_trader`. Chỉ `backend/nautilus/` được import `nautilus_trader`.
5. Không số giả: thiếu dữ liệu/logic → lỗi rõ hoặc 404/501 `NOT_READY`, không placeholder.
6. Một logic một định nghĩa. Comment tiếng Việt có dấu như code xung quanh.
7. Chỉ chạy test được nêu trong brief (không full suite trừ khi brief yêu cầu).
8. Kết thúc: ghi báo cáo `docs/bmad/handoff/<TASK>.report.md`: file đã đổi, việc đã làm, lệnh kiểm + output thật (pass/fail), điểm chưa làm / cần quyết định. Không nói "xong" nếu kiểm chưa đạt.
9. Gặp điểm phải quyết định (lệch dữ liệu, test cũ mâu thuẫn) → DỪNG, ghi vào report, không tự đoán.
