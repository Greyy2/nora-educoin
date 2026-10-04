"""Tín hiệu của sổ trên nến ĐÃ ĐÓNG mới nhất từ dữ liệu sàn — CÙNG đường tính với backtest (E9-S1 AC4, test chênh lệch bằng 0):
dựng engine của tài sản y như PortfolioEngine (_make_trackers), nạp nến từng khung vào đúng chỗ engine tự nạp (df_base / frames), rồi
_build_matrix + VectorEvaluator trên cây của từng tracker. Không có bản tính tín hiệu thứ hai.

Chỉ báo tính từ ĐẦU dữ liệu đưa vào (gốc cố định): sàn trả tối đa ~1500 nến mỗi khung, nên giá trị EMA/ADX dài ở nến cuối có thể lệch rất nhỏ so
với backtest (tính từ 2023). Kiểm chênh lệch: test_live_bot.py (cùng dữ liệu -> trùng từng bit)."""
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backend.core.signals.evaluator import VectorEvaluator, lag_key

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def klines_frame(rows: List[List[Any]], now_ms: int) -> pd.DataFrame:
    """Nến sàn -> DataFrame engine; bỏ nến CHƯA đóng (close_time >= now)."""
    df = pd.DataFrame([r[:7] for r in rows], columns=KLINE_COLS)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    df = df[df["close_time"].astype("int64") < now_ms].drop(columns=["close_time"]).reset_index(drop=True)
    df["is_filled"] = 0
    return df


def required_frames(symbol: str, strategies: List[Dict[str, Any]], base_frame: str) -> List[str]:
    """Các khung engine cần cho sổ (gồm khung chạy và 4h — engine luôn nạp 4h)."""
    eng, _ = _engine(symbol, strategies, base_frame, 0, DAY)
    return sorted(set(eng._refs_by_frame()) | {base_frame, "4h"})


DAY = 86_400_000


def _engine(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    """Engine của tài sản (chưa nạp dữ liệu). start/end chỉ để engine kiểm giới hạn độ dài — dữ liệu do evaluate gán trực tiếp."""
    from backend.core.backtest.portfolio import PortfolioEngine
    end = max(int(end), int(start) + DAY)
    start = max(int(start), end - 1000 * DAY)
    pe = PortfolioEngine([symbol], strategies, start, end, trade_start_ts=start, use_cache=False, base_frame=base_frame)
    return pe._make_trackers(symbol, pe.ledger)


def evaluate(symbol: str, strategies: List[Dict[str, Any]], frames: Dict[str, pd.DataFrame], base_frame: str,
             with_vec: bool = False) -> Dict[str, Any]:
    """frames = {khung: DataFrame nến đã đóng từ đầu dữ liệu}. -> {"t": open_time nến chạy, "close", "high", "low",
    "entries": [{"strategy", "side", "match": bool[], "stop": bool[], "vol": float[] | None, "tracker"}]} (mảng theo nến chạy).
    with_vec: thêm "vec" (VectorEvaluator trên cùng ma trận) để giải thích từng điều kiện (core/analytics/signal_explain.py)."""
    base = frames[base_frame]
    eng, pairs = _engine(symbol, strategies, base_frame, int(base["open_time"].iloc[0]), int(base["open_time"].iloc[-1]))
    base = eng._prepare_candles(base)
    eng.df_base, eng.df_base_hist = base, base
    eng.frames = {fr: (eng._enrich_4h(eng._prepare_candles(df)) if fr == "4h" else eng._prepare_candles(df))
                  for fr, df in frames.items() if fr != base_frame}
    eng.df_4h = eng.frames.get("4h")
    df1, cols = eng._build_matrix()
    n = len(df1)
    vec = VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))
    out = {"t": df1["open_time"].to_numpy(dtype="int64"), "open": df1["open"].to_numpy(dtype=float), "close": df1["close"].to_numpy(dtype=float),
           "high": df1["high"].to_numpy(dtype=float), "low": df1["low"].to_numpy(dtype=float), "entries": []}
    labels = None
    if any(st.get("regime") for st, _ in pairs):
        from backend.core.regime.classifier import classify, profile_cfg
        cfg = profile_cfg(next((st["regime"].get("classifier") for st, _ in pairs if st.get("regime")), None))
        labels = classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), out["t"], cfg)
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)
        if labels is not None and st.get("regime"):
            from backend.core.regime.classifier import masks_for
            allowed, fuse = masks_for(st, st["side"], labels)
            match = match & allowed
            if fuse is not None:
                stop = stop | fuse
        vcol = eng.vol_column(tr)
        out["entries"].append({"strategy": st["id"], "side": st["side"], "match": match, "stop": stop,
                               "vol": cols.get(vcol) if vcol else None, "tracker": tr,
                               "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None})
    if with_vec:
        out["vec"] = vec
    return out
