"""NoraSlotStrategy (P15): MỘT Strategy của Nautilus cho mỗi (chiến lược × tài sản) — ngữ nghĩa PositionManager cũ trên lệnh Nautilus.

Tín hiệu (match / stop / vol / dca) tính SẴN bằng backend.signal.compute (cùng đường dữ liệu engine cũ) và tra theo open_time của nến khung chạy
(ts_event của Bar = open_time + độ dài khung). Lệnh, khớp, phí, số dư, vị thế do Nautilus sinh; strategy chỉ quyết định.

Quy ước thời điểm (khác engine cũ, ghi trong kết quả `fill_convention`): engine cũ vào lệnh ở GIÁ MỞ nến kế tiếp; Nautilus (bar_execution) khớp lệnh
market gửi lúc nến i ĐÓNG ngay ở giá đóng nến i. Mọi quyết định cuối nến (vào / thoát theo tín hiệu / timeout / kill / end) vì vậy khớp ở close nến i.

Loại lệnh (Nautilus `tags[0]`): ENTRY, DCA, SL, TP, TRAIL, EXIT, TIMEOUT, END, KILL.
- SL    = STOP_MARKET reduce_only tại policy.sl_level(avg) (hoặc mức tuyệt đối khi sl_anchor entry/last_layer).
- TP    = LIMIT reduce_only tại policy.tp_level(avg).
- TRAIL = TRAILING_STOP_MARKET gốc của Nautilus (BASIS_POINTS = trailing_stop%·100, activation_price = tp_level(avg, activation%)).
          Tương đương chính sách cũ (kích hoạt khi lãi tại đỉnh >= activation, mức = đỉnh · (1 − trail%)); sau DCA đặt lại với trigger_price từ đỉnh.
- DCA   = LIMIT tại policy.dca_level(last_fill); mỗi lần DCA khớp, SL/TP được `modify_order` (qty + giá từ avg mới), TRAIL đặt lại.
"""
import os
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import LiquiditySide, OrderSide, TrailingOffsetType, TriggerType
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.analys.position import position_size as policy
from backend.models.models import OrderModel, OrderType, PositionModel, PositionStatus, next_id

FLAT, ENTERING, OPEN, EXITING = 0, 1, 2, 3
REASONS = {"ENTRY": "Tín hiệu vào lệnh (AST match)", "DCA": "DCA", "EXIT": "Tín hiệu thoát (AST stop)", "TIMEOUT": "Hết thời gian giữ lệnh",
           "SL": "Stop-loss (từ giá TB)", "TRAIL": "Trailing stop", "TP": "Take-profit (từ giá TB)", "END": "End of Backtest",
           "KILL": "Kill switch danh mục", "STOP": "Người dùng dừng bot"}
_ENTRY_KINDS = ("ENTRY", "DCA")
_NS_MS = 1_000_000
CATCHUP_DELAY_S = 5.0          # live: chờ kết nối dữ liệu/sổ lệnh ổn rồi mới vào lệnh bù


from backend.analys.signal import SignalProvider, ArraySignals


