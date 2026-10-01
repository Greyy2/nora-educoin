# E10-S5: Giải thích và kiểm edge riêng của SOL

- **Epic:** E10 Nghiên cứu chiến lược mới & phương pháp
- **Trạng thái:** backlog
- **Cập nhật:** 2026-10-01

## Story

Là người nghiên cứu, tôi muốn hiểu vì sao alpha trend chỉ lãi trên SOL và liệu edge có bền, để quyết định có nên đưa vào testnet với rủi ro tập trung.

## Acceptance Criteria

1. **Given** cùng tham số alpha SOL, **When** chạy trên 7 tài sản còn lại, **Then** báo cáo dev2/holdout từng tài sản (đã có: 1/7 lãi ở cả hai, chỉ DOGE) kèm phân tích theo regime (xu hướng/đi ngang, biến động).
2. **Given** các cửa sổ trượt khác nhau, **When** chạy lại alpha SOL, **Then** báo cáo độ nhạy theo mốc bắt đầu (ít nhất 3 mốc).
3. **Given** kết quả, **When** kết luận, **Then** ghi rõ nên hay không nên cấp testnet cho SOL, kèm hệ số vốn đề xuất (0,5x hay 0,75x, Q-3).

## Tasks / Subtasks

- [ ] Phân tích theo regime
- [ ] Độ nhạy mốc bắt đầu và cửa sổ
- [ ] So sánh DOGE (lãi) và các tài sản còn lại
- [ ] Viết kết luận trong `docs/alpha_pipeline.md`

## Dev Notes

- R-3. Dữ liệu: `registry.json` → `robustness.other_assets`; `data/alphas/portfolio_*.json`.
- Một lân cận tham số (`trailing_stop=3,0`) làm dev2 chỉ còn +3,12%: kiểm độ nhạy trailing.

## Evidence

- Chưa áp dụng: story chưa làm.

## Change Log

| Ngày | Thay đổi |
|---|---|
| 2026-10-01 | Tạo story, trạng thái `backlog`. |
