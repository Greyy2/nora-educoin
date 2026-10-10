"""P10 — Strategy Contract: check_contract (RUN/ADAPT/REJECT), bộ chuyển đổi, catalog, gợi ý/hover, sửa tại chỗ, phiên bản alpha người dùng."""
import json
import os
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.alpha import compile as dsl, contract
from backend.alpha.compile import compile_code, compile_program, compile_strategy_module, load_system_strategies, strategies_dir
from backend.core.indicator import FEATURES, OPS
from backend.optimize.book import build as sb
from backend.optimize.book import registry as user_alphas
from backend.routes import alpha
from backend.routes import alpha

NORA = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYS_DIR = os.path.join(NORA, "data", "alpha", "strategies")
SAMPLES = os.path.join(NORA, "data", "alpha", "education", "samples.json")

NATIVE = '''
class CustomStrategy(SimpleAlgorithm):
    timeframe = "4h"
    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, 20)
        self.set_positions(close < ema, position=0.0)
        self.set_positions(self.op.crossed_above(close, ema), position=1.0)
'''
LIFECYCLE = '''
class CustomStrategy(SimpleAlgorithm):
    timeframe = "4h"
    def on_start(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, 20)
    def on_bar(self):
        self.set_positions(close < ema, position=0.0)
        self.set_positions(self.op.crossed_above(close, ema), position=1.0)
    def on_stop(self):
        pass
'''
FUNCTION = '''
timeframe = "4h"
FAST = 20
def strategy(data):
    close = data.close
    ema = feat.ema(close, FAST)
    return {"entry": op.crossed_above(close, ema), "exit": close < ema}
'''
NATIVE_INLINE = '''
class CustomStrategy(SimpleAlgorithm):
    timeframe = "4h"
    def __algorithm__(self):
        ema = self.feat.ema(self.data.pv_close, 20)
        self.set_positions(self.data.pv_close < ema, position=0.0)
        self.set_positions(self.op.crossed_above(self.data.pv_close, ema), position=1.0)
'''
JSON_SPEC = {"timeframe": "4h", "params": {"fast": 20}, "indicators": {"ema": "feat.ema(close, fast)"},
             "entry": "op.crossed_above(close, ema)", "exit": "close < ema"}


# ─── RUN ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(n for n in os.listdir(SYS_DIR) if n.endswith(".py") and not n.startswith("_")))
def test_run_system_strategy_files(name):
    code = open(os.path.join(SYS_DIR, name), encoding="utf-8").read()
    res = contract.check_contract(code)
    assert (res["verdict"], res["style"], res["kind"]) == ("RUN", "strategy_module", "module")
    assert res["diagnostics"] == [] and res["normalized_code"] is None
    assert res["ir"] == compile_strategy_module(code)


def test_run_all_education_samples_identical_ir():
    samples = json.load(open(SAMPLES, encoding="utf-8"))
    assert len(samples) == 50
    for s in samples:
        res = contract.check_contract(s["code"])
        assert res["verdict"] == "RUN" and res["style"] == "simple_algorithm", s["key"]
        assert res["ir"].code_hash == compile_code(s["code"], register=False).code_hash, s["key"]


def test_lifecycle_is_native_and_hash_identical():
    a, b = contract.check_contract(LIFECYCLE), contract.check_contract(NATIVE)
    assert (a["verdict"], a["style"]) == ("RUN", "lifecycle") and b["verdict"] == "RUN"
    assert a["ir"].code_hash == b["ir"].code_hash == compile_program(NATIVE).code_hash == compile_program(LIFECYCLE).code_hash


@pytest.mark.parametrize("code,line,col,frag", [
    ("class S(SimpleAlgorithm):\n    def on_start(self):\n        pass\n", 1, 1, "on_bar"),
    ("class S(SimpleAlgorithm):\n    def on_start(self):\n        self.set_positions(1 > 0, position=1)\n    def on_bar(self):\n        pass\n", 3, 9, "on_start"),
    ("class S(SimpleAlgorithm):\n    def on_bar(self):\n        self.set_positions(self.data.pv_close > 1, position=1)\n    def on_stop(self):\n        x = 1\n", 4, 5, "on_stop"),
])
def test_lifecycle_contract_violations(code, line, col, frag):
    res = contract.check_contract(code)
    assert res["verdict"] == "REJECT" and res["style"] in ("lifecycle", "simple_algorithm")
    d = res["diagnostics"][-1]
    assert (d["line"], d["col"]) == (line, col) and frag in d["message_vi"] and d["code"] == "BAD_LIFECYCLE"


