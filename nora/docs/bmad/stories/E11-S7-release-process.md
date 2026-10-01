# E11-S7: Quy trình phát hành và tài liệu

- **Epic:** E11 Bảo mật & phát hành
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người vận hành, tôi muốn một lệnh kiểm tra trước phát hành và quy trình gắn thẻ phiên bản, để mỗi bản chạy trên máy dùng chung đã qua test, golden và smoke.

## Acceptance Criteria

1. **Given** một lệnh kiểm tra (ví dụ `backend/ops/pre_release.sh`), **When** chạy, **Then** thực hiện `pytest` (qua `run_limited`), golden, `smoke_check single|portfolio` và in tổng kết đạt/không đạt.
2. **Given** phát hành, **When** gắn thẻ, **Then** có file phiên bản và `CHANGELOG` ghi thay đổi, hằng số gate và số test.
3. **Given** `requirements.txt`, **When** rà soát, **Then** dòng ghi số test được cập nhật hoặc bỏ (hiện ghi "265 test").
4. **Given** mỗi lần phát hành, **When** rà soát tài liệu, **Then** `architecture.md` §14 không còn mục lệch nào chưa xử lý.

## Tasks / Subtasks

- [ ] Script kiểm tra trước phát hành
- [ ] Chính sách phiên bản và thẻ git
- [ ] Sửa `requirements.txt` (dòng "265 test")
- [ ] Ghi vào `backend/ops/README.md`

## Dev Notes

- Hiện chưa có CI; kiểm tra chạy tay qua `run_limited.sh`. Số test: 440 (theo `a3202c9`).

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
