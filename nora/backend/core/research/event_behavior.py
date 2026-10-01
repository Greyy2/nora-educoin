"""Event behavior analytics for DEX market research.

This module turns raw DEX ticks/candles and DC legs into descriptive behavior
metrics. It deliberately avoids PnL and focuses on peak/reversion events,
flow imbalance, and the overshoot-deficit relation from the research paper.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests

try:
    from backend.db.tick_storage import symbol_dir
except ImportError:
    from nora.backend.db.tick_storage import symbol_dir


GECKO_BASE_URL = "https://api.geckoterminal.com/api/v2"
TRADE_CACHE_TTL_SEC = 45


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(n):
        return default
    return n


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def _pct(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def _to_iso(ts_ms: Optional[int]) -> Optional[str]:
    if not ts_ms:
        return None
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000.0).isoformat(timespec="seconds") + "Z"
    except Exception:
        return None


def _normalize_ticks(df_ticks: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df_ticks is None or df_ticks.empty:
        return pd.DataFrame(columns=["timestamp_ms", "price", "volume_usd", "amount", "side"])
    ticks = df_ticks.copy()
    for col in ["timestamp_ms", "price", "volume_usd", "amount", "side"]:
        if col not in ticks.columns:
            ticks[col] = 0.0
        ticks[col] = pd.to_numeric(ticks[col], errors="coerce")
    ticks = ticks.dropna(subset=["timestamp_ms", "price"])
    ticks = ticks[ticks["price"] > 0].sort_values("timestamp_ms").reset_index(drop=True)
    ticks["volume_usd"] = ticks["volume_usd"].fillna(0.0).abs()
    ticks["amount"] = ticks["amount"].fillna(0.0).abs()
    ticks["side"] = ticks["side"].fillna(0.0)
    return ticks


def _normalize_candles(df_candles: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df_candles is None or df_candles.empty:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    candles = df_candles.copy()
    for col in ["open_time", "open", "high", "low", "close", "volume"]:
        if col in candles.columns:
            candles[col] = pd.to_numeric(candles[col], errors="coerce")
    candles = candles.dropna(subset=["open_time", "close"]).sort_values("open_time").reset_index(drop=True)
    return candles


def _fallback_price_window(candles: pd.DataFrame, latest_ts: int) -> Dict[str, Any]:
    day = candles[candles["open_time"] >= latest_ts - 24 * 3600 * 1000].copy()
    if day.empty:
        day = candles.tail(24).copy()
    if day.empty:
        return {}
    high_idx = day["high"].idxmax() if "high" in day.columns else day["close"].idxmax()
    low_idx = day["low"].idxmin() if "low" in day.columns else day["close"].idxmin()
    high = _safe_float(day.loc[high_idx].get("high"), _safe_float(day.loc[high_idx].get("close"), 0.0)) or 0.0
    low = _safe_float(day.loc[low_idx].get("low"), _safe_float(day.loc[low_idx].get("close"), 0.0)) or 0.0
    current = _safe_float(day.iloc[-1].get("close"), 0.0) or 0.0
    peak_ts = _safe_int(day.loc[high_idx].get("open_time"))
    return {
        "current_price": current,
        "peak_price_24h": high,
        "trough_price_24h": low,
        "peak_ts_ms": peak_ts,
        "sample_count_24h": int(len(day)),
    }


def _flow_stats(ticks: pd.DataFrame) -> Dict[str, float]:
    if ticks.empty:
        return {
            "buy_volume_usd": 0.0,
            "sell_volume_usd": 0.0,
            "net_flow_usd": 0.0,
            "flow_imbalance_pct": 0.0,
            "trade_count": 0.0,
            "avg_trade_usd": 0.0,
            "large_trade_share_pct": 0.0,
        }
    vals = ticks["volume_usd"].fillna(0.0).abs()
    buy = float(vals[ticks["side"] > 0].sum())
    sell = float(vals[ticks["side"] < 0].sum())
    neutral = float(vals[ticks["side"] == 0].sum())
    if neutral and buy == 0.0 and sell == 0.0:
        buy = neutral / 2.0
        sell = neutral / 2.0
    total = buy + sell
    top_cut = float(vals.quantile(0.90)) if len(vals) >= 10 else float(vals.max() if len(vals) else 0.0)
    large_share = _pct(float(vals[vals >= top_cut].sum()), float(vals.sum())) if top_cut > 0 else 0.0
    return {
        "buy_volume_usd": round(buy, 4),
        "sell_volume_usd": round(sell, 4),
        "net_flow_usd": round(buy - sell, 4),
        "flow_imbalance_pct": round(_pct(buy - sell, total), 2),
        "trade_count": float(len(ticks)),
        "avg_trade_usd": round(float(vals.mean()) if len(vals) else 0.0, 4),
        "large_trade_share_pct": round(large_share, 2),
    }


def _phase_label(
    pullback_over_range: float,
    flow_imbalance_pct: float,
    latest_direction: Optional[int],
    event_count_24h: int,
) -> Dict[str, str]:
    if event_count_24h <= 0:
        return {
            "phase": "LOW_EVENT_SAMPLE",
            "label": "Ít event",
            "tone": "muted",
            "thesis": "Mẫu DC 24h còn mỏng; chỉ dùng để theo dõi, chưa nên suy luận quy luật.",
        }
    if latest_direction == 1 and pullback_over_range >= 0.18:
        return {
            "phase": "PEAK_CONFIRMED_PULLBACK",
            "label": "Đỉnh đã xác nhận",
            "tone": "warn",
            "thesis": "DC xác nhận leg tăng đã kết thúc; giá đang hồi vào vùng kiểm định overshoot-deficit.",
        }
    if 0.20 <= pullback_over_range <= 0.32:
        return {
            "phase": "OD_UNITY_BAND",
            "label": "Vùng DC 0.20-0.32R",
            "tone": "good",
            "thesis": "Giá đang ở vùng paper xem là điểm chuyển giữa momentum và fade; nên ưu tiên đọc flow.",
        }
    if pullback_over_range > 0.45:
        return {
            "phase": "DEEP_DEFICIT",
            "label": "Hồi sâu",
            "tone": "bad",
            "thesis": "Giá đã trượt quá vùng cân bằng DC; cần kiểm tra thanh khoản và lực hấp thụ.",
        }
    if pullback_over_range < 0.10 and flow_imbalance_pct > 12:
        return {
            "phase": "PEAK_PRESSURE",
            "label": "Áp lực đỉnh",
            "tone": "good",
            "thesis": "Giá sát đỉnh 24h kèm dòng mua ròng; theo dõi event đảo chiều kế tiếp.",
        }
    if pullback_over_range < 0.10 and flow_imbalance_pct < -12:
        return {
            "phase": "DISTRIBUTION_AT_HIGH",
            "label": "Phân phối gần đỉnh",
            "tone": "warn",
            "thesis": "Giá còn gần đỉnh nhưng flow đã nghiêng bán; rủi ro trượt về band DC tăng.",
        }
    if latest_direction == -1:
        return {
            "phase": "BOUNCE_AFTER_PULLBACK",
            "label": "Hồi phục sau nhịp rơi",
            "tone": "neutral",
            "thesis": "DC xác nhận leg giảm đã kết thúc; kiểm tra liệu flow mua có duy trì sau đáy hay không.",
        }
    return {
        "phase": "BALANCED_FLOW",
        "label": "Cân bằng",
        "tone": "neutral",
        "thesis": "Chưa có một event đỉnh/hồi chi phối rõ; tiếp tục gom thêm mẫu cross-asset.",
    }


def compute_event_behavior_profile(
    symbol: str,
    df_ticks: Optional[pd.DataFrame],
    df_candles: Optional[pd.DataFrame],
    events_df: Optional[pd.DataFrame],
    theta: float,
) -> Dict[str, Any]:
    ticks = _normalize_ticks(df_ticks)
    candles = _normalize_candles(df_candles)
    if ticks.empty and candles.empty:
        return {
            "symbol": symbol,
            "phase": "NO_DATA",
            "phase_label": "Không có dữ liệu",
            "behavior_score": 0.0,
            "notes": ["Không đủ tick/candle để phân tích hành vi event."],
        }

    latest_ts = _safe_int(ticks["timestamp_ms"].max() if not ticks.empty else candles["open_time"].max())
    day_ticks = ticks[ticks["timestamp_ms"] >= latest_ts - 24 * 3600 * 1000].copy() if not ticks.empty else pd.DataFrame()
    price_window: Dict[str, Any] = {}

    if not day_ticks.empty:
        peak_idx = day_ticks["price"].idxmax()
        trough_idx = day_ticks["price"].idxmin()
        price_window = {
            "current_price": _safe_float(day_ticks.iloc[-1].get("price"), 0.0) or 0.0,
            "peak_price_24h": _safe_float(day_ticks.loc[peak_idx].get("price"), 0.0) or 0.0,
            "trough_price_24h": _safe_float(day_ticks.loc[trough_idx].get("price"), 0.0) or 0.0,
            "peak_ts_ms": _safe_int(day_ticks.loc[peak_idx].get("timestamp_ms")),
            "sample_count_24h": int(len(day_ticks)),
        }
    elif not candles.empty:
        price_window = _fallback_price_window(candles, latest_ts)

    current = float(price_window.get("current_price") or 0.0)
    peak = float(price_window.get("peak_price_24h") or current)
    trough = float(price_window.get("trough_price_24h") or current)
    peak_ts = _safe_int(price_window.get("peak_ts_ms"))
    realized_range = max(0.0, peak - trough)
    pullback_from_peak_pct = _pct(max(0.0, peak - current), peak)
    pullback_over_range = (max(0.0, peak - current) / realized_range) if realized_range > 0 else 0.0
    range_pct = _pct(realized_range, peak)
    reversion_low = peak - 0.32 * realized_range if realized_range > 0 else None
    reversion_high = peak - 0.20 * realized_range if realized_range > 0 else None

    day_flow = _flow_stats(day_ticks)
    post_peak_ticks = day_ticks[day_ticks["timestamp_ms"] >= peak_ts].copy() if peak_ts and not day_ticks.empty else pd.DataFrame()
    post_peak_flow = _flow_stats(post_peak_ticks)
    six_hour_ticks = ticks[ticks["timestamp_ms"] >= latest_ts - 6 * 3600 * 1000].copy() if not ticks.empty else pd.DataFrame()
    six_hour_flow = _flow_stats(six_hour_ticks)

    latest_event = {}
    event_count_24h = 0
    event_rate_24h = 0.0
    latest_direction: Optional[int] = None
    os_ratio_median = 0.0
    delta_over_r_median = 0.0
    fade_signal_rate_24h = 0.0

    if events_df is not None and not events_df.empty:
        events = events_df.copy().sort_values("timestamp_conf")
        for col in ["timestamp_conf", "direction", "overshoot_ratio", "delta_over_R", "tmv", "price_ext", "price_conf"]:
            if col in events.columns:
                events[col] = pd.to_numeric(events[col], errors="coerce")
        day_events = events[events["timestamp_conf"] >= latest_ts - 24 * 3600 * 1000].copy()
        if day_events.empty:
            day_events = events.tail(min(12, len(events))).copy()
        event_count_24h = int(len(day_events))
        event_rate_24h = float(event_count_24h)
        os_ratio_median = round(float(day_events["overshoot_ratio"].median()), 3) if "overshoot_ratio" in day_events else 0.0
        delta_over_r_median = round(float(day_events["delta_over_R"].median()), 3) if "delta_over_R" in day_events else 0.0
        if "fade_reversal_signal" in day_events:
            fade_signal_rate_24h = round(float(day_events["fade_reversal_signal"].mean() * 100.0), 2)
        last = day_events.iloc[-1]
        latest_direction = _safe_int(last.get("direction"), 0)
        latest_event = {
            "timestamp_ms": _safe_int(last.get("timestamp_conf")),
            "timestamp": _to_iso(_safe_int(last.get("timestamp_conf"))),
            "direction": latest_direction,
            "direction_label": "Up leg ended / peak confirmed" if latest_direction == 1 else "Down leg ended / trough confirmed",
            "price_ext": _safe_float(last.get("price_ext"), 0.0),
            "price_conf": _safe_float(last.get("price_conf"), 0.0),
            "overshoot_ratio": _safe_float(last.get("overshoot_ratio"), 0.0),
            "delta_over_R": _safe_float(last.get("delta_over_R"), 0.0),
            "tmv": _safe_float(last.get("tmv"), 0.0),
        }

    phase = _phase_label(pullback_over_range, float(day_flow["flow_imbalance_pct"]), latest_direction, event_count_24h)
    pullback_signal = 100.0 - min(100.0, abs(pullback_over_range - 0.26) / 0.26 * 100.0)
    event_signal = min(100.0, event_count_24h * 8.0)
    flow_signal = min(100.0, abs(float(day_flow["flow_imbalance_pct"])) * 2.0)
    range_signal = min(100.0, range_pct * 8.0)
    behavior_score = round(_clamp(pullback_signal * 0.34 + event_signal * 0.28 + flow_signal * 0.20 + range_signal * 0.18), 1)

    notes = [phase["thesis"]]
    if realized_range > 0:
        notes.append(
            f"Giá đã hồi {pullback_over_range:.2f}R từ đỉnh 24h; vùng DC cần quan sát là 0.20-0.32R."
        )
    if post_peak_flow["trade_count"] > 0:
        notes.append(
            f"Sau đỉnh: flow ròng {post_peak_flow['net_flow_usd']:.0f} USD, imbalance {post_peak_flow['flow_imbalance_pct']:.1f}%."
        )
    if os_ratio_median:
        notes.append(f"Median ω/δ gần đây = {os_ratio_median:.2f}; unity là điểm đổi dấu overshoot-deficit.")

    return {
        "symbol": symbol,
        "phase": phase["phase"],
        "phase_label": phase["label"],
        "phase_tone": phase["tone"],
        "thesis": phase["thesis"],
        "behavior_score": behavior_score,
        "theta": float(theta),
        "theta_pct": round(float(theta) * 100.0, 3),
        "current_price": current,
        "peak_price_24h": peak,
        "trough_price_24h": trough,
        "peak_timestamp_ms": peak_ts or None,
        "peak_timestamp": _to_iso(peak_ts),
        "pullback_from_peak_pct": round(pullback_from_peak_pct, 3),
        "pullback_over_range": round(float(pullback_over_range), 3),
        "reversion_progress_pct": round(_clamp(pullback_over_range / 0.32 * 100.0), 1),
        "realized_range_pct": round(range_pct, 3),
        "dc_unity_band": {
            "label": "0.20-0.32R",
            "low_price": round(float(reversion_low), 12) if reversion_low is not None else None,
            "high_price": round(float(reversion_high), 12) if reversion_high is not None else None,
        },
        "event_count_24h": event_count_24h,
        "event_rate_24h": round(event_rate_24h, 2),
        "latest_event": latest_event,
        "overshoot_ratio_median_24h": os_ratio_median,
        "delta_over_R_median_24h": delta_over_r_median,
        "fade_signal_rate_24h_pct": fade_signal_rate_24h,
        "flow_24h": day_flow,
        "flow_6h": six_hour_flow,
        "post_peak_flow": post_peak_flow,
        "sample_count_24h": int(price_window.get("sample_count_24h") or 0),
        "notes": notes,
    }


def _parse_trade_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    attr = item.get("attributes") or {}
    ts_str = attr.get("block_timestamp")
    try:
        ts_ms = int(datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        ts_ms = None
    volume_usd = _safe_float(attr.get("volume_in_usd"), 0.0) or 0.0
    kind = str(attr.get("kind") or "").lower()
    return {
        "timestamp_ms": ts_ms,
        "timestamp": ts_str,
        "kind": kind or None,
        "side": 1 if kind == "buy" else -1 if kind == "sell" else 0,
        "volume_usd": volume_usd,
        "price_from_usd": _safe_float(attr.get("price_from_in_usd")),
        "price_to_usd": _safe_float(attr.get("price_to_in_usd")),
        "from_token_amount": _safe_float(attr.get("from_token_amount")),
        "to_token_amount": _safe_float(attr.get("to_token_amount")),
        "tx_hash": attr.get("tx_hash"),
        "tx_from_address": attr.get("tx_from_address"),
        "block_number": _safe_int(attr.get("block_number")),
    }


def fetch_recent_pool_trades(symbol: str, data_root: Optional[str] = None, limit: int = 40) -> Dict[str, Any]:
    """Fetch recent GeckoTerminal pool trades with a short disk cache."""
    s_dir = symbol_dir(symbol, data_root=data_root)
    pool_path = os.path.join(s_dir, "dex_pool.json")
    cache_path = os.path.join(s_dir, "recent_trades.json")
    now = int(time.time())

    if os.path.isfile(cache_path) and now - int(os.path.getmtime(cache_path)) < TRADE_CACHE_TTL_SEC:
        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass

    if not os.path.isfile(pool_path):
        try:
            from backend.db.tick_storage import load_ticks_df
            df_ticks = load_ticks_df(symbol, data_root=data_root)
            if df_ticks is not None and not df_ticks.empty:
                tail_ticks = df_ticks.tail(limit).iloc[::-1]
                rows = []
                for _, r in tail_ticks.iterrows():
                    side_val = 1 if float(r.get("side", 1) or 1) >= 0 else -1
                    rows.append({
                        "tx_hash": str(r.get("tx_hash", f"0x{symbol.lower()}...{int(r.get('timestamp_ms', 0)) % 100000}")),
                        "block_timestamp": int(r.get("timestamp_ms", 0)) // 1000,
                        "side": side_val,
                        "price_usd": float(r.get("price", 0.0)),
                        "volume_usd": float(r.get("volume_usd", 100.0)),
                        "amount": float(r.get("amount", 0.0)),
                    })
                total = sum(r["volume_usd"] for r in rows)
                buy = sum(r["volume_usd"] for r in rows if r["side"] == 1)
                sell = sum(r["volume_usd"] for r in rows if r["side"] == -1)
                return {
                    "source": "local_pool_ticks",
                    "rows": rows,
                    "count": len(rows),
                    "summary": {
                        "buy_volume_usd": round(buy, 4),
                        "sell_volume_usd": round(sell, 4),
                        "net_flow_usd": round(buy - sell, 4),
                        "flow_imbalance_pct": round(_pct(buy - sell, buy + sell), 2),
                        "total_volume_usd": round(total, 4),
                    }
                }
        except Exception:
            pass
        return {"source": None, "rows": [], "error": "missing dex_pool.json"}

    try:
        with open(pool_path, "r", encoding="utf-8") as handle:
            pool = json.load(handle)
    except Exception as exc:
        return {"source": None, "rows": [], "error": str(exc)}

    network = pool.get("network")
    pool_address = pool.get("pool_address")
    if not network or not pool_address:
        return {"source": None, "rows": [], "error": "missing network or pool_address"}

    url = f"{GECKO_BASE_URL}/networks/{network}/pools/{pool_address}/trades"
    try:
        response = requests.get(url, headers={"accept": "application/json"}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        rows = []
        for item in payload.get("data") or []:
            parsed = _parse_trade_item(item)
            if parsed:
                rows.append(parsed)
        rows = rows[:limit]
        total = sum(float(r.get("volume_usd") or 0.0) for r in rows)
        buy = sum(float(r.get("volume_usd") or 0.0) for r in rows if r.get("side") == 1)
        sell = sum(float(r.get("volume_usd") or 0.0) for r in rows if r.get("side") == -1)
        result = {
            "source": "geckoterminal_pool_trades",
            "fetched_at": now,
            "network": network,
            "pool_address": pool_address,
            "count": len(rows),
            "summary": {
                "buy_volume_usd": round(buy, 4),
                "sell_volume_usd": round(sell, 4),
                "net_flow_usd": round(buy - sell, 4),
                "flow_imbalance_pct": round(_pct(buy - sell, buy + sell), 2),
                "total_volume_usd": round(total, 4),
            },
            "rows": rows,
        }
        try:
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return result
    except Exception as exc:
        return {"source": "geckoterminal_pool_trades", "rows": [], "error": str(exc)}
