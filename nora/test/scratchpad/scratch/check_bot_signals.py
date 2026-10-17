import glob, json, os

for bid in ['bot_1791948995_3cdbec_paper', 'bot_1791892571_d02d93_testnet', 'bot_1791948928_15bf25_paper', 'bot_1791948995_e16469_paper', 'bot_1791893016_b3d74c_testnet']:
    for p in glob.glob(f'/home/vmc03/norabt/nora/data/live/*/{bid}/bot.json'):
        bdir = os.path.dirname(p)
        print(f'=== {bid} ===')
        # Check bot.json base_frame, signal_tf
        with open(p) as f:
            bjson = json.load(f)
        print('base_frame:', bjson.get('base_frame'), 'strategy:', bjson.get('strategy'), 'symbols:', len(bjson.get('symbols', [])))
        # Check last lines of signals.jsonl
        sigf = os.path.join(bdir, 'signals.jsonl')
        if os.path.exists(sigf):
            with open(sigf) as f:
                lines = f.readlines()
                print('signals.jsonl lines:', len(lines))
                if lines:
                    print('last signal:', lines[-1].strip())
        # Check nautilus.log last 5 lines
        logf = os.path.join(bdir, 'nautilus.log')
        if os.path.exists(logf):
            with open(logf) as f:
                lines = f.readlines()
                errs = [l.strip() for l in lines if 'ERROR' in l or 'WARNING' in l or 'Order' in l][-5:]
                print('recent log errors/orders:', errs)
