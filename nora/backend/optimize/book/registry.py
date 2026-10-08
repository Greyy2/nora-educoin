"""Kho alpha + sổ (P9.6): phiên bản engine (engine_version), registry/sổ chính/sổ thử nghiệm/xuất bản (registry), kiểm lại alpha (revalidate), alpha người dùng (user_alphas), tài liệu chiến lược (strategy_doc), Top Agents (đọc file nghiên cứu đã đóng băng).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.core.indicator import REGISTRY
from backend.crawl.store import alpha_dir as alphas_dir
from backend.crawl.store import options, write_job_result
from backend.crawl.store import json_default, read_json
from backend.metrics.charts import BETA_DRIVEN_ID
from backend.optimize.funnel.storage import atomic_write_json
from backend.core.models import NORA_DIR


# ══════════════════════════════════════════════════════════════════════════
# Phiên bản ENGINE (một nguồn duy nhất) cho sổ chiến lược: sổ nào dựng bằng engine khác engine hiện hành thì kết quả (lãi/MDD/bằng chứng) trong sổ
# có thể không còn tái lập được -> giao diện cảnh báo "cần dựng lại".
#
# engine_version() = {"hash": sha256 của ĐẦU VÀO KẾT QUẢ, "commit": git HEAD ngắn, "dirty": có thay đổi chưa commit trong các đầu vào đó, "files": số đầu vào}.
# Đầu vào kết quả (engine_inputs) = (a) file tính toán của engine: backend/core/*.py + optimize/search/evaluate.py (băm byte file), (b) MỖI chiến lược hệ thống: băm IR đã biên dịch
# (cây tín hiệu/stop/position/space của từng chân qua alpha loader) — KHÔNG băm byte file .py nên sửa chú thích/docstring/khoảng trắng không đổi; sửa logic thì đổi.
# Đánh đổi: alpha/compile.py vẫn là trình biên dịch nhưng không băm file; ta băm KẾT QUẢ biên dịch (IR) nên refactor compiler không đổi IR thì không bật cờ, còn sửa compiler làm IR đổi
# thì bật cờ. alpha/contract.py (trợ giúp/gợi ý/sổ tay) không ảnh hưởng kết quả nên không nằm trong. So sánh chỉ dùng `hash`; `commit` để người đọc biết sổ dựng ở đâu.
# Cùng hàm cho mọi nơi ghi (optimize/book/registry.build_book) và đọc (API). Nhớ theo (đường dẫn, mtime_ns, size) của file engine + file chiến lược -> không đọc lại mỗi request.
# ══════════════════════════════════════════════════════════════════════════

ENGINE_COMPUTE_FILES = ("backend/optimize/search/evaluate.py",)    # ngoài backend/core/*.py
REASON_NO_VERSION = "sổ dựng trước khi có phiên bản engine"

GIT_TTL_S = 60.0   # commit / dirty đổi mà không đổi file (git commit) -> làm tươi sau tối đa ngần này giây; hash không phụ thuộc git
_cache: Dict[str, Any] = {"sig": None, "value": None, "at": 0.0}


def _engine_files() -> List[Tuple[str, str]]:
    core = os.path.join(NORA_DIR, "backend", "core")
    rels = [f"backend/core/{n}" for n in sorted(os.listdir(core)) if n.endswith(".py") and n != "__init__.py"] + list(ENGINE_COMPUTE_FILES)
    return [(rel, os.path.join(NORA_DIR, rel)) for rel in rels if os.path.isfile(os.path.join(NORA_DIR, rel))]


def _strategy_ir_hashes() -> List[Tuple[str, str]]:
    """[(chân chiến lược, sha256 của IR biên dịch)] — chỉ phần ảnh hưởng kết quả (bỏ mô tả/nhãn/lược đồ tham số)."""
    from backend.alpha.compile import load_system_strategies
    out = []
    for c in load_system_strategies()["candidates"]:
        ir = {k: c.get(k) for k in ("id", "side", "tree", "stop", "position", "space")}
        out.append((f"strategy:{c['id']}", hashlib.sha256(json.dumps(ir, sort_keys=True, default=repr).encode("utf-8")).hexdigest()))
    return out


def engine_inputs() -> List[str]:
    """Danh sách tên đầu vào được băm (dùng cho lời giải thích)."""
    return [rel for rel, _ in _engine_files()] + [n for n, _ in _strategy_ir_hashes()]


def _git(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", NORA_DIR, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:   # noqa: BLE001  (git thiếu / bị monkeypatch trong test / không phải repo: commit chỉ để tham khảo, hash mới là so sánh)
        return None


def engine_version() -> Dict[str, Any]:
    from backend.alpha.compile import strategy_files
    files = _engine_files()
    sfiles = strategy_files()
    sig = tuple((p, os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in [p for _, p in files] + sfiles)
    if _cache["sig"] == sig and time.time() - _cache["at"] < GIT_TTL_S:
        return dict(_cache["value"])
    h = hashlib.sha256()
    for rel, p in files:
        with open(p, "rb") as fh:
            h.update(rel.encode("utf-8") + b"\0" + fh.read() + b"\0")
    irs = _strategy_ir_hashes()
    for name, d in irs:
        h.update(name.encode("utf-8") + b"\0" + d.encode("ascii") + b"\0")
    status = _git("status", "--porcelain", "--", *[rel for rel, _ in files], *[os.path.relpath(p, NORA_DIR) for p in sfiles])
    value = {"hash": h.hexdigest(), "commit": _git("rev-parse", "--short", "HEAD"), "dirty": (bool(status) if status is not None else None),
             "files": len(files) + len(irs)}
    _cache.update(sig=sig, value=value, at=time.time())
    return dict(value)


def _rebuild_reason(stored: Dict[str, Any], cur: Dict[str, Any]) -> str:
    inputs = engine_inputs()
    core = [i for i in inputs if not i.startswith("strategy:")]
    strat = [i[len("strategy:"):] for i in inputs if i.startswith("strategy:")]
    return (f"đầu vào kết quả của engine ({', '.join(core)}; IR chiến lược: {', '.join(strat)}) đã đổi từ khi dựng sổ: dựng ở commit {stored.get('commit') or '?'} "
            f"(hash {stored['hash'][:8]}), hiện là commit {cur.get('commit') or '?'} (hash {cur['hash'][:8]})")


def book_engine_status(book: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"stored": engine_version lúc dựng | None, "current", "needs_rebuild", "reason"}. Sổ chưa có engine_version -> needs_rebuild True + REASON_NO_VERSION.
    book=None (chưa có sổ) -> needs_rebuild None (không có gì để dựng lại)."""
    cur = engine_version()
    if book is None:
        return {"stored": None, "current": cur, "needs_rebuild": None, "reason": "chưa có sổ"}
    stored = book.get("engine_version")
    if not isinstance(stored, dict) or not stored.get("hash"):
        return {"stored": None, "current": cur, "needs_rebuild": True, "reason": REASON_NO_VERSION}
    if stored["hash"] != cur["hash"]:
        return {"stored": stored, "current": cur, "needs_rebuild": True, "reason": _rebuild_reason(stored, cur)}
    return {"stored": stored, "current": cur, "needs_rebuild": False, "reason": None}


