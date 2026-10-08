"""
test_okx_data.py — dữ liệu theo sàn (data/<okx|binance>/...) + crawler OKX (không gọi mạng).

- default_data_root = data/<NORA_EXCHANGE> (mặc định okx); NORA_LOCAL_DATA_ROOT vẫn ghi đè; cache dùng chung data/_cache.
- exchange_of(manifest): okx_swap -> okx, binance_usdm -> binance.
- Parse file ngày OKX (nến: volume = vol_quote USDT; funding: real_funding_rate).
- Funding: mốc OKX ưu tiên, khoảng trống > 16h lấp bằng proxy Binance và ghi vào manifest.
- promote: staging/cex/<SYM>/perp -> data/market/okx/cex/<SYM>/perp theo manifest; quality gate coi API chính thức OKX là nguồn đã kiểm chứng.
"""
import io
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from backend.crawl import cex as oc
from backend.crawl import store as dl

H = 3_600_000
T0 = 1_704_067_200_000   # 2024-01-01 00:00Z


def test_exchange_root(monkeypatch):
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.delenv("NORA_DATA_ROOT", raising=False)
    monkeypatch.delenv("NORA_EXCHANGE", raising=False)
    assert dl.default_data_root() == os.path.join(dl.DATA_HOME, "market", "okx")
    monkeypatch.setenv("NORA_EXCHANGE", "binance")
    assert dl.default_data_root() == os.path.join(dl.DATA_HOME, "market", "binance")
    assert dl.cache_dir(None, "x").startswith(os.path.join(dl.DATA_HOME, "cache", "process"))
    os.rmdir(dl.cache_dir(None, "x"))
    monkeypatch.setenv("NORA_EXCHANGE", "kraken")
    with pytest.raises(ValueError):
        dl.default_data_root()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", "/tmp/x")
    assert dl.default_data_root() == "/tmp/x" and dl.exchange_root("binance") == "/tmp/x"


def test_exchange_of(monkeypatch):
    monkeypatch.delenv("NORA_EXCHANGE", raising=False)
    assert dl.exchange_of({"exchange": "okx_swap"}) == "okx"
    assert dl.exchange_of({"exchange": "binance_usdm"}) == "binance"
    assert dl.exchange_of({"exchange": "geckoterminal"}) == "okx"
    assert dl.exchange_of(None) == "okx"


def test_parse_okx_files():
    csv = ("instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm\n"
           "BTC-USDT-SWAP,1,2,0.5,1.5,10,0.1,15.5,1705248000000,0\n"
           "ETH-USDT-SWAP,1,2,0.5,1.5,10,0.1,99,1705248000000,0\n")
    df = oc.parse_candles_csv(csv.encode(), "BTC")
    assert len(df) == 1 and df.iloc[0]["volume"] == 15.5 and df.iloc[0]["open_time"] == 1705248000000
    sr = "contract_type/\xb7\xd1,funding_rate/x,real_funding_rate/y,funding_time/z\nSWAP,0.0002,0.0001,1705334400000\n".encode("latin1")
    f = oc.parse_swaprate_csv(sr)
    assert f.iloc[0]["rate"] == 0.0001 and f.iloc[0]["funding_time"] == 1705334400000


def test_hk_days_cover_utc_range():
    days = oc._hk_days(T0, T0 + 24 * H - 60_000)
    lo, _ = oc._hk_day_range(days[0])
    _, hi = oc._hk_day_range(days[-1])
    assert lo <= T0 and hi >= T0 + 24 * H - 60_000 and len(days) == 2


