"""Build the restructured 8-section report -> /home/ubuntu/norabt/okx-report.html"""
import json
import re
from collections import Counter

SP = '/tmp/claude-1000/-home-ubuntu-norabt/47a0aee2-9f8b-4307-bd29-550a7e8f13f1/scratchpad/'
BU = SP + 'build/'
RESEARCH = '/home/ubuntu/norabt/_bmad-output/planning-artifacts/research/market-okx-ai-fintech-agent-economy-2026-09-28/research.md'

old = open(BU + 'template.html').read()
CSS = old[old.index('<style>'):old.index('</style>') + 8]
CSS = CSS.replace('</style>', '\n.part{display:flex;gap:12px;align-items:flex-start}\n.part .pn{flex-shrink:0;width:30px;height:30px;border-radius:9px;background:var(--accent);color:var(--accent-ink);display:grid;place-items:center;font-family:var(--mono);font-weight:700;font-size:14px}\n.part h3{font-size:16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}\n.ptag{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}\n.dir{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}\n.dir.up{background:var(--good-soft);color:var(--good)}.dir.down{background:var(--bad-soft);color:var(--bad)}.dir.flat{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}\n.pair{display:flex;align-items:center;gap:8px;min-width:160px}.pair+.pair{margin-top:4px}\n.pair span[class^="bar"]{height:8px;border-radius:0 4px 4px 0;display:block;min-width:2px}\n.bar-o{background:var(--bar)}.bar-n{background:var(--accent)}\n.pair .v{font-family:var(--mono);font-size:11.5px;color:var(--ink-2);font-variant-numeric:tabular-nums}\n.legend2{display:flex;gap:16px;font-size:12px;color:var(--ink-2)}.legend2 span{display:inline-flex;gap:6px;align-items:center}.legend2 i{width:14px;height:8px;border-radius:2px;display:inline-block}\n.ops{list-style:none;margin:0;padding:0;display:grid;gap:8px}\n.ops li{display:grid;grid-template-columns:minmax(150px,230px) 1fr;gap:12px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--surface-2);font-size:13px;color:var(--ink-2)}\n.ops li b{color:var(--ink)}\n.lead{font-size:14.5px;color:var(--ink-2);max-width:75ch}.lead b{color:var(--ink)}\n@media (max-width:640px){.ops li{grid-template-columns:1fr;gap:2px}.pair{min-width:120px}}\n' + '</style>')
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&family=Noto+Sans+SC:wght@400;600;700&display=swap">')
HELPERS = open(SP + 'build/market_js_helpers.js').read()

F50 = json.load(open('final50.json'))
TOP = json.load(open(BU + 'top100.json'))
NOW = json.load(open('regime_now.json'))
A = json.load(open('bots_agg.json'))
EX = json.load(open('bots_ex.json'))
DCA = json.load(open('dca_stats.json'))
PC = json.load(open('psych_corr.json'))
R = json.load(open('bots_profiled.json'))
md = open(RESEARCH).read()
SOURCES = sorted([dict(n=int(m[1]), what=m[2], pub=m[3], url=m[4], date=m[5], conf=m[7])
                  for m in re.finditer(r'^\| \[(\d+)\] \| (.*?) \| \[(.*?)\]\((.*?)\) \| (.*?) \| (.*?) \| (.*?) \|$', md, re.M)], key=lambda s: s['n'])

S = lambda *ns: ''
fmt = lambda v: f"{v:,.0f}".replace(',', '.')
pct = lambda v: f"{v:g}".replace('.', ',')
REG = {"up": "Tăng", "down": "Giảm", "range": "Đi ngang"}
PILL = {"up": "good", "down": "bad", "range": "neu"}


def head(n, eyebrow, h2, p):
    return f'<div class="sec-head"><div><div class="eyebrow">{("Mục " + str(n) + " · " + eyebrow) if n != "PL" else eyebrow}</div><h2>{h2}</h2><p>{p}</p></div></div>'


def table(headers, rows, right=()):
    th = ''.join(f'<th{" class=\"r\"" if i in right else ""}>{h}</th>' for i, h in enumerate(headers))
    tr = ''.join('<tr>' + ''.join(f'<td{" class=\"r num\"" if i in right else ""}>{c}</td>' for i, c in enumerate(r)) + '</tr>' for r in rows)
    return f'<div class="tbl-wrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def card(title, sub, body, extra=''):
    s = f'<p class="sub">{sub}</p>' if sub else ''
    return f'<div class="card stack"{extra}><div><h3>{title}</h3>{s}</div>{body}</div>'


def kpi(label, value, desc):
    return f'<div class="kpi"><span class="l">{label}</span><span class="v">{value}</span><span class="d">{desc}</span></div>'


grid2 = lambda a, b: f'<div class="grid2">{a}{b}</div>'

# ------------------------------------------------------------------ numbers
reg_cnt = Counter(o['reg'] for o in NOW); hv_n = sum(1 for o in NOW if o['hv'])
btc = next(o for o in NOW if o['sym'] == 'BTCUSDT'); eth = next(o for o in NOW if o['sym'] == 'ETHUSDT')
bar_time = NOW[0]['bar']
n_counter = sum(1 for r in R if r['style'] == 'Bắt đảo chiều, ngược đà')
fit_cnt = Counter(o['fit_tone'] for o in F50)
grp_cnt = Counter(o['group'] for o in F50)

# Concise section content (spliced into build_v3.py between the data block and the nav/script block).
# Relies on names defined above it in build_v2.py: head, table, card, kpi, grid2, S, fmt, pct, REG, PILL,
# NOW, A, EX, DCA, PC, R, TOP, F50, reg_cnt, hv_n, btc, eth, bar_time, n_counter, fit_cnt, grp_cnt, money_rows.
from collections import Counter

style_counts = Counter(r['style'] for r in R)
money_rows = [("GMGN", 42552399), ("fomo Wallet", 31076068), ("Axiom", 18228223), ("Polymarket", 14365000), ("Terminal", 2626204), ("Maestro", 1345310), ("Bankr (AI agent)", 1118200), ("Virtuals Protocol", 596920), ("TermiX ('AI Agents')", 227074)]

# ================================================================== 1. TÓM TẮT
s1 = f'''<section class="sec" id="s1">
{head(1, "Tóm tắt", "Tiền nằm ở bot giao dịch và tín hiệu, chưa nằm ở chợ agent", "Dữ liệu thực đo 28–29/09/2026 trên OKX, Binance và DefiLlama.")}
<div class="kpis">
{kpi("Top 3 app giao dịch", "$92M", "doanh thu 30 ngày" + S(12))}
{kpi("Chợ agent OKX.AI", "$9.653", "tổng từ 07/2026" + S(2))}
{kpi("Bot top giải mã", "50", f"{fmt(A['n_trades'])} lệnh")}
{kpi("Mã đang đi ngang", f"{reg_cnt['range']}/30", "regime hiện tại")}
</div>
<div class="verdict"><span class="eyebrow">Kết luận</span>
<div class="t">Bot top thắng nhờ đánh ngược đà và DCA, nhưng che lỗ treo. Ngách hấp dẫn: tín hiệu, alpha có kiểm chứng và kiểm soát rủi ro gắn vào bot.</div></div>
{card("Năm điều cần biết", "", f"""
<div class="finding"><span class="i">01</span><div><h4>Chợ agent nhỏ hơn bot giao dịch hàng nghìn lần</h4><p>$9.653 cộng dồn so với $92M mỗi 30 ngày.{S(2, 12)}</p></div></div>
<div class="finding"><span class="i">02</span><div><h4>Bot top đánh ngược đà và DCA</h4><p>{n_counter}/50 đánh ngược đà; {DCA['n_down']}/26 lead OKX bình quân giá xuống.</p></div></div>
<div class="finding"><span class="i">03</span><div><h4>Tỷ lệ thắng đẹp che lỗ treo</h4><p>{A['okx_open_neg']}/26 lead OKX ôm lỗ chưa chốt, tổng {fmt(A['okx_open_upl'])} USDT.</p></div></div>
<div class="finding"><span class="i">04</span><div><h4>Thị trường đi ngang: hợp bot top, dễ vỡ nếu ra xu hướng</h4><p>{reg_cnt['range']}/30 mã đi ngang; {hv_n} mã biến động cao.</p></div></div>
<div class="finding"><span class="i">05</span><div><h4>Người dùng chọn theo đám đông, không theo rủi ro</h4><p>Công cụ rủi ro chỉ có 0,3% lượt dùng trên OKX.AI.{S(1)}</p></div></div>""")}
</section>'''

