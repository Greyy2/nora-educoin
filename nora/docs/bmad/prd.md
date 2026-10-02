# PRD: Nora, pipeline nghiên cứu và kiểm chứng chiến lược crypto perp

Phiên bản: 1.0 · Ngày: 01/10/2026 · Nhánh: `fix/pipeline-audit` (HEAD `a3202c9`) · Phạm vi code: `nora/`

Tài liệu này mô tả sản phẩm cần có và ghi rõ phần nào đã có, phần nào chưa. Chi tiết kỹ thuật ở
[architecture.md](architecture.md); danh sách việc ở [epics.md](epics.md). Mọi số đo đều có nguồn trong repo;
chỗ chưa đo ghi "chưa đo".

## 1. Vấn đề và tầm nhìn

### 1.1 Vấn đề

Bảng xếp hạng bot giao dịch công khai (OKX, Binance) cho thấy lãi rất cao nhưng không cho thấy lỗ treo, đòn bẩy
và chi phí thật. Phân tích trong `alpha_pipeline.md` §7 cho thấy phần lớn ROI "khủng" đến từ đòn bẩy 10-30x
và lỗ chưa chốt không hiển thị; chia cho đòn bẩy trung vị thì chỉ còn khoảng 2-15% mỗi 90 ngày trên 1x. Một bộ quét
"rải limit" từng cho +10-20 bps/lệnh trên cả 8 tài sản, nhưng trên random walk vẫn ra +15 bps: edge giả do chọn trước
lệnh "sẽ khớp" và do giả định stop-loss khớp đúng mức. Hai lỗi này là lỗi kiểm chứng, không phải lỗi thị trường.

Vì vậy cần một hệ thống mà kết quả backtest đáng tin: không nhìn trước tương lai, chi phí và rủi ro thanh lý được mô phỏng,
đường vốn tính cả lỗ chưa chốt, và mọi chiến lược phải qua nhiều cổng kiểm chứng độc lập trước khi được gọi là alpha.

### 1.2 Tầm nhìn

Một pipeline duy nhất, tái lập được từng bit, đi từ dữ liệu thị trường đến cấu hình chạy testnet/live cho crypto perp:

```
nghiên cứu -> kiểm chứng (backtest, WFA, Monte Carlo, holdout) -> alpha/sổ chiến lược -> testnet/live -> theo dõi danh mục
```

Nguyên tắc không đổi:

1. **Không nới gate để có kết quả đẹp.** Không có chiến lược nào đạt thì báo "không có". Hiện trạng: một alpha đơn tài sản
   đạt (SOL), sổ chiến lược trượt holdout (`HOLDOUT_FAILED`) và không có cấu hình testnet.
2. **Causal tuyệt đối.** Giá trị tại nến t chỉ dùng dữ liệu đã đóng tới t; khung lớn chỉ hiện khi nến khung đó đã đóng.
3. **Bi quan khi chưa chắc.** Phía bất lợi xử lý trước trong nến; mọi kết quả báo cả SL khớp "level" (cận trên) và "extreme" (cận dưới).
4. **Theo dõi bằng NAV mark-to-market,** không bằng lãi đã chốt.

## 2. Người dùng mục tiêu

| Người dùng | Việc cần làm | Tính năng chính |
|---|---|---|
| Người nghiên cứu / quant | Đề xuất chiến lược, hiệu chỉnh tham số, kiểm chứng, đọc bằng chứng | Trang Alpha, Backtest/WFA/Monte Carlo, kho alpha, lệnh `python -m backend.<gói>.<lệnh>` |
| Người vận hành | Chạy job nặng an toàn trên máy dùng chung, xuất bản sổ, theo dõi danh mục, xử lý sự cố | Hàng đợi `run_limited`, `nora.slice`, trang Danh mục, `publish`, log RAM |

Hiện chưa có người dùng trả tiền hay đa người dùng; hệ thống chạy một máy, một nhóm nhỏ, không có xác thực (xem NFR-9, R-5).

## 3. Mục tiêu và chỉ số thành công

