"""API Router cho Alpha Studio AST Builder & canonical simulation."""
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.alpha.features_meta import FEATURES_CATALOG, OPERATORS_CATALOG
from backend.alpha.templates import STRATEGY_SAMPLES
from backend.alpha.validator import ASTValidationError, ASTValidator
from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import MetricsCalculator
from backend.core.params import StrategyParams
from backend.db.local_pkl import default_data_root, has_frame
from backend.db.models import OrderModel, PositionModel
from backend.studio_pipeline.schemas import (
    StrategySnapshot,
    BacktestResultContract,
    WfaFoldConfig,
    WfaRunRequest,
    MonteCarloRunRequest,
)
from backend.studio_pipeline.jobs import (
    save_backtest_source,
    get_backtest_source,
    list_backtest_history,
    create_wfa_job,
    get_wfa_job,
    list_wfa_history,
    create_mc_job,
    get_mc_job,
    list_mc_history,
    generate_handle,
    submit_background_task,
)
from backend.studio_pipeline.wfa import execute_wfa_pipeline
from backend.studio_pipeline.monte_carlo import execute_monte_carlo_pipeline

router = APIRouter(prefix="/api/studio", tags=["studio"])

REQUIRED_FRAMES = ["1m", "4h"]
LOW_COVERAGE_1M_CANDLES = 3 * 24 * 60


class SimulateRequest(BaseModel):
    symbol: str = Field(..., description="Asset symbol in local PKL data root")
    start_ts: int = Field(..., description="Start timestamp in milliseconds")
    end_ts: int = Field(..., description="End timestamp in milliseconds")
    flows: Optional[List[Dict[str, Any]]] = Field(None, description="Alpha Studio AST flow list")
    code: Optional[str] = Field(None, description="Deprecated Python script payload; disabled by default")
    initial_capital: float = Field(10000.0, ge=1.0, le=1_000_000_000.0)
    capital: Optional[float] = Field(None, ge=1.0, le=1_000_000_000.0)
    leverage: float = Field(1.0, ge=1.0, le=100.0)
    using_match_price: bool = Field(True)
    max_open_trades: int = Field(45, ge=1, le=100)
    stop_loss_rate: float = Field(0.0, ge=0.0, le=100.0)
    take_profit_rate: float = Field(0.0, ge=0.0, le=1000.0)
    timeout: int = Field(0, ge=0, le=525600)
    result_trade_limit: int = Field(300, ge=1, le=2000)


class ScriptSimulateRequest(BaseModel):
    code: str = Field(..., min_length=1)
    symbol: str = Field("SOL")
    timeframe: str = Field("15m")
    capital: float = Field(10000.0, ge=1.0)
    leverage: float = Field(1.0, ge=1.0)
    fee_rate: float = Field(0.0005, ge=0.0)
    slippage: float = Field(0.0002, ge=0.0)
    stop_loss_pct: float = Field(0.0, ge=0.0)
    take_profit_pct: float = Field(0.0, ge=0.0)
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    limit_candles: Optional[int] = Field(None, ge=1)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "mode": "ast_builder",
        "execution": "canonical_backtest_engine",
        "script_mode_enabled": _script_mode_enabled(),
        "required_frames": REQUIRED_FRAMES,
        "max_backtest_days": BacktestEngine.MAX_BACKTEST_DAYS,
    }


@router.get("/samples")
def get_samples() -> Dict[str, Any]:
    return {"samples": STRATEGY_SAMPLES, "mode": "ast_builder"}


@router.get("/features")
def get_features() -> Dict[str, Any]:
    return {
        "features": FEATURES_CATALOG,
        "supported_columns": {
            frame: ASTValidator.supported_columns(frame)
            for frame in sorted(ASTValidator.VALID_FRAMES)
        },
        "frames": sorted(ASTValidator.VALID_FRAMES),
    }


