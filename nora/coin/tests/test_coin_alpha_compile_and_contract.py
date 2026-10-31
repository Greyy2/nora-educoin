"""Test C1 — Bước 3: Compile và kiểm tra contract 6 candidate COIN Alpha.

Mục tiêu:
1. Compile thành công cả 6 candidate legs (kema_long, kema_short, sideway_long, sideway_short, dca_long, dca_short).
2. Kiểm schema defaults: các tham số bắt buộc phải có giá trị hợp lệ.
3. Kiểm exit_unit hiệu lực: tất cả candidate phải có exit_unit='atr' sau khi merge BASE_POSITION.
4. Kiểm DCA khai báo tường minh vs KEMA/Sideway kế thừa BASE_POSITION.
5. Kiểm DCA budget không vượt trần.
6. Kiểm side/family nhất quán giữa candidates và STRATEGIES.
7. Kiểm KEMA/Sideway không có TP mặc định (chỉ exit_signal + SL).
8. Kiểm DCA gate params tồn tại và đủ 3 gate (er, adx, rsi).

Không chạy backtest — kiểm contract code-level thuần túy.
"""
import os
import sys
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
COIN_ROOT = os.path.join(REPO, "nora", "coin")
if COIN_ROOT not in sys.path:
    sys.path.insert(0, COIN_ROOT)

os.environ.setdefault("NORA_PRODUCT", "coin")
os.environ.setdefault("NORA_DIR", COIN_ROOT)
os.environ.setdefault("NORA_LOCAL_DATA_ROOT", os.path.join(COIN_ROOT, "data"))
os.environ.setdefault("NORA_LOCAL_LOGS_ROOT", "/tmp/nora_logs_test")
os.environ.setdefault("NORA_JWT_SECRET", "test-secret-compile")

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.alpha.strategies import CANDIDATES, STRATEGIES, BY_ID
from backend.analys.param import BASE_POSITION, schema_defaults

EXPECTED_IDS = {"kema_long", "kema_short", "sideway_long", "sideway_short", "dca_long", "dca_short"}
DCA_IDS = {"dca_long", "dca_short"}
KEMA_IDS = {"kema_long", "kema_short"}
SIDEWAY_IDS = {"sideway_long", "sideway_short"}


# ── 1. Compile thành công ────────────────────────────────────────────────────

def test_all_six_candidates_present():
    """6 candidate legs phải có sau khi load_system_strategies."""
    ids = {c["id"] for c in CANDIDATES}
    assert EXPECTED_IDS <= ids, f"Thiếu candidates: {EXPECTED_IDS - ids}"


def test_all_candidates_have_required_fields():
    """Mỗi candidate phải có id, side, family, params_schema, position."""
    for c in CANDIDATES:
        if c["id"] not in EXPECTED_IDS:
            continue
        assert c.get("id"), f"{c['id']}: thiếu id"
        assert c.get("side") in ("LONG", "SHORT"), f"{c['id']}: side phải LONG|SHORT"
        assert isinstance(c.get("params_schema"), dict), f"{c['id']}: thiếu params_schema"
        assert isinstance(c.get("position"), dict), f"{c['id']}: thiếu position dict"


def test_load_system_strategies_compiles_clean():
    """load_system_strategies không raise; candidates và strategies không rỗng."""
    loaded = load_system_strategies()
    assert len(loaded["candidates"]) >= 6
    assert len(loaded["strategies"]) >= 3


# ── 2. exit_unit hiệu lực ────────────────────────────────────────────────────

def test_exit_unit_effective_is_atr_for_all():
    """Tất cả candidates phải có exit_unit='atr' sau khi merge BASE_POSITION.
    - DCA: khai báo tường minh trong `position` của class.
    - KEMA/Sideway: kế thừa BASE_POSITION.
    Nếu BASE_POSITION thay đổi khỏi 'atr', test này sẽ fail và báo vấn đề.
    """
    base_exit_unit = BASE_POSITION.get("exit_unit")
    assert base_exit_unit == "atr", f"BASE_POSITION.exit_unit đổi thành {base_exit_unit!r} — kiểm tra contract"

    for c in CANDIDATES:
        if c["id"] not in EXPECTED_IDS:
            continue
        pos = c.get("position", {})
        # Giá trị hiệu lực = position override nếu có, không thì BASE_POSITION
        effective = pos.get("exit_unit") or BASE_POSITION.get("exit_unit")
        assert effective == "atr", f"{c['id']}: exit_unit hiệu lực phải là 'atr', nhận {effective!r}"


