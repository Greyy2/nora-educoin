"""Tham số chiến lược (P9.4): schema (StrategyParams), template (placeholder/sig.*), builder (build_params), materialize + BASE_POSITION của sổ.

Hợp nhất NGUYÊN VĂN từ core/params/{schema,template,builder}.py + phần materialize/BASE_POSITION của core/strategy/book.py (xem docs/bmad/p9_review_log.md, mục P9.4 part 1). Đường dẫn cũ là alias (shim).
"""
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/params/schema.py
#
# Quản lý Tham số Chiến lược (Strategy Parameters).
#
# Module này đảm bảo mọi cấu hình tham số của chiến lược
# được nạp, validate và chuẩn hóa một cách nhất quán,
# không bao giờ bị mất/thiếu các tham số cốt lõi.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyParams:
    """Cấu trúc chuẩn cho tham số một chiến lược (hoặc một luồng chiến lược)."""
    # 1. Định danh
    name: str = "LONG"
    strategy: str = ""
    
    # 2. Tham số chung / Hệ thống
    data_type: str = "1m"                  # '1m' hoặc '4h' (khung khớp lệnh)
    allow_negative_price_rate: bool = True # Cho phép giá âm (ví dụ: dùng cho Keltner)
    using_match_price: bool = True         # Dùng giá khớp thực tế thay vì giá close
    max_open_trades: int = 45              # Tối đa số lệnh mở cùng lúc
    max_capital_usage: float = 1.0         # Tối đa phần trăm vốn được dùng

    # 3. Tham số quản lý rủi ro / vốn
    volume_rate: float = 1.0               # % vốn cho mỗi lệnh (1.0 = 100%)
    leverage: int = 1                      # Đòn bẩy
    fee_rate: float = 0.0005               # Phí TAKER mỗi chiều (lệnh market)
    maker_fee_rate: Optional[float] = None # Phí MAKER mỗi chiều (lệnh limit: DCA, chốt lời); None = bằng taker
    slippage_rate: float = 0.0002          # Slippage mỗi chiều
    stop_loss_rate: float = 0.0            # % Cắt lỗ tính từ GIÁ TRUNG BÌNH (0 = không cắt)
    take_profit_rate: float = 0.0          # % Chốt lời tính từ GIÁ TRUNG BÌNH (0 = không chốt)
    trailing_stop: float = 0.0             # % Trailing stop tính từ đỉnh/đáy có lợi nhất (0 = tắt)
    trailing_activation_pct: float = 0.0   # Chỉ bật trailing khi đã lãi >= % này so với giá TB (0 = bật ngay)
    timeout: int = 0                       # Số PHÚT tối đa giữ lệnh (0 = không giới hạn)
    stop_fill: str = "level"               # Giá khớp SL/trailing khi chạm TRONG nến: "level" (đúng mức + trượt)
                                           # | "extreme" (giá xấu nhất của nến — bi quan, dùng để kiểm độ bền)
    intrabar_path: str = "ohlc"            # Đường giá trong nến: "ohlc" (mặc định, = NautilusTrader O->H->L->C) | "adaptive" (cực gần open trước)
                                           # | "adverse_first" (cũ: phía bất lợi trước — bi quan, giữ cho kiểm bền)
    cooldown: int = 0                      # Số PHÚT chờ sau khi đóng vị thế mới được nhận tín hiệu vào lại (0 = không chờ)
    limit_through_pct: float = 0.0         # Lệnh limit (tầng DCA, chốt lời) chỉ khớp khi giá đi QUA mức bấy nhiêu % (0 = chạm là khớp)

    # 4. Thị trường, khối lượng, DCA / Nhồi lệnh
    market: str = "spot"                   # "spot" (không đòn bẩy, không short) | "perp" (đòn bẩy + thanh lý)
    order_size_pct: float = 100.0          # Ký quỹ lệnh đầu = % vốn ban đầu
    dca_step_pct: float = 0.0              # Giá đi ngược bao nhiêu % so với tầng trước thì nhồi (0 = tắt DCA)
    dca_max_layers: int = 0                # Số tầng nhồi thêm tối đa (không tính lệnh đầu)
    dca_size_multiplier: float = 1.0       # Ký quỹ tầng sau = tầng trước × hệ số (2.0 = martingale)
    maintenance_margin_rate: float = 0.005 # Tỉ lệ ký quỹ duy trì (perp) để tính giá thanh lý
    # 5. Đơn vị thoát lệnh + khối lượng theo rủi ro (để MỘT bộ tham số dùng chung cho mọi tài sản)
    exit_unit: str = "pct"                 # "pct": SL/TP/trailing/bước DCA tính bằng % | "atr": bội số ATR% lúc vào lệnh
    atr_frame: str = "1h"                  # khung tính ATR% (natr) khi exit_unit="atr" — nến ĐÃ ĐÓNG lúc có tín hiệu
    atr_period: int = 14
    sizing: str = "margin_pct"             # "margin_pct": ký quỹ = order_size_pct% vốn | "risk": lỗ tại SL = risk_per_trade_pct% vốn
    risk_per_trade_pct: float = 0.5        # (sizing="risk") % vốn chấp nhận mất nếu chạm SL (gồm phí khứ hồi)
    max_notional_pct: float = 100.0        # (sizing="risk") trần giá trị danh nghĩa một vị thế, % vốn
    dca_steps: List[float] = field(default_factory=list)      # (tuỳ chọn) bước riêng từng tầng, % — ghi đè dca_step_pct
    dca_multipliers: List[float] = field(default_factory=list) # (tuỳ chọn) hệ số riêng từng tầng

    # 6. Các tham số tự do khác (để đánh giá điều kiện)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyParams":
        """Nạp tham số từ Dict (Json DB)."""
        d = dict(data)
        
        # Xử lý các trường có trong class
        core_kwargs = {}
        extra_kwargs = {}
        
        for k, v in d.items():
            if hasattr(cls, k) and k != "extra":
                core_kwargs[k] = v
            else:
                extra_kwargs[k] = v
                
        # Ép kiểu an toàn cho một số trường quan trọng
        if "max_open_trades" in core_kwargs:
            core_kwargs["max_open_trades"] = int(core_kwargs["max_open_trades"])
        if "allow_negative_price_rate" in core_kwargs:
            core_kwargs["allow_negative_price_rate"] = bool(core_kwargs["allow_negative_price_rate"])
        if "using_match_price" in core_kwargs:
            core_kwargs["using_match_price"] = bool(core_kwargs["using_match_price"])
            
        # Nạp data
        obj = cls(**core_kwargs)
        obj.extra = extra_kwargs
        return obj

    def to_dict(self) -> Dict[str, Any]:
        """Xuất về lại Dict phẳng để lưu database."""
        d = {
            "name": self.name,
            "strategy": self.strategy,
            "data_type": self.data_type,
            "allow_negative_price_rate": self.allow_negative_price_rate,
            "using_match_price": self.using_match_price,
            "max_open_trades": self.max_open_trades,
            "max_capital_usage": self.max_capital_usage,
            "volume_rate": self.volume_rate,
            "leverage": self.leverage,
            "stop_loss_rate": self.stop_loss_rate,
            "take_profit_rate": self.take_profit_rate,
            "trailing_stop": self.trailing_stop,
            "trailing_activation_pct": self.trailing_activation_pct,
            "timeout": self.timeout,
            "stop_fill": self.stop_fill,
            "intrabar_path": self.intrabar_path,
            "cooldown": self.cooldown,
            "limit_through_pct": self.limit_through_pct,
            "exit_unit": self.exit_unit,
            "atr_frame": self.atr_frame,
            "atr_period": self.atr_period,
            "sizing": self.sizing,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_notional_pct": self.max_notional_pct,
            "market": self.market,
            "order_size_pct": self.order_size_pct,
            "dca_step_pct": self.dca_step_pct,
            "dca_max_layers": self.dca_max_layers,
            "dca_size_multiplier": self.dca_size_multiplier,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "fee_rate": self.fee_rate,
            "maker_fee_rate": self.maker_fee_rate,
            "slippage_rate": self.slippage_rate,
            "dca_steps": self.dca_steps,
            "dca_multipliers": self.dca_multipliers,
        }
        d.update(self.extra)
        return d


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/params/template.py
#
# Tham số hoá tín hiệu: ngưỡng trong cây điều kiện AST có thể là tham số tối ưu được.
#
# Trong AST, thay một hằng số bằng node   {"param": "rsi_lo", "default": 30}
# -> trước khi chạy, node được thay bằng giá trị cụ thể (signal_params["rsi_lo"] hoặc default).
# Trong grid WFA / tối ưu, khoá tương ứng là "sig.rsi_lo".
#
# Chu kỳ chỉ báo và khung thời gian cũng tham số hoá được: hai trường chuỗi `frame` và `column` của node AST có thể chứa
# `{tên}` (cùng không gian tên "sig." với node số), vd {"frame": "{trend_tf}", "column": "ema_{ema_fast}", "index": 0}.
# Giá trị mặc định lấy từ `defaults` (materialize truyền mặc định của params_schema). Kết quả sau khi thay phải hợp lệ:
#   - khung ∈ FRAMES ("1m","5m","15m","1h","4h","24h"; chấp nhận cả số phút 1/5/15/60/240/1440);
#   - cột là cột OHLCV hoặc cột kernel hợp lệ (signals.kernels.parse_column), chu kỳ n/m là số nguyên 2..500.
# Chuỗi KHÔNG chứa `{...}` được giữ nguyên bit-for-bit (cây cũ không đổi).
# ══════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/params/builder.py
#
# Dựng StrategyParams cho mỗi flow từ tham số quản lý vị thế — dùng chung cho Studio và WFA.
#
# Phí/trượt giá mặc định theo loại sàn (manifest["venue"]) và thị trường — (taker, maker, trượt):
#     CEX spot  : taker 0,10%, maker 0,10%, trượt 0,02%   (Binance spot VIP0, không BNB)
#     CEX perp  : taker 0,05%, maker 0,02%, trượt 0,02%   (Binance USDT-M VIP0 — sàn testnet đã chọn)
#     DEX spot  : phí pool 0,30% mọi lệnh, trượt 0,10%     (AMM: không có maker)
# Taker áp cho lệnh market (vào ở open, SL, trailing, timeout, tín hiệu thoát); maker cho lệnh limit
# (tầng DCA, chốt lời). DEX không có perp -> từ chối market="perp".
# Người dùng có thể ghi đè fee_rate (taker) / maker_fee_rate / slippage_rate.
# ══════════════════════════════════════════════════════════════════════════

