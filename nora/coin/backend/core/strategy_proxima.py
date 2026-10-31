"""Mô-đun Chiến Lược Nghiên Cứu Proxima Native Strategy (backend/core/strategy_proxima.py).

Đặc tả chuẩn mực theo Lộ trình Nghiên cứu Định lượng (Giai đoạn 1 - Research Skeleton):
- Phân định rõ ràng 3 phân hệ:
  1. runtime_safety_policy: Ràng buộc an toàn bất khả xâm phạm của Nora (Sleeve 15$ risk, Reserve 5000$).
  2. fixture_verified: Cơ chế tính toán đã chứng minh qua unit tests / fixtures (Sizing contract-aware, Idempotent ID).
  3. experimental_logic: Toàn bộ các công thức và tham số CHƯA có source/log gốc đối soát (gắn unverified = True).
- Tuyệt đối tuân thủ đường thực thi dùng chung (Shared Execution Path) qua Master Portfolio Admission Controller.
- Không tự tạo Execution Engine riêng, không tự mô phỏng fill giả lập ngoài hệ thống.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple

from nautilus_trader.model.data import Bar, QuoteTick, TradeTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from backend.adapter.execution import (
    InstrumentSpec,
    ExitReason,
    generate_client_order_id,
)
from backend.core.portfolio import (
    MasterPortfolioLedger,
    PortfolioAdmissionController,
    get_portfolio_admission_controller,
)


# ══════════════════════════════════════════════════════════════════════════
# 1. RUNTIME SAFETY POLICY (Chốt chặn an toàn bất khả xâm phạm của Nora)
# ══════════════════════════════════════════════════════════════════════════

RUNTIME_SAFETY_POLICY: Dict[str, Any] = {
    "nora_sleeve_risk_limit": 15.0,         # 1.5% của Sleeve 1,000 USDT (Policy an toàn của Nora)
    "master_reserve_floor": 5000.0,         # Quỹ dự trữ bất khả xâm phạm
    "max_daily_sleeve_loss": 30.0,         # Khóa sleeve nếu lỗ trong ngày chạm 30 USDT (3%)
    "max_sleeve_drawdown_pct": 15.0,        # Khóa sleeve nếu drawdown chạm 150 USDT (15%)
    "shared_execution_required": True,      # Bắt buộc đi qua Nora Shared OMS & Master Admission
}


# ══════════════════════════════════════════════════════════════════════════
# 2. EXPERIMENTAL LOGIC METADATA (Toàn bộ các mục CHƯA xác minh từ log gốc)
# ══════════════════════════════════════════════════════════════════════════

EXPERIMENTAL_LOGIC_SCHEMA: Dict[str, Any] = {
    "anchor_frame": {
        "default": "1h",
        "choices": ["15m", "30m", "1h"],
        "source_verified": False,
        "note": "Khung neo thực tế cần kiểm chứng qua Walk-Forward Analysis (WFA) và trade log gốc",
    },
    "signal_formula_variants": {
        "variant_a": {
            "name": "Standard Keltner Distance",
            "formula_long": "z = (high - ema) / atr > F",
            "formula_short": "w = (ema - low) / atr > F",
            "verified": False,
        },
        "variant_b": {
            "name": "Normalized Band Breakout",
            "formula_long": "z = (high - upper) / (2 * F * atr) > F",
            "formula_short": "w = (lower - low) / (2 * F * atr) > F",
            "verified": False,
        },
    },
    "tp_formula_variants": {
        "variant_a_atr_distance": {
            "name": "ATR Band Target",
            "formula": "delta_tp = 0.05 * atr_anchor * tp_mult",
            "verified": False,
        },
        "variant_b_pnl_equity": {
            "name": "Cycle Equity ROI Target",
            "formula": "(cycle_realized + cycle_unrealized) / E >= target_pct",
            "verified": False,
        },
    },
    "r_ratio": {
        "value": 0.15,
        "proxima_original_risk": "unverified",
        "note": "R10/R15/R25 là tham số quét thực nghiệm, chưa chứng minh là risk ratio hay reserve ratio",
    },
    "exit_order_precedence": {
        "order": "provisional",
        "precedence": [
            ExitReason.CYCLE_SL,
            ExitReason.SESSION_CUTOFF,
            ExitReason.OPPOSITE_BAND,
            ExitReason.CENTER_EXIT,
            ExitReason.PARTIAL_TP,
        ],
        "verified": False,
        "conflict_resolution": "Bảo vệ vốn (CYCLE_SL / CUTOFF) luôn được ưu tiên tuyệt đối trước chốt lời (TP)",
    },
    "execution_feed": {
        "sub_minute_ticks_required": True,
        "expected_fill_model": "next_observed_quote + half_spread + slippage + latency",
        "ready": False,
    },
}


# ══════════════════════════════════════════════════════════════════════════
# 3. FIXTURE-VERIFIED FUNCTIONS (Hàm toán học đã pass qua Unit Test Fixtures)
# ══════════════════════════════════════════════════════════════════════════

def floor_to_step(value: float, step: float) -> float:
    """Làm tròn xuống theo bước nhảy lotSz hoặc tickSz với dung sai chống lỗi số thực."""
    if step <= 0 or value <= 0:
        return 0.0
    safe_val = round(value + 1e-9, 8)
    d_val = Decimal(str(safe_val))
    d_step = Decimal(str(step))
    floored = (d_val // d_step) * d_step
    return float(floored)


def calculate_contract_aware_sizing(
    spec: InstrumentSpec,
    price: float,
    sleeve_capital: float,
    adverse_price_pct: float = 0.008,      # 0.8% Stop loss move
    vl_mult: float = 0.75,
    nora_max_risk_usd: float = 15.0,        # Nora policy cap: 15$
    max_notional_cap_usd: float = 2500.0,   # Sleeve notional cap
    estimated_fee_rate: float = 0.0005,    # 0.05% OKX Taker fee
    estimated_slippage_rate: float = 0.0002,# 0.02% Slippage
    fx_rate_to_ac: float = 1.0,
) -> Tuple[float, float, float]:
    """Tính toán khối lượng hợp đồng theo rủi ro hợp đồng thực tế (Contract-Aware Risk Sizing).
    
    Returns:
        (contracts, notional_usd, estimated_worst_case_loss_usd)
    """
    if price <= 0 or spec.contract_value <= 0 or adverse_price_pct <= 0:
        return 0.0, 0.0, 0.0

    cv = spec.contract_value
    # Khoảng giá lỗ bất lợi tới SL
    adverse_distance = price * adverse_price_pct
    # Chi phí giao dịch khứ hồi dự kiến (2 lượt taker + 2 lượt trượt giá)
    round_trip_cost_rate = (estimated_fee_rate * 2.0) + (estimated_slippage_rate * 2.0)
    cost_per_coin = price * round_trip_cost_rate

    # Rủi ro thực tế trên mỗi hợp đồng khi chạm SL
    risk_per_contract = (adverse_distance + cost_per_coin) * cv * fx_rate_to_ac
    if risk_per_contract <= 0:
        return 0.0, 0.0, 0.0

    # Cận 1: Giới hạn theo ngân sách rủi ro an toàn của Nora (15$)
    c1_contracts = nora_max_risk_usd / risk_per_contract

    # Cận 2: Giới hạn theo trần Notional danh nghĩa của Sleeve
    max_contracts_by_notional = max_notional_cap_usd / (price * cv * fx_rate_to_ac)

    # Áp dụng hệ số nhân Volume Multiplier (VL)
    base_contracts = min(c1_contracts, max_contracts_by_notional)
    scaled_contracts = base_contracts * vl_mult

    # Làm tròn xuống theo lotSz của sàn
    contracts = floor_to_step(scaled_contracts, spec.lotSz)

    if contracts < spec.minSz:
        return 0.0, 0.0, 0.0

    notional_usd = contracts * cv * price * fx_rate_to_ac
    worst_case_loss = contracts * risk_per_contract

    return contracts, notional_usd, worst_case_loss


def evaluate_signal_variant_a(
    running_high: float,
    running_low: float,
    ema: float,
    atr: float,
    f_mult: float,
) -> Tuple[bool, bool, float, float]:
    """Tín hiệu Biến thể A: z = (high - ema) / atr > F; w = (ema - low) / atr > F."""
    if atr <= 1e-8:
        return False, False, 0.0, 0.0
    z = (running_high - ema) / atr
    w = (ema - running_low) / atr
    long_sig = (z > f_mult) and (z >= w)
    short_sig = (w > f_mult) and (w > z)
    return long_sig, short_sig, z, w


def evaluate_signal_variant_b(
    running_high: float,
    running_low: float,
    ema: float,
    atr: float,
    f_mult: float,
) -> Tuple[bool, bool, float, float]:
    """Tín hiệu Biến thể B: z = (high - upper) / K_delta > F (với Upper = EMA + F*ATR, K_delta = 2*F*ATR)."""
    k_delta = 2.0 * f_mult * atr
    if k_delta <= 1e-8:
        return False, False, 0.0, 0.0
    upper = ema + (f_mult * atr)
    lower = ema - (f_mult * atr)
    z = (running_high - upper) / k_delta
    w = (lower - running_low) / k_delta
    long_sig = (z > f_mult) and (z >= w)
    short_sig = (w > f_mult) and (w > z)
    return long_sig, short_sig, z, w


def resolve_exit_state_machine(
    is_long: bool,
    price: float,
    ema: float,
    atr: float,
    f_mult: float,
    cycle_realized_usd: float,
    cycle_unrealized_usd: float,
    sleeve_risk_budget_usd: float,
    is_session_cutoff: bool,
    tp_formula_variant: str = "atr_distance",
    tp_mult: float = 0.8,
    already_partial_tp: bool = False,
    entry_price: float = 0.0,
) -> ExitReason:
    """Xử lý máy trạng thái thoát lệnh với thứ tự ưu tiên và giải quyết xung đột (Conflict Resolution)."""
    cycle_net_pnl = cycle_realized_usd + cycle_unrealized_usd

    # Ưu tiên 1: Cycle Emergency SL (Bảo vệ khẩn cấp tuyệt đối khi lỗ chu kỳ chạm -0.8% E)
    if sleeve_risk_budget_usd > 0:
        if (cycle_net_pnl / sleeve_risk_budget_usd) <= -0.8:
            return ExitReason.CYCLE_SL

    # Ưu tiên 2: Cắt phiên giao dịch (Session Cutoff)
    if is_session_cutoff:
        return ExitReason.SESSION_CUTOFF

    # Ưu tiên 3: Chạm dải đối diện (Opposite Band Breakout)
    if atr > 1e-8 and f_mult > 0:
        upper = ema + (f_mult * atr)
        lower = ema - (f_mult * atr)
        if is_long and price < lower:
            return ExitReason.OPPOSITE_BAND
        elif (not is_long) and price > upper:
            return ExitReason.OPPOSITE_BAND

    # Ưu tiên 4: Dải giữa (Center Exit - quay về cắt qua EMA)
    if is_long and price < ema:
        return ExitReason.CENTER_EXIT
    elif (not is_long) and price > ema:
        return ExitReason.CENTER_EXIT

    # Ưu tiên 5: Chốt lời từng phần (Partial TP)
    if not already_partial_tp and entry_price > 0:
        if tp_formula_variant == "atr_distance":
            delta_tp = 0.05 * atr * tp_mult
            if is_long and (price >= entry_price + delta_tp):
                return ExitReason.PARTIAL_TP
            elif (not is_long) and (price <= entry_price - delta_tp):
                return ExitReason.PARTIAL_TP
        elif tp_formula_variant == "pnl_equity":
            target_gain = 0.05 * sleeve_risk_budget_usd * tp_mult
            if cycle_net_pnl >= target_gain:
                return ExitReason.PARTIAL_TP

    return ExitReason.NONE


# ══════════════════════════════════════════════════════════════════════════
# 4. NAUTILUS NATIVE STRATEGY SKELETON
# ══════════════════════════════════════════════════════════════════════════

class ProximaNativeStrategyConfig(StrategyConfig):
    """Cấu hình tham số chiến lược Proxima Native với phân định rõ ràng 3 phân hệ."""
    instrument_id: str
    sleeve_id: str = "sleeve_proxima"
    sleeve_capital: float = 2000.0
    f_mult: float = 1.0
    vl_mult: float = 1.0
    tp_mult: float = 0.8
    r_ratio: float = 0.15
    anchor_frame: str = "1h"
    signal_variant: str = "variant_a"
    tp_variant: str = "atr_distance"
    shadow_mode: bool = False               # False = thực thi qua Nora Sandbox Execution Client thật


class ProximaNativeStrategy(Strategy):
    """Chiến lược Proxima Native đa tài sản chạy trực tiếp trên Nautilus TradingNode của Nora.
    
    Tích hợp 100% với Nora SandboxExecutionClient, bộ não ProximaSignalEngine (Cách A),
    nạp đủ 50 nến 1H warmup, và kiểm duyệt rủi ro qua Master Portfolio Admission Controller.
    """
    is_native: bool = True
    timeframe: str = "1m"

    def __init__(
        self,
        config: StrategyConfig,
        instruments: Optional[Dict[str, Any]] = None,
        bar_types: Optional[List[Any]] = None,
        admission_controller: Optional[PortfolioAdmissionController] = None,
        **kwargs: Any,
    ):
        super().__init__(config)
        self.cfg_extra = kwargs
        self.instruments_map = instruments or {}
        self.bar_types_list = bar_types or []
        self.sleeve_id = kwargs.get("sleeve_id", "sleeve_proxima")
        self.sleeve_capital = float(kwargs.get("sleeve_capital", 2000.0))
        self.r_ratio = float(kwargs.get("r_ratio", 0.15))
        self.vl_mult = float(kwargs.get("vl_mult", 1.0))
        self.tp_mult = float(kwargs.get("tp_mult", 0.8))
        self.f_mult = float(kwargs.get("f_mult", 1.0))
        self.anchor_frame = str(kwargs.get("anchor_frame", "1h"))
        self.shadow_mode = bool(kwargs.get("shadow_mode", False))

        self.admission_controller = admission_controller or get_portfolio_admission_controller()

        # Quản lý phân hệ Signal & Reader theo từng symbol
        from backend.adapter.readings import MarketDataReader
        from backend.analys.signal.signal import ProximaSignalEngine
        from backend.adapter.execution import get_universal_spec

        self.readers: Dict[str, MarketDataReader] = {}
        self.signal_engines: Dict[str, ProximaSignalEngine] = {}
        self.specs: Dict[str, InstrumentSpec] = {}
        self.is_warmed_up: Dict[str, bool] = {}
        self.last_orders: Dict[str, Any] = {}
        self.position_trackers: Dict[str, Dict[str, Any]] = {}

        for sym in self.instruments_map.keys():
            self.specs[sym] = get_universal_spec(sym)
            self.readers[sym] = MarketDataReader(
                symbol=sym,
                anchor_hours=1,
                k_period=20,
                atr_period=14,
                f_multiplier=self.f_mult,
                warmup_required=20,
            )
            self.signal_engines[sym] = ProximaSignalEngine(
                ema_k=20,
                atr_period=14,
                f_multiplier=self.f_mult,
                tp_mult=self.tp_mult,
                warmup_required=20,
            )
            self.is_warmed_up[sym] = False
            self.position_trackers[sym] = {
                "qty": 0.0,
                "entry_price": 0.0,
                "already_partial_tp": False,
                "realized_pnl": 0.0,
                "fees_paid": 0.0,
            }

    def on_start(self) -> None:
        """Khởi động chiến lược: Đăng ký nến và nạp đủ 50 nến 1H lịch sử (Warmup)."""
        self.log.info(f"Khởi động ProximaNativeStrategy trên {len(self.instruments_map)} tài sản: {list(self.instruments_map.keys())}")

        # 1. Đăng ký nhận luồng nến 1m từ sàn
        for bt in self.bar_types_list:
            self.subscribe_bars(bt)

        # 2. Warmup nến Anchor 1h từ API OKX cho từng symbol (KHÔNG PHÁT LỆNH)
        import json
        import urllib.request
        for sym in self.instruments_map.keys():
            inst_id = sym if sym.endswith("-SWAP") else f"{sym}-USDT-SWAP"
            try:
                url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=50"
                req = urllib.request.Request(url, headers={"User-Agent": "NoraPaper/2.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    res = json.loads(r.read())
                    if res.get("code") == "0" and res.get("data"):
                        raw_bars = list(reversed(res["data"]))
                        closed_anchors = [
                            {
                                "timestamp": int(c[0]),
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": float(c[5]),
                            }
                            for c in raw_bars
                        ]
                        reader = self.readers[sym]
                        reader.closed_1h_bars = closed_anchors
                        reader._compute_indicators()
                        self.signal_engines[sym].update_anchor_indicators(closed_anchors)
                        self.is_warmed_up[sym] = reader.is_warmed_up
                        self.log.info(
                            f"[{sym}] Warmup 1H hoàn tất: {len(closed_anchors)} nến (EMA={reader._cached_ema:.2f}, "
                            f"ATR={reader._cached_atr:.2f}, is_warmed_up={reader.is_warmed_up})"
                        )
            except Exception as e:
                self.log.warning(f"[{sym}] Không thể tải nến warmup từ API: {e}")

    def on_bar(self, bar: Bar) -> None:
        """Xử lý nến 1m ĐÃ ĐÓNG HOÀN TOÀN: Đánh giá tín hiệu -> Risk Gate -> Sandbox Order."""
        inst = self.cache.instrument(bar.bar_type.instrument_id)
        if not inst:
            return

        from backend.data.data import normalize_symbol
        sym = normalize_symbol(str(inst.id.symbol))
        if sym not in self.readers:
            return

        reader = self.readers[sym]
        signal_engine = self.signal_engines[sym]
        spec = self.specs[sym]
        pos_tracker = self.position_trackers[sym]

        bar_dict = {
            "timestamp": bar.ts_event // 1_000_000,
            "open": bar.open.as_double(),
            "high": bar.high.as_double(),
            "low": bar.low.as_double(),
            "close": bar.close.as_double(),
            "volume": bar.volume.as_double(),
        }

        # 1. Nạp nến vào Reader
        m_bar = reader.feed_1m_bar(bar_dict)
        if m_bar is not None and m_bar.closed_1h_bars:
            signal_engine.update_anchor_indicators(m_bar.closed_1h_bars)

        # 2. Không phát lệnh nếu chưa hoàn thành Warmup
        if not reader.is_warmed_up:
            return

        # 3. Thu thập ngữ cảnh vị thế và đánh giá tín hiệu
        current_pos = self.cache.position(inst.id)
        current_qty = float(current_pos.quantity) if current_pos and not current_pos.is_closed else 0.0
        pos_tracker["qty"] = current_qty

        pos_context = {
            "qty_contracts": current_qty,
            "entry_price": float(current_pos.avg_px_open) if current_pos and not current_pos.is_closed else 0.0,
            "already_partial_tp": pos_tracker.get("already_partial_tp", False),
        }

        decision = signal_engine.evaluate(bar_dict, position_context=pos_context)

        # 4. Điều phối hành động giao dịch
        price = bar_dict["close"]
        if decision.intent == "ENTRY" and current_qty == 0:
            # Tính toán khối lượng theo quy tắc Sizing 3 cận của Proxima
            per_market_cap = self.sleeve_capital / max(len(self.instruments_map), 1)
            raw_risk_e = per_market_cap * self.r_ratio
            k_delta = decision.k_delta if decision.k_delta > 1e-6 else (price * 0.01)
            
            # Sizing cận 1: c1 = E / k_delta (coin) -> đổi ra contracts
            cv = spec.contract_value
            contracts_raw = (raw_risk_e / (k_delta * cv)) * self.vl_mult
            
            # Floor theo lotSz
            contracts = spec.lotSz * math.floor(contracts_raw / spec.lotSz)
            if contracts < spec.minSz:
                return

            side_order = OrderSide.BUY if decision.side == "BUY" else OrderSide.SELL
            sl_price = price - (1.5 * decision.atr) if decision.side == "BUY" else price + (1.5 * decision.atr)

            # ── MASTER PORTFOLIO ADMISSION GATE (FAIL-CLOSED) ──
            admitted, reason = self.admission_controller.admit_order(
                sleeve_id=self.sleeve_id,
                side=decision.side,
                requested_qty=contracts,
                price=price,
                contract_value=cv,
                margin_rate=spec.broker_margin_init,
                sl_price=sl_price,
                is_reduce_only=False,
            )

            if not admitted:
                self.log.warning(f"[{sym}] Master Risk Gate từ chối Entry: {reason}")
                return

            # Gửi lệnh trực tiếp vào Nora SandboxExecutionClient
            qty_nautilus = inst.make_qty(contracts)
            order = self.order_factory.market(
                instrument_id=inst.id,
                order_side=side_order,
                quantity=qty_nautilus,
                tags=["ENTRY", "PROXIMA"],
            )
            self.last_orders[str(order.client_order_id)] = {
                "symbol": sym,
                "action": "ENTRY",
                "side": decision.side,
                "qty": contracts,
                "price": price,
            }
            self.submit_order(order)
            self.log.info(f"[{sym}] [SANDBOX ORDER SUBMITTED] {decision.side} {contracts} hợp đồng @ ~{price}")

        elif decision.intent in ("EXIT", "OPPOSITE_BAND", "CENTER_EXIT", "SESSION_CUTOFF") and current_qty > 0:
            # Đóng toàn bộ vị thế qua lệnh Reduce-Only
            self.close_position(current_pos, tags=[decision.intent])
            self.log.info(f"[{sym}] [SANDBOX CLOSE POSITION] Lý do: {decision.intent}")

    def on_order_filled(self, event) -> None:
        """Callback khi Sandbox khớp lệnh thật: Cập nhật Position, Fee, PnL vào Master Ledger đúng một lần."""
        inst = self.cache.instrument(event.instrument_id)
        if not inst:
            return

        from backend.data.data import normalize_symbol
        sym = normalize_symbol(str(inst.id.symbol))
        pos_tracker = self.position_trackers.get(sym, {})

        fill_px = event.last_px.as_double()
        fill_qty = event.last_qty.as_double()
        fee = event.commission.as_double()
        ts = event.ts_event // 1_000_000

        # Đồng bộ sự kiện fill vào Master Portfolio Ledger
        try:
            from backend.core.portfolio import get_live_master_ledger
            ledger = get_live_master_ledger("paper")
            sleeve = ledger.sleeves.get(self.sleeve_id)
            if sleeve:
                # Ghi phí một lần duy nhất
                sleeve.fees_paid += fee
                
                # Tính PnL phát sinh của chính phần fill này nếu là lệnh giảm/đóng vị thế
                pos = self.cache.position(event.instrument_id)
                if pos and pos.is_closed:
                    realized_fill_pnl = float(pos.realized_pnl)
                    sleeve.realized_pnl += realized_fill_pnl
                    pos_tracker["realized_pnl"] += realized_fill_pnl
                    self.log.info(f"[{sym}] [FILL COMPLETED] Đóng vị thế. Realized PnL: ${realized_fill_pnl:+.4f}, Fee: ${fee:.4f}")
                else:
                    self.log.info(f"[{sym}] [FILL COMPLETED] Mở/Tăng vị thế. Qty: {fill_qty} @ {fill_px}, Fee: ${fee:.4f}")
        except Exception as e:
            self.log.error(f"Lỗi đồng bộ Master Ledger khi nhận Fill: {e}")

    def on_stop(self) -> None:
        """Dọn dẹp và dừng chiến lược: Hủy lệnh chờ và đóng các vị thế còn mở."""
        self.log.info("Dừng ProximaNativeStrategy: Đang hủy lệnh chờ và đóng vị thế...")
        for inst_id in self.instruments_map.values():
            self.cancel_all_orders(inst_id.id)
            pos = self.cache.position(inst_id.id)
            if pos and not pos.is_closed:
                self.close_position(pos, tags=["STOP_SHUTDOWN"])
