"""P7 §7.3 — parity xnoquant: cùng code, rổ TOP10 spot Binance nến ngày, 2020-01-02 → 2025-01-01, hồ sơ `xno` của Nora so với kết quả xnoquant đã lưu
(test/fixtures/xno/*.json). Cần bộ dữ liệu lịch sử TOP10 spot (data/binance_hist hoặc NORA_XNO_DATA_ROOT; 2019-10-01 → 2025-01-02 00:00, nến cuối là 1 nến 2025-01-02 nên cửa sổ kết thúc 2025-01-01); thiếu -> bỏ qua.

Dung sai: E1/E2 end_value lệch <= 1%, MDD lệch <= 1 điểm %, tương quan lợi suất ngày >= 0,99; KEMA long: lợi suất tổng lệch <= 5% tương đối, MDD <= 3 điểm %.
Nhãn thời gian: xnoquant ngày t = giá đóng cửa nến mở t-1; xnoquant vào lệnh ở đóng cửa nến 2019-12-31 (nhãn 2020-01-01) -> start của Nora = 2019-12-31
(tín hiệu ở nến 12-31, khớp ở open nến 01-01)."""
import json
import os

import numpy as np
import pytest

from backend.core.strategy.pydsl.weights import TOP10

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "fixtures", "xno")
ROOT = os.path.abspath(os.environ.get("NORA_XNO_DATA_ROOT") or os.path.join(HERE, "..", "data", "binance_hist"))


def _have_data() -> bool:
    return all(os.path.isfile(os.path.join(ROOT, "cex", s, "24h.pkl")) for s in TOP10)


pytestmark = pytest.mark.skipif(not _have_data(), reason=f"chưa có dữ liệu lịch sử TOP10 spot (nến 24h) tại {ROOT} (đặt NORA_XNO_DATA_ROOT hoặc chờ bộ data/binance_hist)")


def _load(name):
    return json.load(open(os.path.join(FIX, name), encoding="utf-8"))


def _run(code, monkeypatch):
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", ROOT)
    from backend.core.backtest import custom_run
    from backend.core.backtest.portfolio import data_cache_clear
    from backend.core.data.loader import CandleLoader
    CandleLoader.clear_cache()
    data_cache_clear()
    params = {"code": code, "profile": "xno", "universe": "TOP10", "start": "2019-12-31", "end": "2024-12-31", "train_ratio": 0.7,
              "initial_capital": 100_000}
    from backend.db.data_layout import DATA_HOME
    if os.path.dirname(ROOT) == os.path.abspath(DATA_HOME):          # bộ mặc định data/binance_hist: chọn qua tham số `exchange` của job
        params["exchange"] = os.path.basename(ROOT)
    return custom_run.run_job(params)


def _stats(out, ref):
    xs = dict(zip(out["series"]["times"], out["series"]["equity"]))
    rt, rv = ref["returns"]["times"], np.array(ref["returns"]["values"], float)
    ours = np.array([xs.get(t) for t in rt], dtype=object)
    ok = np.array([v is not None for v in ours])
    eq = np.array([v for v in ours[ok]], dtype=float)
    r_ours = np.r_[np.nan, eq[1:] / eq[:-1] - 1]
    m = ~np.isnan(r_ours)
    corr = float(np.corrcoef(r_ours[m][1:], rv[ok][m][1:])[0, 1])
    return eq, corr


