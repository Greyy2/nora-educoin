"""Phân bổ vốn + phân bổ rủi ro: thoát lệnh theo ATR, khối lượng theo rủi ro, backtest danh mục chung sổ vốn.

Kiểm:
- exit_unit="atr": SL/TP/trailing = bội số ATR% của nến khung atr_frame ĐÃ ĐÓNG lúc có tín hiệu (nhân quả);
- sizing="risk": chạm SL mất đúng ~risk_per_trade_pct% vốn (gồm phí); đòn bẩy tự hạ để thanh lý xa SL;
- PortfolioEngine một tài sản = BacktestEngine (từng lệnh, từng đồng);
- danh mục nhiều tài sản: trần số vị thế, trần mỗi tài sản, trần tổng danh nghĩa, sổ vốn không vượt,
  lãi/lỗ quy về từng lệnh khớp đúng thay đổi vốn, kill switch đóng hết và ngừng giao dịch.
"""
import numpy as np
import pandas as pd
import pytest

from backend.core.data.resampler import save_resampled_dataset

T0 = 1_700_006_400_000
M = 60_000
DAY = 86_400_000


def _series(days, seed, vol):
    n = days * 1440
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol, n)
    r[1:] -= 0.15 * r[:-1]
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": o,
                         "high": np.maximum(o, c) * (1 + vol / 3), "low": np.minimum(o, c) * (1 - vol / 3),
                         "close": c, "volume": 10.0})


@pytest.fixture
def market(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    for k, (sym, vol) in enumerate((("AAA", 0.0008), ("BBB", 0.0016), ("CCC", 0.0030))):
        df = _series(40, 10 + k, vol)
        end = int(df.open_time.max())
        save_resampled_dataset(symbol=sym, output_dir=str(root / "cex"), df_1m_raw=df, pool_address="s", crawl_ok=True,
                               requested_start_ts=T0, requested_end_ts=end, extra_meta=meta)
        save_resampled_dataset(symbol="perp", output_dir=str(root / "cex" / sym), df_1m_raw=df, pool_address="p",
                               crawl_ok=True, requested_start_ts=T0, requested_end_ts=end,
                               extra_meta={**meta, "exchange": "binance_usdm", "market": "perp"})
        ft = T0 + np.arange(1, 40 * 3) * 8 * 3_600_000
        pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001 * (k + 1)}).to_pickle(
            root / "cex" / sym / "perp" / "funding.pkl")
    return root


def f(frame, column, index=0):
    return {"frame": frame, "column": column, "index": index}


POSITION = {"market": "perp", "leverage": 10, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14,
            "sizing": "risk", "risk_per_trade_pct": 1.0, "max_notional_pct": 300, "stop_loss_rate": 2.0,
            "take_profit_rate": 3.0, "trailing_stop": 1.5, "trailing_activation_pct": 1.0, "timeout": 720}
LONG = {"id": "rsi_long", "side": "LONG", "tree": [[[f("15m", "rsi_14"), "<", 40]]], "position": POSITION}
SHORT = {"id": "rsi_short", "side": "SHORT", "tree": [[[f("15m", "rsi_14"), ">", 60]]], "position": POSITION}


# ─── Tracker: ATR + rủi ro ──────────────────────────────────────────────────

def _tracker(**pos):
    from backend.core.execute.tracker import PositionTracker
    from backend.core.params.builder import build_params
    from backend.core.execute.models import PositionType
    side = pos.pop("side", "LONG")
    params = build_params("f", {"match": [], "stop": []}, side, {**POSITION, **pos}, "cex")
    return PositionTracker(0, 0, "X", "f", params, PositionType.LONG if side == "LONG" else PositionType.SHORT,
                           initial_capital=10000.0)


def test_atr_exits_and_risk_sizing_lose_exactly_risk_at_stop():
    tr = _tracker(fee_rate=0.0, maker_fee_rate=0.0, slippage_rate=0.0, trailing_stop=0, take_profit_rate=3.0)
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False, vol=1.5)   # ATR% = 1,5 lúc tín hiệu
    tr.on_bar(M, 100, 100, 100, 100, entry_signal=False, stop_signal=False, vol=9.9)  # vol mới không ảnh hưởng
    assert tr.is_open
    assert tr.sl_pct == pytest.approx(3.0) and tr.tp_pct == pytest.approx(4.5)
    assert tr.qty * 100 == pytest.approx(10000 * 0.01 / 0.03)                        # danh nghĩa = rủi ro / khoảng SL
    pos = tr.on_bar(2 * M, 100, 100, 96, 96.5, entry_signal=False, stop_signal=False)
    assert pos.status.name == "SL" and pos.close_price == pytest.approx(97.0)
    assert pos.real_pnl == pytest.approx(-100.0)                                      # đúng 1% vốn
    assert pos.unit_pct == pytest.approx(1.5) and pos.risk_usd == pytest.approx(100.0)


