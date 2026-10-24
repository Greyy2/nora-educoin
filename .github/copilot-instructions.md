# NORA BT — PROJECT CONTEXT & WORK STATUS

> **Mục tiêu:** Vận hành hai sản phẩm NoraBT độc lập:
> 1. **EDU (Educational Backtest & Alpha Studio):** Quản lý DSL, phân tích chiến lược, giả lập backtest trên nến BTC/crypto.
> 2. **COIN (Testnet/Trading):** Bot giao dịch và các dịch vụ production.

## Trạng thái đã hoàn thành
- Tách mã nguồn, backend/frontend, data roots và dịch vụ EDU/COIN; kiểm tra import isolation không phát hiện cross-import.
- EDU có API backtest/jobs; job nặng được giới hạn RAM 2 GB. Auth token có audience riêng cho EDU và COIN.
- Public cutover đã được xác minh ngày **2026-10-23 khoảng 05:00 UTC**:
  - `https://coin.expsolution.io` phục vụ UI và API health `product=coin`.
  - `https://edu.expsolution.io` phục vụ UI và API health `product=edu`.
  - `./nora/check/check.sh` đạt **19/19 PASS**, gồm service, routing, RubiLab và test EDU/COIN.
- Apex UI legacy trả 410 có chủ đích; legacy API/service vẫn được giữ làm fallback. Cutover hoàn tất, nhưng việc retire legacy chưa được nghiệm thu.

## Việc đang theo dõi và công việc tiếp theo
### Soak sau cutover
- Bắt đầu soak 48 giờ từ lần public verification khoảng **2026-10-23 05:00 UTC**; mốc kiểm tra lại khoảng **2026-10-25 05:00 UTC**.
- Trong soak, theo dõi health, lỗi API/UI, Nginx/service logs và xác nhận DNS/HTTPS vẫn định tuyến đúng.
- Giữ legacy fallback. Chỉ đánh giá retire sau khi đủ soak, chạy lại checker, kiểm kê phụ thuộc/backup/rollback và có xác nhận của owner. Không tự tuyên bố retire trước các gate này.

### Workstream đã kiểm chứng: proof tính toán theo fixture
- **Đã triển khai và kiểm thử proof run end-to-end** trong một notebook duy nhất: [nora/check/calculation_audit.ipynb](../nora/check/calculation_audit.ipynb). Notebook chạy fixture 25 bars qua production PortfolioEngine của COIN và EDU, không tự dựng execution/fill.
- **Kết quả lần kiểm thử mới nhất:** cả 8 code cells chạy sạch; 9/9 reconciliation nhóm PASS. COIN: SMA crossover + TP, 2 production fills, independent fill-ledger PnL/equity khớp và 11/11 metric checks PASS. EDU: QuickRsi DSL target khớp RSI oracle, 2 production fills, PnL/equity khớp và 6/6 metric checks PASS.
- Oracle tính indicator, signal kỳ vọng, PnL, return và drawdown độc lập; dùng giá/qty/fee thực tế từ fill records để tính ledger. Fill timing, phí 0.05%, zero funding/slippage, tolerance và RSI/Nautilus convention được nêu trong notebook.
- **Phạm vi bằng chứng còn hẹp:** một fixture và một strategy/config đại diện cho mỗi sản phẩm. Chưa chứng minh mọi strategy, mọi edge case, short/multi-position, funding/slippage khác 0, live execution, hay sẵn sàng giao dịch vốn thật. Không tuyên bố parity RSI tuyệt đối với Nautilus.
- Giữ một notebook là deliverable; các bảng evidence và PASS/FAIL nằm trong notebook, không tạo workbook/checker rời theo mặc định.
- Việc tiếp theo nếu mở rộng correctness proof: thêm fixture nhỏ có thể tính tay cho phí/funding/slippage, short, nhiều trade và edge cases; chốt expected behavior trước khi thêm; chạy regression riêng. Không trộn benchmark hiệu năng vào correctness gate.
- Tách riêng trạng thái này khỏi cutover/soak: test notebook PASS không chứng minh DNS/public deployment hay hoàn tất soak/retire legacy.

