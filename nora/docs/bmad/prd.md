# PRD: Nora, Pipeline Nghiên Cứu và Kiểm Chứng Chiến Lược Crypto Perp

Phiên bản: 2.0 · Ngày: 09/10/2026 · Kiến trúc chuẩn: P9–P12 (Backend 5 phân tầng, Data một cây, UI MetaProvider)

Tài liệu này mô tả chi tiết sản phẩm, phạm vi, các yêu cầu chức năng (FR), yêu cầu phi chức năng (NFR), rủi ro, và ánh xạ tới danh sách Epics (E1–E20). Chi tiết kỹ thuật nằm ở [architecture.md](architecture.md); danh sách chi tiết các story ở [epics.md](epics.md).

---

## 1. Vấn đề và tầm nhìn

### 1.1 Vấn đề
- Bảng xếp hạng bot giao dịch công khai (OKX, Binance) thường phóng đại lợi nhuận (bỏ qua lỗ treo, đòn bẩy quá mức, chi phí trượt giá và funding thật).
- Nhiều hệ thống backtest mắc lỗi nghiêm trọng: **nhìn trước tương lai (lookahead bias)**, giả định khớp lệnh phi thực tế (chọn trước lệnh thắng, khớp stop-loss tại đúng giá đặt khi nến gap xuyên qua), và **overfitting** do thử quá nhiều tham số mà không có kiểm định out-of-sample nghiêm ngặt.
- Thiếu sự liên kết chặt chẽ giữa môi trường backtest và môi trường thực thi live, dẫn tới việc "backtest lãi khủng nhưng live cháy tài khoản".

### 1.2 Tầm nhìn
Xây dựng một pipeline định lượng crypto perp duy nhất, tái lập bit-identical, đi từ nến thô tới thực thi live:
```
Dữ liệu chuẩn -> Tín hiệu/Chiến lược -> Core Engine (Khớp 2 pha) -> Kiểm chứng (WFA/MC/Holdout) -> Alpha Registry/Sổ -> Live (Paper/Testnet/Live)
```

**Nguyên tắc không thoả hiệp:**
1. **Tuyệt đối Causal:** Nến tại thời điểm $t$ chỉ nhìn dữ liệu đã đóng trước hoặc tại $t$. Không nhìn trước nến tương lai.
2. **Bi quan khi chưa chắc chắn:** Trong một nến, chiều bất lợi được xử lý trước; tính cả 2 kịch bản SL level (cận trên) và SL extreme (cận dưới).
3. **Quản trị bằng NAV Mark-to-Market (MTM):** Đường vốn tính theo NAV thực tế từng giờ (bao gồm unrealized PnL), không chỉ tính vốn khi chốt lệnh.
4. **Không nới cổng kiểm định:** Không hạ tiêu chí để lấy kết quả đẹp. Nếu không đạt thì kết luận "chưa có alpha".
5. **Một Engine duy nhất:** Cùng một logic khớp lệnh và hạch toán vốn từ backtest, WFA, Monte Carlo đến Paper/Testnet.

---

## 2. Người dùng mục tiêu

| Người dùng | Nhu cầu & Hành vi | Điểm chạm tính năng |
|---|---|---|
| **Quantitative Researcher** | Nghiên cứu tín hiệu, viết chiến lược, quét không gian tham số, chạy WFA & Monte Carlo, xuất bản Alpha | Trang Studio, Backtest, Funnel, Alpha Lab, CLI `ops/run_limited.sh` |
| **Trader / Quant Operator** | Vận hành sổ chiến lược, theo dõi danh mục đa tài sản, giám sát rủi ro tài khoản thật, kích hoạt Kill Switch | Trang Portfolio, Live Monitor, History, cấu hình `live/config.yaml` |
| **Quant Learner / Dev** | Tìm hiểu cơ chế khớp lệnh perp, xem mẫu chiến lược chuẩn, tự viết và chạy thử chiến lược theo contract | Trang Education, Create Alpha, tài liệu `engine-spec.md` |

---

## 3. Mục tiêu và chỉ số thành công

