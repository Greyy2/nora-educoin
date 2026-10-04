"""Unit systemd của Nora: restart API không được giết job nền (job là tiến trình con của nora-api.service)."""
import os

OPS = os.path.join(os.path.dirname(__file__), "..", "backend", "utils", "ops", "systemd")


def _directives(name):
    with open(os.path.join(OPS, name), encoding="utf-8") as fh:
        return dict(ln.split("=", 1) for ln in (x.strip() for x in fh) if ln and not ln.startswith(("#", "[")) and "=" in ln)


def test_api_unit_restart_keeps_background_jobs():
    d = _directives("nora-api.service.in")
    assert d["KillMode"] == "process"           # chỉ dừng uvicorn; job đang chạy/đang xếp hàng sống tiếp
    assert d["Slice"] == "nora.slice" and d["MemoryMax"] == "3G"


def test_job_launcher_points_at_existing_run_limited_and_modules():
    import importlib
    from backend.api.jobs import batch
    assert os.access(batch.RUN_LIMITED, os.X_OK)
    for kind, spec in batch.KINDS.items():
        importlib.import_module(spec["module"])          # mọi loại job trỏ tới module có thật


def test_backend_has_only_planned_packages():
    root = os.path.join(os.path.dirname(__file__), "..", "backend")
    pkgs = {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and not d.startswith(("_", "."))}
    assert pkgs == {"api", "carlo", "core", "db", "live", "optimize", "utils", "wfa"}   # live: bot theo sổ (E9)


def test_resume_code_fingerprint_files_exist():
    from backend.optimize import store as results_store
    root = os.path.join(os.path.dirname(__file__), "..")
    missing = [f for f in results_store._CODE_FILES if not os.path.isfile(os.path.join(root, f))]
    assert not missing        # file đổi tên mà quên cập nhật -> khoá resume không còn theo dõi mã thật
