# P14 — Strategy Risk Controller theo họ chiến lược + Execution Engine chuẩn Nautilus (plan + TODO triển khai)

Người triển khai: đọc HẾT file này trước khi sửa. Nguyên tắc bắt buộc:
- Kết quả khớp NautilusTrader (develop) — kiến trúc/code được khác (memory: nautilus-result-parity).
- Một định nghĩa cho mỗi logic (p9_ledger --dups = 0). Core không import ngoài core (test_layering strict = 0).
- Chạy mọi thứ qua `ops/run_limited.sh --no-lock --`; golden: `NORA_GOLDEN_DATA_ROOT=$PWD/data/market/binance`.
- Chiến lược/sổ không khai báo họ → profile `legacy` = hành vi hiện tại, kết quả BIT-IDENTICAL (golden + 50 mẫu + check_baseline không đổi).
- Không commit lẫn file người khác: `git diff --cached --name-status` trước mỗi commit.

## 0. Đính chính kết luận G3 (trường hợp B) — đọc trước

Báo cáo trước nói "Nora gặp SL 98 trước DCA 97". Đọc lại kernel thì SAI:
`backend/core/backtest.py` `_intrabar_path` (~563-680): mỗi chặng O→H/L→C là MỘT tick; trong tick thứ tự là
(a) mọi tầng DCA bị giá vượt qua → (b) chốt lời → (c) nhóm stop (SL/trailing/thanh lý); mức SL `sl_lv` tính MỘT lần từ giá TB đầu nến
(SL cũ còn hiệu lực trong nến). Đây CHÍNH LÀ thứ tự Nautilus (matching_core: lệnh limit trước stop trong cùng tick, stop dời có hiệu lực từ nến sau).
→ Với cùng bộ lệnh, ca B Nora = Nautilus: DCA 97 khớp rồi SL 98 đóng hết. Việc của P14-A là CHỨNG MINH bằng test lệnh, không phải sửa engine.
→ Vấn đề thật của ca B là CHIẾN LƯỢC: tầng DCA nằm sâu hơn SL — xử lý ở P14-B (Risk Controller), không ở engine.

Khuyến nghị đã chốt: engine giữ đúng ngữ nghĩa Nautilus (một chế độ duy nhất, không thêm chế độ "đường đi liên tục"); mâu thuẫn chiến lược bị chặn từ lớp Risk Controller trước khi lệnh tới engine.

---

## P14-A. Kiểm khớp core engine THUẦN với Nautilus (ở mức lệnh, không chiến lược) — kịch bản S15

Mục tiêu: tách bạch engine khỏi chiến lược. Đưa CÙNG danh sách lệnh + CÙNG nến 1m vào hai engine.

A1. Thiết kế harness `test/scripts/nautilus_diff/s15_*.py` (copy khuôn s11_*):
- `s15_cases.py`: định nghĩa ca bằng dữ liệu tổng hợp (DataFrame 1m nhỏ, vài chục nến, giá chọn tay) + danh sách hành động theo thời gian:
  `{"t": ms, "act": "open", "side": "LONG", "qty": ..}`, `{"act": "limit", "price": .., "qty": .., "reduce_only": bool, "tag": "dca1"}`,
  `{"act": "stop", "trigger": .., "reduce_only": True, "tag": "sl"}`, `{"act": "trailing", "offset_pct": .., "activation": ..}`,
  `{"act": "cancel", "tag": ..}`, `{"act": "replace", "tag": .., "price": ..}`, `{"act": "close"}`.
- Phía Nora: lớp thực thi dùng chung kernel — KHÔNG đi qua tín hiệu. Nếu chưa có API "đặt lệnh trực tiếp" cho KernelBook thì viết adapter test-only gọi đúng các hàm kernel (`_open`/`_add_layer`/`_close`/`_intrabar_path`) với trạng thái slot dựng tay, hoặc mở một entry point mỏng `KernelBook.submit_order(...)` (nếu thêm vào core: thuần, không I/O, có test).
- Phía Nautilus: strategy chỉ REPLAY danh sách hành động bằng lệnh native (MarketOrder, LimitOrder post-only khi cần, StopMarketOrder reduce-only, TrailingStopMarketOrder), `bar_execution=True`, adaptive/OHLC theo ca.
- `s15_compare.py`: so từng fill (thời điểm, giá, khối lượng, phí, loại), vị thế cuối, vốn; dung sai giá rel<1e-9, qty rel<1e-7 (+làm tròn 8 chữ số), vốn<1e-6.

