"""Gate 1.4: MDD & Chart Series Alignment Verification (COIN & EDU Isolated).

Tiêu chí nghiệm thu Gate 1.4:
1. Đối soát cơ chế tính MDD giữa `_metric_block` (intrabar MDD) và `stage_block` (chart series drawdown_pct).
2. Chứng minh `equity_worst` (giá trị vốn thấp nhất trong nến/ngày) được phản ánh nhất quán:
   - Khi có râu nến giảm sâu trong ngày (intrabar dip), MDD không bị che giấu bởi giá đóng cửa.
   - Chuỗi drawdown_pct trong chart stages sử dụng `np.minimum(eq, worst)`, bảo toàn rủi ro thật.
3. Chạy end-to-end qua backtest engine trên CẢ EDU và COIN (cô lập tuyệt đối).
4. Khẳng định BẮT BUỘC (Mandatory Assertion):
   - Không dùng `if stages and "drawdown_pct" in stages:`
   - Yêu cầu `drawdown_pct` phải tồn tại trong `stages["all"]` và có phần tử.
   - Khớp sai số trong dung sai đóng băng: |max_dd_from_series - mdd_pct| <= 0.05%.
"""
import pytest
import os
import sys
import json
import subprocess
import numpy as np


def test_gate1_4_synthetic_mdd_and_chart_drawdown_alignment():
    """Kiểm tra logic toán học giữa _metric_block và stage_block."""
    # Chạy qua COIN
    sys_path_save = list(sys.path)
    try:
        if "nora/coin" not in sys.path:
            sys.path.insert(0, os.path.abspath("nora/coin"))
        from backend.analys.metrics.trades import _metric_block
        from backend.analys.metrics.charts import stage_block

        # Kịch bản 1: Equity không có intrabar dip (equity_worst == equity)
        times = np.array([1700000000000, 1700086400000, 1700172800000, 1700259200000], dtype=np.int64)
        equity = np.array([1000.0, 1100.0, 990.0, 1050.0], dtype=np.float64)
        worst = equity.copy()
        ret = np.zeros(equity.shape[0])
        ret[1:] = equity[1:] / equity[:-1] - 1.0

        # Tính metrics
        metrics = _metric_block(ret, [], fees=0.0, series_equity=equity, series_worst=worst)
        assert metrics["mdd_pct"] == 10.0

        # Tính chart stage
        chart = stage_block(times, equity, equity_worst=worst)
        chart_dd = chart["drawdown_pct"]
        max_chart_dd = abs(min(chart_dd))
        assert round(max_chart_dd, 2) == 10.0
        assert abs(max_chart_dd - metrics["mdd_pct"]) < 1e-4

        # Kịch bản 2: Có intrabar dip sâu (worst < eq)
        worst_with_dip = np.array([1000.0, 1100.0, 935.0, 1050.0], dtype=np.float64)
        metrics_dip = _metric_block(ret, [], fees=0.0, series_equity=equity, series_worst=worst_with_dip)
        assert metrics_dip["mdd_pct"] == 15.0

        chart_dip = stage_block(times, equity, equity_worst=worst_with_dip)
        max_chart_dip_dd = abs(min(chart_dip["drawdown_pct"]))
        assert round(max_chart_dip_dd, 2) == 15.0
        assert abs(max_chart_dip_dd - metrics_dip["mdd_pct"]) < 1e-4
    finally:
        sys.path = sys_path_save


SUBPROCESS_SCRIPT = """
import json, sys
from backend.jobs.tasks import run_custom

code = '''class FastDipHarvester(NoraStrategy):
    timeframe = '24h'
    stop_loss_pct = 2.0
    take_profit_pct = 4.0
    risk_per_trade_pct = 0.25

    def on_bar(self):
        r = rsi(close, 10)
        s = sma(close, 15)
        buy_sig = r < 35.0
        exit_sig = crossover(close, s)
        self.close(exit_sig)
        self.buy(buy_sig)
'''
res = run_custom({
    'code': code,
    'symbols': ['BTC'],
    'start': '2023-10-06',
    'end': '2026-10-03',
    'train_ratio': 0.7,
    'initial_capital': 10000.0
})
metrics = res.get('metrics', {}).get('simulate', {})
stages = res.get('series', {}).get('stages', {}).get('all', {})

out = {
    'mdd_pct': metrics.get('mdd_pct'),
    'has_stages': bool(stages),
    'drawdown_pct': stages.get('drawdown_pct') if stages else None,
}
print('__RESULT__:' + json.dumps(out))
"""

def run_isolated_backtest(product: str) -> dict:
    root = "/home/vmc03/norabt"
    py = "/home/vmc03/.venvs/nora312/bin/python"
    env = dict(os.environ, PYTHONPATH=f"nora/{product}")
    cmd = [py, "-c", SUBPROCESS_SCRIPT]
    cp = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, check=True)
    line = next(l for l in cp.stdout.splitlines() if l.startswith("__RESULT__:"))
    return json.loads(line.replace("__RESULT__:", ""))


def test_gate1_4_mandatory_drawdown_chart_alignment_coin():
    """Kiểm tra bắt buộc tính nhất quán mdd_pct và drawdown_pct chart series trên COIN."""
    res = run_isolated_backtest("coin")
    mdd_pct = res["mdd_pct"]
    assert mdd_pct is not None, "Metrics simulate mdd_pct không được None!"
    assert mdd_pct >= 0.0

    # Khẳng định BẮT BUỘC (Mandatory assertion - không bypass if)
    assert res["has_stages"] is True, "Series stages phải tồn tại trong kết quả backtest!"
    dd_series = res["drawdown_pct"]
    assert dd_series is not None, "drawdown_pct bắt buộc phải có trong chart stages!"
    assert len(dd_series) > 0, "drawdown_pct series không được rỗng!"

    max_dd_from_series = abs(min(dd_series))
    diff = abs(max_dd_from_series - mdd_pct)
    # Dung sai đóng băng trong contract: <= 0.05%
    assert diff <= 0.05, f"COIN: Lệch MDD giữa metrics ({mdd_pct}%) và chart ({max_dd_from_series}%): diff={diff}% > 0.05%"


def test_gate1_4_mandatory_drawdown_chart_alignment_edu():
    """Kiểm tra bắt buộc tính nhất quán mdd_pct và drawdown_pct chart series trên EDU."""
    res = run_isolated_backtest("edu")
    mdd_pct = res["mdd_pct"]
    assert mdd_pct is not None, "Metrics simulate mdd_pct không được None!"
    assert mdd_pct >= 0.0

    # Khẳng định BẮT BUỘC (Mandatory assertion - không bypass if)
    assert res["has_stages"] is True, "Series stages phải tồn tại trong kết quả backtest!"
    dd_series = res["drawdown_pct"]
    assert dd_series is not None, "drawdown_pct bắt buộc phải có trong chart stages!"
    assert len(dd_series) > 0, "drawdown_pct series không được rỗng!"

    max_dd_from_series = abs(min(dd_series))
    diff = abs(max_dd_from_series - mdd_pct)
    # Dung sai đóng băng trong contract: <= 0.05%
    assert diff <= 0.05, f"EDU: Lệch MDD giữa metrics ({mdd_pct}%) và chart ({max_dd_from_series}%): diff={diff}% > 0.05%"
