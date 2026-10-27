# BÁO CÁO TỔNG KẾT TOÀN DIỆN: KHẢ THI OOS SAU CHI PHÍ & NĂNG LỰC VẬN HÀNH 10 BOT DEMO

**Ngày hoàn tất:** 2026-10-26 14:46:11
**Trạng thái hợp đồng:** `COIN_EXECUTION_PARITY_CONTRACT_V1` (ENFORCED)
**Môi trường kiểm tra:** Simulated / OKX Demo Proxy | **Live Capital:** `BLOCKED (false)`

## 1. Kết quả Cách ly Dữ liệu EDU & COIN theo Allowlist

- **Nguyên tắc:** Dữ liệu alpha của EDU giữ nguyên 100%. COIN chỉ giữ lại các ứng viên Top OKX, Proxima và Vinh Breakout.
- **Thực hiện:** Đã chuyển 62 alpha trùng không thuộc allowlist sang thư mục an toàn: `nora/coin/data/alpha/_quarantine/`.
- **Allowlist COIN được kích hoạt:** `33312a2f4dfc`, `alpha_proxima_research`, `18e87aa868ad`, `efa90f74cd08`.

## 2. Kết quả Parity Fixtures (Khớp lệnh & Tín hiệu)

- **File fixture:** `nora/coin/tests/test_candidate_parity_fixtures.py`
- **Tín hiệu & Ý định lệnh:** Khớp chính xác 100% về vị trí thanh nến, indicator math và order intent.
- **Ràng buộc rủi ro Master:** Khẳng định engine sizing ép chặt mức rủi ro tối đa $\le 25\text{ USDT}$ / trade trên Master 10.000 USDT (Fast Dip: Notional $\le 1.250\text{ USDT}$; Vinh Breakout: Notional $\le 1.000\text{ USDT}$).
- **Kết quả test:** **PASS 3/3 tests (100%)**.

## 3. Bảng Kết quả Feasibility Độc lập Từng Cấu hình (Train vs OOS & Stress x2)

| Chiến lược | Cặp | Train Ret% (Trades) | OOS Base Ret% (Trades) | OOS Base PF | OOS Base MDD | OOS Stress x2 Ret% | OOS Stress PF | OOS Stress MDD | Kết luận Sàng lọc |
|---|---|---|---|---|---|---|---|---|---|
| Fast Dip Harvester | BTC | +0.98% (2) | +0.49% (1) | N/A (0 trade lỗ) | 0.0% | +0.48% | N/A (0 trade lỗ) | 0.0% | **CHƯA ĐỦ BẰNG CHỨNG** |
| Fast Dip Harvester | ETH | +0.49% (1) | +0.0% (0) | N/A | 0.0% | +0.0% | N/A | 0.0% | **CHƯA ĐỦ BẰNG CHỨNG** |
| Vinh Breakout (33312a2f4dfc) | BTC | +5.65% (24) | +2.41% (11) | 2.134 | 2.01% | +2.23% | 1.991 | 2.15% | **KHẢ THI THỬ DEMO** |
| Vinh Breakout (33312a2f4dfc) | ETH | +20.45% (28) | +-1.7% (15) | 0.427 | 1.86% | +-2.0% | 0.374 | 2.1% | **CHƯA ĐỦ BẰNG CHỨNG** |

> [!NOTE]
> **Trạng thái Funding Rate:** Ghi nhận `PARTIAL_PROXY` (thiếu dữ liệu qua đêm liên tục ở các khung dài). Các kết quả trên cần tiếp tục được đối soát khi thu thập đủ chuỗi fills trên OKX Demo.

## 4. Đánh giá Sức chứa Vận hành 10 Bot (Capacity Test Hạ tầng)

- **Mô hình Master Ledger:** 10.000 USDT ảo được chia đều cho 10 bot sleeves (1.000 USDT / sleeve).
- **Kiểm soát rủi ro cộng dồn (Master Risk Controller):**
  - Rủi ro tối đa mỗi lệnh: $25\text{ USDT}$ / lệnh.
  - Tổng rủi ro mở đồng thời tối đa của 10 bot: $\le 250\text{ USDT}$ ($2.5\%$ Master Equity).
  - Giới hạn dừng lỗ ngày (Master Daily Loss): Chạm $-200\text{ USDT}$ ($-2.0\%$) $\to$ Toàn bộ 10 bot bị khóa vào lệnh mới ngay lập tức.
  - Đòn bẩy gộp (Gross Exposure): Tổng 10 vị thế $\le 30.000\text{ USDT}$ ($3.0\times$).
  - Cơ chế biên ngày: Tự động tính toán PnL, trừ funding và flatten lúc 00:00:00 UTC.
- **Kết luận Sức chứa:** Hạ tầng NoraBT hoàn toàn đủ điều kiện kỹ thuật để chạy đồng thời 10 sleeves trên OKX Demo mà không xảy ra xung đột lệnh hay tràn rủi ro danh mục.

## 5. Các Việc Phụ Trợ Đã Hoàn Tất (UI / UX)

1. **Form Đăng nhập (`EnterForm.jsx`):** Đã xóa bỏ hoàn toàn mật khẩu mặc định `1`, xóa placeholder/label gợi ý `(mặc định: 1)`, bắt buộc user tự nhập mật khẩu.
2. **Bộ chọn Danh mục (`Backtest.jsx`):** Đã sắp xếp Top Assets đưa BTC lên đầu, ETH thứ hai; bổ sung 2 nút tiện ích **[Chọn Top 10]** và **[Chọn Top 20]** phục vụ chọn nhanh danh mục.
