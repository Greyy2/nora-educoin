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


_BASE_DATA_ROOT = os.environ["NORA_LOCAL_DATA_ROOT"]


@pytest.fixture(autouse=True)
def _restore_data_root():
    """Một số test gán thẳng os.environ[...]; luôn khôi phục để test sau không dùng thư mục đã bị xoá."""
    yield
    os.environ["NORA_LOCAL_DATA_ROOT"] = _BASE_DATA_ROOT
