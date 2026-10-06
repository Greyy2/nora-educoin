"""Quản lý Tham số Chiến lược (Strategy Parameters).

Module này đảm bảo mọi cấu hình tham số của chiến lược
được nạp, validate và chuẩn hóa một cách nhất quán,
không bao giờ bị mất/thiếu các tham số cốt lõi.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
