"""P6.4: đường SỰ KIỆN (SimVenue + PositionManager + Account/PositionBook) phải cho kết quả BIT-IDENTICAL với PositionTracker.on_bar.

Oracle = PositionTracker sản xuất (đã bit-identical với RefPositionTracker / kernel nhờ test_kernel_parity) chạy từng nến; đường event chạy
trên CÙNG nến + tín hiệu + trần rủi ro + funding + kill. Bảy tầng, mỗi tầng chỉ bật tính năng của nó (và các tầng trước):
  4a vào/thoát market, hết thời gian, funding, cooldown, trần danh mục      4b SL (+ sizing theo rủi ro)
  4c DCA: vòng settle trong nến, từ chối ngân sách/vốn                       4d TP (bỏ qua nến có DCA khớp)
  4e trailing (đỉnh các nến trước)                                           4f thanh lý (perp đòn bẩy cao)
  4g limit_through, stop_fill='extreme', gap (open vượt mức), hoà mức thoát-trước-DCA
Mỗi cấu hình: 1 slot hoặc 3 slot dùng chung MỘT Account. So SÁNH TỪNG BIT (float.hex): mọi trường PositionModel đã đóng, từng nến mọi trạng thái
của slot + sổ vốn (equity, reserved, peak, rejected), chuỗi OrderModel, vị thế còn mở, bộ đếm, chuỗi sự kiện của book, và id (lệch so với mốc
đầu lần chạy phải y hệt -> `_next_id()` được gọi đúng thứ tự). Test cuối kiểm các nhánh của từng tầng thực sự bị chạm (không "xanh rỗng").
Số cấu hình mỗi tầng đổi bằng NORA_EVENT_CONFIGS (mặc định 40). Mismatch -> sửa đường event, KHÔNG nới so sánh.
"""
import dataclasses
import math
import os
import random
import time
from collections import Counter
from typing import Any, Dict, List

import pytest

from backend.core.execute import policy
from backend.core.execute.account import Account
from backend.core.execute.events import Fill, OrderRejected
from backend.core.execute.manager import PositionManager
from backend.core.execute.models import PositionType
from backend.core.execute.sim_venue import SimVenue
from backend.core.execute.tracker import PositionTracker, _next_id
from backend.core.execute.venue import OrderKind
from backend.core.params.builder import build_params
from test_kernel_parity import _fit_dca_budget, rand_position

M = 60_000
STAGES = "abcdefg"
N_CONFIGS = int(os.environ.get("NORA_EVENT_CONFIGS", "40"))
_COV: Dict[str, Counter] = {s: Counter() for s in STAGES}
_RAN: Counter = Counter()
_TIME: Dict[str, float] = {}


