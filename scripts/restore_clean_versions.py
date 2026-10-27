import json
from pathlib import Path

orig_13 = {
    '090730ae35b8.v1.json',
    '15567e02a806.v1.json',
    '18e87aa868ad.v1.json',
    '26aca0bfd4f9.v1.json',
    '270e6e28416f.v1.json',
    '303d4b713dda.v1.json',
    '33312a2f4dfc.v1.json',
    '717c1890c59e.v1.json',
    'a68011336aa5.v1.json',
    'bf519617d973.v1.json',
    'efb1fbe2db86.v1.json',
    'fa9587a97fa9.v1.json',
    'fa9587a97fa9.v2.json'
}

vdir = Path('nora/edu/data/alpha/user/_versions')
current_files = {f.name for f in vdir.glob('*.json')}
extra = current_files - orig_13
print(f'Extra generated version files to remove: {len(extra)}')
for name in extra:
    (vdir / name).unlink()
print(f'Remaining version files in _versions/: {len(list(vdir.glob("*.json")))}')
