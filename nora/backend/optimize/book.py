"""Chốt sổ chiến lược: tín hiệu + chiến lược + phân bổ vốn + phân bổ rủi ro (tham số theo chiến lược, không theo tài sản).

|──────────── dev 80% ─────────────|── holdout 20% ──|
|── dev1: chọn tham số ─|─ dev2 ───|   chấm 1 lần    |

A. dev1  — mỗi chiến lược ứng viên: thử các cấu hình trên CẢ vũ trụ 8 tài sản (backtest danh mục, rủi ro chuẩn
           0,5%/lệnh, SL khớp đúng mức). Điểm = lãi / MDD; bắt buộc đủ lệnh và >= 5/8 tài sản có lãi. Giữ top-3.
B. dev2  — cấu hình top-1 của mỗi chiến lược phải: lãi với SL khớp đúng mức VÀ khớp bi quan, MDD <= 30%,
           đủ lệnh, >= 4/8 tài sản có lãi. Top-2, top-3 chỉ để đo độ ổn định (không dùng để chọn).
C. sổ    — các chiến lược đạt chạy CHUNG một sổ vốn với giới hạn danh mục (RiskConfig). Rủi ro mỗi lệnh như nhau
           cho mọi chiến lược (khối lượng đã tự quy đổi theo ATR). Mức rủi ro/lệnh cuối = mức lớn nhất sao cho
           bootstrap 1 năm trên lợi suất ngày dev2 (SL bi quan) có P(MDD >= 30%) <= 5%.
D. holdout — chạy đúng sổ đã chốt một lần (cả hai cách khớp SL). Không chọn lại gì ở bước này.

Job API (POST /api/studio/book/build -> api/jobs/runner.py -> run_job(params)); tham số và mặc định: DEFAULTS
(workers, per_worker_mb, n, seed, only, out, keep_top, resume, max_configs, force_large).
Quy mô lớn (tới ~1.000.000 cấu hình): giai đoạn A chạy STREAMING — cấu hình sinh lười, mỗi kết quả ghi ngay vào <run_dir>/results.sqlite
(backend/optimize/results_store.py), tiến trình cha chỉ giữ top-K (K = max(3, keep_top), mặc định 50) nên RAM cha phẳng.
  resume=<run_dir>     chạy tiếp lần bị ngắt (bỏ qua job đã có trong kho; kết quả cuối y hệt lần chạy không gián đoạn)
  max_configs=N        từ chối khi tổng số cấu hình > N (mặc định 200000) trừ khi force_large; trước khi chạy in ước lượng
                       (số cấu hình × giây đo thực của 1 cấu hình / số worker) và ghi <run_dir>/estimate.json
  tiến độ: <run_dir>/progress.json (tối đa mỗi 5 giây); SIGTERM -> flush kho rồi thoát (resume được).
  stage_a.json / result.json chỉ chứa top-K mỗi chiến lược + số đếm (stage_a_counts.json: tried/passed); toàn bộ hàng xem qua kho.
Kết quả: data/alphas/book.json (+ data/alphas/testnet/book.json CHỈ khi holdout đạt; trượt holdout -> status HOLDOUT_FAILED, không có testnet), báo cáo tại <data>/_cache/book/<thời điểm>/.

Bộ nhớ (mỗi worker là một tiến trình có cache riêng):
  NORA_CANDLE_CACHE_MB   ngân sách cache nến cả file (script này mặc định 512 MB)
  NORA_DATA_CACHE_MB     ngân sách cache mảng giá + kernel theo cửa sổ (script này mặc định 1024 MB)
  RAM một worker: mặc định PER_WORKER_MB (số ĐO THỰC, chỉ để hoạch định số worker + cổng RAM; rào cứng là
  trần cgroup — worker vượt thì bị giết riêng, _pool_map_safe chạy lại với một nửa số worker).
  Đo lại bằng dòng `đỉnh RAM/worker` và ghi đè bằng per_worker_mb khi dữ liệu/ngân sách cache đổi.
  workers="auto" đọc cả giới hạn cgroup (systemd-run -p MemoryMax=...), không chỉ RAM trống của máy.
  BẮT BUỘC chạy dưới trần RAM (job API luôn qua backend/utils/ops/run_limited.sh; không có trần cgroup thì từ chối, trừ khi NORA_ALLOW_UNLIMITED=1).
  Dữ liệu dùng chung: trước mỗi pool, tiến trình CHA dựng một lần mảng giá + kernel + funding của cả vũ trụ vào
  <run_dir>/_shared/ (backend/core/data/shared.py); worker chỉ np.load(mmap_mode="r") qua NORA_SHARED_DATA_DIR
  -> RAM riêng (anon) mỗi worker nhỏ, trang file chỉ tính MỘT lần trong cgroup. Chạy xong thì xoá _shared (lỗi thì giữ lại).
  OMP_NUM_THREADS / OPENBLAS_NUM_THREADS / MKL_NUM_THREADS đặt = "1" nếu chưa có.
"""
# ── Đặt TRƯỚC mọi import numpy/backend: tiến trình con kế thừa qua fork ──────
import os
for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")
os.environ.setdefault("NORA_CANDLE_CACHE_MB", "512")
os.environ.setdefault("NORA_DATA_CACHE_MB", "1024")
# ─────────────────────────────────────────────────────────────────────────────

