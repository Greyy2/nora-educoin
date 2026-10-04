"""Chế độ Cơ bản / Nâng cao: cây tham số hoá, params_schema, preset, validate 422, custom_gates, API.

Không chạy job thật: Popen bị thay bằng bản giả ghi lại lệnh (như test_book_api).
"""
import json
import os
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.jobs import batch as batch_jobs
from job_modules import launched
from backend.api.routers import book as book_router
from backend.api.routers import strategies as strategies_router
from backend.core.params.builder import POSITION_KEYS
from backend.core.params import presets as pr
from backend.core.params import modes as rm
from backend.core.params.template import FRAMES, collect_placeholders, collect_string_placeholders, resolve_placeholders
from backend.core.strategy import book as sb
from backend.core.strategy.book import BASE_POSITION, BY_ID, CANDIDATES, materialize, schema_defaults
from legacy_candidates import LEGACY
from backend.core.strategy.library import calc, cond, cross_over, cross_under, f, p


# ─── Cây CŨ (literal, trước khi tham số hoá chu kỳ/khung) — bằng chứng bit-identical của mặc định ──────────
_UP_1H = (f("1h", "ema_50"), ">", f("1h", "ema_200"))
_DN_1H = (f("1h", "ema_50"), "<", f("1h", "ema_200"))
_KC_UP = {**f("4h", "ema_30"), "add": calc(f("4h", "atr_14"), "*", p("k_up", 2.0))}
_KC_DN = {**f("4h", "ema_30"), "subtract": calc(f("4h", "atr_14"), "*", p("k_dn", 2.0))}
# Cây mặc định (tham số = mặc định schema). Họ trend/breakout/momentum vào lệnh khi CẮT (sự kiện, như ta.crossover / KEMA của sova).
OLD_TREES = {
    "trend_long": cond(_UP_1H, (f("1h", "adx_14"), ">", p("adx_min", 20)), *cross_over(f("15m", "close"), f("15m", "dch_20"))),
    "trend_short": cond(_DN_1H, (f("1h", "adx_14"), ">", p("adx_min", 20)), *cross_under(f("15m", "close"), f("15m", "dcl_20"))),
    "breakout_4h_long": cond((f("4h", "ema_50"), ">", f("4h", "ema_200")), *cross_over(f("4h", "close"), f("4h", "dch_20"))),
    "breakout_4h_short": cond((f("4h", "ema_50"), "<", f("4h", "ema_200")), *cross_under(f("4h", "close"), f("4h", "dcl_20"))),
    "keltner_trend_long": cond(*cross_over(f("4h", "close"), _KC_UP)),
    "keltner_trend_short": cond(*cross_under(f("4h", "close"), _KC_DN)),
    "momentum_long": cond(*cross_over(f("1h", "roc_24"), p("roc_min", 3)), (f("15m", "close"), ">", f("15m", "ema_20"))),
    "reversion_long": cond((f("5m", "rsi_14"), "<", p("rsi_lo", 25)), (f("5m", "close"), "<", f("5m", "bbl_20_2")),
                           (f("1h", "er_20"), "<", p("er_max", 0.3))),
    "reversion_short": cond((f("5m", "rsi_14"), ">", p("rsi_hi", 75)), (f("5m", "close"), ">", f("5m", "bbu_20_2")),
                            (f("1h", "er_20"), "<", p("er_max", 0.3))),
}

OLD_TREES.update({"kema_long": OLD_TREES["keltner_trend_long"], "kema_short": OLD_TREES["keltner_trend_short"],
                  "sideway_long": OLD_TREES["reversion_long"], "sideway_short": OLD_TREES["reversion_short"],
                  "dca_long": cond((f("1h", "rsi_14"), "<", p("rsi_lo", 30)), (f("1h", "close"), "<", f("1h", "bbl_20_2")),
                                   (f("4h", "er_20"), "<", p("er_max", 0.35))),
                  "dca_short": cond((f("1h", "rsi_14"), ">", p("rsi_hi", 70)), (f("1h", "close"), ">", f("1h", "bbu_20_2")),
                                    (f("4h", "er_20"), "<", p("er_max", 0.35)))})
REAL_CATALOG_TESTS = ("test_real_catalog_", "test_default_resolution_equals_old_literal_tree", "test_default_position_and_signal_params_unchanged",
                      "test_schema_is_well_formed")


@pytest.fixture(autouse=True)
def _legacy_catalog(request, monkeypatch):
    """Phần lớn test cơ chế (preset, chế độ chạy, kiểm tham số) viết trên 9 chiến lược cũ: chạy chúng trên danh mục cũ; test danh mục thật thì không."""
    if not request.node.name.startswith(REAL_CATALOG_TESTS):
        monkeypatch.setattr(sb, "CANDIDATES", list(LEGACY))
        monkeypatch.setattr(sb, "EXTRA_CANDIDATES", [])


# ─── 1. Mẫu tham số hoá ──────────────────────────────────────────────────────
@pytest.mark.parametrize("cid", [c["id"] for c in CANDIDATES + LEGACY])
def test_default_resolution_equals_old_literal_tree(cid):
    c = BY_ID[cid]
    old = resolve_placeholders(OLD_TREES[cid], {})
    assert materialize(c, {})["tree"] == old                                       # không truyền gì: mặc định trong schema
    assert materialize(c, schema_defaults(c))["tree"] == old                       # truyền tường minh mọi mặc định
    # ngưỡng số vẫn đổi được và vẫn khớp cây cũ
    sig = {"sig.adx_min": 25, "sig.roc_min": 5, "sig.rsi_lo": 20, "sig.rsi_hi": 80, "sig.er_max": 0.2}
    assert materialize(c, sig)["tree"] == resolve_placeholders(OLD_TREES[cid], {k[4:]: v for k, v in sig.items()})
    assert json.dumps(materialize(c, {})["tree"]) == json.dumps(old)               # giống từng ký tự (kể cả 20.0 vs 20)


@pytest.mark.parametrize("cid", [c["id"] for c in CANDIDATES + LEGACY])
def test_default_position_and_signal_params_unchanged(cid):
    c = BY_ID[cid]
    st = materialize(c, {})
    assert st["position"] == {**BASE_POSITION, **c["position"]} and st["signal_params"] == {}   # không thêm khoá nào khi không truyền gì
    st2 = materialize(c, {"sig.adx_min": 25, "stop_loss_rate": 2}, risk_per_trade_pct=0.75)
    assert st2["signal_params"] == {"adx_min": 25} and st2["position"]["stop_loss_rate"] == 2 and st2["position"]["risk_per_trade_pct"] == 0.75


