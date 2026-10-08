"""P6.8a: đối soát cấp sự kiện sàn ↔ sim (backend/live/compare.compare_events)."""
import dataclasses

import pytest

from backend.core.models import Fill, OrderRejected
from backend.metrics import trades as C

H = 3_600_000
T0 = 1_700_000_000_000


def fill(slot, kind, t, price, *, oid=1, raw=None, notional=0.0, fee=0.0, **kw):
    return Fill(slot=slot, order_id=oid, kind=kind, t=t, price=price, raw_price=price if raw is None else raw, notional=notional,
                margin=0.0, fee=fee, slip=0.0, liquidity="taker", **kw)


def trade(slot, t, entry_px, close_kind, close_px, *, d_in=0.0, d_out=0.0, dt=5_000, fee_ex=0.0, fee_sim=0.0, oid=1):
    """Một vị thế LONG: (exec, sim). d_in/d_out = chênh GIÁ tuyệt đối của sàn so với sim."""
    sim = [fill(slot, "entry", t, entry_px, oid=oid, raw=entry_px * 0.9999, notional=1000.0, fee=fee_sim / 2),
           fill(slot, close_kind, t + 3 * H, close_px, oid=oid + 1, fee=fee_sim / 2)]
    ex = [fill(slot, "entry", t + dt, entry_px + d_in, oid=oid, notional=1000.0),
          fill(slot, close_kind, t + 3 * H + dt, close_px + d_out, oid=oid + 1, fee=fee_ex)]
    return ex, sim


def run(n, **kw):
    ex, sm = [], []
    for i in range(n):
        e, s = trade(i % 3, T0 + i * 10 * H, 100.0, "exit", 101.0, oid=10 * i, **kw)
        ex += e
        sm += s
    return ex, sm


def test_matching_with_time_tolerance_and_latency():
    ex, sm = trade(0, T0, 100.0, "exit", 101.0, dt=7_000)
    r = C.compare_events(ex, sm, "1h", sides={0: "LONG"})
    assert r["summary"]["matched"] == 2 and r["summary"]["only_exec"] == 0 and r["summary"]["only_sim"] == 0
    assert r["positions"]["matched"] == 1
    assert r["kinds"]["entry"]["latency_ms"]["mean"] == 7000.0
    # lệch quá 1 nến -> không ghép
    ex2 = [fill(0, "entry", T0 + 2 * H, 100.0, notional=1000.0), fill(0, "exit", T0 + 5 * H, 101.0)]
    r2 = C.compare_events(ex2, sm, "1h", sides={0: "LONG"})
    assert r2["summary"]["matched"] == 0 and r2["positions"]["only_exec"] == 1 and r2["positions"]["only_sim"] == 1
    # khung 4h thì ghép được
    assert C.compare_events(ex2, sm, "4h", sides={0: "LONG"})["positions"]["matched"] == 1


def test_bps_sign_long_short():
    # LONG: vào đắt hơn 0.1 / 100 = 10 bps (kém); đóng rẻ hơn 0.1/101 (kém)
    ex, sm = trade(0, T0, 100.0, "exit", 101.0, d_in=0.1, d_out=-0.101)
    r = C.compare_events(ex, sm, "1h", sides={0: "LONG"})
    assert r["kinds"]["entry"]["bps"]["mean"] == pytest.approx(10.0, abs=0.01)
    assert r["kinds"]["exit"]["bps"]["mean"] == pytest.approx(10.0, abs=0.01)
    # SHORT cùng giá lệch: vào đắt hơn = TỐT cho short (âm), đóng rẻ hơn = tốt
    r = C.compare_events(ex, sm, "1h", sides={0: "SHORT"})
    assert r["kinds"]["entry"]["bps"]["mean"] == pytest.approx(-10.0, abs=0.01)
    assert r["kinds"]["exit"]["bps"]["mean"] == pytest.approx(-10.0, abs=0.01)
    # side lấy từ trường dict `side`
    ex_d = [{**dataclasses.asdict(f), "side": "SHORT"} for f in ex]
    assert C.compare_events(ex_d, sm, "1h")["kinds"]["entry"]["bps"]["mean"] == pytest.approx(-10.0, abs=0.01)