POSITION_KEYS = (
    "market", "leverage", "max_open_trades", "stop_loss_rate", "take_profit_rate", "trailing_stop",
    "trailing_activation_pct", "timeout", "order_size_pct", "dca_step_pct", "dca_max_layers",
    "dca_size_multiplier", "maintenance_margin_rate", "fee_rate", "maker_fee_rate", "slippage_rate",
    "using_match_price", "stop_fill", "intrabar_path", "exit_unit", "atr_frame", "atr_period", "sizing", "risk_per_trade_pct",
    "max_notional_pct", "cooldown", "dca_steps", "dca_multipliers", "limit_through_pct",
)

VENUE_COSTS = {  # (taker, maker, trượt giá)
    ("cex", "spot"): (0.0010, 0.0010, 0.0002),
    ("cex", "perp"): (0.0005, 0.0002, 0.0002),
    ("dex", "spot"): (0.0030, 0.0030, 0.0010),
}


def venue_of_symbol(symbol: str) -> str:
    from backend.db.local_pkl import read_manifest
    manifest = read_manifest(symbol) or {}
    venue = str(manifest.get("venue") or "").lower()
    return venue if venue in ("cex", "dex") else "dex"  # không rõ -> giả định bảo thủ (phí cao)


def resolve_costs(venue: str, market: str, fee_rate: Optional[float], slippage_rate: Optional[float],
                  maker_fee_rate: Optional[float] = None):
    """-> (taker, maker, trượt giá)."""
    key = (venue, market)
    if key not in VENUE_COSTS:
        raise ValueError(f"Không hỗ trợ market='{market}' trên venue='{venue}' (DEX hiện chỉ có spot).")
    taker, maker, slip = VENUE_COSTS[key]
    return (taker if fee_rate is None else float(fee_rate),
            maker if maker_fee_rate is None else float(maker_fee_rate),
            slip if slippage_rate is None else float(slippage_rate))


