"""Collect top OKX copy-trading lead traders and their closed positions (official public API v5)."""
import json, subprocess, time, sys
BASE = "https://www.okx.com"

def get(path):
    for attempt in range(3):
        try:
            out = subprocess.run(["curl", "-s", "--max-time", "12", "-A", "Mozilla/5.0", BASE + path],
                                 capture_output=True, text=True, timeout=15).stdout
            d = json.loads(out)
            if d.get("code") == "0":
                return d
            if d.get("code") in ("50011", "50061"):  # rate limit
                time.sleep(2); continue
            return d
        except Exception:
            time.sleep(1)
    return {"code": "ERR", "data": []}

# 1) candidate pool: first 8 pages of the overview ranking (20 per page)
cands = []
for page in range(1, 9):
    d = get(f"/api/v5/copytrading/public-lead-traders?instType=SWAP&sortType=overview&limit=20&page={page}")
    ranks = (d.get("data") or [{}])[0].get("ranks", [])
    cands += ranks
    time.sleep(0.3)
print("candidates", len(cands), file=sys.stderr)
json.dump(cands, open("okx_candidates.json", "w"), ensure_ascii=False)

# 2) select: lead >= 60 days, then composite rank on pnl, aum, current copiers
pool = [c for c in cands if int(c.get("leadDays") or 0) >= 60]
def rank(key):
    order = sorted(pool, key=lambda c: -float(c.get(key) or 0))
    return {c["uniqueCode"]: i for i, c in enumerate(order)}
rp, ra, rc = rank("pnl"), rank("aum"), rank("copyTraderNum")
pool.sort(key=lambda c: rp[c["uniqueCode"]] + ra[c["uniqueCode"]] + rc[c["uniqueCode"]])
top = pool[:25]

# 3) closed positions (paginate with 'after' = last subPosId), up to 10 pages
bots = []
for c in top:
    uc = c["uniqueCode"]; trades = []; after = None
    for _ in range(10):
        q = f"/api/v5/copytrading/public-subpositions-history?instType=SWAP&uniqueCode={uc}&limit=100"
        if after: q += f"&after={after}"
        rows = get(q).get("data") or []
        if not rows: break
        trades += rows; after = rows[-1]["subPosId"]
        time.sleep(0.25)
        if len(rows) < 20: break
    stats = (get(f"/api/v5/copytrading/public-stats?instType=SWAP&uniqueCode={uc}&lastDays=4").get("data") or [{}])[0]
    time.sleep(0.25)
    bots.append({"exchange": "OKX", "id": uc, "name": c.get("nickName"), "meta": c, "stats": stats, "trades": trades})
    print(c.get("nickName"), len(trades), file=sys.stderr)
json.dump(bots, open("okx_bots.json", "w"), ensure_ascii=False)
print("done", len(bots), sum(len(b["trades"]) for b in bots))
