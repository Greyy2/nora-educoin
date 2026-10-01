"""
test_round3_completion.py — các mục còn lại sau review vòng 3.

Mỗi test tương ứng một lỗi đã được xác nhận khi review; test phải FAIL trên
commit 808d7f4 (baseline) và PASS sau khi sửa.

1. Luồng dữ liệu SẠCH phải chạy được end-to-end (gate không được chặn tất cả).
2. MC: source_wfa_id > source_handle > trades; không mượn gate bằng trades giả.
3. has_ticks fail-closed; tick ngắn không được thay chuỗi 1m dài.
4. Cache research phải hết hạn khi 1m/manifest thay đổi.
5. Sweep θ không chọn θ khi quá ít điểm để tách train/test.
6. Gate bắt buộc 4h; load_candle_df không tự dựng nến từ tick.
7. Không còn default 'SOL'; cấu hình WFA ở frontend khớp schema backend.
8. Crawler xoá checkpoint khi crawl thành công.
"""
import json
import os
import re
import tempfile
import time

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.core.resampler import save_resampled_dataset

D = 86_400_000
T0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC (neo ngày)
FRONTEND_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "src"))

FLOW_1M = {
    "id": "flow1",
    "name": "LONG close>open",
    "type": "LONG",
    "ast": {
        "type": "LONG",
        "match": [{"condition": [[[{"frame": "1m", "column": "close"}, ">", {"frame": "1m", "column": "open"}]]]}],
        "stop": [{"condition": [[[{"frame": "1m", "column": "close"}, "<", {"frame": "1m", "column": "open"}]]]}],
    },
}


def _rw_1m(n_days: int, seed: int = 7) -> pd.DataFrame:
    n = n_days * 1440
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 3e-4, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 3e-4, n)))
    return pd.DataFrame({
        "open_time": T0 + np.arange(n, dtype=np.int64) * 60_000,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.uniform(10, 100, n),
    })


