# ADR-P9 — Tinh gọn kiến trúc backend và dữ liệu

Ngày: 2026-10-07 · Trạng thái: **đề xuất, chờ review chéo (norabt-99 kiến trúc ↔ norabt-e2 alpha ↔ backtest analyst)** · Nhánh: `fix/pipeline-audit`

## 1. Mục tiêu và luật bất biến

Backend hiện có 153 file / ~29.000 dòng, logic trùng lặp, core import ngược lên optimize/live/api, tên trùng nghĩa khác nhau.
Mục tiêu: **core chỉ còn logic engine thuần**, mỗi thư mục ít file, đặt tên đúng nghĩa; dữ liệu tách rõ "lưu lâu dài" và "tạm thời".

Luật bất biến khi chuyển:
1. **Không mất logic**: chỉ di chuyển và gộp (không viết lại). Sau mỗi bước: golden + kernel parity bit-identical, event/runner parity, venue conformance,
   live bot, test chéo Nautilus (nautilus_diff S1–S8) không đổi, và cổng của phiên alpha (test_pydsl_*, test_custom_backtest, test_xno_parity,
   test_diagnostics_*, test_edu_*, test_user_alphas, test_strategy_doc, lint_edu_samples).
2. **Review chéo**: trước mỗi commit gửi bảng ánh xạ cũ → mới + danh sách file + kết quả cổng cho phiên kia; chỉ commit khi có OK.
3. **Tương thích ngược** trong lúc chuyển: shim tái xuất ở đường dẫn cũ (job cũ lưu tên module trong `batch.KINDS`; pickle `paper.pkl` / `unified.pkl`
   lưu tên lớp; worker pool pickle tên hàm). Gỡ shim ở bước cuối.
4. Mọi số hiển thị đều do module logic tính từ dữ liệu thật (không số tĩnh/giả trong frontend hay file dữ liệu).

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
  metrics/
    metrics.py               # bộ chỉ số đầy đủ, một công thức (khớp xnoquant + Nautilus), tham số periods_per_year
    trades.py                # bảng lệnh, thống kê theo lệnh/chiến lược, đối soát sàn ↔ sim
    charts.py                # chuỗi cho biểu đồ: vốn, sụt giảm, NAV ngày, dashboard
  regime/regime.py           # nhận diện trạng thái thị trường + học bảng regime
  wfa/wfa.py                 # walk-forward
  carlo/carlo.py             # Monte Carlo
  verdict/verdict.py         # kết luận chống ăn may: DSR, PBO, lân cận, chẩn đoán, insight
  optimize/
    search/   generate.py, evaluate.py          # sinh alpha, chạy hàng loạt, dữ liệu dùng chung
    funnel/   stages.py, storage.py             # phễu S0 → FINAL
    book/     build.py, registry.py             # dựng sổ, preset, kho alpha, alpha người dùng, testnet
    process/  process.py, tasks.py, workers.py  # hàng đợi/huỷ/khôi phục; mọi run_job; đa tiến trình + RAM
  crawl/
    cex.py                   # nến + funding OKX/Binance, chung một khung
    dex.py                   # tick swap on-chain + lưu tick
    store.py                 # layout dữ liệu, đọc/ghi, resample, quality gate, mmap dùng chung, LRU
  live/
    bot.py                   # vòng chạy thật: chỉ engine unified (bỏ legacy sau khi demo ổn định)
    okx.py                   # cổng sàn OKX: REST, ký, bộ lọc lot/tick, OkxVenue, khoá
  routes/                    # (← api/) router + kiểm tham số job + chế độ Cơ bản/Nâng cao
