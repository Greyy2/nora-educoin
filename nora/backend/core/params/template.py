"""Tham số hoá tín hiệu: ngưỡng trong cây điều kiện AST có thể là tham số tối ưu được.

Trong AST, thay một hằng số bằng node   {"param": "rsi_lo", "default": 30}
-> trước khi chạy, node được thay bằng giá trị cụ thể (signal_params["rsi_lo"] hoặc default).
Trong grid WFA / tối ưu, khoá tương ứng là "sig.rsi_lo".

Chu kỳ chỉ báo và khung thời gian cũng tham số hoá được: hai trường chuỗi `frame` và `column` của node AST có thể chứa
`{tên}` (cùng không gian tên "sig." với node số), vd {"frame": "{trend_tf}", "column": "ema_{ema_fast}", "index": 0}.
Giá trị mặc định lấy từ `defaults` (materialize truyền mặc định của params_schema). Kết quả sau khi thay phải hợp lệ:
  - khung ∈ FRAMES ("1m","5m","15m","1h","4h","24h"; chấp nhận cả số phút 1/5/15/60/240/1440);
  - cột là cột OHLCV hoặc cột kernel hợp lệ (signals.kernels.parse_column), chu kỳ n/m là số nguyên 2..500.
Chuỗi KHÔNG chứa `{...}` được giữ nguyên bit-for-bit (cây cũ không đổi).
"""
import math
import re
from typing import Any, Dict, Optional, Set

SIG_PREFIX = "sig."
FRAMES = ("1m", "5m", "15m", "1h", "4h", "24h")
FRAME_MINUTES = {1: "1m", 5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "24h"}
MIN_PERIOD, MAX_PERIOD = 2, 500
_STR_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_STR_FIELDS = ("frame", "column")


def collect_placeholders(obj: Any) -> Dict[str, float]:
    """{tên tham số: giá trị mặc định} của mọi node {"param": ...} trong obj."""
    found: Dict[str, float] = {}

    def walk(node):
        if isinstance(node, dict):
            if "param" in node and set(node) <= {"param", "default"}:
                found[str(node["param"])] = float(node.get("default", 0.0))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def collect_string_placeholders(obj: Any) -> Set[str]:
    """Tên mọi `{tên}` nằm trong trường chuỗi frame/column của node AST."""
    found: Set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _STR_FIELDS and isinstance(value, str):
                    found.update(_STR_PLACEHOLDER.findall(value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def _fmt_number(value: float) -> str:
    """20.0 -> '20', 2.5 -> '2.5' (tên cột kernel: bbl_20_2, bbl_20_2.5)."""
    if float(value).is_integer():
        return str(int(value))
    return format(float(value), "f").rstrip("0").rstrip(".")


def _placeholder_text(name: str, field: str, values: Dict[str, Any], defaults: Dict[str, Any]) -> str:
    if name in values:
        value = values[name]
    elif name in defaults:
        value = defaults[name]
    else:
        raise ValueError(f"Thiếu giá trị cho tham số tín hiệu '{name}' (dùng trong {field} của điều kiện)")
    if isinstance(value, bool):
        raise ValueError(f"Tham số tín hiệu '{name}' phải là số hoặc khung thời gian, nhận {value!r}")
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(f"Tham số tín hiệu '{name}' phải hữu hạn, nhận {value!r}")
        if field == "frame":   # số phút -> tên khung
            if float(value) in {float(k) for k in FRAME_MINUTES}:
                return FRAME_MINUTES[int(value)]
            raise ValueError(f"Khung '{name}'={value!r} không hợp lệ; chọn một trong {list(FRAMES)}")
        return _fmt_number(value)
    raise ValueError(f"Tham số tín hiệu '{name}' phải là số hoặc khung thời gian, nhận {value!r}")


def _resolve_string(text: str, field: str, values: Dict[str, Any], defaults: Dict[str, Any]) -> str:
    out = _STR_PLACEHOLDER.sub(lambda m: _placeholder_text(m.group(1), field, values, defaults), text)
    if "{" in out or "}" in out:
        raise ValueError(f"{field} {text!r} có dấu ngoặc nhọn không đúng cú pháp {{tên}}")
    if field == "frame":
        if out not in FRAMES:
            raise ValueError(f"Khung thời gian {out!r} không hợp lệ; chọn một trong {list(FRAMES)}")
        return out
    from backend.core.signals.kernels import BASE_COLUMNS, parse_column
    if out in BASE_COLUMNS:
        return out
    parsed = parse_column(out)
    if parsed is None:
        raise ValueError(f"Cột chỉ báo {out!r} (từ {text!r}) không hợp lệ: chu kỳ phải là số nguyên {MIN_PERIOD}..{MAX_PERIOD}, "
                         f"hệ số k trong (0, 10]")
    spec, params = parsed
    for pname, pval in zip(spec.params, params):
        if pname in ("n", "m") and not MIN_PERIOD <= pval <= MAX_PERIOD:
            raise ValueError(f"Chu kỳ {pname}={pval:g} của cột {out!r} ngoài khoảng {MIN_PERIOD}..{MAX_PERIOD}")
    return out


def resolve_placeholders(obj: Any, values: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Any:
    """Bản sao của obj với mọi node {"param": name} thay bằng số (values[name] hoặc default của node) và mọi `{tên}` trong
    frame/column thay bằng giá trị (values[tên], không có thì defaults[tên]; thiếu cả hai -> ValueError)."""
    defaults = defaults or {}
    if isinstance(obj, dict):
        if "param" in obj and set(obj) <= {"param", "default"}:
            name = str(obj["param"])
            if name not in values and "default" not in obj:
                raise ValueError(f"Thiếu giá trị cho tham số tín hiệu '{name}'")
            value = values.get(name, obj.get("default"))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Tham số tín hiệu '{name}' phải là số, nhận {value!r}")
            return float(value)
        out = {}
        for key, value in obj.items():
            if key in _STR_FIELDS and isinstance(value, str) and "{" in value:
                out[key] = _resolve_string(value, key, values, defaults)
            else:
                out[key] = resolve_placeholders(value, values, defaults)
        return out
    if isinstance(obj, list):
        return [resolve_placeholders(item, values, defaults) for item in obj]
    return obj


def split_params(params: Dict[str, Any]):
    """{'sig.rsi_lo': 25, 'leverage': 5} -> ({'rsi_lo': 25}, {'leverage': 5})."""
    signal = {k[len(SIG_PREFIX):]: v for k, v in params.items() if k.startswith(SIG_PREFIX)}
    position = {k: v for k, v in params.items() if not k.startswith(SIG_PREFIX)}
    return signal, position
