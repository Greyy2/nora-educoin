"""Job edu_precompute (B7): chạy backtest THẬT cho 50 mẫu chiến lược giáo dục và lưu kết quả để trang Education hiển thị ngay.

Mỗi mẫu của samples.json (crawl/store.alpha_education_samples(); xuất từ frontend/src/components/education/educationSamples.js bằng test/scripts/export_edu_samples.py)
chạy qua ĐÚNG đường custom_run.run_custom (cùng engine, benchmark luôn long, chẩn đoán, nhận xét như POST /api/studio/custom/backtest) với cấu hình mặc định của Nora
và `position` CỦA MẪU (nếu có).
Kết quả: crawl/store.education_results_dir()/<key>.json = {key, name, ..., program_hash, config, data (nguồn + sha256), git_commit, generated_at, metrics, diagnostics,
insights, series (hạ mẫu), explain, warnings} và index.json cùng thư mục.

Mặc định: cửa sổ = phần dữ liệu chung của cả rổ trong kho (run_defaults.default_window: ngày đầy đủ đầu tiên sau nến đầu muộn nhất → ngày đầy đủ cuối cùng trước nến cuối sớm nhất),
vốn 10000, train_ratio 0,7, rổ = mọi tài sản perp OKX có trong kho (run_defaults.default_universe).

Tham số (run_job params): only (list key; trống = tất cả), start, end, train_ratio, initial_capital.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from backend.core.backtest.run_defaults import DEFAULT_CAPITAL, DEFAULT_TRAIN_RATIO, default_window
from backend.utils.jobs import options, write_job_result

DEFAULTS = {"only": None, "start": None, "end": None, "train_ratio": DEFAULT_TRAIN_RATIO, "initial_capital": DEFAULT_CAPITAL}
NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))      # chỉ để chạy `git rev-parse`
MAX_POINTS = 400


def results_dir() -> str:
    from backend.crawl.store import education_results_dir
    return education_results_dir()


def load_samples(path: Optional[str] = None) -> List[Dict[str, Any]]:
    from backend.crawl.store import alpha_education_samples
    with open(path or alpha_education_samples(), encoding="utf-8") as fh:
        return json.load(fh)


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=NORA_DIR, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:      # noqa: BLE001
        return None


def downsample_series(series: Dict[str, Any], max_points: int = MAX_POINTS) -> Dict[str, Any]:
    """Hạ mẫu các chuỗi ngày (cùng chỉ số cho times/equity/pnl/drawdown/benchmark) còn <= max_points điểm, luôn giữ điểm đầu và cuối."""
    def pick(n: int) -> List[int]:
        return list(range(n)) if n <= max_points else sorted(set(np.linspace(0, n - 1, max_points).round().astype(int).tolist()))

    def cut(block: Dict[str, Any]) -> Dict[str, Any]:
        n = len(block.get("times", []))
        idx = pick(n)
        out = dict(block)
        for k, v in block.items():
            if isinstance(v, list) and len(v) == n:
                out[k] = [v[i] for i in idx]
        return out

    from backend.core.metrics.series_stages import downsample_stage
    out = cut({k: v for k, v in series.items() if k not in ("test", "benchmark", "stages")})
    for k in ("test", "benchmark"):
        if k in series:
            blk = dict(series[k])
            nested = blk.pop("benchmark", None)       # series.test.benchmark (benchmark chạy lại trên cửa sổ test) cắt cùng lưới riêng
            out[k] = cut(blk)
            if nested is not None:
                out[k]["benchmark"] = cut(nested)
    if "stages" in series:      # chuỗi giai đoạn ĐÃ tính ở backend: chỉ gom nhóm để vẽ (series_stages.downsample_stage), không tính lại
        out["stages"] = {k: downsample_stage(v, max_points) for k, v in series["stages"].items()}
    out["downsampled_from"] = len(series.get("times", []))
    return out


def _atomic_write(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, allow_nan=False, default=_json_default)
    os.replace(tmp, path)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"không JSON hoá được {type(o)}")


def _clear_data_caches() -> None:
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()


def _run_one(sample: Dict[str, Any], a, custom_run) -> Dict[str, Any]:
    """Chạy một mẫu qua custom_run.run_custom; trả dict kết quả."""
    params = {"code": sample["code"], "start": a.start, "end": a.end, "train_ratio": float(a.train_ratio), "initial_capital": float(a.initial_capital)}
    if sample.get("position"):
        params["position"] = sample["position"]
    _clear_data_caches()
    try:
        return custom_run.run_custom(params)
    finally:
        _clear_data_caches()


def run_job(params=None):
    import warnings
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    if not (a.start and a.end):
        a.start, a.end = default_window()
    from backend.core.backtest import custom_run
    from backend.core.strategy.pydsl import compile_code, explain_program
    samples = load_samples()
    only = set(a.only or [])
    unknown = sorted(only - {s["key"] for s in samples})
    if unknown:
        raise ValueError(f"mẫu không tồn tại: {unknown}")
    if only:
        samples = [s for s in samples if s["key"] in only]
    out_dir = results_dir()
    os.makedirs(out_dir, exist_ok=True)
    commit, t0 = git_commit(), time.time()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index: List[Dict[str, Any]] = []
    print(f"edu_precompute: {len(samples)} mẫu | {a.start} → {a.end} | commit {commit}", flush=True)
    for n, s in enumerate(samples, 1):
        key, ts = s["key"], time.time()
        item: Dict[str, Any] = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"),
                                "file": f"{key}.json"}
        try:
            out = _run_one(s, a, custom_run)
            prog = compile_code(s["code"], register=False)
            sim = out["metrics"]["simulate"]
            rec = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"), "summary": s.get("summary"),
                   "program_hash": out["program_hash"], "config": out["config"], "data": out["data"], "git_commit": commit,
                   "generated_at": generated_at, "metrics": out["metrics"], "yearly": out["yearly"], "diagnostics": out["diagnostics"], "insights": out["insights"],
                   "series": downsample_series(out["series"]), "by_symbol": out["by_symbol"], "final_equity": out["final_equity"], "warnings": out["warnings"],
                   "trades_closed": len(out["trades"]), "positions_open": len(out["positions_open"]), "explain": explain_program(prog, position=s.get("position"))}
            _atomic_write(os.path.join(out_dir, f"{key}.json"), rec)
            item.update({"status": "ok", "program_hash": out["program_hash"], "final_equity": out["final_equity"], "cagr_pct": sim.get("cagr_pct"),
                         "mdd_pct": sim.get("mdd_pct"), "sharpe": sim.get("sharpe"), "trades": len(out["trades"]) + len(out["positions_open"]),
                         "insights": [i["id"] for i in out["insights"]], "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: OK vốn cuối {out['final_equity']} | {item['wall_s']}s", flush=True)
        except Exception as e:      # noqa: BLE001 — một mẫu lỗi không dừng cả job; ghi rõ lỗi vào index
            item.update({"status": "failed", "error": f"{type(e).__name__}: {e}", "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: LỖI {item['error']}", flush=True)
        index.append(item)
    ok = sum(1 for i in index if i["status"] == "ok")
    full = not only
    if not full:      # chạy một phần: giữ các dòng cũ của mẫu khác trong index
        try:
            with open(os.path.join(out_dir, "index.json"), encoding="utf-8") as fh:
                old = {i["key"]: i for i in json.load(fh).get("items", [])}
        except (OSError, ValueError):
            old = {}
        old.update({i["key"]: i for i in index})
        index_items = list(old.values())
    else:
        index_items = index
    wall = round(time.time() - t0, 1)
    idx = {"generated_at": generated_at, "git_commit": commit, "start": a.start, "end": a.end, "train_ratio": float(a.train_ratio), "initial_capital": float(a.initial_capital),
           "count": len(index_items), "ok": sum(1 for i in index_items if i.get("status") == "ok"), "failed": sum(1 for i in index_items if i.get("status") == "failed"),
           "last_run": {"samples": len(index), "ok": ok, "failed": len(index) - ok, "wall_s": wall}, "items": index_items}
    _atomic_write(os.path.join(out_dir, "index.json"), idx)
    result = {"samples": len(index), "ok": ok, "failed": len(index) - ok, "wall_s": wall, "git_commit": commit, "items": index}
    print(f"edu_precompute xong: {ok}/{len(index)} mẫu OK, {wall}s", flush=True)
    write_job_result(result)
    return result
