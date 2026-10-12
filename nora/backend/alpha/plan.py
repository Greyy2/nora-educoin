"""Kế hoạch chạy: Plan, build_plan (chương trình DSL -> chiến lược), RiskConfig, aggregate_positions và tiện ích vị thế.
Tách từ module strategy cũ (P17 T1-B5a); phần tính tín hiệu ở backend/signal/compute.py."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from backend.models.params import BASE_POSITION, config_from_dict, FRAME_ORDER, FRAMES, NORA_DEFAULTS, RISK, RUN_FRAME, resolve_position_auto
from backend.models.models import DataSource, data_source
from backend.signal.nodes import Program


@dataclass
class RiskConfig:
    max_positions: int = 8
    max_per_symbol: int = 1
    max_gross_exposure: float = 3.0
    kill_switch_dd_pct: float = 30.0   # 0 = tắt
    max_open_risk_pct: float = 0.0     # trần Σ rủi ro tới SL (cả rổ DCA) của mọi vị thế đang mở, % vốn; lệnh mới bị thu nhỏ / chặn. 0 = tắt
    dd_throttle_pct: float = 0.0       # vốn đã chốt sụt d% so với đỉnh -> rủi ro lệnh mới × max(sàn, 1 − d / mức này). 0 = tắt
    dd_throttle_floor: float = 0.25    # hệ số rủi ro tối thiểu khi đang giảm theo mức sụt

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RiskConfig":
        return config_from_dict(cls, d)


def aggregate_positions(positions) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Lệnh đã đóng -> (by_strategy, by_symbol): {pnl_usd, trades, wins, fees_usd, funding_usd} — dùng chung cho engine danh mục và backtest tick."""
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_symbol: Dict[str, Dict[str, float]] = {}
    for p in positions:
        for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
            agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
            agg["pnl_usd"] += p.real_pnl
            agg["trades"] += 1
            agg["wins"] += int(p.real_pnl > 0)
            agg["fees_usd"] += p.fees_usd or 0.0
            agg["funding_usd"] += p.funding_usd or 0.0
    return by_strategy, by_symbol


SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k

def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str], by_id: Mapping[str, Dict[str, Any]]) -> None:
    """by_id: {id chiến lược: định nghĩa} (strategies.py.BY_ID) — core không import sổ chiến lược."""
    short = [i for i in strategy_ids if by_id[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


# Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
# cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).
#
# Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (signal/indicator.py::register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


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
               run_frame: Optional[str] = None, exact_id: bool = False, data: Optional[DataSource] = None) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id). data: nguồn dữ liệu (tên tài sản trần — DataSource.base_name); None = mặc định."""
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
    pos = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}, program.timeframe)
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    src = data_source(data)
    names = list(dict.fromkeys(src.base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.models.params import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)




