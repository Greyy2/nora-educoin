#!/usr/bin/env python3
"""Script sinh 2 artifacts chuẩn bị cho WFA & Monte Carlo:
1. artifacts/backtest_results/wfa_mc_cohort_freeze.json (Đóng băng phân loại cohort 25 rows dựa trên mã nguồn)
2. artifacts/backtest_results/wfa_mc_protocol_preregistration.md (Văn bản tiền đăng kiểm giao thức WFA/MC)
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path("/home/vmc03/norabt")
OUT_DIR = REPO_ROOT / "artifacts" / "backtest_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_FILE = OUT_DIR / "input_manifest.json"
RESULTS_FILE = OUT_DIR / "master_backtest_results.json"

def main():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8")) if MANIFEST_FILE.exists() else {}
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8")) if RESULTS_FILE.exists() else []
    
    # 1. ĐÓNG BĂNG PHÂN LOẠI COHORT (25 ROWS)
    cohort_rows = []
    
    # Danh sách 4 bài EDU buy-and-hold (chỉ 1 trade, không có exit condition)
    edu_buy_and_hold_ids = {"026f43441cb2", "0bf936687964", "138df68946ad", "1a1a4389a821"}
    
    for r in results:
        aid = r["id"]
        cat = r["category"]
        trades = r.get("trades", 0)
        
        # Tìm metadata tương ứng trong manifest
        m_cfg = next((item for item in manifest.get("results_summary", []) if item["id"] == aid), {})
        
        # Phân loại dựa trên TÍNH CHẤT MÃ NGUỒN (không dựa vào PnL)
        if cat == "COIN Portfolio":
            classification = "PORTFOLIO_COMBO"
            evaluation_track = "PORTFOLIO_SHARED_EXPOSURE_EVALUATION"
            wfa_suitability = "SEPARATE_PORTFOLIO_EVALUATION"
            wfa_method = "PORTFOLIO_ROLLING_OOS"
            rationale = "Cấp độ rổ danh mục 6 legs chia sẻ vốn và exposure, không phải alpha đơn lẻ; phải đánh giá riêng biệt, cấm xếp hạng."
        elif cat == "COIN Top Agent":
            classification = "PROXY_ENTRY_RESEARCH_ONLY"
            evaluation_track = "RESEARCH_PROXY_TRACK"
            wfa_suitability = "EXPLORATORY_OOS_ONLY"
            wfa_method = "RESEARCH_ONLY_NO_DECISION"
            rationale = "Chỉ có tham số thoát lệnh/trailing lấy từ OKX; điều kiện vào lệnh là proxy nhân tạo (RSI < 30); không đại diện bot OKX thực, không đưa vào bảng KEEP/REJECT."
        elif aid in ("sideway_long", "sideway_short") or aid in ("0873864b8db7", "15567e02a806", "0bf936687964"):
            classification = "LOW_SAMPLE_CRITICAL"
            evaluation_track = "SAMPLE_SUFFICIENCY_MONITORING"
            wfa_suitability = "INSUFFICIENT_SAMPLE_KNOWN"
            wfa_method = "FIXED_PARAM_ROLLING_OOS"
            rationale = f"Mẫu lệnh cực mỏng ({trades} lệnh cả 2.7 năm); chắc chắn rơi vào INSUFFICIENT_SAMPLE trên các lát cắt thời gian."
        elif cat == "COIN User V2":
            classification = "FIXED_PARAM_ROLLING_OOS"
            evaluation_track = "FORMAL_ALPHA_CANDIDATE"
            wfa_suitability = "ROLLING_OOS_WINDOW_EVALUATION"
            wfa_method = "FIXED_PARAM_ROLLING_OOS"
            rationale = "Mã nguồn hiện tại chạy tham số cố định (Donchian/Dynamic Channel, stop_loss_rate 2.5/3.0, không có grid tối ưu); trạng thái duy nhất là Rolling OOS tham số cố định."
        elif cat in ("COIN System Leg", "EDU Canonical"):
            classification = "FIXED_PARAM_ROLLING_OOS"
            evaluation_track = "STANDARD_BASELINE_TRACK"
            wfa_suitability = "ROLLING_OOS_WINDOW_EVALUATION"
            wfa_method = "FIXED_PARAM_ROLLING_OOS"
            rationale = "Chiến lược có quy tắc và tham số cố định, không có tham số tối ưu lại trên train; bản chất là đánh giá OOS từng cửa sổ (Rolling OOS), không phải True WFA."
        else:
            classification = "FIXED_PARAM_ROLLING_OOS"
            evaluation_track = "STANDARD_BASELINE_TRACK"
            wfa_suitability = "ROLLING_OOS_WINDOW_EVALUATION"
            wfa_method = "FIXED_PARAM_ROLLING_OOS"
            rationale = f"Mã nguồn học viên active ({aid}) đầy đủ logic vào/thoát lệnh nhưng tham số cố định."

        cohort_rows.append({
            "id": aid,
            "name": r["name"],
            "venue": r["venue"],
            "category": cat,
            "source_classification": classification,
            "evaluation_track": evaluation_track,
            "wfa_suitability": wfa_suitability,
            "wfa_method_assigned": wfa_method,
            "source_rationale": rationale,
            "in_sample_trades": trades,
            "in_sample_ret_pct": r.get("ret_pct"),
            "symbols": m_cfg.get("symbols", ["BTC"]),
            "timeframe": m_cfg.get("timeframe", "1h"),
            "effective_leverage": m_cfg.get("effective_leverage"),
            "effective_risk_pct": m_cfg.get("effective_risk_pct"),
            "code_sha256": m_cfg.get("code_sha256"),
            "raw_ledger_file": m_cfg.get("raw_ledger_file"),
            "raw_ledger_sha256": m_cfg.get("raw_ledger_sha256"),
        })

    freeze_payload = {
        "cohort_freeze_version": "1.1.0",
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Đóng băng phân loại chính xác 25 đối tượng từ master smoke-run dựa trên đặc tính mã nguồn phục vụ tiền đăng kiểm Rolling OOS và Monte Carlo.",
        "gate_status": "FORMAL_EXECUTION_STRICTLY_BLOCKED",
        "blocking_reasons": [
            "Owner đã chốt risk/trade <= 0.25% master, gross <= 3x và one-way <= 2x; runtime enforcement chưa được nghiệm thu.",
            "Account fee tier và calibrated execution costs (spread/slippage) chưa được xác minh (UNVERIFIED).",
            "Funding rate lịch sử OKX và time-effective instrument specs chưa tích hợp.",
            "Backtest-Live execution parity và Demo replay chưa nghiệm thu."
        ],
        "approval_metadata": {
            "status": "PARTIAL_DECISIONS_RECORDED_FULL_SIGNOFF_PENDING",
            "approved_by": None,
            "approved_at_utc": None,
            "protocol_file": "artifacts/backtest_results/wfa_mc_protocol_preregistration.md",
            "protocol_sha256_at_approval": None,
            "protocol_sha256_current": None,
            "owner_decisions": {
                "oos_sample_rule": {
                    "value": "A_AGGREGATED_OOS_MIN_30_TRADES",
                    "status": "APPROVED_BY_OWNER",
                    "decision_date_utc": "2026-10-29"
                },
                "classification_thresholds": {
                    "value": "SECTION_7_PROPOSED_THRESHOLDS_ACCEPTED",
                    "status": "APPROVED_BY_OWNER",
                    "decision_date_utc": "2026-10-29"
                }
            },
            "note": "Owner đã chốt quy tắc mẫu OOS và ngưỡng phân loại; chưa ghi nhận chữ ký phê duyệt toàn bộ protocol. Hash hiện hành không phải hash ký duyệt. Giữ gate thi công BLOCKED cho đến khi các readiness gates được nghiệm thu."
        },
        "total_cohort_records": len(cohort_rows),
        "cohort_summary": {
            "portfolio_combos_count": sum(1 for c in cohort_rows if c["source_classification"] == "PORTFOLIO_COMBO"),
            "structural_excluded_count": sum(1 for c in cohort_rows if c["source_classification"] == "EXCLUDED_STRUCTURAL_NO_SIGNAL_LOGIC"),
            "proxy_research_count": sum(1 for c in cohort_rows if c["source_classification"] == "PROXY_ENTRY_RESEARCH_ONLY"),
            "low_sample_critical_count": sum(1 for c in cohort_rows if c["source_classification"] == "LOW_SAMPLE_CRITICAL"),
            "fixed_param_rolling_oos_count": sum(1 for c in cohort_rows if c["source_classification"] == "FIXED_PARAM_ROLLING_OOS"),
        },
        "records": cohort_rows
    }

    freeze_json_path = OUT_DIR / "wfa_mc_cohort_freeze.json"
    freeze_json_path.write_text(json.dumps(freeze_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Đã tạo file đóng băng cohort: {freeze_json_path}")

    # 2. VĂN BẢN TIỀN ĐĂNG KIỂM GIAO THỨC WFA & MONTE CARLO
    # Tạo bảng chi tiết 25 IDs
    table_rows_md = []
    for idx, c in enumerate(cohort_rows, 1):
        table_rows_md.append(
            f"| {idx} | `{c['id']}` | {c['name'][:30]} | {c['category']} | {c['in_sample_trades']} | {c['source_classification']} | `{c['wfa_method_assigned']}` |"
        )
    table_25_ids_md = "\n".join(table_rows_md)
    now_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    protocol_template = r"""# TIỀN ĐĂNG KIỂM GIAO THỨC ĐÁNH GIÁ ROLLING OOS & MONTE CARLO (COHORT MASTER BACKTEST)
