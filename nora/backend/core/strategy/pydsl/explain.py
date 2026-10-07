"""Giải thích cấu trúc chiến lược Python từ chương trình đã biên dịch (B2 — không dùng LLM).

Dịch cây biểu thức AST sang tiếng Việt tự nhiên và trích xuất:
- indicators[]: danh sách chỉ báo kỹ thuật với tham số thực tế, khung nến, warmup
- rules[]: quy tắc vào/thoát lệnh theo thứ tự set_positions
- execution[]: cơ chế thực thi theo hồ sơ (xno / nora) từ profiles.py
- warnings[]: cảnh báo cấu trúc (dạng sự kiện/trạng thái, thiếu chân thoát, warmup...)
"""
from typing import Any, Dict, List, Optional, Set, Tuple

import backend.core.strategy.pydsl.features as feat_mod
import backend.core.strategy.pydsl.ops as ops_mod
from backend.core.strategy.pydsl.program import (
    Bin, BoolConst, Call, Cmp, Const, Data, Inv, Logic, Neg, Node, Pick, Program,
)
from backend.core.strategy.pydsl.profiles import NORA_DEFAULTS, XNO_FEE, XNO_POSITION

DATA_VI = {
    "open": "giá mở cửa",
    "high": "giá cao nhất",
    "low": "giá thấp nhất",
    "close": "giá đóng cửa",
    "volume": "khối lượng",
}


def _clean_num(v: float) -> str:
    if isinstance(v, (int, float)):
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def _format_feat_call(call: Call) -> str:
    """Định dạng cuộc gọi chỉ báo dạng toán học: EMA(close, 20), RSI(close, 14)..."""
    spec = call.spec
    name = spec.name.upper()
    args: List[str] = []
    for p in spec.params:
        if p.name in call.bound:
            val = call.bound[p.name]
            if isinstance(val, Node):
                args.append(expr_to_vi(val))
            elif isinstance(val, (int, float)):
                args.append(_clean_num(val))
            elif val != 0 and str(val):
                args.append(str(val))
    return f"{name}({', '.join(args)})"


def expr_to_vi(node: Node, parent_prec: int = 0) -> str:
    """Dịch cây biểu thức Node sang tiếng Việt có nghĩa."""
    if isinstance(node, Const):
        return _clean_num(node.value)
    if isinstance(node, BoolConst):
        return "Đúng" if node.value else "Sai"
    if isinstance(node, Data):
        return DATA_VI.get(node.col_name, f"giá {node.col_name}")
    if isinstance(node, Neg):
        return f"-{expr_to_vi(node.a, 8)}"
    if isinstance(node, Bin):
        prec_map = {"+": 4, "-": 4, "*": 6, "/": 6}
        prec = prec_map.get(node.op, 5)
        op_sym = {"+": " + ", "-": " - ", "*": " × ", "/": " / "}.get(node.op, f" {node.op} ")
        sa = expr_to_vi(node.a, prec)
        sb = expr_to_vi(node.b, prec)
        res = f"{sa}{op_sym}{sb}"
        return f"({res})" if prec < parent_prec else res
    if isinstance(node, Cmp):
        cmp_vi = {
            ">": "lớn hơn",
            ">=": "lớn hơn hoặc bằng",
            "<": "nhỏ hơn",
            "<=": "nhỏ hơn hoặc bằng",
            "==": "bằng",
            "!=": "khác",
        }
        sa = expr_to_vi(node.a, 2)
        sb = expr_to_vi(node.b, 2)
        phrase = cmp_vi.get(node.op, node.op)
        return f"{sa} {phrase} {sb}"
    if isinstance(node, Logic):
        sa = expr_to_vi(node.a, 1)
        sb = expr_to_vi(node.b, 1)
        conj = "VÀ" if node.op == "&" else "HOẶC"
        return f"{sa} {conj} {sb}"
    if isinstance(node, Inv):
        return f"KHÔNG PHẢI ({expr_to_vi(node.a, 1)})"
    if isinstance(node, Pick):
        parent_call = _format_feat_call(node.call)
        fn_name = node.call.spec.name
        if fn_name == "bbands":
            sub_names = ["Dải trên", "Dải giữa", "Dải dưới"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        if fn_name == "macd":
            sub_names = ["Đường MACD", "Đường Signal", "Histogram"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        if fn_name == "stoch":
            sub_names = ["%K", "%D"]
            sub = sub_names[node.idx] if node.idx < len(sub_names) else f"Đầu ra {node.idx}"
            return f"{sub} {parent_call}"
        return f"Đầu ra {node.idx + 1} của {parent_call}"
    if isinstance(node, Call):
        if node.is_feature:
            return _format_feat_call(node)
        op_name = node.spec.name
        b = node.bound
        if op_name == "crossed_above":
            return f"{expr_to_vi(b['a'])} cắt lên {expr_to_vi(b['b'])}"
        if op_name == "crossed_below":
            return f"{expr_to_vi(b['a'])} cắt xuống {expr_to_vi(b['b'])}"
        if op_name == "crossed":
            return f"{expr_to_vi(b['a'])} cắt {expr_to_vi(b['b'])}"
        if op_name == "crossed_above_value":
            return f"{expr_to_vi(b['a'])} cắt lên mức {_clean_num(b['value'])}"
        if op_name == "crossed_below_value":
            return f"{expr_to_vi(b['a'])} cắt xuống mức {_clean_num(b['value'])}"
        if op_name == "hold_for":
            p = b.get("periods", 1)
            return f"duy trì ({expr_to_vi(b['cond'])}) trong {p} nến"
        if op_name == "rising":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} tăng liên tục {p} nến"
        if op_name == "falling":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} giảm liên tục {p} nến"
        if op_name == "previous":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} của {p} nến trước"
        if op_name == "shift":
            p = b.get("periods", 1)
            return f"{expr_to_vi(b['x'])} lùi {p} nến"
        if op_name == "diff":
            p = b.get("periods", 1)
            return f"chênh lệch {expr_to_vi(b['x'])} so với {p} nến trước"
        if op_name == "pct_change":
            p = b.get("periods", 1)
            return f"% thay đổi của {expr_to_vi(b['x'])} sau {p} nến"
        if op_name == "between":
            return f"{expr_to_vi(b['x'])} nằm trong khoảng [{expr_to_vi(b['lower'])}, {expr_to_vi(b['upper'])}]"
        if op_name == "where":
            return f"nếu ({expr_to_vi(b['cond'])}) thì {expr_to_vi(b['a'])}, ngược lại {expr_to_vi(b['b'])}"
        if op_name == "and_":
            return f"({expr_to_vi(b['a'])}) VÀ ({expr_to_vi(b['b'])})"
        if op_name == "or_":
            return f"({expr_to_vi(b['a'])}) HOẶC ({expr_to_vi(b['b'])})"
        if op_name == "not_":
            return f"KHÔNG PHẢI ({expr_to_vi(b['a'])})"
        # Các op khác
        parts = [f"{k}={expr_to_vi(v) if isinstance(v, Node) else _clean_num(v)}" for k, v in b.items()]
        return f"{op_name}({', '.join(parts)})"
    return str(node)


