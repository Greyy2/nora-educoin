# Nora: Crypto Perpetuals Quantitative Research & Execution Pipeline

Nora là pipeline nghiên cứu và kiểm chứng chiến lược định lượng crypto perp, được thiết kế theo nguyên tắc strictly causal, tái lập bit-identical, và tích hợp một Core Execution Engine duy nhất xuyên suốt từ backtest, WFA, Monte Carlo cho tới Paper và Live trading.

---

## 1. Khởi động nhanh (Quick Start)

### 1.1 Khởi động toàn bộ hệ thống (API + Frontend)
```bash
cd /home/vmc03/norabt/nora
./start.sh
```
- **FastAPI Backend:** Chạy tại `http://localhost:18010` (Endpoint metadata: `GET /api/studio/meta`).
- **React Frontend UI:** Chạy tại `http://localhost:15173`.
- Dừng hệ thống: `./stop.sh`.

### 1.2 Chạy các tác vụ nặng an toàn trong Cgroup Slice
Mọi tác vụ nặng (Backtest lớn, WFA, Quét tối ưu phễu) đều bắt buộc chạy qua `ops/run_limited.sh` để đảm bảo không tràn RAM (trần 12 GB trong `nora.slice`):
```bash
# Chạy job backtest / benchmark trong cgroup slice
./ops/run_limited.sh python -m backend.optimize.funnel.run --help
```

---

## 2. Cây thư mục cấp cao

```text
nora/
├── backend/                  # 5 phân tầng sạch sẽ: alpha -> core -> optimize -> live -> routes
│   ├── alpha/                # BaseStrategy contract, validator, và 50+ strategies
│   ├── core/                 # Pure domain logic: engine khớp nến 1m 2 pha, CapitalLedger, indicators
│   ├── optimize/             # Funnel S0-FINAL, WFA, Monte Carlo, Strategy Book builder
│   ├── live/                 # Thực thi: paper/, testnet/, live/ (OKX perp)
│   └── routes/               # FastAPI endpoints (/api/studio/meta, book, live, v.v.)
├── data/
│   ├── market/               # Cây dữ liệu một nguồn duy nhất: <venue>/<market>/<symbol>/<timeframe>.pkl
│   └── alphas/               # registry.json và book.json (được version kiểm soát)
├── frontend/                 # Single-Page App (React 18, Vite, MetaProvider, Dark Theme)
├── ops/                      # Quản trị cgroups: run_limited.sh, nora.slice, systemd units
├── test/                     # Golden bit-identical harness, Nautilus 332/332 parity, unit tests
└── docs/                     # Toàn bộ tài liệu kỹ thuật chuẩn BMAD (xem docs/bmad/)
```

---

## 3. Hệ thống Tài liệu (Documentation)

Dự án áp dụng phương pháp phát triển Agile hướng AI **BMAD (Breakthrough Method for Agile AI-Driven Development)**:

- 📋 [Project Brief](docs/bmad/product-brief.md): Vấn đề, tầm nhìn, người dùng mục tiêu và chỉ số thành công.
- 🎯 [PRD v2.0](docs/bmad/prd.md): Yêu cầu chức năng (FR1–FR41), NFR, ràng buộc và danh sách Epics E1–E20.
- 🏛️ [Kiến trúc Spine](docs/bmad/architecture.md): Tổng quan kiến trúc 5 phân tầng và các quyết định cốt lõi.
  - 🌳 [Cây mã nguồn chi tiết](docs/bmad/architecture/source-tree.md): 1 dòng cho mỗi file trong hệ thống.
  - 📏 [Coding Standards](docs/bmad/architecture/coding-standards.md): 9 luật thép kiến trúc bất biến.
  - 🧩 [Components & Dataflow](docs/bmad/architecture/components.md): Sơ đồ luồng dữ liệu end-to-end.
  - 💾 [Data Models](docs/bmad/architecture/data-models.md): Định dạng nến, attrs metadata và cache lifecycle.
  - 🔌 [API Specification](docs/bmad/architecture/api-spec.md): Hợp đồng `/api/studio/meta` và routers.
  - ⚙️ [Engine Specification](docs/bmad/architecture/engine-spec.md): Khớp lệnh 2 pha, O-H-L-C bi quan, phí, funding.
  - 🧪 [Test Strategy](docs/bmad/architecture/test-strategy.md): Golden test, Nautilus parity, causal guards.
- 🎨 [Frontend & UX Spec](docs/bmad/ux-design.md): Sơ đồ màn hình, MetaProvider, responsive và formatting.
- 📊 [Epics & Stories](docs/bmad/epics.md): 20 Epics, 109 stories chuẩn BMAD.
- 🚦 [Sprint Status](docs/bmad/sprint-status.yaml): Nguồn trạng thái máy đọc duy nhất của toàn bộ sprint.
- 📜 [Agent Instructions](AGENTS.md): Quy tắc thép dành cho lập trình viên và AI agent.
