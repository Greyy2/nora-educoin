"""Engine mô phỏng backtest (1m thực thi + kernel đa khung).

Luồng:
1. Nạp nến 1m (kèm is_filled) và các khung được AST tham chiếu (luôn có 4h để tương thích).
2. Tính kernel (backend/signals/kernels.py) trên nến ĐÃ ĐÓNG của từng khung; kernel 1m chỉ
   tính trên các phút CÓ giao dịch (nến điền không phải một quan sát).
3. Ghép vào dòng thời gian 1m: nến 1m đóng lúc T chỉ thấy nến khung F đã đóng tại thời điểm <= T
   (merge_asof theo decision_time = open_1m + 1m và avail_time = open_F + độ dài F).
4. Tính tín hiệu match/stop của từng flow bằng VectorEvaluator (cùng ngữ nghĩa LogicEvaluator).
5. Vòng lặp khớp lệnh theo từng nến 1m có giao dịch (backtest/execution.py).
6. Đường vốn mark-to-market (lấy mẫu mỗi giờ + mỗi lần đóng lệnh) để đo sụt giảm cả phần lỗ treo.
"""
import time
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.backtest.execution import CapitalLedger, PositionTracker
from backend.core.evaluator import VectorEvaluator, lag_key
from backend.core.loader import CandleLoader
from backend.core.params import StrategyParams
from backend.db.models import PositionType
from backend.signals import kernels

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
    MTM_SAMPLE_MINUTES = 60
    # Bỏ qua nến "rảnh" (không vị thế mở, không lệnh chờ, không tín hiệu vào) — kết quả BIT-IDENTICAL (test golden + test bật/tắt).
    _SKIP_IDLE = True

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
        self.bar_hook = None  # (tuỳ chọn, dùng cho test) gọi sau mỗi nến có giao dịch: hook(engine, t)

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
        if self.df_1m is None or self.df_1m.empty:
            return
        self.closed_positions, self.orders, self.equity_curve = [], [], []
        print(f"Bắt đầu chạy backtest cho {self.symbol} ({len(self.df_1m)} nến 1 phút)...")
        started = time.time()

        df1, cols = self._build_matrix()
        n = len(df1)

        def get(frame, column, lag):
            return cols.get(f"{frame}|{lag_key(column, lag)}", np.full(n, np.nan))

        vec = VectorEvaluator(n, get)
        signals = [(vec.tree(tr.match_tree), vec.tree(tr.stop_tree)) for tr in self.trackers]
        vols = [cols.get(self.vol_column(tr)) if self.vol_column(tr) else None for tr in self.trackers]

        t_arr = df1["open_time"].to_numpy(dtype="int64")
        o_arr, h_arr = df1["open"].to_numpy(dtype="float64"), df1["high"].to_numpy(dtype="float64")
        l_arr, c_arr = df1["low"].to_numpy(dtype="float64"), df1["close"].to_numpy(dtype="float64")
        filled = df1["is_filled"].to_numpy() == 1
        max_open = [int(getattr(tr.params, "max_open_trades", 45) or 45) for tr in self.trackers]

        last_sample = None
        last_real = None
        self.ruined_at = None
        f_times = self.funding["funding_time"].to_numpy(dtype="int64") if self.funding is not None else np.array([], "int64")
        f_rates = self.funding["rate"].to_numpy(dtype="float64") if self.funding is not None else np.array([])
        f_idx = 0
        real_pos = np.flatnonzero(~filled)  # chỉ nến có giao dịch (nến điền is_filled=1 bị bỏ qua hoàn toàn)
        n_real = len(real_pos)
        rt = t_arr[real_pos]
        skip = self._SKIP_IDLE and self.bar_hook is None   # bar_hook (test) cần kiểm bất biến mỗi nến
        if skip:
            # Nến có tín hiệu vào của BẤT KỲ flow nào, từ trade_start_ts (trước đó on_bar không làm gì khi phẳng)
            sig_any = np.zeros(n, dtype=bool)
            for match, _ in signals:
                sig_any |= match
            cand = np.flatnonzero(sig_any[real_pos] & (rt >= self.trade_start_ts))
        busy = False  # nến trước còn flow mở / lệnh chờ?
        step = self.MTM_SAMPLE_MINUTES * 60_000
        r = 0
        while r < n_real:
            if skip and not busy and not any(tr.is_open or tr.pending_entry or tr.pending_exit for tr in self.trackers):
                k = int(np.searchsorted(cand, r))
                land = int(cand[k]) if k < len(cand) else n_real
                if land > r:  # r..land-1: phẳng, không tín hiệu -> chỉ còn mẫu vốn theo giờ (funding no-op khi phẳng;
                    # f_idx sẽ trượt tại nến đáp xuống, lúc đó mọi flow vẫn phẳng nên không trả funding)
                    last_real = int(real_pos[land - 1])
                    j = r if last_sample is None else int(np.searchsorted(rt, last_sample + step, side="left"))
                    while j < land:
                        ij = int(real_pos[j])
                        self._sample_equity(int(rt[j]), c_arr[ij], l_arr[ij], h_arr[ij])
                        last_sample = int(rt[j])
                        j = int(np.searchsorted(rt, last_sample + step, side="left"))
                    r = land
                    continue
            i = int(real_pos[r])
            r += 1
            last_real = i
            t = int(t_arr[i])
            while f_idx < len(f_times) and f_times[f_idx] <= t:  # funding đến hạn trước/ tại nến này
                for tr in self.trackers:
                    tr.apply_funding(float(f_rates[f_idx]), float(o_arr[i]))
                f_idx += 1
            can_trade = t >= self.trade_start_ts
            open_now = sum(1 for tr in self.trackers if tr.is_open)
            closed_any = False
            busy = False
            for k, tracker in enumerate(self.trackers):
                match, stop = signals[k]
                pos = tracker.on_bar(t, o_arr[i], h_arr[i], l_arr[i], c_arr[i],
                                     entry_signal=bool(match[i]) and can_trade,
                                     stop_signal=bool(stop[i]),
                                     can_open=can_trade and open_now < max_open[k],
                                     vol=float(vols[k][i]) if vols[k] is not None else float("nan"))
                if tracker.is_open or tracker.pending_entry:
                    busy = True
                if pos is not None:
                    self._collect(tracker, pos)
                    closed_any = True
                    if self.ledger.equity <= 0 and self.ruined_at is None:
                        self.ruined_at = t
            if self.bar_hook is not None:
                self.bar_hook(self, t)
            if closed_any or last_sample is None or t - last_sample >= step:
                self._sample_equity(t, c_arr[i], l_arr[i], h_arr[i])
                last_sample = t

        if last_real is not None:
            t = int(t_arr[last_real])
            for tracker in self.trackers:
                pos = tracker.force_close(t, float(o_arr[last_real]), "End of Backtest")
                if pos is not None:
                    self._collect(tracker, pos)
            self._sample_equity(t, c_arr[last_real], l_arr[last_real], h_arr[last_real])

        print(f"Hoàn thành backtest. Thu được {len(self.closed_positions)} vị thế. Mất {time.time() - started:.2f} giây.")

    def _collect(self, tracker: PositionTracker, pos) -> None:
        self.closed_positions.append(pos)
        self.orders.extend(tracker.orders)
        tracker.orders = []

    def _sample_equity(self, t: int, close: float, low: float, high: float) -> None:
        """Vốn mark-to-market = vốn đã chốt (ledger, gồm funding) + lãi/lỗ treo của vị thế mở."""
        mtm = sum(tr.unrealized_pnl_usd(close) for tr in self.trackers)
        worst = sum(tr.unrealized_pnl_usd(low if tr.is_long else high) for tr in self.trackers)
        self.equity_curve.append({
            "time": t,
            "equity": round(self.ledger.equity + mtm, 4),
            "equity_worst": round(self.ledger.equity + worst, 4),
        })

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