@pytest.mark.parametrize("cid", [c["id"] for c in CANDIDATES + LEGACY])
def test_schema_is_well_formed(cid):
    c = BY_ID[cid]
    schema = c["params_schema"]
    assert schema and set(c["space"]) <= set(schema)                                # mọi khoá của không gian tối ưu có trong schema
    groups = [v["group"] for v in schema.values()]
    assert groups == sorted(groups, key={"signal": 0, "dca": 1, "exit": 2, "risk": 3}.get)   # thứ tự: tín hiệu, dồn lệnh, thoát lệnh, rủi ro
    mid = {k: v[len(v) // 2] for k, v in c["space"].items()}
    for key, spec in schema.items():
        assert {"group", "type", "default", "label_vi", "unit", "help_vi"} <= set(spec) and spec["type"] in ("int", "float", "choice")
        if spec["group"] == "signal":
            assert key.startswith("sig.")
        else:
            assert key in POSITION_KEYS and spec["group"] in ("dca", "exit", "risk")
        if spec["type"] == "choice":
            assert spec["default"] in spec["choices"] and set(spec["choices"]) <= set(FRAMES)
        else:
            assert {"min", "max", "step"} <= set(spec) and spec["min"] <= spec["default"] <= spec["max"]
        if key in mid and not key.startswith("sig."):
            assert spec["default"] == mid[key], key                                 # mặc định thoát lệnh = mức giữa của space
        _, err = rm.check_value(key, spec, spec["default"])
        assert err is None
    # mọi {tên} và node {"param"} trong cây vào + cây thoát + điều kiện DCA đều có tham số signal tương ứng, mặc định node khớp schema
    trees = [c["tree"], c.get("stop") or [], c.get("dca_gate") or []]
    names = set().union(*(collect_string_placeholders(t) | set(collect_placeholders(t)) for t in trees))
    assert {"sig." + n for n in names} == {k for k, v in schema.items() if v["group"] == "signal"}
    for n, d in {k: v for t in trees for k, v in collect_placeholders(t).items()}.items():
        assert schema["sig." + n]["default"] == d
    assert set(c["space"]) | {k for k, v in schema.items() if v["group"] == "signal"} >= {k for k in c["space"] if k.startswith("sig.")}


def test_advanced_params_change_the_tree():
    c = BY_ID["trend_long"]
    tree = materialize(c, {"sig.trend_tf": "4h", "sig.ema_fast": 20, "sig.ema_slow": 100, "sig.adx_n": 20, "sig.entry_tf": "5m", "sig.dch_n": 55})["tree"]
    flat = json.dumps(tree)
    for frag in ('"4h"', '"ema_20"', '"ema_100"', '"adx_20"', '"5m"', '"dch_55"'):
        assert frag in flat
    assert "ema_50" not in flat and '"1h"' not in flat
    bb = materialize(BY_ID["reversion_long"], {"sig.bb_n": 30, "sig.bb_k": 2.5})["tree"]
    assert "bbl_30_2.5" in json.dumps(bb)


def test_numeric_minutes_accepted_for_frames():
    tree = [[[{"frame": "{tf}", "column": "close", "index": 0}, ">", 1]]]
    assert resolve_placeholders(tree, {"tf": 240})[0][0][0]["frame"] == "4h"
    assert resolve_placeholders(tree, {}, {"tf": "15m"})[0][0][0]["frame"] == "15m"
    assert resolve_placeholders(tree, {"tf": "1h"}, {"tf": "15m"})[0][0][0]["frame"] == "1h"       # giá trị ưu tiên hơn mặc định


@pytest.mark.parametrize("values,frag", [
    ({"trend_tf": "2h"}, "Khung thời gian"),                 # khung không thuộc tập hợp lệ
    ({"trend_tf": 7}, "không hợp lệ"),                       # số phút lạ
    ({"trend_tf": True}, "phải là số hoặc khung"),
    ({"ema_fast": 1}, "2..500"),                             # chu kỳ < 2
    ({"ema_fast": 501}, "2..500"),
    ({"ema_fast": 20.5}, "không hợp lệ"),                    # chu kỳ không nguyên
    ({"ema_fast": float("nan")}, "hữu hạn"),
    ({"ema_fast": "abc"}, "không hợp lệ"),                   # cột ema_abc không phải kernel
])
def test_placeholder_validation_errors(values, frag):
    tree = [[[{"frame": "{trend_tf}", "column": "ema_{ema_fast}", "index": 0}, ">", 1]]]
    base = {"trend_tf": "1h", "ema_fast": 50}
    with pytest.raises(ValueError, match=frag):
        resolve_placeholders(tree, {**base, **values})


def test_placeholder_missing_and_bad_syntax_and_unknown_kernel():
    with pytest.raises(ValueError, match="Thiếu giá trị"):
        resolve_placeholders({"frame": "1h", "column": "ema_{x}"}, {})
    with pytest.raises(ValueError, match="Cột chỉ báo"):
        resolve_placeholders({"frame": "1h", "column": "{k}_20"}, {"k": "zzz"})
    with pytest.raises(ValueError, match="cú pháp"):
        resolve_placeholders({"frame": "1h", "column": "ema_{a}}"}, {"a": 20})
    # cột OHLCV qua placeholder hợp lệ; chuỗi thường không đụng tới
    assert resolve_placeholders({"frame": "1h", "column": "{c}"}, {"c": "close"}) == {"frame": "1h", "column": "close"}
    assert resolve_placeholders({"frame": "1h", "column": "ema_50"}, {}) == {"frame": "1h", "column": "ema_50"}
    # bbwp có tham số m; chu kỳ m cũng bị chặn 2..500
    with pytest.raises(ValueError, match="2..500"):
        resolve_placeholders({"frame": "1h", "column": "bbwp_20_2_{m}"}, {"m": 900})


# ─── 2. validate_params ──────────────────────────────────────────────────────
def _preset_params(cid):
    return schema_defaults(BY_ID[cid])


def test_validate_params_messages_are_per_field_and_vietnamese():
    c = BY_ID["trend_long"]
    base = _preset_params("trend_long")
    full, errs = rm.validate_params(c, {"sig.ema_fast": 20, "sig.trend_tf": "4h"}, base, "p")
    assert not errs and full["sig.ema_fast"] == 20 and full["sig.trend_tf"] == "4h" and full["sig.ema_slow"] == 200   # thiếu -> từ base
    bad = {"sig.ema_fast": 3.5, "sig.trend_tf": "2h", "stop_loss_rate": 99, "nope": 1, "ema_slow": 100, "leverage": 11, "timeout": "x"}
    _, errs = rm.validate_params(c, bad, base, "p")
    fields = dict(errs)
    assert set(fields) == {"p.sig.ema_fast", "p.sig.trend_tf", "p.stop_loss_rate", "p.nope", "p.ema_slow", "p.leverage", "p.timeout"}
    assert "số nguyên" in fields["p.sig.ema_fast"] and "một trong" in fields["p.sig.trend_tf"]
    assert "khoảng" in fields["p.stop_loss_rate"] and "'sig.ema_slow'" in fields["p.ema_slow"] and "phải là số" in fields["p.timeout"]
    _, errs = rm.validate_params(c, {"sig.ema_fast": 100, "sig.ema_slow": 60}, base, "p")
    assert errs == [("p.sig.ema_fast", "trend_long: EMA nhanh (100) phải nhỏ hơn EMA chậm (60)")]
    _, errs = rm.validate_params(c, [1, 2], base, "p")
    assert errs and errs[0][0] == "p"


def test_job_params_minimal_and_keeps_space_keys():
    c = BY_ID["breakout_4h_long"]
    full = {**schema_defaults(c), "stop_loss_rate": 3.0, "sig.ema_fast": 20, "risk_per_trade_pct": 0.9}
    jp = rm.job_params(c, full)
    assert set(c["space"]) <= set(jp) and jp["stop_loss_rate"] == 3.0 and jp["sig.ema_fast"] == 20
    assert "risk_per_trade_pct" not in jp and "atr_period" not in jp and "sig.ema_slow" not in jp


def test_common_risk():
    a = {"risk_per_trade_pct": 0.5}
    b = {"risk_per_trade_pct": 1.0}
    assert rm.common_risk([("x", a), ("y", dict(a))]) == (0.5, [])
    assert rm.common_risk([("x", a), ("y", b)], 0.75) == (0.75, [])
    val, errs = rm.common_risk([("x", a), ("y", b)])
    assert val is None and errs[0][0] == "strategies[1].params.risk_per_trade_pct"


# ─── 3. Preset: thứ tự nguồn ─────────────────────────────────────────────────
def _row(params, score, ret=10.0):
    return {"params": params, "score": score, "dev1": {"ret_pct": ret, "mdd_pct": 5.0, "sharpe": 1.0, "trades": 99, "symbols_positive": 6}}


def _run(root, name, stage_a, report_cands=None):
    d = root / name
    d.mkdir(parents=True)
    (d / "stage_a.json").write_text(json.dumps(stage_a))     # json.dumps ghi -Infinity như build_strategy_book
    (d / "report.json").write_text(json.dumps({"windows": {}, "candidates": report_cands or {}}))
    return d


NEG = float("-inf")


def test_presets_priority_book_then_latest_stage_a_then_defaults(tmp_path):
    runs = tmp_path / "book"
    # run cũ: có trend_long tốt (điểm 2), reversion_long (điểm 1)
    _run(runs, "20260101_000000", {"trend_long": [_row({"sig.adx_min": 20, "stop_loss_rate": 1.5}, 2.0)],
                                   "reversion_long": [_row({"sig.rsi_lo": 30}, 1.0)]})
    # run mới: trend_long top-1 (điểm 5) trước top-2 (điểm 7: phải chọn theo ĐIỂM, không theo thứ tự); breakout_4h_long cũng có (nhưng sổ thắng)
    _run(runs, "20260102_000000", {"trend_long": [_row({"sig.adx_min": 25, "stop_loss_rate": 3.5}, 5.0), _row({"sig.adx_min": 30}, 7.0), _row({}, NEG)],
                                   "breakout_4h_long": [_row({"stop_loss_rate": 1.5}, 3.0)],
                                   "trend_short": [_row({"stop_loss_rate": 1.5}, NEG)],               # không qua cổng -> bỏ
                                   "momentum_long": [_row({"sig.roc_min": 5}, None)]},                # score null (stage_a_rows) -> bỏ
         {"trend_long": {"dev1_tried": 24, "accepted": False, "stability": "0/2",
                         "dev1_top": [{"params": {"sig.adx_min": 30}, "dev2_pass": False, "dev2_extreme": {"ret_pct": -3.0}}]}})
    book = {"generated_at": 1790856748686, "risk_per_trade_pct": 0.5, "strategies": [
        {"id": "breakout_4h_long", "params": {"stop_loss_rate": 3.0, "timeout": 10080, "trailing_activation_pct": 1.0, "trailing_stop": 3.0, "bogus": 1},
         "evidence": {"accepted": True, "stability": "2/3", "dev1_tried": 24, "dev1_top": [{"dev1": {"ret_pct": 19.5, "daily": [1]}}]}}]}
    doc = pr.build_presets(book=book, runs_dir=str(runs))
    P = doc["presets"]
    assert set(P) == set(BY_ID)
    # 1. sổ thắng stage A; khoá lạ bị bỏ; thiếu khoá thì mặc định schema
    b = P["breakout_4h_long"]
    assert b["source_kind"] == "book" and b["source"] == "book.json (sổ đã build 01/10)" and b["params"]["stop_loss_rate"] == 3.0
    assert "bogus" not in b["params"] and b["params"]["sig.ema_fast"] == 50 and b["evidence"]["dev1"] == {"ret_pct": 19.5}
    assert b["timeframe"] == "1m" and b["evidence"]["timeframe"] == "1m"
    # 2. run mới nhất có cấu hình qua cổng; chọn điểm cao nhất (7.0), kèm dev2
    t = P["trend_long"]
    assert "build 20260102_000000 stage A" in t["source"] and t["params"]["sig.adx_min"] == 30
    assert t["evidence"]["score"] == 7.0 and t["evidence"]["accepted"] is False and t["evidence"]["dev2_extreme"] == {"ret_pct": -3.0}
    assert t["timeframe"] == "1m" and t["evidence"]["timeframe"] == "1m"
    # run cũ chỉ dùng khi run mới không có cấu hình qua cổng
    assert "build 20260101_000000 stage A" in P["reversion_long"]["source"] and P["reversion_long"]["params"]["sig.rsi_lo"] == 30
    # 3. còn lại: mặc định schema, timeframe=None
    for cid in ("trend_short", "momentum_long", "reversion_short", "breakout_4h_short"):
        assert P[cid]["source"] == pr.SOURCE_DEFAULT and P[cid]["source_kind"] == "default" and P[cid]["evidence"] is None
        assert P[cid]["params"] == schema_defaults(BY_ID[cid])
        assert P[cid]["timeframe"] is None
    for cid, preset in P.items():                       # params luôn đầy đủ và hợp lệ theo schema
        assert set(preset["params"]) == set(BY_ID[cid]["params_schema"])
        _, errs = rm.validate_params(BY_ID[cid], preset["params"], preset["params"])
        assert not errs, (cid, errs)


def test_presets_new_verified_run_beats_old_book_unverified_does_not(tmp_path):
    book = {"generated_at": 1790856748686, "timeframe": "15m", "strategies": [
        {"id": "breakout_4h_long", "params": {"stop_loss_rate": 3.0}, "evidence": {}}]}
    # run mới hơn sổ nhưng top-K không qua dev2 -> sổ (đã qua dev2) vẫn thắng
    _run(tmp_path / "a", "20261003_120000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]})
    b = pr.build_presets(book=book, runs_dir=str(tmp_path / "a"))["presets"]["breakout_4h_long"]
    assert b["source_kind"] == "book" and b["timeframe"] == "15m"
    # run mới hơn sổ, có cấu hình qua dev2 -> stage A thắng
    _run(tmp_path / "b", "20261003_120000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]},
         {"breakout_4h_long": {"dev1_top": [{"params": {"stop_loss_rate": 2.0}, "dev2_pass": True}]}})
    b = pr.build_presets(book=book, runs_dir=str(tmp_path / "b"))["presets"]["breakout_4h_long"]
    assert b["source_kind"] == "stage_a" and "20261003_120000" in b["source"] and b["params"]["stop_loss_rate"] == 2.0
    assert b["evidence"]["dev2_verified"] is True and b["timeframe"] == "1m"
    # run cũ hơn sổ, dù qua dev2 -> sổ thắng (cùng mức kiểm chứng, sổ mới hơn)
    _run(tmp_path / "c", "20260101_000000", {"breakout_4h_long": [_row({"stop_loss_rate": 2.0}, 6.0)]},
         {"breakout_4h_long": {"dev1_top": [{"params": {"stop_loss_rate": 2.0}, "dev2_pass": True}]}})
    assert pr.build_presets(book=book, runs_dir=str(tmp_path / "c"))["presets"]["breakout_4h_long"]["source_kind"] == "book"


def test_presets_stage_a_picks_robust_plateau_on_dev1_only(tmp_path):
    # đỉnh nhọn adx=30 (điểm 9, hai lân cận trượt cổng) vs vùng phẳng adx=20..25 (điểm 4, 4) -> chọn vùng phẳng; dev2 KHÔNG ảnh hưởng lựa chọn
    rows = [_row({"sig.adx_min": 15}, NEG), _row({"sig.adx_min": 20}, 4.0), _row({"sig.adx_min": 25}, 4.0),
            _row({"sig.adx_min": 30}, 9.0), _row({"sig.adx_min": 35}, NEG)]
    rob = pr.robust_scores(rows)
    assert rob[1] == pytest.approx((0 + 4 + 4) / 3) and rob[2] == pytest.approx((4 + 4 + 9) / 3) and rob[3] == pytest.approx((4 + 9 + 0) / 3)
    _run(tmp_path, "20261003_000000", {"trend_long": rows},
         {"trend_long": {"dev1_top": [{"params": {"sig.adx_min": 30}, "dev2_pass": True}]}})       # đỉnh qua dev2 vẫn không được chọn
    t = pr.build_presets(book=None, runs_dir=str(tmp_path), use_book_file=False)["presets"]["trend_long"]
    assert t["params"]["sig.adx_min"] == 25 and t["evidence"]["score"] == 4.0
    assert t["evidence"]["robust_score"] == pytest.approx(17 / 3, abs=1e-4) and t["evidence"]["dev2_verified"] is None
    assert "bền vững dev1" in t["source"]


def test_presets_write_load_roundtrip_and_fallbacks(tmp_path):
    doc = pr.build_presets(book=None, runs_dir=str(tmp_path / "none"), use_book_file=False)
    path = tmp_path / "presets.json"
    pr.write_presets(doc, str(path))
    assert pr.load_presets(str(path)) == {k: {**v} for k, v in doc["presets"].items()}
    assert pr.load_presets(str(tmp_path / "missing.json"))["trend_long"]["source"] == pr.SOURCE_DEFAULT
    path.write_text("{hỏng")
    assert pr.load_presets(str(path))["trend_long"]["source_kind"] == "default"
    # file có khoá lạ / thiếu khoá -> chuẩn hoá theo schema hiện hành
    path.write_text(json.dumps({"presets": {"trend_long": {"params": {"stop_loss_rate": 3.0, "zzz": 1, "sig.trend_tf": "9h"}, "source": "x"}}}))
    got = pr.load_presets(str(path))["trend_long"]
    assert got["params"]["stop_loss_rate"] == 3.0 and "zzz" not in got["params"] and got["params"]["sig.trend_tf"] == "1h" and got["source"] == "x"


# ─── 4. API ─────────────────────────────────────────────────────────────────
class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        self.pid = 2 ** 22 + 12345
        self.returncode = None

    def wait(self):
        return 0


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(tmp_path / "alphas"))
    monkeypatch.setenv("NORA_BOOK_PATH", str(tmp_path / "book.json"))
    monkeypatch.setenv("NORA_PRESETS_PATH", str(tmp_path / "presets.json"))
    FakePopen.calls = []
    monkeypatch.setattr(batch_jobs.subprocess, "Popen", FakePopen)
    pr.write_presets({"presets": {
        "breakout_4h_long": {"params": {"stop_loss_rate": 3.0, "trailing_stop": 3.0, "trailing_activation_pct": 1.0, "timeout": 10080},
                             "timeframe": "15m",
                             "source": "book.json (sổ đã build 01/10)", "source_kind": "book", "evidence": {"stage": "book"}},
        "trend_long": {"params": {"sig.adx_min": 25, "stop_loss_rate": 3.5, "trailing_stop": 4.5, "trailing_activation_pct": 0.0, "timeout": 4320},
                       "timeframe": "15m",
                       "source": "build X stage A top-1 dev1", "source_kind": "stage_a", "evidence": {"stage": "dev1"}}}})
    app = FastAPI()
    app.include_router(book_router.router)
    app.include_router(strategies_router.router)
    return TestClient(app)


BT = {"start": "2025-03-01", "end": "2025-06-30", "symbols": ["BTC", "SOL"]}
URL = "/api/studio/book/backtest"


def _cmd_strategies():
    p = launched(FakePopen.calls[-1])[1]
    return p["strategies"], p


def _job(client, jid):
    r = client.get(f"/api/studio/book/jobs/{jid}")
    assert r.status_code == 200, r.text
    return r.json()


def test_real_catalog_three_strategies_with_legs(client):
    rows = client.get("/api/studio/strategies").json()
    assert [x["id"] for x in rows] == ["kema_long", "kema_short", "sideway_long", "sideway_short", "dca_long", "dca_short"]
    assert {x["strategy"] for x in rows} == {"kema", "sideway", "dca"} and all("sova" not in (x["description"] + x["family"]).lower() for x in rows)
    cat = client.get("/api/studio/strategies/catalog").json()
    assert [c["id"] for c in cat] == ["kema", "sideway", "dca"] and cat[0]["legs"] == {"LONG": "kema_long", "SHORT": "kema_short"} \
        and cat[2]["legs"] == {"LONG": "dca_long", "SHORT": "dca_short"}
    assert client.post(URL, json={**BT, "strategies": [{"id": "kema_long"}, {"id": "kema_short"}]}).status_code == 200
    assert client.post(URL, json={**BT, "strategies": [{"id": "trend_long"}]}).status_code == 200      # id cũ vẫn chạy được (sổ đã xuất bản)


def test_get_strategies_shape(client):
    r = client.get("/api/studio/strategies")
    assert r.status_code == 200
    rows = r.json()
    assert [x["id"] for x in rows] == [c["id"] for c in sb.CANDIDATES] and len(rows) == 9
    x = {r["id"]: r for r in rows}["trend_long"]
    assert set(x) == {"id", "strategy", "family", "side", "description", "params_schema", "preset", "frames_allowed"}
    assert x["frames_allowed"] == list(FRAMES) and list(x["params_schema"]) == list(BY_ID["trend_long"]["params_schema"])   # thứ tự giữ nguyên
    spec = x["params_schema"]["sig.ema_fast"]
    assert spec == {"group": "signal", "type": "int", "min": 5, "max": 100, "step": 1, "default": 50, "label_vi": "EMA nhanh", "unit": "nến",
                    "help_vi": spec["help_vi"]}
    assert x["params_schema"]["sig.trend_tf"]["type"] == "choice" and "4h" in x["params_schema"]["sig.trend_tf"]["choices"]
    assert x["preset"]["source"] == "build X stage A top-1 dev1" and x["preset"]["params"]["sig.adx_min"] == 25
    assert x["preset"]["params"]["sig.ema_fast"] == 50                                       # preset đầy đủ khoá
    assert x["preset"]["timeframe"] == "15m"
    # chiến lược không có trong presets.json -> mặc định schema
    d = {r["id"]: r for r in rows}["reversion_short"]["preset"]
    assert d["source"] == pr.SOURCE_DEFAULT and d["evidence"] is None
    assert d["timeframe"] is None
    json.dumps(rows, allow_nan=False)


def test_validate_endpoint(client):
    ok = client.post("/api/studio/strategies/validate", json={"id": "trend_long", "params": {"sig.ema_fast": 20}}).json()
    assert ok["ok"] and ok["errors"] == [] and ok["resolved"]["sig.ema_fast"] == 20 and ok["resolved"]["sig.adx_min"] == 25
    bad = client.post("/api/studio/strategies/validate", json={"id": "trend_long", "params": {"sig.ema_fast": 0}}).json()
    assert not bad["ok"] and bad["errors"][0]["field"] == "params.sig.ema_fast" and bad["resolved"] is None
    assert client.post("/api/studio/strategies/validate", json={"id": "nope"}).status_code == 404


def test_basic_mode_ignores_client_params_and_uses_presets(client):
    crazy = {"stop_loss_rate": 999, "sig.ema_fast": -5, "whatever": "x", "sig.trend_tf": "9h"}
    r = client.post(URL, json={**BT, "strategies": [{"id": "breakout_4h_long", "params": crazy}, {"id": "trend_long", "params": crazy}],
                               "risk_per_trade_pct": 3.0, "stop_fill": "extreme"})
    assert r.status_code == 200, r.text                                     # mode mặc định = basic: không 422 vì tham số bị bỏ qua
    items, cmd = _cmd_strategies()
    assert items == [{"id": "breakout_4h_long", "params": {"stop_loss_rate": 3.0, "trailing_stop": 3.0, "trailing_activation_pct": 1.0, "timeout": 10080}},
                     {"id": "trend_long", "params": {"sig.adx_min": 25, "stop_loss_rate": 3.5, "trailing_stop": 4.5, "trailing_activation_pct": 0.0, "timeout": 4320}}]
    assert cmd["risk_per_trade"] == 0.5 and cmd["stop_fill"] == "level"   # khoá sẵn: bỏ qua rủi ro/stop_fill của client
    assert cmd["symbols"] == ["BTC@perp", "SOL@perp"]                                           # tài sản + cửa sổ ngày vẫn theo client
    job = _job(client, r.json()["job_id"])
    assert job["mode"] == "basic" and job["custom_gates"] is False and job["promotable"] is True and job["ignored_client_params"] is True
    rs = {s["id"]: s for s in job["resolved"]["strategies"]}
    assert rs["breakout_4h_long"]["params"]["stop_loss_rate"] == 3.0 and rs["breakout_4h_long"]["preset_source"] == "book.json (sổ đã build 01/10)"
    assert rs["trend_long"]["params"]["sig.ema_fast"] == 50                       # tham số ĐẦY ĐỦ, tái lập được
    assert job["resolved"]["risk_per_trade_pct"] == 0.5 and job["resolved"]["start"] == "2025-03-01"
    # mode mặc định khi không gửi == basic
    assert client.post(URL, json={**BT, "strategies": [{"id": "trend_long"}]}).status_code == 200


def test_basic_mode_limits_strategy_count_and_ids(client):
    ids = [c["id"] for c in sb.CANDIDATES]
    assert client.post(URL, json={**BT, "strategies": [{"id": i} for i in ids]}).status_code == 200      # đúng 9 (cả sổ)
    n = len(FakePopen.calls)
    r = client.post(URL, json={**BT, "strategies": [{"id": i} for i in ids] + [{"id": "trend_long"}]})
    assert r.status_code == 422                                                                   # 10 mục: vượt trần / lặp id
    r = client.post(URL, json={**BT, "strategies": [{"id": "khong_co"}]})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "strategies[0].id" and "Không có chiến lược" in r.json()["detail"][0]["msg"]
    assert len(FakePopen.calls) == n


def test_basic_mode_timeframe_mismatch_warning(client):
    # Khớp khung (15m): không có cảnh báo
    r_ok = client.post(URL, json={**BT, "timeframe": "15m", "strategies": [{"id": "trend_long"}]})
    assert r_ok.status_code == 200
    assert "timeframe_mismatch" not in r_ok.json()
    job_ok = _job(client, r_ok.json()["job_id"])
    assert "timeframe_mismatch" not in job_ok["resolved"]

    # Lệch khung (1h != preset 15m): có cảnh báo trong response và job resolved, không chặn (200)
    r_warn = client.post(URL, json={**BT, "timeframe": "1h", "strategies": [{"id": "trend_long"}]})
    assert r_warn.status_code == 200
    assert "timeframe_mismatch" in r_warn.json()
    assert "1h" in r_warn.json()["timeframe_mismatch"] and "15m" in r_warn.json()["timeframe_mismatch"]
    job_warn = _job(client, r_warn.json()["job_id"])
    assert "timeframe_mismatch" in job_warn["resolved"]

    # Preset mặc định (timeframe=None): không cảnh báo lệch khung
    r_def = client.post(URL, json={**BT, "timeframe": "1h", "strategies": [{"id": "reversion_short"}]})
    assert r_def.status_code == 200
    assert "timeframe_mismatch" not in r_def.json()

    # WFA basic: lệch khung cũng cảnh báo
    wfa_warn = client.post("/api/studio/book/wfa", json={**WFA, "timeframe": "1h", "candidates": ["trend_long"]})
    assert wfa_warn.status_code == 200
    assert "timeframe_mismatch" in wfa_warn.json()
    job_wfa = _job(client, wfa_warn.json()["job_id"])
    assert "timeframe_mismatch" in job_wfa["resolved"]

    # WFA basic: đúng khung 15m không cảnh báo
    wfa_ok = client.post("/api/studio/book/wfa", json={**WFA, "timeframe": "15m", "candidates": ["trend_long"]})
    assert wfa_ok.status_code == 200
    assert "timeframe_mismatch" not in wfa_ok.json()


def test_invalid_mode_is_422(client):
    assert client.post(URL, json={**BT, "mode": "expert", "strategies": [{"id": "trend_long"}]}).status_code == 422


def test_advanced_backtest_validates_and_passes_all_params(client):
    params = {"sig.trend_tf": "4h", "sig.ema_fast": 20, "sig.ema_slow": 100, "sig.adx_n": 20}
    r = client.post(URL, json={**BT, "mode": "advanced", "strategies": [{"id": "trend_long", "params": params}]})
    assert r.status_code == 200, r.text
    items, cmd = _cmd_strategies()
    prm = items[0]["params"]
    assert prm["sig.trend_tf"] == "4h" and prm["sig.ema_fast"] == 20 and prm["sig.ema_slow"] == 100 and prm["sig.adx_n"] == 20
    assert prm["sig.adx_min"] == 25 and prm["stop_loss_rate"] == 3.5          # khoá thiếu lấy từ preset (không phải mức giữa của space)
    assert "sig.dch_n" not in prm and "atr_period" not in prm                  # khác mặc định mới đi kèm (space luôn đi kèm)
    job = _job(client, r.json()["job_id"])
    assert job["mode"] == "advanced" and job["ignored_client_params"] is False and job["promotable"] is True
    full = job["resolved"]["strategies"][0]["params"]
    assert full["sig.trend_tf"] == "4h" and set(full) == set(BY_ID["trend_long"]["params_schema"])
    # tham số đã giải quyết dựng lại đúng cây
    tree = materialize(BY_ID["trend_long"], prm)["tree"]
    assert tree[0][0] == [{"frame": "4h", "column": "ema_20", "index": 0}, ">", {"frame": "4h", "column": "ema_100", "index": 0}]


def test_advanced_backtest_risk_per_trade(client):
    r = client.post(URL, json={**BT, "mode": "advanced", "risk_per_trade_pct": 0.8,
                               "strategies": [{"id": "trend_long"}, {"id": "breakout_4h_long", "params": {"risk_per_trade_pct": 0.3}}]})
    assert r.status_code == 200, r.text                                    # mức của request thắng
    _, cmd = _cmd_strategies()
    assert cmd["risk_per_trade"] == 0.8
    r = client.post(URL, json={**BT, "mode": "advanced", "strategies": [{"id": "trend_long"}, {"id": "breakout_4h_long", "params": {"risk_per_trade_pct": 0.3}}]})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "strategies[1].params.risk_per_trade_pct"


@pytest.mark.parametrize("params,field,frag", [
    ({"sig.ema_fast": 0}, "strategies[0].params.sig.ema_fast", "khoảng 5 đến 100"),
    ({"sig.ema_fast": 20.5}, "strategies[0].params.sig.ema_fast", "số nguyên"),
    ({"sig.ema_fast": 150}, "strategies[0].params.sig.ema_fast", "khoảng"),
    ({"sig.ema_fast": 90, "sig.ema_slow": 60}, "strategies[0].params.sig.ema_fast", "nhỏ hơn EMA chậm"),
    ({"sig.trend_tf": "2h"}, "strategies[0].params.sig.trend_tf", "một trong"),
    ({"sig.entry_tf": 15}, "strategies[0].params.sig.entry_tf", "một trong"),
    ({"stop_loss_rate": 0}, "strategies[0].params.stop_loss_rate", "khoảng"),
    ({"stop_loss_rate": "abc"}, "strategies[0].params.stop_loss_rate", "phải là số"),
    ({"stop_loss_rate": True}, "strategies[0].params.stop_loss_rate", "phải là số"),
    ({"leverage": 25}, "strategies[0].params.leverage", "khoảng"),
    ({"timeout": -1}, "strategies[0].params.timeout", "khoảng"),
    ({"adx_n": 14}, "strategies[0].params.adx_n", "sig.adx_n"),                    # gợi ý tiền tố
    ({"nonexistent": 1}, "strategies[0].params.nonexistent", "không có trong chiến lược"),
])
def test_advanced_validation_422_per_field(client, params, field, frag):
    r = client.post(URL, json={**BT, "mode": "advanced", "strategies": [{"id": "trend_long", "params": params}]})
    assert r.status_code == 422, r.text
    d = {e["field"]: e["msg"] for e in r.json()["detail"]}
    assert field in d and frag in d[field], d
    assert any(ord(ch) > 127 for ch in d[field])                                  # tiếng Việt
    assert not FakePopen.calls


def test_advanced_reports_every_bad_field_at_once(client):
    r = client.post(URL, json={**BT, "mode": "advanced", "strategies": [
        {"id": "trend_long", "params": {"sig.ema_fast": 0, "stop_loss_rate": 99}}, {"id": "reversion_long", "params": {"sig.bb_k": 9}}]})
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["detail"]} == {"strategies[0].params.sig.ema_fast", "strategies[0].params.stop_loss_rate",
                                                        "strategies[1].params.sig.bb_k"}


# ─── custom_gates ───────────────────────────────────────────────────────────
DAILY = list(np.random.default_rng(11).normal(0.0012, 0.012, 150))


def test_mc_basic_ignores_client_settings(client):
    r = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "simulations": 500, "ruin_threshold_pct": 10, "stress_max_mdd_pct": 5,
                                                 "block_days": 2, "horizon_days": 30, "stress_scenarios": ["cost_x2"]})
    assert r.status_code == 200, r.text
    out = r.json()
    prm = out["params"]
    assert prm["simulations"] == 10_000 and prm["block_days"] == 5 and prm["horizon_days"] == 365 and prm["ruin_threshold_pct"] == 30.0
    assert prm["mode"] == "basic" and prm["custom_gates"] is False and prm["promotable"] is True and prm["ignored_client_params"] is True
    assert len(out["stress"]) == 6 and out["gate"]["gate_eligible"] is True and out["gate"]["stress_max_mdd_pct"] == 50.0


