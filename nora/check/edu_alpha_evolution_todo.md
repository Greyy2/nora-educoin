# EDU Alpha Evolution — Todo triển khai có kiểm soát

**Ngày lập:** 2026-10-27
**Trạng thái:** PARTIAL / NOT ACCEPTED — Hai alpha `0d51ba8d2012` và `541c55834f56` đã có candidate chạy tuần tự qua EDU API worker 2 GB trên cửa sổ lịch sử đầy đủ; chưa alpha nào được nghiệm thu pass. Theo yêu cầu owner, kiểm chứng cần dùng COIN/Nautilus. Chỉ có một parent fold của `0d51ba8d2012` chạy được qua COIN custom-backtest; candidate/fold còn lại chưa chạy. COIN portfolio-WFA hiện chỉ nhận strategy ID trong thư viện COIN, không nhận trực tiếp EDU custom DSL; do đó lượt này **chưa phải COIN WFA pipeline hoàn chỉnh**. Alpha được xác nhận pass: **0**. Handoff chi tiết tại [edu_alpha_coin_wfa_handoff_20261027.md](./edu_alpha_coin_wfa_handoff_20261027.md). Không gọi 23 alpha là đã tiến hóa xong.
**Mục tiêu:** điều tra có thể tái lập các alpha có kết quả baseline OOS âm; chỉ tạo candidate nghiên cứu sau khi xác minh dữ liệu, code, config, execution và chi phí. Không cam kết mọi alpha sẽ có lãi, không tự động sửa alpha người dùng, không cho phép triển khai live.

**Backlog riêng cho 27 fixture/test alpha bị block:** owner chọn **không dùng WFA để tiến hóa**, mà một full-history run duy nhất/candidate cùng bốn parent-template controls (31 job serial, không tuning/rerun) theo [full-history amendment](./edu_fixture_alpha_full_history_amendment_20261028.json). V2 có 27 DSL riêng, giữ source gốc, action `buy→close` để exit thắng ở bar đồng thời; kiểm tra offline 27/27 body/hash/source pass. **V2 chưa production-compile hoặc backtest**; không tái sử dụng compile/WFA receipts của v1. WFA v1 2/93 là lịch sử và không resume. Candidate v1 U1 BTC 1h fold 1 +0.32%, win rate 18.9%, PF 1.033, không đạt protocol. Production compile/full-history cần EDU API loopback, hiện sandbox chặn (HTTP 403); system Python thiếu pandas nên compile local không chạy. Single full-history result sẽ chỉ là mô tả trên history đã xem, không phải pass/holdout/profitability claim. Không gộp 27 fixture vào queue 23 alpha OOS-negative và không tuyên bố backtest dương đảm bảo lãi.

**Cập nhật chẩn đoán:** [báo cáo 23 alpha OOS âm](./edu_alpha_fail_reason_and_evolution_report.md) có logic/config của 23/23, OOS aggregate và market-path summary quanh full-run entries rơi vào ngày OOS cho 19/23. Đây là giả thuyết có mức chứng cứ được nêu rõ, không phải 23 test-stage trade-level root causes đã xác nhận: chỉ `0d51ba8d2012` có signal-level reconstruction từng bar; `15567e02a806`, `270e6e28416f`, `bf519617d973`, `fa9587a97fa9` thiếu OOS trade ledger; `18e87aa868ad` còn unit mismatch cần xử lý. Mọi hướng cần kiểm tra trên ledger/config hash-matched trước khi được xem là kết luận.

**Cập nhật trạng thái bằng chứng 2026-10-27 20:00 UTC (baseline WFA cũ):** Các kết quả dưới đây đã được ghi vào artifact; đây không phải nghiệm thu hoàn tất. Nguồn WFA [edu_evolution_wfa_results.json](./edu_evolution_wfa_results.json) ghi `total_evaluated=23`, với 19 `UNVERIFIED / INVALID_FOLD_WINDOWS`, 4 `INSUFFICIENT_SAMPLE`, 0 `WFA_PASS`, 0 `WFA_FAIL`; manifest candidate ghi 29 variants. Vì vậy không được mô tả các WFA run này là fold validation hợp lệ hoặc coi các dispositions là bằng chứng đã tối ưu chiến lược:

