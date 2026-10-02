# E15-S1 — Regime thị trường: đặc tả (P2.1–P2.4)

**Mục tiêu.** Sổ có nhiều chiến lược. Mỗi chiến lược chỉ vào lệnh trong trạng thái thị trường (regime) mà nó được thiết kế cho. Khi giá chạy thẳng đứng ngược chiều vị thế, sổ cắt lệnh trước khi thang DCA bị thanh lý. Kiểu cháy tài khoản của các bot OKX nhồi lệnh xảy ra đúng lúc trend thẳng đứng; regime là lớp chặn chuyện đó.

## 1. Nguyên tắc

- **Một đường dữ liệu.** Đặc trưng regime là cột kernel (`core/signals/kernels.py`). Chúng đi qua đúng bộ máy căn khung của engine (`BacktestEngine.extra_refs` → `_refs_by_frame` → warmup theo khung → `_build_matrix`). Khung lớn chỉ dùng nến **đã đóng**. Không có bản tính thứ hai.
- **Nhân quả.** Nhãn ở phút *t* chỉ phụ thuộc dữ liệu ≤ *t*. Đã kiểm bằng `test_regime.py::test_regime_is_causal`: thêm 12 ngày dữ liệu tương lai thì toàn bộ tiền tố nhãn không đổi.
- **Golden bất biến.** Chiến lược không có khoá `regime` thì engine chạy y nguyên, vì regime chỉ áp qua mặt nạ `match` / `stop` trong `PortfolioEngine.load_data`, còn kernel numba không đổi. Đã kiểm bằng `test_regime_allow_all_without_fuse_is_identical`, `test_golden_results.py` và `test_kernel_parity.py`.
- **Dùng lại cho live/testnet.** `core/signals/snapshot.py` tính regime bằng cùng hàm `classify` tại nến 1m đã đóng cuối.

## 2. Đặc trưng

| Khung | Cột | Ý nghĩa |
|---|---|---|
| 4h | `er_20` | Kaufman efficiency ratio: độ "thẳng" của xu hướng (0..1) |
| 4h | `adx_14` | Độ mạnh xu hướng (Wilder) |
| 4h | `ema_50`, `ema_200` | Chiều xu hướng |
| 1h | `roc_24` | Lợi suất 24h (%) |
| 1h | `roc_1` | Lợi suất của nến 1h vừa đóng (%) |
| 1h | `bbwp_20_2_720` | Phân vị độ rộng Bollinger trong 30 ngày (0..100) |

## 3. Trạng thái (ưu tiên từ trên xuống) — `core/regime/classifier.py::raw_states`

| Mã | Tên | Điều kiện (mặc định) |
|---|---|---|
| 6 | CRASH | `roc_24 ≤ −12` hoặc `roc_1 ≤ −5` |
| 5 | SURGE | `roc_24 ≥ +12` hoặc `roc_1 ≥ +5` |
| 4 | VOL_EXPANSION | `bbwp ≥ 90` |
| 2 / 3 | TREND_UP / TREND_DOWN | `er ≥ 0.30` và `adx ≥ 20`; chiều theo `ema_50` so với `ema_200` |
| 1 | RANGE | còn lại (đủ đặc trưng) |
| 0 | UNKNOWN | thiếu đặc trưng (đang warmup) |

Ngưỡng nằm trong `classifier.DEFAULTS`. Mọi tham số này được tính là trial trong DSR/PBO (P2.7) khi chúng được tối ưu.

## 4. Chống nhảy — `smooth`

- Trạng thái thường (RANGE / TREND / VOL_EXPANSION) phải giữ liên tục **≥ 180 phút** thì mới được nhận. Nếu bị chen ngang bởi trạng thái thô khác, bộ đếm bắt đầu lại từ đầu.
- CRASH / SURGE được nhận **ngay** và giữ **≥ 360 phút** kể từ phút cuối còn tín hiệu sốc. Hết thời gian giữ thì nhận ngay trạng thái nền.
- Chi phí: chỉ duyệt các điểm đổi trạng thái thô, nên với nhiều năm dữ liệu 1m vẫn hết khoảng mili-giây.
- Snapshot dùng cửa sổ 3 ngày. Bộ nhớ của luật chống nhảy ≤ 6 giờ, nên nhãn hội tụ về đúng nhãn của backtest toàn lịch sử.

## 5. Ghép regime ↔ chiến lược — `core/strategy/book.py::REGIME_MAP`

| Chiến lược | Regime được vào lệnh | Cầu chì |
|---|---|---|
| trend_long, momentum_long | TREND_UP, SURGE | CRASH → thoát |
| trend_short | TREND_DOWN, CRASH | SURGE → thoát |
| breakout_4h_long | TREND_UP, VOL_EXPANSION, SURGE | CRASH → thoát |
| breakout_4h_short | TREND_DOWN, VOL_EXPANSION, CRASH | SURGE → thoát |
| reversion_long, reversion_short | RANGE | sốc ngược chiều → thoát |

- **Áp dụng.** `match &= allowed`; `stop |= fuse`. Tín hiệu thoát đóng lệnh ở nến sau, gồm cả thang DCA, nên lệnh không bị nhồi tiếp khi trend thẳng đứng.
- **Bật.** Dùng `materialize(..., regime=True)`, `run(..., regime=True)` hoặc `POST /api/studio/book/backtest {"regime": true}`. Mặc định là tắt, và chỉ bật mặc định sau khi báo cáo P2.4 xác nhận.

## 6. Đo độ chuẩn (P2.4) — `core/regime/report.py`, job `regime_report`, `POST /api/studio/market/regime/report`

- **A. Theo từng nhãn:** tỷ trọng thời gian, số đợt, thời lượng, số lần đổi trong 30 ngày, và lợi suất 24h *tiếp theo* (trung bình, trung vị, % dương, |r|).
  - Kỳ vọng: TREND_UP có lợi suất tiếp theo > 0, TREND_DOWN < 0, RANGE có |r| nhỏ.
- **B. Sự kiện thẳng đứng** (định nghĩa sau sự việc: |lợi suất 24h tới| ≥ 12%):
  - recall phát hiện CRASH / SURGE;
  - độ trễ (phút);
  - phần trăm quãng giá đã đi trước khi phát hiện;
  - tỷ lệ cảnh báo mà giá tiếp tục cùng chiều sốc trong 24h sau đó.
- **C. Sổ preset tắt / bật regime:** chạy trên cùng dữ liệu. So sánh lãi, MDD, Sharpe, số lệnh, và lãi/lỗ theo (chiến lược × regime lúc vào lệnh) để kiểm chứng `REGIME_MAP`.

## 7. Tiêu chí chấp nhận

- [x] Test nhân quả, test chống nhảy, test thứ tự ưu tiên, test mặt nạ, test "cho phép tất cả = engine gốc" (`test/test_regime.py`).
- [x] Snapshot thị trường trả `regime` (state, nhãn, raw, since, giá trị đặc trưng); mỗi chiến lược có `entry_raw`, `regime_ok`.
- [ ] Báo cáo P2.4 trên 8 tài sản thật. Đạt khi:
  - bật regime thì MDD giảm;
  - lãi không giảm quá 20% tương đối;
  - CRASH recall ≥ 60%.
