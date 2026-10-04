"""Payload Danh mục (backend/core/analytics/dashboard.py + GET /api/studio/portfolio/dashboard) trên đường vốn/lệnh giả lập.

Chuỗi NAV dựng từ lợi suất ngày đã biết nên các số (drawdown, VaR, bảng tháng, cắt kỳ) kiểm được bằng tay.
"""
import hashlib
import json
import math
import os
import time

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.analytics import feeds
from backend.core.analytics import dashboard as pdash
from backend.api.routers import portfolio as portfolio_router
from backend.api.jobs import batch as batch_jobs

INIT = 10_000.0
DAY = 86_400_000


def _ms(date, hour=0):
    return int(pd.Timestamp(date, tz="UTC").value // 1_000_000) + hour * 3_600_000


def make_result(returns, start="2025-01-01", trades=None, halted_at=None, rejected=0, kill_pct=30.0, attempts=None):
    """Đường vốn từ lợi suất ngày: mỗi ngày 2 mẫu (12h thấp hơn 0,1%, 23h = NAV cuối ngày) -> test lấy 'mẫu cuối ngày'."""
    nav, rows, prev = [], [], INIT
    for i, r in enumerate(returns):
        d = (pd.Timestamp(start) + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        cur = prev * (1 + r)
        rows.append({"time": _ms(d, 12), "equity": round(min(prev, cur) * 0.999, 4), "equity_worst": round(min(prev, cur) * 0.995, 4)})
        rows.append({"time": _ms(d, 23), "equity": round(cur, 4), "equity_worst": round(cur * 0.999, 4)})
        nav.append(cur)
        prev = cur
    end_ms = _ms(start) + len(returns) * DAY
    return {
        "equity_curve": rows, "trade_list": trades or [], "halted_at": halted_at, "rejected_for_risk": rejected,
        **({} if attempts is None else {"risk_blocked_attempts": attempts}),
        "config": {"strategies": [{"id": "trend_long", "params": {}}, {"id": "trend_short", "params": {}}],
                   "symbols": ["BTC@perp", "SOL@perp"], "start": _ms(start), "end": end_ms, "initial_capital": INIT,
                   "risk": {"kill_switch_dd_pct": kill_pct, "max_positions": 8, "max_per_symbol": 1, "max_gross_exposure": 3.0}},
        "final_equity": nav[-1],
    }, nav


def _trade(strategy, side, notional, pnl, enter, close, reason="Stop Loss"):
    return {"symbol": "BTC@perp", "strategy": strategy, "side": side, "enter_time": enter, "enter_price": 100.0, "close_time": close,
            "close_price": 101.0, "pnl": pnl, "status": "TP", "close_reason": reason, "qty": notional / 100.0, "notional": notional,
            "margin_usd": notional / 10}


TOP_KEYS = {"available", "source", "period", "kpis", "series", "distribution", "monthly", "risk", "strategies", "events", "positions", "stats", "mdd",
            "strategy_stats"}
KPI_KEYS = {"nav", "nav_change_day", "nav_change_day_pct", "pnl_today", "pnl_month", "pnl_year", "ret_period_pct", "bench_ret_period_pct",
            "excess_pct", "sharpe", "sortino", "calmar", "mdd_pct", "dd_now_pct", "var95_1d", "var95_pct", "cvar95_1d",
            "spark_nav", "spark_ret", "spark_dd"}
SERIES_KEYS = {"dates", "nav", "bench", "drawdown_pct", "daily_pnl", "rolling_sharpe_63"}
RISK_KEYS = {"margin_used_pct", "exposure_gross_pct", "exposure_net_pct", "by_market", "cagr_pct", "vol_annual_pct", "win_days_pct", "active_days",
             "profit_factor", "open_positions", "strategies_running"}
STRAT_KEYS = {"id", "side", "status", "weight_pct", "pnl", "contribution_pct", "sharpe", "mdd_pct", "pnl_30d"}


def _rng_returns(n, seed=1):
    return list(np.random.default_rng(seed).normal(0.0008, 0.01, n))


def _bench(start="2024-12-01", days=200, seed=5):
    idx = pd.date_range(start, periods=days, freq="D")
    return pd.Series(100 * np.cumprod(1 + np.random.default_rng(seed).normal(0, 0.02, days)), index=idx)


# ─── Đủ khoá, độ dài khớp ───────────────────────────────────────────────────
@pytest.mark.parametrize("period", pdash.PERIODS)
def test_payload_has_every_key_and_aligned_series(period):
    trades = [_trade("trend_long", "LONG", 5000, 120.0, _ms("2025-02-01"), _ms("2025-02-03")),
              _trade("trend_short", "SHORT", 3000, -40.0, _ms("2025-02-05"), _ms("2025-02-06")),
              _trade("trend_long", "LONG", 4000, 15.0, _ms("2025-04-05"), _ms("2025-04-10", 23), "End of Backtest")]
    res, _ = make_result(_rng_returns(100), trades=trades, halted_at=_ms("2025-04-05"), rejected=700, attempts=7)
    p = pdash.build_dashboard(res, _bench(), period, job_id="j1", label="L")
    assert set(p) == TOP_KEYS and p["available"] is True and p["period"] == period
    assert set(p["kpis"]) == KPI_KEYS and set(p["series"]) == SERIES_KEYS and set(p["risk"]) == RISK_KEYS
    n = len(p["series"]["dates"])
    assert n > 0 and all(len(p["series"][k]) == n for k in SERIES_KEYS)
    assert all(s <= 0 for s in p["series"]["drawdown_pct"]) and p["kpis"]["mdd_pct"] == min(p["series"]["drawdown_pct"])
    assert {"bins", "var95_pct"} == set(p["distribution"]) and 15 <= len(p["distribution"]["bins"]) <= 30
    assert sum(b["count"] for b in p["distribution"]["bins"]) == n
    assert p["distribution"]["var95_pct"] == -p["kpis"]["var95_pct"]
    assert all(set(s) == STRAT_KEYS for s in p["strategies"]) and {s["id"] for s in p["strategies"]} == {"trend_long", "trend_short"}
    assert set(p["source"]) == {"kind", "job_id", "label", "start", "end", "strategies", "symbols", "benchmark"}
    assert p["source"]["start"] == "2025-01-01" and p["source"]["end"] == "2025-04-10" and p["source"]["job_id"] == "j1"
    assert [e["level"] for e in p["events"] if e["level"] == "crit"]            # kill switch
    assert any(e["text"].startswith("7 lần vào lệnh bị chặn") for e in p["events"])   # lệnh bị chặn vì rủi ro
    json.dumps(p, allow_nan=False)                                               # không có NaN/inf


def test_risk_block_event_counts_attempts_not_minutes():
    res, _ = make_result(_rng_returns(30), rejected=1234, attempts=7)
    texts = [e["text"] for e in pdash.build_dashboard(res, None, "ALL")["events"]]
    assert ("7 lần vào lệnh bị chặn do giới hạn rủi ro danh mục (tối đa 8 vị thế / 1 mỗi tài sản / trần exposure 3× vốn)") in texts
    assert not any("1234" in t for t in texts)                                   # không phơi số phút thô


def test_risk_block_event_absent_when_no_attempts_and_hedged_for_old_results():
    res, _ = make_result(_rng_returns(30), rejected=0, attempts=0)
    assert not any("chặn" in e["text"] for e in pdash.build_dashboard(res, None, "ALL")["events"])
    old, _ = make_result(_rng_returns(30), rejected=55)                           # kết quả cũ: chỉ có số phút
    texts = [e["text"] for e in pdash.build_dashboard(old, None, "ALL")["events"]]
    assert any("chặn do giới hạn rủi ro" in t and "55" not in t for t in texts)


# ─── Giá trị biết trước ─────────────────────────────────────────────────────
def test_drawdown_and_nav_known_values():
    r = [0.02, -0.01, -0.02, 0.03]
    res, nav = make_result(r)
    p = pdash.build_dashboard(res, None, "ALL")
    assert p["series"]["nav"] == [round(x, 2) for x in nav]          # lấy mẫu CUỐI ngày (23h), không phải mẫu 12h
    assert p["series"]["bench"] == [None] * 4                        # không có benchmark
    assert nav[0] == pytest.approx(10200.0) and nav[2] == pytest.approx(9896.04)
    assert p["series"]["drawdown_pct"][0] == 0.0
    assert p["series"]["drawdown_pct"][1] == pytest.approx(-1.0, abs=0.005)
    assert p["kpis"]["mdd_pct"] == pytest.approx((9896.04 / 10200 - 1) * 100, abs=0.005)       # -2.98
    assert p["kpis"]["dd_now_pct"] == pytest.approx((nav[3] / 10200 - 1) * 100, abs=0.005)    # chưa hồi lại đỉnh 10200
    assert p["kpis"]["ret_period_pct"] == pytest.approx((nav[3] / INIT - 1) * 100, abs=0.005)
    assert p["series"]["daily_pnl"] == [round(nav[0] - INIT, 2)] + [round(b - a, 2) for a, b in zip(nav, nav[1:])]
    assert p["kpis"]["pnl_today"] == round(nav[3] - nav[2], 2) and p["kpis"]["nav_change_day"] == p["kpis"]["pnl_today"]
    assert p["series"]["rolling_sharpe_63"] == [None] * 4


def test_win_days_counts_only_days_with_pnl():
    r = [0.02, 0.0, 0.0, -0.01, 0.0, 0.01, 0.0, 0.0]      # 3 ngày có lãi/lỗ (2 lãi, 1 lỗ), 5 ngày đứng ngoài thị trường
    res, _ = make_result(r)
    risk = pdash.build_dashboard(res, None, "ALL")["risk"]
    assert risk["active_days"] == 3 and risk["win_days_pct"] == pytest.approx(66.7, abs=0.05)
    flat, _ = make_result([0.0] * 5)
    risk = pdash.build_dashboard(flat, None, "ALL")["risk"]
    assert risk["active_days"] == 0 and risk["win_days_pct"] is None


def test_var_cvar_sharpe_known_values():
    r = [-0.03, -0.02] + [0.001] * 19                                  # n=21: phân vị 5% rơi đúng phần tử thứ 2
    res, nav = make_result(r)
    k = pdash.build_dashboard(res, None, "ALL")["kpis"]
    assert k["var95_pct"] == 2.0 and k["cvar95_1d"] == pytest.approx(0.025 * nav[-1], abs=0.01)
    assert k["var95_1d"] == pytest.approx(0.02 * nav[-1], abs=0.01)
    arr = np.asarray(r)
    assert k["sharpe"] == pytest.approx(arr.mean() / arr.std(ddof=1) * math.sqrt(365), abs=0.01)
    dd = math.sqrt(np.mean(np.minimum(arr, 0) ** 2))
    assert k["sortino"] == pytest.approx(arr.mean() / dd * math.sqrt(365), abs=0.01)
    cagr = (nav[-1] / INIT) ** (365 / 21) - 1
    mdd = abs(k["mdd_pct"]) / 100
    assert k["calmar"] == pytest.approx(cagr / mdd, rel=0.01)


def test_monthly_table_known_values():
    anchors = {"2024-12-31": INIT, "2025-01-31": 10_500.0, "2025-02-28": 10_290.0, "2025-03-31": 10_804.5}
    days = pd.date_range("2025-01-01", "2025-03-31")
    s = pd.Series(anchors); s.index = pd.to_datetime(s.index)
    nav = s.reindex(s.index.union(days)).interpolate("time").reindex(days)
    r = (nav.to_numpy() / np.r_[INIT, nav.to_numpy()[:-1]] - 1).tolist()
    res, _ = make_result(r)
    m = pdash.build_dashboard(res, None, "ALL")["monthly"]["years"]
    assert len(m) == 1 and m[0]["year"] == 2025
    assert m[0]["months"][:3] == [5.0, -2.0, 5.0] and m[0]["months"][3:] == [None] * 9
    assert m[0]["total"] == pytest.approx(8.045, abs=0.011)
    p = pdash.build_dashboard(res, None, "ALL")
    assert p["kpis"]["mdd_pct"] == pytest.approx(-2.0, abs=0.01)           # đỉnh 31/1 -> đáy 28/2
    assert p["kpis"]["pnl_month"] == pytest.approx(10_804.5 - 10_290.0, abs=0.01)
    assert p["kpis"]["pnl_year"] == pytest.approx(804.5, abs=0.01)


def test_monthly_spans_years_and_partial_months():
    res, nav = make_result(_rng_returns(60), start="2024-12-15")
    years = pdash.build_dashboard(res, None, "ALL")["monthly"]["years"]
    assert [y["year"] for y in years] == [2024, 2025]
    assert years[0]["months"][11] is not None and years[0]["months"][:11] == [None] * 11
    assert years[1]["months"][0] is not None and years[1]["months"][1] is not None
    dec_end = [n for n, d in zip(nav, pd.date_range("2024-12-15", periods=60)) if d == pd.Timestamp("2024-12-31")][0]
    assert years[0]["total"] == pytest.approx((dec_end / INIT - 1) * 100, abs=0.01)


# ─── Cắt kỳ ─────────────────────────────────────────────────────────────────
def test_period_slicing():
    res, nav = make_result(_rng_returns(100, seed=3))
    dates = pd.date_range("2025-01-01", periods=100)
    nav = pd.Series(nav, index=dates)
    full = pdash.build_dashboard(res, _bench(), "ALL")
    assert full["series"]["dates"][0] == "2025-01-01" and len(full["series"]["dates"]) == 100
    assert full["series"]["rolling_sharpe_63"][:62] == [None] * 62 and full["series"]["rolling_sharpe_63"][62] is not None
    assert full["kpis"]["ret_period_pct"] == pytest.approx((nav.iloc[-1] / INIT - 1) * 100, abs=0.01)

    m1 = pdash.build_dashboard(res, _bench(), "1M")
    cut = dates[-1] - pd.DateOffset(months=1)                                    # 10/03/2025
    assert m1["series"]["dates"][0] == f"{cut + pd.Timedelta(days=1):%Y-%m-%d}" and m1["series"]["dates"][-1] == "2025-04-10"
    base = nav[cut]
    assert m1["kpis"]["ret_period_pct"] == pytest.approx((nav.iloc[-1] / base - 1) * 100, abs=0.01)
    assert m1["series"]["nav"][-1] == full["series"]["nav"][-1]
    # bench quy về cùng NAV gốc của kỳ: ngày đầu ≈ base × (giá ngày đầu / giá ngày cutoff)
    b = _bench()
    assert m1["series"]["bench"][0] == pytest.approx(base * b[cut + pd.Timedelta(days=1)] / b[cut], abs=0.01)
    assert m1["kpis"]["bench_ret_period_pct"] == pytest.approx((b["2025-04-10"] / b[cut] - 1) * 100, abs=0.01)
    assert m1["kpis"]["excess_pct"] == pytest.approx(m1["kpis"]["ret_period_pct"] - m1["kpis"]["bench_ret_period_pct"], abs=0.011)
    # rolling Sharpe tính trên toàn lịch sử rồi mới cắt -> kỳ 1M (ngày ≥ 69 của chuỗi) đã có giá trị
    assert None not in m1["series"]["rolling_sharpe_63"]
    assert m1["series"]["rolling_sharpe_63"] == full["series"]["rolling_sharpe_63"][-len(m1["series"]["dates"]):]
    assert m1["monthly"] == full["monthly"]                                       # bảng tháng luôn toàn lịch sử

    m3 = pdash.build_dashboard(res, None, "3M")
    assert m3["series"]["dates"][0] == "2025-01-11" and len(m3["series"]["dates"]) == 90
    ytd = pdash.build_dashboard(res, None, "YTD")
    assert ytd["series"]["dates"] == full["series"]["dates"] and ytd["kpis"]["ret_period_pct"] == full["kpis"]["ret_period_pct"]
    y1 = pdash.build_dashboard(res, None, "1Y")
    assert y1["series"]["dates"] == full["series"]["dates"]
    with pytest.raises(ValueError):
        pdash.build_dashboard(res, None, "5Y")


def test_period_ending_year_start_uses_previous_year_end_for_ytd():
    res, nav = make_result(_rng_returns(60, seed=9), start="2024-12-01")
    ytd = pdash.build_dashboard(res, None, "YTD")
    assert ytd["series"]["dates"][0] == "2025-01-01" and len(ytd["series"]["dates"]) == 29
    dec31 = nav[30]
    assert ytd["kpis"]["pnl_year"] == pytest.approx(nav[-1] - dec31, abs=0.01)
    assert ytd["kpis"]["ret_period_pct"] == pytest.approx((nav[-1] / dec31 - 1) * 100, abs=0.01)


# ─── Exposure / vị thế / chiến lược ─────────────────────────────────────────
def test_exposure_open_positions_and_strategy_rows():
    r = _rng_returns(70, seed=4)
    end_day = "2025-03-11"
    trades = [
        _trade("trend_long", "LONG", 20_000, 300.0, _ms("2025-01-10"), _ms("2025-01-12")),
        _trade("trend_long", "LONG", 10_000, -100.0, _ms("2025-02-10"), _ms("2025-02-12")),
        _trade("trend_short", "SHORT", 10_000, 50.0, _ms("2025-02-20"), _ms("2025-02-22")),
        _trade("trend_long", "LONG", 6_000, 10.0, _ms("2025-03-05"), _ms(end_day, 23), "End of Backtest"),     # đang mở
        _trade("trend_short", "SHORT", 2_000, -5.0, _ms("2025-03-06"), _ms(end_day, 23), "End of Backtest"),    # đang mở
    ]
    res, nav = make_result(r, trades=trades)
    p = pdash.build_dashboard(res, None, "ALL")
    k = p["risk"]
    last = nav[-1]
    assert k["open_positions"] == 2 and k["strategies_running"] == 2
    assert k["exposure_gross_pct"] == pytest.approx(8000 / last * 100, abs=0.06)
    assert k["exposure_net_pct"] == pytest.approx(4000 / last * 100, abs=0.06)
    assert k["by_market"][0]["long_pct"] == pytest.approx(6000 / last * 100, abs=0.06)
    assert k["by_market"][0]["short_pct"] == pytest.approx(2000 / last * 100, abs=0.06)
    assert k["margin_used_pct"] == pytest.approx(800 / last * 100, abs=0.06)
    wins, losses = 300 + 50 + 10, 100 + 5
    assert k["profit_factor"] == pytest.approx(wins / losses, abs=0.01)
    s = {x["id"]: x for x in p["strategies"]}
    assert s["trend_long"]["pnl"] == 210.0 and s["trend_short"]["pnl"] == 45.0
    assert s["trend_long"]["contribution_pct"] == pytest.approx(2.1, abs=0.01)
    tot = 20_000 + 10_000 + 10_000 + 6_000 + 2_000
    assert s["trend_long"]["weight_pct"] == pytest.approx(36_000 / tot * 100, abs=0.1)
    assert s["trend_long"]["weight_pct"] + s["trend_short"]["weight_pct"] == pytest.approx(100, abs=0.1)
    assert s["trend_long"]["side"] == "LONG" and s["trend_short"]["side"] == "SHORT"
    assert len(s["trend_long"]["pnl_30d"]) == 30 and sum(s["trend_long"]["pnl_30d"]) == pytest.approx(10 - 100, abs=0.01)  # 30 ngày cuối: từ 10/2
    assert s["trend_long"]["mdd_pct"] <= 0 and s["trend_short"]["status"] == "active"
    # 1M chỉ tính lệnh đóng trong kỳ (từ 12/2): trend_long còn -100 (12/2) + 10
    m1 = {x["id"]: x for x in pdash.build_dashboard(res, None, "1M")["strategies"]}
    assert m1["trend_long"]["pnl"] == pytest.approx(-90.0)


def test_exposure_without_notional_falls_back_to_qty_or_null():
    t_q = {"symbol": "BTC@perp", "strategy": "trend_long", "side": "LONG", "enter_time": _ms("2025-01-05"), "enter_price": 50.0,
           "close_time": _ms("2025-01-10", 23), "pnl": 1.0, "close_reason": "End of Backtest", "qty": 40.0}
    res, nav = make_result(_rng_returns(10), trades=[t_q])
    k = pdash.build_dashboard(res, None, "ALL")["risk"]
    assert k["exposure_gross_pct"] == pytest.approx(2000 / nav[-1] * 100, abs=0.06) and k["margin_used_pct"] is None
    t_none = {k_: v for k_, v in t_q.items() if k_ != "qty"}
    res2, _ = make_result(_rng_returns(10), trades=[t_none])
    k2 = pdash.build_dashboard(res2, None, "ALL")["risk"]
    assert k2["exposure_gross_pct"] is None and k2["open_positions"] == 1
    k3 = pdash.build_dashboard(make_result(_rng_returns(10))[0], None, "ALL")["risk"]
    assert k3["exposure_gross_pct"] == 0.0 and k3["open_positions"] == 0 and k3["profit_factor"] is None


# ─── Sự kiện ────────────────────────────────────────────────────────────────
def test_events_drawdown_budget_and_kill_switch():
    r = [0.0] * 5 + [-0.06] * 5 + [0.0] * 3                       # NAV -26,6% từ đỉnh (equity_worst thấp hơn nữa)
    res, _ = make_result(r, halted_at=_ms("2025-01-10"), kill_pct=30.0)
    ev = pdash.build_dashboard(res, None, "ALL")["events"]
    levels = [e["level"] for e in ev]
    assert levels.count("warn") == 1 and levels.count("crit") == 2                   # 15% (50% hạn mức) + 24% (80%) + kill switch
    assert [e for e in ev if e["level"] == "warn"][0]["time"] < [e for e in ev if e["level"] == "crit"][0]["time"]
    assert ev == sorted(ev, key=lambda e: e["time"])
    assert any("Kill switch" in e["text"] for e in ev)
    ks = [e for e in ev if "Kill switch" in e["text"]][0]
    assert ks["time"] == _ms("2025-01-10") and ks["level"] == "crit"
    # kỳ cắt: sự kiện trước đầu kỳ không hiện
    res2, _ = make_result([0.0] * 60 + [0.001] * 40, halted_at=_ms("2025-01-05"))
    assert not any("Kill switch" in e["text"] for e in pdash.build_dashboard(res2, None, "1M")["events"])


def test_prefers_exact_daily_nav_when_present():
    res, nav = make_result(_rng_returns(5))
    res["daily_nav"] = [{"date": f"2025-01-0{i + 1}", "equity": 10_000 + i} for i in range(5)]
    res["equity_curve"] = res["equity_curve"][::3]                  # đường vốn thưa
    assert pdash.build_dashboard(res, None, "ALL")["series"]["nav"] == [10000.0, 10001.0, 10002.0, 10003.0, 10004.0]


def test_empty_curve_is_unavailable():
    p = pdash.build_dashboard({"equity_curve": [], "config": {"initial_capital": INIT}}, None, "ALL")
    assert p["available"] is False and p["reason"]


# ─── Router ─────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "data"))
    portfolio_router._CACHE.clear()
    app = FastAPI()
    app.include_router(portfolio_router.router)
    return TestClient(app)


def _job(result, kind="book_backtest", name=None, args=None, log="[run_limited] peak RAM 1 MB / limit x | exit 0\n"):
    d = os.path.join(batch_jobs.jobs_root(), name or f"{time.strftime('%Y%m%d_%H%M%S')}_a1b2c3")
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": os.path.basename(d), "kind": kind, "params": args or {"start": "2025-01-01", "end": "2025-04-10"},
                               "pid": 2 ** 22 + 7, "created": 1.0, "started": None, "finished": None, "state": "running", "exit_code": None})
    open(os.path.join(d, "out.log"), "w").write(log)
    if result is not None:
        json.dump(result, open(os.path.join(d, "result.json"), "w"))
    return os.path.basename(d)


