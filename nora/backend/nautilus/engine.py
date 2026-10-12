"""Engine backtest = NautilusTrader (P15): `PortfolioEngine` / `BacktestEngine` giữ chữ ký, phương thức công khai và hình dạng `get_results()` của engine cũ,
nhưng khớp lệnh, phí, số dư, vị thế do `nautilus_trader.backtest.engine.BacktestEngine` sinh (venue OKX, NETTING, MARGIN, USDT, bar_execution=True).

Luồng một lần chạy (`backtest.NautilusRun`; dựng engine / nạp nến theo chunk ở backtest.py, kết quả ở results.py):
  1. Tín hiệu: tính SẴN bằng backend.signal.compute (SignalEngine / matrix_evaluator / entry_event_mask / _regime_gate) — đúng đường dữ liệu engine cũ.
  2. Nến thực thi: ParquetDataCatalog (1m EXTERNAL, ts_event = đóng) — khung chạy > 1m do `catalog.aggregate_frame` gộp; nạp theo CHUNK (RAM bị chặn),
     `BacktestEngine.run(streaming=True)` từng chunk.
  3. Mỗi (chiến lược × tài sản) một `NoraSlotStrategy`; `Coordinator` (portfolio.py) giữ luật rủi ro danh mục, kill switch, đường vốn.
  4. Kết quả: PositionModel / OrderModel dựng từ fill + PositionClosed của Nautilus; final_equity = số dư tài khoản Nautilus.

Không mô phỏng (Nautilus không có; KHÔNG giả): trượt giá %, funding, thanh lý. Mỗi trường hợp ghi vào `results["warnings"]` + cờ riêng.
"""
import contextlib
import io
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

import numpy as np

from nautilus_trader import __version__ as NAUTILUS_VERSION

from backend.signal.nodes import lag_key
from backend.signal.compute import FRESH, SignalEngine, SignalPortfolio, entry_event_mask, matrix_evaluator, slot_fresh_frames, _regime_gate, _regime_labels
from backend.alpha.plan import RiskConfig, aggregate_positions
from backend.nautilus import catalog as cat
from backend.nautilus.backtest import CHUNK_BARS, NautilusRun      # noqa: F401 — NautilusRun: lõi chạy ở backtest.py; re-export cho nơi gọi cũ

FILL_CONVENTION = ("Lệnh market gửi lúc nến i đóng khớp ở GIÁ ĐÓNG nến i (Nautilus bar_execution); engine cũ khớp ở giá MỞ nến i+1. "
                   "SL/TP/TRAIL/DCA khớp theo đường O→H→L→C của nến (bar_adaptive_high_low_ordering theo intrabar_path).")


def provenance(base_frame: str) -> Dict[str, Any]:
    """Nguồn gốc MỘT kết quả engine (MỘT định nghĩa; mọi payload kết quả mang khoá `provenance`). Job runner chỉ thêm job_id / computed_at lên dict này."""
    return {"engine": "nautilus_trader", "version": NAUTILUS_VERSION, "base_frame": base_frame, "exec_frame": base_frame, "venue": "OKX", "oms": "NETTING", "account": "MARGIN",
            "fill_convention": FILL_CONVENTION, "slippage_modeled": False, "funding_modeled": False, "liquidation_modeled": False}


# ═══ BacktestEngine: MỘT tài sản, nhiều flow ═══════════════════════════════
class BacktestEngine(SignalEngine):
    """Điều phối dữ liệu + tín hiệu (SignalEngine) và chạy trên Nautilus (một tài sản, nhiều flow, sổ vốn riêng)."""

    def run(self):
        if self.df_base is None or self.df_base.empty:
            return
        self.closed_positions, self.orders, self.equity_curve = [], [], []
        df1, cols = self._build_matrix()
        n = len(df1)
        vec = matrix_evaluator(cols, n)
        real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)
        entries = []
        for tr in self.slots:
            vcol = self.vol_column(tr)
            entries.append({"strategy": "", "slot": tr, "match": entry_event_mask(vec, cols, tr, self.base_frame)[real], "stop": vec.tree(tr.stop_tree)[real],
                            "vol": cols[vcol][real] if vcol and vcol in cols else None, "dca": vec.tree(tr.dca_tree)[real] if tr.dca_tree else None})
        book = {"symbol": self.symbol, "data": {"t": df1["open_time"].to_numpy(dtype="int64")[real]}, "entries": entries}
        risk = RiskConfig(max_positions=max(1, len(self.slots)), max_per_symbol=max(1, len(self.slots)), max_gross_exposure=1e12, kill_switch_dd_pct=0.0)
        res = NautilusRun([book], self.initial_capital, risk, self.trade_start_ts, self.end_ts, self.base_frame, True, self._src()).run()
        self.closed_positions, self.orders, self.equity_curve = res["positions"], res["orders"], res["equity_curve"]
        self.ruined_at = res["ruined_at"]
        self.ledger.equity, self.ledger.rejected = res["final_equity"], res["rejected_for_capital"]
        self._res = res

    def get_results(self):
        res = getattr(self, "_res", {})
        return {"positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve, "ruined_at": getattr(self, "ruined_at", None),
                "final_equity": self.ledger.equity, "rejected_for_capital": self.ledger.rejected, "dca_layers_rejected": res.get("dca_layers_rejected", 0),
                "funding_modeled": False, "funding_events": 0, "warnings": res.get("warnings", []), "provenance": provenance(self.base_frame)}


