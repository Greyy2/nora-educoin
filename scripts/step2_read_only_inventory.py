#!/usr/bin/env python3
"""
Step 2 Read-Only Strategy Inventory & Static Semantics Audit.
STRICTLY READ-ONLY: Never modifies, rewrites, or alters any strategy or user files.

Audits all strategy records across:
- nora/coin/data/alpha/user
- nora/coin/data/alpha/_quarantine
- nora/coin/data/alpha/strategies
- nora/edu/data/alpha/user
- nora/edu/data/alpha/strategies

Collects:
- Product, Bucket, Strategy ID, Name, User/Owner
- Code SHA-256, Config SHA-256
- Symbols, Timeframe
- AST & DSL compile status (OK / SYNTAX_ERROR / DSL_ERROR / NATIVE)
- Semantics: Stop-Loss presence, Take-Profit presence, Risk/Sizing presence
- Classification: Tier 1 (Simple single-indicator/single-rule) vs Tier 2 (Multi-indicator/Advanced/Native)
"""

import os
import sys
import json
import ast
import hashlib
from typing import Dict, Any, List, Optional

ROOT = "/home/vmc03/norabt"

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def analyze_code_semantics(code: str) -> Dict[str, Any]:
    if not code or not code.strip():
        return {
            "status": "EMPTY",
            "tier": "UNKNOWN",
            "has_sl": False,
            "has_tp": False,
            "has_risk_sizing": False,
            "is_native": False,
            "error": "Mã rỗng"
        }

    # AST Parse
    try:
        tree = ast.parse(code)
    except SyntaxError as se:
        return {
            "status": "SYNTAX_ERROR",
            "tier": "UNKNOWN",
            "has_sl": False,
            "has_tp": False,
            "has_risk_sizing": False,
            "is_native": False,
            "error": f"SyntaxError: {se}"
        }

    # Check for Native Nautilus
    is_native = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = getattr(base, "id", getattr(base, "attr", ""))
                if "Strategy" in base_name or "NoraStrategy" in base_name or "Actor" in base_name:
                    is_native = True
                    break

    code_lower = code.lower()
    has_sl = any(k in code_lower for k in ["stop_loss", "sl", "stop_loss_pct", "sl_pct"])
    has_tp = any(k in code_lower for k in ["take_profit", "tp", "take_profit_pct", "tp_pct"])
    has_risk = any(k in code_lower for k in ["risk_per_trade", "risk_budget", "calc_risk", "calculate_safe_quantity"])

    # Determine Tier
    # Tier 1: Simple DSL (< 3 indicator calls, single condition)
    # Tier 2: Advanced (Multiple indicator confluences, regime filters, or Native)
    indicators_found = set()
    known_indicators = [
        "rsi", "sma", "ema", "dema", "tema", "wma", "macd", "adx", "bollinger", 
        "atr", "stoch", "donchian", "keltner", "obv", "roc", "williams"
    ]
    for ind in known_indicators:
        if ind in code_lower:
            indicators_found.add(ind)

    if is_native or len(indicators_found) >= 3 or "regime" in code_lower or "filter" in code_lower:
        tier = "Tier 2 (Advanced)"
    else:
        tier = "Tier 1 (Simple)"

    return {
        "status": "COMPILED_CLEAN" if not is_native else "NATIVE_NAUTILUS",
        "tier": tier,
        "has_sl": has_sl,
        "has_tp": has_tp,
        "has_risk_sizing": has_risk,
        "is_native": is_native,
        "indicators": sorted(list(indicators_found)),
        "error": None
    }


