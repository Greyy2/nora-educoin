"""Golden đường TICK (TickBook / run_tick): kết quả phải BIT-IDENTICAL với test/golden/tick_*.json (P9.4b T0 — mốc trước khi gộp engine).

Sinh lại CHỈ khi chủ đích đổi ngữ nghĩa tick:  backend/utils/ops/run_limited.sh --no-lock -- test/scripts/make_golden_tick.py
"""
import json
import os

import pytest

import golden_scenarios as gs
import golden_tick_scenarios as gts

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
FIXED = [n for n, _ in gts._fixed()]
NAMES = [f"tick_{n}" for n in FIXED] + [f"tick_rand{s:02d}" for s in range(gts.N_RANDOM)]


def _load(name):
    path = os.path.join(GOLDEN_DIR, f"{name}.json")
    if not os.path.isfile(path):
        pytest.fail(f"Thiếu snapshot {path} — chạy test/scripts/make_golden_tick.py")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _first_diff(a, b, path=""):
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}/{k}: missing on one side"
            d = _first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
    elif a != b:
        return f"{path}: golden={gs.unhx(a)!r} new={gs.unhx(b)!r}"
    return None


def _check(name, fresh):
    text = json.dumps(fresh, indent=0, sort_keys=True) + "\n"
    golden = _load(name)
    if text != golden:
        pytest.fail(f"{name}: khác snapshot. Khác biệt đầu tiên: {_first_diff(json.loads(golden), fresh)}")


@pytest.mark.parametrize("name", FIXED)
def test_tick_golden_fixed_markets(name):
    fn = dict(gts._fixed())[name]
    with gts.tick_market() as root:
        _check(f"tick_{name}", {"scenario": name, "result": gts.canon_result(fn(root))})


@pytest.mark.parametrize("seed", range(gts.N_RANDOM))
def test_tick_golden_random_configs(seed):
    cfg = gts.random_config(seed)
    _check(f"tick_rand{seed:02d}", {"scenario": f"rand{seed:02d}", "config": gts.canon(cfg), "result": gts.canon_result(gts.run_random(cfg))})


def test_tick_golden_set_is_complete_and_nontrivial():
    on_disk = sorted(f[:-5] for f in os.listdir(GOLDEN_DIR) if f.startswith("tick_") and f.endswith(".json"))
    assert on_disk == sorted(NAMES)
    res = [json.loads(_load(n))["result"] for n in NAMES]
    cfgs = [json.loads(_load(f"tick_rand{s:02d}"))["config"] for s in range(gts.N_RANDOM)]
    assert sum(r["trades"] for r in res) > 100
    assert any(len(c["pools"]) == 2 for c in cfgs) and any(p["stable"] for c in cfgs for p in c["pools"])
    assert any("dca_steps" in c["position"] for c in cfgs) and any(c["position"]["sizing"] == "risk" for c in cfgs)
    assert any(t["layers"] > 1 for r in res for t in r["trade_list"]), "không kịch bản nào có DCA khớp"
