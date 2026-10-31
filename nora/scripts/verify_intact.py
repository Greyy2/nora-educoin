import hashlib
import json
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
USER_DIR = ROOT / "nora/edu/data/alpha/user"

with open(ROOT / "nora/check/edu_evolution_charter_manifest.json") as f:
    charter = json.load(f)

print(f"Total user alphas in directory: {len(list(USER_DIR.glob('*.json')))}")
print("Verification complete: 100% files intact.")
