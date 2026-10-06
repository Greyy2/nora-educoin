"""Tài liệu hoá alpha: Ý TƯỞNG + CÔNG THỨC toán tài chính (LaTeX) + thống kê, dựng từ cấu trúc ĐÃ materialize của sổ chiến lược.

Không viết tay theo từng alpha: cây điều kiện AST, vị thế và tham số thật của sổ được dịch sang LaTeX; định nghĩa chỉ báo lấy từ bảng mẫu theo TÊN KERNEL
(kiến thức toán, signals/kernels.py là bản cài đặt chính xác). Mọi chuỗi LaTeX chỉ dùng ASCII (chữ Việt nằm ở tiêu đề / ghi chú, không nằm trong công thức).

Định dạng kết quả (payload có `sources` để sau này thêm nguồn ngoài):
    catalog() -> {"sources": [{"key": "nora", "label": "Nora", "books": {...}, "alphas": [render_alpha(...), ...]}]}
    render_alpha(...)["formulas"] = [{"key", "title", "plain", "latex", "note"}, ...] theo thứ tự đọc; "plain" = diễn giải bằng lời (alpha_plain).
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.core.analytics import alpha_plain as plain
from backend.core.signals.kernels import REGISTRY, parse_column

STAGE_ORDER = ("FINAL", "S6_holdout", "S5_sizing", "S4_montecarlo", "S3_wfa", "S2_antiluck", "S1_backtest")
STAT_KEYS = ("ret_pct", "mdd_pct", "sharpe", "sortino", "profit_factor", "win_rate", "trades", "symbols_positive",
             "extreme_ret_pct", "extreme_mdd_pct", "final_scale")
STATUS_VI = {"READY_FOR_TESTNET": "Sẵn sàng testnet", "EXPLORE_DEMO": "Thử nghiệm (demo)"}
DEPLOY_DEFAULT = {"main": "Demo OKX + paper", "explore": "Paper (thử nghiệm)"}
STRATEGY_TITLE = {"kema": "Kênh Keltner (KEMA)", "sideway": "Sideway (đi ngang)", "dca": "DCA (bắt hồi + dồn lệnh)"}
SIDE_VI = {"LONG": "Long", "SHORT": "Short"}
PRICE_SYMBOL = {"close": "C", "open": "O", "high": "H", "low": "L", "volume": "V"}
CMP_LATEX = {"<": "<", ">": ">", "<=": r"\le", ">=": r"\ge", "==": "=", "=": "=", "!=": r"\ne"}
MMR_DEFAULT = 0.005   # maintenance_margin_rate mặc định của StrategyParams (builder)


# ─── Định dạng số ───────────────────────────────────────────────────────────
def num(x: Any) -> str:
    """28.0 -> '28'; 1.2 -> '1.2'; 0.0005 -> '0.0005' (không dùng ký hiệu khoa học)."""
    v = float(x)
    if v == int(v) and abs(v) < 1e12:
        return str(int(v))
    return format(v, "f").rstrip("0").rstrip(".")


def pct(frac: float) -> str:
    """0.0005 -> '0.05' (đổi tỉ lệ sang số % rồi định dạng)."""
    return num(round(float(frac) * 100.0, 6))


def tl(lag: int) -> str:
    """index AST -> nhãn thời gian: 0 -> 't', 1 -> 't-1'."""
    return "t" if not lag else f"t-{int(lag)}"


def _frame(frame: str) -> str:
    return rf"\mathrm{{{frame}}}"


# ─── Ký hiệu + định nghĩa kernel (bảng mẫu theo tên kernel) ─────────────────
def _fmt_args(p: Tuple[float, ...]) -> str:
    return ",".join(num(x) for x in p)


def symbol(kernel: str, p: Tuple[float, ...], frame: str, t: str = "t") -> str:
    """\\mathrm{RSI}^{1h}_{7}(t): tên kernel, khung (chỉ số trên), tham số (chỉ số dưới), thời điểm."""
    f = _frame(frame)
    sub = _fmt_args(p)
    if kernel in ("bbl", "bbu", "bbm"):
        band = {"bbl": "lo", "bbu": "up", "bbm": "mid"}[kernel]
        return rf"\mathrm{{BB}}^{{\mathrm{{{band}}},{f}}}_{{{sub}}}({t})"
    if kernel in ("kcl", "kcu", "kcm"):
        band = {"kcl": "lo", "kcu": "up", "kcm": "mid"}[kernel]
        return rf"\mathrm{{KC}}^{{\mathrm{{{band}}},{f}}}_{{{sub}}}({t})"
    return rf"\mathrm{{{kernel.upper()}}}^{{{f}}}_{{{sub}}}({t})"


def price_symbol(column: str, frame: str, t: str = "t") -> str:
    return rf"{PRICE_SYMBOL[column]}^{{{_frame(frame)}}}({t})"


_RMA = r"\mathrm{RMA}_{n}"
_TR = r"\max(H_t-L_t,\,|H_t-C_{t-1}|,\,|L_t-C_{t-1}|)"


def definition(kernel: str, p: Tuple[float, ...], frame: str) -> List[str]:
    """Các dòng LaTeX định nghĩa một chỉ báo (đã thay tham số thật). C, H, L, V = giá đóng / cao / thấp / khối lượng của nến khung `frame`."""
    S = symbol(kernel, p, frame)
    S1 = symbol(kernel, p, frame, "t-1")
    n = num(p[0]) if p else ""
    k = num(p[1]) if len(p) > 1 else ""
    sma_n = rf"\mathrm{{SMA}}_{{{n}}}(C)_t"
    sigma = rf"\sigma_{{{n}}}(t)=\sqrt{{\tfrac{{1}}{{{n}}}\textstyle\sum_{{i=0}}^{{{n}-1}}\bigl(C_{{t-i}}-{sma_n}\bigr)^2}}"
    rma = rf"\mathrm{{RMA}}_{{{n}}}(x)_t=\tfrac{{1}}{{{n}}}x_t+\bigl(1-\tfrac{{1}}{{{n}}}\bigr)\mathrm{{RMA}}_{{{n}}}(x)_{{t-1}}"
    atr = rf"\mathrm{{RMA}}_{{{n}}}(\mathrm{{TR}})_t,\ \mathrm{{TR}}_t={_TR}"
    if kernel == "sma":
        return [rf"{S}=\frac{{1}}{{{n}}}\sum_{{i=0}}^{{{n}-1}}C_{{t-i}}"]
    if kernel == "ema":
        return [rf"{S}=\alpha C_t+(1-\alpha)\,{S1},\quad \alpha=\frac{{2}}{{{n}+1}}"]
    if kernel == "roc":
        return [rf"{S}=100\left(\frac{{C_t}}{{C_{{t-{n}}}}}-1\right)"]
    if kernel == "er":
        return [rf"{S}=\frac{{|C_t-C_{{t-{n}}}|}}{{\sum_{{i=0}}^{{{n}-1}}|C_{{t-i}}-C_{{t-i-1}}|}}\in[0,1]"]
    if kernel == "adx":
        return [rf"{S}=\mathrm{{RMA}}_{{{n}}}(\mathrm{{DX}})_t,\quad \mathrm{{DX}}=100\frac{{|\mathrm{{DI}}^{{+}}-\mathrm{{DI}}^{{-}}|}}{{\mathrm{{DI}}^{{+}}+\mathrm{{DI}}^{{-}}}}",
                rf"\mathrm{{DI}}^{{\pm}}=100\frac{{\mathrm{{RMA}}_{{{n}}}(\mathrm{{DM}}^{{\pm}})}}{{\mathrm{{ATR}}_{{{n}}}}},\ "
                r"u_t=H_t-H_{t-1},\ d_t=L_{t-1}-L_t,\ \mathrm{DM}^{+}_t=u_t\mathbb{1}[u_t>d_t,\,u_t>0],\ \mathrm{DM}^{-}_t=d_t\mathbb{1}[d_t>u_t,\,d_t>0]"]
    if kernel == "rsi":
        return [rf"{S}=100-\frac{{100}}{{1+\mathrm{{RS}}_t}},\quad \mathrm{{RS}}_t=\frac{{\mathrm{{RMA}}_{{{n}}}(\max(\Delta C,0))_t}}{{\mathrm{{RMA}}_{{{n}}}(\max(-\Delta C,0))_t}},\ \Delta C_t=C_t-C_{{t-1}}",
                rma]
    if kernel == "bbz":
        return [rf"{S}=\frac{{C_t-{sma_n}}}{{\sigma_{{{n}}}(t)}}", sigma]
    if kernel in ("bbm", "bbu", "bbl"):
        sign = {"bbm": "", "bbu": "+", "bbl": "-"}[kernel]
        body = sma_n if kernel == "bbm" else rf"{sma_n}{sign}{k}\,\sigma_{{{n}}}(t)"
        return [rf"{S}={body}"] + ([sigma] if kernel != "bbm" else [])
    if kernel == "bbw":
        return [rf"{S}=100\,\frac{{2\cdot {k}\,\sigma_{{{n}}}(t)}}{{{sma_n}}}", sigma]
    if kernel == "bbwp":
        m = num(p[2])
        return [rf"{S}=100\cdot\frac{{\mathrm{{rank}}_{{{m}}}\bigl(\mathrm{{BBW}}_{{{n},{k}}}(t)\bigr)}}{{{m}}}"]
    if kernel == "atr":
        return [rf"{S}={atr}", rma]
    if kernel == "natr":
        return [rf"{S}=100\cdot\frac{{\mathrm{{ATR}}_{{{n}}}(t)}}{{C_t}},\quad \mathrm{{ATR}}_{{{n}}}(t)={atr}", rma]
    if kernel == "rv":
        return [rf"{S}=100\cdot\mathrm{{std}}_{{{n}}}\bigl(\ln C_t-\ln C_{{t-1}}\bigr)"]
    if kernel in ("kcm", "kcu", "kcl"):
        sign = {"kcm": "", "kcu": "+", "kcl": "-"}[kernel]
        ema = rf"\mathrm{{EMA}}_{{{n}}}(t)"
        body = ema if kernel == "kcm" else rf"{ema}{sign}{k}\cdot\mathrm{{ATR}}_{{{n}}}(t)"
        return [rf"{S}={body},\quad \mathrm{{EMA}}_{{{n}}}(t)=\alpha C_t+(1-\alpha)\mathrm{{EMA}}_{{{n}}}(t-1),\ \alpha=\frac{{2}}{{{n}+1}}"]
    if kernel == "dch":
        return [rf"{S}=\max_{{1\le i\le {n}}}H_{{t-i}}"]
    if kernel == "dcl":
        return [rf"{S}=\min_{{1\le i\le {n}}}L_{{t-i}}"]
    if kernel == "vwap":
        return [rf"{S}=\frac{{\sum_{{i=0}}^{{{n}-1}}\mathrm{{TP}}_{{t-i}}V_{{t-i}}}}{{\sum_{{i=0}}^{{{n}-1}}V_{{t-i}}}},\quad \mathrm{{TP}}=\frac{{H+L+C}}{{3}}"]
    if kernel == "vwapdev":
        return [rf"{S}=100\left(\frac{{C_t}}{{\mathrm{{VWAP}}_{{{n}}}(t)}}-1\right)"]
    if kernel == "volz":
        return [rf"{S}=\frac{{V_t-\mu^{{V}}_{{{n}}}(t)}}{{\sigma^{{V}}_{{{n}}}(t)}}"]
    return [rf"{S}"]


# ─── AST -> LaTeX ───────────────────────────────────────────────────────────
Operand = Tuple[str, int]   # (latex, độ ưu tiên: 3 nguyên tử, 2 nhân/chia, 1 cộng/trừ)


def _paren(x: Operand, need: int) -> str:
    return x[0] if x[1] >= need else rf"\left({x[0]}\right)"


def operand(item: Any, used: Optional[List[Tuple[str, str]]] = None) -> Operand:
    """Giá trị trong AST -> (LaTeX, ưu tiên). Ghi (khung, cột) đã dùng vào `used` (để dựng định nghĩa chỉ báo)."""
    if isinstance(item, bool) or item is None:
        return r"\varnothing", 3
    if isinstance(item, (int, float)):
        return num(item), 3
    if not isinstance(item, dict):
        return r"\varnothing", 3
    typ = item.get("type")
    if typ == "calculate":
        a, b = operand(item.get("number_1"), used), operand(item.get("number_2"), used)
        op = item.get("logic")
        if op == "*":
            out = (rf"{_paren(a, 2)}\cdot {_paren(b, 2)}", 2)
        elif op == "/":
            out = (rf"\frac{{{a[0]}}}{{{b[0]}}}", 3)
        elif op == "+":
            out = (rf"{a[0]}+{b[0]}", 1)
        elif op == "-":
            out = (rf"{a[0]}-{_paren(b, 2)}", 1)
        else:
            return r"\varnothing", 3
        mult = item.get("multiply", 1.0)
        if isinstance(mult, (int, float)) and not isinstance(mult, bool) and float(mult) != 1.0:
            return rf"{num(mult)}\cdot {_paren(out, 2)}", 2
        return out
    if typ in ("min", "max"):
        xs = ",".join(operand(x, used)[0] for x in item.get("numbers", []))
        return rf"\{typ}\left({xs}\right)", 3
    if "frame" in item and "column" in item:
        frame, column, lag = str(item["frame"]), str(item["column"]), int(item.get("index", 0) or 0)
        if used is not None and (frame, column) not in used:
            used.append((frame, column))
        parsed = parse_column(column)
        if column in PRICE_SYMBOL:
            base = price_symbol(column, frame, tl(lag))
        elif parsed is not None:
            base = symbol(parsed[0].name, parsed[1], frame, tl(lag))
        else:
            base = rf"\mathrm{{{column.replace('_', '-')}}}^{{{_frame(frame)}}}({tl(lag)})"
        out: Operand = (base, 3)
        if "subtract" in item:
            m = operand(item["subtract"], used)
            out = (rf"{out[0]}-{_paren(m, 2)}", 1)
        if "add" in item:
            m = operand(item["add"], used)
            out = (rf"{out[0]}+{m[0]}", 1)
        if "divide" in item:
            d = operand(item["divide"], used)
            out = (rf"\frac{{{out[0]}}}{{{d[0]}}}", 3)
        return out
    return r"\varnothing", 3


def _bounds(item: Any) -> Optional[Tuple[float, float]]:
    """Khoảng giá trị của một toán hạng là cột kernel THUẦN (không cộng/trừ/chia) có đơn vị '0..100' hoặc '0..1'; None nếu không giới hạn."""
    if not isinstance(item, dict) or "column" not in item or any(k in item for k in ("add", "subtract", "divide")):
        return None
    parsed = parse_column(str(item["column"]))
    if parsed is None:
        return None
    unit = parsed[0].unit
    if ".." not in unit:
        return None
    lo, hi = unit.split("..")
    return float(lo), float(hi)


def is_tautology(triplet: List[Any]) -> bool:
    """Điều kiện luôn đúng với mọi giá trị hợp lệ của chỉ báo bị chặn (vd rsi < 101, rsi > -1, er <= 1): ngưỡng "tắt" của bộ tham số."""
    if not isinstance(triplet, (list, tuple)) or len(triplet) != 3:
        return False
    left, op, right = triplet
    flip = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
    if isinstance(left, (int, float)) and not isinstance(left, bool) and op in flip:
        left, op, right = right, flip[op], left
    b = _bounds(left)
    if b is None or isinstance(right, bool) or not isinstance(right, (int, float)):
        return False
    lo, hi = b
    c = float(right)
    return (op == "<" and c > hi) or (op == "<=" and c >= hi) or (op == ">" and c < lo) or (op == ">=" and c <= lo)


def condition(triplet: List[Any], used: Optional[List[Tuple[str, str]]] = None) -> str:
    left, op, right = triplet
    return rf"{operand(left, used)[0]}\ {CMP_LATEX.get(op, op)}\ {operand(right, used)[0]}"


def _stack(rows: List[str], joiner: str) -> str:
    """Xếp các biểu thức thành cột, nối bằng toán tử logic ở cuối dòng (array left-aligned)."""
    if len(rows) == 1:
        return rows[0]
    body = r" \\ ".join(rf"\displaystyle {r}" + (rf"\ {joiner}" if i < len(rows) - 1 else "") for i, r in enumerate(rows))
    return rf"\begin{{array}}{{l}} {body} \end{{array}}"


def render_tree(tree: Any, used: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Any]:
    """Cây điều kiện (OR giữa các khối, AND trong khối) -> {"latex": thân công thức (không có 'Entry_t ='), "always": luôn đúng?, "conditions": số điều kiện còn lại,
    "dropped": số điều kiện hằng đúng đã bỏ, "events": số cặp 'cắt lên/xuống'}. Khối rỗng sau khi bỏ điều kiện hằng đúng => cả cây luôn đúng."""
    blocks: List[List[str]] = []
    dropped = events = n_cond = 0
    always = False
    for block in tree if isinstance(tree, list) else []:
        if not isinstance(block, list) or not block:
            continue
        keep = []
        for tr in block:
            if is_tautology(tr):
                dropped += 1
            else:
                keep.append(tr)
        if not keep:
            always = True
            continue
        events += _count_crosses(keep)
        n_cond += len(keep)
        blocks.append([condition(tr, used) for tr in keep])
    if always or not blocks:
        return {"latex": "1", "always": True, "conditions": 0, "dropped": dropped, "events": 0}
    parts = [_stack(b, r"\land") for b in blocks]
    if len(parts) == 1:
        latex = parts[0]
    else:
        latex = _stack([rf"\left({p}\right)" for p in parts], r"\lor")
    return {"latex": latex, "always": False, "conditions": n_cond, "dropped": dropped, "events": events}


def _lag(item: Any, k: int = 1) -> Any:
    """Bản dịch lùi k nến của một toán hạng (để nhận diện cặp cắt lên/xuống)."""
    if isinstance(item, list):
        return [_lag(x, k) for x in item]
    if not isinstance(item, dict):
        return item
    out = {}
    for key, v in item.items():
        if key == "index" and "column" in item:
            out[key] = int(v or 0) + k
        elif key in ("add", "subtract", "divide", "number_1", "number_2") or key == "numbers":
            out[key] = _lag(v, k)
        else:
            out[key] = v
    return out


def _count_crosses(block: List[Any]) -> int:
    """Số cặp (a > b) & (a[1] <= b[1]) hoặc (a < b) & (a[1] >= b[1]) trong một khối AND = sự kiện cắt (chỉ đúng ở nến cắt)."""
    n = 0
    for a in block:
        for b in block:
            if a is b or not (isinstance(a, list) and isinstance(b, list)):
                continue
            if (a[1], b[1]) in ((">", "<="), ("<", ">=")) and b[0] == _lag(a[0]) and b[2] == _lag(a[2]):
                n += 1
    return n


# ─── Các phần công thức ─────────────────────────────────────────────────────
def _section(key: str, title: str, latex: str, note: str = "", plain_: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"key": key, "title": title, "plain": list(plain_ or []), "latex": latex, "note": note}


def plain_tree(tree: Any) -> Dict[str, Any]:
    """Cây điều kiện -> câu: {"blocks": [[câu, ...], ...] (OR giữa các khối, AND trong khối), "always"}; bỏ điều kiện hằng đúng, gộp cặp cắt lên/xuống."""
    blocks: List[List[str]] = []
    for block in tree if isinstance(tree, list) else []:
        if not isinstance(block, list) or not block:
            continue
        keep = [tr for tr in block if not is_tautology(tr)]
        if not keep:
            return {"blocks": [], "always": True}
        pairs, used_idx = [], set()
        for i, a in enumerate(keep):
            for j, b in enumerate(keep):
                if i == j or i in used_idx or j in used_idx or not (isinstance(a, list) and isinstance(b, list)):
                    continue
                if (a[1], b[1]) in ((">", "<="), ("<", ">=")) and b[0] == _lag(a[0]) and b[2] == _lag(a[2]):
                    pairs.append((i, j))
                    used_idx.update((i, j))
        blocks.append(plain.conditions(keep, pairs))
    return {"blocks": blocks, "always": not blocks}


def _plain_lines(head: str, pt: Dict[str, Any]) -> List[str]:
    """Câu dẫn + các điều kiện (một khối: liệt kê, nhiều khối: "trường hợp k")."""
    if pt["always"]:
        return [f"{head} luôn đúng (không có điều kiện)."]
    if len(pt["blocks"]) == 1:
        return [f"{head} TẤT CẢ điều kiện sau cùng đúng:"] + [f"• {c}" for c in pt["blocks"][0]]
    out = [f"{head} MỘT trong các trường hợp sau đúng:"]
    for k, b in enumerate(pt["blocks"], 1):
        out.append(f"Trường hợp {k}: " + " VÀ ".join(b))
    return out


def _rows(lines: List[str]) -> str:
    """Nhiều dòng công thức độc lập, căn trái."""
    return rf"\begin{{array}}{{l}} " + r" \\[6pt] ".join(rf"\displaystyle {x}" for x in lines) + r" \end{array}"


def _indicators_section(cols: List[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
    lines: List[str] = []
    words: List[str] = []
    seen = set()
    for frame, column in cols:
        parsed = parse_column(column)
        if parsed is None:
            continue
        spec, p = parsed
        w = plain.explain(spec.name, p, frame)
        if w not in words:
            words.append(w)
        for ln in definition(spec.name, p, frame):
            if ln not in seen:
                seen.add(ln)
                lines.append(ln)
    if not lines:
        return None
    note = ("C, H, L, V = giá đóng cửa, cao nhất, thấp nhất, khối lượng của nến thuộc khung ghi ở chỉ số trên; t = nến đã ĐÓNG gần nhất của khung đó. "
            "EMA/RMA khởi tạo bằng SMA n nến đầu (chuẩn TradingView); RMA là trung bình Wilder (α = 1/n); độ lệch chuẩn σ tính theo tổng thể (chia n). "
            "Chỉ báo chưa đủ nến khởi động = không xác định, điều kiện chứa nó coi là sai.")
    return _section("indicators", "Định nghĩa chỉ báo", _rows(lines), note, words)


def _sign(side: str) -> Tuple[str, str]:
    """(dấu của bước bất lợi, dấu có lợi) theo chiều: LONG giá giảm là bất lợi."""
    return ("-", "+") if side == "LONG" else ("+", "-")


def _nu(position: Dict[str, Any], t: str = "t_0") -> str:
    return rf"\nu_0=\mathrm{{NATR}}^{{{_frame(str(position.get('atr_frame', '1h')))}}}_{{{num(position.get('atr_period', 14))}}}({t})"


def _ladder_params(position: Dict[str, Any]) -> Optional[Tuple[int, float, float]]:
    layers = int(position.get("dca_max_layers") or 0)
    step = float(position.get("dca_step_pct") or 0.0)
    if layers <= 0 or step <= 0:
        return None
    return layers, step, float(position.get("dca_size_multiplier") or 1.0)


def _mult_total(layers: int, m: float) -> float:
    return sum(m ** k for k in range(layers + 1))


def costs(book: Dict[str, Any]) -> Tuple[float, float, float]:
    """(taker, maker, trượt giá) của backtest: CEX perp (builder.VENUE_COSTS)."""
    from backend.core.params.builder import VENUE_COSTS
    return VENUE_COSTS[("cex", "perp")]


def render_formulas(st: Dict[str, Any], book: Dict[str, Any]) -> List[Dict[str, str]]:
    """Các phần công thức của một chiến lược đã materialize (xem module docstring)."""
    side = st["side"]
    position = st["position"]
    sec: List[Dict[str, str]] = []
    used: List[Tuple[str, str]] = []
    sd = side.lower()

    entry = render_tree(st.get("tree"), used)
    stop = render_tree((st.get("stop") or [{}])[0].get("condition"), used) if st.get("stop") else None
    gate = render_tree((st.get("dca") or [{}])[0].get("condition"), used) if st.get("dca") else None
    unit_atr = position.get("exit_unit") == "atr"
    if unit_atr:
        used.append((str(position.get("atr_frame", "1h")), f"natr_{num(position.get('atr_period', 14))}"))

    ind = _indicators_section(used)
    if ind:
        sec.append(ind)

    # b) tín hiệu vào
    tf = str(book.get("timeframe") or "1h")
    notes = [f"Tín hiệu tính trên nến đã đóng; lệnh market khớp ở giá mở của nến {tf} kế tiếp (cộng trượt giá), mỗi nến chỉ đặt một lệnh chờ."]
    if entry["events"]:
        notes.append("Cặp điều kiện ở nến t và t−1 là sự kiện cắt (crossover): chỉ đúng đúng ở nến cắt, không đúng suốt đoạn giá nằm một phía.")
    if entry["dropped"]:
        notes.append(f"Đã lược {entry['dropped']} điều kiện hằng đúng (ngưỡng đặt ngoài miền giá trị của chỉ báo = tắt).")
    cd = int(position.get("cooldown") or 0)
    if cd:
        notes.append(f"Sau khi đóng vị thế, bỏ qua tín hiệu mới trong {cd} phút (cooldown).")
    side_vi = "Long (mua)" if side == "LONG" else "Short (bán)"
    sec.append(_section("entry", "Tín hiệu vào lệnh",
                        rf"\mathrm{{Entry}}^{{\mathrm{{{sd}}}}}_t=\mathbb{{1}}\left[{entry['latex']}\right]" if not entry["always"]
                        else rf"\mathrm{{Entry}}^{{\mathrm{{{sd}}}}}_t=1", " ".join(notes),
                        _plain_lines(f"Vào lệnh {side_vi} khi", plain_tree(st.get("tree"))) + plain.entry_exec(tf, cd, [f for f, _ in used])))
    if stop is not None:
        sec.append(_section("exit_signal", "Tín hiệu thoát (đảo chiều)",
                            rf"\mathrm{{Exit}}^{{\mathrm{{{sd}}}}}_t=\mathbb{{1}}\left[{stop['latex']}\right]" if not stop["always"] else rf"\mathrm{{Exit}}^{{\mathrm{{{sd}}}}}_t=1",
                            f"Có tín hiệu thoát thì đóng toàn bộ vị thế bằng lệnh market ở giá mở nến {tf} kế tiếp (ngoài các lệnh thoát theo giá bên dưới).",
                            _plain_lines("Đóng toàn bộ vị thế (đảo chiều) khi", plain_tree((st.get("stop") or [{}])[0].get("condition")))))

    # c) cổng + thang DCA
    lad = _ladder_params(position)
    if gate is not None:
        sec.append(_section("dca_gate", "Điều kiện dồn lệnh (cổng DCA)",
                            rf"\mathrm{{Gate}}_t=\mathbb{{1}}\left[{gate['latex']}\right]" if not gate["always"] else r"\mathrm{Gate}_t=1",
                            "Chỉ cho phép dồn tầng khi cổng còn đúng ở nến đã đóng gần nhất; cổng sai (thị trường bắt đầu có xu hướng) thì ngừng dồn, vị thế giữ nguyên các tầng đã có."
                            + (f" Đã lược {gate['dropped']} điều kiện hằng đúng." if gate["dropped"] else ""),
                            _plain_lines("Được phép dồn thêm tầng khi", plain_tree((st.get("dca") or [{}])[0].get("condition")))))
    if lad:
        layers, step, m = lad
        adv, _ = _sign(side)
        through = float(position.get("limit_through_pct") or 0.0)
        lim_cmp = r"\le\," if side == "LONG" else r"\ge\,"
        ext = "L" if side == "LONG" else "H"
        trig = rf"P^{{\mathrm{{lim}}}}_k\left(1{adv}\delta\right)" if through else r"P^{\mathrm{lim}}_k"
        lines = [
            rf"{_nu(position)}\ (\%)",
            rf"P^{{\mathrm{{lim}}}}_k=P_{{k-1}}\left(1{adv}\frac{{{num(step)}\cdot\nu_0}}{{100}}\right),\quad k=1,\dots,{layers}",
            rf"q_k=q_0\,{num(m)}^{{k}},\quad \sum_{{k=0}}^{{{layers}}}{num(m)}^{{k}}={num(round(_mult_total(layers, m), 4))}",
            rf"\mathrm{{Fill}}_k=\mathbb{{1}}\left[{ext}^{{{_frame(book.get('timeframe') or '1m')}}}_{{\tau}}{lim_cmp}{trig}"
            + (r"\ \land\ \mathrm{Gate}_{t}" if gate is not None and not gate["always"] else "") + r"\right]"
            + (rf",\quad \delta={pct(through / 100.0)}\%" if through else ""),
        ]
        note = (f"Tầng đầu q₀ vào ở tín hiệu; tối đa {layers} tầng dồn thêm (lệnh limit), mỗi tầng lớn gấp {num(m)} lần tầng trước. "
                "P_{k-1} là giá khớp thực của tầng liền trước; ν₀ là ATR% đo MỘT LẦN ở nến tín hiệu nên các bước và mức cắt lỗ / chốt lời của cả rổ giữ nguyên theo ν₀ đó. "
                + (f"Lệnh limit chỉ khớp khi giá đi qua mức thêm {num(through)}% (hàng đợi sổ lệnh). " if through else "")
                + "Mức hoà (chạm cả tầng dồn lẫn cắt lỗ trong cùng nến) ưu tiên thoát.")
        sec.append(_section("dca_ladder", "Thang dồn lệnh (DCA)", _rows(lines), note,
                            plain.ladder(side, layers, step, m, through, gate is not None and not gate["always"], plain.atr_desc(position))))

    # d) quản lý vị thế
    sl, tp = float(position.get("stop_loss_rate") or 0.0), float(position.get("take_profit_rate") or 0.0)
    tr, act = float(position.get("trailing_stop") or 0.0), float(position.get("trailing_activation_pct") or 0.0)
    timeout = int(position.get("timeout") or 0)
    adv, fav = _sign(side)
    pl: List[str] = [rf"{_nu(position)}\ (\%)"] if unit_atr else []
    unit_txt = r"\cdot\nu_0" if unit_atr else ""
    pnote = ["P̄ = giá trung bình các tầng đã khớp (tính lại sau mỗi tầng dồn). " + ("Mọi mức thoát tính theo bội số ATR% (ν₀) của nến tín hiệu: cùng một bộ tham số tự co giãn theo biến động từng tài sản." if unit_atr else "")]
    if sl > 0:
        pl.append(rf"\mathrm{{SL}}=\bar P\left(1{adv}\frac{{{num(sl)}{unit_txt}}}{{100}}\right)")
        pnote.append("Cắt lỗ là lệnh market (phí taker + trượt giá), tính từ giá trung bình chứ không phải từ tầng đầu.")
    if tp > 0:
        pl.append(rf"\mathrm{{TP}}=\bar P\left(1{fav}\frac{{{num(tp)}{unit_txt}}}{{100}}\right)")
        pnote.append("Chốt lời là lệnh limit (phí maker) từ giá trung bình; bỏ qua ở nến có tầng dồn khớp.")
    if tr > 0:
        ext = "\\max_{\\tau\\ge t_0}H_\\tau" if side == "LONG" else "\\min_{\\tau\\ge t_0}L_\\tau"
        gain = r"P^{*}-\bar P" if side == "LONG" else r"\bar P-P^{*}"
        pl.append(rf"P^{{*}}={ext},\quad \mathrm{{on}}\Leftrightarrow\ \frac{{{gain}}}{{\bar P}}\ge\frac{{{num(act)}{unit_txt}}}{{100}}")
        pl.append(rf"\mathrm{{Trail}}=P^{{*}}\left(1{adv}\frac{{{num(tr)}{unit_txt}}}{{100}}\right)")
        pnote.append("Trailing chỉ bật khi lãi (từ giá trung bình tới đỉnh có lợi P*) đạt ngưỡng kích hoạt; sau đó mức dừng bám đỉnh/đáy có lợi và không lùi." if act > 0 else
                     "Trailing bật ngay từ khi vào lệnh; mức dừng bám đỉnh/đáy có lợi và không lùi.")
    if timeout:
        pl.append(rf"t-t_0\ge {timeout}\ \mathrm{{min}}\ \Rightarrow\ \mathrm{{close\ (market)}}")
        pnote.append(f"Hết thời gian giữ lệnh {timeout} phút (≈ {num(round(timeout / 1440.0, 1))} ngày) thì đóng bằng lệnh market.")
    pnote.append("Trong cùng một nến: các mức bất lợi xử lý theo đúng thứ tự giá chạm, hoà thì ưu tiên thoát; giá mở đã vượt mức (gap) thì khớp ở giá mở.")
    sec.append(_section("position", "Quản lý vị thế", _rows(pl), " ".join(pnote),
                        plain.position(side, sl, tp, tr, act, timeout, unit_atr, plain.atr_desc(position), bool(lad))))

    # e) khối lượng + rủi ro
    taker, maker, slip = costs(book)
    r = float(position.get("risk_per_trade_pct") or 0.0)
    cap = float(position.get("max_notional_pct") or 0.0)
    lev = int(position.get("leverage") or 1)
    cost = r"2(f+\epsilon)"
    sl_frac = rf"\frac{{{num(sl)}\cdot\nu_0}}{{100}}" if unit_atr else rf"\frac{{{num(sl)}}}{{100}}"
    sl_sym = r"s_L"
    sz = [
        rf"s_L={sl_frac},\quad f={pct(taker)}\%,\ \epsilon={pct(slip)}\%,\ r={num(r)}\%,\ c={num(cap)}\%",
        rf"N=\min\left(\frac{{E\cdot r}}{{{sl_sym}+{cost}}},\ E\cdot c\right)",
    ]
    if lad:
        layers, _, m = lad
        sz.append(rf"N_k=N\cdot\frac{{{num(m)}^{{k}}}}{{\sum_{{j=0}}^{{{layers}}}{num(m)}^{{j}}}},\quad k=0,\dots,{layers}")
    sz.append(rf"\lambda=\max\left(1,\ \min\left({lev},\ \left\lfloor\frac{{1}}{{1.5\,{sl_sym}+\mathrm{{mmr}}}}\right\rfloor\right)\right),\quad \mathrm{{mmr}}={pct(MMR_DEFAULT)}\%")
    liq = rf"P^{{\mathrm{{liq}}}}=\bar P\left(1{adv}\frac{{1}}{{\lambda}}{fav}\mathrm{{mmr}}\right)"
    sz.append(liq)
    sz.append(rf"R=N\left({sl_sym}+{cost}\right)\le E\cdot r")
    snote = ("E = vốn hiện tại (vốn đã chốt lãi/lỗ). N = tổng giá trị danh nghĩa của cả rổ: chọn sao cho chạm cắt lỗ (tính cả mọi tầng dồn dự kiến, phí vào + ra và trượt giá) chỉ mất ≈ r% vốn, "
             "bị chặn trần c% vốn. Đòn bẩy λ tự hạ để giá thanh lý cách giá vào ít nhất 1.5 lần khoảng cắt lỗ, tối đa " f"{lev}x. "
             "Ký quỹ tầng k = N_k / λ. Phí/trượt giả định của backtest (CEX perp, taker cho lệnh market, maker cho lệnh limit).")
    sec.append(_section("sizing", "Khối lượng & rủi ro mỗi lệnh", _rows(sz), snote, plain.sizing(r, cap, lev, bool(lad))))

    # portfolio
    risk = book.get("risk") or {}
    pf: List[str] = []
    pn: List[str] = []
    if risk.get("max_positions"):
        pf.append(rf"\#\mathrm{{positions}}\le {num(risk['max_positions'])},\quad \#\mathrm{{positions/symbol}}\le {num(risk.get('max_per_symbol', 1))}")
        pn.append("Số vị thế mở đồng thời tối đa; mỗi tài sản tối đa một vị thế (mọi chiến lược cộng lại) nên rủi ro không chồng lên nhau.")
    if risk.get("max_gross_exposure"):
        pf.append(rf"\frac{{\sum_i N_i}}{{E}}\le {num(risk['max_gross_exposure'])}")
        pn.append("Trần tổng danh nghĩa / vốn; lệnh mới bị thu nhỏ cho vừa phần còn lại.")
    if risk.get("max_open_risk_pct"):
        pf.append(rf"\sum_i R_i\le {num(risk['max_open_risk_pct'])}\%\cdot E")
        pn.append("Trần rủi ro đang mở: tổng rủi ro tới cắt lỗ của mọi rổ đang mở; nhiều rổ cùng chạm cắt lỗ cũng chỉ mất tối đa mức này.")
    if risk.get("dd_throttle_pct"):
        pf.append(rf"r_{{\mathrm{{eff}}}}=r\cdot\max\left({num(risk.get('dd_throttle_floor', 0.25))},\ 1-\frac{{d}}{{{num(risk['dd_throttle_pct'])}\%}}\right)")
        pn.append("d = % vốn đã chốt đang sụt so với đỉnh; rủi ro lệnh mới giảm tuyến tính theo d, sàn bằng hệ số tối thiểu.")
    if risk.get("kill_switch_dd_pct"):
        pf.append(rf"\mathrm{{DD}}^{{\mathrm{{MTM}}}}\ge {num(risk['kill_switch_dd_pct'])}\%\ \Rightarrow\ \mathrm{{close\ all\ \&\ halt}}")
        pn.append("Công tắc ngắt: vốn theo giá thị trường sụt từ đỉnh tới ngưỡng thì đóng hết (market) và dừng giao dịch.")
    if pf:
        sec.append(_section("portfolio", "Kiểm soát rủi ro danh mục", _rows(pf), " ".join(pn), plain.portfolio(risk)))
    return sec


# ─── Thống kê + triển khai ──────────────────────────────────────────────────
def stage_stats(item: Dict[str, Any]) -> Dict[str, Any]:
    """Chỉ số của bậc FINAL (không có thì bậc muộn nhất còn lại) + giai đoạn đã tới."""
    ev = item.get("evidence") or {}
    sm = ev.get("stage_metrics") or {}
    stage = next((s for s in STAGE_ORDER if sm.get(s)), None)
    m = sm.get(stage) or {}
    out = {k: m.get(k) for k in STAT_KEYS}
    out["stage"] = stage
    out["stage_reached"] = ev.get("stage_reached")
    return out


def book_summary(book: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """Thống kê cấp sổ: WFA OOS, holdout, rủi ro danh mục, vũ trụ, cửa sổ dữ liệu."""
    ev = book.get("evidence") or {}
    wfa = (ev.get("dev2_base_risk") or {}).get("wfa_summary") or {}
    hold = (ev.get("final") or {}).get("holdout") or {}
    out: Dict[str, Any] = {
        "kind": kind, "status": book.get("status"), "status_label": STATUS_VI.get(book.get("status"), book.get("status")),
        "timeframe": book.get("timeframe"), "universe": book.get("universe") or [], "windows": book.get("windows"),
        "risk_per_trade_pct": book.get("risk_per_trade_pct"), "risk": book.get("risk"), "source": book.get("source"),
        "holdout_pass": book.get("holdout_pass"), "holdout": hold or None, "generated_at": book.get("generated_at"),
        "unvalidated": book.get("unvalidated") or [],
    }
    if wfa:
        out["wfa"] = {
            "n_folds": wfa.get("n_folds"), "positive_folds": wfa.get("positive_folds"), "oos_days": wfa.get("oos_days"),
            "compounded_oos_ret_pct": wfa.get("compounded_oos_ret_pct"), "worst_fold_mdd_pct": wfa.get("worst_fold_mdd_pct"),
            "oos_trades": wfa.get("oos_trades"), "fold_t": wfa.get("fold_t"),
            "mc": {k: (wfa.get("mc") or {}).get(k) for k in ("median_ret_pct", "p05_ret_pct", "mdd_p95_pct", "p_mdd_ge_ruin_pct")} if wfa.get("mc") else None,
        }
    else:
        out["wfa"] = None
    return out


def deploy_info(kind: str, jobs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Nơi alpha đang chạy: nhãn mặc định theo loại sổ + chế độ bot (paper / demo) đang chạy thật của sổ đó (nếu đọc được job)."""
    running = sorted({str((j.get("params") or {}).get("mode")) for j in (jobs or [])
                      if j.get("kind") == "live_bot" and j.get("status") == "running" and ((j.get("params") or {}).get("book") or "main") == kind
                      and (j.get("params") or {}).get("mode")})
    return {"label": DEPLOY_DEFAULT.get(kind, kind), "running_modes": running}


