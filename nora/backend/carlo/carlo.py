# Nguồn: docs/bmad/p9_review_log.md (mục P9.5, P9.10a).
"""Monte Carlo: bootstrap theo khối + kịch bản cực xấu + gate (mọi cổng alpha/sổ đều đọc hằng số ở đây).

Thực hiện:
- Block Bootstrap trên lợi suất NGÀY mark-to-market của OOS — đường vốn ngày đã chứa lỗ treo nên MDD không bị đánh giá thấp.
- Mô phỏng tăng trưởng vốn theo lãi kép thực tế (Compounded Equity: equity *= 1 + r).
- Phân phối xác suất Max Drawdown / lãi cuối và Xác suất Cháy (Risk of Ruin %).
- Xuất dữ liệu biểu đồ phân tán và quantile bands (Fan Chart).
- Sử dụng Local Generator ngẫu nhiên `np.random.default_rng(seed)` an toàn đa luồng.
"""
from typing import Any, Dict, List, Optional

import numpy as np


# ─── Hằng số GATE Monte Carlo (mọi cổng alpha/sổ đều đọc ở đây; KHÔNG nới để có kết quả đẹp) ───────────────
MC_MIN_SIMULATIONS = 10_000        # số kịch bản bootstrap TỐI THIỂU để một kết quả được dùng làm gate (ít hơn -> gate_eligible=False)
MC_MAX_SIMULATIONS = 50_000        # trần cho API Studio (RAM/thời gian)
MC_RUIN_THRESHOLD_PCT = 30.0       # "cháy" = MDD của một đường mô phỏng >= 30%
MC_MAX_RUIN_PCT = 5.0              # P(MDD >= 30%) tối đa 5%
STRESS_MAX_MDD_PCT = 50.0          # MDD của MỌI kịch bản cực xấu phải < 50% (cấu hình được: tham số stress_max_mdd_pct)
# Kịch bản cost_x2 = trừ thêm một lần phí khứ hồi: (taker 0,05% + trượt giá 0,02% của CEX perp) x 2 chiều x VÒNG QUAY ĐO TỪ LỆNH của chính lượt
# chạy đang được stress (danh nghĩa mở / vốn lúc vào lệnh, mỗi ngày — measure_turnover). Nguồn không có lệnh (chỉ chuỗi lợi suất ngày) và
# không có phí do người dùng nhập -> KHÔNG giả định vòng quay: dòng cost_x2 ghi "không đo được vòng quay" và cổng không đạt (check stress_measured).
STRESS_COST_TAKER = 0.0005
STRESS_COST_SLIPPAGE = 0.0002
NOTE_COST_UNMEASURED = "không đo được vòng quay vốn (thiếu lệnh của lượt chạy này) nên không dựng kịch bản chi phí gấp đôi; không dùng vòng quay giả định"
CRASH_CAP = 0.95                   # ngày sập tối đa -95%
STRESS_PATH_POINTS = 72            # số điểm tối đa mỗi đường vẽ trả về cho UI
# Trend thẳng đứng (P2.6): giá đi +40% trong 3 ngày / −30% trong 1 ngày NGƯỢC vị thế lớn nhất từng mở. Lỗ mỗi vị thế:
#   có cắt lỗ theo rủi ro (sizing "risk": danh nghĩa × khoảng SL = rpt × vốn): min(danh nghĩa × biên độ, STRESS_GAP_MULT × rpt × vốn)
#     (giá chạy thẳng -> SL khớp trượt, coi như mất gấp đôi rủi ro kế hoạch);
#   không cắt lỗ (bot DCA/grid kiểu OKX): min(danh nghĩa × biên độ, ký quỹ) — bị thanh lý thì mất hết ký quỹ.
VERTICAL_SURGE_PCT, VERTICAL_SURGE_DAYS = 40.0, 3
VERTICAL_CRASH_PCT = 30.0
STRESS_GAP_MULT = 2.0

STRESS_LABELS_VI = {
    "worst_days_first": "Ngày lỗ tệ nhất đến trước",
    "reversed_order": "Đảo ngược thứ tự lịch sử",
    "crash_day": "Ngày sập (2x ngày xấu nhất) ở đầu",
    "cost_x2": "Chi phí giao dịch gấp đôi",
    "longest_losing_streak_x2": "Chuỗi thua dài nhất lặp 2 lần ở đầu",
    "worst_bootstrap": "Đường bootstrap tệ nhất (MDD lớn nhất)",
    "vertical_surge": "Tăng thẳng đứng +40%/3 ngày ngược vị thế SHORT lớn nhất",
    "vertical_crash": "Sập −30%/1 ngày ngược vị thế LONG lớn nhất",
    "vertical_chain": "Chuỗi liên tiếp: tăng +40%/3 ngày rồi sập −30%, lặp 2 lần",
}
VERTICAL_NAMES = ("vertical_surge", "vertical_crash", "vertical_chain")


