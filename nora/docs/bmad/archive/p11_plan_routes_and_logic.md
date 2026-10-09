# P11 — Kế hoạch triển khai: gọn `routes/` + việc logic còn lại (2026-10-08)

Người đọc: người triển khai (anh) và hai phiên hỗ trợ (kiến trúc "nautilus trader backtest", logic + dữ liệu "alpha và backtest analyst").
Trạng thái nền: kiến trúc P9/P10 đã chốt (`docs/bmad/p9_architecture_final.md`, ADR `docs/bmad/adr-p9-backend-layout.md`). Chưa commit gì.
Chạy Python: `ops/run_limited.sh --no-lock -- ...`; golden: `NORA_GOLDEN_DATA_ROOT=$PWD/data/market/binance`.

---

## A. Kiến trúc — `routes/` từ 14 file xuống 5 file (theo package backend)

### A1. Cây đích

```
routes/
  alpha.py      ↔ backend/alpha      viết · sửa · chạy thử · giải thích chiến lược         31 endpoint
  optimize.py   ↔ backend/optimize   phễu kiểm duyệt · sổ alpha · danh mục                    25 endpoint
  data.py       ↔ backend/crawl      dữ liệu thị trường · regime                              7 endpoint
  live.py       ↔ backend/live       bot paper / testnet / live                               5 endpoint
  process.py    ↔ optimize/process   lớp dùng chung: khởi chạy + kiểm tham số job, chế độ
                                     Cơ bản/Nâng cao, metadata cho UI                        1 endpoint
```

Quy tắc:
- **URL giữ nguyên 100 %**: mỗi file khai báo nhiều `APIRouter` với đúng prefix cũ → frontend không sửa.
- `main.py`: 13 dòng `include_router` → mỗi file 1 hàm/biến xuất danh sách router, `main.py` include 5 module.
- Gộp nguyên văn (move-only); helper trùng tên chỉ gộp khi cùng ngữ nghĩa (vd. `_read_json` của routes/book giữ riêng vì trả HTTP 500).
- `process.py` là module helper (không có router riêng ngoài `/api/studio/meta`); router khác import từ đây. Không router nào import router khác.

### A2. Bảng chuyển (file cũ → file mới)

| File cũ | Prefix | Endpoint | → File mới |
|---|---|---|---|
| `alphas.py` | `/api/studio/alphas` | catalog, top_agents, user (POST/GET), user/{id}, /code, /versions, /versions/{v}, /archive, /status | `alpha.py` |
| `strategies.py` | `/api/studio/strategies` | "", "/", catalog, validate, presets, compile, explain, dsl, source/{id} GET/PUT, assist/{catalog,check,complete,hover} | `alpha.py` |
| `custom.py` | `/api/studio/custom` | defaults, backtest | `alpha.py` |
| `chart.py` | `/api/studio/chart` | explain | `alpha.py` |
| `education.py` | `/api/studio/education` | results, results/{key}, precompute, samples | `alpha.py` |
| `funnel.py` | `/api/studio/funnel` | runs (POST/GET), estimate, runs/{id}, /cancel, /stages/{s}/stats, /alphas, /alphas/{a}, /trades, /book, /promote | `optimize.py` |
| `book.py` (`router`) | `/api/studio/book` | "/", backtest, wfa, build, publish, jobs, jobs/{id}, /cancel, /stage_a, mc | `optimize.py` |
| `book.py` (`alphas_router`) | `/api/studio` | alphas, alphas/{id}/revalidate | `optimize.py` |
| `portfolio.py` | `/api/studio/portfolio` | dashboard, trades | `optimize.py` |
| `data.py` | `/api/data` | crawl, ticks/crawl, ticks/coverage, promote | `data.py` |
| `market.py` | `/api/studio/market` | signals, regime, regime/report | `data.py` |
| `live.py` | `/api/studio/live` | bot (POST/GET), trades, compare, compare_events | `live.py` (giữ) |
| `jobs.py` | — (helper) | http_launch, build_and_launch, kiểm tham số job | `process.py` |
| `modes.py` | — (helper) | chế độ Cơ bản/Nâng cao, preset, kiểm params_schema | `process.py` |
| `meta.py` | `/api/studio` | meta | `process.py` |

Tổng 69 endpoint trước = 69 endpoint sau.

### A3. Các bước

