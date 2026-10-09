# Spec: trang "Top 10 OKX Copy-Trade" (tiếng Việt, cho sếp đọc)

Mục đích: sếp cần biết 10 lead copy-trade top OKX hiện tại chơi kiểu gì để thắng thị trường hiện tại. Đơn giản, trọng tâm, số liệu chính xác theo dữ liệu (không bịa, không làm tròn sai).

## Dữ liệu
- `bots.json` (mảng 10 bot, thứ tự = hạng OKX) — nhúng inline vào HTML trong `<script type="application/json" id="data">` (không fetch).
- `summary.json` — nhúng inline `<script type="application/json" id="summary">`: regime thị trường + nhận định tổng quan + mô tả từng bot (văn bản đã viết sẵn, dùng nguyên văn).
- `candles/<SYM>.json` — nến 1H `[[ts_ms, o, h, l, c], ...]`, file riêng, tải bằng `fetch("candles/"+sym+".json")` khi cần (cache trong Map). Có thể không có file cho vài mã → hiện "Không có nến cho mã này".

Field bot (xem bots.json thực tế): rank, name, url, leadDays, copiers, maxCopiers, aum, pnl90 (USDT, OKX công bố 90 ngày), roi90 (%), winOkx (% OKX công bố), profitDays, lossDays, curve [[ts, pnlCum, roiCum%]] (đường PnL lũy kế 90 ngày OKX công bố), n (lệnh đóng), perDay, win (% lệnh đóng lãi), realized, pf, payoff, longPct, levMed, levMax, holdMed/holdWin/holdLoss (giờ), maxLoss, maxWin, top5Share, addPct (% lệnh là tầng vào thêm), addDownPct, stepMed (% bước giá giữa 2 tầng), maxLayers, winMaeMed (% giá đi ngược trung vị của lệnh thắng trước khi về lãi), winMaeP90, momPct (% lệnh vào cùng chiều biến động 24h trước), syms [[sym,count]], nOpen, openUpl, openMargin, open[] (sym có thể null = OKX ẩn), trades[] {sym, side, lev, o, c, po, pc, pnl, pr (% trên ký quỹ), mg, mae, add, bk}.
summary.json: {asOf, window, regime:{...}, headline, points[], styles[{key,label,desc,bots[]}], bots:{<name>:{style, styleKey, verdict, how, edge, risk}}, method[]}.

## Bố cục (2 phần + chi tiết)
1. **Tổng quan**: tiêu đề + dòng thời điểm dữ liệu. Ô regime hiện tại (BTC/ETH 7 ngày, đi ngang/xu hướng). Phân bố lối chơi (vd "6/10 DCA bắt hồi") dạng thanh/chip đếm, mỗi lối 1 dòng mô tả. 3–5 nhận định ngắn (summary.points). Không hero to.
2. **Bảng 10 bot**: mỗi hàng một bot. Cột: Hạng OKX · Tên (link OKX nhỏ) · Lối chơi (chip màu theo styleKey) · PnL 90N · ROI 90N · Thắng % (lệnh) · PF · Đòn bẩy TV · Giữ lệnh TV · Long % · Vào thêm % · Lỗ treo (openUpl, đỏ nếu âm) · Người copy · AUM. Bảng scroll ngang trong container riêng trên mobile. Hàng có hover + cursor pointer + focus bàn phím (Enter). Hàng đang chọn được đánh dấu.
3. **Chi tiết bot** (hiện ngay dưới bảng, mặc định chọn bot đầu tiên để trang không trống):
   - Đầu: tên, hạng, link OKX, chip lối chơi, verdict (1 câu). Đoạn "Cách chơi" (how), "Vì sao thắng" (edge), "Rủi ro" (risk).
   - Lưới tham số tổng quan (label/value): lệnh đóng 90N, lệnh/ngày, thắng %, PF, payoff, đòn bẩy TV/max, giữ lệnh thắng vs lỗ, long %, vào thêm %, bước DCA TV, tầng tối đa, giá đi ngược TV của lệnh thắng, theo đà %, lệnh lỗ lớn nhất, top 5 lệnh chiếm % lãi, vị thế mở/lỗ treo, mã đánh nhiều (top 5 kèm số lệnh).
   - **Biểu đồ đường**: PnL lũy kế 90 ngày (curve, OKX công bố) — line/area. Đánh dấu điểm cuối.
   - **Biểu đồ nến 1H** của 1 mã (select chọn mã, mặc định mã đánh nhiều nhất) + marker vào/thoát của các lệnh đóng của bot trên mã đó: vào long = mũi tên lên dưới nến (xanh), vào short = mũi tên xuống trên nến (đỏ), thoát = chấm/hình tròn (màu theo lãi/lỗ). Tooltip/legend giải thích ký hiệu. Nếu nhiều marker quá (>400) chỉ vẽ trong vùng đang xem hoặc gộp — tuỳ, nhưng vẫn đúng.
   - **List lệnh**: bảng các lệnh đóng (mới nhất trước) lọc theo mã đang chọn (+ tuỳ chọn "Tất cả mã"): Vào (giờ UTC+7? → dùng giờ Việt Nam UTC+7, ghi rõ), Thoát, Mã, Chiều, Đòn bẩy, Giá vào, Giá ra, Ký quỹ, PnL USDT, % ký quỹ, Giá đi ngược tối đa (mae), cờ "tầng thêm" (add). Click một lệnh → chuyển mã trên biểu đồ nến và zoom vào khoảng [open-12h, close+12h], highlight lệnh. Phân trang hoặc giới hạn hiển thị 200 + nút "Xem thêm".
   - Vị thế đang mở (nếu có): mã (hoặc "OKX ẩn"), chiều, đòn bẩy, giá vào, giá mark, lỗ/lãi treo, % — bảng nhỏ.