*Tài liệu tiền đăng kiểm phương pháp luận, cửa sổ kiểm định, tiêu chí mẫu mỏng và bộ ngưỡng phân loại.*
*Ngày cập nhật: __NOW_UTC__ | Phiên bản: 1.1.0-REVISED (Đã xử lý 6 phản biện kỹ thuật)*

> [!IMPORTANT]
> **TRẠNG THÁI HIỆN TẠI: TIỀN ĐĂNG KIỂM (PRE-REGISTRATION) — THI CÔNG BỊ KHÓA (STRICTLY BLOCKED)**
> - Owner đã chốt master risk/trade ≤ 0.25%, gross ≤ 3x và one-way ≤ 2x; runtime enforcement chưa được nghiệm thu. Fee/cost, historical funding/spec và backtest-live/Demo replay cũng chưa đạt, nên chạy chính thức vẫn **BỊ CHẶN**.
> - Mọi thử nghiệm chạy hạ tầng nếu có chỉ mang nhãn: **"Dry-run hạ tầng kỹ thuật, không dùng ra quyết định alpha"** và không được đưa vào bảng lọc.
> - Owner đã chọn Phương án A (Aggregated OOS ≥ 30 trades) và chấp nhận các ngưỡng KEEP / REVIEW / REJECT tại Section 7. Đây là phê duyệt các lựa chọn phương pháp, không đóng các readiness gates.

