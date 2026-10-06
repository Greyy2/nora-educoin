"""Kiểm nhanh logic BOT SÀN (demo/live) so với engine, không cần chờ lệnh thật: phát lại lịch sử nến OKX qua một sàn GIẢ LẬP khớp lệnh
như sàn thật (lệnh market khớp ở giá mở nến kế; lệnh chờ — SL điều kiện, TP limit, tầng DCA post-only — khớp khi giá trong nến đi qua mức,
SL/TP KHÔNG tự cập nhật khi tầng DCA khớp cho tới bước sau của bot). Bóng paper trong bot = engine. So từng lệnh bằng live/compare.py.

Lệch ở đây = khác biệt do CÁCH BOT ĐẶT LỆNH TRÊN SÀN (không phải do sàn): trailing kiểm cuối nến, SL/TP đặt lại chậm sau khi dồn tầng, ...
Chạy: backend/utils/ops/run_limited.sh --no-lock -- test/scripts/check_bot_exec_replay.py [--days 120] [--book main]
"""
import argparse
import json
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
FEE_TAKER, FEE_MAKER, SLIP = 0.0005, 0.0002, 0.0002
THROUGH = 0.0005          # lệnh limit phải đi qua mức 0,05% mới khớp (như engine mặc định)


class SimExchange:
    """Sàn giả lập cùng giao diện OkxAdapter mà bot dùng (khối lượng theo coin)."""

    def __init__(self, capital: float):
        self.cash = capital
        self.pos = {}          # sym -> {"qty" (có dấu), "avg", "open_t", "fees", "realized"}
        self.orders = {}       # sym -> [{"kind": sl|tp|dca, "side", "qty", "px"}]
        self.open_px, self.last_close, self.closed, self.now = {}, {}, {}, 0
        self.on_fill = None    # bot.watch: bot đối soát nhanh ngay sau khi tầng DCA khớp (vòng watch 10 giây của bot thật)

    # ── giao diện bot ──
    def prepare(self, sym, lev):
        pass

    def positions(self):
        return {s: (p["qty"], p["avg"]) for s, p in self.pos.items() if abs(p["qty"]) > 1e-12}

    def equity(self):
        un = sum((self.last_close.get(s, p["avg"]) - p["avg"]) * p["qty"] for s, p in self.pos.items())
        return self.cash + un

    def _fill(self, sym, side, qty, px, fee):
        sgn = 1 if side == "LONG" else -1
        p = self.pos.setdefault(sym, {"qty": 0.0, "avg": 0.0, "open_t": self.now, "fees": 0.0, "realized": 0.0, "entry_avg": px, "peak": px})
        new = p["qty"] + sgn * qty
        if p["qty"] == 0 or (p["qty"] > 0) == (sgn > 0):          # mở / dồn
            p["avg"] = (p["avg"] * abs(p["qty"]) + px * qty) / abs(new)
            p["entry_avg"] = p["avg"]                              # như openAvgPx của OKX: giá vào TB gồm mọi tầng
        else:                                                      # đóng (một phần / toàn bộ)
            close_q = min(qty, abs(p["qty"]))
            p["realized"] += (px - p["avg"]) * close_q * (1 if p["qty"] > 0 else -1)
            self.cash += (px - p["avg"]) * close_q * (1 if p["qty"] > 0 else -1)
        p["qty"] = new if abs(new) > 1e-9 * max(1.0, abs(p["qty"])) else 0.0
        c = px * qty * fee
        p["fees"] += c
        self.cash -= c
        if p["qty"] == 0.0:
            self.closed[sym] = {"close_price": px, "open_price": p["entry_avg"], "pnl": p["realized"] - p["fees"], "fee": -p["fees"],
                                "exchange_close_time": self.now}
            del self.pos[sym]
            self.orders.pop(sym, None)

    def market_open(self, sym, side, qty):
        px = self.open_px[sym] * (1 + SLIP if side == "LONG" else 1 - SLIP)
        self._fill(sym, side, qty, px, FEE_TAKER)
        return self.pos[sym]["avg"]

    def close_market(self, sym):
        p = self.pos.get(sym)
        if p:
            side = "SHORT" if p["qty"] > 0 else "LONG"
            px = self.open_px[sym] * (1 - SLIP if p["qty"] > 0 else 1 + SLIP)
            self._fill(sym, side, abs(p["qty"]), px, FEE_TAKER)

    def place_sl(self, sym, side, qty, trigger):
        self.orders.setdefault(sym, []).append({"kind": "sl", "side": side, "qty": qty, "px": trigger})

    def place_tp(self, sym, side, qty, px):
        self.orders.setdefault(sym, []).append({"kind": "tp", "side": side, "qty": qty, "px": px})

    def place_post_only(self, sym, side, qty, px):
        self.orders.setdefault(sym, []).append({"kind": "dca", "side": side, "qty": qty, "px": px})

    def place_trailing(self, sym, side, qty, callback_pct, active_px):
        self.orders.setdefault(sym, []).append({"kind": "trail", "side": side, "qty": qty, "cb": callback_pct / 100.0, "px": active_px})

    def cancel_all(self, sym):
        self.orders.pop(sym, None)

    def closed_since(self, sym, since):
        return self.closed.pop(sym, {})

    # ── một nến của sàn: khớp lệnh chờ ──
    def bar(self, sym, o, h, l, c):
        self.last_close[sym] = c
        for _ in range(10):
            p = self.pos.get(sym)
            if not p:
                return
            long_ = p["qty"] > 0
            adverse, fav = (l, h) if long_ else (h, l)
            hit = []
            for od in self.orders.get(sym, []):
                if od["kind"] == "sl" and ((adverse <= od["px"]) if long_ else (adverse >= od["px"])):
                    hit.append((od["px"], 0, od))
                elif od["kind"] == "trail" and ((p["peak"] >= od["px"]) if long_ else (p["peak"] <= od["px"])):   # đã kích hoạt (đỉnh tới nến trước)
                    lv = p["peak"] * (1 - od["cb"]) if long_ else p["peak"] * (1 + od["cb"])
                    if (adverse <= lv) if long_ else (adverse >= lv):
                        hit.append((lv, 0, od))
                elif od["kind"] == "dca" and ((adverse <= od["px"] * (1 - THROUGH)) if long_ else (adverse >= od["px"] * (1 + THROUGH))):
                    hit.append((od["px"], 1, od))
            if hit:                                   # mức gặp trước khi giá đi ngược (long: cao nhất trước)
                px, _, od = (max(hit, key=lambda x: (x[0], -x[1])) if long_ else min(hit, key=lambda x: (x[0], x[1])))
                self.orders[sym].remove(od)
                if od["kind"] in ("sl", "trail"):
                    fill = min(px, o) if long_ else max(px, o)
                    self._fill(sym, "SHORT" if long_ else "LONG", abs(p["qty"]), fill * (1 - SLIP if long_ else 1 + SLIP), FEE_TAKER)
                    return
                self._fill(sym, "LONG" if long_ else "SHORT", od["qty"], min(od["px"], o) if long_ else max(od["px"], o), FEE_MAKER)
                if self.on_fill:
                    self.on_fill(self.now)
                continue
            for od in list(self.orders.get(sym, [])):  # chốt lời: limit reduce-only, khối lượng như lúc đặt (có thể nhỏ hơn vị thế sau DCA)
                if od["kind"] == "tp" and ((fav >= od["px"] * (1 + THROUGH)) if long_ else (fav <= od["px"] * (1 - THROUGH))):
                    self.orders[sym].remove(od)
                    self._fill(sym, "SHORT" if long_ else "LONG", min(od["qty"], abs(p["qty"])), max(od["px"], o) if long_ else min(od["px"], o),
                               FEE_MAKER)
                    break
            if sym in self.pos:                        # đỉnh/đáy có lợi cập nhật cuối nến (như engine)
                q = self.pos[sym]
                q["peak"] = max(q["peak"], h) if q["qty"] > 0 else min(q["peak"], l)
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--book", default="main", choices=("main", "explore"))
    ap.add_argument("--trace", default="", help="SYM,YYYY-MM-DD: in sự kiện bot + lệnh paper của mã quanh ngày đó")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    from backend.db.data_layout import default_data_root
    from backend.live import bot as lb
    from backend.live import signals as ls
    from backend.live.compare import compare_trades
    from backend.live.exchange import Filters
    book = lb.load_book(kind=a.book, mode="paper")
    strategies, tf = lb.book_strategies(book), book["timeframe"]
    fms = {"15m": 900_000, "1h": 3_600_000}[tf]
    syms = [s.split("@")[0] for s in book["universe"]]
    root = os.path.join(default_data_root(), "cex")
    full = {}
    for s in syms:
        need = ls.required_frames(f"{s}@perp", strategies, tf)
        fr = {f: pd.read_pickle(os.path.join(root, s, "perp", f"{f}.pkl")) for f in need}
        full[s] = ls.evaluate(f"{s}@perp", strategies, fr, tf)
    t_end = min(int(v["t"][-1]) for v in full.values())
    t0 = t_end - a.days * 86_400_000
    sim = SimExchange(10_000.0)
    logs = []
    state = lb.State(os.path.join(os.environ.get("TMPDIR", "/tmp"), "nora_replay_state.json"))
    state.d = {"positions": {}, "last_close": {}, "peak_equity": 10_000.0, "halted": False, "last_bar": None, "trades": [], "external": []}
    bot = lb.Bot(book, "demo", sim, state, logs.append, {s: Filters(1e-9, 1e-9, 0.0, 0.0) for s in syms}, None, 10_000.0)
    sim.on_fill = bot.watch
    idx = {s: {int(t): i for i, t in enumerate(v["t"])} for s, v in full.items()}
    grid = sorted(t for t in idx[syms[0]] if t0 <= t <= t_end)
    tr_sym, tr_lo, tr_hi = "", 0, 0
    if a.trace:
        tr_sym, day = a.trace.split(",")
        tr_lo = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
        tr_hi = tr_lo + 86_400_000
    for k in range(1, len(grid)):
        now, prev = grid[k], grid[k - 1]
        sig = {}
        for s, v in full.items():
            i = idx[s].get(prev)
            if i is None:
                continue
            sig[s] = {**{kk: v[kk][: i + 1] for kk in ("t", "open", "high", "low", "close")},
                      "entries": [{**e, "match": e["match"][: i + 1], "stop": e["stop"][: i + 1],
                                   "vol": e["vol"][: i + 1] if e["vol"] is not None else None,
                                   "dca": e["dca"][: i + 1] if e.get("dca") is not None else None} for e in v["entries"]]}
            j = idx[s].get(now)
            if j is not None:
                sim.open_px[s] = float(v["open"][j])
        sim.now = now
        lb._now_ms = lambda: now                      # thời điểm sự kiện = nến đang phát lại
        bot.step(now, sig, {})
        if a.trace and tr_lo <= now <= tr_hi:
            print("  ORD", pd.Timestamp(now, unit="ms"), tr_sym, sim.pos.get(tr_sym, {}).get("qty"), sim.orders.get(tr_sym), flush=True)
        for s, v in full.items():                     # nến `now` diễn ra trên sàn: lệnh chờ khớp
            j = idx[s].get(now)
            if j is not None:
                sim.bar(s, float(v["open"][j]), float(v["high"][j]), float(v["low"][j]), float(v["close"][j]))
    ex, pa = bot.state.d["trades"], bot.paper.trades
    out = compare_trades(ex, pa, tf)
    s = out["summary"]
    print(f"sổ {a.book} ({tf}), {a.days} ngày, {len(syms)} mã: lệnh sàn giả lập {len(ex)}, lệnh paper (engine) {len(pa)}")
    print("TÓM TẮT:", json.dumps(s, ensure_ascii=False))
    print("Lý do thoát (sàn / paper) của cặp lệch tầng hoặc lệch lý do:")
    diff = Counter((str(q["reason"][0])[:22], str(q["reason"][1])[:22]) for q in out["pairs"]
                   if q["layers"][0] != q["layers"][1] or (q["close_bps"] or 0) > 5)
    for (r0, r1), n in diff.most_common(8):
        print(f"   {n:4d}  sàn: {r0:24s} paper: {r1}")
    big = sorted([q for q in out["pairs"] if q["close_bps"] is not None], key=lambda q: -abs(q["close_bps"]))[:5]
    for q in big:
        print("   lệch lớn:", q["symbol"], q["strategy"], pd.Timestamp(q["entry_time"], unit="ms"), "close_bps", q["close_bps"],
              "tầng", q["layers"], "lý do", q["reason"])
    if a.trace:
        sym, day = a.trace.split(",")
        lo = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000) - 86_400_000
        hi = lo + 4 * 86_400_000
        for e in logs:
            if e.get("symbol") == sym and lo <= int(e.get("t") or 0) <= hi:
                print("  BOT", {k: v for k, v in e.items() if k not in ("t",)})
        for t in pa:
            if t["symbol"].startswith(sym) and lo <= t["enter_time"] <= hi:
                print("  PAPER", t)
    kinds = Counter(e.get("kind") for e in logs)
    print("Sự kiện bot:", dict(kinds))


if __name__ == "__main__":
    main()
