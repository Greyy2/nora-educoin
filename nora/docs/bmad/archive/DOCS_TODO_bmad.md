# TODO tài liệu Nora theo BMAD + cách dùng BMAD thực tế (2026-10-09)

Người triển khai: anh. BMAD đã cài sẵn trong repo: **BMAD v6.12** ở `/home/vmc03/norabt/.agent/` (`_bmad/` cấu hình + 29 skill `bmad-*` trong `.agent/skills/`), dùng từ agent của anh (Antigravity / công cụ đọc `.agent/skills`). File này sẽ chuyển vào `archive/` khi xong.

---

## 0. Hiện trạng (vì sao phải làm)

- Cấu hình BMAD trỏ SAI chỗ: `planning_artifacts = {project-root}/_bmad-output/planning-artifacts`, `implementation_artifacts = {project-root}/_bmad-output/implementation-artifacts`, `project_knowledge = {project-root}/docs` → `norabt/docs` không tồn tại; tài liệu thật ở `nora/docs/bmad/` được viết tay, các skill BMAD không thấy.
- `nora/docs/bmad/README.md` định nghĩa sai BMAD ("Business, Model, Architecture, Delivery"); BMAD = *Breakthrough Method for Agile AI-Driven Development*.
- Lỗi thời: `architecture.md` ~50 chỗ đường cũ (`core/execute`, `api/`, `_cache`, `data/alphas`, `optimize_alphas`), `prd.md` ~15, `docs/README.md` ~13; baseline ghi `dc08366` (03/10).
- 3 nguồn trạng thái chồng nhau: `roadmap.md` ("nguồn duy nhất", P0–P12), `epics.md` (E1–E16), `sprint-status.yaml`. P9–P12 (tái cấu trúc, alpha contract, UI sync, signal timing) chưa có epic/story.
- 14 file kế hoạch rời (`p6_…`→`p12_…`, `adr-*`, `p9_review_log`, `p10_handover_logic`, `p11_*`, `p12_*`) = thực chất là spec/epic/story/kiến trúc chưa vào đúng chỗ.
- Story (94 file) thiếu khối **Story** (Là… tôi muốn… để…), **Dev Agent Record**, **QA Results**.
- Thiếu UX spec, Project Brief, AGENTS.md (project context). Tài liệu chuyên đề nằm rời: `ui_contract`, `funnel_contract`, `data_layout`, `metrics_inventory`, `signals_strategies`, `alpha_pipeline`.
- README: `norabt/README.md` (tiếng Anh, "NoraBT"), `nora/docs/README.md` ("Hiện trạng 01/10"); `nora/README.md` chưa có.
- `_bmad-output/` đã có kết quả cũ: `forge/norabt-discovery-risk`, `specs/spec-portfolio-correlation`, `planning-artifacts/research/market-okx-…` — giữ, chuyển vào nơi mới ở bước 1.

---

## 1. Cấu hình BMAD trỏ vào tài liệu thật (làm đầu tiên)

Không sửa `_bmad/config.toml` (installer ghi đè). Ghi đè ở `/home/vmc03/norabt/.agent/_bmad/custom/config.toml`:
```toml
[core]
project_name = "nora"
document_output_language = "Tiếng Việt"
communication_language = "Vietnamese"
output_folder = "nora/docs/bmad"

[modules.bmm]
planning_artifacts = "{project-root}/nora/docs/bmad"
implementation_artifacts = "{project-root}/nora/docs/bmad"
project_knowledge = "{project-root}/nora/docs"
```
- [ ] Ghi file trên (kiểm `{project-root}` = `/home/vmc03/norabt`: chạy `bmad-help` và xem đường nó báo).
- [ ] Chuyển `_bmad-output/{forge,specs,planning-artifacts/research}` → `nora/docs/bmad/research/` (giữ nguyên tên thư mục con).
- [ ] Chạy skill **`bmad-project-context`** (chế độ adopt) → tạo `AGENTS.md` ở `nora/` gồm luật thép (mục 3.2 `coding-standards`) để mọi agent đọc trước khi làm.

## 2. Cây tài liệu đích (khớp tên file mặc định của skill BMAD v6)