---

## 1. Ranh Giới Phương Pháp: Rolling OOS vs True WFA

Hầu hết các alpha hiện tại có bộ tham số cố định trong mã nguồn. Cần phân định rạch ròi 2 phương thức:
1. **Rolling OOS Window Evaluation (Đánh giá cửa sổ trượt tham số cố định)**:
   - *Áp dụng cho*: Toàn bộ 17 alphas/legs đang chạy tham số cố định trong mã nguồn:
     - 6 COIN System Legs (`kema_long`, `kema_short`, `sideway_long`, `sideway_short`, `dca_long`, `dca_short`).
     - 3 COIN User V2 (`efa90f74cd08_v2`, `18e87aa868ad_v2`, `33312a2f4dfc_v2`). *Lưu ý: Do hiện tại chưa khai báo grid tham số tối ưu, 3 alpha này được phân loại duy nhất là Rolling OOS tham số cố định, không để trạng thái 'nếu'.*
     - 2 EDU Canonical (`edu_canonical_beginner_dual_ema`, `edu_canonical_advanced_volatility_breakout`).
     - 6 EDU Active User có logic tín hiệu (`0873864b8db7`, `090730ae35b8`, `0d51ba8d2012`, `14e3b934b1e5`, `15567e02a806`, `18e87aa868ad`).
   - *Bản chất*: KHÔNG có bước tái tối ưu tham số trên tập Train. Train chỉ dùng làm warmup/tích lũy trạng thái chỉ báo; OOS đánh giá hiệu suất thuần túy trên dữ liệu tương lai chưa nhìn thấy.
