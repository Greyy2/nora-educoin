import json,time,sys,os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'.')
from collect_lib import get
START=int(sys.argv[1]); os.makedirs("candles15",exist_ok=True)
def one(sym):
    inst=f"{sym}-USDT-SWAP"; out=[]; after=""
    for _ in range(40):
        rows=get(f"/api/v5/market/history-candles?instId={inst}&bar=15m&limit=100"+(f"&after={after}" if after else "")).get("data") or []
        if not rows: break
        out+=rows; after=rows[-1][0]; time.sleep(0.3)
        if int(after)<START: break
    out=sorted({int(r[0]):r for r in out if int(r[0])>=START}.values(),key=lambda r:int(r[0]))
    json.dump([[int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4])] for r in out],open(f"candles15/{sym}.json","w"))
    print(sym,len(out),flush=True)
with ThreadPoolExecutor(4) as ex: list(ex.map(one,json.load(open("syms15.json"))))
