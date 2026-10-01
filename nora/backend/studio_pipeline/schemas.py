"""Schemas & Data Contracts cho Studio Pipeline: Backtest -> WFA -> Monte Carlo."""
import math
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ─── param_grid validation constants ─────────────────────────────────────────
ALLOWED_GRID_KEYS = {
    "stop_loss_rate", "take_profit_rate", "timeout", "leverage", "max_open_trades",
    "trailing_stop", "trailing_activation_pct", "order_size_pct",
    "dca_step_pct", "dca_max_layers", "dca_size_multiplier",
}
MAX_GRID_COMBOS = 50


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
    trailing_stop: float = Field(0.0)
    trailing_activation_pct: float = Field(0.0)
    market: str = Field("spot", pattern="^(spot|perp)$")
    order_size_pct: float = Field(100.0)
    dca_step_pct: float = Field(0.0)
    dca_max_layers: int = Field(0)
    dca_size_multiplier: float = Field(1.0)
    maintenance_margin_rate: float = Field(0.005)
    fee_rate: Optional[float] = Field(None)
    maker_fee_rate: Optional[float] = Field(None)
    stop_fill: str = Field("level", pattern="^(level|extreme)$", description="Khớp SL: đúng mức | giá xấu nhất của nến (bi quan)")
    exit_unit: str = Field("pct", pattern="^(pct|atr)$", description="SL/TP/trailing/bước DCA: % | bội số ATR% lúc vào lệnh")
    atr_frame: str = Field("1h", pattern="^(1m|5m|15m|1h|4h|24h)$")
    atr_period: int = Field(14, ge=2, le=200)
    sizing: str = Field("margin_pct", pattern="^(margin_pct|risk)$", description="Khối lượng: % vốn làm ký quỹ | theo rủi ro tại SL")
    risk_per_trade_pct: float = Field(0.5, gt=0.0, le=5.0, description="sizing=risk: % vốn mất nếu chạm SL")
    max_notional_pct: float = Field(100.0, gt=0.0, le=1000.0, description="sizing=risk: trần danh nghĩa một vị thế, % vốn")
    signal_params: Dict[str, float] = Field(default_factory=dict, description="Giá trị ngưỡng tín hiệu ({'param': ...} trong AST)")
    param_candidates: Optional[List[Dict[str, Any]]] = Field(None, description="Danh sách tổ hợp cụ thể để WFA chọn trên IS (thay cho param_grid)")
    slippage_rate: Optional[float] = Field(None)
    param_grid: Optional[Dict[str, List[Any]]] = Field(default_factory=dict, description="Grid tham số tối ưu IS")

    @field_validator("param_grid")
    @classmethod
    def _check_grid(cls, v: Optional[Dict[str, List[Any]]]) -> Optional[Dict[str, List[Any]]]:
        if not v:
            return v or {}
        bad_keys = {k for k in v if k not in ALLOWED_GRID_KEYS and not k.startswith("sig.")}
        if bad_keys:
            raise ValueError(
                f"param_grid có key không hợp lệ: {sorted(bad_keys)}. "
                f"Chỉ chấp nhận: {sorted(ALLOWED_GRID_KEYS)}"
            )
        for k, vals in v.items():
            if not isinstance(vals, list) or len(vals) == 0:
                raise ValueError(f"param_grid['{k}'] phải là list không rỗng")
            for x in vals:
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    raise ValueError(
                        f"param_grid['{k}'] chỉ chấp nhận số (int/float), "
                        f"không chấp nhận {type(x).__name__}: {x!r}"
                    )
        # Dùng math.prod để không dựng list tổ hợp (an toàn với grid lớn)
        n = math.prod(len(vals) for vals in v.values())
        if n > MAX_GRID_COMBOS:
            raise ValueError(
                f"param_grid có {n} tổ hợp > {MAX_GRID_COMBOS}. "
                "Hãy giảm số lượng tham số hoặc thu hẹp khoảng giá trị."
            )
        return v

    @field_validator("param_candidates")
    @classmethod
    def _check_candidates(cls, v):
        if v is None:
            return v
        if len(v) > MAX_GRID_COMBOS:
            raise ValueError(f"param_candidates có {len(v)} tổ hợp > {MAX_GRID_COMBOS}")
        for combo in v:
            bad = {k for k in combo if k not in ALLOWED_GRID_KEYS and not k.startswith("sig.")}
            if bad:
                raise ValueError(f"param_candidates có key không hợp lệ: {sorted(bad)}")
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in combo.values()):
                raise ValueError("param_candidates chỉ nhận giá trị số")
        return v


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
    model_config = ConfigDict(extra="forbid")

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
    min_is_profit_pct: float = Field(0.0, description="Lợi nhuận IS trung bình tối thiểu (%) của các fold TRADED; dùng trong acceptance gate")
    max_is_mdd_pct: float = Field(15.0, description="(Chưa dùng trong gate) MDD IS tối đa (%)")
    min_oos_profit_pct: float = Field(0.0, description="Lợi nhuận OOS tối thiểu (%)")
    max_oos_mdd_pct: float = Field(25.0, description="MDD OOS tối đa từng fold (%)")
    min_positive_folds: int = Field(4, description="Số fold OOS có lãi tối thiểu")
    min_total_oos_profit_pct: float = Field(0.0, description="Tổng lợi nhuận OOS mục tiêu (%)")


class WfaRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    status: str = Field("TRADED", description="TRADED | NO_TRADE (không đủ lệnh IS)")


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
    param_stability: Optional[float] = Field(None, description="Độ ổn định tham số giữa các fold (None khi không có grid)")
    acceptance_gate_passed: bool
    gate_checks: Dict[str, Any]
    aggregate_oos_trades: List[Dict[str, Any]]
    aggregate_oos_equity: List[Dict[str, Any]]
    generated_at: int


class MonteCarloRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    max_ruin_pct: float = Field(5.0, ge=0.0, le=100.0, description="Xác suất ruin tối đa (%) để coi là robust")


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
    source_gate_passed: Optional[bool] = Field(None, description="WFA gate: True=pass, False=fail, None=MC standalone (không qua WFA)")
    seed: Optional[int] = None
    max_ruin_pct: Optional[float] = None
    robust_passed: bool = Field(False, description="True chỉ khi nguồn đã qua WFA gate VÀ risk_of_ruin_pct <= max_ruin_pct")
    robust_checks: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any]
    generated_at: int
