"""Build the restructured 8-section report -> /home/ubuntu/norabt/okx-report.html"""
import json
import re
from collections import Counter

import os

SP = '/tmp/claude-1000/-home-ubuntu-norabt/47a0aee2-9f8b-4307-bd29-550a7e8f13f1/scratchpad/'
BU = SP + 'build/'
RESEARCH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "research.md"))

old = open(BU + 'template.html').read()
CSS = old[old.index('<style>'):old.index('</style>') + 8]
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

S = lambda *ns: ''.join(f'<a class="src" href="#src" data-ref="{n}">[{n}]</a>' for n in ns)
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

# ================================================================== 1. TÓM TẮT
s1 = f'''<section class="sec" id="s1">
{head(1, "Tóm tắt", "Agent fintech trên OKX &amp; Binance: tiền nằm ở đâu, bot top chơi thế nào, nên vào ngách nào",
      "Dữ liệu thực đo 28–29/09/2026 từ OKX.AI, OKX Copy/Bot/Signal Marketplace, Binance Copy Trading và Trading Bots, DefiLlama và 86 nguồn công khai.")}
<div class="kpis">
{kpi("Doanh thu 30 ngày, top 3 app giao dịch", "$92M", "GMGN, fomo, Axiom" + S(12))}
{kpi("Chợ agent OKX.AI", "$9.653", "tổng tiền qua chợ task; 146 agent online" + S(1, 2))}
{kpi("Bot top được giải mã", "50", f"{fmt(A['n_trades'])} lệnh; trade, grid/DCA, signal, alpha")}
{kpi("Regime hiện tại", f"{reg_cnt['range']}/30", f"mã bot top đánh nhiều nhất đang đi ngang; {hv_n} mã biến động cao")}
</div>
<div class="verdict"><span class="eyebrow">Kết luận chính</span>
<div class="t">Tiền đang chảy qua bot giao dịch, copy-trade và tín hiệu, chưa chảy qua chợ agent. Bot top thắng bằng đánh ngược đà và DCA, hợp với thị trường đi ngang hiện tại, nhưng che lỗ treo và dễ vỡ khi thị trường ra xu hướng.</div>
<p>Vì vậy ngách hấp dẫn là lớp <b>tín hiệu và alpha có kiểm chứng</b> và lớp <b>kiểm soát rủi ro gắn vào bot đang chạy</b>. Bán công cụ đo rủi ro đơn thuần hiện gần như không có người mua (Mục 8).</p></div>
{card("Năm phát hiện", "", f"""
<div class="finding"><span class="i">01</span><div><h4>Chợ agent còn rất nhỏ so với bot giao dịch</h4><p>OKX.AI tổng $9.653 từ 07/2026; top 3 app giao dịch thu $92M chỉ trong 30 ngày.{S(2, 12)}</p></div></div>
<div class="finding"><span class="i">02</span><div><h4>Bot top chủ yếu đánh ngược đà và DCA</h4><p>{n_counter}/50 lead đánh ngược đà; {DCA['n_down']}/26 lead OKX bình quân giá xuống.</p></div></div>
<div class="finding"><span class="i">03</span><div><h4>Tỷ lệ thắng đẹp che lỗ treo</h4><p>Thắng trung vị {pct(A['win_med']['OKX'])}–{pct(A['win_med']['Binance'])}%, nhưng {A['okx_open_neg']}/26 lead OKX đang ôm lỗ chưa chốt, tổng {fmt(A['okx_open_upl'])} USDT.</p></div></div>
<div class="finding"><span class="i">04</span><div><h4>Thị trường đang đi ngang: đúng sân của bot top, nhưng có tín hiệu yếu đi</h4><p>{reg_cnt['range']}/30 mã đi ngang, {hv_n} mã biến động cao; BTC {pct(btc['r7'])}% và ETH {pct(eth['r7'])}% trong 7 ngày.</p></div></div>
<div class="finding"><span class="i">05</span><div><h4>Người dùng chọn theo đám đông và tỷ lệ thắng, không theo rủi ro</h4><p>OKX: số người copy đi cùng AUM (hệ số {pct(PC['OKX']['AUM']['copiers'])}); Binance: đi cùng tỷ lệ thắng ({pct(PC['Binance']['Tỷ lệ thắng (lệnh)']['copiers'])}); công cụ rủi ro chỉ có 0,3% lượt dùng trên OKX.AI.{S(1)}</p></div></div>""")}
</section>'''

# ================================================================== 2. QUY MÔ
money_rows = [("GMGN", 42552399), ("fomo Wallet", 31076068), ("Axiom", 18228223), ("Polymarket", 14365000), ("Terminal", 2626204),
              ("Maestro", 1345310), ("Bankr (AI agent)", 1118200), ("Virtuals Protocol", 596920), ("TermiX ('AI Agents')", 227074)]
