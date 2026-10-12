"""Dựng sổ + presets (P9.6): nhóm kiểm tham số/khung dùng cho engine và phễu (từ models/params/modes), dựng sổ chiến lược (optimize/book), presets (models/params/presets).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8, P9.9). Chiến lược hệ thống nạp từ file DSL (strategy_loader cũ) nằm ở đây.
"""
import calendar
import heapq
import itertools
import json
import math
import os
import time
import warnings
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.carlo.carlo import bootstrap_daily
from backend.models.params import DAY_MS as DAY, BASE_RISK_PER_TRADE_PCT, REGIME_MAP, RISK, materialize, regime_for, schema_defaults
from backend.alpha.compile import load_system_strategies
from backend.models.storage import alpha_dir, alpha_dir as alphas_dir, alpha_run_dir
from backend.metrics.metrics import portfolio_metrics
from backend.models.models import NORA_DIR
from backend.optimize.funnel.storage import atomic_write_json, data_fingerprint, make_job_key, normalize, ResultsStore, stream_stage
from backend.optimize.process.workers import auto_workers, pool_map_safe
from backend.optimize.search.evaluate import BacktestJob, make_engine, SharedExporter
from backend.optimize.search.generate import grid_size, iter_params
from backend.models.storage import as_list, json_default, options, read_json, write_job_result


# ══════════════════════════════════════════════════════════════════════════
# Chế độ chạy: Cơ bản (basic = preset khoá sẵn) / Nâng cao (advanced = mọi tham số chỉnh được, kiểm theo params_schema).
#
# Module thuần (không FastAPI): kiểm tham số theo params_schema của chiến lược, điền khoá thiếu từ preset, rút tham số tối thiểu cho job,
# và phân loại "custom_gates" (kết quả dùng ngưỡng gate khác chuẩn -> không được xuất bản/promote). Lớp API: backend/routes/modes.py.
# Mọi thông báo lỗi bằng tiếng Việt, gắn theo TRƯỜNG: [{"field": "strategies[0].params.sig.ema_fast", "message": "..."}].
# ══════════════════════════════════════════════════════════════════════════

# 6 kịch bản luôn có + 3 kịch bản trend thẳng đứng (chỉ có khi nguồn biết vị thế, vd. WFA — carlo.vertical_exposure)

FieldError = Tuple[str, str]       # (trường, thông báo)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unit(spec: Dict[str, Any]) -> str:
    return f" {spec['unit']}" if spec.get("unit") else ""


def check_value(key: str, spec: Dict[str, Any], value: Any) -> Tuple[Any, Optional[str]]:
    """-> (giá trị đã chuẩn hoá, lỗi|None) cho một tham số theo spec của params_schema."""
    label = f"{spec['label_vi']} ({key})"
    if spec["type"] == "choice":
        if value not in spec["choices"] or not isinstance(value, str):
            return None, f"{label} phải là một trong {spec['choices']}, nhận {value!r}"
        return value, None
    if not _num(value):
        return None, f"{label} phải là số, nhận {value!r}"
    lo, hi = spec["min"], spec["max"]
    if spec["type"] == "int":
        if not float(value).is_integer():
            return None, f"{label} phải là số nguyên từ {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
        value = int(value)
    else:
        value = float(value)
    if not lo <= value <= hi:
        return None, f"{label} phải nằm trong khoảng {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
    return value, None


def validate_params(candidate: Dict[str, Any], params: Any, base: Dict[str, Any], prefix: str = "params") -> Tuple[Dict[str, Any], List[FieldError]]:
    """Kiểm `params` của một chiến lược theo params_schema (khoá lạ, kiểu, khoảng, khung thời gian, EMA nhanh < chậm, cột kernel, ngân sách DCA).
    Khoá thiếu lấy từ `base` (preset). -> (tham số ĐẦY ĐỦ đã chuẩn hoá, danh sách lỗi theo trường). Có lỗi thì tham số đầy đủ chưa đáng tin."""
    schema = candidate["params_schema"]
    cid = candidate["id"]
    errors: List[FieldError] = []
    if not isinstance(params, dict):
        return dict(base), [(prefix, f"{cid}: params phải là đối tượng {{khoá: giá trị}}, nhận {type(params).__name__}")]
    full = dict(base)
    for key, value in params.items():
        spec = schema.get(key)
        if spec is None:
            hint = f" (ý bạn là '{'sig.' + key}'?)" if "sig." + key in schema else ""
            errors.append((f"{prefix}.{key}", f"{cid}: tham số '{key}' không có trong chiến lược này{hint}; khoá hợp lệ: {list(schema)}"))
            continue
        norm, err = check_value(key, spec, value)
        if err:
            errors.append((f"{prefix}.{key}", f"{cid}: {err}"))
        else:
            full[key] = norm
    if errors:
        return full, errors
    fast, slow = full.get("sig.ema_fast"), full.get("sig.ema_slow")
    if fast is not None and slow is not None and fast >= slow:
        errors.append((f"{prefix}.sig.ema_fast", f"{cid}: EMA nhanh ({fast}) phải nhỏ hơn EMA chậm ({slow})"))
    if errors:
        return full, errors
    # Thay thử vào cây: bắt cột kernel/khung không hợp lệ (cùng kiểm tra lúc chạy thật) + ngân sách DCA của vị thế
    try:
        st = materialize(candidate, full)
        from backend.models.params import VENUE_COSTS, dca_budget_check
        budget = dca_budget_check(st["position"], VENUE_COSTS[("cex", "perp")])
        if not budget["ok"]:
            errors.append((prefix, f"{cid}: ngân sách DCA không đủ — cần {budget['need_pct']:.1f}% vốn, trần {budget['cap_pct']:.1f}%"))
    except ValueError as exc:
        errors.append((prefix, f"{cid}: {exc}"))
    return full, errors


SCHEMA_SPACE_EXCLUDE = ("risk_per_trade_pct",)   # phễu cố định rủi ro/lệnh (S5 tìm hệ số khối lượng sau)


def schema_space(candidate: Dict[str, Any], exclude=SCHEMA_SPACE_EXCLUDE) -> Dict[str, List[Any]]:
    """Không gian sinh alpha từ params_schema: số nguyên/thực -> mọi giá trị min, min+step, ..., max; lựa chọn -> mọi lựa chọn.
    Là lưới rời rạc (cùng định dạng `space`) nên dùng chung được bộ sinh / lân cận ±1 bước của phễu."""
    out: Dict[str, List[Any]] = {}
    for key, spec in (candidate.get("params_schema") or {}).items():
        if key in exclude:
            continue
        if spec["type"] == "choice":
            out[key] = list(spec["choices"])
            continue
        lo, hi, step = spec["min"], spec["max"], spec.get("step") or 1
        n = int(math.floor((hi - lo) / step + 1e-9)) + 1
        if spec["type"] == "int":
            out[key] = [int(lo + i * step) for i in range(n)]
        else:
            nd = max(0, -int(math.floor(math.log10(step)))) + 2 if step < 1 else 2
            out[key] = [round(lo + i * step, nd) for i in range(n)]
    return out


# ─── Khung chạy (nến mô phỏng) ───────────────────────────────────────────────
def frame_keys(candidate: Dict[str, Any]) -> List[str]:
    """Khoá chọn KHUNG nến của chiến lược (sig.*_tf, atr_frame...): kiểu choice, mọi lựa chọn là khung."""
    from backend.alpha.dsl.strategy import FRAME_MS
    return [k for k, v in (candidate.get("params_schema") or {}).items()
            if v.get("type") == "choice" and set(v.get("choices") or []) <= set(FRAME_MS)]


def lift_frame(frame: str, base_frame: str, choices: List[str]) -> Optional[str]:
    """Khung >= khung chạy giữ nguyên; nhỏ hơn -> khung chạy nếu là lựa chọn hợp lệ, không thì None (không chạy được)."""
    from backend.alpha.dsl.strategy import FRAME_MS
    if FRAME_MS[frame] >= FRAME_MS[base_frame]:
        return frame
    return base_frame if base_frame in choices else None


