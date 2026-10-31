import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COIN_ROOT = REPO_ROOT / "nora" / "coin"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))

import numpy as np
import pandas as pd
import pytest

from backend.analys.alpha.code.compile import compile_code
from backend.analys.signal.signal import Ctx

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "alpha"


def _make_daily_fixture(n_bars: int = 365) -> pd.DataFrame:
    base_ts = 1672531200000
    t = base_ts + np.arange(n_bars, dtype=np.int64) * 86_400_000
    np.random.seed(42)
    trend = np.linspace(20000, 45000, n_bars)
    noise = np.random.normal(0, 500, n_bars)
    c = trend + noise + 2000 * np.sin(np.linspace(0, 4 * np.pi, n_bars))
    h = c + np.abs(np.random.normal(300, 150, n_bars))
    l = c - np.abs(np.random.normal(300, 150, n_bars))
    o = c + np.random.normal(0, 100, n_bars)
    v = np.random.uniform(1000, 5000, n_bars)
    return pd.DataFrame({"open_time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})


@pytest.mark.parametrize("aid,expected_sl", [
    ("efa90f74cd08", 3.0),
    ("18e87aa868ad", 2.5),
    ("33312a2f4dfc", 2.5),
])
def test_user_alpha_v2_compiles_and_matches_v1_signals(aid, expected_sl):
    """Test 3 bản v2 compile thành công, tường minh exit_unit='atr' và tín hiệu khớp bit-for-bit với v1."""
    v1_file = DATA_DIR / "user" / f"{aid}.json"
    v2_file = DATA_DIR / "user" / f"{aid}_v2.json"
    
    assert v1_file.is_file(), f"Missing v1 file: {v1_file}"
    assert v2_file.is_file(), f"Missing v2 file: {v2_file}"
    
    d1 = json.loads(v1_file.read_text(encoding="utf-8"))
    d2 = json.loads(v2_file.read_text(encoding="utf-8"))
    
    prog_v1 = compile_code(d1["code"])
    prog_v2 = compile_code(d2["code"])
    
    # 1. Kiểm tra position overrides v2
    pos2 = prog_v2.position_overrides
    assert pos2.get("exit_unit") == "atr"
    assert pos2.get("stop_loss_rate") == expected_sl
    assert pos2.get("cooldown") == 1440
    assert pos2.get("risk_per_trade_pct") == 0.25
    
    # 2. Kiểm tra tín hiệu đối soát trên fixture 365 nến daily
    df = _make_daily_fixture(365)
    n1, data1 = prog_v1._data(df)
    ctx1 = Ctx(n1, data1)
    v1_signals = [np.asarray(call[0].ev(ctx1), dtype=bool) for call in prog_v1.calls]
    
    n2, data2 = prog_v2._data(df)
    ctx2 = Ctx(n2, data2)
    v2_signals = [np.asarray(call[0].ev(ctx2), dtype=bool) for call in prog_v2.calls]
    
    assert len(v1_signals) == len(v2_signals)
    for idx in range(len(v1_signals)):
        assert np.array_equal(v1_signals[idx], v2_signals[idx]), f"Lệch tín hiệu call #{idx} giữa v1 và v2 của {aid}"


@pytest.mark.parametrize("agent_slug,expected_name,expected_pos", [
    ("okx_01pp", "ProxyExitFit01pp", {"exit_unit": "pct", "take_profit_rate": 0.931, "leverage": 15}),
    ("okx_auroraxwt", "ProxyExitFitAuroraxwt", {"exit_unit": "pct", "stop_loss_rate": 0.218, "leverage": 20}),
    ("okx_dark_wood_dahlia", "ProxyExitFitDarkWoodDahlia", {"exit_unit": "pct", "take_profit_rate": 3.159, "leverage": 10}),
])
def test_top_agent_draft_compiles_with_unverified_label(agent_slug, expected_name, expected_pos):
    """Test 3 chiến lược Top Agent proxy trong catalog nghiên cứu scripts/ compile thành công với nhãn DRAFT_UNVERIFIED."""
    from scripts.top_agents_proxy_catalog import TOP_AGENT_PROXY_CODES
    assert agent_slug in TOP_AGENT_PROXY_CODES, f"Missing {agent_slug} in scripts/top_agents_proxy_catalog.py"
    class_code = TOP_AGENT_PROXY_CODES[agent_slug]

    assert f"class {expected_name}" in class_code, f"Không tìm thấy class {expected_name}"
    assert "[DRAFT_UNVERIFIED]" in class_code, "Code phải có nhãn cảnh báo [DRAFT_UNVERIFIED]"
    assert "[PROXY_EXIT_FIT]" in class_code, "Code phải có nhãn [PROXY_EXIT_FIT]"

    prog = compile_code(class_code)
    assert prog.name == expected_name
    for k, v in expected_pos.items():
        assert prog.position_overrides.get(k) == v, (
            f"Mismatch parameter {k}: {prog.position_overrides.get(k)} != {v}"
        )

