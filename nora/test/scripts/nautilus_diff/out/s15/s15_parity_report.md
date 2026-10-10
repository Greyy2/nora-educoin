# Báo Cáo Đối Chiếu Parity Core Execution Engine (S15)

So sánh trực tiếp kết quả khớp lệnh giữa **Nora Core Execution Engine** và **NautilusTrader Native BacktestEngine** trên 15 kịch bản nến tổng hợp (30 runs).

| STT | Mã ca | Chế độ | Mô tả | Fills | Equity (USDT) | Sai số Px (rel) | Sai số Phí | Kết quả |
|---|---|---|---|---|---|---|---|---|
| 1 | `C1a_market` | `ohlc` | Lệnh market vào vị thế ở open | 1 | 9999.9500 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 2 | `C1a_market` | `adaptive` | Lệnh market vào vị thế ở open | 1 | 9999.9500 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 3 | `C1b_limit_touch` | `ohlc` | Limit TP chạm đúng mức trong nến | 2 | 10001.9296 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 4 | `C1b_limit_touch` | `adaptive` | Limit TP chạm đúng mức trong nến | 2 | 10001.9296 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 5 | `C1c_limit_miss` | `ohlc` | Limit TP thiếu 0.01 không khớp | 1 | 9999.9500 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 6 | `C1c_limit_miss` | `adaptive` | Limit TP thiếu 0.01 không khớp | 1 | 9999.9500 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 7 | `C2a_long_dca_above_sl` | `ohlc` | LONG: DCA 99.0 trên SL 98.0, nến rơi 96.0 | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 8 | `C2a_long_dca_above_sl` | `adaptive` | LONG: DCA 99.0 trên SL 98.0, nến rơi 96.0 | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 9 | `C2b_long_dca_below_sl` | `ohlc` | LONG ca B: DCA 97.0 dưới SL 98.0, nến rơi 96.0 | 3 | 9998.8614 | 0.0e+00 | 3.9e-09 | ✅ PASS |
| 10 | `C2b_long_dca_below_sl` | `adaptive` | LONG ca B: DCA 97.0 dưới SL 98.0, nến rơi 96.0 | 3 | 9998.8614 | 0.0e+00 | 3.9e-09 | ✅ PASS |
| 11 | `C2a_short_dca_above_sl` | `ohlc` | SHORT: DCA 101.0 trước SL 102.0, nến giật 104.0 | - | - | - | - | ❌ Fill #1 side mismatch: SELL vs BUY |
| 12 | `C2a_short_dca_above_sl` | `adaptive` | SHORT: DCA 101.0 trước SL 102.0, nến giật 104.0 | - | - | - | - | ❌ Fill #1 side mismatch: SELL vs BUY |
| 13 | `C2b_short_dca_below_sl` | `ohlc` | SHORT ca B: DCA 103.0 sau SL 102.0, nến giật 104.0 | - | - | - | - | ❌ Fill #1 side mismatch: SELL vs BUY |
| 14 | `C2b_short_dca_below_sl` | `adaptive` | SHORT ca B: DCA 103.0 sau SL 102.0, nến giật 104.0 | - | - | - | - | ❌ Fill #1 side mismatch: SELL vs BUY |
| 15 | `C3_multi_limit_cross` | `ohlc` | 3 tầng DCA (99, 98, 97) cùng bị vượt khi nến rơi 96.5 | 4 | 9999.8900 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 16 | `C3_multi_limit_cross` | `adaptive` | 3 tầng DCA (99, 98, 97) cùng bị vượt khi nến rơi 96.5 | 4 | 9999.8900 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 17 | `C4a_gap_open_stop` | `ohlc` | Gap mở cửa rơi xuyên SL 98.0 (open 95.0) -> khớp ở giá open | 2 | 9994.9025 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 18 | `C4a_gap_open_stop` | `adaptive` | Gap mở cửa rơi xuyên SL 98.0 (open 95.0) -> khớp ở giá open | 2 | 9994.9025 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 19 | `C4b_gap_open_limit` | `ohlc` | Gap mở cửa tăng qua TP 105.0 (open 108.0) -> khớp đúng giá limit 105.0 | 2 | 10004.9290 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 20 | `C4b_gap_open_limit` | `adaptive` | Gap mở cửa tăng qua TP 105.0 (open 108.0) -> khớp đúng giá limit 105.0 | 2 | 10004.9290 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 21 | `C5_stale_sl_intrabar` | `ohlc` | SL cũ 98.0 còn hiệu lực trong nến: low 97.8 kích hoạt SL cũ dù SL mới là 97.51 | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 22 | `C5_stale_sl_intrabar` | `adaptive` | SL cũ 98.0 còn hiệu lực trong nến: low 97.8 kích hoạt SL cũ dù SL mới là 97.51 | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 23 | `C6_trailing_trigger_same_bar` | `ohlc` | Đỉnh nến nâng peak kích hoạt trailing, đáy nến chạm mức trailing trigger | 2 | 10002.3388 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 24 | `C6_trailing_trigger_same_bar` | `adaptive` | Đỉnh nến nâng peak kích hoạt trailing, đáy nến chạm mức trailing trigger | 2 | 10002.3388 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 25 | `C7_reduce_only_flat` | `ohlc` | Lệnh stop reduce-only đóng hết 2.0 qty sau khi DCA khớp | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 26 | `C7_reduce_only_flat` | `adaptive` | Lệnh stop reduce-only đóng hết 2.0 qty sau khi DCA khớp | 3 | 9996.8214 | 0.0e+00 | 5.1e-10 | ✅ PASS |
| 27 | `C8_limit_through_zero` | `ohlc` | limit_through_pct=0: chạm đúng 99.0 là khớp maker | 2 | 9999.9300 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 28 | `C8_limit_through_zero` | `adaptive` | limit_through_pct=0: chạm đúng 99.0 là khớp maker | 2 | 9999.9300 | 0.0e+00 | 0.0e+00 | ✅ PASS |
| 29 | `C9_liquidation` | `ohlc` | Đòn bẩy 20x, MMR 0.5%: liq price = 95.5. Nến rơi 94.0 -> thanh lý | 2 | 9908.0450 | 0.0e+00 | 1.1e-16 | ✅ PASS |
| 30 | `C9_liquidation` | `adaptive` | Đòn bẩy 20x, MMR 0.5%: liq price = 95.5. Nến rơi 94.0 -> thanh lý | 2 | 9908.0450 | 0.0e+00 | 1.1e-16 | ✅ PASS |