| # | Mục tiêu | Chỉ số / ngưỡng | Hiện trạng (nguồn) |
|---|---|---|---|
| G1 | Chỉ công nhận alpha qua đủ cổng | WFA: ≥ 60% fold OOS có lãi, ≥ 5 fold, lãi IS TB ≥ 0, MDD fold ≤ 30%, lãi kép OOS ≥ 0 · Monte Carlo trên lợi suất ngày MTM: P(MDD ≥ 30%) ≤ 5% (alpha đơn tài sản: chuỗi mô phỏng dài bằng số ngày OOS; sổ: 365 ngày) · Holdout 20% cuối: lãi > 0, MDD ≤ 30%, đủ lệnh · đòn bẩy ≤ 10x | `trend_long_perp__SOL` đạt: WFA 14 fold, 9 có lãi (64,3%), OOS +35,97%; MC ngày 0,80% (chuỗi 434 ngày OOS); holdout +14,71%, MDD 12,23% (`data/alphas/registry.json`) |
| G2 | Sổ chiến lược qua holdout trước khi xuất cấu hình testnet | `holdout_level` > 0 và MDD ≤ 30% (cả level, extreme) | **Chưa đạt**: sổ `breakout_4h_long + breakout_4h_short` holdout −4,06% (level) / −7,38% (extreme) → `HOLDOUT_FAILED`, không có `testnet/book.json` |
| G3 | Tái lập bit-identical | Cùng dữ liệu (sha256), cùng tham số, cùng seed cho cùng từng bit; tối ưu hiệu năng không đổi kết quả | Golden harness 3 kịch bản + 1 test phát hiện xáo trộn 1 bit; qua mọi lần mmap / skip-idle / tái cấu trúc (`test/test_golden_results.py`) |
| G4 | Chạy gọn trong ngân sách RAM chung | `nora.slice` MemoryMax 12 GB, không swap; không job nào làm sập máy | Sau sửa OOM: build 7 ứng viên × 24 cấu hình 487 s, đỉnh 2,5 GB (`06ae13b`); benchmark 8 perp: đỉnh slice 5950 → 2045 MB (`b179f2b`) |
| G5 | Vòng lặp UI đầy đủ không cần CLI | Alpha build → Backtest → WFA → Monte Carlo → Danh mục | Chạy thật: build 71,1 s, backtest 6,6 s, WFA 53,5 s (đọc từ `data/_cache/api_jobs/*/job.json`); Monte Carlo đồng bộ, ngưỡng test < 15 s ở kích thước tối đa, thời gian thực tế chưa ghi log |
| G6 | Theo dõi danh mục Live / Testnet / Backtest | Cùng một payload cho cả ba nguồn; Live/Testnet nối tài khoản thật không đổi UI | Payload xong; Live/Testnet đang dùng feed **giả lập** (`mock: true`); chưa có tài khoản thật |
| G7 | Không có gate nào bị nới âm thầm | Hằng số gate nằm ở một nơi, có test | `backend/wfa/portfolio_wfa.py` (đầu file), `backend/core/strategy/strategy_book.py` (`GATES`), `backend/optimize/optimize_alphas.py` |

## 4. Phạm vi

### 4.1 Trong phạm vi

- Dữ liệu Binance spot và USDT-M perp (8 tài sản: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX), nến 1m + funding, 3 năm.
- Tín hiệu kernel causal, chiến lược AST, engine 1m có DCA, perp, thanh lý, funding, sổ vốn chung, giới hạn danh mục.
- Kiểm chứng: WFA (đơn tài sản và danh mục), Monte Carlo (theo lệnh và theo ngày MTM), holdout, kiểm độ bền, kiểm null.
- Kho alpha, sổ chiến lược, xuất cấu hình Binance Futures testnet, xuất bản có xác nhận.
- API Studio (job nền), UI v2 (Danh mục, Backtest/WFA/Monte Carlo, Alpha), vận hành trong `nora.slice`.

### 4.2 Ngoài phạm vi (hiện tại)

- Giao dịch tự động thật (bot gửi lệnh), kể cả testnet: chưa có (epic E9).
- Khung dưới 1 phút, sổ lệnh (order book), tick CEX; dữ liệu on-chain; đa sàn ngoài Binance.
- Tối ưu danh mục toàn cục (mean-variance), phân bổ vốn động giữa alpha.
- Đa người dùng, phân quyền, thanh toán.
- DEX spot: dữ liệu và code còn (AERO, VVV, tối đa 179 ngày) nhưng không phải trọng tâm; DEX không hỗ trợ perp.
- Hệ thống MySQL/Mongo cũ và các trang "Legacy" của UI: giữ nguyên, không phát triển thêm.

## 5. Yêu cầu chức năng (FR)

