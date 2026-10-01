"""Data Quality Gate Module
Validates asset tick and candle data integrity, checks for missing bars, duplicate timestamps,
extreme outliers, and zero-volume periods.
Outputs Data Quality Score (0-100) and Gate Status (APPROVED, WARNING, BLOCKED, NEEDS_MORE_DATA).
"""
import copy
import os
import time
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

try:
    from backend.db.tick_storage import load_ticks_df, load_candle_df, default_data_root, symbol_dir
except ImportError:
    from nora.backend.db.tick_storage import load_ticks_df, load_candle_df, default_data_root, symbol_dir


# Tỉ lệ phút không có giao dịch tối đa cho phép. Engine KHÔNG khớp lệnh trên nến điền
# (chờ phút có giao dịch thật), nên nến điền không tạo lệnh ảo; ngưỡng này chỉ loại
# các pool quá thưa. Đo thực tế: AERO/USDC (Base, ~$30M thanh khoản) = 43%.
MAX_FILLED_RATIO_1M = 0.60


class DataQualityStatus:
    APPROVED = "APPROVED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


# Cache kết quả gate trong process. Khoá gồm (mtime_ns, size) của MỌI file trong thư mục
# tài sản -> bất kỳ file nào đổi (crawl lại, sửa pkl, manifest) thì cache tự hết hạn.
# Gate trên 3 năm dữ liệu 1m mất ~11s (sha256 + resample 1,58 triệu nến), cache tránh lặp lại
# ở mỗi lần backtest/WFA.
_GATE_CACHE: Dict[tuple, Dict[str, Any]] = {}
_GATE_CACHE_MAX = 256


def _gate_cache_key(symbol: str, timeframe: str, data_root: Optional[str]) -> Optional[tuple]:
    s_dir = symbol_dir(symbol, data_root)
    if not os.path.isdir(s_dir):
        return None
    files = []
    for name in sorted(os.listdir(s_dir)):
        path = os.path.join(s_dir, name)
        if os.path.isfile(path):
            st = os.stat(path)
            files.append((name, st.st_mtime_ns, st.st_size))
    return (os.path.abspath(s_dir), timeframe, tuple(files))


