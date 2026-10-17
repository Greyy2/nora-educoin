import urllib.request, json

req = urllib.request.urlopen('http://127.0.0.1:18010/api/studio/live/candidates', timeout=5)
data = json.loads(req.read().decode())
candidates = data.get('candidates', [])
print(f'Total candidates: {len(candidates)}')
for c in candidates:
    print(f"ID: {c.get('id')} | Name: {c.get('name')} | Side: {c.get('side')} | TF: {c.get('timeframe')} | Ret: {c.get('ret_pct')}% | Sharpe: {c.get('sharpe')} | MDD: {c.get('mdd_pct')}% | Source: {c.get('source')}")
