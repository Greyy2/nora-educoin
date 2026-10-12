# Hợp đồng API Nora Backend (P15 — Nautilus Native)

Nguồn sự thật cho toàn bộ endpoint backend giao tiếp với frontend (`frontend/src/api.js`).
Mọi endpoint phải tuân thủ tuyệt đối cấu trúc này. Nếu logic chưa hoàn tất, trả `HTTP 501 Not Implemented` với `{ "detail": { "code": "NOT_READY", "message": "Chức năng đang được tích hợp" } }`. Tuyệt đối không trả số giả.

---

## 1. Bảng ánh xạ tham số UI sang Nautilus Trader

| Tham số UI (`position.*`) | Kiểu | Nautilus Trader Core Implementation |
|---|---|---|
| `order_size_pct` | float (1–100%) | Sizing động từ `portfolio.account(venue).balance_free * order_size_pct * leverage` |
| `leverage` | int (1–125) | Cấu hình `leverages={instrument_id: Decimal(leverage)}` trong `engine.add_venue` |
| `maker_fee`, `taker_fee` | float | `MakerTakerFeeModel` + `maker_fee`/`taker_fee` trong `CryptoPerpetual` lấy từ OKX instrument |
| `slippage_pct` | float | **Không mô phỏng** (Nautilus không có trượt giá %): provenance `slippage_modeled:false` + `warnings` khi ≠ 0; tham số `unsupported:true` trong meta; mặc định 0 |
| `stop_loss_rate` (SL) | float | `StopMarketOrder` (reduce_only=True) neo theo giá khớp entry / avg position |
| `take_profit_rate` (TP) | float | `LimitOrder` (reduce_only=True) |
| `trailing_stop_rate` | float | `TrailingStopMarketOrder` (activation_price, callback_rate / basis_points) |
| `dca_steps`, `dca_orders` | list / int | Đặt các `LimitOrder` đa tầng; cập nhật qty SL/TP khi tầng DCA khớp (`modify_order`) |
| `timeout_bars` | int | Đặt timer cảnh báo đóng lệnh sau N bars qua `clock.set_time_alert` hoặc so `ts_event` |
| `cooldown_bars` | int | Khoảng nghỉ không vào lệnh mới sau khi vừa đóng vị thế |
| `atr_frame`, `atr_mult` | str, float | Chỉ báo `AverageTrueRange` của Nautilus trên BarType tương ứng |
| `max_positions` | int | `Coordinator` trong `backend/nautilus/portfolio.py` quản lý giới hạn số vị thế đồng thời của danh mục (không có `PortfolioGuard`) |
| `max_drawdown_limit` | float | Kill switch max drawdown nằm trong `Coordinator` (`backend/nautilus/portfolio.py`) |
| `funding` | - | **Không mô phỏng** (backtest Nautilus không thanh toán funding): provenance `funding_modeled:false` + `warnings`; `unsupported:true`; UI ẩn |
| `liquidation` | - | **Không mô phỏng** thanh lý/ký quỹ: provenance `liquidation_modeled:false` + `warnings`; `unsupported:true` |
| `limit_through_pct` | float | **Không mô phỏng**: provenance `limit_through_modeled:false` + `warnings`; `unsupported:true` |
| `stop_fill` (`extreme`) | str | **Không mô phỏng** giá khớp extreme khi gap: provenance `stop_fill_extreme_modeled:false` + `warnings`; `unsupported:true` |

---

## 2. Danh mục Endpoints & Contract Shape

### A. Studio & Metadata
1. `GET /api/studio/meta`
   - Request: Headers `If-None-Match`
   - Response: `200 OK` (hoặc `304 Not Modified`)
   - Shape:
     ```json
     {
       "version": "sha256_hash",
       "engine": { "name": "nautilus_trader", "version": "1.231.0", "docs_url": "https://nautilustrader.io/docs/" },
       "metrics": { "defs": {}, "groups": [] },
       "frames": ["1m", "5m", "15m", "1h", "4h", "24h"],
       "symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", ...],
       "limits": { "max_symbols": 10, "max_bars": 2000000 }
     }
     ```

2. `GET /api/studio/custom/defaults`
   - Response:
     ```json
     {
       "symbols": ["BTC-USDT-SWAP"],
       "start": "2024-01-01",
       "end": "2024-12-31",
       "train_ratio": 0.7,
       "capital": 10000.0,
       "engine": "nautilus_trader"
     }
     ```

### B. Alpha & Chiến lược
3. `GET /api/studio/strategies`
   - Response: Danh sách chiến lược kèm `params_schema`, `preset`, `frames_allowed`
4. `GET /api/studio/strategies/catalog`
   - Response: Danh mục chiến lược lõi và chiến lược mẫu (KEMA, DCA, Sideway, +50 mẫu)
5. `GET /api/studio/strategies/source/{id}`
   - Response: `{ "id": str, "code": str }`
6. `PUT /api/studio/strategies/source/{id}`
   - Request body: `{ "code": str }`
   - Response: `{ "id": str, "ok": true }`
7. `GET /api/studio/education/samples`
   - Response: Danh sách đúng 50 mẫu chiến lược giáo dục từ `data/alpha/education/samples.json`:
     `[{ "key": str, "name": str, "category": str, "difficulty": str, "summary": str, "code": str }]`
   - Kết quả mẫu: CHỈ từ cache thật. `GET /api/studio/education/samples/{key}/result` → `404 {"code":"NOT_READY"}` cho tới khi job `education_warm` đã chạy mẫu đó (không còn `sample_results.json` / số giả).
8. `GET /api/studio/alphas/catalog`
   - Response:
     ```json
     {
       "sources": [
         {
           "key": "nora",
           "label": "Nora",
           "strategies": [
             {
               "key": str,
               "strategy": str,
               "name": str,
               "kind": str,
               "side": "Long" | "Short" | "Long + Short",
               "idea": str,
               "plain": [str],
               "math": [],
               "stats": [],
               "summary": { "n": int, "ret_pct": float, "mdd_pct": float, "sharpe": float, ... },
               "is_user_alpha": bool
             }
           ]
         }
       ]
     }
     ```
9. `GET /api/studio/alphas/top_agents`
   - Response: Đọc trực tiếp từ file đông kết `data/alpha/research/okx_top10_agents.json`:
     `{ "bots": [...], "n_bots": 10, "generated_at": str, "provenance": {} }`

### C. Jobs & Backtest
10. `POST /api/studio/custom/backtest`
    - Request: `{ "code": str, "symbols": [str], "start": str, "end": str, "capital": float, "position": {} }`
    - Response: `{ "job_id": str, "status": "QUEUED" }` (Chạy trong tiến trình độc lập, không block API worker)
11. `GET /api/studio/book/jobs/{job_id}`
    - Response khi đang chạy: `{ "id": str, "status": "RUNNING", "progress": float }`
    - Response khi hoàn tất:
      ```json
      {
        "id": str,
        "status": "DONE",
        "result": {
          "metrics": { "simulate": {}, "train": {}, "test": {} },
          "series": { "stages": { "all": { "times": [], "equity": [] } } },
          "trades": [],
          "by_symbol": {},
          "yearly": []
        }
      }
      ```
    - Response khi job không tồn tại: HTTP 410 Gone `{ "detail": { "code": "EPHEMERAL_GONE" } }`

---
*Ghi chú*: Hợp đồng này được bảo vệ bằng test hồi quy `test/regression/test_api_contract.py`.
