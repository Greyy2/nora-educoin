# Danh mục Hữu hạn Alpha Universe (GATE 1 - Alpha Universe Manifest)

**Status:** APPROVED INVENTORY (No Alpha Scoring Performed)  
**Date:** 2026-10-25  
**Version:** 1.0.0-INVENTORY  

---

## 1. Giới thiệu & Phạm vi

Theo quy định của **GATE 1**, bước này chỉ lập danh mục hữu hạn (finite inventory) có tính tái lập của toàn bộ các biến thể chiến lược và tập dữ liệu đầu vào đã duyệt.
**Tuyệt đối chưa thực hiện chấm điểm alpha, xếp hạng hay tối ưu hóa tham số** khi các gate thực thi và rủi ro chưa hoàn tất.

---

## 2. Ma trận Biến thể Hữu hạn (72 Variants)

Vũ trụ chiến lược được tổ chức thành 2 track độc lập:
1. **Track 1: Swing / Positional (5m, 15m, 1h, 4h, 24h)**
   - 3 họ chiến lược (`kema`, `sideway`, `dca`) $\times$ 2 chân (`LONG`, `SHORT`) = 6 candidates.
   - 2 cặp tiền cơ sở (`BTC-USDT-SWAP`, `ETH-USDT-SWAP`).
   - 5 khung thời gian ($6 \times 2 \times 5 = 60$ biến thể).
   - Hệ số stress chi phí: **x2**.

2. **Track 2: Scalp (1m)**
   - 6 candidates $\times$ 2 cặp tiền $\times$ 1 khung ($6 \times 2 \times 1 = 12$ biến thể).
   - Hệ số stress chi phí: **x2 và x3** (áp lực trượt giá và độ trễ cao).

Tổng quy mô không gian tìm kiếm: **72 biến thể hữu hạn**.

---

## 3. Ràng buộc Tách biệt & Dữ liệu Causal

- Dữ liệu đầu vào: OKX Parquet Catalog đã kiểm toán (BTC: `cd026438b6a668b1`, ETH: `8d62dc2d69c4d5cf`).
- Không có bất kỳ thay đổi nào làm biến đổi catalog active hiện tại.
- Tất cả các kết quả cũ từ `book.json` (36 candidate pre-parity) giữ nguyên trạng thái **CÁCH LY TOÀN PHẦN** (`QUARANTINED_STALE`).