| ID | Mục tiêu | Chỉ số & Ngưỡng định lượng | Trạng thái hiện tại |
|---|---|---|---|
| **G1** | Chỉ công nhận Alpha qua đủ cổng | WFA: $\ge 60\%$ fold OOS có lãi, $\ge 5$ folds, MDD OOS $\le 30\%$, CAGR OOS $> 0$. Monte Carlo MTM: $P(\text{MDD} \ge 30\%) \le 5\%$. Holdout 20% cuối: Return $> 0$, MDD $\le 30\%$, Leverage $\le 10x$. | Đạt cho cặp `SOL` (`trend_long_perp__SOL`: WFA 14 folds, 64.3% win, OOS +35.97%; MC ngày 0.80%; Holdout +14.71%). |
| **G2** | Sổ chiến lược qua Holdout trước khi cấp Testnet | `holdout_level > 0` và MDD $\le 30\%$ (cả level và extreme). | Đang tiếp tục kiểm chứng thêm các ứng viên mới sau P10. |
| **G3** | Tái lập Bit-identical | Cùng SHA256 dữ liệu, cùng tham số, cùng seed $\rightarrow$ Ra kết quả trùng khớp từng bit float (`test_golden_results.py`). | 100% đạt qua Golden Harness và Nautilus 332/332 parity test. |
| **G4** | Vận hành trong ngân sách RAM | Giới hạn `nora.slice` MemoryMax 12 GB, không swap; không có process nào gây OOM máy chủ. | Đạt. Quản lý qua `ops/run_limited.sh` và `flock`. |
| **G5** | Vòng lặp UI Studio khép kín | Người dùng tạo chiến lược $\rightarrow$ Backtest $\rightarrow$ WFA $\rightarrow$ MC $\rightarrow$ Xuất bản sổ hoàn toàn qua giao diện web. | Đạt (Trang Backtest, Alpha, CreateAlpha kết nối `/api/studio/*`). |
| **G6** | Giám sát danh mục Live / Paper | Dashboard đọc trực tiếp trạng thái tài khoản OKX demo / live thật, hiển thị NAV MTM, drawdown, vị thế mở. | Đạt qua route `/api/studio/live/*`. |

---

## 4. Phạm vi sản phẩm

### 4.1 Trong phạm vi
- **Dữ liệu:** OKX & Binance Futures (10 tài sản cốt lõi: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, NEAR, SUI), nến 1m + funding history, cấu trúc cây thống nhất `data/market/<venue>/<market>/<symbol>/<timeframe>.pkl`.
- **Backend 5 phân tầng:** `alpha → core → optimize → live → routes`. Core engine không phụ thuộc I/O.
- **Chiến lược:** Strategy Contract tiêu chuẩn (`BaseStrategy`, `evaluate(candles) -> signals`, kiểm định RUN / ADAPT / REJECT).
- **Core Engine:** Khớp nến 1m, 2 pha (khám phá tín hiệu $\rightarrow$ khớp lệnh nội bar OHLC), hỗ trợ DCA, isolated margin perp, funding rate, liquidation price, và `CapitalLedger` chống over-allocation.
- **Kiểm chứng:** Walk-Forward Analysis (WFA), Monte Carlo Block Bootstrap (theo lệnh và theo chuỗi ngày MTM), Holdout out-of-sample.
- **Thực thi Live:** Tách biệt 3 môi trường rõ ràng: `live/paper`, `live/testnet`, `live/live`.
- **Frontend:** Single-Page Application (React/Vite), giao diện Dark Theme chuyên nghiệp, Responsive, lấy danh mục metadata động từ `/api/studio/meta`.

### 4.2 Ngoài phạm vi
- Giao dịch cao tần dưới 1 phút (HFT, order book tick-level L2/L3).
- Arbitrage cross-exchange và multi-leg spread trading.
- DEX và on-chain spot tokens (tập trung tối đa vào Crypto Perp CEX).
- Đa người dùng phức tạp, SSO, phân quyền RBAC và hệ thống thanh toán thương mại.

---

## 5. Yêu cầu chức năng (Functional Requirements - FR)