4. Chân trang: phương pháp (summary.method) ngắn, nguồn: OKX public API v5 (copytrading public-*, market history-candles).

## Kỹ thuật
- Chart: `<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>` (global `LightweightCharts`, API v4: createChart, addCandlestickSeries, addAreaSeries/addLineSeries, series.setMarkers(sorted by time), timeScale().setVisibleRange). Time phải là giây UTC (ts/1000), marker time phải khớp thời điểm nến: floor về giờ (Math.floor(ts/3600000)*3600). Markers phải sort tăng dần theo time. Màu chart lấy từ CSS tokens (getComputedStyle) và cập nhật khi đổi theme (matchMedia change + MutationObserver data-theme).
- Định dạng số kiểu Việt: dấu chấm nghìn, phẩy thập phân (Intl 'vi-VN'). Tiền: "$" hoặc "USDT" nhất quán (dùng USDT cho PnL, $ cho AUM cũng được — chọn USDT cho tất cả).
- Theme: tokens trên :root (light), dark qua @media guarded + [data-theme=dark] như contract. body background token. Semantic xanh/đỏ cho lãi/lỗ riêng với accent.
- Font: Google Fonts, hỗ trợ tiếng Việt + chữ Hán trong tên bot (fallback Noto Sans SC). Số tabular-nums.
- Responsive 400px, gutter 16px, bảng overflow-x:auto. `[hidden]` để ẩn. Không alert/print.
- Viết page content không kèm <!doctype>/<html>/<head>/<body>; `<title>` ở đầu: "Top 10 OKX Copy-Trade".
- Không dùng emoji. Không 01/02/03 trang trí. Không card khắp nơi.

## Bổ sung (ưu tiên hơn phần trên nếu mâu thuẫn)
- bots.json có thêm `pnl30`, `pnl7` (USDT, từ đường PnL OKX). Bảng thêm cột "PnL 30N" và "PnL 7N" ngay sau "PnL 90N" (màu xanh/đỏ theo dấu) vì sếp cần biết ai đang thắng thị trường hiện tại.
- Cột "Thắng %" trong bảng = `winOkx` (OKX công bố); trong lưới chi tiết ghi cả `winOkx` ("Tỷ lệ thắng OKX") và `win` ("Lệnh con có lãi").
- Ghi chú dưới bảng: "PnL 90N, ROI, Thắng %, AUM, người copy: OKX công bố. Các cột khác tính từ lệnh con đã đóng."
- `pr` trong trades đã là % (vd 208.0 = 208%). `mae` đã là % giá (âm). `uplr` của open đã là %. roi90/winOkx/win/longPct/addPct/momPct/top5Share đã là %.
- Hiển thị null là "—". Không suy diễn thêm số nào ngoài dữ liệu.
- Output: thư mục `site/` gồm `site/index.html` (page, nhúng inline bots.json + summary.json) và `site/candles/*.json` (copy từ ../candles). Tạo bằng script build `build.py` đọc bots.json, summary.json, template → index.html (để chạy lại khi dữ liệu đổi).