Cột "TT": **Có** = đã có và có test; **Một phần** = có nhưng thiếu ý nào đó (ghi chú); **Chưa** = chưa có. Cột Epic trỏ tới [epics.md](epics.md).

### 5.1 Dữ liệu

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-1 | Crawl nến 1m Binance spot và USDT-M perp + lịch sử funding từ data.binance.vision (ZIP có checksum SHA-256) và REST cho phần mới nhất; thiếu tháng hoặc checksum sai thì `crawl_ok=false` | Có | E1 |
| FR-2 | Bố cục `data/cex/<SYM>[/perp]`, `data/dex/<SYM>`; ký hiệu `BTC@perp` luôn phân giải tới thư mục perp, không bao giờ rơi về spot; tên trùng giữa hai venue phải ghi tiền tố, không đoán | Có | E1 |
| FR-3 | 1m là nguồn duy nhất; 5m/15m/1h/4h/24h resample theo UTC, `label=left, closed=left`, 4h neo 00:00 UTC; resample idempotent | Có | E1 |
| FR-4 | Mỗi tài sản có `manifest.json` (nguồn, `synthetic`, `crawl_ok`, độ phủ, `filled_ratio_1m`, `sha256_1m`, checksum đã xác minh) | Có | E1 |
| FR-5 | Quality gate trả `APPROVED / WARNING / BLOCKED / NEEDS_MORE_DATA`; chặn khi thiếu manifest, `synthetic`, `crawl_ok=false`, sha256 lệch, trùng timestamp, `filled_ratio > 60%`, thiếu 4h, resample lệch; < 30 ngày thì `NEEDS_MORE_DATA` | Một phần: gate được gọi ở Studio `/simulate`, scan, WFA đơn tài sản, research, `promote_staging`; **không** gọi trong đường danh mục/sổ (`PortfolioEngine`, `build_strategy_book`, `validate_book`, `run_book_backtest`) | E1, E11 |
| FR-6 | `promote_staging` chỉ chuyển sang `data/<venue>/` những tài sản qua gate | Có | E1 |

### 5.2 Tín hiệu và chiến lược

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-7 | 23 kernel thuần và causal (prefix-invariant); NaN trong giai đoạn khởi động; điều kiện dùng NaN là False | Có | E2 |
| FR-8 | Khung 1m, 5m, 15m, 1h, 4h, 24h; kernel khung F chỉ hiện ở nến 1m khi nến F đã đóng (`avail_time = open_F + độ dài F`); đọc nến trước bằng `index` (≤ 500) | Có | E2 |
| FR-9 | Chiến lược là cây điều kiện AST; bộ đánh giá vector cho cùng kết quả với bộ đánh giá từng nến | Có | E2 |
| FR-10 | Kiểm tra tín hiệu trước khi ghép chiến lược: `CO_THONG_TIN / YEU / KHONG` theo t-stat, kiểm bằng dữ liệu cài sẵn edge và random walk | Có | E2 |
| FR-11 | Thư viện: 8 tín hiệu `SIGNALS`, 8 chiến lược mẫu `KERNEL_STRATEGIES`, 5 không gian tối ưu `OPTIMIZATION_SPACES`, 7 ứng viên sổ `CANDIDATES` | Có | E2 |
| FR-12 | Ngưỡng tín hiệu tham số hoá `{"param": ...}`, tối ưu qua khoá `sig.<tên>` | Có | E2 |

