"""Add averaging-down (DCA) analysis to section 8 of the report."""
import json
import statistics as st
from collections import defaultdict

B = '/tmp/claude-1000/-home-ubuntu-norabt/47a0aee2-9f8b-4307-bd29-550a7e8f13f1/scratchpad/build/'
R = json.load(open('bots_profiled.json'))
okx = {b['id']: b for b in json.load(open('okx_bots.json'))}

# ---- per OKX lead: add-on entries while an earlier same-side position on the same symbol is still open
for r in R:
    if r['exchange'] != 'OKX':
        r['p']['dca'] = None
        continue
    T = [t for t in okx[r['id']]['trades'] if t.get('closeTime') and t.get('openTime')]
    by = defaultdict(list)
    for t in T:
        by[(t['instId'], t['posSide'])].append(t)
    adds = down = 0; max_stack = 0
    for (inst, side), arr in by.items():
        arr.sort(key=lambda t: int(t['openTime'])); openl = []
        for t in arr:
            o = int(t['openTime']); px = float(t['openAvgPx'])
            openl = [x for x in openl if int(x['closeTime']) > o]
            if openl:
                adds += 1; ref = float(openl[-1]['openAvgPx'])
                down += (px < ref) if side == 'long' else (px > ref)
            openl.append(t); max_stack = max(max_stack, len(openl))
    d = dict(adds=round(adds / len(T) * 100), down=round(down / adds * 100) if adds else None, stack=max_stack)
    r['p']['dca'] = d
    if d['adds'] >= 35 and (d['down'] or 0) >= 60:
        r['tags'].append('Bình quân giá xuống (DCA)')
        r['story'] += f" Mở thêm lệnh cùng chiều khi lệnh cũ chưa đóng ở {d['adds']}% số lệnh, {d['down']}% trong đó ở giá xấu hơn (bình quân giá xuống), chồng tối đa {d['stack']} vị thế."
json.dump(R, open('bots_profiled.json', 'w'), ensure_ascii=False, indent=1)

O = [r for r in R if r['exchange'] == 'OKX']
n_adds = sum(1 for r in O if r['p']['dca']['adds'] >= 35)
n_down = sum(1 for r in O if r['p']['dca']['adds'] >= 35 and (r['p']['dca']['down'] or 0) >= 60)
n_pyr = sum(1 for r in O if r['p']['dca']['adds'] >= 35 and (r['p']['dca']['down'] or 100) <= 40)
med_down = st.median([r['p']['dca']['down'] for r in O if r['p']['dca']['adds'] >= 35])
med_stack = st.median([r['p']['dca']['stack'] for r in O])
n_strict = sum(1 for r in R if r['style'] == 'Nhồi lệnh, gồng lỗ (DCA)')
big = sorted(O, key=lambda r: -r['p']['dca']['stack'])[:2]
stats = dict(n_adds=n_adds, n_down=n_down, n_pyr=n_pyr, med_down=med_down, med_stack=med_stack, n_strict=n_strict)
print(stats, [(r['name'], r['p']['dca']['stack']) for r in big])

card = f'''<div class="card stack">
        <div><h3>DCA: bot top OKX chủ yếu bình quân giá xuống</h3><p class="sub">Lệnh mở thêm cùng mã, cùng chiều khi lệnh trước chưa đóng; so giá vào với lệnh đang mở trước đó</p></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>Chỉ số (26 lead OKX)</th><th class="r">Kết quả</th></tr></thead>
          <tbody>
            <tr><td>Mở thêm lệnh khi lệnh cũ chưa đóng (≥ 35% số lệnh)</td><td class="r num"><b>{n_adds}/26</b></td></tr>
            <tr><td>Phần lớn lệnh mở thêm ở giá xấu hơn: <b>bình quân giá xuống</b></td><td class="r num"><b>{n_down}/26</b></td></tr>
            <tr><td>Phần lớn lệnh mở thêm khi đang lãi (nhồi theo đà)</td><td class="r num">{n_pyr}/26</td></tr>
            <tr><td>Tỷ lệ lệnh mở thêm ở giá xấu hơn (trung vị)</td><td class="r num">{med_down:g}%</td></tr>
            <tr><td>Số vị thế cùng mở tối đa (trung vị)</td><td class="r num">{med_stack:g}</td></tr>
            <tr><td>DCA <b>kèm gồng lỗ</b> (giữ lệnh lỗ ≥ 2 lần lệnh lãi)</td><td class="r num">{n_strict}/26</td></tr>
          </tbody>
        </table></div>
        <p class="note">Có lead chồng hơn 100 vị thế cùng lúc ({big[0]['name']}: {big[0]['p']['dca']['stack']}; {big[1]['name']}: {big[1]['p']['dca']['stack']}). Binance gộp mọi lần vào thêm thành một vị thế với giá vốn trung bình, nên <b>không đo được DCA trên Binance</b> từ dữ liệu công khai.</p>
      </div>'''
