import sys
from pathlib import Path

import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COIN_ROOT))

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


def test_available_universe_reads_all_catalog_assets(tmp_path, monkeypatch):
    bars = tmp_path / "data" / "bar"
    (bars / "AERO-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL").mkdir(parents=True)
    (bars / "ZETA-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL").mkdir()
    monkeypatch.setattr(market_data, "default_catalog_path", lambda: str(tmp_path))

    assert market_data.available_universe() == ["AERO", "ZETA"]


def test_run_defaults_separates_selected_from_all_available_assets(monkeypatch):
    monkeypatch.setattr(market_data, "default_window", lambda: ("2025-01-01", "2025-02-01"))
    monkeypatch.setattr(market_data, "default_universe", lambda: ["BTC"])
    monkeypatch.setattr(market_data, "available_universe", lambda: ["BTC", "NEWCOIN"])

    defaults = market_data.run_defaults()

    assert defaults["symbols"] == ["BTC@perp"]
    assert defaults["available_symbols"] == ["BTC@perp", "NEWCOIN@perp"]

    monkeypatch.setattr(market_data, "available_universe", lambda: [])
    defaults_without_catalog = market_data.run_defaults()
    assert defaults_without_catalog["symbols"] == []
    assert defaults_without_catalog["available_symbols"] == []


def test_live_launch_requires_an_explicit_market():
    from backend.jobs.runner.live import resolve_live_source
    from backend.routes.live import StartBotRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StartBotRequest()
    with pytest.raises(ValueError, match="market"):
        resolve_live_source({})
