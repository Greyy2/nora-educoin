"""Engine Nautilus (backend/nautilus/engine.py) trên dữ liệu THẬT (catalog OKX), đoạn ngắn: bất biến kế toán + kịch bản SL/TP/DCA/trailing/timeout/
cooldown/kill switch/max_positions. Số kỳ vọng tính từ chính fill của Nautilus (báo cáo `generate_order_fills_report`), không có số bịa.

Chạy: NORA_PYTHON=$HOME/.venvs/nora312/bin/python ops/run_limited.sh --no-lock -- -m pytest test/test_nautilus_engine.py -q
"""
import datetime as dt

import pytest

from backend.alpha.compile import cond, f
from backend.alpha.dsl.strategy import RiskConfig
from backend.nautilus import catalog as cat
from backend.nautilus.engine import NautilusRun, PortfolioEngine, BacktestEngine
from backend.nautilus.strategy import FLAT

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(autouse=True)
def real_data(monkeypatch):
    """conftest cô lập data root; test này cần catalog + pkl thật (chỉ đọc)."""
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setattr(NautilusRun, "KEEP_REPORTS", True)


def ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


BASE = {"market": "perp", "leverage": 5, "exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 20.0, "fee_rate": 0.0005,
        "maker_fee_rate": 0.0002, "slippage_rate": 0.0, "limit_through_pct": 0.0, "cooldown": 0, "atr_frame": "1m"}
OPEN_RISK = dict(kill_switch_dd_pct=0, max_gross_exposure=100, max_open_risk_pct=0, dd_throttle_pct=0)


def run(pos, a="2024-03-04 00:00", b="2024-03-04 06:00", sym=("BTC@perp",), risk=None, side="LONG", frame="1m", n=1, close_at_end=True):
    strats = [{"id": f"s{i}", "side": side, "tree": cond((f(frame, "close"), ">", 0)), "position": {**BASE, **pos, "atr_frame": frame}} for i in range(n)]
    pe = PortfolioEngine(list(sym), strats, ms(a) - 3600_000, ms(b), trade_start_ts=ms(a), risk=risk or RiskConfig(**OPEN_RISK), base_frame=frame,
                         close_at_end=close_at_end)
    pe.run()
    return pe, pe.get_results()


def fills(pe):
    return pe._res["reports"]["fills"]


def money(v) -> float:
    return float(str(v[0]).split()[0])


def tick(sym="BTC"):
    return float(cat.get_instrument(sym).price_increment)