**Tổng kết:** 26/30 kịch bản đạt chuẩn parity tuyệt đối (13/15 kịch bản pass cả 2 chế độ `ohlc` và `adaptive`).

## Bảng Ánh Xạ Ngữ Nghĩa Mã Nguồn (A3)

| Hành vi khớp lệnh | Mã nguồn Nora (`backend/core/backtest.py`) | Mã nguồn NautilusTrader Rust (`crates/execution/src/matching_engine/`) | Tài liệu chuẩn Nautilus |
|---|---|---|---|
| **1. Lệnh Market** | Dòng 4210 `_add_layer`, 4450-4490 (khớp ở Open của nến kế tiếp tín hiệu) | `matching_engine/mod.rs` `process_bar` (~dòng 1880-1920) | `docs/concepts/backtesting/bar-execution.md` |
| **2. Lệnh Limit chạm đúng mức** | Dòng 563-680 `_intrabar_path` (chạm đúng mức là khớp maker tại đúng giá limit) | `matching_core.rs` `iterate_bids`/`iterate_asks` (~dòng 340-420) | `docs/concepts/backtesting/fill-prices-and-matching.md` |
| **3. Lệnh Limit thiếu 1 tick** | Dòng 563-680 `_intrabar_path` (giá không chạm mức -> giữ nguyên resting order) | `matching_core.rs` (~dòng 360-390) | `docs/concepts/backtesting/fill-prices-and-matching.md` |
| **4. Gap mở cửa vượt Stop** | Dòng 585-610 `_intrabar_path` (gap qua stop: khớp ở đúng giá Open của nến) | `matching_engine/mod.rs` `process_bar` (~dòng 1900-1950) | `docs/concepts/backtesting/bar-execution.md` |
| **5. Gap mở cửa vượt Limit** | Dòng 585-610 `_intrabar_path` (gap qua limit: khớp ở đúng giá mức limit) | `matching_core.rs` (~dòng 350-380) | `docs/concepts/backtesting/fill-prices-and-matching.md` |
| **6. Ca B (DCA dưới SL, Long)** | Dòng 563-680 `_intrabar_path` (DCA khớp trước, SL tính theo avg cũ khớp sau đóng hết) | `matching_engine/mod.rs` (`iterate_bids` DCA Buy trước `iterate_asks` SL Sell) | `docs/concepts/backtesting/bar-execution.md` |
| **7. Nhiều tầng Limit cùng chặng** | Dòng 563-680 `_intrabar_path` (khớp tuần tự toàn bộ các tầng bị vượt qua) | `matching_core.rs` (~dòng 400-430) | `docs/concepts/backtesting/fill-prices-and-matching.md` |
| **8. Trailing Stop cùng nến** | Dòng 610-645 `_intrabar_path` (đỉnh nến nâng peak kích hoạt, đáy nến chạm trigger) | `matching_core.rs` (ratchet peak tick-by-tick trên O-H-L-C) | `docs/concepts/backtesting/bar-execution.md` |
| **9. Thanh lý Perp** | Dòng 660-680 `_intrabar_path`, `position_size.py` dòng 140-160 (`liq_price`) | `matching_engine/mod.rs` (stop trigger tại liquidation level) | `docs/concepts/backtesting/bar-execution.md` |
| **10. Thứ tự duyệt lệnh trong tick** | Dòng 563-680: Nhóm theo loại lệnh: (a) DCA limit -> (b) TP limit -> (c) Stop market | Duyệt theo sổ lệnh: `iterate_bids` (Buy) trước `iterate_asks` (Sell) | `crates/execution/src/matching_engine/mod.rs` |

## Phân Tích Sự Khác Biệt Ở Ca SHORT (C2a_short, C2b_short)

- **LONG side (C2a_long, C2b_long):** Khớp 100% tuyệt đối. Với LONG, DCA = BUY (Bid side), SL = SELL (Ask side). Cả Nautilus (Bid trước Ask) và Nora (DCA trước SL) đều cho cùng thứ tự: DCA khớp trước, SL khớp sau.
- **SHORT side (C2a_short, C2b_short):**
  - Nautilus duyệt `iterate_bids` trước `iterate_asks`: Lệnh SL (BUY) được duyệt trước lệnh DCA (SELL), dẫn đến SL đóng vị thế ban đầu trước, rồi DCA mở vị thế mới sau.
  - Nora gom theo hành vi nghiệp vụ: DCA limit duyệt trước SL stop, dẫn đến DCA khớp trước nâng vị thế, rồi SL khớp sau đóng toàn bộ vị thế.
  - Kết luận: Đây là khác biệt về quy ước thứ tự duyệt lệnh Bid/Ask vs Limit/Stop của hai hệ thống, đã được chứng minh trong S4 (EXT_REPORT.md). Theo đúng kế hoạch P14, mâu thuẫn này được giải quyết ở **Lớp 1 (Risk Controller)** bằng cách ngăn chặn đặt DCA vượt quá SL ngay từ tầng chiến lược, giữ nguyên matching engine thuần Nautilus.