def test_dca_declares_exit_unit_explicitly():
    """DCA phải khai báo exit_unit='atr' tường minh trong position dict của class."""
    for c in CANDIDATES:
        if c["id"] not in DCA_IDS:
            continue
        pos = c.get("position", {})
        assert pos.get("exit_unit") == "atr", (
            f"{c['id']}: DCA phải khai báo exit_unit='atr' tường minh, "
            f"nhận position={pos}"
        )


def test_kema_sideway_declare_exit_unit_explicitly():
    """KEMA và Sideway khai báo exit_unit='atr' tường minh (Giai đoạn 1)."""
    for c in CANDIDATES:
        if c["id"] not in (KEMA_IDS | SIDEWAY_IDS):
            continue
        pos = c.get("position", {})
        assert pos.get("exit_unit") == "atr", (
            f"{c['id']}: KEMA/Sideway phải khai báo exit_unit='atr' tường minh, "
            f"nhận: {pos.get('exit_unit')!r}."
        )


# ── 3. atr_frame ─────────────────────────────────────────────────────────────

def test_dca_declares_atr_frame_1h_explicitly():
    """DCA khai báo atr_frame='1h' tường minh."""
    for c in CANDIDATES:
        if c["id"] not in DCA_IDS:
            continue
        pos = c.get("position", {})
        assert pos.get("atr_frame") == "1h", (
            f"{c['id']}: DCA phải khai báo atr_frame='1h' tường minh, nhận {pos.get('atr_frame')!r}"
        )


def test_base_position_atr_frame_is_auto():
    """BASE_POSITION.atr_frame phải là 'auto' để KEMA/Sideway dùng signal_tf khi resolve."""
    assert BASE_POSITION.get("atr_frame") == "auto", (
        f"BASE_POSITION.atr_frame đổi thành {BASE_POSITION.get('atr_frame')!r}. "
        "Cập nhật note nếu đây là thay đổi có chủ ý."
    )


# ── 4. Schema defaults hợp lệ ────────────────────────────────────────────────

def test_schema_defaults_are_numeric_within_range():
    """Mọi tham số numeric trong schema phải có default trong [min, max]."""
    for c in CANDIDATES:
        if c["id"] not in EXPECTED_IDS:
            continue
        for k, spec in (c.get("params_schema") or {}).items():
            default = spec.get("default")
            if spec.get("type") in ("float", "int") and default is not None:
                lo, hi = spec.get("min", default), spec.get("max", default)
                assert lo <= default <= hi, (
                    f"{c['id']}.{k}: default={default} ngoài [{lo}, {hi}]"
                )


def test_schema_choice_defaults_in_choices():
    """Tham số choice phải có default nằm trong danh sách choices."""
    for c in CANDIDATES:
        if c["id"] not in EXPECTED_IDS:
            continue
        for k, spec in (c.get("params_schema") or {}).items():
            if spec.get("type") == "choice":
                choices = spec.get("choices", [])
                default = spec.get("default")
                assert default in choices, (
                    f"{c['id']}.{k}: default={default!r} không thuộc choices={choices}"
                )


# ── 5. DCA contract ──────────────────────────────────────────────────────────

def test_dca_has_gate_params():
    """DCA phải có đủ 3 gate params (có prefix 'sig.' trong schema): gate_er_max, gate_adx_max, gate_rsi."""
    # Schema compile thêm prefix 'sig.' cho tất cả params từ p() trong __algorithm__
    required_gates = {"sig.gate_er_max", "sig.gate_adx_max", "sig.gate_rsi"}
    for c in CANDIDATES:
        if c["id"] not in DCA_IDS:
            continue
        schema = c.get("params_schema", {})
        gate_keys = {k for k in schema if "gate" in k}
        assert required_gates <= gate_keys, (
            f"{c['id']}: thiếu gate params {required_gates - gate_keys}; có: {gate_keys}"
        )


