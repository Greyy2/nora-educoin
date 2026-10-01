"""
test_capital_ledger.py — A1 + A5: phân bổ vốn và kế toán phải chính xác tới từng cent.

A1  Bất biến kiểm ở MỌI nến, trên nhiều kịch bản ngẫu nhiên (nhiều flow, DCA, spot/perp,
    phí maker/taker, funding):
      reserved == Σ reserved_here của các flow;  reserved <= equity × usage;  không over-allocate;
      spot: vốn mark-to-market không âm.
    Cuối kỳ: vốn = vốn đầu + Σ lãi/lỗ ròng các lệnh (đã gồm phí và funding).
A5  Đối chiếu ĐỘC LẬP: tính lại lãi/lỗ từng lệnh chỉ từ danh sách lệnh con (giá, khối lượng, phí
    từng lệnh) + funding, so với con số engine báo.
    Phí từng lệnh phải đúng loại: vào ở open / SL / trailing / timeout = taker; DCA / chốt lời = maker.
"""
import numpy as np
import pandas as pd
import pytest

from backend.backtest.engine import BacktestEngine
from backend.backtest.params_builder import build_params
from backend.db.models import OrderType, PositionType

T0 = 1_700_006_400_000
M = 60_000


def _df(n, seed, drift=0.0, vol=0.002):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": open_,
                         "high": np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n))),
                         "low": np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n))),
                         "close": close, "volume": 1.0})


