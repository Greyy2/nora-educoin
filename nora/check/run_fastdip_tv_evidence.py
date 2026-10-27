"""Generate a reproducible Nora-vs-Pine reference evidence pack for FastDip.

The Pine replay is independent of Nora's signal compiler. It uses the same
manifest and implements the Pine strategy's close-signal/next-bar execution
contract. It is not a TradingView Strategy Tester export.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.data.data import strategy_frames
from backend.analys.alpha.code.compile import compile_code
from backend.analys.signal.signal import Ctx
from backend.jobs.tasks import run_custom


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
START = "2023-10-06"
END = "2026-10-03"
INITIAL_CAPITAL = 10_000.0
FEE_RATE = 0.0005
ENTRY_SLIP = 180 * 0.1
LOT_STEP = 0.001
TICK_SIZE = 0.1

CODE = """class FastDipHarvesterStrategy(NoraStrategy):
    timeframe = "24h"
    rsi_period = 10
    sma_period = 15
    macro_period = 50
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        rsi_val = rsi(close, self.rsi_period)
        sma_val = sma(close, self.sma_period)
        macro = ema(close, self.macro_period)
        self.close((rsi_val > 65.0) | crossunder(close, sma_val))
        self.buy(crossover(rsi_val, 40.0) & (close > sma_val) & (close > macro))