def data_symbol(symbol: str, market: str) -> Tuple[str, str]:
    """Ký hiệu dữ liệu thực dùng cho backtest: perp -> '<SYM>@perp' nếu có dữ liệu perp thật.

    Trả (symbol_dữ_liệu, nguồn_giá): 'perp' | 'spot_proxy' | 'spot'.
    """
    from backend.db.data_layout import resolve_asset_dir, split_instrument
    base, _ = split_instrument(symbol)
    if market != "perp":
        return base, "spot"
    perp = f"{base}@perp"
    return (perp, "perp") if resolve_asset_dir(perp) else (base, "spot_proxy")


def pool_fee_rate(symbol: Optional[str]) -> Optional[float]:
    """Phí pool DEX đã xác minh (manifest["pool_fee_rate"], đọc on-chain), nếu có."""
    if not symbol:
        return None
    from backend.db.local_pkl import read_manifest
    value = (read_manifest(symbol) or {}).get("pool_fee_rate")
    return float(value) if value is not None else None


def dca_budget_check(position: Dict[str, Any], venue_costs: Tuple[float, float, float]) -> Dict[str, Any]:
    """Kiểm tra mọi tầng DCA khai báo có vừa trần vốn (max_capital_usage) không — chỉ với sizing="margin_pct".

    Ký quỹ lệnh đầu = order_size_pct% vốn, tầng k = tầng k-1 × hệ số; PositionTracker bỏ âm thầm tầng nào làm
    ký quỹ + phí đã trả vượt vốn × max_capital_usage. need_pct = order_size_pct × (m0·(1+L·taker) + Σ m_k·(1+L·maker)),
    m0 = 1, m_k = tích luỹ hệ số; L = đòn bẩy (1 với spot). venue_costs = (taker, maker, trượt) đã resolve.
    -> {"ok", "need_pct", "cap_pct", "layers", "max_order_size_pct"} (max_order_size_pct = order_size lớn nhất còn vừa)."""
    taker, maker = float(venue_costs[0]), float(venue_costs[1])
    market = str(position.get("market") or "spot").lower()
    lev = 1.0 if market == "spot" else max(1.0, float(position.get("leverage") or 1.0))
    size = float(position.get("order_size_pct") if position.get("order_size_pct") is not None else 100.0)
    cap = 100.0 * float(position.get("max_capital_usage") if position.get("max_capital_usage") is not None else 1.0)
    cap = max(0.0, min(cap, 100.0))
    steps = [float(x) for x in (position.get("dca_steps") or [])]
    if not steps:
        n, step = int(position.get("dca_max_layers") or 0), float(position.get("dca_step_pct") or 0.0)
        steps = [step] * n if step > 0 else []
    layers = len(steps)
    result = {"ok": True, "need_pct": size, "cap_pct": cap, "layers": layers, "max_order_size_pct": size}
    if layers == 0 or str(position.get("sizing") or "margin_pct").lower() != "margin_pct":
        return result
    mults = [float(x) for x in (position.get("dca_multipliers") or [])] or \
            [float(position.get("dca_size_multiplier") or 1.0)] * layers
    if len(mults) < layers:
        mults += [mults[-1]] * (layers - len(mults))
    unit = 1.0 + lev * taker          # lệnh đầu (market, taker)
    m = 1.0
    for k in mults[:layers]:
        m *= k
        unit += m * (1.0 + lev * maker)   # tầng DCA (limit, maker)
    result["need_pct"] = size * unit
    result["max_order_size_pct"] = cap / unit
    result["ok"] = size * unit <= cap + 1e-9
    return result