scale = table(["Thị trường", "Giá trị", "Loại số liệu"], [
    ["<b>OKX.AI</b> · chợ task", "$9,7K", "Cộng dồn 07–09/2026" + S(2)],
    ["<b>Olas Mech</b> · chợ agent", "$110K", "Cộng dồn, 12M request" + S(17)],
    ["<b>x402</b> · thanh toán máy-máy", "$41–50M", "Cộng dồn từ 2025; ~50% giao dịch ảo" + S(14, 15)],
    ["<b>Bot giao dịch</b> top 3", "$92M", "Doanh thu 30 ngày" + S(12)],
    ["<b>Virtuals ACP</b> · aGDP", "$479M", "Có trợ cấp tới $1M/tháng" + S(18, 19)],
    ["<b>Ramp</b> · agent tài chính doanh nghiệp", "$1,5B", "Doanh thu annualized" + S(21)],
    ["<b>Agentic commerce Mỹ 2030</b>", "$190–385B", "Dự báo, Morgan Stanley" + S(36)],
    ["<b>Agentic commerce toàn cầu 2030</b>", "$3–5T", "Dự báo, McKinsey" + S(35)],
], right=(1,))
layers = table(["Lớp", "Tiền đang chảy"], [
    ["App/bot giao dịch", '<span class="pill good">$92M/30 ngày</span>'],
    ["Copy-trade trên sàn", '<span class="pill good">Chia 10–30% lợi nhuận</span>'],
    ["Thị trường dự đoán", '<span class="pill good">$14,4M/30 ngày</span>'],
    ["Bot có sẵn trên sàn", '<span class="pill neu">Sàn thu phí; 1,7M+ bot OKX</span>'],
    ["Thanh toán x402", '<span class="pill warn">$41–50M cộng dồn</span>'],
    ["Chợ agent (OKX.AI, ACP, Olas)", '<span class="pill bad">Rất ít</span>'],
])
s2 = f'''<section class="sec" id="s2" hidden="">
{head(2, "Quy mô", "Tiền thật nằm ở giao dịch; chợ agent còn ở mức nghìn USD", "Từ vài nghìn USD của chợ agent tới hàng tỷ USD của agent tài chính doanh nghiệp.")}
{grid2(card("Doanh thu 30 ngày", "DefiLlama, 30 ngày đến 27/09/2026. Cột cam là toàn bộ chợ task OKX.AI (cộng dồn)",
            '<div class="hbar" id="chart-money"></div><div class="axis"><span></span><span class="ticks"><span>$0</span><span>$10M</span><span>$20M</span><span>$30M</span><span>$40M</span></span><span></span></div>'),
       card("Các lớp thị trường", "", layers))}
{card("Thang quy mô", "Khác đơn vị (cộng dồn, theo năm, dự báo); chỉ để thấy độ lớn tương đối", scale)}
</section>'''

# ================================================================== 3. MARKET
mk_map = table(["Lớp", "OKX", "Binance"], [
    ["<b>Người dùng</b>", "150M+", "300M+"],
    ["<b>Chợ agent bên thứ ba</b>", "OKX.AI: 146 agent online, $9.653" + S(1, 2), "Không có; Skills Hub chỉ có skill chính thức" + S(63)],
    ["<b>Công cụ cho agent</b>", "Agent Trade Kit, OnchainOS (miễn phí)" + S(9), "Agent OS, AI Pro $9,99–29,99" + S(62, 64)],
    ["<b>Bot có sẵn</b>", "691K grid spot, 648K grid futures, 431K DCA" + S(57), "85K + 41K bot đang chạy ($284M)" + S(60)],
    ["<b>Copy-trade / tín hiệu</b>", "600 bot marketplace; 31 kênh tín hiệu" + S(57, 58), "Lead top lãi $1,21M/30 ngày" + S(59)],
    ["<b>Người tạo kiếm tiền</b>", "Chia 1–30% lợi nhuận; thuê bao OKX.AI; x402", "Chia ≤30% lợi nhuận + 10% hoa hồng; Binance Link 30–50%" + S(61)],
    ["<b>Tham số AI cho bot grid</b>", "Có, đặt một lần lúc tạo bot" + S(80), "Có, đặt một lần lúc tạo bot" + S(79)],
    ["<b>On-chain</b>", "X Layer: x402 không tốn gas", "BNB Chain: GMGN $10,65M/30 ngày; AI agent có doanh thu duy nhất là TermiX" + S(66)],
])
s3 = f'''<section class="sec" id="s3" hidden="">
{head(3, "Market", "OKX &amp; Binance: hạ tầng agent đã có, người dùng vẫn ở copy-trade và bot", "So sánh hai sàn theo từng lớp; số chụp trực tiếp từ trang và API công khai.")}
<div class="kpis">
{kpi("Bot marketplace top OKX", "10.055", "người copy · $3,05M tài sản theo · chia 30%" + S(57))}
{kpi("Kênh tín hiệu lớn nhất OKX", "50.002", "người theo" + S(58))}
{kpi("Lead top Binance", "$1,21M", "PnL 30 ngày" + S(59))}
{kpi("Hợp đồng TradFi trên Binance", "206", "cổ phiếu, hàng hoá token hoá" + S(86))}
</div>
{card("Bản đồ hai sàn", "", mk_map)}
</section>'''

# ================================================================== 4. XU HƯỚNG
rn_rows = [[f"<b>{o['sym'].replace('USDT', '')}</b>", f'<span class="pill {PILL[o["reg"]]}">{REG[o["reg"]]}</span>' + (' <span class="pill warn">Biến động cao</span>' if o['hv'] else ''),
            pct(o['r24']) + "%", pct(o['r7']) + "%" if o['r7'] is not None else "—", fmt(o['trades'])] for o in NOW]
