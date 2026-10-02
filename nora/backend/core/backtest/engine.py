"""Engine mô phỏng backtest (1m thực thi + kernel đa khung).

Luồng:
1. Nạp nến 1m (kèm is_filled) và các khung được AST tham chiếu (luôn có 4h để tương thích).
2. Tính kernel (backend/core/signals/kernels.py) trên nến ĐÃ ĐÓNG của từng khung; kernel 1m chỉ
   tính trên các phút CÓ giao dịch (nến điền không phải một quan sát).
3. Ghép vào dòng thời gian 1m: nến 1m đóng lúc T chỉ thấy nến khung F đã đóng tại thời điểm <= T
   (merge_asof theo decision_time = open_1m + 1m và avail_time = open_F + độ dài F).
4. Tính tín hiệu match/stop của từng flow bằng VectorEvaluator (cùng ngữ nghĩa LogicEvaluator).
5. Vòng lặp khớp lệnh theo từng nến 1m có giao dịch (backtest/execution.py).
6. Đường vốn mark-to-market (lấy mẫu mỗi giờ + mỗi lần đóng lệnh) để đo sụt giảm cả phần lỗ treo.
"""
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.core.execute.ledger import CapitalLedger
from backend.core.execute.tracker import PositionTracker
from backend.core.signals.evaluator import lag_key
from backend.core.data.loader import CandleLoader
from backend.core.params.schema import StrategyParams
from backend.core.execute.models import PositionType
from backend.core.signals import kernels

FRAME_MS: Dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000,
}
LEGACY_4H_COLUMNS = {"atr", "atr14", "atr17", "atr20", "kup17_05", "kmid17_05", "klo17_05",
                     "kup20_15", "kmid20_15", "klo20_15"}
BASE_COLS = ("open", "high", "low", "close", "volume")
KEY = "__bar_open_time"  # cột khoá nội bộ (tránh trùng với cột "open_time" mà AST có thể dùng)


def collect_field_refs(tree) -> Set[Tuple[str, str, int]]:
    """Mọi (frame, column, lag) mà một cây điều kiện tham chiếu."""
    refs: Set[Tuple[str, str, int]] = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "frame" in node and "column" in node:
                refs.add((str(node["frame"]), str(node["column"]), int(node.get("index", 0) or 0)))
            for key in ("number_1", "number_2", "add", "subtract", "divide"):
                if key in node:
                    walk(node[key])
            for item in node.get("numbers", []) if isinstance(node.get("numbers"), list) else []:
                walk(item)

    walk(tree)
    return refs


def frame_features(df: pd.DataFrame, refs: Set[Tuple[str, int]]) -> pd.DataFrame:
    """Tính các cột (kernel/base/legacy) + cột trễ cho một khung. df đã sắp theo open_time."""
    out = pd.DataFrame({KEY: df["open_time"].to_numpy()})
    cache: Dict[str, pd.Series] = {}
    for column, lag in sorted(refs):
        if column not in cache:
            if column in df.columns:
                cache[column] = pd.to_numeric(df[column], errors="coerce").reset_index(drop=True)
            elif kernels.is_kernel_column(column):
                cache[column] = kernels.compute(df.reset_index(drop=True), column)
            else:
                cache[column] = pd.Series(np.nan, index=range(len(df)))
        series = cache[column]
        out[lag_key(column, lag)] = (series.shift(lag) if lag else series).to_numpy()
    return out


