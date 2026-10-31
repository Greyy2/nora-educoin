"""Benchmark đo lường Staged Latency và Peak Memory cho CROSS-04 và CROSS-05.

Chạy đo lường trên 1 market, 5 markets, và 10 markets khung 1h.
Đo chi tiết 4 tầng:
1. Data Load & Info
2. AST Compile & Plan Build
3. Engine Execution (Matching)
4. Metrics & Diagnostics

Lặp lại tối thiểu 3 lần, ghi nhận min/median/max và VmHWM / VmRSS.
"""
import os
import sys
import time
import json
import statistics
from pathlib import Path

# Đảm bảo đúng import path
EDU_ROOT = Path(__file__).resolve().parents[1] / "nora/edu"
sys.path.insert(0, str(EDU_ROOT))

from backend.analys.alpha.code.compile import compile_code
from backend.analys.alpha.code.plan import build_plan
from backend.data.data import data_info, check_data, UNIVERSE_BASES
from backend.jobs.tasks import run_custom, date_ms

SAMPLE_CODE = """class BenchmarkTrend(SimpleAlgorithm):
    id = "benchmark_trend"
    timeframe = "1h"
    sizing = "risk"
    risk_per_trade_pct = 0.5
    stop_loss_rate = 3.0
    exit_unit = "pct"

    def __algorithm__(self):
        close = self.data.pv_close
        fast = self.feat.ema(close, timeperiod=9)
        slow = self.feat.ema(close, timeperiod=21)
        self.set_positions(fast > slow, position=1)
        self.set_positions(fast < slow, position=0)
"""

START_DATE = "2025-01-01"
END_DATE = "2025-07-01"

def get_proc_memory() -> dict:
    mem = {}
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) == 2 and parts[0] in ("VmPeak", "VmSize", "VmHWM", "VmRSS"):
                    mem[parts[0]] = parts[1].strip()
    except Exception:
        pass
    return mem

def run_single_benchmark(symbols: list[str]) -> dict:
    t_start = time.perf_counter()
    mem_before = get_proc_memory()

    # Stage 1: AST Compile & Plan Build
    t0 = time.perf_counter()
    prog = compile_code(SAMPLE_CODE)
    plan = build_plan(prog, symbols, run_frame="1h")
    stage_compile_ms = (time.perf_counter() - t0) * 1000

    # Stage 2: Data Info & Validation
    t1 = time.perf_counter()
    start_ms = date_ms(START_DATE)
    end_ms = date_ms(END_DATE) + 86400000
    data, warns = data_info(plan.symbols, start_ms, end_ms, "okx")
    stage_data_ms = (time.perf_counter() - t1) * 1000

    # Stage 3: Full run_custom execution
    t2 = time.perf_counter()
    result = run_custom({
        "code": SAMPLE_CODE,
        "symbols": symbols,
        "start": START_DATE,
        "end": END_DATE,
        "run_frame": "1h",
        "initial_capital": 10000,
        "parallel_runs": True,
        "include_benchmark": True,
    })
    total_run_ms = (time.perf_counter() - t2) * 1000

    total_latency_ms = (time.perf_counter() - t_start) * 1000
    mem_after = get_proc_memory()

    return {
        "symbols_count": len(symbols),
        "stage_compile_ms": round(stage_compile_ms, 2),
        "stage_data_ms": round(stage_data_ms, 2),
        "total_run_ms": round(total_run_ms, 2),
        "total_latency_ms": round(total_latency_ms, 2),
        "mem_before": mem_before,
        "mem_after": mem_after,
        "trades_count": len(result.get("trades", [])),
        "ret_pct": (result.get("metrics", {}).get("simulate") or {}).get("ret_pct"),
    }

def main():
    workloads = {
        "1_market": ["BTC"],
        "5_markets": ["BTC", "ETH", "SOL", "BNB", "XRP"],
        "10_markets": UNIVERSE_BASES[:10],
    }

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workloads": {},
    }

    for name, syms in workloads.items():
        print(f"\n>>> Đang đo benchmark: {name} ({len(syms)} symbols: {syms})...")
        runs = []
        for i in range(3):
            print(f"  Lần chạy {i+1}/3...")
            run_data = run_single_benchmark(syms)
            runs.append(run_data)
            print(f"    Total latency: {run_data['total_latency_ms']:.2f} ms | VmHWM: {run_data['mem_after'].get('VmHWM')}")

        latencies = [r["total_latency_ms"] for r in runs]
        compile_times = [r["stage_compile_ms"] for r in runs]
        data_times = [r["stage_data_ms"] for r in runs]
        engine_times = [r["total_run_ms"] for r in runs]

        report["workloads"][name] = {
            "symbols": syms,
            "repeats": 3,
            "latency_ms": {
                "min": round(min(latencies), 2),
                "median": round(statistics.median(latencies), 2),
                "max": round(max(latencies), 2),
            },
            "stage_compile_ms_median": round(statistics.median(compile_times), 2),
            "stage_data_ms_median": round(statistics.median(data_times), 2),
            "stage_engine_ms_median": round(statistics.median(engine_times), 2),
            "peak_memory": runs[-1]["mem_after"],
            "accounting_sanity": {
                "trades": runs[0]["trades_count"],
                "ret_pct": runs[0]["ret_pct"],
            }
        }

    out_file = Path("nora/check/staged_performance_baseline_20261029.json")
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[DONE] Đã lưu baseline hiệu năng vào: {out_file}")

if __name__ == "__main__":
    main()
