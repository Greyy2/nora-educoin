import json, os, collections
from pathlib import Path

base = Path('nora/edu/data')
ad = base / 'alpha/user'
ud = base / 'users'
archive_dir = base / 'alpha/_unlinked_archive'

accounts = {}
for f in ud.glob('*.json'):
    try:
        accounts[f.stem] = json.loads(f.read_text())
    except Exception:
        pass

alphas = []
for f in ad.glob('*.json'):
    try:
        alphas.append((f.stem, json.loads(f.read_text())))
    except Exception:
        pass

owners = collections.defaultdict(list)
unlinked = []
for aid, x in alphas:
    oid = x.get('owner_id')
    if oid in accounts:
        owners[oid].append((aid, x))
    else:
        unlinked.append((aid, x))

def outcome(x):
    m = (x.get('result') or {}).get('metrics') or x.get('metrics') or {}
    m = m.get('simulate') if isinstance(m, dict) else None
    if not isinstance(m, dict): return None
    for k in ('net_pnl_usdt', 'net_pnl_usd', 'pnl_usd'):
        if isinstance(m.get(k), (float, int)): return float(m[k])
    for k in ('net_return_pct', 'ret_pct', 'total_return_pct'):
        if isinstance(m.get(k), (float, int)): return float(m[k])
    return None

cats = {}
for oid, rs in owners.items():
    vals = [outcome(x) for _, x in rs]
    if all(v > 0 for v in vals): cats[oid] = 'all_positive'
    elif any(v > 0 for v in vals) and any(v < 0 for v in vals): cats[oid] = 'mixed'
    elif all(v >= 0 for v in vals) and any(v == 0 for v in vals): cats[oid] = 'nonnegative_has_zero'
    elif all(v < 0 for v in vals): cats[oid] = 'all_loss'
    else: cats[oid] = 'unknown'

no_alpha_users = [u for u in accounts if u not in owners]
all_pos_users = [u for u, c in cats.items() if c == 'all_positive']
mixed_users = [u for u, c in cats.items() if c == 'mixed']
zero_users = [u for u, c in cats.items() if c == 'nonnegative_has_zero']

archived_files = list(archive_dir.glob('*.json')) if archive_dir.exists() else []

summary = {
    "total_accounts": len(accounts),
    "no_alpha_users_count": len(no_alpha_users),
    "no_alpha_users": [(u, accounts[u].get('handle') or accounts[u].get('username')) for u in no_alpha_users],
    "all_positive_users_count": len(all_pos_users),
    "vinh_in_all_positive": "aed197a5e968" in all_pos_users,
    "mixed_users_count": len(mixed_users),
    "nonnegative_has_zero_users_count": len(zero_users),
    "total_alphas_in_user_dir": len(alphas),
    "unlinked_alphas_in_user_dir": len(unlinked),
    "archived_unlinked_alphas_count": len(archived_files)
}

print(json.dumps(summary, indent=2, ensure_ascii=False))

# Update manifest with final kept_users
manifest_path = Path("nora/check/edu_cleanup_manifest.json")
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text())
    manifest["kept_users"] = sorted(list(accounts.keys()))
    manifest["final_stats"] = summary
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
