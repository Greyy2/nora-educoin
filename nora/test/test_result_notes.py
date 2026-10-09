"""metrics/charts.build_notes: mỗi ghi chú chứa đúng số đo của lần chạy (không số chép tay), mục thiếu số đo thì vắng."""
import json
import os

from backend.crawl import store
from backend.metrics.charts import build_notes

REC = os.path.join(os.path.dirname(__file__), "fixtures", "result_notes_sample.json")


def _rec():
    r = store.read_json(os.path.abspath(REC))
    if not r or "explain" not in r:
        import pytest
        pytest.skip("chưa có kết quả Education chạy sẵn kèm explain")
    return r


def test_notes_quote_run_numbers():
    r = _rec()
    n = build_notes(r["explain"], r)
    m = r["metrics"]["simulate"]
    assert f"{m['sharpe']:,.2f}" in n["metrics"]["sharpe"] and f"{m['sharpe']:,.2f}" in n["summary"]
    assert f"{m['mdd_pct']:,.2f}" in n["metrics"]["mdd_pct"] and f"{m['mdd_pct']:,.2f}" in n["summary"] and f"{m['mdd_pct']:,.2f}" in n["equity"]
    sa = r["diagnostics"]["signal_activity"]
    for k, c in sa["exit_reason_counts"].items():
        assert k in n["exits"] and f"({c} lệnh)" in n["exits"]
    assert next(x["action_vi"] for x in r["explain"]["rules"] if x["type"].startswith("entry")) in n["metrics"]["ret_pct"]


def test_fixture_notes_numbers_all_come_from_result():
    r = _rec()
    _check_numbers(r, build_notes(r["explain"], r))


def test_notes_deterministic_and_degrade():
    r = _rec()
    assert build_notes(r["explain"], r) == build_notes(r["explain"], r)
    assert build_notes({}, {}) == {"metrics": {}}


# ─── ghi chú phải sinh từ CHÍNH lần chạy: khác số liệu thì khác chữ; mọi số trích dẫn có trong kết quả ───
import re  # noqa: E402

import pytest  # noqa: E402

from backend.metrics.charts import NOTE_TOUR  # noqa: E402
from test_custom_backtest import CODE_1H, _params, market  # noqa: E402,F401

CODE_EMA = '''
class Ema(SimpleAlgorithm):
    timeframe = "4h"
    fast = 3
    slow = 8
    def __algorithm__(self):
        close = self.data.pv_close
        f = self.feat.ema(close, self.fast)
        s = self.feat.ema(close, self.slow)
        self.set_positions(self.op.crossed_below(f, s), position=0)
        self.set_positions(self.op.crossed_above(f, s), position=1)
'''


def _run(code, **kw):
    """Đúng đường nút Chạy: build_job('custom_backtest') -> tasks.run_custom."""
    from backend.optimize.process import tasks
    from backend.routes import process as job_routes
    cfg = {"start": "2023-11-22", "end": "2023-12-18", "symbols": ["AAA", "BBB", "CCC"], "initial_capital": 10_000, **kw, "code": code}
    tasks._clear_data_caches()
    return tasks.run_custom(job_routes.build_job("custom_backtest", cfg))


_NUM = re.compile(r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)          # ngày
    out = set()
    for t in _NUM.findall(text):
        t = t.replace(",", "").replace("−", "-").lstrip("+")
        out.add(abs(float(t)))
    return out


def _result_numbers(r):
    """Mọi số trong kết quả (đệ quy) + làm tròn 0/1/2/3 chữ số, ×100 cho tỉ lệ (drawdown), số trong logic đã biên dịch."""
    vals = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.add(abs(float(o)))
    walk({k: v for k, v in r.items() if k != "explain"})
    ser = r.get("series") or {}
    vals |= {abs(round(float(v) * 100, 2)) for v in (ser.get("drawdown") or [])}
    vals |= _numbers(json.dumps(r.get("explain") or {}, ensure_ascii=False))
    return vals


def _check_numbers(r, notes):
    allowed = _result_numbers(r)

    def ok(x):
        return any(abs(x - v) <= 0.0051 + 1e-9 * abs(v) or abs(x - round(v)) < 1e-9 for v in allowed)
    bad = []
    texts = {k: v for k, v in notes.items() if isinstance(v, str)}
    texts.update({f"metrics.{k}": v for k, v in notes["metrics"].items()})
    for key, txt in texts.items():
        bad += [(key, x) for x in sorted(_numbers(txt)) if not ok(x)]
    assert not bad, bad


