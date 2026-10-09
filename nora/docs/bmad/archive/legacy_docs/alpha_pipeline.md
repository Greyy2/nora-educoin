# Từ chiến lược tới alpha sẵn sàng testnet

Luồng: **data → tín hiệu + chiến lược → backtest (scan) → WFA → Monte Carlo → holdout → kho alpha → cấu hình testnet**.

## 1. Backtest

- `POST /api/studio/book/backtest` (job `book_backtest` → `core/backtest/run.py`): một hoặc nhiều chiến lược của sổ trên các tài sản perp,
  chế độ Cơ bản (preset khoá) / Nâng cao (sửa từng tham số). Mỗi tài sản đều qua quality gate.
- Kết quả tái lập được: cùng dữ liệu (`sha256_1m` trong manifest) và cùng tham số thì cho cùng số.

## 2–3. Tối ưu và kiểm duyệt alpha: phễu S0–FINAL

Đường tối ưu đơn tài sản cũ (`optimize_alphas`, `robustness_check`, `build_alpha_registry`) đã bỏ ngày 02/10/2026; thay bằng **phễu**
(`docs/funnel_contract.md`, `POST /api/studio/funnel/runs` → job `funnel_run` → `optimize/funnel/run.py`):
sinh alpha → S1 backtest dev1 → S2 chống ăn may (DSR, PBO, lân cận tham số) → S3 WFA dev2 → S4 Monte Carlo 10.000 kịch bản + kịch bản cực xấu →
S5 khối lượng sống sót → S6 holdout (một lần) → FINAL → `POST /api/studio/funnel/promote` đưa vào kho alpha.
Không nới gate để có kết quả đẹp: không alpha nào qua thì báo thẳng là không có.

## 4. Kho alpha và cấu hình testnet

- `data/alphas/registry.json`: mỗi alpha gồm template, tham số, AST đã thay tham số, số liệu sàng lọc/WFA/MC/holdout,
  sha256 dữ liệu và commit code.
- `data/alphas/testnet/<alpha_id>.json`: cấu hình Binance Futures testnet, mô tả đúng hành vi đã mô phỏng:
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
| Lướt nhanh maker 1m–15m (limit vào, limit chốt, SL cứng) | `backend/core/research/research_maker_scalp.py` | **Không có edge.** 9.792 cấu hình × 8 tài sản; gần như tất cả lỗ ở dev. Edge bắt đáy 2–4 bps bị adverse selection của lệnh limit ăn hết. |
| Funding carry (short perp + long spot) | dữ liệu `funding.pkl` | 12–14%/năm trong 2024, còn **1–2%/năm trong 2026**. Chưa tính phí 4 chân và vốn chia hai chân. |
| Trend chung tham số cho 8 tài sản, hai chiều | `backend/core/research/research_trend_portfolio.py` | **Thất bại.** Short trend lỗ ở mọi giai đoạn; long trend chỉ có edge trên SOL (DOGE yếu). |
| Danh mục alpha + mức vốn | `backend/optimize/portfolio_sizing.py` | SOL một mình tốt hơn SOL+DOGE. Hệ số vốn tối đa trong ngân sách rủi ro: **0,5x** (extreme) – **0,75x** (level). |

**Bài học về kiểm chứng.** Bộ quét lối "rải limit" từng cho +10–20 bps/lệnh trên cả 8 tài sản. Phép kiểm random walk
(`test/test_research_null.py`) cho ra +15 bps, tức edge giả. Có hai nguyên nhân:
1. Chọn trước lệnh "sẽ khớp", một dạng nhìn trước tương lai.
2. SL khớp đúng mức khi giá giật xuyên mức.

Mọi bộ quét mới phải qua phép kiểm null này trước khi tin kết quả.

**Vì sao bot top "lãi khủng".** Chia ROI công bố cho đòn bẩy trung vị thì phần lớn chỉ còn khoảng 2–15% mỗi 90 ngày trên 1x. Phần "khủng" là đòn bẩy 10–30x
cộng lỗ treo không hiển thị. Với alpha SOL:
- hệ số 3x cho lãi trung vị 1 năm ~150%, nhưng P(MDD ≥ 30%) ≈ 99%;
- trong ngân sách đã chốt (≤ 5%), lãi trung vị ~20–40%/năm.

## 8. WFA danh mục + Monte Carlo ngày cho sổ chiến lược (`backend/wfa/run.py`)

