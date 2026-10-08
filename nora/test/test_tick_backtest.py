"""Backtest THEO TICK cho DEX (không gọi mạng): chi phí AMM đúng toán, hai móc tuỳ chọn của tracker, thứ tự TP/SL trong một nến, thời điểm giao tín hiệu,
cửa sổ tick, từ chối (chân SHORT, thiếu tick, trộn perp + DEX), get_book assets, và một lần chạy đầu-cuối qua run_job trên dữ liệu DEX giả lập.

Tick giả: mỗi tick đặt dự trữ sao cho giá biên = mid mong muốn (reserve_base cố định, reserve_quote = mid × reserve_base) -> mọi lệnh có trượt giá tính được bằng tay."""
import json

import numpy as np
import pandas as pd
import pytest

from backend.core import backtest as dex
from backend.crawl.store import require_perp
from backend.crawl.store import save_resampled_dataset, write_parquet_atomic
from data_helpers import patch_meta
from backend.crawl.dex import pool_info
from backend.core.models import PositionType
from backend.core.backtest import PositionTracker
from backend.core.params import build_params
from backend.crawl.dex import TICK_COLUMNS

T0 = 1_700_006_400_000                 # 00:00 UTC, chia hết cho mọi khung
MIN, F15, DAY = 60_000, 900_000, 86_400_000
W = T0 + 60 * DAY                      # đầu cửa sổ tick giả (60 ngày sau đầu nến)
RB, FEE, GAS = 1_000_000.0, 0.003, 0.02    # dự trữ token gốc cố định, phí pool, gas mỗi swap của tick giả
CAPITAL = 10_000.0


# ─── dữ liệu giả ────────────────────────────────────────────────────────────
def _candles(days, seed=5, vol=0.0008):
    n = days * 1440
    r = np.random.default_rng(seed).normal(0.00002, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * MIN, "open": o, "high": np.maximum(o, c) * (1 + vol / 3),
                         "low": np.minimum(o, c) * (1 - vol / 3), "close": c, "volume": 10.0})


def _asset(root, name, venue="dex", days=62, ticks=None, **meta):
    df = _candles(days)
    out = root / venue
    save_resampled_dataset(symbol=name, output_dir=str(out), df_1m_raw=df, pool_address="0xpool", crawl_ok=True, requested_start_ts=T0,
                           requested_end_ts=int(df.open_time.max()), extra_meta={"venue": venue, "checksums_verified": True, "exchange": "geckoterminal", **({"network": "base"} if venue == "dex" else {}), **meta})
    d = out / name
    onchain = {"pool_address": "0xpool", "fee_rate": FEE, "stable": False, "pool_type": "aerodrome_v2"} if venue == "dex" else None
    if ticks is not None:   # metadata ticks/onchain nằm trong attrs của ticks.parquet
        tick_meta = {"source": "evm_swaps", "synthetic": False, "start_ts": int(ticks.timestamp_ms.iloc[0]), "end_ts": int(ticks.timestamp_ms.iloc[-1]),
                     "rows": len(ticks), "window_days": 3, "network": "base", "fee_rate": FEE, "stable": False, "pool_type": "aerodrome_v2"}
        write_parquet_atomic(ticks.copy(), str(d / "ticks.parquet"), {"ticks": tick_meta, "onchain": onchain})
    elif onchain:           # chưa có tick: onchain nằm trong attrs nến
        patch_meta(str(d), onchain=onchain)
    return d


def mk_ticks(points, rb=RB):
    """points = [(timestamp_ms, mid USD)] -> bảng tick đủ cột; giá khớp = mid × (1 + phí), dự trữ cho giá biên đúng bằng mid."""
    ts = np.array([p[0] for p in points], dtype=np.int64)
    mid = np.array([p[1] for p in points], dtype=float)
    n = len(ts)
    return pd.DataFrame({"timestamp_ms": ts, "block_number": np.arange(n, dtype=np.int64), "log_index": 0, "tx_hash": [f"0x{i}:0" for i in range(n)],
                         "price": mid * (1 + FEE), "mid_price": mid, "amount": 1.0, "volume_usd": mid * (1 + FEE), "side": "buy",
                         "reserve_base": rb, "reserve_quote": mid * rb, "quote_usd": 1.0})[TICK_COLUMNS]


