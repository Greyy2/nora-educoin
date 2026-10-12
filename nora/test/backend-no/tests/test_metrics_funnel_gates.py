# Đã chuyển khỏi test/ (P17 T1-B5c): cổng phễu (funnel/stages) đã gỡ; bản gốc ở tag pre-p17-research.
def test_funnel_gates_do_not_read_win_rate_or_profit_factor():
    """P9.11: win_rate/PF thành None khi không xác định — an toàn vì không cổng phễu nào đọc chúng. Nếu sau này có cổng đọc PF,
    "không có lệnh thua" (profit_factor_note == NOTE_NO_LOSSES) phải được coi là ĐẠT (hành vi cũ PF = 99) — test này sẽ nhắc."""
    import inspect

    from backend import XXstages as gates
    # P9.10b: cổng đã gộp vào optimize/funnel/stages.py (cùng file với mã chạy phễu/hiển thị đọc win_rate/PF) -> chỉ quét các hàm cổng evaluate_*
    src = "".join(inspect.getsource(getattr(gates, n)) for n in ("evaluate_s1", "evaluate_dsr", "evaluate_neighbour", "evaluate_s3", "evaluate_mc_checks", "evaluate_s6",
                                                                   "dsr_cut", "thresholds_snapshot", "_msg", "reason_label"))
    assert "profit_factor" not in src and "win_rate" not in src
    base = {"ret_pct": 5.0, "mdd_pct": 5.0, "trades": 500, "symbols_positive": 8}
    assert gates.evaluate_s1({**base, "profit_factor": None, "win_rate": None}) == gates.evaluate_s1({**base, "profit_factor": 99.0, "win_rate": 100.0})
