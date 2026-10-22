"""Module Điều Phối Vận Hành Live/Paper của Adapter (backend/adapter/runner.py).

Đảm nhiệm theo chuẩn Kiến trúc 3 Phân Hệ & 2 Worker:
1. readings.py -> Sinh MarketReading & bắn lên Redis (Con 1 - Market Listener).
2. execution.py -> Nhận MarketReading từ Redis, quản lý vị thế, sizing 3 cận an toàn (Con 2 - Execution Worker).
3. runner.py -> Bộ điều phối Live/Paper, Giám sát lỗi thực thi thời gian thực & Persistence:
   - Đo trượt giá Execution Delta (bps): Cảnh báo nếu lệch > 15 bps (|fill_px - expected_price| / expected_price * 10,000 > 15).
   - Giám sát từ chối lệnh (Order Rejection Watcher): Auto-retry với fallback size (50% size hoặc floor theo lotSz).
   - Giám sát độ trễ mạng (Feed Latency): Ngắt lệnh Entry nếu nến trễ > 3.0 giây.
   - Ghi persistence chuẩn Nora: bot.json, events.jsonl, equity.jsonl, positions.json, heartbeat.json.
   - Đồng bộ tức thì lên Nora Web UI & Resizable Drawer.
   - Cung cấp mô hình Hybrid tương thích Nautilus Trader (TradingNode).
"""

from __future__ import annotations

import collections
import json
import logging
import math
import os
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.adapter.readings import MarketDataReader, MarketBar, MarketReading
from backend.analys.signal.signal import ProximaSignalEngine, SignalDecision
from backend.adapter.execution import (
    BotLifecycleState,
    ExitReason,
    InstrumentSpec,
    OrderAction,
    OrderStatus,
    TradeCycleResult,
    UniversalExecutionModel,
    generate_client_order_id,
    get_universal_spec,
    sync_okx_specs,
)
from backend.models.storage import data_home, write_json_atomic

try:
    import redis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

log = logging.getLogger("backend.adapter.runner")