@router.get("/operators")
def get_operators() -> Dict[str, Any]:
    return {
        "operators": OPERATORS_CATALOG,
        "comparison_operators": sorted(ASTValidator.VALID_OPERATORS),
        "math_operators": sorted(ASTValidator.VALID_MATH_LOGIC),
    }


@router.get("/datasets")
def get_datasets() -> Dict[str, Any]:
    data_root = default_data_root()
    datasets: List[Dict[str, Any]] = []

    if os.path.isdir(data_root):
        for asset in sorted(os.listdir(data_root)):
            asset_dir = os.path.join(data_root, asset)
            if not os.path.isdir(asset_dir) or asset.startswith("."):
                continue

            pkl_files = [name for name in sorted(os.listdir(asset_dir)) if name.endswith(".pkl")]
            timeframes = [name[:-4] for name in pkl_files]
            frame_details = []
            for file_name in pkl_files:
                path = os.path.join(asset_dir, file_name)
                frame_details.append({
                    "timeframe": file_name[:-4],
                    "size_kb": round(os.path.getsize(path) / 1024, 1),
                })

            frame_summaries = {
                frame: _frame_summary(asset_dir, frame)
                for frame in REQUIRED_FRAMES
                if os.path.isfile(os.path.join(asset_dir, f"{frame}.pkl"))
            }
            has_required = all(frame in frame_summaries for frame in REQUIRED_FRAMES)
            summary_1m = frame_summaries.get("1m", {})
            warnings = _dataset_warnings(summary_1m, has_required)

            datasets.append({
                "asset": asset,
                "symbol": asset,
                "timeframes": timeframes,
                "timeframe_details": frame_details,
                "required_frames": REQUIRED_FRAMES,
                "has_required_frames": has_required,
                "frame_summaries": frame_summaries,
                "summary_candles": summary_1m.get("candles", 0),
                "start_ts": summary_1m.get("start_ts"),
                "end_ts": summary_1m.get("end_ts"),
                "date_range": summary_1m.get("date_range", "N/A"),
                "warnings": warnings,
            })

    return {
        "datasets": datasets,
        "data_root": data_root,
        "required_frames": REQUIRED_FRAMES,
        "max_backtest_days": BacktestEngine.MAX_BACKTEST_DAYS,
    }


