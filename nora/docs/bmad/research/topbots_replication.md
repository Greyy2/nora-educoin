# Tái tạo lối đánh của bot copy-trading top trên nến 1m thật — "toàn thắng" che giấu điều gì?

> Thí nghiệm nghiên cứu, không phải khuyến nghị giao dịch. Mọi con số trong tài liệu này lấy từ lần chạy `20261002_023453.json` của
> `test/scripts/research_topbots.py` (dữ liệu Binance USDT-M perp 1m thật, kết thúc 1790788080000 ms epoch ≈ 2026-09-30 17:08 UTC,
> cổng chất lượng dữ liệu: BTC@perp APPROVED, DOGE@perp APPROVED, ETH@perp APPROVED, SOL@perp APPROVED).
> Chạy lại: `ops/run_limited.sh -- test/scripts/research_topbots.py` (≈ 463 giây, đỉnh RAM ≈ 5,1 GB cho 5 worker).

## 1. Câu hỏi và phương pháp

**Câu hỏi.** Các bot copy-trading hàng đầu trên OKX công bố tỉ lệ thắng 48–99%, PF 2,2–14,6 (sáu bot được chọn). Nếu bắt chước đúng *cấu trúc* lệnh của họ
(DCA/martingale, đòn bẩy cao, chốt lời nhỏ, **không cắt lỗ**) trên giá thật, thì (a) trong chính khoảng thời gian họ được đo, (b) trên toàn bộ 3 năm dữ liệu,
kết quả khác nhau thế nào, và các chỉ số "đẹp" đó che giấu cái gì (lỗ treo, thanh lý, cháy tài khoản)?

**Nguồn tham số.** `okx-report.html`, khối `const BOTS = [...]` (parse bằng JSON trong `parse_bots`, không chép tay).
Với mỗi bot Trade: `p` (lev_med, hold_med, win, long_pct, top_syms, pf, momentum, days, per_day) và `v` (spacing = bước DCA % giá,
stack = số tầng tối đa, size = hệ số khối lượng tầng, tp = chốt lời theo **% ký quỹ** → % giá = tp / đòn bẩy).

**Ánh xạ sang tham số vị thế Nora** (`market="perp"`, ký quỹ isolated, thanh lý bật, `stop_loss_rate=0`, `timeout=0`, phí/trượt giá Binance USDT-M VIP0:
taker 0,05%, maker 0,02%, trượt 0,02%, funding thật từ `funding.pkl`):

| Bot (nguồn BOTS) | Biến thể trong báo cáo | Đòn bẩy | Bước DCA % | Tầng DCA (stack−1 → dùng) | Hệ số tầng | TP %ký quỹ → %giá | Chiều (long_pct) | order_size_pct (lớn nhất theo `dca_budget_check`) | Tài sản chạy (top_syms có dữ liệu) | Thiếu dữ liệu | Cửa sổ A |
|---|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 (OKX Copy Trading) | DCA dày | 30x | 0.32 | 57 → 57 | 1.0 | 48.1 → 1.603 | LONG (92%) | 1.7135 | ETH, DOGE, BTC | — | 88 ngày |
| 好望角9999 (OKX Copy Trading) | DCA vừa | 10x | 0.69 | 60 → 60 | 1.0 | 18.2 → 1.82 | SHORT (16%) | 1.6359 | ETH | ONE, ZEC | 28 ngày |
| xiaojian888999 (OKX Copy Trading) | DCA vừa | 10x | 0.73 | 9 → 9 | 1.01 | 10.4 → 1.04 | LONG/SHORT (48%) | 4.7682 mỗi chiều (nửa ngân sách) | BTC, ETH | SNDK | 91 ngày |
| Shallow-Pair-Frog (OKX Copy Trading) | DCA martingale | 50x | 0.67 | 11 → 11 | 1.98 | 274.0 → 5.48 | LONG (69%) | 0.0267 | BTC, ETH | ZEC | 90 ngày |
| BestMax (OKX Copy Trading) | DCA dày | 20x | 0.4 | 24 → 24 | 1.0 | 20.7 → 1.035 | LONG (100%) | 3.9831 | SOL | PUMP, HYPE | 90 ngày |
| 星火研究院-大象 (Binance Copy Trading) | Vào–ra dứt khoát | 8x | — | 0 → 0 | 1.0 | 1.4 → 0.175 | LONG/SHORT (53%) | 49.8007 mỗi chiều (nửa ngân sách) | ETH, BTC | HYPE | 137 ngày |

Ghi chú ánh xạ:

- **Số tầng.** Không bot nào phải giảm số tầng: ngân sách engine (`dca_budget_check`) đủ cho `stack−1` tầng ở mọi bot, nhưng với *martingale ×1,98* (Shallow-Pair-Frog)
  ký quỹ lệnh đầu chỉ còn 0,0267% vốn (tổng ký quỹ + phí của 11 tầng + lệnh đầu ≈ 3.741 lần lệnh đầu). Quy tắc cài sẵn: nếu ký quỹ lớn nhất < 0,01% vốn thì giảm số tầng đến khi đạt (có test).
- **Số tầng thực dùng thấp hơn nhiều so với cấu hình** (xem cột "tầng max" ở các bảng sau): ở 30x isolated giá thanh lý chỉ cách giá TB 2,83% nên maomao12345 không bao giờ
  vượt 18 tầng dù cấu hình 57 tầng; mọi tầng sâu hơn là "không thể" trong chế độ isolated.
- **order_size_pct = lớn nhất thoả `dca_budget_check`** (theo yêu cầu): khi nhồi hết tầng, bot dùng **toàn bộ** vốn làm ký quỹ. Đây là cấu hình nguy hiểm nhất
  có thể; bot thật có thể dùng ít vốn hơn mỗi vị thế. Mục 5 chạy độ nhạy với ký quỹ ×0,25.
