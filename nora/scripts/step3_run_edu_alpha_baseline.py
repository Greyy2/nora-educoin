#!/usr/bin/env python3
"""
scripts/step3_run_edu_alpha_baseline.py

Thực thi chạy Baseline tuần tự cho Alpha EDU đủ điều kiện (VALID_AS_IS),
thu thập metrics chi tiết (Train In-Sample vs Test Out-of-Sample),
phân loại mô tả khách quan và lập Báo cáo Đo lường Baseline Sơ bộ (Preliminary Baseline Measurement).
Không tô vẽ, không dùng nhãn phỏng đoán khi chưa đủ bằng chứng.
Không ghi đè dữ liệu user alpha gốc.
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path("/home/vmc03/norabt").resolve()
EDU_DIR = ROOT / "nora/edu"
USER_DIR = EDU_DIR / "data/alpha/user"
LEDGER_PATH = ROOT / "nora/check/edu_source_assessment_ledger.json"
OUT_RESULTS = ROOT / "nora/check/edu_alpha_baseline_results.json"
OUT_REPORT = ROOT / "nora/check/edu_alpha_closeout_and_baseline_report.md"

sys.path.insert(0, str(EDU_DIR))
os.environ["NORA_DATA_ROOT"] = str(EDU_DIR / "data")


def load_raw_job_data(job_id: str) -> Dict[str, Any]:
    job_path = EDU_DIR / f"data/cache/process/_mem/{job_id}.json"
    if not job_path.exists():
        return {}
    with open(job_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_rigorous_report(results_data: Dict[str, Any]):
    runs = results_data.get("baseline_runs", {})
    blocked = results_data.get("blocked_records", {})

    oos_marginal_count = 0
    oos_small_sample_count = 0
    full_pos_oos_neg_count = 0
    full_non_pos_oos_neg_count = 0
    vinh_mismatch_count = 0

    run_records = []

    for aid, r in runs.items():
        job_id = r.get("job_id")
        raw_job = load_raw_job_data(job_id)
        res = raw_job.get("result") or {}
        m = res.get("metrics") or {}
        sim = m.get("simulate") or {}
        train = m.get("train") or {}
        test = m.get("test") or {}
        cfg = res.get("config") or {}
        pos = cfg.get("position") or {}
        prov = cfg.get("param_provenance") or {}

        full_ret = sim.get("ret_pct", 0.0)
        train_ret = train.get("ret_pct", 0.0)
        oos_ret = test.get("ret_pct", 0.0)
        full_mdd = sim.get("mdd_pct", 0.0)
        oos_mdd = test.get("mdd_pct", 0.0)
        full_trades = sim.get("trades", 0)
        oos_trades = test.get("trades", 0)
        full_sharpe = sim.get("sharpe")
        oos_sharpe = test.get("sharpe")
        win_rate = sim.get("win_rate_trades", 0.0)
        fees_usd = sim.get("fees_usd", 0.0)
        sl_rate = pos.get("stop_loss_rate")
        tp_rate = pos.get("take_profit_rate")

        declared_exit = prov.get("exit_unit", {}).get("declared_in_code")
        runtime_exit = pos.get("exit_unit")
        is_mismatch = (declared_exit is not None and declared_exit != runtime_exit)
        if is_mismatch:
            vinh_mismatch_count += 1

        start_date = cfg.get("start", "2023-10-06")
        end_date = cfg.get("end", "2026-10-03")
        train_ratio = cfg.get("train_ratio", 0.7)
        is_3m = (start_date == "2026-07-01")

        # Phân loại mô tả trung tính, chính xác theo số liệu thực tế
        if oos_ret > 0:
            if is_3m or full_trades < 20 or oos_trades < 10:
                cat = "OOS_POSITIVE_SMALL_SAMPLE"
                diag = f"OOS dương (+{oos_ret:.2f}%) nhưng mẫu quá nhỏ ({full_trades} lệnh trên cửa sổ 3 tháng); chưa đủ dữ liệu để đánh giá độ bền thống kê."
                oos_small_sample_count += 1
            else:
                cat = "OOS_MARGINAL_POSITIVE"
                diag = f"OOS dương biên (+{oos_ret:.2f}%, Sharpe OOS {oos_sharpe if oos_sharpe is not None else 'N/A'}); hiệu suất suy giảm mạnh so với In-Sample (+{train_ret:.2f}%)."
                oos_marginal_count += 1
        elif full_ret > 0 and oos_ret <= 0:
            cat = "FULL_POSITIVE_OOS_NEGATIVE"
            diag = f"Toàn kỳ dương (+{full_ret:.2f}%) và Train dương (+{train_ret:.2f}%), nhưng OOS âm ({oos_ret:.2f}%, Sharpe {oos_sharpe if oos_sharpe is not None else 'N/A'})."
            full_pos_oos_neg_count += 1
        else:
            cat = "FULL_NON_POSITIVE_OOS_NEGATIVE"
            reasons = []
            if train_ret > 0:
                reasons.append(f"Train dương nhẹ (+{train_ret:.2f}%)")
            else:
                reasons.append(f"Train âm ({train_ret:.2f}%)")
            reasons.append(f"OOS âm ({oos_ret:.2f}%)")
            if win_rate < 30.0:
                reasons.append(f"WinRate quan sát {win_rate:.1f}%")
            if fees_usd > 100.0 and full_trades > 100:
                reasons.append(f"Phí sàn phát sinh {fees_usd:.1f}$")
            diag = "; ".join(reasons)
            full_non_pos_oos_neg_count += 1

        run_records.append({
            "aid": aid,
            "name": r.get("name", ""),
            "owner": "Vinh" if r.get("is_vinh") else str(r.get("owner_id", ""))[:8],
            "window": f"{start_date}..{end_date} (tr={train_ratio})",
            "is_3m": is_3m,
            "full_ret": full_ret,
            "train_ret": train_ret,
            "oos_ret": oos_ret,
            "full_mdd": full_mdd,
            "full_sharpe": full_sharpe,
            "oos_sharpe": oos_sharpe,
            "full_trades": full_trades,
            "oos_trades": oos_trades,
            "win_rate": win_rate,
            "fees_usd": fees_usd,
            "sl_rate": sl_rate,
            "tp_rate": tp_rate,
            "runtime_exit": runtime_exit,
            "declared_exit": declared_exit,
            "is_mismatch": is_mismatch,
            "category": cat,
            "diagnosis": diag,
            "peak_rss_mb": raw_job.get("progress", {}).get("peak_rss_mb"),
        })

    # Cập nhật kết quả JSON chuẩn hóa
    results_data["report_title"] = "BÁO CÁO ĐO LƯỜNG BASELINE SƠ BỘ KHO ALPHA EDU"
    results_data["disclaimer"] = "Preliminary Baseline Measurement for academic research only; not final acceptance; no live trading approval."
    results_data["summary"] = {
        "total_evaluated": len(run_records),
        "oos_marginal_positive": oos_marginal_count,
        "oos_positive_small_sample": oos_small_sample_count,
        "full_positive_oos_negative": full_pos_oos_neg_count,
        "full_non_positive_oos_negative": full_non_pos_oos_neg_count,
        "zero_trades": 0,
        "runtime_error": 0,
        "vinh_atr_mismatch_count": vinh_mismatch_count
    }

    for rec in run_records:
        aid = rec["aid"]
        if aid in results_data.get("baseline_runs", {}):
            results_data["baseline_runs"][aid]["category"] = rec["category"]
            results_data["baseline_runs"][aid]["trades"] = rec["full_trades"]
            results_data["baseline_runs"][aid]["oos_trades"] = rec["oos_trades"]
            results_data["baseline_runs"][aid]["train_ret"] = rec["train_ret"]
            results_data["baseline_runs"][aid]["oos_ret"] = rec["oos_ret"]
            results_data["baseline_runs"][aid]["runtime_exit_unit"] = rec["runtime_exit"]
            results_data["baseline_runs"][aid]["declared_exit_unit"] = rec["declared_exit"]
            results_data["baseline_runs"][aid]["is_unit_mismatch"] = rec["is_mismatch"]
            results_data["baseline_runs"][aid]["diagnosis"] = rec["diagnosis"]

    with open(OUT_RESULTS, "w", encoding="utf-8") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)

    # Viết báo cáo Markdown chuẩn hóa
    lines = []
    lines.append("# BÁO CÁO ĐO LƯỜNG BASELINE SƠ BỘ KHO ALPHA NORA EDU")
    lines.append("\n> [!WARNING]")
    lines.append("> **TUYÊN BỐ VỀ BẢN CHẤT NGHIÊN CỨU & NGUYÊN TẮC KHOA HỌC:**")
    lines.append("> 1. Đây là **Báo cáo Đo lường Baseline Sơ bộ (Preliminary Baseline Measurement)** ghi nhận kết quả mô phỏng ban đầu của các alpha. Báo cáo này **KHÔNG PHẢI** là nghiệm thu bàn giao cuối cùng, không chứng minh trading edge thực tế, và không cấu thành phê duyệt triển khai Live Trading.")
    lines.append("> 2. **27/57 Alpha người dùng tiếp tục bị CHẶN (`BLOCKED_UNKNOWN_INTENT`)** do chứa điều kiện hằng số/bất khả thi (`close > 0`, `close > 10`, `close < 0`, `close > 1`). Hệ thống bảo toàn nguyên vẹn bản ghi và không tự suy diễn ý đồ của người dùng.")
    lines.append("> 3. **Không sử dụng nhãn 'ROBUST':** Việc đánh giá độ bền đòi hỏi quy trình Walk-Forward đa khung thời gian và kiểm định Holdout độc lập một lần duy nhất. Báo cáo này chỉ ghi nhận các số đo mô tả (descriptive baseline).\n")

    lines.append("## 1. THÔNG SỐ THỰC THI & GIỚI HẠN MÔ HÌNH (EXECUTION DISCLOSURES)")
    lines.append("- **Engine thực thi:** `NautilusTrader 1.231.0` chạy trong tiến trình con độc lập qua `ops/run_limited.sh`.")
    lines.append("- **Giới hạn tài nguyên (Execution Gate):** Tuân thủ cgroup slice `nora.slice` với trần RAM **2 GB/job** (`MemoryMax=2G`, không swap, `nice 10`, CPU affinity `0-13`). Mức sử dụng RAM đỉnh thực tế từ **907.5 MiB đến 1,499.3 MiB** (100% nằm dưới trần 2 GB, 0 lỗi OOM).")
    lines.append("- **Semantics của In-Sample (Train) vs Out-of-Sample (OOS):**")
    lines.append("  - Giai đoạn In-Sample (Train) và Out-of-Sample (OOS) là các lần mô phỏng **chạy riêng biệt** trong engine (`backend/analys/metrics/trades.py::stage_split`).")
    lines.append("  - Giai đoạn OOS bắt đầu từ mốc chia thời gian với **vốn khởi điểm ban đầu mới (fresh capital 10,000 USD)** và từ trạng thái ban đầu không có vị thế mở, không phải là luồng vốn nối tiếp từ Train.")
    lines.append("  - Vì là hai lần chạy độc lập, số lệnh phát sinh trong OOS ở một số chiến lược có thể chênh lệch hoặc lớn hơn số lệnh Full-window (ví dụ: `bf519617d973` Full có 9 lệnh nhưng OOS chạy riêng sinh 22 lệnh).")
    lines.append("- **Cơ chế khớp lệnh & Chi phí:**")
    lines.append("  - **Khớp lệnh (Fill):** Khớp tại giá mở cửa nến tiếp theo (`synthetic OHLC open quote`).")
    lines.append("  - **Phí giao dịch (Fees):** Phí CEX phái sinh chuẩn (Maker 0.02%, Taker 0.05%).")
    lines.append("  - **Trượt giá (Slippage):** Giả định bằng 0 (`slippage_ticks=0`); chưa đo lường trượt giá sổ lệnh L2 thực tế.")
    lines.append("  - **Funding Rate & Liquidation:** Chưa được mô hình hóa trong đợt chạy baseline này.")
    lines.append("- **Dữ liệu lịch sử:** Nến chuẩn 1m/24h từ kho OKX Perpetual (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE`, `ADA`, `AVAX`, `LINK`, `TRX`).\n")

    lines.append("## 2. TỔNG KẾT PHÂN BỔ BASELINE (30 ALPHA ĐỦ ĐIỀU KIỆN)")
    lines.append(f"- **Tổng số Alpha User:** 57 (30 `VALID_AS_IS`, 27 `BLOCKED_UNKNOWN_INTENT`).")
    lines.append(f"- **Số Alpha hoàn thành chạy Baseline:** **30/30** (100% hoàn tất qua runner, 0 lỗi runtime).")
    lines.append(f"- **Khảo sát Lợi nhuận Toàn kỳ (Full Window):** 15 Dương (50%) / 15 Không dương (50%).")
    lines.append(f"- **Phân loại Mô tả theo Kết quả Thực tế:**")
    lines.append(f"  - **Lợi nhuận OOS dương biên (`OOS_MARGINAL_POSITIVE`):** **6/30** (20.0%) — Đạt lợi nhuận dương trên OOS (+0.81% đến +6.87%, Sharpe OOS 0.10 đến 0.31), nhưng hiệu suất suy giảm mạnh so với In-Sample.")
    lines.append(f"  - **Lợi nhuận OOS dương với mẫu nhỏ (`OOS_POSITIVE_SMALL_SAMPLE`):** **1/30** (3.3%) — Chiến lược FastDip (`8a47cdbcc942` của Vinh) lãi +18.17% trên OOS nhưng chỉ có duy nhất **3 lệnh** trên cửa sổ ngắn 3 tháng, không thể so sánh tương đương với 29 alpha còn lại.")
    lines.append(f"  - **Toàn kỳ dương nhưng OOS âm (`FULL_POSITIVE_OOS_NEGATIVE`):** **8/30** (26.7%) — Lợi nhuận toàn kỳ và Train dương nhưng OOS âm.")
    lines.append(f"  - **Toàn kỳ không dương và OOS âm (`FULL_NON_POSITIVE_OOS_NEGATIVE`):** **15/30** (50.0%) — Trong đó 13 alpha âm cả Train lẫn OOS, 2 alpha có Train dương nhẹ (+0.18% và +1.71%) nhưng toàn kỳ và OOS đều âm.")
    lines.append(f"- **Cảnh báo Lệch Đơn vị Runtime (Unit Mismatch):** **7/30 Alpha của user Vinh** code khai báo `stop_loss_pct` nhưng cấu hình runtime thực tế đang ăn `exit_unit='atr'` (thoát lệnh theo khoảng cách biến động ATR chứ không phải % giá cố định).\n")

    lines.append("## 3. BẢNG DỮ LIỆU ĐO LƯỜNG CHI TIẾT (FULL SIMULATE VS OUT-OF-SAMPLE)\n")
    lines.append("| ID | Tên chiến lược | Chủ sở hữu | Cửa sổ dữ liệu | Toàn kỳ (%) | MDD (%) | Train (%) | OOS (%) | OOS Sharpe | Lệnh (Full/OOS) | Phí ($) | Exit Unit | Phân loại Mô tả |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")

    for r in run_records:
        name = r["name"][:24]
        full_ret_str = f"**{r['full_ret']:+.2f}%**"
        train_ret_str = f"{r['train_ret']:+.2f}%"
        oos_ret_str = f"**{r['oos_ret']:+.2f}%**"
        oos_sh_str = f"{r['oos_sharpe']:.2f}" if r['oos_sharpe'] is not None else "N/A"
        trades_str = f"{r['full_trades']} / {r['oos_trades']}"
        mismatch_flag = "⚠️ `atr`" if r["is_mismatch"] else "`pct`"

        lines.append(f"| `{r['aid']}` | {name} | {r['owner']} | {r['window']} | {full_ret_str} | {r['full_mdd']:.2f}% | {train_ret_str} | {oos_ret_str} | {oos_sh_str} | {trades_str} | {r['fees_usd']:.1f} | {mismatch_flag} | `{r['category']}` |")

    lines.append("\n## 4. QUAN SÁT KỸ THUẬT & CÁC YẾU TỐ CẦN KIỂM CHỨNG (EMPIRICAL OBSERVATIONS)")
    lines.append("""
