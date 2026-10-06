"""P6.12 — nến danh mục HAI PHA: lệnh vào của tài sản B ở open nến t phải được xét theo trạng thái LÚC MỞ NẾN, không nhìn trước SL / TP / giá đóng
nến của tài sản A đứng trước trong cùng nến t (ADR P6 §10; EXT_REPORT S8 đo lệch 1.6-2.7% vốn cuối so với NautilusTrader trước khi sửa).

Kịch bản dựng tay, hai tài sản AAA (đứng trước) / BBB, nến phẳng 100, mỗi chiến lược một tài sản (khoá "symbols"):
  nến 4: tín hiệu vào của AAA -> AAA vào ở open nến 5;  nến 9: tín hiệu vào của BBB -> BBB chờ vào ở open nến 10;
  nến 10: AAA chạm SL / TP TRONG nến (BBB phẳng). Đúng thời gian: lúc mở nến 10 AAA vẫn đang mở.
 (1) max_positions=1: BBB phải bị CHẶN (code cũ cho vào vì AAA đã đóng trong nến);
 (2) trần gross 0.6x vốn: AAA đang giữ 5000 -> chỉ còn 1000 danh nghĩa cho BBB (code cũ: AAA đã đóng, còn 5940 -> BBB 4950);
 (3) vốn tính khối lượng: AAA chốt lời +150 TRONG nến 10 -> BBB vẫn tính theo vốn lúc mở nến (10000) chứ không phải 10150.
Mỗi kịch bản chạy qua BỐN cài đặt phải ra đúng như nhau: oracle (RefPortfolioEngine), kernel (PortfolioEngine), PaperBook event (Runner +
PositionManager + SimVenue) và PaperBook tracker (Runner + PositionTracker)."""
import numpy as np
import pandas as pd
import pytest

import golden_scenarios as gs
import reference_engine as ref
from backend.core.backtest.portfolio import PortfolioEngine, RiskConfig
from backend.core.data.resampler import save_resampled_dataset
from backend.live.paper import PaperBook
from test_runner_parity import _feed

T0 = 1_700_006_400_000
M = 60_000
N = 31 * 1440                      # >= 30 ngày: qua cổng chất lượng dữ liệu (nến phẳng nên chạy nhanh)
SYMS = ["AAA@perp", "BBB@perp"]


def _bars(special):
    """N nến phẳng 100; `special` = {chỉ số nến: (o, h, l, c)} thay thế."""
    rows = [(100.0, 100.0, 100.0, 100.0)] * N
    rows = [special.get(i, r) for i, r in enumerate(rows)]
    return pd.DataFrame({"open_time": T0 + np.arange(N, dtype=np.int64) * M, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 10.0})


def _write_market(root, frames):
    meta = {"venue": "cex", "checksums_verified": True, "exchange": "binance"}
    for sym, df in frames.items():
        end = int(df.open_time.max())
        save_resampled_dataset(symbol=sym, output_dir=f"{root}/cex", df_1m_raw=df, pool_address="s", crawl_ok=True,
                               requested_start_ts=T0, requested_end_ts=end, extra_meta=meta)
        save_resampled_dataset(symbol="perp", output_dir=f"{root}/cex/{sym}", df_1m_raw=df, pool_address="p", crawl_ok=True,
                               requested_start_ts=T0, requested_end_ts=end, extra_meta={**meta, "exchange": "binance_usdm", "market": "perp"})
        ft = T0 + np.arange(1, 3) * 8 * 3_600_000 * 100          # funding sau cuối dữ liệu: không ảnh hưởng
        pd.DataFrame({"funding_time": ft, "interval_h": 8.0, "rate": 0.0}).to_pickle(f"{root}/cex/{sym}/perp/funding.pkl")


def _strategy(sid, sym, minute, **pos):
    position = {"market": "perp", "leverage": 1, "order_size_pct": 50.0, "fee_rate": 0.0, "maker_fee_rate": 0.0, "slippage_rate": 0.0}
    position.update(pos)
    tree = [[[{"frame": "1m", "column": "open_time", "index": 0}, "==", T0 + minute * M]]]
    return {"id": sid, "side": "LONG", "tree": tree, "position": position, "symbols": [sym]}