link = '''<div class="card stack">
        <div><h3>Vì sao ba điều này đi cùng nhau</h3><p class="sub">Đánh ngược đà + bình quân giá xuống</p></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>Biểu hiện</th><th>Cơ chế</th></tr></thead>
          <tbody>
            <tr><td><b>Tỷ lệ thắng rất cao</b></td><td>Giá hồi một chút là chốt được lệnh có lãi</td></tr>
            <tr><td><b>Lỗ treo bị giấu</b></td><td>Lệnh lỗ không đóng, nằm ở vị thế đang mở nên không vào tỷ lệ thắng</td></tr>
            <tr><td><b>Đuôi lỗ cực lớn</b></td><td>Khi giá đi một chiều không hồi (đi ngang chuyển sang xu hướng mạnh), các vị thế chồng lên nhau cùng lỗ</td></tr>
          </tbody>
        </table></div>
        <p class="note">Đây là rủi ro mà cảnh báo chuyển regime (Mục 12) nhắm tới: báo trước khi thị trường chuyển sang xu hướng mạnh.</p>
      </div>'''

t = open(B + 'template.html').read()


def R_(a, b):
    global t
    assert a in t, a[:70]
    t = t.replace(a, b, 1)


# BOTS data
a = t.index('const BOTS = ['); b = t.index('];\nconst BAGG', a) + 1
bots_js = json.loads(t[a + len('const BOTS = '):b])
by_name = {(r['exchange'], r['name']): r for r in R}
for x in bots_js:
    r = by_name[(x['ex'], x['name'])]; x['p'] = r['p']; x['tags'] = r['tags']; x['story'] = r['story']
t = t[:a] + 'const BOTS = ' + json.dumps(bots_js, ensure_ascii=False) + t[b:]
# tag counts used by the risk chart
a = t.index('const BAGG = '); b = t.index(';\n', a)
bagg = json.loads(t[a + len('const BAGG = '):b])
from collections import Counter
bagg['tags'] = Counter(tg for r in R for tg in r['tags'])
t = t[:a] + 'const BAGG = ' + json.dumps(bagg, ensure_ascii=False) + t[b:]

# insert DCA cards before the risk-signs row
anchor = '<div class="grid2">\n      <div class="card stack">\n        <div><h3>Dấu hiệu rủi ro phổ biến</h3>'
R_(anchor, '<div class="grid2">\n      ' + card + '\n      ' + link + '\n    </div>\n\n    ' + anchor)

# detail row: DCA line per exchange
R_('<tr><td>Thuận xu hướng / nhồi lệnh</td><td class="r num">${p.aligned??"—"}% / ${p.overlap}%</td></tr>',
   '<tr><td>Thuận xu hướng</td><td class="r num">${p.aligned??"—"}%</td></tr>'
   '<tr><td>Mở thêm khi lệnh cũ chưa đóng / ở giá xấu hơn / chồng tối đa</td><td class="r num">${p.dca?`${p.dca.adds}% / ${p.dca.down??"—"}% / ${p.dca.stack}`:"Không đo được (Binance gộp vị thế)"}</td></tr>')

# verdict bullets + KPI
R_('<li><b>Lỗ treo và đuôi lỗ</b>:',
   f'<li><b>DCA là lối vận hành chủ đạo trên OKX ({n_down}/26 bình quân giá xuống)</b>: cộng với đánh ngược đà, đây là công thức "thắng nhiều lần nhỏ, thua một lần lớn".</li>\n        <li><b>Lỗ treo và đuôi lỗ</b>:')
R_('<div class="t">Bot top kiếm tiền bằng tỷ lệ thắng cao, đánh ngược đà, nhưng đuôi lỗ lớn và lỗ treo bị giấu.',
   '<div class="t">Bot top kiếm tiền bằng tỷ lệ thắng cao, đánh ngược đà và bình quân giá xuống (DCA), nhưng đuôi lỗ lớn và lỗ treo bị giấu.')

# methodology
R_('<b>"Nhồi lệnh"</b>: mở thêm lệnh cùng mã, cùng chiều khi lệnh trước chưa đóng.</li>',
   '<b>"Nhồi lệnh"</b>: mở thêm lệnh cùng mã, cùng chiều khi lệnh trước chưa đóng; <b>"bình quân giá xuống"</b> khi lệnh mở thêm có giá xấu hơn lệnh đang mở trước đó. Chỉ đo được trên OKX (ghi từng vị thế con); Binance gộp vị thế.</li>')

# section 1 finding 07
R_('<p>50 bot top OKX và Binance: 22/50 đánh ngược đà, tỷ lệ thắng trung vị 74–86%,',
   f'<p>50 bot top OKX và Binance: 22/50 đánh ngược đà, {n_down}/26 lead OKX bình quân giá xuống (DCA), tỷ lệ thắng trung vị 74–86%,')

open(B + 'template.html', 'w').write(t)
json.dump(stats, open('dca_stats.json', 'w'))
print('patched')
