"""Đưa alpha FINAL vào kho alpha (data/alphas/registry.json) kèm hệ số s và bằng chứng của phễu + cấu hình testnet.

KHÔNG đổi định dạng registry: alpha ghi cùng các khoá như backend/optimize/registry.build_registry (alpha_id, strategy, family, side, symbol, market,
position, signal_params, flows, evidence, data ...) cộng MỘT khoá mới `funnel` chứa bằng chứng. Alpha của phễu chạy trên CẢ vũ trụ (danh mục) nên
`symbol` = "PORTFOLIO"; cấu hình testnet là cấu hình danh mục một chiến lược (cùng định dạng testnet/book.json: book_export.testnet_book_config).
Ghi lại cùng alpha_id (alpha đã đưa vào trước đó) = thay thế mục cũ (idempotent).
"""
import json
import os
import time
from typing import Any, Dict, Optional

from backend.utils.jsonsafe import json_default

from . import sizing
from .storage import RunStore


def registry_alpha_id(strategy: str, alpha_id: str) -> str:
    return f"funnel__{strategy}__{alpha_id}"


def _atomic_dump(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=json_default)
    os.replace(tmp, path)


def promote_alpha(run_dir: str, alpha_id: str, alphas_dir: str, note: Optional[str] = None) -> Dict[str, Any]:
    """-> {"registry_path", "alpha_id", "registry_alpha_id", "final_scale", "testnet_config"}. ValueError nếu alpha chưa FINAL."""
    from backend.core.strategy import book as sb
    from backend.optimize.book_export import testnet_book_config
    from backend.optimize.registry import build_registry
    store = RunStore(run_dir, read_only=True)
    try:
        alpha = store.get_alpha(alpha_id)
        run = store.read_run()
        stages = store.alpha_metrics(alpha_id)
        mc = store.read_mc(alpha_id)
    finally:
        store.close()
    if alpha is None:
        raise KeyError(alpha_id)
    if alpha["stage_reached"] != "FINAL" or alpha["rejected_stage"] or alpha["final_scale"] is None:
        raise ValueError(f"alpha chưa đạt FINAL (dừng ở {alpha['stage_reached']}, loại: {alpha['reject_code']})")
    s = float(alpha["final_scale"])
    rpt = sizing.risk_for_scale(s)
    cand = {c["id"]: c for c in sb.CANDIDATES}[alpha["strategy"]]
    st = sb.materialize(cand, alpha["params"], risk_per_trade_pct=rpt, stop_fill="level")
    cfg = run.get("config", {})
    reg_id = registry_alpha_id(alpha["strategy"], alpha_id)
    funnel = {
        "run_id": run.get("run_id"), "alpha_id": alpha_id, "final_scale": s, "risk_per_trade_pct": rpt, "params": alpha["params"],
        "universe": cfg.get("symbols"), "windows": cfg.get("windows"), "data_sha256": cfg.get("data_sha256"), "commit": cfg.get("commit"),
        "thresholds": cfg.get("thresholds"), "stage_metrics": stages,
        "monte_carlo": {"summary": ((mc or {}).get("mc") or {}).get("summary"), "gate": ((mc or {}).get("mc") or {}).get("gate"),
                        "scale_search": (mc or {}).get("scale_search"), "verified": (mc or {}).get("verified")},
        "promoted_at": int(time.time() * 1000), "note": note,
    }
    entry = {
        "alpha_id": reg_id, "strategy": alpha["strategy"], "family": cand["family"], "side": cand["side"], "symbol": "PORTFOLIO",
        "data_symbol": None, "price_source": None, "market": "perp", "position": st["position"], "signal_params": st["signal_params"],
        "flows": [{"id": alpha["strategy"], "name": f"{cand['side']} {alpha['strategy']}", "type": cand["side"],
                   "ast": {"type": cand["side"], "match": [{"condition": st["tree"]}], "stop": []}}],
        "evidence": {"windows": cfg.get("windows"), "funnel": {k: stages.get(k) for k in ("S1_backtest", "S3_wfa", "S6_holdout")}},
        "robustness": None, "data": {"sha256_1m": cfg.get("data_sha256"), "exchange": "binance_usdm"},
        "funnel": funnel,
    }
    reg_path = os.path.join(alphas_dir, "registry.json")
    try:
        with open(reg_path, encoding="utf-8") as fh:
            registry = json.load(fh)
    except FileNotFoundError:
        repo = os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
        registry = build_registry([], [], source=run_dir, repo_dir=repo)
    alphas = [a for a in registry.get("alphas", []) if a.get("alpha_id") != reg_id]
    alphas.append(entry)
    registry["alphas"] = alphas
    registry["generated_at"] = int(time.time() * 1000)
    _atomic_dump(reg_path, registry)

    book = {"universe": cfg.get("symbols") or [f"{u}@perp" for u in sb.UNIVERSE], "risk_per_trade_pct": rpt, "risk": sb.RISK,
            "strategies": [{"id": cand["id"], "side": cand["side"], "flow": entry["flows"][0]["ast"], "position": st["position"]}],
            "evidence": {"funnel": funnel}}
    testnet_path = os.path.join(alphas_dir, "testnet", f"{reg_id}.json")
    _atomic_dump(testnet_path, {**testnet_book_config(book), "funnel_alpha_id": alpha_id, "final_scale": s})
    return {"registry_path": reg_path, "alpha_id": alpha_id, "registry_alpha_id": reg_id, "final_scale": s, "testnet_config": testnet_path}
