"""Sàng lọc nhanh lối LƯỚT NGẮN kiểu bot top (vào limit maker, chốt lời limit maker, cắt lỗ cứng).

Mục đích: trả lời "tín hiệu bắt hồi có edge 2–4 bps ở mốc 15 phút; vào/ra bằng maker (~4 bps khứ hồi)
thay vì taker (~14 bps) thì có thành lãi không?" TRƯỚC khi đưa vào engine thật.

Mô phỏng (bi quan, không nhìn trước), trên nến 1m perp thật:
- Tín hiệu đúng trên nến i đã đóng -> đặt LIMIT post-only (GTX) tại close_i × (1 ∓ off), sống ttl phút.
  Nếu open của phút kế tiếp đã vượt qua giá limit (lệnh thành taker) thì GTX bị từ chối -> không vào.
- Khớp khi giá ĐI XUYÊN qua limit (low < L với long), khớp đúng giá L (maker, không trượt).
- Sau khi khớp: SL (taker + trượt) được xét ngay trong nến khớp; TP (maker) chỉ từ nến sau.
  Cùng nến chạm cả SL và TP -> tính SL. Gap qua mức -> khớp ở open. Hết giờ -> đóng ở open (taker).
- Một vị thế một lúc: sự kiện chỉ được nhận nếu tới sau khi lệnh trước đã thoát.
Không tính funding (giữ lệnh ngắn); engine thật sẽ tính.

Chống overfit: chọn cấu hình CHỈ trên 80% đầu (dev); 20% cuối (holdout) chỉ in cho các cấu hình đã chọn.

Dùng: PYTHONPATH=. python -m backend.core.research.research_maker_scalp [--assets BTC,ETH] [--workers auto|8]
"""
import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002
GRIDS = {
    # vòng 1: rộng, limit nông
    "r1": dict(OFFS=[0.0, 0.1, 0.2, 0.4], TTLS=[5, 15, 60], TPS=[0.15, 0.3, 0.6, 1.0], SLS=[0.5, 1.0, 2.0, 4.0],
               TOS=[30, 120, 480]),
    # vòng 2: limit sâu (vòng 1 cho thấy offset lớn nhất tốt nhất), giữ lâu hơn
    "r2": dict(OFFS=[0.4, 0.7, 1.0, 1.5], TTLS=[60, 240], TPS=[0.4, 0.7, 1.0, 1.5], SLS=[1.0, 2.0, 3.0],
               TOS=[120, 480, 1440]),
}
OFFS, TTLS, TPS, SLS, TOS = (GRIDS["r1"][k] for k in ("OFFS", "TTLS", "TPS", "SLS", "TOS"))
SIGNAL_SET = "r1"
DEV_FRAC = 0.8
# Giá khớp stop-loss khi giá chạm SL TRONG một nến:
#   "level"   = đúng mức SL (lạc quan: giả định không có cú giật xuyên mức — đây là giả định của engine cũ)
#   "extreme" = giá xấu nhất của nến (bi quan nhất: low với long, high với short)
# Phép kiểm random walk đuôi dày cho thấy "level" tạo edge giả +10 bps với lối rải limit bắt wick.
SL_FILL = "extreme"


