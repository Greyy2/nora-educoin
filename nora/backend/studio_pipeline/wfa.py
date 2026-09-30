"""Walk-Forward Analysis (WFA) Orchestrator & Windowed Runner cho Studio Pipeline.

Thực hiện:
- Tự động chia cửa sổ trượt In-Sample (Train) và Out-of-Sample (Test) không chồng lấp.
- Tối ưu tham số trên In-Sample (Train) và test cố định trên Out-of-Sample (Test).
- Đánh giá tiêu chí Acceptance Gate (min folds, min positive ratio, min trades, max MDD, compounded return).
- Xuất danh sách lệnh OOS tổng hợp (aggregate_oos_trades) cho Monte Carlo.
"""
import itertools
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.alpha.validator import ASTValidator
from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import MetricsCalculator
from backend.core.params import StrategyParams
from backend.db.local_pkl import default_data_root, has_frame, resolve_symbol_dir
from .jobs import complete_wfa_job, fail_wfa_job, update_wfa_progress
from .schemas import (
    StrategySnapshot,
    WfaFoldConfig,
    WfaFoldResult,
    WfaResultContract,
)


def _ts_to_date_str(ts_ms: Optional[int]) -> str:
    if not ts_ms:
        return "N/A"
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def generate_folds(
    start_ts: int,
    end_ts: int,
    train_days: int = 30,
    test_days: int = 10,
    step_days: Optional[int] = None,
    embargo_days: int = 0,
    anchored: bool = False,
    **kwargs,
) -> List[Dict[str, int]]:
    """
    Sinh các cửa sổ fold theo ngày, đảm bảo OOS không chồng lấp (Phase 3.1).
    Nếu step_days < test_days, raise ValueError để ngăn chặn OOS chồng lấp.
    """
    D = 86_400_000
    step = (step_days or test_days) * D
    if step < test_days * D:
        raise ValueError(f"step ({step // D}d) < test ({test_days}d) -> OOS chồng lấp! Không được phép.")

    folds = []
    test_start = start_ts + (train_days + embargo_days) * D
    while test_start + test_days * D <= end_ts:
        train_end = test_start - embargo_days * D
        train_start = start_ts if anchored else train_end - train_days * D
        folds.append({
            "train_start_ts": int(train_start),
            "train_end_ts": int(train_end),
            "test_start_ts": int(test_start),
            "test_end_ts": int(test_start + test_days * D),
        })
        test_start += step
    return folds


