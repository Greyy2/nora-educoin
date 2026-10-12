"""P9.9 — chiến lược hệ thống viết bằng DSL Python (data/alpha/strategies/*.py) == định nghĩa cứng cũ, TỪNG BIT.

Tham chiếu cũ = test/fixtures/system_candidates_v1.json (chụp từ book.py cũ của thư mục strategy trong core: CANDIDATES / STRATEGIES ngay trước khi chuyển sang file).
1. Dạng biên dịch (cây tree/stop/dca_gate, position, space, params_schema, mô tả họ) trùng JSON từng ký tự (cả thứ tự khoá, kiểu int/float).
2. Với cả 6 chân (gồm cổng DCA) và nhiều điểm tham số (mặc định, giữa lưới, ngẫu nhiên trong lưới và trong khoảng p(lo, hi, step)): materialize() hai bên
   trùng, và backtest PortfolioEngine (dữ liệu tổng hợp) ra kết quả trùng từng bit.
3. Lỗi biên dịch có dòng/cột; ràng buộc của p(); loader bắt id trùng.
"""
import copy
import json
import os
import random

import pytest

import golden_scenarios as gs
from backend.signal.nodes import DslError
from backend.alpha.compile import compile_strategy_module, load_system_strategies, strategies_dir
from backend.models.params import AUTO_FALLBACK_ATR_FRAME, AUTO_FALLBACK_COOLDOWN, REGIME_MAP, RISK, materialize, schema_defaults
from backend import strategies as sl

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "system_candidates_v1.json")
with open(FIXTURE, encoding="utf-8") as _fh:
    OLD = json.load(_fh)
OLD_BY_ID = {c["id"]: c for c in OLD["candidates"]}
IDS = [c["id"] for c in OLD["candidates"]]


def _dump(x):
    return json.dumps(x, ensure_ascii=False)


def _old(cid):
    c = copy.deepcopy(OLD_BY_ID[cid])
    c.pop("legacy", None)          # khoá chết (không code nào đọc) — bỏ khi chuyển sang file
    return c


# P14 thêm vào params_schema của MỌI chiến lược hệ thống ba tham số hồ sơ rủi ro (core/params.py::BASE_POSITION: risk_profile, sl_anchor, sl_beyond_last_pct);
# fixture system_candidates_v1.json chụp trước P14 nên không có. Chủ ý của mã (không phải lỗi) -> bỏ khỏi so sánh; mọi khoá còn lại vẫn so từng ký tự.
P14_SCHEMA_KEYS = ("risk_profile", "sl_anchor", "sl_beyond_last_pct")


def _norm(c):
    """Điền mặc định cũ vào position (atr_frame 1h / cooldown 60 phút): file chiến lược khai tường minh, fixture cũ để {} — hai dạng tương đương.
    Bỏ ba khoá schema P14 (xem P14_SCHEMA_KEYS)."""
    c = copy.deepcopy(c)
    for k in P14_SCHEMA_KEYS:
        c.get("params_schema", {}).pop(k, None)
    c["position"] = {"atr_frame": AUTO_FALLBACK_ATR_FRAME, "cooldown": AUTO_FALLBACK_COOLDOWN, **c.get("position", {})}
    return c


def _with_avg_anchor(st):
    return {**st, "position": {**st["position"], "sl_anchor": st["position"].get("sl_anchor") or "avg"}}


def test_loaded_catalog_is_json_identical_to_old_hardcoded():
    assert [c["id"] for c in sl.CANDIDATES] == IDS
    for c in sl.CANDIDATES:
        assert _dump(_norm(c)) == _dump(_norm(_old(c["id"]))), c["id"]
        # bất biến thật: materialize() trùng từng ký tự với định nghĩa cũ
        # P14: schema mới có sl_anchor mặc định "avg"; fixture cũ không có khoá -> position.sl_anchor "" = theo risk_profile "legacy" (position_size.RISK_PROFILES["legacy"].sl_anchor == "avg")
        assert _dump(_with_avg_anchor(materialize(c, schema_defaults(c)))) == _dump(
            _with_avg_anchor(materialize(_old(c["id"]), schema_defaults(_old(c["id"]))))), c["id"]
    assert _dump(sl.STRATEGIES) == _dump(OLD["strategies"])
    assert sorted(REGIME_MAP) == sorted(OLD["regime_map_keys"])
    assert set(sl.SOURCES) == set(IDS) and all(v["file"].endswith(".py") for v in sl.SOURCES.values())


