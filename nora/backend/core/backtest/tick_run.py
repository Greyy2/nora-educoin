"""Backtest THEO TICK cho tài sản DEX (spot AMM, chỉ chân LONG) — job book_backtest với data="tick" (core/backtest/run.py::run_job).

Vì sao: nến 15m không biết trong nến TP hay SL chạm trước, và AMM không có sổ lệnh (không có lệnh limit chờ, khớp luôn là swap có trượt giá theo độ sâu pool).
Mỗi swap on-chain (tick) là một bước khớp lệnh: TickBook (= KernelBook, kernel numba duy nhất + vòng danh mục của engine) chạy từng tick như một vi-nến o=h=l=c = giá biên SAU swap
(mid_price; NaN thì dùng giá khớp). Một engine duy nhất — không có bộ khớp lệnh thứ hai; chỉ hai móc AMM trong kernel (limit_taker, trượt giá theo dự trữ pool; P9.4b T6).

Tín hiệu (đường tính của bot live: live/signals.evaluate, không bản tính thứ hai):
- Khung tín hiệu = nến TRƯỚC cửa sổ (kho nến local, làm khởi động) + nến dựng từ tick TRONG cửa sổ. Dựng bằng nến 1m: 1m kho (< W) + ticks_to_bars(tick, "1m") rồi lấp khe bằng
  fill_missing_1m_candles và resample_from_1m cho từng khung — đúng cách kho sinh các khung từ 1m, nên khung lớn cắt ngang mốc W vẫn đúng và không có bước nhảy ở chỗ nối.
  Cơ sở giá nến tick = giá KHỚP gồm phí pool (mặc định ticks_to_bars) = cơ sở nến GeckoTerminal của kho; thực thi dùng giá BIÊN sau swap.
- Nến cơ sở [t, t+F) đóng lúc t+F; tín hiệu match/stop/dca/vol của nó thành HÀNH ĐỘNG được ở tick ĐẦU TIÊN có timestamp >= t+F+latency_ms (latency mặc định = thời gian block của mạng,
  NETWORKS[mạng]["block_ms"]; nhiều mạng: lấy lớn nhất). Giữa hai lần đóng nến: match=False, stop=False, vol = của nến đóng gần nhất, dca = cổng của nến đóng gần nhất.
  Nhiều nến đóng mà không có tick nào ở giữa: match lấy của nến mới nhất, stop = HOẶC của các nến bị bỏ (không mất tín hiệu thoát). Tín hiệu vào của nến không có swap nào (n_trades=0) bị bỏ.
- Tín hiệu giao ở tick k -> tracker đặt lệnh chờ -> mở vị thế ở ĐẦU tick k+1 (swap kế tiếp thực tế); tương tự tín hiệu thoát. Nến cơ sở đầu tiên có tín hiệu là [W, W+F).
- SL / TP / tầng DCA phản ứng NGAY tại tick giá cắt qua mức (không trễ, giả định bot theo dõi liên tục) và khớp ở GIÁ HIỆN TẠI (hoặc mức nếu chưa vượt) + trượt giá AMM.

Chi phí (kernel core/backtest.py::_amm_impact; vỏ Python core/execute/amm.py): mọi lệnh = swap taker (limit_taker=True): phí = phí pool (manifest["ticks"]["fee_rate"], null -> từ chối) + trượt giá ĐÚNG theo dự trữ pool tại tick đó
(x*y=k hoặc stable x³y+xy³=k, giải số) + gas cố định mỗi swap (NETWORKS[mạng]["swap_gas_usd"] hoặc tham số gas_usd) quy theo danh nghĩa.
Giới hạn đã biết: một lệnh của ta không làm đổi dự trữ cho tick kế (không mô hình hoá tác động lên pool); vốn MTM đánh giá theo giá biên, chưa trừ chi phí thoát.
Kết quả: cùng lược đồ run.run (số đo danh mục, trade_list, equity_curve lấy mẫu mỗi NẾN CƠ SỞ, daily_nav, config) + config.data="tick", tick_window, latency_ms, cost_model, tick_stats.
"""
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.backtest import dex
from backend.core.backtest.portfolio import aggregate_positions
from backend.core.backtest.run import result_payload
from backend.core.data.resampler import fill_missing_1m_candles, resample_from_1m, ticks_to_bars
from backend.core.backtest import KernelBook
from backend.core.execute.amm import AmmImpact
from backend.db.local_pkl import _frame_ms

