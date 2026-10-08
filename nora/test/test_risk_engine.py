"""P6.1: core/position_size.py (admit_entry, kill_triggered) — nguồn duy nhất của quy tắc rủi ro danh mục (hàm thuần).
(a) Unit từng quy tắc: trần số vị thế, per-symbol, room gross, trần rủi ro mở, dd_throttle (sàn + chặn 1.0), kill switch.
(b) Parity: sổ paper KernelBook từng nến (live/paper.py::KernelPaperBook) == PortfolioEngine/kernel trên ngẫu nhiên cấu hình có ĐỦ trần rủi ro: cùng lệnh đóng (mọi trường),
    cùng rejected_for_risk, cùng halted_at. Lệch -> sửa risk.py, KHÔNG nới so sánh.
Số cấu hình đổi bằng NORA_RISK_PARITY_CONFIGS (mặc định 100)."""
import os
import random

import pytest

import golden_scenarios as gs
from backend.core.backtest import PortfolioEngine, RiskConfig
from backend.core.position_size import Admission, admit_entry, kill_triggered
from test_kernel_parity import market_root, rand_portfolio_config  # noqa: F401  (market_root là fixture: thị trường 34 ngày, 4 + 2 tài sản)

INF = float("inf")
N_CONFIGS = int(os.environ.get("NORA_RISK_PARITY_CONFIGS", "100"))
N_CHUNKS = 5
_COV = {"ran": 0, "rejected": 0, "halted": 0, "dca": 0}


def _adm(**kw):
    """Mặc định: danh mục trống, vốn 1000 = đỉnh, mọi trần rủi ro tắt."""
    a = dict(n_open=0, per_symbol_open=0, equity=1000.0, peak=1000.0, gross=0.0, open_risk=0.0, max_positions=8, max_per_symbol=1,
             max_gross_exposure=3.0)
    a.update(kw)
    return admit_entry(**a)


# ── (a) unit ────────────────────────────────────────────────────────────────
def test_free_book_admits_with_no_caps():
    assert _adm() == Admission(True, 3000.0, INF, 1.0)


def test_positions_cap_blocks_at_limit():
    assert _adm(n_open=2, max_positions=3).can_open
    a = _adm(n_open=3, max_positions=3)
    assert a == Admission(False, INF, INF, 1.0)                      # bị chặn: các trần giữ mặc định
    assert not _adm(n_open=9, max_positions=3).can_open


def test_per_symbol_cap_blocks_at_limit():
    assert _adm(per_symbol_open=1, max_per_symbol=2).can_open
    assert not _adm(per_symbol_open=2, max_per_symbol=2).can_open
    assert not _adm(per_symbol_open=1, max_per_symbol=1).can_open


def test_caps_are_cast_to_int():
    assert not _adm(n_open=3, max_positions=3.0).can_open
    assert _adm(n_open=3, max_positions="4").can_open


def test_gross_room_is_clamped_and_blocks_when_not_positive():
    a = _adm(gross=1000.0, max_gross_exposure=3.0)                   # room = 3*1000 - 1000
    assert a.can_open and a.max_new_notional == 2000.0
    a = _adm(gross=3000.0)                                           # room = 0 -> chặn (room > 0 là nghiêm ngặt)
    assert not a.can_open and a.max_new_notional == 0.0
    a = _adm(gross=4500.0)                                           # room < 0 -> kẹp về 0
    assert not a.can_open and a.max_new_notional == 0.0
    assert a.max_new_risk == INF and a.risk_scale == 1.0             # quy tắc sau không chạy khi đã chặn


def test_open_risk_cap():
    a = _adm(max_open_risk_pct=2.0, open_risk=5.0)                   # trần 2% * 1000 = 20 -> còn 15
    assert a.can_open and a.max_new_risk == 0.02 * 1000.0 - 5.0
    a = _adm(max_open_risk_pct=2.0, open_risk=20.0)                  # còn 0 -> chặn
    assert not a.can_open and a.max_new_risk == 0.0
    a = _adm(max_open_risk_pct=2.0, open_risk=35.0)
    assert not a.can_open and a.max_new_risk == 0.02 * 1000.0 - 35.0  # âm: giữ nguyên giá trị
    assert _adm(max_open_risk_pct=0.0, open_risk=1e9).max_new_risk == INF   # 0 = tắt


def test_open_risk_cap_skipped_when_gross_already_blocks():
    a = _adm(gross=3000.0, max_open_risk_pct=2.0, open_risk=0.0)
    assert not a.can_open and a.max_new_risk == INF


