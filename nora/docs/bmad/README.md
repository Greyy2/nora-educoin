# Bộ tài liệu BMAD của Nora

Bộ tài liệu được xây dựng và duy trì theo phương pháp **BMAD (Breakthrough Method for Agile AI-Driven Development)**: kết hợp chặt chẽ giữa yêu cầu sản phẩm (PRD), kiến trúc và đặc tả kỹ thuật, danh sách Epic, và các Story có tiêu chí chấp nhận định lượng cùng bằng chứng kiểm chứng cụ thể.

Tài liệu được viết bằng tiếng Việt; các thuật ngữ kỹ thuật, tên file, hàm, tham số và trạng thái máy đọc giữ nguyên tiếng Anh.
- Baseline code: Commit `f4864d5` (Nhánh `fix/pipeline-audit`)
- Cập nhật: 12/10/2026

---

## 1. Mục lục Tài liệu

| Tài liệu | Nội dung chính | Khi nào đọc |
|---|---|---|
| [product-brief.md](product-brief.md) | Vấn đề, tầm nhìn, đối tượng người dùng, chỉ số thành công | Khi bắt đầu dự án hoặc định hình lại mục tiêu |
| [prd.md](prd.md) | PRD v2.0: Phạm vi, FR1–FR41, NFR1–NFR8, ràng buộc, rủi ro và danh sách Epics (E1–E20 + E22–E23 mục P15/P16 trong epics.md) | Trước khi đề xuất tính năng hoặc thay đổi phạm vi |
| [p16_consolidation_plan.md](p16_consolidation_plan.md) | Kế hoạch P16 hiện hành: hiện trạng, kiến trúc file đích (§4), `backend/data.py` (§5), phases | Trước khi sửa mã nguồn hoặc thiết kế luồng |
| [p15_handover.md](p15_handover.md) · [p15_api_contract.md](p15_api_contract.md) · [p15_nautilus_native_backend.md](p15_nautilus_native_backend.md) | Luật kiến trúc/logic, hợp đồng API và plan gốc P15 (Nautilus native) | Khi làm việc với engine/API |
| [../knowledge_base/02_boss_mandates_and_rulebase.md](../knowledge_base/02_boss_mandates_and_rulebase.md) | Rulebase/chỉ đạo của anh | Khi cần luật nghiệp vụ |
| [ux-design.md](ux-design.md) | Đặc tả giao diện & UX: Sơ đồ màn hình, luồng người dùng, MetaProvider, chuẩn format | Khi phát triển hoặc sửa component frontend |
| [epics.md](epics.md) | Bảng tổng quan 23 Epics, 136 Stories, và tiến độ tổng | Khi lập kế hoạch sprint hoặc chọn story tiếp theo |
| [sprint-status.yaml](sprint-status.yaml) | Nguồn trạng thái máy đọc duy nhất của toàn bộ sprint | Cho công cụ CI/CD, script kiểm tra, và AI agent |
| [stories/](stories/) | Mỗi story một file markdown theo chuẩn BMAD 9 mục | Khi thực hiện hoặc nghiệm thu story cụ thể |
| [research/](research/) | Báo cáo nghiên cứu, tài liệu forge và specs theo chuẩn BMAD | Khi tham khảo kết quả nghiên cứu thị trường / bot |
| [archive/](archive/) | Lưu trữ kế hoạch cũ (P6–P13), review log, handover, roadmap cũ, legacy docs | Chỉ đọc khi cần tra cứu lịch sử quyết định |
| [archive/2026-10-p16/](archive/2026-10-p16/README.md) | architecture/*, architecture.md, p14_*, p15 v1, knowledge_base 01/03/04 (engine cũ/DEX) | Chỉ tra cứu lịch sử |

---

## 2. Quy ước Trạng thái Story & Epic

Mọi story và epic tuân thủ tập trạng thái thống nhất:
- `backlog`: Chưa làm, chưa đủ điều kiện bắt đầu.
- `ready`: Đủ điều kiện bắt đầu (phụ thuộc đã xong, AC đã được duyệt).
- `in-progress`: Đang trong quá trình triển khai code và kiểm thử.
- `review`: Đã hoàn thành code, đang chờ xác minh bằng chứng QA gate.
- `done`: Mọi Acceptance Criteria đã được kiểm chứng (có commit, test pass, số đo cụ thể) và QA Results ghi nhận `PASS`.

---

## 3. Mẫu Story BMAD Chuẩn (9 Mục)

Mỗi file story trong thư mục `stories/` bắt buộc tuân theo cấu trúc sau:
```markdown
# Story <Epic-ID>-<Story-ID>: <Tên Story>

## Status
Done | In-Progress | Review | Ready | Backlog

## Story
**Là** <vai trò>, **tôi muốn** <tính năng/hành động>, **để** <giá trị mang lại>.

## Acceptance Criteria
1. Given ... When ... Then ...
2. ...

## Tasks / Subtasks
- [x] Task 1 (AC: 1)
- [ ] Task 2 (AC: 2)

## Dev Notes
Nguồn tham chiếu architecture/..., file sửa, ràng buộc kỹ thuật.

## Dev Agent Record
- **Agent Model:** Tên model thực hiện
- **Completion Notes:** Ghi chú kỹ thuật khi hoàn thành
- **File List:** Danh sách file tạo/sửa

## QA Results
- **Gate:** PASS | CONCERNS | FAIL
- **Commit:** Hash commit tương ứng
- **Tests:** Tên unit test hoặc kết quả kiểm thử

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| YYYY-MM-DD | 1.0.0 | Khởi tạo và ghi nhận kết quả | Tên người/Agent |
```

---

## 4. Kiểm tra Tính Nhất Quán (Consistency Check)

Để đảm bảo toàn bộ hệ thống tài liệu không có liên kết gãy, trạng thái đồng bộ 100% giữa các story và `sprint-status.yaml`, chạy script:
```bash
python3 /home/vmc03/norabt/nora/test/scripts/check_docs.py
```
