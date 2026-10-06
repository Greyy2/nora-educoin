"""P6.3: Account + PositionBook chỉ đổi trạng thái qua sự kiện -> phát lại chuỗi sự kiện của lần chạy gốc vào
sổ vốn + book MỚI phải cho đúng từng bit: ledger (equity, reserved, peak, rejected) và mọi trường PositionModel/OrderModel.
Chạy đường Python (PositionTracker) trên nến tổng hợp, cấu hình ngẫu nhiên, nhiều tracker dùng chung một sổ vốn."""
import dataclasses
import random
from collections import Counter

import numpy as np
import pytest

from backend.core.execute.account import Account, PositionBook
from backend.core.execute.events import Fill, FundingApplied, OrderRejected, PositionMarked
from backend.core.execute.ledger import CapitalLedger
from backend.core.execute.models import PositionType
from backend.core.execute.tracker import PositionTracker
from backend.core.params.builder import build_params

M = 60_000


def test_capital_ledger_is_account():
    assert CapitalLedger is Account


def _position(rng, side):
    perp = side == "SHORT" or rng.random() < 0.8
    p = {"market": "perp" if perp else "spot", "leverage": rng.choice([1, 3, 10, 25, 60]) if perp else 1,
         "maintenance_margin_rate": rng.choice([0.005, 0.02]),
         "stop_loss_rate": 0.0 if rng.random() < 0.2 else round(rng.uniform(0.5, 4.0), 2),
         "take_profit_rate": 0.0 if rng.random() < 0.4 else round(rng.uniform(0.4, 4.0), 2),
         "trailing_stop": 0.0 if rng.random() < 0.5 else round(rng.uniform(0.5, 3.0), 2),
         "trailing_activation_pct": rng.choice([0.0, 0.5, 1.5]),
         "timeout": rng.choice([0, 0, 90, 600]), "cooldown": rng.choice([0, 0, 10]),
         "stop_fill": rng.choice(["level", "extreme"]), "limit_through_pct": rng.choice([0.0, 0.0, 0.05]),
         "order_size_pct": rng.choice([5.0, 20.0, 45.0]), "exit_unit": "pct"}
    layers = rng.choice([0, 0, 2, 4])
    if layers:
        mult = rng.choice([1.0, 1.5, 2.0])
        p.update(dca_max_layers=layers, dca_step_pct=round(rng.uniform(0.3, 2.0), 2), dca_size_multiplier=mult,
                 order_size_pct=2.0 if mult == 2.0 else 5.0)       # build_params từ chối DCA vượt ngân sách vốn
    if rng.random() < 0.4:
        p.update(sizing="risk", risk_per_trade_pct=round(rng.uniform(0.3, 3.0), 2), max_notional_pct=rng.choice([100.0, 400.0]))
        if not p["stop_loss_rate"]:
            p["stop_loss_rate"] = 2.0
    return p


def _bars(rng, n, sigma):
    px, out = 100.0, []
    for i in range(n):
        o = px
        c = o * float(np.exp(rng.gauss(0, sigma)))
        h = max(o, c) * (1 + abs(rng.gauss(0, sigma / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, sigma / 2)))
        out.append((i * M, o, h, l, c))
        px = c
    return out


def _fields(obj):
    """Mọi trường dataclass -> chuỗi repr (so từng bit: repr float khứ hồi, phân biệt -0.0)."""
    return repr(dataclasses.asdict(obj))


def _run(seed):
    rng = random.Random(seed)
    initial = rng.choice([1_000.0, 10_000.0])
    ledger = Account(initial)
    events, trackers, closed = [], [], []
    for slot in range(4):
        side = rng.choice(["LONG", "SHORT"])
        params = build_params("f", {"match": [], "stop": []}, side, _position(rng, side), "cex")
        tr = PositionTracker(slot, 7, f"S{slot}", "f", params, PositionType.LONG if side == "LONG" else PositionType.SHORT,
                             initial_capital=initial, ledger=ledger)
        tr.book.slot, tr.book.events = slot, events
        trackers.append(tr)
    sigma = rng.choice([0.002, 0.006, 0.015])
    bars = [_bars(rng, 1500, sigma) for _ in trackers]
    p_sig = rng.choice([0.01, 0.05])
    for i in range(1500):
        for k, tr in enumerate(trackers):
            t, o, h, l, c = bars[k][i]
            pos = tr.on_bar(t, o, h, l, c, entry_signal=rng.random() < p_sig, stop_signal=rng.random() < p_sig / 4)
            if pos is not None:
                closed.append(pos)
            if i % 480 == 479:
                tr.apply_funding(round(rng.uniform(-0.002, 0.002), 5), c, t)
    for k, tr in enumerate(trackers[:2]):                       # hai tracker đóng cuối kỳ, hai còn mở (nếu đang mở)
        pos = tr.force_close(bars[k][-1][0], bars[k][-1][4])
        if pos is not None:
            closed.append(pos)
    return initial, ledger, events, trackers, closed


@pytest.mark.parametrize("seed", range(14))
def test_replay_events_reproduces_ledger_and_models_bit_for_bit(seed):
    initial, ledger, events, trackers, closed = _run(seed)
    fresh = Account(initial)
    books = [PositionBook(fresh, tr.account_id, tr.campaign_id, tr.symbol, tr.flow_name, tr.pos_type, slot=tr.book.slot)
             for tr in trackers]
    replay_closed = []
    for ev in events:
        pos = books[ev.slot].apply(ev)
        if pos is not None:
            replay_closed.append(pos)
    assert (repr(fresh.equity), repr(fresh.reserved), repr(fresh.peak), fresh.rejected) == (
        repr(ledger.equity), repr(ledger.reserved), repr(ledger.peak), ledger.rejected)
    assert [_fields(p) for p in replay_closed] == [_fields(p) for p in closed]
    for tr, bk in zip(trackers, books):
        assert [_fields(o) for o in bk.orders] == [_fields(o) for o in tr.orders]
        assert (bk.position is None) == (tr.position is None)
        if tr.position is not None:
            assert _fields(bk.position) == _fields(tr.position)
        # entry_equity khi đang đóng chỉ là vết của lần _open thất bại (tracker ghi trước khi biết vào được lệnh) — không phải kế toán
        for name in ("qty", "avg", "margin_used", "fees_paid", "layer_count", "last_fill", "reserved_here",
                     "funding_paid", "entry_time") + (("entry_equity",) if tr.position is not None else ()):
            assert repr(getattr(bk, name)) == repr(getattr(tr, name)), name


def test_replay_covers_every_event_kind():
    """Các seed trên phải thực sự đi qua mọi nhánh kế toán (không phát lại một chuỗi nghèo nàn)."""
    kinds, reasons = Counter(), Counter()
    for seed in range(14):
        for ev in _run(seed)[2]:
            if isinstance(ev, Fill):
                kinds[ev.kind] += 1
            elif isinstance(ev, OrderRejected):
                reasons[ev.reason] += 1
            else:
                kinds[type(ev).__name__] += 1
    for need in ("entry", "dca", "sl", "tp", "trail", "timeout", "liq", "end", "exit", "FundingApplied", "PositionMarked"):
        assert kinds[need] > 0, (need, dict(kinds))
    assert reasons["budget"] > 0 and reasons["capital"] > 0, dict(reasons)
    assert FundingApplied and PositionMarked  # noqa: B015  (import dùng cho kiểm kiểu sự kiện)
