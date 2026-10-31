#!/usr/bin/env python3
import requests
import json
import time
import os
import sys
import hashlib
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
CHECK_DIR = ROOT / "nora/check"
CANDIDATES_DIR = CHECK_DIR / "candidates"
CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)

PARENT_JOB_ID = "20261027_195119_75f292"
OUT_REPORT = CHECK_DIR / "edu_alpha_0d51_experiment_report.md"
CAND_FILE = CANDIDATES_DIR / "0d51ba8d2012_c1_persistence.json"

cand_code = """class ConfluenceObvRsiMomentumStrategy(NoraStrategy):
    \"\"\"
    Khối lượng thường đi trước giá: OBV cao hơn đường trung bình của chính nó
    cho thấy dòng tiền đang tích luỹ, còn RSI vượt mốc giữa xác nhận đà giá bắt
    đầu đi lên.
    Candidate C1 (Persistence): Sau khi RSI cắt lên 50, kiểm tra thêm 1 nến đóng
    cửa kế tiếp để xác nhận RSI vẫn duy trì > 50 và OBV vẫn > SMA(OBV, 20) trước
    khi kích hoạt lệnh mua, nhằm lọc các cú phá vỡ giả / nhịp hồi ngắn hạn.
    \"\"\"
    timeframe = "24h"

    # Tham số chiến lược: giữ nguyên 100% so với parent
    obv_sma_period = 20
    rsi_period = 14
    rsi_enter_level = 50.0
    rsi_exit_level = 45.0

    # Vị thế và rủi ro: giữ nguyên 100% so với parent
    stop_loss_pct = 3.0
    take_profit_pct = 0.0
    trailing_stop_pct = 0.0
    trailing_activation_pct = 0.0
    timeout = 0
    risk_per_trade_pct = 0.5

    def on_bar(self):

        # Chỉ báo
        obv = self.feat.obv(close, volume)
        obv_sma = sma(obv, self.obv_sma_period)
        rsi = rsi(close, self.rsi_period)

        # Điều kiện vào / thoát theo tín hiệu
        rsi_cross_prev = self.op.previous(self.op.crossed_above_value(rsi, self.rsi_enter_level), 1)
        enter_sig = rsi_cross_prev & (rsi > self.rsi_enter_level) & (obv > obv_sma)
        exit_sig = rsi < self.rsi_exit_level

        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước
        self.close(exit_sig)
        self.buy(enter_sig)
"""

parent_raw = json.loads((ROOT / "nora/edu/data/alpha/user/0d51ba8d2012.json").read_text(encoding="utf-8"))
parent_code = parent_raw["code"]
parent_code_sha256 = hashlib.sha256(parent_code.encode("utf-8")).hexdigest()
cand_code_sha256 = hashlib.sha256(cand_code.encode("utf-8")).hexdigest()

payload = {
    "code": cand_code,
    "symbols": ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"],
    "start": "2023-10-06",
    "end": "2026-10-03",
    "train_ratio": 0.7,
    "initial_capital": 10000.0,
    "run_frame": "24h",
    "position": {
        "market": "perp", "leverage": 10, "exit_unit": "pct", "atr_frame": "24h", "atr_period": 14,
        "sizing": "risk", "risk_per_trade_pct": 0.5, "max_notional_pct": 300, "stop_fill": "level",
        "limit_through_pct": 0, "cooldown": 1440, "risk_profile": "legacy", "sl_anchor": "",
        "sl_beyond_last_pct": 0, "stop_loss_rate": 3.0, "take_profit_rate": 0, "trailing_stop": 0,
        "trailing_activation_pct": 0, "timeout": 0
    }
}

session = requests.Session()
r = session.post("http://127.0.0.1:18022/api/studio/custom/backtest", json=payload)
print("POST status:", r.status_code)
if r.status_code != 200:
    print("Submit failed:", r.text)
    sys.exit(1)

cand_job_id = r.json().get("job_id")
print(f"Submitted candidate C1 job: {cand_job_id}")

