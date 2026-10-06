"""Diễn giải alpha bằng LỜI (thuật ngữ tài chính phổ biến) song song với công thức LaTeX của alpha_doc.

Cùng nguồn: cây điều kiện AST + vị thế đã materialize + bảng theo TÊN KERNEL (không viết tay theo từng alpha). Mỗi hàm trả câu tiếng Việt
đã điền tham số thật. Số viết kiểu Việt (dấu phẩy thập phân).
"""
from typing import Any, Dict, List, Optional, Tuple

from backend.core.signals.kernels import parse_column

FRAME_VI = {"1m": "1 phút", "5m": "5 phút", "15m": "15 phút", "1h": "1 giờ", "4h": "4 giờ", "24h": "ngày"}
PRICE_VI = {"close": "giá đóng cửa", "open": "giá mở cửa", "high": "giá cao nhất", "low": "giá thấp nhất", "volume": "khối lượng"}
CMP_VI = {"<": "dưới", ">": "trên", "<=": "không cao hơn", ">=": "không thấp hơn", "==": "bằng", "=": "bằng", "!=": "khác"}


def vn(x: Any) -> str:
    """Số kiểu Việt: 1.2 -> "1,2"; 4.0 -> "4"."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    s = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def frame_vi(frame: str) -> str:
    return FRAME_VI.get(str(frame), str(frame))


def _bars(n: Any, frame: str) -> str:
    return f"{vn(n)} nến {frame_vi(frame)}"


# ─── Tên gọi ngắn của một chỉ báo (dùng trong câu điều kiện) ─────────────────
def name(kernel: str, p: Tuple[float, ...], frame: str) -> str:
    n = vn(p[0]) if p else ""
    k = vn(p[1]) if len(p) > 1 else ""
    f = frame_vi(frame)
    return {
        "sma": f"đường trung bình SMA {n} (khung {f})",
        "ema": f"đường trung bình mũ EMA {n} (khung {f})",
        "roc": f"tốc độ thay đổi giá ROC {n} (khung {f})",
        "er": f"hệ số hiệu quả xu hướng ER {n} (khung {f})",
        "adx": f"sức mạnh xu hướng ADX {n} (khung {f})",
        "rsi": f"RSI {n} (khung {f})",
        "bbz": f"độ lệch Z-score so với trung bình {n} (khung {f})",
        "bbm": f"đường giữa Bollinger {n} (khung {f})",
        "bbu": f"dải trên Bollinger ({n} nến, {k} độ lệch chuẩn, khung {f})",
        "bbl": f"dải dưới Bollinger ({n} nến, {k} độ lệch chuẩn, khung {f})",
        "bbw": f"độ rộng dải Bollinger {n} (khung {f})",
        "bbwp": f"phân vị độ rộng Bollinger (khung {f})",
        "atr": f"biên độ dao động trung bình ATR {n} (khung {f})",
        "natr": f"ATR% {n} (khung {f})",
        "rv": f"biến động thực RV {n} (khung {f})",
        "kcm": f"đường giữa kênh Keltner {n} (khung {f})",
        "kcu": f"dải trên kênh Keltner ({n} nến, {k}×ATR, khung {f})",
        "kcl": f"dải dưới kênh Keltner ({n} nến, {k}×ATR, khung {f})",
        "dch": f"đỉnh cao nhất {n} nến trước (khung {f})",
        "dcl": f"đáy thấp nhất {n} nến trước (khung {f})",
        "vwap": f"giá trung bình theo khối lượng VWAP {n} (khung {f})",
        "vwapdev": f"% lệch giá so với VWAP {n} (khung {f})",
        "volz": f"đột biến khối lượng (Z-score {n} nến, khung {f})",
    }.get(kernel, f"{kernel.upper()} {n} (khung {f})")


# ─── Định nghĩa dễ hiểu của từng chỉ báo ───────────────────────────────────
def explain(kernel: str, p: Tuple[float, ...], frame: str) -> str:
    n = vn(p[0]) if p else ""
    k = vn(p[1]) if len(p) > 1 else ""
    b = _bars(p[0], frame) if p else ""
    nm = name(kernel, p, frame)
    text = {
        "sma": f"giá đóng cửa trung bình cộng của {b} gần nhất — mức giá \"cân bằng\" của giai đoạn đó.",
        "ema": f"giá trung bình của {b} nhưng nến càng gần càng được coi trọng hơn (trung bình mũ), nên bám giá nhanh hơn SMA; "
               "thường dùng làm đường xu hướng chính.",
        "roc": f"giá hiện tại đã tăng/giảm bao nhiêu % so với {b} trước.",
        "er": f"đo thị trường đang đi một chiều hay lình xình trong {b}: lấy quãng đường giá đi được (đầu → cuối) chia cho tổng quãng đường "
              "giá thực sự đã chạy lên xuống. Gần 1 = xu hướng rõ, đi thẳng; gần 0 = đi ngang, nhiễu, giằng co.",
        "adx": f"đo độ MẠNH của xu hướng (không phân biệt tăng hay giảm) trong khoảng {b}, thang 0–100: dưới ~20–25 là không có xu hướng, "
               "trên ~40 là xu hướng rất mạnh.",
        "rsi": f"chỉ số sức mạnh tương đối trên {b}: so độ lớn các nhịp tăng với các nhịp giảm gần đây, thang 0–100. "
               "Thấp (thường < 30) = bị bán quá đà (quá bán), cao (> 70) = bị mua quá đà (quá mua).",
        "bbz": f"giá đang cách mức trung bình {b} bao nhiêu lần độ lệch chuẩn (càng xa 0 càng bất thường).",
        "bbm": f"đường giữa dải Bollinger = giá trung bình cộng {b}.",
        "bbu": f"đường trung bình {b} cộng thêm {k} lần độ lệch chuẩn của giá — biên trên \"bình thường\"; giá vượt lên trên là đang căng/quá mua thống kê.",
        "bbl": f"đường trung bình {b} trừ đi {k} lần độ lệch chuẩn của giá — biên dưới \"bình thường\"; giá rơi xuống dưới là đang bị bán quá đà thống kê.",
        "bbw": f"độ rộng dải Bollinger so với giá (%): hẹp = thị trường đang nén biến động, rộng = đang biến động mạnh.",
        "bbwp": "độ rộng Bollinger hiện tại đứng ở phân vị nào so với lịch sử gần đây (thấp = đang nén, thường trước một nhịp bùng nổ).",
        "atr": f"biên độ dao động trung bình mỗi nến trong {b} (tính cả khoảng nhảy giá giữa các nến) — thước đo biến động theo đơn vị giá.",
        "natr": f"biên độ dao động trung bình mỗi nến ({b}) tính theo % giá. Dùng làm \"thước đo\" biến động: mọi khoảng cách cắt lỗ, chốt lời, "
                "bước dồn lệnh đều là BỘI SỐ của ATR% này, nên tự rộng ra khi thị trường biến động mạnh và hẹp lại khi êm.",
        "rv": f"độ biến động thực tế: độ lệch chuẩn của lợi suất (log) {b}, theo %.",
        "kcm": f"đường giữa kênh Keltner = EMA {n} của giá.",
        "kcu": f"EMA {n} cộng {k} lần ATR — biên trên của kênh co giãn theo biến động; đóng cửa vượt lên trên = phá kênh đi lên.",
        "kcl": f"EMA {n} trừ {k} lần ATR — biên dưới của kênh; đóng cửa xuyên xuống dưới = phá kênh đi xuống.",
        "dch": f"đỉnh cao nhất của {b} TRƯỚC nến hiện tại — giá đóng cửa vượt lên là breakout.",
        "dcl": f"đáy thấp nhất của {b} TRƯỚC nến hiện tại — giá đóng cửa thủng xuống là breakdown.",
        "vwap": f"giá trung bình có trọng số theo khối lượng của {b} — mức giá \"đông người giao dịch\" nhất.",
        "vwapdev": f"giá đang cao/thấp hơn VWAP {n} bao nhiêu %.",
        "volz": f"khối lượng hiện tại cao bất thường đến đâu so với {b} gần nhất (số lần độ lệch chuẩn).",
    }.get(kernel, "")
    return f"{nm[0].upper()}{nm[1:]}: {text}" if text else nm


# ─── Điều kiện bằng lời ────────────────────────────────────────────────────
def operand(item: Any) -> str:
    if isinstance(item, bool) or item is None:
        return "—"
    if isinstance(item, (int, float)):
        return vn(item)
    if not isinstance(item, dict):
        return "—"
    typ = item.get("type")
    if typ == "calculate":
        a, b = operand(item.get("number_1")), operand(item.get("number_2"))
        logic = item.get("logic")
        word = {"*": "×", "/": "÷", "+": "+", "-": "−"}.get(logic, "?")
        num_b = isinstance(item.get("number_2"), (int, float)) and not isinstance(item.get("number_2"), bool)
        out = f"{b} × {a}" if logic == "*" and num_b else f"{a} {word} {b}"   # "4,6 × ATR" đọc tự nhiên hơn "ATR × 4,6"
        mult = item.get("multiply", 1.0)
        if isinstance(mult, (int, float)) and not isinstance(mult, bool) and float(mult) != 1.0:
            out = f"{vn(mult)} × ({out})"
        return out
    if typ in ("min", "max"):
        return f"{'nhỏ nhất' if typ == 'min' else 'lớn nhất'} của ({', '.join(operand(x) for x in item.get('numbers', []))})"
    if "frame" in item and "column" in item:
        frame, column, lag = str(item["frame"]), str(item["column"]), int(item.get("index", 0) or 0)
        parsed = parse_column(column)
        if column in PRICE_VI:
            base = f"{PRICE_VI[column]} khung {frame_vi(frame)}"
        elif parsed is not None:
            base = name(parsed[0].name, parsed[1], frame)
        else:
            base = column
        if "subtract" in item:
            base = f"{base} − {operand(item['subtract'])}"
        if "add" in item:
            base = f"{base} + {operand(item['add'])}"
        if "divide" in item:
            base = f"({base}) ÷ {operand(item['divide'])}"
        if lag:
            base = f"{base} [của {lag} nến trước]" if lag > 1 else f"{base} [của nến trước]"
        return base
    return "—"


def _strip_lag(text: str) -> str:
    return text.replace(" [của nến trước]", "")


def conditions(block: List[Any], cross_pairs: List[Tuple[int, int]]) -> List[str]:
    """Các điều kiện AND của một khối thành câu; cặp (a ở nến t, a ở nến t−1 ngược chiều) gộp thành "cắt lên/cắt xuống"."""
    out, skip = [], set()
    for i, j in cross_pairs:
        a = block[i]
        word = "CẮT LÊN trên" if a[1] in (">", ">=") else "CẮT XUỐNG dưới"
        out.append(f"{operand(a[0])} {word} {operand(a[2])} (nến trước còn ở phía bên kia, nến vừa đóng đã vượt qua)")
        skip.update((i, j))
    for i, c in enumerate(block):
        if i in skip:
            continue
        left, op, right = c
        out.append(f"{operand(left)} {CMP_VI.get(op, op)} {operand(right)}")
    return [_strip_lag(x) if "CẮT" in x else x for x in out]


# ─── Các phần còn lại ──────────────────────────────────────────────────────
def ladder(side: str, layers: int, step: float, m: float, through: float, gated: bool, atr_desc: str) -> List[str]:
    adverse = "giảm" if side == "LONG" else "tăng"
    act = "mua thêm" if side == "LONG" else "bán thêm"
    out = [f"Giá {adverse} tiếp sau khi vào lệnh thì {act} tối đa {layers} tầng. Mỗi tầng đặt sẵn lệnh chờ (limit) cách giá khớp của tầng liền trước "
           f"{vn(step)} × ATR% ({atr_desc}, đo một lần lúc vào lệnh).",
           f"Mỗi tầng lớn gấp {vn(m)} lần tầng trước (tầng đầu 1 phần, tầng 1 {vn(m)} phần, tầng 2 {vn(round(m * m, 2))} phần…): dồn càng sâu thì giá trung bình "
           "càng được kéo nhanh về gần giá hiện tại."]
    if gated:
        out.append("Chỉ dồn khi điều kiện \"được phép dồn\" còn đúng ở nến vừa đóng — tức thị trường vẫn đi ngang. Khi bắt đầu có xu hướng thì NGỪNG dồn, "
                   "không nhồi lệnh mù quáng theo giá.")
    if through:
        out.append(f"Lệnh chờ chỉ tính là khớp khi giá đi qua mức đặt thêm {vn(through)}% (giả định thận trọng về hàng đợi sổ lệnh).")
    return out


def position(side: str, sl: float, tp: float, tr: float, act: float, timeout: int, unit_atr: bool, atr_desc: str, layered: bool = True) -> List[str]:
    u = f" × ATR% ({atr_desc})" if unit_atr else "%"
    ref = "GIÁ TRUNG BÌNH các tầng đã khớp (dồn thêm thì mức dời theo giá trung bình mới)" if layered else "giá vào lệnh"
    out = []
    if sl > 0:
        out.append(f"Cắt lỗ {'cả rổ ' if layered else ''}khi giá đi ngược {vn(sl)}{u} tính từ {ref}.")
    if tp > 0:
        out.append(f"Chốt lời {'cả rổ ' if layered else ''}khi giá đi thuận {vn(tp)}{u} tính từ {'giá trung bình' if layered else 'giá vào lệnh'} (lệnh limit).")
    if tr > 0:
        start = f"khi đang lãi từ {vn(act)}{u}" if act > 0 else "ngay từ đầu"
        out.append(f"Dừng lỗ động (trailing stop): bật {start}; sau đó đặt cách đỉnh lãi cao nhất {vn(tr)}{u} và chỉ dời theo hướng có lợi, không lùi.")
    if timeout:
        out.append(f"Giữ lệnh tối đa {vn(timeout)} phút (≈ {vn(round(timeout / 1440.0, 1))} ngày), quá hạn thì đóng bằng giá thị trường.")
    return out


def sizing(r: float, cap: float, lev: int, layered: bool) -> List[str]:
    out = [f"Khối lượng tính NGƯỢC từ rủi ro: chọn tổng giá trị lệnh sao cho nếu chạm cắt lỗ (đã gồm mọi tầng dồn dự kiến, phí và trượt giá) "
           f"thì chỉ mất khoảng {vn(r)}% vốn. Thị trường càng biến động (cắt lỗ càng xa) thì vào lệnh càng nhỏ.",
           f"Tổng giá trị lệnh không vượt {vn(cap)}% vốn."]
    if layered:
        out.append("Phần rủi ro đó được chia sẵn cho tầng đầu và các tầng dồn theo tỷ lệ tăng dần ở trên — dồn hết tầng vẫn không vượt mức rủi ro đã định.")
    out.append(f"Đòn bẩy tối đa {lev}x nhưng tự hạ xuống sao cho giá thanh lý luôn xa hơn mức cắt lỗ ít nhất 1,5 lần: lệnh luôn bị cắt lỗ trước khi bị thanh lý. "
               "Đòn bẩy chỉ quyết định ký quỹ phải bỏ ra, KHÔNG làm tăng rủi ro.")
    return out


def portfolio(risk: Dict[str, Any]) -> List[str]:
    out = []
    if risk.get("max_positions"):
        out.append(f"Tối đa {vn(risk['max_positions'])} vị thế mở cùng lúc, mỗi đồng coin tối đa {vn(risk.get('max_per_symbol', 1))} vị thế.")
    if risk.get("max_gross_exposure"):
        out.append(f"Tổng giá trị các lệnh đang mở không quá {vn(risk['max_gross_exposure'])} lần vốn.")
    if risk.get("max_open_risk_pct"):
        out.append(f"Tổng rủi ro của mọi lệnh đang mở (nếu tất cả cùng chạm cắt lỗ) không quá {vn(risk['max_open_risk_pct'])}% vốn — lệnh mới bị thu nhỏ hoặc bỏ qua.")
    if risk.get("dd_throttle_pct"):
        out.append(f"Đang thua lỗ thì tự giảm rủi ro: vốn sụt d% so với đỉnh thì lệnh mới chỉ còn (1 − d/{vn(risk['dd_throttle_pct'])}%) mức rủi ro, "
                   f"thấp nhất {vn(round(float(risk.get('dd_throttle_floor', 0.25)) * 100))}%.")
    if risk.get("kill_switch_dd_pct"):
        out.append(f"Công tắc ngắt: vốn (tính cả lãi lỗ chưa chốt) sụt {vn(risk['kill_switch_dd_pct'])}% từ đỉnh thì đóng hết và dừng giao dịch.")
    return out


def atr_desc(position_: Dict[str, Any]) -> str:
    return f"{vn(position_.get('atr_period', 14))} nến {frame_vi(str(position_.get('atr_frame', '1h')))}"


def entry_exec(timeframe: Optional[str], cooldown: int, frames: Optional[List[str]] = None) -> List[str]:
    tf = frame_vi(timeframe or "1h")
    out = [f"Kiểm điều kiện mỗi khi một nến {tf} ĐÓNG (không dùng dữ liệu tương lai); đủ điều kiện thì vào lệnh thị trường ở đầu nến {tf} kế tiếp."]
    bigger = sorted({frame_vi(f) for f in frames or [] if f != (timeframe or "1h")})
    if bigger:
        out.append(f"Chỉ báo khung {', '.join(bigger)} chỉ đổi giá trị khi nến khung đó đóng hẳn; giữa chừng dùng giá trị của nến đã đóng gần nhất.")
    if cooldown:
        out.append(f"Vừa đóng vị thế thì nghỉ {vn(cooldown)} phút (≈ {vn(round(cooldown / 60.0, 1))} giờ) mới nhận tín hiệu mới.")
    return out
