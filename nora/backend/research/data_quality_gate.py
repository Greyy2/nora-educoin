"""Data Quality Gate Module
Validates asset tick and candle data integrity, checks for missing bars, duplicate timestamps,
extreme outliers, and zero-volume periods.
Outputs Data Quality Score (0-100) and Gate Status (APPROVED, WARNING, BLOCKED, NEEDS_MORE_DATA).
"""
import os
import time
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

try:
    from backend.db.tick_storage import load_ticks_df, load_candle_df, default_data_root, symbol_dir
except ImportError:
    from nora.backend.db.tick_storage import load_ticks_df, load_candle_df, default_data_root, symbol_dir


class DataQualityStatus:
    APPROVED = "APPROVED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


def evaluate_data_quality(
    symbol: str,
    timeframe: str = "1h",
    df_candles: Optional[pd.DataFrame] = None,
    df_ticks: Optional[pd.DataFrame] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates data quality for a given asset.
    Returns:
        status: APPROVED | WARNING | BLOCKED | NEEDS_MORE_DATA
        quality_score: 0.0 - 100.0
        issues: list of issue descriptions
        metrics: detailed breakdown metrics
    """
    s_dir = symbol_dir(symbol, data_root)
    if not os.path.isdir(s_dir):
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Thư mục dữ liệu {symbol} không tồn tại"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    # Phase 1 Gate Check: manifest.json phải tồn tại và synthetic == False
    import json
    manifest_path = os.path.join(s_dir, "manifest.json")
    manifest = None
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = None

    if manifest is None:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: {symbol} thiếu manifest.json kiểm định nguồn gốc dữ liệu"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    if manifest.get("synthetic", True) is True:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: {symbol} được đánh dấu dữ liệu nhân tạo (synthetic=true)"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    # Kiểm tra nến 1m và tính nhất quán với các khung khác
    df_1m = load_candle_df(symbol, "1m", data_root)
    df_15m = load_candle_df(symbol, "15m", data_root)
    if df_1m is not None and not df_1m.empty:
        # 1. Không có timestamp trùng lặp
        if df_1m["open_time"].duplicated().any():
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: Phát hiện timestamp trùng lặp trong nến 1m của {symbol}"],
                "metrics": {"total_bars": len(df_1m)},
            }

        # 2. Tỉ lệ nến điền (filled_ratio) không vượt ngưỡng 30%
        filled_ratio = float(manifest.get("filled_ratio_1m", 0.0))
        if "is_filled" in df_1m.columns:
            filled_ratio = float((df_1m["is_filled"] == 1).mean())
        if filled_ratio > 0.30:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 10.0,
                "issues": [f"Chặn chạy: Tỉ lệ nến điền (filled_ratio={filled_ratio*100:.1f}%) vượt ngưỡng 30%"],
                "metrics": {"filled_ratio": filled_ratio},
            }

        # 3. Không có bước nhảy giá bất thường trong 1 phút > 50%
        pct_1m = df_1m["close"].pct_change().abs()
        if (pct_1m > 0.50).any():
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 10.0,
                "issues": [f"Chặn chạy: Phát hiện bước nhảy giá bất thường > 50% trong 1 phút"],
                "metrics": {"max_1m_jump": float(pct_1m.max())},
            }

        # 4. Resample 1m -> 15m phải khớp với 15m đang lưu (sai số < 1e-6)
        if df_15m is not None and not df_15m.empty:
            try:
                from backend.core.resampler import resample_from_1m
            except ImportError:
                from nora.backend.core.resampler import resample_from_1m
            resampled_15m = resample_from_1m(df_1m, "15m")
            merged_check = pd.merge(resampled_15m, df_15m, on="open_time", suffixes=("_resampled", "_stored"))
            if merged_check.empty or len(merged_check) != len(df_15m):
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Timestamps giữa 1m resample và 15m lưu trữ không khớp"],
                    "metrics": {"resampled_bars": len(resampled_15m), "stored_bars": len(df_15m)},
                }
            max_diff = (merged_check["close_resampled"] - merged_check["close_stored"]).abs().max()
            if max_diff > 1e-6:
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Resample 1m sang 15m lệch với 15m lưu trữ (max diff: {max_diff:.6e})"],
                    "metrics": {"max_diff_15m": float(max_diff)},
                }

    # Load candles if not provided
    if df_candles is None or df_candles.empty:
        df_candles = load_candle_df(symbol, timeframe, data_root)
    
    # Load ticks if not provided
    if df_ticks is None or df_ticks.empty:
        df_ticks = load_ticks_df(symbol, data_root)

    total_ticks = len(df_ticks) if df_ticks is not None else 0
    total_bars = len(df_candles) if df_candles is not None else 0

    issues: List[str] = []
    penalties: float = 0.0

    # 1. Check sample size
    if total_bars < 30 and total_ticks < 100:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 35.0,
            "issues": ["Dữ liệu quá mỏng (dưới 30 nến / 100 ticks), chưa đủ để kết luận định lượng"],
            "metrics": {
                "total_bars": total_bars,
                "total_ticks": total_ticks,
                "time_span_days": 0.0,
            },
        }

    # 2. Analyze Candle Structure
    zero_vol_pct = 0.0
    max_gap_hours = 0.0
    time_span_days = 0.0
    outlier_count = 0
    noise_ratio = 0.0

    if total_bars > 0 and "close" in df_candles.columns:
        # Time span calculation
        t_min = df_candles["open_time"].min()
        t_max = df_candles["open_time"].max()
        time_span_days = max(0.01, (t_max - t_min) / (1000 * 86400))

        # Check zero / flat volume
        if "volume" in df_candles.columns:
            zero_vol_count = (df_candles["volume"] <= 0).sum()
            zero_vol_pct = float(zero_vol_count / total_bars * 100.0)
            if zero_vol_pct > 30.0:
                penalties += min(30.0, zero_vol_pct * 0.6)
                issues.append(f"Tỷ lệ nến rỗng (volume = 0) cao: {zero_vol_pct:.1f}%")

        # Check timestamp continuity / gaps
        diffs = df_candles["open_time"].diff().dropna()
        if not diffs.empty:
            expected_step = diffs.median()
            large_gaps = diffs[diffs > expected_step * 3]
            if len(large_gaps) > 0:
                max_gap_hours = float(diffs.max() / (1000 * 3600))
                penalties += min(25.0, len(large_gaps) * 4.0)
                issues.append(f"Phát hiện {len(large_gaps)} khoảng trống dữ liệu (gap lớn nhất: {max_gap_hours:.1f} giờ)")

        # Check price anomalies / extreme outliers
        returns = df_candles["close"].pct_change().dropna()
        if not returns.empty:
            std_ret = returns.std()
            if std_ret > 0:
                extreme_jumps = returns[returns.abs() > 0.50]  # > 50% in single bar
                outlier_count = len(extreme_jumps)
                if outlier_count > 0:
                    penalties += min(30.0, outlier_count * 8.0)
                    issues.append(f"Có {outlier_count} biến động giá đột biến bất thường (>50% trong 1 bar)")

            # High noise estimation: Parkinson volatility vs return volatility
            high_low_ratio = (df_candles["high"] / (df_candles["low"] + 1e-9) - 1.0).mean()
            abs_ret_mean = returns.abs().mean()
            if abs_ret_mean > 0:
                noise_ratio = float(high_low_ratio / (abs_ret_mean + 1e-9))
                if noise_ratio > 3.5:
                    penalties += 10.0
                    issues.append("Độ nhiễu bóng nến (high-low spread) lớn so với bước giá thực")

    # 3. Analyze Tick Density & Microstructure (Tick-Native)
    inter_trade_median_sec = 0.0
    inter_trade_p95_sec = 0.0
    trades_per_day = 0.0
    dup_timestamp_rate = 0.0
    dup_tx_rate = 0.0
    estimated_slippage_pct = 0.15  # baseline 0.15%
    buy_sell_imbalance = 0.0

    if total_ticks > 0 and df_ticks is not None and not df_ticks.empty:
        if time_span_days <= 0.0 and "timestamp_ms" in df_ticks.columns:
            t_min = df_ticks["timestamp_ms"].min()
            t_max = df_ticks["timestamp_ms"].max()
            time_span_days = max(0.01, (t_max - t_min) / (1000 * 86400))

        trades_per_day = float(total_ticks / max(0.01, time_span_days))

        # Inter-trade intervals
        if "timestamp_ms" in df_ticks.columns:
            sorted_ts = df_ticks["timestamp_ms"].sort_values().values
            diff_sec = np.diff(sorted_ts) / 1000.0
            if len(diff_sec) > 0:
                inter_trade_median_sec = float(np.median(diff_sec))
                inter_trade_p95_sec = float(np.percentile(diff_sec, 95))

                if inter_trade_p95_sec > 7200:  # > 2h gap
                    penalties += min(20.0, (inter_trade_p95_sec / 3600) * 2.0)
                    issues.append(f"Khoảng cách giữa các lệnh giao dịch lớn (p95: {inter_trade_p95_sec / 60:.1f} phút)")

            # Check duplicates
            dup_ts_count = int(pd.Series(sorted_ts).duplicated().sum())
            dup_timestamp_rate = float(dup_ts_count / total_ticks)

        if "tx_hash" in df_ticks.columns:
            dup_tx_count = int(df_ticks["tx_hash"].duplicated().sum())
            dup_tx_rate = float(dup_tx_count / total_ticks)

        # Slippage estimation based on trade activity and trade sizes
        if "volume_usd" in df_ticks.columns:
            med_vol = float(df_ticks["volume_usd"].median())
            if med_vol < 20.0:
                estimated_slippage_pct = 0.75
                penalties += 12.0
                issues.append("Kích thước lệnh giao dịch USD trung bình thấp (< $20), pool có thanh khoản mỏng")
            elif med_vol < 100.0:
                estimated_slippage_pct = 0.40
            else:
                estimated_slippage_pct = 0.20

        # Buy / Sell imbalance
        if "side" in df_ticks.columns:
            buys = float(np.sum(df_ticks["side"] == 1))
            sells = float(np.sum(df_ticks["side"] == -1))
            buy_sell_imbalance = float(abs(buys - sells) / max(1.0, buys + sells))
            if buy_sell_imbalance > 0.65:
                penalties += 10.0
                issues.append(f"Mất cân bằng chiều giao dịch mua/bán on-chain cao ({buy_sell_imbalance * 100:.1f}%)")

        if total_ticks < 100:
            penalties += 25.0
            issues.append("Số lượng tick giao dịch quá mỏng (< 100 trades), trượt giá thực tế sẽ rất cao")

    # Sample check for status
    if total_ticks < 50 and total_bars < 20:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 30.0,
            "issues": ["Dữ liệu quá mỏng (dưới 50 ticks), cần thu thập thêm lịch sử on-chain"],
            "metrics": {
                "total_bars": int(total_bars),
                "total_ticks": int(total_ticks),
                "time_span_days": round(time_span_days, 1),
                "zero_volume_pct": round(zero_vol_pct, 1),
                "max_gap_hours": round(max_gap_hours, 1),
                "outlier_count": int(outlier_count),
                "noise_ratio": round(noise_ratio, 2),
                "inter_trade_median_sec": round(inter_trade_median_sec, 1),
                "inter_trade_p95_sec": round(inter_trade_p95_sec, 1),
                "trades_per_day": round(trades_per_day, 1),
                "estimated_slippage_pct": round(estimated_slippage_pct, 3),
            },
        }

    # Calculate final quality score
    base_score = 100.0 - penalties
    quality_score = max(5.0, min(100.0, base_score))

    # Determine status
    if quality_score >= 75.0 and len(issues) <= 1:
        status = DataQualityStatus.APPROVED
    elif quality_score >= 50.0:
        status = DataQualityStatus.WARNING
    else:
        status = DataQualityStatus.BLOCKED

    return {
        "symbol": symbol,
        "status": status,
        "quality_score": round(quality_score, 1),
        "issues": issues if issues else ["Dữ liệu liên tục, sạch và đạt chuẩn kiểm định"],
        "metrics": {
            "total_bars": int(total_bars),
            "total_ticks": int(total_ticks),
            "time_span_days": round(time_span_days, 1),
            "zero_volume_pct": round(zero_vol_pct, 1),
            "max_gap_hours": round(max_gap_hours, 1),
            "outlier_count": int(outlier_count),
            "noise_ratio": round(noise_ratio, 2),
            "inter_trade_median_sec": round(inter_trade_median_sec, 1),
            "inter_trade_p95_sec": round(inter_trade_p95_sec, 1),
            "trades_per_day": round(trades_per_day, 1),
            "estimated_slippage_pct": round(estimated_slippage_pct, 3),
            "dup_timestamp_rate": round(dup_timestamp_rate, 4),
            "buy_sell_imbalance": round(buy_sell_imbalance, 3),
        },
    }
