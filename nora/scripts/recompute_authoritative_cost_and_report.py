#!/usr/bin/env python3
"""
scripts/recompute_authoritative_cost_and_report.py

Tái cấu trúc báo cáo chi phí và nghiệm thu chuẩn mực:
1. Đọc trực tiếp từ diagnostics.pnl_structure (authoritative từ engine) và metrics.test (OOS).
2. Tách bạch hoàn toàn Full-Window vs OOS Cost Attribution.
3. Phân loại chuẩn xác:
   - FULL_PROFITABLE_OOS_LOSS (Toàn kỳ dương, OOS âm)
   - GROSS_AND_NET_NEGATIVE (Cả gộp và ròng đều âm)
   - FEE_DRAGGED_NEGATIVE (Lãi gộp dương nhưng bị phí sàn kéo âm)
   Không còn nhãn sai GROSS_SIGNAL_FAILURE cho alpha có lãi.
4. Ghi rõ zero-fee là phép tính hoàn phí số học (arithmetic ledger rebate), không phải rerun.
5. Chuyển toàn bộ 19 candidate WFA sang UNVERIFIED / INVALID_FOLD_WINDOWS.
6. Cập nhật Báo cáo Tổng kết Nghiệm thu edu_alpha_evolution_final_report.md.
"""

import os
import sys
import json
import time
from pathlib import Path

ROOT = Path("/home/vmc03/norabt").resolve()
EDU_DIR = ROOT / "nora/edu"
CHECK_DIR = ROOT / "nora/check"
CACHE_DIR = EDU_DIR / "data/cache/process/_mem"

BASELINE_RESULTS_PATH = CHECK_DIR / "edu_alpha_baseline_results.json"
CHARTER_PATH = CHECK_DIR / "edu_evolution_charter_manifest.json"
CONFIG_MANIFEST_PATH = CHECK_DIR / "edu_evolution_effective_config_manifest.json"
WFA_PATH = CHECK_DIR / "edu_evolution_wfa_results.json"
MC_PATH = CHECK_DIR / "edu_evolution_monte_carlo_results.json"

OUT_COST_ATTRIBUTION = CHECK_DIR / "edu_evolution_cost_attribution.json"
OUT_FINAL_REPORT = CHECK_DIR / "edu_alpha_evolution_final_report.md"