```
nora/
  README.md                         MỚI — Nora là gì · chạy nhanh · cây thư mục · link docs
  AGENTS.md                         MỚI — do bmad-project-context sinh (luật cho agent)
  docs/
    README.md                       chỉ là mục lục → bmad/, knowledge_base/
    knowledge_base/                 giữ (lý thuyết + luật của boss); được trỏ từ architecture
    bmad/                           = planning_artifacts = implementation_artifacts
      product-brief.md              (bmad-product-brief)      ← knowledge_base/01 + prd §1–3
      prd.md                        (bmad-prd)                Goals · Background · FR1… · NFR1… · UI goals · Technical assumptions · Epic list
      ux-design.md                  (bmad-ux)                 sơ đồ trang · luồng · MetaProvider · responsive · "UI chỉ format"
      architecture.md               (bmad-architecture)       quyết định + spine; chi tiết ở architecture/
      architecture/
        source-tree.md              ← p9_architecture_final.md (cây backend / data / frontend, 1 dòng mỗi file)
        components.md               alpha → core engine → optimize (search, funnel, book, process) → live (paper, testnet, live) → routes
        data-models.md              ← data_layout.md + vòng đời cache + metadata trong pkl
        api-spec.md                 ← ui_contract + funnel_contract + /api/studio/meta
        engine-spec.md              ← architecture.md §4–7 cũ (O→H→L→C, 2 pha, phí/trượt/funding, sizing, WFA, MC) + metrics_inventory + signals_strategies + alpha_pipeline
        coding-standards.md         luật thép (mục 3.2)
        test-strategy.md            golden bit-identical · kernel parity · Nautilus 332/332 · p9_ledger --dups · layering strict · E2E playwright
        decisions/                  ADR-P6-unified-execution.md · ADR-P9-backend-layout.md · ADR-P10-alpha-contract.md
      epics.md                      (bmad-create-epics-and-stories) danh sách epic + story + AC mức epic
      sprint-status.yaml            (bmad-sprint-planning) NGUỒN TRẠNG THÁI DUY NHẤT
      stories/                      mỗi story một file, mẫu ở mục 3.1
      research/                     ← _bmad-output cũ + docs/research/
      archive/                      roadmap.md · p6…p12 · p9_review_log · p10_handover · p11_* · playbook_p1_p5 · legacy/ · DOCS_TODO_bmad.md (khi xong)
```

## 3. Nội dung chuẩn

### 3.1 Mẫu story (mọi story mới + 94 story cũ)
```markdown
# Story E17.3: <tên>
## Status
Draft | Approved | InProgress | Review | Done
## Story
**Là** <vai> **tôi muốn** <việc> **để** <giá trị>
## Acceptance Criteria
1. <đo được: test / số / lệnh kiểm>
## Tasks / Subtasks
- [ ] Task 1 (AC: 1)
  - [ ] subtask
## Dev Notes
Nguồn: architecture/<file>.md#… · file sửa · ràng buộc (coding-standards)
### Testing
lệnh chạy (ops/run_limited.sh …), test chứng minh
## Change Log
| Ngày | Phiên bản | Mô tả | Người |
## Dev Agent Record
Agent model · Debug log · Completion notes · File list
## QA Results
Gate: PASS | CONCERNS | FAIL · bằng chứng: commit, test, số đo (nguồn trong repo)
```
Map trạng thái cũ → mới: `backlog`→Draft, `ready`→Approved, `in-progress`→InProgress, `review`→Review, `done`→Done. Mục **Evidence** cũ → chia vào *Dev Agent Record / File list* + *QA Results*.

