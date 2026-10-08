"""Sinh lại snapshot golden đường TICK vào test/golden/tick_*.json từ code HIỆN TẠI (P9.4b T0).

Chạy:  cd nora && ops/run_limited.sh --no-lock -- test/scripts/make_golden_tick.py
Chỉ chạy lại khi CHỦ ĐÍCH đổi ngữ nghĩa tick; refactor phải giữ nguyên các file này (test/test_tick_golden.py).
"""
import json
import os
import sys
import time

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, NORA)
sys.path.insert(0, os.path.join(NORA, "test"))
os.environ.setdefault("NORA_ALLOW_UNLIMITED", "1")
GOLDEN_DIR = os.path.join(NORA, "test", "golden")

import golden_tick_scenarios as gts  # noqa: E402


def main() -> int:
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for name, canon in gts.all_scenarios():
        t = time.time()
        path = os.path.join(GOLDEN_DIR, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(canon, fh, indent=0, sort_keys=True)
            fh.write("\n")
        r = canon["result"]
        print(f"[make_golden_tick] {name}: trades={r.get('trades')} final_equity={r.get('final_equity')} {time.time() - t:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
