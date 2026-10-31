#!/usr/bin/env python3
"""
scripts/step6_edu_evo_protocol_and_candidates.py
Thực hiện EDU-EVO-06 & EDU-EVO-07:
1. EDU-EVO-06: Đăng ký trước Research Protocol bất biến (ngưỡng, folds, tiêu chí pass/fail, cgroup limits).
2. EDU-EVO-07: Tạo research-only candidates cho các alpha đủ điều kiện trong hàng đợi điều tra.
   - Lưu tại nora/check/candidates/{aid}/
   - Kiểm tra hash bảo toàn 100% file gốc trong nora/edu/data/alpha/user/.
"""

import os
import sys
import json
import re
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path("/home/vmc03/norabt").resolve()
EDU_DIR = ROOT / "nora/edu"
CHECK_DIR = ROOT / "nora/check"
CANDIDATES_DIR = CHECK_DIR / "candidates"
USER_DIR = EDU_DIR / "data/alpha/user"

CHARTER_PATH = CHECK_DIR / "edu_evolution_charter_manifest.json"
CONFIG_MANIFEST_PATH = CHECK_DIR / "edu_evolution_effective_config_manifest.json"
DIAGNOSIS_PATH = CHECK_DIR / "edu_evolution_diagnosis_dossier.json"
PROTOCOL_PATH = CHECK_DIR / "edu_evolution_research_protocol.json"
CANDIDATES_MANIFEST_PATH = CHECK_DIR / "edu_evolution_candidates_manifest.json"