### 5.1 Dữ liệu Thị trường (Market Data)
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-1** | Crawl dữ liệu nến 1m lịch sử và funding rates từ sàn (Binance / OKX) kèm kiểm tra checksum tính toàn vẹn. | Có | E1 |
| **FR-2** | Lưu trữ dữ liệu chuẩn hóa dạng một cây duy nhất `data/market/<venue>/<market>/<symbol>/<timeframe>.pkl`. | Có | E1, E17 |
| **FR-3** | Đóng gói metadata (`sha256`, `coverage`, `filled_ratio`, `is_synthetic`) trực tiếp vào attrs của DataFrame `.pkl`. | Có | E1, E17 |
| **FR-4** | Resample causal từ nến 1m ra các khung cao hơn (5m, 15m, 1h, 4h, 1d) theo UTC, `label='left', closed='left'`. | Có | E1 |
| **FR-5** | Data Quality Gate: Tự động phân loại `APPROVED / WARNING / BLOCKED / NEEDS_MORE_DATA`. Chặn dữ liệu thiếu hoặc synthetic. | Có | E1, E11 |
| **FR-6** | Bổ sung đầy đủ 10 cặp tài sản chính: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, NEAR, SUI. | Có | E17 |

### 5.2 Tín hiệu và Chiến lược (Alpha & Strategy Contract)
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-7** | Thư viện 23+ kernel tín hiệu thuần và strictly causal (prefix-invariant). Không được phép rò rỉ nến tương lai. | Có | E2 |
| **FR-8** | Căn chỉnh đa khung thời gian: Nến khung $F$ chỉ có sẵn cho nến 1m sau khi nến $F$ đã đóng (`avail_time = open_F + duration_F`). | Có | E2, E20 |
| **FR-9** | Chuẩn hóa Strategy Contract: Kế thừa `BaseStrategy`, cài đặt phương thức `evaluate(candles) -> signals`. | Có | E18 |
| **FR-10** | Trình xác thực Alpha Validator: Phân loại chiến lược theo 3 trạng thái `RUN` (hợp lệ trực tiếp), `ADAPT` (cần bọc adapter), `REJECT` (sai contract/lookahead). | Có | E18 |
| **FR-11** | Cung cấp kho 50+ chiến lược mẫu (Trend, Reversal, Breakout, Volatility, DCA) kèm docstrings tiếng Anh giải thích logic cho Education. | Có | E18 |
| **FR-12** | Quản lý tham số hoá chiến lược (`parameters` schema) cho phép engine quét grid/opt một cách tất định. | Có | E2, E18 |

### 5.3 Core Execution Engine & Quản trị Vốn
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-13** | Khớp lệnh nến 1m theo mô hình 2 pha: Phase 1 tạo tín hiệu cuối nến $t$; Phase 2 khớp lệnh tại nến $t+1$ (open hoặc chạm limit/stop trong bar). | Có | E3, E20 |
| **FR-14** | Khớp lệnh nội bar bi quan: Ưu tiên chạm Stop-Loss trước Take-Profit khi cả 2 mức giá đều nằm trong phạm vi $[Low, High]$. | Có | E3 |
| **FR-15** | Mô phỏng chi phí thực tế: Phí taker/maker theo sàn, trượt giá (slippage), funding rate tính theo chu kỳ 8 giờ. | Có | E3 |
| **FR-16** | Cơ chế tính khối lượng đa dạng: Fixed Margin, % Equity, hoặc % Risk per trade (đo bằng khoảng cách ATR tới SL). | Có | E3 |
| **FR-17** | Quản lý vị thế DCA và đòn bẩy Isolated: Tính toán chính xác giá hòa vốn, giá thanh lý và tỷ lệ ký quỹ duy trì. | Có | E3 |
| **FR-18** | `CapitalLedger`: Sổ quỹ vốn tập trung, theo dõi tổng ký quỹ, ngăn chặn over-allocation giữa nhiều chiến lược chạy đồng thời. | Có | E3 |
| **FR-19** | `PortfolioEngine`: Chạy danh mục đa tài sản × đa chiến lược với giới hạn rủi ro danh mục (Max open positions, Max notional). | Có | E3 |
| **FR-20** | Tương thích và đối soát tương đương bit-for-bit với engine NautilusTrader (332/332 test cases khớp tuyệt đối). | Có | E16 |

