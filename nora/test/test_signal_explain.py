"""Biểu đồ tín hiệu (metrics/charts.py::explain + /api/studio/chart/explain): điểm tín hiệu = cạnh lên của tín hiệu engine, mỗi điều kiện
mang giá trị hai vế và đúng/sai khớp phép so sánh, đường chỉ báo tách đúng thang (giá vs dao động)."""
import numpy as np
import pytest

from backend.metrics import charts as se
from backend.crawl.store import CandleLoader
from backend.core import backtest as bt
from test_strategy_book import T0, market  # noqa: F401  (market là fixture: 70 ngày, 3 tài sản)

DAY = 86_400_000
F = lambda fr, c, i=0: {"frame": fr, "column": c, "index": i}  # noqa: E731
POS = {"market": "perp", "leverage": 5, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14, "sizing": "risk", "risk_per_trade_pct": 1.0,
       "max_notional_pct": 300.0, "stop_loss_rate": 2.0, "take_profit_rate": 3.0, "timeout": 600, "cooldown": 60}
ST = {"id": "x", "side": "LONG", "position": POS,
      "tree": [[[F("1h", "rsi_14"), "<", 40], [F("1h", "close"), ">", F("4h", "ema_20")]], [[F("1h", "close"), "<", F("1h", "bbl_20_2")]]],
      "stop": [{"condition": [[[F("1h", "rsi_14"), ">", 70]]]}]}


def test_explain_signals_match_engine_and_conditions(market):
    sym, end = "BBB@perp", T0 + 68 * DAY
    frames = {fr: CandleLoader(sym, frame=fr, use_cache=False).load_data(0, end) for fr in bt.required_frames(sym, [ST], "1h")}
    ref = bt.evaluate_signals(sym, [ST], frames, "1h")
    start = int(ref["t"][300])
    out = se.explain(sym, ST, "1h", frames, start, end)
    t = ref["t"]
    win = (t >= start) & (t <= end)
    m = np.asarray(ref["entries"][0]["match"])[win]
    rising = int((m & ~np.r_[False, m[:-1]]).sum())
    entries = [s for s in out["signals"] if s["kind"] == "entry"]
    assert rising > 0 and len(entries) == rising
    assert len(out["candles"]) == int(win.sum()) and out["candles"][0]["t"] == start // 1000
    ops = {"<": np.less, ">": np.greater}
    for s in entries:
        assert s["blocks_ok"], "điểm vào phải có ít nhất một khối AND đúng hết"
        for c in s["conditions"]:
            if c["left"] is not None and c["right"] is not None:
                assert c["ok"] == bool(ops[c["op"]](c["left"], c["right"]))
    names = {o["name"] for o in out["overlays"]}
    osc = {o["name"]: o["levels"] for o in out["oscillators"]}
    assert "EMA 20 [4h]" in names and "Bollinger dưới 20 / 2 [1h]" in names
    assert osc["RSI 14 [1h]"] == [40.0, 70.0]
    assert out["conditions"]["exit"] == [["RSI 14 [1h] > 70"]]
    assert any(s["kind"] == "exit" for s in out["signals"]) or not np.asarray(ref["entries"][0]["stop"])[win].any()


def test_explain_window_outside_data_raises(market):
    sym = "BBB@perp"
    frames = {fr: CandleLoader(sym, frame=fr, use_cache=False).load_data(0, T0 + 68 * DAY) for fr in bt.required_frames(sym, [ST], "1h")}
    with pytest.raises(ValueError):
        se.explain(sym, ST, "1h", frames, T0 + 400 * DAY, T0 + 401 * DAY)


def test_labels_are_readable():
    node = {**F("4h", "ema_50"), "add": {"type": "calculate", "number_1": F("4h", "atr_14"), "logic": "*", "number_2": 2.5}}
    assert se.label(node) == "EMA 50 [4h] + (ATR 14 [4h] * 2.5)"
    assert se.label(F("1h", "close", 1)) == "Giá đóng [1h] (trước 1 nến)"