import heapq
import itertools
import json
import random
import sys
import time
import warnings

import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.carlo.monte_carlo import bootstrap_daily
from backend.core.metrics.portfolio import portfolio_metrics
from backend.utils.parallel import auto_workers, pool_map_safe
from backend.optimize.results_store import ResultsStore, data_fingerprint, make_job_key
from backend.optimize.stream import normalize, stream_stage
from backend.utils.jobs import as_list, options, write_job_result
from backend.utils.jsonsafe import json_default

DAY = 86_400_000
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
    from backend.db.local_pkl import read_manifest
    ms = [read_manifest(s) for s in symbols]
    start = max(int(m["start_ts"]) for m in ms) + WARMUP
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    return {"start": start, "dev1_end": start + int(span * 0.4), "dev2_end": start + int(span * 0.8), "end": end}


def _make_engine(job):
    """job = (strategies [(candidate_id, params)], window (start, end), stop_fill, risk dict, risk_per_trade)."""
    from backend.core.strategy.book import CANDIDATES, materialize, perp_symbols
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    items, (start, end), stop_fill, risk, rpt = job
    by_id = {c["id"]: c for c in CANDIDATES}
    strategies = [materialize(by_id[cid], prm, stop_fill=stop_fill, risk_per_trade_pct=rpt) for cid, prm in items]
    return PortfolioEngine(perp_symbols(), strategies, start - WARMUP, end, trade_start_ts=start,
                           risk=RiskConfig.from_dict(risk)), start


def run_book(job):
    import contextlib
    import io
    from backend.utils.memwatch import peak_rss_mb, rss_anon_mb
    eng, start = _make_engine(job)
    with contextlib.redirect_stdout(io.StringIO()):
        eng.run()
    result = metrics(eng.get_results(), start)
    result["_peak_rss_mb"] = round(peak_rss_mb(), 1)  # đỉnh (gồm trang mmap dùng chung) của tiến trình worker tới lúc này
    result["_rss_anon_mb"] = round(rss_anon_mb(), 1)  # phần RAM riêng của worker (không gồm mmap dùng chung)
    return result


def _export_shared(jobs, shared_dir, label):
    """Tiến trình cha dựng MỘT lần dữ liệu của cả giai đoạn vào shared_dir (worker chỉ mmap). Trả các khoá đã dùng."""
    import ctypes
    import gc
    from backend.core.data import shared as shared_data
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    t = time.time()
    keys, written = set(), 0
    for job in jobs:
        eng, _ = _make_engine(job)
        info = shared_data.export(eng, shared_dir)
        keys.update(info["keys"].values())
        written += len(info["written"])
    CandleLoader.clear_cache()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # trả heap đã giải phóng về OS trước khi fork pool
    except OSError:
        pass
    print(f"[shared] {label}: {written} bộ mới, {len(keys)} bộ, {_dir_mb(shared_dir, keys):.0f} MB ({time.time() - t:.0f}s)", flush=True)
    return keys


def _dir_mb(shared_dir, keys=None) -> float:
    total = 0
    names = keys if keys is not None else os.listdir(shared_dir) if os.path.isdir(shared_dir) else []
    for name in names:
        for base, _, files in os.walk(os.path.join(shared_dir, name)):
            total += sum(os.path.getsize(os.path.join(base, fn)) for fn in files)
    return total / 1048576


