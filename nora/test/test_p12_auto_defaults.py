"""P12-B: atr_frame / cooldown không khai báo = "auto" -> theo khung tín hiệu của chiến lược; khai báo tường minh giữ nguyên."""
import backend  # noqa: F401  (đăng ký nguồn dữ liệu cho build_plan)
from backend.alpha.compile import annotate_report, compile_code, explain_program
from backend.alpha.plan import build_plan
from backend.analys.param import BASE_POSITION, materialize, resolve_position_auto

CODE = '''class S(SimpleAlgorithm):
    timeframe = "{tf}"
    stop_loss_rate = 3.0
    risk_per_trade_pct = 0.5
{extra}
    def __algorithm__(self):
        close = self.data.pv_close
        ema = self.feat.ema(close, 20)
        self.set_positions(close < ema, position=0.0)
        self.set_positions(self.op.crossed_above(close, ema), position=1.0)
'''


def _prog(tf, extra=""):
    return compile_code(CODE.format(tf=tf, extra=extra), register=False)


def test_base_position_is_auto():
    assert BASE_POSITION["atr_frame"] == "auto" and BASE_POSITION["cooldown"] == "auto"


def test_resolver():
    r = resolve_position_auto(BASE_POSITION, "24h")
    assert (r["atr_frame"], r["cooldown"]) == ("24h", 1440)
    r = resolve_position_auto(BASE_POSITION, "1h")
    assert (r["atr_frame"], r["cooldown"]) == ("1h", 60)
    r = resolve_position_auto({**BASE_POSITION, "atr_frame": "4h", "cooldown": 0}, "24h")   # tường minh (kể cả 0) giữ nguyên
    assert (r["atr_frame"], r["cooldown"]) == ("4h", 0)
    assert resolve_position_auto(BASE_POSITION)["cooldown"] == 60       # không biết khung: mặc định cũ


def test_book_materialize_keeps_legacy_defaults():
    st = materialize({"id": "x", "side": "LONG", "tree": [], "position": {}}, {})
    assert (st["position"]["atr_frame"], st["position"]["cooldown"]) == ("1h", 60)


def test_plan_24h_resolves_from_signal_frame():
    pos = build_plan(_prog("24h"), ["BTC@perp"]).strategies[0]["position"]
    assert (pos["atr_frame"], pos["cooldown"]) == ("24h", 1440)


def test_plan_1h_same_as_old_default():
    pos = build_plan(_prog("1h"), ["BTC@perp"]).strategies[0]["position"]
    assert (pos["atr_frame"], pos["cooldown"]) == ("1h", 60)


def test_plan_explicit_unchanged():
    # B7: chiến lược 24h có atr_frame="4h" cần chạy ở khung <= 4h (ở đây truyền run_frame="1m" / Chuẩn)
    pos = build_plan(_prog("24h", '    atr_frame = "4h"\n    cooldown = 0\n'), ["BTC@perp"], run_frame="1m").strategies[0]["position"]
    assert (pos["atr_frame"], pos["cooldown"]) == ("4h", 0)


def _card(ex, title):
    return next(c["desc"] for c in ex["execution"] if c["title"] == title)


def test_explain_shows_resolved_values():
    desc = _card(explain_program(_prog("24h")), "Quản trị rủi ro")
    assert "khung 24h" in desc and "1440 phút" in desc
    desc = _card(explain_program(_prog("24h", '    atr_frame = "4h"\n    cooldown = 30\n')), "Quản trị rủi ro")
    assert "khung 4h" in desc and "30 phút" in desc


def test_annotate_timeframe_comment():
    out = annotate_report(CODE.format(tf="24h", extra=""), as_comments=True)
    assert "ATR khung 24h" in out["annotated_code"] and "1440" in out["annotated_code"]
    out = annotate_report(CODE.format(tf="24h", extra='    atr_frame = "4h"\n    cooldown = 30\n'), as_comments=True)
    assert "ATR khung 24h" not in out["annotated_code"]
