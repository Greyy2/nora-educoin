import json,time,sys,os
sys.path.insert(0,'.')
from collect_lib import get
START=1783209600000  # 2026-07-05 00:00 UTC (cửa sổ lịch sử lệnh 90 ngày)
os.makedirs("candles",exist_ok=True)
for inst in json.load(open("syms.json")):
    out=[]; after=""
    for _ in range(40):
        rows=get(f"/api/v5/market/history-candles?instId={inst}&bar=1H&limit=100"+(f"&after={after}" if after else "")).get("data") or []
        if not rows: break
        out+=rows; after=rows[-1][0]; time.sleep(0.11)
        if int(after)<START: break
    out=sorted({int(r[0]):r for r in out if int(r[0])>=START}.values(),key=lambda r:int(r[0]))
    json.dump([[int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4])] for r in out],open(f"candles/{inst.replace('-USDT-SWAP','')}.json","w"))
    print(inst,len(out),file=sys.stderr)
