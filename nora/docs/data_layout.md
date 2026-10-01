# Dữ liệu thị trường của Nora

Dữ liệu thị trường (giá OHLCV, khối lượng và swap DEX nếu có) là **đầu vào** cho mọi bước
phía sau: **Backtest → WFA → Monte Carlo → Research**. Kết quả chỉ đáng tin khi dữ liệu thật,
đúng thời gian và có nguồn gốc rõ ràng. Tài liệu này mô tả cách dữ liệu được sắp xếp và vì sao.

Toàn bộ logic đường dẫn nằm trong một module duy nhất: `backend/db/data_layout.py`.

## Cấu trúc thư mục

```
nora/data/
├── cex/                     sàn tập trung (Binance)
│   └── <SYM>/               BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX  — spot
│       ├── 1m.pkl           NGUỒN DUY NHẤT (nến 1m chính thức của sàn)
│       ├── 5m.pkl 15m.pkl 1h.pkl 4h.pkl 24h.pkl   resample từ 1m (core/resampler.py)
│       ├── manifest.json
│       └── perp/            <SYM>@perp — Binance USDT-M perpetual, 3 năm
│           ├── 1m.pkl ...   nến perp (data.binance.vision/futures/um, có checksum)
│           ├── funding.pkl  lịch sử funding (8h/lần) — engine trả/nhận funding khi giữ lệnh
│           └── manifest.json
├── dex/                     sàn phi tập trung (AMM pool on-chain)
│   └── <SYM>/               AERO (Base), VVV (Base)
│       ├── 1m.pkl ...       nến 1m của pool; phút không có swap -> nến điền is_filled=1
│       ├── ticks.parquet    (tuỳ chọn) swap thật, khai báo trong manifest["ticks"]
│       └── manifest.json
├── _meta/                   danh sách target crawl (không phải tài sản)
└── _cache/                  cache tính toán (research), xoá được bất cứ lúc nào
```

- Thư mục bắt đầu bằng `.` hoặc `_` không phải tài sản.
- Ký hiệu tài sản: `BTC` nếu tên là duy nhất; `cex:UNI` / `dex:UNI` khi cùng tên có ở cả hai loại sàn
  (không có tiền tố thì hệ thống báo lỗi, không tự đoán).
- Instrument perp: `BTC@perp` = `cex/BTC/perp`. Chiến lược `market="perp"` tự dùng dữ liệu `@perp` (giá perp + funding);
  không có dữ liệu perp thì chạy trên giá spot và kết quả ghi rõ `price_source = spot_proxy`, `funding_modeled = false`.
  Ký hiệu có `@perp` không bao giờ bị phân giải nhầm sang thư mục spot.
- Funding trung bình 3 năm (người giữ long trả): BTC ≈ 7,4%/năm, ETH 7,6%, SOL 5,4%, XRP 7,2%, DOGE 8,2%, ADA 7,5%,
  AVAX 5,2%, BNB −1,0%.
- Phí pool DEX đã xác minh on-chain (Aerodrome V2 `PoolFactory.getFee`): AERO/USDC và VVV/WETH đều **0,30%**
  (`manifest.pool_fee_rate`).
- `nora/data_staging/`: nơi crawler ghi trước. `scripts/promote_staging.py` chỉ chuyển sang
  `data/<venue>/` những tài sản qua quality gate.
- `nora/test/data_legacy/`: bộ dữ liệu cũ (tick tổng hợp từ nến 15m, không có manifest).
  Chỉ giữ để tham chiếu, **không dùng cho backtest**.

## Vì sao tách CEX / DEX

