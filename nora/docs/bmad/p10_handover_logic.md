# Bàn giao phiên logic + dữ liệu ("alpha và backtest analyst") — 2026-10-08

Kiến trúc tham chiếu: `docs/bmad/p9_architecture_final.md` (phiên kiến trúc). Hợp đồng chiến lược: `docs/bmad/p10_alpha_contract.md`.
Chưa commit gì (cây làm việc nhánh `fix/pipeline-audit`). Chạy Python qua `ops/run_limited.sh --no-lock -- ...`.

## 1. Đã xong (đã kiểm)

| Mảng | Kết quả | Kiểm |
|---|---|---|
| Engine | core thuần (không I/O, không import ngoài core); nguồn dữ liệu tiêm vào (`core/models.DataSource`, `EngineData` ở `optimize/search/evaluate.py`); regime classifier trong `core/signal`; `signal_snapshot`/`check_signals`/`evaluate_signals` trong `core/backtest` | golden bit-identical; Nautilus check_baseline 332/332 |
| Dữ liệu | metadata trong `attrs["nora"]` của pkl/parquet (bỏ manifest.json/dex_pool.json); `binance_hist` gộp vào `market/binance/cex` (spot, 2019→); cây `data/{alpha,backtest,wfa,live,market,cache}` | migrate 28/28; read_manifest/pool_info trước=sau trên 23 tài sản |
| Live | `live/{live,testnet,paper}.py`; `data/live/{paper,testnet}/<sàn>_<sổ>`; 3 bot chạy lại, pickle cũ nạp được; tab demo đọc đúng engine | bot start OK 08:08 |
| Cache | chỉ job đang chạy; xong → lưu về data/ + xoá; lỗi/huỷ giữ 7 ngày; custom_backtest giữ trong RAM API (64), không ghi đĩa; thư mục mồ côi tự dọn | test_job_lifecycle |
| Funnel | S2_antiluck gộp: lân cận + PBO trong S3_wfa, DSR trong S4_montecarlo (S4 kết luận); tham số S2_* giữ nguyên; run cũ có S2 vẫn đọc | test_funnel |
| Dọn rác | code chết xoá, ~20 nhóm trùng gộp 1 định nghĩa, comment đường cũ sửa | p9_ledger --dups = 0; layering strict 0 vi phạm |
| alpha/ | `contract.py` (hợp đồng Strategy, catalog, check RUN/ADAPT/REJECT, complete/hover) + `compile.py` (compiler, adapter registry: function/JSON/AI-python, loader + sửa tại chỗ + backup + nạp lại); user alpha lưu phiên bản (`alpha_id`) | test_alpha_contract 29 pass; API thật trả lời catalog/check/source sau restart 08:53 |
| Frontend | CodeMirror 6 + trợ lý fintech (gợi ý, hover, lint, chip RUN/ADAPT/REJECT), sửa strategy hệ thống, "Mở để sửa" user alpha | build dist OK; thử trên mock |

## 1b. Test tổng (4 nhóm song song, golden data/market/binance + layering strict) — XONG

- Tổng: 1.345 pass, 10 skip, 4 fail → cả 4 là lỗi fixture test, không phải logic:
  - 3 test: fixture đặt NORA_JOB_DIR vào thư mục chưa tạo (writer cố ý không tự tạo thư mục — bot bị huỷ không tạo lại thư mục job). Sửa 7 file test (os.makedirs trước setenv).
  - test_scale_pipeline::test_build_request_accepts_large_n_and_new_flags: đọc FakePopen của test_book_api trong khi fixture client (từ test_book_ui_backend) vá Popen bằng FakePopen riêng → đổi import.
- Chạy lại các test đã sửa: 28/28 pass (+ test_job_lifecycle 10/10, test_scale_pipeline 44/45 trước sửa → test còn lại pass sau sửa).
- Log: `/tmp/claude-1000/-home-vmc03-norabt/1e443e8b-0398-49c0-8399-bb0220f086fc/scratchpad/gate/out{0..3}.log`.

## 2. Đang dở (lúc bàn giao)

- 3 file thừa đã gộp vào `alpha/{compile,contract}.py`; kiến trúc đã CHỐT (norabt-fc). Test tổng xong (mục 1b).
- API thật (sau restart 08:53): catalog/check/complete/hover/source trả lời đúng; PUT `kema` không đổi nội dung đã chạy 08:58 (file giống hệt bản sao lưu `data/cache/process/_strategy_backup/`). Chưa thử trên UI thật: trình soạn mới + lưu phiên bản user alpha.

## 3. TODO để chốt (anh tự làm được)

1. (Tuỳ chọn) chạy lại test sau khi anh sửa gì thêm: `NORA_GOLDEN_DATA_ROOT=$PWD/data/market/binance ops/run_limited.sh --no-lock -- -m pytest -q test/<file>.py` (`test_scale_pipeline::...sigterm...` có thể chập chờn).
2. Kiểm UI: `/alpha/create` gõ code → chip RUN; sửa sai tên chỉ báo → REJECT + "Sửa thành"; chạy backtest → Lưu → "Mở để sửa" → lưu v2.
3. Catalog alpha → "</> Mã nguồn" → chỉ bấm "Kiểm tra" (KHÔNG "Lưu" khi bot đang chạy — file đó bot đang dùng).
4. Sau restart API: mọi book hiện `needs_rebuild` (engine_version đổi) → dựng lại book khi cần.
5. Commit (khi anh muốn): kiểm `git diff --cached --name-status`, commit theo nhóm (engine / data / live / funnel / alpha / frontend).

## 4. Trao đổi với phiên kiến trúc (norabt-fc / "nautilus trader backtest")

- Báo: 3 file thừa đã gộp — `backend/alpha/` = `compile.py`, `contract.py` (+`__init__`); `optimize/book/` = `build.py`, `registry.py`. Nhờ rà cây lần cuối + cập nhật `p9_architecture_final.md` (thêm alpha/ API p10).
- ĐÃ XONG (norabt-fc, kiến trúc CHỐT): cây khớp ADR §2; `NORA_DIR`/`DATA_DIR` định nghĩa một lần ở `core/models.py` (crawl/store, alpha/compile, optimize/process import); `p9_architecture_final.md` đã cập nhật alpha/P10. engine_version đổi thêm một lần (book vốn đã cần dựng lại).

## 5. Việc logic để sau (cần anh quyết thời điểm)

- P9.4b T8–T11: bot paper/demo chạy hẳn trên kernel, xoá đoạn LEGACY ~1.600 dòng trong `core/backtest.py` + ~25 hàm `position_size` (đang được bot legacy dùng).
- Trùng cố ý chưa gộp vì đổi số: Sharpe inline trong `portfolio_metrics`, `charts._num` (+0.0), `registry/build._num`.
- `normalized_code` (Chuẩn hoá code) mất comment do `ast.unparse`.
- Chặn sửa strategy khi có bot live đang chạy hiện chặn mọi bot, chưa lọc theo strategy bot dùng.
- 2 user alpha thử nghiệm `29b85425e324`, `4d4ef78d5b96` (đã archive) còn file trong `data/alpha/user/` — xoá tay nếu không cần.
- `data/live/testnet/okx_main_legacy` = trạng thái demo legacy cũ (06/10), giữ lại; bỏ nếu không cần.
