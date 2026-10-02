"""DCA variants + cross-bot correlation for the 28 trade leads in the top-50 list.
OKX: sub-positions (each add-on is its own record) -> layers, spacing, size scaling, basket close.
Binance: merged positions -> adverse excursion vs avg cost from 4H candles (proxy for averaging / holding through loss)."""
import json, bisect, statistics as st, math
from collections import defaultdict, Counter
F = json.load(open('final50.json'))
TOP = {b['name'] for b in F if b['group'] == 'Trade'}
O = [b for b in json.load(open('okx_bots.json')) if b['name'] in TOP]
B = [b for b in json.load(open('bnb_bots.json')) if b['name'] in TOP]
C = json.load(open('candles_4h.json'))
CT = {s: [r[0] for r in c] for s, c in C.items()}
P = {b['name']: b['metrics']['p'] for b in F if b['group'] == 'Trade'}
FM = {b['name']: b for b in F if b['group'] == 'Trade'}

def mae(sym, side, o, c, px):
    """worst move against avg cost while the position was open (fraction)."""
    if sym not in C: return None
    t = CT[sym]; i = bisect.bisect_left(t, o - 4*3600*1000); j = bisect.bisect_right(t, c)
    bars = C[sym][max(0, i):j]
    if not bars: return None
    if side == 'long': return max(0, (px - min(r[2] for r in bars)) / px)
    return max(0, (max(r[1] for r in bars) - px) / px)

out = []
for b in O:
    T = [t for t in b['trades'] if t.get('closeTime') and t.get('openTime')]
    by = defaultdict(list)
    for t in T: by[(t['instId'], t['posSide'])].append(t)
    adds = down = 0; stack = 0; spac = []; size_r = []; basket = 0; layers_at_close = []
    for (inst, side), arr in by.items():
        arr.sort(key=lambda t: int(t['openTime'])); openl = []
        for t in arr:
            o = int(t['openTime']); px = float(t['openAvgPx']); m = float(t['margin'] or 0)
            openl = [x for x in openl if int(x['closeTime']) > o]
            if openl:
                adds += 1; ref = openl[-1]; rp = float(ref['openAvgPx'])
                worse = (px < rp) if side == 'long' else (px > rp)
                down += worse
                if worse: spac.append(abs(px / rp - 1) * 100)
                rm = float(ref['margin'] or 0)
                if rm > 0 and m > 0: size_r.append(m / rm)
                # basket close: add-on closes within 1 minute of the layer before it
                if abs(int(t['closeTime']) - int(ref['closeTime'])) <= 60000: basket += 1
            openl.append(t); stack = max(stack, len(openl))
    # two-sided: opened while an opposite-side position on the same symbol is still open
    byi = defaultdict(list)
    for t in T: byi[t['instId']].append((int(t['openTime']), int(t['closeTime']), t['posSide']))
    hed = 0
    for arr in byi.values():
        for o, c, sd in arr:
            hed += any(o2 < o < c2 and sd2 != sd for o2, c2, sd2 in arr)
    hedge = round(hed / len(T) * 100)
    wins = [float(t['pnlRatio']) * 100 for t in T if float(t['pnl']) > 0]
    out.append(dict(ex='OKX', name=b['name'], n=len(T), adds=round(adds / len(T) * 100), down=round(down / adds * 100) if adds else None,
                    stack=stack, spacing=round(st.median(spac), 2) if spac else None,
                    size=round(st.median(size_r), 2) if size_r else None,
                    mart=round(sum(1 for r in size_r if r >= 1.3) / len(size_r) * 100) if size_r else None,
                    basket=round(basket / adds * 100) if adds else None, hedge=hedge,
                    tp=round(st.median(wins), 1) if wins else None))
for b in B:
    T = [t for t in b['trades'] if t.get('closed') and t.get('opened')]
    ms = []; wins_deep = 0; wins = 0
    for t in T:
        if int(t['closed']) - int(t['opened']) < 8 * 3600 * 1000: continue  # 4H bars too coarse for short holds
        m = mae(t['symbol'], t['side'].lower(), int(t['opened']), int(t['closed']), float(t['avgCost']))
        if m is None: continue
        ms.append(m * 100)
        if float(t['closingPnl']) > 0:
            wins += 1; wins_deep += (m * float(t['leverage']) >= 0.5)
    tp = [float(t['roi']) * 100 for t in T if float(t['closingPnl']) > 0]
    out.append(dict(ex='Binance', name=b['name'], n=len(T), n_long=len(ms), mae_med=round(st.median(ms), 2) if ms else None,
                    mae_p90=round(sorted(ms)[int(len(ms) * .9) - 1], 2) if ms else None,
                    deep_win=round(wins_deep / wins * 100) if wins else None, tp=round(st.median(tp), 1) if tp else None))

