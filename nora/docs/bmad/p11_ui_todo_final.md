# P11 — TODO UI bản chốt (2026-10-08)

Người triển khai: anh. Đã duyệt bởi phiên kiến trúc + phiên logic ("alpha và backtest analyst").
Nguồn: `p11_plan_routes_and_logic.md` §E/E6 (cấu trúc) + `p11_ui_sync_plan.md` (hành vi). File này thay cả hai cho phần UI.
Quy tắc: **backend là nguồn sự thật duy nhất; UI chỉ trình bày + format.** Mỗi bước xong: `npm run build` sạch rồi mới sang bước sau.

> Trạng thái (cập nhật): worker studio của phiên logic ĐÃ XONG → `frontend/`, `backend/alpha/compile.py`, `routes/alpha.py` rảnh cho Bước 0–2 (education mở mẫu với dòng comment `# ▸`, endpoint `POST /strategies/annotate {code, as_comments|strip}`, `studio/samples.js` đã xoá).
> Bước 3 (backend của phiên logic) ĐÃ XONG → mọi bước còn lại do anh làm, không còn file nào bị khoá.

---

## Bước 0 — Bỏ thứ không dùng (backend + frontend)

Quyết định người dùng: cái nào không dùng thì bỏ.

| Bỏ | Nơi sửa | Ghi chú |
|---|---|---|
| `GET /api/studio/education/results`, `GET /results/{key}`, `POST /precompute` | `backend/routes/alpha.py` | UI không gọi; education luôn chạy live (51/51 mẫu chạy trên engine) |
| Job `edu_precompute` (`run_edu_precompute`, `EDU_PRECOMPUTE_DEFAULTS`, KINDS) | `optimize/process/{tasks,process}.py`, `routes/process.py` (meta jobs) | kéo theo endpoint trên |
| Kết quả precompute `data/backtest/education/` + helper `education_results_dir` | `crawl/store.py` (kind `education_results`) | nếu cần baseline hồi quy: test chạy live 51 mẫu thay cho file precompute (phiên logic đã có bộ kiểm) |
| `test/test_edu_precompute.py` | `test/` | thay bằng test chạy live mẫu (hoặc xoá nếu đã có) |
| `GET /api/studio/market/signals` | `routes/data.py` | UI, test, script không gọi |
| `api.js`: `postExplainStrategy`, `getEducationResults`, `getEducationResult` | `frontend/src/api.js` | export chết |
| `lib/jobs.js:jobWhen`, `lib/params.js:paramUnitOr`, `lib/format.js:finite`, `lib/stopfill.js:STOP_FILL_LABEL`, `WfaResult.jsx:chosenText`, `funnel/parts.jsx:MetricVal` | frontend | export chết |
| `src/styles/education.css` | frontend | không ai import |
| Route `/funnel`, `/funnel/:runId` (`FunnelRedirect`) | `App.jsx` (+ sửa link nội bộ) | chỉ chuyển hướng |

**Phụ thuộc phải xử lý TRƯỚC khi xoá `data/backtest/education/`** (phiên logic chỉ ra):
- `test/test_result_notes.py` đọc `data/backtest/education/breakout_bb_squeeze.json` làm kết quả thật → đổi sang chạy live 1 mẫu (`run_custom`, 1 tài sản, cửa sổ ngắn) hoặc chép một fixture nhỏ vào `test/fixtures/`.
- `test/scripts/check_samples_run.py` so 3 mẫu với `data/backtest/education/<key>.json` → bỏ phần so sánh, giữ phần chạy live 51 mẫu làm kiểm hồi quy.
- Bỏ cùng `edu_precompute`: mục `KINDS` trong `optimize/process/process.py`, `tasks.run_edu_precompute` + `EDU_PRECOMPUTE_DEFAULTS`, helper `education_results_dir` / `results_dir` trong `crawl/store.py` nếu không còn ai dùng (meta đọc từ KINDS nên tự theo). Bước `edu_results` trong `test/scripts/migrate_data_tree.py` là lịch sử chạy một lần — để nguyên.
- `/market/signals`: chỉ bỏ route; `core/backtest.signal_snapshot` GIỮ (test/script dùng).

**GIỮ** (có người dùng dù không có UI): `/api/data/{crawl,promote,ticks/crawl,ticks/coverage}` — đường duy nhất để cập nhật dữ liệu (luật: job chỉ qua API runner); ghi rõ trong `docs/data_layout.md` là "API vận hành (curl/script)". `getStudioMeta`, `getUserAlphaVersions`, `postFunnelBook` — dùng ở Bước 3–4.