# ================================================================== 2. QUY MÔ
scale = table(["Thị trường", "Giá trị", "Loại"], [
    ["Chợ task OKX.AI", "$9,7K", "cộng dồn" + S(2)],
    ["Thanh toán x402", "$41–50M", "cộng dồn, ~50% ảo" + S(14, 15)],
    ["Bot giao dịch top 3", "$92M", "30 ngày" + S(12)],
    ["Agent tài chính doanh nghiệp (Ramp)", "$1,5B", "theo năm" + S(21)],
    ["Agentic commerce toàn cầu 2030", "$3–5T", "dự báo" + S(35)],
], right=(1,))
s2 = f'''<section class="sec" id="s2" hidden="">
{head(2, "Quy mô", "Chợ agent ở mức nghìn USD, giao dịch ở mức chục triệu USD mỗi tháng", "Cột cam là toàn bộ chợ task OKX.AI.")}
{grid2(card("Doanh thu 30 ngày", "DefiLlama, đến 27/09/2026",
            '<div class="hbar" id="chart-money"></div><div class="axis"><span></span><span class="ticks"><span>$0</span><span>$10M</span><span>$20M</span><span>$30M</span><span>$40M</span></span><span></span></div>'),
       card("Thang quy mô", "Khác đơn vị, chỉ để so độ lớn", scale))}
</section>'''

# ================================================================== 3. MARKET
mk_map = table(["", "OKX", "Binance"], [
    ["<b>Người dùng</b>", "150M+", "300M+"],
    ["<b>Chợ agent bên thứ ba</b>", "Có (146 agent)" + S(1), "Không" + S(63)],
    ["<b>Bot có sẵn</b>", "1,7M+ bot" + S(57), "126K bot" + S(60)],
    ["<b>Copy-trade top</b>", "10.055 người copy một bot" + S(57), "Lead lãi $1,21M/30 ngày" + S(59)],
    ["<b>Người tạo kiếm tiền</b>", "Chia 1–30% lợi nhuận, thuê bao", "Chia ≤30% + 10% hoa hồng" + S(61)],
    ["<b>Tham số AI cho bot</b>", "Đặt một lần lúc tạo" + S(80), "Đặt một lần lúc tạo" + S(79)],
])
play = table(["Lối chơi bot top (trung vị)", "OKX", "Binance"], [
    ["Giữ lệnh", f"{pct(A['hold_med']['OKX'])} giờ", f"{pct(A['hold_med']['Binance'])} giờ"],
    ["Tỷ lệ long", f"{pct(A['long_med']['OKX'])}%", f"{pct(A['long_med']['Binance'])}%"],
    ["Tỷ lệ thắng", f"{pct(A['win_med']['OKX'])}%", f"{pct(A['win_med']['Binance'])}%"],
    ["Đòn bẩy", f"{pct(A['lev_med']['OKX'])}x", f"{pct(A['lev_med']['Binance'])}x"],
    ["Lệnh TradFi", f"{EX['OKX']['cls'].get('tradfi', 0)}%", f"{EX['Binance']['cls'].get('tradfi', 0)}%"],
], right=(1, 2))
s3 = f'''<section class="sec" id="s3" hidden="">
{head(3, "Market", "Hai sàn đã có hạ tầng agent; người dùng vẫn ở copy-trade và bot", "Chụp trực tiếp từ trang và API công khai.")}
{grid2(card("OKX và Binance", "", mk_map), card("Bot top chơi khác nhau thế nào", "OKX nghiêng long, giữ lâu; Binance cân bằng, lướt nhanh", play))}
</section>'''

# ================================================================== 4. XU HƯỚNG
def dirc(k, label=""):
    icon = {"up": "↑", "down": "↓", "flat": "→"}[k]
    return f'<span class="dir {k}">{icon}{(" " + label) if label else ""}</span>'

def part(n, title, tag, sub=""):
    return (f'<div class="part"><span class="pn">{n}</span><div><h3>{title} <span class="ptag">{tag}</span></h3>'
            + (f'<p class="sub">{sub}</p>' if sub else '') + '</div></div>')

def bars(old, new):
    return (f'<div class="pair"><span class="bar-o" style="width:{old * 2}%"></span><span class="v">{old}%</span></div>'
            f'<div class="pair"><span class="bar-n" style="width:{new * 2}%"></span><span class="v">{new}%</span></div>')

users_rows = [
    ("Dùng tín hiệu nhiều nhất", "93% lượt dùng fintech OKX.AI; 75.460 signal bot trên OKX", "up"),
    ("Copy bot DCA/grid", "10.055 người copy một bot; OKX có hơn 1,7M bot", "up"),
    ("Chuyển sang cổ phiếu, hàng hoá token hoá", "~20% lệnh của bot top", "up"),
    ("Đổi app giao dịch rất nhanh", "fomo: 30 ngày gần nhất = 45% doanh thu cả năm; Photon, Banana Gun sụt mạnh", "up"),
    ("Chọn theo đám đông và tỷ lệ thắng", "Số người copy đi cùng AUM (0,66) và tỷ lệ thắng (0,54)", "flat"),
    ("Người theo tín hiệu là nhỏ lẻ", "Trung bình ~$3 AUM mỗi người theo", "flat"),
    ("Không mua công cụ rủi ro bán lẻ", "25 agent, 27 lượt dùng", "down"),
]
users_tr = table(["Xu hướng", "Bằng chứng", "Hướng"], [[f"<b>{t}</b>", e, dirc(d)] for t, e, d in users_rows])

shift_rows = [("Tín hiệu &amp; dữ liệu", 48, 26, "down", "đã bão hoà"), ("Giao dịch, copy-trade", 6, 17, "up", ""),
              ("xStocks (cổ phiếu token hoá)", 0, 10, "up", ""), ("Hạ tầng tin cậy", 12, 14, "up", ""), ("Rủi ro &amp; bảo mật", 25, 22, "flat", "")]
shift = table(["Ngách người tạo chọn", "Listing cũ → mới", "Hướng"], [[f"<b>{n}</b>", bars(o, w), dirc(d, lab)] for n, o, w, d, lab in shift_rows])
ops = '<ul class="ops">' + ''.join(f'<li><b>{h}</b><span>{t}</span></li>' for h, t in [
    ("Chuyển từ bán lẻ sang thuê bao", "gói thuê bao tăng từ 1 (listing cũ) lên 7 (listing mới)"),
    ("Chạy bot bằng API", "11/24 lead Binance top"),
    ("Chạy hai chiều cùng lúc", "cùng một người tạo chạy cả DCA long lẫn DCA short ETH"),
    ("Đăng ký nhiều, ra tiền ít", "OKX.AI có 10.000+ agent đăng ký nhưng chỉ 146 online"),
    ("Né phần sàn cho miễn phí", "người tạo dồn sang chiến lược và tín hiệu"),
]) + '</ul>'

