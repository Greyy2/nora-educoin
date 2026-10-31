import json
from pathlib import Path

root = Path("nora/check/candidates")
for p in sorted(root.glob("*/*.json")):
    try:
        d = json.loads(p.read_text())
        print(f"{p.parent.name} | {p.name} | hyp: {d.get('hypothesis_type')} | len_code: {len(d.get('code', ''))}")
    except Exception as e:
        print(f"{p}: err {e}")
