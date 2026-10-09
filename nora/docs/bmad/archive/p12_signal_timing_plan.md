# P12 — Thời điểm tín hiệu khung lớn + mặc định ATR/cooldown theo khung (plan + todo)

Căn cứ (2026-10-08): mô phỏng độc lập trend_kema_breakout khớp engine từng lệnh; so sánh Nora / NautilusTrader (Rust rc7 source + harness nautilus_diff) / Sova (`sova/backend`).

## Kết luận đã chốt
| # | Vấn đề | Tham chiếu | Quyết định |
|---|---|---|---|
| 1 | Tín hiệu khung lớn (vd 24h) là TRẠNG THÁI trên mọi nến base 1m suốt 1440 phút → cắt lỗ + hết cooldown 60' là mua lại cùng breakout (48/202 lệnh ở mẫu KEMA) | Nautilus: `on_bar(daily)` 1 lần/ngày; Sova: cross 1 nến + dedup (`kema.py:53-82`, `broker.py:456`) | **SỬA**: tín hiệu VÀO của khung > base chỉ kích ở nến base đầu tiên sau khi nến khung tín hiệu đóng |
| 2 | Cùng phút, coin xử lý tuần tự (thoát→vào từng coin) | Nautilus xử lý từng instrument tuần tự, không barrier (`engine.rs:926-942`); harness S8 khớp Nora tới cent | **GIỮ NGUYÊN** |
| 3 | `atr_frame` mặc định "1h", cooldown 60' bất kể khung | Sova: ATR cùng khung chiến lược tại nến tín hiệu (`position_sizer.py:1180`, `broker.py:492`) | **SỬA mặc định**: atr_frame = khung tín hiệu; cooldown = 1 nến khung tín hiệu. Giá trị khai báo tường minh giữ nguyên |
| 4 | Harness Nautilus chưa có kịch bản đa khung/cooldown/ATR | — | **THÊM S9** |

Giữ nguyên (đã đúng/ chặt hơn tham chiếu): khớp lệnh ở open nến base kế tiếp (= Sova); cắt lỗ kiểm trên đường 1m trong nến (chính xác hơn Sova); quy tắc P6.12 (cắt lỗ trong nến không trả chỗ cho lệnh vào cùng open).

## TODO (thứ tự thực hiện)

### A. Sửa (1) — tín hiệu vào kích theo sự kiện nến khung tín hiệu  [logic engine]
- [ ] A1 Tại nơi dựng mask tín hiệu từ cột đã gather (`core/backtest.py` ~3014-3063, `align_index`/`gather`): với mỗi cây điều kiện VÀO có khung > base, tạo `fresh = (idx != idx_prev)` theo khung đó; `entry_mask &= fresh_of_signal_frame`. Khung tín hiệu của một cây = khung lớn nhất trong các lá của cây (nếu cây trộn khung: dùng khung lớn nhất). Không áp cho cây THOÁT/STOP (trạng thái).
- [ ] A2 Một định nghĩa duy nhất: hàm `entry_event_mask(mask, frame_idx)` trong core/backtest.py; mọi đường dùng chung: kernel batch (`_on_bar_rest` + vòng quét nhanh ~1350), `KernelBook`/`SlotDriver` (paper/live), `signal_snapshot`/`evaluate_signals`, `test/reference_engine.py` (parity).
- [ ] A3 Chặn ở nến vừa đóng vị thế giữ như cũ (`closed is None`); lệnh vào bị chặn đúng phút đó (cooldown/đủ vị thế/rủi ro) thì MẤT (như Nautilus/Sova) — ghi vào docstring.
- [ ] A4 Cờ cấu hình `signal_mode` mặc định "event" (giá trị "level" giữ hành vi cũ để tái tạo kết quả lịch sử); đưa vào ENGINE fingerprint.
- [ ] A5 Test mới: (a) chiến lược 24h trên base 1m: cắt lỗ trong ngày → không vào lại tới nến ngày kế; (b) khung = base: kết quả bit-identical với trước; (c) mask trộn khung; (d) live KernelBook cùng hành vi batch (step == batch).

