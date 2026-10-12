"""Engine backtest = NautilusTrader (P15): `PortfolioEngine` / `BacktestEngine` giữ chữ ký, phương thức công khai và hình dạng `get_results()` của engine cũ,
nhưng khớp lệnh, phí, số dư, vị thế do `nautilus_trader.backtest.engine.BacktestEngine` sinh (venue OKX, NETTING, MARGIN, USDT, bar_execution=True).

Luồng một lần chạy (`NautilusRun`):
  1. Tín hiệu: tính SẴN bằng backend.alpha.dsl.strategy (SignalEngine / matrix_evaluator / entry_event_mask / _regime_gate) — đúng đường dữ liệu engine cũ.
  2. Nến thực thi: ParquetDataCatalog (1m EXTERNAL, ts_event = đóng) — khung chạy > 1m do `catalog.aggregate_frame` gộp; nạp theo CHUNK (RAM bị chặn),
     `BacktestEngine.run(streaming=True)` từng chunk.
  3. Mỗi (chiến lược × tài sản) một `NoraSlotStrategy`; `Coordinator` (portfolio.py) giữ luật rủi ro danh mục, kill switch, đường vốn.
  4. Kết quả: PositionModel / OrderModel dựng từ fill + PositionClosed của Nautilus; final_equity = số dư tài khoản Nautilus.

Không mô phỏng (Nautilus không có; KHÔNG giả): trượt giá %, funding, thanh lý. Mỗi trường hợp ghi vào `results["warnings"]` + cờ riêng.
"""
import contextlib
import io
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from nautilus_trader import __version__ as NAUTILUS_VERSION
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine as NautilusEngine
from nautilus_trader.config import LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money

from backend.models.params import FRAME_MS
from backend.alpha.dsl.signal import lag_key
from backend.alpha.dsl.strategy import (FRESH, RiskConfig, SignalEngine, SignalPortfolio, aggregate_positions, entry_event_mask,
                                   matrix_evaluator, slot_fresh_frames, _regime_gate, _regime_labels)
from backend.nautilus import catalog as cat
from backend.nautilus.portfolio import Coordinator
from backend.nautilus.strategy import FLAT, NoraSlotStrategy

FILL_CONVENTION = ("Lệnh market gửi lúc nến i đóng khớp ở GIÁ ĐÓNG nến i (Nautilus bar_execution); engine cũ khớp ở giá MỞ nến i+1. "
                   "SL/TP/TRAIL/DCA khớp theo đường O→H→L→C của nến (bar_adaptive_high_low_ordering theo intrabar_path).")
CHUNK_BARS = 300_000        # số nến tối đa mỗi lần nạp vào engine Nautilus (chặn RAM)