### Workstream tiếp theo: kiểm tra logic và vận hành sau khi tách COIN/EDU
Mục tiêu là xác nhận **mỗi sản phẩm vẫn hoạt động đúng độc lập từ frontend tới backend/data/job/engine**, đồng thời không rò rỉ trạng thái hay ảnh hưởng chéo. Theo dõi todo chi tiết có dependency trong session; các phase chính:

#### Findings đã xác minh ngày 2026-10-23
- **Không thấy lỗi ở các gate runtime đã chạy:** trước khi có source changes, `./nora/check/check.sh` đạt **19/19 PASS**. Sau thay đổi dưới đây, backend services/public health và product test suites tiếp tục PASS; full checker chỉ báo dirty-worktree gate vì các source changes chưa commit.
- **ĐÃ SỬA — COIN build scripts:** [nora/coin/frontend/package.json](../nora/coin/frontend/package.json) dùng `vite.config.js` cho COIN và delegate EDU build sang `nora/edu/frontend`; `npm run build:all` đã build thành công cả hai output.
- **ĐÃ SỬA — COIN `api:check`:** đã thêm `scripts/checkApi.mjs`; gate hiện kiểm tra 142 static API helper path prefixes có route trong ít nhất một OpenAPI schema COIN/EDU. Đây là **route-existence check**, không thay thế kiểm tra method/request-response/auth.
- **ĐÃ SỬA — COIN dev proxy:** [nora/coin/frontend/vite.config.js](../nora/coin/frontend/vite.config.js) proxy API/charts/WebSocket về port COIN `18012`, không còn trỏ legacy `18010`.
- **ĐÃ BỔ SUNG — COIN regression:** [nora/coin/tests/test_coin_app.py](../nora/coin/tests/test_coin_app.py) hiện có 13 test cho routes/data root, build command/entrypoint, proxy, health product identity, token audience, risk/exposure/drawdown/kill-switch, job input allowlist, custom-backtest API, trade-metrics oracle, regime API categorical contract và resource limits. API regression xác minh input sai trả 422 và không launch; input hợp lệ gọi launch boundary; cancel kiểm tra job không tồn tại và ID sai mà không gửi tín hiệu tiến trình.
- **COVERAGE GAP CÒN LẠI — COIN:** một custom backtest thật qua API→worker đã chạy thành công ngày 2026-10-24, status `done`, log `peak RAM 271 MB / limit 4G`; đây là smoke run, chưa thay thế regression lặp lại cho status/failure/cancel/ownership/recovery. Chưa phủ full backtest accounting matrix, exchange adapter partial/reject/cancel trên stub/testnet, UI browser journeys và request/response/auth contract đầy đủ.
- **PASS có lưu ý — EDU frontend:** `npm run build` thành công; Vite cảnh báo một số chunk >500 kB. Chưa có đo UX/performance hoặc gate kích thước; ghi nhận như follow-up, không xem là build failure.
- Lệnh npm phải chạy từ frontend product root (hoặc qua `npm --prefix ...`); chạy ở repository root báo thiếu `package.json` là **sai working directory**, không tính là lỗi riêng của sản phẩm.
- **ĐÃ SỬA — RAM cap cho backtest:** `nora/coin/ops/run_limited.sh` mặc định giới hạn mỗi scope job ở 4G; EDU tiếp tục giới hạn ở 2G. Cả hai dùng `MemorySwapMax=0`; slice Nora trên máy hiện tại giới hạn tổng ở 10G (`MemoryHigh=9G`), service COIN 4G và EDU 2G. Trước đó COIN wrapper không đặt trần riêng, chỉ dựa vào tổng slice.
- **ĐÃ SỬA — Tính ngân sách cgroup hiệu lực:** resource helper trước đây ưu tiên `NORA_SLICE_CG`, có thể trả giới hạn cha 10G thay cho cap scope thấp hơn (ví dụ EDU 2G), khiến ước lượng worker cao hơn ngân sách job. COIN và EDU giờ chọn giới hạn nhỏ nhất trong scope cùng mọi ancestor, và tính headroom nhỏ nhất theo usage tương ứng; thiếu usage cho một cgroup đã giới hạn thì fail-closed về 0 MB.
- **ĐÃ BỔ SUNG — Resource regression:** cả hai test suite kiểm tra cấu hình wrapper/service và mô phỏng scope+parent để bảo đảm worker planner dùng giới hạn/headroom hiệu lực. Đã chạy harmless job qua wrapper thật: COIN báo cgroup 4096 MB, EDU 2048 MB; các mức trống quan sát được lần chạy thay đổi theo sử dụng RAM. Đây kiểm chứng cgroup RAM, không phải tải stress/OOM test.
- **Re-check cuối ngày 2026-10-24:** COIN **13/13** và EDU **13/13** tests PASS; EDU job backtest/API lifecycle và golden parity PASS; COIN API→worker custom backtest `done`, kết quả trả đầy đủ, `peak RAM 271 MB / limit 4G`. Wrapper smoke riêng xác nhận cgroup limit hiệu lực COIN 4G / EDU 2G. `npm --prefix nora/coin/frontend run build:all`, `api:check` (142 prefixes), `bash -n` và `git diff --check` PASS. Full `./nora/check/check.sh` đạt **18/19**, chỉ FAIL gate worktree cleanliness vì changes chưa commit; mọi gate chức năng còn lại PASS. Có 5 COIN và 4 EDU deprecation warnings. Slice hiện không đặt `CPUQuota` (infinity); job wrapper pin CPU affinity `0-13`, nên tập CPU từng job bị giới hạn nhưng chưa có quota tổng CPU cho cả Nora. Chưa chạy tải cạnh tranh/stress hoặc thử nghiệm OOM; đây không phải bằng chứng load stability. Không tuyên bố toàn bộ workstream done; các gap lifecycle/backtest/live/UI nêu trên còn mở.