# ══════════════════════════════════════════════════════════════════════════
# Kho alpha (C3) + xuất cấu hình cho Binance Futures testnet (D).
#
# Kho alpha = các bộ (chiến lược × tài sản × tham số) đã qua ĐỦ gate của backend/optimize/funnel/stages.py:
# WFA (OOS) + Monte Carlo (cháy <= 5%) + holdout 20% cuối có lãi và MDD <= 30%, đòn bẩy <= 10x.
# Mỗi mục ghi đủ để tái lập: template, tham số, AST đã thay tham số, số liệu từng giai đoạn,
# sha256 dữ liệu 1m, commit code tại thời điểm tối ưu.
#
# Cấu hình testnet mô tả ĐÚNG những gì engine đã mô phỏng (không thêm hành vi mới):
# - Tín hiệu đánh giá trên nến ĐÃ ĐÓNG; vào lệnh MARKET ở đầu phút kế tiếp (taker).
# - Tầng DCA: lệnh LIMIT post-only (GTX, maker) cách giá khớp tầng trước dca_step_pct.
# - Chốt lời: LIMIT reduce-only (maker) tại giá TB × (1 ± tp%). Cắt lỗ: STOP_MARKET reduce-only từ giá TB.
# - Trailing / timeout / tín hiệu thoát: đóng MARKET (taker). Ký quỹ ISOLATED.
# Tick size / step size / min notional phải lấy từ /fapi/v1/exchangeInfo lúc chạy bot.
#
# Sổ chiến lược: ghi book.json / testnet, xuất bản (book_export):
# Xuất sổ chiến lược đã chốt: data/alpha/book.json (tái lập backtest) + data/alpha/testnet/book.json (bot Binance Futures testnet).
#
# Cấu hình testnet mô tả ĐÚNG hành vi đã mô phỏng trong PortfolioEngine:
# - Tín hiệu trên nến đã đóng -> vào MARKET đầu phút kế tiếp; ATR% = natr(atr_period) của nến atr_frame đã đóng.
# - Khoảng SL = stop_loss_rate × ATR%; danh nghĩa = vốn × risk_per_trade% / (SL% + 2 × (taker + trượt)),
#   chặn bởi max_notional_pct% vốn và phần còn lại của trần tổng danh nghĩa (max_gross_exposure × vốn).
# - Đòn bẩy = min(max_leverage, floor(1 / (1,5 × SL + mmr))) — giá thanh lý luôn cách xa hơn SL; ký quỹ ISOLATED.
# - SL STOP_MARKET reduce-only; trailing (bội số ATR) đóng MARKET; TP LIMIT reduce-only (nếu có); timeout đóng MARKET.
# - Giới hạn danh mục: max_positions, max_per_symbol, kill switch khi vốn MTM sụt kill_switch_dd_pct% từ đỉnh.
# ══════════════════════════════════════════════════════════════════════════

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
    from backend.core.params import resolve_placeholders, split_params
    from backend.crawl.store import read_manifest

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
        "engine_version": engine_version(),   # P9.15: hash mã engine lúc dựng -> API so với engine hiện hành (needs_rebuild)
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
    from backend.core.params import materialize
    from backend.optimize.book.build import UNIVERSE, BY_ID
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
        "engine_version": engine_version(),   # P9.15: hash mã engine lúc dựng sổ -> API so với engine hiện hành (needs_rebuild)
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
    """Xuất bản một sổ đã dựng (src_dir/book.json [+ testnet/book.json]) sang dest_dir (thư mục data/alpha/ đang dùng).

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
            "engine": book_engine_status(book),   # sổ xuất bản giữ engine_version lúc DỰNG (xuất bản không dựng lại)
            "strategies": [s.get("id") for s in book.get("strategies", [])], "written": written, "testnet_removed": removed}


# ══════════════════════════════════════════════════════════════════════════
# Xuất bản & Thăng hạng Alpha từ phễu (promote_alpha, build_report, book_source)
# ══════════════════════════════════════════════════════════════════════════

def registry_alpha_id(strategy: str, alpha_id: str) -> str:
    return f"funnel__{strategy}__{alpha_id}"


def promote_alpha(run_dir: str, alpha_id: str, alphas_dir: str, note: Optional[str] = None) -> Dict[str, Any]:
    """-> {"registry_path", "alpha_id", "registry_alpha_id", "final_scale", "testnet_config"}. ValueError nếu alpha chưa FINAL."""
    from backend.core.params import RISK, materialize
    from backend.optimize.book.build import BY_ID, UNIVERSE
    from backend.optimize.funnel.storage import RunStore
    from backend.optimize.funnel.stages import risk_for_scale
    from backend.optimize.search.generate import split_regime
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
    rpt = risk_for_scale(s)
    cand = BY_ID[alpha["strategy"]]
    params, rmode = split_regime(alpha["params"])
    regime = False
    if rmode == "learn":   # bảng regime của lần chạy holdout (học trên dữ liệu trước holdout)
        from backend.regime.regime import NAMES
        blocked = ((stages.get("S6_holdout") or {}).get("regime_blocked")) or []
        regime = {"allowed": [r for r in NAMES if r not in blocked], "fuse": False, "blocked": blocked} if blocked else False
    st = materialize(cand, params, regime=regime, risk_per_trade_pct=rpt, stop_fill="level")
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
        **({"regime": st["regime"]} if st.get("regime") else {}),
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
    atomic_write_json(reg_path, registry, indent=2, clean=False, allow_nan=True)

    book = {"universe": cfg.get("symbols") or [f"{u}@perp" for u in UNIVERSE], "risk_per_trade_pct": rpt, "risk": RISK,
            "strategies": [{"id": cand["id"], "side": cand["side"], "flow": entry["flows"][0]["ast"], "position": st["position"]}],
            "evidence": {"funnel": funnel}}
    testnet_path = os.path.join(alphas_dir, "testnet", f"{reg_id}.json")
    atomic_write_json(testnet_path, {**testnet_book_config(book), "funnel_alpha_id": alpha_id, "final_scale": s}, indent=2, clean=False, allow_nan=True)
    return {"registry_path": reg_path, "alpha_id": alpha_id, "registry_alpha_id": reg_id, "final_scale": s, "testnet_config": testnet_path}


def _metrics(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("ret_pct", "mdd_pct", "sharpe", "trades", "win_rate", "profit_factor", "halted_at")}


EXPLORE_MIN_STAGE = 1      # sổ thử nghiệm: alpha phải qua S1 (stage_idx >= 1 và không bị loại ở S0/S1; lượt cũ: stage_idx 2 = đã qua S1)


def build_report(run_dir: str, alpha_ids: List[str], rpt: float, wfa: Dict[str, Any], explore: bool = False) -> Dict[str, Any]:
    from backend.optimize.search.evaluate import run
    from backend.core.params import RISK
    from backend.optimize.search.generate import split_regime
    from backend.optimize.funnel.storage import RunStore
    from backend.optimize.funnel.stages import evaluate_s6, S6_MIN_RET_PCT, S6_MAX_MDD_PCT, windows_iso
    st = RunStore(run_dir, read_only=True)
    try:
        run_info = st.read_run()
        items, cands, seen = [], {}, set()
        for aid in alpha_ids:
            al = st.get_alpha(aid)
            if al is None:
                raise ValueError(f"không có alpha {aid}")
            final = al["stage_reached"] == "FINAL" and not al["rejected_stage"]
            passed_s1 = int(al["stage_idx"]) >= EXPLORE_MIN_STAGE and not (al["rejected_stage"] in ("S0_generate", "S1_backtest"))
            if not final and not (explore and passed_s1):
                raise ValueError(f"{aid} chưa đạt {'S1' if explore else 'FINAL'} (dừng ở {al['stage_reached']})")
            if al["strategy"] in seen:
                raise ValueError(f"mỗi chiến lược một alpha: {al['strategy']} bị lặp")
            seen.add(al["strategy"])
            params, _ = split_regime(al["params"])
            params = {k: v for k, v in params.items() if k != "risk_per_trade_pct"}
            items.append({"id": al["strategy"], "params": params})
            cands[al["strategy"]] = {"accepted": True, "funnel_alpha_id": aid, "final_scale": al["final_scale"], "validated": final,
                                     "stage_reached": al["stage_reached"], "reject_code": al["reject_code"],
                                     "stage_metrics": st.alpha_metrics(aid)}
    finally:
        st.close()
    cfg, w = run_info["config"], run_info["windows_ms"]
    tf = cfg.get("timeframe", "1m")
    from backend.crawl.store import exchange
    data_ex = cfg.get("data_exchange", "binance")           # run trước khi tách dữ liệu theo sàn = dữ liệu Binance
    if data_ex != exchange():
        raise ValueError(f"run phễu chạy trên dữ liệu {data_ex}, đang dùng {exchange()} (NORA_EXCHANGE) — holdout phải cùng dữ liệu")
    if wfa or not explore:
        wfa_items = sorted((s["id"], s["configs"][0]) for s in wfa.get("candidates") or [] if s.get("configs"))
        want = sorted((i["id"], {k: v for k, v in i["params"].items()}) for i in items)
        if [x[0] for x in wfa_items] != [x[0] for x in want] or any(
                {k: b[1].get(k) for k in a[1]} != a[1] for a, b in zip(wfa_items, want)):   # WFA chỉ ghi khoá khác mặc định
            raise ValueError("job WFA không chạy đúng các cấu hình của sổ")
        if float(wfa.get("risk_per_trade_pct") or -1) != float(rpt):
            raise ValueError(f"job WFA chạy rủi ro {wfa.get('risk_per_trade_pct')}% khác {rpt}%")
        if not explore and not (wfa.get("gate") or {}).get("passed"):
            raise ValueError("gate WFA danh mục của sổ chưa qua")
    hold = {}
    for sf in ("level", "extreme"):
        r = run([(i["id"], i["params"]) for i in items], cfg["symbols"], int(w["dev2_end"]), int(w["end"]), rpt, sf, RISK, base_frame=tf)
        hold[sf] = _metrics(r)
    ok, code, msg = evaluate_s6(hold["level"], hold["extreme"])
    return {
        "timeframe": tf,
        "data_exchange": data_ex,
        "windows": windows_iso(w),
        "gates": {"funnel_thresholds": cfg.get("thresholds"), "wfa_gate": wfa.get("gate"), "holdout": {"min_ret_pct": S6_MIN_RET_PCT,
                                                                                                      "max_mdd_pct": S6_MAX_MDD_PCT}},
        "book": {"strategies": items, "risk_per_trade_pct": float(rpt), "risk": RISK, "risk_scale_bootstrap": None,
                 "dev2_base_risk": {"wfa_summary": {k: v for k, v in (wfa.get("summary") or {}).items() if k not in ("oos_daily", "oos_daily_dates")}},
                 "explore": bool(explore),
                 "final": {"holdout": hold, "holdout_reason": msg}, "holdout_pass": bool(ok)},
        "candidates": cands,
    }


BOOK_SOURCE_FMT = "funnel {run_id} (wfa {wfa}) {date}"
_BOOK_SOURCE_RE = re.compile(r"^funnel (?P<run_id>\S+) \(wfa (?P<wfa>\S+)\) (?P<date>\S+)$")


def book_source(run_id: str, wfa_job_id: Optional[str], date: str) -> str:
    """Chuỗi `source` ghi vào book.json (MỘT định dạng); parse_book_source đọc ngược."""
    return BOOK_SOURCE_FMT.format(run_id=run_id, wfa=wfa_job_id or "-", date=date)


def parse_book_source(source: Optional[str]) -> Optional[Dict[str, Any]]:
    """{"run_id", "wfa_job_id" | None, "date"} từ book["source"]; None nếu sổ không dựng từ phễu."""
    m = _BOOK_SOURCE_RE.match(source or "")
    return {"run_id": m["run_id"], "wfa_job_id": None if m["wfa"] == "-" else m["wfa"], "date": m["date"]} if m else None


# ══════════════════════════════════════════════════════════════════════════
# Kiểm lại một alpha trong kho (data/alpha/registry.json) bằng ENGINE HIỆN HÀNH theo đúng các cổng của phễu (job API `alpha_revalidate`).
#
# Alpha cũ (vd. trend_long_perp__SOL) được dựng bằng đường tối ưu đơn tài sản đã xoá (P0.11a) và engine trước P1, nên bằng chứng trong kho
# không còn tái lập được. Job này chạy lại đúng cây tín hiệu + tham số vị thế đã lưu (flows[0].ast + position) trên tài sản của alpha:
#   S3  WFA tham số cố định trên dev2 (fold train/test của phễu; IS = level, kill tắt; OOS = extreme, kill bật) -> gates.evaluate_s3
#   S5  hệ số khối lượng s lớn nhất trong [S5_S_MIN, 1] mà MC (>= 10.000 kịch bản + kịch bản cực xấu + trend thẳng đứng) qua -> sizing.search_scale
#   S6  holdout một lần ở hệ số s (level + extreme, kill bật) -> gates.evaluate_s6
# Kết luận: "validated" (kèm final_scale) hoặc "retired" (kèm mã + lý do). apply=True: ghi status/revalidation vào registry; alpha bị loại thì
# cấu hình testnet của nó chuyển sang data/alpha/testnet/_retired/ (giữ lại để tra cứu, bot không còn đọc).
# ══════════════════════════════════════════════════════════════════════════

ALPHA_REVALIDATE_DEFAULTS = {"alpha_id": "trend_long_perp__SOL", "apply": False}
TIMEFRAME = "15m"   # khung chạy (khung tín hiệu của alpha phải >= khung này; trend_long_perp__SOL dùng 15m/1h)


def load_alpha(alpha_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    with open(os.path.join(base or alphas_dir(), "registry.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next((a for a in reg.get("alphas") or [] if a.get("alpha_id") == alpha_id), None)
    if al is None:
        raise SystemExit(f"Không có alpha {alpha_id} trong registry.json")
    return al


def alpha_strategy(al: Dict[str, Any], scale: float = 1.0) -> Dict[str, Any]:
    """Chiến lược PortfolioEngine của alpha (đúng tham số đã lưu; khối lượng nhân scale), chỉ chạy trên tài sản của nó."""
    from backend.optimize.funnel.stages import scale_position
    ast = al["flows"][0]["ast"]
    return {"id": al["alpha_id"], "side": al["side"], "tree": ast["match"][0]["condition"], "stop": ast.get("stop") or [],
            "position": scale_position(al["position"], scale) if scale != 1.0 else dict(al["position"]), "symbols": [al["data_symbol"]]}


def _run(al, window, stop_fill: str, kill: bool, scale: float = 1.0) -> Dict[str, Any]:
    from backend.optimize.search.evaluate import run
    from backend.core.params import BASE_RISK_PER_TRADE_PCT, RISK
    risk = {**RISK, "kill_switch_dd_pct": RISK["kill_switch_dd_pct"] if kill else 0}
    return run([], [al["data_symbol"]], int(window[0]), int(window[1]), BASE_RISK_PER_TRADE_PCT, stop_fill, risk,
               extra_strategies=[alpha_strategy(al, scale)], base_frame=TIMEFRAME)


def _oos(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"ret_pct": r["ret_pct"], "mdd_pct": r["mdd_pct"], "trades": r["trades"], "halted": bool(r.get("halted_at"))}


def wfa_check(al, folds: List[Dict[str, Any]], scale: float = 1.0) -> Dict[str, Any]:
    """WFA tham số cố định (cùng quy ước phễu S3) -> aggregate_wfa (summary/metrics/series/trades) + shock (vị thế ngược chiều lớn nhất)."""
    from backend.carlo.carlo import merge_exposure, vertical_exposure
    from backend.metrics.trades import rows_from_trade_list
    from backend.optimize.search.evaluate import aggregate_wfa
    out, shocks = [], []
    for f in folds:
        is_r = _run(al, f["train"], "level", False, scale)
        oos = _run(al, f["test"], "extreme", True, scale)
        rows = rows_from_trade_list(oos["trade_list"])
        shocks.append(vertical_exposure(oos["trade_list"], None))   # alpha cỡ theo % vốn: lỗ tối đa = ký quỹ (bảo thủ)
        out.append({"fold": f["fold"], "train": f["train_iso"], "test": f["test_iso"], "is_ret_pct": is_r["ret_pct"], "is_trades": is_r["trades"],
                    "oos": _oos(oos), "daily": oos["daily"], "daily_start": f["test_iso"][0], "trades": rows})
    agg = aggregate_wfa(out)
    agg["shock"] = merge_exposure(shocks)
    return agg


def revalidate(al: Dict[str, Any], windows: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    from backend.optimize.search import evaluate as bt
    from backend.optimize.funnel import stages as gates, stages as sizing
    w = windows or gates.compute_windows([al["data_symbol"]])
    folds = bt.fold_job_plan(gates.wfa_folds(w))
    rep: Dict[str, Any] = {"alpha_id": al["alpha_id"], "symbol": al["data_symbol"], "windows": gates.windows_iso(w), "checked_at": int(time.time() * 1000)}
    agg = wfa_check(al, folds)
    ok3, code3, msg3 = gates.evaluate_s3(agg["summary"])
    rep["wfa"] = {"summary": agg["summary"], "passed": ok3, "reason": None if ok3 else msg3,
                  "metrics": {k: agg["metrics"].get(k) for k in ("ret_pct", "mdd_pct", "sharpe", "trades", "win_rate", "profit_factor")}}
    rep["shock"] = agg["shock"]
    verdict = lambda ok, code, msg, **kw: {**rep, **kw, "status": "validated" if ok else "retired", "reject_code": None if ok else code,  # noqa: E731
                                           "reason": None if ok else msg}
    if not ok3:
        return verdict(False, code3, msg3)
    if len(agg["series"]) < gates.S4_MIN_DAYS:
        return verdict(False, "S4.days", f"S4.days: {gates.reason_label('S4.days')} ({len(agg['series'])} < {gates.S4_MIN_DAYS})")
    turnover = agg["metrics"].get("turnover_daily")   # đo từ lệnh OOS (None -> cost_x2 không đo được -> cổng không đạt)
    s_star, steps = sizing.search_scale(lambda s: bt.mc_check(agg["series"], s, agg["shock"], turnover))
    rep["sizing"] = {"s": s_star, "search": steps}
    if s_star is None:
        last = bt.mc_check(agg["series"], gates.S5_S_MIN, agg["shock"], turnover)
        _, code, msg = gates.evaluate_mc_checks(last["gate"], "S5")
        return verdict(False, code, msg)
    hold = (w["dev2_end"], w["end"])
    lv, ex = _run(al, hold, "level", True, s_star), _run(al, hold, "extreme", True, s_star)
    ok6, code6, msg6 = gates.evaluate_s6(lv, ex)
    rep["holdout"] = {"scale": s_star, "level": _oos(lv), "extreme": _oos(ex), "passed": ok6}
    return verdict(ok6, code6, msg6, final_scale=s_star if ok6 else None)


def apply_result(rep: Dict[str, Any], base: Optional[str] = None) -> List[str]:
    """Ghi status + revalidation vào registry; alpha "retired" -> testnet/<id>.json chuyển sang testnet/_retired/. -> các đường dẫn đã đổi."""
    base = base or alphas_dir()
    path = os.path.join(base, "registry.json")
    with open(path, encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next(a for a in reg["alphas"] if a.get("alpha_id") == rep["alpha_id"])
    al["status"] = rep["status"]
    al["revalidation"] = {k: v for k, v in rep.items() if k != "alpha_id"}
    atomic_write_json(path, reg, indent=2, clean=False, allow_nan=True)
    changed = [path]
    tn = os.path.join(base, "testnet", f"{rep['alpha_id']}.json")
    if rep["status"] == "retired" and os.path.isfile(tn):
        dst = os.path.join(base, "testnet", "_retired", f"{rep['alpha_id']}.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(tn, dst)
        changed.append(dst)
    return changed


def run_alpha_revalidate(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(ALPHA_REVALIDATE_DEFAULTS, params)
    from backend.optimize.process.workers import require_memory_limit
    require_memory_limit("alpha_revalidate")
    al = load_alpha(a.alpha_id)
    from backend.crawl.store import require_data_ok_or_exit
    require_data_ok_or_exit([al["data_symbol"]])
    rep = revalidate(al)
    print(f"{rep['alpha_id']}: {rep['status']}" + (f" (s={rep.get('final_scale')})" if rep["status"] == "validated" else f" — {rep['reason']}"),
          flush=True)
    if a.apply:
        rep["changed"] = apply_result(rep)
        print("đã ghi:", rep["changed"], flush=True)
    write_job_result(rep)
    return rep


# ══════════════════════════════════════════════════════════════════════════
# Quản lý Alpha người dùng (C1 — lưu trữ, xác minh, checklist, catalog).
#
# Kho lưu trữ: crawl/store.alpha_user_dir()/<alpha_id>.json (đường dẫn đặt MỘT chỗ: get_user_alphas_dir; thư mục job: batch.jobs_root())
# alpha_id = sha1(program_hash + cấu hình chạy)[:12]
# Bản ghi = code + program_hash + config + ảnh chụp đầy đủ kết quả (`result`) + `evidence`, đã xác minh trực tiếp từ job_id (chống giả mạo từ client).
# Chạy ở /alpha/create và /education chỉ là TẠM THỜI (job_ttl dọn sau 24 h nếu không được lưu); chỉ lệnh Lưu mới ghi vào đây.
# Vòng đời: SAVED -> CANDIDATE -> ARCHIVED
# ══════════════════════════════════════════════════════════════════════════

def get_user_alphas_dir(base_dir: Optional[str] = None) -> str:
    if base_dir:
        return os.path.join(base_dir, "user")
    from backend.crawl.store import alpha_user_dir
    return alpha_user_dir()


def generate_alpha_id(program_hash: str, config: Dict[str, Any]) -> str:
    """Tạo mã alpha_id bất biến: sha1(program_hash + canonical config)[:12]."""
    canon = {
        "symbols": sorted(config.get("symbols") or []),
        "start": config.get("start"),
        "end": config.get("end"),
        "train_ratio": config.get("train_ratio"),
        "initial_capital": config.get("initial_capital"),
        "timeframe": config.get("timeframe"),
        "position": config.get("position"),
    }
    raw = f"{program_hash}:{json.dumps(canon, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _num(v: Any) -> Optional[float]:
    """Số hữu hạn (kể cả 0) hoặc None — không bao giờ thay thiếu bằng 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _first_num(block: Any, *keys: str) -> Optional[float]:
    for k in keys:
        n = _num((block or {}).get(k)) if isinstance(block, dict) else None
        if n is not None:
            return n
    return None


