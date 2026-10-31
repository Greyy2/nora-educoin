# Đặc tính code của 27 EDU alpha candidates — 2026-10-28

## Phạm vi và trạng thái bằng chứng

Báo cáo này mô tả 27 code `research-v2` đã được thay trực tiếp vào đúng 27 user-alpha
record hiện có, giữ nguyên ID. Artifact
[`edu_fixture_alpha_candidates_v2_20261028.json`](./candidates/edu_fixture_alpha_candidates_v2_20261028.json)
được giữ làm migration manifest/audit metadata, không phải alpha record thứ hai trong
kho EDU. Các idea là đề xuất nghiên cứu mới, không phải phục hồi ý định ban đầu của tác giả.

**Cập nhật:** 27/27 code v2 production-compile bằng EDU DSL compiler, nhưng 27 code
chưa backtest. Novelty audit so với 30 alpha hiện hữu cho thấy nhiều signal-family
overlap; v2 bị đánh dấu **không đủ điều kiện backtest** và runner cũ đã được chặn.
Không candidate nào được xác nhận pass hoặc có lãi. Các mô tả dưới đây xác nhận code
đã viết gì, không khẳng định hiệu quả giao dịch.

## Tổng quan cấu trúc

- Có 27 candidate, chia theo template: U1 = 6, U2 = 7, U3 = 7, U4 = 7.
- U1, U3, U4 dùng BTC-USDT 1h; U2 dùng ETH-USDT 15m.
- Cả 27 đều long/flat: dùng `buy` và `close`, không có nhánh `sell`/short.
- Mỗi candidate có điều kiện vào và điều kiện đóng vị thế riêng. Generator phát
  `buy` trước `close`; theo DSL contract đã kiểm tra, action `close` gọi sau sẽ
  thắng nếu tín hiệu vào và thoát cùng đúng trên một bar.
- Source không khai báo sizing, stop-loss, take-profit, leverage hay giới hạn rủi ro.
  Các cấu hình mặc định từ API/engine cho v2 chưa được xác minh trong một run.
- AST body của 27 candidate khác nhau; điều đó không chứng minh 27 edge kinh tế độc
  lập. Một số candidate vẫn cùng họ tín hiệu và có thể tương quan cao.

## Danh sách theo template và code

“Vào” và “Thoát” là điều kiện trong candidate code, được diễn đạt ngắn gọn; các phép
cross là crossover/crossunder theo DSL, không phải chỉ so sánh mức tĩnh.