def test_notes_numbers_all_come_from_result(market):
    for code in (CODE_1H, CODE_EMA):
        r = _run(code)
        n = build_notes(r["explain"], r)
        assert n["summary"] and n["equity"]
        _check_numbers(r, n)


def test_notes_differ_across_samples_and_parameters(market):
    a, b = _run(CODE_1H), _run(CODE_EMA)
    c = _run(CODE_EMA.replace("slow = 8", "slow = 14"))
    na, nb, nc = (build_notes(x["explain"], x) for x in (a, b, c))
    for x, y in ((na, nb), (nb, nc)):
        assert x["summary"] != y["summary"]
        for k in set(x) & set(y):
            if k == "metrics":
                continue
            if _numbers(x[k]) != _numbers(y[k]) or k == "summary":
                assert x[k] != y[k], k
    # đổi tham số -> quy tắc được diễn giải đổi theo ("EMA 14" thay "EMA 8") và con số đổi theo
    assert "giá đóng cửa, 14)" in nc["summary"] and "giá đóng cửa, 14)" not in nb["summary"] and "giá đóng cửa, 8)" in nb["summary"]
    assert b["program_hash"] != c["program_hash"] and b["metrics"]["simulate"] != c["metrics"]["simulate"]
    # không câu nào giống hệt giữa các lần chạy khác nhau trừ nhãn thuần tuý (ghi chú không số liệu)
    for k in set(nb) & set(nc) & {t["notes_key"] for t in NOTE_TOUR}:
        if nb[k] == nc[k]:
            assert not _numbers(nb[k]), k
    for k in set(nb["metrics"]) & set(nc["metrics"]):
        if nb["metrics"][k] == nc["metrics"][k]:
            assert not _numbers(nb["metrics"][k]), k


def test_run_button_path_edit_param_gives_new_result(market):
    base = _run(CODE_EMA)
    again = _run(CODE_EMA)
    assert again["program_hash"] == base["program_hash"] and again["metrics"] == base["metrics"]       # cùng mã -> cùng kết quả
    assert again["final_equity"] == base["final_equity"] and again["trades"] == base["trades"]
    edited = _run(CODE_EMA.replace("fast = 3", "fast = 5").replace("slow = 8", "slow = 20"))
    assert edited["program_hash"] != base["program_hash"]
    assert edited["metrics"]["simulate"] != base["metrics"]["simulate"] or edited["trades"] != base["trades"]
    assert edited["alpha_id"] != base["alpha_id"]
    pos = _run(CODE_EMA, position={"risk_per_trade_pct": 0.1})                                           # đổi cấu hình chạy -> kết quả mới
    assert pos["metrics"]["simulate"] != base["metrics"]["simulate"] or pos["trades"] != base["trades"]


def test_tour_is_five_simple_steps():
    assert [t["key"] for t in NOTE_TOUR] == ["summary", "equity", "yearly", "by_symbol", "train_test"]
    from backend.metrics.charts import EDUCATION_HIDDEN_SECTIONS
    assert set(EDUCATION_HIDDEN_SECTIONS) == {"benchmark", "holding", "pnl_structure"}
    assert not {t["key"] for t in NOTE_TOUR} & set(EDUCATION_HIDDEN_SECTIONS)


def test_summary_cap_skip_sentence():
    r = json.loads(json.dumps(_rec()))
    r["config"] = {**(r.get("config") or {}), "risk": {"max_positions": 3}}
    r["risk_blocked_attempts"] = 7
    s = build_notes(r["explain"], r)["summary"]
    assert "7 lần tín hiệu vào bị bỏ qua vì danh mục đã giữ đủ 3 vị thế." in s
    allowed = _result_numbers(r)   # (fixture recorded: other sections not number-checked here)
    assert {7.0, 3.0} <= allowed and {7.0, 3.0} <= _numbers("7 lần ... 3 vị thế")
    for v in (0, None):
        r["risk_blocked_attempts"] = v
        assert "bị bỏ qua" not in build_notes(r["explain"], r)["summary"]
