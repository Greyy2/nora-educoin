"""Backtest DANH MỤC: nhiều tài sản × nhiều chiến lược trên MỘT sổ vốn và MỘT dòng thời gian.

Vì sao: tham số không được chỉnh theo từng tài sản. Mỗi chiến lược có một bộ tham số dùng chung
(SL/TP/trailing theo bội số ATR, khối lượng theo rủi ro), chạy trên cả vũ trụ tài sản, và vốn được
phân bổ theo rủi ro ở cấp danh mục:

- Sổ vốn chung (CapitalLedger): mọi vị thế của mọi tài sản giữ chỗ ký quỹ + phí từ cùng một quỹ.
- Giới hạn danh mục (RiskConfig), kiểm tra lúc vào lệnh:
    max_positions        số vị thế mở đồng thời tối đa (toàn danh mục)
    max_per_symbol       số vị thế tối đa trên một tài sản (mọi chiến lược cộng lại)
    max_gross_exposure   Σ giá trị danh nghĩa vị thế mở / vốn — lệnh mới bị THU NHỎ cho vừa phần còn lại
    kill_switch_dd_pct   vốn MTM sụt từ đỉnh >= ngưỡng -> đóng hết (market) và dừng giao dịch (như bot thật)
- Thứ tự trong một phút: các tài sản xử lý theo thứ tự cố định của danh sách (tái lập được).

Mỗi tài sản dùng lại BacktestEngine để nạp dữ liệu, tính kernel đa khung (chỉ nến đã đóng) và funding,
nên ngữ nghĩa từng vị thế giống hệt backtest đơn tài sản (test đối chiếu trong test_portfolio_engine.py).
"""
import contextlib
import io
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.core.backtest import shared_data
from backend.core.backtest.engine import BacktestEngine
from backend.core.backtest.execution import CapitalLedger, PositionTracker
from backend.core.signals.evaluator import VectorEvaluator, lag_key
from backend.utils.lru import ByteLRU, env_mb


@dataclass
class RiskConfig:
    max_positions: int = 8
    max_per_symbol: int = 1
    max_gross_exposure: float = 3.0
    kill_switch_dd_pct: float = 30.0   # 0 = tắt

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RiskConfig":
        d = dict(d or {})
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# Bộ nhớ đệm dữ liệu theo tiến trình: (symbol, start, end, refs, perp) -> mảng giá + cột kernel + funding.
# Khi tối ưu ngưỡng tín hiệu / tham số vị thế, cột kernel không đổi nên chỉ tính một lần.
# Giới hạn theo BYTE (NORA_DATA_CACHE_MB, mặc định 1500 MB), có khoá cho API đa luồng.
_DATA_CACHE = ByteLRU(env_mb("NORA_DATA_CACHE_MB", 1500))


def data_cache_clear() -> None:
    """Xóa toàn bộ _DATA_CACHE — gọi giữa các chiến lược ứng viên để giải phóng RAM."""
    _DATA_CACHE.clear()


