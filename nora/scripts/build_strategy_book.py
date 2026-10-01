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

Dùng: PYTHONPATH=. python scripts/build_strategy_book.py [--workers 10] [--n 24] [--only trend_long,trend_short]
Kết quả: alphas/book.json (+ alphas/testnet/book.json nếu sổ có chiến lược), báo cáo tại <data>/_cache/book/<thời điểm>/.

Bộ nhớ (mỗi worker là một tiến trình có cache riêng):
  NORA_CANDLE_CACHE_MB   ngân sách cache nến cả file (script này mặc định 512 MB)
  NORA_DATA_CACHE_MB     ngân sách cache mảng giá + kernel theo cửa sổ (script này mặc định 1024 MB)
  RAM một worker: mặc định PER_WORKER_MB (số ĐO THỰC, chỉ để hoạch định số worker + cổng RAM; rào cứng là
  trần cgroup — worker vượt thì bị giết riêng, _pool_map_safe chạy lại với một nửa số worker).
  Đo lại bằng dòng `đỉnh RAM/worker` và ghi đè bằng --per-worker-mb khi dữ liệu/ngân sách cache đổi.
  --workers auto đọc cả giới hạn cgroup (systemd-run -p MemoryMax=...), không chỉ RAM trống của máy.
  BẮT BUỘC chạy dưới trần RAM: scripts/run_limited.sh -- scripts/build_strategy_book.py ...
  (không có trần cgroup thì script từ chối chạy, trừ khi NORA_ALLOW_UNLIMITED=1).
  Dữ liệu dùng chung: trước mỗi pool, tiến trình CHA dựng một lần mảng giá + kernel + funding của cả vũ trụ vào
  <run_dir>/_shared/ (backend/backtest/shared_data.py); worker chỉ np.load(mmap_mode="r") qua NORA_SHARED_DATA_DIR
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

import argparse
import itertools
import json
import random
import sys
import time
import warnings

import pandas as pd

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

from backend.backtest.portfolio_metrics import bootstrap_daily, portfolio_metrics  # noqa: E402
from backend.utils.parallel import auto_workers, pool_map_safe  # noqa: E402

DAY = 86_400_000
WARMUP = 20 * DAY
MDD_LIMIT = 30.0
RUIN_MAX_PCT = 5.0
RISK_SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
MAX_RISK_PER_TRADE = 2.0
# Đo 01/10/2026 (dữ liệu dùng chung qua mmap, 8 tài sản perp, dev1 ≈ 14 tháng): VmHWM 560–590 MB mỗi worker (đã gồm trang mmap
# dùng chung ~440 MB/giai đoạn; phần riêng ~150 MB) × 1,3 dự phòng. Trước khi dùng mmap: 1280–1320 MB (xem git log).
# Đo lại bằng dòng `đỉnh RAM/worker`, ghi đè bằng --per-worker-mb khi kích thước dữ liệu hoặc ngân sách cache đổi;
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
    from backend.alpha.strategy_book import CANDIDATES, materialize, perp_symbols
    from backend.backtest.portfolio import PortfolioEngine, RiskConfig
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
    from backend.backtest import shared_data
    from backend.backtest.portfolio import data_cache_clear
    from backend.core.loader import CandleLoader
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


def configs(candidate, n, seed):
    keys = sorted(candidate["space"])
    grid = [dict(zip(keys, v)) for v in itertools.product(*(candidate["space"][k] for k in keys))]
    if len(grid) <= n:
        return grid
    return random.Random(seed).sample(grid, n)


def score(m, gates, sym_key="min_symbols_positive"):
    ok = m["trades"] >= gates["min_trades"] and m["symbols_positive"] >= gates[sym_key] and m["ret_pct"] > 0 \
        and m["mdd_pct"] <= gates["max_mdd_pct"]
    return (m["ret_pct"] / max(m["mdd_pct"], 1.0)) if ok else float("-inf"), ok


def _strip(m):
    return {k: v for k, v in m.items() if k not in ("daily", "_peak_rss_mb", "_rss_anon_mb")}


def _peak(results) -> str:
    peaks = [r.get("_peak_rss_mb", 0.0) for r in results if r]
    anon = [r.get("_rss_anon_mb", 0.0) for r in results if r]
    if not peaks:
        return "đỉnh RAM/worker ?"
    return f"đỉnh RAM/worker {max(peaks):.0f} MB (riêng {max(anon):.0f} MB + mmap dùng chung)"


