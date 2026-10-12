"""GET /api/studio/strategies/dsl: tham chiếu DSL dựng từ pydsl/spec.
Kiểm tra bắt buộc từ điển lý thuyết (B1): 100% feature và operator phải có đủ các trường:
label_vi, formula, meaning_vi, read_vi, warmup, category.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import alpha
from backend.alpha.dsl import indicator as feat_mod, indicator as ops_mod


def test_dsl_reference():
    app = FastAPI()
    app.include_router(alpha.strategies_router)
    r = TestClient(app).get("/api/studio/strategies/dsl")
    assert r.status_code == 200
    j = r.json()
    assert [d["name"] for d in j["data"]] == ["pv_open", "pv_high", "pv_low", "pv_close", "pv_volume"]

    feats = {f["name"]: f for f in j["features"]}
    assert len(feats) == len(feat_mod.FEATURES)
    assert feats["sma"]["signature"].startswith("self.feat.sma(real")
    assert feats["rsi"]["doc"]

    ops = {o["name"]: o for o in j["operators"]}
    assert len(ops) == len(ops_mod.OPS)
    assert ops["crossed_above"]["returns"] == "bool"

    # B1: Mỗi feature và mỗi operator phải có đầy đủ 6 trường từ điển lý thuyết
    required_fields = ("label_vi", "formula", "meaning_vi", "read_vi", "category")
    for name, item in feats.items():
        for field in required_fields:
            val = item.get(field)
            assert isinstance(val, str) and val.strip(), f"Feature {name!r} thiếu trường {field!r}: {val!r}"
        assert item.get("warmup") is not None, f"Feature {name!r} thiếu warmup"

    for name, item in ops.items():
        for field in required_fields:
            val = item.get(field)
            assert isinstance(val, str) and val.strip(), f"Operator {name!r} thiếu trường {field!r}: {val!r}"
        assert item.get("warmup") is not None, f"Operator {name!r} thiếu warmup"
