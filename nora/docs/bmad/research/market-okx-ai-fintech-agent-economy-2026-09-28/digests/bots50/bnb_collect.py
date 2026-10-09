"""Collect top Binance futures copy-trading lead portfolios and their position history
by rendering the public pages and recording the page's own API responses."""
import json, asyncio, glob, sys
from playwright.async_api import async_playwright
EXE = glob.glob('/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1234/*/chrome-headless-shell')[0]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36"

async def main():
    lists = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=EXE)
        ctx = await b.new_context(user_agent=UA, locale="en-US", viewport={'width': 1400, 'height': 1000})
        pg = await ctx.new_page()
        async def on_list(r):
            if 'recommend-lead-item' in r.url:
                try:
                    body = json.loads(r.request.post_data or '{}'); lists[body.get('dataType')] = (await r.json())['data']['items']
                except Exception: pass
        pg.on('response', on_list)
        await pg.goto('https://www.binance.com/en/copy-trading', wait_until='domcontentloaded', timeout=60000)
        await pg.wait_for_timeout(9000)
        items = {}
        for k, arr in lists.items():
            for it in arr:
                it.setdefault('_lists', []); items.setdefault(it['leadPortfolioId'], it)['_lists'].append(k)
        cands = list(items.values())
        print('lists', {k: len(v) for k, v in lists.items()}, 'unique', len(cands), file=sys.stderr)
        def rank(key):
            o = sorted(cands, key=lambda c: -float(c.get(key) or 0)); return {c['leadPortfolioId']: i for i, c in enumerate(o)}
        rp, rc, ra, rn = rank('pnl'), rank('copierPnl'), rank('aum'), rank('currentCopyCount')
        cands.sort(key=lambda c: rp[c['leadPortfolioId']] + rc[c['leadPortfolioId']] + ra[c['leadPortfolioId']] + rn[c['leadPortfolioId']])
        bots = []
        for c in cands:
            if len(bots) >= 25: break
            pid = c['leadPortfolioId']; got = {}
            async def on_resp(r):
                u = r.url
                try:
                    if 'position-history' in u:
                        got.setdefault('hist', []).append((r.request, await r.json()))
                    elif u.split('?')[0].endswith('lead-portfolio/detail'):
                        got['detail'] = (await r.json()).get('data')
                    elif 'performance/coin' in u:
                        got['coins'] = (await r.json()).get('data')
                except Exception: pass
            p2 = await ctx.new_page(); p2.on('response', on_resp)
            try:
                await p2.goto(f'https://www.binance.com/en/copy-trading/lead-details/{pid}?timeRange=90D', wait_until='domcontentloaded', timeout=60000)
                await p2.wait_for_timeout(7000)
                for label in ['Position History', 'Positions History']:
                    try:
                        await p2.get_by_text(label, exact=False).first.click(timeout=3000); await p2.wait_for_timeout(4000); break
                    except Exception: pass
                trades = []; total = 0
                if got.get('hist'):
                    req, js = got['hist'][-1]; data = js.get('data') or {}
                    trades = list(data.get('list') or []); total = data.get('total') or 0
                    body = json.loads(req.post_data or '{}'); headers = {k: v for k, v in req.headers.items() if not k.startswith(':')}
                    page_no = 2
                    while len(trades) < min(total, 1000):
                        body['pageNumber'] = page_no
                        resp = await ctx.request.post(req.url, data=json.dumps(body), headers=headers)
                        more = ((await resp.json()).get('data') or {}).get('list') or []
                        if not more: break
                        trades += more; page_no += 1
                        await p2.wait_for_timeout(800)
            except Exception as e:
                print('err', c.get('nickname'), str(e)[:80], file=sys.stderr); trades = []; total = 0
            await p2.close()
            if len(trades) < 30:
                print('skip', c.get('nickname'), len(trades), file=sys.stderr); continue
            bots.append({'exchange': 'Binance', 'id': pid, 'name': c.get('nickname'), 'meta': c, 'detail': got.get('detail'),
                         'coins': got.get('coins'), 'total': total, 'trades': trades})
            print('add', c.get('nickname'), len(trades), '/', total, file=sys.stderr)
        await b.close()
    json.dump(bots, open('bnb_bots.json', 'w'), ensure_ascii=False)
    print('done', len(bots), sum(len(b['trades']) for b in bots))
asyncio.run(main())
