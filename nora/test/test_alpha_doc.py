"""Tài liệu hoá alpha (core/analytics/alpha_doc.py + GET /api/studio/alphas/catalog): ý tưởng + công thức LaTeX dựng từ cấu trúc ĐÃ materialize.

Kiểm: dựng được mọi alpha của sổ hiện có, công thức chứa đúng tham số thật, bỏ điều kiện hằng đúng, OR / index 1 / calculate, router.
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import alphas as alphas_router
from backend.core.analytics import alpha_doc as ad
from backend.core.strategy.library import calc, cond, f

BOOK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "alphas")


@pytest.fixture(autouse=True)
def _no_jobs(monkeypatch):
    monkeypatch.setattr(ad, "_live_jobs", lambda: [])   # không đọc job thật của máy


def _book(kind="main"):
    path = os.path.join(BOOK_DIR, "book.json" if kind == "main" else os.path.join("explore", "book.json"))
    if not os.path.isfile(path):
        pytest.skip(f"chưa có {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sec(alpha, key):
    return next((s for s in alpha["formulas"] if s["key"] == key), None)


# ─── Dựng alpha thật của sổ ─────────────────────────────────────────────────
def test_render_every_alpha_of_both_books():
    for kind in ("main", "explore"):
        book = _book(kind)
        for item in book["strategies"]:
            a = ad.render_alpha(item, book, kind)
            assert a["id"] == item["id"] and a["book"] == kind and a["idea"]
            keys = [s["key"] for s in a["formulas"]]
            assert keys[0] == "indicators" and "entry" in keys and "position" in keys and "sizing" in keys and "portfolio" in keys
            for s in a["formulas"]:
                assert s["title"] and s["latex"] and s["latex"].isascii(), (a["id"], s["key"])   # chữ Việt chỉ ở tiêu đề / ghi chú
                assert s["latex"].count("{") == s["latex"].count("}")
            assert "sova" not in json.dumps(a, ensure_ascii=False).lower()


def test_dca_long_formulas_carry_real_parameters():
    book = _book("main")
    item = next(s for s in book["strategies"] if s["id"] == "dca_long")
    a = ad.render_alpha(item, book)
    p = item["params"]
    ind = _sec(a, "indicators")["latex"]
    assert rf"\mathrm{{RSI}}^{{\mathrm{{1h}}}}_{{{p['sig.rsi_n']}}}" in ind
    assert rf"_{{{p['sig.bb_n']},{p['sig.bb_k']}}}" in ind
    assert rf"\mathrm{{ER}}^{{\mathrm{{{p['sig.regime_tf']}}}}}_{{{p['sig.er_n']}}}" in ind
    assert rf"\mathrm{{NATR}}^{{\mathrm{{{p['atr_frame']}}}}}_{{{p['atr_period']}}}" in ind
    entry = _sec(a, "entry")
    assert r"<\ 28" in entry["latex"] and r"<\ 0.4" in entry["latex"] and r"\land" in entry["latex"]
    assert f"{p['cooldown']} phút" in entry["note"]
    gate = _sec(a, "dca_gate")["latex"]
    assert r"<\ 0.75" in gate and r"<\ 49" in gate and "101" not in gate           # rsi < 101 = ngưỡng tắt -> bỏ
    lad = _sec(a, "dca_ladder")["latex"]
    assert "3.75" in lad and "1.6" in lad and "k=1,\\dots,4" in lad and "0.05" in lad
    pos = _sec(a, "position")["latex"]
    for v in ("4.1", "5.85", "2.4", str(p["timeout"])):
        assert v in pos
    sz = _sec(a, "sizing")["latex"]
    assert "r=1.5" in sz and "c=490" in sz and "f=0.05" in sz and r"\min\left(7," in sz
    port = _sec(a, "portfolio")["latex"]
    assert "30\\%" in port and "6\\%" in port and "5\\%" in port
    st = a["stats"]
    assert st["stage"] == "FINAL" and st["trades"] == item["evidence"]["stage_metrics"]["FINAL"]["trades"]
    assert a["strategy"] == "dca" and a["alpha_id"] == item["evidence"]["funnel_alpha_id"]
    assert a["deploy"]["label"] == "Demo OKX + paper"


def test_kema_long_has_exit_signal_and_no_ladder():
    book = _book("main")
    item = next(s for s in book["strategies"] if s["id"] == "kema_long")
    a = ad.render_alpha(item, book)
    assert _sec(a, "dca_ladder") is None and _sec(a, "dca_gate") is None
    entry = _sec(a, "entry")
    assert "t-1" in entry["latex"] and "4.6" in entry["latex"] and "crossover" in entry["note"]
    assert "3.2" in _sec(a, "exit_signal")["latex"]
    assert a["strategy_label"] == "Kênh Keltner (KEMA)" and a["label"].startswith("Kênh Keltner (KEMA)")


def test_explore_dca_short_gate_drops_off_placeholder_and_deploy_label():
    book = _book("explore")
    item = next(s for s in book["strategies"] if s["id"] == "dca_short")
    a = ad.render_alpha(item, book, "explore")
    gate = _sec(a, "dca_gate")["latex"]
    assert "RSI" not in gate and "-1" not in gate and "0.15" in gate and "46" in gate
    assert a["deploy"]["label"] == "Paper (thử nghiệm)" and a["status"] == "EXPLORE_DEMO"
    assert "+" in _sec(a, "dca_ladder")["latex"]   # short: dồn khi giá TĂNG


def test_stats_fallback_to_latest_stage():
    item = {"evidence": {"stage_reached": "S3_wfa", "stage_metrics": {"S1_backtest": {"ret_pct": 1.0, "trades": 3}, "S3_wfa": {"ret_pct": 2.0, "sharpe": 1.5}}}}
    st = ad.stage_stats(item)
    assert st["stage"] == "S3_wfa" and st["ret_pct"] == 2.0 and st["stage_reached"] == "S3_wfa" and st["trades"] is None


def test_deploy_info_reads_running_bots_of_the_book_only():
    jobs = [{"kind": "live_bot", "status": "running", "params": {"mode": "demo", "book": "main"}},
            {"kind": "live_bot", "status": "done", "params": {"mode": "paper", "book": "main"}},
            {"kind": "live_bot", "status": "running", "params": {"mode": "paper", "book": "explore"}}]
    assert ad.deploy_info("main", jobs)["running_modes"] == ["demo"]
    assert ad.deploy_info("explore", jobs)["running_modes"] == ["paper"]


# ─── Cây điều kiện tổng hợp ─────────────────────────────────────────────────
def test_or_nesting_index1_and_add_calculate():
    up = {**f("4h", "ema_30"), "add": calc(f("4h", "atr_14"), "*", 2.0)}
    lag = {**f("4h", "ema_30", 1), "add": calc(f("4h", "atr_14", 1), "*", 2.0)}
    tree = [[[f("4h", "close"), ">", up], [f("4h", "close", 1), "<=", lag]], [[f("1h", "rsi_14"), "<", 20]]]
    out = ad.render_tree(tree)
    x = out["latex"]
    assert r"\lor" in x and r"\land" in x and "t-1" in x
    assert r"\mathrm{EMA}^{\mathrm{4h}}_{30}(t)+\mathrm{ATR}^{\mathrm{4h}}_{14}(t)\cdot 2" in x
    assert out["conditions"] == 3 and out["events"] == 1 and not out["always"]


def test_arithmetic_precedence_subtract_divide_and_minmax():
    sub = {**f("1h", "close"), "subtract": calc(f("1h", "atr_14"), "+", 1.0)}
    ratio = {"type": "calculate", "number_1": f("1h", "close"), "logic": "/", "number_2": f("1h", "sma_20")}
    mixed = {"type": "calculate", "number_1": calc(f("1h", "atr_14"), "+", 1.0), "logic": "*", "number_2": 2.0}
    assert r"-\left(" in ad.operand(sub)[0]
    assert r"\frac{C^{\mathrm{1h}}(t)}{\mathrm{SMA}^{\mathrm{1h}}_{20}(t)}" == ad.operand(ratio)[0]
    assert ad.operand(mixed)[0].startswith(r"\left(")        # (a + 1)·2: tổng nằm trong nhân phải có ngoặc
    assert ad.operand({"type": "max", "numbers": [f("1h", "close"), 3]})[0].startswith(r"\max\left(")


def test_tautologies_are_dropped_but_real_thresholds_stay():
    tri = lambda col, op, v: [f("1h", col), op, v]
    assert ad.is_tautology(tri("rsi_7", "<", 101)) and ad.is_tautology(tri("rsi_7", ">", -1))
    assert ad.is_tautology(tri("er_20", "<=", 1)) and ad.is_tautology(tri("adx_14", ">=", 0))
    assert ad.is_tautology([101, ">", f("1h", "rsi_7")])           # hằng ở vế trái
    assert not ad.is_tautology(tri("rsi_7", "<", 100)) and not ad.is_tautology(tri("rsi_7", "<", 30))
    assert not ad.is_tautology(tri("ema_20", "<", 101))              # chỉ báo không bị chặn
    assert not ad.is_tautology([{**f("1h", "rsi_7"), "add": 1}, "<", 101])   # có cộng/trừ -> không kết luận
    out = ad.render_tree(cond(tri("er_20", "<", 0.4), tri("rsi_7", "<", 101)))
    assert out["dropped"] == 1 and out["conditions"] == 1 and "RSI" not in out["latex"]
    allt = ad.render_tree(cond(tri("rsi_7", "<", 101)))
    assert allt["always"] and allt["latex"] == "1"


def test_every_kernel_has_definition_and_symbol():
    from backend.core.signals.kernels import REGISTRY
    for name, spec in REGISTRY.items():
        p = tuple(spec.defaults)
        lines = ad.definition(name, p, "1h")
        assert lines and all(x.isascii() for x in lines), name
        assert ad.symbol(name, p, "1h").isascii()


# ─── Router ─────────────────────────────────────────────────────────────────
def test_catalog_endpoint_has_nora_source_first():
    app = FastAPI()
    app.include_router(alphas_router.router)
    r = TestClient(app).get("/api/studio/alphas/catalog")
    assert r.status_code == 200
    j = r.json()
    assert j["sources"][0]["key"] == "nora" and j["sources"][0]["label"] == "Nora"
    alphas = j["sources"][0]["alphas"]
    if os.path.isfile(os.path.join(BOOK_DIR, "book.json")):
        assert alphas and alphas[0]["book"] == "main"
        books = [a["book"] for a in alphas]
        assert books == sorted(books, key=lambda b: 0 if b == "main" else 1)   # sổ chính trước
        assert "main" in j["sources"][0]["books"]


def test_catalog_with_no_books_returns_empty_source(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(tmp_path))
    monkeypatch.setenv("NORA_BOOK_PATH", str(tmp_path / "book.json"))
    out = ad.catalog()
    assert out["sources"][0]["key"] == "nora" and out["sources"][0]["alphas"] == []
