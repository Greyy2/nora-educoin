"""Lint NGHIÊM NGẶT 50 mẫu chiến lược giáo dục (frontend/src/components/education/educationSamples.js).

Nguyên tắc: không dùng LLM; mọi câu giải thích phải ĐÚNG với code VÀ hồ sơ thực thi (xno | nora) mà mẫu chạy.
Phần viết tay chỉ là lý thuyết ("Khái niệm tài chính"); quy tắc / chỉ báo / thực thi do explain.py sinh lúc chạy nên KHÔNG lặp lại trong docstring.

Mã thoát khác 0 nếu có bất kỳ lỗi nào. Chạy:  backend/utils/ops/run_limited.sh --no-lock -- test/scripts/lint_edu_samples.py [đường_dẫn_samples.js]

Quy tắc (mã lỗi ở đầu mỗi dòng báo cáo):
  SCHEMA    đủ key/name/category/difficulty/summary/code/profile; category thuộc 5 nhóm (mỗi nhóm 10 mẫu); difficulty hợp lệ; key & name duy nhất;
            summary, docstring bằng tiếng Việt; xno không có `position`; nora: `position` chỉ gồm khoá hợp lệ (params.builder.POSITION_KEYS).
  COMPILE   compile_code() thành công; feature / operator tồn tại; build_plan() của hồ sơ khai báo dựng được.
  BOILER    docstring không còn khung "Trading Rules" / "STEP n" / "Financial Concept:"; chỉ là đoạn lý thuyết ngắn.
  NUMBA     không nhắc "Numba" (DSL là numpy/pandas) ở bất kỳ đâu trong mẫu.
  RISK      nhắc stop-loss / cắt lỗ / take-profit / chốt lời / trailing / timeout (thời gian giữ tối đa) chỉ khi (a) hồ sơ nora VÀ tham số vị thế
            tương ứng được khai báo trong `position`, hoặc (b) câu đó nói rõ là thoát THEO TÍN HIỆU và code có luật thoát, hoặc (c) câu phủ định
            ("không ...") mà tham số đó thực sự bằng 0 ở hồ sơ hiệu lực.
  RISKNUM   hồ sơ nora: số "N×ATR" gần từ khoá SL/TP/trailing phải bằng tham số vị thế khai báo.
  SHORT     nhắc short / bán khống khi chương trình không có chân SHORT.
  EXEC      câu về thực thi (spot, perp, đòn bẩy, phí, trượt giá, funding, next open, rổ TOP10, cooldown...) thuộc explain.py, không viết tay.
  INDIC     nhắc chỉ báo (EMA, RSI, ATR, MACD, Bollinger, ADX, Donchian, VWAP, ...) mà chương trình không dùng.
  NUMBER    mọi số trong tên / tóm tắt / docstring / chú thích phải là hằng số có thật trong chương trình (tham số chỉ báo, ngưỡng, bội số)
            hoặc tham số vị thế của hồ sơ; kèm kiểm tra riêng "EMA 20", "RSI < 30", "2×ATR" so với đúng chỉ báo / ngưỡng / hướng so sánh.
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_NORA = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _NORA not in sys.path:
    sys.path.insert(0, _NORA)

from backend.core.strategy.pydsl import compile_code  # noqa: E402
from backend.core.strategy.pydsl import profiles  # noqa: E402
from backend.core.strategy.pydsl.explain import explain_program  # noqa: E402
from backend.core.strategy.pydsl.program import Bin, BoolConst, Call, Cmp, Const, Data, Inv, Logic, Neg, Pick  # noqa: E402
from backend.core.strategy.pydsl.spec import FEATURE_SPECS_DATA, OP_SPECS_DATA  # noqa: E402
from backend.core.params.builder import POSITION_KEYS  # noqa: E402

SAMPLES_PATH = os.path.join(_NORA, "frontend", "src", "components", "education", "educationSamples.js")
CATEGORIES = ["Trend Following", "Mean Reversion", "Breakout & Momentum", "Multi-Indicator Confluence", "Risk-Managed & Exits"]
DIFFICULTIES = {"Beginner", "Intermediate", "Advanced"}
PROFILES = {"xno", "nora"}
PER_CATEGORY = 10
MAX_DOC_CHARS = 700

VI_CHARS = "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"

# ─── từ khoá rủi ro → tham số vị thế tương ứng ────────────────────────────────────────
RISK_TERMS = {
    "stop_loss_rate": r"stop[\s-]?loss|\bSL\b|cắt\s+lỗ|dừng\s+lỗ|\bstop\b",
    "take_profit_rate": r"take[\s-]?profit|\bTP\b|chốt\s+lời|chốt\s+lãi",
    "trailing_stop": r"trailing|bám\s+đuôi",
    "timeout": r"time[\s-]?out|thời\s+gian\s+giữ\s+tối\s+đa|hết\s+hạn\s+giữ",
}
SIGNAL_EXIT = re.compile(r"theo\s+tín\s+hiệu|tín\s+hiệu\s+thoát", re.IGNORECASE)
NEGATION = re.compile(r"\b(không|chưa|chẳng|thay\s+vì)\b", re.IGNORECASE)

# ─── nhắc thực thi (explain.py sinh) ────────────────────────────────────────────────
EXEC_TERMS = re.compile(
    r"\bspot\b|\bperp\b|perpetual|đòn\s+bẩy|leverage|phí\s+(giao\s+dịch|khớp|sàn)|trượt\s+giá|slippage|funding|next[\s-]open|"
    r"mở\s+cửa\s+nến\s+(tiếp|kế)|\bTOP\s?10\b|cooldown|ký\s+quỹ|giá\s+thanh\s+lý|bị\s+thanh\s+lý", re.IGNORECASE)

# ─── chỉ báo: (regex nhận diện trong văn bản, tập feature/cột đủ điều kiện) ─────────────────
_ANY = None  # luôn không hợp lệ (không có trong DSL)
INDICATORS = [
    ("EMA", r"\bEMA\b|Exponential\s+Moving", {"ema", "dema", "tema", "macd"}),
    ("SMA", r"\bSMA\b", {"sma", "bbands", "rolling_mean"}),
    ("WMA", r"\bWMA\b", {"wma"}),
    ("DEMA", r"\bDEMA\b", {"dema"}),
    ("TEMA", r"\bTEMA\b", {"tema"}),
    ("RSI", r"\bRSI\b", {"rsi"}),
    ("ATR", r"\bATR\b|Average\s+True\s+Range", {"atr", "natr", "trange"}),
    ("NATR", r"\bNATR\b", {"natr"}),
    ("MACD", r"\bMACD\b", {"macd"}),
    ("Bollinger", r"Bollinger|\bBB\b|%B\b", {"bbands"}),
    ("ADX", r"\bADX\b", {"adx"}),
    ("DI", r"[+\-−]DI\b|Directional", {"plus_di", "minus_di", "adx"}),
    ("Donchian", r"Donchian", {"donchian_upper", "donchian_lower"}),
    ("Keltner", r"Keltner", {"ema", "atr"}),
    ("Stochastic", r"Stochastic|%K\b|%D\b", {"stoch"}),
    ("CCI", r"\bCCI\b|Commodity\s+Channel", {"cci"}),
    ("Williams", r"Williams|%R\b", {"willr"}),
    ("MFI", r"\bMFI\b|Money\s+Flow", {"mfi"}),
    ("OBV", r"\bOBV\b|On[\s-]Balance", {"obv"}),
    ("ROC", r"\bROC\b|Rate\s+of\s+Change", {"roc", "rocp"}),
    ("Momentum", r"\bMomentum\(|\bMomentum\s+\d", {"momentum"}),
    ("Z-Score", r"Z[\s-]?Score|z-score", {"zscore", "rolling_zscore", "volume_z"}),
    ("LinReg", r"hồi\s+quy\s+tuyến\s+tính|Linear\s*Reg", {"linearreg", "linearreg_slope"}),
    ("StdDev", r"độ\s+lệch\s+chuẩn|\bStdDev\b|\bσ\b|sigma", {"stddev", "bbands", "zscore", "rolling_zscore", "rolling_std", "volume_z", "var"}),
    ("Volume", r"khối\s+lượng|\bvolume\b|\bVolume\b", {"volume_z", "obv", "mfi", "volume"}),
    ("VWAP", r"\bVWAP\b", _ANY),
    ("Ichimoku", r"Ichimoku|Kumo", _ANY),
    ("SAR", r"Parabolic\s+SAR|\bSAR\b", _ANY),
    ("Supertrend", r"Supertrend", _ANY),
    ("Aroon", r"\bAroon\b", _ANY),
    ("Fibonacci", r"Fibonacci", _ANY),
    ("Pivot", r"\bPivot\b", _ANY),
    ("Heikin", r"Heikin", _ANY),
    ("Chandelier", r"Chandelier", {"__chandelier__"}),   # cần donchian_upper + atr (kiểm riêng)
]

# ─── tên chỉ báo khi viết "EMA 20" / "EMA(20)" / "ROC(10)" ──────────────────────────────
PERIOD_NAMES = {
    "EMA": {"ema"}, "SMA": {"sma"}, "WMA": {"wma"}, "DEMA": {"dema"}, "TEMA": {"tema"}, "RSI": {"rsi"}, "ATR": {"atr"}, "NATR": {"natr"},
    "ADX": {"adx"}, "CCI": {"cci"}, "MFI": {"mfi"}, "ROC": {"roc", "rocp"}, "Momentum": {"momentum"}, "Donchian": {"donchian_upper", "donchian_lower"},
    "BB": {"bbands"}, "Bollinger": {"bbands"}, "Keltner": {"ema", "atr"}, "StdDev": {"stddev"}, "Williams": {"willr"}, "OBV": {"obv"},
    "Z-Score": {"zscore"}, "MACD": {"macd"}, "LinearReg": {"linearreg", "linearreg_slope"}, "Slope": {"linearreg_slope"},
}
LEVEL_NAMES = {   # tên trong văn bản → feature để so ngưỡng
    "RSI": {"rsi"}, "ADX": {"adx"}, "CCI": {"cci"}, "MFI": {"mfi"}, "ROC": {"roc", "rocp"}, "NATR": {"natr"}, "Z-Score": {"zscore", "rolling_zscore"},
    "Momentum": {"momentum"}, "Williams %R": {"willr"}, "%R": {"willr"}, "%K": {"stoch"}, "%D": {"stoch"}, "MACD": {"macd"}, "Slope": {"linearreg_slope"},
}

NUM_RE = re.compile(r"(?<![\w.])[-−+]?\d+(?:[.,]\d+)?")


# ═══ nạp mẫu ═══════════════════════════════════════════════════════════════════════════
def load_samples(path: str = SAMPLES_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    m = re.search(r"export\s+const\s+EDU_SAMPLES\s*=\s*(\[[\s\S]*\]);?\s*$", content)
    if not m:
        raise ValueError(f"Không tìm thấy EDU_SAMPLES trong {path}")
    return json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(1)))


# ═══ phân tích chương trình ════════════════════════════════════════════════════════════
def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _const_of(node):
    """Giá trị hằng của nút (Const / Neg(Const)), None nếu không phải hằng."""
    if isinstance(node, Const):
        return node.value
    if isinstance(node, Neg):
        v = _const_of(node.a)
        return None if v is None else -v
    return None


def _feats_in(node, out=None):
    """Tên feature xuất hiện trong cây node."""
    out = set() if out is None else out
    if isinstance(node, Pick):
        _feats_in(node.call, out)
    elif isinstance(node, Call):
        if node.is_feature:
            out.add(node.spec.name)
        for v in node.bound.values():
            if hasattr(v, "kind"):
                _feats_in(v, out)
    elif isinstance(node, (Bin, Cmp, Logic)):
        _feats_in(node.a, out)
        _feats_in(node.b, out)
    elif isinstance(node, (Neg, Inv)):
        _feats_in(node.a, out)
    return out


class Facts:
    """Số liệu thật của chương trình để đối chiếu với văn bản."""

    def __init__(self, program):
        self.numbers = set()                      # mọi hằng số (và ×100, |x|)
        self.call_nums = {}                       # feature -> số tham số trong các lần gọi (chu kỳ, nbdev...)
        self.levels = set()                       # (feature, '<'|'>', hằng)
        self.mults = {}                           # feature -> bội số (2.0 trong `ema + 2.0*atr`, nbdev...)
        self.exit_rules = 0
        for mask, level, _ in program.calls:
            self.exit_rules += 1 if level == 0 else 0
            self._walk(mask)

    def _add(self, v):
        self.numbers.update({v, -v, abs(v), v * 100, -v * 100, abs(v) * 100})

    def _walk(self, node):
        if node is None:
            return
        c = _const_of(node)
        if c is not None:
            self._add(c)
            return
        if isinstance(node, (BoolConst, Data)):
            return
        if isinstance(node, Pick):
            self._walk(node.call)
            return
        if isinstance(node, Call):
            for k, v in node.bound.items():
                if hasattr(v, "kind"):
                    self._walk(v)
                elif _num(v) is not None:
                    self._add(float(v))
                    if node.is_feature:
                        self.call_nums.setdefault(node.spec.name, set()).add(float(v))
                        if k in ("nbdev", "nbdevup", "nbdevdn"):
                            self.mults.setdefault(node.spec.name, set()).add(float(v))
            name = node.spec.name
            if not node.is_feature and name in ("crossed_above_value", "crossed_below_value"):
                v = _num(node.bound.get("value"))
                if v is not None:
                    d = ">" if name == "crossed_above_value" else "<"
                    for f in _feats_in(node.bound["a"]):
                        self.levels.add((f, d, v))
            return
        if isinstance(node, Bin):
            ca, cb = _const_of(node.a), _const_of(node.b)
            if node.op == "*" and (ca is not None or cb is not None):
                c, other = (ca, node.b) if ca is not None else (cb, node.a)
                for f in _feats_in(other):
                    self.mults.setdefault(f, set()).add(abs(c))
            self._walk(node.a)
            self._walk(node.b)
            return
        if isinstance(node, Cmp):
            ca, cb = _const_of(node.a), _const_of(node.b)
            flip = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "==", "!=": "!="}
            if cb is not None:
                self._cmp(node.a, node.op, cb)
            if ca is not None:
                self._cmp(node.b, flip[node.op], ca)
            self._walk(node.a)
            self._walk(node.b)
            return
        if isinstance(node, Logic):
            self._walk(node.a)
            self._walk(node.b)
            return
        if isinstance(node, (Neg, Inv)):
            self._walk(node.a)

    def _cmp(self, side, op, c):
        d = ">" if op in (">", ">=") else "<" if op in ("<", "<=") else None
        if d:
            for f in _feats_in(side):
                self.levels.add((f, d, c))


# ═══ tách văn bản cần kiểm ═════════════════════════════════════════════════════════════
def split_code(code: str):
    """(docstring, [chú thích dòng]) của mẫu."""
    m = re.search(r'"""([\s\S]*?)"""', code)
    doc = re.sub(r"\s*\n\s*", " ", m.group(1)).strip() if m else ""   # gỡ xuống dòng để tách câu đúng
    rest = code[m.end():] if m else code
    comments = [c.strip() for c in re.findall(r"#(.*)", rest)]
    return doc, comments


def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]


def effective_position(profile: str, sample_pos: dict, program) -> dict:
    """Tham số vị thế hiệu lực: xno = không SL/TP/trailing/timeout; nora = mặc định Nora + code + `position` của mẫu."""
    if profile == "xno":
        return dict(profiles.XNO_POSITION)
    return {**profiles.NORA_DEFAULTS, **program.position_overrides, **(sample_pos or {})}


def declared_position(profile: str, sample_pos: dict, program) -> dict:
    """Chỉ phần KHAI BÁO tường minh (code hoặc `position`): mặc định ngầm của nora không tính là "đã đặt"."""
    if profile == "xno":
        return {}
    return {**program.position_overrides, **(sample_pos or {})}


# ═══ kiểm tra một mẫu ══════════════════════════════════════════════════════════════════
def lint_sample(s: dict, valid_feats: set, valid_ops: set):
    key = s.get("key", "?")
    errs = []

    def err(code, msg):
        errs.append(f"[{key}] {code}: {msg}")

    # ── SCHEMA ──
    for f in ("key", "name", "category", "difficulty", "summary", "code", "profile"):
        if not s.get(f):
            err("SCHEMA", f"thiếu trường `{f}`")
    if errs:
        return errs
    if s["category"] not in CATEGORIES:
        err("SCHEMA", f"category {s['category']!r} không thuộc {CATEGORIES}")
    if s["difficulty"] not in DIFFICULTIES:
        err("SCHEMA", f"difficulty {s['difficulty']!r} không thuộc {sorted(DIFFICULTIES)}")
    profile = s["profile"]
    if profile not in PROFILES:
        err("SCHEMA", f"profile {profile!r} không thuộc {sorted(PROFILES)}")
        return errs
    pos = s.get("position") or {}
    if not isinstance(pos, dict):
        err("SCHEMA", "`position` phải là dict")
        return errs
    if profile == "xno" and pos:
        err("SCHEMA", "hồ sơ xno không có `position` (xnoquant chỉ thoát theo tín hiệu; tham số vị thế bị bỏ qua)")
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        err("SCHEMA", f"`position` có khoá không hợp lệ: {bad}")
    if not any(ch in s["summary"].lower() for ch in VI_CHARS):
        err("SCHEMA", "summary phải bằng tiếng Việt (có dấu)")

    code = s["code"]
    doc, comments = split_code(code)
    if not doc.strip():
        err("SCHEMA", "thiếu docstring lý thuyết")
    elif not any(ch in doc.lower() for ch in VI_CHARS):
        err("SCHEMA", "docstring phải bằng tiếng Việt (có dấu)")
    if len(doc.strip()) > MAX_DOC_CHARS:
        err("SCHEMA", f"docstring dài {len(doc.strip())} ký tự (> {MAX_DOC_CHARS}): chỉ giữ đoạn lý thuyết ngắn")

    # ── BOILER / NUMBA (trên toàn bộ mẫu) ──
    if re.search(r"Trading\s+Rules|Financial\s+Concept\s*:|\bSTEP\s*\d|STRATEGY\s*:|={10,}", code):
        err("BOILER", "còn khung 'Trading Rules' / 'STEP n' / 'Financial Concept:' / 'STRATEGY:' trong code")
    all_text = "\n".join([s["name"], s["summary"], code])
    if re.search(r"numba|jit\b", all_text, re.IGNORECASE):
        err("NUMBA", "nhắc Numba/JIT: chỉ báo DSL chạy bằng numpy/pandas")

    # ── COMPILE ──
    try:
        program = compile_code(code, register=False)
    except Exception as e:   # noqa: BLE001
        err("COMPILE", f"lỗi biên dịch DSL: {e}")
        return errs
    for f in re.findall(r"self\.feat\.([a-zA-Z0-9_]+)", code):
        if f not in valid_feats:
            err("COMPILE", f"feature không tồn tại: self.feat.{f}")
    for o in re.findall(r"self\.op\.([a-zA-Z0-9_]+)", code):
        if o not in valid_ops:
            err("COMPILE", f"operator không tồn tại: self.op.{o}")
    try:
        profiles.build_plan(program, profile, ["BTC"] if profile == "xno" else ["BTC@perp"], position=pos or None)
    except Exception as e:   # noqa: BLE001
        err("COMPILE", f"build_plan({profile}) lỗi: {e}")
    try:
        ex = explain_program(program, profile)
        if not ex["rules"]:
            err("COMPILE", "explain_program không trả quy tắc nào")
    except Exception as e:   # noqa: BLE001
        err("COMPILE", f"explain_program lỗi: {e}")
        return errs

    facts = Facts(program)
    declared = declared_position(profile, pos, program)
    eff = effective_position(profile, pos, program)
    for k in ("stop_loss_rate", "take_profit_rate", "trailing_stop", "timeout"):
        if k in pos and not isinstance(pos[k], (int, float)):
            err("SCHEMA", f"position.{k} phải là số")
    pos_numbers = set()
    for k in ("stop_loss_rate", "take_profit_rate", "trailing_stop", "timeout", "cooldown", "atr_period"):
        v = _num(eff.get(k)) if k in declared else None
        if v:
            pos_numbers.update({v, v / 60.0, v / 1440.0})
    for k in ("leverage", "risk_per_trade_pct"):
        v = _num(declared.get(k))
        if v:
            pos_numbers.add(v)

    feats_used = set(program.features) | set(program.columns) | {f"{c}" for c in program.columns}
    uses_atr_position = profile == "nora" and any(_num(declared.get(k)) for k in ("stop_loss_rate", "take_profit_rate", "trailing_stop"))
    allowed_nums = facts.numbers | pos_numbers | {0.0, 1.0, 100.0}

    # văn bản cần kiểm: tên, tóm tắt, docstring, chú thích code (không gồm code)
    texts = [("name", s["name"]), ("summary", s["summary"]), ("docstring", doc)] + [("comment", c) for c in comments if c]

    for where, text in texts:
        for sent in sentences(text):
            _check_sentence(err, where, sent, program, profile, pos, declared, eff, facts, feats_used, uses_atr_position, allowed_nums)
    return errs


def _check_sentence(err, where, sent, program, profile, pos, declared, eff, facts, feats_used, uses_atr_position, allowed_nums):
    tag = f"({where}) “{sent[:90]}”"
    # RISK
    for param, rx in RISK_TERMS.items():
        if not re.search(rx, sent, re.IGNORECASE):
            continue
        ok = False
        if profile == "nora" and _num(declared.get(param)):
            ok = True
        elif SIGNAL_EXIT.search(sent) and facts.exit_rules > 0:
            ok = True
        elif NEGATION.search(sent) and not _num(eff.get(param)):
            ok = True
        if not ok:
            err("RISK", f"{tag} nhắc {param} nhưng hồ sơ {profile} không đặt tham số này; "
                        "hãy nêu rõ là thoát theo tín hiệu hoặc khai báo `position`")
        elif profile == "nora" and _num(declared.get(param)) and param != "timeout":
            # RISKNUM: số N×ATR trong câu phải bằng tham số đã khai báo
            for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*[×x*]\s*ATR|ATR\s*[×x*]\s*(\d+(?:[.,]\d+)?)", sent):
                v = float((m.group(1) or m.group(2)).replace(",", "."))
                cands = {_num(declared.get(k)) for k in ("stop_loss_rate", "take_profit_rate", "trailing_stop")}
                if v not in cands:
                    err("RISKNUM", f"{tag} nêu {v:g}×ATR nhưng position = { {k: declared.get(k) for k in ('stop_loss_rate', 'take_profit_rate', 'trailing_stop') if k in declared} }")
    # SHORT
    if not program.has_short and re.search(r"\bshort\b|bán\s+khống|vị\s+thế\s+bán", re.sub(r"short[\s-]?term", "", sent, flags=re.IGNORECASE), re.IGNORECASE):
        err("SHORT", f"{tag} nhắc short/bán khống nhưng chương trình không có chân SHORT")
    # EXEC
    if EXEC_TERMS.search(sent):
        err("EXEC", f"{tag} nhắc cơ chế thực thi (do explain.py sinh theo hồ sơ), không viết tay")
    # INDIC
    for name, rx, ok_set in INDICATORS:
        if not re.search(rx, sent):
            continue
        if name == "Chandelier":   # đỉnh n nến − k×ATR (code) HOẶC trailing stop theo ATR khai báo ở hồ sơ nora
            good = ({"donchian_upper", "atr"} <= feats_used) or (profile == "nora" and bool(_num(declared.get("trailing_stop"))))
        elif name == "Keltner":
            good = {"ema", "atr"} <= feats_used
        elif name == "ATR":
            good = bool(feats_used & ok_set) or uses_atr_position
        elif ok_set is None:
            good = False
        else:
            good = bool(feats_used & ok_set)
        if not good:
            err("INDIC", f"{tag} nhắc {name} nhưng chương trình không dùng chỉ báo/dữ liệu này")
    # NUMBER (a) mọi số phải có thật
    cleaned = re.sub(r"\bpv_\w+|\b[a-z_]+\d+\b", "", sent)       # bỏ tên biến kiểu ema_20
    for m in NUM_RE.finditer(cleaned):
        v = float(m.group(0).replace("−", "-").replace(",", "."))
        if not (v in allowed_nums or abs(v) in allowed_nums):
            err("NUMBER", f"{tag} số {m.group(0)} không có trong code/vị thế")
    # NUMBER (b) "EMA 20" / "EMA(20)": chu kỳ phải khớp đúng chỉ báo
    for m in re.finditer(r"\b(" + "|".join(re.escape(n) for n in PERIOD_NAMES) + r")\s*\(?\s*(\d+(?:\.\d+)?)\b(?!\s*[%×x])", sent):
        name, v = m.group(1), float(m.group(2))
        fs = PERIOD_NAMES[name]
        have = set()
        for f in fs:
            have |= facts.call_nums.get(f, set())
        if have and v not in have:
            err("NUMBER", f"{tag} {name} {v:g}: chu kỳ thật của {sorted(fs)} là {sorted(have)}")
        if not have and (feats_used & fs):
            err("NUMBER", f"{tag} {name} {v:g}: không tìm thấy tham số số trong lần gọi {sorted(fs)}")
    # NUMBER (c) "RSI < 30": ngưỡng + hướng phải khớp một phép so sánh thật
    for m in re.finditer(r"(" + "|".join(re.escape(n) for n in LEVEL_NAMES) + r")\s*(?:\(\s*\d+(?:\s*,\s*\d+)*\s*\))?\s*(<=|>=|<|>|≤|≥)\s*([-−+]?\d+(?:\.\d+)?)", sent):
        name, op, v = m.group(1), m.group(2), float(m.group(3).replace("−", "-"))
        d = ">" if op in (">", ">=", "≥") else "<"
        fs = LEVEL_NAMES[name]
        if not any((f, d, v) in facts.levels for f in fs):
            err("NUMBER", f"{tag} “{m.group(0)}” không khớp phép so sánh nào trong code (feature {sorted(fs)}, hướng {d}, ngưỡng {v:g})")
    # NUMBER (d) "2×ATR", "2,5 độ lệch chuẩn": bội số phải khớp
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:lần\s*)?[×x*]?\s*(ATR|độ\s+lệch\s+chuẩn|StdDev)|(ATR|StdDev)\s*[×x*]\s*(\d+(?:[.,]\d+)?)", sent):
        v = float((m.group(1) or m.group(4)).replace(",", "."))
        what = m.group(2) or m.group(3)
        fs = {"ATR": {"atr", "natr"}}.get(what, {"stddev", "bbands", "zscore", "rolling_zscore"})
        have = set()
        for f in fs:
            have |= facts.mults.get(f, set())
        if what == "ATR" and profile == "nora":
            have |= {_num(declared.get(k)) for k in ("stop_loss_rate", "take_profit_rate", "trailing_stop") if _num(declared.get(k))}
        # nhân thêm hằng ngoài (vd stddev nbdev 1.0 × 2.0)
        if have and v not in have and not any(abs(v - a * b) < 1e-9 for a in have for b in have):
            err("NUMBER", f"{tag} “{m.group(0)}”: bội số thật của {what} là {sorted(have)}")
        if not have:
            err("NUMBER", f"{tag} “{m.group(0)}”: code không có phép nhân {what} nào")


# ═══ tổng hợp ═════════════════════════════════════════════════════════════════════════
def lint_all(samples_path: str = SAMPLES_PATH, verbose: bool = True, legacy: bool = False):
    """Trả về (danh sách lỗi, số mẫu). Không in nếu verbose=False. legacy=True: mẫu thiếu `profile` coi là xno (để đếm lỗi của bản cũ)."""
    samples = load_samples(samples_path)
    if legacy:
        samples = [{"profile": "xno", **s} for s in samples]
    valid_feats, valid_ops = set(FEATURE_SPECS_DATA), set(OP_SPECS_DATA)
    errors = []
    keys, names = set(), set()
    cat_count = {c: 0 for c in CATEGORIES}
    for s in samples:
        k, n = s.get("key"), s.get("name")
        if k in keys:
            errors.append(f"[{k}] SCHEMA: key trùng")
        if n in names:
            errors.append(f"[{k}] SCHEMA: name trùng")
        keys.add(k)
        names.add(n)
        if s.get("category") in cat_count:
            cat_count[s["category"]] += 1
        errors += lint_sample(s, valid_feats, valid_ops)
    if len(samples) != PER_CATEGORY * len(CATEGORIES):
        errors.append(f"[*] SCHEMA: có {len(samples)} mẫu, cần {PER_CATEGORY * len(CATEGORIES)}")
    for c, n in cat_count.items():
        if n != PER_CATEGORY:
            errors.append(f"[*] SCHEMA: nhóm {c!r} có {n} mẫu, cần {PER_CATEGORY}")
    if verbose:
        failed = {e.split("]")[0] for e in errors}
        print(f"Kiểm tra {len(samples)} mẫu: {len(samples) - len(failed - {'[*'})} mẫu sạch, {len(errors)} lỗi")
        by = {}
        for e in errors:
            by[e.split("] ")[1].split(":")[0]] = by.get(e.split("] ")[1].split(":")[0], 0) + 1
        for c, n in sorted(by.items()):
            print(f"  {c:9s} {n}")
        for e in errors:
            print("  ✖", e)
    return errors, len(samples)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    errs, _ = lint_all(args[0] if args else SAMPLES_PATH, legacy="--legacy" in sys.argv)
    sys.exit(1 if errs else 0)
