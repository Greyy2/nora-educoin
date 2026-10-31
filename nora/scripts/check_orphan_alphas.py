import json
from pathlib import Path

user_dir = Path("nora/edu/data/alpha/user")
ids = ["ca1dece21d96", "04e66d1c63d7", "342d4c6f38d5", "9b86a200202a", "a7d15861ca72", "93edc7884cff"]

for i in ids:
    p = user_dir / f"{i}.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"{i}: owner_id={d.get('owner_id')}, name={d.get('name')}, status={d.get('status')}, forked_from={d.get('forked_from')}")