GAP = json.load(open('gap.json'))
GN = {"SIG": "Tín hiệu", "TRADE": "Giao dịch", "DEFI": "DeFi yield", "PRED": "Dự đoán", "RISK": "Rủi ro", "INFRA": "Hạ tầng tin cậy", "RWA": "xStocks"}
def verdict_tag(o):
    if o['k'] == 'SIG': return '<span class="pill warn">Dồn vào 1 agent</span>'
    r = o['ratio_ex'] or 0
    if r >= 1.5: return '<span class="pill good">Thiếu cung</span>' + (' <span class="muted">mẫu nhỏ</span>' if o['n'] <= 4 else '')
    return '<span class="pill bad">Dư cung</span>' if r < 0.2 else '<span class="pill neu">Cân bằng</span>'
def sd(sup, dem):
    return (f'<div class="pair"><span class="bar-o" style="width:{min(sup, 100)}%"></span><span class="v">{pct(sup)}%</span></div>'
            f'<div class="pair"><span class="bar-n" style="width:{min(dem, 100)}%"></span><span class="v">{pct(dem)}%</span></div>')
gap = table(["Ngách", "Cung → cầu", "Kết luận"], [[f"<b>{GN[o['k']]}</b>", sd(o['sup'], o['dem']), verdict_tag(o)] for o in GAP if o['k'] in GN])

rn_rows = [[f"<b>{o['sym'].replace('USDT', '')}</b>",
            f'<span class="pill {PILL[o["reg"]]}">{REG[o["reg"]]}</span>' + (' <span class="pill warn">Biến động cao</span>' if o['hv'] else ''),
            pct(o['r7']) + "%" if o['r7'] is not None else "—"] for o in NOW[:12]]
style_fit = table(["Lối chơi", "Lúc này"], [
    ["Ngược đà, DCA, grid", '<span class="pill good">Hợp</span>'],
    ["Theo xu hướng", '<span class="pill warn">Kém hợp</span>'],
    ["Nghiêng long", '<span class="pill warn">Rủi ro</span> nhiều mã đỏ 7 ngày'],
])
scen = table(["Nếu chuyển sang", "Bị ảnh hưởng nhất", "Dấu hiệu báo trước"], [
    ["Xu hướng giảm", "DCA long, lead OKX nghiêng long", "Biến động nén rồi bung xuống, funding âm"],
    ["Xu hướng tăng mạnh", "DCA short (bot ETH short top OKX)", "OI tăng, funding dương cực đoan"],
    ["Biến động cực cao", "Bot đòn bẩy ≥ 20x, lưới hẹp", "ATR tăng vọt, lịch CPI/FOMC"],
])
legend2 = lambda a, b: f'<div class="legend2"><span><i class="bar-o"></i>{a}</span><span><i class="bar-n"></i>{b}</span></div>'
s4 = f"""<section class="sec" id="s4" hidden="">
{head(4, "Xu hướng", "Người dùng muốn tín hiệu và copy bot; người tạo đang rời tín hiệu", "Hai phía cầu và cung, rồi regime thị trường hiện tại.")}
<div class="card stack">{part(1, "Xu hướng người dùng bot", "Cầu")}{users_tr}</div>
<div class="card stack">{part(2, "Xu hướng người tạo agent", "Cung", "Tỷ trọng ngách giữa listing cũ (48) và listing mới (58) trên OKX.AI")}
{legend2("Listing cũ", "Listing mới")}{shift}
<div><div class="eyebrow" style="margin-bottom:6px">Cách vận hành và bán cũng đổi</div>{ops}</div></div>
<div class="card stack">{part(3, "Cung và cầu lệch nhau", "Lệch")}
<p class="lead">Người dùng vẫn chủ yếu dùng <b>tín hiệu và copy bot</b>, trong khi người tạo đang <b>rời tín hiệu</b> để sang giao dịch, xStocks và thuê bao.</p>
{legend2("Cung: % số agent", "Cầu: % lượt dùng")}{gap}
<p class="note">Rủi ro, hạ tầng tin cậy, xStocks: 45 agent (42,5% cung) chỉ có 0,4% lượt dùng. Cầu copy-trade thật nằm trên chợ của sàn (10.055 người copy một bot).</p></div>
<div class="card stack">{part(4, "Regime hiện tại", "Thị trường", f"Nến 4 giờ đóng lúc {bar_time} UTC")}
<div class="kpis">
{kpi("Đi ngang", f"{reg_cnt['range']}/30", "mã bot top đánh nhiều")}
{kpi("Tăng / giảm", f"{reg_cnt['up']} / {reg_cnt['down']}", "mã")}
{kpi("Biến động cao", f"{hv_n}/30", "mã")}
{kpi("BTC 7 ngày", f"{pct(btc['r7'])}%", f"ETH {pct(eth['r7'])}%; cả hai đi ngang")}
</div>
{grid2('<div class="stack"><div class="eyebrow">Lối chơi nào hợp lúc này</div>' + style_fit + '</div>', '<div class="stack"><div class="eyebrow">12 mã bot top đánh nhiều nhất</div>' + table(["Mã", "Regime", "7 ngày"], rn_rows, right=(2,)) + '</div>')}
<div class="stack"><div class="eyebrow">Khi regime đổi</div>{scen}</div></div>
<p class="note">Lưu ý phương pháp: "listing cũ/mới" suy từ mã agent OKX.AI (mã &lt; 10.000 là cũ) vì sàn không công bố ngày đăng; đây là cách gần đúng.</p>
</section>"""

# ================================================================== 5. FLOW TỔNG THỂ
tiers = Counter(t['tier'] for t in TOP)
flow_pay = '''<div class="swim">
<div class="fnode"><span class="k">1</span><h4>Người mua</h4><p>Trader, người copy, agent</p></div>
<div class="fnode"><span class="k">2</span><h4>Trả tiền</h4><p>Phí lệnh, chia lợi nhuận, thuê bao, x402</p></div>
<div class="fnode opp"><span class="k">3</span><h4>Người tạo</h4><p>Lead, bot, kênh tín hiệu, agent</p></div>
<div class="fnode"><span class="k">4</span><h4>Sàn</h4><p>Giữ tiền, thu phí mọi lệnh</p></div>
<div class="fnode"><span class="k">5</span><h4>On-chain</h4><p>X Layer, BNB Chain</p></div></div>'''
chain = '''<div class="flow">
<div class="fnode free"><span class="k">DỮ LIỆU</span><h4>Gần như miễn phí</h4></div>
<div class="fnode opp"><span class="k">TÍN HIỆU / ALPHA</span><h4>Có người trả</h4></div>
<div class="fnode free"><span class="k">QUÉT TOKEN</span><h4>Miễn phí</h4></div>
<div class="fnode opp"><span class="k">KIỂM SOÁT RỦI RO</span><h4>Chưa ai làm</h4></div>
<div class="fnode free"><span class="k">THỰC THI</span><h4>Sàn cho miễn phí</h4></div>
<div class="fnode free"><span class="k">THANH TOÁN</span><h4>Sàn nắm</h4></div></div>'''
niche_heat = table(["Ngách", "Lượt dùng OKX.AI", "Độ hot"], [
    ["Tín hiệu &amp; dữ liệu", "93,2%", '<span class="pill good">Rất hot</span>'],
    ["Giao dịch &amp; copy-trade", "2,1%", '<span class="pill good">Rất hot</span>'],
    ["Thị trường dự đoán", "0,2%", '<span class="pill good">Hot</span>'],
    ["Hạ tầng thanh toán", "0,1%", '<span class="pill warn">Ấm</span>'],
    ["DeFi yield", "4,0%", '<span class="pill bad">Lạnh</span>'],
    ["Rủi ro &amp; bảo mật", "0,3%", '<span class="pill bad">Lạnh</span>'],
], right=(1,))
s5 = f'''<section class="sec" id="s5" hidden="">
{head(5, "Flow tổng thể", "Tiền chạy thế nào, khâu nào còn chỗ", "Ô xanh: còn chỗ cho đội nhỏ. Ô sọc: đã miễn phí.")}
{card("Luồng tiền", "", flow_pay)}
{card("Chuỗi giá trị", "", chain)}
{grid2(card("100 agent nổi bật theo ngách", f"Rất hot {tiers['Rất hot']} · Hot {tiers['Hot']} · Ấm {tiers['Ấm']} · Lạnh {tiers['Lạnh']}", '<div class="hbar" id="chart-tn"></div>'),
       card("Độ hot theo ngách", "", niche_heat))}
</section>'''

