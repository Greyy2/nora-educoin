"""Dữ liệu dùng chung qua mmap (backend/core/data/shared.py) phải BẰNG TỪNG BIT dữ liệu tự dựng,
và PortfolioEngine chạy với shared_dir cho kết quả chuẩn hoá y hệt khi không dùng nó."""
import os

import numpy as np
import pandas as pd
import pytest

import golden_scenarios as gs
from data_helpers import save_synthetic

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

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
    monkeypatch.delenv("NORA_SHARED_DATA_DIR", raising=False)
    for k, (sym, vol) in enumerate((("AAA", 0.0008), ("BBB", 0.0016), ("CCC", 0.0030))):
        save_synthetic(symbol=sym, output_dir=str(root / "cex"), df_1m_raw=_series(40, 10 + k, vol))
    gs.clear_caches()
    yield root
    gs.clear_caches()


SYMS = ["AAA@perp", "BBB@perp", "CCC@perp"]


def _engine(**kw):
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    return PortfolioEngine(SYMS, [gs.LONG, gs.SHORT], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY,
                           risk=RiskConfig(), use_cache=False, **kw)


def _assert_same(built, loaded):
    assert loaded is not None
    assert list(loaded) == list(built) and list(loaded["cols"]) == list(built["cols"]) and built["cols"]
    pairs = [(k, built[k], loaded[k]) for k in ("t", "o", "h", "l", "c", "f_t", "f_r")]
    pairs += [(f"cols[{k}]", built["cols"][k], loaded["cols"][k]) for k in built["cols"]]
    for name, a, b in pairs:
        assert a.dtype == b.dtype, name
        assert a.shape == b.shape, name
        assert np.array_equal(a, b, equal_nan=True), name
        assert a.tobytes() == b.tobytes(), name   # NaN/-0.0 cũng giống từng bit
        if not name.startswith("cols["):
            assert not b.flags.writeable, name    # nền: view mmap chỉ đọc (cột = giá trị khung mmap gom theo chỉ số)


def _tmp_left(out):
    return [n for sub in ("base", "ft", "fv", "ix") if (out / sub).is_dir() for n in os.listdir(out / sub) if ".tmp" in n]


def test_mmap_data_equals_built_data_bit_for_bit(market, tmp_path):
    from backend.optimize.search import evaluate as shared_data
    eng = _engine()
    out = tmp_path / "shared"
    info = shared_data.export(eng, str(out))
    assert sorted(info["written"]) == sorted(SYMS) and shared_data.size_mb(str(out), info["paths"]) > 0
    again = shared_data.export(eng, str(out))        # đã có -> không ghi lại
    assert again["written"] == [] and again["paths"] == info["paths"]
    assert not _tmp_left(out)
    for sym in SYMS:
        e, _ = eng._make_slots(sym, eng.ledger)
        built = eng._build_symbol_data(e)
        loaded = shared_data.load(str(out), shared_data.plan(e))
        _assert_same(built, loaded)
        assert len(loaded["f_t"]) == 0 and len(built["f_t"]) == 0   # P15: Nautilus backtest không thanh toán funding (nautilus/engine.py::_build_symbol_data) -> không có chuỗi funding