def path_ticks(path):
    """Giá phẳng 100 mỗi 30 giây suốt nến cơ sở đầu + 1 tick, rồi `path` (các mid, mỗi 30 giây), rồi giá cuối giữ phẳng mỗi phút tới hết 1 giờ."""
    pts = [(W + k * 30_000, 100.0) for k in range(33)]             # tới W+960s: tick thứ 32 là tick mở lệnh
    t = pts[-1][0]
    for mid in path:
        t += 30_000
        pts.append((t, mid))
    last = path[-1]
    pts += [(t + k * MIN, last) for k in range(1, int((W + 3600_000 - t) // MIN) + 1)]
    return mk_ticks(pts)


@pytest.fixture
def market(tmp_path, monkeypatch):
    """Gốc dữ liệu giả: DEX XYZ (nến 62 ngày + tick giả đặt sau mỗi test), DEX NOTICK (không tick), CEX AAA có perp; chiến lược t_long / t_cyc / t_short."""
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    from backend.optimize.book import build as sb
    from backend.alpha.compile import cond, f
    pos = {"exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 50, "stop_loss_rate": 2.0, "take_profit_rate": 2.0}
    monkeypatch.setattr(sb, "CANDIDATES", [
        {"id": "t_long", "family": "x", "side": "LONG", "description": "luôn khớp", "tree": cond((f("15m", "close"), ">", 0)),
         "position": {**pos, "cooldown": 100_000}, "space": {}},                       # chỉ một lệnh (cooldown dài) -> kiểm thứ tự TP/SL
        {"id": "t_cyc", "family": "x", "side": "LONG", "description": "vào lại liên tục", "tree": cond((f("15m", "close"), ">", 0)),
         "position": {**pos, "cooldown": 15}, "space": {}},
        {"id": "t_short", "family": "x", "side": "SHORT", "description": "bán khống", "tree": cond((f("15m", "close"), ">", 0)),
         "position": pos, "space": {}}])
    _asset(root, "NOTICK")
    _asset(root, "AAA", venue="cex")
    save_resampled_dataset(symbol="perp", output_dir=str(root / "cex" / "AAA"), df_1m_raw=_candles(5), pool_address="x", crawl_ok=True,
                           extra_meta={"venue": "cex", "checksums_verified": True, "exchange": "binance_usdm", "market": "perp"})
    return root


def _xyz(root, ticks):
    return _asset(root, "XYZ", ticks=ticks)


def _run(items, ticks_df, root, **kw):
    from backend.optimize.search.evaluate import run_tick
    from backend.core.params import RISK
    _xyz(root, ticks_df)
    args = dict(start=None, end=None, rpt=0.5, risk=RISK, stop_fill="level", base_frame="15m", capital=CAPITAL)
    args.update(kw)
    return run_tick(items, ["dex:XYZ"], args.pop("start"), args.pop("end"), args.pop("rpt"), args.pop("risk"), args.pop("stop_fill"), args.pop("base_frame"),
                    args.pop("capital"), **args)


# ─── AMM: toán đúng ─────────────────────────────────────────────────────────
def test_amm_volatile_impact_is_exact_constant_product():
    rb, rq, qu, fee = 2_000_000.0, 3_000_000.0, 2.0, 0.003              # quote có giá 2 USD -> dự trữ quote 6 triệu USD
    n = 25_000.0
    buy, sell = dex.amm_price_impact(n, True, rb, rq, qu, fee, False), dex.amm_price_impact(n, False, rb, rq, qu, fee, False)
    e = n / qu * (1 - fee)                                              # quote đưa vào pool sau phí
    assert buy == pytest.approx(e / rq, rel=1e-12)                      # mua: Δ(1-f) / R_quote
    mid = rq / rb
    a = n / (mid * qu) * (1 - fee)                                      # base bán, sau phí
    assert sell == pytest.approx(a / (rb + a), rel=1e-12)               # bán: A(1-f) / (R_base + A(1-f))
    out = dex.amm_amount_out(n / qu, rq, rb, fee, False)
    assert out == pytest.approx(rb * e / (rq + e), rel=1e-12)
    assert (rq + e) * (rb - out) == pytest.approx(rq * rb, rel=1e-12)   # x*y=k giữ nguyên (trên phần đã trừ phí)
    assert dex.amm_price_impact(n, True, rb, rq, qu, 0.0, False) > buy      # bỏ phí khỏi đầu vào thì trượt giá lớn hơn một chút: phí không nằm trong impact


def test_amm_impact_adds_gas_and_validates_state():
    m = dex.AmmImpact(FEE, False, GAS)
    with pytest.raises(ValueError):
        m.set_state(0.0, 1.0, 1.0)
    m.set_state(RB, 100 * RB, 1.0)
    n = 1_000.0
    assert m(n, True) == pytest.approx(dex.amm_price_impact(n, True, RB, 100 * RB, 1.0, FEE, False) + GAS / n)
    assert m(0.0, True) == 0.0
    with pytest.raises(ValueError):
        dex.AmmImpact(1.0, False)


def test_amm_stable_pool_solves_invariant_and_slips_less_than_volatile():
    rb = rq = 5_000_000.0
    fee = 0.0005
    for spend in (1_000.0, 100_000.0, 1_000_000.0):
        out = dex.amm_amount_out(spend, rq, rb, fee, True)
        e = spend * (1 - fee)
        assert dex._stable_k(rq + e, rb - out) == pytest.approx(dex._stable_k(rq, rb), rel=1e-12)    # x³y+xy³ = k
    small, big = dex.amm_price_impact(1_000.0, True, rb, rq, 1.0, fee, True), dex.amm_price_impact(1_000_000.0, True, rb, rq, 1.0, fee, True)
    vol = dex.amm_price_impact(1_000_000.0, True, rb, rq, 1.0, fee, False)
    assert 0 < small < big < vol                                          # stable cân bằng gần giá 1:1 trượt ít hơn x*y=k, tăng theo khối lượng
    assert dex.amm_price_impact(1_000_000.0, False, rb, rq, 1.0, fee, True) > 0


def test_pool_info_refuses_null_fee_and_reads_sources(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    d = _asset(root, "NOFEE")
    patch_meta(str(d), onchain={"fee_rate": None, "stable": False, "pool_type": "aerodrome_v2"})
    with pytest.raises(ValueError, match="phí pool"):
        pool_info("dex:NOFEE")
    d = _asset(root, "WITHFEE")
    info = pool_info("WITHFEE")
    assert info["fee_rate"] == FEE and info["fee_source"].startswith("dex_pool.json") and info["pool_type"] == "aerodrome_v2" and info["ticks"] is None


# ─── tracker: móc tuỳ chọn ──────────────────────────────────────────────────
def _tracker(**kw):
    pos = {"market": "spot", "leverage": 1, "stop_loss_rate": 2.0, "take_profit_rate": 4.0, "order_size_pct": 40, "sizing": "margin_pct", "exit_unit": "pct",
           "dca_steps": [1.0], "dca_multipliers": [1.0], "fee_rate": 0.003, "maker_fee_rate": 0.001, "slippage_rate": 0.001, "limit_through_pct": 0.0}
    params = build_params("L", {"type": "LONG", "match": [], "stop": [], "dca": []}, "LONG", {**pos, **kw.pop("pos", {})}, "dex")
    return PositionTracker(1, 1, "X", "L", params, PositionType.LONG, initial_capital=CAPITAL, **kw)


def _drive(tr):
    """vào ở open 100 (market), DCA khi giá nhảy xuống 99 (gap qua mức DCA 99.099: limit chờ sẵn khớp ở MỨC; limit_taker/AMM khớp ở 99), rồi giá nhảy lên 5% trên giá TB (gap qua mức TP 4%: limit khớp ở mức TP)."""
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False)
    tr.on_bar(1, 100, 100, 100, 100, entry_signal=False, stop_signal=False)
    tr.on_bar(2, 99, 99, 99, 99, entry_signal=False, stop_signal=False)
    avg = tr.avg
    pos = tr.on_bar(3, avg * 1.05, avg * 1.05, avg * 1.05, avg * 1.05, entry_signal=False, stop_signal=False)
    return pos, tr.orders, avg


def test_tracker_defaults_keep_maker_limit_fills():
    pos, orders, avg = _drive(_tracker())
    assert [o.liquidity for o in orders] == ["taker", "maker", "maker"]                 # vào market; DCA + TP là limit (maker)
    assert orders[0].order_price == pytest.approx(100 * 1.001) and orders[1].order_price == pytest.approx(100.1 * 0.99) and pos.close_price == pytest.approx(avg * 1.04)   # TP limit khớp ở MỨC (4%), không ở open gap 5%
    assert [o.slippage for o in orders] == [0.001, 0.0, 0.0]
    assert orders[1].fee_usd == pytest.approx(orders[1].qty * 100.1 * 0.99 * 0.001)


def test_tracker_limit_taker_and_impact_fn_charge_taker_fee_and_impact():
    seen = []

    def impact(n, buy):
        seen.append((n, buy))
        return 0.01
    pos, orders, avg = _drive(_tracker(limit_taker=True, impact_fn=impact))
    assert [o.liquidity for o in orders] == ["taker"] * 3
    assert all(o.slippage == 0.01 for o in orders)                                      # impact_fn thay slippage_rate ở MỌI lệnh (vào, DCA, TP)
    assert orders[0].order_price == pytest.approx(100 * 1.01) and orders[1].order_price == pytest.approx(99.0 * 1.01)
    assert orders[1].fee_usd == pytest.approx(orders[1].qty * orders[1].order_price * 0.003)    # phí taker, không phải maker
    assert pos.close_price == pytest.approx(avg * 1.05 * 0.99)                           # chốt lời = swap bán ở giá hiện tại trừ trượt giá
    assert [b for _, b in seen] == [True, True, False]                                   # mua (vào), mua (DCA), bán (đóng)
    assert pos.fees_usd == pytest.approx(sum(o.fee_usd for o in orders))


def test_tracker_risk_sizing_uses_impact_on_planned_notional():
    kw = dict(pos={"sizing": "risk", "risk_per_trade_pct": 1.0, "max_notional_pct": 1000.0, "dca_steps": [], "dca_multipliers": []})
    base, flat, big = _tracker(**kw), _tracker(**kw, impact_fn=lambda n, b: 0.001), _tracker(**kw, impact_fn=lambda n, b: 0.02)
    sizes = []
    for tr in (base, flat, big):
        tr._apply_exit_unit(1.0)
        sizes.append(tr._risk_margin())
    assert sizes[1] == pytest.approx(sizes[0])                  # impact hằng = slippage_rate cũ -> cùng khối lượng
    assert sizes[2] < sizes[0]                                  # trượt giá lớn hơn -> chi phí khứ hồi lớn hơn -> khối lượng nhỏ hơn
    deep = _tracker(**kw, impact_fn=lambda notional, b: 0.001 + 1e-6 * notional)
    deep._apply_exit_unit(1.0)
    assert deep._risk_margin() < sizes[1]                       # trượt giá tăng theo khối lượng được tính trên khối lượng dự kiến


def test_kernel_refuses_trackers_with_amm_hooks():
    from backend.core.backtest import pack_slots
    with pytest.raises(ValueError, match="limit_taker"):
        pack_slots([_tracker(limit_taker=True)])
    pack_slots([_tracker()])


# ─── tín hiệu: thời điểm giao + cổng nến không có swap ─────────────────────
def _fake_signals(match, stop, traded, latency=2_000, nb=None):
    from backend.optimize.search.evaluate import _Signals
    s = _Signals.__new__(_Signals)
    s.v = {"t": np.arange(len(match)) * F15 + W, "entries": [{"match": np.array(match), "stop": np.array(stop), "vol": None, "dca": None}]}
    s.i0, s.nb, s.w, s.frame_ms, s.latency = 0, nb or len(match), W, F15, latency
    s.traded = np.array(traded)
    s.last, s.ignored_no_trade, s.skipped = -1, 0, 0
    s.held = [{"match": False, "stop": False, "vol": None, "dca": True}]
    return s


def test_signal_delivered_at_first_tick_after_bar_close_plus_latency():
    s = _fake_signals([True, False, False], [False, False, False], [True, True, True])
    assert not s.at(W + F15 - 1)[0]["match"]                 # nến 0 chưa đóng
    assert not s.at(W + F15 + 1_999)[0]["match"]             # đã đóng nhưng chưa đủ latency
    assert s.at(W + F15 + 2_000)[0]["match"] is True          # tick đầu tiên >= đóng + latency
    assert s.at(W + F15 + 2_030)[0]["match"] is False         # chỉ giao MỘT lần; giữa hai lần đóng nến: match = stop = False
    assert s.held[0]["dca"] is True and s.skipped == 0


def test_entry_from_bar_without_swaps_is_ignored_and_stop_survives_skipped_bars():
    s = _fake_signals([False, True, False], [False, False, False], [True, False, True])
    assert not s.at(W + 2 * F15 + 2_000)[0]["match"]         # nến 1 không có swap nào: tín hiệu vào bị bỏ
    assert s.ignored_no_trade == 1 and s.skipped == 1       # tick đầu tiên đã nằm sau đóng nến 1 -> chỉ thấy nến 1 mới nhất, nến 0 bị bỏ qua (không tick ở giữa)
    s = _fake_signals([False, True, False], [True, False, False], [True, False, True])
    out = s.at(W + 2 * F15 + 2_000)[0]                       # nến 0 (stop) và nến 1 (match, không swap) cùng đã đóng khi có tick
    assert out["stop"] is True and out["match"] is False and s.ignored_no_trade == 1


# ─── thứ tự trong một nến: điều duy nhất nến không biết ─────────────────────
ITEMS = [("t_long", {})]


def _entry_notional_and_fill():
    m = dex.AmmImpact(FEE, False, GAS)
    m.set_state(RB, 100.0 * RB, 1.0)
    margin = CAPITAL * 0.5
    return margin, 100.0 * (1 + m(margin, True))


def test_tp_crossed_before_sl_in_same_bar_is_take_profit_and_reverse_is_stop_loss(market):
    up_first = _run(ITEMS, path_ticks([100.5, 101.0, 102.5, 97.0]), market)       # cùng một nến 15m: high 102.5, low 97 — chỉ thứ tự khác
    down_first = _run(ITEMS, path_ticks([99.0, 98.5, 97.0, 102.5]), market)
    a, b = up_first["trade_list"], down_first["trade_list"]
    assert len(a) == len(b) == 1
    assert a[0]["status"] == "TP" and b[0]["status"] == "SL"
    assert a[0]["close_price"] == pytest.approx(102.5, rel=2e-3) and a[0]["pnl"] > 0
    assert b[0]["close_price"] == pytest.approx(97.0, rel=2e-3) and b[0]["pnl"] < 0
    assert up_first["config"]["data"] == "tick" and up_first["ret_pct"] > 0 > down_first["ret_pct"]


def test_entry_opens_on_swap_after_the_delivery_tick_and_costs_follow_the_pool(market):
    res = _run(ITEMS, path_ticks([100.0, 100.0]), market)
    t = res["trade_list"][0]
    # nến 0 đóng ở W+900s; latency mặc định = block_ms của mạng (2000) -> giao ở tick W+930s; mở ở tick kế (W+960s)
    assert t["enter_time"] == W + 960_000 and res["config"]["latency_ms"] == 2_000
    margin, fill = _entry_notional_and_fill()
    assert t["enter_price"] == pytest.approx(fill, rel=1e-9) and t["notional"] == pytest.approx(margin, rel=1e-3)
    res2 = _run(ITEMS, path_ticks([100.0, 100.0]), market, latency_ms=45_000)       # trễ hơn: giao ở tick đầu >= W+945s = W+960s, mở ở W+990s
    assert res2["trade_list"][0]["enter_time"] == W + 990_000 and res2["config"]["latency_ms"] == 45_000
    st = res["tick_stats"]
    assert st["taker_fills"] == 2 and st["avg_fill_slippage_bps"] > 0                # vào + thoát cuối cửa sổ, đều là swap taker có trượt giá
    assert res["config"]["cost_model"]["pools"]["XYZ"]["fee_rate"] == FEE and res["config"]["cost_model"]["pools"]["XYZ"]["gas_usd"] == 0.02
    assert res["trade_list"][0]["fees_usd"] > 0 and res["equity_curve"][-1]["time"] >= W + 3_600_000 - F15


def test_window_is_clamped_to_tick_coverage_and_aligned_to_base_bar(market):
    ticks = path_ticks([100.0, 100.0])
    first, last = int(ticks.timestamp_ms.iloc[0]) + 7 * MIN, int(ticks.timestamp_ms.iloc[-1])      # đầu lệch mốc nến 15m
    ticks = ticks.assign(timestamp_ms=ticks.timestamp_ms + 7 * MIN)
    res = _run(ITEMS, ticks, market, start=W - 5 * DAY, end=W + 30 * DAY)
    win = res["config"]["tick_window"]
    assert win["start"] == W + F15 and win["start"] % F15 == 0                      # làm tròn LÊN mốc nến cơ sở kế tiếp
    assert win["end"] == last + 7 * MIN and win["requested_start"] == W - 5 * DAY
    assert res["config"]["start"] == win["start"] and res["config"]["end"] == win["end"]
    infos = [{"symbol": "XYZ", "ticks": {"start_ts": first, "end_ts": first + 10 * MIN}}]
    with pytest.raises(ValueError, match="ngắn hơn một nến cơ sở"):
        dex.tick_window(infos, None, None, F15)


# ─── từ chối ────────────────────────────────────────────────────────────────
def test_short_leg_and_both_sides_are_rejected_with_vietnamese_message(market):
    with pytest.raises(ValueError, match="chỉ chạy chân LONG"):
        _run([("t_long", {}), ("t_short", {})], path_ticks([100.0, 100.0]), market)
    with pytest.raises(ValueError, match="chỉ chạy chân LONG"):
        from backend.optimize.search.evaluate import run
        run([("t_short", {})], ["dex:NOTICK"], W, W + DAY, 0.5, "level", {}, base_frame="15m", venue="dex")


def test_tick_mode_requires_ticks_and_dex_and_no_mixing(market):
    from backend.optimize.process import process as batch
    from backend.routes import jobs as batch_routes
    base = {"start": "2023-12-10", "end": "2023-12-12", "timeframe": "15m", "strategies": [{"id": "t_long", "params": {}}]}
    _xyz(market, path_ticks([100.0, 100.0]))
    ok = batch_routes.build_job("book_backtest", {**base, "symbols": ["XYZ"], "data": "candle"})
    assert ok["symbols"] == ["dex:XYZ"] and "data" not in ok
    with pytest.raises(batch.JobError, match="chưa có tick"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["dex:NOTICK"], "data": "tick"})
    with pytest.raises(batch.JobError, match="chạy chung"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["BTC", "dex:XYZ"]})
    with pytest.raises(batch.JobError, match="chỉ dành cho tài sản DEX"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["BTC"], "data": "tick"})
    with pytest.raises(batch.JobError, match="chân LONG"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["XYZ"], "strategies": [{"id": "t_short", "params": {}}]})
    with pytest.raises(batch.JobError, match="chọn chiến lược"):
        batch_routes.build_job("book_backtest", {k: v for k, v in base.items() if k != "strategies"} | {"symbols": ["XYZ"]})
    with pytest.raises(batch.JobError, match="không có tài sản DEX"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["dex:ZZZ"]})
    day = "2023-11-14"                                          # trước đầu tick giả (W = đầu ngày thứ 60 sau T0 = 2024-01-13): cửa sổ ngoài độ phủ
    with pytest.raises(batch.JobError, match="ngắn hơn một nến cơ sở"):
        batch_routes.build_job("book_backtest", {**base, "symbols": ["XYZ"], "data": "tick", "start": day, "end": "2023-11-15"})
    t = batch_routes.build_job("book_backtest", {**base, "symbols": ["XYZ"], "data": "tick", "start": "2024-01-13", "end": "2024-01-14", "latency_ms": 500, "gas_usd": 0.1})
    assert t["data"] == "tick" and t["latency_ms"] == 500 and t["gas_usd"] == 0.1


