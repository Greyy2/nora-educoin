"""LÕI chạy Nautilus duy nhất của Nora: một nơi dựng engine + venue, một vòng nạp nến theo chunk, hai cách dùng.

- `make_engine`: DUY NHẤT dựng BacktestEngineConfig + venue OKX (NETTING, MARGIN, USDT, bar_execution=True).
- `stream`: DUY NHẤT vòng nạp nến theo CHUNK (RAM bị chặn) + `run(streaming=True)`; `on_chunk(ts_unique, trọng_số)` cho người gọi cần lưới thời điểm (Coordinator).
- `NautilusRun`: đường DSL (NoraSlotStrategy + Coordinator), kết quả qua `results.dsl_results`.
- `run_native`: đường Strategy do người dùng viết (kế thừa nautilus Strategy), kết quả qua `results.native_results`.
"""
import inspect
from decimal import Decimal
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Type

import numpy as np

from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine as NautilusEngine
from nautilus_trader.config import LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.alpha.dsl.strategy import RiskConfig
from backend.models.params import FRAME_MS
from backend.nautilus import catalog as cat
from backend.nautilus import results as res_mod
from backend.nautilus.portfolio import Coordinator
from backend.nautilus.strategy import NoraSlotStrategy

CHUNK_BARS = 300_000        # số nến tối đa mỗi lần nạp vào engine Nautilus (chặn RAM)
SAMPLE_MS = 60 * 60_000     # đường vốn lấy mẫu mỗi giờ (như Coordinator.MTM_SAMPLE_MINUTES)
_NS_MS = 1_000_000


# ═══ Dựng engine + nạp nến: MỘT nơi ═════════════════════════════════════════
def make_engine(initial_capital: float, leverage: float, adaptive: bool) -> NautilusEngine:
    cfg = BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True), risk_engine=RiskEngineConfig(bypass=True), run_analysis=False)
    eng = NautilusEngine(cfg)
    eng.add_venue(venue=cat.VENUE_OKX, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                  starting_balances=[Money(float(initial_capital), USDT)], default_leverage=Decimal(str(float(leverage))), bar_execution=True,
                  bar_adaptive_high_low_ordering=bool(adaptive), reject_stop_orders=False, use_message_queue=False)
    return eng


class Feed(NamedTuple):
    symbol: str                 # ký hiệu catalog (đã chuẩn hoá) — khoá của `instruments`
    arrays: Dict[str, np.ndarray]
    weight: int = 1             # số slot xử lý mỗi nến của feed này (Coordinator.bar_done)