def test_only_backtest_source_is_accepted(client):
    for src in ("paper", "real", "live", "testnet"):
        assert client.get(f"/api/studio/portfolio/dashboard?source={src}").status_code == 422


def test_dashboard_endpoint_caches_and_rebases_benchmark(client, monkeypatch):
    res, _ = make_result(_rng_returns(100))
    jid = _job(res)
    calls = []
    monkeypatch.setattr(portfolio_router.pd_mod, "benchmark_daily_closes", lambda *a: calls.append(a) or _bench())
    r = client.get(f"/api/studio/portfolio/dashboard?source=backtest&job_id={jid}&period=3M")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["available"] and p["period"] == "3M" and p["source"]["job_id"] == jid and p["series"]["bench"][0] is not None
    assert p["source"]["label"].startswith("Backtest ·") and "2025-01-01→2025-04-10" in p["source"]["label"]
    assert len(calls) == 1 and calls[0][0] == "BTC@perp"
    assert client.get(f"/api/studio/portfolio/dashboard?source=backtest&job_id={jid}&period=3M").json() == p
    assert len(calls) == 1                                                       # lần 2 từ bộ đệm
    client.get(f"/api/studio/portfolio/dashboard?source=backtest&job_id={jid}&period=1M")
    assert len(calls) == 2                                                       # khoá theo (job, period)
    # không truyền job_id -> job backtest xong gần nhất
    assert client.get("/api/studio/portfolio/dashboard").json()["source"]["job_id"] == jid


