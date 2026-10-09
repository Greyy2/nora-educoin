# Epic và story

Cập nhật: 2026-10-06 · Baseline code: `dc2032c` (nhánh `fix/pipeline-audit`). Yêu cầu: [prd.md](prd.md); kiến trúc: [architecture.md](architecture.md); trạng thái máy đọc: [sprint-status.yaml](sprint-status.yaml).

Trạng thái: `backlog` (chưa làm) · `ready` (đủ điều kiện làm) · `in-progress` · `review` · `done`. Mỗi story có một file trong [stories/](stories/).

## Bảng tổng

| Epic | Tên | Trạng thái | Story (done / tổng) | Ghi chú |
|---|---|---|---|---|
| E1 | Dữ liệu thị trường | done | 6 / 6 | Khoảng trống: gate chưa chặn đường danh mục (E11-S6). |
| E2 | Tín hiệu & chiến lược | done | 5 / 5 | - |
| E3 | Engine backtest, vốn & rủi ro | done | 8 / 8 | - |
| E4 | Kiểm chứng WFA / Monte Carlo / holdout | done | 6 / 6 | Chưa có hiệu chỉnh đa kiểm định (E10). |
| E5 | Alpha & sổ chiến lược | done | 5 / 5 | Epic hoàn thành về mặt tính năng; kết quả nghiên cứu: một alpha đạt, sổ chưa đạt (R-1 đến R-4). |
| E6 | Hạ tầng vận hành & bộ nhớ | done | 6 / 6 | - |
| E7 | Studio API | done | 7 / 7 | Chưa có xác thực (E11). |
| E8 | UI v2 | in-progress | 6 / 7 | Còn E8-S7 (test tự động frontend). |
| E9 | Testnet & Live | in-progress | 4 / 7 | Bot OKX demo chạy từ 04/10/2026; đối soát sàn ↔ paper có (S6 review, chờ ≥ 30 cặp lệnh). Chưa vốn thật (S4). |
| E10 | Nghiên cứu chiến lược mới & phương pháp | backlog | 0 / 6 | Giải quyết R-1 đến R-4. |
| E11 | Bảo mật & phát hành | backlog | 0 / 7 | Giải quyết R-5, R-7, R-9. |
| E12 | Tốc độ (500k alpha ≤ 4 h) | done | 3 / 3 | 15m: 80 alpha/s (500k ≈ 1,7 h); 1h: 103 alpha/s. |
| E13 | Hai chế độ chạy Cơ bản / Nâng cao | done | 2 / 2 | 5/7 preset stage A chưa qua dev2 (ghi nhãn). |
| E14 | Phễu kiểm duyệt alpha | done | 3 / 3 | Lượt thật 36.000 alpha → 0 FINAL; alpha SOL bị loại khi kiểm lại. |
| E15 | Regime và điều phối chiến lược | done | 6 / 6 | Bảng tĩnh không khớp dữ liệu; học trên train cải thiện nhưng WFA chưa qua. |
| E16 | Kiến trúc thực thi thống nhất (backtest → testnet → live) | in-progress | 9 / 10 | P6.0–P6.7, P6.10–P6.12 xong; P6.8 demo bot đang chạy đo dung sai. |
| E17 | Tái cấu trúc backend + dữ liệu (P9) | done | 4 / 4 | Phân tầng 5 lớp sạch sẽ, cây dữ liệu một nguồn data/market, scoped process cache. |
| E18 | Alpha contract + Studio Editor (P10) | done | 4 / 4 | Hợp đồng BaseStrategy, Validator RUN/ADAPT/REJECT, 50+ chiến lược mẫu, Studio Editor web. |
| E19 | UI nguồn sự thật duy nhất + responsive (P11) | done | 4 / 4 | MetaProvider (/api/studio/meta), đồng bộ dropdown/pages, Dark theme responsive. |
| E20 | Signal timing & Causal execution (P12) | done | 3 / 3 | Tín hiệu bar t khớp tại open bar t+1, hạch toán 2 pha, bộ test causal bit-identical. |

