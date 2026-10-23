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

1. **Kiểm kê và chốt acceptance matrix:** liệt kê user journey, route, module, data root, worker, UI surface và test hiện có cho từng sản phẩm; mỗi hành vi có điều kiện đầu vào, kết quả mong đợi, lỗi mong đợi và PASS/FAIL quan sát được.
2. **Boundary/runtime:** chạy COIN/EDU ở process sạch và hai thứ tự import; xác nhận module origin, product identity, config/env, secret/audience, data/cache/log roots, startup/shutdown, và không fallback sang sản phẩm kia hay legacy. Kiểm tra lỗi cấu hình thiếu phải rõ ràng.
3. **Frontend, API, identity và data:** build riêng từng UI; kiểm tra navigation, API base URL, auth/session, form/loading/error/empty state; kiểm thử toàn bộ OpenAPI contracts, validation, ownership, status/error schema, dữ liệu/cache/catalog, persistence và từ chối cross-product. Bao gồm dữ liệu hỏng/thiếu và identifier/path không hợp lệ.
4. **Jobs:** kiểm tra submit → queued → running → success/failure/cancel, progress/log/result, ownership, retry/restart/idempotency, process-group cancellation, allowlist, tham số an toàn, lock, timeout và memory/CPU boundaries. Chứng minh tải EDU không làm nghẽn COIN.
5. **Luồng nghiệp vụ EDU:** market data → DSL compile/diagnostics → strategy save/load/version → backtest → result/chart/history → cancel/retry; kiểm tra DSL/dữ liệu biên và đối soát kết quả với oracle phù hợp.
6. **Luồng nghiệp vụ COIN:** strategy/parameters → signal/backtest → scan/optimization/WFA/Monte Carlo nếu được hỗ trợ → trade/portfolio/history; xác minh sizing, fill, phí, equity, metrics và invalid-input behavior. Live/exchange chỉ testnet hoặc stub, gồm partial/reject/cancel, position reconciliation, restart recovery và risk limits; tuyệt đối không dùng vốn thật trong gate này.
7. **Failure/recovery:** fault injection có giới hạn cho service/API, exchange/data, cache/storage, worker, timeout/cancel race, Nginx upstream và resource pressure; xác nhận lỗi hiển thị, log/health hữu ích, không hỏng state, không ảnh hưởng sản phẩm còn lại và phục hồi an toàn.
8. **Regression, deployment và sign-off:** chuyển lỗi/contract đã xác nhận thành automated regression riêng cho COIN và EDU; chạy frontend builds, product tests, import isolation, calculation notebook và `./nora/check/check.sh`. Kiểm tra systemd/Nginx/HTTPS/logs, backup/restore/rollback và tiếp tục soak theo gate vận hành.

**Điều kiện đóng workstream:** tất cả journey trong acceptance matrix có bằng chứng; COIN và EDU regression suites/builds/system check đều PASS; không còn mismatch hoặc lỗi mức blocker/high chưa xử lý; lỗi còn lại được ghi rõ cùng owner/waiver; có xác nhận operator cho deploy/rollback và owner cho quyết định legacy. Test chức năng không thay thế soak. Giữ legacy fallback cho tới khi đủ 48 giờ soak và được owner nghiệm thu; không tự retire. Không kết luận mọi logic đúng hay sẵn sàng vốn thật nếu các trường hợp đó chưa nằm trong phạm vi đã kiểm thử.

## Lệnh kiểm tra thường dùng
- Full cutover/system check: `./nora/check/check.sh`
- EDU tests: `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/edu/tests/test_edu_app.py`
- COIN tests: `/home/vmc03/.venvs/nora312/bin/python /home/vmc03/norabt/nora/coin/tests/test_coin_app.py`
- RubiLab hiện tại: [nora/check/rubilab_verify.py](../nora/check/rubilab_verify.py)

## Hướng dẫn làm việc
- Tiếp tục công việc đang mở từ trạng thái ở trên; không hỏi lại các quyết định đã chốt.
- Ưu tiên bằng chứng có thể tái lập, dữ liệu từng bước và tiêu chí pass/fail rõ ràng. Cập nhật mục trạng thái này khi có kết quả kiểm chứng mới; phân biệt rõ “đã triển khai”, “đã kiểm thử”, “đã public” và “đã soak/retire”.
