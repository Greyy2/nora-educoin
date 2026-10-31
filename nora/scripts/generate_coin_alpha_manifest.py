#!/usr/bin/env python3
"""Script kiểm kê read-only 6 candidate COIN Alpha.
Chạy: python scripts/generate_coin_alpha_manifest.py
Ghi ra nora/check/coin_alpha_manifest.json
Không chạy backtest, không sửa dữ liệu.
"""
import hashlib, json, os, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COIN_ROOT = os.path.join(REPO, "nora", "coin")
sys.path.insert(0, COIN_ROOT)
os.environ.setdefault("NORA_PRODUCT", "coin")
os.environ.setdefault("NORA_DIR", COIN_ROOT)
os.environ.setdefault("NORA_LOCAL_DATA_ROOT", os.path.join(COIN_ROOT, "data"))
os.environ.setdefault("NORA_LOCAL_LOGS_ROOT", "/tmp/nora_logs")
os.environ.setdefault("NORA_JWT_SECRET", "test-secret-for-manifest-only")

from backend.analys.alpha.code.compile import load_system_strategies
from backend.analys.param import BASE_POSITION

loaded = load_system_strategies()
candidates = loaded["candidates"]
strategies = loaded["strategies"]
sources = loaded["sources"]

def summarise_position(position_override, base):
    merged = {**base, **position_override}
    keys = ["exit_unit", "atr_frame", "cooldown", "sizing", "risk_per_trade_pct",
            "max_notional_pct", "market", "stop_fill"]
    out = {}
    for k in keys:
        v = merged.get(k)
        src = "strategy_file" if k in position_override else "BASE_POSITION"
        if v is not None:
            out[k] = {"value": v, "source": src}
    return out

def extract_params_summary(schema):
    rows = []
    for k, v in (schema or {}).items():
        row = {"key": k, "label": v.get("label_vi", k), "default": v.get("default"),
               "type": v.get("type"), "group": v.get("group", "signal")}
        if v.get("min") is not None:
            row["range"] = [v["min"], v["max"]]
        if v.get("grid"):
            row["grid"] = v["grid"]
        rows.append(row)
    return rows

manifest_rows = []
for cand in candidates:
    cid = cand["id"]
    src = sources.get(cid, {})
    schema = cand.get("params_schema", {})
    tf_keys = [k for k, v in schema.items() if v.get("type") == "choice" and "tf" in k]
    has_dca = any("dca" in k for k in schema)
    dca_keys = {k: {"default": v.get("default"), "group": v.get("group")} for k, v in schema.items() if "dca" in k}
    gate_keys = [k for k in schema if "gate" in k]
    position_override = cand.get("position", {})
    effective_position = summarise_position(position_override, BASE_POSITION)
    row = {
        "id": cid, "side": cand.get("side"), "family": cand.get("family"),
        "description": cand.get("description"),
        "source": {"file": os.path.relpath(src.get("file",""), REPO) if src.get("file") else None,
                   "sha256": src.get("sha256",""), "code_hash": src.get("code_hash","")},
        "timeframe_params": tf_keys,
        "has_dca": has_dca, "dca_params": dca_keys if has_dca else {},
        "dca_gate_params": gate_keys if has_dca else [],
        "position_effective": effective_position,
        "position_source_note": (
            "exit_unit='atr' TUONG MINH trong file DSL."
            if "exit_unit" in position_override else
            "exit_unit/atr_frame KE THUA BASE_POSITION (exit_unit='atr', atr_frame='auto'). "
            "Cần regression xác nhận engine nhận đúng."
        ),
        "executable": True, "record_type": "system_strategy",
        "params_schema_count": len(schema),
        "params_summary": extract_params_summary(schema),
    }
    manifest_rows.append(row)

user_dir = os.path.join(COIN_ROOT, "data", "alpha", "user")
research_dir = os.path.join(COIN_ROOT, "data", "alpha", "research")
book_path = os.path.join(COIN_ROOT, "data", "alpha", "book.json")
user_records = [f for f in os.listdir(user_dir) if f.endswith(".json")] if os.path.isdir(user_dir) else []
research_records = [f for f in os.listdir(research_dir) if f.endswith(".json")] if os.path.isdir(research_dir) else []

top_agents_file = os.path.join(research_dir, "okx_top10_agents.json")
top_agent_count = 0
if os.path.isfile(top_agents_file):
    try:
        ta_data = json.loads(open(top_agents_file).read())
        top_agent_count = len(ta_data.get("bots", []))
    except Exception:
        pass

manifest = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "purpose": "Kiem ke read-only kho Alpha COIN (Buoc 3). Khong chay backtest.",
    "system_candidates": manifest_rows,
    "summary": {
        "system_legs": len(manifest_rows),
        "strategies": len(strategies),
        "user_records": len(user_records),
        "research_files": len(research_records),
        "top_agent_bots": top_agent_count,
        "book_exists": os.path.isfile(book_path),
    },
    "position_contract_notes": {
        "BASE_POSITION_exit_unit": BASE_POSITION.get("exit_unit"),
        "BASE_POSITION_atr_frame": BASE_POSITION.get("atr_frame"),
        "BASE_POSITION_cooldown": BASE_POSITION.get("cooldown"),
        "note": (
            "Kema/Sideway khong khai bao exit_unit trong DSL; ke thua BASE_POSITION. "
            "DCA khai bao tuong minh exit_unit='atr', atr_frame='1h'. "
            "Regression can xac nhan engine nhan dung gia tri qua API."
        ),
    },
    "top_agent_note": (
        "Top Agent la snapshot bao cao OKX. Khong co code executable. "
        "Khong promote/chay bot tu day khi chua co code+contract+kiem chung rieng."
    ),
}

out_path = os.path.join(REPO, "nora", "check", "coin_alpha_manifest.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(f"Manifest: {os.path.relpath(out_path, REPO)}")
print(f"  System legs : {manifest['summary']['system_legs']}")
print(f"  Strategies  : {manifest['summary']['strategies']}")
print(f"  User records: {manifest['summary']['user_records']}")
print(f"  Top agents  : {manifest['summary']['top_agent_bots']}")
