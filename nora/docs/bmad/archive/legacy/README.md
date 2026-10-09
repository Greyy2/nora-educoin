# Legacy: tài liệu BMAD giai đoạn DEX (chỉ để tra cứu lịch sử)

Các file trong thư mục này được viết ở giai đoạn Nora còn là công cụ nghiên cứu vi cấu trúc DEX
(tick, Directional Change, Intrinsic Time; ngày đề trên file: 06/09/2026 đến 08/09/2026).
Từ cuối tháng 09/2026 hệ thống đổi trọng tâm sang crypto perp (Binance USDT-M), pipeline
data -> tín hiệu -> backtest -> WFA -> Monte Carlo -> holdout -> alpha/sổ chiến lược.

**Không còn đúng hiện trạng.** Cụ thể:

- Đường dẫn code đã đổi: `backend/core/research/...` vẫn còn nhưng không phải trục chính; CLI chuyển từ
  `nora/scripts/` sang `backend/cli/`, test từ `nora/tests/` sang `nora/test/` (commit `6d35c0d`, `4e8dd61`).
- Các số liệu trong `02_current_system_status.md` (cổng, trạng thái ONLINE, 50 asset DEX) là ảnh chụp ngày 08/09/2026.
- `03_api_and_data_contracts.md` không mô tả các endpoint `/api/studio/book/*` và `/api/studio/portfolio/*`.
  Hợp đồng hiện hành: `nora/docs/ui_contract.md`.
- `waves/` là nhật ký ba đợt sóng của giai đoạn DEX; không có đợt sóng nào sau đó.

Tài liệu hiện hành: [../README.md](../README.md) (PRD, kiến trúc, epic, story, trạng thái sprint).
Các luật thép trong `nora/docs/knowledge_base/` (causal, không nới gate, chi phí thật) vẫn áp dụng.

| File | Nội dung gốc |
|---|---|
| `01_architecture_and_codemap.md` | bản đồ code giai đoạn DEX |
| `02_current_system_status.md` | hiện trạng ngày 08/09/2026 |
| `03_api_and_data_contracts.md` | hợp đồng API giai đoạn DEX |
| `04_playbook_specifications.md` | playbook DC Fade / Breakout / Do Not Trade |
| `waves/wave_01..03_*.md` | báo cáo ba đợt sóng DEX |
