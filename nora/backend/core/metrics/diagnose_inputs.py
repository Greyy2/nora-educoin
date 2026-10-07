"""Đầu vào dữ liệu thật cho chẩn đoán (core/metrics/diagnose.py): giá ngày của từng tài sản, chuỗi thị trường (BTC hoặc chỉ số rổ), nến khung chiến lược.

Mọi thứ đọc từ CHÍNH nguồn dữ liệu của lần chạy (env NORA_EXCHANGE / NORA_LOCAL_DATA_ROOT đã đặt trước khi chạy) qua CandleLoader — cùng kho với engine.
Nhãn thời gian = giờ ĐÓNG nến (open_time + độ dài khung) như đường vốn ngày của custom_run.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DAY = 86_400_000
_FRAME_ORDER = ("24h", "4h", "1h", "15m", "5m", "1m")


def _clean(df: pd.DataFrame, drop_filled: bool = True) -> pd.DataFrame:
    from backend.core.backtest.engine import BacktestEngine
    out = BacktestEngine._prepare_candles(df)
    if drop_filled and "is_filled" in out.columns:
        out = out[pd.to_numeric(out["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
    return out


def daily_close(symbol: str, end: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(nhãn đóng ngày ms, giá đóng cửa ngày) của tài sản từ đầu lịch sử tới `end`; khung 24h nếu có, không thì gộp từ khung nhỏ hơn. None nếu không có dữ liệu."""
    from backend.core.data.loader import CandleLoader
    for frame in _FRAME_ORDER:
        try:
            df = _clean(CandleLoader(symbol, frame=frame, use_cache=True).load_data(0, end))
        except FileNotFoundError:
            continue
        if df.empty:
            continue
        t, c = df["open_time"].to_numpy(dtype="int64"), df["close"].to_numpy(dtype="float64")
        if frame != "24h":
            day = t // DAY * DAY
            keep = np.r_[day[1:] != day[:-1], True]            # nến cuối của mỗi ngày
            t, c = day[keep], c[keep]
        return t + DAY, c
    return None


def load_prices(symbols: List[str], end: int) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """{ký hiệu dữ liệu (BTC, BTC@perp, ...): (nhãn ngày, giá đóng)} cho các tài sản đọc được."""
    out = {}
    for s in symbols:
        r = daily_close(s, end)
        if r is not None:
            out[str(s).split(":")[-1]] = r
    return out


def market_series(prices: Dict[str, Tuple[np.ndarray, np.ndarray]], weights: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """Chuỗi giá thị trường để phân chế độ: BTC nếu có trong rổ; không thì chỉ số rổ rebalance ngày theo trọng số `weights` (mặc định đều) trên các coin có giá ngày hôm đó."""
    by_base: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for k, v in prices.items():
        by_base.setdefault(k.split("@")[0], v)
    if not by_base:
        return None
    if "BTC" in by_base:
        lab, cl = by_base["BTC"]
        return {"label_times": lab, "close": cl, "source": "BTC"}
    frame = pd.DataFrame({b: pd.Series(c, index=l) for b, (l, c) in by_base.items()}).sort_index()
    rets = frame.pct_change(fill_method=None)
    w = pd.Series({b: float((weights or {}).get(b, 1.0)) for b in frame.columns})
    valid = rets.notna()
    wsum = (valid * w).sum(axis=1)
    daily = (rets.fillna(0.0) * w).sum(axis=1) / wsum.where(wsum > 0)
    index = (1.0 + daily.fillna(0.0)).cumprod()
    return {"label_times": index.index.to_numpy(dtype="int64"), "close": index.to_numpy(dtype="float64"),
            "source": f"chỉ số rổ {len(by_base)} coin ({'theo trọng số' if weights else 'đều'})"}


def strategy_frames(symbols: List[str], timeframe: str, end: int, drop_filled: bool = False) -> Dict[str, pd.DataFrame]:
    """Nến khung chiến lược của từng tài sản từ đầu lịch sử tới `end` (chỉ báo như engine: gốc cố định); tài sản không đọc được bị bỏ qua.
    drop_filled=True khi khung chiến lược = khung chạy (engine bỏ nến điền ở khung chạy)."""
    from backend.core.data.loader import CandleLoader
    out = {}
    for s in symbols:
        try:
            df = _clean(CandleLoader(s, frame=timeframe, use_cache=True).load_data(0, end), drop_filled)
        except FileNotFoundError:
            continue
        if not df.empty:
            out[str(s).split(":")[-1]] = df
    return out