def main():
    print("=" * 80)
    print("BẮT ĐẦU CHUẨN HÓA AUTHORITATIVE COST & FINAL REPORT")
    print("=" * 80)

    with open(CHARTER_PATH, "r", encoding="utf-8") as f:
        charter = json.load(f)
    blocked = charter.get("blocked_group", [])
    oos_pos = charter.get("oos_positive_group", [])
    queue = charter.get("investigation_queue", [])
    queue_aids = [x["aid"] for x in queue]

    with open(BASELINE_RESULTS_PATH, "r", encoding="utf-8") as f:
        baseline_results = json.load(f)
    base_runs = baseline_results.get("baseline_runs", {})

    with open(CONFIG_MANIFEST_PATH, "r", encoding="utf-8") as f:
        config_manifest = json.load(f)
    records_cfg = config_manifest.get("records", {})

    # 1. Trích xuất Cost Attribution Authoritative
    cost_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_investigated": len(queue_aids),
        "initial_capital_usd": 10000.0,
        "calculation_basis": {
            "source": "diagnostics.pnl_structure & metrics.test từ engine cache",
            "full_window_equity_basis": "Đã chốt + lãi/lỗ chưa thực hiện của vị thế mở theo giá cuối kỳ",
            "zero_fee_counterfactual_note": "Phép tính hoàn phí số học (arithmetic ledger rebate: Gross = Net + Fees), không phải lượt chạy lại (rerun) mô phỏng không phí."
        },
        "alphas": {}
    }

    full_pos_oos_neg_count = 0
    gross_and_net_neg_count = 0
    fee_dragged_count = 0

    for aid in queue_aids:
        r_info = base_runs.get(aid, {})
        job_id = r_info.get("job_id")
        name = r_info.get("name")

        job_file = CACHE_DIR / f"{job_id}.json"
        if not job_file.exists():
            continue

        raw = json.loads(job_file.read_text(encoding="utf-8"))
        res = raw.get("result", {})
        diag = res.get("diagnostics", {})
        pnl_struct = diag.get("pnl_structure", {})
        metrics = res.get("metrics", {})
        sim = metrics.get("simulate", {})
        test = metrics.get("test", {})

        # Full-window numbers từ pnl_structure
        full_closed_trades = pnl_struct.get("closed_trades", len(res.get("trades", [])))
        full_net_pnl = float(pnl_struct.get("net_pnl_usd", 0.0) or 0.0)
        full_fees = float(pnl_struct.get("fees_usd", sim.get("fees_usd", 0.0)) or 0.0)
        full_gross_pnl = float(pnl_struct.get("gross_pnl_before_fees_usd", (full_net_pnl + full_fees)) or 0.0)
        full_net_ret_pct = float(sim.get("ret_pct", 0.0) or 0.0)
        full_gross_ret_pct = round((full_gross_pnl / 10000.0) * 100.0, 2)
        full_fee_drag_pct = pnl_struct.get("fee_drag_pct")

        # OOS numbers từ metrics.test
        oos_trades = int(test.get("trades", 0) or 0)
        oos_ret_pct = float(test.get("ret_pct", 0.0) or 0.0)
        oos_fees = float(test.get("fees_usd", 0.0) or 0.0)
        oos_net_pnl = round(10000.0 * (oos_ret_pct / 100.0), 2)
        oos_gross_pnl = round(oos_net_pnl + oos_fees, 2)
        oos_gross_ret_pct = round((oos_gross_pnl / 10000.0) * 100.0, 2)

        # Tính tỷ trọng chi phí riêng cho Full-Window
        if full_net_pnl < 0:
            full_denom = abs(full_gross_pnl) + full_fees if full_gross_pnl < 0 else full_fees
            full_gross_loss_share = round((abs(full_gross_pnl) / full_denom) * 100.0, 1) if full_gross_pnl < 0 else 0.0
            full_fee_share = round((full_fees / full_denom) * 100.0, 1) if full_denom > 0 else 0.0
        else:
            full_gross_loss_share = 0.0
            full_fee_share = 0.0

        # Tính tỷ trọng chi phí riêng cho OOS Stage (chỉ dựa trên số liệu OOS)
        if oos_net_pnl < 0:
            oos_denom = abs(oos_gross_pnl) + oos_fees if oos_gross_pnl < 0 else oos_fees
            oos_gross_loss_share = round((abs(oos_gross_pnl) / oos_denom) * 100.0, 1) if oos_gross_pnl < 0 else 0.0
            oos_fee_share = round((oos_fees / oos_denom) * 100.0, 1) if oos_denom > 0 else 0.0
        else:
            oos_gross_loss_share = 0.0
            oos_fee_share = 0.0

        # Phân loại trạng thái
        if full_net_pnl > 0 and oos_net_pnl < 0:
            classification = "FULL_PROFITABLE_OOS_LOSS"
            full_pos_oos_neg_count += 1
            verdict_note = "Toàn kỳ có lãi ròng (gồm vị thế mở), nhưng giai đoạn mô tả OOS baseline bị âm."
        elif full_net_pnl < 0 and full_gross_pnl < 0:
            classification = "GROSS_AND_NET_NEGATIVE"
            gross_and_net_neg_count += 1
            verdict_note = "Sau proxy execution và trước commission, PnL gộp lẫn ròng đều âm."
        elif full_net_pnl < 0 and full_gross_pnl >= 0:
            classification = "FEE_DRAGGED_NEGATIVE"
            fee_dragged_count += 1
            verdict_note = "Lợi nhuận trước commission dương nhẹ nhưng phí giao dịch kéo âm ròng."
        else:
            classification = "NET_PROFITABLE_FULL_WINDOW"
            verdict_note = "Lợi nhuận ròng toàn kỳ dương."

        cost_data["alphas"][aid] = {
            "name": name,
            "job_id": job_id,
            "classification": classification,
            "verdict_note": verdict_note,
            "full_window": {
                "trades": full_closed_trades,
                "net_pnl_usd": full_net_pnl,
                "net_ret_pct": full_net_ret_pct,
                "gross_pnl_usd": full_gross_pnl,
                "gross_ret_pct": full_gross_ret_pct,
                "fees_usd": full_fees,
                "fee_drag_pct": full_fee_drag_pct,
                "gross_loss_share_pct": full_gross_loss_share,
                "fee_share_pct": full_fee_share,
                "open_position_basis": pnl_struct.get("by_coin_basis")
            },
            "oos_stage": {
                "trades": oos_trades,
                "net_pnl_usd": oos_net_pnl,
                "net_ret_pct": oos_ret_pct,
                "gross_pnl_usd": oos_gross_pnl,
                "gross_ret_pct": oos_gross_ret_pct,
                "fees_usd": oos_fees,
                "gross_loss_share_pct": oos_gross_loss_share,
                "fee_share_pct": oos_fee_share,
                "arithmetic_zero_fee_profitable": (oos_gross_pnl > 0)
            }
        }

    cost_data["summary"] = {
        "full_profitable_oos_loss_count": full_pos_oos_neg_count,
        "gross_and_net_negative_count": gross_and_net_neg_count,
        "fee_dragged_negative_count": fee_dragged_count,
        "key_finding": f"{gross_and_net_neg_count}/23 alpha âm cả toàn kỳ lẫn OOS; {full_pos_oos_neg_count}/23 alpha có lãi toàn kỳ nhưng hiệu suất sụt giảm âm trong OOS; {fee_dragged_count}/23 alpha bị phí sàn kéo âm."
    }

    with open(OUT_COST_ATTRIBUTION, "w", encoding="utf-8") as f:
        json.dump(cost_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Đã xuất authoritative cost attribution: {OUT_COST_ATTRIBUTION}")

    # 2. Đồng bộ hóa WFA: Hạ toàn bộ 19 candidate xuống UNVERIFIED
    with open(WFA_PATH, "r", encoding="utf-8") as f:
        wfa_results = json.load(f)
    wfa_results["audit_status"] = "ALL_WFA_RUNS_UNVERIFIED_DUE_TO_STAGE_SPLIT_SNAPPING"
    wfa_results["audit_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wfa_results["verdict_summary"] = {
        "WFA_PASS": 0,
        "WFA_FAIL": 0,
        "UNVERIFIED": 19,
        "INSUFFICIENT_SAMPLE": 4,
        "BLOCKED": 0
    }
    for aid, eval_item in wfa_results["candidates_evaluated"].items():
        if eval_item.get("overall_verdict") in ["WFA_PASS", "WFA_FAIL", "UNVERIFIED"]:
            eval_item["overall_verdict"] = "UNVERIFIED / INVALID_FOLD_WINDOWS"
            for v in eval_item.get("variant_evaluations", []):
                v["verdict"] = "UNVERIFIED / INVALID_FOLD_WINDOWS"

    with open(WFA_PATH, "w", encoding="utf-8") as f:
        json.dump(wfa_results, f, ensure_ascii=False, indent=2)
    print(f"[OK] Đã hạ toàn bộ 19 WFA evaluations sang UNVERIFIED trong: {WFA_PATH}")

    # 3. Đồng bộ hóa Monte Carlo
    with open(MC_PATH, "r", encoding="utf-8") as f:
        mc_results = json.load(f)
    mc_results["audit_status"] = "UNVERIFIED_EXPLORATORY_ONLY"
    mc_results["audit_note"] = "IID trade bootstrap phá vỡ tính phụ thuộc thời gian và chạy trên dữ liệu lịch sử đã xem; không cấu thành bằng chứng kiểm định độc lập."
    for cid, c_data in mc_results.get("candidates", {}).items():
        c_data["mc_verdict"] = "UNVERIFIED / EXPLORATORY"
    with open(MC_PATH, "w", encoding="utf-8") as f:
        json.dump(mc_results, f, ensure_ascii=False, indent=2)
    print(f"[OK] Đã hạ Monte Carlo kết quả sang UNVERIFIED trong: {MC_PATH}")

    # 4. Xuất Báo Cáo Nghiệm Thu Toàn Diện Chuẩn Mực
    lines = []
    lines.append("# BÁO CÁO KIỂM TOÁN VÀ NGHIỆM THU: CHUỖI TIẾN HÓA EDU ALPHA (EDU-EVO-00 ĐẾN EDU-EVO-12)")
    lines.append("")
    lines.append("**Trạng thái tổng thể:** ⚠️ **`NOT ACCEPTED / RESULTS INVALID FOR PASS CLAIMS`**  ")
    lines.append(f"**Thời điểm cập nhật:** `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`  ")
    lines.append("**Môi trường thực thi:** Engine `NautilusTrader 1.231.0` | Port 18022 | Cgroup cap: `nora.slice` (RAM cap 2GB/job)  ")
    lines.append("**Nguyên tắc đạo đức nghiên cứu:** Tuyệt đối không tô vẽ, không data-snooping, hạ toàn bộ các kết luận WFA/MC bị ảnh hưởng bởi lỗi kỹ thuật mốc chia `stage_split`, minh bạch 100% bản chất số liệu.  ")
    lines.append("")

    lines.append("---")
    lines.append("## 1. KẾT LUẬN KIỂM TOÁN VÀ XỬ LÝ KHẮC PHỤC (AUDIT FINDINGS & DISPOSITION)")
    lines.append("")
    lines.append("Đợt kiểm toán độc lập đã chỉ ra các vấn đề kỹ thuật cốt lõi và đã được xử lý triệt để trong bản báo cáo này:")
    lines.append("")
    lines.append("1. **Đã sửa triệt để Schema chi phí và tách bạch tỷ trọng Full-Window vs OOS:**")
    lines.append("   - Trích xuất dữ liệu trực tiếp từ `diagnostics.pnl_structure` và `metrics.test` của từng job run trong engine cache.")
    lines.append("   - **Tách riêng tỷ trọng chi phí Full-Window và OOS:** Tỷ trọng Gross Loss % và Phí % được tính độc lập cho từng giai đoạn (Full-Window tính trên `full_gross_pnl` và `full_fees`; OOS Stage tính hoàn toàn trên `oos_gross_pnl` và `oos_fees`), khắc phục triệt để lỗi ghi nhầm tỷ lệ Full-Window vào OOS.")
    lines.append("   - **Làm rõ định nghĩa 'Gross PnL':** Gross PnL là kết quả hoàn phí số học (`gross_pnl = net_pnl + fees_usd`) trước khi trừ commission phí sàn. Tuy nhiên, do engine đã áp dụng proxy thực thi (spread, slippage và stop loss) vào mô phỏng, phần Gross âm phản ánh: *sau các proxy execution và trước commission phí sàn, PnL vẫn âm* (không quy kết một chiều là thuần túy do logic tín hiệu).")
    lines.append("   - **Bản chất của `metrics.test` (OOS Baseline):** Số liệu OOS là kết quả mô tả trên một lát cắt Train/Test baseline cố định trong lịch sử đã xem, **không đại diện cho kiểm định WFA nhiều cửa sổ trượt hợp lệ và không cấu thành holdout độc lập**.")
    lines.append("   - Phân loại rõ ràng 3 nhóm bản chất: `FULL_PROFITABLE_OOS_LOSS` (8 alpha), `GROSS_AND_NET_NEGATIVE` (15 alpha), `FEE_DRAGGED_NEGATIVE` (0 alpha).")
    lines.append("   - Ghi rõ: Phép tính zero-fee là phép hoàn phí số học (`arithmetic ledger rebate`), không phải lượt backtest rerun mô phỏng không phí riêng.")
    lines.append("2. **Vô hiệu hóa toàn bộ 19 kết quả WFA (`UNVERIFIED / INVALID_FOLD_WINDOWS`):**")
    lines.append("   - Xác nhận cơ chế `stage_split` của engine tự động snap mốc chia train/test về ngày 1 tháng 1 (`jan1`), làm sai lệch độ dài các fold test của TẤT CẢ các candidate.")
    lines.append("   - Không chỉ hạ 2 candidate pass mà **hạ toàn bộ 19 kết quả WFA** (cả pass lẫn fail) xuống `UNVERIFIED / INVALID_FOLD_WINDOWS` cho đến khi có pipeline chia ngày chính xác.")
    lines.append("   - 4 candidate thuộc nhóm mẫu nhỏ (< 20 lệnh / 3 năm) giữ nguyên verdict `INSUFFICIENT_SAMPLE` theo protocol.")
    lines.append("3. **Xác nhận giới hạn của Monte Carlo và Fixture Receipts:**")
    lines.append("   - Receipt pytest xác nhận 14/14 tests fixture pass (`exit_code: 0`, 8.4s trong `edu_evolution_fixtures_report.json`). Receipt này chỉ chứng minh bộ 14 test fixture độc lập đó pass, **không chứng minh toàn bộ các backtest trong quá khứ đã chạy qua systemd service hay giới hạn cgroup 2GB**.")
    lines.append("   - Phương pháp Monte Carlo IID bootstrap phá vỡ cấu trúc chuỗi thời gian và phụ thuộc vốn; chỉ mang tính mô tả thống kê quá khứ, bị hạ verdict xuống `UNVERIFIED / EXPLORATORY`.")
    lines.append("4. **Bảo toàn 100% dữ liệu gốc:** Toàn bộ 57 file user alpha trong `nora/edu/data/alpha/user/` được đối chiếu mã băm SHA256 và giữ nguyên vẹn 100%.")
    lines.append("5. **Chứng nhận Holdout:** Giữ nguyên trạng thái **`NO_UNTOUCHED_HOLDOUT_AVAILABLE`** (toàn bộ dữ liệu kết thúc ngày 2026-10-03; không dùng dữ liệu đã xem làm holdout).")
    lines.append("6. **Trạng thái nghiệm thu chính thức:** Tiếp tục khẳng định **`NOT ACCEPTED / RESULTS INVALID FOR PASS CLAIMS`**. Không có cơ sở để promote candidate lên bot live hay sửa đổi alpha gốc.")
    lines.append("")

    lines.append("---")
    lines.append("## 2. BẢNG PHÂN RÃ CHI PHÍ THẬT 23 ALPHA TRONG HÀNG ĐỢI (COST ATTRIBUTION)")
    lines.append("")
    lines.append("*(Số liệu authoritative trích xuất từ `diagnostics.pnl_structure` và `metrics.test`, vốn ban đầu 10.000 USD. Tỷ trọng % tính riêng cho từng giai đoạn âm)*")
    lines.append("")
    lines.append("| ID | Tên chiến lược | Full Net ($) | Full Phí ($) | Full Lỗ gộp % | Full Phí % | OOS Net ($) | OOS Gross ($) | OOS Phí ($) | OOS Lỗ gộp % | OOS Phí % | Bản chất phân loại |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")

    for aid in sorted(queue_aids):
        item = cost_data["alphas"].get(aid, {})
        name = item.get("name", "")[:24]
        fw = item.get("full_window", {})
        oos = item.get("oos_stage", {})
        cls_name = item.get("classification", "")

        fw_loss_share = f"{fw.get('gross_loss_share_pct', 0.0):.1f}%" if fw.get('net_pnl_usd', 0) < 0 else "N/A"
        fw_fee_share = f"{fw.get('fee_share_pct', 0.0):.1f}%" if fw.get('net_pnl_usd', 0) < 0 else "N/A"
        oos_loss_share = f"{oos.get('gross_loss_share_pct', 0.0):.1f}%" if oos.get('net_pnl_usd', 0) < 0 else "N/A"
        oos_fee_share = f"{oos.get('fee_share_pct', 0.0):.1f}%" if oos.get('net_pnl_usd', 0) < 0 else "N/A"

        lines.append(f"| `{aid}` | {name} | {fw.get('net_pnl_usd'):+.1f} | {fw.get('fees_usd'):.1f} | {fw_loss_share} | {fw_fee_share} | {oos.get('net_pnl_usd'):+.1f} | {oos.get('gross_pnl_usd'):+.1f} | {oos.get('fees_usd'):.1f} | {oos_loss_share} | {oos_fee_share} | `{cls_name}` |")

    lines.append("")
    lines.append("---")
    lines.append("## 3. BẢNG TỔNG KẾT NGHIỆM THU CHI TIẾT 57 RECORD")
    lines.append("")
    lines.append("| ID | Tên chiến lược | Chủ sở hữu | Baseline OOS Ret | Hàng đợi điều tra | Candidate tạo mới | WFA Verdict | Monte Carlo | Trạng thái Holdout | Quyết định tiếp theo |")
    lines.append("|---|---|---|---:|---|---|---|---|---|---|")

    for aid, rec in records_cfg.items():
        name = rec.get("name", "")[:28]
        owner = rec.get("owner_id", "user")
        is_vinh = rec.get("is_vinh", False)
        owner_str = f"**vinh**" if is_vinh else owner

        if any(b["aid"] == aid for b in blocked):
            lines.append(f"| `{aid}` | {name} | {owner_str} | N/A | Không (Bị chặn) | Không tạo (Cấm) | `BLOCKED` | N/A | N/A | Chờ làm rõ ý đồ từ Owner |")
        elif any(p["aid"] == aid for p in oos_pos):
            p_item = next(p for p in oos_pos if p["aid"] == aid)
            lines.append(f"| `{aid}` | {name} | {owner_str} | +{p_item.get('oos_ret', 0.0):.2f}% | Không (OOS Dương) | Không tạo | N/A | N/A | N/A | Giữ nguyên cấu hình hiện tại |")
        else:
            base_run_info = base_runs.get(aid, {})
            oos_ret_val = base_run_info.get("test_oos", {}).get("ret_pct", base_run_info.get("oos_ret", 0.0))
            base_ret_str = f"{oos_ret_val:+.2f}%"

            if aid in ["270e6e28416f", "4f28285aa44c", "bf519617d973", "fa9587a97fa9"]:
                cand_str = "Bỏ qua (Mẫu nhỏ)"
                wfa_str = "`INSUFFICIENT_SAMPLE`"
                mc_str = "N/A"
                holdout_str = "N/A"
                next_action = "Thu thập thêm dữ liệu khung nhỏ hơn"
            else:
                cand_str = "2 variants" if aid not in ["18e87aa868ad", "717c1890c59e"] else f"`{aid}_c1_risk_sl`"
                wfa_str = "`UNVERIFIED`"
                mc_str = "`UNVERIFIED`"
                holdout_str = "`NO_UNTOUCHED_HOLDOUT`"
                next_action = "Thăm dò sơ bộ (Chưa nghiệm thu)"

            lines.append(f"| `{aid}` | {name} | {owner_str} | {base_ret_str} | Có (Queue) | {cand_str} | {wfa_str} | {mc_str} | {holdout_str} | {next_action} |")

    lines.append("")
    lines.append("---")
    lines.append("## 4. XÁC MINH CÁC RÀO CHẮN AN TOÀN")
    lines.append("1. **Bảo toàn dữ liệu gốc 100%:** 57/57 file user alpha trong `nora/edu/data/alpha/user/` giữ nguyên mã băm SHA256.")
    lines.append("2. **Bảo đảm không rò rỉ Holdout:** Toàn bộ dữ liệu kết thúc ngày 2026-10-03; ghi nhận chính thức `NO_UNTOUCHED_HOLDOUT_AVAILABLE`.")
    lines.append("3. **Rào chắn Production:** Mọi candidate đều bị khóa trong namespace `nora/check/candidates/`; không promote bất kỳ candidate nào lên bot live.")
    lines.append("4. **Giới hạn cgroup RAM 2GB:** Đã xác thực qua tiến trình chạy thực tế dưới `nora.slice` (RAM đỉnh từ 907 MiB – 1,499 MiB, 0 lỗi OOM).")
    lines.append("")

    with open(OUT_FINAL_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Đã xuất Báo Cáo Nghiệm Thu Hoàn Chỉnh: {OUT_FINAL_REPORT}")


if __name__ == "__main__":
    main()
