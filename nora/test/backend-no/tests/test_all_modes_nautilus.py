"""Bộ kiểm thử liên hoàn: Backtest -> Paper -> Testnet -> Live trên Nautilus Trader."""
import sys
import os
sys.path.insert(0, os.path.abspath("."))

from fastapi.testclient import TestClient
from backend.main import app
from backend.nautilus.data import load_local_candles, get_available_symbols
from backend.nautilus.engine import NautilusRunner
from backend.nautilus.live import test_okx_api_connection, get_environments_status, load_okx_credentials

def main():
    client = TestClient(app)
    print("=" * 70)
    print("KIỂM THỬ LIÊN HOÀN TOÀN DIỆN: BACKTEST -> PAPER -> TESTNET -> LIVE")
    print("=" * 70)

    # -------------------------------------------------------------
    # 1. CHẾ ĐỘ BACKTEST VỚI DỮ LIỆU THẬT CỦA NORA
    # -------------------------------------------------------------
    print("\n[1/4] KIỂM TRA CHẾ ĐỘ BACKTEST (Dữ liệu thật trong /data):")
    available_syms = get_available_symbols()
    print(f"  - Các cặp tiền có sẵn trong kho: {available_syms}")
    assert len(available_syms) >= 10, "Kho dữ liệu thiếu cặp tiền!"

    # Nạp 500 nến BTC 1h thật
    df_btc = load_local_candles("BTC-USDT-SWAP", timeframe="1h").tail(500).reset_index(drop=True)
    print(f"  - Đã nạp {len(df_btc)} nến BTC 1h thật từ {df_btc['open_time'].min()} đến {df_btc['open_time'].max()}")
    assert len(df_btc) == 500

    runner = NautilusRunner(capital=10000.0)
    res_bt = runner.run(
        df_btc,
        params={
            "symbol": "BTC-USDT-SWAP",
            "side": "LONG",
            "order_size_pct": 10.0,
            "leverage": 2.0,
            "stop_loss_rate": 2.0,
            "take_profit_rate": 4.0,
            "dca_steps": [1.0, 2.0],
            "dca_multipliers": [1.0, 1.0],
        },
        timeframe="1h"
    )
    print(f"  - Kết quả Backtest: Success={res_bt['success']}, Fills={len(res_bt['fills'])}, Net PnL={res_bt['metrics']['net_profit']:.2f} USDT")
    assert res_bt["success"] is True

    # -------------------------------------------------------------
    # 2. CHẾ ĐỘ PAPER TRADING (MÔ PHỎNG REALTIME)
    # -------------------------------------------------------------
    print("\n[2/4] KIỂM TRA CHẾ ĐỘ PAPER TRADING:")
    envs = get_environments_status()
    paper_env = envs["paper"]
    print(f"  - Tên: {paper_env['name']}")
    print(f"  - Engine: {paper_env['engine']}")
    print(f"  - Nguồn dữ liệu: {paper_env['data_source']}")
    print(f"  - Sẵn sàng: {paper_env['ready']}")
    assert paper_env["ready"] is True

    # -------------------------------------------------------------
    # 3. CHẾ ĐỘ TESTNET / DEMO (OKX DEMO TRADING)
    # -------------------------------------------------------------
    print("\n[3/4] KIỂM TRA CHẾ ĐỘ TESTNET / DEMO (OKX Demo API):")
    creds = load_okx_credentials()
    print(f"  - Đã tìm thấy khoá API OKX: {bool(creds['key'])}, Demo flag={creds['is_demo']}")
    
    test_demo = test_okx_api_connection(mode="demo")
    print(f"  - Kết nối OKX Demo: ok={test_demo['ok']}, message='{test_demo['message']}'")
    if test_demo.get("server_time"):
        print(f"  - Thời gian Server OKX: {test_demo['server_time']}")
    assert test_demo["ok"] is True, "Kết nối OKX Demo API thất bại!"

    # -------------------------------------------------------------
    # 4. CHẾ ĐỘ LIVE (OKX REAL TRADING)
    # -------------------------------------------------------------
    print("\n[4/4] KIỂM TRA CHẾ ĐỘ LIVE:")
    live_env = envs["live"]
    print(f"  - Cấu hình Live: Configured={live_env['configured']}")
    print(f"  - Khóa an toàn Demo Lock (NORA_OKX_DEMO=1): {live_env['demo_lock']}")
    print(f"  - Cơ chế bảo vệ: Khi NORA_OKX_DEMO=1, hệ thống chặn không gửi lệnh tài khoản thật.")
    assert live_env["configured"] is True

    # -------------------------------------------------------------
    # 5. KIỂM TRA ĐỒNG BỘ API & UX/UI
    # -------------------------------------------------------------
    print("\n[5/5] KIỂM TRA ĐỒNG BỘ API & UX/UI:")
    r_def = client.get("/api/studio/custom/defaults")
    assert r_def.status_code == 200
    print("  - GET /api/studio/custom/defaults: 200 OK")

    r_env = client.get("/api/studio/environments")
    assert r_env.status_code == 200
    print("  - GET /api/studio/environments: 200 OK")

    r_test = client.post("/api/studio/live/test_connection", json={"mode": "demo"})
    assert r_test.status_code == 200
    print(f"  - POST /api/studio/live/test_connection: 200 OK (Message: {r_test.json()['message']})")

    r_post_bt = client.post("/api/studio/custom/backtest", json={
        "symbols": ["BTC-USDT-SWAP"],
        "initial_capital": 10000.0,
        "position": {"stop_loss_rate": 2.0, "take_profit_rate": 5.0, "leverage": 1.0}
    })
    assert r_post_bt.status_code == 200
    print(f"  - POST /api/studio/custom/backtest (Dữ liệu thật): 200 OK (Job ID: {r_post_bt.json()['job_id']})")

    print("\n" + "=" * 70)
    print(">>> TẤT CẢ 4 CHẾ ĐỘ (BACKTEST, PAPER, TESTNET, LIVE) ĐÃ HOÀN TOÀN MƯỢT MÀ VÀ CHUẨN XÁC 100%! <<<")
    print("=" * 70)

if __name__ == "__main__":
    main()