def build_params(flow_name: str, flow_ast: Dict[str, Any], flow_type: str, position: Dict[str, Any],
                 venue: str, symbol: Optional[str] = None) -> StrategyParams:
    market = str(position.get("market") or "spot").lower()
    fee_override = position.get("fee_rate")
    maker_override = position.get("maker_fee_rate")
    if venue == "dex" and fee_override is None:  # DEX: dùng phí pool thật nếu manifest có
        pool_fee = pool_fee_rate(symbol)
        if pool_fee is not None:
            fee_override = pool_fee
            maker_override = pool_fee if maker_override is None else maker_override
    fee, maker, slip = resolve_costs(venue, market, fee_override, position.get("slippage_rate"), maker_override)
    leverage = float(position.get("leverage") or 1.0)
    if market == "spot" and leverage != 1.0:
        raise ValueError("Spot không dùng đòn bẩy — đặt leverage=1 hoặc market='perp'.")
    budget = dca_budget_check(position, (fee, maker, slip))
    if not budget["ok"]:
        raise ValueError(
            f"Flow '{flow_name}': ngân sách DCA không đủ — {budget['layers']} tầng nhồi (+ lệnh đầu) cần "
            f"{budget['need_pct']:.1f}% vốn (gồm phí) nhưng trần là {budget['cap_pct']:.1f}%; tầng cuối sẽ bị bỏ "
            f"âm thầm. Giảm order_size_pct xuống tối đa {budget['max_order_size_pct']:.2f}% (hoặc bớt tầng/hệ số).")
    return StrategyParams(
        name=flow_name,
        strategy="studio_ast",
        data_type="1m",
        using_match_price=bool(position.get("using_match_price", True)),
        max_open_trades=int(position.get("max_open_trades") or 45),
        volume_rate=1.0,
        leverage=leverage,
        fee_rate=fee,
        maker_fee_rate=maker,
        slippage_rate=slip,
        stop_loss_rate=float(position.get("stop_loss_rate") or 0.0),
        take_profit_rate=float(position.get("take_profit_rate") or 0.0),
        trailing_stop=float(position.get("trailing_stop") or 0.0),
        trailing_activation_pct=float(position.get("trailing_activation_pct") or 0.0),
        timeout=int(position.get("timeout") or 0),
        stop_fill=str(position.get("stop_fill") or "level"),
        intrabar_path=str(position.get("intrabar_path") or "ohlc"),
        cooldown=int(position.get("cooldown") or 0),
        limit_through_pct=max(0.0, float(position.get("limit_through_pct") or 0.0)),
        exit_unit=str(position.get("exit_unit") or "pct"),
        atr_frame=str(position.get("atr_frame") or "1h"),
        atr_period=int(position.get("atr_period") or 14),
        sizing=str(position.get("sizing") or "margin_pct"),
        risk_per_trade_pct=float(position.get("risk_per_trade_pct") or 0.5),
        max_notional_pct=float(position.get("max_notional_pct") or 100.0),
        market=market,
        order_size_pct=float(position.get("order_size_pct") if position.get("order_size_pct") is not None else 100.0),
        dca_step_pct=float(position.get("dca_step_pct") or 0.0),
        dca_max_layers=int(position.get("dca_max_layers") or 0),
        dca_size_multiplier=float(position.get("dca_size_multiplier") or 1.0),
        # bước / hệ số riêng từng tầng (ghi đè dca_step_pct / dca_size_multiplier) — trước 04/10/2026 bị bỏ qua dù dca_budget_check có tính
        dca_steps=[float(x) for x in (position.get("dca_steps") or [])],
        dca_multipliers=[float(x) for x in (position.get("dca_multipliers") or [])],
        maintenance_margin_rate=float(position.get("maintenance_margin_rate") or 0.005),
        extra={"ast": {**flow_ast, "type": flow_type}, "type": flow_type},
    )


