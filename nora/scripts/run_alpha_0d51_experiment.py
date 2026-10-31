#!/usr/bin/env python3
"""
scripts/run_alpha_0d51_experiment.py
Thực thi quy trình thực nghiệm độc lập cho Alpha #1: 0d51ba8d2012
(OBV Volume Accumulation + RSI Momentum)
1. Đóng băng mã băm parent.
2. Tạo candidate 0d51ba8d2012_c1_persistence (chỉ đổi 1 giả thuyết: persistence 1 close).
3. Chạy backtest cho candidate bằng run_custom trên cùng contract engine.
4. Đối soát số học toàn diện Parent vs Candidate.
5. Xuất báo cáo thực nghiệm nora/check/edu_alpha_0d51_experiment_report.md.
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
EDU_DIR = ROOT / "nora/edu"
CHECK_DIR = ROOT / "nora/check"
CANDIDATE_DIR = CHECK_DIR / "candidates"
CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(EDU_DIR))
os.environ["NORA_DATA_ROOT"] = str(EDU_DIR / "data")

from backend.jobs.tasks import run_custom
from backend.analys.alpha.code.compile import compile_code

PARENT_PATH = EDU_DIR / "data/alpha/user/0d51ba8d2012.json"
OUT_REPORT = CHECK_DIR / "edu_alpha_0d51_experiment_report.md"
OUT_CANDIDATE_JSON = CANDIDATE_DIR / "0d51ba8d2012_c1_persistence.json"

def main():
    print("=" * 80)
    print("BẮT ĐẦU THỰC NGHIỆM ĐỘC LẬP: ALPHA 0d51ba8d2012 (PARENT VS CANDIDATE C1)")
    print("=" * 80)

    # 1. Đóng băng Parent
    parent_raw = json.loads(PARENT_PATH.read_text(encoding="utf-8"))
    parent_code = parent_raw["code"]
    parent_cfg = parent_raw["config"]
    parent_code_sha256 = hashlib.sha256(parent_code.encode("utf-8")).hexdigest()
    
    print(f"[PARENT] ID: 0d51ba8d2012 | Name: {parent_raw.get('name')}")
    print(f"[PARENT] Code SHA256: {parent_code_sha256}")
    print(f"[PARENT] Config Program Hash: {parent_raw.get('program_hash')}")

    # 2. Xây dựng Candidate C1 với giả thuyết đơn biến: Persistence thêm 1 close
    candidate_code = """class ConfluenceObvRsiMomentumStrategy(NoraStrategy):
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

        # Điều kiện vào / thoát lệnh:
        # C1 biến đổi: yêu cầu sự kiện cross đã xảy ra ở bar trước đó VÀ tại bar hiện tại
        # RSI vẫn giữ trên 50 đồng thời OBV vẫn giữ trên đường SMA20 (xác nhận persistence 1 bar).
        rsi_cross_prev = self.op.previous(self.op.crossed_above_value(rsi, self.rsi_enter_level), 1)
        enter_sig = rsi_cross_prev & (rsi > self.rsi_enter_level) & (obv > obv_sma)
        exit_sig = rsi < self.rsi_exit_level

        # Vị thế: 0 = không giữ, 1 = LONG; lệnh gọi sau ghi đè lệnh trước
        self.close(exit_sig)
        self.buy(enter_sig)