def lift_frames(candidate: Dict[str, Any], params: Dict[str, Any], base_frame: str) -> Dict[str, Any]:
    """Tham số với mọi khung (kể cả mặc định schema) nâng lên >= khung chạy. ValueError nếu một khung không thể nâng."""
    if base_frame == "1m":
        return dict(params)
    out = dict(params)
    defaults = schema_defaults(candidate)
    for k in frame_keys(candidate):
        cur = out.get(k, defaults[k])
        new = lift_frame(cur, base_frame, list(candidate["params_schema"][k]["choices"]))
        if new is None:
            raise ValueError(f"{candidate['id']}: {k}={cur} nhỏ hơn khung chạy {base_frame} và không có lựa chọn >= {base_frame}")
        if new != cur or k in out:
            out[k] = new
    return out


# ══════════════════════════════════════════════════════════════════════════
# Dữ liệu sổ chiến lược (phần tham số vị thế đã ở models/params.py — RISK cũng ở đó vì alpha/dsl/strategy.build_plan cần)
#
# Sổ chiến lược (strategy book): tham số theo CHIẾN LƯỢC, không theo tài sản; vốn phân bổ theo RỦI RO.
#
# Nguyên tắc:
# - Một chiến lược = tín hiệu (AST trên kernel) + quản lý vị thế. Một bộ tham số dùng chung cho cả vũ trụ tài sản.
# - Thoát lệnh theo bội số ATR% (exit_unit="atr") để cùng tham số tự co giãn theo biến động từng tài sản:
#   stop_loss_rate=2 nghĩa là SL cách giá vào 2 × ATR%(khung atr_frame) đo ở nến đã đóng lúc có tín hiệu.
# - Khối lượng theo rủi ro (sizing="risk"): chạm SL mất ~risk_per_trade_pct% vốn; đòn bẩy tự hạ để thanh lý
#   cách giá vào >= 1,5 × khoảng SL; trần đòn bẩy 10x (mức rủi ro đã chốt).
# - Rủi ro danh mục (RiskConfig): số vị thế đồng thời, mỗi tài sản tối đa 1 vị thế, trần tổng danh nghĩa, kill switch 30%.
#
# Chọn chiến lược (run_book_build bên dưới) chạy trên CẢ vũ trụ cùng lúc (backtest danh mục), nên một
# cấu hình chỉ thắng nhờ một tài sản sẽ bị loại bởi điều kiện độ phủ (đa số tài sản phải có lãi).
#
# Chiến lược hệ thống = file Python DSL (P9.9): KEMA / Sideway / DCA (mỗi chiến lược một chân LONG và một chân SHORT; mỗi bộ tham số của một chân = một alpha;
# "Cả hai" = chạy cả hai chân) được VIẾT trong data/alpha/strategies/*.py (SimpleAlgorithm + p('tên', mặc_định, lo=, hi=, step=, grid=) cho tham số; nhãn/trợ giúp
# tiếng Việt nằm trong file). CANDIDATES / STRATEGIES / BY_ID bên dưới chỉ là góc nhìn trên kết quả biên dịch của load_system_strategies (cây khuôn, params_schema,
# space) — core không đọc file.
# ══════════════════════════════════════════════════════════════════════════

UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

GATES = {
    "min_trades": 40,             # trên cả danh mục, mỗi giai đoạn
    "min_symbols_positive": 5,    # dev1: >= 5/8 tài sản có lãi (độ phủ)
    "min_symbols_positive_dev2": 4,
    "max_mdd_pct": 30.0,
}

_LOADED = load_system_strategies()
CANDIDATES: List[Dict[str, Any]] = list(_LOADED["candidates"])
# Định nghĩa đăng ký thêm ngoài danh mục (test: chiến lược cũ của golden / kiểm parity). Không hiện ở API danh mục, không sinh alpha.
EXTRA_CANDIDATES: List[Dict[str, Any]] = []


def all_candidates() -> List[Dict[str, Any]]:
    """Danh mục + định nghĩa đăng ký thêm (đọc tại lúc gọi: test thay CANDIDATES / EXTRA_CANDIDATES vẫn có hiệu lực)."""
    return CANDIDATES + EXTRA_CANDIDATES


class _ById(Mapping):
    """{id: định nghĩa} của all_candidates(), tính tại lúc tra."""
    def _m(self) -> Dict[str, Dict[str, Any]]:
        return {c["id"]: c for c in all_candidates()}

    def __getitem__(self, key: str) -> Dict[str, Any]:
        return self._m()[key]

    def __iter__(self):
        return iter(self._m())

    def __len__(self) -> int:
        return len(self._m())


BY_ID: Mapping = _ById()

STRATEGIES: List[Dict[str, Any]] = list(_LOADED["strategies"])
SOURCES: Dict[str, Dict[str, str]] = dict(_LOADED["sources"])   # {id chân: {file, sha256, code_hash}} — nguồn gốc file của từng chiến lược

REGIME_MAP.update({c["id"]: regime_for(c["side"]) for c in CANDIDATES})   # REGIME_MAP (dict) do models/params.py giữ; điền ở đây


def reload_system_strategies() -> Dict[str, Any]:
    """Nạp lại data/alpha/strategies/*.py (cache mtime+size tự vô hiệu) và làm mới CANDIDATES / STRATEGIES / SOURCES / REGIME_MAP TẠI CHỖ
    (các nơi đã giữ tham chiếu tới danh sách vẫn thấy mã mới). Lượt backtest / sổ / phễu chạy SAU ĐÓ dùng mã mới. Lỗi biên dịch -> DslError, trạng thái cũ giữ nguyên."""
    loaded = load_system_strategies()
    old_ids = {c["id"] for c in CANDIDATES}
    CANDIDATES[:] = list(loaded["candidates"])
    STRATEGIES[:] = list(loaded["strategies"])
    SOURCES.clear()
    SOURCES.update(loaded["sources"])
    for gone in old_ids - {c["id"] for c in CANDIDATES}:
        REGIME_MAP.pop(gone, None)
    REGIME_MAP.update({c["id"]: regime_for(c["side"]) for c in CANDIDATES})
    return loaded


def perp_symbols(universe: List[str] = None) -> List[str]:
    return [f"{s}@perp" for s in (universe or UNIVERSE)]


def book_strategies(ids: Optional[List[str]] = None, regime: bool = True) -> List[Dict[str, Any]]:
    """Mọi chiến lược lõi của sổ với bộ tham số tốt nhất (presets.json) — tham số khác vẫn là cùng chiến lược.
    regime=True: kèm bảng regime cho phép (entry = tín hiệu thô VÀ regime cho phép; entry_raw = tín hiệu thô)."""
    presets = load_presets()
    return [materialize(c, presets[c["id"]]["params"], regime=regime) for c in CANDIDATES if not ids or c["id"] in ids]