Sổ chiến lược (nhiều tài sản, MỘT sổ vốn) chỉ có dev1/dev2/holdout và bootstrap. `wfa/run.py` bổ sung WFA trượt:

- Mỗi fold: **IS** chọn lại cấu hình của từng chiến lược (top-K ứng viên, điểm = lãi / max(MDD,1), kill switch tắt, SL "level");
  **OOS** chạy CẢ sổ chung vốn bằng các cấu hình đã chọn (kill switch bật, SL "level" và "extreme"). Train 120 ngày, test 30 ngày, OOS không chồng.
- Nối lợi suất ngày MTM của OOS (extreme, cơ sở bi quan) rồi **Monte Carlo ngày** (`run_monte_carlo_daily`, block 5 ngày, 1 năm): khác Monte Carlo
  theo lệnh vì đường vốn ngày đã gồm lỗ chưa chốt.
- Gate (hằng số đầu `backend/wfa/portfolio_wfa.py`): ≥ 5 fold, lãi IS trung bình ≥ 0, ≥ 60% fold OOS có lãi, MDD tệ nhất một fold ≤ 30%,
  lãi kép OOS ≥ 0, P(MDD ≥ 30% trong 1 năm) ≤ 5%.
- Lãi IS của một fold = trung bình lãi IS (chạy riêng từng chiến lược) của các cấu hình đã chọn.

```bash
curl -X POST localhost:18010/api/studio/book/wfa -H 'content-type: application/json' -d '{"mode":"advanced","report_dir":"<thời điểm>","include_rejected":false}'
curl -X POST localhost:18010/api/studio/book/wfa -H 'content-type: application/json' -d '{"mode":"advanced","candidates":["trend_long","reversion_short"],"n":3}'
```
Kết quả: `<data>/_cache/book_wfa/<thời điểm>/report.json`.

## 9. API sổ chiến lược: job nền (`/api/studio/book`)

API có trần RAM riêng (3G) nên KHÔNG chạy backtest/WFA danh mục trong tiến trình. Mỗi job là một tiến trình con
`ops/run_limited.sh -- -m backend.<gói>.<lệnh> ...` (scope riêng trong `nora.slice`, xếp hàng tuần tự bằng flock, worker tự chia);
API chỉ khởi chạy, theo dõi và đọc kết quả (`backend/api/jobs/batch.py`, router `backend/api/routers/book.py`).

| Endpoint | Việc |
|---|---|
| `GET /api/studio/book/` | `data/alphas/book.json` (status, chiến lược + tham số + tóm tắt bằng chứng), tóm tắt báo cáo `book_wfa` mới nhất, danh mục ứng viên (id, family, side, mô tả, không gian tham số) |
| `POST /backtest` `{strategies?, symbols?, start, end, risk_per_trade_pct?, stop_fill?}` | `backend/core/backtest/run_book_backtest.py`; bỏ `strategies` = dùng `data/alphas/book.json`; tham số thiếu = mức giữa của không gian |
| `POST /wfa` `{report_dir? \| candidates + n \| strategies, start?, end?, train_days?, test_days?, step_days?, sims?}` | `backend/wfa/run.py` |
| `POST /build` `{only?, n?}` | `backend/optimize/book.py` (ghi vào thư mục job; xuất bản sang `data/alphas/` qua `/book/publish`) |
| `GET /jobs`, `GET /jobs/{job_id}` | danh sách / trạng thái + 40 dòng log cuối + `result` khi xong |

Mô hình job: mỗi job có thư mục `<data>/_cache/api_jobs/<job_id>/` gồm `job.json` (loại, đối số, pid, mốc thời gian, mã thoát),
`out.log` (stdout+stderr) và `result.json` (báo cáo cuối; script ghi khi có env `NORA_JOB_DIR`). Trạng thái:
`queued` (log chỉ có dòng "đang chờ job khác" của run_limited) → `running` → `done` | `failed`. Trạng thái sống sót qua khởi động lại API
(đọc lại từ pid / dòng `exit N` cuối log / `result.json`). Chỉ có danh sách trắng loại job + cờ; đối số được kiểm (ngày, tài sản trong vũ trụ,
số trong khoảng), không dùng shell; tối đa 8 job đang chạy/chờ (429). `POST /backtest` trả `result.trade_list` (từng lệnh) và `equity_curve` (≤ 2000 điểm),
cùng các số đo của `portfolio_metrics`.