def _pool_shared(jobs, workers, label, shared_dir):
    """Export dữ liệu dùng chung -> pool -> xoá các bộ của giai đoạn này (đã chạy xong; lỗi thì ngoại lệ bay lên, giữ nguyên để gỡ lỗi)."""
    import shutil
    keys = _export_shared(jobs, shared_dir, label)
    res = _pool_map_safe(run_book, jobs, workers, label)
    for k in keys:
        shutil.rmtree(os.path.join(shared_dir, k), ignore_errors=True)
    return res


def config_count(candidate, n):
    """Số cấu hình sẽ thử = min(n, kích thước lưới) — không dựng lưới."""
    total = 1
    for k in candidate["space"]:
        total *= len(candidate["space"][k])
    return min(int(n), total)


def iter_configs(candidate, n, seed):
    """Sinh LƯỜI từng cấu hình (dict), cùng thứ tự với `configs()`: lưới vừa n -> toàn lưới theo itertools.product (khoá sắp xếp);
    ngược lại `random.Random(seed).sample` n vị trí của lưới (lấy mẫu theo CHỈ SỐ, giải mã chỉ số -> tổ hợp) nên không cần dựng cả lưới
    — cùng dãy với `random.Random(seed).sample(grid, n)` của bản cũ."""
    keys = sorted(candidate["space"])
    sizes = [len(candidate["space"][k]) for k in keys]
    total = 1
    for sz in sizes:
        total *= sz
    if total <= n:
        positions = range(total)
    elif total <= sys.maxsize:
        positions = random.Random(seed).sample(range(total), n)
    else:  # không gian khổng lồ (> 2^63): rút ngẫu nhiên không lặp (bản cũ không dựng nổi lưới như vậy)
        rng = random.Random(seed)

        def _draw():
            seen = set()
            while len(seen) < n:
                x = rng.randrange(total)
                if x not in seen:
                    seen.add(x)
                    yield x
        positions = _draw()
    for pos in positions:
        vals, r = [], pos
        for k, sz in zip(reversed(keys), reversed(sizes)):
            r, m = divmod(r, sz)
            vals.append(candidate["space"][k][m])
        vals.reverse()
        yield dict(zip(keys, vals))


def configs(candidate, n, seed, lazy=False):
    """Danh sách cấu hình (như cũ). lazy=True -> trả generator (không dựng lưới/danh sách) cho không gian rất lớn."""
    gen = iter_configs(candidate, n, seed)
    return gen if lazy else list(gen)


def score(m, gates, sym_key="min_symbols_positive"):
    ok = m["trades"] >= gates["min_trades"] and m["symbols_positive"] >= gates[sym_key] and m["ret_pct"] > 0 \
        and m["mdd_pct"] <= gates["max_mdd_pct"]
    return (m["ret_pct"] / max(m["mdd_pct"], 1.0)) if ok else float("-inf"), ok


def _strip(m):
    return {k: v for k, v in m.items() if k not in ("daily", "_peak_rss_mb", "_rss_anon_mb")}


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


class SharedExporter:
    """Xuất dữ liệu dùng chung (mmap) CHO ĐÚNG những job mới cần, ngay trước khi job được gửi đi (giai đoạn A streaming).
    Mỗi (cửa sổ, refs kernel, perp) khác nhau xuất đúng một lần (như _export_shared cũ làm cho cả danh sách job); job trùng chữ ký bỏ qua
    rất rẻ (chỉ dựng tracker của 1 tài sản). Worker thấy khoá chưa có thì tự dựng (đúng kết quả, chỉ tốn RAM hơn)."""

    def __init__(self, shared_dir, label):
        self.shared_dir, self.label = shared_dir, label
        self.sigs, self.keys, self.written = set(), set(), 0
        self.t0 = time.time()

    def __call__(self, job):
        from backend.core.data import shared as shared_data
        eng, _ = _make_engine(job)
        sym = eng.symbols[0]
        te, _ = eng._make_trackers(sym, eng.ledger)
        sig = (eng.start_ts, eng.end_ts) + tuple(eng._cache_key(sym, te)[3:])
        if sig in self.sigs:
            return
        self.sigs.add(sig)
        info = shared_data.export(eng, self.shared_dir)
        self.keys.update(info["keys"].values())
        self.written += len(info["written"])
        _release_memory()

    def cleanup(self):
        import shutil
        print(f"[shared] {self.label}: {self.written} bộ mới, {len(self.keys)} bộ, {_dir_mb(self.shared_dir, self.keys):.0f} MB "
              f"({time.time() - self.t0:.0f}s)", flush=True)
        for k in self.keys:
            shutil.rmtree(os.path.join(self.shared_dir, k), ignore_errors=True)