@pytest.mark.parametrize("name,tol_end", [("E1_long_all.json", 0.01), ("E2_half_all.json", 0.01)])
def test_always_long_matches_xno(name, tol_end, monkeypatch):
    ref = _load(name)
    out = _run(ref["strategy"]["code"], monkeypatch)
    perf = ref["strategy"]["performance"]
    want_end = perf["analysis"]["end_value"]
    assert out["final_equity"] == pytest.approx(want_end, rel=tol_end), f"end_value {out['final_equity']} vs xnoquant {want_end}"
    mdd = out["metrics"]["simulate"]["xno"]["max_drawdown"]
    assert abs(mdd - perf["performance"]["max_drawdown"]) <= 0.01
    _, corr = _stats(out, ref)
    assert corr >= 0.99, f"tương quan lợi suất ngày {corr:.4f}"
    # giai đoạn test: xnoquant chạy lại từ vốn đầu tại đầu test (agg_test) -> Nora cũng chạy lại [mốc chia, end] từ vốn đầu
    assert out["metrics"]["notes"]["test_fresh_capital"] and "series" in out and "test" in out["series"]
    got, want = out["metrics"]["test"]["xno"], ref["agg_test"]
    print(f"{name} test: ours cagr={got['annual_return']:.4f} mdd={got['max_drawdown']:.4f} pf={got['profit_factor']:.4f} calmar={got['calmar']:.4f} | "
          f"xno cagr={want['cagr']:.4f} mdd={want['max_drawdown']:.4f} pf={want['profit_factor']:.4f} calmar={want['calmar']:.4f}")
    assert got["annual_return"] == pytest.approx(want["cagr"], rel=0.01)
    assert abs(got["max_drawdown"] - want["max_drawdown"]) <= 0.01
    assert got["profit_factor"] == pytest.approx(want["profit_factor"], rel=0.01)
    assert got["calmar"] == pytest.approx(want["calmar"], rel=0.01)


def test_xnoquant_crypto_spot_disallows_short():
    """E3: xnoquant trên Crypto Spot bỏ qua position < 0, không đặt lệnh nào."""
    e3 = _load("E3_short_all.json")
    perf = e3["strategy"]["performance"]["analysis"]
    assert perf["total_trades"] == 0, f"Spot không được short nhưng có {perf['total_trades']} lệnh"
    assert perf["total_fee"] == 0, f"Phí phải bằng 0 nhưng là {perf['total_fee']}"
    assert pytest.approx(perf["end_value"], rel=1e-6) == 100_000.0


def test_xnoquant_e4_and_e6_equivalence():
    """E6 (chứa position=-1) tương đương E4 (chứa position=0) trên Spot (tương quan >= 0.9999)."""
    e4 = _load("E4_up_day.json")
    e6 = _load("E6_mixed.json")
    r4 = np.array(e4["returns"]["values"], float)
    r6 = np.array(e6["returns"]["values"], float)
    corr = float(np.corrcoef(r4, r6)[0, 1])
    assert corr >= 0.9999, f"Tương quan E4 và E6 phải >= 0.9999, thực tế {corr:.6f}"


def test_rsi_does_not_affect_kema_in_xnoquant():
    """E9 (KEMA bỏ điều kiện RSI) trùng từng bit với KEMA gốc trên xnoquant (loại trừ nguyên nhân do RSI)."""
    e9 = _load("E9_kema_nrsi.json")
    kema = _load("KEMA_long.json")
    r9 = np.array(e9["returns"]["values"], float)
    rk = np.array(kema["returns"]["values"], float)
    diff = np.abs(r9 - rk)
    assert np.max(diff) == 0.0, f"Sai số lớn nhất giữa E9 và KEMA phải bằng 0, thực tế {np.max(diff)}"
    corr = float(np.corrcoef(r9, rk)[0, 1])
    assert corr == 1.0
    p9 = e9["strategy"]["performance"]["analysis"]
    pk = kema["strategy"]["performance"]["analysis"]
    assert p9["total_trades"] == pk["total_trades"] == 1108
    assert p9["total_closed_trades"] == pk["total_closed_trades"] == 22
    assert pytest.approx(p9["end_value"], rel=1e-6) == pk["end_value"]


@pytest.mark.xfail(strict=False, reason="khác biệt chấp nhận: cơ chế bảo toàn vị thế của Nora (quyết định 07/10/2026)")
def test_kema_long_matches_xno(monkeypatch):
    ref = _load("KEMA_long.json")
    out = _run(ref["strategy"]["code"], monkeypatch)
    perf = ref["strategy"]["performance"]
    got = out["metrics"]["simulate"]["xno"]
    assert got["cumulative_return"] == pytest.approx(perf["performance"]["cumulative_return"], rel=0.05)
    assert abs(got["max_drawdown"] - perf["performance"]["max_drawdown"]) <= 0.03