# ─── Kịch bản cực xấu (tất định, KHÔNG ngẫu nhiên) + gate ──────────────────────────────────────────────
def _sample_idx(total: int, points: int = STRESS_PATH_POINTS) -> List[int]:
    """Chỉ số bước (0 = vốn đầu) lấy mẫu để vẽ: đều nhau, luôn có bước đầu và cuối."""
    stride = max(1, int(np.ceil(total / points)))
    idx = list(range(0, total + 1, stride))
    if idx[-1] != total:
        idx.append(total)
    return idx


def _path_row(name: str, r, label_vi: Optional[str] = None, max_mdd_pct: float = STRESS_MAX_MDD_PCT,
              with_path: bool = True) -> Dict[str, Any]:
    """Đường vốn lãi kép từ chuỗi lợi suất ngày `r` (thập phân) -> các số đo của MỘT kịch bản.
    Hệ số ngày = max(0, 1 + r): chạm 0 thì vốn ở lại 0 (cháy). mdd_pct/terminal_ret_pct/worst_day_pct tính theo %."""
    r = np.asarray(r, dtype=float)
    eq = np.cumprod(np.maximum(0.0, 1.0 + r))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    mdd = float(((peak - eq) / peak).max() * 100.0)
    ruin = bool(eq.min() <= 0.0)
    row: Dict[str, Any] = {
        "name": name, "label_vi": label_vi or STRESS_LABELS_VI.get(name, name),
        "mdd_pct": round(mdd, 2), "terminal_ret_pct": round(float(eq[-1] - 1.0) * 100.0, 2),
        "worst_day_pct": round(float(r.min()) * 100.0, 2), "days_underwater": int((eq < peak).sum()),
        "ruin": ruin, "days": int(len(r)), "passed": bool(mdd < max_mdd_pct and not ruin),
    }
    if with_path:
        full = np.r_[1.0, eq]
        idx = _sample_idx(len(r))
        row["path"] = {"days": idx, "ret_pct": [round(float(full[i] - 1.0) * 100.0, 2) for i in idx]}
    return row


def longest_losing_run(d) -> np.ndarray:
    """Đoạn ngày LỖ (< 0) liên tiếp dài nhất của chuỗi (gặp ngày >= 0 thì đứt); trùng độ dài thì lấy đoạn xuất hiện trước."""
    d = np.asarray(d, dtype=float)
    best_lo, best_len, lo = 0, 0, None
    for i, x in enumerate(d):
        if x < 0:
            lo = i if lo is None else lo
            if i - lo + 1 > best_len:
                best_lo, best_len = lo, i - lo + 1
        else:
            lo = None
    return d[best_lo:best_lo + best_len].copy()


def _notional(t: Dict[str, Any]) -> float:
    if t.get("notional") is not None:
        return float(t["notional"])
    margin, lev = float(t.get("margin_usd") or 0.0), float(t.get("leverage") or 1.0)
    if margin > 0:
        return margin * lev
    return float(t.get("qty") or 0.0) * float(t.get("avg_price") or t.get("enter_price") or 0.0)


def vertical_exposure(trades: List[Dict[str, Any]], rpt_pct: Optional[float],
                      gap_mult: float = STRESS_GAP_MULT) -> Optional[Dict[str, float]]:
    """Lỗ (phần vốn) nếu trend thẳng đứng xảy ra đúng lúc vị thế ngược chiều MỞ NHIỀU NHẤT (quét theo thời gian, cộng mọi lệnh đang mở).
    trades: [{side, enter_time, close_time, entry_equity, notional | margin_usd+leverage | qty+giá}] (trade_rows / trade_list).
    rpt_pct: rủi ro kế hoạch mỗi lệnh (% vốn) khi chiến lược có cắt lỗ; None = không cắt lỗ (mất tối đa ký quỹ).
    -> {"crash_loss": lỗ LONG khi −30%, "surge_loss": lỗ SHORT khi +40%, "max_long_exposure", "max_short_exposure"} hoặc None (không lệnh)."""
    ev: Dict[str, List] = {"LONG": [], "SHORT": []}
    for t in trades or []:
        eq = float(t.get("entry_equity") or 0.0)
        if eq <= 0 or t.get("enter_time") is None:
            continue
        n = _notional(t) / eq
        move = (VERTICAL_CRASH_PCT if t.get("side") == "LONG" else VERTICAL_SURGE_PCT) / 100.0
        cap = gap_mult * rpt_pct / 100.0 if rpt_pct is not None else n / max(float(t.get("leverage") or 1.0), 1.0)
        loss = min(n * move, cap)
        end = t.get("close_time")
        end = int(end) if end is not None else 2 ** 62
        side = "LONG" if t.get("side") == "LONG" else "SHORT"
        ev[side] += [(int(t["enter_time"]), 1, loss, n), (end, 0, -loss, -n)]   # cùng thời điểm: đóng (0) trước mở (1)
    if not ev["LONG"] and not ev["SHORT"]:
        return None
    out = {}
    for side, key in (("LONG", "crash"), ("SHORT", "surge")):
        cur_l = cur_n = best_l = best_n = 0.0
        for _, _, dl, dn in sorted(ev[side], key=lambda e: (e[0], e[1])):
            cur_l, cur_n = cur_l + dl, cur_n + dn
            best_l, best_n = max(best_l, cur_l), max(best_n, cur_n)
        out[f"{key}_loss"] = round(min(best_l, 1.0), 6)
        out[f"max_{side.lower()}_exposure"] = round(best_n, 4)
    return out