- **`0d51ba8d2012` C1 (Persistence):** Đã chạy re-run Parent job `20261027_195119_75f292` (peak RAM 1047 MB / 2GB) và Candidate C1 job `20261027_195333_c7062f` (peak RAM 988 MB / 2GB). Đã xuất kết quả chính xác theo đúng tên trường engine (`win_rate_trades`, `profit_factor_trades`, `expectancy_pct`), lưu artifact candidate [0d51ba8d2012_c1_persistence.json](./candidates/0d51ba8d2012_c1_persistence.json) và báo cáo authoritative tại [edu_alpha_0d51_experiment_report.md](./edu_alpha_0d51_experiment_report.md). Test return: -11.39% → -11.16%, test expectancy: -0.1470% → -0.1441%, win rate: 15.1% → 13.2%, profit factor: 0.283 → 0.256. Verdict: `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`.
- **`0d51ba8d2012` C2 (SMA50 trend filter, revalidated 2026-10-27 21:44 UTC):** Job `20261027_214402_3f09f1` completed through local EDU API worker, exit 0, peak RAM 1024 MB / 2 GB. Request inherited the parent job config, same 10-symbol universe/date range/data catalog and position settings. Full-window descriptive result: return +7.28% → +5.87%; MDD 28.18% → 22.70%; trades 256 → 144; WR 17.6% → 18.8%; PF 0.921 → 0.851; expectancy +0.0001% → -0.0233%; fees $124.31 → $71.46. The filter reduced drawdown/trades but did not improve net return or expectancy; verdict `NOT_PASS`. API returned `config.test_start=2025-01-01`, not required WFA boundary `2024-10-01`; exclude train/test metrics and do not call this exact-fold WFA. Evidence: [C2 evaluation](./candidates/0d51ba8d2012_c2_trend_filter_evaluation.json). Protocol budget is max two candidates/alpha; C1+C2 consume the `0d51ba8d2012` budget, so stop further variants on this already-viewed window.
- **`541c55834f56` C2 (SMA50 trend filter, sequential revalidation 2026-10-27 21:48 UTC):** Parent `20261027_214742_038be6` then C2 `20261027_214837_f2f662` ran one at a time; exit 0, wrapper peaks 1081/984 MB under 2 GB. Both used current parent config, same 10-symbol catalog/dates and position settings. Full-window descriptive comparison: return +8.90% → +10.15%, MDD 30.33% → 26.77%, trades 381 → 329, WR 16.5% → 19.1%, PF 1.085 → 1.086, expectancy +0.0422% → +0.0391%, fees $221.96 → $179.64. This is promising in cumulative return/drawdown but per-trade expectancy declined slightly; it remains research-only. API boundary is `2025-01-01` rather than exact fold start `2024-10-01`, and full period has been viewed; no WFA/holdout pass. Evidence: [alpha report](./edu_alpha_541c55834f56_experiment_report.md) and [C2 evaluation](./candidates/541c55834f56_c2_trend_filter_evaluation.json).
- **COIN engine handoff (2026-10-27 22:03 UTC):** Thử dùng COIN portfolio-WFA trực tiếp không phù hợp: endpoint yêu cầu strategy IDs từ `BY_ID`/book và các strategy đó được materialize từ thư viện COIN; API không nhận EDU user DSL. Đã chạy parent `0d51ba8d2012` bằng COIN `custom_backtest` trên đúng fold 1: job `20261027_220350_5d8ae9`, program hash `457060fb8c85`, `2024-10-01`–`2025-05-31`, 10 OKX perpetuals, simulate return **+35.54%**, MDD **26.54%**, 61 trades, WR **11.5%**, PF **2.117**, fees **$61.27**, wrapper peak **446 MB / 4G** (job RSS peak 700.8 MB). Job status `done`, exit 0. **Không chạy candidate trong fold này, không chạy fold 2/3, không có hash-matched full WFA comparison.** Closed PnL $3,355.53 + unrealized PnL của 2 vị thế mở $199.11 = $3,554.64, equity change là $3,553.97; residual khoảng **-$0.67** chưa giải thích. Treat as `PARTIAL_FOLD / LEDGER_RECONCILIATION_REQUIRED`, not pass. No COIN jobs remain active at handoff.
- **`14e3b934b1e5` C1 (ROC-Rising):** Đã hoàn tất đối đầu Parent `20261027_192941_f36171` (peak RAM 1140 MB) vs Candidate `20261027_193324_1d0c42` (peak RAM 1079 MB). Test return: -27.78% → -27.76%, expectancy: -0.0836% → -0.0804%, win rate: 36.5% → 34.4%, profit factor: 0.476 → 0.461. Báo cáo độc lập tại [edu_alpha_14e3_experiment_report.md](./edu_alpha_14e3_experiment_report.md). Verdict: `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`.
- **`18e87aa868ad` Rebaseline (`exit_unit=pct`):** Job `20261027_193923_b7b8f5.json` hoàn tất trên đĩa (exit_code 0, peak RAM 1070 MB). Dưới contract chuẩn `exit_unit=pct` khớp code, OOS test có đúng 19 trades (< 20 trades), test return -29.25%, win rate 5.3%, PF 0.132. Báo cáo tại [edu_alpha_18e8_experiment_report.md](./edu_alpha_18e8_experiment_report.md). Verdict: `INSUFFICIENT_SAMPLE`.
- **`15567e02a806`:** OOS test chỉ có 9 trades (< 20 trades). Báo cáo tại [edu_alpha_1556_experiment_report.md](./edu_alpha_1556_experiment_report.md). Verdict: `INSUFFICIENT_SAMPLE`.
- **Baseline sample-limited:** 8 alpha (`4f28285aa44c` 7, `15567e02a806` 9, `270e6e28416f` 17, `b96bafe57445` 18, `cb750cb1eb10` 18, `18e87aa868ad` 19, `fa9587a97fa9` 19, `bf519617d973` 22 test / 9 sim ledger corrupt) có baseline OOS dưới ngưỡng hoặc ledger không nhất quán; dừng tuning trên mẫu/artifact hiện tại. Đây là disposition dựa trên baseline, không thay verdict WFA.
- **Kết quả WFA cho các alpha trong queue:** Artifact ghi 23 alpha-level evaluations, trong đó 19 bị vô hiệu hóa do `INVALID_FOLD_WINDOWS` và 4 `INSUFFICIENT_SAMPLE`. Đây không phải “đã qua WFA”; chưa có WFA pass/fail hợp lệ và chưa có căn cứ đóng tiến hóa các alpha đó.
- **Bảo toàn dữ liệu:** Báo cáo kiểm tra ghi nhận 57/57 file user alpha giữ nguyên hash SHA256; không có candidate nào được đưa lên live bot. Đây là các rào chắn bảo toàn, không đồng nghĩa chuỗi tiến hóa đã nghiệm thu hoặc đóng.

- **Current handoff (2026-10-27 22:18 UTC):** Owner yêu cầu dừng và bàn giao; không khởi chạy thêm job. Các experiment đã có: `0d51ba8d2012` C1/C2 không pass (2 candidates; budget exhausted), `14e3b934b1e5` C1 không pass, `541c55834f56` C2 promising nhưng unvalidated. Một COIN exact-date custom-backtest fold chỉ chạy parent `0d51ba8d2012`; đây không phải WFA pipeline hoặc candidate comparison. Số alpha được xác nhận tối ưu thành công/pass: **0**. Không có COIN job active lúc chốt. Xem [COIN WFA handoff](./edu_alpha_coin_wfa_handoff_20261027.md).

**Cập nhật audit 5 nhóm agent và sửa WFA exact boundary (2026-10-27):**

