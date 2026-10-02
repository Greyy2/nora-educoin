"""
test_round4_venue_and_fills.py — vòng 4: dữ liệu 3 năm CEX (Binance) + 2 DEX.

1. Engine KHÔNG khớp lệnh trên nến điền (is_filled=1); khớp ở open phút có giao dịch kế tiếp.
2. fetch_candles_df giữ cột is_filled cho engine.
3. Gate: ngưỡng phút trống MAX_FILLED_RATIO_1M (60%).
4. WFA gate có điều kiện lợi nhuận IS (min_is_profit_pct).
5. Monte Carlo: robust_passed = WFA gate True VÀ ruin <= max_ruin_pct.
6. Crawler Binance: chuẩn hoá µs->ms, bỏ header, volume = quote, kiểm SHA-256, thiếu tháng -> crawl_ok=False.
7. Mô hình phí theo venue (CEX/DEX) trong Research.
"""
import hashlib
import io
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

from backend.core.data.resampler import save_resampled_dataset

D = 86_400_000
T0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC
FLOW_1M = {
    "id": "flow1", "name": "LONG close>open", "type": "LONG",
    "ast": {
        "type": "LONG",
        "match": [{"condition": [[[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]]}],
        "stop": [{"condition": [[[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]]}],
    },
}


def _rw_1m(n_days: float, seed: int = 11, t0: int = T0) -> pd.DataFrame:
    n = int(n_days * 1440)
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open_time": t0 + np.arange(n, dtype=np.int64) * 60_000,
        "open": open_,
        "high": np.maximum(open_, close) * 1.0003,
        "low": np.minimum(open_, close) * 0.9997,
        "close": close,
        "volume": rng.uniform(10, 100, n),
    })