def _signals():
    from backend.core.strategy.library import cond, f
    if SIGNAL_SET == "r2":
        up = (f("4h", "ema_50"), ">", f("4h", "ema_200"))
        rng = (f("1h", "er_20"), "<", 0.3)
        return {("LONG", k): v for k, v in {
            "rsi15m_20": cond((f("15m", "rsi_14"), "<", 20)),
            "rsi15m_25": cond((f("15m", "rsi_14"), "<", 25)),
            "rsi15m_30": cond((f("15m", "rsi_14"), "<", 30)),
            "rsi1h_30": cond((f("1h", "rsi_14"), "<", 30)),
            "rsi15m_25_up4h": cond((f("15m", "rsi_14"), "<", 25), up),
            "rsi15m_25_range": cond((f("15m", "rsi_14"), "<", 25), rng),
            "always": cond((f("1m", "close"), ">", 0)),
        }.items()} | {("SHORT", k): v for k, v in {
            "rsi15m_75": cond((f("15m", "rsi_14"), ">", 75)),
            "rsi15m_75_dn4h": cond((f("15m", "rsi_14"), ">", 75), (f("4h", "ema_50"), "<", f("4h", "ema_200"))),
            "always": cond((f("1m", "close"), ">", 0)),
        }.items()}
    L = {
        "z60_rsi7": cond((f("1m", "rsi_7"), "<", 20), (f("1m", "bbz_60"), "<", -2.5)),
        "z60_deep": cond((f("1m", "bbz_60"), "<", -3.5)),
        "rsi5m_25": cond((f("5m", "rsi_14"), "<", 25)),
        "bb5m_range": cond((f("5m", "rsi_14"), "<", 30), (f("5m", "close"), "<", f("5m", "bbl_20_2")),
                           (f("1h", "er_20"), "<", 0.35)),
        "vwap_dip": cond((f("1m", "vwapdev_60"), "<", -0.6), (f("1m", "rsi_7"), "<", 25)),
        "rsi15m_25": cond((f("15m", "rsi_14"), "<", 25)),
    }
    S = {
        "z60_rsi7": cond((f("1m", "rsi_7"), ">", 80), (f("1m", "bbz_60"), ">", 2.5)),
        "z60_deep": cond((f("1m", "bbz_60"), ">", 3.5)),
        "rsi5m_25": cond((f("5m", "rsi_14"), ">", 75)),
        "bb5m_range": cond((f("5m", "rsi_14"), ">", 70), (f("5m", "close"), ">", f("5m", "bbu_20_2")),
                           (f("1h", "er_20"), "<", 0.35)),
        "vwap_dip": cond((f("1m", "vwapdev_60"), ">", 0.6), (f("1m", "rsi_7"), ">", 75)),
        "rsi15m_25": cond((f("15m", "rsi_14"), ">", 75)),
    }
    return {("LONG", k): v for k, v in L.items()} | {("SHORT", k): v for k, v in S.items()}


def _load(symbol):
    from backend.core.backtest.engine import BacktestEngine
    from backend.core.params.builder import build_params
    from backend.core.signals.evaluator import VectorEvaluator, lag_key
    from backend.db.local_pkl import read_manifest
    m = read_manifest(symbol)
    start, end = int(m["start_ts"]), int(m["end_ts"])
    start = max(start, end - 1095 * 86_400_000)
    eng = BacktestEngine(0, 0, symbol, start + 3 * 86_400_000, end)
    sigs = _signals()
    for (side, name), tree in sigs.items():
        eng.add_strategy_flow(f"{side}_{name}", build_params(
            f"{side}_{name}", {"match": [{"condition": tree}], "stop": []}, side, {"market": "perp"}, "cex"))
    eng.load_data()
    df, cols = eng._build_matrix()
    n = len(df)
    vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))
    real = df["is_filled"].to_numpy() == 0
    fires = {k: (vec.tree(t) & real)[real] for k, t in sigs.items()}
    d = df[real]
    return (d["open_time"].to_numpy("int64"), d["open"].to_numpy("f8"), d["high"].to_numpy("f8"),
            d["low"].to_numpy("f8"), d["close"].to_numpy("f8"), fires)


def _gather(a, idx):
    return a[np.clip(idx, 0, len(a) - 1)]


def _simulate(side, fire, o, h, l, c, spacing=5, chunk=3000):
    """Trả {cfg: (entry_bar, exit_bar, ret)} cho mọi cấu hình (chưa lọc chồng lệnh)."""
    n = len(c)
    ev = np.nonzero(fire[:-2])[0]
    ev = ev[ev + max(TTLS) + max(TOS) + 2 < n]
    if len(ev):  # một chuỗi tín hiệu liên tục: lấy mỗi `spacing` phút một sự kiện (giới hạn bộ nhớ)
        keep, last = [], -10**9
        for k, i in enumerate(ev):
            if i - last >= spacing:
                keep.append(k)
                last = i
        ev = ev[np.asarray(keep, dtype=int)]
    out = {}
    for part in np.array_split(ev, max(1, int(np.ceil(len(ev) / chunk)))):
        for cfg, (e, x, r) in _simulate_events(side, part, o, h, l, c).items():
            if cfg in out:
                pe, px, pr = out[cfg]
                out[cfg] = (np.concatenate([pe, e]), np.concatenate([px, x]), np.concatenate([pr, r]))
            else:
                out[cfg] = (e, x, r)
    return out