- Bot đánh hai chiều (xiaojian888999 long 48%, 星火研究院-大象 long 53%) chạy hai flow LONG + SHORT, mỗi flow nửa ngân sách.
- Bot thứ 6 là bot Binance "lướt ngắn / vào–ra dứt khoát" **星火研究院-大象** (tp 1,4% ký quỹ ở 8x = chốt 0,175% giá, thắng 99%, giữ trung vị 0,77h, **không có tầng DCA**).
  Ký quỹ 100% vốn / lệnh chia đôi cho hai chiều. Các bot khác trong danh sách (01pp, Milies L, ...) không chạy; BestMax chỉ chạy được trên SOL vì PUMP/HYPE không có trong dữ liệu.
- Mỗi tài sản chạy **sổ vốn riêng** (10.000 USDT), kết quả bot = trung bình đều các tài sản (không tái cân bằng); MDD tính trên đường vốn trung bình
  (đáy `equity_worst` từng giờ của mọi tài sản cộng lại — bi quan).

## 2. GIẢ ĐỊNH VỀ ĐIỂM VÀO — phần quan trọng nhất cần đọc

Báo cáo OKX **không tiết lộ trigger vào lệnh** của bot. Điểm vào ở đây là **giả định của chúng tôi**, không phải tái tạo tín hiệu thật:

1. **`reentry` — "vào lại ngay khi trống"**: khi không có vị thế, sau cooldown 5 phút thì vào ngay (điều kiện luôn đúng). Chiều theo `long_pct`
   (≥65% chỉ LONG, ≤35% chỉ SHORT, ở giữa chạy cả hai chiều cùng lúc). Khớp với thống kê `momentum` (% lệnh cùng chiều biến động 24h): bot có momentum 30–60% (maomao 49,
   xiaojian 39, Shallow 36, BestMax 44, 大象 41) coi là trung tính, không lọc; 好望角9999 (momentum 23%, ngược đà) chỉ SHORT khi ROC 24h > 0.
   **Hệ quả:** với bot hai chiều, hai chân LONG và SHORT mở đồng thời (hedge); kết quả `reentry` của xiaojian888999 và 大象 vì vậy chịu phí hai chân.
2. **`reversion` — tín hiệu bắt hồi có sẵn của Nora** (`strategy_library`: `dip_5m_rsi_bb_ranging` cho LONG, `rip_5m_rsi_bb_ranging` cho SHORT:
   5m RSI14 quá bán/quá mua + giá ngoài Bollinger 20/2 + regime đi ngang). Đây là tín hiệu *có lý do kinh tế* đối lập với "vào bừa", và hai chiều của nó loại trừ nhau.

Cả hai đều **không đại diện cho edge thật** của bot (nếu có). Vì vậy tài liệu này đo *cấu trúc rủi ro của kiểu quản lý vị thế*, **không** kết luận "bot X lỗ" hay "bot X gian lận".

Các cửa sổ: **A** = `p.days` ngày cuối đến 2026-09-30 (cửa sổ đo của chính bot: 88 / 28 / 91 / 90 / 90 / 137 ngày), **B** = toàn bộ dữ liệu (≈ 1.075 ngày sau 20 ngày khởi động chỉ báo).

Cách đo (xem `compute_metrics`): lệnh = một vị thế (cả rổ DCA); thắng = `real_pnl` sau phí và funding > 0; **không tính vị thế còn mở lúc cuối dữ liệu** vào win rate (cột "mở lúc cuối" cho biết số lượng — đó chính là lỗ treo
bị bỏ ngoài thống kê, vị thế bị đóng cưỡng bức lúc cuối cửa sổ nhưng vốn cuối đã gồm chúng); "lãi thực hiện" = vốn cuối / vốn đầu − 1; **MDD MTM** = từ đỉnh vốn mark-to-market đến đáy `equity_worst`
(gồm lỗ treo tại giá xấu nhất của nến), lấy mẫu theo giờ; "cháy" = `equity_worst` ≤ 10% vốn đầu (−90%); "MAE max" = lỗ treo lớn nhất của một vị thế, % vốn (không gồm nến bị thanh lý);
TB thắng / TB thua = trung bình `profit_pct` (% vốn tiểu khoản lúc vào lệnh).

## 3. Kết quả — chính sách của bot, không cắt lỗ


### 3.1a Điểm vào "tín hiệu bắt hồi" — cửa sổ A — chính khoảng thời gian bot được đo

| Bot | công bố win% / PF | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | MAE max % | thanh lý | thanh lý đầu (ngày) | cháy (ngày) | tầng max | % thời gian mở | mở lúc cuối |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | 76% / 2.24 | 124 | 91.9 | 2.50 | 4.85 / -27.06 | 203.0 | 24.2 | 26.3 | 10 | 3.5 | — | 18 | 65.7 | 3 |
| 好望角9999 | 90% / 11.36 | 7 | 100.0 | — | 1.55 / — | -3.2 | 26.4 | 29.2 | 0 | — | — | 22 | 80.8 | 1 |
| xiaojian888999 | 71% / 2.32 | 209 | 97.6 | 0.90 | 1.33 / -47.40 | -15.6 | 49.9 | 47.5 | 5 | 11.3 | — | 10 | 93.6 | 0 |
| Shallow-Pair-Frog | 48% / 4.52 | 19 | 100.0 | — | 20.04 / — | 356.0 | 27.0 | 20.3 | 0 | — | — | 11 | 86.3 | 2 |
| BestMax | 74% / 5.41 | 57 | 98.2 | 1.07 | 3.53 / -84.22 | 6.6 | 88.5 | 82.3 | 1 | 11.2 | — | 23 | 45.8 | 0 |
| 星火研究院-大象 | 99% / 14.58 | 638 | 98.3 | 0.49 | 0.42 / -39.16 | -78.6 | 83.3 | 48.0 | 9 | 17.2 | — | 1 | 70.3 | 1 |

