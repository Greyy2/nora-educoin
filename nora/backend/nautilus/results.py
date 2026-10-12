"""MỘT bộ chuyển kết quả Nautilus -> hợp đồng dữ liệu Nora (cả đường DSL lẫn đường Strategy bản địa).

- `_payload(**fields)`: MỘT định nghĩa bộ khoá của kết quả một lần chạy (RUN_KEYS); thiếu / thừa khoá -> lỗi, nên hai đường không lệch hình dạng.
- `dsl_results(...)`: từ Coordinator + NoraSlotStrategy (đường DSL, `backtest.NautilusRun`).
- `native_results(...)`: từ cache Nautilus (đường Strategy do người dùng viết, `backtest.run_native`):
    * vị thế đóng = `cache.positions()` đã đóng + `cache.position_snapshots()` (NETTING chụp vị thế cũ khi mở lại cùng instrument);
    * lý do đóng / trạng thái lấy từ LỆNH ĐÓNG (tag ENTRY/SL/TP/TRAIL/EXIT/END... nếu chiến lược gắn, không thì theo loại lệnh), KHÔNG BAO GIỜ từ dấu của PnL;
    * trường không tính được từ cache = None (người dùng phải xử lý None): mae_pct, max_price, min_price, unit_pct, risk_usd.
- by_symbol / by_strategy: duy nhất `signal.compute.aggregate_positions`.
"""
from bisect import bisect_right
from typing import Any, Dict, List, Optional

import numpy as np

from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderStatus, OrderType as NtOrderType

from backend.alpha.plan import aggregate_positions
from backend.models.models import OrderModel, OrderType, PositionModel, PositionStatus, PositionType, next_id
from backend.nautilus import catalog as cat
from backend.nautilus.strategy import FLAT, REASONS

_NS_MS = 1_000_000
RUN_KEYS = ("positions", "orders", "equity_curve", "final_equity", "balance", "rejected_for_capital", "rejected_for_risk", "risk_blocked_attempts",
            "halted_at", "ruined_at", "skipped_no_vol", "dca_layers_rejected", "last_close", "open_positions", "warnings", "venue_rejects")


def _payload(**fields: Any) -> Dict[str, Any]:
    """Kết quả một lần chạy: đúng bộ khoá RUN_KEYS (đường DSL và bản địa cùng đi qua đây)."""
    if set(fields) != set(RUN_KEYS):
        raise KeyError(f"kết quả chạy lệch bộ khoá: thiếu {sorted(set(RUN_KEYS) - set(fields))}, thừa {sorted(set(fields) - set(RUN_KEYS))}")
    return fields


def portfolio_view(run: Dict[str, Any], initial_capital: float) -> Dict[str, Any]:
    """Kết quả một lần chạy -> dạng `PortfolioEngine.get_results()` (thêm by_strategy / by_symbol qua aggregate_positions)."""
    by_strategy, by_symbol = aggregate_positions(run["positions"])
    return {**run, "initial_capital": float(initial_capital), "by_strategy": by_strategy, "by_symbol": by_symbol, "funding_modeled": False, "funding_events": 0}


# ═══ Đường DSL ══════════════════════════════════════════════════════════════
def dsl_results(books: List[Dict[str, Any]], warnings: List[str], co: Any, slots: List[Any], ex: List[Dict[str, np.ndarray]]) -> Dict[str, Any]:
    last_close = {b["symbol"]: (float(ex[i]["c"][-1]) if len(ex[i]["t"]) else float("nan")) for i, b in enumerate(books)}
    opens = []
    for s in slots:
        if s.qty > 0 and s.st != FLAT:
            mark = last_close[s.symbol]
            opens.append({"symbol": s.symbol, "strategy": s.sid, "side": s.spec.pos_type.name, "qty": s.qty, "entry_price": s.avg,
                          "mark_price": mark, "notional": s.qty * mark, "unrealized_pnl": s.unrealized(mark), "opened": int(s.entry_time),
                          "margin_usd": s.margin_used, "leverage": s.pos_lev})
    warns = list(warnings)
    if co.venue_rejects:
        warns.append(f"{len(co.venue_rejects)} lệnh bị Nautilus từ chối (ví dụ {co.venue_rejects[0]})")
    return _payload(positions=co.positions, orders=co.orders, equity_curve=co.curve, final_equity=co.equity(), balance=co.balance(),
                    rejected_for_capital=co.rejected_for_capital, rejected_for_risk=co.rejected_for_risk, risk_blocked_attempts=co.risk_blocked_attempts,
                    halted_at=co.halted_at, ruined_at=co.ruined_at, skipped_no_vol=sum(s.skipped_no_vol for s in slots),
                    dca_layers_rejected=sum(s.dca_rejected for s in slots), last_close=last_close, open_positions=opens, warnings=warns,
                    venue_rejects=co.venue_rejects)


