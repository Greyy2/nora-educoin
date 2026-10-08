"""Strategy Contract (P9 alpha/): giới hạn + lỗi + gợi ý cho chiến lược do người dùng/AI viết. Chỉ import core (DslError ở core/signal vì Program ném nó).

Chuyển từ core/signal.py (P9 alpha pass): MAX_CODE_CHARS, MAX_NODES, BASE_CLASS, at, suggest, _position_attr_names.
"""
import ast
import difflib
import io
import re
import tokenize
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.core.signal import DslError

MAX_CODE_CHARS = 50_000
MAX_NODES = 20_000
BASE_CLASS = "SimpleAlgorithm"

def at(node, message: str) -> DslError:
    """DslError gắn vào một nút ast (lineno, col_offset 0-based -> cột 1-based)."""
    line = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    err = DslError(message, line, None if col is None else col + 1)
    end_line, end_col = getattr(node, "end_lineno", None), getattr(node, "end_col_offset", None)
    if end_line is not None and end_col is not None:
        err.end_line, err.end_col = end_line, end_col + 1
    return err


def suggest(name: str, options: Iterable[str], n: int = 4) -> str:
    """' Gần đúng: a, b, c' (rỗng nếu không có tên nào gần)."""
    close: List[str] = difflib.get_close_matches(str(name), list(options), n=n, cutoff=0.5)
    return f" Gần đúng: {', '.join(close)}." if close else ""


def _position_attr_names() -> Set[str]:
    from backend.core.params import POSITION_KEYS
    return set(POSITION_KEYS)


# ══════════════════════════════════════════════════════════════════════════
# Vòng đời hợp đồng (NautilusTrader-style): on_start (khai báo) -> on_bar (luật) -> on_stop (tuỳ chọn, no-op).
# Biên dịch ĐỒNG NGHĨA với `def __algorithm__(self)` có thân = thân on_start + thân on_bar (cùng IR, cùng program_hash).
# Hàm thuần trên AST; cả hai trình biên dịch (alpha, module) dùng chung `lifecycle_body`.
# ══════════════════════════════════════════════════════════════════════════

LIFECYCLE = ("on_start", "on_bar", "on_stop")
_ACTIONS = ("set_positions", "set_dca_gate")


