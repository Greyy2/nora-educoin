"""Per-bot stats from OKX public closed/open sub-positions + 1H candles. Output: bots.json (page data)."""
import json, os, statistics as S, bisect
from collections import Counter, defaultdict
H=3600_000
sel=json.load(open("sel_raw.json"))
C={}
def candles(sym):
    if sym not in C:
        p=f"candles/{sym}.json"; C[sym]=json.load(open(p)) if os.path.exists(p) else []
    return C[sym]
def f(x):
    try: return float(x)
    except: return None
def med(a): return S.median(a) if a else None
def r(x,n=2): return None if x is None else round(x,n)
out=[]
for b in sel:
    m=b["meta"]; T=[]
    for t in b["trades"]:
        if not t.get("closeTime"): continue
        T.append(dict(sym=t["instId"].replace("-USDT-SWAP",""),side=t["posSide"],lev=f(t["lever"]),o=int(t["openTime"]),c=int(t["closeTime"]),
                      po=f(t["openAvgPx"]),pc=f(t["closeAvgPx"]),pnl=f(t["pnl"]),pr=f(t["pnlRatio"]),mg=f(t["margin"]),sz=f(t["subPos"]),id=t["subPosId"]))
    T.sort(key=lambda x:x["o"])
    # MAE (worst adverse move vs entry, % price) and 24h momentum at entry, from 1H candles
    for t in T:
        k=candles(t["sym"]); ts=[x[0] for x in k]; t["mae"]=None; t["mom"]=None
        if not k: continue
        i0=bisect.bisect_right(ts,t["o"])-1; i1=bisect.bisect_right(ts,t["c"])-1
        if i0>=0 and i1>=i0:
            seg=k[i0:i1+1]
            if t["side"]=="long": t["mae"]=min(0,(min(x[3] for x in seg)/t["po"]-1)*100)
            else: t["mae"]=min(0,(1-max(x[2] for x in seg)/t["po"])*100)
        j=i0-1; j24=j-24
        if j24>=0:
            mv=k[j][4]/k[j24][4]-1
            t["mom"]=(mv>0)==(t["side"]=="long") if abs(mv)>0.002 else None
    # DCA: a sub-position opened while another same sym+side is still open = add; basket = chain of overlaps
    adds=0; down=0; steps=[]; baskets=[]; byk=defaultdict(list)
    for t in T: byk[(t["sym"],t["side"])].append(t)
    for key,arr in byk.items():
        cur=[]; end=-1
        for t in arr:
            if cur and t["o"]<end:
                adds+=1; t["add"]=True; prev=cur[-1]
                adv=(prev["po"]-t["po"])/prev["po"]*100 if t["side"]=="long" else (t["po"]-prev["po"])/prev["po"]*100
                if adv>0: down+=1; steps.append(adv)
                cur.append(t); end=max(end,t["c"])
            else:
                if cur: baskets.append(cur)
                cur=[t]; end=t["c"]; t["add"]=False
        if cur: baskets.append(cur)
    bid={id(t):i for i,bk in enumerate(sorted(baskets,key=lambda bk:bk[0]["o"])) for t in bk}
    for t in T: t["bk"]=bid[id(t)]
    n=len(T); W=[t for t in T if t["pnl"]>0]; L=[t for t in T if t["pnl"]<=0]
    gw=sum(t["pnl"] for t in W); gl=-sum(t["pnl"] for t in L)
    hold=lambda a:[(t["c"]-t["o"])/H for t in a]
    wins_mae=[t["mae"] for t in W if t["mae"] is not None]
    moms=[t["mom"] for t in T if t["mom"] is not None]
    top5=sum(sorted([t["pnl"] for t in W],reverse=True)[:5])
    symc=Counter(t["sym"] for t in T)
    op=b["open"]; upl=sum(f(x["upl"]) or 0 for x in op); omg=sum(f(x["margin"]) or 0 for x in op)
    st=b["stats90"]
    out.append(dict(
        rank=m["okxRank"], name=m["nickName"], code=m["uniqueCode"], url=f"https://www.okx.com/copy-trading/account/{m['uniqueCode']}?tab=swap",
        leadDays=int(m["leadDays"]), copiers=int(m["copyTraderNum"]), maxCopiers=int(m["maxCopyTraderNum"]), accCopiers=int(m["accCopyTraderNum"]),
        aum=f(m["aum"]), pnl90=f(m["pnl"]), roi90=f(m["pnlRatio"])*100, winOkx=f(m["winRatio"])*100,
        profitDays=int(st.get("profitDays") or 0), lossDays=int(st.get("lossDays") or 0), invest=f(st.get("investAmt")), copierPnl=f(st.get("curCopyTraderPnl")),
        pref=[[p["ccy"],round(f(p["ratio"])*100,1)] for p in b["pref"]],
        curve=[[int(p["beginTs"]),f(p["pnl"]),f(p["pnlRatio"])*100] for p in sorted(b["pnl90"],key=lambda p:int(p["beginTs"]))],
        n=n, first=T[0]["o"], last=max(t["c"] for t in T), perDay=n/max(1,(max(t["c"] for t in T)-T[0]["o"])/86400000),
        win=len(W)/n*100, realized=gw-gl, pf=gw/gl if gl else None, payoff=(gw/len(W))/(gl/len(L)) if W and L and gl else None,
        longPct=sum(t["side"]=="long" for t in T)/n*100, levMed=med([t["lev"] for t in T]), levMax=max(t["lev"] for t in T),
        holdMed=med(hold(T)), holdWin=med(hold(W)), holdLoss=med(hold(L)),
        maxLoss=min(t["pnl"] for t in T), maxWin=max(t["pnl"] for t in T), top5Share=top5/gw*100 if gw else None,
        addPct=adds/n*100, addDownPct=down/n*100, stepMed=med(steps), maxLayers=max(len(bk) for bk in baskets), baskets=len(baskets),
        winMaeMed=med(wins_mae), winMaeP90=sorted(wins_mae)[int(len(wins_mae)*0.1)] if wins_mae else None,
        momPct=sum(moms)/len(moms)*100 if moms else None,
        syms=symc.most_common(), nOpen=len(op), openUpl=upl, openMargin=omg,
        open=[dict(sym=x["instId"].replace("-USDT-SWAP","") or None, side=x["posSide"], lev=f(x["lever"]), o=int(x["openTime"]) if x.get("openTime") else None,
                   po=f(x["openAvgPx"]), mark=f(x["markPx"]), upl=f(x["upl"]), uplr=(f(x["uplRatio"]) or 0)*100, mg=f(x["margin"])) for x in op],
        trades=[dict(sym=t["sym"],side=t["side"],lev=t["lev"],o=t["o"],c=t["c"],po=t["po"],pc=t["pc"],pnl=r(t["pnl"]),pr=r(t["pr"]*100,1),mg=r(t["mg"]),
                     mae=r(t["mae"]),add=t["add"],bk=t["bk"]) for t in T],
    ))
