"""Chạy MỌI mẫu (50 mẫu giáo dục + code dựng sẵn của StudioWorkspace) qua ĐÚNG đường chạy của nút "Chạy": routes/alpha custom backtest ->
build_job("custom_backtest") -> tasks.run_custom (cùng hàm runner của job). In bảng compile/run/lệnh/lỗi.

Chạy: ops/run_limited.sh --no-lock -- test/scripts/check_samples_run.py [--only k1,k2] [--json out.json]
Thoát 1 nếu có mẫu lỗi.
"""
import argparse
import json
import os
import re
import sys
import time

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)

from backend.alpha.compile import compile_code                       # noqa: E402
from backend.alpha.dsl.signal import DslError                             # noqa: E402
from backend.crawl.store import alpha_education_samples, run_defaults   # noqa: E402
from backend.optimize.process import tasks                           # noqa: E402
from backend.routes import process as job_routes                     # noqa: E402


def frontend_samples():
    """Code dựng sẵn trong StudioWorkspace (frontend/src/components/studio/samples.js: mọi `export const X = `...``; hiện chỉ BLANK_CODE)."""
    path = os.path.join(NORA, "frontend", "src", "components", "studio", "samples.js")
    if not os.path.isfile(path):      # giao diện đã bỏ/di chuyển file mẫu dựng sẵn -> chỉ chạy 50 mẫu giáo dục
        return []
    text = open(path, encoding="utf-8").read()
    return [{"key": "fe_" + m.group(1).lower(), "code": m.group(2).replace("\\`", "`")} for m in re.finditer(r"export const (\w+)\s*=\s*`(.*?)`", text, re.S)]


def run_config(sample, defaults):
    """Cấu hình chạy của mẫu: trường riêng (symbols/start/end/train_ratio/initial_capital/position/run_frame) nếu có, không thì run_defaults() (như form)."""
    cfg = {"code": sample["code"], "start": sample.get("start") or defaults["start"], "end": sample.get("end") or defaults["end"],
           "train_ratio": sample.get("train_ratio", defaults.get("train_ratio", 0.7)), "initial_capital": sample.get("initial_capital", defaults.get("initial_capital"))}
    symbols = sample.get("symbols") or defaults.get("symbols")
    if symbols:
        cfg["symbols"] = symbols
    for k in ("position", "run_frame"):
        if sample.get(k):
            cfg[k] = sample[k]
    return cfg


def run_one(sample, defaults):
    row = {"key": sample["key"], "compile": False, "run": False, "trades": None, "error": None, "wall_s": None}
    t0 = time.time()
    try:
        compile_code(sample["code"], register=False)
        row["compile"] = True
        params = job_routes.build_job("custom_backtest", run_config(sample, defaults))     # đúng như post_custom_backtest
        tasks._clear_data_caches()
        try:
            out = tasks.run_custom(params)
        finally:
            tasks._clear_data_caches()
        row.update(run=True, trades=len(out["trades"]) + len(out["positions_open"]), final_equity=out["final_equity"], out=out)
    except (DslError, Exception) as e:      # noqa: BLE001 — báo lỗi từng mẫu
        row["error"] = f"{type(e).__name__}: {e}"
    row["wall_s"] = round(time.time() - t0, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="key cách nhau dấu phẩy")
    ap.add_argument("--json", help="ghi bảng kết quả ra file")
    a = ap.parse_args()
    samples = json.load(open(alpha_education_samples(), encoding="utf-8")) + frontend_samples()
    if a.only:
        want = set(a.only.split(","))
        samples = [s for s in samples if s["key"] in want]
    defaults = run_defaults()
    print(f"cửa sổ mặc định {defaults['start']} → {defaults['end']} | {len(defaults.get('symbols') or [])} tài sản | {len(samples)} mẫu", flush=True)
    rows = []
    for i, s in enumerate(samples, 1):
        r = run_one(s, defaults)
        r.pop("out", None)
        print(f"[{i}/{len(samples)}] {r['key']:34s} compile={'OK' if r['compile'] else 'FAIL'} run={'OK' if r['run'] else 'FAIL'} trades={r['trades']} "
              f"{r['wall_s']}s {r['error'] or ''}", flush=True)
        rows.append(r)
    ok = sum(r["run"] for r in rows)
    print(f"\nTỔNG: {ok}/{len(rows)} chạy OK, {len(rows) - ok} lỗi; compile OK {sum(r['compile'] for r in rows)}/{len(rows)}")
    for r in rows:
        if not r["run"]:
            print(f"  LỖI {r['key']}: {r['error']}")
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