def test_funding_gaps_filled_by_binance_proxy(tmp_path, monkeypatch):
    end = T0 + 10 * 8 * H
    okx_times = [T0 + i * 8 * H for i in (0, 1, 2, 7, 8, 9, 10)]       # thiếu mốc 3..6 -> một khoảng trống
    monkeypatch.setattr(oc, "fetch_day_zip", lambda *a, **k: None)
    monkeypatch.setattr(oc, "_okx_get", lambda s, path, p, pause: [] if "after" in p else
                        [{"fundingTime": str(t), "realizedRate": "0.0001", "fundingRate": "0.0002"} for t in okx_times])
    bpath = tmp_path / "funding.pkl"
    pd.DataFrame({"funding_time": [T0 + i * 8 * H + 1 for i in range(11)], "interval_h": np.nan, "rate": 0.0005}).to_pickle(bpath)
    df, meta, issues = oc.okx_crawl_funding(None, "BTC", T0, end, str(tmp_path), 1, str(bpath))
    assert not issues
    assert meta["sources"] == {"okx_rest": 7, "binance_proxy": 4} and len(meta["proxy_ranges"]) == 1
    assert (df.set_index("funding_time")["rate"].loc[okx_times] == 0.0001).all()
    assert df["funding_time"].is_monotonic_increasing and len(df) == 11


def _zip(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def test_crawl_writes_okx_layout_and_promotes(tmp_path, monkeypatch):
    """Crawl giả (file ngày + REST) -> staging/cex/BTC/perp; promote -> data/market/okx/cex/BTC/perp; gate APPROVED dù có bước nhảy > 50%."""
    monkeypatch.delenv("NORA_EXCHANGE", raising=False)
    start, n = T0, 31 * 1440
    end = start + (n - 1) * 60_000
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    close[20000:] *= 1.8                                                 # bước nhảy thật > 50% trong 1 phút
    frame = pd.DataFrame({"open_time": start + np.arange(n) * 60_000, "close": close})

    def day_zip(session, kind, base, d, cache_dir):
        lo, hi = oc._hk_day_range(d)
        if kind == "swaprate" or d == oc._hk_days(start, end)[-1]:
            return None                                                  # ngày cuối: chưa phát hành -> REST
        part = frame[frame.open_time.between(lo, hi)]
        rows = "".join(f"BTC-USDT-SWAP,{c},{c * 1.001},{c * 0.999},{c},1,1,{c * 10},{t},0\n" for t, c in zip(part.open_time, part.close))
        return ("instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm\n" + rows).encode()

    def okx_get(session, path, p, pause):
        if "funding" in path:
            return [] if "after" in p else [{"fundingTime": str(start + i * 8 * H), "realizedRate": "0.0001"} for i in range(93)]
        part = frame[(frame.open_time < p["after"])].tail(100)
        return [[str(t), str(c), str(c * 1.001), str(c * 0.999), str(c), "1", "1", str(c * 10), "1"]
                for t, c in zip(part.open_time[::-1], part.close[::-1])]

    monkeypatch.setattr(oc, "fetch_day_zip", day_zip)
    monkeypatch.setattr(oc, "_okx_get", okx_get)
    staging = tmp_path / "staging"
    out = oc.okx_run_job({"symbols": "BTC", "years": (n - 1) / 1440 / 365.25, "end_ts": end, "output_dir": str(staging / "cex"),
                      "cache_dir": str(tmp_path / "c"), "workers": 2})
    m = out[0]
    assert m["exchange"] == "okx_swap" and m["official_api"] is True and m["symbol"] == "BTC@perp"
    assert m["rows"]["1m"] == n and m["filled_ratio_1m"] == 0.0 and m["source_files"]["rest_rows"] > 0
    assert m["volume_unit"] == "quote_usdt" and m["funding"]["sources"] == {"okx_rest": 93}

    from backend.crawl import store as promote
    from backend.crawl.store import DataQualityStatus, evaluate_data_quality
    dq = evaluate_data_quality("BTC@perp", timeframe="1m", data_root=str(staging))
    assert dq["status"] not in (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA), dq["issues"]
    data = tmp_path / "data"
    res = promote.run_job({"staging": str(staging), "data": str(data), "apply": True})
    assert [a["dst"] for a in res["actions"]] == [str(data / "okx" / "cex" / "BTC" / "perp")]
    man = promote.manifest_of_dir(str(data / "okx" / "cex" / "BTC" / "perp"))
    assert man["exchange"] == "okx_swap" and os.path.exists(data / "okx" / "cex" / "BTC" / "perp" / "funding.pkl")
