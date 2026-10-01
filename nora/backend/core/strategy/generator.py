"""Trình tạo (Generator) các công thức Chiến lược Alpha thông dụng.

Sinh ra các bộ tham số JSON/AST hoàn chỉnh (như Keltner)
để truyền thẳng vào Backtest Engine.
"""
from typing import Any, Dict

from .builder import ASTBuilder, AlphaStrategyBuilder


def generate_keltner_flow(
    pos_type: str = "LONG",
    keltner_period: int = 17,
    keltner_multiplier: float = 0.5,
    margin: float = 1.0,
    baseprofit: float = 2000000.0,
    step_profit: float = 2.0,
    back_profit: float = 18.0
) -> Dict[str, Any]:
    """Tạo ra một cấu trúc AST cho chiến lược Keltner cơ bản.
    
    LONG: 
      Match: 1m high > 4h kup AND 4h atr > 0 AND ...
      Stop: 1m low < 4h klo
    SHORT:
      Match: 1m low < 4h klo AND 4h atr > 0 AND ...
      Stop: 1m high > 4h kup
    """
    ast = ASTBuilder()
    builder = AlphaStrategyBuilder(pos_type=pos_type)
    
    # Định dạng tên cột chỉ báo
    klo_col = f"klo{keltner_period}_{str(keltner_multiplier).replace('.', '')}"
    kup_col = f"kup{keltner_period}_{str(keltner_multiplier).replace('.', '')}"
    
    if pos_type == "LONG":
        # Điều kiện MUA: 1m high > 4h kup
        cond_match = [
            ast.compare(ast.field("1m", "high"), ">", ast.field("4h", kup_col)),
            ast.compare(ast.field("4h", "atr"), ">", 0),
        ]
        # Điều kiện CẮT LỖ: 1m low < 4h klo
        cond_stop = [
            ast.compare(ast.field("1m", "low"), "<", ast.field("4h", klo_col))
        ]
    else:
        # Điều kiện BÁN (SHORT): 1m low < 4h klo
        cond_match = [
            ast.compare(ast.field("1m", "low"), "<", ast.field("4h", klo_col)),
            ast.compare(ast.field("4h", "atr"), ">", 0),
        ]
        # Điều kiện CẮT LỖ: 1m high > 4h kup
        cond_stop = [
            ast.compare(ast.field("1m", "high"), ">", ast.field("4h", kup_col))
        ]
        
    builder.add_match_or_condition(ast.and_group(*cond_match))
    builder.add_stop_or_condition(ast.and_group(*cond_stop))
    
    builder.set_config(
        margin=margin,
        baseprofit=baseprofit,
        step_profit=step_profit,
        back_profit=back_profit,
        enter_price="market"
    )
    
    return builder.build()


def generate_full_keltner_strategy(
    keltner_period: int = 17,
    keltner_multiplier: float = 0.5,
) -> Dict[str, Any]:
    """Sinh toàn bộ chiến lược Keltner bao gồm cả 2 luồng LONG và SHORT."""
    return {
        "LONG-4h": generate_keltner_flow("LONG", keltner_period, keltner_multiplier),
        "SHORT-4h": generate_keltner_flow("SHORT", keltner_period, keltner_multiplier),
    }