# ══════════════════════════════════════════════════════════════════════════
# Chốt sổ chiến lược: tín hiệu + chiến lược + phân bổ vốn + phân bổ rủi ro (tham số theo chiến lược, không theo tài sản).
#
# |──────────── dev 80% ─────────────|── holdout 20% ──|
# |── dev1: chọn tham số ─|─ dev2 ───|   chấm 1 lần    |
#
# A. dev1  — mỗi chiến lược ứng viên: thử các cấu hình trên CẢ vũ trụ 8 tài sản (backtest danh mục, rủi ro chuẩn
#            0,5%/lệnh, SL khớp đúng mức). Điểm = lãi / MDD; bắt buộc đủ lệnh và >= 5/8 tài sản có lãi. Giữ top-3.
# B. dev2  — cấu hình top-1 của mỗi chiến lược phải: lãi với SL khớp đúng mức VÀ khớp bi quan, MDD <= 30%,
#            đủ lệnh, >= 4/8 tài sản có lãi. Top-2, top-3 chỉ để đo độ ổn định (không dùng để chọn).
# C. sổ    — các chiến lược đạt chạy CHUNG một sổ vốn với giới hạn danh mục (RiskConfig). Rủi ro mỗi lệnh như nhau
#            cho mọi chiến lược (khối lượng đã tự quy đổi theo ATR). Mức rủi ro/lệnh cuối = mức lớn nhất sao cho
#            bootstrap 1 năm trên lợi suất ngày dev2 (SL bi quan) có P(MDD >= 30%) <= 5%.
# D. holdout — chạy đúng sổ đã chốt một lần (cả hai cách khớp SL). Không chọn lại gì ở bước này.
#
# Job API (POST /api/studio/book/build -> optimize/process/process.py -> run_job(params)); tham số và mặc định: DEFAULTS
# (workers, per_worker_mb, n, seed, only, out, keep_top, resume, max_configs, force_large, timeframe = khung chạy 1m/15m/1h/4h).
# Quy mô lớn (tới ~1.000.000 cấu hình): giai đoạn A chạy STREAMING — cấu hình sinh lười, mỗi kết quả ghi ngay vào <run_dir>/results.sqlite
# (backend/optimize/funnel/storage.py), tiến trình cha chỉ giữ top-K (K = max(3, keep_top), mặc định 50) nên RAM cha phẳng.
#   resume=<run_dir>     chạy tiếp lần bị ngắt (bỏ qua job đã có trong kho; kết quả cuối y hệt lần chạy không gián đoạn)
#   max_configs=N        từ chối khi tổng số cấu hình > N (mặc định 200000) trừ khi force_large; trước khi chạy in ước lượng
#                        (số cấu hình × giây đo thực của 1 cấu hình / số worker) và ghi <run_dir>/estimate.json
#   tiến độ: <run_dir>/progress.json (tối đa mỗi 5 giây); SIGTERM -> flush kho rồi thoát (resume được).
#   stage_a.json / result.json chỉ chứa top-K mỗi chiến lược + số đếm (stage_a_counts.json: tried/passed); toàn bộ hàng xem qua kho.
# Kết quả: data/alpha/book.json (+ data/alpha/testnet/book.json CHỈ khi holdout đạt; trượt holdout -> status HOLDOUT_FAILED, không có testnet), báo cáo tại <data>/alpha/book/<thời điểm>/.
#
# Bộ nhớ (mỗi worker là một tiến trình có cache riêng):
#   NORA_CANDLE_CACHE_MB   ngân sách cache nến cả file (script này mặc định 512 MB)
#   NORA_DATA_CACHE_MB     ngân sách cache mảng giá + kernel theo cửa sổ (script này mặc định 1024 MB)
#   RAM một worker: mặc định PER_WORKER_MB (số ĐO THỰC, chỉ để hoạch định số worker + cổng RAM; rào cứng là
#   trần cgroup — worker vượt thì bị giết riêng, _pool_map_safe chạy lại với một nửa số worker).
#   Đo lại bằng dòng `đỉnh RAM/worker` và ghi đè bằng per_worker_mb khi dữ liệu/ngân sách cache đổi.
#   workers="auto" đọc cả giới hạn cgroup (systemd-run -p MemoryMax=...), không chỉ RAM trống của máy.
#   BẮT BUỘC chạy dưới trần RAM (job API luôn qua ops/run_limited.sh; không có trần cgroup thì từ chối, trừ khi NORA_ALLOW_UNLIMITED=1).
#   Dữ liệu dùng chung: trước mỗi pool, tiến trình CHA dựng một lần mảng giá + kernel + funding của cả vũ trụ vào
#   <run_dir>/_shared/ (backend/optimize/search/evaluate.py); worker chỉ np.load(mmap_mode="r") qua NORA_SHARED_DATA_DIR
#   -> RAM riêng (anon) mỗi worker nhỏ, trang file chỉ tính MỘT lần trong cgroup. Chạy xong thì xoá _shared (lỗi thì giữ lại).
#   OMP_NUM_THREADS / OPENBLAS_NUM_THREADS / MKL_NUM_THREADS đặt = "1" nếu chưa có.
# ══════════════════════════════════════════════════════════════════════════

# ── Đặt TRƯỚC mọi import numpy/backend: tiến trình con kế thừa qua fork ──────
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")
# ─────────────────────────────────────────────────────────────────────────────




WARMUP = 20 * DAY
MDD_LIMIT = 30.0
RUIN_MAX_PCT = 5.0
RISK_SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
MAX_RISK_PER_TRADE = 2.0
# Đo 01/10/2026 (dữ liệu dùng chung qua mmap, 8 tài sản perp, dev1 ≈ 14 tháng): VmHWM 560–590 MB mỗi worker (đã gồm trang mmap
# dùng chung ~440 MB/giai đoạn; phần riêng ~150 MB) × 1,3 dự phòng. Trước khi dùng mmap: 1280–1320 MB (xem git log).
# Đo lại bằng dòng `đỉnh RAM/worker`, ghi đè bằng per_worker_mb khi kích thước dữ liệu hoặc ngân sách cache đổi;
# trần cgroup (run_limited.sh) mới là rào cứng.
PER_WORKER_MB = 800


def windows(symbols):
    from backend.data.data import read_manifest
    ms = [read_manifest(s) for s in symbols]
    start = max(int(m["start_ts"]) for m in ms) + WARMUP
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    return {"start": start, "dev1_end": start + int(span * 0.4), "dev2_end": start + int(span * 0.8), "end": end}


def run_book(job):
    import contextlib
    import io
    from backend.optimize.process.workers import peak_rss_mb, rss_anon_mb
    eng, start = make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    result = metrics(eng.get_results(), start)
    result["_peak_rss_mb"] = round(peak_rss_mb(), 1)  # đỉnh (gồm trang mmap dùng chung) của tiến trình worker tới lúc này
    result["_rss_anon_mb"] = round(rss_anon_mb(), 1)  # phần RAM riêng của worker (không gồm mmap dùng chung)
    return result


def _pool_shared(jobs, workers, label, shared_dir):
    """Làm nóng kho dùng chung -> pool -> dọn kho của giai đoạn này (lỗi thì ngoại lệ bay lên, kho giữ nguyên để gỡ lỗi)."""
    exporter = SharedExporter(shared_dir, label)
    exporter.ensure(jobs)
    res = _pool_map_safe(run_book, jobs, workers, label)
    exporter.cleanup()
    return res


def config_count(candidate, n):
    """Số cấu hình sẽ thử = min(n, kích thước lưới) — không dựng lưới."""
    return min(int(n), grid_size(candidate["space"]))


def iter_configs(candidate, n, seed):
    """Sinh LƯỜI từng cấu hình (dict) của `candidate["space"]` — MỘT bộ lấy mẫu: optimize.search.generate.iter_params (lưới vừa n -> toàn lưới
    theo thứ tự product của khoá sắp xếp; ngược lại `random.Random(seed).sample` n vị trí theo CHỈ SỐ, không dựng lưới)."""
    return iter_params(candidate["space"], n, seed)


def configs(candidate, n, seed, lazy=False):
    """Danh sách cấu hình (như cũ). lazy=True -> trả generator (không dựng lưới/danh sách) cho không gian rất lớn."""
    gen = iter_configs(candidate, n, seed)
    return gen if lazy else list(gen)


def score(m, gates, sym_key="min_symbols_positive"):
    ok = m["trades"] >= gates["min_trades"] and m["symbols_positive"] >= gates[sym_key] and m["ret_pct"] > 0 \
        and m["mdd_pct"] <= gates["max_mdd_pct"]
    return (m["ret_pct"] / max(m["mdd_pct"], 1.0)) if ok else float("-inf"), ok


def strip_metrics(m, also=()):
    """Bỏ khoá nội bộ/nặng (chuỗi ngày, RSS) khỏi số đo trước khi ghi ra file; `also` = khoá bỏ thêm. MỘT định nghĩa cho build + tasks."""
    drop = ("daily", "_peak_rss_mb", "_rss_anon_mb") + tuple(also)
    return {k: v for k, v in m.items() if k not in drop}


def stage_a_rows(stage_a):
    """stage_a (đủ số đo) -> bản gọn cho UI (result.json của job): MỌI cấu hình đã thử, đã xếp theo điểm.
    score = None khi không đạt cổng (JSON không có -Infinity); passed = qua cổng dev1."""
    return {cid: [{"params": r["params"],
                   "dev1": {k: r["dev1"].get(k) for k in ("ret_pct", "mdd_pct", "trades", "symbols_positive", "sharpe")},
                   "score": (r["score"] if r["score"] > float("-inf") else None), "passed": bool(r["score"] > float("-inf"))}
                  for r in rows] for cid, rows in stage_a.items()}


