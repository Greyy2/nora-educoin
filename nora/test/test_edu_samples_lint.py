"""Lint nghiêm ngặt 50 mẫu giáo dục chạy TRONG tiến trình pytest (không subprocess) + kiểm tra chính bộ lint bắt được các khẳng định sai."""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
import lint_edu_samples as L  # noqa: E402
from backend.alpha.dsl.indicator import FEATURE_SPECS_DATA, OP_SPECS_DATA  # noqa: E402

FEATS, OPS = set(FEATURE_SPECS_DATA), set(OP_SPECS_DATA)


@pytest.fixture(scope="module")
def samples():
    return {s["key"]: s for s in L.load_samples()}


def test_all_samples_pass_strict_lint():
    errors, n = L.lint_all(verbose=False)
    assert n == 50
    assert not errors, "\n".join(errors)


def _errs(sample):
    return "\n".join(L.lint_sample(sample, FEATS, OPS))


def _with(sample, **kw):
    s = copy.deepcopy(sample)
    s.update(kw)
    return s


def test_lint_flags_false_claims(samples):
    base = samples["trend_dual_ema"]   # EMA 20/50, chỉ long, không khai báo position
    assert not _errs(base)
    assert "RISK" in _errs(_with(base, summary=base["summary"] + " Cắt lỗ 2×ATR."))             # SL chưa khai báo
    assert "RISK" in _errs(_with(base, summary=base["summary"] + " Có trailing stop."))
    assert "NUMBA" in _errs(_with(base, summary=base["summary"] + " Tính bằng Numba."))
    assert "SHORT" in _errs(_with(base, summary=base["summary"] + " Bán khống khi cắt xuống."))
    assert "INDIC" in _errs(_with(base, summary=base["summary"] + " Lọc bằng RSI."))             # RSI không dùng
    assert "NUMBER" in _errs(_with(base, summary="Mua khi EMA 21 cắt lên EMA 50."))               # sai chu kỳ
    assert "NUMBER" in _errs(_with(base, summary="Mua khi EMA 20 cắt lên EMA 55."))
    assert "BOILER" in _errs(_with(base, code=base["code"].replace('"""\n', '"""\n    Trading Rules:\n', 1)))
    assert "SCHEMA" in _errs(_with(base, position={"nope": 2.0}))                                 # khoá position không hợp lệ
    assert "SCHEMA" in _errs(_with(base, category="Khác"))
    assert "EXEC" in _errs(_with(base, summary=base["summary"] + " Dùng đòn bẩy."))


def test_lint_threshold_and_direction(samples):
    base = samples["trend_adx_directional"]    # ADX > 25 vào, ADX < 20 thoát
    assert not _errs(base)
    assert "NUMBER" in _errs(_with(base, summary="Mua khi ADX > 30."))
    assert "NUMBER" in _errs(_with(base, summary="Mua khi ADX < 25."))                           # sai hướng


def test_lint_risk_params_must_match(samples):
    base = samples["risk_atr_fixed_multiple_stop"]   # tham số vị thế khai báo trong code: stop_loss_rate = 2.0
    assert "    stop_loss_rate = 2.0" in base["code"] and not _errs(base)
    assert "RISKNUM" in _errs(_with(base, summary="Mua khi giá đóng cửa cắt lên SMA 20; cắt lỗ 5×ATR."))
    assert "RISK" in _errs(_with(base, summary=base["summary"] + " Chốt lời 4×ATR."))            # take_profit_rate chưa khai báo
    no_sl = "\n".join(ln for ln in base["code"].split("\n") if not ln.startswith("    stop_loss_rate"))
    assert "RISK" in _errs(_with(base, code=no_sl))                                              # bỏ SL khỏi code nhưng văn bản vẫn nói


def test_samples_declare_every_parameter_explicitly():
    """Mọi mẫu: tham số chỉ báo/ngưỡng là hằng số tên rõ ở đầu class (self.<tên>), vị thế + rủi ro khai báo tường minh trong code (không `position` ngoài, không mặc định ngầm)."""
    import ast
    import re
    import backend.optimize  # noqa: F401  (đăng ký nguồn dữ liệu cho build_plan)
    from backend.alpha.compile import compile_code
    from backend.alpha.dsl.strategy import build_plan
    for s in L.load_samples():
        assert "position" not in s, s["key"]
        prog = compile_code(s["code"], register=False)
        assert {"stop_loss_rate", "risk_per_trade_pct"} <= set(prog.position_overrides), s["key"]   # atr_frame / cooldown có thể bỏ = "auto" (theo khung tín hiệu)
        assert not any("mặc định" in w for w in build_plan(prog, ["BTC@perp"]).warnings), s["key"]   # build_plan không phải gán mặc định ngầm
        fn = next(n for n in ast.walk(ast.parse(s["code"])) if isinstance(n, ast.FunctionDef))
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                assert not re.search(r"\d", n.id), f"{s['key']}: tên biến {n.id} chứa số (đổi tham số sẽ làm tên sai)"
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "feat":
                for a in n.args:       # đối số số của chỉ báo: chỉ cho phép 0 (loại MA của stoch)
                    assert not (isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value != 0), f"{s['key']}: số trần trong self.feat.{n.func.attr}"