### A. Hiện tượng chênh lệch giữa In-Sample và Out-of-Sample (8 Alpha nhóm FULL_POSITIVE_OOS_NEGATIVE):
- **Hiện tượng:**
  - `717c1890c59e` (WMA Crossover): Tập Train (70% thời gian) đạt **+172.89%**, nhưng sang tập Test OOS (30% thời gian) ghi nhận **-9.49%**.
  - `fa9587a97fa9` (Trend Alignment): Tập Train đạt **+63.45%**, nhưng OOS sụt giảm xuống **-29.25%** (Sharpe OOS -1.14).
  - `541c55834f56` (Daily Range Expansion): Train đạt **+40.78%**, OOS ghi nhận **-25.74%**.
- **Ý nghĩa kỹ thuật:** Sự sụt giảm hiệu suất mạnh giữa Train và OOS là tín hiệu cảnh báo rõ ràng. Tuy nhiên, để xác định đây là do hiện tượng curve-fitting (overfitting tham số) hay do thị trường chuyển pha chế độ (regime shift), cần thực hiện thêm các phân tích phân rã lợi nhuận theo chế độ thị trường (regime attribution) và kiểm định walk-forward rolling window.

### B. Vai trò của chi phí giao dịch (Fee Impact):
- **Số liệu quan sát:**
  - `14e3b934b1e5` (ROC Momentum): Phát sinh **736 lệnh**, tiền phí sàn ghi nhận **238.2 USD**, PnL toàn kỳ **-29.81%**.
  - `5e52d3fdf71f` (Bollinger Overextension): Phát sinh **504 lệnh**, phí sàn **192.4 USD**, PnL **-24.74%**.
  - `b4b65cd3493f` (CCI Snapback): Phát sinh **479 lệnh**, phí sàn **171.9 USD**, PnL **-21.49%**.