1. **Chụp bảng route TRƯỚC**:
   ```
   ops/run_limited.sh --no-lock -- -c "from backend.main import app; import json; print(json.dumps(sorted((sorted(r.methods), r.path) for r in app.routes if hasattr(r,'methods'))))" > /tmp/routes_before.json
   ```
2. Tạo `process.py` = `jobs.py` + `modes.py` + `meta.py` (nguyên văn; một khối import đầu file).
3. Tạo `alpha.py`, `optimize.py`; gộp `market.py` vào `data.py`. Mỗi file giữ tên router cũ có tiền tố (vd. `strategies_router`, `funnel_router`) và xuất `ROUTERS = [...]`.
4. Sửa import mọi nơi: `backend/` (router gọi `routes.jobs` → `routes.process`), `test/` (`backend.routes.<cũ>` → file mới; monkeypatch chuỗi đường dẫn), `test/scripts/`.
5. `main.py`: `for m in (alpha, optimize, data, live, process): for r in m.ROUTERS: app.include_router(r)` — **giữ đúng thứ tự include cũ** (FastAPI khớp route theo thứ tự đăng ký; `/api/studio/alphas` của book và `/api/studio/meta` cùng prefix `/api/studio`).
6. Xoá 10 file cũ: `alphas, strategies, custom, chart, education, funnel, book, portfolio, market, jobs, modes, meta` (giữ `data.py`, `live.py` đã sửa).
7. Cập nhật: `test/test_layering.py` (LAYER_RULES cho 5 file routes), `test/test_ops_units.py` nếu kiểm danh sách file, `docs/bmad/adr-p9-backend-layout.md` §2 (`routes/` 5 file), `docs/bmad/p9_architecture_final.md` (bảng file cũ → mới ở trên).

### A4. Kiểm tra (một lần ở cuối)

- Bảng route SAU giống hệt TRƯỚC: `diff /tmp/routes_before.json /tmp/routes_after.json` rỗng.
- Import sạch mọi module backend; `test/scripts/p9_ledger.py --hide-identical --dups` → MISSING không tăng, DUPS = 0.
- pytest: `test_book_api test_book_ui_backend test_funnel test_custom_backtest test_live_bot test_bot_unified test_web_perf_cache test_run_modes test_user_alphas test_signal_explain test_layering test_ops_units`.
- `systemctl --user restart nora-api` (bot không bị ảnh hưởng: KillMode=process) → mở UI: Alpha/Create, Catalog, Funnel, Book, Danh mục, Live, Dữ liệu.

### A5. Việc kiến trúc nhỏ đi kèm

- **Bản sao lưu khi sửa chiến lược** đang ghi vào `data/cache/process/_strategy_backup/` → cache bị dọn (chỉ giữ tiến trình đang chạy) nên bản lưu mất. Chuyển sang nơi lâu dài: `data/alpha/strategies/.versions/<file>.<ts>.py` (hằng đường dẫn trong `alpha/compile.py`, cạnh bộ nạp).
- `data/carlo/` và `data/live/live/` tạo khi có dữ liệu đầu tiên — không cần làm gì.

---

## B. Logic — việc còn lại

Thứ tự đề xuất (mỗi mục: việc · nơi sửa · xong khi):