# ═══ Một lần chạy trên Nautilus ═════════════════════════════════════════════
class NautilusRun:
    """books = [{"symbol", "data": {"t"...}, "entries": [{"strategy", "slot": SlotSpec, "match", "stop", "vol", "dca"}]}] (như PortfolioEngine.books)."""
    KEEP_REPORTS = False     # test: giữ các báo cáo Nautilus (fills / positions / account) để đối chiếu

    def __init__(self, books: List[Dict[str, Any]], initial_capital: float, risk: RiskConfig, trade_start_ts: int, end_ts: int, base_frame: str,
                 close_at_end: bool, data: Any):
        """data: DataSource (models/models) — nến thực thi + spec hợp đồng đều lấy từ đây (một đường dữ liệu)."""
        self.data = data
        self.books, self.initial, self.risk = books, float(initial_capital), risk
        self.trade_start, self.end_ts, self.base, self.close_at_end = int(trade_start_ts), int(end_ts), base_frame, bool(close_at_end)
        self.fr = FRAME_MS[base_frame]
        self.warnings: List[str] = []
        self.reports: Dict[str, Any] = {}

    # ── kiểm tra tham số mô phỏng được / không ──
    def _check_slots(self) -> None:
        slip, thru, extreme, lev = set(), set(), set(), False
        paths, perp = set(), False
        for b in self.books:
            for e in b["entries"]:
                sp = e["slot"]
                if sp.intrabar_path == "adverse_first":
                    raise ValueError(f"{e['strategy']}: intrabar_path='adverse_first' không được hỗ trợ trên Nautilus (chỉ ohlc / adaptive)")
                paths.add(sp.intrabar_path)
                if sp.slippage_rate > 0:
                    slip.add(sp.slippage_rate)
                if sp.limit_through > 0:
                    thru.add(sp.limit_through)
                if sp.stop_fill == "extreme":
                    extreme.add(e["strategy"])
                perp |= sp.market == "perp"
                lev |= sp.market == "perp" and sp.max_leverage > 1
        if len(paths) > 1:
            raise ValueError(f"Mọi chiến lược của một lần chạy phải cùng intrabar_path (Nautilus cấu hình theo venue), nhận {sorted(paths)}")
        self.adaptive = "adaptive" in paths
        if slip:
            self.warnings.append(f"slippage_rate={sorted(slip)} không được Nautilus mô phỏng (không có trượt giá %): bỏ qua, khớp ở giá của mô hình Nautilus")
        if thru:
            self.warnings.append(f"limit_through_pct={sorted(thru)} không được hỗ trợ: lệnh limit khớp khi giá chạm mức (không cần đi xuyên qua)")
        if extreme:
            self.warnings.append(f"stop_fill='extreme' ({sorted(extreme)}) không được hỗ trợ: stop-market khớp theo mô hình Nautilus")
        if lev:
            self.warnings.append("thanh lý (liquidation) không được Nautilus 1.231 mô phỏng trong backtest: vị thế đòn bẩy không bị thanh lý")
        if perp:
            self.warnings.append("funding perp không được Nautilus thanh toán trong backtest: funding_usd = 0")

    def _instruments(self) -> Dict[str, Any]:
        fees: Dict[str, Tuple[float, float]] = {}
        for b in self.books:
            for e in b["entries"]:
                sp = e["slot"]
                f = (float(sp.maker_fee_rate), float(sp.fee_rate))
                if fees.setdefault(b["symbol"], f) != f:
                    raise ValueError(f"{b['symbol']}: các chiến lược trên cùng tài sản phải cùng phí maker/taker (Nautilus đặt phí trên instrument)")
        return {sym: cat.build_instrument(sym, self.data.instrument_spec(sym), maker_fee=m, taker_fee=t) for sym, (m, t) in fees.items()}

    # ── chạy ──
    def run(self) -> Dict[str, Any]:
        self._check_slots()
        insts = self._instruments()
        books = self.books
        lo = self.trade_start // self.fr * self.fr
        ex = [self.data.exec_arrays(b["symbol"], self.base, lo, self.end_ts) for b in books]
        total = sum(len(a["t"]) for a in ex)
        cfg = BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True), risk_engine=RiskEngineConfig(bypass=True), run_analysis=False)
        eng = NautilusEngine(cfg)
        max_lev = max([float(e["slot"].max_leverage) for b in books for e in b["entries"]] + [1.0])
        eng.add_venue(venue=cat.VENUE_OKX, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                      starting_balances=[Money(self.initial, USDT)], default_leverage=Decimal(str(max_lev)), bar_execution=True,
                      bar_adaptive_high_low_ordering=self.adaptive, reject_stop_orders=False, use_message_queue=False)
        for inst in insts.values():
            eng.add_instrument(inst)
        acct: List[Any] = []     # tài khoản được Nautilus tạo khi bắt đầu chạy

        def balance() -> float:
            if not acct:
                acct.append(eng.cache.account_for_venue(cat.VENUE_OKX))
            return acct[0].balance_total(USDT).as_double()
        co = Coordinator(self.risk, self.initial, self.trade_start, balance, len(books), self.fr)
        slots: List[NoraSlotStrategy] = []
        n_per = []
        for b_i, b in enumerate(books):
            t_list = b["data"]["t"].tolist()
            n_per.append(len(b["entries"]))
            last_open = int(ex[b_i]["t"][-1]) if len(ex[b_i]["t"]) else None
            for e in b["entries"]:
                sig = {"t": t_list, "match": e["match"].tolist(), "stop": e["stop"].tolist(),
                       "vol": e["vol"].tolist() if e.get("vol") is not None else None, "dca": e["dca"].tolist() if e.get("dca") is not None else None}
                s = NoraSlotStrategy(len(slots), e["slot"], e["strategy"], b["symbol"], b_i, insts[b["symbol"]], cat.get_bar_type(b["symbol"], self.base),
                                     self.fr, sig, co, last_open, self.close_at_end, self.trade_start)
                slots.append(s)
                eng.add_strategy(s)
        co.slots = slots
        last_open_all = max((int(a["t"][-1]) for a in ex if len(a["t"])), default=None)
        if total:
            n_chunks = max(1, -(-total // CHUNK_BARS))
            t_min, t_max = min(int(a["t"][0]) for a in ex if len(a["t"])), last_open_all
            edges = np.linspace(t_min, t_max + 1, n_chunks + 1).astype(np.int64)
            for c in range(n_chunks):
                bars, ts_all, w_all = [], [], []
                for b_i, b in enumerate(books):
                    t = ex[b_i]["t"]
                    a, z = int(np.searchsorted(t, edges[c])), int(np.searchsorted(t, edges[c + 1]))
                    if z > a:
                        bars += cat.bars_from_arrays(b["symbol"], ex[b_i], self.base, insts[b["symbol"]], a, z)
                        ts_all.append(t[a:z] + self.fr)
                        w_all.append(np.full(z - a, n_per[b_i], dtype=np.int64))
                if not bars:
                    continue
                u, inv = np.unique(np.concatenate(ts_all), return_inverse=True)
                co.set_grid(u, np.bincount(inv, weights=np.concatenate(w_all)).astype(np.int64))
                eng.add_data(bars, sort=True)
                eng.run(streaming=True)
                eng.clear_data()
            eng.end()
        if self.close_at_end and eng.cache.positions_open():
            self.warnings.append(f"{len(eng.cache.positions_open())} vị thế còn mở sau close_at_end")
        co.final_sample(last_open_all, self.initial)
        out = self._results(co, slots, ex)
        out["reports"] = None
        if self.KEEP_REPORTS:
            self.reports = {"fills": eng.trader.generate_order_fills_report(), "positions": eng.trader.generate_positions_report(),
                            "account": eng.trader.generate_account_report(cat.VENUE_OKX), "balance": balance()}
            out["reports"] = self.reports
        eng.dispose()
        return out

    def _results(self, co: Coordinator, slots: List[NoraSlotStrategy], ex: List[Dict[str, np.ndarray]]) -> Dict[str, Any]:
        last_close = {b["symbol"]: (float(ex[i]["c"][-1]) if len(ex[i]["t"]) else float("nan")) for i, b in enumerate(self.books)}
        opens = []
        for s in slots:
            if s.qty > 0 and s.st != FLAT:
                mark = last_close[s.symbol]
                opens.append({"symbol": s.symbol, "strategy": s.sid, "side": s.spec.pos_type.name, "qty": s.qty, "entry_price": s.avg,
                              "mark_price": mark, "notional": s.qty * mark, "unrealized_pnl": s.unrealized(mark), "opened": int(s.entry_time),
                              "margin_usd": s.margin_used, "leverage": s.pos_lev})
        warns = list(self.warnings)
        if co.venue_rejects:
            warns.append(f"{len(co.venue_rejects)} lệnh bị Nautilus từ chối (ví dụ {co.venue_rejects[0]})")
        return {"positions": co.positions, "orders": co.orders, "equity_curve": co.curve, "final_equity": co.equity(), "balance": co.balance(),
                "rejected_for_capital": co.rejected_for_capital, "rejected_for_risk": co.rejected_for_risk, "risk_blocked_attempts": co.risk_blocked_attempts,
                "halted_at": co.halted_at, "ruined_at": co.ruined_at, "skipped_no_vol": sum(s.skipped_no_vol for s in slots),
                "dca_layers_rejected": sum(s.dca_rejected for s in slots), "last_close": last_close, "open_positions": opens, "warnings": warns,
                "venue_rejects": co.venue_rejects}


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
