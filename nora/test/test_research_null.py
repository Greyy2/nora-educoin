"""Bộ quét nghiên cứu phải KHÔNG tạo edge trên random walk (phép kiểm null).

Lỗi đã gặp: bộ quét lối "rải limit" cho +10–15 bps/lệnh trên random walk vì chọn trước lệnh "sẽ khớp"
(bỏ qua lệnh khớp sớm nhưng sắp lỗ). Sau khi sửa, kỳ vọng phải xấp xỉ −phí.
"""
import os
import sys

import numpy as np
import pytest

from backend.core.research import research_maker_scalp as R


def _random_walk(n=150_000, sub=20, seed=11):
    rng = np.random.default_rng(seed)
    steps = rng.standard_normal((n, sub)) * 0.0009 / np.sqrt(sub)
    lp = np.cumsum(steps.ravel()).reshape(n, sub) + np.log(100.0)
    prev = np.r_[np.log(100.0), lp[:-1, -1]]
    return (np.exp(prev), np.exp(np.maximum(lp.max(1), prev)), np.exp(np.minimum(lp.min(1), prev)), np.exp(lp[:, -1]))


@pytest.fixture(autouse=True)
def _small_grid(monkeypatch):
    monkeypatch.setattr(R, "OFFS", [0.7, 1.0])
    monkeypatch.setattr(R, "TTLS", [240])
    monkeypatch.setattr(R, "TPS", [1.0, 1.5])
    monkeypatch.setattr(R, "SLS", [3.0])
    monkeypatch.setattr(R, "TOS", [120])


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_limit_scalp_has_no_edge_on_random_walk(side):
    o, h, l, c = _random_walk()
    res = R._simulate(side, np.ones(len(c), bool), o, h, l, c, spacing=30)
    for cfg, (e, x, r) in res.items():
        _, r2 = R._no_overlap(e, x, r)
        assert len(r2) > 150
        mean_bps = r2.mean() * 1e4
        se_bps = r2.std(ddof=1) / np.sqrt(len(r2)) * 1e4
        # kỳ vọng thật = −phí (4–9 bps); không được dương có ý nghĩa
        assert mean_bps < 2 * se_bps, (cfg, mean_bps, se_bps)


def test_no_overlap_never_skips_an_earlier_pending_order_for_a_later_one():
    # sự kiện 0 không khớp (chiếm chỗ tới 50), sự kiện 10 khớp và thoát ở 30: phải bị bỏ vì còn lệnh chờ
    e = np.array([0, 10, 60])
    x = np.array([50, 30, 80])
    r = np.array([np.nan, 0.05, -0.01])
    kept_e, kept_r = R._no_overlap(e, x, r)
    assert kept_e.tolist() == [60] and kept_r.tolist() == [-0.01]
