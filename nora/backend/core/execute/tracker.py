"""Quản lý vị thế (Position management) — một flow chiến lược.

Vòng đời một nến 1m CÓ GIAO DỊCH (nến điền is_filled=1 bị bỏ qua hoàn toàn):

1. Đầu nến (giá open):
   - lệnh thoát chờ (tín hiệu stop ở nến trước) hoặc hết thời gian giữ lệnh -> đóng ở open;
   - lệnh vào chờ (tín hiệu match ở nến trước) -> mở tầng đầu ở open (+ trượt giá).
2. Trong nến — đường giá `intrabar_path` (policy.bar_points):
   - "ohlc" (MẶC ĐỊNH, = NautilusTrader): Open -> High -> Low -> Close. "adaptive" (= `bar_adaptive_high_low_ordering`): cực gần open ghé trước.
     Mỗi chặng là MỘT tick: mọi lệnh bị chặng đó xuyên qua khớp ngay trong tick, theo thứ tự nhóm của sàn Nautilus: (a) các tầng DCA
     (lệnh limit nhồi, từ gần ra xa; avg và giá thanh lý tính lại ngay), (b) chốt lời (limit), (c) các lệnh stop — SL, trailing, thanh lý —
     mức bị xuyên cao nhất trước (long). Lệnh bảo vệ SL / TP là lệnh ĐÃ NẰM TRÊN SÀN từ cuối nến trước: mức của chúng cố định cả nến,
     đặt lại từ avg mới (sau fill DCA) chỉ có hiệu lực từ nến sau; riêng nếu TP mới đã nằm "trong giá" tại close thì nó khớp ngay ở close
     như lệnh taker (đúng hành vi Nautilus: lệnh đặt lại thấy sổ lệnh lúc close). Stop-market khớp ở mức kích hoạt; tick mở cửa (gap) thì ở open.
     Lệnh limit (DCA, TP) luôn khớp ở mức đặt. Trailing: đỉnh/đáy chạy theo từng chặng, mức trailing dùng ở một chặng là mức tính sau chặng trước.
   - "adverse_first" (cũ, giữ nguyên từng bit cho kiểm bền): phía BẤT LỢI trước, theo đúng thứ tự giá chạm (long: từ trên xuống):
     tầng DCA (lệnh limit), stop-loss, trailing stop, giá thanh lý (perp). Sau mỗi tầng DCA, giá trung bình và giá thanh lý được tính lại ngay
     (sàn tự tính giá thanh lý). Hoà mức -> ưu tiên THOÁT (bi quan). SL CŨ (quy tắc bảo thủ, 2026-10-06): lệnh SL đang nằm trên sàn không dời
     được ngay sau fill DCA, nên trong phần còn lại của nến mức SL dùng là mức SL lúc tầng DCA ĐẦU TIÊN của nến khớp; SL tính từ avg mới có
     hiệu lực từ nến sau. Giá open đã vượt mức stop-market (SL/trailing/thanh lý) -> khớp ở open (gap). Lệnh LIMIT đang chờ (tầng DCA)
     khớp đúng ở mức đặt: phần giá tốt hơn khi gap thuộc về bên khớp lệnh (sàn thật / NautilusTrader).
3. (chỉ "adverse_first") Phía CÓ LỢI: chốt lời (limit, từ giá TB) chỉ được xét nếu trong nến KHÔNG có tầng DCA nào
   khớp — không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến. Chốt lời khớp đúng ở mức TP
   (kể cả khi open đã vượt mức).
4. Cuối nến: cập nhật đỉnh/đáy có lợi (cho trailing), lỗ treo tối đa (MAE), rồi đặt lệnh chờ
   cho nến sau theo tín hiệu match/stop (tính trên nến đã đóng).

Chế độ thị trường:
- spot: đòn bẩy = 1, không cho SHORT, không thanh lý.
- perp: đòn bẩy L, ký quỹ isolated, thanh lý khi giá chạm
  long:  avg × (1 − 1/L + mmr)      short: avg × (1 + 1/L − mmr).
  Giá dùng là giá perp thật khi có dữ liệu <SYM>@perp (kèm funding); không có thì giá spot làm proxy.
- stop_fill="extreme": SL/trailing khớp ở giá xấu nhất của nến chạm mức (bi quan). Mặc định "level"
  giả định khớp đúng mức + trượt — lạc quan khi giá giật xuyên mức trong một nến.

Cooldown (tuỳ chọn): sau khi đóng vị thế (kể cả force_close), tín hiệu vào lệnh trong `cooldown` phút bị bỏ qua
— tín hiệu là TRẠNG THÁI nên nếu không chờ, flow có thể vào lại vài phút sau SL trên cùng trạng thái cũ.

Khối lượng: ký quỹ tầng đầu = VỐN HIỆN TẠI (vốn ban đầu + lãi/lỗ đã chốt, do engine cập nhật)
× order_size_pct%; tầng k = tầng k-1 × hệ số. Ngân sách một vị thế = vốn hiện tại lúc mở × max_capital_usage;
tầng nào vượt ngân sách thì bị bỏ qua. Vốn <= 0 -> không mở lệnh mới (cháy tài khoản).
PnL % của lệnh tính trên vốn lúc mở lệnh (để ghép lãi kép đúng trong WFA/Monte Carlo).

Hai móc TUỲ CHỌN cho thị trường không có sổ lệnh (AMM / DEX, chạy bằng tick — core/backtest/tick_run.py); mặc định tắt = hành vi cũ đúng từng bit:
- limit_taker=True: tầng DCA và chốt lời không phải lệnh limit chờ sẵn mà là swap thực hiện khi giá đi qua mức -> tính như lệnh market (phí taker + trượt giá).
- impact_fn(notional_usd, is_buy) -> tỉ lệ trượt giá, thay slippage_rate cho MỌI lệnh khớp kiểu taker và cho chi phí khứ hồi khi tính khối lượng (_risk_margin).
Kernel numba (core/backtest/kernel.py) KHÔNG hỗ trợ hai móc này: chỉ đường Python (PaperBook / tracker) dùng được; kernel từ chối tracker có móc.
"""
import itertools
import time
from operator import attrgetter
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.core.params.schema import StrategyParams
from backend.core.execute import policy
from backend.core.execute.account import Account, PositionBook
from backend.core.execute.events import Fill, FundingApplied
from backend.core.execute.ledger import CapitalLedger
from backend.core.execute.models import PositionModel, PositionStatus, PositionType