- Năm audit agent chỉ đọc, không tạo/chạy candidate. Kết luận chung: các WFA cũ vẫn `UNVERIFIED / INVALID_FOLD_WINDOWS`; đa số artifact không có test-stage ledger gắn với source/config hiện tại. Các con số dưới đây là baseline lịch sử đã xem, không phải holdout.
- **Momentum:** `14e3b934b1e5` OOS −27,78%/381 trades; C1 ROC-rising −27,78% → −27,76%, vẫn `NOT_PASS`. `541c55834f56` −25,74%/189; `f261549d9efa` −21,42%/241; `f4e211e9510d` −6,59%/77: chưa có OOS trade-level attribution đủ để biện minh filter đơn biến. `cb750cb1eb10` −5,05%/18: dưới ngưỡng 20, giữ `INSUFFICIENT_SAMPLE`.
- **Rebound:** `5e52d3fdf71f` −24,89%; `6afa7f774655` −10,25%; `715e56a6dd33` −11,02%; `7f67e9aed0aa` −16,75%; `89379cc0ab52` −20,96%; `b4b65cd3493f` −13,17%; `c33cc317bbeb` −28,81%. Các candidate cũ đổi đồng thời stop/risk hoặc thêm filter nhưng không có receipts/ledger OOS hash-matched; C2 của `6afa` và `7f67` ghi 0 trades. Không suy diễn “xu hướng giảm” thành nguyên nhân đã chứng minh; cần ledger test-stage và signal/features tại entry/exit theo từng vị thế trước khi chọn biến.
- **Exit/risk:** `3cfcc2d296a2` −26,77%/193, C1 −20,31% trung bình fold và 0/3 fold dương; `7f3486d63ca8` −17,14%/267, hai candidate −13,59%/−11,79% nhưng config risk giữa code/effective artifact lệch; `717c1890c59e` −9,49%/46, candidate summary +4,53% nhưng chỉ từ WFA invalid và MC CI vẫn âm; `b96bafe57445` −6,55%/18, candidate thiếu mẫu. Không xem tăng risk/SL là sửa edge; phải tách exit/entry khỏi sizing và đối chiếu fills.
- **Sample/receipt:** `4f28285aa44c` OOS 7; `270e6e28416f` 17; `15567e02a806` 9; `fa9587a97fa9` 19 — sample-limited, không tune trên lát cắt hiện có. `bf519617d973` metric OOS 22 nhưng chưa có test ledger đối soát — `LEDGER_BLOCKED`, không gọi sample fail. `18e87aa868ad` baseline dùng `atr` trái với code `pct`; rebaseline đúng `pct` có OOS 19 và −29,25%, vẫn sample-limited. `0d51ba8d2012` đủ mẫu nhưng C1 chỉ −11,39% → −11,16%, không pass; receipt revalidation gắn guest UID, cần owner-scoped receipt nếu chạy lại.
- **Nguyên nhân tổng hợp đã được chứng minh:** lỗi boundary cũ do `stage_split()` snap theo ngày 1/1; đây là nguyên nhân WFA invalid, **không phải nguyên nhân alpha thua**. Với các alpha còn lại, nguyên nhân lợi nhuận âm cụ thể chưa được xác nhận vì thiếu test-stage ledger, hoặc baseline/config không khớp. Danh sách logic/candidate facts chi tiết nằm trong [edu_alpha_fail_reason_and_evolution_report.md](./edu_alpha_fail_reason_and_evolution_report.md) và artifact từng alpha hiện có.
- **Sửa local chưa nghiệm thu:** custom backtest nhận `test_start` qua request → runner allowlist → worker split → `build_result`; config/manifest ghi boundary hiệu lực và result giữ `test_trades` riêng. WFA script chỉ nhận đúng một `--alpha-id` + `--candidate-id` mỗi lượt, ghi checkpoint atomic sau từng fold, giữ source/protocol/manifest hashes, không ghi đè report nếu thiếu `--overwrite`, và fail-closed khi boundary/ledger lệch. Runner WFA tắt benchmark/diagnostics không dùng cho gate, chạy main/test tuần tự, dừng các bước còn lại khi required run lỗi; mặc định UI/custom backtest giữ benchmark/diagnostics/parallel behavior cũ. Không chạy mọi alpha hoặc candidate song song.
- **Validation hiện tại:** Python 3.12 từng chạy được khi đặt `PYTHONHOME` tới uv runtime và thêm `nora312/site-packages` vào `PYTHONPATH`; tuy nhiên wrapper hiện mặc định trỏ `/home/vmc03/.venvs/nora312/bin/python` không chạy được. Lượt thử mới nhất: `run_limited.sh -- ... --help` báo “Không chạy được python”; khi đặt `NORA_PYTHON` tới binary uv Python 3.12 thì qua được kiểm tra interpreter nhưng dừng với “Chưa có nora.slice”. EDU API health trên `127.0.0.1:18022` trả `ok=true`, nhưng OpenAPI đang phục vụ không công bố `test_start` trong `CustomBacktestRequest`; không gửi backtest qua API vì field boundary có thể bị bỏ qua và tạo run sai protocol. Regression exact-boundary request/runner và bounded sequential-step **2/2 PASS**; `py_compile`, CLI `--help`, Pylance diagnostics và `git diff --check` PASS ở lượt validation trước. Không chạy ngoài wrapper/giới hạn RAM 2GB. Chưa có bằng chứng runtime cho engine split hoặc run WFA; không đánh dấu TODO/phase DONE. Cần runner trong user systemd session với `nora.slice`, interpreter/dependency path hợp lệ, và EDU service nạp code có `test_start` trước khi chạy candidate. Lệnh chạy một candidate sau khi các điều kiện đó sẵn sàng: `nora/edu/ops/run_limited.sh -- /home/vmc03/norabt/scripts/step7_edu_evo_run_wfa.py --alpha-id <ID> --candidate-id <ID>`; mỗi lượt chỉ 3 fold tuần tự, checkpoint riêng theo candidate.

## 1. Phạm vi và nguyên tắc chặn đi lạc

### Phạm vi đầu vào