@pytest.mark.parametrize("extra,custom", [
    ({"simulations": 10_000}, False),
    ({"simulations": 20_000, "block_days": 3, "horizon_days": 100, "seed": 3, "scale": 1.5}, False),     # đổi tham số dữ liệu: vẫn gate chuẩn
    ({"simulations": 500}, True),                                                                          # < 10.000
    ({"ruin_threshold_pct": 20}, True),
    ({"stress_max_mdd_pct": 70}, True),
    ({"stress_scenarios": ["cost_x2", "crash_day"]}, True),
    ({"stress_scenarios": ["worst_days_first", "reversed_order", "crash_day", "cost_x2", "longest_losing_streak_x2", "worst_bootstrap"]}, False),
])
def test_mc_advanced_custom_gates_flag(client, extra, custom):
    r = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "mode": "advanced", **({"simulations": 10_000} | extra)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["params"]["mode"] == "advanced" and out["params"]["custom_gates"] is custom and out["params"]["promotable"] is (not custom)
    assert out["gate"]["custom_gates"] is custom
    if custom:
        assert out["gate"]["gate_eligible"] is False
    if "stress_scenarios" in extra:
        assert {s["name"] for s in out["stress"]} == set(extra["stress_scenarios"])
        assert out["gate"]["checks"]["stress_mdd"]["detail"] in extra["stress_scenarios"]