def test_module_lifecycle_and_side():
    src = open(os.path.join(SYS_DIR, "kema.py"), encoding="utf-8").read()
    assert contract.check_contract(src.replace('    id = "kema_long"', '    side = "LONG"\n    id = "kema_long"'))["verdict"] == "RUN"
    bad = contract.check_contract(src.replace('    id = "kema_long"', '    side = "SHORT"\n    id = "kema_long"'))
    assert bad["verdict"] == "REJECT" and "side" in bad["diagnostics"][-1]["message_vi"]


# ─── ADAPT ───────────────────────────────────────────────────────────────────

def test_adapt_function_style():
    res = contract.check_contract(FUNCTION)
    assert (res["verdict"], res["style"]) == ("ADAPT", "function")
    assert res["ir"].code_hash == compile_program(NATIVE).code_hash
    assert compile_program(res["normalized_code"]).code_hash == res["ir"].code_hash
    assert any(d["code"] == "ADAPTED_FUNCTION" for d in res["diagnostics"])
    assert compile_code(FUNCTION, register=False).code_hash == res["ir"].code_hash        # compile_code (đường chạy thật) nhận trực tiếp


def test_adapt_function_tuple_return_and_data_subscript():
    code = 'def strategy(data):\n    c = data["close"]\n    return c > 1, c < 1\n'
    res = contract.check_contract(code)
    assert res["verdict"] == "ADAPT" and res["ir"].levels == [0.0, 1.0]


@pytest.mark.parametrize("form", ["dict", "text"])
def test_adapt_json_spec(form):
    code = JSON_SPEC if form == "dict" else json.dumps(JSON_SPEC, indent=1)
    res = contract.check_contract(code)
    assert (res["verdict"], res["style"]) == ("ADAPT", "json_spec")
    assert res["ir"].code_hash == compile_program(NATIVE_INLINE).code_hash
    assert compile_program(res["normalized_code"]).code_hash == res["ir"].code_hash
    if form == "text":
        assert compile_code(code, register=False).code_hash == res["ir"].code_hash


def test_json_spec_tuple_indicator_and_errors_point_at_key():
    spec = {"indicators": {"up, mid, lo": "feat.bbands(close, 20)"}, "entry": "close > up", "exit": "close < mid"}
    assert contract.check_contract(spec)["verdict"] == "ADAPT"
    text = json.dumps({"timeframe": "4h", "indicators": {"ema": "feat.emaa(close, 20)"}, "entry": "close > ema"}, indent=1)
    res = contract.check_contract(text)
    d = res["diagnostics"][-1]
    assert res["verdict"] == "REJECT" and d["code"] == "UNKNOWN_FEATURE" and d["path"] == "indicators.ema" and "ema" in d["suggest"]
    assert text.split("\n")[d["line"] - 1].strip().startswith('"ema"')
    assert contract.check_contract({"entry": "close > 1", "bogus": 1})["diagnostics"][-1]["path"] == "bogus"
    assert contract.check_contract({"exit": "close > 1"})["verdict"] == "REJECT"


AI_CODE = '''```python
from nora import Strategy
class S(Strategy):
    timeframe = "4h"
    def __algorithm__(self):
        close = self.data.Close
        ema = self.feat.EMA(close, 20)
        self.set_positions((close < ema) and (close > 0), position=0.0)
        self.set_positions(not (close < ema), position=1.0)
        self.set_positions(0 < close < 5, position=1.0)
```'''


def test_adapt_ai_python_variants():
    res = contract.check_contract(AI_CODE)
    assert (res["verdict"], res["style"]) == ("ADAPT", "ai_python")
    codes = {d["code"] for d in res["diagnostics"]}
    assert {"NORMALIZED_FENCE", "NORMALIZED_IMPORT", "NORMALIZED_BASE", "NORMALIZED_NAME", "NORMALIZED_BOOL_OP", "NORMALIZED_CHAINED_COMPARE"} <= codes
    assert compile_program(res["normalized_code"]).code_hash == res["ir"].code_hash
    with pytest.raises(Exception):
        compile_code(AI_CODE.replace("```python", "").replace("```", ""), register=False)      # compile native vẫn nghiêm ngặt