### 5.3 Engine và rủi ro

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-13 | Khớp lệnh trên nến 1m có giao dịch; vào ở open nến kế tiếp sau tín hiệu; phía bất lợi xử lý theo thứ tự giá chạm, hoà thì ưu tiên thoát; gap khớp ở open; không chốt lời trong nến vừa khớp tầng DCA | Có | E3 |
| FR-14 | Phí taker cho lệnh market (vào, SL, trailing, timeout, thoát theo tín hiệu), maker cho tầng DCA và chốt lời; mặc định theo venue: CEX perp 0,05%/0,02% + trượt 0,02% | Có | E3 |
| FR-15 | Perp: ký quỹ isolated, giá thanh lý, funding trả/nhận hạch toán vào vốn; spot không short, không đòn bẩy | Có | E3 |
| FR-16 | Hai kiểu khối lượng: `margin_pct` (ký quỹ = % vốn hiện tại) và `risk` (lỗ tại SL = `risk_per_trade_pct`% vốn, gồm phí khứ hồi); `risk` cần `stop_loss_rate > 0` | Có | E3 |
| FR-17 | `exit_unit="atr"`: SL/TP/trailing/bước DCA là bội số ATR% của nến đã đóng lúc có tín hiệu; chưa đủ ATR thì bỏ tín hiệu | Có | E3 |
| FR-18 | Đòn bẩy thực (sizing `risk`, perp) = min(đòn bẩy tham số, ⌊1/(1,5×SL + mmr)⌋) để giá thanh lý cách giá vào ≥ 1,5 lần khoảng SL | Có | E3 |
| FR-19 | Ngân sách DCA: cấu hình `margin_pct` không vừa vốn bị từ chối kèm gợi ý `order_size_pct` lớn nhất còn vừa; tầng bị bỏ lúc chạy được đếm (`dca_layers_rejected`) | Có | E3 |
| FR-20 | `cooldown` (phút) sau khi đóng vị thế mới nhận tín hiệu vào lại (mặc định 0; sổ dùng 60) | Có | E3 |
| FR-21 | `CapitalLedger`: mọi flow và tầng DCA giữ chỗ từ cùng một quỹ vốn; vốn ≤ 0 thì ngừng mở lệnh | Có | E3 |
| FR-22 | `PortfolioEngine`: nhiều tài sản × nhiều chiến lược trên một sổ vốn; `RiskConfig` mặc định 8 vị thế, 1 vị thế/tài sản, tổng danh nghĩa ≤ 3× vốn, kill switch khi MDD MTM ≥ 30% | Có | E3 |
| FR-23 | Đường vốn MTM lấy mẫu mỗi giờ, kèm điểm xấu nhất trong nến (`equity_worst`); MDD thấy được lỗ treo | Có | E3 |
| FR-24 | Dữ liệu giá + kernel dùng chung giữa worker qua mmap (chỉ đọc); bỏ qua phút rảnh; kết quả bit-identical | Có | E3 |

### 5.4 Kiểm chứng

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-25 | WFA đơn tài sản: fold IS/OOS không chồng, chọn tham số trên IS, kiểm cố định trên OOS; gate gồm `is_return, total_folds, positive_ratio, total_trades, worst_mdd, compounded_return`; fold không có cấu hình đủ lệnh IS là `NO_TRADE` | Có | E4 |
| FR-26 | WFA danh mục: IS chọn lại cấu hình từng chiến lược, OOS chạy cả sổ chung vốn (kill switch bật), báo SL "level" và "extreme"; gate 6 điều kiện (xem architecture §6.2) | Có | E4 |
| FR-27 | Monte Carlo block bootstrap theo lệnh đã đóng **và** theo lợi suất ngày MTM; cổng ruin dùng cơ sở ngày; cùng seed cho cùng số | Có | E4 |
| FR-28 | Holdout 20% cuối chạy một lần với cấu hình đã chốt; không chọn lại gì ở bước này | Có | E4 |
| FR-29 | Kiểm độ bền: lân cận tham số (đổi từng tham số một mức) và chuyển tài sản | Có | E4 |
| FR-30 | Kiểm null: bộ quét mới phải ra "không có edge" trên random walk | Có (cho bộ quét maker và DC); chưa là cổng bắt buộc cho mọi bộ quét | E4, E10 |
| FR-31 | Hệ số vốn tối đa theo ngân sách rủi ro P(MDD ≥ 30%) ≤ 5% (bootstrap ngày) | Có | E4 |
| FR-32 | Hiệu chỉnh đa kiểm định (Deflated Sharpe, permutation test), nhật ký số lần chạm holdout | Chưa | E10 |

### 5.5 Alpha và sổ chiến lược

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-33 | `optimize_alphas`: dev1 sàng lọc (top-8) → dev2 WFA → MC ngày → holdout; ALPHA chỉ khi qua cả bốn và đòn bẩy ≤ 10x | Có | E4, E5 |
| FR-34 | Kho alpha `data/alphas/registry.json` ghi đủ để tái lập (AST đã thay tham số, bằng chứng từng giai đoạn, sha256 dữ liệu, commit code) | Có | E5 |
| FR-35 | `build_strategy_book`, giai đoạn A-D: dev1 chọn tham số trên cả vũ trụ, dev2 gate, chốt rủi ro/lệnh bằng bootstrap, holdout một lần | Có | E5 |
| FR-36 | `book.json` luôn có `status ∈ {READY_FOR_TESTNET, HOLDOUT_FAILED}`; `testnet/book.json` chỉ ghi khi holdout đạt, và xoá bản cũ khi trượt | Có | E5 |
| FR-37 | Cấu hình testnet mô tả đúng hành vi đã mô phỏng (ISOLATED, MARKET vào lệnh, LIMIT GTX cho DCA, STOP_MARKET reduce-only, kill switch 30%) | Có (chỉ là file cấu hình; chưa có bot đọc) | E5, E9 |