# ═══ Đường bản địa ══════════════════════════════════════════════════════════
_STOP_TYPES = (NtOrderType.STOP_MARKET, NtOrderType.STOP_LIMIT, NtOrderType.TRAILING_STOP_MARKET, NtOrderType.TRAILING_STOP_LIMIT)
_LIMIT_TYPES = (NtOrderType.LIMIT, NtOrderType.MARKET_IF_TOUCHED, NtOrderType.LIMIT_IF_TOUCHED)
_TAG_STATUS = {"TP": PositionStatus.TP, "SL": PositionStatus.SL, "TRAIL": PositionStatus.SL}   # tag khác (EXIT / TIMEOUT / END / KILL) -> CANCEL: đóng không qua SL/TP
_EXIT_TAGS = ("EXIT", "SL", "TP", "TRAIL", "TIMEOUT", "END", "KILL")


def close_label(order: Any) -> tuple:
    """(close_reason, PositionStatus) của vị thế từ LỆNH ĐÓNG: tag do chiến lược gắn nếu thuộc bộ tag của Nora, không thì theo loại lệnh. Không dùng PnL."""
    tag = order.tags[0] if order is not None and order.tags else None
    if tag in _EXIT_TAGS:
        return REASONS[tag], _TAG_STATUS.get(tag, PositionStatus.CANCEL)
    if order is not None and order.order_type in _STOP_TYPES:
        return "Lệnh dừng (stop order)", PositionStatus.SL
    if order is not None and order.order_type in _LIMIT_TYPES:
        return "Lệnh limit thoát (reduce-only)", PositionStatus.TP
    return "Exit (lệnh thị trường)", PositionStatus.CANCEL


def _label(iid: Any, labels: Dict[str, str]) -> str:
    return labels.get(str(iid), str(iid).split(".")[0])


def _closed_positions(cache: Any) -> List[Any]:
    out = [p for p in cache.position_snapshots() if p.is_closed] + [p for p in cache.positions() if p.is_closed]
    return sorted(out, key=lambda p: (p.ts_closed, p.ts_opened))


def _money(m: Any) -> float:
    return float(m.as_double())


