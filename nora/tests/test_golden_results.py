"""Golden results: kết quả backtest phải BIT-IDENTICAL với snapshot trong tests/golden/*.json.

Dùng để chứng minh thay đổi hiệu năng (mmap dùng chung, bỏ qua phút rảnh...) không đổi kết quả.
Sinh lại snapshot CHỈ khi chủ đích đổi ngữ nghĩa:  scripts/run_limited.sh -- scripts/make_golden.py
"""
import json
import os

import pytest

import golden_scenarios as gs

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
REAL_ROOT = os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data")


def _load(name):
    path = os.path.join(GOLDEN_DIR, f"{name}.json")
    if not os.path.isfile(path):
        pytest.fail(f"Thiếu snapshot {path} — chạy scripts/make_golden.py")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _assert_identical(golden, fresh, name):
    if golden == fresh:
        return
    diffs = gs.diff_canonical(golden, fresh)
    pytest.fail(f"{name}: kết quả khác snapshot. Khác biệt đầu tiên:\n  " + "\n  ".join(diffs or ["(không xác định được)"]))


def test_golden_portfolio_synthetic(tmp_path):
    golden = _load("portfolio_synthetic")
    assert len(golden["positions"]) > 0
    _assert_identical(golden, gs.scenario_portfolio_synthetic(tmp_path / "data"), "portfolio_synthetic")


def test_golden_single_dca_filled(tmp_path):
    golden = _load("single_dca_filled")
    assert len(golden["positions"]) > 0
    _assert_identical(golden, gs.scenario_single_dca_filled(tmp_path / "data"), "single_dca_filled")


def test_golden_portfolio_real(monkeypatch):
    root = os.path.abspath(REAL_ROOT)
    if not gs.real_data_available(root):
        pytest.skip(f"Không có dữ liệu thật tại {root} (đặt NORA_GOLDEN_DATA_ROOT)")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", root)
    gs.clear_caches()
    golden = _load("portfolio_real")
    try:
        fresh = gs.scenario_portfolio_real(root)
    finally:
        gs.clear_caches()
    _assert_identical(golden, fresh, "portfolio_real")