### 3.1b Điểm vào "tín hiệu bắt hồi" — cửa sổ B — toàn bộ ≈ 3 năm

| Bot | công bố win% / PF | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | MAE max % | thanh lý | thanh lý đầu (ngày) | cháy (ngày) | tầng max | % thời gian mở | mở lúc cuối |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | 76% / 2.24 | 2569 | 85.5 | 0.91 | 4.28 / -26.94 | -99.9 | 100.0 | 26.4 | 372 | 24.8 | 256.6 (3/3 tk) | 18 | 49.5 | 3 |
| 好望角9999 | 90% / 11.36 | 498 | 97.2 | 0.93 | 1.38 / -40.10 | -51.0 | 84.8 | 40.5 | 14 | 19.1 | — | 26 | 68.2 | 1 |
| xiaojian888999 | 71% / 2.32 | 2891 | 96.8 | 0.83 | 1.39 / -47.53 | -99.7 | 99.9 | 47.5 | 93 | 3.0 | 374.8 (2/2 tk) | 10 | 87.0 | 0 |
| Shallow-Pair-Frog | 48% / 4.52 | 517 | 72.3 | 0.80 | 21.70 / -67.11 | -100.0 | 100.0 | 75.1 | 143 | 51.1 | 136.9 (2/2 tk) | 12 | 81.0 | 2 |
| BestMax | 74% / 5.41 | 1260 | 96.0 | 0.93 | 3.44 / -83.69 | -100.0 | 100.0 | 82.8 | 51 | 51.1 | 90.7 (1/1 tk) | 23 | 31.7 | 0 |
| 星火研究院-大象 | 99% / 14.58 | 5410 | 97.8 | 0.51 | 0.42 / -37.81 | -100.0 | 100.0 | 48.0 | 92 | 3.1 | 146.2 (2/2 tk) | 1 | 65.8 | 1 |

### 3.2a Điểm vào "vào lại ngay khi trống" — cửa sổ A — chính khoảng thời gian bot được đo

| Bot | công bố win% / PF | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | MAE max % | thanh lý | thanh lý đầu (ngày) | cháy (ngày) | tầng max | % thời gian mở | mở lúc cuối |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | 76% / 2.24 | 318 | 89.9 | 1.27 | 4.19 / -27.01 | 99.4 | 46.8 | 26.4 | 32 | 3.2 | — | 18 | 99.5 | 3 |
| 好望角9999 | 90% / 11.36 | 5 | 100.0 | — | 1.77 / — | -5.8 | 27.7 | 30.6 | 0 | — | — | 23 | 85.9 | 1 |
| xiaojian888999 | 71% / 2.32 | 294 | 97.3 | 0.90 | 1.32 / -46.79 | -19.2 | 58.7 | 47.4 | 8 | 5.2 | — | 10 | 100.0 | 4 |
| Shallow-Pair-Frog | 48% / 4.52 | 32 | 90.6 | 1.00 | 10.23 / -52.68 | 0.2 | 77.7 | 70.2 | 3 | 61.7 | — | 12 | 99.9 | 2 |
| BestMax | 74% / 5.41 | 171 | 97.7 | 0.53 | 3.36 / -84.02 | -84.9 | 98.9 | 82.4 | 4 | 10.4 | 30.1 (1/1 tk) | 23 | 99.2 | 1 |
| 星火研究院-大象 | 99% / 14.58 | 1168 | 97.8 | 0.55 | 0.42 / -37.08 | -95.0 | 95.0 | 48.0 | 20 | 16.8 | 96.4 (2/2 tk) | 1 | 100.0 | 4 |

### 3.2b Điểm vào "vào lại ngay khi trống" — cửa sổ B — toàn bộ ≈ 3 năm

| Bot | công bố win% / PF | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | MAE max % | thanh lý | thanh lý đầu (ngày) | cháy (ngày) | tầng max | % thời gian mở | mở lúc cuối |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | 76% / 2.24 | 7791 | 85.9 | 0.96 | 4.28 / -26.95 | -99.8 | 100.0 | 26.4 | 1097 | 3.7 | 289.1 (3/3 tk) | 18 | 99.0 | 3 |
| 好望角9999 | 90% / 11.36 | 555 | 96.2 | 0.71 | 1.34 / -40.19 | -97.9 | 98.4 | 40.4 | 21 | 16.6 | 636.1 (1/1 tk) | 26 | 75.7 | 1 |
| xiaojian888999 | 71% / 2.32 | 6693 | 97.0 | 0.93 | 1.33 / -47.38 | -99.7 | 99.9 | 47.5 | 202 | 3.0 | 374.8 (2/2 tk) | 10 | 100.0 | 4 |
| Shallow-Pair-Frog | 48% / 4.52 | 736 | 73.4 | 0.85 | 24.33 / -69.84 | -100.0 | 100.0 | 75.1 | 196 | 24.8 | 136.9 (2/2 tk) | 12 | 99.9 | 2 |
| BestMax | 74% / 5.41 | 4995 | 96.3 | 0.98 | 3.56 / -83.87 | -100.0 | 100.0 | 82.8 | 185 | 11.9 | 23.2 (1/1 tk) | 23 | 98.1 | 1 |
| 星火研究院-大象 | 99% / 14.58 | 13485 | 97.8 | 0.46 | 0.37 / -32.90 | -100.0 | 100.0 | 48.0 | 233 | 3.0 | 74.6 (2/2 tk) | 1 | 88.9 | 2 |

(`cháy (ngày)` = số ngày từ đầu cửa sổ đến lần đầu đường vốn *trung bình các tài sản* có `equity_worst` ≤ 10% vốn đầu; trong ngoặc là số tài sản (sổ vốn riêng) đã cháy;
"—" = không cháy. `lãi thực hiện` và `MDD` là trung bình đều các tài sản của bot.)

