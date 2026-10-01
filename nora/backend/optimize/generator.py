"""Bộ sinh Tổ hợp Tham số (Parameter Combinations Generator).

Sinh ra hàng ngàn bộ thông số khác nhau từ cấu hình tĩnh hoặc cấu hình động.
Ví dụ: Grid Search (Cartesian Product) cho Keltner (length: [10, 20], multiplier: [1.0, 1.5])
"""
import itertools
from typing import Any, Dict, List
from backend.core.strategy.params import StrategyParams

class ParamGenerator:
    """Sinh mảng cấu hình tham số để chạy Optimizer."""

    @staticmethod
    def generate_grid(base_params: Dict[str, Any], ranges: Dict[str, List[Any]]) -> List[StrategyParams]:
        """Tạo lưới tổ hợp (Cartesian Product) từ các cấu hình phạm vi.
        
        Args:
            base_params: Cấu hình mặc định (VD: take_profit_rate, stop_loss_rate...)
            ranges: Cấu hình dạng danh sách các giá trị có thể (VD: {"multiplier": [1.0, 2.0]})
            
        Returns:
            Danh sách các đối tượng StrategyParams để nạp vào Engine.
        """
        # Trích xuất tên tham số và danh sách giá trị tương ứng
        keys = list(ranges.keys())
        values_lists = list(ranges.values())
        
        # Sinh tổ hợp tích Đề-các
        combinations = list(itertools.product(*values_lists))
        
        results = []
        for combo in combinations:
            # Sao chép base_params để không bị ghi đè
            current_kwargs = base_params.copy()
            current_extra = current_kwargs.get("extra", {}).copy()
            
            # Đổ dữ liệu từ tổ hợp vào kwargs hoặc extra
            for i, key in enumerate(keys):
                val = combo[i]
                # Nếu key tồn tại trực tiếp trên lớp StrategyParams (ví dụ stop_loss_rate)
                if key in current_kwargs:
                    current_kwargs[key] = val
                else:
                    # Nếu key là tham số tuỳ chỉnh, đẩy vào extra (keltner_length, keltner_multiplier...)
                    current_extra[key] = val
                    
            current_kwargs["extra"] = current_extra
            results.append(StrategyParams(**current_kwargs))
            
        return results
