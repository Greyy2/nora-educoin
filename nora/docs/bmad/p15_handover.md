# P15 — Chốt kiến trúc + logic (bàn giao, 2026-10-10)

Plan gốc: `p15_nautilus_native_backend.md`. File này là bản CHỐT: kiến trúc, luật logic, hiện trạng, việc còn lại + cổng kiểm. Làm đúng file này; chỗ nào lệch phải hỏi trước.

## 1. Kiến trúc (chốt)

```
frontend (giữ UX) ── /api/* (routes cũ khôi phục: process, alpha, optimize, data, live, engine)
backend/
  main.py                 FastAPI; /api/health = {ok, engine{name,version}}; NotReady → 501 {code:"NOT_READY"}
  routes/                 chỉ parse/validate → gọi optimize/process (job) hoặc module logic. Không logic, không số cố định.
  core/strategy.py        logic KHÔNG thuộc engine (copy nguyên từ engine cũ): evaluate_signals, entry_event_mask, matrix_evaluator,
                          _regime_gate, build_plan/Plan, RiskConfig, SignalEngine/SignalPortfolio (dựng dữ liệu + cột tín hiệu, warmup)
  core/{params,indicator,signal,models,position_size}.py, alpha/   DSL, tham số, contract (không đổi)
  nautilus/               LỚP DUY NHẤT import nautilus_trader
    engine.py             PortfolioEngine(SignalPortfolio) / BacktestEngine(SignalEngine): CÙNG API engine cũ; khớp lệnh/phí/số dư = Nautilus
                          provenance(base_frame) — định nghĩa DUY NHẤT
    strategy.py           NoraSlotStrategy: ngữ nghĩa PositionManager cũ bằng lệnh Nautilus (ENTRY/DCA/SL/TP/TRAIL/EXIT/TIMEOUT/END/KILL tags)
    portfolio.py          Coordinator: luật _admit cũ (max_positions/per_symbol/gross/kill/open_risk/dd_throttle), equity MTM theo giá từng symbol
    catalog.py            đọc ParquetDataCatalog data/market/okx/catalog (1m thật, ts=close), aggregate_frame, instrument từ instruments.json
    version.py, live.py   phiên bản (chỉ báo, không tự cài); kiểm kết nối OKX
  metrics/ carlo/ wfa/ regime/ optimize/   khôi phục nguyên bản, gọi engine qua backend.nautilus.engine
  crawl/                  crawl OKX → pkl + catalog
test/backend-no/          engine cũ + test cũ của engine (chỉ tham chiếu, ngoài suite)
```

Luật kiến trúc:
1. Chỉ `backend/nautilus/` import `nautilus_trader`. Không ai import `backend.core.backtest`, `backend.live`, `backend.signals`.
2. Một định nghĩa cho mỗi logic (tín hiệu: core/strategy; khớp lệnh: Nautilus; luật danh mục: portfolio.Coordinator; provenance: engine.provenance).
3. Không sửa/fork Nautilus. Hành vi riêng → Strategy/Coordinator.
4. Không số giả: chưa có logic → `NotReady` (501). Không fallback âm thầm (thiếu catalog → `CatalogError`).
5. Mọi chạy engine qua job runner (process riêng, ops/run_limited.sh, venv ~/.venvs/nora312, pin nautilus_trader==1.231.0).

## 2. Logic (chốt)

