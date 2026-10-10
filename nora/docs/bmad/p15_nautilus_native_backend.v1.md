# P15 — Backend dùng thẳng NautilusTrader làm core engine (plan + TODO triển khai)

Quyết định (sếp, 2026-10-10): không tự build engine backtest. Giữ UI/UX hiện tại; `backend/` chỉ còn API + lớp đồng bộ input từ view sang chuẩn Nautilus và kết quả Nautilus về shape UI. Engine cũ đã cất ở `test/backtest-no` (chỉ để tham chiếu, không import).

## 1. Khả thi?
| Câu hỏi | Trả lời (đã kiểm trên máy) |
|---|---|
| Miễn phí? | Có. NautilusTrader mã nguồn mở, giấy phép **LGPL-3.0-only** (metadata gói). Dùng làm thư viện (import, cài từ PyPI) trong sản phẩm đóng/thương mại: được. Nếu SỬA mã của chính Nautilus và phân phối bản sửa thì phải công bố phần sửa → nguyên tắc: KHÔNG fork/sửa Nautilus, chỉ dùng API công khai. |
| Bản đang có | `nautilus_trader 2.0.0rc6` trong `~/.venvs/nautilus` (Python 3.14). Yêu cầu Python **>=3.12,<3.15**. Venv backend hiện tại `~/.venvs/nora` là **3.11** → phải chuyển API sang venv 3.12–3.14. |
| Có OKX? | Có adapter `nautilus_trader.adapters.okx` (cùng binance, bybit, hyperliquid, dydx…) → live/paper/demo cũng chạy bằng Nautilus (TradingNode), bỏ bot tự viết. |
| Funding perp? | Có kiểu dữ liệu `FundingRateUpdate`; cần xác minh backtest có tự áp funding cho vị thế perp ở bản đang dùng (nếu không: actor/strategy áp như harness S11c). |
| Thống kê? | Có `PortfolioAnalyzer` + statistic (CAGR, Calmar, MaxDrawdown, ProfitFactor, Expectancy, Volatility…) → dùng làm nguồn số liệu chính. |
| Chuẩn đúng? | Engine của Nautilus = chuẩn → kết quả "khớp Nautilus" tự đúng; harness nautilus_diff chuyển thành bộ test hồi quy giữa các phiên bản Nautilus. |
| Đánh đổi | Nhanh kém engine numba cũ (event-driven, mỗi config ~ vài giây/tháng dữ liệu/symbol trên 1m). Research hàng loạt (funnel hàng nghìn config) sẽ chậm → làm research sau bằng tầng sàng lọc riêng hoặc chạy song song nhiều process. Không có AMM/DEX → tạm bỏ hoặc để sau. |

## 2. Kiến trúc đích
```
frontend (giữ nguyên UX)
   │  HTTP JSON (giữ shape hiện tại; chỗ nào cần đổi thì đổi có chủ đích)
backend/
  routes/            FastAPI (giữ URL hiện tại)
  adapter/
    config.py        input UI → BacktestRunConfig / BacktestEngineConfig / venue (OKX perp, fee, leverage, account MARGIN/NETTING)
    data.py          data/market/<sàn>/... → ParquetDataCatalog Nautilus (Bar 1m + khung lớn, Instrument CryptoPerpetual, FundingRateUpdate)
    strategy.py      chiến lược Nora (DSL alpha + 3 chiến lược hệ thống) → Nautilus Strategy (một lớp chung đọc IR đã biên dịch)
    risk.py          Risk profile theo họ chiến lược (P14-B) → tham số Strategy/RiskEngine của Nautilus
    results.py       kết quả Nautilus (fills, positions, account, PortfolioAnalyzer) → JSON shape UI (trades, equity, metrics, notes)
    jobs.py          chạy backtest Nautilus trong job process (giữ cơ chế job/cache hiện tại)
  live/              TradingNode Nautilus + adapter OKX (paper/demo/live)
  alpha/             DSL + contract + assist (giữ: biên dịch code người dùng → IR; Strategy chung thực thi IR)
docs/backend.md      chỉ mô tả lớp adapter + link docs Nautilus (https://nautilustrader.io/docs/)
```
Không còn: core/backtest.py kernel, reference engine, funnel kernel path, KernelBook, nautilus_diff (chuyển thành regression giữa phiên bản).