style_fit = table(["Lối chơi", "Hợp khi", "Lúc này"], [
    ["<b>Ngược đà, DCA, grid</b>", "Đi ngang, biến động vừa", '<span class="pill good">Hợp</span> nhưng cảnh giác với mã biến động cao'],
    ["<b>Theo xu hướng</b>", "Xu hướng rõ", '<span class="pill warn">Kém hợp</span>: dễ bị quét hai đầu'],
    ["<b>Scalper</b>", "Biến động cao, thanh khoản tốt", '<span class="pill neu">Tuỳ mã</span>'],
    ["<b>Nghiêng long</b> (OKX trung vị 73,5%)", "Thị trường tăng", '<span class="pill warn">Rủi ro</span>: nhiều mã đỏ 7 ngày'],
])
scen = table(["Nếu thị trường chuyển sang", "Bot bị ảnh hưởng nhất", "Tín hiệu báo trước"], [
    ["<b>Xu hướng giảm</b>", "DCA long, grid không có dừng lỗ; lead OKX nghiêng long", "Nén biến động rồi bung xuống; funding âm; OI giảm"],
    ["<b>Xu hướng tăng mạnh</b>", "DCA short (các bot ETH short top OKX)", "OI tăng + funding dương cực đoan; lực mua chủ động lệch"],
    ["<b>Biến động cực cao</b>", "Bot đòn bẩy ≥ 20x, lưới hẹp", "ATR tăng vọt; sổ lệnh mỏng; lịch sự kiện (CPI, FOMC)"],
])
heat = '<div class="stack">' + ''.join(f'<div><span class="pill {c}">{t}</span> {x}</div>' for c, t, x in [
    ("good", "Nóng", "<b>Copy-trade bot và tín hiệu</b>: 10K–50K người theo mỗi bot/kênh top" + S(57, 58)),
    ("good", "Nóng", "<b>TradFi token hoá</b>: ~20% lệnh của bot top; 206 hợp đồng trên Binance" + S(86)),
    ("good", "Nóng", "<b>Hạ tầng thanh toán cho agent</b>: Stripe, Mastercard, Visa, Coinbase, OKX" + S(32, 33)),
    ("good", "Nóng", "<b>Thị trường dự đoán</b>: bot chiếm phần lớn volume" + S(76)),
    ("bad", "Nguội", "<b>Token agent</b>: giảm 70–90%" + S(28)),
    ("bad", "Nguội", "<b>Agent DeFi yield</b>: Giza đã đóng cửa" + S(51)),
    ("bad", "Nguội", "<b>Bot Telegram đời cũ</b>: Photon, Banana Gun sụt mạnh" + S(12)),
]) + '</div>'
expect = table(["Kỳ vọng", "Thực tế"], [
    ["OKX.AI 10.000+ agent" + S(5), "146 online, tổng $9.653"],
    ["BNB Chain 200K+ agent", "1 agent có doanh thu đáng kể" + S(66)],
    ["x402 hàng trăm triệu giao dịch", "$41–50M, ~50% ảo" + S(14)],
    ["AI agent tự trade thay người", "Người dùng vẫn chạy bot grid/DCA cổ điển"],
    ["$3–5T vào 2030" + S(35), "Hôm nay tiền ở app giao dịch"],
])
s4 = f'''<section class="sec" id="s4" hidden="">
{head(4, "Xu hướng", "Regime hiện tại và lối chơi đang hợp thị trường", f"Regime của chính mã giao dịch trên nến 4 giờ đóng lúc {bar_time} UTC: tăng khi giá &gt; EMA50 &gt; EMA200 và ADX ≥ 20, giảm khi ngược lại, còn lại là đi ngang.")}
<div class="kpis">
{kpi("Đi ngang", f"{reg_cnt['range']}/30", "mã bot top đánh nhiều nhất")}
{kpi("Xu hướng tăng / giảm", f"{reg_cnt['up']} / {reg_cnt['down']}", "mã")}
{kpi("Biến động cao", f"{hv_n}/30", "ATR ở nhóm 20% cao nhất 90 ngày")}
{kpi("BTC / ETH, 7 ngày", f"{pct(btc['r7'])} / {pct(eth['r7'])}%", "cả hai đang đi ngang")}
</div>
{card("Lối chơi nào hợp lúc này", f"Trong 50 bot top: {fit_cnt['good']} hợp, {fit_cnt['warn']} cần cảnh giác, {fit_cnt['bad']} rủi ro rõ, {fit_cnt['neu']} không gắn một regime", style_fit)}
{card("Kịch bản khi regime đổi", "Để agent chuẩn bị trước, không phản ứng sau", scen)}
{card("Regime 30 mã bot top đánh nhiều nhất", "Xếp theo số lệnh của 50 bot", table(["Mã", "Regime", "24 giờ", "7 ngày", "Số lệnh bot top"], rn_rows, right=(2, 3, 4)))}
{grid2(card("Nóng lên và nguội đi", "", heat), card("Kỳ vọng và thực tế", "", expect))}
</section>'''

# ================================================================== 5. FLOW TỔNG THỂ (+ 100 agent stats)
niche_heat = table(["Ngách", "Agent OKX.AI", "Lượt dùng", "Tiền thật", "Độ hot"], [
    ["<b>Giao dịch &amp; copy-trade</b>", "13", "2,1%", "$92M/30 ngày (app); chia 10–30% (copy)", '<span class="pill good">Rất hot</span>'],
    ["<b>Tín hiệu &amp; dữ liệu</b>", "38", "93,2%", "Kênh top 50.002 người theo", '<span class="pill good">Rất hot</span>'],
    ["<b>Thị trường dự đoán</b>", "2", "0,2%", "Polymarket $14,4M/30 ngày", '<span class="pill good">Hot</span>'],
    ["<b>Hạ tầng thanh toán &amp; tin cậy</b>", "14", "0,1%", "VC: Catena $30M, Natural $30M", '<span class="pill warn">Ấm (VC)</span>'],
    ["<b>DeFi yield / LP</b>", "4", "4,0%", "Almanak $169/30 ngày; Giza đóng", '<span class="pill bad">Lạnh</span>'],
    ["<b>Rủi ro &amp; bảo mật</b>", "25", "0,3%", "CertiK 0,001 USDT; GoPlus miễn phí", '<span class="pill bad">Lạnh (bán lẻ)</span>'],
    ["<b>Cổ phiếu token hoá</b>", "6", "0%", "Chưa có", '<span class="pill bad">Lạnh</span>'],
], right=(1, 2))
tiers = Counter(t['tier'] for t in TOP); tn = Counter(t['niche'] for t in TOP)
top15 = table(["#", "Agent", "Nơi", "Chỉ số", "Độ hot"], [[str(t['rank']), f"<b>{t['name']}</b>", t['where'], t['metric'], f'<span class="pill blue">{t["score"]} · {t["tier"]}</span>'] for t in TOP[:15]])
flow_pay = '''<div class="swim">
<div class="fnode"><span class="k">1</span><h4>Người mua</h4><p>Trader, người copy, agent khác</p></div>
<div class="fnode"><span class="k">2 · TRẢ TIỀN</span><h4>Phí lệnh · chia lợi nhuận · thuê bao · x402</h4><p>Sàn giữ tiền, trả phần chia cho người tạo</p></div>
<div class="fnode opp"><span class="k">3 · NGƯỜI TẠO</span><h4>Lead, bot, kênh tín hiệu, agent</h4><p>Nhận 10–30% lợi nhuận hoặc phí</p></div>
<div class="fnode"><span class="k">4 · SÀN</span><h4>OKX, Binance</h4><p>Thu phí giao dịch trên mọi lệnh</p></div>
<div class="fnode"><span class="k">5 · ON-CHAIN</span><h4>X Layer, BNB Chain</h4><p>Thanh toán x402, escrow OKX.AI</p></div></div>'''
chain = '''<div class="flow">
<div class="fnode free"><span class="k">1 · DỮ LIỆU</span><h4>Giá, on-chain, funding</h4><p>Gần như miễn phí</p></div>
<div class="fnode opp"><span class="k">2 · ALPHA / TÍN HIỆU</span><h4>Chiến lược</h4><p>Có người trả phí định kỳ</p></div>
<div class="fnode free"><span class="k">3 · QUÉT TOKEN</span><h4>Honeypot, scam</h4><p>CertiK 0,001 USDT; GoPlus miễn phí</p></div>
<div class="fnode opp"><span class="k">4 · KIỂM SOÁT RỦI RO</span><h4>Lỗ treo, cảnh báo regime</h4><p>Chưa ai làm; lỗ treo −1,29M USDT</p></div>
<div class="fnode free"><span class="k">5 · THỰC THI</span><h4>Đặt lệnh, định tuyến</h4><p>Sàn cho miễn phí</p></div>
<div class="fnode free"><span class="k">6 · THANH TOÁN</span><h4>x402, escrow</h4><p>Sàn và mạng thẻ nắm</p></div></div>'''
s5 = f'''<section class="sec" id="s5" hidden="">
{head(5, "Flow tổng thể", "Tiền chạy thế nào, và khâu nào còn chỗ", "Luồng tiền, chuỗi giá trị, và thống kê 100 agent nổi bật nhất.")}
{card("Luồng tiền", "", flow_pay)}
{card("Chuỗi giá trị", "Ô sọc: sàn hoặc đơn vị lớn đã cho miễn phí. Ô xanh: còn chỗ cho đội nhỏ.", chain)}
{grid2(card("100 agent nổi bật: theo ngách", "Điểm hot quy đổi thang log từ doanh thu, người dùng hoặc lượt bán", '<div class="hbar" id="chart-tn"></div>'),
       card("100 agent nổi bật: theo độ hot", f"Rất hot {tiers['Rất hot']} · Hot {tiers['Hot']} · Ấm {tiers['Ấm']} · Lạnh {tiers['Lạnh']}", '<div class="hbar" id="chart-tier"></div>'))}
{card("Độ hot theo ngách", "Cung và cầu đo trên 106 agent fintech OKX.AI; tiền thật từ DefiLlama và các sàn", niche_heat)}
{card("15 agent hot nhất trong 100", "", top15)}
</section>'''