Kiểm: OpenAPI giảm đúng 4 thao tác (72 → 68); `pytest` các file liên quan; build sạch.

---

## Bước 1 — Dọn trang (không đổi hành vi)
- [ ] Gộp `pages/CreateAlpha.jsx` + `pages/Education.jsx` (vỏ 3 dòng) → `pages/Studio.jsx` nhận `mode` từ route; URL `/alpha/create`, `/education` giữ.
- [ ] ~10 chỗ `toFixed`/`fmt` tự viết → `lib/format.js`.
- Xong khi: build sạch; không file mồ côi; 9 trang mở không lỗi console.

## Bước 2 — Cấu trúc (chỉ đổi đường dẫn file + import, view y hệt)
```
src/  main.jsx · App.jsx · api.js (nhóm theo 5 router backend: alpha, optimize, data, live, process; 1 hàm / route)
  meta/MetaProvider.jsx (Bước 3)       hooks/          lib/ (chỉ thuần UI)       layout/Shell.jsx
  pages/       Portfolio · Backtest · AlphaCatalog · Studio · Tune (← Alpha.jsx) · Funnel · Live · History
  components/
    ui/        ui.jsx · DateField · Term · MathBlock · QuickGuide · Collapsible · Pager · ProgressBar · Sparkline
    charts/    chart/ + charts/ gộp; chartUtils.js → geometry.js; chartUtil.js → chartFormat.js
    alpha/     studio/* · AlphaTabs
    optimize/  funnel/* · backtest/* · WfaResult · McResult · RunModes · GateList · EngineWarning
    portfolio/ Dashboard · OverviewExtras · DetailSection
    jobs/      JobPanel · JobTray
  styles/      base · shell (← app.css) · alpha (← alphadoc + pushToAlpha + strategyEditor + diagnostics) · optimize (← funnel + backtest) · portfolio
```
- Xong khi: build sạch; chụp màn hình từng trang trước/sau giống nhau.

---

## Bước 3 — Backend (phiên logic) — ✅ XONG 2026-10-08
A3 fingerprint = `core/*.py` + `optimize/search/evaluate.py` + hash IR đã biên dịch từng chân (comment/contract/refactor compiler không bật cờ; mọi sổ bật `needs_rebuild` một lần) · A4 `/live/trades|compare|compare_events` trả `engine` + `dir`, compare unified = event path · A5 job tạm hết hạn → 410 `{code: "EPHEMERAL_GONE", message, job_id}` (GET job + lưu user alpha) · A6 nhãn job dùng `data/alpha/book.json` · meta thêm `metrics` + `explain_tour`.

**Sau khi xong Bước 0:** thêm các mục đã bỏ (PrecomputeRequest, run_edu_precompute, build_edu_precompute, các route education/signals …) vào danh sách cố ý xoá trong `test/scripts/p9_ledger.py` để `p9_ledger --hide-identical` hết báo MISSING (hiện 78 do Bước 0 đang dở; `--dups` = 0).

**Phần Bước 0 còn lại (sau khi Bước 3 xong, giờ làm được):** `optimize/process/process.py` mục `KINDS["edu_precompute"]` (~L204) + chú thích ~L412 · `optimize/process/tasks.py` `run_edu_precompute` + khối chú thích (~L154–227) · `routes/process.py` nhánh `elif kind == "edu_precompute"` (~L288), `build_edu_precompute` (~L352), docstring L5/L386. OpenAPI hiện 69 thao tác (đã bỏ education results/precompute + market/signals, thêm `POST /strategies/annotate`).

### Hợp đồng `/api/studio/meta` (dùng ở Bước 4–5)
```
funnel        {stages: [{id, label, short, has_trades, legacy}], gates: [{key, label, value, unit, stage}]}
frames        {all, custom_backtest, funnel}                     → danh sách khung cho từng form
live          {modes: [{mode, dir, engines, default_engine, books, exec}], venues, books, engines}
jobs          {kinds: [{kind, label, persist_to, ephemeral}]}
universe      {data, book, explore}                              → 10 tài sản theo kho / theo sổ
limits        {funnel_run, funnel_book, custom_backtest, book_backtest, book_wfa, book_mc, book_build, live_bot, regime_report, data_crawl, data_crawl_ticks}
metrics       {defs: {<key>: {label_vi, unit, format, better: "higher"|"lower", group, help_vi}} (161 khoá), groups}
explain_tour  [{key, label_vi, notes_key, section}] (17 bước)
engine        {hash, commit, dirty, files}
books         {main|explore: {stored, current, needs_rebuild, reason, fix: {action, endpoint, body}}}
paths         {book, explore_book, registry, presets, alpha_user, cache_process, market, live}
version       hash 16 ký tự (ETag)
```

