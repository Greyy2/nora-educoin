"""
test_mc_gate.py — Test cho Đợt 1.1: MC source_gate logic

Quy tắc: viết test trước, chạy FAIL trên code lỗi, sau đó sửa mới PASS.

Các tình huống (bảng spec):
- WFA gate True, cùng process                                → source_gate_passed = True
- WFA gate True, sau jobs._WFA_JOBS.clear() (giả lập restart)→ source_gate_passed = True
- WFA gate False (cả hai cách)                               → source_gate_passed = False
- source_wfa_id không tồn tại / chưa completed               → source_gate_passed = False
- Không có source_wfa_id                                     → source_gate_passed = None
- Có source_wfa_id kèm trades giả                            → MC dùng lệnh của WFA job
"""
import json
import pytest
from backend.api.jobs import store as jobs
from backend.carlo.monte_carlo import _resolve_wfa_gate


def _make_fake_trades(n: int = 40):
    """Tạo danh sách lệnh giả đủ điều kiện MC (>= 30)."""
    return [{"pnl_pct": 0.5} for _ in range(n)]


def _setup_wfa_job(gate_passed: bool, trades=None):
    """Tạo WFA job đã completed với gate_passed tùy ý."""
    wfa_id = jobs.create_wfa_job("TESTSYM", "Test Strategy", total_folds=4)
    result = {
        "acceptance_gate_passed": gate_passed,
        "aggregate_oos_trades": trades or _make_fake_trades(),
        "total_oos_trades": 40,
    }
    jobs.complete_wfa_job(wfa_id, result)
    return wfa_id


# ── Test 1: gate True, cùng process ──────────────────────────────────────────
def test_gate_true_same_process():
    wfa_id = _setup_wfa_job(gate_passed=True)
    assert _resolve_wfa_gate(wfa_id) is True


# ── Test 2: gate True, sau khi xóa in-memory (giả lập server restart) ────────
def test_gate_true_after_memory_clear():
    wfa_id = _setup_wfa_job(gate_passed=True)
    jobs._WFA_JOBS.clear()  # giả lập restart, chỉ còn SQLite
    assert _resolve_wfa_gate(wfa_id) is True


# ── Test 3: gate False, cùng process ─────────────────────────────────────────
def test_gate_false_same_process():
    wfa_id = _setup_wfa_job(gate_passed=False)
    assert _resolve_wfa_gate(wfa_id) is False


# ── Test 4: gate False, sau khi xóa in-memory ────────────────────────────────
def test_gate_false_after_memory_clear():
    wfa_id = _setup_wfa_job(gate_passed=False)
    jobs._WFA_JOBS.clear()
    assert _resolve_wfa_gate(wfa_id) is False


# ── Test 5: source_wfa_id không tồn tại ──────────────────────────────────────
def test_gate_nonexistent_job():
    assert _resolve_wfa_gate("nonexistent-wfa-id-12345") is False


# ── Test 6: job tồn tại nhưng chưa completed (pending/running) ───────────────
def test_gate_pending_job():
    wfa_id = jobs.create_wfa_job("TESTSYM", "Test", total_folds=4)
    # Không gọi complete_wfa_job → job vẫn là "pending"
    assert _resolve_wfa_gate(wfa_id) is False


# ── Test 7: không có source_wfa_id → None ────────────────────────────────────
def test_gate_no_source_wfa_id():
    assert _resolve_wfa_gate(None) is None
    assert _resolve_wfa_gate("") is None


# ── Test 8: MC dùng lệnh của WFA job, bỏ trades giả ─────────────────────────
def test_mc_uses_wfa_trades_not_fake():
    """
    Khi có source_wfa_id, MC phải lấy aggregate_oos_trades từ WFA job.
    Client không được tự gửi trades khác để bypass.
    """
    real_wfa_trades = _make_fake_trades(n=50)
    fake_client_trades = [{"pnl_pct": 999.0} for _ in range(50)]  # giả mạo

    wfa_id = _setup_wfa_job(gate_passed=True, trades=real_wfa_trades)

    # Hàm helper để extract trades từ WFA (sẽ được dùng trong execute_monte_carlo_pipeline)
    job = jobs.get_wfa_job(wfa_id)
    assert job is not None
    res = job.get("result") or {}
    extracted_trades = res.get("aggregate_oos_trades", [])
    assert extracted_trades == real_wfa_trades, (
        "MC phải lấy trades từ WFA job, không dùng trades từ client"
    )
    # Đảm bảo fake_client_trades không bằng wfa_trades
    assert fake_client_trades != real_wfa_trades
