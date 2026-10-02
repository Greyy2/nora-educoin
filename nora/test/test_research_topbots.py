"""research_topbots: parse BOTS từ okx-report.html, ánh xạ tham số bot -> Nora, và một lần chạy tổng hợp nhỏ.

Kiểm:
- parse `const BOTS` (JSON thật) và các bot được chọn có đủ trường p/v;
- chốt lời % ký quỹ -> % giá = tp / đòn bẩy; ngân sách DCA hợp lệ (dca_budget_check) cho MỌI tầng;
- số tầng bị giảm đúng khi ngân sách engine không cho (martingale đòn bẩy cao);
- hàm đo lường (hợp các khoảng, MDD MTM gồm lỗ treo, thời điểm cháy);
- một lần chạy PortfolioEngine trên dữ liệu tổng hợp: tất định, không SL thì stop_fill không đổi kết quả.
"""
import os

import numpy as np
import pandas as pd
import pytest

from backend.cli import research_topbots as rt
from backend.core.backtest.params_builder import dca_budget_check, resolve_costs
from backend.core.data.resampler import save_resampled_dataset

COSTS = resolve_costs("cex", "perp", None, None)
HTML = rt.BOTS_HTML
needs_html = pytest.mark.skipif(not os.path.isfile(HTML), reason="thiếu okx-report.html")
AVAIL = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]


@pytest.fixture(scope="module")
def bots():
    return {b["name"]: b for b in rt.parse_bots(HTML)}


@needs_html
def test_parse_bots_reads_json_and_selected_bots_have_params(bots):
    assert len(bots) >= 28
    for name in rt.SELECTED:
        b = bots[name]
        assert b["grp"] == "Trade" and b["p"]["top_syms"] and b["v"]["lev"] and b["v"]["tp"] > 0
    m = bots["maomao12345"]
    assert m["v"]["spacing"] == 0.32 and m["v"]["stack"] == 58 and m["v"]["tp"] == 48.1 and m["p"]["lev_med"] == 30.0


def test_tp_margin_to_price():
    assert rt.tp_price_pct(48.1, 30) == pytest.approx(1.60333, rel=1e-4)
    assert rt.tp_price_pct(18.2, 10) == pytest.approx(1.82)
    assert rt.tp_price_pct(274.0, 50) == pytest.approx(5.48)
    assert rt.tp_price_pct(5.0, 0.5) == pytest.approx(5.0)   # đòn bẩy < 1 coi như 1


@needs_html
def test_map_maomao_full_stack_fits_budget(bots):
    s = rt.map_bot(bots["maomao12345"], AVAIL, COSTS)
    assert s["layers"] == 57 and not s["layers_capped"] and s["sides"] == ["LONG"]
    assert s["symbols"] == ["ETH", "DOGE", "BTC"] and s["tp_price_pct"] == pytest.approx(1.6033, rel=1e-3)
    pos = {"market": "perp", "leverage": s["leverage"], "order_size_pct": s["order_size_pct_per_side"],
           "dca_step_pct": s["step_pct"], "dca_max_layers": s["layers"], "dca_size_multiplier": s["size_mult"]}
    chk = dca_budget_check(pos, COSTS)
    assert chk["ok"] and chk["layers"] == 57
    # lớn nhất: tăng thêm 1% thì vượt trần
    assert not dca_budget_check({**pos, "order_size_pct": s["order_size_pct_per_side"] * 1.01}, COSTS)["ok"]
    assert s["sl2span_beyond_liq"] and s["sl_control_pct"] < s["liq_dist_pct"]   # SL 2×span nằm sau giá thanh lý


@needs_html
def test_map_sides_and_missing_symbols(bots):
    hw = rt.map_bot(bots["好望角9999"], AVAIL, COSTS)
    assert hw["sides"] == ["SHORT"] and hw["momentum_mode"] == "counter"
    assert hw["symbols"] == ["ETH"] and set(hw["symbols_missing"]) == {"ONE", "ZEC"}
    xj = rt.map_bot(bots["xiaojian888999"], AVAIL, COSTS)
    assert xj["sides"] == ["LONG", "SHORT"] and xj["layers"] == 9
    assert xj["order_size_pct_per_side"] <= xj["max_order_size_pct"] / 2 + 1e-9    # hai chiều chia đôi ngân sách
    bm = rt.map_bot(bots["BestMax"], AVAIL, COSTS)
    assert bm["symbols"] == ["SOL"] and bm["layers"] == 24 and bm["leverage"] == 20.0
    sc = rt.map_bot(bots["星火研究院-大象"], AVAIL, COSTS)   # lướt ngắn Binance: không DCA
    assert sc["layers"] == 0 and sc["tp_price_pct"] == pytest.approx(1.4 / 8) and sc["sl2span_pct"] == 0


@needs_html
def test_martingale_budget_forces_tiny_first_layer(bots):
    s = rt.map_bot(bots["Shallow-Pair-Frog"], AVAIL, COSTS)
    assert s["size_mult"] == 1.98 and s["layers"] == 11 and s["order_size_pct_per_side"] < 0.05


