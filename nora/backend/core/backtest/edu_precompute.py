"""Job edu_precompute (B7): chạy backtest THẬT cho 50 mẫu chiến lược giáo dục và lưu kết quả để trang Education hiển thị ngay.

Mỗi mẫu của data/education/samples.json (xuất từ frontend/src/components/education/educationSamples.js bằng test/scripts/export_edu_samples.py) chạy qua ĐÚNG đường
custom_run.run_custom (cùng engine, benchmark luôn long, chẩn đoán, nhận xét như POST /api/studio/custom/backtest) với hồ sơ + position CỦA MẪU (xno | nora).
Kết quả: data/education/results/<key>.json = {key, name, ..., program_hash, config, data (nguồn + sha256), git_commit, generated_at, metrics, diagnostics, insights,
series (hạ mẫu), explain, warnings} và data/education/results/index.json.

Mặc định: start 2019-12-31 → end 2024-12-31 (= 2020-01-02 → 2025-01-01 của trang Education theo nhãn xnoquant: tín hiệu nến 12-31 khớp ở open 01-01), vốn 100000,
train_ratio 0,7. Mẫu xno: rổ TOP10 spot binance_hist (mặc định của hồ sơ xno). Mẫu nora: rổ mặc định của trang Education ['BTC@perp'] trên kho dữ liệu hiện tại;
nếu cổng chất lượng dữ liệu / thiếu dữ liệu chặn thì lùi về rổ TOP10 spot binance_hist (market=spot) và ghi rõ trong config.fallback + warnings.

Tham số (run_job params): only (list key; trống = tất cả), start, end, train_ratio, initial_capital.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"only": None, "start": "2019-12-31", "end": "2024-12-31", "train_ratio": 0.7, "initial_capital": 100_000.0}
NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EDU_DIR = os.path.join(NORA_DIR, "data", "education")
SAMPLES_FILE = os.path.join(EDU_DIR, "samples.json")
RESULTS_DIR = os.path.join(EDU_DIR, "results")
EDU_NORA_SYMBOLS = ["BTC@perp"]       # mặc định của trang Education (DEFAULT_FORM.symbols)
FALLBACK_RUN_FRAME = "1h"      # rổ lùi 10 coin × 5 năm ở nến 1m cần ~7,5 phút + 5,5 GB RAM mỗi mẫu; nến 1h giữ SL/trailing theo giờ
MAX_POINTS = 400
_SOURCE_ENV = ("NORA_EXCHANGE", "NORA_LOCAL_DATA_ROOT")


def load_samples(path: str = SAMPLES_FILE) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    for r in rows:
        r.setdefault("profile", "xno")
    return rows


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
    """Chạy một mẫu; trả dict kết quả của custom_run + config.fallback nếu phải lùi nguồn dữ liệu. Môi trường nguồn dữ liệu được khôi phục sau mỗi mẫu."""
    saved = {k: os.environ.get(k) for k in _SOURCE_ENV}
    base = {"code": sample["code"], "profile": sample["profile"], "start": a.start, "end": a.end, "train_ratio": float(a.train_ratio),
            "initial_capital": float(a.initial_capital)}
    if sample.get("position") and sample["profile"] == "nora":
        base["position"] = sample["position"]
    attempts: List[Dict[str, Any]] = [dict(base)]
    if sample["profile"] == "nora":
        attempts = [{**base, "symbols": list(EDU_NORA_SYMBOLS)},
                    {**base, "universe": "TOP10", "exchange": custom_run.XNO_DEFAULT_DATA, "market": "spot", "run_frame": FALLBACK_RUN_FRAME}]
    err = None
    try:
        for i, params in enumerate(attempts):
            for k, v in saved.items():              # mỗi lần thử bắt đầu từ môi trường nguồn dữ liệu ban đầu
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v
            _clear_data_caches()
            try:
                out = custom_run.run_custom(params)
            except Exception as e:      # noqa: BLE001 — cổng chất lượng / thiếu dữ liệu: thử cấu hình lùi
                err = f"{type(e).__name__}: {e}"
                if i + 1 < len(attempts):
                    continue
                raise
            if i > 0:
                note = (f"Rổ mặc định của trang Education {EDU_NORA_SYMBOLS} không chạy được ({err}); chạy lùi trên rổ TOP10 spot {custom_run.XNO_DEFAULT_DATA} "
                        f"(hồ sơ nora, market=spot, khung chạy {FALLBACK_RUN_FRAME} thay vì 1m) — kết quả KHÔNG tương đương BTC@perp")
                out["config"]["fallback"] = {"reason": err, "from_symbols": EDU_NORA_SYMBOLS, "to": "TOP10 spot " + custom_run.XNO_DEFAULT_DATA, "run_frame": FALLBACK_RUN_FRAME}
                out["warnings"] = [note] + list(out["warnings"])
            return out
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        _clear_data_caches()
    raise RuntimeError(err or "không chạy được")


def run_job(params=None):
    import warnings
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.core.backtest import custom_run
    from backend.core.strategy.pydsl import compile_code, explain_program
    samples = load_samples()
    only = set(a.only or [])
    unknown = sorted(only - {s["key"] for s in samples})
    if unknown:
        raise ValueError(f"mẫu không tồn tại: {unknown}")
    if only:
        samples = [s for s in samples if s["key"] in only]
    os.makedirs(RESULTS_DIR, exist_ok=True)
    commit, t0 = git_commit(), time.time()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index: List[Dict[str, Any]] = []
    print(f"edu_precompute: {len(samples)} mẫu | {a.start} → {a.end} | commit {commit}", flush=True)
    for n, s in enumerate(samples, 1):
        key, ts = s["key"], time.time()
        item: Dict[str, Any] = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"), "profile": s["profile"],
                                "file": f"{key}.json"}
        try:
            out = _run_one(s, a, custom_run)
            prog = compile_code(s["code"], register=False)
            sim = out["metrics"]["simulate"]
            rec = {"key": key, "name": s.get("name"), "category": s.get("category"), "difficulty": s.get("difficulty"), "summary": s.get("summary"),
                   "profile": s["profile"], "program_hash": out["program_hash"], "config": out["config"], "data": out["data"], "git_commit": commit,
                   "generated_at": generated_at, "metrics": out["metrics"], "yearly": out["yearly"], "diagnostics": out["diagnostics"], "insights": out["insights"],
                   "series": downsample_series(out["series"]), "by_symbol": out["by_symbol"], "final_equity": out["final_equity"], "warnings": out["warnings"],
                   "trades_closed": len(out["trades"]), "positions_open": len(out["positions_open"]), "explain": explain_program(prog, profile=s["profile"], position=s.get("position"))}
            _atomic_write(os.path.join(RESULTS_DIR, f"{key}.json"), rec)
            item.update({"status": "ok", "program_hash": out["program_hash"], "final_equity": out["final_equity"], "cagr_pct": sim["nora"].get("cagr_pct"),
                         "mdd_pct": sim["nora"].get("mdd_pct"), "sharpe": sim["nora"].get("sharpe"), "trades": len(out["trades"]) + len(out["positions_open"]),
                         "insights": [i["id"] for i in out["insights"]], "fallback": bool(out["config"].get("fallback")), "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: OK vốn cuối {out['final_equity']} | {item['wall_s']}s", flush=True)
        except Exception as e:      # noqa: BLE001 — một mẫu lỗi không dừng cả job; ghi rõ lỗi vào index
            item.update({"status": "failed", "error": f"{type(e).__name__}: {e}", "wall_s": round(time.time() - ts, 1)})
            print(f"[{n}/{len(samples)}] {key}: LỖI {item['error']}", flush=True)
        index.append(item)
    ok = sum(1 for i in index if i["status"] == "ok")
    full = not only
    if not full:      # chạy một phần: giữ các dòng cũ của mẫu khác trong index
        try:
            with open(os.path.join(RESULTS_DIR, "index.json"), encoding="utf-8") as fh:
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
    _atomic_write(os.path.join(RESULTS_DIR, "index.json"), idx)
    result = {"samples": len(index), "ok": ok, "failed": len(index) - ok, "wall_s": wall, "git_commit": commit, "items": index}
    print(f"edu_precompute xong: {ok}/{len(index)} mẫu OK, {wall}s", flush=True)
    write_job_result(result)
    return result
