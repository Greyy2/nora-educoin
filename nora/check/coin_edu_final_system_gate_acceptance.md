# Biên bản Nghiệm thu Hệ thống Cuối cùng (GATE 8 - Final System Gate Acceptance)

**Hệ thống:** Nora Quant (COIN Platform & EDU Platform)  
**Ngày nghiệm thu:** 2026-10-25  
**Trạng thái tổng thể:** **ACCEPTED WITH RESTRICTIONS (LOCAL ACCEPTANCE PASSED / PROMOTION FROZEN)**  
**Phạm vi:** Kiểm toán tính chân thực Backtest - Live, Rào chắn Rủi ro, và Độc lập Hệ thống.  

---

## 1. Bảng Tổng hợp Kết quả Nghiệm thu 8 Cổng (Gates 0A – 8)

| Gate ID | Tên Cổng Nghiệm thu | Tiêu chuẩn Đánh giá | Kết quả Đạt được | Kết luận |
|---|---|---|---|:---:|
| **GATE 0A** | Fast Evidence Audit (C1–C10) | Bộ test hồi quy COIN/EDU tuần tự, 5x flaky journey, golden parity, native fill, final bar, contract, quarantine, no unintended orders, catalog hash, system check. | - COIN: 74/74 PASS, EDU: 25 PASS, Rubilab: 100% PASS.<br>- Flaky Journey: 10/10 PASS (5 lượt lặp liên tiếp).<br>- Catalog SHA-256 đối soát trùng khớp 100%.<br>- Check.sh: 18/19 PASS (chỉ cảnh báo dirty worktree). | **PASS** |
| **GATE 0** | Parity Execution Contract | Đóng băng quyết định của Owner: 10k Master, 1k Bot, Hard SL, 0.25% risk, 2% daily loss, 15% MDD, 3x gross, 2x net, 00:00 UTC flatten, L1 Quote Tick open fill, Stop slippage x2. | - Văn bản: `coin_execution_parity_contract.md`<br>- Cài đặt: `contracts.py`<br>- Cờ bảo vệ: `parameters_authoritative=false`, `execution_implemented=false`, `promotion_allowed=false`. | **FROZEN & ENFORCED** |
| **GATE 1** | Alpha Universe Manifest | Lập danh mục hữu hạn có tính tái lập, không chấm điểm sớm. Tách biệt Swing track (5m-24h) và Scalp track (1m). | - Manifest: `alpha_universe_manifest.json` (72 biến thể hữu hạn).<br>- 3 họ: `kema`, `sideway`, `dca` (6 candidates).<br>- Cách ly toàn phần 36 candidate pre-parity. | **APPROVED INVENTORY** |
| **GATE 2** | Market Data Readiness | Kiểm toán Parquet catalog nến 1m, tính hợp lệ OHLC, căn chỉnh UTC, tỷ lệ lấp đầy, digest SHA-256. | - 1,580,149 nến 1m sạch cho BTC và ETH (~3 năm).<br>- `filled_ratio: 0.0`, 100% hợp lệ OHLC.<br>- Báo cáo: `market_data_readiness_audit.md`. | **AUDITED & APPROVED** |
| **GATE 3 / 3A** | Nautilus Realism & Edge Cases | Khớp lệnh native Nautilus qua L1 Quote Tick ($t_{\text{open}} + 2\text{ns}$), Gap-through SL, Same-bar SL/TP adverse ordering, chặn nến cuối. | - 37/37 fixture tests PASS.<br>- Đảm bảo không bypass OrderMatchingEngine gốc của Nautilus. | **ENFORCED** |
| **GATE 4** | Authoritative Risk Gate | Master Ledger 6 invariants, PortfolioAdmissionController kiểm soát vốn gốc, equity headroom, free cash, today PnL. | - 27/27 accounting tests PASS.<br>- Chặn triệt để phantom capital và vượt hạn mức. | **ENFORCED** |
| **GATE 5B** | Cost Model Calibration | Hiệu chuẩn từ fills quan sát thực tế; nếu thiếu mẫu bắt buộc báo cáo INCONCLUSIVE và chặn promotion. | - Báo cáo: `cost_model_calibration_report.md`.<br>- Kết luận: **INCONCLUSIVE** (chưa đủ fills OKX Demo).<br>- `promotion_allowed = false` (Fail-Closed). | **INCONCLUSIVE (SAFE)** |
| **GATE 6** | Alpha Rerun Pipeline | Đánh giá 72 biến thể trên Train/Dev + OOS Holdout, stress chi phí x2/x3, DSR $\ge 0.95$, Monte Carlo ruin $\le 5\%$. | - Báo cáo cũ ghi `N=0`, nhưng chưa tìm thấy per-variant/fold raw artifacts, DSR inputs hoặc MC seeds/paths để tái lập.<br>- Báo cáo hiện được đánh dấu **UNVERIFIED / NOT EVALUATED**; không kết luận alpha nào thắng/thua. | **BLOCKED** |
| **GATE 7** | Portfolio Selection | Chọn tối đa 10 bot từ ứng viên đạt chuẩn, correlation $\le 0.5$, symbol/timeframe/family caps, Joint MC MDD $\le 20\%$. | - Báo cáo: `alpha_portfolio_selection_report.md`.<br>- **0 bot được release** do GATE 6, parity, cost và risk authority chưa qua; đây không phải kết luận đã chứng minh `N=0` alpha. | **BLOCKED** |
| **GATE 8** | Final System Gate | Kiểm định độc lập kiến trúc, route, memory cap, không cross-import, dịch vụ nền và legacy fallback. | - Toàn bộ dịch vụ chạy ổn định (Port 18012, 18022, 18010).<br>- Memory cap 4GB (COIN) và 2GB (EDU) được giám sát. | **ACCEPTED** |

---

## 2. Cam kết Vận hành & An toàn Vốn (Operational Directives)

1. **Tuyệt đối KHÔNG sử dụng Vốn thật:** Mọi hoạt động giao dịch chỉ được phép diễn ra trên môi trường Sandbox / Paper hoặc tài khoản OKX Demo Trading.
2. **Nguyên tắc Fail-Closed được bảo toàn:** Toàn bộ candidate hoặc backtest job thiếu chữ ký số xác thực nguồn gốc từ máy chủ (`server_attestation`) đều bị từ chối 400 trước khi chạm vào launcher.
3. **Tính toàn vẹn mã nguồn:** Mọi thay đổi logic đều có fixture độc lập đi kèm, bảo toàn các comment, docstring và tính độc lập của 2 phân hệ COIN và EDU.
