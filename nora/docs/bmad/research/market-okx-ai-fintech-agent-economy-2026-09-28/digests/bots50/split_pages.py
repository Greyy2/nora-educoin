"""Split each report section into short sub-pages with a grouped sidebar menu.
Runs on the built HTML (post-process), so it survives rebuilds of build_v3.py.
The inline <script> is untouched, so the CSP hash stays valid."""
import copy
import sys
from bs4 import BeautifulSoup

PATH = sys.argv[1] if len(sys.argv) > 1 else '/home/ubuntu/norabt/okx-report.html'
soup = BeautifulSoup(open(PATH).read(), 'html.parser')
main = soup.find('main')
secs = {s['id']: s for s in main.find_all('section', class_='sec', recursive=False)}


def kids(sec):
    return [c for c in sec.children if getattr(c, 'name', None)]


def grid_cards(el):
    return [c for c in el.children if getattr(c, 'name', None)]


def head(num, group, title, sub=''):
    h = BeautifulSoup(f'<div class="sec-head"><div><div class="eyebrow">Mục {num} · {group}</div><h2>{title}</h2>'
                      + (f'<p>{sub}</p>' if sub else '') + '</div></div>', 'html.parser')
    return h


def page(pid, num, group, title, blocks, sub=''):
    s = soup.new_tag('section', attrs={'class': 'sec', 'id': pid, 'hidden': ''})
    s.append(head(num, group, title, sub))
    for b in blocks:
        s.append(copy.copy(b))
    return s


def strip_part(card):
    """Drop the numbered 'part' header inside a card (the page title already says it)."""
    c = copy.copy(card)
    p = c.find('div', class_='part')
    if p:
        sub = p.find('p', class_='sub')
        p.replace_with(sub) if sub else p.decompose()
    return c


K = {sid: kids(s) for sid, s in secs.items()}
pages = []   # (group_num, group_label, [(pid, sub_num, sub_label, section)])

# 1, 2: single pages, unchanged
pages.append(("1", "Tóm tắt", [("s1", None, "Tóm tắt", secs['s1'])]))
pages.append(("2", "Quy mô", [("s2", None, "Quy mô", secs['s2'])]))

# 3 Market: one page
pages.append(("3", "Market", [("s3", None, "Market", secs['s3'])]))

# 4 Xu hướng: 3 pages
c = K['s4']; note = c[5]
pages.append(("4", "Xu hướng", [
    ("s4a", "4.1", "Cầu &amp; cung", page("s4a", "4.1", "Xu hướng", "Người dùng muốn gì, người tạo đang làm gì", [c[1], c[2], note])),
    ("s4c", "4.2", "Cung – cầu lệch", page("s4c", "4.2", "Xu hướng", "Cung và cầu lệch nhau", [c[3]])),
    ("s4d", "4.3", "Regime hiện tại", page("s4d", "4.3", "Xu hướng", "Regime thị trường hiện tại", [c[4]])),
]))

# 5 Flow: one page
pages.append(("5", "Flow tổng thể", [("s5", None, "Flow tổng thể", secs['s5'])]))

# 6 Top bot: 3 pages
c = K['s6']
tb = {c2['data-bt']: c2 for c2 in c if c2.get('data-bt')}
grid = [x for x in c if 'grid2' in (x.get('class') or [])][0]
def titled(block, title):
    b = copy.copy(block)
    b.insert(0, BeautifulSoup(f'<div><h3>{title}</h3></div>', 'html.parser'))
    return b
pages.append(("6", "Top bot", [
    ("s6a", "6.1", "Tổng quan", page("s6a", "6.1", "Top bot", "50 bot đang ra tiền: tổng quan", [c[1], tb['cov'], grid], "28 trade · 10 grid/DCA · 6 signal · 6 alpha.")),
    ("s6b", "6.2", "Trade", page("s6b", "6.2", "Top bot", "28 lead copy-trade", [titled(tb['bb-okx'], "OKX · 14 lead"), titled(tb['bb-bnb'], "Binance · 14 lead")], "Bấm vào một bot để xem cách chơi, vì sao hot, hướng đi, regime và rủi ro.")),
    ("s6c", "6.3", "Bot, Signal &amp; Alpha", page("s6c", "6.3", "Top bot", "Bot grid/DCA, kênh tín hiệu và alpha", [titled(tb['bb-bot'], "Bot grid/DCA · 10"), titled(tb['bb-sig'], "Signal · 6"), titled(tb['bb-alpha'], "Alpha / Agent · 6")], "Bấm vào một bot để xem chi tiết.")),
    ("s6d", "6.4", "Lối đánh chung", page("s6d", "6.4", "Top bot", "Bot top có cùng một lối đánh không?",
        [tb['dca-kpi'], tb['ms-dims'], tb['ms-arch'], tb['dca-verdict'], tb['dca-var'], tb['dca-tr'], tb['dca-co']],
        "So 28 bot trade trên 9 khía cạnh, từ list lệnh và đường vốn công bố.")),
]))

# 7 Tâm lý: one page
pages.append(("7", "Tâm lý người dùng", [("s7", None, "Tâm lý người dùng", secs['s7'])]))

# 8 Hướng đi: 2 pages
c = K['s8']
pages.append(("8", "Hướng đi", [
    ("s8a", "8.1", "So sánh", page("s8a", "8.1", "Hướng đi", "Bốn ngách: risk, alpha, signal, trade", [c[1], c[4]])),
    ("s8b", "8.2", "Chi tiết 4 ngách", page("s8b", "8.2", "Hướng đi", "Hiện tại, cơ hội và rủi ro từng ngách", [c[2], c[3]])),
]))

# rebuild <main>
main.clear()
first = True
for gnum, glabel, subs in pages:
    for pid, snum, slabel, sec in subs:
        sec = sec if sec.parent is None else sec.extract()
        if first:
            if sec.has_attr('hidden'): del sec['hidden']
            first = False
        else:
            sec['hidden'] = ''
        main.append(sec)

# rebuild sidebar menu
nav = soup.find('nav', id='nav')
nav.clear()
html = ''
for gnum, glabel, subs in pages:
    if len(subs) == 1:
        pid = subs[0][0]
        html += f'<button data-s="{pid}"><span class="n">{gnum}</span>{glabel}</button>'
    else:
        html += f'<div class="ng"><span class="n">{gnum}</span>{glabel}</div>'
        html += ''.join(f'<button class="sub" data-s="{pid}"><span class="n">{snum}</span>{slabel}</button>' for pid, snum, slabel, _ in subs)
nav.append(BeautifulSoup(html, 'html.parser'))
side_h = soup.find('div', class_='side-h')
if side_h:
    side_h.find_all('div')[-1].string = "8 mục"

# styles for grouped menu
style = soup.find('style')
style.append('''
.nav .ng{display:flex;gap:10px;align-items:baseline;padding:10px 10px 4px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.nav .ng .n{font-family:var(--mono);width:14px}
.nav button.sub{padding:6px 10px 6px 20px;font-size:12.5px}
.nav button.sub .n{width:24px}
@media (max-width:980px){.nav .ng{display:none}.nav button.sub{padding:8px 10px}}
''')
open(PATH, 'w').write(str(soup))
print('pages', [p for _, _, s in pages for p, *_ in s])