@router.post("/simulate")
def run_simulation(req: SimulateRequest) -> Dict[str, Any]:
    start_wall = time.time()
    clean_symbol = req.symbol.strip().upper()

    if req.code and not req.flows:
        raise HTTPException(
            status_code=403,
            detail="Python script mode đã được tắt mặc định. Hãy dùng AST/flows Builder hoặc bật endpoint /simulate-script bằng NORA_STUDIO_ENABLE_SCRIPT=1.",
        )
    if not req.flows:
        raise HTTPException(status_code=400, detail="Cần gửi ít nhất một flow AST trong trường flows.")

    _validate_range(req.start_ts, req.end_ts)
    enabled_flows = _enabled_flows(req.flows)
    if not enabled_flows:
        raise HTTPException(status_code=400, detail="Không có flow nào đang bật để mô phỏng.")

    try:
        ASTValidator.validate_flows_or_raise(enabled_flows)
    except ASTValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    missing_frames = [
        frame for frame in REQUIRED_FRAMES
        if not has_frame(clean_symbol, frame, data_root=default_data_root())
    ]
    if missing_frames:
        raise HTTPException(
            status_code=404,
            detail=f"{clean_symbol} thiếu dữ liệu bắt buộc cho Studio: {', '.join(missing_frames)}. Studio không tự crawl khi thiếu data.",
        )

    initial_capital = float(req.capital if req.capital is not None else req.initial_capital)

    try:
        engine = BacktestEngine(
            account_id=0,
            campaign_id=0,
            symbol=clean_symbol,
            start_ts=int(req.start_ts),
            end_ts=int(req.end_ts),
        )
        for index, flow in enumerate(enabled_flows):
            flow_ast = _flow_ast(flow)
            flow_type = str(flow_ast.get("type", "LONG")).upper()
            flow_name = str(flow.get("name") or flow.get("id") or f"{flow_type}_{index + 1}")
            if flow_type not in flow_name.upper():
                flow_name = f"{flow_type}_{flow_name}"

            params = StrategyParams(
                name=flow_name,
                strategy="studio_ast",
                data_type="1m",
                using_match_price=bool(req.using_match_price),
                max_open_trades=int(req.max_open_trades),
                volume_rate=1.0,
                leverage=int(req.leverage),
                stop_loss_rate=float(req.stop_loss_rate),
                take_profit_rate=float(req.take_profit_rate),
                timeout=int(req.timeout),
                extra={"ast": flow_ast},
            )
            engine.add_strategy_flow(flow_name, params)

        engine.load_data()
        if engine.df_1m is None or engine.df_1m.empty:
            raise HTTPException(status_code=404, detail=f"Không có nến 1m cho {clean_symbol} trong khoảng đã chọn.")
        if engine.df_4h is None or engine.df_4h.empty:
            raise HTTPException(status_code=404, detail=f"Không có nến 4h cho {clean_symbol} trong khoảng đã chọn.")
        engine.run()
        raw_results = engine.get_results()
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi mô phỏng Studio: {exc}")

    positions = raw_results.get("positions", [])
    orders = raw_results.get("orders", [])
    metrics = _metrics_payload(positions, initial_capital)
    trades = _serialize_positions(positions, req.result_trade_limit, initial_capital)
    all_trades = _serialize_positions(positions, len(positions), initial_capital)
    equity_curve = _closed_trade_curve(positions, initial_capital)
    elapsed_ms = int((time.time() - start_wall) * 1000)

    # Chuẩn hóa & lưu trữ contract nguồn cho WFA & Monte Carlo
    source_handle = generate_handle("bt_src")
    strat_name = str(enabled_flows[0].get("name", "Studio Strategy")) if enabled_flows else f"{clean_symbol} Strategy"
    snapshot = StrategySnapshot(
        strategy_id=source_handle,
        name=strat_name,
        symbol=clean_symbol,
        start_ts=int(req.start_ts),
        end_ts=int(req.end_ts),
        flows=enabled_flows,
        initial_capital=initial_capital,
        leverage=float(req.leverage),
        using_match_price=bool(req.using_match_price),
        max_open_trades=int(req.max_open_trades),
        stop_loss_rate=float(req.stop_loss_rate),
        take_profit_rate=float(req.take_profit_rate),
        timeout=int(req.timeout),
    )
    source_contract = BacktestResultContract(
        source_handle=source_handle,
        strategy_snapshot=snapshot,
        symbol=clean_symbol,
        summary=metrics,
        trades=all_trades,
        equity_curve=equity_curve,
        generated_at=int(time.time() * 1000),
    )
    save_backtest_source(source_contract.model_dump())

    return {
        "mode": "ast_builder",
        "engine": "BacktestEngine",
        "symbol": clean_symbol,
        "source_handle": source_handle,
        "strategy_snapshot": snapshot.model_dump(),
        "execution_frame": "1m",
        "indicator_frame": "4h",
        "timeframe": "1m/4h",
        "start_ts": int(req.start_ts),
        "end_ts": int(req.end_ts),
        "execution_time_ms": elapsed_ms,
        "metrics": metrics,
        "trades": trades,
        "orders": _serialize_orders(orders),
        "positions_count": len(positions),
        "orders_count": len(orders),
        "returned_trades": len(trades),
        "result_trade_limit": req.result_trade_limit,
        "equity_curve": equity_curve,
        "equity_curve_mode": "closed_trade_cumulative_pct",
        "data": {
            "candles_1m": 0 if engine.df_1m is None else len(engine.df_1m),
            "candles_4h": 0 if engine.df_4h is None else len(engine.df_4h),
            "required_frames": REQUIRED_FRAMES,
            "max_backtest_days": BacktestEngine.MAX_BACKTEST_DAYS,
        },
        "flows": [
            {
                "name": str(flow.get("name") or flow.get("id") or f"flow_{index + 1}"),
                "type": str(_flow_ast(flow).get("type", "LONG")).upper(),
            }
            for index, flow in enumerate(enabled_flows)
        ],
    }