- Kho hiện có **57 active user alpha**. Audit ngày 2026-10-27 ghi nhận **27 `BLOCKED_UNKNOWN_INTENT`** và 30 record còn lại mới có bằng chứng compile, chưa được chấp nhận về execution/config.
- Baseline lịch sử có **30 run**: 23 kết quả OOS âm, 6 OOS dương biên và 1 OOS dương chỉ có 3 trades. Đây là kết quả mô tả từ cấu hình/run cũ, không phải kết quả sau các sửa đổi unit gần đây.
- Kế hoạch nghiên cứu tiến hóa trước mắt chỉ xếp **23 alpha OOS âm lịch sử** vào hàng đợi điều tra. Đây chưa phải quyết định rằng chúng đều “fail” cuối cùng.
- 7 alpha OOS dương không thuộc hàng đợi tiến hóa lỗ. Kết quả dương không đồng nghĩa đã pass về độ bền; đặc biệt alpha 3 trades phải giữ trạng thái mẫu nhỏ/chưa kết luận.
- **27 alpha chưa rõ ý đồ không được backtest để chọn winner hoặc tự viết lại.** Chỉ đưa trở lại phạm vi sau khi có quyết định của owner về ý đồ chiến lược.

### Quy tắc không được phá

1. Không sửa/xóa/ghi đè alpha user, version lịch sử, record Vinh hoặc baseline artifacts. Candidate chỉ được lưu trong namespace nghiên cứu tách biệt, có parent ID và hash.
2. Không dùng OOS đã xem trong baseline (bao gồm split lịch sử kết thúc 2026-10-03) để chọn tham số rồi gọi nó là holdout hoặc bằng chứng độc lập.
3. Không đổi nhiều giả thuyết cùng lúc. Giảm risk/sizing là thí nghiệm risk riêng, không được trình bày như đã cải thiện edge của signal.
4. Không tự diễn giải tên alpha thành logic. Chẩn đoán phải khớp source, effective config, trade/fill ledger và exit reason.
5. Không gọi slippage proxy là slippage venue-measured. Không giả định funding, liquidation, fee tier hoặc historical instrument spec đã được xác minh nếu artifact không chứng minh.
6. Giữ cả run âm, lỗi, thiếu mẫu và bị chặn trong báo cáo; `NOT RUN`, `UNKNOWN`, `BLOCKED` không được đổi thành số 0 hoặc `FAIL`.
7. Không chạy sweep rộng, MC, hoặc holdout cho tới khi các gate phụ thuộc hoàn tất. Không gửi lệnh, không start bot, không promote candidate.

## 2. Chuỗi dependency và TODO

Các TODO dưới đây chạy theo dependency ghi rõ; không bắt đầu TODO khi dependency chưa `DONE`. Tại thời điểm lập kế hoạch, các TODO đều `NOT_STARTED`; trạng thái hiện tại là partial/not accepted như cập nhật ở đầu tài liệu.

### EDU-EVO-00 — Khóa charter và universe nghiên cứu

- **Phụ thuộc:** không có.
- **Việc làm:** đóng băng danh sách 57 record và phân nhóm hiện hành; xác nhận 23 OOS âm lịch sử là queue điều tra chứ không phải tập pass/fail cuối cùng; giữ 7 OOS dương ngoài queue; giữ 27 unknown-intent ở trạng thái blocked.
- **Deliverable:** charter có timestamp, danh sách ID theo nhóm, phạm vi được phép chạy và danh sách ngoài phạm vi.
- **PASS:** tổng ID duy nhất khớp inventory filesystem; mọi ID có đúng một disposition; không có record unknown-intent lẫn vào queue tuning.
- **BLOCK:** inventory hoặc phân loại hiện tại không tái lập được. Không chạy backtest/tuning.

### EDU-EVO-01 — Đóng băng source, version và cấu hình hiệu lực

- **Phụ thuộc:** EDU-EVO-00.
- **Việc làm:** với mỗi record trong queue, ghi alpha ID/owner, active version, code hash, config hash, code compiler version, unit SL/TP, sizing, risk, leverage, symbols, timeframe, run window và mọi field override. Đối chiếu code với cấu hình thực sự được plan builder/runtime tiêu thụ.
- **Lưu ý hiện trạng:** 23 record non-Vinh đã có active version đổi exit semantics sang `pct`, nhưng kết quả baseline lịch sử chưa được chạy lại trên active version mới. 7 record Vinh được giữ nguyên và cần xác minh riêng unit/config hiệu lực; không suy ra cấu hình từ comment hoặc tên.
- **Deliverable:** manifest bất biến theo record, kèm field source → consumer → effective value và hash.
- **PASS:** compiler/plan builder cho ra effective config xác định; không còn mismatch chưa giải quyết; artifacts/hash đủ để dựng lại request.
- **BLOCK:** config thiếu, unit không rõ, owner/version mapping sai, hoặc runtime bỏ qua field quan trọng. Sửa quy trình/contract trước; không đoán thay owner.

### EDU-EVO-02 — Xác minh dữ liệu và chọn cửa sổ khả dụng

- **Phụ thuộc:** EDU-EVO-00.
- **Việc làm:** kiểm kê dữ liệu thực sự được EDU runner đọc: symbol/timeframe, timestamp đầu-cuối, gap/duplicate, timezone, candle completeness, warm-up, data digest và khả năng tái tạo snapshot. Xác minh ngày dữ liệu chưa từng xuất hiện trong baseline/report/artifact trước khi đề xuất holdout.
- **Quyết định chưa được giả định:** độ dài train/test/fold và holdout chỉ được chốt sau khi biết dữ liệu khả dụng. Đề xuất 180d/60d, 3–5 folds hoặc holdout 90d trong tài liệu trao đổi không phải lịch đã được xác nhận; tuyệt đối không dùng khoảng thời gian đã xem làm holdout mới.
- **Deliverable:** data inventory có hash và sơ đồ timeline đánh dấu vùng đã xem, vùng development có thể dùng và vùng holdout nếu có.
- **PASS:** mọi cửa sổ dự kiến có data digest, bar count, gap/warm-up disclosure; vùng holdout (nếu có) nằm sau knowledge cutoff và chưa được mở.
- **BLOCK:** thiếu dữ liệu mới độc lập, causal gap chưa giải quyết hoặc không tái tạo được snapshot. Khi đó chỉ được làm chẩn đoán/baseline mô tả, không tuyên bố holdout.

