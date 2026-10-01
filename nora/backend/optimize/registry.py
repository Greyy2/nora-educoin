"""Kho alpha (C3) + xuất cấu hình cho Binance Futures testnet (D).

Kho alpha = các bộ (chiến lược × tài sản × tham số) đã qua ĐỦ gate của scripts/optimize_alphas.py:
WFA (OOS) + Monte Carlo (cháy <= 5%) + holdout 20% cuối có lãi và MDD <= 30%, đòn bẩy <= 10x.
Mỗi mục ghi đủ để tái lập: template, tham số, AST đã thay tham số, số liệu từng giai đoạn,
sha256 dữ liệu 1m, commit code tại thời điểm tối ưu.

Cấu hình testnet mô tả ĐÚNG những gì engine đã mô phỏng (không thêm hành vi mới):
- Tín hiệu đánh giá trên nến ĐÃ ĐÓNG; vào lệnh MARKET ở đầu phút kế tiếp (taker).
- Tầng DCA: lệnh LIMIT post-only (GTX, maker) cách giá khớp tầng trước dca_step_pct.
- Chốt lời: LIMIT reduce-only (maker) tại giá TB × (1 ± tp%). Cắt lỗ: STOP_MARKET reduce-only từ giá TB.
- Trailing / timeout / tín hiệu thoát: đóng MARKET (taker). Ký quỹ ISOLATED.
Tick size / step size / min notional phải lấy từ /fapi/v1/exchangeInfo lúc chạy bot.
"""
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from backend.utils.jsonsafe import json_default

TESTNET = {"exchange": "binance_futures_testnet", "rest": "https://testnet.binancefuture.com",
           "ws": "wss://stream.binancefuture.com", "fees_assumed": {"maker": 0.0002, "taker": 0.0005}}


def _git_revision(repo_dir: str) -> Dict[str, Any]:
    try:
        head = subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", repo_dir, "status", "--porcelain", "nora/backend"],
                                    capture_output=True, text=True).stdout.strip())
        return {"commit": head or None, "dirty_backend": dirty}
    except OSError:
        return {"commit": None, "dirty_backend": None}


def build_registry(results: List[Dict[str, Any]], spaces: List[Dict[str, Any]], source: str,
                   repo_dir: Optional[str] = None, robustness: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.core.strategy.params_template import resolve_placeholders, split_params
    from backend.db.local_pkl import read_manifest

    by_id = {s["id"]: s for s in spaces}
    alphas = []
    for r in results:
        if r.get("verdict") != "ALPHA":
            continue
        sd = by_id[r["space"]]
        params = dict(r["final_params"])
        signal, position = split_params(params)
        tree = resolve_placeholders(sd["tree"], signal)
        manifest = read_manifest(r["data_symbol"]) or {}
        alphas.append({
            "alpha_id": f"{r['space']}__{r['symbol']}",
            "strategy": r["space"],
            "family": sd["family"],
            "side": sd["side"],
            "symbol": r["symbol"],
            "data_symbol": r["data_symbol"],
            "price_source": r.get("price_source"),
            "market": position.get("market", "spot"),
            "position": position,
            "signal_params": signal,
            "flows": [{"id": r["space"], "name": f"{sd['side']} {r['space']}", "type": sd["side"],
                       "ast": {"type": sd["side"], "match": [{"condition": tree}], "stop": []}}],
            "evidence": {"windows": r.get("windows"), "screen": r.get("screen"), "wfa": r.get("wfa"),
                         "monte_carlo": r.get("mc"), "monte_carlo_trades": r.get("mc_trades"), "holdout": r.get("holdout"), "checks": r.get("checks"),
                         "configs_tried": r.get("configs_tried"), "space_size": r.get("space_size")},
            "robustness": (robustness or {}).get(f"{r['space']}__{r['symbol']}"),
            "data": {"sha256_1m": manifest.get("sha256_1m"), "start_ts": manifest.get("start_ts"),
                     "end_ts": manifest.get("end_ts"), "exchange": manifest.get("exchange")},
        })
    return {
        "generated_at": int(time.time() * 1000),
        "source_optimization": source,
        "code": _git_revision(repo_dir) if repo_dir else None,
        "gates": {"wfa": "acceptance_gate_passed", "mc_ruin_max_pct": 5.0, "mc_basis": "daily", "holdout_mdd_max_pct": 30.0,
                  "leverage_max": 10},
        "pairs_evaluated": len(results),
        "alphas": alphas,
    }


def testnet_config(alpha: Dict[str, Any]) -> Dict[str, Any]:
    """Cấu hình chạy Binance Futures testnet cho một alpha perp."""
    if alpha["market"] != "perp":
        raise ValueError(f"{alpha['alpha_id']}: testnet Binance Futures chỉ nhận alpha market=perp")
    pos = alpha["position"]
    short = alpha["side"] == "SHORT"
    return {
        **TESTNET,
        "alpha_id": alpha["alpha_id"],
        "symbol": f"{alpha['symbol']}USDT",
        "margin_type": "ISOLATED",
        "leverage": int(pos.get("leverage", 1)),
        "position_side": "SHORT" if short else "LONG",
        "sizing": {"order_size_pct_of_equity": pos.get("order_size_pct", 100.0),
                   "note": "ký quỹ lệnh đầu = % vốn hiện tại; notional = ký quỹ × đòn bẩy"},
        "entry": {"order_type": "MARKET", "when": "đầu phút kế tiếp sau khi tín hiệu đúng trên nến 1m đã đóng",
                  "signal_flows": alpha["flows"]},
        "dca": {"enabled": float(pos.get("dca_step_pct", 0) or 0) > 0 and int(pos.get("dca_max_layers", 0) or 0) > 0,
                "step_pct_from_last_fill": pos.get("dca_step_pct", 0.0),
                "max_layers": pos.get("dca_max_layers", 0),
                "size_multiplier": pos.get("dca_size_multiplier", 1.0),
                "order_type": "LIMIT", "time_in_force": "GTX"},
        "take_profit": {"pct_from_avg": pos.get("take_profit_rate", 0.0), "order_type": "LIMIT", "reduce_only": True},
        "stop_loss": {"pct_from_avg": pos.get("stop_loss_rate", 0.0), "order_type": "STOP_MARKET", "reduce_only": True},
        "trailing": {"pct_from_peak": pos.get("trailing_stop", 0.0),
                     "activation_pct": pos.get("trailing_activation_pct", 0.0), "order_type": "MARKET"},
        "timeout_minutes": pos.get("timeout", 0),
        "risk_limits": {"kill_switch_drawdown_pct": 30.0, "max_leverage": 10},
        "backtest_evidence": alpha["evidence"],
        "exchange_filters": "lấy tickSize / stepSize / minNotional từ /fapi/v1/exchangeInfo khi khởi động",
    }


def write_registry(registry: Dict[str, Any], out_dir: str) -> List[str]:
    os.makedirs(os.path.join(out_dir, "testnet"), exist_ok=True)
    written = [os.path.join(out_dir, "registry.json")]
    with open(written[0], "w", encoding="utf-8") as fh:
        json.dump(registry, fh, ensure_ascii=False, indent=2, default=json_default)
    for alpha in registry["alphas"]:
        if alpha["market"] == "perp":
            path = os.path.join(out_dir, "testnet", f"{alpha['alpha_id']}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(testnet_config(alpha), fh, ensure_ascii=False, indent=2, default=json_default)
            written.append(path)
    return written
