"""Kịch bản "golden results": chạy engine backtest và trả về dict CHUẨN HOÁ để so sánh BIT-IDENTICAL.

Mục đích: các thay đổi hiệu năng (mmap dữ liệu dùng chung, bỏ qua phút rảnh...) phải cho kết quả y hệt.
Mọi float được mã hoá bằng float.hex() (None giữ nguyên) nên so sánh bằng `==` là chính xác từng bit.
Bỏ qua id (result_id/order_id dựa trên thời gian) và mọi thứ không tất định.

Các hàm ở đây thuần tuý (không đụng file ngoài `root` được truyền vào, trừ scenario_portfolio_real chỉ ĐỌC data_root).
Snapshot lưu ở test/golden/*.json, sinh lại bằng test/make_golden.py.
"""
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

T0 = 1_700_006_400_000
M = 60_000
DAY = 86_400_000


# ─── Mã hoá chuẩn ───────────────────────────────────────────────────────────

def hx(v: Any) -> Any:
    """float -> chuỗi hex chính xác; None giữ nguyên; int/str giữ nguyên."""
    if v is None:
        return None
    if isinstance(v, (bool, str)):
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    return float(v).hex()


def unhx(v: Any) -> Any:
    """Giải mã hex để in cho dễ đọc (chuỗi không phải hex giữ nguyên)."""
    if isinstance(v, str):
        try:
            return float.fromhex(v) if v.startswith(("0x", "-0x")) or v in ("inf", "-inf", "nan") else v
        except ValueError:
            return v
    return v


def _enum(v: Any) -> Any:
    return v.name if hasattr(v, "name") else v


def canon_position(p: Any) -> Dict[str, Any]:
    return {
        "symbol": p.symbol, "strategy_id": p.strategy_id or None, "flow": p.flow or None,
        "pos_type": _enum(p.pos_type), "status": _enum(p.status), "status_int": int(p.status),
        "enter_time": int(p.enter_time), "close_time": None if p.close_time is None else int(p.close_time),
        "enter_price": hx(p.enter_price), "close_price": hx(p.close_price), "avg_price": hx(p.avg_price),
        "qty": hx(p.qty), "layers": int(p.layers), "real_pnl": hx(p.real_pnl), "profit_pct": hx(p.profit_pct),
        "fees_usd": hx(p.fees_usd), "funding_usd": hx(p.funding_usd), "mae_pct": hx(p.mae_pct),
        "entry_equity": hx(p.entry_equity),
    }


def _pos_key(c: Dict[str, Any]):
    return (c["close_time"] if c["close_time"] is not None else 1 << 62, c["enter_time"], c["symbol"],
            c["strategy_id"] or c["flow"] or "")


def canon_order(o: Any) -> Dict[str, Any]:
    return {"order_time": int(o.order_time), "order_type": _enum(o.order_type), "order_price": hx(o.order_price),
            "qty": hx(o.qty), "phase": int(o.phase), "fee_usd": hx(o.fee_usd), "liquidity": o.liquidity}


def canonicalize(res: Dict[str, Any]) -> Dict[str, Any]:
    positions = sorted((canon_position(p) for p in res["positions"]), key=_pos_key)
    orders = sorted((canon_order(o) for o in res["orders"]),
                    key=lambda c: (c["order_time"], c["order_type"], c["order_price"], c["qty"]))
    return {
        "positions": positions,
        "equity_curve": [{"time": int(r["time"]), "equity": hx(r["equity"]), "equity_worst": hx(r["equity_worst"])}
                         for r in res["equity_curve"]],
        "final_equity": hx(res["final_equity"]),
        "rejected_for_capital": int(res["rejected_for_capital"]),
        "rejected_for_risk": int(res["rejected_for_risk"]) if "rejected_for_risk" in res else None,
        "halted_at": None if res.get("halted_at") is None else int(res["halted_at"]),
        "ruined_at": None if res.get("ruined_at") is None else int(res["ruined_at"]),
        "n_orders": len(res["orders"]),
        "orders": orders,
    }


