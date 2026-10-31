import os
import sys
from pathlib import Path

EDU_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDU_ROOT))
os.environ["NORA_DATA_ROOT"] = str(EDU_ROOT / "data")

from backend.analys.param import selected_market_cost_defaults
from backend.data import data as market_data


def test_selected_market_cost_presets_average_only_markets_with_presets():
    costs = selected_market_cost_defaults(["BTC@perp", "ETH-USDT-SWAP", "NEWCOIN@perp"])

    assert costs["BTC"] == {
        "fee_rate": 0.0005,
        "maker_fee_rate": 0.0002,
        "slippage_rate": 0.0004,
    }
    assert costs["ETH"] == costs["BTC"]
    assert costs["NEWCOIN"] == {
        "fee_rate": 0.0,
        "maker_fee_rate": 0.0,
        "slippage_rate": 0.0,
    }


def test_selected_market_cost_preset_and_no_preset_cases():
    assert selected_market_cost_defaults(["BNB"])["BNB"] == {
        "fee_rate": 0.0005,
        "maker_fee_rate": 0.0002,
        "slippage_rate": 0.0005,
    }
    assert selected_market_cost_defaults(["NEWCOIN"])["NEWCOIN"] == {
        "fee_rate": 0.0,
        "maker_fee_rate": 0.0,
        "slippage_rate": 0.0,
    }


def test_run_defaults_offers_all_catalog_assets(monkeypatch):
    monkeypatch.setattr(market_data, "default_window", lambda: ("2025-01-01", "2025-02-01"))
    monkeypatch.setattr(market_data, "available_universe", lambda: ["BTC", "NEWCOIN"])

    defaults = market_data.run_defaults()

    assert defaults["symbols"] == ["BTC@perp"]
    assert defaults["available_symbols"] == ["BTC@perp", "NEWCOIN@perp"]

    monkeypatch.setattr(market_data, "available_universe", lambda: [])
    defaults_without_catalog = market_data.run_defaults()
    assert defaults_without_catalog["symbols"] == []
    assert defaults_without_catalog["available_symbols"] == []


def test_available_universe_is_empty_when_market_catalog_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(market_data, "default_catalog_path", lambda: str(tmp_path / "missing"))

    assert market_data.available_universe() == []
