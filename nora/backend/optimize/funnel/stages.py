"""Phễu alpha S0 -> FINAL (P9.6): ngưỡng cổng (gates), tìm hệ số khối lượng (sizing), thống kê, ước lượng, bộ điều phối các tầng (orchestrator), promote, xuất bản sổ (publish), tính lại (recompute) và job chạy phễu (run).

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8).
"""
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import numpy as np

from backend.optimize.funnel.storage import atomic_write_json, FLAT_KEYS as DIST_KEYS, RunStore, StageResult
from backend.optimize.process.process import graceful_sigterm, Progress
from backend.optimize.search import evaluate as bt
from backend.optimize.search.evaluate import SharedExporter
from backend.optimize.search.generate import alpha_id_of, count_params, iter_params, iter_params_factored, regime_variants, space_for, validate_alpha
from backend.metrics.trades import num_or_none
from backend.crawl.store import as_list, options, read_json, write_job_result
from backend.carlo import carlo
from backend.models.params import BASE_RISK_PER_TRADE_PCT, DAY_MS as DAY, date_ms, iso_date
from backend.wfa import wfa as wfa_mod


# ══════════════════════════════════════════════════════════════════════════
# Mọi NGƯỠNG của phễu kiểm duyệt — hằng số có tên (khớp bảng ở docs/funnel_contract.md §1). KHÔNG nới để có kết quả đẹp.
#
# Hàm `evaluate_*` đọc hằng số TẠI THỜI ĐIỂM GỌI (không gán mặc định lúc import) nên test có thể monkeypatch module này.
# Mỗi hàm trả `(passed, code, msg)`: code dạng "S3.positive_ratio", msg = "<code>: <câu tiếng Việt> (<số liệu>)".
#
# Mốc thời gian dev1/dev2/holdout của phễu (windows):
# Cửa sổ dữ liệu của phễu: dev1 / dev2 / holdout (cùng công thức build_strategy_book.windows) + fold WFA.
# ══════════════════════════════════════════════════════════════════════════

# ── Danh sách tầng (thứ tự cố định) ─────────────────────────────────────────
# Từ 08/10/2026 KHÔNG còn tầng chống ăn may riêng: lân cận tham số + PBO chạy trong S3 (walk-forward), DSR (N hiệu dụng) chạy trong S4 (Monte
# Carlo, tầng kết luận). Số hiệu tầng GIỮ NGUYÊN (S3 vẫn là S3_wfa...) nên `stage_idx` / tên tầng trong kho và thư mục lệnh của lượt cũ vẫn khớp;
# chỉ chừa trống số 2. Lượt cũ còn khối S2_antiluck -> hiển thị như tầng "cũ" (LEGACY_STAGE), không ghi lại dữ liệu.
STAGES: List[str] = ["S0_generate", "S1_backtest", "S3_wfa", "S4_montecarlo", "S5_sizing", "S6_holdout", "FINAL"]
STAGE_IDX: Dict[str, int] = {"S0_generate": 0, "S1_backtest": 1, "S3_wfa": 3, "S4_montecarlo": 4, "S5_sizing": 5, "S6_holdout": 6, "FINAL": 7}
IDX_S1, IDX_S3, IDX_S4 = STAGE_IDX["S1_backtest"], STAGE_IDX["S3_wfa"], STAGE_IDX["S4_montecarlo"]   # tầng "trước" của S3 / S4 / S5 (cho store.pending)
LEGACY_STAGE = "S2_antiluck"                      # chỉ còn trong kho của lượt chạy trước 08/10/2026
LEGACY_STAGE_IDX: Dict[str, int] = {LEGACY_STAGE: 2}
ALL_STAGE_IDX: Dict[str, int] = {**STAGE_IDX, **LEGACY_STAGE_IDX}
STAGE_LABELS: Dict[str, str] = {
    "S0_generate": "Sinh alpha", "S1_backtest": "Backtest sàng lọc (dev1)", LEGACY_STAGE: "Chống ăn may (tầng cũ, nay gộp vào S3 / S4)",
    "S3_wfa": "Walk-forward (dev2) + lân cận / PBO", "S4_montecarlo": "Monte Carlo + DSR (kết luận)", "S5_sizing": "Khối lượng sống sót",
    "S6_holdout": "Holdout (chấm một lần)", "FINAL": "Đủ điều kiện testnet",
}
TRADE_STAGES: Tuple[str, ...] = ("S1_backtest", "S3_wfa", "S5_sizing", "S6_holdout")   # tầng LƯU lệnh vào kho (storage.write_trades) — thứ tự tầng; route /trades + meta đọc từ đây
NEIGHBOUR_STAGE = "S2_neighbour"   # kết quả backtest của điểm lân cận chưa có trong S1 (bảng stage_metrics, không phải tầng của phễu)


def trades_from(stage: str) -> Optional[str]:
    """Tầng mà `stage` hiển thị lệnh của nó: chính nó có lệnh -> None; không thì tầng có lệnh gần nhất đứng TRƯỚC trong thứ tự phễu (kể cả tầng cũ S2)."""
    if stage in TRADE_STAGES:
        return None
    order = sorted({**STAGE_IDX, **LEGACY_STAGE_IDX}.items(), key=lambda kv: kv[1])
    prev = [s for s, _ in order if ALL_STAGE_IDX[stage] > ALL_STAGE_IDX[s] and s in TRADE_STAGES]
    return prev[-1] if prev else None

# ── Dữ liệu / cửa sổ ────────────────────────────────────────────────────────
WARMUP_DAYS = 20             # nạp thêm trước đầu cửa sổ để kernel đủ dữ liệu (như build_strategy_book)
DEV1_FRAC = 0.4              # dev1 = 40% đầu; dev2 = 40% tiếp theo; holdout = 20% cuối (như build_strategy_book.windows)
DEV2_FRAC = 0.8

# ── S0: sinh alpha ──────────────────────────────────────────────────────────
ALPHA_ID_LEN = 16            # số ký tự hex của alpha_id = sha1(chiến lược + tham số chuẩn hoá)[:16]
S0_MAX_LEVERAGE = 10         # đòn bẩy tối đa của bộ tham số (kho alpha: <= 10x)

# ── S1: backtest sàng lọc trên dev1 (rủi ro chuẩn, SL khớp đúng mức, kill switch tắt) ─
S1_MIN_RET_PCT = 0.0         # lãi dev1 phải > 0
S1_MAX_MDD_PCT = 30.0        # MDD tối đa (điểm xấu nhất trong nến)
S1_MIN_TRADES = 40           # số lệnh tối thiểu trên cả danh mục
S1_MIN_SYMBOLS_POSITIVE = 5  # số tài sản có lãi tối thiểu (độ phủ danh mục)

# ── Chống ăn may (trước đây tầng S2; tên hằng giữ nguyên): lân cận + PBO chạy ở S3, DSR chạy ở S4 ───────────────
# Từ 03/10/2026 DSR / PBO là XẾP HẠNG + CẢNH BÁO, không còn cổng cứng trước WFA: DSR >= 0,95 chặn 100% (kể cả với N hiệu dụng) trong khi
# nhóm alpha qua WFA (cổng S3 mới) lãi trên holdout (TB +2% so với −2,1% của alpha ngẫu nhiên). Quyết định qua/không giao cho các cổng NGOÀI
# MẪU (S3 WFA, S4 Monte Carlo, S6 holdout); S4 giữ top DSR của mỗi chiến lược, S3 kiểm lân cận tham số + PBO.
S2_DSR_TOP_FRAC = 0.05              # đi tiếp: top 5% DSR trong các alpha đã qua S1 của CÙNG chiến lược
S2_DSR_TOP_MIN = 3                  # ... nhưng ít nhất 3 alpha mỗi chiến lược (nếu có)
S2_NEIGHBOUR_MIN_PROFIT_RATIO = 0.60   # >= 60% điểm lân cận (±1 bước mỗi khoá) có lãi trên dev1 (cổng cứng)
S2_PBO_MAX = 0.5                    # PBO của chiến lược (CSCV) > 0,5 -> CẢNH BÁO (pbo_flag) ghi vào số đo, không loại
S2_PBO_BLOCKS = 16                  # số khối của CSCV (C(16,8) = 12.870 cách chia)
S2_PBO_MAX_ALPHAS = 2000            # > 2000 alpha: chỉ lấy 2000 alpha điểm IS cao nhất cho ma trận PBO
S2_PBO_MIN_ALPHAS = 4               # ít hơn: không đủ alpha để xếp hạng -> không đo PBO (không gắn cờ)
S2_EFF_SAMPLE = 600                 # số alpha điểm cao nhất dùng để ước lượng N hiệu dụng của DSR (carlo.effective_trials)

# ── S3: walk-forward danh mục trên dev2 với tham số CỐ ĐỊNH ────────────────
S3_TRAIN_DAYS = 120
S3_TEST_DAYS = 30
S3_MIN_FOLDS = 5                    # tối thiểu số fold
S3_MIN_TRADED_FOLDS = 3             # tối thiểu số fold có lệnh (fold 0 lệnh trung tính)
S3_MIN_FOLD_T = 1.0                 # t-stat lãi TB/fold OOS (fold có lệnh) >= 1 — thay cổng "tỉ lệ fold lãi >= 60%" (sai với lãi lệch phải)
S3_MIN_EX_BEST_FOLD_PCT = -2.0      # bỏ fold OOS tốt nhất, lãi kép còn lại >= -2% (không dựa vào một fold may mắn)
S3_MIN_COMPOUNDED_OOS_PCT = 0.0     # lãi kép OOS phải > 0
S3_MAX_FOLD_MDD_PCT = 30.0          # MDD fold OOS xấu nhất tối đa
S3_MIN_AVG_IS_RET_PCT = 0.0         # lãi IS trung bình các fold >= 0

# ── S4: Monte Carlo trên chuỗi ngày OOS (cơ sở "extreme") ──────────────────
S4_MIN_SIMULATIONS = 10_000         # >= 10.000 kịch bản bootstrap (= carlo.carlo.MC_MIN_SIMULATIONS)
S4_RUIN_THRESHOLD_PCT = 30.0        # "cháy" = MDD >= 30%
S4_MAX_RUIN_PCT = 5.0               # P(MDD >= 30% trong 1 năm) <= 5%
S4_STRESS_MAX_MDD_PCT = 50.0        # MỌI kịch bản cực xấu: MDD < 50% và không chạm vốn 0
S4_MIN_DAYS = 20                    # ít hơn ngần này ngày OOS thì không đủ để bootstrap
S4_BLOCK_DAYS = 5
S4_HORIZON_DAYS = 365
S4_SEED = 1