### 3.2 `coding-standards.md` (luật thép — nguồn: các quyết định đã chốt)
- Một engine (`core/backtest.py`) cho backtest/paper/testnet/live; nhanh hơn = tối ưu trong `optimize/`.
- Mỗi logic một định nghĩa; gate `p9_ledger --dups` = 0.
- Phân tầng: `core` → `alpha`/`metrics`/`regime`/`wfa`/`carlo` → `crawl` → `optimize` → `live`/`routes`; `core` không I/O; `metrics` chỉ tính thuần; `test_layering` strict = 0.
- Chiến lược: Strategy Contract (`alpha/contract.py`) → IR (`core/signal.py`); RUN | ADAPT | REJECT, không đoán.
- Dữ liệu: `data/{market/<sàn>/{cex,dex}, alpha, backtest, wfa, carlo, live/{paper,testnet,live}, cache/{process,shared}}`; dữ liệu thị trường chỉ `.pkl` (metadata trong attrs); cache chỉ giữ tiến trình đang chạy / dở dang.
- Chạy Python chỉ qua `ops/run_limited.sh` (nora.slice 12G); job chỉ qua API runner; script ở `test/scripts/`.
- UI: backend là nguồn sự thật (`/api/studio/meta`); UI chỉ trình bày + format.
- Golden bit-identical; lệch thì sửa code, không nới test. Khoá OKX chỉ qua `~/.config/nora/okx.env`; live cần `confirm_live`.
- Không mock trong backtest/WFA/MC.

### 3.3 Epic mới (việc đã làm sau 03/10 — viết story với bằng chứng thật)
| Epic | Nội dung | Nguồn để viết story |
|---|---|---|
| E17 Tái cấu trúc backend + dữ liệu | P9.0–P9.10, data tree, pkl-only, cache lifecycle, routes 5 file, optimize 9 file | `adr-p9-backend-layout.md`, `p9_architecture_final.md`, `p9_review_log.md`, `p11_plan_routes_and_logic.md` §A, D |
| E18 Alpha contract + trình soạn | P10: contract, adapters, assist, sửa chiến lược tại chỗ, education annotate | `p10_alpha_contract.md`, `p10_handover_logic.md`, `p11b_studio_view_plan.md` |
| E19 UI một nguồn sự thật | meta, MetaProvider, bỏ mock, cấu trúc frontend, responsive | `p11_ui_sync_plan.md`, `p11_ui_todo_final.md`, `p11_plan_routes_and_logic.md` §E |
| E20 Signal timing | P12 | `p12_signal_timing_plan.md` |
Đồng thời: đóng E16 (P6 + P9.4b single engine), cập nhật trạng thái E8/E9.

---

## 4. TODO (làm lần lượt; mỗi bước dùng skill BMAD tương ứng)

| # | Việc | Skill BMAD | Xong khi |
|---|---|---|---|
| 1 | Cấu hình `custom/config.toml` + chuyển `_bmad-output` (mục 1) | `bmad-help` (kiểm đường) | `bmad-help` báo planning/implementation = `nora/docs/bmad` |
| 2 | `AGENTS.md` cho `nora/` | `bmad-project-context` (adopt) | file có luật mục 3.2 |
| 3 | `architecture/source-tree.md`, `data-models.md`, `components.md`, `coding-standards.md`, `test-strategy.md`, `decisions/*` | `bmad-architecture` (chế độ *from existing codebase* / update) | mọi đường dẫn trong docs tồn tại; 0 tên module cũ |
| 4 | `architecture/engine-spec.md`, `api-spec.md` (gộp tài liệu chuyên đề) | `bmad-architecture` | `ui_contract`, `funnel_contract`, `data_layout`, `metrics_inventory`, `signals_strategies`, `alpha_pipeline` → archive |
| 5 | `architecture.md` = spine + mục lục `architecture/` | `bmad-architecture` (validate) | skill validate PASS |
| 6 | `product-brief.md` | `bmad-product-brief` | — |
| 7 | `prd.md` cập nhật: FR/NFR đánh số, khớp hiện tại (OKX 10 tài sản, data tree, live paper/testnet/live, alpha contract, studio/education, cache), Epic list E1–E20 | `bmad-prd` (update + validate) | validate PASS; mỗi FR trỏ epic |
| 8 | `ux-design.md` | `bmad-ux` | trang, luồng, quy tắc UI khớp app hiện tại |
| 9 | `epics.md` E1–E20 + story cho E17–E20 | `bmad-create-epics-and-stories` | mọi việc P9–P12 có story với QA Results thật |
| 10 | Chuẩn hoá 94 story cũ sang mẫu 3.1 | script (test/scripts/bmad_story_migrate.py) hoặc `bmad-spec` (update) | mọi story có 9 mục; Evidence không mất |
| 11 | `sprint-status.yaml` sinh lại từ epics | `bmad-sprint-planning` (sprint-planning / validate) | validate PASS; `roadmap.md` → archive |
| 12 | Archive: roadmap, p6…p12, review log, handover, playbook, legacy | — | `bmad/` gốc chỉ còn file của mục 2 |
| 13 | README: `nora/README.md` mới; `norabt/README.md` trỏ `nora/`; `docs/README.md` = mục lục | — | lệnh chạy trong README chạy được |
| 14 | Kiểm nhất quán (script `test/scripts/check_docs.py`): story ↔ sprint-status; mọi đường dẫn file tồn tại; không còn tên module cũ (dùng bảng OLD_MODULES / `p9_ledger` OLD_HOME); không link hỏng | — | script 0 lỗi |
| 15 | Retrospective E16 + E17 | `bmad-retrospective` | file retro trong `bmad/` |

