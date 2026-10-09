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
var_card = card("Biến thể DCA của 14 lead OKX", "Cùng một khung, khác nhau ở 5 núm vặn: bước giá, số tầng, size tầng sau, cách chốt, đòn bẩy",
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
{kpi("Lead OKX có DCA", f"{n_dca}/14", f"{n_dca_strict} DCA rõ, {n_dca - n_dca_strict} DCA nhẹ")}
{kpi("Bot grid/DCA", f"{grp_cnt['Bot grid/DCA']}/{grp_cnt['Bot grid/DCA']}", "DCA/grid theo định nghĩa")}
{kpi("Binance gồng lỗ sâu", f"{n_deep}/14", "dấu hiệu bình quân giá")}
{kpi("Cùng lên xuống", sgn(CO['OKX']['med']), "tương quan trung vị giữa 2 bot OKX")}
</div>'''
dca_verdict = f'''<div class="verdict" data-bt="dca-verdict"><span class="eyebrow">Nhận định</span>
<div class="t">Đúng: phần lớn bot top dùng DCA ({n_dca}/14 lead OKX, {grp_cnt['Bot grid/DCA']}/{grp_cnt['Bot grid/DCA']} bot grid/DCA, {n_deep}/14 lead Binance có dấu hiệu). Mỗi bot là một biến thể, khác nhau ở 5 núm vặn.</div>
<p>DCA không làm thắng nhiều hơn, nhưng làm cú lỗ cuối nặng hơn. Các bot ít khi lên xuống cùng nhau vì đánh mã và thời điểm khác nhau. Vì vậy phải chấm rủi ro từng bot theo 5 núm vặn cộng regime, không thể dùng một điểm chung.</p></div>'''

# per-bot strategy sketch for the detail rows
RV_ = {"up": "xu hướng tăng", "down": "xu hướng giảm", "range": "đi ngang"}
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
            core = (f"khi giá đi ngược, vào thêm mỗi ~{dec(v['spacing'], 2)}%, tầng sau ×{dec(v['size'], 1)} tầng trước, tối đa {v['stack']} tầng; "
                    f"{v['basket']}% tầng đóng cùng lúc tầng trước (chốt cả rổ)")
        s = f"{v['variant']}: {syms}, {side}, {dec(p['lev_med'], 0)}x; {core}; chốt lời trung vị {dec(v['tp'], 0)}% ký quỹ."
    else:
        core = (f"{v['deep_win']}% lệnh thắng từng lỗ ≥ 50% ký quỹ trước khi về lãi (gồng lỗ hoặc bình quân giá)" if v['variant'] == 'Gồng lỗ sâu'
                else "ít khi để giá đi ngược sâu, vào ra dứt khoát" if v['variant'] == 'Vào–ra dứt khoát' else "ít lệnh giữ lâu, chưa đủ để đo")
        s = f"{v['variant']}: {syms}, {side}, {dec(p['lev_med'], 0)}x; {core}; chốt lời trung vị {dec(v['tp'], 0)}% ký quỹ."
    if best: s += f" Ăn nhiều nhất khi {RV_[best]}; nguy hiểm khi {worst}."
    return s