class AdapterRunner:
    """Bộ điều phối vận hành thực thi Live/Paper của Adapter.
    
    Tích hợp:
    - 3 phân hệ: readings -> signal -> execution.
    - Giám sát 3 lớp bảo vệ: Execution Delta (15 bps), Rejection Auto-retry, Feed Latency Guard (3.0s).
    - Persistence chuẩn Nora: bot.json, events.jsonl, equity.jsonl, positions.json.
    """

    def __init__(
        self,
        reader: MarketDataReader,
        execution_model: UniversalExecutionModel,
        signal_engine: Optional[ProximaSignalEngine] = None,
        broker_order_submitter: Optional[Callable[[OrderAction], str]] = None,
        broker_order_canceller: Optional[Callable[[str], bool]] = None,
        bot_dir: Optional[str] = None,
        bot_id: Optional[str] = None,
        mode: str = "paper",
        max_feed_latency_s: float = 3.0,
        max_execution_delta_bps: float = 15.0,
        max_rejection_retries: int = 2,
        check_latency: bool = False,
        shadow_mode: bool = False,
    ):
        self.reader = reader
        self.exec_model = execution_model
        self.signal_engine = signal_engine or ProximaSignalEngine()
        self.broker_order_submitter = broker_order_submitter
        self.broker_order_canceller = broker_order_canceller

        self.bot_dir = bot_dir
        self.bot_id = bot_id or f"proxima_{reader.symbol}_{mode}"
        self.mode = mode
        self.shadow_mode = shadow_mode

        # Tham số giám sát rủi ro thực thi
        self.max_feed_latency_s = max_feed_latency_s
        self.max_execution_delta_bps = max_execution_delta_bps
        self.max_rejection_retries = max_rejection_retries
        self.check_latency = check_latency

        # Quản lý retry lệnh bị từ chối
        self._rejection_counts: Dict[str, int] = {}
        self._last_orders: Dict[str, OrderAction] = {}

        # Nhật ký giám sát vận hành thực tế
        self.execution_audit_log: List[Dict[str, Any]] = []

        # Khởi tạo thư mục persistence nếu có
        if self.bot_dir:
            os.makedirs(self.bot_dir, exist_ok=True)
            self._init_persistence_files()

    @property
    def lifecycle_state(self) -> BotLifecycleState:
        return self.exec_model.lifecycle_state

    @property
    def is_running(self) -> bool:
        return self.exec_model.lifecycle_state == BotLifecycleState.RUNNING

    def request_graceful_pause(self) -> None:
        """Kích hoạt tạm dừng có trật tự (PAUSE_ENTRY): Không vào lệnh mới, chỉ thoát lệnh cũ."""
        log.info(f"[{self.reader.symbol}] Kích hoạt Graceful Pause (PAUSE_ENTRY)...")
        self.exec_model.lifecycle_state = BotLifecycleState.PAUSE_ENTRY
        self._record_audit_event("GRACEFUL_PAUSE_REQUESTED", {"symbol": self.reader.symbol})
        self._persist_state()

    def on_market_reading(
        self,
        market_bar: MarketReading,
        fx_rate_to_ac: float = 1.0,
        time_str: Optional[str] = None,
    ) -> Optional[OrderAction]:
        """Xử lý MarketReading đã được chuẩn hóa (từ readings.py hoặc nhận qua Redis Bus):
        signal.py -> execution.py -> broker.
        """
        bar_ts = market_bar.timestamp or 0
        bar = {
            "timestamp": bar_ts,
            "open": market_bar.open,
            "high": market_bar.high,
            "low": market_bar.low,
            "close": market_bar.close,
            "volume": market_bar.volume,
        }

        # ─── BẢO VỆ 1: GIÁM SÁT ĐỘ TRỄ MẠNG (FEED LATENCY GUARD) ───────
        if self.check_latency and bar_ts > 0:
            now_ms = int(time.time() * 1000)
            latency_s = (now_ms - bar_ts) / 1000.0
            if latency_s > self.max_feed_latency_s:
                log.warning(
                    f"[{self.reader.symbol}] [LATENCY GUARD] Độ trễ nến {latency_s:.2f}s vượt ngưỡng {self.max_feed_latency_s}s! "
                    "Ngắt lệnh mới để bảo vệ vốn."
                )
                self._record_audit_event("FEED_LATENCY_EXCEEDED", {
                    "latency_s": latency_s,
                    "max_allowed": self.max_feed_latency_s,
                    "bar_ts": bar_ts,
                    "now_ms": now_ms,
                })
                self._persist_state(bar_ts)
                return None

        # 1. Cập nhật chỉ báo khung lớn (Anchor) nếu có nến đóng mới
        if market_bar.closed_1h_bars:
            self.signal_engine.update_anchor_indicators(market_bar.closed_1h_bars)

        # 2. Thu thập context vị thế hiện tại chuyển sang bộ não tín hiệu (signal.py)
        pos = self.exec_model.pos
        pos_context = {
            "qty_contracts": pos.qty_contracts,
            "entry_price": pos.entry_price,
            "already_partial_tp": pos.already_partial_tp,
        }

        # 3. signal.py tính toán và phát quyết định chiến lược (SignalDecision)
        decision = self.signal_engine.evaluate(bar, position_context=pos_context)

        # 4. execution.py thực thi quyết định, sinh OrderAction chuẩn quy cách
        action = self.exec_model.step(decision, market_bar, fx_rate_to_ac=fx_rate_to_ac, time_str=time_str)

        # 5. Điều phối hành động tới sàn nếu có kết nối broker thật
        if action.action_type in ("ENTRY", "PARTIAL_CLOSE", "CLOSE_ALL"):
            if action.order_id:
                self._last_orders[action.order_id] = action

            self._record_audit_event("ORDER_SUBMITTED", {
                "action_type": action.action_type,
                "side": action.side,
                "qty_contracts": action.qty_contracts,
                "expected_price": action.expected_price,
                "order_id": action.order_id,
                "sl_price": action.sl_price,
                "tp_price": action.tp_price,
                "shadow_mode": self.shadow_mode,
            })

            if self.shadow_mode or (self.mode == "paper" and not self.broker_order_submitter):
                # Chế độ Paper / Shadow Mode: Khớp mô phỏng tức thời theo trượt giá lý thuyết và phí sàn chuẩn
                slip = self.exec_model.spec.slippage_rate
                fill_px = action.expected_price * (1.0 + slip) if action.side == "BUY" else action.expected_price * (1.0 - slip)
                fee = fill_px * action.qty_contracts * self.exec_model.spec.contract_value * self.exec_model.spec.taker_fee_rate
                fill_prefix = "shadow" if self.shadow_mode else "paper"
                self._record_audit_event(f"{fill_prefix.upper()}_FILL", {
                    "order_id": action.order_id,
                    "side": action.side,
                    "fill_px": fill_px,
                    "qty": action.qty_contracts,
                    "fee": fee,
                })
                self.handle_broker_fill(
                    fill_px=fill_px,
                    fill_qty=action.qty_contracts,
                    fee=fee,
                    liquidity="TAKER",
                    timestamp=bar_ts or int(time.time() * 1000),
                    order_id=action.order_id,
                    action_type=action.action_type,
                    fill_id=f"{fill_prefix}_{action.order_id}",
                )
            elif self.broker_order_submitter:
                try:
                    self.broker_order_submitter(action)
                except Exception as e:
                    log.error(f"Lỗi khi gửi lệnh sang broker: {e}")
                    self.handle_broker_reject(action.order_id, str(e))

        elif action.action_type == "CANCEL":
            self._record_audit_event("CANCEL_REQUESTED", {
                "order_id": action.order_id,
                "side": action.side,
            })
            if self.broker_order_canceller and action.order_id:
                try:
                    self.broker_order_canceller(action.order_id)
                except Exception as e:
                    log.error(f"Lỗi khi gửi yêu cầu hủy lệnh: {e}")

        elif action.action_type == "HOLD":
            if getattr(action, "reason", ""):
                self._record_audit_event("ORDER_ADMISSION_DENIED", {
                    "reason": action.reason,
                    "side": getattr(decision, "side", "HOLD"),
                    "price": bar["close"],
                })
            else:
                prev_decision = getattr(self, "_prev_decision_str", None)
                curr_decision_str = f"{getattr(decision, 'direction', 'NONE')}_{getattr(decision, 'intent', 'HOLD')}"
                if curr_decision_str != prev_decision or (bar_ts and bar_ts % 300000 == 0):
                    self._prev_decision_str = curr_decision_str
                    self._record_audit_event("SIGNAL_EVALUATED", {
                        "bar_ts": bar_ts,
                        "close": bar["close"],
                        "direction": str(getattr(decision, "direction", "NONE")),
                        "intent": getattr(decision, "intent", "HOLD"),
                        "reason": getattr(decision, "reason", "NORMAL_HOLD") or "NORMAL_HOLD",
                        "pos_qty": pos.qty_contracts,
                    })

        # Ghi nhận trạng thái persistence định kỳ
        self._persist_state(bar_ts)

        return action

    def on_1m_bar(
        self,
        bar: Dict[str, float],
        fx_rate_to_ac: float = 1.0,
        time_str: Optional[str] = None,
    ) -> Optional[OrderAction]:
        """Xử lý nhịp nến 1m đến từ sàn (chế độ trực tiếp / đơn luồng):
        readings.py -> on_market_reading.
        """
        bar_ts = int(bar.get("timestamp", 0))

        # ─── BẢO VỆ 1: GIÁM SÁT ĐỘ TRỄ MẠNG (FEED LATENCY GUARD) ───────
        if self.check_latency and bar_ts > 0:
            now_ms = int(time.time() * 1000)
            latency_s = (now_ms - bar_ts) / 1000.0
            if latency_s > self.max_feed_latency_s:
                log.warning(
                    f"[{self.reader.symbol}] [LATENCY GUARD] Độ trễ nến {latency_s:.2f}s vượt ngưỡng {self.max_feed_latency_s}s! "
                    "Ngắt lệnh mới để bảo vệ vốn."
                )
                self._record_audit_event("FEED_LATENCY_EXCEEDED", {
                    "latency_s": latency_s,
                    "max_allowed": self.max_feed_latency_s,
                    "bar_ts": bar_ts,
                    "now_ms": now_ms,
                })
                market_bar = self.reader.feed_1m_bar(bar)
                self._persist_state(bar_ts)
                return None

        # 1. Đưa nến vào bộ đọc (readings.py) để chuẩn hóa nến và gom nến anchor
        market_bar = self.reader.feed_1m_bar(bar)
        if market_bar is None:
            return None

        return self.on_market_reading(market_bar, fx_rate_to_ac=fx_rate_to_ac, time_str=time_str)

    def handle_broker_fill(
        self,
        fill_px: float,
        fill_qty: float,
        fee: float = 0.0,
        liquidity: str = "TAKER",
        timestamp: int = 0,
        order_id: Optional[str] = None,
        action_type: Optional[str] = None,
        fill_id: Optional[str] = None,
    ) -> None:
        """Xử lý sự kiện khớp lệnh nhận được từ WebSocket sàn."""
        # ─── BẢO VỆ 2: ĐO TRƯỢT GIÁ EXECUTION DELTA (BPS) ───────────────
        last_order = self._last_orders.get(order_id) if order_id else None
        expected_price = last_order.expected_price if last_order else fill_px

        if expected_price > 0 and fill_px > 0:
            delta_bps = (abs(fill_px - expected_price) / expected_price) * 10_000.0
            if delta_bps > self.max_execution_delta_bps:
                log.warning(
                    f"[{self.reader.symbol}] [SLIPPAGE WARNING] Execution Delta {delta_bps:.2f} bps "
                    f"vượt ngưỡng {self.max_execution_delta_bps} bps! (Fill: {fill_px}, Dự kiến: {expected_price})"
                )
                self._record_audit_event("EXECUTION_DELTA_WARNING", {
                    "order_id": order_id,
                    "fill_px": fill_px,
                    "expected_price": expected_price,
                    "delta_bps": round(delta_bps, 2),
                    "threshold_bps": self.max_execution_delta_bps,
                })

        # Gửi sự kiện fill vào execution model
        self.exec_model.on_fill(
            fill_px=fill_px,
            fill_qty_contracts=fill_qty,
            fee=fee,
            liquidity=liquidity,
            timestamp=timestamp,
            order_id=order_id,
            action_type=action_type,
            fill_id=fill_id,
        )

        # Xóa theo dõi retry khi lệnh đã khớp
        if order_id and order_id in self._rejection_counts:
            del self._rejection_counts[order_id]

        self._record_audit_event("FILL_CONFIRMED", {
            "order_id": order_id,
            "fill_id": fill_id,
            "px": fill_px,
            "qty": fill_qty,
            "fee": fee,
            "liquidity": liquidity,
            "pos_contracts": self.exec_model.pos.qty_contracts,
            "pos_entry_price": self.exec_model.pos.entry_price,
        })

        # Đồng bộ sự kiện khớp lệnh vào Master Portfolio Ledger
        try:
            from backend.core.portfolio import get_live_master_ledger
            ledger = get_live_master_ledger(self.mode)
            s_id = self.bot_id
            if s_id not in ledger.sleeves and f"sleeve_{s_id}" in ledger.sleeves:
                s_id = f"sleeve_{s_id}"
            elif s_id not in ledger.sleeves and s_id.startswith("sleeve_") and s_id[7:] in ledger.sleeves:
                s_id = s_id[7:]

            last_ord = self._last_orders.get(order_id) if order_id else None
            side = last_ord.side if last_ord else ("BUY" if fill_qty > 0 else "SELL")
            act = action_type or (last_ord.action_type if last_ord else "ENTRY")
            cv = self.exec_model.spec.contract_value
            margin_delta = (fill_qty * cv * fill_px * self.exec_model.effective_margin_ratio) if act == "ENTRY" else -(fill_qty * cv * fill_px * self.exec_model.effective_margin_ratio)

            ledger.record_fill(
                fill_id=fill_id or f"fill_{order_id}",
                sleeve_id=s_id,
                symbol=self.reader.symbol,
                side=side,
                qty=fill_qty,
                price=fill_px,
                fee=fee,
                realized_gain=self.exec_model.pos.cycle_realized_pnl if act in ("PARTIAL_CLOSE", "CLOSE_ALL") else 0.0,
                margin_delta=margin_delta,
                timestamp=timestamp or int(time.time() * 1000),
            )
        except Exception as err:
            log.debug(f"Đồng bộ Master Ledger warning: {err}")

        self._persist_state(timestamp or int(time.time() * 1000))

    def handle_broker_reject(self, order_id: Optional[str] = None, reason: str = "") -> None:
        """Xử lý sự kiện sàn từ chối lệnh với cơ chế tự động thử lại (Order Rejection Watcher)."""
        log.warning(f"[{self.reader.symbol}] Lệnh {order_id} bị sàn từ chối: {reason}")
        self.exec_model.on_reject(order_id=order_id, reason=reason)

        self._record_audit_event("ORDER_REJECTED", {"order_id": order_id, "reason": reason})

        # ─── BẢO VỆ 3: ORDER REJECTION WATCHER & FALLBACK SIZING ────────
        if order_id and order_id in self._last_orders:
            last_order = self._last_orders[order_id]
            retries = self._rejection_counts.get(order_id, 0)

            # Chỉ tự động retry đối với lệnh ENTRY khi chưa vượt quá số lần retry tối đa
            if last_order.action_type == "ENTRY" and retries < self.max_rejection_retries:
                self._rejection_counts[order_id] = retries + 1
                orig_qty = last_order.qty_contracts
                spec = self.exec_model.spec

                # Tính fallback size: giảm 50% khối lượng, làm tròn bước lotSz
                reduced_qty = spec.lotSz * math.floor((orig_qty * 0.5) / spec.lotSz)
                fallback_qty = max(spec.minSz, reduced_qty)

                if fallback_qty >= spec.minSz and fallback_qty < orig_qty:
                    log.info(
                        f"[{spec.symbol}] [REJECTION WATCHER] Kích hoạt auto-retry (lần {retries + 1}/{self.max_rejection_retries}) "
                        f"với Fallback Size: {fallback_qty} contracts (gốc: {orig_qty})"
                    )

                    cv = spec.contract_value
                    coin_qty = fallback_qty * cv
                    notional_q = fallback_qty * cv * last_order.expected_price
                    notional_ac = notional_q * 1.0
                    margin_ac = notional_ac * self.exec_model.effective_margin_ratio

                    retry_action = OrderAction(
                        action_type="ENTRY",
                        side=last_order.side,
                        qty_contracts=fallback_qty,
                        coin_qty=coin_qty,
                        expected_price=last_order.expected_price,
                        notional_quote=notional_q,
                        notional_account=notional_ac,
                        margin_account=margin_ac,
                        order_type=last_order.order_type,
                        sl_price=last_order.sl_price,
                        tp_price=last_order.tp_price,
                        order_id=f"{order_id}_retry_{retries + 1}",
                        estimated_fee_ac=notional_ac * spec.taker_fee_rate,
                    )

                    if retry_action.order_id:
                        self._last_orders[retry_action.order_id] = retry_action
                    self._record_audit_event("ORDER_RETRY_SUBMITTED", {
                        "orig_order_id": order_id,
                        "retry_order_id": retry_action.order_id,
                        "fallback_qty": fallback_qty,
                        "attempt": retries + 1,
                    })

                    if self.broker_order_submitter:
                        try:
                            self.broker_order_submitter(retry_action)
                        except Exception as e:
                            log.error(f"Lỗi khi phát lệnh retry: {e}")

        self._persist_state()

    def handle_broker_cancel(self, order_id: Optional[str] = None) -> None:
        """Xử lý sự kiện sàn xác nhận đã hủy lệnh."""
        self.exec_model.on_cancel(order_id=order_id)
        self._record_audit_event("CANCEL_CONFIRMED", {"order_id": order_id})
        self._persist_state()

    def handle_protective_ack(self, sl_order_id: str, tp_order_id: str) -> None:
        """Xử lý xác nhận lệnh bảo vệ SL/TP từ sàn."""
        self.exec_model.on_protective_ack(sl_order_id, tp_order_id)
        self._record_audit_event("PROTECTIVE_ACK", {"sl": sl_order_id, "tp": tp_order_id})
        self._persist_state()

    def handle_protective_reject(self, reason: str = "") -> None:
        """Xử lý sự kiện lệnh bảo vệ bị từ chối -> Kích hoạt thoát khẩn cấp."""
        log.critical(f"[{self.reader.symbol}] Lệnh bảo vệ bị từ chối! Kích hoạt phòng vệ khẩn cấp: {reason}")
        self.exec_model.on_protective_reject(reason)
        self._record_audit_event("PROTECTIVE_REJECTED", {"reason": reason})
        self._persist_state()

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Lấy bản chụp trạng thái hiện tại phục vụ UI và Telemetry."""
        pos = self.exec_model.pos
        return {
            "symbol": self.reader.symbol,
            "lifecycle_state": self.exec_model.lifecycle_state.value,
            "capital": self.exec_model.capital,
            "risk_budget_e": self.exec_model.risk_budget_e,
            "qty_contracts": pos.qty_contracts,
            "entry_price": pos.entry_price,
            "sl_price": pos.sl_price,
            "tp_price": pos.tp_price,
            "protective_status": pos.protective_status.value,
            "cycle_realized_pnl": pos.cycle_realized_pnl,
            "total_fees_paid": pos.total_fees_paid,
            "has_pending_order": self.exec_model.pending_order is not None,
            "closed_cycles_count": len(self.exec_model.closed_cycles),
            "last_cycle_result": (
                self.exec_model.last_cycle_result.__dict__
                if self.exec_model.last_cycle_result else None
            ),
        }

    def force_close_all_positions(
        self,
        price: Optional[float] = None,
        reason: ExitReason = ExitReason.SESSION_CUTOFF,
    ) -> Optional[OrderAction]:
        """Đóng khẩn cấp toàn bộ vị thế khi người dùng dừng bot."""
        action = self.exec_model.force_close_all(price=price, reason=reason)
        if action:
            self._record_audit_event("FORCE_CLOSE_ALL", {
                "reason": reason.value,
                "qty": action.qty_contracts,
                "price": action.expected_price,
            })
            self._persist_state()
        return action

    def close(self) -> None:
        """Dọn dẹp và dừng runner an toàn."""
        self.request_graceful_pause()
        self._persist_state()

    # ─── PERSISTENCE CHUẨN NORA (bot.json, events.jsonl, equity.jsonl, positions.json) ──

    def _init_persistence_files(self) -> None:
        """Khởi tạo cấu trúc file persistence chuẩn Nora."""
        if not self.bot_dir:
            return

        bot_json_path = os.path.join(self.bot_dir, "bot.json")
        if not os.path.isfile(bot_json_path):
            bot_data = {
                "bot_id": self.bot_id,
                "mode": self.mode,
                "symbol": self.reader.symbol,
                "strategy": "Proxima_KEMA_BandGrid",
                "status": "running",
                "capital": self.exec_model.capital,
                "pid": os.getpid(),
                "started_at": int(time.time() * 1000),
                "specs": {
                    "ctVal": self.exec_model.spec.ctVal,
                    "lotSz": self.exec_model.spec.lotSz,
                    "minSz": self.exec_model.spec.minSz,
                    "multiplier": self.exec_model.spec.multiplier,
                },
            }
            write_json_atomic(bot_json_path, bot_data, indent=2)

        events_path = os.path.join(self.bot_dir, "events.jsonl")
        if not os.path.isfile(events_path):
            self._record_audit_event("BOT_INITIALIZED", {
                "bot_id": self.bot_id,
                "mode": self.mode,
                "symbol": self.reader.symbol,
                "capital": self.exec_model.capital,
                "execution_type": "ProximaDecoupledPaperSimulator",
                "shadow_mode": self.shadow_mode,
                "specs": {
                    "ctVal": self.exec_model.spec.ctVal,
                    "lotSz": self.exec_model.spec.lotSz,
                    "minSz": self.exec_model.spec.minSz,
                    "multiplier": self.exec_model.spec.multiplier,
                },
            })

    def _persist_state(self, timestamp: Optional[int] = None) -> None:
        """Đồng bộ trạng thái vào bot.json, equity.jsonl, positions.json, heartbeat.json."""
        if not self.bot_dir:
            return

        ts = timestamp or int(time.time() * 1000)
        pos = self.exec_model.pos
        mark_price = pos.entry_price if pos.entry_price > 0 else (self.reader._1m_bars[-1]["close"] if self.reader._1m_bars else 0.0)

        # 1. positions.json
        positions_path = os.path.join(self.bot_dir, "positions.json")
        positions_view = []
        if pos.qty_contracts != 0:
            cv = self.exec_model.spec.contract_value
            is_long = pos.qty_contracts > 0
            unrealized = (mark_price - pos.entry_price) * pos.qty_contracts * cv
            pnl_pct = ((mark_price - pos.entry_price) / pos.entry_price * 100.0) if is_long else ((pos.entry_price - mark_price) / pos.entry_price * 100.0)
            positions_view.append({
                "symbol": self.reader.symbol,
                "side": "LONG" if is_long else "SHORT",
                "qty": abs(pos.qty_contracts),
                "entry_price": round(pos.entry_price, 4),
                "mark_price": round(mark_price, 4),
                "unrealized_pnl": round(unrealized, 4),
                "pnl_pct": round(pnl_pct, 2),
                "sl_price": pos.sl_price,
                "tp_price": pos.tp_price,
            })
        try:
            write_json_atomic(positions_path, positions_view, indent=2)
        except Exception:
            pass

        # 2. equity.jsonl
        equity_path = os.path.join(self.bot_dir, "equity.jsonl")
        cv = self.exec_model.spec.contract_value
        unrealized = (mark_price - pos.entry_price) * pos.qty_contracts * cv if pos.qty_contracts != 0 else 0.0
        balance = self.exec_model.capital + pos.cycle_realized_pnl - pos.total_fees_paid
        total_equity = balance + unrealized

        eq_point = {
            "ts": ts,
            "equity": round(total_equity, 2),
            "balance": round(balance, 2),
            "unrealized": round(unrealized, 2),
            "open_positions": 1 if pos.qty_contracts != 0 else 0,
            "closed_cycles": len(self.exec_model.closed_cycles),
        }
        try:
            with open(equity_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(eq_point) + "\n")
        except Exception:
            pass

        # 3. heartbeat.json
        hb_path = os.path.join(self.bot_dir, "heartbeat.json")
        hb_data = {
            "updated_at": ts,
            "symbol": self.reader.symbol,
            "last_bar_ts": self.reader._last_1m_ts,
            "status": self.lifecycle_state.value,
            "marks": {self.reader.symbol: mark_price},
        }
        try:
            write_json_atomic(hb_path, hb_data, indent=2)
        except Exception:
            pass

    def _record_audit_event(self, event_type: str, payload: Any) -> None:
        """Ghi nhận sự kiện kiểm toán vận hành và lưu vào events.jsonl."""
        ts = int(time.time() * 1000)
        event_row = {
            "t": ts,
            "type": event_type,
            "event": event_type,
            "payload": payload if isinstance(payload, dict) else str(payload),
        }
        self.execution_audit_log.append(event_row)

        if self.bot_dir:
            events_path = os.path.join(self.bot_dir, "events.jsonl")
            try:
                with open(events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event_row, ensure_ascii=False) + "\n")
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════════════════
# 2 WORKERS ARCHITECTURE: Con 1 (Market Listener) & Con 2 (Execution Worker)
# ════════════════════════════════════════════════════════════════════════════

class RedisBus:
    """Bus truyền thông tin giữa Market Listener và Execution Worker qua Redis Pub/Sub."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        channel_prefix: str = "nora",
        in_memory_only: bool = False,
    ):
        self.channel_prefix = channel_prefix
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.in_memory_only = in_memory_only
        self._client: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._is_connected: bool = False
        self._fallback_handlers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._listener_thread: Optional[threading.Thread] = None
        self._running: bool = False

        # Hệ thống đảm bảo độ tin cậy tin nhắn (Delivery Guarantees)
        self._seq_counter: int = 0
        self._backlog: Dict[str, collections.deque] = {}  # channel -> deque(maxlen=2000)
        self._expected_seq: Dict[str, int] = {}          # channel -> expected seq_id
        self._gap_detected_count: int = 0
        self._acks_received: Dict[str, Set[int]] = {}

        if not self.in_memory_only:
            self._connect()

    def _connect(self) -> None:
        if not _HAS_REDIS:
            log.warning("Thư viện redis chưa cài đặt -> Dùng fallback in-memory bus.")
            return

        try:
            self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
            self._client.ping()
            self._is_connected = True
            log.info(f"Kết nối Redis Pub/Sub thành công tại {self.redis_url}")
        except Exception as e:
            log.warning(f"Không thể kết nối Redis ({e}) -> Sử dụng fallback in-memory bus.")
            self._client = None
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def publish_market_reading(self, symbol: str, reading_dict: Dict[str, Any]) -> bool:
        """Con 1: Bắn MarketReading lên Redis channel nora:market:{symbol} kèm sequence ID."""
        channel = f"{self.channel_prefix}:market:{symbol}"
        self._seq_counter += 1
        seq = self._seq_counter
        envelope = {
            "_seq_id": seq,
            "_ts": int(time.time() * 1000),
            "payload": reading_dict,
        }

        if channel not in self._backlog:
            self._backlog[channel] = collections.deque(maxlen=2000)
        self._backlog[channel].append(envelope)

        payload_str = json.dumps(envelope, ensure_ascii=False)

        if self._is_connected and self._client:
            try:
                self._client.publish(channel, payload_str)
                return True
            except Exception as e:
                log.error(f"Lỗi publish market reading lên Redis: {e}")

        # In-memory fallback
        for handler in self._fallback_handlers.get(channel, []):
            try:
                self._dispatch(channel, envelope, handler)
            except Exception as err:
                log.error(f"Lỗi fallback handler: {err}")
        return True

    def publish_order_action(self, bot_id: str, action_dict: Dict[str, Any]) -> bool:
        """Con 2: Bắn OrderAction lên Redis channel nora:orders:{bot_id} kèm sequence ID."""
        channel = f"{self.channel_prefix}:orders:{bot_id}"
        self._seq_counter += 1
        seq = self._seq_counter
        envelope = {
            "_seq_id": seq,
            "_ts": int(time.time() * 1000),
            "payload": action_dict,
        }

        if channel not in self._backlog:
            self._backlog[channel] = collections.deque(maxlen=2000)
        self._backlog[channel].append(envelope)

        payload_str = json.dumps(envelope, ensure_ascii=False)

        if self._is_connected and self._client:
            try:
                self._client.publish(channel, payload_str)
                return True
            except Exception as e:
                log.error(f"Lỗi publish order action lên Redis: {e}")

        for handler in self._fallback_handlers.get(channel, []):
            try:
                self._dispatch(channel, envelope, handler)
            except Exception as err:
                log.error(f"Lỗi fallback handler: {err}")
        return True

    def subscribe_market(
        self,
        symbol: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Con 2: Đăng ký nhận nến / tín hiệu thị trường của symbol từ Redis."""
        channel = f"{self.channel_prefix}:market:{symbol}"
        self._fallback_handlers.setdefault(channel, []).append(callback)

        if self._is_connected and self._client:
            if not self._pubsub:
                self._pubsub = self._client.pubsub()
            self._pubsub.subscribe(**{channel: lambda msg: self._handle_redis_msg(channel, msg, callback)})
            if not self._running:
                self._start_listener()

    def subscribe_orders(
        self,
        bot_id: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Đăng ký nhận lệnh từ bot."""
        channel = f"{self.channel_prefix}:orders:{bot_id}"
        self._fallback_handlers.setdefault(channel, []).append(callback)

        if self._is_connected and self._client:
            if not self._pubsub:
                self._pubsub = self._client.pubsub()
            self._pubsub.subscribe(**{channel: lambda msg: self._handle_redis_msg(channel, msg, callback)})
            if not self._running:
                self._start_listener()

    def _dispatch(self, channel: str, parsed_msg: Dict[str, Any], callback: Callable[[Dict[str, Any]], None]) -> None:
        """Phát tán tin nhắn tới callback với giám sát hở mạch / mất gói."""
        if isinstance(parsed_msg, dict) and "_seq_id" in parsed_msg:
            seq = parsed_msg["_seq_id"]
            expected = self._expected_seq.get(channel, 0)
            if expected > 0 and seq > expected:
                gap = seq - expected
                self._gap_detected_count += gap
                log.warning(f"[{channel}] [REDIS BUS] Phát hiện hở mạch / mất {gap} tin nhắn! Kì vọng seq {expected}, nhận {seq}.")
            self._expected_seq[channel] = seq + 1
            actual_data = parsed_msg.get("payload") or parsed_msg
        else:
            actual_data = parsed_msg

        callback(actual_data)

    def _handle_redis_msg(self, channel: str, message: Any, callback: Callable[[Dict[str, Any]], None]) -> None:
        if not message or message.get("type") != "message":
            return
        data_str = message.get("data")
        if not data_str:
            return
        try:
            parsed = json.loads(data_str)
            self._dispatch(channel, parsed, callback)
        except Exception as e:
            log.error(f"Lỗi giải mã JSON từ Redis channel {channel}: {e}")

    def ack(self, channel: str, seq_id: int) -> None:
        """Xác nhận đã tiếp nhận và xử lý thành công tin nhắn seq_id."""
        self._acks_received.setdefault(channel, set()).add(seq_id)

    def get_backlog(self, channel: str, from_seq: int = 0) -> List[Dict[str, Any]]:
        """Truy xuất backlog buffer tin nhắn phục vụ phục hồi khi ngắt kết nối."""
        if channel not in self._backlog:
            return []
        return [msg for msg in self._backlog[channel] if msg.get("_seq_id", 0) >= from_seq]

    def _start_listener(self) -> None:
        self._running = True

        def _worker():
            log.info("Redis Pub/Sub listener thread khởi động...")
            while self._running and self._pubsub:
                try:
                    self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except Exception as e:
                    if self._running:
                        log.warning(f"Lỗi trong Redis pubsub loop: {e}")
                        time.sleep(1.0)

        self._listener_thread = threading.Thread(target=_worker, daemon=True)
        self._listener_thread.start()

    def close(self) -> None:
        self._running = False
        if self._pubsub:
            try:
                self._pubsub.close()
            except Exception:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass


class MarketListenerWorker:
    """Worker 1: Lắng nghe dữ liệu thị trường và ném lên Redis.
    
    Nhiệm vụ:
    - Nhận nến 1m từ WebSocket / REST feed.
    - Chuyển vào MarketDataReader (readings.py) để resample 1h, tính EMA_K, ATR(14), z, w.
    - Bắn MarketReading lên Redis Pub/Sub (channel nora:market:{symbol}).
    """

    def __init__(
        self,
        reader: MarketDataReader,
        redis_bus: RedisBus,
    ):
        self.reader = reader
        self.redis_bus = redis_bus
        self.reader.redis_bus = redis_bus

    def on_raw_bar(self, bar: Dict[str, float]) -> Optional[MarketReading]:
        """Nhận nến thô 1m từ nguồn cấp (Feed) và phát tán lên Redis qua readings.py."""
        reading = self.reader.feed_1m_bar(bar)
        return reading


class ExecutionWorker:
    """Worker 2: Đọc MarketReading từ Redis để vào/thoát lệnh.
    
    Nhiệm vụ:
    - Đăng ký (Subscribe) channel nora:market:{symbol} từ RedisBus.
    - Áp dụng các chốt kiểm soát an toàn (Feed Latency Guard, Sizing 3 cận, 6 bước thoát lệnh).
    - Phát OrderAction tới sàn / Sandbox.
    - Giám sát trượt giá Execution Delta & Auto-retry khi bị từ chối.
    - Ghi nhận đầy đủ persistence chuẩn Nora (bot.json, events, equity, positions).
    """

    def __init__(
        self,
        runner: AdapterRunner,
        redis_bus: RedisBus,
    ):
        self.runner = runner
        self.redis_bus = redis_bus
        self._subscribe_to_redis()

    def _subscribe_to_redis(self) -> None:
        symbol = self.runner.reader.symbol
        log.info(f"ExecutionWorker subscribing to Redis channel for {symbol}...")
        self.redis_bus.subscribe_market(symbol, self._on_market_reading_cb)

    def _on_market_reading_cb(self, reading_dict: Dict[str, Any]) -> None:
        self.on_market_reading_received(reading_dict)

    def on_market_reading_received(self, reading_dict: Dict[str, Any]) -> Optional[OrderAction]:
        """Callback khi nhận được MarketReading từ Redis."""
        if isinstance(reading_dict, MarketReading):
            reading = reading_dict
        elif hasattr(MarketReading, "from_dict"):
            reading = MarketReading.from_dict(reading_dict)
        else:
            reading = MarketReading(
                timestamp=int(reading_dict.get("timestamp", 0)),
                symbol=str(reading_dict.get("symbol", self.runner.reader.symbol)),
                open=float(reading_dict.get("open", 0.0)),
                high=float(reading_dict.get("high", 0.0)),
                low=float(reading_dict.get("low", 0.0)),
                close=float(reading_dict.get("close", 0.0)),
                volume=float(reading_dict.get("volume", 0.0)),
                closed_1h_bars=reading_dict.get("closed_1h_bars", []),
                is_warmed_up=bool(reading_dict.get("is_warmed_up", False)),
                ema=reading_dict.get("ema"),
                atr=reading_dict.get("atr"),
                upper_band=reading_dict.get("upper_band"),
                lower_band=reading_dict.get("lower_band"),
                k_delta=reading_dict.get("k_delta"),
                z_score=float(reading_dict.get("z_score", 0.0)),
                w_score=float(reading_dict.get("w_score", 0.0)),
                breakout_signal=str(reading_dict.get("breakout_signal", "FLAT")),
                regime=str(reading_dict.get("regime", "RANGE")),
                regime_context=reading_dict.get("regime_context", {}),
            )
        return self.runner.on_market_reading(reading)


def create_decoupled_proxima_bot(
    symbol: str,
    spec: InstrumentSpec,
    capital: float = 10000.0,
    r_ratio: float = 0.15,
    vl_mult: float = 0.75,
    tp_mult: float = 0.8,
    f_mult: float = 1.0,
    mode: str = "paper",
    bot_id: Optional[str] = None,
    redis_bus: Optional[RedisBus] = None,
    broker_order_submitter: Optional[Callable[[OrderAction], str]] = None,
    broker_order_canceller: Optional[Callable[[str], bool]] = None,
    bot_dir: Optional[str] = None,
    check_latency: bool = False,
    anchor_tf: Optional[str] = "1h",
    signal_mode: str = "breakout",
    shadow_mode: bool = False,
    sync_specs: bool = False,
) -> Tuple[MarketListenerWorker, ExecutionWorker, AdapterRunner]:
    """Factory khởi tạo đầy đủ hệ thống 2 Worker & Runner cho bot Proxima Decoupled."""
    bot_id = bot_id or f"proxima_{symbol.lower().replace('-', '_')}_{mode}"
    bot_dir = bot_dir or os.path.join(data_home(), "live", mode, bot_id)

    bus = redis_bus or RedisBus()

    active_spec = sync_okx_specs(symbol) if sync_specs else spec

    reader = MarketDataReader(
        symbol=symbol,
        anchor_tf=anchor_tf,
        signal_mode=signal_mode,
        f_multiplier=f_mult,
        redis_bus=bus,
    )
    exec_model = UniversalExecutionModel(
        spec=active_spec,
        capital=capital,
        r_ratio=r_ratio,
        vl_mult=vl_mult,
        auto_fill_simulation=(mode == "paper" and broker_order_submitter is None and not shadow_mode),
        bot_id=bot_id,
        mode=mode,
        enforce_risk_gate=(mode != "backtest"),
        shadow_mode=shadow_mode,
    )
    sig_engine = ProximaSignalEngine(
        f_multiplier=f_mult,
        tp_mult=tp_mult,
    )

    runner = AdapterRunner(
        reader=reader,
        execution_model=exec_model,
        signal_engine=sig_engine,
        broker_order_submitter=broker_order_submitter,
        broker_order_canceller=broker_order_canceller,
        bot_dir=bot_dir,
        bot_id=bot_id,
        mode=mode,
        check_latency=check_latency,
        shadow_mode=shadow_mode,
    )

    listener_worker = MarketListenerWorker(reader=reader, redis_bus=bus)
    execution_worker = ExecutionWorker(runner=runner, redis_bus=bus)

    return listener_worker, execution_worker, runner


def run_decoupled_proxima_live(params: Dict[str, Any]) -> Dict[str, Any]:
    """Khởi chạy Bot Proxima Decoupled (2 Worker qua RedisBus) trên môi trường Live/Paper/Testnet.

    Quy chuẩn vận hành Nora:
    - Worker 1 (MarketListenerWorker): Tiếp nhận nến 1m, gom nến anchor (15m/30m/1h), tính EMA_K, ATR(14), z, w, Regime nhẹ và publish MarketReading lên Redis.
    - Worker 2 (ExecutionWorker): Lắng nghe Redis, áp dụng 3 chốt bảo vệ (Feed Latency, Execution Delta, Auto-retry Rejection),
      Sizing 3 cận an toàn (c1, c2, c3), 6 bước thoát lệnh (SL -0.8% E, Cutoff, Center, Opposite, Partial TP +5%*TP).
    - Hỗ trợ Shadow Mode (shadow=True) chạy song song an toàn tuyệt đối, không can thiệp lệnh thật hay ảnh hưởng paper bots.
    - Đồng bộ persistence chuẩn Nora: bot.json, events.jsonl, equity.jsonl, positions.json, heartbeat.json.
    - Giám sát cờ dừng: Nhận stop file (<bot_dir>/stop), gọi request_graceful_pause(), đóng vị thế nếu close=True, và cập nhật status="stopped".
    """
    from backend.adapter.execution import get_universal_spec, sync_okx_specs
    from backend.core import live as lv
    from backend.models.storage import pid_start_ticks

    mode = str(params.get("mode", "paper"))
    capital = float(params.get("capital") or 10000.0)
    r_ratio = float(params.get("r_ratio") or 0.15)
    vl_mult = float(params.get("vl_mult") or 0.75)
    tp_mult = float(params.get("tp_mult") or 0.8)
    f_mult = float(params.get("f_mult") or 1.0)
    anchor_tf = str(params.get("anchor_tf") or "1h")
    signal_mode = str(params.get("signal_mode") or "breakout")
    shadow_mode = bool(params.get("shadow", False))
    sync_specs_flag = bool(params.get("sync_specs", True))

    bot_id = str(params.get("bot_id") or lv.new_bot_id(mode))

    raw_symbols = params.get("symbols") or ["BTC-USDT-SWAP"]
    if isinstance(raw_symbols, str):
        raw_symbols = [x.strip() for x in raw_symbols.split(",") if x.strip()]
    primary_sym = raw_symbols[0].replace("@perp", "").replace("@PERP", "")
    if not primary_sym.endswith("-SWAP") and "-" not in primary_sym and "/" not in primary_sym and primary_sym in ("BTC", "ETH", "SOL"):
        primary_sym = f"{primary_sym}-USDT-SWAP"

    spec = sync_okx_specs(primary_sym) if sync_specs_flag else get_universal_spec(primary_sym)
    bot_dir = os.path.join(lv.data_home(), "live", mode, bot_id)
    os.makedirs(bot_dir, exist_ok=True)

    bus = RedisBus()
    listener_worker, execution_worker, runner = create_decoupled_proxima_bot(
        symbol=primary_sym,
        spec=spec,
        capital=capital,
        r_ratio=r_ratio,
        vl_mult=vl_mult,
        tp_mult=tp_mult,
        f_mult=f_mult,
        mode=mode,
        bot_id=bot_id,
        bot_dir=bot_dir,
        redis_bus=bus,
        check_latency=(mode != "paper"),
        anchor_tf=anchor_tf,
        signal_mode=signal_mode,
        shadow_mode=shadow_mode,
        sync_specs=False,  # đã sync ở trên
    )

    runner._persist_state()

    lv.set_status(
        bot_dir,
        "running",
        pid=os.getpid(),
        pid_start=pid_start_ticks(os.getpid()),
        strategy="proxima_decoupled",
        job_id=os.path.basename(os.environ.get("NORA_JOB_DIR", "")) or None,
    )
    print(f"[{mode.upper()}] Proxima Decoupled Bot {bot_id} đang chạy: {primary_sym} · R={r_ratio} · VL={vl_mult} · TP={tp_mult} · F={f_mult}...", flush=True)

    stop_file = os.path.join(bot_dir, "stop")

    # ─── BƯỚC WARMUP TOÀN DIỆN: Nạp đủ 50 nến Anchor 1h + 100 nến 1m ───
    try:
        inst_id = primary_sym
        if not inst_id.endswith("-SWAP") and ("BTC" in inst_id or "ETH" in inst_id or "SOL" in inst_id):
            inst_id = f"{inst_id}-USDT-SWAP"

        # 1. Nạp 50 nến Anchor từ OKX API (1H / 15m / 30m) để tính EMA(20) và ATR(14)
        bar_param = "1H"
        if anchor_tf.lower().endswith("m"):
            bar_param = anchor_tf
        elif anchor_tf.lower().endswith("h"):
            bar_param = anchor_tf.upper()

        url_anchor = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar={bar_param}&limit=50"
        req_a = urllib.request.Request(url_anchor, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_a, timeout=8) as r:
            res_a = json.loads(r.read())
            if res_a.get("code") == "0" and res_a.get("data"):
                raw_anchor = list(reversed(res_a["data"]))
                closed_anchors = []
                for c in raw_anchor:
                    closed_anchors.append({
                        "timestamp": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    })
                runner.reader.closed_1h_bars = closed_anchors
                runner.reader._compute_indicators()
                runner.signal_engine.update_anchor_indicators(closed_anchors)
                ema_val = runner.reader._cached_ema or 0.0
                atr_val = runner.reader._cached_atr or 0.0
                print(f"[{mode.upper()}] Đã nạp {len(closed_anchors)} nến Anchor {bar_param} thành công (EMA={ema_val:.2f}, ATR={atr_val:.2f}, is_warmed_up={runner.reader.is_warmed_up}).", flush=True)

        # 2. Nạp 100 nến 1m gần nhất để làm nóng bộ đệm 1m và tính z-score/w-score
        url_1m = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=100"
        req_1m = urllib.request.Request(url_1m, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_1m, timeout=8) as r:
            res_1m = json.loads(r.read())
            if res_1m.get("code") == "0" and res_1m.get("data"):
                raw_1m = list(reversed(res_1m["data"]))
                for c in raw_1m:
                    ts = int(c[0])
                    bar = {
                        "timestamp": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                    runner.reader._1m_bars.append(bar)
                    runner.reader._seen_1m_ts.add(ts)
                    runner.reader._last_1m_ts = max(runner.reader._last_1m_ts, ts)
                print(f"[{mode.upper()}] Đã nạp {len(raw_1m)} nến 1m lịch sử vào bộ đọc.", flush=True)

        runner._record_audit_event("WARMUP_COMPLETED", {
            "anchor_tf": anchor_tf,
            "closed_anchors_count": len(runner.reader.closed_1h_bars),
            "cached_ema": runner.reader._cached_ema,
            "cached_atr": runner.reader._cached_atr,
            "is_warmed_up": runner.reader.is_warmed_up,
        })
        runner._persist_state()
    except Exception as e:
        log.warning(f"Lỗi nạp nến warmup: {e}")

    last_poll_ts = 0
    last_closed_ts = runner.reader._last_1m_ts

    try:
        while True:
            # 1. Kiểm tra cờ dừng bot từ Web UI / API
            flag = lv.stop_flag(bot_dir)
            if flag is not None or os.path.isfile(stop_file):
                close = True
                if isinstance(flag, dict):
                    close = bool(flag.get("close", True))
                print(f"[{mode.upper()}] Nhận cờ dừng cho {bot_id} (close={close}), đang dừng bot...", flush=True)
                runner.request_graceful_pause()
                if close and runner.exec_model.pos.qty_contracts != 0:
                    runner.force_close_all_positions(reason=ExitReason.SESSION_CUTOFF)
                runner.close()
                bus.close()
                lv.set_status(bot_dir, "stopped")
                break

            # 2. Lấy nến thời gian thực từ sàn OKX
            now_ts = int(time.time())
            if now_ts - last_poll_ts >= 3:
                last_poll_ts = now_ts
                try:
                    inst_id = primary_sym
                    if not inst_id.endswith("-SWAP") and ("BTC" in inst_id or "ETH" in inst_id or "SOL" in inst_id):
                        inst_id = f"{inst_id}-USDT-SWAP"
                    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=3"
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=3) as r:
                        res = json.loads(r.read())
                        if res.get("code") == "0" and res.get("data") and len(res["data"]) >= 2:
                            # 2.1 Cập nhật mark_price tức thời từ nến đang chạy (res["data"][0])
                            live_c = res["data"][0]
                            mark_px = float(live_c[4])
                            if runner.exec_model.pos.qty_contracts != 0:
                                runner.exec_model.pos.mark_price = mark_px

                            # 2.2 Lấy nến 1m ĐÃ ĐÓNG HOÀN TOÀN (res["data"][1])
                            closed_c = res["data"][1]
                            closed_ts = int(closed_c[0])

                            if closed_ts > last_closed_ts:
                                last_closed_ts = closed_ts
                                closed_bar = {
                                    "timestamp": closed_ts,
                                    "open": float(closed_c[1]),
                                    "high": float(closed_c[2]),
                                    "low": float(closed_c[3]),
                                    "close": float(closed_c[4]),
                                    "volume": float(closed_c[5]),
                                }
                                listener_worker.on_raw_bar(closed_bar)
                except Exception as poll_err:
                    log.debug(f"Poll nến OKX warning: {poll_err}")

            time.sleep(1.0)
    finally:
        runner.close()
        bus.close()

    return {"bot_id": bot_id, "mode": mode, "status": "stopped" if os.path.isfile(stop_file) else "running"}

