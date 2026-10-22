#!/usr/bin/env python3
"""Script launch 1 Paper Bot Proxima — ETH-USDT-SWAP, sleeve 2,000 USDT.

Chạy:
    PYTHONPATH=. /home/vmc03/.venvs/nora312/bin/python launch_proxima_paper.py

Ghi chú:
- Kiểm tra Master Fund state trước khi gọi.
- Không tự thay đổi tham số r_ratio/vl_mult/tp_mult/f_mult mà không backtest lại.
"""
import json
import time
import urllib.request
import urllib.error

API_BASE = "http://localhost:18010/api/studio"

# ─── Cấu hình Bot ────────────────────────────────────────────────────────────
BOT_CONFIG = {
    "mode": "paper",
    "strategy_type": "proxima",
    "symbols": ["ETH-USDT-SWAP"],
    "capital": 2000.0,               # Sleeve 2,000 USDT (trong 8,000 unallocated)
    "base_frame": "1m",              # Khung dữ liệu thực thi
    "anchor_tf": "1h",               # Anchor timeframe cho tín hiệu Proxima
    "r_ratio": 0.15,                 # Tỷ lệ dự trữ vốn R (15%)
    "vl_mult": 1.0,                  # Volume multiplier
    "tp_mult": 0.8,                  # Take Profit multiplier
    "f_mult": 1.0,                   # F-delta multiplier
    "enter_on_start": False,         # Không vào lệnh ngay khi khởi động
}

# ─── Risk Limits cố định (không điều chỉnh) ──────────────────────────────────
RISK_LIMITS = {
    "sleeve_cap": 2000.0,
    "max_loss_per_trade_pct": 0.015,  # 1.5% → $30/trade
    "sleeve_drawdown_lock_pct": 0.15, # 15% → $300 → LOCKED
    "master_circuit_breaker_pct": 0.20,
    "required_headroom": 2000.0,
}


def api_get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_post(path: str, body: dict) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def check_master_fund() -> bool:
    print("=" * 60)
    print("KIEM TRA MASTER FUND")
    print("=" * 60)

    portfolio = api_get("/portfolio/master")
    summary = portfolio.get("portfolio_summary", {})

    initial = summary.get("initial_capital", 0)
    allocated = summary.get("total_allocated_capital", 0)
    headroom = summary.get("deployable_headroom_for_new_bot", 0)
    equity = summary.get("master_equity", 0)
    circuit = summary.get("circuit_breaker_status", "UNKNOWN")
    dd_pct = summary.get("drawdown_from_peak_pct", 0)

    print(f"  Initial Capital:   ${initial:,.2f} USDT")
    print(f"  Total Allocated:   ${allocated:,.2f} USDT")
    print(f"  Master Equity:     ${equity:,.2f} USDT")
    print(f"  Deployable:        ${headroom:,.2f} USDT")
    print(f"  Circuit Breaker:   {circuit}")
    print(f"  Peak Drawdown:     {dd_pct:.2f}%")
    print()

    ok = True
    sleeve_needed = RISK_LIMITS["required_headroom"]

    if circuit != "NORMAL":
        print(f"  FAIL Circuit Breaker TRIGGERED: {circuit}")
        ok = False

    if headroom < sleeve_needed:
        print(f"  FAIL Khong du headroom: can ${sleeve_needed:.0f}, co ${headroom:.2f}")
        ok = False

    if dd_pct > 15.0:
        print(f"  WARN Drawdown {dd_pct:.1f}% > 15%")
        ok = False

    if ok:
        print(f"  OK Master Fund healthy -- co the cap sleeve ${sleeve_needed:.0f}")

    return ok


def launch_proxima_bot() -> dict:
    print()
    print("=" * 60)
    print("LAUNCH PAPER BOT: Proxima / ETH / 2000 USDT")
    print("=" * 60)
    print(f"  Config: {json.dumps(BOT_CONFIG)}")
    result = api_post("/live/bot", BOT_CONFIG)
    return result


def monitor_bot(bot_id: str, max_wait: int = 45) -> None:
    print(f"\nCho bot {bot_id} khoi dong (toi da {max_wait}s)...")
    from pathlib import Path
    bot_json = Path(f"/home/vmc03/norabt/nora/data/live/paper/{bot_id}/bot.json")
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if bot_json.exists():
            try:
                state = json.loads(bot_json.read_text())
                status = state.get("status", "?")
                print(f"  [{time.time()-t0:.0f}s] status = {status}")
                if status in ("running", "starting"):
                    print(f"  OK Bot {bot_id} dang chay!")
                    return
                elif status in ("failed", "error"):
                    print(f"  FAIL: {state.get('error', 'unknown')}")
                    return
            except Exception as e:
                print(f"  [{time.time()-t0:.0f}s] Doc bot.json loi: {e}")
        time.sleep(3)
    print(f"  WARN Timeout sau {max_wait}s")


def main():
    print()
    print("NORA PAPER: LAUNCH PROXIMA BOT -- 10 MARKET PHASE 1")
    print()

    try:
        ok = check_master_fund()
    except Exception as e:
        print(f"FAIL Khong ket noi duoc API: {e}")
        print("   Chay: systemctl --user start nora-api")
        return

    if not ok:
        print("\nDUNG: khong du dieu kien de launch bot moi.")
        return

    print()
    confirm = input("Launch bot? (yes/no): ").strip().lower()
    if confirm not in ("yes", "y"):
        print("Huy launch.")
        return

    try:
        result = launch_proxima_bot()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"FAIL API error {e.code}: {body}")
        return
    except Exception as e:
        print(f"FAIL Launch loi: {e}")
        return

    bot_id = result.get("bot_id", "?")
    job_id = result.get("job_id", "?")
    print(f"\n  OK Bot launched!")
    print(f"     bot_id = {bot_id}")
    print(f"     job_id = {job_id}")

    monitor_bot(bot_id, max_wait=45)

    print()
    print("BUOC TIEP THEO:")
    print(f"  tail -f data/live/paper/{bot_id}/equity.jsonl")
    print(f"  tail -f data/live/paper/{bot_id}/events.jsonl")
    print()
    print("Phase 2 (sau >= 72h):")
    print("  DeFi cluster  : UNI, NEAR -- sleeve 1,500 USDT")
    print("  Alt L1 cluster: SOL, FIL, XRP -- sleeve 1,500 USDT")
    print("  Speculative   : STRK, HYPE, DOGE -- sleeve 1,000 USDT")


if __name__ == "__main__":
    main()
