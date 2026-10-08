"""P9.4b T6: kernel (SlotDriver, hai móc AMM trong kernel) == RefPositionTracker (bản đóng băng nhánh limit_taker / impact_fn của tracker) trên cấu hình ngẫu nhiên:
mọi nến so toàn bộ trạng thái + sổ vốn, vị thế đóng, lệnh (giá, phí, trượt giá, thanh khoản), trên cả ba biến thể móc (limit_taker + impact_fn / chỉ limit_taker / chỉ impact_fn),
pool volatile và stable, dự trữ đổi theo từng nến, LONG / SHORT, spot / perp, 3 đường giá trong nến (ohlc, adaptive, adverse_first)."""
import dataclasses
import math
import os
import random
from collections import Counter

import pytest

from backend.core.backtest import SlotDriver, PositionTracker
from backend.core.models import PositionType, Account
from reference_engine import RefAmmImpact, RefCapitalLedger, RefPositionTracker
from test_event_path_parity import _ATTRS, _hx, _make_config

N_CONFIGS = int(os.environ.get("NORA_AMM_CONFIGS", "45"))
_COV: Counter = Counter()
FEES = [0.0, 0.0003, 0.003, 0.01]


def _canon(obj):
    out = {}
    for f in dataclasses.fields(obj):
        if f.name in ("order_id", "result_id", "position_id"):
            continue
        v = getattr(obj, f.name)
        out[f.name] = _hx(v.name if hasattr(v, "name") and hasattr(v, "value") else v)
    return out


def _snap(a, led):
    return ([_hx(getattr(a, x)) for x in _ATTRS], [led.equity.hex(), led.reserved.hex(), led.peak.hex(), led.rejected, led.free().hex()])


def _amm_config(seed):
    cfg = _make_config(seed, 6)
    rng = random.Random(seed ^ 0x5EED)
    variant = seed % 3                      # 0 cả hai móc, 1 chỉ limit_taker, 2 chỉ impact_fn
    stable = rng.random() < 0.4
    fee = rng.choice(FEES)
    gas = rng.choice([0.0, 0.02, 0.5])
    slots = []
    for side, params in cfg["slots"]:
        if variant != 1:                    # có pool: phí taker = maker = phí pool (như TickBook)
            params = dataclasses.replace(params, fee_rate=fee, maker_fee_rate=fee)
        slots.append((side, params))
    cfg["slots"] = slots
    pools = []                              # pools[k][i] = (rb, rq, qu): dự trữ pool của slot k ở nến i (đi ngẫu nhiên)
    for k in range(len(slots)):
        rq = 10 ** rng.uniform(3.5, 7.0)
        rb = rq / 100.0 * math.exp(rng.gauss(0, 0.3))
        qu = rng.choice([1.0, 1.0, 0.5, 2.0])
        row = []
        for i in range(cfg["nbars"]):
            rb *= math.exp(rng.gauss(0, 0.003))
            rq *= math.exp(rng.gauss(0, 0.003))
            row.append((rb, rq, qu))
        pools.append(row)
    cfg.update(variant=variant, stable=stable, fee=fee, gas=gas, pools=pools)
    return cfg


def _run(kind, cfg):
    variant, stable, fee, gas = cfg["variant"], cfg["stable"], cfg["fee"], cfg["gas"]
    n_slots = len(cfg["slots"])
    ltaker = variant in (0, 1)
    pooled = variant in (0, 2)
    kinds = [PositionType.LONG if side == "LONG" else PositionType.SHORT for side, _ in cfg["slots"]]
    models = [RefAmmImpact(fee, stable, gas) if pooled else None for _ in range(n_slots)]
    if kind == "ref":
        led = RefCapitalLedger(cfg["initial"])
        actors = [RefPositionTracker(k, 7, f"S{k}", "f", params, kinds[k], initial_capital=cfg["initial"], ledger=led,
                                     limit_taker=ltaker, impact_fn=models[k]) for k, (_, params) in enumerate(cfg["slots"])]
    else:
        acct = Account(cfg["initial"])
        trackers = [PositionTracker(k, 7, f"S{k}", "f", params, kinds[k], initial_capital=cfg["initial"], ledger=acct)
                    for k, (_, params) in enumerate(cfg["slots"])]
        amm = [{"limit_taker": ltaker, **({"fee": fee, "stable": stable, "gas": gas} if pooled else {})} for _ in trackers]
        drv = SlotDriver(trackers, meta=[(tr.symbol, "") for tr in trackers], amm=amm)
        led, actors = drv.ledger, [drv[k] for k in range(n_slots)]
    trace, closed = [], []
    for i in range(cfg["nbars"]):
        for k, a in enumerate(actors):
            t, o, h, l, c = cfg["bars"][k][i]
            s = cfg["steps"][i][k]
            if pooled:
                rb, rq, qu = cfg["pools"][k][i]
                if kind == "ref":
                    models[k].set_state(rb, rq, qu)
                else:
                    drv.set_amm(k, rb, rq, qu)
            if i in cfg["funding"]:
                trace.append(("funding", k, i, _hx(a.apply_funding(cfg["funding"][i], o))))
            a.max_new_notional, a.max_new_risk, a.risk_scale = s["caps"]
            pos = a.on_bar(t, o, h, l, c, entry_signal=s["entry"], stop_signal=s["stop"], can_open=s["can_open"], vol=s["vol"], dca_gate=s["dca_gate"])
            a.max_new_notional = a.max_new_risk = float("inf")
            a.risk_scale = 1.0
            if pos is not None:
                closed.append(_canon(pos))
            trace.append((k, i, _snap(a, led), _canon(pos) if pos is not None else None, _hx(a.unrealized_pnl_usd(c)) if a.is_open else None))
        if cfg["kill_at"] == i:
            for k, a in enumerate(actors):
                a.pending_entry = False
                if pooled:
                    models[k] and models[k].set_state(*cfg["pools"][k][i]) if kind == "ref" else drv.set_amm(k, *cfg["pools"][k][i])
                pos = a.force_close(cfg["bars"][k][i][0], cfg["bars"][k][i][4], "Kill switch danh mục")
                if pos is not None:
                    closed.append(_canon(pos))
                trace.append(("kill", k, i, _snap(a, led), _canon(pos) if pos is not None else None))
    last = cfg["nbars"] - 1
    if cfg["close_at_end"]:
        for k, a in enumerate(actors[: max(1, n_slots - 1)]):
            if pooled:
                models[k] and models[k].set_state(*cfg["pools"][k][last]) if kind == "ref" else drv.set_amm(k, *cfg["pools"][k][last])
            pos = a.force_close(cfg["bars"][k][last][0], cfg["bars"][k][last][4])
            if pos is not None:
                closed.append(_canon(pos))
            trace.append(("end", k, _snap(a, led), _canon(pos) if pos is not None else None))
    final = [{"orders": [_canon(o) for o in a.orders], "position": _canon(a.position) if a.position is not None else None, "state": _snap(a, led)} for a in actors]
    return {"trace": trace, "final": final, "closed": closed}


