"""Signal kernels — lõi chỉ báo của Nora.

Mỗi kernel là một hàm THUẦN và CAUSAL: giá trị tại nến t chỉ dùng dữ liệu của các nến <= t
(nến t đã đóng). Tính chất này được kiểm bằng test "prefix-invariance":
    kernel(df)[:t] == kernel(df[:t])      với mọi t.

Trong giai đoạn khởi động (chưa đủ `period` nến), kernel trả NaN; khi đó điều kiện AST
nào dùng giá trị NaN đều là False (không có tín hiệu sớm từ dữ liệu thiếu).

Tên cột dùng trong AST:   <kernel>_<tham số 1>[_<tham số 2>...]
    rsi_14      ema_50      atr_14      bbz_20      bbl_20_2      dch_20      vwapdev_60

Kernel được tính trên nến ĐÃ ĐÓNG của từng khung (1m, 5m, 15m, 1h, 4h, 24h) và chỉ
được nhìn thấy ở nến 1m khi nến khung đó đã đóng (xem backtest/engine.py).
"""
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BASE_COLUMNS = ("open", "high", "low", "close", "volume")


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


def _rma(x: pd.Series, n: int) -> pd.Series:
    """Wilder moving average (RMA), đệ quy -> causal. NaN trong n-1 nến đầu."""
    return x.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
                     axis=1).max(axis=1)


# ─── Xu hướng ────────────────────────────────────────────────────────────────

def sma(df, n):
    return df["close"].rolling(int(n), min_periods=int(n)).mean()


def ema(df, n):
    return df["close"].ewm(span=int(n), adjust=False, min_periods=int(n)).mean()


def roc(df, n):
    """% thay đổi giá so với n nến trước."""
    return (df["close"] / df["close"].shift(int(n)) - 1.0) * 100.0


def er(df, n):
    """Kaufman Efficiency Ratio (0..1): gần 1 = đi một chiều (xu hướng), gần 0 = nhiễu/đi ngang."""
    n = int(n)
    change = (df["close"] - df["close"].shift(n)).abs()
    path = df["close"].diff().abs().rolling(n, min_periods=n).sum()
    return (change / path.replace(0, np.nan)).clip(0, 1)


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
    """Wilder RSI (0..100)."""
    n = int(n)
    delta = df["close"].diff()
    gain = _rma(delta.clip(lower=0), n)
    loss = _rma((-delta).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))  # không có nhịp giảm: 100; đứng yên: 50
    return out.where(gain.notna())


def bbz(df, n):
    """Z-score của close so với SMA n (đơn vị: độ lệch chuẩn)."""
    n = int(n)
    mid = df["close"].rolling(n, min_periods=n).mean()
    std = df["close"].rolling(n, min_periods=n).std(ddof=0)
    return (df["close"] - mid) / std.replace(0, np.nan)


def bbm(df, n, k):
    return sma(df, n)


def bbu(df, n, k):
    n = int(n)
    return sma(df, n) + float(k) * df["close"].rolling(n, min_periods=n).std(ddof=0)


def bbl(df, n, k):
    n = int(n)
    return sma(df, n) - float(k) * df["close"].rolling(n, min_periods=n).std(ddof=0)


def bbw(df, n, k):
    """Độ rộng Bollinger (%) = (upper - lower) / mid * 100 — thấp = biến động nén."""
    return (bbu(df, n, k) - bbl(df, n, k)) / sma(df, n) * 100.0


def bbwp(df, n, k, m):
    """Phân vị (0..100) của độ rộng Bollinger trong m nến gần nhất — thấp = đang nén (squeeze)."""
    m = int(m)
    return bbw(df, n, k).rolling(m, min_periods=m).rank(pct=True) * 100.0


# ─── Biến động ───────────────────────────────────────────────────────────────

def atr(df, n):
    return _rma(_true_range(df), int(n))


def natr(df, n):
    """ATR theo % giá."""
    return atr(df, n) / df["close"] * 100.0


def rv(df, n):
    """Biến động thực (%) = độ lệch chuẩn log-return của n nến."""
    n = int(n)
    return np.log(df["close"]).diff().rolling(n, min_periods=n).std(ddof=0) * 100.0


def kcm(df, n, k):
    return ema(df, n)


def kcu(df, n, k):
    return ema(df, n) + float(k) * atr(df, n)


def kcl(df, n, k):
    return ema(df, n) - float(k) * atr(df, n)


# ─── Vùng giá / breakout ─────────────────────────────────────────────────────