def test_key_changes_when_source_file_changes(market):
    from backend.optimize.search import evaluate as shared_data
    eng = _engine()
    e, _ = eng._make_slots("AAA@perp", eng.ledger)
    p1 = shared_data.plan(e)
    assert p1 == shared_data.plan(e) and len(p1["base"]) == 40 and p1["cols"]
    import glob
    for fp in glob.glob(str(market / "market" / "okx" / "catalog" / "data" / "bar" / "AAA-USDT-SWAP.*" / "*.parquet")):   # catalog đổi (mtime) -> khoá đổi
        st = os.stat(fp)
        os.utime(fp, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    p2 = shared_data.plan(e)
    assert p2["base"] != p1["base"]
    assert shared_data.load(str(market), {"base": "0" * 40, "frames": {}, "cols": {}}) is None


def test_indicators_are_window_invariant_fixed_origin(market):
    """Chỉ báo tính từ đầu lịch sử (gốc cố định, như TradingView): cùng phút -> cùng giá trị dù cửa sổ backtest bắt đầu khác nhau,
    và dù cột khác cùng khung cần warmup dài hơn. Khoá cột vì thế không phụ thuộc cửa sổ nạp."""
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    from backend.optimize.search import evaluate as shared_data
    a = {"id": "a", "side": "LONG", "tree": [[[{"frame": "4h", "column": "ema_20"}, ">", 0],
                                             [{"frame": "1m", "column": "rsi_14"}, ">", 0]]], "position": gs._POSITION}
    b = {"id": "b", "side": "LONG", "tree": [[[{"frame": "4h", "column": "ema_20"}, ">", {"frame": "4h", "column": "ema_120"}],
                                             [{"frame": "1m", "column": "rsi_14"}, ">", 0]]], "position": gs._POSITION}
    got = []
    for st, start in ((a, T0), (b, T0 + 9 * DAY)):
        pe = PortfolioEngine(["AAA@perp"], [st], start, T0 + 30 * DAY, trade_start_ts=T0 + 12 * DAY, risk=RiskConfig(), use_cache=False)
        e, _ = pe._make_slots("AAA@perp", pe.ledger)
        got.append((shared_data.plan(e), pe._build_symbol_data(e)))
    (p1, d1), (p2, d2) = got
    assert p1["base"] != p2["base"] and p1["cols"]["4h|ema_20"] == p2["cols"]["4h|ema_20"]   # khác cửa sổ, CÙNG giá trị khung ...
    common = np.intersect1d(d1["t"], d2["t"])
    assert len(common) > 1000
    for cid in ("4h|ema_20", "1m|rsi_14"):
        v1 = d1["cols"][cid][np.searchsorted(d1["t"], common)]
        v2 = d2["cols"][cid][np.searchsorted(d2["t"], common)]
        assert v1.tobytes() == v2.tobytes(), cid                        # ... nhưng cùng giá trị từng bit ở mọi phút chung


def test_two_groups_share_base_and_only_add_missing_columns(market, tmp_path):
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    from backend.optimize.search import evaluate as shared_data
    out = tmp_path / "shared"
    st1 = {"id": "s1", "side": "LONG", "tree": [[[{"frame": "15m", "column": "rsi_14"}, "<", 40]]], "position": gs._POSITION}
    st2 = {"id": "s2", "side": "LONG", "tree": [[[{"frame": "15m", "column": "rsi_20"}, "<", 30]]], "position": gs._POSITION}
    engs = [PortfolioEngine(SYMS, [st], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY, risk=RiskConfig(), use_cache=False)
            for st in (st1, st2)]
    shared_data.export(engs[0], str(out))
    n_cols = len(os.listdir(out / "fv"))
    before = dict(shared_data.STATS)
    shared_data.export(engs[1], str(out))
    assert len(os.listdir(out / "base")) == len(SYMS)                                 # nền dùng chung
    assert shared_data.STATS["bases_written"] == before["bases_written"]
    assert len(os.listdir(out / "fv")) - n_cols == len(SYMS)                          # chỉ thêm rsi_20 cho mỗi tài sản
    for pe in engs:
        for sym in SYMS:
            e, _ = pe._make_slots(sym, pe.ledger)
            _assert_same(pe._build_symbol_data(e), shared_data.load(str(out), shared_data.plan(e)))


def test_build_matrix_only_equals_subset_of_full(market):
    eng = _engine()
    e, _ = eng._make_slots("BBB@perp", eng.ledger)
    e.load_data()
    _, full = e._build_matrix()
    pick = set(list(full)[:1] + list(full)[-1:])
    _, part = e._build_matrix(only=pick)
    assert set(part) == pick
    for k in pick:
        assert part[k].tobytes() == full[k].tobytes()


def test_run_with_shared_dir_matches_run_without(market, tmp_path, monkeypatch):
    from backend.alpha.dsl import strategy as portfolio
    from backend.optimize.search import evaluate as shared_data
    plain = _engine()
    plain.run()
    golden = gs.canonicalize(plain.get_results())
    assert golden["positions"]

    out = str(tmp_path / "shared")
    shared_data.export(_engine(), out)
    gs.clear_caches()
    eng = _engine(shared_dir=out)
    eng.load_data()
    assert all(not b["data"]["t"].flags.writeable and not b["data"]["t"].flags.owndata for b in eng.books)  # mmap chỉ đọc, không phải bản sao
    eng.run()
    assert gs.canonicalize(eng.get_results()) == golden

    # qua biến môi trường + use_cache=True: dữ liệu mmap KHÔNG vào _DATA_CACHE
    monkeypatch.setenv("NORA_SHARED_DATA_DIR", out)
    gs.clear_caches()
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    env_eng = PortfolioEngine(SYMS, [gs.LONG, gs.SHORT], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY,
                              risk=RiskConfig(), use_cache=True)
    assert env_eng.shared_dir == out
    env_eng.run()
    assert gs.canonicalize(env_eng.get_results()) == golden
    assert portfolio.data_source().memo.used == 0

    # thư mục trống -> engine tự điền đúng phần thiếu vào shared_dir rồi đọc mmap; lần sau không phải dựng lại
    empty = str(tmp_path / "empty")
    before = shared_data.STATS["fills"]
    lazy = _engine(shared_dir=empty)
    lazy.run()
    assert gs.canonicalize(lazy.get_results()) == golden
    assert shared_data.STATS["fills"] - before == len(SYMS)                         # mỗi tài sản điền một lần
    assert len(os.listdir(os.path.join(empty, "base"))) == len(SYMS) and os.listdir(os.path.join(empty, "fv"))
    calls = []
    orig = PortfolioEngine._build_symbol_data
    monkeypatch.setattr(PortfolioEngine, "_build_symbol_data", lambda self, e, only=None: calls.append(1) or orig(self, e, only))
    again = _engine(shared_dir=empty)
    again.run()
    assert calls == [] and gs.canonicalize(again.get_results()) == golden


def test_golden_real_through_shared_mmap(tmp_path):
    """Kịch bản dữ liệu thật của golden, nhưng dữ liệu đi qua export + mmap: phải trùng snapshot từng bit."""
    import json
    root = os.path.abspath(os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data"))
    if not gs.real_data_available(root):
        pytest.skip(f"Không có dữ liệu thật tại {root}")
    if not os.environ.get("NORA_GOLDEN_DATA_ROOT"):
        pytest.skip("portfolio_real.json ghi bằng engine cũ trên kho pkl (mốc thời gian/số liệu khác engine Nautilus + catalog): chỉ so khi "
                    "đặt NORA_GOLDEN_DATA_ROOT tới kho tương ứng")
    with open(os.path.join(os.path.dirname(__file__), "golden", "portfolio_real.json"), encoding="utf-8") as fh:
        golden = json.load(fh)
    fresh = gs.scenario_portfolio_real(root, shared_dir=str(tmp_path / "shared"))
    assert os.listdir(tmp_path / "shared")
    assert golden == fresh, gs.diff_canonical(golden, fresh)


@pytest.mark.parametrize("frame", ["15m", "1m"])
def test_lazy_fill_equals_built_and_is_reused(market, tmp_path, frame):
    """Kho trống: worker tự điền (nền + giá trị cột theo khung + chỉ số căn) -> bằng từng bit với tự dựng; engine thứ hai cùng refs
    không phải tính gì nữa. Gồm cả cột khung 1m (tính trên toàn bộ phút thật từ đầu lịch sử)."""
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    from backend.optimize.search import evaluate as shared_data
    out = tmp_path / "shared"
    st = {"id": "s", "side": "LONG", "position": gs._POSITION,
          "tree": [[[{"frame": frame, "column": "rsi_14"}, "<", {"frame": "4h", "column": "ema_30", "index": 1}]]]}

    def engine():
        return PortfolioEngine(SYMS, [st], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY, risk=RiskConfig(), use_cache=False,
                               shared_dir=str(out))
    pe = engine()
    for sym in SYMS:
        e, _ = pe._make_slots(sym, pe.ledger)
        lazy = pe._load_symbol(sym, e)
        e2, _ = pe._make_slots(sym, pe.ledger)
        built = pe._build_symbol_data(e2)
        assert list(lazy["cols"]) == list(built["cols"])
        for k in ("t", "o", "h", "l", "c", "f_t", "f_r"):
            assert lazy[k].tobytes() == built[k].tobytes(), k
        for k in built["cols"]:
            assert lazy["cols"][k].dtype == built["cols"][k].dtype and lazy["cols"][k].tobytes() == built["cols"][k].tobytes(), k
    before = shared_data.STATS["fills"]
    pe2 = engine()
    pe2.load_data()
    assert shared_data.STATS["fills"] == before                                       # đọc thẳng kho, không tính lại


def test_base_frame_1h_shared_equals_built_and_rejects_smaller_frames(market, tmp_path):
    """Khung chạy 1h: kho dùng chung bằng từng bit với tự dựng; khung tín hiệu nhỏ hơn khung chạy bị từ chối rõ ràng."""
    from backend.alpha.dsl.strategy import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    st = {"id": "s", "side": "LONG", "position": {**gs._POSITION, "atr_frame": "1h"},
          "tree": [[[{"frame": "1h", "column": "rsi_14"}, "<", {"frame": "4h", "column": "ema_30", "index": 1}]]]}
    kw = dict(trade_start_ts=T0 + 3 * DAY, risk=RiskConfig(), use_cache=False, base_frame="1h")
    pe = PortfolioEngine(SYMS, [st], T0, T0 + 30 * DAY, shared_dir=str(tmp_path / "shared"), **kw)
    for sym in SYMS:
        e, _ = pe._make_slots(sym, pe.ledger)
        lazy = pe._load_symbol(sym, e)
        e2, _ = pe._make_slots(sym, pe.ledger)
        built = pe._build_symbol_data(e2)
        assert len(built["t"]) and np.all(np.diff(built["t"]) == 3_600_000)          # nến 1h
        for k in ("t", "o", "h", "l", "c"):
            assert lazy[k].tobytes() == built[k].tobytes(), k
        for k in built["cols"]:
            assert lazy["cols"][k].tobytes() == built["cols"][k].tobytes(), k
    plain = PortfolioEngine(SYMS, [st], T0, T0 + 30 * DAY, **kw)
    plain.run()
    assert plain.get_results()["positions"]
    small = {**st, "tree": [[[{"frame": "15m", "column": "rsi_14"}, "<", 30]]]}
    with pytest.raises(ValueError, match="nhỏ hơn khung chạy"):
        PortfolioEngine(SYMS, [small], T0, T0 + 30 * DAY, **kw).load_data()
