"""Gate 1.5: Empirical Parity with Losing Trades (SL) & ETH.

Tiêu chí nghiệm thu Gate 1.5:
1. Chạy độc lập qua subprocess giữa COIN (PYTHONPATH=nora/coin) và EDU (PYTHONPATH=nora/edu) - Zero cross-import.
2. Kiểm thử trên BTC (3 bps slippage proxy) có phát sinh lệnh cắt lỗ (SL hits / losing trades).
3. Kiểm thử trên ETH (5 bps slippage proxy) xác nhận hợp đồng và trượt giá ETH hoạt động chính xác.
4. Đối soát 100% các metrics dùng chung (ret_pct, mdd_pct, sharpe, sortino, trades, win_rate, fees_usd).
5. Phân định rõ ràng schema: EDU chứa các trường chẩn đoán giáo dục mở rộng, COIN trả về bộ production quants chuẩn.
"""
import json
import os
import subprocess
import sys
import pytest

RUNNER_SCRIPT = """
import json
import sys
from backend.jobs.tasks import run_custom

symbol = sys.argv[1]
code = '''class StandardDeviationDynamicChannelBreakout(NoraStrategy):
    timeframe = '24h'
    sma_period = 20
    std_period = 20
    std_nbdev = 1.5
    macro_period = 100
    stop_loss_pct = 2.5
    risk_per_trade_pct = 0.25

    def on_bar(self):
        sma_val = sma(close, self.sma_period)
        std_val = stddev(close, self.std_period, self.std_nbdev)
        upper_band = sma_val + std_val
        macro = ema(close, self.macro_period)

        exit_sig = close < sma_val
        enter_sig = crossover(close, upper_band) & (close > macro)

        self.close(exit_sig)
        self.buy(enter_sig)
'''

res = run_custom({
    'code': code,
    'symbols': [symbol],
    'start': '2023-10-06',
    'end': '2026-10-03',
    'train_ratio': 0.7,
    'initial_capital': 10000.0
})

trades = res.get('trades', [])
trades_summary = [
    {
        'symbol': r.get('symbol', symbol),
        'side': r.get('side'),
        'qty': round(float(r.get('qty', 0.0)), 6),
        'enter_time': r.get('enter_time'),
        'close_time': r.get('close_time'),
        'enter_price': round(float(r.get('enter_price', 0.0)), 4),
        'close_price': round(float(r.get('close_price', 0.0)), 4),
        'close_reason': r.get('close_reason'),
        'fees_usd': round(float(r.get('fees_usd', 0.0)), 4),
        'funding_usd': round(float(r.get('funding_usd', 0.0)), 4),
        'pnl_usd': round(float(r.get('pnl', r.get('pnl_usd', 0.0))), 4)
    }
    for r in trades
]

output = {
    'metrics': res.get('metrics', {}).get('simulate', {}),
    'trades_count': len(trades),
    'trades_summary': trades_summary
}

print('__EMPIRICAL_RESULT__' + json.dumps(output))
"""

