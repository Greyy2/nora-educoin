"""Do the 28 top trade leads share one way of thinking? Compare them on 9 dimensions, then group into archetypes."""
import json
from collections import Counter
F = [b for b in json.load(open('final50.json')) if b['group'] == 'Trade']
V = {r['name']: r for r in json.load(open('dca_variants.json'))['bots']}
N = len(F)
def avg_in(b):
    v = V[b['name']]['variant']
    return v.startswith('DCA') or v == 'Gồng lỗ sâu'
DIMS = [
    ("Vào lệnh", lambda p, b: 'Ngược đà' if (p['momentum'] or 50) <= 42 else 'Theo đà' if p['momentum'] >= 58 else 'Trung tính'),
    ("Khi giá đi ngược", lambda p, b: 'Vào thêm hoặc gồng' if avg_in(b) else 'Không vào thêm'),
    ("Tỷ lệ thắng", lambda p, b: '≥ 70%' if p['win'] >= 70 else '< 70%'),
    ("Lãi TB so với lỗ TB", lambda p, b: 'Lãi nhỏ hơn lỗ' if p['payoff'] is not None and p['payoff'] < 1 else 'Lãi lớn hơn lỗ'),
    ("Giữ lệnh lỗ", lambda p, b: 'Lâu hơn lệnh lãi' if (p['hold_ratio'] or 0) > 1 else 'Ngắn hơn lệnh lãi'),
    ("Kiếm nhiều nhất khi", lambda p, b: {'range': 'Đi ngang', 'up': 'Xu hướng tăng', 'down': 'Xu hướng giảm'}[max(p['reg_pnl'], key=lambda k: p['reg_pnl'][k])]),
    ("Chiều", lambda p, b: 'Nghiêng long' if p['long_pct'] >= 65 else 'Nghiêng short' if p['long_pct'] <= 35 else 'Hai chiều'),
    ("Đòn bẩy", lambda p, b: '≥ 20x' if p['lev_med'] >= 20 else '< 20x'),
    ("Nguồn lãi", lambda p, b: 'Dồn vào ≤ 5 lệnh' if (p['top5_share'] or 0) >= 60 else 'Rải đều nhiều lệnh'),
]
rows = []
for name, f in DIMS:
    c = Counter(f(b['metrics']['p'], b) for b in F)
    (top, n), *rest = c.most_common()
    share = round(n / N * 100)
    level = 'Giống nhau' if share >= 70 else 'Khá giống' if share >= 55 else 'Khác nhau'
    rows.append(dict(dim=name, top=top, n=n, share=share, rest=[(k, v) for k, v in rest], level=level))
    print(name, c.most_common(), level)

# archetypes
def arche(b):
    p = b['metrics']['p']
    if avg_in(b) and p['win'] >= 70 and (p['momentum'] or 50) < 58: return 'Bắt hồi, bình quân giá'
    if (p['momentum'] or 0) >= 58: return 'Theo đà'
    if p['win'] < 70 or (p['top5_share'] or 0) >= 60 and (p['payoff'] or 0) >= 2: return 'Săn cú lớn'
    return 'Lướt ngắn, chốt nhanh'
A = Counter(); members = {}
for b in F:
    a = arche(b); A[a] += 1; members.setdefault(a, []).append(b['name'])
print(A, members)
ARCH_DESC = {'Bắt hồi, bình quân giá': 'Vào ngược hoặc trung tính, giá đi ngược thì vào thêm hoặc gồng, chốt khi hồi. Thắng nhiều lần nhỏ.',
             'Săn cú lớn': 'Chấp nhận thua nhiều lần, lãi dồn vào vài lệnh lớn.',
             'Theo đà': 'Vào cùng chiều giá vừa chạy, bám xu hướng.',
             'Lướt ngắn, chốt nhanh': 'Giữ lệnh ngắn, vào ra dứt khoát, ít khi vào thêm.'}
arch = []
for a, n in A.most_common():
    g = [b for b in F if arche(b) == a]; ps = [b['metrics']['p'] for b in g]
    md = lambda xs: sorted(xs)[len(xs) // 2]
    arch.append(dict(name=a, desc=ARCH_DESC[a], n=n, okx=sum(1 for b in g if b['where'].startswith('OKX')),
                     win=md([p['win'] for p in ps]), lev=md([p['lev_med'] for p in ps]), hold=md([p['hold_med'] for p in ps]),
                     examples=[b['name'] for b in g][:3]))
json.dump(dict(n=N, dims=rows, arch=arch, of={b['name']: arche(b) for b in F}), open('mindset.json', 'w'), ensure_ascii=False, indent=1)