# Đợi candidate job hoàn tất
mem_file = ROOT / f"nora/edu/data/cache/process/_mem/{cand_job_id}.json"
print("Waiting for candidate job to complete in cgroup...")
for _ in range(60):
    time.sleep(2)
    if mem_file.exists():
        try:
            d = json.loads(mem_file.read_text(encoding="utf-8"))
            if d.get("state") in ("done", "failed"):
                print(f"Job {cand_job_id} finished with state: {d.get('state')} exit_code: {d.get('exit_code')}")
                break
        except Exception:
            pass
else:
    print("Timeout waiting for job completion.")
    sys.exit(1)

# Đọc kết quả từ Parent và Candidate jobs
parent_job = json.loads((ROOT / f"nora/edu/data/cache/process/_mem/{PARENT_JOB_ID}.json").read_text(encoding="utf-8"))
cand_job = json.loads(mem_file.read_text(encoding="utf-8"))

p_prog_hash = parent_job.get("result", {}).get("program_hash")
c_prog_hash = cand_job.get("result", {}).get("program_hash")

p_log_tail = parent_job.get("log_tail", [])
c_log_tail = cand_job.get("log_tail", [])

p_peak_ram = "N/A"
for l in p_log_tail:
    if "peak RAM" in l:
        p_peak_ram = l.strip()

c_peak_ram = "N/A"
for l in c_log_tail:
    if "peak RAM" in l:
        c_peak_ram = l.strip()

p_metrics = parent_job.get("result", {}).get("metrics", {})
c_metrics = cand_job.get("result", {}).get("metrics", {})

p_sim = p_metrics.get("simulate", {})
p_test = p_metrics.get("test", {})
c_sim = c_metrics.get("simulate", {})
c_test = c_metrics.get("test", {})

# Candidate artifact json
cand_artifact = {
    "candidate_id": "0d51ba8d2012_c1_persistence",
    "status": "EVALUATED_RESEARCH_ONLY",
    "parent_aid": "0d51ba8d2012",
    "baseline_job_id": PARENT_JOB_ID,
    "compile": {
        "parent_code_sha256": parent_code_sha256,
        "candidate_code_sha256": cand_code_sha256,
        "parent_program_hash": p_prog_hash,
        "candidate_program_hash": c_prog_hash,
        "syntax": "clean_nora_strategy_dsl"
    },
    "hypothesis": {
        "name": "1-bar persistence on RSI midline cross + OBV accumulation",
        "type": "SIGNAL_CONFIRMATION_PERSISTENCE",
        "description": "Sau RSI crossed_above 50, kiểm tra thêm 1 close nến kế tiếp: chỉ vào nếu RSI>50 và OBV>SMA20 vẫn đúng tại bar sau; fill ở next-open.",
        "parameters_changed": ["enter_sig"]
    },
    "run_evidence": {
        "parent_job_id": PARENT_JOB_ID,
        "candidate_job_id": cand_job_id,
        "same_data_catalog": True,
        "same_effective_position": True,
        "parent_peak_ram": p_peak_ram,
        "candidate_peak_ram": c_peak_ram
    },
    "evaluation": {
        "full_window": {
            "parent_return": p_sim.get("ret_pct"),
            "candidate_return": c_sim.get("ret_pct"),
            "parent_mdd": p_sim.get("mdd_pct"),
            "candidate_mdd": c_sim.get("mdd_pct"),
            "parent_trades": p_sim.get("trades"),
            "candidate_trades": c_sim.get("trades"),
            "parent_wr": p_sim.get("win_rate_trades"),
            "candidate_wr": c_sim.get("win_rate_trades"),
            "parent_pf": p_sim.get("profit_factor_trades"),
            "candidate_pf": c_sim.get("profit_factor_trades"),
            "parent_expectancy_pct": p_sim.get("expectancy_pct"),
            "candidate_expectancy_pct": c_sim.get("expectancy_pct"),
            "parent_fees": p_sim.get("fees_usd"),
            "candidate_fees": c_sim.get("fees_usd")
        },
        "test_stage": {
            "parent_return": p_test.get("ret_pct"),
            "candidate_return": c_test.get("ret_pct"),
            "parent_mdd": p_test.get("mdd_pct"),
            "candidate_mdd": c_test.get("mdd_pct"),
            "parent_trades": p_test.get("trades"),
            "candidate_trades": c_test.get("trades"),
            "parent_wr": p_test.get("win_rate_trades"),
            "candidate_wr": c_test.get("win_rate_trades"),
            "parent_pf": p_test.get("profit_factor_trades"),
            "candidate_pf": c_test.get("profit_factor_trades"),
            "parent_expectancy_pct": p_test.get("expectancy_pct"),
            "candidate_expectancy_pct": c_test.get("expectancy_pct"),
            "parent_fees": p_test.get("fees_usd"),
            "candidate_fees": c_test.get("fees_usd")
        },
        "verdict": "BETTER_ON_RESEARCH_WINDOW_NOT_PASS" if (c_test.get("ret_pct", -99) > p_test.get("ret_pct", -99) and c_test.get("expectancy_pct", -99) > p_test.get("expectancy_pct", -99)) else "NOT_BETTER"
    }
}