def test_dd_throttle_scale_floor_and_ceiling():
    f = lambda eq, **kw: _adm(equity=eq, peak=1000.0, dd_throttle_pct=10.0, **kw)  # noqa: E731
    assert f(1000.0).risk_scale == 1.0                               # chưa sụt
    assert f(1200.0).risk_scale == 1.0                               # trên đỉnh cũ: rs > 1 -> chặn 1.0
    a = f(950.0)                                                     # sụt 5% / ngưỡng 10% -> 0.5
    assert a.can_open and a.risk_scale == 1.0 - (1.0 - 950.0 / 1000.0) / (10.0 / 100.0)
    assert f(900.0).risk_scale == 0.25                               # chạm sàn mặc định
    assert f(500.0).risk_scale == 0.25                               # dưới sàn -> sàn
    assert _adm(equity=500.0, peak=1000.0, dd_throttle_pct=10.0, dd_throttle_floor=0.5).risk_scale == 0.5
    assert f(500.0).can_open                                         # throttle chỉ thu nhỏ, không chặn


def test_dd_throttle_disabled_or_no_peak():
    assert _adm(equity=500.0, peak=1000.0, dd_throttle_pct=0.0).risk_scale == 1.0
    assert _adm(equity=500.0, peak=1000.0, dd_throttle_pct=None).risk_scale == 1.0
    assert _adm(equity=500.0, peak=0.0, dd_throttle_pct=10.0).risk_scale == 1.0     # peak <= 0: bỏ qua
    assert _adm(equity=500.0, peak=-5.0, dd_throttle_pct=10.0).risk_scale == 1.0


def test_throttle_skipped_when_risk_cap_blocks():
    a = _adm(equity=900.0, peak=1000.0, dd_throttle_pct=10.0, max_open_risk_pct=1.0, open_risk=50.0)
    assert not a.can_open and a.risk_scale == 1.0


def test_admission_is_immutable_tuple():
    a = _adm()
    assert tuple(a) == (a.can_open, a.max_new_notional, a.max_new_risk, a.risk_scale)
    with pytest.raises(AttributeError):
        a.can_open = False


def test_kill_switch_boundary():
    assert not kill_triggered(901.0, 1000.0, 10.0)
    assert kill_triggered(900.0, 1000.0, 10.0) == (900.0 <= 1000.0 * (1.0 - 10.0 / 100.0))   # đúng ngưỡng: (<=) kích hoạt
    assert kill_triggered(899.9, 1000.0, 10.0)
    assert kill_triggered(0.0, 1000.0, 100.0)                        # kill = 100%: worst <= 0
    assert not kill_triggered(-1e9, 1000.0, 0.0)                     # 0 không bao giờ kích hoạt
    assert not kill_triggered(-1e9, 1000.0, None)
    assert kill_triggered(500.0, 1000.0, 30.0) is True


# ── (b) parity paper (KernelBook từng nến, P9.4b T7) == kernel batch ──────────────────────────────────────────
def _risk_cfg(seed, market_root_):
    """Cấu hình danh mục ngẫu nhiên (cùng bộ sinh của test_kernel_parity) nhưng MỌI trần rủi ro đều bật, không đóng ở cuối dữ liệu."""
    cfg = rand_portfolio_config(seed, market_root_)
    rng = random.Random(seed ^ 0x5EED)
    cfg["risk"] = RiskConfig(max_positions=rng.choice([1, 2, 3, 8]), max_per_symbol=rng.choice([1, 2]),
                             max_gross_exposure=rng.choice([0.3, 1.0, 3.0, 10.0]), kill_switch_dd_pct=rng.choice([5.0, 10.0, 30.0, 60.0]),
                             max_open_risk_pct=rng.choice([0.5, 1.0, 2.0, 5.0]), dd_throttle_pct=rng.choice([2.0, 5.0, 10.0, 25.0]),
                             dd_throttle_floor=rng.choice([0.1, 0.25, 0.5]))
    cfg["close_at_end"] = False
    return cfg


def _trade_key(x):
    return (x["symbol"], x["strategy"], x["enter_time"], x["close_time"], x["side"], x["reason"], round(x["close_price"], 6),
            round(x["pnl"], 6), x["layers"], round(x["qty"], 6), round(x["avg_price"], 6), round(x["fees"], 6), round(x["funding"], 6))


def _pos_key(p):
    return (p.symbol, p.strategy_id, int(p.enter_time), int(p.close_time), p.pos_type.name, p.close_reason, round(p.close_price, 6),
            round(p.real_pnl, 6), int(p.layers or 1), round(float(p.qty), 6), round(float(p.avg_price or p.enter_price), 6),
            round(float(p.fees_usd or 0), 6), round(float(p.funding_usd or 0), 6))


