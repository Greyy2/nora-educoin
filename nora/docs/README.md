# HỆ THỐNG TÀI LIỆU DỰ ÁN NORA (BMAD & KNOWLEDGE BASE)

## Cấu trúc thư mục

```text
nora/
├── backend/
│   ├── main.py            # App FastAPI (uvicorn backend.main:app)
│   ├── api/               # routers/, schemas.py, control.py (điều khiển node cũ), jobs/ (store, batch, scan)
│   ├── core/              # Lõi nghiệp vụ
│   │   ├── contracts.py   # Hợp đồng dữ liệu Backtest/WFA/Monte Carlo
│   │   ├── data/          # loader, resampler, quality_gate, crawler/
│   │   ├── signals/       # kernels, diagnostics, evaluator
│   │   ├── strategy/      # params, strategy_book/library, templates, builder/generator/validator, DC
│   │   ├── backtest/      # engine, portfolio, execution, metrics, shared_data
│   │   ├── analytics/     # portfolio_dashboard, stats_metrics, queries
│   │   └── research/      # nghiên cứu thị trường (regime, DC, insight, scan)
│   ├── db/                # data_layout, local_pkl, tick_storage, mysql, mongo, models
│   ├── optimize/          # generator, ranker, runner, registry, book_export
│   ├── wfa/               # walk_forward (đơn tài sản), portfolio_wfa
│   ├── carlo/             # monte_carlo
│   └── utils/             # lru, parallel, memwatch, jsonsafe, jobresult
├── test/                  # pytest + golden/ (snapshot bit-identical)
├── scripts/               # CLI: run_limited.sh, run_book_backtest, build_strategy_book, smoke_check, ...
├── ops/                   # systemd units, install_user_units.sh
├── alphas/                # sổ alpha / registry
├── data/                  # dữ liệu & cache (không commit)
├── frontend/              # Vite SPA
└── docs/                  # tài liệu
```

Chạy mọi thứ qua `scripts/run_limited.sh` (PYTHONPATH=nora, cwd=nora); import theo dạng `backend.core.backtest.portfolio`, `backend.api.jobs.batch`, ...

---

Cấu trúc tài liệu dự án Nora được thiết kế theo tiêu chuẩn kép:
1. **`knowledge_base/` (Tri thức & Định hướng cốt lõi)**: Lưu giữ toàn bộ ý tưởng gốc, lý thuyết định lượng, triết lý vi mô DEX và các **Luật thép (Rule Base)** được đúc kết từ chỉ đạo của Sếp qua các phiên review. Đây là tầng tri thức bất biến, không chứa code.
2. **`bmad/` (Build - Measure - Architecture - Deliver)**: Bản đồ kỹ thuật chi tiết dành cho Developer và AI. Bao gồm đặc tả kiến trúc (Spec), bản đồ file code (Code Map), hiện trạng hệ thống và báo cáo kết quả theo từng đợt sóng (Wave Reports).

---

## 📂 Sơ Đồ Cây Thư Mục Tài Liệu

```text
nora/docs/
├── README.md                                    # Mục lục và định hướng chung
│
├── knowledge_base/                              # [PHẦN 1] TRI THỨC VÀ Ý TƯỞNG CỐT LÕI
│   ├── 01_core_vision_and_principles.md         # Tầm nhìn, triết lý DEX Microstructure & Intrinsic Time
│   ├── 02_boss_mandates_and_rulebase.md         # Luật thép từ Sếp qua các đợt review (Rule Base)
│   ├── 03_mathematical_foundations.md           # Lý thuyết toán học: DC, Scaling Laws, Overshoot Deficit
│   └── 04_friction_and_cost_stress_theory.md    # Lý thuyết ma sát thị trường: Từ Zero Cost đến Extreme Stress
│
└── bmad/                                        # [PHẦN 2] SPECS, BẢN ĐỒ CODE & BÁO CÁO TIẾN ĐỘ
    ├── 01_architecture_and_codemap.md           # Bản đồ định tuyến: chức năng nào nằm ở file nào
    ├── 02_current_system_status.md              # Hiện trạng các module (Backend, Frontend, Cache, Port)
    ├── 03_api_and_data_contracts.md             # Đặc tả giao thức REST API & Schema dữ liệu JSON
    ├── 04_playbook_specifications.md            # Quy tắc chiến thuật (DC Fade, Breakout, Do Not Trade)
    └── waves/                                   # Báo cáo tiến độ & kết quả từng đợt sóng (Session Logs)
        ├── wave_01_core_tick_engine.md          # Đợt sóng 1: Lõi Tick Engine, DC Event Profile, loại bỏ nến
        ├── wave_02_cost_stress_models.md        # Đợt sóng 2: Triển khai 4 cấp độ chi phí (Zero -> Stress)
        └── wave_03_timeframe_universe_cache.md  # Đợt sóng 3: Độc lập hóa Timeframe 15m/1h/4h & Universe Cache
```

---

## 🧭 Nguyên Tắc Vận Hành Cho Developer & AI
- **Khi bắt đầu phiên làm việc mới**: Luôn đọc `nora/docs/knowledge_base/02_boss_mandates_and_rulebase.md` và `nora/docs/bmad/02_current_system_status.md` để nắm chắc các ràng buộc bất biến và hiện trạng mã nguồn.
- **Khi hoàn thành một tính năng/đợt tối ưu**: Cập nhật hiện trạng vào `nora/docs/bmad/02_current_system_status.md` và tạo một file báo cáo đợt sóng mới trong `nora/docs/bmad/waves/wave_XX_...md`.
- **Khi Sếp đưa ra góp ý mới**: Bổ sung ngay nguyên tắc mới vào `nora/docs/knowledge_base/02_boss_mandates_and_rulebase.md`.
