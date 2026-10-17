"""Kiểm thử tự động cho kiểm tra đồng nhất 4 tầng (P18 B2-B5)."""
import json
import os
import pytest
import pandas as pd

from test.scripts.parity_live import (
    load_live_bars,
    load_live_events,
    check_level1_data,
    check_level2_signals,
    check_level3_orders,
    check_level4_slippage,
    run_full_parity,
)


@pytest.fixture
def mock_bot_dir(tmp_path):
    bot_dir = tmp_path / "bot_test_parity"
    bot_dir.mkdir()

    # Tạo bot.json
    meta = {
        "bot_id": "bot_test_parity",
        "mode": "paper",
        "capital": 1000.0,
        "launch_params": {
            "strategies": [{"id": "test_strat", "symbols": ["BTC-USDT-SWAP"]}],
            "symbols": ["BTC-USDT-SWAP"],
            "base_frame": "1m",
        },
        "base_frame": "1m",
    }
    with open(bot_dir / "bot.json", "w") as f:
        json.dump(meta, f)

    # Tạo bars.jsonl
    base_ts = 1700000000000
    bars = []
    for i in range(10):
        t_open = base_ts + i * 60000
        t_close = t_open + 60000
        bars.append({
            "symbol": "BTC-USDT-SWAP",
            "ts_open": t_open,
            "ts_close": t_close,
            "open": 50000.0 + i * 10,
            "high": 50020.0 + i * 10,
            "low": 49990.0 + i * 10,
            "close": 50015.0 + i * 10,
            "volume": 1.5,
        })
    with open(bot_dir / "bars.jsonl", "w") as f:
        for b in bars:
            f.write(json.dumps(b) + "\n")

    # signals.jsonl: nến 0 có match (vào lệnh), nến 1 có stop (thoát); ts = giờ đóng nến
    sigs = [{"ts": base_ts + (i + 1) * 60000, "symbol": "BTC-USDT-SWAP", "slot": "test_strat", "match": i == 0, "stop": i == 1, "dca": True} for i in range(10)]
    with open(bot_dir / "signals.jsonl", "w") as f:
        for r in sigs:
            f.write(json.dumps(r) + "\n")

    # Tạo events.jsonl
    events = [
        {"t": base_ts + 60000, "type": "signal", "symbol": "BTC-USDT-SWAP", "open_ms": base_ts},
        {"t": base_ts + 60700, "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "test_strat", "px": 50015.5, "qty": 0.01, "side": "BUY", "kind": "ENTRY", "ts": base_ts + 60700, "catchup": False},
        {"t": base_ts + 120000, "type": "signal", "symbol": "BTC-USDT-SWAP", "open_ms": base_ts + 60000},
        {"t": base_ts + 120650, "type": "fill", "symbol": "BTC-USDT-SWAP", "strategy": "test_strat", "px": 50025.2, "qty": 0.01, "side": "SELL", "kind": "EXIT", "ts": base_ts + 120650, "catchup": False},
    ]
    with open(bot_dir / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    return str(bot_dir)


BASE_TS = 1700000000000


def _rest(symbol, lo, hi):
    """REST giả: đúng các nến 1m của bars.jsonl (open/high/low/close giống hệt)."""
    rows = [{"open_time": BASE_TS + i * 60000, "open": 50000.0 + i * 10, "high": 50020.0 + i * 10, "low": 49990.0 + i * 10, "close": 50015.0 + i * 10, "volume": 1.0} for i in range(10)]
    return pd.DataFrame(rows)


def _recompute(symbol, strategy, frame):
    return {BASE_TS + i * 60000: (i == 0, i == 1, True) for i in range(10)}


STRATS = [{"id": "test_strat"}]


def test_parity_all_tiers_pass_with_data(mock_bot_dir):
    res = run_full_parity(mock_bot_dir, rest_fetch=_rest, recompute=_recompute, strategies=STRATS)
    assert res["level1_data"]["status"] == "PASS" and res["level1_data"]["bars_checked"] == 10
    assert res["level2_signals"]["status"] == "PASS" and res["level2_signals"]["signals_checked"] == 10
    assert res["level3_orders"]["status"] == "PASS" and res["level3_orders"]["orders_checked"] >= 2
    assert res["level4_slippage"]["status"] == "PASS" and res["level4_slippage"]["median_bps"] <= 3.0
    assert res["ok"] is True and res["insufficient"] == []


def test_parity_detects_data_and_signal_mismatch(mock_bot_dir):
    bad_rest = lambda s, lo, hi: _rest(s, lo, hi).assign(close=lambda d: d["close"] + 5.0)
    assert run_full_parity(mock_bot_dir, rest_fetch=bad_rest, recompute=_recompute, strategies=STRATS)["level1_data"]["status"] == "FAIL"
    flipped = lambda s, st, f: {t: (not m, sp, d) for t, (m, sp, d) in _recompute(s, st, f).items()}
    res = run_full_parity(mock_bot_dir, rest_fetch=_rest, recompute=flipped, strategies=STRATS)
    assert res["level2_signals"]["status"] == "FAIL" and res["ok"] is False


def test_parity_empty_bot_is_insufficient_not_pass(tmp_path):
    d = tmp_path / "bot_empty"
    d.mkdir()
    (d / "bot.json").write_text(json.dumps({"bot_id": "bot_empty", "base_frame": "1h"}))
    res = run_full_parity(str(d), rest_fetch=_rest, recompute=_recompute, strategies=STRATS)
    for k in ("level1_data", "level2_signals", "level3_orders", "level4_slippage"):
        assert res[k]["status"] == "INSUFFICIENT" and res[k]["ok"] is False, k
    assert res["ok"] is False and res["insufficient"] == [1, 2, 3, 4]


def test_parity_min_bars(mock_bot_dir):
    res = run_full_parity(mock_bot_dir, min_bars=11, rest_fetch=_rest, recompute=_recompute, strategies=STRATS)      # chỉ có 10 nến
    assert res["level1_data"]["status"] == "INSUFFICIENT" and res["level2_signals"]["status"] == "INSUFFICIENT" and res["ok"] is False
    assert run_full_parity(mock_bot_dir, min_bars=10, rest_fetch=_rest, recompute=_recompute, strategies=STRATS)["ok"] is True


def test_parity_match_bar_without_order_fails(mock_bot_dir):
    ev = os.path.join(mock_bot_dir, "events.jsonl")
    rows = [json.loads(x) for x in open(ev)]
    rows = [r for r in rows if not (r["type"] == "fill" and r["kind"] == "ENTRY")]
    with open(ev, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    l3 = check_level3_orders(mock_bot_dir, load_live_bars(mock_bot_dir), load_live_events(mock_bot_dir))
    assert l3["status"] == "FAIL" and any(m["kind"] == "match_without_order" for m in l3["mismatches"])