# variant label
for r in out:
    p = P[r['name']]; r.update(win=p['win'], lev=p['lev_med'], hold=p['hold_med'], hold_ratio=p['hold_ratio'],
                               tail=p['tail'], momentum=p['momentum'], pf=p['pf'], users=FM[r['name']]['users_n'],
                               mdd=FM[r['name']]['metrics'].get('mdd'), roi=FM[r['name']]['metrics'].get('roi'))
    if r['ex'] == 'OKX':
        if r['adds'] < 20: v = 'Lệnh đơn'
        elif (r['down'] or 0) <= 40: v = 'Nhồi theo lãi'
        elif r['adds'] < 35 or (r['down'] or 0) < 55: v = 'DCA nhẹ'
        elif (r['size'] or 0) >= 1.3 or (r['mart'] or 0) >= 50: v = 'DCA martingale'
        elif (r['spacing'] or 0) < 0.5: v = 'DCA dày'
        elif r['spacing'] <= 1: v = 'DCA vừa'
        else: v = 'DCA thưa'
    else:
        v = 'Chưa đủ dữ liệu' if r['n_long'] < 8 else 'Gồng lỗ sâu' if (r['deep_win'] or 0) >= 30 else 'Vào–ra dứt khoát'
    r['variant'] = v

def rank(xs):
    s = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0] * len(xs); i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and xs[s[j + 1]] == xs[s[i]]: j += 1
        for k in range(i, j + 1): r[s[k]] = (i + j) / 2
        i = j + 1
    return r
def spear(a, b):
    pr = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pr) < 6: return None, len(pr)
    x, y = rank([p[0] for p in pr]), rank([p[1] for p in pr])
    mx, my = st.mean(x), st.mean(y)
    num = sum((i - mx) * (j - my) for i, j in zip(x, y)); den = math.sqrt(sum((i - mx) ** 2 for i in x) * sum((j - my) ** 2 for j in y))
    return (round(num / den, 2) if den else None), len(pr)

