# Tài liệu Dự án Nora

Toàn bộ tài liệu chính thức của hệ thống Nora được quản lý tập trung và chuẩn hóa theo phương pháp **BMAD (Breakthrough Method for Agile AI-Driven Development)** tại thư mục `bmad/`.

---

## Mục lục Tài liệu Chính

| Tài liệu | Mô tả |
|---|---|
| [bmad/README.md](bmad/README.md) | Tổng quan hệ thống tài liệu BMAD và hướng dẫn quy trình làm việc |
| [bmad/product-brief.md](bmad/product-brief.md) | Project Brief: Vấn đề, tầm nhìn, người dùng mục tiêu và chỉ số thành công |
| [bmad/prd.md](bmad/prd.md) | PRD v2.0: Yêu cầu chức năng (FR1–FR41), NFR, và danh sách Epics (E1–E20; E22–E23 xem epics.md) |
| [bmad/p16_consolidation_plan.md](bmad/p16_consolidation_plan.md) | Kế hoạch P16 hiện hành: hiện trạng, kiến trúc file đích, phases, `backend/data.py` |
| [bmad/p15_handover.md](bmad/p15_handover.md) · [bmad/p15_api_contract.md](bmad/p15_api_contract.md) | Luật kiến trúc/logic P15 và hợp đồng API (Nautilus native) |
| [nautilus_architecture.md](nautilus_architecture.md) | Kiến trúc Nautilus (sẽ gộp với handover ở P16 task 6.1) |
| [knowledge_base/02_boss_mandates_and_rulebase.md](knowledge_base/02_boss_mandates_and_rulebase.md) | Luật/chỉ đạo của anh (rulebase) |
| [bmad/ux-design.md](bmad/ux-design.md) | Đặc tả Frontend & UX: MetaProvider, Sơ đồ trang, và Responsive chuẩn |
| [bmad/epics.md](bmad/epics.md) | Danh sách 23 Epics và 136 Stories |
| [bmad/sprint-status.yaml](bmad/sprint-status.yaml) | Nguồn trạng thái máy đọc duy nhất của toàn bộ sprint |
| [bmad/stories/](bmad/stories/) | Danh sách chi tiết các Story định dạng chuẩn 9 mục BMAD |
| [bmad/archive/](bmad/archive/) | Kho lưu trữ lịch sử kế hoạch cũ (P6–P13), review logs, handover, legacy docs |
| [bmad/archive/2026-10-p16/](bmad/archive/2026-10-p16/README.md) | Tài liệu engine cũ/DEX đã archive ở P16 (architecture/*, p14_*, knowledge_base 01/03/04) — xem README trong thư mục |

---

*Lưu ý: Không tạo tài liệu kế hoạch rời bên ngoài thư mục `bmad/`. Quyết định kỹ thuật mới ghi vào `bmad/p16_consolidation_plan.md` (hoặc plan phase kế tiếp); ADR cũ đã archive.*
