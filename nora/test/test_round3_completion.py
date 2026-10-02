"""
test_round3_completion.py — các mục còn lại sau review vòng 3.

Mỗi test tương ứng một lỗi đã được xác nhận khi review; test phải FAIL trên
commit 808d7f4 (baseline) và PASS sau khi sửa.

1. Luồng dữ liệu SẠCH phải chạy được end-to-end (gate không được chặn tất cả).
2. MC: source_wfa_id > source_handle > trades; không mượn gate bằng trades giả.
3. has_ticks fail-closed; tick ngắn không được thay chuỗi 1m dài.
4. Cache research phải hết hạn khi 1m/manifest thay đổi.
5. Sweep θ không chọn θ khi quá ít điểm để tách train/test.
6. Gate bắt buộc 4h; load_candle_df không tự dựng nến từ tick.
7. Không còn default 'SOL'; cấu hình WFA ở frontend khớp schema backend.
8. Crawler xoá checkpoint khi crawl thành công.
"""
import json
import os
import re
import time

import numpy as np
import pandas as pd
import pytest

from backend.core.data.resampler import save_resampled_dataset

D = 86_400_000
T0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC (neo ngày)
FRONTEND_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "src"))

FLOW_1M = {
    "id": "flow1",
    "name": "LONG close>open",
    "type": "LONG",
    "ast": {
        "type": "LONG",
        "match": [{"condition": [[[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]]}],
        "stop": [{"condition": [[[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]]}],
    },
}


def _rw_1m(n_days: int, seed: int = 7) -> pd.DataFrame:
    n = n_days * 1440
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 3e-4, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 3e-4, n)))
    return pd.DataFrame({
        "open_time": T0 + np.arange(n, dtype=np.int64) * 60_000,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.uniform(10, 100, n),
    })


@pytest.fixture
def clean_asset(tmp_path, monkeypatch):
    """Tài sản 40 ngày dữ liệu 'sạch' đi qua đúng đường crawler -> resampler -> manifest."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    sym = "CLEAN"
    df = _rw_1m(40)
    save_resampled_dataset(
        symbol=sym, output_dir=str(root), df_1m_raw=df, pool_address="0xclean",
        crawl_ok=True, requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
    )
    return sym, str(root)


def _wait_mc(job_id, timeout=30):
    from backend.api.jobs.store import get_mc_job
    t_end = time.time() + timeout
    while time.time() < t_end:
        job = get_mc_job(job_id)
        if job and job.get("status") in ("completed", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("MC job không kết thúc")


def _completed_wfa(trades, gate=True):
    from backend.api.jobs.store import complete_wfa_job, create_wfa_job
    job_id = create_wfa_job("CLEAN", "S", 4)
    complete_wfa_job(job_id, {
        "acceptance_gate_passed": gate, "aggregate_oos_trades": trades,
        "strategy_name": "S", "symbol": "CLEAN",
    })
    return job_id


def _small_trades(n=40):
    return [{"trade_id": str(i), "pnl_pct": 0.5 if i % 2 else -0.4} for i in range(n)]


# ─── 1. Dữ liệu sạch chạy được end-to-end ───────────────────────────────────

def test_gate_approves_clean_resampled_data(clean_asset):
    from backend.core.data.quality_gate import DataQualityStatus, evaluate_data_quality
    sym, root = clean_asset
    dq = evaluate_data_quality(sym, timeframe="1m", data_root=root)
    assert dq["status"] == DataQualityStatus.APPROVED, dq["issues"]


# ─── 2. Monte Carlo: ưu tiên nguồn lệnh ─────────────────────────────────────


# ─── 3. Tick thật: fail-closed và phải đủ độ phủ ────────────────────────────

def _write_ticks(sym_dir, start_ts, n=500, step_ms=60_000):
    pd.DataFrame({
        "timestamp_ms": start_ts + np.arange(n, dtype=np.int64) * step_ms,
        "price": 100.0 + np.sin(np.arange(n)),
        "amount": 1.0,
    }).to_parquet(os.path.join(sym_dir, "ticks.parquet"))


def test_has_ticks_requires_manifest_declaration(tmp_path):
    from backend.db.local_pkl import has_ticks
    sym_dir = tmp_path / "TK"
    sym_dir.mkdir()
    _write_ticks(str(sym_dir), T0)
    assert has_ticks("TK", data_root=str(tmp_path)) is False, "ticks.parquet không có manifest khai báo -> False"

    with open(sym_dir / "manifest.json", "w") as f:
        json.dump({"synthetic": False, "ticks": {"synthetic": False, "start_ts": T0, "end_ts": T0 + D}}, f)
    assert has_ticks("TK", data_root=str(tmp_path)) is True
    assert has_ticks("TK", data_root=str(tmp_path), min_days=30) is False


# ─── 4. Cache research hết hạn khi dữ liệu đổi ──────────────────────────────


# ─── 5. Sweep θ ─────────────────────────────────────────────────────────────


# ─── 6. Gate bắt buộc 4h; không dựng nến từ tick ────────────────────────────

def test_gate_blocks_when_4h_missing(clean_asset):
    from backend.core.data.quality_gate import DataQualityStatus, evaluate_data_quality
    sym, root = clean_asset
    os.remove(os.path.join(root, sym, "4h.pkl"))
    dq = evaluate_data_quality(sym, timeframe="1m", data_root=root)
    assert dq["status"] == DataQualityStatus.BLOCKED
    assert any("4h" in i for i in dq["issues"])


def test_load_candle_df_has_no_tick_fallback(tmp_path):
    from backend.db.tick_storage import load_candle_df
    sym_dir = tmp_path / "ONLYTICKS"
    sym_dir.mkdir()
    _write_ticks(str(sym_dir), T0, n=2000)
    assert load_candle_df("ONLYTICKS", "1h", data_root=str(tmp_path)).empty


# ─── 7. Không default 'SOL'; frontend khớp schema ───────────────────────────


def _js_object_numbers(block: str) -> dict:
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)\s*,", block)}


def test_no_hardcoded_sol_fallback_in_frontend():
    offenders = []
    for dirpath, _, files in os.walk(FRONTEND_SRC):
        for name in files:
            if name.endswith(".jsx") and not name.startswith("__"):
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                if re.search(r"\|\|\s*['\"]SOL['\"]|symbol:\s*['\"]SOL['\"]", text):
                    offenders.append(name)
    assert not offenders, f"Còn fallback 'SOL' cứng: {offenders}"


# ─── 8. Crawler xoá checkpoint khi thành công ───────────────────────────────


