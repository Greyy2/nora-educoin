"""Bản nháp hợp đồng thực thi & chuẩn Parity Backtest-Live.

Định nghĩa các bất biến (invariants), thông số chi phí, mô hình khớp lệnh, và dung sai đối soát
giữa Backtest (Nautilus BacktestEngine) và Live (Nautilus TradingNode / Exchange Adapter).

Thông số hiện tại chưa được xác minh theo tài khoản/venue và không đủ điều kiện
để chứng nhận parity hoặc promote một kết quả backtest.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Any, Dict, List, Optional, Tuple

CONTRACT_VERSION = "1.0.0"
CONTRACT_NAME = "COIN_EXECUTION_PARITY_CONTRACT_V1"

# ── 1. BẤT BIẾN DỮ LIỆU THỊ TRƯỜNG & TÍNH NHÂN QUẢ (CAUSAL DATA) ──
SIGNAL_DECISION_RULE = "CLOSED_BAR_ONLY"   # Tín hiệu CHỈ sinh sau khi nến đã đóng hoàn toàn (UTC ts_event / ts_init)
TIMEFRAME_ALIGNMENT = "UTC_ALIGNED"        # Nến resample (5m, 15m, 1h, 4h, 24h) tính từ mốc 00:00:00 UTC
PROHIBIT_FUTURE_DATA = True               # Nghiêm cấm nhìn trước tương lai (zero lookahead bias)
INTERPOLATION_POLICY = "FAIL_CLOSED"      # Dữ liệu nến thiếu/trùng không tự suy diễn; thiếu dữ liệu bắt buộc -> fail

# ── 2. ĐỘ TRỄ VÀ ĐỊNH GIÁ THỰC THI (TIMING & PRICING) ──
EXECUTION_TIMING = "NEXT_CANDLE_OPEN"              # Owner-approved target; current Nautilus path does not implement it yet.
DEFAULT_ORDER_TYPE = "TAKER"                      # Mặc định taker; maker chỉ áp dụng khi có bằng chứng mô hình xác suất khớp (fill probability)
DEFAULT_LATENCY_MS = 50                           # Giá trị minh họa chưa được đo/hiệu chuẩn; không dùng để chứng nhận

# ── 3. CHI PHÍ, TRƯỢT GIÁ VÀ TỶ GIÁ FUNDING (COSTS & FUNDING) ──
DEFAULT_TAKER_FEE_RATE = 0.0005                   # Mức minh họa, chưa xác minh tier tài khoản
DEFAULT_MAKER_FEE_RATE = 0.0002                   # Mức minh họa, chưa xác minh tier tài khoản
MIN_SLIPPAGE_RATE = 0.0002                        # Floor minh họa, chưa hiệu chuẩn từ fills/spread
FUNDING_SETTLEMENT_HOURS_UTC = (0, 8, 16)          # Các mốc thanh toán funding của OKX: 00:00, 08:00, 16:00 UTC
STRESS_COST_MULTIPLIER_SWING = 2.0                # Hệ số stress chi phí cho swing (5m-24h): x2
STRESS_COST_MULTIPLIER_SCALP = 3.0                # Hệ số stress chi phí tối đa cho 1m scalp: x3

# ── 4. KÝ QUỸ, ĐÒN BẨY VÀ THANH LÝ (MARGIN & LIQUIDATION) ──
MAINTENANCE_MARGIN_RATE_TIER1 = 0.004             # Mức minh họa chưa xác minh; mâu thuẫn snapshot instrument hiện có
LIQUIDATION_PRICE_REFERENCE = "MARK_PRICE"        # Đánh giá thanh lý dựa trên Mark Price, không dùng Last Trade Price
MANDATORY_VENUE_HARD_SL = True                    # Bắt buộc stop-loss cứng được sàn xác nhận (venue acknowledgement)

# ── 5. QUYẾT ĐỊNH CỦA OWNER VỀ TÀI KHOẢN VÀ CỔNG RỦI RO (OWNER RISK LIMITS) ──
VIRTUAL_MASTER_CAPITAL_USDT = 10_000.0             # Master equity ảo mặc định cho OKX Demo
VIRTUAL_BOT_CAPITAL_USDT = 1_000.0                 # Vốn cấp cho mỗi bot/sleeve
MAX_RISK_PER_TRADE_PCT = 0.0025                    # Rủi ro tối đa mỗi lệnh: 0.25% Master Equity
DAILY_LOSS_LIMIT_MASTER_PCT = 0.02                 # Giới hạn lỗ ngày Master: 2.0%
DAILY_LOSS_LIMIT_BOT_PCT = 0.03                    # Giới hạn lỗ ngày Bot: 3.0%
PROVISIONAL_MDD_STOP_PCT = 0.15                    # Ngưỡng dừng drawdown tạm thời: 15% (sau này: min(1.5x OOS MDD, 20%))
MAX_GROSS_LEVERAGE = 3.0                           # Trần đòn bẩy gộp danh mục: <= 3.0x equity
MAX_NET_EXPOSURE = 2.0                             # Trần vị thế ròng một chiều (BTC+ETH): <= 2.0x equity
MIDNIGHT_UTC_FLATTEN = True                        # Tất toán vị thế tại 00:00:00 UTC sau khi tính funding
REJECT_ENTRY_AT_OR_AFTER_BOUNDARY = True           # Từ chối lệnh mới có fill timestamp >= 00:00:00 UTC
APPROVED_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
APPROVED_VENUES = ("OKX_DEMO", "OKX_TESTNET")

# ── 6. DUNG SAI NGHIỆM THU PARITY (PARITY ACCEPTANCE TOLERANCES) ──
TOLERANCE_FIXTURE_DECISION_PARITY = 1.0           # 100% quyết định (signal, intent, order) phải khớp trên bộ fixture độc lập
TOLERANCE_REPLAY_DECISION_PARITY = 0.99           # >= 99% quyết định phải khớp khi record/replay Paper/Demo
MAX_COST_MODEL_DEVIATION = 0.30                   # Độ lệch chi phí mô hình hoá so với thực tế quan sát được <= 30%
MAX_EXPECTANCY_DRIFT = 0.30                       # Độ trôi expectancy backtest vs replay <= 30%

APPROVED_RESEARCH_PROXY = {
    "status": "APPROVED_PROXY",
    "measured": False,
    "promotion_allowed": False,
    "official_ranking_allowed": False,
    "slippage_taker_bps_per_side": {
        "BTC": 3.0,
        "ETH": 5.0,
        "SOL": 6.0,
        "BNB": 5.0,
        "XRP": 6.0,
        "DOGE": 7.0,
        "ADA": 7.0,
        "AVAX": 7.0,
        "LINK": 7.0,
        "TRX": 6.0,
    },
    "stop_slippage_multiplier": 2.0,
    "entry_fill_timing": "NEXT_CANDLE_OPEN",
    "signal_exit_fill_timing": "NEXT_CANDLE_OPEN",
    "observed_engine_fill_timing": "NEXT_CANDLE_OPEN_SYNTHETIC_QUOTE",
    "swing_stress_multiplier": 2.0,
    "scalp_stress_multipliers": [2.0, 3.0],
    "fee_status": "UNVERIFIED",
    "funding_status": "PARTIAL_PUBLIC_HISTORY",
    "next_open_proxy_implemented": True,
    "matching_engine": "NAUTILUS_ORDER_MATCHING_ENGINE",
    "quote_source": "SYNTHETIC_OHLC_OPEN",
    "quote_depth_modeled": False,
    "measured_latency": False,
    "execution_implemented": False,
}


@dataclass(frozen=True)
class ExecutionContractManifest:
    version: str = CONTRACT_VERSION
    name: str = CONTRACT_NAME
    signal_decision_rule: str = SIGNAL_DECISION_RULE
    execution_timing: str = EXECUTION_TIMING
    default_order_type: str = DEFAULT_ORDER_TYPE
    default_latency_ms: int = DEFAULT_LATENCY_MS
    taker_fee_rate: float = DEFAULT_TAKER_FEE_RATE
    maker_fee_rate: float = DEFAULT_MAKER_FEE_RATE
    min_slippage_rate: float = MIN_SLIPPAGE_RATE
    funding_settlement_hours_utc: Tuple[int, ...] = FUNDING_SETTLEMENT_HOURS_UTC
    stress_cost_swing: float = STRESS_COST_MULTIPLIER_SWING
    stress_cost_scalp: float = STRESS_COST_MULTIPLIER_SCALP
    liquidation_ref: str = LIQUIDATION_PRICE_REFERENCE
    mandatory_hard_sl: bool = MANDATORY_VENUE_HARD_SL
    virtual_master_capital_usdt: float = VIRTUAL_MASTER_CAPITAL_USDT
    virtual_bot_capital_usdt: float = VIRTUAL_BOT_CAPITAL_USDT
    max_risk_per_trade_pct: float = MAX_RISK_PER_TRADE_PCT
    daily_loss_master_pct: float = DAILY_LOSS_LIMIT_MASTER_PCT
    daily_loss_bot_pct: float = DAILY_LOSS_LIMIT_BOT_PCT
    provisional_mdd_stop_pct: float = PROVISIONAL_MDD_STOP_PCT
    max_gross_leverage: float = MAX_GROSS_LEVERAGE
    max_net_exposure: float = MAX_NET_EXPOSURE
    midnight_utc_flatten: bool = MIDNIGHT_UTC_FLATTEN
    reject_boundary_entry: bool = REJECT_ENTRY_AT_OR_AFTER_BOUNDARY
    fixture_decision_parity: float = TOLERANCE_FIXTURE_DECISION_PARITY
    replay_decision_parity: float = TOLERANCE_REPLAY_DECISION_PARITY
    max_cost_deviation: float = MAX_COST_MODEL_DEVIATION
    max_expectancy_drift: float = MAX_EXPECTANCY_DRIFT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "invariants": {
                "signal_decision_rule": self.signal_decision_rule,
                "execution_timing": self.execution_timing,
                "default_order_type": self.default_order_type,
                "prohibit_future_data": PROHIBIT_FUTURE_DATA,
                "interpolation_policy": INTERPOLATION_POLICY,
            },
            "parameters": {
                "default_latency_ms": self.default_latency_ms,
                "taker_fee_rate": self.taker_fee_rate,
                "maker_fee_rate": self.maker_fee_rate,
                "min_slippage_rate": self.min_slippage_rate,
                "funding_settlement_hours_utc": list(self.funding_settlement_hours_utc),
                "liquidation_price_reference": self.liquidation_ref,
                "mandatory_venue_hard_sl": self.mandatory_hard_sl,
            },
            "owner_risk_limits": {
                "virtual_master_capital_usdt": self.virtual_master_capital_usdt,
                "virtual_bot_capital_usdt": self.virtual_bot_capital_usdt,
                "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
                "daily_loss_master_pct": self.daily_loss_master_pct,
                "daily_loss_bot_pct": self.daily_loss_bot_pct,
                "provisional_mdd_stop_pct": self.provisional_mdd_stop_pct,
                "max_gross_leverage": self.max_gross_leverage,
                "max_net_exposure": self.max_net_exposure,
                "midnight_utc_flatten": self.midnight_utc_flatten,
                "reject_boundary_entry": self.reject_boundary_entry,
                "approved_instruments": list(APPROVED_INSTRUMENTS),
                "approved_venues": list(APPROVED_VENUES),
            },
            "tolerances": {
                "fixture_decision_parity": self.fixture_decision_parity,
                "replay_decision_parity": self.replay_decision_parity,
                "max_cost_model_deviation": self.max_cost_deviation,
                "max_expectancy_drift": self.max_expectancy_drift,
                "stress_multipliers": {
                    "swing_5m_24h": self.stress_cost_swing,
                    "scalp_1m": self.stress_cost_scalp,
                },
            },
        }


_GLOBAL_MANIFEST = ExecutionContractManifest()


def get_execution_contract_manifest() -> Dict[str, Any]:
    """Trả về draft contract, proxy nghiên cứu đã duyệt và timing mismatch chưa được khắc phục."""
    manifest = _GLOBAL_MANIFEST.to_dict()
    manifest["status"] = "DRAFT_UNVERIFIED"
    manifest["parameters_authoritative"] = False
    manifest["research_cost_proxy"] = deepcopy(APPROVED_RESEARCH_PROXY)
    return manifest


ATTESTATION_SECRET_SALT = "NORA_SERVER_PARITY_ATTESTATION_SECRET_2026"


def compute_attestation_signature(payload: Dict[str, Any], salt: str = ATTESTATION_SECRET_SALT) -> str:
    """Tính chữ ký số SHA256 ràng buộc không thể giả mạo của Server Attestation."""
    keys = (
        "engine_version_hash",
        "contract_version",
        "code_hash",
        "config_hash",
        "symbol",
        "data_digest",
        "cost_model_hash",
        "risk_gate_passed",
        "oos_mdd",
        "issued_at_utc",
    )
    canonical_repr = "|".join(str(payload.get(k, "")) for k in keys)
    return hmac.new(salt.encode("utf-8"), canonical_repr.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_server_attestation(
    engine_version_hash: str,
    code_hash: str,
    config_hash: str,
    symbol: str,
    data_digest: str,
    cost_model_hash: str,
    risk_gate_passed: bool,
    oos_mdd: float,
    oos_sharpe: float,
    salt: str = ATTESTATION_SECRET_SALT,
) -> Dict[str, Any]:
    """Cấp chứng chỉ kiểm định chính thức từ server (Server-Owned Attestation)."""
    now_utc = datetime.now(timezone.utc).isoformat()
    record = {
        "engine_version_hash": engine_version_hash,
        "contract_version": CONTRACT_VERSION,
        "code_hash": code_hash,
        "config_hash": config_hash,
        "symbol": symbol,
        "data_digest": data_digest,
        "cost_model_hash": cost_model_hash,
        "risk_gate_passed": risk_gate_passed,
        "oos_mdd": float(oos_mdd),
        "oos_sharpe": float(oos_sharpe),
        "issued_at_utc": now_utc,
    }
    record["signature"] = compute_attestation_signature(record, salt=salt)
    return record


def verify_server_attestation(attestation: Optional[Dict[str, Any]], salt: str = ATTESTATION_SECRET_SALT) -> Tuple[bool, str]:
    """Xác thực tính toàn vẹn và chữ ký của Server Attestation chống giả mạo."""
    if not isinstance(attestation, dict):
        return False, "Thiếu hoặc sai cấu trúc server_attestation"

    sig = attestation.get("signature")
    if not sig or not isinstance(sig, str):
        return False, "Thiếu trường chữ ký số signature trong attestation"

    expected_sig = compute_attestation_signature(attestation, salt=salt)
    if not hmac.compare_digest(sig, expected_sig):
        return False, "CHỮ_KÝ_KHÔNG_HỢP_LỆ: Attestation đã bị sửa đổi hoặc giả mạo"

    if not attestation.get("risk_gate_passed"):
        return False, "ATTESTATION_REJECTED: Chiến lược không vượt qua cổng rủi ro (risk_gate_passed=False)"

    if attestation.get("contract_version") != CONTRACT_VERSION:
        return False, f"ATTESTATION_EXPIRED: Phiên bản hợp đồng không khớp ({attestation.get('contract_version')} != {CONTRACT_VERSION})"

    return True, "ATTESTATION_VALID"


def verify_candidate_parity_provenance(candidate: Dict[str, Any]) -> Tuple[bool, str]:
    """Fail-closed: Chỉ chấp nhận candidate có Server Attestation hợp lệ, nhưng vẫn khóa promotion cho đến khi hoàn thành mọi evidence gates."""
    if not candidate:
        return False, "Candidate rỗng hoặc không tồn tại"

    attestation = candidate.get("server_attestation")
    if not attestation:
        return False, (
            "PARITY_VALIDATION_NOT_IMPLEMENTED: Chưa có bằng chứng kiểm định do server "
            "tạo và ràng buộc với đúng mã, cấu hình, dữ liệu, instrument, cost model và risk gates."
        )

    valid, reason = verify_server_attestation(attestation)
    if not valid:
        return False, f"ALPHA_RESULT_FORGED_OR_INVALID: {reason}"

    # Ngay cả khi attestation hợp lệ, nếu GATE 0 chưa mở promotion_allowed thì vẫn fail-closed
    manifest = get_execution_contract_manifest()
    if not manifest["research_cost_proxy"].get("promotion_allowed", False):
        return False, (
            "PROMOTION_LOCKED_PENDING_ALL_GATES: Candidate mang attestation hợp lệ nhưng "
            "hệ thống đang trong trạng thái đóng băng promotion (GATE 0: promotion_allowed=False)."
        )

    return True, "PROVENANCE_VERIFIED"


def verify_backtest_job_parity(job_record: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Fail closed: Kiểm tra Server Attestation đính kèm job backtest."""
    if not job_record:
        return False, "Không tìm thấy bản ghi job backtest"

    attestation = job_record.get("server_attestation")
    if not attestation:
        return False, (
            "PARITY_VALIDATION_NOT_IMPLEMENTED: Job không có bằng chứng kiểm định "
            "do server tạo và xác thực."
        )

    valid, reason = verify_server_attestation(attestation)
    if not valid:
        return False, f"JOB_ATTESTATION_FORGED_OR_INVALID: {reason}"

    manifest = get_execution_contract_manifest()
    if not manifest["research_cost_proxy"].get("promotion_allowed", False):
        return False, (
            "PROMOTION_LOCKED_PENDING_ALL_GATES: Job mang attestation hợp lệ nhưng "
            "hệ thống đang trong trạng thái đóng băng promotion (GATE 0: promotion_allowed=False)."
        )

    return True, "JOB_PARITY_VERIFIED"