# ================================================================== 6. TOP BOT (50)
hidden = [r for r in R if 'Lỗ treo lớn (vị thế đang mở)' in r['tags']]
hidden_tbl = table(["Lead OKX", "Thắng (đã đóng)", "Lãi đã chốt", "Vị thế mở", "Lỗ chưa chốt"],
                   [[f"<b>{r['name']}</b>", f"{r['p']['win']}%", fmt(r['p']['net']), str(r['open']['n']), f'<span style="color:var(--bad)">{fmt(r["open"]["upl"])}</span>'] for r in sorted(hidden, key=lambda r: r['open']['upl'])],
                   right=(1, 2, 3, 4))
ex_tbl = table(["Chỉ số (trung vị)", "OKX", "Binance"], [
    ["Giữ lệnh", f"{pct(A['hold_med']['OKX'])} giờ", f"{pct(A['hold_med']['Binance'])} giờ"],
    ["Tỷ lệ long", f"{pct(A['long_med']['OKX'])}%", f"{pct(A['long_med']['Binance'])}%"],
    ["Tỷ lệ thắng (lệnh đã đóng)", f"{pct(A['win_med']['OKX'])}%", f"{pct(A['win_med']['Binance'])}%"],
    ["Đòn bẩy", f"{pct(A['lev_med']['OKX'])}x", f"{pct(A['lev_med']['Binance'])}x"],
    ["Lệnh TradFi", f"{EX['OKX']['cls'].get('tradfi', 0)}%", f"{EX['Binance']['cls'].get('tradfi', 0)}%"],
    ["Bình quân giá xuống (DCA)", f"{DCA['n_down']}/26 lead", "Không đo được (sàn gộp vị thế)"],
], right=(1, 2))
reg_perf = table(["Regime lúc vào lệnh", "% lệnh", "Thắng", "Số bot lãi nhất"], [
    [REG[k], f"{A['reg_share_all'].get(k, 0)}%", f"{A['reg_win_all'].get(k, 0)}%", str(A['best_regime'].get(k, 0))] for k in ("up", "range", "down")], right=(1, 2, 3))
