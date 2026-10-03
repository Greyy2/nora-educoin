"""Chế độ chạy: Cơ bản (basic = preset khoá sẵn) / Nâng cao (advanced = mọi tham số chỉnh được, kiểm theo params_schema).

Module thuần (không FastAPI): kiểm tham số theo params_schema của chiến lược, điền khoá thiếu từ preset, rút tham số tối thiểu cho job,
và phân loại "custom_gates" (kết quả dùng ngưỡng gate khác chuẩn -> không được xuất bản/promote). Lớp API: backend/api/modes.py.
Mọi thông báo lỗi bằng tiếng Việt, gắn theo TRƯỜNG: [{"field": "strategies[0].params.sig.ema_fast", "message": "..."}].
"""
import math
from typing import Any, Dict, List, Optional, Tuple

MODES = ("basic", "advanced")
MAX_STRATEGIES = 9                 # số chiến lược lõi (strategy.book.CANDIDATES)
DEFAULT_TRAIN_DAYS, DEFAULT_TEST_DAYS = 120, 30   # fold mặc định của WFA (validate_book)
STANDARD_MC_SIMULATIONS = 10_000    # = carlo.monte_carlo.MC_MIN_SIMULATIONS
STANDARD_MC = {"block_days": 5, "horizon_days": 365, "ruin_threshold_pct": 30.0, "seed": 7, "scale": 1.0}
# 6 kịch bản luôn có + 3 kịch bản trend thẳng đứng (chỉ có khi nguồn biết vị thế, vd. WFA — carlo.vertical_exposure)
STRESS_BASE = ("worst_days_first", "reversed_order", "crash_day", "cost_x2", "longest_losing_streak_x2", "worst_bootstrap")
STRESS_VERTICAL = ("vertical_surge", "vertical_crash", "vertical_chain")
STRESS_NAMES = STRESS_BASE + STRESS_VERTICAL

FieldError = Tuple[str, str]       # (trường, thông báo)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unit(spec: Dict[str, Any]) -> str:
    return f" {spec['unit']}" if spec.get("unit") else ""


def check_value(key: str, spec: Dict[str, Any], value: Any) -> Tuple[Any, Optional[str]]:
    """-> (giá trị đã chuẩn hoá, lỗi|None) cho một tham số theo spec của params_schema."""
    label = f"{spec['label_vi']} ({key})"
    if spec["type"] == "choice":
        if value not in spec["choices"] or not isinstance(value, str):
            return None, f"{label} phải là một trong {spec['choices']}, nhận {value!r}"
        return value, None
    if not _num(value):
        return None, f"{label} phải là số, nhận {value!r}"
    lo, hi = spec["min"], spec["max"]
    if spec["type"] == "int":
        if not float(value).is_integer():
            return None, f"{label} phải là số nguyên từ {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
        value = int(value)
    else:
        value = float(value)
    if not lo <= value <= hi:
        return None, f"{label} phải nằm trong khoảng {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
    return value, None


def validate_params(candidate: Dict[str, Any], params: Any, base: Dict[str, Any], prefix: str = "params") -> Tuple[Dict[str, Any], List[FieldError]]:
    """Kiểm `params` của một chiến lược theo params_schema (khoá lạ, kiểu, khoảng, khung thời gian, EMA nhanh < chậm, cột kernel, ngân sách DCA).
    Khoá thiếu lấy từ `base` (preset). -> (tham số ĐẦY ĐỦ đã chuẩn hoá, danh sách lỗi theo trường). Có lỗi thì tham số đầy đủ chưa đáng tin."""
    schema = candidate["params_schema"]
    cid = candidate["id"]
    errors: List[FieldError] = []
    if not isinstance(params, dict):
        return dict(base), [(prefix, f"{cid}: params phải là đối tượng {{khoá: giá trị}}, nhận {type(params).__name__}")]
    full = dict(base)
    for key, value in params.items():
        spec = schema.get(key)
        if spec is None:
            hint = f" (ý bạn là '{'sig.' + key}'?)" if "sig." + key in schema else ""
            errors.append((f"{prefix}.{key}", f"{cid}: tham số '{key}' không có trong chiến lược này{hint}; khoá hợp lệ: {list(schema)}"))
            continue
        norm, err = check_value(key, spec, value)
        if err:
            errors.append((f"{prefix}.{key}", f"{cid}: {err}"))
        else:
            full[key] = norm
    if errors:
        return full, errors
    fast, slow = full.get("sig.ema_fast"), full.get("sig.ema_slow")
    if fast is not None and slow is not None and fast >= slow:
        errors.append((f"{prefix}.sig.ema_fast", f"{cid}: EMA nhanh ({fast}) phải nhỏ hơn EMA chậm ({slow})"))
    if errors:
        return full, errors
    # Thay thử vào cây: bắt cột kernel/khung không hợp lệ (cùng kiểm tra lúc chạy thật) + ngân sách DCA của vị thế
    try:
        from backend.core.strategy.book import materialize
        st = materialize(candidate, full)
        from backend.core.params.builder import VENUE_COSTS, dca_budget_check
        budget = dca_budget_check(st["position"], VENUE_COSTS[("cex", "perp")])
        if not budget["ok"]:
            errors.append((prefix, f"{cid}: ngân sách DCA không đủ — cần {budget['need_pct']:.1f}% vốn, trần {budget['cap_pct']:.1f}%"))
    except ValueError as exc:
        errors.append((prefix, f"{cid}: {exc}"))
    return full, errors