def test_mc_advanced_bad_stress_names_422(client):
    r = client.post("/api/studio/book/mc", json={"daily_returns": DAILY, "mode": "advanced", "stress_scenarios": ["nope"]})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "stress_scenarios"


def _stamped_job(kind, state="done", name=None, result=None, **meta):
    d = os.path.join(batch_jobs.jobs_root(), name or f"{time.strftime('%Y%m%d_%H%M%S')}_a1b2c3")
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": os.path.basename(d), "kind": kind, "params": {}, "pid": 2 ** 22 + 1, "created": 1.0, "started": 2.0,
                               "finished": 3.0, "state": state, "exit_code": 0, **meta})
    open(os.path.join(d, "out.log"), "w").write("")
    if result is not None:
        json.dump(result, open(os.path.join(d, "result.json"), "w"))
    return os.path.basename(d), d


def test_publish_refuses_custom_gates_job(client, tmp_path):
    jid, d = _stamped_job("book_build", name="20260101_000001_aaaaaa", custom_gates=True, mode="advanced", promotable=False)
    os.makedirs(os.path.join(d, "alphas"))
    json.dump({"status": "x"}, open(os.path.join(d, "alphas", "book.json"), "w"))
    r = client.post("/api/studio/book/publish", json={"job_id": jid})
    assert r.status_code == 409 and "custom_gates" in r.json()["detail"] and "KHÔNG" in r.json()["detail"]
    assert not (tmp_path / "alphas").exists()                                  # không ghi gì ra data/alphas