### 3.3 Chỉ số bot công bố vs bản tái tạo (cùng bảng, hai cột đầu): thắng nhiều, nhưng không phải vì có lãi

Tỉ lệ thắng tái tạo ở cửa sổ A là 92–100% (reversion) và 90–100% (reentry): **cao hơn con số công bố ở 5/6 bot** (công bố 48–90%) và xấp xỉ ở 星火研究院-大象 (97,8–98,3% vs 99%),
dù PF thực hiện chỉ >1 ở vài ô và lãi thực hiện âm ở nhiều ô. Ở cửa sổ B tỉ lệ thắng vẫn 72–98% trong khi tài khoản đã cháy. Win rate không phân biệt được "có lãi" với "sắp cháy".
(PF/win công bố của bot là của lệnh đã đóng trong cửa sổ riêng, kèm edge điểm vào mà ở đây không có — so sánh chỉ mang tính định tính.)

## 4. Đối chứng: cùng bot + SL cứng

SL cứng đặt theo đặc tả (2 × biên độ DCA, tính từ giá TB) hoá ra **nằm sau giá thanh lý** ở mọi bot có DCA (ví dụ maomao12345: biên độ 18,24% → SL 36,48% nhưng thanh lý ở 2,83%):
engine kiểm giá thanh lý trước nên kết quả **trùng khít** với bản không SL (đã chạy thật, cấu hình `sl_2span`, trùng từng con số ở cả 20 ô bot × biến thể × cửa sổ có DCA).
Vì vậy đối chứng có ý nghĩa là **SL ngay trước giá thanh lý**: `SL = min(2×biên độ DCA, 0,5 × khoảng cách tới giá thanh lý)` từ giá TB (maomao 1,42%, 好望角 4,75%, xiaojian 4,75%, Shallow 0,75%, BestMax 2,25%, 大象 6,0%).
SL là lệnh market; chạy ở **cả hai kiểu khớp**: `extreme` (khớp giá xấu nhất của nến chạm SL — bi quan) và `level` (khớp đúng mức SL + trượt — lạc quan).
Bản **không SL không phụ thuộc kiểu khớp** (stop_fill chỉ ảnh hưởng SL/trailing; thanh lý luôn khớp ở giá thanh lý) — có test xác nhận kết quả trùng nhau.


### 4.1 Cửa sổ A

| Bot | điểm vào | cấu hình | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) |
|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | reversion | không SL | 124 | 91.9 | 2.50 | 4.85 / -27.06 | 203.0 | 24.2 | 10 | — |
| maomao12345 | reversion | SL, khớp extreme | 198 | 70.7 | 0.96 | 2.90 / -7.25 | -5.2 | 24.6 | 0 | — |
| maomao12345 | reversion | SL, khớp level | 198 | 70.7 | 1.11 | 2.90 / -6.23 | 14.8 | 13.2 | 0 | — |
| maomao12345 | reentry | không SL | 318 | 89.9 | 1.27 | 4.19 / -27.01 | 99.4 | 46.8 | 32 | — |
| maomao12345 | reentry | SL, khớp extreme | 529 | 70.7 | 0.92 | 2.66 / -7.06 | -23.7 | 44.5 | 0 | — |
| maomao12345 | reentry | SL, khớp level | 529 | 70.7 | 1.01 | 2.66 / -6.23 | 2.4 | 36.9 | 0 | — |
| 好望角9999 | reversion | không SL | 7 | 100.0 | — | 1.55 / — | -3.2 | 26.4 | 0 | — |
| 好望角9999 | reversion | SL, khớp extreme | 14 | 92.9 | 1.53 | 1.31 / -10.37 | 6.1 | 14.1 | 0 | — |
| 好望角9999 | reversion | SL, khớp level | 14 | 92.9 | 1.54 | 1.31 / -10.27 | 6.2 | 14.0 | 0 | — |
| 好望角9999 | reentry | không SL | 5 | 100.0 | — | 1.77 / — | -5.8 | 27.7 | 0 | — |
| 好望角9999 | reentry | SL, khớp extreme | 10 | 90.0 | 1.40 | 1.75 / -10.49 | 4.4 | 16.2 | 0 | — |
| 好望角9999 | reentry | SL, khớp level | 10 | 90.0 | 1.43 | 1.75 / -10.27 | 4.7 | 16.0 | 0 | — |
| xiaojian888999 | reversion | không SL | 209 | 97.6 | 0.90 | 1.33 / -47.40 | -15.6 | 49.9 | 5 | — |
| xiaojian888999 | reversion | SL, khớp extreme | 218 | 97.2 | 1.37 | 1.32 / -29.13 | 44.1 | 33.6 | 0 | — |
| xiaojian888999 | reversion | SL, khớp level | 218 | 97.2 | 1.74 | 1.32 / -24.05 | 76.9 | 23.2 | 0 | — |
| xiaojian888999 | reentry | không SL | 294 | 97.3 | 0.90 | 1.32 / -46.79 | -19.2 | 58.7 | 8 | — |
| xiaojian888999 | reentry | SL, khớp extreme | 371 | 95.4 | 0.96 | 1.27 / -26.24 | -11.3 | 51.3 | 0 | — |
| xiaojian888999 | reentry | SL, khớp level | 371 | 95.4 | 1.04 | 1.27 / -24.05 | 9.2 | 42.5 | 0 | — |
| Shallow-Pair-Frog | reversion | không SL | 19 | 100.0 | — | 20.04 / — | 356.0 | 27.0 | 0 | — |
| Shallow-Pair-Frog | reversion | SL, khớp extreme | 81 | 21.0 | 1.18 | 0.18 / -0.04 | 0.3 | 0.3 | 0 | — |
| Shallow-Pair-Frog | reversion | SL, khớp level | 81 | 21.0 | 1.40 | 0.18 / -0.03 | 0.5 | 0.2 | 0 | — |
| Shallow-Pair-Frog | reentry | không SL | 32 | 90.6 | 1.00 | 10.23 / -52.68 | 0.2 | 77.7 | 3 | — |
| Shallow-Pair-Frog | reentry | SL, khớp extreme | 113 | 28.3 | 1.27 | 0.13 / -0.04 | 0.5 | 0.4 | 0 | — |
| Shallow-Pair-Frog | reentry | SL, khớp level | 113 | 28.3 | 1.49 | 0.13 / -0.03 | 0.7 | 0.3 | 0 | — |
| BestMax | reversion | không SL | 57 | 98.2 | 1.07 | 3.53 / -84.22 | 6.6 | 88.5 | 1 | — |
| BestMax | reversion | SL, khớp extreme | 73 | 89.0 | 0.81 | 2.45 / -21.98 | -34.5 | 56.1 | 0 | — |
| BestMax | reversion | SL, khớp level | 73 | 89.0 | 0.87 | 2.45 / -20.49 | -23.7 | 51.7 | 0 | — |
| BestMax | reentry | không SL | 171 | 97.7 | 0.53 | 3.36 / -84.02 | -84.9 | 98.9 | 4 | 30.1 |
| BestMax | reentry | SL, khớp extreme | 255 | 91.0 | 1.07 | 2.69 / -21.90 | 55.6 | 75.9 | 0 | — |
| BestMax | reentry | SL, khớp level | 255 | 91.0 | 1.15 | 2.69 / -20.53 | 132.8 | 72.8 | 0 | — |
| 星火研究院-大象 | reversion | không SL | 638 | 98.3 | 0.49 | 0.42 / -39.16 | -78.6 | 83.3 | 9 | — |
| 星火研究院-大象 | reversion | SL, khớp extreme | 754 | 97.6 | 0.62 | 0.42 / -25.35 | -66.0 | 73.3 | 0 | — |
| 星火研究院-大象 | reversion | SL, khớp level | 754 | 97.6 | 0.69 | 0.42 / -23.02 | -54.7 | 64.5 | 0 | — |
| 星火研究院-大象 | reentry | không SL | 1168 | 97.8 | 0.55 | 0.42 / -37.08 | -95.0 | 95.0 | 20 | 96.4 |
| 星火研究院-大象 | reentry | SL, khớp extreme | 2096 | 96.5 | 0.49 | 0.42 / -24.03 | -98.5 | 98.5 | 0 | 65.8 |
| 星火研究院-大象 | reentry | SL, khớp level | 2096 | 96.5 | 0.50 | 0.42 / -23.38 | -98.2 | 98.2 | 0 | 68.9 |

