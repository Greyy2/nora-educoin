# Từ chiến lược tới alpha sẵn sàng testnet

Luồng: **data → tín hiệu + chiến lược → backtest (scan) → WFA → Monte Carlo → holdout → kho alpha → cấu hình testnet**.

## 1. Backtest và scan

- `POST /api/studio/simulate`: một chiến lược trên một tài sản. `market="perp"` tự dùng dữ liệu `<SYM>@perp` và funding.
- `POST /api/studio/scan`: một chiến lược trên nhiều tài sản, chạy nền, có tiến độ, lưu SQLite (`scan_jobs`).
  - Tham số: `strategy_id` (mẫu trong `/samples`) hoặc `flows`; `symbols` (mặc định mọi tài sản hợp thị trường);
    `days`; `position` (ghi đè tham số vị thế); `signal_params`.
  - Mỗi tài sản đều qua quality gate. Tài sản không hợp lệ (vd. DEX + perp) được bỏ qua kèm lý do.
  - Theo dõi bằng `GET /api/studio/scan/{job_id}`; lịch sử ở `GET /api/studio/scan/history`.
- Kết quả tái lập được: cùng dữ liệu (`sha256_1m` trong manifest) và cùng tham số thì cho cùng số.

## 2. Tối ưu trung thực (`scripts/optimize_alphas.py`)

Không gian tối ưu nằm ở `alpha/strategy_library.OPTIMIZATION_SPACES`. Ngưỡng tín hiệu được viết dạng `{"param": ...}` và tối ưu qua khoá `sig.<tên>`.

```
|──────────── dev 80% ─────────────|── holdout 20% ──|
|── dev1: sàng lọc ──|─ dev2: WFA ─|   chấm cuối     |
```

1. **Sàng lọc (dev1):** thử N cấu hình lấy mẫu ngẫu nhiên (seed cố định, ghi lại số cấu hình đã thử). Giữ cấu hình có lãi,
   MDD mark-to-market ≤ 30% và đủ số lệnh; lấy top-8.
2. **WFA (dev2):** fold test đầu tiên bắt đầu đúng tại cuối dev1. Mỗi fold chọn cấu hình tốt nhất trong top-8 trên IS và
   kiểm trên OOS. Gate: lợi nhuận IS ≥ 0, ≥ 50% fold OOS có lãi, đủ lệnh, MDD fold ≤ 30%, lợi nhuận OOS lãi kép ≥ 0.
3. **Monte Carlo** trên lệnh OOS của WFA (block bootstrap 5, 2000 lần): xác suất cháy (MDD ≥ 30%) ≤ 5%.
4. **Holdout (20% cuối, chưa ai chạm):** chạy cấu hình được WFA chọn nhiều nhất. Phải có lãi, MDD ≤ 30%, đủ lệnh.

**ALPHA** = qua cả 4 giai đoạn, và đòn bẩy ≤ 10x (mức rủi ro "vừa phải" đã chốt).
Nếu không có cặp nào đạt thì báo thẳng là không có; không nới gate để có kết quả đẹp.

```bash
cd nora
PYTHONPATH=. python scripts/optimize_alphas.py --n 60 --workers 10          # mọi cặp
PYTHONPATH=. python scripts/optimize_alphas.py --spaces trend_long_perp --assets BTC,ETH
```

## 3. Kiểm độ bền (`scripts/robustness_check.py`)

```bash
PYTHONPATH=. python scripts/robustness_check.py data/_cache/optimize/<thời điểm>/results.json <space_id> <SYM>
```

- **Lân cận tham số:** đổi từng tham số sang mức kề bên. Nếu phần lớn lân cận vẫn lãi ở cả dev2 và holdout thì alpha không nằm trên một "đỉnh nhọn" overfit.
- **Chuyển tài sản:** giữ nguyên tham số, chạy trên các tài sản cùng venue. Kết quả này cho biết edge là chung hay riêng từng tài sản.
- Kết quả lưu ở `robustness_<space>__<SYM>.json` cạnh `results.json`. Bước dựng kho tự gắn nó vào mục `robustness` của alpha.

## 4. Kho alpha và cấu hình testnet

```bash
PYTHONPATH=. python scripts/build_alpha_registry.py data/_cache/optimize/<thời điểm>
```