def test_dashboard_endpoint_errors(client):
    assert client.get("/api/studio/portfolio/dashboard?period=7D").status_code == 422
    assert client.get("/api/studio/portfolio/dashboard?source=real").status_code == 422
    assert client.get("/api/studio/portfolio/dashboard?job_id=xyz").status_code == 422
    assert client.get("/api/studio/portfolio/dashboard?job_id=20260101_000000_ffffff").status_code == 404
    r = client.get("/api/studio/portfolio/dashboard")                            # chưa có job nào
    assert r.status_code == 200 and r.json()["available"] is False
    wfa = _job({"x": 1}, kind="book_wfa", name="20260101_000001_a1b2c3")
    assert client.get(f"/api/studio/portfolio/dashboard?job_id={wfa}").status_code == 422
    failed = _job(None, name="20260101_000002_a1b2c3", log="Traceback\n[run_limited] peak RAM 1 MB / limit x | exit 1\n")
    assert client.get(f"/api/studio/portfolio/dashboard?job_id={failed}").status_code == 409


def test_dashboard_is_fast_for_one_year(client):
    res, _ = make_result(_rng_returns(365, seed=8), trades=[_trade("trend_long", "LONG", 5000, 1.0, _ms("2025-01-02"), _ms("2025-01-03"))] * 800)
    t0 = time.time()
    p = pdash.build_dashboard(res, _bench(days=400), "ALL")
    assert time.time() - t0 < 1.0 and len(p["series"]["dates"]) == 365