def test_wfa_job_with_custom_gates_makes_mc_non_promotable(client):
    daily = {"extreme": DAILY, "level": DAILY}
    jid, _ = _stamped_job("book_wfa", name="20260101_000002_bbbbbb", custom_gates=True, mode="advanced", result={"summary": {"oos_daily": daily}})
    r = client.post("/api/studio/book/mc", json={"wfa_job_id": jid})            # MC chuẩn nhưng nguồn WFA dùng gate tuỳ chỉnh
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["params"]["custom_gates"] is True and out["params"]["promotable"] is False and out["gate"]["gate_eligible"] is False
    assert out["params"]["source"]["job_id"] == jid


def test_job_status_mirrors_flags_into_result(client):
    jid, _ = _stamped_job("book_backtest", name="20260101_000003_cccccc", mode="advanced", custom_gates=True, promotable=False, result={"ret_pct": 1.0})
    job = _job(client, jid)
    assert job["result"]["custom_gates"] is True and job["result"]["promotable"] is False and job["result"]["mode"] == "advanced"
    rows = client.get("/api/studio/book/jobs").json()["jobs"]
    assert rows[0]["mode"] == "advanced" and rows[0]["custom_gates"] is True


# ─── WFA ────────────────────────────────────────────────────────────────────
WFA = {"start": "2025-01-01", "end": "2025-09-30"}


