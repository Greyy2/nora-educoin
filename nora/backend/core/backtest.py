"""Engine duy nhất (P9.4): kernel numba (cache=True), BacktestEngine, PortfolioEngine, tài sản DEX.

Hợp nhất NGUYÊN VĂN từ core/backtest/{kernel,engine,portfolio,dex}.py (xem docs/bmad/p9_review_log.md, mục P9.4 part 1). Đường dẫn cũ là alias (shim).
"""
import contextlib
import io
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

import numpy as np
import pandas as pd
from numba import carray, njit, types
from numba.core import cgutils
from numba.extending import intrinsic

from backend.core.execute import tracker as _execution
from backend.core.models import OrderModel, OrderType, PositionModel, PositionStatus, CapitalLedger, PositionType
from backend.core.execute.tracker import PositionTracker
from backend.core.signal import lag_key, VectorEvaluator, Program
from backend.core.data.loader import CandleLoader
from backend.core.params import FRAME_ORDER, FRAMES, NORA_DEFAULTS, RUN_FRAME, StrategyParams
from backend.core import indicator as kernels
from backend.core.data import shared as shared_data
from backend.utils.lru import ByteLRU, env_mb
from backend.db.data_layout import clean_name, default_data_root, parse_symbol, resolve_asset_dir, split_instrument


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/backtest/kernel.py
#
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
    F_PLANNED, F_PVOL, F_SL, F_TP, F_TRAIL, F_TACT = range(19)
F_DS0 = 19                    # F[:, F_DS0 + j] = bước DCA hiện tại (đã quy đổi theo unit)
F_FIXED = 19
# ── Tham số float P ─────────────────────────────────────────────────────────
P_FEE, P_MAKER, P_SLIP, P_MMR, P_MAXLEV, P_CAPUSE, P_BSL, P_BTP, P_BTR, P_BTA, P_RISK, P_MAXNOT, P_OSP, P_LTHRU = range(14)
P_BS0 = 14                    # P[:, P_BS0 + j] = bước DCA gốc; P[:, P_BS0 + ml + j] = hệ số khối lượng tầng j (ml = số cột tối đa)
P_FIXED = 14                  # P_LTHRU: lệnh limit (DCA, TP) chỉ khớp khi giá đi qua mức bấy nhiêu (tỉ lệ); 0 = chạm là khớp
# ── Tham số int PI ──────────────────────────────────────────────────────────
PI_LONG, PI_PERP, PI_TIMEOUT, PI_COOL, PI_EXTREME, PI_ATR, PI_RISKSZ, PI_NBASE, PI_MAXOPEN, PI_PATH = range(10)
NPI = 10                      # PI_PATH: đường giá trong nến — 0 adverse_first (cũ), 1 ohlc (mặc định), 2 adaptive
# ── Trạng thái int I ────────────────────────────────────────────────────────
I_OPEN, I_PE, I_PX, I_LAYERS, I_ENTRY_T, I_LASTCLOSE, I_HASLC, I_DCAREJ, I_SKIP, I_POS, I_NST, I_BLK, I_DCAOK = range(13)
NI = 13                       # I_DCAOK: 1 = nến này được dồn tầng DCA (điều kiện DCA tại cuối nến trước; không có điều kiện -> luôn 1)
# ── Bộ đếm G ────────────────────────────────────────────────────────────────
G_REJ, G_NPOS, G_NORD, G_NCL, G_OVF, G_RISKMIN, G_ATT, G_HALT, G_RUIN, G_NSMP = range(10)
NG = 10
LG_EQ, LG_RES, LG_PEAK = 0, 1, 2      # LG_PEAK: đỉnh vốn đã chốt (giảm rủi ro theo mức sụt)
# ── Đầu ra vị thế (outF / outI) và lệnh (ordF / ordI) ───────────────────────
(O_ENTER_PRICE, O_CLOSE_PRICE, O_PNL, O_PCT, O_QTY, O_AVG, O_ENTRY_EQ, O_ENTRY_MARGIN, O_ENTRY_NOTIONAL, O_ENTRY_FEE, O_EXIT_FEE,
 O_TOTAL_MARGIN, O_FEES, O_FUNDING, O_MAE, O_MAXP, O_MINP, O_UNIT, O_LEVUSED, O_RISK) = range(20)
NOF = 20
OI_TR, OI_ENTER_T, OI_CLOSE_T, OI_STATUS, OI_LAYERS, OI_REASON, OI_FIRST_ORD, OI_START = range(8)
NOI = 8
OR_PRICE, OR_QTY, OR_FEE = range(3)
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
def _log_order(pidx, t, price, qty, phase, fee, is_exit, liq, ordF, ordI, G):
    j = G[G_NORD]
    if j >= ordF.shape[0]:
        G[G_OVF] = 1
        return
    ordF[j, OR_PRICE] = price
    ordF[j, OR_QTY] = qty
    ordF[j, OR_FEE] = fee
    ordI[j, ORI_POS] = pidx
    ordI[j, ORI_TIME] = t
    ordI[j, ORI_PHASE] = phase
    ordI[j, ORI_EXIT] = is_exit
    ordI[j, ORI_LIQ] = liq
    G[G_NORD] = j + 1