A2. Ma trận ca (mỗi ca × OHLC và adaptive):
1. Một lệnh market; một limit chạm đúng mức; limit chạm thiếu 1 tick.
2. Limit + stop cùng nến, limit TRÊN stop (ca A) và limit DƯỚI stop (ca B) cho cả LONG và SHORT.
3. Nhiều tầng limit cùng bị vượt trong một chặng.
4. Gap mở cửa vượt qua stop; vượt qua limit (giá khớp = open hay = mức?).
5. Stop dời sau fill trong cùng nến (stop cũ còn hiệu lực).
6. Trailing kích hoạt và chạm trong cùng nến (đỉnh nến nâng mức trước khi chạm đáy).
7. Reduce-only vượt khối lượng vị thế; huỷ lệnh rồi giá chạm mức; sửa giá lệnh.
8. `limit_through_pct` = 0 và > 0 (chỉ đối chiếu khi =0; >0 xem G2 trong p13).
9. Thanh lý (giá thanh lý trong nến) — nếu Nautilus không tự thanh lý: ghi "ngoài phạm vi Nautilus", khoá bằng test Nora riêng.

A3. Với mỗi ca ghi bảng ngữ nghĩa (Nora file:dòng ↔ Nautilus `crates/execution/src/matching_engine/mod.rs` process_bar ~1880-2100, `matching_core.rs` iterate_*, doc `docs/concepts/backtesting/bar-execution.md`, `fill-prices-and-matching.md`).

A4. Kết quả mong đợi: tất cả khớp (theo mục 0). Ca nào lệch: DỪNG, báo lệnh lệch đầu tiên + bằng chứng; sửa engine theo Nautilus chỉ sau khi duyệt; mọi golden đổi phải giải thích.

A5. Hoàn tất: thêm S15 vào `check_baseline.py` (đọc lại `p94b_baseline.sha256` ngay trước `--write`), README + EXT_REPORT mục S15. Sửa lại EXT_REPORT/E21-S3 phần "ca B khác nhau" thành "giống nhau, chứng minh bởi S15".

Xong khi: s15_compare all MATCH; check_baseline ok; không đổi backend (trừ entry point submit_order nếu cần, có test).

---

## P14-B. Strategy Risk Controller theo họ chiến lược

### B1. Kiểm kê hiện trạng (bắt buộc làm trước, ghi vào `docs/bmad/p14_inventory.md`)
Liệt kê mọi tham số rủi ro/phân bổ, nơi định nghĩa, nơi dùng, phạm vi (chung toàn hệ / theo chiến lược):
- `core/params.py`: `POSITION_KEYS` (~332), `BASE_POSITION` (~496), `RISK` (~523), `resolve_position_auto`, `build_params` (~425), `dca_budget_check` (~371), `materialize` (~555).
- `core/position_size.py`: `SlotSpec` (~308), `risk_margin`/`flat_margin`/`clamp_margin`/`planned_risk_cap`/`apply_risk_ceiling` (~197-240), `admit_entry` (~270), `kill_triggered` (~297), `sl_level`/`dca_level`/`tp_level`/`trail_*`/`liq_price`.
- `core/backtest.py`: `RiskConfig` (~3222), `_admit` (~997), `_portfolio_bar` (~1085), `_on_bar_open`/`_on_bar_rest` (~811/830), `_intrabar_path`/`_intrabar_adverse` (~563/690), `_layer_cost/_layer_apply` (~247/270), `build_plan` (~3824), `_make_slots` (~3322), `entry_event_mask` (~2872).
- `optimize/book/build.py` (RISK của sổ, sizing), `optimize/funnel/stages.py` (S5 sizing), `live/live.py` (bot dùng cùng SlotSpec).
- Chiến lược hệ thống `data/alpha/strategies/{kema,sideway,dca}.py`, 50 mẫu `data/alpha/education/samples.json`.
Kết quả: bảng "khoá | mặc định | ai đặt | ngữ nghĩa hiện tại | áp cho họ nào".

