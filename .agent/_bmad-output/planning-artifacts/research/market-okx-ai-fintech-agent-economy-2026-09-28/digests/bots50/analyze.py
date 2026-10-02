"""Infer the trading style of 50 top copy-trading leads (OKX + Binance) from their closed
positions and the market regime at entry.

Regime (per symbol, 4H bars, last bar CLOSED before the entry time -> no look-ahead):
  up    : close > EMA50 > EMA200 and ADX14 >= 20
  down  : close < EMA50 < EMA200 and ADX14 >= 20
  range : anything else
  high-vol flag: ATR14 in the top 20% of its trailing 90-day window
"Theo đà" (momentum entry): long after a positive 24h return, short after a negative one.
"""
import bisect
import json
import math
import statistics as st
from collections import Counter, defaultdict

TRADFI = set("""SNDK INTC XAU XAG SPCX SOXL MSTR CL MU LITE NVDA TSLA AAPL AMZN META GOOGL GOOG MSFT COIN HOOD PLTR AMD QQQ SPY
NG BZ CRCL GME AVGO ORCL SMCI ARM BABA TSM NFLX UNH COPPER XPT XPD WTI BRENT NATGAS IBIT MSTU TQQQ SQQQ CRWV RDDT UBER
SNOW SHOP PYPL DIS NKE JPM V MA WMT KO PEP INTU ADBE CRM IONQ RGTI QBTS OKLO CEG VST ASTS RKLB HIMS SOFI UPST APP DUOL""".split())
MEME = set("PEPE DOGE SHIB BONK WIF FLOKI PUMP USELESS FARTCOIN TRUMP MEW POPCAT BOME NEIRO MOODENG PNUT GOAT SPX TURBO BRETT MOG PENGU 1000PEPE 1000BONK 1000SHIB 1000FLOKI".split())
MAJOR = {"BTC", "ETH"}


def ema(xs, n):
    k = 2 / (n + 1); out = []; e = None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k); out.append(e)
    return out