# ══════════════════════════════════════════════════════════════════════════
# P9.4 — nguyên văn từ core/strategy/book.py
#
# Phần tham số vị thế của sổ chiến lược: hằng số mức rủi ro, BASE_POSITION, regime_for, schema_defaults, signal_defaults, materialize.
# Dữ liệu CANDIDATES/GATES/RISK/STRATEGIES ở lại core/strategy/book.py (book import ngược các tên này từ đây).
# ══════════════════════════════════════════════════════════════════════════

MAX_LEVERAGE = 10
BASE_RISK_PER_TRADE_PCT = 0.5
PESSIMISTIC_LIMIT_THROUGH_PCT = 0.15   # kịch bản bi quan (stop_fill="extreme"): lệnh limit phải đi qua mức 0,15% mới khớp   # mức chuẩn khi chọn chiến lược; mức cuối do bootstrap ngân sách MDD quyết định

BASE_POSITION = {
    "market": "perp", "leverage": MAX_LEVERAGE, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14,
    "sizing": "risk", "risk_per_trade_pct": BASE_RISK_PER_TRADE_PCT, "max_notional_pct": 300.0,
    "stop_fill": "level",
    "limit_through_pct": 0.05,   # lệnh limit (tầng DCA, chốt lời) chỉ khớp khi giá đi QUA mức 0,05% (hàng đợi sổ lệnh), không phải chạm là khớp
    "cooldown": 60,   # phút: một nến 1h — tránh vào lại ngay trên cùng trạng thái tín hiệu cũ sau khi vừa thoát (SL/trailing)
}