### 4.2 Cửa sổ B (≈ 3 năm)

| Bot | điểm vào | cấu hình | lệnh | win% | PF | TB thắng / TB thua | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) |
|---|---|---|---|---|---|---|---|---|---|---|
| maomao12345 | reversion | không SL | 2569 | 85.5 | 0.91 | 4.28 / -26.94 | -99.9 | 100.0 | 372 | 256.6 |
| maomao12345 | reversion | SL, khớp extreme | 3406 | 66.3 | 0.72 | 2.78 / -7.38 | -99.6 | 99.7 | 0 | 261.0 |
| maomao12345 | reversion | SL, khớp level | 3406 | 66.3 | 0.86 | 2.78 / -6.22 | -96.0 | 97.1 | 0 | 533.8 |
| maomao12345 | reentry | không SL | 7791 | 85.9 | 0.96 | 4.28 / -26.95 | -99.8 | 100.0 | 1097 | 289.1 |
| maomao12345 | reentry | SL, khớp extreme | 11403 | 67.2 | 0.85 | 2.76 / -7.27 | -100.0 | 100.0 | 0 | 174.8 |
| maomao12345 | reentry | SL, khớp level | 12847 | 67.1 | 0.95 | 2.76 / -6.22 | -99.4 | 99.8 | 0 | 471.1 |
| 好望角9999 | reversion | không SL | 498 | 97.2 | 0.93 | 1.38 / -40.10 | -51.0 | 84.8 | 14 | — |
| 好望角9999 | reversion | SL, khớp extreme | 594 | 90.4 | 0.89 | 1.10 / -10.97 | -53.2 | 73.1 | 0 | — |
| 好望角9999 | reversion | SL, khớp level | 594 | 90.4 | 0.96 | 1.10 / -10.22 | -23.8 | 66.5 | 0 | — |
| 好望角9999 | reentry | không SL | 555 | 96.2 | 0.71 | 1.34 / -40.19 | -97.9 | 98.4 | 21 | 636.1 |
| 好望角9999 | reentry | SL, khớp extreme | 805 | 89.8 | 0.79 | 1.03 / -10.91 | -87.9 | 90.7 | 0 | 1036.0 |
| 好望角9999 | reentry | SL, khớp level | 805 | 89.8 | 0.84 | 1.03 / -10.23 | -77.3 | 84.1 | 0 | — |
| xiaojian888999 | reversion | không SL | 2891 | 96.8 | 0.83 | 1.39 / -47.53 | -99.7 | 99.9 | 93 | 374.8 |
| xiaojian888999 | reversion | SL, khớp extreme | 3245 | 94.3 | 0.72 | 1.30 / -25.96 | -99.9 | 99.9 | 0 | 293.0 |
| xiaojian888999 | reversion | SL, khớp level | 3245 | 94.3 | 0.82 | 1.30 / -24.11 | -99.4 | 99.7 | 0 | 445.0 |
| xiaojian888999 | reentry | không SL | 6693 | 97.0 | 0.93 | 1.33 / -47.38 | -99.7 | 99.9 | 202 | 374.8 |
| xiaojian888999 | reentry | SL, khớp extreme | 8660 | 94.6 | 0.85 | 1.24 / -25.65 | -100.0 | 100.0 | 0 | 254.1 |
| xiaojian888999 | reentry | SL, khớp level | 8660 | 94.6 | 0.91 | 1.24 / -24.14 | -100.0 | 100.0 | 0 | 356.6 |
| Shallow-Pair-Frog | reversion | không SL | 517 | 72.3 | 0.80 | 21.70 / -67.11 | -100.0 | 100.0 | 143 | 136.9 |
| Shallow-Pair-Frog | reversion | SL, khớp extreme | 1652 | 18.6 | 0.72 | 0.13 / -0.04 | -7.5 | 8.4 | 0 | — |
| Shallow-Pair-Frog | reversion | SL, khớp level | 1652 | 18.6 | 0.90 | 0.13 / -0.03 | -2.2 | 4.3 | 0 | — |
| Shallow-Pair-Frog | reentry | không SL | 736 | 73.4 | 0.85 | 24.33 / -69.84 | -100.0 | 100.0 | 196 | 136.9 |
| Shallow-Pair-Frog | reentry | SL, khớp extreme | 3141 | 18.5 | 0.69 | 0.13 / -0.04 | -15.5 | 16.4 | 0 | — |
| Shallow-Pair-Frog | reentry | SL, khớp level | 3141 | 18.5 | 0.88 | 0.13 / -0.03 | -4.9 | 6.8 | 0 | — |
| BestMax | reversion | không SL | 1260 | 96.0 | 0.93 | 3.44 / -83.69 | -100.0 | 100.0 | 51 | 90.7 |
| BestMax | reversion | SL, khớp extreme | 1386 | 88.1 | 0.76 | 2.63 / -23.75 | -100.0 | 100.0 | 0 | 74.5 |
| BestMax | reversion | SL, khớp level | 1386 | 88.1 | 0.87 | 2.63 / -20.52 | -99.8 | 100.0 | 0 | 247.1 |
| BestMax | reentry | không SL | 4995 | 96.3 | 0.98 | 3.56 / -83.87 | -100.0 | 100.0 | 185 | 23.2 |
| BestMax | reentry | SL, khớp extreme | 7416 | 87.9 | 0.93 | 2.64 / -23.45 | -100.0 | 100.0 | 0 | 23.8 |
| BestMax | reentry | SL, khớp level | 7416 | 87.9 | 0.99 | 2.64 / -20.53 | -100.0 | 100.0 | 0 | 93.8 |
| 星火研究院-大象 | reversion | không SL | 5410 | 97.8 | 0.51 | 0.42 / -37.81 | -100.0 | 100.0 | 92 | 146.2 |
| 星火研究院-大象 | reversion | SL, khớp extreme | 6470 | 96.5 | 0.40 | 0.42 / -24.50 | -100.0 | 100.0 | 0 | 102.5 |
| 星火研究院-大象 | reversion | SL, khớp level | 6470 | 96.5 | 0.42 | 0.42 / -23.27 | -100.0 | 100.0 | 0 | 114.8 |
| 星火研究院-大象 | reentry | không SL | 13485 | 97.8 | 0.46 | 0.37 / -32.90 | -100.0 | 100.0 | 233 | 74.6 |
| 星火研究院-大象 | reentry | SL, khớp extreme | 18483 | 96.4 | 0.43 | 0.32 / -17.93 | -100.0 | 100.0 | 0 | 41.5 |
| 星火研究院-大象 | reentry | SL, khớp level | 22933 | 96.4 | 0.48 | 0.29 / -15.48 | -100.0 | 100.0 | 0 | 50.5 |