def test_sample_at_exclusive_end_belongs_to_last_day():
    """Mẫu vốn đúng mốc end (00:00 ngày sau) không được tạo thêm một ngày."""
    res, nav = make_result([0.01, 0.01, 0.01])
    res["equity_curve"].append({"time": res["config"]["end"], "equity": 10_500.0, "equity_worst": 10_500.0})
    p = pdash.build_dashboard(res, None, "ALL")
    assert p["series"]["dates"] == ["2025-01-01", "2025-01-02", "2025-01-03"] and p["series"]["nav"][-1] == 10500.0
    assert p["source"]["end"] == "2025-01-03"


# ─── Feed abstraction: backtest không đổi; live/testnet giả lập ──────────────────────────────────────────────
def _synthetic_backtest():
    trades = [_trade("trend_long", "LONG", 5000, 120.0, _ms("2025-02-01"), _ms("2025-02-03")),
              _trade("trend_short", "SHORT", 3000, -40.0, _ms("2025-02-05"), _ms("2025-02-06")),
              _trade("trend_long", "LONG", 4000, 15.0, _ms("2025-04-05"), _ms("2025-04-10", 23), "End of Backtest")]
    return make_result(_rng_returns(100), trades=trades, halted_at=_ms("2025-04-05"), rejected=7)[0]


