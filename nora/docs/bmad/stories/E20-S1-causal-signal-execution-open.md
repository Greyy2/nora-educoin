# Story E20-S1: Thực thi tín hiệu tại open nến t+1 sau khi nến t đã đóng

## Status
Done

## Story
**Là** quant researcher, **tôi muốn** tín hiệu sinh ra tại cuối nến $t$ chỉ được thực thi tại giá Open của nến $t+1$, **để** loại bỏ hoàn toàn lookahead bias và phản ánh đúng thực tế trễ khớp lệnh.

## Acceptance Criteria
1. Bộ sinh tín hiệu nhận nến $t$ đã đóng đầy đủ giá $[Open, High, Low, Close, Volume]$.
2. Lệnh thị trường (Market Order) vào vị thế được khớp tại giá $Open_{t+1}$, không bao giờ khớp ở $Close_t$.
3. Các mức Stop-Loss và Take-Profit được kích hoạt bắt đầu từ nến $t+1$.
4. Tuyệt đối không sử dụng thông tin của nến $t+1$ trong quá trình tính toán tín hiệu tại nến $t$.

## Tasks / Subtasks
- [x] Rà soát và chuẩn hoá logic vòng lặp bar-by-bar trong engine (AC: 1, 2)
- [x] Đảm bảo timestamp của signal và execution được phân biệt rõ ràng (AC: 2, 3)
- [x] Chạy unit tests kiểm tra lệnh khớp tại Open t+1 (AC: 4)

## Dev Notes
- Tài liệu tham chiếu: [engine-spec.md](../architecture/engine-spec.md), [coding-standards.md](../architecture/coding-standards.md).
- File triển khai: `backend/core/backtest/engine.py`.
- Testing: `test/test_signal_event.py`, `test/test_causal_engine.py`.

## Dev Agent Record
- **Agent Model:** BMAD Senior Developer
- **Completion Notes:** Code P12 (`entry_event_mask`, `signal_mode`) đã được commit và kiểm chứng.
- **File List:**
  - `backend/core/backtest/engine.py`
  - `test/test_signal_event.py`
  - `test/test_causal_engine.py`

## QA Results
- **Gate:** PASS
- **Commit:** `64a7a43`, `6f54be2`
- **Tests:**
  - `pytest test/test_signal_event.py` PASS
  - `pytest test/test_causal_engine.py` PASS

## Change Log
| Ngày | Phiên bản | Mô tả | Người |
|---|---|---|---|
| 2026-10-07 | 1.0.0 | Đảm bảo strictly causal signal timing | BMAD Dev |
| 2026-10-09 | 1.0.1 | Chuyển sang Review, cập nhật test thật | BMAD Dev |
| 2026-10-09 | 1.0.2 | Hoàn tất nghiệm thu, chuyển sang Done với commit `64a7a43` | BMAD Dev |
| 2026-10-09 | 1.0.3 | Bổ sung commit `6f54be2` (tường minh atr_frame/cooldown cho DCA/Sideway) | BMAD Dev |