@router.post("/simulate-script")
def run_script_simulation(req: ScriptSimulateRequest) -> Dict[str, Any]:
    if not _script_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail="Python script execution đang tắt. Chỉ bật local bằng NORA_STUDIO_ENABLE_SCRIPT=1 khi thật sự cần nghiên cứu nội bộ.",
        )

    from backend.alpha.script_engine import ScriptStrategyRunner
    from backend.db.local_pkl import fetch_candles_df

    start_wall = time.time()
    clean_symbol = req.symbol.strip().upper()
    clean_tf = req.timeframe.strip().lower()
    df = fetch_candles_df(
        symbol=clean_symbol,
        frame=clean_tf,
        start_ts=req.start_ts,
        end_ts=req.end_ts,
        data_root=default_data_root(),
    )
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu {clean_symbol} {clean_tf}.")
    if req.limit_candles and len(df) > req.limit_candles:
        df = df.iloc[-req.limit_candles:].reset_index(drop=True)

    try:
        results = ScriptStrategyRunner.compile_and_run(
            code=req.code,
            df=df,
            initial_capital=req.capital,
            leverage=req.leverage,
            fee_rate=req.fee_rate,
            slippage=req.slippage,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    results["execution_time_ms"] = int((time.time() - start_wall) * 1000)
    results["symbol"] = clean_symbol
    results["timeframe"] = clean_tf
    results["mode"] = "python_script"
    return results


def _validate_range(start_ts: int, end_ts: int) -> None:
    if end_ts <= start_ts:
        raise HTTPException(status_code=400, detail="end_ts phải lớn hơn start_ts.")
    days = (end_ts - start_ts) / 86_400_000
    if days > BacktestEngine.MAX_BACKTEST_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Khoảng mô phỏng {days:.1f} ngày vượt giới hạn {BacktestEngine.MAX_BACKTEST_DAYS} ngày.",
        )


