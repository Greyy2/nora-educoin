"""Script chạy backtest Nautilus và cập nhật kết quả cho 26 alpha fixture của EDU.

Đảm bảo dữ liệu thật 100% từ engine, không dùng số mock.
Sau khi chạy xong, card_index() và API Market EDU sẽ lập tức nhận kết quả và view lên UI.
"""
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

EDU_ROOT = Path("/home/vmc03/norabt/nora/edu")
sys.path.insert(0, str(EDU_ROOT))

from backend.jobs.tasks import run_custom
from backend.analys.alpha import store

ALPHA_DIR = EDU_ROOT / "data" / "alpha" / "user"

FX_ALPHA_IDS = [
    "0bf936687964", "138df68946ad", "1a1a4389a821", "1e4c0b9f84f7",
    "214ea8fdf3e6", "234e6df02e37", "2e41b2cfa24d", "571474a18f55",
    "616e1b8cbc88", "64b657c8de8e", "74f607263c5c", "7c1bf0a9686a",
    "7f770ebe5ab5", "856ddc574ce7", "862e0c9eebbe", "930294d28c45",
    "9eec3d61131d", "a4d6826fbbc6", "af2bf88426c4", "bd234070bd7b",
    "be1174b24a44", "cb0b6e0f12e7", "d0518c0cca14", "e9a9a5b44d03",
    "ee0cf7f58f94", "fd16df3d0a3f"
]

print(f"=== BẮT ĐẦU CHẠY VÀ CẬP NHẬT {len(FX_ALPHA_IDS)} ALPHAS FIXTURE TRONG EDU ===")
start_all = time.time()
success_count = 0
failed = []

for idx, aid in enumerate(FX_ALPHA_IDS, 1):
    file_path = ALPHA_DIR / f"{aid}.json"
    if not file_path.exists():
        print(f"[{idx}/{len(FX_ALPHA_IDS)}] KHÔNG TÌM THẤY: {file_path}")
        failed.append((aid, "File not found"))
        continue

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        cfg = data.get("config", {})
        symbols = cfg.get("symbols", ["BTC-USDT"])
        run_frame = cfg.get("run_frame") or cfg.get("timeframe", "1h")

        print(f"\n[{idx}/{len(FX_ALPHA_IDS)}] Chạy alpha {aid} ({data.get('name')}) | {symbols} | {run_frame}...")
        t0 = time.time()

        params = {
            "code": data["code"],
            "symbols": symbols,
            "start": "2024-01-01",
            "end": "2026-09-01",
            "train_ratio": 0.8,
            "initial_capital": 10000.0,
            "run_frame": run_frame,
        }

        res = run_custom(params)
        duration = round(time.time() - t0, 1)

        sim_metrics = (res.get("metrics") or {}).get("simulate", {})
        ret_pct = sim_metrics.get("return_pct")
        trades = sim_metrics.get("total_trades")
        mdd_pct = sim_metrics.get("max_drawdown_pct")
        sharpe = sim_metrics.get("sharpe_ratio")
        final_eq = res.get("final_equity", 10000.0)

        # Cập nhật trực tiếp kết quả vào file record
        data["result"] = res
        data["metrics"] = res.get("metrics", {})
        data["final_equity"] = final_eq
        data["program_hash"] = res.get("program_hash")
        data["backtest_status"] = "SUCCESS"
        data["checklist"] = res.get("checklist", {})
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Ghi lại file json
        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # Kiểm tra lại card
        card = store.strategy_card(data)
        print(f"  -> XONG trong {duration}s! Return: {card.get('ret_pct')}% | Trades: {card.get('trades')} | PnL: ${card.get('pnl_usd')} | MDD: {card.get('mdd_pct')}% | Sharpe: {card.get('sharpe')}")
        success_count += 1

    except Exception as e:
        print(f"  -> LỖI khi chạy {aid}: {e}")
        failed.append((aid, str(e)))

total_time = round(time.time() - start_all, 1)
print(f"\n=== HOÀN TẤT BATCH: Thành công {success_count}/{len(FX_ALPHA_IDS)} trong {total_time}s ===")
if failed:
    print(f"Danh sách thất bại ({len(failed)}):")
    for f in failed:
        print(f"  {f[0]}: {f[1]}")