def test_wfa_and_funnel_reject_dex_symbols(market):
    from backend.optimize.process import process as batch
    from backend.routes import jobs as batch_routes
    _xyz(market, path_ticks([100.0, 100.0]))
    with pytest.raises(batch.JobError, match="WFA / phễu chưa hỗ trợ"):
        batch_routes.check_symbols(["dex:XYZ"])
    with pytest.raises(batch.JobError, match="WFA / phễu chưa hỗ trợ"):
        batch_routes.build_job("book_wfa", {"candidates": ["t_long"], "symbols": ["XYZ"]})
    with pytest.raises(ValueError, match="WFA chưa hỗ trợ tài sản DEX"):
        from backend.optimize.process.tasks import run_book_wfa as wfa_job
        wfa_job({"candidates": "t_long", "symbols": "dex:XYZ"})
    with pytest.raises(ValueError, match="chưa hỗ trợ tài sản DEX"):
        require_perp(["AAA", "dex:XYZ"], "Phễu")
    require_perp(["AAA"], "Phễu")


def test_run_job_rejects_mixing_and_tick_on_perp(market):
    from backend.optimize.process.tasks import run_book_backtest as run_job
    with pytest.raises(ValueError, match="chạy chung"):
        run_job({"strategies": [{"id": "t_long"}], "symbols": "AAA,dex:NOTICK", "start": "2024-01-01", "end": "2024-01-02"})
    with pytest.raises(ValueError, match="chỉ dành cho tài sản DEX"):
        run_job({"strategies": [{"id": "t_long"}], "symbols": "AAA@perp", "data": "tick"})