| Hạng mục | Luật |
|---|---|
| Tín hiệu | Tính trên nến ĐÃ ĐÓNG như engine cũ (bit-identical — test_strategy_signal_parity). Warmup từ HISTORY_START. |
| Vào lệnh | Tín hiệu cuối nến i → MARKET gửi tại close nến i, Nautilus khớp tại close nến i (cũ: open nến i+1; 1m ≈ cùng giá). |
| Lệnh chờ | SL = STOP_MARKET reduce_only; TP = LIMIT reduce_only; trailing = TRAILING_STOP_MARKET (bps + activation); DCA = LIMIT từ giá khớp cuối × dca_mults. DCA khớp → modify SL/TP theo avg mới, đặt lại TRAIL. |
| Thời gian | Lệnh chờ khớp đóng dấu thời điểm close nến (cũ: open) → lệch 1 phút ở nến 1m. timeout/cooldown theo ms như cũ. |
| Sizing | flat (order_size_pct) / risk (risk_pct, max_notional_pct) bằng policy cũ; vốn sizing = balance Nautilus + phí vào của vị thế mở. |
| Danh mục | Coordinator = _admit cũ. Kill switch: halt + đóng hết tag KILL. |
| Phí | maker/taker từ tham số slot → đặt trên instrument. Khác phí giữa chiến lược cùng symbol → ValueError. |
| Không mô phỏng (cảnh báo + provenance *_modeled=false, KHÔNG làm giả) | slippage %, funding, thanh lý, limit_through_pct>0, stop_fill="extreme". `intrabar_path="adverse_first"` → ValueError. DEX/AMM/tick → 501. |
| Khung chạy | `base_frame`: 1m = Chuẩn; khung tín hiệu (1h…) = Nhanh. Engine dựng nến khung chạy từ 1m catalog bằng aggregate_frame. |
| Kết quả | get_results() giữ mọi key cũ + `warnings`, `provenance`. final_equity = balance Nautilus = vốn đầu + Σ real_pnl. |

## 3. Hiện trạng đã kiểm (Opus)
- test_nautilus_engine (13) + test_strategy_signal_parity + test_no_mock + test_custom_backtest + test_meta: **73 passed**.
- So engine cũ (10 mẫu × BTC/ETH × 2024H1): số lệnh trùng 20/20; tắt slippage: 10/20 trùng ±2 tick, còn lại lệch ≤1 tick hoặc 1 phút; chênh lợi nhuận ≈ funding cũ.
- Tốc độ: 1 symbol 1 năm 1m ≈ 26 s; 1h ≈ 1 s; 10 symbol × 3 năm 1h ≈ 21–28 s (nguội 56 s).
- Full suite: xem §5 (kết quả lần chạy cuối).

## 4. Việc còn lại (anh triển khai — mỗi mục có cổng kiểm)

| # | Việc | Cổng kiểm (tôi check) |
|---|---|---|
| R1 | ✅ XONG (987 passed). Giữ xanh khi làm R2–R7. Full suite xanh: sửa các test còn lỗi theo §5 (test cũ chưa cập nhật P14 → sửa theo code hiện tại, ghi lý do; test chỉ dành engine cũ → chuyển test/backend-no/tests) | `pytest test/` 0 failed; không giảm assertion che bug |
| R2 | Dọn: chuyển `test/scripts/nautilus_diff/{s10_run_nautilus,s15_compare}.py` và script cũ import engine cũ sang `test/backend-no/scripts/` | grep `backend.core.backtest\|backend.live\|backend.signals\|NautilusRunner\|_make_trackers` trong backend/ test/ (trừ backend-no và test parity) = 0 |
| R3 | Meta: tham số không mô phỏng có `unsupported:true` + help_vi "Nautilus không mô phỏng"; mặc định slippage = 0 để lần chạy mặc định không cảnh báo | test_meta + chạy mặc định `warnings == []` |
| R4 | UI: chọn "Độ chi tiết khớp lệnh" (base_frame: Chuẩn 1m / Nhanh = khung tín hiệu), mặc định Studio = Nhanh; badge provenance trên Result; hiển thị `warnings` | E2E Studio: chạy cả 2 chế độ, badge đúng |
| R5 | Cache kết quả theo (code, RunSpec, digest dữ liệu, version Nautilus, base_frame) + làm nóng 50 mẫu education | mở mẫu ≤1 s lần 2 |
| R6 | Restart nora-api + E2E (`scratchpad/e2e_api.py`): health, meta, samples, live 501, custom job thật, API <1 s khi job chạy | script exit 0 |
| R7 | Live trên Nautilus TradingNode (phase sau, cần duyệt) | — |

## 5. Full suite lần cuối
2026-10-10 (Opus chạy, venv nora312, run_limited): **987 passed, 6 skipped, 0 failed** — 54 phút 54 giây.
