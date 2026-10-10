"""Test NautilusRunner độc lập."""
import sys
import os
sys.path.insert(0, os.path.abspath("."))

import pandas as pd
from backend.nautilus import NautilusRunner, check_for_updates, get_version_info

def main():
    print("=== KIỂM TRA PHIÊN BẢN NAUTILUS TRADER ===")
    info = get_version_info()
    print("Version Info:", info)

    print("\n=== TẠO DỮ LIỆU NẾN THỬ NGHIỆM ===")
    # Nến 1: Open 100 -> High 101 -> Low 98 -> Close 100 -> Khớp ENTRY tại 100
    # Nến 2: Open 100 -> High 105 -> Low 99 -> Close 104 -> Khớp TP tại 103 (TP 3%)
    df = pd.DataFrame([
        {"open_time": 1700000000000, "open": 100.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1.0},
        {"open_time": 1700000060000, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1.0},
    ])

    print("\n=== CHẠY BACKTEST ENGINE ===")
    runner = NautilusRunner(capital=10000.0)
    res = runner.run(
        df,
        params={
            "symbol": "BTC-USDT-SWAP",
            "side": "LONG",
            "order_size_pct": 10.0,
            "leverage": 1.0,
            "take_profit_rate": 3.0,
            "stop_loss_rate": 2.0,
        }
    )

    print("\n=== KẾT QUẢ BACKTEST ===")
    print("Success:", res["success"])
    print("Metrics:", res["metrics"])
    print(f"Total Fills: {len(res['fills'])}")
    for f in res["fills"]:
        print("  Fill:", f)

    assert res["success"] is True, "Backtest thất bại!"
    assert len(res["fills"]) >= 2, "Chưa khớp đủ Entry và TP!"
    print("\n>>> KIỂM TRA NAUTILUS ENGINE THÀNH CÔNG RỰC RỠ 100% <<<")

if __name__ == "__main__":
    main()
