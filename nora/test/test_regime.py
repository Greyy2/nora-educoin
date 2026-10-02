"""Regime (core/regime/classifier.py): luật phân loại + chống nhảy, nhân quả (không nhìn tương lai), và ghép vào PortfolioEngine
(lọc tín hiệu vào, cầu chì thoát) — không bật regime thì engine y nguyên (golden bất biến)."""
import numpy as np

from backend.core.regime import classifier as rg
from test_strategy_book import T0, market  # noqa: F401  (market là fixture: 70 ngày, 3 tài sản)
from backend.core.strategy.book import f

M = 60_000
DAY = 86_400_000
POSITION = {"market": "perp", "order_size_usd": 1000, "leverage": 2, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720}
LONG = {"id": "rsi_long", "side": "LONG", "tree": [[[f("15m", "rsi_14"), "<", 40]]], "position": POSITION}


def _t(n):
    return T0 + np.arange(n, dtype=np.int64) * M


def test_smooth_confirm_hold_and_shock():
    raw = np.full(5000, rg.RANGE, dtype=np.int8)
    raw[1000:1100] = rg.TREND_UP            # 100 phút < 180 -> không được nhận
    raw[2000:2500] = rg.TREND_UP            # giữ đủ 180 phút -> nhận từ phút 2180
    raw[3000:3010] = rg.CRASH               # sốc: nhận ngay, giữ 360 phút kể từ phút sốc cuối
    out = rg.smooth(raw, _t(5000))
    assert (out[:2180] == rg.RANGE).all()
    assert (out[2180:2500] == rg.TREND_UP).all()
    assert (out[2500:2680] == rg.TREND_UP).all() and (out[2680:3000] == rg.RANGE).all()   # quay về RANGE cũng phải xác nhận
    assert (out[3000:3010] == rg.CRASH).all()
    assert (out[3010:3370] == rg.CRASH).all() and (out[3370:] == rg.RANGE).all()


def test_smooth_interrupted_pending_restarts():
    raw = np.full(2000, rg.RANGE, dtype=np.int8)
    raw[100:250] = rg.TREND_DOWN
    raw[250:260] = rg.VOL_EXPANSION         # chen ngang -> đếm lại từ đầu
    raw[260:600] = rg.TREND_DOWN
    out = rg.smooth(raw, _t(2000))
    assert (out[:440] == rg.RANGE).all() and out[440] == rg.TREND_DOWN


def test_raw_states_priority_and_warmup():
    n = 6
    feats = {
        ("4h", "er_20"): [np.nan, 0.1, 0.5, 0.5, 0.5, 0.5], ("4h", "adx_14"): [np.nan, 30, 30, 30, 30, 30],
        ("4h", "ema_50"): [np.nan, 1, 2, 1, 2, 2], ("4h", "ema_200"): [np.nan, 1, 1, 2, 1, 1],
        ("1h", "roc_24"): [np.nan, 0, 0, 0, 13, -3], ("1h", "roc_1"): [np.nan, 0, 0, 0, 0, -6],
        ("1h", "bbwp_20_2_720"): [np.nan, 95, 10, 10, 10, 10],
    }
    out = rg.raw_states(lambda fr, c: np.asarray(feats[(fr, c)], float), n)
    assert [rg.NAMES[x] for x in out] == ["UNKNOWN", "VOL_EXPANSION", "TREND_UP", "TREND_DOWN", "SURGE", "CRASH"]


def test_masks_for_strategy():
    labels = np.array([rg.RANGE, rg.TREND_UP, rg.CRASH, rg.SURGE], dtype=np.int8)
    allowed, fuse = rg.masks_for({"regime": {"allowed": ["TREND_UP"]}}, "LONG", labels)
    assert allowed.tolist() == [False, True, False, False] and fuse.tolist() == [False, False, True, False]
    _, fuse = rg.masks_for({"regime": {"allowed": ["RANGE"]}}, "SHORT", labels)
    assert fuse.tolist() == [False, False, False, True]
    assert rg.masks_for({}, "LONG", labels) == (None, None)