# (băm cập nhật khi đổi lời văn sự kiện "bị chặn do giới hạn rủi ro"; đã kiểm: thay lại câu cũ thì ra đúng băm trước đó, mọi khoá khác không đổi)
# sha256 của payload (sort_keys) do build_dashboard cũ (trước khi có feed/`positions`) dựng trên _synthetic_backtest() + _bench()
PRE_FEED_HASH = {"ALL": "36b304102d85e7b4c6dd812b21042b835bcc105567dc0056bdd161c7f7c27d60",
                 "3M": "332ce8d8e8959ab1532205483e7a2aafaf1bd4a6630357827764596bc2dec731"}


@pytest.mark.parametrize("period", ["ALL", "3M"])
def test_backtest_feed_payload_identical_to_pre_feed_output(period):
    res = _synthetic_backtest()
    snap = feeds.BacktestFeed(res, "j1", "L").fetch()
    p = pdash.build_from_snapshot(snap, period, _bench())
    assert p["positions"] == [] and "mock" not in p and "mock_note" not in p and "mock" not in p["source"]
    assert p == pdash.build_dashboard(res, _bench(), period, job_id="j1", label="L")
    for k in ("positions", "stats", "mdd", "strategy_stats"):                   # khoá được thêm sau (feed, bộ số đo chuẩn, theo chiến lược)
        p.pop(k)
    assert hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest() == PRE_FEED_HASH[period]


