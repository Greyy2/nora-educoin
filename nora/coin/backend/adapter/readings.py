"""Module Chuẩn Hóa Dữ Liệu Thị Trường của Adapter (backend/adapter/readings.py).

Đảm nhiệm duy nhất nhiệm vụ Thu nhận & Chuẩn hóa Dữ liệu (Data Ingestion & Normalization):
1. Nhận nến 1m từ sàn (OKX WebSocket / REST / Nautilus Market Data Feed).
2. Kiểm tra tính toàn vẹn (Data Integrity):
   - Loại bỏ nến trùng lặp theo timestamp (de-duplication).
   - Hỗ trợ nến đến muộn / sai thứ tự trong khung ân hạn (Grace Period window).
3. Tự động gom nến và chốt nến Anchor (khung cấu hình anchor_hours) chuẩn mực:
   - Áp dụng cấu hình đa khung thật sự: anchor_ms = anchor_hours * 3600 * 1000.
   - Chống nhìn trước tương lai: chỉ gom khi nến anchor đã hoàn toàn kết thúc theo dòng thời gian stream_now_ts.
   - Quản lý trạng thái nến thiếu (Incomplete Buckets): Trạng thái WAITING_CATCHUP trong khung ân hạn và DISCARDED_INCOMPLETE khi quá hạn.
   - Tự động Recompute Anchor Bar: Khi nến đến muộn (Late Bar) về bổ sung đủ nến hoặc làm thay đổi giá High/Low/Volume của Anchor Bar cũ, nến Anchor đó lập tức được tính toán lại chính xác và cập nhật vào closed_1h_bars.
4. Đa tài sản: Hoàn toàn phi tài sản (Coin perp, CFD, Index) chỉ thao tác trên OHLCV.
5. Trả về cấu trúc MarketBar chuẩn hóa cho bộ tính tín hiệu (signal.py) và bộ thực thi (execution.py).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class MarketBar:
    """Nến thị trường chuẩn hóa được đẩy qua các phân hệ phân tích và thực thi."""
    timestamp: int                          # Millisecond timestamp nến 1m hiện tại
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed_1h_bars: List[Dict[str, float]]  # Danh sách nến Anchor đã đóng hoàn toàn (để tính chỉ báo)
    is_warmed_up: bool                      # Đã đủ nến Anchor để tính chỉ báo tin cậy chưa
    ema: Optional[float] = None             # EMA_K (k=20)
    atr: Optional[float] = None             # ATR(14)
    upper_band: Optional[float] = None      # EMA + F * ATR
    lower_band: Optional[float] = None      # EMA - F * ATR
    k_delta: Optional[float] = None         # 2 * F * ATR
    z_score: float = 0.0                    # (High_1m - Upper) / K_delta
    w_score: float = 0.0                    # (Lower - Low_1m) / K_delta
    breakout_signal: str = "FLAT"           # "LONG", "SHORT", "FLAT"
    regime: str = "RANGE"                   # Bối cảnh thị trường (tham khảo nhẹ: "VOL_EXPANSION", "TREND_UP", "TREND_DOWN", "RANGE")
    regime_context: Dict[str, Any] = field(default_factory=dict)  # Chi tiết: dist_from_ema_atr, atr_pct, strength

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "is_warmed_up": self.is_warmed_up,
            "ema": self.ema,
            "atr": self.atr,
            "upper_band": self.upper_band,
            "lower_band": self.lower_band,
            "k_delta": self.k_delta,
            "z_score": self.z_score,
            "w_score": self.w_score,
            "breakout_signal": self.breakout_signal,
            "regime": self.regime,
            "regime_context": self.regime_context,
            "closed_1h_bars": self.closed_1h_bars,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MarketBar:
        return cls(
            timestamp=int(d.get("timestamp", 0)),
            symbol=str(d.get("symbol", "")),
            open=float(d.get("open", 0.0)),
            high=float(d.get("high", 0.0)),
            low=float(d.get("low", 0.0)),
            close=float(d.get("close", 0.0)),
            volume=float(d.get("volume", 0.0)),
            closed_1h_bars=list(d.get("closed_1h_bars", [])),
            is_warmed_up=bool(d.get("is_warmed_up", False)),
            ema=d.get("ema"),
            atr=d.get("atr"),
            upper_band=d.get("upper_band"),
            lower_band=d.get("lower_band"),
            k_delta=d.get("k_delta"),
            z_score=float(d.get("z_score", 0.0)),
            w_score=float(d.get("w_score", 0.0)),
            breakout_signal=str(d.get("breakout_signal", "FLAT")),
            regime=str(d.get("regime", "RANGE")),
            regime_context=dict(d.get("regime_context", {})),
        )


# Bí danh tương thích ngược
MarketReading = MarketBar


class MarketDataReader:
    """Bộ thu nhận & chuẩn hóa dữ liệu nến độc lập của Adapter."""

    def __init__(
        self,
        symbol: str,
        anchor_hours: int = 1,
        anchor_minutes: Optional[int] = None,
        anchor_tf: Optional[str] = None,
        signal_mode: str = "breakout",       # "breakout" (chuẩn Proxima) hoặc "mean_reversion"
        warmup_required: int = 20,          # Mặc định cần 20 nến Anchor để đảm bảo EMA20 và ATR14
        grace_period_minutes: int = 15,     # Khung ân hạn nến đến muộn (phút)
        k_period: int = 20,                 # Chu kỳ EMA K
        atr_period: int = 14,               # Chu kỳ ATR
        f_multiplier: float = 1.0,          # Hệ số dải Keltner F
        redis_bus: Optional[Any] = None,    # RedisBus để ném MarketReading lên Redis
    ):
        self.symbol = symbol

        # Hỗ trợ đa khung Anchor linh hoạt: 2m, 5m, 15m, 30m, 1h, 2h, 4h
        if anchor_tf:
            tf_s = anchor_tf.lower().strip()
            if tf_s.endswith("m"):
                self.anchor_minutes = max(1, int(tf_s[:-1]))
            elif tf_s.endswith("h"):
                self.anchor_minutes = max(1, int(tf_s[:-1]) * 60)
            elif tf_s.endswith("d"):
                self.anchor_minutes = max(1, int(tf_s[:-1]) * 1440)
            else:
                self.anchor_minutes = 60
        elif anchor_minutes:
            self.anchor_minutes = max(1, anchor_minutes)
        else:
            self.anchor_minutes = max(1, anchor_hours) * 60

        self.anchor_hours = max(1, math.ceil(self.anchor_minutes / 60))
        self.signal_mode = signal_mode if signal_mode in ("breakout", "mean_reversion") else "breakout"

        self.warmup_required = warmup_required
        self.grace_period_ms = grace_period_minutes * 60 * 1000
        self.k_period = k_period
        self.atr_period = atr_period
        self.f_multiplier = f_multiplier
        self.redis_bus = redis_bus

        # Bộ đệm nến 1m thô và tập timestamp đã nhận để de-duplicate
        self._1m_bars: List[Dict[str, float]] = []
        self._seen_1m_ts: Set[int] = set()
        self._last_1m_ts: int = 0           # Mốc thời gian cao nhất của dòng dữ liệu (stream leading edge)

        # Bộ đệm nến chạy (running 1m bar) cho luồng tick / event 1s
        self._running_bar: Optional[Dict[str, float]] = None

        # Danh sách nến Anchor đã đóng hoàn toàn
        self.closed_1h_bars: List[Dict[str, float]] = []
        self._last_anchor_ts: int = 0

        # Quản lý bucket thiếu dữ liệu
        self.incomplete_buckets: Dict[int, Dict[str, Any]] = {}

        # Cache chỉ báo
        self._cached_ema: Optional[float] = None
        self._cached_atr: Optional[float] = None

    @property
    def is_warmed_up(self) -> bool:
        """Đã đủ số nến Anchor đóng để tính toán chỉ báo tin cậy?"""
        return len(self.closed_1h_bars) >= self.warmup_required

    def _compute_indicators(self) -> None:
        """Tính toán EMA_K và ATR(14) từ closed_1h_bars."""
        if not self.is_warmed_up:
            self._cached_ema = None
            self._cached_atr = None
            return

        alpha_ema = 2.0 / (self.k_period + 1.0)
        ema = self.closed_1h_bars[0]["close"]
        for b in self.closed_1h_bars[1:]:
            ema = (b["close"] * alpha_ema) + (ema * (1.0 - alpha_ema))
        self._cached_ema = ema

        trs = []
        for idx, b in enumerate(self.closed_1h_bars):
            if idx == 0:
                trs.append(b["high"] - b["low"])
            else:
                prev_c = self.closed_1h_bars[idx - 1]["close"]
                trs.append(max(b["high"] - b["low"], abs(b["high"] - prev_c), abs(b["low"] - prev_c)))

        if len(trs) >= self.atr_period:
            atr = sum(trs[:self.atr_period]) / self.atr_period
            for tr in trs[self.atr_period:]:
                atr = (atr * (self.atr_period - 1) + tr) / self.atr_period
            self._cached_atr = atr
        else:
            self._cached_atr = None

    def feed_1m_bar(self, bar: Dict[str, float]) -> Optional[MarketReading]:
        """Nạp một nến 1m mới vào bộ đọc và sinh MarketReading chuẩn hóa.

        bar yêu cầu: {"timestamp": ms, "open": float, "high": float, "low": float, "close": float, "volume": float}
        """
        ts = int(bar.get("timestamp") or bar.get("open_time") or bar.get("time") or 0)
        bar["timestamp"] = ts

        # 1. Loại bỏ nến trùng lặp hoàn toàn
        if ts in self._seen_1m_ts:
            return None

        # 2. Xử lý nến đến muộn / sai thứ tự so với stream leading edge
        if self._last_1m_ts > 0 and ts < self._last_1m_ts:
            # Nếu nến đến muộn vượt quá thời gian ân hạn -> từ chối để tránh hồi quy trạng thái
            if (self._last_1m_ts - ts) > self.grace_period_ms:
                return None
            # Nằm trong grace period -> chèn đúng thứ tự thời gian
            self._seen_1m_ts.add(ts)
            timestamps = [int(b["timestamp"]) for b in self._1m_bars]
            idx = bisect.bisect_right(timestamps, ts)
            self._1m_bars.insert(idx, bar)

            # Tự động Recompute Anchor Bucket chứa nến muộn này
            self._recompute_bucket_for_late_bar(ts)
            self._compute_indicators()
        else:
            self._seen_1m_ts.add(ts)
            self._last_1m_ts = ts
            self._1m_bars.append(bar)

            # Kiểm tra chốt các nến Anchor mới theo mốc thời gian dẫn đầu
            prev_len = len(self.closed_1h_bars)
            self._check_and_aggregate_closed_anchors(self._last_1m_ts)
            if len(self.closed_1h_bars) != prev_len:
                self._compute_indicators()

        high_1m = float(bar["high"])
        low_1m = float(bar["low"])

        ema = self._cached_ema
        atr = self._cached_atr
        upper = None
        lower = None
        k_delta = None
        z_score = 0.0
        w_score = 0.0
        signal = "FLAT"

        regime = "RANGE"
        regime_ctx: Dict[str, Any] = {}

        if ema is not None and atr is not None and atr > 0:
            k_half = self.f_multiplier * atr
            k_delta = 2.0 * k_half
            upper = ema + k_half
            lower = ema - k_half
            if k_delta > 1e-8:
                z_score = (high_1m - upper) / k_delta
                w_score = (lower - low_1m) / k_delta
                if self.signal_mode == "mean_reversion":
                    # Kịch bản Mean Reversion: Quá mua -> Đánh Short, Quá bán -> Đánh Long
                    if z_score > self.f_multiplier:
                        signal = "SHORT"
                    elif w_score > self.f_multiplier:
                        signal = "LONG"
                else:
                    # Kịch bản Breakout chuẩn Proxima gốc: Xuyên phá dải trên -> Long, xuyên phá dải dưới -> Short
                    if z_score > self.f_multiplier:
                        signal = "LONG"
                    elif w_score > self.f_multiplier:
                        signal = "SHORT"

            regime_ctx = self.detect_regime(float(bar["close"]))
            regime = regime_ctx.get("regime", "RANGE")

        reading = MarketReading(
            timestamp=ts,
            symbol=self.symbol,
            open=float(bar["open"]),
            high=high_1m,
            low=low_1m,
            close=float(bar["close"]),
            volume=float(bar.get("volume", 0.0)),
            closed_1h_bars=list(self.closed_1h_bars),
            is_warmed_up=self.is_warmed_up,
            ema=ema,
            atr=atr,
            upper_band=upper,
            lower_band=lower,
            k_delta=k_delta,
            z_score=z_score,
            w_score=w_score,
            breakout_signal=signal,
            regime=regime,
            regime_context=regime_ctx,
        )

        # Bắn lên Redis nếu có cấu hình RedisBus
        if self.redis_bus:
            try:
                self.redis_bus.publish_market_reading(self.symbol, reading.to_dict())
            except Exception as e:
                pass

        return reading

    def detect_regime(self, current_1m_close: float) -> Dict[str, Any]:
        """Phân loại bối cảnh thị trường nhẹ nhàng để tham khảo ở Bước 1."""
        if not self._cached_ema or not self._cached_atr or self._cached_atr <= 0:
            return {"regime": "RANGE", "strength": 0.0, "dist_from_ema_atr": 0.0, "atr_pct": 0.0}

        dist_from_ema = (current_1m_close - self._cached_ema) / self._cached_atr
        atr_pct = (self._cached_atr / self._cached_ema) * 100.0

        if atr_pct > 2.0:
            regime = "VOL_EXPANSION"
        elif dist_from_ema > 0.8:
            regime = "TREND_UP"
        elif dist_from_ema < -0.8:
            regime = "TREND_DOWN"
        else:
            regime = "RANGE"

        return {
            "regime": regime,
            "dist_from_ema_atr": round(dist_from_ema, 3),
            "atr_pct": round(atr_pct, 3),
            "strength": round(abs(dist_from_ema), 2),
        }

    def _recompute_bucket_for_late_bar(self, ts: int) -> None:
        """Tính toán lại chính xác nến Anchor khi nhận được nến đến muộn (Late Bar)."""
        anchor_ms = self.anchor_minutes * 60 * 1000
        expected_minutes = self.anchor_minutes
        min_required_minutes = max(1, int(expected_minutes * 0.90))

        target_start = (ts // anchor_ms) * anchor_ms
        target_end = target_start + anchor_ms

        # Lấy toàn bộ nến 1m trong bucket này (đã bao gồm nến muộn vừa chèn)
        bucket_bars = [
            b for b in self._1m_bars
            if target_start <= int(b["timestamp"]) < target_end
        ]
        unique_minutes = len(set(int(b["timestamp"]) // 60000 for b in bucket_bars))

        if unique_minutes >= min_required_minutes:
            bucket_bars.sort(key=lambda x: int(x["timestamp"]))
            recomputed_anchor = {
                "timestamp": target_start,
                "open": bucket_bars[0]["open"],
                "high": max(b["high"] for b in bucket_bars),
                "low": min(b["low"] for b in bucket_bars),
                "close": bucket_bars[-1]["close"],
                "volume": sum(b.get("volume", 0.0) for b in bucket_bars),
            }

            # 1. Nếu bucket trước đây từng bị đánh dấu INCOMPLETE -> xóa bỏ trạng thái thiếu
            if target_start in self.incomplete_buckets:
                del self.incomplete_buckets[target_start]

            # 2. Tìm và cập nhật lại nến trong closed_1h_bars
            found = False
            for i, existing in enumerate(self.closed_1h_bars):
                if existing["timestamp"] == target_start:
                    self.closed_1h_bars[i] = recomputed_anchor
                    found = True
                    break

            # Nếu chưa có (trước đó bị thiếu nến nên chưa được tạo) -> chèn vào đúng vị trí theo timestamp
            if not found:
                idx = bisect.bisect_right([b["timestamp"] for b in self.closed_1h_bars], target_start)
                self.closed_1h_bars.insert(idx, recomputed_anchor)

    def _check_and_aggregate_closed_anchors(self, stream_now_ts: int) -> None:
        """Gom nến theo đúng khung cấu hình anchor_minutes và quản lý bucket thiếu."""
        anchor_ms = self.anchor_minutes * 60 * 1000
        expected_minutes = self.anchor_minutes
        min_required_minutes = max(1, int(expected_minutes * 0.90))

        if self._last_anchor_ts == 0 and self._1m_bars:
            first_ts = int(self._1m_bars[0]["timestamp"])
            self._last_anchor_ts = (first_ts // anchor_ms) * anchor_ms

        while True:
            target_start = self._last_anchor_ts
            target_end = target_start + anchor_ms

            # Nếu khung anchor này chưa kết thúc tại thời điểm stream_now_ts hiện tại -> dừng
            if stream_now_ts < target_end:
                break

            # Lấy tất cả các nến 1m thuộc khung này
            bucket_bars = [
                b for b in self._1m_bars
                if target_start <= int(b["timestamp"]) < target_end
            ]
            unique_minutes = len(set(int(b["timestamp"]) // 60000 for b in bucket_bars))

            if unique_minutes >= min_required_minutes:
                # Đủ điều kiện toàn vẹn dữ liệu -> chốt nến Anchor
                bucket_bars.sort(key=lambda x: int(x["timestamp"]))
                agg_bar = {
                    "timestamp": target_start,
                    "open": bucket_bars[0]["open"],
                    "high": max(b["high"] for b in bucket_bars),
                    "low": min(b["low"] for b in bucket_bars),
                    "close": bucket_bars[-1]["close"],
                    "volume": sum(b.get("volume", 0.0) for b in bucket_bars),
                }
                # Xóa khỏi incomplete nếu có
                if target_start in self.incomplete_buckets:
                    del self.incomplete_buckets[target_start]

                if not any(b["timestamp"] == target_start for b in self.closed_1h_bars):
                    self.closed_1h_bars.append(agg_bar)
                self._last_anchor_ts += anchor_ms
            else:
                # Chưa đủ nến: Kiểm tra xem còn trong thời gian ân hạn (grace period) không
                if stream_now_ts < target_end + self.grace_period_ms:
                    # Đang trong thời gian ân hạn chờ nến đến bù -> không vội bỏ qua bucket
                    self.incomplete_buckets[target_start] = {
                        "status": "WAITING_CATCHUP",
                        "unique_minutes": unique_minutes,
                        "expected": expected_minutes,
                    }
                    break
                else:
                    # Đã hết thời gian ân hạn mà vẫn thiếu -> ghi nhận INCOMPLETE và bỏ qua
                    self.incomplete_buckets[target_start] = {
                        "status": "DISCARDED_INCOMPLETE",
                        "unique_minutes": unique_minutes,
                        "expected": expected_minutes,
                    }
                    self._last_anchor_ts += anchor_ms

        # Dọn dẹp bộ nhớ: Giữ lại nến 1m trong 48 anchor cycles gần nhất (dọn định kỳ theo lô)
        if len(self._1m_bars) > 4000:
            keep_threshold = stream_now_ts - (48 * anchor_ms)
            self._1m_bars = [b for b in self._1m_bars if int(b["timestamp"]) >= keep_threshold]
            self._seen_1m_ts = {int(b["timestamp"]) for b in self._1m_bars}

    def feed_tick(
        self,
        price: float,
        size: float = 0.0,
        timestamp_ms: Optional[int] = None,
    ) -> Optional[MarketReading]:
        """Nạp tick giá thời gian thực (1s event / tick stream).

        Cập nhật running 1m bar và tính toán breach tức thời:
        1s tick/event -> running 1m High/Low -> signal at t -> fill at t+1s.
        """
        ts = int(timestamp_ms or (time.time() * 1000))
        minute_ts = (ts // 60000) * 60000

        # Nếu bước sang phút mới -> chốt nến phút trước và đưa vào pipeline
        if self._running_bar and minute_ts > int(self._running_bar["timestamp"]):
            self.feed_1m_bar(self._running_bar)
            self._running_bar = None

        if self._running_bar is None:
            self._running_bar = {
                "timestamp": minute_ts,
                "open": float(price),
                "high": float(price),
                "low": float(price),
                "close": float(price),
                "volume": float(size),
            }
        else:
            self._running_bar["high"] = max(float(self._running_bar["high"]), float(price))
            self._running_bar["low"] = min(float(self._running_bar["low"]), float(price))
            self._running_bar["close"] = float(price)
            self._running_bar["volume"] = float(self._running_bar["volume"]) + float(size)

        # Đánh giá tín hiệu trực tiếp trên running 1m bar
        high_1m = float(self._running_bar["high"])
        low_1m = float(self._running_bar["low"])
        ema = self._cached_ema
        atr = self._cached_atr
        upper = None
        lower = None
        k_delta = None
        z_score = 0.0
        w_score = 0.0
        signal = "FLAT"

        regime = "RANGE"
        regime_ctx: Dict[str, Any] = {}

        if ema is not None and atr is not None and atr > 0:
            k_half = self.f_multiplier * atr
            k_delta = 2.0 * k_half
            upper = ema + k_half
            lower = ema - k_half
            if k_delta > 1e-8:
                z_score = (high_1m - upper) / k_delta
                w_score = (lower - low_1m) / k_delta
                if self.signal_mode == "mean_reversion":
                    if z_score > self.f_multiplier:
                        signal = "SHORT"
                    elif w_score > self.f_multiplier:
                        signal = "LONG"
                else:
                    if z_score > self.f_multiplier:
                        signal = "LONG"
                    elif w_score > self.f_multiplier:
                        signal = "SHORT"

            regime_ctx = self.detect_regime(float(price))
            regime = regime_ctx.get("regime", "RANGE")

        reading = MarketReading(
            timestamp=ts,
            symbol=self.symbol,
            open=float(self._running_bar["open"]),
            high=high_1m,
            low=low_1m,
            close=float(price),
            volume=float(self._running_bar["volume"]),
            closed_1h_bars=list(self.closed_1h_bars),
            is_warmed_up=self.is_warmed_up,
            ema=ema,
            atr=atr,
            upper_band=upper,
            lower_band=lower,
            k_delta=k_delta,
            z_score=z_score,
            w_score=w_score,
            breakout_signal=signal,
            regime=regime,
            regime_context=regime_ctx,
        )

        if self.redis_bus:
            try:
                self.redis_bus.publish_market_reading(self.symbol, reading.to_dict())
            except Exception:
                pass

        return reading