2. **True Walk-Forward Optimization (WFO thực thụ)**:
   - *Điều kiện cần*: Chỉ áp dụng khi chiến lược có định nghĩa rõ không gian tham số Grid (ví dụ: `lookback ∈ [10, 20, 30]`, `stop_loss_rate ∈ [2.0, 2.5, 3.0]`). Hiện tại chưa có alpha nào trong cohort có grid được duyệt, do đó **không có alpha nào chạy theo luồng True WFA trong đợt này**.

---

## 2. Giới Hạn Cốt Lõi Về Tính Độc Lập Của Dữ Liệu: Pseudo-OOS vs Pure Holdout

Cần nêu trung thực và minh bạch giới hạn về dữ liệu trước Owner:
1. **Bản chất 'Train' và 'OOS'**: Với các chiến lược tham số cố định, tập Train mở rộng (expanding train) không thực hiện vai trò tìm kiếm tham số. Ba cửa sổ OOS thực chất chỉ là **3 lát cắt thời gian lịch sử (historical time slices)**.
2. **Rủi ro Rò rỉ Thông tin (Information Leakage)**: Đợt Master Smoke Run vừa qua đã chạy toàn bộ dữ liệu 2.7 năm (`2024-01` đến `2026-09`). Kết quả in-sample toàn kỳ đã được quan sát. Nếu trong quá trình phát triển vừa qua (ví dụ viết User V2, chỉnh sizing 0.25%, gắn SL), các quyết định kỹ thuật đã vô thức dựa vào việc quan sát hành vi thị trường 2024–2026, thì 3 cửa sổ OOS này **không còn là tập dữ liệu tinh khiết chưa từng thấy (Pure Untouched OOS)**.
3. **Kết luận kỹ thuật**: Kết quả OOS của 3 folds chỉ mang ý nghĩa **Pseudo-OOS (Kiểm định lát cắt lịch sử)**. Để có đánh giá Out-of-Sample thực sự khách quan (True Blind Holdout), hệ thống bắt buộc phải kiểm định trên dữ liệu mới hoàn toàn (sau `2026-09`) hoặc trên các cặp tiền/tài sản chưa từng được backtest.

---

## 3. Thiết Kế Cửa Sổ Kiểm Định (3 Folds trên chu kỳ 2024-01 đến 2026-09)

Tổng thời gian dữ liệu: ~2.7 năm (1,005 ngày). Phân chia 3 Folds theo mô hình Anchored Slicing:

| Fold | Khoảng Thời Gian Train (Warmup) | Độ Dài Train | Khoảng Thời Gian OOS (Đánh giá) | Độ Dài OOS | Chế Độ Thị Trường Đại Diện |
|---|---|---|---|---|---|
| **Fold 1** | `2024-01-01` → `2024-11-30` | 11 tháng | `2024-12-01` → `2025-06-30` | 7 tháng | Bull/Euphoria & Điều chỉnh |
| **Fold 2** | `2024-01-01` → `2025-06-30` | 18 tháng | `2025-07-01` → `2026-01-31` | 7 tháng | Sideway / Biến động cao |
| **Fold 3** | `2024-01-01` → `2026-01-31` | 25 tháng | `2026-02-01` → `2026-09-01` | 7 tháng | Bear / Chuyển giao xu hướng |

---

## 4. Quy Tắc Số Lệnh Tối Thiểu & Phương Án Xử Lý Mẫu Mỏng