mech = table(["Biểu hiện", "Cơ chế (ngược đà + DCA)"], [
    ["<b>Tỷ lệ thắng rất cao</b>", "Giá hồi một chút là chốt được lệnh có lãi"],
    ["<b>Lỗ treo bị giấu</b>", "Lệnh lỗ không đóng, nằm ở vị thế đang mở"],
    ["<b>Đuôi lỗ cực lớn</b>", "Giá đi một chiều không hồi, các vị thế chồng lên nhau cùng lỗ"],
])
style_counts = Counter(r['style'] for r in R)
s6 = f'''<section class="sec" id="s6" hidden="">
{head(6, "Top bot", "50 bot đang ra tiền: cách chơi, vì sao hot, hướng đi",
      f"Gồm {grp_cnt['Trade']} lead copy-trade, {grp_cnt['Bot grid/DCA']} bot grid/DCA, {grp_cnt['Signal']} kênh tín hiệu và {grp_cnt['Alpha/Agent']} sản phẩm alpha/agent. Lối chơi của lead được suy ra từ {fmt(A['n_trades'])} lệnh đã đóng và regime lúc vào lệnh; đây là suy luận từ hành vi, không phải luật thật của bot.")}
<div class="kpis">
{kpi("Đánh ngược đà", f"{n_counter}/50", f"lead; trung vị {pct(A['momentum_med'])}% lệnh vào cùng chiều 24h")}
{kpi("Bình quân giá xuống", f"{DCA['n_down']}/26", f"lead OKX; chồng tối đa trung vị {pct(DCA['med_stack'])} vị thế")}
{kpi("Lỗ treo (OKX)", f"{A['okx_open_neg']}/26", f"lead; tổng {fmt(A['okx_open_upl'])} USDT")}
{kpi("Lệnh TradFi", f"{A['cls'].get('tradfi', 0)}%", "cổ phiếu, hàng hoá token hoá")}
</div>
<div class="card stack">
<div><h3>Hồ sơ 50 bot</h3><p class="sub">Bấm vào một dòng để xem 5 lớp phân tích: cách chơi, vì sao hot, hướng đi, regime hiện tại, rủi ro</p></div>
<div class="filters"><div class="tabs" role="tablist" id="b-grp"></div><input id="b-q" type="search" placeholder="Tìm tên hoặc mã…" aria-label="Tìm bot"><span class="count" id="b-count"></span></div>
<div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Loại</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime hiện tại</th></tr></thead><tbody id="b-body"></tbody></table></div>
</div>
{grid2(card("Lối chơi của 50 lead copy-trade", "Mỗi lead một lối chơi chính", '<div class="hbar" id="chart-style"></div>'), card("OKX khác Binance", "", ex_tbl))}
{grid2(card("Kiếm tiền trong regime nào", "Giai đoạn khảo sát (chủ yếu 07–09/2026) nghiêng tăng; một phần thành tích có thể do thị trường", reg_perf),
       card("Vì sao thắng nhiều mà vẫn nguy hiểm", "", mech))}
{card("Lỗ treo: điều bảng xếp hạng không cho thấy", "Lead OKX có lỗ chưa chốt lớn so với lãi đã chốt (API vị thế đang mở). Binance không công khai vị thế mở.", hidden_tbl)}
</section>'''

# ================================================================== 7. TÂM LÝ NGƯỜI DÙNG
corr = table(["Chỉ số của lead", "OKX (26)", "Binance (24)"], [
    [k, pct(PC['OKX'][k]['copiers']) if k in PC['OKX'] else "—", pct(PC['Binance'][k]['copiers']) if k in PC['Binance'] else "—"]
    for k in ("AUM", "Tỷ lệ thắng (lệnh)", "MDD công bố", "ROI công bố", "PnL công bố", "Số ngày dẫn lệnh", "Đòn bẩy")], right=(1, 2))
choose = table(["Họ chọn", "Bằng chứng", "Mức"], [
    ["<b>Tín hiệu</b>", "93% lượt dùng fintech OKX.AI; kênh top 50.002 người theo" + S(1, 58), '<span class="pill good">Rất cao</span>'],
    ["<b>Bot tự động</b>", "1,7M+ bot trên OKX; 126K trên Binance" + S(57, 60), '<span class="pill good">Rất cao</span>'],
    ["<b>Copy lead / bot</b>", "Bot top 10.055 người copy; nhiều suất Binance gần kín" + S(57, 59), '<span class="pill good">Cao</span>'],
    ["<b>Công cụ đo rủi ro</b>", "25 agent, 27 lượt dùng" + S(1), '<span class="pill bad">Rất thấp</span>'],
])
why = '<ul class="clean">' + ''.join(f'<li>{x}</li>' for x in [
    f"<b>OKX: theo đám đông.</b> Số người copy đi cùng AUM (hệ số {pct(PC['OKX']['AUM']['copiers'])}), gần như không liên quan tỷ lệ thắng ({pct(PC['OKX']['Tỷ lệ thắng (lệnh)']['copiers'])}). Thấy tiền đông thì theo.",
    f"<b>Binance: theo độ ổn định hiển thị.</b> Người copy đi cùng tỷ lệ thắng ({pct(PC['Binance']['Tỷ lệ thắng (lệnh)']['copiers'])}) và né MDD cao ({pct(PC['Binance']['MDD công bố']['copiers'])}). Lead lãi lớn nhưng hung hăng lại ít người copy ({pct(PC['Binance']['PnL công bố']['copiers'])}).",
    "<b>Tín hiệu: theo thương hiệu, không theo hiệu suất.</b> Kênh đông nhất có APY 30 ngày âm; số người theo ngược chiều APY (−0,83, 6 kênh).",
    "<b>OKX.AI: theo phương pháp quen và giá rẻ.</b> TradeDesk (lý thuyết Chan, 0,1 USDT) chiếm 92% lượt dùng fintech.",
]) + '</ul>'
moments = table(["Khoảnh khắc", "Họ cần", "Sản phẩm chạm được"], [
    ["<b>Trước khi copy</b>", "Chọn bot nào", "Bảng xếp hạng theo rủi ro thật"],
    ["<b>Đang copy</b>", "Không phải canh", "Cảnh báo khi bot xấu đi"],
    ["<b>Sắp lỗ lớn</b>", "Cắt kịp thời", "Đề xuất giảm vốn, dừng copy"],
    ["<b>Vừa lỗ</b>", "Hiểu vì sao", "Chẩn đoán: regime nào, tham số nào"],
])
s7 = f'''<section class="sec" id="s7" hidden="">
{head(7, "Tâm lý người dùng", "Người dùng mua thứ kiếm tiền hộ mình, và chọn theo đám đông", "Dựa trên số người copy, người theo và lượt dùng thật của các bot hot.")}
{grid2(card("Họ chọn gì", "", choose), card("Số người copy đi cùng chỉ số nào", "Hệ số tương quan hạng (Spearman) giữa số người copy và chỉ số của lead; mẫu nhỏ, chỉ là tương quan", corr))}
{grid2(card("Vì sao họ chọn bot đó", "", why), card("Khi nào họ chịu trả tiền cho rủi ro", "Rủi ro chỉ được quan tâm khi đã lỗ, hoặc khi gắn vào thứ họ đang dùng", moments))}
<div class="verdict"><span class="eyebrow">Nhận định</span><p>Chỉ số hiển thị trên bảng xếp hạng (AUM, tỷ lệ thắng, MDD) quyết định lựa chọn, trong khi lỗ treo và đuôi lỗ không được hiển thị. Đây là khoảng cách thông tin lớn nhất của thị trường.</p></div>
</section>'''

