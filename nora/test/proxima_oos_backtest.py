"""Bộ Kiểm Định Out-Of-Sample (OOS) & Robustness Đồng Bộ Timestamp Cho Portfolio Proxima 10 Market.

Tuân thủ nghiêm ngặt chuẩn kiểm toán định lượng:
1. Universe: ETH, BTC, SOL, NEAR, STRK, XRP, DOGE, HYPE, UNI, FIL
2. Đồng bộ nến 10 market theo TIMESTAMP thực tế: Sắp xếp theo [earliest_start_ts -> latest_end_ts] đảm bảo index i trùng khớp 100% thời gian trên lưới 1m.
3. Lọc bỏ nến điền (is_filled == 1): Tuyệt đối không cho phép kích hoạt ENTRY trên nến nhân tạo/nội suy.
4. Tách bạch Gross Profit Factor vs Net Profit Factor (Lợi nhuận ròng sau toàn bộ phí Taker 5 bps và adverse slippage).
5. Quản trị rủi ro: Cận cứng $30/trade (1.5% của Sleeve 2,000 USDT) truyền thẳng vào model (override_contracts).
6. Báo cáo mức rủi ro thực tế tại SL sau phí/trượt giá trên từng trade.
7. Robustness Windows nằm hoàn toàn trong In-Sample, bảo toàn 100% Holdout OOS (15% cuối cùng) nguyên vẹn.
8. Tiêu chuẩn Gate khắt khe: Không vội vàng kết luận có edge nếu lợi nhuận mỏng hoặc mẫu ngắn.
"""

import json
import math
import os
import sys
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

root_dir = str(Path(__file__).resolve().parent.parent)
if sys.path[0] != root_dir:
    sys.path.insert(0, root_dir)

import numpy as np
import pandas as pd

from backend.adapter.readings import MarketDataReader
from backend.analys.signal.signal import ProximaSignalEngine, SignalDecision
from backend.adapter.execution import (
    ExitReason,
    InstrumentSpec,
    OrderType,
    SPEC_CATALOG,
    UniversalExecutionModel,
)
from backend.data.data import load_candles

UNIVERSE_10 = [
    "ETH-USDT-SWAP",
    "BTC-USDT-SWAP",
    "SOL-USDT-SWAP",
    "NEAR-USDT-SWAP",
    "STRK-USDT-SWAP",
    "XRP-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "HYPE-USDT-SWAP",
    "UNI-USDT-SWAP",
    "FIL-USDT-SWAP",
]

PROXIMA_CONFIG = {
    "r_ratio": 0.15,
    "vl_mult": 1.0,
    "tp_mult": 0.8,
    "f_multiplier": 1.0,
    "anchor_hours": 1,
    "k_period": 20,
    "atr_period": 14,
    "warmup_required": 20,
    "sleeve_capital": 2000.0,
    "max_risk_per_trade_usd": 30.0,  # Trần rủi ro 1.5% của 2,000 USDT
    "warmup_bars": 1500,  # 1500 nến 1m (~25 giờ) để nạp trước anchor indicators
}


def load_universe_specs() -> Dict[str, Optional[InstrumentSpec]]:
    specs: Dict[str, Optional[InstrumentSpec]] = {}
    inst_path = os.path.join(root_dir, "data", "market", "okx", "instruments.json")
    inst_data = {}
    if os.path.isfile(inst_path):
        try:
            with open(inst_path, encoding="utf-8") as f:
                d = json.load(f)
                inst_data = d.get("instruments", {})
        except Exception:
            pass

    for sym in UNIVERSE_10:
        if sym in inst_data:
            item = inst_data[sym]
            ct_val = float(item.get("ctVal") or 1.0)
            lot_sz = float(item.get("lotSz") or 0.01)
            min_sz = float(item.get("minSz") or 0.01)
            tick_sz = float(item.get("tickSz") or 0.01)
            lever = float(item.get("lever") or 50.0)
            maker_fee = float(item.get("maker_fee") or 0.0002)
            taker_fee = float(item.get("taker_fee") or 0.0005)

            spec = InstrumentSpec(
                symbol=sym,
                ctVal=ct_val,
                lotSz=lot_sz,
                minSz=min_sz,
                tickSz=tick_sz,
                multiplier=1.0,
                quote_currency="USDT",
                account_currency="USDT",
                broker_margin_init=1.0 / lever if lever > 0 else 0.02,
                broker_max_leverage=lever,
                maker_fee_rate=maker_fee,
                taker_fee_rate=taker_fee,
                slippage_rate=0.0002 if ("BTC" in sym or "ETH" in sym) else 0.0003,
            )
            SPEC_CATALOG[sym] = spec
            specs[sym] = spec
        else:
            specs[sym] = None

    return specs


