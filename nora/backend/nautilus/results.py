"""Bộ chuyển đổi kết quả từ NautilusTrader sang hợp đồng dữ liệu Nora (P15 Native).

Trích xuất trực tiếp từ engine Nautilus:
- Positions -> PositionModel (hỗ trợ cả đóng và đang mở)
- Orders/Fills -> OrderModel
- Equity curve -> chuỗi mẫu MTM theo thời gian
- Tóm tắt theo tài sản (by_symbol)
- Metrics và Provenance
"""
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from nautilus_trader.model.enums import OrderSide, PositionSide
from backend.models.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType, next_id
from backend.nautilus.engine import provenance


def parse_commissions(commissions: Any) -> float:
    """Tính tổng phí USD từ danh sách hoa hồng của Nautilus (vd: ['0.42540850 USDT'])."""
    if commissions is None:
        return 0.0
    if callable(commissions):
        try:
            commissions = commissions()
        except Exception:
            return 0.0
    if isinstance(commissions, (int, float)):
        return float(commissions)
    total = 0.0
    for c in commissions:
        try:
            if hasattr(c, "as_double"):
                total += c.as_double()
            elif isinstance(c, str):
                val = float(c.split()[0])
                total += val
            else:
                total += float(c)
        except Exception:
            pass
    return round(total, 6)