# ================================================================== 8. HƯỚNG ĐI (NGÁCH)
def niche_card(title, pill, state, opp, how, risks):
    li = lambda xs: '<ul class="clean">' + ''.join(f'<li>{x}</li>' for x in xs) + '</ul>'
    return f'''<div class="card stack"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h3>{title}</h3>{pill}</div>
<div><div class="eyebrow">Thị trường hiện tại</div>{li(state)}</div>
<div><div class="eyebrow">Cơ hội</div>{li(opp)}</div>
<div><div class="eyebrow">Cách đi</div>{li(how)}</div>
<div><div class="eyebrow">Rủi ro</div>{li(risks)}</div></div>'''

risk_c = niche_card("A · Risk đơn thuần", '<span class="pill warn">Cầu thấp nếu bán lẻ</span>',
    ["25 agent rủi ro trên OKX.AI, tổng 27 lượt dùng; CertiK 0,001 USDT/lượt, GoPlus miễn phí" + S(1, 54),
     "Tham số AI của sàn chỉ đặt một lần lúc tạo bot; chưa ai chẩn đoán vì sao bot lỗ" + S(79)],
    [f"{A['okx_open_neg']}/26 lead OKX đang ôm lỗ chưa chốt ({fmt(A['okx_open_upl'])} USDT) mà bảng xếp hạng không hiển thị",
     f"{DCA['n_down']}/26 lead OKX chạy DCA: cần cảnh báo trước khi thị trường ra xu hướng"],
    ["Gắn vào bot người dùng đang copy: cảnh báo, đề xuất giảm vốn; bán thuê bao",
     "Dùng rủi ro làm động cơ xếp hạng bot, không bán bản báo cáo riêng"],
    ["Người dùng chỉ quan tâm sau khi lỗ", "Điểm rủi ro khó kiểm chứng ngay; báo động nhầm làm mất niềm tin",
     "Phụ thuộc dữ liệu công khai của sàn", "Ranh giới với tư vấn đầu tư"])
alpha_c = niche_card("B · Alpha (nghiên cứu, dữ liệu, insight)", '<span class="pill good">Có người trả qua terminal và API</span>',
    ["GMGN bán alpha smart money kèm công cụ vào lệnh: $42,55M/30 ngày" + S(12),
     "TradeDesk (chỉ báo Chan) chiếm 92% lượt dùng fintech OKX.AI; Nansen x402 $0,01–0,05/lượt" + S(1, 46),
     "Dữ liệu thô rẻ hoặc miễn phí: CoinGecko $0,01/lượt" + S(53)],
    ["Feed regime và nguy cơ chuyển regime cho bot và agent khác: chưa ai bán",
     "TradFi (~20% lệnh bot top) và thị trường châu Á còn ít nguồn phân tích tốt" + S(86),
     "Bán cho người xây bot (B2B) thay vì người dùng lẻ"],
    ["API/MCP trả theo lượt (x402) cho agent; thuê bao cho bản chuyên sâu",
     "Gắn vào công cụ vào lệnh hoặc bảng xếp hạng để người dùng thấy giá trị ngay"],
    ["Giá bị ép vì dữ liệu cơ bản gần như miễn phí", "Alpha mất hiệu lực khi nhiều người dùng",
     "Phụ thuộc dữ liệu công khai của sàn", "Khó chứng minh giá trị nếu không gắn với lệnh"])
signal_c = niche_card("C · Signal (tín hiệu vào lệnh)", '<span class="pill good">Nhiều người dùng nhất, ít tiền mỗi người</span>',
    ["OKX Signal Marketplace: 31 kênh; 6 kênh top có 86.375 người theo nhưng AUM chỉ $258K (~$3/người)" + S(58),
     "Tỷ lệ thắng thực của người theo trung vị 51%; kênh đông nhất có APY 30 ngày âm" + S(58),
     "OKX.AI: 8 gói thuê bao tháng đều là tín hiệu (10–20 USDT); 1M·斯巴达 154 thuê bao, vô địch hackathon" + S(1, 3),
     "Trên OKX có 75.460 signal bot đang chạy" + S(57)],
    ["Người tạo không cần tự bỏ vốn: bot của người theo tự vào lệnh, người tạo nhận 10–30% lợi nhuận hoặc phí tháng",
     "Tín hiệu kèm lịch sử thực và tự tắt khi regime không hợp: khác hẳn kênh chỉ khoe APY backtest",
     "Người theo đang chọn theo thương hiệu, không theo hiệu suất (tương quan −0,83): có chỗ cho kênh minh bạch"],
    ["Phát hành qua OKX Signal Marketplace (chia lợi nhuận), OKX.AI (thuê bao), cộng đồng Telegram",
     "Công khai kết quả thực của người theo, không chỉ backtest"],
    ["Ít tiền mỗi người theo: doanh thu chia lợi nhuận nhỏ nếu không có quy mô",
     "Uy tín sụp nhanh sau một chuỗi lỗ", "Độ trễ và trượt giá khi hàng nghìn người cùng vào lệnh",
     "Ranh giới với tư vấn đầu tư"])
trade_c = niche_card("D · Trade", '<span class="pill blue">Tiền lớn nhất, rủi ro vốn cao nhất</span>',
    ["Bot marketplace OKX top: 10.055 người copy, $3,05M tài sản theo, chia 30%" + S(57),
     "Lead Binance top lãi $1,21M/30 ngày; chia ≤30% lợi nhuận" + S(59, 61),
     "Bot grid/DCA đã miễn phí khắp nơi; tham số AI có sẵn trên mọi sàn" + S(79)],
    ["Bot tự đổi tham số theo regime: chưa sàn nào làm" + S(79, 84),
     "TradFi perpetual: 206 hợp đồng trên Binance, bot top đã dịch chuyển sang" + S(86)],
    ["Chạy chiến lược bằng vốn thật, công khai PnL, phát hành làm lead bot hoặc lead trader API",
     "Thu bằng chia lợi nhuận người copy"],
    ["Cần vốn và chịu drawdown thật", "Cạnh tranh với hàng trăm nghìn bot và công cụ miễn phí của sàn",
     "Hiệu suất không bền: lead dẫn đầu thay nhau nhanh", "Pháp lý Việt Nam với sàn nước ngoài và stablecoin" + S(43)])