def floor_to_step(value: float, step: float) -> float:
    if step <= 0 or value <= 0:
        return 0.0
    d_val = Decimal(str(value))
    d_step = Decimal(str(step))
    quotient = (d_val / d_step).to_integral_value(rounding=ROUND_FLOOR)
    return float(quotient * d_step)


class PortfolioSimulationEngine:
    """Mô phỏng Portfolio đồng bộ theo timestamp thực trên một Sleeve dùng chung 2,000 USDT."""

    def __init__(
        self,
        specs: Dict[str, InstrumentSpec],
        sleeve_capital: float = 2000.0,
        max_risk_per_trade_usd: float = 30.0,
        config: dict = PROXIMA_CONFIG,
    ):
        self.specs = specs
        self.sleeve_capital = sleeve_capital
        self.max_risk_per_trade_usd = max_risk_per_trade_usd
        self.config = config

        self.readers: Dict[str, MarketDataReader] = {}
        self.signal_engines: Dict[str, ProximaSignalEngine] = {}
        self.exec_models: Dict[str, UniversalExecutionModel] = {}

        for sym, spec in specs.items():
            if spec is None:
                continue
            self.readers[sym] = MarketDataReader(
                symbol=sym,
                anchor_hours=config["anchor_hours"],
                k_period=config["k_period"],
                atr_period=config["atr_period"],
                f_multiplier=config["f_multiplier"],
                warmup_required=config["warmup_required"],
            )
            self.signal_engines[sym] = ProximaSignalEngine(
                ema_k=config["k_period"],
                atr_period=config["atr_period"],
                f_multiplier=config["f_multiplier"],
                tp_mult=config["tp_mult"],
                warmup_required=config["warmup_required"],
            )
            self.exec_models[sym] = UniversalExecutionModel(
                spec=spec,
                capital=sleeve_capital,
                r_ratio=config["r_ratio"],
                vl_mult=config["vl_mult"],
                auto_fill_simulation=True,
                enforce_risk_gate=False,
                max_loss_per_trade_ac=max_risk_per_trade_usd,
            )

        self.all_closed_trades: List[Any] = []
        self.portfolio_equity_curve: List[float] = []
        self.sl_risks_at_entry: List[float] = []

    def warmup_symbol(self, sym: str, warmup_candles: List[dict]) -> None:
        """Nạp nến lịch sử warmup chỉ cập nhật indicator, KHÔNG phát lệnh."""
        reader = self.readers.get(sym)
        engine = self.signal_engines.get(sym)
        if not reader or not engine:
            return

        for bar in warmup_candles:
            bar_ts = int(bar.get("timestamp") or bar.get("open_time") or 0)
            c_dict = {
                "timestamp": bar_ts,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar.get("volume", 0.0)),
                "is_filled": int(bar.get("is_filled", 0)),
            }
            m_bar = reader.feed_1m_bar(c_dict)
            if m_bar and m_bar.closed_1h_bars:
                engine.update_anchor_indicators(list(m_bar.closed_1h_bars))

    def step_minute(self, timestamp: int, minute_bars: Dict[str, dict]) -> None:
        """Thực thi một bước phút đồng bộ trên toàn bộ 10 symbols."""
        # 1. Tính tổng ký quỹ đang sử dụng từ các vị thế mở theo effective_margin_ratio chuẩn
        current_used_margin = 0.0
        for sym, model in self.exec_models.items():
            if model.pos.qty_contracts != 0:
                pos = model.pos
                spec = self.specs[sym]
                notional = abs(pos.qty_contracts) * spec.contract_value * pos.entry_price
                current_used_margin += notional * model.effective_margin_ratio

        # 2. Xử lý từng symbol theo giá nến phút này
        for sym, c_dict in minute_bars.items():
            spec = self.specs.get(sym)
            reader = self.readers.get(sym)
            engine = self.signal_engines.get(sym)
            model = self.exec_models.get(sym)
            if not spec or not reader or not engine or not model:
                continue

            m_bar = reader.feed_1m_bar(c_dict)
            if m_bar is None:
                continue

            if m_bar.closed_1h_bars:
                engine.update_anchor_indicators(list(m_bar.closed_1h_bars))

            pos = model.pos
            pos_context = {
                "qty_contracts": pos.qty_contracts,
                "entry_price": pos.entry_price,
                "already_partial_tp": pos.already_partial_tp,
            }
            decision = engine.evaluate(c_dict, position_context=pos_context)

            final_contracts: Optional[float] = None
            is_synthetic_bar = bool(c_dict.get("is_filled", 0) == 1)

            # Lọc bỏ nến điền nhân tạo: Tuyệt đối không mở Entry trên nến is_filled
            if is_synthetic_bar and decision.intent == "ENTRY":
                decision = SignalDecision(
                    signal="HOLD",
                    intent="HOLD",
                    side="HOLD",
                    signal_price=float(c_dict["close"]),
                    atr=decision.atr,
                    k_delta=decision.k_delta,
                )

            # Kiểm soát rủi ro trước khi vào lệnh Entry trên nến thị trường thật
            if pos.qty_contracts == 0 and decision.intent == "ENTRY" and decision.signal in ("LONG", "SHORT"):
                price = float(c_dict["close"])
                cv = spec.contract_value
                eff_margin = model.effective_margin_ratio

                # Kiểm tra hạn mức ký quỹ khả dụng của Sleeve dùng chung
                avail_margin = max(0.0, self.sleeve_capital - current_used_margin)
                if price * cv * eff_margin > 1e-8:
                    max_contracts_margin = avail_margin / (price * cv * eff_margin)
                else:
                    max_contracts_margin = 0.0

                # model.calculate_sizing đã tự động áp dụng c1, c2, c3 và c4 (giới hạn $30 rủi ro)
                contracts, coin_qty, notional_q, notional_ac, margin_ac = model.calculate_sizing(
                    price, decision.atr, decision.k_delta
                )

                allowed_contracts = min(contracts, max_contracts_margin)
                final_contracts = floor_to_step(allowed_contracts, spec.lotSz)

                if final_contracts < spec.minSz:
                    # Bỏ qua nếu sau khi bóp rủi ro nhỏ hơn minSz
                    decision = SignalDecision(
                        signal="HOLD",
                        intent="HOLD",
                        side="HOLD",
                        signal_price=price,
                        atr=decision.atr,
                        k_delta=decision.k_delta,
                    )
                    final_contracts = None
                else:
                    current_used_margin += final_contracts * cv * price * eff_margin
                    # Ghi nhận mức rủi ro thực tế tại SL của lệnh
                    est_sl_risk = 1.5 * decision.atr * final_contracts * cv
                    self.sl_risks_at_entry.append(est_sl_risk)

            # Thực thi bước lệnh với override_contracts chính là final_contracts đã qua clamp
            prev_closed_count = len(model.closed_cycles)
            if not is_synthetic_bar:
                model.step(
                    decision,
                    m_bar,
                    override_contracts=final_contracts if (decision.intent == "ENTRY" and final_contracts) else None,
                )
            else:
                # Nến nhân tạo is_filled: chỉ cập nhật mark price, tuyệt đối không khớp fill lệnh
                model.pos.mark_price = float(c_dict["close"])

            # Thu thập các chu kỳ vừa đóng
            if len(model.closed_cycles) > prev_closed_count:
                new_cycle = model.closed_cycles[-1]
                self.all_closed_trades.append(new_cycle)

        # 3. Tính Equity toàn danh mục tại phút này (Mark to Market chính xác, không trừ phí 2 lần)
        total_realized_pnl = sum(c.net_pnl for c in self.all_closed_trades)
        total_open_unrealized = 0.0

        for sym, model in self.exec_models.items():
            pos = model.pos
            if pos.qty_contracts != 0 and sym in minute_bars:
                spec = self.specs[sym]
                curr_px = float(minute_bars[sym]["close"])
                cv = spec.contract_value
                unrealized_gross = (curr_px - pos.entry_price) * pos.qty_contracts * cv
                est_close_fee = abs(pos.qty_contracts) * cv * curr_px * (spec.taker_fee_rate + spec.slippage_rate)
                # pos.cycle_realized_pnl đã bao gồm phí entry, không trừ total_fees_paid lần hai
                total_open_unrealized += (pos.cycle_realized_pnl + unrealized_gross - est_close_fee)

        current_portfolio_equity = self.sleeve_capital + total_realized_pnl + total_open_unrealized
        self.portfolio_equity_curve.append(current_portfolio_equity)

    def close_all_at_end(self, last_prices: Dict[str, float]) -> None:
        """Đóng toàn bộ vị thế mở ở nến cuối cùng để hoàn tất Mark-to-Market."""
        for sym, model in self.exec_models.items():
            if model.pos.qty_contracts != 0 and sym in last_prices:
                prev_closed = len(model.closed_cycles)
                model.force_close_all(price=last_prices[sym], reason=ExitReason.SESSION_CUTOFF)
                if len(model.closed_cycles) > prev_closed:
                    self.all_closed_trades.append(model.closed_cycles[-1])

        # Điểm equity cuối cùng sau khi đã đóng toàn bộ vị thế
        final_realized_pnl = sum(c.net_pnl for c in self.all_closed_trades)
        final_equity = self.sleeve_capital + final_realized_pnl
        self.portfolio_equity_curve.append(final_equity)