## 3. Cập nhật Nautilus (bắt buộc có cơ chế)
- Pin phiên bản trong `requirements` của backend (vd `nautilus_trader==X.Y.Z`); KHÔNG cài từ nhánh develop trên production (chỉ dùng develop để thử trước).
- Job định kỳ (systemd timer tuần): kiểm PyPI có bản mới → tạo venv tạm, cài bản mới, chạy bộ hồi quy (mục 5-T3) → báo khác biệt (lệnh/vốn/thống kê) so với bản đang pin.
- Nâng phiên bản = đổi pin + chạy cổng + ghi CHANGELOG nội bộ "nautilus X→Y: thay đổi kết quả do …" (link release notes Nautilus).
- Theo dõi breaking change API (Nautilus còn đổi API giữa các bản): adapter là lớp DUY NHẤT gọi API Nautilus → chỉ sửa một chỗ.

## 4. TODO

### Phase 0 — Chuẩn bị
- [ ] 0.1 Venv API mới Python 3.12–3.14 (khuyên 3.12/3.13 ổn định với numpy/pandas/fastapi): cài fastapi/uvicorn/pandas/pyarrow + `nautilus_trader==<pin>`; systemd unit nora-api trỏ venv mới; giữ `~/.venvs/nora` cho tham chiếu.
- [ ] 0.2 Chọn bản pin: bản stable mới nhất trên PyPI (không rc) — kiểm có OKX adapter + funding backtest; ghi lý do.
- [ ] 0.3 Kiểm kê toàn bộ endpoint UI dùng (frontend/src/api.js ↔ routes, đã có api:check) và shape JSON từng màn hình → `docs/bmad/p15_api_contract.md` (đây là hợp đồng phải giữ).
- [ ] 0.4 Kiểm kê tính năng engine cũ đang được UI dùng → bảng "Nautilus có sẵn / làm trong Strategy / bỏ": fee maker/taker, slippage (FillModel), SL/TP/trailing (order types), timeout, cooldown, DCA ladder, ATR stop, sizing risk, portfolio caps (RiskEngine + strategy), kill switch, funding, liquidation (MarginAccount), regime gating, signal event (on_bar), multi-timeframe (bar types), DEX/AMM (bỏ/để sau), tick backtest.

### Phase 1 — Dữ liệu
- [ ] 1.1 `adapter/data.py`: chuyển pkl 1m (attrs metadata) → `ParquetDataCatalog` (BarType `<SYM>-PERP.OKX-1-MINUTE-LAST-EXTERNAL`, ts_event = bar close theo chuẩn Nautilus), Instrument `CryptoPerpetual` từ thông số OKX (tick size, lot size, ctVal, margin, maker/taker fee), FundingRateUpdate từ funding.pkl.
- [ ] 1.2 Khung lớn: để Nautilus tự tổng hợp (internal bar aggregation) hoặc ghi sẵn bar khung lớn EXTERNAL — chọn một, ghi lý do (khuyên: chỉ 1m EXTERNAL, khung lớn INTERNAL timestamp_on_close).
- [ ] 1.3 Crawl tiếp tục ghi pkl như hiện tại + bước sync catalog sau mỗi lần crawl (idempotent, theo mtime).
- [ ] 1.4 Test: số bar, khoảng thời gian, giá/khối lượng trong catalog == pkl.

### Phase 2 — Chiến lược
- [ ] 2.1 `adapter/strategy.py`: một lớp `NoraStrategy(Strategy)` nhận IR (từ alpha/compile) + position/risk params; tín hiệu: tính chỉ báo bằng indicator Nautilus nếu có tương đương, còn lại tính trên bar đã đóng bằng mã chỉ báo hiện có (port sang adapter, KHÔNG tham chiếu engine cũ); quyết định vào lệnh trong `on_bar` của khung tín hiệu (sự kiện đóng nến).
- [ ] 2.2 Lệnh: market vào; SL = StopMarket reduce-only; TP = Limit reduce-only; trailing = TrailingStopMarket; DCA = Limit các tầng; timeout/cooldown = timer/logic trong strategy; sizing theo risk profile.
- [ ] 2.3 Risk profiles (P14-B) áp trong strategy (neo SL, quyền DCA, luật hợp lệ) — contract alpha kiểm trước khi chạy.
- [ ] 2.4 3 chiến lược hệ thống + 50 mẫu chạy được trên NoraStrategy; alpha người dùng (DSL) chạy được.
- [ ] 2.5 Đa tài sản: một strategy instance mỗi (chiến lược × symbol) hoặc một instance quản lý nhiều instrument; giới hạn danh mục (max positions/gross/kill) qua RiskEngine + một Actor danh mục.

