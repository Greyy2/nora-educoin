"""Sinh lại snapshot "golden results" vào tests/golden/*.json từ code HIỆN TẠI.

Chạy:  cd nora && scripts/run_limited.sh -- scripts/make_golden.py
Chỉ chạy lại khi CHỦ ĐÍCH đổi ngữ nghĩa backtest; thay đổi hiệu năng phải giữ nguyên các file này.
Kịch bản dữ liệu thật dùng NORA_GOLDEN_DATA_ROOT (mặc định <nora>/data), bỏ qua nếu thiếu dữ liệu.
Nhẹ (không dùng pool/đa tiến trình), không phụ thuộc NORA_ALLOW_UNLIMITED.
"""
import json
import os
import sys
import tempfile
import time

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, NORA)
sys.path.insert(0, os.path.join(NORA, "tests"))
GOLDEN_DIR = os.path.join(NORA, "tests", "golden")

import golden_scenarios as gs  # noqa: E402


def _write(name: str, canon: dict, seconds: float) -> None:
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    path = os.path.join(GOLDEN_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(canon, fh, indent=0, sort_keys=True)
        fh.write("\n")
    print(f"[make_golden] {name}: {len(canon['positions'])} positions, {canon['n_orders']} orders, "
          f"{len(canon['equity_curve'])} equity rows, {seconds:.1f}s -> {path}", flush=True)


def main() -> int:
    for name, fn in (("portfolio_synthetic", gs.scenario_portfolio_synthetic),
                     ("single_dca_filled", gs.scenario_single_dca_filled)):
        with tempfile.TemporaryDirectory(prefix="nora_golden_") as tmp:
            t = time.time()
            canon = fn(os.path.join(tmp, "data"))
            _write(name, canon, time.time() - t)
    data_root = os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(NORA, "data")
    if not gs.real_data_available(data_root):
        print(f"[make_golden] portfolio_real SKIPPED: thiếu BTC/perp/1m.pkl ... trong {data_root}", flush=True)
        return 0
    t = time.time()
    canon = gs.scenario_portfolio_real(data_root)
    _write("portfolio_real", canon, time.time() - t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