### 5.6 Vận hành

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-38 | Mọi job nặng chạy qua `backend/utils/ops/run_limited.sh` trong `nora.slice` (12 GB, không swap), xếp hàng tuần tự bằng `flock`, CPU 0-13, nice 10 | Có | E6 |
| FR-39 | Script nặng từ chối chạy khi không có trần RAM cgroup (trừ `NORA_ALLOW_UNLIMITED=1`) | Có | E6 |
| FR-40 | Số worker tự chia: min(CPU dùng được, ngân sách RAM / RAM mỗi worker); ngân sách chừa dự phòng 8 GB cho máy dùng chung | Có | E6 |
| FR-41 | Worker bị OOM-kill thì chạy lại riêng các job còn thiếu với nửa số worker; lỗi thật của job nổi lên ngay | Có | E6 |
| FR-42 | Cài đặt lặp lại được: venv + `requirements.txt` ghim phiên bản, unit systemd user (`install_user_units.sh`) | Có | E6 |
| FR-43 | `smoke_check` kiểm bất biến và tất định nhanh (single / portfolio / studio / optcheck) | Có | E6 |

### 5.7 API

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-44 | `/api/studio/book/*`: backtest, WFA, build chạy nền (trả `job_id`), trạng thái `queued/running/done/failed`, bền qua khởi động lại API, tối đa 8 job đang chạy/chờ (429) | Có | E7 |
| FR-45 | Đối số job kiểm chặt: danh sách trắng loại job và cờ, không shell, ngày/tài sản/số trong khoảng | Có | E7 |
| FR-46 | `POST /book/mc` đồng bộ, trùng bit với `run_monte_carlo_daily` cùng seed; giới hạn simulations ≤ 10000, horizon ≤ 730 | Có | E7 |
| FR-47 | `POST /book/publish` chép sổ của job build sang `data/alphas/` (build không tự ghi đè sổ đang xuất bản) | Có | E7 |
| FR-48 | `GET /portfolio/dashboard?source=live|testnet|backtest`, 5 kỳ `1M/3M/YTD/1Y/ALL`; Live/Testnet rơi về feed giả lập có `mock: true` | Có | E7 |
| FR-49 | `GET /book/`, `GET /alphas` cấp catalog, tham số mặc định, vũ trụ, cửa sổ, kho alpha | Có | E7 |
| FR-50 | API Studio cũ (`/simulate`, `/scan`, `/wfa/run`, `/monte-carlo/run`) lưu SQLite, giữ tương thích | Có | E7 |

### 5.8 UI

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-51 | Trang Danh mục: KPI, NAV so với BTC, drawdown, P&L ngày, phân phối lợi suất + VaR, heatmap tháng, rolling Sharpe, bảng chiến lược, sự kiện rủi ro, bảng vị thế đang mở | Có | E8 |
| FR-52 | Nguồn Live / Testnet / Backtest; feed giả lập có banner và chip MOCK | Có | E8 |
| FR-53 | Trang Backtest → WFA (tham số cố định hoặc chọn lại ở IS) → Monte Carlo (fan chart, histogram, gate), deep-link được | Có | E8 |
| FR-54 | Trang Alpha: bảng xếp hạng stage A, "Gửi sang Backtest", kho alpha, trạng thái sổ, "Xuất bản sổ này" có hộp xác nhận | Có | E8 |
| FR-55 | Chủ đề Sáng/Tối, nhớ lựa chọn | Có | E8 |
| FR-56 | Cải thiện trải nghiệm (đang làm): phạm vi chốt trong story E8-S6 | Một phần | E8 |

### 5.9 Testnet và Live

