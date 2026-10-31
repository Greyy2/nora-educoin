import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NORA_DIR = REPO_ROOT / "nora"

def check_import_isolation():
    print("=== CHECKING IMPORT ISOLATION BETWEEN COIN AND EDU ===")
    
    # 1. EDU -> COIN
    edu_backend = NORA_DIR / "edu" / "backend"
    cross_edu_to_coin = []
    for py_file in edu_backend.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            if re.search(r"(from|import)\s+.*\b(nora\.coin|coin\.backend)\b", content):
                cross_edu_to_coin.append(str(py_file.relative_to(REPO_ROOT)))
        except Exception as e:
            pass

    # 2. COIN -> EDU
    coin_backend = NORA_DIR / "coin" / "backend"
    cross_coin_to_edu = []
    for py_file in coin_backend.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            if re.search(r"(from|import)\s+.*\b(nora\.edu|edu\.backend)\b", content):
                cross_coin_to_edu.append(str(py_file.relative_to(REPO_ROOT)))
        except Exception as e:
            pass

    print(f"EDU -> COIN cross-imports: {len(cross_edu_to_coin)}")
    for f in cross_edu_to_coin:
        print(f"  VIOLATION: {f}")

    print(f"COIN -> EDU cross-imports: {len(cross_coin_to_edu)}")
    for f in cross_coin_to_edu:
        print(f"  VIOLATION: {f}")

    if cross_edu_to_coin or cross_coin_to_edu:
        print("\nRESULT: FAILED import isolation check!")
        sys.exit(1)
    else:
        print("\nRESULT: PASS — 0 cross-import violations between COIN and EDU!")

if __name__ == "__main__":
    check_import_isolation()