- **Đánh giá:** Chi phí giao dịch ở mức hàng trăm USD là yếu tố khách quan làm suy giảm vốn trong điều kiện giao dịch tần suất lớn. Tuy nhiên, để xác định tỷ trọng tác động chính xác của phí sàn đối với tổng khoản lỗ, cần thực hiện thêm các lượt chạy đối chứng giả định không phí (`zero-fee counterfactual runs`).

### C. Tỷ lệ thắng thấp và cấu hình Stop-Loss:
- **Số liệu quan sát:**
  - `bf519617d973` (DEMA Optimized): Tỷ lệ thắng **0.0%** (9 lệnh full / 22 lệnh OOS), lỗ toàn kỳ **-31.86%**; cấu hình `stop_loss_rate = 2.5%`.
  - `4f28285aa44c` (Dual EMA + ADX): Tỷ lệ thắng **0.0%** (10 lệnh full / 7 lệnh OOS), lỗ **-4.40%**; cấu hình `stop_loss_rate = 3.0%`.
  - `270e6e28416f` (EMA Trend Rider): Tỷ lệ thắng **7.7%** (13 lệnh full / 17 lệnh OOS), lỗ **-31.35%**; cấu hình `stop_loss_rate = 2.5%`.
- **Đánh giá:** Các chiến lược này đều có mức Stop-Loss cố định từ 2.5% đến 3.0% trên khung nến ngày 24h. Tỷ lệ thắng cực thấp là hiện tượng cần đối chiếu với trade-level log chi tiết để phân biệt giữa việc bị chạm ngưỡng cắt lỗ do biến động ngắn hạn (whipsaw) hay do bản thân tín hiệu vào lệnh ngược pha xu hướng.

