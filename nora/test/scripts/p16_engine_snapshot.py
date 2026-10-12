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

from backend.alpha.compile import cond, f                      # noqa: E402
from backend.alpha.dsl.strategy import RiskConfig, _strategy_flow  # noqa: E402
import backend.optimize  # noqa: E402,F401  (đăng ký EngineData mặc định)
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--check")
    a = ap.parse_args()
    cur = collect()
    print(json.dumps(cur, indent=1, sort_keys=True))
    if a.save:
        with open(a.save, "w") as fh:
            json.dump(cur, fh, indent=1, sort_keys=True)
        print("saved", a.save)
    if a.check:
        with open(a.check) as fh:
            base = json.load(fh)
        if base == cur:
            print("IDENTICAL")
            return 0
        print("DIFFERENT")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
