import os
import json
from pathlib import Path
from collections import Counter

def inspect_app(app_name, path_str):
    base = Path(path_str)
    users_dir = base / "data" / "users"
    alpha_dir = base / "data" / "alpha" / "user"
    quarantine_dir = base / "data" / "alpha" / "_quarantine"
    
    users = {}
    if users_dir.is_dir():
        for f in users_dir.iterdir():
            if f.name.endswith(".json") and f.is_file():
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        d = json.load(fp)
                        if isinstance(d, dict) and "id" in d:
                            users[d["id"]] = d
                except Exception:
                    pass

    alphas = []
    if alpha_dir.is_dir():
        for f in alpha_dir.iterdir():
            if f.name.endswith(".json") and f.is_file():
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        d = json.load(fp)
                        alphas.append((f.stem, d))
                except Exception:
                    pass

    quarantine = []
    if quarantine_dir.is_dir():
        for f in quarantine_dir.iterdir():
            if f.name.endswith(".json") and f.is_file():
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        d = json.load(fp)
                        quarantine.append((f.stem, d))
                except Exception:
                    pass

    # Map alphas to users
    user_alpha_counts = Counter()
    unowned_alphas = 0
    orphan_alphas = 0

    for aid, adata in alphas:
        oid = adata.get("owner_id")
        if not oid:
            unowned_alphas += 1
        elif oid in users:
            user_alpha_counts[oid] += 1
        else:
            orphan_alphas += 1

    users_with_alphas = len(user_alpha_counts)
    
    return {
        "app": app_name,
        "total_users": len(users),
        "total_active_alphas": len(alphas),
        "total_quarantine_alphas": len(quarantine),
        "total_strategies": len(alphas) + len(quarantine),
        "users_with_strategies": users_with_alphas,
        "users_without_strategies": len(users) - users_with_alphas,
        "unowned_system_alphas": unowned_alphas,
        "orphan_alphas": orphan_alphas,
        "distribution": Counter(user_alpha_counts.values())
    }

print(json.dumps(inspect_app("COIN", "nora/coin"), indent=2))
print(json.dumps(inspect_app("EDU", "nora/edu"), indent=2))
