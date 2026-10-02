"""Golden results: kết quả backtest phải BIT-IDENTICAL với snapshot trong test/golden/*.json.

Dùng để chứng minh thay đổi hiệu năng (mmap dùng chung, bỏ qua phút rảnh...) không đổi kết quả.
Sinh lại snapshot CHỈ khi chủ đích đổi ngữ nghĩa:  backend/utils/ops/run_limited.sh -- test/make_golden.py
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
        pytest.fail(f"Thiếu snapshot {path} — chạy test/make_golden.py")
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


def _flip_last_hex_digit(h):
    """Đổi chữ số hex cuối của mantissa (sai lệch 1 ulp-cỡ-bit) — vẫn là chuỗi hex hợp lệ."""
    head, _, exp = h.partition("p")
    last = head[-1]
    return head[:-1] + ("0" if last != "0" else "1") + "p" + exp


def test_golden_comparison_detects_one_bit_perturbation():
    """Chứng minh bộ so sánh KHÔNG mù: đổi 1 chữ số hex cuối của real_pnl một vị thế -> báo khác biệt đúng vị thế + trường."""
    import copy
    golden = _load("portfolio_synthetic")
    fresh = copy.deepcopy(golden)
    k = len(fresh["positions"]) // 2
    pos = fresh["positions"][k]
    old = pos["real_pnl"]
    pos["real_pnl"] = _flip_last_hex_digit(old)
    assert pos["real_pnl"] != old and float.fromhex(pos["real_pnl"]) != float.fromhex(old)
    assert golden != fresh
    diffs = gs.diff_canonical(golden, fresh)
    assert diffs, "diff_canonical không thấy sai lệch"
    assert any(f"position #{k} " in d and "real_pnl" in d and pos["symbol"] in d for d in diffs), diffs
    with pytest.raises(pytest.fail.Exception, match=f"position #{k} .*real_pnl"):
        _assert_identical(golden, fresh, "perturbed")