| ID | Yêu cầu | TT | Epic |
|---|---|---|---|
| FR-57 | Bot Binance Futures testnet đọc `testnet/*.json` và chạy đúng quy tắc đã mô phỏng | Chưa | E9 |
| FR-58 | `TestnetFeed` / `LiveFeed` thật (lịch sử lệnh, số dư, vị thế) thay feed giả lập, payload không đổi | Chưa (stub `NotAvailable`) | E9 |
| FR-59 | Kill switch live (30% từ đỉnh) và giới hạn danh mục áp trên tài khoản thật | Chưa | E9 |
| FR-60 | Đối soát live so với backtest (sai khác khớp lệnh, trượt giá, phí) | Chưa | E9 |

## 6. Yêu cầu phi chức năng (NFR)

| ID | Loại | Yêu cầu | Cách kiểm |
|---|---|---|---|
| NFR-1 | Tính đúng | Không nhìn trước tương lai ở kernel, khung lớn, vào lệnh, chọn tham số trong WFA | `test_kernel_is_causal_prefix_invariant`, `test_prefix_check_detects_a_lookahead_kernel`, `test_no_lookahead_when_future_modified`, `test_4h_lookahead_candle_visibility`, `test_is_selection_never_sees_oos_data` |
| NFR-2 | Tính đúng | Bất biến vốn ở mọi nến; lãi/lỗ tính lại độc lập từ lệnh con khớp | `test_ledger_invariants_every_bar_random_multi_flow`, `test_pnl_recomputed_independently_from_orders` |
| NFR-3 | Tái lập | Cùng dữ liệu + tham số + seed = cùng từng bit; mọi float của golden mã hoá `float.hex()` | `test_golden_*`, `test_*_skip_equals_full_loop`, `test_mmap_data_equals_built_data_bit_for_bit` |
| NFR-4 | Hiệu năng | Job build/WFA đủ nhanh để lặp trong một buổi | build 71,1 s (1 ứng viên × 8 cấu hình), WFA 53,5 s, backtest 6,6 s; full 7 × 24 cấu hình 487 s; các số khác chưa đo |
| NFR-5 | Bộ nhớ | Toàn Nora ≤ 12 GB (`nora.slice`), API ≤ 3 GB; ~142 MB RAM riêng mỗi worker; không cache nào không giới hạn | `test_memory_guards.py` (25 test), log `data/_cache/runs/*_mem.csv` |
| NFR-6 | Bảo mật | Chỉ API được phép gọi job; không shell; không lộ khoá sàn; truy cập bị kiểm soát | Đối số job: có (`test_book_api.py`). Xác thực API: **chưa có** (R-5); khoá sàn: chưa áp dụng vì chưa có bot |
| NFR-7 | Khả dụng UI | Dùng được ở trình duyệt bị chính sách chặn URL chứa "miner"; Sáng/Tối; trạng thái job rõ (queued/running/done/failed) | commit `cc68087`, `b0419d5` |
| NFR-8 | Quan sát | Mỗi job có `out.log`, thời điểm bắt đầu/kết thúc, mã thoát; mỗi lần chạy nặng có log RAM mỗi giây | `data/_cache/api_jobs/<id>/`, `data/_cache/runs/` |
| NFR-9 | Bảo mật mạng | API chỉ nên nghe trong mạng tin cậy | Hiện unit systemd đặt `NORA_API_HOST=0.0.0.0`, CORS `*`: **chưa đạt** (E11) |
| NFR-10 | Bảo trì | Bố cục package rõ (core/db/api/optimize/wfa/carlo/utils + main.py; lệnh nằm trong gói của nó, ops trong utils/ops); không import vòng | commit `6d35c0d`: 94 module import được; `backend/main.py` vẫn 2261 dòng chứa route cũ |

## 7. Ràng buộc

- **Máy dùng chung:** 67 GB RAM, không swap, ~32 GB trống tại thời điểm cấu hình; Nora giới hạn 12 GB (~18%). Tràn trần thì kernel chỉ giết tiến trình trong slice. Một job tràn RAM từng làm sập cả máy trước khi có `nora.slice` (nguyên nhân gốc: cache không giới hạn × 10 worker, xem E6-S1).
- **CPU:** lõi 0-13, `nice 10`; controller `cpu` không được uỷ quyền cho user session nên dùng `taskset`, không dùng `CPUQuota`.
- **Chính sách trình duyệt:** trình duyệt do quản trị chặn đường dẫn có chứa "miner"; Vite dev nạp `/src/pages/Miner.jsx` làm toàn app không khởi động. Đã đổi tên thành `PhienDao.jsx` (`cc68087`). Mọi tên file/route mới tránh từ này.
- **Dữ liệu:** Binance Vision (3 năm). DEX qua GeckoTerminal miễn phí tối đa 179 ngày, không có tick lịch sử.
- **Sàn mục tiêu:** Binance USDT-M (phí VIP0: taker 0,05%, maker 0,02%). Mọi kết quả phụ thuộc giả định phí và trượt giá 0,02% mỗi chiều.
- **Python 3.11** trong `~/.venvs/nora`; số tệp dữ liệu (`data/`) không commit, trừ `data/alphas/`.

