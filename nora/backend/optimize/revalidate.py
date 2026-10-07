"""Kiểm lại một alpha trong kho (data/alphas/registry.json) bằng ENGINE HIỆN HÀNH theo đúng các cổng của phễu (job API `alpha_revalidate`).

Alpha cũ (vd. trend_long_perp__SOL) được dựng bằng đường tối ưu đơn tài sản đã xoá (P0.11a) và engine trước P1, nên bằng chứng trong kho
không còn tái lập được. Job này chạy lại đúng cây tín hiệu + tham số vị thế đã lưu (flows[0].ast + position) trên tài sản của alpha:
  S3  WFA tham số cố định trên dev2 (fold train/test của phễu; IS = level, kill tắt; OOS = extreme, kill bật) -> gates.evaluate_s3
  S5  hệ số khối lượng s lớn nhất trong [S5_S_MIN, 1] mà MC (>= 10.000 kịch bản + kịch bản cực xấu + trend thẳng đứng) qua -> sizing.search_scale
  S6  holdout một lần ở hệ số s (level + extreme, kill bật) -> gates.evaluate_s6
Kết luận: "validated" (kèm final_scale) hoặc "retired" (kèm mã + lý do). apply=True: ghi status/revalidation vào registry; alpha bị loại thì
cấu hình testnet của nó chuyển sang data/alphas/testnet/_retired/ (giữ lại để tra cứu, bot không còn đọc).
"""
import json
import os
import shutil
import time
import warnings
from typing import Any, Dict, List, Optional

from backend.utils.jobs import options, write_job_result

DEFAULTS = {"alpha_id": "trend_long_perp__SOL", "apply": False}
TIMEFRAME = "15m"   # khung chạy (khung tín hiệu của alpha phải >= khung này; trend_long_perp__SOL dùng 15m/1h)


def alphas_dir() -> str:
    from backend.core.params.presets import alphas_dir as _dir
    return _dir()


def load_alpha(alpha_id: str, base: Optional[str] = None) -> Dict[str, Any]:
    with open(os.path.join(base or alphas_dir(), "registry.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next((a for a in reg.get("alphas") or [] if a.get("alpha_id") == alpha_id), None)
    if al is None:
        raise SystemExit(f"Không có alpha {alpha_id} trong registry.json")
    return al


def alpha_strategy(al: Dict[str, Any], scale: float = 1.0) -> Dict[str, Any]:
    """Chiến lược PortfolioEngine của alpha (đúng tham số đã lưu; khối lượng nhân scale), chỉ chạy trên tài sản của nó."""
    from backend.optimize.funnel.sizing import scale_position
    ast = al["flows"][0]["ast"]
    return {"id": al["alpha_id"], "side": al["side"], "tree": ast["match"][0]["condition"], "stop": ast.get("stop") or [],
            "position": scale_position(al["position"], scale) if scale != 1.0 else dict(al["position"]), "symbols": [al["data_symbol"]]}


def _run(al, window, stop_fill: str, kill: bool, scale: float = 1.0) -> Dict[str, Any]:
    from backend.core.backtest.run import run
    from backend.core.strategy.book import BASE_RISK_PER_TRADE_PCT, RISK
    risk = {**RISK, "kill_switch_dd_pct": RISK["kill_switch_dd_pct"] if kill else 0}
    return run([], [al["data_symbol"]], int(window[0]), int(window[1]), BASE_RISK_PER_TRADE_PCT, stop_fill, risk,
               extra_strategies=[alpha_strategy(al, scale)], base_frame=TIMEFRAME)


def _oos(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"ret_pct": r["ret_pct"], "mdd_pct": r["mdd_pct"], "trades": r["trades"], "halted": bool(r.get("halted_at"))}


def wfa(al, folds: List[Dict[str, Any]], scale: float = 1.0) -> Dict[str, Any]:
    """WFA tham số cố định (cùng quy ước phễu S3) -> aggregate_wfa (summary/metrics/series/trades) + shock (vị thế ngược chiều lớn nhất)."""
    from backend.carlo.monte_carlo import merge_exposure, vertical_exposure
    from backend.core.metrics.trades import rows_from_trade_list
    from backend.optimize.funnel.evaluate import aggregate_wfa
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
    from backend.optimize.funnel import evaluate as bt
    from backend.optimize.funnel import gates, sizing
    w = windows or gates.compute_windows([al["data_symbol"]])
    folds = bt.fold_job_plan(gates.wfa_folds(w))
    rep: Dict[str, Any] = {"alpha_id": al["alpha_id"], "symbol": al["data_symbol"], "windows": gates.windows_iso(w), "checked_at": int(time.time() * 1000)}
    agg = wfa(al, folds)
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
    from backend.utils.jsonsafe import json_default
    base = base or alphas_dir()
    path = os.path.join(base, "registry.json")
    with open(path, encoding="utf-8") as fh:
        reg = json.load(fh)
    al = next(a for a in reg["alphas"] if a.get("alpha_id") == rep["alpha_id"])
    al["status"] = rep["status"]
    al["revalidation"] = {k: v for k, v in rep.items() if k != "alpha_id"}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2, default=json_default)
    os.replace(tmp, path)
    changed = [path]
    tn = os.path.join(base, "testnet", f"{rep['alpha_id']}.json")
    if rep["status"] == "retired" and os.path.isfile(tn):
        dst = os.path.join(base, "testnet", "_retired", f"{rep['alpha_id']}.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(tn, dst)
        changed.append(dst)
    return changed


def run_job(params=None) -> Dict[str, Any]:
    warnings.filterwarnings("ignore")
    a = options(DEFAULTS, params)
    from backend.utils.memwatch import require_memory_limit
    require_memory_limit("alpha_revalidate")
    al = load_alpha(a.alpha_id)
    from backend.core.data.quality_gate import require_data_ok_or_exit
    require_data_ok_or_exit([al["data_symbol"]])
    rep = revalidate(al)
    print(f"{rep['alpha_id']}: {rep['status']}" + (f" (s={rep.get('final_scale')})" if rep["status"] == "validated" else f" — {rep['reason']}"),
          flush=True)
    if a.apply:
        rep["changed"] = apply_result(rep)
        print("đã ghi:", rep["changed"], flush=True)
    write_job_result(rep)
    return rep