def _replay(pe, strategies, risk, trade_start):
    """Phát lại đúng dữ liệu + tín hiệu của pe từng nến vào sổ paper KernelBook (như test_live_bot::test_paper_book_replays_engine_trades_exactly)."""
    from backend.core.backtest import KernelPaperBook
    pb = KernelPaperBook(strategies, pe.symbols, "1m", pe.initial_capital, risk, trade_start=trade_start)
    grid = sorted({int(t) for bk in pe.books for t in bk["data"]["t"]})
    pos = {bk["symbol"]: {int(t): i for i, t in enumerate(bk["data"]["t"])} for bk in pe.books}
    fptr = {bk["symbol"]: 0 for bk in pe.books}
    for t in grid:
        bars, sig, fund = {}, {}, {}
        for bk in pe.books:
            s, d = bk["symbol"], bk["data"]
            i = pos[s].get(t)
            if i is None:
                continue
            bars[s] = (d["o"][i], d["h"][i], d["l"][i], d["c"][i])
            sig[s] = [{"match": e["match"][i], "stop": e["stop"][i], "vol": e["vol"][i] if e["vol"] is not None else None,
                       "dca": bool(e["dca"][i]) if e.get("dca") is not None else True} for e in bk["entries"]]
            fl = []
            while fptr[s] < len(d["f_t"]) and d["f_t"][fptr[s]] <= t:
                fl.append((int(d["f_t"][fptr[s]]), float(d["f_r"][fptr[s]])))
                fptr[s] += 1
            fund[s] = fl
        pb.step_bar(t, bars, sig, fund)
    return pb


@pytest.mark.parametrize("chunk", range(N_CHUNKS))
def test_paper_book_equals_kernel_with_all_risk_caps(market_root, chunk):
    per = N_CONFIGS // N_CHUNKS + (1 if chunk < N_CONFIGS % N_CHUNKS else 0)
    ran = skipped = 0
    with gs.data_root_env(market_root):
        for j in range(per):
            seed = 500_000 + chunk * 10_000 + j
            cfg = _risk_cfg(seed, market_root)
            pe = PortfolioEngine(cfg["symbols"], cfg["strategies"], cfg["start"], cfg["end"], trade_start_ts=cfg["trade_start"],
                                 initial_capital=cfg["capital"], risk=cfg["risk"], close_at_end=False)
            try:
                pe.run()
            except ValueError:                                       # cấu hình bị từ chối (ngân sách DCA, ...): không có gì để so
                skipped += 1
                continue
            res = pe.get_results()
            label = f"risk-parity seed={seed}"
            if res.get("ruined_at"):                                 # cháy tài khoản: sổ paper không mô hình hoá (ngoài phạm vi risk.py)
                skipped += 1
                continue
            risk = {"max_positions": cfg["risk"].max_positions, "max_per_symbol": cfg["risk"].max_per_symbol,
                    "max_gross_exposure": cfg["risk"].max_gross_exposure, "kill_switch_dd_pct": cfg["risk"].kill_switch_dd_pct,
                    "max_open_risk_pct": cfg["risk"].max_open_risk_pct, "dd_throttle_pct": cfg["risk"].dd_throttle_pct,
                    "dd_throttle_floor": cfg["risk"].dd_throttle_floor}
            pb = _replay(pe, cfg["strategies"], risk, cfg["trade_start"])
            want = sorted(_pos_key(p) for p in res["positions"])
            got = sorted(_trade_key(x) for x in pb.trades)
            assert len(got) == len(want), f"{label}: số lệnh đóng paper={len(got)} kernel={len(want)}"
            for k, (g, w) in enumerate(zip(got, want)):
                assert g == w, f"{label}: lệnh #{k} khác paper={g} kernel={w}"
            assert pb.rejected_for_risk == res["rejected_for_risk"], f"{label}: rejected_for_risk"
            assert pb.halted_at == res.get("halted_at"), f"{label}: halted_at"
            _COV["ran"] += 1
            _COV["rejected"] += bool(pb.rejected_for_risk)
            _COV["halted"] += pb.halted_at is not None
            _COV["dca"] += any(x["layers"] > 1 for x in pb.trades)
            ran += 1
    _COV["skipped"] = _COV.get("skipped", 0) + skipped
    assert ran >= per * 0.5, f"quá nhiều cấu hình bị bỏ ({skipped}/{per}) — test không đủ sức"


def test_zz_risk_parity_coverage():
    """Các nhánh risk thực sự được chạm tới (không 'xanh rỗng'). Chỉ kiểm khi chạy đủ bộ parity."""
    if _COV["ran"] < N_CONFIGS * 0.5 or N_CONFIGS < 40:
        pytest.skip("chưa chạy đủ bộ parity (chạy riêng một phần hoặc ít cấu hình)")
    print(f"\n[risk-parity] {_COV}")
    assert _COV["rejected"] > 0, _COV                                # có lệnh bị chặn bởi risk
    assert _COV["halted"] > 0, _COV                                  # có kill switch kích hoạt
    assert _COV["dca"] > 0, _COV                                     # có lệnh DCA nhiều tầng