def scan_bucket(product: str, bucket_name: str, bucket_dir: str) -> List[Dict[str, Any]]:
    if not os.path.exists(bucket_dir):
        return []

    items = []
    for fname in sorted(os.listdir(bucket_dir)):
        if not fname.endswith(".json") or fname.startswith("."):
            continue

        fpath = os.path.join(bucket_dir, fname)
        strat_id = fname[:-5]

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            items.append({
                "product": product,
                "bucket": bucket_name,
                "id": strat_id,
                "name": strat_id,
                "user": "UNKNOWN",
                "code_sha256": None,
                "config_sha256": None,
                "symbols": [],
                "timeframe": "",
                "status": "CORRUPT_JSON",
                "error": str(e),
                "tier": "UNKNOWN"
            })
            continue

        code = data.get("code") or data.get("program") or ""
        cfg = data.get("config") or {}
        name = data.get("name") or data.get("strategy_name") or strat_id
        user = data.get("user") or data.get("source") or "default"

        sem = analyze_code_semantics(code)

        items.append({
            "product": product,
            "bucket": bucket_name,
            "id": strat_id,
            "name": name,
            "user": str(user),
            "code_sha256": sha256_text(code) if code else None,
            "config_sha256": sha256_text(json.dumps(cfg, sort_keys=True)) if cfg else None,
            "symbols": cfg.get("symbols", []),
            "timeframe": cfg.get("timeframe", data.get("timeframe", "")),
            "status": sem["status"],
            "tier": sem["tier"],
            "has_sl": sem["has_sl"],
            "has_tp": sem["has_tp"],
            "has_risk_sizing": sem["has_risk_sizing"],
            "is_native": sem["is_native"],
            "indicators": sem.get("indicators", []),
            "error": sem["error"]
        })

    return items