def _first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            if isinstance(x, tuple) and isinstance(y, tuple):
                for j, (xj, yj) in enumerate(zip(x, y)):
                    if xj != yj:
                        if isinstance(xj, tuple) and len(xj) == 2 and isinstance(xj[0], list):
                            names = list(_ATTRS) + ["led.equity", "led.reserved", "led.peak", "led.rejected", "led.free"]
                            xs, ys = xj[0] + xj[1], yj[0] + yj[1]
                            return f"bước {i} (phần {j}): " + str({names[q]: (xs[q], ys[q]) for q in range(len(xs)) if xs[q] != ys[q]})
                        if isinstance(xj, dict) and isinstance(yj, dict):
                            return f"bước {i} (phần {j}): " + str({q: (xj[q], yj.get(q)) for q in xj if xj[q] != yj.get(q)})
                        return f"bước {i} (phần {j}): ref={xj!r} kernel={yj!r}"
            return f"bước {i}: ref={x!r} kernel={y!r}"
    return f"độ dài khác: ref={len(a)} kernel={len(b)}"


@pytest.mark.parametrize("chunk", range(3))
def test_kernel_amm_equals_frozen_tracker(chunk):
    ran = tries = 0
    want = N_CONFIGS // 3
    first = 880_000 + chunk * 10_000
    while ran < want:
        seed = first + tries
        tries += 1
        assert tries < want * 4, "quá nhiều cấu hình bị build_params từ chối"
        try:
            cfg = _amm_config(seed)
        except ValueError:
            continue
        ref, ker = _run("ref", cfg), _run("kernel", cfg)
        label = f"amm seed={seed} variant={cfg['variant']} stable={cfg['stable']}"
        assert ref["trace"] == ker["trace"], f"{label}: {_first_diff(ref['trace'], ker['trace'])}"
        assert ref["final"] == ker["final"], f"{label}: final khác"
        assert ref["closed"] == ker["closed"], f"{label}: vị thế đóng khác"
        _COV["configs"] += 1
        _COV[f"variant{cfg['variant']}"] += 1
        _COV["stable" if cfg["stable"] else "volatile"] += 1
        _COV["closed"] += len(ref["closed"])
        _COV["dca_layers"] += sum(1 for p in ref["closed"] if int(p["layers"]) > 1)
        for f in ref["final"]:
            for o in f["orders"]:
                _COV["taker_orders"] += o["liquidity"] == "taker"
                _COV["slip_orders"] += float.fromhex(o["slippage"]) > 0
                _COV["dca_taker"] += o["liquidity"] == "taker" and o["phase"] > 0 and o["order_type"] == "BUY"
        for p in ref["closed"]:
            _COV["reason." + p["close_reason"]] += 1
        ran += 1


def test_zz_amm_parity_coverage():
    if _COV["configs"] < N_CONFIGS:
        pytest.skip("chưa chạy đủ các nhóm (chạy cả file để kiểm phủ)")
    need = ["variant0", "variant1", "variant2", "stable", "volatile", "closed", "dca_layers", "taker_orders", "slip_orders",
            "reason.Take-profit (từ giá TB)", "reason.Stop-loss (từ giá TB)"]
    miss = [k for k in need if not _COV[k]]
    assert not miss, f"chưa phủ: {miss}; {dict(_COV)}"