def _wfa_files():
    p = launched(FakePopen.calls[-1])[1]
    return p, p["strategies"]


def test_wfa_basic_uses_presets_default_folds(client):
    r = client.post("/api/studio/book/wfa", json={**WFA, "candidates": ["breakout_4h_long", "trend_long"], "train_days": 30, "test_days": 5, "n": 9,
                                                  "risk_per_trade_pct": 4.0, "sims": 100})
    assert r.status_code == 200, r.text
    cmd, cfgs = _wfa_files()
    assert not {"candidates", "train_days", "test_days", "sims"} & set(cmd)   # fold/gate chuẩn
    assert cfgs == [{"id": "breakout_4h_long", "configs": [{"stop_loss_rate": 3.0, "trailing_stop": 3.0, "trailing_activation_pct": 1.0, "timeout": 10080}]},
                    {"id": "trend_long", "configs": [{"sig.adx_min": 25, "stop_loss_rate": 3.5, "trailing_stop": 4.5, "trailing_activation_pct": 0.0, "timeout": 4320}]}]
    assert cmd["risk_per_trade"] == 0.5
    job = _job(client, r.json()["job_id"])
    assert job["mode"] == "basic" and job["custom_gates"] is False and job["resolved"]["train_days"] == 120 and job["resolved"]["test_days"] == 30
    assert job["ignored_client_params"] is True
    # strategies[].id cũng được (configs bị bỏ qua); report_dir bị từ chối ở chế độ Cơ bản
    r = client.post("/api/studio/book/wfa", json={**WFA, "strategies": [{"id": "trend_long", "configs": [{"stop_loss_rate": 1.5}]}]})
    assert r.status_code == 200 and _wfa_files()[1][0]["configs"][0]["stop_loss_rate"] == 3.5
    assert client.post("/api/studio/book/wfa", json={"report_dir": "x"}).status_code == 422