@njit(**_JIT)
def _add_layer(k, t, price, margin, market, reason, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
    if G[G_NPOS] >= outF.shape[0] or G[G_NORD] >= ordF.shape[0]:
        G[G_OVF] = 1
        return False
    long_ = PI[k, PI_LONG] == 1
    if market:
        fill = price * ((1.0 + P[k, P_SLIP]) if long_ else (1.0 - P[k, P_SLIP]))
    else:
        fill = price
    lev = F[k, F_POS_LEV]
    notional = margin * lev
    fee = notional * (P[k, P_FEE] if market else P[k, P_MAKER])
    if margin <= 0.0 or fill <= 0.0 or F[k, F_MU] + margin + F[k, F_FP] + fee > F[k, F_MAXCAP] + 1e-9:
        return False
    amount = margin + fee
    if amount <= 0.0 or amount > (LG[LG_EQ] - LG[LG_RES]) + 1e-9:   # CapitalLedger.reserve (usage = 1,0)
        G[G_REJ] += 1
        return False
    LG[LG_RES] += amount
    F[k, F_RES_HERE] += margin + fee
    qty = notional / fill
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
    _log_order(pidx, t, fill, qty, I[k, I_LAYERS] - 1, fee, 0, 2 if market else 1, ordF, ordI, G)
    I[k, I_OPEN] = 1
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
def _risk_margin(k, P, PI, F, I, LG):
    sl = F[k, F_SL] / 100.0
    cost = 2.0 * (P[k, P_FEE] + P[k, P_SLIP])
    total_mult = _layer_mult_total(k, I[k, I_NST], P)
    eq = LG[LG_EQ]
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
def _close(k, t, raw_price, status, reason, market, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq):
    long_ = PI[k, PI_LONG] == 1
    if market and status != S_LIQ:
        price = raw_price * ((1.0 - P[k, P_SLIP]) if long_ else (1.0 + P[k, P_SLIP]))
    else:
        price = raw_price
    qty = F[k, F_QTY]
    avg = F[k, F_AVG]
    gross = qty * ((price - avg) if long_ else (avg - price))
    exit_fee = qty * price * (P[k, P_FEE] if (market or status == S_LIQ) else P[k, P_MAKER])
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
    if status == S_LIQ:
        liq = 3
    elif market:
        liq = 2
    else:
        liq = 1
    _log_order(pidx, t, price, qty, I[k, I_LAYERS], exit_fee, 1, liq, ordF, ordI, G)
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
    eq = LG[LG_EQ]
    F[k, F_ENTRY_EQ] = eq
    F[k, F_MAXCAP] = eq * P[k, P_CAPUSE]
    budget = _pmin(F[k, F_MAXCAP], LG[LG_EQ] - LG[LG_RES])
    F[k, F_POS_LEV] = P[k, P_MAXLEV]
    F[k, F_PLANNED] = 0.0
    lev = F[k, F_POS_LEV]
    if PI[k, PI_RISKSZ] == 1:
        margin = _risk_margin(k, P, PI, F, I, LG)
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
        v = margin * lev * (F[k, F_SL] / 100.0 + 2.0 * (P[k, P_FEE] + P[k, P_SLIP])) * _layer_mult_total(k, I[k, I_NST], P)
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
            if _add_layer(k, t, dca_level, margin, False, R_DCA, P, PI, F, I, LG, G, outF, outI, ordF, ordI):
                F[k, F_NEXT] = margin
                dca_filled = True
                continue
            I[k, I_DCAREJ] += 1
            I[k, I_NST] = kk
        # (b) chốt lời
        if has_tp and ((p >= need) if long_ else (p <= need)):
            _close(k, t, tp_lv, S_TP, R_TP, False, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
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
@njit(**_JIT)
def portfolio_kernel(PB, BL, PE, tr_book, book_off, P, PI, F, I, cfg_i, cfg_f,
                     outF, outI, ordF, ordI, closeSeq, eqT, eqM, eqW, G, LG, last_px):
    """PB[b] = (t,o,h,l,c,f_t,f_r,idxm,m_a,m_b,m_l,m_h) địa chỉ (m_*: nến 1m trong nến chạy cho khớp "extreme");
    BL[b] = (n_bars, n_funding, mapped, last_t, n_1m); PE[e] = (match, stop, vol, có_vol) (địa chỉ).
    cfg_i = (trade_start, max_positions, max_per_symbol, close_at_end, step_ms, địa chỉ lưới, độ dài lưới); cfg_f = (initial, gross_cap, kill_frac).
    last_px[b] = (close, low, high, open) của nến cuối đã xử lý; G/LG/I/F/outputs cập nhật tại chỗ."""
    n = cfg_i[6]
    grid = carray(_ptr(cfg_i[5]), (n,), np.int64)
    nb = book_off.shape[0] - 1
    nt = PE.shape[0]
    trade_start = cfg_i[0]
    max_pos = cfg_i[1]
    max_per = cfg_i[2]
    close_end = cfg_i[3]
    step = cfg_i[4]
    init_cap = cfg_f[0]
    cap = cfg_f[1]
    kill = cfg_f[2]
    risk_cap = cfg_f[3]                          # trần Σ rủi ro tới SL của vị thế mở (tỉ lệ vốn); 0 = tắt
    thr = cfg_f[4]                               # giảm rủi ro theo mức sụt vốn đã chốt (tỉ lệ); 0 = tắt
    thr_floor = cfg_f[5]
    ffwd = kill == 0.0                           # tua nhanh phút yên tĩnh chỉ khi không có kill switch (cần MTM từng phút)

    # view mảng (không sao chép)
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

    lg = np.full(nb, -1, dtype=np.int64)         # chỉ số lưới của nến thật gần nhất của từng sổ
    lg_i = np.full(nb, -1, dtype=np.int64)       # chỉ số trong mảng của sổ ứng với lg
    f_ptr = np.zeros(nb, dtype=np.int64)
    peak_mtm = init_cap
    has_sample = False
    last_sample = 0
    halted = False
    halted_at = NONE_I
    ruined_at = NONE_I
    busy = False
    act = np.zeros(nt, dtype=np.bool_)         # slot có chạy ở nến này (pha 1 quyết định, pha 2 dùng)
    cl_open = np.zeros(nt, dtype=np.bool_)     # slot đã đóng ở open nến này (pha 1)
    g = 0
    while g < n:
        if G[G_OVF] != 0:
            break
        if (not busy) and (not _any_active(I, nt)):
            if halted:
                land = n
            else:
                land = ts_g if ts_g > g else g
                while land < n and not sig_any[land]:
                    land += 1
            if land > g:
                peak_mtm = _pmax(peak_mtm, LG[LG_EQ])
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
                        lg[b] = j
                        lg_i[b] = ii
                        fp = _upper_abs(Fts[b], Ts[b][ii], 0, BL[b, 1])
                        if fp > f_ptr[b]:
                            f_ptr[b] = fp
                k = g if not has_sample else _lower(grid, last_sample + step, n)
                while k < land:
                    last_sample = grid[k]
                    has_sample = True
                    _sample(last_sample, LG[LG_EQ], LG[LG_EQ], eqT, eqM, eqW, G)
                    k = _lower(grid, last_sample + step, n)
                g = land
                continue
        if ffwd and busy:
            # Tua nhanh qua các phút YÊN TĨNH (không có kill switch nên MTM từng phút không ảnh hưởng gì ngoài mẫu vốn theo giờ):
            # dừng ở phút sớm nhất có việc — mẫu vốn đến hạn, funding của sổ đang có vị thế, tín hiệu vào của tracker phẳng, vị thế mở
            # chạm DCA/SL/trailing/thanh lý/TP/timeout hoặc có tín hiệu thoát. Phút đó xử lý như thường.
            lim = _lower(grid, last_sample + step, n) if has_sample else g
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
                        lg[b] = j
                        lg_i[b] = ii
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
        can_trade = t >= trade_start and not halted
        touched = False
        busy = False
        # Pha 1 — MỞ NẾN (mọi sổ theo thứ tự): funding, rồi từng slot: luật bỏ qua, xét hạn mức (trạng thái LÚC MỞ NẾN: lg/lg_i còn là nến
        # TRƯỚC nên gross theo đóng nến trước, vốn = sổ vốn sau funding + lệnh thoát ở open) và thoát / vào ở open. Chưa sổ nào chạy trong nến.
        for b in range(nb):
            if BL[b, 2] == 0:
                i = g
            else:
                i = Ims[b][g]
                if i < 0:
                    continue
            o = Os[b][i]
            fe = BL[b, 1]
            while f_ptr[b] < fe and Fts[b][f_ptr[b]] <= t:
                rate = Frs[b][f_ptr[b]]
                for k in range(book_off[b], book_off[b + 1]):
                    _apply_funding(k, rate, o, PI, F, I, LG)
                f_ptr[b] += 1
            for k in range(book_off[b], book_off[b + 1]):
                if I[k, I_OPEN] == 0 and I[k, I_PE] == 0 and not Ms[k][i]:
                    act[k] = False
                    continue
                act[k] = True
                can_open = False
                max_new = np.inf
                max_risk = np.inf
                rscale = 1.0
                if can_trade and I[k, I_PE] == 1 and I[k, I_OPEN] == 0:
                    n_open = 0
                    per_b = 0
                    for kk in range(nt):
                        if I[kk, I_OPEN] == 1:
                            n_open += 1
                            if tr_book[kk] == b:
                                per_b += 1
                    blocked = n_open >= max_pos or per_b >= max_per
                    if not blocked:
                        total = 0.0
                        for bb in range(nb):
                            if lg[bb] >= 0:
                                px = Cs[bb][lg_i[bb]]
                            else:
                                continue
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
                    if blocked:
                        G[G_RISKMIN] += 1
                        if I[k, I_BLK] != g - 1:
                            G[G_ATT] += 1
                        I[k, I_BLK] = g
                closed = _on_bar_open(k, t, o, can_open, max_new, max_risk, rscale, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
                cl_open[k] = closed
                if closed and LG[LG_EQ] <= 0.0 and ruined_at == NONE_I:
                    ruined_at = t
        # Pha 2 — TRONG NẾN (mọi sổ theo thứ tự): SL / TP / DCA / trailing / thanh lý + sổ sách cuối nến, rồi lg/lg_i (= nến này).
        for b in range(nb):
            if BL[b, 2] == 0:
                i = g
            else:
                i = Ims[b][g]
                if i < 0:
                    continue
            o = Os[b][i]
            h = Hs[b][i]
            l = Ls[b][i]
            c = Cs[b][i]
            if BL[b, 4] > 0:
                ja = MAs[b][i]
                jb = MBs[b][i]
            else:
                ja = 0
                jb = 0
            for k in range(book_off[b], book_off[b + 1]):
                if not act[k]:
                    continue
                sig = Ms[k][i]
                vol = Vs[k][i] if PE[k, 3] == 1 else np.nan
                gate = Gs[k][i] if PE[k, 5] == 1 else True
                closed = _on_bar_rest(k, t, o, h, l, c, MLs[b], MHs[b], ja, jb, sig and can_trade, Ss[k][i], cl_open[k], vol, gate,
                                      P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
                if I[k, I_OPEN] == 1 or I[k, I_PE] == 1:
                    busy = True
                if closed and (not cl_open[k]) and LG[LG_EQ] <= 0.0 and ruined_at == NONE_I:
                    ruined_at = t
            lg[b] = g
            lg_i[b] = i
            touched = True
        g += 1
        if not touched:
            continue
        if ffwd and has_sample and t - last_sample < step:
            continue                               # không kill switch: MTM chỉ dùng cho mẫu vốn theo giờ
        # _mtm
        mtm = LG[LG_EQ]
        worst = LG[LG_EQ]
        for b in range(nb):
            for k in range(book_off[b], book_off[b + 1]):
                if I[k, I_OPEN] == 1:
                    mtm += _unreal(k, Cs[b][lg_i[b]], PI, F, I)
                    worst += _unreal(k, Ls[b][lg_i[b]] if PI[k, PI_LONG] == 1 else Hs[b][lg_i[b]], PI, F, I)
        peak_mtm = _pmax(peak_mtm, mtm)
        if kill != 0.0 and (not halted) and worst <= peak_mtm * (1.0 - kill):
            halted = True
            halted_at = t
            for b in range(nb):
                for k in range(book_off[b], book_off[b + 1]):
                    I[k, I_PE] = 0
                    if I[k, I_OPEN] == 1:
                        _close(k, t, Cs[b][lg_i[b]], S_CANCEL, R_KILL, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
            mtm = LG[LG_EQ]
            worst = LG[LG_EQ]
            for b in range(nb):
                for k in range(book_off[b], book_off[b + 1]):
                    if I[k, I_OPEN] == 1:
                        mtm += _unreal(k, Cs[b][lg_i[b]], PI, F, I)
                        worst += _unreal(k, Ls[b][lg_i[b]] if PI[k, PI_LONG] == 1 else Hs[b][lg_i[b]], PI, F, I)
        if (not has_sample) or t - last_sample >= step:
            _sample(t, mtm, worst, eqT, eqM, eqW, G)
            last_sample = t
            has_sample = True

    t_end = grid[n - 1]
    for b in range(nb):
        if lg[b] >= 0:
            ii = lg_i[b]
            last_px[b, 0] = Cs[b][ii]
            last_px[b, 1] = Ls[b][ii]
            last_px[b, 2] = Hs[b][ii]
            last_px[b, 3] = Os[b][ii]
        else:
            for q in range(4):
                last_px[b, q] = np.nan
    if close_end == 1:
        for b in range(nb):
            for k in range(book_off[b], book_off[b + 1]):
                if I[k, I_OPEN] == 1:
                    I[k, I_PE] = 0
                    _close(k, BL[b, 3], last_px[b, 3], S_CANCEL, R_END, True, P, PI, F, I, LG, G, outF, outI, ordF, ordI, closeSeq)
    mtm = LG[LG_EQ]
    worst = LG[LG_EQ]
    for b in range(nb):
        for k in range(book_off[b], book_off[b + 1]):
            if I[k, I_OPEN] == 1:
                mtm += _unreal(k, last_px[b, 0], PI, F, I)
                worst += _unreal(k, last_px[b, 1] if PI[k, PI_LONG] == 1 else last_px[b, 2], PI, F, I)
    _sample(t_end, mtm, worst, eqT, eqM, eqW, G)
    G[G_HALT] = halted_at
    G[G_RUIN] = ruined_at


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
def pack_trackers(trackers: List[Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """-> (P, PI, F, I) khởi tạo từ trạng thái BAN ĐẦU của các PositionTracker (mọi chuẩn hoá/kiểm tra tham số do PositionTracker làm)."""
    nt = len(trackers)
    ml = max([1] + [len(tr.base_dca_steps) for tr in trackers])
    P = np.zeros((nt, P_FIXED + 2 * ml))
    PI = np.zeros((nt, NPI), dtype=np.int64)
    F = np.zeros((nt, F_FIXED + ml))
    I = np.zeros((nt, NI), dtype=np.int64)
    for k, tr in enumerate(trackers):
        if tr.is_open or tr.pending_entry or tr.pending_exit:
            raise ValueError("kernel chỉ chạy được từ trạng thái ban đầu của tracker (không mở, không lệnh chờ)")
        if tr.limit_taker or tr.impact_fn is not None:
            raise ValueError("kernel không hỗ trợ limit_taker / impact_fn (AMM) — chạy bằng core/backtest/tick_run.py")
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
        PI[k, PI_MAXOPEN] = int(getattr(tr.params, "max_open_trades", 45) or 45)
        F[k, F_ENTRY_EQ], F[k, F_MAXCAP], F[k, F_POS_LEV] = tr.entry_equity, tr.max_capital, tr.pos_leverage
        F[k, F_PLANNED], F[k, F_PVOL] = tr.planned_risk, np.nan
        F[k, F_SL], F[k, F_TP], F[k, F_TRAIL], F[k, F_TACT] = tr.sl_pct, tr.tp_pct, tr.trail_pct, tr.trail_activation_pct
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
            np.zeros((cap_ord, 3)), np.zeros((cap_ord, 5), dtype=np.int64), np.zeros(cap_pos, dtype=np.int64),
            np.zeros(cap_smp, dtype=np.int64), np.zeros(cap_smp), np.zeros(cap_smp))


# ─── Dựng lại đối tượng ─────────────────────────────────────────────────────
def _build_objects(trackers: List[Any], meta: List[Tuple[str, str]], F: np.ndarray, I: np.ndarray, outs, G: np.ndarray) -> Tuple[list, list]:
    """-> (positions đã đóng theo thứ tự đóng, orders gom theo vị thế đã đóng); đồng thời ghi lại vị thế/lệnh còn mở vào tracker."""
    outF, outI, ordF, ordI, closeSeq = outs[:5]
    npos, nord, ncl = int(G[G_NPOS]), int(G[G_NORD]), int(G[G_NCL])
    seq = _execution._ID_SEQ
    ids = [next(seq) for _ in range(nord)]
    opos = ordI[:nord, ORI_POS]
    perm = np.argsort(opos, kind="stable")
    start = np.concatenate(([0], np.cumsum(np.bincount(opos, minlength=npos)))).tolist() if nord else [0] * (npos + 1)
    perm_l = perm.tolist()
    o_price, o_qty, o_fee = ordF[:nord, OR_PRICE].tolist(), ordF[:nord, OR_QTY].tolist(), ordF[:nord, OR_FEE].tolist()
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
        long_ = trackers[p_tr[p]].is_long
        tr = trackers[p_tr[p]]
        out = []
        for s in range(start[p], start[p + 1]):
            j = perm_l[s]
            exit_ = o_exit[j] == 1
            out.append(OrderModel(
                order_id=ids[j], account_id=tr.account_id, position_id=ids[first_ord[p]], order_time=o_time[j],
                order_type=OrderType.BUY if long_ != exit_ else OrderType.SELL, order_price=o_price[j], qty=o_qty[j],
                phase=o_phase[j], fee_usd=o_fee[j], liquidity=LIQUIDITY[o_liq[j]]))
        return out

    def mk_position(p: int, closed: bool) -> PositionModel:
        tr = trackers[p_tr[p]]
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
    for p in closeSeq[:ncl].tolist():
        closed_pos.append(mk_position(p, True))
        orders.extend(mk_orders(p))
    # vị thế còn mở (close_at_end=False): ghi vào tracker như vòng lặp cũ để open_positions() dùng được
    closed_set = set(closeSeq[:ncl].tolist())
    for k, tr in enumerate(trackers):
        p = int(I[k, I_POS])
        if I[k, I_OPEN] == 1 and p >= 0 and p not in closed_set:
            tr.position = mk_position(p, False)
            tr.orders = mk_orders(p)
            tr.unit_pct = cols["unit"][p]
        else:
            tr.position = None
            tr.orders = []
    return closed_pos, orders


def _writeback(trackers: List[Any], P: np.ndarray, F: np.ndarray, I: np.ndarray) -> None:
    """Trạng thái cuối của kernel -> thuộc tính tracker (cùng giá trị vòng lặp Python để lại)."""
    for k, tr in enumerate(trackers):
        tr.qty, tr.avg, tr.margin_used, tr.fees_paid = (float(F[k, F_QTY]), float(F[k, F_AVG]), float(F[k, F_MU]),
                                                       float(F[k, F_FP]))
        tr.last_fill, tr.next_margin, tr.peak, tr.mae_usd = (float(F[k, F_LAST_FILL]), float(F[k, F_NEXT]),
                                                            float(F[k, F_PEAK]), float(F[k, F_MAE]))
        tr.reserved_here, tr.funding_paid, tr.entry_equity = float(F[k, F_RES_HERE]), float(F[k, F_FUND]), float(F[k, F_ENTRY_EQ])
        tr.max_capital, tr.pos_leverage, tr.planned_risk = float(F[k, F_MAXCAP]), float(F[k, F_POS_LEV]), float(F[k, F_PLANNED])
        tr.pending_vol = float(F[k, F_PVOL])
        tr.sl_pct, tr.tp_pct, tr.trail_pct, tr.trail_activation_pct = (float(F[k, F_SL]), float(F[k, F_TP]),
                                                                       float(F[k, F_TRAIL]), float(F[k, F_TACT]))
        n = int(I[k, I_NST])
        tr.dca_steps = [float(x) for x in F[k, F_DS0:F_DS0 + n]]
        tr.is_open, tr.pending_entry, tr.pending_exit = bool(I[k, I_OPEN]), bool(I[k, I_PE]), bool(I[k, I_PX])
        tr.layer_count, tr.entry_time = int(I[k, I_LAYERS]), int(I[k, I_ENTRY_T])
        tr.last_close_time = int(I[k, I_LASTCLOSE]) if I[k, I_HASLC] else None
        tr.dca_rejected, tr.skipped_no_vol = int(I[k, I_DCAREJ]), int(I[k, I_SKIP])
        tr.max_new_notional = float("inf")


def _round_curve(eqT: np.ndarray, eqM: np.ndarray, eqW: np.ndarray, ns: int) -> List[Dict[str, float]]:
    """Đường vốn: round(x, 4) của Python (đúng làm tròn thập phân, KHÔNG dùng np.round) trên float Python."""
    return [{"time": t, "equity": round(m, 4), "equity_worst": round(w, 4)}
            for t, m, w in zip(eqT[:ns].tolist(), eqM[:ns].tolist(), eqW[:ns].tolist())]


# ─── Danh mục ───────────────────────────────────────────────────────────────
def run_portfolio(eng: Any) -> None:
    """PortfolioEngine.run(): chạy kernel trên eng.books và ghi kết quả vào eng (closed_positions, orders, equity_curve, bộ đếm, tracker)."""
    books = eng.books
    nb = len(books)
    trackers, tr_book, meta, book_off = [], [], [], [0]
    for b, book in enumerate(books):
        for e in book["entries"]:
            trackers.append(e["tracker"])
            tr_book.append(b)
            meta.append((book["symbol"], e["strategy"]))
        book_off.append(len(trackers))
    nt = len(trackers)

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

    P, PI, F, I = pack_trackers(trackers)
    tab = _Tables(nb, nt)
    for b, bk in enumerate(books):
        d = bk["data"]
        last_t = int(d["t"][-1]) if len(d["t"]) else t_end
        tab.book(b, d["t"], d["o"], d["h"], d["l"], d["c"], d["f_t"], d["f_r"], last_t, idxms[b], d.get("minute"))
    for k in range(nt):
        e = books[tr_book[k]]["entries"][k - book_off[tr_book[k]]]
        tab.entry(k, e["match"], e["stop"], e["vol"], e.get("dca"))
    cfg_i = np.array([eng.trade_start_ts, risk.max_positions, risk.max_per_symbol, 1 if eng.close_at_end else 0,
                      eng.MTM_SAMPLE_MINUTES * 60_000, tab.addr(grid), n], dtype=np.int64)
    cfg_f = np.array([eng.initial_capital, risk.max_gross_exposure, kill, float(risk.max_open_risk_pct or 0.0) / 100.0,
                      float(risk.dd_throttle_pct or 0.0) / 100.0, float(risk.dd_throttle_floor)])
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

    eng.closed_positions, eng.orders = _build_objects(trackers, meta, F2, I2, outs, G)
    eng.equity_curve = _round_curve(outs[5], outs[6], outs[7], int(G[G_NSMP]))
    _writeback(trackers, P2, F2, I2)
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
            _, pairs = sub._make_trackers(book["symbol"], sub.ledger)
            entries = []
            for (_st, tr), e0 in zip(pairs, book["entries"]):
                if BacktestEngine.vol_column(tr) != BacktestEngine.vol_column(e0["tracker"]):
                    raise ValueError("run_many: ghi đè không được đổi exit_unit / atr_frame / atr_period (đổi cột tín hiệu ATR)")
                entries.append({**e0, "tracker": tr})
            sub.books.append({**book, "entries": entries, "f_idx": 0})
        run_portfolio(sub)
        out.append(sub.get_results())
    return out


# ─── Đơn tài sản ────────────────────────────────────────────────────────────
def run_backtest(eng: Any) -> None:
    """BacktestEngine.run() (sau khi đã nạp dữ liệu): dựng ma trận kernel đa khung, tính tín hiệu bằng VectorEvaluator rồi chạy kernel."""
    import time
    from backend.core.signal import VectorEvaluator, lag_key
    eng.closed_positions, eng.orders, eng.equity_curve = [], [], []
    print(f"Bắt đầu chạy backtest cho {eng.symbol} ({len(eng.df_base)} nến {eng.base_frame})...")
    started = time.time()
    df1, cols = eng._build_matrix()
    n = len(df1)

    def get(frame, column, lag):
        return cols.get(f"{frame}|{lag_key(column, lag)}", np.full(n, np.nan))

    vec = VectorEvaluator(n, get)
    signals = [(vec.tree(tr.match_tree), vec.tree(tr.stop_tree), vec.tree(tr.dca_tree) if tr.dca_tree else None) for tr in eng.trackers]
    vols = [cols.get(eng.vol_column(tr)) if eng.vol_column(tr) else None for tr in eng.trackers]
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
    trackers = eng.trackers
    nt, n = len(trackers), len(t)
    if n == 0:
        return
    P, PI, F, I = pack_trackers(trackers)
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
    meta = [(eng.symbol, "") for _ in trackers]
    eng.closed_positions, eng.orders = _build_objects(trackers, meta, F2, I2, outs, G)
    eng.equity_curve = _round_curve(outs[5], outs[6], outs[7], int(G[G_NSMP]))
    _writeback(trackers, P2, F2, I2)
    eng.ledger.equity, eng.ledger.reserved, eng.ledger.peak = float(LG[LG_EQ]), float(LG[LG_RES]), float(LG[LG_PEAK])
    eng.ledger.rejected += int(G[G_REJ])
    eng.ruined_at = None if G[G_RUIN] == NONE_I else int(G[G_RUIN])


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/backtest/engine.py
#
# Engine mô phỏng backtest (1m thực thi + kernel đa khung).
#
# Luồng:
# 1. Nạp nến 1m (kèm is_filled) và các khung được AST tham chiếu (luôn có 4h để tương thích).
# 2. Tính kernel (backend/core/signals/kernels.py) trên nến ĐÃ ĐÓNG của từng khung; kernel 1m chỉ
#    tính trên các phút CÓ giao dịch (nến điền không phải một quan sát).
# 3. Ghép vào dòng thời gian 1m: nến 1m đóng lúc T chỉ thấy nến khung F đã đóng tại thời điểm <= T
#    (merge_asof theo decision_time = open_1m + 1m và avail_time = open_F + độ dài F).
# 4. Tính tín hiệu match/stop của từng flow bằng VectorEvaluator (cùng ngữ nghĩa LogicEvaluator).
# 5. Vòng lặp khớp lệnh theo từng nến 1m có giao dịch (backtest/execution.py).
# 6. Đường vốn mark-to-market (lấy mẫu mỗi giờ + mỗi lần đóng lệnh) để đo sụt giảm cả phần lỗ treo.
# ══════════════════════════════════════════════════════════════════════════

FRAME_MS: Dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000,
}
LEGACY_4H_COLUMNS = {"atr", "atr14", "atr17", "atr20", "kup17_05", "kmid17_05", "klo17_05",
                     "kup20_15", "kmid20_15", "klo20_15"}
BASE_COLS = ("open", "high", "low", "close", "volume")
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
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0, base_frame: str = "1m"):
        if base_frame not in FRAME_MS:
            raise ValueError(f"Khung chạy không hợp lệ: {base_frame!r} (có: {list(FRAME_MS)})")
        self.base_frame = base_frame   # khung nến dùng để MÔ PHỎNG (khớp lệnh, SL/TP theo high/low của nến này)
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

        self.trackers: List[PositionTracker] = []
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
        if len(self.trackers) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")
        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast.get("type", "") or params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT
        self.trackers.append(PositionTracker(
            account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol, flow_name=flow_name,
            params=params, pos_type=pos_type, initial_capital=self.initial_capital, ledger=self.ledger,
        ))

    def _refs_by_frame(self) -> Dict[str, Set[Tuple[str, int]]]:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for frame, refs in (getattr(self, "extra_refs", None) or {}).items():   # vd. đặc trưng regime (core/regime)
            by_frame.setdefault(frame, set()).update(refs)
        for tracker in self.trackers:
            for frame, column, lag in (collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree)
                                       | collect_field_refs(tracker.dca_tree)):
                by_frame.setdefault(frame, set()).add((column, lag))
            if tracker.exit_unit == "atr":  # ATR% cho SL/TP/trailing theo biến động
                by_frame.setdefault(tracker.atr_frame, set()).add((f"natr_{tracker.atr_period}", 0))
        return by_frame

    @staticmethod
    def vol_column(tracker: PositionTracker) -> Optional[str]:
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

    def load_data(self):
        refs = self._refs_by_frame()
        self.check_frames(refs)
        base = self.base_frame
        warm = self._warmup_ms(base, refs.get(base, set()))
        loader = CandleLoader(self.symbol, frame=base, use_cache=True)
        # df_base = nến của KHUNG CHẠY (mặc định 1m)
        self.df_base = self._prepare_candles(loader.load_data(self.start_ts - warm, self.end_ts))
        # chỉ báo trên chính khung chạy tính từ đầu lịch sử (gốc cố định) -> cần cả lịch sử khi có cột của khung chạy
        self.df_base_hist = loader.load_data(HISTORY_START, self.end_ts) if refs.get(base) else None
        if self.trade_start_ts < self.start_ts:
            self.trade_start_ts = self.start_ts

        self.load_frames(refs)
        if any(tr.market == "perp" for tr in self.trackers):
            self.funding = self._load_funding()

    def minute_path(self, open_time: np.ndarray) -> Dict[str, np.ndarray]:
        """Đường giá 1m bên trong từng nến chạy (khung chạy > 1m) — cho khớp "extreme" đúng ngữ nghĩa 1m: lệnh stop khớp ở giá xấu nhất của
        NẾN 1m ĐẦU TIÊN chạm mức, không phải của cả nến 15m/1h/4h (quá bi quan, phụ thuộc khung chạy).
        -> {"m_a", "m_b": int64 (n) — nến chạy i gồm nến 1m [m_a[i], m_b[i]), "m_l", "m_h": float64}. Khung chạy 1m: mảng rỗng."""
        t = np.asarray(open_time, dtype="int64")
        if self.base_frame == "1m" or len(t) == 0:
            return {"m_a": np.zeros(0, dtype="int64"), "m_b": np.zeros(0, dtype="int64"), "m_l": np.zeros(0), "m_h": np.zeros(0)}
        step = FRAME_MS[self.base_frame]
        m1 = CandleLoader(self.symbol, frame="1m", use_cache=False).load_data(int(t[0]), int(t[-1]) + step - 1,
                                                                              columns=["open_time", "high", "low", "is_filled"])
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
            loader = CandleLoader(self.symbol, frame=frame, use_cache=True)
            df = self._prepare_candles(loader.load_data(HISTORY_START, self.end_ts))
            self.frames[frame] = self._enrich_4h(df) if frame == "4h" else df
        self.df_4h = self.frames.get("4h")

    def _load_funding(self) -> Optional[pd.DataFrame]:
        """funding.pkl của instrument perp (nếu symbol là BTC@perp). Không có -> None (ghi rõ trong kết quả)."""
        import os
        from backend.db.local_pkl import resolve_symbol_dir
        path = resolve_symbol_dir(self.symbol)
        file = os.path.join(path, "funding.pkl") if path else None
        if not file or not os.path.isfile(file):
            return None
        df = pd.read_pickle(file)
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
                src = CandleLoader(self.symbol, frame=frame, use_cache=True).load_data(HISTORY_START, self.end_ts)
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
        """Chạy backtest bằng kernel numba (core/backtest/kernel.py) — kết quả trùng từng bit với vòng lặp Python cũ (test/reference_engine.py)."""
        if self.df_base is None or self.df_base.empty:
            return
        run_backtest(self)

    def get_results(self):
        return {"positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
                "ruined_at": getattr(self, "ruined_at", None), "final_equity": self.ledger.equity,
                "rejected_for_capital": self.ledger.rejected,
                "dca_layers_rejected": sum(tr.dca_rejected for tr in self.trackers),
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
        for column in BASE_COLS:
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
    return getattr(eng, "base_frame", "1m") != "1m" and any(getattr(tr, "stop_fill", "level") == "extreme" for tr in getattr(eng, "trackers", []))


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/backtest/portfolio.py
#
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
        d = dict(d or {})
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# Bộ nhớ đệm dữ liệu theo tiến trình: (symbol, start, end, refs, perp) -> mảng giá + cột kernel + funding.
# Khi tối ưu ngưỡng tín hiệu / tham số vị thế, cột kernel không đổi nên chỉ tính một lần.
# Giới hạn theo BYTE (NORA_DATA_CACHE_MB, mặc định 1500 MB), có khoá cho API đa luồng.
_DATA_CACHE = ByteLRU(env_mb("NORA_DATA_CACHE_MB", 1500))


def data_cache_clear() -> None:
    """Xóa toàn bộ _DATA_CACHE — gọi giữa các chiến lược ứng viên để giải phóng RAM."""
    _DATA_CACHE.clear()


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
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True, base_frame: str = "1m"):
        """base_frame: khung nến dùng để mô phỏng (1m mặc định; 15m/1h/4h chạy nhanh hơn nhiều, khung tín hiệu phải >= khung chạy).
        strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (backend/core/data/shared.py); mặc định env NORA_SHARED_DATA_DIR.
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
    def _make_trackers(self, symbol: str, ledger: CapitalLedger) -> Tuple[BacktestEngine, List[Tuple[Dict, PositionTracker]]]:
        from backend.core.params import build_params
        eng = BacktestEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital, base_frame=self.base_frame)
        eng.ledger = ledger
        pairs = []
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            if st.get("regime"):   # đặc trưng regime đi qua cùng bộ máy căn khung với tín hiệu
                from backend.core.regime.classifier import REFS
                eng.extra_refs = REFS
            name = f"{st['side']}_{st['id']}"
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, symbol=symbol))
            pairs.append((st, eng.trackers[-1]))
        return eng, pairs

    @staticmethod
    def _refs_signature(eng: BacktestEngine):
        return tuple(sorted((f, tuple(sorted(r))) for f, r in eng._refs_by_frame().items()))

    def _cache_key(self, symbol: str, eng: BacktestEngine) -> tuple:
        return (symbol, self.start_ts, self.end_ts, self._refs_signature(eng), any(tr.market == "perp" for tr in eng.trackers),
                self.base_frame, needs_minute_path(eng))

    def _build_symbol_data(self, eng: BacktestEngine, only: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Dựng `data` của một tài sản (nến thật 1m + cột kernel + funding), không đụng cache.
        only: chỉ tính các cột này (dữ liệu dùng chung điền phần còn thiếu — core/data/shared.fill)."""
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
        """Dữ liệu qua kho dùng chung (shared_dir, core/data/shared.py): nền mmap + cột chỉ báo tính sẵn theo khung, căn theo chỉ số
        dùng chung. Thiếu phần nào thì tự tính ĐÚNG phần đó, ghi vào kho (tiến trình khác dùng lại) rồi đọc lại.
        Bằng từng bit với _build_symbol_data. None nếu tài sản không có 1m.pkl (dựng như thường)."""
        from backend.core.data.loader import CandleLoader
        p = shared_data.plan(eng)
        if p is None:
            return None
        data = shared_data.load(self.shared_dir, p)
        if data is not None:
            return data
        shared_data.fill(self.shared_dir, self, eng, p)
        eng.df_base, eng.df_base_hist, eng.frames, eng.df_4h, eng.funding = None, None, {}, None, None   # như khi đọc thẳng kho
        CandleLoader.clear_cache()
        return shared_data.load(self.shared_dir, p)

    def _load_symbol(self, symbol: str, eng: BacktestEngine) -> Dict[str, Any]:
        if self.shared_dir:  # mmap chỉ đọc dùng chung — KHÔNG đưa vào _DATA_CACHE (không nhân bản RAM)
            data = self._load_shared(eng)
            if data is not None:
                return data
        key = self._cache_key(symbol, eng)
        if self.use_cache:
            cached = _DATA_CACHE.get(key)
            if cached is not None:
                return cached
        data = self._build_symbol_data(eng)
        if self.use_cache:
            arrays = ([data[k] for k in ("t", "o", "h", "l", "c", "f_t", "f_r")] + list(data["cols"].values())
                      + list((data.get("minute") or {}).values()))
            _DATA_CACHE.put(key, data, sum(a.nbytes for a in arrays))
        return data

    def load_data(self) -> None:
        self.books = []
        for sym in self.symbols:
            eng, pairs = self._make_trackers(sym, self.ledger)
            if not pairs:   # không chiến lược nào chạy trên tài sản này (chỉ xảy ra khi dùng khoá "symbols")
                continue
            # Cổng chất lượng dữ liệu BẮT BUỘC (synthetic / sai sha256 / thiếu dữ liệu -> từ chối); có cache theo file nên rẻ khi gọi lại.
            # Tiến trình cha của CLI đã gọi trước khi fork pool -> worker thừa kế cache, không đọc lại 1m.
            from backend.core.data.quality_gate import require_data_ok
            require_data_ok([sym])
            data = self._load_symbol(sym, eng)
            n = len(data["t"])
            cols = data["cols"]
            vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))
            labels = None
            if any(st.get("regime") for st, _ in pairs):
                from backend.core.regime.classifier import classify, profile_cfg
                cfg = profile_cfg(next((st["regime"].get("classifier") for st, _ in pairs if st.get("regime")), None))
                labels = classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), data["t"], cfg)
            entries = []
            for st, tr in pairs:
                vcol = BacktestEngine.vol_column(tr)
                match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
                if labels is not None and st.get("regime"):   # lọc tín hiệu vào theo regime + cầu chì thoát khi sốc ngược chiều
                    from backend.core.regime.classifier import masks_for
                    allowed, fuse = masks_for(st, st["side"], labels)
                    match = match & allowed
                    if fuse is not None:
                        stop = stop | fuse
                entries.append({
                    "strategy": st["id"], "tracker": tr, "match": match, "stop": stop,
                    "vol": cols.get(vcol) if vcol else None, "regime": labels,
                    "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None,   # điều kiện dồn tầng (None = luôn được dồn)
                })
            self.books.append({"symbol": sym, "data": data, "entries": entries, "f_idx": 0})

    # ─── Giới hạn rủi ro ────────────────────────────────────────────────────
    def run(self) -> None:
        """Chạy cả lần backtest bằng kernel numba (core/backtest/kernel.py): cùng ngữ nghĩa, kết quả trùng từng bit với vòng lặp Python cũ
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
                tr = e["tracker"]
                if not tr.is_open or tr.qty <= 0 or tr.position is None or mark is None or mark != mark:
                    continue
                out.append({"symbol": book["symbol"], "strategy": e["strategy"], "side": tr.pos_type.name, "qty": tr.qty,
                            "entry_price": tr.avg, "mark_price": float(mark), "notional": tr.qty * float(mark),
                            "unrealized_pnl": tr.unrealized_pnl_usd(float(mark)), "opened": int(tr.position.enter_time),
                            "margin_usd": tr.margin_used, "leverage": tr.pos_leverage})
        return out

    def get_results(self) -> Dict[str, Any]:
        by_strategy, by_symbol = aggregate_positions(self.closed_positions)
        skipped = sum(e["tracker"].skipped_no_vol for b in self.books for e in b["entries"])
        dca_rejected = sum(e["tracker"].dca_rejected for b in self.books for e in b["entries"])
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
# P9.4 — nguyên văn từ core/backtest/dex.py
#
# Tài sản DEX trong backtest: nhận diện ký hiệu (không trộn với perp), metadata pool (phí, loại, mạng, độ phủ tick), vị thế spot-LONG và cửa sổ tick.
#
# DEX là spot AMM: không đòn bẩy, không bán khống -> chỉ chạy chân LONG (market="spot", leverage=1). Mọi số của pool (phí, loại, mạng) đọc từ
# manifest.json["ticks"] / dex_pool.json["onchain"] của tài sản — không có giá trị mặc định theo pool; thiếu phí -> từ chối.
# ══════════════════════════════════════════════════════════════════════════

SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k


def is_dex_symbol(symbol: str, data_root: Optional[str] = None) -> bool:
    """'dex:AERO' -> DEX; 'BTC@perp' / 'cex:...' -> không; tên trần: perp có dữ liệu thì là perp (tương thích cũ), không thì DEX nếu có dex/<TÊN>."""
    if split_instrument(symbol)[1]:
        return False
    venue, name = parse_symbol(symbol)
    if venue:
        return venue == "dex"
    root = data_root or default_data_root()
    if resolve_asset_dir(f"cex:{name}@perp", data_root=root):
        return False
    return os.path.isdir(os.path.join(root, "dex", name))


def classify_symbols(symbols: List[str], data_root: Optional[str] = None) -> Tuple[List[str], str]:
    """Ký hiệu người dùng -> (ký hiệu engine, venue): perp -> 'BTC@perp' (như cũ); DEX -> 'dex:AERO'. Trộn perp với DEX -> ValueError."""
    dex = [is_dex_symbol(s, data_root) for s in symbols]
    if any(dex) and not all(dex):
        raise ValueError("không chạy chung tài sản perp (CEX) với tài sản DEX trong một lần backtest — chọn một loại")
    if all(dex) and dex:
        out = []
        for s in symbols:
            q = f"dex:{parse_symbol(s)[1]}"
            if q not in out:
                out.append(q)
        return out, "dex"
    return [s if "@" in s else f"{s}@perp" for s in symbols], "cex"


def require_perp(symbols: List[str], what: str) -> None:
    """WFA / phễu chỉ chạy perp: tài sản DEX (spot AMM, dữ liệu ngắn) chưa có quy trình kiểm định -> từ chối rõ ràng."""
    bad = [s for s in symbols if is_dex_symbol(str(s))]
    if bad:
        raise ValueError(f"{what} chưa hỗ trợ tài sản DEX {bad}: chỉ perp (CEX). Backtest đơn (book_backtest) có hỗ trợ DEX")


def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str]) -> None:
    from backend.core.strategy.book import BY_ID
    short = [i for i in strategy_ids if BY_ID[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def pool_info(symbol: str, data_root: Optional[str] = None) -> Dict[str, Any]:
    """Metadata pool của tài sản DEX: symbol (hiển thị), qualified, network, fee_rate (+ nguồn), stable, pool_type, ticks (manifest["ticks"] hoặc None).
    Phí: manifest["ticks"]["fee_rate"], không có thì dex_pool.json["onchain"]["fee_rate"]; null ở cả hai -> ValueError (không đoán phí)."""
    name = clean_name(parse_symbol(symbol)[1])
    path = resolve_asset_dir(f"dex:{name}", data_root=data_root or default_data_root())
    if not path:
        raise ValueError(f"không có tài sản DEX '{name}' trong kho dữ liệu")
    manifest, onchain = _read_json(os.path.join(path, "manifest.json")), _read_json(os.path.join(path, "dex_pool.json")).get("onchain") or {}
    ticks = manifest.get("ticks") if isinstance(manifest.get("ticks"), dict) else None
    src = "manifest.ticks.fee_rate"
    fee = (ticks or {}).get("fee_rate")
    if fee is None:
        fee, src = onchain.get("fee_rate"), "dex_pool.json onchain.fee_rate"
    if fee is None:
        raise ValueError(f"{name}: chưa xác minh được phí pool on-chain (fee_rate = null) — không thể tính chi phí AMM; crawl lại metadata pool")
    pick = lambda k: (ticks or {}).get(k) if (ticks or {}).get(k) is not None else onchain.get(k)   # noqa: E731
    return {"symbol": name, "qualified": f"dex:{name}", "network": (ticks or {}).get("network") or manifest.get("network"), "fee_rate": float(fee),
            "fee_source": src, "stable": bool(pick("stable")), "pool_type": pick("pool_type"), "ticks": ticks}


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
# P9.4 part 2 — nguyên văn từ core/strategy/pydsl/profiles.py (phần dựng kế hoạch; hằng số profile ở core/params.py)
#
# Thực thi chương trình DSL (docs/bmad/p7_python_strategies.md §5): chương trình đã biên dịch -> chiến lược của PortfolioEngine.
#
# Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
# cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).
#
# Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (core/signals/kernels.register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
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


def base_name(symbol: str) -> str:
    from backend.crawl.store import parse_symbol, split_instrument
    return parse_symbol(split_instrument(symbol)[0])[1]


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
               run_frame: Optional[str] = None, exact_id: bool = False) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id)."""
    from backend.core.strategy import book as sb
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
    pos = {**sb.BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    names = list(dict.fromkeys(base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(sb.RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core.params import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)