# ================================================================== 6. TOP BOT
# ---- 6.x: data coverage, DCA variants, cross-bot correlation (from dca_variants.py)
import statistics as _st
DV = json.load(open('dca_variants.json'))
VB = {r['name']: r for r in DV['bots']}
dec = lambda x, d=1: '—' if x is None else f"{x:.{d}f}".replace('.', ',')
sgn = lambda x: '—' if x is None else ('+' if x > 0 else '−' if x < 0 else '') + dec(abs(x), 2)
okx_v = [r for r in DV['bots'] if r['ex'] == 'OKX']; bnb_v = [r for r in DV['bots'] if r['ex'] == 'Binance']
n_dca = sum(1 for r in okx_v if r['variant'].startswith('DCA'))
n_dca_strict = sum(1 for r in okx_v if r['variant'] in ('DCA dày', 'DCA vừa', 'DCA thưa', 'DCA martingale'))
n_deep = sum(1 for r in bnb_v if r['variant'] == 'Gồng lỗ sâu')
CO = DV['co']
MS = json.load(open('mindset.json'))
lvl_pill = {'Giống nhau': 'blue', 'Khá giống': 'warn', 'Khác nhau': 'neu'}
dim_rows = [[f"<b>{d['dim']}</b>", d['top'], f"{d['n']}/{MS['n']}", ', '.join(f"{k} {v}" for k, v in d['rest']),
             f'<span class="pill {lvl_pill[d["level"]]}">{d["level"]}</span>'] for d in sorted(MS['dims'], key=lambda d: -d['share'])]
dims_card = card("So 28 bot trên 9 khía cạnh", "Từ list lệnh. Giống nhau: ≥ 70% bot cùng một kiểu; khác nhau: dưới 55%",
                 table(["Khía cạnh", "Đa số", "Số bot", "Còn lại", "Mức giống"], dim_rows, right=(2,)), ' data-bt="ms-dims"')
hold_h = lambda h: f"{dec(h * 60, 0)} phút" if h < 1 else f"{dec(h, 1)} giờ" if h < 48 else f"{dec(h / 24, 1)} ngày"
arch_rows = [[f"<b>{a['name']}</b><div class=\"note\">{a['desc']}</div>", f"{a['n']}", f"{a['okx']} · {a['n'] - a['okx']}", f"{a['win']}%",
              dec(a['lev'], 0) + 'x', hold_h(a['hold']), ', '.join(a['examples'])] for a in MS['arch']]
arch_card = card("4 lối đánh trong 28 bot", "Xếp mỗi bot vào một lối theo cách vào lệnh, cách xử lý lệnh lỗ và nguồn lãi",
                 table(["Lối đánh", "Bot", "OKX · Binance", "Thắng", "Đòn bẩy", "Giữ lệnh", "Ví dụ"], arch_rows, right=(1, 2, 3, 4, 5)) +
                 '<p class="note">Trung vị mỗi nhóm. Bắt hồi: có vào thêm hoặc gồng khi giá đi ngược, thắng ≥ 70%, không vào theo đà. Theo đà: ≥ 58% lệnh cùng chiều biến động 24 giờ trước. Săn cú lớn: thắng dưới 70%, hoặc lãi dồn vào ≤ 5 lệnh với lãi TB ≥ 2 lần lỗ TB.</p>',
                 ' data-bt="ms-arch"')
top_arch = MS['arch'][0]
d_avg = next(d for d in MS['dims'] if d['dim'] == 'Khi giá đi ngược'); d_win = next(d for d in MS['dims'] if d['dim'] == 'Tỷ lệ thắng')

cov_tbl = table(["Nhóm", "Tiền", "List lệnh", "Regime lúc vào", "Suy ra chiến lược"], [
    ["<b>Trade OKX</b> · 14", "PnL, AUM, ROI", "Có, từng lệnh con", "Có", '<span class="pill good">Đầy đủ: thấy từng tầng DCA</span>'],
    ["<b>Trade Binance</b> · 14", "PnL, ROI, MDD, AUM", "Có, vị thế đã gộp", "Có", '<span class="pill blue">Khá: thấy lối chơi, không thấy từng tầng</span>'],
    ["<b>Bot grid/DCA</b> · 10", "PnL, ROI", "Không", "Không", '<span class="pill warn">Theo loại bot công bố</span>'],
    ["<b>Signal</b> · 6", "AUM người theo, APY backtest", "Không", "Không", '<span class="pill warn">Chỉ mô tả kênh</span>'],
    ["<b>Alpha/Agent</b> · 6", "Doanh thu nền tảng", "Không áp dụng", "Không áp dụng", '<span class="pill neu">Mô hình kinh doanh</span>'],
])
cov_card = card("Mỗi bot có đủ dữ liệu để suy ra chiến lược không?", "28 bot trade: có. 22 bot còn lại: chỉ có số công bố.", cov_tbl +
                '<p class="note">OKX ghi mỗi lần vào thêm thành một lệnh con, nên thấy được bước giá, số tầng, size từng tầng. Binance gộp các lần vào thêm thành một vị thế, nên đo gián tiếp: giá đi ngược bao xa trước khi lệnh về lãi.</p>',
                ' data-bt="cov"')

VAR_ORDER = [("DCA dày", "Bước < 0,5%, nhiều tầng, chốt nhanh"), ("DCA vừa", "Bước 0,5–1%"), ("DCA thưa", "Bước > 1%, ít tầng, giữ lâu"),
             ("DCA martingale", "Tầng sau to gấp đôi tầng trước"), ("DCA nhẹ", "Ít khi vào thêm"), ("Nhồi theo lãi", "Vào thêm khi đang lãi")]
med = lambda xs: _st.median([x for x in xs if x is not None]) if any(x is not None for x in xs) else None
var_rows = []
for v, desc in VAR_ORDER:
    g = [r for r in okx_v if r['variant'] == v]
    if not g: continue
    var_rows.append([f"<b>{v}</b><div class=\"note\">{desc}</div>", str(len(g)), dec(med([r['stack'] for r in g]), 0), dec(med([r['spacing'] for r in g]), 2) + '%',
                     '×' + dec(med([r['size'] for r in g]), 1), dec(med([r['basket'] for r in g]), 0) + '%', dec(med([r['tp'] for r in g]), 0) + '%',
                     dec(med([r['lev'] for r in g]), 0) + 'x', ', '.join(r['name'] for r in g[:3])])
var_card = card("Cùng vào thêm khi giá ngược, khác thông số", "14 lead OKX: bước giá, số tầng, size tầng sau, cách chốt, đòn bẩy",
                table(["Biến thể", "Bot", "Tầng tối đa", "Bước giá", "Size tầng sau", "Đóng cả rổ", "Chốt lời", "Đòn bẩy", "Ví dụ"], var_rows, right=(1, 2, 3, 4, 5, 6, 7)) +
                '<p class="note">Trung vị mỗi nhóm. Bước giá: giá tầng mới xấu hơn tầng trước bao nhiêu. Size tầng sau: ký quỹ tầng mới / tầng trước. Đóng cả rổ: tầng mới đóng cùng lúc tầng trước (±1 phút). Chốt lời: lãi trung vị trên ký quỹ của lệnh thắng.</p>',
                ' data-bt="dca-var"')