# ─── API: danh sách tài sản ─────────────────────────────────────────────────
def test_get_book_lists_assets_with_candle_and_tick_coverage(market):
    from backend.routes.book import get_book
    ticks = path_ticks([100.0, 100.0])
    _xyz(market, ticks)
    body = get_book()
    assets = {a["symbol"]: a for a in body["assets"]}
    x = assets["XYZ"]
    assert x["venue"] == "dex" and x["market"] == "spot" and x["network"] == "base" and x["fee_rate"] == FEE
    assert x["ticks"] == {"start_ts": int(ticks.timestamp_ms.iloc[0]), "end_ts": int(ticks.timestamp_ms.iloc[-1]), "rows": len(ticks), "window_days": 3}
    assert x["candles"]["start_ts"] == T0 and x["candles"]["end_ts"] > T0
    assert assets["NOTICK"]["ticks"] is None and assets["NOTICK"]["venue"] == "dex"
    assert assets["AAA@perp"]["venue"] == "cex" and assets["AAA@perp"]["market"] == "perp" and assets["AAA@perp"]["ticks"] is None
    assert "universe" in body                                   # universe giữ nguyên


# ─── đầu-cuối qua run_job ───────────────────────────────────────────────────
STD_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "by_symbol", "by_strategy", "daily", "halted_at", "rejected_for_risk",
            "trade_list", "equity_curve", "daily_nav", "config", "final_equity", "meta")


