import json
from pathlib import Path

alpha_dir = Path("nora/edu/data/alpha/user")

# Danh sách 26 alpha ID của 26 user fixture
fx_alpha_ids = [
    "0bf936687964", "138df68946ad", "1a1a4389a821", "1e4c0b9f84f7",
    "214ea8fdf3e6", "234e6df02e37", "2e41b2cfa24d", "571474a18f55",
    "616e1b8cbc88", "64b657c8de8e", "74f607263c5c", "7c1bf0a9686a",
    "7f770ebe5ab5", "856ddc574ce7", "862e0c9eebbe", "930294d28c45",
    "9eec3d61131d", "a4d6826fbbc6", "af2bf88426c4", "bd234070bd7b",
    "be1174b24a44", "cb0b6e0f12e7", "d0518c0cca14", "e9a9a5b44d03",
    "ee0cf7f58f94", "fd16df3d0a3f"
]

print(f"Kiểm tra config của {len(fx_alpha_ids)} fixture alphas:")
for aid in fx_alpha_ids:
    p = alpha_dir / f"{aid}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    cfg = d.get("config", {})
    pos = cfg.get("position", {})
    print(f"{aid} | {d.get('name'):32s} | sym={cfg.get('symbols')} | tf={cfg.get('timeframe')} | run_frame={cfg.get('run_frame')} | start={cfg.get('start')} | end={cfg.get('end')} | sizing={pos.get('sizing')}")
