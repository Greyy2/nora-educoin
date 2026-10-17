"""Kiểm tra backend/data/ (data.py = dùng dữ liệu, crawl.py = kéo dữ liệu về):

A. Catalog THẬT (10 symbol): exec_arrays đơn điệu, load_candles đúng cột, verdict chất lượng đã đóng dấu trong manifest.
B. Cổng chất lượng chỉ ĐỌC verdict trong manifest (thiếu verdict -> DataQualityError chỉ cách xử lý).
C. Crawl OKX bằng file ngày + REST GIẢ (không mạng): ghi catalog + manifest đúng, chạy lại không ghi đôi, nến trùng/hỏng bị loại.
D. fill_missing_1m_candles idempotent (nến điền không biến thành nến thật).
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from backend.data import crawl, data as D
from backend.data.crawl import DataQualityStatus, evaluate_data_quality
from backend.data.data import (
    UNIVERSE_BASES,
    DataQualityError,
    base_name,
    exec_arrays,
    fill_missing_1m_candles,
    frame_ms,
    load_candles,
    normalize_symbol,
    quality_verdict,
    read_manifest,
    require_data_ok,
)
from backend.analys.param import FRAME_MS

H = 3_600_000
DAY = 86_400_000
T0 = 1_704_067_200_000   # 2024-01-01 00:00Z


# ─── A. Catalog thật ───────────────────────────────────────────────────────

@pytest.mark.parametrize("base", UNIVERSE_BASES[:3])
@pytest.mark.parametrize("frame", ["1m", "15m", "1h"])
def test_exec_arrays_consistency(base: str, frame: str):
    """exec_arrays trả dữ liệu đúng định dạng và có tính đơn điệu."""
    start_ms, end_ms = 1735689600000, 1735862400000      # 2025-01-01 -> 2025-01-03
    arr = exec_arrays(base, frame, start_ms, end_ms)
    assert {"t", "o", "h", "l", "c", "v"} <= set(arr)
    assert len(arr["t"]) > 1
    assert (np.diff(arr["t"]) > 0).all(), f"{base} {frame}: timestamps must be strictly monotonic"
    for hi, lo in (("h", "l"), ("h", "o"), ("h", "c"), ("o", "l"), ("c", "l")):
        assert (arr[hi] >= arr[lo]).all(), f"{base} {frame}: {hi} >= {lo}"


@pytest.mark.parametrize("base", UNIVERSE_BASES[:3])
def test_load_candles_structure(base: str):
    df = load_candles(base, "1h", 1735689600000, 1735776000000)
    assert not df.empty
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume"]
    assert (df["high"] >= df["low"]).all()
    assert "is_filled" in load_candles(base, "1m", 1735689600000, 1735689600000 + H).columns


def test_frame_ms_uses_the_single_table():
    assert all(frame_ms(f) == ms for f, ms in FRAME_MS.items()) and frame_ms("1d") == FRAME_MS["24h"]
    with pytest.raises(ValueError):
        frame_ms("7m")


def test_symbol_helpers():
    assert normalize_symbol("cex:btc@perp") == "BTC-USDT-SWAP" and base_name("BTC-USDT-SWAP") == "BTC"
    with pytest.raises(ValueError):
        normalize_symbol("dex:AERO")


@pytest.mark.parametrize("base", UNIVERSE_BASES)
def test_real_manifest_has_stamped_verdict(base: str):
    """Mỗi symbol của rổ có verdict trong manifest (do crawl.refresh_quality / data_update đóng dấu); không BLOCKED."""
    v = quality_verdict(base)
    assert v is not None, f"{base}: manifest chưa có verdict — chạy crawl.refresh_quality"
    assert v["status"] in (DataQualityStatus.APPROVED, DataQualityStatus.WARNING), v["issues"]
    assert read_manifest(base)["quality"]["catalog_digest"]


def test_require_data_ok_reads_verdict_for_real_universe():
    out = require_data_ok(UNIVERSE_BASES)
    assert set(out) == set(UNIVERSE_BASES)


# ─── B. Cổng chỉ đọc verdict ───────────────────────────────────────────────

def _bars(n_days: float, seed: int = 5, t0: int = T0) -> pd.DataFrame:
    """Nến 1m giả: giá bội 0.1 (khớp tickSz 0.1 của BTC), volume quote USDT = 10 * close (-> base coin = 10)."""
    n = int(n_days * 1440)
    rng = np.random.default_rng(seed)
    close = np.round(100 * np.exp(np.cumsum(rng.normal(0, 0.0005, n))), 1)
    return pd.DataFrame({"open_time": t0 + np.arange(n, dtype=np.int64) * 60_000, "open": close, "high": close + 0.1, "low": close - 0.1,
                         "close": close, "volume": close * 10.0})


def test_gate_requires_stamped_verdict_and_blocks_short_data(tmp_path):
    root = str(tmp_path)
    crawl.append_to_catalog("BTC", _bars(10), root)                    # 10 ngày < 30 -> NEEDS_MORE_DATA
    v = quality_verdict("BTC", root)
    assert v["status"] == DataQualityStatus.NEEDS_MORE_DATA
    with pytest.raises(DataQualityError, match="BTC"):
        require_data_ok(["BTC"], root)
    # xoá verdict: cổng KHÔNG tự tính lại mà báo cách xử lý
    path = tmp_path / "market" / "okx" / "catalog" / "_manifest" / "BTC.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m.pop("quality")
    path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(DataQualityError, match="data_update|refresh_quality"):
        require_data_ok(["BTC"], root)
    crawl.refresh_quality(["BTC"], root)                                # đóng dấu lại verdict vào manifest hiện có
    assert quality_verdict("BTC", root)["status"] == DataQualityStatus.NEEDS_MORE_DATA


def test_gate_passes_after_enough_data_and_filled_ratio_blocks(tmp_path):
    root = str(tmp_path)
    crawl.append_to_catalog("ETH", _bars(35), root)
    assert require_data_ok(["ETH"], root)["ETH"]["status"] == DataQualityStatus.APPROVED
    df = _bars(35, seed=6)
    df = df[np.random.default_rng(0).random(len(df)) >= 0.7]           # thiếu 70% phút > ngưỡng 60%
    crawl.append_to_catalog("SOL", df, root)
    assert evaluate_data_quality("SOL", root)["status"] == DataQualityStatus.BLOCKED
    with pytest.raises(DataQualityError, match="SOL"):
        require_data_ok(["SOL"], root)


# ─── C. Crawl OKX giả (file ngày + REST) ───────────────────────────────────

def _csv(base: str, part: pd.DataFrame) -> bytes:
    rows = "".join(f"{base}-USDT-SWAP,{o},{h},{l},{c},1,1,{v},{t},1\n"
                   for t, o, h, l, c, v in zip(part.open_time, part.open, part.high, part.low, part.close, part.volume))
    return ("instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm\n" + rows).encode()


def test_parse_candles_csv_and_hk_days():
    raw = (b"instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm\n"
           b"BTC-USDT-SWAP,1,2,0.5,1.5,10,0.1,15.5,1705248000000,0\n"
           b"ETH-USDT-SWAP,1,2,0.5,1.5,10,0.1,99,1705248000000,0\n")
    df = crawl.parse_candles_csv(raw, "BTC")
    assert len(df) == 1 and df.iloc[0]["volume"] == 15.5 and df.iloc[0]["open_time"] == 1705248000000
    days = crawl._hk_days(T0, T0 + 24 * H - 60_000)
    lo, _ = crawl._hk_day_range(days[0])
    _, hi = crawl._hk_day_range(days[-1])
    assert lo <= T0 and hi >= T0 + 24 * H - 60_000 and len(days) == 2


def test_normalize_candles_drops_bad_rows_and_converts_volume():
    df = pd.DataFrame({"open_time": [60_000, 60_000, 120_000, 180_000, 240_000, 300_000],
                       "open": [10.0, 10.0, 10.0, 10.0, -1.0, 10.0], "high": [11.0, 11.0, 11.0, 8.0, 11.0, 11.0],
                       "low": [9.0] * 6, "close": [10.0, 20.0, 10.0, 10.0, 10.0, 10.0], "volume": [100.0, 200.0, 50.0, 50.0, 50.0, 50.0]})
    out = crawl.normalize_candles(df)
    # trùng open_time=60000 giữ dòng cuối; high<low (180000) và giá<=0 (240000) bị loại; volume = quote/close
    assert out["open_time"].tolist() == [60_000, 120_000, 300_000]
    assert out["volume"].tolist() == [200.0 / 20.0, 5.0, 5.0]
    assert crawl.normalize_candles(df, after_open_ms=120_000)["open_time"].tolist() == [300_000]


@pytest.fixture
def fake_okx(monkeypatch):
    """OKX giả: file ngày cho mọi ngày HK trừ ngày cuối (-> REST); 31 ngày nến BTC."""
    frame = _bars(31)
    end = int(frame.open_time.iloc[-1])
    last_day = crawl._hk_days(T0, end)[-1]

    def day_zip(session, kind, base, d, cache_dir):
        if d == last_day:
            return None
        lo, hi = crawl._hk_day_range(d)
        part = frame[frame.open_time.between(lo, hi)]
        return _csv(base, part) if len(part) else None

    def okx_get(session, path, params, pause=0.0):
        part = frame[frame.open_time < params["after"]].tail(100)
        return [[str(t), str(o), str(h), str(l), str(c), "1", "1", str(v), "1"]
                for t, o, h, l, c, v in zip(part.open_time[::-1], part.open[::-1], part.high[::-1], part.low[::-1], part.close[::-1], part.volume[::-1])]

    monkeypatch.setattr(crawl, "fetch_day_zip", day_zip)
    monkeypatch.setattr(crawl, "_okx_get", okx_get)
    return frame, end


def test_update_catalog_writes_catalog_and_manifest_without_network(tmp_path, fake_okx):
    frame, end = fake_okx
    root = str(tmp_path)
    res = crawl.update_catalog("BTC", end_ms=end, data_root=root)
    assert res["status"] == "UPDATED" and res["new_rows"] > 0
    m = read_manifest("BTC", root)
    assert m["rows_1m"] == res["new_rows"] == len(D.read_1m("BTC", 0, 2**62, root)["t"])
    assert m["volume_unit"] == "base_coin" and m["quality"]["status"] == DataQualityStatus.APPROVED
    arr = D.read_1m("BTC", 0, 2**62, root)
    sel = frame[frame.open_time >= int(arr["t"][0])].iloc[:len(arr["t"])]
    np.testing.assert_array_equal(arr["t"], sel.open_time.to_numpy())
    np.testing.assert_allclose(arr["c"], sel.close.to_numpy())
    np.testing.assert_allclose(arr["v"], 10.0)                            # quote 10*close / close = 10 coin
    assert D.default_catalog_path(root).endswith(os.path.join("market", "okx", "catalog"))


def test_rerun_does_not_double_write(tmp_path, fake_okx):
    frame, end = fake_okx
    root = str(tmp_path)
    crawl.update_catalog("BTC", end_ms=end, data_root=root)
    digest, rows = D.catalog_digest(["BTC"], root), read_manifest("BTC", root)["rows_1m"]
    assert crawl.update_catalog("BTC", end_ms=end, data_root=root)["status"] == "UP_TO_DATE"
    again = crawl.append_to_catalog("BTC", frame, root)                   # nến thô đã có hết -> không ghi gì
    assert again["status"] == "NO_NEW_DATA" and again["new_rows"] == 0
    assert D.catalog_digest(["BTC"], root) == digest and read_manifest("BTC", root)["rows_1m"] == rows
    more = _bars(1, seed=9, t0=int(frame.open_time.iloc[-1]) + 60_000)    # nến mới nối tiếp -> chỉ phần mới được ghi
    assert crawl.append_to_catalog("BTC", more, root)["new_rows"] == len(more)
    assert read_manifest("BTC", root)["rows_1m"] == rows + len(more)


def test_update_rejects_symbol_outside_universe(tmp_path):
    with pytest.raises(ValueError, match="rổ"):
        crawl.update_catalog("PEPE", data_root=str(tmp_path))


# ─── D. Nến điền ──────────────────────────────────────────────────────────

def _gappy(n: int = 120, gap_at: int = 60) -> pd.DataFrame:
    times = [1700000000000 + i * 60_000 for i in range(n) if i != gap_at]
    prices = [100.0 + i * 0.01 for i in range(len(times))]
    return pd.DataFrame({"open_time": times, "open": prices, "high": [p * 1.001 for p in prices], "low": [p * 0.999 for p in prices],
                         "close": prices, "volume": [10.0] * len(times)})


def test_fill_marks_gap_and_is_idempotent():
    once = fill_missing_1m_candles(_gappy())
    assert int((once["is_filled"] == 1).sum()) == 1 and len(once) == 120
    twice = fill_missing_1m_candles(once)
    assert len(twice) == len(once) and int((twice["is_filled"] == 1).sum()) == 1
    row = once[once["is_filled"] == 1].iloc[0]
    assert row["volume"] == 0.0 and row["open"] == row["high"] == row["low"] == row["close"]


def test_real_data_in_gap_replaces_filled_candle():
    df = _gappy()
    once = fill_missing_1m_candles(df)
    t_gap = int(once.loc[once["is_filled"] == 1, "open_time"].iloc[0])
    real = pd.concat([df, pd.DataFrame({"open_time": [t_gap], "open": [150.0], "high": [151.0], "low": [149.0], "close": [150.0], "volume": [3.0]})])
    out = fill_missing_1m_candles(real)
    assert int((out["is_filled"] == 1).sum()) == 0
    assert float(out.loc[out["open_time"] == t_gap, "close"].iloc[0]) == 150.0


# ─── E. P19 Universe Scan Regressions ─────────────────────────────────────

def test_p19_universe_scan_regressions():
    """Kiểm hồi quy P19: default_universe() luôn đúng 10 coin gốc, scan_universe() trả 100 coin."""
    from backend.data.crawl import load_scan_universe, scan_universe_bases
    from backend.nautilus.catalog import get_instrument

    # 1. default_universe() chỉ gồm 10 coin gốc
    def_uni = D.default_universe()
    assert len(def_uni) == 10
    bases = [s.replace("@perp", "") for s in def_uni]
    assert set(bases) == set(D.UNIVERSE_BASES)

    # 2. scan_universe() trả đủ 100 coin
    scan_uni = D.scan_universe()
    assert len(scan_uni) == 100
    for b in D.UNIVERSE_BASES:
        assert b in scan_uni

    # 3. universe_scan.json phân hạng A, B, C và không có mã phi-crypto
    coins_meta = load_scan_universe()
    assert len(coins_meta) == 100
    grades = {c["grade"] for c in coins_meta}
    assert {"A", "B", "C"}.issubset(grades)

    # 4. instruments.json có spec của coin mới (vd: SUI, NEAR)
    for sym in ("NEAR", "SUI", "BTC", "ETH"):
        inst = get_instrument(sym)
        assert inst is not None
        assert inst.id.value.endswith(".OKX")
        assert inst.price_precision > 0