#### Kế hoạch chi tiết theo thứ tự
1. **Triage/acceptance:** giữ nguyên findings và baseline; xác định artifact path mỗi app cần build ra, dev backend target đúng, OpenAPI/API contract expectations, hành vi an toàn live và tiêu chí pass/fail. Không sửa trước khi biết output build nào được deploy.
2. **COIN build commands — đã sửa và build pass:** tiếp tục giữ output path đã được Nginx cấu hình; kiểm tra entrypoint/bundle isolation khi build thay đổi.
3. **COIN dev proxy — đã sửa cấu hình:** tiếp tục smoke test dev API health, login/session và một route an toàn; xác nhận EDU vẫn dùng `18022`, không route sang legacy.
4. **API route gate — đã có:** mở rộng nếu cần để kiểm tra method/schema/auth theo product; hiện 142 path prefixes chỉ chứng minh route tồn tại trong ít nhất một schema.
5. **Tăng COIN regression tiếp:** test process/import/env/audience/data root; meaningful HTTP request/response/error/authorization; deterministic backtest PnL/fees/equity; job submit/status/fail/cancel/ownership qua worker cô lập; exchange adapter chỉ fake/testnet, assert không tạo lệnh live ngoài ý muốn. Regression API mới chỉ xác minh validate/launch boundary và cancel error contract; không dùng key thật hoặc capital thật.
6. **Xác nhận EDU regression:** chạy toàn bộ test EDU; kiểm tra các assertion trên đúng code hiện tại, đặc biệt DSL/backtest, ownership, cancel và data symlink read-only. Bổ sung case chỉ khi acceptance matrix chỉ ra hổng; không suy luận độ bao phủ chỉ từ số dòng test.
7. **Frontend isolation/UI smoke:** build riêng cả hai từ đúng working directory; assert output host/product title, entrypoint, routes và API base/proxy; mở public/dev UI cho các trang chính, auth redirect, loading/error/empty/job-result flows. Tách EDU chunk warning thành follow-up đo kích thước nếu cần.
8. **Business/failure matrix:** kiểm tra EDU journey market→DSL→backtest→result; COIN journey strategy→backtest/scan→portfolio/history và testnet/stub live safety. Fault inject data/cache/storage/worker/upstream/cancel/restart trong môi trường kiểm thử, xác nhận không mất state, lỗi hiển thị rõ và không ảnh hưởng chéo.
9. **Final acceptance & operations:** chạy COIN/EDU focused tests, frontend build/API contract checks, import isolation, calculation notebook, full `./nora/check/check.sh`; kiểm tra health/public HTTPS/logs, rollback/backup. Theo dõi soak đủ 48 giờ từ mốc đã ghi nhận khoảng **2026-10-23 05:00 UTC**; chưa retire legacy trước 2026-10-25 05:00 UTC và owner approval.