risk_c = risk_c.replace("C · Trade", "D · Trade")
compare = table(["Tiêu chí", "A · Risk đơn thuần", "B · Alpha", "C · Signal", "D · Trade"], [
    ["Cầu đã chứng minh", '<span class="pill bad">Thấp</span>', '<span class="pill good">Có (terminal, API)</span>', '<span class="pill good">Cao nhất</span>', '<span class="pill good">Cao</span>'],
    ["Tiền mỗi người dùng", '<span class="pill neu">—</span>', '<span class="pill warn">Thấp–vừa</span>', '<span class="pill bad">Rất thấp (~$3 AUM)</span>', '<span class="pill good">Cao</span>'],
    ["Cạnh tranh", '<span class="pill good">Ít (bản đúng nghĩa)</span>', '<span class="pill warn">Nhiều</span>', '<span class="pill warn">Nhiều</span>', '<span class="pill bad">Rất nhiều</span>'],
    ["Vốn tự bỏ ra", '<span class="pill good">Không</span>', '<span class="pill good">Không</span>', '<span class="pill good">Không</span>', '<span class="pill bad">Có</span>'],
    ["Thời gian ra tiền", '<span class="pill bad">Chậm</span>', '<span class="pill warn">Trung bình</span>', '<span class="pill warn">Trung bình</span>', '<span class="pill good">Nhanh nếu có lãi</span>'],
    ["Rủi ro chính", "Không ai trả tiền", "Giá bị ép, alpha mất hiệu lực", "Uy tín sụp sau chuỗi lỗ", "Mất vốn"],
    ["Hợp đội nhỏ, không tự trade", '<span class="pill good">Có</span>', '<span class="pill good">Có</span>', '<span class="pill good">Có</span>', '<span class="pill bad">Không</span>'],
])
s8 = f'''<section class="sec" id="s8" hidden="">
{head(8, "Hướng đi (ngách)", "Bốn hướng: risk đơn thuần, alpha, signal, trade", "Mỗi hướng gồm thị trường hiện tại, cơ hội, cách đi và rủi ro, dựa trên số liệu ở các mục trước.")}
{card("So sánh bốn hướng", "", compare)}
<div class="grid2">{risk_c}{alpha_c}</div>
<div class="grid2">{signal_c}{trade_c}</div>
<div class="verdict"><span class="eyebrow">Nhận định</span><div class="t">Signal có nhiều người dùng nhất và không cần tự bỏ vốn, nhưng mỗi người mang rất ít tiền. Alpha bán được dưới dạng terminal và API. Risk đơn thuần chưa có cầu. Trade có tiền lớn nhưng cần vốn.</div>
<p>Với đội không tự trade, ba hướng risk, alpha và signal đều khả thi và bổ trợ nhau: <b>signal và xếp hạng bot có ý thức regime, kèm cảnh báo lỗ treo</b>. Chưa sàn nào làm điều này.{S(79)}</p></div>
</section>'''

# ================================================================== APPENDIX
src_sec = f'''<section class="sec" id="src" hidden="">
{head("PL", "Phụ lục", "Phương pháp và nguồn", "Truy cập ngày 28–29/09/2026. Báo cáo gốc, dữ liệu thô và script: _bmad-output/planning-artifacts/research/market-okx-ai-fintech-agent-economy-2026-09-28/")}
{card("Phương pháp", "", '<ul class="clean">' + ''.join(f'<li>{x}</li>' for x in [
    "<b>Chợ agent:</b> chụp toàn bộ 146 agent online của OKX.AI bằng trình duyệt; lượt 'đã bán' là giới hạn trên vì có tính lượt OKX lấy mẫu.",
    "<b>50 bot:</b> OKX API copy-trading chính thức (lead, lệnh đã đóng, vị thế mở); trang lead Binance công khai; OKX Bot/Signal Marketplace; Binance Trading Bots; DefiLlama.",
    "<b>Regime:</b> nến 4 giờ đã đóng trước lúc vào lệnh; không dùng dữ liệu tương lai. 'Theo đà' là long sau 24 giờ tăng, short sau 24 giờ giảm.",
    "<b>DCA:</b> lệnh mở thêm cùng mã, cùng chiều khi lệnh trước chưa đóng, ở giá xấu hơn. Chỉ đo được trên OKX; Binance gộp vị thế.",
    "<b>Giới hạn:</b> suy luận từ lệnh, không thấy luật của bot; tối đa 1.000 lệnh mỗi lead; tỷ lệ thắng OKX công bố là tỷ lệ ngày lãi; tương quan tâm lý dùng mẫu nhỏ.",
    "<b>Kiểm chứng:</b> 18 nhận định trụ cột đối chiếu nguồn độc lập hoặc đo trực tiếp; tỷ lệ thắng tự tính khớp Binance (chênh trung vị 4 điểm %)."]) + '</ul>')}
{card("Nguồn trích dẫn", "", '<div class="tbl-wrap"><table><thead><tr><th>#</th><th>Nội dung</th><th>Nguồn</th><th>Ngày</th><th>Tin cậy</th></tr></thead><tbody id="src-body"></tbody></table></div>')}
</section>'''

sections = [s1, s2, s3, s4, s5, s6, s7, s8, src_sec]
nav_items = [("s1", "Tóm tắt"), ("s2", "Quy mô"), ("s3", "Market"), ("s4", "Xu hướng"), ("s5", "Flow tổng thể"),
             ("s6", "Top bot"), ("s7", "Tâm lý người dùng"), ("s8", "Hướng đi (4 ngách)"), ("src", "Phụ lục: nguồn")]
nav = ''.join(f'<button data-s="{sid}"><span class="n">{i if sid != "src" else "PL"}</span>{lbl}</button>' for i, (sid, lbl) in enumerate(nav_items, 1))