def _enabled_flows(flows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [flow for flow in flows if isinstance(flow, dict) and flow.get("enabled", True)]


def _flow_ast(flow: Dict[str, Any]) -> Dict[str, Any]:
    ast = flow.get("ast", flow)
    return ast if isinstance(ast, dict) else {}


def _script_mode_enabled() -> bool:
    return os.environ.get("NORA_STUDIO_ENABLE_SCRIPT", "").strip().lower() in {"1", "true", "yes", "on"}


def _frame_summary(asset_dir: str, frame: str) -> Dict[str, Any]:
    path = os.path.join(asset_dir, f"{frame}.pkl")
    summary: Dict[str, Any] = {"timeframe": frame, "candles": 0, "date_range": "N/A"}
    try:
        df = pd.read_pickle(path)
        summary["candles"] = int(len(df))
        summary["columns"] = list(df.columns)
        if not df.empty and "open_time" in df.columns:
            open_time = pd.to_numeric(df["open_time"], errors="coerce").dropna()
            if not open_time.empty:
                start_ts = int(open_time.min())
                end_ts = int(open_time.max())
                summary.update({
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "start_date": _format_ts(start_ts),
                    "end_date": _format_ts(end_ts),
                    "date_range": f"{_format_ts(start_ts)} → {_format_ts(end_ts)}",
                })
    except Exception as exc:
        summary["error"] = str(exc)
    return summary


def _dataset_warnings(summary_1m: Dict[str, Any], has_required: bool) -> List[str]:
    warnings = []
    if not has_required:
        warnings.append("Thiếu 1m hoặc 4h nên chưa đủ điều kiện chạy Studio canonical.")
    candles_1m = int(summary_1m.get("candles") or 0)
    if candles_1m and candles_1m < LOW_COVERAGE_1M_CANDLES:
        warnings.append("Dữ liệu 1m ít hơn 3 ngày, kết quả chỉ nên xem như smoke test.")
    return warnings


def _format_ts(ts: Optional[int]) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%Y-%m-%d")


def _format_dt(ts: Optional[int]) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _metrics_payload(positions: List[PositionModel], initial_capital: float) -> Dict[str, Any]:
    base = MetricsCalculator.calculate(positions, initial_capital)
    total_trades = int(base.get("total_trades", 0) or 0)
    winning_trades = sum(1 for position in positions if float(position.profit_pct or 0.0) > 0)
    losing_trades = total_trades - winning_trades
    total_pnl_pct = float(base.get("total_pnl_pct", 0.0) or 0.0)
    estimated_pnl_usd = round(initial_capital * total_pnl_pct / 100, 2)

    return {
        "initial_capital": initial_capital,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "winrate": float(base.get("winrate", 0.0) or 0.0),
        "win_rate": float(base.get("winrate", 0.0) or 0.0),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "return_pct": round(total_pnl_pct, 4),
        "return_mode": "closed_trade_cumulative_pct",
        "estimated_pnl_usd": estimated_pnl_usd,
        "max_drawdown": float(base.get("max_drawdown", 0.0) or 0.0),
        "max_drawdown_pct": float(base.get("max_drawdown", 0.0) or 0.0),
        "profit_factor": float(base.get("profit_factor", 0.0) or 0.0),
        "gross_profit": float(base.get("gross_profit", 0.0) or 0.0),
        "gross_loss": float(base.get("gross_loss", 0.0) or 0.0),
        "unsupported_metrics": ["sharpe_ratio", "sortino_ratio", "tick_equity_curve"],
    }


def _serialize_positions(
    positions: List[PositionModel],
    limit: int,
    initial_capital: float,
) -> List[Dict[str, Any]]:
    sorted_positions = sorted(positions, key=lambda item: item.close_time or item.enter_time or 0)
    rows = []
    for index, position in enumerate(sorted_positions[:limit], start=1):
        pnl_pct = round(float(position.profit_pct or 0.0), 4)
        rows.append({
            "trade_id": position.result_id or index,
            "index": index,
            "flow": position.flow,
            "symbol": position.symbol,
            "pos_type": _enum_name(position.pos_type),
            "entry_time": position.enter_time,
            "entry_date": _format_dt(position.enter_time),
            "entry_price": round(float(position.enter_price or 0.0), 8),
            "close_time": position.close_time,
            "close_date": _format_dt(position.close_time),
            "close_price": round(float(position.close_price or 0.0), 8) if position.close_price is not None else None,
            "status": _enum_name(position.status),
            "pnl_pct": pnl_pct,
            "pnl_usd": round(initial_capital * pnl_pct / 100, 2),
            "estimated_pnl_usd": round(initial_capital * pnl_pct / 100, 2),
            "reason": position.close_reason or position.start_reason,
            "max_price": round(float(position.max_price or 0.0), 8),
            "min_price": round(float(position.min_price or 0.0), 8),
        })
    return rows


def _serialize_orders(orders: List[OrderModel]) -> List[Dict[str, Any]]:
    return [
        {
            "order_id": order.order_id,
            "position_id": order.position_id,
            "order_time": order.order_time,
            "order_date": _format_dt(order.order_time),
            "order_type": _enum_name(order.order_type),
            "order_price": round(float(order.order_price or 0.0), 8),
            "qty": float(order.qty or 0.0),
            "phase": int(order.phase or 0),
        }
        for order in orders
    ]


def _closed_trade_curve(positions: List[PositionModel], initial_capital: float) -> List[Dict[str, Any]]:
    curve = [{
        "time": None,
        "date": "Start",
        "equity": round(initial_capital, 2),
        "cumulative_pnl_pct": 0.0,
        "drawdown_pct": 0.0,
    }]
    cumulative_pct = 0.0
    peak_equity = initial_capital
    for position in sorted(positions, key=lambda item: item.close_time or item.enter_time or 0):
        cumulative_pct += float(position.profit_pct or 0.0)
        equity = initial_capital * (1 + cumulative_pct / 100)
        peak_equity = max(peak_equity, equity)
        drawdown_pct = 0.0 if peak_equity <= 0 else max(0.0, (peak_equity - equity) * 100 / peak_equity)
        curve.append({
            "time": position.close_time or position.enter_time,
            "date": _format_dt(position.close_time or position.enter_time),
            "equity": round(equity, 2),
            "cumulative_pnl_pct": round(cumulative_pct, 4),
            "drawdown_pct": round(drawdown_pct, 4),
            "flow": position.flow,
            "pnl_pct": round(float(position.profit_pct or 0.0), 4),
        })
    return curve


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    return str(name if name is not None else value)


# ─── Pipeline Handoff, WFA & Monte Carlo Endpoints ────────────────────────────

@router.get("/source/{handle}")
def get_pipeline_source(handle: str) -> Dict[str, Any]:
    source = get_backtest_source(handle)
    if not source:
        raise HTTPException(status_code=404, detail="Không tìm thấy backtest source tương ứng.")
    return source


@router.post("/wfa/run")
def run_wfa_endpoint(req: WfaRunRequest) -> Dict[str, Any]:
    snapshot: Optional[StrategySnapshot] = None
    if req.strategy_snapshot:
        snapshot = req.strategy_snapshot
    elif req.source_handle:
        src = get_backtest_source(req.source_handle)
        if src and "strategy_snapshot" in src:
            snapshot = StrategySnapshot(**src["strategy_snapshot"])

    if not snapshot:
        raise HTTPException(
            status_code=400,
            detail=f"Không tìm thấy Strategy Snapshot cho source_handle='{req.source_handle}'. WFA yêu cầu snapshot hợp lệ, không fallback.",
        )

    if req.symbol:
        snapshot.symbol = req.symbol.upper()
    if req.start_ts is not None:
        snapshot.start_ts = req.start_ts
    if req.end_ts is not None:
        snapshot.end_ts = req.end_ts

    cfg = req.config or WfaFoldConfig()
    source_h = req.source_handle or generate_handle("wfa_src")

    # Validate param_grid size BEFORE submitting background task
    if snapshot.param_grid:
        import itertools
        keys = list(snapshot.param_grid.keys())
        combos = list(itertools.product(*[snapshot.param_grid[k] for k in keys]))
        if len(combos) > 50:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"param_grid quá lớn: {len(combos)} tổ hợp (tối đa 50). "
                    "Hãy giảm số lượng tham số hoặc thu hẹp khoảng giá trị."
                ),
            )

    job_id = create_wfa_job(snapshot.symbol, snapshot.name, cfg.fold_count, source_handle=source_h)

    submit_background_task(execute_wfa_pipeline, job_id, snapshot, cfg, source_h)

    return {
        "job_id": job_id,
        "status": "pending",
        "symbol": snapshot.symbol,
        "strategy_name": snapshot.name,
        "total_folds": cfg.fold_count,
        "message": "WFA job đã được tiếp nhận và bắt đầu thực thi trên background worker.",
    }