# ─── REJECT chính xác ───────────────────────────────────────────────────────

BASE = "class S(SimpleAlgorithm):\n    def __algorithm__(self):\n        close = self.data.pv_close\n{line}\n        self.set_positions(close > e, position=1)\n"


def test_reject_unknown_feature_exact_position():
    res = contract.check_contract(BASE.format(line="        e = self.feat.emaa(close, 20)"))
    d = res["diagnostics"][-1]
    assert res["verdict"] == "REJECT" and res["ir"] is None
    assert (d["line"], d["col"], d["end_line"], d["end_col"]) == (4, 13, 4, 27)
    assert d["code"] == "UNKNOWN_FEATURE" and d["severity"] == "error" and "ema" in d["suggest"] and "Gần đúng" not in d["message_vi"]


def test_reject_out_of_range_and_python_apis():
    d = contract.check_contract(BASE.format(line="        e = self.feat.ema(close, 0)"))["diagnostics"][-1]
    assert (d["line"], d["col"], d["code"]) == (4, 34, "OUT_OF_RANGE")
    d = contract.check_contract(BASE.format(line="        e = close.rolling(20).mean()"))["diagnostics"][-1]
    assert d["line"] == 4 and d["code"] == "FORBIDDEN_SYNTAX" and "self.feat.rolling_mean" in d["suggest"]
    d = contract.check_contract(BASE.format(line="        e = np.mean(close)"))["diagnostics"][-1]
    assert d["line"] == 4 and d["code"] == "UNKNOWN_NAME"


def test_reject_structure_syntax_and_unknown():
    d = contract.check_contract("import numpy as np\nclass S(SimpleAlgorithm):\n    pass\n")["diagnostics"][-1]
    assert (d["line"], d["col"]) == (1, 1) and d["code"] == "FORBIDDEN_SYNTAX"
    d = contract.check_contract("class S(SimpleAlgorithm):\n    def initialize(self):\n        pass\n")["diagnostics"][-1]
    assert (d["line"], d["col"], d["code"]) == (2, 5, "BAD_LIFECYCLE") and "on_bar" in d["suggest"] or "on_bar" in d["message_vi"]
    r = contract.check_contract("def foo(:\n")
    assert r["verdict"] == "REJECT" and r["diagnostics"][0]["code"] == "SYNTAX" and r["diagnostics"][0]["line"] == 1
    assert contract.check_contract("x = 1\n")["verdict"] == "REJECT"
    assert contract.check_contract("x" * (contract.MAX_CODE_CHARS + 1))["diagnostics"][0]["code"] == "TOO_LARGE"


def test_reject_if_with_diag_has_position():
    code = "class S(SimpleAlgorithm):\n    def __algorithm__(self):\n        close = self.data.pv_close\n        if close > 1:\n            pass\n"
    d = contract.check_contract(code)["diagnostics"][-1]
    assert (d["line"], d["col"]) == (4, 9) and d["end_line"] >= 5


# ─── Registry ────────────────────────────────────────────────────────────────

def test_adapter_registry_is_extensible():
    n = len(dsl.REGISTRY)
    try:
        dsl.register(dsl.Adapter("toy", False, lambda s: s.tree is not None and s.code.startswith("#toy"), lambda s: dsl._convert_function(s)), first=True)
        assert contract.check_contract("#toy\n" + FUNCTION)["style"] == "toy"
    finally:
        del dsl.REGISTRY[0]
    assert len(dsl.REGISTRY) == n


# ─── Catalog ─────────────────────────────────────────────────────────────────