# Bộ đếm id toàn cục, tăng dần và không trùng (int(time.time()*1000) trùng khi
# nhiều lệnh mở trong cùng 1 ms). Bắt đầu từ epoch-ms * 1000 để vẫn sắp xếp theo thời gian.
_ID_SEQ = itertools.count(int(time.time() * 1000) * 1000)


def _next_id() -> int:
    return next(_ID_SEQ)


def _book_attr(name: str, doc: str = "") -> property:
    """Thuộc tính tracker uỷ quyền sang PositionBook (kế toán, P6.3) — kernel numba đọc/ghi qua đây nên cần setter."""
    return property(attrgetter(f"book.{name}"), lambda self, v: setattr(self.book, name, v), doc=doc)


class PositionTracker:
    """Theo dõi vòng đời vị thế của một flow: Entry -> DCA -> TP / SL / Trailing / Timeout / Liq / Exit."""

    def __init__(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        flow_name: str,
        params: StrategyParams,
        pos_type: PositionType,
        initial_capital: float = 10000.0,
        ledger: Optional[CapitalLedger] = None,
        limit_taker: bool = False,
        impact_fn: Optional[Callable[[float, bool], float]] = None,
    ):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.flow_name = flow_name
        self.params = params
        self.pos_type = pos_type
        self.is_long = pos_type == PositionType.LONG

        self.market = str(getattr(params, "market", "spot") or "spot").lower()
        if self.market not in ("spot", "perp"):
            raise ValueError(f"market phải là 'spot' hoặc 'perp', nhận '{self.market}'")
        if self.market == "spot" and not self.is_long:
            raise ValueError(f"Flow '{flow_name}': thị trường spot không bán khống được — dùng market='perp' cho SHORT.")
        self.leverage = 1.0 if self.market == "spot" else max(1.0, float(params.leverage or 1.0))
        self.mmr = max(0.0, float(getattr(params, "maintenance_margin_rate", 0.005) or 0.0))
        # Phí: taker cho lệnh market (vào ở open, SL, trailing, timeout, tín hiệu thoát);
        #      maker cho lệnh limit (tầng DCA, chốt lời). fee_rate cũ = taker.
        self.fee_rate = max(0.0, float(params.fee_rate or 0.0))
        maker = getattr(params, "maker_fee_rate", None)
        self.maker_fee_rate = self.fee_rate if maker is None else max(0.0, float(maker))
        self.slippage_rate = max(0.0, float(params.slippage_rate or 0.0))
        self.limit_taker = bool(limit_taker)    # AMM: DCA / chốt lời khớp như lệnh taker (phí taker + trượt giá)
        self.impact_fn = impact_fn              # (notional_usd, is_buy) -> trượt giá; None = slippage_rate cố định
        self.capital = float(initial_capital)
        self.capital_usage = max(0.0, min(float(params.max_capital_usage or 1.0), 1.0))
        account = ledger if ledger is not None else Account(self.capital, self.capital_usage)
        self.book = PositionBook(account, account_id, campaign_id, symbol, flow_name, pos_type)  # kế toán vị thế (P6.3)
        self.max_capital = self.capital * self.capital_usage

        # Giá trị gốc của tham số thoát lệnh; mỗi vị thế quy đổi sang % lúc vào lệnh (_apply_exit_unit).
        self.base_sl = max(0.0, float(params.stop_loss_rate or 0.0))
        self.base_tp = max(0.0, float(params.take_profit_rate or 0.0))
        self.base_trail = max(0.0, float(params.trailing_stop or 0.0))
        self.base_trail_act = max(0.0, float(getattr(params, "trailing_activation_pct", 0.0) or 0.0))
        self.timeout_ms = max(0, int(params.timeout or 0)) * 60_000
        self.cooldown_ms = max(0, int(getattr(params, "cooldown", 0) or 0)) * 60_000
        self.last_close_time: Optional[int] = None   # thời điểm đóng vị thế gần nhất (cho cooldown)
        self.dca_rejected = 0       # số tầng DCA bị từ chối vì hết ngân sách vốn (không đổi logic khớp lệnh)
        self.stop_fill = str(getattr(params, "stop_fill", "level") or "level").lower()
        # lệnh limit (tầng DCA, chốt lời) chỉ khớp khi giá đi QUA mức bấy nhiêu % (hàng đợi sổ lệnh); 0 = chạm là khớp
        self.limit_through = max(0.0, float(getattr(params, "limit_through_pct", 0.0) or 0.0)) / 100.0
        if self.stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{self.stop_fill}'")
        self.intrabar_path = str(getattr(params, "intrabar_path", "ohlc") or "ohlc").lower()
        if self.intrabar_path not in policy.INTRABAR_PATHS:
            raise ValueError(f"intrabar_path phải là một trong {policy.INTRABAR_PATHS}, nhận '{self.intrabar_path}'")
        self.exit_unit = str(getattr(params, "exit_unit", "pct") or "pct").lower()
        if self.exit_unit not in ("pct", "atr"):
            raise ValueError(f"exit_unit phải là 'pct' hoặc 'atr', nhận '{self.exit_unit}'")
        self.atr_frame = str(getattr(params, "atr_frame", "1h") or "1h")
        self.atr_period = int(getattr(params, "atr_period", 14) or 14)
        self.sizing = str(getattr(params, "sizing", "margin_pct") or "margin_pct").lower()
        if self.sizing not in ("margin_pct", "risk"):
            raise ValueError(f"sizing phải là 'margin_pct' hoặc 'risk', nhận '{self.sizing}'")
        self.risk_pct = max(0.0, float(getattr(params, "risk_per_trade_pct", 0.5) or 0.0))
        self.max_notional_pct = max(0.0, float(getattr(params, "max_notional_pct", 100.0) or 0.0))
        if self.sizing == "risk" and self.base_sl <= 0:
            raise ValueError(f"Flow '{flow_name}': sizing='risk' cần stop_loss_rate > 0 (rủi ro đo tại SL).")

        layers = max(0, int(getattr(params, "dca_max_layers", 0) or 0))
        step = float(getattr(params, "dca_step_pct", 0.0) or 0.0)
        mult = float(getattr(params, "dca_size_multiplier", 1.0) or 1.0)
        steps = [float(x) for x in (params.dca_steps or [])] or ([step] * layers if step > 0 else [])
        mults = [float(x) for x in (params.dca_multipliers or [])] or [mult] * len(steps)
        if len(mults) < len(steps):
            mults += [mults[-1] if mults else 1.0] * (len(steps) - len(mults))
        if any(s <= 0 for s in steps) or any(m <= 0 for m in mults):
            raise ValueError("Bước DCA và hệ số khối lượng phải > 0")
        self.base_dca_steps = [abs(s) for s in steps]
        self.dca_mults = mults[: len(steps)]
        self.max_leverage = self.leverage
        self.pos_leverage = self.leverage
        self.planned_risk = 0.0
        self.max_new_notional = float("inf")  # trần danh nghĩa cho lệnh sắp mở (do danh mục đặt theo max_gross_exposure)
        self.max_new_risk = float("inf")      # trần rủi ro (tới SL, cả rổ DCA) cho lệnh sắp mở (danh mục: max_open_risk_pct)
        self.risk_scale = 1.0                 # hệ số rủi ro do danh mục đặt (giảm theo mức sụt vốn: dd_throttle_pct)
        self.unit_pct = 0.0
        self.pending_vol = float("nan")
        self.skipped_no_vol = 0     # tín hiệu vào lệnh nhưng chưa có ATR (giai đoạn khởi động)
        self._apply_exit_unit(1.0)
        self.order_size_pct = max(0.0, float(params.order_size_pct or 0.0))

        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        self.match_tree = self._combine_conditions(ast.get("match", []))
        self.stop_tree = self._combine_conditions(ast.get("stop", []))
        # Điều kiện cho phép DCA (dồn có điều kiện): rỗng = luôn được dồn. Giá trị ở nến đã đóng t áp cho các mức DCA trong nến t+1.
        self.dca_tree = self._combine_conditions(ast.get("dca", []))
        self.dca_ok = True

        self.is_open = False
        self.pending_entry = False
        self.pending_exit = False
        self._reset_state()

    def _apply_exit_unit(self, unit: float) -> None:
        """Quy đổi tham số thoát lệnh sang % cho vị thế sắp mở (unit = 1 với exit_unit='pct', = ATR% với 'atr').
        Đặt lại từ giá trị gốc mỗi vị thế: các tầng DCA bị bỏ vì hết vốn ở vị thế trước không ảnh hưởng vị thế sau."""
        (self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct,
         self.dca_steps) = policy.exit_params_scaled(unit, self.base_sl, self.base_tp, self.base_trail,
                                                     self.base_trail_act, self.base_dca_steps)

    # ─── Trạng thái ─────────────────────────────────────────────────────────
    # Kế toán nằm ở PositionBook (account.py); các thuộc tính dưới đây là cửa sổ vào book (tracker/kernel đọc ghi như cũ).
    qty = _book_attr("qty")
    avg = _book_attr("avg")
    margin_used = _book_attr("margin_used")
    fees_paid = _book_attr("fees_paid")
    layer_count = _book_attr("layer_count")
    last_fill = _book_attr("last_fill")
    entry_time = _book_attr("entry_time")
    reserved_here = _book_attr("reserved_here", "tiền đã giữ chỗ trong sổ vốn cho vị thế này")
    funding_paid = _book_attr("funding_paid", "funding đã trả (+) / nhận (−), đã hạch toán thẳng vào sổ vốn")
    entry_equity = _book_attr("entry_equity")
    position = _book_attr("position")
    orders = _book_attr("orders")

    @property
    def ledger(self) -> Account:
        return self.book.account

    @ledger.setter
    def ledger(self, account: Account) -> None:
        self.book.account = account

    def _reset_state(self) -> None:
        self.book.reset()          # qty, avg, ký quỹ, phí, tầng, giữ chỗ, funding, entry_equity = vốn hiện tại
        self.next_margin = 0.0
        self.peak = 0.0
        self.mae_usd = 0.0

    @property
    def equity(self) -> float:
        """Vốn đã chốt hiện tại (dùng chung giữa các flow qua CapitalLedger)."""
        return self.ledger.equity

    @property
    def avg_entry_price(self) -> float:
        return self.avg

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.is_open or self.qty <= 0:
            return 0.0
        return self.book.unrealized_pnl(price)  # funding đã nằm trong ledger.equity

    def apply_funding(self, rate: float, price: float, t: int = 0) -> float:
        """Funding perp: long trả qty·giá·rate khi rate > 0 (short nhận), và ngược lại. Hạch toán ngay."""
        if not self.is_open or self.market != "perp" or self.qty <= 0:
            return 0.0
        payment = policy.funding_payment(self.qty, price, rate, self.is_long)
        return self.book.apply_funding(FundingApplied(self.book.slot, t, rate, price, payment))

    def _liq_price(self) -> Optional[float]:
        if self.market != "perp" or self.qty <= 0:
            return None
        return policy.liq_price(self.avg, self.pos_leverage, self.mmr, self.is_long)

    def _reached(self, level: float, extreme: float) -> bool:
        return policy.reached(level, extreme, self.is_long)

    def _gap_fill(self, level: float, open_price: float) -> float:
        """Giá khớp khi chạm mức: nếu open đã vượt qua mức (gap) thì khớp ở open."""
        return policy.gap_fill(level, open_price, self.is_long)

    def _slip(self, notional: float, is_buy: bool) -> float:
        """Tỉ lệ trượt giá của một lệnh taker: impact_fn theo khối lượng (AMM) hoặc slippage_rate cố định."""
        return policy.slip_rate(self.slippage_rate, self.impact_fn, notional, is_buy)

    def _cost(self, notional: float) -> float:
        """Chi phí KHỨ HỒI (phí taker + trượt giá) tính trên danh nghĩa `notional` — dùng chia rủi ro / khối lượng."""
        return policy.round_trip_cost(self.fee_rate, self.slippage_rate, self.impact_fn, notional)

    # ─── Hành động ──────────────────────────────────────────────────────────
    def _add_layer(self, t: int, price: float, margin: float, market_order: bool, reason: str) -> bool:
        notional = margin * self.pos_leverage
        taker = market_order or self.limit_taker
        slip = self._slip(notional, self.is_long) if taker else 0.0
        fill = policy.entry_fill_price(price, slip, self.is_long) if taker else price
        fee = policy.entry_fee(notional, self.fee_rate if taker else self.maker_fee_rate)
        first = self.book.position is None
        kind = "entry" if first else "dca"
        if margin <= 0 or fill <= 0 or not self.book.can_add(margin, fee, self.max_capital):
            self.book.reject("budget", kind)       # vượt ngân sách vị thế: không đổi sổ vốn
            return False
        if not self.ledger.can_reserve(margin + fee):
            self.book.reject("capital", kind)      # không giữ chỗ được từ vốn trống: ledger.rejected += 1
            return False
        self.book.apply_fill(Fill(
            slot=self.book.slot, order_id=_next_id(), kind=kind, t=t, price=fill, raw_price=price, notional=notional,
            margin=margin, fee=fee, slip=slip, liquidity="taker" if taker else "maker", reason=reason,
            unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
        if first:
            self.peak = fill
        self.is_open = True
        return True

    def _open(self, t: int, open_price: float) -> None:
        if self.equity <= 0:
            return  # cháy tài khoản: không mở lệnh mới
        unit = 1.0
        if self.exit_unit == "atr":
            unit = self.pending_vol
            if not (unit > 0):  # NaN khi chưa đủ nến khởi động ATR
                self.skipped_no_vol += 1
                return
        self._apply_exit_unit(unit)
        self.unit_pct = unit if self.exit_unit == "atr" else 0.0
        self.entry_equity = self.equity
        self.max_capital = self.equity * self.capital_usage
        budget = min(self.max_capital, self.ledger.free())
        self.pos_leverage = self.max_leverage
        self.planned_risk = 0.0
        if self.sizing == "risk":
            margin = self._risk_margin()
        else:
            margin = policy.flat_margin(self.equity, self.order_size_pct)
        if self.risk_scale != 1.0:                            # danh mục đang sụt vốn: thu nhỏ lệnh mới
            margin = margin * self.risk_scale
            self.planned_risk = self.planned_risk * self.risk_scale
        margin = policy.clamp_margin(margin, budget, self.pos_leverage, self.fee_rate, self.max_new_notional)
        if self.sizing == "risk" and margin > 0:
            total_mult = self._layer_mult_total()
            self.planned_risk = min(self.planned_risk, policy.planned_risk_cap(
                margin, self.pos_leverage, self.sl_pct,
                self._cost(margin * self.pos_leverage * total_mult), total_mult))
        # vượt trần rủi ro đang mở của danh mục
        margin, self.planned_risk = policy.apply_risk_ceiling(margin, self.planned_risk, self.max_new_risk)
        if margin <= 0:
            self.book.reject("no_margin", "entry")  # tín hiệu vào lệnh nhưng không còn vốn trống: ledger.rejected += 1
            return
        if self._add_layer(t, open_price, margin, market_order=True, reason="Tín hiệu vào lệnh (AST match)"):
            self.next_margin = margin

    def _layer_mult_total(self) -> float:
        """Tổng khối lượng các tầng (lệnh đầu = 1) theo hệ số DCA."""
        return policy.layer_mult_total(self.dca_mults, len(self.dca_steps))

    def _risk_margin(self) -> float:
        """Khối lượng theo rủi ro: nếu chạm SL (tính cả mọi tầng DCA dự kiến và phí khứ hồi taker + trượt)
        thì mất ~risk_per_trade_pct% vốn. Danh nghĩa bị chặn bởi max_notional_pct% vốn.
        Perp: đòn bẩy thực = min(đòn bẩy tham số, mức để giá thanh lý cách giá vào >= 1,5 × khoảng SL)."""
        margin, self.pos_leverage, self.planned_risk = policy.risk_margin(
            self.equity, self.risk_pct, self.max_notional_pct, self.sl_pct, self.fee_rate, self.slippage_rate,
            self.impact_fn, self.market == "perp", self.max_leverage, self.mmr, self.pos_leverage,
            self._layer_mult_total())
        return margin

    def _close(self, t: int, raw_price: float, status: PositionStatus, reason: str, market_order: bool,
               kind: str = "exit") -> PositionModel:
        taker = market_order or self.limit_taker
        slip = 0.0
        if taker and status != PositionStatus.LIQ:
            slip = self._slip(self.qty * raw_price, not self.is_long)
            price = policy.exit_fill_price(raw_price, slip, self.is_long)
        else:
            price = raw_price
        exit_fee = policy.exit_fee(self.qty, price, self.fee_rate if taker or status == PositionStatus.LIQ else self.maker_fee_rate)
        pos = self.book.apply_close(Fill(
            slot=self.book.slot, order_id=_next_id(), kind=kind, t=t, price=price, raw_price=raw_price, notional=0.0,
            margin=0.0, fee=exit_fee, slip=slip,
            liquidity="liquidation" if status == PositionStatus.LIQ else ("taker" if taker else "maker"),
            reason=reason, status=int(status), mae_usd=self.mae_usd))
        self.is_open = False
        self.pending_exit = False
        self.last_close_time = t
        self._reset_state()
        return pos

    def _status_by_pnl(self, price: float) -> PositionStatus:
        return PositionStatus.TP if policy.in_profit(price, self.avg, self.is_long) else PositionStatus.SL

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Xử lý một nến 1m có giao dịch. Trả vị thế vừa đóng (nếu có).
        vol = ATR% (natr) của khung atr_frame đã đóng tại cuối nến này — dùng khi lệnh vào chờ được đặt ở nến này.
        dca_gate = điều kiện DCA tại cuối nến này (True khi chiến lược không có điều kiện) — quyết định nến SAU có được dồn tầng không."""
        closed: Optional[PositionModel] = None

        # 1. Đầu nến
        if self.is_open:
            if self.pending_exit:
                closed = self._close(t, o, self._status_by_pnl(o), "Tín hiệu thoát (AST stop)", market_order=True, kind="exit")
            elif self.timeout_ms and t - self.entry_time >= self.timeout_ms:
                closed = self._close(t, o, self._status_by_pnl(o), "Hết thời gian giữ lệnh", market_order=True, kind="timeout")
        if closed is None and not self.is_open and self.pending_entry:
            self.pending_entry = False
            if can_open:
                self._open(t, o)

        # 2-3. Trong nến
        if self.is_open and closed is None:
            self.book.mark(h, l)
            closed = self._intrabar(t, o, h, l, c)

        # 4. Cuối nến
        if self.is_open:
            adverse = l if self.is_long else h
            self.mae_usd = min(self.mae_usd, self.unrealized_pnl_usd(adverse))
            self.peak = max(self.peak, h) if self.is_long else min(self.peak, l)
            if stop_signal:
                self.pending_exit = True
        elif closed is None and entry_signal and (
                not self.cooldown_ms or self.last_close_time is None or t - self.last_close_time >= self.cooldown_ms):
            self.pending_entry = True
            self.pending_vol = vol
        self.dca_ok = bool(dca_gate)
        return closed

    def _intrabar(self, t: int, o: float, h: float, l: float, c: float) -> Optional[PositionModel]:
        if self.intrabar_path == "adverse_first":
            return self._intrabar_adverse_first(t, o, h, l)
        return self._intrabar_path(t, o, h, l, c)

    def _intrabar_path(self, t: int, o: float, h: float, l: float, c: float) -> Optional[PositionModel]:
        """Đường ohlc / adaptive (xem docstring module): mỗi chặng là một tick; SL / TP cố định cả nến."""
        is_long = self.is_long
        sign = 1.0 if is_long else -1.0
        adverse = l if is_long else h
        sl_lv = policy.sl_level(self.avg, self.sl_pct, sign) if self.sl_pct else None     # lệnh bảo vệ đã nằm trên sàn từ cuối nến trước
        tp_lv = tp_need = 0.0
        if self.tp_pct:
            tp_lv = policy.tp_level(self.avg, self.tp_pct, sign)
            tp_need = policy.tp_need(tp_lv, self.limit_through, sign)
        peak = self.peak                    # đỉnh/đáy có lợi chạy dọc đường giá (cho trailing)
        dca_filled = False
        prev = o
        for i, p in enumerate(policy.bar_points(self.intrabar_path, o, h, l, c)):
            if i and p == prev:
                continue                    # chặng không đổi giá: không có tick (Nautilus bỏ qua)
            at_open = i == 0
            # (a) nhóm DCA: mọi tầng bị tick xuyên qua, tầng kế tính từ giá khớp gần nhất
            while True:
                k = self.layer_count - 1
                if not (k < len(self.dca_steps) and self.dca_ok):
                    break
                dca_level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
                if not policy.reached(policy.dca_trigger(dca_level, self.limit_through, sign), p, is_long):
                    break
                price = self._gap_fill(dca_level, o) if self.limit_taker else dca_level   # limit khớp ở mức; AMM (swap) khớp ở open
                margin = self.next_margin * self.dca_mults[k]
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    dca_filled = True
                    continue
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: k]  # hết vốn: không nhồi thêm tầng nào nữa
            # (b) chốt lời (limit chờ sẵn từ avg đầu nến)
            if self.tp_pct and policy.tp_hit(p, tp_need, is_long):
                price = policy.tp_fill_price(tp_lv, o, is_long) if self.limit_taker else tp_lv
                return self._close(t, price, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=False, kind="tp")
            # (c) nhóm stop: SL (mức cố định), trailing (từ đỉnh sau chặng trước), thanh lý (tính từ avg hiện tại)
            events: List[Tuple[float, int, str]] = []
            if sl_lv is not None:
                events.append((sl_lv, 0, "sl"))
            if self.trail_pct and policy.trail_active(peak, self.avg, self.trail_activation_pct, sign):
                events.append((policy.trail_level(peak, self.trail_pct, sign), 0, "trail"))
            liq = self._liq_price()
            if liq is not None and liq > 0:
                events.append((liq, 0, "liq"))
            reached = [e for e in events if policy.reached(e[0], p, is_long)]
            if reached:
                level, _, kind = policy.pick_first_touched(reached, is_long)
                price = policy.tick_stop_price(level, o, is_long, at_open)
                if kind == "liq":
                    return self._close(t, price, PositionStatus.LIQ, "Thanh lý (perp)", market_order=False, kind="liq")
                if self.stop_fill == "extreme":
                    price = policy.stop_extreme_fill(price, adverse, is_long)
                if kind == "sl":
                    return self._close(t, price, PositionStatus.SL, "Stop-loss (từ giá TB)", market_order=True, kind="sl")
                return self._close(t, price, self._status_by_pnl(price), "Trailing stop", market_order=True, kind="trail")
            peak = policy.peak_step(peak, p, is_long)
            prev = p
        # Cuối nến: SL / TP đặt lại từ avg mới (sau fill DCA) thấy sổ lệnh ở close; TP mới đã "trong giá" -> khớp ngay ở close (taker)
        if dca_filled and self.tp_pct:
            tp_new = policy.tp_level(self.avg, self.tp_pct, sign)
            if policy.tp_hit(c, tp_new, is_long):
                return self._close(t, c, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=True, kind="tp")
        return None

    def _intrabar_adverse_first(self, t: int, o: float, h: float, l: float) -> Optional[PositionModel]:
        adverse = l if self.is_long else h
        favorable = h if self.is_long else l
        sign = 1.0 if self.is_long else -1.0
        dca_filled = False
        sl_stale: Optional[float] = None    # mức SL CŨ còn hiệu lực sau tầng DCA đầu tiên của nến (sl_pct > 0)

        while True:
            events: List[Tuple[float, int, str]] = []  # (mức, ưu tiên khi hoà: thoát trước, loại)
            k = self.layer_count - 1
            dca_level = None
            if k < len(self.dca_steps) and self.dca_ok:
                dca_level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
                trigger = policy.dca_trigger(dca_level, self.limit_through, sign)
                events.append((trigger, 1, "dca"))
            if self.sl_pct:
                events.append((sl_stale if sl_stale is not None else policy.sl_level(self.avg, self.sl_pct, sign), 0, "sl"))
            if self.trail_pct:
                if policy.trail_active(self.peak, self.avg, self.trail_activation_pct, sign):
                    events.append((policy.trail_level(self.peak, self.trail_pct, sign), 0, "trail"))
            liq = self._liq_price()
            if liq is not None and liq > 0:
                events.append((liq, 0, "liq"))
            reached = [e for e in events if self._reached(e[0], adverse)]
            if not reached:
                break
            # long: mức cao nhất bị chạm trước khi giá rơi xuống; short: mức thấp nhất
            level, _, kind = policy.pick_first_touched(reached, self.is_long)
            price = self._gap_fill(level, o)
            if kind == "dca":
                # lệnh limit chờ sẵn khớp đúng ở giá đặt kể cả khi gap qua mức; AMM (limit_taker) là swap -> khớp ở open
                price = self._gap_fill(dca_level, o) if self.limit_taker else dca_level
                margin = self.next_margin * self.dca_mults[k]
                sl_before = policy.sl_level(self.avg, self.sl_pct, sign) if self.sl_pct else None   # SL đang nằm trên sàn trước fill
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    if not dca_filled:
                        sl_stale = sl_before            # SL cũ chưa dời kịp trong phần còn lại của nến
                    dca_filled = True
                    continue
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: k]  # hết vốn: không nhồi thêm tầng nào nữa
                continue
            if kind == "liq":
                return self._close(t, price, PositionStatus.LIQ, "Thanh lý (perp)", market_order=False, kind="liq")
            if self.stop_fill == "extreme":
                # Bi quan: lệnh stop-market khớp ở giá xấu nhất của nến (cú giật xuyên mức trong nến).
                price = policy.stop_extreme_fill(price, adverse, self.is_long)
            if kind == "sl":
                return self._close(t, price, PositionStatus.SL, "Stop-loss (từ giá TB)", market_order=True, kind="sl")
            return self._close(t, price, self._status_by_pnl(price), "Trailing stop", market_order=True, kind="trail")

        if self.tp_pct and not dca_filled:
            tp_level = policy.tp_level(self.avg, self.tp_pct, sign)
            need = policy.tp_need(tp_level, self.limit_through, sign)
            if policy.tp_hit(favorable, need, self.is_long):
                price = policy.tp_fill_price(tp_level, o, self.is_long) if self.limit_taker else tp_level   # limit khớp ở mức TP
                return self._close(t, price, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=False, kind="tp")
        return None

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        if not self.is_open:
            return None
        self.pending_entry = False
        return self._close(t, raw_price, PositionStatus.CANCEL, reason, market_order=True,
                           kind="kill" if reason.startswith("Kill") else "end")

    @staticmethod
    def _combine_conditions(blocks: List[Dict[str, Any]]) -> List[Any]:
        combined: List[Any] = []
        if not isinstance(blocks, list):
            return combined
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("condition", []), list):
                combined.extend(block.get("condition", []))
        return combined
