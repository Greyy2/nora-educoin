import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

COIN_ROOT = Path("/home/vmc03/norabt/nora/coin")
sys.path.insert(0, str(COIN_ROOT))

from backend.analys.alpha.strategies import BY_ID
from backend.analys.param.params import materialize, schema_defaults
from backend.analys.signal.compute import evaluate_signals
from backend.core.backtest import NautilusRun
from backend.analys.alpha import RiskConfig
from tests.test_execution_realism_fixtures import SimpleStubDataSource

def run_kema_ledger():
    print("=" * 60)
    print("=== 1. AUDIT KEMA_LONG LEDGER VỚI POSITION KẾ THỪA TỪ BASE ===")
    print("=" * 60)
    cand = BY_ID["kema_long"]
    params = schema_defaults(cand)
    # kema_long có signal_tf mặc định là 4h, SL 3.0*ATR, exit_unit='atr'
    params.update({"sig.signal_tf": "4h", "atr_frame": "4h", "cooldown": 240})
    strat = materialize(cand, params, regime=False)
    
    pos = strat["position"]
    print("kema_long materialized position:")
    for k in ["sizing", "risk_per_trade_pct", "stop_loss_rate", "exit_unit", "order_size_pct", "leverage", "max_notional_pct"]:
        print(f"  - {k}: {pos.get(k)}")
    
    # Tạo chuỗi nến 4h kích hoạt tín hiệu buy tại bar 40
    symbol = "BTC-USDT-SWAP"
    frame = "4h"
    fr_ms = 4 * 60 * 60_000
    count = 60
    times = np.arange(count, dtype=np.int64) * fr_ms
    
    # 35 nến đầu giá 30,000 để tính EMA30 và ATR14 ổn định
    closes = np.full(count, 30000.0)
    # Từ bar 36..40 giá tăng vọt để phá kênh Keltner (EMA30 + 2.0*ATR)
    for i in range(35, count):
        closes[i] = 30000.0 + (i - 34) * 500.0
    
    opens = closes - 50.0
    highs = closes + 100.0
    lows = closes - 100.0
    vols = np.full(count, 100.0)
    
    df_4h = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })
    
    sig_res = evaluate_signals(symbol, [strat], {"4h": df_4h}, "4h")
    entry_eval = sig_res["entries"][0]
    matches = np.where(entry_eval["match"])[0]
    print(f"\nSignal matches count: {len(matches)}, first match at bar index: {matches[:5] if len(matches) else 'None'}")
    
    slot = entry_eval["slot"]
    sp = slot.params
    print(f"Slot params: sizing={sp.sizing}, risk_per_trade_pct={sp.risk_per_trade_pct}, order_size_pct={sp.order_size_pct}, lev={sp.leverage}")
    
    ds = SimpleStubDataSource(symbol, frame, times.tolist(), opens.tolist(), highs.tolist(), lows.tolist(), closes.tolist(), vols.tolist(), tick_sz="0.1", lot_sz="0.001")
    book = {
        "symbol": symbol,
        "data": {"t": times},
        "entries": [{
            "strategy": "kema_long",
            "slot": slot,
            "match": entry_eval["match"],
            "stop": entry_eval["stop"],
            "vol": None,
            "dca": None,
        }],
    }
    risk = RiskConfig(max_positions=1, max_per_symbol=1, max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
    res = NautilusRun(
        books=[book],
        initial_capital=10_000.0,
        risk=risk,
        trade_start_ts=0,
        end_ts=int(times[-1] + fr_ms),
        base_frame=frame,
        close_at_end=True,
        data=ds,
        execution_target="next_open",
    ).run()
    
    orders = [o for o in res.get("orders", []) if o.order_type.name == "BUY"]
    print(f"Executed BUY orders count: {len(orders)}")
    
    if orders:
        o = orders[0]
        # Match ở nến T, vào lệnh ở open nến T+1
        match_idx = matches[0]
        entry_bar = match_idx + 1
        entry_px = float(o.price)
        actual_qty = float(o.qty)
        notional = actual_qty * entry_px
        
        # Tính ATR tại bar match
        # Trong SignalSlot, SL = stop_loss_rate * ATR (hoặc pct nếu exit_unit=='pct')
        # Hãy xem SL distance thực tế được tính như thế nào
        print(f"\n--- CHI TIẾT LỆNH THỰC TẾ CỦA KEMA_LONG ---")
        print(f"Match Bar: {match_idx} (close={closes[match_idx]})")
        print(f"Entry Bar: {entry_bar} (open={opens[entry_bar]}, fill_price={entry_px})")
        print(f"Actual Qty: {actual_qty:.4f} BTC")
        print(f"Actual Notional: {notional:.2f} USDT")
        print(f"Initial Capital: 10,000 USDT")
        print(f"Notional / Capital: {notional / 10000.0:.2%}")
        
        # Nếu chạy margin_pct 100%, Notional sẽ là ~ 10,000 * 1.0 = 10,000 USDT
        # Nếu chạy sizing=risk, Qty được tính từ equity * risk_pct / sl_distance
        return {
            "strategy": "kema_long",
            "sizing": sp.sizing,
            "risk_pct": sp.risk_per_trade_pct,
            "order_size_pct": sp.order_size_pct,
            "actual_qty": actual_qty,
            "entry_px": entry_px,
            "notional": notional,
        }
    else:
        print("Không có BUY order nào được khớp!")
        return None

if __name__ == "__main__":
    run_kema_ledger()