def merge_exposure(rows: List[Optional[Dict[str, float]]]) -> Optional[Dict[str, float]]:
    """Gộp nhiều cửa sổ (vd. các fold OOS): lấy mức xấu nhất từng khoá."""
    rows = [r for r in rows if r]
    return {k: max(r[k] for r in rows) for k in rows[0]} if rows else None


def vertical_sequences(shock: Dict[str, float], scale: float = 1.0) -> Dict[str, np.ndarray]:
    """Chuỗi lợi suất ngày của 3 kịch bản trend thẳng đứng (đặt ở ĐẦU, trước lịch sử)."""
    lc = min(1.0, scale * float(shock.get("crash_loss") or 0.0))
    ls = min(1.0, scale * float(shock.get("surge_loss") or 0.0))
    up = np.full(VERTICAL_SURGE_DAYS, (1.0 - ls) ** (1.0 / VERTICAL_SURGE_DAYS) - 1.0)
    return {"vertical_surge": up, "vertical_crash": np.array([-lc]), "vertical_chain": np.r_[up, -lc, up, -lc]}


def stress_scenarios(daily, scale: float = 1.0, extra_cost_daily: Optional[float] = None,
                     max_mdd_pct: float = STRESS_MAX_MDD_PCT, with_path: bool = True,
                     shock: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """5 kịch bản cực xấu TẤT ĐỊNH dựng từ chính chuỗi lợi suất ngày (`daily` x `scale`); mỗi cái cho một đường vốn.
    (kịch bản thứ 6, worst_bootstrap, lấy từ bootstrap nên do hàm chạy bootstrap thêm vào.)
      worst_days_first          chuỗi xếp TĂNG dần: mọi ngày lỗ trước, tệ nhất trước, rồi phần còn lại (cực xấu theo cấu trúc).
      reversed_order            chuỗi lịch sử đảo ngược.
      crash_day                 một ngày sập = 2 x ngày tệ nhất lịch sử (chặn -95%; không có ngày lỗ thì không sập) ở ĐẦU, rồi lịch sử.
      cost_x2                   mọi ngày có hoạt động (lợi suất != 0) trừ thêm `extra_cost_daily` (phí khứ hồi bổ sung = chi phí gấp đôi).
                                `extra_cost_daily` = (taker+trượt giá) x 2 x vòng quay vốn/ngày ĐO TỪ LỆNH (extra_cost_from_turnover); None = không đo được
                                -> dòng `measured=False` (mdd_pct None, note_vi nêu lý do), KHÔNG dùng hằng số.
      longest_losing_streak_x2  chuỗi lỗ liên tiếp dài nhất lặp 2 lần liền nhau ở ĐẦU, rồi toàn bộ lịch sử (không có ngày lỗ thì giữ nguyên).
    shock (vertical_exposure, tuỳ chọn) -> thêm vertical_surge / vertical_crash / vertical_chain (vertical_sequences) ở ĐẦU, rồi lịch sử.
    Độ dài = số ngày lịch sử (cộng phần chèn thêm), KHÔNG cắt/kéo theo horizon của bootstrap."""
    d = scale * np.asarray(daily, dtype=float)
    if d.size == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để dựng kịch bản cực xấu")
    c = None if extra_cost_daily is None else float(extra_cost_daily)
    crash = max(-CRASH_CAP, 2.0 * float(d.min())) if d.min() < 0 else 0.0
    streak = longest_losing_run(d)
    seqs = {
        "worst_days_first": np.sort(d),
        "reversed_order": d[::-1],
        "crash_day": np.r_[crash, d],
        "cost_x2": None if c is None else np.where(d != 0.0, d - c, d),
        "longest_losing_streak_x2": np.r_[streak, streak, d],
    }
    if shock:
        seqs.update({k: np.r_[v, d] for k, v in vertical_sequences(shock, scale).items()})
    rows = []
    for name, seq in seqs.items():
        if seq is None:   # cost_x2 không đo được vòng quay: không có số giả
            rows.append({"name": name, "label_vi": STRESS_LABELS_VI[name], "measured": False, "mdd_pct": None, "terminal_ret_pct": None,
                         "worst_day_pct": None, "days_underwater": None, "ruin": False, "days": None, "passed": None,
                         "note_vi": NOTE_COST_UNMEASURED})
            continue
        row = _path_row(name, seq, max_mdd_pct=max_mdd_pct, with_path=with_path)
        if name == "cost_x2":
            row["note_vi"] = f"Trừ thêm {c * 100:.3f}%/ngày hoạt động (đo từ vòng quay vốn của lệnh trong lượt chạy)"
        elif name in VERTICAL_NAMES:
            row["note_vi"] = (f"Lỗ LONG khi sập {shock['crash_loss'] * scale * 100:.1f}% vốn, lỗ SHORT khi tăng dựng "
                              f"{shock['surge_loss'] * scale * 100:.1f}% vốn (vị thế ngược chiều lớn nhất từng mở)")
        rows.append(row)
    return rows


def extra_cost_from_turnover(turnover_daily: Optional[float], taker: float = STRESS_COST_TAKER,
                             slippage: float = STRESS_COST_SLIPPAGE) -> Optional[float]:
    """Phí bổ sung/ngày hoạt động cho cost_x2 từ vòng quay ĐO ĐƯỢC (lần vốn/ngày); None (không đo được) -> None."""
    return None if turnover_daily is None else (taker + slippage) * 2.0 * float(turnover_daily)


def measure_turnover(trades: Optional[List[Dict[str, Any]]], n_days: int) -> Dict[str, Any]:
    """Vòng quay vốn đo từ lệnh của lượt chạy: Σ (danh nghĩa mở / vốn lúc vào lệnh) / số ngày. trades: dạng trade_rows / trade_list
    (notional | margin_usd x leverage | qty x giá; entry_equity). Mọi lệnh phải có đủ danh nghĩa và vốn lúc vào, nếu không -> turnover_daily None +
    note (không bỏ lệnh thiếu rồi coi như đo được). trades=None (nguồn không có lệnh) hoặc n_days <= 0 -> None + note. 0 lệnh -> 0.0 (đo được).
    Trả cả `sum`/`days` để gộp nhiều cửa sổ (merge_turnover)."""
    out = {"turnover_daily": None, "note": None, "sum": 0.0, "days": int(n_days), "trades": 0, "measurable": 0}
    if trades is None:
        out["note"] = "không có danh sách lệnh của lượt chạy"
        return out
    if n_days <= 0:
        out["note"] = "không có ngày nào để quy vòng quay theo ngày"
        return out
    total = 0.0
    ok = 0
    for t in trades:
        eq = float(t.get("entry_equity") or 0.0)
        notional = _notional(t)
        if eq > 0 and notional > 0:
            total += notional / eq
            ok += 1
    out.update(sum=total, trades=len(trades), measurable=ok)
    if ok < len(trades):
        out["note"] = f"{len(trades) - ok}/{len(trades)} lệnh thiếu danh nghĩa hoặc vốn lúc vào lệnh"
        return out
    out["turnover_daily"] = total / n_days
    return out


def merge_turnover(parts: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Gộp vòng quay của nhiều cửa sổ (fold OOS): Σ danh nghĩa/vốn chia Σ ngày; bất kỳ cửa sổ nào không đo được -> không đo được."""
    parts = [p if p is not None else {"turnover_daily": None, "note": "cửa sổ không có số đo vòng quay", "sum": 0.0, "days": 0,
                                      "trades": 0, "measurable": 0} for p in parts]
    if not parts:
        return {"turnover_daily": None, "note": "không có cửa sổ nào để đo vòng quay", "sum": 0.0, "days": 0, "trades": 0, "measurable": 0}
    bad = next((p for p in parts if p["turnover_daily"] is None), None)
    days = sum(p["days"] for p in parts)
    base = {"sum": sum(p["sum"] for p in parts), "days": days, "trades": sum(p["trades"] for p in parts),
            "measurable": sum(p["measurable"] for p in parts)}
    if bad is not None or days <= 0:
        return {**base, "turnover_daily": None, "note": (bad or {}).get("note") or "không có ngày nào để quy vòng quay theo ngày"}
    return {**base, "turnover_daily": base["sum"] / days, "note": None}


def evaluate_mc_gate(simulations: int, p_mdd_ge_ruin_pct: Optional[float], stress: Optional[List[Dict[str, Any]]], *,
                     min_simulations: int = MC_MIN_SIMULATIONS, max_ruin_pct: float = MC_MAX_RUIN_PCT,
                     ruin_threshold_pct: float = MC_RUIN_THRESHOLD_PCT, stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
                     ) -> Dict[str, Any]:
    """Gate Monte Carlo (thuần): đạt khi CẢ 4 check qua. Mỗi check trả {label, required, actual, passed}.
      simulations   số kịch bản bootstrap >= min_simulations (không đủ -> gate_eligible=False, gate KHÔNG đạt)
      ruin          P(MDD >= ruin_threshold) <= max_ruin_pct
      stress_mdd    MDD của mọi kịch bản cực xấu (gồm worst_bootstrap) < stress_max_mdd_pct
      stress_ruin   không kịch bản cực xấu nào chạm vốn 0
      stress_measured  không kịch bản nào "không đo được" (cost_x2 thiếu vòng quay) — kịch bản đó bị loại khỏi hai check trên và check này trượt
    Thiếu stress / thiếu P(MDD) -> check tương ứng trượt."""
    def chk(label, required, actual, passed, detail=None):
        c = {"label": label, "required": required, "actual": actual, "passed": bool(passed)}
        if detail:
            c["detail"] = detail
        return c

    all_rows = list(stress or [])
    unmeasured = [x["name"] for x in all_rows if x.get("measured") is False]       # kịch bản không dựng được (cost_x2 thiếu vòng quay)
    rows = [x for x in all_rows if x.get("measured") is not False]
    worst = max(rows, key=lambda x: x["mdd_pct"]) if rows else None
    ruined = [x["name"] for x in rows if x["ruin"]]
    over = [x["name"] for x in rows if x["mdd_pct"] >= stress_max_mdd_pct]
    eligible = int(simulations) >= int(min_simulations)
    checks = {
        "simulations": chk("Số kịch bản bootstrap", f">= {int(min_simulations)}", int(simulations), eligible),
        "ruin": chk(f"P(MDD >= {ruin_threshold_pct:.0f}%) trong bootstrap", f"<= {max_ruin_pct}%", p_mdd_ge_ruin_pct,
                    p_mdd_ge_ruin_pct is not None and p_mdd_ge_ruin_pct <= max_ruin_pct),
        "stress_mdd": chk("MDD tệ nhất trong các kịch bản cực xấu", f"< {stress_max_mdd_pct:g}%", worst["mdd_pct"] if worst else None,
                          bool(worst) and not over, f"{worst['name']}" if worst else "thiếu kịch bản cực xấu"),
        "stress_ruin": chk("Kịch bản cực xấu chạm vốn 0", "không có", len(ruined), bool(rows) and not ruined, ", ".join(ruined) or None),
        "stress_measured": chk("Mọi kịch bản cực xấu đều dựng được từ số đo thật", "đủ", len(unmeasured), not unmeasured,
                               ("không đo được: " + ", ".join(unmeasured)) if unmeasured else None),
    }
    return {"passed": all(c["passed"] for c in checks.values()), "gate_eligible": eligible, "checks": checks, "unmeasured_stress": unmeasured,
            "min_simulations": int(min_simulations), "ruin_max_pct": float(max_ruin_pct),
            "stress_max_mdd_pct": float(stress_max_mdd_pct), "ruin_threshold_pct": float(ruin_threshold_pct)}


GATE_THRESHOLD_KEYS = ("min_simulations", "ruin_max_pct", "stress_max_mdd_pct", "ruin_threshold_pct")


def with_gate_thresholds(mc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Bảo đảm kết quả MC có ĐỦ ngưỡng cổng trong `gate` (giao diện không giữ hằng số dự phòng). Kết quả mới luôn có sẵn (evaluate_mc_gate);
    kết quả cũ thiếu thì lấy từ nơi lưu cùng kết quả (params.ruin_threshold_pct) — không suy đoán: ngưỡng không có nguồn -> None và
    `gate.thresholds_missing` liệt kê khoá + `thresholds_note` nêu lý do (giao diện hiện "—" + lý do)."""
    if not isinstance(mc, dict) or not isinstance(mc.get("gate"), dict):
        return mc
    gate = dict(mc["gate"])
    if gate.get("ruin_threshold_pct") is None:
        gate["ruin_threshold_pct"] = (mc.get("params") or {}).get("ruin_threshold_pct")
    missing = [k for k in GATE_THRESHOLD_KEYS if gate.get(k) is None]
    for k in missing:
        gate[k] = None
    gate["thresholds_missing"] = missing
    gate["thresholds_note"] = ("kết quả cũ không lưu ngưỡng cổng: " + ", ".join(missing)) if missing else None
    return {**mc, "gate": gate}


def strip_paths(rows: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Bỏ điểm vẽ khỏi bảng kịch bản (để lưu bằng chứng gọn)."""
    return [{k: v for k, v in r.items() if k != "path"} for r in rows] if rows is not None else None


# ─── Bootstrap theo ngày ────────────────────────────────────────────────────────────────────────────────
def _daily_bootstrap(d, n: int, block_days: int, horizon_days: int, seed, scale: float, cols=None):
    """Vòng bootstrap ngày dùng chung (giữ NGUYÊN thứ tự RNG: mỗi mô phỏng một lệnh rng.integers).
    -> (mdds, rets, fan_vals|None, chỉ số ngày của đường có MDD lớn nhất). `cols` = cột đường vốn cần lấy cho fan."""
    rng = np.random.default_rng(seed)
    mdds, rets = np.empty(n), np.empty(n)
    fan_vals = np.empty((n, len(cols))) if cols is not None else None
    worst_mdd, worst_idx = -1.0, None
    for k in range(n):
        idx = (rng.integers(0, len(d), horizon_days // block_days + 1)[:, None] + np.arange(block_days)).ravel()[:horizon_days] % len(d)
        eq = np.cumprod(1 + scale * d[idx])
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        mdds[k] = ((peak - eq) / peak).max()
        rets[k] = eq[-1] - 1
        if mdds[k] > worst_mdd:
            worst_mdd, worst_idx = mdds[k], idx
        if fan_vals is not None:
            fan_vals[k] = eq[cols] - 1
    return mdds, rets, fan_vals, worst_idx


def run_monte_carlo_daily(
    daily_returns,
    simulations: int = MC_MIN_SIMULATIONS,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = 30.0,
    seed: int = 1,
    scale: float = 1.0,
) -> Dict[str, Any]:
    """Block bootstrap trên LỢI SUẤT NGÀY mark-to-market (gồm cả lỗ chưa chốt), mô phỏng `horizon_days` ngày.

    Đường vốn ngày đã chứa lỗ treo nên MDD không bị đánh giá thấp.
    `scale` nhân lợi suất ngày (hệ số rủi ro). Thứ tự gọi RNG GIỮ NGUYÊN bản bootstrap của build_strategy_book
    (mỗi lần mô phỏng một lệnh rng.integers) -> cùng seed/scale cho đúng cùng số; đừng vector hoá khi chưa so lại bit.
    Mặc định MC_MIN_SIMULATIONS (10.000): số nhỏ hơn chỉ để thử nhanh, không dùng làm gate."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    mdds, rets, _, _ = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale)
    return _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)


def _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed) -> Dict[str, Any]:
    """Tóm tắt từ MDD/lãi cuối của n lần mô phỏng (dùng chung run_monte_carlo_daily và bản chi tiết -> cùng làm tròn)."""
    return {
        "median_ret_pct": round(float(np.median(rets) * 100), 1),
        "p05_ret_pct": round(float(np.percentile(rets, 5) * 100), 1),
        "mdd_p50_pct": round(float(np.percentile(mdds, 50) * 100), 1),
        "mdd_p95_pct": round(float(np.percentile(mdds, 95) * 100), 1),
        "p_mdd_ge_ruin_pct": round(float((mdds >= ruin_threshold_pct / 100).mean() * 100), 2),
        "simulations": n, "block_days": int(block_days), "horizon_days": int(horizon_days), "seed": seed,
    }


def run_monte_carlo_daily_gate(
    daily_returns,
    simulations: int = MC_MIN_SIMULATIONS,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = MC_RUIN_THRESHOLD_PCT,
    seed: int = 1,
    scale: float = 1.0,
    max_ruin_pct: float = MC_MAX_RUIN_PCT,
    stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
    extra_cost_daily: Optional[float] = None,
    shock: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """MC ngày dạng GATE: `summary` (trùng bit run_monte_carlo_daily) + `stress` (5 kịch bản tất định + worst_bootstrap, không điểm vẽ)
    + `gate` (evaluate_mc_gate). Dùng cho gate WFA danh mục."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    mdds, rets, _, worst_idx = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale)
    summary = _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)
    stress = strip_paths(stress_scenarios(d, scale, extra_cost_daily, stress_max_mdd_pct, shock=shock)
                         + [_path_row("worst_bootstrap", scale * d[worst_idx], max_mdd_pct=stress_max_mdd_pct)])
    return {**summary, "stress": stress, "extra_cost_daily": extra_cost_daily,
            "gate": evaluate_mc_gate(n, summary["p_mdd_ge_ruin_pct"], stress, max_ruin_pct=max_ruin_pct,
                                     ruin_threshold_pct=ruin_threshold_pct, stress_max_mdd_pct=stress_max_mdd_pct)}


def _hist(values, bins: int = 20) -> Dict[str, Any]:
    """Histogram ~`bins` cột: [{lo, hi, count}] (đơn vị của `values`, làm tròn 2 số lẻ)."""
    v = np.asarray(values, dtype=float)
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        hi = lo + 1e-6 if lo == 0 else lo + abs(lo) * 1e-6
    counts, edges = np.histogram(v, bins=bins, range=(lo, hi))
    return {"bins": [{"lo": round(float(edges[i]), 2), "hi": round(float(edges[i + 1]), 2), "count": int(counts[i])}
                     for i in range(len(counts))]}


FAN_STEP_DAYS = 5
FAN_QUANTILES = (5, 25, 50, 75, 95)


def run_monte_carlo_daily_detail(
    daily_returns,
    simulations: int = MC_MIN_SIMULATIONS,
    block_days: int = 5,
    horizon_days: int = 365,
    ruin_threshold_pct: float = 30.0,
    seed: int = 1,
    scale: float = 1.0,
    max_ruin_pct: float = MC_MAX_RUIN_PCT,
    stress_max_mdd_pct: float = STRESS_MAX_MDD_PCT,
    extra_cost_daily: Optional[float] = None,
    shock: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Như run_monte_carlo_daily (CÙNG RNG, CÙNG thứ tự gọi -> `summary` trùng từng bit) nhưng thêm dữ liệu vẽ:
    fan = phân vị 5/25/50/75/95 của đường vốn (% lãi từ đầu) lấy mẫu mỗi FAN_STEP_DAYS ngày, histogram MDD và lãi cuối (%),
    `stress` (6 kịch bản cực xấu, có `path` để vẽ), `worst_path` (= đường worst_bootstrap, mốc ngày theo fan) và `gate` (evaluate_mc_gate;
    `gate.gate_eligible` = False khi số mô phỏng < MC_MIN_SIMULATIONS)."""
    d = np.asarray(daily_returns, dtype=float)
    if len(d) == 0:
        raise ValueError("Cần ít nhất một lợi suất ngày để chạy Monte Carlo")
    n = int(simulations)
    days = sorted({0, *range(FAN_STEP_DAYS, int(horizon_days) + 1, FAN_STEP_DAYS), int(horizon_days)})
    cols = np.asarray([k - 1 for k in days if k > 0], dtype=int)      # đường vốn sau k ngày = eq[k-1]
    mdds, rets, fan_vals, worst_idx = _daily_bootstrap(d, n, block_days, horizon_days, seed, scale, cols)
    summary = _daily_summary(mdds, rets, ruin_threshold_pct, n, block_days, horizon_days, seed)
    q = np.percentile(fan_vals * 100, FAN_QUANTILES, axis=0)
    fan: Dict[str, Any] = {"days": days}
    for name, row in zip(("p5", "p25", "p50", "p75", "p95"), q):
        fan[name] = [0.0] + [round(float(x), 2) for x in row]
    worst = _path_row("worst_bootstrap", scale * d[worst_idx], max_mdd_pct=stress_max_mdd_pct)
    stress = stress_scenarios(d, scale, extra_cost_daily, stress_max_mdd_pct, shock=shock) + [worst]
    gate = evaluate_mc_gate(n, summary["p_mdd_ge_ruin_pct"], stress, max_ruin_pct=max_ruin_pct,
                            ruin_threshold_pct=ruin_threshold_pct, stress_max_mdd_pct=stress_max_mdd_pct)
    return {
        "summary": summary, "fan": fan,
        "mdd_hist": _hist(mdds * 100), "ret_hist": _hist(rets * 100),
        "stress": stress, "worst_path": worst["path"], "gate": gate,
        "params": {"simulations": n, "block_days": int(block_days), "horizon_days": int(horizon_days),
                   "ruin_threshold_pct": float(ruin_threshold_pct), "seed": seed, "scale": float(scale), "n_days": int(len(d)),
                   "extra_cost_daily": extra_cost_daily,
                   **({"shock": shock} if shock else {})},
    }


# Alias for backward compatibility


def bootstrap_daily(daily, scale, n=10_000, block=5, horizon=365, seed=1):  # n = carlo.MC_MIN_SIMULATIONS
    """Block bootstrap lợi suất ngày (nhân `scale` = hệ số rủi ro). Giữ khoá kết quả cũ của build_strategy_book."""
    r = run_monte_carlo_daily(daily, simulations=n, block_days=block, horizon_days=horizon,
                              ruin_threshold_pct=MC_RUIN_THRESHOLD_PCT, seed=seed, scale=scale)
    return {"median_ret_pct": r["median_ret_pct"], "p05_ret_pct": r["p05_ret_pct"], "mdd_p95_pct": r["mdd_p95_pct"],
            "p_mdd_ge_30_pct": r["p_mdd_ge_ruin_pct"]}


# ══════════════════════════════════════════════════════════════════════════
# Ý nghĩa thống kê: DSR, N hiệu dụng.
#
# - DSR: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio". Mọi Sharpe ở đây là Sharpe THEO NGÀY (không quy năm).
#     SR0 = sqrt(V[SR_trials]) * ((1 - γ) * Φ^-1(1 - 1/N) + γ * Φ^-1(1 - 1/(N e)))       (kỳ vọng SR lớn nhất của N lần thử, γ = Euler–Mascheroni)
#     DSR = Φ( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1)/4 * SR²) )      (kurt = kurtosis THÔ, chuẩn = 3)
# - N hiệu dụng (effective_trials): các lần thử gần trùng nhau (lân cận lưới, biến thể regime) không phải phép thử độc lập. Theo López de Prado
#   (gom cụm các chiến lược tương quan), N dùng cho SR0 = số cụm (tương quan lợi suất ngày > rho) trong mẫu top-K, phóng theo tỉ lệ ra cả N.
# ══════════════════════════════════════════════════════════════════════════
import math
from statistics import NormalDist
from typing import Sequence


EULER_GAMMA = 0.5772156649015329

_N01 = NormalDist()


def norm_cdf(z: float) -> float:
    return _N01.cdf(z)


def norm_ppf(p: float) -> float:
    return _N01.inv_cdf(p)


# ── DSR ─────────────────────────────────────────────────────────────────────
def expected_max_sr(n_trials: int, sr_var: float) -> float:
    """SR0: kỳ vọng Sharpe lớn nhất của n_trials lần thử độc lập có phương sai Sharpe sr_var (theo ngày). n <= 1 -> 0."""
    if n_trials <= 1 or not sr_var > 0:
        return 0.0
    g = EULER_GAMMA
    return math.sqrt(sr_var) * ((1.0 - g) * norm_ppf(1.0 - 1.0 / n_trials) + g * norm_ppf(1.0 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(sr: float, n_days: int, skew: float, kurt: float, n_trials: int, sr_var: float) -> Dict[str, float]:
    """DSR = xác suất Sharpe thật > SR0 sau khi hiệu chỉnh số lần thử, độ lệch, kurtosis, độ dài mẫu. -> {dsr, sr0}."""
    sr0 = expected_max_sr(n_trials, sr_var)
    if n_days < 3:
        return {"dsr": 0.0, "sr0": sr0}
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr0) * math.sqrt(n_days - 1) / denom
    return {"dsr": norm_cdf(z), "sr0": sr0}


def trial_sr_variance(srs: Sequence[float]) -> float:
    """Phương sai (ddof=1) của Sharpe theo ngày qua các alpha đã thử của một chiến lược; < 2 alpha -> 0."""
    a = np.asarray([x for x in srs if x is not None and math.isfinite(x)], dtype=float)
    return float(a.var(ddof=1)) if a.size >= 2 else 0.0


EFF_RHO = 0.7   # hai lần thử tương quan lợi suất ngày > 0,7 -> cùng một cụm (không độc lập)


def effective_trials(M: np.ndarray, n_total: int, rho: float = EFF_RHO) -> int:
    """N hiệu dụng: gom cụm tham lam các cột của M (ngày × alpha, thứ tự = xếp hạng giảm dần) — alpha vào cụm có đại diện tương quan > rho,
    không thì mở cụm mới; N_eff = round(số cụm / số cột × n_total), trong [1, n_total]. Mẫu rỗng -> n_total (bảo thủ)."""
    if M.size == 0 or M.shape[1] < 2:
        return max(1, int(n_total))
    M = M[:, M.std(axis=0) > 0]
    k = M.shape[1]
    if k < 2:
        return max(1, int(n_total))
    C = np.corrcoef(M.T)
    reps: List[int] = []
    for j in range(k):
        if not any(C[j, r] > rho for r in reps):
            reps.append(j)
    return int(min(n_total, max(1, round(len(reps) / k * n_total))))