def test_catalog_covers_every_feature_and_op_exactly_once():
    cat = contract.catalog()
    names_f = [r["name"] for r in cat["features"]]
    names_o = [r["name"] for r in cat["ops"]]
    assert sorted(names_f) == sorted(set(FEATURES) | {"er"}) and len(names_f) == len(set(names_f))       # er = cột kernel chỉ có ở loại module
    assert sorted(names_o) == sorted(OPS) and len(names_o) == len(set(names_o))
    assert len(cat["version"]) == 12 and cat["version"] == contract.catalog()["version"]
    from backend.alpha.compile import _KERNEL_FEATURES
    assert {r["name"] for r in cat["features"] if "module" in r["modes"]} == set(_KERNEL_FEATURES) | {"bbands"}
    assert {r["name"] for r in cat["ops"] if "module" in r["modes"]} == {"crossed_above", "crossed_below"}
    ema = next(r for r in cat["features"] if r["name"] == "ema")
    assert ema["args"][1] == {"name": "timeperiod", "type": "int", "required": False, "default": 30, "lo": 1, "hi": 5000}
    assert {m["name"] for m in cat["methods"]} == set(contract.METHOD_OPS)
    assert [c["name"] for c in cat["data"]] == ["pv_open", "pv_high", "pv_low", "pv_close", "pv_volume"]


def test_catalog_examples_compile():
    """Mọi ví dụ trong catalog biên dịch được (trừ kiểu cần bối cảnh): validation và code assist cùng một nguồn."""
    cat = contract.catalog()
    bad = []
    for row in cat["features"] + cat["ops"]:
        pre = "        close = self.data.pv_close\n        open = self.data.pv_open\n        high = self.data.pv_high\n        low = self.data.pv_low\n        volume = self.data.pv_volume\n"
        lhs = ", ".join(f"v{i}" for i in range(row["outputs"])) if row["outputs"] > 1 else "v0"
        use = "v0 > 0" if row["returns"] != "bool" else "v0"
        code = f"class S(SimpleAlgorithm):\n    def __algorithm__(self):\n{pre}        {lhs} = {row['example']}\n        self.set_positions({use}, position=1)\n"
        if "alpha" not in row["modes"]:
            continue
        res = contract.check_contract(code)
        if res["verdict"] != "RUN":
            bad.append((row["name"], res["diagnostics"][-1]["message_vi"]))
    assert not bad, bad


# ─── complete / hover ───────────────────────────────────────────────────────

CODE_ASSIST = ('class S(SimpleAlgorithm):\n    timeframe = "4h"\n    def on_start(self):\n        close = self.data.pv_close\n'
               '        ema = self.feat.e\n        x = self.feat.ema(close, 20)\n        y = close.sh\n')


def _labels(r):
    return [i["label"] for i in r["items"]]


def test_complete_contexts():
    r = contract.complete(CODE_ASSIST, 5, 26)
    assert "ema" in _labels(r) and "rsi" not in _labels(r) and all(i["kind"] == "feature" for i in r["items"])
    assert r["range"] == {"line": 5, "col": 25, "end_line": 5, "end_col": 26}
    ema = next(i for i in r["items"] if i["label"] == "ema")
    assert ema["insert"].startswith("ema(") and "timeperiod" in ema["doc_md"]
    assert _labels(contract.complete(CODE_ASSIST, 7, 21)) == ["shift"]
    assert "crossed_above" in _labels(contract.complete("class S(SimpleAlgorithm):\n  def on_bar(self):\n    self.set_positions(self.op.", 3, 32))
    assert set(_labels(contract.complete("x = self.data.", 1, 15))) == {"pv_open", "pv_high", "pv_low", "pv_close", "pv_volume"}
    frames = contract.complete('class S(SimpleAlgorithm):\n    timeframe = "', 2, 18)
    assert _labels(frames) == ["1m", "5m", "15m", "1h", "4h", "24h"]
    cls = contract.complete("class S(SimpleAlgorithm):\n    ", 2, 5)
    assert {"on_start", "on_bar", "on_stop", "timeframe"} <= set(_labels(cls))
    pk = contract.complete("STRATEGY = {}\nclass S(SimpleAlgorithm):\n    def __algorithm__(self):\n        a = p('x', 5, lo=1, ", 4, 28)
    assert "hi=" in _labels(pk) and "lo=" not in _labels(pk) and all(i["kind"] == "param" for i in pk["items"])
    kw = contract.complete("class S(SimpleAlgorithm):\n  def on_start(self):\n    e = self.feat.ema(self.data.pv_close, ", 3, 43)
    assert "timeperiod=" in _labels(kw)


