# P9 — báo cáo luật phụ thuộc (tự sinh bởi nora/test/test_layering.py, chế độ BÁO CÁO)

Không sửa tay. Sinh lại: `PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py`.
Bật bắt buộc (P9.10): `NORA_LAYERING_STRICT=1`. Luật: ADR-P9 §2; ánh xạ đường dẫn hiện tại -> tầng đích: bảng `LAYER_RULES` trong test.

- Module backend: 146 · shim (`# P9-SHIM`, bỏ qua): 25 · chưa ánh xạ: 0
- **Vi phạm: 62**

## Tóm tắt theo luật

| Luật | Số vi phạm |
|---|---:|
| core -> crawl | 15 |
| optimize -> routes | 10 |
| crawl -> core | 6 |
| wfa -> optimize | 6 |
| core -> regime | 4 |
| core order indicator -> signal | 4 |
| optimize -> live | 4 |
| core order signal -> backtest | 3 |
| crawl -> optimize | 3 |
| verdict -> crawl | 2 |
| core -> optimize | 1 |
| core order params -> indicator | 1 |
| live -> routes | 1 |
| metrics -> crawl | 1 |
| metrics -> live | 1 |

## Chi tiết

### core -> crawl (15)

- `backend/core/backtest.py:22` -> `core/data/loader`
- `backend/core/backtest.py:25` -> `core/data/shared`
- `backend/core/backtest.py:26` -> `utils/lru`
- `backend/core/backtest.py:27` -> `db/data_layout`
- `backend/core/backtest.py:1931` -> `db/local_pkl`
- `backend/core/backtest.py:2235` -> `core/data/loader`
- `backend/core/backtest.py:2272` -> `core/data/quality_gate`
- `backend/core/backtest/run_defaults.py:19` -> `crawl/store`
- `backend/core/backtest/run_defaults.py:25` -> `crawl/store`
- `backend/core/execute/amm.py:13` -> `core/data/tick_crawler`
- `backend/core/params.py:320` -> `db/local_pkl`
- `backend/core/params.py:343` -> `db/data_layout`
- `backend/core/params.py:355` -> `db/local_pkl`
- `backend/core/signals/diagnostics.py:105` -> `db/local_pkl`
- `backend/core/strategy/pydsl/profiles.py:33` -> `crawl/store`

### optimize -> routes (10)

- `backend/core/analytics/user_alphas.py:152` -> `api/jobs/batch`
- `backend/core/analytics/user_alphas.py:337` -> `api/jobs/batch`
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

- `backend/core/backtest.py:2195` -> `core/regime/classifier`
- `backend/core/backtest.py:2280` -> `core/regime/classifier`
- `backend/core/backtest.py:2288` -> `core/regime/classifier`
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
- `backend/core/strategy/pydsl/explain.py:14` -> `core/strategy/pydsl/profiles`

### crawl -> optimize (3)

- `backend/crawl/cex.py:19` -> `utils/jobs`
- `backend/crawl/dex.py:17` -> `utils/jobs`
- `backend/crawl/store.py:1797` -> `utils/jobs`

### verdict -> crawl (2)

- `backend/core/metrics/diagnose_inputs.py:25` -> `core/data/loader`
- `backend/core/metrics/diagnose_inputs.py:76` -> `core/data/loader`

### core -> optimize (1)

- `backend/core/signals/snapshot.py:137` -> `core/params/presets`

### core order params -> indicator (1)

- `backend/core/params.py:244` -> `core/signals/kernels`

### live -> routes (1)

- `backend/live/bot.py:61` -> `core/params/modes`

### metrics -> crawl (1)

- `backend/core/analytics/dashboard.py:79` -> `db/local_pkl`

### metrics -> live (1)

- `backend/core/analytics/signal_explain.py:115` -> `live/signals`

## Shim (tương thích ngược, gỡ ở P9.10)

- `core/backtest/dex`
- `core/backtest/engine`
- `core/backtest/kernel`
- `core/backtest/portfolio`
- `core/data/crawler`
- `core/data/loader`
- `core/data/okx_crawler`
- `core/data/promote`
- `core/data/quality_gate`
- `core/data/resampler`
- `core/data/tick_crawler`
- `core/execute/account`
- `core/execute/events`
- `core/execute/ledger`
- `core/execute/models`
- `core/execute/policy`
- `core/execute/risk`
- `core/params/builder`
- `core/params/schema`
- `core/params/template`
- `db/data_layout`
- `db/local_pkl`
- `db/tick_storage`
- `utils/jsonsafe`
- `utils/lru`