### 5.4 Kiểm định & Tối ưu hóa (Validation & Optimization)
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-21** | Walk-Forward Analysis (WFA) đơn tài sản và danh mục: Chia các fold IS/OOS độc lập, chọn tham số trên IS, kiểm định trên OOS. | Có | E4 |
| **FR-22** | Monte Carlo Block Bootstrap: Mô phỏng phân phối lợi nhuận theo lệnh và theo chuỗi ngày NAV MTM với cùng seed. | Có | E4 |
| **FR-23** | Tính toán xác suất phá sản và Drawdown tối đa: $P(\text{MDD} \ge 30\%)$. | Có | E4 |
| **FR-24** | Kiểm định Out-of-Sample Holdout (20% dữ liệu cuối): Chỉ chạy một lần duy nhất với cấu hình đã chốt từ WFA. | Có | E4, E10 |
| **FR-25** | Tối ưu hóa đa tầng (Funnel Optimization): Sàng lọc nhanh Stage 1 $\rightarrow$ WFA Stage 2 $\rightarrow$ MC Stage 3 $\rightarrow$ Holdout Stage 4. | Có | E5 |
| **FR-26** | Xuất bản Alpha Registry (`data/alphas/registry.json`) và Book Config (`book.json`) kèm toàn bộ bằng chứng kiểm định. | Có | E5 |

### 5.5 Thực thi Live & Giám sát (Live Execution)
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-27** | Phân tầng môi trường Live rõ ràng thành 3 package độc lập: `live/paper`, `live/testnet`, `live/live`. | Có | E9, E17 |
| **FR-28** | Kết nối API sàn OKX v5 (REST + WebSocket) thực hiện đặt lệnh, hủy lệnh, đồng bộ vị thế và số dư. | Có | E9 |
| **FR-29** | Giám sát vị thế và hạch toán PnL real-time, đối soát trượt giá và phí giữa sàn thực tế và engine mô phỏng. | Có | E9 |
| **FR-30** | Kill Switch an toàn: Tự động đóng toàn bộ vị thế và hủy lệnh chờ khi drawdown danh mục vượt ngưỡng an toàn (ví dụ 30%). | Có | E9 |

### 5.6 API & Backend Services
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-31** | Backend module hóa thành 5 phân tầng: `backend.alpha`, `backend.core`, `backend.optimize`, `backend.live`, `backend.routes`. | Có | E17 |
| **FR-32** | Endpoint nguồn sự thật duy nhất cho Frontend: `GET /api/studio/meta` (cung cấp danh sách sàn, tài sản, chiến lược, chỉ số). | Có | E19 |
| **FR-33** | Background Job Runner: Quản lý các tác vụ nặng (Backtest, WFA, Build Book) qua tiến trình nền, cung cấp trạng thái `queued/running/done/failed`. | Có | E7 |
| **FR-34** | Quản lý Cache chuẩn: Không lưu cache disk vĩnh viễn không kiểm soát; chỉ giữ cache tiến trình đang chạy và dọn dẹp khi hoàn tất. | Có | E17 |
| **FR-35** | Endpoint xuất bản sổ chiến lược: `POST /api/studio/book/publish` có cơ chế xác nhận an toàn. | Có | E7 |

### 5.7 Giao diện Người dùng (Frontend UX/UI)
| ID | Yêu cầu chức năng | Trạng thái | Epic liên kết |
|---|---|---|---|
| **FR-36** | `MetaProvider` React Context: Tải metadata từ `/api/studio/meta` khi khởi động; toàn bộ UI tiêu thụ meta này, không hardcode. | Có | E19 |
| **FR-37** | Trang Portfolio: Hiển thị NAV MTM, Drawdown, Daily P&L, rolling Sharpe, bảng vị thế và sự kiện rủi ro. | Có | E8 |
| **FR-38** | Trang Backtest & Funnel: Cấu hình tài sản, chiến lược, chạy backtest và phân tích đường cong vốn trực quan. | Có | E8 |
| **FR-39** | Trang Alpha Lab: Quản lý kho Alpha, bảng xếp hạng các ứng viên, xem chi tiết bằng chứng WFA/MC. | Có | E8 |
| **FR-40** | Trang CreateAlpha & Education: Trình biên tập chiến lược tương tác, hiển thị code mẫu, chú thích lý thuyết và kết quả chạy thử. | Có | E18, E19 |
| **FR-41** | Thiết kế Responsive, Dark Theme tinh tế, nhất quán trên Desktop và Tablet. | Có | E19 |

---

## 6. Yêu cầu phi chức năng (Non-Functional Requirements - NFR)

