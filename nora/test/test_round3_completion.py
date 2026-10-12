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
import os
import re

import numpy as np
import pandas as pd
import pytest

from data_helpers import save_synthetic

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
    save_synthetic(
        symbol=sym, output_dir=str(root), df_1m_raw=df, data_root=str(root),
    )
    return sym, str(root)


# ─── 1. Dữ liệu sạch chạy được end-to-end ───────────────────────────────────

def test_gate_approves_clean_resampled_data(clean_asset):
    from backend.data.crawl import DataQualityStatus, evaluate_data_quality
    from backend.data.data import quality_verdict
    sym, root = clean_asset
    dq = evaluate_data_quality(sym, data_root=root)
    assert dq["status"] == DataQualityStatus.APPROVED, dq["issues"]
    assert quality_verdict(sym, root)["status"] == DataQualityStatus.APPROVED    # verdict đã được ghi vào manifest lúc ghi catalog


# ─── 2. Monte Carlo: ưu tiên nguồn lệnh ─────────────────────────────────────


# ─── 4. Cache research hết hạn khi dữ liệu đổi ──────────────────────────────


# ─── 5. Sweep θ ─────────────────────────────────────────────────────────────


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