"""
    # Kiểm tra biên dịch AST của candidate
    try:
        prog = compile_code(candidate_code)
        meta_dict = prog.meta() if callable(getattr(prog, "meta", None)) else getattr(prog, "meta", {})
        cand_program_hash = meta_dict.get("code_hash", "")[:12] if isinstance(meta_dict, dict) else hashlib.sha256(candidate_code.encode("utf-8")).hexdigest()[:12]
        print(f"[CANDIDATE] Biên dịch AST thành công. Program hash: {cand_program_hash}")
    except Exception as e:
        print(f"[ERROR] Candidate AST compile failed: {e}")
        return

    candidate_payload = {
        "candidate_id": "0d51ba8d2012_c1_persistence",
        "parent_aid": "0d51ba8d2012",
        "parent_code_sha256": parent_code_sha256,
        "name": "OBV Volume Accumulation + RSI Momentum (1-Bar Persistence)",
        "hypothesis_type": "SIGNAL_CONFIRMATION_PERSISTENCE",
        "hypothesis_description": "Yêu cầu RSI>50 và OBV>SMA20 duy trì thêm 1 nến đóng cửa trước khi vào lệnh để lọc nhịp hồi ngắn hạn và false midline crosses.",
        "diff_summary": "Thay đổi enter_sig từ rsi_cross trực tiếp thành: rsi_cross_prev & (rsi > 50) & (obv > obv_sma). Giữ nguyên toàn bộ exits, SL 3%, risk 0.5%, universe, fees.",
        "code": candidate_code,
        "config": parent_cfg,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    OUT_CANDIDATE_JSON.write_text(json.dumps(candidate_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Đã lưu candidate artifact: {OUT_CANDIDATE_JSON}")

    # 3. Chạy Backtest Parent
    print("\n--- Đang chạy backtest Parent 0d51ba8d2012 ---")
    parent_params = {
        "code": parent_code,
        "symbols": parent_cfg.get("symbols", ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"]),
        "start": parent_cfg.get("start", "2023-10-06"),
        "end": parent_cfg.get("end", "2026-10-03"),
        "run_frame": parent_cfg.get("run_frame", "24h"),
        "train_ratio": 0.7,
        "initial_capital": 10000.0,
        "position": parent_cfg.get("position", {})
    }
    t0 = time.time()
    parent_res = run_custom(parent_params)
    print(f"Parent backtest hoàn tất trong {time.time() - t0:.2f}s")

    # 4. Chạy Backtest Candidate
    print("\n--- Đang chạy backtest Candidate 0d51ba8d2012_c1_persistence ---")
    candidate_params = {
        "code": candidate_code,
        "symbols": parent_cfg.get("symbols", ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX"]),
        "start": parent_cfg.get("start", "2023-10-06"),
        "end": parent_cfg.get("end", "2026-10-03"),
        "run_frame": parent_cfg.get("run_frame", "24h"),
        "train_ratio": 0.7,
        "initial_capital": 10000.0,
        "position": parent_cfg.get("position", {})
    }
    t0 = time.time()
    cand_res = run_custom(candidate_params)
    print(f"Candidate backtest hoàn tất trong {time.time() - t0:.2f}s")

    # 5. Trích xuất Metrics và So Sánh Số Học
    p_sim = parent_res.get("metrics", {}).get("simulate", {})
    p_train = parent_res.get("metrics", {}).get("train", {})
    p_test = parent_res.get("metrics", {}).get("test", {})
    p_diag = parent_res.get("diagnostics", {}).get("pnl_structure", {})

    c_sim = cand_res.get("metrics", {}).get("simulate", {})
    c_train = cand_res.get("metrics", {}).get("train", {})
    c_test = cand_res.get("metrics", {}).get("test", {})
    c_diag = cand_res.get("diagnostics", {}).get("pnl_structure", {})

    # Full Window numbers
    p_full_ret = float(p_sim.get("ret_pct", 0.0))
    p_full_mdd = float(p_sim.get("mdd_pct", 0.0))
    p_full_trades = int(p_sim.get("trades", 0))
    p_full_wr = float(p_sim.get("win_rate", 0.0))
    p_full_pf = float(p_sim.get("profit_factor", 0.0))
    p_full_fees = float(p_sim.get("fees_usd", 0.0))
    p_full_net_pnl = float(p_diag.get("net_pnl_usd", 0.0) or round(10000.0 * (p_full_ret / 100.0), 2))
    p_full_gross_pnl = round(p_full_net_pnl + p_full_fees, 2)
    p_full_expectancy = round(p_full_net_pnl / p_full_trades, 2) if p_full_trades > 0 else 0.0

    c_full_ret = float(c_sim.get("ret_pct", 0.0))
    c_full_mdd = float(c_sim.get("mdd_pct", 0.0))
    c_full_trades = int(c_sim.get("trades", 0))
    c_full_wr = float(c_sim.get("win_rate", 0.0))
    c_full_pf = float(c_sim.get("profit_factor", 0.0))
    c_full_fees = float(c_sim.get("fees_usd", 0.0))
    c_full_net_pnl = float(c_diag.get("net_pnl_usd", 0.0) or round(10000.0 * (c_full_ret / 100.0), 2))
    c_full_gross_pnl = round(c_full_net_pnl + c_full_fees, 2)
    c_full_expectancy = round(c_full_net_pnl / c_full_trades, 2) if c_full_trades > 0 else 0.0

    # OOS Stage numbers
    p_oos_ret = float(p_test.get("ret_pct", 0.0))
    p_oos_mdd = float(p_test.get("mdd_pct", 0.0))
    p_oos_trades = int(p_test.get("trades", 0))
    p_oos_wr = float(p_test.get("win_rate_trades", 0.0))
    p_oos_pf = float(p_test.get("profit_factor_trades", 0.0))
    p_oos_fees = float(p_test.get("fees_usd", 0.0))
    p_oos_net_pnl = round(10000.0 * (p_oos_ret / 100.0), 2)
    p_oos_gross_pnl = round(p_oos_net_pnl + p_oos_fees, 2)
    p_oos_expectancy = round(p_oos_net_pnl / p_oos_trades, 2) if p_oos_trades > 0 else 0.0

    c_oos_ret = float(c_test.get("ret_pct", 0.0))
    c_oos_mdd = float(c_test.get("mdd_pct", 0.0))
    c_oos_trades = int(c_test.get("trades", 0))
    c_oos_wr = float(c_test.get("win_rate_trades", 0.0))
    c_oos_pf = float(c_test.get("profit_factor_trades", 0.0))
    c_oos_fees = float(c_test.get("fees_usd", 0.0))
    c_oos_net_pnl = round(10000.0 * (c_oos_ret / 100.0), 2)
    c_oos_gross_pnl = round(c_oos_net_pnl + c_oos_fees, 2)
    c_oos_expectancy = round(c_oos_net_pnl / c_oos_trades, 2) if c_oos_trades > 0 else 0.0

    # Trade counts and stop analysis
    p_trades_list = parent_res.get("trades", [])
    c_trades_list = cand_res.get("trades", [])

    p_stops = sum(1 for t in p_trades_list if "Stop-loss" in t.get("close_reason", ""))
    c_stops = sum(1 for t in c_trades_list if "Stop-loss" in t.get("close_reason", ""))

    # Đánh giá Verdict
    if c_oos_trades < 20:
        verdict = "INSUFFICIENT_SAMPLE"
        verdict_summary = "Số lượng giao dịch OOS của candidate < 20 lệnh. Mẫu không đủ để kết luận."
    elif c_oos_ret > p_oos_ret and c_oos_expectancy > p_oos_expectancy:
        verdict = "BETTER_ON_RESEARCH_WINDOW"
        verdict_summary = f"Candidate cải thiện hiệu suất trên cửa sổ nghiên cứu (OOS Ret: {c_oos_ret:+.2f}% vs {p_oos_ret:+.2f}%, Expectancy: ${c_oos_expectancy:.2f} vs ${p_oos_expectancy:.2f})."
    else:
        verdict = "NOT_BETTER"
        verdict_summary = f"Candidate không cải thiện hiệu suất ngoài mẫu (OOS Ret: {c_oos_ret:+.2f}% vs {p_oos_ret:+.2f}%, Expectancy: ${c_oos_expectancy:.2f} vs ${p_oos_expectancy:.2f})."

    print(f"\n[VERDICT ĐẠT ĐƯỢC]: {verdict}")
    print(f"[TÓM TẮT]: {verdict_summary}")

    # 6. Xuất Báo Cáo Markdown
    lines = []
    lines.append(f"# BÁO CÁO THỰC NGHIỆM ĐỘC LẬP: ALPHA 0d51ba8d2012 (PARENT VS CANDIDATE C1)")
    lines.append("")
    lines.append(f"**Mã chiến lược:** `0d51ba8d2012` | **Tên:** OBV Volume Accumulation + RSI Momentum  ")
    lines.append(f"**Candidate:** `0d51ba8d2012_c1_persistence` | **Giả thuyết:** 1-Bar Persistence Confirmation  ")
    lines.append(f"**Thời điểm chạy:** `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`  ")
    lines.append(f"**Môi trường thực thi:** Engine `NautilusTrader 1.231.0` | Port 18022 | Cgroup cap: `nora.slice` (RAM 2GB/job)  ")
    lines.append(f"**Verdict nghiên cứu:** **`{verdict}`**  ")
    lines.append("")

    lines.append("---")
    lines.append("## 1. MÔ TẢ GIẢ THUYẾT VÀ NGUYÊN TẮC CÔ LẬP ĐƠN BIẾN")
    lines.append("")
    lines.append("- **Vấn đề của Parent:** Trong baseline OOS, parent lỗ `-11.39%` (159 lệnh, PF 0.283, MDD 24.63%). 126/158 lệnh full-run trong ngày OOS bị dính stop-loss. Phân tích nến cho thấy RSI cắt lên 50 thường xảy ra trong các nhịp hồi ngắn hạn của xu hướng giảm 60 ngày, thiếu lực tiếp diễn.")
    lines.append("- **Giả thuyết Candidate C1:** Yêu cầu RSI>50 và OBV>SMA20 duy trì thêm 1 nến đóng cửa trước khi kích hoạt lệnh mua:")
    lines.append("  ```python")
    lines.append("  rsi_cross_prev = self.op.previous(self.op.crossed_above_value(rsi, self.rsi_enter_level), 1)")
    lines.append("  enter_sig = rsi_cross_prev & (rsi > self.rsi_enter_level) & (obv > obv_sma)")
    lines.append("  ```")
    lines.append("- **Biến số kiểm soát (Không đổi 100%):** Universe (10 cặp OKX perp), Khung 24h, Vốn 10.000 USD, Cửa sổ (2023-10-06 đến 2026-10-03, train_ratio 0.7), Stop-loss 3.0% (`exit_unit=pct`), Risk/trade 0.5%, Leverage 10x, cấu trúc phí và proxy khớp lệnh.")
    lines.append("")

    lines.append("---")
    lines.append("## 2. BẢNG ĐỐI SOÁT CHỈ SỐ HEAD-TO-HEAD (PARENT VS CANDIDATE C1)")
    lines.append("")
    lines.append("| Chỉ số đo lường | Parent (`0d51ba8d2012`) | Candidate C1 (`c1_persistence`) | Chênh lệch (Delta) | Ý nghĩa thực nghiệm |")
    lines.append("|---|---:|---:|---:|---|")
    lines.append(f"| **Full-Window Net Return (%)** | **{p_full_ret:+.2f}%** | **{c_full_ret:+.2f}%** | {c_full_ret - p_full_ret:+.2f}% | Lợi nhuận ròng toàn kỳ |")
    lines.append(f"| Full-Window Net PnL ($) | ${p_full_net_pnl:+.1f} | ${c_full_net_pnl:+.1f} | ${c_full_net_pnl - p_full_net_pnl:+.1f} | PnL ròng sau phí sàn |")
    lines.append(f"| Full-Window Gross PnL ($) | ${p_full_gross_pnl:+.1f} | ${c_full_gross_pnl:+.1f} | ${c_full_gross_pnl - p_full_gross_pnl:+.1f} | PnL gộp hoàn phí |")
    lines.append(f"| Full-Window Fees ($) | ${p_full_fees:.1f} | ${c_full_fees:.1f} | ${c_full_fees - p_full_fees:+.1f} | Tổng phí giao dịch trả sàn |")
    lines.append(f"| Full-Window Trades | {p_full_trades} | {c_full_trades} | {c_full_trades - p_full_trades:+d} | Số lượng lệnh được kích hoạt |")
    lines.append(f"| Full-Window Win Rate (%) | {p_full_wr:.1f}% | {c_full_wr:.1f}% | {c_full_wr - p_full_wr:+.1f}% | Tỷ lệ lệnh có lãi |")
    lines.append(f"| Full-Window Profit Factor | {p_full_pf:.3f} | {c_full_pf:.3f} | {c_full_pf - p_full_pf:+.3f} | Hệ số lợi nhuận / thua lỗ |")
    lines.append(f"| Full-Window Max Drawdown (%) | {p_full_mdd:.2f}% | {c_full_mdd:.2f}% | {c_full_mdd - p_full_mdd:+.2f}% | Độ sụt giảm vốn tối đa |")
    lines.append(f"| Full-Window Expectancy ($/trade) | ${p_full_expectancy:.2f} | ${c_full_expectancy:.2f} | ${c_full_expectancy - p_full_expectancy:+.2f} | Kỳ vọng lợi nhuận trên mỗi lệnh |")
    lines.append(f"| Full-Window Stop-loss Hits | {p_stops} ({p_stops/p_full_trades*100:.1f}%) | {c_stops} ({c_stops/c_full_trades*100:.1f}%) | {c_stops - p_stops:+d} | Số lệnh kết thúc bằng cắt lỗ |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| **OOS Test Net Return (%)** | **{p_oos_ret:+.2f}%** | **{c_oos_ret:+.2f}%** | {c_oos_ret - p_oos_ret:+.2f}% | **Hiệu suất ngoài mẫu (OOS Stage)** |")
    lines.append(f"| OOS Net PnL ($) | ${p_oos_net_pnl:+.1f} | ${c_oos_net_pnl:+.1f} | ${c_oos_net_pnl - p_oos_net_pnl:+.1f} | PnL ngoài mẫu sau phí |")
    lines.append(f"| OOS Gross PnL ($) | ${p_oos_gross_pnl:+.1f} | ${c_oos_gross_pnl:+.1f} | ${c_oos_gross_pnl - p_oos_gross_pnl:+.1f} | PnL ngoài mẫu trước phí |")
    lines.append(f"| OOS Fees ($) | ${p_oos_fees:.1f} | ${c_oos_fees:.1f} | ${c_oos_fees - p_oos_fees:+.1f} | Phí giao dịch giai đoạn OOS |")
    lines.append(f"| OOS Trades | {p_oos_trades} | {c_oos_trades} | {c_oos_trades - p_oos_trades:+d} | Số lệnh trong giai đoạn OOS |")
    lines.append(f"| OOS Win Rate (%) | {p_oos_wr:.1f}% | {c_oos_wr:.1f}% | {c_oos_wr - p_oos_wr:+.1f}% | Tỷ lệ thắng OOS |")
    lines.append(f"| OOS Profit Factor | {p_oos_pf:.3f} | {c_oos_pf:.3f} | {c_oos_pf - p_oos_pf:+.3f} | Profit factor OOS |")
    lines.append(f"| OOS Max Drawdown (%) | {p_oos_mdd:.2f}% | {c_oos_mdd:.2f}% | {c_oos_mdd - p_oos_mdd:+.2f}% | Sụt giảm vốn giai đoạn OOS |")
    lines.append(f"| OOS Expectancy ($/trade) | ${p_oos_expectancy:.2f} | ${c_oos_expectancy:.2f} | ${c_oos_expectancy - p_oos_expectancy:+.2f} | Kỳ vọng lợi nhuận OOS trên mỗi trade |")
    lines.append("")

    lines.append("---")
    lines.append("## 3. PHÂN TÍCH BẢN CHẤT KỸ THUẬT VÀ KẾT LUẬN")
    lines.append("")
    lines.append(f"1. **Tác động của bộ lọc Persistence:**")
    reduction_pct = (p_full_trades - c_full_trades) / p_full_trades * 100.0 if p_full_trades > 0 else 0.0
    lines.append(f"   - Việc yêu cầu RSI duy trì trên 50 thêm 1 nến đóng cửa đã làm giảm số lượng giao dịch toàn kỳ từ `{p_full_trades}` xuống `{c_full_trades}` lệnh (giảm `{reduction_pct:.1f}%`).")
    if c_oos_ret > p_oos_ret:
        lines.append(f"   - Hiệu suất OOS có sự cải thiện số học từ `{p_oos_ret:+.2f}%` lên `{c_oos_ret:+.2f}%`.")
    else:
        lines.append(f"   - Tuy nhiên, hiệu suất OOS không cải thiện đáng kể (`{c_oos_ret:+.2f}%` so với `{p_oos_ret:+.2f}%`), cho thấy việc trễ 1 nến không giải quyết được vấn đề xu hướng trung hạn yếu.")
    lines.append(f"2. **Tương tác Phí và Kỳ vọng Lệnh (Expectancy):**")
    lines.append(f"   - Phí sàn giảm tương ứng với số lệnh giảm (từ `${p_full_fees:.1f}` xuống `${c_full_fees:.1f}`).")
    lines.append(f"   - Kỳ vọng lợi nhuận trên mỗi trade OOS thay đổi từ `${p_oos_expectancy:.2f}` thành `${c_oos_expectancy:.2f}`.")
    lines.append(f"3. **Kết luận Nghiên cứu (Verdict):**")
    lines.append(f"   - Verdict được ghi nhận là: **`{verdict}`**.")
    lines.append(f"   - {verdict_summary}")
    lines.append(f"   - **Nguyên tắc an toàn:** Kết quả này chỉ có giá trị thăm dò trên cửa sổ nghiên cứu, **không cấu thành WFA pass, không phải holdout độc lập, và không được phép đưa vào sản xuất (live bot)**. File alpha gốc của người dùng được bảo toàn 100%.")
    lines.append("")

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Đã xuất báo cáo thực nghiệm: {OUT_REPORT}")

if __name__ == "__main__":
    main()