def _peak(results) -> str:
    peaks = [r.get("_peak_rss_mb", 0.0) for r in results if r]
    anon = [r.get("_rss_anon_mb", 0.0) for r in results if r]
    if not peaks:
        return "đỉnh RAM/worker ?"
    return f"đỉnh RAM/worker {max(peaks):.0f} MB (riêng {max(anon):.0f} MB + mmap dùng chung)"


def _peak_of(peak, anon) -> str:
    if not peak:
        return "đỉnh RAM/worker ?"
    return f"đỉnh RAM/worker {peak:.0f} MB (riêng {anon:.0f} MB + mmap dùng chung)"


class TopK:
    """Giữ K hàng tốt nhất theo (-điểm, ord) — đúng K phần tử đầu của `sorted(rows, key=-điểm)` ổn định theo thứ tự sinh cấu hình
    (hoà điểm -> ord nhỏ hơn đứng trước), nhưng RAM O(K) dù có hàng triệu cấu hình."""

    def __init__(self, k):
        self.k = max(1, int(k))
        self._heap = []   # min-heap theo (điểm, -ord): gốc = hàng TỆ nhất trong top-K

    def would_enter(self, score_, ord_):
        return len(self._heap) < self.k or (score_, -ord_) > self._heap[0][:2]

    def offer(self, score_, ord_, row):
        item = (score_, -ord_, row)
        if len(self._heap) < self.k:
            heapq.heappush(self._heap, item)
        elif item[:2] > self._heap[0][:2]:
            heapq.heapreplace(self._heap, item)

    def rows(self):
        return [r for _, _, r in sorted(self._heap, key=lambda t: (-t[0], -t[1]))]


def _job_key(stage, cand_id, job, fingerprint):
    """BacktestJob -> job_key (xem store.make_job_key). Khung chạy khác 1m nằm trong khoá (resume không trộn kết quả hai khung)."""
    extra = {"rpt": job.rpt}
    if job.base_frame != "1m":
        extra["base_frame"] = job.base_frame
    return make_job_key(stage, cand_id, [[cid, prm] for cid, prm in job.items], list(job.window), job.stop_fill, job.risk, fingerprint,
                        extra=extra)


def _pool_shared_stored(jobs, workers, label, shared_dir, store, stage, cand_id, fingerprint, progress=None):
    """Như _pool_shared nhưng mỗi kết quả được ghi vào kho ngay khi xong và job đã có trong kho được bỏ qua (--resume).
    Trả danh sách kết quả ĐÚNG thứ tự jobs, đã chuẩn hoá qua JSON (cùng cấu trúc dù lấy từ kho hay vừa chạy)."""
    keys = [_job_key(stage, cand_id if cand_id is not None else "-", j, fingerprint) for j in jobs]
    results = [None] * len(jobs)
    missing = []
    for i, k in enumerate(keys):
        row = store.get(k)
        if row is not None:
            results[i] = row["metrics"]
            if progress is not None:
                progress.tick(resumed=True)
        else:
            missing.append(i)
    if missing:
        sub = [jobs[i] for i in missing]
        exporter = SharedExporter(shared_dir, label)
        exporter.ensure(sub)

        def _done(j, res):
            i = missing[j]
            results[i] = normalize(res)
            store.put(keys[i], stage, cand_id if cand_id is not None else "-", [[c, p] for c, p in jobs[i].items], results[i], ord=i)
            if progress is not None:
                progress.tick(worker_peak_mb=results[i].get("_peak_rss_mb"))
        _pool_map_safe(run_book, sub, workers, label, on_done=_done)
        exporter.cleanup()
    return results


# Bản dùng chung nằm ở backend.optimize.process.workers / backend.metrics.metrics.portfolio_metrics; giữ tên cũ để code/test hiện có không đổi.
metrics = portfolio_metrics
bootstrap = bootstrap_daily
_pool_map_safe = pool_map_safe
_auto_workers = auto_workers


def _new_run_dir():
    """Thư mục lần chạy MỚI: <thời điểm>; trùng giây (hoặc đã có kho kết quả) thì thêm hậu tố để không bao giờ trộn hai lần chạy."""
    base = time.strftime("%Y%m%d_%H%M%S")
    for n in itertools.count(1):
        name = base if n == 1 else f"{base}_{n}"
        path = alpha_run_dir("book", name)
        if not os.path.exists(os.path.join(path, "results.sqlite")):
            os.makedirs(path, exist_ok=True)
            return path


def _resume_dir(path):
    """--resume: thư mục lần chạy (đường dẫn hoặc tên thư mục trong alpha_run_dir("book")) phải có results.sqlite."""
    cand = path if os.path.isabs(path) or os.path.isdir(path) else os.path.join(alpha_run_dir("book"), path)
    cand = os.path.abspath(cand)
    if not os.path.isfile(os.path.join(cand, "results.sqlite")):
        raise SystemExit(f"--resume: {cand} không có results.sqlite (không phải lần chạy build_strategy_book có kho kết quả)")
    return cand


def _fmt_duration(sec):
    sec = float(sec)
    if sec < 90:
        return f"{sec:.0f} giây"
    if sec < 5400:
        return f"{sec / 60:.1f} phút"
    if sec < 172800:
        return f"{sec / 3600:.1f} giờ"
    return f"{sec / 86400:.1f} ngày"


BOOK_BUILD_DEFAULTS = {"workers": "auto", "per_worker_mb": None, "n": 24, "seed": 7, "only": "", "out": None,   # None = alpha_dir() tại lúc chạy
            "keep_top": 50, "resume": "", "max_configs": 200_000, "force_large": False, "timeframe": "1m"}


