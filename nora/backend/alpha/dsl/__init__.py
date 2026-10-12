"""Nora Alpha Domain-Specific Language (AST, Indicators, Signal Trees)."""
from backend.alpha.dsl import indicator, signal, strategy
from backend.alpha.dsl.signal import (
    Program, Node, VectorEvaluator, DslError, code_hash, classify, smooth
)
from backend.alpha.dsl.indicator import (
    FEATURES, OPS, REQUIRED, REGISTRY, Spec, register_program
)
from backend.alpha.dsl.strategy import (
    build_plan, Plan, evaluate_signals, signal_snapshot, check_signals
)

__all__ = [
    "indicator", "signal", "strategy",
    "Program", "Node", "VectorEvaluator", "DslError", "code_hash", "classify", "smooth",
    "FEATURES", "OPS", "REQUIRED", "REGISTRY", "Spec", "register_program",
    "build_plan", "Plan", "evaluate_signals", "signal_snapshot", "check_signals",
]