### B. Sửa (3) — mặc định ATR/cooldown theo khung tín hiệu  [logic params]
- [ ] B1 `core/params.py`: `atr_frame` mặc định "auto" → giải theo khung tín hiệu của chiến lược khi dựng params (build_params / build_plan); `cooldown` mặc định "auto" → FRAME_MS[khung tín hiệu] (phút). Sửa `int(position.get("cooldown") or 0)` để phân biệt "không khai báo" với 0.
- [ ] B2 `/meta`, assist catalog, explain_program, annotate: hiển thị giá trị đã GIẢI (vd "ATR 24h"), không ghi "1h" cố định.
- [ ] B3 50 mẫu education: bỏ dòng `atr_frame = "1h"` / `cooldown = 60` nếu chỉ là mặc định cũ → để "auto" (hoặc ghi tường minh theo khung chiến lược) + câu ý tưởng nêu rõ cắt lỗ theo ATR khung ngày; 4 mẫu risk_* đã dùng "24h" giữ.
- [ ] B4 Test: chiến lược 24h không khai báo → atr_frame 24h, cooldown 1440; khai báo tường minh → giữ nguyên.

### C. Kịch bản Nautilus S9  [kiểm chứng]
- [ ] C1 `test/scripts/nautilus_diff/`: S9 = 2 coin, nến 1m + tín hiệu 1D (ts on close, stream priority), cắt lỗ trong ngày khi tín hiệu ngày vẫn đúng, ATR khác khung (dùng % nếu ATR không mô phỏng được bên Nautilus — ghi rõ), max_positions=1.
- [ ] C2 Chạy Nautilus (`~/.venvs/nautilus`) + Nora; khớp lệnh/giá/vốn; thêm vào `check_baseline` sau khi duyệt.

### D. Dựng lại baseline + dữ liệu
- [ ] D1 Golden: chạy với cờ mới; mọi thay đổi phải giải thích bằng (1)/(3) (diff theo lệnh: chỉ mất lệnh mua lại tín hiệu cũ / đổi khoảng cắt lỗ). Dựng lại `test/golden*`, `test_kernel_parity` (reference engine sửa cùng), `test_dca_cooldown`.
- [ ] D2 `check_baseline` S1–S8 phải KHÔNG đổi hash (khung = base, cooldown 0, % stops). Nếu đổi → dừng, tìm nguyên nhân.
- [ ] D3 Chạy lại 50 mẫu qua đúng đường nút Run: không mẫu nào 0 lệnh; báo bảng trước/sau (số lệnh, % thoát vì cắt lỗ, MDD).
- [ ] D4 Education giải thích: thêm 1 câu tính từ kết quả khi có lệnh bị chặn bởi giới hạn vị thế (`rejected_for_risk` > 0): "N lần tín hiệu bị bỏ qua vì đã giữ đủ 8 vị thế".
- [ ] D5 Sổ main/explore: needs_rebuild bật (fingerprint đổi) → dựng lại khi anh quyết (bot đang dùng sổ).

### E. Chốt
- [ ] E1 Full pytest 1 lượt (4 nhóm song song, golden + layering strict), nautilus check_baseline, p9_ledger --dups 0.
- [ ] E2 Khởi động lại nora-api; bot live chỉ nhận engine mới khi khởi động lại (hỏi anh trước).

## Phân công (chạy song song, không đụng file nhau)
- Worker 1 (Sonnet/medium): A1–A5 (core/backtest.py, test/reference_engine.py, tests).
- Worker 2 (Sonnet/medium): B1–B4 (core/params.py, alpha/*, routes meta, samples.json, tests) — chỉ đụng backtest.py ở chỗ giải atr/cooldown nếu bắt buộc, phối hợp qua coordinator.
- Worker 3 (Sonnet/medium): C1–C2 (harness, không đụng backend).
- Sau khi 1+2 xong: D1–D5 (một worker), rồi E (coordinator).
Ước lượng: A/B/C song song ~1 giờ; D ~1 giờ (50 mẫu chạy lại ~8 s/mẫu); E ~15 phút.
