"""Dựng kho alpha + cấu hình Binance Futures testnet từ kết quả scripts/optimize_alphas.py.

Dùng:  PYTHONPATH=. python scripts/build_alpha_registry.py <thư mục kết quả tối ưu> [--out alphas]
"""
import argparse
import json
import os
import sys

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "alphas"))
    args = ap.parse_args(argv)
    from backend.optimize.registry import build_registry, write_registry
    from backend.core.strategy.strategy_library import OPTIMIZATION_SPACES

    with open(os.path.join(args.results_dir, "results.json"), encoding="utf-8") as fh:
        results = json.load(fh)
    import glob
    robustness = {}
    for path in glob.glob(os.path.join(args.results_dir, "robustness_*.json")):
        with open(path, encoding="utf-8") as fh:
            rep = json.load(fh)
        robustness[f"{rep['space']}__{rep['symbol']}"] = rep
    registry = build_registry(results, OPTIMIZATION_SPACES, source=os.path.abspath(args.results_dir),
                              repo_dir=os.path.dirname(NORA_ROOT), robustness=robustness)
    for path in write_registry(registry, args.out):
        print("ghi:", path)
    print(f"{len(registry['alphas'])} alpha / {registry['pairs_evaluated']} cặp đã đánh giá")


if __name__ == "__main__":
    main()