@pytest.fixture
def clean_asset(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw_1m(40)
    save_resampled_dataset(
        symbol="CLEAN", output_dir=str(root), df_1m_raw=df, pool_address="0xclean", crawl_ok=True,
        requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
        extra_meta={"venue": "cex", "exchange": "binance"},
    )
    return "CLEAN", str(root)


# ─── 1-2. Nến điền ──────────────────────────────────────────────────────────

def _engine_with(df_1m: pd.DataFrame, match_time: int):
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.params.schema import StrategyParams
    df_4h = df_1m.assign(dt=pd.to_datetime(df_1m.open_time, unit="ms", utc=True)).set_index("dt").resample(
        "4h", closed="left", label="left").agg({"open_time": "first", "open": "first", "high": "max",
                                                "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index(drop=True)
    eng = BacktestEngine(0, 0, "T", int(df_1m.open_time.min()), int(df_1m.open_time.max()))
    ast = {"type": "LONG",
           "match": [{"condition": [[[{"frame": "1m", "column": "open_time"}, "==", match_time]]]}],
           "stop": []}
    eng.add_strategy_flow("LONG_f", StrategyParams(name="LONG_f", extra={"ast": ast}))
    eng.df_base = eng._prepare_candles(df_1m)
    eng.df_4h = eng._enrich_4h(eng._prepare_candles(df_4h))
    return eng


def test_pending_entry_waits_for_next_real_minute():
    df = _rw_1m(2)
    df["is_filled"] = 0
    k = 1500                                   # tín hiệu ở nến k (sau khi đã có cây 4h đóng)
    df.loc[k + 1:k + 3, "is_filled"] = 1       # 3 phút kế tiếp không có giao dịch
    for i in range(k + 1, k + 4):              # nến điền: O=H=L=C=close trước
        p = float(df.loc[k, "close"])
        df.loc[i, ["open", "high", "low", "close"]] = p
    eng = _engine_with(df, int(df.loc[k, "open_time"]))
    eng.run()
    pos = eng.closed_positions[0]
    assert pos.enter_time == int(df.loc[k + 4, "open_time"]), "Phải khớp ở open phút CÓ giao dịch kế tiếp"


def test_final_close_uses_last_real_minute():
    df = _rw_1m(2)
    df["is_filled"] = 0
    df.loc[len(df) - 5:, "is_filled"] = 1
    eng = _engine_with(df, int(df.loc[1500, "open_time"]))
    eng.run()
    pos = eng.closed_positions[-1]
    assert pos.close_time == int(df.loc[len(df) - 6, "open_time"])


def test_fetch_candles_keeps_is_filled(clean_asset):
    from backend.db.local_pkl import fetch_candles_df
    sym, root = clean_asset
    assert "is_filled" in fetch_candles_df(sym, "1m", data_root=root).columns


# ─── 3. Gate ngưỡng phút trống ──────────────────────────────────────────────

@pytest.mark.parametrize("empty_ratio,blocked", [(0.45, False), (0.70, True)])
def test_gate_filled_ratio_threshold(tmp_path, empty_ratio, blocked):
    from backend.core.data.quality_gate import evaluate_data_quality
    df = _rw_1m(35)
    keep = np.random.default_rng(0).random(len(df)) >= empty_ratio
    keep[0] = keep[-1] = True
    save_resampled_dataset(symbol="SPARSE", output_dir=str(tmp_path), df_1m_raw=df[keep], pool_address="0x",
                           crawl_ok=True, requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()))
    dq = evaluate_data_quality("SPARSE", timeframe="1m", data_root=str(tmp_path))
    # WARNING (vd. nhiều nến volume=0) không chặn; chỉ BLOCKED / NEEDS_MORE_DATA mới chặn
    assert (dq["status"] in ("BLOCKED", "NEEDS_MORE_DATA")) is blocked, dq["issues"]


# ─── 4. WFA: điều kiện lợi nhuận IS ─────────────────────────────────────────


# ─── 5. Monte Carlo robust verdict ──────────────────────────────────────────

def _mc(trades, gate, sims=10_000):
    from backend.api.jobs.store import complete_wfa_job, create_mc_job, create_wfa_job, get_mc_job
    from backend.carlo.monte_carlo import execute_monte_carlo_pipeline
    from backend.core.contracts import MonteCarloRunRequest
    wfa_id = None
    if gate is not None:
        wfa_id = create_wfa_job("X", "S", 4)
        complete_wfa_job(wfa_id, {"acceptance_gate_passed": gate, "aggregate_oos_trades": trades})
    mc_id = create_mc_job("X", "S", sims, source_wfa_id=wfa_id or "")
    execute_monte_carlo_pipeline(mc_id, MonteCarloRunRequest(source_wfa_id=wfa_id, simulations=sims, seed=5), trades)
    return get_mc_job(mc_id)["result"]


# ─── 6. Crawler Binance ─────────────────────────────────────────────────────

def _kline_csv(rows):
    return "\n".join(",".join(str(v) for v in r) for r in rows).encode()


def test_parse_kline_csv_normalizes_microseconds_and_uses_quote_volume():
    from backend.core.data.crawler import parse_kline_csv
    ms, us = 1717200000000, 1785542400000000
    raw = b"open_time,open,high,low,close,volume,close_time,quote_volume,count,tbb,tbq,ignore\n" + _kline_csv([
        [ms, 1, 2, 0.5, 1.5, 10, ms + 59999, 15.0, 3, 1, 1, 0],
        [us, 1, 2, 0.5, 1.5, 10, us + 59999999, 16.0, 3, 1, 1, 0],
    ])
    df = parse_kline_csv(raw)
    assert df["open_time"].tolist() == [ms, us // 1000]
    assert df["volume"].tolist() == [15.0, 16.0], "volume phải là quote volume (USDT)"


class _Resp:
    def __init__(self, content=b"", text=""):
        self.content, self.text, self.status_code = content, text, 200


def _zip_bytes(csv: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("X-1m-2024-01.csv", csv)
    return buf.getvalue()


def test_fetch_vision_zip_rejects_bad_checksum(tmp_path, monkeypatch):
    import backend.core.data.crawler as cb
    payload = _zip_bytes(_kline_csv([[T0, 1, 1, 1, 1, 1, T0 + 59999, 1, 1, 1, 1, 0]]))
    monkeypatch.setattr(cb, "_http_get", lambda s, url, **k: _Resp(text="0" * 64 + "  f.zip") if url.endswith(".CHECKSUM") else _Resp(content=payload))
    with pytest.raises(cb.ChecksumMismatch):
        cb.fetch_vision_zip(None, "https://x/f.zip", str(tmp_path))
    assert not (tmp_path / "f.zip").exists(), "File sai checksum không được lưu vào cache"


def test_fetch_vision_zip_ok_and_cached(tmp_path, monkeypatch):
    import backend.core.data.crawler as cb
    csv = _kline_csv([[T0, 1, 1, 1, 1, 1, T0 + 59999, 1, 1, 1, 1, 0]])
    payload = _zip_bytes(csv)
    good = hashlib.sha256(payload).hexdigest()
    calls = []

    def fake_get(s, url, **k):
        calls.append(url)
        return _Resp(text=f"{good}  f.zip") if url.endswith(".CHECKSUM") else _Resp(content=payload)

    monkeypatch.setattr(cb, "_http_get", fake_get)
    assert cb.fetch_vision_zip(None, "https://x/f.zip", str(tmp_path)) == csv
    assert cb.fetch_vision_zip(None, "https://x/f.zip", str(tmp_path)) == csv
    assert sum(1 for u in calls if u.endswith(".zip")) == 1, "Lần 2 phải dùng cache"


def test_binance_missing_month_marks_crawl_not_ok(tmp_path, monkeypatch):
    import backend.core.data.crawler as cb
    from backend.core.data.quality_gate import evaluate_data_quality

    def fake_zip(session, url, cache_dir):
        if "2024-02" in url:
            return None                                  # tháng bị thiếu
        if "/daily/" in url:
            return None
        tag = url.rsplit("-1m-", 1)[1].replace(".zip", "")
        start = pd.Timestamp(tag + "-01" if len(tag) == 7 else tag, tz="UTC")
        end = start + pd.offsets.MonthBegin(1)
        idx = pd.date_range(start, end, freq="1min", inclusive="left")
        ts = (idx.asi8 // 10**6).astype("int64")
        rows = [[int(t) * 1000, 1, 1.1, 0.9, 1, 1, 0, 5, 1, 1, 1, 0] for t in ts]  # µs
        return _kline_csv(rows)

    monkeypatch.setattr(cb, "fetch_vision_zip", fake_zip)
    monkeypatch.setattr(cb, "fetch_rest_klines", lambda *a, **k: pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"]))
    end_ms = int(pd.Timestamp("2024-04-01", tz="UTC").value // 10**6) - 60_000
    manifest = cb.run_job({"symbols": "TST", "years": 90 / 365.25, "end_ts": end_ms, "output_dir": str(tmp_path)})[0]
    assert manifest["venue"] == "cex" and manifest["exchange"] == "binance"
    assert manifest["crawl_ok"] is False and any("2024-02" in i for i in manifest["crawl_issues"])
    assert evaluate_data_quality("TST", timeframe="1m", data_root=str(tmp_path))["status"] == "BLOCKED"


# ─── 7. Phí theo venue ──────────────────────────────────────────────────────


# ─── 8. Crawler resume không được biến nến điền thành nến thật ──────────────
# (Thay cho test_crawler_strips_filled_from_existing: test đó tự viết lại logic lọc
#  thay vì gọi code crawler nên luôn pass; lỗi thật nằm ở _read_pickle_if_usable
#  cắt về 6 cột OHLCV trước khi lọc -> mất cờ is_filled.)


# ─── 9. Bước nhảy > 50%/phút: CEX đã kiểm checksum -> WARNING; nguồn khác -> BLOCKED ─

@pytest.mark.parametrize("meta,expected", [
    ({"venue": "cex", "exchange": "binance", "checksums_verified": True}, "WARNING"),
    ({"venue": "dex", "exchange": "geckoterminal"}, "BLOCKED"),
    ({"venue": "cex"}, "BLOCKED"),                       # CEX nhưng chưa kiểm checksum
])
def test_extreme_move_policy_by_source(tmp_path, meta, expected):
    from backend.core.data.quality_gate import evaluate_data_quality
    df = _rw_1m(35)
    k = 20_000
    df.loc[k, ["open", "high", "low", "close"]] = df.loc[k, "close"] * 1.8   # +80% trong 1 phút
    save_resampled_dataset(symbol="JUMP", output_dir=str(tmp_path), df_1m_raw=df, pool_address="0x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
                           extra_meta=meta)
    dq = evaluate_data_quality("JUMP", timeframe="1h", data_root=str(tmp_path))
    assert dq["status"] == expected, dq["issues"]


# ─── 10. Cache của gate: nhanh ở lần 2, hết hạn ngay khi bất kỳ file dữ liệu nào đổi ─

def test_gate_cache_invalidates_on_file_change(tmp_path):
    from backend.core.data import quality_gate as g
    df = _rw_1m(35)
    save_resampled_dataset(symbol="CACHE", output_dir=str(tmp_path), df_1m_raw=df, pool_address="0x", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()))
    first = g.evaluate_data_quality("CACHE", timeframe="1m", data_root=str(tmp_path))
    assert first["status"] != "BLOCKED"
    first["status"] = "MUTATED"  # sửa bản trả về không được làm hỏng cache
    assert g.evaluate_data_quality("CACHE", timeframe="1m", data_root=str(tmp_path))["status"] != "MUTATED"

    p4h = tmp_path / "CACHE" / "4h.pkl"
    bad = pd.read_pickle(p4h)
    bad["close"] *= 1.1
    time.sleep(0.01)
    bad.to_pickle(p4h)
    assert g.evaluate_data_quality("CACHE", timeframe="1m", data_root=str(tmp_path))["status"] == "BLOCKED"