```

**Một engine thực thi duy nhất (người dùng chốt 2026-10-07).** Không có hai bản (kernel numba + bản Python sự kiện) giữ khớp bằng parity.
`core/backtest.py` là engine duy nhất cho backtest, paper và live; tốc độ là thuộc tính của engine, tối ưu thêm thuộc `optimize/`.
- Backtest: chạy cả lô nến như hiện nay.
- Paper/live: gọi cùng engine TỪNG NẾN với trạng thái giữ trong mảng (cơ chế pack/writeback đã có). Engine sinh lệnh (vào/ra/SL/TP/DCA/trailing);
  paper khớp ngay trong engine; live gửi lệnh qua `live/okx.py` (OkxVenue chỉ còn là cổng I/O) và nạp fill của sàn ngược vào trạng thái engine.
- Gỡ bản Python thứ hai: `core/execute/{tracker,manager,sim_venue,runner}` (P9.4b). `test/reference_engine.py` giữ trong test làm oracle.

**Luật phụ thuộc** (test tự động chặn vi phạm, ban đầu báo cáo, sau bắt buộc):
`core ← {metrics, regime, wfa, carlo, verdict} ← optimize ← {live, routes}`; `crawl` chỉ được gọi từ `optimize`, `live`, `routes`;
`core` không import gì ngoài `core`; trong core theo thứ tự `models ← params ← indicator ← signal ← position_size ← backtest`
(file trước không import file sau; ví dụ `signal.py` không được import `backtest.py`). Core không đọc file: dữ liệu và cấu hình được nạp ở tầng trên rồi truyền vào.

## 3. Ánh xạ file cũ → mới

| Đích | Nguồn |
|---|---|
| core/models.py | core/execute/{models,events,account,ledger} |
| core/params.py | core/params/{schema,template,builder}, core/strategy/book.py (materialize, BASE_POSITION), hằng số profile của pydsl/profiles (XNO_FEE, NORA_DEFAULTS, XNO_POSITION) |
| core/indicator.py | core/signals/kernels, core/strategy/pydsl/{features,ops} |
| core/signal.py | core/signals/{evaluator,snapshot,diagnostics}, core/strategy/pydsl/{spec,parser,program,errors,explain} |
| core/position_size.py | core/execute/{policy,risk} |
| core/backtest.py | core/backtest/{engine,portfolio,dex,kernel}, core/execute/{venue,amm} (bước P9.4a chuyển nguyên; P9.4b gỡ tracker/manager/sim_venue/runner), live/paper, core/strategy/pydsl/profiles (build_plan; tỉ trọng rổ nhận qua tham số, không đọc file) |
| metrics/metrics.py | core/metrics/{returns,portfolio,xno} — xno gộp vào một công thức, xoá file |
| metrics/trades.py | core/metrics/trades, live/compare |
| metrics/charts.py | core/analytics/{dashboard,signal_explain}; analytics/feeds.py (không ai dùng) → xoá |
| regime/regime.py | core/regime/{classifier,learn} |
| wfa/wfa.py | wfa/walk_forward |
| carlo/carlo.py | carlo/monte_carlo |
| verdict/verdict.py | optimize/funnel/antiluck, core/metrics/diagnose, phần tính thuần của core/metrics/diagnose_inputs (benchmark, regime, exits, exposure, binding — nhận mảng), core/analytics/insights |
| optimize/search/generate.py | optimize/funnel/generate |
| optimize/search/evaluate.py | optimize/funnel/evaluate, optimize/shared |
| optimize/funnel/stages.py | optimize/funnel/{orchestrator,gates,sizing,stats,publish,promote,recompute,run} |
| optimize/funnel/storage.py | optimize/funnel/storage, optimize/store |
| optimize/book/build.py | optimize/book, core/params/presets |
| optimize/book/registry.py | optimize/{registry,revalidate}, core/analytics/{user_alphas,strategy_doc} |
| optimize/process/process.py | api/jobs/runner, phần hàng đợi/chạy/trạng thái của api/jobs/batch, utils/jobs |
| optimize/process/tasks.py | mọi `run_job`: core/backtest/{run,custom_run,tick_run,edu_precompute}, wfa/run, core/regime/report, core/data/promote; phần NẠP dữ liệu của core/metrics/diagnose_inputs; nạp `data/alpha/universes/*.json` rồi truyền vào build_plan |
| optimize/process/workers.py | utils/{parallel,memwatch} |
| crawl/cex.py | core/data/{crawler,okx_crawler} |
| crawl/dex.py | core/data/tick_crawler, db/tick_storage |
| crawl/store.py | db/{data_layout,local_pkl}, core/data/{loader,resampler,quality_gate,shared}, utils/{lru,jsonsafe} |
| live/bot.py | live/{bot,unified,signals} |
| live/okx.py | live/{okx,okx_venue,exchange,secrets} |
| routes/*.py | api/routers/*; routes/modes.py ← api/modes + core/params/modes; routes/jobs.py ← phần kiểm tham số của api/jobs/batch |
| data/alpha/strategies/*.json | định nghĩa cứng trong core/strategy/{library,book}.py (SIGNALS, KERNEL_STRATEGIES, CANDIDATES) |
| data/alpha/universes/top10_cap.json | core/strategy/pydsl/weights.py (nạp ở optimize, không nạp trong core) |
| data/alpha/education/samples.json | mẫu Education đang nằm ở frontend JS + data/education/samples.json — thành nguồn gốc ở backend, phục vụ qua API |
| test/scripts/ | core/analytics/top_agents (nghiên cứu) |

`*` tracker.py chỉ còn tới P6.9 (nghỉ hưu sau khi demo đạt dung sai).

Kích thước ước tính: core/backtest.py ~3.600 dòng (một file theo yêu cầu), core/signal.py ~2.400 dòng.

## 4. Dữ liệu (`nora/data/`)

```
data/
  market/
    okx/      cex/<SYM>/{1m..24h}.pkl, perp/, funding.pkl, manifest.json      dex/<chain>/<pool>/…, ticks.parquet
    binance/  cex/…   cex_ref/  (← binance_hist: TOP10 spot 2019-10 → 2025-01, chỉ để đối chiếu)
    _meta/
  alpha/
    strategies/  định nghĩa chiến lược hệ thống        user/<id>.json  alpha người dùng (code + program_hash + config + kết quả + bằng chứng)
    universes/   education/samples.json  presets.json  registry.json  book.json  explore/  testnet/
    funnel/<run>/  (← _cache/funnel)                  book/<run>/ (← _cache/book)
  backtest/<id>/   params + kết quả                  backtest/education/  (← data/education/results, sinh lại được)
  wfa/<id>/        (← _cache/book_wfa)               carlo/<id>/
  live/<venue_mode>/  trạng thái bot, sự kiện (lưu lâu dài)  (← _cache/live)
  cache/                                              # TẠM THỜI, xoá được
    process/<id>/  params, trạng thái, tiến độ, log, checkpoint   (← _cache/api_jobs, _cache/runs)
    shared/        mmap chỉ báo dùng chung            quality_gate/
```

**Vòng đời một lần chạy** (backtest, WFA, carlo, phễu, custom backtest, education):
1. Đang chạy: mọi thứ ở `data/cache/process/<id>/`; đứt quãng thì đọc checkpoint và chạy tiếp.
2. Xong: kết quả + params ghi vào nơi lưu lâu dài (`data/backtest|wfa|carlo|alpha/…`).
3. Dọn ngay `data/cache/process/<id>/`. Job lỗi hoặc bị huỷ: giữ log 7 ngày rồi tự xoá. *(người dùng chốt 2026-10-07)*
4. Bước sau (WFA, carlo) đọc từ kết quả lâu dài; chỉ việc đang chạy dở mới có checkpoint trong cache.
5. Trang Lịch sử đọc từ các thư mục kết quả lâu dài, không đọc cache. *(người dùng chốt 2026-10-07)*
6. **Ngoại lệ — chạy tạm của người dùng** (custom backtest ở /alpha/create, lượt chạy Education do người học bấm): KHÔNG ghi vào `data/backtest/`.
   Kết quả ở lại `data/cache/process/<id>/` (giao diện đọc kết quả từ đó) với hạn 24 h. Khi người dùng bấm Lưu: máy chủ đọc kết quả từ thư mục cache,
   kiểm `program_hash` (chống sửa từ phía client), chép code + config + kết quả + bằng chứng vào `data/alpha/user/<id>.json`, rồi xoá thư mục cache.
   Không lưu trong 24 h thì tự xoá.
7. Theo dõi trong git: `data/alpha/{strategies,education,universes}/`, `presets.json`, `registry.json`, `book.json`, `explore/`, `testnet/` được commit;
   `data/alpha/user/`, `data/alpha/funnel/`, `data/alpha/book/`, `data/market/`, `data/backtest|wfa|carlo|live|cache/` không commit (.gitignore).

Chọn gốc dữ liệu: một chỗ duy nhất `crawl/store.py` — `NORA_DATA_ROOT` (mặc định `nora/data`), `NORA_EXCHANGE` chọn `market/<sàn>`,
`NORA_LOCAL_DATA_ROOT` giữ cho test. Bí danh nguồn dữ liệu cũ giữ trong `crawl/store.py`: `binance_hist` → `market/binance/cex_ref`
(bản ghi cũ có `config.exchange` / `data.source = "binance_hist"` vẫn đọc được; nằm trong danh sách shim, không gỡ ở P9.10).
Quy tắc manifest: `sha256_1m` = `compute_df_sha256(df)` (băm NỘI DUNG khung dữ liệu), đúng như quality gate so sánh.
Hiện 79 manifest `okx/cex/*/perp` đang lưu băm BYTE file (đợt gộp data_staging ~07:58 UTC 07/10) → mọi tài sản OKX bị chặn; sửa ở P9.1.

## 5. Kế hoạch triển khai (todo, mỗi ID một commit, review chéo trước khi commit)

| ID | Việc | Người | Cần trước | Xong khi |
|---|---|---|---|---|
| P9.0 | ADR này + test luật phụ thuộc (chế độ báo cáo) | O | — | Phiên alpha + backtest analyst OK; người dùng duyệt |
| P9.1 | Sửa 79 manifest OKX (`compute_df_sha256`), xác nhận nội dung nến trước khi ghi | S | P9.0 + user OK | Quality gate APPROVED/WARNING cho mọi tài sản; test_pydsl_parity xanh |
| P9.2 | `crawl/` (cex, dex, store) + chọn gốc dữ liệu một chỗ | S | P9.0 | Khoá cache mmap không đổi; crawl/quality gate test xanh |
| P9.3 | `data/` theo cây mới (script chuyển + kiểm sha256, symlink tạm ở đường cũ) | S | P9.2 | Mọi job đọc/ghi đúng chỗ mới; không mất file (đếm + băm) |
| P9.4 | `core/` (models, params, indicator, signal, position_size, backtest) + shim | S | P9.2 | Golden + mọi parity + nautilus_diff không đổi |
| P9.4b | Một engine: paper/live gọi kernel từng nến (trạng thái mảng), gỡ tracker/manager/sim_venue/runner; OkxVenue chỉ I/O | O thiết kế, S cài | P9.4 | Paper = backtest bit-identical bằng chính engine; test bot unified + OKX xanh; nautilus_diff không đổi |
| P9.5 | `metrics/` (gộp xno vào metrics.py, periods_per_year) + `regime/`, `wfa/`, `carlo/`, `verdict/` | S | P9.4 + phiên alpha commit xong | test_xno_parity khớp < 1e-9; khoá `metrics.{…}.{xno,nora}` giữ nguyên hoặc có bảng đổi tên cho frontend |
| P9.6 | `optimize/` (search, funnel, book, process) + vòng đời `data/cache/process` + dọn cache | S | P9.4 | Huỷ/khôi phục/resume chạy đúng; job cũ đọc được qua shim |
| P9.7 | `live/` (bot, okx) — chỉ unified; khởi động lại bot demo | S, user duyệt bật lại bot | P9.4, P9.6 | test_live_bot, test_bot_unified, test_okx_venue xanh; bot chạy engine mới |
| P9.8 | `routes/` (← api) + modes + kiểm tham số job | S | P9.6 | Mọi route `/api/studio/*` giữ nguyên; frontend chạy |
| P9.9 | Chiến lược thành dữ liệu `data/alpha/strategies/` | S + phiên alpha | P9.4 | Danh mục chiến lược đọc từ file; golden không đổi |
| P9.10 | Gỡ shim, bật test luật phụ thuộc bắt buộc, full suite, cập nhật architecture.md + BMAD | O | tất cả | 0 vi phạm phụ thuộc; full suite xanh |

Phần của phiên alpha (pydsl, custom_run, edu_precompute, diagnose*, xno, insights, user_alphas, strategy_doc, router custom/education/strategies/alphas,
job custom_backtest/edu_precompute) chỉ được chuyển sau khi phiên đó commit 4 commit của mình và đồng ý.
