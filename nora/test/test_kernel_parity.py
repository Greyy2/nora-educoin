"""Kernel numba (backend/core/backtest/kernel.py) phải cho kết quả BIT-IDENTICAL với vòng lặp Python đóng băng (test/reference_engine.py)
và với golden snapshot. Không có công tắc chạy / không có engine thứ hai: PortfolioEngine.run() / BacktestEngine.run() = kernel.

- Golden: 3 kịch bản (danh mục tổng hợp, đơn tài sản DEX có nến điền, danh mục dữ liệu thật + biến thể mmap) phải == snapshot.
- Ngẫu nhiên: >= 300 cấu hình danh mục (7 ứng viên của sổ + bot DCA kiểu OKX; mọi tham số vị thế, rủi ro danh mục, kill switch, symbols riêng,
  đóng/không đóng cuối dữ liệu, thị trường có khe hở/lệch đầu-cuối) + cấu hình đơn tài sản: so SO SÁNH TỪNG BIT (float.hex) mọi vị thế (mọi trường),
  lệnh (thứ tự + liên kết vị thế), đường vốn, vốn cuối, bộ đếm, thống kê theo chiến lược/tài sản, vị thế còn mở.
- Phủ: test cuối kiểm các nhánh (thanh lý, kill switch, DCA bị từ chối, risk-blocked, ruin...) thực sự được chạm tới (không "xanh rỗng").
Số cấu hình đổi bằng NORA_PARITY_CONFIGS (mặc định 330 ≈ 320 thực chạy + ~60 đơn tài sản). Mismatch -> sửa kernel, KHÔNG nới so sánh.
"""
import dataclasses
import os
import random

import numpy as np
import pandas as pd
import pytest

import golden_scenarios as gs
import reference_engine as ref
from backend.core.backtest import kernel as _kernel_io
from backend.core.backtest.engine import BacktestEngine
from backend.core.params.builder import build_params, dca_budget_check, resolve_costs
from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
from backend.core.data.resampler import save_resampled_dataset
from backend.core.strategy import book as sb
from backend.core.params.schema import StrategyParams