def _release_memory():
    import ctypes
    import gc
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # trả heap đã giải phóng về OS trước khi fork pool
    except OSError:
        pass


def _job_key(stage, cand_id, job, fingerprint):
    """job = (strategies [(id, params)], (start, end), stop_fill, risk, rpt) -> job_key (xem results_store.make_job_key)."""
    items, window, stop_fill, risk, rpt = job
    return make_job_key(stage, cand_id, [[cid, prm] for cid, prm in items], list(window), stop_fill, risk, fingerprint,
                        extra={"rpt": rpt})


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
        exp_keys = _export_shared(sub, shared_dir, label)

        def _done(j, res):
            i = missing[j]
            results[i] = normalize(res)
            store.put(keys[i], stage, cand_id if cand_id is not None else "-", [[c, p] for c, p in jobs[i][0]], results[i], ord=i)
            if progress is not None:
                progress.tick(worker_peak_mb=results[i].get("_peak_rss_mb"))
        _pool_map_safe(run_book, sub, workers, label, on_done=_done)
        import shutil
        for k in exp_keys:
            shutil.rmtree(os.path.join(shared_dir, k), ignore_errors=True)
    return results


# Bản dùng chung nằm ở backend.utils.parallel / backend.core.backtest.portfolio_metrics; giữ tên cũ để code/test hiện có không đổi.
metrics = portfolio_metrics
bootstrap = bootstrap_daily
_pool_map_safe = pool_map_safe
_auto_workers = auto_workers


def _new_run_dir(cache_dir):
    """Thư mục lần chạy MỚI: <thời điểm>; trùng giây (hoặc đã có kho kết quả) thì thêm hậu tố để không bao giờ trộn hai lần chạy."""
    base = time.strftime("%Y%m%d_%H%M%S")
    for n in itertools.count(1):
        name = base if n == 1 else f"{base}_{n}"
        path = cache_dir(None, "book", name)
        if not os.path.exists(os.path.join(path, "results.sqlite")):
            return path


def _resume_dir(path, cache_dir):
    """--resume: thư mục lần chạy (đường dẫn hoặc tên thư mục trong data/_cache/book/) phải có results.sqlite."""
    cand = path if os.path.isabs(path) or os.path.isdir(path) else os.path.join(cache_dir(None, "book"), path)
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


DEFAULTS = {"workers": "auto", "per_worker_mb": None, "n": 24, "seed": 7, "only": "", "out": os.path.join(NORA_ROOT, "data", "alphas"),
            "keep_top": 50, "resume": "", "max_configs": 200_000, "force_large": False}