Nhận xét đối chứng (đọc kèm hai bảng trên):

- Thêm SL **đổi win rate lấy kích thước thua**: maomao12345 (reentry, A) thắng 89,9% → 70,7%, TB thua −27,0% → −7,1% vốn, không còn thanh lý; nhưng PF 1,27 → 0,92 (khớp extreme) hoặc 1,01 (khớp level).
  Nghĩa là phần lớn "lãi" của bản không SL ở cửa sổ A là *nhận rủi ro đuôi chưa bị hoá giải*, không phải edge.
- **Giả định khớp SL làm đổi dấu kết quả** ở nhiều ô: maomao12345 (reentry, A) −23,7% (extreme) vs +2,4% (level); BestMax (reentry, A) +55,6% vs +132,8%; xiaojian888999 (reversion, A) +44,1% vs +76,9%.
  Backtest chỉ dùng khớp `level` đánh giá quá cao các chiến lược có SL gần.
- Ở cửa sổ B, SL **không cứu được** phần lớn bot: maomao12345, xiaojian888999, BestMax, 星火研究院-大象 vẫn cháy (−96% đến −100%) vì điểm vào trung tính không có edge và ký quỹ toàn vốn,
  mỗi lần cắt lỗ mất 6–25% vốn, hàng nghìn lệnh. Ngoại lệ là **Shallow-Pair-Frog**: ký quỹ lệnh đầu chỉ 0,0267% nên SL gần chỉ mất ~0,03–0,04% / lệnh (win 18,5%, TB thắng 0,13%) và tổng −15,5% (extreme) / −4,9% (level) thay vì cháy −100%.
  好望角9999: SL cải thiện `reentry` (−97,9% → −87,9% extreme / −77,3% level) nhưng với `reversion` kết quả phụ thuộc kiểu khớp (−53,2% extreme, −23,8% level, so với −51,0% không SL). Đó là bài học về **kích thước** và về giả định khớp, không phải về win rate.


## 5. Độ nhạy theo kích thước (ký quỹ lệnh đầu × 0,25)

Chạy `20261002_030219_scale0.25.json` (cùng mọi thứ khác, `--size-scale 0.25 --no-controls`): ký quỹ lệnh đầu bằng 25% mức lớn nhất.


**tín hiệu bắt hồi — cửa sổ A**

