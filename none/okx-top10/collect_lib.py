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