# ── S5: khối lượng sống sót ─────────────────────────────────────────────────
S5_S_MIN = 0.2                      # s < 0,2 -> loại
S5_S_MAX = 3.0                      # rủi ro/lệnh tối đa 1,5% (= 0,5% × 3); trước 04/10/2026 là 1,0 (alpha FINAL đều chạm trần, MC còn dư nhiều)
S5_TOLERANCE = 0.01                 # dung sai tìm nhị phân
S5_CONFIRM_STEP = 0.05              # xác nhận trượt (backtest/WFA/MC thật ở s) -> hạ s thêm từng bước này rồi xác nhận lại (khi s <= 1)
S5_CONFIRM_REL_STEP = 0.15          # s > 1: hạ 15% mỗi bước (bước tuyệt đối 0,05 quá chậm khi tìm trên [0,2; 3])
S5_CONFIRM_MAX_TRIES = 8

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
    "S2.pbo": "PBO của chiến lược > 0,5 (cổng cũ, trước 03/10/2026)",
    "S2.dsr": "DSR < 0,95 (cổng cũ, trước 03/10/2026)",
    "S2.dsr_rank": "DSR ngoài top 5% của chiến lược",
    "S2.neighbor": "Lân cận tham số có lãi < 60%",
    "S3.folds": "Số fold < 5",
    "S3.positive_ratio": "Tỉ lệ fold lãi < 60% (cổng cũ, trước 03/10/2026)",
    "S3.traded_folds": "Quá ít fold có lệnh (< 3)",
    "S3.fold_t": "Lãi theo fold không đủ ý nghĩa (t < 1)",
    "S3.ex_best": "Bỏ fold tốt nhất thì lỗ > 2%",
    "S3.oos_compound": "Lãi kép OOS ≤ 0",
    "S3.worst_fold_mdd": "MDD fold xấu nhất > 30%",
    "S3.avg_is": "Lãi IS trung bình < 0",
    "S4.days": "Quá ít ngày OOS để chạy Monte Carlo",
    "S4.simulations": "Số kịch bản Monte Carlo < 10.000",
    "S4.p_mdd": "P(MDD ≥ 30%) > 5% (kể cả ở khối lượng tối thiểu)",
    "S4.stress_mdd": "Kịch bản cực xấu MDD ≥ 50%",
    "S4.stress_ruin": "Kịch bản cực xấu chạm vốn 0",
    "S4.stress_measured": "Có kịch bản cực xấu không đo được (thiếu vòng quay đo từ lệnh)",
    "S5.stress_measured": "Có kịch bản cực xấu không đo được (thiếu vòng quay đo từ lệnh)",
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


# ── Chống ăn may: DSR (S4) / lân cận (S3) ───────────────────────────────────
def dsr_cut(dsrs: List[float]) -> Optional[float]:
    """Ngưỡng DSR để vào top của chiến lược: giá trị thứ k = max(S2_DSR_TOP_MIN, ceil(S2_DSR_TOP_FRAC × n)) khi xếp giảm dần.
    Không có alpha -> None. Hoà điểm ở ngưỡng: mọi alpha bằng ngưỡng đều đi tiếp."""
    vals = sorted((float(d) for d in dsrs if d is not None and math.isfinite(d)), reverse=True)
    if not vals:
        return None
    k = min(len(vals), max(S2_DSR_TOP_MIN, math.ceil(S2_DSR_TOP_FRAC * len(vals))))
    return vals[k - 1]


def evaluate_dsr(dsr: Optional[float], cut: Optional[float]) -> Verdict:
    """DSR (N hiệu dụng) trong top của chiến lược (cut = dsr_cut). Chạy ở S4, cùng mã lý do S2.dsr_rank như trước."""
    if dsr is None or cut is None or not dsr >= cut:
        return False, "S2.dsr_rank", _msg("S2.dsr_rank", f"DSR {_fmt(dsr, 3)} < ngưỡng top {_fmt(cut, 3)}")
    return _OK


def evaluate_neighbour(neighbour_ratio: Optional[float]) -> Verdict:
    """Lân cận tham số có lãi >= S2_NEIGHBOUR_MIN_PROFIT_RATIO (None = không có điểm lân cận: qua). Chạy ở S3, cùng mã S2.neighbor.
    PBO không loại (cảnh báo pbo_flag ở số đo)."""
    if neighbour_ratio is not None and neighbour_ratio < S2_NEIGHBOUR_MIN_PROFIT_RATIO:
        return False, "S2.neighbor", _msg("S2.neighbor", f"{_fmt(neighbour_ratio * 100, 0)}% < {_fmt(S2_NEIGHBOUR_MIN_PROFIT_RATIO * 100, 0)}%")
    return _OK


# ── S3 ──────────────────────────────────────────────────────────────────────
def evaluate_s3(s: Dict[str, Any]) -> Verdict:
    """s = {folds, traded_folds, compounded_oos_ret_pct, fold_t, oos_ex_best_pct, worst_fold_mdd, is_ret_avg} (aggregate_wfa;
    fold_t / oos_ex_best_pct / traded_folds: wfa.wfa.fold_stats). Thứ tự: số fold, fold có lệnh, lãi kép OOS, t theo fold,
    bỏ fold tốt nhất, MDD fold, lãi IS. positive_ratio vẫn có trong số đo để xem nhưng KHÔNG còn là cổng (lãi lệch phải)."""
    if s["folds"] < S3_MIN_FOLDS:
        return False, "S3.folds", _msg("S3.folds", f"{s['folds']} < {S3_MIN_FOLDS}")
    if s.get("traded_folds", s["folds"]) < S3_MIN_TRADED_FOLDS:
        return False, "S3.traded_folds", _msg("S3.traded_folds", f"{s.get('traded_folds')} < {S3_MIN_TRADED_FOLDS}")
    if not s["compounded_oos_ret_pct"] > S3_MIN_COMPOUNDED_OOS_PCT:
        return False, "S3.oos_compound", _msg("S3.oos_compound", f"{_fmt(s['compounded_oos_ret_pct'])}%")
    if not s.get("fold_t", 0.0) >= S3_MIN_FOLD_T:
        return False, "S3.fold_t", _msg("S3.fold_t", f"t = {_fmt(s.get('fold_t'))} < {_fmt(S3_MIN_FOLD_T)}")
    if not s.get("oos_ex_best_pct", 0.0) >= S3_MIN_EX_BEST_FOLD_PCT:
        return False, "S3.ex_best", _msg("S3.ex_best", f"{_fmt(s.get('oos_ex_best_pct'))}% < {_fmt(S3_MIN_EX_BEST_FOLD_PCT)}%")
    if s["worst_fold_mdd"] > S3_MAX_FOLD_MDD_PCT:
        return False, "S3.worst_fold_mdd", _msg("S3.worst_fold_mdd", f"{_fmt(s['worst_fold_mdd'])}% > {_fmt(S3_MAX_FOLD_MDD_PCT)}%")
    if s["is_ret_avg"] is None or s["is_ret_avg"] < S3_MIN_AVG_IS_RET_PCT:
        return False, "S3.avg_is", _msg("S3.avg_is", f"{_fmt(s['is_ret_avg'])}%")
    return _OK


# ── S4 ──────────────────────────────────────────────────────────────────────
def evaluate_mc_checks(gate: Dict[str, Any], prefix: str = "S4") -> Verdict:
    """gate = evaluate_mc_gate(...) của backend.carlo.carlo (5 check). Trả lý do của check trượt đầu tiên."""
    ch = gate["checks"]
    order = (("simulations", f"{prefix}.simulations"), ("ruin", f"{prefix}.p_mdd"), ("stress_mdd", f"{prefix}.stress_mdd"),
             ("stress_ruin", f"{prefix}.stress_ruin"), ("stress_measured", f"{prefix}.stress_measured"))
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


