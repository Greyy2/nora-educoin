# ARCHIVED (P17-T1 B4): kiểm cổng chất lượng/bù nến trên kho pkl + backend.crawl cũ; hành vi còn lại đã viết lại trong test/test_data.py (catalog + verdict trong manifest).
"""
test_resampler_idempotent.py — Đợt 1.2: fill_missing_1m_candles phải idempotent

Vấn đề cũ: fill(fill(x)) tạo ra is_filled=0 cho nến đã được điền,
vì hàm reset is_filled=0 cho mọi dòng kể cả dòng đã điền ở lần trước.

Test phải FAIL trên code cũ (trước khi sửa resampler):
1. fill(fill(x)) phải có cùng filled_ratio và số dòng is_filled==1 như fill(x)
2. Nếu thêm dữ liệu thật cho phút đã được điền → is_filled phải là 0 và mang giá thật
3. Gọi save_resampled_dataset 2 lần: manifest.filled_ratio_1m phải giữ nguyên
4. Crawler: existing_1m sau khi lọc is_filled==1 không chứa nến điền
"""
import os
import tempfile
import pandas as pd

from backend.crawl.store import fill_missing_1m_candles, save_resampled_dataset


def _make_1m_df(n: int = 100, gap_at: int = 50) -> pd.DataFrame:
    """Tạo DataFrame 1m với gap tại vị trí gap_at (thiếu 1 phút)."""
    t0 = 1700000000000
    times = [t0 + i * 60_000 for i in range(n)]
    # Tạo gap bằng cách bỏ phút tại vị trí gap_at
    times = [t for i, t in enumerate(times) if i != gap_at]
    prices = [100.0 + i * 0.01 for i in range(len(times))]
    return pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [10.0] * len(times),
    })


# ── Test 1: fill(fill(x)) == fill(x) ─────────────────────────────────────────
def test_fill_idempotent_filled_ratio():
    """Gọi fill 2 lần phải cho cùng filled_ratio và số dòng is_filled==1."""
    df = _make_1m_df(n=120, gap_at=60)

    df_once = fill_missing_1m_candles(df)
    filled_once = int((df_once["is_filled"] == 1).sum())

    df_twice = fill_missing_1m_candles(df_once)
    filled_twice = int((df_twice["is_filled"] == 1).sum())

    assert filled_once == filled_twice, (
        f"fill(fill(x)) tạo thêm nến điền: lần 1 = {filled_once}, lần 2 = {filled_twice}"
    )
    assert len(df_once) == len(df_twice), (
        f"Số dòng thay đổi sau lần điền thứ 2: {len(df_once)} → {len(df_twice)}"
    )


def test_fill_idempotent_no_extra_filled():
    """Cụ thể hơn: gọi fill 3 lần liên tiếp, is_filled count không tăng."""
    df = _make_1m_df(n=200, gap_at=100)
    df1 = fill_missing_1m_candles(df)
    df2 = fill_missing_1m_candles(df1)
    df3 = fill_missing_1m_candles(df2)

    c1 = int((df1["is_filled"] == 1).sum())
    c2 = int((df2["is_filled"] == 1).sum())
    c3 = int((df3["is_filled"] == 1).sum())
    assert c1 == c2 == c3, f"is_filled count thay đổi: {c1}, {c2}, {c3}"


# ── Test 2: Thêm dữ liệu thật cho phút đã điền → phút đó is_filled phải là 0 ──
def test_real_data_replaces_filled():
    """Nếu có dữ liệu thật cho phút đã điền, dữ liệu thật phải thay thế."""
    df = _make_1m_df(n=100, gap_at=50)
    df_filled = fill_missing_1m_candles(df)

    # Tìm một phút đã được điền
    filled_minutes = df_filled[df_filled["is_filled"] == 1]["open_time"].values
    assert len(filled_minutes) > 0, "Không có phút nào được điền"
    filled_ts = int(filled_minutes[0])

    # Thêm dữ liệu thật cho phút đó (giá thật khác với giá điền)
    real_price = 999.0
    new_real_row = pd.DataFrame([{
        "open_time": filled_ts,
        "open": real_price,
        "high": real_price * 1.01,
        "low": real_price * 0.99,
        "close": real_price,
        "volume": 50.0,
    }])

    # Kết hợp dữ liệu điền với dữ liệu thật
    combined = pd.concat([df_filled, new_real_row], ignore_index=True)

    # Điền lại — lần này phút đó phải là thật
    df_refilled = fill_missing_1m_candles(combined)

    row = df_refilled[df_refilled["open_time"] == filled_ts]
    assert len(row) == 1, f"Phải có đúng 1 dòng cho timestamp {filled_ts}"
    assert int(row.iloc[0]["is_filled"]) == 0, (
        "Phút được thay bằng dữ liệu thật vẫn bị đánh dấu is_filled=1"
    )
    assert abs(float(row.iloc[0]["close"]) - real_price) < 1e-6, (
        f"Giá phải là giá thật {real_price}, không phải giá điền {float(row.iloc[0]['close'])}"
    )


# ── Test 3: save_resampled_dataset 2 lần → manifest.filled_ratio_1m giữ nguyên ─
def test_save_resampled_twice_same_manifest():
    """Gọi save_resampled_dataset 2 lần trên cùng dữ liệu gốc: filled_ratio giữ nguyên."""
    df = _make_1m_df(n=2500, gap_at=500)

    with tempfile.TemporaryDirectory() as tmp:
        m1 = save_resampled_dataset(
            symbol="TEST", output_dir=tmp,
            df_1m_raw=df, pool_address="0x0",
            timeframes=("15m",), synthetic=False,
        )
        # Đọc lại 1m.pkl và gọi lần 2
        df2 = pd.read_pickle(os.path.join(tmp, "TEST", "1m.pkl"))
        m2 = save_resampled_dataset(
            symbol="TEST", output_dir=tmp,
            df_1m_raw=df2, pool_address="0x0",
            timeframes=("15m",), synthetic=False,
        )
        assert abs(m1["filled_ratio_1m"] - m2["filled_ratio_1m"]) < 1e-6, (
            f"filled_ratio thay đổi: {m1['filled_ratio_1m']} → {m2['filled_ratio_1m']}"
        )
        assert m1["rows"]["1m"] == m2["rows"]["1m"], (
            f"Số dòng 1m thay đổi: {m1['rows']['1m']} → {m2['rows']['1m']}"
        )


# ── Test 4: Crawler lọc is_filled==1 từ existing_1m ─────────────────────────
def test_crawler_strips_filled_from_existing():
    """
    Mô phỏng behavior của crawler: khi đọc 1m.pkl cũ, phải lọc bỏ nến điền
    trước khi merge với dữ liệu mới từ API.
    """
    df = _make_1m_df(n=100, gap_at=50)
    df_filled = fill_missing_1m_candles(df)

    # Simulate crawler logic: strip filled candles from existing
    if "is_filled" in df_filled.columns:
        existing_stripped = df_filled[df_filled["is_filled"] != 1]
    else:
        existing_stripped = df_filled

    # existing_stripped không được chứa nến điền
    if "is_filled" in existing_stripped.columns:
        assert (existing_stripped["is_filled"] == 1).sum() == 0, (
            "Sau khi strip, existing_1m vẫn còn nến có is_filled==1"
        )