| # | Việc | Nơi sửa | Xong khi |
|---|---|---|---|
| B1 | Dựng lại các book (engine_version đã đổi nhiều lần trong P9/P10 → mọi book `needs_rebuild`) | UI Book → Build / `POST /api/studio/book/build` | Book hiện tại không còn `needs_rebuild`; so số holdout với bản trước P9 (~+70,6 % 1m) — lệch phải giải thích được |
| B2 | P9.4b T8–T11: bot paper/demo chạy hẳn trên kernel; xoá đoạn LEGACY (~1.600 dòng `tracker/manager/sim_venue/runner` cuối `core/backtest.py`) + ~25 hàm `position_size` chỉ bot legacy dùng; bỏ `engine="legacy"` ở `live/` và `routes/live.py` | `core/backtest.py`, `core/position_size.py`, `live/*.py`, `routes/live.py` | Golden + kernel parity + Nautilus `check_baseline.py` 332/332 + test live xanh; 3 bot chạy engine unified; `data/live/testnet/okx_main_legacy` bỏ được |
| B3 | Gộp trùng cố ý còn lại (đổi số → phải chốt số mới): Sharpe inline trong `portfolio_metrics`; `charts._num` (+0.0); `registry/build._num` | `metrics/metrics.py`, `metrics/charts.py`, `optimize/book/*.py` | Một định nghĩa mỗi công thức; golden cập nhật có giải thích (hoặc giữ nguyên bit nếu không đổi) |
| B4 | Gộp `signal_snapshot` (đang import trễ core.backtest + gọi `eng.load_data` — I/O trong core) vào cạnh `evaluate_signals` ở `core/backtest.py`, nơi gọi nạp dữ liệu và truyền vào | `core/signal.py`, `core/backtest.py`, nơi gọi trong `routes/` | core không còn I/O; layering strict = 0 |
| B5 | Khoá sửa chiến lược khi bot live chạy: hiện chặn với MỌI bot → chỉ chặn chiến lược mà bot đang dùng | `alpha/compile.py` (StrategyEditError), `routes/alpha.py` | Sửa `sideway.py` được khi bot chỉ dùng `kema`/`dca` |
| B6 | `normalized_code` (nút "Chuẩn hoá code") mất comment do `ast.unparse` → giữ comment (tokenize ghép lại) hoặc chỉ format khoảng trắng | `alpha/compile.py` | Comment còn nguyên sau chuẩn hoá |
| B7 | Log lỗi của job: cache giờ xoá job lỗi/huỷ ở lượt dọn kế tiếp → lý do lỗi mất. Nếu cần xem lại: ghi một dòng tóm tắt lỗi (kind, params, 50 dòng cuối out.log) vào nơi lâu dài của loại job đó (vd. `data/backtest/_failed.jsonl`) trước khi xoá | `optimize/process/process.py` | Trang Lịch sử hiện job lỗi gần đây dù thư mục process đã xoá |
| B8 | Kết quả `/alpha/create` (custom_backtest) chỉ ở bộ nhớ API → restart API trước khi bấm Lưu là mất. Chấp nhận, hoặc giữ kết quả cuối mỗi người dùng trong `data/alpha/user/_last/` | `optimize/process/process.py`, `routes/alpha.py` | Quyết định ghi vào ADR §4 |
| B9 | Kiểm UI tính năng P10 (trình soạn có gợi ý code): gõ code → chip RUN; sai tên chỉ báo → REJECT + "Sửa thành"; chạy backtest → Lưu → "Mở để sửa" → lưu v2; Catalog → "</> Mã nguồn" → "Kiểm tra" | frontend | Các luồng trên chạy đúng |
| B10 | Dọn tay (tuỳ chọn): user alpha thử `29b85425e324`, `4d4ef78d5b96` (đã archive) trong `data/alpha/user/` | `data/alpha/user/` | — |

Không thuộc kế hoạch này (đã chốt trước): bước funnel S2_antiluck đã gộp vào S3 (WFA: PBO + lân cận) và S4 (Monte Carlo: DSR, kết luận cuối).

---

## C. Kiểm tra tổng + commit (cuối cùng, một lần)

1. `NORA_LAYERING_WRITE=1 ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py` → strict 0.
2. Nautilus: `test/scripts/nautilus_diff/check_baseline.py` → 332/332.
3. Full pytest: `NORA_GOLDEN_DATA_ROOT=$PWD/data/market/binance ops/run_limited.sh -- -m pytest test -q -p no:cacheprovider`.
4. Commit theo nhóm (kiểm `git diff --cached --name-status` trước mỗi commit, chỉ stage đúng file của nhóm): engine/core · alpha · data layout + crawl · optimize · live · routes · ops · tests · docs · frontend.

---

## D. Kiến trúc — `optimize/`: mỗi file một động từ của pipeline

Giữ 4 thư mục, 9 file (đúng đề xuất gốc). Vấn đề hiện tại không phải tên thư mục mà là **nội dung lẫn vai**: `process/tasks.py` (1.421 dòng) vừa là điểm vào job vừa chứa tính toán + WFA danh mục + nạp dữ liệu; `book/registry.py` (1.190 dòng) gánh 5 vai; `funnel/stages.py` vừa lọc vừa xuất bản.

### D1. Vai đích của từng file