# Bản dùng chung nằm ở backend.utils.parallel / backend.backtest.portfolio_metrics; giữ tên cũ để code/test hiện có không đổi.
metrics = portfolio_metrics
bootstrap = bootstrap_daily
_pool_map_safe = pool_map_safe
_auto_workers = auto_workers


def main(argv=None):
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="auto",
                    help="số worker tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    ap.add_argument("--per-worker-mb", type=float, default=None,
                    help="trần RAM một worker (MB); mặc định = PER_WORKER_MB (số đo thực)")
    ap.add_argument("--n", type=int, default=24, help="số cấu hình thử mỗi chiến lược ở dev1")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="", help="chỉ các chiến lược này (phân tách bằng dấu phẩy)")
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "alphas"))
    a = ap.parse_args(argv)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("build_strategy_book")
    from backend.alpha.strategy_book import BASE_RISK_PER_TRADE_PCT, CANDIDATES, GATES, RISK, perp_symbols
    from backend.db.data_layout import cache_dir
    from backend.utils.memwatch import check_memory_gate, planning_budget_mb

    # ── Số worker + kiểm RAM trước khi chạy ──────────────────────────────────
    per_worker_mb = a.per_worker_mb or PER_WORKER_MB
    if str(a.workers).strip().lower() == "auto":
        workers = _auto_workers(per_worker_mb)
        print(f"[auto] workers={workers} (ngân sách RAM {planning_budget_mb():.0f} MB, "
              f"trần mỗi worker {per_worker_mb:.0f} MB)", flush=True)
    else:
        workers = int(a.workers)
    check_memory_gate(workers * per_worker_mb, f"build_strategy_book --workers {workers}")

    cands = [c for c in CANDIDATES if not a.only or c["id"] in a.only.split(",")]
    w = windows(perp_symbols())
    fmt = lambda x: f"{pd.Timestamp(x, unit='ms'):%Y-%m-%d}"
    print(f"dev1 {fmt(w['start'])} → {fmt(w['dev1_end'])} | dev2 → {fmt(w['dev2_end'])} | holdout → {fmt(w['end'])}", flush=True)
    print(f"workers={workers} | NORA_CANDLE_CACHE_MB={os.environ['NORA_CANDLE_CACHE_MB']} "
          f"| NORA_DATA_CACHE_MB={os.environ['NORA_DATA_CACHE_MB']} | trần mỗi worker {per_worker_mb:.0f} MB", flush=True)
    eval_risk = {**RISK, "kill_switch_dd_pct": 0}
    run_dir = cache_dir(None, "book", time.strftime("%Y%m%d_%H%M%S"))
    report = {"windows": {k: fmt(v) for k, v in w.items()}, "gates": GATES, "risk": RISK, "candidates": {}}
    shared_dir = os.path.join(run_dir, "_shared")
    os.environ["NORA_SHARED_DATA_DIR"] = shared_dir  # đặt TRƯỚC khi tạo pool (fork kế thừa); PortfolioEngine đọc biến này

    # ── A. dev1 — MỖI CHIẾN LƯỢC DÙNG POOL RIÊNG → xả cache khi xong ────────
    t0 = time.time()
    stage_a = {}
    for c in cands:
        cfgs = configs(c, a.n, a.seed)
        jobs = [([(c["id"], cfg)], (w["start"], w["dev1_end"]), "level", eval_risk, BASE_RISK_PER_TRADE_PCT) for cfg in cfgs]
        # Pool mới cho mỗi chiến lược: khi pool đóng, tiến trình con bị thu hồi → RAM giải phóng
        ms = _pool_shared(jobs, workers, f"[A] {c['id']}", shared_dir)
        rows = sorted(
            ({"params": cfg, "dev1": m, "score": score(m, GATES)[0]} for cfg, m in zip(cfgs, ms)),
            key=lambda r: -r["score"],
        )
        stage_a[c["id"]] = rows
        best = rows[0]
        print(
            f"[A] {c['id']:18s} {len(cfgs)} cấu hình, đạt {sum(r['score'] > float('-inf') for r in rows)}; "
            f"tốt nhất: lãi {best['dev1']['ret_pct']}% MDD {best['dev1']['mdd_pct']}% lệnh {best['dev1']['trades']} "
            f"+{best['dev1']['symbols_positive']}/8  ({time.time() - t0:.0f}s | {_peak(ms)})", flush=True
        )
        # Ghi checkpoint sau mỗi chiến lược — không mất kết quả nếu sập giữa chừng
        with open(os.path.join(run_dir, "stage_a.json"), "w", encoding="utf-8") as fh:
            json.dump(stage_a, fh, ensure_ascii=False, indent=1, default=str)

    # ── B. dev2 — cũng một pool riêng cho MỖI chiến lược (cache không dồn qua các chiến lược) ──
    out = {}
    for c in cands:
        top = [r for r in stage_a[c["id"]][:3] if r["score"] > float("-inf")]
        keys = [(c["id"], rank, sf) for rank in range(len(top)) for sf in ("level", "extreme")]
        if not keys:
            continue
        jobs = [([(cid, top[rank]["params"])], (w["dev1_end"], w["dev2_end"]), sf, eval_risk, BASE_RISK_PER_TRADE_PCT)
                for cid, rank, sf in keys]
        res_c = _pool_shared(jobs, workers, f"[B] {c['id']}", shared_dir)
        out.update(zip(keys, res_c))
        print(f"[B] {c['id']:18s} {len(jobs)} lần chạy dev2 xong ({time.time() - t0:.0f}s | {_peak(res_c)})", flush=True)

    accepted = []
    for c in cands:
        top = [r for r in stage_a[c["id"]][:3] if r["score"] > float("-inf")]
        entry = {"description": c["description"], "side": c["side"], "family": c["family"],
                 "dev1_tried": len(stage_a[c["id"]]), "dev1_top": [{"params": r["params"], "dev1": _strip(r["dev1"])} for r in top]}
        passes = []
        for rank, r in enumerate(top):
            lv, ex = out[(c["id"], rank, "level")], out[(c["id"], rank, "extreme")]
            ok = (score(lv, GATES, "min_symbols_positive_dev2")[1] and ex["ret_pct"] > 0 and ex["mdd_pct"] <= MDD_LIMIT)
            passes.append(ok)
            entry["dev1_top"][rank]["dev2_level"] = _strip(lv)
            entry["dev1_top"][rank]["dev2_extreme"] = _strip(ex)
            entry["dev1_top"][rank]["dev2_pass"] = ok
        entry["accepted"] = bool(top) and passes[0]
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
        json.dump({"candidates": report["candidates"]}, fh, ensure_ascii=False, indent=1, default=str)

    if not accepted:
        report["book"] = None
        print("\nKHÔNG có chiến lược nào đạt — không tạo sổ (không nới gate).")
    else:
        items = [(cid, prm) for cid, prm, _ in accepted]
        base_dev2 = _pool_shared(
            [(items, (w["dev1_end"], w["dev2_end"]), sf, RISK, BASE_RISK_PER_TRADE_PCT) for sf in ("level", "extreme")],
            workers, "[C] base_dev2", shared_dir,
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
            res = _pool_shared(fin_jobs, workers, "[D] holdout", shared_dir)
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
            "holdout_pass": bool(final) and final["holdout_level"]["ret_pct"] > 0
            and final["holdout_level"]["mdd_pct"] <= MDD_LIMIT and final["holdout_extreme"]["mdd_pct"] <= MDD_LIMIT,
        }

    # Chạy xong thành công: xoá dữ liệu dùng chung (lỗi/ngoại lệ thì không tới đây -> còn nguyên để gỡ lỗi)
    if os.path.isdir(shared_dir):
        import shutil
        print(f"[shared] xoá {shared_dir} ({_dir_mb(shared_dir):.0f} MB còn lại; mỗi giai đoạn đã tự dọn bộ của nó)", flush=True)
        shutil.rmtree(shared_dir, ignore_errors=True)

    # Ghi báo cáo cuối
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    print("báo cáo:", os.path.join(run_dir, "report.json"))
    if report.get("book"):
        from backend.alpha.book_export import write_book
        for path in write_book(report, a.out, source=run_dir, repo_dir=os.path.dirname(NORA_ROOT)):
            print("ghi:", path)


if __name__ == "__main__":
    main()
