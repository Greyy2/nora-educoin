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


HISTORY_START = 0   # chỉ báo tính từ đầu lịch sử dữ liệu (gốc cố định)


class BacktestEngine:
    """Điều phối dữ liệu, tín hiệu và các flow chiến lược."""

    MAX_BACKTEST_DAYS = 1100
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, account_id: int, campaign_id: int, symbol: str, start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = 10000.0, base_frame: str = "1m"):
        if base_frame not in FRAME_MS:
            raise ValueError(f"Khung chạy không hợp lệ: {base_frame!r} (có: {list(FRAME_MS)})")
        self.base_frame = base_frame   # khung nến dùng để MÔ PHỎNG (khớp lệnh, SL/TP theo high/low của nến này)
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
        self.df_base: Optional[pd.DataFrame] = None        # nến khung chạy của cửa sổ (đã gồm warmup)
        self.df_base_hist: Optional[pd.DataFrame] = None   # lịch sử khung chạy từ gốc (chỉ khi có cột của chính khung chạy)
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
            for frame, column, lag in (collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree)
                                       | collect_field_refs(tracker.dca_tree)):
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
    def check_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Mọi khung tín hiệu / ATR phải >= khung chạy (không thể nhìn nến nhỏ hơn nến đang mô phỏng)."""
        refs = self._refs_by_frame() if refs is None else refs
        small = sorted(fr for fr in refs if fr in FRAME_MS and FRAME_MS[fr] < FRAME_MS[self.base_frame])
        if small:
            raise ValueError(f"Khung {small} nhỏ hơn khung chạy {self.base_frame} — chọn khung tín hiệu/ATR >= {self.base_frame}")

    def load_data(self):
        refs = self._refs_by_frame()
        self.check_frames(refs)
        base = self.base_frame
        warm = self._warmup_ms(base, refs.get(base, set()))
        loader = CandleLoader(self.symbol, frame=base, use_cache=True)
        # df_base = nến của KHUNG CHẠY (mặc định 1m)
        self.df_base = self._prepare_candles(loader.load_data(self.start_ts - warm, self.end_ts))
        # chỉ báo trên chính khung chạy tính từ đầu lịch sử (gốc cố định) -> cần cả lịch sử khi có cột của khung chạy
        self.df_base_hist = loader.load_data(HISTORY_START, self.end_ts) if refs.get(base) else None
        if self.trade_start_ts < self.start_ts:
            self.trade_start_ts = self.start_ts

        self.load_frames(refs)
        if any(tr.market == "perp" for tr in self.trackers):
            self.funding = self._load_funding()

    def minute_path(self, open_time: np.ndarray) -> Dict[str, np.ndarray]:
        """Đường giá 1m bên trong từng nến chạy (khung chạy > 1m) — cho khớp "extreme" đúng ngữ nghĩa 1m: lệnh stop khớp ở giá xấu nhất của
        NẾN 1m ĐẦU TIÊN chạm mức, không phải của cả nến 15m/1h/4h (quá bi quan, phụ thuộc khung chạy).
        -> {"m_a", "m_b": int64 (n) — nến chạy i gồm nến 1m [m_a[i], m_b[i]), "m_l", "m_h": float64}. Khung chạy 1m: mảng rỗng."""
        t = np.asarray(open_time, dtype="int64")
        if self.base_frame == "1m" or len(t) == 0:
            return {"m_a": np.zeros(0, dtype="int64"), "m_b": np.zeros(0, dtype="int64"), "m_l": np.zeros(0), "m_h": np.zeros(0)}
        step = FRAME_MS[self.base_frame]
        m1 = CandleLoader(self.symbol, frame="1m", use_cache=False).load_data(int(t[0]), int(t[-1]) + step - 1,
                                                                              columns=["open_time", "high", "low", "is_filled"])
        if "is_filled" in m1.columns:   # nến 1m điền (không giao dịch) không thể khớp lệnh
            m1 = m1[pd.to_numeric(m1["is_filled"], errors="coerce").fillna(0).astype(int) == 0]
        mt = m1["open_time"].to_numpy(dtype="int64")
        return {"m_a": np.searchsorted(mt, t).astype("int64"), "m_b": np.searchsorted(mt, t + step).astype("int64"),
                "m_l": m1["low"].to_numpy(dtype="float64"), "m_h": m1["high"].to_numpy(dtype="float64")}

    def needs_minute_path(self) -> bool:
        return needs_minute_path(self)

    def load_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Nạp các khung lớn (không gồm 1m) từ ĐẦU lịch sử dữ liệu tới end_ts: chỉ báo tính từ gốc cố định (như TradingView) nên giá trị
        tại nến t không phụ thuộc cửa sổ backtest bắt đầu ở đâu (chỉ phụ thuộc dữ liệu <= t)."""
        refs = self._refs_by_frame() if refs is None else refs
        for frame in sorted(set(refs) | {"4h"}):
            if frame == self.base_frame or frame not in FRAME_MS or FRAME_MS[frame] < FRAME_MS[self.base_frame]:
                continue
            loader = CandleLoader(self.symbol, frame=frame, use_cache=True)
            df = self._prepare_candles(loader.load_data(HISTORY_START, self.end_ts))
            self.frames[frame] = self._enrich_4h(df) if frame == "4h" else df
        self.df_4h = self.frames.get("4h")

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
    def _build_matrix(self, only: Optional[Set[str]] = None) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
        """only: chỉ tính các cột có tên trong tập này ("khung|cột[__lagN]") — dữ liệu dùng chung điền cột còn thiếu.
        Mỗi cột tính độc lập trên khung đã nạp theo refs ĐẦY ĐỦ (frame_features), nên giá trị y hệt khi tính cả bộ."""
        df1 = self._prepare_candles(self.df_base)
        if "is_filled" not in df1.columns:
            df1["is_filled"] = 0
        df1["is_filled"] = pd.to_numeric(df1["is_filled"], errors="coerce").fillna(0).astype(int)
        refs = self._refs_by_frame()
        if only is not None:
            refs = {fr: {(c, lag) for c, lag in rs if f"{fr}|{lag_key(c, lag)}" in only} for fr, rs in refs.items()}
            refs = {fr: rs for fr, rs in refs.items() if rs}
        cols: Dict[str, np.ndarray] = {}
        open_time = df1["open_time"].to_numpy()
        base = self.base_frame
        for frame in ([base] if base in refs else []) + [f for f in refs if f != base]:
            if frame not in FRAME_MS:
                continue
            t_frame, vals = self.frame_values(frame, refs[frame])
            idx = self.align_index(frame, t_frame, open_time, base)
            for cid, v in vals.items():
                cols[cid] = self.gather(v, idx)
        return df1, cols

    def frame_values(self, frame: str, refs: Set[Tuple[str, int]]) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """Giá trị các cột `refs` của khung `frame` trên MỌI nến của khung từ đầu lịch sử (gốc cố định) -> (open_time nến, {cid: giá trị}).
        Khung 1m: chỉ phút có giao dịch (bỏ nến điền). Khung lớn: các nến đã nạp bằng load_frames. Mỗi cột tính độc lập."""
        if frame == self.base_frame:
            src = getattr(self, "df_base_hist", None)
            if src is None:
                src = self.df_base       # dữ liệu gán thẳng (test) = toàn bộ lịch sử
            if src is None:            # đường dữ liệu dùng chung: engine chưa nạp gì
                src = CandleLoader(self.symbol, frame=frame, use_cache=True).load_data(HISTORY_START, self.end_ts)
            src = self._prepare_candles(src)
            if "is_filled" in src.columns:
                src = src[pd.to_numeric(src["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
            if frame == "4h":
                src = self._enrich_4h(src)
        elif frame == "4h" and self.df_4h is not None and not self.df_4h.empty:
            src = self._enrich_4h(self._prepare_candles(self.df_4h))
        else:
            src = self.frames.get(frame)
        if src is None or src.empty:
            return np.zeros(0, dtype="int64"), {f"{frame}|{lag_key(c, lag)}": np.zeros(0) for c, lag in sorted(refs)}
        feat = frame_features(src, refs)
        return (feat[KEY].to_numpy(dtype="int64"),
                {f"{frame}|{name}": feat[name].to_numpy(dtype="float64") for name in feat.columns if name != KEY})

    @staticmethod
    def align_index(frame: str, t_frame: np.ndarray, open_time: np.ndarray, base: str = "1m") -> np.ndarray:
        """Chỉ số nến khung dùng ở từng nến chạy `open_time` (-1 = chưa có). Khung = khung chạy: đúng nến đó (nến không giao dịch -> -1).
        Khung lớn hơn: nến cuối ĐÃ ĐÓNG trước thời điểm quyết định (open + độ dài khung <= t + độ dài nến chạy); open_time khung tăng ngặt
        (_prepare_candles bỏ trùng) nên searchsorted phải − 1 chọn đúng nến như merge_asof(direction="backward")."""
        q = np.asarray(open_time, dtype="int64")
        if len(t_frame) == 0:
            return np.full(len(q), -1, dtype="int64")
        if frame == base:
            pos = np.searchsorted(t_frame, q)
            hit = pos < len(t_frame)
            hit[hit] = t_frame[pos[hit]] == q[hit]
            pos[~hit] = -1
            return pos.astype("int64")
        return (np.searchsorted(t_frame + FRAME_MS[frame], q + FRAME_MS[base], side="right") - 1).astype("int64")

    @staticmethod
    def gather(vals: np.ndarray, idx: np.ndarray) -> np.ndarray:
        """Giá trị theo chỉ số căn phút (-1 -> NaN)."""
        if len(vals) == 0:
            return np.full(len(idx), np.nan)
        out = vals[np.maximum(idx, 0)]
        out[idx < 0] = np.nan
        return out

    def run(self):
        """Chạy backtest bằng kernel numba (core/backtest/kernel.py) — kết quả trùng từng bit với vòng lặp Python cũ (test/reference_engine.py)."""
        if self.df_base is None or self.df_base.empty:
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


def needs_minute_path(eng) -> bool:
    """Có cần đường giá 1m trong nến chạy không: khung chạy > 1m và có chiến lược khớp SL "extreme". Hàm tự do để engine tham chiếu
    (test/reference_engine.py) đi qua cùng đường dữ liệu dùng chung."""
    return getattr(eng, "base_frame", "1m") != "1m" and any(getattr(tr, "stop_fill", "level") == "extreme" for tr in getattr(eng, "trackers", []))
