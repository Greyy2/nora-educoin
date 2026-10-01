"""Động cơ Đa luồng Thực thi Tối ưu hoá (Parallel Optimization Runner).

Quản lý việc phân bổ hàng nghìn bộ Backtest lên các nhân CPU bằng ProcessPoolExecutor.
"""
import concurrent.futures
import time
from typing import Callable, Dict, List, Any

from backend.backtest.engine import BacktestEngine
from backend.core.params import StrategyParams
from backend.backtest.metrics import MetricsCalculator

def _run_single_backtest(
    worker_id: int,
    account_id: int,
    campaign_id: int,
    symbol: str,
    start_ts: int,
    end_ts: int,
    params: StrategyParams,
    ast_generator_func: Callable
) -> Dict[str, Any]:
    """Hàm độc lập (top-level) để chạy bên trong Process (worker).
    
    Yêu cầu: ast_generator_func là hàm (vd: generate_full_keltner_strategy) nhận vào các
    giá trị từ params.extra và trả về một bộ từ điển (dict) chứa các luồng cấu hình (Flows) và AST.
    """
    try:
        start_time = time.time()
        # 1. Sinh AST cho bộ thông số hiện tại
        # Trích xuất các tham số (ví dụ length, multiplier) để truyền vào generator
        length = params.extra.get("length", 17)
        multiplier = params.extra.get("multiplier", 0.5)
        
        ast_config = ast_generator_func(length, multiplier)
        
        # 2. Khởi tạo Engine
        engine = BacktestEngine(account_id, campaign_id, symbol, start_ts, end_ts)
        engine.load_data()
        
        # 3. Đăng ký các luồng vào Engine
        for flow_name, flow_data in ast_config.items():
            # Clone Params và nhúng AST vào
            flow_params = StrategyParams(
                using_match_price=params.using_match_price,
                take_profit_rate=params.take_profit_rate,
                stop_loss_rate=params.stop_loss_rate,
                extra={"ast": flow_data}
            )
            engine.add_strategy_flow(flow_name, flow_params)
            
        # 4. Chạy mô phỏng
        engine.run()
        
        # 5. Tính toán Metrics
        metrics = MetricsCalculator.calculate_all(engine.closed_positions, initial_balance=10000.0)
        
        run_time = time.time() - start_time
        return {
            "params": params,
            "metrics": metrics,
            "run_time_sec": run_time,
            "trades": len(engine.closed_positions),
            "status": "success",
            "error": None
        }
    except Exception as e:
        return {
            "params": params,
            "metrics": None,
            "run_time_sec": 0,
            "trades": 0,
            "status": "error",
            "error": str(e)
        }


class OptimizeRunner:
    """Điều phối chạy Tối ưu hoá đa luồng."""

    def __init__(self, max_workers: int = None):
        """Khởi tạo với số lượng worker tuỳ chọn (mặc định = số CPU core)."""
        self.max_workers = max_workers
        
    def run_optimization(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        start_ts: int,
        end_ts: int,
        params_list: List[StrategyParams],
        ast_generator_func: Callable
    ) -> List[Dict[str, Any]]:
        """Thực thi song song toàn bộ tổ hợp tham số."""
        
        results = []
        total_tasks = len(params_list)
        print(f"🚀 Bắt đầu Tối ưu hoá (Optimization) cho {total_tasks} tổ hợp tham số...")
        print(f"⚙️ Sử dụng {self.max_workers or 'Tất cả'} CPU Cores.")
        
        start_time = time.time()
        
        # Dùng ProcessPoolExecutor với context 'spawn' để tránh deadlock từ PyMongo/Sockets
        import multiprocessing
        context = multiprocessing.get_context("spawn")
        # worker_init: oom_score_adj cao để khi OOM kernel giết worker chứ không giết API
        from backend.utils.memwatch import worker_init
        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers, mp_context=context,
                                                    initializer=worker_init) as executor:
            # Chuẩn bị danh sách args
            futures = []
            for i, p in enumerate(params_list):
                future = executor.submit(
                    _run_single_backtest,
                    worker_id=i,
                    account_id=account_id,
                    campaign_id=campaign_id,
                    symbol=symbol,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    params=p,
                    ast_generator_func=ast_generator_func
                )
                futures.append(future)
                
            # Thu thập kết quả khi hoàn thành
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                results.append(res)
                completed += 1
                if completed % max(1, total_tasks // 10) == 0 or completed == total_tasks:
                    print(f"⏳ Đã chạy {completed}/{total_tasks} tổ hợp ({(completed/total_tasks)*100:.1f}%)", flush=True)
                    
        total_time = time.time() - start_time
        print(f"✅ Hoàn thành Optimization {total_tasks} tổ hợp trong {total_time:.2f} giây.")
        
        return results