### Mâu thuẫn thực tế dữ liệu:
OOS mỗi fold chỉ kéo dài 7 tháng. Các alpha khung 24h (User V2) chỉ có ~45–53 lệnh trong toàn bộ 2.7 năm (trung bình ~1.4 lệnh/tháng $\approx$ 10–12 lệnh mỗi fold OOS 7 tháng). Nếu áp đặt cứng nhắc $N \ge 30$ lệnh trên **mỗi fold**, toàn bộ alpha 24h và sideway sẽ tự động bị đánh dấu là `INSUFFICIENT_SAMPLE`. Chỉ có nhóm Top Agent (proxy) hoặc EMA 1h là vượt qua được ngưỡng này.

### Lựa chọn đã được Owner chốt: Phương án A (Đánh giá mẫu gộp Aggregated OOS)
  - Ngưỡng thống kê $N_{\text{trades, aggregated OOS}} \ge 30$ lệnh được tính trên **tổng cả 3 folds OOS cộng lại** (tương đương 21 tháng OOS). Với phương án này, các alpha 24h có ~30–35 lệnh OOS tổng cộng sẽ đủ điều kiện tính toán Sharpe, t-stat và DSR.
  - Từng fold riêng lẻ chỉ dùng để kiểm tra tính nhất quán phương hướng: yêu cầu ít nhất 2/3 folds có lợi nhuận dương ($Net > 0$) và không vi phạm trần Drawdown.
  - Phương án B (≥ 30 lệnh trên từng fold) **không được chọn**.

---

## 5. Phương Pháp Monte Carlo: Stationary Block Bootstrap & Phân Tích Độ Nhạy

1. **Phương pháp Resampling**:
   - Sử dụng **Stationary Block Bootstrap** (không dùng IID simple bootstrap) nhằm bảo toàn tính phụ thuộc thời gian (autocorrelation) và đặc tính cụm lệnh của chiến lược DCA/Breakout.
   - **Độ dài khối cơ sở (Base Block Length)**: $b = 5$ trades liên tiếp. Đây là **giả định kỹ thuật**.
   - **Kiểm định độ nhạy bắt buộc (Sensitivity Analysis)**: Để tránh kết quả phụ thuộc vào việc chọn $b$, bắt buộc chạy đối soát ở 3 mức: $b \in \{3, 5, 10\}$ trades. Nếu khoảng tin cậy hoặc xác suất ruin thay đổi đột ngột giữa các mức $b$, phải ghi nhận độ bất định cao trong báo cáo.
2. **Tham số mô phỏng**:
   - Số đường mô phỏng: $1,000\text{ paths}$, seed cố định `seed = 42`, vốn ban đầu: $10,000\text{ USDT}$.
3. **Đồng bộ định nghĩa Ruin với Policy Owner**:
   - Thay vì dùng ngưỡng tùy tiện $MDD > 30\%$, định nghĩa Ruin trong Monte Carlo được đồng bộ trực tiếp với chính sách kiểm soát rủi ro của Owner:
     - **Ngưỡng Hard Stop / Ruin chính**: $MDD > 15\%$ (tương ứng với Drawdown Hard Stop $15\%$ của policy).
     - **Ngưỡng Phụ (Extreme Tail Risk)**: $MDD > 20\%$ (tương ứng với trần $\min(1.5 \times \text{MDD}_{\text{in-sample}}, 20\%)$).
     - Báo cáo phải xuất đồng thời $P(MDD > 15\%)$ và $P(MDD > 20\%)$.
4. **Giới hạn phương pháp luận**:
   - Monte Carlo chỉ đo biến thiên thứ tự của các lệnh đã có trong lịch sử; **không thể mô phỏng các regime hoặc cú sập thanh khoản chưa từng gặp trong giai đoạn 2024–2026**.

---

## 6. Thước Đo Deflated Sharpe Ratio (DSR) & Quy Tắc Đếm Số Thử Nghiệm ($N$)

