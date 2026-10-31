import sys
import json
import os

sys.path.insert(0, "/home/vmc03/norabt/nora/coin")
os.environ["NORA_DIR"] = "/home/vmc03/norabt/nora/coin"
os.environ["NORA_LOCAL_DATA_ROOT"] = "/home/vmc03/norabt/nora/coin/data"

from backend.analys.param import BASE_POSITION, NORA_DEFAULTS
from backend.analys.alpha.code.compile import _position_attr_names, RISK_PARAM_MAP

print("=== BASE_POSITION ===")
print(json.dumps(BASE_POSITION, indent=2))

print("\n=== NORA_DEFAULTS ===")
print(json.dumps(NORA_DEFAULTS, indent=2))

print("\n=== _position_attr_names (from compiler) ===")
print(sorted(list(_position_attr_names())))

print("\n=== RISK_PARAM_MAP (from compiler) ===")
print(json.dumps(RISK_PARAM_MAP, indent=2))
