# P11 — Đồng bộ UI với backend + dữ liệu sau kiến trúc lại (plan + todo)

Nguồn: audit read-only 2026-10-08 (frontend/src vs backend/routes + data/, API :18010). Kiến trúc tham chiếu: `p9_architecture_final.md`, `p10_alpha_contract.md`.

## 1. Vấn đề gốc

UI đang tự giữ một bản "sự thật" song song với backend: danh sách bước funnel + nhãn + ngưỡng cổng, khung thời gian, mode/venue/engine bot, loại job, universe, giới hạn tham số, đường dẫn file trong chữ hiển thị. Khi backend đổi (P9/P10) thì bản sao trong UI lệch → sai nhãn, sai hướng dẫn, thiếu tính năng, đọc nhầm nguồn.

Top lệch (ảnh hưởng lớn nhất):
1. Banner "cần dựng lại sổ" chỉ sai cách sửa: sổ đến từ funnel → phải dùng `POST /funnel/runs/{id}/book` (UI chưa có), không phải book_build/publish (dựng sổ khác, universe 8 cứng).
2. Live demo (engine unified) mù: `UnifiedBot` không ghi `state.trades`; UI dùng `/live/compare` (0 khớp) thay vì `/live/compare_events`.
3. Universe hiển thị 8 tài sản (theo sổ) trong khi kho dữ liệu có 10 (LINK, TRX) — lan sang Backtest/Funnel/Regime/Live.
4. `needs_rebuild` không bật khi sửa strategy hệ thống (strategies/*.py không nằm trong fingerprint) nhưng lại bật vì đổi hằng số/code trợ lý.
5. Nhãn bước funnel 3 nguồn khác nhau (UI `STAGE_META`, backend `STAGE_LABELS`, cache stats cũ).
6. Live tab cứng (paper/main, demo/main, paper/explore), không có mode live, không thấy engine.
7. Đường dẫn cũ trong chữ hiển thị (`alphas/book.json`, `data/alphas/registry.json`, `progress.py`, "result.json" cho custom).
8. Custom backtest giờ là kết quả tạm trong RAM → sau restart API UI báo lỗi chung, không nói "kết quả tạm đã mất, chạy lại".
9. Tính năng P10 nửa vời: lịch sử phiên bản user alpha, revalidate alpha chưa có UI.
10. 3–4 chỗ fetch tự viết (useEffect) cạnh `useAsync`; không làm mới catalog sau publish.

## 2. Kiến trúc UI chuẩn (đề xuất)

Nguyên tắc: **backend là nguồn sự thật duy nhất cho mọi tri thức nghiệp vụ; UI chỉ trình bày + điều hướng.**

### 2.1 Một endpoint "meta" duy nhất
`GET /api/studio/meta` (routes/meta.py, đọc từ các nguồn gốc, không định nghĩa lại):
- `funnel`: stages [{id, label, short, has_trades, legacy}] + gates [{key, label, value, unit, stage}] ← `optimize/funnel/stages.py`, `carlo.py`
- `frames`, `frames_allowed` ← `core/params.FRAME_MS`
- `live`: modes [{mode, dir, label, engines, default_engine, books}], venues ← `crawl/store.live_state_key`, `live/live.py`
- `jobs`: kinds [{kind, label, persist_to, ephemeral}] ← `optimize/process/process.KINDS`
- `universe`: {data: [10 tài sản theo sàn/market], book: [...], explore: [...]} ← `crawl/store.list_assets` + book
- `limits`: giới hạn tham số form (WFA n, build n, MC sims…) ← pydantic models của routes
- `engine`: {version, commit, dirty, files} + `books`: {main, explore: {needs_rebuild, reason, source, fix: {action, endpoint, params}}} ← `registry.book_engine_status`
- `paths`: nhãn đường dẫn hiển thị (`data/alpha/book.json` …) ← `crawl/store` helpers
- `version`: hash nội dung meta (UI cache theo ETag)

### 2.2 Frontend
- `MetaProvider` (thay CatalogProvider mở rộng): tải `/meta` 1 lần + revalidate theo ETag khi focus / sau mutation; mọi hằng nghiệp vụ trong `lib/funnel.js`, `lib/modes.js`, `lib/jobs.js`, Live tabs, frames… đọc từ meta (giữ fallback tối thiểu khi API lỗi).
- Một lớp dữ liệu: `useResource(key, fetcher, {poll, invalidateOn})` + `invalidate(key)` sau POST/PUT (publish → invalidate `meta`, `catalog`, `alphas`). Bỏ useEffect tự viết.
- `api.js` = đúng 1 hàm/route; tên theo route; JSDoc type từ OpenAPI (`/openapi.json`) — script `npm run api:check` so api.js với OpenAPI để phát hiện route mất/đổi.
- Lỗi chuẩn: `ApiError.code` từ backend (`EPHEMERAL_GONE`, `SHA_CONFLICT`, `LIVE_BOT_RUNNING`, …) → thông điệp tiếng Việt theo code.

### 2.3 Backend hỗ trợ
- Fingerprint `needs_rebuild`: thêm `data/alpha/strategies/*.py` (+ nội dung DSL đã biên dịch: `code_hash`), loại hằng/code trợ lý không ảnh hưởng kết quả (chỉ băm phần engine thật: dùng danh sách hàm/ module tính toán hoặc băm IR + kernel); sửa `REASON` text tự sinh từ danh sách file.
- `UnifiedBot` ghi trade khi đóng (`_record_close`) → `/live/trades` đúng cho demo; `/live/trades` trả `engine`, `dir`.
- Funnel stats cache: invalidate khi `STAGE_LABELS` đổi (key gồm meta version).
- custom_backtest hết hạn → 410 `EPHEMERAL_GONE`.
- Job label backend dùng `paths` mới (`data/alpha/book.json`).

## 3. TODO (theo thứ tự làm)

### Phase A — Backend nguồn sự thật (logic)
- [ ] A1 `routes/meta.py` + `GET /api/studio/meta` (+ETag) tổng hợp từ các nguồn gốc (mục 2.1); test schema.
- [ ] A2 `book_engine_status`: thêm `fix` {action: "funnel_book" | "book_build", endpoint, params gợi ý: run_id, alpha_ids, risk, wfa_job_id}; reason text sinh từ ENGINE_FILES.
- [ ] A3 Fingerprint: thêm strategies/*.py (code_hash), bỏ ảnh hưởng của code trợ lý/hằng đường dẫn (tách phần trợ lý khỏi phần băm hoặc băm theo IR+kernel); test.
- [ ] A4 `UnifiedBot._record_close` → state.trades; `/live/trades` + `/live/compare` trả `engine`, `dir`; compare tự dùng event-path khi engine=unified.
- [ ] A5 410 `EPHEMERAL_GONE` cho custom_backtest đã mất; save user alpha báo rõ.
- [ ] A6 Funnel stats cache key gồm meta version; job label đường mới.

### Phase B — Frontend nền
- [ ] B1 `MetaProvider` + `useMeta()`; `useResource` + `invalidate`; thay 3–4 useEffect tự viết (Portfolio, AlphaVault, Catalog).
- [ ] B2 Xoá hằng nghiệp vụ trùng: lib/funnel.js (stages, gates), lib/modes.js (WFA/MC/STRESS), lib/jobs.js (kinds), Live tabs, frames trong Backtest/Alpha/NewRunForm, giới hạn form → đọc meta.
- [ ] B3 `ApiError.code` → thông điệp; script `api:check` (OpenAPI vs api.js).

### Phase C — Màn hình
- [ ] C1 EngineWarning: hiển thị lý do + nút đúng `fix` (funnel_book: chọn WFA → `POST /funnel/runs/{id}/book`; cảnh báo bot đang chạy dùng sổ). Thêm wrapper `postFunnelBook`.
- [ ] C2 Live: tab sinh từ meta (paper/testnet/live × book), hiện engine + thư mục; demo/live unified dùng `/live/compare_events`.
- [ ] C3 Universe: Backtest/Funnel/Regime mặc định = universe dữ liệu (10) với nhãn "theo sổ" vs "theo kho".
- [ ] C4 User alpha: lịch sử phiên bản (list/xem/so sánh), nút revalidate alpha (vault).
- [ ] C5 Sửa chữ/đường dẫn cũ (Alpha.jsx:86,190; AlphaDrawer.jsx:156; jobs.js:94; api.js:264; CustomResult.jsx:158; "Đủ điều kiện testnet" → "Đủ điều kiện demo OKX").
- [ ] C6 Funnel: `stageHasTrades` theo meta (S4 không có trades); dùng label từ meta.

### Phase D — Dữ liệu + vận hành
- [ ] D1 Dựng lại sổ main/explore qua funnel_book (sau C1) — quyết: giữ universe 8 của run cũ hay chạy funnel mới cho 10 tài sản. Lưu ý: publish thay sổ bot đang dùng → dừng/khởi động bot theo quy trình.
- [ ] D2 (tuỳ chọn) trang "Dữ liệu": `/api/data/*` coverage, crawl, promote.

### Phase E — Kiểm
- [ ] E1 Test backend: meta schema, fingerprint, unified trades, 410.
- [ ] E2 E2E headless (playwright): mỗi trang tải không lỗi, nhãn khớp meta, banner → nút fix chạy được (mock POST), Live tabs đủ.
- [ ] E3 `npm run build` + `api:check` sạch.

## 4. Phân vai
- Phiên logic + dữ liệu: Phase A, D, E1.
- Frontend (worker Sonnet/medium hoặc anh): Phase B, C, E2–E3.
- Phiên kiến trúc: duyệt `routes/meta.py` (vị trí, không định nghĩa lại hằng — chỉ đọc từ nguồn gốc) + cập nhật `p9_architecture_final.md`.