def _position_model(p: Any, cache: Any, labels: Dict[str, str], strategy_id: str, lev: float, entry_equity: float) -> tuple:
    fills = list(p.events)                                            # OrderFilled của vị thế này, theo thứ tự
    entry = [e for e in fills if e.order_side == p.entry]
    exits = [e for e in fills if e.order_side != p.entry]
    reason, status = close_label(cache.order(p.closing_order_id) if p.closing_order_id is not None else None)
    net = _money(p.realized_pnl)                                      # đã trừ phí (như đường DSL)
    rid = next_id()
    avg_open = float(p.avg_px_open)

    def fee(es: List[Any]) -> float:
        return sum(_money(e.commission) for e in es)

    e0 = entry[0] if entry else None
    notional_all = sum(float(e.last_px) * float(e.last_qty) for e in entry)
    model = PositionModel(
        result_id=rid, account_id=0, campaign_id=0, symbol=_label(p.instrument_id, labels),
        pos_type=PositionType.LONG if p.entry == OrderSide.BUY else PositionType.SHORT, phase=0,
        enter_time=int(e0.ts_event // _NS_MS) if e0 else int(p.ts_opened // _NS_MS), enter_price=float(e0.last_px) if e0 else avg_open,
        close_time=int(p.ts_closed // _NS_MS), close_price=float(p.avg_px_close), status=status, real_pnl=net,
        profit_pct=net / entry_equity * 100.0 if entry_equity > 0 else None, flow="", start_reason="Lệnh vào của chiến lược Nautilus",
        close_reason=reason, max_price=None, min_price=None, qty=float(p.peak_qty), entry_equity=entry_equity,
        entry_margin_usd=float(e0.last_px) * float(e0.last_qty) / lev if e0 else None, entry_notional_usd=float(e0.last_px) * float(e0.last_qty) if e0 else None,
        entry_fee_usd=fee(entry[:1]), exit_fee_usd=fee(exits), layers=len(entry), avg_price=avg_open, total_margin_usd=notional_all / lev,
        mae_pct=None, fees_usd=fee(fills), funding_usd=0.0, unit_pct=None, leverage_used=lev, risk_usd=None, strategy_id=strategy_id)
    orders = [OrderModel(order_id=next_id(), account_id=0, position_id=rid, order_time=int(e.ts_event // _NS_MS),
                         order_type=OrderType.BUY if e.order_side == OrderSide.BUY else OrderType.SELL, order_price=float(e.last_px), qty=float(e.last_qty),
                         phase=0, fee_usd=_money(e.commission),
                         liquidity={LiquiditySide.MAKER: "maker", LiquiditySide.TAKER: "taker"}.get(e.liquidity_side, ""), slippage=0.0) for e in fills]
    return model, orders


def native_results(eng: Any, curve: List[Dict[str, float]], final: Optional[Dict[str, float]], last_bar: Dict[Any, Any], *, initial_capital: float, leverage: float,
                   strategy_id: str, labels: Dict[str, str], warnings: List[str]) -> Dict[str, Any]:
    """labels: str(InstrumentId) -> nhãn tài sản của người gọi. final: {"balance", "equity"} cuối kỳ (None khi không có nến). last_bar: InstrumentId -> Bar cuối."""
    cache = eng.cache
    closed = _closed_positions(cache)
    cum, run = [], float(initial_capital)
    for p in closed:
        run += _money(p.realized_pnl)
        cum.append(run)
    close_ts = [p.ts_closed for p in closed]
    positions: List[PositionModel] = []
    orders: List[OrderModel] = []
    for p in closed:
        k = bisect_right(close_ts, p.ts_opened - 1)                   # vốn đã chốt lúc mở = vốn đầu + Σ PnL các vị thế đóng TRƯỚC thời điểm mở
        eq_entry = float(initial_capital) if k == 0 else cum[k - 1]
        m, o = _position_model(p, cache, labels, strategy_id, leverage, eq_entry)
        positions.append(m)
        orders.extend(o)
    opens = []
    for p in cache.positions_open():
        b = last_bar.get(p.instrument_id)
        if b is None:
            continue
        mark = float(b.close)
        qty = float(p.quantity)
        opens.append({"symbol": _label(p.instrument_id, labels), "strategy": strategy_id, "side": "LONG" if p.is_long else "SHORT", "qty": qty,
                      "entry_price": float(p.avg_px_open), "mark_price": mark, "notional": qty * mark, "unrealized_pnl": _money(p.unrealized_pnl(b.close)),
                      "opened": int(p.ts_opened // _NS_MS), "margin_usd": qty * mark / leverage, "leverage": float(leverage)})
    rejects = []
    for o in cache.orders():
        if o.status in (OrderStatus.REJECTED, OrderStatus.DENIED):
            ev = o.last_event
            rejects.append((_label(o.instrument_id, labels), strategy_id, o.tags[0] if o.tags else o.type_string, str(getattr(ev, "reason", ""))))
    warns = list(warnings)
    if rejects:
        warns.append(f"{len(rejects)} lệnh bị Nautilus từ chối (ví dụ {rejects[0]})")
    if curve:
        ruined = next((int(c["time"]) for c in curve if c["equity"] <= 0.0), None)
    else:
        ruined = None
    last_close = {_label(iid, labels): float(b.close) for iid, b in last_bar.items()}
    acct = cache.account_for_venue(cat.VENUE_OKX)
    balance = final["balance"] if final else _money(acct.balance_total(USDT))
    return _payload(positions=positions, orders=orders, equity_curve=curve, final_equity=final["equity"] if final else float(initial_capital), balance=balance,
                    rejected_for_capital=len(rejects), rejected_for_risk=0, risk_blocked_attempts=0, halted_at=None, ruined_at=ruined,
                    skipped_no_vol=None, dca_layers_rejected=None, last_close=last_close, open_positions=opens, warnings=warns, venue_rejects=rejects)
