"""Hồ sơ thực thi (docs/bmad/p7_python_strategies.md §5): chương trình DSL đã biên dịch -> chiến lược của PortfolioEngine.

`xno`  xấp xỉ xnoquant: rổ TOP10 cố định, spot, mua một lần theo tỉ trọng vốn hoá × mức vị thế, chỉ thoát theo tín hiệu (không SL/TP/trailing/timeout),
       phí 0,1% mỗi lần khớp, trượt 0, cooldown 0, không giới hạn rủi ro danh mục. Mỗi (tài sản, chân) là MỘT chiến lược con (khoá `symbols`).
`nora` quản lý vị thế của Nora: perp, khối lượng theo rủi ro, SL/TP/trailing/timeout theo ATR, cooldown 60 phút, RiskConfig mặc định của sổ.

Tín hiệu của cả hai là cột `py_<hash12>_<le|lx|se|sx>` (core/signals/kernels.register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.core.strategy.pydsl.program import Program
from backend.core.strategy.pydsl.weights import TOP10, TOP10_WEIGHTS

XNO_FEE = 0.001                 # taker = maker = 0,1%
SCALE_SLACK = 1e-9              # chừa một chút để Σ ký quỹ × (1 + phí) <= vốn dù làm tròn số thực
FRAMES = ("1m", "5m", "15m", "1h", "4h", "24h")
FRAME_ORDER = {f: i for i, f in enumerate(FRAMES)}

# Mặc định của hồ sơ nora = BASE_POSITION của sổ (rủi ro 0,5%/lệnh, đòn bẩy trần 10, cooldown 60) + SL 3×ATR; không TP/trailing/timeout.
NORA_DEFAULTS = {"stop_loss_rate": 3.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0}
XNO_POSITION = {"market": "spot", "leverage": 1, "sizing": "margin_pct", "exit_unit": "pct", "stop_loss_rate": 0.0, "take_profit_rate": 0.0,
                "trailing_stop": 0.0, "trailing_activation_pct": 0.0, "timeout": 0, "cooldown": 0, "fee_rate": XNO_FEE, "maker_fee_rate": XNO_FEE,
                "slippage_rate": 0.0, "limit_through_pct": 0.0}


@dataclass
class Plan:
    profile: str
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC" = spot, "BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


def base_name(symbol: str) -> str:
    from backend.db.data_layout import parse_symbol, split_instrument
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


def default_run_frame(program: Program, profile: str) -> str:
    """Khung chạy (nến mô phỏng): xno chạy ở chính khung chiến lược (nến ngày: vào ở open nến kế = ~close nến tín hiệu); nora chạy 1m."""
    return program.timeframe if profile == "xno" else "1m"


def xno_weights(symbols: List[str], warnings: List[str]) -> Dict[str, float]:
    """Tỉ trọng vốn từng tài sản (tổng = 1). Đủ TOP10 -> bảng đo được (chuẩn hoá); tập con -> chuẩn hoá lại; tài sản ngoài bảng -> chia đều cả rổ."""
    names = [base_name(s) for s in symbols]
    if all(n in TOP10_WEIGHTS for n in names):
        raw = {n: TOP10_WEIGHTS[n] for n in names}
        if set(names) != set(TOP10):
            warnings.append(f"Rổ {names} là tập con của TOP10: tỉ trọng xnoquant được chuẩn hoá lại để tổng = 1 (xnoquant thật có thể chia khác)")
    else:
        raw = {n: 1.0 for n in names}
        warnings.append("Có tài sản ngoài TOP10 (không đo được tỉ trọng xnoquant): chia vốn ĐỀU giữa các tài sản")
    total = sum(raw.values())
    return {n: v / total for n, v in raw.items()}


def build_plan(program: Program, profile: str, symbols: List[str], position: Optional[Dict[str, Any]] = None,
               strategy_id: Optional[str] = None, run_frame: Optional[str] = None, market: Optional[str] = None,
               exact_id: bool = False) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). market: chỉ hồ sơ nora ("perp" mặc định | "spot").
    exact_id: hồ sơ nora, chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn (kiểm parity với chiến lược lõi cùng id)."""
    if profile not in ("xno", "nora"):
        raise ValueError(f"profile phải là xno|nora, nhận {profile!r}")
    if not symbols:
        raise ValueError("Cần ít nhất một tài sản")
    legs = program.legs
    if not legs:
        raise ValueError("Chương trình không có chân nào có mức position khác 0 (chỉ có set_positions(..., position=0))")
    warnings: List[str] = []
    base = run_frame or default_run_frame(program, profile)
    if base not in FRAME_ORDER:
        raise ValueError(f"run_frame phải thuộc {list(FRAMES)}")
    if FRAME_ORDER[program.timeframe] < FRAME_ORDER[base]:
        raise ValueError(f"timeframe của chiến lược ({program.timeframe}) nhỏ hơn khung chạy {base}")
    sid = strategy_id or f"py_{program.code_hash}"
    if profile == "xno":
        return _plan_xno(program, symbols, position, sid, base, legs, warnings)
    return _plan_nora(program, symbols, position, sid, base, legs, warnings, market, exact_id)


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.core.params.builder import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)