def run_book_build(params=None):
    """Dựng sổ chiến lược với `params` (xem DEFAULTS) -> báo cáo (cũng ghi book.json vào `out` + $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(BOOK_BUILD_DEFAULTS, params)
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("build_strategy_book")
    from backend.optimize.process.workers import check_memory_gate, planning_budget_mb
    from backend.data.data import require_data_ok_or_exit
    from backend.optimize.process.process import Progress, graceful_sigterm

    # Cổng chất lượng dữ liệu BẮT BUỘC — trước mọi việc khác và trước khi fork pool (worker thừa kế cache gate)
    require_data_ok_or_exit(perp_symbols())

    # ── Số worker + kiểm RAM trước khi chạy ──────────────────────────────────
    per_worker_mb = a.per_worker_mb or PER_WORKER_MB
    if str(a.workers).strip().lower() == "auto":
        workers = _auto_workers(per_worker_mb)
        print(f"[auto] workers={workers} (ngân sách RAM {planning_budget_mb():.0f} MB, "
              f"trần mỗi worker {per_worker_mb:.0f} MB)", flush=True)
    else:
        workers = int(a.workers)
    check_memory_gate(workers * per_worker_mb, f"build_strategy_book --workers {workers}")

    only = as_list(a.only)
    cands = [c for c in CANDIDATES if not only or c["id"] in only]
    keep = max(3, int(a.keep_top))
    counts_per_cand = {c["id"]: config_count(c, a.n) for c in cands}
    total_configs = sum(counts_per_cand.values())
    if total_configs > a.max_configs and not a.force_large:
        raise SystemExit(f"Từ chối: {total_configs:,} cấu hình dev1 ({len(cands)} chiến lược × n {a.n}) vượt max_configs "
                         f"{a.max_configs:,}. Giảm n / only hoặc đặt force_large nếu thật sự muốn chạy.")
    w = windows(perp_symbols())
    fmt = lambda x: f"{pd.Timestamp(x, unit='ms'):%Y-%m-%d}"
    print(f"dev1 {fmt(w['start'])} → {fmt(w['dev1_end'])} | dev2 → {fmt(w['dev2_end'])} | holdout → {fmt(w['end'])}", flush=True)
    print(f"workers={workers} | NORA_CANDLE_CACHE_MB={os.environ['NORA_CANDLE_CACHE_MB']} "
          f"| NORA_DATA_CACHE_MB={os.environ['NORA_DATA_CACHE_MB']} | trần mỗi worker {per_worker_mb:.0f} MB", flush=True)
    eval_risk = {**RISK, "kill_switch_dd_pct": 0}
    resuming = bool(a.resume)
    run_dir = _resume_dir(a.resume) if resuming else _new_run_dir()
    store = ResultsStore(run_dir)
    progress = Progress(run_dir)
    fingerprint = data_fingerprint(perp_symbols())
    run_args = {"n": a.n, "seed": a.seed, "only": ",".join(only), "keep_top": keep}
    if resuming:
        old = store.get_meta("args")
        if old and {k: old.get(k) for k in ("n", "seed", "only")} != {k: run_args[k] for k in ("n", "seed", "only")}:
            print(f"[WARN] resume: tham số lần chạy cũ {old} khác lần này {run_args} — chỉ job trùng job_key được dùng lại", flush=True)
        print(f"[resume] {run_dir}: kho đã có {store.count():,} kết quả", flush=True)
    store.set_meta("args", run_args)
    report = {"windows": {k: fmt(v) for k, v in w.items()}, "gates": GATES, "risk": RISK, "candidates": {}}
    shared_dir = os.path.join(run_dir, "_shared")
    os.environ["NORA_SHARED_DATA_DIR"] = shared_dir  # đặt TRƯỚC khi tạo pool (fork kế thừa); PortfolioEngine đọc biến này
    try:
        with graceful_sigterm(progress):
            return _run(a, cands, keep, counts_per_cand, total_configs, w, fmt, eval_risk, run_dir, store, progress, fingerprint,
                        workers, per_worker_mb, report, shared_dir, resuming,
                        (BASE_RISK_PER_TRADE_PCT, GATES, RISK))
    finally:
        store.close()   # flush lô ghi cuối (cả khi bị SIGTERM / ngoại lệ) -> --resume dùng được


def _run(a, cands, keep, counts_per_cand, total_configs, w, fmt, eval_risk, run_dir, store, progress, fingerprint,
         workers, per_worker_mb, report, shared_dir, resuming, consts):
    BASE_RISK_PER_TRADE_PCT, GATES, RISK = consts
    tf = a.timeframe or "1m"   # khung chạy (nến mô phỏng) của mọi backtest trong lần dựng sổ

    # ── A. dev1 — STREAMING: cấu hình sinh lười -> pool (bounded) -> kho; cha chỉ giữ top-K ───────────
    t0 = time.time()
    stage_a, stage_a_counts, estimate = {}, {}, {"overall": None, "candidates": {}}
    progress.start_stage("A", total_configs)
    for c in cands:
        cid, n_c = c["id"], counts_per_cand[c["id"]]
        progress.stage = f"A · {cid}"
        top = TopK(keep)
        counts = {"tried": 0, "passed": 0}
        peaks = {"peak": 0.0, "anon": 0.0}
        exporter = SharedExporter(shared_dir, f"[A] {cid}")

        def handle(ord_, params, m, from_store, top=top, counts=counts, peaks=peaks):
            sc = score(m, GATES)[0]
            counts["tried"] += 1
            counts["passed"] += sc > float("-inf")
            peaks["peak"] = max(peaks["peak"], m.get("_peak_rss_mb", 0.0))
            peaks["anon"] = max(peaks["anon"], m.get("_rss_anon_mb", 0.0))
            keep_full = top.would_enter(sc, ord_)
            if keep_full:   # hàng có thể thuộc top-K: giữ nguyên (gồm chuỗi `daily`, như stage_a.json cũ)
                top.offer(sc, ord_, {"params": params, "dev1": m, "score": sc})
                stored = m
            else:           # không thuộc top-K: bỏ chuỗi daily + số đo RAM trước khi lưu (RAM cha phẳng, kho gọn)
                stored = {k: v for k, v in m.items() if k not in ("daily", "stats", "_peak_rss_mb", "_rss_anon_mb")}
            return stored, sc

        def jobs(c=c, cid=cid):
            for ord_, cfg in enumerate(iter_configs(c, a.n, a.seed)):
                yield ord_, cfg, BacktestJob([(cid, cfg)], (w["start"], w["dev1_end"]), "level", eval_risk, BASE_RISK_PER_TRADE_PCT,
                                             base_frame=tf)

        stream_kw = dict(store=store, stage="A", candidate=cid, key_of=lambda o, p, j: _job_key("A", cid, j, fingerprint),
                         handle=handle, progress=progress, prepare=exporter)
        it = jobs()
        # Hiệu chỉnh: chạy 1 cấu hình đầu của chiến lược (1 worker) để đo giây/cấu hình -> ước lượng thời gian cả giai đoạn
        first = next(it, None)
        sec = None
        if first is not None and n_c <= workers:
            # Một lượt song song duy nhất: hiệu chỉnh riêng chỉ làm chậm thêm đúng một độ trễ job -> bỏ; thời gian ≈ một cấu hình
            it = itertools.chain([first], it)
            first = None
            estimate["candidates"][cid] = {"configs": n_c, "workers": workers, "calibrated": False,
                                           "note": "≤ số worker: chạy một lượt song song, thời gian ≈ thời gian một cấu hình"}
            print(f"[estimate] {cid}: {n_c:,} cấu hình ≤ {workers} worker -> một lượt song song (≈ thời gian một cấu hình)", flush=True)
        if first is not None:
            if not store.has(_job_key("A", cid, first[2], fingerprint)):
                exporter(first[2])   # xuất dữ liệu dùng chung TRƯỚC khi bấm giờ: chỉ đo thời gian chạy một cấu hình
            t_cal = time.time()
            r = stream_stage([first], run_book, workers=1, label=f"[A] {cid} (hiệu chỉnh)", **stream_kw)
            sec = (time.time() - t_cal) if r["new"] else store.get_meta(f"sec_per_config:{cid}")
            if r["new"]:
                store.set_meta(f"sec_per_config:{cid}", sec)
        if sec:
            remaining = sum(counts_per_cand[x["id"]] for x in cands[cands.index(c):])
            est_c = {"configs": n_c, "sec_per_config": round(sec, 3), "workers": workers, "eta_s": round(n_c * sec / workers, 1)}
            estimate["candidates"][cid] = est_c
            if estimate["overall"] is None:
                estimate["overall"] = {"configs": total_configs, "sec_per_config": round(sec, 3), "workers": workers,
                                       "eta_s": round(total_configs * sec / workers, 1), "calibrated_on": cid}
                print(f"[estimate] {total_configs:,} cấu hình × {sec:.2f} s/cấu hình (đo trên {cid}) / {workers} worker "
                      f"≈ {_fmt_duration(total_configs * sec / workers)} (giai đoạn A)", flush=True)
            print(f"[estimate] {cid}: {n_c:,} cấu hình × {sec:.2f} s / {workers} worker ≈ {_fmt_duration(n_c * sec / workers)} "
                  f"(còn {remaining:,} cấu hình tính từ chiến lược này)", flush=True)
            with open(os.path.join(run_dir, "estimate.json"), "w", encoding="utf-8") as fh:
                json.dump(estimate, fh, ensure_ascii=False, indent=1)
            progress.set_estimate(estimate)
        stream_stage(it, run_book, workers=workers, label=f"[A] {cid}", max_inflight=workers * 4, **stream_kw)
        exporter.cleanup()
        rows = top.rows()
        stage_a[cid] = rows
        stage_a_counts[cid] = {"tried": counts["tried"], "passed": counts["passed"], "kept": len(rows)}
        best = rows[0]
        print(
            f"[A] {cid:18s} {counts['tried']} cấu hình, đạt {counts['passed']}; "
            f"tốt nhất: lãi {best['dev1']['ret_pct']}% MDD {best['dev1']['mdd_pct']}% lệnh {best['dev1']['trades']} "
            f"+{best['dev1']['symbols_positive']}/8  ({time.time() - t0:.0f}s | {_peak_of(peaks['peak'], peaks['anon'])})", flush=True
        )
        store.flush()
        # Ghi checkpoint sau mỗi chiến lược — không mất kết quả nếu sập giữa chừng (chỉ top-K; toàn bộ hàng nằm trong results.sqlite)
        with open(os.path.join(run_dir, "stage_a.json"), "w", encoding="utf-8") as fh:
            json.dump(stage_a, fh, ensure_ascii=False, indent=1, default=json_default)
        with open(os.path.join(run_dir, "stage_a_counts.json"), "w", encoding="utf-8") as fh:
            json.dump(stage_a_counts, fh, ensure_ascii=False, indent=1)

    # ── B. dev2 — cũng một pool riêng cho MỖI chiến lược (cache không dồn qua các chiến lược) ──
    out = {}
    b_plan = []
    for c in cands:
        top = [r for r in stage_a[c["id"]][:3] if r["score"] > float("-inf")]
        keys = [(c["id"], rank, sf) for rank in range(len(top)) for sf in ("level", "extreme")]
        if keys:
            b_plan.append((c, top, keys))
    progress.start_stage("B", sum(len(k) for _, _, k in b_plan))
    for c, top, keys in b_plan:
        jobs_b = [BacktestJob([(cid, top[rank]["params"])], (w["dev1_end"], w["dev2_end"]), sf, eval_risk, BASE_RISK_PER_TRADE_PCT,
                              base_frame=tf) for cid, rank, sf in keys]
        res_c = _pool_shared_stored(jobs_b, workers, f"[B] {c['id']}", shared_dir, store, "B", c["id"], fingerprint, progress)
        out.update(zip(keys, res_c))
        print(f"[B] {c['id']:18s} {len(jobs_b)} lần chạy dev2 xong ({time.time() - t0:.0f}s | "
              f"{_peak(res_c)})", flush=True)

    accepted = []
    for c in cands:
        top = [r for r in stage_a[c["id"]][:3] if r["score"] > float("-inf")]
        entry = {"description": c["description"], "side": c["side"], "family": c["family"],
                 "dev1_tried": stage_a_counts[c["id"]]["tried"], "dev1_top": [{"params": r["params"], "dev1": strip_metrics(r["dev1"])} for r in top]}
        passes = []
        for rank, r in enumerate(top):
            lv, ex = out[(c["id"], rank, "level")], out[(c["id"], rank, "extreme")]
            ok = bool(score(lv, GATES, "min_symbols_positive_dev2")[1] and ex["ret_pct"] > 0 and ex["mdd_pct"] <= MDD_LIMIT)
            passes.append(ok)
            entry["dev1_top"][rank]["dev2_level"] = strip_metrics(lv)
            entry["dev1_top"][rank]["dev2_extreme"] = strip_metrics(ex)
            entry["dev1_top"][rank]["dev2_pass"] = ok
        entry["accepted"] = bool(bool(top) and passes[0])
        entry["stability"] = f"{sum(passes)}/{len(passes)}" if passes else "0/0"
        if entry["accepted"]:
            accepted.append((c["id"], top[0]["params"], out[(c["id"], 0, "extreme")]))
        report["candidates"][c["id"]] = entry
        lv = out.get((c["id"], 0, "level"))
        ex = out.get((c["id"], 0, "extreme"))
        print(f"[B] {c['id']:18s} " + (f"dev2 level {lv['ret_pct']}%/MDD {lv['mdd_pct']}%/+{lv['symbols_positive']}/8, "
                                       f"extreme {ex['ret_pct']}%/MDD {ex['mdd_pct']}% — "
                                       if lv else "không có cấu hình qua dev1 — ")
              + ("ĐẠT" if entry["accepted"] else "LOẠI") + f" (ổn định {entry['stability']})", flush=True)

    # Ghi checkpoint giai đoạn B
    with open(os.path.join(run_dir, "stage_b.json"), "w", encoding="utf-8") as fh:
        json.dump({"candidates": report["candidates"]}, fh, ensure_ascii=False, indent=1, default=json_default)

    if not accepted:
        report["book"] = None
        print("\nKHÔNG có chiến lược nào đạt — không tạo sổ (không nới gate).")
    else:
        items = [(cid, prm) for cid, prm, _ in accepted]
        progress.start_stage("C", 2)
        base_dev2 = _pool_shared_stored(
            [BacktestJob(items, (w["dev1_end"], w["dev2_end"]), sf, RISK, BASE_RISK_PER_TRADE_PCT, base_frame=tf) for sf in ("level", "extreme")],
            workers, "[C] base_dev2", shared_dir, store, "C", "book", fingerprint, progress,
        )
        sizing = {str(s): bootstrap(base_dev2[1]["daily"], s) for s in RISK_SCALES}
        ok_scales = [s for s in RISK_SCALES if sizing[str(s)]["p_mdd_ge_30_pct"] <= RUIN_MAX_PCT]
        scale = max(ok_scales) if ok_scales else 0.0
        rpt = round(min(BASE_RISK_PER_TRADE_PCT * scale, MAX_RISK_PER_TRADE), 3)
        print(f"\n[C] sổ {[i[0] for i in items]}: dev2 rủi ro chuẩn — level {base_dev2[0]['ret_pct']}% / MDD "
              f"{base_dev2[0]['mdd_pct']}%, extreme {base_dev2[1]['ret_pct']}% / MDD {base_dev2[1]['mdd_pct']}%")
        for s in RISK_SCALES:
            b = sizing[str(s)]
            print(f"    rủi ro {BASE_RISK_PER_TRADE_PCT * s:.3f}%/lệnh: lãi 1 năm trung vị {b['median_ret_pct']}%, "
                  f"MDD p95 {b['mdd_p95_pct']}%, P(MDD>=30%) {b['p_mdd_ge_30_pct']}%")
        print(f"    -> rủi ro mỗi lệnh chốt: {rpt}%", flush=True)
        final = {}
        if rpt > 0:
            fin_jobs = [BacktestJob(items, win, sf, RISK, rpt, base_frame=tf)
                        for win in ((w["dev1_end"], w["dev2_end"]), (w["dev2_end"], w["end"]))
                        for sf in ("level", "extreme")]
            progress.start_stage("D", len(fin_jobs))
            res = _pool_shared_stored(fin_jobs, workers, "[D] holdout", shared_dir, store, "D", "book", fingerprint, progress)
            final = {"dev2_level": strip_metrics(res[0]), "dev2_extreme": strip_metrics(res[1]),
                     "holdout_level": strip_metrics(res[2]), "holdout_extreme": strip_metrics(res[3])}
            for k in ("dev2_level", "dev2_extreme", "holdout_level", "holdout_extreme"):
                m = final[k]
                print(f"[D] {k:16s} lãi {m['ret_pct']}%  MDD {m['mdd_pct']}%  sharpe {m['sharpe']}  lệnh {m['trades']}  "
                      f"+{m['symbols_positive']}/8  kill={'có' if m['halted_at'] else 'không'}  {m['by_strategy']}")
        report["book"] = {
            "strategies": [{"id": cid, "params": prm} for cid, prm in items],
            "risk_per_trade_pct": rpt, "risk": RISK, "risk_scale_bootstrap": sizing,
            "dev2_base_risk": {"level": strip_metrics(base_dev2[0]), "extreme": strip_metrics(base_dev2[1])},
            "final": final,
            "holdout_pass": bool(bool(final) and final["holdout_level"]["ret_pct"] > 0
                                 and final["holdout_level"]["mdd_pct"] <= MDD_LIMIT
                                 and final["holdout_extreme"]["mdd_pct"] <= MDD_LIMIT),
        }

    # Chạy xong thành công: xoá dữ liệu dùng chung (lỗi/ngoại lệ thì không tới đây -> còn nguyên để gỡ lỗi)
    if os.path.isdir(shared_dir):
        import shutil
        from backend.optimize.search import evaluate as shared_data
        print(f"[shared] xoá {shared_dir} ({shared_data.size_mb(shared_dir):.0f} MB còn lại; mỗi giai đoạn đã tự dọn kho của nó)", flush=True)
        shutil.rmtree(shared_dir, ignore_errors=True)

    report["timeframe"] = tf
    # Ghi báo cáo cuối
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=json_default)
    print("báo cáo:", os.path.join(run_dir, "report.json"))
    paths = []
    if report.get("book"):
        from backend.optimize.book.registry import write_book
        paths = write_book(report, a.out or alpha_dir(), source=run_dir, repo_dir=os.path.dirname(NORA_DIR))
        for path in paths:
            print("ghi:", path)
        if len(paths) == 1:  # holdout không đạt: chỉ có book.json (HOLDOUT_FAILED), không có cấu hình testnet
            print("HOLDOUT KHÔNG ĐẠT — không tạo data/alpha/testnet/book.json.")
    store.flush()
    progress.finish("done")
    write_job_result({**report, "run_dir": run_dir, "written": paths, "stage_a": stage_a_rows(stage_a),
                      "stage_a_counts": stage_a_counts, "estimate": estimate,
                      "store": {"path": os.path.join(run_dir, "results.sqlite"), "rows": store.count()}})  # chỉ khi chạy như job API (env NORA_JOB_DIR)


# ══════════════════════════════════════════════════════════════════════════
# Bộ tham số tốt nhất ("preset") của từng chiến lược ứng viên — dùng cho chế độ Cơ bản của UI/API.
#
# Nguồn:
#   book    sổ đã chốt data/alpha/book.json (biến NORA_BOOK_PATH): tham số + bằng chứng dev1/dev2 của chiến lược trong sổ.
#   stage_a lần chạy backend.optimize.book MỚI NHẤT trong data/alpha/book/ có cấu hình QUA CỔNG dev1 cho chiến lược đó:
#           cấu hình có điểm BỀN cao nhất trên dev1 (điểm = lãi / MDD, trung bình cùng lân cận lưới; xem robust_scores).
#   default giá trị mặc định của params_schema ("mặc định — chưa tối ưu"), không có bằng chứng, timeframe=None.
# Có cả book lẫn stage_a: nguồn đã qua dev2 thắng; cùng mức thì bằng chứng mới hơn thắng (book: generated_at, stage_a: tên run).
# Mỗi preset ghi `timeframe` = khung chạy lúc tối ưu (dữ liệu cũ không ghi -> "1m").
# `params` của preset luôn ĐẦY ĐỦ mọi khoá của params_schema (khoá thiếu lấy mặc định) để UI hiển thị/sửa; khi chạy job chỉ cần phần khác mặc định
# (routes/modes.job_params). File xuất ra: data/alpha/presets.json (job presets_build = run_job cuối file này).
# ══════════════════════════════════════════════════════════════════════════

PRESETS_VERSION = 1
SOURCE_DEFAULT = "mặc định — chưa tối ưu"
METRIC_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "halted_at")


def book_path() -> str:
    return os.environ.get("NORA_BOOK_PATH") or os.path.join(alphas_dir(), "book.json")


def presets_path() -> str:
    return os.environ.get("NORA_PRESETS_PATH") or os.path.join(alphas_dir(), "presets.json")


def book_timeframe() -> str:
    book = read_json(book_path())
    return (book or {}).get("timeframe", "1m") if isinstance(book, dict) else "1m"


def _metrics(m: Any) -> Optional[Dict[str, Any]]:
    return {k: m[k] for k in METRIC_KEYS if k in m} if isinstance(m, dict) else None


def _clean_params(candidate: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """Mặc định schema, ghi đè bằng khoá của `raw` thuộc schema (khoá lạ bị bỏ)."""
    schema = candidate["params_schema"]
    params = dict(schema_defaults(candidate))
    for key, value in (raw or {}).items():
        spec = schema.get(key)
        if spec is None or isinstance(value, bool):
            continue
        if spec["type"] == "choice":
            if value in spec["choices"]:
                params[key] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            params[key] = int(value) if spec["type"] == "int" and float(value).is_integer() else value
    return params


def _date_vi(ms: Any) -> Optional[str]:
    try:
        return time.strftime("%d/%m", time.gmtime(float(ms) / 1000.0))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_book_time(book: Optional[Dict[str, Any]]) -> float:
    ts = book.get("generated_at") if isinstance(book, dict) else None
    return float(ts) / 1000.0 if isinstance(ts, (int, float)) else 0.0


def _parse_run_time(name: Optional[str]) -> float:
    """Tên thư mục run: YYYYMMDD_HHMMSS (UTC) -> giây epoch; tên khác -> 0."""
    try:
        return float(calendar.timegm(time.strptime((name or "")[:15], "%Y%m%d_%H%M%S")))
    except ValueError:
        return 0.0


def _evidence_time(preset: Dict[str, Any], book_ts: float) -> float:
    return book_ts if preset["source_kind"] == "book" else _parse_run_time(preset["evidence"].get("run"))


def _verified(preset: Dict[str, Any]) -> bool:
    """Sổ chỉ chứa chiến lược đã qua dev2; stage A thì xem dev2_verified (chỉ khi cấu hình bền nằm trong top-K đã kiểm dev2)."""
    return preset["source_kind"] == "book" or preset["evidence"].get("dev2_verified") is True


# ─── Nguồn 1: book.json ─────────────────────────────────────────────────────
def from_book(book: Optional[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(book, dict):
        return out
    by_id = {c["id"]: c for c in candidates}
    when = _date_vi(book.get("generated_at"))
    label = f"book.json (sổ đã build {when})" if when else "book.json"
    tf = book.get("timeframe", "1m")
    for s in book.get("strategies") or []:
        cand = by_id.get(s.get("id"))
        if cand is None:
            continue
        raw = {**(s.get("params") or {})}
        if book.get("risk_per_trade_pct") is not None:
            raw.setdefault("risk_per_trade_pct", book["risk_per_trade_pct"])
        ev = s.get("evidence") or {}
        top = (ev.get("dev1_top") or [{}])[0]
        out[cand["id"]] = {
            "params": _clean_params(cand, raw), "timeframe": tf, "source": label, "source_kind": "book",
            "evidence": {"stage": "book", "timeframe": tf, "accepted": ev.get("accepted"), "stability": ev.get("stability"),
                         "dev1_tried": ev.get("dev1_tried"), "dev1": _metrics(top.get("dev1")),
                         "dev2_level": _metrics(top.get("dev2_level")), "dev2_extreme": _metrics(top.get("dev2_extreme")),
                         "holdout_pass": book.get("holdout_pass"), "book_status": book.get("status")},
        }
    return out


# ─── Nguồn 2: lần build gần nhất có cấu hình qua cổng dev1 ───────────────────
def _passing_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows or []:
        sc = r.get("score")
        if isinstance(sc, (int, float)) and sc > float("-inf") and math.isfinite(sc):
            out.append(r)
    return out


def _bool(v: Any) -> Optional[bool]:
    """Báo cáo cũ lưu bool numpy thành chuỗi "True"/"False" (json default=str) -> bool thật; None giữ None."""
    if v is None or isinstance(v, bool):
        return v
    if v in ("True", "False"):
        return v == "True"
    return bool(v)


def _all_rows(run: str, cid: str, stage_a: Dict[str, Any]) -> List[Dict[str, Any]]:
    """MỌI cấu hình đã thử ở stage A của chiến lược (kho results.sqlite của lần dựng sổ; thiếu kho -> top-K trong stage_a.json).
    -> [{"params", "score" (None/-inf = trượt cổng dev1), "dev1"}]."""
    if os.path.isfile(os.path.join(run, "results.sqlite")):
        from backend.optimize.funnel.storage import ResultsStore
        st = ResultsStore(run, read_only=True)
        try:
            rows = [{"params": r["params"], "score": r["score"], "dev1": r["metrics"]} for r in st.iter_rows("A", cid)]
        finally:
            st.close()
        if rows:
            return rows
    return list(stage_a.get(cid) or [])


def robust_scores(rows: List[Dict[str, Any]]) -> List[float]:
    """Điểm BỀN của từng cấu hình (chỉ dùng dev1): trung bình điểm của chính nó và mọi lân cận lưới (±1 bước trên đúng một khoá, lưới dựng
    từ các giá trị đã thử). Cấu hình trượt cổng / lân cận không có trong danh sách tính 0 — đỉnh nhọn giữa vùng trượt bị hạ điểm."""
    from backend.wfa.wfa import neighbours
    def key(p):
        return json.dumps(p, sort_keys=True)
    space: Dict[str, List[Any]] = {}
    for r in rows:
        for k, v in (r.get("params") or {}).items():
            space.setdefault(k, [])
            if v not in space[k]:
                space[k].append(v)
    space = {k: sorted(v, key=lambda x: (isinstance(x, str), x)) for k, v in space.items() if len(v) > 1}
    sc = {}
    for r in rows:
        v = r.get("score")
        sc[key(r.get("params") or {})] = float(v) if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else 0.0
    out = []
    for r in rows:
        pts = [r.get("params") or {}] + neighbours(space, r.get("params") or {})
        out.append(sum(sc.get(key(p), 0.0) for p in pts) / len(pts))
    return out


def from_build_runs(runs_dir: str, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Duyệt các lần chạy từ MỚI tới CŨ; mỗi chiến lược lấy lần chạy mới nhất có cấu hình qua cổng dev1. Chọn cấu hình qua cổng có ĐIỂM BỀN
    (robust_scores: trung bình cùng lân cận lưới) cao nhất — CHỈ dùng dev1. Không dùng dev2 để chọn: WFA kiểm trên dev2, chọn theo dev2 là rò rỉ.
    Kết quả dev2 của top-K (nếu cấu hình nằm trong đó) chỉ để hiển thị: dev2_verified True/False, hoặc None khi chưa có."""
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(runs_dir):
        return out
    by_id = {c["id"]: c for c in candidates}
    todo = list(by_id)
    for name in sorted(os.listdir(runs_dir), reverse=True):
        if not todo:
            break
        run = os.path.join(runs_dir, name)
        stage_a = read_json(os.path.join(run, "stage_a.json"))
        report = read_json(os.path.join(run, "report.json"))
        if not isinstance(stage_a, dict) or not isinstance(report, dict):
            continue
        tf = report.get("timeframe", "1m")
        for cid in list(todo):
            rows = _all_rows(run, cid, stage_a)
            ok = [i for i, r in enumerate(rows) if _passing_rows([r])]
            if not ok:
                continue
            rob = robust_scores(rows)
            pick = max(ok, key=lambda i: rob[i])   # max ổn định: hoà -> cấu hình đứng trước
            best = rows[pick]
            entry = (report.get("candidates") or {}).get(cid) or {}
            top = next((t for t in entry.get("dev1_top") or [] if t.get("params") == best.get("params")), None)
            evidence = {"stage": "dev1", "run": name, "timeframe": tf, "dev1_tried": entry.get("dev1_tried"),
                        "score": round(float(best["score"]), 4), "robust_score": round(rob[pick], 4), "dev1": _metrics(best.get("dev1")),
                        "dev2_verified": _bool(top.get("dev2_pass")) if top is not None else None}
            if top is not None:   # có trong top-K: kèm kết quả dev2 (chỉ hiển thị)
                evidence.update(accepted=_bool(entry.get("accepted")), stability=entry.get("stability"),
                                dev2_pass=_bool(top.get("dev2_pass")), dev2_level=_metrics(top.get("dev2_level")),
                                dev2_extreme=_metrics(top.get("dev2_extreme")))
            out[cid] = {
                "params": _clean_params(by_id[cid], best.get("params") or {}), "timeframe": tf,
                "source": f"build {name} stage A bền vững dev1 (điểm cùng lân cận)", "source_kind": "stage_a", "evidence": evidence,
            }
            todo.remove(cid)
    return out


