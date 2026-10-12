"""
test_round4_venue_and_fills.py — vòng 4: dữ liệu OKX perp (nến điền, ngưỡng phút trống, bước nhảy giá).

1. Engine KHÔNG khớp lệnh trên nến điền (is_filled=1); khớp ở open phút có giao dịch kế tiếp.
2. load_candles giữ cột is_filled cho engine.
3. Gate: ngưỡng phút trống MAX_FILLED_RATIO_1M (60%).
4. WFA gate có điều kiện lợi nhuận IS (min_is_profit_pct).
5. Monte Carlo: robust_passed = WFA gate True VÀ ruin <= max_ruin_pct.
7. Mô hình phí theo venue (CEX/DEX) trong Research.
"""
import numpy as np
import pandas as pd
import pytest

from data_helpers import FrameData

from data_helpers import save_synthetic

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data

D = 86_400_000
T0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC
FLOW_1M = {
    "id": "flow1", "name": "LONG close>open", "type": "LONG",
    "ast": {
        "type": "LONG",
        "match": [{"condition": [[[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]]}],
        "stop": [{"condition": [[[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]]}],
    },
}


def _rw_1m(n_days: float, seed: int = 11, t0: int = T0) -> pd.DataFrame:
    n = int(n_days * 1440)
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open_time": t0 + np.arange(n, dtype=np.int64) * 60_000,
        "open": open_,
        "high": np.maximum(open_, close) * 1.0003,
        "low": np.minimum(open_, close) * 0.9997,
        "close": close,
        "volume": rng.uniform(10, 100, n),
    })


@pytest.fixture
def clean_asset(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    df = _rw_1m(40)
    save_synthetic(
        symbol="CLEAN", output_dir=str(root), df_1m_raw=df, data_root=str(root),
    )
    return "CLEAN", str(root)


# ─── 1-2. Nến điền ──────────────────────────────────────────────────────────

def _engine_with(df_1m: pd.DataFrame, match_time: int):
    from backend.nautilus.engine import BacktestEngine
    from backend.models.params import StrategyParams
    df_4h = df_1m.assign(dt=pd.to_datetime(df_1m.open_time, unit="ms", utc=True)).set_index("dt").resample(
        "4h", closed="left", label="left").agg({"open_time": "first", "open": "first", "high": "max",
                                                "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index(drop=True)
    eng = BacktestEngine(0, 0, "T", int(df_1m.open_time.min()), int(df_1m.open_time.max()), data=FrameData({"T": df_1m}))
    ast = {"type": "LONG",
           "match": [{"condition": [[[{"frame": "1m", "column": "open_time"}, "==", match_time]]]}],
           "stop": []}
    eng.add_strategy_flow("LONG_f", StrategyParams(name="LONG_f", extra={"ast": ast}))
    eng.df_base = eng._prepare_candles(df_1m)
    eng.df_4h = eng._enrich_4h(eng._prepare_candles(df_4h))
    return eng


def test_filled_minutes_are_never_execution_bars():
    # P15: phút điền (is_filled=1, không giao dịch) KHÔNG vào Nautilus (nến thực thi = nến 1m THẬT). Tín hiệu ở nến thật k khớp market ở GIÁ ĐÓNG nến k
    # (= open k+1, nằm ngay trước khoảng phút điền); engine cũ chờ "phút có giao dịch kế tiếp" (k+4). Mọi fill phải rơi vào ranh giới của nến THẬT.
    df = _rw_1m(2)
    df["is_filled"] = 0
    k = 1500                                   # tín hiệu ở nến k (sau khi đã có cây 4h đóng)
    df.loc[k + 1:k + 3, "is_filled"] = 1       # 3 phút kế tiếp không có giao dịch
    for i in range(k + 1, k + 4):              # nến điền: O=H=L=C=close trước
        p = float(df.loc[k, "close"])
        df.loc[i, ["open", "high", "low", "close"]] = p
    eng = _engine_with(df, int(df.loc[k, "open_time"]))
    eng.run()
    pos = eng.closed_positions[0]
    assert pos.enter_time == int(df.loc[k, "open_time"]) + 60_000, "Khớp ở giá đóng nến thật k"
    real_close_ts = {int(t) + 60_000 for t in df.loc[df["is_filled"] == 0, "open_time"]}
    assert {o.order_time for o in eng.orders} <= real_close_ts, "Không fill nào gắn với nến điền"


def test_final_close_uses_last_real_minute():
    df = _rw_1m(2)
    df["is_filled"] = 0
    df.loc[len(df) - 5:, "is_filled"] = 1
    eng = _engine_with(df, int(df.loc[1500, "open_time"]))
    eng.run()
    pos = eng.closed_positions[-1]
    assert pos.close_time == int(df.loc[len(df) - 6, "open_time"]) + 60_000       # nến thật cuối đóng lúc open + 1 phút (ts_event của Nautilus = giờ đóng nến)


def test_fetch_candles_keeps_is_filled(clean_asset):
    from backend.data.data import load_candles
    sym, root = clean_asset
    assert "is_filled" in load_candles(sym, "1m", data_root=root).columns


# ─── 3. Gate ngưỡng phút trống ──────────────────────────────────────────────

@pytest.mark.parametrize("empty_ratio,blocked", [(0.45, False), (0.70, True)])
def test_gate_filled_ratio_threshold(tmp_path, empty_ratio, blocked):
    from backend.data.crawl import evaluate_data_quality
    df = _rw_1m(35)
    keep = np.random.default_rng(0).random(len(df)) >= empty_ratio
    keep[0] = keep[-1] = True
    save_synthetic(symbol="SPARSE", output_dir=str(tmp_path), df_1m_raw=df[keep], data_root=str(tmp_path))
    dq = evaluate_data_quality("SPARSE", data_root=str(tmp_path))
    # WARNING (vd. nhiều nến volume=0) không chặn; chỉ BLOCKED / NEEDS_MORE_DATA mới chặn
    assert (dq["status"] in ("BLOCKED", "NEEDS_MORE_DATA")) is blocked, dq["issues"]


# ─── 4. WFA: điều kiện lợi nhuận IS ─────────────────────────────────────────


# ─── 5. Monte Carlo robust verdict ──────────────────────────────────────────

# ─── 7. Phí theo venue ──────────────────────────────────────────────────────


# ─── 8. Crawler resume không được biến nến điền thành nến thật ──────────────
# (Thay cho test_crawler_strips_filled_from_existing: test đó tự viết lại logic lọc
#  thay vì gọi code crawler nên luôn pass; lỗi thật nằm ở _read_pickle_if_usable
#  cắt về 6 cột OHLCV trước khi lọc -> mất cờ is_filled.)


# ─── 9. Bước nhảy > 50%/phút: dữ liệu OKX chính thức -> WARNING (sự kiện thật), không chặn ───

def test_extreme_move_is_warning_not_blocked(tmp_path):
    from backend.data.crawl import evaluate_data_quality
    df = _rw_1m(35)
    k = 20_000
    df.loc[k, ["open", "high", "low", "close"]] = df.loc[k, "close"] * 1.8   # +80% trong 1 phút
    save_synthetic(symbol="JUMP", output_dir=str(tmp_path), df_1m_raw=df, data_root=str(tmp_path))
    dq = evaluate_data_quality("JUMP", data_root=str(tmp_path))
    assert dq["status"] == "WARNING", dq["issues"]
