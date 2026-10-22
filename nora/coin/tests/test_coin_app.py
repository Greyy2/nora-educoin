"""Kiểm thử tính độc lập của dự án nora/coin."""
import os
import sys
from pathlib import Path

COIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COIN_ROOT))

def test_coin_imports_and_routes():
    from backend.main import app
    assert app is not None
    assert app.title == "Nora COIN API"

    paths = list(app.openapi().get("paths", {}).keys())
    print(f"Total COIN routes: {len(paths)}")
    assert any("/live" in p for p in paths)
    assert any("/portfolio" in p for p in paths)
    assert any("/api/studio/meta" in p for p in paths)
    assert any("/data" in p for p in paths)
    assert not any("/api/edu" in p for p in paths), "Không được có route /api/edu trong COIN!"
    print("✅ COIN project routes test passed!")

def test_coin_data_isolation():
    from backend.models.storage import data_home
    home = data_home()
    assert "coin/data" in home or "coin" in home, f"Data root không trỏ vào coin: {home}"
    print(f"✅ COIN data root verified: {home}")

if __name__ == "__main__":
    test_coin_imports_and_routes()
    test_coin_data_isolation()
    print("🎉 ALL COIN PROJECT TESTS PASSED!")
