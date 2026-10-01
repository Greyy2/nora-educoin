"""API Router cho Alpha Studio AST Builder & canonical simulation."""
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.strategy.features_meta import FEATURES_CATALOG, OPERATORS_CATALOG
from backend.core.strategy.templates import STRATEGY_SAMPLES
from backend.core.strategy.validator import ASTValidationError, ASTValidator
from backend.core.backtest.engine import BacktestEngine
from backend.core.backtest.metrics import MetricsCalculator
from backend.core.strategy.params import StrategyParams
from backend.db.local_pkl import default_data_root, has_frame
from backend.db.models import OrderModel, PositionModel
from backend.core.contracts import (
    StrategySnapshot,
    BacktestResultContract,
    WfaFoldConfig,
    WfaRunRequest,
    MonteCarloRunRequest,
)
from backend.api.jobs.store import (
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
from backend.wfa.walk_forward import execute_wfa_pipeline
from backend.carlo.monte_carlo import execute_monte_carlo_pipeline

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
    stop_loss_rate: float = Field(0.0, ge=0.0, le=100.0, description="% từ giá trung bình")
    take_profit_rate: float = Field(0.0, ge=0.0, le=1000.0, description="% từ giá trung bình")
    timeout: int = Field(0, ge=0, le=525600, description="Phút giữ lệnh tối đa (0 = không giới hạn)")
    trailing_stop: float = Field(0.0, ge=0.0, le=100.0, description="% từ đỉnh/đáy có lợi nhất")
    trailing_activation_pct: float = Field(0.0, ge=0.0, le=100.0)
    market: str = Field("spot", pattern="^(spot|perp)$", description="spot: không đòn bẩy/không short; perp: đòn bẩy + thanh lý")
    order_size_pct: float = Field(100.0, gt=0.0, le=100.0, description="Ký quỹ lệnh đầu, % vốn")
    dca_step_pct: float = Field(0.0, ge=0.0, le=50.0)
    dca_max_layers: int = Field(0, ge=0, le=50)
    dca_size_multiplier: float = Field(1.0, gt=0.0, le=5.0)
    maintenance_margin_rate: float = Field(0.005, ge=0.0, le=0.2)
    fee_rate: Optional[float] = Field(None, ge=0.0, le=0.05, description="Phí taker; mặc định theo venue/market")
    maker_fee_rate: Optional[float] = Field(None, ge=0.0, le=0.05, description="Phí maker (lệnh limit); mặc định theo venue/market")
    stop_fill: str = Field("level", pattern="^(level|extreme)$", description="Khớp SL/trailing: 'level' (đúng mức) | 'extreme' (giá xấu nhất của nến — bi quan)")
    cooldown: int = Field(0, ge=0, le=525600, description="Phút chờ sau khi đóng vị thế mới được vào lại (0 = không chờ)")
    exit_unit: str = Field("pct", pattern="^(pct|atr)$", description="SL/TP/trailing/bước DCA: % | bội số ATR% lúc vào lệnh")
    atr_frame: str = Field("1h", pattern="^(1m|5m|15m|1h|4h|24h)$")
    atr_period: int = Field(14, ge=2, le=200)
    sizing: str = Field("margin_pct", pattern="^(margin_pct|risk)$", description="Khối lượng: % vốn làm ký quỹ | theo rủi ro tại SL")
    risk_per_trade_pct: float = Field(0.5, gt=0.0, le=5.0, description="sizing=risk: % vốn mất nếu chạm SL")
    max_notional_pct: float = Field(100.0, gt=0.0, le=1000.0, description="sizing=risk: trần danh nghĩa một vị thế, % vốn")
    signal_params: Dict[str, float] = Field(default_factory=dict, description="Giá trị cho node {'param': ...} trong AST")
    slippage_rate: Optional[float] = Field(None, ge=0.0, le=0.05, description="Mặc định theo venue/market")
    result_trade_limit: int = Field(300, ge=1, le=2000)


class ScriptSimulateRequest(BaseModel):
    code: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="Bắt buộc, không mặc định")
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
    from backend.core.strategy.strategy_library import SIGNALS
    return {"samples": STRATEGY_SAMPLES, "signals": SIGNALS, "mode": "ast_builder"}