def run_job(params=None):
    """Dựng sổ chiến lược với `params` (xem DEFAULTS) -> báo cáo (cũng ghi book.json vào `out` + $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("build_strategy_book")
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, CANDIDATES, GATES, RISK, perp_symbols
    from backend.db.data_layout import cache_dir
    from backend.utils.memwatch import check_memory_gate, planning_budget_mb
    from backend.core.data.quality_gate import require_data_ok_or_exit
    from backend.utils.jobs import Progress, graceful_sigterm

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
    run_dir = _resume_dir(a.resume, cache_dir) if resuming else _new_run_dir(cache_dir)
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
                stored = {k: v for k, v in m.items() if k not in ("daily", "_peak_rss_mb", "_rss_anon_mb")}
            return stored, sc

        def jobs(c=c, cid=cid):
            for ord_, cfg in enumerate(iter_configs(c, a.n, a.seed)):
                yield ord_, cfg, ([(cid, cfg)], (w["start"], w["dev1_end"]), "level", eval_risk, BASE_RISK_PER_TRADE_PCT)

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
        jobs_b = [([(cid, top[rank]["params"])], (w["dev1_end"], w["dev2_end"]), sf, eval_risk, BASE_RISK_PER_TRADE_PCT)
                  for cid, rank, sf in keys]
        res_c = _pool_shared_stored(jobs_b, workers, f"[B] {c['id']}", shared_dir, store, "B", c["id"], fingerprint, progress)
        out.update(zip(keys, res_c))
        print(f"[B] {c['id']:18s} {len(jobs_b)} lần chạy dev2 xong ({time.time() - t0:.0f}s | "
              f"{_peak(res_c)})", flush=True)

    accepted = []
    for c in cands:
        top = [r for r in stage_a[c["id"]][:3] if r["score"] > float("-inf")]
        entry = {"description": c["description"], "side": c["side"], "family": c["family"],
                 "dev1_tried": stage_a_counts[c["id"]]["tried"], "dev1_top": [{"params": r["params"], "dev1": _strip(r["dev1"])} for r in top]}
        passes = []
        for rank, r in enumerate(top):
            lv, ex = out[(c["id"], rank, "level")], out[(c["id"], rank, "extreme")]
            ok = bool(score(lv, GATES, "min_symbols_positive_dev2")[1] and ex["ret_pct"] > 0 and ex["mdd_pct"] <= MDD_LIMIT)
            passes.append(ok)
            entry["dev1_top"][rank]["dev2_level"] = _strip(lv)
            entry["dev1_top"][rank]["dev2_extreme"] = _strip(ex)
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
            [(items, (w["dev1_end"], w["dev2_end"]), sf, RISK, BASE_RISK_PER_TRADE_PCT) for sf in ("level", "extreme")],
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
            fin_jobs = [(items, win, sf, RISK, rpt)
                        for win in ((w["dev1_end"], w["dev2_end"]), (w["dev2_end"], w["end"]))
                        for sf in ("level", "extreme")]
            progress.start_stage("D", len(fin_jobs))
            res = _pool_shared_stored(fin_jobs, workers, "[D] holdout", shared_dir, store, "D", "book", fingerprint, progress)
            final = {"dev2_level": _strip(res[0]), "dev2_extreme": _strip(res[1]),
                     "holdout_level": _strip(res[2]), "holdout_extreme": _strip(res[3])}
            for k in ("dev2_level", "dev2_extreme", "holdout_level", "holdout_extreme"):
                m = final[k]
                print(f"[D] {k:16s} lãi {m['ret_pct']}%  MDD {m['mdd_pct']}%  sharpe {m['sharpe']}  lệnh {m['trades']}  "
                      f"+{m['symbols_positive']}/8  kill={'có' if m['halted_at'] else 'không'}  {m['by_strategy']}")
        report["book"] = {
            "strategies": [{"id": cid, "params": prm} for cid, prm in items],
            "risk_per_trade_pct": rpt, "risk": RISK, "risk_scale_bootstrap": sizing,
            "dev2_base_risk": {"level": _strip(base_dev2[0]), "extreme": _strip(base_dev2[1])},
            "final": final,
            "holdout_pass": bool(bool(final) and final["holdout_level"]["ret_pct"] > 0
                                 and final["holdout_level"]["mdd_pct"] <= MDD_LIMIT
                                 and final["holdout_extreme"]["mdd_pct"] <= MDD_LIMIT),
        }

    # Chạy xong thành công: xoá dữ liệu dùng chung (lỗi/ngoại lệ thì không tới đây -> còn nguyên để gỡ lỗi)
    if os.path.isdir(shared_dir):
        import shutil
        print(f"[shared] xoá {shared_dir} ({_dir_mb(shared_dir):.0f} MB còn lại; mỗi giai đoạn đã tự dọn bộ của nó)", flush=True)
        shutil.rmtree(shared_dir, ignore_errors=True)

    # Ghi báo cáo cuối
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=json_default)
    print("báo cáo:", os.path.join(run_dir, "report.json"))
    paths = []
    if report.get("book"):
        from backend.optimize.book_export import write_book
        paths = write_book(report, a.out, source=run_dir, repo_dir=os.path.dirname(NORA_ROOT))
        for path in paths:
            print("ghi:", path)
        if len(paths) == 1:  # holdout không đạt: chỉ có book.json (HOLDOUT_FAILED), không có cấu hình testnet
            print("HOLDOUT KHÔNG ĐẠT — không tạo data/alphas/testnet/book.json.")
    store.flush()
    progress.finish("done")
    write_job_result({**report, "run_dir": run_dir, "written": paths, "stage_a": stage_a_rows(stage_a),
                      "stage_a_counts": stage_a_counts, "estimate": estimate,
                      "store": {"path": os.path.join(run_dir, "results.sqlite"), "rows": store.count()}})  # chỉ khi chạy như job API (env NORA_JOB_DIR)