Tổng: 20 epic (15 done, 3 in-progress, 2 backlog); 109 story (91 done, 1 in-progress, 2 review, 0 ready, 15 backlog).

Epic E5 mang trạng thái `done` về mặt tính năng. Kết quả nghiên cứu là: alpha `trend_long_perp__SOL` từng hợp lệ nhưng bị loại khi kiểm lại bằng engine hiện hành (E14-S3, 03/10/2026); sổ `breakout_4h_long + breakout_4h_short` ở trạng thái `HOLDOUT_FAILED`, không có cấu hình testnet cho sổ. Việc tìm sổ qua holdout nằm ở E10.

## E1: Dữ liệu thị trường [done]

Có dữ liệu Binance spot/perp 3 năm có checksum, bố cục theo venue, resample causal và quality gate.

Yêu cầu liên quan: FR-1 đến FR-6.

Ghi chú: Khoảng trống: gate chưa chặn đường danh mục (E11-S6).

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E1-S1](stories/E1-S1-crawl-binance-klines.md) | Crawl nến Binance spot/perp và funding có checksum | done |
| [E1-S2](stories/E1-S2-data-layout-manifest.md) | Bố cục dữ liệu theo venue, ký hiệu @perp và manifest | done |
| [E1-S3](stories/E1-S3-causal-resampler.md) | Resample causal từ 1m, idempotent | done |
| [E1-S4](stories/E1-S4-data-quality-gate.md) | Quality gate dữ liệu và nơi gate được gọi | done |
| [E1-S5](stories/E1-S5-promote-staging.md) | Chuyển dữ liệu từ staging sang data/ chỉ khi qua gate | done |
| [E1-S6](stories/E1-S6-dex-data-pipeline.md) | Dữ liệu DEX (pool AMM) và chính sách tick | done |

## E2: Tín hiệu & chiến lược [done]

23 kernel causal, căn khung đa khung không nhìn trước, AST, thư viện chiến lược và 7 ứng viên sổ.

Yêu cầu liên quan: FR-7 đến FR-12.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E2-S1](stories/E2-S1-causal-kernels.md) | 23 kernel thuần, causal và bất biến theo tiền tố | done |
| [E2-S2](stories/E2-S2-multi-frame-alignment-ast.md) | Căn khung đa khung (avail_time) và bộ đánh giá AST | done |
| [E2-S3](stories/E2-S3-signal-diagnostics.md) | Kiểm tra tín hiệu có mang thông tin trước khi ghép chiến lược | done |
| [E2-S4](stories/E2-S4-strategy-library-templates.md) | Thư viện tín hiệu, chiến lược mẫu, không gian tối ưu và tham số tín hiệu | done |
| [E2-S5](stories/E2-S5-strategy-book-candidates.md) | Bảy ứng viên sổ chiến lược dùng chung tham số toàn vũ trụ | done |

## E3: Engine backtest, vốn & rủi ro [done]

Engine 1m bi quan có DCA, perp, thanh lý, funding, sổ vốn chung, danh mục có giới hạn, bit-identical.

Yêu cầu liên quan: FR-13 đến FR-24.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E3-S1](stories/E3-S1-intrabar-execution.md) | Khớp lệnh trong nến: phía bất lợi trước, gap, TP không cùng nến DCA | done |
| [E3-S2](stories/E3-S2-fees-funding-liquidation.md) | Phí taker/maker theo venue, funding và thanh lý perp | done |
| [E3-S3](stories/E3-S3-capital-ledger.md) | Sổ vốn chung (CapitalLedger) | done |
| [E3-S4](stories/E3-S4-dca-budget-cooldown.md) | Ngân sách DCA, cooldown và loại tổ hợp không hợp lệ | done |
| [E3-S5](stories/E3-S5-atr-exits-risk-sizing.md) | Thoát theo ATR và khối lượng theo rủi ro, trần đòn bẩy 1,5 × SL | done |
| [E3-S6](stories/E3-S6-portfolio-engine-risk-limits.md) | PortfolioEngine: nhiều tài sản trên một sổ vốn, RiskConfig và kill switch | done |
| [E3-S7](stories/E3-S7-shared-mmap-skip-idle.md) | Dữ liệu dùng chung qua mmap và bỏ qua phút rảnh (bit-identical) | done |
| [E3-S8](stories/E3-S8-golden-harness.md) | Golden harness: snapshot bit-identical của engine | done |

