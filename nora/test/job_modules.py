"""File của các module job (có run_job(params)) để test nạp lại một bản riêng từ file (tên ngắn cũ -> đường dẫn mới)."""
import os

# P9.6: (file mới, tên hàm job) — mỗi file giờ chứa nhiều job (run_job đã đổi tên run_<kind>); job_path dựng một file bọc nạp nguyên file đích
# (giữ __file__ thật để đường dẫn tính từ __file__ đúng) rồi gán `run_job = <hàm job>`, nên test cũ vẫn gọi module.run_job(...).
JOB_FILES = {
    "build_strategy_book": ("optimize/book/build.py", "run_book_build"),
    "validate_book": ("optimize/process/tasks.py", "run_book_wfa"),
    "run_book_backtest": ("optimize/process/tasks.py", "run_book_backtest"),
    "run_funnel": ("optimize/funnel/stages.py", "run_funnel_run"),
    "promote_staging": ("core/data/promote.py", "run_job"),
}
# Module mang dữ liệu sổ chiến lược dùng chung (UNIVERSE / CANDIDATES / GATES...): test monkeypatch BẢN CHÍNH (backend.optimize.book.build), nên bản bọc phải
# trỏ vào đúng module đó chứ không nạp thêm một bản riêng (bản riêng sẽ có UNIVERSE / CANDIDATES riêng, không thấy monkeypatch).
SHARED_MODULES = {"build_strategy_book": "backend.optimize.book.build"}
_WRAP_DIR = []


def job_path(name: str) -> str:
    rel, func = JOB_FILES[name]
    real = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", *rel.split("/")))
    if func == "run_job":
        return real
    if not _WRAP_DIR:
        import tempfile
        _WRAP_DIR.append(tempfile.mkdtemp(prefix="job_modules_"))
    path = os.path.join(_WRAP_DIR[0], f"{name}.py")
    with open(path, "w", encoding="utf-8") as fh:
        if name in SHARED_MODULES:
            fh.write(f"import importlib\n_m = importlib.import_module({SHARED_MODULES[name]!r})\n"
                     f"globals().update({{k: v for k, v in vars(_m).items() if not (k.startswith('__') and k.endswith('__'))}})\nrun_job = _m.{func}\n")
            return path
        fh.write(f"__file__ = {real!r}\nexec(compile(open(__file__, encoding='utf-8').read(), __file__, 'exec'))\nrun_job = {func}\n")
    return path


def launched(call):
    """(kind, params) của một lần batch.launch đã ghi lại bởi FakePopen: cmd = [run_limited.sh, "--", "-m", runner, job_dir]."""
    import json
    cmd = call[0]
    assert cmd[1:4] == ["--", "-m", "backend.optimize.process.process"], cmd
    with open(os.path.join(cmd[4], "params.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    return spec["kind"], spec["params"]
