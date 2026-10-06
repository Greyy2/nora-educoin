"""Sổ PAPER: khớp lệnh mô phỏng bằng SimVenue + PositionManager (đường SỰ KIỆN, P6.5) và đúng vòng danh mục của PortfolioEngine
(giới hạn vị thế / tài sản / tổng danh nghĩa, kill switch trên vốn xấu nhất) — từng nến chạy một, nên chạy được theo thời gian thực
(bot paper) và tái hiện được lịch sử (test: cùng nến + tín hiệu -> cùng lệnh với PortfolioEngine/kernel).

Một nến (t, o, h, l, c) của mỗi tài sản + tín hiệu tại nến đó (match / stop / vol mỗi chiến lược) + funding đến hạn -> step_bar.
Vòng danh mục nằm ở `core/execute/runner.py::Runner` (thứ tự y như test/reference_engine.py::RefPortfolioEngine.run); PaperBook chỉ là mặt
tiền giữ API cũ (books, ledger, trades, last_t, halted_at, peak_mtm, rejected_for_risk, last_close..., positions(), mtm(), step_bar()).

engine="event" (mặc định): MỘT SimVenue chung, MỘT Account chung (= `self.ledger`), một PositionManager mỗi slot (mã số slot liên tiếp theo
thứ tự sổ: tài sản, rồi chiến lược). `e["tracker"]` của mỗi mục trong `books` giữ manager (cùng giao diện đọc: sl_pct, cooldown_ms, qty, avg...).
engine="tracker": đường PositionTracker cũ, bit-identical — TẠM THỜI chỉ cho `tick_run.TickBook` (móc AMM limit_taker / impact_fn mà SimVenue
chưa hỗ trợ; DEX nằm ngoài P6). Bỏ khi DEX chuyển sang SimVenue.

Pickle: bot.py pickle PaperBook vào paper.pkl rồi nạp lại. Bản pickle của code CŨ (không có `runner`) được nạp lại thành engine="tracker"
(trackers + sổ vốn cũ được Runner nhận nguyên, venue=None) nên bot đang chạy tiếp được, bit-identical với trước; sổ mới bắt đầu bằng
paper.pkl mới thì dùng đường event. Runner bỏ móc `collect` khi pickle, __setstate__ gắn lại.
"""
from typing import Any, Dict, List, Optional, Tuple

from backend.core.execute.account import Account
from backend.core.execute.runner import Runner


def _proxy(name: str, settable: bool = True) -> property:
    """Thuộc tính của PaperBook uỷ quyền sang Runner (trạng thái danh mục sống ở Runner)."""
    def get(self):
        return getattr(self.runner, name)

    def put(self, v):
        setattr(self.runner, name, v)
    return property(get, put if settable else None)


class PaperBook:
    def __init__(self, strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str, capital: float, risk: Dict[str, Any],
                 trade_start: int = 0, engine: str = "event", record_events: bool = False):
        from backend.live import signals as ls
        if engine not in ("event", "tracker"):
            raise ValueError(f"engine phải là 'event' hoặc 'tracker', nhận '{engine}'")
        self.engine = engine
        self.symbols = list(symbols)
        ledger = Account(float(capital))
        venue = None
        self.events: Optional[List] = [] if record_events else None   # chuỗi sự kiện của mọi slot (mặc định tắt: bot chạy lâu sẽ phình)
        if engine == "event":
            from backend.core.execute.manager import PositionManager
            from backend.core.execute.sim_venue import SimVenue
            venue = SimVenue()
        books: List[Dict[str, Any]] = []
        slot = 0
        for sym in self.symbols:
            eng, pairs = ls._engine(sym, strategies, base_frame, 0, ls.DAY)
            entries = []
            for st, tr in pairs:
                if engine == "event":
                    actor = PositionManager(tr, venue, slot=slot, account=ledger, events=self.events)   # sổ vốn chung (như PortfolioEngine)
                else:
                    tr.ledger = ledger
                    tr.capital = ledger.initial
                    actor = tr
                slot += 1
                entries.append({"strategy": st["id"], "side": st["side"], "tracker": actor})
            books.append({"symbol": sym, "entries": entries})
        self.runner = Runner(venue, ledger, books, risk, trade_start, collect=self._collect, initial_capital=float(capital))

    # ── trạng thái (uỷ quyền Runner) ──
    books = _proxy("books", settable=False)
    last_close, last_low, last_high, last_open = _proxy("last_close"), _proxy("last_low"), _proxy("last_high"), _proxy("last_open")
    peak_mtm, halted_at, last_t = _proxy("peak_mtm"), _proxy("halted_at"), _proxy("last_t")
    trades, rejected_for_risk = _proxy("trades"), _proxy("rejected_for_risk")
    risk, trade_start = _proxy("risk"), _proxy("trade_start")

    @property
    def ledger(self) -> Account:
        return self.runner.account

    @property
    def venue(self):
        return self.runner.venue

    def __setstate__(self, state: Dict[str, Any]) -> None:
        if "runner" not in state:        # pickle của PaperBook cũ (trackers) -> engine="tracker" trên cùng trạng thái
            old = state
            runner = Runner(None, old["ledger"], old["books"], old["risk"], old["trade_start"], initial_capital=old["peak_mtm"])
            for k in ("last_close", "last_low", "last_high", "last_open", "peak_mtm", "halted_at", "last_t", "trades", "rejected_for_risk"):
                setattr(runner, k, old[k])
            state = {"symbols": old["symbols"], "runner": runner, "engine": "tracker", "events": None}
        self.__dict__.update(state)
        self.runner.collect = self._collect

    # ── danh mục ──
    def mtm(self) -> Tuple[float, float]:
        return self.runner.mtm()

    def _collect(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        """Ghi lệnh đóng (TickBook ghi đè để giữ thêm PositionModel)."""
        self.runner.record(sym, e, pos, low, high)

    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến chạy ở thời điểm t (open_time) — xem Runner.step_bar. -> các lệnh đóng ở nến này."""
        return self.runner.step_bar(t, bars, sig, funding)

    def positions(self) -> List[Dict[str, Any]]:
        return self.runner.positions()