def _labels(symbol, start, end):
    from backend.core.backtest.portfolio import PortfolioEngine
    pe = PortfolioEngine([symbol], [LONG], start, end, trade_start_ts=start, use_cache=False)
    eng, _ = pe._make_trackers(symbol, pe.ledger)
    eng.extra_refs = rg.REFS
    eng.load_data()
    df1, cols = eng._build_matrix()
    n = len(df1)
    t = df1["open_time"].to_numpy(dtype="int64")
    return t, rg.classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t)


def test_regime_is_causal(market):
    start = T0 + 2 * DAY
    t1, a = _labels("CCC@perp", start, T0 + 50 * DAY)
    t2, b = _labels("CCC@perp", start, T0 + 62 * DAY)
    k = len(t1)
    assert (t2[:k] == t1).all() and len(t2) > k + 1000
    assert (a == b[:k]).all()
    assert (a != rg.UNKNOWN).sum() > 1000                     # sau warmup thật sự có nhãn


def _run(strategies, start=T0 + 40 * DAY, end=T0 + 68 * DAY):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    eng = PortfolioEngine(["BBB@perp"], strategies, T0 + 2 * DAY, end, trade_start_ts=start,
                          risk=RiskConfig.from_dict({"max_positions": 99, "max_per_symbol": 99, "max_gross_exposure": 1e9,
                                                     "kill_switch_dd_pct": 0}), use_cache=False)
    eng.run()
    return eng.get_results()


def _sig(r):
    return [(p.enter_time, p.close_time, p.status, round(p.real_pnl, 9)) for p in r["positions"]]


def test_regime_allow_all_without_fuse_is_identical(market):
    plain = _run([LONG])
    gated = _run([{**LONG, "regime": {"allowed": list(rg.NAMES), "fuse": False}}])
    assert len(plain["positions"]) > 5
    assert _sig(plain) == _sig(gated) and plain["final_equity"] == gated["final_equity"]


def test_regime_filters_entries_to_allowed_states(market):
    t, labels = _labels("BBB@perp", T0 + 2 * DAY, T0 + 68 * DAY)
    plain = _run([LONG])
    allowed = ["RANGE"]
    gated = _run([{**LONG, "regime": {"allowed": allowed, "fuse": False}}])
    assert 0 < len(gated["positions"]) <= len(plain["positions"])
    codes = {rg.CODE[x] for x in allowed}
    for p in gated["positions"]:
        i = int(np.searchsorted(t, p.enter_time, side="right")) - 1    # phút tín hiệu = phút đã đóng cuối trước khi vào lệnh
        j = i - 1 if t[i] == p.enter_time else i
        assert labels[j] in codes or labels[i] in codes
    none = _run([{**LONG, "regime": {"allowed": ["SURGE"], "fuse": False}}])
    assert len(none["positions"]) < len(plain["positions"])


def test_keltner_trend_exits_on_opposite_band_cross(market):
    """keltner_trend_long (KEMA của sova): vào khi close cắt lên dải trên, thoát khi close cắt xuống dải dưới (cây stop)."""
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    from backend.core.strategy.book import CANDIDATES, materialize
    cand = {c["id"]: c for c in CANDIDATES}["keltner_trend_long"]
    st = materialize(cand, {"sig.signal_tf": "1h", "sig.ema_n": 20, "sig.k_up": 1.0, "sig.k_dn": 1.0, "stop_loss_rate": 6.0})
    assert st["stop"] and st["stop"][0]["condition"]
    eng = PortfolioEngine(["AAA@perp", "BBB@perp", "CCC@perp"], [st], T0 + 2 * DAY, T0 + 68 * DAY, trade_start_ts=T0 + 35 * DAY,
                          risk=RiskConfig.from_dict({"max_positions": 9, "max_per_symbol": 1, "max_gross_exposure": 1e9,
                                                     "kill_switch_dd_pct": 0}), use_cache=False)
    eng.run()
    reasons = [p.close_reason for p in eng.get_results()["positions"]]
    assert len(reasons) > 3 and "Tín hiệu thoát (AST stop)" in reasons, reasons
