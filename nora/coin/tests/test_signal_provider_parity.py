"""Decision parity fixtures for offline and incremental COIN signal providers."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

COIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COIN_ROOT))

from backend.analys.signal.compute import evaluate_signals
from backend.analys.signal.signal import ArraySignals, LiveSignals
from backend.analys.alpha.strategies import BY_ID, schema_defaults
from backend.analys.param import materialize


BASE_MS = 60_000
SIGNAL_MS = 5 * BASE_MS


def _candles(count: int) -> pd.DataFrame:
    open_time = np.arange(count, dtype=np.int64) * BASE_MS
    minute = np.arange(count, dtype=np.int64)
    # Each completed 5m close changes direction deterministically so the
    # independent oracle exercises both signal and no-signal outcomes.
    block = minute // 5
    close = 100.0 + np.where(block % 4 < 2, block, -block) + (minute % 5) * 0.01
    return pd.DataFrame({
        "open_time": open_time,
        "open": close - 0.01,
        "high": close + 0.02,
        "low": close - 0.02,
        "close": close,
        "volume": np.full(count, 10.0),
    })


def _aggregate_5m(candles: pd.DataFrame) -> pd.DataFrame:
    groups = candles.assign(group=candles["open_time"] // SIGNAL_MS * SIGNAL_MS)
    out = groups.groupby("group", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    return out.rename(columns={"group": "open_time"})


def _strategy() -> dict:
    return {
        "id": "fixture_close_rising",
        "side": "LONG",
        "tree": [[[
            {"frame": "5m", "column": "close", "index": 0},
            ">",
            {"frame": "5m", "column": "close", "index": 1},
        ]]],
        "stop": [],
        "position": {},
    }


def test_incremental_live_signals_match_array_signals_and_independent_oracle():
    candles = _candles(300)
    candle_5m = _aggregate_5m(candles)
    strategy = _strategy()
    offline = evaluate_signals(
        "BTC-USDT-SWAP",
        [strategy],
        {"1m": candles, "5m": candle_5m},
        "1m",
    )
    entry = offline["entries"][0]
    array = ArraySignals({
        "t": offline["t"].tolist(),
        "match": entry["match"].tolist(),
        "stop": entry["stop"].tolist(),
        "vol": None,
        "dca": None,
    }, BASE_MS)

    seed_count = 200
    seed_end_close = seed_count * BASE_MS
    seed_5m = candle_5m[
        candle_5m["open_time"] + SIGNAL_MS <= seed_end_close
    ].copy()
    live = LiveSignals(
        "BTC-USDT-SWAP",
        strategy,
        "1m",
        frames={
            "1m": candles.iloc[:seed_count].copy(),
            "5m": seed_5m,
        },
    )

    closes_5m = candle_5m.set_index("open_time")["close"]
    for i in range(seed_count, len(candles)):
        row = candles.iloc[i]
        close_ms = int(row["open_time"]) + BASE_MS
        live.on_base_bar(
            close_ms,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
        )

        expected = False
        if close_ms % SIGNAL_MS == 0:
            current_open = close_ms - SIGNAL_MS
            previous_open = current_open - SIGNAL_MS
            expected = bool(closes_5m[current_open] > closes_5m[previous_open])

        array_event = array.at(close_ms)
        live_event = live.at(close_ms)
        assert array_event is not None
        assert live_event is not None
        assert array_event["match"] is expected
        assert live_event["match"] is expected
        assert live_event["stop"] == array_event["stop"] is False
        assert live_event["dca"] == array_event["dca"] is True
        assert np.isnan(live_event["vol"])
        assert np.isnan(array_event["vol"])


def test_production_kema_live_signals_match_offline_provider():
    candidate = BY_ID["kema_long"]
    params = schema_defaults(candidate)
    params.update({"sig.signal_tf": "1m", "atr_frame": "1m"})
    strategy = materialize(candidate, params, regime=False)

    count = 420
    open_time = np.arange(count, dtype=np.int64) * BASE_MS
    minute = np.arange(count)
    close = (
        100.0
        + minute * 0.01
        + 2.0 * np.sin(minute / 8.0)
        + np.where(minute % 70 >= 40, 3.0, 0.0)
    )
    candles = pd.DataFrame({
        "open_time": open_time,
        "open": close - 0.03,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": np.full(count, 100.0),
    })
    offline = evaluate_signals(
        "BTC-USDT-SWAP",
        [strategy],
        {"1m": candles},
        "1m",
    )
    entry = offline["entries"][0]
    assert entry["match"].any()
    assert entry["stop"].any()

    seed_count = 360
    live = LiveSignals(
        "BTC-USDT-SWAP",
        strategy,
        "1m",
        frames={"1m": candles.iloc[:seed_count].copy()},
    )
    array = ArraySignals({
        "t": offline["t"].tolist(),
        "match": entry["match"].tolist(),
        "stop": entry["stop"].tolist(),
        "vol": entry["vol"].tolist() if entry.get("vol") is not None else None,
        "dca": entry["dca"].tolist() if entry.get("dca") is not None else None,
    }, BASE_MS)

    for i in range(seed_count, count):
        row = candles.iloc[i]
        close_ms = int(row["open_time"]) + BASE_MS
        live.on_base_bar(
            close_ms,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
        )
        live_event = live.at(close_ms)
        array_event = array.at(close_ms)
        assert live_event is not None
        assert array_event is not None
        assert live_event["match"] == array_event["match"]
        assert live_event["stop"] == array_event["stop"]
        assert live_event["dca"] == array_event["dca"]
        if np.isnan(array_event["vol"]):
            assert np.isnan(live_event["vol"])
        else:
            assert live_event["vol"] == pytest.approx(array_event["vol"], rel=1e-12, abs=1e-12)