b_rows = []
for v, desc in [("Gồng lỗ sâu", "≥ 30% lệnh thắng từng lỗ ≥ 50% ký quỹ"), ("Vào–ra dứt khoát", "Ít khi để giá đi ngược sâu"), ("Chưa đủ dữ liệu", "< 8 lệnh giữ ≥ 8 giờ")]:
    g = [r for r in bnb_v if r['variant'] == v]
    if g: b_rows.append([f"<b>{v}</b><div class=\"note\">{desc}</div>", str(len(g)), dec(med([r['deep_win'] for r in g]), 0) + '%', dec(med([r['mae_med'] for r in g]), 1) + '%',
                         dec(med([r['win'] for r in g]), 0) + '%', dec(med([r['lev'] for r in g]), 0) + 'x', ', '.join(r['name'] for r in g[:3])])
bnb_card = card("14 lead Binance: đo gián tiếp", "Binance gộp tầng, nên đo giá đi ngược bao xa trước khi lệnh về lãi",
                table(["Kiểu", "Bot", "Thắng từng lỗ sâu", "Giá đi ngược", "Thắng", "Đòn bẩy", "Ví dụ"], b_rows, right=(1, 2, 3, 4, 5)) +
                '<p class="note">Chỉ tính lệnh giữ ≥ 8 giờ (nến 4 giờ). "Giá đi ngược": trung vị khoảng giá chạy ngược giá vốn trong lúc giữ lệnh.</p>',
                ' data-bt="dca-bnb"')

strength = lambda r: '' if r is None else 'mạnh' if abs(r) >= .5 else 'vừa' if abs(r) >= .3 else 'yếu'
tr_rows = [[t['ex'], f"{t['a']} ↔ {t['b']}", f'<b>{sgn(t["rho"])}</b>', strength(t['rho']), t['mean']] for t in DV['traits']]
tr_card = card("Tương quan giữa các đặc điểm", "Hệ số Spearman giữa các bot top",
               table(["Mẫu", "Cặp đặc điểm", "Hệ số", "Độ mạnh", "Nghĩa là"], tr_rows, right=(2,)) +
               '<p class="note">Mẫu nhỏ (13–28 bot): xem như xu hướng, chưa phải quy luật. Đuôi lỗ = lệnh lỗ lớn nhất / lệnh lỗ trung vị.</p>',
               ' data-bt="dca-tr"')

co_tbl = table(["Chỉ số", "OKX", "Binance"], [
    ["Tương quan lợi nhuận giữa 2 bot (trung vị)", sgn(CO['OKX']['med']), sgn(CO['Binance']['med'])],
    ["Cặp bot cùng lên xuống mạnh (≥ 0,5)", f"{CO['OKX']['hi']}%", f"{CO['Binance']['hi']}%"],
    ["Cặp bot đi ngược nhau", f"{CO['OKX']['neg']}%", f"{CO['Binance']['neg']}%"],
    ["Tương quan với BTC (trung vị)", sgn(CO['OKX']['btc_med']), sgn(CO['Binance']['btc_med'])],
    ["Bot bám BTC mạnh (|hệ số| ≥ 0,5)", f"{CO['OKX']['btc_hi']}/14", f"{CO['Binance']['btc_hi']}/14"],
    ["Kỳ đo", f"{CO['OKX']['points']} kỳ 5 ngày", f"{CO['Binance']['points']} ngày"],
], right=(1, 2))
top_pairs = ''.join(f'<li><b>{a}</b> ↔ <b>{b}</b>: {sgn(c)}</li>' for ex in ('OKX', 'Binance') for c, a, b in CO[ex]['top'][:2])
co_card = card("Các bot top có cùng lên xuống không?", "Tương quan lợi nhuận theo kỳ, từ đường vốn công bố", co_tbl +
               f'<div><div class="eyebrow" style="margin-bottom:6px">Cặp đi cùng nhau nhất</div><ul class="clean">{top_pairs}</ul></div>',
               ' data-bt="dca-co"')
dca_kpis = f'''<div class="kpis" data-bt="dca-kpi">
{kpi("Khi giá đi ngược", f"{d_avg['n']}/{MS['n']}", "vào thêm hoặc gồng, không cắt")}
{kpi("Tỷ lệ thắng ≥ 70%", f"{d_win['n']}/{MS['n']}", "bot trade")}
{kpi("Lối đánh phổ biến nhất", f"{top_arch['n']}/{MS['n']}", top_arch['name'].lower())}
{kpi("Cùng lên xuống", sgn(CO['OKX']['med']), "tương quan lợi nhuận trung vị giữa 2 bot")}
</div>'''
dca_verdict = f'''<div class="verdict" data-bt="dca-verdict"><span class="eyebrow">Nhận định</span>
<div class="t">Chung một nửa tư duy: gần như cùng cách xử lý lệnh lỗ, nhưng khác cách chọn điểm vào.</div>
<p>Giống nhau: {d_avg['n']}/{MS['n']} bot không cắt lỗ khi giá đi ngược mà vào thêm hoặc gồng, nhờ đó {d_win['n']}/{MS['n']} bot thắng ≥ 70%. Khác nhau: chiều đánh, lúc vào lệnh, regime kiếm tiền, đòn bẩy. Có 4 lối đánh, lối bắt hồi, bình quân giá chiếm {top_arch['n']}/{MS['n']}. Các bot cũng ít khi lãi lỗ cùng lúc (tương quan trung vị {sgn(CO['OKX']['med'])}) vì đánh mã và thời điểm khác nhau. Rủi ro chung nằm ở cách xử lý lệnh lỗ, nên chấm rủi ro phải bắt đầu từ đó rồi mới đến regime.</p></div>'''

# per-bot strategy sketch for the detail rows
RV_ = {"up": "xu hướng tăng", "down": "xu hướng giảm", "range": "đi ngang"}
size_txt = lambda x: 'size tầng sau bằng tầng trước' if 0.9 <= x <= 1.1 else f'tầng sau to gấp {dec(x, 1)} lần tầng trước' if x > 1.1 else f'tầng sau nhỏ hơn (×{dec(x, 1)})'
def sketch(o):
    v = VB.get(o['name']); p = (o['metrics'] or {}).get('p')
    if not v or not p: return None
    syms = ', '.join(s for s, _ in p['top_syms'][:3]); side = 'chủ yếu long' if p['long_pct'] >= 65 else 'chủ yếu short' if p['long_pct'] <= 35 else 'hai chiều'
    best = max(p['reg_pnl'], key=lambda k: p['reg_pnl'][k]) if p['reg_pnl'] else None
    worst = 'xu hướng giảm kéo dài' if p['long_pct'] >= 65 else 'xu hướng tăng kéo dài' if p['long_pct'] <= 35 else 'xu hướng mạnh một chiều'
    if v['ex'] == 'OKX':
        if v['variant'] == 'Nhồi theo lãi':
            core = f"vào thêm khi lệnh đang lãi (chỉ {v['down']}% tầng ở giá xấu hơn), tối đa {v['stack']} tầng"
        else:
            core = (f"khi giá đi ngược, vào thêm mỗi ~{dec(v['spacing'], 2)}%, {size_txt(v['size'])}, tối đa {v['stack']} tầng; "
                    f"{v['basket']}% tầng đóng cùng lúc tầng trước (chốt cả rổ)")
        s = f"{v['variant']}: {syms}, {side}, {dec(p['lev_med'], 0)}x; {core}; chốt lời trung vị {dec(v['tp'], 0)}% ký quỹ."
    else:
        core = (f"{v['deep_win']}% lệnh thắng từng lỗ ≥ 50% ký quỹ trước khi về lãi (gồng lỗ hoặc bình quân giá)" if v['variant'] == 'Gồng lỗ sâu'
                else "ít khi để giá đi ngược sâu, vào ra dứt khoát" if v['variant'] == 'Vào–ra dứt khoát' else "ít lệnh giữ lâu, chưa đủ để đo")
        s = f"{v['variant']}: {syms}, {side}, {dec(p['lev_med'], 0)}x; {core}; chốt lời trung vị {dec(v['tp'], 0)}% ký quỹ."
    if best: s += f" Ăn nhiều nhất khi {RV_[best]}; nguy hiểm khi {worst}."
    return f"Lối {MS['of'][o['name']].lower()} · " + s