### Phase 3 — Kết quả + API
- [ ] 3.1 `adapter/results.py`: fills/positions/account → trades (cùng field UI đang dùng), equity curve (account balance + MTM), metrics: dùng PortfolioAnalyzer; chỉ số UI cần mà Nautilus không có → tính trong results.py từ equity/trades (một định nghĩa) + meta.metrics.defs cập nhật help_vi ("theo Nautilus …").
- [ ] 3.2 Notes/explain education (metrics/charts build_notes) đọc từ results mới — giữ nguyên ngữ nghĩa "mọi số trích từ kết quả".
- [ ] 3.3 Routes giữ URL; job custom_backtest / book_backtest / wfa / mc chạy Nautilus trong process job; meta cập nhật (engine = "nautilus X.Y.Z").
- [ ] 3.4 api:check + so shape JSON với `p15_api_contract.md` (test tự động).

### Phase 4 — Live
- [ ] 4.1 TradingNode Nautilus + adapter OKX (demo/live) + sandbox/paper; cùng NoraStrategy → backtest và live một mã.
- [ ] 4.2 Chuyển 3 bot: dừng bot cũ (đóng/đối soát vị thế demo), khởi động trên TradingNode; trạng thái lưu theo cơ chế Nautilus (cache/persistence).
- [ ] 4.3 Trang Live đọc từ Nautilus (orders/positions/account) qua API.

### Phase 5 — Dọn + docs + cập nhật
- [ ] 5.1 Xoá core engine cũ khỏi backend (đã có bản ở test/backtest-no), xoá test chỉ dành cho engine cũ; layering test cập nhật.
- [ ] 5.2 `docs/backend.md` + README: kiến trúc adapter, link https://nautilustrader.io/docs/ và https://github.com/nautechsystems/nautilus_trader ; bỏ docs engine cũ.
- [ ] 5.3 Cơ chế cập nhật Nautilus (mục 3): timer + script `ops/nautilus_upgrade_check.sh` + bộ hồi quy.

## 5. Kiểm thử (T)
- [ ] T1 Hợp đồng API: mọi màn hình UI (playwright E2E như hiện có) hiển thị đúng với backend mới; api:check sạch.
- [ ] T2 So kết quả mới vs engine cũ trên 50 mẫu + 3 chiến lược: bảng khác biệt (kỳ vọng khác do quy ước khớp lệnh Nautilus: lệnh market từ on_bar khớp ở close nến tín hiệu thay vì open nến kế) — mọi khác biệt phải giải thích được, không có số "lạ".
- [ ] T3 Hồi quy Nautilus: bộ kịch bản cố định (từ nautilus_diff S1–S11 chuyển sang chạy NoraStrategy trên Nautilus) lưu hash kết quả; dùng khi nâng phiên bản.
- [ ] T4 Hiệu năng: thời gian 1 lần chạy Studio (10 symbol × 3 năm 1m) — nếu quá chậm cho UX: dùng khung base 1h cho Studio (tuỳ chọn), cache catalog, chạy song song theo symbol.
- [ ] T5 Live demo chạy 24h trên TradingNode không lỗi, đối soát lệnh với sàn.

## 6. Rủi ro cần anh/sếp biết
1. Tốc độ: Nautilus chậm hơn engine numba (đổi lại đúng chuẩn và có live sẵn). Research hàng loạt cần thiết kế riêng sau.
2. Nautilus còn ở giai đoạn đổi API giữa các bản (2.0 đang rc) → pin bản + lớp adapter duy nhất.
3. Python ≥3.12: cần chuyển venv backend.
4. DEX/AMM không có trong Nautilus → tạm bỏ khỏi UI hoặc để sau.
5. LGPL: không sửa/fork mã Nautilus; nếu cần hành vi khác → làm trong Strategy/Actor của mình.