def _is_doc(stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _calls_action(stmts) -> Optional[ast.Call]:
    for st in stmts:
        for n in ast.walk(st):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _ACTIONS \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self":
                return n
    return None


def has_lifecycle(cls: ast.ClassDef) -> bool:
    return any(isinstance(s, ast.FunctionDef) and s.name in LIFECYCLE for s in cls.body)


def native_tree(tree: ast.Module) -> ast.Module:
    """Cây với mọi class dùng on_start/on_bar/on_stop được viết lại thành `__algorithm__` tổng hợp (để code_hash đúng bằng dạng gốc tương đương)."""
    if not any(isinstance(c, ast.ClassDef) and has_lifecycle(c) for c in tree.body):
        return tree
    out = ast.Module(body=[], type_ignores=[])
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and has_lifecycle(n):
            c = ast.ClassDef(name=n.name, bases=n.bases, keywords=n.keywords, body=lifecycle_body(n), decorator_list=n.decorator_list)
            ast.copy_location(c, n)
            n = c
        out.body.append(n)
    return out


def lifecycle_body(cls: ast.ClassDef) -> List[ast.stmt]:
    """Thân class với on_start/on_bar/on_stop thay bằng MỘT `__algorithm__` tổng hợp (giữ nguyên dòng/cột các câu lệnh gốc).
    Class không dùng vòng đời: trả nguyên `cls.body`. Sai hợp đồng -> DslError có dòng/cột."""
    if not has_lifecycle(cls):
        return list(cls.body)
    found: dict = {}
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name == "__algorithm__":
            raise at(st, "Không trộn `__algorithm__` với on_start/on_bar: chọn một dạng (khuyên dùng on_start + on_bar)")
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name in LIFECYCLE:
            if st.name in found:
                raise at(st, f"`{st.name}` được định nghĩa hai lần")
            if (len(st.args.args) != 1 or st.args.args[0].arg != "self" or st.args.vararg or st.args.kwarg or st.args.kwonlyargs
                    or st.args.defaults or st.decorator_list):
                raise at(st, f"Chữ ký phải đúng `def {st.name}(self):`")
            found[st.name] = st
    if "on_bar" not in found:
        raise at(cls, "Thiếu `def on_bar(self):` chứa các luật self.set_positions(mask, position=...)")
    start, bar, stop = found.get("on_start"), found["on_bar"], found.get("on_stop")
    if start is not None:
        bad = _calls_action(start.body)
        if bad is not None:
            raise at(bad, "on_start chỉ KHAI BÁO tham số và chỉ báo; đặt self.set_positions / set_dca_gate trong on_bar")
    if stop is not None and not all(_is_doc(s) or isinstance(s, ast.Pass) for s in stop.body):
        raise at(stop, "on_stop chỉ được có docstring hoặc pass: engine tính vector hoá cả chuỗi nên không có sự kiện dừng để xử lý")
    if _calls_action(bar.body) is None:
        raise at(bar, "on_bar chưa gọi self.set_positions(mask, position=...) nên không có luật nào")
    algo = ast.FunctionDef(name="__algorithm__", args=bar.args, body=(list(start.body) if start is not None else []) + list(bar.body),
                           decorator_list=[], returns=None, type_comment=None)
    ast.copy_location(algo, bar)
    out: List[ast.stmt] = []
    for st in cls.body:
        if isinstance(st, ast.FunctionDef) and st.name in LIFECYCLE:
            if st is bar:
                out.append(algo)
            continue
        out.append(st)
    return out


# ══════════════════════════════════════════════════════════════════════════
# Danh mục nguyên thủy được phép (catalog) — MỘT định nghĩa duy nhất, sinh từ core/indicator (FEATURES/OPS) + thuộc tính hợp đồng.
# Dùng cho cả kiểm lỗi (check_contract) lẫn trợ lý viết code (assist). Không lặp lại danh sách ở nơi khác.
# ══════════════════════════════════════════════════════════════════════════

KIND_ALPHA = "alpha"       # class đơn, compile_program -> Program
KIND_MODULE = "module"     # file chiến lược hệ thống (STRATEGY + p(...)), compile_strategy_module
# ngữ nghĩa duy nhất của thuộc tính/ phương thức chuỗi (.shift/.fillna/.abs) = các op cùng tên
METHOD_OPS = ("shift", "fillna", "abs")
# chỉ báo / operator mà loại `module` (cột kernel) hỗ trợ: lấy từ chính trình biên dịch để không lệch (xem compile._KERNEL_FEATURES)
MODULE_OPS = ("crossed_above", "crossed_below")
P_KWARGS_DOC = {
    "lo": "Cận dưới của khoảng tối ưu (số).", "hi": "Cận trên của khoảng tối ưu (số).", "step": "Bước nhảy khi tối ưu (số).",
    "choices": "Danh sách lựa chọn (khung nến), thay cho lo/hi/step.", "unit": "Đơn vị hiển thị (chuỗi), vd. \"nến\".",
    "label": "Nhãn tiếng Việt trên giao diện (bắt buộc với tham số mới).", "help": "Trợ giúp tiếng Việt (bắt buộc với tham số mới).",
    "grid": "Lưới nhỏ giá trị thử khi quét tham số, vd. (20, 30, 50).", "group": "Nhóm: signal | dca | exit | risk.",
}
STYLES = (
    ("simple_algorithm", "RUN", "class X(SimpleAlgorithm) với def __algorithm__(self) — cú pháp gốc."),
    ("lifecycle", "RUN", "class X(SimpleAlgorithm) với on_start / on_bar / on_stop — hợp đồng kiểu NautilusTrader (khuyên dùng)."),
    ("strategy_module", "RUN", "File chiến lược hệ thống: STRATEGY = {...} + class có id/family/description + p(...)."),
    ("function", "ADAPT", "def strategy(data): trả về {\"entry\": ..., \"exit\": ...}."),
    ("json_spec", "ADAPT", "Bản mô tả JSON: timeframe, params, indicators, entry, exit, short_entry, short_exit."),
    ("ai_python", "ADAPT", "Mã class do AI/nguồn khác sinh: chuẩn hoá tất định (and/or/not, tên cột, lớp cơ sở...) rồi kiểm lại."),
)

_SERIES_TYPE = {"num": "series_num", "bool": "series_bool", "any": "series_any"}
_SERIES_EXAMPLE = {"high": "high", "low": "low", "close": "close", "volume": "volume", "open": "open", "cond": "(close > open)", "b": "open"}


def _default_json(v):
    from backend.core.indicator import REQUIRED
    if v is REQUIRED:
        return None
    return v


def _arg_row(p) -> dict:
    from backend.core.indicator import REQUIRED
    series = p.kind in _SERIES_TYPE
    return {"name": p.name, "type": _SERIES_TYPE.get(p.kind, p.kind), "required": p.default is REQUIRED,
            "default": _default_json(p.default), "lo": None if series else p.lo, "hi": None if series else p.hi}


def _fmt_default(v) -> str:
    return repr(v)


def _call_texts(prefix: str, spec) -> tuple:
    """(signature, example, insert) của self.feat.x(...) / self.op.x(...)."""
    from backend.core.indicator import REQUIRED
    sig, ex, ins = [], [], []
    n = 0
    for p in spec.params:
        series = p.kind in _SERIES_TYPE
        req = p.default is REQUIRED
        sig.append(p.name if req else f"{p.name}={_fmt_default(p.default)}")
        if p.kind == "matype":
            continue
        n += 1
        if not req and p.default is None:        # "không đặt" (vd. clip lower/upper): không đưa vào ví dụ/chèn
            continue
        if req:
            val = ("(close > open)" if p.kind == "bool" else _SERIES_EXAMPLE.get(p.name, "close")) if series else "1"
            ex.append(val)
            ins.append("${%d:%s}" % (n, val))
        else:
            txt = _fmt_default(p.default)
            ex.append(f"{p.name}={txt}")
            ins.append("%s=${%d:%s}" % (p.name, n, txt))
    return f"{prefix}.{spec.name}({', '.join(sig)})", f"{prefix}.{spec.name}({', '.join(ex)})", f"{prefix}.{spec.name}({', '.join(ins)})"


def _returns(spec) -> str:
    if spec.nout > 1:
        return f"tuple[{spec.nout}]"
    return spec.ret if isinstance(spec.ret, str) else "num|bool"


def _doc_vi(spec) -> str:
    head = spec.label_vi or ""
    body = spec.meaning_vi or spec.doc or ""
    return (f"{head}. {body}" if head and body else head or body).strip()


def _spec_row(prefix: str, kind: str, spec, modes: list) -> dict:
    sig, example, insert = _call_texts(prefix, spec)
    return {"name": spec.name, "kind": kind, "category": spec.category or "", "label_vi": spec.label_vi or "", "signature": sig,
            "args": [_arg_row(p) for p in spec.params], "returns": _returns(spec), "outputs": spec.nout,
            "warmup": spec.warmup if isinstance(spec.warmup, (int, str)) else 0, "doc_vi": _doc_vi(spec), "formula": spec.formula or "",
            "read_vi": spec.read_vi or "", "example": example, "insert": insert, "modes": modes}


def _module_features() -> list:
    from backend.alpha.compile import _KERNEL_FEATURES
    return sorted(set(_KERNEL_FEATURES) | {"bbands"})


def _kernel_row(name: str) -> dict:
    """Hàng catalog cho chỉ báo CHỈ có ở cột kernel (indicator.REGISTRY), loại module."""
    from backend.core.indicator import REGISTRY
    ks = REGISTRY[name]
    series = {"atr": ("high", "low", "close"), "adx": ("high", "low", "close")}.get(name, ("real",))
    args = [{"name": a, "type": "series_num", "required": True, "default": None, "lo": None, "hi": None} for a in series]
    args += [{"name": n, "type": "int", "required": False, "default": int(d), "lo": 1, "hi": 5000} for n, d in zip(("timeperiod",), ks.defaults[:1])]
    sig = f"self.feat.{name}({', '.join(a['name'] if a['required'] else a['name'] + '=' + repr(a['default']) for a in args)})"
    ex = f"self.feat.{name}({', '.join(a['name'] if a['required'] else a['name'] + '=' + repr(a['default']) for a in args)})".replace("(real", "(close")
    ins = "self.feat.%s(${1:close}, timeperiod=${2:%d})" % (name, int(ks.defaults[0]))
    return {"name": name, "kind": "feature", "category": (ks.group or "").lower(), "label_vi": "", "signature": sig, "args": args, "returns": "num", "outputs": 1,
            "warmup": 0, "doc_vi": ks.description, "formula": "", "read_vi": "", "example": ex, "insert": ins, "modes": ["module"]}


def build_catalog() -> dict:
    """Danh mục đầy đủ (không có `version`; xem `catalog()`)."""
    from backend.core.indicator import FEATURES, OPS
    from backend.core.params import EXIT_RISK_SPEC, FRAMES, POSITION_KEYS
    from backend.core.signal import DATA_COLUMNS, DSL_VERSION
    mod_feat = set(_module_features())
    features = [_spec_row("self.feat", "feature", FEATURES[n], ["alpha", "module"] if n in mod_feat else ["alpha"]) for n in sorted(FEATURES)]
    features += [_kernel_row(n) for n in sorted(mod_feat - set(FEATURES))]     # cột kernel chỉ có ở loại module (vd. er)
    features.sort(key=lambda r: r["name"])
    ops = [_spec_row("self.op", "op", OPS[n], ["alpha", "module"] if n in MODULE_OPS else ["alpha"]) for n in sorted(OPS)]
    methods = []
    for m in METHOD_OPS:
        sp = OPS[m]
        rest = [p for p in sp.params[1:]]
        sig = ", ".join(p.name if p.default.__class__.__name__ == "object" else f"{p.name}={_fmt_default(p.default)}" for p in rest)
        ins = ", ".join("${%d:%s}" % (i + 1, _fmt_default(p.default) if p.default.__class__.__name__ != "object" else p.name) for i, p in enumerate(rest))
        methods.append({"name": m, "op": m, "signature": f"<chuỗi>.{m}({sig})", "doc_vi": _doc_vi(sp), "insert": f".{m}({ins})"})
    data = [{"name": f"pv_{c}", "column": c, "signature": f"self.data.pv_{c}",
             "doc_vi": {"open": "Giá mở cửa", "high": "Giá cao nhất", "low": "Giá thấp nhất", "close": "Giá đóng cửa", "volume": "Khối lượng"}.get(c, c)} for c in DATA_COLUMNS]
    tf_doc = "Khung nến của chiến lược, một trong " + ", ".join(FRAMES) + " (mặc định 24h)."
    class_alpha = [
        {"name": "timeframe", "type": "str", "choices": list(FRAMES), "doc_vi": tf_doc, "insert": 'timeframe = "${1:4h}"'},
        {"name": "position_open_times", "type": "list[str]", "choices": None, "doc_vi": 'Giờ UTC "HH:MM" được phép MỞ vị thế.', "insert": 'position_open_times = ["${1:00:00}"]'},
        {"name": "position_open_ranges", "type": "list[str]", "choices": None, "doc_vi": 'Khoảng giờ UTC "HH:MM-HH:MM" được phép mở vị thế.', "insert": 'position_open_ranges = ["${1:08:00-16:00}"]'},
        {"name": "position_close_ranges", "type": "list[str]", "choices": None, "doc_vi": 'Khoảng giờ UTC bắt buộc đóng vị thế (mức 0).', "insert": 'position_close_ranges = ["${1:22:00-23:59}"]'},
    ] + [{"name": k, "type": "position_key", "choices": None, "doc_vi": f"Khoá vị thế {k} (như tham số vị thế khi chạy backtest).", "insert": f"{k} = ${{1:value}}"}
         for k in POSITION_KEYS]
    class_module = [
        {"name": "id", "type": "str", "choices": None, "doc_vi": "Mã chân chiến lược (duy nhất), vd. \"kema_long\".", "insert": 'id = "${1:my_long}"'},
        {"name": "family", "type": "str", "choices": None, "doc_vi": "Tên họ chiến lược hiển thị.", "insert": 'family = "${1:Tên họ}"'},
        {"name": "description", "type": "str", "choices": None, "doc_vi": "Mô tả chân.", "insert": 'description = "${1:Mô tả}"'},
        {"name": "side", "type": "str", "choices": ["LONG", "SHORT"], "doc_vi": "Chiều chân (tuỳ chọn; phải khớp set_positions).", "insert": 'side = "${1:LONG}"'},
        {"name": "position", "type": "dict", "choices": None, "doc_vi": "Khoá vị thế mặc định của chân, vd. {'exit_unit': 'atr'}.", "insert": "position = {${1}}"},
    ]
    pos_rows = []
    for k in POSITION_KEYS:
        base = EXIT_RISK_SPEC.get(k)
        if base is None:
            pos_rows.append({"name": k, "label_vi": k, "lo": None, "hi": None, "unit": "", "doc_vi": ""})
        else:
            kind0, _g, label0, _d, lo0, hi0, _st, unit0, help0 = base
            pos_rows.append({"name": k, "label_vi": label0, "lo": None if kind0 == "choice" else lo0, "hi": None if kind0 == "choice" else hi0,
                             "unit": unit0 or "", "doc_vi": help0 or ""})
    lifecycle = [
        {"name": "on_start", "required": False, "doc_vi": "Khai báo tham số và chỉ báo (không đặt vị thế).", "insert": "def on_start(self):\n    ${1:close = self.data.pv_close}"},
        {"name": "on_bar", "required": True, "doc_vi": "Các luật vào/thoát/dừng: self.set_positions(mask, position=...). Engine tính vector hoá cho cả chuỗi.",
         "insert": "def on_bar(self):\n    self.set_positions(${1:mask}, position=${2:1})"},
        {"name": "on_stop", "required": False, "doc_vi": "Tuỳ chọn, no-op (chỉ docstring/pass).", "insert": "def on_stop(self):\n    pass"},
        {"name": "__algorithm__", "required": False, "doc_vi": "Dạng gốc tương đương on_start + on_bar.", "insert": "def __algorithm__(self):\n    ${1:pass}"},
        {"name": "set_positions", "required": False, "doc_vi": "self.set_positions(mask, position=w): w = 1 vào long, -1 vào short, 0 thoát; lệnh sau ghi đè lệnh trước.",
         "insert": "self.set_positions(${1:mask}, position=${2:1})"},
        {"name": "set_dca_gate", "required": False, "doc_vi": "(loại module) Cổng cho phép dồn tầng DCA.", "insert": "self.set_dca_gate(${1:mask})"},
        {"name": "frame", "required": False, "doc_vi": "(loại module) Chọn khung nến: self.frame('4h') hoặc self.frame(p('signal_tf', '4h', choices=(...))).", "insert": "self.frame(${1:'4h'})"},
    ]
    snippets = [
        {"label": "Chiến lược (on_start/on_bar)", "doc_vi": "Khung chiến lược theo hợp đồng vòng đời.", "insert":
         'class ${1:MyStrategy}(SimpleAlgorithm):\n    timeframe = "${2:4h}"\n\n    def on_start(self):\n        close = self.data.pv_close\n        ema = self.feat.ema(close, ${3:20})\n\n'
         '    def on_bar(self):\n        self.set_positions(close < ema, position=0)\n        self.set_positions(self.op.crossed_above(close, ema), position=1)\n'},
        {"label": "Kênh Keltner", "doc_vi": "EMA ± k × ATR.", "insert": "ema = self.feat.ema(close, ${1:20})\natr = self.feat.atr(high, low, close, ${2:14})\nupper = ema + ${3:2.0} * atr\nlower = ema - ${3:2.0} * atr\n"},
        {"label": "Hàm strategy(data)", "doc_vi": "Dạng hàm (ADAPT).", "insert": 'timeframe = "${1:4h}"\n\ndef strategy(data):\n    close = data.close\n    ema = feat.ema(close, ${2:20})\n    return {"entry": op.crossed_above(close, ema), "exit": close < ema}\n'},
    ]
    return {
        "dsl_version": DSL_VERSION, "styles": [{"style": s, "verdict": v, "label_vi": d} for s, v, d in STYLES], "lifecycle": lifecycle,
        "features": features, "ops": ops, "methods": methods, "data": data, "class_attrs": {"alpha": class_alpha, "module": class_module},
        "position_keys": pos_rows, "frames": list(FRAMES), "p_kwargs": [{"name": k, "doc_vi": P_KWARGS_DOC[k]} for k in ("lo", "hi", "step", "choices", "unit", "label", "help", "grid", "group")],
        "snippets": snippets,
    }


_CATALOG_CACHE: dict = {}


def catalog() -> dict:
    """Catalog + `version` (sha1[:12] nội dung): đổi khi thêm/bớt chỉ báo hay sửa spec."""
    if not _CATALOG_CACHE:
        import hashlib
        import json
        cat = build_catalog()
        ver = hashlib.sha1(json.dumps(cat, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]
        _CATALOG_CACHE.update({"version": ver, **cat})
    return _CATALOG_CACHE


# ══════════════════════════════════════════════════════════════════════════
# check_contract — kiểm hợp đồng + chuyển đổi; verdict RUN | ADAPT | REJECT. Thân thực thi (analyze) nằm ở alpha/compile.py (registry style -> adapter).
# ══════════════════════════════════════════════════════════════════════════

_CODE_RULES = (
    (r"^Lỗi cú pháp", "SYNTAX"), (r"^Mã quá dài", "TOO_LARGE"), (r"^Không phân tích", "SYNTAX"),
    (r"self\.feat\.\w+ chưa", "UNKNOWN_FEATURE"), (r"self\.op\.\w+ chưa", "UNKNOWN_OP"),
    (r"^Biến `.*` chưa được gán|^`\w+` không có sẵn", "UNKNOWN_NAME"),
    (r"self\.data\.\w+ không có|chưa được khai báo ở cấp class|Thuộc tính lớp `|Khoá của STRATEGY|STRATEGY không có khoá", "UNKNOWN_ATTR"),
    (r"on_start|on_bar|on_stop|__algorithm__", "BAD_LIFECYCLE"),
    (r"phải trong \[|ngoài \[|ngoài khoảng|phải trong \[-1", "OUT_OF_RANGE"),
    (r"p\(|Tham số `|Tham số tín hiệu|choices|grid", "BAD_PARAM"),
    (r"không có tham số|thiếu đối số|nhận tối đa|bị truyền hai lần|Thiếu `position=`|Thiếu mặt nạ|chỉ nhận mặt nạ", "BAD_ARGUMENT"),
    (r"phải là hằng số|cần một chuỗi|cần chuỗi số|cần mặt nạ|chuỗi bool|phải là số nguyên|Toán hạng|hai vế là số|chỉ dùng cho", "BAD_TYPE"),
    (r"Thiếu `STRATEGY|STRATEGY phải", "NO_STRATEGY"),
    (r"Cần đúng một class|Cần ít nhất một class|Class phải có dạng|Ở cấp ngoài|Trong class chỉ|Thiếu `def|Chữ ký", "BAD_STRUCTURE"),
    (r"không dùng được|Không dùng|Chưa hỗ trợ|chưa được hỗ trợ|chưa hỗ trợ|không hỗ trợ", "FORBIDDEN_SYNTAX"),
)


def classify(message: str) -> str:
    import re
    for pat, code in _CODE_RULES:
        if re.search(pat, message):
            return code
    return "COMPILE"


def split_suggest(message: str) -> tuple:
    """(message không có đuôi ' Gần đúng: a, b.', [a, b])."""
    import re
    m = re.search(r" Gần đúng: (.*?)\.(?=\s|$)", message)
    if not m:
        return message, []
    return (message[:m.start()] + message[m.end():]).strip(), [x.strip() for x in m.group(1).split(",") if x.strip()]


def check_contract(code) -> dict:
    """check_contract(code) -> {verdict, style, kind, diagnostics[], normalized_code, ir}. Xem docs/bmad/p10_alpha_contract.md §2."""
    from backend.alpha.compile import analyze
    return analyze(code)


# ═══ Trợ lý viết code tất định (P10; gộp từ alpha/assist) ═══

_IDENT = re.compile(r"[A-Za-z_]\w*")
_FRAME_STR = re.compile(r"""(?:timeframe\s*=\s*|self\.frame\(\s*|choices\s*=\s*[\(\[][^\)\]]*|atr_frame\W+|_tf\W+)["'][\w]*$""")


# ─── chỉ mục catalog ─────────────────────────────────────────────────────────

def _index() -> Dict[str, Any]:
    cat = catalog()
    if "_idx" not in cat:
        cat["_idx"] = {
            "feat": {r["name"]: r for r in cat["features"]}, "op": {r["name"]: r for r in cat["ops"]},
            "method": {r["name"]: r for r in cat["methods"]}, "data": {r["name"]: r for r in cat["data"]},
            "alpha": {r["name"]: r for r in cat["class_attrs"]["alpha"]}, "module": {r["name"]: r for r in cat["class_attrs"]["module"]},
            "life": {r["name"]: r for r in cat["lifecycle"]}, "pkw": {r["name"]: r for r in cat["p_kwargs"]},
        }
    return cat["_idx"]


def _fmt_range(a: dict) -> str:
    if a["type"] in ("int", "float") and a["lo"] is not None and a["hi"] is not None:
        return f"[{a['lo']:g}, {a['hi']:g}]"
    return ""


def _args_md(row: dict) -> str:
    out = []
    for a in row["args"]:
        t = {"series_num": "chuỗi số", "series_bool": "mặt nạ bool", "series_any": "chuỗi số/bool", "int": "số nguyên", "float": "số thực",
             "matype": "kiểu MA (chỉ 0 = SMA)"}.get(a["type"], a["type"])
        extra = "bắt buộc" if a["required"] else f"mặc định {a['default']!r}"
        rng = _fmt_range(a)
        out.append(f"- `{a['name']}`: {t}, {extra}" + (f", khoảng {rng}" if rng else ""))
    return "\n".join(out)


def _row_md(row: dict) -> str:
    parts = [f"**{row['name']}**" + (f" — {row['label_vi']}" if row.get("label_vi") else ""), f"```python\n{row['signature']}\n```"]
    if row.get("doc_vi"):
        parts.append(row["doc_vi"])
    parts.append(f"Trả về: `{row['returns']}`" + (f" ({row['outputs']} đầu ra)" if row.get("outputs", 1) > 1 else "")
                 + (f" · khởi động ~{row['warmup']} nến" if row.get("warmup") else ""))
    parts.append("Tham số:\n" + _args_md(row))
    if row.get("formula"):
        parts.append(f"Công thức: `{row['formula']}`")
    if row.get("read_vi"):
        parts.append(f"Cách đọc: {row['read_vi']}")
    parts.append(f"Ví dụ: `{row['example']}`")
    return "\n\n".join(parts)


# ─── tokenize chịu lỗi: ngữ cảnh lời gọi tại một vị trí ──────────────────────

def _offsets(text: str) -> List[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _to_offset(starts: List[int], line: int, col: int, text: str) -> int:
    if line < 1:
        return 0
    if line > len(starts):
        return len(text)
    return min(starts[line - 1] + max(col - 1, 0), len(text))


def _tokens(text: str) -> List[tokenize.TokenInfo]:
    toks: List[tokenize.TokenInfo] = []
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            toks.append(t)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return toks


def _call_stack(text: str, upto: int) -> List[Dict[str, Any]]:
    """Ngăn xếp lời gọi chưa đóng tại offset `upto`: [{name, open (offset), arg (chỉ số đối số hiện tại), kwargs (đã có), at_start (đang ở đầu một đối số)}]."""
    starts = _offsets(text)
    sub = text[:upto]
    toks = _tokens(sub)
    stack: List[Dict[str, Any]] = []
    prev: List[tokenize.TokenInfo] = []
    for i, t in enumerate(toks):
        if t.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        off = starts[t.start[0] - 1] + t.start[1]
        if off >= upto:
            break
        if t.string in "([{" and t.type == tokenize.OP:
            name = None
            if t.string == "(":
                chain, j = [], len(prev) - 1
                while j >= 0 and (prev[j].type == tokenize.NAME or prev[j].string == "."):
                    chain.append(prev[j].string)
                    j -= 1
                name = "".join(reversed(chain)) or None
            stack.append({"name": name, "open": off, "arg": 0, "kwargs": set(), "at_start": True, "brk": t.string})
        elif t.string in ")]}" and t.type == tokenize.OP:
            if stack:
                stack.pop()
        elif t.string == "," and t.type == tokenize.OP and stack:
            stack[-1]["arg"] += 1
            stack[-1]["at_start"] = True
        else:
            if stack:
                stack[-1]["at_start"] = False
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if t.type == tokenize.NAME and nxt is not None and nxt.string == "=" and stack[-1]["at_start"] is False and (
                        not prev or prev[-1].string in ("(", ",")):
                    stack[-1]["kwargs"].add(t.string)
        prev.append(t)
    return stack


def _match_paren(text: str, open_off: int) -> Optional[int]:
    depth, i, n = 0, open_off, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            q = ch
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif ch == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


# ─── ngữ cảnh văn bản ────────────────────────────────────────────────────────

def _is_module_style(code: str) -> bool:
    return re.search(r"^STRATEGY\s*=", code, re.M) is not None


def _locals(code: str) -> List[str]:
    names: List[str] = []
    for m in re.finditer(r"^(?: {8,}|\t\t)([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*=(?!=)", code, re.M):
        for n in re.split(r"\s*,\s*", m.group(1)):
            if n not in names and n != "self":
                names.append(n)
    return names


def _frame_vars(code: str) -> List[str]:
    return [m.group(1) for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s*=\s*self\.frame\(", code, re.M)]


def _scope(lines: List[str], line: int) -> str:
    """'module' | 'class' | 'method' của dòng `line` theo thụt lề (dòng trống lấy theo con trỏ: coi như thụt lề của dòng trước)."""
    cur = lines[line - 1] if 0 < line <= len(lines) else ""
    indent = len(cur) - len(cur.lstrip()) if cur.strip() else None
    if indent is None:
        j = line - 2
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            return "module"
        prev = lines[j]
        indent = len(prev) - len(prev.lstrip())
        if prev.rstrip().endswith(":"):
            indent += 4
    if indent == 0:
        return "module"
    j = line - 2
    while j >= 0:
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) < indent:
            s = ln.strip()
            if s.startswith("def "):
                return "method"
            if s.startswith("class "):
                return "class"
            indent = len(ln) - len(ln.lstrip())
            if indent == 0:
                return "module"
        j -= 1
    return "module"


def _item(label: str, kind: str, detail: str, insert: str, doc_md: str = "", snippet: bool = False) -> Dict[str, Any]:
    return {"label": label, "kind": kind, "detail": detail, "insert": insert, "is_snippet": snippet or "${" in insert, "doc_md": doc_md}


def _member(row: dict, prefix: str) -> str:
    return row["insert"][len(prefix):] if row["insert"].startswith(prefix) else row["insert"]


def _rank(items: List[Dict[str, Any]], typed: str) -> List[Dict[str, Any]]:
    t = typed.lower()
    if not t:
        return items
    keep = [it for it in items if t in it["label"].lower()]
    keep.sort(key=lambda it: (not it["label"].lower().startswith(t), it["label"]))
    return keep


# ─── gợi ý ───────────────────────────────────────────────────────────────────

def complete(code: str, line: int, col: int) -> Dict[str, Any]:
    idx = _index()
    cat = catalog()
    lines = code.split("\n")
    cur = lines[line - 1] if 0 < line <= len(lines) else ""
    prefix = cur[:max(col - 1, 0)]
    m = re.search(r"[A-Za-z_]\w*$", prefix)
    typed = m.group(0) if m else ""
    before = prefix[:len(prefix) - len(typed)]
    rng = {"line": line, "col": col - len(typed), "end_line": line, "end_col": col}
    items: List[Dict[str, Any]] = []

    # 1) bên trong chuỗi
    q = re.search(r"""["'][\w]*$""", prefix)
    if q:
        sm = _FRAME_STR.search(prefix)
        word = re.search(r"[\w]*$", prefix).group(0)
        rng["col"] = col - len(word)
        if sm:
            items = [_item(f, "keyword", "khung nến", f, f"Khung nến **{f}**") for f in cat["frames"]]
        elif re.search(r"\bside\s*=\s*[\"'][\w]*$", prefix):
            items = [_item(v, "keyword", "chiều chân", v) for v in ("LONG", "SHORT")]
        elif re.search(r"\bgroup\s*=\s*[\"'][\w]*$", prefix):
            items = [_item(v, "keyword", "nhóm tham số", v) for v in ("signal", "dca", "exit", "risk")]
        return {"items": _rank(items, word), "range": rng}

    # 2) self.<ns>.<…>
    if before.endswith("self.feat."):
        items = [_item(r["name"], "feature", r["signature"], _member(r, "self.feat."), _row_md(r), True) for r in cat["features"]]
        return {"items": _rank(items, typed), "range": rng}
    if before.endswith("self.op."):
        items = [_item(r["name"], "op", r["signature"], _member(r, "self.op."), _row_md(r), True) for r in cat["ops"]]
        return {"items": _rank(items, typed), "range": rng}
    if before.endswith("self.data."):
        items = [_item(r["name"], "attr", r["signature"], r["name"], f"**{r['signature']}** — {r['doc_vi']}") for r in cat["data"]]
        return {"items": _rank(items, typed), "range": rng}
    if before.endswith("self."):
        items = [_item("feat", "attr", "self.feat.<chỉ báo>", "feat.", "Chỉ báo kỹ thuật (xem danh mục)."),
                 _item("op", "attr", "self.op.<operator>", "op.", "Operator: crossed_above, where, shift, ..."),
                 _item("data", "attr", "self.data.pv_*", "data.", "Cột nến OHLCV đã đóng."),
                 _item("set_positions", "method", "self.set_positions(mask, position=w)", "set_positions(${1:mask}, position=${2:1})", idx["life"]["set_positions"]["doc_vi"], True)]
        if _is_module_style(code):
            items += [_item("set_dca_gate", "method", "self.set_dca_gate(mask)", "set_dca_gate(${1:mask})", idx["life"]["set_dca_gate"]["doc_vi"], True),
                      _item("frame", "method", "self.frame(khung)", "frame(${1:'4h'})", idx["life"]["frame"]["doc_vi"], True)]
        return {"items": _rank(items, typed), "range": rng}

    # 3) <biểu thức>.<…>
    if before.endswith(".") and not before.endswith("self."):
        left = before[:-1]
        mv = re.search(r"([A-Za-z_]\w*)$", left)
        if mv and mv.group(1) in _frame_vars(code):
            items = [_item(r["name"], "attr", r["signature"], r["name"], f"**{r['signature']}** — {r['doc_vi']}") for r in cat["data"]]
        else:
            items = [_item(r["name"], "method", r["signature"], _member(r, "."), f"**{r['signature']}**\n\n{r['doc_vi']}", True) for r in cat["methods"]]
        return {"items": _rank(items, typed), "range": rng}

    # 4) trong lời gọi
    starts = _offsets(code)
    off = _to_offset(starts, line, col - len(typed), code)
    stack = _call_stack(code, off)
    top = stack[-1] if stack else None
    if top is not None and top["name"] is not None and top["brk"] == "(":
        name = top["name"]
        if name == "p" and top["at_start"] and top["arg"] >= 1:
            items = [_item(f"{r['name']}=", "param", "đối số p()", f"{r['name']}=${{1}}", r["doc_vi"], True)
                     for r in cat["p_kwargs"] if r["name"] not in top["kwargs"]]
            return {"items": _rank(items, typed), "range": rng}
        mm = re.fullmatch(r"self\.(feat|op)\.(\w+)", name)
        row = idx[mm.group(1)].get(mm.group(2)) if mm else None
        if row is not None and (top["at_start"] or typed):
            for k, a in enumerate(row["args"]):
                if a["name"] in top["kwargs"] or a["type"] == "matype" or k < top["arg"]:
                    continue
                rg = _fmt_range(a)
                items.append(_item(f"{a['name']}=", "param", f"{a['type']}" + (f" {rg}" if rg else "") + ("" if a["required"] else f", mặc định {a['default']!r}"),
                                   f"{a['name']}=${{1:{a['default'] if not a['required'] else ''}}}", f"Tham số `{a['name']}` của **{row['name']}**", True))
            items += [_item(v, "attr", "biến", v) for v in _locals(code)] + \
                     [_item(r["name"], "attr", r["signature"], f"self.data.{r['name']}", r["doc_vi"]) for r in cat["data"]]
            return {"items": _rank(items, typed), "range": rng}

    # 5) đầu câu lệnh
    scope = _scope(lines, line)
    kind = "module" if _is_module_style(code) else "alpha"
    if scope == "module":
        items = [_item(s["label"], "snippet", "mẫu", s["insert"], s["doc_vi"], True) for s in cat["snippets"]]
        items += [_item("class", "keyword", "class X(SimpleAlgorithm):", "class ${1:MyStrategy}(SimpleAlgorithm):\n    ${2:pass}", "Khai báo chiến lược.", True),
                  _item("STRATEGY", "keyword", "STRATEGY = {...}", 'STRATEGY = {\n    "id": "${1:my}", "name": "${2:Tên}", "kind": "${3:Loại}",\n    "description": "${4:Mô tả}", "idea": "${5:Ý tưởng}", "order": 9,\n}', "Mô tả họ chiến lược (loại module).", True)]
    elif scope == "class":
        items = [_item(r["name"], "method", f"def {r['name']}(self)", r["insert"], r["doc_vi"], True) for r in cat["lifecycle"][:4]]
        items += [_item(r["name"], "attr", r["type"], r["insert"], r["doc_vi"], True) for r in cat["class_attrs"][kind]]
    else:
        items = [_item(v, "attr", "biến cục bộ", v) for v in _locals(code)]
        items += [_item("self", "keyword", "self", "self"), _item("close", "snippet", "cột giá đóng", "close = self.data.pv_close", "Gán cột giá đóng cửa.", False),
                  _item("set_positions", "snippet", "self.set_positions(mask, position=w)", "self.set_positions(${1:mask}, position=${2:1})", idx["life"]["set_positions"]["doc_vi"], True)]
        if kind == "module":
            items.append(_item("p", "keyword", "p(tên, mặc_định, lo=, hi=, step=, ...)", "p('${1:name}', ${2:20}, lo=${3:5}, hi=${4:100}, step=${5:1}, label=\"${6:Nhãn}\", help=\"${7:Trợ giúp}\")",
                               "Khai báo tham số tối ưu được.", True))
    return {"items": _rank(items, typed), "range": rng}


# ─── hover ───────────────────────────────────────────────────────────────────

def _word_at(line: str, col: int) -> Optional[Tuple[str, int, int]]:
    """(từ, cột bắt đầu 1-based, cột kết thúc loại trừ) quanh vị trí con trỏ."""
    pos = max(col - 1, 0)
    for m in _IDENT.finditer(line):
        if m.start() <= pos <= m.end():
            return m.group(0), m.start() + 1, m.end() + 1
    return None


def _p_md(call_src: str) -> Optional[str]:
    try:
        node = ast.parse(call_src, mode="eval").body
    except SyntaxError:
        return None
    if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)):
        return None
    name = node.args[0].value

    def lit(n):
        try:
            return ast.literal_eval(n)
        except (ValueError, SyntaxError):
            return None
    kw = {k.arg: lit(k.value) for k in node.keywords if k.arg}
    default = lit(node.args[1]) if len(node.args) > 1 else None
    if len(node.args) == 1 and not kw:
        return f"**{name}** — tham chiếu tới tham số đã khai báo `p('{name}', ...)`"
    if "choices" in kw:
        body = f"lựa chọn {list(kw['choices'])}, mặc định `{default}`"
    elif all(k in kw for k in ("lo", "hi", "step")):
        typ = "int" if all(isinstance(v, int) and not isinstance(v, bool) for v in (kw["lo"], kw["hi"], kw["step"], default)) else "float"
        body = f"{typ}, mặc định `{default}`, khoảng **[{kw['lo']}, {kw['hi']}]** bước {kw['step']}" + (f" {kw['unit']}" if kw.get("unit") else "")
    else:
        body = f"mặc định `{default}` (khoảng lấy từ bảng thoát/rủi ro chung nếu là khoá vị thế)"
    out = f"**{name}** — {body}"
    if kw.get("label"):
        out += f"\n\nNhãn: {kw['label']}"
    if kw.get("help"):
        out += f"\n\n{kw['help']}"
    if kw.get("grid"):
        out += f"\n\nLưới thử: `{list(kw['grid'])}`"
    return out


def hover(code: str, line: int, col: int) -> Dict[str, Any]:
    idx = _index()
    lines = code.split("\n")
    if not (0 < line <= len(lines)):
        return {"md": None, "range": None}
    cur = lines[line - 1]
    w = _word_at(cur, col)
    starts = _offsets(code)
    off = _to_offset(starts, line, col, code)
    stack = _call_stack(code, off)
    top = stack[-1] if stack else None

    def out(md, a=None, b=None):
        return {"md": md, "range": {"line": line, "col": a, "end_line": line, "end_col": b} if md and a else None}

    if w is not None:
        word, a, b = w
        before = cur[:a - 1]
        # self.feat.X / self.op.X / self.data.X / .method
        if before.endswith("self.feat.") and word in idx["feat"]:
            return out(_row_md(idx["feat"][word]), a, b)
        if before.endswith("self.op.") and word in idx["op"]:
            return out(_row_md(idx["op"][word]), a, b)
        if before.endswith("self.data.") and word in idx["data"]:
            r = idx["data"][word]
            return out(f"**{r['signature']}** — {r['doc_vi']}", a, b)
        if before.endswith(".") and word in idx["method"] and not before.endswith(("self.", "self.feat.", "self.op.")):
            r = idx["method"][word]
            return out(f"**{r['signature']}**\n\n{r['doc_vi']}", a, b)
        # kwarg của feature/op/p() — từ theo sau bởi '='
        rest = cur[b - 1:].lstrip()
        if rest.startswith("=") and not rest.startswith("==") and top is not None and top["name"]:
            mm = re.fullmatch(r"self\.(feat|op)\.(\w+)", top["name"])
            if mm and mm.group(2) in idx[mm.group(1)]:
                for arg in idx[mm.group(1)][mm.group(2)]["args"]:
                    if arg["name"] == word:
                        rg = _fmt_range(arg)
                        return out(f"**{word}** — tham số của `{mm.group(2)}`: {arg['type']}" + ("" if arg["required"] else f", mặc định `{arg['default']}`")
                                   + (f", khoảng **{rg}**" if rg else ""), a, b)
            if top["name"] == "p" and word in idx["pkw"]:
                return out(f"**{word}=** — {idx['pkw'][word]['doc_vi']}", a, b)
        # thuộc tính lớp / vòng đời / từ khoá hợp đồng
        kind = "module" if _is_module_style(code) else "alpha"
        if re.match(r"\s+(def\s+)?\w+", cur) and word in idx["life"] and (cur.strip().startswith("def ") or before.endswith("self.")):
            r = idx["life"][word]
            return out(f"**{word}** — {r['doc_vi']}", a, b)
        if word in idx[kind] and re.match(rf"\s+{word}\s*=", cur):
            r = idx[kind][word]
            return out(f"**{word}** ({r['type']}) — {r['doc_vi']}", a, b)
        if before.endswith("self.") and word in idx["life"]:
            return out(f"**{word}** — {idx['life'][word]['doc_vi']}", a, b)
        if word == "p" and cur[b - 1:].startswith("("):
            open_off = starts[line - 1] + b - 1
            end = _match_paren(code, open_off)
            if end is not None:
                md = _p_md("p" + code[open_off:end + 1])
                if md:
                    return out(md, a, b)
        # biến cục bộ: hiện dòng gán
        for m in re.finditer(rf"^[ \t]+(?:[\w, ]+,\s*)?{re.escape(word)}(?:\s*,[\w, ]+)?\s*=(?!=)\s*(.+)$", code, re.M):
            return out(f"**{word}** — biến cục bộ\n\n```python\n{m.group(0).strip()}\n```", a, b)
    # đang ở trong p(...) (hover vào tên/số bên trong) -> khoảng đã khai báo
    if top is not None and top["name"] == "p" and top["brk"] == "(":
        end = _match_paren(code, top["open"])
        if end is not None:
            md = _p_md("p" + code[top["open"]:end + 1])
            if md:
                return out(md, w[1] if w else col, w[2] if w else col + 1)
    # số / đối số vị trí trong feature/op -> khoảng hợp lệ
    if top is not None and top["name"] and top["brk"] == "(":
        mm = re.fullmatch(r"self\.(feat|op)\.(\w+)", top["name"])
        if mm and mm.group(2) in idx[mm.group(1)] and w is None:
            row = idx[mm.group(1)][mm.group(2)]
            if top["arg"] < len(row["args"]):
                arg = row["args"][top["arg"]]
                rg = _fmt_range(arg)
                return out(f"**{arg['name']}** — đối số {top['arg'] + 1} của `{row['name']}`: {arg['type']}" + (f", khoảng **{rg}**" if rg else ""),
                           col, col + 1)
    return {"md": None, "range": None}