### B2. Định nghĩa `RISK_PROFILES` (MỘT chỗ: `backend/core/position_size.py`)
Mỗi profile là dataclass bất biến, khoá theo tên họ. Khuyến nghị nội dung:

| Họ | Ý tưởng | Neo SL | DCA | Thoát cho phép | Sizing mặc định | Vào lại | Luật kiểm hợp lệ |
|---|---|---|---|---|---|---|---|
| `legacy` | hành vi hiện tại | `avg` (% từ giá TB, như nay) | cho phép như nay | mọi kiểu | như nay | như nay | không thêm luật (bit-identical) |
| `trend` | theo xu hướng | `entry` hoặc `avg` (không DCA nên trùng) | KHÔNG | tín hiệu, trailing, SL, TP tuỳ chọn, timeout tuỳ chọn | `risk` theo khoảng SL | sự kiện tín hiệu + cooldown 1 nến | cấm `dca_*`; bắt buộc SL hoặc trailing |
| `breakout` | phá vỡ vùng | `entry` | KHÔNG | SL, trailing, timeout (bắt buộc ≥1 trong trailing/timeout), tín hiệu | `risk` | sự kiện | cấm `dca_*`; SL bắt buộc |
| `mean_reversion` | hồi về TB | `avg` | cho phép GIỚI HẠN (≤ 2 tầng) | TP về TB/ tín hiệu, SL rộng, timeout | `risk` tính trên cả rổ | sự kiện | nếu có DCA: mọi tầng nằm TRƯỚC SL; SL bắt buộc |
| `dca` | gồng lỗ kéo giá TB | `last_layer` (mức SL = mức tầng cuối × (1 ∓ `sl_beyond_last_pct`)) hoặc `none` (không SL, chỉ ngân sách vốn + thanh lý/kill) | BẮT BUỘC ≥ 1 tầng | TP theo giá TB, tín hiệu, timeout tuỳ chọn | `margin_pct`/ngân sách rổ: tổng vốn cả thang ≤ ngân sách | sau khi đóng rổ | tầng cuối nằm TRƯỚC SL; tổng margin cả thang ≤ ngân sách (`dca_budget_check`); trailing chỉ sau khi đủ điều kiện TP |
| `grid` (tuỳ chọn, để sau) | lưới hai chiều | `none` | lưới | TP từng ô | ngân sách | — | — |

Trường mỗi profile (ví dụ): `name, label_vi, sl_anchor ∈ {entry, avg, last_layer, none}, sl_required, dca ∈ {forbidden, limited(n), required}, exits_allowed, exits_required_any, sizing_default, reentry ("event" + cooldown rule), portfolio_bucket, validate(position) -> list[issue]`.
`validate` trả lỗi có mã + câu tiếng Việt + gợi ý (dùng cho contract/assist).

### B3. Engine: hỗ trợ SL MỨC TUYỆT ĐỐI (để neo `entry`/`last_layer`)
Hiện kernel tính `sl_lv = F_AVG × (1 − sign·F_SL/100)` mỗi nến (neo giá TB). Thêm:
- Cột trạng thái `F_SL_LEVEL` (mức tuyệt đối) + cờ `PI_SL_ANCHOR` (0 = avg như cũ, 1 = mức tuyệt đối).
- Khi `PI_SL_ANCHOR=1`: `sl_lv = F_SL_LEVEL`; Risk Controller (SlotSpec/khi vào lệnh và khi có fill DCA) đặt mức. Với `last_layer`: tính tại lúc vào lệnh từ mức tầng cuối dự kiến (`dca_level` chuỗi) — cố định cả vị thế.
- Áp đúng ở MỌI nơi dùng SL: `_intrabar_path`, `_intrabar_adverse`, `planned_risk_cap`/`risk_margin` (khoảng SL để sizing), `_admit` (open risk), live `KernelBook`, `test/reference_engine.py`, notes/explain (mô tả SL đúng neo).
- `legacy` → `PI_SL_ANCHOR=0` → bit-identical.
- Đây là ngữ nghĩa engine "stop tại giá X" — đúng kiểu Nautilus (StopMarket tại trigger price).

