import json, time, sys
from okx_collect_lib import get
bots = json.load(open("okx_bots.json")); cands = json.load(open("okx_candidates.json"))
keep = [b for b in bots if len(b["trades"]) >= 30]
have = {b["id"] for b in bots}
pool = [c for c in cands if int(c.get("leadDays") or 0) >= 60 and c["uniqueCode"] not in have]
def rank(key):
    order = sorted(pool, key=lambda c: -float(c.get(key) or 0)); return {c["uniqueCode"]: i for i, c in enumerate(order)}
rp, ra, rc = rank("pnl"), rank("aum"), rank("copyTraderNum")
pool.sort(key=lambda c: rp[c["uniqueCode"]] + ra[c["uniqueCode"]] + rc[c["uniqueCode"]])
for c in pool:
    if len(keep) >= 26: break
    uc = c["uniqueCode"]; trades = []; after = None
    for _ in range(10):
        q = f"/api/v5/copytrading/public-subpositions-history?instType=SWAP&uniqueCode={uc}&limit=100" + (f"&after={after}" if after else "")
        rows = get(q).get("data") or []
        if not rows: break
        trades += rows; after = rows[-1]["subPosId"]; time.sleep(0.25)
    if len(trades) < 30: print("skip", c.get("nickName"), len(trades), file=sys.stderr); continue
    stats = (get(f"/api/v5/copytrading/public-stats?instType=SWAP&uniqueCode={uc}&lastDays=4").get("data") or [{}])[0]
    keep.append({"exchange": "OKX", "id": uc, "name": c.get("nickName"), "meta": c, "stats": stats, "trades": trades})
    print("add", c.get("nickName"), len(trades), file=sys.stderr); time.sleep(0.25)
json.dump(keep, open("okx_bots.json", "w"), ensure_ascii=False)
print("kept", len(keep), sum(len(b["trades"]) for b in keep))