def _item(item_id: str, label: str, state: str, value: str, required: str) -> Dict[str, Any]:
    """state: pass | fail | missing. `passed` = True | False | None (thiếu dữ liệu: không đạt cũng không trượt)."""
    return {"id": item_id, "label": label, "state": state, "passed": {"pass": True, "fail": False}.get(state), "value": value, "required": required}


MISSING_VI = "không có dữ liệu"


def evaluate_checklist(result: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra 5 tiêu chí trước khi lưu (chỉ cảnh báo, không chặn). Nguồn DUY NHẤT của checklist: giao diện chỉ hiển thị.
    - >= 20 lệnh đóng
    - có giai đoạn test
    - Sharpe test > 0 (metrics.test.sharpe, năm = 365 ngày)
    - MDD < 50% (metrics.simulate.mdd_pct, đã là %)
    - không phải thuần beta (insight beta_driven)
    Đầu vào thiếu -> state "missing" (không đạt cũng không trượt), không bao giờ ngầm coi là 0."""
    metrics = result.get("metrics") or {}
    trades = result.get("trades")
    n_trades = len(trades) if isinstance(trades, list) else None

    has_test = bool(metrics.get("test"))
    test_sharpe = _first_num(metrics.get("test"), "sharpe")
    mdd_pct = _first_num(metrics.get("simulate"), "mdd_pct")
    if mdd_pct is not None:
        mdd_pct = abs(mdd_pct)

    insights = result.get("insights")
    has_beta_driven = any(isinstance(i, dict) and i.get("id") == BETA_DRIVEN_ID for i in insights) if isinstance(insights, list) else None

    items = [
        _item("trades_ge_20", "Tối thiểu 20 lệnh giao dịch",
              "missing" if n_trades is None else ("pass" if n_trades >= 20 else "fail"),
              MISSING_VI if n_trades is None else f"{n_trades} lệnh", "≥ 20 lệnh"),
        _item("has_test_stage", "Có kiểm định ngoài mẫu (Out-Of-Sample)", "pass" if has_test else "fail", "Đã chạy" if has_test else "Chưa có", "Có giai đoạn test"),
        _item("test_sharpe_positive", "Sharpe ngoài mẫu dương (Sharpe Test > 0)",
              "missing" if test_sharpe is None else ("pass" if test_sharpe > 0.0 else "fail"),
              MISSING_VI if test_sharpe is None else f"{test_sharpe:.2f}", "> 0.0"),
        _item("mdd_under_50", "Mức sụt giảm tối đa dưới 50% (MDD < 50%)",
              "missing" if mdd_pct is None else ("pass" if mdd_pct < 50.0 else "fail"),
              MISSING_VI if mdd_pct is None else f"{mdd_pct:.1f}%", "< 50%"),
        _item("not_pure_beta", "Không phụ thuộc thuần túy vào thị trường (Beta-driven)",
              "missing" if has_beta_driven is None else ("fail" if has_beta_driven else "pass"),
              MISSING_VI if has_beta_driven is None else ("Cảnh báo beta" if has_beta_driven else "Độc lập"), f"Không kích hoạt {BETA_DRIVEN_ID}"),
    ]
    return {"all_passed": all(it["state"] == "pass" for it in items), "n_missing": sum(1 for it in items if it["state"] == "missing"), "items": items}


# ─── Lưu / đọc ──────────────────────────────────────────────────────────────

SNAPSHOT_REQUIRED = ("config", "metrics", "program_hash")


def _git_commit() -> Optional[str]:
    try:
        from backend.optimize.process.tasks import git_commit
        return git_commit()
    except Exception:      # noqa: BLE001 — bằng chứng phụ, thiếu thì null
        return None


def build_evidence(result: Dict[str, Any], job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data") or {}
    return {"job_id": job_id, "program_hash": result.get("program_hash"), "data_source": data.get("source"), "data_sha256_1m": data.get("sha256_1m"),
            "git_commit": _git_commit(), "job_created": job.get("created"), "job_finished": job.get("finished"), "engine": "custom_run (PortfolioEngine)"}


def save_user_alpha(job_id: str, code: str, name: str, note: str = "", source: str = "alpha-create",
                    base_dir: Optional[str] = None, alpha_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Xác thực và lưu trữ bản ghi Alpha người dùng (lần lưu DUY NHẤT; chạy ở /alpha/create và /education chỉ là tạm thời):
    - Đọc kết quả job thật từ máy chủ (job.status == 'done'), KHÔNG nhận kết quả từ client
    - Kiểm tra mã băm chương trình khớp với code gửi lên (chống giả mạo)
    - Ghi ảnh chụp ĐẦY ĐỦ kết quả (`result`) + `explain` + `evidence` nên bản ghi không còn phụ thuộc thư mục job
    - Trả về (record, action: 'created' | 'updated' | 'versioned'); cùng code + cùng cấu hình -> cùng id -> cập nhật, không nhân bản
    - `alpha_id` (P10): lưu PHIÊN BẢN MỚI của alpha đã có (sửa code trong trình soạn tạm -> chạy lại -> Lưu): giữ id, bản ghi cũ nguyên vẹn được
      chuyển vào user/_versions/<id>.v<n>.json, bản ghi chính nhận code + kết quả + bằng chứng mới với version = n + 1
    """
    from backend.optimize.process import process as batch

    job = batch.status(job_id)
    if not job:
        if batch.ephemeral_gone(job_id):
            raise batch.EphemeralGone(job_id)
        raise ValueError(f"Không tìm thấy job_id {job_id}")
    if job.get("status") != "done":
        raise ValueError(f"Job {job_id} chưa hoàn tất (trạng thái: {job.get('status')})")

    result = job.get("result")
    if not result:
        raise ValueError(f"Job {job_id} không có dữ liệu result.json")
    lacking = [k for k in SNAPSHOT_REQUIRED if not result.get(k)]
    if lacking or not (result.get("metrics") or {}).get("simulate"):
        raise ValueError(f"Kết quả job {job_id} thiếu {lacking or ['metrics.simulate']}: không đủ để lưu")

    # Kiểm tra program_hash
    from backend.alpha.compile import compile_code
    prog = compile_code(code, register=False)
    if result.get("program_hash") != prog.code_hash:
        raise ValueError(f"Mã băm chương trình không khớp (kết quả job: {result.get('program_hash')}, code hiện tại: {prog.code_hash})")

    config = result.get("config", {})
    user_dir = get_user_alphas_dir(base_dir)
    os.makedirs(user_dir, exist_ok=True)
    versioned = alpha_id is not None
    if versioned:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alpha_id) or not os.path.isfile(os.path.join(user_dir, f"{alpha_id}.json")):
            raise LookupError(f"Không tìm thấy alpha {alpha_id} để lưu phiên bản mới")
    else:
        alpha_id = generate_alpha_id(prog.code_hash, config)
    checklist = evaluate_checklist(result)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")

    action = "versioned" if versioned else ("updated" if os.path.isfile(file_path) else "created")
    now_iso = datetime.now(timezone.utc).isoformat()

    old_record = {}
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                old_record = json.load(fh)
        except Exception:
            pass

    explain = None
    try:
        from backend.alpha.compile import explain_program
        explain = explain_program(prog, position=config.get("position"))
    except Exception:      # noqa: BLE001 — giải thích là phần phụ; thiếu thì null
        explain = None

    snapshot = {k: v for k, v in result.items() if k not in ("checklist",)}
    snapshot["checklist"] = checklist
    record: Dict[str, Any] = {
        "id": alpha_id,
        "name": name.strip(),
        "note": (note or "").strip(),
        "source": source,
        "status": old_record.get("status", "SAVED"),
        "created_at": old_record.get("created_at", now_iso),
        "updated_at": now_iso,
        "code": code,
        "program_hash": prog.code_hash,
        "config": config,
        "metrics": result.get("metrics", {}),
        "checklist": checklist,
        "data_sha": (result.get("data") or {}).get("sha256_1m"),
        "job_id": job_id,
        "final_equity": result.get("final_equity"),
        "evidence": build_evidence(result, job_id, job),
        "explain": explain,
        "result": snapshot,       # ảnh chụp đầy đủ: metrics, yearly, series (stages + benchmark), trades, diagnostics, insights, by_symbol, warnings...
    }
    if versioned:
        prev_v = int(old_record.get("version") or 1)
        history = list(old_record.get("versions") or [_version_row(old_record, prev_v)])
        vdir = os.path.join(user_dir, "_versions")
        os.makedirs(vdir, exist_ok=True)
        atomic_write_json(os.path.join(vdir, f"{alpha_id}.v{prev_v}.json"), old_record, indent=1)     # bản cũ nguyên vẹn (kể cả kết quả) để so sánh
        record["version"] = prev_v + 1
        record["versions"] = history + [_version_row(record, prev_v + 1)]
    else:
        record["version"] = int(old_record.get("version") or 1)
        if old_record.get("versions"):
            record["versions"] = old_record["versions"]
    atomic_write_json(file_path, record, indent=1)
    return record, action


