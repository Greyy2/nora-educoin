"""Kiến trúc Module Tín hiệu (backend.analys.signal):
- signal.py: Cây biểu thức DSL (nodes/IR), AST evaluator, SignalProvider, LiveSignals, ArraySignals, TradingView TA mappings & Constants
- compute.py: SignalEngine, tính tín hiệu trên nến (evaluate_signals, matrix_evaluator)
"""
import sys
from . import signal as nodes, signal, compute

sys.modules.setdefault("backend.analys.signal.nodes", signal)
sys.modules.setdefault("backend.signal.nodes", signal)

from .signal import (
    ArraySignals,
    LiveSignals,
    SignalProvider,
    _COLS,
    MINUTE_MS,
    DslError,
    Node,
    Program,
    lag_key,
    DSL_VERSION,
    Bin,
    BoolConst,
    Call,
    Cmp,
    Const,
    Data,
    Inv,
    Logic,
    Neg,
    Pick,
    TupleVal,
    code_hash,
    GLOBAL_TA_FUNCS,
    OHLCV_COLUMNS,
    RISK_PARAM_MAP,
)
from .compute import (
    evaluate_signals,
    signal_snapshot,
    check_signals,
    matrix_evaluator,
    entry_event_mask,
    data_cache_clear,
    slot_pairs,
    SignalEngine,
    SignalPortfolio,
    FRESH,
)


__all__ = [
    # signal.py
    "SignalProvider",
    "ArraySignals",
    "LiveSignals",
    "_COLS",
    "MINUTE_MS",
    "DslError",
    "Node",
    "Program",
    "lag_key",
    # compute.py
    "evaluate_signals",
    "signal_snapshot",
    "check_signals",
    "matrix_evaluator",
    "entry_event_mask",
    "data_cache_clear",
    "slot_pairs",
    "SignalEngine",
    "SignalPortfolio",
    "FRESH",
    # note.py
    "GLOBAL_TA_FUNCS",
    "OHLCV_COLUMNS",
    "RISK_PARAM_MAP",
]