@router.get("/wfa/{job_id}/progress")
def get_wfa_progress(job_id: str) -> Dict[str, Any]:
    job = get_wfa_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy WFA job này.")
    return job


@router.get("/wfa/{job_id}/result")
def get_wfa_result(job_id: str) -> Dict[str, Any]:
    job = get_wfa_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy WFA job này.")
    if job.get("status") == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "WFA job thất bại."))
    if job.get("status") != "completed" or not job.get("result"):
        return {
            "status": job.get("status"),
            "progress_pct": job.get("progress_pct", 0.0),
            "current_fold": job.get("current_fold", 0),
            "total_folds": job.get("total_folds", 0),
            "message": job.get("message"),
        }
    return job["result"]


@router.post("/monte-carlo/run")
def run_monte_carlo_endpoint(req: MonteCarloRunRequest) -> Dict[str, Any]:
    trades: List[Dict[str, Any]] = []
    strategy_name = req.strategy_name or "Strategy"
    symbol = req.symbol.upper() if req.symbol else ""

    if req.trades and len(req.trades) > 0:
        trades = req.trades
    elif req.source_wfa_id:
        w_job = get_wfa_job(req.source_wfa_id)
        if w_job and w_job.get("result"):
            trades = w_job["result"].get("aggregate_oos_trades", [])
            strategy_name = w_job["result"].get("strategy_name", strategy_name)
            symbol = w_job["result"].get("symbol", symbol)
    elif req.source_handle:
        b_src = get_backtest_source(req.source_handle)
        if b_src and "trades" in b_src:
            trades = b_src["trades"]
            symbol = b_src.get("symbol", symbol)
            if "strategy_snapshot" in b_src:
                strategy_name = b_src["strategy_snapshot"].get("name", strategy_name)

    if not trades and req.source_handle and req.source_handle.startswith("run_"):
        try:
            r_id = int(req.source_handle.replace("run_", ""))
            from backend.stats import queries as sq
            run_trades_res = sq.trades(r_id, page=1, size=200)
            if run_trades_res and run_trades_res.get("rows"):
                trades = [
                    {
                        "pnl_usd": float(r.get("pnl") or 0.0),
                        "profit_pct": float(r.get("profit_pct") or 0.0),
                        "entry_time": int(r.get("enter_time") or 0),
                        "close_time": int(r.get("exit_time") or 0),
                    }
                    for r in run_trades_res["rows"]
                ]
        except Exception as ex:
            print(f"Failed to fetch trades for {req.source_handle}: {ex}")

    if not trades:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy danh sách lệnh (trades) nào để chạy Monte Carlo. Hãy chạy Backtest hoặc WFA trước.",
        )

    if len(trades) < 30:
        raise HTTPException(
            status_code=400,
            detail=f"Số lượng lệnh ({len(trades)}) < 30. Monte Carlo yêu cầu tối thiểu 30 lệnh để đảm bảo ý nghĩa thống kê.",
        )

    source_wfa = req.source_wfa_id or req.source_handle or ""
    job_id = create_mc_job(symbol, strategy_name, req.simulations, source_wfa_id=source_wfa)
    submit_background_task(execute_monte_carlo_pipeline, job_id, req, trades)

    return {
        "job_id": job_id,
        "status": "pending",
        "symbol": symbol,
        "strategy_name": strategy_name,
        "simulations": req.simulations,
        "trades_count": len(trades),
        "message": "Monte Carlo job đã được tiếp nhận và bắt đầu thực thi.",
    }


@router.get("/monte-carlo/{job_id}/result")
def get_monte_carlo_result(job_id: str) -> Dict[str, Any]:
    job = get_mc_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy Monte Carlo job này.")
    if job.get("status") == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "Monte Carlo job thất bại."))
    if job.get("status") != "completed" or not job.get("result"):
        return {
            "status": job.get("status"),
            "progress_pct": job.get("progress_pct", 0.0),
            "message": job.get("message"),
        }
    return job["result"]


@router.get("/wfa/history")
def get_wfa_history_endpoint(limit: int = 30) -> Dict[str, Any]:
    """Lấy danh sách lịch sử các lần chạy WFA."""
    return {"history": list_wfa_history(limit=limit)}


@router.get("/monte-carlo/history")
def get_monte_carlo_history_endpoint(limit: int = 30) -> Dict[str, Any]:
    """Lấy danh sách lịch sử các lần mô phỏng Monte Carlo."""
    return {"history": list_mc_history(limit=limit)}


@router.get("/backtest/history")
def get_backtest_history_endpoint(limit: int = 30) -> Dict[str, Any]:
    """Lấy danh sách lịch sử các nguồn Backtest đã chạy trong Studio."""
    return {"history": list_backtest_history(limit=limit)}