# ═══ PortfolioEngine: nhiều tài sản × nhiều chiến lược trên MỘT tài khoản Nautilus ═══
class PortfolioEngine(SignalPortfolio):
    MTM_SAMPLE_MINUTES = 60
    LOAD_WORKERS = 1

    # ─── dữ liệu tín hiệu (đúng đường dữ liệu của engine cũ) ─────────────────
    def _build_symbol_data(self, eng: SignalEngine, only: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Dữ liệu một tài sản: nến thật của khung chạy + cột chỉ báo (tín hiệu). only: chỉ tính các cột này (kho dùng chung điền phần thiếu)."""
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix(only=only)
        real = df1["is_filled"].to_numpy() == 0
        return {"t": df1["open_time"].to_numpy(dtype="int64")[real],
                "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
                "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
                "cols": {k: v[real] for k, v in cols.items()}, "f_t": np.array([], "int64"), "f_r": np.array([])}

    def _load_shared(self, eng: SignalEngine) -> Optional[Dict[str, Any]]:
        src = self._src()
        p = src.shared_plan(eng)
        if p is None:
            return None
        data = src.shared_load(self.shared_dir, p)
        if data is not None:
            return data
        src.shared_fill(self.shared_dir, self, eng, p)
        eng.df_base, eng.df_base_hist, eng.frames, eng.df_4h, eng.funding = None, None, {}, None, None
        src.release()
        return src.shared_load(self.shared_dir, p)

    def _load_symbol_window(self, symbol: str, eng: SignalEngine) -> Dict[str, Any]:
        """Bộ nhớ đệm theo CỬA SỔ (cửa sổ rộng hơn phục vụ cửa sổ con bằng cách cắt thời gian; cột ⊆ tập đã dựng)."""
        refs = eng._refs_by_frame()
        need = frozenset(f"{fr}|{lag_key(c, lag)}" for fr, rs in refs.items() for c, lag in rs) \
            | frozenset(f"{fr}|{FRESH}" for fr in slot_fresh_frames(eng.slots, eng.base_frame))
        lo = eng.start_ts - eng._warmup_ms(eng.base_frame, refs.get(eng.base_frame, set()))
        memo = self._src().memo
        key = ("window", symbol, self.end_ts, self.base_frame)
        hit = memo.get(key)
        if hit is not None and hit["lo"] <= lo and hit["start"] <= eng.start_ts and need <= hit["need"]:
            d = hit["data"]
            a = int(np.searchsorted(d["t"], lo, side="left"))
            return {"t": d["t"][a:], "o": d["o"][a:], "h": d["h"][a:], "l": d["l"][a:], "c": d["c"][a:],
                    "cols": {k: v[a:] for k, v in d["cols"].items() if k in need}, "f_t": d["f_t"], "f_r": d["f_r"]}
        data = self._build_symbol_data(eng)
        arrays = [data[k] for k in ("t", "o", "h", "l", "c", "f_t", "f_r")] + list(data["cols"].values())
        memo.put(key, {"lo": lo, "start": eng.start_ts, "need": need, "data": data}, sum(a.nbytes for a in arrays))
        return data

    def _load_symbol(self, symbol: str, eng: SignalEngine) -> Dict[str, Any]:
        if self.shared_dir:
            data = self._load_shared(eng)
            if data is not None:
                return data
        if self.use_cache:
            return self._load_symbol_window(symbol, eng)
        return self._build_symbol_data(eng)

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_slots(sym, self.ledger)
            if not pairs:     # không chiến lược nào chạy trên tài sản này (khoá "symbols")
                continue
            cat.normalize_symbol(sym)           # DEX / ký hiệu lạ: lỗi rõ ràng trước khi nạp
            self._src().require_ok([sym])
            data = self._load_symbol(sym, eng)
            n = len(data["t"])
            cols = data["cols"]
            vec = matrix_evaluator(cols, n)
            labels = _regime_labels(pairs, cols, n, data["t"])
            entries = []
            for st, tr in pairs:
                vcol = SignalEngine.vol_column(tr)
                match, stop = entry_event_mask(vec, cols, tr, eng.base_frame), vec.tree(tr.stop_tree)
                match, stop = _regime_gate(st, labels, match, stop)
                entries.append({"strategy": st["id"], "slot": tr, "match": match, "stop": stop, "vol": cols.get(vcol) if vcol else None, "regime": labels,
                                "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None})
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── chạy ───────────────────────────────────────────────────────────────
    def run(self) -> None:
        """Chạy cả lần backtest trên Nautilus."""
        if not self.books:
            self.load_data()
        self._run_books()

    def _run_books(self) -> None:
        res = NautilusRun(self.books, self.initial_capital, self.risk, self.trade_start_ts, self.end_ts, self.base_frame, self.close_at_end, self._src()).run()
        self._res = res
        self.closed_positions, self.orders, self.equity_curve = res["positions"], res["orders"], res["equity_curve"]
        self.ledger.equity = res["final_equity"]
        self.ledger.rejected += res["rejected_for_capital"]
        self.rejected_for_risk += res["rejected_for_risk"]
        self.risk_blocked_attempts += res["risk_blocked_attempts"]
        self.halted_at, self.ruined_at = res["halted_at"], res["ruined_at"]
        self.last_close = res["last_close"]

    def run_many(self, position_overrides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Nhiều bộ tham số vị thế/thoát lệnh trên CÙNG dữ liệu + CÙNG tín hiệu (nạp/tính một lần): mỗi bộ là MỘT lần chạy Nautilus thật.
        Không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR)."""
        if not self.books:
            self.load_data()
        out: List[Dict[str, Any]] = []
        for ov in position_overrides:
            strategies = [{**st, "position": {**st["position"], **ov}} for st in self.strategies]
            sub = type(self)(self.symbols, strategies, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts, initial_capital=self.initial_capital,
                             risk=self.risk, venue=self.venue, use_cache=False, shared_dir=self.shared_dir, close_at_end=self.close_at_end,
                             base_frame=self.base_frame, data=self.data)
            for book in self.books:
                _, pairs = sub._make_slots(book["symbol"], sub.ledger)
                entries = []
                for (_st, sp), e0 in zip(pairs, book["entries"]):
                    if SignalEngine.vol_column(sp) != SignalEngine.vol_column(e0["slot"]):
                        raise ValueError("run_many: ghi đè không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR)")
                    entries.append({k_: v for k_, v in e0.items()} | {"slot": sp})
                sub.books.append({**book, "entries": entries, "f_idx": 0})
            sub._run_books()
            out.append(sub.get_results())
        return out

    def open_positions(self) -> List[Dict[str, Any]]:
        """Vị thế còn mở sau run() (chỉ khác rỗng khi close_at_end=False), mark = giá đóng cửa cuối của tài sản."""
        return list(getattr(self, "_res", {}).get("open_positions", []))

    def get_results(self) -> Dict[str, Any]:
        by_strategy, by_symbol = aggregate_positions(self.closed_positions)
        res = getattr(self, "_res", {})
        return {
            "positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
            "final_equity": self.ledger.equity, "initial_capital": self.initial_capital,
            "by_strategy": by_strategy, "by_symbol": by_symbol,
            "rejected_for_capital": self.ledger.rejected, "rejected_for_risk": self.rejected_for_risk,
            "risk_blocked_attempts": self.risk_blocked_attempts,
            "skipped_no_vol": res.get("skipped_no_vol", 0), "dca_layers_rejected": res.get("dca_layers_rejected", 0),
            "halted_at": self.halted_at, "ruined_at": self.ruined_at,
            "risk": asdict(self.risk), "symbols": self.symbols, "strategies": [s["id"] for s in self.strategies],
            "funding_modeled": False, "funding_events": 0, "warnings": res.get("warnings", []), "provenance": provenance(self.base_frame),
        }