def _simulate_events(side, ev, o, h, l, c):
    sg = 1.0 if side == "LONG" else -1.0
    out = {}
    if len(ev) == 0:
        return out
    K = max(TTLS)
    win = ev[:, None] + np.arange(1, K + 1)[None, :]
    for off in OFFS:
        lim = c[ev] * (1 - sg * off / 100.0)
        adverse = _gather(l, win) if sg > 0 else _gather(h, win)
        through = (adverse < lim[:, None]) if sg > 0 else (adverse > lim[:, None])
        rejected = (o[ev + 1] <= lim) if sg > 0 else (o[ev + 1] >= lim)  # GTX: sẽ thành taker
        first = np.where(through.any(1), through.argmax(1) + 1, 10**9)
        for ttl in TTLS:
            ok = (first <= ttl) & ~rejected
            # Lệnh không khớp vẫn "chiếm chỗ" tới khi hết hạn (engine chỉ có một lệnh chờ / một vị thế).
            miss_e = ev[~ok]
            miss_busy = miss_e + np.where(rejected[~ok], 1, ttl)
            if not ok.any():
                for sl, tp, to in itertools.product(SLS, TPS, TOS):
                    out[(off, ttl, tp, sl, to)] = (miss_e, miss_busy, np.full(len(miss_e), np.nan))
                continue
            e_idx, fk, lp = ev[ok], first[ok], lim[ok]
            j = e_idx + fk                                     # nến khớp
            T = max(TOS)
            w2 = j[:, None] + np.arange(0, T + 1)[None, :]
            H2, L2, O2 = _gather(h, w2) / lp[:, None], _gather(l, w2) / lp[:, None], _gather(o, w2) / lp[:, None]
            fav = H2 if sg > 0 else 2.0 - L2          # quy về "long": >1 là có lợi
            adv = L2 if sg > 0 else 2.0 - H2
            op = O2 if sg > 0 else 2.0 - O2
            for sl in SLS:
                hit_sl = adv <= 1 - sl / 100.0
                m_sl = np.where(hit_sl.any(1), hit_sl.argmax(1), 10**9)
                for tp in TPS:
                    hit_tp = fav >= 1 + tp / 100.0
                    hit_tp[:, 0] = False                       # không chốt trong nến vừa khớp
                    m_tp = np.where(hit_tp.any(1), hit_tp.argmax(1), 10**9)
                    for to in TOS:
                        sl_first = (m_sl <= m_tp) & (m_sl < to)
                        tp_first = ~sl_first & (m_tp < to)
                        rows = np.arange(len(j))
                        px = np.empty(len(j))
                        fee = np.empty(len(j))
                        ms = np.clip(m_sl, 0, T)
                        if SL_FILL == "extreme":
                            px_sl = np.minimum(1 - sl / 100.0, adv[rows, ms])
                        else:
                            px_sl = np.where(ms > 0, np.minimum(1 - sl / 100.0, op[rows, ms]), 1 - sl / 100.0)
                        mt = np.clip(m_tp, 0, T)
                        px_tp = np.maximum(1 + tp / 100.0, op[rows, mt])
                        px_to = op[rows, np.full(len(j), to)]
                        px[:] = px_to * (1 - SLIP)
                        fee[:] = TAKER
                        px[sl_first] = px_sl[sl_first] * (1 - SLIP)
                        px[tp_first] = px_tp[tp_first]
                        fee[tp_first] = MAKER
                        ret = px - 1.0 - MAKER - fee * px
                        m_exit = np.where(sl_first, m_sl, np.where(tp_first, m_tp, to))
                        ee = np.concatenate([e_idx, miss_e])
                        order = np.argsort(ee, kind="stable")
                        out[(off, ttl, tp, sl, to)] = (ee[order], np.concatenate([j + m_exit, miss_busy])[order],
                                                       np.concatenate([ret, np.full(len(miss_e), np.nan)])[order])
    return out