def test_hover():
    h = contract.hover(CODE_ASSIST, 6, 24)
    assert h["md"] and "self.feat.ema(real, timeperiod=30)" in h["md"] and "[1, 5000]" in h["md"]
    h = contract.hover(CODE_ASSIST, 6, 11)
    assert h["md"] is None or "biến" in h["md"]
    code = "STRATEGY = {}\nclass S(SimpleAlgorithm):\n    def __algorithm__(self):\n        n = p('ema_n', 30, lo=5, hi=200, step=1, label='x', help='y')\n"
    h = contract.hover(code, 4, 14)
    assert "ema_n" in h["md"] and "[5, 200]" in h["md"] and "30" in h["md"]
    h = contract.hover("x = close.shift(1)\n", 1, 13)
    assert "shift" in h["md"]
    assert contract.hover("x = 1\n", 1, 1)["md"] is None


# ─── HTTP + sửa tại chỗ ──────────────────────────────────────────────────────

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(alpha.strategies_router)
    app.include_router(alpha.alphas_router)
    return TestClient(app)


def test_assist_endpoints(client):
    cat = client.get("/api/studio/strategies/assist/catalog").json()
    assert cat["version"] and len(cat["features"]) == len(FEATURES) + 1 and "_idx" not in cat
    r = client.post("/api/studio/strategies/assist/check", json={"code": FUNCTION}).json()
    assert r["verdict"] == "ADAPT" and "ir" not in r and r["meta"]["timeframe"] == "4h" and r["normalized_code"]
    r = client.post("/api/studio/strategies/assist/check", json={"code": BASE.format(line="        e = self.feat.emaa(close, 20)")}).json()
    assert r["verdict"] == "REJECT" and r["diagnostics"][-1]["line"] == 4
    r = client.post("/api/studio/strategies/assist/complete", json={"code": CODE_ASSIST, "line": 5, "col": 26}).json()
    assert "ema" in _labels(r)
    r = client.post("/api/studio/strategies/assist/hover", json={"code": CODE_ASSIST, "line": 6, "col": 24}).json()
    assert r["md"]


