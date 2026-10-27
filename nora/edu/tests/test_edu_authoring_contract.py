"""Unit tests locking the EDU authoring contract and runtime execution contract.
Covers:
1. Supported base classes and lifecycle methods (on_start/on_bar vs __algorithm__).
2. Supported indicators and operators in custom DSL.
3. Position keys, overrides, and provenance mapping in build_plan.
4. Stop loss and take profit units (percentage points: 2.0 = 2%).
5. Zero slippage and fee disclosure.
"""
import pytest
from pathlib import Path
import sys

# Ensure EDU backend is importable
edu_root = Path(__file__).resolve().parent.parent
if str(edu_root) not in sys.path:
    sys.path.insert(0, str(edu_root))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.contract import BASE_CLASSES, LIFECYCLE
from backend.analys.alpha.code.plan import build_plan
from backend.analys.signal import DslError, Program
from backend.analys.param import POSITION_KEYS


def test_supported_base_classes():
    # SimpleAlgorithm, NoraStrategy, AlphaStrategy are custom DSL base classes
    for base in ("SimpleAlgorithm", "NoraStrategy", "AlphaStrategy"):
        code = f"""
class StrategyWithBase({base}):
    timeframe = "1h"
    def on_bar(self):
        c = self.data.pv_close
        sma = self.feat.sma(c, 10)
        self.set_positions(c > sma, position=1.0)
        self.set_positions(c < sma, position=0.0)
"""
        prog = compile_code(code)
        assert isinstance(prog, Program)
        assert prog.timeframe == "1h"
        assert prog.legs == ["LONG"]


def test_lifecycle_on_start_and_on_bar():
    code = """
class LifecycleStrategy(SimpleAlgorithm):
    timeframe = "4h"
    stop_loss_rate = 2.0
    take_profit_rate = 4.0
    exit_unit = "pct"
    period_fast = 9
    period_slow = 21

    def on_start(self):
        pass

    def on_bar(self):
        c = self.data.pv_close
        fast = self.feat.ema(c, self.period_fast)
        slow = self.feat.ema(c, self.period_slow)
        self.set_positions(fast > slow, position=1.0)
        self.set_positions(fast < slow, position=0.0)

    def on_stop(self):
        pass
"""
    prog = compile_code(code)
    assert prog.timeframe == "4h"
    assert prog.legs == ["LONG"]
    assert prog.position_overrides["stop_loss_rate"] == 2.0
    assert prog.position_overrides["take_profit_rate"] == 4.0
    assert prog.position_overrides["exit_unit"] == "pct"


def test_reject_mixing_algorithm_and_on_bar():
    code = """
class InvalidMix(SimpleAlgorithm):
    timeframe = "1h"
    def __algorithm__(self):
        self.set_positions(self.data.pv_close > 100, position=1.0)
    def on_bar(self):
        self.set_positions(self.data.pv_close < 100, position=0.0)
"""
    with pytest.raises(DslError, match="Không trộn `__algorithm__` với on_start/on_bar"):
        compile_code(code)


def test_dsl_forbidden_constructs():
    # If statements are forbidden in vector DSL
    code_if = """
class IfStrategy(SimpleAlgorithm):
    timeframe = "1h"
    def on_bar(self):
        if self.data.pv_close > 100:
            self.set_positions(1, position=1.0)
"""
    with pytest.raises(DslError, match="DSL không có rẽ nhánh"):
        compile_code(code_if)


def test_position_overrides_provenance_and_units():
    code = """
class PosStrategy(SimpleAlgorithm):
    timeframe = "1h"
    stop_loss_rate = 2.5
    take_profit_rate = 5.0
    exit_unit = "pct"
    leverage = 2
    risk_per_trade_pct = 1.0
    slippage_rate = 0.0

    def on_bar(self):
        c = self.data.pv_close
        sma = self.feat.sma(c, 20)
        self.set_positions(c > sma, position=1.0)
        self.set_positions(c < sma, position=0.0)
"""
    prog = compile_code(code)
    plan = build_plan(prog, symbols=["BTC/USDT"])
    
    echo = plan.echo
    prov = echo["param_provenance"]

    # Verify declared in code
    assert prov["stop_loss_rate"]["source"] == "code"
    assert prov["stop_loss_rate"]["value"] == 2.5
    assert prov["stop_loss_rate"]["unit"] == "%"

    assert prov["take_profit_rate"]["source"] == "code"
    assert prov["take_profit_rate"]["value"] == 5.0
    assert prov["take_profit_rate"]["unit"] == "%"

    assert prov["leverage"]["source"] == "code"
    assert prov["leverage"]["value"] == 2
    assert prov["leverage"]["unit"] == "x"

    assert prov["slippage_rate"]["source"] == "code"
    assert prov["slippage_rate"]["value"] == 0.0
    assert prov["slippage_rate"]["unit"] == "%"


def test_canonical_teaching_templates():
    from data.alpha.education.canonical_templates import CANONICAL_TEMPLATES
    assert len(CANONICAL_TEMPLATES) == 2

    for tmpl in CANONICAL_TEMPLATES:
        code = str(tmpl["code"])
        prog = compile_code(code)
        assert isinstance(prog, Program)
        assert prog.legs == ["LONG"]
        assert prog.timeframe == tmpl["timeframe"]

        plan = build_plan(prog, symbols=["BTC/USDT"])
        prov = plan.echo["param_provenance"]
        
        # Check that stop_loss_rate is declared in code with correct unit
        assert prov["stop_loss_rate"]["source"] == "code"
        assert prov["stop_loss_rate"]["unit"] == "%"
        assert prov["exit_unit"]["source"] == "code"
        assert prov["exit_unit"]["value"] == "pct"

        # Check disclosures exist
        assert "slippage" in tmpl["disclosures"]
        assert "fees" in tmpl["disclosures"]
        assert "purpose" in tmpl["disclosures"]


def test_ui_override_conflict_warning():
    code = """
class PosConflictStrategy(SimpleAlgorithm):
    timeframe = "1h"
    stop_loss_rate = 2.0
    exit_unit = "pct"

    def on_bar(self):
        c = self.data.pv_close
        sma = self.feat.sma(c, 20)
        self.set_positions(c > sma, position=1.0)
        self.set_positions(c < sma, position=0.0)
"""
    prog = compile_code(code)
    # UI overrides stop_loss_rate to 5.0
    plan = build_plan(prog, symbols=["BTC/USDT"], position={"stop_loss_rate": 5.0})
    
    assert len(plan.warnings) > 0
    assert "Tham số vị thế 'stop_loss_rate' khai báo trong code là 2.0 nhưng đang bị cấu hình giao diện ghi đè thành 5.0" in plan.warnings[0]
    assert plan.echo["param_provenance"]["stop_loss_rate"]["source"] == "ui"
    assert plan.echo["param_provenance"]["stop_loss_rate"]["value"] == 5.0