def test_feasible_layers_caps_when_budget_impossible():
    n, mx = rt.feasible_layers(50.0, 0.5, 40, 2.0, COSTS)       # 2^40 lần ký quỹ: không thể
    assert n < 40 and mx >= rt.MIN_ORDER_SIZE_PCT
    assert dca_budget_check({"market": "perp", "leverage": 50.0, "order_size_pct": mx, "dca_max_layers": n,
                             "dca_step_pct": 0.5, "dca_size_multiplier": 2.0}, COSTS)["ok"]
    assert dca_budget_check({"market": "perp", "leverage": 50.0, "order_size_pct": mx, "dca_max_layers": n + 1,
                             "dca_step_pct": 0.5, "dca_size_multiplier": 2.0}, COSTS)["max_order_size_pct"] < rt.MIN_ORDER_SIZE_PCT
    assert rt.feasible_layers(10.0, 1.0, 5, 1.0, COSTS)[0] == 5      # khả thi thì giữ nguyên
    assert rt.feasible_layers(10.0, 0.0, 0, 1.0, COSTS)[0] == 0


def test_union_and_curve_stats():
    assert rt._union_ms([(0, 10), (5, 20), (30, 40)]) == 30
    assert rt._union_ms([]) == 0
    h = 3_600_000
    t = np.arange(0, 6) * h
    eq = np.array([10000, 12000, 12000, 6000, 900, 900.0])
    worst = np.array([10000, 11000, 9000, 5000, 800, 800.0])
    cs = rt.curve_stats(rt.hourly_frame(t, eq, worst), 0)
    assert cs["mdd_pct"] == pytest.approx((1.2 - 0.08) / 1.2 * 100)       # đỉnh MTM 12000 -> đáy 800
    assert cs["min_equity_pct"] == pytest.approx(8.0)
    assert cs["ruin_days"] == pytest.approx(4 / 24)                      # worst <= 10% lần đầu ở giờ thứ 4


# ─── Chạy tổng hợp nhỏ ──────────────────────────────────────────────────────
T0 = 1_700_006_400_000
M = 60_000
DAY = 86_400_000


@pytest.fixture
def market(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    n = 30 * 1440
    rng = np.random.default_rng(7)
    r = rng.normal(0, 0.0012, n)
    r[1:] -= 0.15 * r[:-1]
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": o,
                       "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995, "close": c, "volume": 10.0})
    end = int(df.open_time.max())
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    save_resampled_dataset(symbol="AAA", output_dir=str(root / "cex"), df_1m_raw=df, pool_address="s", crawl_ok=True,
                           requested_start_ts=T0, requested_end_ts=end, extra_meta=meta)
    save_resampled_dataset(symbol="perp", output_dir=str(root / "cex" / "AAA"), df_1m_raw=df, pool_address="p",
                           crawl_ok=True, requested_start_ts=T0, requested_end_ts=end,
                           extra_meta={**meta, "exchange": "binance_usdm", "market": "perp"})
    ft = T0 + np.arange(1, 30 * 3) * 8 * 3_600_000
    pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001}).to_pickle(root / "cex" / "AAA" / "perp" / "funding.pkl")
    return end


def _spec(**kw):
    s = {"name": "synthetic", "leverage": 20.0, "step_pct": 0.5, "layers": 6, "size_mult": 1.0, "tp_price_pct": 0.4,
         "sides": ["LONG"], "order_size_pct_per_side": 10.0, "momentum_mode": "neutral", "sl_control_pct": 1.0,
         "sl2span_pct": 6.0}
    s.update(kw)
    return s


def test_synthetic_run_is_deterministic_and_stop_fill_irrelevant_without_sl(market):
    end = market
    start, ts = T0, T0 + 5 * DAY
    runs = {}
    for fill in ("extreme", "level"):
        runs[fill] = rt.run_config("AAA@perp", rt.build_strategies(_spec(), "reentry", 0.0, fill), start, ts, end)
    again = rt.run_config("AAA@perp", rt.build_strategies(_spec(), "reentry", 0.0, "extreme"), start, ts, end)
    a, b = runs["extreme"], runs["level"]
    assert a["trades"] > 10 and 0 <= a["win_rate"] <= 100 and a["max_layers"] >= 1
    assert 0 < a["time_open_pct"] <= 100 and a["mdd_pct"] >= 0 and a["mae_max_pct"] >= 0
    for k in ("trades", "wins", "ret_pct", "mdd_pct", "n_liq", "max_layers", "pf"):
        assert a[k] == b[k] == again[k]                               # tất định; không SL -> stop_fill không đổi gì
    assert a["trades"] == a["wins"] + a["losses"]
    # đối chứng có SL: không thanh lý ở 20x vì SL 1% < khoảng thanh lý 4,5%; có lệnh bị cắt
    sl = rt.run_config("AAA@perp", rt.build_strategies(_spec(), "reentry", 1.0, "extreme"), start, ts, end)
    assert sl["n_liq"] == 0 and sl["trades"] >= a["trades"]
    agg = rt.aggregate([a, sl], ts, end)
    assert agg["trades"] == a["trades"] + sl["trades"] and agg["n_assets"] == 2
    assert agg["daily"] and agg["mdd_pct"] >= 0


def test_two_sided_and_reversion_strategies_build(market):
    st = rt.build_strategies(_spec(sides=["LONG", "SHORT"], order_size_pct_per_side=5.0), "reversion", 0.0, "extreme")
    assert [s["side"] for s in st] == ["LONG", "SHORT"] and len({s["id"] for s in st}) == 2
    assert all(s["position"]["stop_loss_rate"] == 0.0 and s["position"]["timeout"] == 0 for s in st)
    assert st[0]["tree"] != st[1]["tree"]
    cnt = rt.build_strategies(_spec(sides=["SHORT"], momentum_mode="counter"), "reentry", 0.0, "extreme")
    assert any(t[0]["column"] == "roc_24" for t in cnt[0]["tree"][0] if isinstance(t[0], dict))
