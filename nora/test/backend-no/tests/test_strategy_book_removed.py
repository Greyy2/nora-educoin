# Đã chuyển khỏi test/ (P17 T1-B5c): dựng sổ (build_strategy_book), write_book/testnet đã gỡ cùng kho tối ưu; bản gốc ở tag pre-p17-research.
"""Sổ chiến lược: tham số theo chiến lược (dùng chung mọi tài sản), xuất sổ + cấu hình testnet danh mục.

Dữ liệu giả lập 3 tài sản perp (không gọi mạng). Kiểm:
- chia giai đoạn đúng thứ tự (dev1 < dev2 < holdout), luồng A→B→C→D chạy hết và ghi báo cáo;
- MỌI tài sản dùng cùng một bộ tham số của chiến lược (không có tham số theo tài sản);
- sổ xuất ra mô tả đúng quy tắc khối lượng theo rủi ro + giới hạn danh mục đã mô phỏng.
"""
import pathlib
from backend.models.storage import alpha_run_dir
import importlib.util
import json
import numpy as np
import pandas as pd
import pytest
from data_helpers import save_synthetic


def test_book_pipeline_runs_all_stages_with_shared_params(market, monkeypatch, tmp_path):
    sb = _small_book(monkeypatch)
    mod = _load_script("build_strategy_book")
    w = mod.windows(sb.perp_symbols())
    assert w["start"] < w["dev1_end"] < w["dev2_end"] < w["end"]

    # cùng một bộ tham số chạy trên cả 3 tài sản: mọi tài sản đều có lệnh từ cùng chiến lược
    from backend.jobs.evaluate import BacktestJob
    m = mod.run_book(BacktestJob([("t_long", {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720})],
                                 (w["start"], w["dev2_end"]), "level", {"max_positions": 3, "kill_switch_dd_pct": 0}, 0.5))
    assert m["trades"] > 0 and set(m["by_symbol"]) == set(SYMS)

    out = tmp_path / "alphas"
    # bộ dữ liệu giả lập rất nhỏ: số RAM/worker mặc định (cỡ production) không phù hợp, đặt thấp để qua cổng RAM
    mod.run_job({"workers": 2, "per_worker_mb": 300, "n": 4, "out": str(out)})
    reports = sorted(pathlib.Path(alpha_run_dir("book")).glob("*/report.json"))
    assert reports, "phải ghi báo cáo"
    rep = json.loads(reports[-1].read_text())
    assert set(rep["candidates"]) == {"t_long", "t_short"}
    for c in rep["candidates"].values():
        for top in c["dev1_top"]:
            assert "dev2_level" in top and "dev2_extreme" in top
    if rep.get("book"):
        book = json.loads((out / "book.json").read_text())
        assert 0 < book["risk_per_trade_pct"] <= 2.0
        for s in book["strategies"]:
            assert s["position"]["exit_unit"] == "atr" and s["position"]["sizing"] == "risk"
            assert s["position"]["leverage"] <= 10
        # testnet/book.json chỉ có khi holdout đạt; book.json luôn có status tương ứng
        assert (out / "testnet" / "book.json").exists() == (rep["book"]["holdout_pass"] is True)
        assert book["status"] == ("READY_FOR_TESTNET" if rep["book"]["holdout_pass"] is True else "HOLDOUT_FAILED")


def test_book_export_describes_simulated_rules(tmp_path):
    from backend.strategies import build_book, testnet_book_config
    report = {
        "windows": {"start": "a", "dev1_end": "b", "dev2_end": "c", "end": "d"}, "gates": {},
        "candidates": {"trend_long": {"accepted": True}, "trend_short": {"accepted": False}},
        "book": {"strategies": [{"id": "trend_long", "params": {"sig.adx_min": 25, "stop_loss_rate": 2.5,
                                                                "trailing_stop": 3.0, "trailing_activation_pct": 1.0,
                                                                "timeout": 4320}}],
                 "risk_per_trade_pct": 0.75, "risk": {"max_positions": 8, "max_per_symbol": 1,
                                                       "max_gross_exposure": 3.0, "kill_switch_dd_pct": 30.0},
                 "risk_scale_bootstrap": {}, "dev2_base_risk": {}, "final": {}, "holdout_pass": True},
    }
    book = build_book(report, source="x")
    st = book["strategies"][0]
    assert st["position"]["risk_per_trade_pct"] == 0.75 and st["position"]["stop_loss_rate"] == 2.5
    assert st["signal_params"] == {"adx_min": 25}
    cond = json.dumps(st["flow"])
    assert '"param"' not in cond and "25" in cond                      # ngưỡng đã thay vào AST
    assert set(book["rejected_candidates"]) == {"trend_short"}
    cfg = testnet_book_config(book)
    assert cfg["kind"] == "portfolio_book" and cfg["portfolio_limits"]["kill_switch_dd_pct"] == 30.0
    assert "BTCUSDT" in cfg["symbols"] and cfg["sizing"]["risk_per_trade_pct_of_equity"] == 0.75
    assert cfg["strategies"][0]["exits_in_atr_multiples"]["stop_loss_rate"] == 2.5


def test_write_book_holdout_pass_writes_testnet(tmp_path):
    from backend.strategies import write_book
    paths = write_book(_book_report(True), str(tmp_path), source="x")
    assert len(paths) == 2 and (tmp_path / "testnet" / "book.json").exists()
    book = json.loads((tmp_path / "book.json").read_text())
    assert book["status"] == "READY_FOR_TESTNET" and book["holdout_pass"] is True


@pytest.mark.parametrize("hp", [False, "False", None])
def test_write_book_holdout_fail_no_testnet_and_removes_stale(tmp_path, capsys, hp):
    from backend.strategies import write_book
    (tmp_path / "testnet").mkdir()
    (tmp_path / "testnet" / "book.json").write_text("{}")             # file cũ từ lần trước
    paths = write_book(_book_report(hp), str(tmp_path), source="x")
    assert paths == [str(tmp_path / "book.json")]
    assert not (tmp_path / "testnet" / "book.json").exists()
    assert "đã xoá" in capsys.readouterr().out
    book = json.loads((tmp_path / "book.json").read_text())
    assert book["status"] == "HOLDOUT_FAILED" and book["holdout_pass"] is False