def job_params(candidate: Dict[str, Any], full: Dict[str, Any]) -> Dict[str, Any]:
    """Tham số TỐI THIỂU truyền cho job: mọi khoá của `space` (để run_book_backtest không điền mức giữa đè lên) + khoá khác mặc định schema.
    `risk_per_trade_pct` không đi theo tham số (job nhận qua --risk-per-trade)."""
    schema, space = candidate["params_schema"], candidate["space"]
    out = {}
    for key, value in full.items():
        if key == "risk_per_trade_pct":
            continue
        if key in space or value != schema[key]["default"]:
            out[key] = value
    return out


def common_risk(items: List[Tuple[str, Dict[str, Any]]], override: Optional[float] = None) -> Tuple[Optional[float], List[FieldError]]:
    """Mức rủi ro/lệnh dùng chung cho cả lần chạy: `override` nếu có, không thì mọi chiến lược phải cùng một mức (job chỉ nhận một --risk-per-trade)."""
    if override is not None:
        return float(override), []
    values = {}
    for i, (cid, full) in enumerate(items):
        values.setdefault(full.get("risk_per_trade_pct"), []).append((i, cid))
    values.pop(None, None)
    if len(values) <= 1:
        return (next(iter(values)) if values else None), []
    detail = "; ".join(f"{v}% ({', '.join(c for _, c in rows)})" for v, rows in values.items())
    i = list(values.values())[1][0][0]
    return None, [(f"strategies[{i}].params.risk_per_trade_pct",
                   f"Rủi ro mỗi lệnh phải GIỐNG NHAU giữa các chiến lược trong một lần chạy (danh mục dùng chung một mức): {detail}")]


def mc_standard(simulations: int, ruin_threshold_pct: float, stress_max_mdd_pct: float, stress: Optional[List[str]],
                standard_stress_max_mdd_pct: float) -> bool:
    """True nếu cấu hình MC là gate CHUẨN (>= 10.000 kịch bản, ngưỡng cháy 30%, MDD cực xấu chuẩn, đủ 6 kịch bản cực xấu cơ bản).
    Bỏ kịch bản trend thẳng đứng khi nguồn có vị thế -> API /mc tự gắn custom (chỉ ở đó mới biết nguồn)."""
    full_set = stress is None or set(STRESS_BASE) <= set(stress)
    return (simulations >= STANDARD_MC_SIMULATIONS and float(ruin_threshold_pct) == STANDARD_MC["ruin_threshold_pct"]
            and float(stress_max_mdd_pct) == float(standard_stress_max_mdd_pct) and full_set)


SCHEMA_SPACE_EXCLUDE = ("risk_per_trade_pct",)   # phễu cố định rủi ro/lệnh (S5 tìm hệ số khối lượng sau)


def schema_space(candidate: Dict[str, Any], exclude=SCHEMA_SPACE_EXCLUDE) -> Dict[str, List[Any]]:
    """Không gian sinh alpha từ params_schema: số nguyên/thực -> mọi giá trị min, min+step, ..., max; lựa chọn -> mọi lựa chọn.
    Là lưới rời rạc (cùng định dạng `space`) nên dùng chung được bộ sinh / lân cận ±1 bước của phễu."""
    out: Dict[str, List[Any]] = {}
    for key, spec in (candidate.get("params_schema") or {}).items():
        if key in exclude:
            continue
        if spec["type"] == "choice":
            out[key] = list(spec["choices"])
            continue
        lo, hi, step = spec["min"], spec["max"], spec.get("step") or 1
        n = int(math.floor((hi - lo) / step + 1e-9)) + 1
        if spec["type"] == "int":
            out[key] = [int(lo + i * step) for i in range(n)]
        else:
            nd = max(0, -int(math.floor(math.log10(step)))) + 2 if step < 1 else 2
            out[key] = [round(lo + i * step, nd) for i in range(n)]
    return out


# ─── Khung chạy (nến mô phỏng) ───────────────────────────────────────────────
def frame_keys(candidate: Dict[str, Any]) -> List[str]:
    """Khoá chọn KHUNG nến của chiến lược (sig.*_tf, atr_frame...): kiểu choice, mọi lựa chọn là khung."""
    from backend.core.backtest.engine import FRAME_MS
    return [k for k, v in (candidate.get("params_schema") or {}).items()
            if v.get("type") == "choice" and set(v.get("choices") or []) <= set(FRAME_MS)]


def lift_frame(frame: str, base_frame: str, choices: List[str]) -> Optional[str]:
    """Khung >= khung chạy giữ nguyên; nhỏ hơn -> khung chạy nếu là lựa chọn hợp lệ, không thì None (không chạy được)."""
    from backend.core.backtest.engine import FRAME_MS
    if FRAME_MS[frame] >= FRAME_MS[base_frame]:
        return frame
    return base_frame if base_frame in choices else None


def lift_frames(candidate: Dict[str, Any], params: Dict[str, Any], base_frame: str) -> Dict[str, Any]:
    """Tham số với mọi khung (kể cả mặc định schema) nâng lên >= khung chạy. ValueError nếu một khung không thể nâng."""
    from backend.core.strategy.book import schema_defaults
    if base_frame == "1m":
        return dict(params)
    out = dict(params)
    defaults = schema_defaults(candidate)
    for k in frame_keys(candidate):
        cur = out.get(k, defaults[k])
        new = lift_frame(cur, base_frame, list(candidate["params_schema"][k]["choices"]))
        if new is None:
            raise ValueError(f"{candidate['id']}: {k}={cur} nhỏ hơn khung chạy {base_frame} và không có lựa chọn >= {base_frame}")
        if new != cur or k in out:
            out[k] = new
    return out
