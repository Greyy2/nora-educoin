"""Dữ liệu dùng chung qua mmap (backend/core/data/shared.py) phải BẰNG TỪNG BIT dữ liệu tự dựng,
và PortfolioEngine chạy với shared_dir cho kết quả chuẩn hoá y hệt khi không dùng nó."""
import os

import numpy as np
import pandas as pd
import pytest

import golden_scenarios as gs
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
    monkeypatch.delenv("NORA_SHARED_DATA_DIR", raising=False)
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
    gs.clear_caches()
    yield root
    gs.clear_caches()


SYMS = ["AAA@perp", "BBB@perp", "CCC@perp"]


def _engine(**kw):
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    return PortfolioEngine(SYMS, [gs.LONG, gs.SHORT], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY,
                           risk=RiskConfig(), use_cache=False, **kw)


def test_mmap_data_equals_built_data_bit_for_bit(market, tmp_path):
    from backend.core.data import shared as shared_data
    eng = _engine()
    out = tmp_path / "shared"
    info = shared_data.export(eng, str(out))
    assert sorted(info["written"]) == sorted(SYMS) and info["bytes"] > 0
    again = shared_data.export(eng, str(out))        # đã có -> bỏ qua, không ghi lại
    assert again["written"] == [] and sorted(again["skipped"]) == sorted(SYMS) and again["keys"] == info["keys"]
    assert not [n for n in os.listdir(out) if n.startswith(".tmp")]
    for sym in SYMS:
        e, _ = eng._make_trackers(sym, eng.ledger)
        built = eng._build_symbol_data(e)
        loaded = shared_data.load(str(out), info["keys"][sym])
        assert loaded is not None
        assert list(loaded) == list(built) and list(loaded["cols"]) == list(built["cols"]) and built["cols"]
        pairs = [(k, built[k], loaded[k]) for k in ("t", "o", "h", "l", "c", "f_t", "f_r")]
        pairs += [(f"cols[{k}]", built["cols"][k], loaded["cols"][k]) for k in built["cols"]]
        for name, a, b in pairs:
            assert a.dtype == b.dtype, name
            assert a.shape == b.shape, name
            assert np.array_equal(a, b, equal_nan=True), name
            assert a.tobytes() == b.tobytes(), name   # NaN/-0.0 cũng giống từng bit
            assert not b.flags.writeable, name        # chỉ đọc
        assert len(loaded["f_t"]) > 0


def test_key_changes_when_source_file_changes(market):
    from backend.core.data import shared as shared_data
    eng = _engine()
    e, _ = eng._make_trackers("AAA@perp", eng.ledger)
    k1 = eng._shared_key("AAA@perp", e)
    assert k1 == eng._shared_key("AAA@perp", e) and len(k1) == 40
    fund = market / "cex" / "AAA" / "perp" / "funding.pkl"
    st = fund.stat()
    os.utime(fund, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert eng._shared_key("AAA@perp", e) != k1
    assert shared_data.load(str(market), "0" * 40) is None


def test_run_with_shared_dir_matches_run_without(market, tmp_path, monkeypatch):
    from backend.core.backtest import portfolio
    from backend.core.data import shared as shared_data
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
    from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
    env_eng = PortfolioEngine(SYMS, [gs.LONG, gs.SHORT], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY,
                              risk=RiskConfig(), use_cache=True)
    assert env_eng.shared_dir == out
    env_eng.run()
    assert gs.canonicalize(env_eng.get_results()) == golden
    assert portfolio._DATA_CACHE.used == 0

    # khoá không có trong thư mục -> rơi về đường tự dựng như cũ
    fallback = _engine(shared_dir=str(tmp_path / "empty"))
    fallback.run()
    assert gs.canonicalize(fallback.get_results()) == golden


def test_golden_real_through_shared_mmap(tmp_path):
    """Kịch bản dữ liệu thật của golden, nhưng dữ liệu đi qua export + mmap: phải trùng snapshot từng bit."""
    import json
    root = os.path.abspath(os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data"))
    if not gs.real_data_available(root):
        pytest.skip(f"Không có dữ liệu thật tại {root}")
    with open(os.path.join(os.path.dirname(__file__), "golden", "portfolio_real.json"), encoding="utf-8") as fh:
        golden = json.load(fh)
    fresh = gs.scenario_portfolio_real(root, shared_dir=str(tmp_path / "shared"))
    assert os.listdir(tmp_path / "shared")
    assert golden == fresh, gs.diff_canonical(golden, fresh)