hidden = [r for r in R if 'Lỗ treo lớn (vị thế đang mở)' in r['tags']]
hidden_tbl = table(["Lead OKX", "Thắng", "Lỗ chưa chốt"],
                   [[f"<b>{r['name']}</b>", f"{r['p']['win']}%", f'<span style="color:var(--bad)">{fmt(r["open"]["upl"])}</span>'] for r in sorted(hidden, key=lambda r: r['open']['upl'])],
                   right=(1, 2))
s6 = f'''<section class="sec" id="s6" hidden="">
{head(6, "Top bot", "50 bot đang ra tiền", f"{grp_cnt['Trade']} trade · {grp_cnt['Bot grid/DCA']} grid/DCA · {grp_cnt['Signal']} signal · {grp_cnt['Alpha/Agent']} alpha. Bấm vào một bot để xem cách chơi, vì sao hot, hướng đi, regime và rủi ro.")}
<div class="kpis">
{kpi("Đánh ngược đà", f"{n_counter}/50", "lead")}
{kpi("Bình quân giá xuống", f"{DCA['n_down']}/26", "lead OKX")}
{kpi("Lỗ treo", f"{A['okx_open_neg']}/26", f"lead OKX, {fmt(A['okx_open_upl'])} USDT")}
{kpi("Lệnh TradFi", f"{A['cls'].get('tradfi', 0)}%", "cổ phiếu, hàng hoá")}
</div>
{cov_card}
<div class="card stack" data-bt="bb-okx"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="bb-okx"></tbody></table></div></div>
<div class="card stack" data-bt="bb-bnb"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="bb-bnb"></tbody></table></div></div>
<div class="card stack" data-bt="bb-bot"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="bb-bot"></tbody></table></div></div>
<div class="card stack" data-bt="bb-sig"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="bb-sig"></tbody></table></div></div>
<div class="card stack" data-bt="bb-alpha"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="bb-alpha"></tbody></table></div></div>
{grid2(card("Lối chơi của 50 lead", "Thắng nhiều lần nhỏ, thua một lần lớn", '<div class="hbar" id="chart-style"></div>'),
       card("Lỗ treo bảng xếp hạng không cho thấy", "Vị thế đang mở, OKX", hidden_tbl))}
{dca_kpis}
{dims_card}
{arch_card}
{var_card}
{bnb_card}
{tr_card}
{co_card}
{dca_verdict}
</section>'''

# ================================================================== 7. TÂM LÝ NGƯỜI DÙNG
corr = table(["Số người copy đi cùng", "OKX", "Binance"], [
    ["AUM", pct(PC['OKX']['AUM']['copiers']), pct(PC['Binance']['AUM']['copiers'])],
    ["Tỷ lệ thắng", pct(PC['OKX']['Tỷ lệ thắng (lệnh)']['copiers']), pct(PC['Binance']['Tỷ lệ thắng (lệnh)']['copiers'])],
    ["MDD", "—", pct(PC['Binance']['MDD công bố']['copiers'])],
    ["ROI", pct(PC['OKX']['ROI công bố']['copiers']), pct(PC['Binance']['ROI công bố']['copiers'])],
], right=(1, 2))
why = table(["Nơi", "Họ chọn theo"], [
    ["<b>OKX copy-trade</b>", "Đám đông: AUM lớn thì theo"],
    ["<b>Binance copy-trade</b>", "Tỷ lệ thắng cao, MDD thấp"],
    ["<b>Kênh tín hiệu</b>", "Thương hiệu, không theo hiệu suất"],
    ["<b>OKX.AI</b>", "Phương pháp quen, giá rẻ (TradeDesk 92% lượt dùng)"],
])
moments = table(["Khi nào", "Họ trả tiền cho"], [
    ["Trước khi copy", "Chọn bot đáng tin"],
    ["Đang copy", "Cảnh báo khi bot xấu đi"],
    ["Sắp lỗ lớn", "Cắt kịp thời"],
    ["Vừa lỗ", "Hiểu vì sao"],
])
s7 = f'''<section class="sec" id="s7" hidden="">
{head(7, "Tâm lý người dùng", "Người dùng mua thứ kiếm tiền hộ mình và chọn theo đám đông", "Dựa trên số người copy và lượt dùng thật.")}
{grid2(card("Họ chọn bot theo gì", "", why), card("Tương quan với số người copy", "Hệ số Spearman, mẫu 24–26 lead mỗi sàn", corr))}
{grid2(card("Khi nào họ trả tiền cho rủi ro", "Chỉ khi gắn vào thứ họ đang dùng", moments),
       '<div class="verdict"><span class="eyebrow">Nhận định</span><p>Bảng xếp hạng hiển thị AUM, tỷ lệ thắng, MDD, nhưng không hiển thị lỗ treo và đuôi lỗ. Đây là khoảng trống thông tin lớn nhất.</p></div>')}
</section>'''

# ================================================================== 8. HƯỚNG ĐI (4 NGÁCH)
def niche(title, pill, now, opp, risk):
    li = lambda xs: '<ul class="clean">' + ''.join(f'<li>{x}</li>' for x in xs) + '</ul>'
    return f'''<div class="card stack"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h3>{title}</h3>{pill}</div>
<div><div class="eyebrow">Hiện tại</div>{li(now)}</div><div><div class="eyebrow">Cơ hội</div>{li(opp)}</div><div><div class="eyebrow">Rủi ro</div>{li(risk)}</div></div>'''

n_risk = niche("A · Risk đơn thuần", '<span class="pill warn">Cầu thấp</span>',
               ["25 agent, 27 lượt dùng trên OKX.AI" + S(1), "Chưa ai chẩn đoán vì sao bot lỗ" + S(79)],
               [f"Lỗ treo {fmt(A['okx_open_upl'])} USDT không ai hiển thị", "Gắn cảnh báo vào bot người dùng đang copy"],
               ["Người dùng chỉ quan tâm sau khi lỗ", "Báo động nhầm làm mất niềm tin"])
n_alpha = niche("B · Alpha", '<span class="pill good">Bán qua terminal, API</span>',
                ["GMGN (smart money) $42,55M/30 ngày" + S(12), "Dữ liệu thô gần như miễn phí" + S(53)],
                ["Feed regime cho bot và agent: chưa ai bán", "TradFi và châu Á còn ít phân tích"],
                ["Giá bị ép", "Alpha mất hiệu lực khi đông người dùng"])
n_signal = niche("C · Signal", '<span class="pill good">Nhiều người dùng nhất</span>',
                 ["6 kênh top: 86.375 người theo, AUM chỉ $258K" + S(58), "Thắng thực của người theo trung vị 51%" + S(58)],
                 ["Không cần tự bỏ vốn; nhận 10–30% lợi nhuận", "Tín hiệu có kết quả thực và biết tắt theo regime"],
                 ["Ít tiền mỗi người theo (~$3)", "Uy tín sụp sau chuỗi lỗ"])
n_trade = niche("D · Trade", '<span class="pill blue">Tiền lớn, cần vốn</span>',
                ["Bot top OKX: $3,05M tài sản theo, chia 30%" + S(57), "Bot grid/DCA đã miễn phí khắp nơi" + S(79)],
                ["Bot tự đổi tham số theo regime: chưa ai làm" + S(79, 84), "TradFi perpetual đang tăng" + S(86)],
                ["Mất vốn, drawdown thật", "Cạnh tranh với công cụ miễn phí của sàn"])