**Điều kiện đóng workstream:** tất cả journey trong acceptance matrix có bằng chứng; COIN và EDU regression suites/builds/system check đều PASS; không còn mismatch hoặc lỗi mức blocker/high chưa xử lý; lỗi còn lại được ghi rõ cùng owner/waiver; có xác nhận operator cho deploy/rollback và owner cho quyết định legacy. Test chức năng không thay thế soak. Giữ legacy fallback cho tới khi đủ 48 giờ soak và được owner nghiệm thu; không tự retire. Không kết luận mọi logic đúng hay sẵn sàng vốn thật nếu các trường hợp đó chưa nằm trong phạm vi đã kiểm thử.

## Roadmap tiếp theo: tối ưu mọi view và run của COIN / EDU

**Trạng thái tiến độ (2026-10-24):**
- **ĐÃ HOÀN TẤT — View Inventory & Contracts:** Đã lập ma trận rà soát toàn bộ route, component, API dependency, trạng thái loading/error/empty và known risk cho cả COIN và EDU tại [view_inventory_and_contracts.md](file:///home/vmc03/.gemini/antigravity-ide/brain/c51b5916-b13f-4536-8a8b-f97c0ba44438/view_inventory_and_contracts.md).
- **ĐÃ XÁC NHẬN HỢP ĐỒNG REGIME:** API `/api/studio/market/regime` chỉ trả trạng thái rời rạc (categorical states: `UNKNOWN`, `RANGE`, `TREND_UP`, `TREND_DOWN`, `VOL_EXPANSION`, `SURGE`, `CRASH`), **không có float score liên tục**. Tuân thủ nghiêm ngặt nguyên tắc không tự sinh số giả mạo.
- **ĐÃ TRIỂN KHAI — COIN Signed Regime Indicator (`coin-regime-visual`):** Đã hiện thực thanh đo có dấu (`RegimeScale`) trong [OverviewExtras.jsx](../nora/coin/frontend/src/components/portfolio/OverviewExtras.jsx) và CSS [shell.css](../nora/coin/frontend/src/styles/shell.css): cực âm đỏ bên trái (`CRASH -2`, `TREND_DOWN -1`), trung tính `0` ở giữa (`RANGE 0`), cực dương xanh bên phải (`TREND_UP +1`, `SURGE +2`), huy hiệu cảnh báo biến động `VOL_EXPANSION`, xử lý rõ ràng trạng thái zero/missing/stale/error mà không dùng điểm số giả mạo. Hỗ trợ cả Featured Benchmark Banner lẫn Compact Table Scale có accessible ARIA (`role="meter"`).
- **ĐÃ BỔ SUNG REGRESSION TEST:** [test_coin_app.py](../nora/coin/tests/test_coin_app.py) đạt **13/13 PASS**, gồm `test_coin_market_regime_categorical_contract` và kiểm tra resource limits. EDU tests đạt **13/13 PASS**, gồm kiểm tra cap cgroup hiệu lực.
- **CÁC BƯỚC TIẾP THEO:** `coin-backtest-quality` (xác thực toàn bộ luồng backtest/scan/WFA/MC), `coin-intraday-live-parity` (chuẩn hoá intraday execution parity trên stub/testnet), `coin-alpha-research` (chuyển alpha prompt sang kiểm định giả thuyết thị trường), `edu-view-quality`.


### Trình tự thực hiện
1. **Lập inventory & baseline** — map toàn bộ product routes, view states, API/data calls, job/run journeys, coverage và điểm chậm; đo baseline trước khi đặt ngưỡng performance. Dùng kết quả để chốt tiêu chí pass/fail cho từng route; không áp SLO tùy ý khi chưa có số đo.
2. **Nền tảng trải nghiệm chung, triển khai riêng từng product** — kiểm tra fetch/render lặp, pagination/virtualization khi dữ liệu lớn, cache/invalidation, loading/error/empty, responsive/accessibility và job progress/cancel/reload. Chỉ tối ưu có profile chứng minh, không gom mã xuyên COIN/EDU.
3. **COIN Home/Portfolio — thanh regime** — truy API regime hiện có và xác nhận có score liên tục có dấu hay chỉ categorical. Thể hiện thang ngang trái/phải: âm đỏ bên trái, `0` ở giữa, dương xanh lá bên phải; ghi giá trị, trạng thái, thời điểm dữ liệu. Nếu API chỉ có categorical state thì không tự quy đổi/giả tạo số; cần chốt hoặc bổ sung hợp đồng dữ liệu trước. Kiểm tra zero, missing, stale/error, responsive và accessible.
4. **COIN Backtest — độ chính xác và mọi journey** — kiểm tra form, backtest, scan, WFA, Monte Carlo, results, history và drilldown; job submit/progress/failure/cancel/reload; provenance dữ liệu; fill convention/fees/slippage/funding; trade ledger → equity → metrics. Đối soát với oracle fixture độc lập; đo hiệu năng cả view lẫn run trên khối lượng đại diện.
5. **COIN Live — intraday và execution parity** — ưu tiên workflow intraday để nghiên cứu/vận hành nhiều alpha nhưng không hạ risk guard. Truy signal timing, entry/close, session boundary, partial/reject/cancel, fee/slippage, reconciliation và restart. Đối chiếu cách thực thi do Nora code với quy ước Nautilus và backtest cùng cấu hình bằng exchange stub/testnet; không dùng live capital, và mọi thao tác exchange production cần owner/operator approval riêng.
6. **COIN Alpha Prompt — nghiên cứu giả thuyết, không phải tối ưu tham số** — hướng tới quy trình idea research: giả thuyết thị trường và cơ sở kinh tế, nguồn/provenance, quy tắc falsifiable, khả năng có dữ liệu, novelty/overfit checks, truy vết sang code, OOS/WFA/Monte Carlo và human review. Tách generation khỏi validation; không trình bày ý tưởng sinh tự động hay một kết quả backtest như alpha đã được chứng minh. Đây là workstream khó, cần chốt phương pháp/tiêu chí trước khi mở rộng mô hình hoặc prompt.
7. **EDU — mọi view và run** — inventory/tối ưu Home, Market, Studio, Strategy/User/Profile, History, Backtest/Results; kiểm DSL compile, job lifecycle, ownership, reproducibility, provenance, trạng thái UI và correctness. Tối ưu/bổ sung kiểm thử trong EDU, không gọi logic/runtime của COIN.
8. **Acceptance theo evidence** — chạy gate riêng từng route/journey, correctness fixture, API contract, browser smoke và performance baseline-vs-after; ghi PASS/FAIL và phần chưa phủ. Public deployment, soak, legacy retirement và production trading là các quyết định/gate tách biệt.

### Ưu tiên và tiêu chí hoàn tất
- Ưu tiên trước: inventory/baseline, lỗi correctness/risk, sai lệch backtest↔live, workflow hay dùng; sau đó mới tinh chỉnh animation/visual polish.
- Mỗi view phải có tiêu chí trạng thái thành công, loading, empty, error/stale; mỗi run phải kiểm input, progress, cancel, reload/recovery và kết quả.
- Performance pass dựa trên route và workload đại diện được đo, không chỉ dựa trên build pass; không regression correctness/accessibility.
- Alpha research chỉ pass khi có giả thuyết có thể bác bỏ, provenance, kiểm định OOS và người duyệt; không pass chỉ vì LLM trả strategy hoặc backtest dương.
- Không đánh dấu toàn bộ COIN/EDU “done” nếu còn view chưa inventory hoặc journey chưa có evidence; không tuyên bố khớp Nautilus tuyệt đối hay sẵn sàng vốn thật ngoài phạm vi test.

## Lệnh kiểm tra thường dùng
- Full cutover/system check: `./nora/check/check.sh`
- EDU tests: `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/edu/tests/test_edu_app.py`
- COIN tests: `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/coin/tests/test_coin_app.py`
- RubiLab hiện tại: [nora/check/rubilab_verify.py](../nora/check/rubilab_verify.py)

## Hướng dẫn làm việc
- Tiếp tục công việc đang mở từ trạng thái ở trên; không hỏi lại các quyết định đã chốt.
- Ưu tiên bằng chứng có thể tái lập, dữ liệu từng bước và tiêu chí pass/fail rõ ràng. Cập nhật mục trạng thái này khi có kết quả kiểm chứng mới; phân biệt rõ “đã triển khai”, “đã kiểm thử”, “đã public” và “đã soak/retire”.