def test_risk_sizing_includes_round_trip_costs():
    tr = _tracker(trailing_stop=0)  # phí perp mặc định: taker 0,05% + trượt 0,02% mỗi chiều
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False, vol=1.0)
    tr.on_bar(M, 100, 100, 100, 100, entry_signal=False, stop_signal=False)
    pos = tr.on_bar(2 * M, 100, 100, 97, 97.5, entry_signal=False, stop_signal=False)
    assert pos.status.name == "SL"
    assert -pos.real_pnl == pytest.approx(100.0, rel=0.02) and -pos.real_pnl <= 100.0  # ≈ rủi ro, không vượt


# SL = 2 × ATR%; đòn bẩy an toàn = floor(1 / (1,5 × SL + mmr)), trần 10x
@pytest.mark.parametrize("vol,expected_lev", [(0.5, 10), (5.0, 6), (10.0, 3)])
def test_leverage_is_lowered_so_liquidation_stays_beyond_stop(vol, expected_lev):
    tr = _tracker()
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False, vol=vol)
    tr.on_bar(M, 100, 100, 100, 100, entry_signal=False, stop_signal=False)
    sl = tr.sl_pct / 100
    assert tr.pos_leverage == expected_lev
    liq_dist = 1 - tr._liq_price() / tr.avg
    assert liq_dist >= 1.5 * sl - 1e-12


def test_atr_entry_skipped_during_warmup():
    tr = _tracker()
    tr.on_bar(0, 100, 100, 100, 100, entry_signal=True, stop_signal=False, vol=float("nan"))
    tr.on_bar(M, 100, 100, 100, 100, entry_signal=False, stop_signal=False)
    assert not tr.is_open and tr.skipped_no_vol == 1


def test_risk_sizing_requires_stop_loss():
    with pytest.raises(ValueError, match="stop_loss_rate"):
        _tracker(stop_loss_rate=0)


# ─── Engine: ATR lấy từ nến đã đóng ─────────────────────────────────────────

def test_engine_atr_unit_comes_from_closed_bar_at_signal(market):
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.params.builder import build_params
    eng = BacktestEngine(0, 0, "BBB@perp", T0, T0 + 20 * DAY, trade_start_ts=T0 + 3 * DAY)
    eng.add_strategy_flow("LONG_x", build_params("LONG_x", {"match": [{"condition": LONG["tree"]}], "stop": []},
                                                 "LONG", POSITION, "cex", symbol="BBB@perp"))
    eng.load_data()
    df1, cols = eng._build_matrix()
    eng.run()
    natr = cols["1h|natr_14"]
    times = df1["open_time"].to_numpy()
    assert len(eng.closed_positions) > 5
    for p in eng.closed_positions:
        sig_row = np.searchsorted(times, p.enter_time) - 1     # tín hiệu ở nến ngay trước nến vào lệnh
        assert p.unit_pct == pytest.approx(natr[sig_row])
        hour_start = (times[sig_row] + M) // 3_600_000 * 3_600_000
        # natr ở nến tín hiệu là của nến 1h đã đóng trước thời điểm quyết định
        f1h = eng.frames["1h"]
        closed = f1h[f1h.open_time + 3_600_000 <= hour_start + ((times[sig_row] + M) - hour_start)]
        from backend.core.signals import kernels
        expect = kernels.compute(f1h, "natr_14").to_numpy()[len(closed) - 1]
        assert p.unit_pct == pytest.approx(expect)


# ─── Danh mục ───────────────────────────────────────────────────────────────

def _portfolio(symbols, strategies, risk=None, days=(3, 30), **kw):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    eng = PortfolioEngine(symbols, strategies, T0, T0 + days[1] * DAY, trade_start_ts=T0 + days[0] * DAY,
                          risk=RiskConfig.from_dict(risk), use_cache=False, **kw)
    eng.load_data()
    return eng