@router.get("/features")
def get_features() -> Dict[str, Any]:
    from backend.core.signals.kernels import catalog as kernel_catalog
    return {
        "features": FEATURES_CATALOG,
        "kernels": kernel_catalog(),
        "kernel_column_format": "<kernel>_<tham số>[_<tham số>] — vd rsi_14, ema_50, bbl_20_2, dch_20; index = số nến trước",
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

    from backend.db.data_layout import list_assets
    from backend.db.local_pkl import read_manifest
    if os.path.isdir(data_root):
        for item in list_assets(data_root):
            asset = item["qualified"]
            asset_dir = item["path"]
            manifest = read_manifest(asset, data_root=data_root) or {}
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
                "venue": item["venue"],
                "exchange": manifest.get("exchange"),
                "network": manifest.get("network"),
                "source": manifest.get("source"),
                "coverage_days": manifest.get("coverage_days"),
                "filled_ratio_1m": manifest.get("filled_ratio_1m"),
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
    from backend.core.strategy.params_template import resolve_placeholders
    try:  # ngưỡng tín hiệu dạng {"param": ...} -> số
        enabled_flows = resolve_placeholders(_enabled_flows(req.flows), req.signal_params or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not enabled_flows:
        raise HTTPException(status_code=400, detail="Không có flow nào đang bật để mô phỏng.")

    try:
        ASTValidator.validate_flows_or_raise(enabled_flows)
    except ASTValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from backend.db.data_layout import AmbiguousSymbolError
    from backend.core.backtest.params_builder import data_symbol
    data_sym, price_source = data_symbol(clean_symbol, req.market)  # perp -> BTC@perp (giá perp + funding)
    try:
        missing_frames = [
            frame for frame in REQUIRED_FRAMES
            if not has_frame(data_sym, frame, data_root=default_data_root())
        ]
    except AmbiguousSymbolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if missing_frames:
        raise HTTPException(
            status_code=404,
            detail=f"{clean_symbol} thiếu dữ liệu bắt buộc cho Studio: {', '.join(missing_frames)}. Studio không tự crawl khi thiếu data.",
        )

    from backend.core.data.quality_gate import evaluate_data_quality, DataQualityStatus
    dq = evaluate_data_quality(data_sym, timeframe="1m", data_root=default_data_root())
    if dq["status"] in (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA):
        raise HTTPException(
            status_code=422,
            detail={"message": "Dữ liệu không đạt quality gate", "issues": dq["issues"]}
        )

    initial_capital = float(req.capital if req.capital is not None else req.initial_capital)

    from backend.core.backtest.params_builder import POSITION_KEYS, build_params, venue_of_symbol
    position = {key: getattr(req, key) for key in POSITION_KEYS}
    try:
        venue = venue_of_symbol(clean_symbol)
        engine = BacktestEngine(
            account_id=0,
            campaign_id=0,
            symbol=data_sym,
            start_ts=int(req.start_ts),
            end_ts=int(req.end_ts),
            initial_capital=initial_capital,
        )
        for index, flow in enumerate(enabled_flows):
            flow_ast = _flow_ast(flow)
            flow_type = str(flow_ast.get("type", "LONG")).upper()
            flow_name = str(flow.get("name") or flow.get("id") or f"{flow_type}_{index + 1}")
            if flow_type not in flow_name.upper():
                flow_name = f"{flow_type}_{flow_name}"
            engine.add_strategy_flow(flow_name, build_params(flow_name, flow_ast, flow_type, position, venue, clean_symbol))

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
    mtm_curve = raw_results.get("equity_curve", [])
    metrics = _metrics_payload(positions, initial_capital, mtm_curve)
    metrics.update({"venue": venue, "market": req.market, "data_symbol": data_sym, "price_source": price_source,
                    "funding_events": raw_results.get("funding_events", 0),
                    "rejected_for_capital": raw_results.get("rejected_for_capital", 0),
                    "fee_rate": engine.trackers[0].fee_rate if engine.trackers else None,
                    "slippage_rate": engine.trackers[0].slippage_rate if engine.trackers else None,
                    "funding_modeled": bool(raw_results.get("funding_modeled"))})
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
        **{k: getattr(req, k) for k in ("trailing_stop", "trailing_activation_pct", "market", "order_size_pct",
                                        "dca_step_pct", "dca_max_layers", "dca_size_multiplier",
                                        "maintenance_margin_rate", "fee_rate", "maker_fee_rate", "slippage_rate",
                                        "stop_fill", "cooldown", "exit_unit", "atr_frame", "atr_period", "sizing",
                                        "risk_per_trade_pct", "max_notional_pct", "signal_params")},
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

    from backend.core.strategy.script_engine import ScriptStrategyRunner
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


def _metrics_payload(positions: List[PositionModel], initial_capital: float,
                     mtm_curve: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Metrics từ lệnh đã đóng + đường vốn mark-to-market (MDD tính cả lỗ treo trong lệnh)."""
    base = MetricsCalculator.calculate(positions, initial_capital, equity_curve=mtm_curve or None)
    closed_only = MetricsCalculator.calculate(positions, initial_capital)
    maes = [float(getattr(p, "mae_pct", 0.0) or 0.0) for p in positions]
    layers = [int(getattr(p, "layers", 1) or 1) for p in positions]
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
        "return_mode": "equity_curve_fixed_capital" if mtm_curve else "closed_trade_cumulative_pct",
        "estimated_pnl_usd": estimated_pnl_usd,
        "max_drawdown": float(base.get("max_drawdown", 0.0) or 0.0),
        "max_drawdown_pct": float(base.get("max_drawdown", 0.0) or 0.0),
        "profit_factor": float(base.get("profit_factor", 0.0) or 0.0),
        "gross_profit": float(base.get("gross_profit", 0.0) or 0.0),
        "gross_loss": float(base.get("gross_loss", 0.0) or 0.0),
        "unsupported_metrics": ["sharpe_ratio", "sortino_ratio", "tick_equity_curve"],
        "max_drawdown_closed_trades_pct": float(closed_only.get("max_drawdown", 0.0) or 0.0),
        "drawdown_mode": "mark_to_market_worst_intrabar" if mtm_curve else "closed_trades",
        "worst_trade_mae_pct": round(min(maes), 4) if maes else 0.0,
        "avg_layers": round(sum(layers) / len(layers), 3) if layers else 0.0,
        "max_layers": max(layers) if layers else 0,
        "liquidations": sum(1 for p in positions if int(getattr(p, "status", 0)) == 5),
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
            "layers": int(getattr(position, "layers", 1) or 1),
            "avg_price": round(float(getattr(position, "avg_price", 0.0) or 0.0), 8),
            "mae_pct": round(float(getattr(position, "mae_pct", 0.0) or 0.0), 4),
            "fees_usd": round(float(getattr(position, "fees_usd", 0.0) or 0.0), 4),
            "net_pnl_usd": round(float(position.real_pnl or 0.0), 4),
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

    # param_grid validation đã được StrategySnapshot.field_validator xử lý
    # FastAPI trả 422 tự động nếu grid sai → không cần validate lại ở đây

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

    # Thứ tự ưu tiên nguồn lệnh: source_wfa_id > source_handle > trades.
    # Khi có source_wfa_id, luôn dùng aggregate_oos_trades của chính job WFA
    # (không cho client tự gửi trades kèm một WFA id đã pass để "mượn" gate).
    if req.source_wfa_id:
        w_job = get_wfa_job(req.source_wfa_id)
        if not w_job:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy WFA job '{req.source_wfa_id}'.")
        if w_job.get("status") != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"WFA job '{req.source_wfa_id}' chưa hoàn thành (status={w_job.get('status')}).",
            )
        w_res = w_job.get("result")
        if w_res is None and w_job.get("result_json"):
            import json as _json
            w_res = _json.loads(w_job["result_json"])
        w_res = w_res or {}
        trades = list(w_res.get("aggregate_oos_trades") or [])
        strategy_name = w_res.get("strategy_name", strategy_name)
        symbol = w_res.get("symbol", symbol)
    elif req.source_handle:
        if req.source_handle.startswith("run_"):
            raise HTTPException(
                status_code=400,
                detail="Run legacy (MySQL) không hỗ trợ Monte Carlo: lệnh bị phân trang và không có pnl_pct chuẩn. Hãy chạy lại chiến lược trong Studio.",
            )
        b_src = get_backtest_source(req.source_handle)
        if not b_src:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy backtest source '{req.source_handle}'.")
        trades = list(b_src.get("trades") or [])
        symbol = b_src.get("symbol", symbol)
        if "strategy_snapshot" in b_src:
            strategy_name = b_src["strategy_snapshot"].get("name", strategy_name)
    elif req.trades:
        trades = req.trades

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




# ─── Scan backtest: một chiến lược × nhiều tài sản (chạy nền) ────────────────

class ScanRequest(BaseModel):
    model_config = {"extra": "forbid"}

    strategy_id: Optional[str] = Field(None, description="id trong /samples (dùng flows + default_params của mẫu)")
    flows: Optional[List[Dict[str, Any]]] = Field(None, description="Hoặc tự gửi flows AST")
    symbols: Optional[List[str]] = Field(None, description="Mặc định: mọi tài sản phù hợp thị trường")
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    days: Optional[int] = Field(None, ge=1, le=1100, description="Chỉ lấy N ngày gần nhất của mỗi tài sản")
    initial_capital: float = Field(10000.0, ge=1.0)
    position: Dict[str, Any] = Field(default_factory=dict, description="Ghi đè tham số vị thế (POSITION_KEYS)")
    signal_params: Dict[str, float] = Field(default_factory=dict)


@router.post("/scan")
def start_scan(req: ScanRequest) -> Dict[str, Any]:
    from backend.core.backtest.params_builder import POSITION_KEYS
    from backend.db.data_layout import list_assets
    from backend.api.jobs.scan import create_scan_job, execute_scan

    name = "Custom"
    flows = req.flows
    position: Dict[str, Any] = {}
    if req.strategy_id:
        sample = next((s for s in STRATEGY_SAMPLES if s.get("id") == req.strategy_id), None)
        if sample is None:
            raise HTTPException(status_code=404, detail=f"Không có mẫu chiến lược '{req.strategy_id}'.")
        name, flows = sample["name"], sample["flows"]
        position = {k: v for k, v in sample.get("default_params", {}).items() if k in POSITION_KEYS}
    if not flows:
        raise HTTPException(status_code=400, detail="Cần strategy_id hoặc flows.")
    bad = set(req.position) - set(POSITION_KEYS)
    if bad:
        raise HTTPException(status_code=400, detail=f"Tham số vị thế không hỗ trợ: {sorted(bad)}")
    position.update(req.position)
    from backend.core.strategy.params_template import resolve_placeholders
    try:
        ASTValidator.validate_flows_or_raise(resolve_placeholders(_enabled_flows(flows), req.signal_params))
    except (ASTValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    market = str(position.get("market") or "spot")
    symbols = req.symbols or sorted({a["symbol"] for a in list_assets()
                                     if a["instrument"] == "spot" and (market == "spot" or a["venue"] == "cex")})
    job_id = create_scan_job(name, len(symbols), req.model_dump())
    submit_background_task(execute_scan, job_id, _enabled_flows(flows), symbols, position, req.signal_params,
                           req.start_ts, req.end_ts, req.days, req.initial_capital)
    return {"job_id": job_id, "status": "pending", "strategy_name": name, "symbols": symbols, "position": position}


@router.get("/scan/history")
def get_scan_history(limit: int = 30) -> Dict[str, Any]:
    from backend.api.jobs.scan import list_scan_history
    return {"history": list_scan_history(limit=limit)}


@router.get("/scan/{job_id}")
def get_scan(job_id: str) -> Dict[str, Any]:
    from backend.api.jobs.scan import get_scan_job
    job = get_scan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy scan job.")
    return job