## 8. Rủi ro và câu hỏi mở

| ID | Rủi ro / câu hỏi | Tác động | Hướng xử lý |
|---|---|---|---|
| R-1 | **Đa kiểm định (multiple testing).** Đã quét 34 cặp chiến lược × tài sản ở một lượt `optimize_alphas` (`data/_cache/optimize/20260930_1728`: 1 ALPHA, 23 KHONG_DAT, 10 LOAI_O_SANG_LOC), chưa kể các lượt khác và 7 ứng viên sổ. Gate hiện tại không hiệu chỉnh cho số lần thử | Alpha SOL có thể là kết quả may mắn khi chọn 1 trong 34 | E10-S1 (Deflated Sharpe), E10-S2 (permutation test), E10-S6 (sổ ghi số lần thử) |
| R-2 | **Holdout đã dùng nhiều lần.** Giai đoạn D của sổ đã chấm ít nhất 2 lần (`data/_cache/book/20261001_115808`, `..._152813`); holdout của SOL được dùng lại khi tái kiểm (`45f734e`) và trong các lượt tối ưu khác | Holdout không còn "chưa ai chạm"; ước lượng lạc quan | E10-S3 (chính sách holdout, holdout mới khi có dữ liệu mới) |
| R-3 | **Edge SOL riêng lẻ.** Trend chung cho 8 tài sản thất bại; long trend chỉ có edge trên SOL, DOGE yếu (`alpha_pipeline.md` §7); SOL một mình tốt hơn SOL+DOGE | Rủi ro tập trung một tài sản; có thể là đặc thù giai đoạn | E10-S5 |
| R-4 | **Sổ trượt holdout.** Dev2 +26,8% (level) rồi holdout −4,06%: dấu hiệu quá khớp giai đoạn dev hoặc đổi regime | Chưa có sổ nào được cấp testnet | E10-S4 |
| R-5 | **API chưa xác thực.** Unit systemd nghe `0.0.0.0`, CORS `allow_origins=["*"]`, `POST /book/*` chạy được job nặng và `publish` ghi đè `data/alphas/` | Ai trong mạng cũng chạy được job hoặc đổi sổ | E11-S1, E11-S2, E11-S3 |
| R-6 | **Chưa có live feed.** Live/Testnet là dữ liệu giả lập tất định từ engine thật; trang Danh mục dễ bị hiểu nhầm là số thật | Quyết định sai nếu bỏ qua banner MOCK | Banner + chip MOCK đã có; E9-S3, E9-S4 |
| R-7 | **Gate dữ liệu không chặn đường danh mục.** Dữ liệu hỏng sau khi đã promote sẽ không bị `PortfolioEngine` phát hiện | Kết quả sổ sai âm thầm | E11-S6 |
| R-8 | **Giả định khớp lệnh.** SL khớp "level" lạc quan; `extreme` bi quan; thực tế nằm giữa. Chưa đối soát với sàn thật | Lợi nhuận thật có thể thấp hơn cận trên | E9-S6 |
| R-9 | **Bundle UI một cục** (~583 KB JS chưa nén, `frontend/dist`); `main.py` 2261 dòng còn route MySQL cũ | Tải chậm, khó bảo trì | E11-S4, E11-S5 |
| Q-1 | Có chấp nhận holdout "mới" bằng dữ liệu tích luỹ thêm (từ 01/10/2026 trở đi) làm cổng cuối cho SOL không? | Quyết định E10-S3 | Chờ chủ sở hữu |
| Q-2 | Vốn thật tối đa cho testnet/live và ngân sách rủi ro (hiện 30% MDD, ≤ 5% xác suất) có giữ nguyên? | Quyết định E9-S5 | Chờ chủ sở hữu |
| Q-3 | Hệ số vốn cho alpha SOL: 0,5x (extreme) hay 0,75x (level)? | Cấu hình testnet | Chờ chủ sở hữu |