compare = table(["", "Risk", "Alpha", "Signal", "Trade"], [
    ["Cầu", '<span class="pill bad">Thấp</span>', '<span class="pill good">Có</span>', '<span class="pill good">Cao nhất</span>', '<span class="pill good">Cao</span>'],
    ["Tiền mỗi người dùng", "—", '<span class="pill warn">Vừa</span>', '<span class="pill bad">Rất thấp</span>', '<span class="pill good">Cao</span>'],
    ["Cạnh tranh", '<span class="pill good">Ít</span>', '<span class="pill warn">Nhiều</span>', '<span class="pill warn">Nhiều</span>', '<span class="pill bad">Rất nhiều</span>'],
    ["Cần tự bỏ vốn", '<span class="pill good">Không</span>', '<span class="pill good">Không</span>', '<span class="pill good">Không</span>', '<span class="pill bad">Có</span>'],
    ["Hợp đội nhỏ không tự trade", '<span class="pill good">Có</span>', '<span class="pill good">Có</span>', '<span class="pill good">Có</span>', '<span class="pill bad">Không</span>'],
])
s8 = f'''<section class="sec" id="s8" hidden="">
{head(8, "Hướng đi", "Bốn ngách: risk, alpha, signal, trade", "So sánh nhanh, rồi chi tiết từng ngách.")}
{card("So sánh", "", compare)}
<div class="grid2">{n_risk}{n_alpha}</div>
<div class="grid2">{n_signal}{n_trade}</div>
<div class="verdict"><span class="eyebrow">Nhận định</span><div class="t">Đội không tự trade nên kết hợp risk, alpha và signal: tín hiệu và xếp hạng bot có ý thức regime, kèm cảnh báo lỗ treo.</div><p>Chưa sàn nào làm điều này.{S(79)}</p></div>
</section>'''

# ================================================================== APPENDIX
src_sec = f'''<section class="sec" id="src" hidden="">
{head("PL", "Phụ lục", "Phương pháp và nguồn", "Truy cập 28–29/09/2026.")}
{card("Phương pháp", "", '<ul class="clean">' + ''.join(f'<li>{x}</li>' for x in [
    "Chợ agent: chụp 146 agent online OKX.AI; lượt bán là giới hạn trên.",
    "Bot: API copy-trading OKX, trang lead Binance, OKX Bot/Signal Marketplace, Binance Trading Bots, DefiLlama.",
    "Regime: nến 4 giờ đã đóng trước lúc vào lệnh (EMA50/200, ADX, ATR); không dùng dữ liệu tương lai.",
    "Giới hạn: suy luận từ lệnh, không thấy luật của bot; tối đa 1.000 lệnh mỗi lead; tương quan dùng mẫu nhỏ."]) + '</ul>')}
{card("Nguồn", "", '<div class="tbl-wrap"><table><thead><tr><th>#</th><th>Nội dung</th><th>Nguồn</th><th>Ngày</th><th>Tin cậy</th></tr></thead><tbody id="src-body"></tbody></table></div>')}
</section>'''

sections = [s1, s2, s3, s4, s5, s6, s7, s8]
nav_items = [("s1", "Tóm tắt"), ("s2", "Quy mô"), ("s3", "Market"), ("s4", "Xu hướng"), ("s5", "Flow tổng thể"),
             ("s6", "Top bot"), ("s7", "Tâm lý người dùng"), ("s8", "Hướng đi")]
nav = ''.join(f'<button data-s="{sid}"><span class="n">{i if sid != "src" else "PL"}</span>{lbl}</button>' for i, (sid, lbl) in enumerate(nav_items, 1))

bots_js = [dict(rank=o['rank'], grp=o['group'], name=o['name'], where=o['where'], url=o['url'], money=o['money'], users=o['users'], style=o['style'],
                how=o['how'], why=o['why'], trend=o['trend'], fit=o['fit'], tone=o['fit_tone'], risks=o['risks'],
                p=(o['metrics'] or {}).get('p'), open=(o['metrics'] or {}).get('open'), plan=sketch(o), v=VB.get(o['name'])) for o in F50]
