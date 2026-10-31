import json
from pathlib import Path

from backend.analys.alpha.code.compile import compile_code, is_nautilus_native
from backend.analys.alpha.code.route import classify


REPO_ROOT = Path(__file__).resolve().parents[3]
PROXIMA_PATH = REPO_ROOT / "nora" / "coin" / "data" / "alpha" / "user" / "alpha_proxima_research.json"


def test_proxima_is_classified_and_compiled_as_allowlisted_native_strategy():
    code = json.loads(PROXIMA_PATH.read_text(encoding="utf-8"))["code"]
    assert is_nautilus_native(code)
    assert classify(code)["engine"] == "native"
    program = compile_code(code, register=False)
    assert program.meta()["is_native"] is True
    assert program.name == "ProximaUniversalAlpha"


def test_proxima_source_is_not_silently_treated_as_dsl():
    code = json.loads(PROXIMA_PATH.read_text(encoding="utf-8"))["code"]
    assert classify(code)["engine"] != "dsl"