| ID | Tiêu chí | Nội dung yêu cầu | Phương thức kiểm chứng |
|---|---|---|---|
| **NFR-1** | **Strictly Causal** | Không có bất kỳ rò rỉ tương lai nào trong tính toán kernel, resample nến, và thời điểm vào lệnh. | Bộ test causal: `test_kernel_is_causal_prefix_invariant`, `test_no_lookahead_*`. |
| **NFR-2** | **Tính Bất biến Vốn** | Vốn trên `CapitalLedger` luôn khớp từng xu với tổng realized PnL, unrealized PnL, phí và funding ở mọi nến. | `test_ledger_invariants_every_bar_random_multi_flow`. |
| **NFR-3** | **Tái lập Bit-identical** | Cùng dữ liệu + cùng tham số + cùng seed phải ra cùng từng bit float trong kết quả backtest và chỉ số. | `test/test_golden_results.py` (Golden bit-identical harness). |
| **NFR-4** | **Kiến trúc Phân tầng** | Tuân thủ tuyệt đối quy tắc phụ thuộc 1 chiều: `alpha → core → optimize → live → routes`. Không import ngược, không vòng lặp. | `test_p9_layering_strict.py`. |
| **NFR-5** | **Quản lý Bộ nhớ** | Toàn bộ ứng dụng Nora chạy trong giới hạn 12 GB RAM (`nora.slice`). Không sử dụng swap, tự động giải phóng bộ nhớ. | `ops/run_limited.sh`, cgroups limits. |
| **NFR-6** | **Tách biệt Core I/O** | `backend/core/` hoàn toàn là tính toán thuần túy (pure domain logic), không thực hiện bất kỳ thao tác I/O (file, network, DB). | Code review gate & unit test core không mock I/O. |
| **NFR-7** | **Độ trễ API** | Endpoint `/api/studio/meta` phản hồi dưới 100ms. Các job nặng phải trả về `job_id` trong vòng dưới 200ms. | Benchmark API request latency. |
| **NFR-8** | **Khả năng quan sát** | Mọi background job đều có file log riêng biệt (`job.json`, `out.log`), lưu thời gian chạy, CPU/RAM đỉnh và mã thoát. | Kiểm tra thư mục job execution log. |

---

## 7. Ràng buộc kỹ thuật (Technical Constraints)

1. **Môi trường máy chủ:** Linux (Ubuntu/Debian), Python 3.11 trong venv ghim cứng dependencies (`requirements.txt`).
2. **Cgroup Slice:** Mọi tiến trình chạy nặng bắt buộc khởi chạy qua `ops/run_limited.sh` nằm trong slice `nora.slice` (MemoryMax 12 GB, nice 10).
3. **Frontend Stack:** React 18, Vite, CSS Modules / Vanilla CSS hiện đại, không sử dụng thư viện UI cồng kềnh ngoài luồng.
4. **Quy tắc đặt tên:** Tránh tuyệt đối các từ khóa nhạy cảm bị tường lửa chặn (như "miner" $\rightarrow$ dùng "PhienDao").

---

## 8. Rủi ro và Biện pháp Giảm thiểu

| ID | Rủi ro | Tác động | Biện pháp giảm thiểu |
|---|---|---|---|
| **R-1** | Multiple Testing Overfitting | Tìm ra chiến lược có kết quả backtest tốt chỉ nhờ may mắn khi quét quá nhiều tham số. | Bổ sung Deflated Sharpe Ratio, Permutation test, và kiểm định trên Holdout data chưa từng dùng. |
| **R-2** | Regime Shift | Thị trường chuyển biến bất ngờ khiến chiến lược trend/reversal bị thua lỗ liên tiếp. | Giới hạn MDD bằng Portfolio Kill Switch (30%), áp dụng kiểm định độ bền lân cận tham số. |
| **R-3** | Trượt giá thực tế vượt giả định | Khớp lệnh live bị trượt giá nặng hơn 0.02% trong các đợt biến động mạnh. | Đối soát liên tục sai lệch trượt giá giữa sàn thật và engine; cảnh báo nếu vượt ngưỡng dự tính. |
| **R-4** | Tràn RAM máy chủ dùng chung | Job tối ưu hóa đa luồng tiêu tốn quá nhiều RAM gây sập máy chủ. | Cơ chế cấp phát worker động: $\min(\text{CPUs}, \text{RAM\_free} / \text{RAM\_worker})$ và giám sát cgroup. |

---

## 9. Danh sách Epics (E1 – E20)

Hệ thống được phát triển và quản trị theo 20 Epics chuẩn BMAD:

| Epic ID | Tên Epic | Mục tiêu & Phạm vi cốt lõi | FR liên kết |
|---|---|---|---|
| **E1** | Data Pipeline & Market Store | Thu thập, chuẩn hóa, lưu trữ dữ liệu nến 1m và funding rates Binance/OKX. | FR-1, FR-2, FR-3, FR-4, FR-5 |
| **E2** | Causal Signals & AST Strategy | 23+ kernel tín hiệu thuần nhân quả và bộ phân tích điều kiện chiến lược. | FR-7, FR-8, FR-12 |
| **E3** | Core Execution Engine | Động cơ khớp lệnh nến 1m, 2 pha, DCA, perp margin, funding, và CapitalLedger. | FR-13, FR-14, FR-15, FR-16, FR-17, FR-18, FR-19 |
| **E4** | Validation Harness | Bộ kiểm định định lượng: WFA đơn tài sản, WFA danh mục, Monte Carlo Bootstrap, Holdout. | FR-21, FR-22, FR-23, FR-24 |
| **E5** | Alpha & Strategy Book | Quy trình tối ưu đa tầng (Funnel) và đóng gói sổ chiến lược `book.json`. | FR-25, FR-26 |
| **E6** | Ops, Resource & Memory Limits | Quản trị tiến trình an toàn qua `ops/run_limited.sh`, cgroups slice, giám sát RAM. | NFR-5 |
| **E7** | Studio API Services | Hệ thống FastAPI router, Background Job Runner, API endpoints cho Studio. | FR-33, FR-34, FR-35 |
| **E8** | Frontend Application | Giao diện React v2: Trang Danh mục, Backtest, Funnel, Alpha Lab. | FR-37, FR-38, FR-39 |
| **E9** | Live Trading & Account Sync | Thực thi trên sàn OKX demo/live, đồng bộ vị thế, tài khoản, giám sát rủi ro real-time. | FR-28, FR-29, FR-30 |
| **E10** | Multiple Testing Correction & Robustness | Hiệu chỉnh đa kiểm định (Deflated Sharpe), kiểm định độ bền tham số và kiểm tra null. | R-1, FR-24 |
| **E11** | System Hardening & Security | Bảo mật API, kiểm soát phân quyền mạng, chuẩn hóa dữ liệu gate toàn hệ thống. | FR-5, NFR-7 |
| **E12** | Advanced Portfolio Sizing | Thuật toán phân bổ vốn động, tối ưu hóa danh mục theo tỷ lệ rủi ro (Risk-Parity). | FR-19 |
| **E13** | Execution Analytics & Reporting | Báo cáo hiệu suất giao dịch chi tiết, phân tích drawdown thời gian thực, export PDF/HTML. | FR-37 |
| **E14** | Dynamic Market Regime Detection | Bộ lọc chế độ thị trường (Trending vs Ranging) hỗ trợ bật/tắt chiến lược tự động. | FR-7, FR-11 |
| **E15** | Cross-Venue Parity Engine | Chuẩn hóa quy tắc khớp lệnh và phí giữa Binance Futures và OKX Perpetuals. | FR-15 |
| **E16** | Single Engine Parity (Nautilus Parity) | Hợp nhất single engine, đạt 332/332 test cases tương đương từng bit với NautilusTrader. | FR-20, NFR-3 |
| **E17** | Backend & Data Restructuring (P9) | Tái cấu trúc 5 phân tầng sạch sẽ, cây dữ liệu một nguồn `data/market/`, dọn dẹp cache. | FR-2, FR-3, FR-6, FR-31, FR-34, NFR-4, NFR-6 |
| **E18** | Strategy Contract & Studio Editor (P10) | Hợp đồng chiến lược thống nhất `BaseStrategy`, Alpha Validator RUN/ADAPT/REJECT, 50+ mẫu. | FR-9, FR-10, FR-11, FR-40 |
| **E19** | UI Single Source of Truth & Responsive (P11) | Metadata tập trung `/api/studio/meta`, `MetaProvider`, đồng bộ UI hoàn chỉnh, Responsive. | FR-32, FR-36, FR-41 |
| **E20** | Causal Signal Timing & Order Lifecycle (P12) | Kiểm soát chu kỳ lệnh nghiêm ngặt, tín hiệu bar $t$ thực thi tại open $t+1$, chống lookahead. | FR-8, FR-13, NFR-1 |