def test_wfa_advanced_passes_folds_and_flags_custom_sims(client, monkeypatch):
    body = {**WFA, "mode": "advanced", "candidates": ["trend_long"], "n": 4, "train_days": 90, "test_days": 20, "step_days": 10, "mc_seed": 5}
    r = client.post("/api/studio/book/wfa", json={**body, "sims": 10_000})
    assert r.status_code == 200, r.text
    cmd = launched(FakePopen.calls[-1])[1]
    assert cmd["candidates"] == ["trend_long"] and cmd["n"] == 4
    assert cmd["train_days"] == 90 and cmd["step_days"] == 10 and cmd["sims"] == 10000
    assert _job(client, r.json()["job_id"])["custom_gates"] is False
    r = client.post("/api/studio/book/wfa", json={**body, "sims": 500})
    job = _job(client, r.json()["job_id"])
    assert job["custom_gates"] is True and job["promotable"] is False and job["mode"] == "advanced" and job["resolved"]["sims"] == 500


def test_wfa_advanced_unsupported_options_are_reported(client):
    body = {**WFA, "mode": "advanced", "candidates": ["trend_long"]}
    r = client.post("/api/studio/book/wfa", json={**body, "embargo_days": 3})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "embargo_days"
    assert not FakePopen.calls
    r = client.post("/api/studio/book/wfa", json={**body, "step_days": 10, "sims": 10_000, "mc_seed": 3})   # cờ đã nằm trong danh sách trắng
    assert r.status_code == 200, r.text
    cmd = launched(FakePopen.calls[-1])[1]
    assert cmd["step_days"] == 10 and cmd["sims"] == 10000 and cmd["mc_seed"] == 3
    r = client.post("/api/studio/book/wfa", json={**body, "step_days": 999})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "step_days"


