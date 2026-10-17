"""Số đo bot live ở các trường hợp biên: 0 lệnh đóng, vị thế đang mở, dưới 2 ngày dữ liệu. Không mạng."""
from backend.nautilus import live as lv

DAY = 86_400_000


def _snap(series, trades=(), positions=(), fees=0.0123, capital=1000.0, equity=None):
    eq = series[-1]["equity"] if series else capital
    return {"capital": capital, "series": series, "trades": list(trades), "positions": list(positions), "pnl_pct": (eq - capital) / capital * 100,
            "pnl_usd": eq - capital, "fees_usd": fees, "equity": eq, "balance": capital, "unrealized": eq - capital}


def _trade(pnl, t0=0):
    return {"symbol": "BTC@perp", "strategy": "s", "side": "LONG", "enter_time": t0, "enter_price": 100.0, "close_time": t0 + 1000, "close_price": 101.0, "pnl": pnl,
            "status": "TP" if pnl > 0 else "SL", "close_reason": "x", "qty": 1.0, "notional": 100.0, "margin_usd": None, "avg_price": 100.0, "pnl_pct": pnl / 10,
            "fees_usd": 0.0, "funding_usd": 0.0, "layers": 1, "mae_pct": None, "leverage": None, "entry_equity": 1000.0}


def test_no_closed_trades_with_open_positions():
    series = [{"time": 1000 + i * 60_000, "equity": 1000.0 + i * 0.1, "equity_worst": 1000.0 + i * 0.1} for i in range(5)]
    m = lv.bot_metrics(_snap(series, positions=[{"symbol": "A"}] * 5), {"started_at": 1000})
    assert m["trades_closed"] == 0 and m["trades_open"] == 5 and m["trades"] == 0
    assert m["win_rate"] is None and m["reasons"]["win_rate"] == "Chưa có lệnh đóng"
    assert m["profit_factor"] is None and m["reasons"]["profit_factor"] == "Chưa có lệnh đóng"
    assert m["mdd_pct"] == 0.0                      # 0,00% là giá trị thật, không phải thiếu dữ liệu
    assert m["fees_usd"] == 0.0123                  # phí thật, không làm tròn mất


def test_sharpe_needs_two_days():
    series = [{"time": 1000 + i * 60_000, "equity": 1000.0 + i, "equity_worst": 1000.0 + i} for i in range(5)]
    m = lv.bot_metrics(_snap(series), {"started_at": 1000})
    assert m["sharpe"] is None and m["reasons"]["sharpe"] == "Cần ≥ 2 ngày dữ liệu"


def test_sharpe_value_after_days_and_trades():
    eqs = [1000.0, 1010.0, 1005.0, 1020.0, 1015.0]
    series = [{"time": i * DAY + 1000, "equity": e, "equity_worst": e} for i, e in enumerate(eqs)]
    m = lv.bot_metrics(_snap(series, trades=[_trade(5.0), _trade(-2.0, 5000)]), {"started_at": 0})
    assert m["sharpe"] is not None and m["reasons"]["sharpe"] is None
    assert m["trades_closed"] == 2 and m["win_rate"] == 50.0 and m["profit_factor"] is not None
    assert m["mdd_pct"] > 0


def test_all_wins_profit_factor_reason():
    series = [{"time": 1000, "equity": 1005.0, "equity_worst": 1005.0}]
    m = lv.bot_metrics(_snap(series, trades=[_trade(5.0)]), {"started_at": 0})
    assert m["win_rate"] == 100.0 and m["profit_factor"] is None and m["reasons"]["profit_factor"] == "Chưa có lệnh thua"
