"""Mọi NGƯỠNG của phễu kiểm duyệt — hằng số có tên (khớp bảng ở docs/funnel_contract.md §1). KHÔNG nới để có kết quả đẹp.

Hàm `evaluate_*` đọc hằng số TẠI THỜI ĐIỂM GỌI (không gán mặc định lúc import) nên test có thể monkeypatch module này.
Mỗi hàm trả `(passed, code, msg)`: code dạng "S3.positive_ratio", msg = "<code>: <câu tiếng Việt> (<số liệu>)".

Mốc thời gian dev1/dev2/holdout của phễu (windows):
Cửa sổ dữ liệu của phễu: dev1 / dev2 / holdout (cùng công thức build_strategy_book.windows) + fold WFA.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ── Danh sách tầng (thứ tự cố định) ─────────────────────────────────────────
STAGES: List[str] = ["S0_generate", "S1_backtest", "S2_antiluck", "S3_wfa", "S4_montecarlo", "S5_sizing", "S6_holdout", "FINAL"]
STAGE_IDX: Dict[str, int] = {s: i for i, s in enumerate(STAGES)}
STAGE_LABELS: Dict[str, str] = {
    "S0_generate": "Sinh alpha", "S1_backtest": "Backtest sàng lọc (dev1)", "S2_antiluck": "Chống ăn may (DSR / lân cận / PBO)",
    "S3_wfa": "Walk-forward (dev2)", "S4_montecarlo": "Monte Carlo", "S5_sizing": "Khối lượng sống sót",
    "S6_holdout": "Holdout (chấm một lần)", "FINAL": "Đủ điều kiện testnet",
}
NEIGHBOUR_STAGE = "S2_neighbour"   # kết quả backtest của điểm lân cận chưa có trong S1 (bảng stage_metrics, không phải tầng của phễu)

# ── Dữ liệu / cửa sổ ────────────────────────────────────────────────────────
WARMUP_DAYS = 20             # nạp thêm trước đầu cửa sổ để kernel đủ dữ liệu (như build_strategy_book)
DEV1_FRAC = 0.4              # dev1 = 40% đầu; dev2 = 40% tiếp theo; holdout = 20% cuối (như build_strategy_book.windows)
DEV2_FRAC = 0.8
INITIAL_CAPITAL = 10_000.0   # PortfolioEngine mặc định
BASE_RISK_PER_TRADE_PCT = 0.5   # rủi ro/lệnh ở hệ số s = 1 (= strategy_book.BASE_RISK_PER_TRADE_PCT)

# ── S0: sinh alpha ──────────────────────────────────────────────────────────
ALPHA_ID_LEN = 16            # số ký tự hex của alpha_id = sha1(chiến lược + tham số chuẩn hoá)[:16]
S0_MAX_LEVERAGE = 10         # đòn bẩy tối đa của bộ tham số (kho alpha: <= 10x)

# ── S1: backtest sàng lọc trên dev1 (rủi ro chuẩn, SL khớp đúng mức, kill switch tắt) ─
S1_MIN_RET_PCT = 0.0         # lãi dev1 phải > 0
S1_MAX_MDD_PCT = 30.0        # MDD tối đa (điểm xấu nhất trong nến)
S1_MIN_TRADES = 40           # số lệnh tối thiểu trên cả danh mục
S1_MIN_SYMBOLS_POSITIVE = 5  # số tài sản có lãi tối thiểu (độ phủ danh mục)

# ── S2: chống ăn may ────────────────────────────────────────────────────────
S2_DSR_MIN = 0.95                   # Deflated Sharpe Ratio (Bailey & López de Prado 2014) tối thiểu
S2_NEIGHBOUR_MIN_PROFIT_RATIO = 0.60   # >= 60% điểm lân cận (±1 bước mỗi khoá) có lãi trên dev1
S2_PBO_MAX = 0.5                    # PBO của chiến lược (CSCV) tối đa; vượt -> MỌI alpha của chiến lược bị gắn cờ và loại
S2_PBO_BLOCKS = 16                  # số khối của CSCV (C(16,8) = 12.870 cách chia)
S2_PBO_MAX_ALPHAS = 2000            # > 2000 alpha: chỉ lấy 2000 alpha điểm IS cao nhất cho ma trận PBO
S2_PBO_MIN_ALPHAS = 4               # ít hơn: không đủ alpha để xếp hạng -> không đo PBO (không gắn cờ)

# ── S3: walk-forward danh mục trên dev2 với tham số CỐ ĐỊNH ────────────────
S3_TRAIN_DAYS = 120
S3_TEST_DAYS = 30
S3_MIN_FOLDS = 5                    # tối thiểu số fold
S3_MIN_POSITIVE_FOLD_RATIO = 0.60   # >= 60% fold OOS có lãi
S3_MIN_COMPOUNDED_OOS_PCT = 0.0     # lãi kép OOS phải > 0
S3_MAX_FOLD_MDD_PCT = 30.0          # MDD fold OOS xấu nhất tối đa
S3_MIN_AVG_IS_RET_PCT = 0.0         # lãi IS trung bình các fold >= 0

# ── S4: Monte Carlo trên chuỗi ngày OOS (cơ sở "extreme") ──────────────────
S4_MIN_SIMULATIONS = 10_000         # >= 10.000 kịch bản bootstrap (= monte_carlo.MC_MIN_SIMULATIONS)
S4_RUIN_THRESHOLD_PCT = 30.0        # "cháy" = MDD >= 30%
S4_MAX_RUIN_PCT = 5.0               # P(MDD >= 30% trong 1 năm) <= 5%
S4_STRESS_MAX_MDD_PCT = 50.0        # MỌI kịch bản cực xấu: MDD < 50% và không chạm vốn 0
S4_MIN_DAYS = 20                    # ít hơn ngần này ngày OOS thì không đủ để bootstrap
S4_BLOCK_DAYS = 5
S4_HORIZON_DAYS = 365
S4_SEED = 1

# ── S5: khối lượng sống sót ─────────────────────────────────────────────────
S5_S_MIN = 0.2                      # s < 0,2 -> loại
S5_S_MAX = 1.0
S5_TOLERANCE = 0.01                 # dung sai tìm nhị phân
S5_CONFIRM_STEP = 0.05              # xác nhận trượt (backtest/WFA/MC thật ở s) -> hạ s thêm từng bước này rồi xác nhận lại
S5_CONFIRM_MAX_TRIES = 4

# ── S6: holdout (20% cuối), chấm MỘT lần ở hệ số s ──────────────────────────
S6_MIN_RET_PCT = 0.0                # lãi > 0 ở cả khớp "level" và "extreme"
S6_MAX_MDD_PCT = 30.0

# ── Mã lý do loại -> nhãn tiếng Việt (UI gom theo mã) ───────────────────────
REASON_LABELS: Dict[str, str] = {
    "S0.invalid_params": "Tham số không hợp lệ (vd. ngân sách DCA / khoá lạ)",
    "S1.ret_nonpositive": "Lãi dev1 ≤ 0",
    "S1.mdd": "MDD dev1 > 30%",
    "S1.min_trades": "Số lệnh ít hơn ngưỡng",
    "S1.symbols_positive": "Quá ít tài sản có lãi",
    "S1.error": "Backtest lỗi",
    "S2.pbo": "PBO của chiến lược > 0,5",
    "S2.dsr": "DSR < 0,95",
    "S2.neighbor": "Lân cận tham số có lãi < 60%",
    "S3.folds": "Số fold < 5",
    "S3.positive_ratio": "Tỉ lệ fold lãi < 60%",
    "S3.oos_compound": "Lãi kép OOS ≤ 0",
    "S3.worst_fold_mdd": "MDD fold xấu nhất > 30%",
    "S3.avg_is": "Lãi IS trung bình < 0",
    "S4.days": "Quá ít ngày OOS để chạy Monte Carlo",
    "S4.simulations": "Số kịch bản Monte Carlo < 10.000",
    "S4.p_mdd": "P(MDD ≥ 30%) > 5% (kể cả ở khối lượng tối thiểu)",
    "S4.stress_mdd": "Kịch bản cực xấu MDD ≥ 50%",
    "S4.stress_ruin": "Kịch bản cực xấu chạm vốn 0",
    "S5.scale_low": "Hệ số s < 0,2",
    "S5.confirm": "Xác nhận backtest + WFA + MC thật ở s không đạt",
    "S6.holdout_ret": "Holdout lãi ≤ 0",
    "S6.holdout_mdd": "Holdout MDD > 30%",
}


def reason_label(code: Optional[str]) -> str:
    return REASON_LABELS.get(code or "", code or "")


def _fmt(x: Any, nd: int = 2) -> str:
    if x is None:
        return "?"
    if isinstance(x, float):
        if not math.isfinite(x):
            return "?"
        return f"{round(x, nd):g}"
    return str(x)


def _msg(code: str, detail: str) -> str:
    return f"{code}: {reason_label(code)} ({detail})"


Verdict = Tuple[bool, Optional[str], Optional[str]]
_OK: Verdict = (True, None, None)


# ── S1 ──────────────────────────────────────────────────────────────────────
def evaluate_s1(m: Dict[str, Any]) -> Verdict:
    """m = số đo danh mục dev1 (ret_pct, mdd_pct, trades, symbols_positive). Thứ tự kiểm: lãi, MDD, số lệnh, độ phủ."""
    if not m.get("ret_pct", 0.0) > S1_MIN_RET_PCT:
        return False, "S1.ret_nonpositive", _msg("S1.ret_nonpositive", f"{_fmt(m.get('ret_pct'))}%")
    if m.get("mdd_pct", 0.0) > S1_MAX_MDD_PCT:
        return False, "S1.mdd", _msg("S1.mdd", f"{_fmt(m.get('mdd_pct'))}% > {_fmt(S1_MAX_MDD_PCT)}%")
    if m.get("trades", 0) < S1_MIN_TRADES:
        return False, "S1.min_trades", _msg("S1.min_trades", f"{m.get('trades', 0)} < {S1_MIN_TRADES}")
    if m.get("symbols_positive", 0) < S1_MIN_SYMBOLS_POSITIVE:
        return False, "S1.symbols_positive", _msg("S1.symbols_positive", f"{m.get('symbols_positive', 0)} < {S1_MIN_SYMBOLS_POSITIVE}")
    return _OK


# ── S2 ──────────────────────────────────────────────────────────────────────
def evaluate_s2(dsr: Optional[float], neighbour_ratio: Optional[float], pbo: Optional[float]) -> Verdict:
    """Thứ tự: PBO chiến lược (cờ cho mọi alpha) -> DSR -> lân cận. neighbour_ratio None = không có điểm lân cận (qua)."""
    if pbo is not None and pbo > S2_PBO_MAX:
        return False, "S2.pbo", _msg("S2.pbo", f"PBO {_fmt(pbo)}")
    if dsr is None or not dsr >= S2_DSR_MIN:
        return False, "S2.dsr", _msg("S2.dsr", f"{_fmt(dsr, 3)} < {_fmt(S2_DSR_MIN)}")
    if neighbour_ratio is not None and neighbour_ratio < S2_NEIGHBOUR_MIN_PROFIT_RATIO:
        return False, "S2.neighbor", _msg("S2.neighbor", f"{_fmt(neighbour_ratio * 100, 0)}% < {_fmt(S2_NEIGHBOUR_MIN_PROFIT_RATIO * 100, 0)}%")
    return _OK


# ── S3 ──────────────────────────────────────────────────────────────────────
def evaluate_s3(s: Dict[str, Any]) -> Verdict:
    """s = {folds, positive_ratio (0..1), compounded_oos_ret_pct, worst_fold_mdd, is_ret_avg}."""
    if s["folds"] < S3_MIN_FOLDS:
        return False, "S3.folds", _msg("S3.folds", f"{s['folds']} < {S3_MIN_FOLDS}")
    if s["positive_ratio"] < S3_MIN_POSITIVE_FOLD_RATIO:
        return False, "S3.positive_ratio", _msg("S3.positive_ratio", f"{_fmt(s['positive_ratio'] * 100, 0)}% < {_fmt(S3_MIN_POSITIVE_FOLD_RATIO * 100, 0)}%")
    if not s["compounded_oos_ret_pct"] > S3_MIN_COMPOUNDED_OOS_PCT:
        return False, "S3.oos_compound", _msg("S3.oos_compound", f"{_fmt(s['compounded_oos_ret_pct'])}%")
    if s["worst_fold_mdd"] > S3_MAX_FOLD_MDD_PCT:
        return False, "S3.worst_fold_mdd", _msg("S3.worst_fold_mdd", f"{_fmt(s['worst_fold_mdd'])}% > {_fmt(S3_MAX_FOLD_MDD_PCT)}%")
    if s["is_ret_avg"] is None or s["is_ret_avg"] < S3_MIN_AVG_IS_RET_PCT:
        return False, "S3.avg_is", _msg("S3.avg_is", f"{_fmt(s['is_ret_avg'])}%")
    return _OK


# ── S4 ──────────────────────────────────────────────────────────────────────
def evaluate_mc_checks(gate: Dict[str, Any], prefix: str = "S4") -> Verdict:
    """gate = evaluate_mc_gate(...) của backend.carlo.monte_carlo (4 check). Trả lý do của check trượt đầu tiên."""
    ch = gate["checks"]
    order = (("simulations", f"{prefix}.simulations"), ("ruin", f"{prefix}.p_mdd"), ("stress_mdd", f"{prefix}.stress_mdd"),
             ("stress_ruin", f"{prefix}.stress_ruin"))
    for key, code in order:
        c = ch[key]
        if not c["passed"]:
            return False, code, _msg(code, f"{_fmt(c.get('actual'))} (cần {c.get('required')})")
    return _OK


# ── S6 ──────────────────────────────────────────────────────────────────────
def evaluate_s6(level: Dict[str, Any], extreme: Dict[str, Any]) -> Verdict:
    for name, m in (("khớp đúng mức", level), ("giá xấu nhất", extreme)):
        if not m["ret_pct"] > S6_MIN_RET_PCT:
            return False, "S6.holdout_ret", _msg("S6.holdout_ret", f"{name}: {_fmt(m['ret_pct'])}%")
        if m["mdd_pct"] > S6_MAX_MDD_PCT:
            return False, "S6.holdout_mdd", _msg("S6.holdout_mdd", f"{name}: {_fmt(m['mdd_pct'])}% > {_fmt(S6_MAX_MDD_PCT)}%")
    return _OK


def thresholds_snapshot() -> Dict[str, Any]:
    """Ngưỡng hiện hành (ghi vào run.json để lượt chạy tái lập được)."""
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float)) and not isinstance(v, bool)}


# ─── Mốc thời gian dev1/dev2/holdout của phễu (windows) ────────────────────
DAY = 86_400_000


def _ms(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").value // 1_000_000)


def iso_date(ts: int) -> str:
    return f"{pd.Timestamp(int(ts), unit='ms'):%Y-%m-%d}"


def compute_windows(symbols: List[str], override: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """{"start", "dev1_end", "dev2_end", "end"} (ms UTC). Mặc định: start = max(đầu dữ liệu) + WARMUP, end = min(cuối dữ liệu),
    dev1 = 40% đầu, dev2 = 40% tiếp, holdout = 20% cuối. `override` ({khoá: "YYYY-MM-DD"}) ghi đè từng mốc; mốc phải tăng dần."""
    from backend.db.local_pkl import read_manifest
    ms = [read_manifest(s) for s in symbols]
    if not all(ms):
        raise SystemExit(f"Thiếu dữ liệu (manifest) cho: {[s for s, m in zip(symbols, ms) if not m]}")
    start = max(int(m["start_ts"]) for m in ms) + WARMUP_DAYS * DAY
    end = min(int(m["end_ts"]) for m in ms)
    span = end - start
    w = {"start": start, "dev1_end": start + int(span * DEV1_FRAC), "dev2_end": start + int(span * DEV2_FRAC), "end": end}
    for k, v in (override or {}).items():
        if k not in w:
            raise ValueError(f"windows: khoá lạ {k!r}; có: {sorted(w)}")
        w[k] = _ms(v)
    if not (w["start"] < w["dev1_end"] < w["dev2_end"] < w["end"]):
        raise ValueError("windows: phải có start < dev1_end < dev2_end < end")
    return w


def windows_iso(w: Dict[str, int]) -> Dict[str, str]:
    return {k: iso_date(v) for k, v in w.items()}


def wfa_folds(w: Dict[str, int], train_days: Optional[int] = None, test_days: Optional[int] = None) -> List[Dict[str, int]]:
    """Fold WFA trên dev2 (dev1_end -> dev2_end), OOS liền nhau không chồng lấp."""
    from backend.wfa.walk_forward import generate_folds
    return generate_folds(int(w["dev1_end"]), int(w["dev2_end"]), train_days or S3_TRAIN_DAYS, test_days or S3_TEST_DAYS)