- `alphas/registry.json`: mỗi alpha gồm template, tham số, AST đã thay tham số, số liệu sàng lọc/WFA/MC/holdout,
  sha256 dữ liệu và commit code.
- `alphas/testnet/<alpha_id>.json`: cấu hình Binance Futures testnet, mô tả đúng hành vi đã mô phỏng:
  - ký quỹ ISOLATED;
  - vào lệnh MARKET ở phút sau tín hiệu;
  - tầng DCA là LIMIT GTX (maker);
  - chốt lời là LIMIT reduce-only; cắt lỗ là STOP_MARKET reduce-only;
  - có kill switch khi drawdown vượt 30%.
  Tick size / step size lấy từ `/fapi/v1/exchangeInfo` khi bot khởi động.

## 5. Test

| File | Kiểm |
|---|---|
| `test_capital_ledger.py` | bất biến vốn ở mọi nến; lãi/lỗ tính lại độc lập từ lệnh con; phí maker/taker; funding |
| `test_optimization_plumbing.py` | tham số tín hiệu, ứng viên WFA, perp/@perp, phí pool, scan đa tài sản + tái lập |
| `test_pipeline_e2e.py` | trọn luồng trên dữ liệu giả lập: thứ tự thời gian, hợp đồng dữ liệu, tái lập, xuất testnet |

## 6. Khớp stop-loss bi quan (`stop_fill`)

Mặc định (`"level"`), SL/trailing khớp đúng mức cộng trượt giá. Giả định này **lạc quan** khi giá giật xuyên qua mức trong một nến.
`stop_fill="extreme"` cho khớp ở giá xấu nhất của nến đó. Mọi alpha nên được báo ở cả hai mức: "level" là cận trên, "extreme" là cận dưới.

Alpha `trend_long_perp__SOL`:

| | WFA-test | Holdout |
|---|---|---|
| level | +36,4% | +14,7% |
| extreme | +28,3% | +12,3% |

## 7. Hướng chiến lược: đã kiểm gì, kết quả ra sao (30/09/2026)

| Hướng | Công cụ | Kết quả |
|---|---|---|
| Lướt nhanh maker 1m–15m (limit vào, limit chốt, SL cứng) | `scripts/research_maker_scalp.py` | **Không có edge.** 9.792 cấu hình × 8 tài sản; gần như tất cả lỗ ở dev. Edge bắt đáy 2–4 bps bị adverse selection của lệnh limit ăn hết. |
| Funding carry (short perp + long spot) | dữ liệu `funding.pkl` | 12–14%/năm trong 2024, còn **1–2%/năm trong 2026**. Chưa tính phí 4 chân và vốn chia hai chân. |
| Trend chung tham số cho 8 tài sản, hai chiều | `scripts/research_trend_portfolio.py` | **Thất bại.** Short trend lỗ ở mọi giai đoạn; long trend chỉ có edge trên SOL (DOGE yếu). |
| Danh mục alpha + mức vốn | `scripts/portfolio_sizing.py` | SOL một mình tốt hơn SOL+DOGE. Hệ số vốn tối đa trong ngân sách rủi ro: **0,5x** (extreme) – **0,75x** (level). |

**Bài học về kiểm chứng.** Bộ quét lối "rải limit" từng cho +10–20 bps/lệnh trên cả 8 tài sản. Phép kiểm random walk
(`tests/test_research_null.py`) cho ra +15 bps, tức edge giả. Có hai nguyên nhân:
1. Chọn trước lệnh "sẽ khớp", một dạng nhìn trước tương lai.
2. SL khớp đúng mức khi giá giật xuyên mức.

Mọi bộ quét mới phải qua phép kiểm null này trước khi tin kết quả.

**Vì sao bot top "lãi khủng".** Chia ROI công bố cho đòn bẩy trung vị thì phần lớn chỉ còn khoảng 2–15% mỗi 90 ngày trên 1x. Phần "khủng" là đòn bẩy 10–30x
cộng lỗ treo không hiển thị. Với alpha SOL:
- hệ số 3x cho lãi trung vị 1 năm ~150%, nhưng P(MDD ≥ 30%) ≈ 99%;
- trong ngân sách đã chốt (≤ 5%), lãi trung vị ~20–40%/năm.