| # | ID parent | Template / class | Ý tưởng code | Điều kiện vào | Điều kiện thoát |
|---:|---|---|---|---|---|
| 1 | `138df68946ad` | U1 / `U1LinearSlopeTurn` | Động lượng hồi phục qua độ dốc hồi quy dương. | Linear-regression slope(14) cắt lên 0 và close > EMA(50). | Slope(14) cắt xuống 0. |
| 2 | `1a1a4389a821` | U1 / `U1EmaPullback` | Mua nhịp hồi trong xu hướng EMA trung hạn dương. | Close cắt lên EMA(20), đồng thời EMA(20) > EMA(50). | Close cắt xuống EMA(50). |
| 3 | `2e41b2cfa24d` | U1 / `U1BollingerSqueezeBreak` | Co hẹp biến động rồi phá dải trên Bollinger. | NATR(14) của bar trước < SMA(20) của NATR(14), đồng thời close cắt lên dải trên Bollinger. | Close cắt xuống đường giữa Bollinger. |
| 4 | `bd234070bd7b` | U1 / `U1RsiRecoveryTrend` | RSI hồi khỏi vùng quá bán trong chế độ giá dài hạn dương. | RSI(14) cắt lên 35 trong vòng 8 bar kể từ khi RSI < 30, và close > EMA(100). | RSI(14) cắt lên 70 hoặc close < EMA(50). |
| 5 | `be1174b24a44` | U1 / `U1ObvAccumulation` | Xác nhận xu hướng giá bằng dòng khối lượng OBV. | Close > EMA(50) và OBV cắt lên SMA(20) của OBV. | Close < EMA(20) hoặc OBV cắt xuống SMA(20) của OBV. |
| 6 | `cb0b6e0f12e7` | U1 / `U1DonchianBullBreak` | Phá đỉnh vùng giá trước với nến đóng tăng. | Close cắt lên Donchian upper(20) và close > open. | Close cắt xuống EMA(10). |
| 7 | `214ea8fdf3e6` | U2 / `U2ObvBreakout` | Phá vùng giá được hỗ trợ bởi OBV đang cao hơn nền. | Close cắt lên Donchian upper(20) và OBV > SMA(20) của OBV. | Close < EMA(20) hoặc OBV cắt xuống SMA(20) của OBV. |
| 8 | `234e6df02e37` | U2 / `U2DonchianExpansion` | Breakout chỉ khi biến động chưa quá cực đoan. | Close cắt lên Donchian upper(20) và NATR(14) < 2 × SMA(50) của NATR(14). | Close cắt xuống EMA(20). |
| 9 | `616e1b8cbc88` | U2 / `U2NatrExpansionBreak` | Breakout giá đồng thời với biến động chuẩn hóa tăng. | NATR(14) cắt lên SMA(20) của NATR(14), đồng thời close cắt lên Donchian upper(20). | Close cắt xuống EMA(20). |
| 10 | `856ddc574ce7` | U2 / `U2StochasticRecovery` | Stochastic hồi từ vùng thấp nhưng có lọc xu hướng. | Slow %K cắt lên %D khi %K < 20 và close > EMA(50). | Slow %K cắt xuống %D khi %K > 80, hoặc close < EMA(20). |
| 11 | `862e0c9eebbe` | U2 / `U2CciSnapbackTrend` | CCI hồi khỏi mức yếu trong chế độ giá trung hạn dương. | CCI(14) cắt lên -100 và close > EMA(50). | CCI(14) cắt lên +100 hoặc close < EMA(20). |
| 12 | `e9a9a5b44d03` | U2 / `U2MacdZeroRegime` | Chuyển chế độ động lượng MACD có lọc xu hướng dài hơn. | MACD line cắt lên 0 và close > EMA(100). | MACD line cắt xuống 0 hoặc close < EMA(50). |
| 13 | `ee0cf7f58f94` | U2 / `U2BollingerReclaim` | Mean-reversion ngắn sau khi giá lấy lại dải dưới. | Close cắt lên dải dưới Bollinger khi RSI(14) < 45. | Close cắt lên đường giữa Bollinger. |
| 14 | `1e4c0b9f84f7` | U3 / `U3DonchianBreakdownGate` | Đóng vị thế khi phá đáy cấu trúc; vào lại khi lấy lại EMA. | Close cắt lên EMA(20). | Close cắt xuống Donchian lower(20). |
| 15 | `571474a18f55` | U3 / `U3DirectionalTrendGate` | Chuyển hướng DI xác nhận xu hướng tăng; thoát khi xu hướng giảm đủ mạnh. | +DI(14) cắt lên -DI(14) và close > EMA(50). | ADX(14) > 25 và -DI(14) > +DI(14). |
| 16 | `7f770ebe5ab5` | U3 / `U3RocRecoveryGate` | ROC ngắn hạn quay dương trong xu hướng giá dương. | ROC(10) cắt lên 0 và close > EMA(20). | ROC(10) cắt xuống 0. |
| 17 | `930294d28c45` | U3 / `U3RsiStrengthGate` | RSI hồi qua ngưỡng trung tính trong xu hướng tăng. | RSI(14) cắt lên 50 và close > EMA(50). | RSI(14) cắt xuống 45. |
| 18 | `9eec3d61131d` | U3 / `U3MacdRiskGate` | Dùng MACD zero-line làm cổng giữ long/flat. | MACD line cắt lên 0. | MACD line cắt xuống 0. |
| 19 | `af2bf88426c4` | U3 / `U3BollingerReclaim` | Lấy lại đường giữa sau một lần đóng dưới dải thấp. | Close cắt lên Bollinger middle trong vòng 8 bar kể từ lúc close < lower band, đồng thời ROC(1) > 0. | Close cắt xuống Bollinger lower. |
| 20 | `fd16df3d0a3f` | U3 / `U3EmaRegimeGate` | Cổng phân bổ long theo EMA trung hạn. | Close cắt lên EMA(50). | Close cắt xuống EMA(50). |
| 21 | `026f43441cb2` | U4 / `U4DemaCross` | Kiểm tra DEMA nhanh hơn có bù được whipsaw hay không. | DEMA(12) cắt lên DEMA(36). | DEMA(12) cắt xuống DEMA(36). |
| 22 | `0bf936687964` | U4 / `U4DonchianTrendBreak` | Phá đỉnh Donchian và giữ đến khi mất hướng dẫn EMA nhanh. | Close cắt lên Donchian upper(20). | Close cắt xuống EMA(10). |
| 23 | `64b657c8de8e` | U4 / `U4TrendFilteredReversion` | Mean-reversion từ dải dưới nhưng chỉ trong chế độ giá dài hạn dương. | Close cắt lên Bollinger lower và close > EMA(100). | Close cắt lên Bollinger middle. |
| 24 | `74f607263c5c` | U4 / `U4ObvBreakoutConfirmation` | Breakout phải đồng thời có xác nhận OBV mới. | Close cắt lên Donchian upper(20), đồng thời OBV cắt lên SMA(20) của OBV. | Close cắt xuống EMA(20) hoặc OBV cắt xuống SMA(20) của OBV. |
| 25 | `7c1bf0a9686a` | U4 / `U4MacdHistogramAcceleration` | MACD cross có xác nhận histogram tăng liên tiếp. | MACD line cắt lên signal line, histogram tăng trong 2 bar và close > EMA(50). | MACD line cắt xuống signal line. |
| 26 | `a4d6826fbbc6` | U4 / `U4RsiMomentumRegime` | RSI qua trung tính làm tín hiệu động lượng trên trend filter dài hơn. | RSI(14) cắt lên 50 và close > EMA(100). | RSI(14) cắt xuống 45. |
| 27 | `d0518c0cca14` | U4 / `U4SqueezeDonchianBreak` | NATR co lại rồi giá phá đỉnh Donchian. | NATR(14) của bar trước < SMA(20) của NATR(14), đồng thời close cắt lên Donchian upper(20). | Close cắt xuống EMA(20). |