T0, M, DAY = gs.T0, gs.M, gs.DAY
N_CONFIGS = int(os.environ.get("NORA_PARITY_CONFIGS", "330"))   # ~97% chạy được (còn lại bị từ chối ở cả hai engine): >= 300 thực chạy
N_CHUNKS = 6
N_SINGLE = max(12, N_CONFIGS // 5)
_STATS = {"portfolio": 0, "single": 0}
_COV = {}


def _bump(key, n=1):
    _COV[key] = _COV.get(key, 0) + n


# ─── So sánh từng bit ───────────────────────────────────────────────────────
_ID_FIELDS = {"result_id", "order_id", "position_id"}


def hexify(v):
    """Đệ quy: float -> float.hex (so == chính xác từng bit, phân biệt -0.0), enum -> name; dataclass -> dict."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, np.integer)):
        return int(v) if not hasattr(v, "name") else v.name
    if isinstance(v, (float, np.floating)):
        return float(v).hex()
    if hasattr(v, "name") and hasattr(v, "value"):
        return v.name
    if dataclasses.is_dataclass(v):
        return {f.name: hexify(getattr(v, f.name)) for f in dataclasses.fields(v) if f.name not in _ID_FIELDS}
    if isinstance(v, dict):
        return {k: hexify(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [hexify(x) for x in v]
    return v


def full_canon(res):
    """Mọi thứ get_results() trả về, theo ĐÚNG thứ tự, trừ id (đã thay bằng chỉ số vị thế của lệnh)."""
    pos_index = {p.result_id: i for i, p in enumerate(res["positions"])}
    out = {}
    for key, val in res.items():
        if key == "positions":
            out[key] = [hexify(p) for p in val]
        elif key == "orders":
            out[key] = [{**hexify(o), "pos": pos_index.get(o.position_id, "?")} for o in val]
        else:
            out[key] = hexify(val)
    return out


def assert_bit_identical(a, b, label):
    ca, cb = full_canon(a), full_canon(b)
    if ca == cb:
        return
    for key in ca:
        if ca[key] != cb.get(key):
            if isinstance(ca[key], list) and isinstance(cb.get(key), list):
                if len(ca[key]) != len(cb[key]):
                    pytest.fail(f"{label}: {key} khác độ dài ref={len(ca[key])} kernel={len(cb[key])}")
                for i, (x, y) in enumerate(zip(ca[key], cb[key])):
                    if x != y:
                        diff = {k: (x[k], y.get(k)) for k in x if x[k] != y.get(k)} if isinstance(x, dict) else (x, y)
                        pytest.fail(f"{label}: {key}[{i}] khác: {diff}")
            pytest.fail(f"{label}: {key} khác: ref={ca[key]!r} kernel={cb.get(key)!r}")
    pytest.fail(f"{label}: khác khoá {set(ca) ^ set(cb)}")


def _tally(res, tag):
    for p in res["positions"]:
        _bump(f"{tag}.status.{p.status.name}")
        _bump(f"{tag}.reason.{p.close_reason}")
        _bump(f"{tag}.side.{p.pos_type.name}")
        if p.layers > 1:
            _bump(f"{tag}.dca_filled")
        if p.funding_usd:
            _bump(f"{tag}.funding")
        if p.status.name == "SL" and p.mae_pct < 0:
            _bump(f"{tag}.mae")
    for o in res["orders"]:
        _bump(f"{tag}.liq.{o.liquidity}")
    for k in ("rejected_for_capital", "rejected_for_risk", "risk_blocked_attempts", "skipped_no_vol", "dca_layers_rejected"):
        if res.get(k):
            _bump(f"{tag}.{k}")
    if res.get("halted_at"):
        _bump(f"{tag}.halted")
    if res.get("ruined_at"):
        _bump(f"{tag}.ruined")


# ─── Golden ─────────────────────────────────────────────────────────────────
def _golden(name):
    import json
    with open(os.path.join(os.path.dirname(__file__), "golden", f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_golden_portfolio_synthetic_via_kernel(tmp_path):
    golden = _golden("portfolio_synthetic")
    fresh = gs.scenario_portfolio_synthetic(tmp_path / "data")
    assert golden == fresh, gs.diff_canonical(golden, fresh)


def test_golden_single_dca_filled_via_kernel(tmp_path):
    golden = _golden("single_dca_filled")
    fresh = gs.scenario_single_dca_filled(tmp_path / "data")
    assert golden == fresh, gs.diff_canonical(golden, fresh)


@pytest.mark.parametrize("use_shared", [False, True])
def test_golden_portfolio_real_via_kernel(tmp_path, monkeypatch, use_shared):
    root = os.path.abspath(os.environ.get("NORA_GOLDEN_DATA_ROOT") or os.path.join(os.path.dirname(__file__), "..", "data"))
    if not gs.real_data_available(root):
        pytest.skip("không có dữ liệu thật")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", root)
    gs.clear_caches()
    try:
        fresh = gs.scenario_portfolio_real(root, shared_dir=str(tmp_path / "shared") if use_shared else None)
    finally:
        gs.clear_caches()
    golden = _golden("portfolio_real")
    assert golden == fresh, gs.diff_canonical(golden, fresh)


# ─── Dữ liệu tổng hợp ───────────────────────────────────────────────────────
def _write(root, name, df, vol_meta=None, k=0, funding=True):
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    end = int(df.open_time.max())
    save_resampled_dataset(symbol=name, output_dir=os.path.join(root, "cex"), df_1m_raw=df, pool_address="s", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=end, extra_meta=meta)
    save_resampled_dataset(symbol="perp", output_dir=os.path.join(root, "cex", name), df_1m_raw=df, pool_address="p", crawl_ok=True,
                           requested_start_ts=int(df.open_time.min()), requested_end_ts=end,
                           extra_meta={**meta, "exchange": "binance_usdm", "market": "perp"})
    if funding:
        ft = int(df.open_time.min()) + np.arange(1, 24 * 3) * 8 * 3_600_000
        pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0001 * (k + 1) * np.where(np.arange(len(ft)) % 3 == 0, -1, 1)}
                     ).to_pickle(os.path.join(root, "cex", name, "perp", "funding.pkl"))


DAYS = 34
SYMS_FULL = [("AAA", 0.0008), ("BBB", 0.0016), ("CCC", 0.0030), ("DDD", 0.0065)]


@pytest.fixture(scope="module")
def market_root(tmp_path_factory):
    """AAA..DDD đủ phút (34 ngày: cổng dữ liệu đòi >= 30) (vol tăng dần: DDD hay bị thanh lý) + GAP1/GAP2 (thủng phút, bắt đầu muộn/kết thúc sớm -> lưới không thẳng hàng)."""
    root = str(tmp_path_factory.mktemp("kmarket") / "data")
    for k, (sym, vol) in enumerate(SYMS_FULL):
        _write(root, sym, gs._series(DAYS, 100 + k, vol), k=k)
    for k, (sym, vol) in enumerate((("GAPA", 0.0012), ("GAPB", 0.0025))):
        df = gs._series(DAYS, 200 + k, vol)
        rng = np.random.default_rng(5 + k)
        keep = rng.random(len(df)) > 0.04
        keep[0] = keep[-1] = True
        df = df[keep].reset_index(drop=True)
        if k == 1:   # bắt đầu muộn 1,5 ngày, kết thúc sớm 1 ngày
            df = df[(df.open_time >= T0 + int(1.5 * DAY)) & (df.open_time <= T0 + (DAYS - 1) * DAY)].reset_index(drop=True)
        _write(root, sym, df, k=k + 4)
    # DEX spot có phút điền (is_filled=1) cho đơn tài sản
    n = DAYS * 1440
    rng = np.random.default_rng(77)
    r = rng.normal(0, 0.0025, n)
    r[1:] -= 0.1 * r[:-1]
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    full = pd.DataFrame({"open_time": T0 + np.arange(n, dtype=np.int64) * M, "open": o, "high": np.maximum(o, c) * 1.0008,
                         "low": np.minimum(o, c) * 0.9992, "close": c, "volume": 5.0})
    keep = rng.random(n) > 0.30
    keep[0] = keep[-1] = True
    save_resampled_dataset(symbol="DEXA", output_dir=os.path.join(root, "dex"), df_1m_raw=full[keep].reset_index(drop=True),
                           pool_address="0xdex", crawl_ok=True, requested_start_ts=T0, requested_end_ts=int(full.open_time.max()),
                           extra_meta={"venue": "dex", "pool_fee_rate": 0.003})
    return root


def _f(frame, column, index=0):
    return {"frame": frame, "column": column, "index": index}


# ─── Sinh cấu hình ──────────────────────────────────────────────────────────
def _rf(rng, lo, hi, nd=3):
    return round(rng.uniform(lo, hi), nd)


def rand_signal_params(rng, cand):
    """Tham số tín hiệu: chu kỳ nhỏ để tín hiệu bắn trong 34 ngày dữ liệu."""
    out = {}
    for key, spec in (cand.get("params_schema") or {}).items():
        if spec["group"] != "signal":
            continue
        name = key[4:]
        if spec["type"] == "choice":
            out[key] = rng.choice(spec["choices"])
        elif name in ("ema_fast",):
            out[key] = rng.randint(3, 12)
        elif name in ("ema_slow",):
            out[key] = rng.randint(14, 40)
        elif name == "dch_n":
            out[key] = rng.randint(4, 25)
        elif name == "adx_min":
            out[key] = rng.randint(8, 25)
        elif name == "adx_n":
            out[key] = rng.randint(5, 20)
        elif name == "roc_n":
            out[key] = rng.randint(3, 20)
        elif name == "roc_min":
            out[key] = _rf(rng, 0.3, 2.5, 2)
        elif name in ("rsi_lo",):
            out[key] = rng.randint(30, 48)
        elif name in ("rsi_hi",):
            out[key] = rng.randint(52, 70)
        elif name == "rsi_n":
            out[key] = rng.randint(3, 20)
        elif name == "bb_n":
            out[key] = rng.randint(8, 30)
        elif name == "bb_k":
            out[key] = _rf(rng, 0.8, 2.2, 1)
        elif name == "er_n":
            out[key] = rng.randint(5, 30)
        elif name == "er_max":
            out[key] = _rf(rng, 0.3, 0.9, 2)
        elif name == "ema_n":
            out[key] = rng.randint(5, 40)
        elif spec["type"] == "int":
            out[key] = rng.randint(int(spec["min"]), int(min(spec["max"], spec["min"] + 20)))
        else:
            out[key] = _rf(rng, spec["min"], spec["max"], 2)
    return out


def rand_position(rng, side, force_perp=False):
    """Bộ tham số vị thế ngẫu nhiên (mọi khoá POSITION_KEYS đáng kể). Trả dict ghi đè lên BASE_POSITION."""
    spot = (not force_perp) and side == "LONG" and rng.random() < 0.15
    p = {"market": "spot" if spot else "perp"}
    p["leverage"] = 1 if spot else rng.choice([1, 2, 3, 5, 10, 20, 50, 125])
    p["maintenance_margin_rate"] = rng.choice([0.002, 0.005, 0.01, 0.05])
    atr = rng.random() < 0.6
    p["exit_unit"] = "atr" if atr else "pct"
    p["atr_frame"] = rng.choice(["15m", "1h", "4h"])
    p["atr_period"] = rng.choice([7, 14, 21])
    scale = 1.0 if atr else 0.4
    p["stop_loss_rate"] = 0.0 if rng.random() < 0.15 else _rf(rng, 0.5, 4.0) * scale
    p["take_profit_rate"] = 0.0 if rng.random() < 0.45 else _rf(rng, 0.4, 5.0) * scale
    p["trailing_stop"] = 0.0 if rng.random() < 0.45 else _rf(rng, 0.5, 4.0) * scale
    p["trailing_activation_pct"] = 0.0 if rng.random() < 0.5 else _rf(rng, 0.2, 2.5) * scale
    p["timeout"] = rng.choice([0, 0, 45, 240, 1440, 4000])
    p["cooldown"] = rng.choice([0, 0, 15, 60, 600])
    p["stop_fill"] = rng.choice(["level", "extreme"])
    p["limit_through_pct"] = rng.choice([0.0, 0.0, _rf(rng, 0.02, 0.3)])   # lệnh limit phải đi qua mức (DCA / chốt lời)
    p["max_open_trades"] = rng.choice([1, 2, 45])
    p["sizing"] = "risk" if rng.random() < 0.55 else "margin_pct"
    if p["sizing"] == "risk" and p["stop_loss_rate"] <= 0:
        p["stop_loss_rate"] = _rf(rng, 0.5, 3.0) * scale
    p["risk_per_trade_pct"] = _rf(rng, 0.1, 3.0)
    p["max_notional_pct"] = rng.choice([50.0, 100.0, 300.0, 600.0])
    layers = rng.choice([0, 0, 1, 2, 3, 5])
    p["dca_max_layers"] = layers
    p["dca_step_pct"] = _rf(rng, 0.2, 2.5) * scale if layers else 0.0
    p["dca_size_multiplier"] = rng.choice([1.0, 1.3, 2.0, 3.0])
    p["order_size_pct"] = rng.choice([5.0, 20.0, 50.0, 100.0])
    p["fee_rate"] = rng.choice([None, None, 0.0, 0.0003, 0.001])
    p["maker_fee_rate"] = rng.choice([None, None, 0.0, 0.0001])
    p["slippage_rate"] = rng.choice([None, None, 0.0, 0.0005, 0.002])
    return p


def _fit_dca_budget(rng, p):
    """margin_pct + DCA: build_params từ chối cấu hình không vừa ngân sách -> hạ order_size_pct cho vừa (đa phần), thỉnh thoảng giữ nguyên để thử từ chối."""
    if p["sizing"] != "margin_pct" or not p["dca_max_layers"]:
        return
    market = p["market"]
    costs = resolve_costs("cex", market, p.get("fee_rate"), p.get("slippage_rate"), p.get("maker_fee_rate"))
    chk = dca_budget_check({**p, "dca_steps": []}, costs)
    if not chk["ok"]:
        p["order_size_pct"] = max(0.5, round(chk["max_order_size_pct"] * rng.choice([0.5, 0.9, 1.0]), 3) - 0.001)


def _stop_tree(rng, side):
    """Cây tín hiệu thoát (hoặc rỗng): kích hoạt lệnh thoát chờ (pending_exit)."""
    if rng.random() < 0.5:
        return []
    frame = rng.choice(["5m", "15m"])
    cmp, thr = (">", 60) if side == "LONG" else ("<", 40)
    return [{"condition": [[[_f(frame, "rsi_14"), cmp, thr]]]}]


def _dca_gate(rng):
    """Điều kiện dồn tầng DCA (hoặc rỗng = luôn được dồn): bật/tắt thường xuyên để kernel và bản tham chiếu đi qua mọi nhánh."""
    if rng.random() < 0.5:
        return []
    frame = rng.choice(["5m", "15m"])
    return [{"condition": [[[_f(frame, "rsi_14"), rng.choice(["<", ">"]), rng.randint(40, 60)]]]}]


def rand_strategies(rng, symbols):
    """1-3 chiến lược: ứng viên của sổ (7) hoặc bot DCA kiểu OKX; id khác nhau."""
    n = rng.choice([1, 1, 2, 3])
    cands = rng.sample(sb.CANDIDATES, min(n, len(sb.CANDIDATES)))
    out = []
    for i, cand in enumerate(cands):
        if rng.random() < 0.3:   # bot kiểu DCA
            side = cand["side"]
            thr = rng.randint(25, 45) if side == "LONG" else rng.randint(55, 75)
            tf = rng.choice(["1m", "5m", "15m"])
            tree = [[[_f(tf, "rsi_14"), "<" if side == "LONG" else ">", thr]]]
            stop = _stop_tree(rng, side)
            pos = {**sb.BASE_POSITION, **rand_position(rng, side)}
            _fit_dca_budget(rng, pos)
            st = {"id": f"bot{i}_{side.lower()}", "side": side, "tree": tree, "stop": stop, "position": pos, "dca": _dca_gate(rng)}
        else:
            params = rand_signal_params(rng, cand)
            pos = rand_position(rng, cand["side"], force_perp=cand["id"].startswith(("breakout",)) and False)
            _fit_dca_budget(rng, {**pos})
            full = {**sb.BASE_POSITION, **cand.get("position", {}), **pos}
            _fit_dca_budget(rng, full)
            st = sb.materialize(cand, params)
            st["position"] = full
            st.pop("signal_params", None)
        if len(symbols) > 1 and rng.random() < 0.15:
            st["symbols"] = rng.sample(symbols, rng.randint(1, len(symbols) - 1))
        out.append(st)
    return out


def rand_portfolio_config(seed, market_root):
    rng = random.Random(seed)
    gap = rng.random() < 0.3
    pool = ["GAPA@perp", "GAPB@perp", "AAA@perp", "CCC@perp"] if gap else [f"{s}@perp" for s, _ in SYMS_FULL]
    symbols = rng.sample(pool, rng.randint(2, len(pool)))
    start = T0 + rng.choice([0, 0, 1]) * DAY
    cfg = {
        "symbols": symbols, "strategies": rand_strategies(rng, symbols), "start": start, "end": T0 + rng.choice([DAYS - 2, DAYS]) * DAY,
        "trade_start": start + rng.choice([2, 4, 7]) * DAY,
        "capital": rng.choice([1_000.0, 10_000.0, 123_456.78]),
        "risk": RiskConfig(max_positions=rng.choice([1, 2, 3, 8]), max_per_symbol=rng.choice([1, 2]),
                           max_gross_exposure=rng.choice([0.3, 1.0, 3.0, 10.0]), kill_switch_dd_pct=rng.choice([0, 0, 3.0, 10.0, 30.0]),
                           max_open_risk_pct=rng.choice([0.0, 0.0, 0.5, 2.0]), dd_throttle_pct=rng.choice([0.0, 0.0, 2.0, 10.0]),
                           dd_throttle_floor=rng.choice([0.25, 0.5])),
        "close_at_end": rng.random() < 0.8,
    }
    return cfg


def _run_portfolio(cls, cfg):
    eng = cls(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
              initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=cfg["close_at_end"])
    eng.run()
    return eng


@pytest.mark.parametrize("chunk", range(N_CHUNKS))
def test_random_portfolio_configs_bit_identical(market_root, chunk):
    per = N_CONFIGS // N_CHUNKS + (1 if chunk < N_CONFIGS % N_CHUNKS else 0)
    skipped = ran = 0
    with gs.data_root_env(market_root):
        for j in range(per):
            seed = chunk * 10_000 + j
            cfg = rand_portfolio_config(seed, market_root)
            try:
                r = _run_portfolio(ref.RefPortfolioEngine, cfg)
            except ValueError:   # cấu hình bị từ chối (ngân sách DCA, ...): engine mới cũng phải từ chối giống hệt
                with pytest.raises(ValueError):
                    _run_portfolio(PortfolioEngine, cfg)
                skipped += 1
                continue
            n = _run_portfolio(PortfolioEngine, cfg)
            label = f"portfolio seed={seed}"
            assert_bit_identical(r.get_results(), n.get_results(), label)
            if not cfg["close_at_end"]:
                assert hexify(r.open_positions()) == hexify(n.open_positions()), f"{label}: open_positions"
                _bump("portfolio.open_at_end", len(n.open_positions()))
            assert hexify(r.last_close) == hexify(n.last_close), f"{label}: last_close"
            for br, bn in zip(r.books, n.books):
                for er, en in zip(br["entries"], bn["entries"]):
                    tr, tn = er["tracker"], en["tracker"]
                    for attr in ("qty", "avg", "margin_used", "fees_paid", "layer_count", "is_open", "pending_entry", "pending_exit",
                                 "last_close_time", "dca_rejected", "skipped_no_vol", "pos_leverage", "max_capital", "funding_paid"):
                        assert hexify(getattr(tr, attr)) == hexify(getattr(tn, attr)), f"{label}: tracker.{attr}"
            _tally(n.get_results(), "portfolio")
            ran += 1
    _STATS["portfolio"] += per
    assert ran >= per * 0.7, f"quá nhiều cấu hình bị từ chối ({skipped}/{per}) — test không đủ sức"
    _bump("portfolio.ran", ran)
    _bump("portfolio.rejected_configs", skipped)


# ─── Đơn tài sản ────────────────────────────────────────────────────────────
def _single_flows(rng, symbol, venue):
    flows = []
    n = rng.choice([1, 2, 3])
    for i in range(n):
        side = rng.choice(["LONG", "SHORT"]) if venue == "cex" else "LONG"
        tf = rng.choice(["1m", "5m", "15m"])
        thr = rng.randint(25, 48) if side == "LONG" else rng.randint(52, 75)
        tree = [[[_f(tf, "rsi_14"), "<" if side == "LONG" else ">", thr]]]
        stop = _stop_tree(rng, side)
        pos = rand_position(rng, side, force_perp=(venue == "cex" and side == "SHORT"))
        if venue == "dex":
            pos = {**pos, "market": "spot", "leverage": 1, "fee_rate": None, "slippage_rate": None, "maker_fee_rate": None}
        elif pos["market"] == "perp" and rng.random() < 0.2:
            pos["sizing"], pos["stop_loss_rate"] = "margin_pct", pos["stop_loss_rate"]
        _fit_dca_budget(rng, pos)
        flows.append((f"{side}_f{i}", {"match": [{"condition": tree}], "stop": stop, "dca": _dca_gate(rng)}, side, pos))
    return flows


def _exotic_params(rng, name, side):
    """StrategyParams dựng tay (đi đường cấu hình mà build_params không chạm): bước DCA/hệ số riêng từng tầng, max_capital_usage < 1."""
    layers = rng.choice([2, 3, 4])
    steps = [round(rng.uniform(0.3, 1.5), 2) for _ in range(layers)]
    mults = [round(rng.uniform(1.0, 2.5), 2) for _ in range(rng.choice([layers, layers - 1]))]
    tree = [[[_f("1m", "rsi_14"), "<" if side == "LONG" else ">", 40 if side == "LONG" else 60]]]
    return StrategyParams(
        name=name, market="perp", leverage=rng.choice([2, 5, 10]), fee_rate=0.0005, maker_fee_rate=rng.choice([None, 0.0002]),
        slippage_rate=0.0002, stop_loss_rate=_rf(rng, 2.0, 6.0), take_profit_rate=rng.choice([0.0, _rf(rng, 0.5, 2.0)]),
        trailing_stop=rng.choice([0.0, _rf(rng, 1.0, 3.0)]), timeout=rng.choice([0, 600]), order_size_pct=rng.choice([5.0, 10.0]),
        dca_steps=steps, dca_multipliers=mults, max_capital_usage=rng.choice([0.4, 0.8, 1.0]), max_open_trades=rng.choice([1, 45]),
        extra={"ast": {"type": side, "match": [{"condition": tree}], "stop": []}, "type": side})


def _run_single(cls, symbol, venue, flows, start, end, trade_start, capital, exotic):
    eng = cls(0, 0, symbol, start, end, trade_start_ts=trade_start, initial_capital=capital)
    for name, ast, side, pos in flows:
        eng.add_strategy_flow(name, build_params(name, ast, side, pos, venue, symbol=symbol))
    for name, params in exotic:
        eng.add_strategy_flow(name, params)
    eng.load_data()
    eng.run()
    return eng


@pytest.mark.parametrize("chunk", range(2))
def test_random_single_symbol_configs_bit_identical(market_root, chunk):
    per = N_SINGLE // 2 + (1 if chunk < N_SINGLE % 2 else 0)
    ran = 0
    with gs.data_root_env(market_root):
        for j in range(per):   # noqa
            seed = 500_000 + chunk * 10_000 + j
            rng = random.Random(seed)
            venue = "dex" if rng.random() < 0.25 else "cex"
            symbol = "DEXA" if venue == "dex" else rng.choice(["AAA@perp", "CCC@perp", "DDD@perp", "GAPA@perp", "GAPB@perp"])
            start = T0 + rng.choice([0, 1]) * DAY
            args = (symbol, venue, None, start, T0 + DAYS * DAY, start + rng.choice([-1, 2, 5]) * DAY, rng.choice([2_000.0, 10_000.0]), None)
            flows = _single_flows(rng, symbol, venue)
            exotic = [(f"LONG_x{j}", _exotic_params(rng, f"LONG_x{j}", "LONG"))] if venue == "cex" and rng.random() < 0.4 else []
            a = list(args)
            a[2], a[7] = flows, exotic
            try:
                r = _run_single(ref.RefBacktestEngine, *a)
            except ValueError:
                with pytest.raises(ValueError):
                    _run_single(BacktestEngine, *a)
                continue
            n = _run_single(BacktestEngine, *a)
            assert_bit_identical(r.get_results(), n.get_results(), f"single seed={seed} {symbol}")
            for tr, tn in zip(r.trackers, n.trackers):
                for attr in ("qty", "avg", "is_open", "dca_rejected", "skipped_no_vol", "layer_count"):
                    assert hexify(getattr(tr, attr)) == hexify(getattr(tn, attr)), f"single seed={seed}: tracker.{attr}"
            _tally({**n.get_results(), "positions": n.closed_positions, "orders": n.orders}, "single")
            ran += 1
    _STATS["single"] += per
    assert ran >= per * 0.6
    _bump("single.ran", ran)


# ─── Các đường phụ ──────────────────────────────────────────────────────────
def test_capacity_overflow_retry_is_transparent(market_root, monkeypatch):
    cfg = rand_portfolio_config(1, market_root)
    cfg["close_at_end"] = True
    with gs.data_root_env(market_root):
        base = _run_portfolio(PortfolioEngine, cfg).get_results()
        monkeypatch.setattr(_kernel_io, "_INIT_CAP_POS", 1)
        monkeypatch.setattr(_kernel_io, "_INIT_CAP_ORD", 2)
        small = _run_portfolio(PortfolioEngine, cfg).get_results()
    assert base["positions"], "cấu hình thử phải có lệnh"
    assert_bit_identical(base, small, "overflow-retry")


def test_run_many_equals_independent_runs(market_root):
    overrides = [{"stop_loss_rate": 1.5, "leverage": 5}, {"take_profit_rate": 2.0, "cooldown": 0, "stop_fill": "extreme"},
                 {"trailing_stop": 2.0, "dca_max_layers": 2, "dca_step_pct": 0.8, "order_size_pct": 10.0, "sizing": "margin_pct"}]
    cand = sb.BY_ID["trend_long"]
    st = sb.materialize(cand, {"sig.adx_min": 10, "sig.ema_fast": 5, "sig.ema_slow": 20, "sig.trend_tf": "1h", "sig.entry_tf": "15m",
                               "sig.dch_n": 8}, stop_loss_rate=2.0, take_profit_rate=1.0, trailing_stop=1.0)
    syms = ["AAA@perp", "BBB@perp", "CCC@perp"]
    with gs.data_root_env(market_root):
        eng = PortfolioEngine(syms, [st], T0, T0 + DAYS * DAY, trade_start_ts=T0 + 4 * DAY)
        many = eng.run_many(overrides)
        assert eng.closed_positions == [] and not eng.equity_curve, "run_many không được đổi trạng thái engine gốc"
        for ov, res in zip(overrides, many):
            indep = ref.RefPortfolioEngine(syms, [{**st, "position": {**st["position"], **ov}}], T0, T0 + DAYS * DAY,
                                           trade_start_ts=T0 + 4 * DAY)
            indep.run()
            assert_bit_identical(indep.get_results(), res, f"run_many {ov}")
        with pytest.raises(ValueError):
            eng.run_many([{"atr_frame": "4h"}])   # đổi cột tín hiệu ATR -> từ chối


def test_empty_after_halt_and_no_signal_paths(market_root):
    """Không có nến sau trade_start / không tín hiệu: chỉ có mẫu vốn; kết quả y hệt bản Python."""
    cand = sb.BY_ID["reversion_long"]
    st = sb.materialize(cand, {"sig.rsi_lo": 1, "sig.entry_tf": "5m"}, stop_loss_rate=1.5)
    with gs.data_root_env(market_root):
        cfg = {"symbols": ["AAA@perp", "BBB@perp"], "strategies": [st], "start": T0, "end": T0 + DAYS * DAY,
               "trade_start": T0 + 30 * DAY, "capital": 10_000.0, "risk": RiskConfig(), "close_at_end": True}
        r, n = _run_portfolio(ref.RefPortfolioEngine, cfg), _run_portfolio(PortfolioEngine, cfg)
    assert not n.get_results()["positions"] and n.get_results()["equity_curve"]
    assert_bit_identical(r.get_results(), n.get_results(), "no-trade")


def test_account_ruin_path(market_root):
    """Cháy tài khoản: ký quỹ 100% vốn, đòn bẩy 125, phí cao -> lỗ thanh lý (ký quỹ + phí vào + phí thoát) > vốn => vốn <= 0, ruined_at, không mở lệnh mới."""
    pos = {**sb.BASE_POSITION, "market": "perp", "leverage": 125, "sizing": "margin_pct", "order_size_pct": 100.0, "exit_unit": "pct",
           "stop_loss_rate": 0.0, "take_profit_rate": 0.0, "trailing_stop": 0.0, "timeout": 0, "cooldown": 0, "fee_rate": 0.003,
           "maker_fee_rate": 0.003, "slippage_rate": 0.0, "maintenance_margin_rate": 1e-9, "dca_max_layers": 0, "dca_step_pct": 0.0}   # mmr ~0: lỗ thanh lý = cả ký quỹ (+ 2 lần phí) > vốn
    strategies = [{"id": "yolo_long", "side": "LONG", "tree": [[[_f("1m", "rsi_14"), "<", 60]]], "stop": [], "position": pos},
                  {"id": "yolo_short", "side": "SHORT", "tree": [[[_f("1m", "rsi_14"), ">", 40]]], "stop": [], "position": pos}]
    cfg = {"symbols": ["DDD@perp", "CCC@perp"], "strategies": strategies, "start": T0, "end": T0 + DAYS * DAY, "trade_start": T0 + 3 * DAY,
           "capital": 1_000.0, "risk": RiskConfig(max_positions=8, max_per_symbol=2, max_gross_exposure=1000.0, kill_switch_dd_pct=0),
           "close_at_end": True}
    with gs.data_root_env(market_root):
        r, n = _run_portfolio(ref.RefPortfolioEngine, cfg), _run_portfolio(PortfolioEngine, cfg)
    res = n.get_results()
    assert res["ruined_at"] is not None and res["final_equity"] <= 0, "kịch bản phải làm cháy tài khoản"
    assert_bit_identical(r.get_results(), res, "ruin")
    _tally(res, "portfolio")


def test_zz_coverage_all_branches_exercised():
    """Test cuối: các nhánh hiếm phải thật sự được chạm tới trong các cấu hình ngẫu nhiên (chống 'xanh rỗng')."""
    if _STATS["portfolio"] < N_CONFIGS or _STATS["single"] < N_SINGLE:
        pytest.skip("chưa chạy đủ các cấu hình ngẫu nhiên (chạy cả file để kiểm phủ)")
    need = ["portfolio.status.TP", "portfolio.status.SL", "portfolio.status.LIQ", "portfolio.status.CANCEL", "portfolio.dca_filled",
            "portfolio.liq.maker", "portfolio.liq.taker", "portfolio.liq.liquidation", "portfolio.halted", "portfolio.rejected_for_risk",
            "portfolio.risk_blocked_attempts", "portfolio.rejected_for_capital", "portfolio.funding", "portfolio.side.SHORT",
            "portfolio.reason.Tín hiệu thoát (AST stop)", "portfolio.reason.Hết thời gian giữ lệnh", "portfolio.reason.Trailing stop",
            "portfolio.reason.Kill switch danh mục", "portfolio.open_at_end", "portfolio.skipped_no_vol", "portfolio.dca_layers_rejected",
            "portfolio.ruined",
            "single.status.TP", "single.status.SL", "single.dca_filled", "single.funding"]
    missing = [k for k in need if not _COV.get(k)]
    assert not missing, f"nhánh chưa được phủ bởi cấu hình ngẫu nhiên: {missing}; thống kê={dict(sorted(_COV.items()))}"
    print("COVERAGE", dict(sorted(_COV.items())))