def dch(df, n):
    """Đỉnh cao nhất của n nến TRƯỚC nến hiện tại (không gồm nến t) -> close > dch_n là breakout."""
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


def _w(mult: float = 1.0, extra: int = 0):
    def warm(*params):
        return int(max(float(p) for p in params) * mult) + extra if params else extra
    return warm


REGISTRY: Dict[str, KernelSpec] = {s.name: s for s in [
    KernelSpec("sma", ("n",), (20,), sma, _w(), "price", "Xu hướng", "Trung bình cộng close n nến"),
    KernelSpec("ema", ("n",), (50,), ema, _w(3), "price", "Xu hướng", "Trung bình mũ close n nến"),
    KernelSpec("roc", ("n",), (12,), roc, _w(1, 1), "%", "Xu hướng", "% thay đổi so với n nến trước"),
    KernelSpec("er", ("n",), (20,), er, _w(1, 1), "0..1", "Regime", "Efficiency ratio: 1 = xu hướng, 0 = đi ngang"),
    KernelSpec("adx", ("n",), (14,), adx, _w(4, 1), "0..100", "Regime", "Độ mạnh xu hướng (Wilder)"),
    KernelSpec("rsi", ("n",), (14,), rsi, _w(4, 1), "0..100", "Dao động", "RSI Wilder"),
    KernelSpec("bbz", ("n",), (20,), bbz, _w(), "σ", "Dao động", "Z-score close so với SMA n"),
    KernelSpec("bbm", ("n", "k"), (20, 2), bbm, _w(), "price", "Dao động", "Bollinger giữa"),
    KernelSpec("bbu", ("n", "k"), (20, 2), bbu, _w(), "price", "Dao động", "Bollinger trên"),
    KernelSpec("bbl", ("n", "k"), (20, 2), bbl, _w(), "price", "Dao động", "Bollinger dưới"),
    KernelSpec("bbw", ("n", "k"), (20, 2), bbw, _w(), "%", "Biến động", "Độ rộng Bollinger (%)"),
    KernelSpec("bbwp", ("n", "k", "m"), (20, 2, 120), bbwp, lambda n, k, m: int(n) + int(m), "0..100", "Biến động",
               "Phân vị độ rộng Bollinger trong m nến (thấp = nén)"),
    KernelSpec("atr", ("n",), (14,), atr, _w(4, 1), "price", "Biến động", "ATR Wilder"),
    KernelSpec("natr", ("n",), (14,), natr, _w(4, 1), "%", "Biến động", "ATR theo % giá"),
    KernelSpec("rv", ("n",), (60,), rv, _w(1, 1), "%", "Biến động", "Độ lệch chuẩn log-return (%)"),
    KernelSpec("kcm", ("n", "k"), (20, 1.5), kcm, _w(4, 1), "price", "Biến động", "Keltner giữa (EMA)"),
    KernelSpec("kcu", ("n", "k"), (20, 1.5), kcu, _w(4, 1), "price", "Biến động", "Keltner trên"),
    KernelSpec("kcl", ("n", "k"), (20, 1.5), kcl, _w(4, 1), "price", "Biến động", "Keltner dưới"),
    KernelSpec("dch", ("n",), (20,), dch, _w(1, 1), "price", "Breakout", "Đỉnh n nến trước (không gồm nến hiện tại)"),
    KernelSpec("dcl", ("n",), (20,), dcl, _w(1, 1), "price", "Breakout", "Đáy n nến trước (không gồm nến hiện tại)"),
    KernelSpec("vwap", ("n",), (60,), vwap, _w(), "price", "Dòng tiền", "VWAP trượt n nến"),
    KernelSpec("vwapdev", ("n",), (60,), vwapdev, _w(), "%", "Dòng tiền", "% lệch close so với VWAP n nến"),
    KernelSpec("volz", ("n",), (60,), volz, _w(), "σ", "Dòng tiền", "Z-score khối lượng"),
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


def is_kernel_column(column: str) -> bool:
    return parse_column(column) is not None


def compute(df: pd.DataFrame, column: str) -> pd.Series:
    """Tính một cột kernel trên DataFrame OHLCV (đã sắp theo thời gian)."""
    parsed = parse_column(column)
    if parsed is None:
        raise ValueError(f"Cột kernel không hợp lệ: {column!r}")
    spec, params = parsed
    out = spec.fn(df, *params)
    return out.replace([np.inf, -np.inf], np.nan).astype("float64")


def warmup_bars(column: str) -> int:
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