def diff_canonical(a: Dict[str, Any], b: Dict[str, Any], limit: int = 3) -> List[str]:
    """Danh sách mô tả các khác biệt đầu tiên (a = golden, b = chạy mới); rỗng nếu giống hệt."""
    out: List[str] = []
    for key in ("final_equity", "rejected_for_capital", "rejected_for_risk", "halted_at", "ruined_at", "n_orders"):
        if a.get(key) != b.get(key):
            out.append(f"{key}: golden={unhx(a.get(key))!r} new={unhx(b.get(key))!r}")
    pa, pb = a["positions"], b["positions"]
    if len(pa) != len(pb):
        out.append(f"number of positions: golden={len(pa)} new={len(pb)}")
    for i, (x, y) in enumerate(zip(pa, pb)):
        if x != y:
            fields = [k for k in x if x[k] != y.get(k)]
            detail = ", ".join(f"{k}: golden={unhx(x[k])!r} new={unhx(y.get(k))!r}" for k in fields)
            out.append(f"position #{i} ({x['symbol']} {x['strategy_id'] or x['flow']} enter={x['enter_time']}): {detail}")
            if len(out) >= limit:
                return out
    ea, eb = a["equity_curve"], b["equity_curve"]
    if len(ea) != len(eb):
        out.append(f"equity_curve rows: golden={len(ea)} new={len(eb)}")
    for i, (x, y) in enumerate(zip(ea, eb)):
        if x != y:
            out.append(f"equity_curve[{i}] t={x['time']}: golden=({unhx(x['equity'])}, {unhx(x['equity_worst'])}) "
                       f"new=({y['time']}, {unhx(y['equity'])}, {unhx(y['equity_worst'])})")
            break
    if not out and a["orders"] != b["orders"]:
        for i, (x, y) in enumerate(zip(a["orders"], b["orders"])):
            if x != y:
                out.append(f"order #{i} t={x['order_time']}: golden={x} new={y}")
                break
    return out[:limit + 3]


# ─── Tiện ích môi trường ────────────────────────────────────────────────────

@contextmanager
def data_root_env(root: str):
    """Đặt NORA_LOCAL_DATA_ROOT = root trong khối with, khôi phục sau; xoá cache dữ liệu trước/sau."""
    old = os.environ.get("NORA_LOCAL_DATA_ROOT")
    os.environ["NORA_LOCAL_DATA_ROOT"] = str(root)
    clear_caches()
    try:
        yield
    finally:
        clear_caches()
        if old is None:
            os.environ.pop("NORA_LOCAL_DATA_ROOT", None)
        else:
            os.environ["NORA_LOCAL_DATA_ROOT"] = old


def clear_caches() -> None:
    from backend.signal import compute as portfolio
    from backend.data.data import clear_caches as clear_data_caches
    clear_data_caches()
    portfolio.data_cache_clear()


# ─── Kịch bản 1: danh mục tổng hợp (3 tài sản perp) ─────────────────────────

def _series(days, seed, vol):
    n = days * 1440
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol, n)
    r[1:] -= 0.15 * r[:-1]
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": o,
                         "high": np.maximum(o, c) * (1 + vol / 3), "low": np.minimum(o, c) * (1 - vol / 3),
                         "close": c, "volume": 10.0})


def write_synthetic_market(root) -> None:
    """Giống hệt fixture `market` của test_portfolio_engine.py (catalog giả lập trong root)."""
    from data_helpers import save_synthetic
    root = str(root)
    with data_root_env(root):
        for k, (sym, vol) in enumerate((("AAA", 0.0008), ("BBB", 0.0016), ("CCC", 0.0030))):
            save_synthetic(symbol=sym, output_dir=os.path.join(root, "cex"), df_1m_raw=_series(40, 10 + k, vol))


def _f(frame, column, index=0):
    return {"frame": frame, "column": column, "index": index}


