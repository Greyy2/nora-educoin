import json, time, sys
sys.path.insert(0,'.')
from collect_lib import get
board=json.load(open("board.json")); out=[]
for r in board[:25]:
    uc=r["uniqueCode"]; tr=[]; after=None
    for _ in range(20):
        q=f"/api/v5/copytrading/public-subpositions-history?instType=SWAP&uniqueCode={uc}&limit=100"+(f"&after={after}" if after else "")
        rows=get(q).get("data") or []
        if not rows: break
        tr+=rows; after=rows[-1]["subPosId"]; time.sleep(0.25)
    op=get(f"/api/v5/copytrading/public-current-subpositions?instType=SWAP&uniqueCode={uc}&limit=100").get("data") or []
    pnl={k:(get(f"/api/v5/copytrading/public-pnl?instType=SWAP&uniqueCode={uc}&lastDays={k}").get("data") or []) for k in ("3",)}
    st={k:((get(f"/api/v5/copytrading/public-stats?instType=SWAP&uniqueCode={uc}&lastDays={k}").get("data") or [{}])[0]) for k in ("2","3")}
    pref=get(f"/api/v5/copytrading/public-preference-currency?instType=SWAP&uniqueCode={uc}").get("data") or []
    out.append({"meta":r,"trades":tr,"open":op,"pnl90":pnl["3"],"stats30":st["2"],"stats90":st["3"],"pref":pref})
    print(r["okxRank"],r["nickName"],"closed",len(tr),"open",len(op),"pnlpts",len(pnl["3"]),file=sys.stderr); time.sleep(0.3)
json.dump(out,open("bots_raw.json","w"),ensure_ascii=False)
