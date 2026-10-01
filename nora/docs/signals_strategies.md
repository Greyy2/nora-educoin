# Tín hiệu và chiến lược (bước 2)

Luồng: **kernel → tín hiệu → kiểm tra tín hiệu → chiến lược (tín hiệu + quản lý vị thế) → backtest → WFA → Monte Carlo**.

## 1. Kernel (`backend/signals/kernels.py`)

Kernel là một hàm nhỏ, thuần và **causal**: giá trị tại nến t chỉ dùng dữ liệu của các nến ≤ t.
Test `test_kernel_is_causal_prefix_invariant` kiểm mọi kernel bằng cách cắt chuỗi ở nhiều điểm.
Test `test_prefix_check_detects_a_lookahead_kernel` chứng minh chính phép kiểm này bắt được kernel nhìn tương lai.
Trong giai đoạn khởi động kernel trả NaN, và điều kiện nào dùng NaN đều là False.

Tên cột trong AST có dạng `<kernel>_<tham số>`. 23 kernel:

| Nhóm | Kernel |
|---|---|
| Xu hướng | `sma_n`, `ema_n`, `roc_n` |
| Regime | `er_n` (0 = đi ngang, 1 = xu hướng), `adx_n` |
| Dao động | `rsi_n`, `bbz_n` (z-score), `bbm/bbu/bbl_n_k` |
| Biến động | `atr_n`, `natr_n`, `rv_n`, `bbw_n_k`, `bbwp_n_k_m` (phân vị độ rộng → nén), `kcm/kcu/kcl_n_k` |
| Breakout | `dch_n`, `dcl_n` (đỉnh/đáy n nến **trước**, không gồm nến hiện tại) |
| Dòng tiền | `vwap_n`, `vwapdev_n`, `volz_n` |

- **Khung:** 1m, 5m, 15m, 1h, 4h, 24h. Kernel của khung F chỉ được thấy ở nến 1m khi nến F đã đóng.
- **Nến trước:** `{"frame": "15m", "column": "rsi_14", "index": 1}` là RSI của nến 15m trước đó (tối đa 500).
- **1m trên DEX:** kernel 1m chỉ tính trên các phút có giao dịch (nến điền không phải một quan sát).

## 2. Tín hiệu (`backend/alpha/strategy_library.py` → `SIGNALS`)

Mỗi tín hiệu là một cây điều kiện AST. Tám tín hiệu tham khảo từ lối đánh của bot top OKX/Binance
(`okx-report.html`): bắt hồi (5m RSI + Bollinger trong regime đi ngang, 1m z-score sâu), theo xu hướng
(EMA50/200 + ADX + Donchian 15m, hai chiều), theo đà 24h, lướt nhanh VWAP, săn cú lớn sau nén biến động.

## 3. Kiểm tra tín hiệu (`backend/signals/diagnostics.py`)

Trả lời câu hỏi "tín hiệu có mang thông tin về giá tương lai không?" **trước** khi ghép thành chiến lược:

- Vào ở open của phút có giao dịch kế tiếp. Lợi suất đo ở các mốc 15 phút, 1h, 4h, 24h.
- Ở mỗi mốc h chỉ giữ các sự kiện cách nhau ≥ h, để t-stat không bị thổi phồng do chồng lấp.
- Đối chứng là vào ở mọi phút trong cùng khoảng: edge = trung bình sự kiện − trung bình đối chứng.
- Kết luận:
  - **CO_THONG_TIN:** |t| ≥ 3 và cùng dấu ở 60% sự kiện đầu và 40% sau. Ngưỡng là 3 vì kiểm nhiều tín hiệu cùng lúc.
  - **YEU:** 2 ≤ |t| < 3, hoặc không ổn định.
  - **KHONG:** các trường hợp còn lại.
- Cột "sau phí" cho biết edge có đủ bù chi phí khứ hồi theo venue hay không.

Công cụ được kiểm bằng dữ liệu có edge cài sẵn (phải ra CO_THONG_TIN) và random walk (không được ra CO_THONG_TIN).

## 4. Quản lý vị thế (`backend/backtest/execution.py`)

