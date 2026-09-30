"""Engine Mô phỏng Backtest Toàn diện (Backtest Simulation Engine)."""
import time
from typing import List, Optional

import pandas as pd
from backend.backtest.execution import PositionTracker
from backend.core.loader import CandleLoader
from backend.core.params import StrategyParams
from backend.db.models import PositionStatus, PositionType


class BacktestEngine:
    """Quản lý luồng thời gian và điều phối dữ liệu cho tất cả các chiến lược con."""

    MAX_BACKTEST_DAYS = 90
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))

    def __init__(
        self,
        account_id: int,
        campaign_id: int,
        symbol: str,
        start_ts: int,
        end_ts: int,
        trade_start_ts: Optional[int] = None,
    ):
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.trade_start_ts = trade_start_ts if trade_start_ts is not None else start_ts

        days_diff = (end_ts - start_ts) / (86400 * 1000)
        if days_diff > self.MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Limit Exceeded: Yêu cầu chạy {days_diff:.1f} ngày. "
                f"Server chỉ cho phép tối đa {self.MAX_BACKTEST_DAYS} ngày để bảo vệ tài nguyên!"
            )

        self.trackers: List[PositionTracker] = []
        self.df_1m: Optional[pd.DataFrame] = None
        self.df_4h: Optional[pd.DataFrame] = None
        self.closed_positions = []
        self.orders = []

    def load_data(self):
        loader_1m = CandleLoader(self.symbol, frame="1m", use_cache=True)
        self.df_1m = self._prepare_candles(loader_1m.load_data(self.start_ts, self.end_ts))

        # 2.4: Tăng buffer load 4h lên 5 ngày (~30 cây 4h) để tính ATR/Keltner 20 kỳ chuẩn xác
        buffer_ms = 5 * 86400000
        loader_4h = CandleLoader(self.symbol, frame="4h", use_cache=True)
        self.df_4h = self._enrich_4h(
            self._prepare_candles(loader_4h.load_data(self.start_ts - buffer_ms, self.end_ts + buffer_ms))
        )

    def add_strategy_flow(self, flow_name: str, params: StrategyParams):
        if len(self.trackers) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")

        ast_dict = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast_dict.get("type", "")).upper()
        if not ast_type and isinstance(params.extra, dict) and "type" in params.extra:
            ast_type = str(params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT

        tracker = PositionTracker(
            account_id=self.account_id,
            campaign_id=self.campaign_id,
            symbol=self.symbol,
            flow_name=flow_name,
            params=params,
            pos_type=pos_type,
        )
        self.trackers.append(tracker)

    def run(self):
        if self.df_1m is None or self.df_1m.empty:
            return
        if self.df_4h is None or self.df_4h.empty:
            return

        self.closed_positions = []
        self.orders = []
        print(f"Bắt đầu chạy backtest cho {self.symbol} ({len(self.df_1m)} nến 1 phút)...")
        start_time = time.time()

        df_1m_sorted = self._prepare_candles(self.df_1m)
        df_4h_sorted = self._prepare_candles(self.df_4h)
        if df_1m_sorted.empty or df_4h_sorted.empty:
            return

        # 2.1: Look-ahead khung 4h: một nến 1m chỉ được thấy cây 4h đã đóng tại thời điểm nến 1m đó đóng
        M1, H4 = 60_000, 4 * 3_600_000
        left = df_1m_sorted.assign(decision_time=df_1m_sorted["open_time"] + M1)
        right = df_4h_sorted.add_suffix("_4h")  # giữ open_time_4h
        right["avail_time"] = right["open_time_4h"] + H4

        merged_df = pd.merge_asof(
            left.sort_values("decision_time"),
            right.sort_values("avail_time"),
            left_on="decision_time",
            right_on="avail_time",
            direction="backward",
        )
        merged_df = merged_df.dropna(subset=["close_4h"])
        if merged_df.empty:
            return

        records = merged_df.to_dict("records")
        cols_4h = set(right.columns) - {"avail_time"}

        for row in records:
            row_4h = {k[:-3]: v for k, v in row.items() if k in cols_4h and k.endswith("_4h")}
            row_1m = {k: v for k, v in row.items() if k not in cols_4h and k not in ("decision_time", "avail_time")}

            current_time = int(row_1m.get("open_time", 0) or 0)
            can_trade = (current_time >= self.trade_start_ts)
            current_open_positions = sum(1 for trk in self.trackers if trk.is_open)

            for tracker in self.trackers:
                max_trades = getattr(tracker.params, "max_open_trades", 45) or 45
                tracker.update_candle(
                    row_1m,
                    row_4h,
                    open_positions=current_open_positions,
                    max_open_trades=max_trades,
                    can_trade=can_trade,
                )

                if not tracker.is_open and tracker.position and tracker.position.status != PositionStatus.OPEN:
                    self.closed_positions.append(tracker.position)
                    self.orders.extend(tracker.orders)
                    tracker.position = None
                    tracker.orders = []

        # Đóng vị thế còn mở ở cây nến cuối tại giá OPEN của nến cuối
        for tracker in self.trackers:
            if tracker.is_open and tracker.position:
                last_open = float(records[-1].get("open", 0.0))
                last_time = int(records[-1].get("open_time", 0))
                tracker.force_close(last_time, last_open, "End of Backtest")
                self.closed_positions.append(tracker.position)
                self.orders.extend(tracker.orders)
                tracker.position = None
                tracker.orders = []

        elapsed = time.time() - start_time
        print(f"Hoàn thành backtest. Thu được {len(self.closed_positions)} vị thế. Mất {elapsed:.2f} giây.")

    def get_results(self):
        return {
            "positions": self.closed_positions,
            "orders": self.orders,
        }

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
        for column in ("open", "high", "low", "close", "volume"):
            if column in clean.columns:
                clean[column] = pd.to_numeric(clean[column], errors="coerce")
        return clean.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

    @classmethod
    def _enrich_4h(cls, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        required = {"high", "low", "close"}
        if not required.issubset(df.columns):
            return df

        enriched = df.copy()
        high = pd.to_numeric(enriched["high"], errors="coerce")
        low = pd.to_numeric(enriched["low"], errors="coerce")
        close = pd.to_numeric(enriched["close"], errors="coerce")
        prev_close = close.shift(1)
        true_range = pd.concat(
            [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)

        for period in (14, 17, 20):
            enriched[f"atr{period}"] = true_range.rolling(period, min_periods=1).mean()
        enriched["atr"] = enriched["atr17"]

        for period, multiplier in cls.KELTNER_CONFIGS:
            mid = close.ewm(span=period, adjust=False, min_periods=1).mean()
            atr = enriched[f"atr{period}"]
            suffix = cls._keltner_suffix(period, multiplier)
            enriched[f"kmid{suffix}"] = mid
            enriched[f"kup{suffix}"] = mid + atr * multiplier
            enriched[f"klo{suffix}"] = mid - atr * multiplier

        return enriched

    @staticmethod
    def _keltner_suffix(period: int, multiplier: float) -> str:
        multiplier_text = str(multiplier).replace(".", "")
        return f"{period}_{multiplier_text}"