def _build(df, flows, capital=10000.0, funding=None):
    eng = BacktestEngine(0, 0, "T", int(df.open_time.min()), int(df.open_time.max()), initial_capital=capital)
    for i, (side, tree, pos) in enumerate(flows):
        name = f"{side}_{i}"
        params = build_params(name, {"match": [{"condition": tree}], "stop": []}, side, {**pos, "order_size_pct": 1.0}, "cex")
        params.order_size_pct = float(pos.get("order_size_pct", 100.0))   # bỏ qua kiểm tra ngân sách DCA có chủ đích:
        eng.add_strategy_flow(name, params)                               # test này ép sổ vốn xử lý cả tầng DCA bị từ chối
    eng.df_1m = eng._prepare_candles(df)
    tmp = df.assign(dt=pd.to_datetime(df.open_time, unit="ms", utc=True)).set_index("dt")
    agg = tmp.resample("240min", closed="left", label="left").agg(
        {"open_time": "first", "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    agg["open_time"] = (agg.index.asi8 // 10**6).astype("int64")
    eng.frames["4h"] = eng._prepare_candles(agg.reset_index(drop=True))
    eng.df_4h = eng.frames["4h"]
    eng.funding = funding
    return eng


def _random_flow(rng, market):
    side = "SHORT" if market == "perp" and rng.random() < 0.5 else "LONG"
    tree = [[[{"frame": "1m", "column": "rsi_7"}, "<" if side == "LONG" else ">",
              float(rng.uniform(25, 45) if side == "LONG" else rng.uniform(55, 75))]]]
    pos = {
        "market": market,
        "leverage": float(rng.choice([1, 3, 10])) if market == "perp" else 1.0,
        "order_size_pct": float(rng.choice([20, 40, 60, 100])),
        "dca_step_pct": float(rng.choice([0, 0.2, 0.5])),
        "dca_max_layers": int(rng.integers(0, 4)),
        "dca_size_multiplier": float(rng.choice([0.8, 1.0, 2.0])),
        "take_profit_rate": float(rng.choice([0, 0.3, 1.0])),
        "stop_loss_rate": float(rng.choice([0, 0.8, 3.0])),
        "trailing_stop": float(rng.choice([0, 0.5])),
        "timeout": int(rng.choice([0, 30, 240])),
    }
    return side, tree, pos


SCENARIOS = [(seed, market) for seed in range(12) for market in ("spot", "perp")]


@pytest.mark.parametrize("seed,market", SCENARIOS)
def test_ledger_invariants_every_bar_random_multi_flow(seed, market):
    rng = np.random.default_rng(seed)
    df = _df(2500, seed, drift=float(rng.normal(0, 0.0003)))
    flows = [_random_flow(rng, market) for _ in range(int(rng.integers(2, 4)))]
    funding = None
    if market == "perp":
        ft = T0 + np.arange(1, 6) * 480 * M  # mỗi 8 giờ
        funding = pd.DataFrame({"funding_time": ft, "rate": rng.normal(0.0001, 0.0003, len(ft))})
    eng = _build(df, flows, funding=funding)
    violations = []

    def hook(engine, t):
        led = engine.ledger
        held = sum(tr.reserved_here for tr in engine.trackers)
        if abs(led.reserved - held) > 1e-6:
            violations.append(("reserved != Σ", t, led.reserved, held))
        # Funding (perp) trừ vào vốn khi ký quỹ vẫn khoá -> phần vượt chỉ được bằng funding đã trả của lệnh mở
        funding_open = sum(max(tr.funding_paid, 0.0) for tr in engine.trackers if tr.is_open)
        if led.reserved > led.equity * led.usage + funding_open + 1e-6 and led.equity > 0:
            violations.append(("over-allocated", t, led.reserved, led.equity))
        for tr in engine.trackers:
            if tr.is_open and tr.margin_used + tr.fees_paid > tr.reserved_here + 1e-6:
                violations.append(("tracker uses more than reserved", t))

    eng.bar_hook = hook
    eng.run()
    assert not violations, violations[:5]
    total = sum(p.real_pnl for p in eng.closed_positions)
    assert eng.ledger.equity == pytest.approx(10000.0 + total, abs=1e-6)
    assert eng.ledger.reserved == pytest.approx(0.0, abs=1e-9)
    if market == "spot":
        assert min(pt["equity_worst"] for pt in eng.equity_curve) > -1e-6


@pytest.mark.parametrize("seed,market", SCENARIOS[:12])
def test_pnl_recomputed_independently_from_orders(seed, market):
    """A5: lãi/lỗ = Σ (giá thoát − giá khớp từng tầng) × khối lượng × chiều − Σ phí từng lệnh − funding."""
    rng = np.random.default_rng(100 + seed)
    df = _df(2500, 100 + seed)
    flows = [_random_flow(rng, market) for _ in range(2)]
    funding = None
    if market == "perp":
        ft = T0 + np.arange(1, 6) * 480 * M
        funding = pd.DataFrame({"funding_time": ft, "rate": rng.normal(0.0001, 0.0003, len(ft))})
    eng = _build(df, flows, funding=funding)
    eng.run()
    orders = {}
    for o in eng.orders:
        orders.setdefault(o.position_id, []).append(o)
    assert eng.closed_positions
    for pos in eng.closed_positions:
        legs = sorted(orders[pos.result_id], key=lambda o: o.order_id)
        sign = 1.0 if pos.pos_type == PositionType.LONG else -1.0
        entry_side = OrderType.BUY if sign > 0 else OrderType.SELL
        fills = [o for o in legs if o.order_type == entry_side]
        exit_leg = [o for o in legs if o.order_type != entry_side]
        assert len(exit_leg) == 1 and len(fills) == pos.layers
        qty = sum(o.qty for o in fills)
        assert qty == pytest.approx(pos.qty, rel=1e-12)
        avg = sum(o.qty * o.order_price for o in fills) / qty
        assert avg == pytest.approx(pos.avg_price, rel=1e-12)
        gross = sum(sign * (exit_leg[0].order_price - o.order_price) * o.qty for o in fills)
        fees = sum(o.fee_usd for o in legs)
        assert fees == pytest.approx(pos.fees_usd, rel=1e-12, abs=1e-12)
        if int(pos.status) != 5:  # thanh lý: lỗ bị chặn ở ký quỹ
            assert gross - fees - pos.funding_usd == pytest.approx(pos.real_pnl, rel=1e-9, abs=1e-9)
        # Loại phí đúng theo loại lệnh
        assert fills[0].liquidity == "taker"
        assert all(o.liquidity == "maker" for o in fills[1:])
        tp_exit = pos.close_reason.startswith("Take-profit")
        assert exit_leg[0].liquidity == ("maker" if tp_exit else ("liquidation" if int(pos.status) == 5 else "taker"))


def test_two_flows_cannot_over_allocate_capital():
    """Lỗi cũ: mỗi flow định cỡ 100% vốn -> 2 flow cùng lúc dùng 200%."""
    df = _df(300, 1)
    signal = [[[{"frame": "1m", "column": "open_time"}, "==", int(df.open_time[10])]]]
    pos = {"market": "spot", "order_size_pct": 100.0, "fee_rate": 0.0, "maker_fee_rate": 0.0}
    eng = _build(df, [("LONG", signal, pos), ("LONG", signal, pos)])
    eng.run()
    opened = [p for p in eng.closed_positions if p.enter_time == int(df.open_time[11])]
    assert len(opened) == 1 and eng.ledger.rejected >= 1


def test_funding_paid_by_long_received_by_short():
    df = _df(2000, 3, vol=0.0005)
    signal = [[[{"frame": "1m", "column": "open_time"}, "==", int(df.open_time[5])]]]
    ft = np.array([T0 + 480 * M, T0 + 960 * M], dtype="int64")
    funding = pd.DataFrame({"funding_time": ft, "rate": [0.001, 0.002]})
    base = {"market": "perp", "leverage": 5.0, "order_size_pct": 20.0}
    for side, sign in (("LONG", 1.0), ("SHORT", -1.0)):
        eng = _build(df, [(side, signal, base)], funding=funding)
        eng.run()
        pos = eng.closed_positions[0]
        idx = [int(np.searchsorted(df.open_time.to_numpy(), t)) for t in ft]
        expected = sum(pos.qty * float(df.open.iloc[i]) * r for i, r in zip(idx, [0.001, 0.002])) * sign
        assert pos.funding_usd == pytest.approx(expected, rel=1e-9)
        assert eng.ledger.equity == pytest.approx(10000.0 + pos.real_pnl, abs=1e-6)