json.dump(out,open("bots.json","w"),ensure_ascii=False)
for o in out:
    print(f'#{o["rank"]} {o["name"]}: n={o["n"]} {o["perDay"]:.1f}/d win={o["win"]:.0f}% (okx {o["winOkx"]:.0f}) pnl90={o["pnl90"]:.0f} realized={o["realized"]:.0f} roi={o["roi90"]:.0f}% aum={o["aum"]:.0f} cop={o["copiers"]} | long={o["longPct"]:.0f}% lev={o["levMed"]}/{o["levMax"]} hold={o["holdMed"]:.1f}h W{o["holdWin"] or 0:.1f} L{o["holdLoss"] or 0:.1f} | pf={o["pf"] and round(o["pf"],2)} payoff={o["payoff"] and round(o["payoff"],2)} maxL={o["maxLoss"]:.0f} maxW={o["maxWin"]:.0f} top5={o["top5Share"] and round(o["top5Share"])}% | add={o["addPct"]:.0f}% down={o["addDownPct"]:.0f}% step={o["stepMed"] and round(o["stepMed"],2)} layers={o["maxLayers"]} | winMAE={o["winMaeMed"] and round(o["winMaeMed"],2)} p90={o["winMaeP90"] and round(o["winMaeP90"],2)} mom={o["momPct"] and round(o["momPct"])}% | open={o["nOpen"]} upl={o["openUpl"]:.0f} | syms={o["syms"][:5]} pref={o["pref"][:4]}')