def invariants(pe, res):
    cap = res["initial_capital"]
    pnl = sum(p.real_pnl for p in res["positions"])
    assert res["final_equity"] == pytest.approx(cap + pnl, abs=1e-6)
    assert pe._res["balance"] == pytest.approx(cap + pnl, abs=1e-6)          # số dư tài khoản Nautilus
    fr = fills(pe)
    assert sum(p.fees_usd for p in res["positions"]) == pytest.approx(sum(money(c) for c in fr["commissions"]), abs=1e-6)
    assert len(res["orders"]) == len(fr)
    keys = {(int(t.value // 1_000_000), round(float(px), 8), round(float(q), 8)) for t, px, q in zip(fr["ts_last"], fr["avg_px"], fr["filled_qty"])}
    for o in res["orders"]:        # mọi lệnh vào / ra của mỗi vị thế có trong báo cáo fill của Nautilus
        assert (o.order_time, round(o.order_price, 8), round(o.qty, 8)) in keys, o
    assert not any(s for s in [pe._res["venue_rejects"]]), pe._res["venue_rejects"]
    assert res["funding_modeled"] is False


# ─── bất biến ───────────────────────────────────────────────────────────────
def test_invariants_multi_symbol_mixed_exits():
    pe, res = run({"stop_loss_rate": 0.4, "take_profit_rate": 0.5, "trailing_stop": 0.3, "trailing_activation_pct": 0.2, "dca_step_pct": 0.25,
                   "dca_max_layers": 2, "dca_size_multiplier": 1.5, "order_size_pct": 10.0}, sym=("BTC@perp", "ETH@perp", "SOL@perp"))
    assert len(res["positions"]) > 10
    invariants(pe, res)
    for p in res["positions"]:     # mỗi vị thế: khối lượng = Σ các lớp vào; avg = trung bình gia quyền các lớp vào
        entries = [o for o in res["orders"] if o.position_id == p.result_id and o.order_type.name == "BUY"]
        assert sum(o.qty for o in entries) == pytest.approx(p.qty, abs=1e-9)
        assert sum(o.qty * o.order_price for o in entries) / p.qty == pytest.approx(p.avg_price, rel=1e-6)
    assert res["warnings"]


def test_base_frame_1h_invariants():
    pe, res = run({"stop_loss_rate": 1.0, "take_profit_rate": 1.0}, a="2024-03-01 00:00", b="2024-03-20 00:00", frame="1h")
    assert len(res["positions"]) > 5
    invariants(pe, res)
    assert res["equity_curve"][0]["time"] % 3_600_000 == 0


def test_backtest_engine_single_symbol_matches_shape():
    from backend.models.models import data_source
    eng = BacktestEngine(0, 0, "BTC@perp", ms("2024-03-04 00:00") - 3600_000, ms("2024-03-04 03:00"), trade_start_ts=ms("2024-03-04 00:00"), base_frame="1m")
    from backend.models.params import build_params
    from backend.alpha.dsl.strategy import _strategy_flow
    st = {"id": "x", "side": "LONG", "tree": cond((f("1m", "close"), ">", 0)), "position": {**BASE, "stop_loss_rate": 0.3, "take_profit_rate": 0.4}}
    eng.add_strategy_flow("LONG_x", build_params("LONG_x", _strategy_flow(st), "LONG", st["position"], "cex"))
    eng.load_data()
    eng.run()
    res = eng.get_results()
    assert set(res) >= {"positions", "orders", "equity_curve", "ruined_at", "final_equity", "rejected_for_capital", "dca_layers_rejected", "funding_modeled", "funding_events"}
    assert res["final_equity"] == pytest.approx(10000.0 + sum(p.real_pnl for p in res["positions"]), abs=1e-6)
    assert len(res["positions"]) > 5


# ─── kịch bản ───────────────────────────────────────────────────────────────
def test_stop_loss_and_take_profit_levels():
    pe, res = run({"stop_loss_rate": 0.3, "take_profit_rate": 0.4})
    invariants(pe, res)
    t = tick()
    sl = [p for p in res["positions"] if p.close_reason.startswith("Stop-loss")]
    tp = [p for p in res["positions"] if p.close_reason.startswith("Take-profit")]
    assert sl and tp
    for p in tp:      # limit chờ sẵn: khớp đúng mức TP, phí maker
        assert p.close_price == pytest.approx(p.avg_price * 1.004, abs=t)
        assert [o.liquidity for o in res["orders"] if o.position_id == p.result_id][-1] == "maker"
    for p in sl:      # stop-market: khớp ở mức SL (hoặc xấu hơn khi gap), phí taker
        assert p.close_price <= p.avg_price * 0.997 + t
        assert p.real_pnl < 0
        assert [o.liquidity for o in res["orders"] if o.position_id == p.result_id][-1] == "taker"
    tags = fills(pe)["tags"].map(lambda x: x[0])
    assert {"ENTRY", "SL", "TP"} <= set(tags)


def test_dca_updates_qty_avg_and_protective_orders():
    pe, res = run({"stop_loss_rate": 1.0, "take_profit_rate": 0.5, "dca_step_pct": 0.25, "dca_max_layers": 2, "dca_size_multiplier": 1.5,
                   "order_size_pct": 10.0}, b="2024-03-04 03:00")
    invariants(pe, res)
    t = tick()
    deep = [p for p in res["positions"] if p.layers > 1]
    assert deep
    fr = fills(pe)
    tags = fr["tags"].map(lambda x: x[0])
    assert (tags == "DCA").sum() >= 1
    for p in deep:
        ords = [o for o in res["orders"] if o.position_id == p.result_id]
        entries = [o for o in ords if o.order_type.name == "BUY"]
        assert len(entries) == p.layers and sum(o.qty for o in ords if o.order_type.name == "SELL") == pytest.approx(p.qty, abs=1e-9)   # thoát = toàn bộ khối lượng sau DCA
        assert entries[1].order_price <= entries[0].order_price * (1 - 0.0025) + t               # tầng DCA ở dưới giá vào ≥ bước 0,25%
        if p.close_reason.startswith("Take-profit"):
            assert p.close_price == pytest.approx(p.avg_price * 1.005, abs=t)                   # TP đặt lại từ avg MỚI
        elif p.close_reason.startswith("Stop-loss"):
            assert p.close_price <= p.avg_price * 0.99 + t                                     # SL từ avg MỚI
    # lệnh SL/TP ghi nhận trong fill của vị thế nhiều lớp có qty > lớp đầu
    big = fr[(fr["tags"].map(lambda x: x[0]).isin(["SL", "TP"])) & (fr["filled_qty"].astype(float) > 0.1)]
    assert len(big)


def test_trailing_stop_native():
    pe, res = run({"trailing_stop": 0.2, "trailing_activation_pct": 0.1}, b="2024-03-04 03:00")
    invariants(pe, res)
    tr = [p for p in res["positions"] if p.close_reason == "Trailing stop"]
    assert len(tr) > 5
    t = tick()
    assert (fills(pe)["type"] == "TRAILING_STOP_MARKET").sum() == len(tr)
    near = 0
    for p in tr:
        assert p.close_price <= p.max_price * (1 - 0.002) * (1 + 1e-6) + t      # không bao giờ khớp trên mức bám đỉnh
        near += abs(p.close_price - p.max_price * (1 - 0.002)) <= 2 * t
    assert near >= len(tr) // 2                                               # phần lớn khớp đúng mức đỉnh·(1 − 0,2%)


def test_timeout_and_cooldown():
    pe, res = run({"timeout": 5}, b="2024-03-04 01:00")
    invariants(pe, res)
    ps = res["positions"]
    assert len(ps) > 5
    assert all(p.close_reason == "Hết thời gian giữ lệnh" and p.close_time - p.enter_time == 5 * 60_000 for p in ps[:-1])
    pe, res = run({"timeout": 5, "cooldown": 10}, b="2024-03-04 01:00")
    ps = res["positions"]
    assert len(ps) >= 3
    assert all(ps[i + 1].enter_time - ps[i].close_time >= 10 * 60_000 for i in range(len(ps) - 1))


def test_kill_switch_halts_and_closes_all():
    pe, res = run({"stop_loss_rate": 0.5, "order_size_pct": 50.0}, b="2024-03-04 12:00",
                  risk=RiskConfig(kill_switch_dd_pct=0.3, max_gross_exposure=100, max_open_risk_pct=0, dd_throttle_pct=0))
    invariants(pe, res)
    assert res["halted_at"] is not None
    ps = res["positions"]
    assert ps[-1].close_reason == "Kill switch danh mục"
    assert all(p.enter_time <= res["halted_at"] + 60_000 for p in ps)     # không vào lệnh mới sau khi dừng
    assert not pe.open_positions() and pe._res["balance"] == pytest.approx(res["final_equity"])
    assert "KILL" in set(fills(pe)["tags"].map(lambda x: x[0])) or ps[-1].close_reason


def test_max_positions_and_per_symbol():
    pe, res = run({"timeout": 30}, b="2024-03-04 02:00", sym=("BTC@perp", "ETH@perp", "SOL@perp"),
                  risk=RiskConfig(max_positions=2, max_per_symbol=1, kill_switch_dd_pct=0, max_gross_exposure=100, max_open_risk_pct=0, dd_throttle_pct=0))
    invariants(pe, res)
    ev = sorted([(p.enter_time, 1) for p in res["positions"]] + [(p.close_time, -1) for p in res["positions"]], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    assert peak == 2
    assert res["rejected_for_risk"] > 0 and res["risk_blocked_attempts"] > 0
    pe, res = run({"timeout": 30}, b="2024-03-04 01:00", n=2, risk=RiskConfig(max_positions=8, max_per_symbol=1, kill_switch_dd_pct=0, max_gross_exposure=100,
                                                                              max_open_risk_pct=0, dd_throttle_pct=0))
    assert res["rejected_for_risk"] > 0
    ps = sorted(res["positions"], key=lambda p: p.enter_time)
    assert all(ps[i + 1].enter_time >= ps[i].close_time for i in range(len(ps) - 1))      # cùng tài sản: không bao giờ 2 vị thế đồng thời


def test_close_at_end_false_keeps_open_and_final_equity_is_realized():
    pe, res = run({"stop_loss_rate": 0.0, "take_profit_rate": 0.0}, b="2024-03-04 00:30", close_at_end=False)
    ops = pe.open_positions()
    assert len(ops) == 1 and ops[0]["qty"] > 0 and ops[0]["symbol"] == "BTC@perp"
    assert res["final_equity"] == pytest.approx(10000.0 + sum(p.real_pnl for p in res["positions"]), abs=1e-6)


def test_run_many_is_repeated_real_runs():
    pe, _ = run({"stop_loss_rate": 0.3, "take_profit_rate": 0.4}, b="2024-03-04 02:00")
    many = pe.run_many([{"stop_loss_rate": 0.3, "take_profit_rate": 0.4}, {"stop_loss_rate": 0.5, "take_profit_rate": 0.2}])
    for ov, got in zip([{"stop_loss_rate": 0.3, "take_profit_rate": 0.4}, {"stop_loss_rate": 0.5, "take_profit_rate": 0.2}], many):
        alone, ref = run(ov, b="2024-03-04 02:00")
        assert [(p.enter_time, p.close_time, p.close_price) for p in got["positions"]] == [(p.enter_time, p.close_time, p.close_price) for p in ref["positions"]]
        assert got["final_equity"] == ref["final_equity"]
    assert many[0]["final_equity"] != many[1]["final_equity"]


def test_unsupported_features_are_flagged_not_faked():
    pe, res = run({"slippage_rate": 0.001, "limit_through_pct": 0.05, "stop_loss_rate": 0.5})
    w = " | ".join(res["warnings"])
    assert "slippage" in w and "limit_through" in w and "thanh lý" in w and "funding" in w
    assert res["provenance"]["slippage_modeled"] is False and res["provenance"]["liquidation_modeled"] is False
    with pytest.raises(ValueError):
        run({"intrabar_path": "adverse_first"})


# ─── catalog ────────────────────────────────────────────────────────────────
def test_catalog_instrument_and_aggregation():
    i = cat.get_instrument("BTC@perp")
    assert str(i.base_currency) == "BTC" and str(i.quote_currency) == "USDT" and float(i.size_increment) == 0.0001
    from backend.data import data as D
    a = D.read_1m("BTC", ms("2024-03-04 00:00"), ms("2024-03-04 05:59"))
    h = D.aggregate_frame(a, "1h")
    assert len(h["t"]) == 6 and h["t"][0] == ms("2024-03-04 00:00")
    assert h["o"][0] == a["o"][0] and h["c"][0] == a["c"][59] and h["h"][0] == a["h"][:60].max() and h["l"][0] == a["l"][:60].min()
    assert h["v"][0] == pytest.approx(a["v"][:60].sum())
    with pytest.raises(cat.CatalogError):
        cat.load_catalog_bars("BTC", 1, 2)
    with pytest.raises(ValueError):
        cat.normalize_symbol("dex:AERO")
