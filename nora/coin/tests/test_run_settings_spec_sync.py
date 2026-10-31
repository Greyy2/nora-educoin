import os
import sys
from pathlib import Path
import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))

os.environ.setdefault("NORA_PRODUCT", "coin")
os.environ.setdefault("NORA_DIR", str(COIN_ROOT))

from backend.analys.alpha.code.compile import load_system_strategies, compile_code
from backend.analys.alpha.code.plan import build_plan
from backend.analys.param import resolve_position_auto, BASE_POSITION, NORA_DEFAULTS


def test_spec_owns_defaults_when_no_override():
    """2.1: Khi không có override ({}), cấu hình hiệu lực lấy đúng 100% từ Spec."""
    loaded = load_system_strategies()
    candidates = {c["id"]: c for c in loaded["candidates"]}

    # KEMA spec defaults
    kema = candidates["kema_long"]
    kema_spec_pos = kema.get("position", {})
    resolved_kema = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **kema_spec_pos}, "4h")

    assert resolved_kema["exit_unit"] == "atr"
    assert resolved_kema["atr_frame"] == "4h"
    assert resolved_kema["cooldown"] == 240

    # Sideway spec defaults
    sideway = candidates["sideway_long"]
    sideway_spec_pos = sideway.get("position", {})
    resolved_sideway = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **sideway_spec_pos}, "1h")

    assert resolved_sideway["exit_unit"] == "atr"
    assert resolved_sideway["atr_frame"] == "1h"
    assert resolved_sideway["cooldown"] == 60


def test_run_settings_only_modifies_specified_overrides():
    """2.1: RunSettings chỉ lưu overrides; các tham số không ghi đè giữ nguyên từ Spec."""
    loaded = load_system_strategies()
    kema = {c["id"]: c for c in loaded["candidates"]}["kema_long"]
    kema_spec_pos = kema.get("position", {})

    # Người dùng chỉ ghi đè stop_loss_rate = 2.5
    ui_overrides = {"stop_loss_rate": 2.5}
    resolved = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **kema_spec_pos, **ui_overrides}, "4h")

    # Chỉ stop_loss_rate đổi
    assert resolved["stop_loss_rate"] == 2.5
    # Các tham số khác từ spec vẫn giữ nguyên
    assert resolved["exit_unit"] == "atr"
    assert resolved["atr_frame"] == "4h"
    assert resolved["cooldown"] == 240


def test_provenance_records_effective_source_and_values():
    """2.4: Snapshot giá trị hiệu lực vào provenance ghi rõ source ('ui' vs 'code')."""
    code = """class MyTestAlpha(SimpleAlgorithm):
    timeframe = '1h'
    cooldown = 60
    stop_loss_rate = 3.0
    def __algorithm__(self):
        self.set_positions(self.data.pv_close > self.data.pv_open, position=1)
        self.set_positions(self.data.pv_close < self.data.pv_open, position=0)
"""
    prog = compile_code(code)
    # Ghi đè stop_loss_rate từ UI thành 2.0
    ui_pos = {"stop_loss_rate": 2.0}
    plan = build_plan(prog, symbols=["BTC@perp"], position=ui_pos)

    prov = plan.echo.get("param_provenance", {})
    assert "stop_loss_rate" in prov
    assert prov["stop_loss_rate"]["source"] == "ui"
    assert prov["stop_loss_rate"]["value"] == 2.0

    assert "cooldown" in prov
    assert prov["cooldown"]["source"] == "code"
    assert prov["cooldown"]["value"] == 60


def test_reset_overrides_restores_exact_spec_defaults():
    """2.2: Nút khôi phục mặc định (xóa overrides) phục hồi 100% cấu hình Spec."""
    loaded = load_system_strategies()
    kema = {c["id"]: c for c in loaded["candidates"]}["kema_long"]
    spec_pos = kema.get("position", {})

    # Lúc có override
    overrides = {"cooldown": 15, "stop_loss_rate": 1.5}
    with_overrides = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **spec_pos, **overrides}, "4h")
    assert with_overrides["cooldown"] == 15

    # Khi reset về rỗng
    reset_overrides = {}
    restored = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **spec_pos, **reset_overrides}, "4h")
    assert restored["cooldown"] == 240
    assert restored["exit_unit"] == "atr"
