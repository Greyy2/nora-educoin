"""Unit systemd của Nora: restart API không được giết job nền (job là tiến trình con của nora-api.service)."""
import os

OPS = os.path.join(os.path.dirname(__file__), "..", "backend", "ops", "systemd")


def _directives(name):
    with open(os.path.join(OPS, name), encoding="utf-8") as fh:
        return dict(ln.split("=", 1) for ln in (x.strip() for x in fh) if ln and not ln.startswith(("#", "[")) and "=" in ln)


def test_api_unit_restart_keeps_background_jobs():
    d = _directives("nora-api.service.in")
    assert d["KillMode"] == "process"           # chỉ dừng uvicorn; job đang chạy/đang xếp hàng sống tiếp
    assert d["Slice"] == "nora.slice" and d["MemoryMax"] == "3G"
