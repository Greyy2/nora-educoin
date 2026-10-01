"""Xuất sổ chiến lược đã chốt: alphas/book.json (tái lập backtest) + alphas/testnet/book.json (bot Binance Futures testnet).

Cấu hình testnet mô tả ĐÚNG hành vi đã mô phỏng trong PortfolioEngine:
- Tín hiệu trên nến đã đóng -> vào MARKET đầu phút kế tiếp; ATR% = natr(atr_period) của nến atr_frame đã đóng.
- Khoảng SL = stop_loss_rate × ATR%; danh nghĩa = vốn × risk_per_trade% / (SL% + 2 × (taker + trượt)),
  chặn bởi max_notional_pct% vốn và phần còn lại của trần tổng danh nghĩa (max_gross_exposure × vốn).
- Đòn bẩy = min(max_leverage, floor(1 / (1,5 × SL + mmr))) — giá thanh lý luôn cách xa hơn SL; ký quỹ ISOLATED.
- SL STOP_MARKET reduce-only; trailing (bội số ATR) đóng MARKET; TP LIMIT reduce-only (nếu có); timeout đóng MARKET.
- Giới hạn danh mục: max_positions, max_per_symbol, kill switch khi vốn MTM sụt kill_switch_dd_pct% từ đỉnh.
"""
import json
import os
import time
from typing import Any, Dict, List

from backend.alpha.registry import TESTNET, _git_revision


def build_book(report: Dict[str, Any], source: str, repo_dir: str = None) -> Dict[str, Any]:
    from backend.alpha.strategy_book import CANDIDATES, UNIVERSE, materialize
    book = report["book"]
    by_id = {c["id"]: c for c in CANDIDATES}
    strategies = []
    for item in book["strategies"]:
        cand = by_id[item["id"]]
        st = materialize(cand, item["params"], risk_per_trade_pct=book["risk_per_trade_pct"], stop_fill="level")
        strategies.append({
            "id": cand["id"], "family": cand["family"], "side": cand["side"], "description": cand["description"],
            "params": item["params"], "signal_params": st["signal_params"], "position": st["position"],
            "flow": {"type": cand["side"], "match": [{"condition": st["tree"]}], "stop": []},
            "evidence": report["candidates"][cand["id"]],
        })
    return {
        "generated_at": int(time.time() * 1000),
        "source": source,
        "code": _git_revision(repo_dir) if repo_dir else None,
        "universe": [f"{s}@perp" for s in UNIVERSE],
        "windows": report["windows"],
        "gates": report["gates"],
        "risk": book["risk"],
        "risk_per_trade_pct": book["risk_per_trade_pct"],
        "risk_scale_bootstrap": book["risk_scale_bootstrap"],
        "strategies": strategies,
        "evidence": {"dev2_base_risk": book["dev2_base_risk"], "final": book["final"]},
        "holdout_pass": book["holdout_pass"],
        "rejected_candidates": {k: v for k, v in report["candidates"].items() if not v.get("accepted")},
    }


def testnet_book_config(book: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **TESTNET,
        "kind": "portfolio_book",
        "symbols": [s.split("@")[0] + "USDT" for s in book["universe"]],
        "margin_type": "ISOLATED",
        "sizing": {
            "mode": "risk", "risk_per_trade_pct_of_equity": book["risk_per_trade_pct"],
            "formula": "notional = equity × risk% / (SL% + 2 × (taker + slippage)); "
                       "leverage = min(max, floor(1 / (1.5 × SL + mmr)))",
        },
        "portfolio_limits": book["risk"],
        "strategies": [{
            "id": s["id"], "side": s["side"], "signal_flow": s["flow"],
            "atr": {"frame": s["position"]["atr_frame"], "period": s["position"]["atr_period"],
                    "kernel": "natr (ATR Wilder / close × 100), nến đã đóng"},
            "exits_in_atr_multiples": {k: s["position"].get(k, 0) for k in
                                       ("stop_loss_rate", "take_profit_rate", "trailing_stop", "trailing_activation_pct")},
            "timeout_minutes": s["position"].get("timeout", 0),
            "max_leverage": s["position"]["leverage"], "max_notional_pct": s["position"]["max_notional_pct"],
            "orders": {"entry": "MARKET", "stop_loss": "STOP_MARKET reduce-only", "trailing": "MARKET",
                       "take_profit": "LIMIT reduce-only", "timeout": "MARKET"},
        } for s in book["strategies"]],
        "backtest_evidence": book["evidence"],
        "exchange_filters": "lấy tickSize / stepSize / minNotional từ /fapi/v1/exchangeInfo khi khởi động",
    }


def write_book(report: Dict[str, Any], out_dir: str, source: str, repo_dir: str = None) -> List[str]:
    book = build_book(report, source, repo_dir)
    os.makedirs(os.path.join(out_dir, "testnet"), exist_ok=True)
    paths = [os.path.join(out_dir, "book.json"), os.path.join(out_dir, "testnet", "book.json")]
    with open(paths[0], "w", encoding="utf-8") as fh:
        json.dump(book, fh, ensure_ascii=False, indent=2, default=str)
    with open(paths[1], "w", encoding="utf-8") as fh:
        json.dump(testnet_book_config(book), fh, ensure_ascii=False, indent=2, default=str)
    return paths