| Bot | lệnh | win% | PF | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) | tầng max |
|---|---|---|---|---|---|---|---|---|
| maomao12345 | 124 | 91.9 | 2.14 | 27.7 | 5.8 | 10 | — | 18 |
| 好望角9999 | 7 | 100.0 | — | -0.6 | 6.6 | 0 | — | 22 |
| xiaojian888999 | 209 | 97.6 | 1.08 | 2.7 | 12.0 | 5 | — | 10 |
| Shallow-Pair-Frog | 19 | 100.0 | — | 55.5 | 8.7 | 0 | — | 11 |
| BestMax | 57 | 98.2 | 2.34 | 28.8 | 26.7 | 1 | — | 23 |
| 星火研究院-大象 | 638 | 98.3 | 0.58 | -22.3 | 26.9 | 9 | — | 1 |

**tín hiệu bắt hồi — cửa sổ B**

| Bot | lệnh | win% | PF | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) | tầng max |
|---|---|---|---|---|---|---|---|---|
| maomao12345 | 2569 | 85.5 | 0.90 | -54.8 | 76.9 | 372 | — | 18 |
| 好望角9999 | 498 | 97.2 | 1.13 | 16.9 | 30.9 | 14 | — | 26 |
| xiaojian888999 | 2891 | 96.8 | 0.86 | -56.4 | 64.4 | 93 | — | 10 |
| Shallow-Pair-Frog | 508 | 73.2 | 0.83 | -87.1 | 96.6 | 136 | 500.1 | 12 |
| BestMax | 1260 | 96.0 | 0.89 | -81.3 | 94.9 | 51 | — | 23 |
| 星火研究院-大象 | 5410 | 97.8 | 0.47 | -93.7 | 93.9 | 92 | 720.9 | 1 |

**vào lại ngay khi trống — cửa sổ A**

| Bot | lệnh | win% | PF | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) | tầng max |
|---|---|---|---|---|---|---|---|---|
| maomao12345 | 318 | 89.9 | 1.35 | 27.4 | 13.4 | 32 | — | 18 |
| 好望角9999 | 5 | 100.0 | — | -1.3 | 6.9 | 0 | — | 23 |
| xiaojian888999 | 294 | 97.3 | 0.99 | -1.2 | 19.3 | 8 | — | 10 |
| Shallow-Pair-Frog | 30 | 96.7 | 5.51 | 109.6 | 21.5 | 1 | — | 12 |
| BestMax | 171 | 97.7 | 1.60 | 57.2 | 31.7 | 4 | — | 23 |
| 星火研究院-大象 | 1168 | 97.8 | 0.51 | -50.1 | 50.1 | 20 | — | 1 |

**vào lại ngay khi trống — cửa sổ B**

| Bot | lệnh | win% | PF | lãi thực hiện % | MDD MTM % | thanh lý | cháy (ngày) | tầng max |
|---|---|---|---|---|---|---|---|---|
| maomao12345 | 7791 | 85.9 | 0.97 | -43.3 | 78.6 | 1097 | — | 18 |
| 好望角9999 | 555 | 96.2 | 0.81 | -37.8 | 51.3 | 21 | — | 26 |
| xiaojian888999 | 6692 | 97.0 | 0.92 | -61.0 | 72.9 | 201 | — | 10 |
| Shallow-Pair-Frog | 730 | 74.0 | 0.88 | -94.7 | 98.9 | 190 | 838.7 | 12 |
| BestMax | 4995 | 96.3 | 0.99 | -65.2 | 99.1 | 185 | 861.3 | 23 |
| 星火研究院-大象 | 15144 | 97.8 | 0.49 | -99.9 | 99.9 | 260 | 308.0 | 1 |

Nhận xét độ nhạy: số lần thanh lý **không đổi** (thanh lý do giá, không do kích thước), nhưng mỗi lần mất ít hơn nên MDD và cháy giảm: ở cửa sổ B chỉ 5/12 ô còn cháy (≤ −90%; Shallow-Pair-Frog cả hai, BestMax reentry, 星火研究院-大象 cả hai, sau 308–861 ngày thay vì 23–375),
MDD MTM vẫn 31–99%. **Lãi thực hiện ở B vẫn âm ở 11/12 ô** (−38% … −99,9%); ô duy nhất dương là 好望角9999 + tín hiệu bắt hồi (+16,9%, PF 1,13, MDD 30,9% — một tài sản, một đường giá, không kết luận được gì thêm).
Ở cửa sổ A có 7/12 ô dương (xiaojian888999 reversion chỉ +2,7%), nhưng 5/12 ô vẫn âm với MDD tới 50%. Giảm kích thước kéo dài thời gian sống, **không tạo ra edge**.


## 6. Vì sao trông như toàn thắng — và điều xảy ra trong 3 năm

1. **Cấu trúc payoff bất đối xứng, không phải edge.** Chốt lời 0,2–1,8% giá nên gần như mọi rổ DCA cuối cùng chạm TP nếu giá hồi; thua là sự kiện hiếm nhưng khổng lồ.
   Ví dụ maomao12345 reentry cửa sổ B: thắng 85,9% với TB thắng +4,28% và TB thua −26,95% vốn → **cần thắng ≥ 86,3% chỉ để hoà vốn**; thực tế PF 0,96.
   xiaojian888999: thắng 97,0% nhưng TB thua gấp ~36 lần TB thắng (−47,4% vs +1,33%) → PF 0,93. 星火研究院-大象: thắng 97,8%, PF 0,46.
2. **Win rate chỉ đếm lệnh đã đóng.** Bot gần như lúc nào cũng có vị thế mở (cột "% thời gian mở": 76–100% ở `reentry`, 32–94% ở `reversion`) và các vị thế đang chìm trong lỗ không vào thống kê.
   Ở cửa sổ A với `reentry` cả 6 bot đều còn vị thế mở lúc cuối; ví dụ 好望角9999 chỉ có 5 lệnh đóng (100% thắng) nhưng tầng max 23, MDD MTM 27,7%, lãi thực hiện −5,8%.
