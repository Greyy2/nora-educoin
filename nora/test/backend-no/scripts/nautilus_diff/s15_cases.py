"""Synthetic test cases for S15 (Pure Core Execution Engine Parity).
Defines deterministic 1m bar series and action/order configurations across 9 categories.
"""
import pandas as pd
from s15_common import M, T0_MS


def make_bars(ohlc_list, t0=T0_MS):
    """Build a 1m DataFrame from a list of (open, high, low, close) tuples."""
    rows = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        rows.append({
            "open_time": t0 + i * M,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


# 9 Test Categories
CASES = {
    # 1. Cơ bản: market, limit chạm đúng mức, limit thiếu 1 tick
    "C1a_market": {
        "desc": "Lệnh market vào vị thế ở open",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),  # bar 0: trigger
            (100.0, 101.0, 99.5, 100.5),   # bar 1: entry fills at open 100.0
            (100.5, 101.0, 100.0, 100.8),  # bar 2
        ]),
        "sl": 0.0, "tp": 0.0, "dca": None, "trail": None,
    },
    "C1b_limit_touch": {
        "desc": "Limit TP chạm đúng mức trong nến",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.2),   # entry @100.0
            (100.2, 102.0, 100.0, 101.5),  # High touches exactly TP 102.0 (+2%)
        ]),
        "sl": 0.0, "tp": 2.0, "dca": None, "trail": None,
    },
    "C1c_limit_miss": {
        "desc": "Limit TP thiếu 0.01 không khớp",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.2),   # entry @100.0
            (100.2, 101.99, 100.0, 101.5), # High reaches 101.99, TP=102.0 -> miss
        ]),
        "sl": 0.0, "tp": 2.0, "dca": None, "trail": None,
    },

    # 2. Limit + Stop cùng nến: Limit TRÊN Stop (ca A) & Limit DƯỚI Stop (ca B)
    "C2a_long_dca_above_sl": {
        "desc": "LONG: DCA 99.0 trên SL 98.0, nến rơi 96.0",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 100.0, 96.0, 96.0),    # drops to 96.0: DCA 99 fills, then SL 98 triggers
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [1.0], "mults": [1.0]}, "trail": None,
    },
    "C2b_long_dca_below_sl": {
        "desc": "LONG ca B: DCA 97.0 dưới SL 98.0, nến rơi 96.0",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 100.0, 96.0, 96.0),    # drops to 96.0: DCA 97 fills, then SL 98 triggers
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [3.0], "mults": [1.0]}, "trail": None,
    },
    "C2a_short_dca_above_sl": {
        "desc": "SHORT: DCA 101.0 trước SL 102.0, nến giật 104.0",
        "side": "SHORT",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.2, 99.5, 100.0),   # entry @100.0
            (100.0, 104.0, 100.0, 104.0),  # rises to 104.0: DCA 101 fills, then SL 102 triggers
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [1.0], "mults": [1.0]}, "trail": None,
    },
    "C2b_short_dca_below_sl": {
        "desc": "SHORT ca B: DCA 103.0 sau SL 102.0, nến giật 104.0",
        "side": "SHORT",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.2, 99.5, 100.0),   # entry @100.0
            (100.0, 104.0, 100.0, 104.0),  # rises to 104.0: DCA 103 fills, then SL 102 triggers
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [3.0], "mults": [1.0]}, "trail": None,
    },

    # 3. Nhiều tầng limit cùng bị vượt trong một chặng
    "C3_multi_limit_cross": {
        "desc": "3 tầng DCA (99, 98, 97) cùng bị vượt khi nến rơi 96.5",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 100.0, 96.5, 98.0),    # low 96.5: all 3 layers fill
        ]),
        "sl": 5.0, "tp": 0.0, "dca": {"steps": [1.0, 1.0, 1.0], "mults": [1.0, 1.0, 1.0]}, "trail": None,
    },

    # 4. Gap mở cửa vượt qua stop; vượt qua limit
    "C4a_gap_open_stop": {
        "desc": "Gap mở cửa rơi xuyên SL 98.0 (open 95.0) -> khớp ở giá open",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.5, 100.0),   # entry @100.0, SL=98.0
            (95.0, 95.5, 94.0, 94.5),      # Gap down open at 95.0!
        ]),
        "sl": 2.0, "tp": 0.0, "dca": None, "trail": None,
    },
    "C4b_gap_open_limit": {
        "desc": "Gap mở cửa tăng qua TP 105.0 (open 108.0) -> khớp đúng giá limit 105.0",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.5, 100.0),   # entry @100.0, TP=105.0 (+5%)
            (108.0, 109.0, 107.0, 107.5),  # Gap up open at 108.0
        ]),
        "sl": 0.0, "tp": 5.0, "dca": None, "trail": None,
    },

    # 5. Stop dời sau fill trong cùng nến (SL cũ còn hiệu lực)
    "C5_stale_sl_intrabar": {
        "desc": "SL cũ 98.0 còn hiệu lực trong nến: low 97.8 kích hoạt SL cũ dù SL mới là 97.51",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0, SL=98.0
            (100.0, 100.0, 97.8, 98.5),    # DCA 99 fills, low 97.8 triggers stale SL 98.0
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [1.0], "mults": [1.0]}, "trail": None,
    },

    # 6. Trailing kích hoạt và chạm trong cùng nến
    "C6_trailing_trigger_same_bar": {
        "desc": "Đỉnh nến nâng peak kích hoạt trailing, đáy nến chạm mức trailing trigger",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 104.0, 99.5, 102.0),  # High 104 activates trail (act 2%), low 99.5 crosses trail trigger
            (102.0, 102.0, 102.0, 102.0),  # Flat bar to flush
        ]),
        "sl": 0.0, "tp": 0.0, "dca": None, "trail": {"act": 2.0, "offset": 1.5},
    },

    # 7. Reduce-only đóng hết toàn bộ vị thế DCA
    "C7_reduce_only_flat": {
        "desc": "Lệnh stop reduce-only đóng hết 2.0 qty sau khi DCA khớp",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 100.0, 96.0, 96.0),    # DCA 99.0 fills (+1.0 qty), SL 98.0 closes all 2.0 qty
            (96.0, 96.5, 95.5, 96.0),      # flat bar: position must be 0
        ]),
        "sl": 2.0, "tp": 0.0, "dca": {"steps": [1.0], "mults": [1.0]}, "trail": None,
    },

    # 8. limit_through_pct = 0 (chạm đúng mức là khớp)
    "C8_limit_through_zero": {
        "desc": "limit_through_pct=0: chạm đúng 99.0 là khớp maker",
        "side": "LONG",
        "lev": 1,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0
            (100.0, 100.2, 99.0, 99.5),    # low touches exactly 99.00 -> DCA fills
        ]),
        "sl": 5.0, "tp": 0.0, "dca": {"steps": [1.0], "mults": [1.0]}, "trail": None,
    },

    # 9. Thanh lý perp trong nến (leverage 20x, MMR 0.5%)
    "C9_liquidation": {
        "desc": "Đòn bẩy 20x, MMR 0.5%: liq price = 95.5. Nến rơi 94.0 -> thanh lý",
        "side": "LONG",
        "lev": 20,
        "mmr": 0.005,
        "bars": make_bars([
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.5, 99.8, 100.0),   # entry @100.0, liq = 100*(1 - 1/20 + 0.005) = 95.5
            (100.0, 100.0, 94.0, 94.0),    # low 94.0 crosses 95.5 -> liquidation
        ]),
        "sl": 0.0, "tp": 0.0, "dca": None, "trail": None,
    },
}