def evaluate_data_quality(
    symbol: str,
    timeframe: str = "1h",
    df_candles: Optional[pd.DataFrame] = None,
    df_ticks: Optional[pd.DataFrame] = None,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Quality gate (có cache khi chỉ đọc từ đĩa, xem _GATE_CACHE)."""
    if df_candles is not None or df_ticks is not None:
        return _evaluate_data_quality_uncached(symbol, timeframe, df_candles, df_ticks, data_root)
    key = _gate_cache_key(symbol, timeframe, data_root)
    if key is not None and key in _GATE_CACHE:
        return copy.deepcopy(_GATE_CACHE[key])
    result = _evaluate_data_quality_uncached(symbol, timeframe, None, None, data_root)
    if key is not None:
        if len(_GATE_CACHE) >= _GATE_CACHE_MAX:
            _GATE_CACHE.clear()
        _GATE_CACHE[key] = copy.deepcopy(result)
    return result


def _evaluate_data_quality_uncached(
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

    verified_warnings: List[str] = []  # cảnh báo không chặn, gộp vào kết quả cuối

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

    # 1. crawl_ok check
    if manifest.get("crawl_ok") is False:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Quá trình crawl dữ liệu của {symbol} bị lỗi (crawl_ok=False)"],
            "metrics": {"total_bars": 0, "total_ticks": 0},
        }

    # 2. coverage_days check (tối thiểu 30 ngày)
    coverage_days = float(manifest.get("coverage_days", 0.0))
    if coverage_days <= 0.0 and manifest.get("start_ts") and manifest.get("end_ts"):
        coverage_days = (manifest["end_ts"] - manifest["start_ts"]) / 86_400_000.0
    if coverage_days < 30.0:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.NEEDS_MORE_DATA,
            "quality_score": 30.0,
            "issues": [f"Chặn chạy: Thời gian dữ liệu của {symbol} ({coverage_days:.1f} ngày) chưa đủ ngưỡng tối thiểu 30 ngày (NEEDS_MORE_DATA)"],
            "metrics": {"coverage_days": coverage_days},
        }

    # 3. Kiểm tra nến 1m
    df_1m = load_candle_df(symbol, "1m", data_root)
    if df_1m is None or df_1m.empty:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Có manifest nhưng thiếu nến 1m của {symbol}"],
            "metrics": {"total_bars": 0},
        }

    # 4. sha256 1m integrity check
    manifest_sha = manifest.get("sha256_1m")
    if manifest_sha:
        try:
            from backend.core.resampler import compute_df_sha256
        except ImportError:
            from nora.backend.core.resampler import compute_df_sha256
        actual_sha = compute_df_sha256(df_1m)
        if actual_sha != manifest_sha:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: sha256 không khớp giữa 1m.pkl và manifest.json của {symbol}"],
                "metrics": {"manifest_sha": manifest_sha, "actual_sha": actual_sha},
            }

    # 5. Không có timestamp trùng lặp trong 1m
    if df_1m["open_time"].duplicated().any():
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 0.0,
            "issues": [f"Chặn chạy: Phát hiện timestamp trùng lặp trong nến 1m của {symbol}"],
            "metrics": {"total_bars": len(df_1m)},
        }

    # 6. Tỉ lệ nến điền (filled_ratio) không vượt ngưỡng MAX_FILLED_RATIO_1M
    filled_ratio = float(manifest.get("filled_ratio_1m", 0.0))
    if "is_filled" in df_1m.columns:
        filled_ratio = float((df_1m["is_filled"] == 1).mean())
    if filled_ratio > MAX_FILLED_RATIO_1M:
        return {
            "symbol": symbol,
            "status": DataQualityStatus.BLOCKED,
            "quality_score": 10.0,
            "issues": [f"Chặn chạy: Tỉ lệ nến điền (filled_ratio={filled_ratio*100:.1f}%) vượt ngưỡng {MAX_FILLED_RATIO_1M*100:.0f}%"],
            "metrics": {"filled_ratio": filled_ratio},
        }

    # 7. Bước nhảy giá > 50% trong 1 phút.
    #    - Dữ liệu CEX chính thức đã kiểm checksum (vd. Binance data.binance.vision): đây là
    #      sự kiện thị trường THẬT (vd. cú sập thanh lý 2025-10-10) -> WARNING + liệt kê thời điểm,
    #      KHÔNG chặn (loại sự kiện rủi ro thật khỏi backtest làm Monte Carlo lạc quan sai).
    #    - Nguồn khác (DEX / chưa kiểm chứng): có thể là lỗi dữ liệu -> chặn.
    pct_1m = df_1m["close"].pct_change().abs()
    jump_mask = pct_1m > 0.50
    if jump_mask.any():
        verified_cex = str(manifest.get("venue", "")).lower() == "cex" and manifest.get("checksums_verified") is True
        if not verified_cex:
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 10.0,
                "issues": [f"Chặn chạy: Phát hiện bước nhảy giá bất thường > 50% trong 1 phút"],
                "metrics": {"max_1m_jump": float(pct_1m.max())},
            }
        jump_times = pd.to_datetime(df_1m.loc[jump_mask, "open_time"], unit="ms", utc=True)
        extreme_moves = [f"{t:%Y-%m-%d %H:%M}Z" for t in jump_times]
        verified_warnings.append(
            f"Cảnh báo: {len(extreme_moves)} phút có biến động > 50% (dữ liệu CEX đã kiểm checksum, "
            f"giữ lại như sự kiện thật): {', '.join(extreme_moves[:5])}{' …' if len(extreme_moves) > 5 else ''}"
        )

    # 8. So resample: mọi khung đang có (bắt buộc 4h), O/H/L/C sai số tương đối < 1e-9, volume < 1e-6
    try:
        from backend.core.resampler import resample_from_1m
    except ImportError:
        from nora.backend.core.resampler import resample_from_1m

    for check_tf in ["4h", "15m", "1h", "5m"]:
        df_stored = load_candle_df(symbol, check_tf, data_root)
        if check_tf == "4h" and (df_stored is None or df_stored.empty):
            # Engine Studio/WFA dùng 1m + 4h -> thiếu 4h là không chạy được, phải chặn
            return {
                "symbol": symbol,
                "status": DataQualityStatus.BLOCKED,
                "quality_score": 0.0,
                "issues": [f"Chặn chạy: {symbol} thiếu nến 4h (bắt buộc cho engine 1m + 4h)"],
                "metrics": {"total_bars": len(df_1m)},
            }
        if df_stored is not None and not df_stored.empty:
            resampled = resample_from_1m(df_1m, check_tf)
            merged_check = pd.merge(resampled, df_stored, on="open_time", suffixes=("_resampled", "_stored"))
            if merged_check.empty or len(merged_check) != len(df_stored):
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Timestamps giữa 1m resample và {check_tf} lưu trữ không khớp"],
                    "metrics": {"resampled_bars": len(resampled), "stored_bars": len(df_stored)},
                }
            for c in ["open", "high", "low", "close"]:
                rel_err = ((merged_check[f"{c}_resampled"] - merged_check[f"{c}_stored"]).abs() / merged_check[f"{c}_stored"].abs().clip(lower=1e-300)).max()
                if rel_err > 1e-9:
                    return {
                        "symbol": symbol,
                        "status": DataQualityStatus.BLOCKED,
                        "quality_score": 0.0,
                        "issues": [f"Chặn chạy: Resample 1m sang {check_tf} lệch cột {c} (sai số tương đối: {rel_err:.6e} > 1e-9)"],
                        "metrics": {f"rel_diff_{check_tf}_{c}": float(rel_err)},
                    }
            vol_diff = (merged_check["volume_resampled"] - merged_check["volume_stored"]).abs().max()
            if vol_diff > 1e-6:
                return {
                    "symbol": symbol,
                    "status": DataQualityStatus.BLOCKED,
                    "quality_score": 0.0,
                    "issues": [f"Chặn chạy: Resample 1m sang {check_tf} lệch volume (max diff: {vol_diff:.6e} > 1e-6)"],
                    "metrics": {f"diff_{check_tf}_vol": float(vol_diff)},
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

    if verified_warnings:
        issues = list(issues) + verified_warnings
        if status == DataQualityStatus.APPROVED:
            status = DataQualityStatus.WARNING

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