## Bước 4 — Một nguồn sự thật ở UI
- [ ] `src/meta/MetaProvider.jsx` + `useMeta()`: `getStudioMeta()` một lần, giữ `version`; làm mới khi tab focus và sau mọi POST/PUT (If-None-Match/ETag). Thay `context/Catalog.jsx` (catalog vẫn nạp kèm).
- [ ] `hooks/useAsync.js` → `useResource(key, fetcher, {poll})` + `invalidate(key)`; sau publish/build/promote/save: `invalidate('meta','catalog','alphas')`. Thay các `useEffect` fetch tự viết (Portfolio, AlphaCatalog, vault user alpha).
- [ ] Xoá hằng trùng → đọc meta:
  | Xoá | Thay bằng |
  |---|---|
  | `lib/funnel.js` STAGES, ALL_STAGES, STAGE_META, LEGACY_STAGE, METRICS (text luật cổng) | `meta.funnel.stages` (label/short/has_trades/legacy), `meta.funnel.gates` |
  | `lib/jobs.js` JOB_KIND | `meta.jobs.kinds` (label, persist_to, ephemeral) |
  | `lib/modes.js` WFA_STD, MC_STD, STRESS (+ text ngưỡng) | `meta.limits.*`, `meta.funnel.gates` |
  | `lib/params.js` PARAMS, PARAM_GROUPS | `params_schema` từ `/strategies` + `/strategies/catalog` |
  | `lib/stopfill.js`, `lib/runDefaults.js` | `/custom/defaults`, `params_schema` |
  | danh sách khung 15m/1h/4h (Backtest, Tune, NewRunForm, Studio) | `meta.frames.{custom_backtest,funnel,all}` |
  | nhãn/đơn vị/định dạng chỉ số (CustomResult, Dashboard, Funnel AlphaTable/AlphaDrawer, glossary) | `meta.metrics.defs[key]` → `label_vi`, `unit`, `format`, `better` (tô màu tốt/xấu theo `better`), `help_vi` cho tooltip |
  | thứ tự mục trong ResultTour / CustomResult | `meta.explain_tour` (5 bước, xem đặc tả Studio bên dưới) |
  | mục kết quả hiện ở education | ẩn mục trong `meta.education_hidden_sections` khi `mode=education` |
  | đường dẫn hiển thị cứng | `meta.paths.*` |
- [ ] **Đặc tả Studio (education / create)** — ⚠ người dùng đã giao trực tiếp cho phiên logic làm luôn (tour 5 bước, ẩn mục, rút gọn chú thích, tab đầu không nạp sẵn mẫu, nút Lưu thông minh hơn, bỏ chip kiểu "class X(SimpleAlgorithm)…", bỏ ô tìm + lọc danh mục/độ khó ở Mẫu). **Không sửa `components/alpha/studio/*` và khối CSS studio trong `styles/alpha.css` cho tới khi phiên logic báo xong**; mục dưới đây để đối chiếu khi nghiệm thu:
  - `meta.explain_tour` = 5 bước `[{key, label_vi, notes_key, section}]`: `summary` (Kết quả tổng) · `equity` (Đường vốn và sụt giảm) · `yearly` (Theo năm) · `by_symbol` (Theo tài sản) · `train_test` (Train và test). Tour lấy đúng danh sách này; chữ = `result.explain.notes[step.notes_key]` (khoá trơn, KHÔNG còn tiền tố `metrics.`); bước nào thiếu note thì bỏ qua; xoá mọi danh sách bước viết cứng.
  - `meta.education_hidden_sections` = `["benchmark", "holding", "pnl_structure"]`: chỉ ở `/education` không render 3 mục này (so sánh benchmark, thống kê thời gian giữ lệnh, khối cấu trúc PnL); `/alpha/create` vẫn hiện.
  - Ghi chú chỉ lấy từ `explain.notes` của CHÍNH lần chạy, không có chữ mặc định; bấm Chạy với code đã sửa → xoá kết quả + ghi chú cũ trước.
  - Mẫu không còn trường `position` (mọi tham số + vị thế/rủi ro là hằng của class trong code) → KHÔNG gửi `position` cấp mẫu kèm yêu cầu chạy (sẽ đè hằng đã sửa).
  - `explain.execution` (thẻ khớp lệnh) tính theo từng lần chạy → hiển thị nguyên, không có chữ dự phòng.