def test_portfolio_single_symbol_matches_single_engine(market):
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.params.builder import build_params
    pe = _portfolio(["BBB@perp"], [LONG], risk={"max_positions": 99, "max_per_symbol": 99,
                                                 "max_gross_exposure": 1e9, "kill_switch_dd_pct": 0})
    pe.run()
    se = BacktestEngine(0, 0, "BBB@perp", T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY)
    se.add_strategy_flow("LONG_rsi_long", build_params("LONG_rsi_long", {"match": [{"condition": LONG["tree"]}],
                                                                         "stop": []}, "LONG", POSITION, "cex",
                                                       symbol="BBB@perp"))
    se.load_data()
    se.run()
    a, b = pe.get_results(), se.get_results()
    assert len(a["positions"]) == len(b["positions"]) > 10
    for p, q in zip(a["positions"], b["positions"]):
        assert (p.enter_time, p.close_time, p.status) == (q.enter_time, q.close_time, q.status)
        assert p.real_pnl == pytest.approx(q.real_pnl, rel=1e-9, abs=1e-9)
    assert a["final_equity"] == pytest.approx(b["final_equity"], rel=1e-12)


def test_portfolio_risk_caps_and_shared_ledger(market):
    syms = ["AAA@perp", "BBB@perp", "CCC@perp"]
    risk = {"max_positions": 2, "max_per_symbol": 1, "max_gross_exposure": 1.5, "kill_switch_dd_pct": 0}
    eng = _portfolio(syms, [LONG, SHORT], risk=risk)
    seen = {"max_open": 0, "max_gross": 0.0, "violations": []}

    def hook(e, t):
        n_open, per = e._open_counts()
        seen["max_open"] = max(seen["max_open"], n_open)
        if max(per) > 1:
            seen["violations"].append(("per_symbol", t))
        led = e.ledger
        if led.reserved > led.equity * led.usage + sum(
                tr.funding_paid for b in e.books for x in b["entries"] for tr in [x["tracker"]] if tr.is_open) + 1e-6:
            seen["violations"].append(("ledger", t))
        # tổng danh nghĩa theo giá vào lệnh của các vị thế mở <= trần × vốn tại lúc vào lệnh mới nhất
        gross_entry = sum(x["tracker"].qty * x["tracker"].avg for b in e.books for x in b["entries"] if x["tracker"].is_open)
        seen["max_gross"] = max(seen["max_gross"], gross_entry / led.equity)

    eng.bar_hook = hook
    eng.run()
    res = eng.get_results()
    assert not seen["violations"], seen["violations"][:5]
    assert seen["max_open"] == 2                       # trần có tác dụng (tín hiệu dày)
    assert res["rejected_for_risk"] > 0
    # số lần vào lệnh bị chặn: phút liên tiếp của cùng một tracker chỉ tính một lần -> không vượt số phút
    assert 0 < res["risk_blocked_attempts"] <= res["rejected_for_risk"]
    assert seen["max_gross"] <= 1.5 * 1.02             # sai lệch nhỏ do vốn thay đổi khi lệnh khác đóng
    assert set(res["by_symbol"]) == set(syms) and set(res["by_strategy"]) == {"rsi_long", "rsi_short"}
    total = sum(p.real_pnl for p in res["positions"])
    assert res["final_equity"] - 10000.0 == pytest.approx(total, abs=1e-6)   # vốn = Σ lãi/lỗ từng lệnh (gồm funding)
    assert sum(v["pnl_usd"] for v in res["by_strategy"].values()) == pytest.approx(total)
    # thời gian: không vị thế nào vào trước trade_start
    assert min(p.enter_time for p in res["positions"]) >= T0 + 3 * DAY


def test_portfolio_is_deterministic_and_cache_safe(market):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    out = []
    for cache in (False, True, True):
        eng = PortfolioEngine(["AAA@perp", "CCC@perp"], [LONG, SHORT], T0, T0 + 25 * DAY, trade_start_ts=T0 + 3 * DAY,
                              risk=RiskConfig(max_positions=3), use_cache=cache)
        eng.run()
        r = eng.get_results()
        out.append((r["final_equity"], len(r["positions"]), [p.close_time for p in r["positions"]]))
    assert out[0] == out[1] == out[2]


def test_kill_switch_closes_everything_and_stops_trading(market):
    big = {**POSITION, "risk_per_trade_pct": 5.0, "max_notional_pct": 1000, "stop_loss_rate": 6.0,
           "take_profit_rate": 0, "trailing_stop": 0, "timeout": 0}
    strategies = [{**LONG, "position": big}, {**SHORT, "position": big}]
    eng = _portfolio(["AAA@perp", "BBB@perp", "CCC@perp"], strategies,
                     risk={"max_positions": 6, "max_per_symbol": 2, "max_gross_exposure": 10, "kill_switch_dd_pct": 5})
    eng.run()
    res = eng.get_results()
    assert res["halted_at"] is not None
    after = [p for p in res["positions"] if p.enter_time > res["halted_at"]]
    assert not after
    killed = [p for p in res["positions"] if p.close_reason == "Kill switch danh mục"]
    assert killed and all(p.close_time == res["halted_at"] for p in killed)
