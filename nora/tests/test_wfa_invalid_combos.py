"""
test_wfa_invalid_combos.py — G1: WFA bỏ qua combo grid không hợp lệ (vd. ngân sách DCA vượt vốn)

build_params raise ValueError khi DCA vượt trần vốn; _optimize_is phải bỏ qua combo đó (đếm vào
is_summary["invalid_combos"]) thay vì làm hỏng cả job. Tham số GỐC sai thì job vẫn fail với thông điệp rõ.
"""
import os
import tempfile

import numpy as np
import pandas as pd

import backend.studio_pipeline.wfa as wfa_mod
from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job, init_db
from backend.studio_pipeline.schemas import StrategySnapshot, WfaFoldConfig


def _run(snapshot_kwargs, monkeypatch):
    init_db()
    t0 = 1700000000000
    n = 50_400  # 35 ngày
    times = [t0 + i * 60_000 for i in range(n)]
    prices = list(np.random.default_rng(7).lognormal(0, 0.001, n).cumprod() * 100)
    captured = []
    orig = wfa_mod._optimize_is

    def spy(*a, **k):
        res = orig(*a, **k)
        captured.append(res[1])
        return res

    monkeypatch.setattr(wfa_mod, "_optimize_is", spy)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "DCASYM"), exist_ok=True)
        df = pd.DataFrame({
            "open_time": times, "open": prices, "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices], "close": prices, "volume": [10.0] * n,
        })
        from backend.core.resampler import save_resampled_dataset
        save_resampled_dataset(symbol="DCASYM", output_dir=tmp, df_1m_raw=df, pool_address="0xtest",
                               timeframes=("15m", "1h", "4h"), synthetic=False, crawl_ok=True)
        snapshot = StrategySnapshot(
            name="DcaGrid", symbol="DCASYM",
            flows=[{"id": "f1", "type": "LONG", "ast": {"type": "LONG", "nodes": []}}],
            **snapshot_kwargs,
        )
        cfg = WfaFoldConfig(train_days=5, test_days=2, fold_count=3)
        os.environ["NORA_LOCAL_DATA_ROOT"] = tmp
        job_id = create_wfa_job("DCASYM", "DcaGrid", 3)
        wfa_mod.execute_wfa_pipeline(job_id, snapshot, cfg, "test_h")
        return get_wfa_job(job_id), captured


def test_wfa_skips_invalid_dca_combo(monkeypatch):
    """Base hợp lệ (20% × 3 tầng), grid order_size_pct có 90% (vượt trần vốn) -> job hoàn tất, invalid_combos > 0."""
    job, summaries = _run(dict(order_size_pct=20.0, dca_max_layers=2, dca_step_pct=1.0,
                               param_grid={"order_size_pct": [20.0, 90.0]}), monkeypatch)
    assert job.get("status") == "completed", f"Job failed: {job.get('error')}"
    assert summaries and all(s["invalid_combos"] == 1 for s in summaries)


def test_wfa_all_combos_invalid_falls_back_with_note(monkeypatch):
    """Mọi combo đều vượt vốn nhưng tham số gốc hợp lệ -> fold NO_TRADE kèm note, job vẫn hoàn tất."""
    job, summaries = _run(dict(order_size_pct=20.0, dca_max_layers=2, dca_step_pct=1.0,
                               param_grid={"order_size_pct": [80.0, 90.0]}), monkeypatch)
    assert job.get("status") == "completed", f"Job failed: {job.get('error')}"
    assert all(s["invalid_combos"] == 2 and s["insufficient_is_trades"] and s.get("note") for s in summaries)
    assert all(f["status"] == "NO_TRADE" for f in job["result"]["folds"])


def test_wfa_invalid_base_params_still_fail(monkeypatch):
    """Tham số GỐC sai (DCA vượt vốn) và grid không sửa được -> job fail với thông điệp ngân sách DCA."""
    job, _ = _run(dict(order_size_pct=90.0, dca_max_layers=2, dca_step_pct=1.0,
                       param_grid={"stop_loss_rate": [0.01, 0.02]}), monkeypatch)
    assert job.get("status") == "failed"
    assert "ngân sách DCA" in str(job.get("error"))
