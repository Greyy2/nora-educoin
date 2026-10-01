# 03. ĐẶC TẢ GIAO THỨC API & CẤU TRÚC DỮ LIỆU (API & DATA CONTRACTS)

Tài liệu này quy định chi tiết các hợp đồng giao tiếp dữ liệu (Data Contracts) giữa tầng Backend định lượng và Giao diện Web / Client ngoài. Mọi thay đổi về schema đều phải cập nhật tại đây.

---

## 1. Cấu Trúc Dữ Liệu Tick Nguyên Bản (Raw Tick Data Contract)

Dữ liệu đầu vào của Nora là chuỗi giao dịch (swaps/trades) khớp trên DEX, **tuyệt đối không bị gộp nến**.

```json
{
  "timestamp": 1788536025000,          // Unix millisecond (Causal Time)
  "price": 6.21845322,                 // Giá khớp thực tế
  "volume_token": 5240.12,             // Số lượng token giao dịch
  "volume_usd": 32585.40,              // Giá trị quy đổi USD
  "side": "buy",                       // "buy" (Taker mua) | "sell" (Taker bán)
  "pool_address": "0x0392b1...",       // Địa chỉ Pool Uniswap/Aerodrome
  "tx_hash": "0x8f3c1a..."             // Hash giao dịch trên blockchain
}
```

---

## 2. Đặc Tả REST API Endpoints (Port 18010)

### 2.1. Quét Vũ Trụ Thị Trường (DEX Universe Scan)
- **Endpoint**: `GET /api/research/markets/scan`
- **Query Parameters**:
  - `timeframe` *(string, default: "1h")*: `"15m"` | `"1h"` | `"4h"`
  - `symbols` *(string, optional)*: Danh sách lọc coin phân tách bằng dấu phẩy (vd: `ZEN,SOL,MORPHO`)
  - `force_refresh` *(bool, default: false)*: `true` ép quét lại toàn bộ, `false` nạp trực tiếp cache disk (<15ms).

#### Cấu Trúc Response:
```json
{
  "scanned_at": 1788840495,
  "timeframe": "1h",
  "total_analyzed": 50,
  "summary": {
    "can_trade": 0,
    "research_ready": 34,
    "narrow_conditions": 14,
    "do_not_trade": 0,
    "needs_more_data": 2,
    "pass_rate_pct": 68.0,
    "median_health": 83.7
  },
  "rows": [
    {
      "symbol": "ZEN",
      "market_snapshot": {
        "price": 6.21845,
        "change_24h_pct": 10.41,
        "liquidity_usd": 2192744.89,
        "volume_24h_usd": 4059523.08,
        "sparkline": [5.97, 5.85, ..., 6.21]
      },
      "classification": "NARROW_CONDITIONS",
      "market_health_score": 87.7,
      "tradeability_score": 78.4,
      "best_theta": 0.02,
      "best_theta_pct": "2.0%",
      "current_regime": "RANGE_CHOP_REGIME",
      "regime_name": "Đi Ngang / Nhiễu (Range Chop)",
      "recommended_playbook": "DC_OVERSHOOT_FADE",
      "playbook_title": "Đánh Chặn Sóng Rướn Hụt Hơi",
      "falsified": false,
      "falsification_status": "SURVIVED_FRICTION_HURDLE",
      "net_expectancy_bps": 79.0,
      "gross_expectancy_bps": 144.0,
      "friction_hurdle_bps": 65.0
    }
  ]
}
```

---

### 2.2. Chi Tiết Vi Cấu Trúc Tài Sản (Asset Research Drilldown)
- **Endpoint**: `GET /api/research/markets/{symbol}/analysis`
- **Path Parameter**: `symbol` (vd: `ZEN`)
- **Query Parameter**: `timeframe` (vd: `1h`)

#### Nội Dung Trả Về Bổ Sung:
- `behavior_event_profile`:
  - `phase`: Trạng thái bước sóng hiện tại (`BOUNCE_AFTER_PULLBACK`, `OD_UNITY_BAND`...)
  - `pullback_over_range`: Tỷ lệ hồi quy trên biên độ 24h
  - `dc_unity_band`: Vùng giá chuyển pha $[0.20R, 0.32R]$
  - `lambda_dc_daily`: Tần suất xuất hiện biến cố DC trung bình mỗi ngày
  - `od_mean`: Giá trị trung bình Overshoot Deficit.
- `friction_hurdle_breakdown`: Bóc tách chi phí ma sát 4 tầng (Zero ➔ Baseline ➔ Conservative ➔ Stress).

---

### 2.3. Lịch Sử Biến Động Tick (List Trade Causal Trajectory)
- **Endpoint**: `GET /api/research/markets/{symbol}/trades`
- **Yêu cầu tuân thủ**: Trả về trực tiếp mảng các điểm giá và thời gian của từng tick giao dịch, **không gom cụm thành nến OHLC**.
- **Mục đích**: Vẽ đồ thị đường liên tục (Continuous Price Trajectory) trên giao diện soi lệnh của Asset Detail.