```
optimize/                         pipeline: SINH → CHẠY → LỌC → DỰNG SỔ → QUẢN LÝ, chạy bằng JOB
  search/generate.py    SINH      lưới/mẫu tham số, id alpha, biến thể regime, validate_alpha
  search/evaluate.py    CHẠY      engine hàng loạt: backtest, WFA (từng alpha VÀ danh mục), MC, tick; worker; mmap dùng chung; EngineData
  funnel/stages.py      LỌC       cổng S0→FINAL, sizing, thống kê tầng, bộ điều phối phễu
  funnel/storage.py     LƯU       kho kết quả phễu (sqlite), khoá resume, code_version, data_fingerprint
  book/build.py         DỰNG SỔ   chọn alpha đạt → sổ, preset, cấu hình sổ
  book/registry.py      QUẢN LÝ   registry + xuất bản (publish, promote từ phễu) + revalidate + engine_version + user alpha + catalog/tài liệu chiến lược + top agents
  process/process.py    VÒNG ĐỜI  khởi chạy / huỷ / trạng thái / lưu kết quả / dọn cache
  process/tasks.py      ĐIỂM VÀO  mỗi loại job một hàm run_<kind> MỎNG: đọc params → gọi hàm của search/funnel/book → ghi kết quả
  process/workers.py    TÀI NGUYÊN pool tiến trình + trần RAM (nora.slice)
```

### D2. Việc chuyển (move-only, một định nghĩa)

| # | Từ | Đến | Lý do |
|---|---|---|---|
| D2.1 | `tasks`: `run_wfa_job, plan_is_jobs, plan_oos_jobs, plan_regime_jobs, run_portfolio_wfa, print_summary` | `search/evaluate.py` (cạnh `run_wfa`) | WFA là CHẠY engine, không phải điểm vào; hai đường WFA (từng alpha / danh mục) nằm cạnh nhau → phiên logic kiểm có trùng logic IS/OOS không |
| D2.2 | `tasks`: tính toán thuần của backtest tuỳ chỉnh `stage_split, daily_series, build_metrics, yearly_table, build_stages, build_result, run_benchmark, label_stats, shock_stats` | `metrics/trades.py` (hoặc `metrics/metrics.py` cho phần chỉ số) | metrics = tính thuần (luật người dùng 2026-10-08) |
| D2.3 | `tasks`: nạp dữ liệu `check_data, data_info, resolve_symbols, default_universe, default_window, load_samples, daily_close, load_prices, strategy_frames, load_report` | `crawl/store.py` | đọc đĩa = tầng crawl |
| D2.4 | `stages`: `promote_alpha, build_report, run_funnel_book` | `book/registry.py` (promote/xuất bản) + `process/tasks.py` (run_funnel_book chỉ là điểm vào) | phễu chỉ LỌC; ghi vào kho alpha là việc QUẢN LÝ |
| D2.5 | `tasks`: `run_custom, run_custom_backtest, run_edu_precompute, run_book_backtest, run_book_wfa, run_regime_report` | giữ ở `tasks`, rút gọn còn điểm vào | sau D2.1–D2.3 mỗi hàm còn vài chục dòng |

Kết quả dự kiến: `tasks.py` ~300 dòng (chỉ điểm vào), `stages.py` ~1.300, `evaluate.py` ~1.500, `registry.py` ~1.350.

Tên package: giữ `optimize/` (người dùng chốt "pipeline = optimize"); nếu muốn đọc theo nghĩa, có thể đổi `book/registry.py` → `book/library.py` ("kho alpha") — tuỳ anh, đổi tên kéo theo sửa import ở ~25 chỗ.

### D3. Kiểm tra
- Cùng bộ kiểm như A4 (bảng route không đổi, ledger MISSING không tăng, DUPS = 0) + golden, `test_portfolio_wfa`, `test_funnel`, `test_scale_pipeline`, `test_custom_backtest`, `test_edu_precompute`.
- Phiên logic: rà D2.1 — `evaluate.run_wfa` (WFA từng alpha của phễu) và `run_portfolio_wfa` (WFA danh mục) có cùng quy ước IS/OOS không; nếu trùng phần lõi → gộp một hàm (logic, đổi số phải giải thích).

---

## E. Kiến trúc + dọn rác frontend (bổ sung `docs/bmad/p11_ui_sync_plan.md` — phần đó lo HÀNH VI/logic UI, mục này lo CẤU TRÚC)

Audit read-only 2026-10-08 sau lượt bỏ mock (105 file trong `src/`, build sạch).