sys.path.insert(0, str(EDU_DIR))
from backend.analys.alpha.code.compile import compile_code


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    print("=" * 80)
    print("BẮT ĐẦU THỰC HIỆN EDU-EVO-06 & EDU-EVO-07")
    print("=" * 80)

    # Đọc Charter và Diagnosis
    with open(CHARTER_PATH, "r", encoding="utf-8") as f:
        charter = json.load(f)
    investigation_queue = charter.get("investigation_queue", [])
    queue_aids = [x["aid"] for x in investigation_queue]

    with open(CONFIG_MANIFEST_PATH, "r", encoding="utf-8") as f:
        config_manifest = json.load(f)
    records_cfg = config_manifest.get("records", {})

    with open(DIAGNOSIS_PATH, "r", encoding="utf-8") as f:
        diagnosis = json.load(f)
    dossiers = diagnosis.get("dossiers", {})

    # --------------------------------------------------------------------------
    # 1. EDU-EVO-06: Đăng Ký Research Protocol
    # --------------------------------------------------------------------------
    print("\n--- 1. EDU-EVO-06: Đăng Ký Research Protocol (Pre-registered) ---")
    protocol = {
        "protocol_version": "EDU_EVO_PROTOCOL_v1.0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "author": "Antigravity Research & Verification",
        "objectives": "Kiểm tra giả thuyết cải thiện hiệu suất các alpha OOS âm bằng phương pháp khoa học, walk-forward analysis và rào chắn rủi ro chặt chẽ; không data-snooping, không sửa kho gốc.",
        "admission_gates": {
            "min_total_trades": 20,
            "min_trades_per_fold": 5,
            "min_win_rate_pct": 35.0,
            "min_profit_factor": 1.05,
            "min_net_expectancy_usd": 0.0,
            "max_drawdown_pct": 30.0,
            "min_positive_folds_ratio": 0.66,  # Tối thiểu 2/3 folds dương
            "fee_stress_test": {
                "stress_multiplier": 1.5,
                "criterion": "Net return remains positive under 1.5x fee stress"
            }
        },
        "verdict_definitions": {
            "WFA_PASS": "Thỏa mãn toàn bộ admission gates: trades >= 20, Net return > 0, Max DD <= 30%, >= 2/3 folds dương và chịu được phí stress 1.5x.",
            "WFA_FAIL": "Đủ mẫu (>= 20 trades) nhưng vi phạm ít nhất một tiêu chí về lợi nhuận, drawdown, hoặc số fold dương.",
            "INSUFFICIENT_SAMPLE": "Tổng số lệnh < 20 trades trong 3 năm lịch sử; không thể kết luận thống kê.",
            "BLOCKED": "Nằm trong danh sách 27 alpha chưa rõ ý đồ hoặc vi phạm quy tắc an toàn; bị cấm tuning/sweep."
        },
        "wfa_specification": {
            "method": "Anchored Walk-Forward Analysis",
            "folds_count": 3,
            "folds": [
                {
                    "fold_index": 1,
                    "train_start": "2023-10-06",
                    "train_end": "2024-09-30",
                    "test_start": "2024-10-01",
                    "test_end": "2025-05-31",
                    "train_days": 360,
                    "test_days": 242
                },
                {
                    "fold_index": 2,
                    "train_start": "2023-10-06",
                    "train_end": "2025-05-31",
                    "test_start": "2025-06-01",
                    "test_end": "2026-01-31",
                    "train_days": 603,
                    "test_days": 245
                },
                {
                    "fold_index": 3,
                    "train_start": "2023-10-06",
                    "train_end": "2026-01-31",
                    "test_start": "2026-02-01",
                    "test_end": "2026-10-03",
                    "train_days": 848,
                    "test_days": 244
                }
            ]
        },
        "experiment_budget": {
            "max_candidates_per_alpha": 2,
            "max_parameter_trials_per_hypothesis": 3,
            "cgroup_memory_cap": "2GB per backtest process",
            "execution_runner": "nora/edu/ops/run_limited.sh dưới nora.slice"
        },
        "data_provenance": {
            "universe_start": "2023-10-06",
            "universe_end": "2026-10-03",
            "holdout_availability": "NO_UNTOUCHED_HOLDOUT_AVAILABLE",
            "rule": "Không sử dụng bất kỳ khoảng thời gian nào trong 2023-10-06 -> 2026-10-03 làm holdout mới sau khi đã xem trong baseline."
        }
    }

    protocol_str = json.dumps(protocol, sort_keys=True, ensure_ascii=False)
    protocol["protocol_sha256"] = sha256_str(protocol_str)

    with open(PROTOCOL_PATH, "w", encoding="utf-8") as f:
        json.dump(protocol, f, ensure_ascii=False, indent=2)
    print(f"[OK] EDU-EVO-06 PASS: Đã xuất protocol: {PROTOCOL_PATH}")
    print(f"  • Protocol SHA256: {protocol['protocol_sha256'][:16]}...")

    # --------------------------------------------------------------------------
    # 2. EDU-EVO-07: Tạo Candidates Research-Only
    # --------------------------------------------------------------------------
    print("\n--- 2. EDU-EVO-07: Tạo Candidates Research-Only Cho 23 Alpha Hàng Đợi ---")
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)

    candidates_manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol["protocol_sha256"],
        "total_parent_alphas": len(queue_aids),
        "total_candidates": 0,
        "candidates": {}
    }

    # Lưu lại hash ban đầu của toàn bộ 57 user alpha để kiểm tra bất biến
    original_user_hashes = {}
    for p in USER_DIR.glob("*.json"):
        if p.name != "_versions":
            original_user_hashes[p.stem] = sha256_file(p)

    candidate_count = 0

    for aid in queue_aids:
        dossier_item = dossiers.get(aid, {})
        categories = dossier_item.get("assigned_categories", [])
        is_low_sample = "low-sample" in categories

        user_file = USER_DIR / f"{aid}.json"
        raw_user = json.loads(user_file.read_text(encoding="utf-8"))
        code = raw_user.get("code", "")
        cfg = raw_user.get("config", {}) or {}
        pos = cfg.get("position", {}) or {}

        alpha_cand_dir = CANDIDATES_DIR / aid
        alpha_cand_dir.mkdir(parents=True, exist_ok=True)

        candidates_manifest["candidates"][aid] = {
            "parent_name": raw_user.get("name"),
            "is_vinh": raw_user.get("owner_id") == "vinh",
            "assigned_categories": categories,
            "is_low_sample": is_low_sample,
            "variants": []
        }

        # Nếu là low-sample (< 20 trades), không tạo candidate đoán mò, ghi rõ lý do
        if is_low_sample:
            candidates_manifest["candidates"][aid]["status"] = "SKIPPED_LOW_SAMPLE"
            candidates_manifest["candidates"][aid]["notes"] = f"Alpha có {dossier_item.get('performance_metrics', {}).get('total_trades')} trades trong 3 năm (< 20 trades). Thuộc diện INSUFFICIENT_SAMPLE, không được sweep tham số."
            continue

        # Tạo tối đa 2 candidate variants khoa học:
        # Variant 1: Risk & Stop-Loss Rationalization (Giảm risk_per_trade xuống 1.0%, stop_loss_pct nới lên 4.5% hoặc exit_unit=pct)
        # Variant 2: Macro Trend Filter (Thêm Close > EMA50 / EMA200 hoặc RSI confirmation)

        # Variant 1: RATIONAL_RISK_SL
        var1_code = code
        # Thay thế risk_per_trade_pct hoặc stop_loss_pct nếu có trong code
        if "risk_per_trade_pct" in var1_code:
            var1_code = re.sub(r"risk_per_trade_pct\s*=\s*[\d\.]+", "risk_per_trade_pct = 1.0", var1_code)
        if "stop_loss_pct" in var1_code:
            var1_code = re.sub(r"stop_loss_pct\s*=\s*[\d\.]+", "stop_loss_pct = 4.0", var1_code)

        # Kiểm tra compile code
        try:
            compile_code(var1_code)
            var1_valid = True
        except Exception as e:
            var1_valid = False
            var1_err = str(e)

        if var1_valid:
            var1_id = f"{aid}_c1_risk_sl"
            var1_cfg = json.loads(json.dumps(cfg))
            var1_cfg.setdefault("position", {})
            var1_cfg["position"]["risk_per_trade_pct"] = 1.0
            var1_cfg["position"]["stop_loss_rate"] = 4.0
            var1_cfg["position"]["exit_unit"] = "pct"
            var1_cfg["position"]["leverage"] = 1

            var1_data = {
                "candidate_id": var1_id,
                "parent_aid": aid,
                "parent_name": raw_user.get("name"),
                "hypothesis": "Hạ rủi ro mỗi lệnh xuống 1.0% và nới stop loss lên 4.0% để tránh bị quét bởi nhiễu biến động nến ngày (intraday wicks).",
                "hypothesis_type": "sizing_and_risk_control",
                "code": var1_code,
                "config": var1_cfg,
                "code_sha256": sha256_str(var1_code),
                "config_sha256": sha256_str(json.dumps(var1_cfg, sort_keys=True))
            }
            cand1_file = alpha_cand_dir / f"{var1_id}.json"
            with open(cand1_file, "w", encoding="utf-8") as f:
                json.dump(var1_data, f, ensure_ascii=False, indent=2)

            candidates_manifest["candidates"][aid]["variants"].append({
                "candidate_id": var1_id,
                "file": str(cand1_file.relative_to(ROOT)),
                "hypothesis_type": "sizing_and_risk_control",
                "code_sha256": var1_data["code_sha256"]
            })
            candidate_count += 1

        # Variant 2: TREND_MOMENTUM_FILTER (Chỉ thêm nếu code có enter_sig)
        var2_code = code
        if "enter_sig =" in var2_code and "ema(close" not in var2_code:
            # Thêm bộ lọc EMA trend
            var2_code = var2_code.replace("def on_bar(self):", "def on_bar(self):\n        trend_filter = close > sma(close, 50)")
            var2_code = var2_code.replace("enter_sig =", "enter_sig = trend_filter &")

        if var2_code != code:
            try:
                compile_code(var2_code)
                var2_valid = True
            except Exception:
                var2_valid = False

            if var2_valid:
                var2_id = f"{aid}_c2_trend_filter"
                var2_cfg = json.loads(json.dumps(cfg))
                var2_cfg.setdefault("position", {})
                var2_cfg["position"]["risk_per_trade_pct"] = 1.0
                var2_cfg["position"]["exit_unit"] = "pct"
                var2_cfg["position"]["leverage"] = 1

                var2_data = {
                    "candidate_id": var2_id,
                    "parent_aid": aid,
                    "parent_name": raw_user.get("name"),
                    "hypothesis": "Thêm bộ lọc xu hướng trung hạn (Close > SMA50) nhằm loại bỏ tín hiệu mua bắt đáy trong xu hướng giảm mạnh.",
                    "hypothesis_type": "trend_filter",
                    "code": var2_code,
                    "config": var2_cfg,
                    "code_sha256": sha256_str(var2_code),
                    "config_sha256": sha256_str(json.dumps(var2_cfg, sort_keys=True))
                }
                cand2_file = alpha_cand_dir / f"{var2_id}.json"
                with open(cand2_file, "w", encoding="utf-8") as f:
                    json.dump(var2_data, f, ensure_ascii=False, indent=2)

                candidates_manifest["candidates"][aid]["variants"].append({
                    "candidate_id": var2_id,
                    "file": str(cand2_file.relative_to(ROOT)),
                    "hypothesis_type": "trend_filter",
                    "code_sha256": var2_data["code_sha256"]
                })
                candidate_count += 1

    candidates_manifest["total_candidates"] = candidate_count

    with open(CANDIDATES_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates_manifest, f, ensure_ascii=False, indent=2)
    print(f"[OK] EDU-EVO-07 PASS: Đã xuất candidates manifest: {CANDIDATES_MANIFEST_PATH}")
    print(f"  • Tổng candidate variants tạo mới: {candidate_count}")

    # 3. Kiểm tra tính toàn vẹn bất biến của kho gốc
    print("\n--- Kiểm tra bảo toàn dữ liệu gốc (100% Files Unmodified) ---")
    intact_count = 0
    for aid, orig_h in original_user_hashes.items():
        curr_h = sha256_file(USER_DIR / f"{aid}.json")
        assert orig_h == curr_h, f"CRITICAL: File gốc {aid}.json đã bị sửa đổi!"
        intact_count += 1
    print(f"[OK] BẢO TOÀN TUYỆT ĐỐI: 100% ({intact_count}/57) file user alpha gốc giữ nguyên hash SHA256!")


if __name__ == "__main__":
    main()