def test_side_inferred_from_sl_and_unknown_skipped():
    ex, sm = trade(0, T0, 100.0, "sl", 98.0, d_out=-0.098)           # SL dưới giá vào -> LONG
    r = C.compare_events(ex, sm, "1h")
    assert r["kinds"]["sl"]["bps"]["mean"] == pytest.approx(10.0, abs=0.01)
    ex, sm = trade(0, T0, 100.0, "exit", 101.0, d_in=0.1)             # exit, sim entry price < raw? (raw=0.9999*px) -> price>raw = LONG
    assert C.compare_events(ex, sm, "1h")["kinds"]["entry"]["bps"]["mean"] == pytest.approx(10.0, abs=0.01)
    sm2 = [fill(0, "entry", T0, 100.0, notional=1000.0), fill(0, "exit", T0 + H, 101.0)]   # không suy ra được hướng
    ex2 = [fill(0, "entry", T0, 100.1, notional=1000.0), fill(0, "exit", T0 + H, 101.0)]
    r = C.compare_events(ex2, sm2, "1h")
    assert r["positions"]["side_unknown"] == 1 and r["kinds"]["entry"]["bps"]["n"] == 0 and r["kinds"]["entry"]["matched"] == 1


def test_only_one_side_counts_and_dca_sequence():
    sm = [fill(0, "entry", T0, 100.0, notional=1000.0), fill(0, "dca", T0 + H, 99.0, oid=2, notional=500.0),
          fill(0, "dca", T0 + 2 * H, 98.0, oid=3, notional=500.0), fill(0, "tp", T0 + 3 * H, 101.0, oid=4),
          fill(1, "entry", T0, 50.0, oid=5, notional=1000.0), fill(1, "timeout", T0 + 2 * H, 50.0, oid=6)]     # slot 1 chỉ có ở sim
    ex = [fill(0, "entry", T0 + 3_000, 100.0, notional=1000.0), fill(0, "dca", T0 + H + 3_000, 99.0, oid=2, notional=500.0),
          fill(0, "tp", T0 + 3 * H + 3_000, 101.0, oid=4),                                                  # thiếu dca thứ 2
          fill(2, "entry", T0, 10.0, oid=7, notional=100.0)]                                                # slot 2 chỉ có ở sàn
    r = C.compare_events(ex, sm, "1h", sides={0: "LONG", 1: "LONG", 2: "LONG"})
    k = r["kinds"]
    assert (k["entry"]["matched"], k["entry"]["only_sim"], k["entry"]["only_exec"]) == (1, 1, 1)
    assert (k["dca"]["matched"], k["dca"]["only_sim"], k["dca"]["only_exec"]) == (1, 1, 0)
    assert (k["tp"]["matched"], k["tp"]["only_sim"]) == (1, 0)
    assert k["timeout"]["only_sim"] == 1
    assert r["summary"]["matched"] == 3 and r["summary"]["only_sim"] == 3 and r["summary"]["only_exec"] == 1
    assert r["summary"]["only_sim_share"] == pytest.approx(3 / 6, abs=1e-4)
    assert r["positions"] == {"matched": 1, "only_exec": 1, "only_sim": 1, "side_unknown": 0}


def test_budgets_breach_flags_and_ok():
    ex, sm = trade(0, T0, 100.0, "tp", 103.0, d_in=0.0, d_out=-0.103, fee_ex=0.5, fee_sim=0.1)   # tp kém 10 bps (> 3), fee_gap 0.04 % (> 0.02)
    r = C.compare_events(ex, sm, "1h", sides={0: "LONG"})
    keys = {b["key"] for b in r["breaches"]}
    assert keys == {"tp_bps", "fee_gap_pct"} and r["ok"] is False
    assert r["fees"]["gap_pct_mean"] == pytest.approx(0.04, abs=1e-6)
    # nới ngân sách -> ok; ngân sách người dùng gộp lên mặc định
    r = C.compare_events(ex, sm, "1h", budgets={"tp": 20.0, "fee_gap_pct": 0.1}, sides={0: "LONG"})
    assert r["breaches"] == [] and r["ok"] is True and r["budgets"]["entry"] == 5.0 and r["budgets"]["tp"] == 20.0
    # only_sim_share vượt ngưỡng
    r = C.compare_events([], sm, "1h", sides={0: "LONG"})
    assert [b["key"] for b in r["breaches"]] == ["only_sim_share"] and r["enough"] is False


