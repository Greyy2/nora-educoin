# Đã chuyển khỏi test/ (P17 T1-B5c): job book_build / funnel_run đã gỡ khỏi vòng đời; bản gốc ở tag pre-p17-research.
"""ADR-P9 §4 bước 2–3: ghi kết quả lâu dài khi job xong, dọn process, giữ log job lỗi 7 ngày, ngoại lệ chạy tạm."""
import json
import os
import time
import pytest
from backend.jobs import runner as bj


def test_wfa_links_report_and_build_keeps_alphas_and_funnel_record(home):
    w = _job(home, A, "book_wfa", result={"report_path": str(home / "wfa" / "20261007_0900" / "report.json")})
    b = _job(home, B, "book_build", result={"run_dir": "x"}, extra={"alphas": "{}"})
    f = _job(home, C, "funnel_run", result={"ok": 1})
    for d in (w, b, f):
        bj._finish(str(d), 0)
    assert json.load(open(home / "wfa" / A / "job.json"))["report_dir"] == str(home / "wfa" / "20261007_0900")
    assert (home / "alpha" / "book" / B / "alphas" / "book.json").is_file()
    assert (home / "alpha" / "funnel" / C / "job.json").is_file()
    assert bj.job_dir(B) == str(home / "alpha" / "book" / B) and bj.status(C)["status"] == "done"
    assert not any((home / "cache" / "process").iterdir())
