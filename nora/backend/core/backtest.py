"""Engine duy nhất (P9.4): kernel numba (cache=True), BacktestEngine, PortfolioEngine, tài sản DEX.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.4, P9.4b). Giao diện sàn (Order / Venue / VenueCaps) + vỏ AMM có kiểm đầu vào ở phần vĩnh viễn; đường Python cũ (PositionTracker / PositionManager / SimVenue / Runner)
nằm ở khu cuối file "LEGACY PY PATH — xoá ở P9.4b T10".
"""
import contextlib
import dataclasses
import io
import itertools
import math
import os
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from math import isnan
from operator import attrgetter
from typing import Any, Callable, Deque, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple, Set, Union

import numpy as np
import pandas as pd
from numba import carray, njit, types
from numba.core import cgutils
from numba.extending import intrinsic

from backend.core.models import (Account, CapitalLedger, Fill, FundingApplied, OrderModel, OrderRejected, OrderType, PositionBook, PositionModel, PositionStatus,
                                 PositionType, next_id)
from backend.core.models import DataSource, data_source
from backend.core.signal import lag_key, VectorEvaluator, Program
from backend.core.signal import CODE as REGIME_CODE, LABEL_VI as REGIME_LABEL_VI, NAMES as REGIME_NAMES, REFS as REGIME_REFS
from backend.core.signal import classify, masks_for, profile_cfg, raw_states
from backend.core.signal import (DEFAULT_LOOKBACK_MIN, HORIZONS_MIN, MINUTE, _explain, _forward_bps, _num, _since, _stats, _thin,
                                 _verdict)
from backend.core import position_size as policy
from backend.core.position_size import SlotSpec, admit_entry, kill_triggered
from backend.core.params import BASE_POSITION, config_from_dict, DATA_COLUMNS, DEFAULT_CAPITAL, DAY_MS as DAY, FRAME_MS, FRAME_ORDER, FRAMES, NORA_DEFAULTS, RISK, RUN_FRAME, StrategyParams
from backend.core import indicator as kernels


# ══════════════════════════════════════════════════════════════════════════
# Vòng lặp trong của engine backtest (numba) — thay vòng lặp Python từng phút của PortfolioEngine / BacktestEngine.
#
# KHÔNG phải một engine thứ hai: đây là phần thực thi của CHÍNH engine (PortfolioEngine.run / BacktestEngine.run gọi run_portfolio / run_backtest ở cuối file).
# Ngữ nghĩa là bản dịch NGUYÊN VĂN từ execution.PositionTracker (on_bar/_intrabar/_open/_add_layer/_close/_risk_margin/apply_funding),
# CapitalLedger và vòng lặp run() (rủi ro danh mục, kill switch, bỏ qua phút rảnh, lấy mẫu vốn theo giờ). Kết quả BIT-IDENTICAL với bản Python
# (test/test_kernel_parity.py so với test/reference_engine.py + golden snapshot).
#
# Quy tắc giữ bit-identical:
# - Cùng thứ tự phép toán float; KHÔNG dùng fastmath (LLVM không gộp FMA); mọi phép chia/nhân/cộng giữ nguyên thứ tự kết hợp của bản Python.
# - max()/min() của Python: `max(a,b)` = `b if b > a else a`, `min(a,b)` = `b if b < a else a` (khác nhau ở -0.0/NaN) -> _pmax/_pmin.
# - Mọi phép làm tròn `round(x, 4)` (đường vốn) làm ở phần Python cuối file, không làm trong hàm njit.
# - Trạng thái mỗi tracker nằm trong mảng F (float) / I (int); tham số trong P / PI; sổ vốn LG; bộ đếm G; kết quả (vị thế, lệnh, mẫu vốn) ghi vào
#   mảng cấp sẵn rồi phần Python cuối file dựng lại PositionModel/OrderModel. Tràn dung lượng -> G[G_OVF]=1 và Python chạy lại với dung lượng gấp 4.
# - Mảng dữ liệu (t/o/h/l/c/funding/tín hiệu) truyền bằng bảng con trỏ (không sao chép, không chuyên biệt hoá numba theo số tài sản/chiến lược).
# - error_model='numpy': chia cho 0 cho inf/NaN thay vì ném ZeroDivisionError (tham số hợp lệ không bao giờ chia cho 0).
# ══════════════════════════════════════════════════════════════════════════

NONE_I = -(1 << 62)          # None của mốc thời gian (halted_at / ruined_at)

# ── Cột trạng thái float F ──────────────────────────────────────────────────
F_QTY, F_AVG, F_MU, F_FP, F_LAST_FILL, F_NEXT, F_PEAK, F_MAE, F_RES_HERE, F_FUND, F_ENTRY_EQ, F_MAXCAP, F_POS_LEV, \
    F_PLANNED, F_PVOL, F_SL, F_TP, F_TRAIL, F_TACT, F_UNIT, F_RB, F_RQ, F_QU, F_MID = range(24)   # F_UNIT: tracker.unit_pct (đặt ở mỗi lần _open qua được kiểm ATR, kể cả khi lệnh bị từ chối)
# F_RB/F_RQ/F_QU: dự trữ pool (base, quote) + USD / 1 quote tại tick hiện tại, F_MID: giá biên theo dự trữ (reserve_price) — KernelBook.set_amm ghi mỗi tick; chỉ đọc khi PI_AMM = 1
F_DS0 = 24                    # F[:, F_DS0 + j] = bước DCA hiện tại (đã quy đổi theo unit)
F_FIXED = 24
# ── Tham số float P ─────────────────────────────────────────────────────────
P_FEE, P_MAKER, P_SLIP, P_MMR, P_MAXLEV, P_CAPUSE, P_BSL, P_BTP, P_BTR, P_BTA, P_RISK, P_MAXNOT, P_OSP, P_LTHRU, P_AFEE, P_ASTABLE, P_AGAS = range(17)
# P_AFEE/P_ASTABLE/P_AGAS: pool AMM của slot (phí thu trên đầu vào, 1 = stable x³y+xy³, gas USD mỗi swap); chỉ đọc khi PI_AMM = 1
P_BS0 = 17                    # P[:, P_BS0 + j] = bước DCA gốc; P[:, P_BS0 + ml + j] = hệ số khối lượng tầng j (ml = số cột tối đa)
P_FIXED = 17                  # P_LTHRU: lệnh limit (DCA, TP) chỉ khớp khi giá đi qua mức bấy nhiêu (tỉ lệ); 0 = chạm là khớp
# ── Tham số int PI ──────────────────────────────────────────────────────────
PI_LONG, PI_PERP, PI_TIMEOUT, PI_COOL, PI_EXTREME, PI_ATR, PI_RISKSZ, PI_NBASE, PI_MAXOPEN, PI_PATH, PI_LTAKER, PI_AMM = range(12)
# PI_LTAKER: DCA / chốt lời là swap (khớp như lệnh taker, ở open nếu gap); PI_AMM: trượt giá theo dự trữ pool (thay slippage_rate cho mọi lệnh taker + chi phí khứ hồi khi tính khối lượng)
NPI = 12                      # PI_PATH: đường giá trong nến — 0 adverse_first (cũ), 1 ohlc (mặc định), 2 adaptive
# ── Trạng thái int I ────────────────────────────────────────────────────────
I_OPEN, I_PE, I_PX, I_LAYERS, I_ENTRY_T, I_LASTCLOSE, I_HASLC, I_DCAREJ, I_SKIP, I_POS, I_NST, I_BLK, I_DCAOK = range(13)
NI = 13                       # I_DCAOK: 1 = nến này được dồn tầng DCA (điều kiện DCA tại cuối nến trước; không có điều kiện -> luôn 1)
# ── Bộ đếm G ────────────────────────────────────────────────────────────────
G_REJ, G_NPOS, G_NORD, G_NCL, G_OVF, G_RISKMIN, G_ATT, G_HALT, G_RUIN, G_NSMP, G_NADM, G_AMERR = range(12)
# G_AMERR: 1 = một lệnh AMM gặp đầu vào không hợp lệ (dự trữ <= 0, ...); Python (KernelBook / SlotDriver) ném ValueError sau lời gọi kernel
NG = 12                       # G_NADM: số lần xét hạn mức đã ghi vào vết ADM (không bao giờ đặt G_OVF; chỉ ghi khi cfg_i[CI_ADM_ON] != 0)
# cfg_i: (trade_start, max_positions, max_per_symbol, close_at_end, step_ms, địa chỉ lưới, độ dài lưới, địa chỉ ADM, sức chứa ADM, bật ADM)
CI_ADM_PTR, CI_ADM_CAP, CI_ADM_ON = 7, 8, 9
# ADM[cap, 8] = (t, k, n_open, per_book, equity, gross, can_open, max_new) — mỗi lần một slot đang chờ vào lệnh được xét hạn mức ở open
(AD_T, AD_K, AD_NOPEN, AD_PERB, AD_EQ, AD_GROSS, AD_CAN, AD_MAXNEW) = range(8)
NAD = 8
LG_EQ, LG_RES, LG_PEAK = 0, 1, 2      # LG_PEAK: đỉnh vốn đã chốt (giảm rủi ro theo mức sụt)
# ── Đầu ra vị thế (outF / outI) và lệnh (ordF / ordI) ───────────────────────
(O_ENTER_PRICE, O_CLOSE_PRICE, O_PNL, O_PCT, O_QTY, O_AVG, O_ENTRY_EQ, O_ENTRY_MARGIN, O_ENTRY_NOTIONAL, O_ENTRY_FEE, O_EXIT_FEE,
 O_TOTAL_MARGIN, O_FEES, O_FUNDING, O_MAE, O_MAXP, O_MINP, O_UNIT, O_LEVUSED, O_RISK) = range(20)
NOF = 20
OI_TR, OI_ENTER_T, OI_CLOSE_T, OI_STATUS, OI_LAYERS, OI_REASON, OI_FIRST_ORD, OI_START = range(8)
NOI = 8
OR_PRICE, OR_QTY, OR_FEE, OR_RAW, OR_SLIP = range(5)   # OR_RAW: giá tham chiếu trước trượt giá; OR_SLIP: tỉ lệ trượt (như OrderModel.slippage; 0 cho maker/thanh lý)
NOR = 5
ORI_POS, ORI_TIME, ORI_PHASE, ORI_EXIT, ORI_LIQ = range(5)   # ORI_LIQ: 1 maker, 2 taker, 3 liquidation
# mã lý do (đối ứng chuỗi trong _kernel_io.REASONS)
R_ENTRY, R_STOP, R_TIMEOUT, R_LIQ, R_SL, R_TRAIL, R_TP, R_END, R_KILL, R_DCA = range(10)
# trạng thái (PositionStatus)
S_TP, S_SL, S_CANCEL, S_LIQ = 2, 3, 4, 5

_JIT = dict(cache=True, error_model="numpy")


@intrinsic
def _ptr(typingctx, addr):
    """int64 địa chỉ -> voidptr (để carray dựng view mảng NumPy không sao chép)."""
    sig = types.voidptr(types.int64)

    def codegen(context, builder, signature, args):
        return builder.inttoptr(args[0], cgutils.voidptr_t)
    return sig, codegen


@njit(**_JIT)
def _pmax(a, b):
    return b if b > a else a


@njit(**_JIT)
def _pmin(a, b):
    return b if b < a else a


# ─── AMM (pool Uniswap v2 / Aerodrome v2): chi phí swap ĐÚNG theo dự trữ pool (P9.4b T6) ─────────────────────────────────────────────
# NGUỒN DUY NHẤT của toán AMM (core/execute/amm.py đã gộp vào đây; vỏ Python kiểm đầu vào: `amm_amount_out` / `amm_price_impact` / `AmmImpact` bên dưới). Chép nguyên văn từ amm.py cũ:
# volatile x*y=k (công thức đóng), stable x³y+xy³=k (chia đôi 200 vòng, cùng thứ tự phép toán).
# GIÁ BIÊN (`reserve_price`) tính ở Python bằng NumPy, KHÔNG trong njit: NumPy (>= 2, AVX512/SVML) tính `y ** 3` bằng pow SIMD khác libm pow ở bit cuối
# (~5% số đầu vào; math.pow của numba = libm), nên bản njit không thể trùng từng bit — `set_amm` tính mid bằng đúng hàm NumPy cũ và ghi vào F_MID.
_AMM_BISECT = 200      # chia đôi trên [0, dự trữ]: số thực hội tụ sau ~60 vòng, trần để không lặp vô hạn


@njit(**_JIT)
def _stable_k(x, y):
    return x * x * x * y + x * y * y * y


@njit(**_JIT)
def _amm_out_raw(amount_in, r_in, r_out, fee, stable):
    """Lượng token nhận được (đầu vào đã được kiểm > 0): phí thu trên đầu vào."""
    eff = amount_in * (1.0 - fee)
    if not stable:
        return r_out * eff / (r_in + eff)
    k = _stable_k(r_in, r_out)
    x1 = r_in + eff
    lo = 0.0
    hi = r_out
    for _ in range(_AMM_BISECT):
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:
            break
        if _stable_k(x1, mid) < k:
            lo = mid
        else:
            hi = mid
    return r_out - hi


@njit(**_JIT)
def _amm_price_impact_raw(notional, is_buy, mid, rb, rq, qu, fee, stable):
    """Trượt giá (tỉ lệ, KHÔNG gồm phí pool và gas) của lệnh `notional` USD; đầu vào đã được kiểm (notional, dự trữ, qu > 0); mid = giá biên trước lệnh."""
    if is_buy:
        spend = notional / qu
        got = _amm_out_raw(spend, rq, rb, fee, stable)
        return spend * (1.0 - fee) / got / mid - 1.0
    sell = notional / (mid * qu)
    got = _amm_out_raw(sell, rb, rq, fee, stable)
    return 1.0 - got / (sell * (1.0 - fee)) / mid


@njit(**_JIT)
def _amm_impact(k, notional, is_buy, P, F, G):
    """impact_fn của slot k trên pool hiện tại (F_RB/F_RQ/F_QU): trượt giá + gas / danh nghĩa; 0 khi !(notional > 0). Đầu vào không hợp lệ -> G_AMERR."""
    if not notional > 0.0:
        return 0.0
    rb = F[k, F_RB]
    rq = F[k, F_RQ]
    qu = F[k, F_QU]
    if not (rb > 0.0 and rq > 0.0 and qu > 0.0):
        G[G_AMERR] = 1
        return 0.0
    stable = P[k, P_ASTABLE] != 0.0
    mid = F[k, F_MID]
    # đầu vào của _amm_out_raw phải > 0 (amount_out cũ ném ValueError): mua spend = notional/qu, bán sell = notional/(mid*qu)
    if not ((notional / qu if is_buy else notional / (mid * qu)) > 0.0):
        G[G_AMERR] = 1
        return 0.0
    return _amm_price_impact_raw(notional, is_buy, mid, rb, rq, qu, P[k, P_AFEE], stable) + P[k, P_AGAS] / notional


@njit(**_JIT)
def _slip(k, notional, is_buy, P, PI, F, G):
    """Tỉ lệ trượt giá của một lệnh taker: impact theo pool (AMM) hoặc slippage_rate cố định (policy.slip_rate)."""
    if PI[k, PI_AMM] == 1:
        return _amm_impact(k, notional, is_buy, P, F, G)
    return P[k, P_SLIP]


@njit(**_JIT)
def _rt_cost(k, notional, P, PI, F, G):
    """Chi phí KHỨ HỒI trên danh nghĩa `notional` khi có impact (policy.round_trip_cost nhánh impact_fn): 2·phí + trượt mua + trượt bán."""
    return 2.0 * P[k, P_FEE] + _slip(k, notional, True, P, PI, F, G) + _slip(k, notional, False, P, PI, F, G)


# ─── Tracker: các hành động (dịch từ PositionTracker) ───────────────────────
@njit(**_JIT)
def _unreal(k, price, PI, F, I):
    if I[k, I_OPEN] == 0 or F[k, F_QTY] <= 0.0:
        return 0.0
    if PI[k, PI_LONG] == 1:
        move = price - F[k, F_AVG]
    else:
        move = F[k, F_AVG] - price
    return F[k, F_QTY] * move - F[k, F_FP]


@njit(**_JIT)
def _apply_funding(k, rate, price, PI, F, I, LG):
    if I[k, I_OPEN] == 0 or PI[k, PI_PERP] == 0 or F[k, F_QTY] <= 0.0:
        return
    payment = F[k, F_QTY] * price * rate * (1.0 if PI[k, PI_LONG] == 1 else -1.0)
    F[k, F_FUND] += payment
    LG[LG_EQ] = LG[LG_EQ] + (-payment)
    if LG[LG_EQ] > LG[LG_PEAK]:
        LG[LG_PEAK] = LG[LG_EQ]


@njit(**_JIT)
def _log_order(pidx, t, price, qty, phase, fee, is_exit, liq, raw, slip, ordF, ordI, G):
    j = G[G_NORD]
    if j >= ordF.shape[0]:
        G[G_OVF] = 1
        return
    ordF[j, OR_PRICE] = price
    ordF[j, OR_QTY] = qty
    ordF[j, OR_FEE] = fee
    ordF[j, OR_RAW] = raw
    ordF[j, OR_SLIP] = slip
    ordI[j, ORI_POS] = pidx
    ordI[j, ORI_TIME] = t
    ordI[j, ORI_PHASE] = phase
    ordI[j, ORI_EXIT] = is_exit
    ordI[j, ORI_LIQ] = liq
    G[G_NORD] = j + 1


@njit(**_JIT)
def _layer_cost(k, price, margin, market, PI, P, F, LG, G):
    """Chi phí một lớp vào lệnh (chưa áp dụng): -> (ok_code, fill, fee, notional, slip). ok_code 0 ok, 1 vượt ngân sách, 2 thiếu vốn (G_REJ += 1)."""
    long_ = PI[k, PI_LONG] == 1
    taker = market or PI[k, PI_LTAKER] == 1
    lev = F[k, F_POS_LEV]
    notional = margin * lev
    if taker:
        slip = _slip(k, notional, long_, P, PI, F, G)
        fill = price * ((1.0 + slip) if long_ else (1.0 - slip))
    else:
        slip = 0.0
        fill = price
    fee = notional * (P[k, P_FEE] if taker else P[k, P_MAKER])
    if margin <= 0.0 or fill <= 0.0 or F[k, F_MU] + margin + F[k, F_FP] + fee > F[k, F_MAXCAP] + 1e-9:
        return 1, fill, fee, notional, slip
    amount = margin + fee
    if amount <= 0.0 or amount > (LG[LG_EQ] - LG[LG_RES]) + 1e-9:   # CapitalLedger.reserve (usage = 1,0)
        G[G_REJ] += 1
        return 2, fill, fee, notional, slip
    return 0, fill, fee, notional, slip


@njit(**_JIT)
def _layer_apply(k, t, fill, qty, notional, margin, fee, liq, reason, slip, raw, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
    """Áp một fill vào lớp: giữ chỗ vốn, giá vốn bình quân, vị thế mới, nhật ký lệnh."""
    amount = margin + fee
    LG[LG_RES] += amount
    F[k, F_RES_HERE] += margin + fee
    new_qty = F[k, F_QTY] + qty
    F[k, F_AVG] = (F[k, F_AVG] * F[k, F_QTY] + fill * qty) / new_qty
    F[k, F_QTY] = new_qty
    F[k, F_MU] += margin
    F[k, F_FP] += fee
    I[k, I_LAYERS] += 1
    F[k, F_LAST_FILL] = fill
    if I[k, I_POS] < 0:
        pidx = G[G_NPOS]
        G[G_NPOS] = pidx + 1
        I[k, I_POS] = pidx
        I[k, I_ENTRY_T] = t
        F[k, F_PEAK] = fill
        outF[pidx, O_ENTER_PRICE] = fill
        outF[pidx, O_ENTRY_MARGIN] = margin
        outF[pidx, O_ENTRY_NOTIONAL] = notional
        outF[pidx, O_ENTRY_FEE] = fee
        outF[pidx, O_MAXP] = fill
        outF[pidx, O_MINP] = fill
        outF[pidx, O_UNIT] = 0.0
        outF[pidx, O_LEVUSED] = 1.0
        outF[pidx, O_RISK] = 0.0
        outI[pidx, OI_TR] = k
        outI[pidx, OI_ENTER_T] = t
        outI[pidx, OI_FIRST_ORD] = G[G_NORD]
        outI[pidx, OI_START] = reason
    pidx = I[k, I_POS]
    _log_order(pidx, t, fill, qty, I[k, I_LAYERS] - 1, fee, 0, liq, raw, slip, ordF, ordI, G)
    I[k, I_OPEN] = 1


@njit(**_JIT)
def _add_layer(k, t, price, margin, market, reason, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
    if G[G_NPOS] >= outF.shape[0] or G[G_NORD] >= ordF.shape[0]:
        G[G_OVF] = 1
        return False
    ok, fill, fee, notional, slip = _layer_cost(k, price, margin, market, PI, P, F, LG, G)
    if ok != 0:
        return False
    qty = notional / fill
    _layer_apply(k, t, fill, qty, notional, margin, fee, 2 if (market or PI[k, PI_LTAKER] == 1) else 1, reason, slip, price, P, PI, F, I, LG, G, outF, outI, ordF, ordI)
    return True


@njit(**_JIT)
def _apply_exit_unit(k, unit, P, PI, F, I):
    """Quy đổi tham số thoát lệnh sang % cho vị thế sắp mở (đặt lại từ giá trị gốc: tầng DCA bị bỏ ở vị thế trước không ảnh hưởng)."""
    ml = (P.shape[1] - P_FIXED) // 2
    F[k, F_SL] = P[k, P_BSL] * unit
    F[k, F_TP] = P[k, P_BTP] * unit
    F[k, F_TRAIL] = P[k, P_BTR] * unit
    F[k, F_TACT] = P[k, P_BTA] * unit
    n = PI[k, PI_NBASE]
    for j in range(ml):
        F[k, F_DS0 + j] = 0.0
    for j in range(n):
        F[k, F_DS0 + j] = P[k, P_BS0 + j] * unit
    I[k, I_NST] = n


@njit(**_JIT)
def _layer_mult_total(k, n, P):
    ml = (P.shape[1] - P_FIXED) // 2
    total = 1.0
    m = 1.0
    for j in range(n):
        m *= P[k, P_BS0 + ml + j]
        total += m
    return total


@njit(**_JIT)
def _risk_margin(k, P, PI, F, I, LG, G):
    sl = F[k, F_SL] / 100.0
    total_mult = _layer_mult_total(k, I[k, I_NST], P)
    eq = LG[LG_EQ]
    if PI[k, PI_AMM] == 1:   # trượt giá phụ thuộc khối lượng: lần 1 chỉ tính phí, lần 2 tính trượt theo khối lượng dự kiến của lần 1 (policy.risk_margin)
        cap = eq * P[k, P_MAXNOT] / 100.0
        notional = _pmin(eq * P[k, P_RISK] / 100.0 / (sl + 2.0 * P[k, P_FEE]), cap)
        cost = _rt_cost(k, notional, P, PI, F, G)
        notional = _pmin(eq * P[k, P_RISK] / 100.0 / (sl + cost), cap)
    else:
        cost = 2.0 * (P[k, P_FEE] + P[k, P_SLIP])
        notional = eq * P[k, P_RISK] / 100.0 / (sl + cost)
        notional = _pmin(notional, eq * P[k, P_MAXNOT] / 100.0)
    if PI[k, PI_PERP] == 1:
        maxlev_i = np.int64(P[k, P_MAXLEV])
        if sl > 0.0:
            q = 1.0 / (1.5 * sl + P[k, P_MMR])
            safe = np.int64(q) if q < 4.0e18 else np.int64(4000000000000000000)
        else:
            safe = maxlev_i
        v = maxlev_i if maxlev_i < safe else safe          # min(int(max_leverage), safe)
        v = v if v > 1 else 1                              # max(1, ...)
        F[k, F_POS_LEV] = np.float64(v)
    F[k, F_PLANNED] = notional * (sl + cost)
    return notional / total_mult / F[k, F_POS_LEV]


@njit(**_JIT)
def _close_cost(k, raw_price, status, market, PI, P, F, G):
    """Giá/phí/trượt giá đóng hết vị thế (chưa áp dụng): -> (price, exit_fee, slip)."""
    long_ = PI[k, PI_LONG] == 1
    taker = market or PI[k, PI_LTAKER] == 1
    slip = 0.0
    if taker and status != S_LIQ:
        slip = _slip(k, F[k, F_QTY] * raw_price, not long_, P, PI, F, G)
        price = raw_price * ((1.0 - slip) if long_ else (1.0 + slip))
    else:
        price = raw_price
    exit_fee = F[k, F_QTY] * price * (P[k, P_FEE] if (taker or status == S_LIQ) else P[k, P_MAKER])
    return price, exit_fee, slip


@njit(**_JIT)
def _close_apply(k, t, price, exit_fee, status, reason, liq, slip, raw, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    long_ = PI[k, PI_LONG] == 1
    qty = F[k, F_QTY]
    avg = F[k, F_AVG]
    gross = qty * ((price - avg) if long_ else (avg - price))
    trade_cash = gross - F[k, F_FP] - exit_fee
    if status == S_LIQ:
        lim = -(F[k, F_MU] + F[k, F_FP] + exit_fee)
        trade_cash = lim if lim > trade_cash else trade_cash
    r = LG[LG_RES] - F[k, F_RES_HERE]
    LG[LG_RES] = r if r > 0.0 else 0.0                    # max(0.0, reserved - amount)
    LG[LG_EQ] = LG[LG_EQ] + trade_cash
    if LG[LG_EQ] > LG[LG_PEAK]:
        LG[LG_PEAK] = LG[LG_EQ]
    net = trade_cash - F[k, F_FUND]
    ee = F[k, F_ENTRY_EQ]
    pidx = I[k, I_POS]
    outF[pidx, O_CLOSE_PRICE] = price
    outF[pidx, O_PNL] = net
    outF[pidx, O_ENTRY_EQ] = ee
    outF[pidx, O_PCT] = net / ee * 100.0 if ee > 0.0 else 0.0
    outF[pidx, O_QTY] = qty
    outF[pidx, O_AVG] = avg
    outF[pidx, O_TOTAL_MARGIN] = F[k, F_MU]
    outF[pidx, O_EXIT_FEE] = exit_fee
    outF[pidx, O_FEES] = F[k, F_FP] + exit_fee
    outF[pidx, O_FUNDING] = F[k, F_FUND]
    if ee > 0.0:
        v = F[k, F_MAE] / ee * 100.0
        outF[pidx, O_MAE] = v if v < 0.0 else 0.0         # min(0.0, v)
    else:
        outF[pidx, O_MAE] = 0.0
    outI[pidx, OI_CLOSE_T] = t
    outI[pidx, OI_STATUS] = status
    outI[pidx, OI_LAYERS] = I[k, I_LAYERS]
    outI[pidx, OI_REASON] = reason
    _log_order(pidx, t, price, qty, I[k, I_LAYERS], exit_fee, 1, liq, raw, slip, ordF, ordI, G)
    ncl = G[G_NCL]
    if ncl < closeSeq.shape[0]:
        closeSeq[ncl] = pidx
    G[G_NCL] = ncl + 1
    I[k, I_OPEN] = 0
    I[k, I_PX] = 0
    I[k, I_POS] = -1
    I[k, I_LASTCLOSE] = t
    I[k, I_HASLC] = 1
    # _reset_state
    F[k, F_QTY] = 0.0
    F[k, F_AVG] = 0.0
    F[k, F_MU] = 0.0
    F[k, F_FP] = 0.0
    I[k, I_LAYERS] = 0
    F[k, F_LAST_FILL] = 0.0
    F[k, F_NEXT] = 0.0
    I[k, I_ENTRY_T] = 0
    F[k, F_PEAK] = 0.0
    F[k, F_MAE] = 0.0
    F[k, F_RES_HERE] = 0.0
    F[k, F_FUND] = 0.0
    F[k, F_ENTRY_EQ] = LG[LG_EQ]


@njit(**_JIT)
def _close(k, t, raw_price, status, reason, market, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    price, exit_fee, slip = _close_cost(k, raw_price, status, market, PI, P, F, G)
    if status == S_LIQ:
        liq = 3
    elif market or PI[k, PI_LTAKER] == 1:
        liq = 2
    else:
        liq = 1
    _close_apply(k, t, price, exit_fee, status, reason, liq, slip, raw_price, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)


@njit(**_JIT)
def _status_by_pnl(k, price, PI, F):
    move = (price - F[k, F_AVG]) if PI[k, PI_LONG] == 1 else (F[k, F_AVG] - price)
    return S_TP if move > 0.0 else S_SL


@njit(**_JIT)
def _open(k, t, open_price, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
    if LG[LG_EQ] <= 0.0:
        return
    unit = 1.0
    if PI[k, PI_ATR] == 1:
        unit = F[k, F_PVOL]
        if not (unit > 0.0):
            I[k, I_SKIP] += 1
            return
    _apply_exit_unit(k, unit, P, PI, F, I)
    unit_pct = unit if PI[k, PI_ATR] == 1 else 0.0
    F[k, F_UNIT] = unit_pct
    eq = LG[LG_EQ]
    F[k, F_ENTRY_EQ] = eq
    F[k, F_MAXCAP] = eq * P[k, P_CAPUSE]
    budget = _pmin(F[k, F_MAXCAP], LG[LG_EQ] - LG[LG_RES])
    F[k, F_POS_LEV] = P[k, P_MAXLEV]
    F[k, F_PLANNED] = 0.0
    lev = F[k, F_POS_LEV]
    if PI[k, PI_RISKSZ] == 1:
        margin = _risk_margin(k, P, PI, F, I, LG, G)
    else:
        margin = eq * P[k, P_OSP] / 100.0
    lev = F[k, F_POS_LEV]
    if rscale != 1.0:                                     # danh mục đang sụt vốn: thu nhỏ lệnh mới
        margin = margin * rscale
        F[k, F_PLANNED] = F[k, F_PLANNED] * rscale
    m = margin
    x = budget / (1.0 + lev * P[k, P_FEE])
    if x < m:
        m = x
    y = max_new / lev
    if y < m:
        m = y
    margin = m
    if PI[k, PI_RISKSZ] == 1 and margin > 0.0:
        total_mult = _layer_mult_total(k, I[k, I_NST], P)
        if PI[k, PI_AMM] == 1:
            v = margin * lev * (F[k, F_SL] / 100.0 + _rt_cost(k, margin * lev * total_mult, P, PI, F, G)) * total_mult
        else:
            v = margin * lev * (F[k, F_SL] / 100.0 + 2.0 * (P[k, P_FEE] + P[k, P_SLIP])) * total_mult
        F[k, F_PLANNED] = _pmin(F[k, F_PLANNED], v)
    if max_risk != np.inf and F[k, F_PLANNED] > max_risk:   # vượt trần rủi ro đang mở của danh mục
        if max_risk <= 0.0:
            margin = 0.0
        else:
            margin = margin * (max_risk / F[k, F_PLANNED])
            F[k, F_PLANNED] = max_risk
    if margin <= 0.0:
        G[G_REJ] += 1
        return
    if _add_layer(k, t, open_price, margin, True, R_ENTRY, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
        F[k, F_NEXT] = margin
        pidx = I[k, I_POS]
        outF[pidx, O_UNIT] = unit_pct
        outF[pidx, O_LEVUSED] = F[k, F_POS_LEV]
        outF[pidx, O_RISK] = F[k, F_PLANNED]


@njit(**_JIT)
def _better(long_, level, prio, best_level, best_prio):
    if long_:
        return level > best_level or (level == best_level and prio < best_prio)
    return level < best_level or (level == best_level and prio < best_prio)


@njit(**_JIT)
def _intrabar(k, t, o, h, l, c, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    if PI[k, PI_PATH] == 0:
        return _intrabar_adverse(k, t, o, h, l, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    return _intrabar_path(k, t, o, h, l, c, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)


@njit(**_JIT)
def _extreme_price(long_, level, price, adverse, ML, MH, ja, jb):
    """stop_fill='extreme': khớp ở giá xấu nhất của NẾN 1m đầu tiên chạm mức (ML/MH[ja:jb] = nến 1m trong nến chạy). Khung chạy 1m
    (ja == jb): chính nến đó -> giá xấu nhất của nến. Không tìm thấy (thiếu 1m) -> giá xấu nhất của nến chạy."""
    worst = adverse
    for j in range(ja, jb):
        if long_:
            if ML[j] <= level:
                worst = ML[j]
                break
        elif MH[j] >= level:
            worst = MH[j]
            break
    if long_:
        return worst if worst < price else price
    return worst if worst > price else price


@njit(**_JIT)
def _intrabar_path(k, t, o, h, l, c, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    """Đường ohlc / adaptive (bản dịch tracker._intrabar_path): mỗi chặng là một tick; trong tick (a) mọi tầng DCA bị xuyên qua,
    (b) chốt lời, (c) stop (SL / trailing / thanh lý). SL / TP cố định cả nến (lệnh đã nằm trên sàn từ cuối nến trước)."""
    long_ = PI[k, PI_LONG] == 1
    ltaker = PI[k, PI_LTAKER] == 1         # AMM: DCA / chốt lời là swap -> khớp ở open nếu gap qua mức (không phải lệnh limit chờ sẵn)
    adverse = l if long_ else h
    sign = 1.0 if long_ else -1.0
    ml = (P.shape[1] - P_FIXED) // 2
    has_sl = F[k, F_SL] != 0.0
    sl_lv = 0.0
    if has_sl:
        sl_lv = F[k, F_AVG] * (1.0 - sign * F[k, F_SL] / 100.0)
    has_tp = F[k, F_TP] != 0.0
    tp_lv = 0.0
    need = 0.0
    if has_tp:
        tp_lv = F[k, F_AVG] * (1.0 + sign * F[k, F_TP] / 100.0)
        need = tp_lv * (1.0 + sign * P[k, P_LTHRU]) if P[k, P_LTHRU] != 0.0 else tp_lv
    peak = F[k, F_PEAK]
    dca_filled = False
    prev = o
    high_first = PI[k, PI_PATH] == 1 or (h - o < o - l)
    for i in range(4):
        if i == 0:
            p = o
        elif i == 1:
            p = h if high_first else l
        elif i == 2:
            p = l if high_first else h
        else:
            p = c
        if i > 0 and p == prev:
            continue
        # (a) nhóm DCA
        while True:
            kk = I[k, I_LAYERS] - 1
            if not (kk < I[k, I_NST] and I[k, I_DCAOK] == 1):
                break
            dca_level = F[k, F_LAST_FILL] * (1.0 - sign * F[k, F_DS0 + kk] / 100.0)
            trig = dca_level * (1.0 - sign * P[k, P_LTHRU]) if P[k, P_LTHRU] != 0.0 else dca_level
            if not ((p <= trig) if long_ else (p >= trig)):
                break
            margin = F[k, F_NEXT] * P[k, P_BS0 + ml + kk]
            dca_price = dca_level
            if ltaker:
                dca_price = _pmin(dca_level, o) if long_ else _pmax(dca_level, o)   # policy.gap_fill
            if _add_layer(k, t, dca_price, margin, False, R_DCA, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
                F[k, F_NEXT] = margin
                dca_filled = True
                continue
            I[k, I_DCAREJ] += 1
            I[k, I_NST] = kk
        # (b) chốt lời
        if has_tp and ((p >= need) if long_ else (p <= need)):
            tp_price = tp_lv
            if ltaker:
                tp_price = _pmax(tp_lv, o) if long_ else _pmin(tp_lv, o)   # policy.tp_fill_price
            _close(k, t, tp_price, S_TP, R_TP, False, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
        # (c) nhóm stop: SL, trailing, thanh lý (hoà mức -> cái đứng trước)
        have = False
        best_level = 0.0
        best_kind = 0                      # 1 sl, 2 trail, 3 liq
        if has_sl:
            if (p <= sl_lv) if long_ else (p >= sl_lv):
                have = True
                best_level = sl_lv
                best_kind = 1
        if F[k, F_TRAIL] != 0.0:
            if F[k, F_AVG] != 0.0:
                gain_pct = sign * (peak - F[k, F_AVG]) / F[k, F_AVG] * 100.0
            else:
                gain_pct = 0.0
            if gain_pct >= F[k, F_TACT]:
                level = peak * (1.0 - sign * F[k, F_TRAIL] / 100.0)
                if (p <= level) if long_ else (p >= level):
                    if (not have) or _better(long_, level, 0, best_level, 0):
                        have = True
                        best_level = level
                        best_kind = 2
        if PI[k, PI_PERP] == 1 and F[k, F_QTY] > 0.0:
            if long_:
                liq = F[k, F_AVG] * (1.0 - 1.0 / F[k, F_POS_LEV] + P[k, P_MMR])
            else:
                liq = F[k, F_AVG] * (1.0 + 1.0 / F[k, F_POS_LEV] - P[k, P_MMR])
            if liq > 0.0:
                if (p <= liq) if long_ else (p >= liq):
                    if (not have) or _better(long_, liq, 0, best_level, 0):
                        have = True
                        best_level = liq
                        best_kind = 3
        if have:
            level = best_level
            if i == 0:
                if long_:
                    price = o if o < level else level          # chặng mở cửa: min(level, open) (gap)
                else:
                    price = o if o > level else level
            else:
                price = level                                  # trong nến: stop khớp ở mức kích hoạt
            if best_kind == 3:
                _close(k, t, price, S_LIQ, R_LIQ, False, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
                return True
            if PI[k, PI_EXTREME] == 1:
                price = _extreme_price(long_, level, price, adverse, ML, MH, ja, jb)
            if best_kind == 1:
                _close(k, t, price, S_SL, R_SL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
                return True
            _close(k, t, price, _status_by_pnl(k, price, PI, F), R_TRAIL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
        if long_:
            if p > peak:
                peak = p
        else:
            if p < peak:
                peak = p
        prev = p
    # cuối nến: TP đặt lại từ avg mới (sau fill DCA) đã "trong giá" ở close -> khớp ngay ở close (taker)
    if dca_filled and has_tp:
        tp_new = F[k, F_AVG] * (1.0 + sign * F[k, F_TP] / 100.0)
        if (c >= tp_new) if long_ else (c <= tp_new):
            _close(k, t, c, S_TP, R_TP, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
    return False


@njit(**_JIT)
def _intrabar_adverse(k, t, o, h, l, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    long_ = PI[k, PI_LONG] == 1
    ltaker = PI[k, PI_LTAKER] == 1
    adverse = l if long_ else h
    favorable = h if long_ else l
    sign = 1.0 if long_ else -1.0
    ml = (P.shape[1] - P_FIXED) // 2
    dca_filled = False
    has_stale = False                      # đã có SL CŨ còn hiệu lực (sau tầng DCA đầu tiên của nến, sl_pct > 0)
    sl_stale = 0.0
    while True:
        have = False
        best_level = 0.0
        best_prio = 0
        best_kind = 0                      # 0 dca, 1 sl, 2 trail, 3 liq
        kk = I[k, I_LAYERS] - 1
        dca_level = 0.0
        if kk < I[k, I_NST] and I[k, I_DCAOK] == 1:
            dca_level = F[k, F_LAST_FILL] * (1.0 - sign * F[k, F_DS0 + kk] / 100.0)
            level = dca_level * (1.0 - sign * P[k, P_LTHRU]) if P[k, P_LTHRU] != 0.0 else dca_level
            if (adverse <= level) if long_ else (adverse >= level):
                have = True
                best_level = level
                best_prio = 1
                best_kind = 0
        if F[k, F_SL] != 0.0:
            if has_stale:
                level = sl_stale
            else:
                level = F[k, F_AVG] * (1.0 - sign * F[k, F_SL] / 100.0)
            if (adverse <= level) if long_ else (adverse >= level):
                if (not have) or _better(long_, level, 0, best_level, best_prio):
                    have = True
                    best_level = level
                    best_prio = 0
                    best_kind = 1
        if F[k, F_TRAIL] != 0.0:
            if F[k, F_AVG] != 0.0:
                gain_pct = sign * (F[k, F_PEAK] - F[k, F_AVG]) / F[k, F_AVG] * 100.0
            else:
                gain_pct = 0.0
            if gain_pct >= F[k, F_TACT]:
                level = F[k, F_PEAK] * (1.0 - sign * F[k, F_TRAIL] / 100.0)
                if (adverse <= level) if long_ else (adverse >= level):
                    if (not have) or _better(long_, level, 0, best_level, best_prio):
                        have = True
                        best_level = level
                        best_prio = 0
                        best_kind = 2
        if PI[k, PI_PERP] == 1 and F[k, F_QTY] > 0.0:
            if long_:
                liq = F[k, F_AVG] * (1.0 - 1.0 / F[k, F_POS_LEV] + P[k, P_MMR])
            else:
                liq = F[k, F_AVG] * (1.0 + 1.0 / F[k, F_POS_LEV] - P[k, P_MMR])
            if liq > 0.0:
                if (adverse <= liq) if long_ else (adverse >= liq):
                    if (not have) or _better(long_, liq, 0, best_level, best_prio):
                        have = True
                        best_level = liq
                        best_prio = 0
                        best_kind = 3
        if not have:
            break
        level = best_level
        if long_:
            price = o if o < level else level                 # min(level, open)
        else:
            price = o if o > level else level                 # max(level, open)
        if best_kind == 0:
            price = dca_level                                     # lệnh limit chờ sẵn khớp ĐÚNG ở giá đặt, kể cả khi gap qua mức
            if ltaker:
                price = _pmin(dca_level, o) if long_ else _pmax(dca_level, o)   # AMM (swap): khớp ở open nếu gap
            margin = F[k, F_NEXT] * P[k, P_BS0 + ml + kk]
            sl_before = F[k, F_AVG] * (1.0 - sign * F[k, F_SL] / 100.0)   # SL đang nằm trên sàn trước fill (chỉ dùng khi sl_pct > 0)
            if _add_layer(k, t, price, margin, False, R_DCA, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
                F[k, F_NEXT] = margin
                if (not dca_filled) and F[k, F_SL] != 0.0:
                    has_stale = True                          # SL cũ chưa dời kịp trong phần còn lại của nến
                    sl_stale = sl_before
                dca_filled = True
                continue
            I[k, I_DCAREJ] += 1
            I[k, I_NST] = kk
            continue
        if best_kind == 3:
            _close(k, t, price, S_LIQ, R_LIQ, False, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
        if PI[k, PI_EXTREME] == 1:
            # bi quan: khớp ở giá xấu nhất của NẾN 1m đầu tiên chạm mức (ML/MH[ja:jb] = nến 1m trong nến chạy). Khung chạy 1m
            # (ja == jb): chính nến đó -> giá xấu nhất của nến như trước. Không tìm thấy (thiếu 1m) -> giá xấu nhất của nến chạy.
            worst = adverse
            for j in range(ja, jb):
                if long_:
                    if ML[j] <= level:
                        worst = ML[j]
                        break
                elif MH[j] >= level:
                    worst = MH[j]
                    break
            if long_:
                price = worst if worst < price else price
            else:
                price = worst if worst > price else price
        if best_kind == 1:
            _close(k, t, price, S_SL, R_SL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
        _close(k, t, price, _status_by_pnl(k, price, PI, F), R_TRAIL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
        return True
    if F[k, F_TP] != 0.0 and not dca_filled:
        tp_level = F[k, F_AVG] * (1.0 + sign * F[k, F_TP] / 100.0)
        need = tp_level * (1.0 + sign * P[k, P_LTHRU]) if P[k, P_LTHRU] != 0.0 else tp_level
        if (favorable >= need) if long_ else (favorable <= need):
            price = tp_level                                  # limit khớp ĐÚNG ở mức TP, kể cả khi open đã vượt mức
            if ltaker:
                price = _pmax(tp_level, o) if long_ else _pmin(tp_level, o)   # AMM (swap): khớp ở open nếu gap có lợi
            _close(k, t, price, S_TP, R_TP, False, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            return True
    return False


@njit(**_JIT)
def _on_bar_open(k, t, o, can_open, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    """Pha MỞ nến của tracker k (ADR P6 §10): thoát chờ / hết thời gian giữ ở open, rồi vào lệnh chờ ở open nếu can_open. Trả True nếu vị thế
    vừa đóng ở open (truyền cho _on_bar_rest)."""
    closed = False
    if I[k, I_OPEN] == 1:
        if I[k, I_PX] == 1:
            closed = True
            _close(k, t, o, _status_by_pnl(k, o, PI, F), R_STOP, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
        elif PI[k, PI_TIMEOUT] != 0 and t - I[k, I_ENTRY_T] >= PI[k, PI_TIMEOUT]:
            closed = True
            _close(k, t, o, _status_by_pnl(k, o, PI, F), R_TIMEOUT, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    if (not closed) and I[k, I_OPEN] == 0 and I[k, I_PE] == 1:
        I[k, I_PE] = 0
        if can_open:
            _open(k, t, o, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI)
    return closed


@njit(**_JIT)
def _on_bar_rest(k, t, o, h, l, c, ML, MH, ja, jb, entry_signal, stop_signal, closed_open, vol, dca_gate, P, PI, F, I, LG, G,
                 outF, outI, ordF, ordI, closeSeq):
    """Pha TRONG nến + cuối nến của tracker k: SL / TP / DCA / trailing / thanh lý theo đường giá, sổ sách cuối nến (đỉnh, MAE, cờ vào / thoát
    chờ). closed_open = kết quả _on_bar_open cùng nến. Trả True nếu vị thế đóng trong nến NÀY (cả đóng ở open thì trả closed_open)."""
    closed = closed_open
    long_ = PI[k, PI_LONG] == 1
    if I[k, I_OPEN] == 1 and not closed:
        pidx = I[k, I_POS]
        if h > outF[pidx, O_MAXP]:
            outF[pidx, O_MAXP] = h
        if l < outF[pidx, O_MINP]:
            outF[pidx, O_MINP] = l
        closed = _intrabar(k, t, o, h, l, c, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    if I[k, I_OPEN] == 1:
        adverse = l if long_ else h
        u = _unreal(k, adverse, PI, F, I)
        if u < F[k, F_MAE]:
            F[k, F_MAE] = u
        if long_:
            if h > F[k, F_PEAK]:
                F[k, F_PEAK] = h
        else:
            if l < F[k, F_PEAK]:
                F[k, F_PEAK] = l
        if stop_signal:
            I[k, I_PX] = 1
    elif (not closed) and entry_signal and (
            PI[k, PI_COOL] == 0 or I[k, I_HASLC] == 0 or t - I[k, I_LASTCLOSE] >= PI[k, PI_COOL]):
        I[k, I_PE] = 1
        F[k, F_PVOL] = vol
    I[k, I_DCAOK] = 1 if dca_gate else 0
    return closed


@njit(**_JIT)
def _on_bar(k, t, o, h, l, c, ML, MH, ja, jb, entry_signal, stop_signal, can_open, max_new, vol, dca_gate, max_risk, rscale, P, PI, F, I, LG, G,
            outF, outI, ordF, ordI, closeSeq):
    """Một nến có giao dịch cho tracker k (đường đơn tài sản) = _on_bar_open + _on_bar_rest. Trả True nếu vị thế vừa đóng."""
    closed = _on_bar_open(k, t, o, can_open, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    return _on_bar_rest(k, t, o, h, l, c, ML, MH, ja, jb, entry_signal, stop_signal, closed, vol, dca_gate, P, PI, F, I, LG, G,
                        outF, outI, ordF, ordI, closeSeq)


@njit(**_JIT)
def _quiet_bar(k, t, o, h, l, peak, P, PI, F, I):
    """True nếu nến (t, o, h, l) KHÔNG kích hoạt gì cho vị thế đang mở k: không timeout, không chạm DCA / SL / trailing / thanh lý / TP,
    với `peak` = đỉnh có lợi tính tới nến TRƯỚC. Cùng biểu thức (cùng thứ tự phép toán float) với _on_bar/_intrabar khi chúng không làm gì
    -> tua nhanh qua các nến yên tĩnh cho kết quả bit-identical (test_kernel_parity)."""
    if PI[k, PI_TIMEOUT] != 0 and t - I[k, I_ENTRY_T] >= PI[k, PI_TIMEOUT]:
        return False
    long_ = PI[k, PI_LONG] == 1
    adverse = l if long_ else h
    favorable = h if long_ else l
    sign = 1.0 if long_ else -1.0
    kk = I[k, I_LAYERS] - 1
    if kk < I[k, I_NST] and I[k, I_DCAOK] == 1:
        level = F[k, F_LAST_FILL] * (1.0 - sign * F[k, F_DS0 + kk] / 100.0)
        if P[k, P_LTHRU] != 0.0:
            level = level * (1.0 - sign * P[k, P_LTHRU])
        if (adverse <= level) if long_ else (adverse >= level):
            return False
    if F[k, F_SL] != 0.0:
        level = F[k, F_AVG] * (1.0 - sign * F[k, F_SL] / 100.0)
        if (adverse <= level) if long_ else (adverse >= level):
            return False
    if F[k, F_TRAIL] != 0.0:
        pk = peak
        if PI[k, PI_PATH] != 0:
            # đường ohlc / adaptive: đỉnh chạy theo từng chặng -> dùng đỉnh CẢ nến (bao trùm mọi chặng; nến "không yên tĩnh" thừa chỉ chạy chậm hơn, không sai)
            if long_:
                pk = h if h > peak else peak
            else:
                pk = l if l < peak else peak
        if F[k, F_AVG] != 0.0:
            gain_pct = sign * (pk - F[k, F_AVG]) / F[k, F_AVG] * 100.0
        else:
            gain_pct = 0.0
        if gain_pct >= F[k, F_TACT]:
            level = pk * (1.0 - sign * F[k, F_TRAIL] / 100.0)
            if (adverse <= level) if long_ else (adverse >= level):
                return False
    if PI[k, PI_PERP] == 1 and F[k, F_QTY] > 0.0:
        if long_:
            liq = F[k, F_AVG] * (1.0 - 1.0 / F[k, F_POS_LEV] + P[k, P_MMR])
        else:
            liq = F[k, F_AVG] * (1.0 + 1.0 / F[k, F_POS_LEV] - P[k, P_MMR])
        if liq > 0.0:
            if (adverse <= liq) if long_ else (adverse >= liq):
                return False
    if F[k, F_TP] != 0.0:
        tp_level = F[k, F_AVG] * (1.0 + sign * F[k, F_TP] / 100.0)
        if P[k, P_LTHRU] != 0.0:
            tp_level = tp_level * (1.0 + sign * P[k, P_LTHRU])
        if (favorable >= tp_level) if long_ else (favorable <= tp_level):
            return False
    return True


# ─── Tiện ích tìm kiếm ──────────────────────────────────────────────────────
@njit(**_JIT)
def _lower(arr, x, n):
    """searchsorted(arr[:n], x, 'left')."""
    lo = 0
    hi = n
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


@njit(**_JIT)
def _upper_abs(arr, x, lo, hi):
    """Chỉ số tuyệt đối đầu tiên trong [lo, hi) có arr[i] > x (searchsorted 'right' trên đoạn con)."""
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


@njit(**_JIT)
def _any_active(I, nt):
    for k in range(nt):
        if I[k, I_OPEN] == 1 or I[k, I_PE] == 1 or I[k, I_PX] == 1:
            return True
    return False


@njit(**_JIT)
def _sample(t, mtm, worst, eqT, eqM, eqW, G):
    j = G[G_NSMP]
    if j >= eqT.shape[0]:
        G[G_OVF] = 1
        return
    eqT[j] = t
    eqM[j] = mtm
    eqW[j] = worst
    G[G_NSMP] = j + 1


# ─── Vòng lặp DANH MỤC (PortfolioEngine.run) ────────────────────────────────
# Chỉ số mảng trạng thái danh mục (P9.4b T1): PS float64, PSI int64, LPX[nb,4] = (close, low, high, open) của nến cuối đã xử lý (NaN = chưa có).
PS_PEAK_MTM, PS_MTM, PS_WORST = 0, 1, 2
PS_N = 3
(PSI_G, PSI_HALTED, PSI_HALT_AT, PSI_RUIN_AT, PSI_HAS_SMP, PSI_LAST_SMP, PSI_BUSY, PSI_LAST_T) = range(8)
PSI_N = 8
# BAR[nb,4] = (o,h,l,c); BARI[nb,3] = (có nến, ja, jb)
# BARI[nb,8] = (có nến, ja, jb, FR_lo, FR_hi, địa chỉ 1m low, địa chỉ 1m high, độ dài 1m); SIG[nt,5] = (match, stop, dca_gate, slot chạy ở nến này, đã đóng ở open nến này)


def new_portfolio_state(nb, init_cap):
    """(PS, PSI, LPX) khởi tạo cho PortfolioEngine / từng nến."""
    PS = np.zeros(PS_N, dtype=np.float64)
    PS[PS_PEAK_MTM] = init_cap
    PSI = np.zeros(PSI_N, dtype=np.int64)
    PSI[PSI_HALT_AT] = NONE_I
    PSI[PSI_RUIN_AT] = NONE_I
    LPX = np.full((nb, 4), np.nan, dtype=np.float64)
    return PS, PSI, LPX


@njit(**_JIT)
def _admit(k, t, b, can_trade, g, tr_book, book_off, I, F, cfg_i, cfg_f, LPX, LG, G):
    """Xét hạn mức mở lệnh cho slot k (sổ b) tại open nến g (trạng thái LÚC MỞ NẾN: LPX còn là nến TRƯỚC nên gross theo đóng nến trước,
    vốn = sổ vốn sau funding + lệnh thoát ở open). Trả (can_open, max_new, max_risk, rscale); ghi G_RISKMIN / G_ATT / I_BLK."""
    nt = tr_book.shape[0]
    nb = book_off.shape[0] - 1
    max_pos = cfg_i[1]
    max_per = cfg_i[2]
    cap = cfg_f[1]
    risk_cap = cfg_f[3]                          # trần Σ rủi ro tới SL của vị thế mở (tỉ lệ vốn); 0 = tắt
    thr = cfg_f[4]                               # giảm rủi ro theo mức sụt vốn đã chốt (tỉ lệ); 0 = tắt
    thr_floor = cfg_f[5]
    can_open = False
    max_new = np.inf
    max_risk = np.inf
    rscale = 1.0
    if can_trade and I[k, I_PE] == 1 and I[k, I_OPEN] == 0:
        n_open = 0
        per_b = 0
        total = 0.0
        for kk in range(nt):
            if I[kk, I_OPEN] == 1:
                n_open += 1
                if tr_book[kk] == b:
                    per_b += 1
        blocked = n_open >= max_pos or per_b >= max_per
        if not blocked:
            total = 0.0
            for bb in range(nb):
                px = LPX[bb, 0]
                if px != px:
                    continue
                for kk in range(book_off[bb], book_off[bb + 1]):
                    if I[kk, I_OPEN] == 1:
                        total += F[kk, F_QTY] * px
            room = cap * LG[LG_EQ] - total
            max_new = _pmax(0.0, room)
            can_open = room > 0.0
            if can_open and risk_cap != 0.0:
                open_risk = 0.0
                for kk in range(nt):
                    if I[kk, I_OPEN] == 1:
                        open_risk += F[kk, F_PLANNED]
                max_risk = risk_cap * LG[LG_EQ] - open_risk
                can_open = max_risk > 0.0
            if can_open and thr != 0.0 and LG[LG_PEAK] > 0.0:
                rscale = 1.0 - (1.0 - LG[LG_EQ] / LG[LG_PEAK]) / thr
                if rscale < thr_floor:
                    rscale = thr_floor
                if rscale > 1.0:
                    rscale = 1.0
            blocked = not can_open
        if cfg_i[CI_ADM_ON] != 0:                # vết admission (nautilus harness): chỉ ghi, không đổi quyết định; tràn -> bỏ bản ghi, không G_OVF
            j = G[G_NADM]
            G[G_NADM] = j + 1
            if j < cfg_i[CI_ADM_CAP]:
                ADM = carray(_ptr(cfg_i[CI_ADM_PTR]), (cfg_i[CI_ADM_CAP], NAD), np.float64)
                ADM[j, AD_T] = t
                ADM[j, AD_K] = k
                ADM[j, AD_NOPEN] = n_open
                ADM[j, AD_PERB] = per_b
                ADM[j, AD_EQ] = LG[LG_EQ]
                ADM[j, AD_GROSS] = total
                ADM[j, AD_CAN] = 1.0 if can_open else 0.0
                ADM[j, AD_MAXNEW] = max_new
        if blocked:
            G[G_RISKMIN] += 1
            if I[k, I_BLK] != g - 1:
                G[G_ATT] += 1
            I[k, I_BLK] = g
    return can_open, max_new, max_risk, rscale


@njit(**_JIT)
def _portfolio_mtm(book_off, PI, F, I, LPX, LG, PS):
    """MTM + MTM xấu nhất (low cho long / high cho short) của các vị thế mở theo LPX -> PS[PS_MTM], PS[PS_WORST]."""
    nb = book_off.shape[0] - 1
    mtm = LG[LG_EQ]
    worst = LG[LG_EQ]
    for b in range(nb):
        for k in range(book_off[b], book_off[b + 1]):
            if I[k, I_OPEN] == 1:
                mtm += _unreal(k, LPX[b, 0], PI, F, I)
                worst += _unreal(k, LPX[b, 1] if PI[k, PI_LONG] == 1 else LPX[b, 2], PI, F, I)
    PS[PS_MTM] = mtm
    PS[PS_WORST] = worst


@njit(**_JIT)
def _portfolio_bar(t, BAR, BARI, FR, SIG, SIGV, tr_book, book_off, P, PI, F, I, cfg_i, cfg_f, PS, PSI, LPX,
                   outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, ffwd):
    """Thân MỘT nến lưới của danh mục (mọi sổ có nến ở t): pha 1 (funding, luật bỏ qua, _admit, _on_bar_open mọi slot), pha 2 (_on_bar_rest
    từng slot rồi LPX[b]), pha 3 (MTM, đỉnh, kill switch, mẫu vốn; bỏ qua khi ffwd và chưa đến hạn mẫu), rồi PSI[PSI_G] += 1.
    BAR[b] = (o,h,l,c); BARI[b] = (có nến, ja, jb, FR_lo, FR_hi, địa chỉ 1m low, địa chỉ 1m high, độ dài 1m); FR[FR_lo:FR_hi] = funding đến hạn (<= t) của sổ b; SIG[k] = (match, stop, dca_gate, act, closed_open); SIGV[k] = vol."""
    nb = book_off.shape[0] - 1
    trade_start = cfg_i[0]
    step = cfg_i[4]
    kill = cfg_f[2]
    g = PSI[PSI_G]
    can_trade = t >= trade_start and PSI[PSI_HALTED] == 0
    touched = False
    busy = False
    PSI[PSI_LAST_T] = t
    # Pha 1 — MỞ NẾN (mọi sổ theo thứ tự): funding, rồi từng slot: luật bỏ qua, xét hạn mức và thoát / vào ở open. Chưa sổ nào chạy trong nến.
    for b in range(nb):
        if BARI[b, 0] == 0:
            continue
        o = BAR[b, 0]
        for f in range(BARI[b, 3], BARI[b, 4]):
            rate = FR[f]
            for k in range(book_off[b], book_off[b + 1]):
                _apply_funding(k, rate, o, PI, F, I, LG)
        for k in range(book_off[b], book_off[b + 1]):
            if I[k, I_OPEN] == 0 and I[k, I_PE] == 0 and not SIG[k, 0]:
                SIG[k, 3] = False
                continue
            SIG[k, 3] = True
            if can_trade and I[k, I_PE] == 1 and I[k, I_OPEN] == 0:
                can_open, max_new, max_risk, rscale = _admit(k, t, b, can_trade, g, tr_book, book_off, I, F, cfg_i, cfg_f, LPX, LG, G)
            else:
                can_open = False
                max_new = np.inf
                max_risk = np.inf
                rscale = 1.0
            closed = _on_bar_open(k, t, o, can_open, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            SIG[k, 4] = closed
            if closed and LG[LG_EQ] <= 0.0 and PSI[PSI_RUIN_AT] == NONE_I:
                PSI[PSI_RUIN_AT] = t
    # Pha 2 — TRONG NẾN (mọi sổ theo thứ tự): SL / TP / DCA / trailing / thanh lý + sổ sách cuối nến, rồi LPX[b] (= nến này).
    for b in range(nb):
        if BARI[b, 0] == 0:
            continue
        o = BAR[b, 0]
        h = BAR[b, 1]
        l = BAR[b, 2]
        c = BAR[b, 3]
        ja = BARI[b, 1]
        jb = BARI[b, 2]
        ML = carray(_ptr(BARI[b, 5]), (BARI[b, 7],), np.float64)
        MH = carray(_ptr(BARI[b, 6]), (BARI[b, 7],), np.float64)
        for k in range(book_off[b], book_off[b + 1]):
            if not SIG[k, 3]:
                continue
            closed = _on_bar_rest(k, t, o, h, l, c, ML, MH, ja, jb, SIG[k, 0] and can_trade, SIG[k, 1], SIG[k, 4], SIGV[k], SIG[k, 2],
                                  P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            if I[k, I_OPEN] == 1 or I[k, I_PE] == 1:
                busy = True
            if closed and (not SIG[k, 4]) and LG[LG_EQ] <= 0.0 and PSI[PSI_RUIN_AT] == NONE_I:
                PSI[PSI_RUIN_AT] = t
        LPX[b, 0] = c
        LPX[b, 1] = l
        LPX[b, 2] = h
        LPX[b, 3] = o
        touched = True
    PSI[PSI_G] = g + 1
    PSI[PSI_BUSY] = 1 if busy else 0
    if not touched:
        return
    if ffwd and PSI[PSI_HAS_SMP] != 0 and t - PSI[PSI_LAST_SMP] < step:
        return                                   # không kill switch: MTM chỉ dùng cho mẫu vốn theo giờ
    # Pha 3 — _mtm, đỉnh, kill, mẫu vốn
    _portfolio_mtm(book_off, PI, F, I, LPX, LG, PS)
    PS[PS_PEAK_MTM] = _pmax(PS[PS_PEAK_MTM], PS[PS_MTM])
    if kill != 0.0 and PSI[PSI_HALTED] == 0 and PS[PS_WORST] <= PS[PS_PEAK_MTM] * (1.0 - kill):
        PSI[PSI_HALTED] = 1
        PSI[PSI_HALT_AT] = t
        for b in range(nb):
            for k in range(book_off[b], book_off[b + 1]):
                I[k, I_PE] = 0
                if I[k, I_OPEN] == 1:
                    _close(k, t, LPX[b, 0], S_CANCEL, R_KILL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
        _portfolio_mtm(book_off, PI, F, I, LPX, LG, PS)
    if PSI[PSI_HAS_SMP] == 0 or t - PSI[PSI_LAST_SMP] >= step:
        _sample(t, PS[PS_MTM], PS[PS_WORST], eqT, eqM, eqW, G)
        PSI[PSI_LAST_SMP] = t
        PSI[PSI_HAS_SMP] = 1


@njit(**_JIT)
def _portfolio_end(t_end, close_end, close_col, tclose, book_off, P, PI, F, I, LPX, PS, PSI, LG, G, outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW):
    """Cuối lượt: (close_end) đóng mọi vị thế mở tại LPX[b, close_col] (cột 3 = open cho batch; cột 0 = close cho tick close_all) ở thời điểm
    tclose[b]; mẫu vốn cuối ở t_end theo LPX; ghi G_HALT / G_RUIN."""
    nb = book_off.shape[0] - 1
    if close_end == 1:
        for b in range(nb):
            for k in range(book_off[b], book_off[b + 1]):
                if I[k, I_OPEN] == 1:
                    I[k, I_PE] = 0
                    _close(k, tclose[b], LPX[b, close_col], S_CANCEL, R_END, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    _portfolio_mtm(book_off, PI, F, I, LPX, LG, PS)
    _sample(t_end, PS[PS_MTM], PS[PS_WORST], eqT, eqM, eqW, G)
    G[G_HALT] = PSI[PSI_HALT_AT]
    G[G_RUIN] = PSI[PSI_RUIN_AT]


@njit(**_JIT)
def _portfolio_views(PB, BL, PE, tr_book, n):
    """View mảng (không sao chép) của dữ liệu từng sổ / từng slot."""
    nb = BL.shape[0]
    nt = PE.shape[0]
    Ts = [carray(_ptr(PB[b, 0]), (BL[b, 0],), np.int64) for b in range(nb)]
    Os = [carray(_ptr(PB[b, 1]), (BL[b, 0],), np.float64) for b in range(nb)]
    Hs = [carray(_ptr(PB[b, 2]), (BL[b, 0],), np.float64) for b in range(nb)]
    Ls = [carray(_ptr(PB[b, 3]), (BL[b, 0],), np.float64) for b in range(nb)]
    Cs = [carray(_ptr(PB[b, 4]), (BL[b, 0],), np.float64) for b in range(nb)]
    Fts = [carray(_ptr(PB[b, 5]), (BL[b, 1],), np.int64) for b in range(nb)]
    Frs = [carray(_ptr(PB[b, 6]), (BL[b, 1],), np.float64) for b in range(nb)]
    Ims = [carray(_ptr(PB[b, 7]), (n if BL[b, 2] == 1 else 1,), np.int64) for b in range(nb)]
    MAs = [carray(_ptr(PB[b, 8]), (BL[b, 0] if BL[b, 4] > 0 else 1,), np.int64) for b in range(nb)]
    MBs = [carray(_ptr(PB[b, 9]), (BL[b, 0] if BL[b, 4] > 0 else 1,), np.int64) for b in range(nb)]
    MLs = [carray(_ptr(PB[b, 10]), (BL[b, 4] if BL[b, 4] > 0 else 1,), np.float64) for b in range(nb)]
    MHs = [carray(_ptr(PB[b, 11]), (BL[b, 4] if BL[b, 4] > 0 else 1,), np.float64) for b in range(nb)]
    Ms = [carray(_ptr(PE[e, 0]), (BL[tr_book[e], 0],), np.bool_) for e in range(nt)]
    Ss = [carray(_ptr(PE[e, 1]), (BL[tr_book[e], 0],), np.bool_) for e in range(nt)]
    Vs = [carray(_ptr(PE[e, 2]), (BL[tr_book[e], 0],), np.float64) for e in range(nt)]
    Gs = [carray(_ptr(PE[e, 4]), (BL[tr_book[e], 0] if PE[e, 5] == 1 else 1,), np.bool_) for e in range(nt)]

    return Ts, Os, Hs, Ls, Cs, Fts, Frs, Ims, MAs, MBs, MLs, MHs, Ms, Ss, Vs, Gs


@njit(**_JIT)
def portfolio_kernel(PB, BL, PE, tr_book, book_off, P, PI, F, I, cfg_i, cfg_f,
                     outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, last_px):
    """PB[b] = (t,o,h,l,c,f_t,f_r,idxm,m_a,m_b,m_l,m_h) địa chỉ (m_*: nến 1m trong nến chạy cho khớp "extreme");
    BL[b] = (n_bars, n_funding, mapped, last_t, n_1m); PE[e] = (match, stop, vol, có_vol) (địa chỉ).
    cfg_i = (trade_start, max_positions, max_per_symbol, close_at_end, step_ms, địa chỉ lưới, độ dài lưới); cfg_f = (initial, gross_cap, kill_frac).
    last_px[b] = (close, low, high, open) của nến cuối đã xử lý; G/LG/I/F/outputs cập nhật tại chỗ.
    Vòng batch: tua nhanh / bỏ qua nến rảnh ở đây; mỗi nến thật nạp BAR/SIG/funding rồi gọi _portfolio_bar (thân dùng chung với paper/live)."""
    n = cfg_i[6]
    grid = carray(_ptr(cfg_i[5]), (n,), np.int64)
    nb = book_off.shape[0] - 1
    nt = PE.shape[0]
    trade_start = cfg_i[0]
    close_end = cfg_i[3]
    step = cfg_i[4]
    init_cap = cfg_f[0]
    kill = cfg_f[2]
    ffwd = kill == 0.0                           # tua nhanh phút yên tĩnh chỉ khi không có kill switch (cần MTM từng phút)

    Ts, Os, Hs, Ls, Cs, Fts, Frs, Ims, MAs, MBs, MLs, MHs, Ms, Ss, Vs, Gs = _portfolio_views(PB, BL, PE, tr_book, n)

    # funding phẳng: FR[foff[b] : foff[b+1]] = Frs[b]
    foff = np.zeros(nb + 1, dtype=np.int64)
    for b in range(nb):
        foff[b + 1] = foff[b] + BL[b, 1]
    FR = np.empty(foff[nb] if foff[nb] > 0 else 1, dtype=np.float64)
    for b in range(nb):
        for q in range(BL[b, 1]):
            FR[foff[b] + q] = Frs[b][q]

    # phút có tín hiệu vào của BẤT KỲ chiến lược × tài sản nào
    sig_any = np.zeros(n, dtype=np.bool_)
    for e in range(nt):
        b = tr_book[e]
        if BL[b, 2] == 0:
            m = Ms[e]
            for g in range(n):
                if m[g]:
                    sig_any[g] = True
        else:
            m = Ms[e]
            im = Ims[b]
            for g in range(n):
                i = im[g]
                if i >= 0 and m[i]:
                    sig_any[g] = True
    ts_g = _lower(grid, trade_start, n)

    PS = np.zeros(PS_N, dtype=np.float64)
    PS[PS_PEAK_MTM] = init_cap
    PSI = np.zeros(PSI_N, dtype=np.int64)
    PSI[PSI_HALT_AT] = NONE_I
    PSI[PSI_RUIN_AT] = NONE_I
    LPX = np.full((nb, 4), np.nan, dtype=np.float64)
    f_ptr = np.zeros(nb, dtype=np.int64)
    BAR = np.zeros((nb, 4), dtype=np.float64)
    BARI = np.zeros((nb, 8), dtype=np.int64)
    for b in range(nb):
        BARI[b, 5] = PB[b, 10]
        BARI[b, 6] = PB[b, 11]
        BARI[b, 7] = BL[b, 4] if BL[b, 4] > 0 else 1
    SIG = np.zeros((nt, 5), dtype=np.bool_)
    SIGV = np.zeros(nt, dtype=np.float64)
    g = 0
    while g < n:
        if G[G_OVF] != 0:
            break
        if PSI[PSI_BUSY] == 0 and (not _any_active(I, nt)):
            if PSI[PSI_HALTED] != 0:
                land = n
            else:
                land = ts_g if ts_g > g else g
                while land < n and not sig_any[land]:
                    land += 1
            if land > g:
                PS[PS_PEAK_MTM] = _pmax(PS[PS_PEAK_MTM], LG[LG_EQ])
                # _skip_idle: mọi tracker phẳng
                for b in range(nb):
                    j = land - 1                       # nến thật cuối của sổ b trong [g, land)
                    ii = -1
                    if BL[b, 2] == 0:
                        ii = j
                    else:
                        while j >= g:
                            if Ims[b][j] >= 0:
                                ii = Ims[b][j]
                                break
                            j -= 1
                    if ii >= 0:
                        LPX[b, 0] = Cs[b][ii]
                        LPX[b, 1] = Ls[b][ii]
                        LPX[b, 2] = Hs[b][ii]
                        LPX[b, 3] = Os[b][ii]
                        fp = _upper_abs(Fts[b], Ts[b][ii], 0, BL[b, 1])
                        if fp > f_ptr[b]:
                            f_ptr[b] = fp
                k = g if PSI[PSI_HAS_SMP] == 0 else _lower(grid, PSI[PSI_LAST_SMP] + step, n)
                while k < land:
                    PSI[PSI_LAST_SMP] = grid[k]
                    PSI[PSI_HAS_SMP] = 1
                    _sample(grid[k], LG[LG_EQ], LG[LG_EQ], eqT, eqM, eqW, G)
                    k = _lower(grid, PSI[PSI_LAST_SMP] + step, n)
                g = land
                continue
        if ffwd and PSI[PSI_BUSY] != 0:
            # Tua nhanh qua các phút YÊN TĨNH (không có kill switch nên MTM từng phút không ảnh hưởng gì ngoài mẫu vốn theo giờ):
            # dừng ở phút sớm nhất có việc — mẫu vốn đến hạn, funding của sổ đang có vị thế, tín hiệu vào của tracker phẳng, vị thế mở
            # chạm DCA/SL/trailing/thanh lý/TP/timeout hoặc có tín hiệu thoát. Phút đó xử lý như thường.
            lim = _lower(grid, PSI[PSI_LAST_SMP] + step, n) if PSI[PSI_HAS_SMP] != 0 else g
            for k in range(nt):
                if I[k, I_PE] == 1 or I[k, I_PX] == 1:
                    lim = g
                    break
            for b in range(nb):
                if lim <= g:
                    break
                has_open = False
                for k in range(book_off[b], book_off[b + 1]):
                    if I[k, I_OPEN] == 1:
                        has_open = True
                if has_open and f_ptr[b] < BL[b, 1]:
                    fi = _lower(grid, Fts[b][f_ptr[b]], n)
                    if fi < lim:
                        lim = fi
                for k in range(book_off[b], book_off[b + 1]):
                    if I[k, I_OPEN] == 1:
                        continue
                    m = Ms[k]
                    j = g
                    while j < lim:
                        if BL[b, 2] == 0:
                            i = j
                        else:
                            i = Ims[b][j]
                            if i < 0:
                                j += 1
                                continue
                        if m[i]:
                            tj = grid[j]          # tín hiệu chỉ có tác dụng khi được giao dịch và hết cooldown (như _on_bar)
                            if tj >= trade_start and (PI[k, PI_COOL] == 0 or I[k, I_HASLC] == 0
                                                      or tj - I[k, I_LASTCLOSE] >= PI[k, PI_COOL]):
                                lim = j
                                break
                        j += 1
            for b in range(nb):
                for k in range(book_off[b], book_off[b + 1]):
                    if lim <= g:
                        break
                    if I[k, I_OPEN] == 0:
                        continue
                    long_ = PI[k, PI_LONG] == 1
                    peak = F[k, F_PEAK]
                    s = Ss[k]
                    has_gate = PE[k, 5] == 1
                    gk = Gs[k]
                    ok_now = I[k, I_DCAOK] == 1
                    j = g
                    while j < lim:
                        if BL[b, 2] == 0:
                            i = j
                        else:
                            i = Ims[b][j]
                            if i < 0:
                                j += 1
                                continue
                        # điều kiện DCA đổi ở nến này -> phải xử lý nến này để cập nhật trạng thái dồn tầng cho nến sau
                        if s[i] or (has_gate and gk[i] != ok_now) or not _quiet_bar(k, grid[j], Os[b][i], Hs[b][i], Ls[b][i], peak, P, PI, F, I):
                            lim = j
                            break
                        if long_:
                            if Hs[b][i] > peak:
                                peak = Hs[b][i]
                        else:
                            if Ls[b][i] < peak:
                                peak = Ls[b][i]
                        j += 1
            if lim > g:
                # áp đúng các cập nhật của từng phút yên tĩnh: max/min giá, MAE, đỉnh; nến thật cuối của từng sổ
                for b in range(nb):
                    j = lim - 1
                    ii = -1
                    if BL[b, 2] == 0:
                        ii = j
                    else:
                        while j >= g:
                            if Ims[b][j] >= 0:
                                ii = Ims[b][j]
                                break
                            j -= 1
                    if ii >= 0:
                        LPX[b, 0] = Cs[b][ii]
                        LPX[b, 1] = Ls[b][ii]
                        LPX[b, 2] = Hs[b][ii]
                        LPX[b, 3] = Os[b][ii]
                    for k in range(book_off[b], book_off[b + 1]):
                        if I[k, I_OPEN] == 0:
                            continue
                        long_ = PI[k, PI_LONG] == 1
                        pidx = I[k, I_POS]
                        for j in range(g, lim):
                            if BL[b, 2] == 0:
                                i = j
                            else:
                                i = Ims[b][j]
                                if i < 0:
                                    continue
                            h = Hs[b][i]
                            l = Ls[b][i]
                            if h > outF[pidx, O_MAXP]:
                                outF[pidx, O_MAXP] = h
                            if l < outF[pidx, O_MINP]:
                                outF[pidx, O_MINP] = l
                            u = _unreal(k, l if long_ else h, PI, F, I)
                            if u < F[k, F_MAE]:
                                F[k, F_MAE] = u
                            if long_:
                                if h > F[k, F_PEAK]:
                                    F[k, F_PEAK] = h
                            else:
                                if l < F[k, F_PEAK]:
                                    F[k, F_PEAK] = l
                g = lim
                continue
        t = grid[g]
        # nạp nến / funding đến hạn / tín hiệu của từng sổ có nến ở phút g
        for b in range(nb):
            if BL[b, 2] == 0:
                i = g
            else:
                i = Ims[b][g]
                if i < 0:
                    BARI[b, 0] = 0
                    continue
            BARI[b, 0] = 1
            BAR[b, 0] = Os[b][i]
            BAR[b, 1] = Hs[b][i]
            BAR[b, 2] = Ls[b][i]
            BAR[b, 3] = Cs[b][i]
            if BL[b, 4] > 0:
                BARI[b, 1] = MAs[b][i]
                BARI[b, 2] = MBs[b][i]
            else:
                BARI[b, 1] = 0
                BARI[b, 2] = 0
            fe = BL[b, 1]
            BARI[b, 3] = foff[b] + f_ptr[b]
            while f_ptr[b] < fe and Fts[b][f_ptr[b]] <= t:
                f_ptr[b] += 1
            BARI[b, 4] = foff[b] + f_ptr[b]
            for k in range(book_off[b], book_off[b + 1]):
                m_k = Ms[k][i]
                SIG[k, 0] = m_k
                if m_k or I[k, I_OPEN] == 1 or I[k, I_PE] == 1:      # slot không chạy ở nến này thì _portfolio_bar không đọc SIG[k,1:] / SIGV[k]
                    SIG[k, 1] = Ss[k][i]
                    SIG[k, 2] = Gs[k][i] if PE[k, 5] == 1 else True
                    SIGV[k] = Vs[k][i] if PE[k, 3] == 1 else np.nan
        PSI[PSI_G] = g
        _portfolio_bar(t, BAR, BARI, FR, SIG, SIGV, tr_book, book_off, P, PI, F, I, cfg_i, cfg_f, PS, PSI, LPX,
                       outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, ffwd)
        g = PSI[PSI_G]

    for b in range(nb):
        for q in range(4):
            last_px[b, q] = LPX[b, q]
    _portfolio_end(grid[n - 1], close_end, 3, BL[:, 3], book_off, P, PI, F, I, LPX, PS, PSI, LG, G, outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW)


# ─── P9.4b T3 — các điểm vào Python-gọi-được: cùng thân nến `_portfolio_bar` chạy TỪNG NẾN / TỪNG KHÚC (paper, SlotDriver, test) ───
# Hợp đồng bit-identical với portfolio_kernel: cùng thứ tự pha, cùng con trỏ funding (do bên gọi nạp BARI[.., 3:5] / FR), cùng bộ đếm lưới PSI_G.
# PSI_G tăng 1 sau MỖI nến được bước (portfolio_kernel đặt PSI_G = chỉ số lưới trước khi gọi thân nến; nó bỏ qua phút rảnh / tua nhanh phút yên tĩnh
# thì PSI_G nhảy cóc). I_BLK so `g - 1` để đếm các phút chặn LIÊN TIẾP là MỘT lần chặn (risk_blocked_attempts), nên paper PHẢI bước mọi điểm lưới có nến
# (kể cả phút rảnh) để PSI_G liền mạch — khi đó kết quả trùng batch (phút rảnh không đổi trạng thái nào ngoài LPX / đỉnh MTM / mẫu vốn, mà thân nến vẫn làm đúng các việc đó).
# `ffwd` chỉ nên True khi giống batch muốn bỏ MTM từng phút (không kill switch); paper truyền False (peak_mtm theo từng nến như Runner).
@njit(**_JIT)
def step_bars(T, BAR, BARI, FR, SIG, SIGV, tr_book, book_off, P, PI, F, I, cfg_i, cfg_f, PS, PSI, LPX,
              outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, ffwd):
    """Chạy len(T) nến liên tiếp (catch-up) bằng `_portfolio_bar`. T[q] = open_time; BAR[q,b,4] = (o,h,l,c); BARI[q,b,8] (xem _portfolio_bar:
    FR_lo/FR_hi chỉ vào FR phẳng, địa chỉ 1m low/high + độ dài 1m: bộ đệm giả khi không có đường 1m); SIG[q,k,5] = (match, stop, dca_gate, -, -); SIGV[q,k] = vol.
    Dừng sớm khi G_OVF != 0. -> số nến đã chạy."""
    n = T.shape[0]
    for q in range(n):
        if G[G_OVF] != 0:
            return q
        _portfolio_bar(T[q], BAR[q], BARI[q], FR, SIG[q], SIGV[q], tr_book, book_off, P, PI, F, I, cfg_i, cfg_f, PS, PSI, LPX,
                       outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, ffwd)
    return n


@njit(**_JIT)
def slot_bar(k, t, X, FL, ML, MH, ja, jb, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    """MỘT nến của MỘT slot (= PositionTracker.on_bar, hay `_on_bar` cũ): X = (o, h, l, c, max_new, max_risk, risk_scale, vol),
    FL = (entry_signal, stop_signal, can_open, dca_gate). ML/MH/ja/jb: nến 1m trong nến chạy (cho stop_fill='extreme'; ja == jb = không có). -> True nếu vị thế đóng."""
    closed = _on_bar_open(k, t, X[0], FL[2] != 0, X[4], X[5], X[6], P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    return _on_bar_rest(k, t, X[0], X[1], X[2], X[3], ML, MH, ja, jb, FL[0] != 0, FL[1] != 0, closed, X[7], FL[3] != 0,
                        P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)


@njit(**_JIT)
def slot_funding(k, rate, price, PI, F, I, LG):
    """Funding của slot k (= PositionTracker.apply_funding): áp vào vốn và trả khoản thanh toán (0.0 nếu không áp dụng)."""
    if I[k, I_OPEN] == 0 or PI[k, PI_PERP] == 0 or F[k, F_QTY] <= 0.0:
        return 0.0
    payment = F[k, F_QTY] * price * rate * (1.0 if PI[k, PI_LONG] == 1 else -1.0)
    _apply_funding(k, rate, price, PI, F, I, LG)
    return payment


@njit(**_JIT)
def slot_force_close(k, t, price, reason, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    """PositionTracker.force_close: bỏ lệnh chờ vào, đóng market (S_CANCEL) nếu đang mở. reason = R_KILL / R_END. -> True nếu đã đóng."""
    if I[k, I_OPEN] == 0:
        return False
    I[k, I_PE] = 0
    _close(k, t, price, S_CANCEL, reason, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    return True


@njit(**_JIT)
def mtm(book_off, PI, F, I, LPX, LG, PS):
    """(vốn theo đóng nến, vốn theo giá xấu nhất) của danh mục theo LPX; cũng ghi PS[PS_MTM], PS[PS_WORST]."""
    _portfolio_mtm(book_off, PI, F, I, LPX, LG, PS)
    return PS[PS_MTM], PS[PS_WORST]


@njit(**_JIT)
def close_all(t, col, tclose, book_off, P, PI, F, I, LPX, PS, PSI, LG, G, outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW):
    """Đóng mọi vị thế mở (lý do R_END) ở LPX[b, col] (cột 0 = close cho tick close_all, cột 3 = open cho batch) tại thời điểm tclose[b],
    rồi mẫu vốn cuối ở t — đúng `_portfolio_end(close_end=1)`."""
    _portfolio_end(t, 1, col, tclose, book_off, P, PI, F, I, LPX, PS, PSI, LG, G, outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW)


# ─── Vòng lặp ĐƠN TÀI SẢN (BacktestEngine.run) ──────────────────────────────
@njit(**_JIT)
def single_kernel(PB, BL, PE, P, PI, F, I, cfg_i, cfg_f,
                  outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG):
    """Một tài sản (sổ 0 của PB/BL; mọi mảng chỉ gồm nến có giao dịch). cfg_i = (trade_start, step_ms)."""
    n = BL[0, 0]
    nt = PE.shape[0]
    trade_start = cfg_i[0]
    step = cfg_i[1]
    T = carray(_ptr(PB[0, 0]), (n,), np.int64)
    Oo = carray(_ptr(PB[0, 1]), (n,), np.float64)
    Hh = carray(_ptr(PB[0, 2]), (n,), np.float64)
    Ll = carray(_ptr(PB[0, 3]), (n,), np.float64)
    Cc = carray(_ptr(PB[0, 4]), (n,), np.float64)
    hm = BL[0, 4] > 0
    MA = carray(_ptr(PB[0, 8]), (n if hm else 1,), np.int64)
    MB = carray(_ptr(PB[0, 9]), (n if hm else 1,), np.int64)
    ML = carray(_ptr(PB[0, 10]), (BL[0, 4] if hm else 1,), np.float64)
    MH = carray(_ptr(PB[0, 11]), (BL[0, 4] if hm else 1,), np.float64)
    nf = BL[0, 1]
    Ft = carray(_ptr(PB[0, 5]), (nf,), np.int64)
    Fr = carray(_ptr(PB[0, 6]), (nf,), np.float64)
    Ms = [carray(_ptr(PE[e, 0]), (n,), np.bool_) for e in range(nt)]
    Ss = [carray(_ptr(PE[e, 1]), (n,), np.bool_) for e in range(nt)]
    Vs = [carray(_ptr(PE[e, 2]), (n,), np.float64) for e in range(nt)]
    Gs = [carray(_ptr(PE[e, 4]), (n if PE[e, 5] == 1 else 1,), np.bool_) for e in range(nt)]
    sig_any = np.zeros(n, dtype=np.bool_)
    for e in range(nt):
        m = Ms[e]
        for r in range(n):
            if m[r]:
                sig_any[r] = True
    f_idx = 0
    has_sample = False
    last_sample = 0
    last_real = -1
    ruined_at = NONE_I
    busy = False
    r = 0
    while r < n:
        if G[G_OVF] != 0:
            break
        if (not busy) and (not _any_active(I, nt)):
            land = r
            while land < n and not (sig_any[land] and T[land] >= trade_start):
                land += 1
            if land > r:
                last_real = land - 1
                j = r if not has_sample else _lower(T, last_sample + step, n)
                while j < land:
                    # _sample_equity khi phẳng: equity + sum([]) -> equity + 0
                    v = LG[LG_EQ] + 0.0
                    _sample(T[j], v, v, eqT, eqM, eqW, G)
                    last_sample = T[j]
                    has_sample = True
                    j = _lower(T, last_sample + step, n)
                r = land
                continue
        i = r
        r += 1
        last_real = i
        t = T[i]
        while f_idx < nf and Ft[f_idx] <= t:
            for k in range(nt):
                _apply_funding(k, Fr[f_idx], Oo[i], PI, F, I, LG)
            f_idx += 1
        can_trade = t >= trade_start
        open_now = 0
        for k in range(nt):
            if I[k, I_OPEN] == 1:
                open_now += 1
        closed_any = False
        busy = False
        for k in range(nt):
            sig = Ms[k][i]
            vol = Vs[k][i] if PE[k, 3] == 1 else np.nan
            gate = Gs[k][i] if PE[k, 5] == 1 else True
            closed = _on_bar(k, t, Oo[i], Hh[i], Ll[i], Cc[i], ML, MH, MA[i] if hm else 0, MB[i] if hm else 0, sig and can_trade, Ss[k][i],
                             can_trade and open_now < PI[k, PI_MAXOPEN], np.inf, vol, gate, np.inf, 1.0,
                             P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            if I[k, I_OPEN] == 1 or I[k, I_PE] == 1:
                busy = True
            if closed:
                closed_any = True
                if LG[LG_EQ] <= 0.0 and ruined_at == NONE_I:
                    ruined_at = t
        if closed_any or (not has_sample) or t - last_sample >= step:
            mtm = 0.0
            worst = 0.0
            for k in range(nt):
                mtm += _unreal(k, Cc[i], PI, F, I)
                worst += _unreal(k, Ll[i] if PI[k, PI_LONG] == 1 else Hh[i], PI, F, I)
            _sample(t, LG[LG_EQ] + mtm, LG[LG_EQ] + worst, eqT, eqM, eqW, G)
            last_sample = t
            has_sample = True
    if last_real >= 0:
        i = last_real
        t = T[i]
        for k in range(nt):
            if I[k, I_OPEN] == 1:
                I[k, I_PE] = 0
                _close(k, t, Oo[i], S_CANCEL, R_END, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
        mtm = 0.0
        worst = 0.0
        for k in range(nt):
            mtm += _unreal(k, Cc[i], PI, F, I)
            worst += _unreal(k, Ll[i] if PI[k, PI_LONG] == 1 else Hh[i], PI, F, I)
        _sample(t, LG[LG_EQ] + mtm, LG[LG_EQ] + worst, eqT, eqM, eqW, G)
    G[G_RUIN] = ruined_at


# ═══ Cầu nối Python <-> kernel: đóng gói tracker/dữ liệu/tín hiệu thành mảng, chạy kernel, dựng lại PositionModel/OrderModel/đường vốn
# y hệt vòng lặp Python cũ và ghi trạng thái cuối trở lại tracker/sổ vốn. Không sao chép mảng dữ liệu (chỉ truyền địa chỉ). Mảng kết quả
# cấp sẵn; kernel báo tràn (G[G_OVF]) thì chạy lại với dung lượng gấp 4 (kết quả tất định nên chạy lại vô hại). ═══
REASONS = [
    "Tín hiệu vào lệnh (AST match)", "Tín hiệu thoát (AST stop)", "Hết thời gian giữ lệnh", "Thanh lý (perp)",
    "Stop-loss (từ giá TB)", "Trailing stop", "Take-profit (từ giá TB)", "End of Backtest", "Kill switch danh mục", "DCA",
]
LIQUIDITY = {1: "maker", 2: "taker", 3: "liquidation"}
_RETRY_FACTOR = 4
_INIT_CAP_POS, _INIT_CAP_ORD = 2048, 8192   # dung lượng khởi đầu của mảng vị thế / lệnh (tràn -> chạy lại gấp 4)
_MAX_TRIES = 6
# Dung lượng đã phải mở rộng gần nhất trong tiến trình: run_many chạy liền nhiều alpha cùng tín hiệu (số lệnh tương tự) -> bắt đầu từ mức
# đó thay vì tràn rồi chạy lại cả kernel. Chỉ ảnh hưởng cấp phát, không ảnh hưởng kết quả.
_CAP_HINT = [_INIT_CAP_POS, _INIT_CAP_ORD]


# ─── Đóng gói tracker ───────────────────────────────────────────────────────
def pack_slots(specs: List[Any], amm: Optional[List[Optional[Dict[str, Any]]]] = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """-> (P, PI, F, I) khởi tạo từ các SlotSpec (core/params.py: mọi chuẩn hoá / kiểm tra tham số làm ở đó). Đọc theo tên thuộc tính nên
    nhận được cả PositionTracker còn ở trạng thái ban đầu (đường Python cũ, tới T10).
    amm (P9.4b T6): theo từng slot, None hoặc {["fee", "stable", "gas"], ["limit_taker" (mặc định True)], ["fee_rate"]} = slot chạy hai móc AMM của tracker cũ: có "fee" -> impact_fn =
    trượt giá theo dự trữ pool (KernelBook / SlotDriver.set_amm ghi dự trữ mỗi tick); limit_taker -> DCA / chốt lời là swap taker; "fee_rate" ghi đè phí taker = phí maker (= phí pool).
    Tracker mang móc limit_taker / impact_fn (đường Python) vẫn bị từ chối: cấu hình AMM chỉ đi qua `amm`."""
    nt = len(specs)
    if amm is not None and len(amm) != nt:
        raise ValueError("amm: cần đúng một mục (hoặc None) cho mỗi slot")
    ml = max([1] + [len(tr.base_dca_steps) for tr in specs])
    P = np.zeros((nt, P_FIXED + 2 * ml))
    PI = np.zeros((nt, NPI), dtype=np.int64)
    F = np.zeros((nt, F_FIXED + ml))
    I = np.zeros((nt, NI), dtype=np.int64)
    for k, tr in enumerate(specs):
        if getattr(tr, "is_open", False) or getattr(tr, "pending_entry", False) or getattr(tr, "pending_exit", False):
            raise ValueError("kernel chỉ chạy được từ trạng thái ban đầu của tracker (không mở, không lệnh chờ)")
        if getattr(tr, "limit_taker", False) or getattr(tr, "impact_fn", None) is not None:
            raise ValueError("kernel không hỗ trợ limit_taker / impact_fn (AMM) — chạy bằng optimize/search/evaluate.py (đường tick)")
        P[k, P_FEE], P[k, P_MAKER], P[k, P_SLIP], P[k, P_MMR] = tr.fee_rate, tr.maker_fee_rate, tr.slippage_rate, tr.mmr
        P[k, P_MAXLEV], P[k, P_CAPUSE] = tr.max_leverage, tr.capital_usage
        P[k, P_BSL], P[k, P_BTP], P[k, P_BTR], P[k, P_BTA] = tr.base_sl, tr.base_tp, tr.base_trail, tr.base_trail_act
        P[k, P_RISK], P[k, P_MAXNOT], P[k, P_OSP] = tr.risk_pct, tr.max_notional_pct, tr.order_size_pct
        P[k, P_LTHRU] = tr.limit_through
        for j, s in enumerate(tr.base_dca_steps):
            P[k, P_BS0 + j] = s
        for j, m in enumerate(tr.dca_mults):
            P[k, P_BS0 + ml + j] = m
        PI[k, PI_LONG] = 1 if tr.is_long else 0
        PI[k, PI_PERP] = 1 if tr.market == "perp" else 0
        PI[k, PI_TIMEOUT], PI[k, PI_COOL] = tr.timeout_ms, tr.cooldown_ms
        PI[k, PI_EXTREME] = 1 if tr.stop_fill == "extreme" else 0
        PI[k, PI_PATH] = {"adverse_first": 0, "ohlc": 1, "adaptive": 2}[tr.intrabar_path]
        PI[k, PI_ATR] = 1 if tr.exit_unit == "atr" else 0
        PI[k, PI_RISKSZ] = 1 if tr.sizing == "risk" else 0
        PI[k, PI_NBASE] = len(tr.base_dca_steps)
        PI[k, PI_MAXOPEN] = tr.max_open_trades
        a = amm[k] if amm is not None else None
        if a is not None:
            PI[k, PI_LTAKER] = 1 if a.get("limit_taker", True) else 0
            if a.get("fee") is not None:             # có pool: trượt giá theo dự trữ (impact_fn); không có: chỉ limit_taker (trượt = slippage_rate)
                fee = float(a["fee"])
                if not 0.0 <= fee < 1.0:
                    raise ValueError(f"phí pool phải trong [0, 1), nhận {fee}")
                PI[k, PI_AMM] = 1
                P[k, P_AFEE], P[k, P_ASTABLE], P[k, P_AGAS] = fee, 1.0 if a["stable"] else 0.0, float(a.get("gas", 0.0))
            if a.get("fee_rate") is not None:
                P[k, P_FEE] = P[k, P_MAKER] = float(a["fee_rate"])
        F[k, F_ENTRY_EQ], F[k, F_MAXCAP], F[k, F_POS_LEV] = tr.entry_equity, tr.max_capital, tr.pos_leverage
        F[k, F_PLANNED], F[k, F_PVOL] = tr.planned_risk, np.nan
        F[k, F_SL], F[k, F_TP], F[k, F_TRAIL], F[k, F_TACT] = tr.sl_pct, tr.tp_pct, tr.trail_pct, tr.trail_activation_pct
        F[k, F_UNIT] = tr.unit_pct
        for j, s in enumerate(tr.dca_steps):
            F[k, F_DS0 + j] = s
        I[k, I_NST] = len(tr.dca_steps)
        I[k, I_POS] = -1
        I[k, I_BLK] = -2
        I[k, I_DCAOK] = 1 if tr.dca_ok else 0
    return P, PI, F, I


class _Tables:
    """Bảng địa chỉ mảng dữ liệu / tín hiệu cho kernel; giữ tham chiếu để mảng không bị giải phóng trong lúc chạy."""

    def __init__(self, n_books: int, n_entries: int):
        self.keep: List[np.ndarray] = []
        self.PB = np.zeros((n_books, 12), dtype=np.int64)
        self.BL = np.zeros((n_books, 5), dtype=np.int64)
        self.PE = np.zeros((n_entries, 6), dtype=np.int64)   # (match, stop, vol, có_vol, điều kiện DCA, có_điều_kiện)
        self._dummy_b = np.ones(1, dtype=np.bool_)
        self._dummy_f = np.zeros(1)
        self._dummy_i = np.full(1, -1, dtype=np.int64)

    def addr(self, a: np.ndarray) -> int:
        self.keep.append(a)
        return int(a.ctypes.data)

    def book(self, b: int, t, o, h, l, c, f_t, f_r, last_t: int, idxm: Optional[np.ndarray],
             minute: Optional[Dict[str, np.ndarray]] = None) -> None:
        """minute: {"m_a","m_b","m_l","m_h"} (engine.minute_path) — nến 1m trong từng nến chạy cho khớp "extreme"; None/rỗng = khung chạy 1m."""
        t = np.ascontiguousarray(t, dtype=np.int64)
        arrs = [t] + [np.ascontiguousarray(x, dtype=np.float64) for x in (o, h, l, c)]
        f_t = np.ascontiguousarray(f_t, dtype=np.int64)
        f_r = np.ascontiguousarray(f_r, dtype=np.float64)
        if not (len(t) == len(arrs[1]) == len(arrs[2]) == len(arrs[3]) == len(arrs[4])):
            raise ValueError("t/o/h/l/c khác độ dài")
        if len(f_t) != len(f_r):
            raise ValueError("funding: f_t/f_r khác độ dài")
        for q, a in enumerate(arrs):
            self.PB[b, q] = self.addr(a)
        self.PB[b, 5], self.PB[b, 6] = self.addr(f_t), self.addr(f_r)
        self.PB[b, 7] = self.addr(idxm if idxm is not None else self._dummy_i)
        n1 = 0
        if minute is not None and len(minute.get("m_l", ())) > 0:
            ma, mb = (np.ascontiguousarray(minute[k], dtype=np.int64) for k in ("m_a", "m_b"))
            ml, mh = (np.ascontiguousarray(minute[k], dtype=np.float64) for k in ("m_l", "m_h"))
            if len(ma) != len(t) or len(mb) != len(t) or len(ml) != len(mh):
                raise ValueError("minute path: độ dài không khớp")
            self.PB[b, 8], self.PB[b, 9], self.PB[b, 10], self.PB[b, 11] = self.addr(ma), self.addr(mb), self.addr(ml), self.addr(mh)
            n1 = len(ml)
        else:
            self.PB[b, 8] = self.PB[b, 9] = self.addr(self._dummy_i)
            self.PB[b, 10] = self.PB[b, 11] = self.addr(self._dummy_f)
        self.BL[b] = (len(t), len(f_t), 0 if idxm is None else 1, last_t, n1)

    def entry(self, e: int, match, stop, vol, gate=None) -> None:
        m = np.ascontiguousarray(match, dtype=np.bool_)
        s = np.ascontiguousarray(stop, dtype=np.bool_)
        self.PE[e, 0], self.PE[e, 1] = self.addr(m), self.addr(s)
        if vol is None:
            self.PE[e, 2], self.PE[e, 3] = self.addr(self._dummy_f), 0
        else:
            v = np.ascontiguousarray(vol, dtype=np.float64)
            self.PE[e, 2], self.PE[e, 3] = self.addr(v), 1
        if gate is None:
            self.PE[e, 4], self.PE[e, 5] = self.addr(self._dummy_b), 0
        else:
            self.PE[e, 4], self.PE[e, 5] = self.addr(np.ascontiguousarray(gate, dtype=np.bool_)), 1


def _alloc(cap_pos: int, cap_ord: int, cap_smp: int):
    return (np.zeros((cap_pos, NOF)), np.zeros((cap_pos, NOI), dtype=np.int64),
            np.zeros((cap_ord, NOR)), np.zeros((cap_ord, 5), dtype=np.int64), np.zeros(cap_pos, dtype=np.int64),
            np.zeros(cap_smp, dtype=np.int64), np.zeros(cap_smp), np.zeros(cap_smp))


# ─── Dựng lại đối tượng ─────────────────────────────────────────────────────
def _build_objects(specs: List[Any], meta: List[Tuple[str, str]], F: np.ndarray, I: np.ndarray, outs, G: np.ndarray,
                   ids: Optional[List[int]] = None, closed_range: Optional[Tuple[int, int]] = None,
                   ns: Optional[List[Any]] = None) -> Tuple[list, list]:
    """-> (positions đã đóng theo thứ tự đóng, orders gom theo vị thế đã đóng); nếu có `ns` (mỗi slot một đối tượng) thì ghi vào ns[k].position /
    ns[k].orders vị thế + lệnh còn mở (SlotView đọc ra). ids: id của từng lệnh theo chỉ số toàn cục (mặc định rút mới từ dãy toàn cục theo
    models.next_id); closed_range: chỉ dựng các vị thế đóng closeSeq[c0:c1] (SlotDriver)."""
    outF, outI, ordF, ordI, closeSeq = outs[:5]
    npos, nord, ncl = int(G[G_NPOS]), int(G[G_NORD]), int(G[G_NCL])
    if ids is None:
        ids = [next_id() for _ in range(nord)]
    opos = ordI[:nord, ORI_POS]
    perm = np.argsort(opos, kind="stable")
    start = np.concatenate(([0], np.cumsum(np.bincount(opos, minlength=npos)))).tolist() if nord else [0] * (npos + 1)
    perm_l = perm.tolist()
    o_price, o_qty, o_fee = ordF[:nord, OR_PRICE].tolist(), ordF[:nord, OR_QTY].tolist(), ordF[:nord, OR_FEE].tolist()
    o_slip = ordF[:nord, OR_SLIP].tolist()
    o_time, o_phase = ordI[:nord, ORI_TIME].tolist(), ordI[:nord, ORI_PHASE].tolist()
    o_exit, o_liq = ordI[:nord, ORI_EXIT].tolist(), ordI[:nord, ORI_LIQ].tolist()
    p_tr = outI[:npos, OI_TR].tolist()
    first_ord = outI[:npos, OI_FIRST_ORD].tolist()
    cols = {name: outF[:npos, idx].tolist() for name, idx in (
        ("enter_price", O_ENTER_PRICE), ("close_price", O_CLOSE_PRICE), ("pnl", O_PNL), ("pct", O_PCT), ("qty", O_QTY),
        ("avg", O_AVG), ("ee", O_ENTRY_EQ), ("em", O_ENTRY_MARGIN), ("en", O_ENTRY_NOTIONAL), ("ef", O_ENTRY_FEE),
        ("xf", O_EXIT_FEE), ("tm", O_TOTAL_MARGIN), ("fees", O_FEES), ("fund", O_FUNDING), ("mae", O_MAE),
        ("maxp", O_MAXP), ("minp", O_MINP), ("unit", O_UNIT), ("lev", O_LEVUSED), ("risk", O_RISK))}
    e_time, c_time = outI[:npos, OI_ENTER_T].tolist(), outI[:npos, OI_CLOSE_T].tolist()
    status, layers = outI[:npos, OI_STATUS].tolist(), outI[:npos, OI_LAYERS].tolist()
    reason, start_reason = outI[:npos, OI_REASON].tolist(), outI[:npos, OI_START].tolist()

    def mk_orders(p: int) -> List[OrderModel]:
        tr = specs[p_tr[p]]
        long_ = tr.is_long
        out = []
        for s in range(start[p], start[p + 1]):
            j = perm_l[s]
            exit_ = o_exit[j] == 1
            out.append(OrderModel(
                order_id=ids[j], account_id=tr.account_id, position_id=ids[first_ord[p]], order_time=o_time[j],
                order_type=OrderType.BUY if long_ != exit_ else OrderType.SELL, order_price=o_price[j], qty=o_qty[j],
                phase=o_phase[j], fee_usd=o_fee[j], liquidity=LIQUIDITY[o_liq[j]], slippage=o_slip[j]))
        return out

    def mk_position(p: int, closed: bool) -> PositionModel:
        tr = specs[p_tr[p]]
        sym, strat = meta[p_tr[p]]
        kw = dict(result_id=ids[first_ord[p]], account_id=tr.account_id, campaign_id=tr.campaign_id, symbol=sym, pos_type=tr.pos_type,
                  phase=0, enter_time=e_time[p], enter_price=cols["enter_price"][p], flow=tr.flow_name,
                  start_reason=REASONS[start_reason[p]], max_price=cols["maxp"][p], min_price=cols["minp"][p],
                  entry_margin_usd=cols["em"][p], entry_notional_usd=cols["en"][p], entry_fee_usd=cols["ef"][p],
                  strategy_id=strat, unit_pct=cols["unit"][p], leverage_used=cols["lev"][p], risk_usd=cols["risk"][p])
        if closed:
            return PositionModel(
                close_time=c_time[p], close_price=cols["close_price"][p], status=PositionStatus(status[p]),
                close_reason=REASONS[reason[p]], exit_fee_usd=cols["xf"][p], real_pnl=cols["pnl"][p], entry_equity=cols["ee"][p],
                profit_pct=cols["pct"][p], qty=cols["qty"][p], layers=layers[p], avg_price=cols["avg"][p],
                total_margin_usd=cols["tm"][p], fees_usd=cols["fees"][p], funding_usd=cols["fund"][p], mae_pct=cols["mae"][p], **kw)
        return PositionModel(status=PositionStatus.OPEN, entry_equity=float(F[p_tr[p], F_ENTRY_EQ]), **kw)

    closed_pos, orders = [], []
    c0, c1 = (0, ncl) if closed_range is None else closed_range
    for p in closeSeq[c0:c1].tolist():
        closed_pos.append(mk_position(p, True))
        orders.extend(mk_orders(p))
    # vị thế còn mở (close_at_end=False): ghi vào ns để SlotView.position / orders (open_positions) dùng được
    if ns is not None:
        closed_set = set(closeSeq[:ncl].tolist())
        for k in range(len(specs)):
            p = int(I[k, I_POS])
            if I[k, I_OPEN] == 1 and p >= 0 and p not in closed_set:
                ns[k].position = mk_position(p, False)
                ns[k].orders = mk_orders(p)
            else:
                ns[k].position = None
                ns[k].orders = []
    return closed_pos, orders


def _round_curve(eqT: np.ndarray, eqM: np.ndarray, eqW: np.ndarray, ns: int) -> List[Dict[str, float]]:
    """Đường vốn: round(x, 4) của Python (đúng làm tròn thập phân, KHÔNG dùng np.round) trên float Python."""
    return [{"time": t, "equity": round(m, 4), "equity_worst": round(w, 4)}
            for t, m, w in zip(eqT[:ns].tolist(), eqM[:ns].tolist(), eqW[:ns].tolist())]


# ─── Danh mục ───────────────────────────────────────────────────────────────
def run_portfolio(eng: Any) -> None:
    """PortfolioEngine.run(): chạy kernel trên eng.books và ghi kết quả vào eng (closed_positions, orders, equity_curve, bộ đếm, tracker)."""
    books = eng.books
    nb = len(books)
    specs, tr_book, meta, book_off = [], [], [], [0]
    for b, book in enumerate(books):
        for e in book["entries"]:
            specs.append(e["slot"])
            tr_book.append(b)
            meta.append((book["symbol"], e["strategy"]))
        book_off.append(len(specs))
    nt = len(specs)

    # lưới thời gian chung: mọi sổ cùng dòng thời gian (thường gặp) -> dùng thẳng t của sổ đầu, không dựng chỉ mục
    ts = [np.ascontiguousarray(bk["data"]["t"], dtype=np.int64) for bk in books]
    if all(len(t) == len(ts[0]) and (t is ts[0] or np.array_equal(t, ts[0])) for t in ts):
        grid, idxms = ts[0], [None] * nb
    else:
        grid = np.unique(np.concatenate(ts)) if nb else np.array([], dtype=np.int64)
        idxms = []
        for t in ts:
            if len(t) == len(grid) and np.array_equal(t, grid):
                idxms.append(None)
            else:
                m = np.full(len(grid), -1, dtype=np.int64)
                m[np.searchsorted(grid, t)] = np.arange(len(t))
                idxms.append(m)
    n = len(grid)
    risk = eng.risk
    kill = risk.kill_switch_dd_pct / 100.0 if risk.kill_switch_dd_pct else 0.0
    t_end = int(grid[-1]) if n else eng.end_ts
    if n == 0:   # không có nến nào: vòng lặp gốc chỉ lấy mẫu cuối ở end_ts với vốn ban đầu
        eng.closed_positions, eng.orders = [], []
        eng.equity_curve = [{"time": int(t_end), "equity": round(eng.ledger.equity, 4), "equity_worst": round(eng.ledger.equity, 4)}]
        eng.last_close = {bk["symbol"]: float("nan") for bk in books}
        return

    P, PI, F, I = pack_slots(specs)
    tab = _Tables(nb, nt)
    for b, bk in enumerate(books):
        d = bk["data"]
        last_t = int(d["t"][-1]) if len(d["t"]) else t_end
        tab.book(b, d["t"], d["o"], d["h"], d["l"], d["c"], d["f_t"], d["f_r"], last_t, idxms[b], d.get("minute"))
    for k in range(nt):
        e = books[tr_book[k]]["entries"][k - book_off[tr_book[k]]]
        tab.entry(k, e["match"], e["stop"], e["vol"], e.get("dca"))
    cfg_i = np.array([eng.trade_start_ts, risk.max_positions, risk.max_per_symbol, 1 if eng.close_at_end else 0,
                      eng.MTM_SAMPLE_MINUTES * 60_000, tab.addr(grid), n, 0, 0, 0], dtype=np.int64)
    cfg_f = np.array([eng.initial_capital, risk.max_gross_exposure, kill, float(risk.max_open_risk_pct or 0.0) / 100.0,
                      float(risk.dd_throttle_pct or 0.0) / 100.0, float(risk.dd_throttle_floor)])
    adm_cap = int(getattr(eng, "adm_capacity", 0) or 0)      # vết admission (T3): eng.adm_capacity > 0 -> eng.adm = ADM[:n] sau khi chạy
    ADM = np.zeros((max(adm_cap, 1), NAD))
    if adm_cap:
        cfg_i[CI_ADM_PTR], cfg_i[CI_ADM_CAP], cfg_i[CI_ADM_ON] = ADM.ctypes.data, adm_cap, 1
    tr_book_a, book_off_a = np.asarray(tr_book, dtype=np.int64), np.asarray(book_off, dtype=np.int64)
    span_samples = int((int(grid[-1]) - int(grid[0])) // int(cfg_i[4])) + 8

    cap_pos, cap_ord = _CAP_HINT
    for _ in range(_MAX_TRIES):
        outs = _alloc(cap_pos, cap_ord, min(n, span_samples) + 8)
        P2, PI2, F2, I2 = P.copy(), PI, F.copy(), I.copy()
        G = np.zeros(NG, dtype=np.int64)
        LG = np.array([eng.ledger.equity, eng.ledger.reserved, eng.ledger.peak])
        last_px = np.zeros((nb, 4))
        portfolio_kernel(tab.PB, tab.BL, tab.PE, tr_book_a, book_off_a, P2, PI2, F2, I2, cfg_i, cfg_f,
                           outs[0], outs[1], outs[2], outs[3], outs[4], outs[5], outs[6], outs[7], G, LG, last_px)
        if G[G_OVF] == 0:
            break
        cap_pos, cap_ord = cap_pos * _RETRY_FACTOR, cap_ord * _RETRY_FACTOR
        _CAP_HINT[0], _CAP_HINT[1] = cap_pos, cap_ord
    else:
        raise RuntimeError("kernel: tràn bộ nhớ đệm kết quả sau nhiều lần mở rộng")

    if adm_cap:
        eng.adm = ADM[:min(int(G[G_NADM]), adm_cap)].copy()
    fin = _Final(specs, P2, PI2, F2, I2)
    eng.closed_positions, eng.orders = _build_objects(specs, meta, F2, I2, outs, G, ns=fin._ns)
    eng.equity_curve = _round_curve(outs[5], outs[6], outs[7], int(G[G_NSMP]))
    k = 0
    for book in books:   # trạng thái cuối của từng slot (đọc qua SlotView; "tracker" = tên cũ cho người đọc hiện có)
        for e in book["entries"]:
            e["view"] = e["tracker"] = fin.views[k]
            k += 1
    eng.ledger.equity, eng.ledger.reserved, eng.ledger.peak = float(LG[LG_EQ]), float(LG[LG_RES]), float(LG[LG_PEAK])
    eng.ledger.rejected += int(G[G_REJ])
    eng.rejected_for_risk += int(G[G_RISKMIN])
    eng.risk_blocked_attempts += int(G[G_ATT])
    eng.halted_at = None if G[G_HALT] == NONE_I else int(G[G_HALT])
    eng.ruined_at = None if G[G_RUIN] == NONE_I else int(G[G_RUIN])
    eng.last_close = {bk["symbol"]: float(last_px[b, 0]) for b, bk in enumerate(books)}


def run_many(eng: Any, position_overrides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PortfolioEngine.run_many(): nhiều bộ tham số vị thế/thoát lệnh trên CÙNG dữ liệu + CÙNG tín hiệu (nạp/tính một lần).
    Mỗi ghi đè áp lên `position` của MỌI chiến lược; không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR).
    Trả danh sách `get_results()` cùng thứ tự; `eng` không đổi trạng thái (mỗi bộ chạy trên một engine con dùng lại books).
    TODO(optimize): gom alpha có cùng tín hiệu vào, chia lô, song song hoá thuộc backend/optimize — đây chỉ là nguyên liệu."""
    if not eng.books:
        eng.load_data()
    out: List[Dict[str, Any]] = []
    for ov in position_overrides:
        strategies = [{**st, "position": {**st["position"], **ov}} for st in eng.strategies]
        sub = type(eng)(eng.symbols, strategies, eng.start_ts, eng.end_ts, trade_start_ts=eng.trade_start_ts,
                        initial_capital=eng.initial_capital, risk=eng.risk, venue=eng.venue, use_cache=False,
                        shared_dir=eng.shared_dir, close_at_end=eng.close_at_end, base_frame=eng.base_frame)
        for book in eng.books:
            _, pairs = sub._make_slots(book["symbol"], sub.ledger)
            entries = []
            for (_st, sp), e0 in zip(pairs, book["entries"]):
                if BacktestEngine.vol_column(sp) != BacktestEngine.vol_column(e0["slot"]):
                    raise ValueError("run_many: ghi đè không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR)")
                entries.append({k_: v for k_, v in e0.items() if k_ not in ("view", "tracker")} | {"slot": sp})
            sub.books.append({**book, "entries": entries, "f_idx": 0})
        run_portfolio(sub)
        out.append(sub.get_results())
    return out


# ═══ P9.4b T3 — KernelBook (sổ paper trên kernel) và SlotDriver (một / vài slot, giao diện đọc của PositionTracker) ═══
# Cùng mảng trạng thái, cùng thân nến `_portfolio_bar` với backtest; không pickle lớp: save/load = paper_state.npz + paper.json.
_ONE_F = np.zeros(1)                       # ML/MH giả (không có đường 1m): carray độ dài 1 và ja == jb nên không bao giờ được đọc
KB_SCHEMA = 2                              # 2: + cột AMM (P_AFEE.., PI_LTAKER/PI_AMM, F_RB.., G_AMERR) — T6
_EXIT_KIND = {R_SL: "sl", R_TP: "tp", R_TRAIL: "trail", R_STOP: "exit", R_TIMEOUT: "timeout", R_LIQ: "liq", R_KILL: "kill", R_END: "end"}
_CHUNK = 64                                # số nến tối đa mỗi lần gọi step_bars (chặn kích thước bộ đệm dự phòng)


def _amm_check(G: np.ndarray) -> None:
    """Kernel đặt G_AMERR khi một lệnh AMM gặp đầu vào không hợp lệ (amount_out cũ ném ValueError) -> ném lại ở đây (cờ được xoá)."""
    if G[G_AMERR] != 0:
        G[G_AMERR] = 0
        raise ValueError("swap không hợp lệ: khối lượng hoặc dự trữ pool không dương (kernel AMM)")


def reserve_price(reserve_base: Any, reserve_quote: Any, stable: bool) -> np.ndarray:
    """Giá biên (quote / 1 base) theo dự trữ: volatile x*y=k -> rq/rb; stable x^3y+xy^3=k -> (3x^2y+y^3)/(x^3+3xy^2) (x = base, y = quote, đơn vị token).
    Bản của core (không import crawl); NumPy thuần — xem chú thích AMM trên `_amm_out_raw` vì sao không nằm trong njit."""
    x, y = np.asarray(reserve_base, float), np.asarray(reserve_quote, float)
    if not stable:
        return y / x
    return (3 * x * x * y + y ** 3) / (x ** 3 + 3 * x * y * y)


def _amm_state(rb: float, rq: float, qu: float, stable: bool) -> Tuple[float, float, float, float]:
    """-> (rb, rq, qu, mid) đã kiểm (AmmImpact.set_state)."""
    if not (rb > 0 and rq > 0 and qu > 0):
        raise ValueError(f"dự trữ pool không hợp lệ: ({rb}, {rq}), quote_usd={qu}")
    return float(rb), float(rq), float(qu), float(reserve_price(rb, rq, stable))


# ─── AMM: vỏ Python có kiểm đầu vào (P9.4b — gộp từ core/execute/amm.py) ──────────────────────────────────────────────────────────────
# Chi phí khớp lệnh của AMM (pool Uniswap v2 / Aerodrome v2): tính ĐÚNG trượt giá của lệnh của ta trên dự trữ pool tại thời điểm khớp.
#
# Hai loại pool (manifest["ticks"]["stable"]):
# - volatile  x*y = k: ra = R_ra · e / (R_vào + e), e = vào · (1 − phí).
# - stable    x³y + xy³ = k (Aerodrome stable): giải y' từ bất biến bằng CHIA ĐÔI (không có công thức đóng) — đúng tới độ chính xác số thực.
# Dự trữ tính theo ĐƠN VỊ TOKEN (bất biến không đổi dạng khi nhân cả hai dự trữ với hằng số: Aerodrome chuẩn hoá theo decimals nhưng k chỉ đổi theo hằng).
#
# Trượt giá `impact` KHÔNG gồm phí pool (phí do tracker tính riêng bằng fee_rate = phí pool): giá khớp thực tế sau khi bỏ phần phí khỏi đầu vào, so với giá biên TRƯỚC lệnh:
#     mua   impact = (vào_quote·(1−phí) / base_nhận) / giá_biên − 1        (volatile = vào·(1−phí) / R_quote)
#     bán   impact = 1 − (quote_nhận / (bán_base·(1−phí))) / giá_biên      (volatile = bán·(1−phí) / (R_base + bán·(1−phí)))
# Cộng thêm gas_usd / danh nghĩa (phí gas cố định mỗi swap, quy theo tỉ lệ danh nghĩa — lệnh nhỏ chịu gas nặng hơn).
#
# Toán nằm TRONG kernel (`_amm_out_raw`, `_amm_price_impact_raw`, `reserve_price`, `_amm_impact`) — bản duy nhất. Ba thứ dưới đây KHÔNG lặp toán: chúng chỉ thêm
# kiểm đầu vào (ném ValueError như amount_out cũ — kernel thì đặt cờ G_AMERR) cho Python / công cụ, và gọi đúng các hàm trên.

def amm_amount_out(amount_in: float, r_in: float, r_out: float, fee: float, stable: bool) -> float:
    """Lượng token nhận được khi đưa `amount_in` token vào pool có dự trữ (r_in, r_out) và phí `fee` (thu trên đầu vào). Đầu vào không dương -> ValueError."""
    if not (amount_in > 0 and r_in > 0 and r_out > 0):
        raise ValueError(f"swap không hợp lệ: vào={amount_in}, dự trữ=({r_in}, {r_out})")
    return float(_amm_out_raw(float(amount_in), float(r_in), float(r_out), float(fee), bool(stable)))


def amm_price_impact(notional_usd: float, is_buy: bool, reserve_base: float, reserve_quote: float, quote_usd: float, fee: float, stable: bool) -> float:
    """Trượt giá (tỉ lệ, không gồm phí pool) của lệnh `notional_usd` (USD) mua/bán token gốc trên pool có dự trữ token (reserve_base, reserve_quote);
    quote_usd = USD / 1 token quote."""
    mid = float(reserve_price(reserve_base, reserve_quote, stable))             # quote / 1 base (giá biên trước lệnh)
    if is_buy:
        amm_amount_out(notional_usd / quote_usd, reserve_quote, reserve_base, fee, stable)   # kiểm đầu vào: ném ValueError như bản cũ
    else:
        amm_amount_out(notional_usd / (mid * quote_usd), reserve_base, reserve_quote, fee, stable)
    return float(_amm_price_impact_raw(float(notional_usd), bool(is_buy), mid, float(reserve_base), float(reserve_quote), float(quote_usd), float(fee), bool(stable)))


class AmmImpact:
    """Móc impact_fn của PositionTracker cho MỘT pool: dự trữ đặt lại theo từng tick (set_state), gọi (notional_usd, is_buy) -> trượt giá + gas.
    Cũng là mô tả pool (fee, stable, gas_usd) cho TickBook / KernelBook (amm=)."""

    def __init__(self, fee: float, stable: bool, gas_usd: float = 0.0):
        if not 0.0 <= fee < 1.0:
            raise ValueError(f"phí pool phải trong [0, 1), nhận {fee}")
        self.fee, self.stable, self.gas_usd = float(fee), bool(stable), float(gas_usd)
        self.reserve_base = self.reserve_quote = self.quote_usd = float("nan")

    def set_state(self, reserve_base: float, reserve_quote: float, quote_usd: float) -> None:
        if not (reserve_base > 0 and reserve_quote > 0 and quote_usd > 0):
            raise ValueError(f"dự trữ pool không hợp lệ: ({reserve_base}, {reserve_quote}), quote_usd={quote_usd}")
        self.reserve_base, self.reserve_quote, self.quote_usd = float(reserve_base), float(reserve_quote), float(quote_usd)

    def __call__(self, notional_usd: float, is_buy: bool) -> float:
        if not notional_usd > 0:
            return 0.0
        return amm_price_impact(notional_usd, is_buy, self.reserve_base, self.reserve_quote, self.quote_usd, self.fee, self.stable) \
            + self.gas_usd / notional_usd


class _LedgerView:
    """Giao diện đọc của Account trên mảng LG / G (initial, equity, reserved, peak, rejected, usage, free)."""

    def __init__(self, owner):
        self._o = owner

    initial = property(lambda s: float(s._o.cfg_f[0]))
    equity = property(lambda s: float(s._o.LG[LG_EQ]))
    reserved = property(lambda s: float(s._o.LG[LG_RES]))
    peak = property(lambda s: float(s._o.LG[LG_PEAK]))
    rejected = property(lambda s: int(s._o.G[G_REJ]))
    usage = property(lambda s: 1.0)

    def free(self) -> float:
        return self.equity * 1.0 - self.reserved


def _cfg_arrays(capital: float, risk: Dict[str, Any], trade_start: int, step_ms: int) -> Tuple[np.ndarray, np.ndarray]:
    r = RiskConfig.from_dict(risk)
    kill = r.kill_switch_dd_pct / 100.0 if r.kill_switch_dd_pct else 0.0
    cfg_i = np.array([int(trade_start), r.max_positions, r.max_per_symbol, 0, step_ms, 0, 0, 0, 0, 0], dtype=np.int64)
    cfg_f = np.array([float(capital), r.max_gross_exposure, kill, float(r.max_open_risk_pct or 0.0) / 100.0,
                      float(r.dd_throttle_pct or 0.0) / 100.0, float(r.dd_throttle_floor)])
    return cfg_i, cfg_f


class KernelBook:
    """Sổ PAPER chạy đúng kernel của backtest TỪNG NẾN / TỪNG KHÚC (P9.4b T3): trạng thái nằm trọn trong mảng, kết quả trùng từng bit với
    PortfolioEngine(close_at_end=False) cùng chuỗi nến, và trùng PaperBook (Runner) cùng nguồn. API phản chiếu PaperBook (khu LEGACY cuối file):
    step_bar / step_bars, mtm(), positions(), trades, ledger, last_t, halted_at, peak_mtm, rejected_for_risk, last_close/low/high/open.

    Hợp đồng bước: mỗi nến có nến ở ít nhất một tài sản PHẢI được bước theo đúng thứ tự thời gian, KHÔNG bỏ điểm lưới nào (kể cả phút rảnh) — bộ đếm lưới
    PSI_G cho phép đếm các phút bị chặn liên tiếp là một lần (xem chú thích trên `step_bars`). Bộ đệm được nới TRƯỚC mỗi khúc nên không bao giờ tràn;
    khi cạn chỗ thì nén trước (bỏ hàng của vị thế đã đóng — lệnh đóng đã thành dict trong `trades`), sau đó mới nới. save() luôn nén.

    record_full=True (test): giữ nguyên mọi hàng + tracker khởi đầu, không nén -> full_objects() dựng PositionModel/OrderModel y hệt batch."""

    MTM_SAMPLE_MINUTES = 60
    ALLOW_EQUAL_T = False                  # True: nhiều bước cùng t (tick DEX: nhiều swap một block) — kernel không phụ thuộc t tăng ngặt

    def __init__(self, strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str, capital: float, risk: Dict[str, Any],
                 trade_start: int = 0, record_full: bool = False, record_events: bool = True, adm_capacity: int = 0,
                 amm: Optional[List[Optional[Dict[str, Any]]]] = None):
        """amm (T6): theo từng sổ (tài sản), None hoặc {"fee", "stable", "gas"} = pool AMM của tài sản đó — mọi slot của sổ chạy limit_taker + trượt giá theo dự trữ pool
        (phí taker = maker = phí pool); gọi `set_amm(b, rb, rq, qu)` trước mỗi nến."""
        slots, specs = [], []
        pe = PortfolioEngine(list(symbols), strategies, 0, DAY, trade_start_ts=0, use_cache=False, base_frame=base_frame)
        for b, sym in enumerate(symbols):
            for st, sp in pe._make_slots(sym, pe.ledger)[1]:   # đúng live/signals._engine: chuẩn hoá tham số do SlotSpec làm
                slots.append({"book": b, "symbol": sym, "strategy": st["id"], "side": st["side"]})
                specs.append(sp)
        if not specs:
            raise ValueError("Cần ít nhất một tài sản và một chiến lược")
        self._setup(list(symbols), slots, base_frame, float(capital), dict(risk), int(trade_start), record_events, adm_capacity)
        if amm is not None and len(amm) != len(symbols):
            raise ValueError("amm: cần đúng một mục (hoặc None) cho mỗi tài sản")
        P, PI, F, I = pack_slots(specs, None if amm is None else [None if amm[s["book"]] is None else {**amm[s["book"]], "fee_rate": amm[s["book"]]["fee"]} for s in slots])
        F[:, F_ENTRY_EQ] = float(capital)
        for k, tr in enumerate(specs):
            F[k, F_MAXCAP] = float(capital) * tr.capital_usage
        self.P, self.PI, self.F, self.I = P, PI, F, I
        self.cfg_i, self.cfg_f = _cfg_arrays(capital, risk, trade_start, self.MTM_SAMPLE_MINUTES * 60_000)
        self.PS, self.PSI, self.LPX = new_portfolio_state(len(symbols), float(capital))
        self.LG = np.array([float(capital), 0.0, float(capital)])
        self.G = np.zeros(NG, dtype=np.int64)
        self._alloc_buffers(max(64, 8 * len(specs)), max(256, 32 * len(specs)), 256)
        self.record_full = bool(record_full)
        self._specs = specs if record_full else None
        self._arm_adm(adm_capacity)

    # ── dựng / nạp ──
    def _setup(self, symbols, slots, base_frame, capital, risk, trade_start, record_events, adm_capacity):
        self.symbols, self.slots, self.base_frame = symbols, slots, base_frame
        self.capital, self.risk, self.trade_start = capital, dict(risk), trade_start
        nb, nt = len(symbols), len(slots)
        self.nb, self.nt = nb, nt
        self.tr_book = np.array([s["book"] for s in slots], dtype=np.int64)
        off = [0]
        for b in range(nb):
            off.append(off[-1] + sum(1 for s in slots if s["book"] == b))
        self.book_off = np.array(off, dtype=np.int64)
        self.entries = [[k for k in range(nt) if slots[k]["book"] == b] for b in range(nb)]
        self.trades: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.record_events = bool(record_events)
        self._last_t: Optional[int] = None
        self.ledger = _LedgerView(self)
        self.record_full = False
        self._specs = None
        self.adm_capacity = 0
        self._adm = None

    def _alloc_buffers(self, cap_pos: int, cap_ord: int, cap_smp: int) -> None:
        (self.outF, self.outI, self.ordF, self.ordI, self.closeSeq, self.eqT, self.eqM, self.eqW) = _alloc(cap_pos, cap_ord, cap_smp)

    def _arm_adm(self, capacity: int) -> None:
        """Vết admission (cfg_i[CI_ADM_*]): ADM[cap, NAD]; tràn thì bỏ bản ghi, không bao giờ G_OVF. Con trỏ làm mới sau mỗi lần nạp / cấp lại."""
        capacity = int(capacity or 0)
        self.adm_capacity = capacity
        self._adm = np.zeros((max(capacity, 1), NAD))
        self.cfg_i[CI_ADM_PTR], self.cfg_i[CI_ADM_CAP], self.cfg_i[CI_ADM_ON] = (self._adm.ctypes.data, capacity, 1) if capacity else (0, 0, 0)

    @property
    def adm(self) -> np.ndarray:
        """Vết admission đã ghi (bản sao): hàng (t, k, n_open, per_book, equity, gross, can_open, max_new)."""
        return self._adm[:min(int(self.G[G_NADM]), self.adm_capacity)].copy()

    # ── thuộc tính trạng thái (đối ứng PaperBook) ──
    last_t = property(lambda s: s._last_t)
    peak_mtm = property(lambda s: float(s.PS[PS_PEAK_MTM]))
    halted_at = property(lambda s: None if s.PSI[PSI_HALTED] == 0 else int(s.PSI[PSI_HALT_AT]))
    ruined_at = property(lambda s: None if s.PSI[PSI_RUIN_AT] == NONE_I else int(s.PSI[PSI_RUIN_AT]))
    rejected_for_risk = property(lambda s: int(s.G[G_RISKMIN]))
    risk_blocked_attempts = property(lambda s: int(s.G[G_ATT]))
    dca_layers_rejected = property(lambda s: int(s.I[:, I_DCAREJ].sum()))
    skipped_no_vol = property(lambda s: int(s.I[:, I_SKIP].sum()))
    last_close = property(lambda s: s.LPX[:, 0].tolist())
    last_low = property(lambda s: s.LPX[:, 1].tolist())
    last_high = property(lambda s: s.LPX[:, 2].tolist())
    last_open = property(lambda s: s.LPX[:, 3].tolist())

    def mtm(self) -> Tuple[float, float]:
        m, w = mtm(self.book_off, self.PI, self.F, self.I, self.LPX, self.LG, self.PS)
        return float(m), float(w)

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for k in range(self.nt):
            if self.I[k, I_OPEN] == 1:
                sl = self.slots[k]
                out.append({"symbol": sl["symbol"], "strategy": sl["strategy"], "side": sl["side"], "qty": float(self.F[k, F_QTY]),
                            "avg": float(self.F[k, F_AVG]), "layers": int(self.I[k, I_LAYERS]), "entry_time": int(self.I[k, I_ENTRY_T]),
                            "unrealized": float(_unreal(k, self.LPX[sl["book"], 0], self.PI, self.F, self.I))})
        return out

    def equity_curve(self) -> List[Dict[str, float]]:
        """Đường vốn theo giờ + mẫu cuối ở last_t (như PortfolioEngine.equity_curve khi không đóng cuối dữ liệu); không đổi trạng thái."""
        out = _round_curve(self.eqT, self.eqM, self.eqW, int(self.G[G_NSMP]))
        if self._last_t is not None:
            m, w = self.mtm()
            out.append({"time": int(self._last_t), "equity": round(m, 4), "equity_worst": round(w, 4)})
        return out

    def drain_events(self) -> List[Dict[str, Any]]:
        ev, self.events = self.events, []
        return ev

    def set_amm(self, b: int, reserve_base: float, reserve_quote: float, quote_usd: float) -> None:
        """Dự trữ pool (token) + USD / 1 quote của sổ b tại tick sắp bước (AmmImpact.set_state): ghi cho mọi slot của sổ. Không hợp lệ -> ValueError."""
        o0, o1 = int(self.book_off[b]), int(self.book_off[b + 1])
        rb, rq, qu, mid = _amm_state(reserve_base, reserve_quote, quote_usd, bool(self.P[o0, P_ASTABLE]))
        self.F[o0:o1, F_RB], self.F[o0:o1, F_RQ], self.F[o0:o1, F_QU], self.F[o0:o1, F_MID] = rb, rq, qu, mid

    def taker_slippage(self) -> np.ndarray:
        """Tỉ lệ trượt giá của mọi lệnh taker (không tính thanh lý) theo thứ tự slot rồi thời gian (như duyệt tracker.orders từng slot). Cần record_full (không nén hàng)."""
        if not self.record_full:
            raise ValueError("taker_slippage cần record_full=True")
        nord = int(self.G[G_NORD])
        rows = np.flatnonzero(self.ordI[:nord, ORI_LIQ] == 2)
        slot = self.outI[self.ordI[rows, ORI_POS], OI_TR]
        return self.ordF[rows[np.argsort(slot, kind="stable")], OR_SLIP]

    # ── bộ đệm ──
    def _compact(self) -> None:
        """Bỏ hàng của vị thế đã đóng khỏi outF/outI/ordF/ordI (đã thành dict trong `trades`); giữ vị thế đang mở + lệnh của chúng, đánh số lại."""
        if self.record_full:
            return
        G, I = self.G, self.I
        opens = sorted((int(I[k, I_POS]), k) for k in range(self.nt) if I[k, I_OPEN] == 1 and I[k, I_POS] >= 0)
        old_p = np.array([p for p, _ in opens], dtype=np.int64)
        nord = int(G[G_NORD])
        keep = np.flatnonzero(np.isin(self.ordI[:nord, ORI_POS], old_p)) if len(old_p) else np.zeros(0, dtype=np.int64)
        new_of = {int(p): i for i, p in enumerate(old_p.tolist())}
        outF, outI = self.outF[old_p].copy(), self.outI[old_p].copy()
        ordF, ordI = self.ordF[keep].copy(), self.ordI[keep].copy()
        ordI[:, ORI_POS] = [new_of[int(p)] for p in ordI[:, ORI_POS].tolist()]
        first = {}
        for j, p in enumerate(ordI[:, ORI_POS].tolist()):
            first.setdefault(p, j)
        for i in range(len(old_p)):
            outI[i, OI_FIRST_ORD] = first[i]
        for (p, k) in opens:
            I[k, I_POS] = new_of[p]
        self.outF[:] = 0.0
        self.outI[:] = 0
        self.ordF[:] = 0.0
        self.ordI[:] = 0
        self.outF[:len(old_p)], self.outI[:len(old_p)] = outF, outI
        self.ordF[:len(keep)], self.ordI[:len(keep)] = ordF, ordI
        G[G_NPOS], G[G_NORD], G[G_NCL] = len(old_p), len(keep), 0

    def _reserve(self, nbars: int) -> None:
        """Nới bộ đệm TRƯỚC khi chạy nbars nến: mỗi slot tối đa một vị thế mới mỗi nến, mỗi vị thế tối đa (tầng DCA tối đa + 2) lệnh, mỗi mẫu vốn một hàng."""
        G, nt = self.G, self.nt
        ml = (self.P.shape[1] - P_FIXED) // 2
        need_pos, need_ord, need_smp = nt * nbars, nt * nbars * (ml + 2) * 2, nbars + 4
        if G[G_NPOS] + need_pos > self.outF.shape[0] or G[G_NORD] + need_ord > self.ordF.shape[0]:
            self._compact()
        if G[G_NPOS] + need_pos > self.outF.shape[0] or G[G_NORD] + need_ord > self.ordF.shape[0]:
            cp = max(self.outF.shape[0] * 2, int(G[G_NPOS]) + need_pos)
            co = max(self.ordF.shape[0] * 2, int(G[G_NORD]) + need_ord)
            self.outF, self.outI = (np.vstack([a, np.zeros((cp - a.shape[0], a.shape[1]), dtype=a.dtype)]) for a in (self.outF, self.outI))
            self.ordF, self.ordI = (np.vstack([a, np.zeros((co - a.shape[0], a.shape[1]), dtype=a.dtype)]) for a in (self.ordF, self.ordI))
        if self.closeSeq.shape[0] < self.outF.shape[0]:
            self.closeSeq = np.concatenate([self.closeSeq, np.zeros(self.outF.shape[0] - self.closeSeq.shape[0], dtype=np.int64)])
        if G[G_NSMP] + need_smp > self.eqT.shape[0]:
            cs = max(self.eqT.shape[0] * 2, int(G[G_NSMP]) + need_smp)
            self.eqT, self.eqM, self.eqW = (np.concatenate([a, np.zeros(cs - a.shape[0], dtype=a.dtype)]) for a in (self.eqT, self.eqM, self.eqW))
        # closeSeq ghi theo G_NCL (tăng sau mỗi lần đóng): phải đủ chỗ cho vị thế đóng trong khúc (<= số vị thế hiện có + mới)
        if G[G_NCL] + need_pos + nt > self.closeSeq.shape[0]:
            self.closeSeq = np.concatenate([self.closeSeq, np.zeros(int(G[G_NCL]) + need_pos + nt - self.closeSeq.shape[0], dtype=np.int64)])

    # ── chạy ──
    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến ở open_time t (y hệt PaperBook.step_bar): bars[sym] = (o,h,l,c); sig[sym] = [{match, stop, vol, dca}] theo thứ tự chiến lược;
        funding[sym] = [(funding_time, rate)] đến hạn <= t. -> các lệnh đóng ở nến này (dict như Runner.record)."""
        return self.step_bars([(t, bars, sig, funding)])

    def step_bars(self, feed: List[Tuple[int, Dict, Dict, Optional[Dict]]]) -> List[Dict[str, Any]]:
        """Catch-up: nhiều nến liên tiếp (t, bars, sig, funding), cùng kết quả bước từng nến. -> các lệnh đóng của cả khúc."""
        out: List[Dict[str, Any]] = []
        for i in range(0, len(feed), _CHUNK):
            out.extend(self._run_chunk(feed[i:i + _CHUNK]))
        return out

    def _run_chunk(self, feed) -> List[Dict[str, Any]]:
        n, nb, nt = len(feed), self.nb, self.nt
        T = np.zeros(n, dtype=np.int64)
        BAR = np.zeros((n, nb, 4))
        BARI = np.zeros((n, nb, 8), dtype=np.int64)
        SIG = np.zeros((n, nt, 5), dtype=np.bool_)
        SIGV = np.full((n, nt), np.nan)
        FRl: List[float] = []
        dummy = int(_ONE_F.ctypes.data)
        for q, (t, bars, sig, funding) in enumerate(feed):
            lo_ok = (lambda a, b: a < b) if self.ALLOW_EQUAL_T else (lambda a, b: a <= b)   # a "không hợp lệ" so với b
            if q and lo_ok(t, int(T[q - 1])) or (self._last_t is not None and q == 0 and lo_ok(t, self._last_t)):
                raise ValueError(f"KernelBook: nến phải tăng ngặt theo thời gian (t={t})")
            T[q] = t
            for b, sym in enumerate(self.symbols):
                if sym not in bars:
                    continue
                BAR[q, b] = bars[sym]
                lo = len(FRl)
                for _ft, rate in (funding or {}).get(sym, []):
                    FRl.append(float(rate))
                BARI[q, b] = (1, 0, 0, lo, len(FRl), dummy, dummy, 1)
                for k, s in zip(self.entries[b], sig[sym]):
                    SIG[q, k, 0], SIG[q, k, 1], SIG[q, k, 2] = bool(s["match"]), bool(s["stop"]), bool(s.get("dca", True))
                    v = s.get("vol")
                    SIGV[q, k] = float(v) if v is not None else np.nan
        FR = np.array(FRl if FRl else [0.0])
        # đáy / đỉnh nến của từng sổ tại mỗi nến (điền tiếp từ nến trước) -> bar_low / bar_high của lệnh đóng như Runner.record
        LL, HH = np.empty((n, nb)), np.empty((n, nb))
        cur_l, cur_h = self.LPX[:, 1].copy(), self.LPX[:, 2].copy()
        for q in range(n):
            for b in range(nb):
                if BARI[q, b, 0]:
                    cur_l[b], cur_h[b] = BAR[q, b, 2], BAR[q, b, 1]
            LL[q], HH[q] = cur_l, cur_h
        self._reserve(n)
        G = self.G
        ncl0, nord0, rej0, risk0 = int(G[G_NCL]), int(G[G_NORD]), int(G[G_REJ]), int(G[G_RISKMIN])
        ran = step_bars(T, BAR, BARI, FR, SIG, SIGV, self.tr_book, self.book_off, self.P, self.PI, self.F, self.I, self.cfg_i, self.cfg_f,
                        self.PS, self.PSI, self.LPX, self.outF, self.outI, self.ordF, self.ordI, self.closeSeq, self.eqT, self.eqM, self.eqW,
                        G, self.LG, False)
        _amm_check(G)
        if G[G_OVF] != 0 or ran != n:
            raise RuntimeError("KernelBook: tràn bộ đệm kết quả (lỗi dự phòng — _reserve phải ngăn được)")
        self._last_t = int(T[-1])
        closed = self._collect_closed(ncl0, int(G[G_NCL]), T, LL, HH)
        self.trades.extend(closed)
        if self.record_events:
            self._collect_events(nord0, int(G[G_NORD]), int(G[G_REJ]) - rej0, int(G[G_RISKMIN]) - risk0, self._last_t)
        return closed

    def _collect_closed(self, c0: int, c1: int, T, LL, HH) -> List[Dict[str, Any]]:
        if c1 <= c0:
            return []
        ps = self.closeSeq[c0:c1].tolist()
        outF, outI = self.outF, self.outI
        col = lambda idx: outF[ps, idx].tolist()   # noqa: E731
        icol = lambda idx: outI[ps, idx].tolist()  # noqa: E731
        enter_price, close_price, pnl, qty, avg = col(O_ENTER_PRICE), col(O_CLOSE_PRICE), col(O_PNL), col(O_QTY), col(O_AVG)
        fees, fund = col(O_FEES), col(O_FUNDING)
        trs, e_t, c_t, lay, rea = icol(OI_TR), icol(OI_ENTER_T), icol(OI_CLOSE_T), icol(OI_LAYERS), icol(OI_REASON)
        out = []
        for i in range(len(ps)):
            k = trs[i]
            sl = self.slots[k]
            q = int(np.searchsorted(T, c_t[i]))
            out.append({"symbol": sl["symbol"], "strategy": sl["strategy"], "side": "LONG" if self.PI[k, PI_LONG] == 1 else "SHORT",
                        "enter_time": int(e_t[i]), "enter_price": float(enter_price[i]), "avg_price": float(avg[i] or enter_price[i]),
                        "close_time": int(c_t[i]), "close_price": float(close_price[i]), "qty": float(qty[i]), "layers": int(lay[i] or 1),
                        "pnl": round(float(pnl[i]), 6), "reason": REASONS[rea[i]], "fees": round(float(fees[i] or 0), 6),
                        "funding": round(float(fund[i] or 0), 6), "bar_low": float(LL[q, sl["book"]]), "bar_high": float(HH[q, sl["book"]])})
        return out

    def _collect_events(self, o0: int, o1: int, d_rej: int, d_risk: int, t_last: int) -> None:
        if o1 > o0:
            ps = self.ordI[o0:o1, ORI_POS].tolist()
            ks = self.outI[ps, OI_TR].tolist()
            reasons = self.outI[ps, OI_REASON].tolist()
            price, raw, qty, fee, slip = (self.ordF[o0:o1, c].tolist() for c in (OR_PRICE, OR_RAW, OR_QTY, OR_FEE, OR_SLIP))
            tm, ph, ex, lq = (self.ordI[o0:o1, c].tolist() for c in (ORI_TIME, ORI_PHASE, ORI_EXIT, ORI_LIQ))
            for i in range(o1 - o0):
                sl = self.slots[ks[i]]
                kind = _EXIT_KIND[reasons[i]] if ex[i] == 1 else ("entry" if ph[i] == 0 else "dca")
                self.events.append({"kind": kind, "t": int(tm[i]), "slot": ks[i], "symbol": sl["symbol"], "strategy": sl["strategy"],
                                    "side": sl["side"], "price": price[i], "raw_price": raw[i], "qty": qty[i], "fee": fee[i], "slip": slip[i],
                                    "liquidity": LIQUIDITY[lq[i]], "layer": int(ph[i])})
        if d_rej:
            self.events.append({"kind": "reject", "reason": "capital", "n": d_rej, "t": t_last})
        if d_risk:
            self.events.append({"kind": "reject", "reason": "risk", "n": d_risk, "t": t_last})
        if len(self.events) > 50_000:
            del self.events[:len(self.events) - 50_000]

    def close_all(self, t: int, col: int = 0) -> List[Dict[str, Any]]:
        """Đóng mọi vị thế mở (lý do "End of Backtest") ở LPX[:, col] (0 = close, 3 = open) tại t, rồi mẫu vốn cuối (chạy `close_all` của kernel)."""
        self._reserve(1)
        G = self.G
        ncl0, nord0 = int(G[G_NCL]), int(G[G_NORD])
        tclose = np.full(self.nb, int(t), dtype=np.int64)
        close_all(int(t), int(col), tclose, self.book_off, self.P, self.PI, self.F, self.I, self.LPX, self.PS, self.PSI, self.LG, G,
                  self.outF, self.outI, self.ordF, self.ordI, self.closeSeq, self.eqT, self.eqM, self.eqW)
        T = np.array([int(t)], dtype=np.int64)
        LL, HH = self.LPX[:, 1][None, :], self.LPX[:, 2][None, :]
        _amm_check(G)
        closed = self._collect_closed(ncl0, int(G[G_NCL]), T, LL, HH)
        self.trades.extend(closed)
        if self.record_events:
            self._collect_events(nord0, int(G[G_NORD]), 0, 0, int(t))
        return closed

    # ── test: dựng PositionModel / OrderModel đầy đủ ──
    def full_objects(self) -> Tuple[list, list]:
        if not self.record_full:
            raise ValueError("full_objects cần record_full=True")
        meta = [(s["symbol"], s["strategy"]) for s in self.slots]
        fin = _Final(self._specs, self.P, self.PI, self.F, self.I)
        self.full_views = fin.views   # vị thế / lệnh còn mở của từng slot (SlotView)
        return _build_objects(self._specs, meta, self.F, self.I, (self.outF, self.outI, self.ordF, self.ordI, self.closeSeq), self.G, ns=fin._ns)

    # ── lưu / nạp (trạng thái thuần; ghi tệp ở live/live.py) ──
    def params_hash(self) -> str:
        import hashlib
        h = hashlib.sha256()
        for a in (self.P, self.PI, self.cfg_f, self.cfg_i[:5], self.tr_book, self.book_off):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()

    def state_arrays(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Trạng thái đầy đủ để lưu: (mảng đã gọn, meta JSON-được: phiên bản, tài sản, chiến lược, băm tham số, lệnh đã đóng, vị thế). Thuần bộ nhớ — ghi tệp
        (paper_state.npz + paper.json) là việc của live/live.py::save_kernel_book; không pickle lớp."""
        self._compact()
        G = self.G
        npos, nord, nsmp = int(G[G_NPOS]), int(G[G_NORD]), int(G[G_NSMP])
        cfg_i = self.cfg_i.copy()
        cfg_i[CI_ADM_PTR], cfg_i[CI_ADM_CAP], cfg_i[CI_ADM_ON] = 0, 0, 0
        arrays = dict(P=self.P, PI=self.PI, F=self.F, I=self.I, cfg_i=cfg_i, cfg_f=self.cfg_f, PS=self.PS, PSI=self.PSI, LPX=self.LPX, LG=self.LG,
                      G=G, outF=self.outF[:npos], outI=self.outI[:npos], ordF=self.ordF[:nord], ordI=self.ordI[:nord],
                      eqT=self.eqT[:nsmp], eqM=self.eqM[:nsmp], eqW=self.eqW[:nsmp], tr_book=self.tr_book, book_off=self.book_off)
        meta = {"schema": KB_SCHEMA, "kind": "kernel_book", "symbols": self.symbols, "slots": self.slots, "base_frame": self.base_frame,
                "capital": self.capital, "risk": self.risk, "trade_start": self.trade_start, "params_hash": self.params_hash(),
                "last_t": self._last_t, "adm_capacity": self.adm_capacity, "record_events": self.record_events,
                "trades": self.trades, "positions": self.positions()}
        return arrays, meta

    @staticmethod
    def check_state_meta(meta: Dict[str, Any]) -> None:
        if meta.get("schema") != KB_SCHEMA or meta.get("kind") != "kernel_book":
            raise ValueError(f"paper.json: phiên bản / loại không hỗ trợ ({meta.get('schema')}, {meta.get('kind')})")

    @classmethod
    def from_state(cls, meta: Dict[str, Any], z: Mapping[str, np.ndarray], strategies: Optional[List[Dict[str, Any]]] = None) -> "KernelBook":
        """Dựng lại sổ từ (meta, mảng) của state_arrays. strategies (tuỳ chọn): dựng lại tham số từ chiến lược hiện tại và so băm — lệch thì ValueError
        (sổ cũ không khớp cấu hình mới)."""
        cls.check_state_meta(meta)
        kb = cls.__new__(cls)
        kb._setup(list(meta["symbols"]), meta["slots"], meta["base_frame"], float(meta["capital"]), meta["risk"], int(meta["trade_start"]),
                  bool(meta.get("record_events", True)), 0)
        for name in ("P", "PI", "F", "I", "cfg_i", "cfg_f", "PS", "PSI", "LPX", "LG", "G", "tr_book", "book_off"):
            setattr(kb, name, z[name].copy())
        kb.tr_book, kb.book_off = kb.tr_book.astype(np.int64), kb.book_off.astype(np.int64)
        if kb.params_hash() != meta["params_hash"]:
            raise ValueError("paper_state.npz: băm tham số không khớp paper.json (tệp hỏng hoặc không cùng lần lưu)")
        npos, nord, nsmp = len(z["outF"]), len(z["ordF"]), len(z["eqT"])
        kb._alloc_buffers(max(64, 8 * kb.nt, npos * 2), max(256, 32 * kb.nt, nord * 2), max(256, nsmp * 2))
        kb.outF[:npos], kb.outI[:npos], kb.ordF[:nord], kb.ordI[:nord] = z["outF"], z["outI"], z["ordF"], z["ordI"]
        kb.eqT[:nsmp], kb.eqM[:nsmp], kb.eqW[:nsmp] = z["eqT"], z["eqM"], z["eqW"]
        kb.trades = list(meta["trades"])
        kb._last_t = meta["last_t"]
        kb._arm_adm(int(meta.get("adm_capacity", 0)))
        if strategies is not None:
            fresh = cls(strategies, kb.symbols, kb.base_frame, kb.capital, kb.risk, kb.trade_start)
            if fresh.params_hash() != kb.params_hash():
                raise ValueError("sổ paper đã lưu không khớp chiến lược / rủi ro hiện tại (băm tham số khác)")
        return kb


class _Ns:
    """Vị thế + lệnh còn mở của một slot (do _build_objects ghi, SlotView đọc)."""

    def __init__(self):
        self.position = None
        self.orders: list = []


class _Final:
    """Trạng thái CUỐI của một lần chạy batch (mảng P/PI/F/I + vị thế/lệnh còn mở) cho SlotView — thay việc ghi ngược vào PositionTracker."""

    def __init__(self, specs: List[Any], P: np.ndarray, PI: np.ndarray, F: np.ndarray, I: np.ndarray):
        self.specs, self.P, self.PI, self.F, self.I = specs, P, PI, F, I
        self._ns = [_Ns() for _ in specs]
        self.views = [SlotView(self, k) for k in range(len(specs))]

    def refresh_open(self) -> None:
        return None


# ── P9.4b T7: sổ paper trên kernel (KernelPaperBook, trước đây live/paper.py) ──
class _SlotRO:
    """Mặt đọc của một slot cho `books[b]["entries"][j]["tracker"]` (test / công cụ): tham số từ P/PI, trạng thái từ F/I của KernelBook."""

    def __init__(self, kb: "KernelPaperBook", k: int):
        self._kb, self._k = kb, k

    sl_pct = property(lambda s: float(s._kb.F[s._k, 15]))          # F_SL
    qty = property(lambda s: float(s._kb.F[s._k, 0]))              # F_QTY
    avg = property(lambda s: float(s._kb.F[s._k, 1]))              # F_AVG
    timeout_ms = property(lambda s: int(s._kb.PI[s._k, 2]))        # PI_TIMEOUT
    cooldown_ms = property(lambda s: int(s._kb.PI[s._k, 3]))       # PI_COOL
    is_long = property(lambda s: bool(s._kb.PI[s._k, 0]))          # PI_LONG
    is_open = property(lambda s: bool(s._kb.I[s._k, 0]))           # I_OPEN
    pending_entry = property(lambda s: bool(s._kb.I[s._k, 1]))     # I_PE
    layer_count = property(lambda s: int(s._kb.I[s._k, 3]))        # I_LAYERS
    entry_time = property(lambda s: int(s._kb.I[s._k, 4]))         # I_ENTRY_T


class KernelPaperBook(KernelBook):
    """Sổ paper của bot = KernelBook (engine duy nhất) với đúng mặt PaperBook mà bot / API / test dùng: books, ledger, venue (None), symbols, risk, trade_start,
    last_close / last_low / last_high / last_open, peak_mtm, halted_at, last_t, trades, rejected_for_risk, events, mtm(), positions(), step_bar(t, bars, sig, funding).
    Paper PHẢI bước mọi điểm lưới có nến (hợp đồng bộ đếm lưới I_BLK, xem KernelBook); `Bot.advance_paper` đã làm vậy."""

    engine = "kernel"
    venue = None

    def __init__(self, strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str, capital: float, risk: Dict[str, Any],
                 trade_start: int = 0, record_events: bool = False):
        super().__init__(strategies, symbols, base_frame, capital, risk, trade_start, record_events=record_events)

    @property
    def books(self) -> List[Dict[str, Any]]:
        return [{"symbol": sym, "entries": [{"strategy": self.slots[k]["strategy"], "side": self.slots[k]["side"], "tracker": _SlotRO(self, k)}
                                            for k in self.entries[b]]}
                for b, sym in enumerate(self.symbols)]


class SlotDriver:
    """Một hay vài slot dùng chung MỘT sổ vốn, chạy bằng slot_bar / slot_funding / slot_force_close — thay PositionTracker trong test và harness (T5).
    `driver[k]` là SlotView có giao diện đọc + on_bar / apply_funding / force_close / unrealized_pnl_usd / orders / position của PositionTracker.
    Id lệnh rút từ dãy toàn cục theo thứ tự tạo (như tracker)."""

    def __init__(self, specs: List[Any], meta: Optional[List[Tuple[str, str]]] = None, amm: Optional[List[Optional[Dict[str, Any]]]] = None):
        self.nt = len(specs)
        self.specs = list(specs)
        self.P, self.PI, self.F, self.I = pack_slots(specs, amm)
        led = getattr(specs[0], "ledger", None)   # SlotSpec: sổ vốn mới (vốn đầu = initial_capital); PositionTracker (đường cũ): sổ của nó
        if led is not None:
            self.LG = np.array([float(led.equity), float(led.reserved), float(led.peak)])
            self.cfg_f = np.array([float(led.initial)])
        else:
            self.LG = np.array([specs[0].entry_equity, 0.0, specs[0].entry_equity])
            self.cfg_f = np.array([specs[0].capital])
        self.G = np.zeros(NG, dtype=np.int64)
        self._alloc(64, 256)
        self.ids: List[int] = []
        self._ns = [_Ns() for _ in specs]
        self._meta = meta if meta is not None else [(tr.symbol, "") for tr in specs]
        self.ledger = _LedgerView(self)
        self.views = [SlotView(self, k) for k in range(self.nt)]
        self._ml = (self.P.shape[1] - P_FIXED) // 2

    def __getitem__(self, k: int) -> "SlotView":
        return self.views[k]

    def set_amm(self, k: int, reserve_base: float, reserve_quote: float, quote_usd: float) -> None:
        """Dự trữ pool của slot k tại tick sắp bước (slot chạy `amm=` ở pack_slots)."""
        self.F[k, F_RB], self.F[k, F_RQ], self.F[k, F_QU], self.F[k, F_MID] = _amm_state(reserve_base, reserve_quote, quote_usd, bool(self.P[k, P_ASTABLE]))

    def _alloc(self, cp: int, co: int) -> None:
        self.outF, self.outI, self.ordF, self.ordI, self.closeSeq = _alloc(cp, co, 1)[:5]

    def _grow(self) -> None:
        G = self.G
        if G[G_NPOS] + 2 > self.outF.shape[0] or G[G_NORD] + self._ml + 4 > self.ordF.shape[0]:
            cp, co = self.outF.shape[0] * 2, self.ordF.shape[0] * 2
            self.outF, self.outI = (np.vstack([a, np.zeros((cp - a.shape[0], a.shape[1]), dtype=a.dtype)]) for a in (self.outF, self.outI))
            self.ordF, self.ordI = (np.vstack([a, np.zeros((co - a.shape[0], a.shape[1]), dtype=a.dtype)]) for a in (self.ordF, self.ordI))
            self.closeSeq = np.concatenate([self.closeSeq, np.zeros(cp - self.closeSeq.shape[0], dtype=np.int64)])

    def _draw_ids(self) -> None:
        while len(self.ids) < int(self.G[G_NORD]):
            self.ids.append(next_id())

    def _outs(self):
        return (self.outF, self.outI, self.ordF, self.ordI, self.closeSeq)

    def _closed_since(self, c0: int) -> Optional[PositionModel]:
        c1 = int(self.G[G_NCL])
        if c1 <= c0:
            return None
        self._draw_ids()
        pos, _ = _build_objects(self.specs, self._meta, self.F, self.I, self._outs(), self.G, ids=self.ids, closed_range=(c0, c1), ns=self._ns)
        return pos[-1]

    def refresh_open(self) -> None:
        """Dựng lại `position` (vị thế đang mở) và `orders` (LỊCH SỬ lệnh của slot: các vị thế đã đóng theo thứ tự đóng, rồi vị thế đang mở — như
        PositionTracker.orders) của từng slot."""
        self._draw_ids()
        closed, orders = _build_objects(self.specs, self._meta, self.F, self.I, self._outs(), self.G, ids=self.ids, ns=self._ns)
        by_pos: Dict[int, list] = {}
        for o in orders:
            by_pos.setdefault(o.position_id, []).append(o)
        hist: List[list] = [[] for _ in range(self.nt)]
        ncl = int(self.G[G_NCL])
        for p, pos in zip(self.closeSeq[:ncl].tolist(), closed):
            hist[int(self.outI[p, OI_TR])].extend(by_pos.get(pos.result_id, []))
        for k, ns in enumerate(self._ns):
            ns.orders = hist[k] + ns.orders


class SlotView:
    """Slot k của SlotDriver / của một lần chạy batch — bề mặt đọc của PositionTracker (trạng thái từ mảng; tham số tĩnh từ SlotSpec)."""

    def __init__(self, drv: SlotDriver, k: int):
        self._d, self._k = drv, k
        self.max_new_notional = self.max_new_risk = float("inf")
        self.risk_scale = 1.0

    def __getattr__(self, name: str):   # tham số tĩnh đã chuẩn hoá (market, is_long, match_tree, base_sl, ...) lấy từ SlotSpec của slot
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._d.specs[self._k], name)

    def _f(col):   # noqa: N805
        return property(lambda s: float(s._d.F[s._k, col]))

    def _i(col):   # noqa: N805
        return property(lambda s: int(s._d.I[s._k, col]))

    def _b(col):   # noqa: N805
        return property(lambda s: bool(s._d.I[s._k, col]))

    qty, avg, margin_used, fees_paid = _f(F_QTY), _f(F_AVG), _f(F_MU), _f(F_FP)
    last_fill, next_margin, peak, mae_usd = _f(F_LAST_FILL), _f(F_NEXT), _f(F_PEAK), _f(F_MAE)
    reserved_here, funding_paid, entry_equity = _f(F_RES_HERE), _f(F_FUND), _f(F_ENTRY_EQ)
    max_capital, pos_leverage, planned_risk, pending_vol = _f(F_MAXCAP), _f(F_POS_LEV), _f(F_PLANNED), _f(F_PVOL)
    sl_pct, tp_pct, trail_pct, trail_activation_pct, unit_pct = _f(F_SL), _f(F_TP), _f(F_TRAIL), _f(F_TACT), _f(F_UNIT)
    layer_count, entry_time, dca_rejected, skipped_no_vol = _i(I_LAYERS), _i(I_ENTRY_T), _i(I_DCAREJ), _i(I_SKIP)
    is_open, pending_exit, dca_ok = _b(I_OPEN), _b(I_PX), _b(I_DCAOK)
    del _f, _i, _b

    @property
    def pending_entry(self) -> bool:
        return bool(self._d.I[self._k, I_PE])

    @pending_entry.setter
    def pending_entry(self, v: bool) -> None:
        self._d.I[self._k, I_PE] = 1 if v else 0

    @property
    def dca_steps(self) -> List[float]:
        n = int(self._d.I[self._k, I_NST])
        return [float(x) for x in self._d.F[self._k, F_DS0:F_DS0 + n]]

    @property
    def last_close_time(self) -> Optional[int]:
        return int(self._d.I[self._k, I_LASTCLOSE]) if self._d.I[self._k, I_HASLC] else None

    @property
    def position(self) -> Optional[PositionModel]:
        self._d.refresh_open()
        return self._d._ns[self._k].position

    @property
    def orders(self) -> List[OrderModel]:
        self._d.refresh_open()
        return self._d._ns[self._k].orders

    def unrealized_pnl_usd(self, price: float) -> float:
        return float(_unreal(self._k, float(price), self._d.PI, self._d.F, self._d.I))

    def apply_funding(self, rate: float, price: float, t: int = 0) -> float:
        d = self._d
        return float(slot_funding(self._k, float(rate), float(price), d.PI, d.F, d.I, d.LG))

    def on_bar(self, t: int, o: float, h: float, l: float, c: float, entry_signal: bool = False, stop_signal: bool = False,
               can_open: bool = True, vol: float = float("nan"), dca_gate: bool = True,
               minute: Optional[Tuple[np.ndarray, np.ndarray, int, int]] = None) -> Optional[PositionModel]:
        d = self._d
        d._grow()
        ML, MH, ja, jb = minute if minute is not None else (_ONE_F, _ONE_F, 0, 0)
        X = np.array([o, h, l, c, self.max_new_notional, self.max_new_risk, self.risk_scale, vol if vol is not None else np.nan])
        FL = np.array([bool(entry_signal), bool(stop_signal), bool(can_open), bool(dca_gate)], dtype=np.int64)
        c0 = int(d.G[G_NCL])
        slot_bar(self._k, int(t), X, FL, ML, MH, int(ja), int(jb), d.P, d.PI, d.F, d.I, d.LG, d.G, d.outF, d.outI, d.ordF, d.ordI, d.closeSeq)
        _amm_check(d.G)
        if d.G[G_OVF] != 0:
            raise RuntimeError("SlotDriver: tràn bộ đệm kết quả")
        return d._closed_since(c0)

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        d = self._d
        d._grow()
        c0 = int(d.G[G_NCL])
        slot_force_close(self._k, int(t), float(raw_price), R_KILL if reason.startswith("Kill") else R_END, d.P, d.PI, d.F, d.I, d.LG, d.G,
                         d.outF, d.outI, d.ordF, d.ordI, d.closeSeq)
        _amm_check(d.G)
        return d._closed_since(c0)


# ─── Đơn tài sản ────────────────────────────────────────────────────────────
def run_backtest(eng: Any) -> None:
    """BacktestEngine.run() (sau khi đã nạp dữ liệu): dựng ma trận kernel đa khung, tính tín hiệu bằng VectorEvaluator rồi chạy kernel."""
    import time
    eng.closed_positions, eng.orders, eng.equity_curve = [], [], []
    print(f"Bắt đầu chạy backtest cho {eng.symbol} ({len(eng.df_base)} nến {eng.base_frame})...")
    started = time.time()
    df1, cols = eng._build_matrix()
    n = len(df1)
    vec = matrix_evaluator(cols, n)
    signals = [(vec.tree(tr.match_tree), vec.tree(tr.stop_tree), vec.tree(tr.dca_tree) if tr.dca_tree else None) for tr in eng.slots]
    vols = [cols.get(eng.vol_column(tr)) if eng.vol_column(tr) else None for tr in eng.slots]
    real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)   # chỉ nến có giao dịch (nến điền is_filled=1 bị bỏ qua hoàn toàn)
    eng.ruined_at = None
    f_t = eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64")
    f_r = eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([])
    t_r = df1["open_time"].to_numpy(dtype="int64")[real]
    run_single(eng, t_r, df1["open"].to_numpy(dtype="float64")[real],
               df1["high"].to_numpy(dtype="float64")[real], df1["low"].to_numpy(dtype="float64")[real],
               df1["close"].to_numpy(dtype="float64")[real], [(m[real], s[real], g[real] if g is not None else None) for m, s, g in signals],
               [v[real] if v is not None else None for v in vols], f_t, f_r,
               eng.minute_path(t_r) if eng.needs_minute_path() else None)
    print(f"Hoàn thành backtest. Thu được {len(eng.closed_positions)} vị thế. Mất {time.time() - started:.2f} giây.")


def run_single(eng: Any, t, o, h, l, c, signals: List[Tuple[np.ndarray, ...]], vols: List[Optional[np.ndarray]],
               f_t: np.ndarray, f_r: np.ndarray, minute: Optional[Dict[str, np.ndarray]] = None) -> None:
    """BacktestEngine.run(): các mảng CHỈ gồm nến có giao dịch (đã lọc is_filled). Ghi kết quả vào eng."""
    specs = eng.slots
    nt, n = len(specs), len(t)
    if n == 0:
        return
    P, PI, F, I = pack_slots(specs)
    tab = _Tables(1, nt)
    tab.book(0, t, o, h, l, c, f_t, f_r, int(t[-1]), None, minute)
    for k in range(nt):
        tab.entry(k, signals[k][0], signals[k][1], vols[k], signals[k][2] if len(signals[k]) > 2 else None)
    step = eng.MTM_SAMPLE_MINUTES * 60_000
    cfg_i = np.array([eng.trade_start_ts, step], dtype=np.int64)
    cfg_f = np.array([eng.initial_capital])
    span_samples = int((int(t[-1]) - int(t[0])) // step) + 8
    cap_pos, cap_ord = _INIT_CAP_POS, _INIT_CAP_ORD
    for _ in range(_MAX_TRIES):
        outs = _alloc(cap_pos, cap_ord, min(n, span_samples + 2 * cap_pos) + 8)
        P2, PI2, F2, I2 = P.copy(), PI, F.copy(), I.copy()
        G = np.zeros(NG, dtype=np.int64)
        LG = np.array([eng.ledger.equity, eng.ledger.reserved, eng.ledger.peak])
        single_kernel(tab.PB, tab.BL, tab.PE, P2, PI2, F2, I2, cfg_i, cfg_f,
                        outs[0], outs[1], outs[2], outs[3], outs[4], outs[5], outs[6], outs[7], G, LG)
        if G[G_OVF] == 0:
            break
        cap_pos, cap_ord = cap_pos * _RETRY_FACTOR, cap_ord * _RETRY_FACTOR
    else:
        raise RuntimeError("kernel: tràn bộ nhớ đệm kết quả sau nhiều lần mở rộng")
    meta = [(eng.symbol, "") for _ in specs]
    fin = _Final(specs, P2, PI2, F2, I2)
    eng.closed_positions, eng.orders = _build_objects(specs, meta, F2, I2, outs, G, ns=fin._ns)
    eng.equity_curve = _round_curve(outs[5], outs[6], outs[7], int(G[G_NSMP]))
    eng.slot_views = fin.views
    eng.ledger.equity, eng.ledger.reserved, eng.ledger.peak = float(LG[LG_EQ]), float(LG[LG_RES]), float(LG[LG_PEAK])
    eng.ledger.rejected += int(G[G_REJ])
    eng.ruined_at = None if G[G_RUIN] == NONE_I else int(G[G_RUIN])


# ══════════════════════════════════════════════════════════════════════════
# Engine mô phỏng backtest (1m thực thi + kernel đa khung).
#
# Luồng:
# 1. Nạp nến 1m (kèm is_filled) và các khung được AST tham chiếu (luôn có 4h để tương thích).
# 2. Tính kernel (core/indicator.py) trên nến ĐÃ ĐÓNG của từng khung; kernel 1m chỉ
#    tính trên các phút CÓ giao dịch (nến điền không phải một quan sát).
# 3. Ghép vào dòng thời gian 1m: nến 1m đóng lúc T chỉ thấy nến khung F đã đóng tại thời điểm <= T
#    (merge_asof theo decision_time = open_1m + 1m và avail_time = open_F + độ dài F).
# 4. Tính tín hiệu match/stop của từng flow bằng VectorEvaluator (cùng ngữ nghĩa LogicEvaluator).
# 5. Vòng lặp khớp lệnh theo từng nến 1m có giao dịch (backtest/execution.py).
# 6. Đường vốn mark-to-market (lấy mẫu mỗi giờ + mỗi lần đóng lệnh) để đo sụt giảm cả phần lỗ treo.
# ══════════════════════════════════════════════════════════════════════════

KEY = "__bar_open_time"  # cột khoá nội bộ (tránh trùng với cột "open_time" mà AST có thể dùng)


def collect_field_refs(tree) -> Set[Tuple[str, str, int]]:
    """Mọi (frame, column, lag) mà một cây điều kiện tham chiếu."""
    refs: Set[Tuple[str, str, int]] = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "frame" in node and "column" in node:
                refs.add((str(node["frame"]), str(node["column"]), int(node.get("index", 0) or 0)))
            for key in ("number_1", "number_2", "add", "subtract", "divide"):
                if key in node:
                    walk(node[key])
            for item in node.get("numbers", []) if isinstance(node.get("numbers"), list) else []:
                walk(item)

    walk(tree)
    return refs


def frame_features(df: pd.DataFrame, refs: Set[Tuple[str, int]]) -> pd.DataFrame:
    """Tính các cột (kernel/base/legacy) + cột trễ cho một khung. df đã sắp theo open_time."""
    out = pd.DataFrame({KEY: df["open_time"].to_numpy()})
    cache: Dict[str, pd.Series] = {}
    for column, lag in sorted(refs):
        if column not in cache:
            if column in df.columns:
                cache[column] = pd.to_numeric(df[column], errors="coerce").reset_index(drop=True)
            elif kernels.is_kernel_column(column):
                cache[column] = kernels.compute(df.reset_index(drop=True), column)
            else:
                cache[column] = pd.Series(np.nan, index=range(len(df)))
        series = cache[column]
        out[lag_key(column, lag)] = (series.shift(lag) if lag else series).to_numpy()
    return out


HISTORY_START = 0   # chỉ báo tính từ đầu lịch sử dữ liệu (gốc cố định)


class BacktestEngine:
    """Điều phối dữ liệu, tín hiệu và các flow chiến lược."""

    MAX_BACKTEST_DAYS = 1100
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, account_id: int, campaign_id: int, symbol: str, start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = DEFAULT_CAPITAL, base_frame: str = "1m",
                 data: Optional[DataSource] = None):
        """data: nguồn dữ liệu (core/models.DataSource); None = nguồn mặc định của tiến trình (set_default_data_source)."""
        if base_frame not in FRAME_MS:
            raise ValueError(f"Khung chạy không hợp lệ: {base_frame!r} (có: {list(FRAME_MS)})")
        self.base_frame = base_frame   # khung nến dùng để MÔ PHỎNG (khớp lệnh, SL/TP theo high/low của nến này)
        self.data = data
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.trade_start_ts = trade_start_ts if trade_start_ts is not None else start_ts
        self.initial_capital = float(initial_capital)

        days_diff = (end_ts - start_ts) / (86400 * 1000)
        if days_diff > self.MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Limit Exceeded: Yêu cầu chạy {days_diff:.1f} ngày. "
                f"Server chỉ cho phép tối đa {self.MAX_BACKTEST_DAYS} ngày để bảo vệ tài nguyên!"
            )

        self.slots: List[SlotSpec] = []
        self.slot_views: List[Any] = []   # trạng thái cuối của từng slot sau run() (SlotView)
        self.ledger = CapitalLedger(self.initial_capital)
        self.funding: Optional[pd.DataFrame] = None  # perp: funding_time, rate
        self.df_base: Optional[pd.DataFrame] = None        # nến khung chạy của cửa sổ (đã gồm warmup)
        self.df_base_hist: Optional[pd.DataFrame] = None   # lịch sử khung chạy từ gốc (chỉ khi có cột của chính khung chạy)
        self.df_4h: Optional[pd.DataFrame] = None
        self.frames: Dict[str, pd.DataFrame] = {}
        self.closed_positions = []
        self.orders = []
        self.equity_curve: List[Dict[str, float]] = []

    # ─── Cấu hình ───────────────────────────────────────────────────────────
    def add_strategy_flow(self, flow_name: str, params: StrategyParams):
        if len(self.slots) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")
        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast.get("type", "") or params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT
        self.slots.append(SlotSpec(
            account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol, flow_name=flow_name,
            params=params, pos_type=pos_type, initial_capital=self.initial_capital, entry_equity=self.ledger.equity,
        ))

    def _refs_by_frame(self) -> Dict[str, Set[Tuple[str, int]]]:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for frame, refs in (getattr(self, "extra_refs", None) or {}).items():   # vd. đặc trưng regime (core/regime)
            by_frame.setdefault(frame, set()).update(refs)
        for tracker in self.slots:
            for frame, column, lag in (collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree)
                                       | collect_field_refs(tracker.dca_tree)):
                by_frame.setdefault(frame, set()).add((column, lag))
            if tracker.exit_unit == "atr":  # ATR% cho SL/TP/trailing theo biến động
                by_frame.setdefault(tracker.atr_frame, set()).add((f"natr_{tracker.atr_period}", 0))
        return by_frame

    @staticmethod
    def vol_column(tracker: Any) -> Optional[str]:
        return f"{tracker.atr_frame}|natr_{tracker.atr_period}" if tracker.exit_unit == "atr" else None

    def _warmup_ms(self, frame: str, refs: Set[Tuple[str, int]]) -> int:
        bars = max([kernels.warmup_bars(c) + lag for c, lag in refs] + [0])
        return (bars + 2) * FRAME_MS[frame]

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def check_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Mọi khung tín hiệu / ATR phải >= khung chạy (không thể nhìn nến nhỏ hơn nến đang mô phỏng)."""
        refs = self._refs_by_frame() if refs is None else refs
        small = sorted(fr for fr in refs if fr in FRAME_MS and FRAME_MS[fr] < FRAME_MS[self.base_frame])
        if small:
            raise ValueError(f"Khung {small} nhỏ hơn khung chạy {self.base_frame} — chọn khung tín hiệu/ATR >= {self.base_frame}")

    def _src(self) -> DataSource:
        return data_source(getattr(self, "data", None))

    def load_data(self):
        refs = self._refs_by_frame()
        self.check_frames(refs)
        base = self.base_frame
        warm = self._warmup_ms(base, refs.get(base, set()))
        src = self._src()
        # df_base = nến của KHUNG CHẠY (mặc định 1m)
        self.df_base = self._prepare_candles(src.candles(self.symbol, base, self.start_ts - warm, self.end_ts))
        # chỉ báo trên chính khung chạy tính từ đầu lịch sử (gốc cố định) -> cần cả lịch sử khi có cột của khung chạy
        self.df_base_hist = src.candles(self.symbol, base, HISTORY_START, self.end_ts) if refs.get(base) else None
        if self.trade_start_ts < self.start_ts:
            self.trade_start_ts = self.start_ts

        self.load_frames(refs)
        if any(tr.market == "perp" for tr in self.slots):
            self.funding = self._load_funding()

    def minute_path(self, open_time: np.ndarray) -> Dict[str, np.ndarray]:
        """Đường giá 1m bên trong từng nến chạy (khung chạy > 1m) — cho khớp "extreme" đúng ngữ nghĩa 1m: lệnh stop khớp ở giá xấu nhất của
        NẾN 1m ĐẦU TIÊN chạm mức, không phải của cả nến 15m/1h/4h (quá bi quan, phụ thuộc khung chạy).
        -> {"m_a", "m_b": int64 (n) — nến chạy i gồm nến 1m [m_a[i], m_b[i]), "m_l", "m_h": float64}. Khung chạy 1m: mảng rỗng."""
        t = np.asarray(open_time, dtype="int64")
        if self.base_frame == "1m" or len(t) == 0:
            return {"m_a": np.zeros(0, dtype="int64"), "m_b": np.zeros(0, dtype="int64"), "m_l": np.zeros(0), "m_h": np.zeros(0)}
        step = FRAME_MS[self.base_frame]
        m1 = self._src().candles(self.symbol, "1m", int(t[0]), int(t[-1]) + step - 1,
                                 columns=["open_time", "high", "low", "is_filled"], use_cache=False)
        if "is_filled" in m1.columns:   # nến 1m điền (không giao dịch) không thể khớp lệnh
            m1 = m1[pd.to_numeric(m1["is_filled"], errors="coerce").fillna(0).astype(int) == 0]
        mt = m1["open_time"].to_numpy(dtype="int64")
        return {"m_a": np.searchsorted(mt, t).astype("int64"), "m_b": np.searchsorted(mt, t + step).astype("int64"),
                "m_l": m1["low"].to_numpy(dtype="float64"), "m_h": m1["high"].to_numpy(dtype="float64")}

    def needs_minute_path(self) -> bool:
        return needs_minute_path(self)

    def load_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Nạp các khung lớn (không gồm 1m) từ ĐẦU lịch sử dữ liệu tới end_ts: chỉ báo tính từ gốc cố định (như TradingView) nên giá trị
        tại nến t không phụ thuộc cửa sổ backtest bắt đầu ở đâu (chỉ phụ thuộc dữ liệu <= t)."""
        refs = self._refs_by_frame() if refs is None else refs
        for frame in sorted(set(refs) | {"4h"}):
            if frame == self.base_frame or frame not in FRAME_MS or FRAME_MS[frame] < FRAME_MS[self.base_frame]:
                continue
            df = self._prepare_candles(self._src().candles(self.symbol, frame, HISTORY_START, self.end_ts))
            self.frames[frame] = self._enrich_4h(df) if frame == "4h" else df
        self.df_4h = self.frames.get("4h")

    def _load_funding(self) -> Optional[pd.DataFrame]:
        """funding.pkl của instrument perp (nếu symbol là BTC@perp; DataSource.funding). Không có -> None (ghi rõ trong kết quả)."""
        df = self._src().funding(self.symbol)
        if df is None:
            return None
        return df[(df["funding_time"] >= self.start_ts) & (df["funding_time"] <= self.end_ts)].sort_values("funding_time")

    # ─── Chạy ───────────────────────────────────────────────────────────────
    def _build_matrix(self, only: Optional[Set[str]] = None) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
        """only: chỉ tính các cột có tên trong tập này ("khung|cột[__lagN]") — dữ liệu dùng chung điền cột còn thiếu.
        Mỗi cột tính độc lập trên khung đã nạp theo refs ĐẦY ĐỦ (frame_features), nên giá trị y hệt khi tính cả bộ."""
        df1 = self._prepare_candles(self.df_base)
        if "is_filled" not in df1.columns:
            df1["is_filled"] = 0
        df1["is_filled"] = pd.to_numeric(df1["is_filled"], errors="coerce").fillna(0).astype(int)
        refs = self._refs_by_frame()
        if only is not None:
            refs = {fr: {(c, lag) for c, lag in rs if f"{fr}|{lag_key(c, lag)}" in only} for fr, rs in refs.items()}
            refs = {fr: rs for fr, rs in refs.items() if rs}
        cols: Dict[str, np.ndarray] = {}
        open_time = df1["open_time"].to_numpy()
        base = self.base_frame
        for frame in ([base] if base in refs else []) + [f for f in refs if f != base]:
            if frame not in FRAME_MS:
                continue
            t_frame, vals = self.frame_values(frame, refs[frame])
            idx = self.align_index(frame, t_frame, open_time, base)
            for cid, v in vals.items():
                cols[cid] = self.gather(v, idx)
        return df1, cols

    def frame_values(self, frame: str, refs: Set[Tuple[str, int]]) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """Giá trị các cột `refs` của khung `frame` trên MỌI nến của khung từ đầu lịch sử (gốc cố định) -> (open_time nến, {cid: giá trị}).
        Khung 1m: chỉ phút có giao dịch (bỏ nến điền). Khung lớn: các nến đã nạp bằng load_frames. Mỗi cột tính độc lập."""
        if frame == self.base_frame:
            src = getattr(self, "df_base_hist", None)
            if src is None:
                src = self.df_base       # dữ liệu gán thẳng (test) = toàn bộ lịch sử
            if src is None:            # đường dữ liệu dùng chung: engine chưa nạp gì
                src = self._src().candles(self.symbol, frame, HISTORY_START, self.end_ts)
            src = self._prepare_candles(src)
            if "is_filled" in src.columns:
                src = src[pd.to_numeric(src["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
            if frame == "4h":
                src = self._enrich_4h(src)
        elif frame == "4h" and self.df_4h is not None and not self.df_4h.empty:
            src = self._enrich_4h(self._prepare_candles(self.df_4h))
        else:
            src = self.frames.get(frame)
        if src is None or src.empty:
            return np.zeros(0, dtype="int64"), {f"{frame}|{lag_key(c, lag)}": np.zeros(0) for c, lag in sorted(refs)}
        feat = frame_features(src, refs)
        return (feat[KEY].to_numpy(dtype="int64"),
                {f"{frame}|{name}": feat[name].to_numpy(dtype="float64") for name in feat.columns if name != KEY})

    @staticmethod
    def align_index(frame: str, t_frame: np.ndarray, open_time: np.ndarray, base: str = "1m") -> np.ndarray:
        """Chỉ số nến khung dùng ở từng nến chạy `open_time` (-1 = chưa có). Khung = khung chạy: đúng nến đó (nến không giao dịch -> -1).
        Khung lớn hơn: nến cuối ĐÃ ĐÓNG trước thời điểm quyết định (open + độ dài khung <= t + độ dài nến chạy); open_time khung tăng ngặt
        (_prepare_candles bỏ trùng) nên searchsorted phải − 1 chọn đúng nến như merge_asof(direction="backward")."""
        q = np.asarray(open_time, dtype="int64")
        if len(t_frame) == 0:
            return np.full(len(q), -1, dtype="int64")
        if frame == base:
            pos = np.searchsorted(t_frame, q)
            hit = pos < len(t_frame)
            hit[hit] = t_frame[pos[hit]] == q[hit]
            pos[~hit] = -1
            return pos.astype("int64")
        return (np.searchsorted(t_frame + FRAME_MS[frame], q + FRAME_MS[base], side="right") - 1).astype("int64")

    @staticmethod
    def gather(vals: np.ndarray, idx: np.ndarray) -> np.ndarray:
        """Giá trị theo chỉ số căn phút (-1 -> NaN)."""
        if len(vals) == 0:
            return np.full(len(idx), np.nan)
        out = vals[np.maximum(idx, 0)]
        out[idx < 0] = np.nan
        return out

    def run(self):
        """Chạy backtest bằng kernel numba (KernelBook, đầu file này) — kết quả trùng từng bit với vòng lặp Python cũ (test/reference_engine.py)."""
        if self.df_base is None or self.df_base.empty:
            return
        run_backtest(self)

    def get_results(self):
        return {"positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
                "ruined_at": getattr(self, "ruined_at", None), "final_equity": self.ledger.equity,
                "rejected_for_capital": self.ledger.rejected,
                "dca_layers_rejected": sum(v.dca_rejected for v in self.slot_views),
                "funding_modeled": self.funding is not None,
                "funding_events": 0 if self.funding is None else int(len(self.funding))}

    # ─── Tiện ích dữ liệu ───────────────────────────────────────────────────
    @staticmethod
    def _prepare_candles(df: Optional[pd.DataFrame]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        if "open_time" not in df.columns:
            raise ValueError("Candle data thiếu cột open_time.")
        clean = df.reset_index(drop=True).copy()
        clean["open_time"] = pd.to_numeric(clean["open_time"], errors="coerce")
        clean = clean.dropna(subset=["open_time"])
        clean["open_time"] = clean["open_time"].astype("int64")
        for column in DATA_COLUMNS:
            if column in clean.columns:
                clean[column] = pd.to_numeric(clean[column], errors="coerce")
        return clean.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

    @classmethod
    def _enrich_4h(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Cột 4h kiểu cũ (atr*, Keltner kup/kmid/klo) — giữ để tương thích template cũ."""
        if df is None or df.empty or not {"high", "low", "close"}.issubset(df.columns):
            return df
        if "kup20_15" in df.columns:
            return df
        enriched = df.copy()
        high, low, close = enriched["high"], enriched["low"], enriched["close"]
        prev_close = close.shift(1)
        true_range = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                               axis=1).max(axis=1)
        for period in (14, 17, 20):
            enriched[f"atr{period}"] = true_range.rolling(period, min_periods=1).mean()
        enriched["atr"] = enriched["atr17"]
        for period, multiplier in cls.KELTNER_CONFIGS:
            mid = close.ewm(span=period, adjust=False, min_periods=1).mean()
            suffix = f"{period}_{str(multiplier).replace('.', '')}"
            enriched[f"kmid{suffix}"] = mid
            enriched[f"kup{suffix}"] = mid + enriched[f"atr{period}"] * multiplier
            enriched[f"klo{suffix}"] = mid - enriched[f"atr{period}"] * multiplier
        return enriched

    @staticmethod
    def _keltner_suffix(period: int, multiplier: float) -> str:
        return f"{period}_{str(multiplier).replace('.', '')}"


def needs_minute_path(eng) -> bool:
    """Có cần đường giá 1m trong nến chạy không: khung chạy > 1m và có chiến lược khớp SL "extreme". Hàm tự do để engine tham chiếu
    (test/reference_engine.py) đi qua cùng đường dữ liệu dùng chung."""
    return getattr(eng, "base_frame", "1m") != "1m" and any(getattr(tr, "stop_fill", "level") == "extreme" for tr in getattr(eng, "slots", []))


# ══════════════════════════════════════════════════════════════════════════
# Backtest DANH MỤC: nhiều tài sản × nhiều chiến lược trên MỘT sổ vốn và MỘT dòng thời gian.
#
# Vì sao: tham số không được chỉnh theo từng tài sản. Mỗi chiến lược có một bộ tham số dùng chung
# (SL/TP/trailing theo bội số ATR, khối lượng theo rủi ro), chạy trên cả vũ trụ tài sản, và vốn được
# phân bổ theo rủi ro ở cấp danh mục:
#
# - Sổ vốn chung (CapitalLedger): mọi vị thế của mọi tài sản giữ chỗ ký quỹ + phí từ cùng một quỹ.
# - Giới hạn danh mục (RiskConfig), kiểm tra lúc vào lệnh:
#     max_positions        số vị thế mở đồng thời tối đa (toàn danh mục)
#     max_per_symbol       số vị thế tối đa trên một tài sản (mọi chiến lược cộng lại)
#     max_gross_exposure   Σ giá trị danh nghĩa vị thế mở / vốn — lệnh mới bị THU NHỎ cho vừa phần còn lại
#     kill_switch_dd_pct   vốn MTM sụt từ đỉnh >= ngưỡng -> đóng hết (market) và dừng giao dịch (như bot thật)
# - Thứ tự trong một phút: các tài sản xử lý theo thứ tự cố định của danh sách (tái lập được).
#
# Mỗi tài sản dùng lại BacktestEngine để nạp dữ liệu, tính kernel đa khung (chỉ nến đã đóng) và funding,
# nên ngữ nghĩa từng vị thế giống hệt backtest đơn tài sản (test đối chiếu trong test_portfolio_engine.py).
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class RiskConfig:
    max_positions: int = 8
    max_per_symbol: int = 1
    max_gross_exposure: float = 3.0
    kill_switch_dd_pct: float = 30.0   # 0 = tắt
    max_open_risk_pct: float = 0.0     # trần Σ rủi ro tới SL (cả rổ DCA) của mọi vị thế đang mở, % vốn; lệnh mới bị thu nhỏ / chặn. 0 = tắt
    dd_throttle_pct: float = 0.0       # vốn đã chốt sụt d% so với đỉnh -> rủi ro lệnh mới × max(sàn, 1 − d / mức này). 0 = tắt
    dd_throttle_floor: float = 0.25    # hệ số rủi ro tối thiểu khi đang giảm theo mức sụt

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RiskConfig":
        return config_from_dict(cls, d)


# Bộ nhớ đệm dữ liệu theo tiến trình: (symbol, start, end, refs, perp) -> mảng giá + cột kernel + funding — DataSource.memo (nguồn dữ liệu sở hữu,
# backend/optimize/search/evaluate.py: ByteLRU theo NORA_DATA_CACHE_MB, mặc định 1500 MB, có khoá cho API đa luồng).
# Khi tối ưu ngưỡng tín hiệu / tham số vị thế, cột kernel không đổi nên chỉ tính một lần.


def data_cache_clear(data: Optional[DataSource] = None) -> None:
    """Xóa bộ nhớ đệm mảng (DataSource.memo) — gọi giữa các chiến lược ứng viên để giải phóng RAM."""
    data_source(data).memo.clear()


def aggregate_positions(positions) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Lệnh đã đóng -> (by_strategy, by_symbol): {pnl_usd, trades, wins, fees_usd, funding_usd} — dùng chung cho engine danh mục và backtest tick."""
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_symbol: Dict[str, Dict[str, float]] = {}
    for p in positions:
        for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
            agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
            agg["pnl_usd"] += p.real_pnl
            agg["trades"] += 1
            agg["wins"] += int(p.real_pnl > 0)
            agg["fees_usd"] += p.fees_usd or 0.0
            agg["funding_usd"] += p.funding_usd or 0.0
    return by_strategy, by_symbol


def _strategy_flow(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": strategy["side"], "match": [{"condition": strategy["tree"]}], "stop": strategy.get("stop") or [],
            "dca": strategy.get("dca") or []}


class PortfolioEngine:
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = DEFAULT_CAPITAL,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True, base_frame: str = "1m",
                 data: Optional[DataSource] = None):
        """data: nguồn dữ liệu (core/models.DataSource); None = nguồn mặc định của tiến trình (set_default_data_source).
        base_frame: khung nến dùng để mô phỏng (1m mặc định; 15m/1h/4h chạy nhanh hơn nhiều, khung tín hiệu phải >= khung chạy).
        strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (DataSource.shared_*; optimize/search/evaluate.py); mặc định env NORA_SHARED_DATA_DIR.
        Có thì _load_symbol ưu tiên đọc mmap (chỉ đọc) thay vì tự dựng; không thấy khoá thì dựng như cũ."""
        if not symbols or not strategies:
            raise ValueError("Cần ít nhất một tài sản và một chiến lược")
        ids = [s["id"] for s in strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("id chiến lược phải khác nhau")
        self.symbols = list(symbols)
        self.strategies = strategies
        self.start_ts, self.end_ts = int(start_ts), int(end_ts)
        self.trade_start_ts = int(trade_start_ts if trade_start_ts is not None else start_ts)
        self.initial_capital = float(initial_capital)
        self.risk = risk or RiskConfig()
        self.venue = venue
        self.use_cache = use_cache
        self.data = data
        self.shared_dir = shared_dir or os.environ.get("NORA_SHARED_DATA_DIR") or None
        self.ledger = CapitalLedger(self.initial_capital)
        self.books: List[Dict[str, Any]] = []   # mỗi tài sản: dữ liệu + trackers
        self.closed_positions: List[Any] = []
        self.orders: List[Any] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_risk = 0           # số PHÚT lệnh vào bị chặn bởi giới hạn rủi ro (giữ nguyên nghĩa, golden dựa vào đây)
        self.risk_blocked_attempts = 0       # số LẦN vào lệnh bị chặn: các phút liên tiếp của cùng một tracker tính là một lần
        self.close_at_end = close_at_end
        self.base_frame = base_frame
        self.last_close: Dict[str, float] = {}   # giá đóng cửa cuối của từng tài sản (đặt khi run() xong)

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def _make_trackers(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, Any]]]:
        """Đường Python cũ (PaperBook / Manager / tick_run, tới T10): mỗi SlotSpec thành một PositionTracker dựng từ chính spec đó."""
        eng, pairs = self._make_slots(symbol, ledger)
        out = []
        for (st, sp) in pairs:
            tr = PositionTracker(sp.account_id, sp.campaign_id, sp.symbol, sp.flow_name, sp.params, sp.pos_type, sp.capital, ledger)
            out.append((st, tr))
        return eng, out

    def _src(self) -> DataSource:
        return data_source(getattr(self, "data", None))

    def _make_slots(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, SlotSpec]]]:
        from backend.core.params import build_params, manifest_pool_fee
        eng = BacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital, base_frame=self.base_frame, data=getattr(self, "data", None))
        eng.ledger = ledger
        pairs = []
        pool_fee = None
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            if st.get("regime"):   # đặc trưng regime đi qua cùng bộ máy căn khung với tín hiệu
                eng.extra_refs = REGIME_REFS
            name = f"{st['side']}_{st['id']}"
            if self.venue == "dex" and st["position"].get("fee_rate") is None and pool_fee is None:   # phí pool đã xác minh (manifest)
                pool_fee = manifest_pool_fee(self._src().manifest(symbol)) if symbol else None
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, pool_fee=pool_fee))
            pairs.append((st, eng.slots[-1]))
        return eng, pairs

    @staticmethod
    def _refs_signature(eng: BacktestEngine):
        return tuple(sorted((f, tuple(sorted(r))) for f, r in eng._refs_by_frame().items()))

    def _cache_key(self, symbol: str, eng: BacktestEngine) -> tuple:
        return (symbol, self.start_ts, self.end_ts, self._refs_signature(eng), any(tr.market == "perp" for tr in eng.slots),
                self.base_frame, needs_minute_path(eng))

    def _build_symbol_data(self, eng: BacktestEngine, only: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Dựng `data` của một tài sản (nến thật 1m + cột kernel + funding), không đụng cache.
        only: chỉ tính các cột này (dữ liệu dùng chung điền phần còn thiếu — optimize/search/evaluate.py, kho mmap)."""
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        df1, cols = eng._build_matrix(only=only)
        real = df1["is_filled"].to_numpy() == 0
        t = df1["open_time"].to_numpy(dtype="int64")[real]
        out = {
            "t": t,
            "o": df1["open"].to_numpy(dtype="float64")[real], "h": df1["high"].to_numpy(dtype="float64")[real],
            "l": df1["low"].to_numpy(dtype="float64")[real], "c": df1["close"].to_numpy(dtype="float64")[real],
            "cols": {k: v[real] for k, v in cols.items()},
            "f_t": eng.funding["funding_time"].to_numpy(dtype="int64") if eng.funding is not None else np.array([], "int64"),
            "f_r": eng.funding["rate"].to_numpy(dtype="float64") if eng.funding is not None else np.array([]),
        }
        if needs_minute_path(eng):   # khớp "extreme" ở khung chạy > 1m: giá xấu nhất của nến 1m đầu tiên chạm mức
            out["minute"] = eng.minute_path(t)
        return out

    def _load_shared(self, eng: BacktestEngine) -> Optional[Dict[str, Any]]:
        """Dữ liệu qua kho dùng chung (shared_dir, kho mmap ở optimize/search/evaluate.py): nền mmap + cột chỉ báo tính sẵn theo khung, căn theo chỉ số
        dùng chung. Thiếu phần nào thì tự tính ĐÚNG phần đó, ghi vào kho (tiến trình khác dùng lại) rồi đọc lại.
        Bằng từng bit với _build_symbol_data. None nếu tài sản không có 1m.pkl (dựng như thường)."""
        src = self._src()
        p = src.shared_plan(eng)
        if p is None:
            return None
        data = src.shared_load(self.shared_dir, p)
        if data is not None:
            return data
        src.shared_fill(self.shared_dir, self, eng, p)
        eng.df_base, eng.df_base_hist, eng.frames, eng.df_4h, eng.funding = None, None, {}, None, None   # như khi đọc thẳng kho
        src.release()
        return src.shared_load(self.shared_dir, p)

    def _load_symbol(self, symbol: str, eng: BacktestEngine) -> Dict[str, Any]:
        if self.shared_dir:  # mmap chỉ đọc dùng chung — KHÔNG đưa vào DataSource.memo (không nhân bản RAM)
            data = self._load_shared(eng)
            if data is not None:
                return data
        key = self._cache_key(symbol, eng)
        memo = self._src().memo if self.use_cache else None
        if self.use_cache:
            cached = memo.get(key)
            if cached is not None:
                return cached
        data = self._build_symbol_data(eng)
        if self.use_cache:
            arrays = ([data[k] for k in ("t", "o", "h", "l", "c", "f_t", "f_r")] + list(data["cols"].values())
                      + list((data.get("minute") or {}).values()))
            memo.put(key, data, sum(a.nbytes for a in arrays))
        return data

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_slots(sym, self.ledger)
            if not pairs:   # không chiến lược nào chạy trên tài sản này (chỉ xảy ra khi dùng khoá "symbols")
                continue
            # Cổng chất lượng dữ liệu BẮT BUỘC (synthetic / sai sha256 / thiếu dữ liệu -> từ chối); có cache theo file nên rẻ khi gọi lại.
            # Tiến trình cha của CLI đã gọi trước khi fork pool -> worker thừa kế cache, không đọc lại 1m.
            self._src().require_ok([sym])
            data = self._load_symbol(sym, eng)
            n = len(data["t"])
            cols = data["cols"]
            vec = matrix_evaluator(cols, n)
            labels = _regime_labels(pairs, cols, n, data["t"])
            entries = []
            for st, tr in pairs:
                vcol = BacktestEngine.vol_column(tr)
                match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
                match, stop = _regime_gate(st, labels, match, stop)   # lọc tín hiệu vào theo regime + cầu chì thoát khi sốc ngược chiều
                entries.append({
                    "strategy": st["id"], "slot": tr, "match": match, "stop": stop,
                    "vol": cols.get(vcol) if vcol else None, "regime": labels,
                    "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None,   # điều kiện dồn tầng (None = luôn được dồn)
                })
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── Giới hạn rủi ro ────────────────────────────────────────────────────
    def run(self) -> None:
        """Chạy cả lần backtest bằng kernel numba (KernelBook, đầu file này): cùng ngữ nghĩa, kết quả trùng từng bit với vòng lặp Python cũ
        (test/reference_engine.py + test/test_kernel_parity.py)."""
        if not self.books:
            self.load_data()
        run_portfolio(self)

    def run_many(self, position_overrides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Nhiều bộ tham số vị thế/thoát lệnh trên CÙNG dữ liệu + CÙNG tín hiệu (nạp/tính một lần) -> danh sách get_results() cùng thứ tự.
        Không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR). Gom alpha theo tín hiệu là việc của backend/optimize."""
        return run_many(self, position_overrides)

    def open_positions(self) -> List[Dict[str, Any]]:
        """Vị thế còn mở sau run() (chỉ khác rỗng khi close_at_end=False), mark = giá đóng cửa cuối của tài sản."""
        out = []
        for book in self.books:
            mark = self.last_close.get(book["symbol"])
            for e in book["entries"]:
                tr = e.get("view")
                if tr is None or not tr.is_open or tr.qty <= 0 or tr.position is None or mark is None or mark != mark:
                    continue
                out.append({"symbol": book["symbol"], "strategy": e["strategy"], "side": tr.pos_type.name, "qty": tr.qty,
                            "entry_price": tr.avg, "mark_price": float(mark), "notional": tr.qty * float(mark),
                            "unrealized_pnl": tr.unrealized_pnl_usd(float(mark)), "opened": int(tr.position.enter_time),
                            "margin_usd": tr.margin_used, "leverage": tr.pos_leverage})
        return out

    def get_results(self) -> Dict[str, Any]:
        by_strategy, by_symbol = aggregate_positions(self.closed_positions)
        skipped = sum(e["view"].skipped_no_vol for b in self.books for e in b["entries"] if "view" in e)
        dca_rejected = sum(e["view"].dca_rejected for b in self.books for e in b["entries"] if "view" in e)
        return {
            "positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
            "final_equity": self.ledger.equity, "initial_capital": self.initial_capital,
            "by_strategy": by_strategy, "by_symbol": by_symbol,
            "rejected_for_capital": self.ledger.rejected, "rejected_for_risk": self.rejected_for_risk,
            "risk_blocked_attempts": self.risk_blocked_attempts,
            "skipped_no_vol": skipped, "dca_layers_rejected": dca_rejected, "halted_at": self.halted_at, "ruined_at": self.ruined_at,
            "risk": asdict(self.risk), "symbols": self.symbols, "strategies": [s["id"] for s in self.strategies],
        }


# ══════════════════════════════════════════════════════════════════════════
# Tài sản DEX trong backtest: nhận diện ký hiệu (không trộn với perp), metadata pool (phí, loại, mạng, độ phủ tick), vị thế spot-LONG và cửa sổ tick.
#
# DEX là spot AMM: không đòn bẩy, không bán khống -> chỉ chạy chân LONG (market="spot", leverage=1). Mọi số của pool (phí, loại, mạng) đọc từ
# attrs ticks.parquet ("ticks" / "onchain") của tài sản — không có giá trị mặc định theo pool; thiếu phí -> từ chối.
# ══════════════════════════════════════════════════════════════════════════

SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k


# is_dex_symbol / classify_symbols / require_perp (đọc thư mục dữ liệu): ở backend/crawl/store.py (engine-API pass — core không I/O).


def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str], by_id: Mapping[str, Dict[str, Any]]) -> None:
    """by_id: {id chiến lược: định nghĩa} (optimize/book/build.BY_ID) — core không import sổ chiến lược."""
    short = [i for i in strategy_ids if by_id[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


def check_amm_pool(info: Dict[str, Any]) -> None:
    """Pool phải có dự trữ trong tick (loại v2 nhận diện được) và có mạng — nếu không thì không mô hình hoá được AMM."""
    if info["pool_type"] not in POOL_TYPES:
        raise ValueError(f"{info['symbol']}: loại pool {info['pool_type']!r} chưa hỗ trợ — chỉ pool có dự trữ (Aerodrome/Uniswap v2): {POOL_TYPES}")
    if not info["network"]:
        raise ValueError(f"{info['symbol']}: manifest thiếu network")


def tick_window(infos: List[Dict[str, Any]], start: Optional[int], end: Optional[int], frame_ms: int) -> Tuple[int, int]:
    """Cửa sổ chạy tick [W, E] (ms) = [start, end] cắt theo độ phủ tick chung của các tài sản: W làm tròn LÊN mốc nến cơ sở kế tiếp (nến tín hiệu đầu tiên
    phủ trọn bằng tick), E = min(end, tick cuối). Ngắn hơn một nến cơ sở -> ValueError."""
    for i in infos:
        if not i["ticks"]:
            raise ValueError(f"{i['symbol']}: chưa có tick — crawl tick (data_crawl_ticks) trước khi chạy backtest tick")
    lo, hi = max(int(i["ticks"]["start_ts"]) for i in infos), min(int(i["ticks"]["end_ts"]) for i in infos)
    w = max(int(start or 0), lo)
    w = -(-w // frame_ms) * frame_ms
    e = min(int(end) if end else hi, hi)
    if e - w < frame_ms:
        raise ValueError(f"cửa sổ tick sau khi cắt theo độ phủ tick ({lo}..{hi} ms) ngắn hơn một nến cơ sở ({frame_ms // 60_000} phút)")
    return w, e


# ══════════════════════════════════════════════════════════════════════════
# Tín hiệu của sổ trên nến đã đóng (P9.10c: từ live/bot.py — phần thuần engine, không I/O)
#
# Tín hiệu của sổ trên nến ĐÃ ĐÓNG mới nhất từ dữ liệu sàn — CÙNG đường tính với backtest (E9-S1 AC4, test chênh lệch bằng 0):
# dựng engine của tài sản y như PortfolioEngine (_make_slots), nạp nến từng khung vào đúng chỗ engine tự nạp (df_base / frames), rồi
# _build_matrix + VectorEvaluator trên cây của từng slot. Không có bản tính tín hiệu thứ hai.
#
# Chỉ báo tính từ ĐẦU dữ liệu đưa vào (gốc cố định): sàn trả tối đa ~1500 nến mỗi khung, nên giá trị EMA/ADX dài ở nến cuối có thể lệch rất nhỏ so
# với backtest (tính từ 2023). Kiểm chênh lệch: test_live_bot.py (cùng dữ liệu -> trùng từng bit).
# ══════════════════════════════════════════════════════════════════════════

KLINE_COLS = ["open_time", *DATA_COLUMNS, "close_time"]


def klines_frame(rows: List[List[Any]], now_ms: int) -> pd.DataFrame:
    """Nến sàn -> DataFrame engine; bỏ nến CHƯA đóng (close_time >= now)."""
    df = pd.DataFrame([r[:7] for r in rows], columns=KLINE_COLS)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    df = df[df["close_time"].astype("int64") < now_ms].drop(columns=["close_time"]).reset_index(drop=True)
    df["is_filled"] = 0
    return df


def required_frames(symbol: str, strategies: List[Dict[str, Any]], base_frame: str) -> List[str]:
    """Các khung engine cần cho sổ (gồm khung chạy và 4h — engine luôn nạp 4h)."""
    eng, _ = _engine_slots(symbol, strategies, base_frame, 0, DAY)
    return sorted(set(eng._refs_by_frame()) | {base_frame, "4h"})



def _portfolio(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    end = max(int(end), int(start) + DAY)
    start = max(int(start), end - 1000 * DAY)
    return PortfolioEngine([symbol], strategies, start, end, trade_start_ts=start, use_cache=False, base_frame=base_frame)


def _engine_slots(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    """Engine của tài sản (chưa nạp dữ liệu) + [(chiến lược, SlotSpec)]. start/end chỉ để engine kiểm giới hạn độ dài — dữ liệu do evaluate gán trực tiếp."""
    pe = _portfolio(symbol, strategies, base_frame, start, end)
    return pe._make_slots(symbol, pe.ledger)


def matrix_evaluator(cols: Dict[str, np.ndarray], n: int) -> VectorEvaluator:
    """VectorEvaluator trên ma trận cột "khung|cột[__lagN]" (_build_matrix / kho dùng chung); cột thiếu = NaN. Một đường cho backtest, danh mục,
    tín hiệu sổ (evaluate_signals), ảnh chụp tín hiệu và kiểm tra tín hiệu."""
    return VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))


def _regime_labels(pairs: List[Tuple[Dict[str, Any], Any]], cols: Dict[str, np.ndarray], n: int, t: np.ndarray) -> Optional[Any]:
    """Nhãn regime của tài sản (None khi không chiến lược nào bật regime) — dùng chung cho PortfolioEngine.load_data và evaluate_signals."""
    if not any(st.get("regime") for st, _ in pairs):
        return None
    cfg = profile_cfg(next((st["regime"].get("classifier") for st, _ in pairs if st.get("regime")), None))
    return classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t, cfg)


def _regime_gate(st: Dict[str, Any], labels: Optional[Any], match: np.ndarray, stop: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Lọc tín hiệu vào theo regime + cầu chì thoát khi sốc ngược chiều (chiến lược không bật regime / không có nhãn: giữ nguyên)."""
    if labels is not None and st.get("regime"):
        allowed, fuse = masks_for(st, st["side"], labels)
        match = match & allowed
        if fuse is not None:
            stop = stop | fuse
    return match, stop


def evaluate_signals(symbol: str, strategies: List[Dict[str, Any]], frames: Dict[str, pd.DataFrame], base_frame: str,
             with_vec: bool = False) -> Dict[str, Any]:
    """frames = {khung: DataFrame nến đã đóng từ đầu dữ liệu}. -> {"t": open_time nến chạy, "close", "high", "low",
    "entries": [{"strategy", "side", "match": bool[], "stop": bool[], "vol": float[] | None, "slot" (SlotSpec; "tracker" = tên cũ, cùng đối tượng)}]} (mảng theo nến chạy).
    with_vec: thêm "vec" (VectorEvaluator trên cùng ma trận) để giải thích từng điều kiện (metrics/charts.py::explain)."""
    base = frames[base_frame]
    eng, pairs = _engine_slots(symbol, strategies, base_frame, int(base["open_time"].iloc[0]), int(base["open_time"].iloc[-1]))
    base = eng._prepare_candles(base)
    eng.df_base, eng.df_base_hist = base, base
    eng.frames = {fr: (eng._enrich_4h(eng._prepare_candles(df)) if fr == "4h" else eng._prepare_candles(df))
                  for fr, df in frames.items() if fr != base_frame}
    eng.df_4h = eng.frames.get("4h")
    df1, cols = eng._build_matrix()
    n = len(df1)
    vec = matrix_evaluator(cols, n)
    out = {"t": df1["open_time"].to_numpy(dtype="int64"), "open": df1["open"].to_numpy(dtype=float), "close": df1["close"].to_numpy(dtype=float),
           "high": df1["high"].to_numpy(dtype=float), "low": df1["low"].to_numpy(dtype=float), "entries": []}
    labels = _regime_labels(pairs, cols, n, out["t"])
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
        match, stop = _regime_gate(st, labels, match, stop)
        vcol = eng.vol_column(tr)
        out["entries"].append({"strategy": st["id"], "side": st["side"], "match": match, "stop": stop,
                               "vol": cols.get(vcol) if vcol else None, "slot": tr, "tracker": tr,
                               "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None})
    if with_vec:
        out["vec"] = vec
    return out


def _bar_sig(v: Dict[str, Any], i: int) -> List[Dict[str, Any]]:
    return [{"match": bool(e["match"][i]), "stop": bool(e["stop"][i]), "vol": (float(e["vol"][i]) if e["vol"] is not None else None),
             "dca": bool(e["dca"][i]) if e.get("dca") is not None else True}
            for e in v["entries"]]


# ══════════════════════════════════════════════════════════════════════════
# Ảnh chụp tín hiệu (signal_snapshot) + kiểm tra tín hiệu (check_signals) — engine-API pass: chuyển từ core/signal.py (cần PortfolioEngine /
# BacktestEngine + nguồn dữ liệu). Phần giải thích/thống kê thuần (_explain, _since, _thin, _forward_bps, _stats, _verdict) vẫn ở core/signal.py.
# Chú thích đầy đủ: core/signal.py, các mục ảnh chụp tín hiệu (snapshot) và kiểm tra tín hiệu (diagnostics).
# ══════════════════════════════════════════════════════════════════════════

def signal_snapshot(symbol: str, strategies: List[Dict[str, Any]], end_ts: int, lookback_minutes: int = DEFAULT_LOOKBACK_MIN,
                    venue: str = "cex", data: Optional[DataSource] = None) -> Dict[str, Any]:
    """Tín hiệu của `strategies` (dạng chiến lược của PortfolioEngine) trên `symbol` tại nến 1m đã đóng cuối cùng <= end_ts.
    data: nguồn dữ liệu (None = mặc định của tiến trình)."""
    start = int(end_ts) - int(lookback_minutes) * MINUTE
    pe = PortfolioEngine([symbol], strategies, start, int(end_ts), trade_start_ts=start, venue=venue, use_cache=True, data=data)
    eng, pairs = pe._make_slots(symbol, pe.ledger)
    out: Dict[str, Any] = {"symbol": symbol, "bar_open_time": None, "as_of": None, "close": None, "regime": None, "strategies": []}
    if not pairs:
        return out
    eng.extra_refs = REGIME_REFS                     # regime luôn hiển thị, cùng cột đặc trưng với backtest bật regime
    eng.load_data()
    if eng.df_base is None or eng.df_base.empty:
        return out
    df1, cols = eng._build_matrix()
    n = len(df1)
    real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)
    t_all = df1["open_time"].to_numpy(dtype="int64")
    real = real[t_all[real] < int(end_ts)]          # chỉ nến đã ĐÓNG trước end_ts
    if real.size == 0:
        return out
    i = int(real[-1])
    vec = matrix_evaluator(cols, n)
    t_real = t_all[real]
    out.update(bar_open_time=int(t_all[i]), as_of=int(t_all[i]) + MINUTE, close=_num(df1["close"].to_numpy()[i]))
    labels = classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t_all)   # ngưỡng mặc định (hiển thị), không theo hồ sơ chiến lược
    raw = raw_states(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), n)
    name = REGIME_NAMES[int(labels[i])]
    out["regime"] = {"state": name, "label": REGIME_LABEL_VI[name], "raw": REGIME_NAMES[int(raw[i])],
                     "since": _since(labels[real], t_real, len(real) - 1),
                     "features": {f"{fr} {c}": _num(cols.get(f"{fr}|{c}", np.full(n, np.nan))[i])
                                  for fr, refs in sorted(REGIME_REFS.items()) for c, _ in sorted(refs)}}
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
        entry_raw = bool(match[i])
        match, stop = _regime_gate(st, labels, match, stop)   # cùng mặt nạ với PortfolioEngine.load_data
        m_real = match[real]
        out["strategies"].append({
            "id": st["id"], "side": st["side"], "entry": bool(match[i]), "exit": bool(stop[i]), "entry_raw": entry_raw,
            "entry_since": _since(m_real, t_real, len(real) - 1),
            "entry_minutes_in_window": int(m_real.sum()),
            "entry_blocks": _explain(vec, tr.match_tree, i), "exit_blocks": _explain(vec, tr.stop_tree, i),
            "regime_allowed": (st.get("regime") or {}).get("allowed"),
            "regime_ok": bool(not st.get("regime") or labels[i] in [REGIME_CODE[x] for x in st["regime"].get("allowed") or REGIME_NAMES]),
        })
    return out


def check_signals(symbol: str, signals: Dict[str, Dict[str, Any]], start_ts: Optional[int] = None,
                  end_ts: Optional[int] = None, horizons_min: Iterable[int] = HORIZONS_MIN,
                  baseline_step: int = 7, data: Optional[DataSource] = None) -> Dict[str, Any]:
    """Kiểm tra nhiều tín hiệu trên một tài sản (nạp dữ liệu + tính kernel một lần). data: nguồn dữ liệu (None = mặc định)."""
    from backend.core.params import VENUE_COSTS, build_params, manifest_venue

    manifest = data_source(data).manifest(symbol) or {}
    venue = manifest_venue(manifest)
    start_ts = int(start_ts or manifest.get("start_ts"))
    end_ts = int(end_ts or manifest.get("end_ts"))

    engine = BacktestEngine(0, 0, symbol, start_ts, end_ts, data=data)
    names = list(signals)
    for name in names:  # flow LONG giả chỉ để engine biết cần tính kernel nào
        engine.add_strategy_flow(f"LONG_{name}", build_params(
            f"LONG_{name}", {"match": [{"condition": signals[name]["tree"]}], "stop": []}, "LONG", {}, venue))
    engine.load_data()
    df1, cols = engine._build_matrix()
    n = len(df1)
    vec = matrix_evaluator(cols, n)

    real = df1["is_filled"].to_numpy() == 0
    in_range = df1["open_time"].to_numpy() >= start_ts
    times = df1["open_time"].to_numpy(dtype="int64")[real]
    opens = df1["open"].to_numpy(dtype="float64")[real]
    closes = df1["close"].to_numpy(dtype="float64")[real]
    pos_of_row = np.cumsum(real) - 1  # vị trí trong mảng phút-thật của mỗi dòng
    base_idx = np.arange(0, len(times) - 1, baseline_step)
    base_idx = base_idx[times[base_idx] >= start_ts]

    results: Dict[str, Any] = {}
    for name in names:
        sig = signals[name]
        sign = 1.0 if sig.get("side", "LONG") == "LONG" else -1.0
        fire = vec.tree(sig["tree"]) & real & in_range
        entry = pos_of_row[np.nonzero(fire)[0]] + 1           # vào ở phút thật kế tiếp
        entry = np.unique(entry[entry < len(times)])
        costs = VENUE_COSTS[(venue, "spot" if sign > 0 else ("perp" if venue == "cex" else "spot"))]
        cost_bps = 2 * (costs[0] + costs[2]) * 1e4  # taker + trượt, hai chiều
        by_h = {}
        for h in horizons_min:
            ev_idx = entry[_thin(times[entry], h * 60_000)] if len(entry) else entry
            ev = _forward_bps(times, opens, closes, ev_idx, h * 60_000, sign) if len(ev_idx) else np.array([])
            base = _forward_bps(times, opens, closes, base_idx, h * 60_000, sign)
            by_h[h] = _stats(ev, base, cost_bps)
        results[name] = {
            "side": sig.get("side", "LONG"),
            "family": sig.get("family"),
            "raw_signal_minutes": int(fire.sum()),
            "cost_bps_round_trip": round(cost_bps, 1),
            "horizons": by_h,
            **_verdict(by_h),
        }
    return {"symbol": symbol, "venue": venue, "start_ts": start_ts, "end_ts": end_ts, "signals": results}


# ══════════════════════════════════════════════════════════════════════════
# Dựng kế hoạch chạy (hằng số profile ở core/params.py)
#
# Thực thi chương trình DSL (docs/bmad/p7_python_strategies.md §5): chương trình đã biên dịch -> chiến lược của PortfolioEngine.
#
# Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
# cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).
#
# Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (core/indicator.py::register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


def _ref(program: Program, kind: str) -> Dict[str, Any]:
    return {"frame": program.timeframe, "column": program.column(kind), "index": 0}


def _tree(program: Program, kind: str) -> List:
    return [[[_ref(program, kind), ">", 0.5]]]


def _leg_signals(program: Program, side: str) -> Tuple[List, List]:
    """(cây vào, stop) của một chân: stop theo dạng materialize(): [{"condition": cây}]."""
    ent, ext = ("le", "lx") if side == "LONG" else ("se", "sx")
    return _tree(program, ent), [{"condition": _tree(program, ext)}]


def leg_level(program: Program, side: str, warnings: List[str]) -> float:
    """Mức |position| lớn nhất của chân; nhiều mức khác nhau -> cảnh báo (v1 chỉ dùng mức lớn nhất)."""
    levels = sorted({abs(lv) for lv in program.levels if (lv > 0 if side == "LONG" else lv < 0)})
    if len(levels) > 1:
        warnings.append(f"Chân {side} có nhiều mức position khác nhau {levels}: v1 dùng mức lớn nhất ({levels[-1]:g}) cho mọi lệnh vào, "
                        "không tăng/giảm vị thế theo mức")
    return levels[-1]


def build_plan(program: Program, symbols: List[str], position: Optional[Dict[str, Any]] = None, strategy_id: Optional[str] = None,
               run_frame: Optional[str] = None, exact_id: bool = False, data: Optional[DataSource] = None) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id). data: nguồn dữ liệu (tên tài sản trần — DataSource.base_name); None = mặc định."""
    if not symbols:
        raise ValueError("Cần ít nhất một tài sản")
    legs = program.legs
    if not legs:
        raise ValueError("Chương trình không có chân nào có mức position khác 0 (chỉ có set_positions(..., position=0))")
    warnings: List[str] = []
    base = run_frame or RUN_FRAME
    if base not in FRAME_ORDER:
        raise ValueError(f"run_frame phải thuộc {list(FRAMES)}")
    if FRAME_ORDER[program.timeframe] < FRAME_ORDER[base]:
        raise ValueError(f"timeframe của chiến lược ({program.timeframe}) nhỏ hơn khung chạy {base}")
    sid = strategy_id or f"py_{program.code_hash}"
    pos = {**BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    src = data_source(data)
    names = list(dict.fromkeys(src.base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core.params import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)


# ══════════════════════════════════════════════════════════════════════════
# Giao diện sàn dùng chung cho SimVenue / OkxVenue (phần VĨNH VIỄN)
#
# Giao diện sàn (Venue) — P6.4. Đặc tả: docs/bmad/p6_execution_design.md §3.
#
# Một Protocol duy nhất cho mọi nơi khớp lệnh: `SimVenue` (khu LEGACY cuối file: backtest-py, paper) và `OkxVenue` (live/live.py: demo, live).
# PositionManager (khu LEGACY cuối file) chỉ nói chuyện với giao diện này: đặt LỆNH (`submit`), kéo SỰ KIỆN (`next_event` -> Fill / OrderRejected),
# rồi tự áp sự kiện vào Account / PositionBook (core/models.py) — venue KHÔNG đụng vào sổ vốn.
#
# Quy ước:
# - `slot` là chỉ số slot (symbol × chiến lược) trong runner; mỗi slot có tập lệnh chờ riêng và tối đa một vị thế (net).
# - `Order.id` là định danh lệnh CHỜ (để `cancel`), do người đặt cấp bằng `new_order_id()`; KHÔNG phải `Fill.order_id`
#   (id ghi vào `OrderModel`: sim cấp bằng `next_id()` (core/models.py) lúc khớp, OKX dùng id của sàn).
# - Lệnh ENTRY/EXIT là MARKET (level = nan). SL/TRAIL/TP là lệnh bảo vệ đóng hết vị thế; DCA là lệnh limit nhồi tầng.
# - Hợp đồng chung (P6.8b): ENTRY thứ hai trên slot đã có vị thế -> OrderRejected("position_exists"); SL/TP/TRAIL/DCA khi slot chưa có vị thế ->
#   OrderRejected("no_position") — cả SimVenue lẫn OkxVenue (manager không bao giờ làm vậy, nên đường event vẫn bit-identical).
# - `next_event` là kéo (pull): trả sự kiện kế tiếp của slot hoặc None khi hết (sim khớp theo nến hiện tại, OKX đọc hàng đợi poll).
#
# ══════════════════════════════════════════════════════════════════════════

NAN = float("nan")


class OrderKind(IntEnum):
    ENTRY = 1   # market, mở tầng đầu
    EXIT = 2    # market, đóng hết (tín hiệu thoát / hết thời gian / kill)
    DCA = 3     # limit nhồi tầng
    SL = 4      # stop-loss đóng hết (từ giá TB)
    TRAIL = 5   # trailing stop đóng hết
    TP = 6      # limit chốt lời đóng hết (từ giá TB)


@dataclass
class Order:
    id: int
    slot: int
    kind: OrderKind
    is_buy: bool
    level: float = NAN          # DCA/SL/TRAIL/TP: mức giá đặt; ENTRY/EXIT: nan (market ở open)
    trigger: float = NAN        # DCA/TP có limit_through: mức phải đi QUA; mặc định (nan) = level
    notional: float = 0.0       # ENTRY/DCA (sim tính qty = notional / giá khớp); EXIT/SL/TRAIL/TP: đóng hết
    margin: float = 0.0
    reason: str = ""            # nhãn close_reason / start_reason của tracker
    reduce_only: bool = False
    post_only: bool = False
    # TRAIL (P6.8b): `level` luôn là mức stop TĨNH tính từ đỉnh các nến trước (SimVenue đọc mức này). Venue có trailing gốc (OKX) đọc thêm
    # `activation` (giá kích hoạt) và `callback_pct` (% lùi khỏi đỉnh, vd 1.5 = 1.5%); thiếu (nan) thì rơi về level / trigger như quy ước cũ.
    activation: float = NAN
    callback_pct: float = NAN
    # TRAIL cho SimVenue đường ohlc/adaptive: `peak` = đỉnh/đáy có lợi các nến TRƯỚC (venue tự chạy tiếp theo từng chặng của nến) và
    # `activation_pct` = ngưỡng lãi % để bật trailing (so với avg hiện tại); thiếu (nan) thì venue dùng `level` tĩnh như đường cũ.
    peak: float = NAN
    activation_pct: float = NAN


@dataclass(frozen=True)
class VenueCaps:
    generates_liquidation: bool   # venue tự sinh Fill thanh lý (sim); sàn thật chỉ quan sát
    native_trailing: bool         # venue có lệnh trailing gốc (OKX); sim dùng mức tĩnh tính từ đỉnh các nến trước
    post_only: bool               # venue hỗ trợ post_only cho lệnh limit
    rounds_qty: bool              # venue làm tròn qty/giá theo bộ lọc sàn


class Venue(Protocol):
    caps: VenueCaps

    def submit(self, order: Order) -> None: ...
    def cancel(self, order_id: int) -> None: ...
    def cancel_slot(self, slot: int) -> None: ...
    def open_orders(self, slot: int) -> List[Order]: ...
    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]: ...


_ORDER_ID = itertools.count(1)


def new_order_id() -> int:
    """Cấp `Order.id` mới (toàn cục, tăng dần). Tách khỏi `models._ID_SEQ` để việc đặt/huỷ lệnh chờ không tiêu id của OrderModel."""
    return next(_ORDER_ID)


# ══════════════════════════════════════════════════════════════════════════
# LEGACY PY PATH — xoá ở P9.4b T10
#
# Đường Python cũ chuyển NGUYÊN VĂN từ core/execute/{tracker,manager,sim_venue,runner}.py (P9.4b: gộp vào core/backtest.py). Chỉ còn dùng cho
# PaperBook / tick_run / test đối chiếu cho tới T10; kernel ở trên là engine duy nhất. Không thêm gì mới vào khu này.
# ══════════════════════════════════════════════════════════════════════════

# ── legacy: core/execute/tracker.py ──
#
# Quản lý vị thế (Position management) — một flow chiến lược.
#
# Vòng đời một nến 1m CÓ GIAO DỊCH (nến điền is_filled=1 bị bỏ qua hoàn toàn):
#
# 1. Đầu nến (giá open):
#    - lệnh thoát chờ (tín hiệu stop ở nến trước) hoặc hết thời gian giữ lệnh -> đóng ở open;
#    - lệnh vào chờ (tín hiệu match ở nến trước) -> mở tầng đầu ở open (+ trượt giá).
# 2. Trong nến — đường giá `intrabar_path` (policy.bar_points):
#    - "ohlc" (MẶC ĐỊNH, = NautilusTrader): Open -> High -> Low -> Close. "adaptive" (= `bar_adaptive_high_low_ordering`): cực gần open ghé trước.
#      Mỗi chặng là MỘT tick: mọi lệnh bị chặng đó xuyên qua khớp ngay trong tick, theo thứ tự nhóm của sàn Nautilus: (a) các tầng DCA
#      (lệnh limit nhồi, từ gần ra xa; avg và giá thanh lý tính lại ngay), (b) chốt lời (limit), (c) các lệnh stop — SL, trailing, thanh lý —
#      mức bị xuyên cao nhất trước (long). Lệnh bảo vệ SL / TP là lệnh ĐÃ NẰM TRÊN SÀN từ cuối nến trước: mức của chúng cố định cả nến,
#      đặt lại từ avg mới (sau fill DCA) chỉ có hiệu lực từ nến sau; riêng nếu TP mới đã nằm "trong giá" tại close thì nó khớp ngay ở close
#      như lệnh taker (đúng hành vi Nautilus: lệnh đặt lại thấy sổ lệnh lúc close). Stop-market khớp ở mức kích hoạt; tick mở cửa (gap) thì ở open.
#      Lệnh limit (DCA, TP) luôn khớp ở mức đặt. Trailing: đỉnh/đáy chạy theo từng chặng, mức trailing dùng ở một chặng là mức tính sau chặng trước.
#    - "adverse_first" (cũ, giữ nguyên từng bit cho kiểm bền): phía BẤT LỢI trước, theo đúng thứ tự giá chạm (long: từ trên xuống):
#      tầng DCA (lệnh limit), stop-loss, trailing stop, giá thanh lý (perp). Sau mỗi tầng DCA, giá trung bình và giá thanh lý được tính lại ngay
#      (sàn tự tính giá thanh lý). Hoà mức -> ưu tiên THOÁT (bi quan). SL CŨ (quy tắc bảo thủ, 2026-10-06): lệnh SL đang nằm trên sàn không dời
#      được ngay sau fill DCA, nên trong phần còn lại của nến mức SL dùng là mức SL lúc tầng DCA ĐẦU TIÊN của nến khớp; SL tính từ avg mới có
#      hiệu lực từ nến sau. Giá open đã vượt mức stop-market (SL/trailing/thanh lý) -> khớp ở open (gap). Lệnh LIMIT đang chờ (tầng DCA)
#      khớp đúng ở mức đặt: phần giá tốt hơn khi gap thuộc về bên khớp lệnh (sàn thật / NautilusTrader).
# 3. (chỉ "adverse_first") Phía CÓ LỢI: chốt lời (limit, từ giá TB) chỉ được xét nếu trong nến KHÔNG có tầng DCA nào
#    khớp — không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến. Chốt lời khớp đúng ở mức TP
#    (kể cả khi open đã vượt mức).
# 4. Cuối nến: cập nhật đỉnh/đáy có lợi (cho trailing), lỗ treo tối đa (MAE), rồi đặt lệnh chờ
#    cho nến sau theo tín hiệu match/stop (tính trên nến đã đóng).
#
# Chế độ thị trường:
# - spot: đòn bẩy = 1, không cho SHORT, không thanh lý.
# - perp: đòn bẩy L, ký quỹ isolated, thanh lý khi giá chạm
#   long:  avg × (1 − 1/L + mmr)      short: avg × (1 + 1/L − mmr).
#   Giá dùng là giá perp thật khi có dữ liệu <SYM>@perp (kèm funding); không có thì giá spot làm proxy.
# - stop_fill="extreme": SL/trailing khớp ở giá xấu nhất của nến chạm mức (bi quan). Mặc định "level"
#   giả định khớp đúng mức + trượt — lạc quan khi giá giật xuyên mức trong một nến.
#
# Cooldown (tuỳ chọn): sau khi đóng vị thế (kể cả force_close), tín hiệu vào lệnh trong `cooldown` phút bị bỏ qua
# — tín hiệu là TRẠNG THÁI nên nếu không chờ, flow có thể vào lại vài phút sau SL trên cùng trạng thái cũ.
#
# Khối lượng: ký quỹ tầng đầu = VỐN HIỆN TẠI (vốn ban đầu + lãi/lỗ đã chốt, do engine cập nhật)
# × order_size_pct%; tầng k = tầng k-1 × hệ số. Ngân sách một vị thế = vốn hiện tại lúc mở × max_capital_usage;
# tầng nào vượt ngân sách thì bị bỏ qua. Vốn <= 0 -> không mở lệnh mới (cháy tài khoản).
# PnL % của lệnh tính trên vốn lúc mở lệnh (để ghép lãi kép đúng trong WFA/Monte Carlo).
#
# Hai móc TUỲ CHỌN cho thị trường không có sổ lệnh (AMM / DEX, chạy bằng tick — optimize/search/evaluate.py); mặc định tắt = hành vi cũ đúng từng bit:
# - limit_taker=True: tầng DCA và chốt lời không phải lệnh limit chờ sẵn mà là swap thực hiện khi giá đi qua mức -> tính như lệnh market (phí taker + trượt giá).
# - impact_fn(notional_usd, is_buy) -> tỉ lệ trượt giá, thay slippage_rate cho MỌI lệnh khớp kiểu taker và cho chi phí khứ hồi khi tính khối lượng (_risk_margin).
# Kernel numba (core/backtest.py) chạy hai móc này riêng (P9.4b T6: PI_LTAKER / PI_AMM, KernelBook(amm=) / SlotDriver(amm=)); `pack_slots` vẫn từ chối tracker mang móc. Bản tracker
# là nguồn gốc của nhánh AMM trong kernel; oracle đóng băng của nhánh này: test/reference_engine.py::RefPositionTracker (limit_taker / impact_fn).
#

# Bộ đếm id nằm ở core/models.py (next_id); tên cũ giữ làm alias cho sim_venue / test (cùng MỘT dãy).


def _book_attr(name: str, doc: str = "") -> property:
    """Thuộc tính tracker uỷ quyền sang PositionBook (kế toán, P6.3) — kernel numba đọc/ghi qua đây nên cần setter."""
    return property(attrgetter(f"book.{name}"), lambda self, v: setattr(self.book, name, v), doc=doc)


class PositionTracker:
    """Theo dõi vòng đời vị thế của một flow: Entry -> DCA -> TP / SL / Trailing / Timeout / Liq / Exit."""

    def __init__(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        flow_name: str,
        params: StrategyParams,
        pos_type: PositionType,
        initial_capital: float = 10000.0,
        ledger: Optional[CapitalLedger] = None,
        limit_taker: bool = False,
        impact_fn: Optional[Callable[[float, bool], float]] = None,
    ):
        sp = SlotSpec(account_id, campaign_id, symbol, flow_name, params, pos_type, initial_capital,
                      entry_equity=ledger.equity if ledger is not None else None)   # chuẩn hoá + kiểm tham số: một bản duy nhất (params.SlotSpec)
        self.spec = sp
        self.account_id, self.campaign_id, self.symbol, self.flow_name = account_id, campaign_id, symbol, flow_name
        self.params, self.pos_type, self.is_long = params, pos_type, sp.is_long
        self.market, self.leverage, self.mmr = sp.market, sp.leverage, sp.mmr
        self.fee_rate, self.maker_fee_rate, self.slippage_rate = sp.fee_rate, sp.maker_fee_rate, sp.slippage_rate
        self.limit_taker = bool(limit_taker)    # AMM: DCA / chốt lời khớp như lệnh taker (phí taker + trượt giá)
        self.impact_fn = impact_fn              # (notional_usd, is_buy) -> trượt giá; None = slippage_rate cố định
        self.capital, self.capital_usage = sp.capital, sp.capital_usage
        account = ledger if ledger is not None else Account(self.capital, self.capital_usage)
        self.book = PositionBook(account, account_id, campaign_id, symbol, flow_name, pos_type)  # kế toán vị thế (P6.3)
        self.max_capital = sp.max_capital

        self.base_sl, self.base_tp, self.base_trail, self.base_trail_act = sp.base_sl, sp.base_tp, sp.base_trail, sp.base_trail_act
        self.timeout_ms, self.cooldown_ms = sp.timeout_ms, sp.cooldown_ms
        self.last_close_time: Optional[int] = None   # thời điểm đóng vị thế gần nhất (cho cooldown)
        self.dca_rejected = 0       # số tầng DCA bị từ chối vì hết ngân sách vốn (không đổi logic khớp lệnh)
        self.stop_fill, self.limit_through, self.intrabar_path = sp.stop_fill, sp.limit_through, sp.intrabar_path
        self.exit_unit, self.atr_frame, self.atr_period = sp.exit_unit, sp.atr_frame, sp.atr_period
        self.sizing, self.risk_pct, self.max_notional_pct = sp.sizing, sp.risk_pct, sp.max_notional_pct
        self.base_dca_steps, self.dca_mults = sp.base_dca_steps, sp.dca_mults
        self.max_leverage, self.pos_leverage = sp.max_leverage, sp.pos_leverage
        self.planned_risk = 0.0
        self.max_new_notional = float("inf")  # trần danh nghĩa cho lệnh sắp mở (do danh mục đặt theo max_gross_exposure)
        self.max_new_risk = float("inf")      # trần rủi ro (tới SL, cả rổ DCA) cho lệnh sắp mở (danh mục: max_open_risk_pct)
        self.risk_scale = 1.0                 # hệ số rủi ro do danh mục đặt (giảm theo mức sụt vốn: dd_throttle_pct)
        self.unit_pct = 0.0
        self.pending_vol = float("nan")
        self.skipped_no_vol = 0     # tín hiệu vào lệnh nhưng chưa có ATR (giai đoạn khởi động)
        self._apply_exit_unit(1.0)
        self.order_size_pct = sp.order_size_pct
        self.max_open_trades = sp.max_open_trades
        self.match_tree, self.stop_tree, self.dca_tree, self.dca_ok = sp.match_tree, sp.stop_tree, sp.dca_tree, True

        self.is_open = False
        self.pending_entry = False
        self.pending_exit = False
        self._reset_state()

    def _apply_exit_unit(self, unit: float) -> None:
        """Quy đổi tham số thoát lệnh sang % cho vị thế sắp mở (unit = 1 với exit_unit='pct', = ATR% với 'atr').
        Đặt lại từ giá trị gốc mỗi vị thế: các tầng DCA bị bỏ vì hết vốn ở vị thế trước không ảnh hưởng vị thế sau."""
        (self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct,
         self.dca_steps) = policy.exit_params_scaled(unit, self.base_sl, self.base_tp, self.base_trail,
                                                     self.base_trail_act, self.base_dca_steps)

    # ─── Trạng thái ─────────────────────────────────────────────────────────
    # Kế toán nằm ở PositionBook (account.py); các thuộc tính dưới đây là cửa sổ vào book (tracker/kernel đọc ghi như cũ).
    qty = _book_attr("qty")
    avg = _book_attr("avg")
    margin_used = _book_attr("margin_used")
    fees_paid = _book_attr("fees_paid")
    layer_count = _book_attr("layer_count")
    last_fill = _book_attr("last_fill")
    entry_time = _book_attr("entry_time")
    reserved_here = _book_attr("reserved_here", "tiền đã giữ chỗ trong sổ vốn cho vị thế này")
    funding_paid = _book_attr("funding_paid", "funding đã trả (+) / nhận (−), đã hạch toán thẳng vào sổ vốn")
    entry_equity = _book_attr("entry_equity")
    position = _book_attr("position")
    orders = _book_attr("orders")

    @property
    def ledger(self) -> Account:
        return self.book.account

    @ledger.setter
    def ledger(self, account: Account) -> None:
        self.book.account = account

    def _reset_state(self) -> None:
        self.book.reset()          # qty, avg, ký quỹ, phí, tầng, giữ chỗ, funding, entry_equity = vốn hiện tại
        self.next_margin = 0.0
        self.peak = 0.0
        self.mae_usd = 0.0

    @property
    def equity(self) -> float:
        """Vốn đã chốt hiện tại (dùng chung giữa các flow qua CapitalLedger)."""
        return self.ledger.equity

    @property
    def avg_entry_price(self) -> float:
        return self.avg

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.is_open or self.qty <= 0:
            return 0.0
        return self.book.unrealized_pnl(price)  # funding đã nằm trong ledger.equity

    def apply_funding(self, rate: float, price: float, t: int = 0) -> float:
        """Funding perp: long trả qty·giá·rate khi rate > 0 (short nhận), và ngược lại. Hạch toán ngay."""
        if not self.is_open or self.market != "perp" or self.qty <= 0:
            return 0.0
        payment = policy.funding_payment(self.qty, price, rate, self.is_long)
        return self.book.apply_funding(FundingApplied(self.book.slot, t, rate, price, payment))

    def _liq_price(self) -> Optional[float]:
        if self.market != "perp" or self.qty <= 0:
            return None
        return policy.liq_price(self.avg, self.pos_leverage, self.mmr, self.is_long)

    def _reached(self, level: float, extreme: float) -> bool:
        return policy.reached(level, extreme, self.is_long)

    def _gap_fill(self, level: float, open_price: float) -> float:
        """Giá khớp khi chạm mức: nếu open đã vượt qua mức (gap) thì khớp ở open."""
        return policy.gap_fill(level, open_price, self.is_long)

    def _slip(self, notional: float, is_buy: bool) -> float:
        """Tỉ lệ trượt giá của một lệnh taker: impact_fn theo khối lượng (AMM) hoặc slippage_rate cố định."""
        return policy.slip_rate(self.slippage_rate, self.impact_fn, notional, is_buy)

    def _cost(self, notional: float) -> float:
        """Chi phí KHỨ HỒI (phí taker + trượt giá) tính trên danh nghĩa `notional` — dùng chia rủi ro / khối lượng."""
        return policy.round_trip_cost(self.fee_rate, self.slippage_rate, self.impact_fn, notional)

    # ─── Hành động ──────────────────────────────────────────────────────────
    def _add_layer(self, t: int, price: float, margin: float, market_order: bool, reason: str) -> bool:
        notional = margin * self.pos_leverage
        taker = market_order or self.limit_taker
        slip = self._slip(notional, self.is_long) if taker else 0.0
        fill = policy.entry_fill_price(price, slip, self.is_long) if taker else price
        fee = policy.entry_fee(notional, self.fee_rate if taker else self.maker_fee_rate)
        first = self.book.position is None
        kind = "entry" if first else "dca"
        if margin <= 0 or fill <= 0 or not self.book.can_add(margin, fee, self.max_capital):
            self.book.reject("budget", kind)       # vượt ngân sách vị thế: không đổi sổ vốn
            return False
        if not self.ledger.can_reserve(margin + fee):
            self.book.reject("capital", kind)      # không giữ chỗ được từ vốn trống: ledger.rejected += 1
            return False
        self.book.apply_fill(Fill(
            slot=self.book.slot, order_id=next_id(), kind=kind, t=t, price=fill, raw_price=price, notional=notional,
            margin=margin, fee=fee, slip=slip, liquidity="taker" if taker else "maker", reason=reason,
            unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
        if first:
            self.peak = fill
        self.is_open = True
        return True

    def _open(self, t: int, open_price: float) -> None:
        if self.equity <= 0:
            return  # cháy tài khoản: không mở lệnh mới
        unit = 1.0
        if self.exit_unit == "atr":
            unit = self.pending_vol
            if not (unit > 0):  # NaN khi chưa đủ nến khởi động ATR
                self.skipped_no_vol += 1
                return
        self._apply_exit_unit(unit)
        self.unit_pct = unit if self.exit_unit == "atr" else 0.0
        self.entry_equity = self.equity
        self.max_capital = self.equity * self.capital_usage
        budget = min(self.max_capital, self.ledger.free())
        self.pos_leverage = self.max_leverage
        self.planned_risk = 0.0
        if self.sizing == "risk":
            margin = self._risk_margin()
        else:
            margin = policy.flat_margin(self.equity, self.order_size_pct)
        if self.risk_scale != 1.0:                            # danh mục đang sụt vốn: thu nhỏ lệnh mới
            margin = margin * self.risk_scale
            self.planned_risk = self.planned_risk * self.risk_scale
        margin = policy.clamp_margin(margin, budget, self.pos_leverage, self.fee_rate, self.max_new_notional)
        if self.sizing == "risk" and margin > 0:
            total_mult = self._layer_mult_total()
            self.planned_risk = min(self.planned_risk, policy.planned_risk_cap(
                margin, self.pos_leverage, self.sl_pct,
                self._cost(margin * self.pos_leverage * total_mult), total_mult))
        # vượt trần rủi ro đang mở của danh mục
        margin, self.planned_risk = policy.apply_risk_ceiling(margin, self.planned_risk, self.max_new_risk)
        if margin <= 0:
            self.book.reject("no_margin", "entry")  # tín hiệu vào lệnh nhưng không còn vốn trống: ledger.rejected += 1
            return
        if self._add_layer(t, open_price, margin, market_order=True, reason="Tín hiệu vào lệnh (AST match)"):
            self.next_margin = margin

    def _layer_mult_total(self) -> float:
        """Tổng khối lượng các tầng (lệnh đầu = 1) theo hệ số DCA."""
        return policy.layer_mult_total(self.dca_mults, len(self.dca_steps))

    def _risk_margin(self) -> float:
        """Khối lượng theo rủi ro: nếu chạm SL (tính cả mọi tầng DCA dự kiến và phí khứ hồi taker + trượt)
        thì mất ~risk_per_trade_pct% vốn. Danh nghĩa bị chặn bởi max_notional_pct% vốn.
        Perp: đòn bẩy thực = min(đòn bẩy tham số, mức để giá thanh lý cách giá vào >= 1,5 × khoảng SL)."""
        margin, self.pos_leverage, self.planned_risk = policy.risk_margin(
            self.equity, self.risk_pct, self.max_notional_pct, self.sl_pct, self.fee_rate, self.slippage_rate,
            self.impact_fn, self.market == "perp", self.max_leverage, self.mmr, self.pos_leverage,
            self._layer_mult_total())
        return margin

    def _close(self, t: int, raw_price: float, status: PositionStatus, reason: str, market_order: bool,
               kind: str = "exit") -> PositionModel:
        taker = market_order or self.limit_taker
        slip = 0.0
        if taker and status != PositionStatus.LIQ:
            slip = self._slip(self.qty * raw_price, not self.is_long)
            price = policy.exit_fill_price(raw_price, slip, self.is_long)
        else:
            price = raw_price
        exit_fee = policy.exit_fee(self.qty, price, self.fee_rate if taker or status == PositionStatus.LIQ else self.maker_fee_rate)
        pos = self.book.apply_close(Fill(
            slot=self.book.slot, order_id=next_id(), kind=kind, t=t, price=price, raw_price=raw_price, notional=0.0,
            margin=0.0, fee=exit_fee, slip=slip,
            liquidity="liquidation" if status == PositionStatus.LIQ else ("taker" if taker else "maker"),
            reason=reason, status=int(status), mae_usd=self.mae_usd))
        self.is_open = False
        self.pending_exit = False
        self.last_close_time = t
        self._reset_state()
        return pos

    def _status_by_pnl(self, price: float) -> PositionStatus:
        return PositionStatus.TP if policy.in_profit(price, self.avg, self.is_long) else PositionStatus.SL

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Xử lý một nến 1m có giao dịch = `on_bar_open` + `on_bar_rest` liền nhau (đường đơn tài sản). Trả vị thế vừa đóng (nếu có).
        vol = ATR% (natr) của khung atr_frame đã đóng tại cuối nến này — dùng khi lệnh vào chờ được đặt ở nến này.
        dca_gate = điều kiện DCA tại cuối nến này (True khi chiến lược không có điều kiện) — quyết định nến SAU có được dồn tầng không."""
        closed = self.on_bar_open(t, o, h, l, c, can_open)
        return self.on_bar_rest(t, o, h, l, c, entry_signal, stop_signal, closed, vol, dca_gate)

    def on_bar_open(self, t: int, o: float, h: float, l: float, c: float, can_open: bool = True) -> Optional[PositionModel]:
        """Pha MỞ nến (chỉ thấy giá open): thoát chờ / hết thời gian giữ ở open, rồi vào lệnh chờ ở open (nếu `can_open`). Trả vị thế vừa đóng ở
        open (None nếu không) — truyền lại cho `on_bar_rest`. Danh mục gọi pha này cho MỌI tài sản (xét hạn mức dựa trên trạng thái lúc mở nến)
        TRƯỚC khi bất kỳ tài sản nào chạy pha trong nến."""
        closed: Optional[PositionModel] = None
        # 1. Đầu nến
        if self.is_open:
            if self.pending_exit:
                closed = self._close(t, o, self._status_by_pnl(o), "Tín hiệu thoát (AST stop)", market_order=True, kind="exit")
            elif self.timeout_ms and t - self.entry_time >= self.timeout_ms:
                closed = self._close(t, o, self._status_by_pnl(o), "Hết thời gian giữ lệnh", market_order=True, kind="timeout")
        if closed is None and not self.is_open and self.pending_entry:
            self.pending_entry = False
            if can_open:
                self._open(t, o)
        return closed

    def on_bar_rest(self, t: int, o: float, h: float, l: float, c: float, entry_signal: bool, stop_signal: bool,
                    closed: Optional[PositionModel] = None, vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Pha TRONG nến + cuối nến: SL / TP / DCA / trailing / thanh lý theo đường giá, rồi sổ sách cuối nến (đỉnh, MAE, cờ vào / thoát chờ).
        `closed` = kết quả của `on_bar_open` cùng nến (đã đóng ở open thì bỏ qua pha trong nến, và nến đó không đặt lệnh vào chờ)."""
        # 2-3. Trong nến
        if self.is_open and closed is None:
            self.book.mark(h, l)
            closed = self._intrabar(t, o, h, l, c)

        # 4. Cuối nến
        if self.is_open:
            adverse = l if self.is_long else h
            self.mae_usd = min(self.mae_usd, self.unrealized_pnl_usd(adverse))
            self.peak = max(self.peak, h) if self.is_long else min(self.peak, l)
            if stop_signal:
                self.pending_exit = True
        elif closed is None and entry_signal and (
                not self.cooldown_ms or self.last_close_time is None or t - self.last_close_time >= self.cooldown_ms):
            self.pending_entry = True
            self.pending_vol = vol
        self.dca_ok = bool(dca_gate)
        return closed

    def _intrabar(self, t: int, o: float, h: float, l: float, c: float) -> Optional[PositionModel]:
        if self.intrabar_path == "adverse_first":
            return self._intrabar_adverse_first(t, o, h, l)
        return self._intrabar_path(t, o, h, l, c)

    def _intrabar_path(self, t: int, o: float, h: float, l: float, c: float) -> Optional[PositionModel]:
        """Đường ohlc / adaptive (xem docstring module): mỗi chặng là một tick; SL / TP cố định cả nến."""
        is_long = self.is_long
        sign = 1.0 if is_long else -1.0
        adverse = l if is_long else h
        sl_lv = policy.sl_level(self.avg, self.sl_pct, sign) if self.sl_pct else None     # lệnh bảo vệ đã nằm trên sàn từ cuối nến trước
        tp_lv = tp_need = 0.0
        if self.tp_pct:
            tp_lv = policy.tp_level(self.avg, self.tp_pct, sign)
            tp_need = policy.tp_need(tp_lv, self.limit_through, sign)
        peak = self.peak                    # đỉnh/đáy có lợi chạy dọc đường giá (cho trailing)
        dca_filled = False
        prev = o
        for i, p in enumerate(policy.bar_points(self.intrabar_path, o, h, l, c)):
            if i and p == prev:
                continue                    # chặng không đổi giá: không có tick (Nautilus bỏ qua)
            at_open = i == 0
            # (a) nhóm DCA: mọi tầng bị tick xuyên qua, tầng kế tính từ giá khớp gần nhất
            while True:
                k = self.layer_count - 1
                if not (k < len(self.dca_steps) and self.dca_ok):
                    break
                dca_level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
                if not policy.reached(policy.dca_trigger(dca_level, self.limit_through, sign), p, is_long):
                    break
                price = self._gap_fill(dca_level, o) if self.limit_taker else dca_level   # limit khớp ở mức; AMM (swap) khớp ở open
                margin = self.next_margin * self.dca_mults[k]
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    dca_filled = True
                    continue
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: k]  # hết vốn: không nhồi thêm tầng nào nữa
            # (b) chốt lời (limit chờ sẵn từ avg đầu nến)
            if self.tp_pct and policy.tp_hit(p, tp_need, is_long):
                price = policy.tp_fill_price(tp_lv, o, is_long) if self.limit_taker else tp_lv
                return self._close(t, price, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=False, kind="tp")
            # (c) nhóm stop: SL (mức cố định), trailing (từ đỉnh sau chặng trước), thanh lý (tính từ avg hiện tại)
            events: List[Tuple[float, int, str]] = []
            if sl_lv is not None:
                events.append((sl_lv, 0, "sl"))
            if self.trail_pct and policy.trail_active(peak, self.avg, self.trail_activation_pct, sign):
                events.append((policy.trail_level(peak, self.trail_pct, sign), 0, "trail"))
            liq = self._liq_price()
            if liq is not None and liq > 0:
                events.append((liq, 0, "liq"))
            reached = [e for e in events if policy.reached(e[0], p, is_long)]
            if reached:
                level, _, kind = policy.pick_first_touched(reached, is_long)
                price = policy.tick_stop_price(level, o, is_long, at_open)
                if kind == "liq":
                    return self._close(t, price, PositionStatus.LIQ, "Thanh lý (perp)", market_order=False, kind="liq")
                if self.stop_fill == "extreme":
                    price = policy.stop_extreme_fill(price, adverse, is_long)
                if kind == "sl":
                    return self._close(t, price, PositionStatus.SL, "Stop-loss (từ giá TB)", market_order=True, kind="sl")
                return self._close(t, price, self._status_by_pnl(price), "Trailing stop", market_order=True, kind="trail")
            peak = policy.peak_step(peak, p, is_long)
            prev = p
        # Cuối nến: SL / TP đặt lại từ avg mới (sau fill DCA) thấy sổ lệnh ở close; TP mới đã "trong giá" -> khớp ngay ở close (taker)
        if dca_filled and self.tp_pct:
            tp_new = policy.tp_level(self.avg, self.tp_pct, sign)
            if policy.tp_hit(c, tp_new, is_long):
                return self._close(t, c, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=True, kind="tp")
        return None

    def _intrabar_adverse_first(self, t: int, o: float, h: float, l: float) -> Optional[PositionModel]:
        adverse = l if self.is_long else h
        favorable = h if self.is_long else l
        sign = 1.0 if self.is_long else -1.0
        dca_filled = False
        sl_stale: Optional[float] = None    # mức SL CŨ còn hiệu lực sau tầng DCA đầu tiên của nến (sl_pct > 0)

        while True:
            events: List[Tuple[float, int, str]] = []  # (mức, ưu tiên khi hoà: thoát trước, loại)
            k = self.layer_count - 1
            dca_level = None
            if k < len(self.dca_steps) and self.dca_ok:
                dca_level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
                trigger = policy.dca_trigger(dca_level, self.limit_through, sign)
                events.append((trigger, 1, "dca"))
            if self.sl_pct:
                events.append((sl_stale if sl_stale is not None else policy.sl_level(self.avg, self.sl_pct, sign), 0, "sl"))
            if self.trail_pct:
                if policy.trail_active(self.peak, self.avg, self.trail_activation_pct, sign):
                    events.append((policy.trail_level(self.peak, self.trail_pct, sign), 0, "trail"))
            liq = self._liq_price()
            if liq is not None and liq > 0:
                events.append((liq, 0, "liq"))
            reached = [e for e in events if self._reached(e[0], adverse)]
            if not reached:
                break
            # long: mức cao nhất bị chạm trước khi giá rơi xuống; short: mức thấp nhất
            level, _, kind = policy.pick_first_touched(reached, self.is_long)
            price = self._gap_fill(level, o)
            if kind == "dca":
                # lệnh limit chờ sẵn khớp đúng ở giá đặt kể cả khi gap qua mức; AMM (limit_taker) là swap -> khớp ở open
                price = self._gap_fill(dca_level, o) if self.limit_taker else dca_level
                margin = self.next_margin * self.dca_mults[k]
                sl_before = policy.sl_level(self.avg, self.sl_pct, sign) if self.sl_pct else None   # SL đang nằm trên sàn trước fill
                if self._add_layer(t, price, margin, market_order=False, reason="DCA"):
                    self.next_margin = margin
                    if not dca_filled:
                        sl_stale = sl_before            # SL cũ chưa dời kịp trong phần còn lại của nến
                    dca_filled = True
                    continue
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: k]  # hết vốn: không nhồi thêm tầng nào nữa
                continue
            if kind == "liq":
                return self._close(t, price, PositionStatus.LIQ, "Thanh lý (perp)", market_order=False, kind="liq")
            if self.stop_fill == "extreme":
                # Bi quan: lệnh stop-market khớp ở giá xấu nhất của nến (cú giật xuyên mức trong nến).
                price = policy.stop_extreme_fill(price, adverse, self.is_long)
            if kind == "sl":
                return self._close(t, price, PositionStatus.SL, "Stop-loss (từ giá TB)", market_order=True, kind="sl")
            return self._close(t, price, self._status_by_pnl(price), "Trailing stop", market_order=True, kind="trail")

        if self.tp_pct and not dca_filled:
            tp_level = policy.tp_level(self.avg, self.tp_pct, sign)
            need = policy.tp_need(tp_level, self.limit_through, sign)
            if policy.tp_hit(favorable, need, self.is_long):
                price = policy.tp_fill_price(tp_level, o, self.is_long) if self.limit_taker else tp_level   # limit khớp ở mức TP
                return self._close(t, price, PositionStatus.TP, "Take-profit (từ giá TB)", market_order=False, kind="tp")
        return None

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        if not self.is_open:
            return None
        self.pending_entry = False
        return self._close(t, raw_price, PositionStatus.CANCEL, reason, market_order=True,
                           kind="kill" if reason.startswith("Kill") else "end")

    _combine_conditions = staticmethod(SlotSpec._combine_conditions)

# ── legacy: core/execute/manager.py ──
#
# PositionManager (P6.4) — policy một slot theo SỰ KIỆN: thay `PositionTracker.on_bar` cho paper / demo / live.
#
# Vai trò (docs/bmad/p6_execution_design.md §1, §4): giữ trạng thái CHIẾN LƯỢC của slot (lệnh vào/thoát chờ, cooldown, timeout, đỉnh, MAE,
# cổng DCA, ký quỹ tầng kế, tham số thoát đã quy đổi, trần rủi ro do danh mục đặt) và RA LỆNH cho Venue; Fill / OrderRejected do venue trả về
# được áp vào Account + PositionBook (account.py — nơi duy nhất đổi vốn và vị thế). Công thức mức giá / khối lượng chỉ ở policy.py.
#
# Một nến (`on_bar`, cùng chữ ký tracker):
#   begin : lệnh thoát chờ / hết thời gian -> EXIT market; lệnh vào chờ -> sizing (policy + trần danh mục) -> ENTRY market.
#   adverse: đặt SL / TRAIL / DCA / TP từ giá TB; kéo sự kiện của venue (hoà thì thoát trước) — DCA khớp: áp, tính lại lệnh chờ từ avg mới;
#            DCA bị từ chối (ngân sách / vốn): cắt các tầng còn lại, dca_rejected += 1; SL / TRAIL / thanh lý: áp, đóng, kết thúc nến.
#   favorable: TP (venue bỏ qua nếu nến có DCA khớp). end: đỉnh, MAE, cờ pending, cổng DCA, cooldown.
#
# Bot sàn (P6.8b): venue không khớp theo nến mà báo sự kiện qua poll -> `sync_events()` kéo và áp ngay (DCA khớp: đặt lại SL/TP/... từ avg mới;
# SL/TP/trailing khớp: đóng). `sticky_orders=True` (bot sàn) giữ nguyên lệnh đang nằm trên sàn khi tập lệnh mong muốn không đổi (không huỷ/đặt lại mỗi nến —
# lệnh bảo vệ luôn nằm sẵn, ADR D2; trailing gốc không bị đặt lại làm mất đỉnh). Venue có trailing gốc (caps.native_trailing) nhận TRAIL ngay từ lúc vào
# lệnh (sàn tự kích hoạt tại `activation`); sim chỉ đặt TRAIL khi đã kích hoạt theo đỉnh các nến trước.
#
# Dựng từ một PositionTracker đã chuẩn hoá tham số (tracker còn là bộ chuẩn hoá tham số tới P6.9; manager chỉ sao chép trường, không dùng
# sổ/book của tracker). `id` của OrderModel / PositionModel lấy từ `tracker._next_id()` lúc khớp (venue cấp) nên trùng thứ tự gọi của tracker.
#

_EXIT_REASON = "Tín hiệu thoát (AST stop)"
_TIMEOUT_REASON = "Hết thời gian giữ lệnh"
_SL_REASON = "Stop-loss (từ giá TB)"
_TRAIL_REASON = "Trailing stop"
_TP_REASON = "Take-profit (từ giá TB)"
_EXCHANGE_CLOSE_REASON = "Sàn đã đóng vị thế"


class PositionManager:
    """Policy vị thế một slot, điều khiển một Venue (SimVenue ở P6.4; OkxVenue ở P6.7)."""

    def __init__(self, tracker: PositionTracker, venue: Venue, slot: int = 0, account: Optional[Account] = None,
                 events: Optional[List] = None):
        if tracker.limit_taker or tracker.impact_fn is not None:
            raise NotImplementedError("PositionManager chưa hỗ trợ limit_taker / impact_fn (AMM/DEX nằm ngoài P6)")
        tr = tracker
        self.venue = venue
        self.slot = slot
        # ── tham số đã chuẩn hoá (sao chép từ tracker) ──
        self.account_id, self.campaign_id, self.symbol, self.flow_name = tr.account_id, tr.campaign_id, tr.symbol, tr.flow_name
        self.pos_type, self.is_long, self.market = tr.pos_type, tr.is_long, tr.market
        self.mmr = tr.mmr
        self.fee_rate, self.maker_fee_rate, self.slippage_rate = tr.fee_rate, tr.maker_fee_rate, tr.slippage_rate
        self.capital_usage = tr.capital_usage
        self.base_sl, self.base_tp, self.base_trail, self.base_trail_act = tr.base_sl, tr.base_tp, tr.base_trail, tr.base_trail_act
        self.timeout_ms, self.cooldown_ms = tr.timeout_ms, tr.cooldown_ms
        self.stop_fill, self.limit_through = tr.stop_fill, tr.limit_through
        self.intrabar_path = tr.intrabar_path
        self.exit_unit, self.sizing = tr.exit_unit, tr.sizing
        self.risk_pct, self.max_notional_pct = tr.risk_pct, tr.max_notional_pct
        self.base_dca_steps, self.dca_mults = list(tr.base_dca_steps), list(tr.dca_mults)
        self.max_leverage, self.order_size_pct = tr.max_leverage, tr.order_size_pct
        # ── sổ ──
        acct = account if account is not None else tr.ledger
        self.book = PositionBook(acct, self.account_id, self.campaign_id, self.symbol, self.flow_name, self.pos_type,
                                 slot=slot, events=events)
        self.max_capital = tr.max_capital
        # ── trạng thái chiến lược ──
        self.last_close_time: Optional[int] = None
        self.dca_rejected = 0
        self.pos_leverage = tr.pos_leverage
        self.planned_risk = 0.0
        self.max_new_notional = float("inf")   # trần do danh mục đặt từ risk.Admission trước mỗi on_bar
        self.max_new_risk = float("inf")
        self.risk_scale = 1.0
        self.unit_pct = 0.0
        self.pending_vol = float("nan")
        self.skipped_no_vol = 0
        self._apply_exit_unit(1.0)
        self.dca_ok = True
        self.is_open = False
        self.pending_entry = False
        self.pending_exit = False
        self._reset_state()
        add_slot = getattr(venue, "add_slot", None)
        if add_slot is not None:    # SimVenue cần chi phí khớp và cổng kiểm tra trước giao dịch của slot
            add_slot(slot, fee_rate=self.fee_rate, maker_fee_rate=self.maker_fee_rate, slippage_rate=self.slippage_rate,
                     stop_fill=self.stop_fill, gate=self._gate, intrabar_path=self.intrabar_path)

    def __setstate__(self, state: dict) -> None:
        """Pickle cũ (unified.pkl / paper.pkl trước commit 169ddd0) chưa có intrabar_path."""
        self.__dict__.update(state)
        self.__dict__.setdefault("intrabar_path", "ohlc")

    # ─── Trạng thái (cửa sổ vào book; cũng là PositionView của SimVenue) ────────
    qty = _book_attr("qty")
    avg = _book_attr("avg")
    margin_used = _book_attr("margin_used")
    fees_paid = _book_attr("fees_paid")
    layer_count = _book_attr("layer_count")
    last_fill = _book_attr("last_fill")
    entry_time = _book_attr("entry_time")
    reserved_here = _book_attr("reserved_here")
    funding_paid = _book_attr("funding_paid")
    entry_equity = _book_attr("entry_equity")
    position = _book_attr("position")
    orders = _book_attr("orders")

    @property
    def ledger(self) -> Account:
        return self.book.account

    @ledger.setter
    def ledger(self, account: Account) -> None:
        self.book.account = account

    @property
    def equity(self) -> float:
        return self.ledger.equity

    @property
    def avg_entry_price(self) -> float:
        return self.avg

    def _apply_exit_unit(self, unit: float) -> None:
        (self.sl_pct, self.tp_pct, self.trail_pct, self.trail_activation_pct,
         self.dca_steps) = policy.exit_params_scaled(unit, self.base_sl, self.base_tp, self.base_trail,
                                                     self.base_trail_act, self.base_dca_steps)

    def _reset_state(self) -> None:
        self.book.reset()
        self.next_margin = 0.0
        self.peak = 0.0
        self.mae_usd = 0.0

    def unrealized_pnl_usd(self, price: float) -> float:
        if not self.is_open or self.qty <= 0:
            return 0.0
        return self.book.unrealized_pnl(price)

    def apply_funding(self, rate: float, price: float, t: int = 0) -> float:
        if not self.is_open or self.market != "perp" or self.qty <= 0:
            return 0.0
        payment = policy.funding_payment(self.qty, price, rate, self.is_long)
        return self.book.apply_funding(FundingApplied(self.book.slot, t, rate, price, payment))

    # ─── Cổng kiểm tra trước giao dịch (venue gọi trước khi chấp nhận lệnh vào / DCA) ──
    def _gate(self, kind: str, margin: float, fee: float, price: float) -> Optional[str]:
        if margin <= 0 or price <= 0 or not self.book.can_add(margin, fee, self.max_capital):
            return "budget"        # vượt ngân sách vị thế: không đổi sổ vốn
        if not self.ledger.can_reserve(margin + fee):
            return "capital"       # không giữ chỗ được từ vốn trống: ledger.rejected += 1
        return None

    # ─── Đặt lệnh ───────────────────────────────────────────────────────────
    def _submit(self, kind: OrderKind, is_buy: bool, **kw) -> None:
        self.venue.submit(Order(new_order_id(), self.slot, kind, is_buy, **kw))

    # Bot sàn bật: giữ lệnh đang nằm trên sàn nếu tập lệnh mong muốn không đổi (xem docstring module). Mặc định tắt (sim: đặt lại mỗi nến như cũ).
    sticky_orders = False
    _placed_qty = -1.0

    @staticmethod
    def _nn(x: float) -> Optional[float]:
        return None if x != x else x

    def _order_key(self, o: Order, native: bool) -> tuple:
        n = self._nn
        if o.kind == OrderKind.TRAIL and native:       # trailing gốc: sàn tự bám đỉnh -> chỉ kích hoạt / callback quyết định lệnh có đổi không
            return (int(o.kind), n(o.activation), n(o.callback_pct))
        return (int(o.kind), n(o.level), n(o.trigger), o.notional, o.margin)

    def _desired_orders(self) -> List[Order]:
        """Tập lệnh chờ mong muốn từ avg, last_fill và peak hiện tại (DCA kế tiếp, SL, TRAIL, TP)."""
        sign = 1.0 if self.is_long else -1.0
        k = self.layer_count - 1
        caps = getattr(self.venue, "caps", None)
        native = bool(caps is not None and caps.native_trailing)
        out: List[Order] = []

        def add(kind: OrderKind, is_buy: bool, **kw) -> None:
            out.append(Order(new_order_id(), self.slot, kind, is_buy, **kw))
        if k < len(self.dca_steps) and self.dca_ok:
            level = policy.dca_level(self.last_fill, self.dca_steps[k], sign)
            margin = self.next_margin * self.dca_mults[k]
            add(OrderKind.DCA, self.is_long, level=level, trigger=policy.dca_trigger(level, self.limit_through, sign),
                notional=margin * self.pos_leverage, margin=margin, reason="DCA", post_only=True)
        if self.sl_pct:
            add(OrderKind.SL, not self.is_long, level=policy.sl_level(self.avg, self.sl_pct, sign), reason=_SL_REASON, reduce_only=True)
        path_mode = self.intrabar_path != "adverse_first"
        if self.trail_pct and (native or path_mode or policy.trail_active(self.peak, self.avg, self.trail_activation_pct, sign)):
            # level = mức stop tĩnh từ đỉnh các nến trước (SimVenue đường cũ); activation / callback_pct cho trailing gốc của sàn (OkxVenue);
            # peak / activation_pct: SimVenue đường ohlc/adaptive tự chạy đỉnh theo từng chặng và tự kiểm kích hoạt
            add(OrderKind.TRAIL, not self.is_long, level=policy.trail_level(self.peak, self.trail_pct, sign),
                activation=policy.tp_level(self.avg, self.trail_activation_pct, sign), callback_pct=self.trail_pct,
                reason=_TRAIL_REASON, reduce_only=True, peak=self.peak, activation_pct=self.trail_activation_pct)
        if self.tp_pct:
            level = policy.tp_level(self.avg, self.tp_pct, sign)
            add(OrderKind.TP, not self.is_long, level=level, trigger=policy.tp_need(level, self.limit_through, sign),
                reason=_TP_REASON, reduce_only=True, post_only=True)
        return out

    def _place_orders(self) -> None:
        """Đặt lại DCA kế tiếp / SL / TRAIL / TP từ avg, last_fill và peak hiện tại (gọi sau mỗi fill)."""
        want = self._desired_orders()
        if self.sticky_orders and self._placed_qty == self.qty:
            caps = getattr(self.venue, "caps", None)
            native = bool(caps is not None and caps.native_trailing)
            if Counter(self._order_key(o, native) for o in want) == Counter(self._order_key(o, native) for o in self.venue.open_orders(self.slot)):
                return
        self.venue.cancel_slot(self.slot)
        for o in want:
            self.venue.submit(o)
        self._placed_qty = self.qty

    # ─── Hành động ──────────────────────────────────────────────────────────
    def _status_by_pnl(self, price: float) -> PositionStatus:
        return PositionStatus.TP if policy.in_profit(price, self.avg, self.is_long) else PositionStatus.SL

    def _enrich(self, fill: Fill, **kw) -> Fill:
        """Thông tin do policy quyết định (venue không biết): tracker ghi cùng các trường này vào Fill."""
        return dataclasses.replace(fill, **kw)

    def _apply_close(self, fill: Fill) -> PositionModel:
        pos = self.book.apply_close(fill)
        self.venue.cancel_slot(self.slot)
        self.is_open = False
        self.pending_exit = False
        self.last_close_time = fill.t
        self._reset_state()
        return pos

    def _close_market(self, status: PositionStatus, reason: str, kind: str) -> PositionModel:
        self._submit(OrderKind.EXIT, not self.is_long, reason=reason)
        ev = self.venue.next_event(self.slot)
        return self._apply_close(self._enrich(ev, kind=kind, status=int(status), mae_usd=self.mae_usd))

    def _enter(self, margin: float, reason: str) -> bool:
        """Lệnh vào tầng đầu (market ở open). False nếu bị từ chối (ngân sách / vốn)."""
        self._submit(OrderKind.ENTRY, self.is_long, notional=margin * self.pos_leverage, margin=margin, reason=reason)
        ev = self.venue.next_event(self.slot)
        if isinstance(ev, OrderRejected):
            self.book.reject(ev.reason, "entry", ev.order_id)
            return False
        self.book.apply_fill(self._enrich(ev, unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
        self.peak = ev.price
        self.is_open = True
        return True

    def _open(self, t: int, open_price: float) -> None:
        if self.equity <= 0:
            return  # cháy tài khoản: không mở lệnh mới
        unit = 1.0
        if self.exit_unit == "atr":
            unit = self.pending_vol
            if not (unit > 0):  # NaN khi chưa đủ nến khởi động ATR
                self.skipped_no_vol += 1
                return
        self._apply_exit_unit(unit)
        self.unit_pct = unit if self.exit_unit == "atr" else 0.0
        self.entry_equity = self.equity
        self.max_capital = self.equity * self.capital_usage
        budget = min(self.max_capital, self.ledger.free())
        self.pos_leverage = self.max_leverage
        self.planned_risk = 0.0
        if self.sizing == "risk":
            margin = self._risk_margin()
        else:
            margin = policy.flat_margin(self.equity, self.order_size_pct)
        if self.risk_scale != 1.0:                            # danh mục đang sụt vốn: thu nhỏ lệnh mới
            margin = margin * self.risk_scale
            self.planned_risk = self.planned_risk * self.risk_scale
        margin = policy.clamp_margin(margin, budget, self.pos_leverage, self.fee_rate, self.max_new_notional)
        if self.sizing == "risk" and margin > 0:
            total_mult = self._layer_mult_total()
            self.planned_risk = min(self.planned_risk, policy.planned_risk_cap(
                margin, self.pos_leverage, self.sl_pct,
                policy.round_trip_cost(self.fee_rate, self.slippage_rate, None, margin * self.pos_leverage * total_mult), total_mult))
        # vượt trần rủi ro đang mở của danh mục
        margin, self.planned_risk = policy.apply_risk_ceiling(margin, self.planned_risk, self.max_new_risk)
        if margin <= 0:
            self.book.reject("no_margin", "entry")  # tín hiệu vào lệnh nhưng không còn vốn trống: ledger.rejected += 1
            return
        if self._enter(margin, "Tín hiệu vào lệnh (AST match)"):
            self.next_margin = margin

    def _layer_mult_total(self) -> float:
        return policy.layer_mult_total(self.dca_mults, len(self.dca_steps))

    def _risk_margin(self) -> float:
        margin, self.pos_leverage, self.planned_risk = policy.risk_margin(
            self.equity, self.risk_pct, self.max_notional_pct, self.sl_pct, self.fee_rate, self.slippage_rate,
            None, self.market == "perp", self.max_leverage, self.mmr, self.pos_leverage, self._layer_mult_total())
        return margin

    # ─── Một nến ────────────────────────────────────────────────────────────
    def on_bar(self, t: int, o: float, h: float, l: float, c: float,
               entry_signal: bool, stop_signal: bool, can_open: bool = True,
               vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Một nến 1m có giao dịch — cùng chữ ký và kết quả với `PositionTracker.on_bar` (= `on_bar_open` + `on_bar_rest`; trả vị thế vừa đóng)."""
        closed = self.on_bar_open(t, o, h, l, c, can_open)
        return self.on_bar_rest(t, o, h, l, c, entry_signal, stop_signal, closed, vol, dca_gate)

    def on_bar_open(self, t: int, o: float, h: float, l: float, c: float, can_open: bool = True) -> Optional[PositionModel]:
        """Pha MỞ nến (như `PositionTracker.on_bar_open`): báo nến cho venue, thoát chờ / hết thời gian giữ ở open, vào lệnh chờ ở open."""
        closed: Optional[PositionModel] = None
        begin_bar = getattr(self.venue, "begin_bar", None)
        if begin_bar is not None:
            begin_bar(self.slot, t, o, h, l, c, self)

        # 1. Đầu nến
        if self.is_open:
            if self.pending_exit:
                closed = self._close_market(self._status_by_pnl(o), _EXIT_REASON, "exit")
            elif self.timeout_ms and t - self.entry_time >= self.timeout_ms:
                closed = self._close_market(self._status_by_pnl(o), _TIMEOUT_REASON, "timeout")
        if closed is None and not self.is_open and self.pending_entry:
            self.pending_entry = False
            if can_open:
                self._open(t, o)
        return closed

    def on_bar_rest(self, t: int, o: float, h: float, l: float, c: float, entry_signal: bool, stop_signal: bool,
                    closed: Optional[PositionModel] = None, vol: float = float("nan"), dca_gate: bool = True) -> Optional[PositionModel]:
        """Pha TRONG nến + cuối nến (như `PositionTracker.on_bar_rest`); `closed` = kết quả `on_bar_open` cùng nến."""
        # 2-3. Trong nến
        if self.is_open and closed is None:
            self.book.mark(h, l)
            closed = self._intrabar()

        # 4. Cuối nến
        if self.is_open:
            adverse = l if self.is_long else h
            self.mae_usd = min(self.mae_usd, self.unrealized_pnl_usd(adverse))
            self.peak = max(self.peak, h) if self.is_long else min(self.peak, l)
            if stop_signal:
                self.pending_exit = True
        elif closed is None and entry_signal and (
                not self.cooldown_ms or self.last_close_time is None or t - self.last_close_time >= self.cooldown_ms):
            self.pending_entry = True
            self.pending_vol = vol
        self.dca_ok = bool(dca_gate)
        return closed

    def _close_event(self, fill: Fill) -> PositionModel:
        """Fill đóng do venue sinh (SL / TRAIL / LIQ / TP / sàn đã đóng): gắn trạng thái + MAE rồi áp."""
        if fill.kind == "liq":
            status = PositionStatus.LIQ
        elif fill.kind == "tp":
            status = PositionStatus.TP
        elif fill.kind == "sl":
            status = PositionStatus.SL
        else:
            status = self._status_by_pnl(fill.raw_price)   # trailing: lãi hay lỗ theo giá khớp (trước trượt)
        extra = {}
        if not fill.reason:                                # OKX suy kind từ vị thế biến mất: không có nhãn lệnh -> nhãn theo loại
            extra["reason"] = {"sl": _SL_REASON, "tp": _TP_REASON, "trail": _TRAIL_REASON}.get(fill.kind, _EXCHANGE_CLOSE_REASON)
        return self._apply_close(self._enrich(fill, status=int(status), mae_usd=self.mae_usd, **extra))

    def _handle(self, ev) -> Optional[PositionModel]:
        """Một sự kiện của venue khi vị thế đang mở. DCA bị từ chối (ngân sách / vốn / sàn): cắt các tầng còn lại; DCA khớp: áp, tính lại lệnh chờ
        từ avg mới; lệnh bảo vệ bị từ chối: chỉ ghi sổ (bot cảnh báo; nến sau đặt lại); đóng: áp. Trả vị thế vừa đóng, None nếu vẫn mở."""
        if isinstance(ev, OrderRejected):
            self.book.reject(ev.reason, ev.kind, ev.order_id)
            if ev.kind == "dca":
                self.dca_rejected += 1
                self.dca_steps = self.dca_steps[: self.layer_count - 1]   # không nhồi thêm tầng nào nữa
            return None
        if ev.kind == "dca":
            self.book.apply_fill(self._enrich(ev, unit_pct=self.unit_pct, leverage_used=self.pos_leverage, risk_usd=self.planned_risk))
            self.next_margin = ev.margin
            self._place_orders()                            # avg / last_fill đổi: tính lại SL, TRAIL, DCA kế, TP
            return None
        return self._close_event(ev)

    def sync_events(self) -> Optional[PositionModel]:
        """Bot sàn: kéo và áp mọi sự kiện venue đã có (poll: DCA khớp, SL/TP/trailing khớp, sàn đóng vị thế) — DCA khớp thì SL/TP mới đặt ngay từ avg mới.
        Trả vị thế vừa đóng (nếu có). Không làm gì khi slot chưa mở."""
        if not self.is_open:
            return None
        while True:
            ev = self.venue.next_event(self.slot)
            if ev is None:
                return None
            closed = self._handle(ev)
            if closed is not None:
                return closed

    def _intrabar(self) -> Optional[PositionModel]:
        self._place_orders()
        while True:
            ev = self.venue.next_event(self.slot)
            if ev is None:
                break
            closed = self._handle(ev)
            if closed is not None:
                return closed
        end_adverse = getattr(self.venue, "end_adverse", None)
        if end_adverse is not None:
            end_adverse(self.slot)
        ev = self.venue.next_event(self.slot)               # phía có lợi: TP
        if ev is not None:
            return self._close_event(ev)
        return None

    def force_close(self, t: int, raw_price: float, reason: str = "End of Backtest") -> Optional[PositionModel]:
        if not self.is_open:
            return None
        self.pending_entry = False
        quote = getattr(self.venue, "quote", None)
        if quote is not None:
            quote(self.slot, t, raw_price)
        return self._close_market(PositionStatus.CANCEL, reason, "kill" if reason.startswith("Kill") else "end")

# ── legacy: core/execute/sim_venue.py ──
#
# SimVenue (P6.4) — sàn mô phỏng theo nến, cài `Venue` (venue.py) cho backtest-py / paper.
#
# Khớp lệnh theo nến với chính sách đường giá trong nến `intrabar_path` (mỗi slot một giá trị, do manager truyền qua `add_slot`) — tái hiện
# NGUYÊN VĂN `PositionTracker._intrabar`:
#
# **"ohlc" (mặc định, = NautilusTrader) / "adaptive"** (`_match_path`): nến là đường O -> H -> L -> C (adaptive: cực gần open trước; `policy.bar_points`).
# Mỗi chặng là MỘT tick: venue trả lần lượt (a) các fill DCA mà chặng xuyên qua (từ gần ra xa; sau mỗi fill manager đặt lại lệnh, tầng kế tính từ
# giá khớp), (b) chốt lời (limit, khớp ở mức TP), (c) lệnh stop: SL, TRAIL, thanh lý — mức bị xuyên cao nhất trước (long). SL / TP là lệnh đã nằm
# trên sàn từ cuối nến trước: venue ĐÓNG BĂNG mức của chúng ở lần `next_event` đầu của nến (manager đặt lại từ avg mới sau fill DCA chỉ có hiệu lực
# từ nến sau). Stop-market khớp ở mức kích hoạt; tick mở cửa (gap) thì ở open. TRAIL: venue giữ đỉnh/đáy chạy theo từng chặng (khởi tạo từ `Order.peak`),
# kích hoạt theo `activation_pct` và avg hiện tại, mức = `callback_pct`% khỏi đỉnh sau chặng trước (không có `peak` -> dùng `level` tĩnh như cũ).
# Cuối nến (`end_adverse` -> `_match_favorable`): nếu nến có fill DCA và TP đặt lại từ avg mới đã "trong giá" ở close -> khớp ngay ở close (taker).
#
# **"adverse_first"** (cũ, giữ nguyên từng bit — slot cũ trong paper.pkl mặc định như vậy):
#
# 1. Lệnh market ENTRY / EXIT khớp ở giá open (đã gồm trượt giá taker), theo thứ tự đặt.
# 2. Phía BẤT LỢI: trong các lệnh chờ DCA (limit), SL, TRAIL và giá thanh lý (sinh từ `position_view`, chỉ perp), lệnh nào ĐÃ CHẠM
#    (long: low <= mức; short: high >= mức) thì chọn mức chạm TRƯỚC: long = mức cao nhất, short = thấp nhất; hoà mức -> thoát
#    (SL/TRAIL/LIQ, ưu tiên 0) trước DCA (ưu tiên 1); hoà tiếp -> theo thứ tự DCA, SL, TRAIL, LIQ. Giá open đã vượt mức stop-market
#    (SL/TRAIL/LIQ) -> khớp ở open (gap).
#    `stop_fill="extreme"`: SL/TRAIL khớp ở giá xấu nhất của nến. DCA có `trigger` (limit_through): phải đi QUA mức mới khớp, và luôn
#    khớp ở giá đặt (level), kể cả khi open đã gap qua mức (quy tắc bảo thủ 2026-10-06: phần giá tốt hơn thuộc về bên khớp lệnh).
#    Sau mỗi fill vị thế đổi (DCA) người đặt lệnh tính lại lệnh chờ rồi gọi `next_event` tiếp, NHƯNG lệnh SL cũ vẫn nằm trên sàn:
#    từ sau fill DCA đầu tiên của nến, mức SL dùng trong phần còn lại của nến là mức SL cũ (`_Slot.stale_sl`); SL mới có hiệu lực từ nến sau.
#    Giá thanh lý vẫn tính lại ngay từ avg mới.
# 3. `end_adverse(slot)` chuyển sang phía CÓ LỢI: TP (limit từ giá TB) chỉ xét nếu trong nến KHÔNG có DCA khớp; khớp ở mức TP (level), kể cả khi open đã vượt mức.
# 4. Peak của trailing do người đặt lệnh giữ và chỉ đổi cuối nến (trailing dùng đỉnh các nến TRƯỚC) — venue chỉ nhận mức TRAIL tĩnh.
#
# Venue không đụng vào sổ vốn: kiểm tra trước giao dịch (ngân sách vị thế, giữ chỗ vốn) là `gate` do người đặt lệnh cấp cho từng slot;
# gate từ chối -> `OrderRejected` và KHÔNG tiêu id (id `Fill.order_id` lấy từ `tracker._next_id()` lúc khớp, đúng thứ tự gọi của tracker).
# Chưa hỗ trợ móc fill-model của AMM (`limit_taker`, `impact_fn`): DEX nằm ngoài P6 -> raise.
#

_KIND_NAME = {OrderKind.ENTRY: "entry", OrderKind.EXIT: "exit", OrderKind.DCA: "dca", OrderKind.SL: "sl", OrderKind.TRAIL: "trail", OrderKind.TP: "tp"}

# gate(kind, margin, fee, fill_price) -> None (chấp nhận) | lý do từ chối ("budget" | "capital")
Gate = Callable[[str, float, float, float], Optional[str]]


def _trigger(order: Order) -> float:
    """Mức phải đi tới để lệnh limit khớp: `trigger` (limit_through) nếu có, không thì `level`."""
    return order.level if isnan(order.trigger) else order.trigger


class PositionView(Protocol):
    """Cửa sổ ĐỌC vào vị thế của slot (đối tượng sống: venue đọc lại sau mỗi fill, người đặt lệnh không cần đẩy cập nhật)."""
    avg: float
    qty: float
    pos_leverage: float
    mmr: float
    is_long: bool
    market: str          # "perp" -> venue sinh giá thanh lý; "spot" -> không


@dataclass
class _Slot:
    fee_rate: float
    maker_fee_rate: float
    slippage_rate: float
    stop_fill: str
    gate: Optional[Gate]
    qty_step: float = 0.0
    orders: List[Order] = field(default_factory=list)     # lệnh chờ (DCA / SL / TRAIL / TP)
    market: List[Order] = field(default_factory=list)     # lệnh market chờ khớp ở giá quote (ENTRY / EXIT)
    view: Optional[PositionView] = None
    phase: str = "adverse"
    t: int = 0
    o: float = float("nan")
    h: float = float("nan")
    l: float = float("nan")
    c: float = float("nan")
    quoted: bool = False
    dca_filled: bool = False
    stale_sl: Optional[float] = None    # mức SL cũ còn hiệu lực sau fill DCA đầu tiên của nến (None = chưa có DCA khớp / không có SL)
    # ── đường ohlc / adaptive ──
    intrabar_path: str = "ohlc"
    pts: tuple = ()                     # bốn điểm giá của nến theo thứ tự đi qua
    tick_i: int = 0                     # chặng đang xử lý (0 = tick mở cửa)
    prev: float = float("nan")          # giá chặng trước (chặng không đổi giá bị bỏ qua)
    frozen: bool = False                # đã đóng băng SL / TP của nến chưa
    sl_lv: Optional[float] = None       # mức SL cố định cả nến (None = không có SL)
    sl_reason: str = ""
    tp_lv: Optional[float] = None       # mức TP cố định cả nến (None = không có TP)
    tp_need: float = float("nan")
    tp_reason: str = ""
    peak: float = float("nan")          # đỉnh/đáy có lợi chạy theo chặng (trailing); nan = không có TRAIL
    rejects: Deque[OrderRejected] = field(default_factory=deque)   # lệnh bị từ chối ngay lúc đặt (hợp đồng venue.py): trả ở next_event trước mọi khớp

    def __setstate__(self, state) -> None:
        """Pickle cũ (paper.pkl của bot đang chạy, trước P6.8b) chưa có `rejects`."""
        self.__dict__.update(state)
        self.__dict__.setdefault("rejects", deque())
        self.__dict__.setdefault("stale_sl", None)
        self.__dict__.setdefault("qty_step", 0.0)
        for k, v in (("intrabar_path", "adverse_first"), ("pts", ()), ("tick_i", 0), ("prev", float("nan")), ("frozen", False),
                     ("sl_lv", None), ("sl_reason", ""), ("tp_lv", None), ("tp_need", float("nan")), ("tp_reason", ""), ("peak", float("nan"))):
            self.__dict__.setdefault(k, v)     # slot cũ (trước intrabar_path) giữ chính sách cũ để vị thế đang mở không đổi ngữ nghĩa giữa chừng


class SimVenue:
    caps = VenueCaps(generates_liquidation=True, native_trailing=False, post_only=False, rounds_qty=False)

    def __init__(self, post_only: bool = False, rounds_qty: bool = False) -> None:
        if post_only or rounds_qty:
            self.caps = VenueCaps(generates_liquidation=True, native_trailing=False, post_only=post_only, rounds_qty=rounds_qty)
        self._slots: Dict[int, _Slot] = {}

    # ─── cấu hình ───────────────────────────────────────────────────────────
    def add_slot(self, slot: int, *, fee_rate: float, maker_fee_rate: float, slippage_rate: float, stop_fill: str = "level",
                 gate: Optional[Gate] = None, limit_taker: bool = False, impact_fn=None, intrabar_path: str = "ohlc",
                 qty_step: float = 0.0) -> None:
        """Đăng ký slot với chi phí khớp của nó. gate = kiểm tra trước giao dịch cho lệnh vào / DCA (None = luôn chấp nhận).
        intrabar_path = "ohlc" | "adaptive" | "adverse_first" (xem docstring module)."""
        if limit_taker or impact_fn is not None:
            raise NotImplementedError("SimVenue chưa hỗ trợ limit_taker / impact_fn (AMM/DEX nằm ngoài P6)")
        if stop_fill not in ("level", "extreme"):
            raise ValueError(f"stop_fill phải là 'level' hoặc 'extreme', nhận '{stop_fill}'")
        if intrabar_path not in policy.INTRABAR_PATHS:
            raise ValueError(f"intrabar_path phải là một trong {policy.INTRABAR_PATHS}, nhận '{intrabar_path}'")
        self._slots[slot] = _Slot(float(fee_rate), float(maker_fee_rate), float(slippage_rate), stop_fill, gate,
                                  qty_step=float(qty_step), intrabar_path=intrabar_path)

    # ─── Venue ──────────────────────────────────────────────────────────────
    def submit(self, order: Order) -> None:
        st = self._slots[order.slot]
        has_pos = st.view is not None and st.view.qty > 0
        if order.kind == OrderKind.ENTRY and (has_pos or any(o.kind == OrderKind.ENTRY for o in st.market)):
            st.rejects.append(OrderRejected(order.slot, order.id, "entry", "position_exists"))     # như OkxVenue: tối đa một vị thế mỗi slot
            return
        if order.kind in (OrderKind.DCA, OrderKind.SL, OrderKind.TRAIL, OrderKind.TP) and not has_pos:
            st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME[order.kind], "no_position"))
            return
        if self.caps.post_only and getattr(order, "post_only", False):
            ref_px = st.prev if (not isnan(st.prev) and st.prev > 0) else (st.o if st.quoted else float("nan"))
            if not isnan(ref_px) and ref_px > 0 and not isnan(order.level):
                if (order.is_buy and order.level >= ref_px) or (not order.is_buy and order.level <= ref_px):
                    st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME.get(order.kind, "order"), "post_only"))
                    return
        if self.caps.rounds_qty and st.qty_step > 0 and order.kind in (OrderKind.ENTRY, OrderKind.DCA):
            px = st.o if (order.kind == OrderKind.ENTRY and st.quoted) else order.level
            if px > 0 and order.notional > 0:
                raw_qty = order.notional / px
                rounded_steps = math.floor(raw_qty / st.qty_step + 1e-12)
                if rounded_steps <= 0:
                    st.rejects.append(OrderRejected(order.slot, order.id, _KIND_NAME.get(order.kind, "order"), "min_size"))
                    return
                order.notional = rounded_steps * st.qty_step * px
        if order.kind in (OrderKind.ENTRY, OrderKind.EXIT):
            if not st.quoted:
                raise RuntimeError("SimVenue: lệnh market cần giá quote (gọi begin_bar hoặc quote trước)")
            st.market.append(order)
        else:
            st.orders.append(order)

    def cancel(self, order_id: int) -> None:
        for st in self._slots.values():
            st.orders = [o for o in st.orders if o.id != order_id]
            st.market = [o for o in st.market if o.id != order_id]

    def cancel_slot(self, slot: int) -> None:
        st = self._slots[slot]
        st.orders.clear()
        st.market.clear()

    def open_orders(self, slot: int) -> List[Order]:
        st = self._slots[slot]
        return list(st.market) + list(st.orders)

    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]:
        st = self._slots[slot]
        if st.rejects:
            return st.rejects.popleft()
        if st.market:
            return self._match_market(slot, st, st.market.pop(0))
        if st.view is None:
            return None
        if st.phase == "adverse":
            return self._match_adverse(slot, st)
        if st.phase == "favorable":
            return self._match_favorable(slot, st)
        return None

    # ─── theo nến ───────────────────────────────────────────────────────────
    def quote(self, slot: int, t: int, price: float) -> None:
        """Giá tham chiếu cho lệnh market ngoài vòng nến (ví dụ đóng cuối kỳ / kill switch)."""
        st = self._slots[slot]
        st.t, st.o, st.quoted = int(t), float(price), True

    def begin_bar(self, slot: int, t: int, o: float, h: float, l: float, c: float, position_view: PositionView) -> None:
        """Bắt đầu nến của slot: đặt quote = open, phía bất lợi mở. position_view (đối tượng sống) cho qty / avg / thanh lý."""
        st = self._slots[slot]
        st.t, st.o, st.h, st.l, st.c, st.quoted = int(t), o, h, l, c, True
        st.view = position_view
        st.phase = "adverse"
        st.dca_filled = False
        st.stale_sl = None
        st.frozen = False
        st.tick_i = 0
        st.prev = o
        st.peak = float("nan")
        st.pts = () if st.intrabar_path == "adverse_first" else policy.bar_points(st.intrabar_path, o, h, l, c)

    def end_adverse(self, slot: int) -> None:
        """Chuyển sang phía CÓ LỢI của nến (TP)."""
        self._slots[slot].phase = "favorable"

    # ─── khớp lệnh ──────────────────────────────────────────────────────────
    def _match_market(self, slot: int, st: _Slot, order: Order) -> Union[Fill, OrderRejected]:
        is_long = st.view.is_long if st.view is not None else order.is_buy
        raw = st.o
        if order.kind == OrderKind.ENTRY:
            slip = st.slippage_rate
            price = policy.entry_fill_price(raw, slip, is_long)
            notional = order.notional
            if self.caps.rounds_qty and st.qty_step > 0 and raw > 0:
                steps = math.floor(notional / raw / st.qty_step + 1e-12)
                notional = steps * st.qty_step * price
            fee = policy.entry_fee(notional, st.fee_rate)
            reason = st.gate("entry", order.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, order.id, "entry", reason)
            return Fill(slot=slot, order_id=next_id(), kind="entry", t=st.t, price=price, raw_price=raw, notional=notional,
                        margin=order.margin, fee=fee, slip=slip, liquidity="taker", reason=order.reason)
        return self._close_fill(slot, st, "exit", raw, order.reason, taker=True)

    def _close_fill(self, slot: int, st: _Slot, kind: str, raw: float, reason: str, taker: bool, liq: bool = False) -> Fill:
        """Fill đóng hết vị thế (thứ tự phép toán y `PositionTracker._close`). Xoá mọi lệnh chờ của slot."""
        is_long, qty = st.view.is_long, st.view.qty
        slip = 0.0
        if taker and not liq:
            slip = st.slippage_rate
            price = policy.exit_fill_price(raw, slip, is_long)
        else:
            price = raw
        fee = policy.exit_fee(qty, price, st.fee_rate if taker or liq else st.maker_fee_rate)
        st.orders.clear()
        st.market.clear()
        return Fill(slot=slot, order_id=next_id(), kind=kind, t=st.t, price=price, raw_price=raw, notional=0.0, margin=0.0,
                    fee=fee, slip=slip, liquidity="liquidation" if liq else ("taker" if taker else "maker"), reason=reason)

    def _first(self, st: _Slot, kind: OrderKind) -> Optional[Order]:
        for o in st.orders:
            if o.kind == kind:
                return o
        return None

    def _match_path(self, slot: int, st: _Slot) -> Optional[Union[Fill, OrderRejected]]:
        """Đường ohlc / adaptive: kéo fill kế tiếp của tick hiện tại; hết tick thì sang chặng sau (xem docstring module)."""
        view = st.view
        is_long = view.is_long
        if not st.frozen:                   # SL / TP đã nằm trên sàn từ cuối nến trước (manager vừa đặt): mức cố định cả nến
            st.frozen = True
            sl, tp, tr = self._first(st, OrderKind.SL), self._first(st, OrderKind.TP), self._first(st, OrderKind.TRAIL)
            if sl is not None:
                st.sl_lv, st.sl_reason = sl.level, sl.reason
            else:
                st.sl_lv = None
            if tp is not None:
                st.tp_lv, st.tp_need, st.tp_reason = tp.level, _trigger(tp), tp.reason
            else:
                st.tp_lv = None
            st.peak = tr.peak if tr is not None else float("nan")
        while st.tick_i < 4:
            p = st.pts[st.tick_i]
            if st.tick_i and p == st.prev:
                st.tick_i += 1
                continue
            ev = self._match_tick(slot, st, p, st.tick_i == 0)
            if ev is not None:
                return ev
            st.peak = policy.peak_step(st.peak, p, is_long)
            st.prev = p
            st.tick_i += 1
        return None

    def _match_tick(self, slot: int, st: _Slot, p: float, at_open: bool) -> Optional[Union[Fill, OrderRejected]]:
        """Fill kế tiếp mà tick giá `p` kích hoạt: (a) DCA, (b) TP, (c) stop (SL / TRAIL / thanh lý). None = tick hết việc."""
        view = st.view
        is_long = view.is_long
        sign = policy.sign_of(is_long)
        od = self._first(st, OrderKind.DCA)
        if od is not None and policy.reached(_trigger(od), p, is_long):
            price = od.level        # limit chờ sẵn khớp ĐÚNG ở giá đặt, kể cả khi gap qua mức
            fee = policy.entry_fee(od.notional, st.maker_fee_rate)
            st.orders.remove(od)
            reason = st.gate("dca", od.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, od.id, "dca", reason)
            st.dca_filled = True
            return Fill(slot=slot, order_id=next_id(), kind="dca", t=st.t, price=price, raw_price=price, notional=od.notional,
                        margin=od.margin, fee=fee, slip=0.0, liquidity="maker", reason=od.reason)
        if st.tp_lv is not None and policy.tp_hit(p, st.tp_need, is_long):
            return self._close_fill(slot, st, "tp", st.tp_lv, st.tp_reason, taker=False)     # limit khớp ĐÚNG ở mức TP
        events = []     # (mức, ưu tiên, loại) — thứ tự SL, TRAIL, LIQ như tracker
        reasons = {"sl": st.sl_reason}
        if st.sl_lv is not None:
            events.append((st.sl_lv, 0, "sl"))
        tr = self._first(st, OrderKind.TRAIL)
        if tr is not None:
            if isnan(tr.peak):              # lệnh TRAIL không kèm đỉnh: mức tĩnh như đường cũ
                events.append((tr.level, 0, "trail"))
                reasons["trail"] = tr.reason
            elif policy.trail_active(st.peak, view.avg, tr.activation_pct, sign):
                events.append((policy.trail_level(st.peak, tr.callback_pct, sign), 0, "trail"))
                reasons["trail"] = tr.reason
        if view.market == "perp" and view.qty > 0:
            liq = policy.liq_price(view.avg, view.pos_leverage, view.mmr, is_long)
            if liq > 0:
                events.append((liq, 0, "liq"))
        reached = [e for e in events if policy.reached(e[0], p, is_long)]
        if not reached:
            return None
        level, _, kind = policy.pick_first_touched(reached, is_long)
        price = policy.tick_stop_price(level, st.o, is_long, at_open)
        if kind == "liq":
            return self._close_fill(slot, st, "liq", price, "Thanh lý (perp)", taker=False, liq=True)
        if st.stop_fill == "extreme":
            price = policy.stop_extreme_fill(price, st.l if is_long else st.h, is_long)
        return self._close_fill(slot, st, kind, price, reasons[kind], taker=True)

    def _match_adverse(self, slot: int, st: _Slot) -> Optional[Union[Fill, OrderRejected]]:
        if st.intrabar_path != "adverse_first":
            return self._match_path(slot, st)
        view = st.view
        is_long = view.is_long
        adverse = st.l if is_long else st.h
        by_kind: Dict[str, Order] = {}
        events = []   # (mức, ưu tiên khi hoà: thoát trước, loại) — thứ tự DCA, SL, TRAIL, LIQ như tracker
        for kind, name, prio in ((OrderKind.DCA, "dca", 1), (OrderKind.SL, "sl", 0), (OrderKind.TRAIL, "trail", 0)):
            od = self._first(st, kind)
            if od is not None:
                by_kind[name] = od
                lv = st.stale_sl if (name == "sl" and st.stale_sl is not None) else _trigger(od)   # SL cũ chưa dời kịp sau fill DCA
                events.append((lv, prio, name))
        liq = None
        if view.market == "perp" and view.qty > 0:
            liq = policy.liq_price(view.avg, view.pos_leverage, view.mmr, is_long)
            if liq > 0:
                events.append((liq, 0, "liq"))
        reached = [e for e in events if policy.reached(e[0], adverse, is_long)]
        if not reached:
            return None
        level, _, kind = policy.pick_first_touched(reached, is_long)
        if kind == "dca":
            od = by_kind["dca"]
            price = od.level        # limit chờ sẵn khớp ĐÚNG ở giá đặt, kể cả khi gap qua mức
            fee = policy.entry_fee(od.notional, st.maker_fee_rate)
            st.orders.remove(od)
            reason = st.gate("dca", od.margin, fee, price) if st.gate is not None else None
            if reason is not None:
                return OrderRejected(slot, od.id, "dca", reason)
            if not st.dca_filled:
                sl_od = self._first(st, OrderKind.SL)
                st.stale_sl = sl_od.level if sl_od is not None else None   # SL đang nằm trên sàn trước fill (manager sắp đặt lại từ avg mới)
            st.dca_filled = True
            return Fill(slot=slot, order_id=next_id(), kind="dca", t=st.t, price=price, raw_price=price, notional=od.notional,
                        margin=od.margin, fee=fee, slip=0.0, liquidity="maker", reason=od.reason)
        price = policy.gap_fill(level, st.o, is_long)
        if kind == "liq":
            return self._close_fill(slot, st, "liq", price, "Thanh lý (perp)", taker=False, liq=True)
        if st.stop_fill == "extreme":
            price = policy.stop_extreme_fill(price, adverse, is_long)   # bi quan: stop-market khớp ở giá xấu nhất của nến
        return self._close_fill(slot, st, kind, price, by_kind[kind].reason, taker=True)

    def _match_favorable(self, slot: int, st: _Slot) -> Optional[Fill]:
        tp = self._first(st, OrderKind.TP)
        if st.intrabar_path != "adverse_first":
            # TP đặt lại từ avg mới (sau fill DCA trong nến) thấy sổ lệnh ở close: đã "trong giá" -> khớp ngay ở close như lệnh taker
            if tp is None or not st.dca_filled or not policy.tp_hit(st.c, tp.level, st.view.is_long):
                return None
            return self._close_fill(slot, st, "tp", st.c, tp.reason, taker=True)
        if tp is None or st.dca_filled:     # không giả định "vừa nhồi ở đáy vừa chốt ở đỉnh" trong cùng một nến
            return None
        is_long = st.view.is_long
        need = _trigger(tp)
        favorable = st.h if is_long else st.l
        if not policy.tp_hit(favorable, need, is_long):
            return None
        raw = tp.level      # limit chờ sẵn khớp ĐÚNG ở mức TP, kể cả khi open đã vượt mức
        return self._close_fill(slot, st, "tp", raw, tp.reason, taker=False)

# ── legacy: core/execute/runner.py ──
#
# Runner (P6.5) — chạy MỘT nến của cả danh mục qua một Venue: nguồn duy nhất của vòng danh mục cho paper / bot (docs/bmad/p6_execution_design.md §5).
#
# Thứ tự y hệt vòng lặp gốc (test/reference_engine.py::RefPortfolioEngine.run), HAI PHA mỗi nến (ADR P6 §10, P6.12):
# pha 1 (mở nến, tài sản theo thứ tự sổ) funding -> từng slot: luật bỏ qua, `risk.admit_entry` (trạng thái LÚC MỞ NẾN, gross theo `last_close` = đóng nến
# trước, chỉ khi qua trần số vị thế) -> đặt trần (max_new_notional / max_new_risk / risk_scale) -> `on_bar_open` -> xả trần -> thu lệnh đóng ở open;
# pha 2 (trong nến, tài sản theo thứ tự sổ) `on_bar_rest` -> thu lệnh đóng -> cập nhật last_close/low/high/open;
# pha 3: MTM (mtm, worst) -> `peak_mtm` -> `risk.kill_triggered` -> đóng hết ("Kill switch danh mục").
# Trước P6.12 mỗi tài sản chạy TRỌN nến rồi mới tới tài sản kế -> lệnh vào của B ở open thấy SL/TP trong nến của A (nhìn trước); nay thì không.
#
# Runner KHÔNG biết slot khớp lệnh thế nào: mỗi slot ("tracker" trong `books`) là một "actor" có giao diện chung của `PositionManager` (đường event,
# điều khiển Venue) và `PositionTracker` (đường cũ): is_open, pending_entry, qty, planned_risk, max_new_*, risk_scale, on_bar_open, on_bar_rest, apply_funding,
# force_close, unrealized_pnl_usd. Nên cùng một vòng danh mục chạy được cho cả hai — test_runner_parity.py dựa vào đó để khoá bit-identical.
# `venue` chỉ được giữ để chủ sở hữu (PaperBook / bot) truy cập; Runner không gọi nó (venue None = đường tracker cũ, không có sàn).
#

class Runner:
    def __init__(self, venue, account, books: List[Dict[str, Any]], risk: Dict[str, Any], trade_start: int = 0,
                 collect: Optional[Callable[..., None]] = None, initial_capital: Optional[float] = None):
        """books = [{"symbol", "entries": [{"strategy", "side", "tracker": actor}]}] theo thứ tự sổ (tài sản, rồi chiến lược).
        collect(sym, e, pos, low, high) thay `record` nếu chủ sở hữu muốn móc thêm khi ghi lệnh đóng (TickBook)."""
        self.venue = venue
        self.account = account
        self.books = books
        self.risk = dict(risk)
        self.trade_start = int(trade_start)
        self.collect = collect
        n = len(books)
        nan = float("nan")
        self.last_close, self.last_low, self.last_high, self.last_open = [nan] * n, [nan] * n, [nan] * n, [nan] * n
        self.peak_mtm = float(account.initial if initial_capital is None else initial_capital)
        self.halted_at: Optional[int] = None
        self.last_t: Optional[int] = None
        self.trades: List[Dict[str, Any]] = []
        self.rejected_for_risk = 0

    def __getstate__(self) -> Dict[str, Any]:
        """Pickle (paper.pkl của bot): bỏ móc `collect` (hàm gắn của chủ sở hữu) — PaperBook.__setstate__ gắn lại sau khi nạp."""
        d = dict(self.__dict__)
        d["collect"] = None
        return d

    # ── danh mục ──
    def _gross(self) -> float:
        tot = 0.0
        for b, bk in enumerate(self.books):
            px = self.last_close[b]
            if px != px:
                continue
            tot += sum(e["tracker"].qty * px for e in bk["entries"] if e["tracker"].is_open)
        return tot

    def _open_risk(self) -> float:
        """Σ rủi ro tới SL (planned_risk) của mọi vị thế đang mở."""
        tot = 0.0
        for bk in self.books:
            for e in bk["entries"]:
                if e["tracker"].is_open:
                    tot += e["tracker"].planned_risk
        return tot

    def _counts(self) -> Tuple[int, List[int]]:
        per = [sum(1 for e in bk["entries"] if e["tracker"].is_open) for bk in self.books]
        return sum(per), per

    def mtm(self) -> Tuple[float, float]:
        """(vốn theo giá đóng nến, vốn theo giá xấu nhất của nến) = vốn đã chốt + lãi/lỗ chưa chốt của mọi vị thế mở."""
        mtm = worst = self.account.equity
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    mtm += tr.unrealized_pnl_usd(self.last_close[b])
                    worst += tr.unrealized_pnl_usd(self.last_low[b] if tr.is_long else self.last_high[b])
        return mtm, worst

    def positions(self) -> List[Dict[str, Any]]:
        out = []
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                if tr.is_open:
                    out.append({"symbol": bk["symbol"], "strategy": e["strategy"], "side": e["side"], "qty": tr.qty, "avg": tr.avg,
                                "layers": tr.layer_count, "entry_time": tr.entry_time, "unrealized": tr.unrealized_pnl_usd(self.last_close[b])})
        return out

    # ── lệnh đóng ──
    def record(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        """Ghi lệnh đóng; fees/funding = chi phí cộng dồn (dương = trả), bar_low/bar_high = nến đóng (đối chiếu kịch bản SL bi quan)."""
        self.trades.append({"symbol": sym, "strategy": e["strategy"], "side": pos.pos_type.name, "enter_time": int(pos.enter_time),
                            "enter_price": float(pos.enter_price), "avg_price": float(pos.avg_price or pos.enter_price),
                            "close_time": int(pos.close_time), "close_price": float(pos.close_price), "qty": float(pos.qty),
                            "layers": int(pos.layers or 1), "pnl": round(float(pos.real_pnl), 6), "reason": pos.close_reason,
                            "fees": round(float(pos.fees_usd or 0), 6), "funding": round(float(pos.funding_usd or 0), 6),
                            "bar_low": float(low), "bar_high": float(high)})

    def _collect(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        (self.collect or self.record)(sym, e, pos, low, high)

    # ── một nến ──
    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến chạy ở thời điểm t (open_time), HAI PHA (ADR P6 §10). bars[sym] = (o, h, l, c) (tài sản không có nến: bỏ qua);
        sig[sym] = [{match, stop, vol}] theo thứ tự chiến lược; funding[sym] = [(funding_time, rate)] đến hạn <= t. -> các lệnh đóng ở nến này.

        Pha 1 — MỞ NẾN, mọi tài sản theo thứ tự sổ: funding -> từng slot: luật bỏ qua, `admit_entry` (trạng thái LÚC MỞ NẾN: vị thế mở
        sau các lệnh thoát/vào ở open của tài sản đứng trước; chưa tài sản nào chạy trong nến; gross định giá theo `last_close` = đóng nến
        TRƯỚC; vốn = sổ vốn sau funding + lệnh thoát ở open) -> đặt trần -> `on_bar_open` (thoát chờ / hết hạn, vào lệnh ở open) -> xả trần.
        Pha 2 — TRONG NẾN, mọi tài sản theo thứ tự sổ: `on_bar_rest` (SL / TP / DCA / trailing / thanh lý theo đường giá + sổ sách cuối nến),
        rồi cập nhật last_close/low/high/open. Pha 3: MTM -> peak_mtm -> kill switch.
        Nhờ vậy lệnh vào của tài sản B ở open t KHÔNG thấy lệnh thoát trong nến (SL/TP) hay giá đóng nến của tài sản A đứng trước (không nhìn trước)."""
        n0 = len(self.trades)
        cap = float(self.risk["max_gross_exposure"])
        kill_pct = float(self.risk.get("kill_switch_dd_pct") or 0)
        can_trade = t >= self.trade_start and self.halted_at is None
        touched = False
        todo: List[Tuple[int, str, Tuple[float, float, float, float], List[Tuple[Dict[str, Any], Dict[str, Any], bool, Any]]]] = []
        # ── Pha 1: mở nến ──
        for b, bk in enumerate(self.books):
            sym = bk["symbol"]
            if sym not in bars:
                continue
            o, h, l, c = bars[sym]
            for ft, rate in (funding or {}).get(sym, []):
                for e in bk["entries"]:
                    e["tracker"].apply_funding(float(rate), float(o))
            acts: List[Tuple[Dict[str, Any], Dict[str, Any], bool, Any]] = []
            for e, s in zip(bk["entries"], sig[sym]):
                tr = e["tracker"]
                m = bool(s["match"])
                if not tr.is_open and not tr.pending_entry and not m:
                    continue
                can_open = False
                if can_trade and tr.pending_entry and not tr.is_open:
                    n_open, per = self._counts()
                    gross = open_risk = 0.0
                    if n_open < int(self.risk["max_positions"]) and per[b] < int(self.risk["max_per_symbol"]):
                        gross = self._gross()
                        open_risk = self._open_risk()
                    adm = admit_entry(n_open, per[b], self.account.equity, self.account.peak, gross, open_risk,
                                      self.risk["max_positions"], self.risk["max_per_symbol"], cap,
                                      self.risk.get("max_open_risk_pct") or 0.0, self.risk.get("dd_throttle_pct") or 0.0,
                                      self.risk.get("dd_throttle_floor", 0.25))
                    can_open = adm.can_open
                    tr.max_new_notional, tr.max_new_risk, tr.risk_scale = adm.max_new_notional, adm.max_new_risk, adm.risk_scale
                    if not can_open:
                        self.rejected_for_risk += 1
                closed_open = tr.on_bar_open(t, o, h, l, c, can_open=can_open)
                tr.max_new_notional = float("inf")
                tr.max_new_risk = float("inf")
                tr.risk_scale = 1.0
                if closed_open is not None:
                    self._collect(sym, e, closed_open, l, h)
                acts.append((e, s, m, closed_open))
            todo.append((b, sym, (o, h, l, c), acts))
        # ── Pha 2: trong nến ──
        for b, sym, (o, h, l, c), acts in todo:
            for e, s, m, closed_open in acts:
                tr = e["tracker"]
                vol = s.get("vol")
                pos = tr.on_bar_rest(t, o, h, l, c, entry_signal=m and can_trade, stop_signal=bool(s["stop"]), closed=closed_open,
                                     vol=float(vol) if vol is not None else float("nan"), dca_gate=bool(s.get("dca", True)))
                if pos is not None and pos is not closed_open:
                    self._collect(sym, e, pos, l, h)
            self.last_close[b], self.last_low[b], self.last_high[b], self.last_open[b] = float(c), float(l), float(h), float(o)
            touched = True
        self.last_t = t
        if touched:
            mtm, worst = self.mtm()
            self.peak_mtm = max(self.peak_mtm, mtm)
            if self.halted_at is None and kill_triggered(worst, self.peak_mtm, kill_pct):
                self._kill(t)
        return self.trades[n0:]

    def _kill(self, t: int) -> None:
        """Kill switch: dừng giao dịch mới và đóng hết vị thế ở giá đóng nến gần nhất."""
        self.halted_at = t
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                tr = e["tracker"]
                tr.pending_entry = False
                pos = tr.force_close(t, self.last_close[b], "Kill switch danh mục")
                if pos is not None:
                    self._collect(bk["symbol"], e, pos, self.last_low[b], self.last_high[b])

    # ── bot sàn (P6.8b): sự kiện venue đến giữa hai nến ──
    def sync_events(self) -> List[Dict[str, Any]]:
        """Áp các sự kiện venue đã có (DCA khớp, sàn đóng vị thế...) của mọi slot đang mở -> lệnh đóng mới. Chỉ actor có `sync_events` (manager)."""
        n0 = len(self.trades)
        for b, bk in enumerate(self.books):
            for e in bk["entries"]:
                sync = getattr(e["tracker"], "sync_events", None)
                if sync is None or not e["tracker"].is_open:
                    continue
                pos = sync()
                if pos is not None:
                    self._collect(bk["symbol"], e, pos, self.last_low[b], self.last_high[b])
        return self.trades[n0:]

    def sample(self, t: int, marks: Dict[str, float]) -> Tuple[float, bool]:
        """Mẫu giá giữa hai nến (ADR D3): vốn MTM tại giá mẫu `marks[sym]` (thiếu -> giá đóng nến gần nhất) so với `peak_mtm` — cùng `risk.kill_triggered`
        như cuối nến, chỉ khác điểm giá. KHÔNG nâng peak_mtm (peak chỉ theo MTM đóng nến như sim). -> (vốn MTM theo mẫu, kill có kích hoạt)."""
        m = self.account.equity
        for b, bk in enumerate(self.books):
            px = marks.get(bk["symbol"])
            if px is not None and px == px:
                self.last_close[b] = float(px)
            px = self.last_close[b]
            if px != px:
                continue
            for e in bk["entries"]:
                if e["tracker"].is_open:
                    m += e["tracker"].unrealized_pnl_usd(px)
        if self.halted_at is None and kill_triggered(m, self.peak_mtm, float(self.risk.get("kill_switch_dd_pct") or 0)):
            self._kill(t)
            return m, True
        return m, False


# ── legacy: PaperBook (trước đây live/paper.py) ──
#
# Sổ PAPER: khớp lệnh mô phỏng bằng SimVenue + PositionManager (đường SỰ KIỆN, P6.5) và đúng vòng danh mục của PortfolioEngine — từng nến chạy một.
# Vòng danh mục nằm ở `Runner`; PaperBook chỉ là mặt tiền giữ API cũ (books, ledger, trades, last_t, halted_at, peak_mtm, rejected_for_risk, last_close...,
# positions(), mtm(), step_bar()). engine="event" (mặc định): MỘT SimVenue chung, MỘT Account chung, một PositionManager mỗi slot (`e["tracker"]` giữ manager).
# engine="tracker": đường PositionTracker cũ, bit-identical (TickBook cũ). Bot paper (và bóng của bot demo legacy) đã chạy trên `KernelPaperBook`; PaperBook còn
# cho bóng của UnifiedBot (T8/T9), test đối chiếu và việc chuyển paper.pkl cũ (live/live.py PHẦN B); xoá ở T10.
#
# Pickle: bản pickle của code CŨ (không có `runner`) được nạp lại thành engine="tracker" (trackers + sổ vốn cũ được Runner nhận nguyên, venue=None) nên bot
# đang chạy tiếp được, bit-identical với trước. Runner bỏ móc `collect` khi pickle, __setstate__ gắn lại. Pickle cũ lưu `backend.live.paper.PaperBook` được
# StateUnpickler (live/live.py, bảng OLD_CLASSES) ánh xạ về lớp này.

def _engine(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    """Như _engine_slots nhưng mỗi slot là một PositionTracker (đường Python cũ của PaperBook / unified, tới T10)."""
    pe = _portfolio(symbol, strategies, base_frame, start, end)
    return pe._make_trackers(symbol, pe.ledger)


def _proxy(name: str, settable: bool = True) -> property:
    """Thuộc tính của PaperBook uỷ quyền sang Runner (trạng thái danh mục sống ở Runner)."""
    def get(self):
        return getattr(self.runner, name)

    def put(self, v):
        setattr(self.runner, name, v)
    return property(get, put if settable else None)


class PaperBook:
    def __init__(self, strategies: List[Dict[str, Any]], symbols: List[str], base_frame: str, capital: float, risk: Dict[str, Any],
                 trade_start: int = 0, engine: str = "event", record_events: bool = False,
                 post_only: bool = False, rounds_qty: bool = False):
        if engine not in ("event", "tracker"):
            raise ValueError(f"engine phải là 'event' hoặc 'tracker', nhận '{engine}'")
        self.engine = engine
        self.symbols = list(symbols)
        ledger = Account(float(capital))
        venue = None
        self.events: Optional[List] = [] if record_events else None   # chuỗi sự kiện của mọi slot (mặc định tắt: bot chạy lâu sẽ phình)
        if engine == "event":
            venue = SimVenue(post_only=post_only, rounds_qty=rounds_qty)
        books: List[Dict[str, Any]] = []
        slot = 0
        for sym in self.symbols:
            eng, pairs = _engine(sym, strategies, base_frame, 0, DAY)
            entries = []
            for st, tr in pairs:
                if engine == "event":
                    actor = PositionManager(tr, venue, slot=slot, account=ledger, events=self.events)   # sổ vốn chung (như PortfolioEngine)
                else:
                    tr.ledger = ledger
                    tr.capital = ledger.initial
                    actor = tr
                slot += 1
                entries.append({"strategy": st["id"], "side": st["side"], "tracker": actor})
            books.append({"symbol": sym, "entries": entries})
        self.runner = Runner(venue, ledger, books, risk, trade_start, collect=self._collect, initial_capital=float(capital))

    # ── trạng thái (uỷ quyền Runner) ──
    books = _proxy("books", settable=False)
    last_close, last_low, last_high, last_open = _proxy("last_close"), _proxy("last_low"), _proxy("last_high"), _proxy("last_open")
    peak_mtm, halted_at, last_t = _proxy("peak_mtm"), _proxy("halted_at"), _proxy("last_t")
    trades, rejected_for_risk = _proxy("trades"), _proxy("rejected_for_risk")
    risk, trade_start = _proxy("risk"), _proxy("trade_start")

    @property
    def ledger(self) -> Account:
        return self.runner.account

    @property
    def venue(self):
        return self.runner.venue

    def __setstate__(self, state: Dict[str, Any]) -> None:
        if "runner" not in state:        # pickle của PaperBook cũ (trackers) -> engine="tracker" trên cùng trạng thái
            old = state
            runner = Runner(None, old["ledger"], old["books"], old["risk"], old["trade_start"], initial_capital=old["peak_mtm"])
            for k in ("last_close", "last_low", "last_high", "last_open", "peak_mtm", "halted_at", "last_t", "trades", "rejected_for_risk"):
                setattr(runner, k, old[k])
            state = {"symbols": old["symbols"], "runner": runner, "engine": "tracker", "events": None}
        self.__dict__.update(state)
        self.runner.collect = self._collect

    # ── danh mục ──
    def mtm(self) -> Tuple[float, float]:
        return self.runner.mtm()

    def _collect(self, sym: str, e: Dict[str, Any], pos, low: float, high: float) -> None:
        """Ghi lệnh đóng (TickBook ghi đè để giữ thêm PositionModel)."""
        self.runner.record(sym, e, pos, low, high)

    def step_bar(self, t: int, bars: Dict[str, Tuple[float, float, float, float]], sig: Dict[str, List[Dict[str, Any]]],
                 funding: Optional[Dict[str, List[Tuple[int, float]]]] = None) -> List[Dict[str, Any]]:
        """Một nến chạy ở thời điểm t (open_time) — xem Runner.step_bar. -> các lệnh đóng ở nến này."""
        return self.runner.step_bar(t, bars, sig, funding)

    def positions(self) -> List[Dict[str, Any]]:
        return self.runner.positions()