### EDU-EVO-03 — Xác nhận execution contract và tái lập baseline hiện hành

- **Phụ thuộc:** EDU-EVO-01, EDU-EVO-02.
- **Việc làm:**
  1. Chạy deterministic fixtures cho signal timing, next-bar execution, stop/TP, phí, sizing, position lifecycle và equity accounting trên EDU engine hiện hành.
  2. Xác minh provenance của engine thực tế. Đối chiếu với docs/run artifacts xem spread proxy, stop proxy, phí, funding và liquidation được áp dụng thế nào; không dùng `slippage=0` từ report cũ nếu code/provenance chứng minh cấu hình khác.
  3. Sau khi xác định được config active, chạy lại đúng 30 record thuộc nhóm có thể chạy bằng cùng cửa sổ/capital/symbol/timeframe lịch sử, lưu output mới và gắn nhãn **re-baseline, không phải validation độc lập**. Nếu một record không còn tái tạo được, báo riêng, không thay bằng config khác.
- **Deliverable:** fixture receipts, request/config/input hashes, per-run job ID, raw trade/fill/equity artifacts, engine provenance và reconciliation với metric report.
- **PASS:** fixtures khớp oracle độc lập; run artifacts tái lập được; metrics khớp trade ledger trong tolerance đã ghi; mọi sai khác baseline cũ được giải thích.
- **BLOCK:** execution/cost path chưa xác định, hoặc số liệu lưu không đối chiếu được. Không tiến hóa strategy trước khi sửa nguồn sai và rerun gate này.

### EDU-EVO-04 — Phân rã PnL và chi phí không gây hiểu nhầm

- **Phụ thuộc:** EDU-EVO-03.
- **Việc làm:** cho từng run và từng fold sau này, đối chiếu:
  - gross trade PnL trước phí;
  - commission/fee thực sự được engine trừ;
  - spread/slippage proxy riêng, nếu có;
  - funding/liquidation và các trường thiếu phải để `UNKNOWN`/`NOT_MODELED`;
  - net equity/PnL cuối cùng.
- Chạy hai phép đo riêng: (a) ledger attribution cố định fills để tách số học phí khỏi gross; (b) full rerun counterfactual với fee/proxy thay đổi để quan sát tương tác với equity, sizing và fills. Không coi zero-fee run là cấu hình chọn winner.
- **Deliverable:** per-alpha cost attribution, công thức/nguồn số, giới hạn và so sánh counterfactual với config bất biến.
- **PASS:** gross − phí − các cost đã mô hình hóa reconciles về net theo semantics engine; mọi khoản chưa đo/thiếu đều hiển thị rõ.
- **BLOCK:** không thể tách được cost hoặc counterfactual thay đổi ngoài biến dự kiến. Không quy kết lỗ cho phí/slippage.

### EDU-EVO-05 — Lập hồ sơ chẩn đoán cho từng alpha trong queue

- **Phụ thuộc:** EDU-EVO-03, EDU-EVO-04.
- **Việc làm:** cho mỗi alpha, trích xuất trade log và tính thống nhất: số giao dịch, wins/losses/breakeven, expectancy, PF, drawdown, long/short, symbol, thời gian nắm giữ, exit reason, loss streak, fees, contribution tập trung, và kết quả theo khoảng thời gian. Đối chiếu mỗi kết luận với code/config và ít nhất một ví dụ trade có thể truy ngược.
- **Phân loại chẩn đoán:** `signal/entry`, `exit`, `sizing/risk`, `cost-sensitive`, `data/config/execution issue`, `low-sample`, `unknown`. Có thể gán nhiều nhãn nhưng phải dẫn chứng; không ép mỗi alpha vào một “root cause” duy nhất.
- **Deliverable:** 23 hồ sơ riêng; mỗi hồ sơ tách ba phần: observed facts, hypothesis cần kiểm tra, experiment phân biệt hypothesis.
- **PASS:** mọi nguyên nhân khẳng định đều có ledger/code evidence; mọi giả thuyết ghi điều kiện bác bỏ; mẫu nhỏ hoặc dữ liệu không đủ được giữ `INCONCLUSIVE`.
- **BLOCK:** thiếu trade/fill records, mismatch code/config hoặc không thể tái lập số đo. Không sáng tác hướng tiến hóa cho alpha đó.

### EDU-EVO-06 — Đăng ký trước tiêu chí và ngân sách thí nghiệm

- **Phụ thuộc:** EDU-EVO-05; EDU-EVO-02 cung cấp timeline.
- **Việc làm:** trước khi candidate chạy, chốt một research protocol dùng chung:
  - tiêu chí tối thiểu cho số trades, net return/expectancy, drawdown, độ ổn định giữa folds và cost stress;
  - định nghĩa return/equity, phí, stress multiplier và xử lý fold không có lệnh;
  - phương pháp WFA, train/test length, bước cuộn, warm-up, capital reset/continuity, cách ghép OOS folds;
  - ngân sách candidate/thử nghiệm cho mỗi alpha, giới hạn số tham số thay đổi mỗi hypothesis và cách ghi mọi lần thử;
  - tiêu chí insufficient-sample, stop/continue và điều kiện chấp nhận candidate.
- Các ngưỡng không tự lấy từ COIN, từ attachment hay từ kết quả đã quan sát. Đề xuất ban đầu phải được đóng băng trước sweep; mọi sửa protocol sau khi thấy kết quả tạo protocol version mới và không được xóa kết quả cũ.
- **Deliverable:** protocol có version/hash, cửa sổ và ngưỡng định lượng được phê duyệt trước khi tuning.
- **PASS:** reviewer có thể quyết định pass/fail từ metrics đã định nghĩa mà không cần diễn giải tùy ý sau kết quả.
- **BLOCK:** chưa thống nhất ngưỡng hoặc dữ liệu không đủ cho WFA hợp lệ. Không chạy sweep; có thể hoàn tất chẩn đoán ở các gate trước.