def _find_calls(node: Node, out: List[Call]) -> None:
    if isinstance(node, Call):
        out.append(node)
        for v in node.bound.values():
            if isinstance(v, Node):
                _find_calls(v, out)
    elif isinstance(node, Pick):
        _find_calls(node.call, out)
    elif isinstance(node, (Bin, Cmp, Logic)):
        _find_calls(node.a, out)
        _find_calls(node.b, out)
    elif isinstance(node, (Neg, Inv)):
        _find_calls(node.a, out)


def _has_event_trigger(node: Node) -> bool:
    calls: List[Call] = []
    _find_calls(node, calls)
    event_ops = {"crossed", "crossed_above", "crossed_below", "crossed_above_value", "crossed_below_value"}
    return any(c.spec.name in event_ops for c in calls if not c.is_feature)


def explain_program(program: Program, profile: str = "xno", position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Phân tích chương trình đã biên dịch và trả về bộ giải thích có cấu trúc."""
    profile = (profile or "xno").lower().strip()
    if profile not in ("xno", "nora"):
        profile = "xno"

    # 1. Chỉ báo sử dụng
    all_calls: List[Call] = []
    for mask, _, _ in program.calls:
        _find_calls(mask, all_calls)

    feat_calls = [c for c in all_calls if c.is_feature]
    indicators: List[Dict[str, Any]] = []
    seen_feat_keys: Set[str] = set()

    for fc in feat_calls:
        signature = _format_feat_call(fc)
        if signature in seen_feat_keys:
            continue
        seen_feat_keys.add(signature)
        indicators.append({
            "name": fc.spec.name,
            "call": signature,
            "label_vi": fc.spec.label_vi or fc.spec.name.upper(),
            "meaning_vi": fc.spec.meaning_vi or fc.spec.doc or "",
            "formula": fc.spec.formula or "",
            "timeframe": program.timeframe,
            "warmup": int(fc.warm),
            "category": fc.spec.category or "trend",
        })

    # 2. Quy tắc vào / thoát lệnh
    rules: List[Dict[str, Any]] = []
    has_exit_rule = False

    for idx, (mask, level, line) in enumerate(program.calls, start=1):
        cond_str = expr_to_vi(mask)
        if level > 0:
            target_str = "LONG" if level == 1.0 else f"LONG (tỷ trọng {_clean_num(level * 100)}%)"
            action_vi = f"Vào {target_str} khi {cond_str}"
            rule_type = "entry_long"
        elif level < 0:
            target_str = "SHORT" if level == -1.0 else f"SHORT (tỷ trọng {_clean_num(abs(level) * 100)}%)"
            action_vi = f"Vào {target_str} khi {cond_str}"
            rule_type = "entry_short"
        else:
            action_vi = f"Thoát vị thế (đưa về 0) khi {cond_str}"
            rule_type = "exit"
            has_exit_rule = True

        rules.append({
            "index": idx,
            "line": line,
            "level": float(level),
            "type": rule_type,
            "condition_vi": cond_str,
            "action_vi": action_vi,
            "is_event": _has_event_trigger(mask),
        })

    # 3. Cơ chế thực thi theo hồ sơ
    execution: List[Dict[str, str]] = []
    if profile == "xno":
        execution = [
            {"title": "Khớp lệnh", "desc": "Khớp ở giá mở cửa nến tiếp theo (Next Open) sau khi nến tín hiệu đóng."},
            {"title": "Thị trường & Đòn bẩy", "desc": "Giao ngay (Spot), đòn bẩy cố định 1x, không có bán khống (Short)."},
            {"title": "Phân bổ vốn", "desc": "Chia vốn theo tỷ trọng vốn hóa rổ TOP10 × mức vị thế chỉ định."},
            {"title": "Quản trị rủi ro", "desc": "Không sử dụng Stop-Loss / Take-Profit; vị thế giữ cho tới khi có tín hiệu thoát hoặc kết thúc kỳ."},
            {"title": "Chi phí giao dịch", "desc": f"Phí khớp lệnh {_clean_num(XNO_FEE * 100)}% mỗi chiều, giả định trượt giá bằng 0."},
        ]
    else:  # nora
        pos_cfg = {**NORA_DEFAULTS, "cooldown": 60, **(program.position_overrides or {}), **(position or {})}
        risk_parts = []   # chỉ nhắc cơ chế thực sự bật (giá trị > 0) — đúng như build_plan sẽ chạy
        if float(pos_cfg.get("stop_loss_rate") or 0) > 0:
            risk_parts.append(f"Stop-Loss {_clean_num(pos_cfg['stop_loss_rate'])}×ATR tính từ giá trung bình")
        if float(pos_cfg.get("take_profit_rate") or 0) > 0:
            risk_parts.append(f"Take-Profit {_clean_num(pos_cfg['take_profit_rate'])}×ATR")
        if float(pos_cfg.get("trailing_stop") or 0) > 0:
            act = float(pos_cfg.get("trailing_activation_pct") or 0)
            risk_parts.append(f"trailing stop {_clean_num(pos_cfg['trailing_stop'])}×ATR" + (f" (bật khi lãi ≥ {_clean_num(act)}×ATR)" if act > 0 else ""))
        if int(pos_cfg.get("timeout") or 0) > 0:
            risk_parts.append(f"giữ tối đa {int(pos_cfg['timeout'])} phút")
        if int(pos_cfg.get("cooldown") or 0) > 0:
            risk_parts.append(f"nghỉ {int(pos_cfg['cooldown'])} phút sau khi thoát")
        risk_desc = ("Ngoài tín hiệu thoát: " + ", ".join(risk_parts) + ".") if risk_parts else "Chỉ thoát theo tín hiệu; không có Stop-Loss / Take-Profit."
        if pos_cfg.get("atr_frame"):
            risk_desc += f" ATR đo trên khung {pos_cfg['atr_frame']}."
        execution = [
            {"title": "Khớp lệnh", "desc": "Khớp ở giá mở cửa nến tiếp theo (Next Open) theo quy chuẩn Nora Engine."},
            {"title": "Thị trường & Đòn bẩy", "desc": "Hợp đồng phái sinh vĩnh cửu (Perpetual), hỗ trợ đòn bẩy và cả hai chiều Long/Short."},
            {"title": "Phân bổ vốn", "desc": "Chia khối lượng theo ngân sách rủi ro (Risk-based sizing) từng lệnh."},
            {"title": "Quản trị rủi ro", "desc": risk_desc},
            {"title": "Chi phí giao dịch", "desc": "Tính phí sàn theo mô hình Maker/Taker thực tế kèm mô phỏng trượt giá bảo thủ."},
        ]

    # 4. Cảnh báo cấu trúc
    warnings: List[str] = list(program.warnings)

    # Kiểm tra tín hiệu sự kiện vs trạng thái
    for r in rules:
        if r["level"] != 0 and not r["is_event"]:
            warnings.append(
                f"Quy tắc {r['index']} (dòng {r['line']}): Tín hiệu dạng trạng thái (điều kiện so sánh liên tục); "
                "khi điều kiện duy trì đúng qua nhiều nến, lệnh chỉ được kích hoạt lại nếu vị thế trước đó đã đóng."
            )

    if not has_exit_rule and len(rules) > 0:
        warnings.append("Chiến lược không có quy tắc thoát lệnh tường minh (set_positions(0)); vị thế chỉ đóng khi đổi chiều hoặc kết thúc kỳ backtest.")

    if program.has_long and not program.has_short:
        warnings.append("Chiến lược chỉ kích hoạt vị thế LONG (mua/nắm giữ), không tham gia chiều SHORT khi thị trường giảm.")

    if program.warmup_bars >= 60:
        warnings.append(f"Số nến khởi động khá lớn ({program.warmup_bars} nến); chiến lược cần đủ dữ liệu lịch sử trước khi bắt đầu sinh tín hiệu.")

    return {
        "indicators": indicators,
        "rules": rules,
        "execution": execution,
        "warnings": list(dict.fromkeys(warnings)),
    }
