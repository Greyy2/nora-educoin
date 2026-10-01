"""Tham số hoá tín hiệu: ngưỡng trong cây điều kiện AST có thể là tham số tối ưu được.

Trong AST, thay một hằng số bằng node   {"param": "rsi_lo", "default": 30}
-> trước khi chạy, node được thay bằng giá trị cụ thể (signal_params["rsi_lo"] hoặc default).
Trong grid WFA / tối ưu, khoá tương ứng là "sig.rsi_lo".
"""
from typing import Any, Dict

SIG_PREFIX = "sig."


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


def resolve_placeholders(obj: Any, values: Dict[str, float]) -> Any:
    """Bản sao của obj với mọi node {"param": name} thay bằng số (values[name] hoặc default)."""
    if isinstance(obj, dict):
        if "param" in obj and set(obj) <= {"param", "default"}:
            name = str(obj["param"])
            if name not in values and "default" not in obj:
                raise ValueError(f"Thiếu giá trị cho tham số tín hiệu '{name}'")
            value = values.get(name, obj.get("default"))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Tham số tín hiệu '{name}' phải là số, nhận {value!r}")
            return float(value)
        return {key: resolve_placeholders(value, values) for key, value in obj.items()}
    if isinstance(obj, list):
        return [resolve_placeholders(item, values) for item in obj]
    return obj


def split_params(params: Dict[str, Any]):
    """{'sig.rsi_lo': 25, 'leverage': 5} -> ({'rsi_lo': 25}, {'leverage': 5})."""
    signal = {k[len(SIG_PREFIX):]: v for k, v in params.items() if k.startswith(SIG_PREFIX)}
    position = {k: v for k, v in params.items() if not k.startswith(SIG_PREFIX)}
    return signal, position