### EDU-EVO-07 — Tạo candidate research-only theo từng giả thuyết

- **Phụ thuộc:** EDU-EVO-05, EDU-EVO-06.
- **Việc làm:** tạo candidate có parent alpha ID, source/config diff, rationale, falsifiable hypothesis, parameter grid đã đăng ký, trial ID, source/config hash và protocol hash. Mỗi candidate chỉ kiểm tra một giả thuyết chính; tách signal changes khỏi risk/sizing changes.
- Chỉ dùng cú pháp được EDU DSL compiler hỗ trợ; thêm compiler/signal fixture cho thay đổi logic. Nếu đổi ý tưởng chiến lược (side, thesis, loại entry/exit) thì ghi là strategy variant mới, không gọi là tuning tham số.
- **Deliverable:** candidate manifest và code/config trong namespace research-only; alpha user gốc không đổi.
- **PASS:** mọi candidate dựng lại được từ manifest; tất cả trial dự kiến đã liệt kê trước; source original hash trước/sau không đổi.
- **BLOCK:** candidate cần suy đoán ý đồ, thay semantics không được phê duyệt, hoặc vượt trial budget.

### EDU-EVO-08 — Chạy WFA development folds có provenance đầy đủ

- **Phụ thuộc:** EDU-EVO-02, EDU-EVO-03, EDU-EVO-06, EDU-EVO-07.
- **Việc làm:** chọn tham số chỉ trên train fold theo protocol; chạy test fold kế tiếp đúng một lần cho mỗi candidate/fold; lưu tất cả run kể cả lỗi, lỗ, no-trade và insufficient sample. Không tái sử dụng baseline OOS cũ như fold test mới.
- Lưu per-fold source/config/data/engine/cost hashes, start/end, warm-up, bars, trades, raw ledger, metrics và exit status. Nếu thiếu số fold hoặc sample theo tiêu chí, kết quả là `INSUFFICIENT_EVIDENCE`, không thay cửa sổ ngẫu nhiên.
- **Deliverable:** fold-level immutable run records và phép tổng hợp OOS đã định trước; có thể chạy lại và đối chiếu.
- **PASS:** đủ số fold theo protocol; không leakage giữa train/test; test chỉ đánh giá params đã chọn từ train; mọi row trong search đều có trạng thái.
- **BLOCK:** leakage, thiếu fold, sai config, cost/input hash khác dự kiến hoặc pipeline không tái lập.

### EDU-EVO-09 — Chấm gate WFA và kiểm tra data snooping

- **Phụ thuộc:** EDU-EVO-08.
- **Việc làm:** áp dụng nguyên văn tiêu chí ở EDU-EVO-06; báo theo fold và tổng hợp, dispersion, số trial thực tế, hiệu quả sau cost stress. Dùng điều chỉnh/đánh giá phù hợp với số candidate đã thử (ví dụ DSR chỉ khi inputs và trial count có thể tái tạo). Không chọn chỉ theo best fold hay full-window return.
- **Deliverable:** mỗi alpha/candidate có verdict `WFA_PASS`, `WFA_FAIL`, `INSUFFICIENT_SAMPLE` hoặc `BLOCKED`, cùng evidence từng gate và lý do.
- **PASS:** verdict tự động suy ra từ protocol frozen; kết quả không phụ thuộc việc bỏ các candidate thua khỏi báo cáo.
- **BLOCK:** protocol đổi sau kết quả, trial count thiếu, hoặc statistical inputs không tái lập.

### EDU-EVO-10 — Monte Carlo/robustness sau WFA, không thay WFA

- **Phụ thuộc:** EDU-EVO-09; chỉ chạy candidate đạt WFA hoặc được protocol yêu cầu chẩn đoán.
- **Việc làm:** chốt trước resampling unit, block length, số đường mô phỏng, seed, ruin/drawdown definitions và ngưỡng. Bảo toàn sự phụ thuộc thời gian bằng phương pháp đã định trước; lưu seeds/paths hoặc artifacts đủ để tái lập.
- **Deliverable:** MC configuration, seeds, reproducible paths/summary, uncertainty intervals và gate result.
- **PASS:** kết quả lặp lại từ raw trade/equity series và frozen config; không dùng MC để biến một edge âm thành pass.
- **BLOCK:** mẫu quá nhỏ, mô hình resampling không phù hợp hoặc artifacts không tái lập.

### EDU-EVO-11 — Freeze candidate và mở holdout mới một lần

- **Phụ thuộc:** EDU-EVO-09 và EDU-EVO-10; EDU-EVO-02 phải xác nhận vùng holdout mới, chưa xem.
- **Việc làm:** freeze source/config/parameter/protocol/data hashes trước khi mở; evaluator chỉ chạy candidate đã freeze, không đổi tham số sau khi thấy holdout. Nếu không có data timestamps mới độc lập với baseline/report/diagnostics thì ghi `NO_UNTOUCHED_HOLDOUT_AVAILABLE`; không đổi tên vùng đã xem thành holdout.
- **Deliverable:** signed/frozen candidate manifest, holdout access/run receipt, raw records và kết quả một lần.
- **PASS:** holdout chưa từng được xem trước run, hashes khớp freeze, chỉ có một lần đánh giá; thất bại thì loại candidate khỏi xác nhận, không retune trên holdout.
- **BLOCK:** rò rỉ, holdout đã xem, code/config đổi hoặc không có dữ liệu độc lập.

### EDU-EVO-12 — Báo cáo closeout và disposition

