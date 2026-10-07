# P9.4b — Một engine thực thi duy nhất (kernel cho backtest, paper, live)

Ngày: 2026-10-07 · Chủ: norabt-e2 (logic) · Kiến trúc: ADR-P9 "Một engine thực thi duy nhất" · Tham chiếu đúng/sai: NautilusTrader (test/scripts/nautilus_diff S1–S8)

## 1. Đích

- Kernel numba trong `backend/core/backtest.py` là engine DUY NHẤT.
  - Backtest: chạy cả lô nến (như nay).
  - Paper: gọi cùng kernel TỪNG NẾN, trạng thái nằm trong mảng; khớp ngay trong kernel; trùng từng bit với backtest cùng chuỗi nến.
  - Live: kernel sinh ý định lệnh; OKX khớp; fill thật ghi ngược vào trạng thái kernel. Sàn là nguồn sự thật về fill/vị thế; SL/TP/DCA là lệnh đặt sẵn trên sàn, phản chiếu mức của engine.
- Gỡ: `core/execute/{tracker,manager,sim_venue,runner}.py`, `PositionBook`, nửa event-path của `models.py`. `venue.py` chỉ còn I/O và chuyển vào `live/okx_venue.py`. `test/reference_engine.py` giữ làm oracle trong test.

## 2. Quyết định (chốt 2026-10-07 theo khuyến nghị, người dùng uỷ quyền "theo recommend")

| # | Quyết định |
|---|---|
| a | Bỏ engine thực thi legacy trong `bot.py` (`_open_exec`, `_protect`, `step_exec`) ở P9.4b. |
| b | Bóng (shadow) của bot demo = KernelBook SIM; bỏ kiểm post-only của SimVenue. |
| c | Sau mỗi fill DCA đặt lại SL/TP ngay (như unified hiện nay); chênh lệch so với "SL cố định cả nến" được đo, không giấu. |
| d | Đặt toàn bộ thang DCA còn lại (`ladder()`), không chỉ tầng kế tiếp. |
| e | Funding lấy từ hoá đơn sàn (bills); không tự tính khi có số sàn. |
| f | Đóng một phần dùng kế toán mới `F_PREAL` (chỉ nhánh live). |
| g | Kernel ghi `OrderModel.slippage` (hôm nay luôn 0 — lỗi). |
| h | Oracle AMM: mở rộng `reference_engine` bằng bản sao đóng băng nhánh `limit_taker`/`impact_fn` của tracker, ngoài golden tick. |
| i | Chấp nhận `engine_version`/`code_version` đổi → mọi sổ bị gắn "cần dựng lại" dù kết quả trùng; dựng lại sổ sau P9.4b. |

## 3. Các bước (mỗi bước một commit; cổng G* bắt buộc)

**Cổng G\*:** golden (`NORA_GOLDEN_DATA_ROOT=data/binance`), `test_kernel_parity`, `test_skip_idle`, `test_runner_parity` + `test_event_path_parity` (tới T9), `test_venue_conformance`, `test_okx_venue`, `test_live_bot`, `test_bot_unified`, `test_compare_events`, `test_tick_backtest`, `test_tick_golden`, baseline sha nautilus (T0), `bench_engine.py compare` ≤ +5% thời gian/alpha (mốc P9.4 phần 1: 1,10 s).

| # | Việc | Test mới |
|---|---|---|
| T0 | Mốc: nautilus `run_nora`/`ext_run_nora` ohlc+adaptive, `compare`/`ext_compare` → `nautilus_diff/p94b_baseline.sha256`; golden tick từ đường tracker hiện nay; fixture 5 pickle bot; số bench | `test_tick_golden.py`, `make_golden_tick.py` |

