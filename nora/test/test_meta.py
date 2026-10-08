"""GET /api/studio/meta: mọi trường bằng đúng nguồn của nó (không giá trị chép tay)."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.carlo import carlo
from backend.core.params import FRAME_MS
from backend.crawl import store
from backend.live import live as live_mod
from backend.main import app
from backend.optimize.book import registry
from backend.optimize.funnel import stages
from backend.optimize.process import process as P
from backend.routes import alpha, optimize, process as process_routes, live as live_routes


@pytest.fixture(scope="module")
def m():
    return process_routes._build_meta()


def test_stages_and_trades(m):
    ids = [s["id"] for s in m["funnel"]["stages"] if not s["legacy"]]
    assert ids == stages.STAGES
    assert [s["id"] for s in m["funnel"]["stages"] if s["legacy"]] == [stages.LEGACY_STAGE]
    assert {s["id"] for s in m["funnel"]["stages"] if s["has_trades"]} == set(stages.TRADE_STAGES)
    assert all(s["label"] == stages.STAGE_LABELS[s["id"]] for s in m["funnel"]["stages"])


def test_gates_equal_constants(m):
    snap = stages.thresholds_snapshot()
    g = {x["key"]: x["value"] for x in m["funnel"]["gates"]}
    for k in ("S1_MAX_MDD_PCT", "S1_MIN_TRADES", "S3_MIN_FOLD_T", "S4_MAX_RUIN_PCT", "S6_MAX_MDD_PCT", "S2_PBO_MAX"):
        assert g[k] == snap[k]
    assert g["MC_MAX_RUIN_PCT"] == carlo.MC_MAX_RUIN_PCT and g["MC_MIN_SIMULATIONS"] == carlo.MC_MIN_SIMULATIONS
    assert "min_sharpe" not in g


def test_frames_live_jobs(m):
    assert m["frames"]["all"] == list(FRAME_MS)
    assert set(m["frames"]["funnel"]) <= set(FRAME_MS) and set(m["frames"]["custom_backtest"]) <= set(FRAME_MS)
    modes = {x["mode"]: x for x in m["live"]["modes"]}
    assert set(modes) == {"paper", "demo", "live"}
    for k, x in modes.items():
        assert x["default_engine"] == store.default_engine(k) and x["engines"] == list(live_mod.ENGINES)
        assert x["dir"] == "live/" + store.LIVE_MODE_DIR[k]
    assert modes["live"]["books"] == ["main"] and modes["paper"]["books"] == list(live_mod.BOOKS)
    assert set(m["live"]["venues"]) == {"okx", "binance"}
    assert [k["kind"] for k in m["jobs"]["kinds"]] == list(P.KINDS)
    for k in m["jobs"]["kinds"]:
        assert k["ephemeral"] == (k["kind"] in P.EPHEMERAL_KINDS)
        base = P.persist_dest_base(k["kind"])
        assert k["persist_to"] == (os.path.relpath(base, store.data_home()) if base else None)


def test_universe_limits_books_paths(m):
    assert m["universe"]["data"]["assets"] == [a["symbol"] for a in store.list_assets() if a.get("instrument") == "perp"]
    for key, path in (("book", store.alpha_file("book")), ("explore", store.alpha_dir("explore", "book.json"))):
        b = store.read_json(path)
        assert m["universe"][key] == (b["universe"] if b else [])
    lim = m["limits"]["funnel_run"]["seed"]
    sch = optimize.FunnelRunRequest.model_json_schema()["properties"]["seed"]
    assert (lim["minimum"], lim["maximum"], lim["default"]) == (sch["minimum"], sch["maximum"], sch["default"])
    cap = m["limits"]["live_bot"]["capital"]
    assert cap["exclusiveMinimum"] == 0 and cap["maximum"] == live_routes.BotRequest.model_json_schema()["properties"]["capital"]["maximum"]
    for key, p in (("book", store.alpha_file("book")), ("explore_book", store.alpha_dir("explore", "book.json"))):
        assert m["paths"][key] == os.path.relpath(p, store.data_home())


def test_book_fix_parsed_from_book(m):
    for key, explore in (("main", False), ("explore", True)):
        st = m["books"][key]
        book = store.read_json(store.alpha_file("book") if key == "main" else store.alpha_dir("explore", "book.json"))
        if not st.get("needs_rebuild"):
            assert "fix" not in st
            continue
        src = registry.parse_book_source(book.get("source"))
        if src:
            f = st["fix"]
            assert f["action"] == "funnel_book" and f["run_id"] == src["run_id"] and f["endpoint"].endswith(f"/runs/{src['run_id']}/book")
            assert f["body"]["alpha_ids"] == [s["evidence"]["funnel_alpha_id"] for s in book["strategies"] if s["evidence"].get("funnel_alpha_id")]
            assert f["body"]["risk_per_trade_pct"] == book["risk_per_trade_pct"] and f["body"]["explore"] is explore
        else:
            assert st["fix"]["action"] == "book_build"


def test_book_source_roundtrip():
    s = registry.book_source("fr-1", None, "2026-10-08")
    assert registry.parse_book_source(s) == {"run_id": "fr-1", "wfa_job_id": None, "date": "2026-10-08"}
    assert registry.parse_book_source("book_build job x") is None


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
    from backend.optimize.process import tasks
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
    v0 = process_routes._build_meta()["version"]
    changed = {**metrics_mod.METRIC_DEFS, "sharpe": {**metrics_mod.METRIC_DEFS["sharpe"], "label_vi": "Sharpe (đổi)"}}
    monkeypatch.setattr(process_routes, "METRIC_DEFS", changed)
    assert process_routes._build_meta()["version"] != v0
