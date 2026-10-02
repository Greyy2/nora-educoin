import pytest
import numpy as np
import pandas as pd
from typing import Dict, Any

from backend.core.backtest.engine import BacktestEngine
from backend.core.params.schema import StrategyParams
from backend.core.execute.models import PositionStatus, PositionType


def make_dummy_candles(n_minutes: int = 1440 * 10, seed: int = 42, warmup_days: int = 2):
    """Tạo chuỗi nến 1m và 4h nhân tạo từ Geometric Brownian Motion (GBM) có warmup 4h trước."""
    rng = np.random.default_rng(seed)
    # Start at timestamp 1700000000000 (aligned to 4h)
    start_ts = 1700000000000
    start_ts = (start_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
    
    warmup_minutes = warmup_days * 1440
    total_minutes = warmup_minutes + n_minutes
    times_1m = [start_ts + i * 60_000 for i in range(total_minutes)]
    returns = rng.normal(0, 0.001, size=total_minutes)
    prices = 100.0 * np.exp(np.cumsum(returns))
    
    records_1m = []
    for i, t in enumerate(times_1m):
        c = prices[i]
        o = prices[i - 1] if i > 0 else c
        h = max(o, c) * (1 + abs(rng.normal(0, 0.0005)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.0005)))
        records_1m.append({
            "open_time": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": float(rng.uniform(10, 100)),
        })
    df_all_1m = pd.DataFrame(records_1m)
    
    # Aggregate to 4h
    df_temp = df_all_1m.copy()
    df_temp["dt"] = pd.to_datetime(df_temp["open_time"], unit="ms", utc=True)
    df_4h = (
        df_temp.set_index("dt")
        .resample("4h", closed="left", label="left")
        .agg({
            "open_time": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        .dropna()
        .reset_index(drop=True)
    )
    
    # df_1m bắt đầu sau khoảng warmup
    df_1m = df_all_1m.iloc[warmup_minutes:].reset_index(drop=True)
    return df_1m, df_4h


def create_test_engine(df_1m, df_4h, flow_config, using_match_price=False, stop_loss_rate=5.0, take_profit_rate=10.0):
    start_ts = int(df_1m["open_time"].min())
    end_ts = int(df_1m["open_time"].max())
    engine = BacktestEngine(account_id=0, campaign_id=0, symbol="TEST", start_ts=start_ts, end_ts=end_ts)
    for flow in flow_config["flows"]:
        flow_ast = dict(flow.get("ast", flow))
        flow_name = flow.get("id", "flow1")
        flow_type = flow.get("type", flow_ast.get("type", "LONG"))
        flow_ast["type"] = flow_type
        params = StrategyParams(
            name=flow_name,
            strategy="studio_ast",
            data_type="1m",
            using_match_price=using_match_price,
            max_open_trades=1,
            volume_rate=1.0,
            leverage=1,
            stop_loss_rate=stop_loss_rate,
            take_profit_rate=take_profit_rate,
            timeout=1440,
            extra={"ast": flow_ast, "type": flow_type},
        )
        engine.add_strategy_flow(flow_name, params)
    engine.df_1m = engine._prepare_candles(df_1m)
    engine.df_4h = engine._enrich_4h(engine._prepare_candles(df_4h))
    return engine


def test_no_lookahead_when_future_modified():
    """
    Test không look-ahead (Đợt 6.1):
    Chiến lược sử dụng cả 1m lẫn 4h (1m close > 4h close -> match, 1m close < 4h close -> stop).
    Đặt T lệch mốc 4h (T = mốc 4h + 2h).
    Khi sửa ngẫu nhiên mọi nến sau T:
    - 4h: mọi nến có open_time + 4 * 3600_000 > T
    - 1m: mọi nến có open_time >= T
    mọi lệnh có entry trước T phải hoàn toàn giữ nguyên (cùng enter_time, cùng enter_price).
    """
    df_1m, df_4h = make_dummy_candles(n_minutes=60 * 24 * 7, seed=123)
    
    flow_config = {
        "flows": [{
            "id": "flow1",
            "type": "LONG",
            "ast": {
                "match": [{
                    "condition": [
                        [[{"frame": "1m", "column": "close"}, ">", {"frame": "4h", "column": "close"}]]
                    ]
                }],
                "stop": [{
                    "condition": [
                        [[{"frame": "1m", "column": "close"}, "<", {"frame": "4h", "column": "close"}]]
                    ]
                }]
            }
        }]
    }
    
    engine1 = create_test_engine(df_1m.copy(), df_4h.copy(), flow_config)
    engine1.run()
    trades1 = engine1.closed_positions
    assert len(trades1) > 0, "Cần có ít nhất 1 trade để kiểm tra"
    
    # Chọn trade ở giữa, rồi đặt T = mốc 4h + 2h
    t_mid = trades1[len(trades1) // 2].enter_time
    h4_boundary = (t_mid // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
    T = h4_boundary + 2 * 3600 * 1000
    
    trades_before_T_1 = [
        (t.enter_time, t.enter_price) for t in trades1 if t.enter_time < T
    ]
    assert len(trades_before_T_1) > 0, "Cần có trade trước T"
    
    # Sửa toàn bộ dữ liệu tương lai sau T:
    # 4h: nến chưa đóng tại T (tức open_time + 4h > T)
    # 1m: nến có open_time >= T
    df_1m_mod = df_1m.copy()
    df_4h_mod = df_4h.copy()
    
    mask_1m = df_1m_mod["open_time"] >= T
    df_1m_mod.loc[mask_1m, "open"] *= 2.5
    df_1m_mod.loc[mask_1m, "high"] *= 2.5
    df_1m_mod.loc[mask_1m, "low"] *= 2.5
    df_1m_mod.loc[mask_1m, "close"] *= 2.5
    
    mask_4h = (df_4h_mod["open_time"] + 4 * 3600_000) > T
    df_4h_mod.loc[mask_4h, "open"] *= 2.5
    df_4h_mod.loc[mask_4h, "high"] *= 2.5
    df_4h_mod.loc[mask_4h, "low"] *= 2.5
    df_4h_mod.loc[mask_4h, "close"] *= 2.5
    
    engine2 = create_test_engine(df_1m_mod, df_4h_mod, flow_config)
    engine2.run()
    trades2 = engine2.closed_positions
    trades_before_T_2 = [
        (t.enter_time, t.enter_price) for t in trades2 if t.enter_time < T
    ]
    
    assert trades_before_T_1 == trades_before_T_2, (
        f"Lệnh trước T bị ảnh hưởng khi sửa tương lai sau T! "
        f"Trước T (gốc): {trades_before_T_1[:3]}... vs (sau sửa): {trades_before_T_2[:3]}..."
    )


def test_4h_lookahead_candle_visibility():
    """
    Test 4h lookahead:
    Nến 1m tại thời điểm 00:00 KHÔNG ĐƯỢC thấy nến 4h mở lúc 00:00 (vì nó chưa đóng cho tới 04:00).
    Chỉ nến 1m từ 04:00 trở đi mới được thấy nến 4h của 00:00 - 04:00.
    """
    df_1m, df_4h = make_dummy_candles(n_minutes=60 * 24 * 3, seed=999)
    first_1m_open = int(df_1m.iloc[0]["open_time"])
    # Tìm cây 4h mở đúng tại first_1m_open (ví dụ 00:00)
    matching_4h = df_4h[df_4h["open_time"] == first_1m_open]
    assert not matching_4h.empty
    target_4h_close = float(matching_4h.iloc[0]["close"])
    close_time_target_4h = first_1m_open + 4 * 3600_000
    
    # Chiến lược: Mở lệnh khi close_4h == target_4h_close
    flow_config = {
        "flows": [{
            "id": "flow4h",
            "type": "LONG",
            "ast": {
                "match": [{
                    "condition": [
                        [[{"frame": "4h", "column": "close"}, "==", target_4h_close]]
                    ]
                }],
                "stop": [{
                    "condition": [
                        [[{"frame": "1m", "column": "close"}, "<", 0.0]]
                    ]
                }]
            }
        }]
    }
    
    engine = create_test_engine(df_1m.copy(), df_4h.copy(), flow_config)
    engine.run()
    trades = engine.closed_positions
    assert len(trades) > 0, "Cần có ít nhất 1 trade để kiểm tra lookahead"
    
    first_entry = trades[0].enter_time
    # Cây 4h mở lúc first_1m_open chỉ đóng lúc close_time_target_4h (+4h).
    # Lệnh entry chỉ được phép diễn ra từ lúc nến 4h đóng trở đi (tức >= close_time_target_4h).
    assert first_entry >= close_time_target_4h, (
        f"LOOKAHEAD DETECTED: Lệnh mở tại {first_entry} khi nến 4h chưa đóng (đóng lúc {close_time_target_4h})!"
    )


def test_entry_at_next_candle_open():
    """
    Test 2.2: Tín hiệu match xuất hiện ở nến i thì nến i+1 mới được khớp tại giá open(i+1).
    Không được khớp ngay ở close(i) hay low(i).
    """
    df_1m, df_4h = make_dummy_candles(n_minutes=60 * 24 * 2, seed=777)
    
    # Giả sử điều kiện match chỉ đúng duy nhất tại nến thứ 10
    target_idx = 10
    target_candle_time = int(df_1m.iloc[target_idx]["open_time"])
    next_candle_time = int(df_1m.iloc[target_idx + 1]["open_time"])
    next_candle_open = float(df_1m.iloc[target_idx + 1]["open"])
    
    flow_config = {
        "flows": [{
            "id": "flow_single_match",
            "type": "LONG",
            "ast": {
                "match": [{
                    "condition": [
                        [[{"frame": "1m", "column": "open_time"}, "==", target_candle_time]]
                    ]
                }],
                "stop": [{
                    "condition": [
                        [[{"frame": "1m", "column": "open_time"}, "==", int(df_1m.iloc[target_idx + 5]["open_time"])]]
                    ]
                }]
            }
        }]
    }
    
    engine = create_test_engine(df_1m.copy(), df_4h.copy(), flow_config)
    engine.run()
    trades = engine.closed_positions
    assert len(trades) > 0, "Trade phải được thực hiện"
    trade = trades[0]
    
    # Causal rule: Signal on candle i -> Entry on candle i+1 at open(i+1)
    assert trade.enter_time == next_candle_time, (
        f"Lệnh phải khớp ở nến kế tiếp: enter_time {trade.enter_time} != {next_candle_time}"
    )


def test_gap_through_sl_fills_at_open():
    """
    Test 2.3: Một nến gap qua SL thì phải khớp ở giá open, không khớp ở giá SL (giả định bi quan).
    """
    df_1m, df_4h = make_dummy_candles(n_minutes=60, seed=111)
    
    # Vào lệnh ở nến 0 -> nến 1 khớp tại open
    # Tại nến 5, giá gap mạnh xuống dưới SL (open < SL)
    entry_p = float(df_1m.iloc[1]["open"])
    sl_rate = 5.0  # SL = entry_p * 0.95
    sl_target = entry_p * (1.0 - sl_rate / 100.0)
    gap_open_p = sl_target * 0.90 # Gap down sâu hơn SL
    
    df_1m.loc[5, "open"] = gap_open_p
    df_1m.loc[5, "high"] = gap_open_p * 1.01
    df_1m.loc[5, "low"] = gap_open_p * 0.98
    df_1m.loc[5, "close"] = gap_open_p * 0.99
    
    flow_config = {
        "flows": [{
            "id": "flow_gap",
            "type": "LONG",
            "ast": {
                "match": [{
                    "condition": [
                        [[{"frame": "1m", "column": "open_time"}, "==", int(df_1m.iloc[0]["open_time"])]]
                    ]
                }],
                "stop": []
            }
        }]
    }
    
    engine = create_test_engine(df_1m.copy(), df_4h.copy(), flow_config, stop_loss_rate=sl_rate)
    engine.run()
    trades = engine.closed_positions
    assert len(trades) > 0
    trade = trades[0]
    assert trade.status == PositionStatus.SL
    # Giá đóng phải là gap_open_p có slippage (0.0002), KHÔNG PHẢI sl_target
    expected_exit_price = gap_open_p * (1.0 - 0.0002)
    assert trade.close_price == pytest.approx(expected_exit_price, rel=1e-9), (
        f"SL phải khớp ở giá open thực tế khi gap: {trade.close_price} vs expected {expected_exit_price}"
    )
    assert trade.close_price < sl_target