bots_js = [dict(rank=o['rank'], grp=o['group'], name=o['name'], where=o['where'], url=o['url'], money=o['money'], users=o['users'], style=o['style'],
                how=o['how'], why=o['why'], trend=o['trend'], fit=o['fit'], tone=o['fit_tone'], risks=o['risks'],
                p=(o['metrics'] or {}).get('p'), open=(o['metrics'] or {}).get('open')) for o in F50]
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
  hbar(document.getElementById("chart-tier"), Object.keys(ct).map(k=>({l:k,v:ct[k],c:tc[k]})), Math.max(...Object.values(ct)), v=>v+" agent");
  hbar(document.getElementById("chart-style"), STYLES.map(([k,v])=>({l:k,v})), Math.max(...STYLES.map(s=>s[1])), v=>v+" lead");
})();
(function(){
  const G=[["ALL","Tất cả"],["Trade","Trade"],["Bot grid/DCA","Bot grid/DCA"],["Signal","Signal"],["Alpha/Agent","Alpha/Agent"]]; let g="ALL";
  document.getElementById("b-grp").innerHTML=G.map(([k,l])=>`<button role="tab" data-k="${k}" aria-selected="${k==="ALL"}">${l} <span class="c">${k==="ALL"?BOTS.length:BOTS.filter(b=>b.grp===k).length}</span></button>`).join("");
  document.querySelectorAll("#b-grp button").forEach(b=>b.addEventListener("click",()=>{g=b.dataset.k;document.querySelectorAll("#b-grp button").forEach(x=>x.setAttribute("aria-selected",x===b?"true":"false"));render();}));
  document.getElementById("b-q").addEventListener("input",render);
  const tone={good:"good",warn:"warn",bad:"bad",neu:"neu"};
  const RV={up:"Tăng",down:"Giảm",range:"Đi ngang"};
  const money=v=>(v<0?"−":"")+"$"+Math.abs(v).toLocaleString("vi-VN");
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
      <tr><td>DCA (mở thêm / giá xấu hơn / chồng tối đa)</td><td class="r num">${p.dca?`${p.dca.adds}% / ${p.dca.down??"—"}% / ${p.dca.stack}`:"Không đo được"}</td></tr>
      ${b.open?`<tr><td>Vị thế đang mở · lỗ/lãi chưa chốt</td><td class="r num" style="color:${b.open.upl<0?"var(--bad)":"var(--good)"}">${b.open.n} · ${money(b.open.upl)}</td></tr>`:""}
      </tbody></table></div></div>`;
  }
  function detail(b){
    const L=(t,x)=>`<div><div class="eyebrow">${t}</div><p class="prose">${x}</p></div>`;
    return `<div class="grid2" style="padding:6px 2px 10px"><div class="stack">
      ${L("Cách chơi",esc(b.how))}${L("Vì sao hot",esc(b.why))}${L("Hướng đi",esc(b.trend))}
      ${L("Regime hiện tại",`<span class="pill ${tone[b.tone]}">${esc(b.fit)}</span>`)}
      ${b.risks.length?L("Rủi ro",b.risks.map(r=>`<span class="pill bad" style="margin:0 4px 4px 0">${esc(r)}</span>`).join("")):""}
      <p class="note">${esc(b.where)} · <a href="${esc(b.url)}" target="_blank" rel="noopener">Trang gốc</a></p></div>${metrics(b)||"<div></div>"}</div>`;
  }
  function render(){
    const q=document.getElementById("b-q").value.trim().toLowerCase();
    const rows=BOTS.filter(b=>(g==="ALL"||b.grp===g)&&(!q||(b.name+" "+b.how).toLowerCase().includes(q)));
    document.getElementById("b-count").textContent=rows.length+" bot";
    document.getElementById("b-body").innerHTML=rows.map(b=>`<tr class="brow" style="cursor:pointer" tabindex="0"><td class="num muted">${b.rank}</td>
      <td><b>${esc(b.name)}</b><div class="note">${esc(b.where)}</div></td><td><span class="pill neu">${esc(b.grp)}</span></td><td>${esc(b.style)}</td>
      <td class="r num">${esc(b.money)}</td><td class="r num">${esc(b.users)}</td><td><span class="pill ${tone[b.tone]}">${esc(b.fit.split(":")[0])}</span></td></tr>
      <tr class="bdet" hidden><td colspan="7">${detail(b)}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">Không có bot nào khớp. Hãy bỏ bớt điều kiện lọc.</td></tr>';
    document.querySelectorAll("#b-body tr.brow").forEach(tr=>{const t=()=>{tr.nextElementSibling.hidden=!tr.nextElementSibling.hidden;}; tr.addEventListener("click",t); tr.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();t();}});});
  }
  render();
})();
const confCls=c=>c.startsWith("cao")?"good":c.startsWith("trung bình")?"blue":"warn";
document.getElementById("src-body").innerHTML=SOURCES.map(s=>`<tr id="ref-${s.n}"><td class="num">[${s.n}]</td><td>${esc(s.what)}</td><td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.pub)}</a></td><td class="num muted">${esc(s.date)}</td><td><span class="pill ${confCls(s.conf)}">${esc(s.conf)}</span></td></tr>`).join("");
show((location.hash||"#s1").slice(1), false);
</script>'''
# sources link -> appendix section id "src"
script = script.replace('show("s9",false)', 'show("src",false)')

body = f'''<header class="topbar"><div class="topbar-in"><div class="brand"><div class="logo">OKX</div><div>
<h1>Thị trường Agent Fintech OKX &amp; Binance</h1><p>Quy mô · market · xu hướng · top bot · tâm lý người dùng · hướng đi · dữ liệu 28–29/09/2026</p></div></div>
<div class="chips"><span class="chip blue">BMAD Deep Recon</span><span class="chip">50 bot giải mã</span><span class="chip">86 nguồn</span></div></div></header>
<div class="wrap"><aside class="side"><div class="side-h"><div class="eyebrow">Báo cáo</div><div>8 mục + phụ lục</div></div>
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
open('/home/ubuntu/norabt/okx-report.html', 'w').write(doc)
refs = sorted(set(int(x) for x in re.findall(r'data-ref="(\d+)"', doc)))
print('written', len(doc), 'refs used', len(refs), 'missing', [r for r in refs if r not in {s['n'] for s in SOURCES}])