### E1. Rác (xoá ngay, không đổi hành vi)
| Loại | Mục |
|---|---|
| File không ai import | `src/styles/education.css` (525 dòng) |
| Export chết (0 nơi dùng) | `api.js`: `postExplainStrategy`, `getUserAlphaVersions`, `getEducationResults`, `getEducationResult`, `postFunnelBook` — 3 cái sau sẽ được DÙNG ở sync-plan C1/C4 (giữ nếu làm C1/C4, xoá nếu không); `getStudioMeta` → dùng ở E3. `lib/jobs.js:jobWhen`, `lib/params.js:paramUnitOr`, `lib/format.js:finite`, `lib/stopfill.js:STOP_FILL_LABEL`, `components/WfaResult.jsx:chosenText`, `components/funnel/parts.jsx:MetricVal` |
| Route chỉ để chuyển hướng | `/funnel`, `/funnel/:runId` (`FunnelRedirect`) → bỏ sau khi xác nhận không còn link ngoài trỏ vào |
| Trang vỏ 3 dòng | `pages/CreateAlpha.jsx`, `pages/Education.jsx` (cùng bọc `StudioWorkspace`) → một `pages/Studio.jsx` nhận `mode` từ route |
| Format số tự viết | ~10 chỗ `toFixed`/`fmt` cục bộ trong `.jsx` → `lib/format.js` |

### E2. Cấu trúc đích (khớp package backend như `routes/`)
```
src/
  main.jsx  App.jsx  api.js              api.js = đúng 1 hàm / route (nhóm theo routes/{alpha,optimize,data,live,process})
  meta/MetaProvider.jsx                  thay context/Catalog.jsx: /api/studio/meta + catalog, useMeta()
  hooks/                                 useResource (từ useAsync) · useJob · useJobList · useStored · useMemState · useUnsavedGuard
  lib/                                   CHỈ phần thuần UI: format · dates · glossary · assist · strategyLabel · studioDraft
  layout/Shell.jsx
  pages/        Portfolio · Backtest · AlphaCatalog · Studio · Tune (Alpha.jsx → đổi tên) · Funnel · Live · History
  components/
    ui/         ui.jsx · DateField · Term · MathBlock · QuickGuide · Collapsible · Pager · ProgressBar · Sparkline
    charts/     gộp chart/ + charts/: AreaLine · BarsPosNeg · FanChart · HeatmapTable · Histogram · OverlayHist · UnderwaterStrip ·
                SignalChart · TradeChartDrawer · SignalExplainPanel · geometry.js (← charts/chartUtils.js) · chartFormat.js (← chart/chartUtil.js)
    alpha/      studio/* · AlphaTabs
    optimize/   funnel/* · backtest/* · WfaResult · McResult · RunModes · GateList · EngineWarning
    portfolio/  Dashboard · OverviewExtras · DetailSection
    jobs/       JobPanel · JobTray
  styles/       base.css · shell.css (← app.css) · alpha.css (← alphadoc + pushToAlpha + strategyEditor + diagnostics) ·
                optimize.css (← funnel + backtest) · portfolio.css
```
Lý do: hết cặp `chart/` vs `charts/`; component theo khu vực nghiệp vụ thay vì nằm phẳng; tên CSS cũ (`pushToAlpha`) biến mất; một chỗ tìm mỗi màn hình.

### E3. Một nguồn sự thật (= sync-plan B1/B2)
- `MetaProvider` nạp `/api/studio/meta` một lần (ETag), mọi hằng nghiệp vụ đọc từ đó.
- Xoá khỏi `lib/`: `funnel.js` (STAGES, STAGE_META, LEGACY_STAGE `S2_antiluck` đã lỗi thời, ALL_STAGES, METRICS nếu meta có), `jobs.js` (JOB_KIND), `modes.js` (WFA_STD, MC_STD, STRESS), `params.js` (PARAMS/PARAM_GROUPS → `params_schema` từ `/strategies/catalog`), `stopfill.js`, `runDefaults.js` (← `/custom/defaults`). Phần còn lại thuần UI (nhãn cột bảng `customResult.js`) giữ.

### E4. Endpoint backend không có UI (quyết: làm UI hay ghi "chỉ cho script")
`/api/data/{crawl,promote,ticks/crawl,ticks/coverage}` (sync-plan D2 "trang Dữ liệu"), `/api/studio/market/signals`, `/api/studio/education/precompute`.