class NoraSlotStrategy(Strategy):
    def __init__(self, idx: int, spec: Any, strategy_id: str, symbol: str, sym_idx: int, instrument: CryptoPerpetual, bar_type: BarType,
                 frame_ms: int, sig: Union[Dict[str, Any], SignalProvider], coord: Any, last_open_ms: Optional[int], close_at_end: bool, trade_start_ms: int,
                 hyphens: bool = True, claim_external: bool = False):
        # hyphens=False (live): OKX chỉ nhận clOrdId chữ-số (không dấu gạch) -> Nautilus sinh id không gạch
        # claim_external (live resume): lệnh/vị thế sàn đã đối soát trên instrument này thuộc chiến lược -> nó nhận lại và quản lý tiếp
        super().__init__(StrategyConfig(strategy_id=f"NORA-{idx:03d}", order_id_tag=f"{idx:03d}", use_hyphens_in_client_order_ids=hyphens,
                                        external_order_claims=[instrument.id] if claim_external else None))
        self.spec, self.sid, self.symbol, self.sym_idx = spec, strategy_id, symbol, sym_idx
        self.inst, self.bar_type, self.fr = instrument, bar_type, int(frame_ms)
        self.coord, self.close_at_end, self.trade_start = coord, bool(close_at_end), int(trade_start_ms)
        self.last_open_ms = last_open_ms
        self.is_long = bool(spec.is_long)
        self.sign = 1.0 if self.is_long else -1.0
        self.side_in = OrderSide.BUY if self.is_long else OrderSide.SELL
        self.side_out = OrderSide.SELL if self.is_long else OrderSide.BUY
        # Tín hiệu qua SignalProvider (ArraySignals cho backtest, LiveSignals cho live)
        if isinstance(sig, SignalProvider):
            self.signals: SignalProvider = sig
        else:
            self.signals = ArraySignals(sig, self.fr)
        if isinstance(self.signals, ArraySignals):
            self.sig_t, self.sig_match, self.sig_stop = self.signals.sig_t, self.signals.sig_match, self.signals.sig_stop
            self.sig_vol, self.sig_dca = self.signals.sig_vol, self.signals.sig_dca
        else:
            self.sig_t, self.sig_match, self.sig_stop = [], [], []
            self.sig_vol, self.sig_dca = None, None
        self._p = 0
        self._last_bar_ts = -1
        self.enter_on_start = False    # live: ngay sau khi node chạy (CATCHUP_DELAY_S), vào lệnh bù MỘT lần nếu nến tín hiệu đóng gần nhất (từ lịch sử) có match — không chờ nến khung chạy đầu tiên
        self.catchup_done = False
        self.mult = 1.0
        self.reduce_only = True        # OKX demo/live từ chối reduce-only cho lệnh bảo vệ (điều kiện): live đặt False — vị thế NETTING + huỷ hết lệnh chờ khi thoát nên không đảo vị thế
        self.protect_retry = False     # live: sàn từ chối lệnh reduce-only vì vị thế chưa kịp ghi nhận -> đặt lại SL/TP/TRAIL ở nến kế
        self.own_orders_only = False   # live: chỉ huỷ lệnh của chính chiến lược (tài khoản sàn dùng chung nhiều bot)
        self.resume = False            # live: bot chạy lại sau khi tiến trình chết -> nhận vị thế đã đối soát ở nến/khởi động đầu tiên
        self.bar_ts_shift_ms = 0       # live: chuẩn hoá ts_event của adapter về "giờ đóng nến" nếu khác catalog (đo lúc chạy thật)
        self.nbar = 0
        self.last_bar_wall = 0.0
        self.debug_events = os.environ.get("NORA_DEBUG_EVENTS", "") not in ("", "0", "false")   # live: sự kiện chẩn đoán bar_seen / sig_beat / signal (mặc định tắt)
        self.last_blk = -2
        self.skipped_no_vol = 0
        self.dca_rejected = 0
        self.last_close_time: Optional[int] = None      # trục open_time (ms) như engine cũ
        self.last_close_fill_ts = -1
        self.dca_ok = True
        self.halted = False
        self.last_model: Optional[PositionModel] = None
        self.last_model_ts = -1
        self._reset()


    # ─── trạng thái một vị thế ──────────────────────────────────────────────
    def _reset(self) -> None:
        self.st = FLAT
        self.qty = 0.0
        self.avg = 0.0
        self.layers = 0
        self.last_fill = 0.0
        self.next_margin = 0.0
        self.margin_used = 0.0
        self.res_here = 0.0
        self.fee_open = 0.0
        self.planned_risk = 0.0
        self.pos_lev = float(self.spec.max_leverage)
        self.unit_pct = 0.0
        self.entry_equity = 0.0
        self.entry_time = 0
        self.entry_margin = self.entry_notional = self.entry_fee = 0.0
        self.max_price = self.min_price = 0.0
        self.peak = 0.0
        self.mae_usd = 0.0
        self.pending_qty = 0.0
        self.sl_lvl_abs = 0.0
        self.t_fills: List[tuple] = []
        self._layer_of: Dict[Any, int] = {}
        self.exit_kind: Optional[str] = None
        self.o: Dict[str, Any] = {"SL": None, "TP": None, "TRAIL": None, "DCA": None}
        self._dca_margin = 0.0
        self._apply_unit(1.0)

    def _apply_unit(self, unit: float) -> None:
        sp = self.spec
        self.sl_pct, self.tp_pct, self.trail_pct, self.trail_act, self.dca_steps = policy.exit_params_scaled(
            unit, sp.base_sl, sp.base_tp, sp.base_trail, sp.base_trail_act, sp.base_dca_steps)

    def exposure_qty(self) -> float:
        return self.qty if self.st in (OPEN, EXITING) else self.pending_qty

    def unrealized(self, price: float) -> float:
        return self.qty * (price - self.avg) * self.sign

    # ─── vòng đời ───────────────────────────────────────────────────────────
    def on_start(self) -> None:
        live_inst = self.cache.instrument(self.inst.id)       # live: instrument THẬT của sàn (adapter nạp) thay bản dựng từ instruments.json; backtest: cùng đối tượng
        if live_inst is not None:
            self.inst = live_inst
        self.mult = float(self.inst.multiplier)               # coin mỗi 1 đơn vị số lượng của sàn (OKX: ctVal); catalog/backtest = 1
        if self.resume:
            self.adopt_position(int(self.clock.timestamp_ns() // _NS_MS))
        self.subscribe_bars(self.bar_type)
        if not isinstance(self.signals, ArraySignals):          # live: hẹn một lần sau khi node chạy: vào lệnh bù (nếu bật) hoặc chỉ nạp trạng thái tín hiệu cho heartbeat
            self.clock.set_time_alert(name=f"nora_catchup_{self.sid}_{self.symbol}", callback=self._on_catchup_alert,
                                      alert_time=self.clock.utc_now() + timedelta(seconds=CATCHUP_DELAY_S))

    def _on_catchup_alert(self, event) -> None:
        now = int(event.ts_event // _NS_MS)
        if self.enter_on_start and not self.catchup_done:
            self.run_catch_up(now)
        else:
            self._seed_heartbeat(now)

    def _seed_heartbeat(self, now_ms: int) -> None:
        rec = getattr(self.coord, "recorder", None)
        ev = self.signals.latest_event(now_ms) if hasattr(self.signals, "latest_event") else None
        if rec is not None and ev is not None and hasattr(rec, "seed_signal"):
            rec.seed_signal(self.symbol, int(ev.get("last_open_time") or 0) + self.fr, ev)

    def _ref_price(self) -> float:
        """Giá tham chiếu để cỡ lệnh bù: quote thật (mid) > giá cuối của cache > đóng nến cuối của lịch sử tín hiệu."""
        try:
            q = self.cache.quote_tick(self.inst.id)
            if q is not None:
                return (q.bid_price.as_double() + q.ask_price.as_double()) / 2.0
            from nautilus_trader.model.enums import PriceType
            px = self.cache.price(self.inst.id, PriceType.LAST)
            if px is not None:
                return px.as_double()
        except Exception:
            pass
        df = getattr(self.signals, "frames", {}).get(getattr(self.signals, "base_frame", ""))
        return float(df["close"].iloc[-1]) if df is not None and len(df) else float("nan")

    def run_catch_up(self, now_ms: int, price: Optional[float] = None) -> bool:
        """Vào lệnh bù MỘT lần (idempotent) từ nến tín hiệu đóng gần nhất trong lịch sử. False nếu đã chạy / không có giá."""
        if self.catchup_done:
            return False
        px = float(price) if price is not None else self._ref_price()
        if not (px > 0):
            return False
        self.catchup_done = True
        self.enter_on_start = False
        if self.coord.last[self.sym_idx][0] != self.coord.last[self.sym_idx][0]:
            self.coord.last[self.sym_idx] = (px, px, px)
        self._catch_up(px, now_ms)
        return True

    def on_bar(self, bar: Bar) -> None:
        ts = bar.ts_event // _NS_MS + self.bar_ts_shift_ms
        if not isinstance(self.signals, ArraySignals):          # live: bỏ nến lặp / cũ (WS gửi lại sau khi nối lại)
            if ts <= self._last_bar_ts:
                return
            self._last_bar_ts = ts
            o, h, l, c = bar.open.as_double(), bar.high.as_double(), bar.low.as_double(), bar.close.as_double()
            # khối lượng nến của adapter = HỢP ĐỒNG; lịch sử (catalog/REST) = vol_quote (USDT): quy đổi xấp xỉ bằng giá điển hình (chỉ ảnh hưởng chỉ báo dùng volume)
            self.signals.on_base_bar(ts, o, h, l, c, bar.volume.as_double() * self.mult * (h + l + c) / 3.0)
        if not isinstance(self.signals, ArraySignals):
            self.last_bar_wall = time.time()                                   # live: DataWatch dùng để phát hiện đứng dữ liệu
        if not isinstance(self.signals, ArraySignals) and self.nbar < 3 and self.debug_events:     # live: xác nhận nến WS tới được slot (3 nến đầu mỗi slot)
            self.coord.emit("bar_seen", {"symbol": self.symbol, "strategy": self.sid, "ts": ts, "close": bar.close.as_double()})
        try:
            self._on_bar(bar, ts)
        finally:
            self.coord.bar_done(ts)

    def _catch_up(self, price: float, ts: int) -> None:
        """enter_on_start: cùng luật vào lệnh (admit, cỡ lệnh, SL/TP/TRAIL) như vào thường, chỉ trễ tới lúc khởi động. Ghi sự kiện `catchup` vào events.jsonl."""
        ev = self.signals.latest_event(ts) if hasattr(self.signals, "latest_event") else None
        entered = False
        if self.st == FLAT and ev is not None and ev.get("match") and self.coord.halted_at is None and not self.halted:
            self._enter(price, ev.get("vol", float("nan")), catchup=True)
            entered = self.st == ENTERING
        self.coord.emit("catchup", {"symbol": self.symbol, "strategy": self.sid, "match": bool(ev and ev.get("match")), "signal_open_time": ev.get("signal_open_time") if ev else None,
                                    "last_signal_open_time": ev.get("last_open_time") if ev else None, "stop": bool(ev and ev.get("stop")), "entered": entered, "price": price})
        rec = getattr(self.coord, "recorder", None)
        if rec is not None and ev is not None and hasattr(rec, "seed_signal"):
            rec.seed_signal(self.symbol, int(ev.get("last_open_time") or 0) + self.fr, ev)

    def _signal_index(self, open_ms: int) -> int:
        t, p = self.sig_t, self._p
        n = len(t)
        while p < n and t[p] < open_ms:
            p += 1
        self._p = p
        return p if p < n and t[p] == open_ms else -1

    def _on_bar(self, bar: Bar, ts: int) -> None:
        self.nbar += 1
        rec = getattr(self.coord, "recorder", None) if self.coord is not None else None
        if rec is not None:
            rec.record_bar(self.symbol, bar, ts)

        if self.st == FLAT and hasattr(self.signals, "match_close_ts") and ts not in self.signals.match_close_ts:
            c = bar.close.as_double()
            if self.coord is not None:
                self.coord.last[self.sym_idx] = (c, c, c)
            if self.last_model is not None and self.last_model_ts == ts:
                m = self.last_model
                h = bar.high.as_double()
                l = bar.low.as_double()
                m.max_price, m.min_price = max(m.max_price, h), min(m.min_price, l)
            return

        open_ms = ts - self.fr
        h, l, c = bar.high.as_double(), bar.low.as_double(), bar.close.as_double()
        if self.coord is not None:
            self.coord.last[self.sym_idx] = (c, l, h)
        if self.last_model is not None and self.last_model_ts == ts:      # vị thế vừa đóng TRONG nến này: nến đóng vẫn tính vào max/min giá
            m = self.last_model
            m.max_price, m.min_price = max(m.max_price, h), min(m.min_price, l)
        if self.enter_on_start and not self.catchup_done:       # dự phòng: nến tới trước hẹn giờ vào lệnh bù
            self.run_catch_up(ts, c)
        sig_val = self.signals.at(ts)
        has_sig = sig_val is not None
        if rec is not None:
            rec.record_heartbeat(self.symbol, ts, self.nbar, sig_val if has_sig else None)
            if hasattr(rec, "record_signal") and not isinstance(self.signals, ArraySignals):
                rec.record_signal(self.symbol, self.sid, ts, sig_val)         # live: mỗi nến một dòng tín hiệu gọn (signals.jsonl) cho kiểm tra đồng nhất Tầng 2
        sig_frames = getattr(self.signals, "frames", {})
        sig_err = getattr(self.signals, "last_error", None)
        if self.coord is not None and not isinstance(self.signals, ArraySignals) and self.nbar % 5 == 0 and self.debug_events:         # live: nhịp tim tín hiệu mỗi 5 nến (chẩn đoán)
            self.coord.emit("sig_beat", {"symbol": self.symbol, "strategy": self.sid, "ts": ts, "has_sig": has_sig, "match": bool(sig_val and sig_val["match"]),
                                         "stop": bool(sig_val and sig_val["stop"]), "frames": {k: len(v) for k, v in sig_frames.items()}, "err": sig_err})
        coord_halted = getattr(self.coord, "halted_at", None) is not None if self.coord is not None else False
        if self.st == FLAT:
            if not has_sig or not sig_val["match"]:
                return
            if self.close_at_end and open_ms == self.last_open_ms:
                return
            sp = self.spec
            if self.coord is not None and self.debug_events and not isinstance(self.signals, ArraySignals):    # live + debug_events: ghi mọi tín hiệu vào lệnh + quyết định (chẩn đoán vì sao không có lệnh)
                self.coord.emit("signal", {"symbol": self.symbol, "strategy": self.sid, "open_ms": open_ms, "trade_start": self.trade_start, "halted": coord_halted or self.halted,
                                           "last_close_fill_ts": self.last_close_fill_ts, "price": c})
            if (open_ms >= self.trade_start and not coord_halted and not self.halted
                    and self.last_close_fill_ts < open_ms
                    and (not sp.cooldown_ms or self.last_close_time is None or open_ms - self.last_close_time >= sp.cooldown_ms)):
                self._enter(c, sig_val["vol"])
        elif self.st == OPEN:
            if h > self.max_price:
                self.max_price = h
            if l < self.min_price:
                self.min_price = l
            u = self.unrealized(l if self.is_long else h) - self.fee_open
            if u < self.mae_usd:
                self.mae_usd = u
            self.peak = max(self.peak, h) if self.is_long else min(self.peak, l)
            if has_sig:
                self.dca_ok = bool(sig_val["dca"])
            sp = self.spec
            if self.halted:
                self._exit("KILL")
            elif has_sig and sig_val["stop"]:
                self._exit("EXIT")
            elif sp.timeout_ms and ts - self.entry_time >= sp.timeout_ms:
                self._exit("TIMEOUT")
            elif self.close_at_end and open_ms == self.last_open_ms:
                self._exit("END")
            else:
                if self.protect_retry:
                    self.protect_retry = False
                    self._protect()
                self._reconcile_dca()


    def _coin(self, qty_units: float) -> float:
        """Số lượng sàn (hợp đồng) -> COIN. mult = 1 (backtest): làm tròn theo size_precision như trước (bit-identical)."""
        return round(qty_units, self.inst.size_precision) if self.mult == 1.0 else round(qty_units * self.mult, 12)

    # ─── vào lệnh (= PositionManager._open) ─────────────────────────────────
    def _round_qty(self, q: float) -> Optional[Quantity]:
        try:
            qty = self.inst.make_qty(q / self.mult, round_down=True)       # q tính bằng COIN; số lượng lệnh của sàn tính bằng HỢP ĐỒNG (mult = ctVal; backtest mult = 1)
        except ValueError:
            return None
        return qty if float(qty) >= float(self.inst.min_quantity) and float(qty) > 0.0 else None

    def _enter(self, price: float, vol: float, catchup: bool = False) -> None:
        co, sp = self.coord, self.spec
        adm = co.admit(self)
        if adm is None:
            return
        eq = co.equity()
        if eq <= 0:
            return
        unit = 1.0
        if sp.exit_unit == "atr":
            unit = vol
            if not (unit > 0):
                self.skipped_no_vol += 1
                return
        self._apply_unit(unit)
        unit_pct = unit if sp.exit_unit == "atr" else 0.0
        max_cap = eq * sp.capital_usage
        budget = min(max_cap, eq - co.reserved)
        lev = float(sp.max_leverage)
        sign = self.sign
        # mức SL tuyệt đối (sl_anchor entry / last_layer) — như kernel._open
        sl_abs = 0.0
        if sp.sl_anchor_mode == 1:
            if self.dca_steps:
                p_last = price
                for s in self.dca_steps:
                    p_last = p_last * (1.0 - sign * s / 100.0)
                sl_abs = p_last * (1.0 - sign * self.sl_pct / 100.0) if self.sl_pct > 0.0 else p_last
            else:
                sl_abs = price * (1.0 - sign * self.sl_pct / 100.0) if self.sl_pct > 0.0 else 0.0
        sl_eff = abs(price - sl_abs) / price * 100.0 if (sp.sl_anchor_mode == 1 and sl_abs > 0.0) else self.sl_pct
        total_mult = policy.layer_mult_total(sp.dca_mults, len(self.dca_steps))
        planned = 0.0
        if sp.sizing == "risk":
            margin, lev, planned = policy.risk_margin(eq, sp.risk_pct, sp.max_notional_pct, sl_eff, sp.fee_rate, sp.slippage_rate, None,
                                                      sp.market == "perp", sp.max_leverage, sp.mmr, lev, total_mult)
        else:
            margin = policy.flat_margin(eq, sp.order_size_pct)
        if adm.risk_scale != 1.0:
            margin *= adm.risk_scale
            planned *= adm.risk_scale
        margin = policy.clamp_margin(margin, budget, lev, sp.fee_rate, adm.max_new_notional)
        if sp.sizing == "risk" and margin > 0:
            planned = min(planned, policy.planned_risk_cap(margin, lev, sl_eff, policy.round_trip_cost(sp.fee_rate, sp.slippage_rate, None, margin * lev * total_mult), total_mult))
        margin, planned = policy.apply_risk_ceiling(margin, planned, adm.max_new_risk)
        if margin <= 0:
            co.rejected_for_capital += 1
            return
        notional = margin * lev
        fee_est = notional * sp.fee_rate
        if margin + fee_est > max_cap + 1e-9:          # vượt ngân sách vị thế (không đếm, như _gate "budget")
            return
        if margin + fee_est > (eq - co.reserved) + 1e-9:
            co.rejected_for_capital += 1
            return
        qty = self._round_qty(notional / price)
        if qty is None:                                # dưới khối lượng tối thiểu / lot của sàn
            co.rejected_for_capital += 1
            return
        self.pos_lev, self.planned_risk, self.unit_pct, self.next_margin = lev, planned, unit_pct, margin
        self.entry_equity, self.sl_lvl_abs, self.pending_qty = eq, sl_abs, float(qty) * self.mult
        self.st = ENTERING
        co.activate(self)
        order = self.order_factory.market(self.inst.id, self.side_in, qty, tags=["ENTRY", "CATCHUP"] if catchup else ["ENTRY"])
        self._layer_of[order.client_order_id] = 0
        if not isinstance(self.signals, ArraySignals) and not self.debug_events:       # live: ghi gọn quyết định vào lệnh (khi debug_events bật, `signal` đã ghi mọi tín hiệu)
            co.emit("signal", {"symbol": self.symbol, "strategy": self.sid, "price": price, "qty": float(qty), "catchup": catchup})
        self.submit_order(order)

    # ─── thoát lệnh ─────────────────────────────────────────────────────────
    def _exit(self, kind: str) -> None:
        pos = self._position()
        if pos is None:
            return
        self._cancel_orders()
        self.exit_kind = kind
        self.st = EXITING
        self.close_position(pos, tags=[kind])

    def _cancel_orders(self) -> None:
        """Huỷ lệnh chờ. Backtest: cancel_all_orders như cũ (bit-identical). Live (own_orders_only): CHỈ lệnh của chính chiến lược này (cancel_orders từng lệnh) —
        cancel_all_orders của adapter OKX huỷ mọi lệnh trong cache của instrument, kể cả lệnh bot khác trên cùng tài khoản."""
        if not self.own_orders_only:
            self.cancel_all_orders(self.inst.id)
            return
        orders = [o for o in self.cache.orders_open(instrument_id=self.inst.id, strategy_id=self.id) if not o.is_closed]
        orders += [o for o in self.cache.orders_inflight(instrument_id=self.inst.id, strategy_id=self.id) if o not in orders]
        for o in orders:                       # từng lệnh một: cancel_orders(list) gửi BatchCancelOrders mà SandboxExecutionClient (Paper) chưa cài -> lệnh SL/TP kẹt PENDING_CANCEL
            self.cancel_order(o)

    def stop_close(self, close: bool) -> None:
        """Người dùng dừng bot (CHỈ đường này mới đóng): close=True -> huỷ lệnh chờ của chiến lược rồi đóng đúng vị thế của nó (close_position = lệnh reduce-only đúng cỡ vị thế
        chiến lược trong NETTING; không đụng vị thế bot khác). close=False: giữ nguyên lệnh + vị thế."""
        if not close:
            return
        self.halted = True
        self._cancel_orders()
        pos = self._position()
        if pos is not None:
            self.exit_kind = "STOP"
            self.st = EXITING
            self.close_position(pos, tags=["STOP"])

    def adopt_position(self, ts_ms: int) -> bool:
        """Resume sau khi tiến trình chết: Nautilus đã đối soát (reconciliation) vị thế/lệnh của sàn vào cache TRƯỚC khi chiến lược chạy. Nếu chiến lược có vị thế mở trong cache:
        dựng lại trạng thái slot (OPEN, qty, avg) rồi huỷ lệnh bảo vệ cũ của CHÍNH nó và đặt lại SL/TP/TRAIL/DCA từ vị thế đó. True nếu nhận vị thế."""
        pos = self._position()
        if pos is None:
            return False
        avg, qty = float(pos.avg_px_open), float(pos.quantity) * self.mult
        self._cancel_orders()
        self.st, self.qty, self.avg, self.layers = OPEN, qty, avg, max(self.layers, 1)
        self.last_fill = avg
        self.entry_time = int(ts_ms)
        self.entry_notional, self.entry_margin = qty * avg, qty * avg / self.pos_lev
        self.margin_used, self.entry_equity = self.entry_margin, self.coord.equity()
        self.max_price = self.min_price = self.peak = avg
        self.pending_qty = qty
        self.t_fills = [("ENTRY", int(ts_ms), avg, qty, 0.0, "taker", 0)]
        self.coord.activate(self)
        self.coord.emit("adopted", {"symbol": self.symbol, "strategy": self.sid, "qty": qty, "avg_px": avg})
        self._protect()
        return True

    def kill(self) -> None:
        """Kill switch danh mục: dừng giao dịch mới, đóng vị thế (KILL)."""
        self.halted = True
        if self.st == OPEN:
            self._exit("KILL")

    def _position(self):
        ps = self.cache.positions_open(instrument_id=self.inst.id, strategy_id=self.id)
        return ps[0] if ps else None

    # ─── lệnh bảo vệ / DCA ──────────────────────────────────────────────────
    def _upsert(self, kind: str, make, **mod) -> None:
        """Có lệnh `kind` đang mở -> modify_order (qty + giá); không thì gửi lệnh mới. make() dựng lệnh mới."""
        o = self.o[kind]
        if o is not None and o.is_open:
            if o.quantity != mod["quantity"] or any(getattr(o, k) != v for k, v in mod.items() if k != "quantity"):
                self.modify_order(o, **mod)
            return
        if o is not None and not o.is_closed:         # đang chờ xác nhận: huỷ rồi gửi lại
            self.cancel_order(o)
        o = make()
        self.o[kind] = o
        self.submit_order(o)

    def _protect(self) -> None:
        """Đặt / chỉnh SL, TP, TRAIL, DCA từ vị thế Nautilus hiện tại (gọi sau fill của lớp vào lệnh)."""
        pos = self._position()
        if pos is None:
            return
        inst, sign = self.inst, self.sign
        qty = pos.quantity
        avg = float(pos.avg_px_open)
        self.qty, self.avg = float(qty) * self.mult, avg
        if self.sl_pct or self.sl_lvl_abs:
            lvl = self.sl_lvl_abs if self.spec.sl_anchor_mode == 1 else policy.sl_level(avg, self.sl_pct, sign)
            if lvl > 0:
                px = inst.make_price(lvl)
                self._upsert("SL", lambda: self.order_factory.stop_market(inst.id, self.side_out, qty, px, trigger_type=TriggerType.LAST_PRICE,
                                                                          reduce_only=self.reduce_only, tags=["SL"]), quantity=qty, trigger_price=px)
        if self.tp_pct:
            px = inst.make_price(policy.tp_level(avg, self.tp_pct, sign))
            self._upsert("TP", lambda: self.order_factory.limit(inst.id, self.side_out, qty, px, reduce_only=self.reduce_only, tags=["TP"]), quantity=qty, price=px)
        if self.trail_pct:
            o = self.o["TRAIL"]
            if o is not None and not o.is_closed:
                self.cancel_order(o)
            active = policy.trail_active(self.peak, avg, self.trail_act, sign)
            kw: Dict[str, Any] = {}
            if self.trail_act > 0 and not active:
                kw["activation_price"] = inst.make_price(policy.tp_level(avg, self.trail_act, sign))
            elif self.layers > 1:                      # đặt lại sau DCA khi đã kích hoạt: bám từ đỉnh đã có
                lvl = policy.trail_level(self.peak, self.trail_pct, sign)
                last = self.coord.last[self.sym_idx][0]
                if last == last and (last <= lvl if self.is_long else last >= lvl):   # mức bám đã bị xuyên: Nautilus từ chối stop "trong thị trường" -> thoát ngay (TRAIL)
                    self._exit("TRAIL")
                    return
                kw["trigger_price"] = inst.make_price(lvl)
            o = self.order_factory.trailing_stop_market(inst.id, self.side_out, qty, trailing_offset=Decimal(str(round(self.trail_pct * 100.0, 6))),
                                                        trailing_offset_type=TrailingOffsetType.BASIS_POINTS, trigger_type=TriggerType.LAST_PRICE,
                                                        reduce_only=self.reduce_only, tags=["TRAIL"], **kw)
            self.o["TRAIL"] = o
            self.submit_order(o)
        self._reconcile_dca()

    def _reconcile_dca(self) -> None:
        """Tầng DCA kế tiếp: có khi còn tầng, dca_ok và vốn cho phép; huỷ khi cổng DCA đóng."""
        o = self.o["DCA"]
        want = self.st == OPEN and self.layers - 1 < len(self.dca_steps) and self.dca_ok
        live = o is not None and not o.is_closed
        if live and not want:
            self.cancel_order(o)
            self.o["DCA"] = None
        elif want and not live:
            self._place_dca()

    def _place_dca(self) -> None:
        sp, co = self.spec, self.coord
        k = self.layers - 1
        level = policy.dca_level(self.last_fill, self.dca_steps[k], self.sign)
        margin = self.next_margin * sp.dca_mults[k]
        notional = margin * self.pos_lev
        fee = notional * sp.maker_fee_rate
        eq = co.equity()
        if margin <= 0 or level <= 0 or self.margin_used + margin + self.fee_open + fee > eq * sp.capital_usage + 1e-9:
            self.dca_rejected += 1
            self.dca_steps = self.dca_steps[:k]
            return
        if margin + fee > (eq - co.reserved) + 1e-9:
            co.rejected_for_capital += 1
            self.dca_rejected += 1
            self.dca_steps = self.dca_steps[:k]
            return
        qty = self._round_qty(notional / level)
        if qty is None:
            self.dca_rejected += 1
            self.dca_steps = self.dca_steps[:k]
            return
        self._dca_margin = margin
        o = self.order_factory.limit(self.inst.id, self.side_in, qty, self.inst.make_price(level), tags=["DCA"])
        self._layer_of[o.client_order_id] = self.layers
        self.o["DCA"] = o
        self.submit_order(o)

    # ─── sự kiện Nautilus ───────────────────────────────────────────────────
    def _kind_of(self, client_order_id) -> str:
        return self.cache.order(client_order_id).tags[0]

    def on_order_filled(self, event) -> None:
        order = self.cache.order(event.client_order_id)
        kind = order.tags[0]
        px, qty = round(event.last_px.as_double(), self.inst.price_precision), self._coin(event.last_qty.as_double())
        fee = event.commission.as_double()
        ts = event.ts_event // _NS_MS
        liq = "maker" if event.liquidity_side == LiquiditySide.MAKER else "taker"
        cid = event.client_order_id
        self.coord.emit("fill", {"symbol": self.symbol, "strategy": self.sid, "kind": kind, "side": "BUY" if event.order_side == OrderSide.BUY else "SELL",
                                 "px": px, "qty": qty, "fee": fee, "liquidity": liq, "ts": ts, "client_order_id": str(event.client_order_id),
                                 "venue_order_id": str(event.venue_order_id), "catchup": "CATCHUP" in order.tags})
        if kind in _ENTRY_KINDS:
            if self.st == FLAT:                      # lệnh vào mồ côi (DCA khớp sau khi vị thế đã đóng): coi như vị thế mới
                self.coord.activate(self)
                self.st = ENTERING
                self.pending_qty = qty
            layer = self._layer_of.get(cid, self.layers)
            margin = px * qty / self.pos_lev
            self.fee_open += fee
            self.coord.open_fees += fee
            self.margin_used += margin
            self.res_here += margin + fee
            self.coord.reserved += margin + fee
            first = not self.t_fills
            self.t_fills.append((kind, ts, px, qty, fee, liq, layer))
            if first:
                self.entry_time, self.entry_margin, self.entry_notional, self.entry_fee = ts, margin, px * qty, fee
                self.max_price = self.min_price = self.peak = px
            if layer >= self.layers:
                self.layers = layer + 1
            self.last_fill = px
            if kind == "DCA":
                self.o["DCA"] = None
                self.next_margin = self._dca_margin or self.next_margin
            if order.is_closed:
                if self.st == EXITING:                 # DCA khớp sau khi đã quyết định thoát: đóng luôn phần mới
                    self._exit(self.exit_kind or "EXIT")
                else:
                    self.st = OPEN
                    self._protect()
        else:
            self.fee_open += fee
            self.coord.open_fees += fee
            self.t_fills.append((kind, ts, px, qty, fee, liq, self.layers))
            if kind in self.o:
                self.o[kind] = None
            pos = self._position()
            if pos is not None:                         # đóng một phần (lệnh bảo vệ chưa kịp sửa qty trong cùng nến): đóng nốt phần còn lại cùng lý do
                self.qty = float(pos.quantity) * self.mult
                if kind in ("SL", "TP", "TRAIL") and order.is_closed:     # lệnh còn mở = đang khớp từng phần theo volume nến (bar_execution): chờ, không gửi lệnh đóng mới (đệ quy)
                    self._exit(kind)

    def on_position_closed(self, event) -> None:
        ts = event.ts_closed // _NS_MS
        entry_fills = [f for f in self.t_fills if f[0] in _ENTRY_KINDS]
        exit_fills = [f for f in self.t_fills if f[0] not in _ENTRY_KINDS]
        kind = exit_fills[-1][0] if exit_fills else (self.exit_kind or "EXIT")
        close_px = round(float(event.avg_px_close), 10)
        avg = round(float(event.avg_px_open), 10)
        net = event.realized_pnl.as_double()
        exit_fee = sum(f[4] for f in exit_fills)
        status = (PositionStatus.TP if kind == "TP" else PositionStatus.SL if kind == "SL" else PositionStatus.CANCEL if kind in ("END", "KILL")
                  else PositionStatus.TP if policy.in_profit(close_px, avg, self.is_long) else PositionStatus.SL)
        ee = self.entry_equity
        rid = next_id()
        sp = self.spec
        first_ts = entry_fills[0][1] if entry_fills else self.entry_time
        model = PositionModel(
            result_id=rid, account_id=sp.account_id, campaign_id=sp.campaign_id, symbol=self.symbol, pos_type=sp.pos_type, phase=0,
            enter_time=first_ts, enter_price=entry_fills[0][2] if entry_fills else avg, close_time=ts, close_price=close_px, status=status,
            real_pnl=net, profit_pct=net / ee * 100.0 if ee > 0 else 0.0, flow=sp.flow_name, start_reason=REASONS[entry_fills[0][0]] if entry_fills else "",
            close_reason=REASONS.get(kind, kind), max_price=self.max_price, min_price=self.min_price, qty=float(event.peak_qty) * self.mult, entry_equity=ee,
            entry_margin_usd=self.entry_margin, entry_notional_usd=self.entry_notional, entry_fee_usd=self.entry_fee, exit_fee_usd=exit_fee,
            layers=self.layers, avg_price=avg, total_margin_usd=self.margin_used, mae_pct=min(0.0, self.mae_usd / ee * 100.0) if ee > 0 else 0.0,
            fees_usd=sum(f[4] for f in self.t_fills), funding_usd=0.0, unit_pct=self.unit_pct, leverage_used=self.pos_lev, risk_usd=self.planned_risk,
            strategy_id=self.sid)
        orders = [OrderModel(order_id=next_id(), account_id=sp.account_id, position_id=rid, order_time=f[1],
                             order_type=OrderType.BUY if (f[0] in _ENTRY_KINDS) == self.is_long else OrderType.SELL, order_price=f[2], qty=f[3],
                             phase=f[6], fee_usd=f[4], liquidity=f[5], slippage=0.0) for f in self.t_fills]
        resting = kind in ("SL", "TP", "TRAIL")
        self.last_close_time = ts - self.fr if resting else ts    # trục open_time như engine cũ
        self.last_close_fill_ts = self.last_close_time
        self.last_model, self.last_model_ts = model, ts
        self._cancel_orders()
        self.coord.emit("position_closed", {"symbol": self.symbol, "strategy": self.sid, "kind": kind, "avg_px": avg, "close_px": close_px, "qty": float(event.peak_qty) * self.mult,
                                            "pnl": net, "ts": ts})
        self.coord.on_closed(self, ts - self.fr, model, orders)
        self._reset()

    def on_order_rejected(self, event) -> None:
        self._order_failed(event)

    def on_order_denied(self, event) -> None:
        self._order_failed(event)

    def _order_failed(self, event) -> None:
        order = self.cache.order(event.client_order_id)
        kind = order.tags[0] if order is not None and order.tags else ""
        reason = str(getattr(event, "reason", ""))
        if kind == "TRAIL" and "in the market" in reason:       # mức bám đã bị xuyên khi đặt lại -> như engine cũ: khớp ngay (thoát TRAIL)
            self.o["TRAIL"] = None
            if self.st == OPEN:
                self._exit("TRAIL")
            return
        if kind in ("SL", "TP", "TRAIL") and "would have increased position" in reason:   # vị thế đã đóng trong cùng nến trước khi lệnh bảo vệ tới sàn: vô hại
            self.o[kind] = None
            return
        if kind in ("SL", "TP", "TRAIL") and "Reduce Only is not available" in reason and self.st == OPEN:
            self.o[kind] = None
            self.protect_retry = True
            return
        self.coord.venue_rejects.append((self.symbol, self.sid, kind, reason))
        self.coord.emit("reject", {"symbol": self.symbol, "strategy": self.sid, "kind": kind, "reason": reason})
        if kind == "ENTRY" and self.st == ENTERING and not self.t_fills:
            self.coord.deactivate(self)
            self._reset()
        elif kind in self.o:
            self.o[kind] = None

    def on_order_canceled(self, event) -> None:
        for k, o in self.o.items():
            if o is not None and o.client_order_id == event.client_order_id:
                self.o[k] = None
