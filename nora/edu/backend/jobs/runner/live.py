"""Nora EDU Live Stub — Cấm tuyệt đối giao dịch trực tiếp và truy cập sàn trong Nora EDU."""

def run_live_bot(*args, **kwargs):
    raise PermissionError("Live bot execution is strictly prohibited in Nora EDU.")

def running_live_bot_info():
    return None

def enforce_lifecycle():
    """No-op trong EDU vì EDU không có live bot supervision."""
    pass

def build_chart(*args, **kwargs):
    return {}

def resolve_live_source(*args, **kwargs):
    raise PermissionError("Live bot execution is strictly prohibited in Nora EDU.")

def launch_fingerprint(*args, **kwargs):
    return ""

def supervise_once(*args, **kwargs):
    return {}

def match_fills(*args, **kwargs):
    return []

__all__ = [
    "run_live_bot",
    "running_live_bot_info",
    "enforce_lifecycle",
    "build_chart",
    "resolve_live_source",
    "launch_fingerprint",
    "supervise_once",
    "match_fills",
]
