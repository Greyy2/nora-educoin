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
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.backtest.engine import BacktestEngine
from backend.backtest.execution import CapitalLedger, PositionTracker
from backend.core.evaluator import VectorEvaluator, lag_key


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


# Bộ nhớ đệm dữ liệu theo tiến trình: khoá (symbol, start, end, refs, perp) → mảng giá + cột kernel + funding.
# Dùng ByteLRU giới hạn theo byte (không theo số lượng mục) để tránh OOM.
# Cấu hình qua NORA_DATA_CACHE_MB (mặc định 1500 MB).
import os as _os
from collections import OrderedDict as _OrderedDict


class _ByteLRU:
    """LRU cache giới hạn theo tổng byte — an toàn trong tiến trình đơn."""

    def __init__(self, budget_mb: float):
        self.budget: int = int(budget_mb * 1024 * 1024)
        self.used: int = 0
        self._d: "_OrderedDict" = _OrderedDict()

    def get(self, key):
        item = self._d.get(key)
        if item is None:
            return None
        self._d.move_to_end(key)
        return item[0]

    def put(self, key, value, nbytes: int) -> None:
        if nbytes > self.budget:
            return  # mục lớn hơn ngân sách → không cache
        while self._d and self.used + nbytes > self.budget:
            _, (_, n) = self._d.popitem(last=False)
            self.used -= n
        if key in self._d:
            self.used -= self._d[key][1]
        self._d[key] = (value, nbytes)
        self.used += nbytes

    def clear(self) -> None:
        self._d.clear()
        self.used = 0

    def __len__(self) -> int:
        return len(self._d)


def _data_cache_budget_mb() -> float:
    try:
        return float(_os.environ.get("NORA_DATA_CACHE_MB", "1500"))
    except (TypeError, ValueError):
        return 1500.0


_DATA_CACHE: _ByteLRU = _ByteLRU(_data_cache_budget_mb())


def data_cache_clear() -> None:
    """Xóa toàn bộ _DATA_CACHE — gọi giữa các chiến lược ứng viên để giải phóng RAM."""
    _DATA_CACHE.clear()


def _strategy_flow(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": strategy["side"], "match": [{"condition": strategy["tree"]}], "stop": strategy.get("stop") or []}


class PortfolioEngine:
    MTM_SAMPLE_MINUTES = 60

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True):
        """strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}]."""
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
        self.ledger = CapitalLedger(self.initial_capital)
        self.books: List[Dict[str, Any]] = []   # mỗi tài sản: dữ liệu + trackers
        self.closed_positions: List[Any] = []
        self.orders: List[Any] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_risk = 0
        self.bar_hook = None  # (test) gọi sau mỗi phút: hook(engine, t)

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def _make_trackers(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, PositionTracker]]]:
        from backend.backtest.params_builder import build_params
        eng = BacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital)
        eng.ledger = ledger
        pairs = []
        for st in self.strategies:
            name = f"{st['side']}_{st['id']}"
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, symbol=symbol))
            pairs.append((st, eng.trackers[-1]))
        return eng, pairs

    def _load_symbol(self, symbol: str, eng: BacktestEngine) -> Dict[str, Any]:
        refs = eng._refs_by_frame()
        key = (symbol, self.start_ts, self.end_ts, tuple(sorted((f, tuple(sorted(r))) for f, r in refs.items())),
               any(tr.market == "perp" for tr in eng.trackers))
        if self.use_cache:
            cached = _DATA_CACHE.get(key)
            if cached is not None:
                return cached
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix()
        real = df1["is_filled"].to_numpy() == 0
        data = {
            "t": df1["open_time"].to_numpy(dtype="int64")[real],
            "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
            "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
            "cols": {k: v[real] for k, v in cols.items()},
            "f_t": eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64"),
            "f_r": eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([]),
        }
        if self.use_cache:
            # ước tính byte: mỗi mảng float64 = 8 byte/phần tử; cols là dict nhiều mảng
            n = len(data["t"])
            n_cols = len(data["cols"])
            nbytes = n * 5 * 8 + n_cols * n * 8 + len(data["f_t"]) * 16
            _DATA_CACHE.put(key, data, nbytes)
        return data

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_trackers(sym, self.ledger)
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

        for g in range(len(grid)):
            t = int(grid[g])
            can_trade = t >= self.trade_start_ts and self.halted_at is None
            touched = False
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
                        if n_open >= self.risk.max_positions or per[b] >= self.risk.max_per_symbol:
                            self.rejected_for_risk += 1
                        else:
                            last_close[b] = float(o)  # giá tại thời điểm vào lệnh
                            room = cap * self.ledger.equity - self._gross_notional(last_close)
                            tr.max_new_notional = max(0.0, room)
                            can_open = room > 0
                            if not can_open:
                                self.rejected_for_risk += 1
                    pos = tr.on_bar(t, o, h, l, c, entry_signal=sig and can_trade, stop_signal=bool(e["stop"][i]),
                                    can_open=can_open,
                                    vol=float(e["vol"][i]) if e["vol"] is not None else float("nan"))
                    tr.max_new_notional = float("inf")
                    if pos is not None:
                        self._collect(book["symbol"], e, pos)
                        if self.ledger.equity <= 0 and self.ruined_at is None:
                            self.ruined_at = t
                last_close[b], last_low[b], last_high[b], last_open[b] = float(c), float(l), float(h), float(o)
                touched = True
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
        for b, book in enumerate(self.books):
            t_last = int(book["data"]["t"][-1]) if len(book["data"]["t"]) else t_end
            for e in book["entries"]:  # cùng quy ước BacktestEngine: đóng ở open của nến cuối của tài sản
                pos = e["tracker"].force_close(t_last, last_open[b], "End of Backtest")
                if pos is not None:
                    self._collect(book["symbol"], e, pos)
        mtm, worst = self._mtm(last_close, last_low, last_high)
        self._sample(t_end, mtm, worst)

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
        return {
            "positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
            "final_equity": self.ledger.equity, "initial_capital": self.initial_capital,
            "by_strategy": by_strategy, "by_symbol": by_symbol,
            "rejected_for_capital": self.ledger.rejected, "rejected_for_risk": self.rejected_for_risk,
            "skipped_no_vol": skipped, "halted_at": self.halted_at, "ruined_at": self.ruined_at,
            "risk": asdict(self.risk), "symbols": self.symbols, "strategies": [s["id"] for s in self.strategies],
        }