## E4: Kiểm chứng WFA / Monte Carlo / holdout [done]

WFA đơn tài sản và danh mục, Monte Carlo theo lệnh và theo ngày MTM, holdout, kiểm độ bền, kiểm null.

Yêu cầu liên quan: FR-25 đến FR-31.

Ghi chú: Chưa có hiệu chỉnh đa kiểm định (E10).

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E4-S1](stories/E4-S1-wfa-single-asset.md) | Walk-forward đơn tài sản: fold, gate, NO_TRADE | done |
| [E4-S2](stories/E4-S2-wfa-portfolio.md) | Walk-forward danh mục với IS chọn lại và OOS chung vốn | done |
| [E4-S3](stories/E4-S3-monte-carlo-trade-daily.md) | Monte Carlo theo lệnh và theo lợi suất ngày MTM | done |
| [E4-S4](stories/E4-S4-holdout-optimize-alphas.md) | Quy trình tối ưu trung thực: dev1, WFA dev2, MC, holdout | done |
| [E4-S5](stories/E4-S5-robustness-stopfill-sizing.md) | Kiểm độ bền, SL khớp bi quan và hệ số vốn theo ngân sách rủi ro | done |
| [E4-S6](stories/E4-S6-null-falsification-research.md) | Kiểm null và bài học nghiên cứu: edge giả của bộ quét limit | done |

## E5: Alpha & sổ chiến lược [done]

Kho alpha, quy trình dựng sổ A-D, quy tắc xuất testnet. Kết quả: alpha SOL hợp lệ; sổ `breakout_4h_*` HOLDOUT_FAILED.

Yêu cầu liên quan: FR-33 đến FR-37.

Ghi chú: Epic hoàn thành về mặt tính năng; kết quả nghiên cứu: một alpha đạt, sổ chưa đạt (R-1 đến R-4).

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E5-S1](stories/E5-S1-alpha-registry-testnet-config.md) | Kho alpha và cấu hình Binance Futures testnet cho alpha perp | done |
| [E5-S2](stories/E5-S2-alpha-sol-validated.md) | Alpha trend_long_perp__SOL: kiểm lại và ghi nhận | done |
| [E5-S3](stories/E5-S3-build-strategy-book-stages.md) | Dựng sổ chiến lược: giai đoạn A dev1, B dev2, C sổ, D holdout | done |
| [E5-S4](stories/E5-S4-book-export-holdout-rule.md) | Xuất sổ: trạng thái READY_FOR_TESTNET / HOLDOUT_FAILED và quy tắc không có testnet khi trượt holdout | done |
| [E5-S5](stories/E5-S5-first-book-run-holdout-failed.md) | Sổ breakout_4h đầu tiên trên dữ liệu thật: HOLDOUT_FAILED | done |

## E6: Hạ tầng vận hành & bộ nhớ [done]

Sửa OOM, `nora.slice` 12G, hàng đợi flock, auto workers, bố cục package, smoke check.

Yêu cầu liên quan: FR-38 đến FR-43.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E6-S1](stories/E6-S1-oom-root-cause-bounded-caches.md) | Nguyên nhân OOM và cache giới hạn theo byte | done |
| [E6-S2](stories/E6-S2-cgroup-guard-run-limited.md) | Bắt buộc trần RAM cgroup cho script nặng (run_limited) | done |
| [E6-S3](stories/E6-S3-nora-slice-queue-systemd.md) | nora.slice 12G, hàng đợi flock và unit systemd | done |
| [E6-S4](stories/E6-S4-parallel-auto-workers-pool-safe.md) | Module song song dùng chung: auto workers và pool chịu OOM | done |
| [E6-S5](stories/E6-S5-package-layout-environment.md) | Bố cục package gọn và môi trường tái lập | done |
| [E6-S6](stories/E6-S6-smoke-check-ref-check.md) | Smoke check bất biến và đối chiếu test với phiên bản cũ | done |