def test_equity_drift_and_rejections():
    r = C.compare_events([OrderRejected(slot=0, order_id=1, kind="entry", reason="budget")], [{"slot": 0, "order_id": 1, "kind": "dca", "reason": "capital"}], "1h",
                         exec_equity=[100.0, 101.0, 99.0], sim_equity=[100.0, 100.0, 100.0])
    assert r["equity"] == {"n": 3, "max_abs_drift_pct": 1.0}
    assert r["rejected"] == {"exec": {"budget": 1}, "sim": {"capital": 1}}
    assert C.compare_events([], [], "1h")["equity"] is None
    r = C.compare_events([], [], "1h", budgets={"equity_drift_pct": 0.5}, exec_equity=[{"t": 1, "equity": 101.0}], sim_equity=[(1, 100.0)])
    assert [b["key"] for b in r["breaches"]] == ["equity_drift_pct"]


def test_calibration_median_and_none_under_min_pairs():
    n = C.MIN_PAIRS
    ex, sm = [], []
    for i in range(n):          # trượt bất lợi tăng dần của lệnh vào: 1..n bps (trung vị = (n+1)/2 với n=30 -> 15.5)
        e, s = trade(i, T0 + i * 10 * H, 100.0, "exit", 101.0, d_in=100.0 * (i + 1) / 10_000, oid=10 * i)
        ex += e
        sm += s
    r = C.compare_events(ex, sm, "1h", sides={i: "LONG" for i in range(n)})
    assert r["enough"] is True and r["calibrated"]["entry"] == pytest.approx(15.5 / 10_000, rel=1e-3)
    assert r["calibrated"]["exit"] == 0.0 and r["calibrated"]["sl"] is None and r["calibrated"]["trail"] is None   # exit không lệch; sl/trail không có mẫu
    r = C.compare_events(ex[2:], sm[2:], "1h", sides={i: "LONG" for i in range(n)})                   # n-1 mẫu entry < MIN_PAIRS
    assert r["calibrated"]["entry"] is None


def test_sl_band_classification_and_dict_inputs():
    n = C.MIN_PAIRS
    ex, sm = [], []
    for i in range(n):
        level, extreme = 98.0, 97.0
        px = 98.0 - (0.5 if i % 2 else 0.0)                 # nửa khớp đúng level (better), nửa nằm giữa level và extreme
        e, s = trade(i, T0 + i * 10 * H, 100.0, "sl", level, oid=10 * i)
        e[1] = dataclasses.replace(e[1], price=px)
        s[1] = {**dataclasses.asdict(s[1]), "level": level, "extreme": extreme}                      # sim dạng dict (events.jsonl)
        ex += [dataclasses.asdict(f) for f in e]
        sm += s
    r = C.compare_events(ex, sm, "1h", sides={i: "LONG" for i in range(n)})
    band = r["sl_band"]
    assert band["better"] == 15 and band["between"] == 15 and band["worse"] == 0 and band["between_share"] == 0.5 and band["enough"]
    assert r["calibrated"]["sl"] == pytest.approx(0.5 * 0.5 / 98.0, rel=1e-2)                        # trung vị của {0, 51.02 bps} = 25.5 bps
    # không có extreme -> không phân lớp between/worse
    r = C.compare_events(ex, [{k: v for k, v in s.items() if k != "extreme"} if isinstance(s, dict) else s for s in sm], "1h",
                         sides={i: "LONG" for i in range(n)})
    assert r["sl_band"]["no_extreme"] == n and r["sl_band"]["between_share"] is None


def test_deterministic_and_dataclass_equals_dict():
    ex, sm = run(5, d_in=0.05)
    a = C.compare_events(ex, sm, "1h", sides={i: "LONG" for i in range(3)})
    b = C.compare_events([dataclasses.asdict(f) for f in reversed(ex)], [dataclasses.asdict(f) for f in sm], "1h", sides={i: "LONG" for i in range(3)})
    assert a == b == C.compare_events(ex, sm, "1h", sides={i: "LONG" for i in range(3)})
