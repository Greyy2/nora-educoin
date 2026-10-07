"""Thực thi chương trình DSL (docs/bmad/p7_python_strategies.md §5): chương trình đã biên dịch -> chiến lược của PortfolioEngine.

Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).

Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (core/signals/kernels.register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.core.strategy.pydsl.program import Program

FRAMES = ("1m", "5m", "15m", "1h", "4h", "24h")
FRAME_ORDER = {f: i for i, f in enumerate(FRAMES)}
RUN_FRAME = "1m"                # khung chạy (nến mô phỏng)

# Mặc định = BASE_POSITION của sổ (rủi ro 0,5%/lệnh, đòn bẩy trần 10, cooldown 60) + SL 3×ATR; không TP/trailing/timeout.
NORA_DEFAULTS = {"stop_loss_rate": 3.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0}


@dataclass
class Plan:
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


def base_name(symbol: str) -> str:
    from backend.crawl.store import parse_symbol, split_instrument
    return parse_symbol(split_instrument(symbol)[0])[1]


def _ref(program: Program, kind: str) -> Dict[str, Any]:
    return {"frame": program.timeframe, "column": program.column(kind), "index": 0}


def _tree(program: Program, kind: str) -> List:
    return [[[_ref(program, kind), ">", 0.5]]]


def _leg_signals(program: Program, side: str) -> Tuple[List, List]:
    """(cây vào, stop) của một chân: stop theo dạng materialize(): [{"condition": cây}]."""
    ent, ext = ("le", "lx") if side == "LONG" else ("se", "sx")
    return _tree(program, ent), [{"condition": _tree(program, ext)}]


def leg_level(program: Program, side: str, warnings: List[str]) -> float:
    """Mức |position| lớn nhất của chân; nhiều mức khác nhau -> cảnh báo (v1 chỉ dùng mức lớn nhất)."""
    levels = sorted({abs(lv) for lv in program.levels if (lv > 0 if side == "LONG" else lv < 0)})
    if len(levels) > 1:
        warnings.append(f"Chân {side} có nhiều mức position khác nhau {levels}: v1 dùng mức lớn nhất ({levels[-1]:g}) cho mọi lệnh vào, "
                        "không tăng/giảm vị thế theo mức")
    return levels[-1]


def build_plan(program: Program, symbols: List[str], position: Optional[Dict[str, Any]] = None, strategy_id: Optional[str] = None,
               run_frame: Optional[str] = None, exact_id: bool = False) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id)."""
    from backend.core.strategy import book as sb
    if not symbols:
        raise ValueError("Cần ít nhất một tài sản")
    legs = program.legs
    if not legs:
        raise ValueError("Chương trình không có chân nào có mức position khác 0 (chỉ có set_positions(..., position=0))")
    warnings: List[str] = []
    base = run_frame or RUN_FRAME
    if base not in FRAME_ORDER:
        raise ValueError(f"run_frame phải thuộc {list(FRAMES)}")
    if FRAME_ORDER[program.timeframe] < FRAME_ORDER[base]:
        raise ValueError(f"timeframe của chiến lược ({program.timeframe}) nhỏ hơn khung chạy {base}")
    sid = strategy_id or f"py_{program.code_hash}"
    pos = {**sb.BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    names = list(dict.fromkeys(base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(sb.RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core.params.builder import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)