def _strategy_flow(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": strategy["side"], "match": [{"condition": strategy["tree"]}], "stop": strategy.get("stop") or []}


class PortfolioEngine:
    MTM_SAMPLE_MINUTES = 60
    # Bỏ qua phút "rảnh" (không vị thế mở, không lệnh chờ, không tín hiệu vào) — kết quả BIT-IDENTICAL (test golden + test bật/tắt).
    _SKIP_IDLE = True

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True):
        """strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (backend/core/backtest/shared_data.py); mặc định env NORA_SHARED_DATA_DIR.
        Có thì _load_symbol ưu tiên đọc mmap (chỉ đọc) thay vì tự dựng; không thấy khoá thì dựng như cũ."""
        if not symbols or not strategies:
            raise ValueError("Cần ít nhất một tài sản và một chiến lược")
        ids = [s["id"] for s in strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("id chiến lược phải khác nhau")
        self.symbols = list(symbols)
        self.strategies = strategies
        self.start_ts, self.end_ts = int(start_ts), int(end_ts)
        self.trade_start_ts = int(trade_start_ts if trade_start_ts is not None else start_ts)
        self.initial_capital = float(initial_capital)
        self.risk = risk or RiskConfig()
        self.venue = venue
        self.use_cache = use_cache
        self.shared_dir = shared_dir or os.environ.get("NORA_SHARED_DATA_DIR") or None
        self.ledger = CapitalLedger(self.initial_capital)
        self.books: List[Dict[str, Any]] = []   # mỗi tài sản: dữ liệu + trackers
        self.closed_positions: List[Any] = []
        self.orders: List[Any] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_risk = 0           # số PHÚT lệnh vào bị chặn bởi giới hạn rủi ro (giữ nguyên nghĩa, golden dựa vào đây)
        self.risk_blocked_attempts = 0       # số LẦN vào lệnh bị chặn: các phút liên tiếp của cùng một tracker tính là một lần
        self.bar_hook = None  # (test) gọi sau mỗi phút: hook(engine, t)
        self.close_at_end = close_at_end
        self.last_close: Dict[str, float] = {}   # giá đóng cửa cuối của từng tài sản (đặt khi run() xong)

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def _make_trackers(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, PositionTracker]]]:
        from backend.core.backtest.params_builder import build_params
        eng = BacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital)
        eng.ledger = ledger
        pairs = []
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            name = f"{st['side']}_{st['id']}"
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, symbol=symbol))
            pairs.append((st, eng.trackers[-1]))
        return eng, pairs

    @staticmethod
    def _refs_signature(eng: BacktestEngine):
        return tuple(sorted((f, tuple(sorted(r))) for f, r in eng._refs_by_frame().items()))

    def _cache_key(self, symbol: str, eng: BacktestEngine) -> tuple:
        return (symbol, self.start_ts, self.end_ts, self._refs_signature(eng), any(tr.market == "perp" for tr in eng.trackers))

    def _shared_key(self, symbol: str, eng: BacktestEngine) -> Optional[str]:
        sym, start, end, refs, perp = self._cache_key(symbol, eng)
        return shared_data.data_key(sym, start, end, refs, perp)

    def _build_symbol_data(self, eng: BacktestEngine) -> Dict[str, Any]:
        """Dựng `data` của một tài sản (nến thật 1m + cột kernel + funding), không đụng cache."""
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix()
        real = df1["is_filled"].to_numpy() == 0
        return {
            "t": df1["open_time"].to_numpy(dtype="int64")[real],
            "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
            "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
            "cols": {k: v[real] for k, v in cols.items()},
            "f_t": eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64"),
            "f_r": eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([]),
        }

    def _load_symbol(self, symbol: str, eng: BacktestEngine) -> Dict[str, Any]:
        if self.shared_dir:  # mmap chỉ đọc do tiến trình cha dựng — KHÔNG đưa vào _DATA_CACHE (không nhân bản RAM)
            skey = self._shared_key(symbol, eng)
            shared = shared_data.load(self.shared_dir, skey) if skey else None
            if shared is not None:
                return shared
        key = self._cache_key(symbol, eng)
        if self.use_cache:
            cached = _DATA_CACHE.get(key)
            if cached is not None:
                return cached
        data = self._build_symbol_data(eng)
        if self.use_cache:
            arrays = [data[k] for k in ("t", "o", "h", "l", "c", "f_t", "f_r")] + list(data["cols"].values())
            _DATA_CACHE.put(key, data, sum(a.nbytes for a in arrays))
        return data

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_trackers(sym, self.ledger)
            if not pairs:   # không chiến lược nào chạy trên tài sản này (chỉ xảy ra khi dùng khoá "symbols")
                continue
            # Cổng chất lượng dữ liệu BẮT BUỘC (synthetic / sai sha256 / thiếu dữ liệu -> từ chối); có cache theo file nên rẻ khi gọi lại.
            # Tiến trình cha của CLI đã gọi trước khi fork pool -> worker thừa kế cache, không đọc lại 1m.
            from backend.core.data.quality_gate import require_data_ok
            require_data_ok([sym])
            data = self._load_symbol(sym, eng)
            n = len(data["t"])
            cols = data["cols"]
            vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))
            entries = []
            for st, tr in pairs:
                vcol = BacktestEngine.vol_column(tr)
                entries.append({
                    "strategy": st["id"], "tracker": tr,
                    "match": vec.tree(tr.match_tree), "stop": vec.tree(tr.stop_tree),
                    "vol": cols.get(vcol) if vcol else None,
                })
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── Giới hạn rủi ro ────────────────────────────────────────────────────
    def _gross_notional(self, last_close: List[float]) -> float:
        total = 0.0
        for b, book in enumerate(self.books):
            px = last_close[b]
            if px != px:  # NaN: tài sản chưa có nến nào
                continue
            for e in book["entries"]:
                if e["tracker"].is_open:
                    total += e["tracker"].qty * px
        return total

    def _open_counts(self) -> Tuple[int, List[int]]:
        per = [sum(1 for e in book["entries"] if e["tracker"].is_open) for book in self.books]
        return sum(per), per

    # ─── Chạy ───────────────────────────────────────────────────────────────
    def run(self) -> None:
        if not self.books:
            self.load_data()
        grid = np.unique(np.concatenate([b["data"]["t"] for b in self.books]))
        idx_maps = []
        for book in self.books:
            m = np.full(len(grid), -1, dtype=np.int64)
            m[np.searchsorted(grid, book["data"]["t"])] = np.arange(len(book["data"]["t"]))
            idx_maps.append(m)
        last_close = [float("nan")] * len(self.books)
        last_low = [float("nan")] * len(self.books)
        last_high = [float("nan")] * len(self.books)
        last_open = [float("nan")] * len(self.books)
        peak_mtm = self.initial_capital
        last_sample = None
        cap = self.risk.max_gross_exposure
        kill = self.risk.kill_switch_dd_pct / 100.0 if self.risk.kill_switch_dd_pct else 0.0

        n_grid = len(grid)
        skip = self._SKIP_IDLE and self.bar_hook is None   # bar_hook (test) cần kiểm bất biến mỗi phút
        if skip:
            # Phút có tín hiệu vào của BẤT KỲ chiến lược × tài sản nào, tính từ trade_start_ts (trước đó on_bar không làm gì)
            sig_any = np.zeros(n_grid, dtype=bool)
            for book in self.books:
                pos = np.searchsorted(grid, book["data"]["t"])
                for e in book["entries"]:
                    sig_any[pos] |= e["match"]
            cand = np.flatnonzero(sig_any & (grid >= self.trade_start_ts))
        busy = False  # vòng trước còn tracker mở / lệnh chờ?

        g = 0
        while g < n_grid:
            if skip and not busy and not self._any_active():
                land = n_grid if self.halted_at is not None else (
                    int(cand[np.searchsorted(cand, g)]) if np.searchsorted(cand, g) < len(cand) else n_grid)
                if land > g:  # g..land-1: không có gì xảy ra ngoài funding trượt, last_*, mẫu vốn theo giờ
                    peak_mtm = max(peak_mtm, self.ledger.equity)
                    last_sample = self._skip_idle(grid, idx_maps, g, land, last_sample, last_close, last_low, last_high,
                                                  last_open)
                    g = land
                    continue
            t = int(grid[g])
            can_trade = t >= self.trade_start_ts and self.halted_at is None
            touched = False
            busy = False
            for b, book in enumerate(self.books):
                i = idx_maps[b][g]
                if i < 0:
                    continue
                d = book["data"]
                o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
                while book["f_idx"] < len(d["f_t"]) and d["f_t"][book["f_idx"]] <= t:
                    for e in book["entries"]:
                        e["tracker"].apply_funding(float(d["f_r"][book["f_idx"]]), float(o))
                    book["f_idx"] += 1
                for e in book["entries"]:
                    tr = e["tracker"]
                    sig = bool(e["match"][i])
                    if not tr.is_open and not tr.pending_entry and not sig:
                        continue  # không có gì xảy ra với tracker này ở phút này
                    can_open = False
                    if can_trade and tr.pending_entry and not tr.is_open:
                        n_open, per = self._open_counts()
                        blocked = n_open >= self.risk.max_positions or per[b] >= self.risk.max_per_symbol
                        if not blocked:
                            last_close[b] = float(o)  # giá tại thời điểm vào lệnh
                            room = cap * self.ledger.equity - self._gross_notional(last_close)
                            tr.max_new_notional = max(0.0, room)
                            can_open = room > 0
                            blocked = not can_open
                        if blocked:
                            self.rejected_for_risk += 1
                            if e.get("blk_g") != g - 1:   # phút trước tracker này không bị chặn -> một lần vào lệnh mới bị chặn
                                self.risk_blocked_attempts += 1
                            e["blk_g"] = g
                    pos = tr.on_bar(t, o, h, l, c, entry_signal=sig and can_trade, stop_signal=bool(e["stop"][i]),
                                    can_open=can_open,
                                    vol=float(e["vol"][i]) if e["vol"] is not None else float("nan"))
                    tr.max_new_notional = float("inf")
                    if tr.is_open or tr.pending_entry:
                        busy = True
                    if pos is not None:
                        self._collect(book["symbol"], e, pos)
                        if self.ledger.equity <= 0 and self.ruined_at is None:
                            self.ruined_at = t
                last_close[b], last_low[b], last_high[b], last_open[b] = float(c), float(l), float(h), float(o)
                touched = True
            g += 1
            if not touched:
                continue
            if self.bar_hook is not None:
                self.bar_hook(self, t)
            mtm, worst = self._mtm(last_close, last_low, last_high)
            peak_mtm = max(peak_mtm, mtm)
            if kill and self.halted_at is None and worst <= peak_mtm * (1.0 - kill):
                self._halt(t, last_close)
                mtm, worst = self._mtm(last_close, last_low, last_high)
            if last_sample is None or t - last_sample >= self.MTM_SAMPLE_MINUTES * 60_000:
                self._sample(t, mtm, worst)
                last_sample = t

        t_end = int(grid[-1]) if len(grid) else self.end_ts
        self.last_close = {book["symbol"]: last_close[b] for b, book in enumerate(self.books)}
        for b, book in enumerate(self.books if self.close_at_end else ()):
            t_last = int(book["data"]["t"][-1]) if len(book["data"]["t"]) else t_end
            for e in book["entries"]:  # cùng quy ước BacktestEngine: đóng ở open của nến cuối của tài sản
                pos = e["tracker"].force_close(t_last, last_open[b], "End of Backtest")
                if pos is not None:
                    self._collect(book["symbol"], e, pos)
        mtm, worst = self._mtm(last_close, last_low, last_high)
        self._sample(t_end, mtm, worst)

    def _any_active(self) -> bool:
        return any(e["tracker"].is_open or e["tracker"].pending_entry or e["tracker"].pending_exit
                   for book in self.books for e in book["entries"])

    def _skip_idle(self, grid, idx_maps, g: int, land: int, last_sample, last_close, last_low, last_high, last_open):
        """Tái hiện đúng những gì vòng lặp gốc làm ở các phút rảnh g..land-1 (mọi tracker đang phẳng):
        - funding: con trỏ f_idx của từng sổ trượt qua mọi funding <= nến cuối của sổ đó trong đoạn (apply_funding là no-op khi phẳng);
        - last_close/low/high/open: nến thật cuối của từng sổ trước `land`;
        - mẫu vốn theo giờ: đúng các thời điểm lưới mà vòng gốc sẽ lấy (t - last_sample >= MTM_SAMPLE_MINUTES), vốn = ledger.equity."""
        t_lo, t_hi = int(grid[g]), int(grid[land]) if land < len(grid) else None
        for b, book in enumerate(self.books):
            d = book["data"]
            lo = int(np.searchsorted(d["t"], t_lo, side="left"))
            hi = len(d["t"]) if t_hi is None else int(np.searchsorted(d["t"], t_hi, side="left"))
            if hi <= lo:
                continue
            i = hi - 1
            book["f_idx"] = max(book["f_idx"], int(np.searchsorted(d["f_t"], d["t"][i], side="right")))
            last_close[b], last_low[b], last_high[b], last_open[b] = (
                float(d["c"][i]), float(d["l"][i]), float(d["h"][i]), float(d["o"][i]))
        step = self.MTM_SAMPLE_MINUTES * 60_000
        k = g if last_sample is None else int(np.searchsorted(grid, last_sample + step, side="left"))
        while k < land:
            mtm, worst = self._mtm(last_close, last_low, last_high)  # phẳng: = vốn đã chốt
            last_sample = int(grid[k])
            self._sample(last_sample, mtm, worst)
            k = int(np.searchsorted(grid, last_sample + step, side="left"))
        return last_sample

    def _mtm(self, last_close, last_low, last_high) -> Tuple[float, float]:
        mtm = worst = self.ledger.equity
        for b, book in enumerate(self.books):
            for e in book["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    mtm += tr.unrealized_pnl_usd(last_close[b])
                    worst += tr.unrealized_pnl_usd(last_low[b] if tr.is_long else last_high[b])
        return mtm, worst

    def _halt(self, t: int, last_close: List[float]) -> None:
        """Kill switch: đóng mọi vị thế ở giá hiện tại (market) và dừng mở lệnh mới."""
        self.halted_at = t
        for b, book in enumerate(self.books):
            for e in book["entries"]:
                tr = e["tracker"]
                tr.pending_entry = False
                pos = tr.force_close(t, last_close[b], "Kill switch danh mục")
                if pos is not None:
                    self._collect(book["symbol"], e, pos)

    def _sample(self, t: int, mtm: float, worst: float) -> None:
        self.equity_curve.append({"time": t, "equity": round(mtm, 4), "equity_worst": round(worst, 4)})

    def _collect(self, symbol: str, entry: Dict[str, Any], pos) -> None:
        pos.symbol = symbol
        pos.strategy_id = entry["strategy"]
        self.closed_positions.append(pos)
        self.orders.extend(entry["tracker"].orders)
        entry["tracker"].orders = []

    # ─── Kết quả ────────────────────────────────────────────────────────────
    def open_positions(self) -> List[Dict[str, Any]]:
        """Vị thế còn mở sau run() (chỉ khác rỗng khi close_at_end=False), mark = giá đóng cửa cuối của tài sản."""
        out = []
        for book in self.books:
            mark = self.last_close.get(book["symbol"])
            for e in book["entries"]:
                tr = e["tracker"]
                if not tr.is_open or tr.qty <= 0 or tr.position is None or mark is None or mark != mark:
                    continue
                out.append({"symbol": book["symbol"], "strategy": e["strategy"], "side": tr.pos_type.name, "qty": tr.qty,
                            "entry_price": tr.avg, "mark_price": float(mark), "notional": tr.qty * float(mark),
                            "unrealized_pnl": tr.unrealized_pnl_usd(float(mark)), "opened": int(tr.position.enter_time),
                            "margin_usd": tr.margin_used, "leverage": tr.pos_leverage})
        return out

    def get_results(self) -> Dict[str, Any]:
        by_strategy: Dict[str, Dict[str, float]] = {}
        by_symbol: Dict[str, Dict[str, float]] = {}
        for p in self.closed_positions:
            for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
                agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
                agg["pnl_usd"] += p.real_pnl
                agg["trades"] += 1
                agg["wins"] += int(p.real_pnl > 0)
                agg["fees_usd"] += p.fees_usd or 0.0
                agg["funding_usd"] += p.funding_usd or 0.0
        skipped = sum(e["tracker"].skipped_no_vol for b in self.books for e in b["entries"])
        dca_rejected = sum(e["tracker"].dca_rejected for b in self.books for e in b["entries"])
        return {
            "positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
            "final_equity": self.ledger.equity, "initial_capital": self.initial_capital,
            "by_strategy": by_strategy, "by_symbol": by_symbol,
            "rejected_for_capital": self.ledger.rejected, "rejected_for_risk": self.rejected_for_risk,
            "risk_blocked_attempts": self.risk_blocked_attempts,
            "skipped_no_vol": skipped, "dca_layers_rejected": dca_rejected, "halted_at": self.halted_at, "ruined_at": self.ruined_at,
            "risk": asdict(self.risk), "symbols": self.symbols, "strategies": [s["id"] for s in self.strategies],
        }
