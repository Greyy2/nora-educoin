import urllib.request, json

# Stop idle bots that have 0 fills
idle_bots = [
    'bot_1791948995_3cdbec_paper',
    'bot_1791948995_4b4793_paper',
    'bot_1791948928_aa1ebd_paper',
    'bot_1791892571_d02d93_testnet',
]

for bid in idle_bots:
    try:
        url = f'http://127.0.0.1:18010/api/studio/live/bot/{bid}/stop?close_positions=true'
        req = urllib.request.Request(url, method='POST')
        with urllib.request.urlopen(req, timeout=5) as r:
            res = json.loads(r.read().decode())
            print(f'Stopped {bid}: {res}')
    except Exception as e:
        print(f'Error stopping {bid}: {e}')