- **Phụ thuộc:** tất cả gate áp dụng từ EDU-EVO-00 đến EDU-EVO-11.
- **Việc làm:** lập bảng cho cả 57 record: ID/owner, disposition, baseline/rebaseline job, candidate IDs, WFA/MC/holdout status, evidence links, blocker và quyết định tiếp theo. Nêu riêng số đã chạy, số đủ mẫu, số WFA pass/fail, số holdout đạt/chưa có; không gộp unknown với fail hoặc pass.
- Candidate chỉ được đề xuất thành alpha version mới sau khi owner/reviewer phê duyệt riêng; không tự động ghi đè active alpha. Kết quả nghiên cứu không cấp live authorization.
- **PASS:** tổng số record reconcile với inventory; toàn bộ verdict có artifact; không có metric/claim vượt evidence.
- **BLOCK:** thiếu artifact, record không có disposition hoặc báo cáo dùng “all pass/profitable/robust” sai căn cứ.

## 3. Lệnh kiểm tra và bằng chứng dự kiến

Lệnh dưới đây là baseline kiểm tra schema hiện có; trước khi chạy phải xác nhận executable/dependencies trong môi trường hiện hành. Không suy ra test PASS từ lệnh đã chạy trong lịch sử:

```bash
/home/vmc03/.venvs/nora312/bin/python nora/check/alpha_rerun_schema.py --validate nora/check/alpha_variant_status.json
/home/vmc03/.venvs/nora312/bin/pytest -q nora/check/test_alpha_rerun_schema.py
```

Đây là tooling COIN và chỉ là tham khảo cho cách đóng gói immutable rows; không được dùng như bằng chứng EDU execution hoặc thay thế test suite EDU. EDU runner/test commands cần được xác nhận lại từ môi trường đang dùng ở EDU-EVO-03.

## 4. Thứ tự bắt đầu và điều kiện dừng

Thực hiện theo chuỗi:

`EDU-EVO-00 → (EDU-EVO-01 + EDU-EVO-02) → EDU-EVO-03 → EDU-EVO-04 → EDU-EVO-05 → EDU-EVO-06 → EDU-EVO-07 → EDU-EVO-08 → EDU-EVO-09 → EDU-EVO-10 → EDU-EVO-11 → EDU-EVO-12`

- Việc đầu tiên còn lại là khép các blocker của **EDU-EVO-00** và **EDU-EVO-01/02** cho alpha đang xét; không mở candidate/run mới trước khi các prereq liên quan được xác minh. Các run đã lỡ khởi chạy được giữ trong nhật ký, không xóa hoặc coi là bằng chứng nếu thiếu receipt.
- Mỗi alpha có thể dừng riêng ở `BLOCKED` hoặc `INSUFFICIENT_SAMPLE`; không để một record bị chặn làm phát sinh suy đoán cho record khác.
- Nếu cost provenance hoặc execution fixtures fail, dừng toàn bộ tuning phụ thuộc engine; sửa producer/test trước rồi tạo run mới có hash mới.
- Nếu chưa có holdout mới, vẫn có thể báo cáo WFA development evidence nhưng không gọi là holdout-validated.
- Workstream chỉ kết thúc khi EDU-EVO-12 pass. “Candidate có lãi trong một run”, “baseline OOS dương”, và “compile thành công” đều không tự đủ điều kiện để gọi alpha pass.

## 5. Nhật ký Alpha đầu tiên: `0d51ba8d2012`

- [x] Parent baseline cũ và source/config đã được kiểm kê; signal-level analysis và market path nằm trong báo cáo chẩn đoán.
- [x] Candidate C1 persistence artifact đã được tạo và đối soát.
- [x] Rerun parent và C1 qua EDU jobs: Parent job `20261027_195119_75f292` (peak RAM 1047 MB / 2GB) và Cand C1 job `20261027_195333_c7062f` (peak RAM 988 MB / 2GB). Lưu raw artifacts và metrics trade-level chính xác (`win_rate_trades`, `profit_factor_trades`, `expectancy_pct`).
- [x] Báo cáo authoritative lưu tại [edu_alpha_0d51_experiment_report.md](./edu_alpha_0d51_experiment_report.md) và candidate JSON tại [0d51ba8d2012_c1_persistence.json](./candidates/0d51ba8d2012_c1_persistence.json).
- [x] Test return nhích -11.39% → -11.16%, test expectancy -0.1470% → -0.1441%, win rate 15.1% → 13.2%, PF 0.283 → 0.256. Không đạt admission gates. Chốt verdict: `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`. Không tune tiếp trên cùng OOS đã xem.
- **Tình trạng:** `CLOSED` — Không promote, không sửa alpha gốc.

## 6. Kết quả triển khai thực tế — theo từng batch & alpha

Các alpha đã có một số run/disposition ghi nhận trong artifacts, nhưng chưa được xử lý và nghiệm thu dứt điểm. Các mục dưới đây là trạng thái bằng chứng hiện có; `UNVERIFIED / INVALID_FOLD_WINDOWS` không tương đương `WFA_FAIL`.

### Batch A — Blocker và đầu hàng đợi

1. **`0d51ba8d2012`:** Đã hoàn tất thực nghiệm đối đầu C1 có raw receipts. Test return: -11.39% → -11.16%, test expectancy: -0.1441%, win rate 13.2%, PF 0.256. Verdict: `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`. Báo cáo: [edu_alpha_0d51_experiment_report.md](./edu_alpha_0d51_experiment_report.md).
2. **`18e87aa868ad`:** Đã xác thực rebaseline `exit_unit=pct` (Job `20261027_193923_b7b8f5`, exit 0, peak RAM 1070 MB). OOS test chỉ có 19 trades (< 20 trades), test return -29.25%, win rate 5.3%, PF 0.132. Dưới ngưỡng tối thiểu 20 trades. Verdict: `INSUFFICIENT_SAMPLE`. Báo cáo: [edu_alpha_18e8_experiment_report.md](./edu_alpha_18e8_experiment_report.md).
3. **`15567e02a806`:** OOS test chỉ có 9 trades (< 20 trades), không sweep tham số. Verdict: `INSUFFICIENT_SAMPLE`. Báo cáo: [edu_alpha_1556_experiment_report.md](./edu_alpha_1556_experiment_report.md).