# ─── Venue đếm nhánh (chỉ để kiểm phủ; không đổi hành vi) ───────────────────
class CountingVenue(SimVenue):
    def __init__(self, cov: Counter):
        super().__init__()
        self.cov = cov

    def next_event(self, slot):
        st = self._slots[slot]
        legacy = st.intrabar_path == "adverse_first"
        if legacy and not st.market and st.view is not None and st.phase == "adverse":
            self._count_tie(st)
        ev = super().next_event(slot)
        if not legacy and isinstance(ev, Fill):     # đường ohlc / adaptive: các nhánh riêng của nó
            if ev.kind == "tp" and ev.liquidity == "taker":
                self.cov["r3_close_tp"] += 1
            if ev.kind == "tp" and ev.liquidity == "maker":
                self.cov["tp_maker_path"] += 1
                if st.dca_filled:
                    self.cov["tp_after_dca_same_bar"] += 1
                if st.tp_need != st.tp_lv:
                    self.cov["limit_through_tp"] += 1
            if ev.kind in ("sl", "trail", "liq") and st.dca_filled:
                self.cov["stop_after_dca_same_bar"] += 1
            if ev.kind == "trail" and ev.raw_price != st.o:
                self.cov["trail_path"] += 1
        if isinstance(ev, Fill) and ev.kind in ("dca", "sl", "trail", "liq") and ev.raw_price == st.o:
            self.cov["gap_fill"] += 1
        if isinstance(ev, Fill) and ev.kind in ("sl", "trail") and st.stop_fill == "extreme" and ev.raw_price != st.o \
                and ev.raw_price == (st.l if st.view.is_long else st.h):
            self.cov["extreme_fill"] += 1
        return ev

    def _count_tie(self, st):
        is_long = st.view.is_long
        adverse = st.l if is_long else st.h
        evs = []
        for kind, name, prio in ((OrderKind.DCA, "dca", 1), (OrderKind.SL, "sl", 0), (OrderKind.TRAIL, "trail", 0)):
            od = self._first(st, kind)
            if od is not None:
                evs.append((od.level if math.isnan(od.trigger) else od.trigger, prio, name))
        reached = [e for e in evs if policy.reached(e[0], adverse, is_long)]
        if len(reached) >= 2:
            level, _, kind = policy.pick_first_touched(reached, is_long)
            if kind != "dca" and any(e[2] == "dca" and e[0] == level for e in reached):
                self.cov["tie_exit_over_dca"] += 1

    def _match_favorable(self, slot, st):
        if st.intrabar_path != "adverse_first":
            return super()._match_favorable(slot, st)
        tp = self._first(st, OrderKind.TP)
        if tp is not None and st.dca_filled:
            need = tp.level if math.isnan(tp.trigger) else tp.trigger
            if policy.tp_hit(st.h if st.view.is_long else st.l, need, st.view.is_long):
                self.cov["tp_skipped_on_dca_bar"] += 1
        ev = super()._match_favorable(slot, st)
        if ev is not None and tp is not None and not math.isnan(tp.trigger) and tp.trigger != tp.level:
            self.cov["limit_through_tp"] += 1
        return ev


# ─── Sinh cấu hình / kịch bản ────────────────────────────────────────────────
def _position(rng: random.Random, n: int, side: str) -> Dict[str, Any]:
    """Tham số vị thế của tầng n (0 = 4a ... 6 = 4g): tính năng của tầng sau bị tắt."""
    p = rand_position(rng, side)
    if n < 1:
        p["stop_loss_rate"], p["sizing"] = 0.0, "margin_pct"
    if n < 2:
        p["dca_max_layers"], p["dca_step_pct"] = 0, 0.0
    if n < 3:
        p["take_profit_rate"] = 0.0
    if n < 4:
        p["trailing_stop"], p["trailing_activation_pct"] = 0.0, 0.0
    if n < 5 and p["market"] == "perp":
        p["leverage"] = rng.choice([1, 2])               # giá thanh lý quá xa -> tầng 4f chưa bật
    if n >= 5 and p["market"] == "perp" and rng.random() < 0.6:
        p["sizing"], p["leverage"] = "margin_pct", rng.choice([10, 25, 50, 125])
        p["order_size_pct"] = rng.choice([5.0, 20.0, 50.0])
    if n < 6:
        p["limit_through_pct"], p["stop_fill"] = 0.0, "level"
    elif p["exit_unit"] == "pct" and p["dca_max_layers"] and p["stop_loss_rate"] > 0 and rng.random() < 0.3:
        p["dca_step_pct"] = p["stop_loss_rate"]          # DCA và SL cùng mức: kiểm hoà -> thoát trước
    _fit_dca_budget(rng, p)
    return p


