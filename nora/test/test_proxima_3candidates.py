"""Kiểm Định So Sánh 3 Ứng Viên Giả Thuyết Proxima Trên 10 Market OKX (Phase 2 & Phase 3).

Universe: ETH, BTC, SOL, NEAR, STRK, XRP, DOGE, HYPE, UNI, FIL
Sleeve Capital: 1,000 USDT / bot (tuân thủ Phase 4 Master Capital Allocation)
Cơ chế mô phỏng: Đồng bộ 100% Timestamp, cách ly nến is_filled, tính Net PnL & Net PF chuẩn.

3 Ứng Viên Độc Lập:
1. Candidate 1 (Baseline Breakout): F=1.0, tp_mult=0.8, anchor=1h, standard exit machine.
2. Candidate 2 (Volatility Confirmed): F=1.25 (yêu cầu breakout dứt khoát hơn để lọc false breakouts trong vùng sideway).
3. Candidate 3 (Trailing Breakeven & Realistic TP): Dời SL về Breakeven khi lãi đạt 1.0 ATR, TP tại 1.5 ATR.
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


class CandidateSimulationEngine:
    """Mô phỏng Portfolio cho một cấu hình ứng viên cụ thể."""

    def __init__(
        self,
        candidate_name: str,
        specs: Dict[str, InstrumentSpec],
        sleeve_capital: float = 1000.0,
        max_risk_per_trade_usd: float = 15.0,  # 1.5% của 1,000 USDT
        candidate_config: dict = None,
    ):
        self.candidate_name = candidate_name
        self.specs = specs
        self.sleeve_capital = sleeve_capital
        self.max_risk_per_trade_usd = max_risk_per_trade_usd
        self.cfg = candidate_config or {}

        self.f_multiplier = float(self.cfg.get("f_multiplier", 1.0))
        self.tp_mult = float(self.cfg.get("tp_mult", 0.8))
        self.r_ratio = float(self.cfg.get("r_ratio", 0.15))
        self.vl_mult = float(self.cfg.get("vl_mult", 1.0))
        self.mode = str(self.cfg.get("mode", "baseline"))

        self.readers: Dict[str, MarketDataReader] = {}
        self.signal_engines: Dict[str, ProximaSignalEngine] = {}
        self.exec_models: Dict[str, UniversalExecutionModel] = {}
        self.max_profit_reached: Dict[str, float] = {}

        for sym, spec in specs.items():
            if spec is None:
                continue
            self.readers[sym] = MarketDataReader(
                symbol=sym,
                anchor_hours=1,
                k_period=20,
                atr_period=14,
                f_multiplier=self.f_multiplier,
                warmup_required=20,
            )
            self.signal_engines[sym] = ProximaSignalEngine(
                ema_k=20,
                atr_period=14,
                f_multiplier=self.f_multiplier,
                tp_mult=self.tp_mult,
                warmup_required=20,
            )
            self.exec_models[sym] = UniversalExecutionModel(
                spec=spec,
                capital=sleeve_capital,
                r_ratio=self.r_ratio,
                vl_mult=self.vl_mult,
                auto_fill_simulation=True,
                enforce_risk_gate=False,
                max_loss_per_trade_ac=max_risk_per_trade_usd,
            )
            self.max_profit_reached[sym] = 0.0

        self.all_closed_trades: List[Any] = []
        self.portfolio_equity_curve: List[float] = []
        self.sl_risks_at_entry: List[float] = []

    def warmup_symbol(self, sym: str, warmup_candles: List[dict]) -> None:
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
        current_used_margin = 0.0
        for sym, model in self.exec_models.items():
            if model.pos.qty_contracts != 0:
                pos = model.pos
                spec = self.specs[sym]
                notional = abs(pos.qty_contracts) * spec.contract_value * pos.entry_price
                current_used_margin += notional * model.effective_margin_ratio

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

            # Ứng viên 3: Trailing Breakeven & Realistic TP
            if self.mode == "breakeven_dynamic" and pos.qty_contracts != 0 and decision.atr:
                is_long = pos.qty_contracts > 0
                curr_px = float(c_dict["close"])
                gain_dist = (curr_px - pos.entry_price) if is_long else (pos.entry_price - curr_px)
                if gain_dist > self.max_profit_reached.get(sym, 0.0):
                    self.max_profit_reached[sym] = gain_dist

                # Khi lãi chạm 1.0 ATR -> Dời SL về Breakeven (entry + fee buffer)
                if gain_dist >= 1.0 * decision.atr:
                    fee_buf = pos.entry_price * 0.0015
                    breakeven_sl = (pos.entry_price + fee_buf) if is_long else (pos.entry_price - fee_buf)
                    if is_long and curr_px <= breakeven_sl:
                        decision = SignalDecision(
                            signal="FLAT",
                            intent="CENTER_EXIT",
                            side="SELL",
                            signal_price=breakeven_sl,
                            exit_reason="breakeven_protect",
                            atr=decision.atr,
                            k_delta=decision.k_delta,
                        )
                    elif (not is_long) and curr_px >= breakeven_sl:
                        decision = SignalDecision(
                            signal="FLAT",
                            intent="CENTER_EXIT",
                            side="BUY",
                            signal_price=breakeven_sl,
                            exit_reason="breakeven_protect",
                            atr=decision.atr,
                            k_delta=decision.k_delta,
                        )

                # Chốt lời chủ động khi đạt 1.5 ATR
                if gain_dist >= 1.5 * decision.atr and not pos.already_partial_tp:
                    decision = SignalDecision(
                        signal="FLAT",
                        intent="PARTIAL_TP",
                        side="SELL" if is_long else "BUY",
                        signal_price=curr_px,
                        exit_reason="atr_dynamic_tp",
                        atr=decision.atr,
                        k_delta=decision.k_delta,
                    )

            final_contracts: Optional[float] = None
            is_synthetic_bar = bool(c_dict.get("is_filled", 0) == 1)

            if is_synthetic_bar and decision.intent == "ENTRY":
                decision = SignalDecision(
                    signal="HOLD",
                    intent="HOLD",
                    side="HOLD",
                    signal_price=float(c_dict["close"]),
                    atr=decision.atr,
                    k_delta=decision.k_delta,
                )

            if pos.qty_contracts == 0 and decision.intent == "ENTRY" and decision.signal in ("LONG", "SHORT"):
                price = float(c_dict["close"])
                cv = spec.contract_value
                eff_margin = model.effective_margin_ratio

                avail_margin = max(0.0, self.sleeve_capital - current_used_margin)
                if price * cv * eff_margin > 1e-8:
                    max_contracts_margin = avail_margin / (price * cv * eff_margin)
                else:
                    max_contracts_margin = 0.0

                contracts, coin_qty, notional_q, notional_ac, margin_ac = model.calculate_sizing(
                    price, decision.atr, decision.k_delta
                )

                allowed_contracts = min(contracts, max_contracts_margin)
                final_contracts = floor_to_step(allowed_contracts, spec.lotSz)

                if final_contracts < spec.minSz:
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
                    est_sl_risk = 1.5 * decision.atr * final_contracts * cv
                    self.sl_risks_at_entry.append(est_sl_risk)
                    self.max_profit_reached[sym] = 0.0

            prev_closed_count = len(model.closed_cycles)
            if not is_synthetic_bar:
                model.step(
                    decision,
                    m_bar,
                    override_contracts=final_contracts if (decision.intent == "ENTRY" and final_contracts) else None,
                )
            else:
                model.pos.mark_price = float(c_dict["close"])

            if len(model.closed_cycles) > prev_closed_count:
                new_cycle = model.closed_cycles[-1]
                self.all_closed_trades.append(new_cycle)
                self.max_profit_reached[sym] = 0.0

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
                total_open_unrealized += (pos.cycle_realized_pnl + unrealized_gross - est_close_fee)

        current_portfolio_equity = self.sleeve_capital + total_realized_pnl + total_open_unrealized
        self.portfolio_equity_curve.append(current_portfolio_equity)

    def close_all_at_end(self, last_prices: Dict[str, float]) -> None:
        for sym, model in self.exec_models.items():
            if model.pos.qty_contracts != 0 and sym in last_prices:
                prev_closed = len(model.closed_cycles)
                model.force_close_all(price=last_prices[sym], reason=ExitReason.SESSION_CUTOFF)
                if len(model.closed_cycles) > prev_closed:
                    self.all_closed_trades.append(model.closed_cycles[-1])

        final_realized_pnl = sum(c.net_pnl for c in self.all_closed_trades)
        final_equity = self.sleeve_capital + final_realized_pnl
        self.portfolio_equity_curve.append(final_equity)


def run_candidate_phase(
    candidate_name: str,
    candidate_config: dict,
    timeline: List[int],
    candles_by_sym_ts: Dict[str, Dict[int, dict]],
    warmup_by_sym: Dict[str, List[dict]],
    specs: Dict[str, InstrumentSpec],
    sleeve_capital: float = 1000.0,
    max_risk_per_trade_usd: float = 15.0,
) -> dict:
    sim = CandidateSimulationEngine(
        candidate_name=candidate_name,
        specs=specs,
        sleeve_capital=sleeve_capital,
        max_risk_per_trade_usd=max_risk_per_trade_usd,
        candidate_config=candidate_config,
    )

    for sym, w_candles in warmup_by_sym.items():
        sim.warmup_symbol(sym, w_candles)

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

    sim.close_all_at_end(last_prices)

    trades = sim.all_closed_trades
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.net_pnl > 0)
    losses = sum(1 for t in trades if t.net_pnl < 0)
    net_pnl = sum(t.net_pnl for t in trades)
    gross_profit = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
    gross_loss = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
    total_fees = sum(t.total_fees for t in trades)

    gross_profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_profit > 0 else 0.0)
    net_wins_pnl = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    net_losses_pnl = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    net_profit_factor = (net_wins_pnl / net_losses_pnl) if net_losses_pnl > 1e-9 else (99.0 if net_wins_pnl > 0 else 0.0)
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

    eq_arr = np.array(sim.portfolio_equity_curve) if sim.portfolio_equity_curve else np.array([sleeve_capital])
    peaks = np.maximum.accumulate(eq_arr)
    drawdowns = (peaks - eq_arr) / peaks * 100.0
    max_dd_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0
    avg_sl_risk = float(np.mean(sim.sl_risks_at_entry)) if sim.sl_risks_at_entry else 0.0

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
            "final_equity": round(sleeve_capital + net_pnl, 2),
        },
        "trades": trade_attributions,
    }


def compare_3_proxima_candidates(total_bars_sample: int = 60000) -> dict:
    specs = load_universe_specs()
    warmup_bars = 1500
    sleeve_capital = 1000.0  # Cấp 1,000 USDT/sleeve theo Phase 4
    max_risk_usd = 15.0      # 1.5% của 1,000 USDT

    df_by_sym = {}
    for sym in UNIVERSE_10:
        base = sym.split("-")[0]
        if specs.get(sym) is None:
            continue
        try:
            df = load_candles(base, "1m")
            if df is not None and len(df) >= (warmup_bars + 5000):
                df_by_sym[sym] = df
        except Exception:
            pass

    active_symbols = [s for s in UNIVERSE_10 if s in df_by_sym]
    needed_len = total_bars_sample + warmup_bars
    latest_end_ts = min(int(df_by_sym[s].iloc[-1]["open_time"]) for s in active_symbols)
    target_start_ts = latest_end_ts - (needed_len * 60 * 1000)

    data_by_sym = {}
    candles_by_sym_ts = {}
    for sym in active_symbols:
        df = df_by_sym[sym]
        df_slice = df[(df["open_time"] >= target_start_ts) & (df["open_time"] <= latest_end_ts)].copy().reset_index(drop=True)
        candles = df_slice.to_dict("records")
        data_by_sym[sym] = candles
        candles_by_sym_ts[sym] = {int(c["open_time"]): c for c in candles}

    timeline = [target_start_ts + (i * 60 * 1000) for i in range(needed_len)]
    total_eval_ts = timeline[warmup_bars:]
    eval_len = len(total_eval_ts)

    is_end_idx = int(eval_len * 0.70)
    val_end_idx = is_end_idx + int(eval_len * 0.15)

    is_ts_list = total_eval_ts[:is_end_idx]
    val_ts_list = total_eval_ts[is_end_idx:val_end_idx]
    holdout_ts_list = total_eval_ts[val_end_idx:]

    valid_specs = {s: specs[s] for s in active_symbols if specs[s] is not None}

    # 3 ỨNG VIÊN GIẢ THUYẾT ĐỘC LẬP
    candidates = {
        "candidate_1_baseline": {
            "name": "Candidate 1 (Baseline Breakout)",
            "description": "Chuẩn Proxima Reference: F=1.0, tp_mult=0.8, anchor=1H, Center Exit",
            "config": {"f_multiplier": 1.0, "tp_mult": 0.8, "vl_mult": 1.0, "r_ratio": 0.15, "mode": "baseline"},
        },
        "candidate_2_vol_filtered": {
            "name": "Candidate 2 (Volatility Confirmed)",
            "description": "Bộ lọc biến động: F=1.25 (yêu cầu breakout mạnh hơn, giảm whipsaw sideway)",
            "config": {"f_multiplier": 1.25, "tp_mult": 0.8, "vl_mult": 1.0, "r_ratio": 0.15, "mode": "baseline"},
        },
        "candidate_3_breakeven_dynamic": {
            "name": "Candidate 3 (Trailing Breakeven & Dynamic TP)",
            "description": "Dời SL về hòa vốn khi +1.0 ATR, chốt lời chủ động khi chạm 1.5 ATR để vượt phí Taker",
            "config": {"f_multiplier": 1.0, "tp_mult": 1.0, "vl_mult": 1.0, "r_ratio": 0.15, "mode": "breakeven_dynamic"},
        },
    }

    comparison_results = {}

    print("═══════════════════════════════════════════════════════════════════")
    print("SO SÁNH 3 ỨNG VIÊN PROXIMA ĐỘC LẬP TRÊN 10 MARKET (PHASE 2 & 3)")
    print("═══════════════════════════════════════════════════════════════════")

    for cand_id, cand_info in candidates.items():
        cand_name = cand_info["name"]
        cfg = cand_info["config"]
        print(f"\n===================================================================")
        print(f"BẮT ĐẦU ĐÁNH GIÁ: {cand_name}")
        print(f"Mô tả: {cand_info['description']}")
        print(f"===================================================================")

        phases = [
            ("in_sample_70", is_ts_list, warmup_bars, is_end_idx + warmup_bars, "In-Sample (70%)"),
            ("validation_15", val_ts_list, is_end_idx + warmup_bars, val_end_idx + warmup_bars, "Validation (15%)"),
            ("holdout_oos_15", holdout_ts_list, val_end_idx + warmup_bars, len(timeline), "Holdout OOS (15% Untouched)"),
        ]

        cand_oos = {}
        for p_key, p_timeline, s_idx, e_idx, p_title in phases:
            w_start_idx = max(0, s_idx - warmup_bars)
            w_ts_list = timeline[w_start_idx:s_idx]
            warmup_by_sym = {s: [candles_by_sym_ts[s][ts] for ts in w_ts_list if ts in candles_by_sym_ts[s]] for s in active_symbols}

            res = run_candidate_phase(
                candidate_name=cand_id,
                candidate_config=cfg,
                timeline=p_timeline,
                candles_by_sym_ts=candles_by_sym_ts,
                warmup_by_sym=warmup_by_sym,
                specs=valid_specs,
                sleeve_capital=sleeve_capital,
                max_risk_per_trade_usd=max_risk_usd,
            )
            cand_oos[p_key] = res["portfolio"]
            p = res["portfolio"]
            print(f"[{p_title}] Trades: {p['total_trades']:3d} | WinRate: {p['win_rate']:5.1f}% | NetPF: {p['net_profit_factor']:4.2f} | Net PnL: ${p['net_pnl']:+6.2f} | MaxDD: {p['max_drawdown_pct']:.2f}%")

        # 3 Cửa sổ Robustness trong IS
        is_span = len(is_ts_list)
        w_size = is_span // 3
        robust_windows = [
            ("Window 1", is_ts_list[0:w_size], warmup_bars + 0, warmup_bars + w_size),
            ("Window 2", is_ts_list[w_size:2 * w_size], warmup_bars + w_size, warmup_bars + 2 * w_size),
            ("Window 3", is_ts_list[2 * w_size:], warmup_bars + 2 * w_size, warmup_bars + is_span),
        ]
        positive_win = 0
        w_results = []
        for w_name, w_timeline, w_s, w_e in robust_windows:
            w_start_idx = max(0, w_s - warmup_bars)
            w_ts_list = timeline[w_start_idx:w_s]
            warmup_by_sym = {s: [candles_by_sym_ts[s][ts] for ts in w_ts_list if ts in candles_by_sym_ts[s]] for s in active_symbols}
            w_res = run_candidate_phase(
                candidate_name=cand_id,
                candidate_config=cfg,
                timeline=w_timeline,
                candles_by_sym_ts=candles_by_sym_ts,
                warmup_by_sym=warmup_by_sym,
                specs=valid_specs,
                sleeve_capital=sleeve_capital,
                max_risk_per_trade_usd=max_risk_usd,
            )
            wp = w_res["portfolio"]
            is_pos = wp["net_pnl"] > 0
            if is_pos:
                positive_win += 1
            w_results.append({"window": w_name, "metrics": wp, "positive": is_pos})
            print(f"  ↳ [{w_name}] NetPF: {wp['net_profit_factor']:4.2f} | Net PnL: ${wp['net_pnl']:+6.2f} | Dương: {is_pos}")

        # Kiểm định Gate
        h_pnl = cand_oos["holdout_oos_15"]["net_pnl"]
        h_trades = cand_oos["holdout_oos_15"]["total_trades"]
        h_net_pf = cand_oos["holdout_oos_15"]["net_profit_factor"]

        g1 = (h_pnl > 0)
        g2 = (positive_win >= 2)
        g3 = (h_trades >= 40)
        g4 = (h_pnl >= 10.0 and h_net_pf >= 1.25)
        approved = (g1 and g2 and g3 and g4)

        comparison_results[cand_id] = {
            "name": cand_name,
            "description": cand_info["description"],
            "config": cfg,
            "oos_results": cand_oos,
            "robustness_windows": w_results,
            "positive_windows_ratio": f"{positive_win}/3",
            "gates": {
                "gate_holdout_positive": g1,
                "gate_robustness_passed": g2,
                "gate_sample_size": g3,
                "gate_edge_strength": g4,
                "approved_for_paper": approved,
            },
        }

    out_file = os.path.join(root_dir, "data", "proxima_3candidates_comparison.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparison_results, f, indent=2, ensure_ascii=False)

    print("\n═══════════════════════════════════════════════════════════════════")
    print("BẢNG TỔNG KẾT NGHIỆM THU 3 ỨNG VIÊN (GATE SUMMARY):")
    print("═══════════════════════════════════════════════════════════════════")
    for cid, cdata in comparison_results.items():
        g = cdata["gates"]
        hp = cdata["oos_results"]["holdout_oos_15"]
        print(f"[{cdata['name']}]")
        print(f"  Holdout Net PnL: ${hp['net_pnl']:+.2f} | Net PF: {hp['net_profit_factor']} | Trades: {hp['total_trades']}")
        print(f"  Robustness Windows: {cdata['positive_windows_ratio']} dương")
        print(f"  KẾT LUẬN CỔNG: {'ĐỦ ĐIỀU KIỆN (PASS)' if g['approved_for_paper'] else 'CHƯA ĐẠT (FAIL - DỪNG TẠI BACKTEST)'}")
    print("═══════════════════════════════════════════════════════════════════")

    return comparison_results


if __name__ == "__main__":
    compare_3_proxima_candidates(total_bars_sample=60000)
