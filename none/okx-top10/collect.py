"""Top OKX copy-trade leads (official public API v5): ranking, closed sub-positions, open sub-positions, daily pnl, stats."""
import json, subprocess, time, sys
BASE = "https://www.okx.com"
def get(path):
    for _ in range(4):
        try:
            d = json.loads(subprocess.run(["curl","-s","--max-time","15","-A","Mozilla/5.0",BASE+path],capture_output=True,text=True,timeout=20).stdout)
            if d.get("code") == "0": return d
            if d.get("code") in ("50011","50061"): time.sleep(2); continue
            return d
        except Exception: time.sleep(1)
    return {"code":"ERR","data":[]}
board=[]; seen=set()
for page in range(1,30):
    d=get(f"/api/v5/copytrading/public-lead-traders?instType=SWAP&limit=20&page={page}")
    blk=(d.get("data") or [{}])[0]; rows=blk.get("ranks",[]); fresh=0
    for r in rows:
        if r["uniqueCode"] in seen: continue
        seen.add(r["uniqueCode"]); fresh+=1; r["okxRank"]=len(board)+1; board.append(r)
    if not rows or not fresh: break
    time.sleep(0.25)
print("board",len(board),blk.get("dataVer"),file=sys.stderr)
json.dump(board,open("board.json","w"),ensure_ascii=False)