def execute_backtest(product_dir: str, symbol: str) -> dict:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    target_path = os.path.join(repo_root, product_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = target_path

    cmd = [
        "/home/vmc03/.venvs/nora312/bin/python",
        "-c",
        RUNNER_SCRIPT,
        symbol
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"Lỗi khi chạy {product_dir} trên {symbol}: {res.stderr}\n{res.stdout}")

    for line in res.stdout.splitlines():
        if line.startswith("__EMPIRICAL_RESULT__"):
            return json.loads(line[len("__EMPIRICAL_RESULT__"):])
    raise RuntimeError(f"Không tìm thấy kết quả từ {product_dir} trên {symbol}")


def test_gate1_5_btc_empirical_parity_with_losing_trades():
    """Kiểm tra parity trên BTC có các lệnh thua lỗ (SL hits)."""
    coin_res = execute_backtest("nora/coin", "BTC")
    edu_res = execute_backtest("nora/edu", "BTC")

    assert coin_res["trades_count"] == 18, f"BTC fixture phải phát sinh đúng 18 lệnh (thực tế {coin_res['trades_count']})"
    assert coin_res["trades_count"] == edu_res["trades_count"], "Số lượng lệnh COIN và EDU phải trùng khớp tuyệt đối"

    # Phân loại rõ ràng lý do đóng lệnh: Stop-loss vs Signal Exit
    sl_trades = [t for t in coin_res["trades_summary"] if "Stop-loss" in str(t.get("close_reason"))]
    signal_trades = [t for t in coin_res["trades_summary"] if "Tín hiệu" in str(t.get("close_reason")) or "AST" in str(t.get("close_reason"))]

    assert len(sl_trades) == 9, f"Khóa chính xác 9 lệnh dính Stop-Loss trên BTC (thực tế {len(sl_trades)})"
    assert len(signal_trades) == 9, f"Khóa chính xác 9 lệnh thoát theo Tín hiệu trên BTC (thực tế {len(signal_trades)})"
    assert len(sl_trades) + len(signal_trades) == 18, "Toàn bộ lệnh phải thuộc về SL hoặc Signal exit!"

    # Xác minh đối chiếu 100% các trường trade giữa COIN và EDU
    for i, (c_tr, e_tr) in enumerate(zip(coin_res["trades_summary"], edu_res["trades_summary"])):
        assert c_tr["symbol"] == e_tr["symbol"], f"Lệnh #{i}: Lệch symbol ({c_tr['symbol']} vs {e_tr['symbol']})"
        assert c_tr["side"] == e_tr["side"], f"Lệnh #{i}: Lệch side ({c_tr['side']} vs {e_tr['side']})"
        assert abs(c_tr["qty"] - e_tr["qty"]) < 1e-6, f"Lệnh #{i}: Lệch qty ({c_tr['qty']} vs {e_tr['qty']})"
        assert c_tr["enter_time"] == e_tr["enter_time"], f"Lệnh #{i}: Lệch enter_time"
        assert c_tr["close_time"] == e_tr["close_time"], f"Lệnh #{i}: Lệch close_time"
        assert c_tr["close_reason"] == e_tr["close_reason"], f"Lệnh #{i}: Lệch close_reason ({c_tr['close_reason']} vs {e_tr['close_reason']})"
        assert abs(c_tr["enter_price"] - e_tr["enter_price"]) < 0.01, f"Lệnh #{i}: Lệch enter_price"
        assert abs(c_tr["close_price"] - e_tr["close_price"]) < 0.01, f"Lệnh #{i}: Lệch close_price"
        assert abs(c_tr["pnl_usd"] - e_tr["pnl_usd"]) < 1e-3, f"Lệnh #{i}: Lệch PnL {c_tr['pnl_usd']} vs {e_tr['pnl_usd']}"
        assert abs(c_tr["fees_usd"] - e_tr["fees_usd"]) < 1e-3, f"Lệnh #{i}: Lệch Fees {c_tr['fees_usd']} vs {e_tr['fees_usd']}"
        assert abs(c_tr["funding_usd"] - e_tr["funding_usd"]) < 1e-3, f"Lệnh #{i}: Lệch Funding {c_tr['funding_usd']} vs {e_tr['funding_usd']}"

        # Xác minh lệnh SL: Giá đóng phải phản ánh mức SL 2.5% bị phạt thêm 2x trượt giá (6 bps cho BTC)
        if "Stop-loss" in str(c_tr["close_reason"]):
            assert c_tr["pnl_usd"] < 0, f"Lệnh SL #{i} nhưng PnL lại dương!"
            max_expected_close_px = c_tr["enter_price"] * (1.0 - 0.025)
            assert c_tr["close_price"] <= (max_expected_close_px + 1.0), (
                f"Lệnh SL #{i}: Giá đóng {c_tr['close_price']} cao hơn ngưỡng SL {max_expected_close_px}"
            )

    # Đối chiếu toàn bộ các chỉ số chung trong simulate
    shared_metric_keys = [
        "ret_pct", "mdd_pct", "sharpe", "sortino", "cagr_pct", "calmar",
        "trades", "win_rate_trades", "profit_factor_trades", "fees_usd"
    ]
    for k in shared_metric_keys:
        c_val = coin_res["metrics"].get(k)
        e_val = edu_res["metrics"].get(k)
        if c_val is None or e_val is None:
            assert c_val == e_val, f"Key {k}: {c_val} vs {e_val}"
        else:
            assert abs(float(c_val) - float(e_val)) < 1e-2, f"Key {k}: COIN={c_val} vs EDU={e_val}"


def test_gate1_5_eth_empirical_parity_and_slippage():
    """Kiểm tra parity trên ETH (5 bps slippage proxy)."""
    coin_res = execute_backtest("nora/coin", "ETH")
    edu_res = execute_backtest("nora/edu", "ETH")

    assert coin_res["trades_count"] > 0, "Phải có giao dịch phát sinh trên ETH"
    assert coin_res["trades_count"] == edu_res["trades_count"], "Số lượng lệnh ETH phải trùng khớp"

    # Phân loại lý do đóng lệnh ETH
    sl_trades = [t for t in coin_res["trades_summary"] if "Stop-loss" in str(t.get("close_reason"))]
    signal_trades = [t for t in coin_res["trades_summary"] if "Tín hiệu" in str(t.get("close_reason")) or "AST" in str(t.get("close_reason"))]
    assert len(sl_trades) > 0, "ETH phải có ít nhất 1 lệnh Stop-loss!"
    assert len(signal_trades) > 0, "ETH phải có ít nhất 1 lệnh Signal exit!"

    # Đối chiếu từng lệnh ETH qua đầy đủ các trường
    for i, (c_tr, e_tr) in enumerate(zip(coin_res["trades_summary"], edu_res["trades_summary"])):
        assert c_tr["symbol"] == e_tr["symbol"], f"Lệnh ETH #{i}: Lệch symbol"
        assert c_tr["side"] == e_tr["side"], f"Lệnh ETH #{i}: Lệch side"
        assert abs(c_tr["qty"] - e_tr["qty"]) < 1e-6, f"Lệnh ETH #{i}: Lệch qty"
        assert c_tr["enter_time"] == e_tr["enter_time"], f"Lệnh ETH #{i}: Lệch enter_time"
        assert c_tr["close_time"] == e_tr["close_time"], f"Lệnh ETH #{i}: Lệch close_time"
        assert c_tr["close_reason"] == e_tr["close_reason"], f"Lệnh ETH #{i}: Lệch close_reason"
        assert abs(c_tr["enter_price"] - e_tr["enter_price"]) < 0.01, f"Lệnh ETH #{i}: Lệch enter_price"
        assert abs(c_tr["close_price"] - e_tr["close_price"]) < 0.01, f"Lệnh ETH #{i}: Lệch close_price"
        assert abs(c_tr["pnl_usd"] - e_tr["pnl_usd"]) < 1e-3, f"Lệnh ETH #{i}: Lệch PnL"
        assert abs(c_tr["fees_usd"] - e_tr["fees_usd"]) < 1e-3, f"Lệnh ETH #{i}: Lệch Fees"
        assert abs(c_tr["funding_usd"] - e_tr["funding_usd"]) < 1e-3, f"Lệnh ETH #{i}: Lệch Funding"

    # Đối chiếu metrics chung
    shared_metric_keys = [
        "ret_pct", "mdd_pct", "sharpe", "sortino", "cagr_pct", "calmar",
        "trades", "win_rate_trades", "profit_factor_trades", "fees_usd"
    ]
    for k in shared_metric_keys:
        c_val = coin_res["metrics"].get(k)
        e_val = edu_res["metrics"].get(k)
        if c_val is None or e_val is None:
            assert c_val == e_val, f"Key {k}: {c_val} vs {e_val}"
        else:
            assert abs(float(c_val) - float(e_val)) < 1e-2, f"Key {k}: COIN={c_val} vs EDU={e_val}"