style_rows = sorted(style_counts.items(), key=lambda x: -x[1])
script = '''<script>
const BOTS = ''' + json.dumps(bots_js, ensure_ascii=False) + ''';
const TOP = ''' + json.dumps([dict(niche=t['niche'], tier=t['tier']) for t in TOP], ensure_ascii=False) + ''';
const STYLES = ''' + json.dumps(style_rows, ensure_ascii=False) + ''';
const SOURCES = ''' + json.dumps(SOURCES, ensure_ascii=False) + ''';
const NICHES = {SIG:{n:"Tín hiệu & dữ liệu",c:"var(--n-sig)"},TRADE:{n:"Giao dịch & copy-trade",c:"var(--n-trade)"},RISK:{n:"Rủi ro & bảo mật",c:"var(--n-risk)"},
  INFRA:{n:"Hạ tầng thanh toán & tin cậy",c:"var(--n-infra)"},DEFI:{n:"DeFi yield / LP",c:"var(--n-defi)"},RWA:{n:"Cổ phiếu token hoá",c:"var(--n-rwa)"},
  PRED:{n:"Thị trường dự đoán",c:"var(--n-pred)"},TRAD:{n:"Fintech truyền thống",c:"var(--n-trad)"},OTHER:{n:"Khác",c:"var(--n-other)"}};
''' + HELPERS + '''
hbar(document.getElementById("chart-money"), ''' + json.dumps([dict(l=l, v=v) for l, v in money_rows] + [dict(l="OKX.AI · toàn chợ task", v=9653, hi=True, tip="$9.653 cộng dồn từ 07/2026")], ensure_ascii=False) + ''', 40000000, usd);
(function(){
  const cn={}, ct={"Rất hot":0,"Hot":0,"Ấm":0,"Lạnh":0}; TOP.forEach(t=>{cn[t.niche]=(cn[t.niche]||0)+1; ct[t.tier]++;});
  const ord=Object.keys(cn).sort((a,b)=>cn[b]-cn[a]);
  hbar(document.getElementById("chart-tn"), ord.map(k=>({l:NICHES[k].n,v:cn[k],c:NICHES[k].c})), Math.max(...Object.values(cn)), v=>v+" agent");
  const tc={"Rất hot":"var(--n-trade)","Hot":"var(--n-pred)","Ấm":"var(--n-sig)","Lạnh":"var(--n-other)"};
  document.getElementById("chart-tier")&&hbar(document.getElementById("chart-tier"), Object.keys(ct).map(k=>({l:k,v:ct[k],c:tc[k]})), Math.max(...Object.values(ct)), v=>v+" agent");
  hbar(document.getElementById("chart-style"), STYLES.map(([k,v])=>({l:k,v})), Math.max(...STYLES.map(s=>s[1])), v=>v+" lead");
})();
(function(){
  const tone={good:"good",warn:"warn",bad:"bad",neu:"neu"};
  const RV={up:"Tăng",down:"Giảm",range:"Đi ngang"};
  const money=v=>(v<0?"−":"")+"$"+Math.abs(v).toLocaleString("vi-VN");
  const dc=(x,d)=>x==null?"—":x.toFixed(d).replace(".",",");
  const DATA={"Trade":"","Bot grid/DCA":"Chỉ có số công bố và loại bot, không có list lệnh.","Signal":"Chỉ có số công bố của kênh (APY backtest, người theo), không có list lệnh.","Alpha/Agent":"Là nền tảng: có doanh thu, không có list lệnh."};
  function metrics(b){
    const p=b.p; if(!p) return "";
    const regs=["up","range","down"].filter(k=>p.reg_share[k]!==undefined);
    const hold=h=>h<1?Math.round(h*60)+" phút":h<48?h.toFixed(1).replace(".",",")+" giờ":(h/24).toFixed(1).replace(".",",")+" ngày";
    return `<div class="stack"><div class="tbl-wrap"><table><thead><tr><th>Regime lúc vào</th><th class="r">% lệnh</th><th class="r">Thắng</th><th class="r">PnL</th></tr></thead><tbody>${regs.map(k=>`<tr><td>${RV[k]}</td><td class="r num">${p.reg_share[k]}%</td><td class="r num">${p.reg_win[k]??"—"}%</td><td class="r num">${money(p.reg_pnl[k]||0)}</td></tr>`).join("")}</tbody></table></div>
      <div class="tbl-wrap"><table><tbody>
      <tr><td>Mã chính</td><td class="r">${p.top_syms.map(([s,c])=>s+" "+c+"%").join(", ")}</td></tr>
      <tr><td>Lệnh · thắng · đòn bẩy</td><td class="r num">${p.n.toLocaleString("vi-VN")} · ${p.win}% · ${String(p.lev_med).replace(".",",")}x</td></tr>
      <tr><td>Giữ lệnh · long</td><td class="r num">${hold(p.hold_med)} · ${p.long_pct}%</td></tr>
      <tr><td>Vào theo đà · thuận xu hướng</td><td class="r num">${p.momentum??"—"}% · ${p.aligned??"—"}%</td></tr>
      ${b.v&&b.v.ex==="OKX"?`<tr><td>Mở thêm · ở giá xấu hơn</td><td class="r num">${b.v.adds}% · ${b.v.down??"—"}%</td></tr>
      <tr><td>Tầng tối đa · bước giá · size tầng sau</td><td class="r num">${b.v.stack} · ${dc(b.v.spacing,2)}% · ×${dc(b.v.size,1)}</td></tr>
      <tr><td>Đóng cả rổ · chốt lời trung vị</td><td class="r num">${b.v.basket??"—"}% · ${dc(b.v.tp,0)}%</td></tr>`:""}
      ${b.v&&b.v.ex==="Binance"?`<tr><td>Thắng từng lỗ ≥ 50% ký quỹ</td><td class="r num">${b.v.deep_win??"—"}%</td></tr>
      <tr><td>Giá đi ngược trung vị · chốt lời trung vị</td><td class="r num">${dc(b.v.mae_med,1)}% · ${dc(b.v.tp,0)}%</td></tr>`:""}
      ${b.v&&b.v.btc!=null?`<tr><td>Tương quan với BTC</td><td class="r num">${dc(b.v.btc,2)}</td></tr>`:""}
      ${b.open?`<tr><td>Vị thế đang mở · lỗ/lãi chưa chốt</td><td class="r num" style="color:${b.open.upl<0?"var(--bad)":"var(--good)"}">${b.open.n} · ${money(b.open.upl)}</td></tr>`:""}
      </tbody></table></div></div>`;
  }
  function detail(b){
    const L=(t,x)=>`<div><div class="eyebrow">${t}</div><p class="prose">${x}</p></div>`;
    return `<div class="grid2" style="padding:6px 2px 10px"><div class="stack">
      ${b.plan?`<div class="verdict" style="padding:12px 14px"><span class="eyebrow">Chiến lược suy ra từ list lệnh</span><p style="margin:4px 0 0">${esc(b.plan)}</p></div>`:""}
      ${L("Cách chơi",esc(b.how))}${L("Vì sao hot",esc(b.why))}${L("Hướng đi",esc(b.trend))}
      ${L("Regime hiện tại",`<span class="pill ${tone[b.tone]}">${esc(b.fit)}</span>`)}
      ${b.risks.length?L("Rủi ro",b.risks.map(r=>`<span class="pill bad" style="margin:0 4px 4px 0">${esc(r)}</span>`).join("")):""}
      ${DATA[b.grp]?`<p class="note"><b>Dữ liệu:</b> ${DATA[b.grp]}</p>`:""}
      <p class="note">${esc(b.where)} · <a href="${esc(b.url)}" target="_blank" rel="noopener">Trang gốc</a></p></div>${metrics(b)||"<div></div>"}</div>`;
  }
  const groups={"bb-okx":b=>b.grp==="Trade"&&b.where.startsWith("OKX"),"bb-bnb":b=>b.grp==="Trade"&&b.where.startsWith("Binance"),
    "bb-bot":b=>b.grp==="Bot grid/DCA","bb-sig":b=>b.grp==="Signal","bb-alpha":b=>b.grp==="Alpha/Agent"};
  Object.entries(groups).forEach(([id,f])=>{
    const el=document.getElementById(id); if(!el) return;
    const rows=BOTS.filter(f);
    el.innerHTML=rows.map((b,i)=>`<tr class="brow" style="cursor:pointer" tabindex="0"><td class="num muted">${i+1}</td>
      <td><b>${esc(b.name)}</b><div class="note">${esc(b.where)}</div></td><td>${esc(b.style)}</td>
      <td class="r num">${esc(b.money)}</td><td class="r num">${esc(b.users)}</td><td><span class="pill ${tone[b.tone]}">${esc(b.fit.split(":")[0])}</span></td></tr>
      <tr class="bdet" hidden><td colspan="6">${detail(b)}</td></tr>`).join("");
    el.querySelectorAll("tr.brow").forEach(tr=>{const t=()=>{tr.nextElementSibling.hidden=!tr.nextElementSibling.hidden;}; tr.addEventListener("click",t); tr.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();t();}});});
  });
})();
const confCls=c=>c.startsWith("cao")?"good":c.startsWith("trung bình")?"blue":"warn";
document.getElementById("src-body")&&(document.getElementById("src-body").innerHTML=SOURCES.map(s=>`<tr id="ref-${s.n}"><td class="num">[${s.n}]</td><td>${esc(s.what)}</td><td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.pub)}</a></td><td class="num muted">${esc(s.date)}</td><td><span class="pill ${confCls(s.conf)}">${esc(s.conf)}</span></td></tr>`).join(""));
show((location.hash||"#s1").slice(1), false);
</script>'''
# sources link -> appendix section id "src"
script = script.replace('show("s9",false)', 'show("src",false)')

body = f'''<header class="topbar"><div class="topbar-in"><div class="brand"><div class="logo">OKX</div><div>
<h1>Thị trường Agent Fintech OKX &amp; Binance</h1><p>Quy mô · market · xu hướng · top bot · tâm lý người dùng · hướng đi · dữ liệu 28–29/09/2026</p></div></div>
<div class="chips"><span class="chip blue">BMAD Deep Recon</span><span class="chip">50 bot giải mã</span></div></div></header>
<div class="wrap"><aside class="side"><div class="side-h"><div class="eyebrow">Báo cáo</div><div>8 mục</div></div>
<nav aria-label="Chuyên mục" class="nav" id="nav">{nav}</nav>
<div class="side-foot"><div><b>Chợ agent:</b> 146 agent OKX.AI</div><div><b>Top bot:</b> 50 (trade, bot, signal, alpha)</div><div><b>Lệnh phân tích:</b> {fmt(A['n_trades'])}</div><div><b>Regime:</b> nến 4H, {bar_time} UTC</div></div></aside>
<main>{''.join(sections)}</main></div><div class="tip" id="tip" role="tooltip"></div>'''

doc = f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Thị trường Agent Fintech OKX</title>
<meta name="description" content="Báo cáo thị trường agent fintech OKX và Binance: quy mô, market, xu hướng theo regime hiện tại, 50 bot top, tâm lý người dùng và ba hướng đi.">
{FONTS}
{CSS.replace('<style>', '<style>' + chr(10) + '[hidden]{display:none!important}', 1)}
</head><body>
{body}
{script}
</body></html>'''
import hashlib, base64
_m = re.search(r'<script>(.*?)</script>', doc, re.S)
_h = base64.b64encode(hashlib.sha256(_m.group(1).encode('utf-8')).digest()).decode()
_csp = ("default-src 'none'; script-src 'sha256-" + _h + "'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
doc = doc.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="' + _csp + '">', 1)
open('/home/ubuntu/norabt/okx-report.html', 'w').write(doc)
refs = sorted(set(int(x) for x in re.findall(r'data-ref="(\d+)"', doc)))
print('written', len(doc), 'refs used', len(refs), 'missing', [r for r in refs if r not in {s['n'] for s in SOURCES}])
