"""Dựng StrategyParams cho mỗi flow từ tham số quản lý vị thế — dùng chung cho Studio và WFA.

Phí/trượt giá mặc định theo loại sàn (manifest["venue"]) và thị trường — (taker, maker, trượt):
    CEX spot  : taker 0,10%, maker 0,10%, trượt 0,02%   (Binance spot VIP0, không BNB)
    CEX perp  : taker 0,05%, maker 0,02%, trượt 0,02%   (Binance USDT-M VIP0 — sàn testnet đã chọn)
    DEX spot  : phí pool 0,30% mọi lệnh, trượt 0,10%     (AMM: không có maker)
Taker áp cho lệnh market (vào ở open, SL, trailing, timeout, tín hiệu thoát); maker cho lệnh limit
(tầng DCA, chốt lời). DEX không có perp -> từ chối market="perp".
Người dùng có thể ghi đè fee_rate (taker) / maker_fee_rate / slippage_rate.
"""
from typing import Any, Dict, Optional, Tuple

from backend.core.params.schema import StrategyParams

POSITION_KEYS = (
    "market", "leverage", "max_open_trades", "stop_loss_rate", "take_profit_rate", "trailing_stop",
    "trailing_activation_pct", "timeout", "order_size_pct", "dca_step_pct", "dca_max_layers",
    "dca_size_multiplier", "maintenance_margin_rate", "fee_rate", "maker_fee_rate", "slippage_rate",
    "using_match_price", "stop_fill", "exit_unit", "atr_frame", "atr_period", "sizing", "risk_per_trade_pct",
    "max_notional_pct", "cooldown", "dca_steps", "dca_multipliers",
)

VENUE_COSTS = {  # (taker, maker, trượt giá)
    ("cex", "spot"): (0.0010, 0.0010, 0.0002),
    ("cex", "perp"): (0.0005, 0.0002, 0.0002),
    ("dex", "spot"): (0.0030, 0.0030, 0.0010),
}


def venue_of_symbol(symbol: str) -> str:
    from backend.db.local_pkl import read_manifest
    manifest = read_manifest(symbol) or {}
    venue = str(manifest.get("venue") or "").lower()
    return venue if venue in ("cex", "dex") else "dex"  # không rõ -> giả định bảo thủ (phí cao)


def resolve_costs(venue: str, market: str, fee_rate: Optional[float], slippage_rate: Optional[float],
                  maker_fee_rate: Optional[float] = None):
    """-> (taker, maker, trượt giá)."""
    key = (venue, market)
    if key not in VENUE_COSTS:
        raise ValueError(f"Không hỗ trợ market='{market}' trên venue='{venue}' (DEX hiện chỉ có spot).")
    taker, maker, slip = VENUE_COSTS[key]
    return (taker if fee_rate is None else float(fee_rate),
            maker if maker_fee_rate is None else float(maker_fee_rate),
            slip if slippage_rate is None else float(slippage_rate))


def data_symbol(symbol: str, market: str) -> Tuple[str, str]:
    """Ký hiệu dữ liệu thực dùng cho backtest: perp -> '<SYM>@perp' nếu có dữ liệu perp thật.

    Trả (symbol_dữ_liệu, nguồn_giá): 'perp' | 'spot_proxy' | 'spot'.
    """
    from backend.db.data_layout import resolve_asset_dir, split_instrument
    base, _ = split_instrument(symbol)
    if market != "perp":
        return base, "spot"
    perp = f"{base}@perp"
    return (perp, "perp") if resolve_asset_dir(perp) else (base, "spot_proxy")


def pool_fee_rate(symbol: Optional[str]) -> Optional[float]:
    """Phí pool DEX đã xác minh (manifest["pool_fee_rate"], đọc on-chain), nếu có."""
    if not symbol:
        return None
    from backend.db.local_pkl import read_manifest
    value = (read_manifest(symbol) or {}).get("pool_fee_rate")
    return float(value) if value is not None else None