def _points(cid, rng):
    """(tên, tham số) : mặc định, giữa lưới, ngẫu nhiên trong lưới, ngẫu nhiên trong khoảng schema (p(lo, hi, step))."""
    c = OLD_BY_ID[cid]
    schema, space = c["params_schema"], c["space"]
    pts = [("default", schema_defaults(c))]
    mid = schema_defaults(c)
    mid.update({k: v[len(v) // 2] for k, v in space.items()})
    pts.append(("mid", mid))
    for i in range(2):
        pts.append((f"grid{i}", {**schema_defaults(c), **{k: rng.choice(v) for k, v in space.items()}}))
    for i in range(2):
        prm = dict(schema_defaults(c))
        for k, e in schema.items():
            if e["group"] == "exit" and k in ("cooldown", "atr_frame", "atr_period"):
                continue
            if e["group"] == "risk":
                continue
            if e["type"] == "choice":
                prm[k] = rng.choice(e["choices"])
            elif e["type"] == "int":
                prm[k] = rng.randrange(e["min"], e["max"] + 1, e["step"])
            else:
                n = int(round((e["max"] - e["min"]) / e["step"]))
                prm[k] = round(e["min"] + rng.randint(0, n) * e["step"], 6)
        pts.append((f"schema{i}", prm))
    return pts


@pytest.mark.parametrize("cid", IDS)
def test_materialize_identical_over_param_points(cid):
    rng = random.Random(f"p99-{cid}")
    old, new = _old(cid), sl.BY_ID[cid]
    for name, prm in _points(cid, rng):
        for regime in (False, True):
            try:
                a = materialize(old, dict(prm), regime=regime)
            except ValueError as e:     # điểm schema ngẫu nhiên có thể cho tên cột/khung không hợp lệ: hai bên phải CÙNG lỗi
                with pytest.raises(ValueError, match=str(e)[:30].replace("(", r"\(")):
                    materialize(new, dict(prm), regime=regime)
                continue
            b = materialize(new, dict(prm), regime=regime)
            assert _dump(a) == _dump(b), (cid, name)


def _run(strategies, symbols, root):
    from backend.alpha.plan import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    with gs.data_root_env(str(root)):
        eng = PortfolioEngine(symbols, strategies, gs.T0, gs.T0 + 38 * gs.DAY, trade_start_ts=gs.T0 + 18 * gs.DAY,
                              risk=RiskConfig.from_dict(RISK), use_cache=False)
        eng.run()
        return gs.canonicalize(eng.get_results())


def test_backtest_bitwise_all_legs_over_param_points(tmp_path):
    gs.write_synthetic_market(tmp_path / "data")
    syms = ["AAA@perp", "BBB@perp", "CCC@perp"]
    trades = {}
    for cid in IDS:
        rng = random.Random(f"bt-{cid}")
        old, new = _old(cid), sl.BY_ID[cid]
        for name, prm in _points(cid, rng)[:4]:           # mặc định, giữa lưới, 2 điểm ngẫu nhiên trong lưới
            sa = materialize(old, dict(prm))
            sb_ = materialize(new, dict(prm))
            # khung tín hiệu không nhỏ hơn khung chạy 1m; dữ liệu tổng hợp có đủ các khung của nến 1m
            ra, rb = _run([sa], syms, tmp_path / "data"), _run([sb_], syms, tmp_path / "data")
            assert ra["equity_curve"] == rb["equity_curve"], (cid, name)
            assert ra["positions"] == rb["positions"], (cid, name)
            assert ra == rb, (cid, name)
            trades[cid] = trades.get(cid, 0) + len(ra["positions"])
    print("trades per leg:", trades)
    assert sum(trades.values()) > 0, "không chân nào có lệnh trên dữ liệu tổng hợp: parity vô nghĩa"


# ─── trình biên dịch / loader ────────────────────────────────────────────────────────────────────────────────────
KEMA_SRC = open(os.path.join(strategies_dir(), "kema.py"), encoding="utf-8").read()


def test_compile_is_deterministic_and_pure():
    a, b = compile_strategy_module(KEMA_SRC), compile_strategy_module(KEMA_SRC)
    assert _dump(a) == _dump(b)
    assert a["code_hash"] == b["code_hash"] and len(a["code_hash"]) == 12


@pytest.mark.parametrize("old,new,msg", [
    ("timeperiod=p('ema_n', 30,", "timeperiod=p('ema_n', 300,", "ngoài"),                 # mặc định ngoài [lo, hi]
    ("tf.pv_close\n        high", "tf.pv_closee\n        high", "pv_"),                      # cột dữ liệu không có
    ("self.feat.ema(", "self.feat.macd(", "chưa hỗ trợ"),                                  # feature không phải cột kernel
    ("kc_up = ema + atr * k_up", "kc_up = ema + atr * k_upp", "chưa được gán"),
])
def test_compile_errors_have_line_and_message(old, new, msg):
    assert old in KEMA_SRC, old
    with pytest.raises(DslError) as ei:
        compile_strategy_module(KEMA_SRC.replace(old, new, 1))
    assert ei.value.line is not None and msg in ei.value.message


def test_unused_signal_param_is_rejected():
    src = KEMA_SRC.replace("kc_dn = ema - atr * k_dn", "kc_dn = ema - atr * 2.0", 1)
    with pytest.raises(DslError, match="k_dn"):
        compile_strategy_module(src)


def test_loader_detects_duplicate_ids(tmp_path):
    (tmp_path / "a.py").write_text(KEMA_SRC, encoding="utf-8")
    (tmp_path / "b.py").write_text(KEMA_SRC, encoding="utf-8")
    with pytest.raises(DslError, match="trùng"):
        load_system_strategies(str(tmp_path))


def test_loader_orders_by_order_then_leg():
    got = load_system_strategies()
    assert [s["id"] for s in got["strategies"]] == ["kema", "sideway", "dca"]
    assert [c["side"] for c in got["candidates"]] == ["LONG", "SHORT"] * 3