def test_wfa_advanced_strategy_configs(client):
    ok = {"id": "trend_long", "configs": [{"stop_loss_rate": 2.0}, {"stop_loss_rate": 3.0, "sig.adx_min": 30}]}
    r = client.post("/api/studio/book/wfa", json={**WFA, "mode": "advanced", "strategies": [ok]})
    assert r.status_code == 200, r.text
    cmd, cfgs = _wfa_files()
    assert [c["stop_loss_rate"] for c in cfgs[0]["configs"]] == [2.0, 3.0] and cfgs[0]["configs"][1]["sig.adx_min"] == 30
    # tham số ngoài không gian tối ưu (chu kỳ/khung) -> đi thẳng vào strategies.json của job
    r = client.post("/api/studio/book/wfa", json={**WFA, "mode": "advanced", "strategies": [
        {"id": "trend_long", "configs": [{"sig.ema_fast": 20, "sig.ema_slow": 100, "sig.trend_tf": "4h"}]}]})
    assert r.status_code == 200, r.text
    cfg = _wfa_files()[1][0]["configs"][0]
    assert cfg["sig.ema_fast"] == 20 and cfg["sig.ema_slow"] == 100 and cfg["sig.trend_tf"] == "4h"
    r = client.post("/api/studio/book/wfa", json={**WFA, "mode": "advanced", "strategies": [{"id": "trend_long", "configs": [{"sig.trend_tf": "3h"}]}]})
    assert r.status_code == 422
    r = client.post("/api/studio/book/wfa", json={**WFA, "mode": "advanced", "strategies": [{"id": "trend_long", "configs": [{"stop_loss_rate": 99}]}]})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "strategies[0].configs[0].stop_loss_rate"


def test_check_wfa_strategies_accepts_schema_keys_and_choices():
    ok = batch_jobs.check_wfa_strategies([{"id": "trend_long", "configs": [{"sig.ema_fast": 20, "sig.trend_tf": "4h", "stop_loss_rate": 2.0}]}])
    assert ok[0]["configs"][0]["sig.trend_tf"] == "4h"
    for bad in ({"sig.trend_tf": "3h"}, {"sig.ema_fast": "20"}, {"nope": 1}, {"stop_loss_rate": float("nan")}, {"stop_loss_rate": True}):
        with pytest.raises(batch_jobs.JobError):
            batch_jobs.check_wfa_strategies([{"id": "trend_long", "configs": [bad]}])


def test_wfa_job_candidates_from_list_accepts_schema_keys():
    import importlib
    vb = importlib.import_module("backend.wfa.run")
    assert vb.candidates_from_list([{"id": "trend_long", "configs": [{"sig.ema_fast": 20, "sig.trend_tf": "4h"}]}])[0]["configs"][0]["sig.trend_tf"] == "4h"
    with pytest.raises(SystemExit):
        vb.candidates_from_list([{"id": "trend_long", "configs": [{"nope": 1}]}])


def test_presets_evidence_bools_are_real_bools(tmp_path):
    run = tmp_path / "20260101_000000"
    run.mkdir()
    cand = BY_ID["trend_long"]
    params = {k: v[0] for k, v in cand["space"].items()}
    (run / "stage_a.json").write_text(json.dumps({"trend_long": [{"score": 1.0, "params": params, "dev1": {}}]}))
    (run / "report.json").write_text(json.dumps({"candidates": {"trend_long": {"accepted": "False", "dev1_top": [{"params": params, "dev2_pass": "True"}]}}}))
    ev = pr.from_build_runs(str(tmp_path), [cand])["trend_long"]["evidence"]
    assert ev["accepted"] is False and ev["dev2_pass"] is True
    out = tmp_path / "p.json"
    pr.write_presets({"x": np.bool_(True)}, str(out))
    assert json.loads(out.read_text()) == {"x": True}


def test_timeframe_lifts_frames_and_blocks_incompatible_strategies():
    """Khung chạy: lựa chọn khung < khung chạy được nâng lên (nếu là lựa chọn hợp lệ) hoặc bỏ; chiến lược không còn khung hợp lệ bị báo."""
    from backend.optimize.funnel import generate as gen
    by = BY_ID
    sp = gen.space_for(by["trend_long"], "schema", "1h")
    assert set(sp["sig.entry_tf"]) == {"1h"} and set(sp["sig.trend_tf"]) == {"1h", "4h", "24h"}
    grid = gen.space_for(by["reversion_long"], "grid", "15m")
    assert grid["sig.entry_tf"] == ["15m"]                                     # mặc định 5m -> 15m
    p = next(gen.iter_params(grid, 1, 1))
    assert gen.validate_alpha(by["reversion_long"], p, "grid", "15m") is None
    assert gen.validate_alpha(by["reversion_long"], {**p, "sig.entry_tf": "5m"}, "grid", "15m")
    bad = gen.incompatible([by["trend_long"], by["keltner_trend_long"]], "schema", "4h")
    assert "trend_long" in bad and "keltner_trend_long" not in bad


def test_api_rejects_strategy_incompatible_with_timeframe():
    from fastapi.testclient import TestClient
    from backend.main import app
    r = TestClient(app).post("/api/studio/funnel/runs", json={"strategies": ["trend_long"], "n_per_strategy": 5, "timeframe": "4h"})
    assert r.status_code == 422 and "khung 4h" in r.text


def test_incompatible_timeframe_is_422_before_job(client):
    """trend_long: khung vào lệnh tối đa nhỏ hơn 4h -> 422 theo trường ngay ở API (trước đây job WFA chạy rồi mới hỏng)."""
    n = len(FakePopen.calls)
    r = client.post(URL, json={**BT, "timeframe": "4h", "strategies": [{"id": "trend_long"}]})
    assert r.status_code == 422 and "4h" in r.text and "strategies[0]" in r.text
    w = client.post("/api/studio/book/wfa", json={**WFA, "timeframe": "4h", "candidates": ["trend_long"]})
    assert w.status_code == 422 and "candidates[0]" in w.text
    assert len(FakePopen.calls) == n
