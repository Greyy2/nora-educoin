"""
conftest.py – Cô lập data root khi chạy test.

PHẢI đứng trước mọi import backend để biến môi trường có hiệu lực.
"""
import os
import tempfile

# ── Thiết lập môi trường cách ly TRƯỚC MỌI import backend ────────────────────
_TMP = tempfile.mkdtemp(prefix="nora_test_")
os.environ["NORA_LOCAL_DATA_ROOT"] = os.path.join(_TMP, "data")
os.makedirs(os.environ["NORA_LOCAL_DATA_ROOT"], exist_ok=True)
# Test nhỏ, và cũng được chạy dưới run_limited.sh ở CI/chạy tay: không bắt buộc trần cgroup cho script nặng.
os.environ.setdefault("NORA_ALLOW_UNLIMITED", "1")

import pytest  # noqa: E402

import backend.optimize  # noqa: E402,F401  (đăng ký lười nguồn dữ liệu mặc định của engine: EngineData)


_BASE_DATA_ROOT = os.environ["NORA_LOCAL_DATA_ROOT"]


@pytest.fixture(autouse=True)
def _restore_data_root():
    """Một số test gán thẳng os.environ[...]; luôn khôi phục để test sau không dùng thư mục đã bị xoá."""
    yield
    os.environ["NORA_LOCAL_DATA_ROOT"] = _BASE_DATA_ROOT


@pytest.fixture(autouse=True)
def _legacy_candidates(monkeypatch):
    """Golden / parity / test cơ chế dùng 9 chiến lược cũ: đăng ký vào book.EXTRA_CANDIDATES (BY_ID tra được, danh mục API không đổi)."""
    from backend.optimize.book import build as sb
    from legacy_candidates import LEGACY
    monkeypatch.setattr(sb, "EXTRA_CANDIDATES", list(LEGACY))
