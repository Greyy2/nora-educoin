"""Thư viện chiến lược (core/analytics/strategy_doc.py, GET /api/studio/alphas/catalog): mỗi CHIẾN LƯỢC một mục (KEMA Long/Short, DCA Long/Short,
Sideway gộp hai chiều), công thức dựng từ cây khuôn của engine nên mọi tham số ngưỡng của cây đều có mặt trong công thức."""
import json

from backend import strategies as sd


def _params(tree):
    out = set()
    for block in tree or []:
        for c in block:
            for x in (c[0], c[2]):
                s = json.dumps(x)
                out.update(p.split('"')[0] for p in s.split('"param": "')[1:])
    return out


def test_one_entry_per_strategy_not_per_alpha(tmp_path):
    cat = sd.catalog(str(tmp_path))
    src = cat["sources"][0]
    assert src["key"] == "nora"
    keys = [s["key"] for s in src["strategies"]]
    assert keys == ["kema_long", "kema_short", "sideway", "dca_long", "dca_short"]
    sw = next(s for s in src["strategies"] if s["key"] == "sideway")
    assert sw["side"] == "Long + Short" and sum(m["title"].endswith("Vào lệnh") for m in sw["math"]) == 2
    for s in src["strategies"]:
        assert s["idea"] and s["plain"] and s["math"] and s["stats"] == []          # thư mục rỗng -> chưa có alpha
        for m in s["math"]:
            assert m["latex"].isascii()


def test_formula_mirrors_engine_template_and_wording():
    from backend.strategies import BY_ID
    for cid in ("kema_long", "dca_short", "sideway_long"):
        c = BY_ID[cid]
        d = sd.leg_doc(c)
        tex = " ".join(m["latex"] for m in d["math"])
        for p in _params(c.get("tree")) | _params(c.get("dca_gate")) | _params(c.get("stop")):
            assert sd.psym(p) in tex, (cid, p)
    k = sd.leg_doc(BY_ID["kema_long"])
    assert k["plain"][0] == "Vào Long khi giá đóng cửa cắt lên trên EMA + hệ số dải trên × ATR."
    g = sd.leg_doc(BY_ID["dca_long"])
    assert any("Chỉ dồn khi" in x and "(tuỳ chọn, mặc định tắt)" in x for x in g["plain"])
    assert sd.psym("rsi_lo") == r"\theta^{\mathrm{RSI}}_{\mathrm{lo}}" and sd.psym("gate_er_max") == r"\theta^{\mathrm{ER}}_{\mathrm{gate}}"
    assert sd.psym("k_up") == r"k_{\mathrm{up}}" and sd.psym("ema_n") == "n"


def test_stats_gather_alphas_of_all_timeframes(tmp_path):
    ev = lambda r: {"funnel_alpha_id": "a" * 16, "stage_metrics": {"FINAL": {"ret_pct": r, "mdd_pct": 1.0, "sharpe": 2.0, "trades": 10}}}  # noqa: E731
    (tmp_path / "explore").mkdir()
    (tmp_path / "book.json").write_text(json.dumps({"timeframe": "1h", "strategies": [{"id": "dca_long", "side": "LONG", "evidence": ev(5.0)}]}))
    (tmp_path / "explore" / "book.json").write_text(json.dumps({"timeframe": "15m", "strategies": [{"id": "dca_long", "side": "LONG", "evidence": ev(7.0)}]}))
    st = {s["key"]: s for s in sd.catalog(str(tmp_path))["sources"][0]["strategies"]}
    assert [(a["timeframe"], a["book"], a["ret_pct"]) for a in st["dca_long"]["stats"]] == [("1h", "main", 5.0), ("15m", "explore", 7.0)]
    assert st["dca_short"]["stats"] == []


def test_catalog_router():
    from backend.routes import alpha
    assert alpha.get_alpha_catalog()["sources"][0]["label"] == "Nora"


def test_summary_is_performance_not_parameters():
    rows = [{"ret_pct": 10.0, "mdd_pct": 1.0, "win_rate": 80.0, "trades": 100, "sharpe": 5.0},
            {"ret_pct": 30.0, "mdd_pct": 3.0, "win_rate": 60.0, "trades": 50, "sharpe": 7.0}]
    m = sd.summarize(rows)
    assert m == {"n": 2, "ret_pct": 20.0, "mdd_pct": 3.0, "win_rate": 70.0, "trades": 150, "sharpe": 6.0}
    assert sd.summarize([]) == {"n": 0}


def test_combined_sides_use_pm_and_valid_commands(tmp_path):
    sw = next(s for s in sd.catalog(str(tmp_path))["sources"][0]["strategies"] if s["key"] == "sideway")
    tex = sw["math"][2]["latex"]
    assert r"1\mp s_L" in tex and r"1\pm s_T" in tex and r"\mps" not in tex