def extract_models_from_nautilus(
    engine: Any,
    strategy_id: str = "NAUTILUS_NATIVE",
    initial_capital: float = 10_000.0,
) -> Tuple[List[PositionModel], List[OrderModel], List[Dict[str, Any]]]:
    """Trích xuất PositionModel, OrderModel và danh sách vị thế mở từ eng.cache."""
    positions_closed: List[PositionModel] = []
    orders_all: List[OrderModel] = []
    positions_open: List[Dict[str, Any]] = []

    # Bản đồ order theo position_id
    pos_orders_map: Dict[str, List[Any]] = {}
    for o in engine.cache.orders():
        pid = str(o.position_id) if hasattr(o, "position_id") and o.position_id else ""
        if pid:
            pos_orders_map.setdefault(pid, []).append(o)

    for p in engine.cache.positions():
        sym = str(p.instrument_id).split(".")[0]
        is_long = (p.entry == OrderSide.BUY)
        pos_type = PositionType.LONG if is_long else PositionType.SHORT
        pid = str(p.id)

        # Orders liên kết với vị thế này
        linked_orders = pos_orders_map.get(pid, [])
        order_models_pos: List[OrderModel] = []
        rid = next_id()

        for lo in linked_orders:
            ot = OrderType.BUY if lo.side == OrderSide.BUY else OrderType.SELL
            px = float(lo.avg_px) if hasattr(lo, "avg_px") and lo.avg_px else 0.0
            qty = float(lo.filled_qty) if hasattr(lo, "filled_qty") and lo.filled_qty else 0.0
            order_ts = int((lo.ts_last or lo.ts_init) // 1_000_000)
            fee = parse_commissions(getattr(lo, "commissions", None))
            om = OrderModel(
                order_id=next_id(),
                account_id=0,
                position_id=rid,
                order_time=order_ts,
                order_type=ot,
                order_price=px,
                qty=qty,
                phase=0,
                fee_usd=fee,
                liquidity="taker",
                slippage=0.0,
            )
            order_models_pos.append(om)
            orders_all.append(om)

        fee_total = parse_commissions(p.commissions() if callable(p.commissions) else p.commissions)
        qty = float(p.peak_qty) if hasattr(p, "peak_qty") and p.peak_qty else float(p.quantity)

        # Kiểm tra trạng thái đóng hay mở
        is_closed = (p.side == PositionSide.FLAT)
        if is_closed:
            enter_ts = int(p.ts_opened // 1_000_000) if p.ts_opened else 0
            close_ts = int(p.ts_closed // 1_000_000) if p.ts_closed else 0
            avg_open = float(p.avg_px_open) if p.avg_px_open else 0.0
            avg_close = float(p.avg_px_close) if p.avg_px_close else 0.0
            pnl = p.realized_pnl.as_double() if hasattr(p.realized_pnl, "as_double") else float(p.realized_pnl or 0.0)

            # Profit status
            status = PositionStatus.TP if pnl > 0 else PositionStatus.SL
            close_reason = "Take-profit" if pnl > 0 else "Stop-loss"

            pm = PositionModel(
                result_id=rid,
                account_id=0,
                campaign_id=0,
                symbol=sym,
                pos_type=pos_type,
                phase=0,
                enter_time=enter_ts,
                enter_price=avg_open,
                close_time=close_ts,
                close_price=avg_close,
                status=status,
                real_pnl=round(pnl, 4),
                profit_pct=round(pnl / initial_capital * 100.0, 4) if initial_capital > 0 else 0.0,
                flow="",
                start_reason="Tín hiệu vào lệnh Nautilus",
                close_reason=close_reason,
                max_price=avg_open,
                min_price=avg_close,
                qty=qty,
                entry_equity=initial_capital,
                entry_margin_usd=avg_open * qty,
                entry_notional_usd=avg_open * qty,
                entry_fee_usd=0.0,
                exit_fee_usd=fee_total,
                layers=1,
                avg_price=avg_open,
                total_margin_usd=avg_open * qty,
                mae_pct=0.0,
                fees_usd=fee_total,
                funding_usd=0.0,
                unit_pct=0.0,
                leverage_used=1.0,
                risk_usd=0.0,
                strategy_id=strategy_id,
            )
            positions_closed.append(pm)
        else:
            # Vị thế còn mở
            avg_open = float(p.avg_px_open) if p.avg_px_open else 0.0
            unreal = 0.0
            if hasattr(p, "unrealized_pnl"):
                try:
                    from nautilus_trader.model.objects import Price
                    unreal = p.unrealized_pnl(Price.from_str(f"{avg_open:.6f}")).as_double()
                except Exception:
                    unreal = 0.0
            positions_open.append({
                "symbol": sym,
                "strategy": strategy_id,
                "side": "LONG" if is_long else "SHORT",
                "qty": qty,
                "entry_price": avg_open,
                "mark_price": avg_open,
                "notional": avg_open * qty,
                "unrealized_pnl": round(unreal, 4),
                "opened": int(p.ts_opened // 1_000_000) if p.ts_opened else 0,
                "margin_usd": avg_open * qty,
                "leverage": 1.0,
            })

    return positions_closed, orders_all, positions_open


def format_nautilus_results(
    engine: Any,
    equity_curve: List[Dict[str, float]],
    initial_capital: float,
    start_ms: int,
    end_ms: int,
    base_frame: str = "1h",
    strategy_id: str = "NAUTILUS_NATIVE",
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Đóng gói kết quả từ Native Nautilus BacktestEngine thành payload tương thích UI Nora."""
    warns = list(warnings or [])
    positions, orders, open_pos = extract_models_from_nautilus(
        engine, strategy_id=strategy_id, initial_capital=initial_capital
    )

    # Lấy số dư tài khoản cuối cùng
    from backend.nautilus import catalog as cat
    from nautilus_trader.model.currencies import USDT
    try:
        acct = engine.cache.account_for_venue(cat.VENUE_OKX)
        final_equity = acct.balance_total(USDT).as_double()
    except Exception:
        final_equity = float(equity_curve[-1]["equity"]) if equity_curve else initial_capital

    # Đảm bảo equity_curve có ít nhất 2 điểm mốc
    if not equity_curve:
        equity_curve = [
            {"time": start_ms, "equity": initial_capital, "equity_worst": initial_capital},
            {"time": end_ms, "equity": final_equity, "equity_worst": final_equity},
        ]
    else:
        # Chuẩn hóa format
        if equity_curve[0]["time"] > start_ms:
            equity_curve.insert(0, {"time": start_ms, "equity": initial_capital, "equity_worst": initial_capital})
        if equity_curve[-1]["time"] < end_ms:
            equity_curve.append({"time": end_ms, "equity": final_equity, "equity_worst": final_equity})

    # Thống kê theo từng symbol và strategy
    by_symbol: Dict[str, Dict[str, Any]] = {}
    by_strategy: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        agg = by_symbol.setdefault(p.symbol, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0})
        agg["pnl_usd"] += p.real_pnl
        agg["trades"] += 1
        if p.real_pnl > 0:
            agg["wins"] += 1
        agg["fees_usd"] += p.fees_usd

        s_agg = by_strategy.setdefault(p.strategy_id or strategy_id, {"pnl_usd": 0.0, "trades": 0})
        s_agg["pnl_usd"] += p.real_pnl
        s_agg["trades"] += 1

    return {
        "positions": positions,
        "orders": orders,
        "equity_curve": equity_curve,
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "balance": round(final_equity, 2),
        "rejected_for_capital": 0,
        "rejected_for_risk": 0,
        "risk_blocked_attempts": 0,
        "halted_at": None,
        "ruined_at": None,
        "skipped_no_vol": 0,
        "dca_layers_rejected": 0,
        "last_close": {},
        "open_positions": open_pos,
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
        "warnings": warns,
        "venue_rejects": [],
        "provenance": provenance(base_frame),
    }