| | CEX | DEX |
|---|---|---|
| Bản chất dữ liệu | Sổ lệnh, kline chính thức của sàn | Swap on-chain vào AMM pool |
| Nguồn hiện tại | data.binance.vision (ZIP tháng/ngày + SHA-256) và REST cho phần mới nhất | GeckoTerminal OHLCV 1m (API miễn phí: **tối đa 180 ngày**) |
| Lịch sử | 3 năm | 179 ngày |
| Phút không giao dịch | ~0% | 13–47% (AERO 46,5%) |
| Đường giá cho Research (DC) | close 1m | tick thật nếu phủ ≥ 90% khoảng 1m, ngược lại close 1m bỏ nến điền |
| Khớp lệnh trong engine | open nến 1m kế tiếp | open của phút **có giao dịch** kế tiếp (bỏ qua nến điền) |
| Mô hình phí khứ hồi | taker 0,1%×2 + trượt 0,02%×2 ≈ **24 bps** | phí pool 0,1%×2 + trượt ước tính×2 + adverse selection 0,05% |
| Bước nhảy > 50%/phút | WARNING (dữ liệu đã kiểm checksum = sự kiện thật, vd. 2025-10-10) | BLOCKED (có thể là lỗi dữ liệu) |

**Tick DEX:** API miễn phí của GeckoTerminal chỉ trả khoảng 300 giao dịch trong 24h gần nhất,
không có lịch sử. `crawler/crawl_dex_ticks.py` chạy định kỳ để tích luỹ tick thật dần dần. Chỉ khi
`manifest["ticks"]` khai báo `synthetic: false` và tick phủ đủ khoảng thời gian thì Research mới
dùng tick thay cho nến 1m. **Không bao giờ** sinh tick giả từ nến.

## manifest.json

Mỗi tài sản có một file manifest. Quality gate đọc manifest để quyết định cho chạy hay chặn.

| Trường | Ý nghĩa |
|---|---|
| `venue`, `exchange`, `network`, `market_symbol`, `pool_address` | nguồn gốc |
| `source`, `synthetic` | `synthetic: true` thì bị chặn |
| `crawl_ok`, `crawl_issues`, `checksums_verified` | crawl lỗi hoặc thiếu tháng thì bị chặn |
| `start_ts`, `end_ts`, `coverage_days`, `coverage_ratio` | dưới 30 ngày thì NEEDS_MORE_DATA |
| `filled_ratio_1m` | trên 60% thì bị chặn |
| `sha256_1m` | lệch với `1m.pkl` thì bị chặn |
| `ticks` | khai báo tick thật (DEX) |

## Quality gate (`research/data_quality_gate.py`)

Gate được gọi trước Studio `/simulate`, trước WFA và trước Research. Các trường hợp bị chặn:
thiếu manifest, `synthetic`, `crawl_ok=false`, sha256 lệch, trùng timestamp, `filled_ratio > 60%`,
thiếu 4h, hoặc resample 1m không khớp với các khung đã lưu (sai số tương đối 1e-9).

## Cập nhật dữ liệu

```bash
cd nora
# CEX spot: 3 năm tới hiện tại (file ZIP được cache ở /home/ubuntu/norabt/data/cache/binance)
PYTHONPATH=. python -m backend.core.data.crawler.crawl_binance_klines --symbols BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX \
    --years 3 --output-dir data_staging
# CEX perp (USDT-M) + funding -> <out>/<SYM>/perp ; chạy gate rồi chuyển vào data/cex/<SYM>/perp
PYTHONPATH=. python -m backend.core.data.crawler.crawl_binance_klines --market um --symbols BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX \
    --years 3 --output-dir data_staging_perp
# DEX: tối đa 179 ngày (giới hạn API miễn phí)
PYTHONPATH=. python -m backend.core.data.crawler.crawl_geckoterminal_full_dataset --targets-file data/_meta/dex_targets.json \
    --output-dir data_staging --lookback-days 179 --limit 1000 --page-delay-sec 3 --minute-max-pages 300
# Kiểm gate + chuyển vào data/<venue>/
PYTHONPATH=. python scripts/promote_staging.py            # xem trước
PYTHONPATH=. python scripts/promote_staging.py --apply
```