def dca_budget_check(position: Dict[str, Any], venue_costs: Tuple[float, float, float]) -> Dict[str, Any]:
    """Kiểm tra mọi tầng DCA khai báo có vừa trần vốn (max_capital_usage) không — chỉ với sizing="margin_pct".

    Ký quỹ lệnh đầu = order_size_pct% vốn, tầng k = tầng k-1 × hệ số; PositionTracker bỏ âm thầm tầng nào làm
    ký quỹ + phí đã trả vượt vốn × max_capital_usage. need_pct = order_size_pct × (m0·(1+L·taker) + Σ m_k·(1+L·maker)),
    m0 = 1, m_k = tích luỹ hệ số; L = đòn bẩy (1 với spot). venue_costs = (taker, maker, trượt) đã resolve.
    -> {"ok", "need_pct", "cap_pct", "layers", "max_order_size_pct"} (max_order_size_pct = order_size lớn nhất còn vừa)."""
    taker, maker = float(venue_costs[0]), float(venue_costs[1])
    market = str(position.get("market") or "spot").lower()
    lev = 1.0 if market == "spot" else max(1.0, float(position.get("leverage") or 1.0))
    size = float(position.get("order_size_pct") if position.get("order_size_pct") is not None else 100.0)
    cap = 100.0 * float(position.get("max_capital_usage") if position.get("max_capital_usage") is not None else 1.0)
    cap = max(0.0, min(cap, 100.0))
    steps = [float(x) for x in (position.get("dca_steps") or [])]
    if not steps:
        n, step = int(position.get("dca_max_layers") or 0), float(position.get("dca_step_pct") or 0.0)
        steps = [step] * n if step > 0 else []
    layers = len(steps)
    result = {"ok": True, "need_pct": size, "cap_pct": cap, "layers": layers, "max_order_size_pct": size}
    if layers == 0 or str(position.get("sizing") or "margin_pct").lower() != "margin_pct":
        return result
    mults = [float(x) for x in (position.get("dca_multipliers") or [])] or \
            [float(position.get("dca_size_multiplier") or 1.0)] * layers
    if len(mults) < layers:
        mults += [mults[-1]] * (layers - len(mults))
    unit = 1.0 + lev * taker          # lệnh đầu (market, taker)
    m = 1.0
    for k in mults[:layers]:
        m *= k
        unit += m * (1.0 + lev * maker)   # tầng DCA (limit, maker)
    result["need_pct"] = size * unit
    result["max_order_size_pct"] = cap / unit
    result["ok"] = size * unit <= cap + 1e-9
    return result


def build_params(flow_name: str, flow_ast: Dict[str, Any], flow_type: str, position: Dict[str, Any],
                 venue: str, symbol: Optional[str] = None) -> StrategyParams:
    market = str(position.get("market") or "spot").lower()
    fee_override = position.get("fee_rate")
    maker_override = position.get("maker_fee_rate")
    if venue == "dex" and fee_override is None:  # DEX: dùng phí pool thật nếu manifest có
        pool_fee = pool_fee_rate(symbol)
        if pool_fee is not None:
            fee_override = pool_fee
            maker_override = pool_fee if maker_override is None else maker_override
    fee, maker, slip = resolve_costs(venue, market, fee_override, position.get("slippage_rate"), maker_override)
    leverage = float(position.get("leverage") or 1.0)
    if market == "spot" and leverage != 1.0:
        raise ValueError("Spot không dùng đòn bẩy — đặt leverage=1 hoặc market='perp'.")
    budget = dca_budget_check(position, (fee, maker, slip))
    if not budget["ok"]:
        raise ValueError(
            f"Flow '{flow_name}': ngân sách DCA không đủ — {budget['layers']} tầng nhồi (+ lệnh đầu) cần "
            f"{budget['need_pct']:.1f}% vốn (gồm phí) nhưng trần là {budget['cap_pct']:.1f}%; tầng cuối sẽ bị bỏ "
            f"âm thầm. Giảm order_size_pct xuống tối đa {budget['max_order_size_pct']:.2f}% (hoặc bớt tầng/hệ số).")
    return StrategyParams(
        name=flow_name,
        strategy="studio_ast",
        data_type="1m",
        using_match_price=bool(position.get("using_match_price", True)),
        max_open_trades=int(position.get("max_open_trades") or 45),
        volume_rate=1.0,
        leverage=leverage,
        fee_rate=fee,
        maker_fee_rate=maker,
        slippage_rate=slip,
        stop_loss_rate=float(position.get("stop_loss_rate") or 0.0),
        take_profit_rate=float(position.get("take_profit_rate") or 0.0),
        trailing_stop=float(position.get("trailing_stop") or 0.0),
        trailing_activation_pct=float(position.get("trailing_activation_pct") or 0.0),
        timeout=int(position.get("timeout") or 0),
        stop_fill=str(position.get("stop_fill") or "level"),
        cooldown=int(position.get("cooldown") or 0),
        exit_unit=str(position.get("exit_unit") or "pct"),
        atr_frame=str(position.get("atr_frame") or "1h"),
        atr_period=int(position.get("atr_period") or 14),
        sizing=str(position.get("sizing") or "margin_pct"),
        risk_per_trade_pct=float(position.get("risk_per_trade_pct") or 0.5),
        max_notional_pct=float(position.get("max_notional_pct") or 100.0),
        market=market,
        order_size_pct=float(position.get("order_size_pct") if position.get("order_size_pct") is not None else 100.0),
        dca_step_pct=float(position.get("dca_step_pct") or 0.0),
        dca_max_layers=int(position.get("dca_max_layers") or 0),
        dca_size_multiplier=float(position.get("dca_size_multiplier") or 1.0),
        # bước / hệ số riêng từng tầng (ghi đè dca_step_pct / dca_size_multiplier) — trước 04/10/2026 bị bỏ qua dù dca_budget_check có tính
        dca_steps=[float(x) for x in (position.get("dca_steps") or [])],
        dca_multipliers=[float(x) for x in (position.get("dca_multipliers") or [])],
        maintenance_margin_rate=float(position.get("maintenance_margin_rate") or 0.005),
        extra={"ast": {**flow_ast, "type": flow_type}, "type": flow_type},
    )
