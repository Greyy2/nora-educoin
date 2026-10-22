import json
from collections import Counter

with open("data/proxima_trade_attribution.json") as f:
    trades = json.load(f)

print(f"Total closed trades: {len(trades)}")

reasons = Counter(t["exit_reason"] for t in trades)
print("\n--- EXIT REASONS BREAKDOWN ---")
for r, count in reasons.most_common():
    sub = [t for t in trades if t["exit_reason"] == r]
    net_pnl = sum(t["net_pnl"] for t in sub)
    fees = sum(t["total_fees"] for t in sub)
    wins = sum(1 for t in sub if t["net_pnl"] > 0)
    wr = wins / len(sub) * 100 if sub else 0
    print(f"  {r:20s}: {count:3d} trades ({count/len(trades)*100:5.1f}%) | Net PnL: ${net_pnl:+7.2f} | Fees: ${fees:6.2f} | WinRate: {wr:5.1f}%")

print("\n--- BREAKDOWN BY SYMBOL ---")
symbols = sorted(set(t["symbol"] for t in trades))
for s in symbols:
    sub = [t for t in trades if t["symbol"] == s]
    net_pnl = sum(t["net_pnl"] for t in sub)
    gross_pnl = sum(t["gross_pnl"] for t in sub)
    fees = sum(t["total_fees"] for t in sub)
    wins = sum(1 for t in sub if t["net_pnl"] > 0)
    wr = wins / len(sub) * 100 if sub else 0
    print(f"  {s:15s}: {len(sub):2d} trades | WinRate: {wr:5.1f}% | Gross: ${gross_pnl:+6.2f} | Fees: ${fees:5.2f} | Net: ${net_pnl:+6.2f}")

print("\n--- NOTIONAL & POSITION SIZE ANALYSIS ---")
from collections import defaultdict
stats = defaultdict(list)
for t in trades:
    # Contract value factor: t["entry_price"] * t["qty_contracts"] * ctVal
    # Here let's get notional quote
    stats[t["symbol"]].append((t["qty_contracts"], t["entry_price"], t["net_pnl"], t["total_fees"]))

for s, lst in sorted(stats.items()):
    qtys = [x[0] for x in lst]
    pxs = [x[1] for x in lst]
    fees = [x[3] for x in lst]
    print(f"  {s:15s}: avg_qty={sum(qtys)/len(qtys):9.2f} | avg_entry_px={sum(pxs)/len(pxs):10.4f} | avg_fee_per_trade=${sum(fees)/len(fees):.4f}")