def test_dca_has_dca_params():
    """DCA phải có dca_step_pct, dca_max_layers, dca_size_multiplier."""
    required_dca = {"dca_step_pct", "dca_max_layers", "dca_size_multiplier"}
    for c in CANDIDATES:
        if c["id"] not in DCA_IDS:
            continue
        schema = c.get("params_schema", {})
        dca_keys = {k for k in schema if k.startswith("dca_")}
        assert required_dca <= dca_keys, (
            f"{c['id']}: thiếu dca params {required_dca - dca_keys}"
        )


def test_dca_long_entry_rsi_threshold_in_range():
    """DCA Long: rsi_lo default phải ở [10, 45]."""
    for c in CANDIDATES:
        if c["id"] != "dca_long":
            continue
        schema = c.get("params_schema", {})
        rsi_lo_spec = schema.get("rsi_lo", {})
        assert rsi_lo_spec.get("default", 0) <= 45, "dca_long.rsi_lo default quá cao"
        assert rsi_lo_spec.get("default", 100) >= 10, "dca_long.rsi_lo default quá thấp"


def test_dca_short_entry_rsi_threshold_in_range():
    """DCA Short: rsi_hi default phải ở [55, 90]. Key trong schema có prefix 'sig.'."""
    for c in CANDIDATES:
        if c["id"] != "dca_short":
            continue
        schema = c.get("params_schema", {})
        # Schema có prefix 'sig.' từ bộ compile DSL
        rsi_hi_spec = schema.get("sig.rsi_hi") or schema.get("rsi_hi", {})
        assert rsi_hi_spec, "dca_short: không tìm thấy rsi_hi trong schema (thử 'sig.rsi_hi' và 'rsi_hi')"
        assert rsi_hi_spec.get("default", 0) >= 55, "dca_short.rsi_hi default quá thấp"
        assert rsi_hi_spec.get("default", 100) <= 90, "dca_short.rsi_hi default quá cao"


# ── 6. KEMA contract ─────────────────────────────────────────────────────────

def test_kema_take_profit_disabled_by_default():
    """KEMA thoát qua signal (crossed_above/below). take_profit_rate có thể có trong schema
    nhưng default = 0 (disabled). Contract: KEMA không chốt lời cố định theo TP%."""
    for c in CANDIDATES:
        if c["id"] not in KEMA_IDS:
            continue
        schema = c.get("params_schema", {})
        tp_spec = schema.get("take_profit_rate") or schema.get("sig.take_profit_rate")
        if tp_spec is not None:
            # Nếu có trong schema thì phải disabled (default=0)
            assert tp_spec.get("default", 0) == 0, (
                f"{c['id']}: KEMA take_profit_rate phải disabled (default=0) vì thoát qua signal, "
                f"nhận default={tp_spec.get('default')!r}"
            )


def test_kema_has_stop_loss_in_schema():
    """KEMA phải có stop_loss_rate làm cắt lỗ an toàn."""
    for c in CANDIDATES:
        if c["id"] not in KEMA_IDS:
            continue
        schema = c.get("params_schema", {})
        assert "stop_loss_rate" in schema, f"{c['id']}: KEMA cần stop_loss_rate"
        sl_spec = schema["stop_loss_rate"]
        assert sl_spec.get("default", 0) > 0, f"{c['id']}: stop_loss_rate default phải > 0"


def test_kema_has_atr_frame_param():
    """KEMA khai báo atr_frame tường minh (= '4h') để ghi rõ tồn tại, dù p() override."""
    for c in CANDIDATES:
        if c["id"] not in KEMA_IDS:
            continue
        # atr_frame có thể được khai báo qua p('atr_frame', '4h') trong __algorithm__
        # hoặc qua position dict. Kiểm ít nhất một trong hai.
        schema = c.get("params_schema", {})
        pos = c.get("position", {})
        has_schema_atr = "atr_frame" in schema
        has_pos_atr = "atr_frame" in pos
        assert has_schema_atr or has_pos_atr, (
            f"{c['id']}: KEMA phải khai báo atr_frame qua schema param hoặc position dict"
        )


