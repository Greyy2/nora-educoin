import json
import sys
import os

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.alpha.code.compile import compile_code

alpha_ids = ["efa90f74cd08", "18e87aa868ad", "33312a2f4dfc", "alpha_proxima_research"]

for aid in alpha_ids:
    fpath = f"/home/vmc03/norabt/nora/coin/data/alpha/user/{aid}.json"
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    code = data.get("code", "")
    print(f"\n==========================================")
    print(f"Alpha: {aid} ({data.get('name')})")
    try:
        prog = compile_code(code)
        print(f"COMPILE RESULT: SUCCESS!")
        print(f"  Program name: {getattr(prog, 'name', None)}")
        print(f"  Program timeframe: {getattr(prog, 'timeframe', None)}")
        print(f"  Program features: {sorted(getattr(prog, 'features', []))}")
        print(f"  Program warmup_bars: {getattr(prog, 'warmup_bars', None)}")
        print(f"  Program position_overrides: {getattr(prog, 'position_overrides', None)}")
    except Exception as e:
        print(f"COMPILE RESULT: FAILED -> {type(e).__name__}: {e}")