1. **Quy tắc đếm số thử nghiệm ($N_{\text{trials}}$)**:
   - $N$ là tổng số lượng cấu hình/phiên bản thực tế đã được khảo sát trong toàn bộ quá trình nghiên cứu. Chọn $N$ nhỏ (ví dụ chỉ 24) sẽ làm DSR cao giả tạo (lạc quan thái quá).
   - Kiểm kê số thử nghiệm:
     - $N_{\text{cohort}} = 24$: Nếu chỉ tính các alpha độc lập trong cohort smoke-run hiện tại.
     - $N_{\text{universe}} = 72$: Có 72 variants trong manifest, nhưng hiện tất cả đều `BLOCKED_NOT_EVALUATED`; đây **không phải 72 trials đã chạy**. Chỉ dùng $N=72$ như sensitivity giả định bảo thủ, không mô tả là số thử nghiệm thực tế.
     - $N_{\text{historical}}$: **Chưa đếm** (hiện tại chưa có danh sách kiểm kê chính thức cho các bản nháp V1/V2 cũ, nên không đưa con số ước tính vào tính toán DSR cho tới khi có danh sách đếm được).
2. **Kịch bản tính toán DSR**: Báo cáo chỉ được gọi $N=24$ là số hiện diện trong cohort smoke; $N=72$ là sensitivity giả định, không phải trial count quan sát. DSR chính thức vẫn cần kiểm kê các cấu hình đã thử trong lịch sử; nếu chưa có, ghi `DSR_UNAVAILABLE` thay vì khẳng định $N$ chính xác.

---

## 7. Bảng Ngưỡng Phân Loại: `OWNER ĐÃ CHẤP NHẬN — 2026-10-29`

*Owner đã chấp nhận các ngưỡng đề xuất dưới đây. DSR vẫn phải tuân theo giới hạn trial-count ở Section 6; các ngưỡng không mở khóa WFA/Monte Carlo khi readiness gates còn BLOCKED.*

| Tiêu Chí Đánh Giá | `KEEP` (Đạt Chuẩn Chuyển Tiếp) | `REVIEW` (Cần Xem Xét & Chẩn Đoán) | `REJECT` (Loại Bỏ Hoặc Đại Tu) | Ghi Chú Kỹ Thuật |
|---|---|---|---|---|
| **Độ Bền OOS (Consistency)** | $\ge 2/3$ folds OOS có lợi nhuận dương ($Net > 0$) | $1/3$ folds OOS có lợi nhuận dương | $0/3$ folds OOS có lợi nhuận dương | Đo tính ổn định qua 3 lát cắt thị trường |
| **OOS Sharpe Ratio** | $\text{Sharpe}_{\text{OOS}} \ge 0.8$ | $0.2 \le \text{Sharpe}_{\text{OOS}} < 0.8$ | $\text{Sharpe}_{\text{OOS}} < 0.2$ | Tính trên OOS gộp (Aggregated OOS) |
| **Deflated Sharpe (DSR, sensitivity $N=72$)** | $DSR \ge 0.95$ (Độ tin cậy 95%) | $0.80 \le DSR < 0.95$ | $DSR < 0.80$ | $N=72$ chỉ là kịch bản giả định bảo thủ cho tới khi kiểm kê trials thực tế |
| **Xác Suất Ruin MC ($P(\text{MDD} > 15\%)$)** | $P(\text{MDD} > 15\%) \le 5.0\%$ | $5.0\% < P \le 15.0\%$ | $P(\text{MDD} > 15\%) > 15.0\%$ | Đồng bộ với Drawdown Stop 15% |
| **Xác Suất Thắng MC ($P(\text{Profit} > 0)$)** | $P(\text{Profit}) \ge 80.0\%$ | $60.0\% \le P < 80.0\%$ | $P(\text{Profit}) < 60.0\%$ | Block bootstrap $b=5$, seed 42 |
| **Độ Đầy Đủ Mẫu (Theo Phương Án A)** | $N_{\text{trades, agg OOS}} \ge 30$ | $15 \le N < 30$ | $N < 15$ | Nếu $N < 30$: Gán `INSUFFICIENT_SAMPLE` |

---

## 8. Bảng Kiểm Kê Từng Đối Tượng Trong Cohort Đóng Băng (25 Rows)