def _plan_xno(program, symbols, position, sid, base, legs, warnings) -> Plan:
    if program.position_overrides or position:
        warnings.append("Hồ sơ xno bỏ qua tham số vị thế của Nora (SL/TP/rủi ro/...): xnoquant chỉ thoát theo tín hiệu")
    names = list(dict.fromkeys(base_name(s) for s in symbols))
    weights = xno_weights(names, warnings)
    scale = 1.0 / (1.0 + XNO_FEE) * (1.0 - SCALE_SLACK)    # Σ ký quỹ × (1 + phí) = vốn: đủ tiền cho cả khoản phí vào lệnh (xnoquant cũng trừ phí khỏi vốn)
    strategies, data_symbols = [], []
    for side in legs:
        level = leg_level(program, side, warnings)
        tree, stop = _leg_signals(program, side)
        if side == "SHORT":
            warnings.append("Chân SHORT chạy trên perp đòn bẩy 1 (đo đạc E3: Crypto Spot của xnoquant không hỗ trợ short; funding perp vẫn tính nếu có dữ liệu)")
        for n in names:
            sym = n if side == "LONG" else f"{n}@perp"
            data_symbols.append(sym)
            pos = {**XNO_POSITION, "market": "spot" if side == "LONG" else "perp",
                   "order_size_pct": 100.0 * weights[n] * level * scale}
            strategies.append({"id": f"{sid}_{side.lower()}_{n}", "side": side, "symbols": [sym], "tree": tree, "stop": stop, "position": pos})
    data_symbols = list(dict.fromkeys(data_symbols))
    risk = {"max_positions": max(1, len(names) * len(legs)), "max_per_symbol": len(legs), "max_gross_exposure": 1e6,
            "kill_switch_dd_pct": 0.0, "max_open_risk_pct": 0.0, "dd_throttle_pct": 0.0}
    echo = {"weights": weights, "fee_rate": XNO_FEE, "order_size_scale": scale, "levels": {s: leg_level(program, s, []) for s in legs}}
    return Plan("xno", strategies, data_symbols, risk, base, "cex", warnings, echo)


def _plan_nora(program, symbols, position, sid, base, legs, warnings, market, exact_id) -> Plan:
    from backend.core.backtest.portfolio import RiskConfig
    from backend.core.strategy import book as sb
    market = market or "perp"
    if market not in ("perp", "spot"):
        raise ValueError("market phải là perp|spot")
    if market == "spot" and "SHORT" in legs:
        raise ValueError("Spot không short được: chương trình có chân SHORT, chọn market=perp")
    pos = {**sb.BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}
    if market == "spot":
        pos.update(market="spot", leverage=1, sizing=pos.get("sizing") or "risk")
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Hồ sơ nora dùng mặc định của Nora cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    names = list(dict.fromkeys(base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" if market == "perp" else n for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; hồ sơ nora định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan("nora", strategies, data_symbols, dict(sb.RISK), base, "cex", warnings, {"position": pos, "market": market})

