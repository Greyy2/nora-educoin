# Đã chuyển khỏi test/ (P17 T1-B5c): script dựng sổ (build_strategy_book) đã gỡ; bản gốc ở tag pre-p17-research.
"""WFA danh mục + Monte Carlo ngày: số đo dùng chung, fold không chồng, không nhìn trước, tái lập, gate, validate_book.

Dữ liệu giả lập 3 tài sản perp 70 ngày (fixture `market` của test_strategy_book). Pool song song được thay bằng bản
chạy tuần tự trong tiến trình (seam `_pool_map`) để ghi lại job; test cuối chạy validate_book.main với pool thật.
"""
import pathlib
from backend.models.storage import alpha_run_dir, run_dir
import json
import numpy as np
import pytest
from backend.jobs import evaluate as pt
from backend.wfa import wfa as pw
from backend.wfa.wfa import generate_folds
from test_strategy_book import T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)


def test_script_aliases_still_point_to_shared_metrics():
    from backend.carlo.carlo import bootstrap_daily
    from backend.metrics.metrics import portfolio_metrics
    mod = _load_script("build_strategy_book")
    assert mod.metrics is portfolio_metrics and mod.bootstrap is bootstrap_daily