### E5. Thứ tự + kiểm
1. E1 (rác) → `npm run build`.
2. E2 (di chuyển file, sửa import; không đổi JSX/hành vi) → build + mở từng trang.
3. E3 cùng sync-plan B1/B2 (đổi hành vi: phải thấy nhãn/cổng/kind khớp backend).
Kiểm: build sạch; đồ thị import không còn file mồ côi; script so `api.js` ↔ `/openapi.json` (sync-plan B3); mọi trang tải không lỗi console.

### E6. Bổ sung sau review của phiên logic (2026-10-08) — kế hoạch được duyệt kèm các điểm này
**Thứ tự / xung đột:** worker logic đang sửa `components/studio/{StudioWorkspace,CodeEditor}.jsx`, `styles/strategyEditor.css`, `backend/alpha/compile.py`, `routes/alpha.py` (chú thích education thành comment `# ▸`, tab "+" mở rỗng). Bước 1 (gộp trang → `Studio.jsx`) và Bước 2 (chuyển `studio/*` → `alpha/`, gộp CSS) chỉ bắt đầu SAU khi phiên logic báo xong.

**Backend phải xong TRƯỚC Bước 4** (phiên logic làm): A3 fingerprint `needs_rebuild` = file engine + hash IR chiến lược đã biên dịch (sửa `data/alpha/strategies/*.py` phải bật cờ; sửa trợ lý/hằng đường dẫn không bật) · A4 `UnifiedBot` ghi lệnh đã đóng (tab demo đang 0 lệnh); `/live/trades`, `/live/compare` trả `engine` + `dir` · A5 job tạm hết hạn → 410 `EPHEMERAL_GONE` (nay 404) · A6 nhãn job còn "alphas/book.json".

**Meta còn thiếu cho Bước 3:**
1. Từ điển chỉ số: label / đơn vị / format / chiều tốt (cao/thấp) cho mọi khoá UI hiển thị (`ret_pct, cagr_pct, sharpe, sortino, mdd_pct, calmar, win_rate_trades, profit_factor_trades, fees_usd, …`) → CustomResult / Dashboard / Funnel / glossary không viết cứng nhãn, đơn vị.
2. Thứ tự mục kết quả cho tour education (đang cứng trong CustomResult / ResultTour) ← khoá notes của `metrics/charts`.
3. `PARAMS` / `PARAM_GROUPS` đọc `params_schema` từ `/strategies` + `/strategies/catalog` (đã có), KHÔNG từ meta.
4. Khung thời gian cho phép: Backtest / Tune / NewRunForm dùng `meta.frames.allowed`, bỏ danh sách 15m/1h/4h viết cứng.
5. Chữ trợ giúp có ngưỡng (30 %, 10.000 lượt mô phỏng…) trong glossary / `params.js` đọc `meta.funnel.gates`.

**Thêm bước kiểm "UI chỉ format":** grep pages/components tìm `reduce`, `Math.`, mean/std, phép tính phần trăm; đã biết: text luật cổng trong `lib/funnel.js` METRICS, Dashboard fallback benchmark `'BTC'`, tính lại vốn/drawdown trong charts. Số nào tính ở UI → chuyển về backend hoặc lấy từ API.

**Sửa Bước 1:** `getEducationResult(s)` KHÔNG giữ — đường chạy education luôn live (51/51 mẫu đã chạy trên engine), file precompute chỉ là baseline hồi quy → xoá 2 hàm UI. Hỏi người dùng có bỏ luôn endpoint `/education/results` + `/education/precompute` không.

**Đã xong (không làm lại):** `/api/studio/meta` từ nguồn thật + ETag (`routes/process.py`, có `test_meta`) · `meta.books` khối fix (funnel_book với run_id / alpha_ids / wfa_job_id thật) · gộp Studio (CreateAlpha / Education = StudioWorkspace, khung phải chỉ Mẫu / Kết quả, ResultTour + annotate) · bỏ toàn bộ mock · thông báo 404/410 "kết quả tạm đã mất" · `postAnnotate` trong api.js.

**Thêm vào kiểm cuối:** E2E xác nhận `/alpha/create` và `/education` chỉ khác ở (comment chú thích, tour hướng dẫn); mỗi trang lấy mẫu vài số trên màn hình so khớp đúng response API.
