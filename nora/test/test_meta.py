"""GET /api/studio/meta: mọi trường bằng đúng nguồn của nó (không giá trị chép tay)."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.carlo import carlo
from backend.analys.param import FRAME_MS
from backend.models import storage as store
from backend.data.data import coverage
from backend.nautilus.version import ENGINE_NAME, NAUTILUS_VERSION
from backend.main import app
from backend.alpha import strategies
from backend.models.meta import build_meta
from backend.jobs import runner as P
from backend.routes import alpha, book as optimize, process as process_routes, live as live_routes  # noqa: F401

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data


@pytest.fixture(scope="module")
def m():
    return build_meta(process_routes._limit_models())




def test_gates_equal_constants(m):
    g = {x["key"]: x["value"] for x in m["gates"]}
    for k in ("MC_MIN_SIMULATIONS", "MC_MAX_SIMULATIONS", "MC_RUIN_THRESHOLD_PCT", "MC_MAX_RUIN_PCT", "STRESS_MAX_MDD_PCT"):
        assert g[k] == getattr(carlo, k)
    assert "funnel" not in m   # phễu đã gỡ: meta không còn mục funnel


def test_frames_live_jobs(m):
    assert m["frames"]["all"] == list(FRAME_MS)
    assert set(m["frames"]["book"]) <= set(FRAME_MS) and set(m["frames"]["custom_backtest"]) <= set(FRAME_MS)
    assert m["frames"]["book"] == ["15m", "1h", "4h"] and m["frames"]["defaults"]["book"] == "1h"
    assert m["frames"]["defaults"]["custom_backtest"] in m["frames"]["custom_backtest"]
    assert set(optimize.BacktestRequest.model_json_schema()["properties"]) >= {"run_frame", "timeframe"}
    # T5: live đã chạy thật trên Nautilus TradingNode -> meta khai báo đủ chế độ (không còn modes=[] / not_ready)
    assert m["live"]["modes"] == ["paper", "testnet", "live"] and "not_ready" not in m["live"]
    assert m["live"]["venues"] == ["okx"]
    assert [k["kind"] for k in m["jobs"]["kinds"]] == list(P.KINDS)
    for k in m["jobs"]["kinds"]:
        assert k["label_vi"] == P.KINDS[k["kind"]]["label_vi"] and k["label_vi"] != k["kind"]
        assert k["ephemeral"] == (k["kind"] in P.EPHEMERAL_KINDS)
        base = P.persist_dest_base(k["kind"])
        assert k["persist_to"] == (os.path.relpath(base, store.data_home()) if base else None)


def test_universe_limits_books_paths(m):
    assert m["universe"]["data"]["assets"] == [a["symbol"] for a in coverage()]
    for key, path in (("book", store.alpha_file("book")), ("explore", store.alpha_dir("explore", "book.json"))):
        b = store.read_json(path)
        assert m["universe"][key] == (b["universe"] if b else [])
    lim = m["limits"]["book_mc"]["seed"]
    sch = optimize.McRequest.model_json_schema()["properties"]["seed"]
    assert (lim["minimum"], lim["maximum"], lim["default"]) == (sch["minimum"], sch["maximum"], sch["default"])
    assert "live_bot" in P.KINDS and P.KINDS["live_bot"]["func"] == "run_live_bot"   # T5: bot live là job kind thật
    for key, p in (("book", store.alpha_file("book")), ("explore_book", store.alpha_dir("explore", "book.json"))):
        assert m["paths"][key] == os.path.relpath(p, store.data_home())


def test_engine_is_nautilus(m):
    assert m["engine"] == {"name": ENGINE_NAME, "version": NAUTILUS_VERSION, "docs_url": "https://nautilustrader.io/docs/latest/",
                           "default_exec_mode": "fast", "standard_frame": "1m",
                           "run_modes": ["backtest", "paper", "testnet"]}   # T5: thêm paper/testnet
    assert NAUTILUS_VERSION not in ("", "not_installed")






def test_etag_304():
    c = TestClient(app)
    r = c.get("/api/studio/meta")
    assert r.status_code == 200 and r.headers["etag"]
    assert c.get("/api/studio/meta", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


# ─── metrics (METRIC_DEFS) + explain_tour (NOTE_TOUR) ───────────────────────
from test_custom_backtest import CODE_1H, _params, market  # noqa: E402,F401  (fixture dữ liệu tổng hợp + mã mẫu)
from backend.metrics import charts, metrics as metrics_mod  # noqa: E402

_DEF_FIELDS = {"label_vi", "unit", "format", "better", "group", "help_vi"}
_NOT_METRICS = {"year", "stage"}


def _leaf_keys(o, out):
    """Khoá có giá trị số (hoặc None) ở mọi mức lồng nhau; bỏ chuỗi/bool/danh sách và bản đồ theo tên (by_coin, by_year, ...)."""
    for k, v in o.items():
        if isinstance(v, dict) and not (k.startswith("by_") or k in ("time_in_market_by_coin", "exit_reasons", "exit_reason_counts")):
            _leaf_keys(v, out)
        elif v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            out.add(str(k))


def test_metric_defs_well_formed():
    for k, d in metrics_mod.METRIC_DEFS.items():
        assert set(d) == _DEF_FIELDS, k
        assert d["unit"] in ("%", "x", "USD", "lệnh", "ngày", "giờ", "phút", "nến", "tầng", "lần", ""), k
        assert d["better"] in ("higher", "lower", None) and d["group"] in metrics_mod.METRIC_GROUPS and d["help_vi"] and d["label_vi"], k
        assert d["format"] in ("pct1", "pct2", "num2", "num3", "int", "usd2", "text"), k


@pytest.fixture
def real_result(market):
    from backend.jobs import tasks
    return tasks.run_custom(_params(code=CODE_1H, symbols=["AAA", "BBB", "CCC"], initial_capital=10_000))


def test_every_result_metric_key_has_a_def(real_result):
    r, keys = real_result, set()
    for blk in r["metrics"].values():
        _leaf_keys({k: v for k, v in blk.items()} if isinstance(blk, dict) else {}, keys)
    for row in r["yearly"] + r["by_symbol"]:
        _leaf_keys(row, keys)
    for sec in ("signal_activity", "pnl_structure", "market_comparison", "train_vs_test", "regime_analysis"):
        _leaf_keys(r["diagnostics"][sec], keys)
    keys -= _NOT_METRICS | {"annualization_days", "test_fresh_capital"}
    assert {"sharpe", "fees_usd", "beta", "train_sharpe"} <= keys
    assert not (keys - set(metrics_mod.METRIC_DEFS)), sorted(keys - set(metrics_mod.METRIC_DEFS))


def test_tour_equals_notes_order(real_result):
    n = charts.build_notes(real_result["explain"], real_result)
    assert [t["notes_key"] for t in charts.NOTE_TOUR] == [k for k in n if k in {t["notes_key"] for t in charts.NOTE_TOUR}]
    assert len(charts.NOTE_TOUR) == 5
    assert all(set(t) == {"key", "label_vi", "notes_key", "section"} and t["label_vi"] for t in charts.NOTE_TOUR)
    assert all(isinstance(n[t["notes_key"]], str) and n[t["notes_key"]] for t in charts.NOTE_TOUR)


def test_meta_exposes_metrics_and_tour(m):
    assert m["metrics"]["defs"] == metrics_mod.METRIC_DEFS and m["metrics"]["groups"] == metrics_mod.METRIC_GROUPS
    assert m["explain_tour"] == charts.NOTE_TOUR and m["education_hidden_sections"] == charts.EDUCATION_HIDDEN_SECTIONS


def test_etag_changes_with_metric_defs(monkeypatch):
    v0 = build_meta(process_routes._limit_models())["version"]
    changed = {**metrics_mod.METRIC_DEFS, "sharpe": {**metrics_mod.METRIC_DEFS["sharpe"], "label_vi": "Sharpe (đổi)"}}
    monkeypatch.setattr(metrics_mod, "METRIC_DEFS", changed)
    assert build_meta(process_routes._limit_models())["version"] != v0


# ─── stress, limits.book_mc ───────────────
import re as _re  # noqa: E402




def test_stress_equals_carlo(m):
    assert m["stress"] == carlo.STRESS_SCENARIOS
    by = {s["key"]: s["label_vi"] for s in m["stress"]}
    assert by == carlo.STRESS_LABELS_VI
    assert f"−{carlo.VERTICAL_CRASH_PCT:.0f}%" in by["vertical_crash"]
    assert f"+{carlo.VERTICAL_SURGE_PCT:.0f}%/{carlo.VERTICAL_SURGE_DAYS} ngày" in by["vertical_surge"]
    assert {s["key"] for s in m["stress"] if s["needs_positions"]} == set(carlo.VERTICAL_NAMES)




def test_book_mc_limits_equal_schema(m):
    props = optimize.McRequest.model_json_schema()["properties"]
    lim = m["limits"]["book_mc"]
    for f in ("simulations", "block_days", "horizon_days", "ruin_threshold_pct", "seed", "scale", "stress_max_mdd_pct"):
        for b in ("minimum", "maximum", "exclusiveMinimum", "default"):
            if b in props[f]:
                assert lim[f][b] == props[f][b], (f, b)
        assert lim[f]["help_vi"] == props[f]["description"]
    assert lim["ruin_threshold_pct"]["default"] == carlo.MC_RUIN_THRESHOLD_PCT
    assert lim["simulations"]["maximum"] == carlo.MC_MAX_SIMULATIONS and lim["simulations"]["default"] == carlo.MC_MIN_SIMULATIONS