@pytest.fixture()
def temp_strategies(tmp_path, monkeypatch):
    d = tmp_path / "strategies"
    shutil.copytree(SYS_DIR, d, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv("NORA_STRATEGIES_DIR", str(d))
    sb.reload_system_strategies()
    yield d
    monkeypatch.undo()
    sb.reload_system_strategies()


def test_edit_in_place_round_trip(client, temp_strategies):
    base = "/api/studio/strategies/source/kema"
    got = client.get(base).json()
    assert got["file"] == "kema.py" and got["legs"] == ["kema_long", "kema_short"] and len(got["sha256"]) == 64
    assert client.get("/api/studio/strategies/source/kema_short").json()["id"] == "kema"
    assert client.get("/api/studio/strategies/source/nope").status_code == 404
    old_desc = sb.BY_ID["kema_long"]["description"]
    new_code = got["code"].replace(old_desc, old_desc + " (đã sửa)")
    assert new_code != got["code"]
    r = client.put(base, json={"code": new_code, "sha256": got["sha256"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["legs"] == ["kema_long", "kema_short"] and body["sha256"] != got["sha256"] and body["reloaded"]
    assert os.path.isfile(body["backup"]) and open(body["backup"], encoding="utf-8").read() == got["code"]
    assert (temp_strategies / "kema.py").read_text(encoding="utf-8") == new_code
    # nạp lại: sổ và loader thấy mã mới
    assert sb.BY_ID["kema_long"]["description"].endswith("(đã sửa)")
    assert load_system_strategies()["candidates"][0]["description"].endswith("(đã sửa)") and strategies_dir() == str(temp_strategies)
    assert sb.SOURCES["kema_long"]["sha256"] == body["sha256"]
    assert client.get(base).json()["sha256"] == body["sha256"]
    # sha cũ -> 409
    r = client.put(base, json={"code": got["code"], "sha256": got["sha256"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHA_CONFLICT" and r.json()["detail"]["current_sha256"] == body["sha256"]


def test_edit_rejects_bad_code_and_wrong_kind(client, temp_strategies):
    got = client.get("/api/studio/strategies/source/dca").json()
    bad = got["code"].replace("self.feat.rsi(", "self.feat.rsii(", 1)
    r = client.put("/api/studio/strategies/source/dca", json={"code": bad, "sha256": got["sha256"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "CONTRACT_REJECTED"
    d = r.json()["detail"]["diagnostics"][-1]
    assert d["code"] == "UNKNOWN_FEATURE" and d["line"] > 1
    r = client.put("/api/studio/strategies/source/dca", json={"code": NATIVE, "sha256": got["sha256"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "WRONG_KIND"
    assert (temp_strategies / "dca.py").read_text(encoding="utf-8") == got["code"]       # file không đổi
    dup = got["code"].replace('"id": "dca",', '"id": "kema",', 1)
    r = client.put("/api/studio/strategies/source/dca", json={"code": dup, "sha256": got["sha256"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_ID"


def test_edit_backup_limit_and_rename(client, temp_strategies):
    got = client.get("/api/studio/strategies/source/sideway").json()
    legs = got["legs"]
    renamed = got["code"].replace(f'"{legs[0]}"', f'"{legs[0]}_v2"')
    assert renamed != got["code"]
    sha, code = got["sha256"], got["code"]
    for i in range(22):
        code = code.replace("Dạng đã biên dịch" if i == 0 else f"#{i - 1}#", f"#{i}#", 1) if i else code + "\n# v0\n"
        r = client.put("/api/studio/strategies/source/sideway", json={"code": code + f"\n# edit {i}\n", "sha256": sha})
        assert r.status_code == 200, r.text
        sha = r.json()["sha256"]
        code = code.split("\n# edit")[0]
    from backend.alpha import compile as dsl
    bdir = os.path.join(dsl.strategies_dir(), dsl.BACKUP_DIRNAME)
    assert dsl.strategies_dir() == str(temp_strategies)
    assert all(os.path.dirname(p) == str(temp_strategies) for p in dsl.strategy_files())      # .versions không lẫn vào loader
    assert len([n for n in os.listdir(bdir) if n.startswith("sideway.")]) == dsl.MAX_BACKUPS
    r = client.put("/api/studio/strategies/source/sideway", json={"code": renamed, "sha256": sha})
    assert r.status_code == 200 and f"{legs[0]}_v2" in r.json()["legs"]


# ─── Alpha người dùng: phiên bản mới ────────────────────────────────────────

def _mock_job(code, job_id, equity_end):
    prog = compile_code(code, register=False)
    return {
        "program_hash": prog.code_hash,
        "config": {"symbols": ["BTC"], "start": "2020-01-02", "end": "2024-12-31", "train_ratio": 0.7, "initial_capital": 100000.0, "timeframe": "24h",
                   "program": {"name": prog.name, "legs": ["LONG"]}},
        "metrics": {"simulate": {"sharpe": 1.5, "ret_pct": equity_end / 1000, "mdd_pct": 25.0, "trades": 35}, "test": {"sharpe": 1.2, "ret_pct": 40.0, "mdd_pct": 18.0}},
        "series": {"times": [1, 2, 3], "equity": [100000.0, 150000.0, equity_end]}, "trades": [{"symbol": "BTC", "pnl": 100.0}] * 35,
        "insights": [], "diagnostics": {}, "final_equity": equity_end,
    }


def test_user_alpha_new_version(tmp_path, monkeypatch, client):
    code1 = FUNCTION.replace("FAST = 20", "FAST = 20")
    code2 = FUNCTION.replace("FAST = 20", "FAST = 30")
    results = {"j1": _mock_job(code1, "j1", 220000.0), "j2": _mock_job(code2, "j2", 260000.0)}
    from backend.optimize.process import process as batch
    monkeypatch.setattr(batch, "status", lambda jid: {"status": "done", "result": results[jid]} if jid in results else None)
    base = str(tmp_path / "alphas")
    rec1, act1 = user_alphas.save_user_alpha("j1", code1, "Alpha A", base_dir=base)
    assert act1 == "created" and rec1["version"] == 1
    aid = rec1["id"]
    with pytest.raises(LookupError):
        user_alphas.save_user_alpha("j2", code2, "Alpha A", base_dir=base, alpha_id="doesnotexist")
    rec2, act2 = user_alphas.save_user_alpha("j2", code2, "Alpha A v2", base_dir=base, alpha_id=aid)
    assert act2 == "versioned" and rec2["id"] == aid and rec2["version"] == 2 and rec2["code"] == code2
    assert rec2["result"]["final_equity"] == 260000.0 and rec2["evidence"]["job_id"] == "j2" and rec2["created_at"] == rec1["created_at"]
    assert [v["version"] for v in rec2["versions"]] == [1, 2] and rec2["versions"][0]["job_id"] == "j1"
    assert os.path.isfile(os.path.join(base, "user", "_versions", f"{aid}.v1.json"))
    assert len(user_alphas.list_user_alphas(base_dir=base)) == 1          # _versions không lẫn vào danh sách
    old = user_alphas.get_user_alpha_version(aid, 1, base_dir=base)
    assert old["code"] == code1 and old["result"]["final_equity"] == 220000.0
    assert user_alphas.get_user_alpha_version(aid, 2, base_dir=base)["code"] == code2
    assert user_alphas.get_user_alpha_version(aid, 9, base_dir=base) is None
    assert [v["version"] for v in user_alphas.list_user_alpha_versions(aid, base_dir=base)] == [1, 2]
    # không có cờ result_stale / không sửa code tại chỗ
    assert "result_stale" not in rec2
    # API: GET code + versions + POST alpha_id
    monkeypatch.setenv("NORA_ALPHAS_DIR", base)
    monkeypatch.setattr("backend.crawl.store.alpha_user_dir", lambda: os.path.join(base, "user"))
    c = client.get(f"/api/studio/alphas/user/{aid}/code").json()
    assert c["code"] == code2 and c["version"] == 2 and len(c["sha256"]) == 64
    assert [v["version"] for v in client.get(f"/api/studio/alphas/user/{aid}/versions").json()] == [1, 2]
    assert client.get(f"/api/studio/alphas/user/{aid}/versions/1").json()["code"] == code1
    assert client.get(f"/api/studio/alphas/user/{aid}/versions/7").status_code == 404
    r = client.post("/api/studio/alphas/user", json={"job_id": "j1", "code": code1, "name": "Alpha A v3", "alpha_id": aid})
    assert r.status_code == 200 and r.json()["action"] == "versioned" and r.json()["version"] == 3
    r = client.post("/api/studio/alphas/user", json={"job_id": "j1", "code": code1, "name": "x", "alpha_id": "nonexistent"})
    assert r.status_code == 404


# ─── annotate: giải thích từng dòng (trang /education) ───

def _edu_samples():
    with open(SAMPLES, encoding="utf-8") as fh:
        return json.load(fh)


def _covered(code, rep):
    cov = {ln for r in rep["lines"] for ln in range(r["line"], r["end_line"] + 1)}
    return [i for i, t in enumerate(code.split("\n"), 1) if t.strip() and i not in cov]


_KINDS = {"class", "attr", "param", "data", "feature", "op", "rule_entry", "rule_exit", "position", "lifecycle", "comment", "other"}


def _check_annot(code):
    rep = dsl.annotate_report(code)
    assert rep["verdict"] in ("RUN", "ADAPT"), rep["diagnostics"]
    src = rep["normalized_code"] or code
    assert _covered(src, rep) == []
    for r in rep["lines"]:
        assert r["kind"] in _KINDS and r["text_vi"] and 1 <= r["line"] <= r["end_line"]
    assert dsl.annotate_report(code) == rep      # tất định
    return rep


def test_annotate_system_strategies():
    for name in sorted(os.listdir(SYS_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(SYS_DIR, name), encoding="utf-8") as fh:
                rep = _check_annot(fh.read())
            assert any(r["kind"] == "rule_entry" for r in rep["lines"])


def test_annotate_all_education_samples():
    samples = _edu_samples()
    assert len(samples) == 50
    for s in samples:
        rep = _check_annot(s["code"])
        kinds = {r["kind"] for r in rep["lines"]}
        assert {"feature", "rule_entry"} <= kinds or {"op", "rule_entry"} <= kinds, s["key"]


def test_annotate_lifecycle_and_rule_text():
    rep = _check_annot(LIFECYCLE)
    texts = [r["text_vi"] for r in rep["lines"] if r["kind"] == "rule_entry"]
    assert any("cắt lên" in t and "100% vị thế LONG" in t for t in texts)
    ema = next(r for r in rep["lines"] if r["kind"] == "feature")
    assert "EMA(giá đóng cửa, 20)" in ema["text_vi"] and "trung bình động" in ema["text_vi"].lower()


def test_annotate_endpoint():
    app = FastAPI()
    app.include_router(alpha.strategies_router)
    r = TestClient(app).post("/api/studio/strategies/annotate", json={"code": NATIVE})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "RUN" and body["style"] and body["lines"] and set(body["lines"][0]) == {"line", "end_line", "kind", "text_vi", "refs"}


# ─── annotate as_comments: giải thích thành chú thích `#` ngay trên từng dòng ───

def _all_codes():
    out = []
    for name in sorted(os.listdir(SYS_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(SYS_DIR, name), encoding="utf-8") as fh:
                out.append(fh.read())
    return out + [s["code"] for s in _edu_samples()]


def test_annotate_comments_identical_program_idempotent_strippable():
    codes = _all_codes()
    assert len(codes) == 53
    mark = dsl.ANNOTATION_MARK.rstrip()
    for code in codes:
        rep = dsl.annotate_report(code, as_comments=True)
        ann = rep["annotated_code"]
        assert ann
        assert dsl.strip_annotations(ann) == code
        assert dsl.annotate_report(ann, as_comments=True)["annotated_code"] == ann       # idempotent
        assert dsl.annotate_report(ann, as_comments=True)["lines"] == rep["lines"]
        assert all(len(ln.strip()) <= 70 + len(dsl.ANNOTATION_MARK) for ln in ann.split("\n") if ln.lstrip().startswith(mark))   # chú thích NGẮN: 1 dòng
        a, b = dsl.compile_report(code), dsl.compile_report(ann)
        if a["ok"]:                                   # mẫu education: class chiến lược
            assert b["ok"] and a["program_hash"] == b["program_hash"] and a["meta"] == b["meta"]
        else:                                         # chiến lược hệ thống: mô-đun nhiều chân
            assert json.dumps(compile_strategy_module(code), sort_keys=True, default=str) == json.dumps(compile_strategy_module(ann), sort_keys=True, default=str)


def test_annotate_comments_keeps_user_comments_and_indent():
    code = NATIVE.replace("        ema = ", "        # của tôi\n        ema = ")
    ann = dsl.annotate_report(code, as_comments=True)["annotated_code"]
    assert "        # của tôi\n" in ann
    lines = ann.split("\n")
    i = next(k for k, t in enumerate(lines) if t.strip().startswith("ema = "))
    j = lines.index("        # của tôi")
    assert j < i and all(t.startswith("        " + dsl.ANNOTATION_MARK) for t in lines[j + 1:i])
    assert dsl.strip_annotations(ann) == code


def test_annotate_comments_endpoint():
    app = FastAPI()
    app.include_router(alpha.strategies_router)
    c = TestClient(app)
    body = c.post("/api/studio/strategies/annotate", json={"code": NATIVE, "as_comments": True}).json()
    assert body["annotated_code"].count(dsl.ANNOTATION_MARK) >= 4
    assert "annotated_code" not in c.post("/api/studio/strategies/annotate", json={"code": NATIVE}).json()
    assert c.post("/api/studio/strategies/annotate", json={"code": body["annotated_code"], "strip": True}).json() == {"stripped_code": NATIVE}


def test_annotate_comments_no_duplicate_of_human_comment():
    mark = dsl.ANNOTATION_MARK.rstrip()
    for code in _all_codes():
        ann = dsl.annotate_report(code, as_comments=True)["annotated_code"].split("\n")
        for i, ln in enumerate(ann):
            if ln.lstrip().startswith(mark):
                j = i - 1
                while j >= 0 and not ann[j].strip():
                    j -= 1
                assert j < 0 or not (ann[j].lstrip().startswith("#") and not ann[j].lstrip().startswith(mark)), (ann[j], ln)