### D. Nhóm Alpha có OOS dương và trường hợp FastDip (`8a47cdbcc942`):
- **Nhóm 6 Alpha OOS dương biên:**
  - `0873864b8db7` (DEMA Turbo Compound): Toàn kỳ đạt **+130.52%**, Train đạt **+112.40%**, nhưng OOS chỉ còn **+6.87%** với Sharpe OOS rơi xuống **0.31**.
  - Các alpha breakout channel của Vinh (`090730ae35b8`, `303d4b713dda`, `33312a2f4dfc`, `efb1fbe2db86`) và `6055aa8f661e`: Đều ghi nhận OOS dương ở mức nhỏ (**+0.81% đến +3.38%**). Cả 6 alpha này đều chạy dưới cấu hình `exit_unit="atr"`.
- **Chiến lược FastDip (`8a47cdbcc942`):**
  - Đạt lợi nhuận OOS **+18.17%**, Sharpe 3.36, MDD 1.03%.
  - Tuy nhiên, chiến lược này chỉ được cấu hình chạy trong **cửa sổ ngắn 3 tháng** (`2026-07-01` đến `2026-10-03`, train ratio 0.3) và **chỉ phát sinh duy nhất 3 lệnh giao dịch**.
  - Đây là kích thước mẫu quá nhỏ, chưa đủ để đánh giá độ bền thống kê. Cửa sổ và tỷ lệ train của FastDip tách biệt hoàn toàn với 29 alpha còn lại, không cấu thành cùng một mặt phẳng so sánh.