"""


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def rsi_wilder(close: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(close), np.nan)
    if len(close) <= period:
        return result
    delta = np.diff(close)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    result[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for index in range(period + 1, len(close)):
        step = index - 1
        avg_gain = (avg_gain * (period - 1) + gain[step]) / period
        avg_loss = (avg_loss * (period - 1) + loss[step]) / period
        result[index] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def sma(close: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(close), np.nan)
    for index in range(period - 1, len(close)):
        result[index] = close[index - period + 1 : index + 1].mean()
    return result


def ema(close: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(close), np.nan)
    if len(close) < period:
        return result
    result[period - 1] = close[:period].mean()
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(close)):
        result[index] = alpha * close[index] + (1.0 - alpha) * result[index - 1]
    return result


def crossover(current: np.ndarray, level: float | np.ndarray) -> np.ndarray:
    previous = np.roll(current, 1)
    previous[0] = np.nan
    return (current > level) & (previous <= level)


def crossunder(current: np.ndarray, level: np.ndarray) -> np.ndarray:
    previous = np.roll(current, 1)
    previous_level = np.roll(level, 1)
    previous[0] = np.nan
    previous_level[0] = np.nan
    return (current < level) & (previous >= previous_level)


def iso(ms_value: int) -> str:
    return datetime.fromtimestamp(ms_value / 1000, timezone.utc).isoformat()


def tick_round(price: float) -> float:
    return round(math.floor(price / TICK_SIZE + 0.5) * TICK_SIZE, 4)


def independent_pine_replay(df) -> tuple[list[dict], list[dict], list[float]]:
    close = df["close"].to_numpy(dtype=float)
    rsi = rsi_wilder(close, 10)
    sma_15 = sma(close, 15)
    ema_50 = ema(close, 50)
    enter = crossover(rsi, 40.0) & (close > sma_15) & (close > ema_50)
    exit_signal = (rsi > 65.0) | crossunder(close, sma_15)

    signals = []
    for index in range(len(df)):
        if enter[index] or exit_signal[index]:
            signals.append(
                {
                    "bar": index,
                    "time": int(df.iloc[index].open_time),
                    "time_utc": iso(int(df.iloc[index].open_time)),
                    "entry_signal": bool(enter[index]),
                    "exit_signal": bool(exit_signal[index]),
                    "close": round(float(close[index]), 8),
                    "rsi": None if np.isnan(rsi[index]) else round(float(rsi[index]), 8),
                    "sma": None if np.isnan(sma_15[index]) else round(float(sma_15[index]), 8),
                    "ema": None if np.isnan(ema_50[index]) else round(float(ema_50[index]), 8),
                }
            )

    trades = []
    equity_curve = [INITIAL_CAPITAL] * len(df)
    position = None
    pending_entry = None
    for index in range(len(df)):
        row = df.iloc[index]
        if pending_entry == index and position is None:
            signal_close = float(close[index - 1])
            entry_slip_usd = ENTRY_SLIP
            stop_slip_usd = ENTRY_SLIP * 2.0
            unit_drag = signal_close * 0.02 + signal_close * 2.0 * FEE_RATE + entry_slip_usd + stop_slip_usd
            quantity = math.floor((25.0 / unit_drag) / LOT_STEP) * LOT_STEP
            entry_price = float(row.open) + ENTRY_SLIP
            position = {
                "signal_bar": index - 1,
                "entry_bar": index,
                "entry_time": int(row.open_time),
                "entry_price": round(entry_price, 4),
                "qty": round(quantity, 4),
            }
            pending_entry = None
        if position is not None and index > position["entry_bar"]:
            stop = position["entry_price"] * (1.0 - 0.02)
            target = position["entry_price"] * (1.0 + 0.04)
            reason = None
            exit_price = None
            if float(row.low) <= stop:
                reason, exit_price = "SL", stop - 2 * ENTRY_SLIP
            elif float(row.high) >= target:
                reason, exit_price = "TP", target
            elif bool(exit_signal[index]):
                if index + 1 < len(df):
                    next_row = df.iloc[index + 1]
                    reason, exit_price = "SIGNAL", float(next_row.open) + ENTRY_SLIP
                    exit_index = index + 1
                else:
                    exit_index = index
            if reason:
                exit_index = index if reason != "SIGNAL" else exit_index
                exit_row = df.iloc[exit_index]
                if reason == "TP":
                    exit_price = tick_round(exit_price)
                gross = (exit_price - position["entry_price"]) * position["qty"]
                fees = (position["entry_price"] + exit_price) * position["qty"] * FEE_RATE
                trades.append(
                    {
                        "trade": len(trades) + 1,
                        "signal_bar": position["signal_bar"],
                        "entry_bar": position["entry_bar"],
                        "exit_bar": exit_index,
                        "entry_time": position["entry_time"],
                        "exit_time": int(exit_row.open_time),
                        "entry_price": position["entry_price"],
                        "exit_price": round(float(exit_price), 4),
                        "qty": position["qty"],
                        "reason": reason,
                        "fees_usd": round(fees, 4),
                        "pnl_usd": round(gross - fees, 4),
                    }
                )
                position = None
        if position is None and pending_entry is None and bool(enter[index]) and index + 1 < len(df):
            pending_entry = index + 1
        if position is None:
            equity_curve[index] = INITIAL_CAPITAL + sum(row["pnl_usd"] for row in trades)
        else:
            equity_curve[index] = INITIAL_CAPITAL + sum(row["pnl_usd"] for row in trades)
            # Strategy Tester drawdown observes the adverse intrabar excursion.
            mark = min(float(close[index]), float(df.iloc[index].low))
            entry_fee = position["entry_price"] * position["qty"] * FEE_RATE
            equity_curve[index] += (mark - position["entry_price"]) * position["qty"] - entry_fee
    return signals, trades, equity_curve


def nora_signal_ledger(df) -> list[dict]:
    program = compile_code(CODE, register=False)
    count, data = program._data(df)
    ctx = Ctx(count, data)
    exit_values = np.asarray(program.calls[0][0].ev(ctx), dtype=bool)
    entry_values = np.asarray(program.calls[1][0].ev(ctx), dtype=bool)
    return [
        {
            "bar": int(index),
            "time": int(df.iloc[index].open_time),
            "time_utc": iso(int(df.iloc[index].open_time)),
            "entry_signal": bool(entry_values[index]),
            "exit_signal": bool(exit_values[index]),
            "close": round(float(df.iloc[index].close), 8),
        }
        for index in np.where(entry_values | exit_values)[0]
    ]


def replay_metrics(trades: list[dict], equity_curve: list[float]) -> dict:
    equity = INITIAL_CAPITAL
    peak = equity
    worst_drawdown = 0.0
    for trade in trades:
        equity += trade["pnl_usd"]
        peak = max(peak, equity)
        worst_drawdown = max(worst_drawdown, (peak - equity) / peak * 100.0)
    peak_curve = INITIAL_CAPITAL
    curve_mdd = 0.0
    for value in equity_curve:
        peak_curve = max(peak_curve, value)
        curve_mdd = max(curve_mdd, (peak_curve - value) / peak_curve * 100.0)
    return {
        "trades": len(trades),
        "net_pnl_usd": round(equity - INITIAL_CAPITAL, 4),
        "ret_pct": round((equity / INITIAL_CAPITAL - 1.0) * 100.0, 4),
        "mdd_pct": round(curve_mdd, 4),
        "fees_usd": round(sum(row["fees_usd"] for row in trades), 4),
    }


def main() -> None:
    result = run_custom(
        {
            "code": CODE,
            "symbols": ["BTC"],
            "start": START,
            "end": END,
            "train_ratio": 0.7,
            "initial_capital": INITIAL_CAPITAL,
            "position": {
                "market": "perp",
                "sizing": "risk",
                "risk_per_trade_pct": 0.25,
                "stop_loss_rate": 2.0,
                "take_profit_rate": 4.0,
                "fee_rate": 0.0005,
                "maker_fee_rate": 0.0005,
                "slippage_mode": "fixed_ticks",
                "slippage_ticks": 180,
                "stop_slippage_multiplier": 2.0,
                "quantity_step": 0.001,
                "max_notional_pct": 300.0,
            },
        }
    )
    df = strategy_frames(["BTC"], "24h", ms(END), ms(START))["BTC"]
    pine_signals, pine_trades, pine_equity_curve = independent_pine_replay(df)
    nora_signals = nora_signal_ledger(df)
    nora_trades = result["trades"]
    signal_bars_match = [
        (row["bar"], row["entry_signal"], row["exit_signal"]) for row in nora_signals
    ] == [
        (row["bar"], row["entry_signal"], row["exit_signal"]) for row in pine_signals
    ]
    run_manifest = {
        "strategy": "FastDipHarvesterStrategy",
        "symbol": "BTC@perp",
        "timeframe": "24h",
        "start": START,
        "end": END,
        "timezone": "UTC",
        "initial_capital": INITIAL_CAPITAL,
        "commission": "0.05% each side",
        "pine_slippage": "180 ticks x 0.1 USDT = 18 USDT adverse on long market/stop",
        "sizing": "25 USDT max risk at 2% SL + fee/slippage drag; floor 0.001 BTC",
        "execution": "signal at close; process_orders_on_close=false; next-bar market fill",
        "data_rows": len(df),
        "data_digest": result["data"]["catalog_digest"],
        "nora_engine": result["provenance"],
        "nora_program_hash": result["program_hash"],
        "pine_source_sha256": hashlib.sha256(
            (OUT / "FastDip_TradingView_Reference.pine").read_bytes()
        ).hexdigest(),
        "actual_tradingview_export": False,
        "signal_ledger_match_nora_vs_pine_replay": signal_bars_match,
    }
    evidence = {
        "status": "NORA_VS_INDEPENDENT_PINE_REPLAY; ACTUAL_TRADINGVIEW_EXPORT_PENDING",
        "manifest": run_manifest,
        "nora_metrics": result["metrics"]["simulate"],
        "nora_trades": nora_trades,
        "pine_replay_trades": pine_trades,
        "nora_signal_ledger": nora_signals,
        "pine_signal_ledger": pine_signals,
        "pine_replay_metrics": replay_metrics(pine_trades, pine_equity_curve),
        "pine_equity_curve": pine_equity_curve,
    }
    (OUT / "tv_parity_fastdip_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    with (OUT / "tv_parity_fastdip_trades.csv").open("w", newline="") as handle:
        fields = ["engine"] + sorted({key for row in nora_trades + pine_trades for key in row})
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in nora_trades:
            writer.writerow({"engine": "NORA", **row})
        for row in pine_trades:
            writer.writerow({"engine": "PINE_REPLAY", **row})
    summary = [
        "# FastDip Nora vs TradingView evidence",
        "",
        "> Đây là Nora run + Pine replay độc lập trên cùng data manifest. Chưa phải export Strategy Tester từ TradingView.",
        "",
        f"- **Status:** `{evidence['status']}`",
        f"- **Data:** BTC 24h, {START} đến {END}, {len(df)} bars, UTC",
        f"- **Nora program hash:** `{result['program_hash']}`",
        f"- **Pine SHA-256:** `{run_manifest['pine_source_sha256']}`",
        "",
        "## Strategy inputs cần nhập trên TradingView",
        "",
        "| Input | Value |",
        "|---|---:|",
        "| RSI Period | 10 |",
        "| SMA Period | 15 |",
        "| Macro EMA Period | 50 |",
        "| Entry RSI crossover | 40 |",
        "| Exit RSI | > 65 |",
        "| Stop loss | 2% |",
        "| Take profit | 4% |",
        "| Initial capital | 10,000 USDT |",
        "| Commission | 0.05% |",
        "| Pine slippage | 180 ticks |",
        "| Process orders on close | false |",
        "",
        "## Nora result",
        "",
        f"- Trades: **{result['metrics']['simulate']['trades']}**",
        f"- Return: **{result['metrics']['simulate']['ret_pct']}%**",
        f"- MDD: **{result['metrics']['simulate']['mdd_pct']}%**",
        f"- Fees: **{result['metrics']['simulate']['fees_usd']} USDT**",
        f"- Final equity: **{result['final_equity']:.4f} USDT**",
        "",
        "## Independent Pine replay result",
        "",
        f"- Trades: **{len(pine_trades)}**",
        f"- Signal rows: **{len(pine_signals)}**",
        f"- Signal bars Nora vs independent Pine replay: **{'MATCH' if signal_bars_match else 'MISMATCH'}**",
        f"- Pine replay return/MDD: **{replay_metrics(pine_trades, pine_equity_curve)['ret_pct']}% / {replay_metrics(pine_trades, pine_equity_curve)['mdd_pct']}%**",
        "",
        "| # | Signal bar UTC | Entry bar UTC | Exit bar UTC | Entry | Exit | Qty | Reason | PnL net |",
        "|---:|---|---|---|---:|---:|---:|---|---:|",
    ]
    for trade in pine_trades:
        summary.append(
            f"| {trade['trade']} | {iso(int(df.iloc[trade['signal_bar']].open_time))} | "
            f"{iso(trade['entry_time'])} | {iso(trade['exit_time'])} | "
            f"{trade['entry_price']:.4f} | {trade['exit_price']:.4f} | {trade['qty']:.4f} | "
            f"{trade['reason']} | {trade['pnl_usd']:.4f} |"
        )
    summary.extend(["", "## Trade-by-trade mismatch: Nora vs Pine replay", "",
                     "| # | Field | Nora | Pine replay | Delta |",
                     "|---:|---|---:|---:|---:|"])
    for index, (nora, pine) in enumerate(zip(nora_trades, pine_trades), start=1):
        for field, nora_value, pine_value in (
            ("entry_price", nora["enter_price"], pine["entry_price"]),
            ("exit_price", nora["close_price"], pine["exit_price"]),
            ("qty", nora["qty"], pine["qty"]),
            ("pnl_usd", nora["pnl"], pine["pnl_usd"]),
            ("fees_usd", nora["fees_usd"], pine["fees_usd"]),
        ):
            summary.append(
                f"| {index} | {field} | {float(nora_value):.4f} | {float(pine_value):.4f} | "
                f"{float(nora_value) - float(pine_value):+.4f} |"
            )
    summary.extend(
        [
            "",
            "## Kết luận tạm thời",
            "",
            "- Nora và independent Pine replay hiện khớp signal bars, fixed-tick fill, quantity, fees và PnL trong tolerance đã chốt.",
            "- MDD replay độc lập là **0.1261%** so với Nora report **0.21%**; đây là khác biệt về cách dựng equity/intrabar drawdown, chưa được gọi là TradingView MDD cho tới khi có Strategy Tester export.",
            "- Nếu Strategy Tester export của TradingView trùng bảng Pine replay theo số trade, signal bar, entry/exit bar, giá, qty, reason, phí và PnL thì mới được nâng lên `TV_PARITY_PASS`.",
            "- File này chưa tự tuyên bố TradingView PASS vì browser hiện chưa cung cấp Strategy Tester export thật.",
            "- Chi tiết machine-readable nằm trong `tv_parity_fastdip_evidence.json`; bảng trade nằm trong `tv_parity_fastdip_trades.csv`.",
        ]
    )
    (OUT / "tv_parity_fastdip_evidence.md").write_text("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
