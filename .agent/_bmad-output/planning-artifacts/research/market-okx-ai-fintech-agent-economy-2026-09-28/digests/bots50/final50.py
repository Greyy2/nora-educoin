"""Assemble the 50 money-making bots (trade leads, grid/DCA bots, signal channels, alpha/agent products)
with a clear analysis layer per bot: how it plays, why it is hot, direction, fit with the current regime, risks."""
import json
import subprocess
import datetime as dt
from collections import Counter

SP = '/tmp/claude-1000/-home-ubuntu-norabt/47a0aee2-9f8b-4307-bd29-550a7e8f13f1/scratchpad/'
R = json.load(open('bots_profiled.json'))
NOW = {o['sym']: o for o in json.load(open('regime_now.json'))}
src = open('analyze.py').read(); ns = {}; exec(src[:src.index('bots = json.load(open("okx_bots.json"))')], ns)
IND, C = ns['IND'], ns['C']
REG_VN = {"up": "tăng", "down": "giảm", "range": "đi ngang"}
fmt = lambda v: f"{v:,.0f}".replace(',', '.')
money = lambda v: ("−" if v < 0 else "") + "$" + fmt(abs(v))


def klines(sym):
    try:
        d = json.loads(subprocess.run(["curl", "-s", "--max-time", "10", f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=4h&limit=300"],
                                      capture_output=True, text=True, timeout=12).stdout)
        return [[int(k[0]), float(k[2]), float(k[3]), float(k[4])] for k in d] if isinstance(d, list) else []
    except Exception:
        return []


def regime_now(sym):
    if sym in NOW and 'px' in NOW[sym]: return NOW[sym]
    if sym not in IND:
        c = klines(sym)
        if len(c) < 210: return None
        t, lab, hv, r24, _ = ns['indicators'](c); C[sym] = c; IND[sym] = (t, lab, hv, r24)
    t, lab, hv, r24 = IND[sym]; i = len(t) - 2; c = C[sym]
    o = dict(sym=sym, reg=lab[i], hv=hv[i], r24=round(r24[i] * 100, 1), r7=round((c[i][3] / c[i - 42][3] - 1) * 100, 1), px=c[i][3])
    NOW[sym] = o; return o


def fit(style, long_pct, now):
    """How well a style fits the symbol's current regime."""
    if not now: return ("neu", "Chưa đủ dữ liệu regime")
    reg, hv, r7 = now['reg'], now['hv'], now['r7']
    counter = style in ("Bắt đảo chiều, ngược đà", "Nhồi lệnh, gồng lỗ (DCA)", "Hỗn hợp / linh hoạt", "Grid", "DCA")
    if counter:
        if reg == "range" and not hv: return ("good", f"Hợp: mã chính đang đi ngang ({now['r7']:+.1f}%/7 ngày)")
        if reg == "range" and hv: return ("warn", "Tạm hợp: đi ngang nhưng biến động cao, dễ phá vùng")
        drift_bad = (long_pct >= 60 and reg == "down") or (long_pct <= 40 and reg == "up")
        return ("bad" if drift_bad else "warn", f"Rủi ro: mã chính đang xu hướng {REG_VN[reg]}, lối ngược đà dễ bị kéo")
    if style == "Theo xu hướng, theo đà":
        return ("good", f"Hợp: có xu hướng {REG_VN[reg]}") if reg != "range" else ("warn", "Kém hợp: thị trường đi ngang, dễ bị quét hai đầu")
    return ("neu", f"Mã chính đang {REG_VN[reg]}")


out = []
# ---------- A. Trade leads: 14 OKX + 14 Binance by composite rank
for ex in ("OKX", "Binance"):
    sub = sorted([r for r in R if r['exchange'] == ex], key=lambda r: r['rank'])[:14]
    for r in sub:
        p = r['p']; main = p['top_syms'][0][0] + "USDT" if p['top_syms'] else None
        now = regime_now(main) if main else None
        tone, fit_txt = fit(r['style'], p['long_pct'], now)
        fill = round(r['copiers'] / r['cap'] * 100) if r['cap'] else None
        if ex == "OKX":
            why = f"AUM {money(r['aum'])} và {r['copiers']} người copy: đám đông thấy tiền đông thì theo; ROI công bố {r['roi']:.0f}%."
        else:
            why = f"Tỷ lệ thắng {p['win']}%" + (f", MDD công bố {r['mdd']}%" if r['mdd'] is not None else "") + f", {r['copiers']}/{r['cap']} suất copy ({fill}%): người dùng Binance chọn bot thắng đều, ít sụt."
        cls = p['cls']; trend = []
        if cls.get('tradfi', 0) >= 30: trend.append(f"dịch chuyển sang TradFi ({cls['tradfi']}% lệnh)")
        if cls.get('meme', 0) >= 30: trend.append(f"săn meme coin ({cls['meme']}% lệnh)")
        if p['top_syms'] and p['top_syms'][0][1] >= 60: trend.append(f"tập trung vào {p['top_syms'][0][0]}")
        if p.get('dca') and p['dca']['adds'] >= 35 and (p['dca']['down'] or 0) >= 60: trend.append("vận hành bằng bình quân giá xuống")
        risks = [t for t in r['tags'] if any(k in t for k in ("Lỗ treo", "lỗ cực lớn", "dồn vào", "Đòn bẩy rất", "Giữ lệnh lỗ"))]
        out.append(dict(group="Trade", name=r['name'], where=f"{ex} Copy Trading" + (" · API" if r['api'] else ""), url=r['url'],
                        money=f"PnL công bố {money(r['pnl'])}", users=f"{r['copiers']} người copy", users_n=r['copiers'],
                        style=r['style'], how=r['story'], why=why, trend=("Đang " + ", ".join(trend) + ".") if trend else "Lối chơi ổn định trong kỳ khảo sát.",
                        fit=fit_txt, fit_tone=tone, risks=risks, metrics=dict(p=p, open=r.get('open'), mdd=r['mdd'], roi=r['roi'], aum=r['aum'])))

# ---------- B. OKX Bot Marketplace (DCA futures) and Binance futures grid
okb = json.load(open(SP + 'okxct_caught.json'))
S = [s for x in okb if x['url'].split('?')[0].endswith('search') for s in x['json']['data'][0]['strategies']]
eth = regime_now("ETHUSDT")
for s in sorted(S, key=lambda s: -float(s['followerAssets'])):
    side = s.get('direction'); lev = s.get('leverage'); since = dt.datetime.fromtimestamp(int(s['cTime']) / 1000, dt.timezone.utc).strftime('%m/%Y')
    tone, ft = fit("DCA", 80 if side == "long" else 20, eth)
    out.append(dict(group="Bot grid/DCA", name=f"{s['username']} · DCA {side} ETH", where="OKX Bot Marketplace",
                    url="https://www.okx.com/trading-bot/marketplace", money=f"PnL {money(float(s['pnl']))} ({float(s['pnlRatio']) * 100:.0f}%)",
                    users=f"{int(s['followerCount']):,}".replace(',', '.') + " người copy", users_n=int(s['followerCount']), style="DCA futures",
                    how=f"DCA hợp đồng ETH chiều {side}, đòn bẩy {lev}x, chạy từ {since}: vào dần theo bước giá khi giá đi ngược, chốt lời khi hồi. Người copy mang {money(float(s['followerAssets']))} chạy theo; người tạo nhận {float(s['profitSharingRatio']) * 100:.0f}% lợi nhuận.",
                    why="Lợi nhuận tích luỹ lớn và lâu năm hiển thị ngay trên chợ; một chạm là copy.",
                    trend="Cùng người tạo chạy song song bản long và bản short ETH: kiếm tiền từ dao động hai chiều thay vì đoán hướng." if s['username'] in ("Used-WebSocket-Lilac", "Mist will disperse") else "Bản DCA long ETH chạy lâu, nhiều người copy.",
                    fit=ft, fit_tone=tone, risks=["Đòn bẩy 20x", "DCA dễ chồng lỗ khi ETH đi một chiều dài"], metrics=None))
bnb = json.load(open(SP + 'bnb_caught.json'))
G = []
for x in bnb:
    u = x['url'].split('?')[0]
    if u.endswith('queryTopStrategy'):
        G += [g for g in x['json']['data'] if g.get('strategyType') == 2]
G = sorted({(g['symbol'], g.get('pnl')): g for g in G}.values(), key=lambda g: -float(g['pnl']))[:4]
for g in G:
    pr = g['strategyParams']; sym = g['symbol'].replace('USDC', 'USDT'); now = regime_now(sym)
    lo, hi = float(pr['lowerLimit']), float(pr['upperLimit']); px = now['px'] if now else None
    pos = None if px is None else ("dưới vùng" if px < lo else "trên vùng" if px > hi else f"trong vùng ({(px - lo) / (hi - lo) * 100:.0f}% từ đáy)")
    tone, ft = fit("Grid", 50, now)
    if pos and "vùng (" not in pos: tone, ft = "bad", f"Giá đang {pos}: lưới không còn hoạt động đúng"
    days = round(int(g['runningTime']) / 1440)
    out.append(dict(group="Bot grid/DCA", name=f"Grid futures {g['symbol']}", where="Binance Trading Bots",
                    url="https://www.binance.com/en/trading-bots", money=f"PnL {money(float(g['pnl']))} (ROI {float(g['roi']):.1f}%)",
                    users=f"{g['copyCount']} người copy", users_n=int(g['copyCount']), style="Grid futures",
                    how=f"Lưới {pr['type']} {pr['gridCount']} mức từ {pr['lowerLimit']} đến {pr['upperLimit']}, đòn bẩy {pr['leverage']}x, chạy {days} ngày: mua thấp bán cao trong vùng; giá hiện {pos or 'không rõ'}.",
                    why="Bảng 'top strategy' của Binance hiển thị PnL và cho copy tham số một chạm.",
                    trend=("Có tính năng trượt vùng lên (trailing up)." if pr.get('trailingUp') else "Vùng giá cố định, không tự dời."),
                    fit=ft, fit_tone=tone, risks=["Phá vùng khi thị trường ra xu hướng", f"Đòn bẩy {pr['leverage']}x"], metrics=None))

# ---------- C. OKX Signal Marketplace
ok2 = json.load(open(SP + 'okxbot2.json'))
SIG = [x for x in ok2 if x['url'].split('?')[0].endswith('signals')][0]['json']['data'][0]['signals']
for s in SIG:
    apy = float(s['annualizedRate']) * 100; wr = float(s['followerWinRate']) * 100
    gap = "Chênh lớn giữa APY backtest và tỷ lệ thắng thực của người theo." if apy > 100 and wr < 50 else ("Hiệu suất 30 ngày đang âm." if apy < 0 else "Hiệu suất và tỷ lệ thắng khá khớp.")
    out.append(dict(group="Signal", name=s['signalChanName'], where="OKX Signal Marketplace", url="https://www.okx.com/trading-bot/signal-marketplace",
                    money=f"AUM người theo {money(float(s['totalFollowerAssets']))}", users=f"{int(s['totalFollowerCount']):,}".replace(',', '.') + " người theo",
                    users_n=int(s['totalFollowerCount']), style="Kênh tín hiệu tự vào lệnh",
                    how=f"Phát tín hiệu, bot của người theo tự vào lệnh. APY backtest 30 ngày {apy:+.0f}%, tỷ lệ thắng của người theo {wr:.0f}%. Người tạo nhận {float(s['profitSharingRatio']) * 100:.0f}% lợi nhuận.",
                    why=("Kênh lâu năm, thương hiệu quen (" + s['username'] + "): số người theo lớn dù hiệu suất gần đây yếu.") if int(s['totalFollowerCount']) > 10000 else "APY backtest cao hiển thị nổi bật.",
                    trend=gap, fit="Tín hiệu, không gắn một regime cố định", fit_tone="neu",
                    risks=(["APY là backtest, không phải kết quả thực"] + (["Tỷ lệ thắng thực dưới 50%"] if wr < 50 else [])), metrics=None))

# ---------- D. Alpha / agent products that make money
ALPHA = [
    ("GMGN", "Solana, BSC, Base", "DT 30 ngày $42,55M", "Hàng triệu trader meme", "Terminal theo dõi ví smart money, bắn lệnh nhanh; thu phí mỗi lệnh.", "Bán alpha (ví cá voi, token mới) kèm công cụ vào lệnh ngay.", "Tăng mạnh: 30 ngày cao hơn trung bình năm.", "https://defillama.com/protocol/gmgn"),
    ("fomo", "Solana, BSC, Monad", "DT 30 ngày $31,08M", "Người dùng phổ thông", "Ví và app giao dịch mạng xã hội, xem người khác mua gì rồi mua theo.", "Copy-trade kiểu mạng xã hội, dễ dùng trên điện thoại.", "Tăng nhanh nhất: 30 ngày = 45% doanh thu cả năm.", "https://fomo.family"),
    ("Axiom", "Solana, BSC", "DT 30 ngày $18,23M", "Trader meme, perp", "Terminal giao dịch meme và perp tốc độ cao.", "Vào lệnh nhanh, gom nhiều nguồn thanh khoản.", "Đi ngang ở mức cao.", "https://axiom.trade"),
    ("Bankr", "Base", "DT 30 ngày $1,12M", "Người dùng X/Farcaster", "AI agent nhận lệnh bằng ngôn ngữ tự nhiên trên X, tự giao dịch và phát hành token.", "Giao dịch chỉ bằng một câu chat.", "Đang giảm so với trung bình năm.", "https://defillama.com/protocol/bankr"),
    ("缠论趋势指标 · TradeDesk", "OKX.AI", "8.580 lượt bán × 0,1 USDT", "Trader châu Á", "API chỉ báo xu hướng theo lý thuyết Chan, trả tiền theo lượt.", "Phương pháp phân tích riêng, quen thuộc với trader Trung Quốc.", "Chiếm 92% lượt dùng fintech trên OKX.AI.", "https://www.okx.ai/agents/11167"),
    ("1M · 斯巴达", "OKX.AI", "Vô địch Hackathon S1, lãi $24.907", "154 thuê bao", "Tín hiệu copy-trade theo xu hướng, 2–5 lệnh/tháng, thuê bao 20 USDT/tháng.", "PnL thật được kiểm chứng qua hackathon.", "Gói thuê bao cao nhất đang có trên OKX.AI.", "https://www.okx.ai/agents/8136"),
]
for name, where, m, users, how, why, trend, url in ALPHA:
    out.append(dict(group="Alpha/Agent", name=name, where=where, url=url, money=m, users=users, users_n=0, style="Alpha / agent", how=how, why=why, trend=trend,
                    fit="Không phụ thuộc một regime", fit_tone="neu", risks=["Doanh thu dao động mạnh theo mùa meme"] if name in ("GMGN", "fomo", "Axiom") else [], metrics=None))

for i, o in enumerate(out, 1): o['rank'] = i
json.dump(out, open('final50.json', 'w'), ensure_ascii=False, indent=1)
json.dump(NOW, open('regime_now_all.json', 'w'), ensure_ascii=False, indent=1)
print(len(out), Counter(o['group'] for o in out), Counter(o['fit_tone'] for o in out))
for o in out[:3] + out[28:31] + out[34:36] + out[38:40] + out[44:46]:
    print(o['rank'], o['group'], o['name'], '|', o['fit'])
