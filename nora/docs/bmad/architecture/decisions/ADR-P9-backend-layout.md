# ADR-P9 — Tinh gọn kiến trúc backend và dữ liệu

Ngày: 2026-10-07 · Trạng thái: **đã duyệt & hoàn thành** · Nhánh: `fix/pipeline-audit`

## 1. Mục tiêu và luật bất biến

Backend được tái cấu trúc thành kiến trúc phân tầng tinh gọn: **core chỉ còn logic engine thuần**, mỗi thư mục ít file, đặt tên đúng nghĩa; dữ liệu tách rõ "lưu lâu dài" và "tạm thời".

Luật bất biến:
1. **Không mất logic**: chỉ di chuyển và gộp. Sau mỗi bước: golden + kernel parity bit-identical, event/runner parity, venue conformance, live bot, test chéo Nautilus (nautilus_diff S1–S8) không đổi.
2. Mọi số hiển thị đều do module logic tính từ dữ liệu thật (không số tĩnh/giả trong frontend hay file dữ liệu).
3. Chuẩn đúng của engine: một logic engine duy nhất của Nora; chuẩn đối chiếu là ngữ nghĩa backtest của NautilusTrader (`test/scripts/nautilus_diff` S1–S8).

## 2. Cây backend đích

```
backend/
  main.py                    # app FastAPI (giữ nguyên chỗ)
  core/                      # THUẦN logic: không I/O, không import ngoài core
    models.py                # Order, Fill, Position, Account, sự kiện, enum
    params.py                # tham số chiến lược: schema, template, builder, materialize
    indicator.py             # mọi chỉ báo, tham số mở (numba + DSL features/ops)
    signal.py                # bộ dịch tín hiệu mở: AST + DSL Python, snapshot, giải thích
    position_size.py         # sizing, mức SL/TP/DCA/trailing, rủi ro danh mục
    backtest.py              # ENGINE THỰC THI DUY NHẤT (numba): nến/tick, CEX/DEX, khớp lệnh, danh mục; chạy cả lô (backtest) hoặc từng nến (paper/live)
  alpha/                     # chiến lược do người dùng/AI viết theo NautilusTrader: HỢP ĐỒNG cố định + bộ chuyển đổi -> MỘT mô hình chuẩn (IR ở core/signal) -> MỘT engine
    contract.py              # Strategy Contract: vòng đời (on_start/on_bar/on_stop), danh mục primitive cho phép, lỗi/giới hạn mã; sai hợp đồng -> ADAPT hoặc REJECT
    compile.py               # bộ chuyển đổi: Python DSL / chiến lược dạng hàm / JSON / mẫu / AI -> IR; biên dịch module chiến lược + cây điều kiện; nạp file chiến lược
  metrics/
    metrics.py               # bộ chỉ số đầy đủ, một công thức chuẩn Nora (đúng theo NautilusTrader), năm = 365 ngày
    trades.py                # bảng lệnh, thống kê theo lệnh/chiến lược, đối soát sàn ↔ sim, chẩn đoán từng lần chạy (diagnose_run)
    charts.py                # chuỗi cho biểu đồ: vốn, sụt giảm, NAV ngày, dashboard, insight, feeds
  regime/regime.py           # nhận diện trạng thái thị trường + học bảng regime
  wfa/wfa.py                 # walk-forward + kiểm chứng chéo / ổn định tham số (PBO-CSCV, lân cận, fold_stats)
  carlo/carlo.py             # Monte Carlo + ý nghĩa thống kê dưới stress (DSR, N hiệu dụng)
  optimize/
    search/   generate.py, evaluate.py          # sinh alpha, chạy hàng loạt, dữ liệu dùng chung
    funnel/   stages.py, storage.py             # phễu S0 → FINAL
    book/     build.py, registry.py             # dựng sổ, preset, kho alpha, alpha người dùng, testnet
    process/  process.py, tasks.py, workers.py  # hàng đợi/huỷ/khôi phục; mọi run_job; đa tiến trình + RAM
  crawl/
    cex.py                   # nến + funding OKX/Binance, chung một khung
    dex.py                   # tick swap on-chain + lưu tick
    store.py                 # layout dữ liệu, đọc/ghi, resample, quality gate, mmap dùng chung, LRU
  live/                      # chia theo MÔI TRƯỜNG chạy: chỉ cấu hình chạy ở đâu, chạy thế nào theo thời gian thực
    live.py                  # vòng chạy thời gian thực dùng chung + cổng sàn OKX + hồ sơ tiền thật (confirm_live)
    testnet.py               # hồ sơ OKX demo (endpoint/cờ demo, khoá demo)
    paper.py                 # hồ sơ paper: nến thật, khớp lệnh mô phỏng trong core
  routes/                    # router FastAPI (5 nhóm router chuẩn theo package)
ops/                         # NGOÀI backend: run_limited.sh, install_user_units.sh, deploy_nginx.sh, systemd/, nginx/
```

**Luật phụ thuộc:**
`core ← {metrics, regime, wfa, carlo} ← optimize ← {live, routes}`; `crawl` chỉ được gọi từ `optimize`, `live`, `routes`;
`core` không import gì ngoài `core`; trong core theo thứ tự `models ← params ← indicator ← signal ← position_size ← backtest`. Core không đọc file: dữ liệu và cấu hình được nạp ở tầng trên rồi truyền vào.

## 3. Cấu trúc dữ liệu (`nora/data/`)

```
data/
  market/
    okx/      cex/<SYM>/{1m..24h}.pkl, perp/, funding.pkl, manifest.json      dex/<chain>/<pool>/…, ticks.parquet
    binance/  cex/…
  alpha/
    strategies/  định nghĩa chiến lược hệ thống        user/<id>.json  alpha người dùng
    education/samples.json  presets.json  registry.json  book.json  explore/  testnet/
    funnel/<run>/                                     book/<run>/
  backtest/<id>/   params + kết quả                  backtest/education/
  wfa/<id>/                                          carlo/<id>/
  live/<venue_mode>/  trạng thái bot, sự kiện (lưu lâu dài)
  cache/                                              # TẠM THỜI, chỉ 2 thư mục
    process/<id>/  params, trạng thái, tiến độ, log (cả log RAM), checkpoint, file tạm crawl
    shared/        mmap chỉ báo dùng chung + cache quality gate
```

**Vòng đời cache:**
- Đang chạy: ghi vào `data/cache/process/<id>/`.
- Xong: kết quả + params chuyển sang nơi lưu lâu dài (`data/backtest|wfa|carlo|alpha/…`).
- Dọn ngay `data/cache/process/<id>/`. Cache CHỈ chứa tiến trình đang chạy.
- Ngoại lệ: backtest tạm của người học (Education) giữ trong cache tối đa 24h, khi bấm Lưu mới chuyển thành `data/alpha/user/<id>.json`.