## E7: Studio API [done]

Job nền cho backtest/WFA/build, Monte Carlo đồng bộ, publish, dashboard Danh mục, feed giả lập.

Yêu cầu liên quan: FR-44 đến FR-50.

Ghi chú: Chưa có xác thực (E11).

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E7-S1](stories/E7-S1-book-jobs-api.md) | API sổ chiến lược: backtest, WFA, build chạy nền | done |
| [E7-S2](stories/E7-S2-job-argument-safety-limits.md) | Đối số job kiểm chặt, giới hạn và khôi phục trạng thái | done |
| [E7-S3](stories/E7-S3-monte-carlo-endpoint.md) | Endpoint Monte Carlo ngày đồng bộ | done |
| [E7-S4](stories/E7-S4-book-build-publish.md) | Build không ghi đè sổ đang xuất bản; publish có kiểm soát | done |
| [E7-S5](stories/E7-S5-portfolio-dashboard-endpoint.md) | Endpoint dashboard Danh mục | done |
| [E7-S6](stories/E7-S6-mock-feeds-live-testnet.md) | Feed Live/Testnet giả lập thay cho tài khoản chưa nối | done |
| [E7-S7](stories/E7-S7-catalog-alphas-studio-compat.md) | Danh mục chiến lược, kho alpha và tương thích API Studio cũ | done |

## E8: UI v2 [in-progress]

Danh mục, Backtest/WFA/Monte Carlo, Alpha, Sáng/Tối; đang cải thiện UX.

Yêu cầu liên quan: FR-51 đến FR-56.

Ghi chú: E8-S6 đã xong (commit 8a96b4e); còn E8-S7.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E8-S1](stories/E8-S1-v2-shell-theme-routing.md) | Khung UI v2: thanh bên, định tuyến, chủ đề Sáng/Tối, tương thích trình duyệt | done |
| [E8-S2](stories/E8-S2-portfolio-page.md) | Trang Danh mục | done |
| [E8-S3](stories/E8-S3-backtest-wfa-mc-loop.md) | Trang Backtest → WFA → Monte Carlo trong một vòng | done |
| [E8-S4](stories/E8-S4-alpha-tuning-publish.md) | Trang Alpha: hiệu chỉnh tham số, gửi sang Backtest, xuất bản sổ | done |
| [E8-S5](stories/E8-S5-portfolio-sources-mock-banner.md) | Nguồn Live | Testnet | Backtest và banner giả lập | done |
| [E8-S6](stories/E8-S6-ux-improvements.md) | Cải thiện trải nghiệm UI v2 | done |
| [E8-S7](stories/E8-S7-frontend-automated-tests.md) | Kiểm thử tự động cho frontend | backlog |

## E9: Testnet & Live [in-progress]

Bot OKX (paper / demo / live), trang Live đọc tài khoản thật, kill switch live, đối soát sàn ↔ paper.

Yêu cầu liên quan: FR-57 đến FR-60.

Ghi chú: sàn triển khai là OKX (Binance chỉ tham khảo). Demo chạy qua API runner; khoá ở `~/.config/nora/okx.env`.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E9-S1](stories/E9-S1-testnet-bot-executor.md) | Bot Binance Futures testnet chạy đúng quy tắc đã mô phỏng | done |
| [E9-S2](stories/E9-S2-exchange-filters-order-rules.md) | Bộ lọc sàn: tickSize, stepSize, minNotional và quy tắc lệnh | done |
| [E9-S3](stories/E9-S3-testnet-feed.md) | TestnetFeed thật thay feed giả lập | done |
| [E9-S4](stories/E9-S4-live-feed.md) | LiveFeed thật cho tài khoản Binance Futures | backlog |
| [E9-S5](stories/E9-S5-live-kill-switch-risk-limits.md) | Kill switch và giới hạn rủi ro trên tài khoản thật | review |
| [E9-S6](stories/E9-S6-live-backtest-reconciliation.md) | Đối soát live/testnet với backtest | review |
| [E9-S7](stories/E9-S7-exchange-secrets-management.md) | Quản lý khoá API sàn | done |

