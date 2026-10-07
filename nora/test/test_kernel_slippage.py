"""P9.4b T2: lệnh của kernel mang `OrderModel.slippage` đúng định nghĩa của đường tracker (tỉ lệ trượt đã áp lên giá khớp, dương;
taker = slippage_rate, maker / thanh lý = 0) — so với các Fill (price, raw_price, slip) mà Python (PositionManager + SimVenue, bit-identical với PositionTracker) phát ra qua PaperBook.
Kernel không hỗ trợ impact_fn (AMM/DEX) nên trường hợp đó nằm ở test_tick_*; ở đây phủ taker, maker và thanh lý trên cấu hình danh mục ngẫu nhiên."""
import pytest

import golden_scenarios as gs
from backend.core.backtest.portfolio import PortfolioEngine
from backend.live.paper import PaperBook
from test_kernel_parity import market_root, rand_portfolio_config  # noqa: F401  (market_root là fixture)
from test_risk_engine import _risk_cfg
from test_runner_parity import _risk_dict, _run

_COV = {"configs": 0, "taker": 0, "maker": 0, "liq": 0, "slip_nonzero": 0, "exit": 0}


def _tracker_fills(events):
    out = []
    for e in events:
        if hasattr(e, "slip") and hasattr(e, "raw_price"):
            out.append((int(e.t), float(e.price).hex(), float(e.slip).hex(), float(e.raw_price).hex(), e.liquidity))
    return sorted(out)


def _kernel_orders(pe):
    res = pe.get_results()
    orders = list(res["orders"])
    for bk in pe.books:                                   # vị thế còn mở: lệnh nằm trong tracker
        for en in bk["entries"]:
            orders.extend(en["tracker"].orders)
    return orders


@pytest.mark.parametrize("chunk", range(3))
def test_kernel_order_slippage_equals_tracker(market_root, chunk):
    with gs.data_root_env(market_root):
        for j in range(8):
            seed = 900_000 + chunk * 100 + j
            cfg = _risk_cfg(seed, market_root) if j % 2 == 0 else {**rand_portfolio_config(seed, market_root), "close_at_end": False}
            pe = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                                 initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
            try:
                pe.run()
            except ValueError:
                continue
            if pe.get_results().get("ruined_at"):
                continue                                  # kernel dừng khi cháy tài khoản, PaperBook không mô hình hoá
            tk = _run(PaperBook(cfg["strategies"], pe.symbols, "1m", pe.initial_capital, _risk_dict(cfg["risk"]),
                                trade_start=cfg["trade_start"], record_events=True), pe)
            want = _tracker_fills(tk.events)
            orders = _kernel_orders(pe)
            got = sorted((int(o.order_time), float(o.order_price).hex(), float(o.slippage).hex(), None, o.liquidity) for o in orders)
            assert [(a, b, c, e) for a, b, c, _, e in want] == [(a, b, c, e) for a, b, c, _, e in got], f"seed={seed}"
            for o in orders:
                _COV["taker"] += o.liquidity == "taker"
                _COV["maker"] += o.liquidity == "maker"
                _COV["liq"] += o.liquidity == "liquidation"
                _COV["slip_nonzero"] += o.slippage != 0.0
                assert (o.slippage == 0.0) == (o.liquidity != "taker") or o.slippage == 0.0   # maker / thanh lý luôn 0
            _COV["configs"] += 1


def test_zz_coverage():
    assert _COV["configs"] >= 8, _COV
    assert _COV["taker"] > 0 and _COV["maker"] > 0 and _COV["liq"] > 0 and _COV["slip_nonzero"] > 0, _COV