class BacktestEngine:
    """Điều phối dữ liệu, tín hiệu và các flow chiến lược."""

    MAX_BACKTEST_DAYS = 1100
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, account_id: int, campaign_id: int, symbol: str, start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.trade_start_ts = trade_start_ts if trade_start_ts is not None else start_ts
        self.initial_capital = float(initial_capital)

        days_diff = (end_ts - start_ts) / (86400 * 1000)
        if days_diff > self.MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Limit Exceeded: Yêu cầu chạy {days_diff:.1f} ngày. "
                f"Server chỉ cho phép tối đa {self.MAX_BACKTEST_DAYS} ngày để bảo vệ tài nguyên!"
            )

        self.trackers: List[PositionTracker] = []
        self.ledger = CapitalLedger(self.initial_capital)
        self.funding: Optional[pd.DataFrame] = None  # perp: funding_time, rate
        self.df_1m: Optional[pd.DataFrame] = None
        self.df_4h: Optional[pd.DataFrame] = None
        self.frames: Dict[str, pd.DataFrame] = {}
        self.closed_positions = []
        self.orders = []
        self.equity_curve: List[Dict[str, float]] = []

    # ─── Cấu hình ───────────────────────────────────────────────────────────
    def add_strategy_flow(self, flow_name: str, params: StrategyParams):
        if len(self.trackers) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")
        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast.get("type", "") or params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT
        self.trackers.append(PositionTracker(
            account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol, flow_name=flow_name,
            params=params, pos_type=pos_type, initial_capital=self.initial_capital, ledger=self.ledger,
        ))

    def _refs_by_frame(self) -> Dict[str, Set[Tuple[str, int]]]:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for frame, refs in (getattr(self, "extra_refs", None) or {}).items():   # vd. đặc trưng regime (core/regime)
            by_frame.setdefault(frame, set()).update(refs)
        for tracker in self.trackers:
            for frame, column, lag in collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree):
                by_frame.setdefault(frame, set()).add((column, lag))
            if tracker.exit_unit == "atr":  # ATR% cho SL/TP/trailing theo biến động
                by_frame.setdefault(tracker.atr_frame, set()).add((f"natr_{tracker.atr_period}", 0))
        return by_frame

    @staticmethod
    def vol_column(tracker: PositionTracker) -> Optional[str]:
        return f"{tracker.atr_frame}|natr_{tracker.atr_period}" if tracker.exit_unit == "atr" else None

    def _warmup_ms(self, frame: str, refs: Set[Tuple[str, int]]) -> int:
        bars = max([kernels.warmup_bars(c) + lag for c, lag in refs] + [0])
        return (bars + 2) * FRAME_MS[frame]

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def load_data(self):
        refs = self._refs_by_frame()
        warm_1m = self._warmup_ms("1m", refs.get("1m", set()))
        loader_1m = CandleLoader(self.symbol, frame="1m", use_cache=True)
        self.df_1m = self._prepare_candles(loader_1m.load_data(self.start_ts - warm_1m, self.end_ts))
        if self.trade_start_ts < self.start_ts:
            self.trade_start_ts = self.start_ts

        for frame in sorted(set(refs) | {"4h"}):
            if frame == "1m" or frame not in FRAME_MS:
                continue
            buffer_ms = max(self._warmup_ms(frame, refs.get(frame, set())), 5 * 86_400_000 if frame == "4h" else 0)
            loader = CandleLoader(self.symbol, frame=frame, use_cache=True)
            df = self._prepare_candles(loader.load_data(self.start_ts - buffer_ms, self.end_ts))
            self.frames[frame] = self._enrich_4h(df) if frame == "4h" else df
        self.df_4h = self.frames.get("4h")
        if any(tr.market == "perp" for tr in self.trackers):
            self.funding = self._load_funding()

    def _load_funding(self) -> Optional[pd.DataFrame]:
        """funding.pkl của instrument perp (nếu symbol là BTC@perp). Không có -> None (ghi rõ trong kết quả)."""
        import os
        from backend.db.local_pkl import resolve_symbol_dir
        path = resolve_symbol_dir(self.symbol)
        file = os.path.join(path, "funding.pkl") if path else None
        if not file or not os.path.isfile(file):
            return None
        df = pd.read_pickle(file)
        return df[(df["funding_time"] >= self.start_ts) & (df["funding_time"] <= self.end_ts)].sort_values("funding_time")

    # ─── Chạy ───────────────────────────────────────────────────────────────
    def _build_matrix(self) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
        df1 = self._prepare_candles(self.df_1m)
        if "is_filled" not in df1.columns:
            df1["is_filled"] = 0
        df1["is_filled"] = pd.to_numeric(df1["is_filled"], errors="coerce").fillna(0).astype(int)
        frames = dict(self.frames)
        if self.df_4h is not None and not self.df_4h.empty:
            frames["4h"] = self._enrich_4h(self._prepare_candles(self.df_4h))

        refs = self._refs_by_frame()
        cols: Dict[str, np.ndarray] = {}
        n = len(df1)

        # Khung 1m: kernel chỉ tính trên phút có giao dịch
        if refs.get("1m"):
            real = df1[df1["is_filled"] == 0].reset_index(drop=True)
            feat = frame_features(real, refs["1m"])
            aligned = pd.DataFrame({KEY: df1["open_time"].to_numpy()}).merge(feat, on=KEY, how="left")
            for name in feat.columns:
                if name != KEY:
                    cols[f"1m|{name}"] = aligned[name].to_numpy(dtype="float64")

        # Các khung lớn: chỉ nến đã đóng
        decision = pd.DataFrame({"decision_time": df1["open_time"].to_numpy() + FRAME_MS["1m"],
                                 "_row": np.arange(n)})
        for frame, frame_refs in refs.items():
            if frame == "1m" or frame not in FRAME_MS:
                continue
            fdf = frames.get(frame)
            if fdf is None or fdf.empty:
                for column, lag in frame_refs:
                    cols[f"{frame}|{lag_key(column, lag)}"] = np.full(n, np.nan)
                continue
            feat = frame_features(fdf, frame_refs)
            feat["avail_time"] = feat[KEY] + FRAME_MS[frame]
            merged = pd.merge_asof(decision, feat.drop(columns=[KEY]).sort_values("avail_time"),
                                   left_on="decision_time", right_on="avail_time", direction="backward")
            merged = merged.sort_values("_row")
            for name in feat.columns:
                if name not in (KEY, "avail_time"):
                    cols[f"{frame}|{name}"] = merged[name].to_numpy(dtype="float64")
        return df1, cols

    def run(self):
        """Chạy backtest bằng kernel numba (core/backtest/kernel.py) — kết quả trùng từng bit với vòng lặp Python cũ (test/reference_engine.py)."""
        if self.df_1m is None or self.df_1m.empty:
            return
        from backend.core.backtest.kernel import run_backtest
        run_backtest(self)

    def get_results(self):
        return {"positions": self.closed_positions, "orders": self.orders, "equity_curve": self.equity_curve,
                "ruined_at": getattr(self, "ruined_at", None), "final_equity": self.ledger.equity,
                "rejected_for_capital": self.ledger.rejected,
                "dca_layers_rejected": sum(tr.dca_rejected for tr in self.trackers),
                "funding_modeled": self.funding is not None,
                "funding_events": 0 if self.funding is None else int(len(self.funding))}

    # ─── Tiện ích dữ liệu ───────────────────────────────────────────────────
    @staticmethod
    def _prepare_candles(df: Optional[pd.DataFrame]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        if "open_time" not in df.columns:
            raise ValueError("Candle data thiếu cột open_time.")
        clean = df.reset_index(drop=True).copy()
        clean["open_time"] = pd.to_numeric(clean["open_time"], errors="coerce")
        clean = clean.dropna(subset=["open_time"])
        clean["open_time"] = clean["open_time"].astype("int64")
        for column in BASE_COLS:
            if column in clean.columns:
                clean[column] = pd.to_numeric(clean[column], errors="coerce")
        return clean.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

    @classmethod
    def _enrich_4h(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Cột 4h kiểu cũ (atr*, Keltner kup/kmid/klo) — giữ để tương thích template cũ."""
        if df is None or df.empty or not {"high", "low", "close"}.issubset(df.columns):
            return df
        if "kup20_15" in df.columns:
            return df
        enriched = df.copy()
        high, low, close = enriched["high"], enriched["low"], enriched["close"]
        prev_close = close.shift(1)
        true_range = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                               axis=1).max(axis=1)
        for period in (14, 17, 20):
            enriched[f"atr{period}"] = true_range.rolling(period, min_periods=1).mean()
        enriched["atr"] = enriched["atr17"]
        for period, multiplier in cls.KELTNER_CONFIGS:
            mid = close.ewm(span=period, adjust=False, min_periods=1).mean()
            suffix = f"{period}_{str(multiplier).replace('.', '')}"
            enriched[f"kmid{suffix}"] = mid
            enriched[f"kup{suffix}"] = mid + enriched[f"atr{period}"] * multiplier
            enriched[f"klo{suffix}"] = mid - enriched[f"atr{period}"] * multiplier
        return enriched

    @staticmethod
    def _keltner_suffix(period: int, multiplier: float) -> str:
        return f"{period}_{str(multiplier).replace('.', '')}"