def _no_overlap(e_idx, x_idx, ret):
    """Một lệnh chờ / một vị thế một lúc, theo thời gian tín hiệu. Sự kiện (khớp hoặc không) chỉ được
    nhận khi đã rảnh; lệnh không khớp chiếm chỗ tới khi hết hạn. KHÔNG được chọn trước lệnh "sẽ khớp"
    (lỗi cũ: bỏ qua lệnh khớp sớm hơn nhưng sắp lỗ, lấy lệnh sâu hơn -> edge giả trên random walk)."""
    keep, last = [], -1
    for k in range(len(e_idx)):
        if e_idx[k] > last:
            keep.append(k)
            last = x_idx[k]
    keep = np.asarray(keep, dtype=int)
    e2, r2 = e_idx[keep], ret[keep]
    filled = np.isfinite(r2)
    return e2[filled], r2[filled]


def _metrics(r):
    if len(r) < 2:
        return {"n": int(len(r))}
    eq = np.cumsum(r)
    mdd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq]))) * 100
    return {"n": int(len(r)), "mean_bps": round(float(r.mean() * 1e4), 2), "win": round(float((r > 0).mean() * 100), 1),
            "sum_pct": round(float(r.sum() * 100), 2), "t": round(float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), 2),
            "mdd_pct": round(mdd, 2)}


def run_asset(symbol):
    t0 = time.time()
    times, o, h, l, c, fires = _load(f"{symbol}@perp")
    split = int(len(times) * DEV_FRAC)
    rows = []
    for (side, name), fire in fires.items():
        res = _simulate(side, fire, o, h, l, c, spacing=30 if name == "always" else 5)
        for cfg, (e, x, r) in res.items():
            e2, r2 = _no_overlap(e, x, r)
            dev, ho = r2[e2 < split], r2[e2 >= split]
            rows.append({"symbol": symbol, "side": side, "signal": name,
                         "cfg": dict(zip(("off", "ttl", "tp", "sl", "timeout"), cfg)),
                         "dev": _metrics(dev), "holdout": _metrics(ho),
                         "dev_days": round((times[split] - times[0]) / 86_400_000, 1),
                         "ho_days": round((times[-1] - times[split]) / 86_400_000, 1)})
    print(f"{symbol}: {len(rows)} cấu hình, {time.time() - t0:.0f}s", flush=True)
    return rows


def _init_grid(round_id):
    from backend.utils.memwatch import worker_init
    worker_init()
    global OFFS, TTLS, TPS, SLS, TOS, SIGNAL_SET
    OFFS, TTLS, TPS, SLS, TOS = (GRIDS[round_id][k] for k in ("OFFS", "TTLS", "TPS", "SLS", "TOS"))
    SIGNAL_SET = round_id


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX")
    ap.add_argument("--workers", default="auto",
                    help="số tiến trình song song; 'auto' = tính theo RAM (gồm cgroup) và CPU")
    ap.add_argument("--round", default="r1", choices=sorted(GRIDS))
    ap.add_argument("--out", default=os.path.join(NORA_ROOT, "data", "_cache", "reports"))
    a = ap.parse_args(argv)
    assets = a.assets.split(",")
    from backend.utils.memwatch import require_memory_limit
    from backend.utils.parallel import resolve_workers
    require_memory_limit("research_maker_scalp")
    # 1500 MB/worker: mỗi job nạp nến 1m cả lịch sử một tài sản + mảng tín hiệu/khớp lệnh cho cả lưới cấu hình (chưa đo thực)
    workers = resolve_workers(a.workers, 1500, "research_maker_scalp")
    global OFFS, TTLS, TPS, SLS, TOS, SIGNAL_SET
    OFFS, TTLS, TPS, SLS, TOS = (GRIDS[a.round][k] for k in ("OFFS", "TTLS", "TPS", "SLS", "TOS"))
    SIGNAL_SET = a.round
    with ProcessPoolExecutor(max_workers=min(workers, len(assets)), initializer=_init_grid,
                             initargs=(a.round,)) as pool:
        rows = list(itertools.chain.from_iterable(pool.map(run_asset, assets)))
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"maker_scalp_{a.round}_{time.strftime('%Y%m%d_%H%M')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    print("lưu:", path, "—", len(rows), "dòng")


if __name__ == "__main__":
    main()