_POSITION = {"market": "perp", "leverage": 10, "exit_unit": "atr", "atr_frame": "1h", "atr_period": 14,
             "sizing": "risk", "risk_per_trade_pct": 1.0, "max_notional_pct": 300, "stop_loss_rate": 2.0,
             "take_profit_rate": 3.0, "trailing_stop": 1.5, "trailing_activation_pct": 1.0, "timeout": 720}
LONG = {"id": "rsi_long", "side": "LONG", "tree": [[[_f("15m", "rsi_14"), "<", 40]]], "position": _POSITION}
SHORT = {"id": "rsi_short", "side": "SHORT", "tree": [[[_f("15m", "rsi_14"), ">", 60]]], "position": _POSITION}


def scenario_portfolio_synthetic(root) -> Dict[str, Any]:
    from backend.alpha.plan import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    write_synthetic_market(root)
    with data_root_env(str(root)):
        eng = PortfolioEngine(["AAA@perp", "BBB@perp", "CCC@perp"], [LONG, SHORT], T0, T0 + 30 * DAY,
                              trade_start_ts=T0 + 3 * DAY, risk=RiskConfig(), use_cache=False)
        eng.run()
        return canonicalize(eng.get_results())


# ─── Kịch bản 3: danh mục dữ liệu thật ──────────────────────────────────────

REAL_SYMBOLS = ["BTC@perp", "SOL@perp", "DOGE@perp"]
REAL_START_MS = int(pd.Timestamp("2025-03-01", tz="UTC").timestamp() * 1000)
REAL_END = "2025-05-30"
REAL_WARMUP_DAYS = 20


def real_data_available(data_root) -> bool:
    """Catalog OKX thật (market/okx/catalog dưới data_root) có nến 1m của mọi REAL_SYMBOLS."""
    from backend.data.data import read_manifest
    cat = os.path.join(str(data_root), "market", "okx", "catalog")
    return all(read_manifest(s.split("@")[0], cat) is not None for s in REAL_SYMBOLS)


def scenario_portfolio_real(data_root, end: Optional[str] = None, shared_dir: Optional[str] = None) -> Dict[str, Any]:
    """shared_dir: nếu có, export dữ liệu mmap vào đó rồi chạy bằng PortfolioEngine(shared_dir=...) (kết quả phải y hệt)."""
    from backend.alpha import strategies as sb
    from backend.analys.param import RISK, materialize
    from backend.alpha.plan import RiskConfig
    from backend.nautilus.engine import PortfolioEngine
    cand = sb.BY_ID
    # cooldown=0, limit_through_pct=0: snapshot này sinh trước khi BASE_POSITION có cooldown=60 / khớp limit phải đi qua mức; ghim để golden
    # vẫn đo đúng ngữ nghĩa cũ
    strategies = [
        materialize(cand["trend_long"], {"sig.adx_min": 25, "stop_loss_rate": 2.5, "trailing_stop": 3.0,
                                            "trailing_activation_pct": 1.0, "timeout": 4320}, cooldown=0, limit_through_pct=0.0),
        materialize(cand["reversion_long"], {"sig.rsi_lo": 25, "sig.er_max": 0.3, "stop_loss_rate": 1.5,
                                                "take_profit_rate": 1.0, "timeout": 1440}, cooldown=0, limit_through_pct=0.0),
    ]
    risk = RiskConfig.from_dict({**RISK, "kill_switch_dd_pct": 0, "max_open_risk_pct": 0.0, "dd_throttle_pct": 0.0})   # golden: ngữ nghĩa cũ
    end_ms = int(pd.Timestamp(end or REAL_END, tz="UTC").timestamp() * 1000)
    with data_root_env(str(data_root)):
        eng = PortfolioEngine(REAL_SYMBOLS, strategies, REAL_START_MS - REAL_WARMUP_DAYS * DAY, end_ms,
                              trade_start_ts=REAL_START_MS, risk=risk, shared_dir=shared_dir)
        if shared_dir:
            from backend.jobs import evaluate as shared_data
            shared_data.export(eng, shared_dir)
            clear_caches()
        eng.run()
        return canonicalize(eng.get_results())
