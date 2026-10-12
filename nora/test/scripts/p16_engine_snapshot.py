"""P16 baseline: băm kết quả của vài lần chạy DSL tất định (dữ liệu catalog thật, cửa sổ ngắn, khung 1h) để chứng minh refactor lõi Nautilus không đổi số.

  python test/scripts/p16_engine_snapshot.py --save test/fixtures/p16_engine_snapshot.json
  python test/scripts/p16_engine_snapshot.py --check test/fixtures/p16_engine_snapshot.json
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.pop("NORA_LOCAL_DATA_ROOT", None)

import numpy as np

from backend.alpha.compile import calc, cond, cross_over, f    # noqa: E402
from backend.alpha.plan import RiskConfig
from backend.signal.compute import _strategy_flow
import backend  # noqa: F401  (đăng ký EngineData mặc định)
from backend.models.params import build_params                  # noqa: E402
from backend.nautilus.engine import BacktestEngine, PortfolioEngine  # noqa: E402


def ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


BASE = {"market": "perp", "leverage": 5, "exit_unit": "pct", "sizing": "margin_pct", "order_size_pct": 20.0, "fee_rate": 0.0005,
        "maker_fee_rate": 0.0002, "slippage_rate": 0.0, "limit_through_pct": 0.0, "cooldown": 0, "atr_frame": "1h"}
OPEN_RISK = dict(kill_switch_dd_pct=0, max_gross_exposure=100, max_open_risk_pct=0, dd_throttle_pct=0)
A, B = "2024-03-01 00:00", "2024-03-12 00:00"
EXITS = {"stop_loss_rate": 1.0, "take_profit_rate": 1.2}
DCA = {"stop_loss_rate": 2.0, "take_profit_rate": 1.5, "dca_step_pct": 0.5, "dca_max_layers": 2, "dca_size_multiplier": 1.5, "order_size_pct": 10.0}


def strategies(pos, n=1, side="LONG"):
    return [{"id": f"s{i}", "side": side, "tree": cond((f("1h", "close"), ">", 0)), "position": {**BASE, **pos}} for i in range(n)]


def portfolio(syms, strats):
    return PortfolioEngine(list(syms), strats, ms(A) - 3600_000 * 24, ms(B), trade_start_ts=ms(A), risk=RiskConfig(**OPEN_RISK), base_frame="1h")


def _norm(res) -> dict:
    """Bỏ provenance; id vị thế / lệnh (next_id theo đồng hồ) thay bằng thứ tự xuất hiện để băm tất định."""
    from dataclasses import asdict
    body = {k: v for k, v in res.items() if k != "provenance"}
    pos = [asdict(p) for p in body["positions"]]
    orders = [asdict(o) for o in body["orders"]]
    rid = {p["result_id"]: i for i, p in enumerate(pos)}
    for i, p in enumerate(pos):
        p["result_id"] = i
    for i, o in enumerate(orders):
        o["order_id"], o["position_id"] = i, rid.get(o["position_id"], -1)
    body["positions"], body["orders"] = pos, orders
    return body


def digest(res) -> dict:
    body = _norm(res)
    h = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return {"sha256": h, "positions": len(res["positions"]), "orders": len(res["orders"]), "curve": len(res["equity_curve"]),
            "final_equity": res["final_equity"]}


def case_backtest_engine():
    eng = BacktestEngine(0, 0, "BTC@perp", ms(A) - 3600_000 * 24, ms(B), trade_start_ts=ms(A), base_frame="1h")
    st = strategies(EXITS)[0]
    eng.add_strategy_flow("LONG_x", build_params("LONG_x", _strategy_flow(st), "LONG", st["position"], "cex"))
    eng.load_data()
    eng.run()
    return digest(eng.get_results())


def case_portfolio_dca():
    pe = portfolio(("BTC@perp", "ETH@perp"), strategies(EXITS) + [{**strategies(DCA)[0], "id": "dca"}])
    pe.run()
    return digest(pe.get_results())


def case_run_many():
    pe = portfolio(("BTC@perp", "ETH@perp"), strategies(EXITS))
    pe.load_data()
    out = pe.run_many([{"stop_loss_rate": 0.8, "take_profit_rate": 1.0}, {"stop_loss_rate": 1.5, "take_profit_rate": 2.0}])
    return [digest(r) for r in out]


def collect() -> dict:
    return {"backtest_engine": case_backtest_engine(), "portfolio_dca": case_portfolio_dca(), "run_many": case_run_many()}


def case_signals() -> dict:
    syms = [
        "BTC@perp", "ETH@perp", "SOL@perp", "BNB@perp", "XRP@perp",
        "DOGE@perp", "ADA@perp", "AVAX@perp", "LINK@perp", "TRX@perp",
    ]
    frames = ["15m", "1h", "4h"]
    out = {}

    def _h(arr):
        if arr is None:
            return None
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()

    for fr in frames:
        kc_up = {**f(fr, "ema_20"), "add": calc(f(fr, "atr_14"), "*", 2.0)}
        tree_kema = cond(*cross_over(f(fr, "close"), kc_up))
        stop_kema = cond((f(fr, "close"), "<", f(fr, "ema_20")))

        tree_dca = cond((f(fr, "rsi_14"), "<", 30), (f(fr, "close"), "<", f(fr, "bbl_20_2")))
        dca_gate = cond((f(fr, "rsi_14"), "<", 40))

        s1 = {"id": "kema", "side": "LONG", "tree": tree_kema, "stop": [{"condition": stop_kema}], "position": {**BASE, **EXITS, "atr_frame": fr}}
        s2 = {"id": "dca", "side": "LONG", "tree": tree_dca, "dca": [{"condition": dca_gate}], "position": {**BASE, **DCA, "atr_frame": fr}}

        pe = PortfolioEngine(syms, [s1, s2], ms(A) - 86400000 * 24, ms(B), trade_start_ts=ms(A), risk=RiskConfig(**OPEN_RISK), base_frame=fr)
        pe.load_data()

        fr_res = {}
        for b in pe.books:
            sym = b["symbol"]
            entries_dict = {}
            for e in b["entries"]:
                entries_dict[e["strategy"]] = {
                    "match": _h(e["match"]),
                    "stop": _h(e["stop"]),
                    "vol": _h(e["vol"]),
                    "dca": _h(e["dca"]),
                }
            entries_dict["_t"] = _h(b["data"]["t"])
            fr_res[sym] = entries_dict
        out[fr] = fr_res
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--check")
    ap.add_argument("--signals", action="store_true")
    a = ap.parse_args()
    cur = case_signals() if a.signals else collect()
    if a.save:
        with open(a.save, "w") as fh:
            json.dump(cur, fh, indent=1, sort_keys=True)
        print("saved", a.save)
        return 0
    if a.check:
        with open(a.check) as fh:
            base = json.load(fh)
        if base == cur:
            print("IDENTICAL")
            return 0
        print("DIFFERENT")
        return 1
    print(json.dumps(cur, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