### B4. Gắn profile vào chiến lược
- `POSITION_KEYS` thêm `risk_profile` (+ `sl_beyond_last_pct` nếu dùng neo last_layer). Mặc định `legacy`.
- `SlotSpec` đọc profile → chuẩn hoá tham số theo profile → set cờ engine.
- DSL (`backend/alpha/contract.py` + `compile.py`): thuộc tính lớp `risk_profile = "dca"`; `check_contract` gọi `profile.validate` → REJECT (mâu thuẫn, kèm gợi ý sửa) hoặc ADAPT (vd đề xuất `sl_anchor=last_layer`); assist catalog có mục profile + hover giải thích.
- Chiến lược hệ thống: `kema.py` → `trend`, `sideway.py` → `mean_reversion`, `dca.py` → `dca`. LƯU Ý: đổi profile làm đổi kết quả → làm ở bước riêng, golden/sổ dựng lại có giải thích; trước đó giữ `legacy`.
- 50 mẫu: khai báo `risk_profile` theo nhóm (trend_*, breakout_*, revert_*, confluence_* → theo ý tưởng; risk_* → theo cơ chế), sửa tham số vi phạm luật.

### B5. Phân bổ vốn danh mục theo họ
- `RISK` (max_positions 8, max_per_symbol 1, gross 3, kill 30%, open risk 6%, dd throttle) hiện dùng chung. Thêm `ALLOCATION` theo bucket/profile: ngân sách vốn %, trần rủi ro mở %, số vị thế tối đa theo bucket; tổng ≤ giới hạn danh mục.
- `_admit`/`admit_entry` kiểm thêm trần theo bucket (một hàm duy nhất). `legacy` → không bucket → bit-identical.
- Sổ (`optimize/book/build.py`) và funnel S5 sizing đọc allocation.

### B6. Meta + UI
- `/api/studio/meta`: `risk_profiles` (tên, label_vi, luật, mặc định) + `allocation`; UI (Studio cài đặt chạy, trang chiến lược, funnel) hiển thị profile; assist dùng meta.

---

## P14-C. Kiểm chứng

C1. Test đơn vị mỗi profile (`test/test_risk_profiles.py`):
- `dca` neo last_layer: giá 100 → 96 (qua tầng 99, 97) → bật 130: các tầng khớp, KHÔNG bị cắt sớm, TP theo giá TB khớp; biến thể rơi qua mức SL sau tầng cuối → đóng đúng mức.
- `dca` + SL mâu thuẫn (SL trên tầng) → contract REJECT với gợi ý.
- `trend` có `dca_*` → REJECT. `breakout` thiếu trailing/timeout → REJECT.
- sizing `risk` dùng đúng khoảng SL theo neo.
C2. Engine: test `PI_SL_ANCHOR=1` vs kỳ vọng tính tay; reference engine cùng kết quả (test_kernel_parity); live KernelBook step = batch.
C3. Kịch bản Nautilus theo profile `s16_*`: phía Nautilus strategy dùng CÙNG luật Risk Controller (đặt StopMarket tại mức tuyệt đối, LimitOrder các tầng) → so từng lệnh. Tách bạch S15 (engine).
C4. Bất biến: `legacy` → golden, 50 mẫu, check_baseline (S1–S15) không đổi một bit. Profile mới: golden riêng.
C5. Sau khi chuyển chiến lược hệ thống/mẫu sang profile: chạy lại 50 mẫu (đường nút Run), funnel nhỏ, dựng lại sổ (needs_rebuild), báo trước/sau.
C6. Cổng cuối: full pytest 1 lượt, test_layering strict, p9_ledger --dups 0, check_baseline ok, npm run build.

## Thứ tự & điểm dừng duyệt
1. P14-A (S15) → báo bảng ngữ nghĩa + kết quả. [không đổi backend]
2. B1 kiểm kê → B2 bảng profile → **anh duyệt bảng**.
3. B3 engine neo SL tuyệt đối (legacy bit-identical) → B4 gắn profile (legacy mặc định) → B5 allocation → B6 meta/UI.
4. C1–C4 → **anh duyệt** chuyển chiến lược hệ thống + mẫu sang profile → C5 → C6.

## Không được làm
- Không thêm chế độ engine thứ hai trái ngữ nghĩa Nautilus.
- Không đổi kết quả `legacy`.
- Không sửa engine để "chữa" lỗi chiến lược — chặn ở Risk Controller.
- Không đặt luật profile rải rác (chỉ trong RISK_PROFILES + validate).