# daily realized PnL correlation (last 60 days, share of each bot's gross)
daily = {}
end = max(int(t.get('closeTime') or t.get('closed') or 0) for b in O + B for t in b['trades'])
D0 = end - 60 * 86400000
for b in O + B:
    s = [0.0] * 60
    for t in b['trades']:
        c = int(t.get('closeTime') or t.get('closed') or 0)
        if c >= D0:
            s[min(59, (c - D0) // 86400000)] += float(t.get('pnl') or t.get('closingPnl') or 0)
    daily[b['name']] = s
names = [r['name'] for r in out]
pairs = []
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, bb = daily[names[i]], daily[names[j]]
        if sum(1 for x in a if x) >= 10 and sum(1 for x in bb if x) >= 10:
            c, _ = spear(a, bb); pairs.append((c, names[i], names[j]))
def pearson(a, b):
    ma, mb = st.mean(a), st.mean(b); da = math.sqrt(sum((x - ma) ** 2 for x in a)); db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (da * db) if da and db else None
def btc_ret(ts, step_ms):
    t = CT['BTCUSDT']; c = C['BTCUSDT']
    px = [c[max(0, bisect.bisect_right(t, x) - 1)][3] for x in ts]
    return [px[i] / px[i - 1] - 1 for i in range(1, len(px))]
eq = {}
for b in O:
    pts = sorted((int(x['beginTs']), float(x['pnlRatio'])) for x in b['meta']['pnlRatios'])[-19:]
    eq[b['name']] = ([p[0] for p in pts], [pts[i][1] - pts[i - 1][1] for i in range(1, len(pts))])
for b in B:
    pts = sorted((int(x['dateTime']), float(x['value'])) for x in b['meta']['chartItems'] if x['dataType'] == 'ROI')
    eq[b['name']] = ([p[0] for p in pts], [(pts[i][1] - pts[i - 1][1]) / 100 for i in range(1, len(pts))])
co = {}
for ex, grp in (('OKX', O), ('Binance', B)):
    ns = [b['name'] for b in grp]; L = min(len(eq[n][1]) for n in ns)
    cs = []
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            c = pearson(eq[ns[i]][1][-L:], eq[ns[j]][1][-L:])
            if c is not None: cs.append((round(c, 2), ns[i], ns[j]))
    br = btc_ret(eq[ns[0]][0][-L - 1:], 0)
    beta = {n: round(pearson(eq[n][1][-L:], br), 2) for n in ns if pearson(eq[n][1][-L:], br) is not None}
    v = [c[0] for c in cs]
    co[ex] = dict(points=L, pairs=len(cs), med=round(st.median(v), 2), hi=round(sum(1 for x in v if x >= .5) / len(v) * 100),
                  neg=round(sum(1 for x in v if x < 0) / len(v) * 100), top=sorted(cs, reverse=True)[:3],
                  btc_med=round(st.median(beta.values()), 2), btc_hi=sum(1 for x in beta.values() if abs(x) >= .5), beta=beta)
    for r in out:
        if r['name'] in beta: r['btc'] = beta[r['name']]
    print(ex, {k: co[ex][k] for k in co[ex] if k != 'beta'})
res = dict(bots=out, pairs=sorted(pairs, reverse=True), co=co)
for r in out: print({k: r[k] for k in r if k not in ('users',)})
print(Counter(r['variant'] for r in out))
pc = [p[0] for p in pairs if p[0] is not None]
print('pairs', len(pc), 'median', st.median(pc), 'share>0.3', sum(1 for x in pc if x > .3) / len(pc), 'top', pairs[:5], 'bottom', pairs[-3:])
okx = [r for r in out if r['ex'] == 'OKX']
for a, b2 in [('adds', 'win'), ('adds', 'tail'), ('adds', 'hold_ratio'), ('adds', 'users'), ('stack', 'tail'), ('lev', 'tail'), ('adds', 'pf'), ('down', 'win'), ('adds', 'roi')]:
    print('OKX', a, b2, spear([r[a] for r in okx], [r[b2] for r in okx]))
bn = [r for r in out if r['ex'] == 'Binance']
for a, b2 in [('deep_win', 'win'), ('deep_win', 'mdd'), ('deep_win', 'users'), ('mae_med', 'win'), ('deep_win', 'tail'), ('lev', 'mdd')]:
    print('BNB', a, b2, spear([r[a] for r in bn], [r[b2] for r in bn]))
allr = out
for a, b2 in [('win', 'tail'), ('hold_ratio', 'win'), ('lev', 'tail'), ('win', 'users'), ('momentum', 'win')]:
    print('ALL', a, b2, spear([r[a] for r in allr], [r[b2] for r in allr]))

okx = [r for r in out if r['ex'] == 'OKX']; bn = [r for r in out if r['ex'] == 'Binance']
TR = [("OKX", "Tỷ lệ lệnh mở thêm", "Tỷ lệ thắng", okx, 'adds', 'win', "DCA nhiều không làm thắng nhiều hơn"),
      ("OKX", "Tỷ lệ lệnh mở thêm", "Đuôi lỗ", okx, 'adds', 'tail', "DCA càng nhiều, lệnh lỗ lớn nhất càng to"),
      ("OKX", "Số tầng tối đa", "Đuôi lỗ", okx, 'stack', 'tail', "Chồng càng nhiều tầng, cú lỗ cuối càng nặng"),
      ("OKX", "Tỷ lệ lệnh mở thêm", "ROI", okx, 'adds', 'roi', "Bot DCA dày có ROI thấp hơn"),
      ("OKX", "Tỷ lệ lệnh mở thêm", "Số người copy", okx, 'adds', 'users', "Người copy hơi chuộng bot DCA"),
      ("Cả hai", "Giữ lệnh lỗ lâu hơn lệnh lãi", "Tỷ lệ thắng", out, 'hold_ratio', 'win', "Tỷ lệ thắng cao phần lớn nhờ gồng lỗ"),
      ("Cả hai", "Tỷ lệ thắng", "Số người copy", out, 'win', 'users', "Người copy chạy theo tỷ lệ thắng"),
      ("Binance", "Lệnh thắng từng lỗ sâu", "MDD", bn, 'deep_win', 'mdd', "Gồng lỗ đi cùng sụt vốn lớn hơn")]
res['traits'] = []
for ex, la, lb, grp, a, b2, mean in TR:
    rho, n = spear([r.get(a) for r in grp], [r.get(b2) for r in grp])
    res['traits'].append(dict(ex=ex, a=la, b=lb, rho=rho, n=n, mean=mean))
json.dump(res, open('dca_variants.json', 'w'), ensure_ascii=False, indent=1)
print(res['traits'])
