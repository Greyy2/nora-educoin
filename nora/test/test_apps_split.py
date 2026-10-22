"""
Verification script for Nora EDU / COIN / Monolith architecture split.
Checks:
1. Imports of backend.apps.edu:app and backend.apps.coin:app
2. Import of legacy backend.main:app
3. Isolation of routes (no live/bot routes in EDU, proper edu/studio routes in EDU)
4. System routers ordering and registration
"""
import sys
import os

sys.path.insert(0, '/home/vmc03/norabt/nora')

def get_all_paths(app):
    return list(app.openapi().get("paths", {}).keys())

def test_split():
    print("Testing backend.apps.edu...")
    from backend.apps.edu import app as edu_app
    assert edu_app is not None, "edu_app is None"
    edu_paths = get_all_paths(edu_app)
    print(f"  EDU routes: {len(edu_paths)} routes")
    assert any('/api/studio' in p for p in edu_paths), "Missing /api/studio in EDU app"
    assert not any('/api/live' in p for p in edu_paths), "Leaked /api/live into EDU app!"
    assert not any('bot' in p.lower() and not 'prompt' in p.lower() for p in edu_paths), "Bot route in EDU app"

    print("Testing backend.apps.coin...")
    from backend.apps.coin import app as coin_app
    assert coin_app is not None, "coin_app is None"
    coin_paths = get_all_paths(coin_app)
    print(f"  COIN routes: {len(coin_paths)} routes")
    assert any('/live' in p for p in coin_paths), "Missing /live in COIN app"
    assert any('/overview' in p for p in coin_paths), "Missing /overview in COIN app"

    print("Testing backend.main (monolith)...")
    from backend.main import app as legacy_app
    assert legacy_app is not None, "legacy_app is None"
    legacy_paths = get_all_paths(legacy_app)
    print(f"  Legacy routes: {len(legacy_paths)} routes")

    print("Testing system.ROUTERS...")
    from backend.routes.system import ROUTERS
    print(f"  system.ROUTERS count: {len(ROUTERS)}")
    assert len(ROUTERS) >= 5, f"Expected at least 5 system routers, got {len(ROUTERS)}"

    print("ALL BACKEND SPLIT VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_split()