def compute_windows(symbols: List[str], override: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """{"start", "dev1_end", "dev2_end", "end"} (ms UTC). Mặc định: start = max(đầu dữ liệu) + WARMUP, end = min(cuối dữ liệu),
    dev1 = 40% đầu, dev2 = 40% tiếp, holdout = 20% cuối. `override` ({khoá: "YYYY-MM-DD"}) ghi đè từng mốc; mốc phải tăng dần."""
    from backend.crawl.store import read_manifest
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
        w[k] = date_ms(v)
    if not (w["start"] < w["dev1_end"] < w["dev2_end"] < w["end"]):
        raise ValueError("windows: phải có start < dev1_end < dev2_end < end")
    return w


def windows_iso(w: Dict[str, int]) -> Dict[str, str]:
    return {k: iso_date(v) for k, v in w.items()}


def wfa_folds(w: Dict[str, int], train_days: Optional[int] = None, test_days: Optional[int] = None) -> List[Dict[str, int]]:
    """Fold WFA trên dev2 (dev1_end -> dev2_end), OOS liền nhau không chồng lấp."""
    from backend.wfa.wfa import generate_folds
    return generate_folds(int(w["dev1_end"]), int(w["dev2_end"]), train_days or S3_TRAIN_DAYS, test_days or S3_TEST_DAYS)


# ══════════════════════════════════════════════════════════════════════════
# Khối lượng sống sót (S5): tìm nhị phân hệ số vốn s ∈ [S_MIN, S_MAX] rồi XÁC NHẬN bằng chạy thật ở s.
#
# Quy đổi s -> khối lượng thật: các chiến lược của sổ dùng sizing="risk" (khối lượng = vốn × risk_per_trade% / (SL% + chi phí)), nên
# `risk_per_trade_pct = BASE_RISK_PER_TRADE_PCT × s` làm khối lượng (qty) mọi lệnh tỉ lệ với s. Với sizing="margin_pct" thì nhân
# `order_size_pct` với s (cùng ý nghĩa). Không tuyệt đối tỉ lệ vì trần danh nghĩa (max_notional_pct), trần tổng danh nghĩa của danh mục và
# đòn bẩy tối đa chặn lệnh lớn -> lợi suất ngày ở size s không đúng bằng s × lợi suất ngày ở s = 1. Vì thế tìm nhị phân trên chuỗi ngày nhân s chỉ cho
# ứng viên; kết luận chỉ khi chạy lại backtest + WFA + Monte Carlo THẬT ở s qua (xác nhận); trượt thì hạ s từng bước rồi xác nhận lại.
# ══════════════════════════════════════════════════════════════════════════

Check = Callable[[float], Dict[str, Any]]   # s -> {"passed": bool, "p_mdd_ge_30": %, "stress_max_mdd": %}


def floor_scale(s: float, step: float = 0.01) -> float:
    """Làm tròn XUỐNG theo bước 0,01 (không bao giờ vượt mức đã kiểm)."""
    return round(math.floor(s / step + 1e-9) * step, 2)


def scale_position(position: Dict[str, Any], s: float) -> Dict[str, Any]:
    """Bản sao `position` với khối lượng nhân s (xem docstring module)."""
    out = dict(position)
    if str(out.get("sizing") or "margin_pct").lower() == "risk":
        out["risk_per_trade_pct"] = round(float(out.get("risk_per_trade_pct") or BASE_RISK_PER_TRADE_PCT) * s, 6)
    else:
        out["order_size_pct"] = round(float(out.get("order_size_pct") if out.get("order_size_pct") is not None else 100.0) * s, 6)
    return out


def risk_for_scale(s: float) -> float:
    """Rủi ro/lệnh (% vốn) ở hệ số s cho các chiến lược của sổ (sizing="risk")."""
    return round(BASE_RISK_PER_TRADE_PCT * s, 6)


def search_scale(check: Check, lo: Optional[float] = None, hi: Optional[float] = None, tol: Optional[float] = None
                 ) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Hệ số s lớn nhất ∈ [lo, hi] mà check(s)["passed"] (giả định đơn điệu: s nhỏ hơn luôn dễ qua hơn). -> (s hoặc None, các bước).
    Thử hi trước (qua -> xong), rồi lo (trượt -> None = s < lo), rồi chia đôi tới khi hi - lo <= tol. s trả về = lo đã qua, làm tròn xuống 0,01."""
    lo = S5_S_MIN if lo is None else lo
    hi = S5_S_MAX if hi is None else hi
    tol = S5_TOLERANCE if tol is None else tol
    steps: List[Dict[str, Any]] = []

    def probe(s: float) -> bool:
        r = check(s)
        steps.append({"s": round(s, 4), "passed": bool(r["passed"]), "p_mdd_ge_30": r.get("p_mdd_ge_30"), "stress_max_mdd": r.get("stress_max_mdd")})
        return bool(r["passed"])

    if probe(hi):
        return floor_scale(hi), steps
    if not probe(lo):
        return None, steps
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if probe(mid):
            lo = mid
        else:
            hi = mid
    return floor_scale(lo), steps


def confirm_with_stepdown(s0: float, confirm: Callable[[float], Dict[str, Any]], step: Optional[float] = None,
                          max_tries: Optional[int] = None, s_min: Optional[float] = None) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Xác nhận ở s0; trượt thì hạ s (s <= 1: trừ step; s > 1: nhân (1 − S5_CONFIRM_REL_STEP)), tối đa max_tries lần thử, s không xuống
    dưới s_min. confirm(s) -> {"passed": bool, ...}.
    -> (s đã xác nhận hoặc None, các lần thử [{s, passed, ...}]). Hết lượt/ s < s_min -> None."""
    step = S5_CONFIRM_STEP if step is None else step
    max_tries = S5_CONFIRM_MAX_TRIES if max_tries is None else max_tries
    s_min = S5_S_MIN if s_min is None else s_min
    attempts: List[Dict[str, Any]] = []
    s = s0
    for _ in range(max_tries):
        if s < s_min - 1e-9:
            break
        r = confirm(s)
        attempts.append({"s": s, **r})
        if r["passed"]:
            return s, attempts
        s = round(s - step, 4) if s <= 1.0 + 1e-9 else max(1.0, round(s * (1.0 - S5_CONFIRM_REL_STEP), 2))
    return None, attempts


# ══════════════════════════════════════════════════════════════════════════
# Thống kê một tầng (docs/funnel_contract.md §3): nhóm vào/ra, lý do loại, theo chiến lược, sống sót theo tham số, top alpha.
#
# Chỉ đọc kho SQLite bằng truy vấn tổng hợp (GROUP BY) hoặc duyệt streaming các cột số -> bộ nhớ O(số alpha × 8 byte × 7 cột) dù tới 1.000.000 alpha.
# `in` = nhóm được chấm ở tầng (đã có số đo tầng đó), `out` = phần qua. Mọi phân phối dùng CÙNG 30 bin cố định chia đều khoảng phân vị 1–99 của nhóm `in`
# (giá trị ngoài khoảng được dồn vào bin đầu/cuối nên tổng số đếm = quy mô nhóm).
# ══════════════════════════════════════════════════════════════════════════

N_BINS = 30
P_LO, P_HI = 1, 99
TOP_N = 20


def r3(x: Any) -> Optional[float]:
    return num_or_none(x, 3)


def scalar_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
    """Chỉ giữ giá trị vô hướng của metrics_json (bỏ danh sách/dict lớn như fold_detail, by_symbol)."""
    return {k: v for k, v in m.items() if isinstance(v, (int, float, bool, str)) or v is None}


def make_edges(vals: np.ndarray) -> Optional[np.ndarray]:
    v = vals[np.isfinite(vals)]
    if v.size == 0:
        return None
    lo, hi = float(np.percentile(v, P_LO)), float(np.percentile(v, P_HI))
    if not hi > lo:
        pad = max(abs(lo) * 1e-6, 1e-6)
        lo, hi = lo - pad, hi + pad
    return np.linspace(lo, hi, N_BINS + 1)


def histogram(vals: np.ndarray, edges: Optional[np.ndarray]) -> Dict[str, Any]:
    v = vals[np.isfinite(vals)]
    missing = int(vals.size - v.size)   # không xác định (None): PF khi không có lệnh thua, win rate khi 0 lệnh... — không vào histogram
    if edges is None:
        return {"bins": [], "n": int(v.size), "n_missing": missing, "p5": None, "p50": None, "p95": None}
    counts, _ = np.histogram(np.clip(v, edges[0], edges[-1]), bins=edges)
    out = {"bins": [{"lo": r3(edges[i]), "hi": r3(edges[i + 1]), "count": int(counts[i])} for i in range(N_BINS)], "n": int(v.size), "n_missing": missing}
    for name, q in (("p5", 5), ("p50", 50), ("p95", 95)):
        out[name] = r3(np.percentile(v, q)) if v.size else None
    return out


def _fetch_numeric(store: RunStore, stage: str):
    cols = ("m.passed", "m.ret_pct", "m.mdd_pct", "m.sharpe", "m.trades", "m.win_rate", "m.profit_factor", "m.score")
    strat: List[str] = []
    data: List[List[float]] = [[] for _ in cols]
    with store._lock:
        cur = store._con.cursor()
        cur.execute(f"SELECT a.strategy, {', '.join(cols)} FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id WHERE m.stage=?", (stage,))
    while True:
        with store._lock:
            batch = cur.fetchmany(20000)
        if not batch:
            break
        for row in batch:
            strat.append(row[0])
            for i, x in enumerate(row[1:]):
                data[i].append(float("nan") if x is None else float(x))
    arr = {c.split(".")[1]: np.asarray(d, dtype=float) for c, d in zip(cols, data)}
    return np.asarray(strat, dtype=object), arr


def stage_stats(store: RunStore, stage: str, top_n: int = TOP_N) -> Dict[str, Any]:
    if stage not in ALL_STAGE_IDX:
        raise KeyError(stage)
    counts = next((c for c in store.stage_counts() if c["stage"] == stage), None)
    if counts is None:   # tầng cũ S2_antiluck chỉ có trong kho của lượt chạy trước 08/10/2026
        raise KeyError(stage)
    out: Dict[str, Any] = {"stage": stage, "label": STAGE_LABELS[stage], "input": counts["done"], "eligible": counts["input"],
                           "passed": counts["passed"], "rejected": counts["rejected"]}
    with store._lock:
        reasons = store._con.execute("SELECT reject_code, COUNT(*) FROM alphas WHERE rejected_stage=? GROUP BY reject_code ORDER BY COUNT(*) DESC, reject_code",
                                     (stage,)).fetchall()
    out["reject_reasons"] = [{"code": c, "label": reason_label(c), "count": int(n)} for c, n in reasons]

    if stage == "S0_generate":
        return {**out, **_stats_s0(store, top_n)}

    strat, a = _fetch_numeric(store, stage)
    passed = a["passed"] == 1
    dists: Dict[str, Any] = {}
    for key in DIST_KEYS:
        v = a[key]
        edges = make_edges(v)
        dists[key] = {"in": histogram(v, edges), "out": histogram(v[passed], edges)}
    out["distributions"] = dists

    by = []
    best_pass = _best_per_strategy(store, stage, True)
    best_any = _best_per_strategy(store, stage, False)
    for s in sorted(set(strat.tolist())):
        sel = strat == s
        n_in, n_pass = int(sel.sum()), int((sel & passed).sum())
        by.append({"strategy": s, "input": n_in, "passed": n_pass, "pass_rate": round(n_pass / n_in * 100, 1) if n_in else 0.0,
                   "median_ret_pct": r3(np.nanmedian(a["ret_pct"][sel])) if n_in else None,
                   "median_mdd_pct": r3(np.nanmedian(a["mdd_pct"][sel])) if n_in else None,
                   "best_alpha_id": best_pass.get(s) or best_any.get(s)})
    out["by_strategy"] = by
    out["param_survival"] = _param_survival(store, stage)
    out["top"] = _top(store, stage, top_n)
    if stage in ("S3_wfa", LEGACY_STAGE):   # số liệu mức chiến lược (N hiệu dụng, phương sai Sharpe, PBO, ngưỡng top DSR); lượt cũ lưu ở khoá "s2:"
        out["strategy_level"] = {s: store.get_kv(f"{STRATEGY_LEVEL_KEY}{s}") or store.get_kv(f"s2:{s}") for s in sorted(set(strat.tolist()))}
    return out


def _best_per_strategy(store: RunStore, stage: str, only_passed: bool) -> Dict[str, str]:
    q = ("SELECT a.strategy, m.alpha_id, MAX(m.score) FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id WHERE m.stage=? "
         + ("AND m.passed=1 " if only_passed else "") + "AND m.score IS NOT NULL GROUP BY a.strategy")
    with store._lock:
        return {s: a for s, a, _ in store._con.execute(q, (stage,)).fetchall()}


def _param_survival(store: RunStore, stage: str) -> List[Dict[str, Any]]:
    """Mỗi (chiến lược, tham số, giá trị): số alpha vào / số qua. Gộp theo params_json trong SQL (số tổ hợp <= kích thước lưới) rồi cộng dồn theo giá trị."""
    if stage == "S0_generate":
        q = "SELECT strategy, params_json, COUNT(*), SUM(CASE WHEN rejected_idx IS NULL THEN 1 ELSE 0 END) FROM alphas GROUP BY strategy, params_json"
        args: tuple = ()
    else:
        q = ("SELECT a.strategy, a.params_json, COUNT(*), SUM(m.passed) FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
             "WHERE m.stage=? GROUP BY a.strategy, a.params_json")
        args = (stage,)
    acc: Dict[tuple, List[int]] = defaultdict(lambda: [0, 0])
    with store._lock:
        rows = store._con.execute(q, args).fetchall()
    for s, pj, n, p in rows:
        for key, val in json.loads(pj).items():
            c = acc[(s, key, json.dumps(val))]
            c[0] += n
            c[1] += int(p or 0)
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for (s, key, vj), (n, p) in acc.items():
        grouped[(s, key)].append({"value": json.loads(vj), "input": n, "passed": p})
    out = []
    for (s, key) in sorted(grouped):
        vals = sorted(grouped[(s, key)], key=lambda x: (not isinstance(x["value"], (int, float)), x["value"] if isinstance(x["value"], (int, float)) else str(x["value"])))
        out.append({"strategy": s, "param": key, "values": vals})
    return out


def _top(store: RunStore, stage: str, n: int) -> List[Dict[str, Any]]:
    with store._lock:
        rows = store._con.execute(
            "SELECT m.alpha_id, a.strategy, a.params_json, m.metrics_json, a.final_scale FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
            "WHERE m.stage=? AND m.passed=1 ORDER BY m.score IS NULL, m.score DESC, a.ord LIMIT ?", (stage, int(n))).fetchall()
    return [{"alpha_id": a, "strategy": s, "params": json.loads(p), "metrics": scalar_metrics(json.loads(m)), "final_scale": fs} for a, s, p, m, fs in rows]


def _stats_s0(store: RunStore, top_n: int) -> Dict[str, Any]:
    with store._lock:
        rows = store._con.execute("SELECT strategy, COUNT(*), SUM(CASE WHEN rejected_idx IS NULL THEN 1 ELSE 0 END) FROM alphas GROUP BY strategy ORDER BY strategy").fetchall()
    best = _best_per_strategy(store, "S1_backtest", False)
    by = [{"strategy": s, "input": int(n), "passed": int(p), "pass_rate": round(p / n * 100, 1) if n else 0.0,
           "median_ret_pct": None, "median_mdd_pct": None, "best_alpha_id": best.get(s)} for s, n, p in rows]
    top = []
    with store._lock:
        trows = store._con.execute(
            "SELECT m.alpha_id, a.strategy, a.params_json, m.metrics_json, a.final_scale FROM stage_metrics m JOIN alphas a ON a.alpha_id=m.alpha_id "
            "WHERE m.stage='S1_backtest' ORDER BY m.score IS NULL, m.score DESC, a.ord LIMIT ?", (int(top_n),)).fetchall()
    for a, s, p, m, fs in trows:
        top.append({"alpha_id": a, "strategy": s, "params": json.loads(p), "metrics": scalar_metrics(json.loads(m)), "final_scale": fs})
    return {"distributions": {}, "by_strategy": by, "param_survival": _param_survival(store, "S0_generate"), "top": top}


# ══════════════════════════════════════════════════════════════════════════
# Ước tính thời gian S1 của phễu từ SỐ ĐO THẬT của các lượt đã chạy (không hằng số "đo sẵn").
#
# Mỗi lượt xong ghi run.json: stages.S1_backtest.{wall_s, input} (thời gian tường và số alpha thật sự được chấm ở S1) và `workers`
# (từ P9.13; lượt cũ không có thì đọc dòng "run_id ... | workers=N" trong out.log của job). Số đo = worker-giây mỗi backtest
# = wall_s × workers / input (giả định các worker bận gần hết thời gian S1 — chính là cách S1 chạy: pool_imap_bounded kín việc).
#
# Chỉ dùng lượt cùng khung chạy (`timeframe`) và cùng chế độ regime: khác nhau thì giây/backtest khác hẳn (15m vs 1m, regime=learn chạy thêm một lượt
# quan sát) -> không ngoại suy. Không có lượt khớp -> sec_per_backtest = None + lý do (giao diện hiện "chưa có số đo"). Không có file bench
# nào được lưu nên không có đường dự phòng khác: chỉ số đo thật.
# ══════════════════════════════════════════════════════════════════════════

MAX_REF_RUNS = 8
_WORKERS_RE = re.compile(r"^run_id\s+\S+\s*\|.*\bworkers=(\d+)", re.M)


def _workers_of(run: Dict[str, Any], jobs_root: Optional[str], funnel_root: Optional[str] = None) -> Optional[int]:
    w = run.get("workers")
    if isinstance(w, int) and not isinstance(w, bool) and w > 0:
        return w
    job_id = run.get("job_id")
    if not job_id or not jobs_root or not re.fullmatch(r"[0-9A-Za-z_-]{3,64}", str(job_id)):
        return None
    head = None
    for root in (jobs_root, funnel_root):   # job xong: log đã được lưu cạnh kết quả (alpha/funnel/<job_id>/out.log, ADR §4.2)
        try:
            with open(os.path.join(root, str(job_id), "out.log"), encoding="utf-8", errors="replace") as fh:
                head = fh.read(20000)
            break
        except (OSError, TypeError):
            continue
    if head is None:
        return None
    m = _WORKERS_RE.search(head)
    return int(m.group(1)) if m else None


def measured_s1_rate(funnel_root: str, timeframe: str, regime: str = "off", jobs_root: Optional[str] = None,
                     limit: int = MAX_REF_RUNS) -> Dict[str, Any]:
    """-> {"sec_per_backtest": trung vị worker-giây/backtest | None, "n_runs", "runs": [{run_id, wall_s, input, workers, sec_per_backtest}],
    "reason": None | lý do không có số đo}."""
    rows: List[Dict[str, Any]] = []
    try:
        names = os.listdir(funnel_root)
    except OSError:
        names = []
    skipped_workers = 0
    for name in names:
        run = read_json(os.path.join(funnel_root, name, "run.json"))
        if not isinstance(run, dict) or not run or run.get("status") != "done":
            continue
        cfg = run.get("config") or {}
        if (cfg.get("timeframe") or "1m") != timeframe or (cfg.get("regime") or "off") != (regime or "off"):
            continue
        s1 = (run.get("stages") or {}).get("S1_backtest") or {}
        wall, n = s1.get("wall_s"), s1.get("input")
        if s1.get("status") != "done" or not isinstance(wall, (int, float)) or not isinstance(n, (int, float)) or wall <= 0 or n <= 0:
            continue
        workers = _workers_of(run, jobs_root, funnel_root)
        if workers is None:
            skipped_workers += 1
            continue
        rows.append({"run_id": run.get("run_id") or name, "finished": run.get("finished") or 0, "wall_s": float(wall), "input": int(n),
                     "workers": workers, "sec_per_backtest": float(wall) * workers / int(n)})
    rows.sort(key=lambda r: r["finished"], reverse=True)
    rows = rows[:limit]
    if not rows:
        why = f"chưa có lượt phễu đã xong nào ở khung {timeframe}, regime={regime or 'off'}" + (
            f" ({skipped_workers} lượt khớp nhưng không biết số worker)" if skipped_workers else "")
        return {"sec_per_backtest": None, "n_runs": 0, "runs": [], "reason": why}
    return {"sec_per_backtest": statistics.median(r["sec_per_backtest"] for r in rows), "n_runs": len(rows),
            "runs": [{k: v for k, v in r.items() if k != "finished"} for r in rows], "reason": None}


# ══════════════════════════════════════════════════════════════════════════
# Điều phối phễu S0 → FINAL: tầng chạy TUẦN TỰ, mỗi tầng STREAMING (job sinh lười -> pool_imap_bounded -> lô kết quả ghi ngay vào kho).
#
# - RAM cha phẳng: chỉ giữ một lô (FLUSH_N alpha) + các trang `pending` (1000 hàng); worker trả dict thuần dữ liệu.
# - RESUME theo run_id: kho là sổ cam kết (xem storage.py). Chạy lại = mỗi tầng chỉ chấm alpha chưa có hàng stage_metrics của tầng đó.
# - Chống ăn may là CHÉO alpha: số liệu mức chiến lược (N lần thử, phương sai Sharpe, PBO, ngưỡng top DSR) tính một lần/chiến lược ở đầu S3 và lưu vào bảng kv
#   (resume / S4 không tính lại); S3 dùng PBO + lân cận, S4 dùng N hiệu dụng + ngưỡng DSR.
# - Tiến độ/ETA: backend.optimize.process.process.Progress (progress.json mỗi <= 5 giây, cũng ghi vào $NORA_JOB_DIR để API hiển thị).
# ══════════════════════════════════════════════════════════════════════════

PER_WORKER_MB = 800            # đo thực (P1.8, 10k alpha schema, 8 tài sản): RAM riêng mỗi worker đỉnh ~715 MB; nền giá dùng chung qua mmap
GEN_BATCH = 5000               # alpha ghi mỗi giao dịch ở S0
PAGE = 1000                    # số alpha nạp mỗi lần từ `pending`
FLUSH_SECONDS = 20.0
FLUSH_N = {"S1_backtest": 200, "S3_wfa": 8, "S4_montecarlo": 16, "S5_sizing": 4, "S6_holdout": 8, "FINAL": 2000}
MAX_ALPHAS_DEFAULT = 1_000_000


@dataclass
class FunnelConfig:
    strategies: List[str]
    n_per_strategy: Optional[int] = None
    full_grid: bool = False
    seed: int = 7
    symbols: Optional[List[str]] = None            # mặc định cả vũ trụ (perp)
    windows: Optional[Dict[str, str]] = None       # ghi đè mốc YYYY-MM-DD: start, dev1_end, dev2_end, end
    train_days: int = S3_TRAIN_DAYS
    test_days: int = S3_TEST_DAYS
    space: str = "grid"                            # grid = lưới nhỏ `space`; schema = toàn bộ params_schema (quy mô lớn)
    timeframe: str = "1m"                          # khung chạy (nến mô phỏng): 15m / 1h / 4h nhanh hơn 1m hàng chục lần; khung tín hiệu >= khung này
    regime: str = "off"                            # off | learn | both (generate.regime_variants): biến thể regime là alpha riêng -> DSR/PBO đếm đủ

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def new_run_id() -> str:
    import uuid
    return f"fr-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def funnel_root() -> str:
    from backend.crawl.store import alpha_run_dir
    path = alpha_run_dir("funnel")
    os.makedirs(path, exist_ok=True)
    return path


def git_info() -> Dict[str, Any]:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", root, "status", "--porcelain", "backend"], capture_output=True, text=True, timeout=10).stdout.strip())
        return {"commit": head or None, "dirty_backend": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty_backend": None}


def _candidates(strategies: List[str]) -> Dict[str, Dict[str, Any]]:
    from backend.optimize.book.build import BY_ID
    by_id = BY_ID
    bad = [s for s in strategies if s not in by_id]
    if bad:
        raise ValueError(f"không có chiến lược {bad}; có: {sorted(by_id)}")
    return {s: by_id[s] for s in strategies}


def planned_alphas(cfg: FunnelConfig) -> Dict[str, int]:
    cands = _candidates(cfg.strategies)
    k = len(regime_variants({}, cfg.regime))
    return {s: k * count_params(space_for(c, cfg.space, cfg.timeframe), cfg.n_per_strategy, cfg.full_grid) for s, c in cands.items()}


# ── Bối cảnh chạy ───────────────────────────────────────────────────────────
class Ctx:
    def __init__(self, store: RunStore, cfg: FunnelConfig, windows: Dict[str, int], workers: int, progress: Progress, log: Callable[[str], None]):
        self.store, self.cfg, self.windows, self.workers, self.progress, self.log = store, cfg, windows, workers, progress, log
        self.serial = workers <= 0
        self.shared_dir = None if self.serial else os.path.join(store.run_dir, "_shared")
        self.symbols = list(cfg.symbols)
        self.base_frame = cfg.timeframe
        self.cands = _candidates(cfg.strategies)
        self.exporter = SharedExporter(self.shared_dir, "funnel", workers, to_job=bt.to_job)
        self.folds = bt.fold_job_plan(wfa_folds(windows, cfg.train_days, cfg.test_days))

    def imap(self, fn: Callable, jobs: Iterable, label: str) -> Iterator[Tuple[int, Any]]:
        if self.serial:
            return ((i, fn(j)) for i, j in enumerate(jobs))
        from backend.optimize.process.workers import pool_imap_bounded
        return pool_imap_bounded(fn, jobs, self.workers, label, self.workers * 4)

    def s1_job(self, strategy: str, params: Dict[str, Any], rpt: float = BASE_RISK_PER_TRADE_PCT, trades: Any = False) -> Dict[str, Any]:
        w = self.windows
        return {**bt.base_job(strategy, params, (w["start"], w["dev1_end"]), "level", False, rpt, self.symbols, self.shared_dir,
                             self.base_frame), "trades": trades}

    def tick(self, worker_peak_mb: Optional[float] = None) -> None:
        self.progress.tick(worker_peak_mb=worker_peak_mb)


def _stream(ctx: Ctx, stage: str, pages: Iterator[Dict[str, Any]], make_job: Callable[[Dict[str, Any]], Dict[str, Any]], fn: Callable,
            on_result: Callable[[Dict[str, Any], Any], StageResult], neighbours: bool = False) -> int:
    """Khung dùng chung: `pages` yield hàng alpha (lười) -> job -> pool -> on_result -> lô -> commit. -> số alpha đã chấm."""
    pending: Dict[int, Dict[str, Any]] = {}
    batch: List[StageResult] = []
    flush_n = FLUSH_N.get(stage, 100)
    t_flush = time.time()
    t_log = time.time()
    done = 0

    def feeder():
        for n, row in enumerate(pages):
            pending[n] = row
            yield make_job(row)

    for i, res in ctx.imap(fn, feeder(), f"[{stage}]"):
        row = pending.pop(i)
        batch.append(on_result(row, res))
        done += 1
        ctx.tick()
        if len(batch) >= flush_n or time.time() - t_flush > FLUSH_SECONDS:
            ctx.store.commit_results(batch, neighbours=neighbours)
            batch, t_flush = [], time.time()
        if time.time() - t_log > 30:
            snap = ctx.progress.snapshot()
            ctx.log(f"[{stage}] {snap['done']}/{snap['total']}  ETA {_fmt_eta(snap.get('eta_s'))}")
            t_log = time.time()
    if batch:
        ctx.store.commit_results(batch, neighbours=neighbours)
    return done


GROUP_MAX = 50        # số alpha tối đa mỗi nhóm run_many (cân tải giữa worker)
GROUP_LOOKAHEAD = 2000   # gom nhóm trong cửa sổ trượt này của hàng chờ (alpha sinh ngẫu nhiên hiếm khi liền kề cùng tín hiệu)


def _stream_grouped(ctx: Ctx, stage: str, pages: Iterator[Dict[str, Any]], make_job: Callable[[Dict[str, Any]], Dict[str, Any]],
                    on_result: Callable[[Dict[str, Any], Any], StageResult]) -> int:
    """Như _stream nhưng mỗi job pool là một NHÓM alpha cùng signal_key (evaluate.w_backtest_group -> run_many): dữ liệu + tín hiệu nạp một
    lần cho cả nhóm. Kết quả từng alpha giống hệt chạy riêng; lô ghi / resume theo từng alpha như _stream."""
    pending: Dict[int, List[Dict[str, Any]]] = {}
    batch: List[StageResult] = []
    flush_n = FLUSH_N.get(stage, 100)
    t_flush = time.time()
    t_log = time.time()
    done = 0

    def feeder():
        buf: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
        held = 0
        n = 0

        def emit(key):
            nonlocal held, n
            items = buf.pop(key)
            held -= len(items)
            pending[n] = [row for row, _ in items]
            n += 1
            if items:
                ctx.exporter.ensure([items[0][1]])
            return {"jobs": [job for _, job in items]}

        for row in pages:
            job = make_job(row)
            key = bt.signal_key(job)
            buf.setdefault(key, []).append((row, job))
            held += 1
            if len(buf[key]) >= GROUP_MAX:
                yield emit(key)
            elif held >= GROUP_LOOKAHEAD:
                yield emit(max(buf, key=lambda k: len(buf[k])))
        for key in list(buf):
            yield emit(key)

    for i, got in ctx.imap(bt.w_backtest_group_rss, feeder(), f"[{stage}]"):
        rows = pending.pop(i)
        for k, (row, res) in enumerate(zip(rows, got["outs"])):
            batch.append(on_result(row, res))
            done += 1
            ctx.tick(got["rss_anon_mb"] if k == 0 else None)
        if len(batch) >= flush_n or time.time() - t_flush > FLUSH_SECONDS:
            ctx.store.commit_results(batch)
            batch, t_flush = [], time.time()
        if time.time() - t_log > 30:
            snap = ctx.progress.snapshot()
            ctx.log(f"[{stage}] {snap['done']}/{snap['total']}  ETA {_fmt_eta(snap.get('eta_s'))}")
            t_log = time.time()
    if batch:
        ctx.store.commit_results(batch)
    return done


def _fmt_eta(s: Optional[float]) -> str:
    if s is None:
        return "?"
    return f"{s:.0f}s" if s < 90 else (f"{s / 60:.1f} phút" if s < 5400 else f"{s / 3600:.1f} giờ")


def _pages(store: RunStore, prev_idx: int, strategy: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    last = -1
    while True:
        rows = store.pending(prev_idx, strategy, after_ord=last, limit=PAGE)
        if not rows:
            return
        for r in rows:
            yield r
        last = rows[-1]["ord"]


def _scalar_base(m: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("ret_pct", "mdd_pct", "sharpe", "sortino", "trades", "win_rate", "profit_factor", "symbols_positive")
    return {k: m[k] for k in keys if k in m}


# ── Từng tầng ───────────────────────────────────────────────────────────────
def check_timeframe(cfg: FunnelConfig) -> None:
    """Khung chạy phải là khung có dữ liệu và mọi chiến lược đã chọn phải có khung tín hiệu >= khung chạy."""
    from backend.alpha.dsl.strategy import FRAME_MS
    from backend.optimize.search.generate import incompatible
    if cfg.timeframe not in FRAME_MS:
        raise ValueError(f"khung chạy không hợp lệ: {cfg.timeframe!r}")
    bad = incompatible(list(_candidates(cfg.strategies).values()), cfg.space, cfg.timeframe)
    if bad:
        raise ValueError(f"chiến lược không chạy được ở khung {cfg.timeframe} (khung tín hiệu tối đa nhỏ hơn khung chạy): "
                         + "; ".join(f"{k} ({', '.join(v)})" for k, v in bad.items()))


def stage_s0(ctx: Ctx) -> None:
    store, cfg = ctx.store, ctx.cfg
    total = sum(planned_alphas(cfg).values())
    ctx.progress.start_stage("S0_generate", total)
    ord_ = 0
    buf: List[Dict[str, Any]] = []
    bad = 0
    for strategy in cfg.strategies:
        cand = ctx.cands[strategy]
        sp = space_for(cand, cfg.space, cfg.timeframe)
        gen = (iter_params_factored(sp, cfg.n_per_strategy, cfg.seed) if cfg.space == "schema" and cfg.n_per_strategy and not cfg.full_grid
               else iter_params(sp, cfg.n_per_strategy, cfg.seed, cfg.full_grid))
        for params in (v for p in gen for v in regime_variants(p, cfg.regime)):
            err = validate_alpha(cand, params, cfg.space, cfg.timeframe)
            row = {"alpha_id": alpha_id_of(strategy, params), "strategy": strategy, "params": params, "ord": ord_}
            if err:
                row.update(reject_code="S0.invalid_params", reject_msg=f"S0.invalid_params: {reason_label('S0.invalid_params')} ({err})")
                bad += 1
            buf.append(row)
            ord_ += 1
            if len(buf) >= GEN_BATCH:
                store.add_alphas(buf)
                ctx.progress.tick(len(buf))
                buf = []
    if buf:
        store.add_alphas(buf)
        ctx.progress.tick(len(buf))
    ctx.log(f"[S0_generate] {ord_} alpha ({bad} không hợp lệ)")


def stage_s1(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S1_backtest", store.count_pending(0))

    def on_result(row, res):
        if "error" in res:
            return StageResult(row["alpha_id"], "S1_backtest", {"error": res["error"]}, False, "S1.error",
                               f"S1.error: {reason_label('S1.error')} ({res['error']})")
        m = res["metrics"]
        ok, code, msg = evaluate_s1(m)
        daily = [("S1_backtest", [{"fold": None, "start": res["daily_start"], "rets": res["daily"]}])]
        trades = [("S1_backtest", res["trades"])] if ok and res["trades"] is not None else []
        return StageResult(row["alpha_id"], "S1_backtest", m, ok, code, msg, trades=trades, daily=daily)

    _stream_grouped(ctx, "S1_backtest", _pages(store, 0), lambda r: ctx.s1_job(r["strategy"], r["params"], trades="pass"), on_result)
    # KHÔNG dọn dữ liệu dùng chung ở đây: S3 chạy các điểm lân cận trên cùng cửa sổ dev1 (S3 dọn).


STRATEGY_LEVEL_KEY = "strategy_level:"   # khoá kv: f"{STRATEGY_LEVEL_KEY}{chiến lược}"


def _dsr_of(m1: Dict[str, Any], info: Dict[str, Any]) -> Dict[str, Any]:
    """DSR của MỘT alpha (số đo S1 m1) với N hiệu dụng + phương sai Sharpe của chiến lược (info) — định nghĩa duy nhất (carlo.deflated_sharpe)."""
    return carlo.deflated_sharpe(m1["sr_daily"], m1["n_days"], m1["skew"], m1["kurt"], info["n_trials"], info["sr_var"])


def _strategy_level(ctx: Ctx, strategy: str) -> Dict[str, Any]:
    """N lần thử, phương sai Sharpe các lần thử, PBO (CSCV) và ngưỡng top DSR của chiến lược — tính từ MỌI alpha đã qua S0 và chạy xong S1
    (cả alpha bị loại ở S1). Tính một lần ở đầu S3 (ma trận lãi ngày dev1 của các lần thử), lưu kv; S4 đọc lại."""
    store = ctx.store
    key = f"{STRATEGY_LEVEL_KEY}{strategy}"
    cached = store.get_kv(key)
    if cached is not None:
        return cached
    srs = [m["sr_daily"] for _, _, m, _ in store.iter_stage_metrics("S1_backtest", strategy) if "sr_daily" in m]
    info: Dict[str, Any] = {"n_trials": len(srs), "n_trials_raw": len(srs), "sr_var": carlo.trial_sr_variance(srs), "pbo": None,
                            "pbo_alphas": 0, "pbo_days": 0}
    ids = store.top_by_score("S1_backtest", strategy, S2_PBO_MAX_ALPHAS)
    if len(ids) >= S2_PBO_MIN_ALPHAS:
        daily = store.read_daily_many(ids, "S1_backtest")
        series = [{"start": rows[0]["start_date"], "rets": rows[0]["rets"]} for a in ids for rows in [daily.get(a)] if rows]
        if len(series) >= S2_PBO_MIN_ALPHAS:
            M = wfa_mod.align_daily(series)
            # N hiệu dụng cho DSR: lần thử gần trùng (lân cận lưới, biến thể regime) không độc lập (carlo.effective_trials)
            info["n_trials"] = carlo.effective_trials(M[:, :S2_EFF_SAMPLE], len(srs))
            r = wfa_mod.pbo_cscv(M, S2_PBO_BLOCKS)
            info.update(pbo=r["pbo"], pbo_alphas=r["n_alphas"], pbo_days=r["n_days"], pbo_logit_median=r["logit_median"], pbo_splits=r["n_splits"])
    info["flag"] = bool(info["pbo"] is not None and info["pbo"] > S2_PBO_MAX)   # cảnh báo, không loại
    # ngưỡng top DSR trong các alpha ĐÃ QUA S1 của chiến lược (xếp hạng thay cho cổng DSR >= 0,95)
    dsrs = [_dsr_of(m, info)["dsr"] for _, _, m, _ in store.iter_stage_metrics("S1_backtest", strategy, passed_only=True) if "sr_daily" in m]
    info["dsr_cut"] = dsr_cut(dsrs)
    info["n_s1_passed"] = len(dsrs)
    store.set_kv(key, info)
    ctx.log(f"[S3_wfa] {strategy}: N={info['n_trials_raw']} N_eff={info['n_trials']} sr_var={info['sr_var']:.2e} PBO={info['pbo']} "
            f"ngưỡng top DSR={info['dsr_cut']} ({len(dsrs)} alpha qua S1)")
    return info


def _neighbour_ratios(ctx: Ctx, strategy: str, cand: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Tuple[Optional[float], int]]:
    """{alpha_id: (tỉ lệ điểm lân cận có lãi (ret_pct > 0) hoặc None nếu không có lân cận, số lân cận hợp lệ)}.
    Kết quả S1 đã lưu (kể cả điểm bị loại ở S1) được dùng lại; điểm chưa có -> chạy backtest dev1 (như S1) và GHI vào stage_metrics[NEIGHBOUR_STAGE]."""
    store = ctx.store
    plan: Dict[str, List[str]] = {}
    nb_params: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ids = []
        for p in wfa_mod.neighbours(space_for(cand, ctx.cfg.space, ctx.cfg.timeframe), r["params"]):
            nid = alpha_id_of(strategy, p)
            nb_params[nid] = p
            ids.append(nid)
        plan[r["alpha_id"]] = ids
    all_ids = sorted(nb_params)
    known = store.metrics_of(all_ids, "S1_backtest")
    known_nb = store.metrics_of([i for i in all_ids if i not in known], NEIGHBOUR_STAGE)
    missing = [i for i in all_ids if i not in known and i not in known_nb and validate_alpha(cand, nb_params[i], ctx.cfg.space, ctx.cfg.timeframe) is None]
    if missing:
        ctx.exporter.ensure([ctx.s1_job(strategy, nb_params[i]) for i in missing])
        got: List[StageResult] = []
        jobs = [ctx.s1_job(strategy, nb_params[i]) for i in missing]
        for i, res in ctx.imap(bt.w_backtest, iter(jobs), "[S3 lân cận]"):
            m = {"error": res["error"]} if "error" in res else res["metrics"]
            got.append(StageResult(missing[i], NEIGHBOUR_STAGE, {**m, "strategy": strategy, "params": nb_params[missing[i]]}, False))
        store.commit_results(got, neighbours=True)
        known_nb = store.metrics_of([i for i in all_ids if i not in known], NEIGHBOUR_STAGE)
    out: Dict[str, Tuple[Optional[float], int]] = {}
    for a, ids in plan.items():
        vals = []
        for i in ids:
            m = known.get(i) or known_nb.get(i)
            if m and "ret_pct" in m:
                vals.append(m["ret_pct"] > 0)
        out[a] = ((sum(vals) / len(vals)) if vals else None, len(vals))
    return out


def _series_of(daily_rows: List[Dict[str, Any]]) -> List[float]:
    return [x for r in daily_rows for x in r["rets"]]


def _export_wfa_windows(ctx: Ctx, strategy: str, params: Dict[str, Any], dev1: bool = False) -> None:
    jobs = []
    if dev1:
        jobs.append(ctx.s1_job(strategy, params))
    for f in ctx.folds:
        for win, fill, kill in ((f["train"], "level", False), (f["test"], "extreme", True)):
            jobs.append(bt.base_job(strategy, params, win, fill, kill, BASE_RISK_PER_TRADE_PCT, ctx.symbols, ctx.shared_dir, ctx.base_frame))
    ctx.exporter.ensure(jobs)


def _wfa_job(ctx: Ctx, row: Dict[str, Any]) -> Dict[str, Any]:
    _export_wfa_windows(ctx, row["strategy"], row["params"])
    return {"strategy": row["strategy"], "params": row["params"], "folds": ctx.folds, "symbols": ctx.symbols,
            "rpt": BASE_RISK_PER_TRADE_PCT, "shared_dir": ctx.shared_dir, "base_frame": ctx.base_frame}


def _wfa_result(row: Dict[str, Any], res: Dict[str, Any]) -> StageResult:
    if "error" in res:
        return StageResult(row["alpha_id"], "S3_wfa", {"error": res["error"]}, False, "S3.folds", f"S3.folds: lỗi chạy WFA ({res['error']})")
    agg = bt.aggregate_wfa(res["folds"], BASE_RISK_PER_TRADE_PCT)
    ok, code, msg = evaluate_s3(agg["summary"])
    return StageResult(row["alpha_id"], "S3_wfa", agg["metrics"], ok, code, msg, trades=[("S3_wfa", agg["trades"])], daily=[("S3_wfa", agg["daily"])])


def _s3_with_neighbours(ctx: Ctx, infos: Dict[str, Dict[str, Any]], pairs: List[Tuple[Dict[str, Any], StageResult]]) -> List[StageResult]:
    """Kết luận S3 = các cổng WFA, rồi (chỉ alpha đã qua WFA, tiết kiệm backtest) lân cận tham số; PBO của chiến lược ghi vào số đo làm cảnh báo."""
    by_strat: Dict[str, List[Dict[str, Any]]] = {}
    for row, r in pairs:
        if r.passed:
            by_strat.setdefault(row["strategy"], []).append(row)
    ratios: Dict[str, Tuple[Optional[float], int]] = {}
    for strategy, rows in by_strat.items():
        ratios.update(_neighbour_ratios(ctx, strategy, ctx.cands[strategy], rows))
    out: List[StageResult] = []
    for row, r in pairs:
        if "error" in r.metrics:
            out.append(r)
            continue
        info = infos[row["strategy"]]
        ratio, n_nb = ratios.get(row["alpha_id"], (None, 0))
        extra = {"neighbor_ratio": ratio, "neighbor_n": n_nb, "pbo_strategy": info["pbo"], "pbo_flag": info["flag"]}
        ok, code, msg = (evaluate_neighbour(ratio) if r.passed else (False, r.code, r.msg))
        out.append(replace(r, metrics={**r.metrics, **extra}, passed=ok, code=code, msg=msg))
    return out


def stage_s3(ctx: Ctx) -> None:
    """Walk-forward dev2 + lân cận tham số + PBO (trước đây tầng S2 riêng). Xử lý theo lô: WFA cả lô trong pool, rồi lân cận cho alpha đã qua WFA, rồi ghi."""
    store = ctx.store
    ctx.progress.start_stage("S3_wfa", store.count_pending(IDX_S1))
    if not ctx.folds:
        raise ValueError("dev2 không đủ dài để tạo fold WFA (train/test ngày)")
    infos = {strategy: _strategy_level(ctx, strategy) for strategy in store.strategies_at(IDX_S1)}
    t_log = time.time()
    for rows in _page_chunks(store, IDX_S1, max(32, ctx.workers * 8)):
        jobs = [_wfa_job(ctx, r) for r in rows]
        pairs: List[Tuple[Dict[str, Any], StageResult]] = []
        for i, res in ctx.imap(bt.w_wfa, iter(jobs), "[S3_wfa]"):
            pairs.append((rows[i], _wfa_result(rows[i], res)))
            ctx.tick()
        store.commit_results(_s3_with_neighbours(ctx, infos, pairs))
        if time.time() - t_log > 30:
            snap = ctx.progress.snapshot()
            ctx.log(f"[S3_wfa] {snap['done']}/{snap['total']}  ETA {_fmt_eta(snap.get('eta_s'))}")
            t_log = time.time()
    ctx.exporter.cleanup()


def _page_chunks(store: RunStore, prev_idx: int, size: int) -> Iterator[List[Dict[str, Any]]]:
    chunk: List[Dict[str, Any]] = []
    for r in _pages(store, prev_idx):
        chunk.append(r)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _with_series(ctx: Ctx, prev_idx: int, from_stage: str, size: int = 64) -> Iterator[Dict[str, Any]]:
    """Alpha đang chờ tầng kế + chuỗi ngày OOS nối của S3 (đọc parquet theo lô) -> hàng có khoá "series"."""
    for chunk in _page_chunks(ctx.store, prev_idx, size):
        daily = ctx.store.read_daily_many([r["alpha_id"] for r in chunk], from_stage, stage_col=from_stage)
        for r in chunk:
            yield {**r, "series": _series_of(daily.get(r["alpha_id"], []))}


def _turnover_of(store: RunStore, alpha_id: str):
    """Vòng quay vốn/ngày đo từ lệnh OOS của S3 (metrics["turnover_daily"]) -> kịch bản cost_x2 của MC (S4/S5). None = không đo được."""
    return store.metrics_of([alpha_id], "S3_wfa").get(alpha_id, {}).get("turnover_daily")


def _shock_of(store: RunStore, alpha_id: str):
    """Vị thế ngược chiều lớn nhất ở OOS của S3 (metrics["shock"]) -> kịch bản trend thẳng đứng của MC (S4/S5)."""
    return store.metrics_of([alpha_id], "S3_wfa").get(alpha_id, {}).get("shock")


def _dsr_fields(info: Dict[str, Any], d: Dict[str, Any]) -> Dict[str, Any]:
    cut = info.get("dsr_cut")
    return {"dsr": round(d["dsr"], 4), "dsr_sr0": round(d["sr0"], 6), "n_trials": info["n_trials"], "n_trials_raw": info.get("n_trials_raw", info["n_trials"]),
            "dsr_cut": None if cut is None else round(cut, 4)}


def _s4_base(m3: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in m3.items() if k in ("ret_pct", "mdd_pct", "sharpe", "sortino", "trades", "win_rate", "profit_factor", "oos_days", "folds",
                                                 "positive_ratio", "worst_fold_mdd", "is_ret_avg", "traded_folds", "fold_t", "oos_ex_best_pct")}


def stage_s4(ctx: Ctx) -> None:
    """Monte Carlo + DSR (N hiệu dụng, trước đây tầng S2) — tầng KẾT LUẬN: loại nếu DSR ngoài top của chiến lược hoặc MC không đạt."""
    store = ctx.store
    ctx.progress.start_stage("S4_montecarlo", store.count_pending(IDX_S3))
    infos: Dict[str, Dict[str, Any]] = {}

    def info_of(strategy: str) -> Dict[str, Any]:
        if strategy not in infos:
            infos[strategy] = _strategy_level(ctx, strategy)   # đã có trong kv từ S3 (tính lại giống hệt nếu thiếu)
        return infos[strategy]

    def dsr_of(a: str, strategy: str, m1: Dict[str, Any]) -> Tuple[Dict[str, Any], Verdict]:
        info = info_of(strategy)
        d = _dsr_of(m1, info)
        return _dsr_fields(info, d), evaluate_dsr(d["dsr"], info.get("dsr_cut"))

    # DSR trước (rẻ): alpha ngoài top DSR bị loại ngay, không tốn Monte Carlo
    for chunk in _page_chunks(store, IDX_S3, 500):
        ids = [r["alpha_id"] for r in chunk]
        m1, m3 = store.metrics_of(ids, "S1_backtest"), store.metrics_of(ids, "S3_wfa")
        rejects = []
        for r in chunk:
            a = r["alpha_id"]
            fields, (ok, code, msg) = dsr_of(a, r["strategy"], m1[a])
            if not ok:
                rejects.append(StageResult(a, "S4_montecarlo", {**_s4_base(m3.get(a, {})), **fields}, False, code, msg))
        store.commit_results(rejects)
        ctx.progress.tick(len(rejects))

    def on_result(row, res):
        a = row["alpha_id"]
        m3 = store.metrics_of([a], "S3_wfa").get(a, {})
        fields, _ = dsr_of(a, row["strategy"], store.metrics_of([a], "S1_backtest")[a])
        base = {**_s4_base(m3), **fields}
        if res["detail"] is None:
            code = "S4.days"
            return StageResult(a, "S4_montecarlo", {**base, "days": res["days"]}, False, code,
                               f"{code}: {reason_label(code)} ({res['days']} < {S4_MIN_DAYS})")
        d, mn = res["detail"], res["min_size"]
        stress_max = max((x["mdd_pct"] for x in d["stress"] if x["mdd_pct"] is not None), default=None)
        m = {**base, "p_mdd_ge_30": d["summary"]["p_mdd_ge_ruin_pct"], "stress_max_mdd": stress_max, "simulations": d["summary"]["simulations"],
             "mdd_p95": d["summary"]["mdd_p95_pct"], "passes_full_size": bool(d["gate"]["passed"]), "min_size_s": mn["s"],
             "min_size_p_mdd_ge_30": mn["p_mdd_ge_30"], "min_size_stress_max_mdd": mn["stress_max_mdd"]}
        ok, code, msg = evaluate_mc_checks(mn["gate"], "S4")
        store.write_mc(a, {"mc": d, "min_size": {k: mn[k] for k in ("s", "passed", "p_mdd_ge_30", "stress_max_mdd")}, "scale_search": [], "verified": None})
        return StageResult(a, "S4_montecarlo", m, ok, code, msg)

    _stream(ctx, "S4_montecarlo", _with_series(ctx, IDX_S3, "S3_wfa"), lambda r: {"series": r["series"], "shock": _shock_of(store, r["alpha_id"]),
                                                              "turnover": _turnover_of(store, r["alpha_id"])},
            bt.w_mc, on_result)


def stage_s5(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S5_sizing", store.count_pending(IDX_S4))

    def make_job(row):
        _export_wfa_windows(ctx, row["strategy"], row["params"], dev1=True)
        return {"strategy": row["strategy"], "params": row["params"], "series": row["series"], "shock": _shock_of(store, row["alpha_id"]),
                "turnover": _turnover_of(store, row["alpha_id"]), "windows": ctx.windows, "folds": ctx.folds,
                "symbols": ctx.symbols, "shared_dir": ctx.shared_dir, "base_frame": ctx.base_frame}

    def on_result(row, res):
        a = row["alpha_id"]
        old = store.read_mc(a) or {}
        verified = None
        if res["s"] is not None:
            last = res["attempts"][-1]
            verified = {"backtest": bool(last["backtest"]), "wfa": bool(last["wfa"]), "mc": bool(last["mc"])}
        store.write_mc(a, {**old, **({"mc_full_size": old.get("mc"), "mc": res["mc_detail"]} if res["s"] is not None else {}),
                           "scale_search": res["search"], "attempts": res["attempts"], "verified": verified})
        if res["s"] is None:
            code = "S5.scale_low" if res.get("reason") == "scale_low" else "S5.confirm"
            why = (res["attempts"][-1].get("reason") if res["attempts"] else None) or "không tìm được s qua kiểm tra MC"
            detail = f"s < {S5_S_MIN}" if code == "S5.scale_low" else str(why)
            return StageResult(a, "S5_sizing", {"final_scale": None, "search_steps": len(res["search"]), "confirm_attempts": len(res["attempts"])},
                               False, code, f"{code}: {reason_label(code)} ({detail})")
        wfa = res["wfa"]
        m = {**wfa["metrics"], "final_scale": res["s"], "search_s": res["s_search"], "search_steps": len(res["search"]),
             "confirm_attempts": len(res["attempts"]), "backtest_ret_pct": res["backtest"]["metrics"]["ret_pct"],
             "backtest_mdd_pct": res["backtest"]["metrics"]["mdd_pct"]}
        return StageResult(a, "S5_sizing", m, True, trades=[("S5_sizing", wfa["trades"])], daily=[("S5_sizing", wfa["daily"])])

    _stream(ctx, "S5_sizing", _with_series(ctx, IDX_S4, "S3_wfa", 16), make_job, bt.w_sizing, on_result)
    ctx.exporter.cleanup()


def stage_s6(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("S6_holdout", store.count_pending(5))
    w = ctx.windows

    def rows_with_scale() -> Iterator[Dict[str, Any]]:
        for chunk in _page_chunks(store, 5, 200):
            m5 = store.metrics_of([r["alpha_id"] for r in chunk], "S5_sizing")
            for r in chunk:
                yield {**r, "scale": m5[r["alpha_id"]]["final_scale"]}

    def make_job(row):
        ctx.exporter.ensure([bt.base_job(row["strategy"], row["params"], (w["dev2_end"], w["end"]), "level", True, BASE_RISK_PER_TRADE_PCT, ctx.symbols, ctx.shared_dir, ctx.base_frame)])
        return {"strategy": row["strategy"], "params": row["params"], "windows": w, "rpt": risk_for_scale(row["scale"]),
                "symbols": ctx.symbols, "shared_dir": ctx.shared_dir, "base_frame": ctx.base_frame}

    def on_result(row, res):
        lv, ex = res["level"], res["extreme"]
        ml, me = lv["metrics"], ex["metrics"]
        m = {**_scalar_base(ml), "final_scale": row["scale"], "extreme_ret_pct": me["ret_pct"], "extreme_mdd_pct": me["mdd_pct"],
             "extreme_trades": me["trades"], "halted": ml["halted"] or me["halted"]}
        if "regime_blocked" in ml:   # bảng regime học trên dữ liệu trước holdout (promote dùng lại)
            m["regime_blocked"] = ml["regime_blocked"]
        ok, code, msg = evaluate_s6(ml, me)
        return StageResult(row["alpha_id"], "S6_holdout", m, ok, code, msg,
                           trades=[("S6_holdout", lv["trades"]), ("S6_holdout_extreme", ex["trades"])],
                           daily=[("S6_holdout", [{"fold": None, "start": lv["daily_start"], "rets": lv["daily"]}]),
                                  ("S6_holdout_extreme", [{"fold": None, "start": ex["daily_start"], "rets": ex["daily"]}])])

    _stream(ctx, "S6_holdout", rows_with_scale(), make_job, bt.w_holdout, on_result)
    ctx.exporter.cleanup()


def stage_final(ctx: Ctx) -> None:
    store = ctx.store
    ctx.progress.start_stage("FINAL", store.count_pending(6))
    batch = []
    for chunk in _page_chunks(store, 6, 500):
        m6 = store.metrics_of([r["alpha_id"] for r in chunk], "S6_holdout")
        for r in chunk:
            m = dict(m6[r["alpha_id"]])
            batch.append(StageResult(r["alpha_id"], "FINAL", m, True, final_scale=m["final_scale"]))
        store.commit_results(batch)
        ctx.progress.tick(len(batch))
        batch = []


STAGE_FUNCS: Dict[str, Callable[[Ctx], None]] = {
    "S0_generate": stage_s0, "S1_backtest": stage_s1, "S3_wfa": stage_s3, "S4_montecarlo": stage_s4,
    "S5_sizing": stage_s5, "S6_holdout": stage_s6, "FINAL": stage_final,
}


# ── Chạy cả phễu ────────────────────────────────────────────────────────────
def run_funnel(cfg: FunnelConfig, run_id: Optional[str] = None, workers: int = 0, until: Optional[str] = None, base_dir: Optional[str] = None,
               log: Callable[[str], None] = lambda s: print(s, flush=True), check_data: bool = True, max_alphas: int = MAX_ALPHAS_DEFAULT,
               ) -> Dict[str, Any]:
    """Chạy (hoặc chạy tiếp) một lượt phễu. workers = 0: tuần tự trong tiến trình (test); > 0: pool_imap_bounded. Trả tóm tắt (counts, run_dir...)."""
    from backend.optimize.book.build import perp_symbols
    from backend.optimize.funnel.storage import data_fingerprint
    if until is not None and until not in STAGE_IDX:
        raise ValueError(f"until phải thuộc {STAGES}")
    run_id = run_id or new_run_id()
    run_dir = os.path.join(base_dir or funnel_root(), run_id)
    resuming = os.path.isfile(os.path.join(run_dir, "results.sqlite"))
    try:   # run.json có thể đã có (API ghi bản "queued" trước khi CLI chạy) — giữ job_id/created
        with open(os.path.join(run_dir, "run.json"), encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    if resuming and old.get("config"):   # resume: dùng đúng cấu hình đã lưu (không cho đổi giữa chừng)
        saved = old["config"]
        cfg = FunnelConfig(**{k: saved[k] for k in FunnelConfig.__dataclass_fields__ if k in saved})
    cfg.symbols = cfg.symbols or perp_symbols()
    cfg.symbols = [s if "@" in s else f"{s}@perp" for s in cfg.symbols]
    check_timeframe(cfg)
    planned = planned_alphas(cfg)
    if sum(planned.values()) > max_alphas:
        raise ValueError(f"{sum(planned.values()):,} alpha vượt giới hạn {max_alphas:,} (giảm n_per_strategy hoặc số chiến lược)")
    if check_data:
        from backend.crawl.store import require_data_ok
        require_data_ok(cfg.symbols)   # cổng chất lượng dữ liệu BẮT BUỘC, trước khi tạo kho / fork pool
    if resuming and old.get("windows_ms"):
        windows = old["windows_ms"]
    else:
        windows = compute_windows(cfg.symbols, cfg.windows)
    store = RunStore(run_dir)
    progress = Progress(run_dir)
    job_dir = os.environ.get("NORA_JOB_DIR")
    from backend.crawl.store import exchange
    cfg_out = {**cfg.to_dict(), "windows": windows_iso(windows), **git_info(), "data_exchange": exchange(),
               "data_sha256": hashlib.sha256(json.dumps(data_fingerprint(cfg.symbols), sort_keys=True).encode()).hexdigest(),
               "thresholds": thresholds_snapshot()}
    store.update_run({"run_id": run_id, "job_id": os.path.basename(job_dir) if job_dir else old.get("job_id"), "status": "running",
                      "created": old.get("created") or time.time(), "started": time.time(), "finished": None,
                      "config": {**(old.get("config") or {}), **cfg_out} if resuming else cfg_out, "windows_ms": windows,
                      "planned": planned, "total_alphas": sum(planned.values()), "until": until, "workers": workers,   # workers: số đo giây/backtest (estimate.py)
                      "stages": old.get("stages") or {s: {"status": "pending"} for s in STAGES}})
    ctx = Ctx(store, cfg, windows, workers, progress, log)
    if resuming:
        log(f"[resume] {run_id}: {store.count_alphas():,} alpha trong kho")
    t_run = time.time()
    status = "done"
    try:
        with graceful_sigterm(progress):
            for stage in STAGES:
                st = store.read_run().get("stages", {}).get(stage, {})
                if st.get("status") == "done":
                    if until == stage:
                        break
                    continue
                t0 = time.time()
                store.update_run({"stages": {stage: {"status": "running", "started": t0}}})
                STAGE_FUNCS[stage](ctx)
                counts = {c["stage"]: c for c in store.stage_counts()}[stage]
                store.update_run({"stages": {stage: {"status": "done", "started": t0, "finished": time.time(), "wall_s": round(time.time() - t0, 1),
                                                     "input": counts["input"], "passed": counts["passed"], "rejected": counts["rejected"]}}})
                _log_stage(ctx, stage, counts, time.time() - t0)
                if until == stage:
                    break
    except SystemExit as exc:
        status = "cancelled" if exc.code == 143 else ("failed" if exc.code else "done")
        raise
    except BaseException:
        status = "failed"
        raise
    finally:
        try:
            ctx.exporter.cleanup()
            if ctx.shared_dir and os.path.isdir(ctx.shared_dir):
                shutil.rmtree(ctx.shared_dir, ignore_errors=True)
            store.update_run({"status": status, "finished": time.time(), "wall_s": round(time.time() - t_run, 1)})
        finally:
            store.close()
    progress.finish(status)
    final_store = RunStore(run_dir, read_only=True)
    try:
        counts = final_store.stage_counts()
        final = final_store.final_alphas()
        disk = final_store.disk_bytes()
    finally:
        final_store.close()
    return {"run_id": run_id, "run_dir": run_dir, "status": status, "counts": counts, "final_alphas": final, "disk_bytes": disk,
            "wall_s": round(time.time() - t_run, 1)}


def _log_stage(ctx: Ctx, stage: str, c: Dict[str, Any], wall: float) -> None:
    with ctx.store._lock:
        rs = ctx.store._con.execute("SELECT reject_code, COUNT(*) FROM alphas WHERE rejected_stage=? GROUP BY reject_code ORDER BY COUNT(*) DESC LIMIT 4",
                                    (stage,)).fetchall()
    top = "; ".join(f"{code} ×{n}" for code, n in rs) or "-"
    ctx.log(f"[{stage}] vào {c['input']} → qua {c['passed']}, loại {c['rejected']} ({wall:.0f}s) | lý do chính: {top}")


# ══════════════════════════════════════════════════════════════════════════
# Tính lại danh sách lệnh S1 của một alpha (alpha bị loại ở S1 chỉ lưu thống kê). Tất định: cùng PortfolioEngine, cùng tham số/cửa sổ/dữ liệu
# -> TRÙNG TỪNG BIT với lệnh một alpha qua S1 đã lưu (test_funnel kiểm). Kết quả được ghi đệm tại <run_dir>/recomputed/<alpha_id>.json.
#
# Job API `funnel_recompute` (optimize/process/process.py -> run_job({"run_id", "alpha_id"})): RAM nằm trong nora.slice, không trong tiến trình API.
# ══════════════════════════════════════════════════════════════════════════

def cache_path(run_dir: str, alpha_id: str) -> str:
    return os.path.join(run_dir, "recomputed", f"{alpha_id}.json")


def read_cached(run_dir: str, alpha_id: str) -> Optional[Dict[str, Any]]:
    return read_json(cache_path(run_dir, alpha_id))


def recompute_s1(run_dir: str, alpha_id: str, shared_dir: Optional[str] = None) -> Dict[str, Any]:
    """Backtest S1 lại (dev1, rủi ro chuẩn, SL level, kill tắt) -> {"trades": [hàng như parquet, không alpha_id/stage], "metrics": {...}, "daily": [...]}."""
    store = RunStore(run_dir, read_only=True)
    try:
        alpha = store.get_alpha(alpha_id)
        run = store.read_run()
    finally:
        store.close()
    if alpha is None:
        raise KeyError(alpha_id)
    w = run["windows_ms"]
    symbols = run["config"]["symbols"]
    job = bt.base_job(alpha["strategy"], alpha["params"], (w["start"], w["dev1_end"]), "level", False, BASE_RISK_PER_TRADE_PCT, symbols, shared_dir,
                       run["config"].get("timeframe", "1m"))
    res = bt.run_backtest(job, want_trades=True)
    return {"alpha_id": alpha_id, "trades": res["trades"], "metrics": res["metrics"], "daily": res["daily"], "daily_start": res["daily_start"]}


def run_funnel_recompute(params=None) -> Dict[str, Any]:
    """Tính lại lệnh S1 của params["alpha_id"] trong lượt params["run_id"] -> ghi <run_dir>/recomputed/<alpha_id>.json."""
    from backend.crawl.store import options, require_data_ok_or_exit
    from backend.optimize.process.workers import require_memory_limit
    a = options({"run_id": "", "alpha_id": ""}, params)
    if not a.run_id or not a.alpha_id:
        raise ValueError("cần run_id và alpha_id")
    require_memory_limit("funnel.recompute")
    run_dir = os.path.join(funnel_root(), a.run_id)
    store = RunStore(run_dir, read_only=True)
    try:
        symbols = store.read_run()["config"]["symbols"]
    finally:
        store.close()
    require_data_ok_or_exit(symbols)
    path = cache_path(run_dir, a.alpha_id)
    atomic_write_json(path, recompute_s1(run_dir, a.alpha_id))
    print(f"ghi: {path}", flush=True)
    return {"path": path}


# ══════════════════════════════════════════════════════════════════════════
# Job phễu kiểm duyệt alpha S0 → FINAL (POST /api/studio/funnel/runs -> optimize/process/process.py -> run_job). Hợp đồng: docs/funnel_contract.md.
# Kho: data/cache/process/funnel/<run_id>/ (run.json, results.sqlite, trades/, daily/, mc/).
#
# Tầng: S0 sinh alpha → S1 backtest dev1 → S3 walk-forward dev2 (tham số cố định) + lân cận / PBO → S4 Monte Carlo + DSR (kết luận) →
# S5 khối lượng sống sót (tìm s + xác nhận thật) → S6 holdout (một lần) → FINAL. Mọi dữ liệu thật: quality gate bắt buộc, không mock.
#
# Tham số (DEFAULTS): strategies, space (grid | schema), timeframe (khung chạy 15m | 1h | 4h; mặc định 15m), regime (off | learn | both), n_per_strategy | full_grid, seed, symbols, windows, train_days, test_days, run_id, resume (run_id của lượt
# bị ngắt: cấu hình lấy từ run.json), until (dừng sau tầng này), workers, per_worker_mb, max_alphas, force_large.
# SIGTERM (nút Huỷ của API) -> flush lô đang ghi rồi thoát; resume tiếp tục đúng chỗ dừng.
# ══════════════════════════════════════════════════════════════════════════

FUNNEL_RUN_DEFAULTS = {"strategies": "", "n_per_strategy": None, "full_grid": False, "seed": 7, "symbols": "", "windows": None, "train_days": None,
            "test_days": None, "run_id": "", "resume": "", "until": "", "workers": "auto", "per_worker_mb": None, "max_alphas": 200_000,
            "force_large": False, "space": "grid", "timeframe": "15m", "regime": "off"}


def run_funnel_run(params=None):
    """Chạy phễu với `params` (xem DEFAULTS) -> kết quả lượt chạy (cũng ghi $NORA_JOB_DIR/result.json)."""
    warnings.filterwarnings("ignore")
    a = options(FUNNEL_RUN_DEFAULTS, params)
    if a.n_per_strategy is not None and a.full_grid:
        raise ValueError("chọn một: n_per_strategy hoặc full_grid")
    from backend.optimize.process.workers import check_memory_gate, require_memory_limit
    require_memory_limit("run_funnel")
    from backend.optimize.process.workers import resolve_workers

    run_id = a.resume or a.run_id or new_run_id()
    resume_dir = os.path.join(funnel_root(), run_id)
    if a.resume and not os.path.isfile(os.path.join(resume_dir, "results.sqlite")):
        raise SystemExit(f"resume: {resume_dir} không có results.sqlite")
    saved = {}
    if a.resume:
        with open(os.path.join(resume_dir, "run.json"), encoding="utf-8") as fh:
            saved = json.load(fh).get("config", {})
    strategies = as_list(a.strategies) or list(saved.get("strategies", []))
    if not strategies:
        raise SystemExit("cần strategies (hoặc resume)")
    if not a.resume and a.n_per_strategy is None and not a.full_grid:
        raise SystemExit("cần n_per_strategy hoặc full_grid")
    cfg = FunnelConfig(
        strategies=strategies,
        n_per_strategy=a.n_per_strategy if not a.resume else saved.get("n_per_strategy"),
        full_grid=a.full_grid if not a.resume else bool(saved.get("full_grid")),
        seed=a.seed if not a.resume else saved.get("seed", a.seed),
        symbols=as_list(a.symbols) or saved.get("symbols"),
        windows=a.windows or saved.get("windows"),
        space=a.space if not a.resume else saved.get("space", "grid"),
        timeframe=a.timeframe if not a.resume else saved.get("timeframe", "1m"),
        regime=a.regime if not a.resume else saved.get("regime", "off"),
        **{k: v for k, v in (("train_days", a.train_days), ("test_days", a.test_days)) if v})
    check_timeframe(cfg)
    planned = planned_alphas(cfg)
    total = sum(planned.values())
    cap = 1_000_000 if a.force_large else a.max_alphas
    if total > cap:
        raise SystemExit(f"Từ chối: {total:,} alpha ({planned}) vượt max_alphas {cap:,}. Giảm n_per_strategy / số chiến lược hoặc đặt force_large (trần cứng 1.000.000).")

    from backend.crawl.store import require_perp
    from backend.optimize.book.build import perp_symbols
    from backend.crawl.store import require_data_ok_or_exit
    require_perp(cfg.symbols or [], "Phễu")
    require_data_ok_or_exit(cfg.symbols or perp_symbols())   # cổng chất lượng dữ liệu BẮT BUỘC, trước mọi việc khác và trước khi fork pool

    per_worker_mb = a.per_worker_mb or PER_WORKER_MB
    workers = resolve_workers(a.workers, per_worker_mb, "run_funnel")
    check_memory_gate(workers * per_worker_mb, f"run_funnel --workers {workers}")
    print(f"run_id {run_id} | {total:,} alpha {planned} | seed {cfg.seed} | workers={workers}", flush=True)
    res = run_funnel(cfg, run_id=run_id, workers=workers, until=a.until or None, check_data=False, max_alphas=1_000_000)

    print(f"\n== Phễu {res['run_id']} ({res['status']}, {res['wall_s']:.0f}s) ==", flush=True)
    for c in res["counts"]:
        print(f"  {c['stage']:14s} vào {c['input']:>8,} | đã chấm {c['done']:>8,} | qua {c['passed']:>8,} | loại {c['rejected']:>8,}", flush=True)
    for fa in res["final_alphas"]:
        print(f"  FINAL {fa['alpha_id']} {fa['strategy']} s={fa['final_scale']} {json.dumps(fa['params'], ensure_ascii=False)}", flush=True)
    print(f"dung lượng kho {res['disk_bytes'] / 1048576:.1f} MB | {res['run_dir']}", flush=True)
    write_job_result({k: res[k] for k in ("run_id", "run_dir", "status", "counts", "final_alphas", "disk_bytes", "wall_s")})   # chỉ khi chạy như job API
    return res
