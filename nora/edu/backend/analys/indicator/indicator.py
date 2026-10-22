"""Chỉ báo (P9.4 part 2): kernel numba causal + đặc tả chữ ký DSL (spec) + feature `self.feat.*` + operator `self.op.*`.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.4 part 2).
Thứ tự trong file: kernels, spec, features, ops. Đăng ký chương trình DSL (`register_program`, cột `py_<hash12>_<le|lx|se|sx>`) nằm trong phần kernels.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from numba import njit

from backend.analys.param import COLUMN_GRAMMAR, DATA_COLUMNS


# ══════════════════════════════════════════════════════════════════════════
# Signal kernels — lõi chỉ báo của Nora.
#
# Mỗi kernel là một hàm THUẦN và CAUSAL: giá trị tại nến t chỉ dùng dữ liệu của các nến <= t
# (nến t đã đóng). Tính chất này được kiểm bằng test "prefix-invariance":
#     kernel(df)[:t] == kernel(df[:t])      với mọi t.
#
# Trong giai đoạn khởi động (chưa đủ `period` nến), kernel trả NaN; khi đó điều kiện AST
# nào dùng giá trị NaN đều là False (không có tín hiệu sớm từ dữ liệu thiếu).
#
# Tên cột dùng trong AST:   <kernel>_<tham số 1>[_<tham số 2>...]
#     rsi_14      ema_50      atr_14      bbz_20      bbl_20_2      dch_20      vwapdev_60
#
# Kernel được tính trên nến ĐÃ ĐÓNG của từng khung (1m, 5m, 15m, 1h, 4h, 24h) và chỉ
# được nhìn thấy ở nến 1m khi nến khung đó đã đóng (xem backtest/engine.py).
# ══════════════════════════════════════════════════════════════════════════



@dataclass(frozen=True)
class KernelSpec:
    name: str
    params: Tuple[str, ...]            # tên tham số theo thứ tự trong tên cột
    defaults: Tuple[float, ...]        # giá trị mặc định (dùng cho catalog/UI)
    fn: Callable[..., pd.Series]
    warmup: Callable[..., int]         # số nến cần để giá trị hợp lệ
    unit: str
    group: str
    description: str


@njit(cache=True)
def _ewm_sma_seed(x: np.ndarray, alpha: float, n: int) -> np.ndarray:
    """Trung bình mũ kiểu TradingView (ta.ema / ta.rma): giá trị đầu tiên = SMA của n giá trị hợp lệ liên tiếp đầu tiên, sau đó
    s = alpha*x + (1-alpha)*s. Trước đó NaN. Giá trị vào NaN sau khi đã khởi tạo -> ra NaN, giữ nguyên trạng thái. Đệ quy -> causal."""
    out = np.full(x.shape[0], np.nan)
    s = 0.0
    seeded = False
    run = 0
    acc = 0.0
    for i in range(x.shape[0]):
        v = x[i]
        if not seeded:
            if v != v:
                run = 0
                acc = 0.0
                continue
            run += 1
            acc += v
            if run > n:
                acc -= x[i - n]
                run = n
            if run == n:
                s = acc / n
                seeded = True
                out[i] = s
            continue
        if v != v:
            continue
        s = alpha * v + (1.0 - alpha) * s
        out[i] = s
    return out


def _tv_ewm(x: pd.Series, alpha: float, n: int) -> pd.Series:
    return pd.Series(_ewm_sma_seed(x.to_numpy(dtype="float64"), float(alpha), int(n)), index=x.index)


def _rma(x: pd.Series, n: int) -> pd.Series:
    """Wilder moving average (RMA) chuẩn TradingView ta.rma: seed SMA n giá trị đầu, rồi alpha = 1/n. Causal."""
    return _tv_ewm(x, 1.0 / n, n)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
                     axis=1).max(axis=1)


# ─── Nautilus Trader Native Indicators Integration ───────────────────────────

def _nautilus_bars_from_df(df: pd.DataFrame):
    """Dựng nhanh danh sách Bar của Nautilus Trader từ DataFrame nến để chạy chỉ báo Nautilus."""
    from decimal import Decimal
    from nautilus_trader.model.currencies import USDT
    from nautilus_trader.model.data import BarSpecification, BarType
    from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import CryptoPerpetual
    from nautilus_trader.model.objects import Currency, Price, Quantity
    from nautilus_trader.persistence.wranglers import BarDataWrangler

    inst_id = InstrumentId(Symbol("BTC-USDT-SWAP"), Venue("OKX"))
    inst = CryptoPerpetual(
        instrument_id=inst_id, raw_symbol=Symbol("BTC-USDT-SWAP"),
        base_currency=Currency.from_str("BTC"), quote_currency=USDT, settlement_currency=USDT,
        is_inverse=False, price_precision=1, size_precision=3,
        price_increment=Price(Decimal("0.1"), 1), size_increment=Quantity(Decimal("0.001"), 3),
        min_quantity=Quantity(Decimal("0.001"), 3), multiplier=Quantity.from_int(1),
        margin_init=Decimal("0.01"), margin_maint=Decimal("0.005"),
        maker_fee=Decimal("0.0002"), taker_fee=Decimal("0.0005"),
        ts_event=0, ts_init=0,
    )
    bar_type = BarType(inst_id, BarSpecification(1, BarAggregation.HOUR, PriceType.LAST), AggregationSource.EXTERNAL)
    wrangler = BarDataWrangler(bar_type, inst)
    n = len(df)
    c = df["close"].to_numpy(dtype=np.float64)
    h = df["high"].to_numpy(dtype=np.float64) if "high" in df else c
    l = df["low"].to_numpy(dtype=np.float64) if "low" in df else c
    o = df["open"].to_numpy(dtype=np.float64) if "open" in df else c
    v = df["volume"].to_numpy(dtype=np.float64) if "volume" in df else np.ones(n, dtype=np.float64)
    mat = np.column_stack([o, h, l, c, v])
    ts = np.arange(n, dtype=np.uint64) * 3600_000_000_000 + 1700000000_000_000_000
    return [wrangler._build_bar(mat[i], ts[i], ts[i]) for i in range(n)]


def nautilus_ema(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính EMA trực tiếp bằng lớp ExponentialMovingAverage chuẩn 100% của Nautilus Trader."""
    from nautilus_trader.indicators import ExponentialMovingAverage
    bars = _nautilus_bars_from_df(df)
    ind = ExponentialMovingAverage(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = ind.value if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_sma(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính SMA trực tiếp bằng lớp SimpleMovingAverage chuẩn 100% của Nautilus Trader."""
    from nautilus_trader.indicators import SimpleMovingAverage
    bars = _nautilus_bars_from_df(df)
    ind = SimpleMovingAverage(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = ind.value if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_rsi(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính RSI trực tiếp bằng lớp RelativeStrengthIndex chuẩn 100% của Nautilus Trader."""
    from nautilus_trader.indicators import RelativeStrengthIndex
    bars = _nautilus_bars_from_df(df)
    ind = RelativeStrengthIndex(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = (ind.value * 100.0) if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_atr(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính ATR trực tiếp bằng lớp AverageTrueRange chuẩn 100% của Nautilus Trader."""
    from nautilus_trader.indicators import AverageTrueRange
    bars = _nautilus_bars_from_df(df)
    ind = AverageTrueRange(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = ind.value if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_roc(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính ROC trực tiếp bằng lớp RateOfChange chuẩn 100% của Nautilus Trader."""
    from nautilus_trader.indicators import RateOfChange
    bars = _nautilus_bars_from_df(df)
    ind = RateOfChange(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = (ind.value * 100.0) if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_er(df: pd.DataFrame, n: int) -> pd.Series:
    """Tính Kaufman Efficiency Ratio trực tiếp bằng lớp EfficiencyRatio của Nautilus Trader."""
    from nautilus_trader.indicators import EfficiencyRatio
    bars = _nautilus_bars_from_df(df)
    ind = EfficiencyRatio(int(n))
    out = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        out[i] = ind.value if ind.initialized else np.nan
    return pd.Series(out, index=df.index)


def nautilus_bbands(df: pd.DataFrame, n: int, k: float) -> Dict[str, pd.Series]:
    """Tính dải Bollinger trực tiếp bằng lớp BollingerBands chuẩn của Nautilus Trader."""
    from nautilus_trader.indicators import BollingerBands
    bars = _nautilus_bars_from_df(df)
    ind = BollingerBands(int(n), float(k))
    up = np.empty(len(bars), dtype=np.float64)
    mid = np.empty(len(bars), dtype=np.float64)
    low = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        if ind.initialized:
            up[i] = ind.upper
            mid[i] = ind.middle
            low[i] = ind.lower
        else:
            up[i] = mid[i] = low[i] = np.nan
    return {
        "upper": pd.Series(up, index=df.index),
        "middle": pd.Series(mid, index=df.index),
        "lower": pd.Series(low, index=df.index),
    }


def nautilus_donchian(df: pd.DataFrame, n: int) -> Dict[str, pd.Series]:
    """Tính kênh Donchian trực tiếp bằng lớp DonchianChannel chuẩn của Nautilus Trader."""
    from nautilus_trader.indicators import DonchianChannel
    bars = _nautilus_bars_from_df(df)
    ind = DonchianChannel(int(n))
    up = np.empty(len(bars), dtype=np.float64)
    mid = np.empty(len(bars), dtype=np.float64)
    low = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        if ind.initialized:
            up[i] = ind.upper
            mid[i] = ind.middle
            low[i] = ind.lower
        else:
            up[i] = mid[i] = low[i] = np.nan
    return {
        "upper": pd.Series(up, index=df.index),
        "middle": pd.Series(mid, index=df.index),
        "lower": pd.Series(low, index=df.index),
    }


def nautilus_keltner(df: pd.DataFrame, n: int, k: float) -> Dict[str, pd.Series]:
    """Tính kênh Keltner trực tiếp bằng lớp KeltnerChannel chuẩn của Nautilus Trader."""
    from nautilus_trader.indicators import KeltnerChannel
    bars = _nautilus_bars_from_df(df)
    ind = KeltnerChannel(int(n), float(k))
    up = np.empty(len(bars), dtype=np.float64)
    mid = np.empty(len(bars), dtype=np.float64)
    low = np.empty(len(bars), dtype=np.float64)
    for i, b in enumerate(bars):
        ind.handle_bar(b)
        if ind.initialized:
            up[i] = ind.upper
            mid[i] = ind.middle
            low[i] = ind.lower
        else:
            up[i] = mid[i] = low[i] = np.nan
    return {
        "upper": pd.Series(up, index=df.index),
        "middle": pd.Series(mid, index=df.index),
        "lower": pd.Series(low, index=df.index),
    }


# ─── Xu hướng ────────────────────────────────────────────────────────────────

def sma(df, n):
    """Simple Moving Average: Vectorized C-level rolling mean."""
    n = int(n)
    return df["close"].rolling(n, min_periods=n).mean()


def ema(df, n):
    """Exponential Moving Average: TradingView ta.ema chuẩn C-level Numba."""
    n = int(n)
    return _tv_ewm(df["close"], 2.0 / (n + 1), n)


def roc(df, n):
    """Rate of Change (% thay đổi giá so với n nến trước)."""
    n = int(n)
    return (df["close"] / df["close"].shift(n) - 1.0) * 100.0


def er(df, n):
    """Kaufman Efficiency Ratio (0..1): tỷ lệ giữa dịch chuyển ròng và tổng biến động."""
    n = int(n)
    direction = (df["close"] - df["close"].shift(n)).abs()
    volatility = df["close"].diff().abs().rolling(n, min_periods=n).sum()
    return direction / volatility.replace(0, np.nan)


def adx(df, n):
    """Wilder ADX: độ mạnh xu hướng (0..100)."""
    n = int(n)
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_n = _rma(_true_range(df), n)
    plus_di = 100 * _rma(plus_dm, n) / atr_n
    minus_di = 100 * _rma(minus_dm, n) / atr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx, n)


# ─── Dao động / bắt hồi ──────────────────────────────────────────────────────

def rsi(df, n):
    """Wilder RSI (0..100): Vectorized chuẩn RMA TradingView ta.rsi."""
    n = int(n)
    diff = df["close"].diff()
    gain = diff.clip(lower=0)
    loss = (-diff).clip(lower=0)
    avg_gain = _rma(gain, n)
    avg_loss = _rma(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def bbz(df, n):
    """Z-score của close so với SMA n (đơn vị: độ lệch chuẩn)."""
    n = int(n)
    mid = df["close"].rolling(n, min_periods=n).mean()
    std = df["close"].rolling(n, min_periods=n).std(ddof=0)
    return (df["close"] - mid) / std.replace(0, np.nan)


def bbm(df, n, k=2.0):
    """Bollinger Middle Band: SMA n nến."""
    return sma(df, n)


def bbu(df, n, k=2.0):
    """Bollinger Upper Band: SMA n + k * std(ddof=0)."""
    n = int(n)
    std = df["close"].rolling(n, min_periods=n).std(ddof=0)
    return sma(df, n) + float(k) * std


def bbl(df, n, k=2.0):
    """Bollinger Lower Band: SMA n - k * std(ddof=0)."""
    n = int(n)
    std = df["close"].rolling(n, min_periods=n).std(ddof=0)
    return sma(df, n) - float(k) * std


def bbw(df, n, k=2.0):
    """Độ rộng Bollinger (%) = (upper - lower) / mid * 100."""
    mid = bbm(df, n, k)
    return (bbu(df, n, k) - bbl(df, n, k)) / mid * 100.0


def bbwp(df, n, k, m):
    """Phân vị (0..100) của độ rộng Bollinger trong m nến gần nhất."""
    m = int(m)
    return bbw(df, n, k).rolling(m, min_periods=m).rank(pct=True) * 100.0


# ─── Biến động ───────────────────────────────────────────────────────────────

def atr(df, n):
    """Average True Range: Vectorized Wilder RMA."""
    n = int(n)
    tr = _true_range(df)
    return _rma(tr, n)


def natr(df, n):
    """ATR theo % giá."""
    return atr(df, n) / df["close"] * 100.0


def rv(df, n):
    """Biến động thực (%) = độ lệch chuẩn log-return của n nến."""
    n = int(n)
    return np.log(df["close"]).diff().rolling(n, min_periods=n).std(ddof=0) * 100.0


def kcm(df, n, k=1.5):
    """Keltner Channel Middle: EMA n nến."""
    return ema(df, n)


def kcu(df, n, k=1.5):
    """Keltner Channel Upper: EMA n + k * ATR n."""
    return ema(df, n) + float(k) * atr(df, n)


def kcl(df, n, k=1.5):
    """Keltner Channel Lower: EMA n - k * ATR n."""
    return ema(df, n) - float(k) * atr(df, n)


# ─── Vùng giá / breakout ─────────────────────────────────────────────────────

def dch(df, n):
    """Đỉnh cao nhất của n nến TRƯỚC nến hiện tại."""
    n = int(n)
    return df["high"].shift(1).rolling(n, min_periods=n).max()


def dcl(df, n):
    """Đáy thấp nhất của n nến TRƯỚC nến hiện tại."""
    n = int(n)
    return df["low"].shift(1).rolling(n, min_periods=n).min()


def vwap(df, n):
    """VWAP trượt n nến theo giá điển hình (H+L+C)/3."""
    n = int(n)
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).rolling(n, min_periods=n).sum()
    vol = df["volume"].rolling(n, min_periods=n).sum()
    return pv / vol.replace(0, np.nan)


def vwapdev(df, n):
    """% lệch của close so với VWAP n nến."""
    return (df["close"] / vwap(df, n) - 1.0) * 100.0


def volz(df, n):
    """Z-score khối lượng so với n nến gần nhất (đột biến khối lượng)."""
    n = int(n)
    mean = df["volume"].rolling(n, min_periods=n).mean()
    std = df["volume"].rolling(n, min_periods=n).std(ddof=0)
    return (df["volume"] - mean) / std.replace(0, np.nan)


def _kw(mult: float = 1.0, extra: int = 0):
    def warm(*params):
        return int(max(float(p) for p in params) * mult) + extra if params else extra
    return warm


REGISTRY: Dict[str, KernelSpec] = {s.name: s for s in [
    KernelSpec("sma", ("n",), (20,), sma, _kw(), "price", "Xu hướng", "Trung bình cộng close n nến"),
    KernelSpec("ema", ("n",), (50,), ema, _kw(3), "price", "Xu hướng", "Trung bình mũ close n nến"),
    KernelSpec("roc", ("n",), (12,), roc, _kw(1, 1), "%", "Xu hướng", "% thay đổi so với n nến trước"),
    KernelSpec("er", ("n",), (20,), er, _kw(1, 1), "0..1", "Regime", "Efficiency ratio: 1 = xu hướng, 0 = đi ngang"),
    KernelSpec("adx", ("n",), (14,), adx, _kw(4, 1), "0..100", "Regime", "Độ mạnh xu hướng (Wilder)"),
    KernelSpec("rsi", ("n",), (14,), rsi, _kw(4, 1), "0..100", "Dao động", "RSI Wilder"),
    KernelSpec("bbz", ("n",), (20,), bbz, _kw(), "σ", "Dao động", "Z-score close so với SMA n"),
    KernelSpec("bbm", ("n", "k"), (20, 2), bbm, _kw(), "price", "Dao động", "Bollinger giữa"),
    KernelSpec("bbu", ("n", "k"), (20, 2), bbu, _kw(), "price", "Dao động", "Bollinger trên"),
    KernelSpec("bbl", ("n", "k"), (20, 2), bbl, _kw(), "price", "Dao động", "Bollinger dưới"),
    KernelSpec("bbw", ("n", "k"), (20, 2), bbw, _kw(), "%", "Biến động", "Độ rộng Bollinger (%)"),
    KernelSpec("bbwp", ("n", "k", "m"), (20, 2, 120), bbwp, lambda n, k, m: int(n) + int(m), "0..100", "Biến động",
               "Phân vị độ rộng Bollinger trong m nến (thấp = nén)"),
    KernelSpec("atr", ("n",), (14,), atr, _kw(4, 1), "price", "Biến động", "ATR Wilder"),
    KernelSpec("natr", ("n",), (14,), natr, _kw(4, 1), "%", "Biến động", "ATR theo % giá"),
    KernelSpec("rv", ("n",), (60,), rv, _kw(1, 1), "%", "Biến động", "Độ lệch chuẩn log-return (%)"),
    KernelSpec("kcm", ("n", "k"), (20, 1.5), kcm, _kw(4, 1), "price", "Biến động", "Keltner giữa (EMA)"),
    KernelSpec("kcu", ("n", "k"), (20, 1.5), kcu, _kw(4, 1), "price", "Biến động", "Keltner trên"),
    KernelSpec("kcl", ("n", "k"), (20, 1.5), kcl, _kw(4, 1), "price", "Biến động", "Keltner dưới"),
    KernelSpec("dch", ("n",), (20,), dch, _kw(1, 1), "price", "Breakout", "Đỉnh n nến trước (không gồm nến hiện tại)"),
    KernelSpec("dcl", ("n",), (20,), dcl, _kw(1, 1), "price", "Breakout", "Đáy n nến trước (không gồm nến hiện tại)"),
    KernelSpec("vwap", ("n",), (60,), vwap, _kw(), "price", "Dòng tiền", "VWAP trượt n nến"),
    KernelSpec("vwapdev", ("n",), (60,), vwapdev, _kw(), "%", "Dòng tiền", "% lệch close so với VWAP n nến"),
    KernelSpec("volz", ("n",), (60,), volz, _kw(), "σ", "Dòng tiền", "Z-score khối lượng"),
]}

_NUM = r"\d+(?:\.\d+)?"
_COLUMN_RE = re.compile(rf"^([a-z]+)((?:_{_NUM})*)$")
MAX_PERIOD = 2000


def parse_column(column: str) -> Optional[Tuple[KernelSpec, Tuple[float, ...]]]:
    """'bbu_20_2' -> (spec bbu, (20.0, 2.0)); None nếu không phải kernel hợp lệ."""
    match = _COLUMN_RE.match(str(column or ""))
    if not match or match.group(1) not in REGISTRY:
        return None
    spec = REGISTRY[match.group(1)]
    params = tuple(float(p) for p in match.group(2).split("_")[1:])
    if len(params) != len(spec.params):
        return None
    for name, value in zip(spec.params, params):
        if name in ("n", "m") and (value != int(value) or not 1 <= value <= MAX_PERIOD):
            return None
        if name == "k" and not 0 < value <= 10:
            return None
    return spec, params


COLUMN_GRAMMAR.update(base=DATA_COLUMNS, parse=parse_column)   # params (đứng dưới) kiểm tên cột khi thay {tên} qua bảng này


# ─── Cột chương trình Python (P7, DSL trong signal/nodes.py) ────────────────────────
# `py_<hash12>_<le|lx|se|sx>`: tín hiệu vào/thoát long/short của MỘT chương trình DSL đã biên dịch. Chương trình được đăng ký TRONG tiến trình chạy
# engine (register_program) rồi đi qua đúng đường kernel như mọi cột khác (engine.frame_features không đổi). Cột py_ không bao giờ được ghi vào kho
# dùng chung (kho dùng chung jobs/evaluate.py bỏ qua) — tính trong tiến trình, tất định theo mã.
_PY_RE = re.compile(r"^py_([0-9a-f]{12})_(le|lx|se|sx)$")
PROGRAMS: Dict[str, object] = {}


def register_program(code_hash: str, program) -> None:
    """program cần: compute_column(df, kind) -> Series 0/1 và warmup_bars (int)."""
    PROGRAMS[str(code_hash)] = program


def is_program_column(column: str) -> bool:
    return _PY_RE.match(str(column or "")) is not None


def _program_of(column: str):
    m = _PY_RE.match(str(column or ""))
    if m is None:
        return None, None
    return PROGRAMS.get(m.group(1)), m.group(2)


def is_kernel_column(column: str) -> bool:
    return parse_column(column) is not None or is_program_column(column)


def compute(df: pd.DataFrame, column: str) -> pd.Series:
    """Tính một cột kernel trên DataFrame OHLCV (đã sắp theo thời gian)."""
    if is_program_column(column):
        prog, kind = _program_of(column)
        if prog is None:
            raise ValueError(f"Cột {column!r}: chương trình Python chưa được đăng ký trong tiến trình này (gọi signal.compile_code trước khi dựng engine)")
        return prog.compute_column(df, kind).astype("float64")
    parsed = parse_column(column)
    if parsed is None:
        raise ValueError(f"Cột kernel không hợp lệ: {column!r}")
    spec, params = parsed
    out = spec.fn(df, *params)
    return out.replace([np.inf, -np.inf], np.nan).astype("float64")


def warmup_bars(column: str) -> int:
    if is_program_column(column):
        prog, _ = _program_of(column)
        return int(prog.warmup_bars) if prog is not None else 0
    parsed = parse_column(column)
    if parsed is None:
        return 0
    spec, params = parsed
    return int(spec.warmup(*params))


def catalog() -> List[Dict]:
    """Danh sách kernel cho API/UI."""
    return [{
        "kernel": s.name,
        "params": list(s.params),
        "example": f"{s.name}_" + "_".join(str(int(d)) if float(d).is_integer() else str(d) for d in s.defaults),
        "unit": s.unit,
        "group": s.group,
        "description": s.description,
    } for s in REGISTRY.values()]


# ══════════════════════════════════════════════════════════════════════════
# Đặc tả chữ ký hàm của DSL (feature / operator): tên tham số, loại, mặc định — dùng chung cho trình biên dịch (kiểm đối số, báo lỗi
# có gợi ý) và cho phần tính toán.
#
# Từ điển lý thuyết (B1): mỗi feature/operator có nhãn tiếng Việt, công thức LaTeX, giải thích ý nghĩa, cách đọc ngưỡng, số nến khởi động và nhóm phân loại.
# ══════════════════════════════════════════════════════════════════════════

REQUIRED = object()

# loại tham số:
#   num   chuỗi số hoặc hằng số         bool  mặt nạ (chuỗi bool)     any  num hoặc bool
#   int   hằng số nguyên trong [lo, hi]  float hằng số trong [lo, hi]  matype hằng 0 (chỉ hỗ trợ SMA như TA-Lib mặc định)
KINDS = ("num", "bool", "any", "int", "float", "matype")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    default: Any = REQUIRED
    lo: Optional[float] = None
    hi: Optional[float] = None

    @property
    def is_series(self) -> bool:
        return self.kind in ("num", "bool", "any")


def S(name: str, default: Any = REQUIRED) -> Param:
    """Chuỗi số."""
    return Param(name, "num", default)


def B(name: str, default: Any = REQUIRED) -> Param:
    return Param(name, "bool", default)


def A(name: str, default: Any = REQUIRED) -> Param:
    return Param(name, "any", default)


def I(name: str, default: Any = REQUIRED, lo: int = 1, hi: int = 5000) -> Param:
    return Param(name, "int", default, lo, hi)


def F(name: str, default: Any = REQUIRED, lo: float = -1e9, hi: float = 1e9) -> Param:
    return Param(name, "float", default, lo, hi)


def MA(name: str) -> Param:
    return Param(name, "matype", 0)


@dataclass(frozen=True)
class Spec:
    name: str
    params: List[Param]
    fn: Callable[..., Any]
    ret: Union[str, Callable[[dict], str]] = "num"       # "num" | "bool" | hàm (đối số đã bind) -> loại
    nout: int = 1                                       # số đầu ra (tuple khi > 1)
    warm: Callable[[dict], int] = field(default=lambda p: 0)
    doc: str = ""
    label_vi: str = ""
    formula: str = ""
    meaning_vi: str = ""
    read_vi: str = ""
    warmup: Union[int, str] = 0
    category: str = ""


# ─── B1: TỪ ĐIỂN FEATURE (42 tính năng) ──────────────────────────────────────────
FEATURE_SPECS_DATA: Dict[str, Dict[str, Any]] = {
    "sma": {
        "label_vi": "Đường trung bình động giản đơn",
        "formula": r"\mathrm{SMA}_n(t) = \frac{1}{n}\sum_{i=0}^{n-1} C_{t-i}",
        "meaning_vi": "Tính mức giá trung bình số học trong n nến gần nhất, làm mượt biến động giá ngắn hạn.",
        "read_vi": "Giá cắt lên trên SMA báo hiệu xu hướng tăng, cắt xuống dưới báo hiệu xu hướng giảm.",
        "warmup": 30,
        "category": "trend",
    },
    "ema": {
        "label_vi": "Đường trung bình động hàm mũ",
        "formula": r"\mathrm{EMA}_n(t) = \alpha C_t + (1-\alpha)\mathrm{EMA}_n(t-1), \quad \alpha = \frac{2}{n+1}",
        "meaning_vi": "Tính trung bình động có trọng số mũ, ưu tiên các nến gần nhất để giảm độ trễ so với SMA.",
        "read_vi": "Phản ứng nhanh với biến động; giá duy trì trên EMA báo hiệu quán tính tăng tiếp diễn.",
        "warmup": 90,
        "category": "trend",
    },
    "dema": {
        "label_vi": "Đường trung bình động hàm mũ kép",
        "formula": r"\mathrm{DEMA}_n = 2\cdot\mathrm{EMA}_n - \mathrm{EMA}_n(\mathrm{EMA}_n)",
        "meaning_vi": "Kết hợp hai tầng EMA để triệt tiêu độ trễ pha, bám sát hành động giá.",
        "read_vi": "Nhận diện đảo chiều sớm hơn EMA thông thường; thích hợp làm đường kích hoạt tín hiệu.",
        "warmup": 180,
        "category": "trend",
    },
    "tema": {
        "label_vi": "Đường trung bình động hàm mũ ba",
        "formula": r"\mathrm{TEMA}_n = 3\cdot\mathrm{EMA} - 3\cdot\mathrm{EMA}(\mathrm{EMA}) + \mathrm{EMA}(\mathrm{EMA}(\mathrm{EMA}))",
        "meaning_vi": "Làm mượt ba tầng giúp lọc nhiễu mà vẫn giữ độ trễ cực thấp trong thị trường biến động nhanh.",
        "read_vi": "Độ nhạy rất cao với giá; phù hợp bắt nhịp bứt phá hoặc lướt sóng ngắn hạn.",
        "warmup": 270,
        "category": "trend",
    },
    "wma": {
        "label_vi": "Đường trung bình động trọng số tuyến tính",
        "formula": r"\mathrm{WMA}_n = \frac{\sum_{i=1}^n i \cdot C_{t-n+i}}{\frac{n(n+1)}{2}}",
        "meaning_vi": "Gán trọng số giảm dần theo cấp số cộng từ nến gần nhất về quá khứ.",
        "read_vi": "Ưu tiên biến động gần nhất một cách tuyến tính, nhạy hơn SMA nhưng mượt hơn giá thô.",
        "warmup": 30,
        "category": "trend",
    },
    "rsi": {
        "label_vi": "Chỉ số sức mạnh tương đối",
        "formula": r"\mathrm{RSI}_n = 100 - \frac{100}{1 + \frac{\mathrm{Wilder}(U, n)}{\mathrm{Wilder}(D, n)}}",
        "meaning_vi": "Đo lường vận tốc và biên độ dao động giá để đánh giá trạng thái hưng phấn hoặc hoảng loạn.",
        "read_vi": "RSI < 30 là vùng quá bán (tiềm năng tạo đáy), RSI > 70 là vùng quá mua (tiềm năng tạo đỉnh).",
        "warmup": 57,
        "category": "momentum",
    },
    "atr": {
        "label_vi": "Biên độ dao động thực tế trung bình",
        "formula": r"\mathrm{ATR}_n = \mathrm{Wilder}(\mathrm{TR}, n)",
        "meaning_vi": "Đo lường mức độ biến động tuyệt đối của thị trường bằng trung bình khoảng biến động n nến.",
        "read_vi": "ATR tăng mạnh thể hiện thị trường mở rộng biên độ; thường dùng để đặt khoảng dừng lỗ theo biến động.",
        "warmup": 57,
        "category": "volatility",
    },
    "natr": {
        "label_vi": "Biên độ dao động chuẩn hóa (%)",
        "formula": r"\mathrm{NATR}_n = \frac{\mathrm{ATR}_n}{C} \times 100",
        "meaning_vi": "Biểu diễn ATR dưới dạng phần trăm thị giá, giúp so sánh mức độ biến động giữa các coin khác nhau.",
        "read_vi": "NATR cao báo hiệu rủi ro dao động lớn, cần giảm đòn bẩy hoặc nới rộng khoảng cắt lỗ.",
        "warmup": 57,
        "category": "volatility",
    },
    "adx": {
        "label_vi": "Chỉ số định hướng trung bình",
        "formula": r"\mathrm{ADX}_n = \mathrm{Wilder}\left(\frac{|+\mathrm{DI} - -\mathrm{DI}|}{+\mathrm{DI} + -\mathrm{DI}} \times 100, n\right)",
        "meaning_vi": "Đo lường cường độ mạnh yếu của xu hướng giá mà không phụ thuộc vào hướng tăng hay giảm.",
        "read_vi": "ADX > 25 báo hiệu xu hướng rõ rệt và mạnh mẽ; ADX < 20 là thị trường đi ngang không xu hướng.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "plus_di": {
        "label_vi": "Chỉ số định hướng dương (+DI)",
        "formula": r"+\mathrm{DI}_n = \frac{\mathrm{Wilder}(+\mathrm{DM}, n)}{\mathrm{ATR}_n} \times 100",
        "meaning_vi": "Đo áp lực và cường độ đẩy giá lên trong chu kỳ n nến.",
        "read_vi": "+DI nằm trên -DI xác nhận phe mua đang kiểm soát thị trường.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "minus_di": {
        "label_vi": "Chỉ số định hướng âm (-DI)",
        "formula": r"-\mathrm{DI}_n = \frac{\mathrm{Wilder}(-\mathrm{DM}, n)}{\mathrm{ATR}_n} \times 100",
        "meaning_vi": "Đo áp lực và cường độ ép giá xuống trong chu kỳ n nến.",
        "read_vi": "-DI nằm trên +DI xác nhận phe bán đang chiếm ưu thế.",
        "warmup": 57,
        "category": "trend_strength",
    },
    "macd": {
        "label_vi": "Phân kỳ hội tụ trung bình động",
        "formula": r"\mathrm{MACD} = \mathrm{EMA}_{12} - \mathrm{EMA}_{26}, \quad \mathrm{Signal} = \mathrm{EMA}_9(\mathrm{MACD})",
        "meaning_vi": "Phát hiện sự biến chuyển động lượng và xu hướng giá qua mối tương quan giữa hai đường EMA.",
        "read_vi": "MACD cắt lên Signal là tín hiệu tăng giá; Histogram chuyển từ âm sang dương báo hiệu động lượng đảo chiều.",
        "warmup": 105,
        "category": "momentum",
    },
    "bbands": {
        "label_vi": "Dải băng Bollinger",
        "formula": r"\mathrm{Mid} = \mathrm{SMA}_n, \quad \mathrm{Upper/Lower} = \mathrm{Mid} \pm k \cdot \sigma",
        "meaning_vi": "Tạo kênh biên bao quanh giá dựa trên độ lệch chuẩn thống kê, đo độ co giãn biến động.",
        "read_vi": "Giá chạm dải dưới thể hiện vùng quá bán cục bộ; dải thắt nút cổ chai báo hiệu biến động lớn sắp tới.",
        "warmup": 5,
        "category": "volatility",
    },
    "roc": {
        "label_vi": "Tỷ lệ thay đổi phần trăm",
        "formula": r"\mathrm{ROC}_n = \frac{C_t - C_{t-n}}{C_{t-n}} \times 100",
        "meaning_vi": "Đo vận tốc biến động giá bằng phần trăm chênh lệch so với n nến trước.",
        "read_vi": "ROC > 0 thể hiện đà tăng; ROC vượt đỉnh cũ cho thấy gia tốc giá đang được đẩy mạnh.",
        "warmup": 10,
        "category": "momentum",
    },
    "rocp": {
        "label_vi": "Tỷ lệ thay đổi tương đối",
        "formula": r"\mathrm{ROCP}_n = \frac{C_t - C_{t-n}}{C_{t-n}}",
        "meaning_vi": "Tỷ lệ thay đổi giá dạng số thập phân so với n nến trước.",
        "read_vi": "Dùng tính toán động lượng tương đối dạng tỷ lệ thay vì phần trăm.",
        "warmup": 10,
        "category": "momentum",
    },
    "momentum": {
        "label_vi": "Độ chênh động lượng tuyệt đối",
        "formula": r"\mathrm{Mom}_n = C_t - C_{t-n}",
        "meaning_vi": "Hiệu số giá trị tuyệt đối giữa giá đóng cửa hiện tại và n nến trước.",
        "read_vi": "Momentum dương và tăng dần cho thấy lực đẩy giá đang mạnh lên.",
        "warmup": 10,
        "category": "momentum",
    },
    "stddev": {
        "label_vi": "Độ lệch chuẩn có trọng số",
        "formula": r"\mathrm{StdDev}_n = k \times \sqrt{\frac{1}{n}\sum (C_i - \bar{C})^2}",
        "meaning_vi": "Đo mức độ phân tán của giá quanh giá trị trung bình trong n nến.",
        "read_vi": "Độ lệch chuẩn cao nghĩa là biến động và rủi ro lớn; giá trị thấp là giai đoạn nén tích lũy.",
        "warmup": 5,
        "category": "volatility",
    },
    "var": {
        "label_vi": "Phương sai chuỗi giá",
        "formula": r"\mathrm{Var}_n = k \times \frac{1}{n}\sum (C_i - \bar{C})^2",
        "meaning_vi": "Bình phương độ lệch chuẩn, đo tổng mức biến thiên phân tán của giá.",
        "read_vi": "Phương sai tăng vọt khi thị trường có những cây nến dao động bất thường.",
        "warmup": 5,
        "category": "volatility",
    },
    "cci": {
        "label_vi": "Chỉ số kênh hàng hóa",
        "formula": r"\mathrm{CCI}_n = \frac{P_{typ} - \mathrm{SMA}(P_{typ})}{0.015 \times \mathrm{MeanDev}}",
        "meaning_vi": "So sánh mức giá điển hình với mức trung bình thống kê để phát hiện chu kỳ cực điểm.",
        "read_vi": "CCI < -100 là vùng quá bán sâu; CCI > +100 báo hiệu bứt phá bước vào xu hướng tăng mạnh.",
        "warmup": 14,
        "category": "momentum",
    },
    "willr": {
        "label_vi": "Chỉ số Williams %R",
        "formula": r"\%R_n = \frac{H_n - C}{H_n - L_n} \times (-100)",
        "meaning_vi": "Đo vị trí của giá đóng cửa so với biên độ đỉnh - đáy trong n nến gần nhất.",
        "read_vi": "%R < -80 là vùng quá bán; %R > -20 là vùng quá mua.",
        "warmup": 14,
        "category": "momentum",
    },
    "mfi": {
        "label_vi": "Chỉ số dòng tiền",
        "formula": r"\mathrm{MFI}_n = 100 - \frac{100}{1 + \frac{\text{Dòng tiền dương}}{\text{Dòng tiền âm}}}",
        "meaning_vi": "Kết hợp khối lượng và biến động giá để đo cường độ dòng tiền đổ vào hoặc rút ra khỏi thị trường.",
        "read_vi": "MFI < 20 là dòng tiền kiệt quệ (vùng quá bán); MFI > 80 là dòng tiền quá nóng (vùng quá mua).",
        "warmup": 14,
        "category": "momentum",
    },
    "obv": {
        "label_vi": "Khối lượng cân bằng lũy kế",
        "formula": r"\mathrm{OBV}_t = \mathrm{OBV}_{t-1} + \mathrm{sgn}(\Delta C) \cdot V_t",
        "meaning_vi": "Cộng dồn khối lượng vào ngày tăng và trừ đi vào ngày giảm để nhận diện dấu chân dòng tiền lớn tích lũy.",
        "read_vi": "OBV lập đỉnh mới trước giá xác nhận xu hướng tăng vững chắc từ dòng tiền thực.",
        "warmup": 1,
        "category": "volume",
    },
    "stoch": {
        "label_vi": "Dao động ngẫu nhiên Stochastic",
        "formula": r"\%K = \frac{C - L_n}{H_n - L_n} \times 100, \quad \%D = \mathrm{SMA}(\%K)",
        "meaning_vi": "So sánh giá đóng cửa với biên độ dao động cao nhất - thấp nhất trong chu kỳ.",
        "read_vi": "%K cắt lên %D tại vùng dưới 20 là điểm mua tiềm năng; cắt xuống ở trên 80 là điểm bán chốt lời.",
        "warmup": 11,
        "category": "momentum",
    },
    "donchian_upper": {
        "label_vi": "Kênh trên Donchian",
        "formula": r"\mathrm{DCH}_n = \max(H_{t-n}, \dots, H_{t-1})",
        "meaning_vi": "Đỉnh cao nhất của n nến quá khứ (không tính nến hiện tại), dùng làm ngưỡng bứt phá xu hướng.",
        "read_vi": "Giá vượt qua kênh trên Donchian là tín hiệu kích hoạt vị thế mua phá vỡ (Breakout).",
        "warmup": 20,
        "category": "channel",
    },
    "donchian_lower": {
        "label_vi": "Kênh dưới Donchian",
        "formula": r"\mathrm{DCL}_n = \min(L_{t-n}, \dots, L_{t-1})",
        "meaning_vi": "Đáy thấp nhất của n nến quá khứ (không tính nến hiện tại), dùng làm ngưỡng hỗ trợ hoặc thoát vị thế.",
        "read_vi": "Giá thủng kênh dưới Donchian kích hoạt điểm dừng lỗ hoặc tín hiệu mở short phá vỡ đáy.",
        "warmup": 20,
        "category": "channel",
    },
    "linearreg_slope": {
        "label_vi": "Độ dốc hồi quy tuyến tính",
        "formula": r"\mathrm{Slope}_n = \frac{n\sum i y_i - \sum i \sum y_i}{n\sum i^2 - (\sum i)^2}",
        "meaning_vi": "Đo độ nghiêng và hướng dốc của đường xu hướng hồi quy qua n nến.",
        "read_vi": "Độ dốc dương xác nhận giá đang trong quỹ đạo tăng; độ dốc chuyển âm báo hiệu xu hướng đảo chiều.",
        "warmup": 14,
        "category": "trend",
    },
    "linearreg": {
        "label_vi": "Đường hồi quy tuyến tính",
        "formula": r"\mathrm{LinReg}_n = a + b \cdot n",
        "meaning_vi": "Giá trị đường hồi quy tuyến tính khớp theo phương pháp bình phương tối thiểu tại nến hiện tại.",
        "read_vi": "Giá giao dịch phía trên đường hồi quy thể hiện xu thế tích cực hơn mức kỳ vọng thống kê.",
        "warmup": 14,
        "category": "trend",
    },
    "rolling_mean": {
        "label_vi": "Trung bình trượt cửa sổ n nến",
        "formula": r"\bar{X}_n = \frac{1}{n}\sum_{i=0}^{n-1} X_{t-i}",
        "meaning_vi": "Tính giá trị trung bình trượt của một chuỗi số liệu bất kỳ trong cửa sổ cố định.",
        "read_vi": "Chuỗi số liệu nằm trên giá trị trung bình phản ánh trạng thái cao hơn ngưỡng cân bằng gần đây.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_std": {
        "label_vi": "Độ lệch chuẩn trượt mẫu (ddof=1)",
        "formula": r"s_n = \sqrt{\frac{1}{n-1}\sum_{i=0}^{n-1} (X_i - \bar{X})^2}",
        "meaning_vi": "Đo lường mức độ biến động mẫu không chệch của chuỗi số liệu trong cửa sổ trượt.",
        "read_vi": "Giá trị tăng cao khi chuỗi số liệu dao động mạnh và phân tán rộng.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_max": {
        "label_vi": "Giá trị lớn nhất trượt",
        "formula": r"\max(X_t, X_{t-1}, \dots, X_{t-n+1})",
        "meaning_vi": "Tìm giá trị cực đại của chuỗi trong n nến gần nhất.",
        "read_vi": "Xác định đỉnh cục bộ hoặc mức kháng cự của chuỗi dữ liệu.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_min": {
        "label_vi": "Giá trị nhỏ nhất trượt",
        "formula": r"\min(X_t, X_{t-1}, \dots, X_{t-n+1})",
        "meaning_vi": "Tìm giá trị cực tiểu của chuỗi trong n nến gần nhất.",
        "read_vi": "Xác định đáy cục bộ hoặc mức hỗ trợ của chuỗi dữ liệu.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_sum": {
        "label_vi": "Tổng trượt n nến",
        "formula": r"\sum_{i=0}^{n-1} X_{t-i}",
        "meaning_vi": "Tính tổng tích lũy của chuỗi trong cửa sổ trượt n nến.",
        "read_vi": "Thường dùng tính tổng khối lượng, tổng biên độ hoặc số phiên thỏa mãn tiêu chí.",
        "warmup": 20,
        "category": "stats",
    },
    "rolling_zscore": {
        "label_vi": "Điểm Z-score trượt",
        "formula": r"Z_n = \frac{X_t - \bar{X}_n}{\sigma_n}",
        "meaning_vi": "Chuẩn hóa khoảng cách của giá trị hiện tại so với trung bình trượt theo số lần độ lệch chuẩn.",
        "read_vi": "Z < -2 là trạng thái lệch cực tiểu thống kê; Z > 2 là trạng thái lệch cực đại thống kê.",
        "warmup": 20,
        "category": "stats",
    },
    "zscore": {
        "label_vi": "Điểm Z-score chuẩn hóa",
        "formula": r"Z_n = \frac{X_t - \bar{X}_n}{\sigma_n}",
        "meaning_vi": "Đo độ lệch chuẩn hóa của chuỗi số so với phân phối trượt gần đây (như kernel bbz).",
        "read_vi": "Z-score vượt ra ngoài biên [-2, 2] cảnh báo trạng thái biến động dị biệt cần lưu ý.",
        "warmup": 20,
        "category": "stats",
    },
    "returns": {
        "label_vi": "Tỷ suất sinh lời đơn",
        "formula": r"R_k = \frac{X_t}{X_{t-k}} - 1",
        "meaning_vi": "Tính phần trăm tăng giảm của chuỗi giá trị sau k nến dạng số thập phân.",
        "read_vi": "Returns > 0 thể hiện chuỗi có mức sinh lời dương sau k nến.",
        "warmup": 1,
        "category": "stats",
    },
    "log_returns": {
        "label_vi": "Tỷ suất sinh lời logarit",
        "formula": r"r_k = \ln(X_t / X_{t-k})",
        "meaning_vi": "Tính tỷ suất sinh lời liên tục (log return), thuận tiện cho tính toán cộng dồn theo chuỗi thời gian.",
        "read_vi": "Chuẩn hóa phân phối lợi suất đối xứng hơn phục vụ các mô hình định lượng.",
        "warmup": 1,
        "category": "stats",
    },
    "trange": {
        "label_vi": "Khoảng biến động thực tế (True Range)",
        "formula": r"\mathrm{TR} = \max(H - L, |H - C_{-1}|, |L - C_{-1}|)",
        "meaning_vi": "Đo biên độ dao động toàn diện của nến bao gồm cả khoảng nhảy giá (gap) so với nến trước.",
        "read_vi": "Phản ánh độ biến động trung thực của từng cây nến đơn lẻ.",
        "warmup": 1,
        "category": "volatility",
    },
    "typprice": {
        "label_vi": "Giá điển hình (Typical Price)",
        "formula": r"P_{typ} = \frac{H + L + C}{3}",
        "meaning_vi": "Mức giá đại diện cho cả cây nến, tính bằng trung bình cộng giữa giá cao, thấp và đóng cửa.",
        "read_vi": "Làm mượt giá đóng cửa, hạn chế tác động của hiện tượng làm giá chốt phiên.",
        "warmup": 0,
        "category": "price",
    },
    "hlc3": {
        "label_vi": "Giá trung bình HLC3",
        "formula": r"\mathrm{HLC3} = \frac{H + L + C}{3}",
        "meaning_vi": "Đồng nghĩa với Typical Price, biểu diễn trọng tâm dao động của nến từ High, Low và Close.",
        "read_vi": "Dùng làm đầu vào tính toán thay cho giá đóng cửa để bộ lọc ổn định hơn.",
        "warmup": 0,
        "category": "price",
    },
    "ohlc4": {
        "label_vi": "Giá trung bình OHLC4",
        "formula": r"\mathrm{OHLC4} = \frac{O + H + L + C}{4}",
        "meaning_vi": "Mức giá trung bình bao quát cả 4 điểm dữ liệu cơ bản của cây nến.",
        "read_vi": "Thể hiện mức giá trung tâm thực tế của toàn bộ phiên giao dịch.",
        "warmup": 0,
        "category": "price",
    },
    "range_pct": {
        "label_vi": "Biên độ nến theo phần trăm",
        "formula": r"\text{Range\%} = \frac{H - L}{C} \times 100",
        "meaning_vi": "Tỷ lệ phần trăm chênh lệch giữa đỉnh và đáy của nến so với giá đóng cửa.",
        "read_vi": "Range% cao bất thường cảnh báo nến giằng co mạnh hoặc biến động tin tức tức thời.",
        "warmup": 0,
        "category": "volatility",
    },
    "volume_z": {
        "label_vi": "Điểm Z-score khối lượng",
        "formula": r"Z_V = \frac{V - \bar{V}_n}{\sigma_{V, n}}",
        "meaning_vi": "Đo độ đột biến của khối lượng giao dịch hiện tại so với trung bình n nến trước.",
        "read_vi": "Z_V > 2 xác nhận nến có khối lượng giao dịch đột biến cao gấp nhiều lần thông thường.",
        "warmup": 20,
        "category": "volume",
    },
}

# ─── B1: TỪ ĐIỂN OPERATOR (30 toán tử) ──────────────────────────────────────────
OP_SPECS_DATA: Dict[str, Dict[str, Any]] = {
    "crossed": {
        "label_vi": "Giao cắt hai chiều",
        "formula": r"(a > b \land a_{-1} \le b_{-1}) \lor (a < b \land a_{-1} \ge b_{-1})",
        "meaning_vi": "Phát hiện thời điểm đường a cắt đường b theo một trong hai chiều tại nến hiện tại.",
        "read_vi": "Báo hiệu khoảnh khắc giao nhau giữa hai chuỗi giá trị.",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_above": {
        "label_vi": "Cắt lên trên",
        "formula": r"a > b \land a_{-1} \le b_{-1}",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên lên trên đường b (sự kiện theo nến).",
        "read_vi": "Tín hiệu mở vị thế MUA (LONG) hoặc thoát vị thế BÁN (SHORT).",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_below": {
        "label_vi": "Cắt xuống dưới",
        "formula": r"a < b \land a_{-1} \ge b_{-1}",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên xuống dưới đường b (sự kiện theo nến).",
        "read_vi": "Tín hiệu mở vị thế BÁN (SHORT) hoặc thoát vị thế MUA (LONG).",
        "warmup": 1,
        "category": "cross",
    },
    "current": {
        "label_vi": "Giá trị nến hiện tại",
        "formula": r"x_t",
        "meaning_vi": "Lấy giá trị của chuỗi tại đúng cây nến hiện tại (phép toán đồng nhất).",
        "read_vi": "Đại diện cho trạng thái thời điểm t tức thời.",
        "warmup": 0,
        "category": "shift",
    },
    "previous": {
        "label_vi": "Giá trị nến trước",
        "formula": r"x_{t-k}, \quad k \ge 1",
        "meaning_vi": "Lấy giá trị của chuỗi lùi về quá khứ k nến, tuân thủ nghiêm ngặt tính nhân quả.",
        "read_vi": "Dùng để so sánh giá trị hiện tại với trạng thái quá khứ.",
        "warmup": 1,
        "category": "shift",
    },
    "shift": {
        "label_vi": "Dịch chuyển chuỗi về quá khứ",
        "formula": r"\mathrm{Lag}_k(x) = x_{t-k}",
        "meaning_vi": "Dịch chuyển toàn bộ chuỗi dữ liệu lùi lại k bước nến để tránh thiên lệch tương lai.",
        "read_vi": "Đảm bảo tín hiệu chỉ sử dụng thông tin đã đóng nến trong quá khứ.",
        "warmup": 1,
        "category": "shift",
    },
    "diff": {
        "label_vi": "Chênh lệch tuyệt đối",
        "formula": r"\Delta x = x_t - x_{t-k}",
        "meaning_vi": "Tính hiệu số giữa giá trị hiện tại và giá trị k nến trước đó.",
        "read_vi": "Diff > 0 thể hiện giá trị đang tăng lên so với nến quá khứ.",
        "warmup": 1,
        "category": "change",
    },
    "pct_change": {
        "label_vi": "Phần trăm thay đổi",
        "formula": r"\frac{x_t - x_{t-k}}{x_{t-k}}",
        "meaning_vi": "Tính tốc độ thay đổi tương đối của chuỗi sau k nến.",
        "read_vi": "Giá trị dương là chuỗi đang tăng trưởng, giá trị âm là chuỗi đang sụt giảm.",
        "warmup": 1,
        "category": "change",
    },
    "rising": {
        "label_vi": "Tăng liên tục k nến",
        "formula": r"x_t > x_{t-1} > \dots > x_{t-k}",
        "meaning_vi": "Kiểm tra chuỗi số có tăng đơn điệu liên tục qua k nến liên tiếp hay không.",
        "read_vi": "Xác nhận quán tính tăng giá dốc và bền bỉ, không bị đứt đoạn.",
        "warmup": 1,
        "category": "change",
    },
    "falling": {
        "label_vi": "Giảm liên tục k nến",
        "formula": r"x_t < x_{t-1} < \dots < x_{t-k}",
        "meaning_vi": "Kiểm tra chuỗi số có giảm đơn điệu liên tục qua k nến liên tiếp hay không.",
        "read_vi": "Xác nhận quán tính giảm giá dốc và liên tục.",
        "warmup": 1,
        "category": "change",
    },
    "fillna": {
        "label_vi": "Điền giá trị rỗng",
        "formula": r"\begin{cases} x_t & \text{nếu } x_t \ne \mathrm{NaN} \\ v & \text{ngược lại} \end{cases}",
        "meaning_vi": "Thay thế các điểm dữ liệu rỗng (NaN) bằng một hằng số xác định.",
        "read_vi": "Làm sạch dữ liệu khởi động hoặc các điểm khuyết thiếu.",
        "warmup": 0,
        "category": "clean",
    },
    "ffill": {
        "label_vi": "Điền giá trị hợp lệ gần nhất",
        "formula": r"x_t = x_{t-1} \text{ khi } x_t \text{ là NaN}",
        "meaning_vi": "Kéo dài giá trị hợp lệ gần nhất trong quá khứ để lấp đầy các khoảng NaN.",
        "read_vi": "Bảo toàn trạng thái cuối cùng được kích hoạt.",
        "warmup": 0,
        "category": "clean",
    },
    "abs": {
        "label_vi": "Giá trị tuyệt đối",
        "formula": r"|x_t|",
        "meaning_vi": "Lấy độ lớn tuyệt đối của chuỗi số, loại bỏ dấu âm.",
        "read_vi": "Đo quy mô biến động không phân biệt chiều hướng.",
        "warmup": 0,
        "category": "math",
    },
    "clip": {
        "label_vi": "Kẹp biên giới hạn",
        "formula": r"\min(\max(x_t, \text{lower}), \text{upper})",
        "meaning_vi": "Giới hạn giá trị của chuỗi nằm gọn trong khoảng [lower, upper].",
        "read_vi": "Triệt tiêu các điểm cực trị dị biệt làm sai lệch mô hình định lượng.",
        "warmup": 0,
        "category": "clean",
    },
    "isna": {
        "label_vi": "Kiểm tra giá trị rỗng",
        "formula": r"x_t = \mathrm{NaN}",
        "meaning_vi": "Trả về True nếu điểm dữ liệu là NaN (chưa đủ nến khởi động hoặc thiếu dữ liệu).",
        "read_vi": "Dùng để kiểm soát tính khả dụng trước khi thực thi logic.",
        "warmup": 0,
        "category": "check",
    },
    "notna": {
        "label_vi": "Kiểm tra có dữ liệu",
        "formula": r"x_t \ne \mathrm{NaN}",
        "meaning_vi": "Trả về True nếu điểm dữ liệu hợp lệ và không bị rỗng.",
        "read_vi": "Xác nhận chuỗi đã qua giai đoạn khởi động an toàn.",
        "warmup": 0,
        "category": "check",
    },
    "isfinite": {
        "label_vi": "Kiểm tra giá trị hữu hạn",
        "formula": r"|x_t| < \infty \land x_t \ne \mathrm{NaN}",
        "meaning_vi": "Kiểm tra số liệu không bị chia cho 0 hoặc lỗi tràn số vô cực.",
        "read_vi": "Lọc bỏ các giá trị vô cực bất thường trước khi so sánh.",
        "warmup": 0,
        "category": "check",
    },
    "zero_ifna": {
        "label_vi": "Gán 0 nếu rỗng",
        "formula": r"\begin{cases} x_t & \text{nếu hợp lệ} \\ 0 & \text{nếu NaN} \end{cases}",
        "meaning_vi": "Quy đổi mọi giá trị NaN hoặc không xác định về mức 0.",
        "read_vi": "Đảm bảo phép cộng trừ chuỗi không bị gián đoạn bởi NaN.",
        "warmup": 0,
        "category": "clean",
    },
    "sign": {
        "label_vi": "Dấu của số liệu",
        "formula": r"\mathrm{sgn}(x_t) \in \{-1, 0, 1\}",
        "meaning_vi": "Xác định hướng của số liệu: 1 nếu dương, -1 nếu âm, 0 nếu bằng 0.",
        "read_vi": "Xác định chiều hướng vị thế hoặc biến động độc lập với quy mô.",
        "warmup": 0,
        "category": "math",
    },
    "replace": {
        "label_vi": "Thay thế giá trị cụ thể",
        "formula": r"\begin{cases} v & \text{nếu } x_t = \text{target} \\ x_t & \text{ngược lại} \end{cases}",
        "meaning_vi": "Thay thế một giá trị mục tiêu cụ thể bằng một giá trị mới.",
        "read_vi": "Hiệu chỉnh các mã lỗi hoặc giá trị quy ước đặc thù.",
        "warmup": 0,
        "category": "clean",
    },
    "between": {
        "label_vi": "Nằm trong khoảng biên",
        "formula": r"\text{lower} \le x_t \le \text{upper}",
        "meaning_vi": "Kiểm tra chuỗi số liệu có nằm trong khoảng giới hạn hai đầu hay không.",
        "read_vi": "Xác định điều kiện dao động trong biên an toàn (ví dụ: RSI từ 40 đến 60).",
        "warmup": 0,
        "category": "check",
    },
    "where": {
        "label_vi": "Lựa chọn theo điều kiện",
        "formula": r"\text{cond} \;?\; a : b",
        "meaning_vi": "Chọn giá trị a nếu điều kiện cond đúng, ngược lại chọn giá trị b.",
        "read_vi": "Rẽ nhánh logic chỉ báo hoặc giá trị vị thế linh hoạt theo nến.",
        "warmup": 0,
        "category": "conditional",
    },
    "value_when": {
        "label_vi": "Giá trị tại lần thỏa điều kiện gần nhất",
        "formula": r"x_{\tau}, \quad \tau = \max \{i \le t \mid \text{cond}_i = \mathrm{True}\}",
        "meaning_vi": "Lưu giữ giá trị x tại cây nến gần nhất mà điều kiện cond xảy ra.",
        "read_vi": "Dùng ghi nhớ mức giá vào lệnh hoặc đỉnh/đáy gần nhất làm mốc đối chiếu.",
        "warmup": 0,
        "category": "conditional",
    },
    "bars_since": {
        "label_vi": "Số nến kể từ lần thỏa điều kiện gần nhất",
        "formula": r"t - \max \{i \le t \mid \text{cond}_i = \mathrm{True}\}",
        "meaning_vi": "Đếm số cây nến trôi qua kể từ lần gần nhất điều kiện cond được thỏa mãn (0 = ngay nến này).",
        "read_vi": "Dùng kiểm soát thời gian nắm giữ, timeout thoát vị thế hoặc chu kỳ làm nguội.",
        "warmup": 0,
        "category": "conditional",
    },
    "hold_for": {
        "label_vi": "Duy trì trạng thái qua k nến",
        "formula": r"\exists i \in [t-k+1, t]: \text{cond}_i = \mathrm{True}",
        "meaning_vi": "Kéo dài hiệu lực của điều kiện True trong k nến liên tiếp kể từ lần xuất hiện gần nhất.",
        "read_vi": "Giữ trạng thái bật tín hiệu đủ lâu để chờ nến xác nhận tiếp theo.",
        "warmup": 1,
        "category": "conditional",
    },
    "crossed_above_value": {
        "label_vi": "Cắt lên trên ngưỡng hằng số",
        "formula": r"a_t > v \land a_{t-1} \le v",
        "meaning_vi": "Phát hiện thời điểm đường a cắt vượt lên một mốc số cố định (ví dụ RSI cắt lên 30).",
        "read_vi": "Tín hiệu bứt phá thoát khỏi vùng quá bán hoặc vượt mốc cản ngang.",
        "warmup": 1,
        "category": "cross",
    },
    "crossed_below_value": {
        "label_vi": "Cắt xuống dưới ngưỡng hằng số",
        "formula": r"a_t < v \land a_{t-1} \ge v",
        "meaning_vi": "Phát hiện thời điểm đường a cắt xuyên xuống dưới một mốc số cố định (ví dụ RSI cắt xuống 70).",
        "read_vi": "Tín hiệu thoái lui khỏi vùng quá mua hoặc thủng ngưỡng hỗ trợ ngang.",
        "warmup": 1,
        "category": "cross",
    },
    "and_": {
        "label_vi": "Điều kiện VÀ logic",
        "formula": r"a \land b",
        "meaning_vi": "Cả hai điều kiện a và b phải đồng thời thỏa mãn tại cùng một cây nến.",
        "read_vi": "Dùng kết hợp nhiều bộ lọc tín hiệu (ví dụ: xu hướng tăng VÀ động lượng quá bán).",
        "warmup": 0,
        "category": "logic",
    },
    "or_": {
        "label_vi": "Điều kiện HOẶC logic",
        "formula": r"a \lor b",
        "meaning_vi": "Ít nhất một trong hai điều kiện a hoặc b thỏa mãn tại cây nến.",
        "read_vi": "Dùng cho các điều kiện thoát vị thế đa dạng (ví dụ: chạm SL HOẶC tín hiệu đảo chiều).",
        "warmup": 0,
        "category": "logic",
    },
    "not_": {
        "label_vi": "Điều kiện PHỦ ĐỊNH logic",
        "formula": r"\neg a",
        "meaning_vi": "Đảo ngược trạng thái logic của điều kiện a (True thành False và ngược lại).",
        "read_vi": "Dùng để loại trừ các trường hợp cấm vào lệnh.",
        "warmup": 0,
        "category": "logic",
    },
}


# ══════════════════════════════════════════════════════════════════════════
# `self.feat.<tên>(...)` — chỉ báo kỹ thuật, tên và chữ ký theo TA-Lib.
#
# Chỉ báo trùng với kernel Nora (sma ema rsi atr natr adx roc bbands donchian volume_z zscore trange) GỌI THẲNG hàm trong
# kernel ở đầu file này trên một DataFrame dựng từ các chuỗi đầu vào: đầu vào là cột giá gốc thì ra đúng từng bit giá trị kernel Nora,
# đầu vào là chuỗi bất kỳ thì cùng công thức trên chuỗi đó. Mọi hàm CAUSAL: giá trị tại nến t chỉ dùng nến <= t (test_pydsl_causal.py).
# Giai đoạn khởi động trả NaN; vô cực đổi thành NaN.
# ══════════════════════════════════════════════════════════════════════════

def _arr(x, n: int) -> np.ndarray:
    """Chuỗi / hằng số -> mảng float64 dài n."""
    a = np.asarray(x, dtype="float64")
    return np.full(n, float(a)) if a.ndim == 0 else a


def nan_nonfinite(x) -> np.ndarray:
    """Mảng float64 với mọi giá trị không hữu hạn (NaN/±inf) -> NaN."""
    a = np.asarray(x, dtype="float64")
    return np.where(np.isfinite(a), a, np.nan)


def _frame(n: int, **cols) -> pd.DataFrame:
    return pd.DataFrame({k: _arr(v, n) for k, v in cols.items()})


def _roll(x: np.ndarray, n: int, how: str, ddof: int = 0) -> np.ndarray:
    r = pd.Series(x).rolling(int(n), min_periods=int(n))
    return getattr(r, how)(ddof=ddof).to_numpy() if how in ("std", "var") else getattr(r, how)().to_numpy()


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(x.shape[0], np.nan)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


# ─── numba: cửa sổ trượt cần vòng lặp riêng ─────────────────────────────────

@njit(cache=True)
def _wma(x, n):
    out = np.full(x.shape[0], np.nan)
    wsum = n * (n + 1) / 2.0
    for i in range(n - 1, x.shape[0]):
        s = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            s += v * (j + 1)
        if ok:
            out[i] = s / wsum
    return out


@njit(cache=True)
def _meandev(x, n):
    out = np.full(x.shape[0], np.nan)
    for i in range(n - 1, x.shape[0]):
        s = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            s += v
        if not ok:
            continue
        m = s / n
        d = 0.0
        for j in range(n):
            d += abs(x[i - n + 1 + j] - m)
        out[i] = d / n
    return out


@njit(cache=True)
def _linreg(x, n):
    slope = np.full(x.shape[0], np.nan)
    end = np.full(x.shape[0], np.nan)
    sx = n * (n - 1) / 2.0
    sxx = (n - 1) * n * (2 * n - 1) / 6.0
    den = n * sxx - sx * sx
    for i in range(n - 1, x.shape[0]):
        sy = 0.0
        sxy = 0.0
        ok = True
        for j in range(n):
            v = x[i - n + 1 + j]
            if v != v:
                ok = False
                break
            sy += v
            sxy += j * v
        if not ok:
            continue
        m = (n * sxy - sx * sy) / den
        b = (sy - m * sx) / n
        slope[i] = m
        end[i] = b + m * (n - 1)
    return slope, end


# ─── hàm tính (đối số: mảng đã căn độ dài n, hằng số) ────────────────────────

def f_sma(n, real, timeperiod):
    return sma(_frame(n, close=real), timeperiod).to_numpy()


def f_ema(n, real, timeperiod):
    return ema(_frame(n, close=real), timeperiod).to_numpy()


def f_dema(n, real, timeperiod):
    e1 = ema(_frame(n, close=real), timeperiod).to_numpy()
    e2 = ema(_frame(n, close=e1), timeperiod).to_numpy()
    return 2.0 * e1 - e2


def f_tema(n, real, timeperiod):
    e1 = ema(_frame(n, close=real), timeperiod).to_numpy()
    e2 = ema(_frame(n, close=e1), timeperiod).to_numpy()
    e3 = ema(_frame(n, close=e2), timeperiod).to_numpy()
    return 3.0 * e1 - 3.0 * e2 + e3


def f_wma(n, real, timeperiod):
    return _wma(_arr(real, n), int(timeperiod))


def f_rsi(n, real, timeperiod):
    return rsi(_frame(n, close=real), timeperiod).to_numpy()


def f_atr(n, high, low, close, timeperiod):
    return atr(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def f_natr(n, high, low, close, timeperiod):
    return natr(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def f_adx(n, high, low, close, timeperiod):
    return adx(_frame(n, high=high, low=low, close=close), timeperiod).to_numpy()


def _di(n, high, low, close, timeperiod):
    df = _frame(n, high=high, low=low, close=close)
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_n = _rma(_true_range(df), int(timeperiod))
    return 100 * _rma(plus_dm, int(timeperiod)) / atr_n, 100 * _rma(minus_dm, int(timeperiod)) / atr_n


def f_plus_di(n, high, low, close, timeperiod):
    return _di(n, high, low, close, timeperiod)[0].to_numpy()


def f_minus_di(n, high, low, close, timeperiod):
    return _di(n, high, low, close, timeperiod)[1].to_numpy()


def f_macd(n, real, fastperiod, slowperiod, signalperiod):
    fast = ema(_frame(n, close=real), fastperiod).to_numpy()
    slow = ema(_frame(n, close=real), slowperiod).to_numpy()
    line = fast - slow
    sig = ema(_frame(n, close=line), signalperiod).to_numpy()
    return line, sig, line - sig


def f_bbands(n, real, timeperiod, nbdevup, nbdevdn, matype):
    df = _frame(n, close=real)
    return (bbu(df, timeperiod, nbdevup).to_numpy(), bbm(df, timeperiod, 1.0).to_numpy(),
            bbl(df, timeperiod, nbdevdn).to_numpy())


def f_roc(n, real, timeperiod):
    return roc(_frame(n, close=real), timeperiod).to_numpy()


def f_rocp(n, real, timeperiod):
    x = _arr(real, n)
    return x / _shift(x, int(timeperiod)) - 1.0


def f_momentum(n, real, timeperiod):
    x = _arr(real, n)
    return x - _shift(x, int(timeperiod))


def f_stddev(n, real, timeperiod, nbdev):
    return _roll(_arr(real, n), timeperiod, "std", ddof=0) * float(nbdev)


def f_var(n, real, timeperiod, nbdev):
    return _roll(_arr(real, n), timeperiod, "var", ddof=0) * float(nbdev)


def f_cci(n, high, low, close, timeperiod):
    tp = (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0
    ma = _roll(tp, timeperiod, "mean")
    return (tp - ma) / (0.015 * _meandev(tp, int(timeperiod)))


def f_willr(n, high, low, close, timeperiod):
    hh = _roll(_arr(high, n), timeperiod, "max")
    ll = _roll(_arr(low, n), timeperiod, "min")
    return -100.0 * (hh - _arr(close, n)) / (hh - ll)


def f_mfi(n, high, low, close, volume, timeperiod):
    tp = (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0
    mf = tp * _arr(volume, n)
    prev = _shift(tp, 1)
    pos = np.where(tp > prev, mf, 0.0)
    neg = np.where(tp < prev, mf, 0.0)
    pos[0] = neg[0] = np.nan   # nến đầu chưa có thay đổi giá
    ps, ns = _roll(pos, timeperiod, "sum"), _roll(neg, timeperiod, "sum")
    return 100.0 * ps / (ps + ns)


def f_obv(n, real, volume):
    c, v = _arr(real, n), _arr(volume, n)
    step = np.zeros(n)
    step[1:] = np.sign(c[1:] - c[:-1]) * v[1:]
    step[0] = v[0]
    return np.cumsum(step)


def f_stoch(n, high, low, close, fastk_period, slowk_period, slowk_matype, slowd_period, slowd_matype):
    hh = _roll(_arr(high, n), fastk_period, "max")
    ll = _roll(_arr(low, n), fastk_period, "min")
    fastk = 100.0 * (_arr(close, n) - ll) / (hh - ll)
    slowk = _roll(fastk, slowk_period, "mean")
    return slowk, _roll(slowk, slowd_period, "mean")


def f_donchian_upper(n, high, timeperiod):
    return dch(_frame(n, high=high), timeperiod).to_numpy()


def f_donchian_lower(n, low, timeperiod):
    return dcl(_frame(n, low=low), timeperiod).to_numpy()


def f_linearreg_slope(n, real, timeperiod):
    return _linreg(_arr(real, n), int(timeperiod))[0]


def f_linearreg(n, real, timeperiod):
    return _linreg(_arr(real, n), int(timeperiod))[1]


def f_rolling_mean(n, real, window):
    return _roll(_arr(real, n), window, "mean")


def f_rolling_std(n, real, window):
    return _roll(_arr(real, n), window, "std", ddof=1)


def f_rolling_max(n, real, window):
    return _roll(_arr(real, n), window, "max")


def f_rolling_min(n, real, window):
    return _roll(_arr(real, n), window, "min")


def f_rolling_sum(n, real, window):
    return _roll(_arr(real, n), window, "sum")


def f_zscore(n, real, window):
    return bbz(_frame(n, close=real), window).to_numpy()


def f_returns(n, real, periods):
    x = _arr(real, n)
    return x / _shift(x, int(periods)) - 1.0


def f_log_returns(n, real, periods):
    x = _arr(real, n)
    with np.errstate(all="ignore"):
        return np.log(x / _shift(x, int(periods)))


def f_trange(n, high, low, close):
    return _true_range(_frame(n, high=high, low=low, close=close)).to_numpy()


def f_typprice(n, high, low, close):
    return (_arr(high, n) + _arr(low, n) + _arr(close, n)) / 3.0


def f_ohlc4(n, open, high, low, close):
    return (_arr(open, n) + _arr(high, n) + _arr(low, n) + _arr(close, n)) / 4.0


def f_range_pct(n, high, low, close):
    return (_arr(high, n) - _arr(low, n)) / _arr(close, n) * 100.0


def f_volume_z(n, volume, timeperiod):
    return volz(_frame(n, volume=volume), timeperiod).to_numpy()


# ─── đăng ký ────────────────────────────────────────────────────────────────
_TP = lambda d=14: I("timeperiod", d)   # noqa: E731
_HLC = [S("high"), S("low"), S("close")]


def _w(mult=1.0, extra=1, key="timeperiod"):
    """Ước lượng số nến khởi động: mult × chu kỳ + extra (cùng kiểu kernels._w)."""
    return lambda p: int(float(p.get(key, 0)) * mult) + extra


def _sum_w(*keys, extra=1):
    return lambda p: int(sum(float(p.get(k, 0)) for k in keys)) + extra


def _spec(name, params, fn, nout=1, warm=None, doc=""):
    meta = FEATURE_SPECS_DATA.get(name, {})
    return Spec(name=name, params=params, fn=fn, ret="num", nout=nout, warm=warm or _w(),
                doc=doc or meta.get("meaning_vi", ""),
                label_vi=meta.get("label_vi", ""),
                formula=meta.get("formula", ""),
                meaning_vi=meta.get("meaning_vi", ""),
                read_vi=meta.get("read_vi", ""),
                warmup=meta.get("warmup", 0),
                category=meta.get("category", ""))


FEATURES: Dict[str, Spec] = {s.name: s for s in [
    _spec("sma", [S("real"), _TP(30)], f_sma, warm=_w(1, 0), doc="Trung bình cộng n nến"),
    _spec("ema", [S("real"), _TP(30)], f_ema, warm=_w(3, 0), doc="Trung bình mũ (seed SMA như TradingView)"),
    _spec("dema", [S("real"), _TP(30)], f_dema, warm=_w(6, 0), doc="Double EMA"),
    _spec("tema", [S("real"), _TP(30)], f_tema, warm=_w(9, 0), doc="Triple EMA"),
    _spec("wma", [S("real"), _TP(30)], f_wma, warm=_w(1, 0), doc="Trung bình trọng số tuyến tính"),
    _spec("rsi", [S("real"), _TP(14)], f_rsi, warm=_w(4, 1), doc="RSI Wilder"),
    _spec("atr", _HLC + [_TP(14)], f_atr, warm=_w(4, 1), doc="ATR Wilder"),
    _spec("natr", _HLC + [_TP(14)], f_natr, warm=_w(4, 1), doc="ATR theo % giá"),
    _spec("adx", _HLC + [_TP(14)], f_adx, warm=_w(4, 1), doc="ADX Wilder"),
    _spec("plus_di", _HLC + [_TP(14)], f_plus_di, warm=_w(4, 1), doc="+DI Wilder"),
    _spec("minus_di", _HLC + [_TP(14)], f_minus_di, warm=_w(4, 1), doc="-DI Wilder"),
    _spec("macd", [S("real"), I("fastperiod", 12), I("slowperiod", 26), I("signalperiod", 9)], f_macd, nout=3,
          warm=lambda p: int(3 * p.get("slowperiod", 26) + 3 * p.get("signalperiod", 9)), doc="MACD -> (macd, signal, hist)"),
    _spec("bbands", [S("real"), I("timeperiod", 5), F("nbdevup", 2.0, 0.0, 10.0), F("nbdevdn", 2.0, 0.0, 10.0), MA("matype")], f_bbands,
          nout=3, warm=_w(1, 0), doc="Bollinger -> (upper, middle, lower); độ lệch chuẩn tổng thể (ddof=0)"),
    _spec("roc", [S("real"), _TP(10)], f_roc, doc="% thay đổi so với n nến trước"),
    _spec("rocp", [S("real"), _TP(10)], f_rocp, doc="Tỉ lệ thay đổi so với n nến trước"),
    _spec("momentum", [S("real"), _TP(10)], f_momentum, doc="Chênh lệch so với n nến trước"),
    _spec("stddev", [S("real"), _TP(5), F("nbdev", 1.0, 0.0, 100.0)], f_stddev, warm=_w(1, 0), doc="Độ lệch chuẩn (ddof=0) × nbdev"),
    _spec("var", [S("real"), _TP(5), F("nbdev", 1.0, 0.0, 100.0)], f_var, warm=_w(1, 0), doc="Phương sai (ddof=0) × nbdev"),
    _spec("cci", _HLC + [_TP(14)], f_cci, warm=_w(1, 0), doc="Commodity Channel Index"),
    _spec("willr", _HLC + [_TP(14)], f_willr, warm=_w(1, 0), doc="Williams %R"),
    _spec("mfi", _HLC + [S("volume"), _TP(14)], f_mfi, doc="Money Flow Index"),
    _spec("obv", [S("real"), S("volume")], f_obv, warm=lambda p: 1, doc="On Balance Volume"),
    _spec("stoch", _HLC + [I("fastk_period", 5), I("slowk_period", 3), MA("slowk_matype"), I("slowd_period", 3), MA("slowd_matype")], f_stoch,
          nout=2, warm=_sum_w("fastk_period", "slowk_period", "slowd_period"), doc="Stochastic chậm -> (slowk, slowd)"),
    _spec("donchian_upper", [S("high"), _TP(20)], f_donchian_upper, doc="Đỉnh n nến TRƯỚC (không gồm nến hiện tại) — như kernel dch"),
    _spec("donchian_lower", [S("low"), _TP(20)], f_donchian_lower, doc="Đáy n nến TRƯỚC (không gồm nến hiện tại) — như kernel dcl"),
    _spec("linearreg_slope", [S("real"), _TP(14)], f_linearreg_slope, warm=_w(1, 0), doc="Độ dốc hồi quy tuyến tính n nến"),
    _spec("linearreg", [S("real"), _TP(14)], f_linearreg, warm=_w(1, 0), doc="Giá trị cuối đường hồi quy tuyến tính n nến"),
    _spec("rolling_mean", [S("real"), I("window", 20)], f_rolling_mean, warm=_w(1, 0, "window")),
    _spec("rolling_std", [S("real"), I("window", 20, lo=2)], f_rolling_std, warm=_w(1, 0, "window"), doc="Độ lệch chuẩn mẫu (ddof=1) như pandas"),
    _spec("rolling_max", [S("real"), I("window", 20)], f_rolling_max, warm=_w(1, 0, "window")),
    _spec("rolling_min", [S("real"), I("window", 20)], f_rolling_min, warm=_w(1, 0, "window")),
    _spec("rolling_sum", [S("real"), I("window", 20)], f_rolling_sum, warm=_w(1, 0, "window")),
    _spec("rolling_zscore", [S("real"), I("window", 20)], f_zscore, warm=_w(1, 0, "window"), doc="(x - TB) / độ lệch chuẩn n nến (như kernel bbz)"),
    _spec("zscore", [S("real"), I("window", 20)], f_zscore, warm=_w(1, 0, "window"), doc="Như rolling_zscore"),
    _spec("returns", [S("real"), I("periods", 1)], f_returns, warm=_w(1, 0, "periods"), doc="x / x[-k] - 1"),
    _spec("log_returns", [S("real"), I("periods", 1)], f_log_returns, warm=_w(1, 0, "periods"), doc="ln(x / x[-k])"),
    _spec("trange", _HLC, f_trange, warm=lambda p: 1, doc="True range"),
    _spec("typprice", _HLC, f_typprice, warm=lambda p: 0, doc="(H+L+C)/3"),
    _spec("hlc3", _HLC, f_typprice, warm=lambda p: 0, doc="(H+L+C)/3"),
    _spec("ohlc4", [S("open"), S("high"), S("low"), S("close")], f_ohlc4, warm=lambda p: 0, doc="(O+H+L+C)/4"),
    _spec("range_pct", _HLC, f_range_pct, warm=lambda p: 0, doc="(H-L)/C × 100"),
    _spec("volume_z", [S("volume"), _TP(20)], f_volume_z, warm=_w(1, 0), doc="Z-score khối lượng n nến (như kernel volz)"),
]}


def evaluate_feature(spec: Spec, n: int, **kw):
    """Chạy một feature: mảng float64 (hoặc tuple mảng) dài n, vô cực -> NaN."""
    out = spec.fn(n, **kw)
    return tuple(nan_nonfinite(o) for o in out) if spec.nout > 1 else nan_nonfinite(out)


# ══════════════════════════════════════════════════════════════════════════
# `self.op.<tên>(...)` — 30 operator chuỗi thời gian, ngữ nghĩa CAUSAL (không shift âm, không bfill).
#
# Quy ước: so sánh có NaN -> False (không có tín hiệu từ dữ liệu thiếu); chuỗi bool không có NaN; vô cực -> NaN.
# Ngữ nghĩa lấy theo tên + TA-Lib/pandas; điểm chưa chắc ghi ở docs/bmad/p7_python_strategies.md §3.
# ══════════════════════════════════════════════════════════════════════════

def _num(x, n: int) -> np.ndarray:
    a = np.asarray(x, dtype="float64")
    return np.full(n, float(a)) if a.ndim == 0 else a


def _bool(x, n: int) -> np.ndarray:
    a = np.asarray(x, dtype=bool)
    return np.full(n, bool(a)) if a.ndim == 0 else a


def _shift_bool(x: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros(x.shape[0], dtype=bool)
    if k < x.shape[0]:
        out[k:] = x[:x.shape[0] - k]
    return out


def _fin(x: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x), x, np.nan)


def _arange_last(mask: np.ndarray) -> np.ndarray:
    """Chỉ số nến gần nhất (<= t) mà mask đúng; -1 nếu chưa có."""
    return np.maximum.accumulate(np.where(mask, np.arange(mask.shape[0]), -1))


# ─── cắt / so sánh ──────────────────────────────────────────────────────────

def _above(a, b):
    return (a > b) & (_shift(a, 1) <= _shift(b, 1))


def _below(a, b):
    return (a < b) & (_shift(a, 1) >= _shift(b, 1))


def o_crossed_above(n, a, b):
    with np.errstate(invalid="ignore"):
        return _above(_num(a, n), _num(b, n))


def o_crossed_below(n, a, b):
    with np.errstate(invalid="ignore"):
        return _below(_num(a, n), _num(b, n))


def o_crossed(n, a, b):
    a, b = _num(a, n), _num(b, n)
    with np.errstate(invalid="ignore"):
        return _above(a, b) | _below(a, b)


def o_crossed_above_value(n, a, value):
    return o_crossed_above(n, a, value)


def o_crossed_below_value(n, a, value):
    return o_crossed_below(n, a, value)


# ─── dịch / thay đổi ────────────────────────────────────────────────────────

def o_current(n, x):
    return x


def o_shift(n, x, periods):
    if np.asarray(x).dtype == bool:
        return _shift_bool(_bool(x, n), int(periods))
    return _shift(_num(x, n), int(periods))


def o_diff(n, x, periods):
    x = _num(x, n)
    return x - _shift(x, int(periods))


def o_pct_change(n, x, periods):
    x = _num(x, n)
    with np.errstate(all="ignore"):
        return _fin(x / _shift(x, int(periods)) - 1.0)


def o_rising(n, x, periods):
    x = _num(x, n)
    out = np.ones(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for i in range(int(periods)):
            out &= _shift(x, i) > _shift(x, i + 1)
    return out


def o_falling(n, x, periods):
    x = _num(x, n)
    out = np.ones(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for i in range(int(periods)):
            out &= _shift(x, i) < _shift(x, i + 1)
    return out


# ─── làm sạch / biến đổi ────────────────────────────────────────────────────

def o_fillna(n, x, value):
    x = _num(x, n)
    return np.where(np.isnan(x), _num(value, n), x)


def o_ffill(n, x):
    x = _num(x, n)
    idx = _arr_valid(x)
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def _arr_valid(x: np.ndarray) -> np.ndarray:
    return _arange_last(~np.isnan(x))


def o_abs(n, x):
    return np.abs(_num(x, n))


def o_clip(n, x, lower, upper):
    x = _num(x, n)
    out = x
    with np.errstate(invalid="ignore"):
        if lower is not None:
            out = np.where(out < lower, lower, out)
        if upper is not None:
            out = np.where(out > upper, upper, out)
    return out


def o_isna(n, x):
    return np.isnan(_num(x, n))


def o_notna(n, x):
    return ~np.isnan(_num(x, n))


def o_isfinite(n, x):
    return np.isfinite(_num(x, n))


def o_zero_ifna(n, x):
    x = _num(x, n)
    return np.where(np.isnan(x), 0.0, x)


def o_sign(n, x):
    x = _num(x, n)
    return np.where(np.isnan(x), np.nan, np.sign(x))


def o_replace(n, x, to_replace, value):
    x = _num(x, n)
    with np.errstate(invalid="ignore"):
        return np.where(x == to_replace, float(value), x)


def o_between(n, x, lower, upper):
    x = _num(x, n)
    with np.errstate(invalid="ignore"):
        return (x >= _num(lower, n)) & (x <= _num(upper, n))


def o_where(n, cond, a, b):
    ra, rb = np.asarray(a), np.asarray(b)
    if ra.dtype == bool and rb.dtype == bool:
        return np.where(_bool(cond, n), _bool(a, n), _bool(b, n))
    return np.where(_bool(cond, n), _num(a, n), _num(b, n))


# ─── trạng thái theo thời gian ──────────────────────────────────────────────

def o_value_when(n, cond, x):
    cond, x = _bool(cond, n), _num(x, n)
    idx = _arange_last(cond)
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def o_bars_since(n, cond):
    cond = _bool(cond, n)
    idx = _arange_last(cond)
    return np.where(idx >= 0, np.arange(n) - idx, np.nan)


def o_hold_for(n, cond, periods):
    """True trong `periods` nến kể từ nến cond đúng gần nhất (gồm chính nến đó)."""
    c = np.cumsum(_bool(cond, n).astype("int64"))
    return _hold(c, int(periods)) > 0


def _hold(c: np.ndarray, k: int) -> np.ndarray:
    prev = np.zeros(c.shape[0], dtype="int64")
    if k < c.shape[0]:
        prev[k:] = c[:c.shape[0] - k]
    return c - prev


# ─── logic ──────────────────────────────────────────────────────────────────

def o_and_(n, a, b):
    return _bool(a, n) & _bool(b, n)


def o_or_(n, a, b):
    return _bool(a, n) | _bool(b, n)


def o_not_(n, a):
    return ~_bool(a, n)


def _ret_shift(p):
    return "bool" if p.get("x_kind") == "bool" else "num"


def _ret_where(p):
    return "bool" if p.get("a_kind") == "bool" and p.get("b_kind") == "bool" else "num"


def _op(name, params, fn, ret="num", warm=None, doc=""):
    meta = OP_SPECS_DATA.get(name, {})
    return Spec(name=name, params=params, fn=fn, ret=ret, nout=1, warm=warm or (lambda p: 0),
                doc=doc or meta.get("meaning_vi", ""),
                label_vi=meta.get("label_vi", ""),
                formula=meta.get("formula", ""),
                meaning_vi=meta.get("meaning_vi", ""),
                read_vi=meta.get("read_vi", ""),
                warmup=meta.get("warmup", 0),
                category=meta.get("category", ""))


_PER = lambda d=1: I("periods", d, lo=1, hi=5000)   # noqa: E731  (periods >= 1: không nhìn tương lai)

OPS: Dict[str, Spec] = {s.name: s for s in [
    _op("crossed", [S("a"), S("b")], o_crossed, "bool", lambda p: 1, "a cắt b theo một trong hai chiều"),
    _op("crossed_above", [S("a"), S("b")], o_crossed_above, "bool", lambda p: 1, "a cắt LÊN b: a > b và a[-1] <= b[-1]"),
    _op("crossed_below", [S("a"), S("b")], o_crossed_below, "bool", lambda p: 1, "a cắt XUỐNG b: a < b và a[-1] >= b[-1]"),
    _op("current", [A("x")], o_current, _ret_shift, doc="giá trị nến hiện tại (đồng nhất)"),
    _op("previous", [A("x"), _PER()], o_shift, _ret_shift, lambda p: int(p.get("periods", 1)), "giá trị k nến trước"),
    _op("shift", [A("x"), _PER()], o_shift, _ret_shift, lambda p: int(p.get("periods", 1)), "dịch k >= 1 nến về quá khứ"),
    _op("diff", [S("x"), _PER()], o_diff, "num", lambda p: int(p.get("periods", 1))),
    _op("pct_change", [S("x"), _PER()], o_pct_change, "num", lambda p: int(p.get("periods", 1))),
    _op("rising", [S("x"), _PER()], o_rising, "bool", lambda p: int(p.get("periods", 1)), "tăng liên tục k nến"),
    _op("falling", [S("x"), _PER()], o_falling, "bool", lambda p: int(p.get("periods", 1)), "giảm liên tục k nến"),
    _op("fillna", [S("x"), S("value", 0.0)], o_fillna, "num", doc="thay NaN bằng value"),
    _op("ffill", [S("x")], o_ffill, "num", doc="điền NaN bằng giá trị hợp lệ gần nhất trước đó"),
    _op("abs", [S("x")], o_abs, "num"),
    _op("clip", [S("x"), F("lower", None), F("upper", None)], o_clip, "num", doc="kẹp trong [lower, upper]"),
    _op("isna", [S("x")], o_isna, "bool"),
    _op("notna", [S("x")], o_notna, "bool"),
    _op("isfinite", [S("x")], o_isfinite, "bool"),
    _op("zero_ifna", [S("x")], o_zero_ifna, "num", doc="NaN -> 0"),
    _op("sign", [S("x")], o_sign, "num"),
    _op("replace", [S("x"), F("to_replace"), F("value")], o_replace, "num", doc="thay giá trị to_replace bằng value"),
    _op("between", [S("x"), S("lower"), S("upper")], o_between, "bool", doc="lower <= x <= upper"),
    _op("where", [B("cond"), A("a"), A("b")], o_where, _ret_where, doc="cond ? a : b"),
    _op("value_when", [B("cond"), S("x")], o_value_when, "num", doc="giá trị x tại nến gần nhất cond đúng"),
    _op("bars_since", [B("cond")], o_bars_since, "num", doc="số nến kể từ lần cond đúng gần nhất (0 = nến này, NaN = chưa từng)"),
    _op("hold_for", [B("cond"), _PER()], o_hold_for, "bool", lambda p: int(p.get("periods", 1)), "giữ True k nến kể từ lần cond đúng gần nhất (gồm nến đó)"),
    _op("crossed_above_value", [S("a"), F("value")], o_crossed_above_value, "bool", lambda p: 1, "a cắt LÊN một mức hằng số"),
    _op("crossed_below_value", [S("a"), F("value")], o_crossed_below_value, "bool", lambda p: 1, "a cắt XUỐNG một mức hằng số"),
    _op("and_", [B("a"), B("b")], o_and_, "bool"),
    _op("or_", [B("a"), B("b")], o_or_, "bool"),
    _op("not_", [B("a")], o_not_, "bool"),
]}

assert len(OPS) == 30, len(OPS)
