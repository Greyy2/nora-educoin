# P9 — báo cáo luật phụ thuộc (tự sinh bởi nora/test/test_layering.py, chế độ BÁO CÁO)

Không sửa tay. Sinh lại: `PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py`.
Bật bắt buộc (P9.10): `NORA_LAYERING_STRICT=1`. Luật: ADR-P9 §2; ánh xạ đường dẫn hiện tại -> tầng đích: bảng `LAYER_RULES` trong test.

- Module backend: 145 · shim (`# P9-SHIM`, bỏ qua): 12 · chưa ánh xạ: 0
- **Vi phạm: 62**

## Tóm tắt theo luật

| Luật | Số vi phạm |
|---|---:|
| core -> crawl | 13 |
| optimize -> routes | 10 |
| crawl -> core | 6 |
| wfa -> optimize | 6 |
| core -> regime | 4 |
| core order indicator -> signal | 4 |
| optimize -> live | 4 |
| core order signal -> backtest | 3 |
| crawl -> optimize | 3 |
| core -> optimize | 2 |
| verdict -> crawl | 2 |
| core order models -> position_size | 1 |
| core order params -> indicator | 1 |
| live -> routes | 1 |
| metrics -> crawl | 1 |
| metrics -> live | 1 |

## Chi tiết

### core -> crawl (13)

- `backend/core/backtest/dex.py:10` -> `db/data_layout`
- `backend/core/backtest/engine.py:21` -> `core/data/loader`
- `backend/core/backtest/engine.py:211` -> `db/local_pkl`
- `backend/core/backtest/portfolio.py:26` -> `core/data/shared`
- `backend/core/backtest/portfolio.py:31` -> `utils/lru`
- `backend/core/backtest/portfolio.py:172` -> `core/data/loader`
- `backend/core/backtest/portfolio.py:209` -> `core/data/quality_gate`
- `backend/core/execute/amm.py:13` -> `core/data/tick_crawler`
- `backend/core/params/builder.py:31` -> `db/local_pkl`
- `backend/core/params/builder.py:54` -> `db/data_layout`
- `backend/core/params/builder.py:66` -> `db/local_pkl`
- `backend/core/signals/diagnostics.py:105` -> `db/local_pkl`
- `backend/core/strategy/pydsl/profiles.py:40` -> `db/data_layout`

### optimize -> routes (10)

- `backend/core/analytics/user_alphas.py:161` -> `api/jobs/batch`
- `backend/core/analytics/user_alphas.py:347` -> `api/jobs/batch`
- `backend/core/backtest/run.py:141` -> `core/params/modes`
- `backend/core/backtest/run.py:161` -> `core/params/modes`
- `backend/core/backtest/tick_run.py:144` -> `core/params/modes`
- `backend/optimize/funnel/generate.py:100` -> `core/params/modes`
- `backend/optimize/funnel/generate.py:107` -> `core/params/modes`
- `backend/optimize/funnel/generate.py:161` -> `core/params/modes`
- `backend/optimize/funnel/generate.py:176` -> `core/params/modes`
- `backend/optimize/funnel/publish.py:95` -> `api/jobs/batch`

### crawl -> core (6)

- `backend/core/data/shared.py:31` -> `core/backtest/engine`
- `backend/core/data/shared.py:32` -> `core/backtest/portfolio`
- `backend/core/data/shared.py:54` -> `core/backtest/engine`
- `backend/core/data/shared.py:56` -> `core/signals/evaluator`
- `backend/core/data/shared.py:129` -> `core/backtest/engine`
- `backend/core/data/shared.py:178` -> `core/signals/evaluator`

### wfa -> optimize (6)

- `backend/wfa/walk_forward.py:27` -> `core/backtest/run`
- `backend/wfa/walk_forward.py:29` -> `optimize/shared`
- `backend/wfa/walk_forward.py:30` -> `utils/parallel`
- `backend/wfa/walk_forward.py:78` -> `utils/memwatch`
- `backend/wfa/walk_forward.py:109` -> `optimize/store`
- `backend/wfa/walk_forward.py:110` -> `optimize/store`

### core -> regime (4)

- `backend/core/backtest/portfolio.py:132` -> `core/regime/classifier`
- `backend/core/backtest/portfolio.py:217` -> `core/regime/classifier`
- `backend/core/backtest/portfolio.py:225` -> `core/regime/classifier`
- `backend/core/signals/snapshot.py:87` -> `core/regime/classifier`

### core order indicator -> signal (4)

- `backend/core/strategy/pydsl/features.py:15` -> `core/strategy/pydsl/spec`
- `backend/core/strategy/pydsl/features.py:336` -> `core/strategy/pydsl/spec`
- `backend/core/strategy/pydsl/ops.py:10` -> `core/strategy/pydsl/spec`
- `backend/core/strategy/pydsl/ops.py:244` -> `core/strategy/pydsl/spec`

### optimize -> live (4)

- `backend/core/backtest/tick_run.py:33` -> `live/paper`
- `backend/core/backtest/tick_run.py:72` -> `live/signals`
- `backend/core/backtest/tick_run.py:89` -> `live/signals`
- `backend/core/backtest/tick_run.py:103` -> `live/bot`

### core order signal -> backtest (3)

- `backend/core/signals/diagnostics.py:102` -> `core/backtest/engine`
- `backend/core/signals/snapshot.py:80` -> `core/backtest/portfolio`
- `backend/core/strategy/pydsl/explain.py:16` -> `core/strategy/pydsl/profiles`

### crawl -> optimize (3)

- `backend/crawl/cex.py:19` -> `utils/jobs`
- `backend/crawl/dex.py:17` -> `utils/jobs`
- `backend/crawl/store.py:1769` -> `utils/jobs`

### core -> optimize (2)

- `backend/core/signals/snapshot.py:137` -> `core/params/presets`
- `backend/core/strategy/pydsl/profiles.py:13` -> `core/strategy/pydsl/weights`

### verdict -> crawl (2)

- `backend/core/metrics/diagnose_inputs.py:25` -> `core/data/loader`
- `backend/core/metrics/diagnose_inputs.py:76` -> `core/data/loader`

### core order models -> position_size (1)

- `backend/core/execute/account.py:10` -> `core/execute/policy`

### core order params -> indicator (1)

- `backend/core/params/template.py:101` -> `core/signals/kernels`

### live -> routes (1)

- `backend/live/bot.py:61` -> `core/params/modes`

### metrics -> crawl (1)

- `backend/core/analytics/dashboard.py:79` -> `db/local_pkl`

### metrics -> live (1)

- `backend/core/analytics/signal_explain.py:115` -> `live/signals`

## Shim (tương thích ngược, gỡ ở P9.10)

- `core/data/crawler`
- `core/data/loader`
- `core/data/okx_crawler`
- `core/data/promote`
- `core/data/quality_gate`
- `core/data/resampler`
- `core/data/tick_crawler`
- `db/data_layout`
- `db/local_pkl`
- `db/tick_storage`
- `utils/jsonsafe`
- `utils/lru`