**T0 – ghi chú (2026-10-07):** bench `bench_engine.py compare` (mặc định, kema_long, 8 perp, dev1, 1m): **1,083 s/alpha** (load_data 0,726 + kernel 0,332; lô 100 = 0,159 s/alpha; engine cũ 22,15 s) — mốc để so ≤ +5% (≤ 1,137 s). Nautilus: `python test/scripts/nautilus_diff/check_baseline.py` (332 sha; `--write` để sinh lại). Golden tick: `test/golden/tick_*.json` (7 thị trường giả + 20 cấu hình seed). Fixture bot: `test/fixtures/live_state_p94b/` (6 file pkl của 5 bot, `SHA256SUMS`; `*.pkl` bị .gitignore nên cần `git add -f`). Cổng G* trên code hiện tại: 229 passed, 5 skipped (3 caps của venue + 2 test chạm OKX Demo thật), 0 fail; check_baseline 332/332 ok.
| T1 | Trạng thái danh mục thành mảng (PS/PSI/LPX); tách `_admit`, `_portfolio_bar`, `_portfolio_end`; vòng batch gọi thân chung | — (nautilus sha trùng) |
| T2 | Tách `_add_layer`/`_close` thành cost + apply; `ordF` 5 cột (OR_RAW, OR_SLIP); điền `OrderModel.slippage` | slippage kernel == tracker |
| T3 | `step_bars`, `slot_bar`, `slot_funding`, `mtm`, `close_all`; `KernelBook` (SIM, save/load npz+json, events); `SlotDriver`; vết admission | `test_kernel_step_parity.py` (batch == step từng nến/khúc ngẫu nhiên/save-load; == PaperBook cũ; SlotDriver == tracker) |
| T4 | `SlotSpec` (chuẩn hoá tham số y hệt `PositionTracker.__init__`) + `SlotView`; `pack_slots`; `_ID_SEQ` → `models.next_id` | thông báo lỗi không đổi |
| T5 | Nautilus `run_nora`/`ext_run_nora` chạy trên SlotDriver/KernelBook | nautilus sha trùng S1–S8 |
| T6 | AMM vào kernel (port njit, `math.pow`, bỏ import crawl khỏi core); TickBook trên KernelBook | `test_amm_njit_bitwise`; golden tick trùng byte |
| T7 | Paper trên KernelBook; `paper.json` + npz; `state_migrate.py` (unpickler hạn chế); router đọc JSON; chạy bóng song song | `test_state_migrate.py` |
| T8 | Hàm live trong kernel (intent, apply entry/dca/close/reduce, reject, bar close, levels, ladder) | `test_live_writeback_equiv.py` (+ khớp một phần, reject, amend, reduce, funding) |
| T9 | `okx.py` clOrdId/cancel/query/fills/bills; `okx_venue.py` chỉ dịch I/O; `unified.py` theo §4.1 (ghi trước ý định, adopt khi khởi động) | viết lại `test_bot_unified`; `test_live_reconcile.py` |
| T10 | Xoá tracker/manager/sim_venue/runner/PositionBook, engine legacy trong `bot.py`, tham số `engine` của router, `_CODE_FILES`; chuyển test sang SlotDriver | toàn bộ suite; grep import cũ rỗng |
| T11 | Triển khai: paper chuyển sau 48 h bóng 0 lệch; demo "adopt" (dừng bot unified, lưu trữ pickle, chuyển trạng thái); cập nhật tài liệu | compare_events trong EVENT_BUDGETS |

Chi tiết thiết kế (API kernel từng nến, vòng live tại mỗi mốc nến, clOrdId, khôi phục khi khởi động lại, AMM, chuyển trạng thái): báo cáo lập kế hoạch ngày 2026-10-07 — tóm tắt ở các mục trên; khi một bước cần chi tiết, đặc tả bước đó được viết kèm khi giao việc.

## 4. Rủi ro chính

- Hiệu năng khi tách thân nến thành hàm (T1): đo bench mỗi bước.
- `-0.0` và vệ sinh nhánh: mọi số hạng mới chỉ cộng trong nhánh live.
- Trạng thái bot đang chạy: không bao giờ chạy hai bot trên một tài khoản; pickle cũ chỉ lưu trữ, không xoá.

**T1 – ghi chú (2026-10-07).** Trạng thái danh mục thành mảng (PS/PSI/LPX), thân nến `_portfolio_bar` (28 tham số: numba gọi hàm ≥ 30 tham số theo đường chậm ~460 ns/lần so với ~28 ns — mọi hàm theo nến mới phải ≤ 28 tham số; `_on_bar` hiện 29). Kết quả trùng từng bit (cổng G*, nautilus 332/332). Tốc độ: kernel một alpha 0,344 s (+3% so với T0), chạy lô 100 alpha 0,167 s/alpha (+5%) — chấp nhận vì bước điền BAR/BARI/SIG theo nến là hợp đồng cần cho T3; theo dõi lại ở T3.