## Nhận xét code, không phải kết luận hiệu năng

1. **Các họ tín hiệu bị lặp có chủ đích.** Nhiều candidate dùng breakout Donchian,
   RSI/CCI/Stochastic recovery, MACD regime, Bollinger reclaim, hoặc EMA regime; sự
   khác nhau thường nằm ở filter/exit. Ví dụ hai squeeze breakout (#3 và #27) dùng
   cùng điều kiện NATR co hẹp-bar trước nhưng khác điều kiện breakout/EMA thoát.
   Vì vậy 27 code khác nhau không đồng nghĩa 27 chiến lược có edge độc lập.
2. **Không có stop/TP trong source candidate.** Điều kiện thoát là tín hiệu indicator
   nêu trong bảng. Chưa xác minh cấu hình bảo vệ mặc định áp lên v2; không nên hiểu
   đây là quản trị rủi ro hoàn chỉnh.
3. **Một số điều kiện đồng thời khá chặt.** #9 đòi hỏi NATR crossover và giá breakout
   cùng bar. #3/#27 chỉ kiểm tra trạng thái NATR của bar ngay trước, không yêu cầu
   squeeze kéo dài nhiều bar.
4. **Có thể cần xem lại tên/hàm ý so với logic thực tế.** #14 vào lại chỉ bằng close
   cắt lên EMA(20), không có filter xu hướng bổ sung; #15 thoát theo trạng thái
   `ADX > 25` và `-DI > +DI`, không đợi crossover mới. Đây là mô tả chính xác code,
   chưa phải khẳng định lỗi.
5. **Phạm vi dữ liệu cố định theo template.** 20 candidate chạy BTC-USDT 1h và 7
   candidate chạy ETH-USDT 15m; chưa có bằng chứng ngoại suy sang symbol/timeframe
   khác.

## Kết luận

Đã lập bản đồ code đầy đủ cho 27 candidate: họ chiến lược, timeframe, điều kiện vào
và thoát. Đây là bước phân tích source, không phải bước tối ưu theo kết quả.
Production compile/backtest vẫn chưa chạy; vì vậy **số alpha v2 đã pass/lãi là 0/27
được kiểm chứng**, không phải kết luận rằng 27 alpha đều lỗ.
