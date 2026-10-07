"""Chuỗi theo giai đoạn (train / test / toàn kỳ) cho biểu đồ, TÍNH HẾT ở backend trên dữ liệu ngày đầy đủ (docs/bmad/p8_education_user_alpha.md §3.7).

`stage_block` dựng một giai đoạn từ đường vốn ngày (+ benchmark cùng lưới): equity, pnl (so với điểm đầu giai đoạn), drawdown_pct (<= 0, đỉnh chạy từ đầu
giai đoạn), ret_pct (lợi suất ngày, phần tử 0 = 0 vì không phải ngày giao dịch), benchmark {equity, pnl}.
`downsample_stage` CHỈ để vẽ: gom nhóm `step` điểm liên tiếp (điểm 0 đứng riêng) rồi lấy từ các số ĐÃ TÍNH: nhãn thời gian/equity/pnl = điểm cuối nhóm,
drawdown = đáy nhóm, ret_pct = lãi kép các ngày trong nhóm (đúng bằng vốn cuối nhóm / vốn cuối nhóm trước − 1). Có thể gọi lại nhiều lần (khối ghi
`downsample` = {step, source_points, points, rule}); giao diện không tính lại số nào, chỉ vẽ.
"""
from typing import Any, Dict, List, Optional

import numpy as np

RULE = "nhãn/equity/pnl = điểm cuối nhóm; drawdown_pct = đáy nhóm; ret_pct = lãi kép trong nhóm; điểm đầu đứng riêng"


def _r(a, d: int) -> List[float]:
    return [round(float(x), d) for x in a]


def stage_block(times_ms, equity, bench_equity=None, bench_label: Optional[str] = None) -> Dict[str, Any]:
    """times_ms: nhãn ms (nửa đêm UTC), trả về nhãn giây. bench_equity: cùng lưới thời gian hoặc None."""
    t = np.asarray(times_ms, dtype="int64")
    eq = np.asarray(equity, dtype="float64")
    peak = np.maximum.accumulate(eq)
    ret = np.zeros(eq.shape[0])
    ret[1:] = (eq[1:] / eq[:-1] - 1.0) * 100.0
    out: Dict[str, Any] = {
        "times": [int(x // 1000) for x in t], "equity": _r(eq, 2), "pnl": _r(eq - eq[0], 2),
        "drawdown_pct": _r((eq / peak - 1.0) * 100.0, 6), "ret_pct": _r(ret, 6), "benchmark": None,
        "downsample": {"step": 1, "source_points": int(t.shape[0]), "points": int(t.shape[0]), "rule": RULE},
    }
    if bench_equity is not None:
        be = np.asarray(bench_equity, dtype="float64")
        out["benchmark"] = {"equity": _r(be, 2), "pnl": _r(be - be[0], 2), "label": bench_label}
    return out


def _groups(n: int, step: int) -> List[slice]:
    return [slice(0, 1)] + [slice(i, min(n, i + step)) for i in range(1, n, step)]


def downsample_stage(block: Optional[Dict[str, Any]], max_points: int) -> Optional[Dict[str, Any]]:
    if not block:
        return block
    n = len(block["times"])
    prev = block.get("downsample") or {"step": 1, "source_points": n}
    if n <= max_points or n < 3:
        return block
    step = int(np.ceil((n - 1) / (max_points - 1)))
    gs = _groups(n, step)
    last = [g.stop - 1 for g in gs]

    def at_last(v: List[float]) -> List[float]:
        return [v[i] for i in last]

    ret = block["ret_pct"]
    out = dict(block)
    out["times"] = at_last(block["times"])
    out["equity"] = at_last(block["equity"])
    out["pnl"] = at_last(block["pnl"])
    out["drawdown_pct"] = [min(block["drawdown_pct"][g]) for g in gs]
    out["ret_pct"] = [round((float(np.prod(1.0 + np.asarray(ret[g]) / 100.0)) - 1.0) * 100.0, 6) if g.start else 0.0 for g in gs]
    b = block.get("benchmark")
    if b:
        out["benchmark"] = {**b, "equity": at_last(b["equity"]), "pnl": at_last(b["pnl"])}
    out["downsample"] = {"step": int(prev["step"]) * step, "source_points": int(prev["source_points"]), "points": len(gs), "rule": RULE}
    return out