# ─── Dựng + đọc ─────────────────────────────────────────────────────────────
def build_presets(book: Optional[Dict[str, Any]] = None, runs_dir: Optional[str] = None,
                  use_book_file: bool = True) -> Dict[str, Any]:
    """Dựng bảng preset cho mọi chiến lược lõi (luật chọn nguồn: đầu file).
    book=None -> đọc book.json hiện hành; runs_dir=None -> data/alpha/book/."""
    if book is None and use_book_file:
        book = read_json(book_path())
    if runs_dir is None:
        from backend.models.storage import cache_dir
        runs_dir = cache_dir(None, "book")
    book_items = from_book(book, CANDIDATES)
    stage_a_items = from_build_runs(runs_dir, CANDIDATES)
    book_ts = _parse_book_time(book)
    presets: Dict[str, Any] = {}
    for c in CANDIDATES:
        found = [p for p in (book_items.get(c["id"]), stage_a_items.get(c["id"])) if p]
        if found:   # qua dev2 trước; cùng mức thì bằng chứng mới hơn thắng (hoà -> book)
            presets[c["id"]] = max(found, key=lambda p: (_verified(p), _evidence_time(p, book_ts)))
        else:
            presets[c["id"]] = {"params": dict(schema_defaults(c)), "timeframe": None,
                                "source": SOURCE_DEFAULT, "source_kind": "default", "evidence": None}
    return {"version": PRESETS_VERSION, "generated_at": int(time.time() * 1000), "presets": presets}