## E10: Nghiên cứu chiến lược mới & phương pháp [backlog]

Deflated Sharpe, permutation test, chính sách holdout, họ chiến lược mới, giải thích edge SOL.

Yêu cầu liên quan: FR-30 (cổng bắt buộc), FR-32.

Ghi chú: Giải quyết R-1 đến R-4.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E10-S1](stories/E10-S1-deflated-sharpe-ratio.md) | Deflated Sharpe Ratio cho alpha và sổ | backlog |
| [E10-S2](stories/E10-S2-permutation-test.md) | Permutation test cho chiến lược | backlog |
| [E10-S3](stories/E10-S3-holdout-reuse-policy.md) | Chính sách dùng lại holdout và holdout tiến tới (forward) | backlog |
| [E10-S4](stories/E10-S4-new-strategy-families.md) | Nghiên cứu họ chiến lược mới để có sổ qua holdout | backlog |
| [E10-S5](stories/E10-S5-sol-edge-explanation.md) | Giải thích và kiểm edge riêng của SOL | backlog |
| [E10-S6](stories/E10-S6-trial-ledger-multiple-testing.md) | Sổ thử nghiệm: đếm mọi cấu hình đã thử | backlog |

## E11: Bảo mật & phát hành [backlog]

Bind localhost hoặc nginx + basic auth, CORS, tách bundle, dọn legacy, gate dữ liệu cho sổ, quy trình phát hành.

Yêu cầu liên quan: NFR-6, NFR-9, NFR-10, FR-5.

Ghi chú: Giải quyết R-5, R-7, R-9.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E11-S1](stories/E11-S1-api-bind-localhost.md) | API chỉ nghe localhost theo mặc định | backlog |
| [E11-S2](stories/E11-S2-nginx-domain-basic-auth.md) | Truy cập từ xa qua nginx: domain, TLS và basic auth | backlog |
| [E11-S3](stories/E11-S3-cors-restriction.md) | Giới hạn CORS | backlog |
| [E11-S4](stories/E11-S4-frontend-bundle-split.md) | Tách bundle frontend (lazy route) | backlog |
| [E11-S5](stories/E11-S5-legacy-cleanup.md) | Dọn legacy: route MySQL cũ, trang Legacy, mã nghiên cứu DEX | backlog |
| [E11-S6](stories/E11-S6-gate-on-book-path.md) | Gate dữ liệu trên đường danh mục/sổ | backlog |
| [E11-S7](stories/E11-S7-release-process.md) | Quy trình phát hành và tài liệu | backlog |

## E12: Tốc độ (500k alpha ≤ 4 h) [done]

Engine numba, kho dữ liệu dùng chung, khung chạy 15m/1h/4h (roadmap P1).

Ghi chú: Golden trùng bit qua mọi bước; P1.7 (lọc thô nhiều vòng) đo và quyết định không làm.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E12-S1](stories/E12-S1-numba-kernel-fast-forward.md) | Kernel numba + tua nhanh phút yên lặng | done |
| [E12-S2](stories/E12-S2-shared-column-store.md) | Kho dữ liệu dùng chung mức cột/khung + điền lười | done |
| [E12-S3](stories/E12-S3-run-timeframe.md) | Khung chạy 15m / 1h / 4h chọn trước khi sinh tham số | done |

## E13: Hai chế độ chạy Cơ bản / Nâng cao [done]