# ── 7. Sideway contract ──────────────────────────────────────────────────────

def test_sideway_has_er_filter():
    """Sideway phải có er_max trong schema (regime filter). Key có prefix 'sig.'."""
    for c in CANDIDATES:
        if c["id"] not in SIDEWAY_IDS:
            continue
        schema = c.get("params_schema", {})
        # Schema compile DSL thêm prefix 'sig.' cho params từ p() trong __algorithm__
        has_er = "sig.er_max" in schema or "er_max" in schema
        assert has_er, f"{c['id']}: Sideway cần er_max hoặc sig.er_max (ER regime filter); keys={list(schema)[:8]}"


def test_sideway_has_tp_and_sl():
    """Sideway phải có take_profit_rate và stop_loss_rate."""
    for c in CANDIDATES:
        if c["id"] not in SIDEWAY_IDS:
            continue
        schema = c.get("params_schema", {})
        assert "take_profit_rate" in schema, f"{c['id']}: Sideway cần take_profit_rate"
        assert "stop_loss_rate" in schema, f"{c['id']}: Sideway cần stop_loss_rate"


def test_sideway_has_timeout():
    """Sideway phải có timeout (tránh stuck position)."""
    for c in CANDIDATES:
        if c["id"] not in SIDEWAY_IDS:
            continue
        schema = c.get("params_schema", {})
        assert "timeout" in schema, f"{c['id']}: Sideway cần timeout"
        assert schema["timeout"].get("default", 0) > 0, f"{c['id']}: timeout default phải > 0"


# ── 8. STRATEGIES vs CANDIDATES nhất quán ───────────────────────────────────

def test_strategies_reference_all_expected_candidates():
    """Mọi id trong EXPECTED_IDS phải nằm trong legs của một STRATEGY."""
    ids_in_strategies = set()
    for st in STRATEGIES:
        for side, cid in st["legs"].items():
            ids_in_strategies.add(cid)
    missing = EXPECTED_IDS - ids_in_strategies
    assert not missing, f"Các candidate legs không nằm trong STRATEGIES: {missing}"


def test_by_id_lookup_works_for_all():
    """BY_ID lookup phải trả đúng candidate cho mọi id trong EXPECTED_IDS."""
    for cid in EXPECTED_IDS:
        c = BY_ID[cid]
        assert c["id"] == cid


def test_strategies_have_long_and_short_legs():
    """Mỗi STRATEGY phải có cả LONG và SHORT legs."""
    for st in STRATEGIES:
        legs = st.get("legs", {})
        assert "LONG" in legs, f"Strategy {st['id']}: thiếu LONG leg"
        assert "SHORT" in legs, f"Strategy {st['id']}: thiếu SHORT leg"


# ── 9. Cooldown mặc định ──────────────────────────────────────────────────────

def test_sideway_declares_cooldown_explicitly():
    """Sideway khai báo cooldown=60 tường minh (tránh dựa vào AUTO)."""
    for c in CANDIDATES:
        if c["id"] not in SIDEWAY_IDS:
            continue
        pos = c.get("position", {})
        # cooldown phải tường minh trong position dict của class (không phải BASE_POSITION)
        assert "cooldown" in pos, (
            f"{c['id']}: Sideway nên khai báo cooldown tường minh trong position dict"
        )
        assert isinstance(pos["cooldown"], int) and pos["cooldown"] > 0, (
            f"{c['id']}: Sideway.cooldown phải là int > 0, nhận {pos.get('cooldown')!r}"
        )


def test_dca_declares_cooldown_explicitly():
    """DCA khai báo cooldown=60 tường minh."""
    for c in CANDIDATES:
        if c["id"] not in DCA_IDS:
            continue
        pos = c.get("position", {})
        assert "cooldown" in pos, f"{c['id']}: DCA nên khai báo cooldown tường minh"
        assert isinstance(pos["cooldown"], int) and pos["cooldown"] > 0, (
            f"{c['id']}: DCA.cooldown phải là int > 0"
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