def stream(eng: NautilusEngine, feeds: List[Feed], base_frame: str, instruments: Dict[str, Any],
           on_chunk: Optional[Callable[[np.ndarray, np.ndarray], None]] = None) -> bool:
    """Nạp nến theo chunk (linspace trên trục thời gian), chạy streaming, kết thúc engine. -> False khi không có nến nào (engine chưa end())."""
    fr = FRAME_MS[base_frame]
    total = sum(len(f.arrays["t"]) for f in feeds)
    if not total:
        return False
    n_chunks = max(1, -(-total // CHUNK_BARS))
    t_min = min(int(f.arrays["t"][0]) for f in feeds if len(f.arrays["t"]))
    t_max = max(int(f.arrays["t"][-1]) for f in feeds if len(f.arrays["t"]))
    edges = np.linspace(t_min, t_max + 1, n_chunks + 1).astype(np.int64)
    for c in range(n_chunks):
        bars, ts_all, w_all = [], [], []
        for f in feeds:
            t = f.arrays["t"]
            a, z = int(np.searchsorted(t, edges[c])), int(np.searchsorted(t, edges[c + 1]))
            if z > a:
                bars += cat.bars_from_arrays(f.symbol, f.arrays, base_frame, instruments[f.symbol], a, z)
                ts_all.append(t[a:z] + fr)
                w_all.append(np.full(z - a, f.weight, dtype=np.int64))
        if not bars:
            continue
        if on_chunk is not None:
            u, inv = np.unique(np.concatenate(ts_all), return_inverse=True)
            on_chunk(u, np.bincount(inv, weights=np.concatenate(w_all)).astype(np.int64))
        eng.add_data(bars, sort=True)
        eng.run(streaming=True)
        eng.clear_data()
    eng.end()
    return True


# ═══ Đường DSL ══════════════════════════════════════════════════════════════
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
        max_lev = max([float(e["slot"].max_leverage) for b in books for e in b["entries"]] + [1.0])
        eng = make_engine(self.initial, max_lev, self.adaptive)
        for inst in insts.values():
            eng.add_instrument(inst)
        acct: List[Any] = []     # tài khoản được Nautilus tạo khi bắt đầu chạy

        def balance() -> float:
            if not acct:
                acct.append(eng.cache.account_for_venue(cat.VENUE_OKX))
            return acct[0].balance_total(USDT).as_double()
        co = Coordinator(self.risk, self.initial, self.trade_start, balance, len(books), self.fr)
        slots: List[NoraSlotStrategy] = []
        for b_i, b in enumerate(books):
            t_list = b["data"]["t"].tolist()
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
        stream(eng, [Feed(b["symbol"], ex[i], len(b["entries"])) for i, b in enumerate(books)], self.base, insts, on_chunk=co.set_grid)
        if self.close_at_end and eng.cache.positions_open():
            self.warnings.append(f"{len(eng.cache.positions_open())} vị thế còn mở sau close_at_end")
        co.final_sample(last_open_all, self.initial)
        out = res_mod.dsl_results(books, self.warnings, co, slots, ex)
        out["reports"] = None
        if self.KEEP_REPORTS:
            self.reports = {"fills": eng.trader.generate_order_fills_report(), "positions": eng.trader.generate_positions_report(),
                            "account": eng.trader.generate_account_report(cat.VENUE_OKX), "balance": balance()}
            out["reports"] = self.reports
        eng.dispose()
        return out


# ═══ Đường Strategy bản địa ═════════════════════════════════════════════════
class EquityTracker(Strategy):
    """Quan sát (không giao dịch): đường vốn MTM theo lưới thời gian + đóng vị thế cuối dữ liệu cho chiến lược của người dùng.

    Mỗi vị thế mở được định giá theo giá đóng NẾN CUỐI CỦA CHÍNH instrument của nó (equity_worst: giá xấu nhất của nến đó), không theo nến vừa tới của tài sản khác.
    Mẫu lấy khi sang thời điểm kế (mọi tài sản của thời điểm trước đã cập nhật) và một lần cuối sau khi chạy xong (`finish`)."""

    def __init__(self, bar_types: List[Any], frame_ms: int, user: Any, last_close_ms: Dict[Any, int], close_at_end: bool, initial_capital: float):
        super().__init__(StrategyConfig(strategy_id="NORA_EQUITY_TRACKER"))
        self.bar_types, self.fr, self.user, self.close_at_end = bar_types, int(frame_ms), user, bool(close_at_end)
        self.end_ms, self.initial = last_close_ms, float(initial_capital)
        self.sample_ms = max(self.fr, SAMPLE_MS)
        self.curve: List[Dict[str, float]] = []
        self.last_bar: Dict[Any, Bar] = {}
        self.final: Optional[Dict[str, float]] = None
        self._pending: Optional[int] = None
        self._last_sample: Optional[int] = None
        self._latest: Optional[int] = None

    def on_start(self) -> None:
        for bt in self.bar_types:
            self.subscribe_bars(bt)

    def _mtm(self) -> Tuple[float, float, float]:
        bal = self.cache.account_for_venue(cat.VENUE_OKX).balance_total(USDT).as_double()
        mtm = worst = bal
        for pos in self.cache.positions_open():
            b = self.last_bar.get(pos.instrument_id)
            if b is None:
                continue
            mtm += pos.unrealized_pnl(b.close).as_double()
            worst += pos.unrealized_pnl(b.low if pos.is_long else b.high).as_double()
        return bal, mtm, worst

    def _sample(self, close_ms: int) -> None:
        _, mtm, worst = self._mtm()
        self.curve.append({"time": close_ms - self.fr, "equity": round(mtm, 4), "equity_worst": round(worst, 4)})
        self._last_sample = close_ms - self.fr

    def on_bar(self, bar: Bar) -> None:
        ts = int(bar.ts_event // _NS_MS)
        iid = bar.bar_type.instrument_id
        if self._pending is not None and ts != self._pending:
            self._sample(self._pending)
            self._pending = None
        self.last_bar[iid] = bar
        self._latest = ts
        if self._last_sample is None or ts - self.fr - self._last_sample >= self.sample_ms:
            self._pending = ts
        if self.close_at_end and ts == self.end_ms.get(iid):
            u = self.user
            if u.cache.positions_open(instrument_id=iid, strategy_id=u.id):
                u.cancel_all_orders(iid)
                u.close_all_positions(iid, tags=["END"])

    def finish(self) -> None:
        """Sau khi engine chạy xong: mẫu cuối (thay mẫu cùng thời điểm) + số dư / vốn cuối."""
        if self._latest is None:
            self.curve.append({"time": 0, "equity": round(self.initial, 4), "equity_worst": round(self.initial, 4)})
            return
        bal, mtm, worst = self._mtm()
        point = {"time": self._latest - self.fr, "equity": round(mtm, 4), "equity_worst": round(worst, 4)}
        if self.curve and self.curve[-1]["time"] == point["time"]:
            self.curve[-1] = point
        else:
            self.curve.append(point)
        self.final = {"balance": bal, "equity": mtm}


def build_user_strategy(strategy_cls: Type[Strategy], strategy_id: str, instruments: Dict[str, Any], bar_types: List[Any], params: Dict[str, Any]) -> Strategy:
    """Dựng Strategy của người dùng theo CHỮ KÝ __init__: truyền `config` + những trong (instruments, bar_types, instrument, bar_type) và tham số mà nó nhận
    (hoặc tất cả nếu có **kwargs). Lỗi thật của __init__ được nêu nguyên văn (không thử-lại từng kiểu)."""
    cfg = StrategyConfig(strategy_id=strategy_id)
    try:
        sig = inspect.signature(strategy_cls.__init__)
        accepted = {n for n, p in sig.parameters.items() if n != "self" and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        var_kw = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
    except (TypeError, ValueError):                 # __init__ kế thừa từ Strategy (không soi được): chỉ nhận config
        accepted, var_kw = {"config"}, False
    avail: Dict[str, Any] = {"instruments": dict(instruments), "bar_types": list(bar_types)}
    if len(bar_types) == 1:
        avail["instrument"], avail["bar_type"] = next(iter(instruments.values())), bar_types[0]
    elif {"instrument", "bar_type"} & accepted and not {"instruments", "bar_types"} & accepted and not var_kw:
        raise ValueError(f"{strategy_cls.__name__}.__init__ nhận một instrument/bar_type nhưng lần chạy có {len(bar_types)} tài sản: "
                         f"khai báo `instruments` / `bar_types` để nhận nhiều tài sản")
    kwargs = {k: v for k, v in avail.items() if var_kw or k in accepted}
    unknown = sorted(set(params) - accepted) if not var_kw else []
    if unknown:
        raise ValueError(f"{strategy_cls.__name__}.__init__ không nhận tham số {unknown}; nhận: {sorted(accepted - {'config'})}")
    return strategy_cls(cfg, **kwargs, **params)


def run_native(strategy_cls: Type[Strategy], symbols: List[str], start_ms: int, end_ms: int, initial_capital: float, base_frame: str,
               leverage: float = 1.0, close_at_end: bool = True, params: Optional[Dict[str, Any]] = None, strategy_id: str = "NATIVE_STRAT") -> Dict[str, Any]:
    """Chạy một Strategy Nautilus bản địa trên catalog OKX bằng CÙNG lõi (make_engine + stream) -> kết quả dạng PortfolioEngine.get_results() (không có provenance).
    symbols: ký hiệu bất kỳ (BTC, BTC@perp, BTC-USDT-SWAP...); vị thế/lệnh mang đúng ký hiệu người gọi truyền vào."""
    fr = FRAME_MS[base_frame]
    lev = max(1.0, float(leverage))
    labels_in = list(dict.fromkeys(symbols))
    norm = [cat.normalize_symbol(s) for s in labels_in]
    if len(set(norm)) != len(norm):
        raise ValueError(f"ký hiệu trùng sau chuẩn hoá: {norm}")
    insts = {n: cat.get_instrument(n) for n in norm}
    bar_types = [cat.get_bar_type(n, base_frame) for n in norm]
    labels = {str(insts[n].id): s for n, s in zip(norm, labels_in)}
    eng = make_engine(initial_capital, lev, adaptive=False)
    for inst in insts.values():
        eng.add_instrument(inst)
    lo = int(start_ms) // fr * fr
    ex = {n: cat.exec_arrays(n, base_frame, lo, int(end_ms)) for n in norm}
    last_close_ms = {insts[n].id: int(ex[n]["t"][-1]) + fr for n in norm if len(ex[n]["t"])}
    user = build_user_strategy(strategy_cls, strategy_id, insts, bar_types, params or {})
    tracker = EquityTracker(bar_types, fr, user, last_close_ms, close_at_end, initial_capital)
    eng.add_strategy(user)           # trước tracker: trên mỗi nến, chiến lược người dùng xử lý rồi tracker mới lấy mẫu / đóng cuối kỳ
    eng.add_strategy(tracker)
    warns: List[str] = ["funding perp không được Nautilus thanh toán trong backtest: funding_usd = 0",
                        "trượt giá % không được Nautilus mô phỏng; thanh lý không được mô phỏng"]
    if not stream(eng, [Feed(n, ex[n]) for n in norm], base_frame, insts):
        warns.append("Không có nến nào trong catalog cho khoảng thời gian này")
    tracker.finish()
    if close_at_end and eng.cache.positions_open():
        warns.append(f"{len(eng.cache.positions_open())} vị thế còn mở sau close_at_end")
    run = res_mod.native_results(eng, tracker.curve, tracker.final, tracker.last_bar, initial_capital=float(initial_capital), leverage=lev,
                                 strategy_id=strategy_id, labels=labels, warnings=warns)
    eng.dispose()
    return res_mod.portfolio_view(run, initial_capital)