### Batch B — Momentum / Breakout

1. **`14e3b934b1e5`:** C1 ROC-rising đã hoàn tất đối đầu Parent `20261027_192941_f36171` vs Cand `20261027_193324_1d0c42`. Test return: -27.78% → -27.76%, expectancy: -0.0804%, win rate: 36.5% → 34.4%, PF: 0.476 → 0.461. Verdict: `BETTER_ON_RESEARCH_WINDOW_NOT_PASS`. Báo cáo: [edu_alpha_14e3_experiment_report.md](./edu_alpha_14e3_experiment_report.md).
2. **`541c55834f56`:** Manifest liệt kê C1 (close top 25% bar range) và C2 (SMA50 filter); WFA record bị đánh dấu `UNVERIFIED / INVALID_FOLD_WINDOWS`. Không dùng số liệu fold đó để kết luận đạt/trượt gate; cần chạy lại bằng pipeline fold hợp lệ trước khi có verdict.
3. **`f261549d9efa`:** Manifest liệt kê C1 ROC-rising confirmation; WFA record `UNVERIFIED / INVALID_FOLD_WINDOWS`. Chưa có WFA verdict hợp lệ.
4. **`f4e211e9510d`:** Ghi nhận kiểm tra `donchian_upper` causal và C1 close confirmation trong artifacts; WFA record `UNVERIFIED / INVALID_FOLD_WINDOWS`. Chưa có WFA verdict hợp lệ.
5. **`cb750cb1eb10`:** OOS test chỉ có 18 trades (< 20 trades). Chuyển sang Batch E: `INSUFFICIENT_SAMPLE`.

### Batch C — Rebound / Mean-Reversion

Đã đánh giá candidate cho toàn bộ 7 alpha:
- `5e52d3fdf71f` (BB Overextension Exit)
- `6afa7f774655` (RSI Rebound with Fast SMA)
- `715e56a6dd33` (Linear Regression Channel)
- `7f67e9aed0aa` (Stochastic & RSI Confluence)
- `89379cc0ab52` (Stochastic Oscillator Bull Cross)
- `b4b65cd3493f` (Commodity Channel Index CCI)
- `c33cc317bbeb` (Multi-Day Cumulative Return Dip)

Các WFA records của nhóm này đều `UNVERIFIED / INVALID_FOLD_WINDOWS`. Vì fold không hợp lệ, các số như drawdown hoặc return sau stress không thể dùng để chốt `WFA_FAIL`; disposition hiện tại là `UNVERIFIED`, không phải bằng chứng candidate tốt hoặc xấu.

### Batch D — Entry/Exit, Risk & Volatility

- `3cfcc2d296a2` (Donchian Lower Channel Exit): WFA record `UNVERIFIED / INVALID_FOLD_WINDOWS`; chưa có verdict admission hợp lệ.
- `7f3486d63ca8` (Dual Oscillator Climax Exit): WFA record `UNVERIFIED / INVALID_FOLD_WINDOWS`; chưa có verdict admission hợp lệ.
- `717c1890c59e` (WMA Crossover): WFA record `UNVERIFIED / INVALID_FOLD_WINDOWS`; chưa có verdict admission hợp lệ.
- `b96bafe57445` (NATR Volatility Breakout): OOS test chỉ có 18 trades (< 20 trades). Chuyển sang Batch E: `INSUFFICIENT_SAMPLE`.

### Batch E — Baseline sample-limited dispositions (dừng tuning trên mẫu hiện có)

Các con số dưới đây là số trade trong baseline OOS/rebaseline đã ghi nhận, không phải kết quả WFA hợp lệ. Với dưới 20 trades, hoặc ledger không nhất quán, không tuning trên mẫu hiện có. WFA artifact riêng có 4 alpha `INSUFFICIENT_SAMPLE` và 19 `INVALID_FOLD_WINDOWS`; không gộp hai loại trạng thái.
- `4f28285aa44c`: 7 baseline OOS trades → dừng tuning do mẫu hiện có
- `15567e02a806`: 9 baseline OOS trades → dừng tuning do mẫu hiện có
- `270e6e28416f`: 17 baseline OOS trades → dừng tuning do mẫu hiện có
- `b96bafe57445`: 18 baseline OOS trades → dừng tuning do mẫu hiện có
- `cb750cb1eb10`: 18 baseline OOS trades → dừng tuning do mẫu hiện có
- `18e87aa868ad`: 19 rebaseline OOS trades (`exit_unit=pct`) → dừng tuning do mẫu hiện có
- `fa9587a97fa9`: 19 baseline OOS trades → dừng tuning do mẫu hiện có
- `bf519617d973`: 22 test / 9 simulate trades (ledger không nhất quán) → blocked chờ ledger reconciliation

Disposition hiện tại cho 8 alpha này là dừng tuning trên baseline/artifact hiện có do mẫu nhỏ hoặc ledger không nhất quán; không kết luận chiến lược đã được tối ưu, cũng không coi đây là WFA disposition hợp lệ. Chỉ mở lại khi có ledger/config/data evidence mới đáp ứng protocol; không sweep ngẫu nhiên.

### Deliverable và tiêu chí đóng từng alpha

- Mỗi alpha có parent freeze, test-stage ledger, code/config diff, candidate JSON, parent/candidate raw job receipts, fold/cost-stress table và report riêng.
- Candidate “pass” chỉ có nghĩa đạt gate WFA đã đăng ký trên development folds, không phải bảo đảm lợi nhuận tương lai. Chỉ data tương lai chưa xem mới có thể làm holdout một lần sau khi freeze; hiện trạng là `NO_UNTOUCHED_HOLDOUT_AVAILABLE`.
- Đóng một alpha ở `WFA_PASS_RESEARCH_ONLY`, `WFA_FAIL`, `NO_SUPPORTED_EVOLUTION`, `INSUFFICIENT_SAMPLE`, hoặc `BLOCKED` kèm artifact và lý do. Không promote/ghi đè alpha user; mọi quyết định promote cần owner approval riêng.