def test_open_positions_in_result_count_toward_exposure_and_margin():
    res, _ = make_result(_rng_returns(60, seed=3))
    res["config"]["initial_capital"] = INIT
    res["positions"] = [
        {"symbol": "SOL@perp", "strategy": "trend_long_perp__SOL", "side": "LONG", "qty": 50.0, "entry_price": 100.0, "mark_price": 102.0,
         "notional": 5100.0, "unrealized_pnl": 95.0, "opened": _ms("2025-02-20"), "margin_usd": 5000.0},
        {"symbol": "ETH@perp", "strategy": "trend_short", "side": "SHORT", "qty": 1.0, "entry_price": 2000.0, "mark_price": 1990.0,
         "notional": 1990.0, "unrealized_pnl": 9.0, "opened": _ms("2025-02-21"), "margin_usd": 199.0},
    ]
    p = pdash.build_dashboard(res, _bench(), "ALL")
    assert [x["symbol"] for x in p["positions"]] == ["SOL@perp", "ETH@perp"]                # lớn nhất trước
    assert p["risk"]["open_positions"] == 2 and p["risk"]["margin_used_pct"] is not None
    nav = p["kpis"]["nav"]
    assert p["risk"]["exposure_gross_pct"] == pytest.approx((5100 + 1990) / nav * 100, abs=0.06)
    assert p["risk"]["exposure_net_pct"] == pytest.approx((5100 - 1990) / nav * 100, abs=0.06)
    json.dumps(p, allow_nan=False)