# Regime cho phép vào lệnh (core/regime/classifier.py). Chỉ áp khi bật regime (materialize(..., regime=True)); tắt -> chiến lược y như cũ
# (golden bất biến). Dạng "CHẶN NGƯỢC CHIỀU": LONG không vào khi TREND_DOWN / CRASH, SHORT không vào khi TREND_UP / SURGE; mọi regime khác được vào.
# Cầu chì TẮT: chiến lược lõi đều có cắt lỗ theo rủi ro (MC trend thẳng đứng: lỗ tối đa ~6% vốn); sau CRASH giá thường hồi nên cầu chì cắt LONG ở
# đáy. Bảng "chỉ cho vào ở regime X" cũ (+ cầu chì) bị dữ liệu thật bác bỏ: sổ +29,6% -> −26,0%; bảng tĩnh chỉ cho vào 8–12% lệnh lãi của chiến
# lược xu hướng vì nhãn xu hướng 4h đến muộn hơn điểm phá vỡ (test/scripts/research_regime_diagnosis.py, roadmap P2.4).
REGIME_DENY: Dict[str, List[str]] = {"LONG": ["TREND_DOWN", "CRASH"], "SHORT": ["TREND_UP", "SURGE"]}
_REGIME_NAMES = ("UNKNOWN", "RANGE", "TREND_UP", "TREND_DOWN", "VOL_EXPANSION", "SURGE", "CRASH")   # = classifier.NAMES
def regime_for(side: str) -> Dict[str, Any]:
    return {"allowed": [r for r in _REGIME_NAMES if r not in REGIME_DENY[side]], "fuse": False}
REGIME_MAP: Dict[str, Dict[str, Any]] = {}   # P9.4: bảng {id: cấu hình regime}; core/strategy/book.py điền từ CANDIDATES (dữ liệu ở lại book); materialize tra bảng này (thiếu -> regime_for(side), cùng kết quả)


def schema_defaults(candidate: Dict[str, Any], group: str = None) -> Dict[str, Any]:
    """{khoá: mặc định} của params_schema (lọc theo nhóm nếu có)."""
    return {k: v["default"] for k, v in (candidate.get("params_schema") or {}).items() if group is None or v["group"] == group}


def signal_defaults(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Mặc định tham số tín hiệu KHÔNG tiền tố "sig." (dùng thay các `{tên}` trong cây khi thiếu giá trị)."""
    return {k[len(SIG_PREFIX):]: v for k, v in schema_defaults(candidate, "signal").items()}


def materialize(candidate: Dict[str, Any], params: Dict[str, Any], regime: Any = False, **position_overrides) -> Dict[str, Any]:
    """Chiến lược cụ thể cho PortfolioEngine: thay ngưỡng/chu kỳ/khung tín hiệu, ghép tham số vị thế.
    `signal_params` trả về chỉ gồm tham số tín hiệu được truyền vào (không gồm mặc định) — như trước.
    regime=True: gắn khoá "regime" theo REGIME_MAP (lọc tín hiệu vào + cầu chì trong PortfolioEngine.load_data);
    regime=dict: cấu hình regime riêng của chiến lược này ({"allowed", "fuse"}, vd. bảng học từ train — core/regime/learn.py)."""
    signal, position = split_params(dict(params))
    if isinstance(regime, dict):
        extra = {"regime": regime}
    else:
        extra = {"regime": REGIME_MAP.get(candidate["id"]) or regime_for(candidate["side"])} if regime else {}
    if candidate.get("stop"):   # tín hiệu thoát (vd. cắt ngược kênh) -> đóng ở open nến 1m kế tiếp
        extra["stop"] = [{"condition": resolve_placeholders(candidate["stop"], signal, signal_defaults(candidate))}]
    if candidate.get("dca_gate"):   # điều kiện cho phép dồn tầng DCA (dồn có điều kiện)
        extra["dca"] = [{"condition": resolve_placeholders(candidate["dca_gate"], signal, signal_defaults(candidate))}]
    pos = {**BASE_POSITION, **candidate.get("position", {}), **position, **position_overrides}
    if pos.get("stop_fill") == "extreme" and "limit_through_pct" not in position and "limit_through_pct" not in position_overrides:
        pos["limit_through_pct"] = PESSIMISTIC_LIMIT_THROUGH_PCT   # bi quan cả cắt lỗ (giá xấu nhất) lẫn lệnh limit (phải đi qua mức)
    return {**extra,
        "id": candidate["id"], "side": candidate["side"],
        "tree": resolve_placeholders(candidate["tree"], signal, signal_defaults(candidate)),
        "position": pos,
        "signal_params": signal,
    }