def write_presets(doc: Dict[str, Any], path: Optional[str] = None) -> str:
    path = path or presets_path()
    atomic_write_json(path, doc, indent=1, clean=False, allow_nan=True)
    return path


def load_presets(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{id: {params, timeframe, source, source_kind, evidence}} cho MỌI chiến lược lõi. Đọc presets.json; chiến lược thiếu/hỏng -> mặc định schema
    (không ghi file). File được kiểm lại theo schema hiện hành (khoá lạ bỏ, thiếu thì điền mặc định)."""
    doc = read_json(path or presets_path())
    stored = (doc or {}).get("presets") if isinstance(doc, dict) else None
    stored = stored if isinstance(stored, dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for c in all_candidates():      # cả chiến lược cũ: sổ / lượt phễu đã có vẫn đọc được
        p = stored.get(c["id"])
        if isinstance(p, dict) and isinstance(p.get("params"), dict):
            out[c["id"]] = {"params": _clean_params(c, p["params"]), "timeframe": p.get("timeframe"),
                            "source": p.get("source") or SOURCE_DEFAULT,
                            "source_kind": p.get("source_kind") or "default", "evidence": p.get("evidence")}
        else:
            out[c["id"]] = {"params": dict(schema_defaults(c)), "timeframe": None,
                            "source": SOURCE_DEFAULT, "source_kind": "default", "evidence": None}
    return out


# ─── Job dựng presets.json (POST /api/studio/strategies/presets) ────────────
def _key_params(params, schema):
    """Chỉ các tham số khác mặc định (để bảng gọn)."""
    return {k: v for k, v in params.items() if v != schema[k]["default"]}


def format_table(doc):
    lines = []
    for c in CANDIDATES:
        p = doc["presets"][c["id"]]
        tf = p.get("timeframe")
        tf_label = f"[{tf}]" if tf else "[—]"
        ev = (p.get("evidence") or {}).get("dev1") or {}
        ev_txt = (f" | dev1 lãi {ev.get('ret_pct')}% MDD {ev.get('mdd_pct')}% sharpe {ev.get('sharpe')} lệnh {ev.get('trades')} "
                  f"+{ev.get('symbols_positive')}") if ev else ""
        full = p.get("evidence") or {}
        d2 = full.get("dev2_extreme") or {}
        ev_txt += (f" | dev2(extreme) lãi {d2.get('ret_pct')}% MDD {d2.get('mdd_pct')}% — "
                   f"{'ĐẠT' if full.get('dev2_pass', full.get('accepted')) is True else 'LOẠI'} dev2") if d2 else ""
        lines.append(f"{c['id']:18s} {tf_label} {p['source']}{ev_txt}")
        lines.append(f"{'':18s} khác mặc định: {_key_params(p['params'], c['params_schema']) or '(không — toàn bộ là mặc định)'}")
    return "\n".join(lines)


def run_presets_build(params=None) -> Dict[str, Any]:
    """Dựng presets.json từ file có sẵn (không chạy backtest). params: out, book, runs_dir, dry_run."""
    a = options({"out": "", "book": "", "runs_dir": "", "dry_run": False}, params)
    doc = build_presets(book=read_json(a.book or book_path()), runs_dir=a.runs_dir or None, use_book_file=False)
    print(format_table(doc))
    if not a.dry_run:
        print("ghi:", write_presets(doc, a.out or None))
    write_job_result(doc)
    return doc
