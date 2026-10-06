"""Vòng lặp trong của engine backtest (numba) — thay vòng lặp Python từng phút của PortfolioEngine / BacktestEngine.

KHÔNG phải một engine thứ hai: đây là phần thực thi của CHÍNH engine (PortfolioEngine.run / BacktestEngine.run gọi run_portfolio / run_backtest ở cuối file).
Ngữ nghĩa là bản dịch NGUYÊN VĂN từ execution.PositionTracker (on_bar/_intrabar/_open/_add_layer/_close/_risk_margin/apply_funding),
CapitalLedger và vòng lặp run() (rủi ro danh mục, kill switch, bỏ qua phút rảnh, lấy mẫu vốn theo giờ). Kết quả BIT-IDENTICAL với bản Python
(test/test_kernel_parity.py so với test/reference_engine.py + golden snapshot).

Quy tắc giữ bit-identical:
- Cùng thứ tự phép toán float; KHÔNG dùng fastmath (LLVM không gộp FMA); mọi phép chia/nhân/cộng giữ nguyên thứ tự kết hợp của bản Python.
- max()/min() của Python: `max(a,b)` = `b if b > a else a`, `min(a,b)` = `b if b < a else a` (khác nhau ở -0.0/NaN) -> _pmax/_pmin.
- Mọi phép làm tròn `round(x, 4)` (đường vốn) làm ở phần Python cuối file, không làm trong hàm njit.
- Trạng thái mỗi tracker nằm trong mảng F (float) / I (int); tham số trong P / PI; sổ vốn LG; bộ đếm G; kết quả (vị thế, lệnh, mẫu vốn) ghi vào
  mảng cấp sẵn rồi phần Python cuối file dựng lại PositionModel/OrderModel. Tràn dung lượng -> G[G_OVF]=1 và Python chạy lại với dung lượng gấp 4.
- Mảng dữ liệu (t/o/h/l/c/funding/tín hiệu) truyền bằng bảng con trỏ (không sao chép, không chuyên biệt hoá numba theo số tài sản/chiến lược).
- error_model='numpy': chia cho 0 cho inf/NaN thay vì ném ZeroDivisionError (tham số hợp lệ không bao giờ chia cho 0).
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from numba import carray, njit, types
from numba.core import cgutils
from numba.extending import intrinsic

from backend.core.execute import tracker as _execution
from backend.core.execute.models import OrderModel, OrderType, PositionModel, PositionStatus

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
    from backend.core.backtest.engine import BacktestEngine
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
    from backend.core.signals.evaluator import VectorEvaluator, lag_key
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
