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
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from backend.core.data import shared as shared_data
from backend.core.backtest.engine import BacktestEngine
from backend.core.execute.ledger import CapitalLedger
from backend.core.execute.tracker import PositionTracker
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
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True, base_frame: str = "1m"):
        """base_frame: khung nến dùng để mô phỏng (1m mặc định; 15m/1h/4h chạy nhanh hơn nhiều, khung tín hiệu phải >= khung chạy).
        strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (backend/core/data/shared.py); mặc định env NORA_SHARED_DATA_DIR.
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
        self.close_at_end = close_at_end
        self.base_frame = base_frame
        self.last_close: Dict[str, float] = {}   # giá đóng cửa cuối của từng tài sản (đặt khi run() xong)

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def _make_trackers(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, PositionTracker]]]:
        from backend.core.params.builder import build_params
        eng = BacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital, base_frame=self.base_frame)
        eng.ledger = ledger
        pairs = []
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            if st.get("regime"):   # đặc trưng regime đi qua cùng bộ máy căn khung với tín hiệu
                from backend.core.regime.classifier import REFS
                eng.extra_refs = REFS
            name = f"{st['side']}_{st['id']}"
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, symbol=symbol))
            pairs.append((st, eng.trackers[-1]))
        return eng, pairs

    @staticmethod
    def _refs_signature(eng: BacktestEngine):
        return tuple(sorted((f, tuple(sorted(r))) for f, r in eng._refs_by_frame().items()))

    def _cache_key(self, symbol: str, eng: BacktestEngine) -> tuple:
        return (symbol, self.start_ts, self.end_ts, self._refs_signature(eng), any(tr.market == "perp" for tr in eng.trackers),
                self.base_frame)

    def _build_symbol_data(self, eng: BacktestEngine, only: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Dựng `data` của một tài sản (nến thật 1m + cột kernel + funding), không đụng cache.
        only: chỉ tính các cột này (dữ liệu dùng chung điền phần còn thiếu — core/data/shared.fill)."""
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix(only=only)
        real = df1["is_filled"].to_numpy() == 0
        return {
            "t": df1["open_time"].to_numpy(dtype="int64")[real],
            "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
            "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
            "cols": {k: v[real] for k, v in cols.items()},
            "f_t": eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64"),
            "f_r": eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([]),
        }

    def _load_shared(self, eng: BacktestEngine) -> Optional[Dict[str, Any]]:
        """Dữ liệu qua kho dùng chung (shared_dir, core/data/shared.py): nền mmap + cột chỉ báo tính sẵn theo khung, căn theo chỉ số
        dùng chung. Thiếu phần nào thì tự tính ĐÚNG phần đó, ghi vào kho (tiến trình khác dùng lại) rồi đọc lại.
        Bằng từng bit với _build_symbol_data. None nếu tài sản không có 1m.pkl (dựng như thường)."""
        from backend.core.data.loader import CandleLoader
        p = shared_data.plan(eng)
        if p is None:
            return None
        data = shared_data.load(self.shared_dir, p)
        if data is not None:
            return data
        shared_data.fill(self.shared_dir, self, eng, p)
        eng.df_base, eng.df_base_hist, eng.frames, eng.df_4h, eng.funding = None, None, {}, None, None   # như khi đọc thẳng kho
        CandleLoader.clear_cache()
        return shared_data.load(self.shared_dir, p)

    def _load_symbol(self, symbol: str, eng: BacktestEngine) -> Dict[str, Any]:
        if self.shared_dir:  # mmap chỉ đọc dùng chung — KHÔNG đưa vào _DATA_CACHE (không nhân bản RAM)
            data = self._load_shared(eng)
            if data is not None:
                return data
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
            labels = None
            if any(st.get("regime") for st, _ in pairs):
                from backend.core.regime.classifier import classify
                labels = classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), data["t"])
            entries = []
            for st, tr in pairs:
                vcol = BacktestEngine.vol_column(tr)
                match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
                if labels is not None and st.get("regime"):   # lọc tín hiệu vào theo regime + cầu chì thoát khi sốc ngược chiều
                    from backend.core.regime.classifier import masks_for
                    allowed, fuse = masks_for(st, st["side"], labels)
                    match = match & allowed
                    if fuse is not None:
                        stop = stop | fuse
                entries.append({
                    "strategy": st["id"], "tracker": tr, "match": match, "stop": stop,
                    "vol": cols.get(vcol) if vcol else None, "regime": labels,
                })
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── Giới hạn rủi ro ────────────────────────────────────────────────────
    def run(self) -> None:
        """Chạy cả lần backtest bằng kernel numba (core/backtest/kernel.py): cùng ngữ nghĩa, kết quả trùng từng bit với vòng lặp Python cũ
        (test/reference_engine.py + test/test_kernel_parity.py)."""
        from backend.core.backtest.kernel import run_portfolio
        if not self.books:
            self.load_data()
        run_portfolio(self)

    def run_many(self, position_overrides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Nhiều bộ tham số vị thế/thoát lệnh trên CÙNG dữ liệu + CÙNG tín hiệu (nạp/tính một lần) -> danh sách get_results() cùng thứ tự.
        Không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR). Gom alpha theo tín hiệu là việc của backend/optimize."""
        from backend.core.backtest.kernel import run_many
        return run_many(self, position_overrides)

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