| Tham số | Ý nghĩa |
|---|---|
| `market` | `spot` (không đòn bẩy, không short) hoặc `perp` (đòn bẩy, ký quỹ isolated, thanh lý; dùng giá USDT-M thật `<SYM>@perp` + funding thật; chỉ khi thiếu dữ liệu perp mới dùng giá spot làm proxy, và `price_source` ghi rõ) |
| `order_size_pct` | ký quỹ lệnh đầu = % vốn **hiện tại** |
| `dca_step_pct`, `dca_max_layers`, `dca_size_multiplier` | nhồi khi giá đi ngược X% so với tầng trước; tối đa N tầng; size tầng sau = tầng trước × hệ số |
| `cooldown` | số phút chờ sau khi đóng vị thế mới nhận tín hiệu vào lại (mặc định 0). Tín hiệu là trạng thái nên không chờ thì có thể vào lại vài phút sau SL trên cùng trạng thái cũ; sổ chiến lược dùng 60 |
| `take_profit_rate`, `stop_loss_rate` | % tính từ **giá trung bình** |
| `trailing_stop`, `trailing_activation_pct` | trailing từ đỉnh/đáy có lợi nhất; bật khi lãi ≥ ngưỡng |
| `timeout` | số phút giữ lệnh tối đa |
| `fee_rate` (taker), `maker_fee_rate`, `slippage_rate` | mặc định theo venue: CEX spot 0,10%/0,10% + trượt 0,02%; CEX perp (Binance USDT-M VIP0) taker 0,05% / maker 0,02% + 0,02%; DEX = phí pool thật trong manifest (0,30%) + 0,10% |

**Ngân sách DCA:** với `sizing="margin_pct"`, lệnh đầu + mọi tầng phải vừa `max_capital_usage` (mặc định 100% vốn), gồm phí:
`order_size_pct × (1·(1+L·taker) + Σ m_k·(1+L·maker)) ≤ 100`, m_k = tích luỹ hệ số, L = đòn bẩy. Tầng nào vượt thì bị bỏ âm thầm,
nên `build_params` (qua `dca_budget_check`) **từ chối** cấu hình không vừa (vd. 20% × 5 tầng; 19% thì vừa) và nêu `order_size_pct` lớn nhất còn vừa.
Số tầng bị từ chối vì hết vốn trong lúc chạy ghi ở `dca_layers_rejected`. `optimize_alphas.py` loại tổ hợp không vừa trước khi lấy mẫu (`configs_invalid`).

**Loại phí theo loại lệnh:** vào lệnh ở open, SL, trailing, timeout, tín hiệu thoát = taker (market, có trượt giá);
tầng DCA và chốt lời = maker (limit, không trượt). Mỗi lệnh con ghi `fee_usd` và `liquidity`.

**Sổ vốn chung (`CapitalLedger`):** mọi flow và mọi tầng DCA phải giữ chỗ (ký quỹ + phí) từ cùng một quỹ vốn,
nên nhiều flow cùng lúc không thể dùng quá vốn. Lệnh không đủ vốn trống bị từ chối và được đếm (`rejected_for_capital`).

**Funding (perp):** mỗi mốc funding, vị thế mở trả/nhận `qty × giá × rate` (long trả khi rate > 0), hạch toán ngay vào vốn.
Lãi/lỗ ròng của lệnh = lãi/lỗ giá − mọi phí − funding. Bộ test `test_capital_ledger.py` tính lại độc lập từ danh sách lệnh con.

Giả định trong một nến (bi quan, có test):

- Phía bất lợi xử lý theo đúng thứ tự giá chạm: tầng DCA, SL, trailing, thanh lý. Sau mỗi tầng, giá trung bình, SL và giá thanh lý được tính lại. Hai mức trùng nhau thì ưu tiên thoát.
- Không chốt lời trong nến vừa khớp tầng DCA.
- Khi giá mở cửa đã vượt qua mức (gap), lệnh khớp ở giá mở cửa.
- Vốn dùng chung, khối lượng co giãn theo vốn hiện tại. Vốn ≤ 0 thì ngừng mở lệnh, nên spot không thể lỗ quá 100%.
- Đường vốn là **mark-to-market** kể cả điểm xấu nhất trong nến, nên MDD thấy được **lỗ treo**. Đây chính là thứ bảng xếp hạng OKX không hiển thị.
  Mỗi lệnh còn có `mae_pct` (lỗ treo tối đa trong lệnh), `layers`, `avg_price`, `fees_usd`.

## 5. Chiến lược mẫu (`KERNEL_STRATEGIES`)

`okx_dca_reversion_long`, `okx_dca_reversion_short_perp`, `okx_dca_dense_fast`, `trend_ema_donchian_long`,
`trend_ema_donchian_short_perp`, `momentum_24h_follow`, `scalp_vwap_fast`, `squeeze_breakout_hunt`.

Mọi chiến lược đều có stop-loss cứng và/hoặc timeout, **khác với bot OKX**. Báo cáo OKX cho thấy 21/28 bot
không cắt lỗ, và số tầng DCA tương quan +0,62 với cú lỗ lớn nhất.

## 6. Chạy kiểm tra bước 2

```bash
cd nora
PYTHONPATH=. python scripts/check_signals_strategies.py --workers 4          # 10 tài sản
PYTHONPATH=. python scripts/check_signals_strategies.py --assets BTC,AERO   # một vài tài sản
```

Kết quả được lưu ở `data/_cache/reports/step2_<thời điểm>.json`.
