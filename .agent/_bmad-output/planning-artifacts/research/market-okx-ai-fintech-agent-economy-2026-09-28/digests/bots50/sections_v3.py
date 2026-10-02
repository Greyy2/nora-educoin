# Concise section content (spliced into build_v3.py between the data block and the nav/script block).
# Relies on names defined above it in build_v2.py: head, table, card, kpi, grid2, S, fmt, pct, REG, PILL,
# NOW, A, EX, DCA, PC, R, TOP, F50, reg_cnt, hv_n, btc, eth, bar_time, n_counter, fit_cnt, grp_cnt, money_rows.
from collections import Counter

style_counts = Counter(r['style'] for r in R)

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
rn_rows = [[f"<b>{o['sym'].replace('USDT', '')}</b>",
            f'<span class="pill {PILL[o["reg"]]}">{REG[o["reg"]]}</span>' + (' <span class="pill warn">Biến động cao</span>' if o['hv'] else ''),
            pct(o['r7']) + "%" if o['r7'] is not None else "—"] for o in NOW[:15]]
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
trend = table(["Xu hướng", "Thực tế"], [
    ['<span class="pill good">Nóng</span> Copy-trade và tín hiệu', "10K–50K người theo mỗi bot/kênh top" + S(57, 58)],
    ['<span class="pill good">Nóng</span> TradFi token hoá', "~20% lệnh bot top; 206 hợp đồng trên Binance" + S(86)],
    ['<span class="pill bad">Nguội</span> Token agent', "Giảm 70–90%" + S(28)],
    ['<span class="pill bad">Kỳ vọng ≠ thực tế</span> Chợ agent', "OKX công bố 10.000+ agent; thực đo 146 online" + S(1, 5)],
])
s4 = f'''<section class="sec" id="s4" hidden="">
{head(4, "Xu hướng", "Thị trường đang đi ngang: lối chơi nào hợp lúc này", f"Regime trên nến 4 giờ đóng lúc {bar_time} UTC.")}
<div class="kpis">
{kpi("Đi ngang", f"{reg_cnt['range']}/30", "mã bot top đánh nhiều")}
{kpi("Tăng / giảm", f"{reg_cnt['up']} / {reg_cnt['down']}", "mã")}
{kpi("Biến động cao", f"{hv_n}/30", "mã")}
{kpi("BTC / ETH 7 ngày", f"{pct(btc['r7'])} / {pct(eth['r7'])}%", "đi ngang")}
</div>
{grid2(card("Lối chơi hợp lúc này", f"{fit_cnt['good']}/50 bot top đang hợp regime", style_fit), card("Regime 15 mã bot top đánh nhiều nhất", "", table(["Mã", "Regime", "7 ngày"], rn_rows, right=(2,))))}
{card("Khi regime đổi", "Để chuẩn bị trước", scen)}
{card("Xu hướng lớn", "", trend)}
</section>'''

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
<div class="card stack">
<div class="filters"><div class="tabs" role="tablist" id="b-grp"></div><input id="b-q" type="search" placeholder="Tìm tên hoặc mã…" aria-label="Tìm bot"><span class="count" id="b-count"></span></div>
<div class="tbl-wrap"><table><thead><tr><th>#</th><th>Bot</th><th>Loại</th><th>Lối chơi</th><th class="r">Tiền</th><th class="r">Người dùng</th><th>Regime</th></tr></thead><tbody id="b-body"></tbody></table></div>
</div>
{grid2(card("Lối chơi của 50 lead", "Thắng nhiều lần nhỏ, thua một lần lớn", '<div class="hbar" id="chart-style"></div>'),
       card("Lỗ treo bảng xếp hạng không cho thấy", "Vị thế đang mở, OKX", hidden_tbl))}
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