Preset khoá tham số ở Cơ bản; Nâng cao sửa từng tham số, gate khác chuẩn → custom_gates (roadmap P0.3, P4.1, P0.3c).

Ghi chú: Preset stage A chưa qua dev2 được gắn nhãn rõ trên UI.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E13-S1](stories/E13-S1-basic-advanced-modes.md) | Chế độ Cơ bản / Nâng cao cho Backtest, WFA, Monte Carlo | done |
| [E13-S2](stories/E13-S2-presets-timeframe-dev2.md) | Preset ghi khung tối ưu, ưu tiên nguồn qua dev2 | done |

## E14: Phễu kiểm duyệt alpha [done]

S0 → FINAL với DSR/PBO/lân cận, WFA, MC, sizing, holdout (roadmap P0.2, P3).

Ghi chú: Chưa có alpha/sổ nào đủ điều kiện testnet; tìm edge mới thuộc E10.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E14-S1](stories/E14-S1-funnel-s0-final.md) | Phễu S0 → FINAL | done |
| [E14-S2](stories/E14-S2-funnel-real-run-9-strategies.md) | Chạy phễu thật 9 chiến lược có regime | done |
| [E14-S3](stories/E14-S3-alpha-sol-revalidate-testnet.md) | Kiểm lại alpha SOL; registry + testnet đúng trạng thái | done |

## E15: Regime và điều phối chiến lược [done]

Regime causal đa khung, báo cáo độ chuẩn, học bảng regime trên train, stress trend thẳng đứng, UI (roadmap P2, P4.3).

Ghi chú: Kết quả trung thực: regime chưa tạo được sổ qua WFA (E15-S3).

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E15-S1](stories/E15-S1-regime-spec.md) | Đặc tả regime | done |
| [E15-S2](stories/E15-S2-regime-report-real-data.md) | Báo cáo độ chuẩn trên 8 tài sản thật | done |
| [E15-S3](stories/E15-S3-regime-learn-wfa.md) | WFA học bảng regime chỉ trên train | done |
| [E15-S4](stories/E15-S4-vertical-trend-stress.md) | Monte Carlo: kịch bản trend thẳng đứng | done |
| [E15-S5](stories/E15-S5-regime-trials-dsr-pbo.md) | Biến thể regime là lần thử trong DSR/PBO | done |
| [E15-S6](stories/E15-S6-regime-ui.md) | Hiển thị regime hiện tại, lịch sử, chiến lược đang bật | done |

## E16: Kiến trúc thực thi thống nhất [in-progress]

Một giao diện sàn (`Venue`) cho sim và OKX, một risk engine, kế toán vị thế theo sự kiện, policy vị thế viết một lần (roadmap P6, ADR-P6). Sim bit-identical với kernel; sim ↔ sàn trong dung sai.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E16-S1](stories/E16-S1-adr-unified-execution.md) | ADR kiến trúc thực thi thống nhất (P6.0) | done |
| [E16-S2](stories/E16-S2-risk-engine.md) | Risk engine độc lập (P6.1) | done |
| [E16-S3](stories/E16-S3-policy-functions.md) | Hàm thuần chính sách vị thế (P6.2) | done |
| [E16-S4](stories/E16-S4-events-and-account.md) | Kế toán vị thế theo sự kiện (P6.3) | done |
| [E16-S5](stories/E16-S5-venue-and-manager.md) | Giao diện Venue, SimVenue và PositionManager (P6.4) | done |
| [E16-S6](stories/E16-S6-runner-and-paperbook.md) | Runner điều phối và PaperBook trên SimVenue (P6.5) | done |
| [E16-S7](stories/E16-S7-venue-conformance.md) | Bộ kiểm thử hợp đồng Venue (P6.6) | done |
| [E16-S8](stories/E16-S8-okx-venue.md) | Adapter OkxVenue (P6.7) | done |
| [E16-S9](stories/E16-S9-unified-bot.md) | Bot chạy trên lõi thống nhất (P6.8) | in-progress |
| [E16-S10](stories/E16-S10-nautilus-parity-and-two-phase.md) | Đối chiếu chuẩn NautilusTrader & Nến hai pha (P6.10–P6.12) | done |

