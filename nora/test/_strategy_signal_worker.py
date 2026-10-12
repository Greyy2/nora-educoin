"""Worker của test_strategy_signal_parity.py: chạy trong tiến trình con (để backend cũ/mới không đụng tên gói `backend`).
Dùng: python _strategy_signal_worker.py <module chứa evaluate_signals/build_plan/required_frames> <in.json> <out.npz>
in.json: {"samples": [{"key", "code"}], "symbols": [...], "start": ms, "end": ms, "warm_ms": ms, "root": thư mục data/market/okx/cex}."""
import importlib
import json
import os
import sys

import numpy as np
import pandas as pd


def main(module: str, inp: str, out: str) -> None:
    cfg = json.load(open(inp, encoding="utf-8"))
    import backend  # noqa: F401  (đăng ký nguồn dữ liệu mặc định, như conftest)
    mod = importlib.import_module(module)
    from backend.alpha.compile import compile_code
    res = {}
    for smp in cfg["samples"]:
        try:
            prog = compile_code(smp["code"])
            plan = mod.build_plan(prog, cfg["symbols"], run_frame=prog.timeframe)
        except Exception as e:   # lỗi biên dịch/dựng kế hoạch: phải GIỐNG NHAU ở hai phía
            res[f"{smp['key']}|error"] = np.array(f"{type(e).__name__}: {e}")
            continue
        # limit_through_pct là tham số KHỚP LỆNH, không phải tín hiệu: P15-D đổi mặc định 0.05 -> 0 (Nautilus không mô phỏng "giá đi xuyên mức limit",
        # core/params.py::BASE_POSITION) nên bỏ khỏi so sánh kế hoạch; mọi khoá còn lại (gồm cột ATR exit_unit/atr_frame/atr_period) vẫn so từng ký tự.
        strategies = [{**st, "position": {k: v for k, v in st["position"].items() if k != "limit_through_pct"}} for st in plan.strategies]
        res[f"{smp['key']}|plan"] = np.array(json.dumps(strategies, sort_keys=True, default=str))
        for sym in cfg["symbols"]:
            need = mod.required_frames(sym, plan.strategies, plan.base_frame)
            frames = {}
            for fr in need:
                df = pd.read_pickle(os.path.join(cfg["root"], sym, "perp", f"{fr}.pkl"))
                ot = pd.to_numeric(df["open_time"])
                frames[fr] = df[(ot >= cfg["start"] - cfg["warm_ms"]) & (ot < cfg["end"])].reset_index(drop=True)
            v = mod.evaluate_signals(sym, plan.strategies, frames, plan.base_frame)
            for k in ("t", "open", "close", "high", "low"):
                res[f"{smp['key']}|{sym}|{k}"] = np.asarray(v[k])
            for i, e in enumerate(v["entries"]):
                for k in ("match", "stop", "vol", "dca"):
                    if e[k] is not None:
                        res[f"{smp['key']}|{sym}|{i}|{k}"] = np.asarray(e[k])
    np.savez(out, **res)


if __name__ == "__main__":
    main(*sys.argv[1:4])