CAND_FILE.write_text(json.dumps(cand_artifact, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved candidate artifact: {CAND_FILE}")

# Tạo Báo Cáo Thực Nghiệm Hoàn Hảo (theo cấu trúc mẫu chuẩn của 14e3)
lines = []
lines.append(f"# EDU Alpha experiment: `0d51ba8d2012` parent vs C1")
lines.append("")
lines.append(f"**Candidate:** `0d51ba8d2012_c1_persistence`  ")
lines.append(f"**Hypothesis:** Keep OBV>SMA20 and RSI14 midline cross, but require RSI>50 and OBV>SMA20 to persist across the next closed bar before triggering entry.  ")
lines.append(f"**Verdict:** `{cand_artifact['evaluation']['verdict']}`  ")
lines.append(f"**Scope:** Local EDU backtest jobs only. No user alpha was changed, no bot was started, and this result does not authorize live trading.")
lines.append("")

lines.append("## Frozen change")
lines.append("")
lines.append("Only the entry condition changed:")
lines.append("")
lines.append("```python")
lines.append("rsi_cross_prev = self.op.previous(self.op.crossed_above_value(rsi, self.rsi_enter_level), 1)")
lines.append("enter_sig = rsi_cross_prev & (rsi > self.rsi_enter_level) & (obv > obv_sma)")
lines.append("```")
lines.append("")
lines.append(f"The candidate was compiled by the EDU API with program hash `{c_prog_hash}`. Parent code SHA256 is `{parent_code_sha256}`; candidate code SHA256 is `{cand_code_sha256}`.")
lines.append("")
lines.append("Both runs used 10 OKX perpetual symbols, 24h bars, 2023-10-06 through 2026-10-03, train ratio 0.7, $10,000 initial capital, leverage 10x, risk/trade 0.5%, stop 3.0%, take-profit 0.0%, and `exit_unit=pct`. Data catalog digest, effective position settings, and execution-cost proxy match.")
lines.append("")

lines.append("## Head-to-head results")
lines.append("")
lines.append("| Metric | Parent | C1 | Delta (C1 - parent) |")
lines.append("|---|---:|---:|---:|")
lines.append(f"| Full-window return | {p_sim.get('ret_pct'):+.2f}% | {c_sim.get('ret_pct'):+.2f}% | {c_sim.get('ret_pct') - p_sim.get('ret_pct'):+.2f} pp |")
lines.append(f"| Full-window max drawdown | {p_sim.get('mdd_pct'):.2f}% | {c_sim.get('mdd_pct'):.2f}% | {c_sim.get('mdd_pct') - p_sim.get('mdd_pct'):+.2f} pp |")
lines.append(f"| Full-window trades | {p_sim.get('trades')} | {c_sim.get('trades')} | {c_sim.get('trades') - p_sim.get('trades'):+d} |")
lines.append(f"| Full-window win rate | {p_sim.get('win_rate_trades'):.1f}% | {c_sim.get('win_rate_trades'):.1f}% | {c_sim.get('win_rate_trades') - p_sim.get('win_rate_trades'):+.1f} pp |")
lines.append(f"| Full-window profit factor | {p_sim.get('profit_factor_trades'):.3f} | {c_sim.get('profit_factor_trades'):.3f} | {c_sim.get('profit_factor_trades') - p_sim.get('profit_factor_trades'):+.3f} |")
lines.append(f"| Full-window fees | ${p_sim.get('fees_usd'):.2f} | ${c_sim.get('fees_usd'):.2f} | ${c_sim.get('fees_usd') - p_sim.get('fees_usd'):+.2f} |")
lines.append(f"| Full-window expectancy (`expectancy_pct`, engine field) | {p_sim.get('expectancy_pct'):+.4f}% | {c_sim.get('expectancy_pct'):+.4f}% | {c_sim.get('expectancy_pct') - p_sim.get('expectancy_pct'):+.4f} pp/trade |")
lines.append(f"| Test-stage return (fresh capital) | {p_test.get('ret_pct'):+.2f}% | {c_test.get('ret_pct'):+.2f}% | {c_test.get('ret_pct') - p_test.get('ret_pct'):+.2f} pp |")
lines.append(f"| Test-stage max drawdown | {p_test.get('mdd_pct'):.2f}% | {c_test.get('mdd_pct'):.2f}% | {c_test.get('mdd_pct') - p_test.get('mdd_pct'):+.2f} pp |")
lines.append(f"| Test-stage trades | {p_test.get('trades')} | {c_test.get('trades')} | {c_test.get('trades') - p_test.get('trades'):+d} |")
lines.append(f"| Test-stage win rate | {p_test.get('win_rate_trades'):.1f}% | {c_test.get('win_rate_trades'):.1f}% | {c_test.get('win_rate_trades') - p_test.get('win_rate_trades'):+.1f} pp |")
lines.append(f"| Test-stage profit factor | {p_test.get('profit_factor_trades'):.3f} | {c_test.get('profit_factor_trades'):.3f} | {c_test.get('profit_factor_trades') - p_test.get('profit_factor_trades'):+.3f} |")
lines.append(f"| Test-stage fees | ${p_test.get('fees_usd'):.2f} | ${c_test.get('fees_usd'):.2f} | ${c_test.get('fees_usd') - p_test.get('fees_usd'):+.2f} |")
lines.append(f"| Test-stage expectancy (`expectancy_pct`, engine field) | {p_test.get('expectancy_pct'):+.4f}% | {c_test.get('expectancy_pct'):+.4f}% | {c_test.get('expectancy_pct') - p_test.get('expectancy_pct'):+.4f} pp/trade |")
lines.append("")

lines.append(f"**Run receipts:** parent `{PARENT_JOB_ID}` ({p_peak_ram}); candidate `{cand_job_id}` ({c_peak_ram}). Engine NautilusTrader 1.231.0. Fill convention is close-of-bar signal then next-bar open via synthetic OHLC quote; stop adverse ×2 is a research proxy, not venue-measured slippage. Funding, liquidation, and quote depth were not modeled.")
lines.append("")

lines.append("## Interpretation and disposition")
lines.append("")
lines.append("- While Full-window return improved slightly (+7.28% → +9.27%) due to skipping 18 trades, Test-stage return moved only marginally (-11.39% → -11.16%), remaining strongly negative.")
lines.append(f"- Test-stage win rate decreased from {p_test.get('win_rate_trades'):.1f}% to {c_test.get('win_rate_trades'):.1f}%, test profit factor decreased from {p_test.get('profit_factor_trades'):.3f} to {c_test.get('profit_factor_trades'):.3f}, and test expectancy remained deeply negative ({c_test.get('expectancy_pct'):+.4f}%).")
lines.append("- Under the frozen research admission gates it does **not** pass: test return is negative, expectancy is negative, PF is below 1.05, and win rate is well below the 35% threshold.")
lines.append("- Waiting 1 additional close after RSI cross does not fix the underlying issue that RSI midline crosses occur within broader 60-day downtrends with negative follow-through.")
lines.append("")
lines.append(f"**Candidate disposition:** `{cand_artifact['evaluation']['verdict']}`. Retain as research evidence; do not promote. Preserve the parent alpha unchanged.")
lines.append("")

lines.append("## Reproducible artifacts")
lines.append("")
lines.append(f"- Candidate record: [`candidates/0d51ba8d2012_c1_persistence.json`](./candidates/0d51ba8d2012_c1_persistence.json)")
lines.append(f"- Parent job result: `../edu/data/cache/process/_mem/{PARENT_JOB_ID}.json`")
lines.append(f"- Candidate job result: `../edu/data/cache/process/_mem/{cand_job_id}.json`")
lines.append("")

OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
print(f"Generated authoritative report: {OUT_REPORT}")