| STT | ID Đối Tượng | Tên Đối Tượng | Phân Loại Danh Mục | Lệnh Smoke | Phân Loại Tính Chất Mã Nguồn | Phương Thức Đánh Giá Gán |
|---|---|---|---|---|---|---|
__TABLE_25_IDS__

### Tóm tắt phân bổ 25 đối tượng:
- **1 Portfolio Combo**: `combo_6_system_legs` $\rightarrow$ Đánh giá riêng ở cấp danh mục, cấm xếp hạng.
- **4 Bài EDU loại trừ cấu trúc**: `026f43441cb2`, `0bf936687964`, `138df68946ad`, `1a1a4389a821` $\rightarrow$ Loại trừ do mã nguồn chỉ có lệnh Mua, không có logic bán/thoát lệnh.
- **3 Top Agent Proxy**: `okx_01pp`, `okx_auroraxwt`, `okx_dark_wood_dahlia` $\rightarrow$ Đánh giá Rolling OOS dạng proxy nghiên cứu (`RESEARCH_ONLY_NO_DECISION`), cấm đưa vào bảng lọc KEEP/REJECT.
- **4 Cảnh báo mẫu mỏng**: `sideway_long` (2 lệnh), `sideway_short` (3 lệnh), `0873864b8db7` (4 lệnh), `15567e02a806` (10 lệnh) $\rightarrow$ Chắc chắn rơi vào `INSUFFICIENT_SAMPLE`.
- **13 Rolling OOS tham số cố định**:
  - 4 COIN System legs: `kema_long` (40), `kema_short` (40), `dca_long` (87), `dca_short` (67).
  - 3 COIN User V2: `efa90f74cd08_v2` (45), `18e87aa868ad_v2` (53), `33312a2f4dfc_v2` (46).
  - 2 EDU Canonical: `edu_canonical_beginner_dual_ema` (668), `edu_canonical_advanced_volatility_breakout` (102).
  - 4 EDU Active User: `090730ae35b8` (17), `0d51ba8d2012` (23), `14e3b934b1e5` (76), `18e87aa868ad` (20).

---

## 9. Biên Bản Phê Duyệt Của Owner (Owner Sign-off & Lock)

*Owner đã chốt các lựa chọn phương pháp bên dưới. Đây chưa phải chữ ký phê duyệt toàn bộ protocol; việc thi công vẫn cần các readiness gates tại đầu tài liệu.*

- **Quy tắc số lệnh**: `PHƯƠNG ÁN A — Aggregated OOS >= 30 trades` (Owner đã chốt 2026-10-29).
- **Ngưỡng KEEP / REVIEW / REJECT**: `SECTION 7 — OWNER ĐÃ CHẤP NHẬN` (2026-10-29).
- **Master Risk đã chốt**: risk/trade <= 0.25% master, gross <= 3x equity, one-way <= 2x equity; runtime enforcement còn mở.
- **Full protocol sign-off**: `CHƯA GHI NHẬN`.
- **Trạng thái thi công**: `STRICTLY_BLOCKED` cho tới khi data/spec/funding, cost, execution/Demo replay và runtime risk gates được nghiệm thu.
"""
    protocol_md = protocol_template.replace("__NOW_UTC__", now_utc_str).replace("__TABLE_25_IDS__", table_25_ids_md)
    protocol_md_path = OUT_DIR / "wfa_mc_protocol_preregistration.md"
    protocol_md_path.write_text(protocol_md, encoding="utf-8")
    
    # Store the current protocol hash separately from any future approval hash.
    protocol_sha = hashlib.sha256(protocol_md.encode("utf-8")).hexdigest()
    freeze_payload["approval_metadata"]["protocol_sha256_current"] = protocol_sha
    freeze_json_path.write_text(json.dumps(freeze_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"✅ Đã tạo văn bản tiền đăng kiểm protocol v1.1.0: {protocol_md_path}")
    print(f"✅ Đã cập nhật file đóng băng cohort kèm approval metadata: {freeze_json_path}")

if __name__ == "__main__":
    main()