- [ ] `lib/format.js`: thêm `fmtMetric(key, value, defs)` dùng `format` của meta (pct2, …) — mọi ô số chỉ số đi qua hàm này.
- [ ] `ApiError`: đọc `detail.code` → thông điệp tiếng Việt: `EPHEMERAL_GONE` ("Kết quả tạm đã mất (API khởi động lại) — chạy lại"), `SHA_CONFLICT`, `LIVE_BOT_RUNNING`.
- [ ] `npm run api:check` (script node): so mọi hàm `api.js` với `/openapi.json` (path + method) → báo thiếu/thừa.
- [ ] Kiểm "UI chỉ format": `grep -rnE "reduce\(|Math\.(sqrt|pow|log)|mean|stdev|/ *100\b" src/pages src/components` → mỗi chỗ tính chỉ số/vốn/drawdown chuyển sang số từ API; đã biết: Dashboard fallback benchmark `'BTC'`, tính lại vốn/drawdown trong charts.
- Xong khi: không còn import từ các hằng đã xoá; nhãn/đơn vị mọi bảng khớp `meta.metrics.defs`; `api:check` sạch.

## Bước 5 — Màn hình
- [ ] `EngineWarning`: đọc `meta.books.{main,explore}`; hiện `reason`; nút gọi đúng `fix.endpoint` với `fix.body` (`action: funnel_book` → `POST /api/studio/funnel/runs/{id}/book`); cảnh báo nếu bot đang chạy dùng sổ đó (`meta.live` + `/live/bot`).
- [ ] `Live`: tab = `meta.live.modes × books` (paper→`live/paper`, demo→`live/testnet`, live→`live/live`, chỉ `books` cho phép); hiện `engine` + `dir` từ `/live/trades`; mode có `exec: true` + engine unified dùng `/live/compare_events`.
- [ ] Universe: Backtest / Funnel NewRunForm / Regime mặc định `meta.universe.data` (10), công tắc "theo sổ" = `meta.universe.book`.
- [ ] User alpha: lịch sử phiên bản (`getUserAlphaVersions`, `/user/{id}/versions/{v}`) + so sánh code; nút revalidate (`POST /api/studio/alphas/{id}/revalidate`).
- [ ] Sửa chữ đường dẫn cũ: `Tune.jsx` (← Alpha.jsx:86,190), `AlphaDrawer.jsx:156`, `jobs.js:94`, `CustomResult.jsx` ("result.json") → `meta.paths`.
- [ ] Funnel: cột/nút lệnh chỉ ở stage `has_trades`; nhãn tầng từ `meta.funnel.stages` (S2 `legacy` chỉ hiện ở run cũ).

## Bước 6 — Dữ liệu (quyết khi tới)
- [ ] Dựng lại sổ main / explore qua funnel_book (sau EngineWarning ở Bước 5): giữ universe 8 của run cũ hay chạy funnel mới cho 10 tài sản.

---

## Kiểm cuối (một lần)
- [ ] `npm run build` + `npm run api:check` sạch; không file mồ côi (đồ thị import).
- [ ] Backend: `NORA_LAYERING_STRICT=1` test_layering; test meta / fingerprint / unified trades / 410; full pytest với `NORA_GOLDEN_DATA_ROOT=$PWD/data/market/binance`.
- [ ] E2E headless (playwright): mỗi trang tải không lỗi; nhãn khớp meta; Live đủ tab; `/alpha/create` và `/education` chỉ khác ở comment chú thích + tour; mỗi trang lấy mẫu vài số trên màn hình so khớp response API.
- [ ] Commit theo nhóm (kiểm `git diff --cached --name-status` trước mỗi commit): backend-bỏ-endpoint · backend A3–A6 + meta · frontend cấu trúc · frontend meta/màn hình.

Đã xong, không làm lại: `/api/studio/meta` + ETag + `test_meta`; `meta.books` khối fix; gộp Studio (Mẫu / Kết quả, ResultTour, annotate); bỏ toàn bộ mock; thông báo "kết quả tạm đã mất"; `postAnnotate`.