def indicators(c):
    t = [r[0] for r in c]; hi = [r[1] for r in c]; lo = [r[2] for r in c]; cl = [r[3] for r in c]
    e50, e200 = ema(cl, 50), ema(cl, 200)
    tr = [hi[0] - lo[0]] + [max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1])) for i in range(1, len(c))]
    pdm = [0] + [max(hi[i] - hi[i - 1], 0) if hi[i] - hi[i - 1] > lo[i - 1] - lo[i] else 0 for i in range(1, len(c))]
    ndm = [0] + [max(lo[i - 1] - lo[i], 0) if lo[i - 1] - lo[i] > hi[i] - hi[i - 1] else 0 for i in range(1, len(c))]
    def wilder(x, n=14):
        out = []; s = None
        for v in x:
            s = v if s is None else s - s / n + v
            out.append(s)
        return out
    atr_s, p_s, n_s = wilder(tr), wilder(pdm), wilder(ndm)
    dx = []
    for a, p, m in zip(atr_s, p_s, n_s):
        if a <= 0: dx.append(0); continue
        pdi, ndi = 100 * p / a, 100 * m / a
        dx.append(0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    adx = ema(dx, 27)  # Wilder smoothing ~ EMA(2n-1)
    atr = [a / 14 for a in atr_s]
    lab, hv, r24 = [], [], []
    for i in range(len(c)):
        if cl[i] > e50[i] > e200[i] and adx[i] >= 20: lab.append("up")
        elif cl[i] < e50[i] < e200[i] and adx[i] >= 20: lab.append("down")
        else: lab.append("range")
        w = atr[max(0, i - 540):i + 1]
        hv.append(len(w) >= 60 and sorted(w).index(atr[i]) / len(w) >= 0.8 if w else False)
        r24.append(cl[i] / cl[i - 6] - 1 if i >= 6 else 0.0)
    return t, lab, hv, r24, i


EXINFO = {x["symbol"]: x for x in json.load(open("exinfo.json"))["symbols"]}
C = json.load(open("candles_4h.json"))
IND = {}
for s, c in C.items():
    t, lab, hv, r24, _ = indicators(c)
    IND[s] = (t, lab, hv, r24)
H4 = 4 * 3600 * 1000


def regime_at(sym, ms):
    if sym not in IND: return None
    t, lab, hv, r24 = IND[sym]
    i = bisect.bisect_right(t, ms - H4) - 1  # last bar fully closed before entry
    if i < 200: return None  # need EMA200 warm-up
    return lab[i], hv[i], r24[i]


def norm_trades(bot):
    out = []
    for t in bot["trades"]:
        if bot["exchange"] == "OKX":
            if not t.get("closeTime") or not t.get("openTime"):
                continue  # not a fully closed position
            sym = t["instId"].replace("-USDT-SWAP", "USDT").replace("-", "")
            side = t["posSide"]; lev = float(t["lever"]); o, c = int(t["openTime"]), int(t["closeTime"])
            pnl = float(t["pnl"]); notional = float(t.get("margin") or 0) * lev
        else:
            if not t.get("closed") or not t.get("opened"):
                continue
            sym = t["symbol"]; side = t["side"].lower(); lev = float(t["leverage"]); o, c = int(t["opened"]), int(t["closed"])
            pnl = float(t["closingPnl"]); notional = float(t.get("maxOpenInterest") or 0) * float(t.get("avgCost") or 0)
        base = sym[:-4] if sym.endswith("USDT") else sym
        base = base.replace("1000", "") if base.startswith("1000") else base
        info = EXINFO.get(sym)
        if info is not None:
            sub = info.get("underlyingSubType") or []
            cls = "tradfi" if "TradFi" in sub else "major" if base in MAJOR else "meme" if "Meme" in sub or base in MEME else "alt"
        else:
            cls = "tradfi" if base in TRADFI else "major" if base in MAJOR else "meme" if base in MEME else "alt"
        out.append(dict(sym=sym, base=base, cls=cls, side=side, lev=lev, open=o, close=c, pnl=pnl, notional=notional,
                        hold_h=max(0, (c - o) / 3.6e6)))
    return out


REG_VN = {"up": "xu hướng tăng", "down": "xu hướng giảm", "range": "đi ngang"}


def profile(bot):
    T = norm_trades(bot)
    n = len(T)
    wins = [x for x in T if x["pnl"] > 0]; losses = [x for x in T if x["pnl"] < 0]
    gross_w = sum(x["pnl"] for x in wins); gross_l = -sum(x["pnl"] for x in losses)
    first, last = min(x["open"] for x in T), max(x["close"] for x in T)
    days = max(1.0, (last - first) / 8.64e7)
    sym_cnt = Counter(x["base"] for x in T)
    top_syms = sym_cnt.most_common(3)
    cls_cnt = Counter(x["cls"] for x in T)
    longs = sum(1 for x in T if x["side"] == "long")
    levs = sorted(x["lev"] for x in T)
    holds = sorted(x["hold_h"] for x in T)
    # regime tagging
    tagged = []
    for x in T:
        r = regime_at(x["sym"], x["open"])
        if r: x["reg"], x["hv"], x["r24"] = r; tagged.append(x)
    reg_cnt = Counter(x["reg"] for x in tagged)
    reg_pnl = defaultdict(float); reg_n = Counter(); reg_w = Counter()
    for x in tagged:
        reg_pnl[x["reg"]] += x["pnl"]; reg_n[x["reg"]] += 1; reg_w[x["reg"]] += x["pnl"] > 0
    hv_pnl = sum(x["pnl"] for x in tagged if x["hv"]); hv_n = sum(1 for x in tagged if x["hv"])
    trend_tr = [x for x in tagged if x["reg"] in ("up", "down")]
    aligned = sum(1 for x in trend_tr if (x["side"] == "long") == (x["reg"] == "up"))
    mom = [x for x in tagged if abs(x["r24"]) > 0.002]
    mom_in = sum(1 for x in mom if (x["side"] == "long") == (x["r24"] > 0))
    # overlapping positions on the same symbol and side (averaging in / pyramiding)
    by = defaultdict(list)
    for x in T: by[(x["base"], x["side"])].append(x)
    ov = 0
    for arr in by.values():
        arr.sort(key=lambda z: z["open"]); max_close = -1
        for z in arr:
            if z["open"] < max_close: ov += 1
            max_close = max(max_close, z["close"])
    win_hold = st.median([x["hold_h"] for x in wins]) if wins else 0
    loss_hold = st.median([x["hold_h"] for x in losses]) if losses else 0
    top5 = sum(sorted((x["pnl"] for x in wins), reverse=True)[:5])
    net = sum(x["pnl"] for x in T)
    med_loss = st.median([-x["pnl"] for x in losses]) if losses else 0
    worst = -min((x["pnl"] for x in T), default=0)
    hours = Counter(int((x["open"] / 3.6e6) % 24) for x in T)
    p = dict(
        n=n, tagged=len(tagged), days=round(days), per_day=round(n / days, 2),
        top_syms=[(s, round(c / n * 100)) for s, c in top_syms], n_syms=len(sym_cnt),
        cls={k: round(v / n * 100) for k, v in cls_cnt.items()},
        long_pct=round(longs / n * 100), lev_med=levs[len(levs) // 2], lev_p90=levs[int(len(levs) * 0.9) - 1] if n > 1 else levs[0],
        hold_med=round(st.median(holds), 2), hold_lt1=round(sum(1 for h in holds if h < 1) / n * 100),
        hold_gt24=round(sum(1 for h in holds if h >= 24) / n * 100),
        win=round(len(wins) / n * 100), payoff=round((gross_w / len(wins)) / (gross_l / len(losses)), 2) if wins and losses else None,
        pf=round(gross_w / gross_l, 2) if gross_l > 0 else None, net=round(net),
        reg_share={k: round(v / max(1, len(tagged)) * 100) for k, v in reg_cnt.items()},
        reg_pnl={k: round(v) for k, v in reg_pnl.items()},
        reg_win={k: round(reg_w[k] / reg_n[k] * 100) for k in reg_n},
        hv_share=round(hv_n / max(1, len(tagged)) * 100), hv_pnl=round(hv_pnl),
        aligned=round(aligned / len(trend_tr) * 100) if trend_tr else None,
        momentum=round(mom_in / len(mom) * 100) if mom else None,
        overlap=round(ov / n * 100), hold_ratio=round(loss_hold / win_hold, 2) if win_hold > 0 else None,
        top5_share=round(top5 / net * 100) if net > 0 else None, tail=round(worst / med_loss, 1) if med_loss > 0 else None,
        peak_hours=[h for h, _ in hours.most_common(3)],
    )
    return p


def classify(p, meta):
    style = "Hỗn hợp / linh hoạt"
    if p["overlap"] >= 35 and (p["hold_ratio"] or 0) >= 2:
        style = "Nhồi lệnh, gồng lỗ (DCA)"
    elif p["hold_med"] < 1 and p["per_day"] >= 3:
        style = "Scalper, lướt sóng ngắn"
    elif (p["momentum"] or 0) >= 58 and (p["aligned"] or 0) >= 55:
        style = "Theo xu hướng, theo đà"
    elif p["momentum"] is not None and p["momentum"] <= 42:
        style = "Bắt đảo chiều, ngược đà"
    elif p["hold_med"] >= 24:
        style = "Swing, giữ lệnh dài"
    tags = []
    if p["lev_med"] >= 50: tags.append("Đòn bẩy rất cao")
    elif p["lev_med"] >= 20: tags.append("Đòn bẩy cao")
    if p["long_pct"] >= 70: tags.append("Nghiêng long")
    elif p["long_pct"] <= 30: tags.append("Nghiêng short")
    if p["top_syms"] and p["top_syms"][0][1] >= 60: tags.append("Tập trung 1 mã")
    if p["cls"].get("tradfi", 0) >= 30: tags.append("TradFi (cổ phiếu, hàng hoá)")
    if p["cls"].get("meme", 0) >= 30: tags.append("Meme coin")
    if meta.get("apiKeyTag"): tags.append("Chạy bằng API/bot")
    if p["top5_share"] and p["top5_share"] >= 60: tags.append("Lãi dồn vào vài lệnh")
    if (p["hold_ratio"] or 0) >= 3: tags.append("Giữ lệnh lỗ lâu hơn lệnh lãi")
    if p["tail"] and p["tail"] >= 15: tags.append("Có lệnh lỗ cực lớn")
    return style, tags


def narrative(p, style, tags):
    syms = ", ".join(s for s, _ in p["top_syms"])
    side = "chủ yếu long" if p["long_pct"] >= 65 else "chủ yếu short" if p["long_pct"] <= 35 else "cả long lẫn short"
    hold = (f"{round(p['hold_med'] * 60)} phút" if p["hold_med"] < 1 else f"{p['hold_med']:.1f} giờ" if p["hold_med"] < 48 else f"{p['hold_med'] / 24:.1f} ngày")
    parts = [f"Đánh {syms}, {side}; giữ lệnh trung vị {hold}, đòn bẩy trung vị {p['lev_med']:g}x, {p['per_day']:g} lệnh/ngày."]
    if p["momentum"] is not None:
        parts.append(f"{p['momentum']}% lệnh vào cùng chiều biến động 24 giờ trước đó" + (
            ", tức đánh theo đà." if p["momentum"] >= 58 else ", tức hay đánh ngược đà, bắt đỉnh đáy." if p["momentum"] <= 42 else "."))
    if p["reg_pnl"]:
        best = max(p["reg_pnl"], key=p["reg_pnl"].get); worst = min(p["reg_pnl"], key=p["reg_pnl"].get)
        s = f"Kiếm nhiều nhất khi thị trường {REG_VN[best]}"
        if p["reg_pnl"][worst] < 0: s += f", lỗ khi {REG_VN[worst]}"
        parts.append(s + ".")
    risk = [t for t in tags if t in ("Đòn bẩy rất cao", "Lãi dồn vào vài lệnh", "Giữ lệnh lỗ lâu hơn lệnh lãi", "Có lệnh lỗ cực lớn")]
    if risk: parts.append("Cần để ý: " + ", ".join(r.lower() for r in risk) + ".")
    return " ".join(parts)


bots = json.load(open("okx_bots.json")) + json.load(open("bnb_bots.json"))
rows = []
for b in bots:
    m = b["meta"]; p = profile(b); style, tags = classify(p, m)
    if b["exchange"] == "OKX":
        head = dict(pnl=float(m.get("pnl") or 0), roi=float(m.get("pnlRatio") or 0) * 100, aum=float(m.get("aum") or 0),
                    copiers=int(m.get("copyTraderNum") or 0), cap=int(m.get("maxCopyTraderNum") or 0), lead_days=int(m.get("leadDays") or 0),
                    win_official=round(float((b.get("stats") or {}).get("winRatio") or 0) * 100), mdd=None,
                    url=f"https://www.okx.com/copy-trading/account/{b['id']}?tab=swap")
    else:
        d = b.get("detail") or {}
        head = dict(pnl=float(m.get("pnl") or 0), roi=float(m.get("roi") or 0), aum=float(m.get("aum") or 0),
                    copiers=int(m.get("currentCopyCount") or 0), cap=int(m.get("maxCopyCount") or 0),
                    lead_days=round((1790640000000 - int(m.get("startTime") or 0)) / 8.64e7) if m.get("startTime") else None,
                    win_official=round(float(m.get("winRate") or 0)), mdd=round(float(m.get("mdd") or 0), 1),
                    url=f"https://www.binance.com/en/copy-trading/lead-details/{b['id']}")
    rows.append(dict(exchange=b["exchange"], id=b["id"], name=b["name"], api=bool(m.get("apiKeyTag")), **head,
                     style=style, tags=tags, story=narrative(p, style, tags), p=p))

# rank for display: composite of headline PnL, AUM, copiers within each exchange
for ex in ("OKX", "Binance"):
    sub = [r for r in rows if r["exchange"] == ex]
    for key in ("pnl", "aum", "copiers"):
        for i, r in enumerate(sorted(sub, key=lambda r: -r[key])): r.setdefault("_rk", 0); r["_rk"] += i
rows.sort(key=lambda r: r["_rk"])
for i, r in enumerate(rows, 1): r["rank"] = i; r.pop("_rk")
json.dump(rows, open("bots_profiled.json", "w"), ensure_ascii=False, indent=1)

# ---- aggregate trends
agg = {}
agg["n_bots"] = len(rows); agg["n_trades"] = sum(r["p"]["n"] for r in rows); agg["tagged"] = sum(r["p"]["tagged"] for r in rows)
agg["styles"] = {ex: Counter(r["style"] for r in rows if r["exchange"] == ex) for ex in ("OKX", "Binance")}
agg["tags"] = Counter(t for r in rows for t in r["tags"])
agg["lev_med"] = {ex: st.median([r["p"]["lev_med"] for r in rows if r["exchange"] == ex]) for ex in ("OKX", "Binance")}
agg["hold_med"] = {ex: round(st.median([r["p"]["hold_med"] for r in rows if r["exchange"] == ex]), 1) for ex in ("OKX", "Binance")}
agg["win_med"] = {ex: st.median([r["p"]["win"] for r in rows if r["exchange"] == ex]) for ex in ("OKX", "Binance")}
agg["long_med"] = {ex: st.median([r["p"]["long_pct"] for r in rows if r["exchange"] == ex]) for ex in ("OKX", "Binance")}
agg["momentum_med"] = st.median([r["p"]["momentum"] for r in rows if r["p"]["momentum"] is not None])
agg["aligned_med"] = st.median([r["p"]["aligned"] for r in rows if r["p"]["aligned"] is not None])
cls_all = Counter(); sym_all = Counter()
for b in bots:
    for x in norm_trades(b): cls_all[x["cls"]] += 1; sym_all[x["base"]] += 1
agg["cls"] = {k: round(v / sum(cls_all.values()) * 100) for k, v in cls_all.items()}
agg["top_syms"] = sym_all.most_common(15)
# where money is made, per bot: which regime holds the largest PnL
agg["best_regime"] = Counter(max(r["p"]["reg_pnl"], key=r["p"]["reg_pnl"].get) for r in rows if r["p"]["reg_pnl"])
agg["reg_share_all"] = {}
tot = Counter()
for r in rows:
    for k, v in r["p"]["reg_share"].items(): tot[k] += v * r["p"]["tagged"] / 100
agg["reg_share_all"] = {k: round(v / sum(tot.values()) * 100) for k, v in tot.items()}
agg["reg_win_all"] = {}
wins = Counter(); cnts = Counter()
for r in rows:
    for k, w in r["p"]["reg_win"].items():
        c = r["p"]["reg_share"].get(k, 0) * r["p"]["tagged"] / 100; wins[k] += w * c / 100; cnts[k] += c
agg["reg_win_all"] = {k: round(wins[k] / cnts[k] * 100) for k in cnts}
agg["api_bots"] = sum(1 for r in rows if r["api"])
json.dump(agg, open("bots_agg.json", "w"), ensure_ascii=False, indent=1, default=lambda o: dict(o))
print(json.dumps(agg, ensure_ascii=False, indent=1, default=lambda o: dict(o))[:3500])
for r in rows[:8]:
    print(r["rank"], r["exchange"], r["name"], "|", r["style"], r["tags"], "\n   ", r["story"])