def _run_all(tmp_path, special_a, pos_a, risk, pos_b=None):
    """-> {impl: [(symbol, enter_time, qty)] theo thứ tự (symbol, enter_time)}, kèm rejected_for_risk."""
    root = str(tmp_path / "data")
    _write_market(root, {"AAA": _bars(special_a), "BBB": _bars({})})
    strategies = [_strategy("sa", "AAA@perp", 4, **pos_a), _strategy("sb", "BBB@perp", 9, **(pos_b or {}))]
    rc = RiskConfig(kill_switch_dd_pct=0.0, **risk)
    out = {}
    with gs.data_root_env(root):
        engines = {}
        for name, cls in (("oracle", ref.RefPortfolioEngine), ("kernel", PortfolioEngine)):
            e = cls(SYMS, strategies, T0, T0 + (N - 1) * M, trade_start_ts=T0, initial_capital=10_000.0, risk=rc, use_cache=False)
            e.run()
            engines[name] = e
            res = e.get_results()
            out[name] = ([(p.symbol, int(p.enter_time), float(p.qty)) for p in res["positions"]], res["rejected_for_risk"])
        risk_d = {"max_positions": rc.max_positions, "max_per_symbol": rc.max_per_symbol, "max_gross_exposure": rc.max_gross_exposure,
                  "kill_switch_dd_pct": 0.0}
        for name in ("event", "tracker"):
            pb = PaperBook(strategies, SYMS, "1m", 10_000.0, risk_d, trade_start=T0, engine=name)
            for t, bars, sig, fund in _feed(engines["oracle"]):
                pb.step_bar(t, bars, sig, fund)
            # PaperBook không đóng nốt cuối dữ liệu: lệnh còn mở tính như lệnh (đóng ở cuối) của oracle / kernel
            rows = [(x["symbol"], x["enter_time"], x["qty"]) for x in pb.trades]
            rows += [(x["symbol"], x["entry_time"], x["qty"]) for x in pb.positions()]
            out[name] = (rows, pb.rejected_for_risk)
    return out


def _check_same(out):
    base = sorted(out["oracle"][0])
    for impl in ("kernel", "event", "tracker"):
        assert sorted(out[impl][0]) == base, f"{impl} khác oracle"
    assert len({out[i][1] for i in out}) == 1, {i: out[i][1] for i in out}     # cùng rejected_for_risk
    return base


def test_slot_freed_intrabar_is_not_available_at_open(tmp_path):
    # AAA chạm SL 2% trong nến 10 (mức 98); lúc mở nến 10 AAA còn mở nên max_positions=1 chặn BBB.
    out = _run_all(tmp_path, {10: (100.0, 100.0, 97.0, 97.0)}, {"stop_loss_rate": 2.0},
                   {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0})
    trades = _check_same(out)
    assert [s for s, _, _ in trades] == ["AAA@perp"], trades
    assert out["oracle"][1] == 1                                                 # BBB bị chặn đúng một nến


def test_gross_room_uses_open_state_not_intrabar_exit(tmp_path):
    # AAA giữ 50 @100 = 5000; trần 0.6x vốn 10000 = 6000 -> BBB chỉ còn 1000 danh nghĩa (qty 10), dù AAA cắt lỗ trong nến 10.
    out = _run_all(tmp_path, {10: (100.0, 100.0, 97.0, 97.0)}, {"stop_loss_rate": 2.0},
                   {"max_positions": 5, "max_per_symbol": 1, "max_gross_exposure": 0.6})
    trades = _check_same(out)
    by = {s: q for s, _, q in trades}
    assert by["AAA@perp"] == pytest.approx(50.0)
    assert by["BBB@perp"] == pytest.approx(10.0), trades                          # code cũ: ~49.5


def test_sizing_equity_is_open_of_bar_equity(tmp_path):
    # AAA chốt lời +150 (TP 3%) trong nến 10; BBB (50% vốn) tính theo vốn lúc mở nến = 10000 -> qty 50 (code cũ: 50.75).
    out = _run_all(tmp_path, {10: (100.0, 103.0, 100.0, 103.0)}, {"take_profit_rate": 3.0},
                   {"max_positions": 5, "max_per_symbol": 1, "max_gross_exposure": 10.0})
    trades = _check_same(out)
    by = {s: q for s, _, q in trades}
    assert by["AAA@perp"] == pytest.approx(50.0)
    assert by["BBB@perp"] == pytest.approx(50.0), trades
    assert out["oracle"][1] == 0


def test_exit_at_open_is_visible_to_later_symbol(tmp_path):
    # Lệnh thoát TẠI OPEN (hết thời gian giữ) của AAA đứng trước BBB thì đã xong khi BBB được xét -> slot nhả ra dùng được ở cùng open.
    # AAA vào ở open nến 5 với timeout 5 phút -> hết hạn ở open nến 10; BBB chờ vào ở open nến 10, max_positions=1.
    out = _run_all(tmp_path, {}, {"timeout": 5}, {"max_positions": 1, "max_per_symbol": 1, "max_gross_exposure": 10.0})
    trades = _check_same(out)
    assert sorted(s for s, _, _ in trades) == ["AAA@perp", "BBB@perp"], trades
    assert out["oracle"][1] == 0