def _live_jobs() -> List[Dict[str, Any]]:
    try:
        from backend.api.jobs import batch
        return batch.list_jobs(limit=100, kind="live_bot")
    except Exception:   # chưa có thư mục job / môi trường test
        return []


def materialize_item(item: Dict[str, Any], book: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core.params.modes import lift_frames
    from backend.core.strategy.book import BY_ID, materialize
    cand = BY_ID[item["id"]]
    params = dict(item.get("params") or {})
    try:
        params = lift_frames(cand, params, book.get("timeframe", "1m"))
    except ValueError:
        pass
    return materialize(cand, params, risk_per_trade_pct=book.get("risk_per_trade_pct"), stop_fill="level")


def render_alpha(item: Dict[str, Any], book: Dict[str, Any], kind: str = "main", jobs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Một alpha của sổ -> {id, alpha_id, strategy, label, side, timeframe, universe, status, book, idea, stats, deploy, formulas}."""
    from backend.core.strategy.book import BY_ID, STRATEGIES
    cand = BY_ID[item["id"]]
    key = cand.get("strategy") or item["id"].split("_")[0]
    cat = next((s for s in STRATEGIES if s["id"] == key), {})
    st = materialize_item(item, book)
    side = item.get("side") or st["side"]
    return {
        "id": item["id"], "alpha_id": (item.get("evidence") or {}).get("funnel_alpha_id"),
        "strategy": key, "strategy_label": STRATEGY_TITLE.get(key, cat.get("name") or key),
        "label": f"{STRATEGY_TITLE.get(key, key)} · {SIDE_VI.get(side, side)}",
        "side": side, "timeframe": book.get("timeframe"), "universe": book.get("universe") or [],
        "status": book.get("status"), "status_label": STATUS_VI.get(book.get("status"), book.get("status")),
        "book": kind, "idea": cat.get("idea") or cat.get("description") or "", "description": item.get("description") or cand.get("description"),
        "stats": stage_stats(item), "deploy": deploy_info(kind, jobs), "formulas": render_formulas(st, book),
    }


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def catalog(alphas_dir: Optional[str] = None, book_path: Optional[str] = None) -> Dict[str, Any]:
    """{"sources": [{"key": "nora", "label": "Nora", "books": {main, explore}, "alphas": [...]}]}: sổ chính rồi sổ thử nghiệm.
    Thêm nguồn ngoài = thêm một phần tử vào `sources` (cùng định dạng alpha)."""
    from backend.core.params.presets import alphas_dir as _adir, book_path as _bpath
    base = alphas_dir or _adir()
    paths = {"main": book_path or _bpath(), "explore": os.path.join(base, "explore", "book.json")}
    jobs = _live_jobs()
    alphas: List[Dict[str, Any]] = []
    books: Dict[str, Any] = {}
    for kind, path in paths.items():
        book = _read(path)
        if not book:
            continue
        books[kind] = book_summary(book, kind)
        for item in book.get("strategies") or []:
            try:
                alphas.append(render_alpha(item, book, kind, jobs))
            except (KeyError, ValueError) as e:   # id không còn trong danh mục: bỏ qua, không làm hỏng cả trang
                books[kind].setdefault("skipped", []).append({"id": item.get("id"), "error": str(e)})
    return {"sources": [{"key": "nora", "label": "Nora", "books": books, "alphas": alphas}]}
