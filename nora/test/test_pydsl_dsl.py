"""P7 — DSL chiến lược Python: ngữ nghĩa, lỗi có dòng/cột, đăng ký cột py_ vào kernels, cấu hình thực thi. Không cần dữ liệu thị trường."""
import numpy as np
import pandas as pd
import pytest

from backend.core import indicator as kernels
from backend.core.signal import DslError
from backend.alpha.compile import compile_code, compile_report
from backend.core import backtest as profiles

HEAD = "class S(SimpleAlgorithm):\n    def __algorithm__(self):\n"


def _body(*lines, attrs=""):
    return "class S(SimpleAlgorithm):\n" + attrs + "    def __algorithm__(self):\n" + "".join(f"        {ln}\n" for ln in lines)


def _df(n=300, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame({"open_time": np.arange(n, dtype=np.int64) * 86_400_000, "open": np.r_[c[0], c[:-1]], "high": c * 1.01, "low": c * 0.99,
                         "close": c, "volume": rng.uniform(1, 100, n)})


def _explicit(code, df=None):
    return compile_code(code, register=False).explicit(_df() if df is None else df)


# ─── mức vị thế ─────────────────────────────────────────────────────────────

def test_position_levels_are_collected_from_set_positions():
    assert compile_code(_body("c = self.data.pv_close", "self.set_positions(c > 0, position=1)"), register=False).levels == [1.0]
    assert compile_code(_body("c = self.data.pv_close", "self.set_positions(c > 0, position=0.5)"), register=False).levels == [0.5]
    both = _body("c = self.data.pv_close", "self.set_positions(c < 0, position=0)", "self.set_positions(c > 1, position=1)")
    assert compile_code(both, register=False).levels == [0.0, 1.0]


# ─── ngữ nghĩa ──────────────────────────────────────────────────────────────

def test_or_is_a_real_or_not_and():
    ex = _explicit(_body("close = self.data.pv_close", "self.set_positions((close > 1e9) | (close > 0), position=1)"))
    assert (ex == 1).all()
    ex = _explicit(_body("close = self.data.pv_close", "self.set_positions((close > 1e9) & (close > 0), position=1)"))
    assert np.isnan(ex).all()
    ex = _explicit(_body("close = self.data.pv_close", "self.set_positions(self.op.or_(close > 1e9, close > 0), position=1)"))
    assert (ex == 1).all()


def test_later_set_positions_overrides_earlier_and_unset_is_nan():
    df = _df()
    code = _body("close = self.data.pv_close", "self.set_positions(close > 0, position=0)", "self.set_positions(close > close.shift(1), position=1)")
    ex = _explicit(code, df)
    up = (df["close"] > df["close"].shift(1)).to_numpy()
    assert (ex[up] == 1).all() and (ex[~up] == 0).all()
    # đảo thứ tự: lệnh gọi sau (thoát) thắng
    code2 = _body("close = self.data.pv_close", "self.set_positions(close > close.shift(1), position=1)", "self.set_positions(close > 0, position=0)")
    assert (_explicit(code2, df) == 0).all()
    # không quy tắc nào kích hoạt -> NaN (giữ mức trước), target ffill, đầu chuỗi = 0
    code3 = _body("close = self.data.pv_close", "self.set_positions(close > close.shift(1), position=1)")
    prog = compile_code(code3, register=False)
    tgt = prog.target(df)
    assert tgt[0] == 0 and set(np.unique(tgt)) <= {0.0, 1.0}
    i = int(np.argmax(up))
    assert (tgt[i:][np.cumsum(up[i:]) > 0] == 1).all()


def test_entry_is_event_exit_is_state_columns():
    df = _df()
    prog = compile_code(_body("close = self.data.pv_close", "self.set_positions(self.op.crossed_below(close, close.shift(2)), position=0)",
                              "self.set_positions(self.op.crossed_above(close, close.shift(2)), position=1)"), register=False)
    cols = prog.columns_for(df)
    exp, tgt = prog.explicit(df), prog.target(df)
    assert ((exp > 0) == (cols["le"] == 1)).all() and ((tgt <= 0) == (cols["lx"] == 1)).all()
    assert ((exp < 0) == (cols["se"] == 1)).all() and ((tgt >= 0) == (cols["sx"] == 1)).all()
    assert cols["le"].sum() > 0 and cols["lx"].sum() > 0 and cols["se"].sum() == 0


def test_comparison_with_nan_is_false_and_no_silent_nan_columns():
    df = _df()
    df.loc[10:20, "close"] = np.nan
    cols = compile_code(_body("close = self.data.pv_close", "self.set_positions(close != 5, position=1)"), register=False).columns_for(df)
    assert cols["le"][10:21].sum() == 0 and not np.isnan(cols["le"]).any() and not np.isnan(cols["lx"]).any()


def test_division_by_zero_is_nan_not_inf():
    ex = _explicit(_body("close = self.data.pv_close", "r = close / (close - close)", "self.set_positions(r > 0, position=1)"))
    assert np.isnan(ex).all()


def test_time_of_day_open_and_close_ranges():
    n = 48
    df = pd.DataFrame({"open_time": np.arange(n, dtype=np.int64) * 3_600_000, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    code = _body('close = self.data.pv_close', "self.set_positions(close > 0, position=1)",
                 attrs='    timeframe = "1h"\n    position_open_ranges = ["09:00-12:00"]\n    position_close_ranges = ["20:00-22:00"]\n')
    ex = compile_code(code, register=False).explicit(df)
    label_h = (np.arange(n) + 1) % 24                        # nhãn = giờ đóng nến
    opened = (label_h >= 9) & (label_h < 12)
    closed = (label_h >= 20) & (label_h < 22)
    assert (ex[opened & ~closed] == 1).all() and (ex[closed] == 0).all() and np.isnan(ex[~opened & ~closed]).all()


def test_position_levels_and_legs_meta():
    p = compile_code(_body("c = self.data.pv_close", "self.set_positions(c > 1, position=0.5)", "self.set_positions(c > 2, position=1)",
                           "self.set_positions(c < 0, position=-1)"), register=False)
    assert p.levels == [-1.0, 0.5, 1.0] and p.legs == ["LONG", "SHORT"]
    assert p.meta()["timeframe"] == "24h" and any("timeframe" in w for w in p.warnings)


def test_matches_kernel_values_exactly_on_raw_columns():
    df = _df(400)
    code = _body("c = self.data.pv_close", "h = self.data.pv_high", "l = self.data.pv_low", "e = self.feat.ema(c, timeperiod=30)",
                 "a = self.feat.atr(h, l, c, timeperiod=14)", "r = self.feat.rsi(c, timeperiod=14)", "self.set_positions(c > e + 2.0 * a, position=1)",
                 "self.set_positions(r > 50, position=-1)")
    prog = compile_code(code, register=False)
    ema, atr, rsi = (kernels.compute(df, f"{k}_{n}").to_numpy() for k, n in (("ema", 30), ("atr", 14), ("rsi", 14)))
    c = df["close"].to_numpy()
    with np.errstate(invalid="ignore"):
        want = np.where(c > ema + 2.0 * atr, 1.0, np.nan)
        want = np.where(rsi > 50, -1.0, want)
    np.testing.assert_array_equal(prog.explicit(df), want)


# ─── lỗi: dòng + cột + gợi ý ────────────────────────────────────────────────

@pytest.mark.parametrize("code,line,needle", [
    (_body("close = self.data.pv_close", "self.set_positions((close > 1) and (close < 2), position=1)"), 4, "`and`"),
    (_body("close = self.data.pv_close", "x = not (close > 1)", "self.set_positions(x, position=1)"), 4, "`not`"),
    (_body("close = self.data.pv_close", "self.set_positions(1 < close < 3, position=1)"), 4, "nối chuỗi"),
    (_body("x = self.feat.supertrend(self.data.pv_close)", "self.set_positions(x > 0, position=1)"), 3, "supertrend"),
    (_body("x = self.feat.emaa(self.data.pv_close, 5)", "self.set_positions(x > 0, position=1)"), 3, "Gần đúng: ema"),
    (_body("x = self.op.nonexistent(self.data.pv_close)", "self.set_positions(x > 0, position=1)"), 3, "nonexistent"),
    (_body("c = self.data.pv_close", "self.set_positions(c, position=1)"), 4, "bool"),
    (_body("c = self.data.pv_close", "self.set_positions(c > 1, position=2)"), 4, "[-1, 1]"),
    (_body("c = self.data.pv_close", "self.set_positions(c > 1)"), 4, "position"),
    (_body("c = self.data.pv_close", "y = c.shift(-1)", "self.set_positions(y > 1, position=1)"), 4, "[1, 5000]"),
    (_body("c = self.data.pv_close", "y = c[-1]", "self.set_positions(c > 1, position=1)"), 4, "shift"),
    (_body("c = self.data.pv_close", "y = self.feat.ema(c, timeperiod=0)", "self.set_positions(c > 1, position=1)"), 4, "timeperiod"),
    (_body("c = self.data.pv_close", "y = self.feat.ema(c, period=5)", "self.set_positions(c > 1, position=1)"), 4, "Gần đúng: timeperiod"),
    (_body("c = self.data.pv_close", "y = zzz + 1", "self.set_positions(c > 1, position=1)"), 4, "chưa được gán"),
    (_body("c = self.data.pv_close", "if c > 1:", "    pass", "self.set_positions(c > 1, position=1)"), 4, "if"),
    (_body("c = self.data.pv_close", "for i in range(3):", "    pass"), 4, "for"),
    (_body("c = self.data.pv_close", "x = abs(c)", "self.set_positions(x > 1, position=1)"), 4, "self.op.abs"),
    (_body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)", attrs='    timeframe = "7x"\n'), 2, "timeframe"),
    (_body("c = self.data.pv_volumez", "self.set_positions(c > 1, position=1)"), 3, "pv_"),
    ("import os\nclass S(SimpleAlgorithm):\n    def __algorithm__(self):\n        pass\n", 1, "import"),
    ("class S(SimpleAlgorithm):\n    def __algorithm__(self):\n        x = (\n", 3, "cú pháp"),
    (_body("c = self.data.pv_close", "x = c & 1", "self.set_positions(c > 1, position=1)"), 4, "bool"),
    (_body("c = self.data.pv_close", "a, b = self.feat.macd(c)", "self.set_positions(c > 1, position=1)"), 4, "3 giá trị"),
    (_body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)", "__import__('os')"), 5, ""),
])
def test_errors_carry_line_col_and_message(code, line, needle):
    with pytest.raises(DslError) as ei:
        compile_code(code, register=False)
    e = ei.value
    assert e.line == line, str(e)
    assert e.col and e.col >= 1
    assert needle in e.message, e.message


def test_no_set_positions_is_an_error_and_report_shape():
    rep = compile_report(HEAD + "        x = self.data.pv_close\n")
    assert rep["ok"] is False and rep["error"]["line"] == 2 and rep["error"]["col"] == 5 and rep["program_hash"] is None
    ok = compile_report(_body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)"))
    assert ok["ok"] and len(ok["program_hash"]) == 12 and ok["error"] is None and ok["meta"]["legs"] == ["LONG"]


def test_user_code_is_never_executed(tmp_path):
    marker = tmp_path / "pwned"
    code = _body(f"x = open('{marker}', 'w')", "self.set_positions(self.data.pv_close > 1, position=1)")
    with pytest.raises(DslError):
        compile_code(code, register=False)
    code = _body("self.set_positions(self.data.pv_close > 1, position=1)", f"__import__('os').system('touch {marker}')")
    with pytest.raises(DslError):
        compile_code(code, register=False)
    assert not marker.exists()


# ─── mã băm + đăng ký kernel ────────────────────────────────────────────────

def test_hash_ignores_comments_whitespace_but_not_semantics():
    a = _body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)")
    b = a.replace("c = self.data.pv_close", "# chú thích\n        c   =   self.data.pv_close")
    c = a.replace("> 1", "> 2")
    assert compile_code(a, register=False).code_hash == compile_code(b, register=False).code_hash != compile_code(c, register=False).code_hash


def test_registry_makes_py_columns_visible_to_kernels():
    prog = compile_code(_body("c = self.data.pv_close", "e = self.feat.ema(c, 10)", "self.set_positions(c > e, position=1)"))
    col = prog.column("le")
    assert col.startswith("py_") and kernels.is_kernel_column(col) and kernels.warmup_bars(col) == prog.warmup_bars == 30
    df = _df()
    np.testing.assert_array_equal(kernels.compute(df, col).to_numpy(), prog.columns_for(df)["le"])
    assert kernels.parse_column(col) is None                       # không phải kernel thường
    with pytest.raises(ValueError, match="chưa được đăng ký"):
        kernels.compute(df, "py_" + "0" * 12 + "_le")
    assert kernels.warmup_bars("py_" + "0" * 12 + "_lx") == 0


def test_shared_store_skips_py_columns(tmp_path):
    import golden_scenarios as gs
    from backend.core.backtest import PortfolioEngine
    from backend.optimize.search import evaluate as shared
    gs.write_synthetic_market(tmp_path / "data")
    prog = compile_code(_body("c = self.data.pv_close", "self.set_positions(c > c.shift(1), position=1)", attrs='    timeframe = "1h"\n'))
    plan = profiles.build_plan(prog, ["AAA"], position={"atr_frame": "1h"})
    with gs.data_root_env(str(tmp_path / "data")):
        eng = PortfolioEngine(plan.symbols, plan.strategies, gs.T0, gs.T0 + 5 * gs.DAY, base_frame="1m")
        e, _ = eng._make_trackers(plan.symbols[0], eng.ledger)
        assert shared.plan(e) is None


# ─── hồ sơ thực thi ─────────────────────────────────────────────────────────

LONG_HALF = _body("c = self.data.pv_close", "self.set_positions(c > 0, position=0.5)")


def test_plan_defaults_overrides_and_validation():
    prog = compile_code(_body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)", attrs="    stop_loss_rate = 2.5\n"), register=False)
    plan = profiles.build_plan(prog, ["BTC", "ETH"], position={"risk_per_trade_pct": 1.0})
    st = plan.strategies[0]
    assert plan.symbols == ["BTC@perp", "ETH@perp"] and plan.base_frame == "1m" and "symbols" not in st
    assert st["position"]["stop_loss_rate"] == 2.5 and st["position"]["risk_per_trade_pct"] == 1.0 and st["position"]["cooldown"] == 60
    assert any("mặc định" in w for w in plan.warnings)
    with pytest.raises(ValueError, match="khoá vị thế"):
        profiles.build_plan(prog, ["BTC"], position={"nope": 1})
    with pytest.raises(ValueError, match="khung chạy"):
        profiles.build_plan(prog, ["BTC"], position={"atr_frame": "15m"}, run_frame="1h")
    both = compile_code(_body("c = self.data.pv_close", "self.set_positions(c > 1, position=1)", "self.set_positions(c < 0, position=-1)"), register=False)
    assert [s["side"] for s in profiles.build_plan(both, ["BTC"]).strategies] == ["LONG", "SHORT"]
