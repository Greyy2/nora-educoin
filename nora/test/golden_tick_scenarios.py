"""Kịch bản golden cho đường TICK (core/backtest/tick_run.py::run_tick, TickBook) — P9.4b T0.

Thị trường tick giả lấy từ test_tick_backtest.py (cùng hàm sinh nến/tick) + 20 cấu hình ngẫu nhiên có seed (pool volatile/stable, một/hai pool,
DCA, sizing theo rủi ro, gas, TP/SL, latency). Kết quả được CHUẨN HOÁ (float -> float.hex, bỏ meta không tất định) để so sánh bit-identical.
Snapshot: test/golden/tick_*.json, sinh bằng test/scripts/make_golden_tick.py; test: test/test_tick_golden.py.
"""
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List

import numpy as np

import test_tick_backtest as tt
from golden_scenarios import hx
from backend.crawl.store import save_resampled_dataset  # noqa: F401  (tt._asset dùng)

N_RANDOM = 20
VOLATILE_RB = (2e5, 1e6, 5e6)


def canon(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): canon(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    if isinstance(o, (bool, str)) or o is None:
        return o
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return hx(float(o))
    return str(o)


def canon_result(res: Dict[str, Any]) -> Dict[str, Any]:
    res = {k: v for k, v in res.items() if k != "meta"}      # wall_s / peak_rss_mb không tất định
    return canon(res)


@contextmanager
def tick_market(extra_candidates: List[Dict[str, Any]] = ()):
    """Gốc dữ liệu giả (thư mục tạm) + chiến lược t_long / t_cyc (như fixture `market` của test_tick_backtest) + `extra_candidates`."""
    from backend.optimize.book import build as sb
    from backend.alpha.compile import cond, f
    pos = {"exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 50, "stop_loss_rate": 2.0, "take_profit_rate": 2.0}
    base = [{"id": "t_long", "family": "x", "side": "LONG", "description": "luôn khớp", "tree": cond((f("15m", "close"), ">", 0)),
             "position": {**pos, "cooldown": 100_000}, "space": {}},
            {"id": "t_cyc", "family": "x", "side": "LONG", "description": "vào lại liên tục", "tree": cond((f("15m", "close"), ">", 0)),
             "position": {**pos, "cooldown": 15}, "space": {}}]
    old_c, old_e, old_env = sb.CANDIDATES, sb.EXTRA_CANDIDATES, os.environ.get("NORA_LOCAL_DATA_ROOT")
    with tempfile.TemporaryDirectory(prefix="nora_golden_tick_") as tmp:
        root = os.path.join(tmp, "data")
        os.makedirs(root)
        os.environ["NORA_LOCAL_DATA_ROOT"] = root
        sb.CANDIDATES, sb.EXTRA_CANDIDATES = base + list(extra_candidates), []
        try:
            yield __import__("pathlib").Path(root)
        finally:
            sb.CANDIDATES, sb.EXTRA_CANDIDATES = old_c, old_e
            if old_env is None:
                os.environ.pop("NORA_LOCAL_DATA_ROOT", None)
            else:
                os.environ["NORA_LOCAL_DATA_ROOT"] = old_env


def _run(items, symbols, root, ticks_by_name, pools=None, **kw):
    """ticks_by_name {tên: bảng tick}; pools {tên: {"stable":bool,"fee":float}} ghi đè metadata pool (mặc định volatile, phí tt.FEE)."""
    from backend.optimize.search.evaluate import run_tick
    from backend.core.params import RISK
    from backend.crawl.store import asset_meta
    from data_helpers import set_ticks_attrs
    for name, tk in ticks_by_name.items():
        d = tt._asset(root, name, ticks=tk)
        p = (pools or {}).get(name)
        if p:
            ticks_meta = {**asset_meta(str(d))["ticks"], "fee_rate": p["fee"], "stable": p["stable"]}
            set_ticks_attrs(str(d), ticks=ticks_meta, onchain={"pool_address": "0xpool", "fee_rate": p["fee"], "stable": p["stable"], "pool_type": "aerodrome_v2"})
    a = dict(start=None, end=None, rpt=0.5, risk=RISK, stop_fill="level", base_frame="15m", capital=tt.CAPITAL)
    a.update(kw)
    return run_tick(items, symbols, a.pop("start"), a.pop("end"), a.pop("rpt"), a.pop("risk"), a.pop("stop_fill"), a.pop("base_frame"), a.pop("capital"), **a)


# ─── kịch bản từ test_tick_backtest ──────────────────────────────────────────
def _fixed():
    """[(tên, hàm(root) -> kết quả thô)] — các thị trường tick giả của test_tick_backtest.py."""
    X = ["dex:XYZ"]
    shifted = tt.path_ticks([100.0, 100.0])
    shifted = shifted.assign(timestamp_ms=shifted.timestamp_ms + 7 * tt.MIN)
    return [
        ("tp_first", lambda r: _run([("t_long", {})], X, r, {"XYZ": tt.path_ticks([100.5, 101.0, 102.5, 97.0])})),
        ("sl_first", lambda r: _run([("t_long", {})], X, r, {"XYZ": tt.path_ticks([99.0, 98.5, 97.0, 102.5])})),
        ("entry_costs", lambda r: _run([("t_long", {})], X, r, {"XYZ": tt.path_ticks([100.0, 100.0])})),
        ("latency_45s", lambda r: _run([("t_long", {})], X, r, {"XYZ": tt.path_ticks([100.0, 100.0])}, latency_ms=45_000)),
        ("window_clamped", lambda r: _run([("t_long", {})], X, r, {"XYZ": shifted}, start=tt.W - 5 * tt.DAY, end=tt.W + 30 * tt.DAY)),
        ("cyc_random_walk", lambda r: _run([("t_cyc", {})], X, r, {"XYZ": tt._cyc_ticks()})),
        ("cyc_gas_latency", lambda r: _run([("t_cyc", {})], X, r, {"XYZ": tt._cyc_ticks()}, latency_ms=500, gas_usd=0.1)),
    ]


# ─── cấu hình ngẫu nhiên có seed ─────────────────────────────────────────────
def _random_ticks(rng, stable, rb, n, step_ms, vol):
    mid0 = 1.0 if stable else float(rng.choice([0.05, 1.0, 100.0, 2500.0]))
    mid = mid0 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    return tt.mk_ticks([(tt.W + k * step_ms, float(m)) for k, m in enumerate(mid)], rb=rb)


def random_config(seed: int) -> Dict[str, Any]:
    """Mô tả cấu hình (JSON thuần) — cũng được lưu trong snapshot để đọc."""
    rng = np.random.default_rng(9000 + seed)
    n_pools = 2 if seed % 5 == 4 else 1                                  # seed 4, 9, 14, 19: hai pool
    pools = []
    for i in range(n_pools):
        stable = bool(rng.random() < 0.35) if seed % 5 != 0 else False      # seed 0,5,10,15: ép volatile
        if seed in (1, 6, 11, 16):
            stable = True
        pools.append({"name": ["XYZ", "XY2"][i], "stable": stable, "fee": float(rng.choice([0.0005, 0.003, 0.01])),
                      "rb": float(rng.choice(VOLATILE_RB)), "n": int(rng.integers(300, 700)), "step_ms": int(rng.choice([60_000, 150_000, 300_000])),
                      "vol": float(rng.choice([0.0002, 0.0005]) if stable else rng.choice([0.002, 0.004, 0.008])), "seed": int(rng.integers(1 << 30))})
    sizing = str(rng.choice(["margin_pct", "risk"]))
    pos = {"exit_unit": "pct", "sizing": sizing, "order_size_pct": float(rng.choice([20, 50, 90])), "stop_loss_rate": float(rng.choice([0.5, 1.0, 2.0, 4.0])),
           "take_profit_rate": float(rng.choice([0.5, 1.0, 2.0, 5.0])), "cooldown": int(rng.choice([0, 15, 45]))}
    if sizing == "risk":
        pos.update(risk_per_trade_pct=float(rng.choice([0.5, 1.0, 2.0])), max_notional_pct=float(rng.choice([100.0, 300.0])))
    if rng.random() < 0.55:                                            # DCA
        k = int(rng.integers(1, 4))
        mults = [float(x) for x in rng.choice([1.0, 1.5, 2.0], k)]
        pos.update(dca_steps=[float(x) for x in np.cumsum(rng.choice([0.3, 0.6, 1.0], k))], dca_multipliers=mults,
                   order_size_pct=float(int(55 / (1 + sum(mults)))))          # ngân sách DCA (lệnh đầu + nhồi) phải <= 100% vốn
    return {"seed": seed, "pools": pools, "position": pos, "signal": str(rng.choice(["always", "up"])), "rpt": float(rng.choice([0.25, 0.5, 1.0])),
            "gas_usd": None if rng.random() < 0.5 else float(rng.choice([0.0, 0.02, 0.5])), "latency_ms": None if rng.random() < 0.6 else int(rng.choice([0, 500, 30_000])),
            "capital": float(rng.choice([5_000.0, 10_000.0, 50_000.0]))}


def run_random(cfg: Dict[str, Any]) -> Dict[str, Any]:
    from backend.alpha.compile import cond, f
    tree = cond((f("15m", "close"), ">", 0)) if cfg["signal"] == "always" else cond((f("15m", "close"), ">", f("15m", "close", 1)))
    cand = {"id": "t_rand", "family": "x", "side": "LONG", "description": "ngẫu nhiên", "tree": tree, "position": cfg["position"], "space": {}}
    if cfg["signal"] == "up":
        cand["stop"] = cond((f("15m", "close"), "<", f("15m", "close", 1)))
    with tick_market([cand]) as root:
        ticks = {p["name"]: _random_ticks(np.random.default_rng(p["seed"]), p["stable"], p["rb"], p["n"], p["step_ms"], p["vol"]) for p in cfg["pools"]}
        meta = {p["name"]: {"stable": p["stable"], "fee": p["fee"]} for p in cfg["pools"]}
        kw = {"rpt": cfg["rpt"], "capital": cfg["capital"]}
        if cfg["gas_usd"] is not None:
            kw["gas_usd"] = cfg["gas_usd"]
        if cfg["latency_ms"] is not None:
            kw["latency_ms"] = cfg["latency_ms"]
        return _run([("t_rand", {})], [f"dex:{p['name']}" for p in cfg["pools"]], root, ticks, pools=meta, **kw)


def all_scenarios():
    """Sinh (tên file, dict chuẩn hoá) cho mọi kịch bản. Mỗi kịch bản chạy trong thư mục tạm riêng."""
    for name, fn in _fixed():
        with tick_market() as root:
            yield f"tick_{name}", {"scenario": name, "result": canon_result(fn(root))}
    for s in range(N_RANDOM):
        cfg = random_config(s)
        yield f"tick_rand{s:02d}", {"scenario": f"rand{s:02d}", "config": canon(cfg), "result": canon_result(run_random(cfg))}