def _run_single_window(
    symbol: str,
    flows: List[Dict[str, Any]],
    start_ts: int,
    end_ts: int,
    initial_capital: float = 10000.0,
    leverage: float = 1.0,
    stop_loss_rate: float = 0.0,
    take_profit_rate: float = 0.0,
    using_match_price: bool = True,
    max_open_trades: int = 45,
    timeout: int = 0,
    trade_start_ts: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Chạy backtest cho một cửa sổ thời gian đơn lẻ qua BacktestEngine causal chuẩn."""
    engine = BacktestEngine(
        account_id=0,
        campaign_id=0,
        symbol=symbol,
        start_ts=start_ts,
        end_ts=end_ts,
        trade_start_ts=trade_start_ts,
    )

    for index, flow in enumerate(flows):
        flow_ast = dict(flow.get("ast", flow))
        flow_type = str(flow.get("type", flow_ast.get("type", "LONG"))).upper()
        flow_name = str(flow.get("name") or flow.get("id") or f"{flow_type}_{index + 1}")
        if flow_type not in flow_name.upper():
            flow_name = f"{flow_type}_{flow_name}"
        flow_ast["type"] = flow_type

        params = StrategyParams(
            name=flow_name,
            strategy="studio_ast",
            data_type="1m",
            using_match_price=bool(using_match_price),
            max_open_trades=int(max_open_trades),
            volume_rate=1.0,
            leverage=int(leverage),
            stop_loss_rate=float(stop_loss_rate),
            take_profit_rate=float(take_profit_rate),
            timeout=int(timeout),
            extra={"ast": flow_ast, "type": flow_type},
        )
        engine.add_strategy_flow(flow_name, params)

    engine.load_data()
    if engine.df_1m is None or engine.df_1m.empty:
        return {"return_pct": 0.0, "max_drawdown_pct": 0.0, "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0}, []

    engine.run()
    res = engine.get_results()
    positions = res.get("positions", [])

    base = MetricsCalculator.calculate(positions, initial_capital)
    total_trades = int(base.get("total_trades", 0) or 0)
    win_rate = float(base.get("winrate", 0.0) or 0.0)
    return_pct = float(base.get("total_pnl_pct", 0.0) or 0.0)
    mdd_pct = float(base.get("max_drawdown_pct", 0.0) or 0.0)
    profit_factor = float(base.get("profit_factor", 0.0) or 0.0)
    net_profit = round(initial_capital * return_pct / 100.0, 2)

    # Thu thập danh sách chi tiết các vị thế
    trade_items: List[Dict[str, Any]] = []
    for index, pos in enumerate(positions, start=1):
        pnl_pct = round(float(pos.profit_pct or 0.0), 4)
        pnl_usd = round(initial_capital * pnl_pct / 100.0, 2)
        pos_type = str(getattr(pos.pos_type, "name", pos.pos_type) or "LONG").upper()
        trade_items.append({
            "trade_id": str(pos.result_id or f"{pos.enter_time}_{index}"),
            "pos_type": pos_type,
            "entry_time": pos.enter_time,
            "entry_date": _ts_to_date_str(pos.enter_time),
            "entry_price": float(pos.enter_price or 0.0),
            "close_time": pos.close_time or pos.enter_time,
            "close_date": _ts_to_date_str(pos.close_time),
            "close_price": float(pos.close_price or 0.0),
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "reason": str(pos.close_reason or pos.start_reason or ""),
        })

    summary = {
        "return_pct": return_pct,
        "max_drawdown_pct": mdd_pct,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_profit": net_profit,
    }
    return summary, trade_items


def _optimize_is(
    symbol: str,
    flows: List[Dict[str, Any]],
    fold_range: Dict[str, int],
    grid: Dict[str, List[Any]],
    cfg: WfaFoldConfig,
    base_params: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Tối ưu tham số trên In-Sample (Train).
    Trả về (chosen_params, is_summary).
    is_summary có thêm key 'insufficient_is_trades'=True nếu không combo nào đạt min_is_trades.
    """
    if not grid:
        s, _ = _run_single_window(
            symbol=symbol,
            flows=flows,
            start_ts=fold_range["train_start_ts"],
            end_ts=fold_range["train_end_ts"],
            **base_params,
        )
        s["insufficient_is_trades"] = False
        return base_params, s

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    if len(combos) > 50:
        combos = combos[:50]

    best = None
    min_is_trades = getattr(cfg, "min_is_trades", 10) or 10

    for combo in combos:
        param_update = dict(zip(keys, combo))
        p = {**base_params, **param_update}
        s, _ = _run_single_window(
            symbol=symbol,
            flows=flows,
            start_ts=fold_range["train_start_ts"],
            end_ts=fold_range["train_end_ts"],
            **p,
        )
        if s["total_trades"] < min_is_trades:
            continue
        score = s["return_pct"] / max(s["max_drawdown_pct"], 1.0)
        if best is None or score > best[0]:
            best = (score, p, s)

    if best is not None:
        best[2]["insufficient_is_trades"] = False
        return best[1], best[2]

    # Không có combo nào đạt min_is_trades → fallback nhưng đánh dấu fold
    s_fallback, _ = _run_single_window(
        symbol=symbol,
        flows=flows,
        start_ts=fold_range["train_start_ts"],
        end_ts=fold_range["train_end_ts"],
        **base_params,
    )
    s_fallback["insufficient_is_trades"] = True
    return base_params, s_fallback


def execute_wfa_pipeline(
    job_id: str,
    snapshot: StrategySnapshot,
    cfg: WfaFoldConfig,
    source_handle: str,
):
    """Tiến trình thực thi WFA hoàn chỉnh chạy trên background thread."""
    try:
        raw_sym = str(snapshot.symbol or "").upper().strip()
        if not raw_sym or raw_sym == "NONE":
            fail_wfa_job(job_id, "Symbol là bắt buộc, không được để trống hoặc fallback ngầm.")
            return

        data_root = default_data_root()
        sym_dir = resolve_symbol_dir(raw_sym, data_root=data_root)
        if not sym_dir or not os.path.isdir(sym_dir):
            fail_wfa_job(job_id, f"Symbol '{raw_sym}' không tồn tại trong data_root. Vui lòng crawl trước khi chạy WFA.")
            return
        symbol = os.path.basename(sym_dir).upper()

        flows = snapshot.flows
        if not flows:
            fail_wfa_job(job_id, "Chiến lược không có flows AST.")
            return

        # Kiểm tra dữ liệu nến
        for frame in ["1m", "4h"]:
            if not has_frame(symbol, frame, data_root=data_root):
                fail_wfa_job(job_id, f"Thiếu nến {frame} cho {symbol} trong data_root.")
                return

        start_ts = snapshot.start_ts
        end_ts = snapshot.end_ts
        if start_ts <= 0 or end_ts <= 0 or end_ts <= start_ts:
            from backend.db.local_pkl import fetch_candles_df
            df_check = fetch_candles_df(symbol, "1m", data_root=default_data_root())
            if not df_check.empty:
                max_ts = int(df_check["open_time"].max())
                min_ts = int(df_check["open_time"].min())
                start_ts = max(min_ts, max_ts - (60 * 86_400_000))
                end_ts = max_ts

        # Sinh danh sách các Fold theo ngày (Phase 3.1)
        raw_folds = generate_folds(
            start_ts=start_ts,
            end_ts=end_ts,
            train_days=cfg.train_days,
            test_days=cfg.test_days,
            step_days=cfg.step_days,
            embargo_days=cfg.embargo_days,
            anchored=cfg.anchored,
        )

        if not raw_folds:
            fail_wfa_job(job_id, "Khoảng thời gian không đủ để tạo ít nhất 1 Fold WFA hợp lệ.")
            return

        total_folds = len(raw_folds)
        update_wfa_progress(job_id, 0, total_folds, f"Đã sinh {total_folds} folds không chồng lấp. Bắt đầu kiểm định...")

        base_params = {
            "initial_capital": snapshot.initial_capital,
            "leverage": snapshot.leverage,
            "stop_loss_rate": snapshot.stop_loss_rate,
            "take_profit_rate": snapshot.take_profit_rate,
            "using_match_price": snapshot.using_match_price,
            "max_open_trades": snapshot.max_open_trades,
            "timeout": snapshot.timeout,
        }
        grid = snapshot.param_grid or {}

        fold_results: List[WfaFoldResult] = []
        all_oos_trades: List[Dict[str, Any]] = []
        chosen_param_list: List[Dict[str, Any]] = []

        for idx, fold_range in enumerate(raw_folds, start=1):
            update_wfa_progress(job_id, idx - 1, total_folds, f"Đang chạy Fold {idx}/{total_folds} (IS Optim -> OOS Test)...")

            # 1. Tối ưu In-Sample (Train)
            chosen_params, is_summary = _optimize_is(
                symbol=symbol,
                flows=flows,
                fold_range=fold_range,
                grid=grid,
                cfg=cfg,
                base_params=base_params,
            )
            chosen_param_list.append(chosen_params)

            # 2. Chạy Out-of-Sample (Test) với chosen_params và warm-up
            # Dùng trade_start_ts = test_start để indicators được làm ấm từ train_end
            warmup_ms = 5 * 86_400_000
            oos_load_start = max(fold_range["train_end_ts"] - warmup_ms, fold_range["train_start_ts"])
            oos_summary, oos_trades = _run_single_window(
                symbol=symbol,
                flows=flows,
                start_ts=oos_load_start,
                end_ts=fold_range["test_end_ts"],
                trade_start_ts=fold_range["test_start_ts"],
                **chosen_params,
            )

            # Đánh giá tiêu chí từng fold
            gate_notes = []
            passed_gate = True
            if is_summary.get("insufficient_is_trades", False):
                passed_gate = False
                gate_notes.append(f"IS: không có combo tham số nào đạt min_is_trades={cfg.min_is_trades}")
            if oos_summary["return_pct"] < cfg.min_oos_profit_pct:
                passed_gate = False
                gate_notes.append(f"OOS Profit {oos_summary['return_pct']}% < {cfg.min_oos_profit_pct}%")
            if oos_summary["max_drawdown_pct"] > cfg.max_oos_mdd_pct:
                passed_gate = False
                gate_notes.append(f"OOS MDD {oos_summary['max_drawdown_pct']}% > {cfg.max_oos_mdd_pct}%")
            if is_summary["total_trades"] < cfg.min_is_trades:
                passed_gate = False
                gate_notes.append(f"IS Trades {is_summary['total_trades']} < {cfg.min_is_trades}")

            fold_res = WfaFoldResult(
                fold_index=idx,
                train_start_ts=fold_range["train_start_ts"],
                train_end_ts=fold_range["train_end_ts"],
                train_start_date=_ts_to_date_str(fold_range["train_start_ts"]),
                train_end_date=_ts_to_date_str(fold_range["train_end_ts"]),
                test_start_ts=fold_range["test_start_ts"],
                test_end_ts=fold_range["test_end_ts"],
                test_start_date=_ts_to_date_str(fold_range["test_start_ts"]),
                test_end_date=_ts_to_date_str(fold_range["test_end_ts"]),
                is_return_pct=is_summary["return_pct"],
                is_max_drawdown_pct=is_summary["max_drawdown_pct"],
                is_trades_count=is_summary["total_trades"],
                is_win_rate=is_summary["win_rate"],
                oos_return_pct=oos_summary["return_pct"],
                oos_max_drawdown_pct=oos_summary["max_drawdown_pct"],
                oos_trades_count=oos_summary["total_trades"],
                oos_win_rate=oos_summary["win_rate"],
                oos_profit_factor=oos_summary["profit_factor"],
                chosen_params=chosen_params,
                passed_gate=passed_gate,
                gate_notes=gate_notes,
                oos_trades=oos_trades,
            )
            fold_results.append(fold_res)
            all_oos_trades.extend(oos_trades)

        update_wfa_progress(job_id, total_folds, total_folds, "Tổng hợp kết quả OOS và đánh giá Acceptance Gate...")

        # Thống kê OOS tổng thể
        positive_folds_count = sum(1 for f in fold_results if f.oos_return_pct > 0)
        worst_fold_mdd = max((f.oos_max_drawdown_pct for f in fold_results), default=0.0)
        avg_oos_mdd = round(sum(f.oos_max_drawdown_pct for f in fold_results) / total_folds, 2) if total_folds > 0 else 0.0
        avg_oos_return = round(sum(f.oos_return_pct for f in fold_results) / total_folds, 2) if total_folds > 0 else 0.0
        total_oos_trades_count = len(all_oos_trades)
        winning_oos_trades = sum(1 for t in all_oos_trades if t.get("pnl_usd", 0.0) > 0)
        overall_oos_win_rate = round(winning_oos_trades / total_oos_trades_count * 100.0, 2) if total_oos_trades_count > 0 else 0.0

        # Lợi nhuận OOS tổng: tính lãi kép ∏(1+r) - 1
        compounded_return = 1.0
        for f in fold_results:
            compounded_return *= (1.0 + f.oos_return_pct / 100.0)
        total_compounded_oos_return = round((compounded_return - 1.0) * 100.0, 2)

        # Tính WFE (Walk-Forward Efficiency)
        total_is_days = sum((f.train_end_ts - f.train_start_ts) / 86_400_000 for f in fold_results)
        total_oos_days = sum((f.test_end_ts - f.test_start_ts) / 86_400_000 for f in fold_results)
        avg_is_ret = sum(f.is_return_pct for f in fold_results) / total_folds if total_folds > 0 else 0.0
        ann_is = avg_is_ret * (365.0 / max(total_is_days / total_folds, 1.0)) if total_folds > 0 else 0.0
        ann_oos = avg_oos_return * (365.0 / max(total_oos_days / total_folds, 1.0)) if total_folds > 0 else 0.0
        wfe = round(ann_oos / ann_is, 2) if ann_is > 0 else 0.0

        # Sắp xếp lệnh OOS theo thời gian vào lệnh
        all_oos_trades.sort(key=lambda t: t.get("entry_time", 0))

        # Đường vốn OOS tổng hợp (lãi kép)
        aggregate_oos_equity = []
        running_equity = snapshot.initial_capital
        peak_equity = running_equity
        for i, trade in enumerate(all_oos_trades):
            running_equity *= (1.0 + trade.get("pnl_pct", 0.0) / 100.0)
            peak_equity = max(peak_equity, running_equity)
            dd = round(((peak_equity - running_equity) / peak_equity * 100.0), 2) if peak_equity > 0 else 0.0
            aggregate_oos_equity.append({
                "time": trade.get("close_time", trade.get("entry_time", 0)),
                "date": trade.get("close_date", ""),
                "equity": round(running_equity, 2),
                "drawdown": dd,
                "trade_index": i + 1,
            })

        # Đánh giá Acceptance Gate (Phase 3.3)
        min_folds = getattr(cfg, "min_folds", 4) or 4
        min_pos_ratio = getattr(cfg, "min_positive_ratio", 0.6) or 0.6
        min_oos_trades = getattr(cfg, "min_oos_trades", 30) or 30
        min_total_return = getattr(cfg, "min_total_oos_profit_pct", 0.0) or 0.0
        max_oos_mdd = getattr(cfg, "max_oos_mdd_pct", 25.0) or 25.0

        pos_ratio = positive_folds_count / total_folds if total_folds > 0 else 0.0

        gate_checks = {
            "total_folds": {
                "label": f"Số lượng Fold ({total_folds})",
                "required": f">= {min_folds} folds",
                "actual": total_folds,
                "passed": total_folds >= min_folds,
            },
            "positive_ratio": {
                "label": f"Tỉ lệ Fold có lãi ({positive_folds_count}/{total_folds} = {pos_ratio*100:.1f}%)",
                "required": f">= {min_pos_ratio*100:.1f}%",
                "actual": round(pos_ratio * 100.0, 1),
                "passed": pos_ratio >= min_pos_ratio,
            },
            "total_trades": {
                "label": f"Tổng số lệnh OOS ({total_oos_trades_count})",
                "required": f">= {min_oos_trades} trades",
                "actual": total_oos_trades_count,
                "passed": total_oos_trades_count >= min_oos_trades,
            },
            "worst_mdd": {
                "label": f"Max Drawdown tệ nhất từng Fold ({worst_fold_mdd}%)",
                "required": f"<= {max_oos_mdd}%",
                "actual": worst_fold_mdd,
                "passed": worst_fold_mdd <= max_oos_mdd,
            },
            "compounded_return": {
                "label": f"Tổng lợi nhuận OOS lãi kép ({total_compounded_oos_return}%)",
                "required": f">= {min_total_return}%",
                "actual": total_compounded_oos_return,
                "passed": total_compounded_oos_return >= min_total_return,
            },
        }
        acceptance_gate_passed = all(check["passed"] for check in gate_checks.values())

        # Tính param_stability thực tế:
        # Tỉ lệ folds dùng chung param combo đa số (mode) / tổng folds.
        # 1.0 = mọi fold chọn cùng một combo (cực kỳ ổn định).
        # 0.0 = mỗi fold chọn combo khác nhau (không ổn định).
        if chosen_param_list:
            import json as _json
            serialized = [_json.dumps(p, sort_keys=True) for p in chosen_param_list]
            from collections import Counter
            most_common_count = Counter(serialized).most_common(1)[0][1]
            param_stability_val = round(most_common_count / len(chosen_param_list), 4)
        else:
            param_stability_val = None

        wfa_result = WfaResultContract(
            wfa_id=job_id,
            source_handle=source_handle,
            strategy_name=snapshot.name,
            symbol=symbol,
            total_folds=total_folds,
            folds=fold_results,
            positive_folds_count=positive_folds_count,
            total_oos_return_pct=total_compounded_oos_return,
            avg_oos_return_pct=avg_oos_return,
            worst_fold_mdd_pct=worst_fold_mdd,
            avg_oos_mdd_pct=avg_oos_mdd,
            total_oos_trades=total_oos_trades_count,
            overall_oos_win_rate=overall_oos_win_rate,
            wfe=wfe,
            param_stability=param_stability_val,
            acceptance_gate_passed=acceptance_gate_passed,
            gate_checks=gate_checks,
            aggregate_oos_trades=all_oos_trades,
            aggregate_oos_equity=aggregate_oos_equity,
            generated_at=int(time.time() * 1000),  # milliseconds, consistent with MC
        )

        complete_wfa_job(job_id, wfa_result.model_dump())

    except Exception as e:
        import traceback
        traceback.print_exc()
        fail_wfa_job(job_id, f"Lỗi không xác định khi chạy WFA: {str(e)}")