3. **Cửa sổ ngắn là ngẫu nhiên có lợi.** Trong cửa sổ A, vài ô cho kết quả rất đẹp (Shallow-Pair-Frog reversion: 19 lệnh, 100% thắng, +356%, MDD 27%; maomao12345 reversion +203%, PF 2,50)
   nhưng cùng cấu trúc ở ô khác của cùng cửa sổ lại cho −16% … −95% (xiaojian888999, BestMax, 星火研究院-大象), và maomao12345 trên DOGE −41% / −34% trong khi ETH +233% / +527%.
   Với 3–20 lệnh đóng, win rate 100% là chuyện thường kể cả khi kỳ vọng âm.
4. **Đường tới cháy rất ngắn.** Ở cửa sổ B, **11/12** cặp (bot × cách vào) cháy (≤ −90%); chỉ 好望角9999 + tín hiệu bắt hồi sống sót (−51%, MDD 84,8%, vốn thấp nhất 29%).
   Thanh lý đầu tiên xảy ra rất sớm: trong 3,0–61,7 ngày đầu của cửa sổ (trung vị 11,3 ngày trên 21 ô có thanh lý; 3,0–3,7 ngày ở maomao12345 reentry, xiaojian888999 và 星火研究院-大象) và số lần thanh lý ở cửa sổ B lên tới hàng chục đến hàng nghìn (maomao12345 reentry: 1.097 lần).
   Cháy toàn bộ (đường vốn trung bình ≤ 10%) sau 23 ngày (BestMax) … 636 ngày (好望角9999 reentry).
   Mỗi lần thanh lý ở rổ đầy mất tới ~100% ký quỹ của rổ — và khi rổ dùng hết vốn, mất ~ toàn bộ vốn của sổ.
5. **Lỗ treo lớn trước khi thanh lý**: MAE max 26% (maomao12345), 47% (xiaojian888999), 70–75% (Shallow-Pair-Frog reentry), 82–83% (BestMax) vốn trong *một* vị thế; MDD MTM ở cửa sổ A đã 24–99%.
   Những đợt lỗ treo này không hiện trong PnL đã chốt của trang copy-trading.
6. **Kết quả ở 3 năm khác hẳn cửa sổ A** vì cửa sổ A là một lát cắt ngắn của một đường giá duy nhất; trên 3 năm có đủ các cú giảm sâu/nhanh (và với SHORT: cú tăng) quét rổ DCA. Thời điểm vốn thấp nhất của nhiều bot ở B rơi vào các ngày cụ thể
   (xem `min_equity_date` trong JSON), không phải rải đều.

## 7. Giới hạn — đọc trước khi trích dẫn

- **Điểm vào là giả định** (mục 2). Không thể suy ra từ đây rằng bot thật lỗ hay có edge; chỉ có thể nói *cấu trúc* "DCA/martingale + đòn bẩy cao + không cắt lỗ + TP nhỏ" có profile thanh lý/cháy như trên **khi điểm vào không có edge** hoặc edge nhỏ hơn đuôi.
- **Isolated margin.** Bot thật trên OKX thường dùng cross margin (đồng vốn cả tài khoản làm đệm) nên có thể chịu sâu hơn thanh lý isolated ở cùng cấu hình; mô phỏng này không có cross. Số tầng thực dùng (≤ 26) vì thế thấp hơn rất nhiều số tầng bot công bố (58–61).
- **Ký quỹ lệnh đầu = lớn nhất cho phép** (toàn vốn khi nhồi hết tầng). Bot thật có thể nhỏ hơn; độ nhạy ×0,25 ở mục 5 cho thấy mức độ thay đổi, không thay thế dữ liệu thật về kích thước.
- **Một đường giá duy nhất mỗi cửa sổ** (không Monte Carlo), các cửa sổ A rất ngắn (28–137 ngày) và một số ô chỉ có vài lệnh đóng; không có khoảng tin cậy.
- **Khớp lệnh trên nến 1m**: lệnh limit DCA/TP được coi là khớp khi giá chạm mức (lạc quan, không xếp hàng); thứ tự trong một nến theo quy ước bi quan của engine (thoát/DCA bất lợi trước, TP chỉ khi nến không nhồi tầng nào).
  MDD lấy mẫu mỗi giờ nên là cận dưới của đáy thật trong giờ.
- **Chia tài sản**: sổ vốn riêng từng tài sản, trung bình đều, không tái cân bằng; bot thật dùng chung vốn nhiều mã (BestMax chỉ chạy được SOL, 好望角9999 chỉ ETH vì ONE/ZEC/PUMP/HYPE/SNDK không có trong dữ liệu).
- **Thời gian cooldown 5 phút** và hai chân hedge của bot hai chiều (reentry) là lựa chọn của chúng tôi.
- Thống kê "công bố" của bot đo trên cửa sổ riêng và chỉ lệnh đã đóng; so sánh trực tiếp chỉ mang tính định tính (số lệnh/ngày và giữ lệnh của bản tái tạo lệch so với công bố; xem `hold_med_h`, `trades_per_day` trong JSON).
- Không có dữ liệu thanh khoản/độ sâu sổ lệnh; trượt giá cố định 0,02%; thanh lý khớp đúng giá thanh lý (không có phí bảo hiểm/ thanh lý một phần).

## 8. Tái lập

- Code: `backend/core/research/research_topbots.py` (tất định; `require_memory_limit`; cổng chất lượng dữ liệu `require_data_ok_or_exit` bắt buộc), test: `test/test_research_topbots.py`.
- Kết quả thô (mọi bot × cách vào × cửa sổ × cấu hình, từng tài sản, đường vốn theo ngày, các tham số ánh xạ): `data/_cache/research/topbots/<ts>.json`.
- Lệnh: `ops/run_limited.sh -- test/scripts/research_topbots.py [--bots a,b] [--windows A,B] [--variants reentry,reversion] [--size-scale 0.25 --no-controls]`.
