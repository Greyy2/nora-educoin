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

import backend  # noqa: F401  (đăng ký lười nguồn dữ liệu mặc định của engine: EngineData)


_BASE_DATA_ROOT = os.environ["NORA_LOCAL_DATA_ROOT"]


@pytest.fixture(autouse=True)
def _restore_data_root():
    """Một số test gán thẳng os.environ[...]; luôn khôi phục để test sau không dùng thư mục đã bị xoá."""
    yield
    os.environ["NORA_LOCAL_DATA_ROOT"] = _BASE_DATA_ROOT


@pytest.fixture(autouse=True)
def _legacy_candidates(monkeypatch):
    """Golden / parity / test cơ chế dùng 9 chiến lược cũ: đăng ký vào book.EXTRA_CANDIDATES (BY_ID tra được, danh mục API không đổi)."""
    from backend import strategies as sb
    from legacy_candidates import LEGACY
    monkeypatch.setattr(sb, "EXTRA_CANDIDATES", list(LEGACY))


@pytest.fixture(scope="module")
def synthetic_data():
    """Nguồn dữ liệu engine cho test dữ liệu GIẢ LẬP (pkl trong NORA_LOCAL_DATA_ROOT): nến thực thi từ chính kho giả lập + spec khai báo tường minh
    (data_helpers.SyntheticData). Dùng `pytestmark = pytest.mark.usefixtures("synthetic_data")`. Phạm vi module (các fixture dựng dữ liệu cấp module chạy engine ngay khi dựng). Khôi phục nhà máy mặc định (EngineData / catalog thật) sau module."""
    from backend.models.models import set_default_data_factory, set_default_data_source
    from backend import _engine_data_factory
    from data_helpers import SyntheticData
    set_default_data_source(SyntheticData())
    yield
    set_default_data_factory(_engine_data_factory)