def _cyc_ticks():
    rng = np.random.default_rng(3)
    mid = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 4 * 96)))                  # bước ngẫu nhiên: 384 tick, mỗi 150 giây (~16 giờ, ~64 nến 15m)
    return mk_ticks([(W + k * 150_000, float(m)) for k, m in enumerate(mid)])


def test_run_job_tick_end_to_end_schema_and_candle_mode_for_dex(market, tmp_path, monkeypatch):
    from backend.optimize.process.tasks import run_book_backtest as run_job
    monkeypatch.setenv("NORA_JOB_DIR", str(tmp_path / "job"))
    _xyz(market, _cyc_ticks())
    out = run_job({"strategies": [{"id": "t_cyc"}], "symbols": "XYZ", "data": "tick", "timeframe": "15m", "out": str(tmp_path / "o.json")})
    saved = json.loads((tmp_path / "job" / "result.json").read_text())
    for k in STD_KEYS:
        assert k in saved, k
    assert saved["trades"] == len(saved["trade_list"]) >= 2 and saved["config"]["data"] == "tick" and saved["config"]["venue"] == "dex"
    assert saved["config"]["symbols"] == ["XYZ"] and all(t["symbol"] == "XYZ" and t["side"] == "LONG" for t in saved["trade_list"])
    assert set(saved["by_symbol"]) == {"XYZ"} and saved["config"]["tick_window"]["start"] == W
    assert saved["equity_curve"] and saved["equity_curve"][0]["equity_worst"] <= saved["equity_curve"][0]["equity"] + 1e-9
    assert out["final_equity"] == pytest.approx(CAPITAL * (1 + out["ret_pct"] / 100), abs=1.0)
    again = run_job({"strategies": [{"id": "t_cyc"}], "symbols": "dex:XYZ", "data": "tick", "timeframe": "15m"})
    assert [t["pnl"] for t in again["trade_list"]] == [t["pnl"] for t in saved["trade_list"]]      # tất định
    # chế độ nến cho DEX: cùng engine với perp, spot LONG-only, phí pool từ manifest
    c = run_job({"strategies": [{"id": "t_cyc"}], "symbols": "XYZ", "start": "2023-12-20", "end": "2024-01-05", "timeframe": "15m"})
    assert c["trades"] > 0 and c["config"]["venue"] == "dex" and c["config"]["data"] == "candle" and c["config"]["symbols"] == ["XYZ"]
    assert all(t["side"] == "LONG" and t["symbol"] == "XYZ" and t["leverage"] == 1.0 for t in c["trade_list"])
    one = [t for t in c["trade_list"] if t["layers"] == 1]
    assert one and all(t["fees_usd"] == pytest.approx(2 * FEE * t["notional"], rel=0.03) for t in one)      # phí pool 0,3% mỗi chiều (manifest), không phải mặc định
    with pytest.raises(ValueError, match="chỉ chạy chân LONG"):
        run_job({"strategies": [{"id": "t_short"}], "symbols": "XYZ", "start": "2023-12-20", "end": "2024-01-05", "timeframe": "15m"})