def _version_row(rec: Dict[str, Any], version: int) -> Dict[str, Any]:
    return {"version": version, "saved_at": rec.get("updated_at"), "program_hash": rec.get("program_hash"), "job_id": rec.get("job_id"), "name": rec.get("name")}


def list_user_alpha_versions(alpha_id: str, base_dir: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """[{version, saved_at, program_hash, job_id, name}] gồm bản hiện tại; None nếu không có alpha."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return None
    return list(rec.get("versions") or [_version_row(rec, int(rec.get("version") or 1))])


def get_user_alpha_version(alpha_id: str, version: int, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Bản ghi đầy đủ của phiên bản `version` (bản hiện tại hoặc user/_versions/<id>.v<n>.json)."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return None
    if int(rec.get("version") or 1) == version:
        return rec
    path = os.path.join(get_user_alphas_dir(base_dir), "_versions", f"{alpha_id}.v{int(version)}.json")
    return read_json(path) if os.path.isfile(path) else None


_HEAVY = ("result", "explain")


def _summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Bản ghi gọn cho danh sách: bỏ ảnh chụp kết quả + giải thích (lấy bằng GET /user/{id})."""
    out = {k: v for k, v in rec.items() if k not in _HEAVY}
    out["has_result"] = isinstance(rec.get("result"), dict)
    return out


def _sort_value(rec: Dict[str, Any], key: str) -> Optional[float]:
    m = rec.get("metrics") or {}
    if key == "sharpe":      # Sharpe giai đoạn test
        return _first_num(m.get("test"), "sharpe")
    if key == "cagr":        # CAGR toàn kỳ — không phải ret_pct
        return _first_num(m.get("simulate"), "cagr_pct")
    return None


def list_user_alphas(sort: Optional[str] = None, status: Optional[str] = None,
                     base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Liệt kê danh sách alpha người dùng (bản ghi gọn, không kèm ảnh chụp kết quả)."""
    user_dir = get_user_alphas_dir(base_dir)
    if not os.path.isdir(user_dir):
        return []

    items: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(user_dir)):
        if fname.endswith(".json") and not fname.endswith(".tmp"):
            path = os.path.join(user_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    rec = json.load(fh)
                    if isinstance(rec, dict) and rec.get("id"):
                        if status and rec.get("status") != status:
                            continue
                        items.append(_summary(rec))
            except Exception:
                continue

    # Sắp xếp (giá trị thiếu xếp cuối)
    if sort in ("sharpe", "cagr"):
        have = sorted((x for x in items if _sort_value(x, sort) is not None), key=lambda x: _sort_value(x, sort), reverse=True)
        items = have + [x for x in items if _sort_value(x, sort) is None]
    elif sort == "date":
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    else:
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    return items


def get_user_alpha(alpha_id: str, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết một alpha người dùng theo id."""
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def update_user_alpha_status(alpha_id: str, new_status: str, base_dir: Optional[str] = None) -> bool:
    """Cập nhật trạng thái alpha: SAVED -> CANDIDATE -> ARCHIVED."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return False
    rec["status"] = new_status
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    atomic_write_json(file_path, rec, indent=1)
    return True


# ══════════════════════════════════════════════════════════════════════════
# Thư viện chiến lược: mỗi CHIẾN LƯỢC (không phải mỗi alpha / khung giờ) = Ý tưởng -> Công thức bằng lời -> Công thức toán học -> Thống kê.
#
# Công thức dựng từ CÂY KHUÔN của chiến lược (optimize/book/build.py CANDIDATES: "ema_{ema_n}", {"param": "k_up"}, khung "{signal_tf}") nên là dạng KÝ HIỆU,
# đúng cấu trúc engine đang chạy; nhãn tham số lấy từ params_schema. Thống kê = các alpha đã qua kiểm định của chiến lược đó trong sổ chính + sổ thử nghiệm
# (mọi khung giờ gộp chung). Danh mục: STRATEGIES; chiến lược có "doc": "combined" (Sideway) là MỘT mục gồm cả hai chiều.
#
#     catalog() -> {"sources": [{"key": "nora", "label": "Nora", "strategies": [{key, name, kind, side, idea, plain, math, summary, stats}, ...]}]}
#     plain: câu tiếng Việt, ký hiệu toán nằm trong $…$ (UI hiện bằng KaTeX nội dòng).
# ══════════════════════════════════════════════════════════════════════════

CMP_LATEX = {"<": "<", ">": ">", "<=": r"\le", ">=": r"\ge"}
CMP_VI = {"<": "<", ">": ">", "<=": "≤", ">=": "≥"}
PRICE = {"close": ("C", "giá đóng cửa"), "open": ("O", "giá mở cửa"), "high": ("H", "giá cao"), "low": ("L", "giá thấp")}
BAND = {"bbl": ("BB", "lo", "dải dưới Bollinger"), "bbu": ("BB", "up", "dải trên Bollinger"), "bbm": ("BB", "mid", "đường giữa Bollinger"),
        "kcl": ("KC", "lo", "dải dưới Keltner"), "kcu": ("KC", "up", "dải trên Keltner"), "kcm": ("KC", "mid", "đường giữa Keltner")}
STAT_KEYS = ("ret_pct", "extreme_ret_pct", "mdd_pct", "extreme_mdd_pct", "sharpe", "sortino", "profit_factor", "win_rate", "trades", "symbols_positive")
# Tổng hợp cấp chiến lược trên các alpha đã đạt: lợi nhuận / tỷ số = trung bình; MDD = xấu nhất; số lệnh = tổng
SUMMARY = {"ret_pct": "mean", "extreme_ret_pct": "mean", "mdd_pct": "max", "extreme_mdd_pct": "max", "sharpe": "mean", "sortino": "mean",
           "profit_factor": "mean", "win_rate": "mean", "trades": "sum"}
STAGES = ("FINAL", "S6_holdout", "S5_sizing", "S4_montecarlo", "S3_wfa", "S2_antiluck", "S1_backtest")
_PH = re.compile(r"\{(\w+)\}")


def vn(x: Any) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    return f"{float(x):.4f}".rstrip("0").rstrip(".").replace(".", ",")


# ─── Ký hiệu tham số ────────────────────────────────────────────────────────
def psym(name: str) -> str:
    """Tên tham số khuôn -> ký hiệu: rsi_lo -> θ^{RSI}_{lo}; gate_er_max -> θ^{ER}_{gate}; k_up -> k_{up}; ema_n -> n."""
    t = name.split("_")
    rest = r"\_".join(t[1:])
    if t[0] == "gate" and len(t) > 1 and t[1] in REGISTRY:
        return rf"\theta^{{\mathrm{{{t[1].upper()}}}}}_{{\mathrm{{gate}}}}"
    if t[0] in REGISTRY and len(t) > 1 and t[-1] not in ("n", "k", "m"):
        return rf"\theta^{{\mathrm{{{t[0].upper()}}}}}_{{\mathrm{{{rest}}}}}"
    if len(t) > 1 and t[-1] in ("n", "k", "m"):
        return t[-1]
    return rf"{t[0]}_{{\mathrm{{{rest}}}}}" if len(t) > 1 else t[0]


def fsym(frame: str) -> str:
    m = _PH.fullmatch(frame)
    return rf"\tau_{{\mathrm{{{m.group(1).replace('_tf', '')}}}}}" if m else rf"\mathrm{{{frame}}}"


def _label(schema: Dict[str, Any], name: str) -> str:
    return str((schema.get(f"sig.{name}") or schema.get(name) or {}).get("label_vi") or name)


def pword(name: str, schema: Dict[str, Any]) -> str:
    """Tên tham số bằng lời: ngưỡng (…_lo/_hi/_max/gate_…) gọi là "ngưỡng …"; còn lại dùng nhãn schema (vd "hệ số dải trên")."""
    t = name.split("_")
    if t[0] == "gate":
        return "ngưỡng dồn"
    if t[0] in REGISTRY and t[-1] in ("lo", "hi", "max", "min"):
        return {"lo": "ngưỡng thấp", "hi": "ngưỡng cao", "max": "ngưỡng", "min": "ngưỡng"}[t[-1]]
    return _label(schema, name).lower()


# ─── Toán hạng / điều kiện: (LaTeX, lời) ──────────────────────────────────────
def operand(item: Any, schema: Dict[str, Any], t: str = "t") -> Tuple[str, str]:
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return vn(item).replace(",", "."), vn(item)
    if not isinstance(item, dict):
        return r"\varnothing", "—"
    if "param" in item:
        return psym(item["param"]), pword(item["param"], schema)
    if item.get("type") == "calculate":
        a, b = operand(item.get("number_1"), schema, t), operand(item.get("number_2"), schema, t)
        if item.get("logic") == "*":
            return rf"{b[0]}\cdot {a[0]}", f"{b[1]} × {a[1]}"
        op = {"+": "+", "-": "-", "/": "/"}.get(item.get("logic"), "?")
        return rf"{a[0]}{op}{b[0]}", f"{a[1]} {op} {b[1]}"
    if "column" in item:
        lag = int(item.get("index", 0) or 0)
        tt = t if not lag else f"{t}-{lag}"
        frame = str(item.get("frame", ""))
        fl = fsym(frame)
        col = str(item["column"])
        kernel = col.split("_", 1)[0]
        subs = [psym(p) for p in _PH.findall(col)]
        if col in PRICE:
            out = (rf"{PRICE[col][0]}^{{{fl}}}_{{{tt}}}", PRICE[col][1])
        elif kernel in BAND:
            sym, band, words = BAND[kernel]
            out = (rf"\mathrm{{{sym}}}^{{\mathrm{{{band}}},{fl}}}_{{{','.join(subs)}}}({tt})", words)
        elif kernel in REGISTRY:
            fw = _label(schema, frame.strip("{}")).lower() if _PH.fullmatch(frame) else frame
            note = f" ({fw})" if frame != schema.get("_main_frame") else ""
            out = (rf"\mathrm{{{kernel.upper()}}}^{{{fl}}}_{{{','.join(subs)}}}({tt})", kernel.upper() + note)
        else:
            out = (rf"\mathrm{{{col}}}({tt})", col)
        if "add" in item:
            m = operand(item["add"], schema, tt)
            out = (rf"{out[0]}+{m[0]}", f"{out[1]} + {m[1]}")
        if "subtract" in item:
            m = operand(item["subtract"], schema, tt)
            out = (rf"{out[0]}-{m[0]}", f"{out[1]} − {m[1]}")
        return out
    return r"\varnothing", "—"


def _shift(item: Any) -> Any:
    if isinstance(item, list):
        return [_shift(x) for x in item]
    if not isinstance(item, dict):
        return item
    return {k: (int(v or 0) + 1 if k == "index" and "column" in item else _shift(v)) for k, v in item.items()}


def _off_by_default(c: List[Any]) -> bool:
    """Ngưỡng mặc định nằm ngoài miền chỉ báo (vd gate_rsi = 101) = điều kiện TUỲ CHỌN, mặc định tắt."""
    left, op, right = c
    if not (isinstance(right, dict) and "default" in right and isinstance(left, dict) and "column" in left):
        return False
    spec = REGISTRY.get(str(left["column"]).split("_", 1)[0])
    if spec is None or ".." not in spec.unit:
        return False
    lo, hi = (float(x) for x in spec.unit.split(".."))
    v = float(right["default"])
    return (op in ("<", "<=") and v > hi) or (op in (">", ">=") and v < lo)


def conditions(tree: Any, schema: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Cây khuôn (OR các khối, AND trong khối) -> (dòng LaTeX, câu). Cặp (x > y tại t, x ≤ y tại t−1) gộp thành "cắt lên"."""
    tex, words = [], []
    blocks = [b for b in (tree or []) if isinstance(b, list) and b]
    for bi, block in enumerate(blocks):
        used = set()
        bt, bw = [], []
        for i, a in enumerate(block):
            if i in used:
                continue
            pair = next((j for j, b in enumerate(block) if j != i and j not in used and (a[1], b[1]) in ((">", "<="), ("<", ">="))
                         and b[0] == _shift(a[0]) and b[2] == _shift(a[2])), None)
            l, r = operand(a[0], schema), operand(a[2], schema)
            opt = " (tuỳ chọn, mặc định tắt)" if _off_by_default(a) else ""
            if pair is not None:
                used.update((i, pair))
                l1, r1 = operand(a[0], schema, "t-1"), operand(a[2], schema, "t-1")
                rev = {">": r"\le", "<": r"\ge"}[a[1]]
                bt.append(rf"{l[0]}{CMP_LATEX[a[1]]}{r[0]}\ \land\ {l1[0]}{rev}{r1[0]}")
                bw.append(f"{l[1]} cắt {'lên trên' if a[1] == '>' else 'xuống dưới'} {r[1]}")
            else:
                bt.append(rf"{l[0]}{CMP_LATEX.get(a[1], a[1])}{r[0]}")
                bw.append(f"{l[1]} {CMP_VI.get(a[1], a[1])} {r[1]}{opt}")
        tex.append(r"\ \land\ ".join(bt))
        words.append(" và ".join(bw))
    if len(tex) > 1:
        tex = [r"\ \lor\ ".join(rf"({x})" for x in tex)]
        words = [" HOẶC ".join(f"({w})" for w in words)]
    return tex, words


# ─── Một mục chiến lược ─────────────────────────────────────────────────────
def _exits(cand: Dict[str, Any], side: str) -> Tuple[List[str], List[str]]:
    sch = cand.get("params_schema") or {}
    adv, fav = {"LONG": ("-", "+"), "SHORT": ("+", "-")}.get(side, (r"\mp ", r"\pm "))   # hai chiều: dấu trên = Long, dấu dưới = Short
    tex = [r"\nu=\mathrm{ATR\%}(t_0)"]
    words = []
    if "dca_step_pct" in sch:
        tex.append(rf"P_k=P_{{k-1}}(1{adv}s\,\nu),\quad q_k=q_0\,m^{{k}},\quad k\le K,\quad \mathrm{{Gate}}_t=1")
        words.append("Giá đi ngược thì dồn tầng $k$ cách tầng trước $s\\nu$ ($\\nu$ = ATR%), khối lượng ×$m$ mỗi tầng, tối đa $K$ tầng — chỉ khi điều kiện dồn còn đúng.")
    pbar = r"\bar P" if "dca_step_pct" in sch else r"P_0"
    ref = "giá trung bình" if "dca_step_pct" in sch else "giá vào"
    tex.append(rf"\mathrm{{SL}}={pbar}(1{adv}s_L\nu),\quad \mathrm{{TP}}={pbar}(1{fav}s_T\nu)")
    words.append(f"Cắt lỗ $s_L\\nu$, chốt lời $s_T\\nu$ tính từ {ref}.")
    if "trailing_stop" in sch:
        ext = {"LONG": r"\max H", "SHORT": r"\min L"}.get(side, r"\max H\ /\ \min L")
        tex.append(rf"\mathrm{{Trail}}=P^*(1{adv}s_R\nu),\quad P^*={ext},\quad \frac{{|P^*-{pbar}|}}{{{pbar}}}\ge a\,\nu")
        words.append("Trailing: lãi đạt $a\\nu$ thì bật, dừng cách đỉnh lãi $s_R\\nu$.")
    return tex, words


def _sizing() -> Tuple[str, str]:
    return (r"N=\min\!\left(\frac{E\,r}{s_L\nu+2(f+\epsilon)},\ E\,c\right),\quad \lambda\le\left\lfloor\frac{1}{1.5\,s_L\nu+\mathrm{mmr}}\right\rfloor",
            "Khối lượng tính ngược từ rủi ro: chạm cắt lỗ (gồm mọi tầng, phí, trượt) chỉ mất $r$% vốn; đòn bẩy tự hạ để luôn cắt lỗ trước khi thanh lý.")


def _main_frame(tree: Any) -> Optional[str]:
    """Khung của toán hạng giá đầu tiên trong cây (khung vào lệnh) — chỉ báo ở khung khác được ghi chú khung."""
    for block in tree or []:
        for c in block:
            for x in (c[0], c[2]):
                if isinstance(x, dict) and x.get("column") in PRICE:
                    return str(x.get("frame"))
    return None


def leg_doc(cand: Dict[str, Any], label: str = "") -> Dict[str, Any]:
    sch = {**(cand.get("params_schema") or {}), "_main_frame": _main_frame(cand.get("tree"))}
    side = cand["side"]
    sv = "Long" if side == "LONG" else "Short"
    plain, math = [], []
    e_tex, e_w = conditions(cand.get("tree"), sch)
    pre = f"{label} " if label else ""
    math.append({"title": f"{pre}Vào lệnh", "latex": rf"\mathrm{{Entry}}^{{\mathrm{{{sv.lower()}}}}}_t=\mathbb{{1}}\left[{e_tex[0]}\right]"})
    plain.append(f"{pre}vào lệnh khi {e_w[0]}." if label else f"Vào {sv} khi {e_w[0]}.")
    if cand.get("stop"):
        x_tex, x_w = conditions(cand.get("stop"), sch)
        math.append({"title": f"{pre}Thoát (đảo chiều)", "latex": rf"\mathrm{{Exit}}_t=\mathbb{{1}}\left[{x_tex[0]}\right]"})
        plain.append(f"{pre}Thoát khi {x_w[0]}.")
    if cand.get("dca_gate"):
        g_tex, g_w = conditions(cand.get("dca_gate"), sch)
        math.append({"title": f"{pre}Được phép dồn", "latex": rf"\mathrm{{Gate}}_t=\mathbb{{1}}\left[{g_tex[0]}\right]"})
        plain.append(f"{pre}Chỉ dồn khi {g_w[0]}.")
    return {"plain": plain, "math": math, "side": side}


def _alphas_of(leg_ids: List[str], books: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out = []
    for kind, book in books:
        for it in book.get("strategies") or []:
            if it.get("id") not in leg_ids:
                continue
            sm = ((it.get("evidence") or {}).get("stage_metrics") or {})
            stage = next((s for s in STAGES if sm.get(s)), None)
            m = sm.get(stage) or {}
            out.append({"leg": it["id"], "side": it.get("side"), "timeframe": book.get("timeframe"), "book": kind,
                        "alpha_id": (it.get("evidence") or {}).get("funnel_alpha_id"), "stage": stage,
                        "universe": len(book.get("universe") or []),
                        **{k: m.get(k) for k in STAT_KEYS}})
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Chỉ số tổng hợp của chiến lược trên các alpha đã đạt (quy tắc SUMMARY); không có alpha -> {"n": 0}."""
    out: Dict[str, Any] = {"n": len(rows)}
    for key, how in SUMMARY.items():
        v = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
        if v:
            out[key] = round(sum(v) / len(v), 4) if how == "mean" else (max(v) if how == "max" else int(sum(v)))
    return out


def _user_card_metrics(sim: Any) -> Dict[str, Any]:
    """Số đo thẻ alpha người dùng từ metrics.simulate của kết quả đã lưu (bộ chỉ số phẳng: ret_pct, mdd_pct, sharpe, sortino, win_rate_trades %, profit_factor_trades, trades).
    Thiếu -> None (giao diện hiện "—"), không bao giờ 0 giả; số 0 thật được giữ."""
    sim = sim or {}
    mdd = _first_num(sim, "mdd_pct")
    trades = _first_num(sim, "trades")
    return {
        "ret_pct": _first_num(sim, "ret_pct"),
        "mdd_pct": abs(mdd) if mdd is not None else None,
        "sharpe": _first_num(sim, "sharpe"),
        "sortino": _first_num(sim, "sortino"),
        "profit_factor": _first_num(sim, "profit_factor_trades"),
        "win_rate": _first_num(sim, "win_rate_trades"),
        "trades": int(trades) if trades is not None else None,
    }


def catalog(alphas_dir: Optional[str] = None) -> Dict[str, Any]:
    from backend.optimize.book.build import BY_ID, STRATEGIES
    if alphas_dir is None:
        from backend.optimize.book.build import alphas_dir as _ad
        alphas_dir = _ad()
    books = [(k, b) for k, b in (("main", read_json(os.path.join(alphas_dir, "book.json"))),
                                 ("explore", read_json(os.path.join(alphas_dir, "explore", "book.json")))) if b]
    sizing_tex, sizing_w = _sizing()
    items = []
    for st in STRATEGIES:
        legs = st["legs"]
        groups = [list(legs.items())] if st.get("doc") == "combined" else [[x] for x in legs.items()]
        for group in groups:
            cands = [BY_ID[cid] for _, cid in group]
            label = len(group) > 1
            docs = [leg_doc(c, ("Long:" if c["side"] == "LONG" else "Short:") if label else "") for c in cands]
            ex_tex, ex_w = _exits(cands[0], "BOTH" if label else cands[0]["side"])
            if label:
                ex_w.append("Hai chiều đối xứng: dấu trên cho Long, dấu dưới cho Short.")
            items.append({
                "key": "_".join([st["id"]] + ([] if label else [group[0][0].lower()])),
                "strategy": st["id"], "name": st["name"], "kind": st["kind"],
                "side": "Long + Short" if label else ("Long" if group[0][0] == "LONG" else "Short"),
                "idea": st["idea"],
                "plain": [p for d in docs for p in d["plain"]] + ex_w + [sizing_w],
                "math": [m for d in docs for m in d["math"]] + [{"title": "Dồn lệnh & thoát lệnh" if "dca_step_pct" in (cands[0].get("params_schema") or {})
                                                                        else "Thoát lệnh", "latex": r" \\ ".join(ex_tex)},
                                                               {"title": "Khối lượng", "latex": sizing_tex}],
            })
            items[-1]["stats"] = _alphas_of([cid for _, cid in group], books)
            items[-1]["summary"] = summarize(items[-1]["stats"])

    # Nhóm Alpha người dùng (C1)
    uas = list_user_alphas(base_dir=alphas_dir)
    for ua in uas:
        if ua.get("status") == "ARCHIVED":
            continue
        code = ua.get("code", "")
        plain_lines = []
        try:
            from backend.alpha.compile import compile_code
            from backend.alpha.compile import explain_program
            prog = compile_code(code, register=False)
            exp = explain_program(prog, position=(ua.get("config") or {}).get("position"))
            plain_lines = [r["action_vi"] for r in exp.get("rules", [])] + [e["desc"] for e in exp.get("execution", [])[:2]]
        except Exception:
            plain_lines = [ua.get("note") or "Chiến lược người dùng đã xác minh"]

        stat_item = {
            "leg": ua["id"],
            "side": "LONG" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "BOTH",
            "timeframe": (ua.get("config", {}) or {}).get("timeframe", "24h"),
            "book": "user",
            "alpha_id": ua["id"],
            "stage": ua.get("status", "SAVED"),
            "universe": len((ua.get("config", {}) or {}).get("symbols") or []),
            **_user_card_metrics((ua.get("metrics") or {}).get("simulate")),
        }
        items.append({
            "key": f"user_{ua['id']}",
            "strategy": ua["id"],
            "name": ua["name"],
            "kind": "Alpha người dùng",
            "side": "Long" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "Long + Short",
            "idea": ua.get("note") or f"Alpha người dùng từ nguồn {ua.get('source', 'alpha-create')}",
            "plain": plain_lines,
            "math": [],
            "stats": [stat_item],
            "summary": {
                "n": 1,
                "ret_pct": stat_item["ret_pct"],
                "mdd_pct": stat_item["mdd_pct"],
                "sharpe": stat_item["sharpe"],
                "sortino": stat_item["sortino"],
                "profit_factor": stat_item["profit_factor"],
                "win_rate": stat_item["win_rate"],
                "trades": stat_item["trades"],
            },
            "is_user_alpha": True,
            "alpha_id": ua["id"],
        })

    return {"sources": [{"key": "nora", "label": "Nora", "strategies": items}]}


# ══════════════════════════════════════════════════════════════════════════
# Top agent trade: doc ket qua da dong bang (implied exit fit + OOS) cua 10 bot copy-trade top OKX.
#
# Nguon duy nhat: crawl/store.alpha_dir('research', 'okx_top10_agents.json') (git-tracked, co provenance).
# Khong doc scripts nghien cuu; ket qua nghien cuu da duoc dong bang mot lan.
#
# GET /api/studio/alphas/top_agents
# {
#   "bots": [ { "slug", "name", "bot_type", "n_baskets", "in_sample", "caveat",
#               "exit_structure", "formula_summary", "class_mix_pct",
#               "in_sample_metrics", "criteria_is", "report_stats", "oos",
#               "mixed_runs", "mixed_runs_note" }, ... ],
#   "n_bots": 10,
#   "generated_at": "<frozen_at>",
#   "provenance": { "frozen_at", "git_commit", "source", "per_bot_sources", ... }
# }
# Neu file khong co: {"bots": [], "n_bots": 0, "reason": "..."}.
# ══════════════════════════════════════════════════════════════════════════

def _frozen_path() -> str:
    from backend.crawl.store import alpha_dir
    return alpha_dir("research", "okx_top10_agents.json")


def _empty(reason: str) -> Dict[str, Any]:
    return {"bots": [], "n_bots": 0, "reason": reason}


def top_agents() -> Dict[str, Any]:
    try:
        with open(_frozen_path(), encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return _empty("Chua co file dong bang data/alpha/research/okx_top10_agents.json")
    except (OSError, ValueError) as exc:
        return _empty(f"Khong doc duoc file dong bang okx_top10_agents.json: {exc}")
    if not isinstance(d, dict) or not isinstance(d.get("bots"), list):
        return _empty("File dong bang okx_top10_agents.json sai dinh dang (thieu 'bots')")

    prov = d.get("provenance") or {}
    bots = d["bots"]
    for b in bots:
        b.setdefault("mixed_runs", False)
        b.setdefault("mixed_runs_note", None)
    return {
        "bots": bots,
        "n_bots": len(bots),
        "generated_at": prov.get("frozen_at"),
        "provenance": prov,
    }