def _make_config(seed: int, n: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    n_slots = rng.choice([1, 1, 3])
    initial = rng.choice([1_000.0, 10_000.0])
    slots = []
    for _ in range(n_slots):
        side = rng.choice(["LONG", "SHORT"])
        params = build_params("f", {"match": [], "stop": []}, side, _position(rng, n, side), "cex")
        if n >= 2:
            params = dataclasses.replace(params, max_capital_usage=rng.choice([1.0, 1.0, 0.6, 0.3]))
        slots.append((side, params))
    sigma = rng.choice([0.002, 0.005, 0.01, 0.02])
    gap = sigma * rng.choice([1.0, 3.0]) if n >= 6 else 0.0
    nbars = rng.choice([900, 1500, 2400])
    p_sig = rng.choice([0.01, 0.05, 0.2])
    bars: List[List[tuple]] = []
    for _ in range(n_slots):
        px, out = 100.0, []
        for i in range(nbars):
            o = px * math.exp(rng.gauss(0, gap)) if gap else px
            c = o * math.exp(rng.gauss(0, sigma))
            h = max(o, c) * (1 + abs(rng.gauss(0, sigma / 2)))
            l = min(o, c) * (1 - abs(rng.gauss(0, sigma / 2)))
            out.append((i * M, o, h, l, c))
            px = c
        bars.append(out)
    inf = float("inf")
    steps = []     # steps[i][k] = tham số on_bar của slot k ở nến i
    for i in range(nbars):
        row = []
        for _ in range(n_slots):
            vol = float("nan") if (i < 30 and rng.random() < 0.8) else sigma * 100.0 * rng.uniform(2.0, 6.0)
            caps = (inf, inf, 1.0)
            if rng.random() < 0.15:
                caps = (rng.choice([0.0, 200.0, 2000.0, inf]), rng.choice([0.0, 5.0, 50.0, inf]), rng.choice([1.0, 1.0, 0.5, 0.25]))
            row.append({"entry": rng.random() < p_sig, "stop": rng.random() < p_sig / 4, "can_open": rng.random() > 0.1,
                        "vol": vol, "dca_gate": rng.random() < 0.75, "caps": caps})
        steps.append(row)
    fund_every = rng.choice([97, 480])
    funding = {i: round(rng.uniform(-0.003, 0.003), 5) for i in range(fund_every - 1, nbars, fund_every)}
    return {"initial": initial, "slots": slots, "bars": bars, "steps": steps, "funding": funding, "nbars": nbars,
            "kill_at": rng.randrange(nbars // 3, nbars) if rng.random() < 0.5 else None,
            "close_at_end": rng.random() < 0.6, "seed": seed}


# ─── Chạy một "thế giới" và ghi vết ──────────────────────────────────────────
def _hx(v):
    if isinstance(v, float):
        return v.hex()
    if isinstance(v, (list, tuple)):
        return [_hx(x) for x in v]
    return v


def _canon(obj, base: int):
    """Dataclass -> dict so được từng bit: float.hex, id trừ mốc đầu lần chạy (id Python sinh theo thứ tự gọi `_next_id`)."""
    out = {}
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        if f.name in ("order_id", "result_id", "position_id"):
            v = 0 if isinstance(obj, OrderRejected) else v - base
        elif hasattr(v, "name") and hasattr(v, "value"):
            v = v.name
        out[f.name] = _hx(v)
    return out


_ATTRS = ("qty", "avg", "margin_used", "fees_paid", "last_fill", "planned_risk", "pos_leverage", "max_capital", "funding_paid",
          "peak", "mae_usd", "next_margin", "unit_pct", "sl_pct", "tp_pct", "trail_pct", "trail_activation_pct", "dca_steps",
          "layer_count", "is_open", "pending_entry", "pending_exit", "last_close_time", "dca_rejected", "skipped_no_vol", "dca_ok",
          "entry_equity", "reserved_here", "entry_time")


def _snap(actor, acct: Account):
    return ([_hx(getattr(actor, a)) for a in _ATTRS],
            [acct.equity.hex(), acct.reserved.hex(), acct.peak.hex(), acct.rejected, acct.free().hex()])


def _run_world(kind: str, cfg: Dict[str, Any], cov: Counter) -> Dict[str, Any]:
    base = _next_id()
    acct = Account(cfg["initial"])
    events: List[Any] = []
    venue = CountingVenue(cov) if kind == "event" else None
    actors = []
    for k, (side, params) in enumerate(cfg["slots"]):
        tr = PositionTracker(k, 7, f"S{k}", "f", params, PositionType.LONG if side == "LONG" else PositionType.SHORT,
                             initial_capital=cfg["initial"], ledger=acct)
        if kind == "oracle":
            tr.book.slot, tr.book.events = k, events
            actors.append(tr)
        else:
            actors.append(PositionManager(tr, venue, slot=k, account=acct, events=events))
    trace, closed = [], []
    n_slots = len(actors)
    for i in range(cfg["nbars"]):
        for k, a in enumerate(actors):
            t, o, h, l, c = cfg["bars"][k][i]
            s = cfg["steps"][i][k]
            if i in cfg["funding"]:
                trace.append(("funding", k, i, _hx(a.apply_funding(cfg["funding"][i], o, t))))
            a.max_new_notional, a.max_new_risk, a.risk_scale = s["caps"]
            pos = a.on_bar(t, o, h, l, c, entry_signal=s["entry"], stop_signal=s["stop"], can_open=s["can_open"],
                           vol=s["vol"], dca_gate=s["dca_gate"])
            a.max_new_notional = a.max_new_risk = float("inf")
            a.risk_scale = 1.0
            if pos is not None:
                closed.append((k, i, pos))
            trace.append((k, i, _snap(a, acct), _canon(pos, base) if pos is not None else None,
                          _hx(a.unrealized_pnl_usd(c)) if a.is_open else None))
        if cfg["kill_at"] == i:
            for k, a in enumerate(actors):
                a.pending_entry = False
                pos = a.force_close(cfg["bars"][k][i][0], cfg["bars"][k][i][4], "Kill switch danh mục")
                if pos is not None:
                    closed.append((k, i, pos))
                trace.append(("kill", k, i, _snap(a, acct), _canon(pos, base) if pos is not None else None))
    last = cfg["nbars"] - 1
    if cfg["close_at_end"]:
        for k, a in enumerate(actors[: max(1, n_slots - 1)]):
            pos = a.force_close(cfg["bars"][k][last][0], cfg["bars"][k][last][4])
            if pos is not None:
                closed.append((k, last, pos))
            trace.append(("end", k, _snap(a, acct), _canon(pos, base) if pos is not None else None))
    final = []
    for a in actors:
        final.append({"orders": [_canon(o, base) for o in a.orders],
                      "position": _canon(a.position, base) if a.position is not None else None,
                      "state": _snap(a, acct)})
    return {"trace": trace, "final": final, "events": [(type(e).__name__, _canon(e, base)) for e in events],
            "closed": closed, "acct": acct}


def _first_diff(a: list, b: list) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            if isinstance(x, tuple) and isinstance(y, tuple) and len(x) == len(y):
                for j, (xj, yj) in enumerate(zip(x, y)):
                    if xj != yj:
                        if isinstance(xj, tuple) and len(xj) == 2 and isinstance(xj[0], list):
                            names = list(_ATTRS) + ["acct.equity", "acct.reserved", "acct.peak", "acct.rejected", "acct.free"]
                            xs, ys = xj[0] + xj[1], yj[0] + yj[1]
                            d = {names[q]: (xs[q], ys[q]) for q in range(len(xs)) if xs[q] != ys[q]}
                            return f"bước {i} (phần {j}): {d}"
                        if isinstance(xj, dict) and isinstance(yj, dict):
                            return f"bước {i} (phần {j}): " + str({q: (xj[q], yj.get(q)) for q in xj if xj[q] != yj.get(q)})
                        return f"bước {i} (phần {j}): oracle={xj!r} event={yj!r}"
            if isinstance(x, tuple) and isinstance(y, dict):
                return f"bước {i}"
            return f"bước {i}: oracle={x!r} event={y!r}"
    return f"độ dài khác: oracle={len(a)} event={len(b)}"


def _tally(stage: str, cfg, oracle, cov: Counter) -> None:
    c = cov
    for _, _, pos in oracle["closed"]:
        c[f"reason.{pos.close_reason}"] += 1
        c[f"status.{pos.status.name}"] += 1
        c[f"side.{pos.pos_type.name}"] += 1
        if pos.layers > 1:
            c["dca_filled"] += 1
        if pos.funding_usd:
            c["funding"] += 1
        if pos.status.name == "SL" and pos.close_reason == "Trailing stop":
            c["trail_loss"] += 1
        if pos.status.name == "TP" and pos.close_reason == "Trailing stop":
            c["trail_gain"] += 1
        if pos.mae_pct < 0:
            c["mae"] += 1
    for f in oracle["final"]:
        for o in f["orders"]:
            c[f"liquidity.{o['liquidity']}"] += 1
    for name, ev in oracle["events"]:
        if name == "OrderRejected":
            c[f"rejected.{ev['kind']}.{ev['reason']}"] += 1
    for _, params in cfg["slots"]:
        if params.market == "spot":
            c["spot"] += 1
        if params.limit_through_pct:
            c["limit_through_cfg"] += 1
    c["configs"] += 1
    st = [f["state"][0] for f in oracle["final"]]
    if any(s[_ATTRS.index("dca_rejected")] for s in st):
        c["dca_rejected"] += 1
    if any(s[_ATTRS.index("skipped_no_vol")] for s in st):
        c["skipped_no_vol"] += 1
    if oracle["acct"].rejected:
        c["ledger_rejected"] += 1
    if len(cfg["slots"]) > 1:
        c["multi_slot"] += 1


def _check_stage(stage: str, first_seed: int) -> None:
    n = STAGES.index(stage)
    cov = _COV[stage]
    ran = tries = 0
    t0 = time.time()
    while ran < N_CONFIGS:
        seed = first_seed + tries
        tries += 1
        assert tries < N_CONFIGS * 3, "quá nhiều cấu hình bị build_params từ chối"
        try:
            cfg = _make_config(seed, n)
        except ValueError:
            continue
        oracle = _run_world("oracle", cfg, cov)
        event = _run_world("event", cfg, cov)
        label = f"stage 4{stage} seed={seed}"
        assert oracle["trace"] == event["trace"], f"{label}: {_first_diff(oracle['trace'], event['trace'])}"
        assert oracle["final"] == event["final"], f"{label}: final khác"
        assert oracle["events"] == event["events"], f"{label}: {_first_diff(oracle['events'], event['events'])}"
        _tally(stage, cfg, oracle, cov)
        ran += 1
    _RAN[stage] = ran
    _TIME[stage] = time.time() - t0


@pytest.mark.parametrize("stage", list(STAGES))
def test_event_path_matches_tracker(stage):
    _check_stage(stage, STAGES.index(stage) * 100_000)


# ─── Phủ nhánh ───────────────────────────────────────────────────────────────
_NEED = {
    "a": ["reason.Tín hiệu thoát (AST stop)", "reason.Hết thời gian giữ lệnh", "reason.End of Backtest", "reason.Kill switch danh mục",
          "funding", "skipped_no_vol", "side.SHORT", "spot", "multi_slot", "liquidity.taker", "rejected.entry.no_margin"],
    "b": ["reason.Stop-loss (từ giá TB)", "status.SL", "mae"],
    "c": ["dca_filled", "liquidity.maker", "dca_rejected", "rejected.dca.budget", "rejected.dca.capital", "ledger_rejected", "stop_after_dca_same_bar"],
    "d": ["reason.Take-profit (từ giá TB)", "status.TP", "tp_skipped_on_dca_bar", "tp_maker_path", "tp_after_dca_same_bar", "r3_close_tp"],
    "e": ["reason.Trailing stop", "trail_gain", "trail_loss", "trail_path"],
    "f": ["status.LIQ", "liquidity.liquidation", "reason.Thanh lý (perp)"],
    "g": ["gap_fill", "extreme_fill", "limit_through_cfg", "limit_through_tp", "tie_exit_over_dca"],
}


def test_zz_coverage_all_stage_branches_exercised():
    if any(_RAN[s] < N_CONFIGS for s in STAGES):
        pytest.skip("chưa chạy đủ các tầng (chạy cả file để kiểm phủ)")
    # phủ tích luỹ: tầng sau chứa luôn tính năng các tầng trước, nên nhánh của tầng x phải thấy ở chính tầng x hoặc sau đó
    missing = {}
    for i, stage in enumerate(STAGES):
        merged = Counter()
        for s in STAGES[i:]:
            merged.update(_COV[s])
        miss = [k for k in _NEED[stage] if not merged.get(k)]
        if miss:
            missing[stage] = miss
    assert not missing, f"nhánh chưa được phủ: {missing}; thống kê={ {s: dict(sorted(_COV[s].items())) for s in STAGES} }"
    print("COVERAGE", {s: dict(sorted(_COV[s].items())) for s in STAGES})
    print("WALL", {s: round(_TIME[s], 1) for s in STAGES}, "configs/stage", N_CONFIGS)