## E17: Tái cấu trúc backend + dữ liệu (P9) [done]

Phân tầng 5 lớp backend độc lập `alpha → core → optimize → live → routes`, cây dữ liệu một nguồn `data/market/` kèm metadata attrs, xoá dead code và quản lý scoped cache.

Yêu cầu liên quan: FR-2, FR-3, FR-6, FR-31, FR-34, NFR-4, NFR-6.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E17-S1](stories/E17-S1-backend-layering.md) | Phân tầng 5 lớp backend alpha -> core -> optimize -> live -> routes | done |
| [E17-S2](stories/E17-S2-market-data-store.md) | Cấu trúc cây dữ liệu thống nhất và metadata attrs | done |
| [E17-S3](stories/E17-S3-scoped-process-cache.md) | Cơ chế cache tiến trình scoped và dọn dẹp bộ nhớ tạm | done |
| [E17-S4](stories/E17-S4-cleanup-source-tree.md) | Loại bỏ module cũ, dead code và đồng bộ source-tree.md | done |

## E18: Alpha contract + Studio Editor (P10) [done]

Chuẩn hoá Strategy Contract `BaseStrategy` (`evaluate(candles) -> signals`), Validator phân loại RUN / ADAPT / REJECT, 50+ chiến lược mẫu kèm docstrings tiếng Anh, tích hợp Studio Editor và Education mode trên web.

Yêu cầu liên quan: FR-9, FR-10, FR-11, FR-40.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E18-S1](stories/E18-S1-strategy-contract-base.md) | Chuẩn hoá Strategy Contract BaseStrategy | done |
| [E18-S2](stories/E18-S2-alpha-validator-contract.md) | Trình xác thực Alpha Validator RUN ADAPT REJECT | done |
| [E18-S3](stories/E18-S3-sample-strategies-library.md) | Thư viện 50+ chiến lược mẫu kèm docstrings tiếng Anh | done |
| [E18-S4](stories/E18-S4-studio-editor-and-education-ui.md) | Tích hợp Studio Editor và trang Education trên giao diện web | done |

## E19: UI nguồn sự thật duy nhất + responsive (P11) [done]

Endpoint `/api/studio/meta` cung cấp danh mục động, `MetaProvider` React Context, đồng bộ toàn bộ dropdown trang UI, thiết kế Dark theme và Responsive.

Yêu cầu liên quan: FR-32, FR-36, FR-41.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E19-S1](stories/E19-S1-studio-meta-endpoint.md) | Endpoint API metadata tập trung /api/studio/meta | done |
| [E19-S2](stories/E19-S2-meta-provider-context.md) | MetaProvider React Context nạp và phân phối metadata | done |
| [E19-S3](stories/E19-S3-ui-sync-with-meta.md) | Đồng bộ toàn bộ các trang UI với MetaProvider | done |
| [E19-S4](stories/E19-S4-responsive-dark-theme.md) | Thiết kế Responsive và hoàn thiện Dark theme | done |

## E20: Signal timing & Causal execution (P12) [done]

Tín hiệu bar $t$ khớp tại open bar $t+1$, hạch toán vòng đời lệnh 2 pha bi quan, loại bỏ lookahead bias, bộ test kiểm định strictly causal bit-identical.

Yêu cầu liên quan: FR-8, FR-13, NFR-1.

| Story | Tiêu đề | Trạng thái |
|---|---|---|
| [E20-S1](stories/E20-S1-causal-signal-execution-open.md) | Thực thi tín hiệu tại open nến t+1 sau khi nến t đã đóng | done |
| [E20-S2](stories/E20-S2-two-phase-order-lifecycle.md) | Hạch toán vòng đời lệnh hai pha không rò rỉ dữ liệu | done |
| [E20-S3](stories/E20-S3-causal-timing-tests.md) | Bộ test kiểm định causal signal timing bit-identical | done |