MINUTE_MS = 60_000
CANDLE_COLS = ["open_time", "open", "high", "low", "close", "volume", "is_filled"]


class TickBook(KernelBook):
    """Sổ của backtest tick = KernelBook (kernel numba, P9.4b T6) với pool AMM gắn cho mọi tài sản: mọi lệnh là swap taker (limit_taker), phí = phí pool,
    trượt giá theo dự trữ pool mỗi tick (`set_amm` trước mỗi `step_bar`). Giữ mọi hàng kết quả (record_full) để dựng PositionModel (symbol, strategy_id) cho metrics."""

    ALLOW_EQUAL_T = True        # nhiều swap một block cùng timestamp

    def __init__(self, strategies, symbols, base_frame, capital, risk, trade_start, models: List[AmmImpact]):
        super().__init__(strategies, symbols, base_frame, capital, risk, trade_start, record_full=True, record_events=False,
                         amm=[{"fee": m.fee, "stable": m.stable, "gas": m.gas_usd} for m in models])

    def results(self) -> List[Any]:
        """Vị thế đã đóng theo thứ tự đóng (PositionModel; sau close_all)."""
        return self.full_objects()[0]


def _signal_frames(q: str, strategies: List[Dict[str, Any]], base_frame: str, w: int, nb: int, frame_ms: int, ticks: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Khung tín hiệu của tài sản: 1m kho (< w) nối 1m dựng từ tick (>= w) tới hết nến cơ sở cuối của cửa sổ, lấp khe, resample từng khung cần.
    Nến lấp (is_filled) vẫn là quan sát — như mọi khung kho."""
    from backend.core.data.loader import CandleLoader
    from backend.live import signals as ls
    stored = CandleLoader(q, frame="1m", use_cache=False).load_data(0, w - 1)
    if "is_filled" not in stored.columns:
        stored = stored.assign(is_filled=0)
    tb = ticks_to_bars(ticks, "1m")[CANDLE_COLS]
    last_min = w + nb * frame_ms - MINUTE_MS
    if int(tb["open_time"].iloc[-1]) < last_min:   # vài phút cuối cửa sổ không có swap: thêm phút cuối (O=H=L=C = close trước, volume 0) để lưới phủ tới hết nến cuối
        c = float(tb["close"].iloc[-1])
        tb = pd.concat([tb, pd.DataFrame([{"open_time": last_min, "open": c, "high": c, "low": c, "close": c, "volume": 0.0, "is_filled": 0}])], ignore_index=True)
    hybrid = fill_missing_1m_candles(pd.concat([stored[CANDLE_COLS], tb], ignore_index=True))
    return {fr: resample_from_1m(hybrid, fr) for fr in ls.required_frames(q, strategies, base_frame)}


class _Signals:
    """Tín hiệu của một tài sản trên lưới nến cơ sở của cửa sổ: giao tại tick đầu tiên >= đóng nến + latency."""

    def __init__(self, q: str, strategies, base_frame: str, w: int, nb: int, ticks: pd.DataFrame, latency: int, frame_ms: int):
        from backend.live import signals as ls
        self.v = ls.evaluate(q, strategies, _signal_frames(q, strategies, base_frame, w, nb, frame_ms, ticks), base_frame)
        self.i0 = int(np.searchsorted(self.v["t"], w))
        if self.i0 + nb > len(self.v["t"]) or int(self.v["t"][self.i0]) != w:
            raise ValueError(f"{q}: khung {base_frame} không phủ cửa sổ tick từ {w}")
        bars = ticks_to_bars(ticks, base_frame).set_index("open_time")["n_trades"]
        self.traded = bars.reindex(w + np.arange(nb, dtype=np.int64) * frame_ms).fillna(0).to_numpy() > 0
        self.w, self.nb, self.latency, self.frame_ms = w, nb, latency, frame_ms
        self.last = -1
        self.held = [{"match": False, "stop": False, "vol": None, "dca": True} for _ in self.v["entries"]]
        self.ignored_no_trade = self.skipped = 0

    def at(self, ts: int) -> List[Dict[str, Any]]:
        """Tín hiệu giao ở tick thời điểm ts (khác `held` chỉ ở tick đầu tiên sau khi một nến đóng)."""
        from backend.live.bot import _bar_sig
        j = min((ts - self.latency - self.w) // self.frame_ms - 1, self.nb - 1)
        if j <= self.last:
            return self.held
        cur = _bar_sig(self.v, self.i0 + j)
        for k, e in enumerate(self.v["entries"]):
            cur[k]["stop"] = bool(e["stop"][self.i0 + self.last + 1:self.i0 + j + 1].any())   # nến bị bỏ qua (không tick ở giữa): giữ tín hiệu thoát
            if cur[k]["match"] and not self.traded[j]:
                cur[k]["match"] = False
                self.ignored_no_trade += 1
        self.skipped += max(0, j - self.last - 1)
        self.last = j
        self.held = [{**d, "match": False, "stop": False} for d in cur]
        return cur


def _tick_arrays(q: str, w: int, e: int, name: str) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Tick của tài sản trong [w, e]: ts, mid (giá biên; NaN -> giá khớp), dự trữ + quote_usd điền tiến/lùi. + số tick phải dùng giá dự phòng."""
    from backend.db.tick_storage import load_ticks_df
    tk = load_ticks_df(q, w, e)
    if tk.empty:
        raise ValueError(f"{name}: không có tick trong cửa sổ {w}..{e}")
    for col in ("reserve_base", "reserve_quote", "quote_usd", "mid_price", "block_number", "log_index"):
        if col not in tk.columns:
            raise ValueError(f"{name}: tick thiếu cột {col} — crawl lại tick (pool phải phát log Sync để có dự trữ)")
    if tk[["reserve_base", "reserve_quote"]].isna().all().any():
        raise ValueError(f"{name}: tick không có dự trữ pool (không có log Sync, vd. pool v3) — không mô hình hoá được AMM")
    fb = {"reserve_ffill": int(tk[["reserve_base", "reserve_quote"]].isna().any(axis=1).sum()), "mid_fallback": int(tk["mid_price"].isna().sum())}
    tk = tk.assign(mid=tk["mid_price"].fillna(tk["price"]))
    for col in ("reserve_base", "reserve_quote", "quote_usd"):
        tk[col] = tk[col].ffill().bfill()
    if tk["quote_usd"].isna().any():
        raise ValueError(f"{name}: tick thiếu quote_usd")
    return tk, fb


def run_tick(items, symbols: List[str], start: Optional[int], end: Optional[int], rpt: float, risk: Dict[str, Any], stop_fill: str, base_frame: str,
             capital: float, latency_ms: Optional[int] = None, gas_usd: Optional[float] = None) -> Dict[str, Any]:
    """items [(id chiến lược, tham số)], symbols = ký hiệu DEX engine ("dex:AERO"), start/end ms (None = hết độ phủ tick; cắt theo độ phủ, xem dex.tick_window)
    -> kết quả cùng lược đồ run.run. latency_ms / gas_usd None = theo mạng của pool (tạo từ NETWORKS)."""
    from backend.core.data.tick_crawler import network_config
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import BY_ID, materialize
    from backend.utils.memwatch import peak_rss_mb
    t0 = time.time()
    dex.require_long_legs([cid for cid, _ in items])
    infos = [dex.pool_info(s) for s in symbols]
    for i in infos:
        dex.check_amm_pool(i)
    nets = {i["qualified"]: network_config(i["network"]) for i in infos}
    frame_ms = _frame_ms(base_frame)
    if frame_ms <= 0:
        raise ValueError(f"khung cơ sở không hợp lệ: {base_frame!r}")
    latency = int(latency_ms) if latency_ms is not None else max(int(n["block_ms"]) for n in nets.values())
    w, e = dex.tick_window(infos, start, end, frame_ms)
    nb = (e - w) // frame_ms
    models = [AmmImpact(i["fee_rate"], i["stable"], float(gas_usd) if gas_usd is not None else float(nets[i["qualified"]]["swap_gas_usd"])) for i in infos]

    fee = max(i["fee_rate"] for i in infos)
    strategies = [materialize(BY_ID[cid], lift_frames(BY_ID[cid], prm, base_frame), stop_fill=stop_fill, risk_per_trade_pct=rpt, **dex.SPOT_POSITION,
                              fee_rate=fee, maker_fee_rate=fee, slippage_rate=0.0, limit_through_pct=0.0) for cid, prm in items]
    book = TickBook(strategies, [i["qualified"] for i in infos], base_frame, capital, risk, w, models)

    data, sigs, stats = [], [], {"reserve_ffill": 0, "mid_fallback": 0}
    for si, i in enumerate(infos):
        tk, fb = _tick_arrays(i["qualified"], w, e, i["symbol"])
        for k in stats:
            stats[k] += fb[k]
        sigs.append(_Signals(i["qualified"], strategies, base_frame, w, nb, tk, latency, frame_ms))
        data.append(pd.DataFrame({"ts": tk["timestamp_ms"], "bn": tk["block_number"], "li": tk["log_index"], "si": si, "mid": tk["mid"],
                                  "rb": tk["reserve_base"], "rq": tk["reserve_quote"], "qu": tk["quote_usd"]}))
    feed = pd.concat(data, ignore_index=True).sort_values(["ts", "bn", "li", "si"], kind="stable")

    curve: List[Dict[str, float]] = []
    cur_b, eq, worst_bar = 0, float(capital), float("inf")

    def flush(upto: int) -> None:
        nonlocal cur_b, worst_bar
        while cur_b < upto:
            curve.append({"time": w + cur_b * frame_ms, "equity": eq, "equity_worst": min(eq, worst_bar)})
            cur_b, worst_bar = cur_b + 1, float("inf")

    t_last = w
    for ts, si, mid, rb, rq, qu in zip(feed["ts"].tolist(), feed["si"].tolist(), feed["mid"].tolist(), feed["rb"].tolist(), feed["rq"].tolist(), feed["qu"].tolist()):
        flush((ts - w) // frame_ms)
        book.set_amm(si, rb, rq, qu)
        sym = infos[si]["qualified"]
        book.step_bar(ts, {sym: (mid, mid, mid, mid)}, {sym: sigs[si].at(ts)})
        eq, worst = book.mtm()
        worst_bar = min(worst_bar, worst)
        t_last = ts
    book.close_all(t_last)
    eq, worst = book.mtm()
    worst_bar = min(worst_bar, worst)
    flush((t_last - w) // frame_ms + 1)

    fills = book.taker_slippage()
    closed = book.results()
    by_strategy, by_symbol = aggregate_positions(closed)
    res = {"positions": closed, "equity_curve": curve, "final_equity": book.ledger.equity, "initial_capital": float(capital), "by_strategy": by_strategy,
           "by_symbol": by_symbol, "rejected_for_capital": book.ledger.rejected, "rejected_for_risk": book.rejected_for_risk,
           "risk_blocked_attempts": book.rejected_for_risk, "halted_at": book.halted_at, "risk": dict(risk)}
    out = result_payload(res, w, e)
    pools = {i["symbol"]: {"network": i["network"], "pool_type": i["pool_type"], "stable": i["stable"], "fee_rate": i["fee_rate"], "fee_source": i["fee_source"],
                           "gas_usd": m.gas_usd} for i, m in zip(infos, models)}
    out["config"] = {
        "strategies": [{"id": cid, "params": prm} for cid, prm in items], "symbols": [i["symbol"] for i in infos], "risk_per_trade_pct": rpt,
        "stop_fill": stop_fill, "risk": res["risk"], "start": w, "end": e, "initial_capital": res["initial_capital"], "timeframe": base_frame,
        "venue": "dex", "data": "tick", "latency_ms": latency,
        "tick_window": {"start": w, "end": e, "requested_start": start, "requested_end": end, "bars": nb, "ticks": int(len(feed))},
        "cost_model": {"model": "amm_exact", "pools": pools, "fills": "mọi lệnh = swap taker (không có lệnh limit chờ): phí pool + trượt giá theo dự trữ pool tại tick + gas",
                       "impact": "constant-product x*y=k (volatile) hoặc x³y+xy³=k giải số (stable), không gồm phí pool", "price_basis": {"signals": "price (giá khớp gồm phí)", "execution": "mid_price (giá biên sau swap)"}},
    }
    out["tick_stats"] = {"signal_bars": nb, "signal_bars_skipped": sum(s.skipped for s in sigs), "entries_ignored_no_trade_bar": sum(s.ignored_no_trade for s in sigs),
                         "ticks_reserve_filled": stats["reserve_ffill"], "ticks_mid_fallback": stats["mid_fallback"], "taker_fills": len(fills),
                         "avg_fill_slippage_bps": round(float(np.mean(fills)) * 1e4, 4) if len(fills) else None}
    out["final_equity"] = round(res["final_equity"], 2)
    out["meta"] = {"wall_s": round(time.time() - t0, 1), "peak_rss_mb": round(peak_rss_mb(), 1)}
    return out