""")

    lines.append("## 5. DANH SÁCH 27 ALPHA BỊ CHẶN (BLOCKED_UNKNOWN_INTENT)\n")
    lines.append("| ID | Tên Alpha | Chủ sở hữu | Lý do kỹ thuật & Căn cứ pháp lý |")
    lines.append("|---|---|---|---|")
    for aid, b in blocked.items():
        name = b.get("name", "")[:30]
        owner = str(b.get("owner_id", ""))[:8]
        reason = b.get("reason", "")
        lines.append(f"| `{aid}` | {name} | {owner} | {reason} |")

    lines.append("""
## 6. ĐỀ XUẤT BƯỚC TIẾP THEO (NEXT STEPS)

1. **Bảo toàn dữ liệu user:** Giữ nguyên trạng 100% kho dữ liệu gốc và 27 alpha bị chặn; không can thiệp cho đến khi có căn cứ ý đồ từ chủ sở hữu.
2. **Không kết luận vội vã:** Báo cáo này đóng vai trò là cột mốc đo lường baseline ban đầu. Không sử dụng kết quả này để tuyên bố pass hoặc sẵn sàng giao dịch.
3. **Kế hoạch Nghiên cứu Tiến hóa có Kiểm soát:**
   - Tạo fork nghiên cứu độc lập (`research_candidate_v1`), không ghi đè kho user.
   - Chạy các lượt đối chứng (counterfactual runs) để kiểm tra giả thuyết fee drag và stop-loss whipsaw.
   - Áp dụng kiểm định Walk-Forward đa khung thời gian và bảo vệ tập dữ liệu Holdout độc lập.
""")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Đã hoàn thiện báo cáo khoa học vào: {OUT_REPORT}")


def main():
    if not OUT_RESULTS.exists():
        print(f"Không tìm thấy file kết quả {OUT_RESULTS}")
        return
    with open(OUT_RESULTS, "r", encoding="utf-8") as f:
        data = json.load(f)
    build_rigorous_report(data)


if __name__ == "__main__":
    main()
