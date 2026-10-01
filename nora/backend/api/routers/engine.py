"""Các Endpoints API cho Hệ thống Nora 2.0 (New Engine)."""
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.api.schemas import BacktestRequest, BacktestResponse, MetricsResponse, PositionResponse, OptimizeRequest
from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import MetricsCalculator
from backend.core.params import StrategyParams
from backend.alpha import generate_full_keltner_strategy
from backend.optimize.generator import ParamGenerator
from backend.optimize.runner import OptimizeRunner
from backend.optimize.ranker import ResultsRanker
from backend.db.models import PositionType, PositionStatus

router = APIRouter(prefix="/api/v2", tags=["Nora 2.0 Core"])

@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    """Kích hoạt Backtest 1 lần duy nhất (Single Run) và trả về biểu đồ + metrics."""
    try:
        start_time = time.time()
        
        # 1. Khởi tạo Engine & Load Data (RAM Cache)
        engine = BacktestEngine(req.account_id, req.campaign_id, req.symbol, req.start_ts, req.end_ts)
        engine.load_data()
        
        # 2. Sinh AST
        if req.strategy_name.lower() == "keltner":
            length = req.extra_params.get("length", 17)
            multiplier = req.extra_params.get("multiplier", 0.5)
            ast_config = generate_full_keltner_strategy(length, multiplier)
        else:
            raise HTTPException(status_code=400, detail="Chiến lược chưa được hỗ trợ.")
            
        # 3. Nạp Flow vào Engine
        for flow_name, flow_data in ast_config.items():
            flow_params = StrategyParams(
                using_match_price=req.using_match_price,
                take_profit_rate=req.take_profit_rate,
                stop_loss_rate=req.stop_loss_rate,
                extra={"ast": flow_data}
            )
            engine.add_strategy_flow(flow_name, flow_params)
            
        # 4. Chạy mô phỏng
        engine.run()
        results = engine.get_results()
        
        # 5. Tính toán kết quả
        metrics = MetricsCalculator.calculate(results["positions"], initial_balance=10000.0)
        
        # Đóng gói Response
        trades_response = []
        for pos in results["positions"]:
            # Map enum
            pos_type = "LONG" if pos.pos_type == PositionType.LONG else "SHORT"
            reason = "Stop Condition" if pos.status == PositionStatus.SL else ("Take Profit" if pos.status == PositionStatus.TP else "End of Backtest")
            
            pnl_pct = pos.profit_pct
            if pos.pos_type == PositionType.SHORT and hasattr(pos, 'enter_price') and hasattr(pos, 'close_price') and pos.enter_price:
                # profit_pct should already be calculated in Model or results, but let's just use it
                pass
                
            trades_response.append(
                PositionResponse(
                    symbol=pos.symbol,
                    type=f"{pos_type}-{pos.phase}h",
                    enter_time=pos.enter_time,
                    enter_price=pos.enter_price,
                    close_time=pos.close_time,
                    close_price=pos.close_price,
                    pnl_pct=pnl_pct,
                    reason=reason
                )
            )
            
        return BacktestResponse(
            metrics=MetricsResponse(
                total_trades=metrics.get("total_trades", 0),
                winrate=metrics.get("winrate", 0.0),
                total_pnl_pct=metrics.get("total_pnl_pct", 0.0),
                max_drawdown_pct=metrics.get("max_drawdown_pct", 0.0),
                sharpe_ratio=metrics.get("sharpe_ratio", 0.0)
            ),
            trades=trades_response,
            run_time_sec=time.time() - start_time
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/run")
def run_optimize(req: OptimizeRequest):
    """Kích hoạt Optimize (Quét Lưới Đa Luồng). Hàm đồng bộ (def) để FastAPI chạy trong threadpool, không chặn event loop."""
    try:
        # 1. Sinh tổ hợp Grid
        base_params = req.base_params.copy()
        if "extra" not in base_params:
            base_params["extra"] = {}
            
        params_list = ParamGenerator.generate_grid(base_params, req.ranges)
        if len(params_list) > 200:
            raise HTTPException(status_code=400, detail="Vượt quá giới hạn 200 tổ hợp.")
            
        # 2. Khởi chạy
        # Số worker theo RAM/CPU còn trống (trong cgroup 3G của API tự ra ít worker), tối đa 4
        from backend.utils.parallel import auto_workers
        runner = OptimizeRunner(max_workers=auto_workers(900, max_workers=4))
        results = runner.run_optimization(
            account_id=req.account_id,
            campaign_id=req.campaign_id,
            symbol=req.symbol,
            start_ts=req.start_ts,
            end_ts=req.end_ts,
            params_list=params_list,
            ast_generator_func=generate_full_keltner_strategy
        )
        
        # 3. Lọc và xếp hạng
        ranked_results = ResultsRanker.rank_results(
            results,
            sort_by=req.sort_by,
            min_trades=req.min_trades,
            max_drawdown=req.max_drawdown,
            min_winrate=req.min_winrate
        )
        
        # Chuẩn hoá kết quả cho JSON (xoá bỏ StrategyParams object)
        clean_results = []
        for r in ranked_results[:10]: # Trả về top 10
            clean_results.append({
                "params": r["params"].extra,
                "metrics": r["metrics"],
                "trades": r["trades"],
                "run_time_sec": r["run_time_sec"]
            })
            
        return {
            "total_combinations": len(params_list),
            "valid_results": len(ranked_results),
            "top_10": clean_results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
