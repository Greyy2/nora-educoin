"""Tổng quan: thống kê theo HỌ chiến lược và danh sách lệnh (lọc/sắp/phân trang/CSV)."""
import pytest

from test_portfolio_dashboard import _bench, _job, _ms, _rng_returns, _trade, client, make_result  # noqa: F401  (client là fixture)
from backend.core.analytics import dashboard as pdash
from backend.core.metrics.trades import strategy_family


def _res():
    trades = [_trade("trend_long", "LONG", 1000, 50.0, _ms("2025-01-05"), _ms("2025-01-06")),
              _trade("trend_long", "LONG", 1000, -20.0, _ms("2025-01-10"), _ms("2025-01-11")),
              _trade("trend_long_perp__SOL", "LONG", 500, 10.0, _ms("2025-01-12"), _ms("2025-01-13")),
              _trade("reversion_short", "SHORT", 800, 0.0, _ms("2025-01-14"), _ms("2025-01-15")),
              _trade("reversion_short", "SHORT", 800, -5.0, _ms("2025-01-20"), _ms("2025-01-21"))]
    res, _ = make_result(_rng_returns(40), trades=trades)
    return res


def test_family_groups_all_params_of_same_strategy():
    assert strategy_family("trend_long_perp__SOL") == "trend_long_perp" and strategy_family("trend_long") == "trend_long"
    p = pdash.build_dashboard(_res(), _bench(), "ALL")
    fam = {x["family"]: x for x in p["strategy_stats"]}
    assert set(fam) == {"trend_long", "trend_long_perp", "reversion_short"}
    t = fam["trend_long"]["trades"]
    assert (t["trades"], t["wins"], t["losses"]) == (2, 1, 1) and t["profit_factor"] == pytest.approx(2.5) and fam["trend_long"]["pnl"] == 30.0
    r = fam["reversion_short"]["trades"]
    assert (r["wins"], r["losses"], r["breakeven"]) == (0, 1, 1) and r["short"]["trades"] == 2


def test_trades_endpoint_filters_sort_paging_csv(client):
    jid = _job(_res())
    base = f"/api/studio/portfolio/trades?job_id={jid}"
    j = client.get(base).json()
    assert j["total"] == 5 and j["job_id"] == jid and [t["pnl"] for t in j["items"]][:2] == [-5.0, 0.0]   # mới đóng trước
    assert client.get(base + "&strategy=trend_long").json()["total"] == 2                                  # id
    assert client.get(base + "&strategy=trend_long_perp").json()["total"] == 1                             # họ chiến lược
    assert client.get(base + "&side=SHORT&outcome=loss").json()["total"] == 1
    assert [t["pnl"] for t in client.get(base + "&sort=-pnl&limit=2").json()["items"]] == [50.0, 10.0]
    assert client.get(base + "&offset=4&limit=2").json()["items"][0]["pnl"] == 50.0
    assert client.get(base + "&sort=bogus").status_code == 422
    csv = client.get(base + "&format=csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("close_time,enter_time,symbol") and len(csv.text.splitlines()) == 6