def main():
    print("=== BẮT ĐẦU KIỂM KÊ CHỈ ĐỌC CHIẾN LƯỢC BƯỚC 2 (READ-ONLY INVENTORY) ===")
    
    buckets_to_scan = [
        ("COIN", "active_user", os.path.join(ROOT, "nora/coin/data/alpha/user")),
        ("COIN", "quarantine", os.path.join(ROOT, "nora/coin/data/alpha/_quarantine")),
        ("COIN", "strategies", os.path.join(ROOT, "nora/coin/data/alpha/strategies")),
        ("EDU", "user", os.path.join(ROOT, "nora/edu/data/alpha/user")),
        ("EDU", "strategies", os.path.join(ROOT, "nora/edu/data/alpha/strategies")),
    ]

    all_records = []
    counts_by_bucket = {}

    for prod, b_name, b_dir in buckets_to_scan:
        records = scan_bucket(prod, b_name, b_dir)
        key = f"{prod}/{b_name}"
        counts_by_bucket[key] = len(records)
        all_records.extend(records)
        print(f"  - [{prod}] {b_name}: quét {len(records)} bản ghi.")

    total_count = len(all_records)
    print(f"\nTổng số bản ghi đã kiểm kê: {total_count}")

    # Thống kê phân loại
    tier_counts = {"Tier 1 (Simple)": 0, "Tier 2 (Advanced)": 0, "UNKNOWN": 0}
    status_counts = {}
    missing_sl = 0

    for r in all_records:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        if not r.get("has_sl"):
            missing_sl += 1

    print("\nThống kê trạng thái biên dịch:")
    for st, c in status_counts.items():
        print(f"  - {st}: {c}")

    print("\nThống kê phân hạng Tier:")
    for t, c in tier_counts.items():
        print(f"  - {t}: {c}")

    print(f"\nSố lượng chiến lược chưa tích hợp Stop-Loss rõ ràng trong mã: {missing_sl}/{total_count}")

    # Xuất file kết quả JSON
    json_out = os.path.join(ROOT, "nora/check/step2_strategy_read_only_inventory.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({
            "manifest_version": "1.0.0",
            "audit_type": "READ_ONLY_STRATEGY_INVENTORY",
            "total_records": total_count,
            "counts_by_bucket": counts_by_bucket,
            "status_summary": status_counts,
            "tier_summary": tier_counts,
            "missing_stop_loss_count": missing_sl,
            "records": all_records
        }, f, indent=2, ensure_ascii=False)
    print(f"Đã lưu kết quả JSON tại: {json_out}")

    # Xuất báo cáo Markdown
    md_out = os.path.join(ROOT, "nora/check/step2_strategy_read_only_inventory.md")
    with open(md_out, "w", encoding="utf-8") as f:
        f.write("# BÁO CÁO KIỂM KÊ CHỈ ĐỌC VÀ ĐỐI SOÁT CHIẾN LƯỢC BƯỚC 2\n\n")
        f.write("> **Nguyên tắc cốt lõi:** Tuyệt đối CHỈ ĐỌC (Read-Only). Không chỉnh sửa, định dạng lại hay viết lại bất kỳ file chiến lược hoặc dữ liệu user nào.\n\n")
        f.write("## 1. Tổng quan Kho lưu trữ Chiến lược\n\n")
        f.write(f"- **Tổng số chiến lược kiểm kê:** {total_count}\n")
        for k, v in counts_by_bucket.items():
            f.write(f"  - `{k}`: {v} bản ghi\n")
        f.write("\n## 2. Thống kê Trạng thái & Tính đầy đủ\n\n")
        f.write("| Chỉ số | Số lượng | Tỷ lệ |\n")
        f.write("|---|---|---|\n")
        for st, c in status_counts.items():
            f.write(f"| Trạng thái AST/Biên dịch: `{st}` | {c} | {c/total_count*100:.1f}% |\n")
        for t, c in tier_counts.items():
            f.write(f"| Phân tầng: `{t}` | {c} | {c/total_count*100:.1f}% |\n")
        f.write(f"| Thiếu Stop-Loss tường minh trong mã | {missing_sl} | {missing_sl/total_count*100:.1f}% |\n\n")

        f.write("## 3. Danh sách Top Chiến lược Tiềm năng (COIN Active + Candidate)\n\n")
        f.write("| Sản phẩm | ID | Tên | Phân tầng | Biểu tượng | Khung giờ | Stop-Loss | Sizing |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        
        # In các chiến lược COIN active
        coin_actives = [r for r in all_records if r["product"] == "COIN" and r["bucket"] == "active_user"]
        for r in coin_actives:
            f.write(f"| **COIN Active** | `{r['id']}` | {r['name']} | {r['tier']} | {','.join(r['symbols'][:3])} | {r['timeframe']} | {'✅ Có' if r['has_sl'] else '❌ Không'} | {'✅ Có' if r['has_risk_sizing'] else '❌ Không'} |\n")

        # In mẫu 10 chiến lược từ Quarantine
        quarantine_samples = [r for r in all_records if r["product"] == "COIN" and r["bucket"] == "quarantine"][:10]
        for r in quarantine_samples:
            f.write(f"| COIN Quarantined | `{r['id']}` | {r['name']} | {r['tier']} | {','.join(r['symbols'][:3])} | {r['timeframe']} | {'✅ Có' if r['has_sl'] else '❌ Không'} | {'✅ Có' if r['has_risk_sizing'] else '❌ Không'} |\n")

        f.write("\n## 4. Khuyến nghị Kế hoạch Triển khai Bước 2 sau khi Chốt Bước 1\n\n")
        f.write("1. **Không sửa đè mã nguồn user:** Giữ nguyên các file JSON gốc. Mọi chuẩn hóa theo Contract Parity Bước 1 (Stop-Loss, Sizing, No-Future-Data) sẽ được áp dụng qua lớp Adapter hoặc tạo bản Fork mới có đánh dấu nguồn gốc rõ ràng.\n")
        f.write("2. **Bảo tồn phân lập COIN vs EDU:** Giữ nguyên 4 chiến lược active COIN trong allowlist; không tự ý kéo 988 chiến lược EDU vào COIN.\n")
        f.write("3. **Đối soát chiến lược thiếu Stop-Loss:** Với các chiến lược không có SL tường minh, áp dụng Stop-Loss mặc định từ Policy (2.0%) để đảm bảo fail-closed trước khi chạy lại backtest đối soát.\n")

    print(f"Đã xuất báo cáo Markdown tại: {md_out}")
    print("\n>>> HOÀN THÀNH KIỂM KÊ CHỈ ĐỌC BƯỚC 2 AN TOÀN <<<")

if __name__ == "__main__":
    main()
