"""Chi phí khớp lệnh của AMM (pool Uniswap v2 / Aerodrome v2): tính ĐÚNG trượt giá của lệnh của ta trên dự trữ pool tại thời điểm khớp.

Hai loại pool (manifest["ticks"]["stable"]):
- volatile  x*y = k: ra = R_ra · e / (R_vào + e), e = vào · (1 − phí).
- stable    x³y + xy³ = k (Aerodrome stable): giải y' từ bất biến bằng CHIA ĐÔI (không có công thức đóng) — đúng tới độ chính xác số thực.
Dự trữ tính theo ĐƠN VỊ TOKEN (bất biến không đổi dạng khi nhân cả hai dự trữ với hằng số: Aerodrome chuẩn hoá theo decimals nhưng k chỉ đổi theo hằng).

Trượt giá `impact` KHÔNG gồm phí pool (phí do tracker tính riêng bằng fee_rate = phí pool): giá khớp thực tế sau khi bỏ phần phí khỏi đầu vào, so với giá biên TRƯỚC lệnh:
    mua   impact = (vào_quote·(1−phí) / base_nhận) / giá_biên − 1        (volatile = vào·(1−phí) / R_quote)
    bán   impact = 1 − (quote_nhận / (bán_base·(1−phí))) / giá_biên      (volatile = bán·(1−phí) / (R_base + bán·(1−phí)))
Cộng thêm gas_usd / danh nghĩa (phí gas cố định mỗi swap, quy theo tỉ lệ danh nghĩa — lệnh nhỏ chịu gas nặng hơn).

P9.4b T6: toán AMM chạy TRONG kernel (core/backtest.py: `_amm_out_raw`, `_amm_price_impact_raw`, `reserve_price`, `_amm_impact`) — đó là bản duy nhất; module này chỉ là vỏ
Python (kiểm đầu vào, ném ValueError, giữ API cũ cho test / công cụ) gọi đúng các hàm đó của core, không import crawl.
"""
from backend.core.backtest import _AMM_BISECT, _amm_out_raw, _amm_price_impact_raw, _stable_k as _stable_k_njit, reserve_price as _reserve_price

BISECT_MAX_ITER = _AMM_BISECT   # chia đôi trên [0, dự trữ]: số thực hội tụ sau ~60 vòng, trần để không lặp vô hạn


def _stable_k(x: float, y: float) -> float:
    return float(_stable_k_njit(float(x), float(y)))


def reserve_price(reserve_base: float, reserve_quote: float, stable: bool) -> float:
    """Giá biên (quote / 1 base) theo dự trữ (bản của core/backtest.py, NumPy)."""
    return float(_reserve_price(reserve_base, reserve_quote, stable))


def amount_out(amount_in: float, r_in: float, r_out: float, fee: float, stable: bool) -> float:
    """Lượng token nhận được khi đưa `amount_in` token vào pool có dự trữ (r_in, r_out) và phí `fee` (thu trên đầu vào)."""
    if not (amount_in > 0 and r_in > 0 and r_out > 0):
        raise ValueError(f"swap không hợp lệ: vào={amount_in}, dự trữ=({r_in}, {r_out})")
    return float(_amm_out_raw(float(amount_in), float(r_in), float(r_out), float(fee), bool(stable)))


def price_impact(notional_usd: float, is_buy: bool, reserve_base: float, reserve_quote: float, quote_usd: float, fee: float, stable: bool) -> float:
    """Trượt giá (tỉ lệ, không gồm phí pool) của lệnh `notional_usd` (USD) mua/bán token gốc trên pool có dự trữ token (reserve_base, reserve_quote);
    quote_usd = USD / 1 token quote."""
    mid = reserve_price(reserve_base, reserve_quote, stable)             # quote / 1 base (giá biên trước lệnh)
    if is_buy:
        amount_out(notional_usd / quote_usd, reserve_quote, reserve_base, fee, stable)   # kiểm đầu vào: ném ValueError như bản cũ
    else:
        amount_out(notional_usd / (mid * quote_usd), reserve_base, reserve_quote, fee, stable)
    return float(_amm_price_impact_raw(float(notional_usd), bool(is_buy), mid, float(reserve_base), float(reserve_quote), float(quote_usd), float(fee), bool(stable)))


class AmmImpact:
    """Móc impact_fn của PositionTracker cho MỘT pool: dự trữ đặt lại theo từng tick (set_state), gọi (notional_usd, is_buy) -> trượt giá + gas.
    Cũng là mô tả pool (fee, stable, gas_usd) cho TickBook / KernelBook (amm=)."""

    def __init__(self, fee: float, stable: bool, gas_usd: float = 0.0):
        if not 0.0 <= fee < 1.0:
            raise ValueError(f"phí pool phải trong [0, 1), nhận {fee}")
        self.fee, self.stable, self.gas_usd = float(fee), bool(stable), float(gas_usd)
        self.reserve_base = self.reserve_quote = self.quote_usd = float("nan")

    def set_state(self, reserve_base: float, reserve_quote: float, quote_usd: float) -> None:
        if not (reserve_base > 0 and reserve_quote > 0 and quote_usd > 0):
            raise ValueError(f"dự trữ pool không hợp lệ: ({reserve_base}, {reserve_quote}), quote_usd={quote_usd}")
        self.reserve_base, self.reserve_quote, self.quote_usd = float(reserve_base), float(reserve_quote), float(quote_usd)

    def __call__(self, notional_usd: float, is_buy: bool) -> float:
        if not notional_usd > 0:
            return 0.0
        return price_impact(notional_usd, is_buy, self.reserve_base, self.reserve_quote, self.quote_usd, self.fee, self.stable) \
            + self.gas_usd / notional_usd
