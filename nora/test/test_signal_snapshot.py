"""Ảnh chụp tín hiệu (core/signals/snapshot.py): cùng đường tính với engine và KHÔNG nhìn tương lai."""
import numpy as np

from backend.models.params import materialize
from test_strategy_book import T0, _small_book, market  # noqa: F401  (market là fixture)

DAY = 86_400_000


def _strats(sb):
    return [materialize(c, {k: v[0] for k, v in c["space"].items()}) for c in sb.CANDIDATES]


def test_snapshot_is_causal_future_data_does_not_change_it(market, monkeypatch):
    """Cùng điểm bắt đầu cửa sổ; thêm 3 ngày dữ liệu SAU phút được chụp -> mọi điều kiện/giá trị ở phút đó y hệt (chỉ báo đệ quy như RSI
    phụ thuộc điểm bắt đầu nên giữ nguyên điểm bắt đầu)."""
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.dsl.signal import VectorEvaluator, lag_key
    from backend.alpha.dsl.strategy import signal_snapshot
    from backend.alpha.dsl.signal import _explain
    sb = _small_book(monkeypatch)
    strats = _strats(sb)
    end = T0 + 20 * DAY + 7 * 60_000
    look = 2 * 24 * 60
    a = signal_snapshot("AAA@perp", strats, end, lookback_minutes=look)
    assert a["bar_open_time"] is not None and a["bar_open_time"] < end and a["as_of"] == a["bar_open_time"] + 60_000
    start = end - look * 60_000
    pe = PortfolioEngine(["AAA@perp"], strats, start, end + 3 * DAY, trade_start_ts=start, use_cache=False)
    eng, pairs = pe._make_slots("AAA@perp", pe.ledger)
    eng.load_data()
    df1, cols = eng._build_matrix()
    i = int(np.flatnonzero(df1["open_time"].to_numpy() == a["bar_open_time"])[0])
    assert i < len(df1) - 1000                                                 # thật sự có dữ liệu tương lai phía sau
    vec = VectorEvaluator(len(df1), lambda f, c, l: cols.get(f"{f}|{lag_key(c, l)}", np.full(len(df1), np.nan)))
    for (st, tr), x in zip(pairs, a["strategies"]):
        assert x["entry_blocks"] == _explain(vec, tr.match_tree, i) and x["exit_blocks"] == _explain(vec, tr.stop_tree, i)
        assert x["entry"] == bool(vec.tree(tr.match_tree)[i])


def test_snapshot_matches_engine_signal_arrays(market, monkeypatch):
    """Tín hiệu vào của snapshot ở phút cuối == mảng tín hiệu mà engine dùng (VectorEvaluator trên ma trận của engine) ở phút đó."""
    from backend.nautilus.engine import PortfolioEngine
    from backend.alpha.dsl.signal import VectorEvaluator, lag_key
    from backend.alpha.dsl.strategy import signal_snapshot
    sb = _small_book(monkeypatch)
    strats = _strats(sb)
    end = T0 + 25 * DAY
    snap = signal_snapshot("BBB@perp", strats, end, lookback_minutes=3 * 24 * 60)
    pe = PortfolioEngine(["BBB@perp"], strats, end - 6 * DAY, end, trade_start_ts=end - 6 * DAY, use_cache=False)
    eng, pairs = pe._make_slots("BBB@perp", pe.ledger)
    eng.load_data()
    df1, cols = eng._build_matrix()
    i = int(np.flatnonzero(df1["open_time"].to_numpy() == snap["bar_open_time"])[0])
    vec = VectorEvaluator(len(df1), lambda f, c, l: cols.get(f"{f}|{lag_key(c, l)}", np.full(len(df1), np.nan)))
    for (st, tr), s in zip(pairs, snap["strategies"]):
        assert s["id"] == st["id"]
        assert s["entry"] == bool(vec.tree(tr.match_tree)[i]) and s["exit"] == bool(vec.tree(tr.stop_tree)[i])
        assert s["entry"] == any(b["pass"] for b in s["entry_blocks"])