@pytest.fixture
def clean_asset(tmp_path, monkeypatch):
    """Tài sản 40 ngày dữ liệu 'sạch' đi qua đúng đường crawler -> resampler -> manifest."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(root))
    sym = "CLEAN"
    df = _rw_1m(40)
    save_resampled_dataset(
        symbol=sym, output_dir=str(root), df_1m_raw=df, pool_address="0xclean",
        crawl_ok=True, requested_start_ts=int(df.open_time.min()), requested_end_ts=int(df.open_time.max()),
    )
    return sym, str(root)


def _wait_mc(job_id, timeout=30):
    from backend.studio_pipeline.jobs import get_mc_job
    t_end = time.time() + timeout
    while time.time() < t_end:
        job = get_mc_job(job_id)
        if job and job.get("status") in ("completed", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("MC job không kết thúc")


def _completed_wfa(trades, gate=True):
    from backend.studio_pipeline.jobs import complete_wfa_job, create_wfa_job
    job_id = create_wfa_job("CLEAN", "S", 4)
    complete_wfa_job(job_id, {
        "acceptance_gate_passed": gate, "aggregate_oos_trades": trades,
        "strategy_name": "S", "symbol": "CLEAN",
    })
    return job_id


def _small_trades(n=40):
    return [{"trade_id": str(i), "pnl_pct": 0.5 if i % 2 else -0.4} for i in range(n)]


# ─── 1. Dữ liệu sạch chạy được end-to-end ───────────────────────────────────

def test_gate_approves_clean_resampled_data(clean_asset):
    from backend.research.data_quality_gate import DataQualityStatus, evaluate_data_quality
    sym, root = clean_asset
    dq = evaluate_data_quality(sym, timeframe="1m", data_root=root)
    assert dq["status"] == DataQualityStatus.APPROVED, dq["issues"]


def test_simulate_accepts_clean_data(clean_asset):
    from backend.api.routers.studio import SimulateRequest, run_simulation
    sym, _ = clean_asset
    res = run_simulation(SimulateRequest(symbol=sym, start_ts=T0 + 6 * D, end_ts=T0 + 30 * D, flows=[FLOW_1M]))
    assert res["metrics"]["total_trades"] > 0


def test_wfa_then_mc_end_to_end_on_clean_data(clean_asset):
    from backend.api.routers.studio import run_monte_carlo_endpoint
    from backend.studio_pipeline.jobs import create_wfa_job, get_wfa_job
    from backend.studio_pipeline.schemas import MonteCarloRunRequest, StrategySnapshot, WfaFoldConfig
    from backend.studio_pipeline.wfa import execute_wfa_pipeline

    sym, _ = clean_asset
    snap = StrategySnapshot(name="E2E", symbol=sym, flows=[FLOW_1M], start_ts=T0 + 6 * D, end_ts=T0 + 39 * D)
    cfg = WfaFoldConfig(train_days=10, test_days=5, min_folds=3)
    job_id = create_wfa_job(sym, "E2E", 0)
    execute_wfa_pipeline(job_id, snap, cfg, "h")
    job = get_wfa_job(job_id)
    assert job["status"] == "completed", job.get("error")
    res = job["result"]

    assert res["generated_at"] > 10**12, "generated_at phải là ms"
    assert res["param_stability"] is None, "Không có grid -> param_stability phải None"
    folds = res["folds"]
    assert len(folds) >= 3
    for a, b in zip(folds, folds[1:]):
        assert b["test_start_ts"] >= a["test_end_ts"], "OOS chồng lấp"
    ids = [t["trade_id"] for t in res["aggregate_oos_trades"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 30

    mc = run_monte_carlo_endpoint(MonteCarloRunRequest(source_wfa_id=job_id, simulations=200, seed=3))
    mc_job = _wait_mc(mc["job_id"])
    assert mc_job["status"] == "completed", mc_job.get("error")
    assert mc_job["result"]["source_gate_passed"] is res["acceptance_gate_passed"]
    # OOS chỉ ~24 ngày (< 30 điểm ngày) -> basis=daily tự lùi về lệnh đã đóng, có ghi chú
    assert mc_job["result"]["trades_count"] == len(ids)
    assert mc_job["result"]["basis"] == "trades" and "basis_note" in mc_job["result"]["summary"]


# ─── 2. Monte Carlo: ưu tiên nguồn lệnh ─────────────────────────────────────

def test_mc_endpoint_ignores_client_trades_when_source_wfa_id():
    from backend.api.routers.studio import run_monte_carlo_endpoint
    from backend.studio_pipeline.schemas import MonteCarloRunRequest

    job_id = _completed_wfa(_small_trades(40), gate=True)
    fake = [{"trade_id": str(i), "pnl_pct": 50.0} for i in range(200)]
    resp = run_monte_carlo_endpoint(MonteCarloRunRequest(source_wfa_id=job_id, trades=fake, simulations=200, seed=1))
    assert resp["trades_count"] == 40, "Phải dùng lệnh của job WFA, không dùng trades client gửi"
    result = _wait_mc(resp["job_id"])["result"]
    assert result["trades_count"] == 40
    assert result["summary"]["max_terminal_equity"] < 10_000 * 2, "Kết quả đang dùng trades giả (+50%/lệnh)"
    assert result["source_gate_passed"] is True


@pytest.mark.parametrize("case", ["missing", "not_completed", "legacy_run", "missing_source"])
def test_mc_endpoint_rejects_invalid_sources(case):
    from backend.api.routers.studio import run_monte_carlo_endpoint
    from backend.studio_pipeline.jobs import create_wfa_job
    from backend.studio_pipeline.schemas import MonteCarloRunRequest

    trades = _small_trades(40)
    if case == "missing":
        req, code = MonteCarloRunRequest(source_wfa_id="wfa_job_khong_ton_tai", trades=trades), 404
    elif case == "not_completed":
        req, code = MonteCarloRunRequest(source_wfa_id=create_wfa_job("X", "S", 4), trades=trades), 409
    elif case == "legacy_run":
        req, code = MonteCarloRunRequest(source_handle="run_123", trades=trades), 400
    else:
        req, code = MonteCarloRunRequest(source_handle="bt_src_khong_ton_tai", trades=trades), 404
    with pytest.raises(HTTPException) as exc:
        run_monte_carlo_endpoint(req)
    assert exc.value.status_code == code


def test_mc_pipeline_never_falls_back_to_client_trades():
    from backend.studio_pipeline.jobs import create_mc_job, get_mc_job
    from backend.studio_pipeline.monte_carlo import execute_monte_carlo_pipeline
    from backend.studio_pipeline.schemas import MonteCarloRunRequest

    job_id = _completed_wfa([], gate=True)  # job WFA không có lệnh OOS
    mc_id = create_mc_job("X", "S", 200, source_wfa_id=job_id)
    execute_monte_carlo_pipeline(mc_id, MonteCarloRunRequest(source_wfa_id=job_id, simulations=200), _small_trades(40))
    assert get_mc_job(mc_id)["status"] == "failed"


# ─── 3. Tick thật: fail-closed và phải đủ độ phủ ────────────────────────────

def _write_ticks(sym_dir, start_ts, n=500, step_ms=60_000):
    pd.DataFrame({
        "timestamp_ms": start_ts + np.arange(n, dtype=np.int64) * step_ms,
        "price": 100.0 + np.sin(np.arange(n)),
        "amount": 1.0,
    }).to_parquet(os.path.join(sym_dir, "ticks.parquet"))


def test_has_ticks_requires_manifest_declaration(tmp_path):
    from backend.db.local_pkl import has_ticks
    sym_dir = tmp_path / "TK"
    sym_dir.mkdir()
    _write_ticks(str(sym_dir), T0)
    assert has_ticks("TK", data_root=str(tmp_path)) is False, "ticks.parquet không có manifest khai báo -> False"

    with open(sym_dir / "manifest.json", "w") as f:
        json.dump({"synthetic": False, "ticks": {"synthetic": False, "start_ts": T0, "end_ts": T0 + D}}, f)
    assert has_ticks("TK", data_root=str(tmp_path)) is True
    assert has_ticks("TK", data_root=str(tmp_path), min_days=30) is False


def test_short_real_ticks_do_not_replace_long_1m_path(clean_asset):
    from backend.research.market_analyzer import load_price_path
    sym, root = clean_asset
    sym_dir = os.path.join(root, sym)
    _write_ticks(sym_dir, T0 + 39 * D, n=1000, step_ms=60_000)  # ~0.7 ngày tick thật
    mpath = os.path.join(sym_dir, "manifest.json")
    m = json.load(open(mpath))
    m["ticks"] = {"source": "geckoterminal_trades", "synthetic": False, "start_ts": T0 + 39 * D, "end_ts": T0 + 39 * D + 999 * 60_000, "rows": 1000}
    json.dump(m, open(mpath, "w"))

    df, resolution = load_price_path(sym, data_root=root)
    assert resolution == "1m_close"
    assert len(df) > 50_000


# ─── 4. Cache research hết hạn khi dữ liệu đổi ──────────────────────────────

def test_research_cache_invalidated_when_data_newer(clean_asset):
    from backend.research.market_analyzer import analyze_market, get_cache_dir
    sym, root = clean_asset
    cache = os.path.join(get_cache_dir(root), f"{sym}_1h.json")
    fake = {"FAKE_CACHE": True, "behavior_event_profile": {"x": 1}, "backtest_simulation": {"cost_models": {"a": 1}}}
    with open(cache, "w") as f:
        json.dump(fake, f)

    # Cache mới hơn dữ liệu -> được dùng
    future = time.time() + 3600
    os.utime(cache, (future, future))
    assert analyze_market(sym, data_root=root).get("FAKE_CACHE") is True

    # Dữ liệu (manifest) mới hơn cache -> phải tính lại
    past = time.time() - 3600
    os.utime(cache, (past, past))
    assert analyze_market(sym, data_root=root).get("FAKE_CACHE") is None


# ─── 5. Sweep θ ─────────────────────────────────────────────────────────────

def test_sweep_does_not_pick_theta_without_train_test_split():
    from backend.research.dc_feature_extractor import sweep_directional_change
    rng = np.random.default_rng(1)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 80)))  # 80 điểm, biến động mạnh
    df = pd.DataFrame({"timestamp_ms": T0 + np.arange(80) * 60_000, "price": prices})
    out = sweep_directional_change(df, "X")
    assert out["best_theta"] is None
    assert sweep_directional_change(df.iloc[:10], "X")["best_theta"] is None


# ─── 6. Gate bắt buộc 4h; không dựng nến từ tick ────────────────────────────

def test_gate_blocks_when_4h_missing(clean_asset):
    from backend.research.data_quality_gate import DataQualityStatus, evaluate_data_quality
    sym, root = clean_asset
    os.remove(os.path.join(root, sym, "4h.pkl"))
    dq = evaluate_data_quality(sym, timeframe="1m", data_root=root)
    assert dq["status"] == DataQualityStatus.BLOCKED
    assert any("4h" in i for i in dq["issues"])


def test_load_candle_df_has_no_tick_fallback(tmp_path):
    from backend.db.tick_storage import load_candle_df
    sym_dir = tmp_path / "ONLYTICKS"
    sym_dir.mkdir()
    _write_ticks(str(sym_dir), T0, n=2000)
    assert load_candle_df("ONLYTICKS", "1h", data_root=str(tmp_path)).empty


# ─── 7. Không default 'SOL'; frontend khớp schema ───────────────────────────

def test_script_request_requires_symbol():
    from backend.api.routers.studio import ScriptSimulateRequest
    with pytest.raises(ValidationError):
        ScriptSimulateRequest(code="class S(Strategy): pass")


def _js_object_numbers(block: str) -> dict:
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)\s*,", block)}


@pytest.mark.parametrize("rel_path,anchor", [
    ("pages/Wfa.jsx", "const defaultConfig = () => ({"),
    ("components/StudioWfa.jsx", "const [config, setConfig] = useState({"),
])
def test_frontend_wfa_default_config_matches_backend_schema(rel_path, anchor):
    """Backend WfaFoldConfig là extra='forbid': frontend gửi field lạ sẽ bị 422."""
    from backend.studio_pipeline.schemas import WfaFoldConfig
    src = open(os.path.join(FRONTEND_SRC, rel_path), encoding="utf-8").read()
    start = src.index(anchor) + len(anchor)
    block = src[start:src.index("})", start)]
    cfg = _js_object_numbers(block)
    assert cfg, f"Không đọc được default config trong {rel_path}"
    WfaFoldConfig(**cfg)  # raise nếu có field lạ / sai kiểu


def test_no_hardcoded_sol_fallback_in_frontend():
    offenders = []
    for dirpath, _, files in os.walk(FRONTEND_SRC):
        for name in files:
            if name.endswith(".jsx") and not name.startswith("__"):
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                if re.search(r"\|\|\s*['\"]SOL['\"]|symbol:\s*['\"]SOL['\"]", text):
                    offenders.append(name)
    assert not offenders, f"Còn fallback 'SOL' cứng: {offenders}"


# ─── 8. Crawler xoá checkpoint khi thành công ───────────────────────────────

def test_crawler_removes_checkpoint_after_success(tmp_path, monkeypatch):
    import backend.crawler.crawl_geckoterminal_full_dataset as crawler
    asset_dir = tmp_path / "OKASSET"
    asset_dir.mkdir()
    ckpt = asset_dir / "1m_raw.partial.pkl"
    _rw_1m(1).to_pickle(ckpt)

    df = _rw_1m(1)
    monkeypatch.setattr(crawler, "_crawl_ohlcv", lambda *a, **k: (df, 3))

    class Args:
        currency, token = "usd", "base"

    manifest = crawler._process_asset(
        target={"asset": "OKASSET", "network": "base", "pool_address": "0xok", "name": "ok"},
        args=Args(), output_dir=str(tmp_path),
        start_sec=int(df.open_time.min()) // 1000, end_sec=int(df.open_time.max()) // 1000,
    )
    assert manifest and manifest["crawl_ok"] is True
    assert not ckpt.exists(), "Checkpoint thô phải bị xoá sau khi crawl + resample thành công"


def test_tests_never_touch_prod_db():
    """(Chuyển từ conftest.py: pytest không thu thập test trong conftest.)"""
    from backend.studio_pipeline import jobs
    assert jobs._get_db_path().startswith(tempfile.gettempdir())
