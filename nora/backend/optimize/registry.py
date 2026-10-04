"""Kho alpha (C3) + xuất cấu hình cho Binance Futures testnet (D).

Kho alpha = các bộ (chiến lược × tài sản × tham số) đã qua ĐỦ gate của backend/optimize/optimize_alphas.py:
WFA (OOS) + Monte Carlo (cháy <= 5%) + holdout 20% cuối có lãi và MDD <= 30%, đòn bẩy <= 10x.
Mỗi mục ghi đủ để tái lập: template, tham số, AST đã thay tham số, số liệu từng giai đoạn,
sha256 dữ liệu 1m, commit code tại thời điểm tối ưu.

Cấu hình testnet mô tả ĐÚNG những gì engine đã mô phỏng (không thêm hành vi mới):
- Tín hiệu đánh giá trên nến ĐÃ ĐÓNG; vào lệnh MARKET ở đầu phút kế tiếp (taker).
- Tầng DCA: lệnh LIMIT post-only (GTX, maker) cách giá khớp tầng trước dca_step_pct.
- Chốt lời: LIMIT reduce-only (maker) tại giá TB × (1 ± tp%). Cắt lỗ: STOP_MARKET reduce-only từ giá TB.
- Trailing / timeout / tín hiệu thoát: đóng MARKET (taker). Ký quỹ ISOLATED.
Tick size / step size / min notional phải lấy từ /fapi/v1/exchangeInfo lúc chạy bot.

Sổ chiến lược: ghi book.json / testnet, xuất bản (book_export):
Xuất sổ chiến lược đã chốt: data/alphas/book.json (tái lập backtest) + data/alphas/testnet/book.json (bot Binance Futures testnet).

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
import shutil
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
    from backend.core.params.template import resolve_placeholders, split_params
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


# ─── Sổ chiến lược: ghi book.json / testnet, xuất bản (book_export) ────────
def _is_true(v) -> bool:
    """Chặt chẽ: chỉ True thật (hoặc chuỗi "True" của báo cáo cũ do default=str); chuỗi 'False' KHÔNG được coi là đúng."""
    return v is True or v == "True"


def build_book(report: Dict[str, Any], source: str, repo_dir: str = None) -> Dict[str, Any]:
    from backend.core.strategy.book import UNIVERSE, materialize, BY_ID
    book = report["book"]
    holdout_pass = _is_true(book.get("holdout_pass"))
    by_id = BY_ID
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
        "timeframe": report.get("timeframe", "1m"),
        "data_exchange": report.get("data_exchange", "binance"),
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
        "holdout_pass": holdout_pass,
        "status": "READY_FOR_TESTNET" if holdout_pass else "HOLDOUT_FAILED",
        "rejected_candidates": {k: v for k, v in report["candidates"].items() if not _is_true(v.get("accepted"))},
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
    """Luôn ghi book.json; CHỈ ghi testnet/book.json khi holdout đạt. Holdout trượt -> xoá testnet/book.json cũ (nếu có)."""
    book = build_book(report, source, repo_dir)
    os.makedirs(out_dir, exist_ok=True)
    paths = [os.path.join(out_dir, "book.json")]
    with open(paths[0], "w", encoding="utf-8") as fh:
        json.dump(book, fh, ensure_ascii=False, indent=2, default=json_default)
    testnet_path = os.path.join(out_dir, "testnet", "book.json")
    if book["holdout_pass"]:
        os.makedirs(os.path.dirname(testnet_path), exist_ok=True)
        with open(testnet_path, "w", encoding="utf-8") as fh:
            json.dump(testnet_book_config(book), fh, ensure_ascii=False, indent=2, default=json_default)
        paths.append(testnet_path)
    elif os.path.exists(testnet_path):
        os.remove(testnet_path)
        print(f"holdout KHÔNG đạt: đã xoá {testnet_path} cũ (không cấp cấu hình testnet cho sổ trượt holdout).")
    return paths


EXPLORE_STATUS = "EXPLORE_DEMO"


def write_explore_book(report: Dict[str, Any], out_dir: str, source: str, repo_dir: str = None) -> List[str]:
    """Sổ THỬ NGHIỆM (alpha chưa chắc qua đủ cổng) -> out_dir/book.json, status EXPLORE_DEMO: chỉ chạy paper/demo, không có testnet/live."""
    book = build_book(report, source, repo_dir)
    book["status"] = EXPLORE_STATUS
    book["unvalidated"] = sorted(k for k, v in report["candidates"].items() if not v.get("validated"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "book.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(book, fh, ensure_ascii=False, indent=2, default=json_default)
    return [path]


def publish_book(src_dir: str, dest_dir: str) -> Dict[str, Any]:
    """Xuất bản một sổ đã dựng (src_dir/book.json [+ testnet/book.json]) sang dest_dir (thư mục data/alphas/ đang dùng).

    Cùng quy tắc write_book: testnet/book.json CHỈ có khi sổ nguồn có (holdout đạt); nếu không thì xoá testnet/book.json cũ ở đích.
    Ghi qua file tạm + os.replace nên người đọc không thấy file dở dang. Thiếu src_dir/book.json -> FileNotFoundError."""
    src_book = os.path.join(src_dir, "book.json")
    if not os.path.isfile(src_book):
        raise FileNotFoundError(src_book)
    src_testnet = os.path.join(src_dir, "testnet", "book.json")
    dst_book = os.path.join(dest_dir, "book.json")
    dst_testnet = os.path.join(dest_dir, "testnet", "book.json")

    def _copy(src: str, dst: str) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)

    with open(src_book, encoding="utf-8") as fh:
        book = json.load(fh)
    _copy(src_book, dst_book)
    written, removed = [dst_book], False
    if os.path.isfile(src_testnet):
        _copy(src_testnet, dst_testnet)
        written.append(dst_testnet)
    elif os.path.exists(dst_testnet):
        os.remove(dst_testnet)
        removed = True
    return {"status": book.get("status"), "holdout_pass": book.get("holdout_pass"), "generated_at": book.get("generated_at"),
            "strategies": [s.get("id") for s in book.get("strategies", [])], "written": written, "testnet_removed": removed}
