"""Schemas & Data Contracts cho Studio Pipeline: Backtest -> WFA -> Monte Carlo."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StrategySnapshot(BaseModel):
    strategy_id: Optional[str] = None
    name: str = Field("Untitled Strategy", description="Tên chiến lược")
    symbol: str = Field(..., description="Cặp tài sản (bắt buộc, không default)")
    start_ts: int = Field(0, description="Timestamp bắt đầu (ms)")
    end_ts: int = Field(0, description="Timestamp kết thúc (ms)")
    flows: List[Dict[str, Any]] = Field(default_factory=list, description="Danh sách flow AST")
    initial_capital: float = Field(10000.0, description="Vốn ban đầu")
    leverage: float = Field(1.0, description="Đòn bẩy")
    using_match_price: bool = Field(True)
    max_open_trades: int = Field(45)
    stop_loss_rate: float = Field(0.0)
    take_profit_rate: float = Field(0.0)
    timeout: int = Field(0)
    param_grid: Optional[Dict[str, List[Any]]] = Field(default_factory=dict, description="Grid tham số tối ưu IS")


class TradeLogEntry(BaseModel):
    trade_id: str
    pos_type: str
    entry_time: int
    entry_date: Optional[str] = None
    entry_price: float
    close_time: int
    close_date: Optional[str] = None
    close_price: float
    pnl_usd: float
    pnl_pct: float
    reason: Optional[str] = None


class BacktestResultContract(BaseModel):
    source_handle: str
    strategy_snapshot: StrategySnapshot
    symbol: str
    summary: Dict[str, Any]
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]
    generated_at: int


class WfaFoldConfig(BaseModel):
    train_days: int = Field(30, ge=1, le=365, description="Độ dài In-Sample (ngày)")
    test_days: int = Field(10, ge=1, le=180, description="Độ dài Out-of-Sample (ngày)")
    step_days: Optional[int] = Field(None, ge=1, le=180, description="Bước trượt mỗi fold (mặc định = test_days)")
    embargo_days: int = Field(0, ge=0, le=30, description="Khoảng cách embargo giữa train và test (ngày)")
    anchored: bool = Field(False, description="Anchored IS window")
    fold_count: int = Field(12, ge=1, le=50, description="Số lượng fold tối đa")
    min_folds: int = Field(4, ge=1, le=50, description="Số lượng fold tối thiểu để gate xét PASS")
    min_positive_ratio: float = Field(0.6, ge=0.0, le=1.0, description="Tỉ lệ fold OOS có lãi tối thiểu")
    min_oos_trades: int = Field(30, ge=1, description="Tổng số lệnh OOS tối thiểu")
    min_is_trades: int = Field(10, ge=1, description="Số lệnh IS tối thiểu mỗi fold để chấp nhận combo")
    min_is_profit_pct: float = Field(0.0, description="Lợi nhuận IS tối thiểu")
    max_is_mdd_pct: float = Field(15.0, description="MDD IS tối đa (%)")
    min_oos_profit_pct: float = Field(0.0, description="Lợi nhuận OOS tối thiểu (%)")
    max_oos_mdd_pct: float = Field(25.0, description="MDD OOS tối đa từng fold (%)")
    min_positive_folds: int = Field(4, description="Số fold OOS có lãi tối thiểu")
    min_total_oos_profit_pct: float = Field(0.0, description="Tổng lợi nhuận OOS mục tiêu (%)")


class WfaRunRequest(BaseModel):
    source_handle: Optional[str] = None
    strategy_snapshot: Optional[StrategySnapshot] = None
    symbol: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    config: Optional[WfaFoldConfig] = None


class WfaFoldResult(BaseModel):
    fold_index: int
    train_start_ts: int
    train_end_ts: int
    train_start_date: str
    train_end_date: str
    test_start_ts: int
    test_end_ts: int
    test_start_date: str
    test_end_date: str
    is_return_pct: float
    is_max_drawdown_pct: float
    is_trades_count: int
    is_win_rate: float
    oos_return_pct: float
    oos_max_drawdown_pct: float
    oos_trades_count: int
    oos_win_rate: float
    oos_profit_factor: float
    chosen_params: Dict[str, Any] = Field(default_factory=dict, description="Bộ tham số tối ưu IS được áp dụng cho OOS")
    passed_gate: bool
    gate_notes: List[str] = Field(default_factory=list)
    oos_trades: List[Dict[str, Any]] = Field(default_factory=list)


class WfaResultContract(BaseModel):
    wfa_id: str
    source_handle: str
    strategy_name: str
    symbol: str
    total_folds: int
    folds: List[WfaFoldResult]
    positive_folds_count: int
    total_oos_return_pct: float
    avg_oos_return_pct: float
    worst_fold_mdd_pct: float
    avg_oos_mdd_pct: float
    total_oos_trades: int
    overall_oos_win_rate: float
    wfe: Optional[float] = Field(None, description="Walk-Forward Efficiency (OOS Annualized Return / IS Annualized Return)")
    param_stability: Optional[float] = Field(None, description="Độ ổn định tham số giữa các fold")
    acceptance_gate_passed: bool
    gate_checks: Dict[str, Any]
    aggregate_oos_trades: List[Dict[str, Any]]
    aggregate_oos_equity: List[Dict[str, Any]]
    generated_at: int


class MonteCarloRunRequest(BaseModel):
    source_wfa_id: Optional[str] = None
    source_handle: Optional[str] = None
    trades: Optional[List[Dict[str, Any]]] = None
    strategy_name: Optional[str] = "Strategy"
    symbol: Optional[str] = None
    initial_capital: float = Field(10000.0, ge=1.0)
    simulations: int = Field(1000, ge=100, le=10000)
    ruin_threshold_pct: float = Field(30.0, ge=5.0, le=95.0, description="Ngưỡng sụt giảm vốn tính là Ruin (%)")
    confidence_levels: List[float] = Field(default_factory=lambda: [90.0, 95.0, 99.0])
    block_size: int = Field(1, ge=1, le=50, description="Kích thước block bootstrap (1 = trade độc lập)")
    seed: Optional[int] = Field(None, description="Random seed để tái lập kết quả")


class MonteCarloResultContract(BaseModel):
    mc_id: str
    source_wfa_id: Optional[str] = None
    strategy_name: str
    symbol: str
    simulations: int
    trades_count: int
    initial_capital: float
    percentile_mdd: Dict[str, float]
    risk_of_ruin_pct: float
    ruin_threshold_pct: float
    terminal_return_pct: Dict[str, float]
    sample_paths: List[List[float]]
    quantile_curves: Dict[str, Any] = Field(default_factory=dict, description="Percentile curves (p5, p25, p50, p75, p95)")
    source_gate_passed: bool = Field(False, description="WFA nguồn đã pass gate hay chưa")
    seed: Optional[int] = None
    summary: Dict[str, Any]
    generated_at: int