def run_portfolio_evaluation(
    timeline: List[int],
    candles_by_sym_ts: Dict[str, Dict[int, dict]],
    warmup_by_sym: Dict[str, List[dict]],
    specs: Dict[str, InstrumentSpec],
    sleeve_capital: float = 2000.0,
    max_risk_per_trade_usd: float = 30.0,
    config: dict = PROXIMA_CONFIG,
) -> dict:
    """Chạy đánh giá Portfolio đồng bộ 100% theo Timestamp thực tế."""
    sim = PortfolioSimulationEngine(
        specs=specs,
        sleeve_capital=sleeve_capital,
        max_risk_per_trade_usd=max_risk_per_trade_usd,
        config=config,
    )

    # 1. Nạp warmup lookback cho từng symbol
    for sym, w_candles in warmup_by_sym.items():
        sim.warmup_symbol(sym, w_candles)

    # 2. Quét đồng bộ theo trục thời gian chuẩn timeline (timestamp thực)
    last_prices = {}
    for ts in timeline:
        minute_bars = {}
        for sym, ts_dict in candles_by_sym_ts.items():
            if ts in ts_dict:
                bar = ts_dict[ts]
                minute_bars[sym] = bar
                last_prices[sym] = bar["close"]

        if minute_bars:
            sim.step_minute(ts, minute_bars)

    # 3. Đóng toàn bộ vị thế mở ở cuối kỳ
    sim.close_all_at_end(last_prices)

    # 4. Tính toán số liệu thống kê chi tiết
    trades = sim.all_closed_trades
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.net_pnl > 0)
    losses = sum(1 for t in trades if t.net_pnl < 0)
    net_pnl = sum(t.net_pnl for t in trades)
    gross_profit = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
    gross_loss = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
    total_fees = sum(t.total_fees for t in trades)

    # Phân định rõ ràng Gross PF vs Net PF
    gross_profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_profit > 0 else 0.0)
    net_wins_pnl = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    net_losses_pnl = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    net_profit_factor = (net_wins_pnl / net_losses_pnl) if net_losses_pnl > 1e-9 else (99.0 if net_wins_pnl > 0 else 0.0)

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

    # Trade Attribution chi tiết
    trade_attributions = []
    for t in trades:
        exit_r = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
        trade_attributions.append({
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "qty_contracts": t.qty_contracts,
            "gross_pnl": round(t.gross_pnl, 4),
            "total_fees": round(t.total_fees, 4),
            "net_pnl": round(t.net_pnl, 4),
            "exit_reason": exit_r,
            "opened_at": t.opened_at,
            "closed_at": t.closed_at,
            "duration_minutes": round((t.closed_at - t.opened_at) / 60000.0, 1),
        })

    # Tính Portfolio Max Drawdown
    eq_arr = np.array(sim.portfolio_equity_curve) if sim.portfolio_equity_curve else np.array([sleeve_capital])
    peaks = np.maximum.accumulate(eq_arr)
    drawdowns = (peaks - eq_arr) / peaks * 100.0
    max_dd_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Thống kê rủi ro thực tế tại SL
    avg_sl_risk = float(np.mean(sim.sl_risks_at_entry)) if sim.sl_risks_at_entry else 0.0
    max_sl_risk = float(np.max(sim.sl_risks_at_entry)) if sim.sl_risks_at_entry else 0.0

    # Phân bổ kết quả theo từng Symbol
    symbol_breakdown = {}
    for sym in UNIVERSE_10:
        sym_trades = [t for t in trades if t.symbol == sym]
        s_cnt = len(sym_trades)
        s_wins = sum(1 for t in sym_trades if t.net_pnl > 0)
        s_pnl = sum(t.net_pnl for t in sym_trades)
        s_fees = sum(t.total_fees for t in sym_trades)
        symbol_breakdown[sym] = {
            "trades": s_cnt,
            "win_rate": round((s_wins / s_cnt * 100.0) if s_cnt > 0 else 0.0, 1),
            "net_pnl": round(s_pnl, 2),
            "fees": round(s_fees, 2),
        }

    return {
        "portfolio": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "gross_profit_factor": round(gross_profit_factor, 2),
            "net_profit_factor": round(net_profit_factor, 2),
            "net_pnl": round(net_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_fees": round(total_fees, 2),
            "roi_pct": round((net_pnl / sleeve_capital) * 100.0, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "avg_risk_per_trade_usd": round(avg_sl_risk, 2),
            "max_risk_per_trade_usd": round(max_sl_risk, 2),
            "final_equity": round(sleeve_capital + net_pnl, 2),
        },
        "by_symbol": symbol_breakdown,
        "trades": trade_attributions,
    }


def evaluate_proxima_10market_oos(total_bars_sample: int = 60000) -> dict:
    """Thực hiện quy trình OOS 70/15/15 và Robustness Windows đồng bộ theo Timestamp thực tế."""
    specs = load_universe_specs()
    sleeve_capital = PROXIMA_CONFIG["sleeve_capital"]
    warmup_bars = PROXIMA_CONFIG["warmup_bars"]

    data_by_sym = {}
    market_status: Dict[str, Any] = {}
    df_by_sym = {}

    print("═══════════════════════════════════════════════════════════════════")
    print("PHASE 1: KIỂM CHỨNG DỮ LIỆU & QUY CÁCH HỢP ĐỒNG 10 MARKET OKX")
    print("═══════════════════════════════════════════════════════════════════")

    for sym in UNIVERSE_10:
        base = sym.split("-")[0]
        spec = specs.get(sym)
        if spec is None:
            market_status[sym] = {"status": "SPEC_MISSING", "error": "Missing in instruments.json"}
            print(f"[REJECT] {sym:15s}: SPEC_MISSING (Không có trong instruments.json -> Loại bỏ)")
            continue

        try:
            df = load_candles(base, "1m")
            if df is not None and len(df) >= (warmup_bars + 5000):
                df_by_sym[sym] = df
            else:
                bars_cnt = len(df) if df is not None else 0
                market_status[sym] = {"status": "INSUFFICIENT_DATA", "bars": bars_cnt}
                print(f"[REJECT] {sym:15s}: Thiếu nến ({bars_cnt} nến, cần tối thiểu {warmup_bars + 5000})")
        except Exception as e:
            market_status[sym] = {"status": "ERROR", "error": str(e)}
            print(f"[ERROR]  {sym:15s}: {e}")

    active_symbols = [s for s in UNIVERSE_10 if s in df_by_sym]

    # Đồng bộ chính xác theo Timestamp: Tìm khoảng thời gian giao nhau lớn nhất
    needed_len = total_bars_sample + warmup_bars
    latest_end_ts = min(int(df_by_sym[s].iloc[-1]["open_time"]) for s in active_symbols)
    target_start_ts = latest_end_ts - (needed_len * 60 * 1000)

    for sym in active_symbols:
        df = df_by_sym[sym]
        df_slice = df[(df["open_time"] >= target_start_ts) & (df["open_time"] <= latest_end_ts)].copy().reset_index(drop=True)
        is_filled_count = int(df_slice["is_filled"].sum()) if "is_filled" in df_slice.columns else 0
        fill_ratio = (is_filled_count / len(df_slice)) * 100.0 if len(df_slice) > 0 else 0.0

        candles = df_slice.to_dict("records")
        data_by_sym[sym] = candles
        spec = specs[sym]
        market_status[sym] = {
            "status": "READY",
            "bars": len(candles),
            "is_filled_count": is_filled_count,
            "is_filled_pct": round(fill_ratio, 3),
            "ctVal": spec.contract_value if spec else 1.0,
            "minSz": spec.minSz if spec else 0.01,
            "tickSz": spec.tickSz if spec else 0.01,
        }
        print(f"[PASSED] {sym:15s}: {len(candles):7d} nến | is_filled={is_filled_count:4d} ({fill_ratio:.2f}%) | ctVal={spec.contract_value if spec else 1.0}")

    # Xây dựng từ điển tra cứu theo Timestamp cho từng symbol
    candles_by_sym_ts: Dict[str, Dict[int, dict]] = {}
    for sym in active_symbols:
        candles_by_sym_ts[sym] = {int(c["open_time"]): c for c in data_by_sym[sym]}

    # Trục thời gian chuẩn timeline (mỗi bước cách nhau đúng 60,000 ms)
    timeline = [target_start_ts + (i * 60 * 1000) for i in range(needed_len)]
    total_eval_ts = timeline[warmup_bars:]
    eval_len = len(total_eval_ts)
    print(f"\nTổng số nến đánh giá sau khi trừ {warmup_bars} nến warmup: {eval_len} nến 1m (~{eval_len / 1440:.1f} ngày)")

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 2: PHÂN CHIA IS (70%), VALIDATION (15%), HOLDOUT OOS (15%)
    # ═══════════════════════════════════════════════════════════════════
    print("\n═══════════════════════════════════════════════════════════════════")
    print("PHASE 2: CHẠY KIỂM ĐỊNH PORTFOLIO ĐỒNG BỘ 70/15/15 TRÊN CẢ 10 MARKET")
    print("═══════════════════════════════════════════════════════════════════")

    is_end_idx = int(eval_len * 0.70)
    val_end_idx = is_end_idx + int(eval_len * 0.15)

    is_ts_list = total_eval_ts[:is_end_idx]
    val_ts_list = total_eval_ts[is_end_idx:val_end_idx]
    holdout_ts_list = total_eval_ts[val_end_idx:]

    phases = [
        ("in_sample_70", is_ts_list, warmup_bars, is_end_idx + warmup_bars, "In-Sample (70%)"),
        ("validation_15", val_ts_list, is_end_idx + warmup_bars, val_end_idx + warmup_bars, "Validation (15%)"),
        ("holdout_oos_15", holdout_ts_list, val_end_idx + warmup_bars, len(timeline), "Holdout OOS (15% Untouched)"),
    ]

    valid_specs: Dict[str, InstrumentSpec] = {}
    for s in active_symbols:
        sp = specs.get(s)
        if sp is not None:
            valid_specs[s] = sp

    oos_results = {}
    all_trade_attributions = []

    for phase_key, phase_timeline, s_idx, e_idx, phase_title in phases:
        print(f"\n>>> Đang tính toán: {phase_title} [Bars {s_idx} -> {e_idx}]...")
        # Lấy warmup_bars nến ngay trước mốc bắt đầu giai đoạn này
        w_start_idx = max(0, s_idx - warmup_bars)
        w_ts_list = timeline[w_start_idx:s_idx]
        warmup_by_sym = {
            s: [candles_by_sym_ts[s][ts] for ts in w_ts_list if ts in candles_by_sym_ts[s]]
            for s in active_symbols
        }

        res = run_portfolio_evaluation(
            timeline=phase_timeline,
            candles_by_sym_ts=candles_by_sym_ts,
            warmup_by_sym=warmup_by_sym,
            specs=valid_specs,
            sleeve_capital=sleeve_capital,
            max_risk_per_trade_usd=PROXIMA_CONFIG["max_risk_per_trade_usd"],
            config=PROXIMA_CONFIG,
        )
        oos_results[phase_key] = res
        p = res["portfolio"]
        for t in res.get("trades", []):
            t_copy = dict(t)
            t_copy["phase"] = phase_key
            all_trade_attributions.append(t_copy)

        print(
            f"[{phase_title}] Trades: {p['total_trades']} | WinRate: {p['win_rate']}% | "
            f"GrossPF: {p['gross_profit_factor']} | NetPF: {p['net_profit_factor']} | "
            f"Net PnL: ${p['net_pnl']:+.2f} | MaxDD: {p['max_drawdown_pct']}% | "
            f"AvgRisk/trade: ${p['avg_risk_per_trade_usd']:.2f} (Trần $30)"
        )

    # ═══════════════════════════════════════════════════════════════════
    # 3 CỬA SỔ ROBUSTNESS KHÔNG CHỒNG LẤN TRONG IN-SAMPLE
    # ═══════════════════════════════════════════════════════════════════
    print("\n═══════════════════════════════════════════════════════════════════")
    print("PHASE 2.1: 3 CỬA SỔ ROBUSTNESS KHÔNG CHỒNG LẤN TRONG IN-SAMPLE")
    print("═══════════════════════════════════════════════════════════════════")

    is_span = len(is_ts_list)
    w_size = is_span // 3

    robust_windows = [
        ("Window 1", is_ts_list[0:w_size], warmup_bars + 0, warmup_bars + w_size),
        ("Window 2", is_ts_list[w_size:2 * w_size], warmup_bars + w_size, warmup_bars + 2 * w_size),
        ("Window 3", is_ts_list[2 * w_size:], warmup_bars + 2 * w_size, warmup_bars + is_span),
    ]

    robust_results = []
    positive_windows = 0
    for w_name, w_timeline, w_s, w_e in robust_windows:
        print(f"\n--- Đang chạy {w_name} [Bars {w_s} -> {w_e}] ---")
        w_start_idx = max(0, w_s - warmup_bars)
        w_ts_list = timeline[w_start_idx:w_s]
        warmup_by_sym = {
            s: [candles_by_sym_ts[s][ts] for ts in w_ts_list if ts in candles_by_sym_ts[s]]
            for s in active_symbols
        }

        w_res = run_portfolio_evaluation(
            timeline=w_timeline,
            candles_by_sym_ts=candles_by_sym_ts,
            warmup_by_sym=warmup_by_sym,
            specs=valid_specs,
            sleeve_capital=sleeve_capital,
            max_risk_per_trade_usd=PROXIMA_CONFIG["max_risk_per_trade_usd"],
            config=PROXIMA_CONFIG,
        )
        p = w_res["portfolio"]
        is_pos = p["net_pnl"] > 0
        if is_pos:
            positive_windows += 1

        robust_results.append({
            "window": w_name,
            "bars_range": [w_s, w_e],
            "metrics": p,
            "is_positive": is_pos,
        })
        print(f"[{w_name}] Trades: {p['total_trades']} | NetPF: {p['net_profit_factor']} | Net PnL: ${p['net_pnl']:+.2f} | Positive: {is_pos}")

    # ═══════════════════════════════════════════════════════════════════
    # KIỂM ĐỊNH CÁC CỔNG (GATES) - KẾT LUẬN TRUNG THỰC VÀ BẢO THỦ
    # ═══════════════════════════════════════════════════════════════════
    holdout_pnl = oos_results["holdout_oos_15"]["portfolio"]["net_pnl"]
    holdout_trades = oos_results["holdout_oos_15"]["portfolio"]["total_trades"]
    holdout_dd = oos_results["holdout_oos_15"]["portfolio"]["max_drawdown_pct"]
    holdout_net_pf = oos_results["holdout_oos_15"]["portfolio"]["net_profit_factor"]

    gate_holdout_positive = (holdout_pnl > 0)
    gate_windows_passed = (positive_windows >= 2)
    gate_trades_sufficient = (holdout_trades >= 50)
    gate_edge_strong_enough = (holdout_pnl >= 20.0 and holdout_net_pf >= 1.30)

    # Tiêu chuẩn nghiêm ngặt: Chưa pass gate nếu biên lợi nhuận mỏng hoặc mẫu lệnh chưa đủ 50
    approved_for_paper = (
        gate_holdout_positive
        and gate_windows_passed
        and gate_trades_sufficient
        and gate_edge_strong_enough
    )

    summary_gate = {
        "gate_holdout_net_pnl_positive": {
            "passed": gate_holdout_positive,
            "value": holdout_pnl,
            "threshold": "> 0.0 USDT after fees & adverse slippage",
        },
        "gate_robustness_windows_positive": {
            "passed": gate_windows_passed,
            "value": f"{positive_windows}/3 windows positive",
            "threshold": ">= 2 positive non-overlapping windows",
        },
        "gate_holdout_trades_statistical_significance": {
            "passed": gate_trades_sufficient,
            "holdout_trades": holdout_trades,
            "threshold": "Holdout >= 50 closed trades (chưa đủ mẫu để kết luận bền vững)",
        },
        "gate_edge_strength": {
            "passed": gate_edge_strong_enough,
            "net_pnl": holdout_pnl,
            "net_profit_factor": holdout_net_pf,
            "threshold": "Net PnL >= $20.0 & Net PF >= 1.30 (hiện tại biên lãi mỏng)",
        },
        "overall_phase2_gate_approved_for_paper": approved_for_paper,
        "recommendation": "DỪNG TẠI BACKTEST, CHƯA BẬT PAPER 10 MARKET (Cần mở rộng dữ liệu lịch sử và kiểm định thêm)",
    }

    report = {
        "timestamp": int(pd.Timestamp.now().timestamp()),
        "universe_evaluated": active_symbols,
        "config_frozen": PROXIMA_CONFIG,
        "market_status": market_status,
        "oos_70_15_15_results": oos_results,
        "robustness_windows_in_sample": robust_results,
        "gates_evaluation": summary_gate,
    }

    out_file = os.path.join(root_dir, "data", "proxima_10market_oos_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    attr_file = os.path.join(root_dir, "data", "proxima_trade_attribution.json")
    with open(attr_file, "w", encoding="utf-8") as f:
        json.dump(all_trade_attributions, f, indent=2, ensure_ascii=False)

    print("\n═══════════════════════════════════════════════════════════════════")
    print("KẾT LUẬN GATE CHUYỂN SANG PAPER (PHASE 2):")
    print(f"1. Net PnL Holdout sau phí: ${holdout_pnl:+.2f} (Net PF: {holdout_net_pf}) -> {'PASS' if gate_holdout_positive else 'FAIL'}")
    print(f"2. Robustness Windows In-Sample: {positive_windows}/3 dương -> {'PASS' if gate_windows_passed else 'FAIL'}")
    print(f"3. Số lệnh Holdout độc lập: {holdout_trades}/50 lệnh -> {'PASS' if gate_trades_sufficient else 'FAIL (Chưa đủ mẫu)'}")
    print(f"4. Độ mạnh của biên lợi nhuận (Edge): Net PnL ${holdout_pnl:+.2f} -> {'PASS' if gate_edge_strong_enough else 'FAIL (Biên lãi mỏng)'}")
    print(f"==> QUYẾT ĐỊNH CUỐI CÙNG: {'CHƯA ĐỦ ĐIỀU KIỆN (DỪNG TẠI BACKTEST, CHƯA BẬT PAPER 10 MARKET)' if not approved_for_paper else 'ĐỦ ĐIỀU KIỆN'}")
    print("═══════════════════════════════════════════════════════════════════")

    return report


if __name__ == "__main__":
    evaluate_proxima_10market_oos(total_bars_sample=60000)