---

## 5. Dùng BMAD thực tế hằng ngày (sau khi xong mục 4)

Gọi skill bằng tên trong agent đọc `.agent/skills` (vd. "run bmad-help", "create the architecture", "run sprint planning"). Không chắc bước tiếp: **`bmad-help`** đọc trạng thái và gợi ý skill.

**Vai (agent persona):** Mary `bmad-agent-analyst` (nghiên cứu, brief) · John `bmad-agent-pm` (PRD, epic) · `bmad-agent-ux-designer` (UX) · `bmad-agent-architect` (kiến trúc) · Amelia `bmad-agent-dev` (code story). Họp nhiều vai: `bmad-party-mode`.

### Vòng đời một tính năng / thay đổi
```
ý tưởng ─► (bmad-brainstorming | bmad-forge-idea | bmad-deep-recon)  nghiên cứu, khi cần
        ─► bmad-spec              gói ý tưởng thành SPEC.md ngắn (có thể tách thành story)
        ─► bmad-prd (update)      thêm FR/NFR + epic vào prd.md
        ─► bmad-architecture      nếu đụng cấu trúc: cập nhật architecture/ + decisions/ADR
        ─► bmad-ux                nếu đụng màn hình
        ─► bmad-create-epics-and-stories   story mới (Status: Draft → Approved khi anh duyệt AC)
        ─► bmad-sprint-planning   readiness gate + cập nhật sprint-status.yaml
        ─► bmad-build             dev làm 1 story: code + test + verify, điền Dev Agent Record (InProgress → Review)
        ─► bmad-code-review       review song song nhiều reviewer → sửa
        ─► bmad-review / QA       điền QA Results (gate PASS/CONCERNS/FAIL + bằng chứng) → Done
        ─► bmad-qa-generate-e2e-tests   khi story đụng UI
        ─► bmad-retrospective     khi xong một epic
```
- Thay đổi lớn giữa chừng (như P9 tái cấu trúc): **`bmad-correct-course`** → bản đề xuất thay đổi sprint, cập nhật PRD/epic/architecture/UX một lượt thay vì viết file kế hoạch rời `pXX_*.md`.
- Giải thích một thay đổi cho người review: `bmad-walkthrough`.
- Luật dự án cho agent: sửa `AGENTS.md` qua `bmad-project-context` (có mục ghi lỗi agent hay mắc).

### Quy tắc giữ docs sạch
1. Không tạo file kế hoạch rời (`pXX_plan.md`) — kế hoạch = story trong `stories/` + trạng thái trong `sprint-status.yaml`.
2. Quyết định kiến trúc = một ADR trong `architecture/decisions/`; mô tả hiện trạng = `architecture/*`; không chép lại ở nhiều nơi.
3. Story chỉ `Done` khi QA Results có commit + test + số đo; không nới gate để đạt.
4. Mỗi lần đổi cấu trúc code: cập nhật `architecture/source-tree.md` trong cùng commit; chạy `check_docs.py`.
5. Nhiều phiên AI làm song song: mỗi phiên nhận story riêng (`InProgress` + tên phiên trong Dev Agent Record) → không hai phiên sửa cùng story/file.
