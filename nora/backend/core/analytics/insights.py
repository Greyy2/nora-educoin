"""Bộ quy tắc sinh nhận xét và chẩn đoán chiến lược (B4 — lớp thực tế, không dùng LLM).

QUY TẮC: mỗi câu nhận xét phải truy được về MỘT con số đo thật trong `diagnostics` (core/metrics/diagnose.py) của chính lần chạy; `evidence` ghi đúng các giá trị đã dùng
để kích hoạt và để viết câu (không số giả, không ngưỡng ngầm trên trường không tồn tại). Đầu vào thiếu (None / available False) -> quy tắc không kích hoạt.

Mỗi quy tắc: id, severity ("warning" | "good" | "info"), hàm (diag, metrics) -> (message_vi, evidence) hoặc None.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

BETA_DRIVEN_ID = "beta_driven"   # nguồn duy nhất: checklist của user_alphas.evaluate_checklist và PushToAlphaModal.jsx (cùng chuỗi) dựa vào id này
SEVERITY_ORDER = {"warning": 0, "good": 1, "info": 2}
Result = Optional[Tuple[str, Dict[str, Any]]]


class InsightRule:
    def __init__(self, rule_id: str, severity: str, builder: Callable[[Dict[str, Any], Dict[str, Any]], Result]):
        self.id = rule_id
        self.severity = severity
        self.builder = builder


RULES: List[InsightRule] = []


def register_rule(rule_id: str, severity: str):
    def decorator(fn):
        RULES.append(InsightRule(rule_id, severity, fn))
        return fn
    return decorator


def _g(d: Dict[str, Any], *path, default=None):
    """d[path0][path1]... an toàn; thiếu / None -> default."""
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or cur.get(p) is None:
            return default
        cur = cur[p]
    return cur


def _nums(*vals) -> bool:
    return all(isinstance(v, (int, float)) for v in vals)


def _exit_share_closed(d: Dict[str, Any], cat: str) -> Optional[Tuple[float, int, int]]:
    """(% lệnh ĐÃ ĐÓNG thoát vì `cat`, số lệnh, số lệnh đã đóng). Lệnh đang mở cuối kỳ không tính vào mẫu số."""
    sig = d.get("signal_activity", {})
    closed = sig.get("closed_trades") or 0
    if closed <= 0:
        return None
    n = (sig.get("exit_reason_counts") or {}).get(cat, 0)
    return n / closed * 100.0, n, closed


# ─── Quy tắc ────────────────────────────────────────────────────────────────

@register_rule(BETA_DRIVEN_ID, "warning")
def rule_beta_driven(d, m):
    mkt = d.get("market_comparison", {})
    if not mkt.get("available"):
        return None
    beta, corr, s_cagr, m_cagr, excess = (mkt.get(k) for k in ("beta", "correlation", "strategy_cagr", "market_cagr", "excess_cagr"))
    if _nums(beta, corr, s_cagr, m_cagr, excess) and corr >= 0.9 and beta >= 0.8:
        return (f"Kết quả bám sát nhịp thị trường: beta {beta:.2f} và tương quan {corr:.2f} với benchmark luôn long; CAGR chiến lược {s_cagr:.1f}%/năm so với "
                f"{m_cagr:.1f}%/năm của benchmark (chênh {excess:+.1f} điểm %/năm).",
                {"beta": beta, "correlation": corr, "strategy_cagr": s_cagr, "market_cagr": m_cagr, "excess_cagr": excess})
    return None


@register_rule("overfit_gap", "warning")
def rule_overfit_gap(d, m):
    tr_s, te_s = _g(d, "train_vs_test", "train_sharpe"), _g(d, "train_vs_test", "test_sharpe")
    if _nums(tr_s, te_s) and tr_s >= 0.8 and te_s < 0.5 * tr_s:
        decay = (1.0 - te_s / tr_s) * 100.0
        return (f"Hiệu quả giảm mạnh ngoài mẫu (Sharpe train {tr_s:.2f} → test {te_s:.2f}, suy giảm {decay:.0f}%); có dấu hiệu quá khớp dữ liệu (overfitting).",
                {"train_sharpe": tr_s, "test_sharpe": te_s, "decay_pct": round(decay, 1)})
    return None


@register_rule("fee_drag", "warning")
def rule_fee_drag(d, m):
    pnl = d.get("pnl_structure", {})
    drag = pnl.get("fee_drag_pct")
    if _nums(drag) and drag >= 20.0:
        return (f"Phí giao dịch ăn {drag:.1f}% lãi gộp trước phí ({pnl.get('fees_usd'):,.0f} USD phí trên {pnl.get('gross_pnl_before_fees_usd'):,.0f} USD lãi gộp); "
                "tần suất ra vào lệnh đang làm mòn đáng kể lợi nhuận ròng.",
                {"fee_drag_pct": drag, "fees_usd": pnl.get("fees_usd"), "gross_pnl_before_fees_usd": pnl.get("gross_pnl_before_fees_usd")})
    return None


@register_rule("tail_dependent", "warning")
def rule_tail_dependent(d, m):
    pnl = d.get("pnl_structure", {})
    top5, closed = pnl.get("top5_profit_pct"), pnl.get("closed_trades", 0)
    if _nums(top5) and closed >= 12 and top5 >= 50.0:
        return (f"Lợi nhuận phụ thuộc lớn vào vài cơ hội cá biệt (5 lệnh thắng lớn nhất đóng góp {top5:.1f}% tổng lãi gộp của {closed} lệnh đã đóng).",
                {"top5_profit_pct": top5, "closed_trades": closed})
    return None


@register_rule("rarely_in_market", "info")
def rule_rarely_in_market(d, m):
    sig = d.get("signal_activity", {})
    days = sig.get("days_in_market_pct")
    if _nums(days) and days < 10.0 and sig.get("total_trades", 0) > 0:
        return (f"Chiến lược hiếm khi có vị thế: chỉ {days:.1f}% số ngày có ít nhất một vị thế mở (exposure trung bình {sig.get('avg_exposure_pct')}% vốn, "
                f"{sig.get('total_trades')} lệnh).",
                {"days_in_market_pct": days, "avg_exposure_pct": sig.get("avg_exposure_pct"), "total_trades": sig.get("total_trades")})
    return None


@register_rule("always_in", "info")
def rule_always_in(d, m):
    sig = d.get("signal_activity", {})
    days, expo = sig.get("days_in_market_pct"), sig.get("avg_exposure_pct")
    if _nums(days) and days >= 95.0:
        tail = f", exposure trung bình {expo:.1f}% vốn" if _nums(expo) else ""
        return (f"Chiến lược gần như luôn có vị thế ({days:.1f}% số ngày có ít nhất một vị thế mở{tail}).",
                {"days_in_market_pct": days, "avg_exposure_pct": expo})
    return None


@register_rule("bear_loss", "warning")
def rule_bear_loss(d, m):
    reg = d.get("regime_analysis", {})
    if not reg.get("available"):
        return None
    bear, bull, cap = reg.get("bear", {}), reg.get("bull", {}), reg.get("initial_capital")
    bp, bu, bd = bear.get("pnl_usd"), bull.get("pnl_usd"), bear.get("days", 0)
    if _nums(bp, bu, cap) and bd >= 30 and bp < 0 and bu > 0 and abs(bp) >= 0.05 * cap:
        return (f"Thua lỗ tập trung khi thị trường dưới SMA200: {bp:,.0f} USD trong {bd} ngày giá {reg.get('market')} dưới SMA{reg.get('sma_days')} "
                f"(trong khi {bull.get('days')} ngày trên SMA200 lãi {bu:,.0f} USD).",
                {"bear_pnl_usd": bp, "bear_days": bd, "bull_pnl_usd": bu, "bull_days": bull.get("days"), "initial_capital": cap,
                 "benchmark_bear_pnl_usd": bear.get("benchmark_pnl_usd"), "market": reg.get("market")})
    return None


@register_rule("positive_bear_performance", "good")
def rule_positive_bear(d, m):
    reg = d.get("regime_analysis", {})
    if not reg.get("available"):
        return None
    bear = reg.get("bear", {})
    bp, bd, mkt_ret, inm = bear.get("pnl_usd"), bear.get("days", 0), bear.get("market_return_pct"), bear.get("days_in_market_pct")
    if _nums(bp, mkt_ret, inm) and bd >= 30 and bp > 0 and mkt_ret < 0 and inm >= 10.0:
        return (f"Có lãi khi thị trường yếu: +{bp:,.0f} USD trong {bd} ngày giá {reg.get('market')} dưới SMA{reg.get('sma_days')}, lúc thị trường giảm "
                f"{mkt_ret:.1f}% (chiến lược có vị thế {inm:.0f}% số ngày đó).",
                {"bear_pnl_usd": bp, "bear_days": bd, "bear_market_return_pct": mkt_ret, "bear_days_in_market_pct": inm, "market": reg.get("market")})
    return None


@register_rule("high_win_rate", "good")
def rule_high_win_rate(d, m):
    pnl = d.get("pnl_structure", {})
    wr, payoff, closed = pnl.get("win_rate"), pnl.get("payoff"), pnl.get("closed_trades", 0)
    if _nums(wr) and wr >= 65.0 and closed >= 10:
        tail = f", tỷ lệ lãi/lỗ trung bình (payoff) {payoff:.2f}" if _nums(payoff) else ""
        return (f"Tỷ lệ lệnh thắng cao ({wr:.1f}% trên {closed} lệnh đã đóng{tail}).", {"win_rate": wr, "payoff": payoff, "closed_trades": closed})
    return None


@register_rule("low_win_rate_trend", "info")
def rule_trend_payoff(d, m):
    pnl = d.get("pnl_structure", {})
    wr, payoff, closed = pnl.get("win_rate"), pnl.get("payoff"), pnl.get("closed_trades", 0)
    if _nums(wr, payoff) and wr < 40.0 and payoff >= 2.0 and closed >= 10:
        return (f"Đặc trưng bắt sóng xu hướng lớn: tỷ lệ thắng thấp ({wr:.1f}%) nhưng payoff cao ({payoff:.2f}) trên {closed} lệnh đã đóng.",
                {"win_rate": wr, "payoff": payoff, "closed_trades": closed})
    return None


@register_rule("drawdown_heavy", "warning")
def rule_drawdown_heavy(d, m):
    mkt = d.get("market_comparison", {})
    mdd, m_mdd = mkt.get("strategy_mdd"), mkt.get("market_mdd")
    if _nums(mdd) and mdd >= 35.0:
        tail = f" (benchmark luôn long: {m_mdd:.1f}%)" if _nums(m_mdd) else ""
        return (f"Mức sụt giảm tối đa theo ngày khá sâu ({mdd:.1f}%){tail}; cần cơ chế cắt lỗ hoặc kiểm soát tỷ trọng vốn.",
                {"max_drawdown_pct": mdd, "market_mdd_pct": m_mdd})
    return None


@register_rule("high_consecutive_losses", "warning")
def rule_consec_losses(d, m):
    losses = _g(d, "pnl_structure", "max_consecutive_losses", default=0)
    if losses >= 6:
        return (f"Chuỗi thua liên tiếp dài nhất lên tới {losses} lệnh đã đóng; cần chuẩn bị chịu đựng chuỗi thua này.", {"max_consecutive_losses": losses})
    return None


@register_rule("low_trade_count", "warning")
def rule_low_trade_count(d, m):
    sig = d.get("signal_activity", {})
    total = sig.get("total_trades", 0)
    if 0 < total < 20:
        return (f"Số lệnh chưa nhiều ({total} lệnh: {sig.get('closed_trades')} đã đóng, {sig.get('open_trades')} đang mở); mẫu thống kê có thể chưa đủ lớn để loại trừ may rủi.",
                {"total_trades": total, "closed_trades": sig.get("closed_trades"), "open_trades": sig.get("open_trades")})
    return None


@register_rule("strong_alpha", "good")
def rule_strong_alpha(d, m):
    mkt = d.get("market_comparison", {})
    if not mkt.get("available"):
        return None
    corr, excess, te_s = mkt.get("correlation"), mkt.get("excess_cagr"), _g(d, "train_vs_test", "test_sharpe")
    if _nums(corr, excess, te_s) and corr <= 0.65 and excess > 0 and te_s >= 0.9:
        return (f"Tín hiệu có tính độc lập với thị trường: tương quan với benchmark thấp ({corr:.2f}), CAGR vượt benchmark {excess:+.1f} điểm %/năm, Sharpe ngoài mẫu {te_s:.2f}.",
                {"correlation": corr, "excess_cagr": excess, "test_sharpe": te_s})
    return None


@register_rule("robust_oos", "good")
def rule_robust_oos(d, m):
    tst = d.get("train_vs_test", {})
    decay, te_s, tr_s = tst.get("sharpe_decay"), tst.get("test_sharpe"), tst.get("train_sharpe")
    if _nums(decay, te_s, tr_s) and decay >= 0.8 and te_s >= 1.0 and tr_s >= 1.0:
        return (f"Hiệu quả ngoài mẫu vững: Sharpe test {te_s:.2f} (giữ {decay * 100:.0f}% so với train {tr_s:.2f}).",
                {"train_sharpe": tr_s, "test_sharpe": te_s, "sharpe_decay": decay})
    return None


@register_rule("sl_dominant_exit", "warning")
def rule_sl_dominant(d, m):
    r = _exit_share_closed(d, "stop_loss")
    if r and r[2] >= 10 and r[0] >= 40.0:
        return (f"{r[0]:.1f}% lệnh đã đóng ({r[1]}/{r[2]}) thoát bằng Stop-Loss thật của engine; cần xem lại điều kiện vào lệnh hoặc khoảng dừng lỗ.",
                {"stop_loss_pct_of_closed": round(r[0], 1), "stop_loss_trades": r[1], "closed_trades": r[2]})
    return None


@register_rule("tp_dominant_exit", "good")
def rule_tp_dominant(d, m):
    r = _exit_share_closed(d, "take_profit")
    if r and r[2] >= 10 and r[0] >= 45.0:
        return (f"{r[0]:.1f}% lệnh đã đóng ({r[1]}/{r[2]}) chạm Take-Profit.",
                {"take_profit_pct_of_closed": round(r[0], 1), "take_profit_trades": r[1], "closed_trades": r[2]})
    return None


@register_rule("kill_switch_hit", "warning")
def rule_kill_switch(d, m):
    n = _g(d, "signal_activity", "exit_reason_counts", "kill_switch", default=0)
    if n > 0:
        return (f"Kill-switch danh mục đã đóng {n} vị thế (vốn sụt tới ngưỡng dừng giao dịch).", {"kill_switch_trades": n})
    return None


@register_rule("negative_excess", "warning")
def rule_negative_excess(d, m):
    mkt = d.get("market_comparison", {})
    excess, s_cagr, m_cagr = mkt.get("excess_cagr"), mkt.get("strategy_cagr"), mkt.get("market_cagr")
    if mkt.get("available") and _nums(excess, s_cagr, m_cagr) and excess < -5.0:
        return (f"Kém hơn việc nắm giữ thụ động: CAGR {s_cagr:.1f}%/năm so với {m_cagr:.1f}%/năm của benchmark luôn long (chênh {excess:.1f} điểm %/năm).",
                {"excess_cagr": excess, "strategy_cagr": s_cagr, "market_cagr": m_cagr})
    return None


@register_rule("concentrated_coin", "warning")
def rule_concentrated_coin(d, m):
    by_coin = _g(d, "pnl_structure", "by_coin", default={})
    if len(by_coin) > 1:
        total = sum(v for v in by_coin.values() if v > 0)
        if total > 0:
            top_sym, top_val = max(by_coin.items(), key=lambda x: x[1])
            share = top_val / total * 100.0
            if share >= 65.0:
                return (f"Lãi tập trung vào {top_sym} ({share:.1f}% tổng lãi các coin có lãi, {top_val:,.0f} USD, gồm lệnh đang mở theo giá cuối).",
                        {"top_coin": top_sym, "share_pct": round(share, 1), "top_coin_pnl_usd": top_val})
    return None


@register_rule("short_profitable", "good")
def rule_short_profitable(d, m):
    pnl = d.get("pnl_structure", {})
    n, p = pnl.get("short_closed_trades", 0), pnl.get("short_pnl_usd")
    if n >= 5 and _nums(p) and p > 0:
        return (f"Chiều Short có lãi: {p:,.0f} USD từ {n} lệnh short đã đóng.", {"short_closed_trades": n, "short_pnl_usd": p})
    return None


@register_rule("short_losing", "warning")
def rule_short_losing(d, m):
    pnl = d.get("pnl_structure", {})
    n, p = pnl.get("short_closed_trades", 0), pnl.get("short_pnl_usd")
    if n >= 5 and _nums(p) and p < 0:
        return (f"Chiều Short đang lỗ: {p:,.0f} USD từ {n} lệnh short đã đóng.", {"short_closed_trades": n, "short_pnl_usd": p})
    return None


@register_rule("only_long_bias", "info")
def rule_only_long(d, m):
    sig = d.get("signal_activity", {})
    shorts, longs = sig.get("short_trades", 0), sig.get("long_trades", 0)
    if shorts == 0 and longs > 0:
        return (f"Chiến lược chỉ tham gia chiều Long ({longs} lệnh, 0 lệnh short).", {"long_trades": longs, "short_trades": shorts})
    return None


@register_rule("binding_condition", "info")
def rule_binding_condition(d, m):
    """Vế duy nhất chặn >= 50% số nến 'suýt đủ điều kiện' (đúng mọi vế trừ một) của quy tắc vào lệnh có >= 3 vế A & B & C."""
    bc = d.get("binding_condition", {})
    if not bc.get("available"):
        return None
    best = None
    for r in bc.get("rules", []):
        b = r.get("binding")
        if r.get("n_conjuncts", 0) >= 3 and b and r.get("near_miss_bars", 0) >= 20 and _nums(b.get("share_of_near_miss_pct")) and b["share_of_near_miss_pct"] >= 50.0:
            if best is None or b["share_of_near_miss_pct"] > best[1]["share_of_near_miss_pct"]:
                best = (r, b)
    if best is None:
        return None
    r, b = best
    return (f"Điều kiện vào lệnh \"{b['text_vi']}\" (quy tắc dòng {r['line']}, {r['n_conjuncts']} vế) là vế DUY NHẤT sai trong {b['share_of_near_miss_pct']:.0f}% số nến suýt đủ điều kiện "
            f"({b['only_false_bars']}/{r['near_miss_bars']} nến); vế này chỉ đúng {b['pct_true']:.1f}% số nến.",
            {"rule_index": r["index"], "line": r["line"], "side": r["side"], "n_conjuncts": r["n_conjuncts"], "conjunct": b["text_vi"], "conjunct_index": b["index"],
             "pct_true": b["pct_true"], "only_false_bars": b["only_false_bars"], "near_miss_bars": r["near_miss_bars"], "all_true_bars": r.get("all_true_bars"),
             "share_of_near_miss_pct": b["share_of_near_miss_pct"]})


def generate_insights(diagnostics: Dict[str, Any], metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chạy toàn bộ bộ quy tắc, sắp theo mức độ: warning -> good -> info (giữ thứ tự khai báo trong cùng mức)."""
    results: List[Dict[str, Any]] = []
    for rule in RULES:
        try:
            out = rule.builder(diagnostics, metrics)
        except Exception:      # noqa: BLE001 — một quy tắc lỗi không làm mất các nhận xét khác
            continue
        if out is not None:
            message, evidence = out
            results.append({"id": rule.id, "severity": rule.severity, "message_vi": message, "evidence": evidence})
    results.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 99))
    return results
