import glob, json, os

for p in sorted(glob.glob('/home/vmc03/norabt/nora/data/live/*/*/bot.json')):
    bdir = os.path.dirname(p)
    with open(p) as f:
        meta = json.load(f)
    bid = meta.get('bot_id')
    mode = meta.get('mode')
    strat = meta.get('strategy')
    status = meta.get('status')
    
    efile = os.path.join(bdir, 'events.jsonl')
    fills = 0
    pnl = 0.0
    if os.path.exists(efile):
        with open(efile) as ef:
            for line in ef:
                try:
                    d = json.loads(line)
                    if d.get('type') == 'fill':
                        fills += 1
                except:
                    pass
    print(f'{bid} | {mode} | {strat} | status={status} | fills={fills}')
